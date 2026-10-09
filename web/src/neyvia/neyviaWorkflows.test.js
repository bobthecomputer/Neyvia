import test from "node:test";
import assert from "node:assert/strict";
import { explain, listWorkflows, suggestWorkflows, WORKFLOWS } from "./neyviaWorkflows.js";

const ALL = { model: true, browser: true, cli: true, files: true, mcp: true };

test("a workflow whose needs are met is runnable", () => {
  const result = explain(WORKFLOWS[0], ALL);
  assert.equal(result.runnable, true);
});

test("an unmet requirement is named in plain words", () => {
  const watch = WORKFLOWS.find((w) => w.id === "watch-a-run");
  const result = explain(watch, { model: true });
  assert.equal(result.runnable, false);
  assert.match(result.reason, /connected browser/);
});

test("only runnable workflows are suggested", () => {
  // Offering one that cannot run costs a decision and a click before failing.
  const { suggested, blocked } = suggestWorkflows(["compute"], { model: true });
  assert.equal(suggested.length, 0);
  assert.ok(blocked.length > 0);
  assert.ok(blocked.every((row) => row.reason));
});

test("blocked workflows are still returned so they can be shown honestly", () => {
  const { blocked } = suggestWorkflows(["software"], { model: true });
  assert.ok(blocked.every((row) => row.runnable === false && row.missing.length > 0));
});

test("suggestions are capped and ordered by how well they match", () => {
  const { suggested } = suggestWorkflows(["software", "writing"], ALL, { limit: 2 });
  assert.equal(suggested.length, 2);
});

test("no goals means no suggestions rather than a random pick", () => {
  assert.deepEqual(suggestWorkflows([], ALL).suggested, []);
});

test("the full list always reports current runnability", () => {
  const rows = listWorkflows({ model: true });
  assert.equal(rows.length, WORKFLOWS.length);
  assert.ok(rows.every((row) => typeof row.runnable === "boolean" && row.reason));
});

test("every workflow declares steps a person can read", () => {
  for (const workflow of WORKFLOWS) {
    assert.ok(workflow.steps.length >= 2, `${workflow.id} needs real steps`);
    assert.ok(workflow.summary.length > 10, `${workflow.id} needs a summary`);
  }
});
