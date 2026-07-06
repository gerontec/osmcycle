#!/usr/bin/env bash
# Point CyclOSM's two coastline layers at the local world_land shapefile
# (see make_land_shapefile.sh) and compile Mapnik XML.
#
# The hillshade + contour layers in project.mml already have `status: off`,
# so no DEM / contours database is required for a first working render.
set -euo pipefail
STYLE_DIR="${1:-style}"
cd "$STYLE_DIR"

sed -i \
  -e "s|file: http://osmdata.openstreetmap.de/download/simplified-land-polygons-complete-3857.zip|file: data/world_land.shp|" \
  -e "s|file: http://osmdata.openstreetmap.de/download/land-polygons-split-3857.zip|file: data/world_land.shp|" \
  project.mml

carto project.mml > mapnik.xml

# Make the shapefile path absolute so renderd finds it regardless of its cwd.
ABS="$(pwd)/data/world_land.shp"
sed -i "s|<!\[CDATA\[data/world_land.shp\]\]>|<![CDATA[$ABS]]>|g" mapnik.xml

echo "Compiled $(pwd)/mapnik.xml"
