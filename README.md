# OSMCycle — CyclOSM cycling stack for Bayern + Tirol + Südtirol + Kärnten

## The idea

**One map, many layers, and rides that report themselves.**

Most cycling setups make you choose: an online map that dies without signal, or
an offline map that knows nothing but roads. OSMCycle is one coherent loop
instead — you render the map yourself, carry it offline, and every ride you
record finds its own way back to a public report without you touching a cable.

**1 · One map.** A self-hosted [CyclOSM](https://www.cyclosm.org/) raster tile
server with **contour lines, hillshade and MTB-scale colouring**, rendered from
OpenStreetMap for Bayern, Tirol, Südtirol and Kärnten. The whole thing is packed
into a single **6.9 GB `alpen_z15.mbtiles`** (zoom 6–15) that lives on the phone.
No signal needed, ever. Tiles that are missing get streamed from the public tile
server and cached, so the map degrades gracefully instead of going blank.

**2 · Layers on top of it.** The same map carries switchable overlays, all drawn
client-side from bundled data, all working offline: three long-distance hiking
trails, summit names, and point layers built from public data — mobile phone
masts (BNetzA), bathing waters (LGL) and groundwater wells (GKD). Your own
recorded tracks are just another layer.

**3 · Rides report themselves.** Press **● REC**, ride, press stop. The track is
written as GPX into a public folder on the phone, and the next time you open the
app it **uploads itself** to the report server — no Syncthing, no PC, no cable,
no account. On the server an hourly job re-derives every altitude from a **30 m
elevation model** (the phone's GPS altitude is far too noisy for climb totals),
computes distance, climb, duration and vertical speed, and publishes the result:

**➡ Live report: https://heissa.de/web1/gpx_report.php**

The report is a map of all your tracks, a sortable table, and — per ride — a
detail map with an elevation profile whose hover marker walks along the route.
Anyone can upload; there is no token and no login.

```
          ┌──────────────── you render it ────────────────┐
OSM data ─┤ osm2pgsql → PostGIS → Mapnik/CyclOSM → renderd ├─▶ tile server :8280
   + DEM  └───────────────────────┬───────────────────────┘
                                  │  pack a bbox
                                  ▼
                        alpen_z15.mbtiles (6.9 GB, z6–15)
                                  │  carried on the phone
                                  ▼
   ┌──────────────────── the app ─────────────────────┐
   │  offline map + layers (trails, peaks, masts, …)  │
   │  ● REC  →  GPX in /sdcard/osmcycle/              │
   └───────────────────────┬──────────────────────────┘
                           │  auto-upload, max 1×/24 h, no token
                           ▼
              gpx_upload.php ──▶ hourly gpx_report.py
                                   │  elevations from Copernicus GLO-30 (MariaDB)
                                   ▼
                            gpx_report.php  ← map + table + elevation profile
```

Everything below is how each piece is built. Rendering is **CPU-bound**
(Mapnik/Cairo) — no GPU needed on the server; the phone only does OpenGL
compositing.

> **"Why not just use Locus Map?"** Fair question — Locus is the better *app*, and
> this is a different kind of thing. The honest comparison, including what
> OSMCycle cannot do, is in
> **[docs/COMPARISON_LOCUS.md](docs/COMPARISON_LOCUS.md)**. Short version: Locus
> reads our `alpen_z15.mbtiles` natively, so you can navigate with Locus on our
> cartography and still let OSMCycle publish your rides.

---

## Get the map without rendering it yourself

The pre-rendered offline map is ready to download:

**➡ https://tmind.de/maps/**

| File | Area | Size |
|------|------|------|
| `alpen_z15.mbtiles` | Bayern + Tirol + Südtirol + Kärnten, zoom 6–15 | 6.9 GB |

The public tile server `maps/tile.php` serves **z6–15 straight out of that same
file**, over TLS and independent of the home render server. So you have two ways
in, and the app uses both:

* **Just install the app.** It streams tiles from `tile.php` — no big download,
  no setup. Viewed tiles are cached and keep working offline afterwards.
* **Go fully offline.** Let the app download `alpen_z15.mbtiles` (it offers to,
  on first start) or push it yourself to `/sdcard/maps/tiles/`.

### 📲 Download & install the app

One address, always the newest APK — as a link and as a QR code. Both point to
the same place, so neither ever needs updating when a release goes out:

<p align="center">
  <b>➡ <a href="https://heissa.de/web1/get_apk.php">https://heissa.de/web1/get_apk.php</a></b><br>
  <br>
  <img src="docs/osmcycle_apk_qr.png" alt="QR code for https://heissa.de/web1/get_apk.php" width="220"><br>
  <b>Point your phone's camera at the QR code → downloads the latest APK</b>
</p>

`get_apk.php` looks up the newest GitHub release and redirects to its APK asset.
If GitHub is unreachable it falls back to the newest APK in its own mirror at
`heissa.de/web1/apk/`. It caches GitHub's answer for **one hour**, so right after
a release it may still hand out the previous APK.

- **Alternatively, straight from GitHub:**
  **➡ https://github.com/gerontec/osmcycle/releases/latest** → tap the
  `osmcycle-vX.apk` asset.
- **Auto-update:** install [Obtainium](https://github.com/ImranR98/Obtainium) →
  "Add App" → the repo URL above. It picks up every new release.
  The app itself does **not** self-update — that is Obtainium's job alone. For an
  update to be installable at all, every APK must be signed with the same key:
  see [Always sign with the same debug keystore](#️-always-sign-with-the-same-debug-keystore).

**Installing without developer mode** (the normal route, no USB/ADB): the first
time you open the APK, Android asks whether it may "install from this source" →
**allow** it (the *"Install unknown apps"* setting for your browser or file
manager). Developer options / USB debugging are only needed for `adb install`.
The download-and-tap route works on Android 16 too — it is just that one-off
per-app permission. (Some vendor ROMs, MIUI for example, add their own extra
dialog — just confirm it.)

## The Android app

Offline-first: it reads **`alpen_z15.mbtiles`** (all four regions, z6–15, with
contour lines) from the **public** folder `/sdcard/maps/tiles/`, and pulls
missing tiles from the server on demand (`hybridsource.py`).

- CyclOSM base map with **contour lines, hillshade and MTB scale**.
- **Zoom past the offline pack (z16–18), live.** The pack stops at z15, and so
  does `tile.php` — it is backed by the very same file. Above that the app
  fetches from the **public CyclOSM server**, which renders in the identical
  style, so crossing the boundary is invisible. Everything up to z15 stays
  offline; only z16+ needs a connection, and without one those tiles simply
  stay blank.
- **Position arrow** that rotates to the GPS heading, and a **◎ focus** button
  that centres *and* zooms to the offline map's deepest level (z15) — centred but
  zoomed out is useless on the trail.
- **● REC** records GPS tracks as **GPX 1.1** into the public folder
  `/sdcard/osmcycle/`. Recording follows a live Android `LocationListener`
  (fresh fixes, not the stale last-known cache), so a real ride is captured at
  full length instead of collapsing into a stationary blob.
- **A recording survives the phone falling asleep.** Points are logged on Kivy's
  `Clock`, and that only ticks while the CPU is awake — screen off, the device
  suspends and the track silently stops growing. (One of our own tracks has a
  380 s hole from exactly this.) While recording, the app now arms an
  `AllowWhileIdle` alarm — the one kind Android still delivers through Doze —
  which wakes the CPU and writes a point. It does **not** hold the CPU up: it
  bounds how much track a suspend can swallow, to `gps.wake_interval` (600 s by
  default, `0` disables). Android throttles these alarms to roughly one per
  9 min per app, so values below ~540 are quietly stretched to that floor.
- **Auto-upload to the online report** — see below; no Syncthing, no PC.
- **≡ Layer** menu toggles the overlays: the 3 hiking trails (Karnischer,
  Maximiliansweg, Tiroler Höhenweg), summit names, mobile masts, bathing waters
  and groundwater wells — all drawn client-side, offline, viewport-culled. The
  counts are the real bundled datasets: 13 980 masts, 373 bathing waters, 428
  groundwater wells.
- **Everything is a setting**, and every setting lives in one file.

<p align="center">
  <img src="docs/screenshot_layers.png" alt="OSMCycle layer menu: hiking trails, summit names, masts, bathing waters, groundwater wells" width="300"><br>
  <i>The ≡ Layer menu — every overlay works offline</i>
</p>

### Configuration and remote control

All settings sit in **`/sdcard/osmcycle/config.json`** — a public path, so you can
read and edit it with plain `adb` and no root. The app writes the file on first
start and re-reads it whenever it changes, so a config push takes effect within
seconds, without restarting anything:

```bash
adb shell cat /sdcard/osmcycle/config.json
```

```json
{
  "map":     { "start_lat": 47.68, "start_zoom": 13, "max_zoom": 18,
               "hizoom_from": 16, "focus_zoom": 15, "follow": false },
  "layers":  { "peaks": false, "masts": false, "bathing": false, "gpx": [] },
  "gps":     { "idle_interval": 60, "rec_interval": 10, "wake_interval": 600 },
  "record":  { "autostart": false },
  "ui":      { "font_size": 11, "bold": false, "panel_opacity": 0.78 },
  "control": { "http_enabled": true, "port": 8765 }
}
```

> **Upgrading from ≤ v1.7:** your existing `config.json` still says
> `"max_zoom": 15`, and the file wins over the new default — so z16+ stays out of
> reach until you raise it. New keys you never had (`hizoom_from`,
> `wake_interval`) do come from the defaults, so those work untouched.
>
> ```bash
> adb shell 'sed -i "s/\"max_zoom\": 15/\"max_zoom\": 18/" /sdcard/osmcycle/config.json'
> ```

The same state is exposed over a small HTTP API bound to **127.0.0.1** — reachable
through `adb forward`, never from the network. It exists so the app can be driven
and inspected without navigating the screen (handy for scripting, testing, and
for letting an AI agent operate it):

```bash
adb forward tcp:8765 tcp:8765
curl localhost:8765/state                                     # position, zoom, layers, REC
curl -X POST localhost:8765/config -d '{"ui.font_size": 9}'   # applied live
curl -X POST localhost:8765/action -d '{"action": "focus"}'
curl -X POST localhost:8765/action -d '{"action": "goto", "lat": 47.42, "lon": 10.98, "zoom": 14}'
```

Actions: `focus`, `zoom_in`, `zoom_out`, `set_zoom`, `goto`, `record_start`,
`record_stop`. Kivy is not thread-safe, so anything the HTTP thread triggers is
bounced onto the main thread via `Clock` before it touches a widget.

### GPX upload → online report (no Syncthing needed)

Recorded tracks travel from the phone into the public report at
**https://heissa.de/web1/gpx_report.php** by themselves — no Syncthing, no PC, no
cable.

```
App (background thread, at most 1×/24 h, on open)
  │  HTTP POST  (multipart, only track_*.gpx, ≤10 MB)
  ▼
https://heissa.de/web1/gpx_upload.php      ← public, token-free, anyone may upload
  │  saves to
  ▼
/var/www/web1/gpx_uploads/<YYYY-MM-DD_HH-MM_Weekday>.gpx
  │  hourly cron scans the folder (gpx_report.py)
  ▼
https://heissa.de/web1/gpx_report.php      ← Bootstrap + Leaflet: maps, table, profile
```

- **When:** a daemon thread starts when the app opens and uploads at most **once
  per 24 h** (stamp file `.last_upload` in the GPX folder). Nothing runs in the
  background while the app is closed — opening it once is enough.
- **What:** only your own recordings (`track_*.gpx`), renamed to the
  `YYYY-MM-DD_HH-MM_Weekday.gpx` convention the report parses for its date
  column. The bundled demo routes are **not** uploaded.
- **No security check** (by design — anyone may upload): the endpoint only checks
  the `.gpx` extension and the size (≤10 MB). No token, no login.
- **Allowed over mobile data** (a GPX is tiny). Failures are silently ignored and
  retried the next time the app opens.

> The report drops tracks shorter than **1 km / 2 vertical metres** (noise and
> drift protection), so only real rides show up.

### What the report shows

- An **overview map** with every track; click a line for the detail view.
- A **sortable table**: start place, altitudes, distance, distance to summit,
  duration, average speed, vertical speed up and down, total climb.
- A **detail view** per ride: the route on the map, and an **elevation profile**
  below it. Hovering the profile puts a marker at the matching point on the map —
  including on the descent, which is why the profile carries its own coordinates.
- A switchable **base map**: our own CyclOSM tiles, CyclOSM worldwide, OSM,
  OpenTopoMap or satellite imagery.
- An [RSS feed](https://heissa.de/web1/rss_gpx.php) of new rides.

**All altitudes come from a digital elevation model, not from the phone.** A GPS
without a barometer is weakest exactly on the vertical axis, and its error
*wanders* while you stand still — integrated over a ride, that invents hundreds
of metres of climb that never happened. The server therefore re-derives every
altitude from Copernicus GLO-30 (30 m), held in MariaDB as raster blocks:
**[docs/ELEVATION.md](docs/ELEVATION.md)** explains the model, the storage layout
and why the lookup is bilinear.

## Repository layout

| Path | What |
|------|------|
| `app/main.py` | Kivy app: map, position arrow, focus button, REC, layer menu |
| `app/appconfig.py` | `config.json` + the localhost control API |
| `app/hybridsource.py` | tile source: offline MBTiles first, network on miss |
| `app/track.py` | GPX recorder + track/position/trail/point map layers |
| `app/wanderwege.json` | 3 hiking trails, simplified, bundled for the layer menu |
| `app/buildozer.spec` | buildozer config → debug APK |
| `style/` | git submodule → `cyclosm/cyclosm-cartocss-style` |
| `server/renderd.conf.example` | renderd config (Mapnik 4.2 plugin path, maps) |
| `server/tileserver-vhost.conf.example` | Apache mod_tile vhost, port **8280** |
| `server/wanderwege.xml` | Mapnik overlay style for the 3 trails |
| `server/gpx_report.py` | hourly generator of the public GPX report (Bootstrap+Leaflet) |
| `server/gpx_upload.php` | public token-free GPX drop endpoint for the app |
| `server/dem/schema.sql` | DB schema for the elevation model (2 tables, raster blocks) |
| `server/dem/dem_import.py` | import Copernicus GLO-30 into MariaDB → [docs/ELEVATION.md](docs/ELEVATION.md) |
| `server/dem/dem_db.py` | `elevation(lat, lon)` — bilinear lookup against the DEM |
| `server/dem/dem_check.py` | verify the imported DEM against the source GeoTIFFs |
| `scripts/setup_tileserver.sh` | one-shot server bring-up |
| `scripts/import_osm.sh` | download + merge + `osm2pgsql` import |
| `scripts/make_land_shapefile.sh` | landlocked land-polygon substitute |
| `scripts/patch_project_mml.sh` | repoint coastline layers + compile `mapnik.xml` |
| `scripts/build_dem.sh` | **contours + hillshade → contour lines in the tiles** |
| `scripts/build_wanderwege.sh` + `tirol_route.sql` | build the trail overlay |
| `scripts/seed.sh` | pre-render a bbox |
| `scripts/pack_mbtiles.py` / `pack_alpen.py` | pack bbox(es) → offline `.mbtiles` |
| `scripts/mbtiles2osmand.py` | convert `.mbtiles` → OsmAnd `.sqlitedb` |
| `scripts/export_layers.py` | export the overlays as GPX for foreign map apps (iOS, Locus, …) |

## Server bring-up (Ubuntu 26.04 / Mapnik 4.2)

```bash
git clone --recursive https://github.com/gerontec/osmcycle ~/python/osmcycle
cd ~/python/osmcycle && git submodule update --init
bash scripts/setup_tileserver.sh    # packages, DB, import, land polygon, renderd, apache
bash scripts/build_dem.sh           # contour lines + hillshade (pyhgtmap + gdaldem)
bash scripts/build_wanderwege.sh    # trail overlay at /tiles/wanderwege/
curl -o /tmp/t.png http://localhost:8280/tiles/cyclosm/17/69749/45644.png
```

The tile vhost's `Listen 8280` is dual-stack, so tiles are served over **IPv6**
too (`http://[<global-v6>]:8280/…`). For access away from home you need an
inbound IPv6 firewall rule on the router and, since the prefix is dynamic, a DNS
**AAAA** name (an IPv6 literal breaks when the prefix rotates).

## Build the app

```bash
cd app
python3.11 -m venv ../venv-buildozer && source ../venv-buildozer/bin/activate
pip install "cython<3.1" buildozer
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64      # p4a needs JDK 17
buildozer -v android debug                              # p4a.branch = release-2024.01.21
adb install -r bin/osmcycle-1.7-arm64-v8a-debug.apk

# optional: push the offline map instead of letting the app download it
adb push alpen_z15.mbtiles /sdcard/maps/tiles/alpen_z15.mbtiles
```

Set `ONLINE_URL` in `app/main.py` to a host the phone can reach (LAN IPv4, or the
server's IPv6 / a DNS AAAA name for mobile use).

> ### ⚠️ Always sign with the same debug keystore
>
> Android only installs an update over an existing app if **both APKs are signed
> with the same key**. A debug build uses `~/.android/debug.keystore` — and
> **buildozer generates that file afresh on every new machine**, with a different
> key.
>
> So the first time you build a release on a different computer, Obtainium will
> dutifully fetch the new APK and Android will refuse it with a signature
> conflict ("App not installed"). To users it looks like a broken release; they
> would have to uninstall the app first (losing their app-private data).
>
> **Before the first build on a new machine**, bring the old keystore along and
> check its fingerprint against the last published APK:
>
> ```bash
> scp old-machine:~/.android/debug.keystore ~/.android/debug.keystore
>
> # fingerprint of the keystore …
> keytool -list -v -keystore ~/.android/debug.keystore \
>         -storepass android -alias androiddebugkey | grep SHA256:
>
> # … must match the one in the last published APK
> keytool -printcert -jarfile osmcycle-v<latest>.apk | grep SHA256:
> ```
>
> The currently valid fingerprint is
> `17:18:6F:D0:F4:BD:FF:88:06:65:69:6E:23:8F:48:84:D2:5F:51:C3:38:AA:55:E0:0A:FB:23:9E:4E:EC:B4:E0`.
> If it differs, **do not tag a release** — the auto-update would be broken for
> every existing user.

## The 3 hiking trails (Wanderwege overlay)

- **Karnischer Höhenweg** and **Maximiliansweg** come straight from their OSM
  route relations (member ways).
- The **Tiroler Höhenweg** is *not* a named OSM route, so it is routed along OSM
  trails through its huts (Mayrhofen → Landshuter/Sattelberg → Tribulaunhütte →
  St. Martin am Schneeberg → Zwickauer Hütte → Stettiner Hütte → Bockerhütte →
  Meran) with **pgRouting** (`pgr_dijkstraVia`, see `tirol_route.sql`). It is
  *not* the same as the Meraner Höhenweg (a loop around Meran) — they only share
  the final section near the Stettiner Hütte.

Served transparently at `/tiles/wanderwege/`; usable as an OsmAnd overlay or via
the app's layer menu.

## On iPhone — and in any other map app

There is no iOS app, and there probably never will be: Apple has no sideloading,
so the QR-code-and-tap route above cannot exist there. But **you do not need our
app to use any of this on an iPhone.**

**The map:** both [Guru Maps](https://gurumaps.app/) and
[Cartograph Maps 3](https://apps.apple.com/us/app/cartograph-maps-3/id1588186796)
read **MBTiles natively** on iOS. Put `alpen_z15.mbtiles` into iCloud Drive, open
it in the Files app, "Copy to" the map app — and you have our CyclOSM cartography,
contour lines and hillshade included, fully offline.

**The layers:** these do *not* come with the map. A raster pack carries the base
map and nothing else; every overlay in OSMCycle is drawn by the app from its own
data. So they are published separately, as plain **GPX** — the one format every
map app reads, and each file lands as its own collection that can be switched on
and off, which is exactly what our layer menu does:

| Layer | File | Contents |
|---|---|---|
| Summit names | [`gipfel.gpx`](https://heissa.de/web1/layers/gipfel.gpx) | 34 114 named summits |
| Mobile masts (BNetzA) | [`sendemasten.gpx`](https://heissa.de/web1/layers/sendemasten.gpx) | 13 980 sites |
| Bathing waters (LGL) | [`badestellen.gpx`](https://heissa.de/web1/layers/badestellen.gpx) | 373 |
| Groundwater wells (GKD) | [`grundwasser.gpx`](https://heissa.de/web1/layers/grundwasser.gpx) | 428 |
| Karnischer Höhenweg | [`wanderweg_karnischer.gpx`](https://heissa.de/web1/layers/wanderweg_karnischer.gpx) | track |
| Maximiliansweg | [`wanderweg_maximiliansweg.gpx`](https://heissa.de/web1/layers/wanderweg_maximiliansweg.gpx) | track |
| Tiroler Höhenweg | [`wanderweg_tiroler_hoehenweg.gpx`](https://heissa.de/web1/layers/wanderweg_tiroler_hoehenweg.gpx) | track |

All of it: <https://heissa.de/web1/layers/> — regenerate with
`scripts/export_layers.py`. The same files work in Locus, OsmAnd, or anything else
that imports GPX; they are not iOS-specific.

**Uploading your rides:** the report's upload endpoint is a token-free HTTP POST,
so an **Apple Shortcut** that picks a `.gpx` and posts it to
`https://heissa.de/web1/gpx_upload.php` is enough to appear in the
[public report](https://heissa.de/web1/gpx_report.php) — no app, no account, no
developer program.

> Caveat, stated plainly: the GPX files are validated as GPX 1.1 and served over
> HTTPS, but **we have not tested the import on an actual iPhone** — no device
> here. If a layer misbehaves in Guru or Cartograph, open an issue.

## Using the maps in OsmAnd

```bash
python3 scripts/mbtiles2osmand.py alpen_z15.mbtiles CyclOSM_Alpen.sqlitedb
adb push CyclOSM_Alpen.sqlitedb <OsmAnd-data-folder>/tiles/CyclOSM_Alpen.sqlitedb
```

OsmAnd reads **only** `.sqlitedb` (BigPlanet), never `.mbtiles`, so the map has to
be converted. Note that on Android 12+ OsmAnd cannot share a single copy of the
map with another app: it does not declare `MANAGE_EXTERNAL_STORAGE` (Play Store
policy), scoped storage hides foreign files from it, and FUSE forbids symlinks on
`/sdcard`. A second copy is unavoidable — see [docs/OSMAND_USERS.md](docs/OSMAND_USERS.md).

Alternatively point OsmAnd at the live server with a tiny online-source
`.sqlitedb` whose `info.url` is `http://[<v6>]:8280/tiles/cyclosm/{0}/{1}/{2}.png`
(base) and `…/tiles/wanderwege/…` (overlay). Enable the **Online maps** plugin,
then select them under **Configure map → Map source / Overlay map**.

## Using the maps in Locus Map — one file, both apps

Locus reads `.mbtiles` natively, so unlike OsmAnd it needs no conversion: drop
`alpen_z15.mbtiles` in and it shows up in **Karten-Manager → OFFLINE** as
*CyclOSM Alpen* (the `name` out of the MBTiles metadata). And it renders it well
— on both test devices it is a genuinely usable offline map.

The interesting part is that Locus can share the **single** 6.9 GB file with
OSMCycle, which OsmAnd cannot. It takes one insight, because the obvious routes
are all dead ends:

* Locus does not declare `MANAGE_EXTERNAL_STORAGE` either, so it cannot read
  `/sdcard/maps/tiles` — no matter what you put there.
* It has no setting for an external map directory.
* Its **Externe Links** feature, which used to reference maps in foreign
  folders, has been **discontinued** — the app says so in the dialog itself.
  *Import* is what is left, and import **copies** into Locus's own folder.

So the file has to live in Locus's folder. The trick is *which* one: Locus keeps
maps in two places, and while `Android/data/…` is sandboxed away from everyone,
**`Android/media/…` is not**. All-files access covers it (only `Android/data` and
`Android/obb` are excluded). Put the map there and both apps reach the same
bytes:

```bash
adb shell mkdir -p /sdcard/Android/media/menion.android.locus/maps
adb shell mv /sdcard/maps/tiles/alpen_z15.mbtiles \
             /sdcard/Android/media/menion.android.locus/maps/
```

`find_mbtiles()` searches that path (see `LOCUS_MAPS`), so OSMCycle keeps working
— verified with the network switched off, on an e-ink HiBreak (Android 14) and a
Poco (Android 12). It needs **All files access**; the app asks for it, or:

```bash
adb shell appops set org.gerontec.osmcycle MANAGE_EXTERNAL_STORAGE allow
```

The `mv` is a rename within the same volume and finishes instantly — no 7 GB
copy, and no second one on disk afterwards.

**The layers** do not travel with the raster pack (it carries the base map and
nothing else). Export them and open them in Locus:

```bash
scripts/export_layers.py                 # -> GPX for every overlay
adb shell am start -a android.intent.action.VIEW \
  -d "file:///path/to/wanderweg_karnischer.gpx" \
  -t "application/gpx+xml" menion.android.locus
```

Each import lands as its own collection that can be switched on and off. Pick the
target folder in the dialog — the default drops everything into the root, which
gets unwieldy fast. Worth knowing before you import the masts: OSMCycle draws
those 13 980 points viewport-culled straight from JSON, while Locus writes every
one of them into its point database.

Locus can also be driven **without its UI** — track recording, navigation and a
map overlay that bypasses its database entirely — through an intent API. There is
no config file (its settings sit in root-only SharedPreferences), so this is the
only handle there is: [docs/locusAPI.md](docs/locusAPI.md).

## Design notes / decisions

- **Rendering stack:** `renderd` + Apache `mod_tile` (the canonical OSM stack).
  `python3-mapnik` is not packaged on Ubuntu 26.04 and `pip install mapnik` will
  not build against Mapnik 4.x, so TileStache/python-mapnik was a dead end.
  Mapnik 4.2's PostGIS reader ships as `postgis+pgraster.input`.
- **Contours + hillshade:** contours from `pyhgtmap --sources=view3` (no NASA
  account needed) loaded into a `contours` DB; hillshade via `gdaldem` →
  `dem/shade.vrt`. The style's hillshade and contour layers (shipped
  `status: off`) are switched on in `build_dem.sh`. pyhgtmap tags contours `ele`
  (not `height`) — caught and renamed on import.
- **Landlocked land polygon:** replaces CyclOSM's ~1 GB coastline shapefiles with
  one world-covering polygon; Mapnik's sea-colour background then reads as land
  everywhere inland.
- **Port 8280:** a dedicated vhost, so the existing web stack (80/443/…) stays
  untouched; dual-stack for IPv6.
- **Austria data:** Geofabrik does not split Austria — the whole country is
  downloaded and clipped per region (Tirol, Südtirol via Italy nord-est, Kärnten)
  before being merged with Bayern.
- **APK build:** `p4a.branch = release-2024.01.21` (Python 3.11). p4a master
  builds Python 3.14, which kivy 2.3.0's Cython C does not compile against.
- **Elevations from a DEM, not from GPS:** see
  [docs/ELEVATION.md](docs/ELEVATION.md) — including why 389 million elevation
  samples are stored as raster blocks rather than one row per point.

## Attribution

Map data © OpenStreetMap contributors (ODbL). Style: CyclOSM (BSD-2-Clause,
`style/` submodule). Contour lines and hillshade in the tiles: viewfinderpanoramas
(SRTM-derived). Elevations in the report: contains modified Copernicus DEM data
(GLO-30) © DLR e.V. 2010–2014 / © Airbus Defence and Space GmbH 2014–2018.
