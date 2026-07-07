"""GPS track recording + GPX export + on-map track line for OSMCycle."""
import os
import time
from datetime import datetime, timezone

from kivy.graphics import Color, Line, Ellipse, Triangle, PushMatrix, PopMatrix, Rotate
from kivy_garden.mapview import MapLayer


def gpx_dir():
    """Writable folder for .gpx files (app external dir on Android)."""
    try:
        from android import mActivity  # type: ignore
        ext = mActivity.getExternalFilesDir(None)
        if ext:
            d = os.path.join(ext.getAbsolutePath(), "tracks")
            os.makedirs(d, exist_ok=True)
            return d
    except Exception:
        pass
    d = os.path.join(os.path.expanduser("~"), "osmcycle_tracks")
    os.makedirs(d, exist_ok=True)
    return d


class TrackLayer(MapLayer):
    """Draws the currently recorded track as a red line on the map."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.points = []  # list of (lat, lon)

    def add_point(self, lat, lon):
        self.points.append((lat, lon))
        self.reposition()

    def clear(self):
        self.points = []
        self.canvas.clear()

    def reposition(self, *args):
        mapview = self.parent
        self.canvas.clear()
        if not mapview or not self.points:
            return
        coords = []
        for lat, lon in self.points:
            x, y = mapview.get_window_xy_from(lat, lon, mapview.zoom)
            coords += [x, y]
        with self.canvas:
            Color(0.85, 0.1, 0.1, 0.9)
            if len(coords) >= 4:
                Line(points=coords, width=2.2)
            # one dot per recorded fix (10 s sample) as a live success-check
            r = 6
            for i in range(0, len(coords), 2):
                Ellipse(pos=(coords[i] - r, coords[i + 1] - r), size=(2 * r, 2 * r))


class PositionLayer(MapLayer):
    """Current GPS position: accuracy circle + arrow rotated to the heading."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.lat = self.lon = None
        self.heading = 0.0

    def set_position(self, lat, lon, heading=None):
        self.lat, self.lon = lat, lon
        if heading is not None:
            self.heading = heading
        self.reposition()

    def reposition(self, *args):
        mapview = self.parent
        self.canvas.clear()
        if not mapview or self.lat is None:
            return
        x, y = mapview.get_window_xy_from(self.lat, self.lon, mapview.zoom)
        with self.canvas:
            Color(0.13, 0.59, 0.95, 0.25)
            Ellipse(pos=(x - 26, y - 26), size=(52, 52))
            Color(0.13, 0.59, 0.95, 1)
            PushMatrix()
            Rotate(angle=-self.heading, origin=(x, y))   # 0 = north = up
            Triangle(points=[x, y + 18, x - 11, y - 12, x + 11, y - 12])
            PopMatrix()


class WanderwegeLayer(MapLayer):
    """Toggleable overlay: the 3 long-distance hiking trails as coloured lines,
    read from a bundled JSON (list of {color, points:[[lon,lat],...]})."""
    COLORS = {"karnisch": (0.84, 0.10, 0.11),
              "maximilian": (0.17, 0.48, 0.71),
              "tirol": (0.10, 0.59, 0.25)}

    def __init__(self, features, **kwargs):
        super().__init__(**kwargs)
        self.visible = False
        self.features = []          # precompute each feature's lon/lat bbox
        for f in features:
            pts = f.get("points") or []
            if len(pts) < 2:
                continue
            lons = [p[0] for p in pts]
            lats = [p[1] for p in pts]
            self.features.append({
                "trail": f["trail"], "points": pts,
                "bb": (min(lons), min(lats), max(lons), max(lats))})

    def set_visible(self, on):
        self.visible = on
        self.reposition()

    def reposition(self, *args):
        mapview = self.parent
        self.canvas.clear()
        if not mapview or not self.visible:
            return
        try:                        # visible viewport in lon/lat (+ margin)
            bb = mapview.get_bbox()
            vlatmin, vlatmax = min(bb[0], bb[2]), max(bb[0], bb[2])
            vlonmin, vlonmax = min(bb[1], bb[3]), max(bb[1], bb[3])
        except Exception:
            vlatmin = vlonmin = -1e9
            vlatmax = vlonmax = 1e9
        with self.canvas:
            for feat in self.features:
                blon0, blat0, blon1, blat1 = feat["bb"]
                if (blon1 < vlonmin or blon0 > vlonmax or
                        blat1 < vlatmin or blat0 > vlatmax):
                    continue        # feature fully off-screen -> skip
                r, g, b = self.COLORS.get(feat["trail"], (0.5, 0.5, 0.5))
                Color(r, g, b, 0.9)
                coords = []
                for lon, lat in feat["points"]:
                    px, py = mapview.get_window_xy_from(lat, lon, mapview.zoom)
                    coords += [px, py]
                if len(coords) >= 4:
                    Line(points=coords, width=2.2, joint="round", cap="round")


class TrackRecorder:
    """Collects GPS fixes and writes a GPX 1.1 file."""
    def __init__(self):
        self.recording = False
        self.points = []       # (lat, lon, ele, iso_time)
        self.start_ts = None

    def start(self):
        self.recording = True
        self.points = []
        self.start_ts = time.strftime("%Y-%m-%d_%H-%M-%S")

    def add(self, lat, lon, ele=None):
        if not self.recording:
            return
        t = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.points.append((lat, lon, ele, t))

    def stop_and_save(self):
        self.recording = False
        if not self.points:
            return None
        path = os.path.join(gpx_dir(), f"track_{self.start_ts}.gpx")
        with open(path, "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<gpx version="1.1" creator="OSMCycle" '
                    'xmlns="http://www.topografix.com/GPX/1/1">\n')
            f.write(f'  <trk><name>OSMCycle {self.start_ts}</name><trkseg>\n')
            for lat, lon, ele, t in self.points:
                f.write(f'    <trkpt lat="{lat:.6f}" lon="{lon:.6f}">')
                if ele is not None:
                    f.write(f'<ele>{ele:.1f}</ele>')
                f.write(f'<time>{t}</time></trkpt>\n')
            f.write('  </trkseg></trk>\n</gpx>\n')
        return path
