// download.js - copies a game from the server onto this device (a worker,
// because only workers can write files to the origin private file system
// in every browser).
//
//   in:   {game}
//   out:  {t: 'progress', done, total} ... then {t: 'done'} or {t: 'error', text}
//
// The game's files go into one pack file; the index of what is where goes
// into IndexedDB.  The first time a game is downloaded, the player's saves on
// the server are copied too, so progress carries over.
'use strict';
importScripts('/web/store.js');

onmessage = async (e) => {
  const game = e.data.game;
  let handle = null, dir = null, name = null;
  try {
    const enc = encodeURIComponent(game);
    const ires = await fetch(`/api/pack/${enc}/index`, { cache: 'no-store' });
    if (!ires.ok) throw new Error(`The server couldn't list the game's files (${ires.status}).`);
    const index = await ires.json();
    const old = await KStore.getGame(game);

    // 1. the game's files
    dir = await KStore.packsDir();
    name = KStore.packName(game, index.version);
    const fh = await dir.getFileHandle(name, { create: true });
    handle = await fh.createSyncAccessHandle();
    await handle.truncate(0);
    const res = await fetch(`/api/pack/${enc}/data?v=${index.version}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`The download failed (${res.status}).`);
    const reader = res.body.getReader();
    let at = 0, last = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      let off = 0;
      while (off < value.length) {
        const n = handle.write(value.subarray(off), { at: at + off });
        if (!n) throw new Error('This device ran out of space for the game.');
        off += n;
      }
      at += value.length;
      const now = Date.now();
      if (now - last > 150) { last = now; postMessage({ t: 'progress', done: at, total: index.total }); }
    }
    if (at !== index.total) throw new Error('The download was cut short. Please try again.');
    await handle.flush();
    await handle.close();
    handle = null;

    // 2. saves, the first time only (later the device's own saves win)
    if (!(await KStore.hasSaves(game))) {
      postMessage({ t: 'progress', done: at, total: index.total, note: 'Copying saved games…' });
      const list = await (await fetch(`/api/saves/${enc}`, { cache: 'no-store' })).json();
      const ops = [];
      for (const f of list) {
        const r = await fetch(`/api/g/${enc}/file?p=${encodeURIComponent(f.p)}`, { cache: 'no-store' });
        if (!r.ok) continue;
        const data = new Uint8Array(await r.arrayBuffer());
        ops.push({ op: 'put', rec: { path: game + '/' + f.p.slice(4), data, dir: false, mtime: f.mtime } });
      }
      if (ops.length) await KStore.applySaves(ops);
    }

    // 3. the index; only now does the new copy replace the old one
    await KStore.putGame({
      name: game, engine: index.engine, beta: index.beta, pgm: index.pgm, app: index.app,
      version: index.version, total: index.total, files: index.files, dirs: index.dirs,
      pack: name, saved: Date.now(),
    });
    if (old && old.pack !== name) await KStore.removePack(old.pack);
    postMessage({ t: 'done' });
  } catch (err) {
    if (handle) { try { await handle.close(); } catch {} }
    const current = await KStore.getGame(game).catch(() => null);
    if (dir && name && (!current || current.pack !== name)) { try { await dir.removeEntry(name); } catch {} }
    postMessage({ t: 'error', text: (err && err.message) || String(err) });
  }
};
