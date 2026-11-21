#!/usr/bin/env python3
"""
Copy saves from the native games into the browser version.

The native games keep their files in
    Mac:     ~/Library/Application Support/Everett Kaser Software/<EKSGameName>/
    Windows: Documents\\<install folder name>\\<game folder name>\\
             (e.g. Documents\\Everett Kaser Software\\Sherlock\\)
and the browser version keeps them in
    saves/<game name>/
with the same layout.  This copies files across without overwriting anything
that already exists in saves/ (use --overwrite to replace, after making a
backup copy of each replaced file as <name>.bak).  The native files are never
changed.  Games are found the same way server.py finds them.

    python3 tools/import_native_saves.py            # copy
    python3 tools/import_native_saves.py --dry-run  # just show what would happen
    python3 tools/import_native_saves.py --overwrite --game Sherlock
    py tools\\import_native_saves.py --games "D:\\Games\\Everett Kaser Software"   # Windows
"""
import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import server  # noqa: E402  (game discovery and native save locations)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="show what would be copied")
    ap.add_argument("--overwrite", action="store_true", help="replace existing browser saves (keeps .bak copies)")
    ap.add_argument("--game", help="only this game (name as shown in the launcher)")
    ap.add_argument("--games", action="append", default=[], metavar="FOLDER",
                    help="another folder holding games, as for server.py")
    args = ap.parse_args()

    for name, game in server.find_games([Path(g).expanduser() for g in args.games]).items():
        if args.game and args.game.lower() != name.lower():
            continue
        src = game.native_saves
        if not src.is_dir():
            continue
        copied = kept = 0
        for f in src.rglob("*"):
            if f.is_dir() or f.name in (".DS_Store", "desktop.ini"):
                continue
            dst = ROOT / "saves" / name / f.relative_to(src)
            if dst.exists() and not args.overwrite:
                kept += 1
                continue
            if not args.dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    shutil.copy2(dst, dst.with_name(dst.name + ".bak"))
                shutil.copy2(f, dst)
            copied += 1
        if copied or kept:
            note = f", kept {kept} existing" if kept else ""
            print(f"{'would copy' if args.dry_run else 'copied'} {copied:3d}{note}  {name}")


if __name__ == "__main__":
    main()
