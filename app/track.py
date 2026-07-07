"""GPS track recording + GPX export + on-map track/GPX layers for OSMCycle."""
import glob
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from kivy.graphics import Color, Line, Ellipse, Triangle, PushMatrix, PopMatrix, Rotate
from kivy_garden.mapview import MapLayer


def _writable(d):
    try:
        os.makedirs(d, exist_ok=True)
        t = os.path.join(d, ".w")
        open(t, "w").close()
        os.remove(t)
        return True
    except Exception:
        return False


def gpx_dir():
    """Single folder holding ALL .gpx (bundled routes seeded on first start +
    own recorded tracks), also what GpxLayer reads. Prefers a PUBLIC folder so
    Syncthing can sync it; falls back to the app-private dir if not writable
    (needs 'All files access' for the public path)."""
    candidates = ["/sdcard/osmcycle", "/storage/emulated/0/osmcycle"]
    try:
        from android import mActivity  # type: ignore
        ext = mActivity.getExternalFilesDir(None)
        if ext:                                   # app-private fallback
            candidates.append(os.path.join(ext.getAbsolutePath(), "gpx"))
    except Exception:
        pass
    candidates.append(os.path.join(os.path.expanduser("~"), "osmcycle_gpx"))
    for d in candidates:
        if _writable(d):
            return d
    return candidates[-1]


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


class GpxLayer(MapLayer):
    """Toggleable GPX overlay, rendered like OsmAnd: every .gpx in the given
    folder(s) becomes coloured track lines. Kept smooth by (1) a zoom floor,
    (2) per-segment viewport culling and (3) screen-space point decimation, so
    only geometry near the active window is projected/drawn."""
    MIN_ZOOM = 11        # below this a whole trail fills the screen -> skip (lag)
    DECIMATE_PX = 2.5    # drop points closer than this (in screen px) to the last
    DEFAULT_COLOR = (0.60, 0.10, 0.75, 0.9)

    def __init__(self, dirs, **kwargs):
        super().__init__(**kwargs)
        self.visible = False
        self.segments = []          # {"points":[(lat,lon)], "bb":(la0,lo0,la1,lo1), "color"}
        if isinstance(dirs, str):
            dirs = [dirs]
        for d in dirs:
            for path in sorted(glob.glob(os.path.join(d or "", "*.gpx"))):
                try:
                    self._load(path)
                except Exception:
                    pass

    @staticmethod
    def _hex_rgba(text):
        try:
            s = text.strip().lstrip("#")
            return (int(s[0:2], 16) / 255.0, int(s[2:4], 16) / 255.0,
                    int(s[4:6], 16) / 255.0, 0.9)
        except Exception:
            return GpxLayer.DEFAULT_COLOR

    def _load(self, path):
        root = ET.parse(path).getroot()
        for trk in root:
            if not trk.tag.endswith("trk"):
                continue
            color = self.DEFAULT_COLOR
            for child in trk:
                if child.tag.endswith("extensions"):
                    for c in child.iter():
                        if c.tag.endswith("color") and c.text:
                            color = self._hex_rgba(c.text)
            for seg in trk:
                if not seg.tag.endswith("trkseg"):
                    continue
                pts = []
                for pt in seg:
                    if pt.tag.endswith("trkpt"):
                        try:
                            pts.append((float(pt.get("lat")), float(pt.get("lon"))))
                        except (TypeError, ValueError):
                            pass
                if len(pts) >= 2:
                    lats = [p[0] for p in pts]
                    lons = [p[1] for p in pts]
                    self.segments.append({
                        "points": pts, "color": color,
                        "bb": (min(lats), min(lons), max(lats), max(lons))})

    def set_visible(self, on):
        self.visible = on
        self.reposition()

    def reposition(self, *args):
        mapview = self.parent
        self.canvas.clear()
        if not mapview or not self.visible:
            return
        if int(mapview.zoom) < self.MIN_ZOOM:
            return                       # zoomed out: overview adds nothing but lag
        try:                             # visible viewport (lat/lon) + margin
            bb = mapview.get_bbox()
            vlatmin, vlatmax = min(bb[0], bb[2]), max(bb[0], bb[2])
            vlonmin, vlonmax = min(bb[1], bb[3]), max(bb[1], bb[3])
        except Exception:
            return                       # unknown viewport -> draw nothing (fast)
        mlat = (vlatmax - vlatmin) * 0.2
        mlon = (vlonmax - vlonmin) * 0.2
        vlatmin -= mlat; vlatmax += mlat; vlonmin -= mlon; vlonmax += mlon
        zoom = mapview.zoom
        d = self.DECIMATE_PX
        with self.canvas:
            for seg in self.segments:
                la0, lo0, la1, lo1 = seg["bb"]
                if (la1 < vlatmin or la0 > vlatmax or
                        lo1 < vlonmin or lo0 > vlonmax):
                    continue             # segment off-screen -> skip
                coords = []
                lx = ly = None
                for lat, lon in seg["points"]:
                    x, y = mapview.get_window_xy_from(lat, lon, zoom)
                    if lx is None or abs(x - lx) + abs(y - ly) >= d:
                        coords += [x, y]
                        lx, ly = x, y
                if len(coords) >= 4:
                    Color(*seg["color"])
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
