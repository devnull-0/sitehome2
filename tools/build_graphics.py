#!/usr/bin/env python3
"""Build the site's large lettering and illustrations as plain SVG.

The website loads no webfonts. Every large heading is drawn ahead of time:
this script shapes the text with HarfBuzz (so kerning and ligatures are
right), converts each glyph into vector paths and writes a small,
self-contained SVG to public/assets/type/. It also draws the illustrations
in public/assets/img/ and the favicon.

Typeface: Georgia, to match the body text. Georgia is a Microsoft font that
cannot be redistributed, so it is not in this repository. If it is installed
on the computer running this script (it is on every Mac and Windows PC) it is
used automatically. Otherwise the script falls back to Gelasio
(tools/fonts/, SIL Open Font License), a free typeface designed as a
metric-compatible alternative to Georgia. Force one with --font.

The SVGs contain only plain shapes with presentation attributes: no
<style>, no <script>, no links, no fonts. Font files are used here at build
time only and are never published. (The logos in public/assets/logo/ are
not generated here.)

Usage (from the repository root):

    python3 -m venv .venv
    .venv/bin/pip install -r tools/requirements.txt
    .venv/bin/python tools/build_graphics.py            # rebuild every image
    .venv/bin/python tools/build_graphics.py --list     # print sizes for <img> tags

To change a heading, edit IMAGES below, re-run the script and update the
width/height attributes of the matching <img> in public/*.html with the
numbers printed by --list.
"""

from __future__ import annotations

import argparse
import io
import os
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

# Warm-neutral palette (same values as public/assets/css/site.css) ----------
LINEN = "#F3EDE3"     # page background
IVORY = "#FBF8F2"     # cards, text on dark sections
SAND = "#E6DCCC"      # alternate light background
OAT = "#CDBDA6"       # borders, decoration
TAUPE = "#9C8775"     # decoration
CAMEL = "#A8835F"     # warm accent (decoration and large lettering only)
MOCHA = "#6E5646"     # buttons, links, dark section
ESPRESSO = "#3A2E26"  # text, darkest section
SHADOW = "#241C17"    # deepest shade (film strip)

STAR = "\u2726"      # four-pointed sparkle, drawn by hand (not in the font)
STAR_ADVANCE = 0.78  # em


# Fonts ----------------------------------------------------------------------
# style -> (file names Georgia may have on Windows/macOS/Linux, Gelasio file)
FONT_FILES = {
    "regular": (("georgia.ttf", "Georgia.ttf"), "Gelasio-Regular.latin.woff2"),
    "bold": (("georgiab.ttf", "Georgia Bold.ttf", "Georgia_Bold.ttf"), "Gelasio-Bold.latin.woff2"),
    "italic": (("georgiai.ttf", "Georgia Italic.ttf", "Georgia_Italic.ttf"), "Gelasio-Italic.latin.woff2"),
    "bolditalic": (("georgiaz.ttf", "Georgia Bold Italic.ttf", "Georgia_Bold_Italic.ttf"),
                   "Gelasio-BoldItalic.latin.woff2"),
}
FONT_SEARCH_DIRS = [
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
    Path.home() / "AppData/Local/Microsoft/Windows/Fonts",
    Path("/System/Library/Fonts/Supplemental"), Path("/Library/Fonts"), Path.home() / "Library/Fonts",
    Path("/usr/share/fonts/truetype/msttcorefonts"), Path("/usr/share/fonts/TTF"),
    Path.home() / ".fonts", Path.home() / ".local/share/fonts",
]


def find_georgia() -> dict[str, Path] | None:
    found = {}
    for style, (names, _) in FONT_FILES.items():
        for d in FONT_SEARCH_DIRS:
            hit = next((d / n for n in names if (d / n).is_file()), None)
            if hit:
                found[style] = hit
                break
    return found if len(found) == len(FONT_FILES) else None


FONT_PATHS: dict[str, Path] = {}


def choose_font(choice: str) -> str:
    georgia = find_georgia() if choice in ("auto", "georgia") else None
    if choice == "georgia" and not georgia:
        raise SystemExit("Georgia (regular, bold, italic, bold italic) was not found on this computer.")
    if georgia:
        FONT_PATHS.update(georgia)
        return "Georgia"
    FONT_PATHS.update({s: FONT_DIR / g for s, (_, g) in FONT_FILES.items()})
    return "Gelasio (Georgia-compatible fallback)"


@dataclass(frozen=True)
class Style:
    face: str  # regular | bold | italic | bolditalic


REGULAR = Style("regular")
BOLD = Style("bold")
ITALIC = Style("italic")
BOLD_ITALIC = Style("bolditalic")


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
    # Band of large words used as a moving ribbon (decorative)
    Image("band", "Design, Print, Photograph", [
        L(Run("Design", BOLD, SAND), Run(f" {STAR} ", BOLD, CAMEL),
          Run("Print", BOLD, SAND), Run(f" {STAR} ", BOLD, CAMEL),
          Run("Photograph", ITALIC, SAND), Run(f" {STAR} ", BOLD, CAMEL),
          size=80),
    ], pad=0, hbox="advance"),

    # Section headings
    Image("h-design-print", "Design & Print", [
        L(Run("Design ", BOLD, ESPRESSO), Run("&", BOLD_ITALIC, MOCHA),
          Run(" Print", BOLD, ESPRESSO), size=104),
    ]),
    Image("h-photography", "Photography", [
        L(Run("Photography", ITALIC, IVORY), size=112),
    ]),
    Image("h-one-studio", "Shoot it. Design it. Print it.", [
        L(Run("Shoot it", BOLD, ESPRESSO), Run(".", BOLD, CAMEL),
          Run(" Design it", ITALIC, MOCHA), Run(".", ITALIC, CAMEL), size=88),
        L(Run("Print it", BOLD, ESPRESSO), Run(".", BOLD, CAMEL), size=88),
    ], leading=1.1),
    Image("h-contact", "Let\u2019s make something.", [
        L(Run("Let\u2019s make", BOLD, IVORY), size=108),
        L(Run("something", ITALIC, IVORY), Run(".", ITALIC, OAT), size=108, indent=2),
    ], leading=1.05),

    # Large step numerals (decorative; the steps are a numbered list)
    Image("n-01", "01", [L(Run("01", ITALIC, CAMEL), size=120)], pad=2, vbox="line"),
    Image("n-02", "02", [L(Run("02", ITALIC, CAMEL), size=120)], pad=2, vbox="line"),
    Image("n-03", "03", [L(Run("03", ITALIC, CAMEL), size=120)], pad=2, vbox="line"),

    # 404 page
    Image("t-404", "404", [
        L(Run("4", BOLD, ESPRESSO), Run("0", ITALIC, CAMEL),
          Run("4", BOLD, ESPRESSO), size=200),
    ]),
]


# Rendering ------------------------------------------------------------------
_FONTS: dict[Style, tuple[hb.Font, int]] = {}


def hb_font(style: Style) -> tuple[hb.Font, int]:
    if style not in _FONTS:
        tt = TTFont(FONT_PATHS[style.face])
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
                raise SystemExit(f"{FONT_PATHS[style.face].name} has no glyph for {bad!r} (U+{ord(bad):04X})")
            fill = fill_for(info.cluster, spans)
            pen = pens.setdefault(fill, RecordingPen())
            ox = x + pos.x_offset * scale
            oy = baseline_y - pos.y_offset * scale
            # font units are y-up, SVG is y-down
            font.draw_glyph_with_pen(info.codepoint, TransformPen(pen, (scale, 0, 0, -scale, ox, oy)))
            x += pos.x_advance * scale + line.tracking * line.size
    return pens, x


def draw_star(pen, x: float, baseline_y: float, size: float) -> None:
    """Four-pointed sparkle centered on the lower-case x-height."""
    r = size * 0.26           # outer radius
    k = size * 0.045          # waist (how thin the arms get)
    cx = x + STAR_ADVANCE * size / 2
    cy = baseline_y - size * 0.25
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

    # Centre-align by shifting whole lines (re-draw shift via transform)
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


def glyph_path(text: str, style: Style, size: float, cx: float, cy: float) -> str:
    """Path data for `text`, with its ink box centered on (cx, cy)."""
    pens, _ = draw_line(L(Run(text, style, "#000"), size=size), 0.0)
    rec = pens["#000"]
    b = BoundsPen(None)
    rec.replay(b)
    x0, y0, x1, y1 = b.bounds
    sp = CompactPathPen()
    rec.replay(TransformPen(sp, (1, 0, 0, 1, cx - (x0 + x1) / 2, cy - (y0 + y1) / 2)))
    return sp.getCommands()


def svg_doc(w: int, h: int, title: str | None, body: str) -> str:
    head = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}"'
    if title:
        return head + f' role="img"><title>{escape(title)}</title>' + body + "</svg>\n"
    return head + ' aria-hidden="true">' + body + "</svg>\n"


def hero_art() -> str:
    """Arch with a striped 70s sun and a giant ampersand: the '&' that joins
    PW&i Studio and Hoffman Images. Decorative."""
    w, h = 520, 640
    amp = glyph_path("&", BOLD, 380, 262, 350)
    stripes = "".join(
        f'<rect x="96" y="{y}" width="328" height="{t}" fill="{MOCHA}"/>'
        for y, t in ((352, 7), (380, 10), (411, 13), (445, 16)))
    body = (
        # arch
        f'<path fill="{MOCHA}" d="M0 640V260A260 260 0 0 1 520 260V640Z"/>'
        # sun, cut by horizontal stripes
        f'<circle cx="260" cy="330" r="158" fill="{CAMEL}"/>' + stripes +
        # horizon lines
        f'<rect x="0" y="488" width="520" height="10" fill="{OAT}"/>'
        f'<rect x="0" y="512" width="520" height="6" fill="{OAT}" opacity=".6"/>'
        # ampersand
        f'<path fill="{IVORY}" d="{amp}"/>'
        # printer's registration mark, bottom left
        f'<g fill="none" stroke="{IVORY}" stroke-width="3">'
        f'<circle cx="58" cy="584" r="16"/><path d="M58 556V612M30 584H86"/></g>'
        # camera aperture, bottom right
        f'<g transform="translate(462 584)"><circle r="22" fill="none" stroke="{IVORY}" stroke-width="3"/>'
        + "".join(f'<path d="M0 0L18 -6" stroke="{IVORY}" stroke-width="3" transform="rotate({a})"/>'
                  for a in range(0, 360, 60)) +
        '</g>'
    )
    return svg_doc(w, h, None, body)


def favicon() -> str:
    """Espresso tile with a linen ampersand."""
    amp = glyph_path("&", BOLD, 44, 32, 32.5)
    body = (f'<rect width="64" height="64" rx="14" fill="{ESPRESSO}"/>'
            f'<path fill="{LINEN}" d="{amp}"/>')
    return svg_doc(64, 64, "PW&i Studio + Hoffman Images", body)




def swatch_fan() -> str:
    """A printer's color-swatch fan in the site colors. Decorative."""
    chips = []
    for angle, color in ((-33, ESPRESSO), (-11, LINEN), (11, CAMEL), (33, MOCHA)):
        chips.append(
            f'<g transform="translate(210 334) rotate({angle})">'
            f'<rect x="-46" y="-270" width="92" height="290" rx="10" fill="{IVORY}" '
            f'stroke="{ESPRESSO}" stroke-opacity=".14" stroke-width="1.5"/>'
            f'<path fill="{color}" d="M-46 -260a10 10 0 0 1 10-10h72a10 10 0 0 1 10 10v160h-92z"/>'
            f'<rect x="-34" y="-86" width="52" height="7" rx="3.5" fill="{ESPRESSO}" fill-opacity=".55"/>'
            f'<rect x="-34" y="-72" width="34" height="6" rx="3" fill="{ESPRESSO}" fill-opacity=".28"/>'
            '</g>')
    rivet = (f'<circle cx="210" cy="334" r="10" fill="{CAMEL}"/>'
             f'<circle cx="210" cy="334" r="3.5" fill="{ESPRESSO}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 50 420 340" '
            f'width="420" height="340" aria-hidden="true">' + "".join(chips) + rivet + "</svg>\n")


def film_strip() -> str:
    """A strip of 35 mm film with four flat-illustration frames:
    portrait, landscape, product, and a camera aperture. Decorative."""
    import math
    holes = "".join(
        f'<rect x="{x}" y="{y}" width="22" height="16" rx="4" fill="{ESPRESSO}"/>'
        for x in range(16, 1000, 40) for y in (12, 232))
    f1 = (  # portrait
        f'<rect x="16" y="40" width="230" height="180" fill="{CAMEL}"/>'
        f'<circle cx="131" cy="80" r="70" fill="{IVORY}" fill-opacity=".22"/>'
        f'<circle cx="131" cy="112" r="33" fill="{IVORY}"/>'
        f'<path fill="{IVORY}" d="M71 220C71 172 99 154 131 154S191 172 191 220Z"/>')
    f2 = (  # landscape
        f'<rect x="262" y="40" width="230" height="180" fill="{LINEN}"/>'
        f'<circle cx="424" cy="98" r="26" fill="{CAMEL}"/>'
        f'<path fill="{TAUPE}" d="M262 176Q318 122 378 160T492 148V220H262Z"/>'
        f'<path fill="{MOCHA}" d="M262 202Q340 172 420 196T492 190V220H262Z"/>')
    f3 = (  # product
        f'<rect x="508" y="40" width="230" height="180" fill="{MOCHA}"/>'
        f'<rect x="508" y="186" width="230" height="34" fill="{TAUPE}"/>'
        f'<ellipse cx="623" cy="190" rx="50" ry="7" fill="{SHADOW}" fill-opacity=".4"/>'
        f'<rect x="611" y="72" width="24" height="30" fill="{IVORY}"/>'
        f'<rect x="608" y="62" width="30" height="13" rx="2" fill="{CAMEL}"/>'
        f'<path fill="{IVORY}" d="M593 190V124Q593 100 623 100T653 124V190Z"/>'
        f'<rect x="593" y="136" width="60" height="34" fill="{CAMEL}"/>')
    # aperture: dark ring, six blade edges, light hexagonal opening
    cx, cy, r_in, r_out = 869, 130, 26, 66
    hexagon = " ".join(f"{cx + r_in * math.cos(math.radians(a)):.1f} {cy + r_in * math.sin(math.radians(a)):.1f}"
                       for a in range(0, 360, 60))
    blades = "".join(
        f'<path d="M{cx + r_in * math.cos(math.radians(a)):.1f} {cy + r_in * math.sin(math.radians(a)):.1f}'
        f'L{cx + r_out * math.cos(math.radians(a + 70)):.1f} {cy + r_out * math.sin(math.radians(a + 70)):.1f}"/>'
        for a in range(0, 360, 60))
    f4 = (
        f'<rect x="754" y="40" width="230" height="180" fill="{TAUPE}"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r_out + 6}" fill="{SHADOW}"/>'
        f'<g stroke="{OAT}" stroke-width="3" stroke-linecap="round">{blades}</g>'
        f'<polygon points="{hexagon}" fill="{IVORY}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 260" '
            f'width="1000" height="260" aria-hidden="true">'
            f'<rect width="1000" height="260" rx="6" fill="{SHADOW}"/>' + holes + f1 + f2 + f3 + f4 +
            "</svg>\n")


COMPOSITIONS = {
    ROOT / "public" / "assets" / "img" / "swatch-fan.svg": swatch_fan,
    ROOT / "public" / "assets" / "img" / "film-strip.svg": film_strip,
    ROOT / "public" / "assets" / "img" / "hero-art.svg": hero_art,
    ROOT / "public" / "favicon.svg": favicon,
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--list", action="store_true", help="print image sizes only")
    ap.add_argument("--font", choices=("auto", "georgia", "gelasio"), default="auto",
                    help="auto: Georgia if installed, else Gelasio (default)")
    ap.add_argument("names", nargs="*", help="only build these images")
    args = ap.parse_args(argv)
    print("Typeface:", choose_font(args.font))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for img in IMAGES:
        if args.names and img.name not in args.names:
            continue
        svg, w, h = render(img)
        if not args.list:
            (OUT_DIR / f"{img.name}.svg").write_text(svg, encoding="utf-8")
        print(f"{img.name:20s} width={round(w)} height={round(h)}  ({len(svg.encode()) / 1024:.1f} KiB)")
    if not args.names and not args.list:
        for path, build in COMPOSITIONS.items():
            svg = build()
            path.write_text(svg, encoding="utf-8")
            print(f"{path.relative_to(ROOT)}  ({len(svg.encode()) / 1024:.1f} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
