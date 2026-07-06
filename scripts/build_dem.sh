#!/usr/bin/env bash
# Build CyclOSM elevation data (contour lines + hillshade) and enable those
# layers, so the tiles show Höhenlinien + Reliefschattierung like the official
# CyclOSM (openstreetmap.org layers=Y). Run after the main osm2pgsql import.
#
#   pip install pyhgtmap        # maintained phyghtmap fork (no NASA account
#                               # needed with --sources=view3)
#
# BBOX covers Bayern + Tirol + Südtirol + Kärnten.
set -euo pipefail
STYLE_DIR="${1:-style}"
BBOX_A="9.9:46.2:15.1:50.6"      # LEFT:BOTTOM:RIGHT:TOP (lon/lat)
cd "$STYLE_DIR/dem"

# --- 1. contour lines (10 m) from viewfinderpanoramas 3" DEM ---------------
pyhgtmap -a "$BBOX_A" -s 10 --sources=view3 \
  --max-nodes-per-tile=0 --max-nodes-per-way=0 --pbf -j 8 -o contour_

# --- 2. load contours into the `contours` PostGIS database -----------------
sudo -u postgres createdb -O "$USER" contours 2>/dev/null || true
sudo -u postgres psql -d contours -c "CREATE EXTENSION IF NOT EXISTS postgis;"
osm2pgsql --slim -d contours --cache 4000 --style contours.style ./contour_*.osm.pbf
# CyclOSM expects table `contours` with a `geometry` column (not planet_osm_line/way)
psql -d contours -c 'DROP TABLE IF EXISTS contours;
  ALTER TABLE planet_osm_line RENAME TO contours;
  ALTER TABLE contours RENAME COLUMN way TO geometry;
  CREATE INDEX ON contours USING gist (geometry);
  CREATE INDEX ON contours (height);
  GRANT SELECT ON contours TO "_renderd"; GRANT USAGE ON SCHEMA public TO "_renderd";'

# --- 3. hillshade VRT from the downloaded .hgt tiles -----------------------
gdalbuildvrt dem.vrt hgt/**/*.hgt
gdaldem hillshade -s 111120 -compute_edges -co compress=lzw dem.vrt hillshade.tif
gdaldem color-relief hillshade.tif -alpha shade.ramp shade_rgba.tif -co compress=lzw
gdalbuildvrt shade.vrt shade_rgba.tif

# --- 4. enable hillshade + contour layers in project.mml -------------------
# They ship with `status: off`; flip the ones we now have data for.
cd ..
python3 - <<'PY'
import re
p="project.mml"; s=open(p).read()
# turn the hillshade + contours* layers on (status: off -> on within those blocks)
for lid in ("hillshade","contours100","contours50","contours20","contours10"):
    s=re.sub(r"(- id: %s\b.*?status: )off"%re.escape(lid), r"\1on", s, flags=re.S)
open(p,"w").write(s)
print("enabled hillshade + contours in project.mml")
PY
carto project.mml > mapnik.xml
ABS="$(pwd)/data/world_land.shp"
sed -i "s|<!\[CDATA\[data/world_land.shp\]\]>|<![CDATA[$ABS]]>|g" mapnik.xml
echo "Recompiled mapnik.xml with Höhenlinien + Hillshade. Restart renderd + clear cache."
