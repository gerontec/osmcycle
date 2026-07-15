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

__all__ = ["available", "send_layer", "remove_layer", "import_layer", "LOCUS_PKG"]

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
    "ActionFiles": "locus.api.android.ActionFiles",
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
        # Overwrite, never merge: sendPacksFileSilent ADDS the pack's points to
        # whatever Locus already shows under this name, so a second send stacks a
        # duplicate of every peak (tap a flag -> the name twice). Drop the old
        # pack first, then send exactly one.
        try:
            _J["ActionDisplayPoints"].INSTANCE.removePackFromLocus(_ctx(), name)
        except Exception:
            pass
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


def import_layer(name, points):
    """PERSISTENTLY store `points` in Locus's own point database, so they survive
    restarts and are there fully offline — unlike send_layer's temporary overlay.

    We never write waypoints.db ourselves: hand-crafted rows miss Locus's required
    fields (uuid, style) and Locus then rejects the whole DB ("Problem mit Daten").
    Instead we hand Locus a GPX and let its OWN importer write the DB, via the
    official ActionFiles.importFileLocus. osmcycle may READ that DB afterwards
    (plain SELECT is safe); only writing has to go through Locus.

    points: (lat, lon) or (lat, lon, label), as PeaksLayer/PointsLayer hold them."""
    import html
    lv = _version()
    if lv is None:
        return False
    # Locus names the import target folder after the GPX <metadata><name> (no
    # headless folder API exists in locus-api 0.10.1), so each layer lands in its
    # own toggleable Locus folder instead of all in the root.
    folder = {"gipfel": "Gipfelnamen", "wasserfaelle": "Wasserfälle",
              "badestellen": "Badestellen", "grundwasser": "Grundwasser",
              "masten": "Sendemasten"}.get(name, name)
    try:
        os.makedirs(LOCUS_SHARE, exist_ok=True)
        path = os.path.join(LOCUS_SHARE, "{}_import.gpx".format(name))
        with open(path, "w", encoding="utf-8") as f:
            f.write("<?xml version='1.0' encoding='UTF-8'?>\n"
                    "<gpx version='1.1' creator='osmcycle' "
                    "xmlns='http://www.topografix.com/GPX/1/1'>\n")
            f.write("  <metadata><name>{}</name></metadata>\n"
                    .format(html.escape(folder)))
            for i, p in enumerate(points, 1):
                # Peaks carry a real name; the nameless layers (waterfalls /
                # bathing are bare coord lists) get a per-point number, else Locus
                # MERGES all identical-named points into one on import (1711 in ->
                # 1710 to items_deleted, 1 left). The number keeps them distinct.
                label = html.escape(str(p[2]) if len(p) > 2
                                    else "{} {}".format(name, i))
                f.write("  <wpt lat='{:.6f}' lon='{:.6f}'><name>{}</name>"
                        "</wpt>\n".format(float(p[0]), float(p[1]), label))
            f.write("</gpx>\n")
        # importFileLocus builds an ACTION_VIEW intent and startActivity()s it; a
        # file:// data Uri trips StrictMode's file-uri check (targetSdk>=24). The
        # GPX sits in Locus's OWN media folder (Locus reads it directly), so we
        # just relax that one policy rather than wiring up a FileProvider.
        VmBuilder = autoclass("android.os.StrictMode$VmPolicy$Builder")
        autoclass("android.os.StrictMode").setVmPolicy(VmBuilder().build())
        uri = _J["Uri"].fromFile(_J["File"](path))
        return bool(_J["ActionFiles"].INSTANCE.importFileLocus(
            _ctx(), uri, "application/gpx+xml", lv, True))
    except Exception as e:
        print("[locus] import '{}' failed: {!r}".format(name, e))
        return False
