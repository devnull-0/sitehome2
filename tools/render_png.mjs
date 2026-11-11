// Render the few raster files a site still needs from the SVG sources:
//   public/favicon.ico            (16, 32 and 48 px, PNG-in-ICO)
//   public/apple-touch-icon.png   (180 px)
//   public/assets/img/og-image.png (1200x630 social preview)
//
// Requires Node 18+ and Playwright with Chromium:
//   npm install --no-save playwright && npx playwright install chromium
//   node tools/render_png.mjs
//
// Run tools/build_graphics.py first if you changed any lettering.

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const pub = (p) => join(root, "public", p);
const dataUri = (p) => "data:image/svg+xml;base64," + readFileSync(pub(p)).toString("base64");

const RUST = "#B7410E", OCHRE = "#CC7722", CREAM = "#EDE8D0";

async function shot(browser, html, width, height) {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  await page.setContent(html, { waitUntil: "load" });
  const png = await page.screenshot({ omitBackground: true, type: "png" });
  await page.close();
  return png;
}

// ICO container holding PNG images (supported by every current browser).
function ico(pngs) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(pngs.length, 4);
  let offset = 6 + 16 * pngs.length;
  const dir = pngs.map(({ size, data }) => {
    const e = Buffer.alloc(16);
    e.writeUInt8(size >= 256 ? 0 : size, 0);
    e.writeUInt8(size >= 256 ? 0 : size, 1);
    e.writeUInt16LE(1, 4);   // colour planes
    e.writeUInt16LE(32, 6);  // bits per pixel
    e.writeUInt32LE(data.length, 8);
    e.writeUInt32LE(offset, 12);
    offset += data.length;
    return e;
  });
  return Buffer.concat([header, ...dir, ...pngs.map((p) => p.data)]);
}

const browser = await chromium.launch();
try {
  const fav = dataUri("favicon.svg");
  const icon = (size, bg = "transparent") =>
    `<html><body style="margin:0;background:${bg}"><img src="${fav}" width="${size}" height="${size}" style="display:block"></body></html>`;

  const sizes = [16, 32, 48];
  const pngs = [];
  for (const size of sizes) pngs.push({ size, data: await shot(browser, icon(size), size, size) });
  writeFileSync(pub("favicon.ico"), ico(pngs));

  // iOS rounds the corners itself, so fill the whole square.
  writeFileSync(pub("apple-touch-icon.png"), await shot(browser, icon(180, RUST), 180, 180));

  const og = `<html><body style="margin:0;width:1200px;height:630px;background:${CREAM};position:relative;overflow:hidden">
    <img src="${dataUri("assets/type/hero-title-wide.svg")}" style="position:absolute;left:72px;top:150px;width:720px">
    <img src="${dataUri("assets/img/hero-art.svg")}" style="position:absolute;right:72px;bottom:44px;width:300px">
    <div style="position:absolute;left:0;right:0;bottom:0;height:44px;background:${RUST};border-top:12px solid ${OCHRE}"></div>
  </body></html>`;
  writeFileSync(pub("assets/img/og-image.png"), await shot(browser, og, 1200, 630));
  console.log("wrote favicon.ico, apple-touch-icon.png, assets/img/og-image.png");
} finally {
  await browser.close();
}
