import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const OUT = path.join(".agent_control", "nas_transfers");
const note = fs.readFileSync(path.join(".agent_control", "neyvia_admin_password.txt"), "utf8");
const username = note.match(/^Username: (.+)$/m)?.[1];
const password = note.match(/^Password: (.+)$/m)?.[1];
if (!username || !password) throw new Error("The local Neyvia account note is incomplete.");

const candidates = [
  { user: username, pass: password, source: "local_password_note" },
];

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1500, height: 960 } });
const result = {
  url: "https://nas.example.invalid:47880/control",
  attempts: [],
  modeSwitchVerified: false,
};

await page.goto(result.url, { waitUntil: "domcontentloaded", timeout: 45000 });
await page.waitForTimeout(1500);

for (const c of candidates) {
  const attempt = { source: c.source, user: c.user, ok: false };
  const pass = page.locator('input[type="password"]').first();
  if ((await pass.count()) === 0) {
    attempt.note = "no_password_field";
    result.attempts.push(attempt);
    break;
  }
  const user = page.locator('input[type="text"], input[name="username"]').first();
  if (await user.count()) await user.fill(c.user);
  await pass.fill(c.pass);
  const submit = page.getByRole("button", { name: /sign\s*in|log\s*in/i }).first();
  if (await submit.count()) await submit.click();
  else await pass.press("Enter");
  await page.waitForTimeout(2500);
  const body = await page.locator("body").innerText();
  attempt.invalid = /invalid/i.test(body);
  attempt.hasModeSwitch = (await page.locator('[data-neyvia-mode-option="chat"]').count()) > 0;
  attempt.ok = attempt.hasModeSwitch;
  result.attempts.push(attempt);
  if (attempt.ok) {
    await page.locator('[data-neyvia-mode-option="chat"]').first().click();
    await page.waitForTimeout(500);
    await page.locator('[data-neyvia-mode-option="orchestration"]').first().click();
    await page.waitForTimeout(700);
    result.modeSwitchVerified = true;
    result.bodySnippet = (await page.locator("body").innerText()).slice(0, 1000);
    break;
  }
}

await page.screenshot({ path: path.join(OUT, "phase_c_ui_live_control_retry.png") });
fs.writeFileSync(path.join(OUT, "phase_c_ui_live_control_retry.json"), JSON.stringify(result, null, 2));
console.log(
  JSON.stringify(
    {
      modeSwitchVerified: result.modeSwitchVerified,
      attempts: result.attempts.map((a) => ({
        source: a.source,
        user: a.user,
        ok: a.ok,
        invalid: a.invalid,
        hasModeSwitch: a.hasModeSwitch,
        note: a.note,
      })),
      passwordSourcesTried: candidates.map((c) => c.source),
    },
    null,
    2,
  ),
);
await browser.close();
