// kint_lib.js - JavaScript side of the KINT web platform layer.
//
// Runs inside the game's Web Worker.  The C main loop never yields back to
// the browser, so everything here is synchronous:
//   * input arrives through a SharedArrayBuffer ring written by the page
//   * files are fetched from the local Python server with synchronous XHR
//   * screen updates, sounds and other UI requests are posted to the page
//
// Module.kint (set up in worker.js) holds the shared state.

addToLibrary({
  $K__deps: ['$UTF8ToString', '$stringToUTF8'],
  $K: {
    files: new Map(),     // handle -> {data, pos, len, writable, path, dirty}
    nextHandle: 3,
    cache: new Map(),     // read-only game file cache: path -> Uint8Array|null
    found: [],
    sleepI32: null,
    sf: null,             // system-font state

    api(op, path) {
      return `/api/g/${encodeURIComponent(Module.kint.game)}/${op}?p=${encodeURIComponent(path)}`;
    },
    httpGet(op, path, binary) {
      const xhr = new XMLHttpRequest();
      xhr.open('GET', K.api(op, path), false);
      if (binary) xhr.responseType = 'arraybuffer';
      xhr.send();
      if (xhr.status !== 200) return null;
      return binary ? new Uint8Array(xhr.response) : xhr.responseText;
    },
    httpSend(method, op, path, body) {
      const xhr = new XMLHttpRequest();
      xhr.open(method, K.api(op, path), false);
      xhr.send(body || null);
      return xhr.status === 200;
    },
    // Read a whole file. Game files (pgm/) never change, so they are cached.
    readFile(path) {
      const cacheable = path.startsWith('pgm/');
      if (cacheable && K.cache.has(path)) return K.cache.get(path);
      const data = K.httpGet('file', path, true);
      if (cacheable) K.cache.set(path, data);
      return data;
    },
    str(ptr) { return ptr ? UTF8ToString(ptr) : null; },
    post(msg, transfer) { postMessage(msg, transfer || []); },
  },

  // ---------------------------------------------------------------- input
  js_poll_input__deps: ['$K', 'kp_event'],
  js_poll_input: function () {
    const ring = Module.kint.ring;           // Int32Array over the shared buffer
    const CAP = Module.kint.ringCap, SZ = 6, BASE = 8;
    let tail = Atomics.load(ring, 1);
    const head = Atomics.load(ring, 0);
    while (tail !== head) {
      const o = BASE + (tail % CAP) * SZ;
      const type = ring[o];
      tail++;
      // collapse runs of mouse moves into the last one, as Windows does
      if (type === 1 && tail !== head && ring[BASE + (tail % CAP) * SZ] === 1) continue;
      _kp_event(type, ring[o + 1], ring[o + 2], ring[o + 3], ring[o + 4]);
    }
    Atomics.store(ring, 1, tail);
  },
  js_input_pending: function () {
    const ring = Module.kint.ring;
    return Atomics.load(ring, 0) !== Atomics.load(ring, 1) ? 1 : 0;
  },
  js_wait: function (ms) {
    const ring = Module.kint.ring;
    const head = Atomics.load(ring, 0);
    if (head !== Atomics.load(ring, 1)) return;
    Atomics.wait(ring, 0, head, ms < 0 ? Infinity : ms);
  },
  js_sleep__deps: ['$K'],
  js_sleep: function (ms) {
    if (!K.sleepI32) K.sleepI32 = new Int32Array(new SharedArrayBuffer(4));
    if (ms > 0) Atomics.wait(K.sleepI32, 0, 0, ms);
  },

  // --------------------------------------------------------------- screen
  js_post_frame__deps: ['$K'],
  js_post_frame: function (ptr, x, y, w, h, cw, ch) {
    const buf = HEAPU8.slice(ptr, ptr + w * h * 4).buffer;
    K.post({ t: 'frame', x, y, w, h, cw, ch, buf }, [buf]);
  },

  // ---------------------------------------------------------------- files
  js_fopen__deps: ['$K'],
  js_fopen: function (appPtr, pgmPtr, oflags) {
    const app = K.str(appPtr), pgm = K.str(pgmPtr);
    let data, writable = false, created = false;
    if ((oflags & 3) === 0) {                         // read only
      data = K.httpGet('file', app, true) || K.readFile(pgm);
    } else {
      writable = true;
      if (oflags & 0x200) {                           // create / truncate
        data = new Uint8Array(0);
        created = true;
      } else {
        data = K.httpGet('file', app, true);
        if (!data) { data = K.readFile(pgm); created = !!data; }
      }
    }
    if (!data) return -1;
    const h = K.nextHandle++;
    const buf = new Uint8Array(Math.max(data.length, 16));
    buf.set(data);
    K.files.set(h, { buf, len: data.length, pos: 0, writable, path: app, dirty: created });
    return h;
  },
  js_fread__deps: ['$K'],
  js_fread: function (h, ptr, n) {
    const f = K.files.get(h);
    if (!f) return -1;
    n = Math.max(0, Math.min(n >>> 0, f.len - f.pos));
    HEAPU8.set(f.buf.subarray(f.pos, f.pos + n), ptr);
    f.pos += n;
    return n;
  },
  js_fwrite__deps: ['$K'],
  js_fwrite: function (h, ptr, n) {
    const f = K.files.get(h);
    if (!f || !f.writable) return -1;
    n = n >>> 0;
    const end = f.pos + n;
    if (end > f.buf.length) {
      const nb = new Uint8Array(Math.max(end, f.buf.length * 2));
      nb.set(f.buf.subarray(0, f.len));
      f.buf = nb;
    }
    f.buf.set(HEAPU8.subarray(ptr, ptr + n), f.pos);
    f.pos = end;
    if (end > f.len) f.len = end;
    f.dirty = true;
    return n;
  },
  js_fseek__deps: ['$K'],
  js_fseek: function (h, off, origin) {
    const f = K.files.get(h);
    if (!f) return -1;
    const base = origin === 0 ? 0 : origin === 1 ? f.pos : f.len;
    const p = base + off;
    if (p < 0) return -1;
    f.pos = p;
    return p;
  },
  js_feof__deps: ['$K'],
  js_feof: function (h) {
    const f = K.files.get(h);
    if (!f) return -1;
    return f.pos >= f.len ? 1 : 0;
  },
  js_fclose__deps: ['$K'],
  js_fclose: function (h) {
    const f = K.files.get(h);
    if (!f) return;
    K.files.delete(h);
    if (f.writable && f.dirty) {
      if (!K.httpSend('PUT', 'file', f.path, f.buf.slice(0, f.len))) {
        console.error('KINT: failed to save', f.path);
      }
    }
  },
  js_fstat__deps: ['$K'],
  js_fstat: function (appPtr, pgmPtr, mtimePtr, typPtr) {
    for (const p of [K.str(appPtr), K.str(pgmPtr)]) {
      const r = K.httpGet('stat', p, false);
      if (r) {
        const s = JSON.parse(r);
        HEAPU32[mtimePtr >> 2] = s.mtime >>> 0;
        HEAPU8[typPtr] = s.dir ? 2 : 1;
        return s.dir ? 0 : s.size;
      }
    }
    return -1;
  },
  js_find__deps: ['$K'],
  js_find: function (appPtr, pgmPtr, stripExt) {
    const seen = new Set();
    K.found = [];
    [[K.str(appPtr), 1], [K.str(pgmPtr), 0]].forEach(([p, isApp]) => {
      const r = K.httpGet('list', p, false);
      if (!r) return;
      for (const e of JSON.parse(r)) {
        let name = e.name;
        if (stripExt) { const i = name.lastIndexOf('.'); if (i > 0) name = name.slice(0, i); }
        const key = name.toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        K.found.push({ name, attrib: e.dir ? 0x10 : 0x20, app: isApp });
      }
    });
    return K.found.length;
  },
  js_find_get__deps: ['$K'],
  js_find_get: function (i, bufPtr, attribPtr, appPtr) {
    const e = K.found[i];
    stringToUTF8(e.name, bufPtr, 260);
    HEAPU8[attribPtr] = e.attrib;
    HEAPU8[appPtr] = e.app;
  },
  js_mkdir__deps: ['$K'],
  js_mkdir: function (p) { return K.httpSend('POST', 'mkdir', K.str(p)) ? 1 : 0; },
  js_rmdir__deps: ['$K'],
  js_rmdir: function (p) { K.httpSend('POST', 'rmdir', K.str(p)); },
  js_delete__deps: ['$K'],
  js_delete: function (p) { K.httpSend('POST', 'delete', K.str(p)); },

  // ---------------------------------------------------------- sound/music
  js_sound_file__deps: ['$K'],
  js_sound_file: function (p) {
    const data = K.readFile(K.str(p));
    if (data) K.post({ t: 'sound', bytes: data.slice().buffer, nostop: 0 });
  },
  js_sound_mem__deps: ['$K'],
  js_sound_mem: function (ptr, len, nostop) {
    if (!ptr) { K.post({ t: 'soundstop' }); return; }
    if (!len) {   // length unknown: read it from the RIFF header
      len = HEAPU32[(ptr + 4) >> 2] + 8;
    }
    K.post({ t: 'sound', bytes: HEAPU8.slice(ptr, ptr + len).buffer, nostop });
  },
  js_music_play__deps: ['$K'],
  js_music_play: function (p) {
    if (!Module.kint.musicEnabled) return 0;
    const data = K.readFile(K.str(p));
    if (!data) return 0;
    K.post({ t: 'music', bytes: data.slice().buffer });
    return 1;
  },
  js_music_stop__deps: ['$K'],
  js_music_stop: function () { K.post({ t: 'musicstop' }); },
  js_music_pause__deps: ['$K'],
  js_music_pause: function (pause) { K.post({ t: 'musicpause', pause }); },

  // ----------------------------------------------------------------- misc
  js_set_title__deps: ['$K'],
  js_set_title: function (p) { K.post({ t: 'title', text: K.str(p) }); },
  js_set_cursor__deps: ['$K'],
  js_set_cursor: function (c) {
    if (Module.kint.cursor !== c) { Module.kint.cursor = c; K.post({ t: 'cursor', c }); }
  },
  js_message__deps: ['$K'],
  js_message: function (p) { const text = K.str(p); console.warn('KINT:', text); K.post({ t: 'message', text }); },
  js_clipboard_set__deps: ['$K'],
  js_clipboard_set: function (p) { K.post({ t: 'clipboard', text: K.str(p) }); },
  js_exit__deps: ['$K'],
  js_exit: function () { K.post({ t: 'exit' }); },

  // --------------------------------------------------------- system fonts
  // Mimics the Windows build: the largest font whose cell height (ascent +
  // descent of "Йy") is less than the requested height.
  js_sysfont_prepare__deps: ['$K'],
  js_sysfont_prepare: function (textPtr, h, flags) {
    if (!K.sf) {
      const canvas = new OffscreenCanvas(2048, 64);
      K.sf = { canvas, ctx: canvas.getContext('2d', { willReadFrequently: true }), fonts: new Map() };
    }
    const sf = K.sf;
    const key = h + ':' + flags;
    let f = sf.fonts.get(key);
    if (!f) {
      const family = (flags & 1) ? '"Courier New", Courier, monospace'
        : (flags & 16) ? '"Times New Roman", Times, serif'
        : 'Tahoma, Verdana, "Segoe UI", sans-serif';
      const style = ((flags & 4) ? 'italic ' : '') + ((flags & 2) ? 'bold ' : '');
      const spec = (pt) => `${style}${Math.floor(pt * 96 / 72)}px ${family}`;
      const probe = (pt) => {
        sf.ctx.font = spec(pt);
        const m = sf.ctx.measureText('Ѝy');
        return { cx: m.width, cy: Math.ceil(m.fontBoundingBoxAscent) + Math.ceil(m.fontBoundingBoxDescent) };
      };
      let i = 8, s;
      do { ++i; s = probe(i); } while (!(s.cx >= 2048 || s.cy >= h) && i < 400);
      do { --i; s = probe(i); } while (!(i <= 4 || (s.cx < 2048 && s.cy < h)));
      sf.ctx.font = spec(i);
      const m = sf.ctx.measureText('Ѝy');
      f = { font: spec(i), ascent: Math.ceil(m.fontBoundingBoxAscent), underline: !!(flags & 8), px: Math.floor(i * 96 / 72) };
      sf.fonts.set(key, f);
    }
    sf.cur = f;
    sf.text = UTF8ToString(textPtr);
    sf.ctx.font = f.font;
    sf.widths = new Map();
    return sf.text.length;
  },
  js_sysfont_width__deps: ['$K'],
  js_sysfont_width: function (n) {
    const sf = K.sf;
    let w = sf.widths.get(n);
    if (w === undefined) {
      w = n <= 0 ? 0 : Math.round(sf.ctx.measureText(sf.text.substring(0, n)).width);
      sf.widths.set(n, w);
    }
    return w;
  },
  js_sysfont_char__deps: ['$K'],
  js_sysfont_char: function (i) { return K.sf.text.charCodeAt(i) || 0; },
  js_sysfont_draw__deps: ['$K'],
  js_sysfont_draw: function (bits, linelen, bw, bh, n, fclr) {
    const sf = K.sf;
    if (sf.canvas.width < bw || sf.canvas.height < bh) {
      sf.canvas.width = Math.max(sf.canvas.width, bw);
      sf.canvas.height = Math.max(sf.canvas.height, bh);
    }
    const ctx = sf.ctx;
    // copy the work bitmap (24-bit BGR) into the canvas
    const img = ctx.createImageData(bw, bh);
    const d = img.data;
    for (let y = 0; y < bh; y++) {
      let s = bits + y * linelen, o = y * bw * 4;
      for (let x = 0; x < bw; x++, s += 3, o += 4) {
        d[o] = HEAPU8[s + 2]; d[o + 1] = HEAPU8[s + 1]; d[o + 2] = HEAPU8[s]; d[o + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    ctx.save();
    ctx.beginPath(); ctx.rect(0, 0, bw, bh); ctx.clip();
    ctx.font = sf.cur.font;
    ctx.textBaseline = 'alphabetic';
    const r = fclr & 255, g = (fclr >>> 8) & 255, b = (fclr >>> 16) & 255;
    ctx.fillStyle = `rgb(${r},${g},${b})`;
    const text = sf.text.substring(0, n);
    ctx.fillText(text, 0, sf.cur.ascent);
    if (sf.cur.underline) {
      const lw = Math.max(1, Math.round(sf.cur.px / 14));
      ctx.fillRect(0, sf.cur.ascent + lw, Math.round(ctx.measureText(text).width), lw);
    }
    ctx.restore();
    // and back again
    const out = ctx.getImageData(0, 0, bw, bh).data;
    for (let y = 0; y < bh; y++) {
      let s = bits + y * linelen, o = y * bw * 4;
      for (let x = 0; x < bw; x++, s += 3, o += 4) {
        HEAPU8[s] = out[o + 2]; HEAPU8[s + 1] = out[o + 1]; HEAPU8[s + 2] = out[o];
      }
    }
  },
});
