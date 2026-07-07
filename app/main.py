"""OSMCycle - CyclOSM cycling app for Bayern + Tirol + Kärnten + Südtirol.

* Offline map (combined MBTiles) + Nachladen from the tile server.
* GPS track recording -> GPX (like OsmAnd).
* Current-position arrow (rotates to heading) + centre-on-me button.
* Layer menu to toggle the 3 long-distance hiking trails (Wanderwege).
"""
import json
import os

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.togglebutton import ToggleButton
from kivy_garden.mapview import MapView, MapSource

from hybridsource import HybridMapSource
from track import TrackLayer, TrackRecorder, PositionLayer, WanderwegeLayer

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


def load_wanderwege():
    try:
        with open(os.path.join(HERE, "wanderwege.json")) as f:
            return json.load(f)
    except Exception:
        return []


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
        self.ww_layer = WanderwegeLayer(load_wanderwege())
        self.mapview.add_layer(self.ww_layer)
        self.pos_layer = PositionLayer()
        self.mapview.add_layer(self.pos_layer)

        self.recorder = TrackRecorder()
        self.last_lat = self.last_lon = None

        self.status = Label(text="GPS: warte…", size_hint=(None, None),
                            size=(360, 44), pos_hint={"x": 0.01, "top": 0.99},
                            color=(0, 0, 0, 1), halign="left")
        root.add_widget(self.status)

        # REC (bottom-left)
        self.rec_btn = ToggleButton(text="● REC", size_hint=(None, None),
                                    size=(150, 60), pos_hint={"x": 0.02, "y": 0.03})
        self.rec_btn.bind(on_press=self.toggle_record)
        root.add_widget(self.rec_btn)

        # Layer menu (top-right)
        layer_btn = Button(text="≡ Layer", size_hint=(None, None), size=(150, 60),
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

    # --- layer menu ------------------------------------------------------
    def open_layers(self, *_):
        box = BoxLayout(orientation="vertical", spacing=8, padding=12)
        tb = ToggleButton(text="Wanderwege (Höhenwege)",
                          state="down" if self.ww_layer.visible else "normal",
                          size_hint_y=None, height=64)
        tb.bind(on_release=lambda b: self.ww_layer.set_visible(b.state == "down"))
        box.add_widget(tb)
        box.add_widget(Label(text="🔴 Karnischer  🔵 Maximilians  🟢 Tiroler",
                             size_hint_y=None, height=40))
        Popup(title="Layer", content=box, size_hint=(0.8, 0.4)).open()

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
        if self.recorder.recording:
            self.recorder.add(lat, lon, ele)
            self.track_layer.add_point(lat, lon)
            self.status.text = f"REC · {len(self.recorder.points)} Punkte"
        else:
            self.status.text = f"GPS: {lat:.5f}, {lon:.5f}"

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
        else:
            path = self.recorder.stop_and_save()
            self.rec_btn.text = "● REC"
            self.status.text = (f"GPX: {os.path.basename(path)}" if path
                                else "Kein Track")


if __name__ == "__main__":
    OSMCycleApp().run()
