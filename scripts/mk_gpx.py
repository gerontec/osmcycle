import json, os, html

src = "/home/gh/python/osmcycle/app/wanderwege.json"
outdir = "/home/gh/python/osmcycle/gpx_wanderwege"
os.makedirs(outdir, exist_ok=True)
data = json.load(open(src))

# name + colour matching the app (track.py COLORS, main.py legend)
META = {
    "maximilian": ("Maximiliansweg", "#2b7ab5"),   # blue
    "karnisch":   ("Karnischer Höhenweg", "#d6191c"),  # red
    "tirol":      ("Tiroler Höhenweg", "#1a9640"),  # green
}

trails = {}
for seg in data:
    trails.setdefault(seg["trail"], []).append(seg["points"])

for trail, segs in trails.items():
    name, color = META.get(trail, (trail, "#ff0000"))
    fn = os.path.join(outdir, f"{trail}.gpx")
    with open(fn, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<gpx version="1.1" creator="osmcycle" '
                'xmlns="http://www.topografix.com/GPX/1/1" '
                'xmlns:osmand="https://osmand.net">\n')
        f.write(f'  <trk><name>{html.escape(name)}</name>\n')
        f.write(f'    <extensions><osmand:color>{color}</osmand:color>'
                f'<osmand:width>bold</osmand:width></extensions>\n')
        for pts in segs:
            f.write('    <trkseg>')
            for lon, lat in pts:
                f.write(f'<trkpt lat="{lat}" lon="{lon}"></trkpt>')
            f.write('</trkseg>\n')
        f.write('  </trk>\n</gpx>\n')
    npts = sum(len(p) for p in segs)
    print(f"{name} [{color}]: {len(segs)} segs, {npts} pts -> {fn} ({os.path.getsize(fn)} B)")
