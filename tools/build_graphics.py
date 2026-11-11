#!/usr/bin/env python3
"""Build the site's large lettering and illustrations as plain SVG.

The website loads no webfonts. Every large headline is drawn ahead of time:
this script shapes the text with HarfBuzz (so kerning is right), converts
each glyph into vector paths and writes a small, self-contained SVG to
public/assets/type/. It also draws the swatch-fan illustration.

Typeface: Roboto Condensed (tools/fonts/, SIL Open Font License), used here
at build time only and never published. Body text on the site uses each
device's own sans-serif (Roboto on Android, Segoe UI on Windows, San
Francisco on Apple devices).

The SVGs contain only plain shapes with presentation attributes: no
<style>, no <script>, no links, no fonts. (The logos in public/assets/logo/
and the photos in public/assets/photos/ are not generated here.)

Usage (from the repository root):

    python3 -m venv .venv
    .venv/bin/pip install -r tools/requirements.txt
    .venv/bin/python tools/build_graphics.py            # rebuild every image
    .venv/bin/python tools/build_graphics.py --list     # print sizes for <img> tags

To change a headline, edit IMAGES below, re-run the script and update the
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
INK = "#0D0D0D"        # near-black page background
WHITE = "#FFFFFF"

STAR = "✦"        # four-pointed sparkle, drawn by hand (not in the font)
STAR_ADVANCE = 0.62    # em


# Fonts ----------------------------------------------------------------------
@dataclass(frozen=True)
class Style:
    file: str


BOLD = Style("RobotoCondensed-Bold.latin.woff2")
HEAVY = Style("RobotoCondensed-ExtraBold.latin.woff2")


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


def Y(text: str, size: float = 96) -> Line:
    """One line of the hero statement, in yellow."""
    return L(Run(text, HEAVY, LIGHT), size=size)


HERO_ALT = "Portraits. Families. Graduates. Design and print. Made to be seen."

IMAGES: list[Image] = [
    # Hero statement: wide screens (three lines) and phones (six lines)
    Image("hero-statement-wide", HERO_ALT, [
        Y("PORTRAITS. FAMILIES."), Y("GRADUATES. DESIGN AND"), Y("PRINT. MADE TO BE SEEN."),
    ], leading=0.98),
    Image("hero-statement-narrow", HERO_ALT, [
        Y("PORTRAITS."), Y("FAMILIES."), Y("GRADUATES."),
        Y("DESIGN AND"), Y("PRINT. MADE"), Y("TO BE SEEN."),
    ], leading=0.98),

    # Ribbon of large words (decorative)
    Image("band", "Design, Print, Photograph", [
        L(Run("DESIGN", HEAVY, WHITE), Run(f" {STAR} ", HEAVY, LIGHT),
          Run("PRINT", HEAVY, WHITE), Run(f" {STAR} ", HEAVY, LIGHT),
          Run("PHOTOGRAPH", HEAVY, WHITE), Run(f" {STAR} ", HEAVY, LIGHT),
          size=80),
    ], pad=0, hbox="advance"),

    # Section headings
    Image("h-photography", "Photography", [
        L(Run("PHOTOGRAPHY", HEAVY, TANGERINE), size=120),
    ]),
    Image("h-recent-work", "Recent work", [
        L(Run("RECENT", HEAVY, LIGHT), size=120),
        L(Run("WORK", HEAVY, LIGHT), size=120),
    ], leading=0.92),
    Image("h-design-print", "Design + Print", [
        L(Run("DESIGN ", HEAVY, INK), Run("+", HEAVY, CERULEAN_DEEP), Run(" PRINT", HEAVY, INK), size=112),
    ]),
    Image("h-one-studio", "Shoot it. Design it. Print it.", [
        L(Run("SHOOT IT. ", HEAVY, INK), Run("DESIGN IT.", HEAVY, WHITE), size=100),
        L(Run("PRINT IT.", HEAVY, INK), size=100),
    ], leading=0.95),
    Image("h-contact", "Let’s make something.", [
        L(Run("LET’S MAKE", HEAVY, INK), size=120),
        L(Run("SOMETHING.", HEAVY, INK), size=120),
    ], leading=0.92),

    # Large step numerals (decorative; the steps are a numbered list)
    Image("n-01", "01", [L(Run("01", HEAVY, WHITE), size=120)], pad=2),
    Image("n-02", "02", [L(Run("02", HEAVY, WHITE), size=120)], pad=2),
    Image("n-03", "03", [L(Run("03", HEAVY, WHITE), size=120)], pad=2),

    # 404 page
    Image("t-404", "404", [L(Run("404", HEAVY, LIGHT), size=220)]),
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
    for angle, color in ((-33, INK), (-11, CERULEAN), (11, LIGHT), (33, TANGERINE)):
        chips.append(
            f'<g transform="translate(210 334) rotate({angle})">'
            f'<rect x="-46" y="-270" width="92" height="290" rx="6" fill="{WHITE}" '
            f'stroke="{INK}" stroke-opacity=".18" stroke-width="1.5"/>'
            f'<path fill="{color}" d="M-46 -264a6 6 0 0 1 6-6h80a6 6 0 0 1 6 6v164h-92z"/>'
            f'<rect x="-34" y="-86" width="52" height="7" rx="1" fill="{INK}" fill-opacity=".6"/>'
            f'<rect x="-34" y="-72" width="34" height="6" rx="1" fill="{INK}" fill-opacity=".3"/>'
            '</g>')
    rivet = (f'<circle cx="210" cy="334" r="10" fill="{INK}"/>'
             f'<circle cx="210" cy="334" r="3.5" fill="{ALUMINIUM}"/>')
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
