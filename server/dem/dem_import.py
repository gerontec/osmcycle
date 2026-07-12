#!/usr/bin/env python3
"""Copernicus GLO-30 (30 m DEM) fuer Bayern + Tirol + Suedtirol + Kaernten
nach wagodb importieren.

Warum als Bloecke und nicht als Zeile pro Hoehenpunkt: die vier Regionen haben
bei 1 Bogensekunde rund 389 Mio. Rasterpunkte. Als Tabellenzeilen waeren das
zweistellige GB plus ein Index, der groesser waere als die Nutzdaten. Das Raster
liegt darum als 256x256-Kacheln aus int16 in einem komprimierten BLOB — eine
Punktabfrage laedt genau einen Block (128 kB roh, ~60 kB komprimiert).

Ausserdem: eine ganze 1-Grad-Kachel am Stueck waere 26 MB und wuerde an
max_allowed_packet (16 MB) scheitern. 256er-Bloecke passen immer.

  export WAGODB_PASSWORD=…
  ./dem_import.py            # fehlende Kacheln laden + importieren
  ./dem_check.py             # Import gegen die GeoTIFFs verifizieren
"""
import os
import zlib

import numpy as np
import pymysql
import rasterio
import requests

def _db_config():
    """Zugangsdaten aus der Umgebung — dieses Repo ist oeffentlich, hier steht
    kein Passwort im Klartext.

        export WAGODB_PASSWORD=…      (Rest hat brauchbare Defaults)
    """
    password = os.environ.get("WAGODB_PASSWORD")
    if not password:
        raise SystemExit("WAGODB_PASSWORD ist nicht gesetzt")
    return dict(host=os.environ.get("WAGODB_HOST", "10.8.0.1"),
                user=os.environ.get("WAGODB_USER", "gh"),
                password=password,
                database=os.environ.get("WAGODB_DATABASE", "wagodb"),
                charset="utf8mb4")

CACHE = "/home/gh/syncthing/copernicus_cache"
AWS = ("https://copernicus-dem-30m.s3.amazonaws.com/"
       "Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM/"
       "Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM.tif")

BLOCK = 256
NODATA = -32768           # int16-Untergrenze, kommt als Hoehe nicht vor

# Bounding-Boxen der vier Regionen (lon_min, lon_max, lat_min, lat_max).
# Die Kachelliste ist die Vereinigung der abgedeckten Ganzgrad-Zellen.
REGIONS = {
    "Bayern":    (8.9, 13.9, 47.2, 50.6),
    "Tirol":     (10.0, 13.0, 46.6, 47.8),
    "Suedtirol": (10.3, 12.5, 46.2, 47.1),
    "Kaernten":  (12.6, 15.1, 46.3, 47.2),
}


def needed_tiles():
    tiles = set()
    for lon0, lon1, lat0, lat1 in REGIONS.values():
        for lat in range(int(lat0), int(lat1) + 1):
            for lon in range(int(lon0), int(lon1) + 1):
                tiles.add((lat, lon))
    return sorted(tiles)


def tile_path(lat, lon):
    return os.path.join(CACHE, f"N{lat:02d}_E{lon:03d}.tif")


def fetch(lat, lon):
    """Kachel von AWS Open Data holen (kein Login noetig)."""
    path = tile_path(lat, lon)
    if os.path.exists(path):
        return path
    url = AWS.format(lat=lat, lon=lon)
    print(f"  lade N{lat:02d}_E{lon:03d} …", end="", flush=True)
    r = requests.get(url, stream=True, timeout=180)
    if r.status_code != 200:
        print(f" HTTP {r.status_code} — uebersprungen")
        return None
    tmp = path + ".part"
    size = 0
    with open(tmp, "wb") as fh:
        for chunk in r.iter_content(1 << 20):
            fh.write(chunk)
            size += len(chunk)
    os.replace(tmp, path)
    print(f" {size / 2**20:.0f} MB")
    return path


SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def split_statements(sql):
    """SQL an ';' zerlegen, aber nur ausserhalb von String-Literalen: die
    Spaltenkommentare enthalten selbst Semikolons, ein naives split() zerschneidet
    das Statement mitten im Text."""
    out, buf, in_str = [], [], False
    for ch in sql:
        if ch == "'":
            in_str = not in_str
        if ch == ";" and not in_str:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return [s.strip() for s in out if s.strip()]


def create_tables(cur):
    """Schema aus schema.sql anwenden — eine Quelle, keine zweite Abschrift der
    DDL hier im Code, die dann auseinanderlaeuft."""
    with open(SCHEMA, encoding="utf-8") as fh:
        sql = "\n".join(line for line in fh
                        if not line.lstrip().startswith("--"))
    for stmt in split_statements(sql):
        cur.execute(stmt)


def import_tile(cur, lat, lon, path):
    with rasterio.open(path) as ds:
        band = ds.read(1)
        tr = ds.transform
        nod = ds.nodata

    grid = np.where(np.isnan(band), NODATA, band)
    if nod is not None:
        grid = np.where(band == nod, NODATA, grid)
    grid = np.clip(np.rint(grid), NODATA, 32767).astype("<i2")

    h, w = grid.shape
    cur.execute(
        "REPLACE INTO dem_tile (lat_deg, lon_deg, width, height, origin_lat,"
        " origin_lon, px_lat, px_lon, blocksize) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (lat, lon, w, h, tr.f + tr.e / 2, tr.c + tr.a / 2, tr.e, tr.a, BLOCK))
    cur.execute("DELETE FROM dem_block WHERE lat_deg=%s AND lon_deg=%s", (lat, lon))

    rows, raw, comp = [], 0, 0
    for brow in range((h + BLOCK - 1) // BLOCK):
        for bcol in range((w + BLOCK - 1) // BLOCK):
            blk = grid[brow * BLOCK:(brow + 1) * BLOCK,
                       bcol * BLOCK:(bcol + 1) * BLOCK]
            # Randbloecke auffuellen, damit jeder Block dieselbe Geometrie hat
            if blk.shape != (BLOCK, BLOCK):
                pad = np.full((BLOCK, BLOCK), NODATA, dtype="<i2")
                pad[:blk.shape[0], :blk.shape[1]] = blk
                blk = pad
            buf = blk.tobytes()
            packed = zlib.compress(buf, 6)
            raw += len(buf)
            comp += len(packed)
            rows.append((lat, lon, brow, bcol, packed))
            if len(rows) >= 64:
                cur.executemany("INSERT INTO dem_block VALUES (%s,%s,%s,%s,%s)", rows)
                rows = []
    if rows:
        cur.executemany("INSERT INTO dem_block VALUES (%s,%s,%s,%s,%s)", rows)

    n = ((h + BLOCK - 1) // BLOCK) * ((w + BLOCK - 1) // BLOCK)
    print(f"  N{lat:02d}_E{lon:03d}: {w}x{h}, {n} Bloecke, "
          f"{raw / 2**20:.0f} MB roh -> {comp / 2**20:.0f} MB in der DB")


def main():
    tiles = needed_tiles()
    print(f"{len(tiles)} Kacheln fuer {', '.join(REGIONS)}")

    conn = pymysql.connect(**_db_config(), autocommit=False)
    cur = conn.cursor()
    create_tables(cur)
    conn.commit()

    cur.execute("SELECT lat_deg, lon_deg FROM dem_tile")
    done = {(r[0], r[1]) for r in cur.fetchall()}

    for lat, lon in tiles:
        if (lat, lon) in done:
            print(f"  N{lat:02d}_E{lon:03d}: schon drin")
            continue
        path = fetch(lat, lon)
        if not path:
            continue
        import_tile(cur, lat, lon, path)
        conn.commit()

    cur.execute("SELECT COUNT(*) FROM dem_tile")
    nt = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*), SUM(LENGTH(data)) FROM dem_block")
    nb, sz = cur.fetchone()
    print(f"\nFertig: {nt} Kacheln, {nb} Bloecke, "
          f"{(sz or 0) / 2**30:.2f} GB Blobdaten")
    conn.close()


if __name__ == "__main__":
    main()
