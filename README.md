# Everett Kaser games in Chrome

Runs your own copies of Everett Kaser's games in a browser tab, using his
KINT 5 interpreter compiled to WebAssembly.

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
| `web/` | Launcher, game page, worker and the built `kint5.js` / `kint5.wasm` |
| `engine/patch_k5.py` | Copies Everett's KINT 5 source from `kint_src/` and applies the small web-port patches into `engine/k5/gen/` |
| `engine/k5/kplat.c`, `kint_lib.js` | The browser platform layer (replaces Everett's Windows `main.c`) |
| `engine/build.sh` | Rebuilds the WebAssembly interpreter (needs Emscripten) |

## Not done yet

- MIDI background music
- The three KINT 6 games (Crocotile, Lair of Moriarty, Occam's Quilt)
- Printing; pasting from the clipboard

## License note

The KINT source is Everett Kaser's and is licensed for personal use only.
Don't redistribute this port, the KINT source, or the games' `MAIN.KE` files.
