#!/usr/bin/env python3
"""Punkte aus einer Locus-Map `waypoints.db` nach GPX exportieren.

Locus legt seine Punkte in **normalem SQLite** ab; OSMCycle (oder jedes Tool)
darf die DB **lesen** (reines SELECT, ungefährlich). Koordinaten stehen als
**Dezimalgrad** (REAL) in den `INTEGER`-deklarierten Spalten `longitude`/
`latitude`. **Schreiben** muss über Locus' API laufen — siehe
docs/locus_offline_points.md.

DB vorher ziehen:
  adb pull /sdcard/Android/media/menion.android.locus/data/database/waypoints.db

Aufruf:
  locus_wp_export.py waypoints.db [out.gpx]      # ohne out.gpx -> stdout
"""
import html
import sqlite3
import sys


def export(db_path, out=None):
    db = sqlite3.connect(db_path)
    rows = db.execute(
        "SELECT name, latitude, longitude, elevation FROM waypoints "
        "WHERE latitude IS NOT NULL AND longitude IS NOT NULL "
        "ORDER BY _id").fetchall()
    lines = ["<?xml version='1.0' encoding='UTF-8'?>",
             "<gpx version='1.1' creator='locus_wp_export' "
             "xmlns='http://www.topografix.com/GPX/1/1'>"]
    for name, lat, lon, ele in rows:
        ele_tag = "<ele>{:.1f}</ele>".format(ele) if ele is not None else ""
        lines.append(
            "  <wpt lat='{:.6f}' lon='{:.6f}'><name>{}</name>{}</wpt>".format(
                lat, lon, html.escape(name or ""), ele_tag))
    lines.append("</gpx>")
    data = "\n".join(lines) + "\n"
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(data)
        print("{} Punkte -> {}".format(len(rows), out))
    else:
        sys.stdout.write(data)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    export(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
