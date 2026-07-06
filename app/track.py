"""GPS track recording + GPX export + on-map track line for OSMCycle."""
import os
import time
from datetime import datetime, timezone

from kivy.graphics import Color, Line
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
        if not mapview or len(self.points) < 2:
            return
        coords = []
        for lat, lon in self.points:
            x, y = mapview.get_window_xy_from(lat, lon, mapview.zoom)
            coords += [x, y]
        with self.canvas:
            Color(0.85, 0.1, 0.1, 0.9)
            Line(points=coords, width=2.2)


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
