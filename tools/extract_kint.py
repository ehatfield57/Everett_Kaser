#!/usr/bin/env python3
"""
Unpack Everett Kaser's KINT downloads into kint_src/ for building.

    python3 tools/extract_kint.py [mskint50.zip] [kint_6_3_0.zip]

Plain `unzip` stops partway through the KINT 6 zip because one help file has
an accented name stored in an old encoding; this handles it.
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = {"k5": "mskint50.zip", "k6": "kint_6_3_0.zip"}


def extract(zip_path: Path, out: Path):
    count = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename
            if not info.flag_bits & 0x800:          # not flagged as UTF-8
                raw = name.encode("cp437")
                try:
                    name = raw.decode("utf-8")
                except UnicodeDecodeError:
                    name = raw.decode("cp1252", "replace")
            dest = (out / name).resolve()
            if out.resolve() not in dest.parents and dest != out.resolve():
                sys.exit(f"refusing to extract outside {out}: {name}")
            if name.endswith("/"):
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(info))
            count += 1
    print(f"{zip_path.name}: {count} files -> {out.relative_to(ROOT)}")


def main():
    given = [Path(a) for a in sys.argv[1:]]
    for sub, default in TARGETS.items():
        zip_path = next((p for p in given if p.name.lower() == default), ROOT / default)
        if not zip_path.exists():
            print(f"missing {default} (download it from https://kaser.com/kint.html)")
            continue
        extract(zip_path, ROOT / "kint_src" / sub)


if __name__ == "__main__":
    main()
