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

`--open` opens the launcher in Chrome. Otherwise go to <https://localhost:8765>
yourself (or `http://` if you haven't made a certificate; see
[Playing on other devices](#playing-on-other-devices)). Leave the Terminal window open while you play; press **Ctrl+C** in it
to stop the server.

Tips:

- **Quit with the game's own Exit menu.** That's when most games save your
  settings, statistics and unfinished puzzle. Closing the window may lose them.
  Exit closes the game's window.
- **Each game opens in its own window**, so the game list stays open. Clicking
  a game that's already open brings its window to the front. (In the iPad Home
  Screen app, games open in place of the list instead.) If Chrome blocks the
  new window, the game opens in place of the list.
- **Sound and music start after your first click** in a game, because Chrome
  doesn't allow a page to play sound before you've interacted with it.
- **Window size:** the game fills the browser tab and redraws when you resize
  it. For full screen use Chrome's **View → Enter Full Screen** (⌃⌘F).
- **Keys:** the games use Windows-style shortcuts, so use **Ctrl** where a game
  says Ctrl; **Cmd** shortcuts are left to Chrome. Right-click works as usual
  (two-finger click on a trackpad).
- **Touch screens (iPad):** tap to left-click, and drag to drag. To
  right-click, **touch and hold** until a ring appears, or **tap with two
  fingers**: it right-clicks where the first finger is. A mouse or trackpad
  connected to the iPad works as usual. Two buttons sit in the bottom-right
  corner on touch screens:
  - **⌨** opens the iPad keyboard, for typing your name and other text into a
    game. Tap it again (or the keyboard's hide key) to close it.
  - **✥** makes swipes act as **arrow keys**, for games where you move a
    character with the keys. A flick is one press, a longer swipe presses
    once for about every half inch your finger travels, and holding your
    finger still after a swipe repeats the key. Taps and touch-and-hold
    still click; dragging is off while it's on. It starts on for Hero's
    Hearts, Hero's Friends and Hero Defiant; each game remembers your choice.
  - **Zoom:** spread two fingers to magnify the spot between them, and pinch
    them together to shrink it again; it stays zoomed when you let go, so
    you can tap and drag as usual. Move two fingers together to look around.
    While zoomed in, **⊖** goes straight back to the whole screen. Each game
    remembers its zoom.
- **iPhone:** the games are laid out for a desktop-sized window, so on a phone
  the game gets a screen at least 1024×720 (the shape of the phone), shrunk
  to fit; zoom in to tap the small icons. Landscape works best.
- **Not available:** printing, and pasting from the clipboard into a game.

Server options:

- `--port 9000` uses another port.
- `--verbose` logs every file request, which is handy if a game misbehaves.
- `--local` accepts connections from this Mac only.
- `--http` serves plain HTTP even if a certificate exists.
- `--cert` and `--key` point at a certificate other than `cert.pem` and `key.pem`.

## Playing on other devices

The server accepts connections from any device on your home network. When it
starts it prints the address for other devices, for example
`https://192.168.4.45:8765/`.

Browsers only let the games run on a **secure (HTTPS)** page, except at
`localhost`. So other devices need HTTPS, which uses a certificate made by
[mkcert](https://github.com/FiloSottile/mkcert). If `cert.pem` and `key.pem`
are in this folder the server uses HTTPS automatically. To make them:

```
brew install mkcert
mkcert -install          # trust mkcert's certificate authority on this Mac
mkcert -cert-file cert.pem -key-file key.pem Edwards-MacBook.local localhost 127.0.0.1 192.168.4.48 192.168.4.45
```

Use your Mac's own name and address. Run the last command again if the Mac's
network address changes. Devices that already trust mkcert's authority (below)
accept the new certificate with nothing more to do.

A device keeps its downloaded games and its progress separately for each
address, so stick to one address on each device. The Mac's name
(`https://Edwards-MacBook.local:8765`) is the safest choice because it stays
the same when the IP address changes. If you do move to a new address, open
the old one once more and use **Remove all games from this device** to free
the space (the page opens even when the server isn't at that address).

**Each other device must trust mkcert's authority too**, or it shows a security
warning. The file to install is `rootCA.pem`, in the folder that
`mkcert -CAROOT` prints:

- **iPhone / iPad:**
  1. On the Mac, `open "$(mkcert -CAROOT)"`, right-click `rootCA.pem` and
     choose Share → AirDrop, then pick the device. (Not `rootCA-key.pem`.)
  2. On the device, open Settings and tap **Profile Downloaded** near the top
     (or General → VPN & Device Management), then **Install**.
  3. Turn on full trust: Settings → General → About → **Certificate Trust
     Settings** → switch on the mkcert entry. Without this step the profile
     does nothing.
  4. Close and reopen the browser. This covers both Chrome and Safari.
- **Another Mac:** open `rootCA.pem` in Keychain Access, add it to the System
  keychain, and set it to "Always Trust".
- **Windows / Android:** import it as a trusted root certificate authority.

Keep `rootCA-key.pem` (in the same folder) on this Mac only, and never share
it. `key.pem` is also private; `.gitignore` keeps both `.pem` files out of git.

Everyone playing shares the same saves folder, so two people playing the same
game at once overwrite each other's progress.

If macOS asks whether Python may accept incoming network connections, choose
**Allow**.

## Playing without the server (offline)

A browser can keep its own copy of a game, so it keeps working when the
server is stopped or the Mac is off. This is meant for the iPad.

1. On the iPad, open the server's address in Chrome or Safari, then tap the
   **Share** button (in Chrome it's in the address bar) and choose **Add to
   Home Screen**. From then on, open **Kaser Games** from the
   Home Screen. A Home Screen app keeps its games for good. The browser itself
   may clear stored games after a few weeks without a visit, and it stores
   them separately from the Home Screen app.
2. With the server running, tap a game. The first time, it downloads (a bar
   shows progress) and then starts. The card then says **On this device**.
   **Download all games** at the bottom fetches every game, about 2 GB.
3. Later, with the server off, the home page says so, and the games on the
   device still play.

Details:

- **Saves:** the first download of a game also copies its saves from
  `saves/<game>/`, so you carry on where you were. After that the device keeps
  its own saves; they are **not** copied back to the Mac (yet).
  Removing a game (the **×** on its card) keeps its saves on the device.
- **Updates:** if a game's files on the Mac change, its card says **Update
  available** and the next tap downloads it again. Changes to the app itself
  (`web/`) reach the device automatically the next time it opens the home page
  while the server is running.
- **On the Mac itself** (`localhost`) games aren't downloaded unless you tick
  **Keep games on this device when I play them** at the bottom of the home
  page; on other devices that box starts ticked.
- Games that aren't downloaded still play straight from the server, as before.

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
                              or, for a game kept on the device (offline):
                                         its files in the browser's private
                                         file system, saves in IndexedDB
```

| Path | What it is |
|---|---|
| `server.py` | Web server for your home network, HTTPS when `cert.pem` exists (Python standard library only) |
| `web/` | Launcher (`index.html`), game page (`play.html`, `play.js`), worker, built interpreters |
| `web/fs.js` | The two file systems a game can use: the server, or the copy on the device |
| `web/store.js`, `download.js`, `sw.js` | Offline play: on-device storage, game downloads, and the service worker that keeps the app itself |
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
node tools/cdp.mjs "https://localhost:8765/play?g=Sherlock" /tmp/out /tmp/steps.json
```

Steps can also be `{"click":[x,y]}` (add `"button":"right"` for a right-click)
and `{"key":"a"}`. Clicks and key presses really happen in the game, so they
can change your saves.

## Troubleshooting

- **"This page must be served by server.py"**: open the game through
  <https://localhost:8765>, not as a file.
- **A game won't start on another device**: use the `https://` address, and
  install mkcert's `rootCA.pem` on that device (see
  [Playing on other devices](#playing-on-other-devices)).
- **The launcher says it can't reach the game server, but the server is
  running** (or the page loads forever): the device doesn't trust the
  certificate. The saved copy of the launcher hides the browser's warning, so
  this is the only sign. Install `rootCA.pem` on the device and turn on full
  trust (see [Playing on other devices](#playing-on-other-devices)).
- **Typing the address without `https://`** is fine: the server forwards
  plain `http://` visits to `https://`.
- **Another device can't connect at all**: check the device is on the same
  Wi-Fi, and that the macOS firewall allows Python (System Settings → Network
  → Firewall).
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
