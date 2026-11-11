# Everett Kaser games in Chrome

Runs your own copies of Everett Kaser's games in a browser tab, using his
KINT 5 and KINT 6 interpreters compiled to WebAssembly.

## Play

```
python3 server.py --open      # or open http://localhost:8765 yourself
```

Pick a game from the launcher. Use the game's own **Exit** menu to quit, so it
can save your settings and puzzles. Your saved files go in `saves/<game>/`.

## How it fits together

| Path | What it is |
|---|---|
| `games/` | Links to the installed `.app` bundles (read-only; files are served straight from them) |
| `server.py` | Local web server (127.0.0.1 only, standard library only) |
| `web/` | Launcher, game page, worker and the built `kint5.*` / `kint6.*` interpreters |
| `engine/patch_k5.py`, `patch_k6.py` | Copy Everett's KINT source from `kint_src/` and apply the small web-port patches into `engine/k5/gen/` and `engine/k6/gen/` |
| `engine/k5/kplat.c`, `engine/k6/kplat6.c` | The browser platform layers (replace Everett's Windows `main.c`) |
| `engine/k5/kint_lib.js` | JavaScript side of the platform layer, shared by both interpreters |
| `engine/build.sh` | Rebuilds both WebAssembly interpreters (needs Emscripten) |
| `web/vendor/` | SpessaSynth MIDI synthesizer (Apache-2.0), rebuilt with `npm install && npm run build` in `tools/music-bundle/` |

## Music

Background music (MIDI) is played by SpessaSynth using macOS's built-in
General MIDI sound bank (`gs_instruments.dls`), the same one native Mac apps
use. Music starts after your first click in the game, because Chrome only
allows sound after you interact with the page.

## Not done yet

- Printing; pasting from the clipboard

## License note

The KINT source is Everett Kaser's and is licensed for personal use only.
Don't redistribute this port, the KINT source, or the games' `MAIN.KE` files.
