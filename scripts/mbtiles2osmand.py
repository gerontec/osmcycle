#!/usr/bin/env python3
"""Convert a standard (TMS) MBTiles file into an OsmAnd .sqlitedb raster map.

    python3 mbtiles2osmand.py IN.mbtiles OUT.sqlitedb [bigplanet|simple]

OsmAnd raster sqlitedb schema:
  tiles(x, y, z, s, image, PRIMARY KEY(x,y,z,s))
  info(...)                       # tile numbering + zoom metadata

Numbering (default 'bigplanet', OsmAnd's native/MOBAC format):
  * z is stored as 17 - zoom
  * x, y are Google/XYZ tile coordinates (y = 0 at the top)
MBTiles stores rows in TMS (y = 0 at the bottom), so we flip:
  y_xyz = (2**zoom - 1) - tile_row
Copy the resulting file to OsmAnd's tiles folder, then pick it under
Configure map -> Map source.
"""
import os
import sqlite3
import sys

SRC = sys.argv[1]
DST = sys.argv[2]
NUMBERING = (sys.argv[3] if len(sys.argv) > 3 else "bigplanet").lower()


def main():
    mb = sqlite3.connect(SRC)
    meta = dict(mb.execute("SELECT name, value FROM metadata"))
    minzoom = int(meta.get("minzoom", 1))
    maxzoom = int(meta.get("maxzoom", 17))

    if os.path.exists(DST):
        os.remove(DST)
    db = sqlite3.connect(DST)
    db.execute("CREATE TABLE tiles (x int, y int, z int, s int, image blob, "
               "PRIMARY KEY (x, y, z, s))")
    db.execute("CREATE INDEX IND on tiles (x, y, z, s)")
    db.execute("CREATE TABLE info (tilenumbering TEXT, minzoom INT, maxzoom INT, "
               "url TEXT, ellipsoid INT, inverted_y INT, timecolumn TEXT, "
               "expireminutes INT, tilesize INT)")
    db.execute(
        "INSERT INTO info (tilenumbering, minzoom, maxzoom, ellipsoid, "
        "inverted_y, timecolumn, expireminutes, tilesize) VALUES "
        "(?, ?, ?, 0, 0, 'no', 0, 256)",
        ("BigPlanet" if NUMBERING == "bigplanet" else "simple", minzoom, maxzoom),
    )

    n = 0
    for zoom, col, row, data in mb.execute(
        "SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles"
    ):
        y_xyz = (2 ** zoom - 1) - row            # TMS row -> XYZ y
        z_store = (17 - zoom) if NUMBERING == "bigplanet" else zoom
        db.execute("INSERT OR REPLACE INTO tiles (x, y, z, s, image) "
                   "VALUES (?, ?, ?, 0, ?)",
                   (col, y_xyz, z_store, sqlite3.Binary(data)))
        n += 1
        if n % 5000 == 0:
            db.commit()
    db.commit()
    db.close()
    print(f"{n} tiles -> {DST} ({os.path.getsize(DST) / 1e6:.1f} MB, "
          f"{NUMBERING}, z{minzoom}-{maxzoom})")


if __name__ == "__main__":
    main()
