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
if (!$url) $url = 'https://tmind.de/maps/apk/osmcycle-v0.9.apk';   // Fallback

header('Location: ' . $url, true, 302);
echo 'Redirecting to the latest OSMCycle APK: ' . htmlspecialchars($url);
