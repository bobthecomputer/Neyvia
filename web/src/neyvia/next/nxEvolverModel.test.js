import assert from "node:assert/strict";
import test from "node:test";

import { diffLines, explainTrial, formatGain, gateSteps, groupFamilies, percentChange, runBudget, splitDomain } from "./nxEvolverModel.js";

const objectives = { fitness: { direction: "max", tolerance: 0 }, success: { direction: "max", tolerance: 0 }, tokens: { direction: "min", tolerance: 0 } };
const stat = (lcb, improved, noninferior = lcb >= 0) => ({ lower_confidence_gain: lcb, paired_gain: lcb, improved, noninferior, incumbent_mean: 1, candidate_mean: 1 });
// Shaped after the real cl_skill_v3 trial 1: discovery passes, held-out success lower bound -0.1168 fails tolerance 0.
const rejected = {
  state: "rejected", promoted: false, trial_number: 1,
  stages: [
    { role: "discovery", eligible: true, hard_gates_passed: true, statistics: { success: stat(0, false), tokens: stat(4364, true), fitness: stat(0.0004, true) } },
    { role: "held_out", purpose: "rotating_held_out", eligible: false, hard_gates_passed: true, statistics: { success: stat(-0.116761, false), tokens: stat(4364, true), fitness: stat(0.0003, true) } },
  ],
};

test("a gate rejection names the objective, the stage and the bound", () => {
  const why = explainTrial(rejected, objectives, "cl_skill");
  assert.equal(why.tone, "red");
  assert.match(why.headline, /Rejected/);
  assert.equal(why.reasons.length, 1);
  assert.match(why.reasons[0], /Adherence × quality could be worse on the held-out tasks/);
  assert.match(why.reasons[0], /−11\.7 pts/);
  assert.deepEqual(gateSteps(rejected).map(step => step.state), ["passed", "failed", "skipped"]);
});

test("an accepted trial lists what improved and never reads as rejected", () => {
  const accepted = { state: "accepted", promoted: true, stages: [
    { role: "discovery", eligible: true, statistics: { tokens: stat(319, true) } },
    { role: "held_out", purpose: "rotating_held_out", eligible: true, statistics: { tokens: stat(319, true) } },
    { role: "held_out", purpose: "fresh_reconfirmation", eligible: true, statistics: { success: stat(0, false), tokens: stat(319, true) } },
  ] };
  const why = explainTrial(accepted, objectives, "manual_compression");
  assert.equal(why.tone, "green");
  assert.match(why.reasons[1], /^Instruction tokens improved/);
  assert.deepEqual(gateSteps(accepted).map(step => step.state), ["passed", "passed", "passed"]);
});

test("a blocked trial keeps the incumbent and hides the raw receipt path", () => {
  const why = explainTrial({ state: "blocked", error: "Luna returned invalid JSON; raw receipt C:\\x\\y.jsonl", stages: [] }, objectives, "cl_skill");
  assert.equal(why.reasons[0], "Luna returned invalid JSON");
  assert.match(why.headline, /current version stays/);
});

test("versions group per family; only the newest version may run, and only within budget", () => {
  const domains = [
    { id: "cl_skill", trials: 1, budget: { max_trials: 2 }, frozen_lock: { ok: true } },
    { id: "cl_skill_v3", trials: 1, budget: { max_trials: 1 }, frozen_lock: { ok: true } },
    { id: "cl_skill_v2", trials: 2, budget: { max_trials: 2 }, frozen_lock: { ok: true } },
  ];
  const [family] = groupFamilies(domains);
  assert.deepEqual(family.versions.map(row => row.version), [1, 2, 3]);
  assert.equal(family.current.id, "cl_skill_v3");
  assert.equal(family.totalTrials, 4);
  assert.match(runBudget(family.current, family.current).blocked, /No trials left/);
  assert.match(runBudget(family.versions[0], family.current).blocked, /only on the current version/);
  assert.match(runBudget({ ...family.current, frozen_lock: { ok: false } }, family.current).blocked, /locked checks changed/);
  assert.deepEqual(runBudget({ id: "x", trials: 0, budget: { max_trials: 2 }, frozen_lock: { ok: true } }).options, [1, 2]);
  assert.deepEqual(splitDomain("manual_compression"), { family: "manual_compression", version: 1 });
});

test("gains read in the direction people expect", () => {
  assert.equal(formatGain("tokens", 319), "319 fewer");
  assert.equal(formatGain("tokens", -12), "12 more");
  assert.equal(formatGain("success", -0.116761), "−11.7 pts");
  assert.equal(percentChange(1255, 936), "−25.4%");
  assert.equal(percentChange(1, 1), "same");
});

test("line diff marks changes and folds long unchanged runs", () => {
  const before = ["a", "b", "c", "d", "e", "f", "g", "h"].join("\n");
  const after = ["a", "b", "c", "d", "e", "f", "g", "H"].join("\n");
  const diff = diffLines(before, after);
  assert.equal(diff.added, 1);
  assert.equal(diff.removed, 1);
  assert.deepEqual(diff.rows.map(row => row.type), ["fold", "same", "same", "del", "add"]);
});
