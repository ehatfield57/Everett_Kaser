#!/usr/bin/env python3
"""
Copy saves from the native Mac apps into the browser version.

The Mac apps keep their files in
    ~/Library/Application Support/Everett Kaser Software/<EKSGameName>/
and the browser version keeps them in
    saves/<game name>/
with the same layout.  This copies files across without overwriting anything
that already exists in saves/ (use --overwrite to replace, after making a
backup copy of each replaced file as <name>.bak).  The native files are never
changed.

    python3 tools/import_native_saves.py            # copy
    python3 tools/import_native_saves.py --dry-run  # just show what would happen
    python3 tools/import_native_saves.py --overwrite --game Sherlock
"""
import argparse
import plistlib
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NATIVE = Path.home() / "Library" / "Application Support" / "Everett Kaser Software"


def games():
    for bundle in sorted((ROOT / "games").iterdir()):
        if bundle.suffix != ".app":
            continue
        name = bundle.name[:-4].removesuffix(" LIC")
        try:
            with open(bundle / "Contents" / "Info.plist", "rb") as f:
                eks = plistlib.load(f).get("EKSGameName") or name
        except (OSError, plistlib.InvalidFileException):
            eks = name
        yield name, eks


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="show what would be copied")
    ap.add_argument("--overwrite", action="store_true", help="replace existing browser saves (keeps .bak copies)")
    ap.add_argument("--game", help="only this game (name as shown in the launcher)")
    args = ap.parse_args()

    for name, eks in games():
        if args.game and args.game.lower() != name.lower():
            continue
        src = NATIVE / eks
        if not src.is_dir():
            continue
        copied = kept = 0
        for f in src.rglob("*"):
            if f.is_dir() or f.name == ".DS_Store":
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
