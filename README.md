# Everett Kaser games in Chrome

Runs your own copies of Everett Kaser's games in a browser tab. The games'
own program files (`MAIN.KE`) are run by Everett's KINT 5 and KINT 6
interpreters, compiled to WebAssembly, with a small local Python server
supplying the game files and storing your saves.

The server runs on a Mac (using the Mac versions of the games) or on a
Windows PC (using the Windows versions; see [Running on Windows](#running-on-windows)).
Any device with a modern browser can then play: the computer itself, an
iPad or iPhone, an Android phone or tablet, or another computer.

All 41 games work: 34 on KINT 5, and 7 on KINT 6 (Sherlock7, Crocotile,
Descartes Enigma, Descartes Rainbow, Honeycomb Hotel 3, Lair of Moriarty and
Occam's Quilt).

## Playing

Start the server from this folder:

```
python3 server.py --open
```

`--open` opens the launcher in Chrome. Otherwise go to the address it prints
(<http://localhost:8765>, or `https://` if you made your own certificate with
mkcert; see [Playing on other devices](#playing-on-other-devices)). Leave the Terminal window open while you play; press **Ctrl+C** in it
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
    still click; dragging is off while it's on. It starts on for Falling
    Hero, Hero's Hearts, Hero's Friends and Hero Defiant; each game remembers
    your choice.
  - **Zoom:** spread two fingers to magnify the spot between them, and pinch
    them together to shrink it again; it stays zoomed when you let go, so
    you can tap and drag as usual. Move two fingers together to look around.
    While zoomed in, **⊖** goes straight back to the whole screen. Each game
    remembers its zoom.
  - **Smooth zoom (✦):** zoomed in, the screen is redrawn with a pixel-art
    upscaler (xBR, in `web/upscale.js`), so edges, icons and text look
    smooth instead of blocky. It can't add detail the game's pictures don't
    have. **✦** (shown while zoomed in) switches between smooth and square
    pixels; the choice applies to every game.
  - **Full screen (⤢, Android):** hides Chrome's address bar and the phone's
    status and navigation bars, leaving the whole screen to the game. Tap it
    again, or swipe in from the edge and press Back, to leave full screen.
    It isn't shown on iPad or iPhone, or in the installed **Kaser Games**
    app on Android, which already opens full screen (see "Playing without
    the server" below).
- **iPhone:** the games are laid out for a desktop-sized window, so on a phone
  the game gets a screen at least 1024×720 (the shape of the phone), shrunk
  to fit; zoom in to tap the small icons. Landscape works best.
- **Not available:** printing, and pasting from the clipboard into a game.

Server options:

- `--port 9000` uses another port.
- `--verbose` logs every file request, which is handy if a game misbehaves.
- `--local` accepts connections from this computer only.
- `--games FOLDER` also looks for games in that folder (it can be given more
  than once). The folder can be a game, hold games, or hold folders of games.
- `--http` serves plain HTTP only (other devices then can't play).
- `--cert` and `--key` point at your own certificate instead of `cert.pem` and `key.pem`.

## Running on Windows

The server also runs on Windows, using the Windows versions of the games
you've installed. Nothing in the games or your Windows installation is
changed.

1. Install Python 3 from <https://www.python.org/downloads/>. During
   installation, tick **Add python.exe to PATH**. (Windows has a `python`
   command even without it, but that only points to the Microsoft Store;
   `start-windows.bat` tells you if that's all it finds.)
2. Unzip this folder **with its folders kept** (right-click the zip →
   **Extract All…**) and put it anywhere you like, for example in Documents.
3. Double-click **`start-windows.bat`**. The first time, it installs the
   `cryptography` package that the server uses to make its security
   certificate for tablets and phones. Then it starts the server and opens
   the game list in your browser. Keep its window open while you play; close
   it to stop the server.

If Windows Firewall asks whether Python may communicate on networks, allow
it on **private networks** if you want to play from other devices (a phone or
tablet); otherwise you can say no.

**Where it looks for games:** the folders the Kaser installers registered
with Windows, plus `C:\eks` (the installers' usual choice),
`Program Files\Everett Kaser Software` and
`Program Files (x86)\Everett Kaser Software`. If your games are somewhere
else, it says "No games found" when it starts. Edit `start-windows.bat` in
Notepad and add the folder to the `server.py` line, for example:

```
%PY% server.py --open --games "D:\Games\Everett Kaser Software" %*
```

Give the folder that holds the game folders. The Windows games keep their
shared `MUSIC` and `COMMONUI` folders there, next to the game folders.

**Music** uses the General MIDI instruments built into Windows
(`C:\Windows\System32\drivers\gm.dls`).

**Your progress** from the Windows games (kept in
`Documents\Everett Kaser Software\<game>`) can be copied in, as described in
[Your saves](#your-saves): run `py tools\import_native_saves.py` in a Command
Prompt in this folder.

## Playing on other devices

The server accepts connections from any device on your home network. When it
starts it prints the address for other devices, for example
`http://192.168.4.45:8766/`. Open that address on the phone, tablet or other
computer. Port 8766 is only for setting a device up; the games themselves are
at `https://192.168.4.45:8765/`, and the setup page takes you there.

Port 8766 serves plain `http://` and nothing else, which matters for Chrome's
**Always use secure connections** setting: that setting tries `https://`
first, and on 8765 it meets a certificate the device doesn't trust yet and
gives up (`ERR_TOO_MANY_RETRIES`). On 8766 the `https://` try is refused, so
Chrome falls back to `http://`. It may first show a "Connection is not secure"
warning; choose **Continue to site**.

Some versions of Chrome (Android Chrome with that setting on, for one) still
end with `ERR_TOO_MANY_RETRIES` on 8766. Then open
`https://192.168.4.45:8765/setup` instead. Chrome warns that the connection
isn't private: tap **Advanced**, then **Proceed**. The setup page appears with
the same steps. Once the certificate is installed, the warning goes away.
(Opening `https://192.168.4.45:8765/` and tapping past the warning also
leads to the setup page.)

Browsers only let the games run on a **secure (https://) page**, except at
`localhost` on the computer itself. So the server makes its own security
certificate the first time it starts (in the `tls` folder; this needs the
`cryptography` package, which `start-windows.bat` installs, or
`python3 -m pip install cryptography`). Each other device has to trust it
once:

1. Open the `http://` address on the device. The first time, it shows a
   **Set up this device** page with a **Download certificate** button and the
   steps for that kind of device:
   - **Android:** download it, then Settings → search for **CA certificate**
     (usually Security → More security settings → Encryption & credentials →
     Install a certificate → CA certificate) → Install anyway → pick
     `kaser-games-certificate.crt` (if the file picker doesn't list it, use
     its search to find it). Android only allows this when the device has a
     screen lock.
   - **iPhone / iPad:** use **Safari** for this step. Download it and allow
     it, then Settings → **Profile Downloaded** → Install, and turn it on in
     Settings → General → About → **Certificate Trust Settings**.
   - **Another computer:** open the file and add it to the trusted root
     certificates (Windows: Install Certificate → Current User → Trusted Root
     Certification Authorities; Mac: Keychain Access → Always Trust).
2. Tap **Check again**. Once the device trusts the server, the page goes
   straight to the games, at the `https://` address. From then on the
   `http://` setup address forwards there by itself.

The certificate's secret key (`tls/ca-key.pem`) never leaves this computer;
don't share it. When the computer's network address changes, the server
makes a new certificate by itself and devices that are already set up don't
need to do anything.

A device keeps its downloaded games and its progress separately for each
address, so stick to one address on each device. The computer's name
(`Edwards-MacBook.local`) is the safest choice because it stays the same when
the IP address changes, but some home networks (eero, for one) don't let
devices find it. If you do move to a new address, open the old one once more
and use **Remove all games from this device** to free the space (the page
opens even when the server isn't at that address).

Everyone playing shares the same saves folder, so two people playing the same
game at once overwrite each other's progress.

If macOS asks whether Python may accept incoming network connections, choose
**Allow**. On Windows, allow it on **private networks**.

**Using mkcert instead.** If `cert.pem` and `key.pem` are in this folder, the
server uses them rather than making its own, and the setup page offers
mkcert's root certificate. To make them:

```
brew install mkcert
mkcert -install          # trust mkcert's certificate authority on this Mac
mkcert -cert-file cert.pem -key-file key.pem Edwards-MacBook.local localhost 127.0.0.1 192.168.4.48 192.168.4.45
```

Run the last command again if the Mac's network address changes. Keep
`rootCA-key.pem` (in the folder `mkcert -CAROOT` prints) on this Mac only.

## Playing without the server (offline)

A browser can keep its own copy of a game, so it keeps working when the
server is stopped or the computer is off. This is meant for tablets and
phones.

1. Put the game list on the device's home screen, and from then on open
   **Kaser Games** from there:
   - **iPad / iPhone:** open the server's address in Chrome or Safari, tap
     the **Share** button (in Chrome it's in the address bar) and choose
     **Add to Home Screen**.
   - **Android:** open the server's address in Chrome, then tap the
     **install** icon in the address bar if there is one, or the **⋮** menu →
     **Add to Home screen** (or **Install app**). The ⋮ menu's **download**
     arrow is something else: it saves a snapshot of the page (a `.mht`
     file) that can't play the games.
     Choose **Install app** if it's offered: the installed app opens full
     screen, with no address bar and the phone's bars hidden. Chrome only
     offers it on the `https://` address once the device trusts the
     certificate; **Add to Home screen** on its own makes a shortcut that
     opens in an ordinary Chrome tab.

   A home screen app keeps its games for good. The browser itself may clear
   stored games after a few weeks without a visit, and it stores them
   separately from the home screen app.
2. With the server running, tap a game. The first time, it downloads (a bar
   shows progress) and then starts. The card then says **On this device**.
   **Download all games** at the bottom fetches every game, about 2 GB.
3. Later, with the server off, the home page says so, and the games on the
   device still play.

Details:

- **Saves:** the first download of a game also copies its saves from
  `saves/<game>/`, so you carry on where you were. After that the device keeps
  its own saves; they are **not** copied back to the computer (yet).
  Removing a game (the **×** on its card) keeps its saves on the device.
- **Updates:** if a game's files on the computer change, its card says **Update
  available** and the next tap downloads it again. Changes to the app itself
  (`web/`) reach the device automatically the next time it opens the home page
  while the server is running.
- **On the computer itself** (`localhost`) games aren't downloaded unless you tick
  **Keep games on this device when I play them** at the bottom of the home
  page; on other devices that box starts ticked.
- Games that aren't downloaded still play straight from the server, as before.

## A static site (no server.py)

`tools/make_static.py` writes the whole site as plain files into `static/`,
which any web server can serve, with no `server.py` behind it: Python's
built-in server, GitHub Pages or an ordinary web host. It's an experiment
toward Everett hosting the games on his own site.

```
python3 tools/make_static.py                                  # every game in games/
python3 tools/make_static.py --game Sherlock7 --game Crocotile   # or just these
cd static && python3 -m http.server 8000 --bind 127.0.0.1
```

Then open <http://localhost:8000/> in Chrome. Picking a game downloads it
once; after that it plays from the browser's storage, even with the web
server stopped. Chrome and Edge show an **Install app** button. The site
is about 2 GB with all 41 games. Running the script again only rewrites the
games that changed.

How it differs from `server.py`:

- Every game is downloaded before it plays; there's nothing to play it from
  otherwise.
- Saves stay in each browser. **Export saves** and **Import saves** at the
  bottom of the page copy them to and from a file, to back them up or move
  them to another device. Saves in `saves/` aren't copied in.
- The page's service worker (`web/sw.js`) adds the security headers the games
  need (cross-origin isolation), which `server.py` sends itself. On the very
  first visit the game page reloads itself once to pick them up.
- Like `server.py`, it only runs on a secure page: `http://localhost` on this
  computer, or `https://` anywhere else. Python's built-in server can't do
  `https://`, so to try it on an iPad or phone, the site has to be on a
  real `https://` host.

`static/` holds copies of the games and macOS's own sound bank, so it's left
out of git. Don't put it anywhere public unless Everett says so; a public site
also needs a freely licensed General MIDI sound bank (`--soundbank FILE.sf2`).

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

On a Mac, the launcher lists every `.app` bundle in `games/`. These are links
to the installed apps, so to add one:

```
ln -s "/path/to/Some Game LIC.app" games/
```

On Windows, install the game as usual; the server finds it in the same
places as your other games (or use `--games`, above).

Then restart the server. The interpreter (KINT 5 or 6) is chosen automatically
from the game's `MAIN.KE` file.

## Rebuilding from scratch

The built interpreters (`web/kint5.*`, `web/kint6.*`) and Everett's source are
not in git, so after a fresh clone, or to change the interpreter code:

1. Download `MSKINT50.ZIP` and `KINT_6_3_0.zip` from
   <https://kaser.com/kint.html> into this folder, along with
   `MacKINT5latest.zip` and `MacKINT6latest.zip` (Everett's newer Mac
   interpreter source, which he sends on request; the KINT 5 one has the
   native puzzle-generator code His Last Bow needs).
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
                              server.py: game files from games/*.app
                                         (Mac) or the Windows game folders,
                                         your files in saves/
                              or, for a game kept on the device (offline):
                                         its files in the browser's private
                                         file system, saves in IndexedDB
```

| Path | What it is |
|---|---|
| `server.py` | Web server for your home network (Python standard library, plus `cryptography` for the certificate) |
| `certs.py` | Makes the server's own certificate authority and certificate in `tls/` |
| `web/setup.html` | The page other devices see until they trust the certificate |
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

Music is played by SpessaSynth using the General MIDI sound bank built into
the server's computer: `gs_instruments.dls` on macOS (the one native Mac apps
use) or `gm.dls` on Windows. To use a different one (or on Linux, which has
none built in), put a `soundbank.sf2` or `soundbank.dls` next to `server.py`.

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
  <http://localhost:8765>, not as a file.
- **"…couldn't be downloaded. Cannot read properties of undefined (reading
  'getDirectory')"** or **"Chrome only runs the games on a secure page"**:
  the device is using a plain `http://` address. Set the device up as in
  [Playing on other devices](#playing-on-other-devices).
- **"Some files are missing"** when the server starts: the zip was unzipped
  without its folders. Unzip it again with **Extract All…**.
- **The launcher says it can't reach the game server, but the server is
  running** (or the page loads forever): the device doesn't trust the
  certificate. The saved copy of the launcher hides the browser's warning, so
  this is the only sign. Open the `http://` address on the device and follow
  the setup page (see [Playing on other devices](#playing-on-other-devices)).
- **Typing the address without `https://`** is fine: once the device is set
  up, the server forwards plain `http://` visits to `https://`.
- **Another device can't connect at all**: check the device is on the same
  Wi-Fi, and that the firewall allows Python: on a Mac, System Settings →
  Network → Firewall; on Windows, Windows Security → Firewall & network
  protection → Allow an app through firewall → Python, **Private** ticked.
  On Windows, also check that your home network is set to **Private**, not
  Public (Settings → Network & internet → Wi-Fi → your network).
- **"Address already in use"**: the server is already running (perhaps in
  another Terminal or Command Prompt window), or use `--port`.
- **Windows: "No games found"**: tell the server where the games are with
  `--games` (see [Running on Windows](#running-on-windows)).
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
