#!/usr/bin/env python3
"""Add photos to the website's photography gallery, then commit and push.

Usage:
    python3 add_photos.py                     # add new photos from ../Photos/general_photography
    python3 add_photos.py some.jpg dir/ ...   # add specific photos or folders
    python3 add_photos.py --no-push           # do everything except commit and push

For each JPEG not already on the site it:
  1. copies the original into assets/photos/full/ with all metadata (EXIF, GPS,
     camera info, XMP) removed. This is lossless: the image data is untouched;
     only the colour profile is kept.
  2. makes a 900px thumbnail in assets/photos/thumb/ (also metadata-free).
  3. rebuilds the gallery in index.html from everything in assets/photos/thumb/.
  4. commits and pushes to GitHub (the live site updates a minute or two later).

Requires macOS (sips) and jpegtran/djpeg (`brew install jpeg-turbo`).
To remove a photo: delete it from assets/photos/full and assets/photos/thumb and rerun.
"""
import argparse
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
DEFAULT_SOURCE = REPO.parent / "Photos" / "general_photography"
FULL = REPO / "assets" / "photos" / "full"
THUMB = REPO / "assets" / "photos" / "thumb"
INDEX = REPO / "index.html"
THUMB_SIZE = 900
THUMB_QUALITY = 80

# EXIF orientation -> lossless jpegtran transform, so photos don't appear rotated
# once the orientation tag is stripped.
ORIENTATION_FIX = {
    "2": ["-flip", "horizontal"],
    "3": ["-rotate", "180"],
    "4": ["-flip", "vertical"],
    "5": ["-transpose"],
    "6": ["-rotate", "90"],
    "7": ["-transverse"],
    "8": ["-rotate", "270"],
}


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw).stdout


def web_name(path: Path) -> str:
    """'2025-11-15 - 2 (2).jpeg' -> '2025-11-15-2-2.jpg'"""
    stem = re.sub(r"[^a-z0-9_]+", "-", path.stem.lower()).strip("-")
    return stem + ".jpg"


def sips_props(path: Path) -> dict:
    out = run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", "-g", "orientation", str(path)])
    return dict(re.findall(r"^\s+(\w+): (\S+)", out, re.M))


def strip_metadata(src: Path, dst: Path, transform=()):
    """Losslessly rewrite a JPEG keeping only the ICC colour profile."""
    base = ["jpegtran", "-copy", "icc", "-optimize", *transform]
    try:
        run([*base, *(["-perfect"] if transform else []), "-outfile", str(dst), str(src)])
    except subprocess.CalledProcessError:
        # Image size isn't a multiple of the JPEG block size; trim the partial edge blocks.
        run([*base, "-trim", "-outfile", str(dst), str(src)])


def metadata_segments(path: Path) -> list:
    """Return any APPn segments other than JFIF and ICC (should be empty)."""
    data = path.read_bytes()
    i, found = 2, []
    while i + 4 <= len(data) and data[i] == 0xFF and data[i + 1] != 0xDA:
        marker = data[i + 1]
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        payload = data[i + 4:i + 16]
        if 0xE0 <= marker <= 0xEF or marker == 0xFE:
            ok = (marker == 0xE0 and payload.startswith(b"JFIF")) or (
                marker == 0xE2 and payload.startswith(b"ICC_PROFILE"))
            if not ok:
                found.append(f"APP{marker - 0xE0}" if marker != 0xFE else "COM")
        i += 2 + length
    return found


def pixels_hash(path: Path) -> str:
    return subprocess.run(f'djpeg -ppm "{path}" | md5', shell=True, check=True,
                          capture_output=True, text=True).stdout.strip()


def add_photo(src: Path) -> bool:
    name = web_name(src)
    if (FULL / name).exists() and (THUMB / name).exists():
        return False
    orientation = sips_props(src).get("orientation", "1")
    transform = ORIENTATION_FIX.get(orientation, [])

    strip_metadata(src, FULL / name, transform)
    if not transform and pixels_hash(src) != pixels_hash(FULL / name):
        sys.exit(f"ERROR: image data changed for {src.name}; aborting.")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_thumb = Path(tmp) / name
        run(["sips", "-Z", str(THUMB_SIZE), "-s", "formatOptions", str(THUMB_QUALITY),
             str(FULL / name), "--out", str(tmp_thumb)])
        strip_metadata(tmp_thumb, THUMB / name)

    for p in (FULL / name, THUMB / name):
        leftover = metadata_segments(p)
        if leftover:
            sys.exit(f"ERROR: metadata {leftover} still in {p}; aborting.")
    note = f" (rotated, orientation {orientation})" if transform else ""
    print(f"  added {src.name} -> {name}{note}")
    return True


def rebuild_gallery():
    rows = []
    for thumb in sorted(THUMB.glob("*.jpg")):
        if not (FULL / thumb.name).exists():
            continue
        p = sips_props(thumb)
        rows.append(
            f'      <button data-full="/assets/photos/full/{thumb.name}">'
            f'<img src="/assets/photos/thumb/{thumb.name}" width="{p["pixelWidth"]}" '
            f'height="{p["pixelHeight"]}" loading="lazy" alt="Photograph"></button>')
    html = INDEX.read_text()
    new, n = re.subn(r'(<div class="gallery" id="gallery">\n).*?(\n    </div>)',
                     lambda m: m.group(1) + "\n".join(rows) + m.group(2), html, flags=re.S)
    if n != 1:
        sys.exit("ERROR: couldn't find the gallery block in index.html.")
    INDEX.write_text(new)
    return len(rows)


def git(*args):
    return subprocess.run(["git", *args], cwd=REPO, check=True, text=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", type=Path, help=f"photos or folders (default: {DEFAULT_SOURCE})")
    ap.add_argument("--no-push", action="store_true", help="update files but don't commit or push")
    args = ap.parse_args()

    for tool in ("sips", "jpegtran", "djpeg"):
        if not shutil.which(tool):
            sys.exit(f"ERROR: '{tool}' not found. Install with: brew install jpeg-turbo")

    sources = []
    for p in args.paths or [DEFAULT_SOURCE]:
        p = p.expanduser()
        if p.is_dir():
            sources += sorted(q for q in p.iterdir() if q.is_file())
        elif p.is_file():
            sources.append(p)
        else:
            sys.exit(f"ERROR: {p} not found.")

    FULL.mkdir(parents=True, exist_ok=True)
    THUMB.mkdir(parents=True, exist_ok=True)

    added = 0
    for src in sources:
        if src.name.startswith("."):
            continue
        if src.suffix.lower() not in (".jpg", ".jpeg"):
            print(f"  skipped {src.name} (only JPEG is supported; export it as .jpg first)")
            continue
        added += add_photo(src)

    total = rebuild_gallery()
    print(f"{added} new photo(s); gallery now has {total}.")

    if args.no_push:
        return
    git("add", "assets/photos", "index.html")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO).returncode == 0:
        print("Nothing to commit.")
        return
    git("commit", "-q", "-m", f"Add {added} photo(s) to gallery")
    git("pull", "-q", "--rebase", "origin", "master")
    git("push", "-q", "origin", "master")
    print("Pushed. The live site updates in a minute or two: https://yotamvaknin.github.io/")


if __name__ == "__main__":
    main()
