"""OSMCycle - CyclOSM cycling app for Bayern + Tirol + Kärnten + Südtirol.

* Offline map (combined MBTiles) + Nachladen from the tile server.
* GPS track recording -> GPX (like OsmAnd).
* Current-position arrow (rotates to heading) + centre-on-me button.

Hiking trails and recorded tracks are shown as an efficient GPX overlay.
"""
import glob
import os
import shutil
import threading

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
# Public tile server (netcup) — works out of the box for new users, no home
# server / IPv6 needed. Serves z6-14 from CyclOSM_Alpen.sqlitedb via tile.php.
ONLINE_URL = "https://tmind.de/maps/tile.php?z={z}&x={x}&y={y}"
# Offline map for first-run download (new users, no map yet)
MBTILES_URL = "https://tmind.de/maps/alpen.mbtiles"
HERE = os.path.dirname(os.path.abspath(__file__))


def mbtiles_target():
    """Writable destination for the downloaded offline map (app-private dir is
    always writable; find_mbtiles() checks it too)."""
    try:
        from android import mActivity  # type: ignore
        ext = mActivity.getExternalFilesDir(None)
        if ext:
            return os.path.join(ext.getAbsolutePath(), MBTILES_NAME)
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), MBTILES_NAME)


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
                                     cache_key="cyclosm", min_zoom=2, max_zoom=14,
                                     tile_size=256, image_ext="png",
                                     attribution="© OpenStreetMap, CyclOSM")
        else:
            source = MapSource(url=ONLINE_URL, cache_key="cyclosm", min_zoom=2,
                               max_zoom=14, tile_size=256, image_ext="png",
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
        self.last_lat = self.last_lon = self.last_ele = None
        self._centered = False

        self.status = Label(text="GPS: warte…", size_hint=(None, None),
                            size=(560, 34), pos_hint={"x": 0.01, "top": 0.99},
                            color=(0, 0, 0, 1), halign="left", valign="middle",
                            font_size="15sp", text_size=(560, 34))
        root.add_widget(self.status)
        self.ele_lbl = Label(text="", size_hint=(None, None),
                             size=(560, 34), pos_hint={"x": 0.01, "top": 0.955},
                             color=(0, 0, 0, 1), halign="left", valign="middle",
                             font_size="15sp", text_size=(560, 34))
        root.add_widget(self.ele_lbl)

        # REC (bottom-left)
        self.rec_btn = ToggleButton(text="● REC", size_hint=(None, None),
                                    size=(210, 90), pos_hint={"x": 0.02, "y": 0.03},
                                    font_size="30sp")
        self.rec_btn.bind(on_press=self.toggle_record)
        root.add_widget(self.rec_btn)

        # Layer menu (top-right) — multi-select overlay chooser
        layer_btn = Button(text="≡ Layer", size_hint=(None, None), size=(220, 90),
                           pos_hint={"right": 0.98, "top": 0.99}, font_size="30sp")
        layer_btn.bind(on_release=self.open_layers)
        root.add_widget(layer_btn)

        # Centre-on-me (bottom-right, circle symbol)
        self.center_btn = Button(text="◎", font_size=42, size_hint=(None, None),
                                 size=(110, 110), pos_hint={"right": 0.98, "y": 0.03})
        self.center_btn.bind(on_release=self.center_on_me)
        root.add_widget(self.center_btn)

        Clock.schedule_once(lambda dt: self.start_gps(), 1)
        if not mbt:                       # new user: offer the offline map download
            Clock.schedule_once(lambda dt: self._offer_download(), 1.5)
        return root

    # --- first-run offline-map download ----------------------------------
    def _offer_download(self):
        box = BoxLayout(orientation="vertical", spacing=12, padding=16)
        box.add_widget(Label(
            text="Offline-Karte (~2,4 GB) jetzt herunterladen?\n"
                 "Empfohlen im WLAN. Danach voll offline nutzbar.",
            font_size="26sp", halign="center"))
        row = BoxLayout(size_hint_y=None, height=110, spacing=12)
        yes = Button(text="Laden", font_size="30sp")
        no = Button(text="Später", font_size="30sp")
        row.add_widget(yes)
        row.add_widget(no)
        box.add_widget(row)
        self._dlg = Popup(title="Karte laden", content=box, size_hint=(0.9, 0.5))
        yes.bind(on_release=lambda b: (self._dlg.dismiss(), self._start_download()))
        no.bind(on_release=lambda b: self._dlg.dismiss())
        self._dlg.open()

    def _start_download(self):
        self._prog_lbl = Label(text="0 %", font_size="30sp")
        self._prog = Popup(title="Karte wird geladen…", content=self._prog_lbl,
                           size_hint=(0.9, 0.3), auto_dismiss=False)
        self._prog.open()
        threading.Thread(target=self._download_thread, daemon=True).start()

    def _download_thread(self):
        import requests
        dest = mbtiles_target()
        tmp = dest + ".part"
        try:
            r = requests.get(MBTILES_URL, stream=True, timeout=60)
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            done = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(262144):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    Clock.schedule_once(
                        lambda dt, d=done, t=total: self._progress(d, t), 0)
            os.replace(tmp, dest)
            Clock.schedule_once(lambda dt: self._download_done(dest), 0)
        except Exception as e:
            try:
                os.remove(tmp)
            except OSError:
                pass
            Clock.schedule_once(lambda dt, e=str(e): self._download_failed(e), 0)

    def _progress(self, done, total):
        mb = done // 1048576
        if total:
            self._prog_lbl.text = f"{done * 100 // total} %  ({mb} / {total // 1048576} MB)"
        else:
            self._prog_lbl.text = f"{mb} MB"

    def _download_done(self, dest):
        self._prog.dismiss()
        self.mapview.map_source = HybridMapSource(
            mbtiles_path=dest, url=ONLINE_URL, cache_key="cyclosm",
            min_zoom=2, max_zoom=14, tile_size=256, image_ext="png",
            attribution="© OpenStreetMap, CyclOSM")
        self.status.text = "Offline-Karte geladen"

    def _download_failed(self, msg):
        self._prog.dismiss()
        self.status.text = "Download fehlgeschlagen"

    # --- layer menu (multi-select) ---------------------------------------
    def open_layers(self, *_):
        box = BoxLayout(orientation="vertical", spacing=6, padding=10,
                        size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        for src in self.gpx_layer.sources():
            tb = ToggleButton(text=src, size_hint_y=None, height=96, font_size="28sp",
                              state="down" if src in self.gpx_layer.enabled else "normal")
            tb.bind(on_release=lambda b, s=src:
                    self.gpx_layer.set_enabled(s, b.state == "down"))
            box.add_widget(tb)
        pk = ToggleButton(text="\U0001F53A Gipfelnamen", size_hint_y=None, height=96,
                          font_size="28sp",
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
        self._gps_on = False
        self._gps_configured = False
        self._gps_start()
        # show the arrow immediately from the last known fix (also works indoors)
        self._show_last_known()

    def _gps_interval(self):
        return 10000 if self.recorder.recording else 60000   # 10 s rec / 60 s idle

    def _gps_start(self):
        """Battery-friendly GPS + 60 s readout poll (plyer's callback is
        unreliable on Android 12+, so we poll the last-known fix ourselves)."""
        try:
            from plyer import gps
            if not self._gps_configured:
                gps.configure(on_location=self.on_location)
                self._gps_configured = True
            gps.start(minTime=self._gps_interval(), minDistance=5)
            self._gps_on = True
            self.status.text = "GPS: aktiv"
        except Exception as e:
            self.status.text = f"GPS n/v ({e})"
        if not getattr(self, "_disp_ev", None):
            self._disp_ev = Clock.schedule_interval(self._loc_tick, 60)
        self._loc_tick(0)

    def _gps_restart(self):
        try:
            from plyer import gps
            gps.stop()
            gps.start(minTime=self._gps_interval(), minDistance=5)
            self._gps_on = True
        except Exception:
            pass

    def _gps_stop(self):
        try:
            from plyer import gps
            gps.stop()
        except Exception:
            pass
        self._gps_on = False
        if getattr(self, "_disp_ev", None):
            self._disp_ev.cancel()
            self._disp_ev = None

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
        if ele is not None:
            self.last_ele = ele
        self.pos_layer.set_position(lat, lon, bearing)
        if not self._centered:            # centre once so the arrow is on-screen
            self._centered = True
            self.mapview.center_on(lat, lon)
        self.ele_lbl.text = self._ele_line()          # altitude line (always)
        if not self.recorder.recording:
            self.status.text = f"{lat:.5f}, {lon:.5f}"

    def _ele_line(self):
        return f"Höhe: {self.last_ele:.0f} m" if self.last_ele is not None else "Höhe: —"

    def _loc_tick(self, dt):
        """Idle readout refresh (60 s). Recording is handled by _rec_tick (10 s)."""
        if self.recorder.recording:
            return
        fix = self._read_location()
        if fix:
            self._update(*fix)

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
            self._gps_restart()                   # 10 s fixes while recording
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
            self._gps_restart()                   # back to 60 s idle


if __name__ == "__main__":
    OSMCycleApp().run()
