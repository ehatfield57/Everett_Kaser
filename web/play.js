// play.js - the page side of a running game: shows the screen, forwards
// mouse and keyboard input to the worker, and plays sounds.
'use strict';

const params = new URLSearchParams(location.search);
const GAME = params.get('g') || '';
const canvas = document.getElementById('screen');
const ctx = canvas.getContext('2d', { alpha: false });
const statusEl = document.getElementById('status');
const overlay = document.getElementById('overlay');
const box = document.getElementById('box');

// --------------------------------------------------------------- input ring
// Must match js_poll_input() in kint_lib.js: [head, tail, ..., events of 6 ints]
const RING_CAP = 4096, EV_SIZE = 6, BASE = 8;
const EV = { MOUSEMOVE: 1, MOUSEDOWN: 2, MOUSEUP: 3, WHEEL: 4, HWHEEL: 5, KEYDOWN: 6, KEYUP: 7,
             CHAR: 8, RESIZE: 9, BLUR: 10, MUSICDONE: 11, CLOSE: 12, HIDDEN: 13, FOCUS: 14 };
let ring = null;

function send(type, a = 0, b = 0, c = 0, d = 0) {
  if (!ring) return;
  const head = Atomics.load(ring, 0), tail = Atomics.load(ring, 1);
  if (head - tail >= RING_CAP) return;           // full: drop
  const o = BASE + (head % RING_CAP) * EV_SIZE;
  ring[o] = type; ring[o + 1] = a; ring[o + 2] = b; ring[o + 3] = c; ring[o + 4] = d;
  Atomics.store(ring, 0, head + 1);
  Atomics.notify(ring, 0);
}

// ---------------------------------------------------------------- overlay
function showBox(html, buttons) {
  box.innerHTML = html;
  const row = document.createElement('div');
  row.className = 'row';
  for (const b of buttons) row.appendChild(b);
  box.appendChild(row);
  overlay.classList.add('show');
  const first = row.querySelector('button.primary') || row.firstChild;
  if (first) first.focus();
}
function button(label, onclick, primary) {
  const b = document.createElement('button');
  b.textContent = label;
  if (primary) b.className = 'primary';
  b.onclick = onclick;
  return b;
}
function hideBox() { overlay.classList.remove('show'); canvas.focus(); }
function escapeHtml(s) { return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
// In its own window (opened by the launcher) the game closes; otherwise it
// goes back to the launcher in this window.
function backToGames() {
  savesWritten().then(() => {
    let opener = null;
    try { opener = window.opener && !window.opener.closed ? window.opener : null; } catch {}
    if (opener) {
      try { opener.focus(); } catch {}
      window.close();
    }
    if (!window.closed) location.href = '/';
  });
}

// ------------------------------------------------------------------ saves
// A game kept on this device saves into IndexedDB.  The worker can't wait for
// IndexedDB while the game runs, so it hands each change to this page.
let saveChain = Promise.resolve();
function storeSaves(ops) {
  saveChain = saveChain.then(() => KStore.applySaves(ops)).catch((err) => {
    console.error('could not save:', err);
    showBox(`<p><b>Your progress could not be saved on this device.</b></p><pre>${escapeHtml(String(err))}</pre>`,
      [button('OK', hideBox, true)]);
  });
}
const savesWritten = () => saveChain;

// ------------------------------------------------------------------ sound
let audio = null, current = null;
const soundCache = new Map();
function audioCtx() {
  if (!audio) audio = new AudioContext();
  if (audio.state === 'suspended') audio.resume();
  return audio;
}
function soundKey(bytes) {           // cheap content hash so repeated sounds decode once
  const u = new Uint8Array(bytes);
  let h = 2166136261;
  for (let i = 0; i < u.length; i += 7) h = Math.imul(h ^ u[i], 16777619);
  return u.length + ':' + (h >>> 0);
}
async function playSound(bytes, nostop) {
  const ac = audioCtx();
  if (nostop && current) return;     // SND_NOSTOP: don't interrupt a playing sound
  const key = soundKey(bytes);
  let buf = soundCache.get(key);
  if (!buf) {
    try { buf = await ac.decodeAudioData(bytes); } catch { return; }
    soundCache.set(key, buf);
  }
  stopSound();
  const src = ac.createBufferSource();
  src.buffer = buf;
  src.connect(ac.destination);
  src.onended = () => { if (current === src) current = null; };
  src.start();
  current = src;
}
function stopSound() {
  if (current) { try { current.stop(); } catch {} current = null; }
}

// ------------------------------------------------------------------ music
// MIDI music is played by SpessaSynth using macOS's own General MIDI sound
// bank, the same one the native Mac apps use.
const music = { setup: null, synth: null, seq: null, playing: false, songs: 0 };
function musicSetup() {
  if (!music.setup) {
    music.setup = (async () => {
      const ac = audioCtx();
      await ac.audioWorklet.addModule('/web/vendor/spessasynth_processor.min.js');
      const { WorkletSynthesizer, Sequencer } = await import('/web/vendor/spessasynth.js');
      const bank = await (await fetch('/api/soundbank')).arrayBuffer();
      const synth = new WorkletSynthesizer(ac);
      synth.connect(ac.destination);
      await synth.soundBankManager.addSoundBank(bank, 'main');
      await synth.isReady;
      const seq = new Sequencer(synth);
      seq.loopCount = 0;
      seq.eventHandler.addEvent('songEnded', 'kint', () => {
        if (music.playing) { music.playing = false; send(EV.MUSICDONE); }
      });
      music.synth = synth;
      music.seq = seq;
    })().catch((err) => { console.error('music unavailable:', err); });
  }
  return music.setup;
}
async function playMusic(bytes) {
  await musicSetup();
  if (!music.seq) { send(EV.MUSICDONE); return; }
  music.seq.loadNewSongList([{ binary: bytes, fileName: 'song.mid' }]);
  music.seq.play();
  music.playing = true;
  music.songs++;
}
function stopMusic() {
  music.playing = false;
  if (music.seq) { music.seq.pause(); music.synth.stopAll(true); }
}
function pauseMusic(pause) {
  if (!music.seq || !music.playing) return;
  if (pause) { music.seq.pause(); music.synth.stopAll(true); } else music.seq.play();
}

// ----------------------------------------------------------------- screen
// The games lay themselves out for a desktop-sized window, so a phone gets a
// game screen at least PHONE_MIN_W x PHONE_MIN_H (same shape as the window),
// shown shrunk to fit.  Elsewhere the game screen is the window's size.
const PHONE_MIN_W = 1024, PHONE_MIN_H = 720;
const isPhone = navigator.maxTouchPoints > 0 && Math.min(screen.width, screen.height) < 600;
function gameSize(w, h) {
  const f = isPhone ? Math.max(1, PHONE_MIN_W / w, PHONE_MIN_H / h) : 1;
  return { w: Math.round(w * f), h: Math.round(h * f) };
}
function viewSize() {
  return gameSize(Math.max(1, Math.floor(window.innerWidth)), Math.max(1, Math.floor(window.innerHeight)));
}
// The largest game screen either way up, so turning the phone never needs more than the game set aside.
function screenSize() {
  if (!isPhone) return { w: screen.width, h: screen.height };
  const a = gameSize(screen.width, screen.height), b = gameSize(screen.height, screen.width);
  return { w: Math.max(a.w, b.w), h: Math.max(a.h, b.h) };
}
function sizeCanvas(w, h) {
  if (canvas.width === w && canvas.height === h) return;
  canvas.width = w;
  canvas.height = h;
  canvas.style.width = w + 'px';
  canvas.style.height = h + 'px';
  relayout();
}

// ------------------------------------------------------------------- zoom
// The canvas is placed with a CSS transform: whole ("fit") or magnified with
// two fingers.  The game doesn't know; pos() maps touches back through it.
// zoom = how far in (1 = fit) and which spot of the game screen (as a fraction
// of its size) is in the middle of the window; it's kept per game.
const MAX_SCALE = 3;                 // most CSS pixels per game pixel
const ZOOM_PREF = 'kaser.zoom.' + GAME;
const zoom = { z: 1, cx: 0.5, cy: 0.5 };
try {
  const v = JSON.parse(localStorage.getItem(ZOOM_PREF));
  if (v && v.z > 1) Object.assign(zoom, { z: +v.z, cx: +v.cx, cy: +v.cy });
} catch {}
function fitScale() {
  return Math.min(window.innerWidth / canvas.width, window.innerHeight / canvas.height, 1);
}
function zoomed() { return zoom.z > 1.001; }
// Show the canvas at scale s with its corner at (tx, ty), kept on screen.
function placeCanvas(s, tx, ty) {
  const W = window.innerWidth, H = window.innerHeight, fit = fitScale();
  s = Math.min(Math.max(s, fit), Math.max(fit, MAX_SCALE));
  const cw = canvas.width * s, ch = canvas.height * s;
  tx = cw <= W ? (W - cw) / 2 : Math.min(0, Math.max(W - cw, tx));
  ty = ch <= H ? (H - ch) / 2 : Math.min(0, Math.max(H - ch, ty));
  zoom.z = s / fit; zoom.cx = (W / 2 - tx) / cw; zoom.cy = (H / 2 - ty) / ch;
  canvas.style.transform = `translate(${tx}px, ${ty}px) scale(${s})`;
  // Square pixels when each game pixel covers a whole number of screen pixels
  // (or plenty of them); smoothed otherwise, so shrunk text stays readable.
  const p = s * (window.devicePixelRatio || 1);
  canvas.style.imageRendering = p >= 2.5 || Math.abs(p - Math.round(p)) < 0.01 ? 'pixelated' : 'auto';
  document.getElementById('zoomBtn').classList.toggle('show', zoomed());
}
// The window or the game screen changed size: keep the same zoom and spot.
function relayout() {
  const s = fitScale() * zoom.z;
  placeCanvas(s, window.innerWidth / 2 - zoom.cx * canvas.width * s,
                 window.innerHeight / 2 - zoom.cy * canvas.height * s);
}
function saveZoom() {
  try {
    if (zoomed()) localStorage.setItem(ZOOM_PREF, JSON.stringify(zoom));
    else localStorage.removeItem(ZOOM_PREF);
  } catch {}
}
function zoomOut() {
  placeCanvas(0, 0, 0);
  saveZoom();
}

// ----------------------------------------------------------------- worker
const worker = new Worker('/web/worker.js');
worker.onerror = (e) => showCrash(e.message || 'worker error');
worker.onmessage = (e) => {
  const m = e.data;
  switch (m.t) {
    case 'frame':
      if (statusEl.isConnected) { statusEl.remove(); firstFrame(); }
      sizeCanvas(m.cw, m.ch);
      ctx.putImageData(new ImageData(new Uint8ClampedArray(m.buf), m.w, m.h), m.x, m.y);
      break;
    case 'sound': playSound(m.bytes, m.nostop); break;
    case 'soundstop': stopSound(); break;
    case 'music': playMusic(m.bytes); break;
    case 'musicstop': stopMusic(); break;
    case 'musicpause': pauseMusic(m.pause); break;
    case 'title': document.title = m.text || GAME; break;
    case 'cursor': canvas.style.cursor = m.c === 1 ? 'wait' : m.c === 2 ? 'pointer' : 'default'; break;
    case 'openurl': if (/^https?:/i.test(m.url || '')) window.open(m.url, '_blank', 'noopener'); break;
    case 'clipboard': navigator.clipboard?.writeText(m.text).catch(() => {}); break;
    case 'message':
      showBox(`<p>${escapeHtml(m.text)}</p>`, [button('OK', hideBox, true)]);
      break;
    case 'saves': storeSaves(m.ops); break;
    case 'exit':
      worker.terminate();
      backToGames();
      break;
    case 'crash': showCrash(m.text); break;
  }
};
function showCrash(text) {
  console.error(text);
  showBox(`<p><b>The game stopped unexpectedly.</b></p><pre>${escapeHtml(text)}</pre>`,
    [button('Back to games', backToGames), button('Restart', () => location.reload(), true)]);
}

async function start() {
  if (!crossOriginIsolated) {
    showCrash(window.isSecureContext
      ? 'This page must be served by server.py (it needs cross-origin isolation for SharedArrayBuffer).'
      : 'Chrome only runs the games on a secure page, and this address isn\'t one. ' +
        'Open /setup on this device to set it up (once), then play from the https:// address.');
    return;
  }
  document.title = GAME;
  // Use the copy kept on this device if there is one, otherwise the server.
  let info = null, local = false;
  try { info = await KStore.getGame(GAME); local = !!info; } catch {}
  if (!info) {
    try { info = await (await fetch('/api/info/' + encodeURIComponent(GAME))).json(); } catch {}
  }
  if (!info) {
    showBox('<p><b>This game isn\'t stored on this device, and the game server can\'t be reached.</b></p>' +
      '<p>Start the server on your Mac, or pick a game that has been downloaded.</p>',
      [button('Back to games', backToGames, true)]);
    return;
  }
  const sab = new SharedArrayBuffer((BASE + RING_CAP * EV_SIZE) * 4);
  ring = new Int32Array(sab);
  const { w, h } = viewSize(), scr = screenSize();
  sizeCanvas(w, h);
  worker.postMessage({ t: 'init', game: GAME, local, sab, ringCap: RING_CAP, music: true,
                       engine: info.engine, beta: info.beta, pgmShown: info.pgm, appShown: info.app,
                       screenW: scr.w, screenH: scr.h, w, h });
  canvas.focus();
}

// ------------------------------------------------------------ mouse input
// Windows MK_ flags for wParam
function mouseFlags(e) {
  return (e.buttons & 1 ? 1 : 0) | (e.buttons & 2 ? 2 : 0) | (e.shiftKey ? 4 : 0) |
         (e.ctrlKey ? 8 : 0) | (e.buttons & 4 ? 0x10 : 0);
}
// Window position -> game screen pixel, through any zoom.
function pos(e) {
  const r = canvas.getBoundingClientRect(), k = canvas.width / r.width;
  return [Math.floor((e.clientX - r.left) * k), Math.floor((e.clientY - r.top) * k)];
}
const BTN = { 0: 0, 1: 1, 2: 2 };      // DOM button -> left/middle/right
let buttonsDown = 0;

// Browsers follow a touch with imitation mouse events; the touch code below
// handles touches itself, so ignore mouse events that arrive right after one.
let lastTouch = -1e9;
const fromTouch = () => performance.now() - lastTouch < 1000;

canvas.addEventListener('mousedown', (e) => {
  if (overlay.classList.contains('show') || fromTouch()) return;
  e.preventDefault();
  canvas.focus();
  audioCtx();
  const b = BTN[e.button];
  if (b === undefined) return;
  buttonsDown |= 1 << b;
  const [x, y] = pos(e);
  send(EV.MOUSEDOWN, b, x, y, mouseFlags(e));
});
window.addEventListener('mouseup', (e) => {
  const b = BTN[e.button];
  if (b === undefined || !(buttonsDown & (1 << b))) return;
  buttonsDown &= ~(1 << b);
  const [x, y] = pos(e);
  send(EV.MOUSEUP, b, x, y, mouseFlags(e));
});
window.addEventListener('mousemove', (e) => {
  if (e.target !== canvas && !buttonsDown) return;
  if (fromTouch()) return;
  const [x, y] = pos(e);
  send(EV.MOUSEMOVE, x, y, mouseFlags(e));
});
canvas.addEventListener('contextmenu', (e) => e.preventDefault());

// ------------------------------------------------------------ touch input
// For iPad and other touch screens:
//   tap                    -> left click
//   touch and drag         -> left-button drag
//   touch and hold         -> right click (a ring shows when it registers)
//   tap with two fingers   -> right click where the first finger is
//   spread / pinch two fingers -> zoom in / out (it stays zoomed); move two fingers to look around
// With "swipe = arrow keys" switched on (the ✥ button), a drag becomes arrow
// keys instead: a flick is one press, every SWIPE_STEP of travel is another,
// and holding the finger still after a swipe repeats the key.
// A mouse or trackpad on the iPad still goes through the mouse handlers above.
const LONG_PRESS_MS = 450, MOVE_SLOP = 10;
const SWIPE_FIRST = 24, SWIPE_STEP = 40, REPEAT_DELAY_MS = 500, REPEAT_MS = 150;
const VK = { LEFT: 37, UP: 38, RIGHT: 39, DOWN: 40, BACK: 8, ENTER: 13, SPACE: 32 };
let touch = null;   // { id, x, y (game), cx, cy (window), state: 'pending' | 'drag' | 'swipe' | 'pinch' | 'done',
                    //   timer, ax, ay (window), vk, pressed }
let swipeMode = false;

// One key press.  The release comes a moment later so a game that polls the
// key state (KINT 6 does) still sees the key down.
function tapKey(vk) {
  send(EV.KEYDOWN, vk, 0);
  setTimeout(() => send(EV.KEYUP, vk, 0), 60);
}
function swipeDir(dx, dy, min) {
  if (Math.max(Math.abs(dx), Math.abs(dy)) < min) return 0;
  return Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? VK.RIGHT : VK.LEFT) : (dy > 0 ? VK.DOWN : VK.UP);
}
function swipePress(vk, x, y) {
  tapKey(vk);
  touch.vk = vk; touch.ax = x; touch.ay = y; touch.pressed = true;
  armRepeat();
}
function armRepeat() {
  clearTimeout(touch.timer);
  const t = touch;
  t.timer = setTimeout(function rep() {
    if (touch !== t) return;
    tapKey(t.vk);
    t.timer = setTimeout(rep, REPEAT_MS);
  }, REPEAT_DELAY_MS);
}

function rightClickAt(x, y) {
  send(EV.MOUSEMOVE, x, y, 0);
  send(EV.MOUSEDOWN, 2, x, y, 2);
  send(EV.MOUSEUP, 2, x, y, 0);
  showRing(x, y);
}
function showRing(x, y) {
  const r = canvas.getBoundingClientRect(), k = r.width / canvas.width;
  const el = document.createElement('div');
  el.className = 'touch-ring';
  el.style.left = (r.left + (x + 0.5) * k) + 'px';
  el.style.top = (r.top + (y + 0.5) * k) + 'px';
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 400);
}
function endTouch() {
  if (touch) clearTimeout(touch.timer);
  touch = null;
}

// Two fingers: spread or pinch to zoom, move together to look around.  If
// they lift quickly without moving it's a two-finger tap (right click).
const TWO_TAP_MS = 600, PINCH_SLOP = 12;
const fingers = new Map();   // pointerId -> [clientX, clientY], every finger on the canvas
let pinch = null;            // { a, b, d0, mx0, my0, s0, tx0, ty0, t0, moved }
function fingerSpan() {
  const [ax, ay] = fingers.get(pinch.a), [bx, by] = fingers.get(pinch.b);
  return { d: Math.max(1, Math.hypot(bx - ax, by - ay)), mx: (ax + bx) / 2, my: (ay + by) / 2 };
}
function startPinch(id) {
  clearTimeout(touch.timer);
  touch.state = 'pinch';
  const r = canvas.getBoundingClientRect();
  pinch = { a: touch.id, b: id, s0: r.width / canvas.width, tx0: r.left, ty0: r.top,
            t0: performance.now(), moved: false };
  const { d, mx, my } = fingerSpan();
  Object.assign(pinch, { d0: d, mx0: mx, my0: my });
}
function movePinch() {
  const { d, mx, my } = fingerSpan();
  if (!pinch.moved && Math.abs(d - pinch.d0) < PINCH_SLOP &&
      Math.hypot(mx - pinch.mx0, my - pinch.my0) < PINCH_SLOP) return;
  pinch.moved = true;
  // Keep the game spot that was between the fingers between them.
  const s = pinch.s0 * d / pinch.d0;
  const gx = (pinch.mx0 - pinch.tx0) / pinch.s0, gy = (pinch.my0 - pinch.ty0) / pinch.s0;
  placeCanvas(s, mx - gx * s, my - gy * s);
}
function endPinch(lifted) {
  if (pinch.moved) {
    if (zoom.z < 1.08) zoomOut();    // nearly all the way out: snap to the whole screen
    saveZoom();
  } else if (lifted && performance.now() - pinch.t0 < TWO_TAP_MS) {
    rightClickAt(touch.x, touch.y);
  }
  pinch = null;
  touch.state = 'done';               // the other finger does nothing until it lifts
}

canvas.addEventListener('pointerdown', (e) => {
  if (e.pointerType === 'mouse') return;
  e.preventDefault();
  lastTouch = performance.now();
  fingers.set(e.pointerId, [e.clientX, e.clientY]);
  if (overlay.classList.contains('show')) return;
  audioCtx();
  try { canvas.setPointerCapture(e.pointerId); } catch {}
  if (touch) {
    // A second finger while the first is still waiting: zoom, or a two-finger tap.
    if (touch.state === 'pending' && !pinch) startPinch(e.pointerId);
    return;
  }
  if (document.activeElement !== kbd) canvas.focus();   // don't close the on-screen keyboard
  const [x, y] = pos(e);
  touch = { id: e.pointerId, x, y, cx: e.clientX, cy: e.clientY, state: 'pending', timer: 0 };
  touch.timer = setTimeout(() => {
    if (touch && touch.state === 'pending') { rightClickAt(touch.x, touch.y); touch.state = 'done'; }
  }, LONG_PRESS_MS);
});
canvas.addEventListener('pointermove', (e) => {
  if (e.pointerType === 'mouse' || !fingers.has(e.pointerId)) return;
  e.preventDefault();
  lastTouch = performance.now();
  fingers.set(e.pointerId, [e.clientX, e.clientY]);
  if (pinch) {
    if (e.pointerId === pinch.a || e.pointerId === pinch.b) movePinch();
    return;
  }
  if (!touch || e.pointerId !== touch.id) return;
  // Distances are measured on the glass (CSS pixels), whatever the zoom.
  const [x, y] = pos(e), cx = e.clientX, cy = e.clientY;
  if (touch.state === 'pending' && swipeMode && Math.hypot(cx - touch.cx, cy - touch.cy) > MOVE_SLOP) {
    clearTimeout(touch.timer);
    touch.state = 'swipe';
    touch.ax = touch.cx; touch.ay = touch.cy; touch.pressed = false;
  }
  if (touch.state === 'swipe') {
    const dx = cx - touch.ax, dy = cy - touch.ay;
    const vk = swipeDir(dx, dy, touch.pressed ? SWIPE_STEP : SWIPE_FIRST);
    if (vk) swipePress(vk, cx, cy);
    else if (touch.pressed && Math.hypot(dx, dy) > MOVE_SLOP) armRepeat();   // still moving: not a hold yet
    return;
  }
  if (touch.state === 'pending' && Math.hypot(cx - touch.cx, cy - touch.cy) > MOVE_SLOP) {
    // It's a drag: press the left button where the finger started.
    clearTimeout(touch.timer);
    touch.state = 'drag';
    send(EV.MOUSEMOVE, touch.x, touch.y, 0);
    send(EV.MOUSEDOWN, 0, touch.x, touch.y, 1);
  }
  if (touch.state === 'drag') send(EV.MOUSEMOVE, x, y, 1);
});
function touchUp(e) {
  if (e.pointerType === 'mouse') return;
  lastTouch = performance.now();
  if (!fingers.delete(e.pointerId)) return;
  e.preventDefault();
  if (pinch && (e.pointerId === pinch.a || e.pointerId === pinch.b)) endPinch(e.type === 'pointerup');
  if (!touch || e.pointerId !== touch.id) return;
  audioCtx();           // iPad only lets sound start on a finger lift
  const [x, y] = pos(e);
  if (touch.state === 'pending' && e.type === 'pointerup') {
    send(EV.MOUSEMOVE, touch.x, touch.y, 0);
    send(EV.MOUSEDOWN, 0, touch.x, touch.y, 1);
    send(EV.MOUSEUP, 0, touch.x, touch.y, 0);
  } else if (touch.state === 'drag') {
    send(EV.MOUSEUP, 0, x, y, 0);
  } else if (touch.state === 'swipe' && !touch.pressed && e.type === 'pointerup') {
    const vk = swipeDir(e.clientX - touch.ax, e.clientY - touch.ay, MOVE_SLOP);   // a short, fast flick
    if (vk) tapKey(vk);
  }
  endTouch();
}
canvas.addEventListener('pointerup', touchUp);
canvas.addEventListener('pointercancel', touchUp);
// Safari's own pinch-to-zoom of the whole page would fight ours.
document.addEventListener('gesturestart', (e) => e.preventDefault());

let wheelAcc = 0, hwheelAcc = 0;
canvas.addEventListener('wheel', (e) => {
  e.preventDefault();
  const scale = e.deltaMode === 1 ? 33 : e.deltaMode === 2 ? 400 : 1;
  const [x, y] = pos(e);
  wheelAcc += e.deltaY * scale;
  hwheelAcc += e.deltaX * scale;
  while (Math.abs(wheelAcc) >= 100) {
    const step = wheelAcc > 0 ? 1 : -1;
    wheelAcc -= step * 100;
    send(EV.WHEEL, -step, x, y);           // Windows: positive = away from the user
  }
  while (Math.abs(hwheelAcc) >= 100) {
    const step = hwheelAcc > 0 ? 1 : -1;
    hwheelAcc -= step * 100;
    send(EV.HWHEEL, step, x, y);
  }
}, { passive: false });

// --------------------------------------------------------- keyboard input
// Chrome's KeyboardEvent.keyCode values are the Windows virtual-key codes.
function keyAllowedToBrowser(e) {
  return e.metaKey || e.key === 'F12';   // keep Cmd shortcuts and DevTools working
}
window.addEventListener('keydown', (e) => {
  if (overlay.classList.contains('show')) return;
  if (keyAllowedToBrowser(e)) return;
  // The iPad's on-screen keyboard often sends no key code; its 'beforeinput' below handles those.
  if (e.target === kbd && (!e.keyCode || e.keyCode === 229 || e.key === 'Unidentified')) return;
  e.preventDefault();
  const vk = e.keyCode;
  if (!vk || vk === 91 || vk === 93) return;
  send(EV.KEYDOWN, vk, e.altKey ? 1 : 0);
  if (!e.ctrlKey && !e.altKey && e.key.length === 1) send(EV.CHAR, e.key.codePointAt(0));
});
window.addEventListener('keyup', (e) => {
  if (keyAllowedToBrowser(e)) return;
  const vk = e.keyCode;
  if (!vk || vk === 91 || vk === 93) return;
  e.preventDefault();
  send(EV.KEYUP, vk, e.altKey || vk === 18 ? 1 : 0);
});

// ------------------------------------------------- touch-screen helpers
// The ⌨ button focuses a hidden text field so the iPad shows its keyboard;
// what's typed is passed to the game as key presses.  The field keeps one
// space in it so Delete always has something to act on.
const kbd = document.getElementById('kbd');
const kbdBtn = document.getElementById('kbdBtn');
const swipeBtn = document.getElementById('swipeBtn');
const hintEl = document.getElementById('hint');
const SWIPE_PREF = 'kaser.swipe.' + GAME;

let hintTimer = 0;
function hint(text) {
  hintEl.textContent = text;
  hintEl.classList.add('show');
  clearTimeout(hintTimer);
  hintTimer = setTimeout(() => hintEl.classList.remove('show'), 1800);
}
function resetKbd() { kbd.value = ' '; try { kbd.setSelectionRange(1, 1); } catch {} }
function typeChar(ch) {
  const c = ch.toUpperCase();
  const vk = /^[A-Z0-9]$/.test(c) ? c.charCodeAt(0) : ch === ' ' ? VK.SPACE : 0;
  if (vk) send(EV.KEYDOWN, vk, 0);
  send(EV.CHAR, ch.codePointAt(0));
  if (vk) send(EV.KEYUP, vk, 0);
}

kbd.addEventListener('beforeinput', (e) => {
  e.preventDefault();
  if (overlay.classList.contains('show')) return;
  const t = e.inputType;
  if (t === 'insertText' || t === 'insertReplacementText' || t === 'insertFromPaste') {
    for (const ch of e.data || '') typeChar(ch);
  } else if (t === 'deleteContentBackward' || t === 'deleteWordBackward') {
    tapKey(VK.BACK);
  } else if (t === 'insertLineBreak' || t === 'insertParagraph') {
    tapKey(VK.ENTER);
  }
  resetKbd();
});
kbd.addEventListener('input', resetKbd);          // in case an edit slipped through
kbd.addEventListener('focus', () => { kbdBtn.classList.add('on'); resetKbd(); });
kbd.addEventListener('blur', () => kbdBtn.classList.remove('on'));
kbdBtn.addEventListener('pointerdown', (e) => e.preventDefault());   // keep focus where it is
kbdBtn.addEventListener('click', () => {
  if (document.activeElement === kbd) { kbd.blur(); canvas.focus(); }
  else { resetKbd(); kbd.focus(); }
});

function setSwipe(on, announce) {
  swipeMode = on;
  swipeBtn.classList.toggle('on', on);
  if (announce) try { localStorage.setItem(SWIPE_PREF, on ? '1' : '0'); } catch {}
  if (announce) hint(on ? 'Swipe = arrow keys (drag is off)' : 'Swipe = drag (normal)');
}
swipeBtn.addEventListener('pointerdown', (e) => e.preventDefault());
swipeBtn.addEventListener('click', () => setSwipe(!swipeMode, true));
// Games where the keys move a hero start with swipes as arrow keys; the ✥ button changes it.
const ARROW_GAMES = ["Hero's Hearts", "Hero's Friends", 'Hero Defiant'];
swipeMode = ARROW_GAMES.includes(GAME);
try { const v = localStorage.getItem(SWIPE_PREF); if (v !== null) swipeMode = v === '1'; } catch {}
setSwipe(swipeMode, false);

// ⊖ appears while zoomed in and goes back to the whole game screen.
const zoomBtn = document.getElementById('zoomBtn');
zoomBtn.addEventListener('pointerdown', (e) => e.preventDefault());
zoomBtn.addEventListener('click', zoomOut);
zoomBtn.classList.toggle('show', zoomed());

// The first time a game is shown on a phone, say how to zoom.
function firstFrame() {
  try {
    if (!isPhone || localStorage.getItem('kaser.zoomhint')) return;
    localStorage.setItem('kaser.zoomhint', '1');
  } catch { return; }
  hint('Spread two fingers to zoom in');
}

// Only touch screens get the buttons; a Mac has a real keyboard.
if (navigator.maxTouchPoints > 0) document.getElementById('touchbar').classList.add('show');

// ---------------------------------------------------------- window events
let resizeTimer = 0;
window.addEventListener('resize', () => {
  relayout();
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { const { w, h } = viewSize(); send(EV.RESIZE, w, h); }, 120);
});
window.addEventListener('blur', () => send(EV.BLUR));
window.addEventListener('focus', () => send(EV.FOCUS));
document.addEventListener('visibilitychange', () => send(EV.HIDDEN, document.hidden ? 1 : 0));
window.addEventListener('pagehide', () => send(EV.CLOSE));

start();
