#!/usr/bin/env python3
"""Export the app's overlay layers as plain GPX, so they work in map apps that
are not ours — Guru Maps and Cartograph on iOS, Locus and OsmAnd on Android.

The offline map (alpen_z15.mbtiles) is a raster pack: it carries the base map and
nothing else. Every overlay in OSMCycle — trails, summits, masts, bathing waters,
groundwater wells — is drawn by the app from its own data. Import the map into a
foreign app and you get a map with no layers on it.

GPX is the one format all of them read, and each imported file shows up as its own
collection that can be switched on and off — which is exactly what our layer menu
does. So the layers survive the trip.

Trails and summits are already GPX in the app (they are what the app itself reads),
so they are only copied. The three point layers are bare [lat, lon] lists and get
turned into waypoints here.

    ./export_layers.py [outdir]        # default: ./layers_export
"""
import json
import os
import shutil
import sys
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "..", "app")

# (source, output name, waypoint prefix, GPX symbol)
POINT_LAYERS = [
    ("sendemasten.json", "sendemasten.gpx", "Mast", "Radio Tower"),
    ("badestellen.json", "badestellen.gpx", "Badestelle", "Swimming Area"),
    ("grundwasser.json", "grundwasser.gpx", "Grundwasser", "Drinking Water"),
    ("wasserfaelle.json", "wasserfaelle.gpx", "Wasserfall", "Waterfall"),
]

# already GPX in the app — the app reads these very files
COPY_LAYERS = [
    ("gpx/karnisch.gpx", "wanderweg_karnischer.gpx"),
    ("gpx/maximilian.gpx", "wanderweg_maximiliansweg.gpx"),
    ("gpx/tirol.gpx", "wanderweg_tiroler_hoehenweg.gpx"),
    ("gpx/gipfel.gpx", "gipfel.gpx"),
]

HEAD = ("<?xml version='1.0' encoding='UTF-8'?>\n"
        "<gpx version='1.1' creator='osmcycle' "
        "xmlns='http://www.topografix.com/GPX/1/1'>\n")


def write_points(src, dest, prefix, sym):
    with open(src, encoding="utf-8") as fh:
        pts = json.load(fh)
    with open(dest, "w", encoding="utf-8") as out:
        out.write(HEAD)
        for i, (lat, lon) in enumerate(pts, 1):
            # The source data carries coordinates only, no names — number them, so
            # every waypoint is still individually addressable in the target app.
            out.write(f"  <wpt lat='{lat}' lon='{lon}'>"
                      f"<name>{escape(prefix)} {i}</name>"
                      f"<sym>{escape(sym)}</sym></wpt>\n")
        out.write("</gpx>\n")
    return len(pts)


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "layers_export")
    os.makedirs(outdir, exist_ok=True)

    for src, name, prefix, sym in POINT_LAYERS:
        n = write_points(os.path.join(APP, src), os.path.join(outdir, name),
                         prefix, sym)
        size = os.path.getsize(os.path.join(outdir, name)) / 1024
        print(f"  {name:34} {n:6d} waypoints  {size:7.0f} kB")

    for src, name in COPY_LAYERS:
        shutil.copy(os.path.join(APP, src), os.path.join(outdir, name))
        size = os.path.getsize(os.path.join(outdir, name)) / 1024
        print(f"  {name:34} {'(copied)':>16}  {size:7.0f} kB")

    print(f"\n-> {outdir}")


if __name__ == "__main__":
    main()
