# Driving Locus Map without its UI

Notes from wiring OSMCycle's offline map and layers into **Locus Map 4.35.0**
(HiBreak, Android 14). The short version: there is **no config file**, but there
is a real **intent API**, and the useful half of it works straight from `adb`.

## There is no config file

Locus keeps exactly two files in its own folder, and neither is a settings file:

```
/sdcard/Android/data/menion.android.locus/files/Locus/info
/sdcard/Android/data/menion.android.locus/files/Locus/config_projections.cfg
```

`info` is pure status (app version, start time, user id). `config_projections.cfg`
does only what its own header says — EPSG map projections.

Everything that actually configures Locus — the active map, layers, folders —
lives in Android's SharedPreferences:

```
/data/data/menion.android.locus/shared_prefs/    ->  Permission denied
```

Without root that is out of reach. **Selecting a map cannot be scripted**; it is
Karten-Manager → OFFLINE → tap the folder → tap the map, by hand. Everything
below is what you *can* do without touching the screen.

## The intent API

Locus exports `com.asamm.locus.api.android.events.ApiEventsReceiver`. Read the
actions it accepts straight off the device:

```bash
adb shell dumpsys package menion.android.locus \
  | grep -oE "locus\.api\.android\.[A-Z_]+" | sort -u
```

| Action | What it does |
| --- | --- |
| `ACTION_TRACK_RECORD_START` | start recording |
| `ACTION_TRACK_RECORD_PAUSE` | pause |
| `ACTION_TRACK_RECORD_STOP` | stop (and save) |
| `ACTION_TRACK_RECORD_ADD_WPT` | drop a waypoint into the running recording |
| `ACTION_DISPLAY_DATA` | show points/tracks on the map |
| `ACTION_DISPLAY_DATA_SILENTLY` | …without bringing Locus to the front, and **without writing them to its database** |
| `ACTION_REMOVE_DATA_SILENTLY` | take them off again |
| `ACTION_PERIODIC_UPDATE` | Locus broadcasts position/state back at you |
| `ACTION_NAVIGATION_START`, `ACTION_GUIDING_START` | start navigation / guidance |
| `ACTION_ADD_NEW_WMS_MAP` | register a WMS source |

### Recording — verified working

The payload-free actions go through plain `am broadcast`. This starts a
recording; the green play button turns into a red dot:

```bash
adb shell am broadcast -a locus.api.android.ACTION_TRACK_RECORD_START \
  -p menion.android.locus            # -> Broadcast completed: result=0
adb shell am broadcast -a locus.api.android.ACTION_TRACK_RECORD_STOP \
  -p menion.android.locus
```

### Importing GPX — verified working

A plain `VIEW` intent opens Locus's import dialog for a GPX file:

```bash
adb shell am start -a android.intent.action.VIEW \
  -d "file:///sdcard/Android/data/menion.android.locus/files/Locus/mapItems/gipfel.gpx" \
  -t "application/gpx+xml" menion.android.locus
```

The dialog itself still needs a tap on **IMPORTIEREN** (scriptable via
`uiautomator dump` + `input tap`, but brittle). Two things to know before you use
it in anger:

* The target-folder dropdown defaults to **Stammverzeichnis**, so everything
  lands in the root in one undifferentiated heap. Pick a folder per layer if you
  want to switch them on and off as groups — which is what OSMCycle's ≡ Layer
  menu does.
* Import writes **every waypoint into Locus's point database**. Fine for the
  three trails and the summits; a bad idea for the 13 980 masts, which OSMCycle
  draws viewport-culled straight from JSON.

### `DISPLAY_DATA_SILENTLY` — the one worth building on

This is the proper answer to the masts: it renders points and tracks as an
overlay **without** touching Locus's database, which is exactly what OSMCycle's
own layers do.

It cannot be triggered from `adb`, though: the data goes in as serialized
`locus-api` objects in an intent extra, and `am` has no way to pass a byte array.
It needs real code — either a small helper app built against
[`locus-api-android`](https://github.com/asamm/locus-api), or the serialisation
built into OSMCycle so it can hand its own layers to Locus. That would be the
elegant split: our data, their renderer.

## Also worth knowing

* Locus reads `.mbtiles` natively (no conversion, unlike OsmAnd) — but **only
  from its own folders**. It does not declare `MANAGE_EXTERNAL_STORAGE`, has no
  setting for an external map directory, and its *Externe Links* feature, which
  used to reference maps elsewhere, **has been discontinued** (the dialog says so
  itself). See the Locus section in the README for how OSMCycle and Locus end up
  sharing a single 6.9 GB file anyway.
* `uiautomator dump` returns an empty tree on Locus's map canvas (it is one big
  drawing surface). It only yields anything on dialogs and panels — and it goes
  stale, so re-dump after every tap rather than trusting the last one.
