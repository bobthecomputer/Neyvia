import assert from "node:assert/strict";
import test from "node:test";

import {
  deriveMissionContextRoots,
  deriveProjectProgressHistory,
  deriveSubAgentLanes,
  deriveWorkspaceHealth,
  parseWorkspaceSyncStatus,
} from "./missionControlModel.js";

const conflictedWorkspace = {
  workspace_id: "w1",
  name: "Proj",
  root_path: "C:/p",
  default_runtime: "hermes",
  goals: [
    `sync_status:${JSON.stringify({
      effectiveDirection: "local_to_nas",
      conflictsDetected: 2,
      manualReviewRequired: true,
      conflictSamples: [{ relativePath: "a.txt" }, { relativePath: "b.txt" }],
      syncReceipt: { receiptId: "r1" },
    })}`,
  ],
};

const mission = {
  mission_id: "m1",
  workspace_id: "w1",
  title: "Ship it",
  state: { status: "running" },
  effectiveRouteContract: {
    roles: [
      { role: "planner", provider: "openai-codex", model: "gpt-5.6-sol", effort: "high", fitScore: 90 },
      { role: "not-a-lane" },
    ],
    mutationReceipts: [{ role: "planner", receiptId: "rc1", schema: "fluxio.route_mutation_receipt.v1" }],
  },
};

test("sync status exposes conflict paths and batch controls only when review is needed", () => {
  const status = parseWorkspaceSyncStatus(conflictedWorkspace);
  assert.equal(status.receiptId, "r1");
  assert.deepEqual(status.batchConflictRelativePaths, ["a.txt", "b.txt"]);
  assert.equal(status.firstConflictRelativePath, "a.txt");
  assert.equal(status.batchResolutionControls.length, 3);
  assert.equal(parseWorkspaceSyncStatus({ goals: ["sync_status:{bad"] }).known, false);
  assert.equal(parseWorkspaceSyncStatus({ goals: [] }).resolutionControls.length, 0);
});

test("progress history prefers the backend v1 payload and otherwise says it is derived", () => {
  const backend = { schema: "fluxio.project_progress_history.v1", projects: [{ workspaceId: "w1" }], schedulingQueue: [] };
  assert.equal(deriveProjectProgressHistory({ projectProgressHistory: backend }), backend);
  const derived = deriveProjectProgressHistory({ workspaces: [conflictedWorkspace], missions: [mission] });
  assert.equal(derived.liveData, false);
  assert.equal(derived.schema, undefined);
  assert.equal(derived.projects[0].counts.active, 1);
});

test("workspace health carries sync review state and backend schedule fields", () => {
  const progressHistory = deriveProjectProgressHistory({ workspaces: [conflictedWorkspace], missions: [mission] });
  const [item] = deriveWorkspaceHealth({ workspaces: [conflictedWorkspace], activeConversations: [], progressHistory });
  assert.equal(item.syncLabel, "Sync review needed");
  assert.equal(item.tone, "warn");
  assert.equal(item.activeCount, 1);
  assert.equal(item.missionCount, 1);
});

test("sub-agent lanes cover planner/executor/verifier routes with receipts and controls", () => {
  const lanes = deriveSubAgentLanes({ activeMissions: [mission], freshnessReference: "", productionHarness: "fluxio_hybrid" });
  assert.equal(lanes.length, 1);
  assert.equal(lanes[0].id, "m1:planner");
  assert.equal(lanes[0].laneProof.routeReceipt.receiptId, "rc1");
  assert.deepEqual(lanes[0].controls.map(control => control.id), ["inspect-events", "proof", "reroute", "pause"]);
  assert.equal(lanes[0].fitScore, 90);
});

test("context roots come from the backend contract and stay truthfully empty without one", () => {
  assert.equal(deriveMissionContextRoots({ mission, activeMissions: [mission] }).counts.totalRoots, 0);
  const withRoots = { ...mission, contextRoots: { schema: "fluxio.mission.context_roots.v1", roots: [{}], counts: { totalRoots: 1 } } };
  assert.equal(deriveMissionContextRoots({ mission: withRoots, activeMissions: [] }).counts.totalRoots, 1);
});
