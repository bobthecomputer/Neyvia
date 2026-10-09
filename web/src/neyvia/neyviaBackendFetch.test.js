import assert from "node:assert/strict";
import test from "node:test";

import { gunzipSync } from "node:zlib";

import {
  encodeJsonBody,
  fetchBackend,
  isNetworkFailure,
  isReadCommand,
  TIMEOUT_MESSAGE,
  UNREACHABLE_MESSAGE,
} from "./neyviaBackendFetch.js";

const noSleep = () => Promise.resolve();

test("only reads are retried", () => {
  assert.equal(isReadCommand("get_neyvia_conversations_command"), true);
  assert.equal(isReadCommand("list_computer_use_twins_command"), true);
  assert.equal(isReadCommand("create_neyvia_conversation_command"), false);
  assert.equal(isReadCommand("delete_neyvia_conversations_command"), false);
});

test("browser network failures are recognised, aborts are not", () => {
  assert.equal(isNetworkFailure(new TypeError("Failed to fetch")), true);
  assert.equal(isNetworkFailure(new TypeError("NetworkError when attempting to fetch resource.")), true);
  assert.equal(isNetworkFailure(new TypeError("Load failed")), true);
  assert.equal(isNetworkFailure(Object.assign(new Error("The user aborted a request"), { name: "AbortError" })), false);
  assert.equal(isNetworkFailure(new Error("get_x failed")), false);
});

test("a read survives a dropped connection and says what happened when it keeps failing", async () => {
  let calls = 0;
  const flaky = async () => {
    calls += 1;
    if (calls < 3) throw new TypeError("Failed to fetch");
    return { status: 200, ok: true };
  };
  const response = await fetchBackend("/api/backend", {}, { command: "get_neyvia_conversations_command", fetchImpl: flaky, sleep: noSleep });
  assert.equal(response.status, 200);
  assert.equal(calls, 3);

  calls = 0;
  const down = async () => { calls += 1; throw new TypeError("Failed to fetch"); };
  await assert.rejects(
    fetchBackend("/api/backend", {}, { command: "get_neyvia_conversations_command", fetchImpl: down, sleep: noSleep }),
    error => error.message === UNREACHABLE_MESSAGE && error.code === "unreachable",
  );
  assert.equal(calls, 3);
});

test("a mutation is attempted once", async () => {
  let calls = 0;
  const down = async () => { calls += 1; throw new TypeError("Failed to fetch"); };
  await assert.rejects(
    fetchBackend("/api/backend", {}, { command: "create_neyvia_conversation_command", fetchImpl: down, sleep: noSleep }),
    error => error.message === UNREACHABLE_MESSAGE,
  );
  assert.equal(calls, 1);
});

test("a gateway error on a read is retried, a PC-offline 503 is not", async () => {
  const statuses = [502, 200];
  const gateway = async () => ({ status: statuses.shift() });
  const response = await fetchBackend("/api/backend", {}, { command: "get_neyvia_conversations_command", fetchImpl: gateway, sleep: noSleep });
  assert.equal(response.status, 200);

  let calls = 0;
  const offline = async () => { calls += 1; return { status: 503 }; };
  const result = await fetchBackend("/api/backend", {}, { command: "get_neyvia_conversations_command", fetchImpl: offline, sleep: noSleep });
  assert.equal(result.status, 503);
  assert.equal(calls, 1);
});

test("a stalled request ends at the deadline with a readable message", async () => {
  const stalled = (_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })));
  });
  await assert.rejects(
    fetchBackend("/api/backend", {}, { command: "create_neyvia_conversation_command", timeoutMs: 20, fetchImpl: stalled, sleep: noSleep }),
    error => error.message === TIMEOUT_MESSAGE && error.code === "timeout",
  );
});

test("an action is never cut off by default, however long it runs", async () => {
  let signalSeen = null;
  const slow = (_url, init) => new Promise(resolve => {
    signalSeen = init.signal;
    setTimeout(() => resolve({ status: 200, ok: true }), 80);
  });
  const response = await fetchBackend("/api/backend", {}, { command: "run_neyvia_orchestration_command", fetchImpl: slow, sleep: noSleep });
  assert.equal(response.status, 200);
  assert.equal(signalSeen.aborted, false);
});

test("the caller's own abort is passed through untouched", async () => {
  const owner = new AbortController();
  const stalled = (_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })));
  });
  const pending = fetchBackend("/api/backend", { signal: owner.signal }, { command: "get_x", timeoutMs: 5000, fetchImpl: stalled, sleep: noSleep });
  owner.abort();
  await assert.rejects(pending, error => error.name === "AbortError");
});

test("a large save is compressed and a small command is left alone", async () => {
  const small = JSON.stringify({ command: "get_task_continuity_command", payload: {} });
  assert.deepEqual(await encodeJsonBody(small), { body: small, headers: {} });

  const large = JSON.stringify({ command: "save_conversation_state_command", payload: { turns: "tool output ".repeat(40000) } });
  const encoded = await encodeJsonBody(large);
  assert.equal(encoded.headers["Content-Encoding"], "gzip");
  assert.ok(encoded.body.byteLength < large.length / 10);
  assert.equal(gunzipSync(Buffer.from(encoded.body)).toString("utf8"), large);
});
