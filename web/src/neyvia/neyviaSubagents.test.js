/**
 * Guards for the subagent overview.
 *
 * The failure being prevented: a parent that reads "working" while a child sits
 * blocked on approval. The work looks healthy and quietly is not, and with ten
 * agents running nobody notices which one stopped.
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  describeSubagents,
  normalizeSubagent,
  shouldExpandOverview,
  sortSubagents,
  summarizeSubagents,
} from "./neyviaSubagents.js";

const agent = (id, state, extra = {}) => ({ id, name: id, state, ...extra });

test("a parent takes the state of its most blocked child", () => {
  const summary = summarizeSubagents([
    agent("a", "working"),
    agent("b", "approval"),
    agent("c", "working"),
  ]);
  assert.equal(summary.state, "approval");
  assert.equal(summary.needsYou, true);
  assert.equal(summary.blockingCount, 1);
});

test("failure outranks everything, including approval", () => {
  const summary = summarizeSubagents([agent("a", "approval"), agent("b", "failed")]);
  assert.equal(summary.state, "failed");
});

test("all-working rolls up to working and needs nobody", () => {
  const summary = summarizeSubagents([agent("a", "working"), agent("b", "working")]);
  assert.equal(summary.state, "working");
  assert.equal(summary.needsYou, false);
  assert.match(summary.label, /2 subagents · 2 working/);
});

test("blocked agents sort to the top", () => {
  const sorted = sortSubagents([
    normalizeSubagent(agent("a", "working", { startedAt: 1 })),
    normalizeSubagent(agent("b", "input", { startedAt: 2 })),
    normalizeSubagent(agent("c", "idle", { startedAt: 3 })),
  ]);
  assert.equal(sorted[0].id, "b");
});

test("ordering is stable so the list does not reshuffle under the cursor", () => {
  const rows = [
    normalizeSubagent(agent("z", "working", { startedAt: 5 })),
    normalizeSubagent(agent("a", "working", { startedAt: 5 })),
  ];
  assert.deepEqual(sortSubagents(rows).map((r) => r.id), ["a", "z"]);
  assert.deepEqual(sortSubagents(rows).map((r) => r.id), ["a", "z"]);
});

test("a nameless agent stays addressable", () => {
  const row = normalizeSubagent({ id: "inv-7", state: "working" });
  assert.equal(row.name, "inv-7");
});

test("an agent with no id is discarded", () => {
  assert.equal(normalizeSubagent({ state: "working" }), null);
  assert.equal(normalizeSubagent(null), null);
});

test("an unknown state is not reported as idle", () => {
  assert.equal(normalizeSubagent(agent("a", "explodinating")).state, "unknown");
});

test("terminal and queued agents retain their real lifecycle", () => {
  const finished = summarizeSubagents([agent("a", "completed"), agent("b", "returned")]);
  assert.equal(finished.state, "completed");
  assert.match(finished.label, /all completed/);
  assert.equal(summarizeSubagents([agent("a", "canceled")]).state, "cancelled");
  assert.equal(summarizeSubagents([agent("a", "pending"), agent("b", "done")]).state, "queued");
  assert.equal(summarizeSubagents([agent("a", "blocked"), agent("b", "running")]).needsYou, true);
  assert.equal(normalizeSubagent(agent("a", "running", {startedAt: "2026-09-05T10:00:00Z"})).startedAt, Date.parse("2026-09-05T10:00:00Z"));
});

test("the overview opens itself when something is blocked", () => {
  const blocked = summarizeSubagents([agent("a", "approval")]);
  assert.equal(shouldExpandOverview(blocked), true);

  const calm = summarizeSubagents([agent("a", "working")]);
  assert.equal(shouldExpandOverview(calm), false);
});

test("the overview opens once there are too many to summarise in a line", () => {
  const many = summarizeSubagents([agent("a", "working"), agent("b", "working"), agent("c", "working")]);
  assert.equal(shouldExpandOverview(many), true);
});

test("empty and singular read naturally", () => {
  assert.equal(describeSubagents(0, {}, 0), "No subagents running");
  assert.equal(describeSubagents(1, {}, 1), "1 subagent · 1 needs you");
  assert.equal(describeSubagents(2, {}, 2), "2 subagents · 2 need you");
});

test("launching agents remain visible in a mixed completed and starting team", () => {
  const result = summarizeSubagents([agent("done", "completed"), agent("starting", "connecting_tools")]);
  assert.equal(result.state, "launching");
  assert.equal(result.counts.launching, 1);
  assert.match(result.label, /1 launching/);
  assert.equal(result.needsYou, false);
});
