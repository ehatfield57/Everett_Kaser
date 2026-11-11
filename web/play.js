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
             CHAR: 8, RESIZE: 9, BLUR: 10, MUSICDONE: 11, CLOSE: 12, HIDDEN: 13 };
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
function backToGames() { location.href = '/'; }

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
function viewSize() {
  return { w: Math.max(1, Math.floor(window.innerWidth)), h: Math.max(1, Math.floor(window.innerHeight)) };
}
function sizeCanvas(w, h) {
  if (canvas.width === w && canvas.height === h) return;
  canvas.width = w;
  canvas.height = h;
  canvas.style.width = w + 'px';
  canvas.style.height = h + 'px';
}

// ----------------------------------------------------------------- worker
const worker = new Worker('/web/worker.js');
worker.onerror = (e) => showCrash(e.message || 'worker error');
worker.onmessage = (e) => {
  const m = e.data;
  switch (m.t) {
    case 'frame':
      if (statusEl) statusEl.remove();
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
    case 'clipboard': navigator.clipboard?.writeText(m.text).catch(() => {}); break;
    case 'message':
      showBox(`<p>${escapeHtml(m.text)}</p>`, [button('OK', hideBox, true)]);
      break;
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
    showCrash('This page must be served by server.py (it needs cross-origin isolation for SharedArrayBuffer).');
    return;
  }
  document.title = GAME;
  let info = {};
  try { info = await (await fetch('/api/info/' + encodeURIComponent(GAME))).json(); } catch {}
  const sab = new SharedArrayBuffer((BASE + RING_CAP * EV_SIZE) * 4);
  ring = new Int32Array(sab);
  const { w, h } = viewSize();
  sizeCanvas(w, h);
  worker.postMessage({ t: 'init', game: GAME, sab, ringCap: RING_CAP, music: true,
                       pgmShown: info.pgm, appShown: info.app,
                       screenW: screen.width, screenH: screen.height, w, h });
  canvas.focus();
}

// ------------------------------------------------------------ mouse input
// Windows MK_ flags for wParam
function mouseFlags(e) {
  return (e.buttons & 1 ? 1 : 0) | (e.buttons & 2 ? 2 : 0) | (e.shiftKey ? 4 : 0) |
         (e.ctrlKey ? 8 : 0) | (e.buttons & 4 ? 0x10 : 0);
}
function pos(e) {
  const r = canvas.getBoundingClientRect();
  return [Math.floor(e.clientX - r.left), Math.floor(e.clientY - r.top)];
}
const BTN = { 0: 0, 1: 1, 2: 2 };      // DOM button -> left/middle/right
let buttonsDown = 0;

canvas.addEventListener('mousedown', (e) => {
  if (overlay.classList.contains('show')) return;
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
  const [x, y] = pos(e);
  send(EV.MOUSEMOVE, x, y, mouseFlags(e));
});
canvas.addEventListener('contextmenu', (e) => e.preventDefault());

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

// ---------------------------------------------------------- window events
let resizeTimer = 0;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { const { w, h } = viewSize(); send(EV.RESIZE, w, h); }, 120);
});
window.addEventListener('blur', () => send(EV.BLUR));
document.addEventListener('visibilitychange', () => send(EV.HIDDEN, document.hidden ? 1 : 0));
window.addEventListener('pagehide', () => send(EV.CLOSE));

start();
