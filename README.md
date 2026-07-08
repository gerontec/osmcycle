# OSMCycle — CyclOSM cycling stack for Bayern + Tirol + Südtirol + Kärnten

A self-hosted [CyclOSM](https://www.cyclosm.org/) raster tile server **with
contour lines, hillshade and MTB-scale colouring** (like openstreetmap.org's
`layers=Y`), plus a small [Kivy](https://kivy.org/) Android app that shows it,
**records GPS tracks as GPX**, and can overlay three long-distance hiking
trails. Coverage: **Bayern, Tirol, Südtirol and Kärnten**.

Recorded rides upload themselves to a public online report — no Syncthing, no PC:

**➡ Live-Report: https://heissa.de/web1/gpx_report.php**

The server side of that report lives in [`server/gpx_report.py`](server/gpx_report.py)
(hourly generator) and [`server/gpx_upload.php`](server/gpx_upload.php) (the
public, token-free drop endpoint).

## Fertige Karte laden — einfachster Weg (ohne selbst zu rendern)

Vorgerenderte Offline-Karten liegen zum Download bereit:

**➡ https://tmind.de/maps/**

| Datei | Gebiet | Größe |
|-------|--------|-------|
| `CyclOSM_Alpen.sqlitedb` | Bayern + Tirol + Südtirol + Kärnten (all-in-one) | 2,4 GB |
| `CyclOSM_Bayern-Tirol.sqlitedb` | Bayern + Tirol | 329 MB |
| `CyclOSM_Kaernten.sqlitedb` | Kärnten | 36 MB |
| `CyclOSM_Suedtirol.sqlitedb` | Südtirol | 28 MB |

**Neue Nutzer — der einfachste Weg:**

1. **Nur die App installieren** (`osmcycle-*.apk`). Sie **streamt die Karte direkt von
   netcup** (`https://tmind.de/maps/tile.php`, z6–14) — kein 2‑GB‑Download, kein OsmAnd,
   keine Einrichtung. Betrachtete Kacheln werden gecacht und funktionieren danach offline.

### 📲 App herunterladen & installieren

<p align="center">
  <img src="docs/osmcycle_apk_qr.png" alt="QR-Code: neueste OSMCycle-APK laden" width="220"><br>
  <b>Handy-Kamera auf den QR halten → lädt automatisch die neueste APK</b><br>
  (Direktlink: <a href="https://heissa.de/web1/get_apk.php">heissa.de/web1/get_apk.php</a> —
  leitet immer auf die aktuellste Release-APK)
</p>

- **APK (neueste Version):**
  **➡ https://github.com/gerontec/osmcycle/releases/latest** → die Datei
  `osmcycle-vX.apk` antippen. Spiegel ohne GitHub:
  **https://tmind.de/maps/apk/osmcycle-v0.9.apk**
- **Auto-Update:** [Obtainium](https://github.com/ImranR98/Obtainium) installieren →
  „Add App" → obige Repo-URL. Holt jede neue Release automatisch.

**Installation ohne Entwicklermodus** (normaler Weg, kein USB/ADB nötig):
Android fragt beim ersten Öffnen der APK, ob es „aus dieser Quelle installieren"
darf → **erlauben** (Einstellung *„Unbekannte Apps installieren"* für den Browser
bzw. Dateimanager). Entwickleroptionen / USB-Debugging braucht man **nur** für
`adb install`. Der Download-und-Antippen-Weg funktioniert auch auf Android 16 ohne
Entwicklermodus — es ist nur die einmalige Quellen-Freigabe pro Browser. (Manche
Hersteller-ROMs, z. B. MIUI, zeigen zusätzlich einen eigenen „Über USB / unbekannte
Apps"-Dialog — einfach bestätigen.)
2. Voll offline / OsmAnd: `CyclOSM_Alpen.sqlitedb` von obigem Link laden, nach
   `Android/data/net.osmand/files/tiles/` legen, dann *Karte konfigurieren → Kartenquelle*.

Der Tile‑Server `maps/tile.php` liefert die Kacheln aus der `sqlitedb` — öffentlich, mit
TLS, unabhängig vom Heim‑Renderserver.

```
OSM (Geofabrik) ─▶ PostGIS (osm2pgsql) ─┐
DEM (viewfinderpanoramas via pyhgtmap) ─┼▶ Mapnik / CyclOSM CartoCSS
  → contours DB + hillshade VRT          │        │
                                 renderd + Apache mod_tile  (IPv4 + IPv6, :8280)
                                          │
        http(s)://<host>:8280/tiles/cyclosm/{z}/{x}/{y}.png        (base map)
        http(s)://<host>:8280/tiles/wanderwege/{z}/{x}/{y}.png     (trail overlay)
                                          │
                   Kivy app  (offline MBTiles + on-demand Nachladen)
```

Rendering is **CPU-bound** (Mapnik/Cairo) — no GPU/CUDA used or needed on the
server; the phone only does OpenGL compositing.

## Repository layout

| Path | What |
|------|------|
| `app/main.py` | Kivy app: map, position arrow, centre button, REC, layer menu |
| `app/hybridsource.py` | tile source: offline MBTiles first, network on miss |
| `app/track.py` | GPX recorder + track/position/Wanderwege map layers |
| `app/wanderwege.json` | 3 hiking trails, simplified, bundled for the layer menu |
| `app/buildozer.spec` | buildozer config → debug APK |
| `style/` | git submodule → `cyclosm/cyclosm-cartocss-style` |
| `server/renderd.conf.example` | renderd config (Mapnik 4.2 plugin path, maps) |
| `server/tileserver-vhost.conf.example` | Apache mod_tile vhost, port **8280** |
| `server/wanderwege.xml` | Mapnik overlay style for the 3 trails |
| `server/gpx_report.py` | hourly generator of the public GPX report (Bootstrap+Leaflet) |
| `server/gpx_upload.php` | public token-free GPX drop endpoint for the app |
| `scripts/setup_tileserver.sh` | one-shot server bring-up |
| `scripts/import_osm.sh` | download + merge + `osm2pgsql` import |
| `scripts/make_land_shapefile.sh` | landlocked land-polygon substitute |
| `scripts/patch_project_mml.sh` | repoint coastline layers + compile `mapnik.xml` |
| `scripts/build_dem.sh` | **contours + hillshade → Höhenlinien in the tiles** |
| `scripts/build_wanderwege.sh` + `tirol_route.sql` | build the trail overlay |
| `scripts/seed.sh` | pre-render a bbox |
| `scripts/pack_mbtiles.py` / `pack_alpen.py` | pack bbox(es) → offline `.mbtiles` |
| `scripts/mbtiles2osmand.py` | convert `.mbtiles` → OsmAnd `.sqlitedb` |

## Server bring-up (Ubuntu 26.04 / Mapnik 4.2)

```bash
git clone --recursive https://github.com/gerontec/osmcycle ~/python/osmcycle
cd ~/python/osmcycle && git submodule update --init
bash scripts/setup_tileserver.sh    # packages, DB, import, land polygon, renderd, apache
bash scripts/build_dem.sh           # Höhenlinien + Hillshade (pyhgtmap + gdaldem)
bash scripts/build_wanderwege.sh    # trail overlay at /tiles/wanderwege/
curl -o /tmp/t.png http://localhost:8280/tiles/cyclosm/17/69749/45644.png
```

The tile vhost's `Listen 8280` is dual-stack, so tiles are served over **IPv6**
too (`http://[<global-v6>]:8280/…`). For access away from home you need an
inbound IPv6 firewall rule on the router and, since the prefix is dynamic, a
DNS **AAAA** name (the IPv6 literal breaks when the prefix rotates).

## The Android app

Offline-first: it reads a combined **`alpen.mbtiles`** (all four regions,
z6–14, with Höhenlinien) locally, and pulls higher zooms / neighbouring tiles
from the server on demand (`hybridsource.py`). Features:

- CyclOSM base with **Höhenlinien + Hillshade + MTB-Skala**.
- **Position arrow** that rotates to the GPS heading + **◎ centre-on-me** button
  (shows the last known fix immediately, auto-centres on the first live fix).
- **● REC** GPS track recording → **GPX 1.1** in the public folder
  `/sdcard/osmcycle/track_<ts>.gpx`. Recording follows a **live Android
  `LocationListener`** (fresh fixes, not the stale last-known cache), so a real
  ride is captured at full length instead of collapsing to a stationary blob.
- **Auto-upload to the online report** — see below; no Syncthing, no PC.
- **≡ Layer** menu toggles the 3 hiking trails (🔴 Karnischer, 🔵 Maximilians,
  🟢 Tiroler Höhenweg), drawn client-side from `wanderwege.json` (offline,
  viewport-culled).

### GPX-Upload → Online-Report (kein Syncthing nötig)

Aufgezeichnete Tracks landen **direkt vom Handy** im öffentlichen Report auf
**https://heissa.de/web1/gpx_report.php** — komplett ohne Syncthing, ohne PC,
ohne Kabel.

```
App (Hintergrund-Thread, max. 1×/24 h beim Öffnen)
  │  HTTP POST  (multipart, nur track_*.gpx, ≤10 MB)
  ▼
https://heissa.de/web1/gpx_upload.php      ← öffentlich, ohne Token, jeder darf
  │  speichert nach
  ▼
/var/www/web1/gpx_uploads/<YYYY-MM-DD_HH-MM_Wochentag>.gpx
  │  stündlicher Cron scannt den Ordner (gpx_report.py, GPX_DIR)
  ▼
https://heissa.de/web1/gpx_report.php      ← Bootstrap+Leaflet, Karte + Tabelle
```

- **Wann:** ein Daemon-Thread startet beim App-Öffnen und lädt höchstens
  **einmal pro 24 h** hoch (Stempeldatei `.last_upload` im GPX-Ordner). Kein
  Dienst im Hintergrund bei geschlossener App — einmal öffnen genügt.
- **Was:** nur eigene Aufnahmen (`track_*.gpx`), umbenannt in die Konvention
  `YYYY-MM-DD_HH-MM_Wochentag.gpx`, die der Report für die Datums­spalte parst.
  Die gebündelten Demo-Routen werden **nicht** hochgeladen.
- **Kein Sicherheitscheck** (Wunsch: jeder darf uploaden) — der Endpoint prüft
  nur `.gpx` + Größe (≤10 MB), kein Token, keine Anmeldung.
- **Über 4G erlaubt** (GPX ist winzig). Fehlschläge (offline) werden still
  ignoriert und beim nächsten Öffnen erneut versucht.

> Der Report filtert Tracks **< 1 km / < 2 hm** aus (Rausch-/Drift-Schutz), also
> erscheinen nur echte Fahrten.

Build + install:

```bash
cd app
python3.11 -m venv ../venv-buildozer && source ../venv-buildozer/bin/activate
pip install "cython<3.1" buildozer
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64      # p4a needs JDK 17
buildozer -v android debug                              # p4a.branch = release-2024.01.21
adb install -r bin/osmcycle-0.1-arm64-v8a-debug.apk
adb push alpen.mbtiles \
  /sdcard/Android/data/org.gerontec.osmcycle/files/alpen.mbtiles
```

Set `ONLINE_URL` in `app/main.py` to a host the phone can reach (LAN IPv4, or
the server's IPv6 / a DNS AAAA name for mobile use).

## The 3 hiking trails (Wanderwege overlay)

- **Karnischer Höhenweg** and **Maximiliansweg** come straight from their OSM
  route relations (member ways).
- The **Tiroler Höhenweg** is *not* a named OSM route, so it is routed along OSM
  trails through its huts (Mayrhofen → Landshuter/Sattelberg → Tribulaunhütte →
  St. Martin am Schneeberg → Zwickauer Hütte → Stettiner Hütte → Bockerhütte →
  Meran) with **pgRouting** (`pgr_dijkstraVia`, see `tirol_route.sql`). It is
  *not* identical to the Meraner Höhenweg (a loop around Meran) — they only
  share the final section near the Stettiner Hütte.

Served transparently at `/tiles/wanderwege/`; usable as an OsmAnd overlay map or
via the app's layer menu.

## Use the maps in OsmAnd

```bash
python3 scripts/mbtiles2osmand.py alpen.mbtiles CyclOSM_Alpen.sqlitedb
adb push CyclOSM_Alpen.sqlitedb <OsmAnd-data-folder>/tiles/CyclOSM_Alpen.sqlitedb
```

Or point OsmAnd at the live server with a tiny online-source `.sqlitedb` whose
`info.url` is `http://[<v6>]:8280/tiles/cyclosm/{0}/{1}/{2}.png` (base) and
`…/tiles/wanderwege/…` (overlay). Enable the **Online-Karten** plugin, then pick
them under **Karte konfigurieren → Kartenquelle / Overlay-Karte**.

**Storage:** OsmAnd's data folder may be internal, `Android/media/net.osmand`,
or a chosen public folder — check **Einstellungen → OsmAnd Einstellungen →
Datenordner**. For big packs, put them on the **SD card / external storage** and
point OsmAnd's data folder there. Delete superseded region `.obf`/`.sqlitedb`
maps to reclaim space.

## Design notes / decisions

- **Rendering stack:** `renderd` + Apache `mod_tile` (canonical OSM stack).
  `python3-mapnik` is not packaged on Ubuntu 26.04 and `pip install mapnik`
  won't build against Mapnik 4.x, so TileStache/python-mapnik was a dead end.
  Mapnik 4.2's PostGIS reader ships as `postgis+pgraster.input`.
- **Höhenlinien + Hillshade:** contours from `pyhgtmap --sources=view3` (no NASA
  account) loaded into a `contours` DB; hillshade via `gdaldem` → `dem/shade.vrt`.
  The style's hillshade + contour layers (shipped `status: off`) are switched on
  in `build_dem.sh`. pyhgtmap tags contours `ele` (not `height`) — captured and
  renamed on import.
- **Landlocked land polygon:** replaces CyclOSM's ~1 GB coastline shapefiles with
  one world-covering polygon; the Mapnik sea-colour background then shows as land
  everywhere inland.
- **Serving port 8280:** dedicated vhost so the existing web stack (80/443/…) is
  untouched; dual-stack for IPv6.
- **Austria data:** Geofabrik doesn't split Austria — the whole country is
  downloaded and clipped per region (Tirol, Südtirol via Italy nord-est, Kärnten)
  before merging with Bayern.
- **APK build:** `p4a.branch = release-2024.01.21` (Python 3.11). p4a master
  builds Python 3.14, which kivy 2.3.0's Cython C does not compile against.

## Attribution

Map data © OpenStreetMap contributors (ODbL). Style: CyclOSM (BSD-2-Clause,
`style/` submodule). Elevation: viewfinderpanoramas (SRTM-derived).
