#!/usr/bin/env python3
"""Make a static copy of the games site: plain files that any web server can
serve (python3 -m http.server, GitHub Pages, an ordinary web host), with no
server.py behind them.

    python3 tools/make_static.py                      # every game in games/
    python3 tools/make_static.py --game Sherlock7 --game Crocotile
    cd static && python3 -m http.server 8000 --bind 127.0.0.1         # then http://localhost:8000/

What it writes (into static/ unless --out says otherwise):

    index.html, play.html, sw.js, manifest.webmanifest, app-icon.png
    web/            the interpreters and page code (web/config.js says "static")
    games.json      the list of games: name, version, icon, where its files are
    icons/          one icon per game
    packs/<game>/   <version>.json (the game's file list) and <version>.bin (its
                    files back to back), the same pack server.py sends
    soundbank.bin   the General MIDI sound bank the music plays with
    <game>/         each game's own page (index.html, from web/game.html), its
                    app manifest and a copy of play.html, so the game can be
                    installed as an app of its own (e.g. Sherlock7/)

Running it again only rewrites a game's pack when the game has changed.

The browser only runs the games on a secure page: https://, or http://localhost
on this computer.  The site holds copies of the games (and, by default, macOS's
own sound bank), so don't put it anywhere public unless Everett says so; for a
public site pass --soundbank with a freely licensed General MIDI .sf2.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import server  # noqa: E402

WEB = ROOT / "web"
PAGES = ["index.html", "play.html"]
NOT_COPIED = {"sw.js", "config.js", "setup.html", "game.html"}   # rewritten here, or server.py only
SITE_DIRS = {"web", "icons", "packs"}
GAME_PAGE_MARK = b"web/gamepage.js"       # how a game's folder is recognised when cleaning up


def slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-") or "game"
    return s + "-game" if s.lower() in SITE_DIRS else s


def shown_paths(g: server.Game) -> dict:
    """Folder paths the game is told it lives in.  The MESH games work out which
    game they are from these, so they keep the real folder names, but not
    anything about this computer or its user."""
    if g.mac:
        return {"pgm": f"/Applications/{g.bundle.name}/Contents/Resources/",
                "app": f"/Users/player/Library/Application Support/Everett Kaser Software/{g.eks_name}/"}
    return {"pgm": f"C:\\Everett Kaser Software\\{g.bundle.name}\\",
            "app": f"C:\\Users\\player\\Documents\\Everett Kaser Software\\{g.bundle.name}\\"}


def write_if_changed(path: Path, data: bytes) -> None:
    if path.exists() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def copy_site(out: Path) -> str:
    """The pages and the code; returns a version string that changes with them."""
    h = hashlib.sha1()
    shutil.rmtree(out / "web", ignore_errors=True)
    for src in sorted(WEB.rglob("*")):
        rel = src.relative_to(WEB).as_posix()
        if not src.is_file() or src.name.startswith(".") or rel in NOT_COPIED:
            continue
        dest = (out / rel) if rel in PAGES or rel == "manifest.webmanifest" else (out / "web" / rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = src.read_bytes()
        write_if_changed(dest, data)
        h.update(rel.encode() + b"\0" + data)
    config = b"// Written by tools/make_static.py: this is a static site (see web/config.js in the project).\n" \
             b"self.KASER_STATIC = true;\n"
    write_if_changed(out / "web" / "config.js", config)
    h.update(config)
    return h.hexdigest()[:16]


def build_game(g: server.Game, out: Path) -> dict:
    s = slug(g.name)
    index, paths = server._pack(g)
    ver = index["version"]
    folder = out / "packs" / s
    folder.mkdir(parents=True, exist_ok=True)
    data = folder / f"{ver}.bin"
    if not (data.exists() and data.stat().st_size == index["total"]):
        print(f"  {g.name}: {index['total'] / 1e6:.0f} MB", flush=True)
        tmp = data.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            for (_, size, _), real in zip(index["files"], paths):
                with open(real, "rb") as src:
                    chunk = src.read(size)
                f.write(chunk.ljust(size, b"\0"))     # a file that shrank: keep the offsets right
        os.replace(tmp, data)
    else:
        print(f"  {g.name}: unchanged", flush=True)
    listing = {"name": g.name, "engine": g.engine, "beta": g.beta, **shown_paths(g), **index,
               "data": data.name}
    write_if_changed(folder / f"{ver}.json", json.dumps(listing, separators=(",", ":")).encode())
    for old in folder.iterdir():                     # earlier versions of this game
        if old.name not in (data.name, f"{ver}.json"):
            old.unlink()

    entry = {"name": g.name, "engine": g.engine, "version": ver, "total": index["total"],
             "beta": g.beta, "index": f"packs/{s}/{ver}.json"}
    icon = server.icon_png(g)
    if icon:
        png = icon.read_bytes()
        if icon.suffix.lower() == ".ico":      # a Windows game: browsers want PNG to install an app
            png = ico_to_png(png) or png
        ext = ".png" if png.startswith(b"\x89PNG") else icon.suffix.lower()
        dest = out / "icons" / (s + ext)
        write_if_changed(dest, png)
        entry["icon"] = f"icons/{dest.name}"
    entry["page"] = f"{s}/"
    write_game_pages(out / s, entry)
    return entry


# ------------------------------------------------------------ .ico -> .png
def ico_to_png(data: bytes) -> bytes | None:
    """The biggest picture in a Windows .ico file, as PNG.  Big icons are
    usually stored as PNG already; smaller ones are bitmaps (32-bit with
    alpha, or 24/8/4/1-bit with a transparency mask), converted here."""
    try:
        _, kind, count = struct.unpack_from("<HHH", data, 0)
        if kind != 1:
            return None
        best = None
        for i in range(count):
            w, h, _, _, _, bits, size, off = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
            key = (w or 256, bits)
            if best is None or key > best[0]:
                best = (key, data[off:off + size])
        if not best:
            return None
        img = best[1]
        return img if img.startswith(b"\x89PNG") else dib_to_png(img)
    except (struct.error, ValueError, IndexError, zlib.error):
        return None


def dib_to_png(dib: bytes) -> bytes | None:
    hsize, w, h2, _, bits, compression = struct.unpack_from("<IiiHHI", dib, 0)
    if compression != 0 or bits not in (1, 4, 8, 24, 32):
        return None
    h = abs(h2) // 2                          # the height counts the image and its mask
    ncolors = struct.unpack_from("<I", dib, 32)[0] or (1 << bits if bits <= 8 else 0)
    pal_at = hsize
    pixels_at = pal_at + 4 * ncolors
    stride = ((w * bits + 31) // 32) * 4
    mask_at = pixels_at + stride * h
    mask_stride = ((w + 31) // 32) * 4
    palette = [dib[pal_at + 4 * i: pal_at + 4 * i + 3] for i in range(ncolors)]   # B, G, R
    has_alpha = bits == 32 and any(dib[pixels_at + 3 + 4 * i] for i in range(w * h))
    rows = []
    for y in range(h):
        src = pixels_at + (h - 1 - y) * stride            # bitmaps are stored bottom up
        msk = mask_at + (h - 1 - y) * mask_stride
        row = bytearray(b"\0")                          # PNG filter: none
        for x in range(w):
            if bits == 32:
                b, g, r, a = dib[src + 4 * x: src + 4 * x + 4]
            else:
                if bits == 24:
                    b, g, r = dib[src + 3 * x: src + 3 * x + 3]
                else:
                    per = 8 // bits
                    byte = dib[src + x // per]
                    idx = (byte >> (8 - bits * (x % per + 1))) & ((1 << bits) - 1)
                    b, g, r = palette[idx]
                a = 255
            if not has_alpha:
                transparent = msk + mask_stride <= len(dib) and dib[msk + x // 8] >> (7 - x % 8) & 1
                a = 0 if transparent else 255
            row += bytes((r, g, b, a))
        rows.append(bytes(row))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def write_game_pages(folder: Path, entry: dict) -> None:
    """The game's own folder, which can be installed as an app of its own:
    index.html (the install and start page), manifest.webmanifest (the app's
    name and icon) and play.html (the game page, kept inside the app's folder;
    its <base> points at the site, and KASER_HOME back at index.html)."""
    icon_url = "../" + entry["icon"] if "icon" in entry else "../app-icon.png"
    game = {k: entry[k] for k in ("name", "version", "total", "index") if k in entry}
    if "icon" in entry:
        game["icon"] = entry["icon"]
    page = (WEB / "game.html").read_text(encoding="utf-8")
    page = (page.replace("__TITLE__", html.escape(entry["name"]))
                .replace("__ICON__", html.escape(icon_url))
                .replace("__GAME__", json.dumps(game).replace("</", "<\\/")))
    write_if_changed(folder / "index.html", page.encode())

    icon_type = "image/x-icon" if entry.get("icon", "").endswith(".ico") else "image/png"
    manifest = {
        "name": entry["name"], "short_name": entry["name"], "start_url": "./", "scope": "./",
        "display": "standalone", "display_override": ["fullscreen"],
        "background_color": "#1d1b18", "theme_color": "#1d1b18",
        "icons": [{"src": icon_url, "sizes": "256x256", "type": icon_type}],
    }
    write_if_changed(folder / "manifest.webmanifest", json.dumps(manifest, indent=1).encode())

    play = (WEB / "play.html").read_text(encoding="utf-8")
    head = play.index("<head>") + len("<head>")
    play = (play[:head] + '\n<base href="../">'
            + "\n<script>self.KASER_HOME = new URL('./', location.href).href;</script>" + play[head:])
    write_if_changed(folder / "play.html", play.encode())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(ROOT / "static"), help="folder to write (default: static/)")
    ap.add_argument("--game", action="append", default=[], metavar="NAME",
                    help="only this game (repeatable; default: every game)")
    ap.add_argument("--games", action="append", default=[], metavar="FOLDER", type=Path,
                    help="another folder to look for games in, as with server.py")
    ap.add_argument("--soundbank", type=Path, help="a General MIDI .sf2 or .dls for the music "
                    "(default: the one server.py uses)")
    args = ap.parse_args()

    out = Path(args.out).resolve()
    if out == ROOT or out == WEB:
        sys.exit("--out must be a folder of its own")
    games = server.find_games(args.games)
    if args.game:
        missing = [n for n in args.game if n not in games]
        if missing:
            sys.exit("No game called " + ", ".join(missing) + ". The games are: " + ", ".join(games))
        games = {n: games[n] for n in args.game}
    games = {n: g for n, g in games.items() if g.engine}
    if not games:
        sys.exit("No games found: put links to them in games/ (see games/README.txt).")

    out.mkdir(parents=True, exist_ok=True)
    print(f"Writing {out}")
    version = copy_site(out)

    print(f"{len(games)} game{'s' * (len(games) != 1)}:")
    entries = [build_game(g, out) for g in sorted(games.values(), key=lambda g: g.name.lower())]
    write_if_changed(out / "games.json", json.dumps(entries, indent=1).encode())

    # Games no longer in the list
    keep = {slug(e["name"]) for e in entries}
    for d in (out / "packs").iterdir():
        if d.is_dir() and d.name not in keep:
            shutil.rmtree(d)
    if (out / "icons").is_dir():
        for f in (out / "icons").iterdir():
            if f.stem not in keep:
                f.unlink()
    for d in out.iterdir():
        page = d / "index.html"
        if (d.is_dir() and d.name not in keep and d.name not in SITE_DIRS
                and page.is_file() and GAME_PAGE_MARK in page.read_bytes()):
            shutil.rmtree(d)

    bank = args.soundbank or server.SOUNDBANK
    if bank and bank.is_file():
        write_if_changed(out / "soundbank.bin", bank.read_bytes())
    else:
        print("No sound bank found, so the games will have no music (see --soundbank).")

    first = next((e for e in entries if e["name"] in ("Sherlock7", "Sherlock") and "icon" in e), None) \
        or next((e for e in entries if "icon" in e), None)
    if first:
        write_if_changed(out / "app-icon.png", (out / first["icon"]).read_bytes())

    # The service worker's version covers the code and pages, so browsers
    # replace their offline copy when any of them changes.
    pages = [p for e in entries for p in (e["page"], e["page"] + "play.html", e["page"] + "manifest.webmanifest")]
    version = hashlib.sha1(version.encode() + (WEB / "game.html").read_bytes()
                           + json.dumps(entries).encode()).hexdigest()[:16]
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    sw = (sw.replace("__VERSION__", version).replace("'__STATIC__'", "'true'")
            .replace("/*GAME_PAGES*/[]", json.dumps(pages)))
    write_if_changed(out / "sw.js", sw.encode())

    total = sum(e["total"] for e in entries)
    print(f"Done: {len(entries)} games, {total / 1e6:.0f} MB.  To try it on this computer:\n"
          f"    cd {out} && python3 -m http.server 8000 --bind 127.0.0.1\n"
          f"then open http://localhost:8000/ in Chrome.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
