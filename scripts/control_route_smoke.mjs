/**
 * DEPRECATED as a product UI gate.
 *
 * Product gate (structured resident ui.*):
 *   npm run verify:cu
 *
 * See .agent_control/mission_artifacts/cu_acceptance/MATRIX.md
 * Kept for ad-hoc Playwright screenshot work (`npm run verify:legacy-browser-smoke`).
 */
import fs from "node:fs/promises";
import path from "node:path";

async function loadPlaywright() {
  try {
    return await import("playwright");
  } catch (error) {
    throw new Error(
      "Playwright is required for browser verification. Run with: npx -y -p playwright node scripts/control_route_smoke.mjs",
      { cause: error },
    );
  }
}

async function main() {
  console.error(
    "DEPRECATED product gate: prefer `npm run verify:cu`. Continuing as an explicitly named legacy screenshot helper only.",
  );
  const targetUrl = process.argv[2] || process.env.FLUXIO_CONTROL_URL || "http://127.0.0.1:1420/control?fixture=agent-running";
  const artifactDir = path.join(process.cwd(), "artifacts", "control-route-smoke");
  await fs.mkdir(artifactDir, { recursive: true });
  const { chromium } = await loadPlaywright();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const result = {
    targetUrl,
    startedAt: new Date().toISOString(),
    console: [],
    errors: [],
  };
  page.on("console", message => result.console.push({ type: message.type(), text: message.text() }));
  page.on("pageerror", error => result.errors.push({ message: error.message, stack: error.stack }));
  try {
    await page.goto(targetUrl, { waitUntil: "networkidle", timeout: 45_000 });
    result.title = await page.title();
    result.hasRoot = await page.locator("#root").count();
    result.hasFluxioText = await page.getByText(/Fluxio|Syntelos|Agent|Workbench/i).first().count();
    result.screenshot = path.join(artifactDir, `control-route-${Date.now()}.png`);
    await page.screenshot({ path: result.screenshot, fullPage: true });
    result.ok = result.hasRoot > 0 && result.hasFluxioText > 0 && result.errors.length === 0;
  } catch (error) {
    result.ok = false;
    result.errors.push({ message: error.message, stack: error.stack });
  } finally {
    await browser.close();
  }
  result.finishedAt = new Date().toISOString();
  const resultPath = path.join(artifactDir, "latest.json");
  await fs.writeFile(resultPath, JSON.stringify(result, null, 2), "utf8");
  console.log(JSON.stringify({ ok: result.ok, resultPath, screenshot: result.screenshot || "" }, null, 2));
  if (!result.ok) {
    process.exit(1);
  }
}

main().catch(error => {
  console.error(error.message);
  if (error.cause?.message) {
    console.error(error.cause.message);
  }
  process.exit(1);
});
