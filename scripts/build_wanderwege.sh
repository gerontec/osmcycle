#!/usr/bin/env bash
# Build the `wanderwege` overlay table (3 long-distance hiking trails) and wire
# it up as a separate transparent renderd map at /tiles/wanderwege/.
#
#   Karnischer Höhenweg + Maximiliansweg : taken directly from their OSM route
#                                          relations (member ways).
#   Tiroler Höhenweg                     : NOT a named OSM route -> routed along
#                                          OSM trails through its huts with
#                                          pgRouting (see tirol_route.sql).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

# --- Karnischer Höhenweg (+variants) and Maximiliansweg from OSM relations ---
psql -d osm <<'SQL'
DROP TABLE IF EXISTS wanderwege;
CREATE TABLE wanderwege AS
SELECT CASE WHEN r.id IN (1163255,1163590,3107762) THEN 'karnisch'
            WHEN r.id = 387633 THEN 'maximilian' END AS trail,
       r.tags->>'name' AS name, l.way AS way
FROM planet_osm_rels r
JOIN planet_osm_line l ON l.osm_id IN (
  SELECT (m->>'ref')::bigint FROM jsonb_array_elements(r.members) m WHERE m->>'type'='W')
WHERE r.id IN (1163255,1163590,3107762,387633);
CREATE INDEX wanderwege_geom ON wanderwege USING gist(way);
GRANT SELECT ON wanderwege TO "_renderd";
SQL

# --- Tiroler Höhenweg via pgRouting through the huts --------------------------
psql -d osm -c "CREATE EXTENSION IF NOT EXISTS pgrouting;"
psql -d osm -f "$HERE/tirol_route.sql"

# --- serve as a separate transparent renderd map -----------------------------
sudo cp "$ROOT/server/wanderwege.xml" /home/"$USER"/python/osmcycle/style/wanderwege.xml
if ! grep -q '\[wanderwege\]' /etc/renderd.conf; then
  sudo tee -a /etc/renderd.conf >/dev/null <<CONF

[wanderwege]
URI=/tiles/wanderwege/
TILEDIR=/var/cache/renderd/tiles
XML=/home/$USER/python/osmcycle/style/wanderwege.xml
HOST=localhost
TILESIZE=256
MAXZOOM=20
CONF
fi
sudo systemctl restart renderd && sudo systemctl reload apache2
echo "Overlay: http://<host>:8280/tiles/wanderwege/{z}/{x}/{y}.png (transparent)"
