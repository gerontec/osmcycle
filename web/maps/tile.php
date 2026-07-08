<?php
// Minimal CyclOSM tile server: serves tiles from the OsmAnd BigPlanet sqlitedb
// that already lives next to this file. URL: tile.php?z={z}&x={x}&y={y}
$z = isset($_GET['z']) ? (int)$_GET['z'] : -1;
$x = isset($_GET['x']) ? (int)$_GET['x'] : -1;
$y = isset($_GET['y']) ? (int)$_GET['y'] : -1;
if ($z < 0 || $x < 0 || $y < 0) { http_response_code(400); exit('bad request'); }

$file = __DIR__ . '/CyclOSM_Alpen.sqlitedb';
if (!is_readable($file)) { http_response_code(500); exit('no db'); }

try {
    $db = new SQLite3($file, SQLITE3_OPEN_READONLY);
} catch (Exception $e) { http_response_code(500); exit('db open'); }

// BigPlanet numbering: stored z = 17 - zoom, x/y are XYZ (Google)
$st = $db->prepare('SELECT image FROM tiles WHERE x=:x AND y=:y AND z=:z LIMIT 1');
$st->bindValue(':x', $x, SQLITE3_INTEGER);
$st->bindValue(':y', $y, SQLITE3_INTEGER);
$st->bindValue(':z', 17 - $z, SQLITE3_INTEGER);
$row = $st->execute()->fetchArray(SQLITE3_ASSOC);

if ($row && $row['image'] !== null) {
    header('Content-Type: image/png');
    header('Cache-Control: public, max-age=604800');
    header('Access-Control-Allow-Origin: *');
    echo $row['image'];
} else {
    http_response_code(404);
}
