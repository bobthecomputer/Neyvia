import test from "node:test";
import assert from "node:assert/strict";

import { dedupeNeyviaSkillRows } from "./neyviaSkillLibrary.js";

test("dedupes equivalent skill titles across curated and user-installed sources", () => {
  const rows = dedupeNeyviaSkillRows([
    { id: "curated-user-path", name: "User Path Validator", sourceType: "curated", instructions: "Short." },
    { skillId: "user-path-validator", label: "User Path Validator", sourceType: "user_authored", instructions: "Installed instructions." },
    { id: "adaptive-orchestrator", name: "Adaptive Orchestrator", sourceType: "user_authored" },
  ]);

  assert.equal(rows.length, 2);
  assert.equal(rows[0].skillId, "user-path-validator");
  assert.equal(rows[1].name, "Adaptive Orchestrator");
});

test("normalizes slug and title formatting before comparing identity", () => {
  const rows = dedupeNeyviaSkillRows([
    { id: "design-taste-pack", name: "Design Taste Frontend", sourceType: "curated" },
    { id: "design-taste-frontend", name: "design-taste-frontend", sourceType: "user_authored" },
  ]);

  assert.equal(rows.length, 1);
  assert.equal(rows[0].id, "design-taste-frontend");
});

test("keeps genuinely different skills in their original order", () => {
  const rows = dedupeNeyviaSkillRows([
    { id: "alpha", name: "Alpha", sourceType: "curated" },
    { id: "beta", name: "Beta", sourceType: "curated" },
  ]);

  assert.deepEqual(rows.map(item => item.id), ["alpha", "beta"]);
});
