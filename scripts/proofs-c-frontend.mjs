#!/usr/bin/env node
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import * as image from "../web/src/neyvia/imagePlaygroundState.js";
import * as provider from "../web/src/neyvia/imageProviderAdapters.js";
import { IMAGE_CONTRACTS, checkedImageAction, ImageContractError, checkImagePromptPresets } from "../web/src/neyvia/imagePlaygroundContracts.js";
import { buildMissionControlModel } from "../web/src/neyvia/missionControlModel.js";
import { LIVE_REVIEW_CONTRACT, checkedLiveReviewProjection, LiveReviewContractError } from "../web/src/neyvia/missionReviewContracts.js";

const repository = fileURLToPath(new URL("../", import.meta.url));
export async function runProofsCFrontend({ root = resolve(repository, ".agent_control/proofs-c/frontend") } = {}) {
  const started = performance.now(), checks = [], failures = [], witnesses = new Map();
  const manifest = JSON.parse(await readFile(resolve(repository, "config/proofs/proofs-c-frontend.json"), "utf8"));
  await mkdir(root, { recursive: true });
  const call = async (name, args) => {
    const result = await (image[name] || provider[name])(...args);
    // Registration mutates only this child process's private provider registry.
    witnesses.set(name, { args: name === "registerImageProviderAdapter" ? [args[0], []] : args, result });
    return result;
  };
  const run = async (id, action) => {
    try { await action(); checks.push({ id, status: "passed" }); }
    catch (error) { const failure = { id, status: "failed", error: error.message }; checks.push(failure); failures.push(failure); }
  };
  let project = image.normalizeProject();
  await run("image.compose-select-edit", async () => {
    project.selection = { x: 61.7, y: 18.2, width: 0, height: 89.6, feather: -2, visible: true };
    project = await call("createLayerFromSelection", [project, { name: "Manual selection", promptRole: "composition subject" }]);
    project = await call("updateLayerInProject", [project, project.selectedLayerId, { x: 74.2, y: 33.6, rotation: 12, promptRole: "moved composition subject" }]);
    const payload = await call("projectToProviderPayload", [project, "edit", { snapshotDataUrl: "data:image/svg+xml,manual-composition" }]);
    await writeFile(resolve(root, "composition-payload.json"), JSON.stringify(payload, null, 2) + "\n");
    project = await call("removeLayerFromProject", [project, project.selectedLayerId]);
    const single = { ...project, layers: [project.layers[0]], selectedLayerId: project.layers[0].id };
    await call("removeLayerFromProject", [single, single.selectedLayerId]);
  });
  await run("image.local-adapter-and-receipts", async () => {
    let invoked = false;
    const adapter = {
      id: `manual-compositor-${Date.now()}`, name: "Manual SVG compositor", capabilities: ["generate", "edit", "composition"],
      async request({ project: incoming, operation, payload, snapshotDataUrl }) {
        if (incoming.provider.id !== adapter.id || payload.operation !== operation || payload.inputs.snapshotDataUrl !== snapshotDataUrl || !payload.compositionIntent.startsWith("Preserve the manual layer positions")) throw new Error("Adapter invocation lost composition context");
        invoked = true;
        const rendered = provider.createLocalDraftResult(incoming, operation, "Explicit local SVG compositor; no remote generation claimed.");
        const artifact = resolve(root, "local-compositor.svg");
        await writeFile(artifact, decodeURIComponent(rendered.layer.src.split(",")[1]));
        return { ...rendered, kind: "provider", provider: adapter.name, meta: { outputArtifactPath: artifact } };
      },
    };
    const registered = await call("registerImageProviderAdapter", [adapter]);
    if (provider.getProviderAdapter(registered.id) !== registered) throw new Error("Registered adapter is not addressable");
    const custom = { ...project, provider: { ...project.provider, id: registered.id }, annotationReadiness: { ...project.annotationReadiness, pins: [{ id: "composition-pin", x: 22, y: 30, comment: "Preserve moved subject" }], rectangles: [{ id: "composition-rectangle", x: 22, y: 30, width: 45, height: 55, comment: "Composition proof region" }] } };
    const rendered = await call("requestProviderOperation", [custom, "edit", { snapshotDataUrl: "data:image/svg+xml,manual-composition" }]);
    project = await call("applyProviderResult", [custom, rendered, "edit"]);
    await writeFile(resolve(root, "available-provider-history.json"), JSON.stringify(project.history[0], null, 2) + "\n");
    if (!invoked) throw new Error("Local adapter transport never ran");
    let duplicateRejected = false;
    try { provider.registerImageProviderAdapter(adapter); } catch { duplicateRejected = true; }
    if (!duplicateRejected) throw new Error("Duplicate provider identity accepted");
    const local = { ...project, provider: { ...project.provider, id: "local-composition-draft" } };
    const draft = await call("requestProviderOperation", [local, "generate"]);
    await call("applyProviderResult", [local, draft, "generate"]);
    // No backend callback is supplied: the actual remote route's unavailable path
    // is exercised without making a provider request or substituting a transport.
    const remote = { ...project, provider: { ...project.provider, id: "codex-gpt-image2" } };
    const blocked = await call("requestProviderOperation", [remote, "edit"]);
    if (blocked.kind !== "provider-blocked" || blocked.blockedReason !== "backend_unavailable" || blocked.layer) throw new Error("Unavailable remote route invented an output");
    project = await call("applyProviderResult", [remote, blocked, "edit"]);
    await writeFile(resolve(root, "blocked-provider-receipt.json"), JSON.stringify(blocked.meta, null, 2) + "\n");
  });
  await run("image.annotate-history-thread", async () => {
    const focus = project.history[0];
    if (!focus) throw new Error("Real blocked operation did not retain its receipt");
    project = await call("setFocusedHistoryItem", [project, focus.id]);
    project = await call("updateFocusedHistoryAnnotations", [project, { pins: [{ id: "manual-pin", x: 12, y: 14, comment: "Review unavailable route" }], rectangles: [{ id: "manual-region", x: 12, y: 14, width: 24, height: 20, comment: "Provider status area" }], comments: [{ id: "manual-comment", text: "Failure path captured" }] }]);
    project = await call("createOpsThreadForFocusedHistory", [project, { title: "Manual provider review" }]);
    await call("createOpsThreadForFocusedHistory", [project, { title: "Idempotent repeat" }]);
    await call("setFocusedHistoryItem", [project, "unknown-history"]);
    await writeFile(resolve(root, "image-project.json"), JSON.stringify(project, null, 2) + "\n");
  });
  await run("image.keyboard-review", async () => {
    let trail = [];
    for (const reason of ["focus", "arrow", "group-jump", "edge-jump"]) {
      const change = { fromScope: "queue", fromIndex: 2, fromCount: 7, toScope: "history", toIndex: 1, toCount: 4, reason };
      await call("buildKeyboardTraversalAnnouncement", [change]);
      trail = await call("appendKeyboardJumpTrail", [trail, change, { maxEntries: 3, at: "2026-10-03T12:00:00Z" }]);
    }
    for (const at of [trail.at(-1).at, "invalid", ""]) {
      await call("formatKeyboardJumpTrailEntry", [{ ...trail.at(-1), at }]);
      await call("formatKeyboardJumpTrailTooltip", [{ ...trail.at(-1), at }]);
    }
    checkImagePromptPresets(image.IMAGE_PROMPT_PRESETS);
    let rejected = false;
    try { checkImagePromptPresets(image.IMAGE_PROMPT_PRESETS.map(row => ({ ...row, strength: 2 }))); } catch (error) { rejected = error.contract === "image.prompt.presets"; }
    if (!rejected) throw new Error("Invalid preset strength escaped its module contract");
    checks.push({ id: "image.prompt.presets", status: "passed", corrupt_result_rejected: true });
  });
  await run("mission.review-projection", async () => {
    const input = { snapshot: {}, workspace: {}, mission: null, pendingQuestions: [], pendingApprovals: [], setupHealth: {}, profileParams: {}, inbox: [] };
    for (const snapshot of [{}, { connectedDeviceBridge: { receipts: [{ receiptKind: "live_review_structured_feedback", event_id: "manual-feedback", planner_executor_handoff_id: "manual-handoff" }] } }]) {
      const review = buildMissionControlModel({ ...input, snapshot }).drawers.builder.liveReviewStudio;
      const corrupt = { ...review, events: review.events.slice(1) };
      let rejected = false;
      try { checkedLiveReviewProjection(corrupt); } catch (error) { rejected = error instanceof LiveReviewContractError; }
      if (!rejected) throw new Error("Missing live review event domain escaped projection contract");
    }
    checks.push({ id: LIVE_REVIEW_CONTRACT.id, status: "passed", corrupt_result_rejected: true });
  });
  // An incorrect but well-shaped output must fail the same production checker.
  for (const [name, contract] of Object.entries(IMAGE_CONTRACTS)) {
    await run(contract.id, async () => {
      const witness = witnesses.get(name);
      if (!witness) throw new Error("Missing production action witness");
      const original = witness.result;
      const corrupt = typeof original === "string" ? `${original}\u0000` : Array.isArray(original) ? original.slice(0, -1) : name === "registerImageProviderAdapter" ? { ...original, id: "wrong-provider" } : name === "projectToProviderPayload" ? { ...original, layers: original.layers.slice(1) } : name === "requestProviderOperation" ? { ...original, meta: { ...original.meta, requestId: "" } } : name === "createOpsThreadForFocusedHistory" ? { ...original, annotationReadiness: { ...original.annotationReadiness, activeThreadRef: "wrong-thread" } } : name === "setFocusedHistoryItem" ? { ...original, focusedHistoryId: "wrong-history" } : name === "updateFocusedHistoryAnnotations" ? { ...original, annotationReadiness: { ...original.annotationReadiness, pins: [] } } : { ...original, layers: original.layers.slice(1) };
      let rejected = false;
      try { checkedImageAction(name, witness.args, corrupt); } catch (error) { rejected = error instanceof ImageContractError && error.contract === contract.id; }
      if (!rejected) throw new Error("Corrupt output escaped production contract");
    });
  }
  const contractIds = [...Object.values(IMAGE_CONTRACTS).map(row => row.id), "image.prompt.presets", LIVE_REVIEW_CONTRACT.id];
  const report = { area: "proofs-c-frontend", ok: !failures.length, contracts: contractIds.map(id => ({ id, status: checks.some(row => row.id === id && row.status === "passed") ? "passed" : "failed" })), checks, coverage: manifest.coverage, scratchRoot: resolve(root), elapsedMs: Math.round((performance.now() - started) * 100) / 100, failures, boundary: manifest.frontier };
  await writeFile(resolve(root, "proofs-c-frontend-receipt.json"), JSON.stringify(report, null, 2) + "\n");
  return report;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2), flag = args.indexOf("--root");
  if (flag >= 0 && !args[flag + 1]) throw new Error("--root requires scratch directory");
  const report = await runProofsCFrontend({ root: flag >= 0 ? resolve(args[flag + 1]) : undefined });
  console.log(JSON.stringify(report));
  process.exitCode = report.ok ? 0 : 1;
}
