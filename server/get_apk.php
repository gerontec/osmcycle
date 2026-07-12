<?php
// get_apk.php – stabiler Redirect auf die NEUESTE OSMCycle-APK.
// QR-Code/Link zeigen hierher und bleiben über alle Releases hinweg gültig:
// fragt die GitHub-Releases ab (1 h gecacht), leitet auf das .apk-Asset weiter.
$cache = __DIR__ . '/.apk_url_cache';
$url = null;

if (is_file($cache) && (time() - filemtime($cache) < 3600)) {
    $url = trim((string)@file_get_contents($cache)) ?: null;
}
if (!$url) {
    $ctx = stream_context_create(['http' => [
        'header' => "User-Agent: osmcycle-get-apk\r\n", 'timeout' => 8]]);
    $j = @file_get_contents(
        'https://api.github.com/repos/gerontec/osmcycle/releases/latest', false, $ctx);
    if ($j && ($d = json_decode($j, true)) && !empty($d['assets'])) {
        foreach ($d['assets'] as $a) {
            if (preg_match('/\.apk$/i', $a['name'] ?? '')) {
                $url = $a['browser_download_url']; break;
            }
        }
    }
    if ($url) @file_put_contents($cache, $url);
}

// Fallback, wenn GitHub nicht erreichbar ist: die neueste APK aus dem eigenen
// Spiegel. Bewusst nicht auf eine Version festgenagelt — eine fest verdrahtete
// Datei veraltet mit jedem Release still und heimlich (stand zuletzt auf v1.5,
// als v1.7 schon da war).
if (!$url) {
    $best = null; $best_v = '0';
    foreach (glob(__DIR__ . '/apk/osmcycle-v*.apk') as $f) {
        if (preg_match('/osmcycle-v([\d.]+)\.apk$/i', $f, $m)
            && version_compare($m[1], $best_v, '>')) {
            $best_v = $m[1];
            $best = 'https://heissa.de/web1/apk/' . basename($f);
        }
    }
    $url = $best;
}
if (!$url) {                              // weder GitHub noch Spiegel
    http_response_code(503);
    exit('No OSMCycle APK available right now.');
}

header('Location: ' . $url, true, 302);
echo 'Redirecting to the latest OSMCycle APK: ' . htmlspecialchars($url);
