// sw.js - service worker: keeps the app itself on this device so the home
// page and downloaded games work with no connection.  server.py serves it at
// /sw.js and fills in VERSION from the files in web/; when any of them
// changes, browsers install a fresh copy of everything at once (so an
// interpreter's .js and .wasm always match).
//
// On a static site (tools/make_static.py, which also fills in STATIC) there is
// no server.py to send the headers that turn on cross-origin isolation, which
// the games need for SharedArrayBuffer.  This worker adds them to every page
// and file it hands out instead.
'use strict';

const VERSION = '__VERSION__';
const STATIC = '__STATIC__' === 'true';
const SHELL = 'shell-' + VERSION;
const DATA = 'data';            // game list, icons, sound bank: kept across versions

// Paths are relative to where the site lives (this worker's scope), so a
// static site works in a sub-folder of a web site too.
const BASE = new URL(self.registration.scope).pathname;
const ENGINE_FILES = [
  'web/config.js', 'web/play.js', 'web/upscale.js', 'web/worker.js', 'web/store.js', 'web/fs.js', 'web/download.js',
  'web/kint5.js', 'web/kint5.wasm', 'web/kint6.js', 'web/kint6.wasm',
  'web/vendor/spessasynth.js', 'web/vendor/spessasynth_processor.min.js',
];
const PLAY = STATIC ? 'play.html' : 'play';
const SHELL_FILES = ['', PLAY, 'manifest.webmanifest', ...ENGINE_FILES];
const SOUNDBANK = STATIC ? 'soundbank.bin' : 'api/soundbank';
const DATA_FILES = [SOUNDBANK, 'app-icon.png'];
const GAME_LIST = STATIC ? 'games.json' : 'api/games';

self.addEventListener('install', (e) => {
  e.waitUntil((async () => {
    const shell = await caches.open(SHELL);
    await shell.addAll(SHELL_FILES.map((u) => new Request(BASE + u, { cache: 'reload' })));
    const data = await caches.open(DATA);
    for (const u of DATA_FILES) {
      if (!(await data.match(BASE + u))) await data.add(BASE + u);
    }
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) {
      if (k.startsWith('shell-') && k !== SHELL) await caches.delete(k);
    }
    await self.clients.claim();
  })());
});

// While the server is unreachable, don't make every request wait for a timeout.
let offlineUntil = 0;

async function fromNetwork(req, ms) {
  if (Date.now() < offlineUntil) throw new Error('offline');
  try {
    const res = await fetch(req, { signal: AbortSignal.timeout(ms) });
    offlineUntil = 0;
    return res;
  } catch (err) {
    offlineUntil = Date.now() + 15000;
    throw err;
  }
}

// Fresh from the server when it answers quickly, else the last copy.
async function networkFirst(req) {
  const cache = await caches.open(DATA);
  try {
    const res = await fromNetwork(req, 2500);
    if (res.ok) await cache.put(req, res.clone());
    return res;
  } catch {
    const hit = await cache.match(req);
    if (hit) {   // mark it, so the page knows the server is away
      const headers = new Headers(hit.headers);
      headers.set('X-Kaser-Offline', '1');
      return new Response(hit.body, { status: hit.status, headers });
    }
    return new Response('offline', { status: 503, headers: { 'Content-Type': 'text/plain', 'X-Kaser-Offline': '1' } });
  }
}

async function cacheFirst(req) {
  const cache = await caches.open(DATA);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fromNetwork(req, 10000);
  if (res.ok) await cache.put(req, res.clone());
  return res;
}

async function shellFile(path, req) {
  const hit = await caches.match(BASE + path, { cacheName: SHELL });
  return hit || fetch(req);
}

// The headers server.py sends with everything (see Handler.end_headers).
function isolated(res) {
  if (!STATIC || res.type === 'opaque' || res.status === 0) return res;
  const headers = new Headers(res.headers);
  headers.set('Cross-Origin-Opener-Policy', 'same-origin');
  headers.set('Cross-Origin-Embedder-Policy', 'require-corp');
  headers.set('Cross-Origin-Resource-Policy', 'same-origin');
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
}

function answer(e, promise) {
  e.respondWith(promise.then(isolated));
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin || !url.pathname.startsWith(BASE)) return;
  let p = url.pathname.slice(BASE.length);
  if (p === 'index.html') p = '';
  if (p === '' || p === PLAY || SHELL_FILES.includes(p)) return answer(e, shellFile(p, req));
  if (!STATIC && p.startsWith('web/')) return answer(e, shellFile(p, req));
  if (p === GAME_LIST || p.startsWith('api/info/')) return answer(e, networkFirst(req));
  if (p === SOUNDBANK || p === 'app-icon.png' || p === 'favicon.ico' ||
      p.startsWith('icons/') || p.startsWith('api/icon/')) return answer(e, cacheFirst(req));
  // Everything else (game downloads, and on the server game files and saves)
  // goes straight to the network.  A static site still needs the headers.
  if (STATIC) answer(e, fetch(req));
});
