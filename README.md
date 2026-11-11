# Site Home: pwistudio.com

Site Home is a secure home page which
does not use webfonts.

It is the home page for **PW&i Studio + Hoffman Images**: graphic design and
printing (PW&i Studio) and studio photography (Hoffman Images).

- **Layout:** bold, photo-led and mostly dark: a near-black hero with
  oversized condensed headlines, a split panel (color block with an inset photo
  beside a full-height portrait), a "Recent work" photo collage, then
  Design + Print, the "Shoot it. Design it. Print it." process, and contact.
- **Palette:** Cerulean `#4484CE`, Aluminium `#D9D9D9`, Light `#F9CF00`
  (yellow) and Tangerine `#F19F4D`, on near-black `#0D0D0D`. A deeper
  cerulean `#2F6DB5` is used where blue sits on a light background, for
  contrast. Every text/background pair meets WCAG AA.
- **Logos as the page title:** the PW&i Design + Print and Hoffman Images logos
  (`public/assets/logo/`) form the main heading, header and footer. On dark
  backgrounds the Hoffman Images wordmark is shown in white.
- **Text: a Roboto-style sans-serif, with no webfonts.** The page uses the
  sans-serif already on each device: Roboto on Android and Chromebooks, Segoe
  UI on Windows, San Francisco on iPhone, iPad and Mac. Nothing is downloaded.
- **Large lettering as images:** the big headlines are SVG vector outlines of
  Roboto Condensed (`public/assets/type/`), so they look the same everywhere.
- **Photos:** six Hoffman Images photos (`public/assets/photos/`), used with
  the subjects' photography releases, served as WebP with JPEG fallbacks and
  stripped of all metadata.
- **No JavaScript, no cookies, no forms, no third-party requests** (no CDNs,
  analytics, embeds or font services).

## What makes it secure

| For visitors | For the host |
| --- | --- |
| No scripts, so there is nothing for XSS to run or hijack | Static files only: no PHP, database or admin login to attack |
| Strict Content-Security-Policy (`default-src 'none'`), sent as a header **and** a `<meta>` tag | Only `GET`/`HEAD` allowed; all other methods get `405` |
| No cookies, trackers or third-party requests, so nothing about the visitor is shared | Hidden files (`.git`, `.env`, `.htaccess`) and config/backup/script files return `404` |
| HTTPS forced, plus HSTS | Directory listings off; server version hidden |
| Can't be framed (clickjacking), `nosniff`, `no-referrer`, all browser features (camera, location...) disabled | Server-side script handlers removed from the web root |
| Cross-origin isolation (COOP, COEP, CORP) | `tools/audit_site.py` blocks risky changes before deploy |
| Photos carry no hidden location or camera data | |

SVGs are generated, not hand-edited, and contain only plain shapes: no
`<script>`, `<style>`, links or embedded fonts.

## Layout

```
public/                 <- the web root: upload only this folder
  index.html, 404.html
  assets/css/site.css   the only stylesheet
  assets/logo/*.svg     the two logos (full versions, compact header marks,
                        white-wordmark Hoffman Images for dark backgrounds)
  assets/photos/*       photos: WebP at 480/960/1440 px + one JPEG fallback
  assets/type/*.svg     large lettering (generated)
  assets/img/*          swatch-fan illustration (generated) + social preview image
  favicon.svg/.ico, apple-touch-icon.png, robots.txt, sitemap.xml
  .well-known/security.txt
  .htaccess             Apache config (headers, HTTPS, access rules)
  _headers              Netlify / Cloudflare Pages headers
server/
  nginx/                nginx server block + headers snippet
  Caddyfile             Caddy config
tools/
  prepare_photos.py     strips metadata and makes web sizes of new photos
  build_graphics.py     regenerates the lettering and illustration
  render_png.mjs        regenerates favicon.ico, touch icon, social image (needs Playwright)
  audit_site.py         security audit, standard library only
  fonts/                Roboto Condensed (SIL OFL), used at build time only
```

## Deploying

Publish the **contents of `public/`** as the site root of `pwistudio.com`.

- **Apache / shared hosting (cPanel etc.):** upload `public/` contents,
  including the hidden `.htaccess` and `.well-known/` (enable "show hidden
  files" in your FTP client). Needs `mod_rewrite` and `mod_headers`. If the
  host terminates HTTPS at a proxy/CDN, read the note in `.htaccess` about
  the redirect.
- **nginx:** see the install steps at the top of `server/nginx/pwistudio.com.conf`.
- **Caddy:** `server/Caddyfile` (HTTPS certificates are automatic).
- **Netlify / Cloudflare Pages:** set the publish/output directory to
  `public`; `_headers` is applied automatically.
- **GitHub Pages** can't send custom headers. The `<meta>` CSP still protects
  the pages, but anti-framing and the other headers are lost, so prefer one
  of the options above.

All configs were tested on nginx 1.24 and Apache 2.4.58. The Caddyfile was not
run.

### Before going live

1. Replace `hello@pwistudio.com` (in `index.html` and
   `.well-known/security.txt`) if your address is different. Add a phone
   number or street address to the contact card if you want them shown.
2. Pick `pwistudio.com` or `www.pwistudio.com` as the main address. The
   configs redirect `www` to the bare domain and the canonical/OG tags use
   the bare domain.
3. HSTS uses `includeSubDomains`: make sure every subdomain (mail, shop...)
   works over HTTPS, or remove `includeSubDomains` from the four header
   configs.
4. Renew the `Expires` date in `security.txt` before **2027-11-11**.
5. Check the live site with [Mozilla Observatory](https://developer.mozilla.org/en-US/observatory),
   [securityheaders.com](https://securityheaders.com) and
   [SSL Labs](https://www.ssllabs.com/ssltest/).

## Editing

One-time setup for the Python tools:

```sh
python3 -m venv .venv
.venv/bin/pip install -r tools/requirements.txt
```

- **Text:** edit `public/index.html` directly.
- **Adding or swapping photos:** only use photos you have a signed release for.

  ```sh
  .venv/bin/python tools/prepare_photos.py ~/Pictures/new-photo.jpg short-name
  ```

  This turns the photo upright, removes **all** metadata (GPS location,
  camera details), saves web sizes in `public/assets/photos/` and prints the
  `<picture>` markup to paste into the page. Write a plain description of
  the photo in its `alt` text (don't name the people in it).
- **Large lettering:** edit the `IMAGES` list in `tools/build_graphics.py`, run
  `.venv/bin/python tools/build_graphics.py`, then copy the printed
  `width`/`height` into the matching `<img>` tag. Keep the `alt` text identical
  to the lettering.
- **Favicon / social image:** `node tools/render_png.mjs` (instructions in the file).
- **Logos:** the files in `public/assets/logo/` were traced into vector shapes
  from screenshots of the Canva designs. For exact originals, export each logo
  from Canva as **SVG** (or a large PNG with a transparent background) and
  replace the matching file, keeping the same file name. Update the
  `width`/`height` in the `<img>` tags if the proportions change. Run
  `python3 tools/audit_site.py` afterward: Canva SVGs sometimes contain
  embedded images or fonts that the audit will flag.

Preview locally with `python3 -m http.server -d public 8000` (or just open
`public/index.html`), and **always run the audit before deploying**:

```sh
python3 tools/audit_site.py
```

It fails if any page gains a script, inline handler or style, external
resource, form, iframe, webfont or unsafe SVG content; if a photo still
carries metadata; if an image lacks `alt`/size or points at a missing file;
or if the header configs drift apart.
