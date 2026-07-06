#!/usr/bin/env bash
# One-shot setup of the CyclOSM tile server on Ubuntu 26.04 (Mapnik 4.2).
# Assumes this repo is checked out at ~/python/osmcycle with the `style`
# submodule initialised (git submodule update --init).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# --- 1. packages -----------------------------------------------------------
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  postgresql postgis osm2pgsql osmium-tool mapnik-utils libmapnik-dev gdal-bin \
  renderd libapache2-mod-tile \
  fonts-dejavu fonts-hanazono fonts-unifont fonts-noto-cjk fonts-noto-core fonts-noto-unhinted
sudo npm install -g carto

# --- 2. database + roles ---------------------------------------------------
sudo -u postgres psql -c "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='$USER') THEN CREATE ROLE \"$USER\" LOGIN SUPERUSER; END IF; END \$\$;"
sudo -u postgres psql -c "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='_renderd') THEN CREATE ROLE \"_renderd\" LOGIN; END IF; END \$\$;"
sudo -u postgres createdb -O "$USER" osm 2>/dev/null || true
sudo -u postgres psql -d osm -c "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS hstore;"

# --- 3. style: land polygon + compile mapnik.xml ---------------------------
bash "$ROOT/scripts/make_land_shapefile.sh" "$ROOT/style"
bash "$ROOT/scripts/patch_project_mml.sh"   "$ROOT/style"

# --- 4. import OSM data ----------------------------------------------------
bash "$ROOT/scripts/import_osm.sh" "$ROOT/data" "style"

# --- 5. renderd + apache mod_tile -----------------------------------------
sudo cp "$ROOT/server/renderd.conf.example" /etc/renderd.conf
sudo sed -i "s|XML=.*|XML=$ROOT/style/mapnik.xml|" /etc/renderd.conf
sudo mkdir -p /var/cache/renderd/tiles && sudo chown -R _renderd:_renderd /var/cache/renderd
sudo cp "$ROOT/server/tileserver-vhost.conf.example" /etc/apache2/sites-available/tileserver.conf
sudo a2enmod tile
sudo a2ensite tileserver
sudo systemctl restart renderd
sudo apache2ctl configtest && sudo systemctl restart apache2

echo "Done. Test:  curl -o /tmp/t.png http://localhost:8280/tiles/cyclosm/12/2179/1418.png"
