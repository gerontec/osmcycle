"""OSMCycle - CyclOSM cycling app for Bayern + Tirol + Kärnten + Südtirol.

* Offline map: reads a combined MBTiles pack (all 4 regions), so it works with
  no network.
* Nachladen: tiles the pack lacks (higher zoom / neighbouring areas) are pulled
  from the tile server on demand and cached, like a normal slippy map.
* Track recording: records the GPS track and exports it as GPX (like OsmAnd).
"""
import os

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.togglebutton import ToggleButton
from kivy_garden.mapview import MapView, MapMarker, MapSource

from hybridsource import HybridMapSource
from track import TrackLayer, TrackRecorder

MBTILES_NAME = "alpen.mbtiles"              # combined 4-region offline pack
# Tile server for on-demand loading (set to a host the phone can reach).
ONLINE_URL = "http://192.168.5.23:8280/tiles/cyclosm/{z}/{x}/{y}.png"
BBOX = (9.9, 46.2, 15.1, 50.6)              # Bayern+Tirol+Südtirol+Kärnten


def find_mbtiles():
    paths = []
    try:
        from android import mActivity  # type: ignore
        ext = mActivity.getExternalFilesDir(None)
        if ext:
            paths.append(os.path.join(ext.getAbsolutePath(), MBTILES_NAME))
    except Exception:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    paths += [os.path.join("/sdcard/osmcycle", MBTILES_NAME),
              os.path.join(here, MBTILES_NAME), MBTILES_NAME]
    return next((p for p in paths if p and os.path.exists(p)), None)


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
        self.mapview = MapView(zoom=13, lat=47.68, lon=11.57)  # Lenggries
        self.mapview.map_source = source
        root.add_widget(self.mapview)

        self.track_layer = TrackLayer()
        self.mapview.add_layer(self.track_layer)
        self.marker = None
        self.recorder = TrackRecorder()

        self.status = Label(text="GPS: warte…", size_hint=(None, None),
                            size=(360, 44), pos_hint={"x": 0.01, "top": 0.99},
                            color=(0, 0, 0, 1), halign="left")
        root.add_widget(self.status)

        self.rec_btn = ToggleButton(text="● REC", size_hint=(None, None),
                                    size=(150, 60), pos_hint={"x": 0.02, "y": 0.03})
        self.rec_btn.bind(on_press=self.toggle_record)
        root.add_widget(self.rec_btn)

        Clock.schedule_once(lambda dt: self.start_gps(), 1)
        return root

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
            self.status.text = f"GPS nicht verfügbar ({e})"

    def on_location(self, **kwargs):
        lat = kwargs.get("lat")
        lon = kwargs.get("lon")
        ele = kwargs.get("altitude")
        if lat is None or lon is None:
            return
        Clock.schedule_once(lambda dt: self._update(lat, lon, ele), 0)

    def _update(self, lat, lon, ele):
        if self.marker is None:
            self.marker = MapMarker(lat=lat, lon=lon)
            self.mapview.add_marker(self.marker)
        else:
            self.marker.lat, self.marker.lon = lat, lon
            self.mapview.remove_marker(self.marker)
            self.mapview.add_marker(self.marker)
        if self.recorder.recording:
            self.recorder.add(lat, lon, ele)
            self.track_layer.add_point(lat, lon)
            self.status.text = f"REC · {len(self.recorder.points)} Punkte"
        else:
            self.status.text = f"GPS: {lat:.5f}, {lon:.5f}"

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
            self.status.text = f"GPX gespeichert: {os.path.basename(path)}" if path \
                else "Kein Track aufgezeichnet"


if __name__ == "__main__":
    OSMCycleApp().run()
