// fs.js - where a running game's files come from.  Runs in the game worker,
// whose interpreter never yields, so every call here is synchronous.
//
// Paths are KINT paths: "pgm/..." is the game's own (read-only) folder and
// "app/..." its save folder; "app/../x" is shared by all games.  Names are
// case-insensitive, as on Windows.
//
// Both file systems implement:
//   read(path)        -> Uint8Array | null
//   stat(path)        -> {size, mtime, dir} | null
//   list(pattern)     -> [{name, dir}]       e.g. "pgm/PUZZLES/*.puz"
//   write(path, data) -> bool                (app/ only)
//   mkdir/rmdir/remove(path) -> bool
//   rename(from, to)  -> bool
'use strict';

// ------------------------------------------------- the local Python server
function serverFS(game) {
  const api = (op, path) => `/api/g/${encodeURIComponent(game)}/${op}?p=${encodeURIComponent(path)}`;
  function get(op, path, binary) {
    const xhr = new XMLHttpRequest();
    xhr.open('GET', api(op, path), false);
    if (binary) xhr.responseType = 'arraybuffer';
    try { xhr.send(); } catch { return null; }
    if (xhr.status !== 200) return null;
    return binary ? new Uint8Array(xhr.response) : xhr.responseText;
  }
  function send(method, url, body) {
    const xhr = new XMLHttpRequest();
    xhr.open(method, url, false);
    try { xhr.send(body || null); } catch { return false; }
    return xhr.status === 200;
  }
  return {
    read: (p) => get('file', p, true),
    stat: (p) => { const r = get('stat', p, false); return r ? JSON.parse(r) : null; },
    list: (p) => { const r = get('list', p, false); return r ? JSON.parse(r) : []; },
    write: (p, data) => send('PUT', api('file', p), data),
    mkdir: (p) => send('POST', api('mkdir', p)),
    rmdir: (p) => send('POST', api('rmdir', p)),
    remove: (p) => send('POST', api('delete', p)),
    rename: (from, to) => send('POST', api('rename', from) + '&to=' + encodeURIComponent(to)),
  };
}

// --------------------------------------------- a copy kept on this device
// rec:   the game's record from KStore (file index of the pack)
// pack:  File holding the game's files back to back (read with FileReaderSync)
// saves: records from KStore.loadSaves()
// persist(ops): hands changes to the page, which writes them to IndexedDB
//   (this worker can't wait for IndexedDB while the game runs).
function localFS(game, rec, pack, saves, persist) {
  const reader = new FileReaderSync();
  const now = () => Math.floor(Date.now() / 1000);

  // game files: lower-case path -> entry
  const pgmFiles = new Map(), pgmDirs = new Map([['', { mtime: 0 }]]), pgmKids = new Map();
  const addKid = (kids, dirKey, name, dir) => {
    let a = kids.get(dirKey);
    if (!a) kids.set(dirKey, a = []);
    a.push({ name, dir });
  };
  for (const [path, mtime] of rec.dirs) {
    pgmDirs.set(path.toLowerCase(), { mtime });
    const i = path.lastIndexOf('/');
    addKid(pgmKids, path.slice(0, i < 0 ? 0 : i).toLowerCase(), path.slice(i + 1), true);
  }
  let off = 0;
  for (const [path, size, mtime] of rec.files) {
    pgmFiles.set(path.toLowerCase(), { off, size, mtime });
    off += size;
    const i = path.lastIndexOf('/');
    addKid(pgmKids, path.slice(0, i < 0 ? 0 : i).toLowerCase(), path.slice(i + 1), false);
  }

  // saved files: lower-case path (from the saves root) -> {path, data, dir, mtime}
  const app = new Map();
  for (const s of saves) app.set(s.path.toLowerCase(), s);
  const gameKey = game.toLowerCase();

  // Split a KINT path into its tree and the path inside it.  ".." never leaves
  // the game folder (pgm) or the saves folder (app).
  function parse(kpath) {
    const parts = kpath.replace(/\\/g, '/').split('/');
    const root = parts.shift();
    let stack;
    if (root === 'pgm') stack = [];
    else if (root === 'app') stack = [game];
    else return null;
    for (const p of parts) {
      if (p === '' || p === '.') continue;
      if (p === '..') { stack.pop(); continue; }
      if (p.startsWith('.') || p.includes('\0')) return null;
      stack.push(p);
    }
    return { root, parts: stack, key: stack.join('/').toLowerCase() };
  }

  const appIsDir = (key) => {
    if (key === '' || key === gameKey) return true;
    const e = app.get(key);
    if (e) return !!e.dir;
    const pre = key + '/';
    for (const k of app.keys()) if (k.startsWith(pre)) return true;
    return false;
  };
  // The real spelling of an app/ path, keeping existing names' case.
  function appRealPath(parts) {
    const out = [];
    for (let i = 0; i < parts.length; i++) {
      const key = parts.slice(0, i + 1).join('/').toLowerCase();
      const e = app.get(key);
      if (e) { out.push(e.path.split('/')[i]); continue; }
      let name = parts[i];
      if (i === 0 && key === gameKey) name = game;
      else {
        const pre = key + '/';
        for (const [k, v] of app) if (k.startsWith(pre)) { name = v.path.split('/')[i]; break; }
      }
      out.push(name);
    }
    return out.join('/');
  }
  function store(rec) {
    app.set(rec.path.toLowerCase(), rec);
    persist([{ op: 'put', rec }]);
  }
  // Make the folders above an app/ path exist, as the server does.
  function ensureParents(parts) {
    for (let i = 1; i < parts.length; i++) {
      const key = parts.slice(0, i).join('/').toLowerCase();
      if (key === gameKey || appIsDir(key)) continue;
      store({ path: appRealPath(parts.slice(0, i)), data: null, dir: true, mtime: now() });
    }
  }

  function globRe(pattern) {
    let re = '';
    for (const c of pattern) {
      re += c === '*' ? '.*' : c === '?' ? '.' : /[\w]/.test(c) ? c : '\\' + c;
    }
    return new RegExp('^' + re + '$', 'i');
  }

  return {
    read(kpath) {
      const p = parse(kpath);
      if (!p) return null;
      if (p.root === 'app') {
        const e = app.get(p.key);
        return e && !e.dir ? e.data.slice() : null;
      }
      const f = pgmFiles.get(p.key);
      if (!f) return null;
      return new Uint8Array(reader.readAsArrayBuffer(pack.slice(f.off, f.off + f.size)));
    },
    stat(kpath) {
      const p = parse(kpath);
      if (!p) return null;
      if (p.root === 'app') {
        const e = app.get(p.key);
        if (e) return { size: e.dir ? 0 : e.data.length, mtime: e.mtime, dir: !!e.dir };
        return appIsDir(p.key) ? { size: 0, mtime: 0, dir: true } : null;
      }
      const f = pgmFiles.get(p.key);
      if (f) return { size: f.size, mtime: f.mtime, dir: false };
      const d = pgmDirs.get(p.key);
      return d ? { size: 0, mtime: d.mtime, dir: true } : null;
    },
    list(kpath) {
      const norm = kpath.replace(/\\/g, '/');
      const i = norm.lastIndexOf('/');
      if (i < 0) return [];
      const pattern = norm.slice(i + 1);
      const p = parse(norm.slice(0, i));
      if (!p) return [];
      let entries;
      if (p.root === 'pgm') {
        if (!pgmDirs.has(p.key)) return [];
        entries = pgmKids.get(p.key) || [];
      } else {
        if (!appIsDir(p.key)) return [];
        const seen = new Map(), pre = p.key ? p.key + '/' : '', depth = p.parts.length;
        for (const [k, e] of app) {
          if (!k.startsWith(pre)) continue;
          const segs = e.path.split('/');
          const name = segs[depth];
          if (!name || seen.has(name.toLowerCase())) continue;
          seen.set(name.toLowerCase(), { name, dir: segs.length > depth + 1 || !!e.dir });
        }
        entries = [...seen.values()];
      }
      const all = pattern === '*' || pattern === '*.*';
      const re = all ? null : globRe(pattern);
      return entries
        .filter((e) => !e.name.startsWith('.') && (all || re.test(e.name)))
        .sort((a, b) => (a.name.toLowerCase() < b.name.toLowerCase() ? -1 : a.name.toLowerCase() > b.name.toLowerCase() ? 1 : 0));
    },
    write(kpath, data) {
      const p = parse(kpath);
      if (!p || p.root !== 'app' || !p.parts.length) return false;
      if (appIsDir(p.key) && !app.get(p.key)?.data) return false;
      ensureParents(p.parts);
      store({ path: appRealPath(p.parts), data: new Uint8Array(data), dir: false, mtime: now() });
      return true;
    },
    mkdir(kpath) {
      const p = parse(kpath);
      if (!p || p.root !== 'app' || !p.parts.length) return false;
      if (app.has(p.key) && !app.get(p.key).dir) return false;
      ensureParents(p.parts);
      if (!appIsDir(p.key)) store({ path: appRealPath(p.parts), data: null, dir: true, mtime: now() });
      return true;
    },
    rmdir(kpath) {
      const p = parse(kpath);
      if (!p || p.root !== 'app' || !appIsDir(p.key)) return false;
      const pre = p.key + '/';
      for (const k of app.keys()) if (k.startsWith(pre)) return false;   // not empty
      if (app.delete(p.key)) persist([{ op: 'delete', key: p.key }]);
      return true;
    },
    remove(kpath) {
      const p = parse(kpath);
      if (!p || p.root !== 'app') return false;
      const e = app.get(p.key);
      if (!e || e.dir) return false;
      app.delete(p.key);
      persist([{ op: 'delete', key: p.key }]);
      return true;
    },
    rename(from, to) {
      const a = parse(from), b = parse(to);
      if (!a || !b || a.root !== 'app' || b.root !== 'app' || !b.parts.length) return false;
      if (!app.has(a.key) && !appIsDir(a.key)) return false;
      const dst = appRealPath(b.parts);
      ensureParents(b.parts);
      const ops = [];
      // move the entry itself and, for a folder, everything inside it
      const moves = [];
      for (const [k, e] of app) {
        if (k === a.key || k.startsWith(a.key + '/')) moves.push([k, e]);
      }
      // replacing a file at the destination, as os.replace does
      const old = app.get(b.key);
      if (old && !old.dir && b.key !== a.key) { app.delete(b.key); ops.push({ op: 'delete', key: b.key }); }
      const cut = a.parts.join('/').length;
      for (const [k, e] of moves) {
        app.delete(k);
        ops.push({ op: 'delete', key: k });
      }
      for (const [, e] of moves) {
        const rec = { ...e, path: dst + e.path.slice(cut) };
        app.set(rec.path.toLowerCase(), rec);
        ops.push({ op: 'put', rec });
      }
      persist(ops);
      return true;
    },
  };
}
