// Accessibility audit of the new shell: axe-core on each main view, plus a keyboard walk
// that tabs through the page and flags focus stops with no visible focus indicator.
//
//   node web/a11y/nx-a11y-audit.mjs --url http://127.0.0.1:1503 --axe <path to axe.min.js> --out <dir>
//
// axe-core is not a dependency: pass the path of an axe.min.js (npm pack axe-core). Runs the
// dev UI with `?fixtures=1&bus=mock`, so every view has the same content on every run.
// Both themes (Forest dark, Morning light) and reduced motion are checked.
import { createRequire } from "node:module";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

const require = createRequire(resolve("package.json"));
const { chromium } = require("playwright");

const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, index, all) => (value.startsWith("--") ? [...pairs, [value.slice(2), all[index + 1]]] : pairs), []));
const base = (args.url || "http://127.0.0.1:1503").replace(/\/$/, "");
const axeSource = readFileSync(args.axe, "utf8");
const out = resolve(args.out || "a11y-out");
const label = args.label || "run";
mkdirSync(out, { recursive: true });

// Each view: how to reach it from a fresh page. `keys` walks with Tab.
const VIEWS = [
  { id: "home", query: "" },
  { id: "chat-live", query: "chat=s-claude-live" },
  { id: "chat-approval", query: "chat=s-codex-approve" },
  { id: "chat-question", query: "chat=s-claude-question" },
  { id: "launcher", query: "", run: async page => { await page.keyboard.press("Control+Space"); await page.waitForTimeout(400); } },
  { id: "notes", query: "", stage: ["app", "notes", "documents"] },
  { id: "files", query: "", stage: ["app", "files", "documents"] },
  { id: "settings", query: "", stage: ["pane", "settings", ""] },
  { id: "runtime", query: "", stage: ["pane", "runtime", ""] },
  { id: "dashboard", query: "", run: async page => { await page.evaluate(() => window.__nxOs?.setDashboard(true)); await page.waitForTimeout(400); } },
  { id: "voice-help", query: "", run: async page => { await page.evaluate(() => window.__nxOs?.setHelp(true)); await page.waitForTimeout(400); } },
];

async function open(page, view, theme) {
  const query = ["fixtures=1", "bus=mock", "busscript=0", "ui=next", view.query].filter(Boolean).join("&");
  await page.goto(`${base}/control?${query}`, { waitUntil: "load" });
  await page.evaluate(next => { try { localStorage.setItem("nx.os.theme", JSON.stringify(next)); localStorage.removeItem("nx.os.layout"); } catch { /* */ } }, theme);
  await page.reload({ waitUntil: "load" });
  await page.waitForSelector(".nx-root", { timeout: 15000 });
  await page.waitForTimeout(800);
  if (view.stage) {
    await page.evaluate(([type, id, extra]) => {
      const os = window.__nxOs;
      if (!os) return;
      if (type === "app") os.openApp(id, extra); else os.showPane(id, extra);
    }, view.stage);
    await page.waitForTimeout(900);
  }
  if (view.run) await view.run(page);
}

/** Tab through up to `limit` stops; report stops whose focus is invisible. */
async function keyboardWalk(page, limit = 80) {
  await page.evaluate(() => { document.activeElement?.blur?.(); window.scrollTo(0, 0); });
  await page.mouse.click(1, 1).catch(() => {});
  const stops = [];
  const invisible = [];
  for (let index = 0; index < limit; index += 1) {
    await page.keyboard.press("Tab");
    const info = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return null;
      const style = getComputedStyle(el);
      const outline = style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0;
      const ring = style.boxShadow && style.boxShadow !== "none";
      // A focused text field inside a container that draws the ring (composer, search) counts.
      let host = el.parentElement; let hostRing = false;
      for (let depth = 0; host && depth < 4; depth += 1, host = host.parentElement) {
        const hostStyle = getComputedStyle(host);
        if (host.matches(":focus-within") && ((hostStyle.boxShadow && hostStyle.boxShadow !== "none" && /accent|rgb/.test(hostStyle.boxShadow)) || (hostStyle.outlineStyle !== "none" && parseFloat(hostStyle.outlineWidth) > 0))) { hostRing = true; break; }
      }
      const name = (el.getAttribute("aria-label") || el.textContent || el.getAttribute("title") || el.getAttribute("placeholder") || "").trim().replace(/\s+/g, " ").slice(0, 50);
      const rect = el.getBoundingClientRect();
      return {
        tag: el.tagName.toLowerCase(), cls: String(el.className || "").slice(0, 60), name,
        visible: outline || ring || hostRing, offscreen: rect.width === 0 || rect.height === 0,
        key: `${el.tagName}|${el.className}|${name}|${Math.round(rect.x)}|${Math.round(rect.y)}`,
      };
    });
    if (!info) continue;
    if (stops.length && stops[0].key === info.key) break; // wrapped around
    stops.push(info);
    if (!info.visible) invisible.push(info);
  }
  return { stops: stops.length, invisible };
}

const browser = await chromium.launch();
const summary = { label, base, at: new Date().toISOString(), views: [] };
for (const theme of (args.themes || "dark,light,sunset,night").split(",")) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  const page = await context.newPage();
  page.on("pageerror", error => console.error(`[pageerror] ${error.message}`));
  for (const view of VIEWS) {
    try {
      await open(page, view, theme);
      await page.addScriptTag({ content: axeSource });
      const result = await page.evaluate(async () => {
        const run = await window.axe.run(document, { resultTypes: ["violations"], runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"] } });
        return run.violations.map(v => ({ id: v.id, impact: v.impact, help: v.help, count: v.nodes.length, nodes: v.nodes.slice(0, 6).map(n => ({ target: n.target.join(" "), summary: n.failureSummary?.split("\n").slice(0, 3).join(" | ") })) }));
      });
      const walk = view.id === "launcher" || view.id === "voice-help" ? { stops: 0, invisible: [] } : await keyboardWalk(page);
      const counts = result.reduce((acc, v) => ({ ...acc, [v.impact]: (acc[v.impact] || 0) + v.count }), {});
      summary.views.push({ theme, view: view.id, counts, violations: result, keyboard: walk });
      if (theme === "dark") await page.screenshot({ path: join(out, `${label}-${view.id}.png`) });
      console.log(`${theme.padEnd(5)} ${view.id.padEnd(14)} critical=${counts.critical || 0} serious=${counts.serious || 0} moderate=${counts.moderate || 0} minor=${counts.minor || 0} tabStops=${walk.stops} noFocusRing=${walk.invisible.length}`);
    } catch (error) {
      console.error(`${theme} ${view.id} failed: ${error.message}`);
      summary.views.push({ theme, view: view.id, error: error.message });
    }
  }
  await context.close();
}
await browser.close();
writeFileSync(join(out, `${label}.json`), JSON.stringify(summary, null, 2));
const total = summary.views.reduce((acc, row) => { for (const [k, v] of Object.entries(row.counts || {})) acc[k] = (acc[k] || 0) + v; acc.noFocusRing += row.keyboard?.invisible.length || 0; return acc; }, { noFocusRing: 0 });
console.log("TOTAL", JSON.stringify(total));
