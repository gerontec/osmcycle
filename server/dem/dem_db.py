#!/usr/bin/env python3
"""Hoehenabfrage gegen das Copernicus-Raster in wagodb (siehe dem_import.py).

    from dem_db import DemDB
    dem = DemDB()
    dem.elevation(47.6812, 11.5794)      # -> 763.4  (Meter, bilinear)

Ersetzt CopernicusDEM (rasterio auf lokalen GeoTIFFs) fuer alles, was nicht auf
heissa.de laeuft: die Kacheln liegen jetzt in der DB, nicht mehr nur im Dateisystem.

Bilinear statt nearest: bei 30 m Rasterweite liegt ein Trackpunkt fast nie auf
einem Rasterpunkt: nearest springt dann in 30-m-Stufen, was im Hoehenprofil als
Treppe sichtbar wird.
"""
import os
import zlib
from collections import OrderedDict

import numpy as np
import pymysql

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

NODATA = -32768
CACHE_BLOCKS = 32          # ~4 MB entpackt; ein Track bleibt in wenigen Bloecken


class DemDB:
    def __init__(self, **db):
        self._conn = pymysql.connect(**{**_db_config(), **db})
        self._heads = {}                      # (lat,lon) -> Rasterkopf
        self._blocks = OrderedDict()          # (lat,lon,brow,bcol) -> ndarray

    # -- Rasterkopf + Bloecke ------------------------------------------------
    def _head(self, lat_deg, lon_deg):
        key = (lat_deg, lon_deg)
        if key not in self._heads:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT width, height, origin_lat, origin_lon, px_lat, px_lon,"
                " blocksize FROM dem_tile WHERE lat_deg=%s AND lon_deg=%s", key)
            row = cur.fetchone()
            cur.close()
            self._heads[key] = row            # None = Kachel nicht importiert
        return self._heads[key]

    def _block(self, lat_deg, lon_deg, brow, bcol, blocksize):
        key = (lat_deg, lon_deg, brow, bcol)
        blk = self._blocks.get(key)
        if blk is None:
            cur = self._conn.cursor()
            cur.execute("SELECT data FROM dem_block WHERE lat_deg=%s AND lon_deg=%s"
                        " AND brow=%s AND bcol=%s", key)
            row = cur.fetchone()
            cur.close()
            if not row:
                return None
            blk = np.frombuffer(zlib.decompress(row[0]), dtype="<i2").reshape(
                blocksize, blocksize)
            self._blocks[key] = blk
            if len(self._blocks) > CACHE_BLOCKS:
                self._blocks.popitem(last=False)
        else:
            self._blocks.move_to_end(key)
        return blk

    def _sample(self, lat_deg, lon_deg, head, row, col):
        """Ein Rasterwert (Zeile/Spalte innerhalb der Kachel) oder None."""
        width, height, _, _, _, _, blocksize = head
        if not (0 <= row < height and 0 <= col < width):
            return None
        blk = self._block(lat_deg, lon_deg, row // blocksize, col // blocksize,
                          blocksize)
        if blk is None:
            return None
        val = int(blk[row % blocksize, col % blocksize])
        return None if val == NODATA else val

    # -- oeffentlich ---------------------------------------------------------
    def elevation(self, lat, lon):
        """Hoehe in Metern, bilinear interpoliert. None ausserhalb der Abdeckung."""
        lat_deg, lon_deg = int(np.floor(lat)), int(np.floor(lon))
        head = self._head(lat_deg, lon_deg)
        if head is None:
            return None
        _, _, origin_lat, origin_lon, px_lat, px_lon, _ = head

        # Bruchteilige Rasterposition (px_lat ist negativ: Zeile 0 liegt im Norden)
        y = (lat - origin_lat) / px_lat
        x = (lon - origin_lon) / px_lon
        r0, c0 = int(np.floor(y)), int(np.floor(x))
        fy, fx = y - r0, x - c0

        quad = [self._sample(lat_deg, lon_deg, head, r0 + dr, c0 + dc)
                for dr, dc in ((0, 0), (0, 1), (1, 0), (1, 1))]
        if any(v is None for v in quad):
            # Kachelrand oder Nodata: auf den naechsten gueltigen Wert zurueckfallen
            near = self._sample(lat_deg, lon_deg, head, int(round(y)), int(round(x)))
            return float(near) if near is not None else None

        v00, v01, v10, v11 = quad
        top = v00 * (1 - fx) + v01 * fx
        bot = v10 * (1 - fx) + v11 * fx
        return float(top * (1 - fy) + bot * fy)

    def close(self):
        self._conn.close()


if __name__ == "__main__":
    dem = DemDB()
    for name, lat, lon in [("Lenggries",   47.6812, 11.5794),
                           ("Brauneck",    47.6667, 11.5333),
                           ("Zugspitze",   47.4211, 10.9853),
                           ("Grossglockner", 47.0742, 12.6947),
                           ("Nuernberg",   49.4521, 11.0767)]:
        print(f"{name:15} {dem.elevation(lat, lon)}")
