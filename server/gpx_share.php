<?php // gpx_share.php – öffentliche GPX-Upload-Seite (kein Login). Postet an gpx_upload.php. ?>
<!doctype html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GPX-Tour hochladen · OSMCycle</title>
<link rel="alternate" type="application/rss+xml" title="OSMCycle · Touren" href="rss_gpx.php">
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
         margin: 0; padding: 1.2rem; line-height: 1.5;
         background: #f6f8f7; color: #1b2a24; }
  @media (prefers-color-scheme: dark) { body { background:#12161a; color:#e6ebe8; } }
  .wrap { max-width: 560px; margin: 0 auto; }
  h1 { font-size: 1.35rem; margin: .2rem 0 .1rem; }
  p.sub { margin: 0 0 1.2rem; opacity: .75; font-size: .95rem; }
  label { display:block; font-weight:600; font-size:.9rem; margin:.9rem 0 .3rem; }
  input[type=text] { width:100%; padding:.6rem .7rem; border-radius:10px;
    border:1px solid #b9c6c0; background:transparent; color:inherit; font-size:1rem; }
  #drop { margin-top:.4rem; border:2px dashed #2c6e49; border-radius:16px;
    padding:2rem 1rem; text-align:center; cursor:pointer; transition:.15s;
    background:rgba(44,110,73,.06); }
  #drop.hi { background:rgba(44,110,73,.18); border-color:#198754; }
  #drop .big { font-size:2.2rem; }
  #drop .hint { opacity:.7; font-size:.85rem; margin-top:.3rem; }
  #list { list-style:none; padding:0; margin:1rem 0 0; }
  #list li { display:flex; justify-content:space-between; gap:.6rem;
    padding:.5rem .7rem; border-radius:10px; background:rgba(127,127,127,.1);
    margin-bottom:.4rem; font-size:.9rem; align-items:center; }
  #list .st { font-weight:700; white-space:nowrap; }
  .ok { color:#198754; } .err { color:#dc3545; } .run { opacity:.6; }
  a.report { display:inline-block; margin-top:1.3rem; color:#2c6e49; font-weight:600; }
  .foot { margin-top:1.6rem; font-size:.8rem; opacity:.6; }
</style>
</head>
<body>
<div class="wrap">
  <h1>🚴 GPX-Tour hochladen</h1>
  <p class="sub">Deine Aufnahme landet im öffentlichen
     <a href="gpx_report.php">Tour-Report</a> – ohne Anmeldung.
     Aus OsmAnd: <em>Meine Orte → Tracks → Teilen → GPX</em>.</p>

  <label for="nick">Dein Name / Kürzel <span style="font-weight:400;opacity:.6">(optional)</span></label>
  <input type="text" id="nick" placeholder="z. B. Alex" maxlength="30" autocomplete="off">

  <label>GPX-Datei(en)</label>
  <div id="drop">
    <div class="big">📂</div>
    <div>Datei hier ablegen oder <u>zum Auswählen tippen</u></div>
    <div class="hint">.gpx · mehrere möglich · max. 10 MB pro Datei</div>
  </div>
  <input type="file" id="file" accept=".gpx,application/gpx+xml" multiple hidden>

  <ul id="list"></ul>
  <a class="report" href="gpx_report.php">→ Zum Tour-Report</a>

  <div class="foot">Nur echte Fahrten erscheinen (Tracks unter 1&nbsp;km / 2&nbsp;hm werden gefiltert).
    Die Karte im Report zeigt Touren im Alpenraum in unserer CyclOSM-Karte, sonst OSM.</div>
</div>

<script>
const drop = document.getElementById('drop');
const file = document.getElementById('file');
const list = document.getElementById('list');
const nick = document.getElementById('nick');
const ENDPOINT = 'gpx_upload.php';

drop.addEventListener('click', () => file.click());
drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('hi'); });
drop.addEventListener('dragleave', () => drop.classList.remove('hi'));
drop.addEventListener('drop', e => {
  e.preventDefault(); drop.classList.remove('hi');
  handle(e.dataTransfer.files);
});
file.addEventListener('change', () => handle(file.files));

function cleanNick(s) { return s.trim().replace(/[^A-Za-z0-9_-]+/g, '_').replace(/^_+|_+$/g, ''); }

function uploadName(orig) {
  const n = cleanNick(nick.value);
  if (!n) return orig;
  const base = orig.replace(/\.gpx$/i, '');
  return base + '__' + n + '.gpx';
}

function handle(files) {
  [...files].forEach(f => {
    if (!/\.gpx$/i.test(f.name)) return addRow(f.name, 'keine .gpx', 'err');
    if (f.size > 10 * 1024 * 1024) return addRow(f.name, 'zu groß', 'err');
    const li = addRow(f.name, '…', 'run');
    const fd = new FormData();
    fd.append('file', f, uploadName(f.name));
    fetch(ENDPOINT, { method: 'POST', body: fd })
      .then(r => r.text().then(t => ({ ok: r.ok, t })))
      .then(({ ok, t }) => setRow(li, ok ? '✓ hochgeladen' : ('✗ ' + t), ok ? 'ok' : 'err'))
      .catch(() => setRow(li, '✗ Netzwerk', 'err'));
  });
}

function addRow(name, status, cls) {
  const li = document.createElement('li');
  li.innerHTML = '<span>' + name.replace(/</g,'&lt;') + '</span><span class="st ' + cls + '">' + status + '</span>';
  list.appendChild(li);
  return li;
}
function setRow(li, status, cls) {
  const st = li.querySelector('.st'); st.textContent = status; st.className = 'st ' + cls;
}
</script>
</body>
</html>
