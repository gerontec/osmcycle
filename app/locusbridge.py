"""Show OSMCycle's overlays in Locus Map — drawn, not imported.

Locus's GPX import writes every waypoint into its point database and keeps it
there. For the three trails that is fine; for the 13 980 masts it is not, and it
is not what our own layers do either — those are drawn from JSON and culled to
the viewport, owning nothing.

The Locus API has the matching call: `sendPacksFileSilent` puts a pack on the map
as a *temporary* overlay, and `removePackFromLocus` takes it off again. Nothing
is stored, so switching a layer on and off costs Locus nothing — exactly the deal
our ≡ Layer menu offers.

Two details decide whether this works at all:

* **It has to go over a file.** The sibling call `sendPackSilent` puts the pack
  in the intent, and an intent crosses Binder, which gives up around 1 MB. The
  masts are far past that. `sendPacksFileSilent` writes the pack to disk and
  passes only the path.
* **Locus has to be able to read that path.** With `fileUri = null` the library
  hands over a bare absolute path (`INTENT_EXTRA_POINTS_FILE_PATH`), so no
  FileProvider is involved and none of it is granted. We therefore write into
  Locus's OWN `Android/media` folder — the one place both apps can reach (see
  find_mbtiles() in main.py, which shares the 6.9 GB map through it).

`ActionDisplayPoints` and `LocusUtils` are Kotlin `object`s without `@JvmStatic`,
so on the JVM their methods live on the `INSTANCE` field, not on the class. And
Kotlin's default arguments produce no overloads without `@JvmOverloads`, so every
parameter has to be passed explicitly — `sendPacksFileSilent` really does want
its `fileUri` and `centerOnData`.
"""
import os

try:
    from jnius import autoclass  # type: ignore
    _HAVE_JNIUS = True
except Exception:
    _HAVE_JNIUS = False

__all__ = ["available", "send_layer", "remove_layer", "LOCUS_PKG"]

LOCUS_PKG = "menion.android.locus"
# Not app-private: Locus reads the pack file straight off this path.
LOCUS_SHARE = "/sdcard/Android/media/{}/osmcycle".format(LOCUS_PKG)


# Resolved once, on the main thread, by preload(). This is not premature caching:
# autoclass() ends in a JNI FindClass, and on a thread the JVM only attached later
# — our HTTP thread — that runs against the SYSTEM class loader, which knows
# nothing of the APK ("Didn't find class ... DexPathList[[directory "."]]"). Class
# objects resolved on the main thread stay usable from any thread, so we look them
# up once where it works and hand the references around.
_J = {}

# Not just what we call — everything the SIGNATURES touch. pyjnius resolves a
# method's parameter and return types lazily, at call time, on the calling thread;
# LocusVersion (what getActiveVersion hands back) blew up exactly that way even
# though we never name it ourselves.
_CLASSES = {
    "LocusUtils": "locus.api.android.utils.LocusUtils",
    "ActionDisplayPoints": "locus.api.android.ActionDisplayPoints",
    "PackPoints": "locus.api.android.objects.PackPoints",
    "LocusVersion": "locus.api.android.objects.LocusVersion",
    "Point": "locus.api.objects.geoData.Point",
    "Location": "locus.api.objects.extra.Location",
    "ArrayList": "java.util.ArrayList",
    "File": "java.io.File",
    "Uri": "android.net.Uri",
    "Context": "android.content.Context",
    "PythonActivity": "org.kivy.android.PythonActivity",
}


def preload():
    """Call once from the Kivy main thread (see _J). Safe to call repeatedly."""
    if not _HAVE_JNIUS or _J:
        return bool(_J)
    try:
        for key, path in _CLASSES.items():
            _J[key] = autoclass(path)
        return True
    except Exception as e:
        _J.clear()
        print("[locus] preload failed: {!r}".format(e))
        return False


def _ctx():
    return _J["PythonActivity"].mActivity


def _version():
    """The running Locus, or None when it is not installed."""
    if not _J:
        return None
    try:
        # The Int overload, to avoid dragging the VersionCode enum through JNI.
        return _J["LocusUtils"].INSTANCE.getActiveVersion(_ctx(), 0)
    except Exception as e:
        print("[locus] no version: {!r}".format(e))
        return None


def available():
    return preload() and _version() is not None


def send_layer(name, points, center=False):
    """Draw `points` in Locus as the temporary pack `name`.

    points: (lat, lon) or (lat, lon, label) — PointsLayer and PeaksLayer as they
    already are, no second data source."""
    lv = _version()
    if lv is None:
        return False
    try:
        pack = _J["PackPoints"](name)
        Point, Location = _J["Point"], _J["Location"]
        for p in points:
            lat, lon = float(p[0]), float(p[1])
            label = str(p[2]) if len(p) > 2 else name
            pack.addPoint(Point(label, Location(lat, lon)))

        packs = _J["ArrayList"]()
        packs.add(pack)

        os.makedirs(LOCUS_SHARE, exist_ok=True)
        f = _J["File"](os.path.join(LOCUS_SHARE, "{}.locus".format(name)))
        return bool(_J["ActionDisplayPoints"].INSTANCE.sendPacksFileSilent(
            _ctx(), lv, packs, f, None, bool(center)))
    except Exception as e:
        print("[locus] send '{}' failed: {!r}".format(name, e))
        return False


def remove_layer(name):
    """Take the pack off Locus's map again. Only ever touches temporary packs."""
    if _version() is None:
        return False
    try:
        _J["ActionDisplayPoints"].INSTANCE.removePackFromLocus(_ctx(), name)
        return True
    except Exception as e:
        print("[locus] remove '{}' failed: {!r}".format(name, e))
        return False
