# Elevation: how OSMCycle gets its altitude numbers

Every altitude you see in the [online report](https://heissa.de/web1/gpx_report.php) —
the start/summit altitude, the climb in metres, the vertical speed, and the
elevation profile under the map — comes from a **digital elevation model**, not
from the phone's GPS. This document explains why, where the data comes from, how
it is stored, and how it is queried.

## Why not the GPS altitude?

A GPS receiver without a barometer solves altitude from satellite geometry
alone, and that is the weakest axis of the fix: the satellites are all *above*
the receiver, so the vertical component is poorly constrained. In practice a
phone reports 10–30 m of vertical error, and — worse for our purpose — that
error **wanders** while you stand still. Integrating those wobbles over a ride
invents hundreds of metres of climb that never happened.

A track recorded on the phone therefore keeps its GPS altitudes only as a
fallback (`<ele>` in the GPX). Everything the report computes is re-derived from
the elevation model at the recorded lat/lon.

## The data: Copernicus GLO-30

* **Source:** Copernicus DEM GLO-30, the ESA/EU global elevation model, 1 arc
  second ≈ **30 m** ground sampling. Free and open, no login, no key.
* **Distribution:** the AWS Open Data mirror, one GeoTIFF per 1°×1° cell:
  `https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N47_00_E011_00_DEM/...`
* **Coverage we hold:** Bayern, Tirol, Südtirol and Kärnten — the same four
  regions the offline map covers. That is **32 tiles**, about 389 million
  elevation samples.

One quirk that matters and is easy to get wrong: **above 50° N, Copernicus
switches the longitude spacing to 1.5″** to keep the ground resolution roughly
square as the meridians converge. Our N50 tiles are therefore 2400 columns wide,
not 3600. Nothing may assume a fixed grid size — the georeference is stored per
tile.

## Storage: raster blocks in MariaDB, not one row per point

The tiles live in the `wagodb` MariaDB instance, in two tables.

**A row per elevation point is not an option.** 389 million rows, each holding
two coordinates and one short integer, would cost tens of gigabytes plus an
index larger than the payload, and every profile would become a 400-row lookup
storm. The raster is stored the way a raster wants to be stored: as tiles of
tiles.

```sql
dem_tile (lat_deg, lon_deg,          -- SW corner of the 1° cell
          width, height,             -- grid size (2400×3600 above 50° N!)
          origin_lat, origin_lon,    -- centre of pixel (0,0), top-left
          px_lat, px_lon,            -- step per pixel; px_lat is negative
          blocksize)                 -- 256

dem_block (lat_deg, lon_deg, brow, bcol,
           data)                     -- zlib(int16 little-endian, row-major)
```

* One `dem_block` row is a **256×256 patch of int16 metres**: 128 kB raw, about
  60 kB after zlib. A point query decompresses exactly one of them.
* Elevations are rounded to whole metres. `int16` covers −32768…32767, so the
  Dead Sea and Everest both fit with room to spare; **−32768 is reserved as
  nodata**.
* A whole 1° tile as a single blob would be 26 MB and would be rejected by
  MariaDB's `max_allowed_packet` (16 MB). 256-blocks always fit — that is a
  reason for the block size, not just a preference.

What this costs in practice, for all four regions:

| | |
|---|---|
| tiles | 32 |
| blocks | 6 750 |
| raw raster | 885 MB |
| stored in MariaDB | **319 MB** (zlib, ~36 %) |

## Lookup: bilinear, not nearest

`dem_db.py` turns a lat/lon into metres:

```python
from dem_db import DemDB
dem = DemDB()
dem.elevation(47.6812, 11.5794)     # -> 687.3
```

It finds the 1° tile, converts lat/lon to a fractional row/column with that
tile's own georeference, fetches the (cached) 256-block, and **interpolates
bilinearly** between the four surrounding samples.

Bilinear rather than nearest-neighbour is a deliberate choice: on a 30 m grid a
track point almost never lands exactly on a raster point. Nearest-neighbour
snaps to the closest sample, so a track walking diagonally across the grid gets
its altitude in 30 m steps — visible in the profile as a staircase, and it
inflates the climb total, because every step is counted as a real ascent. At
tile edges and around nodata the code falls back to nearest, which is better
than returning nothing.

The block cache holds the last 32 decompressed blocks (~4 MB). One track stays
within a handful of blocks, so a whole profile is computed from a couple of
decompressions.

### Verified against the source

The DB path is checked against the original GeoTIFFs (`dem_check.py`). Bilinear
vs. the GeoTIFF's nearest-neighbour sample:

| | DB (bilinear) | GeoTIFF (nearest) | Δ |
|---|---|---|---|
| Lenggries | 687.3 m | 686.9 m | +0.4 m |
| Brauneck | 1281.3 m | 1282.0 m | −0.7 m |
| Zugspitze | 2948.0 m | 2948.7 m | −0.8 m |
| Tegernsee | 745.6 m | 744.7 m | +0.9 m |
| Kufstein | 482.4 m | 483.3 m | −0.9 m |

All within ±0.9 m — exactly the sub-pixel disagreement bilinear *should* have
with nearest, and proof that the georeference survives the trip into the
database: an off-by-one row, a flipped axis or a wrong pixel size would show up
here as tens or hundreds of metres, not centimetres.

## From elevations to the numbers in the report

`gpx_report.py` runs hourly on the server and, per track:

1. Looks up the elevation of every trackpoint (DEM first, GPS `<ele>` only if
   the point falls outside the coverage).
2. **Climb (`Hm ↑`)** is summed from a **100 m distance-sampled** version of the
   track, not from consecutive points. Summing raw point-to-point differences
   would add up the model's own metre-level noise over thousands of points and
   report a climb far larger than the real one. Resampling by distance first
   removes that.
3. **Summit** is the highest DEM point; the "to summit" distance, duration and
   vertical speeds are measured against it.
4. The **elevation profile** shipped to the browser is
   `[[km, m, lat, lon], …]` over the *whole* track (~400 points), while the map
   line is drawn only up to the summit. That is why the profile carries its own
   lat/lon: hovering it puts a marker at the matching place on the map, and that
   has to work on the descent too.

The profile itself is plain inline SVG — a polyline, an area fill and a hover
crosshair. It is not worth a charting library.

## Files

| file | role |
|---|---|
| `schema.sql` | the two tables above — apply it, or let `dem_import.py` do it |
| `dem_import.py` | downloads the missing GLO-30 tiles and imports them as blocks |
| `dem_db.py` | `DemDB.elevation(lat, lon)` — bilinear lookup against MariaDB |
| `dem_check.py` | verifies the DB against the original GeoTIFFs |
| `gpx_report.py` | hourly report generator: elevations, climb, profile |

## Attribution

Contains modified Copernicus DEM data. © DLR e.V. 2010–2014 / © Airbus Defence
and Space GmbH 2014–2018, provided under the
[Copernicus DEM licence](https://spacedata.copernicus.eu/documents/20123/121286/CSCDA_ESA_Mission-specific+Annex.pdf).
