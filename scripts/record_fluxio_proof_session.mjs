import fs from "node:fs/promises";
import path from "node:path";

function stamp() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

function ensureUrl(value) {
  const raw = String(value || "http://127.0.0.1:1420/control?fixture=agent-running").trim();
  return raw || "http://127.0.0.1:1420/control?fixture=agent-running";
}

async function loadPlaywright() {
  try {
    return await import("playwright");
  } catch (error) {
    throw new Error(
      "Playwright is required for proof recording. Run with: npx -y -p playwright node scripts/record_fluxio_proof_session.mjs",
      { cause: error },
    );
  }
}

async function main() {
  const targetUrl = ensureUrl(process.argv[2]);
  const root = process.cwd();
  const sessionRoot = path.join(root, "artifacts", `fluxio-proof-${stamp()}`, "product-ui-session");
  const videoDir = path.join(sessionRoot, "videos");
  await fs.mkdir(videoDir, { recursive: true });

  const { chromium, devices } = await loadPlaywright();
  const browser = await chromium.launch({ headless: true });
  const transcript = {
    kind: "fluxio.product-ui-proof",
    targetUrl,
    startedAt: new Date().toISOString(),
    artifacts: [],
    steps: [],
    console: [],
    errors: [],
  };

  async function captureViewport(name, viewport, device = null) {
    const context = await browser.newContext({
      ...(device || {}),
      viewport,
      recordVideo: { dir: videoDir, size: viewport },
    });
    await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
    const page = await context.newPage();
    page.on("console", message => transcript.console.push({ type: message.type(), text: message.text() }));
    page.on("pageerror", error => transcript.errors.push({ message: error.message, stack: error.stack }));
    const proof = { name, viewport, steps: [] };
    try {
      await page.goto(targetUrl, { waitUntil: "networkidle", timeout: 45_000 });
      proof.steps.push("loaded");
      await page.keyboard.press("Tab");
      proof.steps.push("keyboard-tabbed");
      const screenshotPath = path.join(sessionRoot, `${name}.png`);
      await page.screenshot({ path: screenshotPath, fullPage: true });
      transcript.artifacts.push(screenshotPath);

      for (const label of ["Workbench", "Skills", "Agent"]) {
        const control = page.getByRole("button", { name: new RegExp(label, "i") }).first();
        if (await control.count()) {
          await control.click({ timeout: 5_000 });
          await page.waitForTimeout(350);
          const surfacePath = path.join(sessionRoot, `${name}-${label.toLowerCase()}.png`);
          await page.screenshot({ path: surfacePath, fullPage: true });
          transcript.artifacts.push(surfacePath);
          proof.steps.push(`clicked:${label}`);
        }
      }
    } catch (error) {
      proof.error = error.message;
      transcript.errors.push({ viewport: name, message: error.message, stack: error.stack });
    } finally {
      const tracePath = path.join(sessionRoot, `${name}.trace.zip`);
      await context.tracing.stop({ path: tracePath });
      transcript.artifacts.push(tracePath);
      const pages = context.pages();
      await Promise.all(pages.map(item => item.close().catch(() => {})));
      await context.close();
      proof.finishedAt = new Date().toISOString();
      transcript.steps.push(proof);
    }
  }

  await captureViewport("desktop", { width: 1440, height: 1000 });
  await captureViewport("mobile", { width: 390, height: 844 }, devices["Pixel 7"]);
  await browser.close();

  transcript.finishedAt = new Date().toISOString();
  transcript.status = transcript.errors.length ? "completed_with_errors" : "completed";
  const transcriptPath = path.join(sessionRoot, "product-ui-transcript.json");
  await fs.writeFile(transcriptPath, JSON.stringify(transcript, null, 2), "utf8");
  await fs.writeFile(
    path.join(sessionRoot, "README.md"),
    [
      "# Fluxio Product UI Proof",
      "",
      `Target: ${targetUrl}`,
      `Status: ${transcript.status}`,
      `Started: ${transcript.startedAt}`,
      `Finished: ${transcript.finishedAt}`,
      "",
      "Artifacts are screenshots, Playwright traces, and browser-recorded videos generated from the live page.",
      "",
    ].join("\n"),
    "utf8",
  );
  console.log(JSON.stringify({ ok: transcript.errors.length === 0, sessionRoot, transcriptPath }, null, 2));
}

main().catch(error => {
  console.error(error.message);
  if (error.cause?.message) {
    console.error(error.cause.message);
  }
  process.exit(1);
});
