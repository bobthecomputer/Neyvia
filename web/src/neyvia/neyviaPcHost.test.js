import assert from "node:assert/strict";
import test from "node:test";

import { callPcHost, PC_OFFLINE_MESSAGE, PcHostError, readPcHostStatus } from "./neyviaPcHost.js";

function reply(status, body) {
  return { status, ok: status >= 200 && status < 300, json: async () => body };
}

async function withFetch(fn, run) {
  const original = globalThis.fetch;
  globalThis.fetch = fn;
  try { return await run(); } finally { globalThis.fetch = original; }
}

test("computer use is sent with a request id and lets the backend route it to the PC app", async () => {
  let seen = null;
  await withFetch(async (url, init) => { seen = { url, init }; return reply(200, { ok: true, data: { specs: [] } }); }, async () => {
    const data = await callPcHost("list_computer_use_twins_command", {});
    assert.deepEqual(data, { specs: [] });
  });
  assert.equal(seen.url, "/api/backend");
  assert.equal(seen.init.credentials, "same-origin");
  const body = JSON.parse(seen.init.body);
  assert.equal(body.command, "list_computer_use_twins_command");
  assert.ok(body.requestId.length >= 8);
});

test("a disconnected PC app is reported as offline, not as a generic failure", async () => {
  await withFetch(async () => reply(503, { ok: false, error: PC_OFFLINE_MESSAGE, desktopController: true, pcOffline: true }), async () => {
    await assert.rejects(
      callPcHost("verify_computer_use_change_command", { approved: true }),
      error => error instanceof PcHostError && error.offline === true && error.status === 503,
    );
  });
});

test("other failures keep their own message and are not offline", async () => {
  await withFetch(async () => reply(403, { ok: false, error: "The PC owner's account is required for desktop control." }), async () => {
    await assert.rejects(
      callPcHost("run_computer_use_twin_command", {}),
      error => error.offline === false && /PC owner/.test(error.message),
    );
  });
  await withFetch(async () => reply(503, { ok: false, error: "Desktop controller queue is full.", desktopController: true, pcOffline: false }), async () => {
    await assert.rejects(callPcHost("verify_computer_use_change_command", {}), error => error.offline === false && error.status === 503);
  });
});

test("PC status distinguishes online, offline, non-owner and unreachable", async () => {
  const online = await readPcHostStatus(async () => reply(200, { ok: true, data: { online: true, deviceName: "ASUSPSDLB", updatedAt: 1790000000 } }));
  assert.deepEqual(online, { checked: true, registered: true, online: true, deviceName: "ASUSPSDLB", reason: "" });

  const offline = await readPcHostStatus(async () => reply(200, { ok: true, data: { online: false, deviceName: null, updatedAt: 1790000000 } }));
  assert.equal(offline.online, false);
  assert.equal(offline.registered, true);
  assert.equal(offline.reason, PC_OFFLINE_MESSAGE);

  const neverPaired = await readPcHostStatus(async () => reply(200, { ok: true, data: { online: false, deviceName: null, updatedAt: null } }));
  assert.equal(neverPaired.registered, false);

  const other = await readPcHostStatus(async () => reply(403, { ok: false, error: "owner only" }));
  assert.equal(other.online, false);
  assert.match(other.reason, /PC owner/);

  const unreachable = await readPcHostStatus(async () => { throw new TypeError("Failed to fetch"); });
  assert.equal(unreachable.online, false);
  assert.match(unreachable.reason, /Can't reach Neyvia/);
});
