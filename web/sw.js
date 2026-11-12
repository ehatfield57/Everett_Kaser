// sw.js - service worker: keeps the app itself on this device so the home
// page and downloaded games work while the server is off.  Served at /sw.js
// by server.py, which fills in VERSION from the files in web/; when any of
// them changes, browsers install a fresh copy of everything at once (so an
// interpreter's .js and .wasm always match).
'use strict';

const VERSION = '__VERSION__';
const SHELL = 'shell-' + VERSION;
const DATA = 'data';            // game list, icons, sound bank: kept across versions

const SHELL_FILES = [
  '/', '/play', '/manifest.webmanifest',
  '/web/play.js', '/web/worker.js', '/web/store.js', '/web/fs.js', '/web/download.js',
  '/web/kint5.js', '/web/kint5.wasm', '/web/kint6.js', '/web/kint6.wasm',
  '/web/vendor/spessasynth.js', '/web/vendor/spessasynth_processor.min.js',
];
const DATA_FILES = ['/api/soundbank', '/app-icon.png'];

self.addEventListener('install', (e) => {
  e.waitUntil((async () => {
    const shell = await caches.open(SHELL);
    await shell.addAll(SHELL_FILES.map((u) => new Request(u, { cache: 'reload' })));
    const data = await caches.open(DATA);
    for (const u of DATA_FILES) {
      if (!(await data.match(u))) await data.add(u);
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
  const hit = await caches.match(path, { cacheName: SHELL });
  return hit || fetch(req);
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  const p = url.pathname;
  if (p === '/' || p === '/index.html') return e.respondWith(shellFile('/', req));
  if (p === '/play') return e.respondWith(shellFile('/play', req));
  if (p === '/manifest.webmanifest' || p.startsWith('/web/')) return e.respondWith(shellFile(p, req));
  if (p === '/api/games' || p.startsWith('/api/info/')) return e.respondWith(networkFirst(req));
  if (p.startsWith('/api/icon/') || p === '/api/soundbank' || p === '/app-icon.png' || p === '/favicon.ico') return e.respondWith(cacheFirst(req));
  // everything else (game files, downloads, saves) goes straight to the server
});
