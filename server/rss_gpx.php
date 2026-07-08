<?php
// rss_gpx.php – RSS-Feed der aufgezeichneten GPX-Touren (SEO/Crawler).
// Datenquelle: gpx_report.json (Sidecar, stündlich von gpx_report.py erzeugt,
// gleiche Quelle wie gpx_report.php). Kein DB-Zugriff nötig.
header('Content-Type: application/rss+xml; charset=UTF-8');
header('Cache-Control: public, max-age=3600');

$base = 'https://web1.heissa.de/web1';
$JSON = __DIR__ . '/gpx_report.json';

function x($s){ return htmlspecialchars($s ?? '', ENT_XML1|ENT_QUOTES, 'UTF-8'); }

$tracks = [];
if (is_readable($JSON)) {
    $tracks = json_decode(file_get_contents($JSON), true) ?: [];
}
// neueste zuerst
usort($tracks, function($a, $b){ return strcmp($b['sort_key'] ?? '', $a['sort_key'] ?? ''); });
$tracks = array_slice($tracks, 0, 50);          // Feed auf 50 Einträge begrenzen

$items = ''; $latest = '2000-01-01';
foreach ($tracks as $t) {
    $sk = $t['sort_key'] ?? '';                  // YYYY-MM-DD
    $ts = preg_match('/^\d{4}-\d{2}-\d{2}$/', $sk) ? strtotime($sk) : time();
    $day = date('Y-m-d', $ts);
    if ($day > $latest) $latest = $day;

    $place = $t['place'] ?? 'Tour';
    $dist  = isset($t['dist_km']) ? number_format($t['dist_km'], 1, ',', '.') . ' km' : null;
    $hm    = isset($t['hm_up'])   ? $t['hm_up'] . ' hm' : null;
    $ele   = (isset($t['ele_start']) && isset($t['ele_end']))
             ? $t['ele_start'] . '→' . $t['ele_end'] . ' m' : null;
    $kmh   = isset($t['kmh']) && $t['kmh'] ? number_format($t['kmh'], 1, ',', '.') . ' km/h' : null;

    $stats = implode(', ', array_filter([$dist, $hm, $ele, $kmh]));
    $title = $place . ' – ' . ($t['date_str'] ?? $day);
    $desc  = 'Tour ab ' . $place . ' am ' . ($t['date_str'] ?? $day)
           . ($stats ? '. ' . $stats : '') . '.';

    // Deep-Link auf das passende Jahr/Monat-Filterset des Reports
    $y = (int)substr($sk, 0, 4); $m = (int)substr($sk, 5, 2);
    $link = $base . '/gpx_report.php' . ($y ? "?year=$y&month=$m" : '');

    $guid = 'gpx-' . md5(($t['filename'] ?? $title) . $sk);
    $items .= "  <item>\n"
        . "    <title>" . x($title) . "</title>\n"
        . "    <link>" . x($link) . "</link>\n"
        . "    <guid isPermaLink=\"false\">" . x($guid) . "</guid>\n"
        . "    <pubDate>" . date(DATE_RSS, $ts) . "</pubDate>\n"
        . "    <description>" . x($desc) . "</description>\n"
        . "  </item>\n";
}
echo '<?xml version="1.0" encoding="UTF-8"?>' . "\n";
?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>OSMCycle · Aufgezeichnete Touren</title>
  <atom:link href="<?= $base ?>/rss_gpx.php" rel="self" type="application/rss+xml"/>
  <link><?= $base ?>/gpx_report.php</link>
  <description>GPS-Touren (Rad/Wandern) aus der OSMCycle-App, mit Distanz, Höhenmetern und Startort – automatisch aus den hochgeladenen GPX-Tracks.</description>
  <language>de-de</language>
  <lastBuildDate><?= date(DATE_RSS, strtotime($latest)) ?></lastBuildDate>
  <ttl>720</ttl>
<?= $items ?></channel>
</rss>
