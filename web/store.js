// store.js - games kept on this device for offline play.  Used by the home
// page, the game page and both workers.
//
//   IndexedDB "kaser":
//     games  name -> { name, engine, pgm, app, version, total, files, dirs, pack, saved }
//            files: [[path, size, mtime], ...] in pack order; dirs: [[path, mtime], ...]
//     saves  key  -> { path, data: Uint8Array | null, dir, mtime }
//            path is relative to the saves root ("Sherlock/sherlock.ini"); key is
//            path lower-cased, because game file names are case-insensitive.
//   Origin private file system:  packs/<file>  the game's files back to back.
'use strict';

const KStore = (() => {
  let dbp = null;
  function db() {
    if (!dbp) {
      dbp = new Promise((resolve, reject) => {
        const r = indexedDB.open('kaser', 1);
        r.onupgradeneeded = () => {
          r.result.createObjectStore('games', { keyPath: 'name' });
          r.result.createObjectStore('saves');
        };
        r.onsuccess = () => resolve(r.result);
        r.onerror = () => reject(r.error);
      });
    }
    return dbp;
  }
  const done = (tx) => new Promise((res, rej) => {
    tx.oncomplete = () => res();
    tx.onerror = tx.onabort = () => rej(tx.error || new Error('storage transaction failed'));
  });
  const req = (r) => new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });

  async function getGame(name) {
    const d = await db();
    return req(d.transaction('games').objectStore('games').get(name));
  }
  async function allGames() {
    const d = await db();
    return req(d.transaction('games').objectStore('games').getAll());
  }
  async function putGame(rec) {
    const d = await db();
    const tx = d.transaction('games', 'readwrite');
    tx.objectStore('games').put(rec);
    return done(tx);
  }
  async function deleteGame(name) {
    const rec = await getGame(name);
    const d = await db();
    const tx = d.transaction('games', 'readwrite');
    tx.objectStore('games').delete(name);
    await done(tx);
    if (rec) await removePack(rec.pack);
  }

  // Saves for one game: everything under "<game>/" plus files shared by all
  // games at the top of the saves folder.
  async function loadSaves(game) {
    const d = await db();
    const st = d.transaction('saves').objectStore('saves');
    const lo = game.toLowerCase() + '/';
    const [mine, all] = await Promise.all([
      req(st.getAll(IDBKeyRange.bound(lo, lo + '￿'))),
      req(st.getAllKeys()),
    ]);
    const shared = all.filter((k) => !k.includes('/'));
    const sharedRecs = shared.length ? await Promise.all(shared.map((k) => req(d.transaction('saves').objectStore('saves').get(k)))) : [];
    return mine.concat(sharedRecs.filter(Boolean));
  }
  async function hasSaves(game) {
    const d = await db();
    const lo = game.toLowerCase() + '/';
    const n = await req(d.transaction('saves').objectStore('saves').count(IDBKeyRange.bound(lo, lo + '￿')));
    return n > 0;
  }
  // ops: [{op: 'put', rec} | {op: 'delete', key}]
  async function applySaves(ops) {
    const d = await db();
    const tx = d.transaction('saves', 'readwrite');
    const st = tx.objectStore('saves');
    for (const o of ops) {
      if (o.op === 'put') st.put(o.rec, o.rec.path.toLowerCase());
      else if (o.op === 'delete') st.delete(o.key);
    }
    return done(tx);
  }

  async function packsDir() {
    const root = await navigator.storage.getDirectory();
    return root.getDirectoryHandle('packs', { create: true });
  }
  async function packFile(name) {
    return (await (await packsDir()).getFileHandle(name)).getFile();
  }
  async function removePack(name) {
    if (!name) return;
    try { await (await packsDir()).removeEntry(name); } catch {}
  }
  // A file name for a game's pack; includes the version so an update can be
  // written next to the old copy before replacing it.
  function packName(game, version) {
    return encodeURIComponent(game).replace(/\./g, '%2E') + '_' + version + '.bin';
  }

  return { getGame, allGames, putGame, deleteGame, loadSaves, hasSaves, applySaves,
           packsDir, packFile, removePack, packName };
})();
