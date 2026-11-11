#!/usr/bin/env python3
"""
Local web server for playing Everett Kaser's games in Chrome.

    python3 server.py            # then open http://localhost:8765

Games are read directly from the .app bundles linked in ./games.  Anything a
game writes (settings, progress, logs) is stored under ./saves/<game name>/.
The server only listens on 127.0.0.1, so it is not reachable from other
computers.  It uses only the Python standard library.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import mimetypes
import os
import plistlib
import posixpath
import subprocess
import sys
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GAMES_DIR = ROOT / "games"
SAVES_DIR = ROOT / "saves"
WEB_DIR = ROOT / "web"
CACHE_DIR = ROOT / ".cache"

mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("text/javascript", ".js")


# ---------------------------------------------------------------- games
class Game:
    def __init__(self, bundle: Path):
        self.bundle = bundle
        self.name = bundle.name[:-4] if bundle.name.endswith(".app") else bundle.name
        if self.name.endswith(" LIC"):
            self.name = self.name[:-4]
        self.resources = bundle / "Contents" / "Resources"
        self.engine = self._detect_engine()
        self.eks_name = self._read_eks_name()

    def _read_eks_name(self) -> str:
        """The name the native Mac app uses for its save folder (e.g. "MESH Hero Defiant")."""
        try:
            with open(self.bundle / "Contents" / "Info.plist", "rb") as f:
                return plistlib.load(f).get("EKSGameName") or self.name
        except (OSError, plistlib.InvalidFileException):
            return self.name

    def shown_paths(self) -> dict:
        """Folder paths as the native Mac app reports them to the game.
        The MESH games use these to work out which game they are."""
        home = Path.home()
        return {
            "pgm": str(self.resources.resolve()) + "/",
            "app": f"{home}/Library/Application Support/Everett Kaser Software/{self.eks_name}/",
        }

    def _detect_engine(self) -> int:
        try:
            with open(self.resources / "MAIN.KE", "rb") as f:
                head = f.read(0xE0)
        except OSError:
            return 0
        if head.startswith(b"KASMB"):
            return 5
        if b"KINT6" in head:
            return 6
        return 0

    @property
    def saves(self) -> Path:
        return SAVES_DIR / self.name


def find_games() -> dict[str, Game]:
    games = {}
    if GAMES_DIR.is_dir():
        for p in sorted(GAMES_DIR.iterdir()):
            if p.suffix == ".app" and (p / "Contents" / "Resources").is_dir():
                g = Game(p)
                games[g.name] = g
    return games


GAMES = find_games()


# ------------------------------------------------------- path resolution
_dir_cache: dict[Path, dict[str, str]] = {}
_dir_lock = threading.Lock()


def _listing(d: Path, cache: bool) -> dict[str, str]:
    """lower-case name -> real name for the entries of directory d."""
    if cache:
        with _dir_lock:
            if d in _dir_cache:
                return _dir_cache[d]
    try:
        names = {n.lower(): n for n in os.listdir(d)}
    except OSError:
        names = {}
    if cache:
        with _dir_lock:
            _dir_cache[d] = names
    return names


def resolve(game: Game, kpath: str, must_exist: bool = True) -> Path | None:
    """
    Map a KINT path ("pgm/IMAGES/x.BMP", "app/foo.ini", "pgm/../MUSIC/y.MID")
    to a real file, matching names case-insensitively like Windows does.

    pgm/ is the game's Resources folder (read-only).  The Windows layout keeps
    MUSIC and COMMONUI one level above the game; the Mac bundles keep them
    inside Resources, so "pgm/../X" means Resources/X.

    app/ is the player's save folder; "app/../X" is shared by all games.
    """
    kpath = kpath.replace("\\", "/")
    root_name, _, rest = kpath.partition("/")
    if root_name == "pgm":
        root, top, cache = game.resources, game.resources, True
    elif root_name == "app":
        root, top, cache = game.saves, SAVES_DIR, False
    else:
        return None

    cur = root
    parts = [p for p in rest.split("/") if p not in ("", ".")]
    for i, part in enumerate(parts):
        if part == "..":
            if cur != top:
                cur = cur.parent
            continue
        if part.startswith(".") or "\0" in part:
            return None
        real = _listing(cur, cache).get(part.lower())
        last = i == len(parts) - 1
        if real is None:
            if must_exist:
                return None
            real = part
        cur = cur / real
        if not last and must_exist and not cur.is_dir():
            return None
    # never escape the allowed tree
    try:
        cur.resolve().relative_to(top.resolve())
    except ValueError:
        if root_name == "pgm":
            # games/ entries are symlinks to the real bundles; check against those
            try:
                cur.resolve().relative_to(game.resources.resolve())
            except ValueError:
                return None
        else:
            return None
    return cur


# ------------------------------------------------------------- icons
def icon_png(game: Game) -> Path | None:
    """Convert the bundle's AppIcon.icns to PNG with macOS 'sips' (cached)."""
    icns = game.resources / "AppIcon.icns"
    if not icns.exists():
        return None
    out = CACHE_DIR / "icons" / f"{game.name}.png"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(["sips", "-s", "format", "png", "-Z", "256", str(icns), "--out", str(out)],
                           check=True, capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
    return out if out.exists() else None


# ------------------------------------------------------------ handler
class Server(ThreadingHTTPServer):
    daemon_threads = True
    verbose = False


class Handler(BaseHTTPRequestHandler):
    server: Server

    server_version = "KaserWeb/1.0"

    # The game runs in a worker that needs SharedArrayBuffer, which Chrome
    # only allows on "cross-origin isolated" pages.
    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        if self.server.verbose:
            super().log_message(fmt, *args)

    # -- helpers
    def send_bytes(self, data: bytes, ctype: str = "application/octet-stream", status=HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def send_json(self, obj, status=HTTPStatus.OK):
        self.send_bytes(json.dumps(obj).encode(), "application/json", status)

    def not_found(self):
        self.send_bytes(b"not found", "text/plain", HTTPStatus.NOT_FOUND)

    def send_file(self, path: Path):
        try:
            data = path.read_bytes()
        except OSError:
            return self.not_found()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_bytes(data, ctype)

    # -- routing
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(url.path)
        query = urllib.parse.parse_qs(url.query)
        if path in ("/", "/index.html"):
            return self.send_file(WEB_DIR / "index.html")
        if path == "/play":
            return self.send_file(WEB_DIR / "play.html")
        if path == "/api/games":
            return self.send_json([
                {"name": g.name, "engine": g.engine} for g in GAMES.values()
            ])
        if path.startswith("/api/icon/"):
            g = GAMES.get(path[len("/api/icon/"):])
            p = icon_png(g) if g else None
            return self.send_file(p) if p else self.not_found()
        if path.startswith("/api/info/"):
            g = GAMES.get(path[len("/api/info/"):])
            return self.send_json({"name": g.name, "engine": g.engine, **g.shown_paths()}) if g else self.not_found()
        if path.startswith("/api/g/"):
            return self.game_api("GET", path, query)
        if path.startswith("/web/"):
            rel = posixpath.normpath(path[len("/web/"):])
            if rel.startswith("..") or rel.startswith("/"):
                return self.not_found()
            return self.send_file(WEB_DIR / rel)
        return self.not_found()

    def do_PUT(self):
        url = urllib.parse.urlsplit(self.path)
        self.game_api("PUT", urllib.parse.unquote(url.path), urllib.parse.parse_qs(url.query))

    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
        self.game_api("POST", urllib.parse.unquote(url.path), urllib.parse.parse_qs(url.query))

    # -- game file API: /api/g/<game>/<op>?p=<kint path>
    def game_api(self, method: str, path: str, query):
        parts = path.split("/", 4)          # ['', 'api', 'g', game, op]
        if len(parts) != 5:
            return self.not_found()
        game = GAMES.get(parts[3])
        op = parts[4]
        kpath = (query.get("p") or [""])[0]
        if game is None or not kpath:
            return self.not_found()
        writing = method in ("PUT", "POST")
        if writing and not kpath.startswith("app/"):
            return self.send_bytes(b"read-only", "text/plain", HTTPStatus.FORBIDDEN)
        if writing:
            game.saves.mkdir(parents=True, exist_ok=True)

        if method == "GET" and op == "file":
            p = resolve(game, kpath)
            return self.send_file(p) if p and p.is_file() else self.not_found()

        if method == "GET" and op == "stat":
            p = resolve(game, kpath)
            if not p or not p.exists():
                return self.not_found()
            st = p.stat()
            return self.send_json({"size": st.st_size, "mtime": int(st.st_mtime), "dir": p.is_dir()})

        if method == "GET" and op == "list":
            folder, _, pattern = kpath.replace("\\", "/").rpartition("/")
            d = resolve(game, folder) if folder else None
            if not d or not d.is_dir():
                return self.send_json([])
            entries = []
            for name in sorted(os.listdir(d), key=str.lower):
                if name.startswith("."):
                    continue
                if fnmatch.fnmatch(name.lower(), pattern.lower()) or pattern in ("*.*", "*"):
                    entries.append({"name": name, "dir": (d / name).is_dir()})
            return self.send_json(entries)

        if method == "PUT" and op == "file":
            p = resolve(game, kpath, must_exist=False)
            if not p:
                return self.not_found()
            length = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(length)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, p)
            return self.send_bytes(b"ok", "text/plain")

        if method == "POST" and op in ("mkdir", "rmdir", "delete"):
            p = resolve(game, kpath, must_exist=(op != "mkdir"))
            if not p:
                return self.not_found()
            try:
                if op == "mkdir":
                    p.mkdir(parents=True, exist_ok=True)
                elif op == "rmdir":
                    p.rmdir()
                else:
                    p.unlink()
            except OSError:
                return self.send_bytes(b"failed", "text/plain", HTTPStatus.CONFLICT)
            return self.send_bytes(b"ok", "text/plain")

        return self.not_found()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="open the launcher in Chrome")
    ap.add_argument("--verbose", action="store_true", help="log every request")
    args = ap.parse_args()

    if not (WEB_DIR / "kint5.wasm").exists():
        sys.exit("web/kint5.wasm is missing - build it first with: engine/build.sh")
    SAVES_DIR.mkdir(exist_ok=True)

    httpd = Server(("127.0.0.1", args.port), Handler)
    httpd.verbose = args.verbose
    url = f"http://localhost:{args.port}/"
    print(f"Found {len(GAMES)} games.  Serving on {url}  (Ctrl+C to stop)")
    if args.open:
        subprocess.run(["open", "-a", "Google Chrome", url], check=False)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
