"""OSMCycle - CyclOSM cycling app for Bayern + Tirol + Kärnten + Südtirol.

* Offline map (combined MBTiles) + Nachladen from the tile server.
* GPS track recording -> GPX (like OsmAnd).
* Current-position arrow (rotates to heading) + centre-on-me button.

Hiking trails and recorded tracks are shown as an efficient GPX overlay.
"""
import glob
import os
import re
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
                   PeaksLayer, PointsLayer, gpx_dir,
                   COLOR_MASTS, COLOR_BATHING, COLOR_GROUNDWATER)

MBTILES_NAME = "alpen.mbtiles"

# --- Update-Check -----------------------------------------------------------
# Die App installiert nichts selbst; sie vergleicht nur die eigene Version mit
# dem neuesten GitHub-Release und reicht den Download an den Browser weiter.
# get_apk.php leitet stabil auf das Asset der neuesten Release-APK.
GITHUB_LATEST = "https://api.github.com/repos/gerontec/osmcycle/releases/latest"
APK_REDIRECT = "https://heissa.de/web1/get_apk.php"
# Nur Notnagel: auf Android kommt die Version aus PackageInfo.versionName,
# das ist die Wahrheit aus buildozer.spec und kann nicht davon abweichen.
APP_VERSION = "1.2"

# Punkt-Layer, aus wagodb exportiert (siehe scripts/export_points.sh)
MASTS_NAME = "sendemasten.json"        # EMF-Standorte der BNetzA
BATHING_NAME = "badestellen.json"      # LGL-Badegewaesser
GROUNDWATER_NAME = "grundwasser.json"  # GKD-Grundwassermessstellen
# Public tile server (netcup) — works out of the box for new users, no home
# server / IPv6 needed. Serves z6-14 from CyclOSM_Alpen.sqlitedb via tile.php.
ONLINE_URL = "https://tmind.de/maps/tile.php?z={z}&x={x}&y={y}"
# Offline map for first-run download (new users, no map yet)
MBTILES_URL = "https://tmind.de/maps/alpen.mbtiles"
# Public GPX drop — recorded tracks are uploaded here once/day so they show up
# on https://heissa.de/web1/gpx_report.php. No token, anyone may upload.
GPX_UPLOAD_URL = "https://heissa.de/web1/gpx_upload.php"
HERE = os.path.dirname(os.path.abspath(__file__))


# A live LocationListener: getLastKnownLocation() returns a *stale cached* fix
# that barely moves, which collapsed real rides to a near-stationary blob. This
# streams fresh fixes straight from the GPS provider so recording follows the
# actual route.
try:
    from jnius import PythonJavaClass, java_method, autoclass  # type: ignore
    _HAVE_JNIUS = True

    class _LocationListener(PythonJavaClass):
        __javainterfaces__ = ['android/location/LocationListener']
        __javacontext__ = 'app'

        def __init__(self, cb):
            super().__init__()
            self._cb = cb

        @java_method('(Landroid/location/Location;)V')
        def onLocationChanged(self, location):
            try:
                self._cb(location)
            except Exception:
                pass

        @java_method('(Ljava/lang/String;ILandroid/os/Bundle;)V')
        def onStatusChanged(self, provider, status, extras):
            pass

        @java_method('(Ljava/lang/String;)V')
        def onProviderEnabled(self, provider):
            pass

        @java_method('(Ljava/lang/String;)V')
        def onProviderDisabled(self, provider):
            pass
except Exception:
    _HAVE_JNIUS = False


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


def _report_name(fname):
    """Rename own recordings (track_YYYY-MM-DD_HH-MM-SS.gpx) to the
    YYYY-MM-DD_HH-MM_Weekday.gpx convention gpx_report.py parses for its date
    column. Anything else is uploaded under its original name."""
    import re
    from datetime import datetime
    m = re.match(r"track_(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-\d{2}\.gpx$", fname)
    if not m:
        return fname
    try:
        d = datetime.strptime(m.group(1), "%Y-%m-%d")
        return f"{m.group(1)}_{m.group(2)}-{m.group(3)}_{d.strftime('%a')}.gpx"
    except Exception:
        return fname


def upload_tracks_daily():
    """Once per day, POST own recorded tracks (track_*.gpx) to the public
    heissa.de endpoint so they appear on the online report. Runs in a background
    daemon thread; tolerant of failure (offline, no server), retries next day."""
    import time
    try:
        import requests
    except Exception as e:
        print(f"[upload] no requests: {e}")
        return
    d = gpx_dir()
    stamp = os.path.join(d, ".last_upload")
    try:
        if os.path.exists(stamp) and (time.time() - os.path.getmtime(stamp)) < 86400:
            print("[upload] skip: uploaded within last 24h")
            return
    except Exception:
        pass
    tracks = sorted(glob.glob(os.path.join(d, "track_*.gpx")))
    print(f"[upload] dir={d} tracks={len(tracks)} -> {GPX_UPLOAD_URL}")
    sent = 0
    for path in tracks:
        up = _report_name(os.path.basename(path))
        try:
            with open(path, "rb") as fh:
                r = requests.post(GPX_UPLOAD_URL,
                                  files={"file": (up, fh, "application/gpx+xml")},
                                  timeout=30)
            print(f"[upload] {up} -> HTTP {r.status_code} {r.text[:40]}")
            if r.status_code == 200:
                sent += 1
        except Exception as e:
            print(f"[upload] fail {up}: {e}")
    if sent:
        try:
            with open(stamp, "w") as fh:
                fh.write(str(int(time.time())))
        except Exception:
            pass
    print(f"[upload] done, {sent} sent")


def version_tuple(text):
    """'v1.10' -> (1, 10). Leeres Tupel, wenn nichts Brauchbares drinsteht —
    dann wird nicht verglichen und der Nutzer nicht mit Unsinn behelligt."""
    parts = []
    for chunk in re.split(r"[.\-+_]", (text or "").strip().lstrip("vV")):
        if not chunk.isdigit():
            break                      # Suffixe wie '1.2-beta' hoeren hier auf
        parts.append(int(chunk))
    return tuple(parts)


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
        # Gleiche Gipfel, 20 % groessere Schrift (Sehschwaeche). Teilt sich die
        # geparsten Punkte mit dem Standard-Layer, statt die GPX erneut zu lesen.
        self.peaks_big_layer = PeaksLayer([], font_size=PeaksLayer.FONT_SIZE * 1.2)
        self.peaks_big_layer.peaks = self.peaks_layer.peaks
        self.mapview.add_layer(self.peaks_big_layer)
        # Punkt-Layer: Grundwasser zuerst, damit die selteneren Badestellen und
        # die Masten darueber liegen und nicht verdeckt werden.
        self.groundwater_layer = PointsLayer(
            os.path.join(HERE, GROUNDWATER_NAME), COLOR_GROUNDWATER, min_zoom=11)
        self.mapview.add_layer(self.groundwater_layer)
        self.bathing_layer = PointsLayer(
            os.path.join(HERE, BATHING_NAME), COLOR_BATHING, min_zoom=10, radius=5)
        self.mapview.add_layer(self.bathing_layer)
        self.masts_layer = PointsLayer(
            os.path.join(HERE, MASTS_NAME), COLOR_MASTS, min_zoom=12)
        self.mapview.add_layer(self.masts_layer)
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
        self.ele_lbl.text = self._ele_line()   # Kartengroesse schon vor dem GPS-Fix
        # background offline-map download progress (empty unless downloading)
        self.dl_lbl = Label(text="", size_hint=(None, None),
                            size=(560, 28), pos_hint={"x": 0.01, "top": 0.918},
                            color=(0.1, 0.42, 0.15, 1), halign="left", valign="middle",
                            font_size="13sp", text_size=(560, 28))
        root.add_widget(self.dl_lbl)

        # REC (bottom-left)
        self.rec_btn = ToggleButton(text="● REC", size_hint=(None, None),
                                    size=(210, 90), pos_hint={"x": 0.02, "y": 0.03},
                                    font_size="30sp")
        self.rec_btn.bind(on_press=self.toggle_record)
        root.add_widget(self.rec_btn)

        # Layer menu (top-right) — multi-select overlay chooser
        layer_btn = Button(text="≡ Layer", size_hint=(None, None), size=(220, 90),
                           pos_hint={"right": 0.98, "top": 0.99}, font_size="22sp")
        layer_btn.bind(on_release=self.open_layers)
        root.add_widget(layer_btn)

        # Centre-on-me (bottom-right, circle symbol)
        self.center_btn = Button(text="◎", font_size=42, size_hint=(None, None),
                                 size=(110, 110), pos_hint={"right": 0.98, "y": 0.03})
        self.center_btn.bind(on_release=self.center_on_me)
        root.add_widget(self.center_btn)

        Clock.schedule_once(lambda dt: self.start_gps(), 1)
        Clock.schedule_once(lambda dt: self._check_update(), 3)   # still im Hintergrund
        if not mbt:                       # no offline map yet → fetch it
            Clock.schedule_once(lambda dt: self._auto_get_map(), 1.5)
        # once/day: push recorded tracks to the public heissa.de report
        threading.Thread(target=upload_tracks_daily, daemon=True).start()
        return root

    # --- Update-Check ------------------------------------------------------
    def _app_version(self):
        """Eigene Version. Auf Android aus PackageInfo (kommt aus buildozer.spec),
        sonst der Notnagel APP_VERSION."""
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            ctx = PythonActivity.mActivity
            return ctx.getPackageManager().getPackageInfo(
                ctx.getPackageName(), 0).versionName
        except Exception:
            return APP_VERSION

    def _check_update(self):
        threading.Thread(target=self._update_thread, daemon=True).start()

    def _update_thread(self):
        """Fragt das neueste GitHub-Release ab. Still bei jedem Fehler: ein
        fehlgeschlagener Update-Check darf die Karte nie stoeren."""
        import requests
        try:
            r = requests.get(GITHUB_LATEST, timeout=8,
                             headers={"User-Agent": "osmcycle"})
            tag = r.json().get("tag_name", "")
        except Exception:
            return
        latest, current = version_tuple(tag), version_tuple(self._app_version())
        if latest and current and latest > current:
            Clock.schedule_once(lambda dt: self._offer_update(tag))

    def _offer_update(self, tag):
        box = BoxLayout(orientation="vertical", spacing=12, padding=16)
        box.add_widget(Label(
            text=f"Neue Version {tag} verfügbar.\n"
                 f"Installiert: v{self._app_version()}",
            font_size="26sp", halign="center"))
        row = BoxLayout(size_hint_y=None, height=110, spacing=12)
        yes = Button(text="Laden", font_size="30sp")
        no = Button(text="Später", font_size="30sp")
        row.add_widget(yes)
        row.add_widget(no)
        box.add_widget(row)
        self._upd = Popup(title="Update", content=box, size_hint=(0.9, 0.5))
        yes.bind(on_release=lambda b: (self._upd.dismiss(),
                                       self._open_url(APK_REDIRECT)))
        no.bind(on_release=lambda b: self._upd.dismiss())
        self._upd.open()

    def _open_url(self, url):
        """Uebergibt an den Browser. Die Installation macht Android selbst — eine
        In-App-Installation braeuchte REQUEST_INSTALL_PACKAGES + FileProvider."""
        try:
            from jnius import autoclass, cast
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
            intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            cast("android.content.Context",
                 PythonActivity.mActivity).startActivity(intent)
        except Exception:
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception:
                pass

    # --- first-run offline-map download ----------------------------------
    def _is_metered(self):
        """True on mobile data / metered WiFi (or if unknown) — used to avoid
        auto-pulling the ~2.4 GB map over a cellular plan."""
        try:
            from jnius import autoclass
            Context = autoclass("android.content.Context")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            cm = PythonActivity.mActivity.getSystemService(Context.CONNECTIVITY_SERVICE)
            return bool(cm.isActiveNetworkMetered())
        except Exception:
            return True

    def _auto_get_map(self):
        """No offline map yet: auto-download on WiFi (non-blocking, app stays
        usable via online streaming); on mobile data ask first (2.4 GB)."""
        if self._is_metered():
            self._offer_download()
        else:
            self._start_download(blocking=False)

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

    def _start_download(self, blocking=True):
        if blocking:
            self._prog_lbl = Label(text="0 %", font_size="30sp")
            self._prog = Popup(title="Karte wird geladen…", content=self._prog_lbl,
                               size_hint=(0.9, 0.3), auto_dismiss=False)
            self._prog.open()
        else:                                  # WiFi auto: progress in the label
            self._prog = None
            self.dl_lbl.text = "Karte lädt… 0 %"
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
        txt = (f"{done * 100 // total} %  ({mb} / {total // 1048576} MB)"
               if total else f"{mb} MB")
        if getattr(self, "_prog", None):
            self._prog_lbl.text = txt
        else:
            self.dl_lbl.text = "Karte lädt… " + txt

    def _download_done(self, dest):
        if getattr(self, "_prog", None):
            self._prog.dismiss()
        self.dl_lbl.text = ""
        self.mapview.map_source = HybridMapSource(
            mbtiles_path=dest, url=ONLINE_URL, cache_key="cyclosm",
            min_zoom=2, max_zoom=14, tile_size=256, image_ext="png",
            attribution="© OpenStreetMap, CyclOSM")
        self.status.text = "Offline-Karte geladen"

    def _download_failed(self, msg):
        if getattr(self, "_prog", None):
            self._prog.dismiss()
        self.dl_lbl.text = "Karten-Download fehlgeschlagen (später erneut)"

    # --- layer menu (multi-select) ---------------------------------------
    def open_layers(self, *_):
        box = BoxLayout(orientation="vertical", spacing=6, padding=10,
                        size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        for src in self.gpx_layer.sources():
            tb = ToggleButton(text=src, size_hint_y=None, height=96, font_size="22.4sp",
                              state="down" if src in self.gpx_layer.enabled else "normal")
            tb.bind(on_release=lambda b, s=src:
                    self.gpx_layer.set_enabled(s, b.state == "down"))
            box.add_widget(tb)
        pk = ToggleButton(text="\U0001F53A Gipfelnamen", size_hint_y=None, height=96,
                          font_size="22.4sp",
                          state="down" if self.peaks_layer.visible else "normal")
        box.add_widget(pk)
        pk_big = ToggleButton(text="\U0001F53A Gipfelnamen groß", size_hint_y=None,
                              height=96, font_size="22.4sp",
                              state="down" if self.peaks_big_layer.visible else "normal")
        box.add_widget(pk_big)

        # Beide Gipfel-Layer zeigen dieselben Namen; gleichzeitig aktiv wuerden
        # sie uebereinander zeichnen -> der eine schaltet den anderen ab.
        def _peaks(_b):
            on = pk.state == "down"
            self.peaks_layer.set_visible(on)
            if on and pk_big.state == "down":
                pk_big.state = "normal"
                self.peaks_big_layer.set_visible(False)

        def _peaks_big(_b):
            on = pk_big.state == "down"
            self.peaks_big_layer.set_visible(on)
            if on and pk.state == "down":
                pk.state = "normal"
                self.peaks_layer.set_visible(False)

        pk.bind(on_release=_peaks)
        pk_big.bind(on_release=_peaks_big)

        for text, layer in (("\U0001F4F6 Sendemasten", self.masts_layer),
                            ("\U0001F3CA Badestellen", self.bathing_layer),
                            ("\U0001F4A7 Grundwasserbrunnen", self.groundwater_layer)):
            tb = ToggleButton(text=f"{text} ({layer.count()})", size_hint_y=None,
                              height=96, font_size="22.4sp",
                              state="down" if layer.visible else "normal")
            tb.bind(on_release=lambda b, ly=layer: ly.set_visible(b.state == "down"))
            box.add_widget(tb)
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
        self._live_fix = None
        self._loc_listener = None
        self._ensure_loc_listener()
        self._gps_start()
        # show the arrow immediately from the last known fix (also works indoors)
        self._show_last_known()

    def _ensure_loc_listener(self):
        """Register our own LocationListener so recording follows live GPS
        instead of the stale last-known cache. Idempotent; no-op off Android."""
        if getattr(self, "_loc_listener", None) is not None or not _HAVE_JNIUS:
            return
        try:
            Context = autoclass("android.content.Context")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            self._lm = PythonActivity.mActivity.getSystemService(Context.LOCATION_SERVICE)
            self._loc_listener = _LocationListener(self._on_new_location)
            self._request_loc_updates()
        except Exception:
            self._loc_listener = None

    def _request_loc_updates(self):
        """(Re)subscribe the listener at a record-aware cadence: ~2 s while
        recording (accurate track), 30 s idle (battery)."""
        if not _HAVE_JNIUS or getattr(self, "_loc_listener", None) is None:
            return
        try:
            Looper = autoclass("android.os.Looper")
            looper = Looper.getMainLooper()
            min_ms = 2000 if self.recorder.recording else 30000
            self._lm.removeUpdates(self._loc_listener)
            for prov in ("gps", "network"):
                try:
                    self._lm.requestLocationUpdates(prov, min_ms, 0.0,
                                                    self._loc_listener, looper)
                except Exception:
                    pass
        except Exception:
            pass

    def _on_new_location(self, location):
        try:
            self._live_fix = (
                location.getLatitude(), location.getLongitude(),
                location.getAltitude() if location.hasAltitude() else None,
                location.getBearing() if location.hasBearing() else None,
                location.getTime())
        except Exception:
            pass

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
        self._request_loc_updates()               # match listener cadence to rec state
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
        """Freshest fix available: the live LocationListener stream vs. each
        provider's last-known, chosen by timestamp so a moving ride is actually
        followed (last-known alone is stale and barely moves). Returns
        (lat, lon, ele, bearing) or None."""
        best = None
        best_t = -1
        live = getattr(self, "_live_fix", None)
        if live is not None:
            best = (live[0], live[1], live[2], live[3])
            best_t = live[4]
        try:
            from jnius import autoclass
            Context = autoclass("android.content.Context")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            lm = PythonActivity.mActivity.getSystemService(Context.LOCATION_SERVICE)
            for prov in ("gps", "fused", "network"):
                try:
                    loc = lm.getLastKnownLocation(prov)
                except Exception:
                    loc = None
                if loc and loc.getTime() > best_t:
                    best_t = loc.getTime()
                    best = (loc.getLatitude(), loc.getLongitude(),
                            loc.getAltitude() if loc.hasAltitude() else None,
                            loc.getBearing() if loc.hasBearing() else None)
        except Exception:
            pass
        return best

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

    def _map_size_text(self):
        """Groesse der aktiven Offline-Karte. Bei laufendem Download waechst die
        Datei, darum jedes Mal frisch statten statt zu cachen."""
        path = find_mbtiles()
        if not path:
            return None
        try:
            gb = os.path.getsize(path) / 2 ** 30
        except OSError:
            return None
        return f"{gb:.1f}".replace(".", ",") + " GB"

    def _ele_line(self):
        ele = (f"Höhe: {self.last_ele:.0f} m" if self.last_ele is not None
               else "Höhe: —")
        size = self._map_size_text()
        return f"{ele}   ·   Karte: {size}" if size else ele

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
