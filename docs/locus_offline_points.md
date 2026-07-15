# Offline-Punkte in Locus (Gipfel / Wasserfälle / Badestellen)

Stand: 2026-07-15. Ziel: OSMCycle-Overlays (Gipfelnamen, Wasserfälle, Badestellen)
sollen **offline** in Locus Map verfügbar sein — als **eine geteilte Punkt-Quelle**
für beide Apps, analog zur geteilten Kartendatei (`find_mbtiles()` / `LOCUS_MAPS`).

## Warum überhaupt

- Unsere `alpen_z15.mbtiles` sind **reine Raster-PNG-Kacheln** (CyclOSM via
  renderd/Mapnik, siehe `scripts/pack_mbtiles.py`: nur Tabellen `metadata` +
  `tiles`, `format=png`, **kein** UTFGrid). Locus kann daraus **keine** Objekte
  lesen — Raster ist nur ein Bild.
- Locus zeigt Gipfel beim Antippen zwar mit Namen/Höhe/Foto/Wikipedia — das kommt
  aber aus Locus' **Online**-POI-Lookup (empirisch bestätigt: offline nur noch
  gecacht). **In den Bergen ohne Netz kennt Locus die Gipfel nicht.**
- Der frühere „Doppel-Name" (`Geierstein` + `Geierstein (1491 m)`) war ein reines
  **Online-Artefakt**: Locus' Online-POI **plus** unser gesendeter Pack.

Fazit: für echten Offline-Betrieb müssen die Punkte in Locus' **eigene**
Datenbank.

## `waypoints.db` — Format (reverse-engineered)

- Pfad: `/sdcard/Android/media/menion.android.locus/data/database/waypoints.db`
- **Standard SQLite 3, unverschlüsselt** (`user_version 14`, geschrieben mit
  SQLite 3.32).
- Cache-Marker-Dateien im selben Ordner: `.count_dbWaypoints`,
  `.mVisibleItems_dbWaypoints` (Locus' zwischengespeicherte Zähler/Sichtbarkeit).

Tabellen:

```sql
-- Punkt-Ordner (hierauf zeigt waypoints.parent_id)
CREATE TABLE groups (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NON NULL,
  mode INTEGER DEFAULT 0, icon TEXT NON NULL, extra_style BYTE,
  parent_id INTEGER DEFAULT -1, labels_mode INTEGER DEFAULT -1,
  time_created INTEGER, time_updated INTEGER, uuid BYTE);

-- die Punkte selbst
CREATE TABLE waypoints (_id INTEGER PRIMARY KEY AUTOINCREMENT, parent_id INTEGER,
  track_id INTEGER, rw_mode TEXT, name TEXT, name_testing TEXT,
  extra_data BYTE, extra_icon TEXT, extra_style BYTE,
  extra_gc_simple BYTE, extra_gc BYTE,
  longitude INTEGER, latitude INTEGER,           -- Integer-Encoding: SIEHE TODO
  time_created INTEGER, time INTEGER,
  elevation FLOAT, speed FLOAT, bearing FLOAT, accuracy FLOAT,
  privacy TEXT, uuid BYTE);

CREATE TABLE categories (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT,
  icon TEXT, extra_style BYTE, group_id INTEGER, labels_mode INTEGER);
CREATE TABLE folder_group (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT);
CREATE TABLE items_deleted (_id INTEGER PRIMARY KEY AUTOINCREMENT, type INTEGER,
  time_deleted INTEGER, uuid BYTE);
```

## ⚠️ NIEMALS direkt in `waypoints.db` schreiben

Empirisch bestätigt (2026-07-15): eigene `INSERT`s (selbst mit
`name`/`longitude`/`latitude`/`elevation`/`parent_id`) führen dazu, dass Locus
beim Start **„Hoppla! Problem mit Daten (Punkte/Tracks)"** meldet und ein
Backup wiederherstellen will. Locus verwirft die DB, weil Pflichtfelder fehlen
(`uuid`, serialisiertes `extra_style`) bzw. die Cache-Marker nicht passen.

→ **Schreiben ausschließlich über die Locus-API.** `waypoints.db` **lesen** ist
dagegen unbedenklich (reines `SELECT`).

## Schreib-Weg (offizielle API) — implementiert

`locus-api-android:0.10.1`, aufgerufen per pyjnius in `app/locusbridge.py`:

```
ActionFiles.importFileLocus(Context, Uri fileUri, String mime, LocusVersion, boolean callImport)
```

Intern (aus dem Bytecode):
```
Intent(ACTION_VIEW).setPackage("menion.android.locus")
    .setDataAndType(fileUri, mime)
    .addFlags(FLAG_GRANT_READ_URI_PERMISSION)
    .putExtra("INTENT_EXTRA_CALL_IMPORT", callImport);
context.startActivity(intent);
```

Details/Fallen:
- Braucht eine **Uri**. `file://` löst ab targetSdk 24 `FileUriExposedException`
  aus. Umgehung in `import_layer()`: StrictMode-`VmPolicy` kurz lockern und die
  GPX in Locus' **eigenen** Media-Ordner (`LOCUS_SHARE`) schreiben — den liest
  Locus direkt; kein FileProvider nötig.
- `callImport=true` → Locus führt den Import aus (ggf. mit UI-Dialog).
- **Persistent** (überlebt Neustart, offline). Gegensatz: `sendPacksFileSilent`
  (bisheriges `send_layer`) = **temporäres** Overlay, weg nach Locus-Neustart.

Neue Funktion `locusbridge.import_layer(name, points)` und Control-Action
`locus_import` (`POST /action {"action":"locus_import","layer":"gipfel"}`, Port
8765) sind implementiert.

## Lese-Weg (OSMCycle nutzt dieselbe DB)

OSMCycle ist Python **mit `sqlite3`** → kann `waypoints.db` direkt lesen
(`SELECT name, longitude, latitude, elevation FROM waypoints WHERE parent_id=…`).
Damit wird die von Locus geschriebene DB zur **geteilten** Punkt-Quelle für beide
Apps. Schreiben bleibt Locus vorbehalten.

## Umfang

Nur **Wasserfälle, Gipfel, Badestellen** (klein genug). **Nicht** Sendemasten
(~14 000) und **nicht** Grundwasser — die würden die Punkt-DB/Karte ausbremsen
(genau darum nutzt der Bestand für Masten temporäre Packs statt der DB).

## Wichtige Erkenntnisse aus dem ersten echten Import (2026-07-15)

- **Koordinaten-Encoding: KEIN E6/E7.** Locus speichert `longitude`/`latitude`
  als **Dezimalgrad direkt** (z. B. `9.16346`, `47.76863`) — die Spalten sind
  zwar `INTEGER` deklariert, aber SQLite ist dynamisch typisiert und Locus legt
  REAL ab. → OSMCycle liest sie einfach als Float, keine Umrechnung.
- **Locus merged beim Import gleichnamige Punkte.** Erster Import der 1711
  Wasserfälle: `sqlite_sequence` = 1711 eingefügt, aber `items_deleted` = 1710,
  `waypoints` = **1** übrig. Ursache: die namelosen Layer (`wasserfaelle`,
  `badestellen`) sind reine Koordinatenlisten (`PointsLayer.points = [(lat,lon)]`)
  → alle bekamen denselben Namen → Locus fasst sie zu einem zusammen. **Fix:**
  jedem namelosen Punkt einen eindeutigen Namen geben (`"{name} {i}"`); Gipfel
  haben ohnehin echte Namen. (umgesetzt in `import_layer`.)

## Waypoint-Anatomie (forensisch, echte Locus-Zeilen)

Zwei von Locus **selbst** geschriebene Zeilen untersucht (2026-07-15): eine per
`importFileLocus`, eine über „Punkt speichern" in der Locus-UI.

Pflicht-/Kernfelder eines gültigen Punkts:

| Spalte | Beispiel | Anmerkung |
|---|---|---|
| `name` | `Geierstein (1491 m)` / `2026-07-15 19:15:18` | UI-Punkte auto-benannt mit Zeitstempel |
| `name_testing` | = `name` | such-normalisierte Kopie, **von Locus gefüllt** |
| `latitude` / `longitude` | `47.67849956101252` / `11.630453804090534` | **Dezimalgrad, REAL** (Spalte ist `INTEGER`, aber SQLite dynamisch typisiert) — kein E6/E7 |
| `time_created` / `time` | `1784135754886` | Epoch-**Millisekunden** |
| `privacy` | `PRIVATE` | String, Pflicht |
| `uuid` | `BYTE[16] = dc4a6609…0b7b` | 16-Byte-Binär-UUID, **Pflicht** |
| `parent_id` | `1` | Locus' **Default-Ordner** (dafür gibt es KEINE `groups`-Zeile; benannte Ordner bekommen erst beim Anlegen eine) |

Optionale/leere Felder:

- `extra_icon`, `extra_style`: bei Import **und** manuellem Punkt `NULL` →
  **Symbol/Farbe kommt vom Ordner** (`groups.icon`/`groups.extra_style`), nicht
  pro Punkt (außer man wählt explizit ein Icon).
- `elevation`: nur gesetzt, wenn die GPX `<ele>` hatte (Gipfel ja, Wasserfälle
  nein).
- `track_id`, `rw_mode`, `speed`, `bearing`, `accuracy`, `extra_gc*`: `NULL`.

`extra_data` — Beschreibung/Attribute als **serialisierter Blob**
(Locus `GeoDataExtra`), length-prefixed. Beispiel (Beschreibung
„Test add and save"):

```
01 0000000000000000  1d000000      01000000    1e000000  11   54657374…7361766)
version(=1, int64?)  size(=29)     count(=1)   key(=30)  len  UTF-8 "Test add and save"
```

**Konsequenz fürs Direkt-Schreiben:** genau `uuid` + `name_testing` + `privacy`
(und passende Cache-Marker) fehlten → Locus meldete „Problem mit Daten" und
verwarf die ganze DB. Darum: **schreiben nur über die API**, lesen (`SELECT
name, latitude, longitude, elevation, parent_id`) ist unbedenklich.

## Noch fehlende Schritte (TODO)
2. **Lese-Integration in OSMCycle:** `waypoints.db` per `sqlite3` einlesen,
   Koordinaten dekodieren, in die Overlays einspeisen.
3. **Einmaliger Auto-Import beim ersten Start:** in `main.py` per Config-Flag
   (z. B. `locus.imported`) die 3 Layer einmalig via `import_layer` nach Locus
   schieben; danach nicht erneut.
4. **Ordner + Icons pro Layer:** jeder Import landet in einem eigenen
   Locus-Ordner (in Locus einzeln an-/abschaltbar); Symbol je Layer über
   `extra_icon` setzen. Aktuell: 3 Importe = 3 Ordner.
5. **UX von `callImport=true` prüfen:** ob/welcher Dialog je Import erscheint
   (3 Layer → 3 Importe). Ggf. auf einen kombinierten Import eindampfen.
6. **On-Device verifizieren:** `locus_import` auslösen → Punkte da → Locus
   **neu starten** → immer noch da → **offline** (Flugmodus) → immer noch da.
7. **buildozer:** prüfen, ob der StrictMode-Trick reicht oder doch ein
   FileProvider im Manifest nötig ist.
8. **Release 2.3:** bauen, auf Poco (`88825b15`) + A57 (`192.168.5.241:5555`)
   deployen, taggen. (Signatur-Hinweis: Geräte hängen am
   `~/.android/debug.keystore` = `b4f9c7b4…`; Fremd-Builds `17186fd0…` verlangen
   Uninstall+Install.)

## Bereits umgesetzt (uncommittet, Stand 2026-07-15)

- `locusbridge.import_layer()` + `ActionFiles` in `_CLASSES`.
- `locus_import` Control-Action in `main.py`.
- (aus derselben Sitzung, unabhängig:) `send_layer` **überschreibt statt merged**
  (verhindert gestapelte Duplikate); kleiner „Gipfelnamen"-Layer entfernt (nur
  noch der große); `download_map`-Action; Positionspfeil **doppelt so groß**.
