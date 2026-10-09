import { readFile, stat } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const manifestPath = resolve(root, "web/public/manifest.webmanifest");
const workerPath = resolve(root, "web/public/service-worker.js");
const offlinePath = resolve(root, "web/public/offline.html");
const htmlPath = resolve(root, "web/index.html");

const [manifestRaw, worker, offline, html] = await Promise.all([
  readFile(manifestPath, "utf8"),
  readFile(workerPath, "utf8"),
  readFile(offlinePath, "utf8"),
  readFile(htmlPath, "utf8"),
]);
const manifest = JSON.parse(manifestRaw);
const failures = [];
if (manifest.display !== "standalone") failures.push("manifest display must be standalone");
if (manifest.start_url !== "/control") failures.push("manifest start_url must be /control");
if (!html.includes('rel="manifest"')) failures.push("index.html does not link the manifest");
if (!worker.includes('/offline.html')) failures.push("service worker has no offline fallback");
if (!worker.includes('url.pathname.startsWith("/api")')) failures.push("service worker does not exclude API traffic");
if (!offline.includes("NAS connection")) failures.push("offline page does not explain NAS connectivity");

for (const icon of manifest.icons || []) {
  const iconPath = resolve(root, "web/public", String(icon.src || "").replace(/^\//, ""));
  try {
    const file = await stat(iconPath);
    if (!file.isFile() || file.size === 0) failures.push(`icon is empty: ${icon.src}`);
  } catch {
    failures.push(`icon is missing: ${icon.src}`);
  }
}

if (failures.length) {
  console.error(JSON.stringify({ ok: false, failures }, null, 2));
  process.exitCode = 1;
} else {
  console.log(JSON.stringify({
    ok: true,
    name: manifest.name,
    startUrl: manifest.start_url,
    shortcuts: (manifest.shortcuts || []).map(item => item.url),
    icons: (manifest.icons || []).map(item => `${item.sizes}:${item.purpose}`),
  }, null, 2));
}
