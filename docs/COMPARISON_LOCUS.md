# OSMCycle vs. Locus Map

People ask why this exists when [Locus Map](https://www.locusmap.app/) already
does everything. It is a fair question, and the honest answer is: **Locus is the
better app, and OSMCycle is a different thing.** Locus is a mature, commercial
outdoor navigation app with a decade of polish behind it. OSMCycle is a
self-hosted stack that happens to have an app at one end of it.

If you want to *navigate*, install Locus Map. If you want to *own the whole
chain* — the cartography, the server, the data, the report — read on.

## The short version

|  | Locus Map 4 | OSMCycle |
|---|---|---|
| What it is | A finished product | A pipeline you run yourself |
| Who makes the map | Locus (LoMaps) or a map you import | **You do** — own render server, own style |
| Coverage | Worldwide | Bayern, Tirol, Südtirol, Kärnten |
| Cost | Free tier; Silver €10/yr, Gold €24/yr | Free — but you supply the server |
| Account | Needed for sync / live tracking | None, anywhere |
| Routing & voice navigation | **Yes** (LoRouter offline, BRouter) | **No** |
| Address / POI search | **Yes**, offline | **No** |
| Vector maps | **Yes** | No — raster tiles only |
| Track recording → GPX | Yes | Yes |
| Elevation profile | Yes, on device | Yes, on the report server |
| Where tracks end up | Locus cloud / your export | **Your own public report page** |
| Scriptable from a shell | No | **Yes** — config file + HTTP API |
| Source | Closed | Open, all of it |

## Where Locus is simply better

No point pretending otherwise. Locus gives you **turn-by-turn navigation with
voice**, offline routing, offline address and POI search, vector maps that
restyle on the fly, a map manager, sensor support (heart rate, cadence), Wear OS,
geocaching, weather, Android Auto, and web/device synchronisation. OSMCycle has
none of that and is not trying to.

Locus is also more careful in a place where we are not: it interpolates
elevations from HGT files with **bicubic** interpolation over 16 surrounding
samples. We use bilinear over 4. On a 30 m grid the difference is small, but it
is a difference, and it is not in our favour.

And Locus works everywhere on Earth. Our map stops at the borders of four
regions, because someone (me) has to render it.

## Where OSMCycle is genuinely different

**1 · You render the map, so you decide what is on it.**
Locus lets you *import* a map. OSMCycle *is* the thing that makes the map: OSM →
PostGIS → Mapnik with the CyclOSM style, plus contour lines, hillshade and MTB
scale colouring switched on in the style itself. Want different contour spacing,
a different colour for gravel, an extra layer from a shapefile? Change the style
and re-render. With Locus you are a consumer of whatever map you were given.

**2 · Your rides publish themselves — to your server.**
Press REC, ride, open the app once. The GPX uploads itself to
[a public report](https://heissa.de/web1/gpx_report.php) that *you* host: a map of
every track, a table of the stats, an elevation profile per ride, an RSS feed. No
account, no cloud, no token — the upload endpoint is deliberately open. Locus can
sync tracks, but to *Locus's* cloud, under *Locus's* terms.

**3 · The app is a scriptable object, not just a UI.**
Every setting lives in one public JSON file that the app re-reads when it changes,
and there is a localhost HTTP API for state and actions:

```bash
adb forward tcp:8765 tcp:8765
curl localhost:8765/state
curl -X POST localhost:8765/action -d '{"action": "goto", "lat": 47.42, "lon": 10.98, "zoom": 14}'
```

You can drive the whole app from a shell without touching the screen. No consumer
app does this, and it is the single feature that most changes how the thing feels
to work with.

**4 · Layers from public authorities, not from a POI store.**
Mobile phone masts (BNetzA), bathing waters (LGL), groundwater wells (GKD),
summit names, three long-distance trails — all bundled, all offline, all built
from open government data with scripts in this repo. Add your own by dropping in
a GeoJSON.

**5 · The elevation model is yours.**
Locus fills altitudes from HGT files you download onto the phone. We re-derive
every altitude *on the server* from Copernicus GLO-30, held in MariaDB as
compressed raster blocks (389 million samples, 319 MB), verified against the
source GeoTIFFs to ±0.9 m. The phone stays dumb; the model can be improved,
replaced or re-run over old tracks without touching a single device. See
[ELEVATION.md](ELEVATION.md).

Both approaches exist for the same reason, and it is worth stating plainly: **a
phone's GPS altitude is not usable for climb totals.** Without a barometer the
vertical axis is the weakest part of the fix and the error wanders while you stand
still, so summing it over a ride invents hundreds of metres of ascent. Locus
solved this with "fill altitude" from HGT; we solved it server-side. Anyone who
reports climb straight from GPS is reporting fiction.

## You can use our map *in* Locus

This is not an either/or. Locus reads **MBTiles natively** — drop
`alpen_z15.mbtiles` into Locus's `maps` folder and it appears as an offline map,
no conversion needed. (OsmAnd, by contrast, only reads `.sqlitedb`, so it needs
`scripts/mbtiles2osmand.py` first.)

```
alpen_z15.mbtiles  →  <Locus data folder>/maps/
```

So a perfectly sensible setup is: **navigate with Locus, on our cartography**, and
use OSMCycle's app when you want the recording to publish itself. Download:
<https://tmind.de/maps/>

Whether Locus can read *the same single copy* that OSMCycle uses depends on where
Locus's data folder lives on your Android version — on Android 11+ scoped storage
makes one shared copy hard for every app involved. We have not tested it.

## Honest list of what OSMCycle lacks

- No routing, no navigation, no voice guidance.
- No search — not for addresses, not for POIs.
- Raster tiles only; no vector map, no on-the-fly restyling.
- Four regions, not the world.
- No sensors, no Wear OS, no Android Auto, no geocaching.
- No barometer support; the live altitude readout is raw GPS (only the *report*
  is DEM-corrected).
- The APK is debug-signed and distributed outside the Play Store.
- One person maintains it. Locus has a company.

## When to pick which

**Use Locus Map if** you want to be guided somewhere, search for things, ride
outside these four regions, or simply want an app that works without you running
a server.

**Use OSMCycle if** you want to control the cartography end to end, keep your
tracks on infrastructure you own, publish them publicly without an account, or
drive the app from a script.

**Use both** — the map is the same file.

---

Sources for the Locus facts above:
[feature comparison](https://www.locusmap.app/comparison/),
[Premium](https://www.locusmap.app/premium/),
[external maps](https://docs.locusmap.app/doku.php?id=manual:user_guide:maps_external),
[elevation in Locus](https://www.locusmap.app/all-you-wanted-to-know-about-elevation-in-locus/).
Checked July 2026; Locus moves fast, so verify before relying on any of it.
