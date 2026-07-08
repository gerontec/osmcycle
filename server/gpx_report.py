#!/usr/bin/env python3
"""
gpx_report.py - GPX-Auswertung mit Copernicus GLO-30 Höhendaten (Bayern + Österreich)
Schreibt PHP-Report nach /var/www/web1/gpx_report.php
"""

import os
import sys
import math
import time
import json
import rasterio
import rasterio.sample
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

# ── Konfiguration ────────────────────────────────────────────────────────────
GPX_DIR     = ["/home/gh/syncthing/media", "/home/gh/osmand-tracks", "/var/www/web1/gpx_uploads"]
REPORT_PATH = "/var/www/web1/gpx_report.php"
COP_CACHE   = "/home/gh/syncthing/copernicus_cache"

# Bounding-Box Bayern + Tirol
LAT_MIN, LAT_MAX = 46, 50
LON_MIN, LON_MAX = 9,  14

# Namespace-Map für OsmAnd-GPX
NS = {
    'gpx':    'http://www.topografix.com/GPX/1/1',
    'osmand': 'https://osmand.net/docs/technical/osmand-file-formats/osmand-gpx',
}

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_UA  = "gpx_report/1.0 (heissa.de)"

# ── Copernicus GLO-30 laden ──────────────────────────────────────────────────
class CopernicusDEM:
    """Lädt Copernicus GLO-30 GeoTIFF-Kacheln und liefert Höhenwerte."""
    def __init__(self, cache_dir):
        self._dir = Path(cache_dir)
        self._handles = {}

    def _tile(self, lat, lon):
        key = (int(math.floor(lat)), int(math.floor(lon)))
        if key not in self._handles:
            lat_i, lon_i = key
            fname = self._dir / f"N{lat_i:02d}_E{lon_i:03d}.tif"
            if not fname.exists():
                return None
            self._handles[key] = rasterio.open(fname)
        return self._handles[key]

    def get_elevation(self, lat, lon):
        ds = self._tile(lat, lon)
        if ds is None:
            return None
        try:
            vals = list(rasterio.sample.sample_gen(ds, [(lon, lat)]))
            v = float(vals[0][0])
            return v if v > -9000 else None
        except Exception:
            return None

    def close(self):
        for ds in self._handles.values():
            ds.close()
        self._handles.clear()

def load_copernicus():
    print("Lade Copernicus GLO-30 Höhendaten …")
    dem = CopernicusDEM(COP_CACHE)
    total = (LAT_MAX - LAT_MIN) * (LON_MAX - LON_MIN)
    found = sum(1 for lat in range(LAT_MIN, LAT_MAX) for lon in range(LON_MIN, LON_MAX)
                if (Path(COP_CACHE) / f"N{lat:02d}_E{lon:03d}.tif").exists())
    print(f"  {found}/{total} Kacheln verfügbar.")
    return dem


# ── Nominatim Reverse-Geocoding ───────────────────────────────────────────────
_last_nom_request = 0.0

def get_place_name(lat, lon):
    global _last_nom_request
    wait = 1.0 - (time.time() - _last_nom_request)
    if wait > 0:
        time.sleep(wait)
    url = (f"{NOMINATIM_URL}?lat={lat}&lon={lon}"
           f"&format=json&accept-language=de&zoom=14")
    req = urllib.request.Request(url, headers={"User-Agent": NOMINATIM_UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        _last_nom_request = time.time()
        addr = data.get("address", {})
        return (addr.get("town")
             or addr.get("city")
             or addr.get("municipality")
             or addr.get("village")
             or addr.get("hamlet")
             or addr.get("county")
             or data.get("display_name", chr(8211)).split(",")[0])
    except (urllib.error.URLError, Exception) as e:
        print(f"    Nominatim-Fehler ({lat},{lon}): {e}")
        return chr(8211)


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────
def calc_hm(points, sample_m=100):
    """Gesamte Aufwärts-Höhenmeter via distanzbasiertem Sampling.

    SRTM3 hat 90 m Rasterauflösung. Bei direkter Punkt-für-Punkt-Summation
    entstehen physisch unmögliche Sprünge (20–48 m in 5–6 s = bis 32.000 Hm/h),
    weil jeder GPS-Punkt in eine andere Rasterzelle fällt.
    Lösung: SRTM-Höhe nur alle sample_m Meter auslesen → ein Wert pro Zelle,
    keine Doppelzählungen durch Zellgrenzen-Hin-und-her.
    """
    sampled = [points[0]['ele']]
    accum   = 0.0
    for i in range(1, len(points)):
        p0, p1 = points[i-1], points[i]
        accum += haversine(p0['lat'], p0['lon'], p1['lat'], p1['lon']) * 1000  # → Meter
        if accum >= sample_m:
            if p1['ele'] is not None:
                sampled.append(p1['ele'])
            accum = 0.0
    if points[-1]['ele'] is not None:
        sampled.append(points[-1]['ele'])
    return sum(
        max(0.0, sampled[i] - sampled[i-1])
        for i in range(1, len(sampled))
        if sampled[i] is not None and sampled[i-1] is not None
    )


def haversine(lat1, lon1, lat2, lon2):
    """Distanz in km (Haversine)."""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a  = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def fmt_ele(val):
    return f"{val:.0f} m" if val is not None else "–"


def fmt_f1(val):
    return f"{val:.1f}" if val is not None else "–"


# ── GPX parsen ────────────────────────────────────────────────────────────────
def parse_gpx(filepath, elev_data):
    try:
        tree = ET.parse(filepath)
    except ET.ParseError as e:
        print(f"  Parse-Fehler {filepath.name}: {e}")
        return None

    root = tree.getroot()

    # Track-Punkte einlesen
    points = []
    for trkpt in root.findall('.//gpx:trkpt', NS):
        lat = float(trkpt.get('lat'))
        lon = float(trkpt.get('lon'))

        # Copernicus GLO-30 (primär); Fallback auf GPS
        ele_cop  = elev_data.get_elevation(lat, lon)
        ele_gps  = None
        ele_el   = trkpt.find('gpx:ele', NS)
        if ele_el is not None:
            try:
                ele_gps = float(ele_el.text)
            except ValueError:
                pass
        ele = ele_cop  if ele_cop  is not None else ele_gps

        ts = None
        time_el = trkpt.find('gpx:time', NS)
        if time_el is not None:
            try:
                ts = datetime.fromisoformat(time_el.text.replace('Z', '+00:00'))
            except ValueError:
                pass

        points.append({'lat': lat, 'lon': lon, 'ele': ele, 'ele_gps': ele_gps, 'ts': ts})

    if len(points) < 2:
        return None

    # Distanz
    dist_km = sum(
        haversine(points[i-1]['lat'], points[i-1]['lon'],
                  points[i]['lat'],   points[i]['lon'])
        for i in range(1, len(points))
    )
    peak_idx = max(range(len(points)), key=lambda i: points[i]['ele'] if points[i]['ele'] is not None else -9999)
    dist_peak_km = sum(
        haversine(points[i-1]['lat'], points[i-1]['lon'],
                  points[i]['lat'],   points[i]['lon'])
        for i in range(1, peak_idx + 1)
    )

    # Gesamt-Aufwärts-Hm via distanzbasiertem Sampling (100 m pro Messung)
    hm_up = calc_hm(points, sample_m=100)

    # Dauer
    t0   = points[0]['ts']
    peak_pt = max((p for p in points if p['ele'] is not None and p['ts'] is not None),
                  key=lambda p: p['ele'], default=None)
    t1   = peak_pt['ts'] if peak_pt else None
    t_end = points[-1]['ts']
    dur_h = None
    if t0 and t1:
        dur_h = (t1 - t0).total_seconds() / 3600.0
        if dur_h <= 0:
            dur_h = None
    dur_total_h = None
    if t0 and t_end:
        dur_total_h = (t_end - t0).total_seconds() / 3600.0
        if dur_total_h <= 0:
            dur_total_h = None

    # km/h aus Distanz / Zeit
    kmh = dist_km / dur_h if dur_h else None

    # Hm/h: nur SRTM; Gipfelzone = erste ≥ srtm_max − 75 m (ignoriert Kammwanderung).
    # Aufbruch = letzter Punkt ≤ srtm_min + 20 m vor Gipfelzone (Talrast überspringen).
    # Bewegungszeit: Pausen > 11 min werden abgezogen.
    SUMMIT_THRESH = 75   # m unter SRTM-Maximum
    timed = [(i, p) for i, p in enumerate(points)
             if p['ele'] is not None and p['ts'] is not None]
    hmh = hmh_down = None

    if len(timed) > 1:
        srtm_max = max(p['ele'] for _, p in timed)
        summit_entry = next(
            ((i, p) for i, p in timed if p['ele'] >= srtm_max - SUMMIT_THRESH), None)
        if summit_entry:
            sum_i, sum_p = summit_entry

            # ── Aufstieg ──────────────────────────────────────────────────────
            before_summit = [(i, p) for i, p in timed if i <= sum_i]
            srtm_min_up = min(p['ele'] for _, p in before_summit)
            start_cands = [(i, p) for i, p in before_summit
                           if p['ele'] <= srtm_min_up + 20]
            if start_cands:
                start_i, start_p = start_cands[-1]
                ele_diff = sum_p['ele'] - start_p['ele']
                asc_seg = [(i, p) for i, p in timed if start_i <= i <= sum_i]
                asc_h = (asc_seg[-1][1]['ts'] - asc_seg[0][1]['ts']).total_seconds() / 3600.0
                if ele_diff > 10 and asc_h > 0:
                    hmh = ele_diff / asc_h

            # ── Abstieg ───────────────────────────────────────────────────────
            after_summit = [(i, p) for i, p in timed if i >= sum_i]
            if len(after_summit) > 1:
                srtm_min_dn = min(p['ele'] for _, p in after_summit)
                end_cands = [(i, p) for i, p in after_summit
                             if p['ele'] <= srtm_min_dn + 20]
                if end_cands:
                    end_i, end_p = end_cands[0]   # erstes Erreichen des Tals
                    ele_diff_dn = sum_p['ele'] - end_p['ele']
                    desc_seg = [(i, p) for i, p in timed if sum_i <= i <= end_i]
                    desc_h = (desc_seg[-1][1]['ts'] - desc_seg[0][1]['ts']).total_seconds() / 3600.0
                    if ele_diff_dn > 10 and desc_h > 0:
                        hmh_down = ele_diff_dn / desc_h

    # Datum aus Dateinamen (Format: YYYY-MM-DD_HH-MM_Weekday.gpx)
    name = filepath.stem  # z.B. 2026-02-19_11-57_Thu
    date_str = "–"
    try:
        date_str = datetime.strptime(name[:10], '%Y-%m-%d').strftime('%d.%m.%Y')
    except ValueError:
        pass

    # Startort via OSM Nominatim
    p0 = points[0]
    print(f"    Geocoding Startpunkt ({p0['lat']:.4f}, {p0['lon']:.4f}) …")
    place = get_place_name(p0['lat'], p0['lon'])
    print(f"    → {place}")

    # Nur Aufstieg zeichnen: Koordinaten beim Gipfelpunkt abschneiden
    peak_i = max(range(len(points)), key=lambda i: points[i]['ele'] if points[i]['ele'] is not None else -9999)
    track_pts = points[:peak_i + 1]
    step  = max(1, len(track_pts) // 300)
    coords = [[round(p['lat'], 6), round(p['lon'], 6)] for p in track_pts[::step]]
    last  = [round(track_pts[-1]['lat'], 6), round(track_pts[-1]['lon'], 6)]
    if coords[-1] != last:
        coords.append(last)

    return {
        'filename':    filepath.name,
        'date_str':    date_str,
        'sort_key':    name[:10],
        'place':       place,
        'ele_start':   points[0]['ele'],
        'ele_end':     max((p['ele'] for p in points if p['ele'] is not None), default=None),
        'dist_km':     dist_km,
        'dist_peak_km': dist_peak_km,
        'hm_up':       hm_up,
        'dur_h':       dur_h,
        'dur_total_h': dur_total_h,
        'kmh':         kmh,
        'hmh':         hmh,
        'hmh_down':    hmh_down,
        'coords':      coords,
    }


# ── PHP-Report erzeugen ───────────────────────────────────────────────────────
def write_report(tracks):
    import json as _json

    tracks_sorted = sorted(tracks, key=lambda x: x['sort_key'], reverse=True)

    # Nur die Felder, die PHP braucht
    php_data = []
    for t in tracks_sorted:
        php_data.append({
            'sort_key':  t['sort_key'],          # YYYY-MM-DD
            'date_str':  t['date_str'],
            'place':     t['place'],
            'ele_start': round(t['ele_start']) if t['ele_start'] is not None else None,
            'ele_end':   round(t['ele_end'])   if t['ele_end']   is not None else None,
            'dist_km':     round(t['dist_km'], 1),
            'dist_peak_km': round(t['dist_peak_km'], 1),
            'hm_up':     round(t['hm_up']),
            'dur_h':     round(t['dur_h'], 4)     if t['dur_h']     is not None else None,
            'dur_total_h': round(t['dur_total_h'], 4) if t['dur_total_h'] is not None else None,
            'kmh':       round(t['kmh'], 1)    if t['kmh']       is not None else None,
            'hmh':       round(t['hmh'], 1)      if t['hmh']      is not None else None,
            'hmh_down':  round(t['hmh_down'], 1) if t['hmh_down'] is not None else None,
            'coords':    t['coords'],
        })

    now        = datetime.now().strftime('%d.%m.%Y %H:%M')
    json_data  = _json.dumps(php_data, ensure_ascii=False)

    php = f"""<?php
// Automatisch generiert von gpx_report.py
// Letzte Aktualisierung: {now}

$tracks = json_decode('{json_data}', true);
$total  = count($tracks);

$monate = ['','Januar','Februar','März','April','Mai','Juni',
           'Juli','August','September','Oktober','November','Dezember'];

// Verfügbare Jahre und Monate ermitteln
$avail_years  = [];
$avail_months = [];
foreach ($tracks as $t) {{
    $y = (int)substr($t['sort_key'], 0, 4);
    $m = (int)substr($t['sort_key'], 5, 2);
    $avail_years[$y]  = true;
    $avail_months[$y][$m] = true;
}}
krsort($avail_years);

// Filter aus GET
$sel_year  = isset($_GET['year'])  ? (int)$_GET['year']  : 0;
$sel_month = isset($_GET['month']) ? (int)$_GET['month'] : 0;

// Filtern
$filtered = array_filter($tracks, function($t) use ($sel_year, $sel_month) {{
    if ($sel_year  && (int)substr($t['sort_key'],0,4) !== $sel_year)  return false;
    if ($sel_month && (int)substr($t['sort_key'],5,2) !== $sel_month) return false;
    return true;
}});

function fmt_ele($v)  {{ return $v !== null ? $v.' m' : '–'; }}
function fmt_f1($v)   {{ return $v !== null ? number_format($v,1,',','.') : '–'; }}
function fmt_dur($h)  {{
    if ($h === null) return '–';
    $hh = (int)$h;
    $mm = (int)(($h - $hh) * 60);
    return sprintf('%d:%02d h', $hh, $mm);
}}
?>
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GPX-Auswertung</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" rel="stylesheet">
  <style>
    :root {{ --gpx-green:#2c6e49; }}
    body  {{ background:#f0f2f5; }}
    h1    {{ color:var(--gpx-green); }}
    .gpx-table thead th {{
      background:var(--gpx-green); color:#fff; white-space:nowrap; border:none;
    }}
    .gpx-table tbody tr {{ cursor:pointer; }}
    .gpx-table tbody tr:hover td {{ background:#f0faf4; }}
    .gpx-table td {{ white-space:nowrap; vertical-align:middle; }}
    .badge-place {{
      background:#e0f2e9; color:var(--gpx-green);
      font-size:.8em; font-weight:500; padding:3px 9px; border-radius:12px;
    }}
    .stat-block {{ border-right:1px solid #dee2e6; }}
    .stat-block:last-child {{ border-right:none; }}
    .card-track {{ cursor:pointer; transition:box-shadow .15s; }}
    .card-track:hover {{ box-shadow:0 4px 12px rgba(0,0,0,.2) !important; }}
    #leaflet-map {{ height:60vh; min-height:300px; }}
    .map-hint {{ font-size:.75em; color:#888; }}
  </style>
</head>
<body>
<?php
  $track_map_data = array_values(array_map(function($t) {{
      return ['date'=>$t['date_str'],'place'=>$t['place'],'coords'=>$t['coords']];
  }}, $filtered));
?>
<div class="container py-3">

  <h1 class="mb-1">&#127956; GPX-Auswertung</h1>
  <p class="text-muted small mb-3">
    <?= $total ?> Tracks gesamt &nbsp;&bull;&nbsp;
    Höhendaten: SRTM3 (Bayern &amp; Tirol) &nbsp;&bull;&nbsp;
    Stand: {now}
  </p>

  <?php if ($total > 20 || $sel_year || $sel_month): ?>
  <form method="get" class="card p-3 mb-3 shadow-sm">
    <div class="row g-2 align-items-center">
      <div class="col-auto">
        <label class="col-form-label fw-semibold" style="color:var(--gpx-green)">Jahr</label>
      </div>
      <div class="col-auto">
        <select name="year" class="form-select form-select-sm" onchange="this.form.submit()">
          <option value="0"<?= $sel_year==0?' selected':'' ?>>Alle</option>
          <?php foreach (array_keys($avail_years) as $y): ?>
            <option value="<?= $y ?>"<?= $sel_year==$y?' selected':'' ?>><?= $y ?></option>
          <?php endforeach; ?>
        </select>
      </div>
      <div class="col-auto">
        <label class="col-form-label fw-semibold" style="color:var(--gpx-green)">Monat</label>
      </div>
      <div class="col-auto">
        <select name="month" class="form-select form-select-sm" onchange="this.form.submit()">
          <option value="0"<?= $sel_month==0?' selected':'' ?>>Alle</option>
          <?php
            $show_y = $sel_year ?: array_key_first($avail_years);
            $months_for_year = array_keys($avail_months[$show_y] ?? []);
            sort($months_for_year);
            foreach ($months_for_year as $m):
          ?>
            <option value="<?= $m ?>"<?= $sel_month==$m?' selected':'' ?>><?= $monate[$m] ?></option>
          <?php endforeach; ?>
        </select>
      </div>
      <?php if ($sel_year || $sel_month): ?>
      <div class="col-auto">
        <a href="?" class="btn btn-sm btn-outline-secondary">&#x2715; Zurücksetzen</a>
      </div>
      <?php endif; ?>
    </div>
  </form>
  <?php endif; ?>

  <?php if ($sel_year || $sel_month):
    $n = count($filtered);
    $label = "$n Tracks";
    if ($sel_year)  $label .= " &nbsp;&bull;&nbsp; $sel_year";
    if ($sel_month) $label .= " &nbsp;&bull;&nbsp; ".$monate[$sel_month];
  ?>
  <p class="text-muted small mb-2"><?= $label ?></p>
  <?php endif; ?>

  <!-- ═══ DESKTOP: Tabelle (ab md) ═══════════════════════════════════════ -->
  <div class="d-none d-md-block">
    <div class="card shadow-sm">
      <table class="table table-hover mb-0 gpx-table">
        <thead>
          <tr>
            <th>Datum</th>
            <th>Ort (Start)</th>
            <th class="text-end">Höhe Start</th>
            <th class="text-end">Höhe Ziel</th>
            <th class="text-end">Distanz</th>
            <th class="text-end">bis Gipfel</th>
            <th class="text-end">Dauer (Gipfel)</th>
            <th class="text-end">Gesamt</th>
            <th class="text-end">&#8960;&nbsp;km/h</th>
            <th class="text-end">Hm/h&nbsp;&#8593;</th>
            <th class="text-end">Hm/h&nbsp;&#8595;</th>
            <th class="text-end">Hm&nbsp;&#8593;</th>
          </tr>
        </thead>
        <tbody>
          <?php foreach (array_values($filtered) as $idx => $t): ?>
          <tr onclick="showTrack(<?= $idx ?>)" title="Auf Karte anzeigen">
            <td><?= htmlspecialchars($t['date_str']) ?></td>
            <td><span class="badge-place"><?= htmlspecialchars($t['place']) ?></span></td>
            <td class="text-end"><?= fmt_ele($t['ele_start']) ?></td>
            <td class="text-end"><?= fmt_ele($t['ele_end']) ?></td>
            <td class="text-end"><?= fmt_f1($t['dist_km']) ?> km</td>
            <td class="text-end"><?= fmt_f1($t['dist_peak_km']) ?> km</td>
            <td class="text-end"><?= fmt_dur($t['dur_h']) ?></td>
            <td class="text-end"><?= fmt_dur($t['dur_total_h']) ?></td>
            <td class="text-end"><?= fmt_f1($t['kmh']) ?></td>
            <td class="text-end"><?= fmt_f1($t['hmh']) ?></td>
            <td class="text-end"><?= fmt_f1($t['hmh_down']) ?></td>
            <td class="text-end"><?= $t['hm_up'] ?> m</td>
          </tr>
          <?php endforeach; ?>
        </tbody>
      </table>
    </div>
    <p class="map-hint mt-1 ms-1">&#128205; Zeile anklicken zum Anzeigen auf der Karte</p>
  </div>

  <!-- ═══ MOBIL: Cards (bis md) ══════════════════════════════════════════ -->
  <div class="d-md-none">
    <?php foreach (array_values($filtered) as $idx => $t): ?>
    <div class="card shadow-sm mb-3 card-track" onclick="showTrack(<?= $idx ?>)">
      <div class="card-header d-flex justify-content-between align-items-center py-2"
           style="background:var(--gpx-green)">
        <span class="text-white fw-semibold"><?= htmlspecialchars($t['date_str']) ?></span>
        <span style="background:rgba(255,255,255,.2);color:#fff;font-size:.8em;padding:2px 9px;border-radius:12px">
          &#128205; <?= htmlspecialchars($t['place']) ?>
        </span>
      </div>
      <div class="card-body p-0">
        <div class="row g-0 text-center border-bottom">
          <div class="col-6 py-2 border-end">
            <div class="text-muted" style="font-size:.75em">Höhe Start</div>
            <div class="fw-bold"><?= fmt_ele($t['ele_start']) ?></div>
          </div>
          <div class="col-6 py-2">
            <div class="text-muted" style="font-size:.75em">Höhe Ziel</div>
            <div class="fw-bold"><?= fmt_ele($t['ele_end']) ?></div>
          </div>
        </div>
        <div class="row g-0 text-center border-bottom">
          <div class="col-3 py-2 stat-block">
            <div class="text-muted" style="font-size:.7em">Distanz</div>
            <div class="small fw-semibold"><?= fmt_f1($t['dist_km']) ?> km</div>
          </div>
          <div class="col-3 py-2 stat-block">
            <div class="text-muted" style="font-size:.7em">Gipfel</div>
            <div class="small fw-semibold"><?= fmt_dur($t['dur_h']) ?></div>
          </div>
          <div class="col-3 py-2 stat-block">
            <div class="text-muted" style="font-size:.7em">Gesamt</div>
            <div class="small fw-semibold"><?= fmt_dur($t['dur_total_h']) ?></div>
          </div>
          <div class="col-3 py-2 stat-block">
            <div class="text-muted" style="font-size:.7em">km/h</div>
            <div class="small fw-semibold"><?= fmt_f1($t['kmh']) ?></div>
          </div>
          <div class="col-3 py-2 stat-block">
            <div class="text-muted" style="font-size:.7em">Hm/h &#8593;</div>
            <div class="small fw-semibold"><?= fmt_f1($t['hmh']) ?></div>
          </div>
        </div>
        <div class="text-center py-2 text-muted small">
          <?= $t['hm_up'] ?> m Höhenmeter &#8593; &nbsp;&bull;&nbsp;
          <span style="color:var(--gpx-green)">Tippen für Karte</span>
        </div>
      </div>
    </div>
    <?php endforeach; ?>
  </div>

  <p class="text-muted mt-3" style="font-size:.75em">{REPORT_PATH}</p>
</div>

<!-- ═══ MODAL: Leaflet-Karte ════════════════════════════════════════════════ -->
<div class="modal fade" id="mapModal" tabindex="-1">
  <div class="modal-dialog modal-xl modal-fullscreen-md-down">
    <div class="modal-content">
      <div class="modal-header py-2" style="background:var(--gpx-green)">
        <h5 class="modal-title text-white" id="mapModalTitle"></h5>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body p-0">
        <div id="leaflet-map"></div>
      </div>
    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const allTracks = <?= json_encode($track_map_data) ?>;

let leafletMap  = null;
let mapLayers   = [];
let pendingIdx  = null;

const mapModalEl = document.getElementById('mapModal');

mapModalEl.addEventListener('shown.bs.modal', function() {{
  if (!leafletMap) {{
    leafletMap = L.map('leaflet-map');
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19
    }}).addTo(leafletMap);
  }}
  leafletMap.invalidateSize();

  if (pendingIdx === null) return;
  mapLayers.forEach(l => l.remove());
  mapLayers = [];

  const t    = allTracks[pendingIdx];
  const line = L.polyline(t.coords, {{color:'#2c6e49', weight:4, opacity:.85}});
  mapLayers.push(line.addTo(leafletMap));

  mapLayers.push(
    L.circleMarker(t.coords[0], {{
      radius:9, color:'#fff', weight:2, fillColor:'#198754', fillOpacity:1
    }}).bindPopup('<b>Start</b>').addTo(leafletMap)
  );
  mapLayers.push(
    L.circleMarker(t.coords[t.coords.length - 1], {{
      radius:9, color:'#fff', weight:2, fillColor:'#dc3545', fillOpacity:1
    }}).bindPopup('<b>Ziel</b>').addTo(leafletMap)
  );

  leafletMap.fitBounds(line.getBounds(), {{padding:[30, 30]}});
  pendingIdx = null;
}});

function showTrack(idx) {{
  const t = allTracks[idx];
  document.getElementById('mapModalTitle').textContent =
    t.date + '\u2002\u2013\u2002' + t.place;
  pendingIdx = idx;
  bootstrap.Modal.getOrCreateInstance(mapModalEl).show();
}}
</script>
</body>
</html>
"""

    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(php)
    print(f"Report geschrieben: {REPORT_PATH}")


# ── Hauptprogramm ─────────────────────────────────────────────────────────────
def main():
    dirs = [GPX_DIR] if isinstance(GPX_DIR, str) else GPX_DIR
    gpx_files = sorted(f for d in dirs for f in Path(d).glob("*.gpx"))
    if not gpx_files:
        print(f"Keine GPX-Dateien gefunden.")
        sys.exit(1)
    print(f"{len(gpx_files)} GPX-Dateien gefunden.")

    elev = load_copernicus()

    tracks = []
    for f in gpx_files:
        print(f"  Verarbeite {f.name} …")
        result = parse_gpx(f, elev)
        if not result:
            print(f"    → übersprungen (zu wenige Punkte)")
        elif result['dist_km'] < 1.0 or result['hm_up'] < 2.0:
            print(f"    → übersprungen (dist={result['dist_km']:.2f} km, hm={result['hm_up']:.0f} m)")
        else:
            tracks.append(result)

    if not tracks:
        print("Keine auswertbaren Tracks gefunden.")
        sys.exit(1)

    write_report(tracks)
    print(f"\nFertig. {len(tracks)} Tracks ausgewertet.")


if __name__ == '__main__':
    main()
