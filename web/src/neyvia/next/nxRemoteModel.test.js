import assert from "node:assert/strict";
import test from "node:test";

import { countdown, endsConnection, normalizeAddress, pngSize, remoteKey, scrollerAt, textBoxAt, timeLeft } from "./nxRemoteModel.js";

// The owning PC refuses everything but these; the UI must never offer more.
test("remoteKey sends text and navigation keys, blocks Enter, Tab, Delete and shortcuts", () => {
  assert.deepEqual(remoteKey({ key: "a" }), { kind: "text", text: "a" });
  assert.deepEqual(remoteKey({ key: "ArrowLeft" }), { kind: "press_key", key: "left" });
  assert.deepEqual(remoteKey({ key: "Backspace" }), { kind: "press_key", key: "backspace" });
  assert.equal(remoteKey({ key: "Enter" }).kind, "blocked");
  assert.equal(remoteKey({ key: "Tab" }).kind, "blocked");
  assert.equal(remoteKey({ key: "Delete" }).kind, "blocked");
  assert.equal(remoteKey({ key: "v", ctrlKey: true }).kind, "blocked");
  assert.equal(remoteKey({ key: "Shift" }), null);
});

const elements = [
  { element_token: "w", role: "Window", enabled: true, offscreen: false, actions: ["scroll"], screenshot_frame: { x: 0, y: 0, w: 400, h: 300 } },
  { element_token: "e", role: "Edit", enabled: true, offscreen: false, actions: ["set_value"], screenshot_frame: { x: 20, y: 20, w: 200, h: 20 } },
  { element_token: "b", role: "Button", enabled: true, offscreen: false, actions: ["invoke"], screenshot_frame: { x: 20, y: 60, w: 200, h: 30 } },
  { element_token: "x", role: "Edit", enabled: false, offscreen: false, actions: ["set_value"], screenshot_frame: { x: 20, y: 100, w: 200, h: 20 } },
];

test("only an enabled text box under the pointer takes typing; scroll finds the scroller", () => {
  assert.equal(textBoxAt(elements, 30, 25)?.element_token, "e");
  assert.equal(textBoxAt(elements, 30, 70), null);
  assert.equal(textBoxAt(elements, 30, 105), null);
  assert.equal(scrollerAt(elements, 30, 70)?.element_token, "w");
});

test("pngSize reads the header and rejects anything else", () => {
  const bytes = new Uint8Array(24);
  bytes.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13, 0x49, 0x48, 0x44, 0x52]);
  new DataView(bytes.buffer).setUint32(16, 480);
  new DataView(bytes.buffer).setUint32(20, 300);
  assert.deepEqual(pngSize(bytes.buffer), { width: 480, height: 300 });
  assert.equal(pngSize(new Uint8Array(10).buffer), null);
});

test("times, ends and addresses", () => {
  const now = Date.parse("2026-10-03T20:00:00Z");
  assert.equal(timeLeft("2026-10-03T20:12:00Z", now), "12 min left");
  assert.equal(timeLeft("2026-10-03T20:00:40Z", now), "40 s left");
  assert.equal(timeLeft("2026-10-03T19:59:00Z", now), "Time's up");
  assert.equal(countdown(now + 112000, now), "1:52");
  assert.ok(endsConnection("session_stopped") && endsConnection("capability_invalid"));
  assert.ok(!endsConnection("protected_window") && !endsConnection("host_unavailable"));
  assert.equal(normalizeAddress(" 192.0.2.10:47880/ "), "http://192.0.2.10:47880");
});
