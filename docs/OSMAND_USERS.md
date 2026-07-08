# Eigene OsmAnd-Touren im OSMCycle-Report auswerten

Du nutzt das normale **OsmAnd** (nicht die OSMCycle-App) und willst deine
aufgezeichneten Touren im öffentlichen Report sehen?
→ **https://heissa.de/web1/gpx_report.php** (+ RSS-Feed `rss_gpx.php`)

Es gibt **keinen** installierbaren OsmAnd-Upload-Plugin mit eigener Server-Logik —
das lässt OsmAnd nicht zu. Aber diese drei Wege funktionieren mit dem
Standard-OsmAnd, vom bequemsten zum manuellsten:

## A) Automatisch: OsmAnd „Online tracking" (empfohlen)
OsmAnd schickt während der Aufnahme jeden GPS-Punkt an eine frei wählbare URL.
Der Server baut daraus automatisch eine GPX und filtert sie in den Report.

1. OsmAnd → **Plugins → Trip recording** aktivieren.
2. **Einstellungen → Trip recording → Online tracking** öffnen.
3. Als **Web-Adresse** eintragen (ersetze `DEINNAME` durch dein Kürzel):
   ```
   https://heissa.de/web1/gpx_track.php?id=DEINNAME&lat={0}&lon={1}&time={2}&alt={4}
   ```
4. Intervall z. B. 5–10 s. Fertig — einfach aufnehmen und fahren.

Sobald du 15 min lang keinen Punkt mehr sendest (Tour vorbei), wird die Session
serverseitig als `YYYY-MM-DD_HH-MM_Wochentag.gpx` abgeschlossen und erscheint
nach dem nächsten stündlichen Lauf im Report. Kein Export, kein Teilen nötig.

## B) Manuell: aufgezeichnete GPX hochladen (kein Setup)
Wenn du lieber die fertige OsmAnd-GPX schickst (mit exakter Höhe):

- **Upload-Seite im Browser:** https://heissa.de/web1/gpx_share.php
  → Datei(en) ablegen/auswählen, optional Name eintragen, fertig.
- Track holst du aus OsmAnd via **Meine Orte → Tracks → Track → Teilen/Export → GPX**.
- Der optionale Name erscheint im Report/Feed als „· von <Name>".

OsmAnd benennt seine Tracks bereits als `2026-05-09_09-06_Sat.gpx` — genau das
Format, das der Report fürs Datum parst. Nichts umbenennen.

## Unsere Karte in OsmAnd (scharfe CyclOSM-Kacheln)
**Plugin-Bündel** `osmand/cyclosm_plugin.json` in OsmAnd importieren
(*Einstellungen → OsmAnd konfigurieren/Import*) — bringt die Kartenquelle
**CyclOSM (OSMCycle)** mit.

Oder von Hand hinzufügen (funktioniert garantiert):
- OsmAnd → **Karte konfigurieren → Kartenquelle → + / Online-Karten**
- Name: `CyclOSM (OSMCycle)`
- URL: `https://tmind.de/maps/tile.php?z={0}&x={1}&y={2}`
- Min-Zoom **6**, Max-Zoom **14**, Kachelgröße 256, `.png`

> Hinweis: Der Report zeigt nur echte Fahrten — Tracks unter **1 km / 2 hm**
> werden herausgefiltert.

---
### Serverseite (für Betreiber)
`server/gpx_track.php` sammelt die Online-Tracking-Punkte pro `id` in
`gpx_live/<id>.ndjson`; bei einer Lücke > 15 min (oder per Cron
`gpx_track.php?finalize=1`, alle 20 min) wird die Session nach `gpx_uploads/`
geschrieben, das `gpx_report.py` scannt. Läuft als `www-data`, kein Token.
