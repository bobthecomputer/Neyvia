import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const baseUrl = process.env.NEYVIA_PHASE7_BASE_URL || "http://127.0.0.1:47887";
const screenshotPath = path.resolve(
  process.env.NEYVIA_PHASE7_SCREENSHOT || "proof/phase7/continuity-settings.png",
);
fs.mkdirSync(path.dirname(screenshotPath), { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });

async function openSettings() {
  await page.locator(".fluxos-shell").waitFor({ state: "visible", timeout: 20000 });
  const rail = page.locator(".reference-settings-rail-link");
  if (await rail.count()) {
    await rail.first().click();
    return;
  }
  const button = page.getByRole("button", { name: "Settings", exact: true });
  if (await button.count()) {
    await button.last().click();
    return;
  }
  const link = page.getByRole("link", { name: "Settings", exact: true });
  if (await link.count()) {
    await link.last().click();
    return;
  }
  const text = page.getByText("Settings", { exact: true });
  if (await text.count()) {
    await text.first().click();
    return;
  }
  throw new Error("The visible app shell did not expose a Settings control.");
}

try {
  await page.goto(`${baseUrl}/control`, { waitUntil: "domcontentloaded" });
  const loginResponse = await page.request.post(`${baseUrl}/api/auth/local-session`);
  const login = await loginResponse.json();
  if (!loginResponse.ok()) {
    throw new Error(`Local session bootstrap failed: ${JSON.stringify(login)}`);
  }
  await page.goto(`${baseUrl}/control`, { waitUntil: "domcontentloaded" });
  await page.locator(".fluxos-shell").waitFor({ state: "visible", timeout: 20000 });

  await openSettings();
  await page.locator('[data-settings-card-tab="continuity"]').click();
  const operations = page.locator('[data-neyvia-operation-settings="true"]');
  await operations.waitFor({ state: "visible" });

  await operations.getByLabel("Progress updates").selectOption("frequent");
  await operations.getByLabel("Notification importance").selectOption("blocking");
  await operations.getByLabel("Verification").selectOption("proportional");
  await operations.getByLabel("Visual effects").selectOption("subtle");
  await operations.getByLabel(/Concurrent GPU jobs/).fill("1");
  await operations.getByLabel(/Maximum estimated cost/).fill("1.5");
  await operations.getByLabel(/When GPU work becomes idle/).selectOption("snapshot-and-delete");

  await page.goto(`${baseUrl}/control`, { waitUntil: "domcontentloaded" });
  await page.locator(".fluxos-shell").waitFor({ state: "visible", timeout: 20000 });
  await openSettings();
  await page.locator('[data-settings-card-tab="continuity"]').click();
  const restored = page.locator('[data-neyvia-operation-settings="true"]');
  await restored.waitFor({ state: "visible" });
  if ((await restored.getByLabel("Progress updates").inputValue()) !== "frequent") {
    throw new Error("Continuity preferences did not survive reload.");
  }

  await page.locator('[data-settings-card-tab="runtimes"]').click();
  const thunder = page.locator(".neyvia-thunder-acceptance");
  await thunder.waitFor({ state: "visible" });
  await thunder.getByText("Simulated · no spend", { exact: true }).waitFor({
    state: "visible",
    timeout: 15000,
  });
  if ((await thunder.getAttribute("data-simulated")) !== "true") {
    throw new Error("Thunder simulator was not clearly identified as simulated.");
  }
  await thunder.getByRole("button", { name: "Run simulated journey" }).click();
  await thunder.getByText("Simulated journey passed").waitFor({
    state: "visible",
    timeout: 15000,
  });
  await thunder.getByText(/idle Policy Applied/i).waitFor({ state: "visible" });

  await page.waitForTimeout(500);
  await page.screenshot({ path: screenshotPath, fullPage: true });
  process.stdout.write(JSON.stringify({
    ok: true,
    baseUrl,
    screenshotPath,
    checks: {
      continuityControlsVisible: true,
      preferencesPersistAfterReload: true,
      simulatedProviderLabelVisible: true,
      simulatedJourneyPassed: true,
      idlePolicyProofVisible: true,
    },
  }));
} catch (error) {
  const diagnosticPath = screenshotPath.replace(/\.png$/i, "-failure.png");
  await page.screenshot({ path: diagnosticPath, fullPage: true });
  const diagnostic = {
    ok: false,
    error: String(error?.message || error),
    url: page.url(),
    title: await page.title(),
    body: (await page.locator("body").innerText()).slice(0, 3000),
    settingsNodes: await page.getByText("Settings", { exact: true }).evaluateAll(nodes =>
      nodes.slice(0, 10).map(node => node.parentElement?.outerHTML || node.outerHTML),
    ),
    openAppNodes: await page.getByText("Open App", { exact: true }).evaluateAll(nodes =>
      nodes.slice(0, 10).map(node => node.outerHTML),
    ),
    screenshotPath: diagnosticPath,
  };
  process.stderr.write(JSON.stringify(diagnostic, null, 2));
  throw error;
} finally {
  await browser.close();
}
