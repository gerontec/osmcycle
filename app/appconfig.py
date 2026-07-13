"""Runtime settings + remote control for OSMCycle.

Every setting the UI can change also lives in ONE JSON file in the public GPX
folder, and the app re-reads that file whenever its mtime changes. So the app
can be driven entirely from a shell -- no tapping through screens:

    adb shell cat /sdcard/osmcycle/config.json
    adb shell 'sed -i s/"focus_zoom": 15/"focus_zoom": 12/ /sdcard/osmcycle/config.json'
    adb push config.json /sdcard/osmcycle/config.json

and over HTTP, which also reports live state and triggers actions:

    adb forward tcp:8765 tcp:8765
    curl localhost:8765/state
    curl localhost:8765/config
    curl -X POST localhost:8765/config -d '{"map.focus_zoom": 12}'
    curl -X POST localhost:8765/action -d '{"action": "focus"}'

Both routes write the same file, so they can never drift apart. The server
binds to 127.0.0.1 only: reachable through `adb forward` or from the device
itself, never from the network.
"""
import json
import os
import threading
import traceback

from http.server import BaseHTTPRequestHandler, HTTPServer

CONFIG_NAME = "config.json"
CONTROL_PORT = 8765

# The single source of truth for what a setting is called and what it defaults
# to. Anything not listed here is ignored on load, so a stale or hand-mangled
# file can never inject unknown keys into the app.
DEFAULTS = {
    "map": {
        "start_lat": 47.68,
        "start_lon": 11.57,
        "start_zoom": 13,        # with an offline map; without one the app
                                 # falls back to the world overview (z3)
        "min_zoom": 2,
        "max_zoom": 15,          # the offline pack tops out here
        "focus_zoom": 15,        # zoom the (o) focus button jumps to
        "follow": False,         # re-centre on every fix, not just the first
    },
    "layers": {
        "peaks": False,
        "peaks_big": False,
        "masts": False,
        "bathing": False,
        "groundwater": False,
        "gpx": [],               # names of GPX sources to show (see /state)
    },
    "gps": {
        "idle_interval": 60,     # seconds between fixes while not recording
        "rec_interval": 10,      # seconds between fixes while recording
        # Safety net while recording: rec_interval rides on Kivy's Clock, which
        # is dead while the CPU is suspended -- a screen-off ride silently loses
        # every point until something else wakes the device. This arms an
        # AllowWhileIdle alarm that fires through Doze and logs a point, so the
        # worst-case gap in a track is bounded. 0 disables it.
        # Android throttles these alarms to roughly one per 9 min per app, so
        # anything below ~540 is quietly stretched to that floor.
        "wake_interval": 600,    # seconds; hard upper bound on a track's gap
    },
    "record": {
        "autostart": False,      # start recording as soon as the app opens
    },
    "ui": {
        # Status- und Hoehenzeile. Schwarz direkt auf der Karte war ueber Wald
        # und Hillshade nicht lesbar -> auf einer halbtransparenten Platte.
        # font_size ist 'sp', wird also zusaetzlich mit der System-Schriftgroesse
        # skaliert (Poco: font_scale 1.4) -- darum die kleine Zahl. Aenderung
        # wirkt sofort, ohne Neustart.
        "font_size": 11,
        "bold": False,
        "panel_opacity": 0.78,   # 0 = keine Platte, nur Text
        "menu_font_size": 11,    # Eintraege im ≡-Layer-Menue
    },
    "control": {
        "http_enabled": True,
        "port": CONTROL_PORT,
    },
}


def _merge(base, incoming):
    """Recursively copy known keys from `incoming` over `base`, keeping the
    type of the default (a config file is user-editable, so "15" must not turn
    map.focus_zoom into a string that later breaks a comparison)."""
    for key, default in base.items():
        if key not in incoming:
            continue
        value = incoming[key]
        if isinstance(default, dict) and isinstance(value, dict):
            _merge(default, value)
        elif isinstance(default, bool):
            base[key] = value if isinstance(value, bool) else \
                str(value).strip().lower() in ("1", "true", "yes", "on")
        elif isinstance(default, int) and not isinstance(default, bool):
            try:
                base[key] = int(value)
            except (TypeError, ValueError):
                pass
        elif isinstance(default, float):
            try:
                base[key] = float(value)
            except (TypeError, ValueError):
                pass
        elif isinstance(default, list):
            if isinstance(value, list):
                base[key] = value
        else:
            base[key] = value
    return base


class Config:
    """The config file, plus the mtime bookkeeping that makes external edits
    take effect without a restart."""

    def __init__(self, folder):
        self.path = os.path.join(folder, CONFIG_NAME)
        self.data = json.loads(json.dumps(DEFAULTS))   # deep copy
        self._mtime = 0.0

    # -- disk -------------------------------------------------------------
    def load(self):
        """Read the file; write it out first if it does not exist yet, so the
        very first start already leaves a complete, documented file behind."""
        try:
            with open(self.path, encoding="utf-8") as fh:
                _merge(self.data, json.load(fh))
            self._mtime = os.path.getmtime(self.path)
        except FileNotFoundError:
            self.save()
        except Exception:
            # A broken file must not kill the app -- keep the defaults and
            # overwrite it with something valid.
            traceback.print_exc()
            self.save()
        return self

    def save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            os.replace(tmp, self.path)
            self._mtime = os.path.getmtime(self.path)
        except Exception:
            traceback.print_exc()

    def reload_if_changed(self):
        """True if the file on disk is newer than what we last wrote/read.
        Called from a Clock tick, so an `adb push` is picked up within seconds."""
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            return False
        if mtime <= self._mtime:
            return False
        self._mtime = mtime
        try:
            with open(self.path, encoding="utf-8") as fh:
                _merge(self.data, json.load(fh))
        except Exception:
            traceback.print_exc()
            return False
        return True

    # -- access -----------------------------------------------------------
    def get(self, dotted, default=None):
        node = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted, value):
        parts = dotted.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def update(self, incoming):
        """Accept both a nested dict and flat dotted keys
        ({"map": {"focus_zoom": 12}} == {"map.focus_zoom": 12}), because the
        dotted form is what is comfortable to type on a command line."""
        nested = {}
        for key, value in incoming.items():
            if "." in key:
                node = nested
                parts = key.split(".")
                for part in parts[:-1]:
                    node = node.setdefault(part, {})
                node[parts[-1]] = value
            else:
                nested[key] = value
        _merge(self.data, nested)
        self.save()


class _Handler(BaseHTTPRequestHandler):
    """GET /config, GET /state, POST /config, POST /action."""

    server_version = "OSMCycle"

    def _reply(self, code, payload):
        body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):                                  # noqa: N802 (stdlib API)
        srv = self.server.ctl
        try:
            if self.path.startswith("/config"):
                self._reply(200, srv.config.data)
            elif self.path.startswith("/state"):
                self._reply(200, srv.state_fn())
            else:
                self._reply(404, {"error": "use /config, /state or /action"})
        except Exception as exc:
            traceback.print_exc()
            self._reply(500, {"error": str(exc)})

    def do_POST(self):                                 # noqa: N802 (stdlib API)
        srv = self.server.ctl
        try:
            body = self._body()
            if self.path.startswith("/config"):
                srv.config.update(body)
                srv.apply_fn()                  # take effect without a restart
                self._reply(200, srv.config.data)
            elif self.path.startswith("/action"):
                result = srv.action_fn(body.get("action", ""), body)
                self._reply(200 if result.get("ok") else 400, result)
            else:
                self._reply(404, {"error": "use /config or /action"})
        except Exception as exc:
            traceback.print_exc()
            self._reply(500, {"error": str(exc)})

    def log_message(self, fmt, *args):
        pass                                    # keep logcat readable


class ControlServer(threading.Thread):
    """Serves the control API on 127.0.0.1. Daemon thread: it must never keep
    the app alive after the UI is gone."""

    daemon = True

    def __init__(self, config, state_fn, action_fn, apply_fn, port=CONTROL_PORT):
        super().__init__(name="osmcycle-control")
        self.config = config
        self.state_fn = state_fn
        self.action_fn = action_fn
        self.apply_fn = apply_fn
        self.port = port
        self.httpd = None

    def run(self):
        try:
            self.httpd = HTTPServer(("127.0.0.1", self.port), _Handler)
            self.httpd.ctl = self
            self.httpd.serve_forever(poll_interval=0.5)
        except Exception:
            traceback.print_exc()               # port taken -> app runs anyway

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
