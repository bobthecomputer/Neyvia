import { checkCapabilityAction } from "./neyviaCapabilityContracts.js";
export const CAPABILITY_EVOLUTION_COMMANDS = Object.freeze({
  snapshot: "get_capability_evolution_command",
  createTrial: "create_capability_evolution_trial_command",
  sealCandidate: "seal_capability_skill_candidate_command",
  recordEvidence: "record_capability_evolution_evidence_command",
  buildForge: "build_capability_counterfactual_forge_command",
  decideTrial: "decide_capability_evolution_trial_command",
  materializeSkill: "materialize_capability_skill_command",
  establishProofLease: "establish_capability_proof_lease_command",
  renewProofLease: "renew_capability_proof_lease_command",
  recordProofLeaseDisposition:
    "record_capability_proof_lease_disposition_command",
  rollbackSkill: "rollback_capability_skill_materialization_command",
  acceptOutcome: "accept_constellation_outcome_command",
  importAppOutcomes: "import_capability_run_bundle_command",
});

export const COUNTERFACTUAL_FORGE_SCHEMA =
  "neyvia.counterfactual_skill_forge.v1";
export const SEALED_SKILL_CANDIDATE_SCHEMA =
  "neyvia.sealed_skill_candidate.v1";
export const COUNTERFACTUAL_CASE_LIMIT = 6;
const SKILL_CANDIDATE_ACTIONS = new Set(["branch", "repair", "merge"]);

const ACTION_ORDER = new Map([
  ["repair", 0],
  ["branch", 1],
  ["prove", 2],
  ["merge", 3],
  ["quarantine", 4],
  ["retire", 5],
  ["promote_to_app", 6],
]);

export function asCapabilityList(value) {
  return Array.isArray(value) ? value : [];
}

function capabilityActionLabelUnchecked(action) {
  const labels = {
    prove: "Prove",
    branch: "Branch",
    repair: "Repair",
    merge: "Merge",
    quarantine: "Quarantine",
    retire: "Retire",
    promote_to_app: "Make app",
  };
  return labels[String(action || "")] || "Review";
}

export function capabilityTone(action, state = "") {
  const normalizedState = String(state || "").toLowerCase();
  if (["accepted", "evidence_ready"].includes(normalizedState)) return "good";
  if (["rejected", "cancelled"].includes(normalizedState)) return "quiet";
  if (["repair", "quarantine", "retire"].includes(String(action || ""))) return "warn";
  if (String(action || "") === "promote_to_app") return "good";
  return "learning";
}

function selectCapabilityRecommendationUnchecked(snapshot) {
  const recommendations = [
    ...asCapabilityList(snapshot?.appOutcomeLearning?.proposals),
    ...asCapabilityList(snapshot?.recommendations),
  ];
  if (!recommendations.length) return null;
  return [...recommendations].sort((left, right) => {
    const leftActive = left?.status === "trial_active" ? -1 : 0;
    const rightActive = right?.status === "trial_active" ? -1 : 0;
    if (leftActive !== rightActive) return leftActive - rightActive;
    const priorityDifference =
      Number(left?.priority ?? 9) - Number(right?.priority ?? 9);
    if (priorityDifference) return priorityDifference;
    const leftOrder = ACTION_ORDER.get(left?.action) ?? 99;
    const rightOrder = ACTION_ORDER.get(right?.action) ?? 99;
    if (leftOrder !== rightOrder) return leftOrder - rightOrder;
    const leftUsage = Number(
      left?.evidenceSummary?.frictionCount
      || left?.evidenceSummary?.appRunCount
      || left?.evidenceSummary?.usageCount
      || 0,
    );
    const rightUsage = Number(
      right?.evidenceSummary?.frictionCount
      || right?.evidenceSummary?.appRunCount
      || right?.evidenceSummary?.usageCount
      || 0,
    );
    return rightUsage - leftUsage;
  })[0];
}

function selectCapabilityRecoveryUnchecked(snapshot) {
  const recoveries = asCapabilityList(snapshot?.capabilityTreasury?.recoveries)
    .filter(recovery =>
      recovery?.schema === "neyvia.capability_recovery_mission.v1"
      && recovery?.state === "review_required"
      && recovery?.humanApprovalRequired === true
      && recovery?.candidateActivated !== true
      && recovery?.published !== true
      && String(recovery?.prompt || "").trim(),
    );
  if (!recoveries.length) return null;
  return [...recoveries].sort((left, right) => {
    const priorityDifference =
      Number(left?.priority ?? 99) - Number(right?.priority ?? 99);
    if (priorityDifference) return priorityDifference;
    const evidenceDifference =
      Number(right?.evidenceCount || 0) - Number(left?.evidenceCount || 0);
    if (evidenceDifference) return evidenceDifference;
    return String(left?.title || "").localeCompare(String(right?.title || ""));
  })[0];
}

function buildCapabilityRecoveryPayloadUnchecked(recovery) {
  if (
    recovery?.schema !== "neyvia.capability_recovery_mission.v1"
    || recovery?.state !== "review_required"
    || recovery?.humanApprovalRequired !== true
    || recovery?.candidateActivated === true
    || recovery?.published === true
    || !String(recovery?.recoveryId || "").trim()
    || !String(recovery?.prompt || "").trim()
  ) {
    return null;
  }
  const route =
    recovery?.recommendedRoute && typeof recovery.recommendedRoute === "object"
      ? recovery.recommendedRoute
      : {};
  return {
    recoveryId: String(recovery.recoveryId),
    title: String(recovery.title || "Review prior work"),
    prompt: String(recovery.prompt),
    recommendedLaneId: String(recovery.recommendedLaneId || ""),
    route: {
      runtime: String(route.runtime || ""),
      provider: String(route.provider || ""),
      model: String(route.model || ""),
      effort: String(route.effort || ""),
      availability: String(
        route?.availability?.state || route.availability || "",
      ),
    },
  };
}

function buildCapabilityTrialPayloadUnchecked(
  recommendation,
  { conversationId = "", missionId = "" } = {},
) {
  if (!recommendation?.capabilityId) return null;
  return {
    lineageId: recommendation.lineageId || "",
    capabilityId: recommendation.capabilityId,
    capabilityKind: recommendation.capabilityKind || "skill",
    label: recommendation.label || recommendation.capabilityId,
    origin: recommendation.origin || "neyvia",
    action: recommendation.action || "prove",
    title: recommendation.title || `Prove ${recommendation.label || recommendation.capabilityId}`,
    reason: recommendation.reason || "",
    context: {
      conversationId,
      missionId,
      intent: "bounded_baseline_candidate_comparison",
      discoverySource: recommendation.origin || "neyvia",
      mutationBrief: recommendation.mutationBrief || "",
    },
    baseline: {
      source: "current_lineage",
      ...recommendation.evidenceSummary,
    },
    candidate: {
      status: "mutation_brief",
      intent: recommendation.mutationBrief || recommendation.title || "",
      activated: false,
    },
    successContract: recommendation.successContract || {},
    createdBy: "operator",
  };
}

function isCapabilityRunBundleUnchecked(value) {
  return Boolean(
    value
    && typeof value === "object"
    && !Array.isArray(value)
    && value.schema === "neyvia.capability-run-bundle/v2"
    && String(value.appFactoryJobId || "").trim()
    && String(value.appId || "").trim()
    && value.candidateActivated === false
    && value.transcriptsIncluded === false
    && Array.isArray(value.runs)
    && value.runs.length > 0
    && value.runs.length <= 100
    && value.runs.every(run =>
      run?.schema === "neyvia.capability-run/v2"
      && run?.status === "sealed"
      && /^[0-9a-f]{64}$/i.test(String(run?.receiptDigest || ""))
      && run?.candidateActivated === false
      && run?.transcriptsIncluded === false
    )
  );
}

function buildCapabilityRunImportPayloadUnchecked(
  bundle,
  { reviewConfirmed = false, importedBy = "operator" } = {},
) {
  if (!isCapabilityRunBundle(bundle) || reviewConfirmed !== true) return null;
  return {
    bundle,
    reviewConfirmed: true,
    importedBy: String(importedBy || "operator"),
  };
}

function skillCandidateRequiresSealUnchecked(trial) {
  return Boolean(
    trial?.capabilityKind === "skill" &&
      SKILL_CANDIDATE_ACTIONS.has(String(trial?.action || "")),
  );
}

function skillCandidateIsSealedUnchecked(trial) {
  const candidate = trial?.candidate;
  return Boolean(
    candidate?.schema === SEALED_SKILL_CANDIDATE_SCHEMA &&
      candidate?.state === "sealed" &&
      candidate?.packageDigest &&
      candidate?.skillMarkdown &&
      candidate?.openaiYaml &&
      candidate?.activated === false,
  );
}

function buildSkillCandidateMarkdownUnchecked(
  trial,
  { description = "", instructions = "" } = {},
) {
  const targetSkillId = String(trial?.candidate?.targetSkillId || "").trim();
  const normalizedDescription = String(description || "").replace(/\s+/g, " ").trim();
  const normalizedInstructions = String(instructions || "").trim();
  if (!targetSkillId || !normalizedDescription || !normalizedInstructions) return "";
  const displayName = String(
    trial?.candidate?.displayName || trial?.label || targetSkillId,
  ).trim();
  return [
    "---",
    `name: ${targetSkillId}`,
    `description: ${JSON.stringify(normalizedDescription)}`,
    "---",
    "",
    `# ${displayName}`,
    "",
    "## Goal",
    "",
    normalizedDescription,
    "",
    "## Workflow",
    "",
    normalizedInstructions,
    "",
  ].join("\n");
}

function buildSkillCandidateSealPayloadUnchecked(
  trial,
  {
    description = "",
    instructions = "",
    reviewConfirmed = false,
    sealedBy = "operator",
  } = {},
) {
  if (
    !trial?.trialId ||
    !skillCandidateRequiresSeal(trial) ||
    skillCandidateIsSealed(trial) ||
    reviewConfirmed !== true ||
    asCapabilityList(trial?.evidence).length > 0
  ) {
    return null;
  }
  const skillMarkdown = buildSkillCandidateMarkdown(trial, {
    description,
    instructions,
  });
  if (!skillMarkdown) return null;
  const targetSkillId = String(trial.candidate.targetSkillId);
  const normalizedDescription = String(description || "").replace(/\s+/g, " ").trim();
  const sentence = normalizedDescription
    ? normalizedDescription[0].toLowerCase() + normalizedDescription.slice(1)
    : "complete the reviewed workflow";
  return {
    trialId: trial.trialId,
    skillMarkdown,
    displayName: String(
      trial?.candidate?.displayName || trial?.label || targetSkillId,
    ).trim(),
    defaultPrompt: `Use $${targetSkillId} to ${sentence.replace(/\.$/, "")}.`,
    reviewConfirmed: true,
    sealedBy: String(sealedBy || "operator"),
  };
}

function skillCandidateCanCompareUnchecked(trial) {
  return !skillCandidateRequiresSeal(trial) || skillCandidateIsSealed(trial);
}

function synthesisCanEnterLearningUnchecked(graph) {
  const synthesis = graph?.synthesis;
  return Boolean(
    synthesis?.synthesisId &&
      synthesis?.status === "ready" &&
      synthesis?.evidence?._contract?.ready === true,
  );
}

export function capabilityMetric(value, fallback = "Not measured") {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return fallback;
  return `${Math.round(numeric * 100)}%`;
}

function eligibleReceiptCandidatesUnchecked(snapshot) {
  return asCapabilityList(snapshot?.receiptComparisons?.candidates).filter(
    item =>
      item?.eligible === true &&
      item?.schema === "neyvia.receipt_measurement.v1" &&
      item?.turnId,
  );
}

function proofLeaseReceiptCandidatesUnchecked(snapshot) {
  return eligibleReceiptCandidates(snapshot).filter(
    item =>
      item?.verificationStatus === "passed" &&
      item?.authorityRecorded === true,
  );
}

function receiptOptionLabelUnchecked(receipt) {
  if (!receipt?.turnId) return "Unknown receipt";
  const runtime = [receipt.runtime, receipt.model].filter(Boolean).join(" · ");
  const proofCount = Number(receipt.proofArtifactCount || 0);
  const proof = `${proofCount} proof artifact${proofCount === 1 ? "" : "s"}`;
  const status = String(receipt.verificationStatus || receipt.status || "recorded")
    .replaceAll("_", " ");
  return [runtime || "Recorded run", status, proof].join(" · ");
}

function buildReceiptComparisonPayloadUnchecked(
  trial,
  {
    conversationId = "",
    missionId = "",
    baselineTurnId = "",
    candidateTurnId = "",
    sameContractConfirmed = false,
    operatorValue = "",
    operatorNote = "",
  } = {},
) {
  if (
    !trial?.trialId ||
    !skillCandidateCanCompare(trial) ||
    !conversationId ||
    !baselineTurnId ||
    !candidateTurnId ||
    baselineTurnId === candidateTurnId ||
    sameContractConfirmed !== true ||
    !["candidate_better", "about_the_same", "baseline_better"].includes(
      operatorValue,
    )
  ) {
    return null;
  }
  return {
    trialId: trial.trialId,
    conversationId,
    missionId,
    baselineTurnId,
    candidateTurnId,
    sameContractConfirmed: true,
    operatorValue,
    operatorNote: String(operatorNote || "").trim(),
    recordedBy: "operator",
  };
}

function counterfactualReplayCandidatesUnchecked(trial) {
  const sealedDigest = skillCandidateIsSealed(trial)
    ? String(trial.candidate.packageDigest)
    : "";
  return asCapabilityList(trial?.evidence)
    .filter(item => {
      const pair = item?.receiptPair;
      return Boolean(
        item?.runId &&
          item?.transcriptsIncluded === false &&
          pair?.schema === "neyvia.receipt_comparison.v1" &&
          pair?.sameContractConfirmed === true &&
          pair?.transcriptsIncluded === false &&
          pair?.baseline?.authorityRecorded === true &&
          pair?.baseline?.authority?.recorded === true &&
          pair?.candidate?.authorityRecorded === true &&
          pair?.candidate?.authority?.recorded === true &&
          (
            !skillCandidateRequiresSeal(trial) ||
            (
              sealedDigest &&
              item?.candidatePackageDigest === sealedDigest &&
              pair?.candidatePackageDigest === sealedDigest
            )
          ),
      );
    })
    .slice(-COUNTERFACTUAL_CASE_LIMIT);
}

function counterfactualCaseLabelUnchecked(run) {
  const baseline = String(run?.receiptPair?.baseline?.turnId || "baseline");
  const candidate = String(run?.receiptPair?.candidate?.turnId || "candidate");
  const lift = Number(run?.deltas?.outcomeLift);
  const liftLabel = Number.isFinite(lift)
    ? `${Math.round(lift * 100)}% lift`
    : "lift unmeasured";
  return `${baseline} → ${candidate} · ${liftLabel}`;
}

function buildCounterfactualForgePayloadUnchecked(
  trial,
  {
    reviewConfirmed = false,
    reviewedBy = "operator",
    caseRunIds = null,
  } = {},
) {
  if (
    !trial?.trialId ||
    reviewConfirmed !== true ||
    !["branch", "repair", "merge", "promote_to_app"].includes(trial?.action)
  ) {
    return null;
  }
  const available = counterfactualReplayCandidates(trial);
  const selectedIds = Array.isArray(caseRunIds)
    ? caseRunIds.filter(Boolean)
    : available.map(item => item.runId);
  const uniqueIds = [...new Set(selectedIds)].slice(0, COUNTERFACTUAL_CASE_LIMIT);
  const required = Math.max(
    1,
    Number(trial?.successContract?.requiredComparableRuns || 1),
  );
  if (uniqueIds.length < required) return null;
  const availableIds = new Set(available.map(item => item.runId));
  if (uniqueIds.some(runId => !availableIds.has(runId))) return null;
  return {
    trialId: trial.trialId,
    caseRunIds: uniqueIds,
    reviewConfirmed: true,
    reviewedBy: String(reviewedBy || "operator"),
  };
}

function counterfactualForgeCanApproveUnchecked(trial) {
  const forge = trial?.verdict?.counterfactualForge;
  const candidateBindingReady = !skillCandidateRequiresSeal(trial) || (
    skillCandidateIsSealed(trial) &&
    forge?.candidatePackageDigest === trial?.candidate?.packageDigest
  );
  return Boolean(
    trial?.state === "evidence_ready" &&
      candidateBindingReady &&
      forge?.schema === COUNTERFACTUAL_FORGE_SCHEMA &&
      forge?.reviewConfirmed === true &&
      forge?.reviewGatePassed === true &&
      forge?.recommendedDecision === "accept" &&
      forge?.candidateActivated === false,
  );
}

function selectSkillMaterializationReviewUnchecked(snapshot) {
  const reviews = asCapabilityList(snapshot?.skillMaterializationReviews);
  if (!reviews.length) return null;
  return [...reviews].sort((left, right) => {
    const rank = state => {
      if (state === "review_required") return 0;
      if (state === "materialized_inactive") return 2;
      return 2;
    };
    const leaseRank = review => {
      const leaseState = String(review?.proofLease?.state || "");
      return {
        held: 0,
        reproof_required: 1,
        review_due: 2,
        retirement_review: 3,
        unestablished: 4,
        current: 5,
        withdrawn: 6,
      }[leaseState] ?? 7;
    };
    const stateDifference = rank(left?.state) - rank(right?.state);
    if (stateDifference) return stateDifference;
    return leaseRank(left) - leaseRank(right);
  })[0];
}

function buildSkillMaterializationPayloadUnchecked(
  review,
  { reviewConfirmed = false, materializedBy = "operator" } = {},
) {
  if (
    !review?.trialId ||
    !review?.candidateDigest ||
    review?.state !== "review_required" ||
    review?.canMaterialize !== true ||
    reviewConfirmed !== true
  ) {
    return null;
  }
  return {
    trialId: review.trialId,
    candidateDigest: review.candidateDigest,
    reviewConfirmed: true,
    materializedBy: String(materializedBy || "operator"),
  };
}

function buildSkillMaterializationRollbackPayloadUnchecked(
  review,
  {
    reviewConfirmed = false,
    rolledBackBy = "operator",
    reason = "",
  } = {},
) {
  const materialization = review?.materialization || review;
  if (
    !materialization?.materializationId ||
    !materialization?.candidateDigest ||
    materialization?.state !== "materialized_inactive" ||
    reviewConfirmed !== true
  ) {
    return null;
  }
  return {
    materializationId: materialization.materializationId,
    candidateDigest: materialization.candidateDigest,
    reviewConfirmed: true,
    rolledBackBy: String(rolledBackBy || "operator"),
    reason: String(reason || "").trim(),
  };
}

function proofLeaseDependencyPathsUnchecked(value) {
  const paths = String(value || "")
    .split(/\r?\n/)
    .map(item => item.trim().replaceAll("\\", "/"))
    .filter(Boolean);
  return [...new Set(paths)].slice(0, 12);
}

function buildProofLeaseEstablishPayloadUnchecked(
  review,
  {
    goalStatement = "",
    dependencyPaths = "",
    reviewAfterDays = 30,
    reviewConfirmed = false,
    issuedBy = "operator",
  } = {},
) {
  const materialization = review?.materialization || review;
  const lease = review?.proofLease || {};
  const goal = String(goalStatement || "").replace(/\s+/g, " ").trim();
  const days = Number(reviewAfterDays);
  if (
    !materialization?.materializationId ||
    materialization?.state !== "materialized_inactive" ||
    lease?.state !== "unestablished" ||
    lease?.canEstablish !== true ||
    goal.length < 12 ||
    !Number.isInteger(days) ||
    days < 1 ||
    days > 365 ||
    reviewConfirmed !== true
  ) {
    return null;
  }
  return {
    materializationId: materialization.materializationId,
    goalStatement: goal,
    dependencyPaths: proofLeaseDependencyPaths(dependencyPaths),
    reviewAfterDays: days,
    reviewConfirmed: true,
    issuedBy: String(issuedBy || "operator"),
  };
}

function buildProofLeaseRenewalPayloadUnchecked(
  review,
  {
    conversationId = "",
    turnId = "",
    goalStillMatches = false,
    operatorValue = "",
    reviewConfirmed = false,
    renewedBy = "operator",
  } = {},
) {
  const materialization = review?.materialization || review;
  const lease = review?.proofLease || {};
  if (
    !materialization?.materializationId ||
    !materialization?.candidateDigest ||
    materialization?.state !== "materialized_inactive" ||
    lease?.canRenew !== true ||
    !conversationId ||
    !turnId ||
    goalStillMatches !== true ||
    operatorValue !== "still_useful" ||
    reviewConfirmed !== true
  ) {
    return null;
  }
  return {
    materializationId: materialization.materializationId,
    candidateDigest: materialization.candidateDigest,
    conversationId,
    turnId,
    goalStillMatches: true,
    operatorValue: "still_useful",
    reviewConfirmed: true,
    renewedBy: String(renewedBy || "operator"),
  };
}

function buildProofLeaseDispositionPayloadUnchecked(
  review,
  {
    disposition = "",
    note = "",
    reviewConfirmed = false,
    recordedBy = "operator",
  } = {},
) {
  const materialization = review?.materialization || review;
  const leaseState = String(review?.proofLease?.state || "");
  if (
    !materialization?.materializationId ||
    !leaseState ||
    ["unestablished", "withdrawn"].includes(leaseState) ||
    !["needs_repair", "no_longer_needed"].includes(disposition) ||
    reviewConfirmed !== true
  ) {
    return null;
  }
  return {
    materializationId: materialization.materializationId,
    disposition,
    note: String(note || "").trim(),
    reviewConfirmed: true,
    recordedBy: String(recordedBy || "operator"),
  };
}

function buildCapabilityAppPromptUnchecked(recommendation, trial = null) {
  if (!recommendation?.capabilityId) return "";
  const evidenceCount = Number(
    trial?.verdict?.comparableRunCount ||
      recommendation?.evidenceSummary?.feedbackCount ||
      0,
  );
  return [
    `Build an optional Neyvia ecosystem app from the approved capability lineage “${recommendation.label || recommendation.capabilityId}”.`,
    `Preserve capability ID ${recommendation.capabilityId} and the human-reviewed evolution lineage.`,
    evidenceCount
      ? `Use ${evidenceCount} comparable evidence run${evidenceCount === 1 ? "" : "s"} as the product baseline.`
      : "Do not claim the flow is proven until its comparison evidence is attached.",
    "Keep installation review-gated, expose rollback, and return App Factory proof.",
  ].join(" ");
}

export function capabilityActionLabel(...args) { return checkCapabilityAction("capabilityActionLabel", args, capabilityActionLabelUnchecked(...args)); }

export function selectCapabilityRecommendation(...args) { return checkCapabilityAction("selectCapabilityRecommendation", args, selectCapabilityRecommendationUnchecked(...args)); }

export function selectCapabilityRecovery(...args) { return checkCapabilityAction("selectCapabilityRecovery", args, selectCapabilityRecoveryUnchecked(...args)); }

export function buildCapabilityRecoveryPayload(...args) { return checkCapabilityAction("buildCapabilityRecoveryPayload", args, buildCapabilityRecoveryPayloadUnchecked(...args)); }

export function buildCapabilityTrialPayload(...args) { return checkCapabilityAction("buildCapabilityTrialPayload", args, buildCapabilityTrialPayloadUnchecked(...args)); }

export function isCapabilityRunBundle(...args) { return checkCapabilityAction("isCapabilityRunBundle", args, isCapabilityRunBundleUnchecked(...args)); }

export function buildCapabilityRunImportPayload(...args) { return checkCapabilityAction("buildCapabilityRunImportPayload", args, buildCapabilityRunImportPayloadUnchecked(...args)); }

export function skillCandidateRequiresSeal(...args) { return checkCapabilityAction("skillCandidateRequiresSeal", args, skillCandidateRequiresSealUnchecked(...args)); }

export function skillCandidateIsSealed(...args) { return checkCapabilityAction("skillCandidateIsSealed", args, skillCandidateIsSealedUnchecked(...args)); }

export function skillCandidateCanCompare(...args) { return checkCapabilityAction("skillCandidateCanCompare", args, skillCandidateCanCompareUnchecked(...args)); }

export function buildSkillCandidateMarkdown(...args) { return checkCapabilityAction("buildSkillCandidateMarkdown", args, buildSkillCandidateMarkdownUnchecked(...args)); }

export function buildSkillCandidateSealPayload(...args) { return checkCapabilityAction("buildSkillCandidateSealPayload", args, buildSkillCandidateSealPayloadUnchecked(...args)); }

export function synthesisCanEnterLearning(...args) { return checkCapabilityAction("synthesisCanEnterLearning", args, synthesisCanEnterLearningUnchecked(...args)); }

export function eligibleReceiptCandidates(...args) { return checkCapabilityAction("eligibleReceiptCandidates", args, eligibleReceiptCandidatesUnchecked(...args)); }

export function proofLeaseReceiptCandidates(...args) { return checkCapabilityAction("proofLeaseReceiptCandidates", args, proofLeaseReceiptCandidatesUnchecked(...args)); }

export function receiptOptionLabel(...args) { return checkCapabilityAction("receiptOptionLabel", args, receiptOptionLabelUnchecked(...args)); }

export function buildReceiptComparisonPayload(...args) { return checkCapabilityAction("buildReceiptComparisonPayload", args, buildReceiptComparisonPayloadUnchecked(...args)); }

export function counterfactualReplayCandidates(...args) { return checkCapabilityAction("counterfactualReplayCandidates", args, counterfactualReplayCandidatesUnchecked(...args)); }

export function counterfactualCaseLabel(...args) { return checkCapabilityAction("counterfactualCaseLabel", args, counterfactualCaseLabelUnchecked(...args)); }

export function buildCounterfactualForgePayload(...args) { return checkCapabilityAction("buildCounterfactualForgePayload", args, buildCounterfactualForgePayloadUnchecked(...args)); }

export function counterfactualForgeCanApprove(...args) { return checkCapabilityAction("counterfactualForgeCanApprove", args, counterfactualForgeCanApproveUnchecked(...args)); }

export function selectSkillMaterializationReview(...args) { return checkCapabilityAction("selectSkillMaterializationReview", args, selectSkillMaterializationReviewUnchecked(...args)); }

export function buildSkillMaterializationPayload(...args) { return checkCapabilityAction("buildSkillMaterializationPayload", args, buildSkillMaterializationPayloadUnchecked(...args)); }

export function buildSkillMaterializationRollbackPayload(...args) { return checkCapabilityAction("buildSkillMaterializationRollbackPayload", args, buildSkillMaterializationRollbackPayloadUnchecked(...args)); }

export function proofLeaseDependencyPaths(...args) { return checkCapabilityAction("proofLeaseDependencyPaths", args, proofLeaseDependencyPathsUnchecked(...args)); }

export function buildProofLeaseEstablishPayload(...args) { return checkCapabilityAction("buildProofLeaseEstablishPayload", args, buildProofLeaseEstablishPayloadUnchecked(...args)); }

export function buildProofLeaseRenewalPayload(...args) { return checkCapabilityAction("buildProofLeaseRenewalPayload", args, buildProofLeaseRenewalPayloadUnchecked(...args)); }

export function buildProofLeaseDispositionPayload(...args) { return checkCapabilityAction("buildProofLeaseDispositionPayload", args, buildProofLeaseDispositionPayloadUnchecked(...args)); }

export function buildCapabilityAppPrompt(...args) { return checkCapabilityAction("buildCapabilityAppPrompt", args, buildCapabilityAppPromptUnchecked(...args)); }

export function capabilityCommands() { return checkCapabilityAction("capabilityCommands", [], CAPABILITY_EVOLUTION_COMMANDS); }
capabilityCommands();
