// gamepage.js - one game's own page on a static site (game.html).
//
// In a browser it offers to install the game as an app of its own (Chrome and
// Edge ask with a button; Safari needs Share -> Add to Home Screen), or to play
// it right there.  Opened as the installed app, it downloads the game the first
// time (and again when the site has a newer version), then starts it.
//
// The game runs from play.html in this same folder, so it stays inside the
// installed app (a page outside the app's folder would open in a browser bar).
'use strict';

const G = JSON.parse(document.getElementById('game').textContent);  // {name, icon, index, version, total}
const site = (p) => new URL('../' + p, location.href).href;
const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const standalone = navigator.standalone ||
  matchMedia('(display-mode: standalone), (display-mode: fullscreen), (display-mode: minimal-ui)').matches;

$('name').textContent = G.name;
$('iosName').textContent = G.name;
$('device').textContent = /iPhone|iPod/.test(navigator.userAgent) ? 'iPhone' : 'iPad';
$('install').textContent = 'Install ' + G.name;

// The service worker keeps this page and the game code for use offline, and
// adds the headers the game needs (see sw.js).  In an iPad Home Screen app this
// is the first page ever opened, so it registers the worker itself.
if ('serviceWorker' in navigator && window.isSecureContext) {
  navigator.serviceWorker.register(site('sw.js')).catch((err) => console.warn('offline support unavailable:', err));
}

function sizeText(bytes) { return Math.max(1, Math.round(bytes / 1e6)) + ' MB'; }
function setState(text, ok) { $('state').textContent = text; $('state').classList.toggle('ok', !!ok); }

// The site's current entry for this game, if the site can be reached.
async function latest() {
  try {
    const res = await fetch(site('games.json'), { cache: 'no-cache' });
    if (!res.ok || res.headers.get('X-Kaser-Offline')) return null;
    return (await res.json()).find((g) => g.name === G.name) || null;
  } catch { return null; }
}

function download(entry) {
  $('progress').hidden = false;
  $('progressText').textContent = 'Downloading…';
  $('fill').style.width = '0';
  if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
  return new Promise((resolve) => {
    const w = new Worker(site('web/download.js'));
    w.onmessage = (e) => {
      const m = e.data;
      if (m.t === 'progress') {
        $('fill').style.width = (100 * m.done / Math.max(1, m.total)).toFixed(1) + '%';
        $('progressText').textContent = m.note || `Downloading… ${sizeText(m.done)} of ${sizeText(m.total)}`;
        return;
      }
      w.terminate();
      $('progress').hidden = true;
      if (m.t === 'done') resolve(true);
      else { alert(`${G.name} couldn't be downloaded.\n\n${m.text}`); resolve(false); }
    };
    w.onerror = (e) => w.onmessage({ data: { t: 'error', text: e.message || 'unknown error' } });
    w.postMessage({ game: G.name, server: false, index: site(entry.index), icon: site(entry.icon || 'app-icon.png') });
  });
}

// Make sure an up-to-date copy is on this device.  An older copy still plays
// when there's no connection or the update fails.
async function ready() {
  let rec = null;
  try { rec = await KStore.getGame(G.name); } catch {}
  const entry = await latest();
  if (rec && (!entry || rec.version === entry.version)) return true;
  if (!entry) {
    setState('No connection to the games site, and the game isn\'t downloaded yet. Try again when you\'re online.');
    return false;
  }
  setState(rec ? 'Updating…' : 'Downloading the game (once)…');
  const ok = await download(entry);
  return ok || !!rec;
}

function play() {
  location.replace('play.html?g=' + encodeURIComponent(G.name));
}

async function playWhenReady(btn) {
  btn.disabled = true;
  try {
    if (await ready()) play();
  } finally { btn.disabled = false; }
}

async function main() {
  if (!window.isSecureContext) {
    setState('The games only run on a secure page (https://, or http://localhost on the computer serving them).');
    return;
  }
  let rec = null;
  try { rec = await KStore.getGame(G.name); } catch {}

  if (standalone) {
    // The installed app: straight into the game, except after leaving it.
    $('allGames').hidden = true;
    $('app').hidden = false;
    $('play').onclick = () => playWhenReady($('play'));
    if (params.has('exited')) { setState(rec ? 'Ready to play' : '', true); return; }
    setState(rec ? 'Starting…' : 'Getting ready…');
    if (await ready()) play();
    else $('play').textContent = 'Try again';
    return;
  }

  // In a browser
  $('browser').hidden = false;
  setState(rec ? 'On this device' : `${sizeText(G.total)} download`, !!rec);
  $('playHere').onclick = () => playWhenReady($('playHere'));
  if (isIOS) { $('iosSteps').hidden = false; return; }
  let prompt = null;
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    prompt = e;
    $('install').hidden = false;
    $('otherSteps').hidden = true;
  });
  window.addEventListener('appinstalled', () => {
    $('install').hidden = true;
    setState(`Installed. Open ${G.name} from your apps; it downloads the game the first time.`, true);
  });
  $('install').onclick = async () => {
    if (!prompt) return;
    prompt.prompt();
    try { await prompt.userChoice; } catch {}
    prompt = null;
  };
  // No offer from the browser after a moment: it can't install pages, or this
  // game is installed already.
  setTimeout(() => { if (!prompt) $('otherSteps').hidden = false; }, 2000);
}

main();
