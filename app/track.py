"""GPS track recording + GPX export + on-map track/GPX layers for OSMCycle."""
import bisect
import glob
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from kivy.core.text import Label as CoreLabel
from kivy.graphics import (Color, Line, Ellipse, Triangle, Rectangle,
                           PushMatrix, PopMatrix, Rotate)
from kivy_garden.mapview import MapLayer


_DATE_IN_NAME = re.compile(
    r"\d{4}-\d{2}-\d{2}"        # 2026-07-10   <- so heissen aufgenommene Tracks
    r"|\d{4}_\d{2}_\d{2}"       # 2026_07_10
    r"|\d{2}\.\d{2}\.\d{4}"     # 10.07.2026
    r"|(?:19|20)\d{6}"          # 20260710
)


def _dated(path):
    """True, wenn der Dateiname ein Datum traegt. Aufgezeichnete Fahrten heissen
    track_2026-07-10_15-30-00.gpx; die bleiben aus den Layern. Die mitgelieferten
    Routen (karnisch, maximilian, tirol, gipfel) haben keins und bleiben sichtbar."""
    return bool(_DATE_IN_NAME.search(os.path.basename(path)))


def rgba(hexstr, alpha=0.85):
    """'#FF5020' -> (1.0, 0.314, 0.125, alpha)."""
    s = hexstr.lstrip("#")
    return (int(s[0:2], 16) / 255.0, int(s[2:4], 16) / 255.0,
            int(s[4:6], 16) / 255.0, alpha)


# Farben aus OsmAnds eigener Palette (DefaultColors.java), damit die App neben
# einer OsmAnd-Karte nicht fremd wirkt. OsmRouteType.HIKING traegt dort "orange".
COLOR_HIKING = rgba("#FF5020", 0.9)   # OsmAnd ORANGE    – Wanderwege
COLOR_MASTS = rgba("#D00D0D")         # OsmAnd RED       – Sendemasten
COLOR_BATHING = rgba("#10C0F0")       # OsmAnd LIGHTBLUE – Badestellen
COLOR_GROUNDWATER = rgba("#1010A0")   # OsmAnd BLUE      – Grundwasserbrunnen
COLOR_WATERFALL = rgba("#00A8A8")     # TEAL             – Wasserfaelle (OSM)


def _writable(d):
    try:
        os.makedirs(d, exist_ok=True)
        t = os.path.join(d, ".w")
        open(t, "w").close()
        os.remove(t)
        return True
    except Exception:
        return False


def gpx_dir():
    """Single folder holding ALL .gpx (bundled routes seeded on first start +
    own recorded tracks), also what GpxLayer reads. Prefers a PUBLIC folder so
    Syncthing can sync it; falls back to the app-private dir if not writable
    (needs 'All files access' for the public path)."""
    candidates = ["/sdcard/osmcycle", "/storage/emulated/0/osmcycle"]
    try:
        from android import mActivity  # type: ignore
        ext = mActivity.getExternalFilesDir(None)
        if ext:                                   # app-private fallback
            candidates.append(os.path.join(ext.getAbsolutePath(), "gpx"))
    except Exception:
        pass
    candidates.append(os.path.join(os.path.expanduser("~"), "osmcycle_gpx"))
    for d in candidates:
        if _writable(d):
            return d
    return candidates[-1]


class TrackLayer(MapLayer):
    """Draws the currently recorded track as a red line on the map."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.points = []  # list of (lat, lon)

    def add_point(self, lat, lon):
        self.points.append((lat, lon))
        self.reposition()

    def clear(self):
        self.points = []
        self.canvas.clear()

    def reposition(self, *args):
        mapview = self.parent
        self.canvas.clear()
        if not mapview or not self.points:
            return
        coords = []
        for lat, lon in self.points:
            x, y = mapview.get_window_xy_from(lat, lon, mapview.zoom)
            coords += [x, y]
        with self.canvas:
            Color(0.85, 0.1, 0.1, 0.9)
            if len(coords) >= 4:
                Line(points=coords, width=2.2)
            # one dot per recorded fix (10 s sample) as a live success-check
            r = 6
            for i in range(0, len(coords), 2):
                Ellipse(pos=(coords[i] - r, coords[i + 1] - r), size=(2 * r, 2 * r))


class PositionLayer(MapLayer):
    """Current GPS position: accuracy circle + arrow rotated to the heading."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.lat = self.lon = None
        self.heading = 0.0

    def set_position(self, lat, lon, heading=None):
        self.lat, self.lon = lat, lon
        if heading is not None:
            self.heading = heading
        self.reposition()

    def reposition(self, *args):
        mapview = self.parent
        self.canvas.clear()
        if not mapview or self.lat is None:
            return
        x, y = mapview.get_window_xy_from(self.lat, self.lon, mapview.zoom)
        with self.canvas:
            Color(0.13, 0.59, 0.95, 0.25)
            Ellipse(pos=(x - 26, y - 26), size=(52, 52))
            Color(0.13, 0.59, 0.95, 1)
            PushMatrix()
            Rotate(angle=-self.heading, origin=(x, y))   # 0 = north = up
            # Doppelte Groesse (Spitze +36 / Basis +-22, -24) -> gut sichtbarer
            # Richtungspfeil; die Spitze zeigt zur Heading.
            Triangle(points=[x, y + 36, x - 22, y - 24, x + 22, y - 24])
            PopMatrix()


class GpxLayer(MapLayer):
    """Toggleable GPX overlay, rendered like OsmAnd: every .gpx in the given
    folder(s) becomes track lines. Kept smooth by (1) a zoom floor,
    (2) per-segment viewport culling and (3) screen-space point decimation, so
    only geometry near the active window is projected/drawn."""
    MIN_ZOOM = 11        # below this a whole trail fills the screen -> skip (lag)
    DECIMATE_PX = 2.5    # drop points closer than this (in screen px) to the last
    HIKING_COLOR = COLOR_HIKING   # eine Farbe fuer alle Wanderwege

    def __init__(self, dirs, **kwargs):
        super().__init__(**kwargs)
        self.enabled = set()        # names of tracks currently shown (multi-select)
        self.segments = []          # {"points","bb","color","src"}
        if isinstance(dirs, str):
            dirs = [dirs]
        for d in dirs:
            for path in sorted(glob.glob(os.path.join(d or "", "*.gpx"))):
                if _dated(path):
                    continue
                try:
                    self._load(path)
                except Exception:
                    pass

    def _load(self, path):
        root = ET.parse(path).getroot()
        base = os.path.splitext(os.path.basename(path))[0]
        for trk in root:
            if not trk.tag.endswith("trk"):
                continue
            name = base
            for child in trk:
                if child.tag.endswith("name") and child.text:
                    name = child.text
            # <osmand:color> aus der GPX wird bewusst ignoriert: alle Wanderwege
            # sollen einheitlich erscheinen, nicht je Datei anders.
            for seg in trk:
                if not seg.tag.endswith("trkseg"):
                    continue
                pts = []
                for pt in seg:
                    if pt.tag.endswith("trkpt"):
                        try:
                            pts.append((float(pt.get("lat")), float(pt.get("lon"))))
                        except (TypeError, ValueError):
                            pass
                if len(pts) >= 2:
                    lats = [p[0] for p in pts]
                    lons = [p[1] for p in pts]
                    self.segments.append({
                        "points": pts, "src": name,
                        "bb": (min(lats), min(lons), max(lats), max(lons))})

    def sources(self):
        """Distinct track names, in load order (for the layer menu)."""
        seen = []
        for s in self.segments:
            if s["src"] not in seen:
                seen.append(s["src"])
        return seen

    def set_enabled(self, src, on):
        self.enabled.add(src) if on else self.enabled.discard(src)
        self.reposition()

    def reposition(self, *args):
        mapview = self.parent
        self.canvas.clear()
        if not mapview or not self.enabled:
            return
        if int(mapview.zoom) < self.MIN_ZOOM:
            return                       # zoomed out: overview adds nothing but lag
        try:                             # visible viewport (lat/lon) + margin
            bb = mapview.get_bbox()
            vlatmin, vlatmax = min(bb[0], bb[2]), max(bb[0], bb[2])
            vlonmin, vlonmax = min(bb[1], bb[3]), max(bb[1], bb[3])
        except Exception:
            return                       # unknown viewport -> draw nothing (fast)
        mlat = (vlatmax - vlatmin) * 0.2
        mlon = (vlonmax - vlonmin) * 0.2
        vlatmin -= mlat; vlatmax += mlat; vlonmin -= mlon; vlonmax += mlon
        zoom = mapview.zoom
        d = self.DECIMATE_PX
        with self.canvas:
            Color(*self.HIKING_COLOR)      # eine Farbe fuer alle Wanderwege
            for seg in self.segments:
                if seg["src"] not in self.enabled:
                    continue             # track not selected -> skip
                la0, lo0, la1, lo1 = seg["bb"]
                if (la1 < vlatmin or la0 > vlatmax or
                        lo1 < vlonmin or lo0 > vlonmax):
                    continue             # segment off-screen -> skip
                coords = []
                lx = ly = None
                for lat, lon in seg["points"]:
                    x, y = mapview.get_window_xy_from(lat, lon, zoom)
                    if lx is None or abs(x - lx) + abs(y - ly) >= d:
                        coords += [x, y]
                        lx, ly = x, y
                if len(coords) >= 4:
                    Line(points=coords, width=2.2, joint="round", cap="round")


class PeaksLayer(MapLayer):
    """Named-summit overlay from GPX <wpt> ('Gipfelnamen'). Only near the active
    window and only when zoomed in, with a per-frame label cap + texture cache,
    so tens of thousands of peaks stay smooth."""
    MIN_ZOOM = 13
    MAX_LABELS = 80
    FONT_SIZE = 26                 # Standard; grosse Variante bekommt 20 % mehr

    def __init__(self, dirs, font_size=FONT_SIZE, **kwargs):
        super().__init__(**kwargs)
        self.visible = False
        self.font_size = font_size
        self.peaks = []            # (lat, lon, name)
        self._tex = {}             # name -> Texture (lazy cache)
        if isinstance(dirs, str):
            dirs = [dirs]
        for d in dirs:
            for path in sorted(glob.glob(os.path.join(d or "", "*.gpx"))):
                if _dated(path):
                    continue
                try:
                    self._load(path)
                except Exception:
                    pass

    def _load(self, path):
        for wpt in ET.parse(path).getroot():
            if not wpt.tag.endswith("wpt"):
                continue
            try:
                lat = float(wpt.get("lat"))
                lon = float(wpt.get("lon"))
            except (TypeError, ValueError):
                continue
            name = ""
            for c in wpt:
                if c.tag.endswith("name") and c.text:
                    name = c.text
                    break
            if name:
                self.peaks.append((lat, lon, name))

    def _texture(self, name):
        tex = self._tex.get(name)
        if tex is None:
            lbl = CoreLabel(text=name, font_size=self.font_size)
            lbl.refresh()
            tex = lbl.texture
            self._tex[name] = tex
        return tex

    def set_visible(self, on):
        self.visible = on
        self.reposition()

    def reposition(self, *args):
        mapview = self.parent
        self.canvas.clear()
        if not mapview or not self.visible:
            return
        if int(mapview.zoom) < self.MIN_ZOOM:
            return
        try:
            bb = mapview.get_bbox()
            vlatmin, vlatmax = min(bb[0], bb[2]), max(bb[0], bb[2])
            vlonmin, vlonmax = min(bb[1], bb[3]), max(bb[1], bb[3])
        except Exception:
            return
        zoom = mapview.zoom
        drawn = 0
        with self.canvas:
            for lat, lon, name in self.peaks:
                if not (vlatmin <= lat <= vlatmax and vlonmin <= lon <= vlonmax):
                    continue
                x, y = mapview.get_window_xy_from(lat, lon, zoom)
                Color(0.35, 0.20, 0.05, 1)                 # brown summit marker
                Triangle(points=[x, y + 7, x - 6, y - 5, x + 6, y - 5])
                tex = self._texture(name)
                if tex:
                    w, h = tex.size
                    Color(1, 1, 1, 0.7)                    # readability halo
                    Rectangle(pos=(x + 7, y - 1), size=(w + 2, h))
                    Color(0.15, 0.10, 0.05, 1)             # dark text
                    Rectangle(texture=tex, pos=(x + 8, y - 1), size=(w, h))
                drawn += 1
                if drawn >= self.MAX_LABELS:
                    break


class PointsLayer(MapLayer):
    """Punktwolke aus einer JSON-Liste [[lat,lon],...]. Wie PeaksLayer: erst ab
    min_zoom, nur im sichtbaren Fenster, mit Zeichen-Obergrenze. Die Liste wird
    nach lat sortiert, dann schneidet eine Bisektion das sichtbare Breitenband
    heraus, statt jeden Frame alle Punkte zu prüfen — das traegt auch die knapp
    14.000 Sendemasten fluessig."""

    def __init__(self, path, color, min_zoom=12, max_points=500, radius=4,
                 **kwargs):
        super().__init__(**kwargs)
        self.visible = False
        self.color = color
        self.min_zoom = min_zoom
        self.max_points = max_points
        self.radius = radius
        self.points = []
        try:
            with open(path) as f:
                self.points = [(float(a), float(b)) for a, b in json.load(f)]
        except Exception:
            pass                         # keine Datei -> Layer bleibt leer
        self.points.sort()               # Bisektion braucht lat-Sortierung
        self._lats = [p[0] for p in self.points]

    def count(self):
        return len(self.points)

    def set_visible(self, on):
        self.visible = on
        self.reposition()

    def reposition(self, *args):
        mapview = self.parent
        self.canvas.clear()
        if not mapview or not self.visible or not self.points:
            return
        if int(mapview.zoom) < self.min_zoom:
            return
        try:
            bb = mapview.get_bbox()
            vlatmin, vlatmax = min(bb[0], bb[2]), max(bb[0], bb[2])
            vlonmin, vlonmax = min(bb[1], bb[3]), max(bb[1], bb[3])
        except Exception:
            return
        lo = bisect.bisect_left(self._lats, vlatmin)
        hi = bisect.bisect_right(self._lats, vlatmax)
        zoom = mapview.zoom
        r = self.radius
        drawn = 0
        with self.canvas:
            Color(*self.color)
            for lat, lon in self.points[lo:hi]:
                if not (vlonmin <= lon <= vlonmax):
                    continue
                x, y = mapview.get_window_xy_from(lat, lon, zoom)
                Ellipse(pos=(x - r, y - r), size=(2 * r, 2 * r))
                drawn += 1
                if drawn >= self.max_points:
                    break


class TrackRecorder:
    """Collects GPS fixes and writes a GPX 1.1 file."""
    def __init__(self):
        self.recording = False
        self.points = []       # (lat, lon, ele, iso_time)
        self.start_ts = None
        self._last_ele = None

    def start(self):
        self.recording = True
        self.points = []
        self._last_ele = None
        self.start_ts = time.strftime("%Y-%m-%d_%H-%M-%S")

    def add(self, lat, lon, ele=None):
        if not self.recording:
            return
        if ele is None:                 # carry forward last known altitude so
            ele = self._last_ele        # every point keeps an <ele>
        else:
            self._last_ele = ele
        t = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.points.append((lat, lon, ele, t))

    def stop_and_save(self):
        self.recording = False
        if not self.points:
            return None
        path = os.path.join(gpx_dir(), f"track_{self.start_ts}.gpx")
        with open(path, "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<gpx version="1.1" creator="OSMCycle" '
                    'xmlns="http://www.topografix.com/GPX/1/1">\n')
            f.write(f'  <trk><name>OSMCycle {self.start_ts}</name><trkseg>\n')
            for lat, lon, ele, t in self.points:
                f.write(f'    <trkpt lat="{lat:.6f}" lon="{lon:.6f}">')
                if ele is not None:
                    f.write(f'<ele>{ele:.1f}</ele>')
                f.write(f'<time>{t}</time></trkpt>\n')
            f.write('  </trkseg></trk>\n</gpx>\n')
        return path
