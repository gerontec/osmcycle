<?php
// Public GPX drop endpoint for the osmcycle app — NO security check, anyone
// may upload. Saved files land in gpx_uploads/ which gpx_report.py scans, so
// uploaded tracks show up on gpx_report.php after the next hourly regenerate.
// Only guards: must be a .gpx and <= 10 MB (to keep junk out, not for auth).
header('Content-Type: text/plain; charset=utf-8');

if (empty($_FILES['file']['name'])) { http_response_code(400); exit('no file'); }
$name = basename($_FILES['file']['name']);
if (!preg_match('/\.gpx$/i', $name)) { http_response_code(400); exit('only .gpx'); }
if (($_FILES['file']['size'] ?? 0) > 10 * 1024 * 1024) { http_response_code(413); exit('too big'); }

// keep the YYYY-MM-DD_HH-MM_Weekday.gpx convention gpx_report.py parses,
// just strip anything unexpected.
$name = preg_replace('/[^A-Za-z0-9._-]/', '_', $name);

$dir = __DIR__ . '/gpx_uploads';
if (!is_dir($dir) && !mkdir($dir, 0755, true)) { http_response_code(500); exit('mkdir failed'); }

$dest = "$dir/$name";
if (move_uploaded_file($_FILES['file']['tmp_name'], $dest)) {
    @chmod($dest, 0644);   // world-readable so the gh cron (gpx_report.py) can read it
    echo 'OK';
} else {
    http_response_code(500);
    exit('save failed');
}
