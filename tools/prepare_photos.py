#!/usr/bin/env python3
"""Prepare photos for the website.

For each photo this script:
  * turns it upright (applies the camera's orientation flag),
  * strips ALL metadata (EXIF, GPS location, camera serials, XMP, comments),
  * writes WebP files at 480, 960 and 1440 px wide plus one 960 px JPEG
    fallback to public/assets/photos/,
  * prints the <picture> markup to paste into the page.

Only publish photos you have the subject's permission (a release) to use.

Usage (from the repository root; needs Pillow: pip install -r tools/requirements.txt):

    .venv/bin/python tools/prepare_photos.py PHOTO.jpg short-name [PHOTO2.jpg name2 ...]

Run tools/audit_site.py afterward: it fails if any published image still
carries metadata.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "public" / "assets" / "photos"
WEBP_WIDTHS = (480, 960, 1440)
JPEG_WIDTH = 960


def clean_copy(im: Image.Image) -> Image.Image:
    """Pixels only: a brand-new image carries no info/metadata at all."""
    im = ImageOps.exif_transpose(im).convert("RGB")
    fresh = Image.new("RGB", im.size)
    fresh.paste(im)
    return fresh


def resized(im: Image.Image, width: int) -> Image.Image:
    if im.width <= width:
        return im.copy()
    height = round(im.height * width / im.width)
    return im.resize((width, height), Image.LANCZOS)


def prepare(src: Path, name: str) -> None:
    if not name.replace("-", "").isalnum() or name.lower() != name:
        raise SystemExit(f"use a short lower-case name with dashes, not {name!r}")
    with Image.open(src) as original:
        base = clean_copy(original)
    OUT.mkdir(parents=True, exist_ok=True)

    srcset = []
    for w in sorted({min(w, base.width) for w in WEBP_WIDTHS}):  # never upscale
        im = resized(base, w)
        path = OUT / f"{name}-{im.width}.webp"
        im.save(path, "WEBP", quality=80, method=6)
        srcset.append(f"assets/photos/{path.name} {im.width}w")

    jpg = resized(base, JPEG_WIDTH)
    jpg_path = OUT / f"{name}-{jpg.width}.jpg"
    jpg.save(jpg_path, "JPEG", quality=82, optimize=True, progressive=True)

    h = round(base.height * jpg.width / base.width)
    print(f"\n{name}: {base.width}x{base.height} source")
    print("<picture>")
    print(f'  <source type="image/webp" srcset="{", ".join(srcset)}" sizes="(min-width: 60em) 50vw, 100vw">')
    print(f'  <img src="assets/photos/{jpg_path.name}" alt="DESCRIBE THE PHOTO" '
          f'width="{jpg.width}" height="{h}" loading="lazy" decoding="async">')
    print("</picture>")


def main(argv: list[str]) -> int:
    if len(argv) < 2 or len(argv) % 2:
        print(__doc__)
        return 2
    for src, name in zip(argv[0::2], argv[1::2]):
        prepare(Path(src), name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
