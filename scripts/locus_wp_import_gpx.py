#!/usr/bin/env python3
"""Aus einem OSMCycle-Punkt-Layer eine **Locus-import-taugliche GPX** bauen.

Spiegelt `app/locusbridge.import_layer`:
 * namelose Punkte (reine Koordinatenlisten wie `wasserfaelle.json` /
   `badestellen.json`) bekommen eine laufende Nummer im Namen — sonst **merged
   Locus gleichnamige Punkte beim Import** (1711 rein -> 1 übrig, verifiziert).
 * `<metadata><name>` schlägt den Zielordner vor (Locus ignoriert ihn i. d. R.
   und importiert ins Stammverzeichnis — siehe docs/locus_offline_points.md).

Der eigentliche Import in Locus' DB passiert auf dem Gerät über
`ActionFiles.importFileLocus` (Locus schreibt die DB selbst; nie direkt
schreiben). Dieses Skript erzeugt nur die Datei.

Eingabe = JSON-Liste aus `[lat, lon]` oder `[lat, lon, name]`.

Aufruf:
  locus_wp_import_gpx.py wasserfaelle.json Wasserfälle [out.gpx]
"""
import html
import json
import sys


def build(src, name, out=None):
    with open(src, encoding="utf-8") as f:
        pts = json.load(f)
    out = out or "{}_import.gpx".format(name)
    lines = ["<?xml version='1.0' encoding='UTF-8'?>",
             "<gpx version='1.1' creator='osmcycle' "
             "xmlns='http://www.topografix.com/GPX/1/1'>",
             "  <metadata><name>{}</name></metadata>".format(html.escape(name))]
    for i, p in enumerate(pts, 1):
        label = str(p[2]) if len(p) > 2 else "{} {}".format(name, i)
        lines.append(
            "  <wpt lat='{:.6f}' lon='{:.6f}'><name>{}</name></wpt>".format(
                float(p[0]), float(p[1]), html.escape(label)))
    lines.append("</gpx>")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("{} Punkte -> {}".format(len(pts), out))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    build(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
