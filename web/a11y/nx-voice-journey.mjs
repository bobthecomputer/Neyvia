// Voice control journey: drive the real UI like Paul would and take a screenshot per step.
//
//   node web/a11y/nx-voice-journey.mjs --url http://127.0.0.1:1503 --out <dir> [--live] [--wav <file>]
//
// Default: the dev design fixtures (`?fixtures=1`), commands typed into the voice card.
// --live: the real backend (voice_command_command) instead of the fixtures.
// --wav: also say a command through a fake microphone playing this file (Chromium's fake capture),
//        so the words go through the real speech engine first.
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

const require = createRequire(resolve("package.json"));
const { chromium } = require("playwright");
const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, index, all) => (value.startsWith("--") ? [...pairs, [value.slice(2), all[index + 1]?.startsWith("--") || all[index + 1] == null ? "1" : all[index + 1]]] : pairs), []));
const base = (args.url || "http://127.0.0.1:1503").replace(/\/$/, "");
const out = resolve(args.out || "voice-out");
mkdirSync(out, { recursive: true });
const live = Boolean(args.live);
const query = live ? "ui=next" : "fixtures=1&bus=mock&busscript=0&ui=next";

const launch = { args: [] };
if (args.wav) launch.args.push("--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", `--use-file-for-fake-audio-capture=${resolve(args.wav)}`);
const browser = await chromium.launch(launch);
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: args.wav ? ["microphone"] : [] });
const page = await context.newPage();
const log = [];
page.on("pageerror", error => log.push({ pageerror: error.message }));

// A fresh state root opens first-run setup; close it like Paul would (Esc).
async function settle() {
  await page.waitForTimeout(800);
  for (let tries = 0; tries < 3 && await page.locator(".nx-onb").count(); tries += 1) { await page.keyboard.press("Escape"); await page.waitForTimeout(600); }
}
async function shot(name) { await page.waitForTimeout(500); await page.screenshot({ path: join(out, `${name}.png`) }); }
async function say(text) {
  if (!(await page.locator(".nx-voice-card").count())) {
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: /Voice commands/ }).click();
    await page.waitForTimeout(300); // the button starts listening; typing a command drops that recording
  }
  const field = page.getByRole("textbox", { name: "Type a voice command" });
  await field.fill(text);
  await field.press("Enter");
  await page.waitForFunction(() => !document.querySelector(".nx-voice-status q") || document.querySelector(".nx-voice-say"), null, { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(700);
  const card = await page.locator(".nx-voice-card").innerText().catch(() => "");
  const announced = await page.evaluate(() => (globalThis.__nxAnnounced || []).slice(-1)[0]?.text || "");
  log.push({ said: text, card: card.replace(/\s+/g, " ").trim(), announced });
  return card;
}

await page.goto(`${base}/control?${query}`, { waitUntil: "load" });
await page.waitForSelector(".nx-root", { timeout: 20000 });
await page.waitForTimeout(1500);
await settle();

// 1. Open an app by voice.
await page.getByRole("button", { name: /Voice commands/ }).click();
await page.waitForTimeout(600);
await shot("01-voice-card-listening");
await page.locator(".nx-voice-x").click();
await say("open notes");
log.push({ check: "notes open", ok: await page.locator(".nx-notes").count() > 0 });
await shot("02-open-notes");

// 2. Close it, then a new Codex chat in the dictation folder.
await say("close");
log.push({ check: "stage closed", ok: (await page.locator(".nx-notes").count()) === 0 });
await say("new codex chat in dictation");
const newChat = await page.locator(".nx-new").innerText().catch(() => "");
log.push({ check: "new chat: codex + dictation folder", ok: /dictation/i.test(newChat) && (await page.getByRole("radio", { name: "Codex" }).getAttribute("aria-checked")) === "true" });
await shot("03-new-codex-chat-in-dictation");

// 3. Approve what's on screen.
await page.goto(`${base}/control?${query}&chat=s-codex-approve`, { waitUntil: "load" });
await settle();
await page.waitForSelector(".nx-pending", { timeout: 20000 }).catch(() => {});
await page.waitForTimeout(800);
await say("approve");
log.push({ check: "approved toast", ok: /Approved/.test(await page.locator(".nx-toasts").innerText().catch(() => "")) });
await shot("04-approve");

// 4. Something it doesn't know, and an ambiguous name: nothing runs, choices are offered.
await say("open chat quantization");
await say("make me a sandwich");
await shot("05-no-match-choices");

// 5. Help: every shortcut and command.
await say("what can I say");
log.push({ check: "help sheet", ok: await page.getByRole("dialog", { name: "Keyboard and voice" }).count() > 0 });
await shot("06-keyboard-and-voice");
await page.keyboard.press("Escape");

// 6. Keyboard only: Ctrl+/ opens the same sheet, focus is inside it, Tab stays inside.
await page.keyboard.press("Control+/");
await page.waitForTimeout(400);
const inside = [];
for (let index = 0; index < 4; index += 1) { await page.keyboard.press("Tab"); inside.push(await page.evaluate(() => Boolean(document.activeElement?.closest(".nx-help")))); }
log.push({ check: "focus trapped in sheet", ok: inside.every(Boolean) });
await page.keyboard.press("Escape");

// 7. Real microphone path (optional): hold Ctrl+Alt+Space while the fake mic plays the file.
if (args.wav) {
  await page.goto(`${base}/control?${query}`, { waitUntil: "load" });
  await page.waitForSelector(".nx-root");
  await page.waitForTimeout(1500);
  await settle();
  await page.keyboard.down("Control"); await page.keyboard.down("Alt"); await page.keyboard.down("Space");
  await page.waitForTimeout(Number(args.holdMs || 3500));
  await page.keyboard.up("Space"); await page.keyboard.up("Alt"); await page.keyboard.up("Control");
  await page.waitForFunction(() => document.querySelector(".nx-voice-say") || document.querySelector(".nx-voice-card.is-error"), null, { timeout: 120000 }).catch(() => {});
  await page.waitForTimeout(800);
  log.push({ spoken: await page.locator(".nx-voice-card").innerText().catch(() => "(no card)"), notesOpen: await page.locator(".nx-notes").count() > 0 });
  await shot("07-spoken-command");
}

writeFileSync(join(out, "journey.json"), JSON.stringify(log, null, 2));
console.log(JSON.stringify(log, null, 2));
await browser.close();
