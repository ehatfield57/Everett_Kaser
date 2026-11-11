// worker.js - runs one KINT 5 game.  The interpreter's main loop takes over
// this worker completely; the page talks to it through a SharedArrayBuffer
// (input) and receives postMessage()s (screen, sound, title, ...).
importScripts('/web/kint5.js');

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
    const mod = await createKint5(moduleArg);
    const rc = mod._kp_main(m.screenW, m.screenH, m.w, m.h);
    if (rc) postMessage({ t: 'crash', text: `The game could not start (code ${rc}).` });
  } catch (err) {
    postMessage({ t: 'crash', text: String((err && err.stack) || err) });
  }
};
