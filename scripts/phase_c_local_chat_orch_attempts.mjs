import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const OUT = path.join(".agent_control", "nas_transfers");
const note = fs.readFileSync(path.join(".agent_control", "neyvia_admin_password.txt"), "utf8");
const password = note.match(/^Password: (.+)$/m)?.[1];
if (!password) throw new Error("The local Neyvia account note is incomplete.");
const RUNTIMES = [
  { id: "claude-code", label: /Claude Code/i },
  { id: "grok-build", label: /Grok Build/i },
  { id: "opencode", label: /^OpenCode$/i },
];

async function login(page) {
  const pass = page.locator('input[type="password"]').first();
  if ((await pass.count()) === 0) return "not_shown";
  const user = page.locator('input[type="text"], input[name="username"]').first();
  if (await user.count()) await user.fill("admin");
  await pass.fill(password);
  const submit = page.getByRole("button", { name: /sign\s*in|log\s*in/i }).first();
  if (await submit.count()) await submit.click();
  else await pass.press("Enter");
  await page.waitForTimeout(2500);
  return "submitted";
}

async function ensureChatMode(page) {
  const chat = page.locator('[data-neyvia-mode-option="chat"]').first();
  if (await chat.count()) {
    await chat.click();
    await page.waitForTimeout(600);
  }
}

async function pickRuntime(page, labelRe) {
  // Prefer select/combobox options mentioning the runtime.
  const select = page.locator("select").filter({ hasText: labelRe }).first();
  if (await select.count()) {
    const options = await select.locator("option").allTextContents();
    const match = options.find((t) => labelRe.test(t));
    if (match) {
      await select.selectOption({ label: match });
      return { ok: true, via: "select", label: match };
    }
  }
  // Click any button/option containing the label.
  const option = page.getByRole("option", { name: labelRe }).first();
  if (await option.count()) {
    await option.click();
    return { ok: true, via: "option" };
  }
  const btn = page.getByRole("button", { name: labelRe }).first();
  if (await btn.count()) {
    await btn.click();
    return { ok: true, via: "button" };
  }
  // Open runtime menus/dropdowns commonly used in Fluxio shell.
  const triggers = page.locator("button, [role='button']").filter({ hasText: /runtime|model|Hermes|Claude|Grok|OpenCode/i });
  const count = await triggers.count();
  for (let i = 0; i < Math.min(count, 12); i += 1) {
    const t = triggers.nth(i);
    await t.click().catch(() => {});
    await page.waitForTimeout(300);
    const item = page.getByText(labelRe).first();
    if (await item.count()) {
      await item.click();
      return { ok: true, via: "menu-item" };
    }
  }
  return { ok: false };
}

async function sendPrompt(page, text) {
  const box = page
    .locator("textarea, [contenteditable='true'], input[type='text']")
    .filter({ hasNot: page.locator('[type="password"]') })
    .last();
  if ((await box.count()) === 0) return { ok: false, error: "no_input" };
  await box.click();
  await box.fill(text).catch(async () => {
    await page.keyboard.type(text);
  });
  const send = page.getByRole("button", { name: /send|run|submit|ask/i }).first();
  if (await send.count()) await send.click();
  else await page.keyboard.press("Enter");
  await page.waitForTimeout(8000);
  return { ok: true };
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1500, height: 960 } });
const result = {
  createdAt: new Date().toISOString(),
  url: "http://127.0.0.1:1420/control",
  login: null,
  modeSwitch: false,
  turns: {},
};

await page.goto(result.url, { waitUntil: "domcontentloaded", timeout: 45000 });
result.login = await login(page);
await page.waitForSelector('[data-neyvia-mode-option="chat"]', { timeout: 20000 });
await ensureChatMode(page);
const orch = page.locator('[data-neyvia-mode-option="orchestration"]').first();
await orch.click();
await page.waitForTimeout(500);
await ensureChatMode(page);
result.modeSwitch = true;

for (const runtime of RUNTIMES) {
  const turn = { runtime: runtime.id, status: "attempted" };
  await ensureChatMode(page);
  turn.pick = await pickRuntime(page, runtime.label);
  turn.send = await sendPrompt(page, `PHASE_C_${runtime.id}_CHAT_PROOF: reply with OK only`);
  const body = await page.locator("body").innerText();
  turn.snippet = body.slice(0, 1800);
  turn.liveActionsVisible = (await page.locator('[data-neyvia-live-actions="true"]').count()) > 0;
  const lower = body.toLowerCase();
  if (/phase_c_.*_ok|\bok\b/.test(lower) && /auth|login|not logged|api key|unauthorized|failed/.test(lower) === false) {
    // weak success heuristic — require no auth words near failure banners
  }
  if (/not logged|loggedin\": false|auth login|login required|api key|unauthorized|device-auth|please log|sign in to/.test(lower)) {
    turn.status = "blocked_auth";
  } else if (/failed|error|not found|unsupported/.test(lower)) {
    turn.status = "failed_or_blocked";
  } else {
    turn.status = "inconclusive_no_clear_success";
  }
  const shot = path.join(OUT, `phase_c_chat_attempt_${runtime.id}.png`);
  await page.screenshot({ path: shot, fullPage: false });
  turn.screenshot = shot;
  result.turns[runtime.id] = turn;
}

// Orchestration smoke: switch mode, confirm >=2 roles, try launch if present.
await page.locator('[data-neyvia-mode-option="orchestration"]').first().click();
await page.waitForTimeout(900);
const orchBody = await page.locator("body").innerText();
result.orchestration = {
  visible: (await page.locator('[aria-label="Orchestration board"], .neyvia-orchestration-board').count()) > 0,
  hasTimeline: /timeline/i.test(orchBody),
  hasRoles: /Operator|Attacker|Defender|Auditor/i.test(orchBody),
  roleRuntimeOptions: {
    claude: /Claude Code/i.test(orchBody),
    grok: /Grok Build/i.test(orchBody),
    opencode: /OpenCode/i.test(orchBody),
  },
  snippet: orchBody.slice(0, 1500),
};
const launch = page.getByRole("button", { name: /launch|start mission|run orchestration|run with proof/i }).first();
if (await launch.count()) {
  await launch.click();
  await page.waitForTimeout(5000);
  result.orchestration.launchClicked = true;
  result.orchestration.afterLaunchSnippet = (await page.locator("body").innerText()).slice(0, 1500);
} else {
  result.orchestration.launchClicked = false;
}
await page.screenshot({ path: path.join(OUT, "phase_c_orchestration_attempt.png"), fullPage: false });

fs.writeFileSync(path.join(OUT, "phase_c_local_chat_orch_attempts.json"), JSON.stringify(result, null, 2));
console.log(
  JSON.stringify(
    {
      modeSwitch: result.modeSwitch,
      turns: Object.fromEntries(Object.entries(result.turns).map(([k, v]) => [k, { status: v.status, pick: v.pick }])),
      orchestration: {
        visible: result.orchestration.visible,
        hasTimeline: result.orchestration.hasTimeline,
        hasRoles: result.orchestration.hasRoles,
        roleRuntimeOptions: result.orchestration.roleRuntimeOptions,
        launchClicked: result.orchestration.launchClicked,
      },
    },
    null,
    2,
  ),
);
await browser.close();
