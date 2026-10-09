import test from "node:test";
import assert from "node:assert/strict";

import { uniqueDialogueOverlay, reconcileChatTranscriptTurns, savedTurnRuntimeDetails } from "./neyviaTranscriptMerge.js";

test("status previews cannot truncate received text and full results repair prefixes", () => {
  const full = { id: "answer", role: "assistant", title: "a".repeat(1200) + " preserved ending", pending: true };
  const preview = { ...full, title: full.title.slice(0, 1200), pending: false };
  assert.equal(reconcileChatTranscriptTurns([full, preview])[0].title, full.title);
  assert.equal(reconcileChatTranscriptTurns([full, preview])[0].pending, false);
  assert.equal(reconcileChatTranscriptTurns([preview, { ...full, pending: false }])[0].title, full.title);
});

test("saved chat reads its actual persisted runtime result without inventing a missing model", () => {
  const receipt = { model: "gpt-6-astra", provider: "openai-codex", effort: "high", runtime: "hermes" };
  assert.deepEqual(savedTurnRuntimeDetails({ metadata: { runtimeResult: { compartment: { turnReceipt: receipt } } } }), { model: "gpt-6-astra", provider: "openai-codex", effort: "high", runtimeId: "hermes", turnReceipt: receipt });
  assert.equal(savedTurnRuntimeDetails({}).model, "");
});

test("reconciles persisted completion by turn ID without dropping repeated messages", () => {
  const pending = { id: "turn-1", role: "assistant", title: "Thinking", pending: true };
  const completed = { ...pending, title: "yes", pending: false };
  const repeated = { ...completed, id: "turn-2" };
  assert.deepEqual(reconcileChatTranscriptTurns([pending, completed, repeated, completed]), [completed, repeated]);
});

test("removes old compartment copies while preserving unmatched history and repeated turns", () => {
  const primary = { id: "turn-1", role: "user", title: "yes" };
  const copy = { ...primary, id: "compartment-1", role: "operator" };
  const repeated = { ...copy, id: "compartment-2" };
  assert.deepEqual(reconcileChatTranscriptTurns([primary, copy, repeated]), [primary, repeated]);
  assert.deepEqual(uniqueDialogueOverlay([primary], [copy]), []);
});

test("removes runtime snapshot copies of a completed exchange", () => {
  const primary = [
    { role: "user", title: "Inspect the UI" },
    { role: "assistant", title: "The UI is ready." },
  ];
  const runtimeSnapshot = [
    { role: "user", title: "Inspect the UI" },
    { role: "assistant", title: "The UI is ready." },
  ];

  assert.deepEqual(uniqueDialogueOverlay(primary, runtimeSnapshot), []);
});

test("preserves a genuinely additional repeated turn", () => {
  const primary = [{ role: "user", title: "yes" }];
  const runtimeSnapshot = [
    { role: "user", title: " yes " },
    { role: "user", title: "YES" },
  ];

  assert.deepEqual(uniqueDialogueOverlay(primary, runtimeSnapshot), [runtimeSnapshot[1]]);
});

test("keeps distinct runtime-only dialogue in source order", () => {
  const runtimeSnapshot = [
    { role: "assistant", title: "First new reply" },
    { role: "assistant", title: "Second new reply" },
  ];

  assert.deepEqual(uniqueDialogueOverlay([], runtimeSnapshot), runtimeSnapshot);
});
