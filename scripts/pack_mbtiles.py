#!/usr/bin/env python3
"""Pack the Bayern+Tirol bbox into a standard (TMS) MBTiles file by pulling
tiles from the running mod_tile server (which renders + caches on demand).

    python3 pack_mbtiles.py [MINZOOM] [MAXZOOM] [OUTPUT.mbtiles]

Defaults: z6..z13 -> bayern-tirol.mbtiles.  Requires: requests.
The result is consumed offline by app/hybridsource.py on the device.
"""
import math
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

BBOX = (9.9, 46.6, 13.9, 50.6)  # lon_min, lat_min, lon_max, lat_max
BASE = os.environ.get("TILE_BASE", "http://localhost:8280/tiles/cyclosm")
MINZ = int(sys.argv[1]) if len(sys.argv) > 1 else 6
MAXZ = int(sys.argv[2]) if len(sys.argv) > 2 else 13
OUT = sys.argv[3] if len(sys.argv) > 3 else "bayern-tirol.mbtiles"


def deg2num(lat, lon, z):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def all_tiles():
    for z in range(MINZ, MAXZ + 1):
        x0, y0 = deg2num(BBOX[3], BBOX[0], z)  # top-left  (lat_max, lon_min)
        x1, y1 = deg2num(BBOX[1], BBOX[2], z)  # bot-right (lat_min, lon_max)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                yield z, x, y


def fetch(t):
    z, x, y = t
    try:
        r = requests.get(f"{BASE}/{z}/{x}/{y}.png", timeout=60)
        if r.status_code == 200 and r.content:
            return z, x, y, r.content
    except Exception as e:
        print(f"warn {z}/{x}/{y}: {e!r}")
    return None


def main():
    if os.path.exists(OUT):
        os.remove(OUT)
    db = sqlite3.connect(OUT)
    db.execute("CREATE TABLE metadata (name text, value text)")
    db.execute("CREATE TABLE tiles (zoom_level int, tile_column int, "
               "tile_row int, tile_data blob)")
    db.execute("CREATE UNIQUE INDEX tile_index ON tiles"
               "(zoom_level, tile_column, tile_row)")
    meta = {
        "name": "CyclOSM Bayern+Tirol", "type": "baselayer", "version": "1.0",
        "description": "CyclOSM raster tiles, Bayern + Tirol", "format": "png",
        "minzoom": str(MINZ), "maxzoom": str(MAXZ),
        "bounds": f"{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}",
        "center": "11.5,47.5,8",
        "attribution": "(c) OpenStreetMap contributors, CyclOSM",
    }
    db.executemany("INSERT INTO metadata VALUES (?,?)", list(meta.items()))
    db.commit()

    tl = list(all_tiles())
    print(f"{len(tl)} tiles to pack ({MINZ}..{MAXZ})")
    cnt = 0
    with ThreadPoolExecutor(max_workers=16) as ex:
        for res in ex.map(fetch, tl):
            if not res:
                continue
            z, x, y, data = res
            tms_row = (2 ** z - 1) - y  # XYZ y -> TMS tile_row
            db.execute("INSERT OR REPLACE INTO tiles VALUES (?,?,?,?)",
                       (z, x, tms_row, sqlite3.Binary(data)))
            cnt += 1
            if cnt % 2000 == 0:
                db.commit()
                print(f"  {cnt}/{len(tl)} packed")
    db.commit()
    db.close()
    print(f"DONE {cnt} tiles -> {OUT} "
          f"({os.path.getsize(OUT) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
