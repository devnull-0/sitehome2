#!/usr/bin/env python3
"""Build the site's large decorative lettering and illustration as plain SVG.

The website loads no webfonts. Headings are real text in each device's own
sans-serif (so search engines and screen readers read them directly); the
large decorative characters (the 01/02/03 step numbers and the 404) are
drawn ahead of time by this script: it shapes the text with HarfBuzz,
converts each glyph into vector paths and writes a small, self-contained SVG
to public/assets/type/. It also draws the swatch-fan illustration.

Typeface: Roboto Light (tools/fonts/, SIL Open Font License), used here at
build time only and never published.

The SVGs contain only plain shapes with presentation attributes: no
<style>, no <script>, no links, no fonts. (The logos in public/assets/logo/
and the photos in public/assets/photos/ are not generated here.)

Usage (from the repository root):

    python3 -m venv .venv
    .venv/bin/pip install -r tools/requirements.txt
    .venv/bin/python tools/build_graphics.py            # rebuild every image
    .venv/bin/python tools/build_graphics.py --list     # print sizes for <img> tags

To change one, edit IMAGES below, re-run the script and update the
width/height attributes of the matching <img> in public/*.html with the
numbers printed by --list.
"""

from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

import uharfbuzz as hb
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "tools" / "fonts"
OUT_DIR = ROOT / "public" / "assets" / "type"

# Palette (same values as public/assets/css/site.css) ------------------------
CERULEAN = "#4484CE"
CERULEAN_DEEP = "#2F6DB5"  # cerulean for lettering on light backgrounds (contrast)
ALUMINIUM = "#D9D9D9"
LIGHT = "#F9CF00"      # yellow
TANGERINE = "#F19F4D"
INK = "#1F1F1F"        # charcoal text
WHITE = "#FFFFFF"

STAR = "✦"        # four-pointed sparkle, drawn by hand (not in the font)
STAR_ADVANCE = 0.62    # em


# Fonts ----------------------------------------------------------------------
@dataclass(frozen=True)
class Style:
    file: str


LIGHT_WEIGHT = Style("Roboto-Light.latin.woff2")


# Image description ----------------------------------------------------------
@dataclass
class Run:
    text: str
    style: Style
    fill: str


@dataclass
class Line:
    runs: list[Run]
    size: float              # font size in px (SVG user units)
    indent: float = 0.0      # extra x offset in px
    tracking: float = 0.0    # extra letter spacing, in em


@dataclass
class Image:
    name: str
    title: str
    lines: list[Line]
    leading: float = 0.98    # baseline-to-baseline distance, in em of the line
    pad: float = 4.0         # padding around the ink, px
    align: str = "left"      # left | center
    hbox: str = "ink"        # ink: crop to the letters | advance: keep side spacing
    vbox: str = "ink"        # ink: crop to the letters | line: same box for any text
    extra: list[str] = field(default_factory=list)  # raw extra <path> markup


def L(*runs: Run, size: float, indent: float = 0.0, tracking: float = 0.0) -> Line:
    return Line(list(runs), size, indent, tracking)


IMAGES: list[Image] = [
    # Large step numerals (decorative; the steps are a numbered list)
    Image("n-01", "01", [L(Run("01", LIGHT_WEIGHT, CERULEAN_DEEP), size=120)], pad=2),
    Image("n-02", "02", [L(Run("02", LIGHT_WEIGHT, CERULEAN_DEEP), size=120)], pad=2),
    Image("n-03", "03", [L(Run("03", LIGHT_WEIGHT, CERULEAN_DEEP), size=120)], pad=2),

    # 404 page
    Image("t-404", "404", [
        L(Run("4", LIGHT_WEIGHT, CERULEAN_DEEP), Run("0", LIGHT_WEIGHT, TANGERINE),
          Run("4", LIGHT_WEIGHT, CERULEAN_DEEP), size=220),
    ]),
]


# Rendering ------------------------------------------------------------------
_FONTS: dict[Style, tuple[hb.Font, int]] = {}


def hb_font(style: Style) -> tuple[hb.Font, int]:
    if style not in _FONTS:
        tt = TTFont(FONT_DIR / style.file)
        upem = tt["head"].unitsPerEm
        tt.flavor = None  # woff2 -> plain sfnt bytes for HarfBuzz
        buf = io.BytesIO()
        tt.save(buf)
        _FONTS[style] = (hb.Font(hb.Face(hb.Blob(buf.getvalue()))), upem)
    return _FONTS[style]


def group_runs(runs: list[Run]):
    """Merge neighboring runs that share a style so they shape together
    (keeps kerning across color changes)."""
    groups: list[tuple[Style, str, list[tuple[int, int, str]]]] = []
    for run in runs:
        if groups and groups[-1][0] == run.style:
            style, text, spans = groups[-1]
            start = len(text)
            groups[-1] = (style, text + run.text, spans + [(start, start + len(run.text), run.fill)])
        else:
            groups.append((run.style, run.text, [(0, len(run.text), run.fill)]))
    return groups


def fill_for(cluster: int, spans) -> str:
    for start, end, fill in spans:
        if start <= cluster < end:
            return fill
    return spans[-1][2]


def draw_line(line: Line, baseline_y: float):
    """Return ({fill: RecordingPen}, advance_width) for one line."""
    pens: dict[str, RecordingPen] = {}
    x = line.indent
    for style, text, spans in group_runs(line.runs):
        font, upem = hb_font(style)
        scale = line.size / upem
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(font, buf, {"kern": True, "liga": True})
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            if info.codepoint == 0:
                bad = text[info.cluster]
                if bad == STAR:
                    fill = fill_for(info.cluster, spans)
                    draw_star(pens.setdefault(fill, RecordingPen()), x, baseline_y, line.size)
                    x += STAR_ADVANCE * line.size
                    continue
                raise SystemExit(f"{style.file} has no glyph for {bad!r} (U+{ord(bad):04X})")
            fill = fill_for(info.cluster, spans)
            pen = pens.setdefault(fill, RecordingPen())
            ox = x + pos.x_offset * scale
            oy = baseline_y - pos.y_offset * scale
            # font units are y-up, SVG is y-down
            font.draw_glyph_with_pen(info.codepoint, TransformPen(pen, (scale, 0, 0, -scale, ox, oy)))
            x += pos.x_advance * scale + line.tracking * line.size
    return pens, x


def draw_star(pen, x: float, baseline_y: float, size: float) -> None:
    """Four-pointed sparkle centered on the capital letters."""
    r = size * 0.25           # outer radius
    k = size * 0.04           # waist (how thin the arms get)
    cx = x + STAR_ADVANCE * size / 2
    cy = baseline_y - size * 0.355
    pen.moveTo((cx, cy - r))
    pen.qCurveTo((cx + k, cy - k), (cx + r, cy))
    pen.qCurveTo((cx + k, cy + k), (cx, cy + r))
    pen.qCurveTo((cx - k, cy + k), (cx - r, cy))
    pen.qCurveTo((cx - k, cy - k), (cx, cy - r))
    pen.closePath()


def fmt(n: float) -> str:
    s = f"{n:.1f}"
    s = s.rstrip("0").rstrip(".") if "." in s else s
    return "0" if s in ("-0", "") else s


class CompactPathPen(SVGPathPen):
    def __init__(self):
        super().__init__(None, ntos=fmt)


def render(img: Image) -> tuple[str, float, float]:
    line_pens = []
    y = 0.0
    for i, line in enumerate(img.lines):
        if i == 0:
            y = line.size * 0.8
        else:
            y += line.size * img.leading
        pens, width = draw_line(line, y)
        line_pens.append((pens, width))

    # Measure ink bounds
    bounds = BoundsPen(None)
    widths = []
    for pens, width in line_pens:
        lb = BoundsPen(None)
        for rec in pens.values():
            rec.replay(bounds)
            rec.replay(lb)
        widths.append(lb.bounds)
    x0, y0, x1, y1 = bounds.bounds
    if img.hbox == "advance":
        x0, x1 = 0.0, max(width for _, width in line_pens)
    if img.vbox == "line":  # fixed ascent/descent, so sibling images match in size
        first, last = img.lines[0].size, img.lines[-1].size
        y0, y1 = first * 0.8 - first * 0.74, y + last * 0.27

    # Center-align by shifting whole lines
    by_fill: dict[str, list[tuple[RecordingPen, float]]] = {}
    for (pens, _), lb in zip(line_pens, widths):
        shift = 0.0
        if img.align == "center" and lb:
            shift = ((x1 - x0) - (lb[2] - lb[0])) / 2 - (lb[0] - x0)
        for fill, rec in pens.items():
            by_fill.setdefault(fill, []).append((rec, shift))

    p = img.pad
    px = 0.0 if img.hbox == "advance" else p
    w, h = (x1 - x0) + 2 * px, (y1 - y0) + 2 * p
    dx, dy = -x0 + px, -y0 + p

    paths = []
    for fill, recs in by_fill.items():
        sp = CompactPathPen()
        for rec, shift in recs:
            rec.replay(TransformPen(sp, (1, 0, 0, 1, dx + shift, dy)))
        paths.append(f'<path fill="{fill}" d="{sp.getCommands()}"/>')

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {fmt(w)} {fmt(h)}" '
        f'width="{round(w)}" height="{round(h)}" role="img">'
        f'<title>{escape(img.title)}</title>'
        + "".join(paths) + "".join(img.extra) + "</svg>\n"
    )
    return svg, w, h


# Illustrations --------------------------------------------------------------
def swatch_fan() -> str:
    """A printer's color-swatch fan in the site colors. Decorative."""
    chips = []
    for angle, color in ((-33, CERULEAN_DEEP), (-11, CERULEAN), (11, LIGHT), (33, TANGERINE)):
        chips.append(
            f'<g transform="translate(210 334) rotate({angle})">'
            f'<rect x="-46" y="-270" width="92" height="290" rx="6" fill="{WHITE}" '
            f'stroke="{INK}" stroke-opacity=".14" stroke-width="1.5"/>'
            f'<path fill="{color}" d="M-46 -264a6 6 0 0 1 6-6h80a6 6 0 0 1 6 6v164h-92z"/>'
            f'<rect x="-34" y="-86" width="52" height="7" rx="1" fill="{INK}" fill-opacity=".6"/>'
            f'<rect x="-34" y="-72" width="34" height="6" rx="1" fill="{INK}" fill-opacity=".3"/>'
            '</g>')
    rivet = (f'<circle cx="210" cy="334" r="10" fill="{CERULEAN_DEEP}"/>'
             f'<circle cx="210" cy="334" r="3.5" fill="{WHITE}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 50 420 340" '
            f'width="420" height="340" aria-hidden="true">' + "".join(chips) + rivet + "</svg>\n")


COMPOSITIONS = {
    ROOT / "public" / "assets" / "img" / "swatch-fan.svg": swatch_fan,
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--list", action="store_true", help="print image sizes only")
    ap.add_argument("names", nargs="*", help="only build these images")
    args = ap.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for img in IMAGES:
        if args.names and img.name not in args.names:
            continue
        svg, w, h = render(img)
        if not args.list:
            (OUT_DIR / f"{img.name}.svg").write_text(svg, encoding="utf-8")
        print(f"{img.name:22s} width={round(w)} height={round(h)}  ({len(svg.encode()) / 1024:.1f} KiB)")
    if not args.names and not args.list:
        for path, build in COMPOSITIONS.items():
            svg = build()
            path.write_text(svg, encoding="utf-8")
            print(f"{path.relative_to(ROOT)}  ({len(svg.encode()) / 1024:.1f} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
