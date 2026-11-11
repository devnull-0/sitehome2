#!/usr/bin/env python3
"""Security and hygiene audit for the static site in public/.

Run before every deploy (standard library only, no installs needed):

    python3 tools/audit_site.py

It fails (exit code 1) if any published file could run code, load anything
from another site, use a webfont, or weaken the security headers. It also
checks a few accessibility basics.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"

CSP = ("default-src 'none'; img-src 'self'; style-src 'self'; base-uri 'none'; "
       "form-action 'none'; frame-ancestors 'none'; upgrade-insecure-requests")
# <meta> CSP cannot carry frame-ancestors; the HTTP header does.
META_CSP = CSP.replace(" frame-ancestors 'none';", "")

HEADER_FILES = [PUBLIC / "_headers", PUBLIC / ".htaccess",
                ROOT / "server" / "nginx" / "security-headers.conf", ROOT / "server" / "Caddyfile"]
REQUIRED_HEADERS = ["Strict-Transport-Security", "X-Content-Type-Options", "X-Frame-Options",
                    "Referrer-Policy", "Permissions-Policy", "Cross-Origin-Opener-Policy",
                    "Cross-Origin-Resource-Policy", "Cross-Origin-Embedder-Policy"]

FONT_EXT = {".woff", ".woff2", ".ttf", ".otf", ".eot"}
ACTIVE_EXT = {".js", ".mjs", ".php", ".phtml", ".phar", ".pl", ".py", ".cgi", ".sh",
              ".asp", ".aspx", ".jsp", ".swf", ".wasm", ".exe", ".bat"}
BANNED_TAGS = {"script", "iframe", "frame", "object", "embed", "applet", "form", "input",
               "button", "textarea", "select", "base", "portal", "template"}
URL_ATTRS = {"href", "src", "srcset", "action", "formaction", "poster", "data", "xlink:href"}
# Absolute URLs allowed only in these metadata spots (they load nothing).
ALLOWED_ABSOLUTE = re.compile(r"^https://pwistudio\.com/")

problems: list[str] = []


def fail(path: Path, msg: str) -> None:
    problems.append(f"{path.relative_to(ROOT)}: {msg}")


class PageAudit(HTMLParser):
    def __init__(self, path: Path):
        super().__init__(convert_charrefs=True)
        self.path = path
        self.meta_csp: list[str] = []
        self.has_referrer = False
        self.h1 = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in BANNED_TAGS:
            fail(self.path, f"<{tag}> is not allowed (no scripts, frames, forms or plugins)")
        if tag == "style":
            fail(self.path, "<style> blocks are not allowed; use assets/css/site.css")
        if tag == "h1":
            self.h1 += 1
        for name, value in attrs:
            value = value or ""
            if name.startswith("on"):
                fail(self.path, f"inline event handler {name}= on <{tag}>")
            if name == "style":
                fail(self.path, f"inline style= on <{tag}> (blocked by CSP)")
            if name in URL_ATTRS:
                self.check_url(tag, name, value)
        if tag == "meta":
            if (a.get("http-equiv") or "").lower() == "content-security-policy":
                self.meta_csp.append(a.get("content") or "")
            if a.get("name") == "referrer":
                self.has_referrer = True
            if a.get("property") == "og:image" and not ALLOWED_ABSOLUTE.match(a.get("content") or ""):
                fail(self.path, "og:image must point at https://pwistudio.com/")
        if tag == "img":
            if "alt" not in a:
                fail(self.path, f"<img src={a.get('src')!r}> has no alt attribute")
            if not (a.get("width") and a.get("height")):
                fail(self.path, f"<img src={a.get('src')!r}> needs width and height")
        if tag == "a" and (a.get("target") or "").lower() == "_blank":
            rel = (a.get("rel") or "").split()
            if "noopener" not in rel or "noreferrer" not in rel:
                fail(self.path, "target=_blank link needs rel=\"noopener noreferrer\"")

    def check_url(self, tag, name, value):
        for url in [u.strip().split(" ")[0] for u in value.split(",")] if name == "srcset" else [value.strip()]:
            low = url.lower()
            if low.startswith(("javascript:", "vbscript:", "data:", "blob:", "file:")):
                fail(self.path, f"{name}={url!r} uses a dangerous URL scheme")
            elif low.startswith("mailto:") or low.startswith("#"):
                continue
            elif low.startswith(("http:", "//")):
                fail(self.path, f"{name}={url!r} is not HTTPS / is protocol-relative")
            elif low.startswith("https:"):
                if not (tag == "link" and name == "href" and ALLOWED_ABSOLUTE.match(url)):
                    fail(self.path, f"{name}={url!r} loads from another site")


def audit_html(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if not text.lstrip().lower().startswith("<!doctype html>"):
        fail(path, "missing <!doctype html>")
    p = PageAudit(path)
    p.feed(text)
    if p.meta_csp != [META_CSP]:
        fail(path, f"meta CSP must be exactly: {META_CSP}")
    if not p.has_referrer:
        fail(path, "missing <meta name=\"referrer\">")
    if p.h1 != 1:
        fail(path, f"expected exactly one <h1>, found {p.h1}")
    if not re.search(r'<html[^>]+lang="[A-Za-z]{2,3}(-[A-Za-z0-9]+)*"', text):
        fail(path, "<html> needs a lang attribute")


SVG_BAD = [
    (re.compile(r"<\s*script", re.I), "<script>"),
    (re.compile(r"<\s*foreignObject", re.I), "<foreignObject>"),
    (re.compile(r"<\s*style", re.I), "<style> (use presentation attributes)"),
    (re.compile(r"\son[a-z]+\s*=", re.I), "event handler attribute"),
    (re.compile(r"(?:xlink:)?href\s*=\s*[\"'](?!#)", re.I), "external link/reference"),
    (re.compile(r"url\(\s*[\"']?(?!#)", re.I), "external url()"),
    (re.compile(r"<!ENTITY|<!DOCTYPE", re.I), "DTD/entity declaration"),
    (re.compile(r"<\s*(image|use|animate|set)\b[^>]*\bhref", re.I), "referencing element"),
    (re.compile(r"<\s*text\b", re.I), "<text> (needs a font; convert to outlines)"),
]


def audit_svg(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for rx, label in SVG_BAD:
        if rx.search(text):
            fail(path, f"SVG contains {label}")
    if 'aria-hidden="true"' not in text and "<title>" not in text:
        fail(path, "SVG needs a <title> or aria-hidden=\"true\"")


def audit_css(path: Path) -> None:
    text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
    if re.search(r"@font-face", text, re.I):
        fail(path, "@font-face found: webfonts are not allowed")
    if re.search(r"@import", text, re.I):
        fail(path, "@import found: keep a single stylesheet")
    for m in re.finditer(r"url\(\s*[\"']?([^\"')]+)", text, re.I):
        if re.match(r"(?i)(https?:|//|data:|javascript:)", m.group(1).strip()):
            fail(path, f"url({m.group(1)}) loads from elsewhere")
    if re.search(r"expression\s*\(|(?<![-\w])behavior\s*:|-moz-binding", text, re.I):
        fail(path, "legacy script-in-CSS construct found")


def audit_headers() -> None:
    for f in HEADER_FILES:
        if not f.exists():
            fail(f, "missing")
            continue
        text = f.read_text(encoding="utf-8")
        if CSP not in text:
            fail(f, "Content-Security-Policy differs from the site policy")
        for h in REQUIRED_HEADERS:
            if h not in text:
                fail(f, f"missing {h}")


def audit_security_txt() -> None:
    f = PUBLIC / ".well-known" / "security.txt"
    if not f.exists():
        fail(f, "missing")
        return
    m = re.search(r"^Expires:\s*(\S+)", f.read_text(encoding="utf-8"), re.M)
    if not m:
        fail(f, "no Expires field")
        return
    expires = dt.datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)
    if expires <= now:
        fail(f, f"Expires {m.group(1)} has passed: renew it")
    elif expires - now > dt.timedelta(days=366):
        fail(f, "Expires should be less than a year away")


def main() -> int:
    for path in sorted(PUBLIC.rglob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext in FONT_EXT:
            fail(path, "font file in the web root: the site must not ship webfonts")
        if ext in ACTIVE_EXT:
            fail(path, "executable/script file in the web root")
        if ext == ".html":
            audit_html(path)
        elif ext == ".svg":
            audit_svg(path)
        elif ext == ".css":
            audit_css(path)
    audit_headers()
    audit_security_txt()

    if problems:
        print("Site audit FAILED:")
        for p in problems:
            print("  -", p)
        return 1
    print("Site audit passed: no scripts, no third-party requests, no webfonts, headers consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
