"""Vergleicht die DB-Abfrage gegen die GeoTIFFs (die Quelle der Wahrheit)."""
import rasterio
import rasterio.sample

from dem_db import DemDB

PTS = [("Lenggries", 47.6812, 11.5794), ("Brauneck", 47.6667, 11.5333),
       ("Zugspitze", 47.4211, 10.9853), ("Tegernsee", 47.7100, 11.7580),
       ("Kufstein", 47.5833, 12.1667), ("Muenchen", 48.1372, 11.5755)]

dem = DemDB()
print(f"{'Ort':12} {'DB bilinear':>12} {'TIF nearest':>12}   Diff")
for name, lat, lon in PTS:
    db_v = dem.elevation(lat, lon)
    path = f"/home/gh/syncthing/copernicus_cache/N{int(lat):02d}_E{int(lon):03d}.tif"
    with rasterio.open(path) as ds:
        tif = float(list(rasterio.sample.sample_gen(ds, [(lon, lat)]))[0][0])
    if db_v is None:
        print(f"{name:12} {'—':>12} {tif:12.1f}   Kachel fehlt noch")
    else:
        print(f"{name:12} {db_v:12.1f} {tif:12.1f}   {db_v - tif:+.1f} m")
