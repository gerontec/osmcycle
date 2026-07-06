#!/usr/bin/env bash
# Download Bayern + Tirol, merge, and import into a PostGIS database `osm`
# using the schema CyclOSM expects (pgsql backend, -G --hstore --slim).
set -euo pipefail
DATA_DIR="${1:-data}"
STYLE_DIR="${2:-style}"
mkdir -p "$DATA_DIR"
cd "$DATA_DIR"

# Geofabrik does NOT split Austria into states, so we grab all of Austria and
# clip the western part (Tirol/Vorarlberg) to the render bbox.
BBOX="9.9,46.6,13.9,50.6"   # lon_min,lat_min,lon_max,lat_max

[ -f bayern-latest.osm.pbf ]  || wget -q https://download.geofabrik.de/europe/germany/bayern-latest.osm.pbf
[ -f austria-latest.osm.pbf ] || wget -q https://download.geofabrik.de/europe/austria-latest.osm.pbf

osmium extract -b "$BBOX" austria-latest.osm.pbf -o austria-west.osm.pbf --overwrite
osmium merge bayern-latest.osm.pbf austria-west.osm.pbf -o bayern-tirol.osm.pbf --overwrite
osmium fileinfo -e bayern-tirol.osm.pbf | grep -iE "Number of|Bounding box"

# Database (run once): createdb osm; CREATE EXTENSION postgis, hstore;
osm2pgsql -c -G --hstore --slim -d osm -C 24000 --number-processes "$(nproc)" bayern-tirol.osm.pbf

# CyclOSM-specific SQL views
psql -d osm -f "../$STYLE_DIR/views.sql"

# Let the renderd service account read the data
psql -d osm -c 'GRANT SELECT ON ALL TABLES IN SCHEMA public TO "_renderd";
                GRANT USAGE ON SCHEMA public TO "_renderd";
                ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO "_renderd";'
echo "Import complete."
