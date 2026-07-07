"""OSMCycle - CyclOSM cycling app for Bayern + Tirol + Kärnten + Südtirol.

* Offline map (combined MBTiles) + Nachladen from the tile server.
* GPS track recording -> GPX (like OsmAnd).
* Current-position arrow (rotates to heading) + centre-on-me button.

Hiking trails and recorded tracks are shown as an efficient GPX overlay.
"""
import glob
import os
import shutil

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.togglebutton import ToggleButton
from kivy_garden.mapview import MapView, MapSource

from hybridsource import HybridMapSource
from track import (TrackLayer, TrackRecorder, PositionLayer, GpxLayer,
                   PeaksLayer, gpx_dir)

MBTILES_NAME = "alpen.mbtiles"
ONLINE_URL = "http://[2a02:810d:4117:7300:ce96:e5ff:fe01:e09c]:8280/tiles/cyclosm/{z}/{x}/{y}.png"
HERE = os.path.dirname(os.path.abspath(__file__))


def find_mbtiles():
    paths = []
    try:
        from android import mActivity  # type: ignore
        ext = mActivity.getExternalFilesDir(None)
        if ext:
            paths.append(os.path.join(ext.getAbsolutePath(), MBTILES_NAME))
    except Exception:
        pass
    paths += [os.path.join("/sdcard/osmcycle", MBTILES_NAME),
              os.path.join(HERE, MBTILES_NAME), MBTILES_NAME]
    return next((p for p in paths if p and os.path.exists(p)), None)


def request_all_files_access():
    """Ask for 'All files access' so the public gpx folder (Syncthing) is
    writable on Android 11+. No-op elsewhere / if already granted."""
    try:
        from jnius import autoclass
        Environment = autoclass("android.os.Environment")
        if Environment.isExternalStorageManager():
            return
        Intent = autoclass("android.content.Intent")
        Settings = autoclass("android.provider.Settings")
        Uri = autoclass("android.net.Uri")
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
        intent.setData(Uri.parse("package:" + act.getPackageName()))
        act.startActivity(intent)
    except Exception:
        pass


def seed_gpx():
    """Copy the bundled routes into the (public) gpx folder once, so bundled
    routes and own recordings live in the SAME folder that Syncthing sees."""
    dest = gpx_dir()
    for f in glob.glob(os.path.join(HERE, "gpx", "*.gpx")):
        t = os.path.join(dest, os.path.basename(f))
        if not os.path.exists(t):
            try:
                shutil.copy(f, t)
            except Exception:
                pass


class OSMCycleApp(App):
    def build(self):
        mbt = find_mbtiles()
        if mbt:
            source = HybridMapSource(mbtiles_path=mbt, url=ONLINE_URL,
                                     cache_key="cyclosm", min_zoom=2, max_zoom=18,
                                     tile_size=256, image_ext="png",
                                     attribution="© OpenStreetMap, CyclOSM")
        else:
            source = MapSource(url=ONLINE_URL, cache_key="cyclosm", min_zoom=2,
                               max_zoom=18, tile_size=256, image_ext="png",
                               attribution="© OpenStreetMap, CyclOSM")

        root = FloatLayout()
        self.mapview = MapView(zoom=13, lat=47.68, lon=11.57)
        self.mapview.map_source = source
        root.add_widget(self.mapview)

        self.track_layer = TrackLayer()
        self.mapview.add_layer(self.track_layer)
        # single (public) gpx folder: bundled routes + own recordings
        request_all_files_access()
        seed_gpx()
        self.gpx_layer = GpxLayer([gpx_dir()])
        self.mapview.add_layer(self.gpx_layer)
        self.peaks_layer = PeaksLayer([gpx_dir()])
        self.mapview.add_layer(self.peaks_layer)
        self.pos_layer = PositionLayer()
        self.mapview.add_layer(self.pos_layer)

        self.recorder = TrackRecorder()
        self.last_lat = self.last_lon = None
        self._centered = False

        self.status = Label(text="GPS: warte…", size_hint=(None, None),
                            size=(360, 44), pos_hint={"x": 0.01, "top": 0.99},
                            color=(0, 0, 0, 1), halign="left")
        root.add_widget(self.status)

        # REC (bottom-left)
        self.rec_btn = ToggleButton(text="● REC", size_hint=(None, None),
                                    size=(150, 60), pos_hint={"x": 0.02, "y": 0.03})
        self.rec_btn.bind(on_press=self.toggle_record)
        root.add_widget(self.rec_btn)

        # Layer menu (top-right) — multi-select overlay chooser
        layer_btn = Button(text="≡ Layer", size_hint=(None, None), size=(160, 60),
                           pos_hint={"right": 0.98, "top": 0.99})
        layer_btn.bind(on_release=self.open_layers)
        root.add_widget(layer_btn)

        # Centre-on-me (bottom-right, circle symbol)
        self.center_btn = Button(text="◎", font_size=42, size_hint=(None, None),
                                 size=(110, 110), pos_hint={"right": 0.98, "y": 0.03})
        self.center_btn.bind(on_release=self.center_on_me)
        root.add_widget(self.center_btn)

        Clock.schedule_once(lambda dt: self.start_gps(), 1)
        return root

    # --- layer menu (multi-select) ---------------------------------------
    def open_layers(self, *_):
        box = BoxLayout(orientation="vertical", spacing=6, padding=10,
                        size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        for src in self.gpx_layer.sources():
            tb = ToggleButton(text=src, size_hint_y=None, height=64,
                              state="down" if src in self.gpx_layer.enabled else "normal")
            tb.bind(on_release=lambda b, s=src:
                    self.gpx_layer.set_enabled(s, b.state == "down"))
            box.add_widget(tb)
        pk = ToggleButton(text="\U0001F53A Gipfelnamen", size_hint_y=None, height=64,
                          state="down" if self.peaks_layer.visible else "normal")
        pk.bind(on_release=lambda b: self.peaks_layer.set_visible(b.state == "down"))
        box.add_widget(pk)
        sv = ScrollView()
        sv.add_widget(box)
        Popup(title="Layer anzeigen", content=sv, size_hint=(0.85, 0.7)).open()

    # --- GPS -------------------------------------------------------------
    def start_gps(self):
        try:
            from android.permissions import request_permissions, Permission
            request_permissions([Permission.ACCESS_FINE_LOCATION,
                                 Permission.ACCESS_COARSE_LOCATION])
        except Exception:
            pass
        try:
            from plyer import gps
            gps.configure(on_location=self.on_location)
            gps.start(minTime=1000, minDistance=1)
            self.status.text = "GPS: aktiv"
        except Exception as e:
            self.status.text = f"GPS n/v ({e})"
        # show the arrow immediately from the last known fix (also works indoors)
        self._show_last_known()

    def _read_location(self):
        """Current fix straight from Android LocationManager. Works even when the
        plyer on_location callback never fires. Returns (lat, lon, ele, bearing)
        or None."""
        try:
            from jnius import autoclass
            Context = autoclass("android.content.Context")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            lm = PythonActivity.mActivity.getSystemService(Context.LOCATION_SERVICE)
            loc = (lm.getLastKnownLocation("gps")
                   or lm.getLastKnownLocation("fused")
                   or lm.getLastKnownLocation("network"))
            if loc:
                return (loc.getLatitude(), loc.getLongitude(),
                        loc.getAltitude() if loc.hasAltitude() else None,
                        loc.getBearing() if loc.hasBearing() else None)
        except Exception:
            pass
        return None

    def _show_last_known(self):
        fix = self._read_location()
        if fix:
            self._update(*fix)

    def on_location(self, **kwargs):
        lat, lon = kwargs.get("lat"), kwargs.get("lon")
        if lat is None or lon is None:
            return
        Clock.schedule_once(
            lambda dt: self._update(lat, lon, kwargs.get("altitude"),
                                    kwargs.get("bearing")), 0)

    def _update(self, lat, lon, ele, bearing):
        self.last_lat, self.last_lon = lat, lon
        self.pos_layer.set_position(lat, lon, bearing)
        if not self._centered:            # centre once so the arrow is on-screen
            self._centered = True
            self.mapview.center_on(lat, lon)
        if not self.recorder.recording:
            self.status.text = f"GPS: {lat:.5f}, {lon:.5f}"

    def _rec_tick(self, dt):
        """Every 10 s while recording: sample the position via LocationManager,
        log it and drop a dot on the map — visible proof recording works."""
        fix = self._read_location()
        if not fix:
            self.status.text = "REC · warte auf GPS…"
            return
        lat, lon, ele, bearing = fix
        self._update(lat, lon, ele, bearing)      # keep the arrow fresh
        self.recorder.add(lat, lon, ele)
        self.track_layer.add_point(lat, lon)      # draws the line + a dot
        self.status.text = f"REC · {len(self.recorder.points)} Punkte"

    def center_on_me(self, *_):
        if self.last_lat is not None:
            self.mapview.center_on(self.last_lat, self.last_lon)

    # --- recording -------------------------------------------------------
    def toggle_record(self, *_):
        if self.rec_btn.state == "down":
            self.recorder.start()
            self.track_layer.clear()
            self.rec_btn.text = "■ STOP"
            self.status.text = "REC gestartet"
            self._rec_ev = Clock.schedule_interval(self._rec_tick, 10)
            self._rec_tick(0)                     # drop the first dot immediately
        else:
            if getattr(self, "_rec_ev", None):
                self._rec_ev.cancel()
                self._rec_ev = None
            path = self.recorder.stop_and_save()
            self.rec_btn.text = "● REC"
            self.status.text = (f"GPX: {os.path.basename(path)}" if path
                                else "Kein Track")


if __name__ == "__main__":
    OSMCycleApp().run()
