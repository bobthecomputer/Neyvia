// Projection integrity only: event cards and default example paths are not
// receipts that an external browser, runtime or supervisor actually ran.
export const LIVE_REVIEW_CONTRACT = {
  id: "mission.review.projection",
  claim: "Live review preserves every event domain, annotation recovery handles, screenshot/replay links, planner and supervisor route/feedback fields",
};
export class LiveReviewContractError extends Error {
  constructor() { super(`Model contract ${LIVE_REVIEW_CONTRACT.id} failed`); this.contract = LIVE_REVIEW_CONTRACT.id; }
}
const has = (object, keys) => Boolean(object) && keys.every(key => Object.hasOwn(object, key));
export function checkedLiveReviewProjection(review) {
  const domains = {
    file_change: ["artifactPaths", "source"],
    browser_qa: ["previewUrl", "browserActions", "deepLink"],
    computer_use: ["launchedPrograms", "runtimeActivity", "deepLink"],
    preview_refresh: ["screenshotFrames"],
    verification: ["tests", "deepLink"],
    image_playground: ["queueTimeline", "providerEvents", "generatedImages", "layerHandoff", "artifactPaths"],
    operator_followup: ["operatorMessages", "acknowledgedBy"],
    progress_update: ["cadenceMinutes", "cadenceState", "cadenceAgeMinutes", "progressUpdate", "selectedSkills", "plannerRules", "designPrompts", "nextIdea", "structuredFeedbackReceipt"],
    runtime_activity: ["runtimeActivity", "deepLink"],
    continuation_supervisor: ["continuationSupervisor", "selectedSkills", "designPrompts", "nextIdea", "structuredFeedbackReceipt", "deepLink"],
    replay_marker: ["replayMarkers"],
  };
  const events = review?.events;
  let valid = Array.isArray(events) && new Set(events.map(row => row.id)).size === events.length && Object.entries(domains).every(([kind, keys]) => {
    const rows = events.filter(row => row.kind === kind);
    return rows.length === 1 && has(rows[0], ["id", "kind", "timestamp", ...keys]);
  });
  const byKind = kind => events?.find(row => row.kind === kind);
  valid &&= has(review?.plannerProof, ["selectedSkills", "plannerRules", "designPrompts", "nextIdea", "structuredFeedbackReceipt", "latestStructuredFeedbackReceipt", "decisionInfluence"]) && ["selectedSkills", "plannerRules", "designPrompts", "decisionInfluence"].every(key => Array.isArray(review.plannerProof[key]));
  valid &&= has(review?.continuationSupervisor, ["state", "failureReason", "blockerReason", "dispatchLagMinutes", "reconcileLatencyMs", "externalHeartbeatRequired", "routePreservation"]) && typeof review.continuationSupervisor.externalHeartbeatRequired === "boolean" && has(review.continuationSupervisor.routePreservation, ["selectedSkills", "designPrompts", "nextIdea", "model", "provider", "effort", "executionRoot"]);
  valid &&= Array.isArray(review?.annotationReadiness?.blocks) && review.annotationReadiness.blocks.every(row => has(row, ["id", "page", "recoveryAction"]) && (has(row, ["pin"]) || has(row, ["rectangle"])));
  valid &&= byKind("preview_refresh").screenshotFrames.every(row => has(row, ["id", "path", "thumbnailPath", "timestamp"])) && byKind("replay_marker").replayMarkers.every(row => has(row, ["id", "snapshotPath", "frameId", "deepLink"]) && has(row.deepLink, ["proofTarget", "threadTarget"]));
  valid &&= has(byKind("progress_update").progressUpdate, ["changed", "blocker", "tests", "next"]) && byKind("progress_update").selectedSkills === review.plannerProof.selectedSkills && byKind("continuation_supervisor").continuationSupervisor === review.continuationSupervisor;
  for (const row of [review?.plannerProof?.structuredFeedbackReceipt, review?.plannerProof?.latestStructuredFeedbackReceipt]) {
    if (row && Object.keys(row).length) valid &&= has(row, ["receiptKind", "eventId", "plannerExecutorHandoffId"]) && row.receiptKind === "live_review_structured_feedback";
  }
  if (!valid) throw new LiveReviewContractError();
  return review;
}
