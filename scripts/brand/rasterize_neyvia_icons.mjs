// Rasterises the Neyvia sun mark SVGs into the PNG sources the app ships.
// Run after `python scripts/brand/neyvia_sun_mark.py`; then `npx tauri icon` builds ICO/ICNS and the
// mobile sets from the two 1024 sources (see docs/NEYVIA_BRAND.md).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = file => fs.readFileSync(path.join(root, file), "utf8");

const jobs = [
  // Desktop: the disc alone on transparent, so the taskbar shows a sun, not a tile.
  { svg: "src-tauri/icons/neyvia-icon.svg", out: "src-tauri/icons/neyvia-desktop-1024.png", size: 1024 },
  // Mobile stores want an opaque tile.
  { svg: "docs/brand/neyvia-app-icon-light.svg", out: "src-tauri/icons/neyvia-mobile-1024.png", size: 1024, opaque: true },
  { svg: "docs/brand/neyvia-app-icon-light.svg", out: "web/public/icons/neyvia-192.png", size: 192 },
  { svg: "docs/brand/neyvia-app-icon-light.svg", out: "web/public/icons/neyvia-512.png", size: 512 },
  { svg: "docs/brand/neyvia-app-icon-maskable.svg", out: "web/public/icons/neyvia-maskable-512.png", size: 512, opaque: true },
];

const browser = await chromium.launch();
try {
  for (const job of jobs) {
    const page = await browser.newPage({ viewport: { width: job.size, height: job.size }, deviceScaleFactor: 1 });
    const svg = read(job.svg).replace("<svg ", `<svg width="${job.size}" height="${job.size}" `);
    await page.setContent(`<html><body style="margin:0;background:${job.opaque ? "#fbf6ec" : "transparent"}">${svg}</body></html>`);
    await page.screenshot({ path: path.join(root, job.out), omitBackground: !job.opaque, clip: { x: 0, y: 0, width: job.size, height: job.size } });
    await page.close();
    console.log(`wrote ${job.out}`);
  }
} finally {
  await browser.close();
}
