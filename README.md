# Everett Kaser games in Chrome

Runs your own copies of Everett Kaser's games in a browser tab. The games'
own program files (`MAIN.KE`) are run by Everett's KINT 5 and KINT 6
interpreters, compiled to WebAssembly, with a small local Python server
supplying the game files and storing your saves.

All 40 games work: 37 on KINT 5, plus Crocotile, Lair of Moriarty and
Occam's Quilt on KINT 6.

## Playing

Start the server from this folder:

```
python3 server.py --open
```

`--open` opens the launcher in Chrome. Otherwise go to <http://localhost:8765>
yourself. Leave the Terminal window open while you play; press **Ctrl+C** in it
to stop the server.

Tips:

- **Quit with the game's own Exit menu.** That's when most games save your
  settings, statistics and unfinished puzzle. Closing the tab may lose them.
  Exit takes you back to the game list.
- **Sound and music start after your first click** in a game, because Chrome
  doesn't allow a page to play sound before you've interacted with it.
- **Window size:** the game fills the browser tab and redraws when you resize
  it. For full screen use Chrome's **View → Enter Full Screen** (⌃⌘F).
- **Keys:** the games use Windows-style shortcuts, so use **Ctrl** where a game
  says Ctrl; **Cmd** shortcuts are left to Chrome. Right-click works as usual
  (two-finger click on a trackpad).
- **Not available:** printing, and pasting from the clipboard into a game.

Server options: `--port 9000` to use another port, `--verbose` to log every
file request (handy if a game misbehaves).

## Your saves

Everything a game writes goes into `saves/<game name>/`, using the same file
layout as the native Mac apps. Files the games ship with are never modified.

- **Back up:** copy the `saves` folder.
- **Start a game afresh:** delete its folder in `saves/` (or rename it to keep
  a copy).
- **Bring over progress from the native Mac apps:** they keep their saves in
  `~/Library/Application Support/Everett Kaser Software/`. To copy them in:

  ```
  python3 tools/import_native_saves.py --dry-run   # see what would be copied
  python3 tools/import_native_saves.py             # copy (never overwrites)
  python3 tools/import_native_saves.py --overwrite --game Sherlock
  ```

  `--overwrite` replaces the browser saves, keeping a `.bak` copy of each
  replaced file. The native files are never changed. The browser and native
  versions keep separate progress after that.

Some games also keep resized copies of their artwork (`SIZED_*.bmp`) in their
save folder, as the Mac versions do. These are caches and are safe to delete.

## Adding a game

The launcher lists every `.app` bundle in `games/`. These are links to the
installed apps, so to add one:

```
ln -s "/path/to/Some Game LIC.app" games/
```

Then restart the server. The interpreter (KINT 5 or 6) is chosen automatically
from the game's `MAIN.KE` file.

## Rebuilding from scratch

The built interpreters (`web/kint5.*`, `web/kint6.*`) and Everett's source are
not in git, so after a fresh clone, or to change the interpreter code:

1. Download `MSKINT50.ZIP` and `KINT_6_3_0.zip` from
   <https://kaser.com/kint.html> into this folder.
2. Unpack them into `kint_src/`:
   `python3 tools/extract_kint.py`
3. Build both interpreters (needs [Emscripten](https://emscripten.org),
   e.g. `brew install emscripten`):
   `engine/build.sh` (or `engine/build.sh debug` for a slower build with
   extra safety checks)

The music synthesizer in `web/vendor/` is committed, so it only needs
rebuilding to change its version: `cd tools/music-bundle && npm install && npm run build`.

## How it fits together

```
Chrome tab (web/play.html, play.js)        Web Worker (web/worker.js)
  shows the screen, plays sound/music  <--   runs kint5.wasm or kint6.wasm:
  sends mouse/keyboard input           -->   Everett's interpreter + our
                                             platform layer
                                                    |  file reads/writes
                                                    v
                              server.py: game files from games/*.app,
                                         your files in saves/
```

| Path | What it is |
|---|---|
| `server.py` | Local web server (127.0.0.1 only; Python standard library only) |
| `web/` | Launcher (`index.html`), game page (`play.html`, `play.js`), worker, built interpreters |
| `engine/patch_k5.py`, `patch_k6.py` | Copy Everett's source from `kint_src/` and apply the small web-port patches into `engine/k5/gen/` and `engine/k6/gen/` |
| `engine/k5/kplat.c`, `engine/k6/kplat6.c` | Browser platform layers (they replace Everett's Windows `main.c`) |
| `engine/k5/kint_lib.js` | JavaScript side of the platform layer, shared by both interpreters |
| `engine/build.sh` | Builds both interpreters |
| `web/vendor/` | SpessaSynth MIDI synthesizer (Apache-2.0) |
| `tools/cdp.mjs` | Drives a headless Chrome for automated checks (see below) |
| `tools/import_native_saves.py`, `extract_kint.py` | Helpers described above |

Music is played by SpessaSynth using macOS's built-in General MIDI sound bank
(`gs_instruments.dls`), the same one native Mac apps use.

## Checking that a game starts

`tools/cdp.mjs` opens a page in a hidden Chrome, follows a list of steps and
saves screenshots, for example:

```
echo '[{"wait":8000},{"shot":"start"},{"eval":"document.title"}]' > /tmp/steps.json
node tools/cdp.mjs "http://localhost:8765/play?g=Sherlock" /tmp/out /tmp/steps.json
```

Steps can also be `{"click":[x,y]}` (add `"button":"right"` for a right-click)
and `{"key":"a"}`. Clicks and key presses really happen in the game, so they
can change your saves.

## Troubleshooting

- **"This page must be served by server.py"**: open the game through
  <http://localhost:8765>, not as a file.
- **"Address already in use"**: the server is already running (perhaps in
  another Terminal window), or use `--port`.
- **No sound or music**: click inside the game once. Also check the game's own
  music and sound settings (usually under the Player menu); they come over
  from the native app if you imported its saves.
- **"The game stopped unexpectedly"**: note what you were doing, and use
  **Restart**. Running the server with `--verbose` and rebuilding with
  `engine/build.sh debug` gives more detail.

## License note

The KINT interpreter source is © Everett Kaser and licensed for personal use
only. Don't redistribute this port with his code, the KINT source, the built
interpreters, or the games' `MAIN.KE` files. `.gitignore` keeps all of those
out of this repository, so it contains only the port's own code.
