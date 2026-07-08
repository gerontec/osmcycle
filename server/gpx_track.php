<?php
// gpx_track.php – Collector für OsmAnds "Online tracking" (Trip recording).
// Jeder Punkt, den OsmAnd per HTTP-GET schickt, wird an einen Live-Puffer pro
// Nutzer angehängt; wird eine Session still (Lücke > $GAP), landet sie als
// normale  YYYY-MM-DD_HH-MM_Wochentag.gpx  in gpx_uploads/ und taucht damit in
// gpx_report.php + rss_gpx.php auf. Kein Token (wie gpx_upload.php).
//
// OsmAnd-URL (Einstellungen → Trip recording → Online tracking):
//   https://heissa.de/web1/gpx_track.php?id=DEINNAME&lat={0}&lon={1}&time={2}&alt={4}
// Cron schließt stille Sessions:  ...gpx_track.php?finalize=1
header('Content-Type: text/plain; charset=utf-8');

$GAP  = 900;                          // 15 min ohne Punkt => Session beenden
$LIVE = __DIR__ . '/gpx_live';
$OUT  = __DIR__ . '/gpx_uploads';

if (!is_dir($LIVE)) @mkdir($LIVE, 0755, true);

// Cron-/Wartungsaufruf: nur stille Sessions abschließen
if (isset($_GET['finalize'])) { finalize_stale($LIVE, $OUT, $GAP); exit('finalized'); }

$lat = $_GET['lat'] ?? null;
$lon = $_GET['lon'] ?? null;
if (!is_numeric($lat) || !is_numeric($lon)) {
    finalize_stale($LIVE, $OUT, $GAP);          // trotzdem aufräumen
    http_response_code(400); exit('need numeric lat & lon');
}

$id  = preg_replace('/[^A-Za-z0-9._-]/', '_', substr((string)($_GET['id'] ?? 'anon'), 0, 40));
$alt = is_numeric($_GET['alt'] ?? '') ? (float)$_GET['alt'] : null;

// Zeit: leer=jetzt, numerisch (s oder ms) oder ISO-String
$t = (string)($_GET['time'] ?? '');
if ($t === '')            $ts = time();
elseif (is_numeric($t)) { $ts = (float)$t; if ($ts > 1e11) $ts /= 1000; $ts = (int)$ts; }
else                      $ts = strtotime($t) ?: time();

$live = "$LIVE/$id.ndjson";

// Lücke => vorherige Session dieses Nutzers zuerst abschließen
if (is_file($live) && (time() - filemtime($live)) > $GAP) finalize($live, $OUT);

file_put_contents($live,
    json_encode(['lat'=>(float)$lat,'lon'=>(float)$lon,'ts'=>$ts,'alt'=>$alt])."\n",
    FILE_APPEND | LOCK_EX);

finalize_stale($LIVE, $OUT, $GAP);              // andere stille Sessions mitnehmen
echo 'OK';

function finalize_stale($LIVE, $OUT, $GAP) {
    foreach (glob("$LIVE/*.ndjson") as $f)
        if (time() - filemtime($f) > $GAP) finalize($f, $OUT);
}

function finalize($live, $OUT) {
    $lines = @file($live, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    @unlink($live);
    if (!$lines) return;
    $pts = [];
    foreach ($lines as $l) { $p = json_decode($l, true); if ($p) $pts[] = $p; }
    if (count($pts) < 2) return;                // zu kurz -> verwerfen
    usort($pts, fn($a, $b) => $a['ts'] <=> $b['ts']);

    $start = $pts[0]['ts'];
    $name  = date('Y-m-d_H-i', $start) . '_' . date('D', $start) . '.gpx';
    if (!is_dir($OUT)) @mkdir($OUT, 0755, true);

    $gpx  = '<?xml version="1.0" encoding="UTF-8"?>' . "\n";
    $gpx .= '<gpx version="1.1" creator="OsmAnd-OnlineTracking" '
          . 'xmlns="http://www.topografix.com/GPX/1/1">' . "\n";
    $gpx .= '  <trk><name>OsmAnd ' . date('Y-m-d_H-i', $start) . '</name><trkseg>' . "\n";
    foreach ($pts as $p) {
        $gpx .= sprintf('    <trkpt lat="%.6f" lon="%.6f">', $p['lat'], $p['lon']);
        if ($p['alt'] !== null) $gpx .= '<ele>' . sprintf('%.1f', $p['alt']) . '</ele>';
        $gpx .= '<time>' . gmdate('Y-m-d\TH:i:s\Z', $p['ts']) . '</time></trkpt>' . "\n";
    }
    $gpx .= '  </trkseg></trk>' . "\n</gpx>\n";

    $dest = "$OUT/$name";
    file_put_contents($dest, $gpx, LOCK_EX);
    @chmod($dest, 0644);                         // world-readable für den gh-Cron
}
