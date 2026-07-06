#!/usr/bin/env bash
# CyclOSM's project.mml references two large coastline shapefiles downloaded
# from osmdata.openstreetmap.de (land-polygons-*). Bayern + Tirol is entirely
# landlocked, so those layers contribute nothing except a ~1 GB download.
#
# Instead we generate a single world-covering land polygon. With the Mapnik
# Map background set to the sea colour (#8ecbeb), this polygon paints the whole
# (inland) map area as land, which is exactly correct here.
set -euo pipefail
STYLE_DIR="${1:-style}"
OUT="$STYLE_DIR/data/world_land"
mkdir -p "$STYLE_DIR/data"

cat > "$STYLE_DIR/data/world_land.geojson" <<'GEOJSON'
{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},
"geometry":{"type":"Polygon","coordinates":[[[-180,-85.05],[180,-85.05],
[180,85.05],[-180,85.05],[-180,-85.05]]]}}]}
GEOJSON

ogr2ogr -f "ESRI Shapefile" -t_srs EPSG:3857 "$OUT.shp" "$STYLE_DIR/data/world_land.geojson"
shapeindex "$OUT.shp"
echo "Created $OUT.shp (+ .index)"
