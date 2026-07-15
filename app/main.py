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
from kivy.graphics import Color, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.togglebutton import ToggleButton
from kivy_garden.mapview import MapView

from appconfig import Config, ControlServer
import locusbridge
from hybridsource import HybridMapSource, HIZOOM_FROM
from track import (TrackLayer, TrackRecorder, PositionLayer, GpxLayer,
                   PeaksLayer, PointsLayer, gpx_dir, _writable,
                   COLOR_MASTS, COLOR_BATHING, COLOR_GROUNDWATER,
                   COLOR_WATERFALL)

MBTILES_NAME = "alpen_z15.mbtiles"
# Mitgelieferte Welt-Uebersicht (nur Kontinente, z0-5, ~1,2 MB). Sofort-Karte,
# bis die grosse Offline-Karte vollstaendig geladen ist. Wird von find_mbtiles()
# NICHT als "grosse Karte" erkannt (anderer Name), blockt den Download also nicht.
MINI_NAME = "mini.mbtiles"

# --- Update-Check -----------------------------------------------------------
# Die App installiert nichts selbst; sie vergleicht nur die eigene Version mit
# dem neuesten GitHub-Release und reicht den Download an den Browser weiter.
# get_apk.php leitet stabil auf das Asset der neuesten Release-APK.
GITHUB_LATEST = "https://api.github.com/repos/gerontec/osmcycle/releases/latest"
APK_REDIRECT = "https://heissa.de/web1/get_apk.php"
# Nur Notnagel: auf Android kommt die Version aus PackageInfo.versionName,
# das ist die Wahrheit aus buildozer.spec und kann nicht davon abweichen.
APP_VERSION = "2.1"
# Wird beim Build gestempelt (build_apk.sh setzt das Datum). Erscheint unten
# rechts auf der Karte als "vX.Y · JJJJ-MM-TT" statt der (C)-Attribution.
BUILD_DATE = "2026-07-13"

# Punkt-Layer, aus wagodb exportiert (siehe scripts/export_points.sh)
MASTS_NAME = "sendemasten.json"        # EMF-Standorte der BNetzA
BATHING_NAME = "badestellen.json"      # LGL-Badegewaesser
GROUNDWATER_NAME = "grundwasser.json"  # GKD-Grundwassermessstellen
WATERFALL_NAME = "wasserfaelle.json"   # waterway=waterfall aus OSM (BY/T/ST/K)
# Public tile server (netcup) — works out of the box for new users, no home
# server / IPv6 needed. tile.php serves z6-15 straight out of the same
# alpen_z15.mbtiles that MBTILES_URL hands out.
ONLINE_URL = "https://tmind.de/maps/tile.php?z={z}&x={x}&y={y}"
# Offline map for first-run download (new users, no map yet)
MBTILES_URL = "https://tmind.de/maps/alpen_z15.mbtiles"
# Public GPX drop — recorded tracks are uploaded here once/day so they show up
# on https://heissa.de/web1/gpx_report.php. No token, anyone may upload.
GPX_UPLOAD_URL = "https://heissa.de/web1/gpx_upload.php"
HERE = os.path.dirname(os.path.abspath(__file__))
# Locus Map's own offline-map folder. See find_mbtiles() for why we read from it.
LOCUS_MAPS = "/sdcard/Android/media/menion.android.locus/maps"
# Private broadcast the recording wake alarm fires at us (see _wake_alarm_arm)
WAKE_ACTION = "org.gerontec.osmcycle.WAKE"


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


def map_dir():
    """Folder for the offline map: PUBLIC, so a single copy is shared instead of
    a second 7 GB one. Prefers Locus's own maps folder — Locus reads offline maps
    ONLY from there, so downloading straight into it means both apps use one file
    (osmcycle still finds it via find_mbtiles). _writable() creates the folder if
    it does not exist yet. Falls back to /sdcard/maps/tiles (same layout OsmAnd
    expects, <data folder>/tiles/) when the Locus path is not writable. Kept out
    of the Syncthing folder (gpx_dir()) on purpose; needs 'All files access', see
    request_all_files_access()."""
    candidates = [LOCUS_MAPS, "/sdcard/maps/tiles", "/storage/emulated/0/maps/tiles"]
    try:
        from android import mActivity  # type: ignore
        ext = mActivity.getExternalFilesDir(None)
        if ext:                                   # app-private fallback
            candidates.append(ext.getAbsolutePath())
    except Exception:
        pass
    candidates.append(os.path.expanduser("~"))
    for d in candidates:
        if _writable(d):
            return d
    return candidates[-1]


def mbtiles_target():
    """Writable destination for the downloaded offline map."""
    return os.path.join(map_dir(), MBTILES_NAME)


def find_mbtiles():
    # map_dir() now prefers LOCUS_MAPS; still read the legacy public dirs so a
    # pack downloaded there by an earlier version is used instead of re-fetched.
    paths = [os.path.join(map_dir(), MBTILES_NAME),
             os.path.join("/sdcard/maps/tiles", MBTILES_NAME),
             os.path.join("/storage/emulated/0/maps/tiles", MBTILES_NAME)]
    try:
        # Maps downloaded by <=v1.5 still sit in the app-private dir; keep using
        # them instead of pulling the multi-GB pack down again.
        from android import mActivity  # type: ignore
        ext = mActivity.getExternalFilesDir(None)
        if ext:
            paths.append(os.path.join(ext.getAbsolutePath(), MBTILES_NAME))
    except Exception:
        pass
    # Locus reads offline maps ONLY from its own folders — Asamm dropped the
    # "external links" feature, so it cannot be pointed at /sdcard/maps. Its
    # Android/media folder is the one place both apps can reach: unlike
    # Android/data it is not sandboxed, and All-files access covers it. Sharing
    # the file from there beats keeping a second 7 GB copy.
    paths.append(os.path.join(LOCUS_MAPS, MBTILES_NAME))
    paths += [os.path.join(HERE, MBTILES_NAME), MBTILES_NAME]
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
        # Alle Einstellungen liegen in EINER Datei im oeffentlichen GPX-Ordner
        # (/sdcard/osmcycle/config.json). request_all_files_access() laeuft erst
        # weiter unten, darum hier den Ordner selbst anlegen — sonst landet die
        # Datei im app-privaten Fallback und waere per adb nicht erreichbar.
        request_all_files_access()
        self.cfg = Config(gpx_dir()).load()

        mbt = find_mbtiles()
        mini = os.path.join(HERE, MINI_NAME)
        lo = self.cfg.get("map.min_zoom", 2)
        hi = self.cfg.get("map.max_zoom", 18)
        hz = self.cfg.get("map.hizoom_from", HIZOOM_FROM)
        if mbt:
            source = HybridMapSource(mbtiles_path=mbt, url=ONLINE_URL,
                                     hizoom_from=hz,
                                     cache_key="cyclosm", min_zoom=lo, max_zoom=hi,
                                     tile_size=256, image_ext="png",
                                     attribution="")
        elif os.path.exists(mini):
            # Noch keine grosse Karte: die mitgelieferte Welt-Uebersicht (z0-5,
            # nur Kontinente) sofort offline zeigen; z6+ kommt online dazu, bis
            # der grosse Download fertig ist und _download_done umschaltet.
            source = HybridMapSource(mbtiles_path=mini, url=ONLINE_URL,
                                     hizoom_from=hz,
                                     cache_key="cyclosm", min_zoom=0, max_zoom=hi,
                                     tile_size=256, image_ext="png",
                                     attribution="")
        else:
            # Gar keine Offline-Karte: trotzdem die Hybrid-Quelle, sonst gaebe
            # es oberhalb von z15 nur 404s von tile.php.
            source = HybridMapSource(mbtiles_path=None, url=ONLINE_URL,
                                     hizoom_from=hz,
                                     cache_key="cyclosm", min_zoom=lo, max_zoom=hi,
                                     tile_size=256, image_ext="png",
                                     attribution="")

        root = FloatLayout()
        # Mit Detailkarte direkt in die Alpen. Ohne (nur Mini-Weltkarte) auf
        # Uebersichtszoom starten, damit sofort die Kontinente sichtbar sind
        # statt einer leeren Flaeche; nach dem Download schaltet _download_done um.
        start_zoom = self.cfg.get("map.start_zoom", 13) if mbt else 3
        self.mapview = MapView(zoom=start_zoom,
                               lat=self.cfg.get("map.start_lat", 47.68),
                               lon=self.cfg.get("map.start_lon", 11.57))
        self.mapview.map_source = source
        root.add_widget(self.mapview)

        self.track_layer = TrackLayer()
        self.mapview.add_layer(self.track_layer)
        # single (public) gpx folder: bundled routes + own recordings
        seed_gpx()
        self.gpx_layer = GpxLayer([gpx_dir()])
        self.mapview.add_layer(self.gpx_layer)
        # Gipfelnamen in groesserer Schrift (Sehschwaeche) — der einzige
        # Gipfel-Layer; liest die GPX-Waypoints selbst.
        self.peaks_big_layer = PeaksLayer([gpx_dir()],
                                          font_size=PeaksLayer.FONT_SIZE * 1.2)
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
        # Waterfalls are sparse landmarks (1711 in all four regions), so a higher
        # per-frame cap than the dense masts is fine; z12 like the masts.
        self.waterfall_layer = PointsLayer(
            os.path.join(HERE, WATERFALL_NAME), COLOR_WATERFALL, min_zoom=12,
            max_points=800, radius=5)
        self.mapview.add_layer(self.waterfall_layer)
        self.pos_layer = PositionLayer()
        self.mapview.add_layer(self.pos_layer)

        # OSMCycles eigene Punkt-DB im Locus-Format (groups + waypoints, Dezimal-
        # grad) — ein geteiltes Format fuer beide Apps. Einmalig im Hintergrund
        # aus den geladenen Layern aufbauen. Siehe app/pointsdb.py und
        # docs/locus_offline_points.md.
        try:
            import pointsdb
            self.points_db = os.path.join(gpx_dir(), pointsdb.DB_NAME)
            if not os.path.exists(self.points_db):
                threading.Thread(target=pointsdb.build, args=(self.points_db, {
                    "gipfel": self.peaks_big_layer.peaks,
                    "wasserfaelle": self.waterfall_layer.points,
                    "badestellen": self.bathing_layer.points,
                    "grundwasser": self.groundwater_layer.points,
                    "masten": self.masts_layer.points,
                }), daemon=True).start()
        except Exception as e:
            print("[pointsdb] build skipped: {!r}".format(e))

        self.recorder = TrackRecorder()
        self.last_lat = self.last_lon = self.last_ele = None
        self._centered = False

        self.status = self._readout(text="GPS: warte…", top=0.99)
        root.add_widget(self.status)
        self.ele_lbl = self._readout(text="", top=0.955)
        root.add_widget(self.ele_lbl)
        self.ele_lbl.text = self._ele_line()   # Kartengroesse schon vor dem GPS-Fix
        # background offline-map download progress (empty unless downloading).
        # Height follows the rendered text (texture_size) so it never clips —
        # robust across devices with different screen densities.
        self.dl_lbl = Label(text="", size_hint=(None, None),
                            width=820, height=40, pos_hint={"x": 0.01, "top": 0.84},
                            color=(0.05, 0.35, 0.10, 1), halign="left", valign="middle",
                            font_size="24sp", bold=True, text_size=(820, None))
        self.dl_lbl.bind(
            texture_size=lambda inst, ts: setattr(inst, "height", ts[1] + 12))
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

        # Zoom +/- als kompakter Cluster unten rechts, über dem ◎-Button,
        # aktuelle Stufe darunter (max z15).
        self.zoom_in_btn = Button(text="+", font_size=40, size_hint=(None, None),
                                  size=(88, 88),
                                  pos_hint={"right": 0.98, "y": 0.25})
        self.zoom_in_btn.bind(on_release=lambda b: self._zoom_by(1))
        root.add_widget(self.zoom_in_btn)
        self.zoom_out_btn = Button(text="−", font_size=40, size_hint=(None, None),
                                   size=(88, 88),
                                   pos_hint={"right": 0.98, "y": 0.155})
        self.zoom_out_btn.bind(on_release=lambda b: self._zoom_by(-1))
        root.add_widget(self.zoom_out_btn)
        # Zoom-Stufe als Button im gleichen Stil wie +/- (dunkler Grund, weißer
        # Text rendert zuverlässig — reines Label war auf der E-Ink-Karte
        # unlesbar). Rein anzeigend, keine Aktion.
        self.zoom_lbl = Button(text=f"z{start_zoom}", size_hint=(None, None),
                               size=(88, 48),
                               pos_hint={"right": 0.98, "y": 0.115},
                               font_size="24sp", bold=True)
        root.add_widget(self.zoom_lbl)
        self.mapview.bind(zoom=self._on_zoom_changed)

        # Release + Deploy-Datum unten rechts (ersetzt die (C)-Attribution).
        # Sitzt am unteren Rand unter dem ◎-Button.
        self.info_lbl = Label(
            text=f"v{self._app_version()} · {BUILD_DATE}",
            size_hint=(None, None), size=(360, 24),
            pos_hint={"right": 0.995, "y": 0.0},
            color=(0, 0, 0, 0.6), halign="right", valign="bottom",
            font_size="12sp", text_size=(360, 24))
        root.add_widget(self.info_lbl)

        # Resolve the Locus classes here, on the Kivy thread: autoclass() from the
        # HTTP thread hits the system class loader and cannot see the APK.
        locusbridge.preload()
        self.apply_config()                       # layers etc. from config.json
        # Pick up external edits (adb push / echo) within a couple of seconds,
        # so the app can be reconfigured without ever touching the screen.
        Clock.schedule_interval(self._config_tick, 2)
        if self.cfg.get("control.http_enabled", True):
            self.control = ControlServer(
                self.cfg, self.state, self.action, self._apply_config_threadsafe,
                port=self.cfg.get("control.port", 8765))
            self.control.start()

        Clock.schedule_once(lambda dt: self.start_gps(), 1)
        Clock.schedule_once(lambda dt: self._check_update(), 3)   # still im Hintergrund
        if not mbt:                       # no offline map yet → fetch it
            Clock.schedule_once(lambda dt: self._auto_get_map(), 1.5)
        if self.cfg.get("record.autostart", False):
            Clock.schedule_once(lambda dt: self.action("record_start", {}), 2)
        # once/day: push recorded tracks to the public heissa.de report
        threading.Thread(target=upload_tracks_daily, daemon=True).start()
        return root

    def _readout(self, text, top):
        """Eine Ablesezeile (GPS-Status / Hoehe) oben links.

        Zwei Fallen, die hier vorher beide zugeschnappt sind:

        * 'sp' skaliert mit der System-Schriftgroesse (auf dem Poco font_scale
          1.4, bei 440 dpi also Faktor 3.85). Eine in rohen Pixeln festgenagelte
          Label-Hoehe ist dann kleiner als die Zeile und schneidet die Glyphen ab
          -> Hoehe NIE fixieren, sondern aus texture_size nachfuehren.
        * Schwarz direkt auf der Karte verschwindet ueber Wald und Hillshade
          -> auf eine halbtransparente Platte legen.

        Groesse und Fettung kommen aus der Config und werden von apply_config()
        live nachgezogen — die richtige Groesse haengt am Geraet, die will man
        nicht neu bauen muessen.
        """
        # 800 px: breit genug fuer "Höhe: 1234 m · Karte: 6,4 GB", endet aber vor
        # dem ≡-Layer-Button oben rechts (der beginnt bei ~838 px).
        width = 800
        lbl = Label(text=text, size_hint=(None, None), size=(width, 10),
                    pos_hint={"x": 0.01, "top": top},
                    color=(0, 0, 0, 1), halign="left", valign="middle",
                    text_size=(width - 24, None), padding=(12, 6))
        lbl.bind(texture_size=lambda w, ts: setattr(w, "height", ts[1] + 12))

        alpha = self.cfg.get("ui.panel_opacity", 0.78)
        if alpha > 0:
            with lbl.canvas.before:
                Color(1, 1, 1, alpha)
                plate = RoundedRectangle(pos=lbl.pos, size=lbl.size, radius=[10])
            lbl.bind(pos=lambda w, v: setattr(plate, "pos", w.pos),
                     size=lambda w, v: setattr(plate, "size", w.size))
        return lbl

    # --- config: file <-> UI ------------------------------------------------
    def _config_tick(self, dt):
        if self.cfg.reload_if_changed():
            self.apply_config()

    def _apply_config_threadsafe(self):
        """Entry point for the HTTP thread. Applying the config redraws layers,
        and Kivy refuses to build graphics instructions off the main thread —
        so hop over via Clock instead of drawing here."""
        Clock.schedule_once(lambda dt: self.apply_config(), 0)

    def apply_config(self):
        """Push the config onto the widgets. Idempotent, so it can run on every
        external change as well as once at startup."""
        cfg = self.cfg
        font_size = cfg.get("ui.font_size", 11)
        for lbl in (self.status, self.ele_lbl):
            lbl.font_size = f"{font_size}sp"
            lbl.bold = cfg.get("ui.bold", False)

        # peaks_big ist jetzt der einzige Gipfel-Layer; alte "klein"-Einstellung
        # (layers.peaks) uebernehmen, damit sie nicht stumm verlorengeht.
        self.peaks_big_layer.set_visible(
            cfg.get("layers.peaks_big", False) or cfg.get("layers.peaks", False))
        self.masts_layer.set_visible(cfg.get("layers.masts", False))
        self.bathing_layer.set_visible(cfg.get("layers.bathing", False))
        self.groundwater_layer.set_visible(cfg.get("layers.groundwater", False))
        self.waterfall_layer.set_visible(cfg.get("layers.waterfalls", False))
        wanted = set(cfg.get("layers.gpx", []) or [])
        for src in self.gpx_layer.sources():
            self.gpx_layer.set_enabled(src, src in wanted)

    def _store_layers(self):
        """Write the current overlay state back, so the file always mirrors what
        is on screen — otherwise a UI toggle would be undone by the next reload."""
        self.cfg.update({
            "layers.peaks_big": self.peaks_big_layer.visible,
            "layers.masts": self.masts_layer.visible,
            "layers.bathing": self.bathing_layer.visible,
            "layers.groundwater": self.groundwater_layer.visible,
            "layers.waterfalls": self.waterfall_layer.visible,
            "layers.gpx": sorted(self.gpx_layer.enabled),
        })

    # --- remote control (see appconfig.py) ----------------------------------
    def state(self):
        """Everything an outside caller needs to know without a screenshot."""
        mv = self.mapview
        mbt = find_mbtiles()
        return {
            "version": self._app_version(),
            "build_date": BUILD_DATE,
            "position": {"lat": self.last_lat, "lon": self.last_lon,
                         "ele": self.last_ele},
            "map": {"zoom": round(mv.zoom, 2), "lat": round(mv.lat, 6),
                    "lon": round(mv.lon, 6),
                    "min_zoom": mv.map_source.get_min_zoom(),
                    "max_zoom": mv.map_source.get_max_zoom(),
                    "mbtiles": mbt,
                    "mbtiles_gb": (round(os.path.getsize(mbt) / 2 ** 30, 2)
                                   if mbt else None)},
            "recording": {"active": self.recorder.recording,
                          "points": len(self.recorder.points)},
            "layers": {"peaks_big": self.peaks_big_layer.visible,
                       "masts": self.masts_layer.visible,
                       "bathing": self.bathing_layer.visible,
                       "groundwater": self.groundwater_layer.visible,
                       "waterfalls": self.waterfall_layer.visible,
                       "gpx_enabled": sorted(self.gpx_layer.enabled),
                       "gpx_available": sorted(self.gpx_layer.sources())},
            "gpx_dir": gpx_dir(),
            "status": self.status.text,
        }

    def action(self, name, params):
        """One-shot commands. Called from the HTTP thread, so every widget touch
        is bounced onto the Kivy thread via Clock — Kivy is not thread-safe."""
        def later(fn):
            Clock.schedule_once(lambda dt: fn(), 0)
            return {"ok": True, "action": name}

        if name == "focus":
            return later(self.center_on_me)
        if name == "zoom_in":
            return later(lambda: self._zoom_by(1))
        if name == "zoom_out":
            return later(lambda: self._zoom_by(-1))
        if name == "set_zoom":
            zoom = int(params.get("zoom", self.cfg.get("map.focus_zoom", 15)))
            return later(lambda: self._set_zoom(zoom))
        if name == "goto":
            try:
                lat = float(params["lat"])
                lon = float(params["lon"])
            except (KeyError, TypeError, ValueError):
                return {"ok": False, "error": "goto needs lat and lon"}
            zoom = params.get("zoom")
            return later(lambda: self._goto(lat, lon, zoom))
        if name == "record_start":
            return later(lambda: self._set_recording(True))
        if name == "record_stop":
            return later(lambda: self._set_recording(False))
        if name == "download_map":
            # Start/resume the offline pack download. _start_download() no-ops
            # when one is already running and resumes from the .part otherwise.
            return later(lambda: self._start_download(blocking=False))
        # Not bounced onto the Kivy thread: these touch no widget, only Java, and
        # 13 980 masts would visibly stall the map if they ran on it. Runs on the
        # HTTP thread so the caller actually gets a result back.
        if name in ("locus_send", "locus_remove", "locus_import"):
            return self._locus_action(name, params.get("layer", "all"))
        return {"ok": False, "error": f"unknown action: {name}",
                "known": ["focus", "zoom_in", "zoom_out", "set_zoom", "goto",
                          "record_start", "record_stop", "download_map",
                          "locus_send", "locus_remove", "locus_import"]}

    def _locus_layers(self):
        """The very data the ≡ Layer menu draws — Locus gets no second source."""
        return {
            "gipfel": self.peaks_big_layer.peaks,
            "masten": self.masts_layer.points,
            "badestellen": self.bathing_layer.points,
            "grundwasser": self.groundwater_layer.points,
            "wasserfaelle": self.waterfall_layer.points,
        }

    def _locus_action(self, name, which):
        if not locusbridge.available():
            return {"ok": False, "error": "Locus Map ist nicht installiert"}
        layers = self._locus_layers()
        wanted = list(layers) if which == "all" else [w.strip() for w in
                                                      which.split(",")]
        unknown = [w for w in wanted if w not in layers]
        if unknown:
            return {"ok": False, "error": f"unbekannte Layer: {unknown}",
                    "known": list(layers)}
        result = {}
        for w in wanted:
            if name == "locus_send":
                result[w] = {"sent": locusbridge.send_layer(w, layers[w]),
                             "points": len(layers[w])}
            elif name == "locus_import":
                # Persist into Locus's own DB (offline, survives restarts).
                result[w] = {"imported": locusbridge.import_layer(w, layers[w]),
                             "points": len(layers[w])}
            else:
                result[w] = {"removed": locusbridge.remove_layer(w)}
        return {"ok": True, "action": name, "layers": result}

    def _set_zoom(self, zoom):
        mv = self.mapview
        mv.zoom = max(mv.map_source.get_min_zoom(),
                      min(mv.map_source.get_max_zoom(), int(zoom)))

    def _goto(self, lat, lon, zoom=None):
        if zoom is not None:
            self._set_zoom(zoom)
        self.mapview.center_on(lat, lon)

    def _set_recording(self, on):
        """Drive the REC button rather than the recorder, so the UI and the
        recorder can never disagree about whether we are recording."""
        if on == self.recorder.recording:
            return
        self.rec_btn.state = "down" if on else "normal"
        self.toggle_record()

    def _zoom_by(self, delta):
        """+/- buttons: step the zoom one level, clamped to the source range
        (the offline pack caps at z15)."""
        self._set_zoom(int(round(self.mapview.zoom)) + delta)

    def _on_zoom_changed(self, mapview, zoom):
        self.zoom_lbl.text = f"z{int(round(zoom))}"

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
        auto-pulling the ~6.9 GB map over a cellular plan."""
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
        usable via online streaming); on mobile data ask first (6.9 GB)."""
        if self._is_metered():
            self._offer_download()
        else:
            self._start_download(blocking=False)

    def _offer_download(self):
        box = BoxLayout(orientation="vertical", spacing=12, padding=16)
        box.add_widget(Label(
            text="Offline-Karte (~6,9 GB, Zoom 15) jetzt herunterladen?\n"
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
        if getattr(self, "_dl_running", False):    # already downloading/resuming
            return
        self._dl_running = True
        if blocking:
            self._prog_lbl = Label(text="0 %", font_size="30sp")
            self._prog = Popup(title="Karte wird geladen…", content=self._prog_lbl,
                               size_hint=(0.9, 0.3), auto_dismiss=False)
            self._prog.open()
        else:                                  # WiFi auto: progress in the label
            self._prog = None
            self.dl_lbl.text = "Karte lädt… 0 %"
        threading.Thread(target=self._download_thread, daemon=True).start()

    # Robust, resumable download (OsmAnd-style): the .part file is kept across
    # failures and app restarts; each attempt resumes from the last byte via an
    # HTTP Range request, with a bounded number of auto-retries and backoff.
    MAP_DL_RETRIES = 12

    def _download_thread(self):
        import requests
        import time
        dest = mbtiles_target()
        tmp = dest + ".part"
        last_err = None
        try:
            for attempt in range(1, self.MAP_DL_RETRIES + 1):
                try:
                    if self._download_once(requests, tmp, dest):
                        Clock.schedule_once(
                            lambda dt: self._download_done(dest), 0)
                        return
                except Exception as e:                 # network drop / timeout
                    last_err = str(e)
                    have = 0
                    try:
                        have = os.path.getsize(tmp)
                    except OSError:
                        pass
                    Clock.schedule_once(
                        lambda dt, a=attempt, h=have:
                        self._progress_retry(a, h), 0)
                    time.sleep(min(30, 2 ** attempt))  # exponential backoff
            # retries exhausted — keep the .part file so a later run resumes
            Clock.schedule_once(
                lambda dt, e=last_err: self._download_failed(e), 0)
        finally:
            self._dl_running = False

    def _download_once(self, requests, tmp, dest):
        """One resume attempt. Returns True when the file is complete."""
        have = 0
        try:
            have = os.path.getsize(tmp)
        except OSError:
            have = 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        r = requests.get(MBTILES_URL, stream=True, timeout=60, headers=headers)
        # Whole file already on disk (server rejects the range as satisfied).
        if r.status_code == 416:
            r.close()
            if os.path.exists(tmp):
                os.replace(tmp, dest)
                return True
            return False
        r.raise_for_status()
        # If we asked to resume but the server ignored the Range (200 not 206),
        # restart from scratch to avoid a corrupt (double-prefixed) file.
        if have and r.status_code != 206:
            have = 0
        mode = "ab" if have else "wb"
        cr = r.headers.get("content-range", "")
        if "/" in cr:
            total = int(cr.rsplit("/", 1)[1])
        else:
            total = int(r.headers.get("content-length", 0)) + have
        done = have
        with open(tmp, mode) as f:
            for chunk in r.iter_content(262144):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                Clock.schedule_once(
                    lambda dt, d=done, t=total: self._progress(d, t), 0)
        # Only accept the file once every byte is present.
        if total and os.path.getsize(tmp) < total:
            raise IOError("incomplete: %d/%d" % (os.path.getsize(tmp), total))
        os.replace(tmp, dest)
        return True

    def _progress(self, done, total):
        # Percent on the first line, size in GB on the second — stays big and
        # readable without the size running off the right edge (2 lines fit).
        if total:
            pct = done * 100 // total
            sz = (f"{done / 1073741824:.1f} / {total / 1073741824:.1f} GB"
                  .replace(".", ","))
            txt = f"{pct} %\n{sz}"
        else:
            txt = f"{done // 1048576} MB"
        if getattr(self, "_prog", None):
            self._prog_lbl.text = txt
        else:
            self.dl_lbl.text = "Karte lädt… " + txt

    def _progress_retry(self, attempt, have):
        mb = have // 1048576
        txt = (f"Neuer Versuch {attempt}/{self.MAP_DL_RETRIES} "
               f"(bei {mb} MB)…")
        if getattr(self, "_prog", None):
            self._prog_lbl.text = txt
        else:
            self.dl_lbl.text = txt

    def _download_done(self, dest):
        if getattr(self, "_prog", None):
            self._prog.dismiss()
        self.dl_lbl.text = ""
        self.mapview.map_source = HybridMapSource(
            mbtiles_path=dest, url=ONLINE_URL, cache_key="cyclosm",
            hizoom_from=self.cfg.get("map.hizoom_from", HIZOOM_FROM),
            min_zoom=self.cfg.get("map.min_zoom", 2),
            max_zoom=self.cfg.get("map.max_zoom", 18),
            tile_size=256, image_ext="png", attribution="")
        self.status.text = "Offline-Karte geladen"

    def _download_failed(self, msg):
        if getattr(self, "_prog", None):
            self._prog.dismiss()
        # The .part file is kept — the next start resumes where this stopped.
        self.dl_lbl.text = "Download unterbrochen – wird fortgesetzt"

    # --- layer menu (multi-select) ---------------------------------------
    def open_layers(self, *_):
        # 'sp' wird mit der System-Schriftgroesse skaliert (Poco: 1.4) — die
        # Zahl hier ist darum klein. Button-Hoehe bleibt bei 96 px, sonst wird
        # das Menue unterwegs nicht mehr treffsicher bedienbar.
        menu_fs = f"{self.cfg.get('ui.menu_font_size', 11)}sp"
        box = BoxLayout(orientation="vertical", spacing=6, padding=10,
                        size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        for src in self.gpx_layer.sources():
            tb = ToggleButton(text=src, size_hint_y=None, height=96, font_size=menu_fs,
                              state="down" if src in self.gpx_layer.enabled else "normal")
            tb.bind(on_release=lambda b, s=src: (
                    self.gpx_layer.set_enabled(s, b.state == "down"),
                    self._store_layers()))
            box.add_widget(tb)
        pk_big = ToggleButton(text="\U0001F53A Gipfelnamen", size_hint_y=None,
                              height=96, font_size=menu_fs,
                              state="down" if self.peaks_big_layer.visible else "normal")
        box.add_widget(pk_big)

        def _peaks_big(_b):
            self.peaks_big_layer.set_visible(pk_big.state == "down")
            self._store_layers()

        pk_big.bind(on_release=_peaks_big)

        for text, layer in (("\U0001F4F6 Sendemasten", self.masts_layer),
                            ("\U0001F3CA Badestellen", self.bathing_layer),
                            ("\U0001F4A7 Grundwasserbrunnen", self.groundwater_layer),
                            ("\U0001F4A6 Wasserfälle", self.waterfall_layer)):
            tb = ToggleButton(text=f"{text} ({layer.count()})", size_hint_y=None,
                              height=96, font_size=menu_fs,
                              state="down" if layer.visible else "normal")
            tb.bind(on_release=lambda b, ly=layer: (
                    ly.set_visible(b.state == "down"), self._store_layers()))
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
        key = "gps.rec_interval" if self.recorder.recording else "gps.idle_interval"
        return int(self.cfg.get(key, 10 if self.recorder.recording else 60)) * 1000

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
            self._disp_ev = Clock.schedule_interval(
                self._loc_tick, self.cfg.get("gps.idle_interval", 60))
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
        elif self.cfg.get("map.follow", False):   # keep the map under the arrow
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
        """Fokus-Button: nicht nur zentrieren, sondern gleich auf die hoechste
        Stufe zoomen (map.focus_zoom, per Default das Maximum der Offline-Karte).
        Zentriert, aber weit herausgezoomt ist unterwegs nutzlos."""
        if self.last_lat is None:
            return
        self._set_zoom(self.cfg.get("map.focus_zoom", 15))
        self.mapview.center_on(self.last_lat, self.last_lon)

    # --- wake alarm ------------------------------------------------------
    # _rec_tick hangs off Kivy's Clock, and that Clock only runs while the CPU
    # does. Screen off with no wake lock anywhere in the app means the device
    # suspends and the track simply stops growing -- the 380 s hole in
    # track_2026-07-09_10-17-10.gpx is exactly that. AllowWhileIdle alarms are
    # the one thing Android still delivers through Doze, so we re-arm one for
    # every recording and log a point from it. That does not keep the CPU up
    # (rec_interval is still best-effort); it bounds how much track a suspend
    # can swallow.
    def _wake_alarm_arm(self):
        """(Re)arm the one-shot safety alarm. Called on record start and again
        from every firing, because AllowWhileIdle alarms do not repeat."""
        secs = int(self.cfg.get("gps.wake_interval", 600) or 0)
        if secs <= 0 or not _HAVE_JNIUS:
            return
        try:
            if getattr(self, "_wake_rx", None) is None:
                self._wake_rx = self._wake_register_receiver()
            AlarmManager = autoclass("android.app.AlarmManager")
            SystemClock = autoclass("android.os.SystemClock")
            Context = autoclass("android.content.Context")
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            am = act.getSystemService(Context.ALARM_SERVICE)
            at = SystemClock.elapsedRealtime() + secs * 1000
            pi = self._wake_pending_intent()
            try:
                am.setExactAndAllowWhileIdle(
                    AlarmManager.ELAPSED_REALTIME_WAKEUP, at, pi)
            except Exception:
                # No exact-alarm permission (it is user-revocable): the inexact
                # variant needs none and still pierces Doze, it just may fire
                # late. A late point beats a missing one.
                am.setAndAllowWhileIdle(
                    AlarmManager.ELAPSED_REALTIME_WAKEUP, at, pi)
        except Exception as e:
            print(f"[wake] arm failed: {e}")

    def _wake_register_receiver(self):
        """p4a's BroadcastReceiver.start() calls the four-arg registerReceiver().
        From targetSdk 34 on, Android 14 rejects that for a non-system action
        like ours with a SecurityException -- the exported flag is mandatory.
        So build p4a's receiver but register it ourselves, NOT_EXPORTED: nobody
        outside this app has any business firing our wake alarm."""
        from android.broadcast import BroadcastReceiver
        Handler = autoclass("android.os.Handler")
        Context = autoclass("android.content.Context")
        VERSION = autoclass("android.os.Build$VERSION")
        act = autoclass("org.kivy.android.PythonActivity").mActivity

        rx = BroadcastReceiver(self._on_wake_alarm, actions=[WAKE_ACTION])
        rx.handlerthread.start()
        rx.handler = Handler(rx.handlerthread.getLooper())
        if VERSION.SDK_INT >= 33:                 # flag exists only from Tiramisu
            act.registerReceiver(rx.receiver, rx.receiver_filter, None,
                                 rx.handler, Context.RECEIVER_NOT_EXPORTED)
        else:
            act.registerReceiver(rx.receiver, rx.receiver_filter, None,
                                 rx.handler)
        return rx

    def _wake_pending_intent(self):
        Intent = autoclass("android.content.Intent")
        PendingIntent = autoclass("android.app.PendingIntent")
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        intent = Intent(WAKE_ACTION)
        intent.setPackage(act.getPackageName())
        return PendingIntent.getBroadcast(
            act, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE)

    def _wake_alarm_cancel(self):
        if not _HAVE_JNIUS:
            return
        try:
            Context = autoclass("android.content.Context")
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            act.getSystemService(Context.ALARM_SERVICE).cancel(
                self._wake_pending_intent())
        except Exception:
            pass
        if getattr(self, "_wake_rx", None) is not None:
            try:
                self._wake_rx.stop()
            except Exception:
                pass
            self._wake_rx = None
        self._wake_unlock()

    def _on_wake_alarm(self, context, intent):
        """Receiver thread. Android only guarantees the CPU stays up for the
        duration of onReceive, and we hand the actual work to the Kivy thread —
        so take our own short lock first, or the device can suspend again
        before the point is ever written."""
        self._wake_lock(20000)
        self._wake_alarm_arm()                    # re-arm before doing any work
        Clock.schedule_once(self._wake_tick, 0)   # graphics need the main thread

    def _wake_tick(self, dt):
        try:
            if self.recorder.recording:
                self._rec_tick(0)
        finally:
            self._wake_unlock()

    def _wake_lock(self, timeout_ms):
        """Always taken WITH a timeout: if the Kivy thread never gets round to
        _wake_tick, an untimed lock would pin the CPU awake forever."""
        if not _HAVE_JNIUS or getattr(self, "_wl", None) is not None:
            return
        try:
            Context = autoclass("android.content.Context")
            PowerManager = autoclass("android.os.PowerManager")
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            pm = act.getSystemService(Context.POWER_SERVICE)
            wl = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "osmcycle:wake")
            wl.setReferenceCounted(False)
            wl.acquire(timeout_ms)
            self._wl = wl
        except Exception as e:
            print(f"[wake] lock failed: {e}")
            self._wl = None

    def _wake_unlock(self):
        wl = getattr(self, "_wl", None)
        if wl is None:
            return
        try:
            if wl.isHeld():
                wl.release()
        except Exception:
            pass
        self._wl = None

    # --- recording -------------------------------------------------------
    def toggle_record(self, *_):
        if self.rec_btn.state == "down":
            self.recorder.start()
            self.track_layer.clear()
            self.rec_btn.text = "■ STOP"
            self.status.text = "REC gestartet"
            self._gps_restart()                   # 10 s fixes while recording
            self._rec_ev = Clock.schedule_interval(
                self._rec_tick, self.cfg.get("gps.rec_interval", 10))
            self._rec_tick(0)                     # drop the first dot immediately
            self._wake_alarm_arm()                # bound the damage of a suspend
        else:
            if getattr(self, "_rec_ev", None):
                self._rec_ev.cancel()
                self._rec_ev = None
            self._wake_alarm_cancel()
            path = self.recorder.stop_and_save()
            self.rec_btn.text = "● REC"
            self.status.text = (f"GPX: {os.path.basename(path)}" if path
                                else "Kein Track")
            self._gps_restart()                   # back to 60 s idle


if __name__ == "__main__":
    OSMCycleApp().run()
