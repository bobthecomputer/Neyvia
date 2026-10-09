// Render Neyvia's own shell in Neyvia's owned Obscura engine (no Chrome/Edge,
// no window) and save screenshots of the views the Look track changes.
//
//   node scripts/look_render.mjs --out proof/look/before [--base http://127.0.0.1:48851]
//        [--port 48852] [--themes dark,light,sunset,night] [--views home,chat,settings]
//        [--setup '{"font":"inter"}']   (a Settings look patch saved before rendering)
//
// The backend must already be running (scripts/run_web_backend.py on --base).
// The engine is the pinned Obscura build the C13 taste track used.
import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { spawn } from "node:child_process";
import { chromium } from "playwright";

const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, index, all) => (value.startsWith("--") ? [...pairs, [value.slice(2), all[index + 1]]] : pairs), []));
const base = args.base || "http://127.0.0.1:48851";
const port = Number(args.port || 48852);
const out = path.resolve(args.out || "proof/look/shots");
const themes = (args.themes || "dark,light,sunset,night").split(",");
const views = (args.views || "home,chat,settings").split(",");
const width = Number(args.width || 1440), height = Number(args.height || 900);
const exe = process.env.NEYVIA_OBSCURA_EXE || "C:/Users/user/Projects/nx-c13-taste/scripts/evidence/c13-runtime/obscura-v0.2.4/obscura.exe";
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function startEngine() {
  const token = crypto.randomBytes(27).toString("base64url");
  const child = spawn(exe, ["serve", "--host", "127.0.0.1", "--port", String(port), "--user-agent", "NeyviaAgent/1.0 (Look render; Obscura)", "--max-connections", "8", "--allow-private-network"],
    { windowsHide: true, stdio: "ignore", env: { ...process.env, OBSCURA_CDP_TOKEN: token, OBSCURA_ROTATE_PROFILE: "0", OBSCURA_NAV_TIMEOUT_MS: "20000", OBSCURA_SCRIPT_DEADLINE_MS: "15000" } });
  const endpoint = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 100; i += 1) {
    try { const r = await fetch(`${endpoint}/json/version`, { headers: { Authorization: `Bearer ${token}` } }); if (r.ok) return { child, endpoint, token }; } catch { /* starting */ }
    await pause(100);
  }
  child.kill();
  throw new Error("Obscura did not start");
}

async function session() {
  const response = await fetch(`${base}/api/auth/local-session`, { method: "POST", headers: { "Content-Type": "application/json", Origin: base }, body: "{}" });
  const cookie = (response.headers.getSetCookie?.() || [response.headers.get("set-cookie")]).filter(Boolean).map(line => line.split(";")[0]);
  if (!cookie.length) throw new Error(`No local session (${response.status})`);
  return cookie.map(pair => { const at = pair.indexOf("="); return { name: pair.slice(0, at), value: pair.slice(at + 1) }; });
}

async function command(cookies, name, payload) {
  const response = await fetch(`${base}/api/backend`, { method: "POST", headers: { "Content-Type": "application/json", Origin: base, Cookie: cookies.map(c => `${c.name}=${c.value}`).join("; ") }, body: JSON.stringify({ command: name, payload }) });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || body.ok === false) throw new Error(`${name}: ${body.error || response.status}`);
  return body.data ?? body;
}

const THEME_TO_SETTINGS = { dark: "forest", light: "morning", sunset: "sunset", night: "night-green" };

async function main() {
  await fs.mkdir(out, { recursive: true });
  const cookies = await session();
  await command(cookies, "onboarding_save_command", { dismissed: true }).catch(() => {});
  const engine = await startEngine();
  const report = { engine: "obscura", exe, base, viewport: { width, height }, shots: [], errors: [] };
  let browser;
  try {
    browser = await chromium.connectOverCDP(engine.endpoint, { headers: { Authorization: `Bearer ${engine.token}` } });
    const context = browser.contexts()[0] || await browser.newContext();
    await context.addCookies(cookies.map(c => ({ ...c, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" })));
    const page = context.pages()[0] || await context.newPage();
    page.on("pageerror", error => report.errors.push(String(error.message || error).slice(0, 300)));
    await page.setViewportSize?.({ width, height }).catch(() => {});
    for (const theme of themes) {
      const settings = await command(cookies, "settings_get_command", {});
      // Every run states its whole look (default unless --setup gives one), so runs don't inherit each other's.
      const defaults = { look: { font: "neyvia", textSize: "m", background: { kind: "theme", preset: "", color: "", image: "", dim: 0, blur: 0 } } };
      const setup = args.setup ? JSON.parse(args.setup) : {};
      const look = { ...defaults.look, ...(setup.look || {}), background: { ...defaults.look.background, ...(setup.look?.background || {}) } };
      const patch = { theme: THEME_TO_SETTINGS[theme], ...setup, look };
      await command(cookies, "settings_update_command", { patch, expectedRevision: settings.revision });
      for (const view of views) {
        const url = view === "settings" ? `${base}/control?pane=settings` : `${base}/control`;
        await page.goto(url, { waitUntil: "load", timeout: 30000 });
        await page.evaluate(theme => { localStorage.setItem("nx.os.theme", JSON.stringify(theme)); localStorage.removeItem("nx.os.look"); }, theme);
        await page.goto(url, { waitUntil: "load", timeout: 30000 });
        await page.waitForSelector(".nx", { timeout: 20000 });
        for (let i = 0; i < 25 && await page.evaluate(t => document.querySelector(".nx")?.dataset.nxTheme !== t, theme); i += 1) {
          if (i === 12) await page.goto(url, { waitUntil: "load", timeout: 30000 });
          await pause(300);
        }
        await page.evaluate(() => {
          window.__lookErrors = [];
          window.addEventListener("error", event => window.__lookErrors.push(String(event.error?.stack || event.message || event.error).slice(0, 900)));
          window.addEventListener("unhandledrejection", event => window.__lookErrors.push(`rejection: ${event.reason?.message || event.reason}`));
          const original = console.error;
          console.error = (...parts) => { window.__lookErrors.push(parts.map(p => String(p?.stack || p)).join(" ").slice(0, 900)); original(...parts); };
        });
        await pause(1200);
        if (view === "fontprobe") {
          // Which families this engine can actually draw (system and bundled web fonts).
          await page.evaluate(() => {
            const families = ["Segoe UI Variable Text", "Segoe UI Variable Display", "Segoe UI", "Georgia", "Consolas", "Geist", "Inter", "Newsreader", "Fraunces", "Cascadia Code", "serif", "sans-serif", "system-ui"];
            const probe = document.createElement("div");
            probe.style.cssText = "position:fixed;inset:0;z-index:99999;background:#fff;color:#000;font-size:26px;padding:20px;line-height:1.5";
            probe.innerHTML = families.map(f => `<div style="font-family:'${f}',monospace">${f}: Handgloves Rag 0123</div>`).join("");
            document.body.appendChild(probe);
          });
          await pause(1500);
        }
        if (view === "chat") {
          await page.evaluate(() => document.querySelector(".nx-row")?.click());
          await pause(1500);
        }
        if (view === "settings") {
          // The way a person gets there: the sidebar's Settings button, else More > Settings.
          const direct = await page.evaluate(() => { const b = document.querySelector('[data-nx-open="settings"]'); b?.click(); return Boolean(b); });
          if (!direct) {
            // Before the Look track the only way in was the launcher: Apps, type "settings", Enter.
            await page.evaluate(() => document.querySelector('button[aria-label="Apps"]')?.click());
            await pause(500);
            await page.evaluate(() => {
              const input = document.querySelector(".nx-launcher input");
              Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, "settings");
              input.dispatchEvent(new Event("input", { bubbles: true }));
            });
            await pause(400);
            await page.evaluate(() => document.querySelector(".nx-launcher input").dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
          }
          await pause(1500);
          if (args.scroll) await page.evaluate(y => document.querySelector(".nx-set")?.scrollBy(0, Number(y)), args.scroll);
          await pause(300);
        }
        // A picture background arrives a moment after the page: wait for it (up to 6 s).
        for (let i = 0; i < 20 && await page.evaluate(() => {
          const fill = document.querySelector(".nx-backdrop-fill");
          return document.querySelector(".nx-root")?.dataset.nxBg === "image" && (!fill || getComputedStyle(fill).backgroundImage === "none");
        }); i += 1) await pause(300);
        await page.evaluate(async () => { await document.fonts?.ready; });
        const file = path.join(out, `${view}-${theme}.png`);
        await page.screenshot({ path: file, timeout: 20000 });
        const facts = await page.evaluate(() => {
          const root = document.querySelector(".nx");
          const style = root ? getComputedStyle(root) : null;
          const fonts = [...(document.fonts || [])].filter(f => f.status === "loaded").map(f => f.family);
          return { errors: (window.__lookErrors || []).slice(0, 5), font: style?.fontFamily, size: style?.fontSize, theme: root?.dataset.nxTheme, bg: style?.backgroundColor, fontsLoaded: [...new Set(fonts)].join(","), w: innerWidth, h: innerHeight };
        });
        if (args.eval) facts.eval = await page.evaluate(source => (0, eval)(source), args.eval).catch(error => `eval failed: ${error.message}`);
        report.shots.push({ file, view, theme, ...facts });
        console.log(view, theme, JSON.stringify(facts));
      }
    }
  } finally {
    await browser?.close().catch(() => {});
    engine.child.kill();
    await fs.writeFile(path.join(out, "render.json"), JSON.stringify(report, null, 2));
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
