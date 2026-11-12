// worker.js - runs one game with the KINT 5 or KINT 6 interpreter.  The
// interpreter's main loop takes over this worker completely; the page talks
// to it through a SharedArrayBuffer (input) and receives postMessage()s
// (screen, sound, title, ...).
//
// Files come from the copy of the game kept on this device when there is one
// (m.local), otherwise from the server.

importScripts('/web/store.js', '/web/fs.js');

async function openFS(m) {
  if (!m.local) return serverFS(m.game);
  const rec = await KStore.getGame(m.game);
  if (!rec) throw new Error('This game is no longer stored on this device.');
  const [pack, saves] = await Promise.all([KStore.packFile(rec.pack), KStore.loadSaves(m.game)]);
  if (pack.size !== rec.total) throw new Error('The stored copy of this game is incomplete. Remove it and download it again.');
  return localFS(m.game, rec, pack, saves, (ops) => postMessage({ t: 'saves', ops }));
}

onmessage = async (e) => {
  const m = e.data;
  if (m.t !== 'init') return;
  try {
    const fs = await openFS(m);
    const moduleArg = {
      kint: {
        game: m.game,
        fs,
        ring: new Int32Array(m.sab),
        ringCap: m.ringCap,
        musicEnabled: !!m.music,
        cursor: -1,
      },
      locateFile: (p) => '/web/' + p,
      print: (s) => console.log(s),
      printErr: (s) => console.error(s),
    };
    const engine = m.engine === 6 ? 6 : 5;
    importScripts(`/web/kint${engine}.js`);
    const create = engine === 6 ? createKint6 : createKint5;
    const mod = await create(moduleArg);
    mod.ccall('kp_set_paths', null, ['string', 'string'], [m.pgmShown || 'pgm/', m.appShown || 'app/']);
    const rc = mod._kp_main(m.screenW, m.screenH, m.w, m.h);
    if (rc) postMessage({ t: 'crash', text: `The game could not start (code ${rc}).` });
  } catch (err) {
    postMessage({ t: 'crash', text: String((err && err.stack) || err) });
  }
};
