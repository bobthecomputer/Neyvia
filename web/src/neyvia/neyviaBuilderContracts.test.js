import assert from "node:assert/strict";
import test from "node:test";

import {
  builderNodeBlockers,
  contextImportEvidence,
  contextSourcePayload,
  contextStageRequest,
  dynamicPlanApprovalPayload,
  dynamicPlanApprovalReceipt,
  dynamicPlanRequestPayload,
  dynamicPlanSpawnPayload,
  dynamicPlanStateFromLatestRun,
  managedCliReadiness,
  NEYVIA_DYNAMIC_PLAN_COMMANDS,
  partitionRepairRuns,
  resolveChildConversation,
  selectedContextRows,
  stagedContextReceipt,
} from "./neyviaBuilderContracts.js";

test("selected context rows retain the import receipt lineage", () => {
  const preview = {
    source: { sha256: "source-hash" },
    items: [
      { itemId: "a", content: "safe" },
      { itemId: "b", content: "not selected" },
    ],
  };
  const rows = selectedContextRows(preview, ["a"], { importId: "context-1", sourceSha256: "source-hash" });
  assert.deepEqual(rows, [{
    sourceId: "context-1:a",
    sourceItemId: "a",
    kind: "imported-context",
    content: "safe",
    sourceSha256: "source-hash",
    importId: "context-1",
  }]);
  assert.deepEqual(contextImportEvidence({ importId: "context-1", sourceSha256: "source-hash", scope: { selectedItemIds: ["a"] } }), {
    importId: "context-1",
    sourceSha256: "source-hash",
    selectedItemIds: ["a"],
    importedItems: 0,
    credentialRedactions: 0,
  });
});

test("child navigation only resolves a real child conversation", () => {
  const node = { nodeId: "worker-1", conversationId: "parent" };
  assert.equal(resolveChildConversation(node, [{ conversationId: "other", parentConversationId: "parent" }]), null);
  assert.equal(resolveChildConversation(node, [{
    conversationId: "child",
    parentConversationId: "parent",
    metadata: { nodeId: "worker-1" },
  }]).conversationId, "child");
});

test("Builder keeps exact blockers instead of converting missing proof to success", () => {
  assert.deepEqual(builderNodeBlockers({ nodeId: "worker", lifecycleStage: "working", runtime: "", progress: {} }), [
    "route unavailable",
    "runtime receipt pending",
    "selected context packet not reported",
  ]);
  assert.equal(managedCliReadiness({ agentReady: false, ready: false, blocker: "Claude Code is not installed." }).ready, false);
  assert.equal(managedCliReadiness({ agentReady: true, ready: true }).ready, true);
});

test("browser staging keeps only the backend upload lineage", () => {
  assert.deepEqual(stagedContextReceipt({
    upload_id: "upload-1",
    source_sha256: "a".repeat(64),
    display_name: "codex.jsonl",
    bytes: 128,
    internalPath: "C:\\secret\\staging\\upload-1",
  }), {
    kind: "staged-upload",
    uploadId: "upload-1",
    sourceSha256: "a".repeat(64),
    displayName: "codex.jsonl",
    bytes: 128,
  });
  assert.deepEqual(contextSourcePayload({
    kind: "staged-upload",
    uploadId: "upload-1",
    sourceSha256: "a".repeat(64),
  }), { uploadId: "upload-1", sourceSha256: "a".repeat(64) });
  assert.deepEqual(contextSourcePayload({ kind: "desktop-path", exportPath: "C:\\exports\\codex.jsonl" }), {
    exportPath: "C:\\exports\\codex.jsonl",
  });
});

test("live orchestration progress satisfies identity and context reporting without inventing a final receipt", () => {
  const node = { lifecycleStage: "working", routeSelection: {runtimeId: "opencode-go"},
    progress: {processId: 24260, externalRuntimeSessionId: "session-live", contextContentHash: "observed-hash"}};
  assert.deepEqual(builderNodeBlockers(node), []);
  assert.deepEqual(builderNodeBlockers({...node, resultSummary: {error: "real failure"}}), ["real failure"]);
  assert.deepEqual(builderNodeBlockers({...node, progress: {resumeExternalRuntimeSessionId: "old"}}),
    ["runtime receipt pending", "selected context packet not reported"]);
  assert.equal(node.progress.runtimeReceipt, undefined);
});

test("browser staging accepts the canonical stage_upload receipt shape", () => {
  const sourceSha256 = "b".repeat(64);
  assert.deepEqual(stagedContextReceipt({
    uploadId: "upload-canonical",
    sha256: sourceSha256,
    sizeBytes: 256,
  }), {
    kind: "staged-upload",
    uploadId: "upload-canonical",
    sourceSha256,
    displayName: "",
    bytes: 256,
  });
});

test("Builder separates the newest repair run from retained failures", () => {
  const result = partitionRepairRuns([
    { id: "old-failure", status: "failed", title: "Historical failure", createdAt: "2026-07-30T09:00:00Z" },
    { id: "latest-repair", kind: "repair", status: "running", updatedAt: "2026-07-31T09:00:00Z" },
    { id: "old-repair", runType: "repair", status: "failed", updatedAt: "2026-07-29T09:00:00Z" },
  ]);
  assert.equal(result.latestRepair.id, "latest-repair");
  assert.deepEqual(result.historicalFailures.map(row => row.id), ["old-failure", "old-repair"]);
});

test("Decompose uses the Neyvia dynamic-plan gate instead of the static preset", () => {
  assert.deepEqual(NEYVIA_DYNAMIC_PLAN_COMMANDS, {
    request: "request_neyvia_dynamic_plan_command",
    approve: "approve_neyvia_dynamic_plan_command",
    spawn: "spawn_neyvia_dynamic_children_command",
  });
});

test("dynamic approval receipt is exact and bound to the pending run", () => {
  const identity = { runId: "dynamic-plan-123", planHash: "a".repeat(64) };
  assert.deepEqual(dynamicPlanApprovalReceipt(identity), {
    schema: "neyvia.approval.receipt.v1",
    issuer: "neyvia",
    approved: true,
    runId: "dynamic-plan-123",
    planHash: "a".repeat(64),
  });
  assert.deepEqual(dynamicPlanApprovalPayload(identity), {
    runId: "dynamic-plan-123",
    approvalReceipt: dynamicPlanApprovalReceipt(identity),
  });
  assert.deepEqual(dynamicPlanSpawnPayload(identity), { runId: "dynamic-plan-123" });
  assert.equal(dynamicPlanApprovalReceipt({ runId: "dynamic-plan-123" }), null);
  assert.equal(dynamicPlanApprovalPayload({ planHash: "a".repeat(64) }), null);
});

test("persisted latestRun rehydrates the exact Builder lifecycle and receipts", () => {
  const pendingRun = {
    runId: "dynamic-plan-082cb24c2d4d4d328319",
    conversationId: "conversation-builder",
    status: "awaiting_approval",
    plannerRoute: { runtimeId: "codex", provider: "openai-codex", model: "gpt-5.6-sol", effort: "xhigh" },
    plannerReceipt: { status: "completed", receiptId: "planner-receipt-1" },
    rawReply: "{...}",
    typedPlan: { schema: "neyvia.orchestration.typed-lead-plan.v1" },
    validationErrors: [],
    planHash: "a".repeat(64),
    approvalReceipt: null,
    createdAt: "2026-08-01T09:00:00Z",
    updatedAt: "2026-08-01T09:00:01Z",
  };
  assert.deepEqual(dynamicPlanStateFromLatestRun(pendingRun), {
    lifecycle: "awaiting_approval",
    identity: { runId: pendingRun.runId, planHash: pendingRun.planHash },
    plannerReceipt: pendingRun.plannerReceipt,
    approvalReceipt: null,
    spawnReceipt: null,
  });
  assert.equal(dynamicPlanStateFromLatestRun({ ...pendingRun, status: "blocked" }).lifecycle, "blocked");
  assert.equal(dynamicPlanStateFromLatestRun({ ...pendingRun, status: "spawned" }).lifecycle, "spawned");
  assert.equal(dynamicPlanStateFromLatestRun({ ...pendingRun, status: "approved" }).lifecycle, "spawning");
  assert.equal(dynamicPlanStateFromLatestRun({ ...pendingRun, status: "approved" }).spawnReceipt, null);
});

test("Builder wires request to explicit approval, then spawn and fabric refresh", async () => {
  const source = await import("fs").then(fs => fs.readFileSync(new URL("./NeyviaProductModePanels.jsx", import.meta.url), "utf8"));
  const requestIndex = source.indexOf("NEYVIA_DYNAMIC_PLAN_COMMANDS.request");
  const approveIndex = source.indexOf("NEYVIA_DYNAMIC_PLAN_COMMANDS.approve");
  const spawnIndex = source.indexOf("NEYVIA_DYNAMIC_PLAN_COMMANDS.spawn");
  assert.ok(requestIndex >= 0 && approveIndex > requestIndex && spawnIndex > approveIndex);
  assert.match(source, /dynamicPlanApprovalPayload\(decomposeIdentity\)/);
  assert.match(source, /setDecomposeLifecycle\("blocked"\)/);
  assert.match(source, /await refreshFabric\(\);/);
  assert.match(source, /data-neyvia-approve-dynamic-plan="true"/);
  assert.match(source, /dynamicPlanStateFromLatestRun\(graph\?\.latestRun\)/);
  assert.match(source, /if \(decomposeAction !== "idle"\) return/);
});

test("Decompose omits empty imported context and forwards selected rows only", () => {
  const base = dynamicPlanRequestPayload({
    conversationId: "conversation-1",
    objective: "Bounded objective",
    importedContextRows: [],
  });
  assert.equal(Object.hasOwn(base, "contextSelection"), false);

  const rows = [
    { sourceId: "context-1:a", importId: "context-1", sourceSha256: "a".repeat(64) },
    { sourceId: "context-1:b", importId: "context-1", sourceSha256: "a".repeat(64) },
  ];
  const selected = dynamicPlanRequestPayload({
    conversationId: "conversation-1",
    objective: "Bounded objective",
    importedContextRows: rows,
  });
  assert.deepEqual(selected.contextSelection, rows);
  assert.notEqual(selected.contextSelection, rows);
});

test("browser context staging matches the authenticated raw-upload endpoint", () => {
  const file = { name: "codex.jsonl" };
  const request = contextStageRequest(file);
  assert.equal(request.method, "POST");
  assert.equal(request.credentials, "same-origin");
  assert.equal(request.headers["Content-Type"], "application/octet-stream");
  assert.equal(request.headers["X-Neyvia-File-Name"], "codex.jsonl");
  assert.equal(request.body, file);
});
