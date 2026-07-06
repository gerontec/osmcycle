# OSMCycle — CyclOSM map app for Bayern + Tirol

A self-hosted [CyclOSM](https://www.cyclosm.org/) raster tile server plus a
small [Kivy](https://kivy.org/) Android app that displays it. Coverage: all of
**Bayern** and **Tirol** (western Austria, clipped to the render bbox).

```
OSM data (Geofabrik)  ─▶  PostGIS (osm2pgsql)  ─▶  Mapnik / CyclOSM CartoCSS
                                                        │
                                             renderd + Apache mod_tile
                                                        │
                                   http://<host>:8280/tiles/cyclosm/{z}/{x}/{y}.png
                                                        │
                                          Kivy app (kivy_garden.mapview)
```

The tile pipeline is **CPU-bound** (Mapnik/Cairo). No GPU/CUDA is used or
needed on the server; the phone only does OpenGL compositing in the app.

## Repository layout

| Path | What |
|------|------|
| `app/main.py` | Kivy app (offline-first MapView) |
| `app/hybridsource.py` | tile source: MBTiles offline, network fallback |
| `app/buildozer.spec` | buildozer config → debug APK |
| `style/` | git submodule → `cyclosm/cyclosm-cartocss-style` |
| `server/renderd.conf.example` | renderd config (Mapnik 4.2 plugin path, `cyclosm` map) |
| `server/tileserver-vhost.conf.example` | Apache mod_tile vhost on port **8280** |
| `scripts/setup_tileserver.sh` | one-shot server bring-up |
| `scripts/import_osm.sh` | download + merge + `osm2pgsql` import |
| `scripts/make_land_shapefile.sh` | landlocked land-polygon (see below) |
| `scripts/patch_project_mml.sh` | repoint coastline layers + compile `mapnik.xml` |
| `scripts/seed.sh` | pre-render tiles z6–13 for the bbox |
| `scripts/build_dem.sh` | contour lines + hillshade → Höhenlinien in the tiles |
| `scripts/pack_mbtiles.py` | pack a bbox into an offline `.mbtiles` (BBOX overridable) |
| `scripts/mbtiles2osmand.py` | convert `.mbtiles` → OsmAnd `.sqlitedb` raster map |

## Quick start (server, Ubuntu 26.04 / Mapnik 4.2)

```bash
git clone --recursive https://github.com/gerontec/osmcycle ~/python/osmcycle
cd ~/python/osmcycle
git submodule update --init          # if you forgot --recursive
bash scripts/setup_tileserver.sh     # packages, DB, import, renderd, apache
bash scripts/seed.sh 6 13            # optional: warm the cache
curl -o /tmp/t.png http://localhost:8280/tiles/cyclosm/12/2179/1418.png
```

## Offline pack + app

The app is **offline-first**. Bayern + Tirol ships as an MBTiles pack that the
app reads locally (no network), while higher zooms / neighbouring tiles are
pulled from the server on demand and disk-cached — like a normal slippy map
(`app/hybridsource.py`).

1. **Build the offline pack** (server, after `seed.sh`):

   ```bash
   pip install requests
   python3 scripts/pack_mbtiles.py 6 13 bayern-tirol.mbtiles   # ~hundreds of MB
   ```

2. **Build the APK**:

   ```bash
   cd app
   python3.11 -m venv ../venv-buildozer && source ../venv-buildozer/bin/activate
   pip install "cython<3.1" buildozer
   export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64   # p4a needs JDK 17
   buildozer -v android debug
   ```

3. **Sideload to the device** (USB adb):

   ```bash
   adb install -r bin/osmcycle-0.1-debug.apk
   adb shell mkdir -p /sdcard/Android/data/org.gerontec.osmcycle/files
   adb push bayern-tirol.mbtiles \
     /sdcard/Android/data/org.gerontec.osmcycle/files/bayern-tirol.mbtiles
   ```

The app looks for `bayern-tirol.mbtiles` in its external files dir (no runtime
permission needed), then `/sdcard/osmcycle/`. Set `ONLINE_URL` in
`app/main.py` to a host the phone can reach (LAN/VPN) for on-demand loading.

## Design notes / decisions

These deviate from a naïve "pip install mapnik + TileStache" plan for good
reasons — both of those are effectively dead on modern Python:

- **Rendering stack:** `renderd` + Apache `mod_tile` (the canonical OSM tile
  stack) instead of TileStache. `python3-mapnik` is **not packaged** on Ubuntu
  26.04 and `pip install mapnik` does not build against Mapnik 4.x, so a Python
  tile server was not viable. Mapnik 4.2's PostGIS reader ships as
  `postgis+pgraster.input`.
- **Serving port:** a dedicated Apache vhost on **8280** (80/443/8080/8088 were
  already taken by other services), so the existing web stack is untouched.
- **Landlocked land polygons:** CyclOSM's `project.mml` pulls ~1 GB of global
  coastline shapefiles. Bayern + Tirol has no coastline, so we substitute one
  world-covering land polygon (`make_land_shapefile.sh`). The Mapnik Map
  background is the sea colour `#8ecbeb`; the polygon paints the inland area as
  land — visually identical here, ~1 GB and lots of time saved.
- **Hillshade / contours disabled:** those layers already carry `status: off`
  in `project.mml`, so no DEM or `contours` database is required for a first
  working render. Enable them later by generating elevation data.
- **Austria data:** Geofabrik does not split Austria into states, so all of
  Austria is downloaded and the west (Tirol/Vorarlberg) is clipped to the
  render bbox `9.9,46.6,13.9,50.6` before merging with Bayern.

## Use the offline maps in OsmAnd

Convert a pack and drop it into OsmAnd's tiles folder — it then appears under
**Karte konfigurieren → Kartenquelle**:

```bash
python3 scripts/pack_mbtiles.py 6 15 alpen.mbtiles      # BBOX per region, seeded
python3 scripts/mbtiles2osmand.py alpen.mbtiles CyclOSM_Alpen.sqlitedb
adb push CyclOSM_Alpen.sqlitedb \
  /storage/emulated/0/Android/Media/net.osmand/tiles/CyclOSM_Alpen.sqlitedb
```

Note: OsmAnd's data folder can be internal *or* `Android/media/net.osmand` —
check **Einstellungen → OsmAnd Einstellungen → Datenordner** and drop the
`.sqlitedb` into that folder's `tiles/` subdir. Requires the **Online-Karten**
plugin enabled. Higher `maxzoom` = sharper (but bigger); z6–15 keeps it usable
while staying reasonable in size.

## Attribution

Map data © OpenStreetMap contributors (ODbL). Rendering style: CyclOSM
(BSD-2-Clause), see the `style/` submodule.
