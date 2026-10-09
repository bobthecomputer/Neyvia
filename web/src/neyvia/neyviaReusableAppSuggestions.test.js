import test from "node:test";
import assert from "node:assert/strict";
import { suggestReusableApp } from "./neyviaReusableAppSuggestions.js";

test("three completed repetitions produce one optional app suggestion", () => {
  const result = suggestReusableApp([
    { id: "m1", title: "Find paid design tasks", status: "completed" },
    { id: "m2", title: "Find paid design tasks", status: "verified" },
    { id: "m3", title: "Find paid design tasks", status: "delivered" },
  ]);
  assert.equal(result?.evidenceCount, 3);
  assert.match(result?.prompt || "", /review before installation/i);
  assert.deepEqual(result?.sourceMissionIds, ["m1", "m2", "m3"]);
});

test("unfinished work never teaches the app", () => {
  const result = suggestReusableApp([
    { title: "Find paid design tasks", status: "failed" },
    { title: "Find paid design tasks", status: "running" },
    { title: "Find paid design tasks", status: "queued" },
  ]);
  assert.equal(result, null);
});

test("generic titles and one-off jobs do not create noise", () => {
  assert.equal(suggestReusableApp([
    { title: "New mission", status: "completed" },
    { title: "New mission", status: "completed" },
    { title: "New mission", status: "completed" },
  ]), null);
  assert.equal(suggestReusableApp([
    { title: "Prepare the quarterly customer report", status: "completed" },
  ]), null);
});

test("an explicit workflow identity survives changing display titles", () => {
  const result = suggestReusableApp([
    { workflowId: "paid-task-search", title: "Search French listings", verified: true },
    { workflowId: "paid-task-search", title: "Search remote listings", proofStatus: "passed" },
    { workflowId: "paid-task-search", title: "Search local listings", status: "done" },
  ]);
  assert.equal(result?.evidenceCount, 3);
  assert.match(result?.summary || "", /3 times/);
});
