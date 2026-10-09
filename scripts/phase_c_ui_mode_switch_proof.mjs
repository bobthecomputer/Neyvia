import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const OUT_DIR = path.join(".agent_control", "nas_transfers");

async function loginIfNeeded(page, result) {
  const pass = page.locator('input[type="password"]').first();
  if ((await pass.count()) === 0) {
    result.login = "not_shown";
    return;
  }
  result.login = "form_seen";
  const user = page
    .locator('input[name="username"], input[autocomplete="username"], input[type="text"]')
    .first();
  if ((await user.count()) > 0) {
    await user.fill(JSON.parse(process.env.NEYVIA_PROOF_LOGIN || "{}").username || "admin");
  }
  const credentials = JSON.parse(process.env.NEYVIA_PROOF_LOGIN || "{}");
  if (!credentials.password) throw new Error("NEYVIA_PROOF_LOGIN is required for authenticated proof");
  await pass.fill(credentials.password);
  const submit = page.getByRole("button", { name: /log\s*in|sign\s*in|continue|enter/i }).first();
  if ((await submit.count()) > 0) {
    await submit.click();
  } else {
    await pass.press("Enter");
  }
  await page.waitForTimeout(2500);
  result.login = "submitted";
}

async function exercise(url, outPrefix, withLogin) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1500, height: 960 } });
  const result = { url, steps: [], errors: [], withLogin: !!withLogin };
  page.on("pageerror", (e) => result.errors.push(String(e.message || e)));
  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForTimeout(2000);
    result.title = await page.title();
    if (withLogin) await loginIfNeeded(page, result);
    await page.waitForTimeout(1500);
    await page
      .waitForSelector('[data-neyvia-product-mode], [data-neyvia-mode-option], text=Chat', {
        timeout: 20000,
      })
      .catch(() => null);
    const bodyText = await page.locator("body").innerText();
    result.bodySnippet = bodyText.slice(0, 1200);
    result.hasChatText = /\bChat\b/.test(bodyText);
    result.hasOrchestrationText = /\bOrchestration\b/.test(bodyText);
    result.chatOptionCount = await page.locator('[data-neyvia-mode-option="chat"]').count();
    result.orchOptionCount = await page.locator('[data-neyvia-mode-option="orchestration"]').count();
    result.modeSwitchCount = await page
      .locator('.neyvia-product-mode-switch, [aria-label="Neyvia product mode"]')
      .count();

    if (result.chatOptionCount) {
      await page.locator('[data-neyvia-mode-option="chat"]').first().click();
      await page.waitForTimeout(700);
      result.steps.push("clicked_chat");
      result.modeAfterChat = await page
        .locator("[data-neyvia-product-mode]")
        .first()
        .getAttribute("data-neyvia-product-mode")
        .catch(() => null);
      result.liveActionsVisible =
        (await page.locator('[data-neyvia-live-actions="true"]').count()) > 0;
    }

    if (result.orchOptionCount) {
      await page.locator('[data-neyvia-mode-option="orchestration"]').first().click();
      await page.waitForTimeout(900);
      result.steps.push("clicked_orchestration");
      result.modeAfterOrch = await page
        .locator("[data-neyvia-product-mode]")
        .first()
        .getAttribute("data-neyvia-product-mode")
        .catch(() => null);
      result.orchBoardVisible =
        (await page.locator('[aria-label="Orchestration board"], .neyvia-orchestration-board').count()) >
        0;
      const after = await page.locator("body").innerText();
      result.orchHasTimeline = /timeline/i.test(after);
      result.orchHasRoles = /role/i.test(after);
      result.orchSnippet = after.slice(0, 1200);
    }

    const all = await page.locator("body").innerText();
    result.mentionsClaude = /Claude Code/i.test(all);
    result.mentionsGrok = /Grok Build|\bGrok\b/i.test(all);
    result.mentionsOpenCode = /OpenCode/i.test(all);
    const shot = path.join(OUT_DIR, `${outPrefix}.png`);
    await page.screenshot({ path: shot, fullPage: false });
    result.screenshot = shot;
    result.modeSwitchVerified =
      result.chatOptionCount > 0 &&
      result.orchOptionCount > 0 &&
      result.steps.includes("clicked_chat") &&
      result.steps.includes("clicked_orchestration");
  } catch (e) {
    result.fatal = String(e);
    try {
      await page.screenshot({ path: path.join(OUT_DIR, `${outPrefix}-error.png`), fullPage: false });
    } catch {
      // ignore
    }
  }
  await browser.close();
  fs.writeFileSync(path.join(OUT_DIR, `${outPrefix}.json`), JSON.stringify(result, null, 2));
  return result;
}

const local = await exercise("http://127.0.0.1:1420/control", "phase_c_ui_local_control", true);
const live = await exercise(
  "https://nas.example.invalid:47880/control",
  "phase_c_ui_live_control",
  true,
);
const summary = { local, live, createdAt: new Date().toISOString() };
fs.mkdirSync(OUT_DIR, { recursive: true });
fs.writeFileSync(
  path.join(OUT_DIR, "phase_c_ui_mode_switch_summary.json"),
  JSON.stringify(summary, null, 2),
);
console.log(JSON.stringify(summary, null, 2));
