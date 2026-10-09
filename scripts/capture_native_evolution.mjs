import { chromium } from "playwright";
import fs from "node:fs/promises";
import path from "node:path";

const baseURL = process.env.NEYVIA_SCREENSHOT_URL || "http://127.0.0.1:47880/control?preview-control=1";
const outputRoot = path.resolve(process.env.NEYVIA_SCREENSHOT_DIR || "proof/native-evolution/screenshots");
await fs.mkdir(outputRoot, { recursive: true });

const browser = await chromium.launch({ headless: true });
const consoleErrors = [];

async function openHarnesses(page) {
  await page.goto(baseURL, { waitUntil: "networkidle", timeout: 120000 });
  const harnessControl = page.getByText(/Harness(?:es| Control)/i).first();
  if (await harnessControl.count()) {
    await harnessControl.click();
  }
  await page.getByRole("heading", { name: /malleable harness with a proof authority/i }).waitFor({ timeout: 45000 });
}

async function capture(name, viewport, actions = async () => {}) {
  const page = await browser.newPage({ viewportSize: viewport, reducedMotion: "reduce" });
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(`${name}: ${message.text()}`);
  });
  page.on("pageerror", (error) => consoleErrors.push(`${name}: ${error.message}`));
  await openHarnesses(page);
  await actions(page);
  const metrics = await page.evaluate(() => ({
    viewport: { width: window.innerWidth, height: window.innerHeight },
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    panel: document.querySelector(".neyvia-native-evolution")?.getBoundingClientRect().toJSON(),
  }));
  if (metrics.scrollWidth > metrics.clientWidth + 1) {
    throw new Error(`${name} has horizontal overflow: ${metrics.scrollWidth} > ${metrics.clientWidth}`);
  }
  await page.screenshot({ path: path.join(outputRoot, `${name}.png`), fullPage: true });
  await fs.writeFile(path.join(outputRoot, `${name}.json`), JSON.stringify(metrics, null, 2));
  await page.close();
}

await capture("desktop-native-overview", { width: 1440, height: 900 });
await capture("desktop-native-expanded", { width: 1440, height: 900 }, async (page) => {
  await page.getByRole("button", { name: /how it works/i }).click();
  await page.getByText("Behavior Space", { exact: true }).waitFor();
});
await capture("compact-native-phone", { width: 390, height: 844 }, async (page) => {
  await page.getByRole("tab", { name: "Phone" }).click();
  await page.getByText(/use the same work from your phone/i).waitFor();
});
await capture("tablet-native-nas", { width: 820, height: 1180 }, async (page) => {
  await page.getByRole("tab", { name: "NAS" }).click();
  await page.getByText(/keep durable work on the NAS/i).waitFor();
});

await browser.close();
await fs.writeFile(
  path.join(outputRoot, "console-errors.json"),
  JSON.stringify(consoleErrors, null, 2),
);
if (consoleErrors.length) {
  throw new Error(`Browser console emitted ${consoleErrors.length} error(s).`);
}
console.log("NEYVIA_NATIVE_SCREENSHOTS_OK");
