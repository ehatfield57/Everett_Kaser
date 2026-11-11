// worker.js - runs one game with the KINT 5 or KINT 6 interpreter.  The
// interpreter's main loop takes over this worker completely; the page talks
// to it through a SharedArrayBuffer (input) and receives postMessage()s
// (screen, sound, title, ...).

onmessage = async (e) => {
  const m = e.data;
  if (m.t !== 'init') return;
  const moduleArg = {
    kint: {
      game: m.game,
      ring: new Int32Array(m.sab),
      ringCap: m.ringCap,
      musicEnabled: !!m.music,
      cursor: -1,
    },
    locateFile: (p) => '/web/' + p,
    print: (s) => console.log(s),
    printErr: (s) => console.error(s),
  };
  try {
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
