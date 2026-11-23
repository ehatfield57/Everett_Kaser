#!/usr/bin/env python3
"""
Local web server for playing Everett Kaser's games in Chrome.

    python3 server.py            # then open https://localhost:8765
    py server.py --open          # on Windows (or double-click start-windows.bat)

Games are read directly from where they are installed: the Mac .app bundles
linked in ./games, or the Windows game folders (found automatically in the
usual install places, or given with --games).  Anything a game writes
(settings, progress, logs) is stored under ./saves/<game name>/.
The server listens on all network interfaces, so other devices on your local
network can play too.  They need https://, so the server makes its own
certificate in tls/ (see certs.py; needs the "cryptography" package) and shows
each new device how to trust it at http://<address>:8765/.  On the computer
itself http://localhost works without any certificate.  If cert.pem and key.pem
(made with mkcert) are next to this file, those are used instead.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import mimetypes
import os
import plistlib
import posixpath
import socket
import ssl
import struct
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import certs

ROOT = Path(__file__).resolve().parent
GAMES_DIR = ROOT / "games"
SAVES_DIR = ROOT / "saves"
WEB_DIR = ROOT / "web"
CACHE_DIR = ROOT / ".cache"
IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"


def find_soundbank() -> Path | None:
    """The General MIDI sound bank the music is played with: a soundbank.sf2
    or soundbank.dls next to this file if there is one, otherwise the one
    built into the operating system (the one native apps play MIDI through)."""
    candidates = [ROOT / "soundbank.sf2", ROOT / "soundbank.dls",
                  Path("/System/Library/Components/CoreAudio.component/Contents/Resources/gs_instruments.dls")]
    if IS_WINDOWS:
        windir = Path(os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows")
        candidates.append(windir / "System32" / "drivers" / "gm.dls")
    return next((p for p in candidates if p.is_file()), None)


SOUNDBANK = find_soundbank()

mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("application/manifest+json", ".webmanifest")


# ---------------------------------------------------------------- games
# Folders the Windows games share with each other, one level above each game
# folder ("pgm/../MUSIC").  The Mac bundles keep their own copies inside.
SHARED_DIRS = ("MUSIC", "COMMONUI")


class Game:
    """One installed game: a Mac .app bundle, or a Windows game folder
    (for example C:\\...\\Everett Kaser Software\\Sherlock)."""

    def __init__(self, path: Path):
        self.bundle = path
        self.mac = path.suffix == ".app"
        if self.mac:
            self.name = path.name[:-4]
            if self.name.endswith(" LIC"):
                self.name = self.name[:-4]
            self.resources = path / "Contents" / "Resources"
        else:
            self.name = path.name
            self.resources = path
        # lower-case name -> (real name, path) of shared folders that appear
        # inside the game folder, so a game sees the same tree on both systems
        self.shared: dict[str, tuple[str, Path]] = {}
        if not self.mac:
            here = _listing(path, False)
            above = _listing(path.parent, False)
            for d in SHARED_DIRS:
                real = above.get(d.lower())
                if d.lower() not in here and real and (path.parent / real).is_dir():
                    self.shared[d.lower()] = (real, path.parent / real)
        self.engine = self._detect_engine()
        self.eks_name = self._read_eks_name()
        self.beta = self._detect_beta() if self.engine == 6 else None

    def _read_eks_name(self) -> str:
        """The name the native Mac app uses for its save folder (e.g. "MESH Hero Defiant")."""
        if not self.mac:
            return self.name
        try:
            with open(self.bundle / "Contents" / "Info.plist", "rb") as f:
                return plistlib.load(f).get("EKSGameName") or self.name
        except (OSError, plistlib.InvalidFileException):
            return self.name

    @property
    def native_saves(self) -> Path:
        """Where the native (non-browser) version of this game keeps its saves."""
        if self.mac:
            return Path.home() / "Library" / "Application Support" / "Everett Kaser Software" / self.eks_name
        # Windows: Documents\<install folder name>\<game folder name>
        return documents_folder() / self.bundle.parent.name / self.bundle.name

    def shown_paths(self) -> dict:
        """Folder paths as the native app reports them to the game.
        The MESH games use these to work out which game they are."""
        return {
            "pgm": str(self.resources.resolve()) + os.sep,
            "app": str(self.native_saves) + os.sep,
        }

    def _detect_engine(self) -> int:
        main_ke = _listing(self.resources, False).get("main.ke", "MAIN.KE")
        try:
            with open(self.resources / main_ke, "rb") as f:
                head = f.read(0xE0)
        except OSError:
            return 0
        if head.startswith(b"KASMB"):
            return 5
        if b"KINT6" in head:
            return 6
        return 0

    def _detect_beta(self) -> dict | None:
        """Pre-release (beta test) games come with a KINT 6 interpreter built in
        BETA mode: some system calls take an extra "beta key" argument, and the
        game stops working after a set date.  Recognised by the interpreter's
        "BETA TEST period ... has elapsed" message.  Returns None for a normal
        game, else {"expires": "YYYY-MM-DD" or None}: the first day it no
        longer runs, read from the Mac app (unknown for Windows)."""
        if self.mac:
            exe_dir = self.bundle / "Contents" / "MacOS"
            exes = sorted(exe_dir.iterdir()) if exe_dir.is_dir() else []
        else:
            exes = [p for p in sorted(self.bundle.iterdir()) if p.suffix.lower() == ".exe"]
        marker = "BETA TEST period"
        for exe in exes:
            try:
                data = exe.read_bytes()
            except OSError:
                continue
            if marker.encode() in data or marker.encode("utf-16-le") in data:
                return {"expires": beta_expiry_arm64(data)}
        return None

    @property
    def saves(self) -> Path:
        return SAVES_DIR / self.name


def beta_expiry_arm64(data: bytes) -> str | None:
    """The Mac beta interpreter checks today's date with three compares in a
    row, 16 bytes apart: cmp wN,#year / cmp wN,#month / cmp wN,#day, and
    stops when today is on or after that date.  Find them in the arm64 code."""
    def cmp_imm(ins):              # 32-bit "cmp wN, #imm" (unshifted)
        return (ins >> 10) & 0xFFF if (ins & 0xFFC0001F) == 0x7100001F else None
    words = memoryview(data)[: len(data) // 4 * 4].cast("I")
    for i in range(len(words) - 8):
        y = cmp_imm(words[i])
        if y is None or not 2000 <= y <= 2100:
            continue
        m, d = cmp_imm(words[i + 4]), cmp_imm(words[i + 8])
        if m and d and 1 <= m <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{m:02d}-{d:02d}"
    return None


def documents_folder() -> Path:
    """The user's Documents folder (on Windows it may have been moved, for
    example into OneDrive, so ask Windows where it is)."""
    if IS_WINDOWS:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:  # CSIDL_PERSONAL
                return Path(buf.value)
        except (OSError, AttributeError):
            pass
    return Path.home() / "Documents"


def windows_install_folders() -> list[Path]:
    """Folders where the Windows games are probably installed: the folders the
    installers registered with Windows, plus the usual default places."""
    found: list[Path] = []
    if not IS_WINDOWS:
        return found
    try:
        import winreg
        keys = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
        for hive, key in keys:
            try:
                k = winreg.OpenKey(hive, key)
            except OSError:
                continue
            with k:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    try:
                        with winreg.OpenKey(k, winreg.EnumKey(k, i)) as app:
                            def val(n):
                                try:
                                    return str(winreg.QueryValueEx(app, n)[0])
                                except OSError:
                                    return ""
                            if "kaser" not in (val("Publisher") + val("DisplayName")).lower():
                                continue
                            loc = val("InstallLocation") or val("DisplayIcon") or val("UninstallString")
                            loc = loc.strip().strip('"').split('"')[0].split(",")[0]
                            p = Path(loc)
                            if p.suffix:          # a file inside the game folder
                                p = p.parent
                            if p.is_dir():
                                found.append(p)
                    except OSError:
                        continue
    except ImportError:
        pass
    for var in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432"):
        base = os.environ.get(var)
        if base:
            found.append(Path(base) / "Everett Kaser Software")
    found.append(Path(r"C:\Everett Kaser Software"))
    for drive in "CD":
        found.append(Path(f"{drive}:\\eks"))       # the installers' usual default
    return found


def is_game(p: Path) -> bool:
    if p.suffix == ".app":
        return (p / "Contents" / "Resources").is_dir()
    return p.is_dir() and "main.ke" in _listing(p, False)


def find_games(extra: list[Path] | None = None) -> dict[str, Game]:
    """Every game in games/, in the folders given with --games and in the
    usual Windows install places.  Each folder may be a game itself, hold
    games, or hold folders of games (one level deeper)."""
    games: dict[str, Game] = {}
    seen: set[Path] = set()

    def add(p: Path):
        try:
            key = p.resolve()
        except OSError:
            return
        if key in seen:
            return
        seen.add(key)
        g = Game(p)
        if g.name not in games:
            games[g.name] = g

    def scan(folder: Path, depth: int):
        if is_game(folder):
            return add(folder)
        if depth == 0 or not folder.is_dir():
            return
        try:
            entries = sorted(folder.iterdir(), key=lambda q: q.name.lower())
        except OSError:
            return
        for p in entries:
            if not p.name.startswith(".") and (p.suffix == ".app" or p.is_dir()):
                scan(p, depth - 1)

    for folder in [GAMES_DIR, *(extra or []), *windows_install_folders()]:
        scan(folder, 2)
    return games


GAMES: dict[str, Game] = {}


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
    inside Resources, so "pgm/../X" means Resources/X.  For a Windows game
    folder those shared folders are shown inside it, to match the Mac.

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

    shared = {path: real for real, path in game.shared.values()} if root_name == "pgm" else {}
    cur = root
    parts = [p for p in rest.split("/") if p not in ("", ".")]
    for i, part in enumerate(parts):
        if part == "..":
            if cur in shared:           # a shared folder's parent is the game folder
                cur = game.resources
            elif cur != top:
                cur = cur.parent
            continue
        if part.startswith(".") or "\0" in part:
            return None
        last = i == len(parts) - 1
        if cur == game.resources and root_name == "pgm" and part.lower() in game.shared:
            cur = game.shared[part.lower()][1]
            continue
        real = _listing(cur, cache).get(part.lower())
        if real is None:
            if must_exist:
                return None
            real = part
        cur = cur / real
        if not last and must_exist and not cur.is_dir():
            return None
    # never escape the allowed tree.  The walk above can't climb out by name;
    # also accept links the game's own files make (games/ entries are links).
    allowed = [top] if root_name == "app" else [game.resources, *shared]
    for a in allowed:
        for c, t in ((cur, a), (cur.resolve(), a.resolve())):
            try:
                c.relative_to(t)
                return cur
            except ValueError:
                pass
    return None


# ------------------------------------------------------------- icons
def icon_png(game: Game) -> Path | None:
    """The game's icon: the Mac bundle's AppIcon.icns converted to PNG with
    macOS 'sips', or the icon inside a Windows game's .exe (cached)."""
    if not game.mac:
        return exe_icon(game)
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


def exe_icon(game: Game) -> Path | None:
    """Copy the first icon out of a Windows game's .exe into a .ico file."""
    out = CACHE_DIR / "icons" / f"{game.name}.ico"
    if out.exists():
        return out
    exes = [p for p in game.resources.iterdir()
            if p.suffix.lower() == ".exe" and not p.name.lower().startswith("unins")]
    # prefer the one named after the game, then the biggest
    exes.sort(key=lambda p: (p.stem.lower() != game.name.lower(), -p.stat().st_size))
    for exe in exes:
        try:
            ico = ico_from_exe(exe.read_bytes())
        except (OSError, ValueError, IndexError, struct.error):
            ico = None
        if ico:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(ico)
            return out
    return None


def ico_from_exe(data: bytes) -> bytes | None:
    """Rebuild a .ico file from an .exe's RT_GROUP_ICON / RT_ICON resources."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        return None
    nsect, opt_size = struct.unpack_from("<H12xH", data, pe + 6)
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    dirs = opt + (96 if magic == 0x10B else 112)
    res_rva = struct.unpack_from("<I", data, dirs + 2 * 8)[0]
    if not res_rva:
        return None
    sections = []
    for i in range(nsect):
        vsize, va, rawsize, raw = struct.unpack_from("<IIII", data, opt + opt_size + 40 * i + 8)
        sections.append((va, max(vsize, rawsize), raw))

    def at(rva):
        for va, size, raw in sections:
            if va <= rva < va + size:
                return raw + rva - va
        raise ValueError("bad RVA")

    base = at(res_rva)

    def entries(off):
        named, ids = struct.unpack_from("<HH", data, base + off + 12)
        for i in range(named + ids):
            name, target = struct.unpack_from("<II", data, base + off + 16 + 8 * i)
            yield name, target

    def leaf(target):
        while target & 0x80000000:        # descend to the first language
            target = next(entries(target & 0x7FFFFFFF))[1]
        rva, size = struct.unpack_from("<II", data, base + target)
        return data[at(rva):at(rva) + size]

    types = dict(entries(0))
    if 14 not in types or 3 not in types:          # RT_GROUP_ICON, RT_ICON
        return None
    icons = {name: target for name, target in entries(types[3] & 0x7FFFFFFF)}
    group = leaf(next(entries(types[14] & 0x7FFFFFFF))[1])
    count = struct.unpack_from("<H", group, 4)[0]
    head, images = [], []
    for i in range(count):
        w, h, colors, _, planes, bits, _, icon_id = struct.unpack_from("<BBBBHHIH", group, 6 + 14 * i)
        if icon_id not in icons:
            continue
        img = leaf(icons[icon_id])
        head.append(struct.pack("<BBBBHHII", w, h, colors, 0, planes, bits, len(img), 0))
        images.append(img)
    if not images:
        return None
    offset = 6 + 16 * len(images)
    fixed = []
    for h_, img in zip(head, images):
        fixed.append(h_[:12] + struct.pack("<I", offset))
        offset += len(img)
    return struct.pack("<HHH", 0, 1, len(images)) + b"".join(fixed) + b"".join(images)


# ---------------------------------------------------- offline downloads
# A browser can keep a copy of a game so it plays without this server.  The
# game's Resources folder is sent as one "pack": an index of files followed by
# their contents back to back.  Files the interpreter never reads are left out.
PACK_SKIP = {"appicon.icns", "assets.car"}
PACK_SKIP_EXT = {".exe", ".dll"}   # Windows programs: the browser has its own interpreter
_pack_cache: dict[str, tuple[list, dict, list[Path]]] = {}


def pack_index(game: Game) -> dict:
    """Files and folders of the game, in pack order, plus a version string."""
    return _pack(game)[0]


def _pack(game: Game) -> tuple[dict, list[Path]]:
    """The pack index, and the real location of each file in it."""
    key = game.name
    trees = [("", game.resources), *((real + "/", path) for real, path in game.shared.values())]
    stamp = []
    for _, t in trees:
        try:
            stamp.append(t.stat().st_mtime)
        except OSError:
            stamp.append(0)
    hit = _pack_cache.get(key)
    if hit and hit[0] == stamp:
        return hit[1], hit[2]
    files, dirs, paths = [], [], []
    for prefix, tree in trees:
        top = tree.resolve()
        if prefix:
            dirs.append([prefix[:-1], int(os.stat(top).st_mtime)])
        for d, subdirs, names in os.walk(top, followlinks=True):
            subdirs[:] = sorted(n for n in subdirs if not n.startswith("."))
            rel = Path(d).relative_to(top).as_posix()
            rel = prefix + ("" if rel == "." else rel + "/")
            if rel != prefix:
                dirs.append([rel[:-1], int(os.stat(d).st_mtime)])
            for n in sorted(names):
                if (n.startswith(".") or n.lower() in PACK_SKIP
                        or os.path.splitext(n)[1].lower() in PACK_SKIP_EXT):
                    continue
                full = os.path.join(d, n)
                st = os.stat(full)
                files.append([rel + n, st.st_size, int(st.st_mtime)])
                paths.append(Path(full))
    h = hashlib.sha1(json.dumps([files, dirs]).encode()).hexdigest()[:16]
    index = {"version": h, "total": sum(f[1] for f in files), "files": files, "dirs": dirs}
    _pack_cache[key] = (stamp, index, paths)
    return index, paths


def save_files(game: Game) -> list[dict]:
    """The player's saved files for a game, without the SIZED_* picture caches
    (the game rebuilds those itself)."""
    out = []
    root = game.saves
    if not root.is_dir():
        return out
    for d, subdirs, names in os.walk(root):
        subdirs[:] = sorted(n for n in subdirs if not n.startswith("."))
        rel = Path(d).relative_to(root).as_posix()
        rel = "" if rel == "." else rel + "/"
        for n in sorted(names):
            if n.startswith(".") or n.upper().startswith("SIZED_") or n.endswith(".tmp"):
                continue
            st = os.stat(os.path.join(d, n))
            out.append({"p": "app/" + rel + n, "size": st.st_size, "mtime": int(st.st_mtime)})
    return out


def web_version() -> str:
    """Changes whenever a file in web/ changes, so browsers refresh their offline copy."""
    h = hashlib.sha1()
    for p in sorted(WEB_DIR.rglob("*")):
        if p.is_file():
            st = p.stat()
            h.update(f"{p.relative_to(WEB_DIR)}:{st.st_size}:{st.st_mtime_ns};".encode())
    return h.hexdigest()[:16]


# ------------------------------------------------------------ handler
class Server(ThreadingHTTPServer):
    daemon_threads = True
    verbose = False
    ssl_ctx: ssl.SSLContext | None = None   # set when serving HTTPS
    ca_cert: Path | None = None             # the certificate devices install to trust us
    https_port = 0                          # where the games are served over https

    def finish_request(self, request, client_address):
        # Runs in the connection's own thread, so one slow or stuck device
        # can't hold up everyone else during the TLS handshake.
        if self.ssl_ctx is None:
            return super().finish_request(request, client_address)
        request.settimeout(30)
        first = request.recv(1, socket.MSG_PEEK)
        if not first:
            return
        if first != b"\x16":        # not a TLS handshake: an http:// address
            request.settimeout(None)
            return super().finish_request(request, client_address)
        tls = self.ssl_ctx.wrap_socket(request, server_side=True)
        try:
            tls.settimeout(None)
            super().finish_request(tls, client_address)
        finally:
            self.shutdown_request(tls)

    def handle_error(self, request, client_address):
        # A device that doesn't trust the certificate, or a dropped connection,
        # is routine; report it in one line instead of a traceback.
        err = sys.exc_info()[1]
        if isinstance(err, (ssl.SSLError, ConnectionError, TimeoutError)):
            if self.verbose:
                print(f"{client_address[0]}: {err}", file=sys.stderr)
            return
        super().handle_error(request, client_address)


class SetupServer(Server):
    """Plain-http port that only shows the setup page and hands out the CA.

    Chrome's "Always use secure connections" turns http://<address>:8765 into
    https://, and while the device doesn't trust our certificate yet that ends
    in ERR_TOO_MANY_RETRIES, so the device never sees the setup page.  This
    port refuses https outright (it closes any TLS handshake), which makes
    Chrome fall back to http:// (asking first in that mode)."""

    def finish_request(self, request, client_address):
        request.settimeout(30)
        first = request.recv(1, socket.MSG_PEEK)
        if not first or first == b"\x16":     # nothing, or a TLS handshake: hang up
            return
        request.settimeout(None)
        ThreadingHTTPServer.finish_request(self, request, client_address)


class DualStackServer(Server):
    """Listens on IPv6 and IPv4 at once.  The Mac's Bonjour name (<name>.local)
    resolves to IPv6 addresses too, and some devices try those first."""
    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def make_server(local: bool, port: int, setup: bool = False) -> Server:
    if local:
        return Server(("127.0.0.1", port), Handler)
    try:
        if setup:
            class S(SetupServer, DualStackServer):
                pass
            return S(("::", port), Handler)
        return DualStackServer(("::", port), Handler)
    except OSError:
        return (SetupServer if setup else Server)(("0.0.0.0", port), Handler)   # no IPv6 here


def bonjour_name() -> str | None:
    """This Mac's network name, e.g. Edwards-MacBook.local, which stays the
    same when the IP address changes."""
    try:
        name = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True,
                              text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return f"{name}.local" if name else None


def lan_addresses() -> list[str]:
    """Every IPv4 address this computer has on the local network, the main one first."""
    out = []
    main = lan_address()
    if main:
        out.append(main)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in out and not ip.startswith("127.") and not ip.startswith("169.254."):
                out.append(ip)
    except OSError:
        pass
    return out


def mkcert_ca() -> Path | None:
    """mkcert's root certificate, when the user's own cert.pem came from mkcert."""
    try:
        root = subprocess.run(["mkcert", "-CAROOT"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    p = Path(root) / "rootCA.pem" if root else None
    return p if p and p.exists() else None


def lan_address() -> str | None:
    """This Mac's address on the local network (no packets are sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return None


class Handler(BaseHTTPRequestHandler):
    server: Server

    server_version = "KaserWeb/1.0"

    # The game runs in a worker that needs SharedArrayBuffer, which Chrome
    # only allows on "cross-origin isolated" pages.
    corp = "same-origin"

    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", self.corp)
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

    # -- plain http:// from another device
    def plain_from_elsewhere(self) -> bool:
        """True for an http:// request from another device while we serve HTTPS.
        Chrome won't run the games on such a page, so it only gets the setup page
        (which forwards to https:// once the device trusts our certificate).
        Everything on the setup port counts, wherever it comes from."""
        if isinstance(self.server, SetupServer):
            return True
        if self.server.ssl_ctx is None or isinstance(self.connection, ssl.SSLSocket):
            return False
        ip = self.client_address[0]
        if ip.startswith("::ffff:"):
            ip = ip[7:]
        return not (ip.startswith("127.") or ip == "::1")

    def send_ca(self):
        der = certs.ca_der(self.server.ca_cert) if self.server.ca_cert else None
        if not der:
            return self.not_found()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-x509-ca-cert")
        self.send_header("Content-Disposition", 'attachment; filename="kaser-games-certificate.crt"')
        self.send_header("Content-Length", str(len(der)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(der)

    def send_setup(self):
        page = (WEB_DIR / "setup.html").read_text(encoding="utf-8")
        page = page.replace("__HAS_CA__", "true" if self.server.ca_cert else "false")
        page = page.replace("__HTTPS_PORT__", str(self.server.https_port))
        self.send_bytes(page.encode(), "text/html; charset=utf-8")

    # -- routing
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(url.path)
        query = urllib.parse.parse_qs(url.query)
        if path == "/kaser-games-certificate.crt":
            return self.send_ca()
        if path == "/setup" or self.plain_from_elsewhere():
            return self.send_setup()
        if path == "/api/ping":
            # The setup page (on http://) asks this over https:// to see whether
            # this device trusts the certificate yet.
            self.corp = "cross-origin"
            return self.send_bytes(b"ok", "text/plain")
        if path in ("/", "/index.html"):
            return self.send_file(WEB_DIR / "index.html")
        if path == "/play":
            return self.send_file(WEB_DIR / "play.html")
        if path == "/sw.js":
            js = (WEB_DIR / "sw.js").read_text(encoding="utf-8").replace("__VERSION__", web_version())
            return self.send_bytes(js.encode(), "text/javascript")
        if path == "/manifest.webmanifest":
            return self.send_file(WEB_DIR / "manifest.webmanifest")
        if path in ("/app-icon.png", "/favicon.ico"):
            g = GAMES.get("Sherlock") or next(iter(GAMES.values()), None)
            p = icon_png(g) if g else None
            return self.send_file(p) if p else self.not_found()
        if path == "/api/games":
            return self.send_json([
                {"name": g.name, "engine": g.engine,
                 "version": pack_index(g)["version"] if g.engine else ""} for g in GAMES.values()
            ])
        if path.startswith("/api/pack/"):
            return self.pack_api(path[len("/api/pack/"):], query)
        if path.startswith("/api/saves/"):
            g = GAMES.get(path[len("/api/saves/"):])
            return self.send_json(save_files(g)) if g else self.not_found()
        if path.startswith("/api/icon/"):
            g = GAMES.get(path[len("/api/icon/"):])
            p = icon_png(g) if g else None
            return self.send_file(p) if p else self.not_found()
        if path == "/api/soundbank":
            return self.send_file(SOUNDBANK) if SOUNDBANK else self.not_found()
        if path.startswith("/api/info/"):
            g = GAMES.get(path[len("/api/info/"):])
            return self.send_json({"name": g.name, "engine": g.engine, "beta": g.beta, **g.shown_paths()}) if g else self.not_found()
        if path.startswith("/api/g/"):
            return self.game_api("GET", path, query)
        if path.startswith("/web/"):
            rel = posixpath.normpath(path[len("/web/"):])
            if rel.startswith("..") or rel.startswith("/"):
                return self.not_found()
            return self.send_file(WEB_DIR / rel)
        return self.not_found()

    def pack_api(self, rest: str, query):
        name, _, what = rest.rpartition("/")
        g = GAMES.get(name)
        if g is None or not g.engine:
            return self.not_found()
        index, paths = _pack(g)
        if what == "index":
            return self.send_json({"name": g.name, "engine": g.engine, "beta": g.beta, **g.shown_paths(), **index})
        if what != "data":
            return self.not_found()
        if (query.get("v") or [""])[0] != index["version"]:
            return self.send_bytes(b"game changed", "text/plain", HTTPStatus.CONFLICT)
        # Stream the files back to back without holding them all in memory.
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(index["total"]))
        self.end_headers()
        if self.command == "HEAD":
            return
        for (rel, size, _), real in zip(index["files"], paths):
            with open(real, "rb") as f:
                left = size
                while left > 0:
                    chunk = f.read(min(left, 1 << 20))
                    if not chunk:      # file shrank: pad so offsets stay right
                        chunk = b"\0" * left
                    self.wfile.write(chunk)
                    left -= len(chunk)

    def do_PUT(self):
        if self.plain_from_elsewhere():
            return self.send_bytes(b"use https", "text/plain", HTTPStatus.FORBIDDEN)
        url = urllib.parse.urlsplit(self.path)
        self.game_api("PUT", urllib.parse.unquote(url.path), urllib.parse.parse_qs(url.query))

    def do_POST(self):
        if self.plain_from_elsewhere():
            return self.send_bytes(b"use https", "text/plain", HTTPStatus.FORBIDDEN)
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
            names = os.listdir(d)
            if d == game.resources and kpath.startswith("pgm"):
                names += [real for real, _ in game.shared.values()]
            for name in sorted(names, key=str.lower):
                if name.startswith("."):
                    continue
                if fnmatch.fnmatch(name.lower(), pattern.lower()) or pattern in ("*.*", "*"):
                    is_dir = name.lower() in game.shared if d == game.resources else False
                    entries.append({"name": name, "dir": is_dir or (d / name).is_dir()})
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

        if method == "POST" and op == "rename":
            to = (query.get("to") or [""])[0]
            src = resolve(game, kpath)
            dst = resolve(game, to, must_exist=False) if to.startswith("app/") else None
            if not src or not dst:
                return self.not_found()
            try:
                os.replace(src, dst)
            except OSError:
                return self.send_bytes(b"failed", "text/plain", HTTPStatus.CONFLICT)
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
    ap.add_argument("--cert", default=str(ROOT / "cert.pem"), help="TLS certificate (default: cert.pem)")
    ap.add_argument("--key", default=str(ROOT / "key.pem"), help="TLS private key (default: key.pem)")
    ap.add_argument("--http", action="store_true", help="serve plain HTTP even if a certificate exists")
    ap.add_argument("--local", action="store_true", help="only accept connections from this computer")
    ap.add_argument("--games", action="append", default=[], metavar="FOLDER",
                    help="another folder holding games (e.g. where the Windows games are installed); "
                         "may be given more than once")
    args = ap.parse_args()

    global GAMES
    GAMES = find_games([Path(g).expanduser() for g in args.games])

    missing = [f for f in ("index.html", "play.js", "kint5.wasm", "kint6.wasm") if not (WEB_DIR / f).exists()]
    if missing:
        sys.exit(f"Some files are missing from {WEB_DIR} ({', '.join(missing)}).\n"
                 "The zip was probably unzipped without its folders.  Unzip it again,\n"
                 "keeping the folders (in Windows: right-click the zip > Extract All...).")
    SAVES_DIR.mkdir(exist_ok=True)

    # Other devices need https://.  This computer can use http://localhost.
    cert = key = None
    own_cert = False          # the user's own (mkcert) certificate: trusted here too
    lan = [] if args.local else lan_addresses()
    if not args.http:
        if Path(args.cert).exists() and Path(args.key).exists():
            cert, key, own_cert = args.cert, args.key, True
        elif not args.local:
            if certs.available():
                try:
                    cert, key, new_ca = certs.ensure(lan)
                    if new_ca:
                        print(f"Made a security certificate for this computer in {certs.TLS_DIR}")
                except Exception as err:      # never let this stop the games on this computer
                    print(f"Couldn't make a security certificate ({err}); other devices won't be able to play.")
            else:
                print("Tablets, phones and other computers can't play until the 'cryptography' package is installed:\n"
                      f"    {'py' if IS_WINDOWS else 'python3'} -m pip install cryptography\n"
                      "  (start-windows.bat does this for you), then start the server again.")

    httpd = make_server(args.local, args.port)
    httpd.verbose = args.verbose
    if cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        httpd.ssl_ctx = ctx
        httpd.ca_cert = mkcert_ca() if own_cert else certs.CA_CERT
        httpd.https_port = args.port
    setupd = None
    if lan and cert:
        try:
            setupd = make_server(False, args.port + 1, setup=True)
            setupd.ca_cert, setupd.https_port, setupd.verbose = httpd.ca_cert, args.port, args.verbose
            threading.Thread(target=setupd.serve_forever, daemon=True).start()
        except OSError as err:
            print(f"Couldn't open the setup port {args.port + 1} ({err}).")

    url = f"{'https' if own_cert else 'http'}://localhost:{args.port}/"
    print(f"Found {len(GAMES)} games.  On this computer, open {url}  (Ctrl+C to stop)")
    if not GAMES:
        print("  No games found.  Tell the server where they are installed, for example:\n"
              '    py server.py --games "C:\\Program Files (x86)\\Everett Kaser Software"')
    if not SOUNDBANK:
        print("  No General MIDI sound bank found, so there will be no music "
              "(put one next to server.py as soundbank.sf2).")
    if lan and cert:
        sport = args.port + 1 if setupd else args.port
        print(f"Tablets, phones and other computers: open http://{lan[0]}:{sport}/")
        print("   The first time, it shows how to set the device up; after that it goes straight to the games"
              f" (at https://{lan[0]}:{args.port}/).")
        print(f"   If Chrome says ERR_TOO_MANY_RETRIES, open https://{lan[0]}:{args.port}/setup instead"
              " and tap Advanced, then Proceed.")
        name = bonjour_name()
        if name:
            print(f"   or, by name (stays the same if the address changes): http://{name}:{sport}/")
    if args.open:
        if IS_MAC:
            subprocess.run(["open", "-a", "Google Chrome", url], check=False)
        else:
            webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
