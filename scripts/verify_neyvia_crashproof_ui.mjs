import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";


function argument(name, fallback = "") {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}


const baseUrl = argument("--base-url", "http://127.0.0.1:47880").replace(/\/$/, "");
const output = resolve(argument("--output", ".agent_control/runtime_proof/neyvia-crashproof-ui.png"));
const mobile = process.argv.includes("--mobile");
const orchestration = process.argv.includes("--orchestration");
const viewport = mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 };

await mkdir(dirname(output), { recursive: true });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport });
const page = await context.newPage();
await page.goto(`${baseUrl}/control`, { waitUntil: "domcontentloaded" });
await page.evaluate(async () => {
  const response = await fetch("/api/auth/local-session", { method: "POST" });
  if (!response.ok) throw new Error(`local session failed: ${response.status}`);
});
await page.goto(
  orchestration ? `${baseUrl}/control?surface=builder&mode=builder` : `${baseUrl}/control`,
  { waitUntil: "domcontentloaded" },
);
await page.locator(".fluxos-shell").waitFor({ state: "visible", timeout: 30000 });
if (orchestration) {
  const orchestrationSurface = page.locator('[data-neyvia-orchestration="true"]');
  try {
    await orchestrationSurface.waitFor({ state: "visible", timeout: 30000 });
  } catch (error) {
    const debug = await page.evaluate(() => ({
      href: window.location.href,
      mode: document.querySelector("[data-neyvia-product-mode]")?.getAttribute("data-neyvia-product-mode") || "",
      shellClass: document.querySelector(".fluxos-shell")?.className || "",
      orchestrationCount: document.querySelectorAll('[data-neyvia-orchestration="true"]').length,
      orchestrationDisplay: (() => {
        const node = document.querySelector('[data-neyvia-orchestration="true"]');
        return node ? window.getComputedStyle(node).display : "missing";
      })(),
    }));
    throw new Error(`orchestration surface did not become visible: ${JSON.stringify(debug)}`, { cause: error });
  }
}
await page.screenshot({ path: output, fullPage: true });

const proof = await page.evaluate(() => ({
  title: document.title,
  productModes: document.querySelectorAll("[data-neyvia-product-mode]").length,
  criticalSurfaces: document.querySelectorAll("[data-neyvia-critical-surface]").length,
  orchestrationSurfaces: document.querySelectorAll('[data-neyvia-orchestration="true"]').length,
  diagnosticsVisible: document.querySelectorAll("[data-neyvia-diagnostics][open]").length,
  bodyOverflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
}));

await browser.close();
process.stdout.write(`${JSON.stringify({ ok: true, output, viewport, proof })}\n`);
