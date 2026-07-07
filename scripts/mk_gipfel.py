#!/usr/bin/env python3
"""Fetch all named peaks (natural=peak + name) in the map's bbox from Overpass
and write them as GPX waypoints (name + elevation)."""
import html
import json
import urllib.parse
import urllib.request

BBOX = (46.2, 9.9, 50.6, 15.1)          # S, W, N, E  (Bayern+Tirol+Südtirol+Kärnten)
OUT = "/home/gh/python/osmcycle/gpx_wanderwege/gipfel.gpx"

query = (
    "[out:json][timeout:300];"
    f'node["natural"="peak"]["name"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});'
    "out body;"
)
req = urllib.request.Request(
    "https://overpass-api.de/api/interpreter",
    data=urllib.parse.urlencode({"data": query}).encode(),
    headers={"User-Agent": "osmcycle-gipfel/1.0"},
)
elements = json.load(urllib.request.urlopen(req, timeout=310))["elements"]

lines = ["<?xml version='1.0' encoding='UTF-8'?>",
         "<gpx version='1.1' creator='osmcycle' "
         "xmlns='http://www.topografix.com/GPX/1/1'>"]
n = 0
for e in elements:
    if e.get("type") != "node":
        continue
    tags = e.get("tags", {})
    name = tags.get("name")
    if not name:
        continue
    label = name
    ele = tags.get("ele")
    if ele:
        try:
            label = f"{name} ({int(round(float(str(ele).replace(',', '.').split()[0])))} m)"
        except (ValueError, IndexError):
            pass
    lines.append(
        f"  <wpt lat='{e['lat']:.6f}' lon='{e['lon']:.6f}'>"
        f"<name>{html.escape(label)}</name><sym>Summit</sym></wpt>")
    n += 1
lines.append("</gpx>")
with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print(f"{n} Gipfel -> {OUT}")
