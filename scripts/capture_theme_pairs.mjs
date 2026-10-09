// Screenshot every main screen of the shell in two themes and put each pair side by side
// (plan 19 R3: light themes as good as dark). Uses the dev UI's fixtures, so every run
// shows the same content.
//
//   node scripts/capture_theme_pairs.mjs --url http://r3-light.localhost:1831 --out proof/r3-light/before
//     [--themes dark,light] [--only home,chat-live] [--extra scroll=http://...,kit=http://...]
//
// --extra adds static pages: id=url or id=url|Key*N (keys pressed after load).
// Writes <view>-<theme>.png and <view>-pair.png (left = first theme, right = second).
// Also reports the lowest text contrast per view (rendered text against its painted
// background) so a washed-out light theme shows up as a number, not only a look.
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

const require = createRequire(resolve("package.json"));
const { chromium } = require("playwright");

const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, index, all) => (value.startsWith("--") ? [...pairs, [value.slice(2), all[index + 1]]] : pairs), []));
const base = (args.url || "http://127.0.0.1:1831").replace(/\/$/, "");
const out = resolve(args.out || "proof/r3-light/run");
const themes = (args.themes || "dark,light").split(",");
const only = args.only ? new Set(args.only.split(",")) : null;
mkdirSync(out, { recursive: true });

const stage = (type, id, extra = "") => async page => {
  await page.evaluate(([t, i, e]) => { const os = window.__nxOs; if (t === "app") os.openApp(i, e); else os.showPane(i, e); }, [type, id, extra]);
  await page.waitForTimeout(1100);
};
const call = (fn, wait = 700) => async page => { await page.evaluate(fn); await page.waitForTimeout(wait); };

const VIEWS = [
  { id: "home", query: "" },
  { id: "chat-live", query: "chat=s-claude-live" },
  { id: "chat-approval", query: "chat=s-codex-approve" },
  { id: "launcher", query: "", run: call("window.__nxOs.setLauncher(true)") },
  { id: "dashboard", query: "chat=s-claude-live", run: call("window.__nxOs.setDashboard(true)") },
  { id: "notes", query: "", run: stage("app", "notes", "documents") },
  { id: "files", query: "", run: stage("app", "files", "documents") },
  { id: "settings", query: "", run: stage("pane", "settings", "") },
  { id: "runtime", query: "", run: stage("pane", "runtime", "") },
  { id: "nightshift", query: "", run: stage("pane", "mission", "nightshift") },
  { id: "accounts", query: "", run: stage("pane", "accounts", "") },
  { id: "onboarding", query: "", run: call("window.__nxOs.openOnboarding('welcome')", 1200) },
  { id: "phone-chat", query: "chat=s-claude-live", phone: true },
  { id: "phone-home", query: "", phone: true },
  { id: "signin", query: "", signIn: true, wait: ".ny-si-card" },
  { id: "lab-details", url: "/design-lab.html?only=details-states", lab: true },
  { id: "lab-numbers", url: "/design-lab.html?only=details-numbers", lab: true },
  { id: "lab-all", url: "/design-lab.html", lab: true, full: true },
];
for (const pair of (args.extra || "").split(",").filter(Boolean)) {
  // id=url or id=url|Key*N (press Key N times after load, e.g. to scroll a feed)
  const [id, rest] = [pair.slice(0, pair.indexOf("=")), pair.slice(pair.indexOf("=") + 1)];
  const [url, keys] = rest.split("|");
  VIEWS.push({ id, url, keys, external: true, full: !keys, phone: id.includes("phone") });
}

// Lowest contrast among visible text nodes; background found by walking up to the
// first opaque painted colour (gradients and images count as unknown and are skipped).
const CONTRAST = `(() => {
  const parse = c => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const lum = ({ r, g, b }) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const blend = (top, under) => ({ r: top.r * top.a + under.r * (1 - top.a), g: top.g * top.a + under.g * (1 - top.a), b: top.b * top.a + under.b * (1 - top.a), a: 1 });
  // A gradient painted under the text (an avatar sphere, a hero) cannot be read from styles:
  // those nodes are counted as unknownBg and checked from the pixels or by hand instead.
  const gradientUnder = el => { for (let n = el; n; n = n.parentElement) { const s = getComputedStyle(n); if (parse(s.backgroundColor)?.a >= 1) return false; if (/gradient/.test(s.backgroundImage) && n.getBoundingClientRect().width < 200) return true; } return false; };
  const bgOf = el => { const layers = []; for (let n = el; n; n = n.parentElement) { const s = getComputedStyle(n); const c = parse(s.backgroundColor); if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; } } let base = { r: 255, g: 255, b: 255, a: 1 }; if (layers.length && layers[layers.length - 1].a >= 1) base = layers.pop(); else { const root = parse(getComputedStyle(document.body).backgroundColor); if (root && root.a >= 1) base = root; } for (let i = layers.length - 1; i >= 0; i--) base = blend(layers[i], base); return base; };
  const rows = []; let unknownBg = 0;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let t = walker.nextNode(); t; t = walker.nextNode()) {
    const text = t.textContent.trim(); if (!text) continue;
    const el = t.parentElement; if (!el) continue;
    const r = el.getBoundingClientRect(); if (!r.width || !r.height || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
    const s = getComputedStyle(el); if (s.visibility === "hidden" || Number(s.opacity) < 0.2) continue;
    let fg = parse(s.color); if (!fg) continue;
    if (gradientUnder(el)) { unknownBg += 1; continue; }
    const bg = bgOf(el); fg = blend(fg, bg);
    const a = lum(fg), b = lum(bg); const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    rows.push({ ratio: Math.round(ratio * 100) / 100, text: text.slice(0, 40), size: parseFloat(s.fontSize), cls: String(el.className || "").slice(0, 50) });
  }
  rows.sort((x, y) => x.ratio - y.ratio);
  const small = rows.filter(r => r.size < 18.5);
  return { measured: rows.length, unknownBg, under45: small.filter(r => r.ratio < 4.5).length, worst: rows.slice(0, 5) };
})()`;

const browser = await chromium.launch();
const report = { base, at: new Date().toISOString(), themes, views: [] };
for (const view of VIEWS) {
  if (only && !only.has(view.id)) continue;
  for (const theme of themes) {
    const size = view.phone ? { width: 390, height: 844 } : { width: 1440, height: 900 };
    const context = await browser.newContext({ viewport: size, deviceScaleFactor: 1, colorScheme: theme === "dark" || theme === "sunset" || theme === "night" ? "dark" : "light" });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    try {
      if (view.external) {
        // Static app folders served raw by vite: a missing generated pack must answer 404
        // (vite's HTML fallback is not JSON), and the App SDK template gets a name and an
        // identity the way the generator would give them.
        await page.route("**/generated-pack.json", route => route.fulfill({ status: 404, body: "" }));
        await page.route("**/__neyvia/**", route => route.fulfill({ status: 404, body: "" }));
        await page.route("**/identity.json", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ instance: "preview", name: "Counter" }) }));
        await page.route(/app_sdk\/web\/index\.html/, async route => {
          const response = await route.fetch();
          route.fulfill({ response, body: (await response.text()).replaceAll("__NAME__", "Counter") });
        });
        await page.goto(view.url, { waitUntil: "load" });
        await page.waitForTimeout(1200);
        if (view.keys) {
          const [key, times] = view.keys.split("*");
          for (let n = 0; n < Number(times || 1); n += 1) { await page.keyboard.press(key); await page.waitForTimeout(450); }
          await page.waitForTimeout(600);
        }
      } else if (view.lab) {
        const sep = view.url.includes("?") ? "&" : "?";
        await page.goto(`${base}${view.url}${sep}theme=${theme}`, { waitUntil: "load" });
        await page.waitForSelector("[data-specimen]", { timeout: 20000 });
        await page.waitForTimeout(900);
      } else {
        const query = (view.signIn ? ["ui=next"] : ["preview-control=1", "fixtures=1", "bus=mock", "busscript=0", "ui=next", view.query]).filter(Boolean).join("&");
        await page.goto(`${base}/control?${query}`, { waitUntil: "load" });
        await page.evaluate(next => { try { localStorage.setItem("nx.os.theme", JSON.stringify(next)); localStorage.removeItem("nx.os.layout"); localStorage.setItem("nx.os.ambient", "true"); } catch { /* */ } }, theme);
        await page.reload({ waitUntil: "load" });
        await page.waitForSelector(view.wait || ".nx-root", { timeout: 20000 });
        await page.waitForTimeout(1400);
        if (view.run) await view.run(page);
      }
      const contrast = await page.evaluate(CONTRAST);
      await page.screenshot({ path: join(out, `${view.id}-${theme}.png`), fullPage: Boolean(view.full) });
      report.views.push({ view: view.id, theme, contrast, errors });
      console.log(`${view.id.padEnd(14)} ${theme.padEnd(6)} text=${contrast.measured} under4.5=${contrast.under45} worst=${contrast.worst[0]?.ratio ?? "-"} ${contrast.worst[0] ? JSON.stringify(contrast.worst[0].text) : ""}${errors.length ? ` errors=${errors.length}` : ""}`);
    } catch (error) {
      console.error(`${view.id} ${theme} failed: ${error.message.split("\n")[0]}`);
      report.views.push({ view: view.id, theme, error: error.message });
    }
    await context.close();
  }
}
await browser.close();
writeFileSync(join(out, "report.json"), JSON.stringify(report, null, 2));
