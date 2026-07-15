"""OSMCycles eigene Punkt-Datenbank — nach dem Vorbild von Locus' waypoints.db.

Gleiches Layout wie Locus (`groups` = Ordner, `waypoints` = Punkte, Koordinaten
als **Dezimalgrad** REAL, 16-Byte-`uuid`), damit die Punktdaten EIN geteiltes
Format über beide Apps sind und die `scripts/locus_wp_*`-Tools auch hierauf
laufen. OSMCycle besitzt diese Datei (lesen UND schreiben) — Locus' eigene DB
darf dagegen nie von Hand geschrieben werden (siehe
docs/locus_offline_points.md).

Ein `groups`-Eintrag pro Layer (gipfel, wasserfaelle, badestellen, …), die
Punkte hängen über `waypoints.parent_id` daran.
"""
import os
import sqlite3
import time
import uuid as _uuid

DB_NAME = "osmcycle_points.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    _id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, icon TEXT,
    parent_id INTEGER DEFAULT -1, time_created INTEGER, uuid BLOB);
CREATE TABLE IF NOT EXISTS waypoints (
    _id INTEGER PRIMARY KEY AUTOINCREMENT, parent_id INTEGER, name TEXT,
    longitude REAL, latitude REAL, elevation REAL,
    time_created INTEGER, privacy TEXT DEFAULT 'PRIVATE', uuid BLOB);
CREATE INDEX IF NOT EXISTS wp_parent ON waypoints(parent_id);
"""


def _now():
    return int(time.time() * 1000)


def build(path, layers):
    """(Neu-)Aufbau der DB aus {gruppenname: [(lat, lon[, name[, ele]]), …]}.

    Schreibt in eine .tmp und ersetzt atomar, damit ein abgebrochener Build die
    bestehende DB nicht beschädigt. Namelose Punkte bekommen 'gruppe N' — sonst
    wären sie in Locus (bei Export/Import) nicht unterscheidbar."""
    tmp = path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    db = sqlite3.connect(tmp)
    try:
        db.executescript(SCHEMA)
        now = _now()
        for gname, points in layers.items():
            gid = db.execute(
                "INSERT INTO groups(name, time_created, uuid) VALUES(?,?,?)",
                (gname, now, _uuid.uuid4().bytes)).lastrowid
            rows = []
            for i, p in enumerate(points, 1):
                name = str(p[2]) if len(p) > 2 else "{} {}".format(gname, i)
                ele = float(p[3]) if len(p) > 3 else None
                rows.append((gid, name, float(p[1]), float(p[0]), ele, now,
                             _uuid.uuid4().bytes))
            db.executemany(
                "INSERT INTO waypoints(parent_id, name, longitude, latitude, "
                "elevation, time_created, uuid) VALUES(?,?,?,?,?,?,?)", rows)
        db.commit()
    finally:
        db.close()
    os.replace(tmp, path)
    return path


def read_group(path, gname):
    """Punkte einer Gruppe als [(lat, lon, name, elevation), …]."""
    db = sqlite3.connect(path)
    try:
        return db.execute(
            "SELECT w.latitude, w.longitude, w.name, w.elevation FROM waypoints w "
            "JOIN groups g ON w.parent_id = g._id WHERE g.name = ? "
            "ORDER BY w._id", (gname,)).fetchall()
    finally:
        db.close()


def counts(path):
    """{gruppenname: anzahl} — leeres dict, wenn die DB fehlt."""
    if not os.path.exists(path):
        return {}
    db = sqlite3.connect(path)
    try:
        return dict(db.execute(
            "SELECT g.name, count(w._id) FROM groups g "
            "LEFT JOIN waypoints w ON w.parent_id = g._id GROUP BY g._id"))
    finally:
        db.close()
