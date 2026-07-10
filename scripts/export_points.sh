#!/bin/bash
# Exportiert die Punkt-Layer der App aus der wagodb (MariaDB) nach app/*.json.
#
#   sendemasten.json   emf_standorte          (BNetzA EMF-Standorte)
#   badestellen.json   badegewaesser          (LGL-Badegewaesser)
#   grundwasser.json   grundwasser_messstelle (GKD-Grundwassermessstellen)
#
# Format: [[lat,lon],...], nach lat sortiert — PointsLayer bisectiert darauf.
# Aufruf auf heissa.de (dort liegt die wagodb lokal):  sudo bash scripts/export_points.sh
set -e

APP_DIR="$(cd "$(dirname "$0")/../app" && pwd)"

export_one() {
    local tbl="$1" out="$2"
    mysql -N -B wagodb -e \
      "SELECT ROUND(lat,5), ROUND(lon,5) FROM $tbl
        WHERE lat IS NOT NULL AND lon IS NOT NULL
          AND lat BETWEEN 46 AND 51.5 AND lon BETWEEN 8 AND 15
        ORDER BY lat, lon;" > "/tmp/${out}.tsv"

    python3 - "$out" "$APP_DIR" <<'PY'
import json, os, sys
out, app_dir = sys.argv[1], sys.argv[2]
pts = []
with open(f"/tmp/{out}.tsv") as f:
    for line in f:
        a, b = line.split()
        pts.append([float(a), float(b)])
path = os.path.join(app_dir, f"{out}.json")
with open(path, "w") as f:
    json.dump(pts, f, separators=(",", ":"))
print(f"{out:14} {len(pts):6} Punkte -> {path} ({os.path.getsize(path)/1024:.0f} KiB)")
PY
    rm -f "/tmp/${out}.tsv"
}

export_one emf_standorte          sendemasten
export_one badegewaesser          badestellen
export_one grundwasser_messstelle grundwasser

chmod 644 "$APP_DIR"/sendemasten.json "$APP_DIR"/badestellen.json "$APP_DIR"/grundwasser.json
echo "fertig."
