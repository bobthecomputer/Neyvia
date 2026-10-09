import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const OUT = path.join(".agent_control", "nas_transfers");
const note = fs.readFileSync(path.join(".agent_control", "neyvia_admin_password.txt"), "utf8");
const password = note.match(/^Password: (.+)$/m)?.[1];
if (!password) throw new Error("The local Neyvia account note is incomplete.");
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1500, height: 960 } });
const result = { url: "http://127.0.0.1:1420/control", steps: [] };

try {
  await page.goto(result.url, { waitUntil: "domcontentloaded", timeout: 45000 });
  await page.waitForTimeout(2000);
  result.title = await page.title();
  result.before = (await page.locator("body").innerText()).slice(0, 1200);
  const pass = page.locator('input[type="password"]').first();
  result.hasPassword = (await pass.count()) > 0;
  if (result.hasPassword) {
    const user = page.locator('input[type="text"], input[name="username"]').first();
    if (await user.count()) await user.fill("admin");
    await pass.fill(password);
    const submit = page.getByRole("button", { name: /sign\s*in|log\s*in/i }).first();
    if (await submit.count()) await submit.click();
    else await pass.press("Enter");
    await page.waitForTimeout(3500);
    result.steps.push("login_submitted");
  }
  result.after = (await page.locator("body").innerText()).slice(0, 1500);
  result.chatCount = await page.locator('[data-neyvia-mode-option="chat"]').count();
  result.orchCount = await page.locator('[data-neyvia-mode-option="orchestration"]').count();
  result.hasChatText = /\bChat\b/.test(result.after || "");
  result.hasOrchText = /\bOrchestration\b/.test(result.after || "");
  await page.screenshot({ path: path.join(OUT, "phase_c_local_login_debug.png"), fullPage: false });
} catch (e) {
  result.fatal = String(e);
  try {
    await page.screenshot({ path: path.join(OUT, "phase_c_local_login_debug_error.png"), fullPage: false });
  } catch {}
}
fs.writeFileSync(path.join(OUT, "phase_c_local_login_debug.json"), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
await browser.close();
