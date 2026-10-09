import { checkedLiveReviewProjection } from "./missionReviewContracts.js";
import {
  describeApprovalBehavior,
  describeExplanationBehavior,
  describeMissionAssumption,
  describeMissionKnownState,
  describeMissionNeedsInput,
  describeNextOperatorAction,
  describeProfileFit,
  previewLabel,
  describeVisibilityBehavior,
  formatDurationCompact,
  missionStatusTone,
  resolveCurrentRuntimeLane,
  resolveMissionPauseReason,
  runtimeLabel,
  titleizeToken,
  visibilityProfileState,
} from "./missionHelpers.js";

function asList(value) {
  return Array.isArray(value) ? value : [];
}

function uniq(items) {
  return [...new Set(asList(items).filter(Boolean).map(item => String(item).trim()))];
}

function asInt(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.round(parsed) : fallback;
}

function asBooleanFlag(value) {
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (["false", "0", "no", "off", "inactive", "stopped"].includes(normalized)) {
      return false;
    }
    return Boolean(normalized);
  }
  return Boolean(value);
}

function clampPercent(value) {
  return Math.max(0, Math.min(100, asInt(value)));
}

function listLabel(value) {
  if (!value) {
    return "Item";
  }
  return String(value);
}

function ratioPercent(part, total) {
  if (total <= 0) {
    return 0;
  }
  return clampPercent(Math.round((part / total) * 100));
}

function scoreTone(score) {
  if (score >= 85) {
    return "good";
  }
  if (score >= 65) {
    return "warn";
  }
  return "bad";
}

function serviceStatusTone(status) {
  if (["healthy", "connected", "ready", "passed"].includes(status)) {
    return "good";
  }
  if (
    [
      "missing",
      "blocked",
      "failed",
      "error",
      "degraded",
      "unavailable",
      "stale",
    ].includes(status)
  ) {
    return "bad";
  }
  return "warn";
}

function topBarLiveStatus(mission, pendingQuestions, pendingApprovals) {
  const approvalCount =
    asList(pendingApprovals).length + asList(mission?.proof?.pending_approvals).length;
  if (!mission) {
    return { label: "No active mission", tone: "neutral" };
  }
  if (approvalCount > 0) {
    return { label: "Needs approval", tone: "warn" };
  }
  if (asList(pendingQuestions).length > 0) {
    return { label: "Needs operator input", tone: "warn" };
  }
  if (asList(mission?.state?.verification_failures).length > 0) {
    return { label: "Verification failed", tone: "bad" };
  }
  if (mission?.state?.status === "completed") {
    return { label: "Completed", tone: "good" };
  }
  if (mission?.state?.status === "running") {
    return { label: "Active run", tone: "good" };
  }
  return {
    label: titleizeToken(mission?.state?.status || mission?.missionLoop?.continuityState || "active"),
    tone: missionStatusTone(mission?.state?.status),
  };
}

function deriveCurrentTask(mission) {
  const latestRevision = asList(mission?.plan_revisions).slice(-1)[0];
  const revisionStep = asList(latestRevision?.steps).find(step => step?.status === "in_progress");
  if (revisionStep?.title) {
    return revisionStep.title;
  }
  if (asList(mission?.state?.remaining_steps).length > 0) {
    return mission.state.remaining_steps[0];
  }
  if (asList(mission?.delegated_runtime_sessions).length > 0) {
    const delegated = mission.delegated_runtime_sessions[0];
    return delegated?.detail || delegated?.last_event || "Delegated runtime lane active";
  }
  return mission?.proof?.summary || "Waiting for the next mission checkpoint.";
}

function deriveNextCheckpoint(mission) {
  const latestRevision = asList(mission?.plan_revisions).slice(-1)[0];
  const nextRevisionStep = asList(latestRevision?.steps).find(step => step?.status === "pending");
  if (nextRevisionStep?.title) {
    return nextRevisionStep.title;
  }
  const remaining = asList(mission?.state?.remaining_steps);
  if (remaining.length > 1) {
    return remaining[1];
  }
  if (mission?.state?.status === "completed") {
    return "Finalize review and close mission";
  }
  return "Awaiting next checkpoint";
}

function deriveChanged(mission, workspace) {
  if (asList(mission?.changed_files).length > 0) {
    return mission.changed_files;
  }
  const actionTitles = asList(mission?.action_history)
    .map(action => action?.proposal?.title)
    .filter(Boolean);
  if (actionTitles.length > 0) {
    return actionTitles.slice(0, 5);
  }
  const git = workspace?.gitSnapshot || {};
  if (git.repoDetected) {
    return [
      `${git.stagedCount || 0} staged`,
      `${git.unstagedCount || 0} unstaged`,
      `${git.untrackedCount || 0} untracked`,
    ];
  }
  return ["No changed files captured yet."];
}

function deriveChecks(mission) {
  const checks = [
    ...asList(mission?.proof?.passed_checks).map(item => `Passed: ${item}`),
    ...asList(mission?.proof?.failed_checks).map(item => `Failed: ${item}`),
    ...asList(mission?.state?.verification_failures).map(item => `Failure: ${item}`),
  ];
  const actionResults = asList(mission?.action_history).map(
    action => action?.result?.result_summary || action?.result?.error || action?.result?.stdout,
  );
  return uniq([...checks, ...actionResults]).slice(0, 8);
}

function deriveArtifacts(mission, inbox) {
  const explicit = asList(mission?.proof_artifacts);
  if (explicit.length > 0) {
    return explicit.slice(0, 8);
  }
  return uniq([
    mission?.proof?.summary,
    mission?.missionLoop?.continuityDetail,
    inbox?.previewMessage,
    asList(mission?.delegated_runtime_sessions)[0]?.detail,
  ]).slice(0, 6);
}

function deriveVerificationSummary(mission) {
  return (
    mission?.missionLoop?.lastVerificationSummary ||
    mission?.state?.last_verification_summary ||
    mission?.proof?.summary ||
    "Verification detail has not been recorded yet."
  );
}

function deriveDiffSummary(workspace) {
  const git = workspace?.gitSnapshot || {};
  if (!git.repoDetected) {
    return "No Git diff detected for this workspace.";
  }
  return `${git.branch || "unknown"} · ${git.stagedCount || 0} staged · ${git.unstagedCount || 0} unstaged · ${git.untrackedCount || 0} untracked`;
}

function deriveQueueItems(mission, pendingQuestions, pendingApprovals) {
  const items = [];

  for (const approval of [
    ...asList(mission?.proof?.pending_approvals),
    ...asList(pendingApprovals).map(item => item?.reason || item?.toolId || item?.approval_id),
  ]) {
    if (!approval) {
      continue;
    }
    items.push({
      tone: "warn",
      type: "Approval",
      title: approval,
      reason: "Mission is paused at a review boundary.",
    });
  }

  for (const question of asList(pendingQuestions)) {
    items.push({
      tone: "warn",
      type: "Question",
      title: question?.question || "Operator input required",
      reason: question?.summary || "Neyvia needs a scope answer before it can continue safely.",
    });
  }

  for (const failure of asList(mission?.state?.verification_failures)) {
    items.push({
      tone: "bad",
      type: "Verification",
      title: failure,
      reason: "Review the failing check before approving additional execution.",
    });
  }

  if (items.length === 0) {
    items.push({
      tone: "good",
      type: "Recommended",
      title: describeNextOperatorAction(mission, pendingQuestions),
      reason:
        mission?.proof?.summary ||
        mission?.missionLoop?.continuityDetail ||
        "Run can continue inside the current guardrails.",
    });
  }

  return items.slice(0, 8);
}

function derivePrimaryAction(mission, queueItems) {
  const firstQueue = queueItems[0];
  if (!mission) {
    return {
      kind: "start",
      label: "Launch mission",
      reason: "Start one bounded mission to unlock proof, approvals, and a readable thread.",
    };
  }

  if (firstQueue?.tone === "warn" || firstQueue?.tone === "bad") {
    return {
      kind: "queue",
      label: "Review queue",
      reason: firstQueue?.title || "A boundary needs judgment before Neyvia can continue.",
    };
  }

  if (
    mission?.missionLoop?.continuityState === "resume_available" ||
    mission?.state?.status === "queued"
  ) {
    return {
      kind: "resume",
      label: "Resume mission",
      reason:
        mission?.missionLoop?.continuityDetail ||
        mission?.state?.continuity_detail ||
        "Resume from the last safe checkpoint.",
    };
  }

  if (mission?.state?.status === "completed") {
    return {
      kind: "proof",
      label: "Review proof",
      reason: deriveVerificationSummary(mission),
    };
  }

  return {
    kind: "proof",
    label: "Open proof",
    reason: deriveVerificationSummary(mission),
  };
}

function deriveThreadSections({ mission, pendingQuestions, workspace }) {
  if (!mission) {
    return [];
  }

  const currentTask = deriveCurrentTask(mission);
  const nextCheckpoint = deriveNextCheckpoint(mission);
  const pauseReason = resolveMissionPauseReason(mission);
  const knownState = describeMissionKnownState(mission);
  const assumptions = describeMissionAssumption(mission, pendingQuestions);
  const needsInput = describeMissionNeedsInput(mission, pendingQuestions);
  const changed = deriveChanged(mission, workspace).join(" · ");
  const verification = deriveVerificationSummary(mission);

  return [
    {
      id: "current-task",
      label: "Current task",
      body: currentTask,
      detail: `Next checkpoint: ${nextCheckpoint}`,
      tone: missionStatusTone(mission?.state?.status),
    },
    {
      id: "known-state",
      label: "What Neyvia knows",
      body: knownState,
      detail: resolveCurrentRuntimeLane(mission),
      tone: "neutral",
    },
    {
      id: "assumptions",
      label: "What Neyvia assumes",
      body: assumptions,
      detail: pauseReason ? `Pause boundary: ${pauseReason}` : "",
      tone: "neutral",
    },
    {
      id: "needs-input",
      label: "What Neyvia needs from operator",
      body: needsInput,
      detail: describeNextOperatorAction(mission, pendingQuestions),
      tone: "warn",
    },
    {
      id: "changed",
      label: "What changed",
      body: changed,
      detail: deriveDiffSummary(workspace),
      tone: "neutral",
    },
    {
      id: "proof",
      label: "What proof exists",
      body: verification,
      detail: mission?.proof?.summary || "Proof keeps accumulating while the mission runs.",
      tone: asList(mission?.state?.verification_failures).length > 0 ? "bad" : "good",
    },
  ];
}

function timelineEntry(kind, title, detail, tone = "neutral", meta = "") {
  return { kind, title, detail, tone, meta };
}

function deriveEvents(mission, snapshot) {
  const events = [];

  for (const session of asList(mission?.delegated_runtime_sessions)) {
    for (const event of asList(session?.latest_events)) {
      const kind = String(event?.kind || "runtime").toLowerCase();
      const eventDetail =
        kind === "runtime.phase_entered"
          ? `${titleizeToken(event?.data?.phase || "execute")} phase via ${titleizeToken(
              event?.data?.role || "route",
            )}${event?.data?.provider ? ` · ${titleizeToken(event.data.provider)}` : ""}${event?.data?.model ? ` · ${event.data.model}` : ""}`
          : kind === "runtime.route_switch_reason"
            ? event?.data?.reason || event?.message || session?.detail || ""
            : kind === "runtime.handoff"
              ? event?.data?.reason || event?.message || session?.detail || ""
              : session?.detail || session?.last_event || "";
      events.push(
        timelineEntry(
          event?.kind || "runtime",
          event?.message || "Runtime update",
          eventDetail,
          missionStatusTone(session?.status),
          runtimeLabel(session?.runtime_id),
        ),
      );
    }
  }

  for (const action of asList(mission?.action_history)) {
    events.push(
      timelineEntry(
        action?.proposal?.kind || "action",
        action?.proposal?.title || action?.action_id || "Action",
        action?.result?.result_summary || action?.result?.error || action?.result?.stdout || "",
        action?.result?.error ? "bad" : action?.gate?.status === "pending" ? "warn" : "neutral",
        action?.executed_at || "",
      ),
    );
  }

  for (const activity of asList(snapshot?.activity)) {
    events.push(
      timelineEntry(
        activity?.kind || "activity",
        activity?.message || "Activity update",
        "",
        activity?.kind === "approval.request" ? "warn" : "neutral",
        activity?.timestamp || "",
      ),
    );
  }

  if (events.length === 0) {
    events.push(
      timelineEntry(
        "timeline",
        "Mission thread is waiting for the next event",
        "New actions, delegated lane events, and approvals will appear here.",
      ),
    );
  }

  return events.slice(0, 24);
}

function deriveConfidenceSurface({
  mission,
  snapshot,
  setupHealth,
  queueItems,
  pendingQuestions,
  pendingApprovals,
}) {
  const release = snapshot?.releaseReadiness || {};
  const requiredGateSummary = release?.requiredGateSummary || {};
  const requiredPassed = asInt(requiredGateSummary?.passed);
  const requiredTotal = asInt(requiredGateSummary?.total);
  const requiredScore = clampPercent(
    requiredGateSummary?.score ?? ratioPercent(requiredPassed, requiredTotal),
  );
  const qualityScore = clampPercent(release?.qualityScore ?? 0);
  const releaseScore = clampPercent(release?.score ?? 0);
  const verificationFailures = asList(mission?.state?.verification_failures).length;
  const questionCount = asList(pendingQuestions).length;
  const approvalCount =
    asList(mission?.proof?.pending_approvals).length + asList(pendingApprovals).length;
  const missingDependencyCount = asList(setupHealth?.missingDependencies).length;
  const urgentQueueCount = queueItems.filter(
    item => item?.tone === "warn" || item?.tone === "bad",
  ).length;
  const frictionPenalty = Math.min(
    36,
    urgentQueueCount * 4 +
      questionCount * 4 +
      approvalCount * 3 +
      verificationFailures * 6 +
      missingDependencyCount * 5,
  );

  const fallbackBase = requiredTotal > 0 ? requiredScore : qualityScore;
  const blendedBase = releaseScore > 0 ? releaseScore : fallbackBase;
  const confidenceScore = clampPercent(
    Math.round(blendedBase * 0.78 + requiredScore * 0.14 + qualityScore * 0.08) -
      frictionPenalty +
      (mission ? 4 : -4),
  );

  const setupSummary =
    setupHealth?.serviceManagementSummary || {
      totalItems: asList(setupHealth?.serviceManagement).length,
      healthyCount: asList(setupHealth?.serviceManagement).filter(
        item => serviceStatusTone(item?.currentHealthStatus) === "good",
      ).length,
    };
  const environmentPercent =
    asInt(setupSummary?.totalItems) > 0
      ? ratioPercent(asInt(setupSummary?.healthyCount), asInt(setupSummary?.totalItems))
      : setupHealth?.environmentReady
        ? 100
        : 40;

  const proofChecks = asList(release?.proofReadiness?.proofs);
  const proofPassed = proofChecks.filter(item => item?.passed).length;
  const proofPercent =
    proofChecks.length > 0
      ? ratioPercent(proofPassed, proofChecks.length)
      : mission
        ? 60
        : 0;

  const continuityPercent = !mission
    ? 0
    : mission?.state?.status === "completed"
      ? 100
      : mission?.state?.status === "running"
        ? 84
        : mission?.missionLoop?.continuityState === "resume_available"
          ? 78
          : mission?.state?.status === "queued"
            ? 62
            : 70;

  const operatorPercent = clampPercent(
    100 - Math.min(75, questionCount * 12 + approvalCount * 10 + verificationFailures * 15),
  );

  const phase =
    confidenceScore >= 85 && requiredPassed === requiredTotal && requiredTotal > 0
      ? "Validation ready"
      : confidenceScore >= 70
        ? "Close to validation"
        : "Hardening required";

  const nextActions = uniq([
    ...asList(release?.nextActions),
    ...queueItems
      .filter(item => item?.tone === "warn" || item?.tone === "bad")
      .map(item => item?.title || item?.reason),
    ...asList(setupHealth?.blockerExplanations),
  ]).slice(0, 6);

  const gates = asList(release?.gates).slice(0, 10).map(gate => ({
    gateId: gate?.gateId || gate?.label || "",
    label: gate?.label || "Gate",
    required: Boolean(gate?.required),
    passed: Boolean(gate?.passed),
    details: gate?.details || "",
    tone: gate?.passed ? "good" : gate?.required ? "bad" : "warn",
  }));

  return {
    score: confidenceScore,
    tone: scoreTone(confidenceScore),
    label: `${confidenceScore}% release confidence`,
    phase,
    releaseStatus: titleizeToken(release?.status || "building"),
    releaseScore,
    qualityScore,
    qualitySignals: {
      completionRate: asInt(release?.qualitySignals?.completionRate),
      delegatedRunRate: asInt(release?.qualitySignals?.delegatedRunRate),
      resumeRunRate: asInt(release?.qualitySignals?.resumeRunRate),
      resumeCompletionRate: asInt(release?.qualitySignals?.resumeCompletionRate),
      verificationPauseRate: asInt(release?.qualitySignals?.verificationPauseRate),
    },
    proofReady: Boolean(release?.proofReadiness?.ready),
    requiredGateSummary: {
      passed: requiredPassed,
      total: requiredTotal,
      score: requiredScore,
      label:
        requiredTotal > 0
          ? `${requiredPassed}/${requiredTotal} required gates passed`
          : "Required gates not reported yet",
    },
    calculatedAt: release?.calculatedAt || "",
    milestones: [
      {
        id: "environment",
        label: "Environment and services",
        percent: environmentPercent,
        detail:
          asInt(setupSummary?.totalItems) > 0
            ? `${asInt(setupSummary?.healthyCount)}/${asInt(setupSummary?.totalItems)} services healthy`
            : "Service health snapshot unavailable",
      },
      {
        id: "continuity",
        label: "Mission continuity",
        percent: continuityPercent,
        detail: mission
          ? titleizeToken(
              mission?.missionLoop?.continuityState || mission?.state?.status || "active",
            )
          : "No active mission yet",
      },
      {
        id: "proof",
        label: "Proof and verification",
        percent: proofPercent,
        detail:
          proofChecks.length > 0
            ? `${proofPassed}/${proofChecks.length} proving checks passed`
            : "Proof checks appear after first proving cycle",
      },
      {
        id: "operator",
        label: "Operator confidence",
        percent: operatorPercent,
        detail:
          questionCount + approvalCount + verificationFailures > 0
            ? `${questionCount} questions · ${approvalCount} approvals · ${verificationFailures} failures`
            : "No active friction in queue",
      },
    ],
    gates,
    nextActions,
  };
}

function deriveProfileStudio(snapshot, workspace, profileId, profileParams) {
  const profiles = snapshot?.profiles || {};
  const availableProfiles = asList(profiles?.availableProfiles);
  const details = profiles?.details || {};
  const activeDetail = details?.[profileId] || {};
  const activeAgent = activeDetail?.agent || {};
  const visibilityState = visibilityProfileState(profileParams);
  const profileRows = availableProfiles.slice(0, 10).map(name => {
    const item = details?.[name] || {};
    const params = item?.parameters || {};
    return {
      id: name,
      label: titleizeToken(name),
      description: item?.description || describeProfileFit(name),
      approval: titleizeToken(params?.approvalStrictness || "tiered"),
      autonomy: titleizeToken(params?.autonomyLevel || "balanced"),
      visibility: titleizeToken(params?.visibilityLevel || "balanced"),
      density: titleizeToken(params?.uiDensity || "comfortable"),
      tone: name === profileId ? "good" : "neutral",
    };
  });

  return {
    activeProfileId: profileId,
    activeProfileLabel: titleizeToken(profileId),
    availableProfiles,
    activeDescription: activeDetail?.description || describeProfileFit(profileId),
    behavior: [
      {
        label: "Approval boundary",
        value: describeApprovalBehavior(profileParams?.approvalStrictness || "tiered"),
      },
      {
        label: "Explanation style",
        value: describeExplanationBehavior(
          profileParams?.explanationLevel || activeAgent?.explanation_depth || "medium",
        ),
      },
      {
        label: "Visibility policy",
        value: describeVisibilityBehavior(profileParams?.visibilityLevel || "balanced"),
      },
      {
        label: "Profile fit",
        value: describeProfileFit(profileId),
      },
    ],
    visibilityState: {
      level: visibilityState?.level || "balanced",
      guided: Boolean(visibilityState?.guided),
      detailed: Boolean(visibilityState?.detailed),
      expert: Boolean(visibilityState?.expert),
    },
    workspacePolicy: [
      {
        label: "Current workspace profile",
        value: titleizeToken(workspace?.user_profile || profileId),
      },
      {
        label: "Preferred harness",
        value: titleizeToken(workspace?.preferred_harness || "fluxio_hybrid"),
      },
      {
        label: "Routing strategy",
        value: titleizeToken(workspace?.routing_strategy || "profile_default"),
      },
      {
        label: "Auto-optimize routing",
        value: workspace?.auto_optimize_routing ? "Enabled" : "Disabled",
      },
      {
        label: "Commit style",
        value: titleizeToken(workspace?.commit_message_style || "scoped"),
      },
      {
        label: "Execution target",
        value: titleizeToken(workspace?.execution_target_preference || "profile_default"),
      },
    ],
    profileRows,
  };
}

function deriveServiceStudio(workspace, setupHealth) {
  const workspaceServices = asList(workspace?.serviceManagement);
  const setupServices = asList(setupHealth?.serviceManagement);
  const services = workspaceServices.length > 0 ? workspaceServices : setupServices;
  const summary = workspace?.serviceManagementSummary || setupHealth?.serviceManagementSummary || {};

  const normalized = services
    .map(item => {
      const status =
        item?.currentHealthStatus || item?.lastVerificationResult || item?.status || "unknown";
      const tone = serviceStatusTone(status);
      const actions = [
        ...asList(item?.serviceActions),
        ...(item?.verifyAction?.actionId ? [item.verifyAction] : []),
      ]
        .filter(action => action?.actionId)
        .map(action => {
          const surface = action?.surface
            ? action.surface
            : action?.commandSurface?.startsWith("git.")
              ? "git"
            : action?.commandSurface?.startsWith("validate.")
              ? "validate"
              : action?.commandSurface?.startsWith("bridge.")
                ? "bridge"
                : "setup";
          return {
            actionId: action.actionId,
            label: action.label || action.actionId,
            commandSurface: action.commandSurface || "",
            detail: action.description || action.detail || action.followUp || "",
            requiresApproval: Boolean(action.requiresApproval),
            surface,
          };
        });

      return {
        serviceId: item?.serviceId || item?.label || "service",
        label: item?.label || item?.serviceId || "Service",
        category: titleizeToken(item?.serviceCategory || "service"),
        status: titleizeToken(status),
        tone,
        managementMode: titleizeToken(item?.managementMode || "externally_managed"),
        required: Boolean(item?.required),
        details: [
          item?.details || "",
          item?.updateAvailable && item?.latestVersion
            ? `Latest ${item.latestVersion}`
            : "",
        ]
          .filter(Boolean)
          .join(" · "),
        version: item?.version || "",
        latestVersion: item?.latestVersion || "",
        updateAvailable: Boolean(item?.updateAvailable),
        actions,
      };
    })
    .sort((left, right) => {
      const rank = { bad: 0, warn: 1, good: 2, neutral: 3 };
      const leftRank = rank[left.tone] ?? 3;
      const rightRank = rank[right.tone] ?? 3;
      if (leftRank !== rightRank) {
        return leftRank - rightRank;
      }
      return left.label.localeCompare(right.label);
    });

  return {
    summary: {
      totalItems: asInt(summary?.totalItems, normalized.length),
      healthyCount: asInt(
        summary?.healthyCount,
        normalized.filter(item => item.tone === "good").length,
      ),
      needsAttentionCount: asInt(
        summary?.needsAttentionCount,
        normalized.filter(item => item.tone !== "good").length,
      ),
      runtimeCount: asInt(summary?.runtimeCount),
      toolServerCount: asInt(summary?.toolServerCount),
      bridgeCount: asInt(summary?.bridgeCount),
    },
    services: normalized.slice(0, 20),
    urgent: normalized.filter(item => item.tone === "bad" || item.tone === "warn").slice(0, 6),
    availableActionCount: normalized.reduce((total, item) => total + item.actions.length, 0),
  };
}

function skillPackTone(item) {
  if (item?.installed && item?.testStatus === "reviewed") {
    return "good";
  }
  if (item?.installed) {
    return "warn";
  }
  return item?.recommended ? "neutral" : "warn";
}

function deriveSkillStudio(snapshot, workspace) {
  const skillLibrary = snapshot?.skillLibrary || {};
  const summary = skillLibrary?.managementSummary || {};
  const curatedPacks = asList(skillLibrary?.curatedPacks);
  const recommendedPacks = asList(skillLibrary?.recommendedPacks);
  const workspaceRecommendations = asList(workspace?.recommendedSkillPacks);
  const recommended = (
    workspaceRecommendations.length > 0 ? workspaceRecommendations : recommendedPacks
  )
    .slice(0, 8)
    .map(item => ({
      id: item?.packId || item?.pack_id || item?.label,
      label: item?.label || item?.packId || "Pack",
      description: item?.description || "",
      audience: titleizeToken(item?.audience || "all"),
      status: titleizeToken(item?.testStatus || item?.promotionState || "recommended"),
      tone: skillPackTone(item),
      installed: Boolean(item?.installed),
      executionCapable: Boolean(item?.execution_capable),
      guidanceOnly: Boolean(item?.guidance_only),
      permissions: asList(item?.permissions),
      profileSuitability: asList(item?.profile_suitability).map(entry => titleizeToken(entry)),
      originType: titleizeToken(item?.originType || item?.source?.kind || "recommended"),
      testStatus: titleizeToken(item?.testStatus || "recommended"),
    }));

  const curated = curatedPacks.slice(0, 10).map(item => ({
    id: item?.packId || item?.pack_id || item?.label,
    label: item?.label || item?.packId || "Pack",
    status: titleizeToken(item?.testStatus || item?.promotionState || "active"),
    usageCount: asInt(item?.usageCount),
    helpedCount: asInt(item?.helpedCount),
    tone: skillPackTone(item),
    installed: Boolean(item?.installed),
    executionCapable: Boolean(item?.execution_capable),
    guidanceOnly: Boolean(item?.guidance_only),
    permissions: asList(item?.permissions),
    profileSuitability: asList(item?.profile_suitability).map(entry => titleizeToken(entry)),
    originType: titleizeToken(item?.originType || item?.source?.kind || "curated"),
    testStatus: titleizeToken(item?.testStatus || "active"),
  }));

  const allPacks = uniq([...recommended.map(item => item.id), ...curated.map(item => item.id)]);
  const needsAttention = curated.filter(
    item =>
      item.status !== "Reviewed" ||
      !item.installed ||
      item.testStatus !== "Reviewed",
  );
  const executionReadyCount = curated.filter(
    item => item.installed && item.executionCapable && item.testStatus === "Reviewed",
  ).length;
  const coverageByProfile = {
    Beginner: curated.filter(item => item.profileSuitability.includes("Beginner")).length,
    Builder: curated.filter(item => item.profileSuitability.includes("Builder")).length,
    Advanced: curated.filter(item => item.profileSuitability.includes("Advanced")).length,
  };
  const nextQualityActions = uniq([
    asInt(summary?.needsTestCount) > 0
      ? `Review and test ${asInt(summary?.needsTestCount)} skill pack(s) with missing verification status.`
      : "",
    recommended.some(item => !item.installed)
      ? "Install or promote recommended packs before claiming full workflow coverage."
      : "",
    executionReadyCount < Math.max(1, Math.ceil(curated.length * 0.6))
      ? "Increase execution-capable reviewed packs to support broader operator workflows."
      : "",
    asInt(summary?.learnedCount) === 0
      ? "Capture at least one learned skill event from a real mission cycle."
      : "",
  ]).slice(0, 4);

  return {
    summary: {
      totalSkills: asInt(summary?.totalSkills, curatedPacks.length),
      reviewedReusableCount: asInt(summary?.reviewedReusableCount),
      needsTestCount: asInt(summary?.needsTestCount),
      learnedCount: asInt(summary?.learnedCount),
      disabledCount: asInt(summary?.disabledCount),
      installedCount: curatedPacks.filter(item => item?.installed).length,
      executionReadyCount,
      uniquePackCount: allPacks.length,
    },
    recommended,
    curated,
    needsAttention: needsAttention.slice(0, 8),
    coverageByProfile,
    nextQualityActions,
    capabilitiesNote:
      "Skill CRUD is not exposed as a dedicated control-room command yet, so this studio is review-first.",
  };
}

function workflowTone(status) {
  if (status === "ready") {
    return "good";
  }
  if (status === "blocked") {
    return "bad";
  }
  return "warn";
}

function deriveWorkflowStudio(snapshot, profileId) {
  const studio = snapshot?.workflowStudio || {};
  const recipes = asList(studio?.recipes).map(item => ({
    workflowId: item?.workflowId || item?.label || "",
    label: item?.label || "Workflow",
    description: item?.description || "",
    status: titleizeToken(item?.status || "available"),
    audience: titleizeToken(item?.audience || "all"),
    surface: titleizeToken(item?.surface || "builder_view"),
    reviewStatus: titleizeToken(item?.reviewStatus || "reviewed"),
    runtimeChoice: runtimeLabel(item?.runtimeChoice),
    skillIds: asList(item?.skillIds),
    serviceIds: asList(item?.serviceIds),
    verificationDefaults: asList(item?.verificationDefaults),
    tone: workflowTone(item?.status),
  }));
  const recommended =
    recipes.find(
      item =>
        item.tone !== "bad" &&
        ["All", titleizeToken(profileId), "Builder", "Beginner", "Advanced"].includes(
          item.audience,
        ),
    ) || recipes[0] || null;

  return {
    summary: {
      recipeCount: asInt(studio?.managementSummary?.recipeCount, recipes.length),
      reviewedCount: asInt(studio?.managementSummary?.reviewedCount),
      blockedCount: asInt(studio?.managementSummary?.blockedCount),
      recommendedMode: titleizeToken(studio?.recommendedMode || "agent"),
    },
    recipes: recipes.slice(0, 10),
    recommended,
    learningQueue: asList(studio?.learningQueue).slice(0, 6),
  };
}

function deriveBuilderOps(workspace) {
  return {
    gitActions: asList(workspace?.gitActions).map(item => ({
      actionId: item?.actionId || "",
      label: item?.label || item?.actionId || "Git action",
      detail: item?.detail || item?.command || "",
      requiresApproval: Boolean(item?.requiresApproval),
      surface: "git",
      tone: item?.requiresApproval ? "warn" : "neutral",
    })),
    validationActions: asList(workspace?.validationActions).map(item => ({
      actionId: item?.actionId || "",
      label: item?.label || item?.actionId || "Validation action",
      detail: item?.detail || item?.command || "",
      requiresApproval: Boolean(item?.requiresApproval),
      surface: "validate",
      tone: item?.requiresApproval ? "warn" : "good",
    })),
  };
}

function roadmapState(done, blocked = false) {
  if (done) {
    return "done";
  }
  return blocked ? "blocked" : "next";
}

function roadmapTone(state) {
  if (state === "done") {
    return "good";
  }
  if (state === "blocked") {
    return "bad";
  }
  return "warn";
}

function deriveQualityRoadmap({
  confidence,
  mission,
  setupHealth,
  serviceStudio,
  skillStudio,
  workflowStudio,
  builderOps,
}) {
  const requiredDone =
    confidence?.requiredGateSummary?.total > 0 &&
    confidence?.requiredGateSummary?.passed >= confidence?.requiredGateSummary?.total;
  const completionRate = asInt(confidence?.qualitySignals?.completionRate);
  const delegatedRate = asInt(confidence?.qualitySignals?.delegatedRunRate);
  const resumeCompletionRate = asInt(confidence?.qualitySignals?.resumeCompletionRate);
  const verificationPauseRate = asInt(confidence?.qualitySignals?.verificationPauseRate);
  const serviceHealthy =
    asInt(serviceStudio?.summary?.needsAttentionCount) === 0 &&
    asInt(setupHealth?.missingDependencies?.length) === 0;
  const skillQualityReady = asInt(skillStudio?.summary?.needsTestCount) === 0;
  const workflowReady = asInt(workflowStudio?.summary?.blockedCount) === 0;
  const proofReady = Boolean(confidence?.proofReady);
  const hasMission = Boolean(mission);
  const hasValidationAction = asList(builderOps?.validationActions).length > 0;

  const tracks = [
    {
      id: "required-gates",
      label: "Required gates stay green",
      state: roadmapState(requiredDone),
      detail: confidence?.requiredGateSummary?.label || "Required gate summary unavailable.",
      hint: requiredDone
        ? "All required gates are currently passing."
        : "Resolve failed required gates before quality tuning.",
      suggestedAction: hasValidationAction ? "Run validation action" : "",
      actionKind: hasValidationAction ? "validate" : "",
    },
    {
      id: "completion-rate",
      label: "Lift completion rate above 50%",
      state: roadmapState(completionRate >= 50, !hasMission),
      detail: `Current completion rate: ${completionRate}%`,
      hint: hasMission
        ? "Run bounded missions end-to-end and close them with proof."
        : "Launch a mission first to generate quality data.",
      suggestedAction: hasMission ? "Launch one bounded run" : "Start first mission",
      actionKind: "mission",
    },
    {
      id: "delegated-usage",
      label: "Lift delegated run rate above 20%",
      state: roadmapState(delegatedRate >= 20, !hasMission),
      detail: `Current delegated run rate: ${delegatedRate}%`,
      hint: "Use runtime lanes that exercise delegated execution with approval boundaries.",
      suggestedAction: "Launch delegated mission",
      actionKind: "mission",
    },
    {
      id: "resume-reliability",
      label: "Lift resumed-run completion above 60%",
      state: roadmapState(resumeCompletionRate >= 60, !hasMission),
      detail: `Current resumed completion rate: ${resumeCompletionRate}%`,
      hint: "Pause/resume real runs and ensure they still close with proof.",
      suggestedAction: "Run resume scenario",
      actionKind: "mission",
    },
    {
      id: "verification-friction",
      label: "Keep verification pauses below 25%",
      state: roadmapState(verificationPauseRate < 25),
      detail: `Current verification pause rate: ${verificationPauseRate}%`,
      hint: "Use validation actions continuously and tighten proof expectations.",
      suggestedAction: hasValidationAction ? "Run validation action" : "Review verification defaults",
      actionKind: hasValidationAction ? "validate" : "",
    },
    {
      id: "skill-quality",
      label: "Skill studio quality bar",
      state: roadmapState(skillQualityReady),
      detail: `${asInt(skillStudio?.summary?.needsTestCount)} pack(s) still need test/review coverage.`,
      hint: skillQualityReady
        ? "Skill packs are currently reviewed."
        : "Focus on packs marked as not reviewed or not installed.",
      suggestedAction:
        asList(skillStudio?.nextQualityActions)[0] || "Review skill studio inventory",
      actionKind: "skill",
    },
    {
      id: "service-health",
      label: "Service health stays stable",
      state: roadmapState(serviceHealthy),
      detail: `${asInt(serviceStudio?.summary?.needsAttentionCount)} service(s) need attention.`,
      hint: serviceHealthy
        ? "All tracked services are currently healthy."
        : "Repair service blockers before long unattended runs.",
      suggestedAction: "Run service repair action",
      actionKind: "service",
    },
    {
      id: "workflow-readiness",
      label: "Workflow recipes stay ready",
      state: roadmapState(workflowReady && proofReady),
      detail: `${asInt(workflowStudio?.summary?.blockedCount)} workflow(s) blocked · proof cycle ${proofReady ? "ready" : "not ready"}.`,
      hint: "Use one recommended workflow end-to-end and capture proof.",
      suggestedAction: "Execute recommended workflow",
      actionKind: "workflow",
    },
  ].map(item => ({
    ...item,
    tone: roadmapTone(item.state),
  }));

  const doneCount = tracks.filter(item => item.state === "done").length;
  const nextCount = tracks.filter(item => item.state === "next").length;
  const blockedCount = tracks.filter(item => item.state === "blocked").length;

  return {
    targetScore: 100,
    currentScore: confidence?.score || 0,
    gap: Math.max(0, 100 - (confidence?.score || 0)),
    doneCount,
    nextCount,
    blockedCount,
    tracks,
    headline:
      nextCount === 0 && blockedCount === 0
        ? "Quality roadmap is complete."
        : `${nextCount + blockedCount} quality step(s) remain for 100%.`,
  };
}

function classifyFeatureTruth({ mission, snapshot, setupHealth, previewMode }) {
  const realReady = [];
  const realSecondary = [];
  const fixtureOnly = [];
  const notReady = [];

  if (mission) {
    realReady.push("Mission thread and action history");
  }
  if ((snapshot?.workspaces || []).length > 0) {
    realReady.push("Workspace registration and runtime selection");
  }
  if ((snapshot?.workspaces || []).some(item => asList(item?.serviceManagement).length > 0)) {
    realReady.push("Service management summary and health detail");
  }
  if ((snapshot?.skillLibrary?.curatedPacks || []).length > 0) {
    realReady.push("Skill catalog with reviewed pack metadata");
  }
  if ((snapshot?.workflowStudio?.recipes || []).length > 0) {
    realReady.push("Workflow recipe studio");
  }
  if (snapshot?.releaseReadiness?.score !== undefined) {
    realReady.push("Release-readiness scoring and gate evidence");
  }
  if ((snapshot?.runtimes || []).some(item => item?.detected)) {
    realReady.push("Runtime detection and health telemetry");
  }
  if ((snapshot?.bridgeLab?.connectedSessions || []).length > 0) {
    realSecondary.push("Connected app bridge telemetry");
  }
  if ((snapshot?.skillLibrary?.recommendedPacks || []).length > 0) {
    realSecondary.push("Skill recommendation signals");
  }
  if (snapshot?.profiles?.availableProfiles?.length > 0) {
    realSecondary.push("Profile parameter matrix and behavior defaults");
  }

  if (previewMode !== "live") {
    fixtureOnly.push("Fixture-backed snapshot review");
  }
  fixtureOnly.push("Builder review controls");
  fixtureOnly.push("Live sync cadence controls");

  for (const blocker of asList(setupHealth?.blockerExplanations)) {
    notReady.push(blocker);
  }
  for (const gate of asList(snapshot?.releaseReadiness?.gates)) {
    if (gate?.required && !gate?.passed) {
      notReady.push(`${gate.label}: ${gate.details}`);
    }
  }

  if (asList(snapshot?.workspaces).length === 0) {
    notReady.push("No workspace selected");
  }
  if (!mission) {
    notReady.push("No active mission");
  }

  return {
    realReady: uniq(realReady),
    realSecondary: uniq(realSecondary),
    fixtureOnly: uniq(fixtureOnly),
    notReady: uniq(notReady),
  };
}

function deriveStateAudit({ mission, setupHealth }) {
  const status = mission?.state?.status || "none";
  const approvalWait =
    asList(mission?.proof?.pending_approvals).length > 0 ||
    status === "needs_approval" ||
    status === "waiting_for_approval";
  const verificationFailure =
    asList(mission?.state?.verification_failures).length > 0 || status === "verification_failed";
  const firstRun = !mission;
  const blockedSetup = !setupHealth?.environmentReady;

  return [
    {
      id: "first-run",
      label: "First run",
      state: firstRun ? "active" : "resolved",
      nextAction: firstRun ? "Pick workspace and launch one bounded mission." : "Already passed.",
    },
    {
      id: "no-mission",
      label: "No mission",
      state: firstRun ? "active" : "resolved",
      nextAction: firstRun ? "Launch mission from the primary action button." : "Mission exists.",
    },
    {
      id: "blocked-setup",
      label: "Blocked setup",
      state: blockedSetup ? "active" : "resolved",
      nextAction: blockedSetup
        ? asList(setupHealth?.blockerExplanations)[0] || "Run setup repair actions."
        : "Setup health is ready.",
    },
    {
      id: "mission-launch",
      label: "Mission launch",
      state: mission ? "resolved" : "waiting",
      nextAction: mission ? "Mission launched." : "Pending first launch.",
    },
    {
      id: "approval-wait",
      label: "Approval wait",
      state: approvalWait ? "active" : "resolved",
      nextAction: approvalWait ? "Review queue and approve or reject." : "No approval boundary active.",
    },
    {
      id: "active-run",
      label: "Active run",
      state: status === "running" ? "active" : "resolved",
      nextAction:
        status === "running" ? "Monitor thread and proof deltas." : "Run is not currently active.",
    },
    {
      id: "verification-failure",
      label: "Verification failure",
      state: verificationFailure ? "active" : "resolved",
      nextAction: verificationFailure
        ? asList(mission?.state?.verification_failures)[0] || "Open proof drawer."
        : "No current failure.",
    },
    {
      id: "resumed-run",
      label: "Resumed run",
      state:
        mission?.missionLoop?.continuityState === "resume_available" || status === "queued"
          ? "active"
          : "resolved",
      nextAction:
        mission?.missionLoop?.continuityState === "resume_available" || status === "queued"
          ? "Use Resume mission."
          : "No resume boundary active.",
    },
    {
      id: "completed-run",
      label: "Completed run",
      state: status === "completed" ? "active" : "resolved",
      nextAction:
        status === "completed" ? "Review proof and close out." : "Mission has not completed yet.",
    },
  ];
}

function deriveEnvironmentLabel(setupHealth, mission, workspace) {
  const runtime =
    mission?.runtime_id ||
    workspace?.default_runtime ||
    asList(setupHealth?.dependencies).find(item => item?.category === "agent_runtime")?.dependencyId;
  if (!runtime) {
    return "Environment status";
  }
  return `${runtimeLabel(runtime)} lane`;
}

function deriveElapsed(mission) {
  const seconds =
    mission?.missionLoop?.timeBudget?.elapsedSeconds || mission?.state?.elapsed_runtime_seconds;
  if (typeof seconds === "number") {
    return formatDurationCompact(seconds);
  }
  return "0m";
}

function deriveRemaining(mission) {
  const seconds =
    mission?.missionLoop?.timeBudget?.remainingSeconds || mission?.state?.remaining_runtime_seconds;
  if (typeof seconds === "number") {
    return formatDurationCompact(seconds);
  }
  return "Unknown";
}

function timeValue(value) {
  if (!value) {
    return Number.NaN;
  }
  const parsed = Date.parse(String(value));
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

function latestTimestamp(...values) {
  let best = "";
  let bestValue = Number.NEGATIVE_INFINITY;
  for (const value of values.flat()) {
    const score = timeValue(value);
    if (Number.isFinite(score) && score >= bestValue) {
      best = String(value);
      bestValue = score;
    }
  }
  return best;
}

function isTerminalMissionStatus(status) {
  return ["completed", "failed", "cancelled", "stopped"].includes(
    String(status || "").toLowerCase(),
  );
}

function latestMeaningfulDelegatedEvent(mission) {
  for (const session of asList(mission?.delegated_runtime_sessions).slice().reverse()) {
    const event = asList(session?.latest_events)
      .slice()
      .reverse()
      .find(item => item?.message && item?.kind !== "session.heartbeat");
    if (event) {
      return event;
    }
  }
  return null;
}

function deriveMissionLatestTimestamp(mission) {
  return latestTimestamp(
    mission?.updated_at,
    mission?.state?.updated_at,
    mission?.state?.worker_heartbeat_at,
    mission?.missionLoop?.updatedAt,
    asList(mission?.action_history).map(item => item?.executed_at),
    asList(mission?.plan_revisions).map(item => item?.created_at),
    asList(mission?.delegated_runtime_sessions).map(item => item?.updated_at),
    asList(mission?.delegated_runtime_sessions).flatMap(item =>
      asList(item?.latest_events).map(event => event?.timestamp || event?.created_at),
    ),
  );
}

function deriveMissionFreshness(mission, referenceTimestamp) {
  const status = String(
    mission?.state?.status || mission?.missionLoop?.continuityState || "active",
  ).toLowerCase();
  if (["blocked", "needs_approval", "verification_failed"].includes(status)) {
    return {
      state: "blocked",
      label: status === "needs_approval" ? "Approval needed" : "Blocked",
      detail: "The mission is not making unattended progress.",
      tone: "warn",
      ageSeconds: null,
    };
  }
  if (status === "queued") {
    return {
      state: "queued",
      label: "Queued",
      detail: "Waiting for its workspace execution slot.",
      tone: "neutral",
      ageSeconds: null,
    };
  }
  const latest = timeValue(deriveMissionLatestTimestamp(mission));
  const reference = timeValue(referenceTimestamp);
  if (!Number.isFinite(latest) || !Number.isFinite(reference)) {
    return {
      state: "unverified",
      label: "Freshness unknown",
      detail: "No comparable heartbeat or update timestamp was returned.",
      tone: "neutral",
      ageSeconds: null,
    };
  }
  const ageSeconds = Math.max(0, Math.round((reference - latest) / 1000));
  if (ageSeconds <= 120) {
    return {
      state: "live",
      label: "Live",
      detail: "A heartbeat or mission update arrived within two minutes.",
      tone: "good",
      ageSeconds,
    };
  }
  if (ageSeconds <= 900) {
    return {
      state: "quiet",
      label: "Quiet",
      detail: "No recent movement; the lane may still be working.",
      tone: "neutral",
      ageSeconds,
    };
  }
  return {
    state: "stale",
    label: "Stale",
    detail: "No heartbeat or mission update has arrived for more than fifteen minutes.",
    tone: "warn",
    ageSeconds,
  };
}

function deriveMissionLastMovement(mission) {
  const latestAction = asList(mission?.action_history).slice(-1)[0];
  if (latestAction?.result?.result_summary || latestAction?.proposal?.title) {
    return (
      latestAction?.result?.result_summary ||
      latestAction?.result?.error ||
      latestAction?.proposal?.title
    );
  }
  const delegatedEvent = latestMeaningfulDelegatedEvent(mission);
  if (delegatedEvent?.message) {
    return delegatedEvent.message;
  }
  return (
    mission?.state?.last_plan_summary ||
    mission?.missionLoop?.continuityDetail ||
    mission?.proof?.summary ||
    "Waiting for the next mission movement."
  );
}

function deriveMissionExecutionPath(mission, workspace) {
  const delegated = asList(mission?.delegated_runtime_sessions).find(
    item => item?.execution_root || item?.workspace_root,
  );
  return (
    delegated?.execution_root ||
    delegated?.workspace_root ||
    mission?.execution_scope?.execution_root ||
    mission?.state?.execution_scope?.execution_root ||
    workspace?.root_path ||
    ""
  );
}

function pathLeafLabel(value) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  const parts = text.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] || text;
}

function missionNeedsAttention(mission) {
  return Boolean(
    asList(mission?.proof?.pending_approvals).length > 0 ||
      asList(mission?.state?.verification_failures).length > 0 ||
      ["needs_approval", "blocked", "verification_failed", "queued"].includes(
        mission?.state?.status || "",
      ),
  );
}

function activityTone(activity) {
  const kind = String(activity?.kind || "").toLowerCase();
  const action = String(activity?.metadata?.action || "").toLowerCase();
  const message = `${kind} ${activity?.message || ""}`;
  if (/failed|error|verification_failed/.test(message)) {
    return "bad";
  }
  if (kind === "approval.request" || kind === "mission.queued" || /approval|blocked|queued/.test(message)) {
    return "warn";
  }
  if (action === "complete" || /completed|healthy|ready/.test(message)) {
    return "good";
  }
  return "neutral";
}

function deriveActivityDetail(activity, missionById) {
  const metadata = activity?.metadata || {};
  const missionTitle =
    missionById.get(activity?.mission_id)?.title ||
    missionById.get(activity?.mission_id)?.objective ||
    "";
  const blockingMissionTitle =
    missionById.get(metadata.blockingMissionId)?.title ||
    missionById.get(metadata.blockingMissionId)?.objective ||
    metadata.blockingMissionId ||
    "";
  return uniq([
    missionTitle,
    metadata.runtimeId ? runtimeLabel(metadata.runtimeId) : metadata.runtime_id ? runtimeLabel(metadata.runtime_id) : "",
    metadata.provider ? `${titleizeToken(metadata.provider)}${metadata.model ? `:${metadata.model}` : ""}` : "",
    metadata.queuePosition ? `Queue ${metadata.queuePosition}` : "",
    metadata.action ? `Action ${titleizeToken(metadata.action)}` : "",
    metadata.autopilotStatus ? titleizeToken(metadata.autopilotStatus) : "",
    metadata.pauseReason ? `Pause ${titleizeToken(metadata.pauseReason)}` : "",
    metadata.blockerClass ? `Blocker ${titleizeToken(metadata.blockerClass)}` : "",
    blockingMissionTitle ? `Blocked by ${blockingMissionTitle}` : "",
  ]).join(" · ");
}

function deriveMissionNexus(mission, workspace) {
  const pendingApproval = asList(mission?.proof?.pending_approvals)[0];
  const verificationFailure = asList(mission?.state?.verification_failures)[0];
  const latestPlan = asList(mission?.plan_revisions).slice(-1)[0];
  const delegatedEvent = latestMeaningfulDelegatedEvent(mission);
  const status = mission?.state?.status || mission?.missionLoop?.continuityState || "active";
  const executionPath = deriveMissionExecutionPath(mission, workspace);

  let label = "";
  let reason = "";
  let tone = "neutral";

  if (verificationFailure) {
    label = "Verification nexus";
    reason = verificationFailure;
    tone = "bad";
  } else if (pendingApproval) {
    label = "Approval nexus";
    reason = pendingApproval;
    tone = "warn";
  } else if (["needs_approval", "blocked", "queued"].includes(status)) {
    label = "Operator nexus";
    reason =
      mission?.state?.last_plan_summary ||
      mission?.missionLoop?.continuityDetail ||
      deriveMissionLastMovement(mission);
    tone = "warn";
  } else if (latestPlan?.summary) {
    label = "Plan nexus";
    reason = latestPlan.summary;
    tone = "neutral";
  } else if (delegatedEvent?.message) {
    label = "Runtime nexus";
    reason = delegatedEvent.message;
    tone = missionStatusTone(status);
  } else {
    return null;
  }

  return {
    id: `nexus-${mission?.mission_id || mission?.title || reason}`,
    missionId: mission?.mission_id || "",
    title: mission?.title || mission?.objective || "Mission",
    label,
    reason,
    detail: deriveCurrentTask(mission),
    next: deriveNextCheckpoint(mission),
    tone,
    timestamp: deriveMissionLatestTimestamp(mission),
    workspaceName: workspace?.name || "Workspace",
    executionPath,
    folderLabel: pathLeafLabel(executionPath) || pathLeafLabel(workspace?.root_path || ""),
  };
}

const WORKSPACE_SYNC_STATUS_PREFIX = "sync_status:";
const WORKSPACE_SYNC_BATCH_PREFIX = "sync_conflict_batch_resolution:";
const SUB_AGENT_LANE_ROLES = ["planner", "executor", "verifier"];
const SYNC_RESOLUTION_CONTROLS = [
  { id: "local-wins", resolution: "local_wins", label: "Keep computer copy" },
  { id: "nas-wins", resolution: "nas_wins", label: "Keep NAS copy" },
  { id: "keep-newer", resolution: "keep_newer", label: "Keep newer file" },
];

function parseWorkspaceGoalJson(workspace, prefix) {
  const rows = [];
  for (const goal of asList(workspace?.goals)) {
    const text = String(goal || "").trim();
    if (!text.startsWith(prefix)) {
      continue;
    }
    try {
      const parsed = JSON.parse(text.slice(prefix.length));
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        rows.push(parsed);
      }
    } catch {
      // A malformed goal row is skipped; it is never replaced with an invented status.
    }
  }
  return rows;
}

export function parseWorkspaceSyncConflictBatchResolutions(workspace) {
  return parseWorkspaceGoalJson(workspace, WORKSPACE_SYNC_BATCH_PREFIX);
}

export function parseWorkspaceSyncStatus(workspace) {
  const latest = parseWorkspaceGoalJson(workspace, WORKSPACE_SYNC_STATUS_PREFIX).pop() || {};
  const syncReceipt = latest.syncReceipt && typeof latest.syncReceipt === "object" ? latest.syncReceipt : {};
  const conflictPaths = uniq(
    asList(latest.conflictSamples).map(sample => sample?.relativePath || sample?.relative_path || ""),
  );
  const conflictCount = asInt(latest.conflictsDetected ?? syncReceipt.conflictsDetected);
  const manualReviewRequired = Boolean(latest.manualReviewRequired || syncReceipt.manualReviewRequired);
  const needsResolution = conflictPaths.length > 0 && (manualReviewRequired || conflictCount > 0);
  return {
    known: Object.keys(latest).length > 0,
    receiptId: String(syncReceipt.receiptId || ""),
    syncReceipt,
    effectiveDirection: String(latest.effectiveDirection || syncReceipt.effectiveDirection || ""),
    conflictCount,
    manualReviewRequired,
    firstConflictRelativePath: conflictPaths[0] || "",
    batchConflictRelativePaths: conflictPaths,
    resolutionControls: needsResolution ? SYNC_RESOLUTION_CONTROLS : [],
    batchResolutionControls: needsResolution && conflictPaths.length > 1 ? SYNC_RESOLUTION_CONTROLS : [],
    conflictBatchResolutionReceipts: parseWorkspaceSyncConflictBatchResolutions(workspace),
  };
}

// The backend owns the authoritative project progress history. When a summary has
// not delivered it, the board falls back to counts derived from the missions it
// does have and says so (liveData: false) instead of claiming the v1 schema.
export function deriveProjectProgressHistory(snapshot) {
  const history = snapshot?.projectProgressHistory;
  if (history?.schema === "fluxio.project_progress_history.v1") {
    return history;
  }
  const missions = asList(snapshot?.missions);
  const projects = asList(snapshot?.workspaces).map(workspace => {
    const rows = missions.filter(item => item?.workspace_id === workspace?.workspace_id);
    const active = rows.filter(item => !isTerminalMissionStatus(item?.state?.status));
    const queued = rows.filter(item => item?.state?.status === "queued");
    const blocked = rows.filter(item => missionNeedsAttention(item) && item?.state?.status !== "queued");
    const completed = rows.filter(item => item?.state?.status === "completed");
    const latest = rows
      .slice()
      .sort((left, right) => timeValue(deriveMissionLatestTimestamp(right)) - timeValue(deriveMissionLatestTimestamp(left)))[0];
    return {
      workspaceId: workspace?.workspace_id || "",
      workspaceName: workspace?.name || "Workspace",
      rootPath: workspace?.root_path || "",
      runtime: workspace?.default_runtime || "",
      counts: {
        missions: rows.length,
        active: active.length,
        queued: queued.length,
        blocked: blocked.length,
        completed: completed.length,
      },
      latestMissionId: latest?.mission_id || "",
      latestMissionTitle: latest?.title || latest?.objective || "",
      milestones: [],
      buckets: [],
      liveData: false,
    };
  });
  return { projects, schedulingQueue: [], liveData: false, empty: projects.length === 0 };
}

export function deriveWorkspaceHealth({ workspaces, activeConversations, progressHistory }) {
  const projectById = new Map(asList(progressHistory?.projects).map(item => [item?.workspaceId, item]));
  return asList(workspaces)
    .map(workspace => {
      const workspaceId = workspace?.workspace_id || "";
      const project = projectById.get(workspaceId) || {};
      const counts = project.counts || {};
      const conversations = asList(activeConversations).filter(item => item.workspaceId === workspaceId);
      const blockedCount = Math.max(asInt(counts.blocked), conversations.filter(item => item.blocked).length);
      const activeCount = Math.max(asInt(counts.active), conversations.length);
      const syncStatus = parseWorkspaceSyncStatus(workspace);
      const syncAuthority = project.syncAuthority || {};
      const syncLabel = syncAuthority.schema
        ? titleizeToken(syncAuthority.state || syncAuthority.authority || "sync")
        : syncStatus.known
          ? syncStatus.manualReviewRequired
            ? "Sync review needed"
            : titleizeToken(syncStatus.effectiveDirection || "synced")
          : "Local only";
      return {
        workspaceId,
        title: workspace?.name || project.workspaceName || "Workspace",
        path: workspace?.root_path || "",
        runtime: runtimeLabel(workspace?.default_runtime || project.runtime),
        syncLabel,
        syncStatus,
        syncAuthority,
        scheduleRecommendation: project.scheduleRecommendation || {},
        launchRehearsal: project.launchRehearsal || {},
        latestMissionTitle: project.latestMissionTitle || "No mission has run in this project yet.",
        nextAction:
          project.nextAction ||
          (blockedCount > 0
            ? "Review the first blocked mission before dispatching more project work."
            : "Launch the next mission for this project."),
        progressMilestones: asList(project.milestones),
        progressBuckets: asList(project.buckets),
        activeCount,
        blockedCount,
        completedCount: asInt(counts.completed),
        missionCount: asInt(counts.missions, conversations.length),
        tone: blockedCount > 0 || syncStatus.manualReviewRequired ? "warn" : activeCount > 0 ? "good" : "neutral",
      };
    })
    .sort((left, right) => {
      if (left.blockedCount !== right.blockedCount) {
        return right.blockedCount - left.blockedCount;
      }
      if (left.activeCount !== right.activeCount) {
        return right.activeCount - left.activeCount;
      }
      return String(left.title).localeCompare(String(right.title));
    });
}

// Context roots, dependency edges and the write-scope preflight are computed by the
// backend per mission. The board surfaces the selected (or first active) mission
// contract and keeps an empty, truthful shape when none is attached.
export function deriveMissionContextRoots({ mission, activeMissions }) {
  const candidates = [mission, ...asList(activeMissions)];
  const source = candidates.find(item => item?.contextRoots?.schema)?.contextRoots;
  if (source) {
    return source;
  }
  return {
    roots: [],
    related: [],
    dependencyEdges: [],
    writeScopePreflight: { status: "unknown", warnings: [] },
    counts: { totalRoots: 0, relatedWorkspaces: 0, writableRoots: 0, syncPairs: 0, dependencyEdges: 0 },
    policy: {
      writeScope: "primary_and_declared_mirrors",
      relatedWorkspaceWritePolicy: "read_only_until_selected",
    },
  };
}

function laneControls(mission, role) {
  const status = String(mission?.state?.status || "");
  const running = ["running", "active", "executing"].includes(status);
  return [
    { id: "inspect-events", action: "inspect-events", label: "Inspect events", enabled: true, detail: `Open the ${role} lane event trail.` },
    { id: "proof", action: "proof", label: "Open proof", enabled: true, detail: `Review ${role} proof and receipts.` },
    { id: "reroute", action: "reroute", label: "Reroute", enabled: !["completed", "stopped"].includes(status), detail: `Apply a recommended ${role} route with a receipt.` },
    running
      ? { id: "pause", action: "pause", label: "Stop mission", enabled: true, detail: "Request a mission stop." }
      : { id: "resume", action: "resume", label: "Resume mission", enabled: status !== "completed", detail: "Request a mission resume." },
  ];
}

// Planner, executor and verifier routes become separate lanes, each with its own
// proof drill-down and the controls the lane-control receipt command understands.
export function deriveSubAgentLanes({ activeMissions, freshnessReference, productionHarness }) {
  const lanes = [];
  for (const mission of asList(activeMissions)) {
    const contract = mission?.effectiveRouteContract || {};
    const receipts = asList(contract.mutationReceipts).filter(item => item && typeof item === "object");
    const freshness = deriveMissionFreshness(mission, freshnessReference);
    const missionId = mission?.mission_id || "";
    for (const route of asList(contract.roles)) {
      const role = String(route?.role || "").toLowerCase();
      if (!SUB_AGENT_LANE_ROLES.includes(role)) {
        continue;
      }
      const routeReceipt = receipts.filter(item => item.role === role).pop() || {};
      const blocked = missionNeedsAttention(mission);
      lanes.push({
        id: `${missionId}:${role}`,
        missionId,
        missionTitle: mission?.title || mission?.objective || "Mission",
        role: titleizeToken(role),
        statusLabel: titleizeToken(mission?.state?.status || "active"),
        tone: blocked ? "warn" : missionStatusTone(mission?.state?.status),
        provider: route?.provider ? titleizeToken(route.provider) : "Unresolved",
        model: route?.model || "Profile default",
        effort: route?.effort || "medium",
        runtime: runtimeLabel(route?.runtimeId || mission?.runtime_id),
        harness: titleizeToken(mission?.harness_id || productionHarness),
        fallbackPolicy: route?.fallbackPolicy || "same_provider",
        taskType: route?.taskType || "general_coding",
        routeIntent: route?.routeIntent || "",
        routeReason: route?.reason || "",
        fitScore: asInt(route?.fitScore),
        outcomeSampleCount: asInt(route?.outcomeSampleCount),
        outcomeSuccessRate: asInt(route?.outcomeSuccessRate),
        detail: deriveVerificationSummary(mission),
        laneProof: {
          heartbeatStatus: freshness.label,
          summary: deriveVerificationSummary(mission),
          passedChecks: asList(mission?.proof?.passed_checks).length,
          failedChecks: asList(mission?.state?.verification_failures).length,
          pendingApprovals: asList(mission?.proof?.pending_approvals).length,
          changedFiles: asList(mission?.changed_files).length,
          routeReceipt,
        },
        controls: laneControls(mission, role),
      });
    }
  }
  return lanes;
}

function deriveBuilderBoard({ mission, workspace, snapshot, confidence, uiMode = "agent" }) {
  const workspaceId = uiMode === "builder" ? "" : workspace?.workspace_id || "";
  const workspaces = asList(snapshot?.workspaces);
  const workspaceById = new Map(workspaces.map(item => [item?.workspace_id, item]));
  const missions = asList(snapshot?.missions).filter(item =>
    workspaceId ? item?.workspace_id === workspaceId : true,
  );
  const missionById = new Map(missions.map(item => [item?.mission_id, item]));
  const activeMissions = missions.filter(item => !isTerminalMissionStatus(item?.state?.status));
  const blockedCount = activeMissions.filter(item => missionNeedsAttention(item)).length;
  const delegatedLaneCount = activeMissions.reduce(
    (total, item) =>
      total +
      asList(item?.delegated_runtime_sessions).filter(
        session => !["completed", "failed", "stopped"].includes(session?.status || ""),
      ).length,
    0,
  );
  const runtimeCount = new Set(activeMissions.map(item => item?.runtime_id).filter(Boolean)).size;
  const selectedMissionId = mission?.mission_id || "";
  const productionHarness =
    snapshot?.harnessLab?.productionHarness || workspace?.preferred_harness || "fluxio_hybrid";
  const freshnessReference = latestTimestamp(
    snapshot?.generatedAt,
    snapshot?.generated_at,
    snapshot?.updatedAt,
    asList(snapshot?.missions).map(item => deriveMissionLatestTimestamp(item)),
  );

  const activeConversations = activeMissions
    .slice()
    .sort((left, right) => {
      const delta = timeValue(deriveMissionLatestTimestamp(right)) - timeValue(deriveMissionLatestTimestamp(left));
      if (Number.isFinite(delta) && delta !== 0) {
        return delta;
      }
      return String(left?.title || left?.objective || "").localeCompare(
        String(right?.title || right?.objective || ""),
      );
    })
    .map(item => {
      const ownerWorkspace = workspaceById.get(item?.workspace_id) || workspace;
      const status = item?.state?.status || item?.missionLoop?.continuityState || "active";
      const executionPath = deriveMissionExecutionPath(item, ownerWorkspace);
      const providerTruth =
        item?.providerTruth ||
        item?.missionLoop?.providerTruth ||
        item?.state?.provider_runtime_truth ||
        {};
      const activeRoute = providerTruth?.activeRoute || {};
      const blocker =
        item?.missionLoop?.blocker ||
        item?.state?.blocker_classification ||
        {};
      const stuckReason =
        blocker?.summary ||
        resolveMissionPauseReason(item) ||
        "";
      const freshness = deriveMissionFreshness(item, freshnessReference);
      return {
        missionId: item?.mission_id || "",
        workspaceId: item?.workspace_id || "",
        workspaceName: ownerWorkspace?.name || "Workspace",
        workspacePath: ownerWorkspace?.root_path || "",
        folderLabel: pathLeafLabel(executionPath) || pathLeafLabel(ownerWorkspace?.root_path || ""),
        title: item?.title || item?.objective || "Mission",
        runtime: runtimeLabel(item?.runtime_id),
        statusLabel: titleizeToken(status),
        tone: missionStatusTone(item?.state?.status),
        selected: item?.mission_id === selectedMissionId,
        blocked: missionNeedsAttention(item),
        current: deriveCurrentTask(item),
        next: deriveNextCheckpoint(item),
        lastMovement: deriveMissionLastMovement(item),
        updatedAt: deriveMissionLatestTimestamp(item),
        freshnessState: freshness.state,
        freshnessLabel: freshness.label,
        freshnessDetail: freshness.detail,
        freshnessTone: freshness.tone,
        freshnessAgeSeconds: freshness.ageSeconds,
        pendingApprovals: asList(item?.proof?.pending_approvals).length,
        verificationFailures: asList(item?.state?.verification_failures).length,
        delegatedSessions: asList(item?.delegated_runtime_sessions).filter(
          session => !["completed", "failed", "stopped"].includes(session?.status || ""),
        ).length,
        executionPath,
        harnessLabel: titleizeToken(item?.harness_id || productionHarness),
        providerLabel: activeRoute?.provider ? titleizeToken(activeRoute.provider) : "Unresolved",
        modelLabel: activeRoute?.model || "Profile default",
        routeRole: activeRoute?.role ? titleizeToken(activeRoute.role) : "Route",
        blockerClass: blocker?.class || "",
        stuckReason,
        nextCheckpointPrediction: deriveNextCheckpoint(item),
      };
    });

  const projectProgressHistory = deriveProjectProgressHistory(snapshot);
  const workspaceHealth = deriveWorkspaceHealth({
    workspaces: workspaceId ? workspaces.filter(item => item?.workspace_id === workspaceId) : workspaces,
    activeConversations,
    progressHistory: projectProgressHistory,
  });
  const contextRoots = deriveMissionContextRoots({ mission, activeMissions });
  const subAgentLanes = deriveSubAgentLanes({ activeMissions, freshnessReference, productionHarness });

  const roots = workspaces
    .filter(item => (workspaceId ? item?.workspace_id === workspaceId : true))
    .map(item => {
      const workspaceConversations = activeConversations.filter(
        entry => entry.workspaceId === item?.workspace_id,
      );
      const blocked = workspaceConversations.filter(entry => entry.blocked).length;
      const delegated = workspaceConversations.reduce(
        (total, entry) => total + asInt(entry.delegatedSessions),
        0,
      );
      return {
        workspaceId: item?.workspace_id || "",
        title: item?.name || "Workspace",
        path: item?.root_path || "",
        folderLabel: pathLeafLabel(item?.root_path),
        activeCount: workspaceConversations.length,
        blockedCount: blocked,
        delegatedCount: delegated,
        tone:
          blocked > 0
            ? "warn"
            : workspaceConversations.length > 0 || item?.runtimeStatus?.detected
              ? "good"
              : "neutral",
      };
    })
    .sort((left, right) => {
      if (left.blockedCount !== right.blockedCount) {
        return right.blockedCount - left.blockedCount;
      }
      if (left.activeCount !== right.activeCount) {
        return right.activeCount - left.activeCount;
      }
      return String(left.title).localeCompare(String(right.title));
    });

  const nexuses = activeMissions
    .map(item => deriveMissionNexus(item, workspaceById.get(item?.workspace_id) || workspace))
    .filter(Boolean)
    .sort((left, right) => timeValue(right.timestamp) - timeValue(left.timestamp))
    .slice(0, 8);

  const whileAway = asList(snapshot?.activity)
    .filter(item => {
      if (!item?.mission_id) {
        return true;
      }
      const missionRow = missionById.get(item.mission_id);
      return workspaceId ? missionRow?.workspace_id === workspaceId : true;
    })
    .slice(0, 10)
    .map((item, index) => ({
      id: `${item?.mission_id || "workspace"}-${item?.timestamp || index}-${item?.kind || "activity"}`,
      missionId: item?.mission_id || "",
      missionTitle:
        missionById.get(item?.mission_id)?.title ||
        missionById.get(item?.mission_id)?.objective ||
        "Workspace activity",
      label: titleizeToken(item?.kind || "activity"),
      message: item?.message || "Activity update",
      detail: deriveActivityDetail(item, missionById),
      tone: activityTone(item),
      timestamp: item?.timestamp || "",
    }));

  const nextUpSource = activeConversations.length > 0 ? activeConversations : [];
  const nextUp = nextUpSource.slice(0, 8).map(item => ({
    missionId: item.missionId,
    title: item.title,
    statusLabel: item.statusLabel,
    runtime: item.runtime,
    summary: item.next,
    detail: item.blocked ? item.lastMovement : item.current,
    routeLabel: `${item.providerLabel} · ${item.modelLabel}`,
    checkpoint: item.nextCheckpointPrediction,
    tone: item.blocked ? "warn" : item.tone,
    updatedAt: item.updatedAt,
    selected: item.selected,
  }));

  const stuckThreads = activeConversations
    .filter(item => item.blocked || item.blockerClass || item.stuckReason)
    .slice(0, 6)
    .map(item => ({
      missionId: item.missionId,
      title: item.title,
      blockerClass: titleizeToken(item.blockerClass || "operator_only"),
      reason: item.stuckReason || item.lastMovement || "Blocked without a recorded reason.",
      routeLabel: `${item.providerLabel} · ${item.modelLabel}`,
      runtime: item.runtime,
      tone: item.tone === "bad" ? "bad" : "warn",
    }));

  const winningRouteMap = new Map();
  for (const item of activeConversations) {
    const key = `${item.runtime}|${item.providerLabel}|${item.modelLabel}`;
    const existing = winningRouteMap.get(key) || {
      key,
      runtime: item.runtime,
      provider: item.providerLabel,
      model: item.modelLabel,
      activeCount: 0,
      blockedCount: 0,
    };
    existing.activeCount += 1;
    if (item.blocked) {
      existing.blockedCount += 1;
    }
    winningRouteMap.set(key, existing);
  }
  const winningRoutes = [...winningRouteMap.values()]
    .sort((left, right) => {
      if (left.blockedCount !== right.blockedCount) {
        return left.blockedCount - right.blockedCount;
      }
      return right.activeCount - left.activeCount;
    })
    .slice(0, 4)
    .map(item => ({
      ...item,
      tone: item.blockedCount > 0 ? "warn" : "good",
      outcomeSampleCount: item.activeCount,
      outcomeSuccessRate: ratioPercent(item.activeCount - item.blockedCount, item.activeCount),
      outcomeTrend: item.blockedCount > 0 ? "needs_repair" : "stable",
      label: `${item.runtime} · ${item.provider} · ${item.model}`,
      detail:
        item.blockedCount > 0
          ? `${item.activeCount} active · ${item.blockedCount} blocked`
          : `${item.activeCount} active and clear`,
    }));

  const predictedCheckpoints = nextUp
    .map(item => `${item.title}: ${item.checkpoint || item.summary}`)
    .slice(0, 6);

  const changedWhileAway = whileAway
    .slice(0, 6)
    .map(item => `${item.missionTitle}: ${item.message}`);

  const summary =
    activeConversations.length > 0
      ? `${activeConversations.length} active conversation${activeConversations.length === 1 ? "" : "s"} across ${Math.max(runtimeCount, 1)} runtime lane${Math.max(runtimeCount, 1) === 1 ? "" : "s"}. ${blockedCount > 0 ? `${blockedCount} need operator attention.` : "No operator block is active right now."} Top route: ${winningRoutes[0]?.label || "not resolved yet"}.`
      : "No active conversations. Builder stays ready for launch, runtime tuning, and review.";

  return {
    headline:
      activeConversations.length > 0
        ? "Builder command deck"
        : "Builder readiness deck",
    summary,
    metrics: [
      {
        id: "active",
        label: "Active conversations",
        value: `${activeConversations.length}`,
        detail: activeConversations.length > 0 ? "Visible in the control board" : "Launch a mission to start the board",
        tone: activeConversations.length > 0 ? "good" : "neutral",
      },
      {
        id: "blocked",
        label: "Need attention",
        value: `${blockedCount}`,
        detail: blockedCount > 0 ? "Approvals, queue, or verification boundaries are open" : "No active blockers",
        tone: blockedCount > 0 ? "warn" : "good",
      },
      {
        id: "delegated",
        label: "Delegated lanes",
        value: `${delegatedLaneCount}`,
        detail: delegatedLaneCount > 0 ? "Hermes/OpenClaw sessions in flight" : "No live delegated lane right now",
        tone: delegatedLaneCount > 0 ? "neutral" : "warn",
      },
      {
        id: "harness",
        label: "Production harness",
        value: titleizeToken(productionHarness),
        detail: snapshot?.harnessLab?.recommendation || "Harness comparison is visible in Builder.",
        tone: blockedCount > 0 ? "warn" : "good",
      },
    ],
    activeConversations,
    roots,
    workspaceHealth,
    projectProgressHistory,
    contextRoots,
    subAgentLanes,
    nexuses,
    whileAway,
    nextUp,
    stuckThreads,
    winningRoutes,
    changedWhileAway,
    predictedCheckpoints,
    selectedFocus: mission
      ? {
          missionId: mission.mission_id,
          title: mission.title || mission.objective || "Mission",
          current: deriveCurrentTask(mission),
          next: deriveNextCheckpoint(mission),
          lastMovement: deriveMissionLastMovement(mission),
          proof: deriveVerificationSummary(mission),
          updatedAt: deriveMissionLatestTimestamp(mission),
        }
      : null,
  };
}

function priorityTone(priority) {
  const normalized = String(priority || "").toLowerCase();
  if (normalized === "high") {
    return "bad";
  }
  if (normalized === "medium") {
    return "warn";
  }
  if (normalized === "low") {
    return "good";
  }
  return "neutral";
}

function actionForGuidancePanel(panel) {
  const normalized = String(panel || "").toLowerCase();
  if (normalized === "auth") {
    return "open_auth";
  }
  if (normalized === "setup") {
    return "open_runtime";
  }
  if (normalized === "guidance") {
    return "open_profiles";
  }
  if (normalized === "projects") {
    return "open_workspace";
  }
  if (normalized === "missions") {
    return "open_mission";
  }
  if (normalized === "integrations") {
    return "open_escalation";
  }
  if (normalized === "builder_view" || normalized === "builder") {
    return "open_builder";
  }
  if (normalized === "skill_studio" || normalized === "skills") {
    return "open_skills";
  }
  return "open_builder";
}

function deriveTutorialStudio({
  mission,
  snapshot,
  setupHealth,
  profileId,
  workflowStudio,
}) {
  const onboarding = snapshot?.onboarding || {};
  const guidance = snapshot?.guidance || {};
  const tutorial = onboarding?.tutorial || {};
  const completedSteps = asList(tutorial?.completedSteps);
  const steps = asList(tutorial?.steps).map((item, index) => {
    const status = String(
      item?.status ||
        (completedSteps.includes(item?.step_id)
          ? "completed"
          : item?.step_id === tutorial?.currentStepId
            ? "current"
            : "pending"),
    ).toLowerCase();
    return {
      id: item?.step_id || `step-${index}`,
      title: item?.title || `Step ${index + 1}`,
      description: item?.description || "",
      panel: item?.panel || "Builder",
      status: titleizeToken(status),
      done: status === "completed",
      current: status === "current" || status === "in_progress" || item?.step_id === tutorial?.currentStepId,
      tone: status === "completed" ? "good" : status === "pending" ? "neutral" : "warn",
      actionId: actionForGuidancePanel(item?.panel),
    };
  });
  const currentStep =
    steps.find(item => item.current) ||
    steps.find(item => !item.done) ||
    steps[steps.length - 1] ||
    null;
  const motionMode =
    snapshot?.profiles?.details?.[profileId]?.ui?.motion ||
    asList(guidance?.profileChoices).find(item => item?.name === profileId)?.motion ||
    "standard";
  const readiness = uniq([
    ...asList(onboarding?.nextActions),
    ...asList(setupHealth?.blockerExplanations),
  ]).slice(0, 4);
  const cards = asList(guidance?.guidanceCards)
    .slice(0, 4)
    .map(item => ({
      id: item?.card_id || item?.title || "guide",
      title: item?.title || "Guidance",
      body: item?.body || "",
      panel: item?.panel || "Builder",
      kind: titleizeToken(item?.kind || "guide"),
      actionId: actionForGuidancePanel(item?.panel || item?.kind),
    }));
  const improvements = asList(guidance?.productImprovements)
    .slice(0, 3)
    .map(item => ({
      id: item?.item_id || item?.title || "improvement",
      title: item?.title || "Improvement",
      reason: item?.reason || "",
      priority: titleizeToken(item?.priority || "medium"),
      category: titleizeToken(item?.category || "product"),
      tone: priorityTone(item?.priority),
    }));

  return {
    headline: tutorial?.isComplete ? "Tutorial complete" : currentStep?.title || "Finish guided setup",
    summary: tutorial?.isComplete
      ? "Builder is ready for real mission work. Keep the guide nearby for deliberate setup and escalation."
      : currentStep?.description ||
        "Finish the guided path so Builder, runtime policy, and escalation all stay coherent.",
    progressLabel: `${completedSteps.length}/${Math.max(steps.length, 1)} complete`,
    currentStep,
    steps,
    cards,
    improvements,
    readiness,
    motionMode: titleizeToken(motionMode),
    recommendedWorkflow: workflowStudio?.recommended?.label || "Long-Run Agent Session",
    primaryActionId: currentStep?.actionId || "open_mission",
    primaryActionLabel:
      currentStep?.panel ? `Open ${currentStep.panel}` : mission ? "Keep building" : "Launch first mission",
  };
}

function deriveRecommendationStudio({
  mission,
  workspace,
  setupHealth,
  serviceStudio,
  skillStudio,
  workflowStudio,
  qualityRoadmap,
  builderBoard,
}) {
  const struggleSignals = [];
  const approvalCount = asInt(asList(mission?.proof?.pending_approvals).length);
  const verificationCount = asInt(asList(mission?.state?.verification_failures).length);
  const serviceAttention = asInt(serviceStudio?.summary?.needsAttentionCount);
  const skillAttention = asInt(skillStudio?.summary?.needsTestCount);

  if (approvalCount > 0) {
    struggleSignals.push({
      id: "approval-friction",
      label: "Approval friction",
      detail: `${approvalCount} approval boundary is slowing the loop right now.`,
      tone: "warn",
      actionId: "open_queue",
    });
  }
  if (verificationCount > 0) {
    struggleSignals.push({
      id: "verification-friction",
      label: "Verification friction",
      detail: `${verificationCount} failed verification signal needs proof-first attention.`,
      tone: "bad",
      actionId: "open_proof",
    });
  }
  if (serviceAttention > 0) {
    struggleSignals.push({
      id: "runtime-drift",
      label: "Runtime drift",
      detail: `${serviceAttention} runtime or service item still needs repair or review.`,
      tone: "warn",
      actionId: "open_runtime",
    });
  }
  if (skillAttention > 0) {
    struggleSignals.push({
      id: "skill-gap",
      label: "Skill coverage gap",
      detail: `${skillAttention} skill pack(s) still need tests or promotion before they can be trusted.`,
      tone: "warn",
      actionId: "open_skills",
    });
  }
  if (struggleSignals.length === 0) {
    struggleSignals.push({
      id: "clear-lane",
      label: "No major blocker",
      detail: "Use the recommended workflow and keep Builder focused on the highest-value active conversation.",
      tone: "good",
      actionId: "open_mission",
    });
  }

  const skillRecommendations = uniq([
    ...asList(workspace?.skillRecommendations).map(item => `${item?.label || "Skill"}||${item?.reason || ""}`),
    ...skillStudio.recommended.map(item => `${item?.label || "Pack"}||${item?.description || ""}`),
  ])
    .slice(0, 4)
    .map((item, index) => {
      const [label, reason] = String(item).split("||");
      return {
        id: `skill-recommendation-${index}-${label}`,
        label,
        reason,
      };
    });

  const nextMoves = uniq([
    ...asList(qualityRoadmap?.tracks)
      .filter(item => item?.state !== "done")
      .slice(0, 3)
      .map(item => `${item?.label || "Next move"}||${item?.suggestedAction || "Open"}||${item?.actionKind || ""}`),
    workflowStudio?.recommended?.label
      ? `${workflowStudio.recommended.label}||Recommended workflow for the current profile||workflow`
      : "",
    asList(setupHealth?.blockerExplanations)[0]
      ? `${asList(setupHealth?.blockerExplanations)[0]}||Resolve setup blocker before long unattended runs||runtime`
      : "",
  ])
    .slice(0, 4)
    .map((item, index) => {
      const [label, detail, actionKind] = String(item).split("||");
      return {
        id: `recommendation-next-${index}`,
        label,
        detail,
        actionId:
          actionKind === "validate"
            ? "run_validation"
            : actionKind === "workflow"
              ? "open_workflow"
              : actionKind === "skill"
                ? "open_skills"
                : actionKind === "service" || actionKind === "runtime"
                  ? "open_runtime"
                  : "open_mission",
      };
    });

  return {
    headline:
      workflowStudio?.recommended?.label || "Builder recommendations",
    summary:
      builderBoard.activeConversations.length > 0
        ? "Recommendations adapt to the active conversations, current blockers, and the packs that still need work."
        : "Recommendations are based on setup state, workflow readiness, and the gaps still blocking a strong first run.",
    struggleSignals: struggleSignals.slice(0, 4),
    skillRecommendations,
    nextMoves,
    learningQueue: asList(workflowStudio?.learningQueue).slice(0, 4).map((item, index) => ({
      id: `learning-${index}-${item?.title || item}`,
      title: item?.title || listLabel(item),
      priority: titleizeToken(item?.priority || "medium"),
      tone: priorityTone(item?.priority),
    })),
    activeConversationCount: builderBoard.activeConversations.length,
    blockedConversationCount: builderBoard.activeConversations.filter(item => item.blocked).length,
    recommendedSurface: titleizeToken(workflowStudio?.recommended?.surface || "builder_view"),
  };
}

function deriveMissionWatchdog(snapshot) {
  const source = snapshot?.missionWatchdog || snapshot?.mission_watchdog || null;
  if (!source || typeof source !== "object") {
    return null;
  }
  const supervisor = source.supervisor || source.supervisor_state || {};
  const problemRegistrySource = source.problemRegistry || source.problem_registry || {};
  const problems = asList(problemRegistrySource.problems || source.problems).map((problem, index) => ({
    ...problem,
    problemId: problem?.problemId || problem?.problem_id || problem?.id || `watchdog-problem-${index}`,
    status: problem?.status || "open",
    kind: problem?.kind || problem?.type || "watchdog_problem",
    severity: problem?.severity || problem?.tone || "warn",
    firstRepairStep: problem?.firstRepairStep || problem?.first_repair_step || problem?.firstStep || "",
  }));
  const firstOpenProblem =
    problems.find(problem => !["closed", "resolved", "dismissed"].includes(String(problem?.status || "open").toLowerCase())) ||
    null;
  const cadencePolicy =
    source.cadencePolicy ||
    source.cadence_policy ||
    supervisor.cadencePolicy ||
    supervisor.cadence_policy ||
    {};
  const loopIntervalSeconds = asInt(
    source.loopIntervalSeconds ??
      source.loop_interval_seconds ??
      supervisor.loopIntervalSeconds ??
      supervisor.loop_interval_seconds ??
      supervisor.intervalSeconds ??
      supervisor.interval_seconds ??
      0,
  );
  const loopStatus =
    source.loopStatus ||
    source.loop_status ||
    supervisor.loopStatus ||
    supervisor.loop_status ||
    supervisor.status ||
    "unknown";
  return {
    ...source,
    supervisorSchema:
      source.supervisorSchema ||
      source.supervisor_schema ||
      supervisor.supervisorSchema ||
      supervisor.supervisor_schema ||
      supervisor.schema ||
      "",
    loopActive: asBooleanFlag(
      source.loopActive ??
        source.loop_active ??
        supervisor.loopActive ??
        supervisor.loop_active ??
        supervisor.active,
    ),
    loopStatus,
    loopMode: source.loopMode || source.loop_mode || supervisor.mode || supervisor.loopMode || "watchdog",
    loopNextRunAt:
      source.loopNextRunAt ||
      source.loop_next_run_at ||
      supervisor.loopNextRunAt ||
      supervisor.loop_next_run_at ||
      supervisor.nextRunAt ||
      supervisor.next_run_at ||
      "",
    loopIntervalSeconds,
    loopRunsCompleted: asInt(
      source.loopRunsCompleted ??
        source.loop_runs_completed ??
        supervisor.runsCompleted ??
        supervisor.runs_completed ??
        supervisor.runCount ??
        supervisor.run_count ??
        0,
    ),
    cadencePolicy,
    problemRegistry: {
      ...problemRegistrySource,
      problems,
      openProblemCount: asInt(
        problemRegistrySource.openProblemCount ??
          problemRegistrySource.open_problem_count ??
          problems.filter(problem => !["closed", "resolved", "dismissed"].includes(String(problem?.status || "open").toLowerCase())).length,
      ),
      newProblemCount: asInt(problemRegistrySource.newProblemCount ?? problemRegistrySource.new_problem_count ?? 0),
      resolvedProblemCount: asInt(
        problemRegistrySource.resolvedProblemCount ?? problemRegistrySource.resolved_problem_count ?? 0,
      ),
      nextAction:
        problemRegistrySource.nextAction ||
        problemRegistrySource.next_action ||
        firstOpenProblem?.firstRepairStep ||
        "",
    },
    firstOpenProblem,
    issueCount: asInt(source.issueCount ?? source.issue_count ?? asList(source.issues).length),
    queuePressure: asInt(source.queuePressure ?? source.queue_pressure ?? 0),
    queuePressureSafe: asInt(source.queuePressureSafe ?? source.queue_pressure_safe ?? 0),
    queuePressureUnknown: asInt(source.queuePressureUnknown ?? source.queue_pressure_unknown ?? 0),
    queuePressureOverlap: asInt(source.queuePressureOverlap ?? source.queue_pressure_overlap ?? 0),
    artifactReady: asInt(source.artifactReady ?? source.artifact_ready ?? 0),
    artifactPartial: asInt(source.artifactPartial ?? source.artifact_partial ?? 0),
    artifactMissing: asInt(source.artifactMissing ?? source.artifact_missing ?? 0),
    artifactUnplanned: asInt(source.artifactUnplanned ?? source.artifact_unplanned ?? 0),
    artifactEntryPoints: asList(source.artifactEntryPoints || source.artifact_entry_points),
  };
}

function deriveMissionArtifactEntrypoints(missionWatchdog) {
  return asList(missionWatchdog?.artifactEntryPoints || missionWatchdog?.artifact_entry_points).map((entry, index) => ({
    id: entry?.id || entry?.missionId || entry?.mission_id || `artifact-entry-${index}`,
    missionId: entry?.missionId || entry?.mission_id || "",
    label: entry?.label || entry?.title || entry?.missionTitle || entry?.mission_title || "Mission artifacts",
    path: entry?.path || entry?.artifactPath || entry?.artifact_path || "",
    status: entry?.status || entry?.readinessStatus || entry?.readiness_status || "unknown",
    detail: entry?.detail || entry?.summary || "",
  }));
}

function deriveBuilderArtifactReadiness(missionWatchdog) {
  const artifactReadiness = missionWatchdog?.artifactReadiness || missionWatchdog?.artifact_readiness || {};
  const entryPoints = deriveMissionArtifactEntrypoints(missionWatchdog);
  return {
    schema: "fluxio.builder_artifact_readiness.v1",
    status:
      missionWatchdog?.artifactMissing > 0
        ? "missing"
        : missionWatchdog?.artifactPartial > 0
          ? "partial"
          : missionWatchdog
            ? "ready"
            : "unknown",
    ready: asInt(missionWatchdog?.artifactReady ?? 0),
    partial: asInt(missionWatchdog?.artifactPartial ?? 0),
    missing: asInt(missionWatchdog?.artifactMissing ?? 0),
    unplanned: asInt(missionWatchdog?.artifactUnplanned ?? 0),
    byMission: artifactReadiness,
    entryPoints,
  };
}

function deriveLiveReviewStudio({
  mission,
  workspace,
  snapshot,
  previewMode,
  liveSyncSeconds,
  liveSyncSuspended,
  lastPushReason,
  isRefreshing,
  builderBoard,
}) {
  const bridgeSessions = asList(snapshot?.bridgeLab?.connectedSessions);
  const missionWatchdog = deriveMissionWatchdog(snapshot);
  const builderArtifactReadiness = deriveBuilderArtifactReadiness(missionWatchdog);
  const missionFiles = deriveChanged(mission, workspace).slice(0, 3);
  const reviewTargets = [];

  reviewTargets.push({
    id: "review-preview",
    label: previewMode === "live" ? "Live surface" : "Fixture surface",
    title: previewMode === "live" ? "Live Builder review" : previewLabel(previewMode, snapshot?.previewMeta),
    detail:
      previewMode === "live"
        ? liveSyncSuspended
          ? "Live sync is paused while the surface is hidden."
          : lastPushReason
            ? `Latest backend push: ${lastPushReason}.`
            : "Live backend state is active for review."
        : "Fixture mode is active for repeatable review and screenshot work.",
    tone: previewMode === "live" ? (liveSyncSuspended ? "warn" : "good") : "neutral",
    actionId: "open_builder",
    commentSeed:
      previewMode === "live"
        ? "Live UI review note for the current Builder surface:\nWhat feels wrong:\nWhat should change:\n"
        : "Fixture review note:\nThis scenario should read differently because \n",
  });

  if (mission) {
    reviewTargets.push({
      id: `review-mission-${mission?.mission_id || "current"}`,
      label: "Mission focus",
      title: mission?.title || mission?.objective || "Current mission",
      detail: `${deriveCurrentTask(mission)} · Next ${deriveNextCheckpoint(mission)}`,
      tone: missionNeedsAttention(mission) ? "warn" : missionStatusTone(mission?.state?.status),
      actionId: "focus_thread",
      commentSeed: `Mission UI review for ${mission?.title || "the current mission"}:\nThis decision point should look different because \n`,
    });
  }

  if (builderBoard.activeConversations.length > 1) {
    reviewTargets.push({
      id: "review-conversations",
      label: "Conversation grid",
      title: `${builderBoard.activeConversations.length} active conversations`,
      detail: `${builderBoard.activeConversations.filter(item => item.blocked).length} blocked · ${builderBoard.activeConversations.length - 1} secondary thread card(s) visible.`,
      tone: builderBoard.activeConversations.some(item => item.blocked) ? "warn" : "good",
      actionId: "focus_conversations",
      commentSeed: "Conversation board review:\nWhich thread deserves more visual weight and why:\n",
    });
  }

  for (const [index, item] of bridgeSessions.slice(0, 2).entries()) {
    reviewTargets.push({
      id: item?.session_id || `review-bridge-${index}`,
      label: titleizeToken(item?.bridge_transport || "bridge"),
      title: item?.app_name || "Connected app",
      detail:
        asList(item?.context_preview).map(entry => entry?.summary).find(Boolean) ||
        item?.latest_task_result?.resultSummary ||
        "Connected app review target is ready.",
      tone: item?.bridge_health === "healthy" ? "good" : "warn",
      actionId: "open_runtime",
      commentSeed: `Bridge review for ${item?.app_name || "this app"}:\nThis hand-off or preview block should change because \n`,
    });
  }

  for (const [index, file] of missionFiles.entries()) {
    reviewTargets.push({
      id: `review-file-${index}-${file}`,
      label: "Changed file",
      title: file,
      detail: "Use this as a review anchor when pointing at what should change in the live UI flow.",
      tone: "neutral",
      actionId: "open_proof",
      commentSeed: `Review note for ${file}:\nThe visible UI behavior should change like this:\n`,
    });
  }

  const previewUrl = mission?.state?.last_preview_url || mission?.state?.preview_url || "No preview URL captured";
  const screenshotPath =
    mission?.proof?.latest_screenshot_path || mission?.state?.last_screenshot_path || "screenshots/latest.png";
  const verificationStep =
    asList(mission?.state?.verification_failures).length > 0 ? "Verification blocked by failing checks" : "Verification checks in progress";
  const imageArtifacts = asList(mission?.proof?.artifacts)
    .map(item => item?.path || item?.artifact_path || "")
    .filter(Boolean)
    .slice(0, 2);
  const nowDate = new Date();
  const nowTimestamp = nowDate.toISOString();
  const progressWindow =
    mission?.state?.last_progress_update_at || mission?.state?.updated_at || mission?.updated_at || mission?.created_at || "";
  const progressWindowDate = progressWindow ? new Date(progressWindow) : null;
  const progressWindowAgeMinutes =
    progressWindowDate && Number.isFinite(progressWindowDate.getTime())
      ? Math.max(0, Math.round((nowDate.getTime() - progressWindowDate.getTime()) / 60000))
      : null;
  const progressCadenceState =
    progressWindowAgeMinutes == null
      ? "missing"
      : progressWindowAgeMinutes <= 20
        ? "healthy"
        : progressWindowAgeMinutes <= 35
          ? "stale"
          : "overdue";
  const runtimeActivitySignals = uniq(
    asList(snapshot?.activity)
      .slice(0, 10)
      .map(item => item?.message || item?.kind || "")
      .filter(Boolean),
  ).slice(0, 4);
  const latestPlanRevision = asList(mission?.plan_revisions).slice(-1)[0] || {};
  const plannerSelectedSkills = uniq([
    ...asList(latestPlanRevision?.selected_skills),
    ...asList(latestPlanRevision?.selectedSkills),
    ...asList(mission?.state?.selected_skills),
    ...asList(mission?.state?.selectedSkills),
  ]).slice(0, 6);
  const plannerRules = uniq([
    ...asList(latestPlanRevision?.rules),
    ...asList(latestPlanRevision?.guardrails),
    ...asList(mission?.state?.rules),
    ...asList(mission?.state?.guardrails),
  ]).slice(0, 5);
  const plannerDesignPrompts = uniq([
    ...asList(latestPlanRevision?.design_prompts),
    ...asList(latestPlanRevision?.designPrompts),
    ...asList(mission?.state?.design_prompts),
    ...asList(mission?.state?.designPrompts),
  ]).slice(0, 4);
  const plannerNextIdea =
    latestPlanRevision?.next_idea ||
    latestPlanRevision?.nextIdea ||
    mission?.state?.next_idea ||
    mission?.state?.nextIdea ||
    "No next-idea handoff captured yet.";
  const latestStructuredFeedbackReceiptRaw = asList(snapshot?.connectedDeviceBridge?.receipts)
    .slice()
    .reverse()
    .find(receipt => receipt?.receiptKind === "live_review_structured_feedback") || null;
  const latestStructuredFeedbackReceipt = latestStructuredFeedbackReceiptRaw
    ? {
        receiptKind: "live_review_structured_feedback",
        eventId: latestStructuredFeedbackReceiptRaw.eventId || latestStructuredFeedbackReceiptRaw.event_id || "",
        plannerExecutorHandoffId:
          latestStructuredFeedbackReceiptRaw.plannerExecutorHandoffId ||
          latestStructuredFeedbackReceiptRaw.planner_executor_handoff_id ||
          "",
        nextIdea: latestStructuredFeedbackReceiptRaw.nextIdea || latestStructuredFeedbackReceiptRaw.next_idea || "",
        timestamp: latestStructuredFeedbackReceiptRaw.timestamp || "",
        status: latestStructuredFeedbackReceiptRaw.status || "received",
      }
    : null;
  const structuredFeedbackReceipt = latestStructuredFeedbackReceipt;
  const decisionInfluence = [
    {
      id: "skills-to-layout",
      source: plannerSelectedSkills.length > 0 ? plannerSelectedSkills.map(titleizeToken).join(" · ") : "No selected skill captured",
      appliedTo: "UI hierarchy and mobile-safe component density",
      evidence: plannerDesignPrompts[0] || "Design prompt not captured yet",
      verifierFeedback: asList(mission?.state?.verification_failures)[0] || "No verifier objection recorded",
    },
    {
      id: "rules-to-execution",
      source: plannerRules.length > 0 ? plannerRules.join(" · ") : "Default planner guardrails",
      appliedTo: "Executor scope, route preservation, and proof collection",
      evidence: plannerNextIdea,
      verifierFeedback: verificationStep,
    },
  ];
  const internalSupervisorState = snapshot?.internalContinuationSupervisor || {};
  const continuationSupervisor = {
    enabled: internalSupervisorState.enabled !== false,
    hardenedHarness: true,
    state:
      mission?.state?.continuation_reconcile_decision ||
      internalSupervisorState.lastDecision ||
      mission?.missionLoop?.continuityState ||
      mission?.state?.continuity_state ||
      (mission?.state?.status === "running" ? "active" : mission ? "queued" : "idle"),
    lastCompletionAt:
      mission?.state?.continuation_completed_at ||
      mission?.missionLoop?.lastCompletionAt ||
      mission?.state?.last_delegate_completed_at ||
      mission?.state?.updated_at ||
      "",
    reconcileRecordedAt:
      mission?.state?.continuation_dispatch_at || internalSupervisorState.lastDispatchAt || internalSupervisorState.lastRunAt || "",
    expectedDispatchWindowMinutes: "0-2",
    dispatchLagMinutes:
      Number.isFinite(progressWindowAgeMinutes) && progressWindowAgeMinutes >= 0
        ? progressWindowAgeMinutes
        : null,
    failureReason:
      mission?.state?.continuation_reconcile_reason ||
      internalSupervisorState.lastSkippedReason ||
      mission?.missionLoop?.continuityDetail ||
      mission?.state?.continuity_detail ||
      (mission ? "No immediate-continuation failure recorded." : "No active mission to supervise."),
    reconcileLatencyMs:
      asInt(
        mission?.state?.continuation_reconcile_latency_ms ??
          internalSupervisorState.lastContinuationLatencyMs ??
          0,
      ),
    blockerReason:
      mission?.state?.blocker_classification?.reason ||
      internalSupervisorState.lastSkippedReason ||
      mission?.state?.continuation_reconcile_reason ||
      "",
    externalHeartbeatRequired: Boolean(internalSupervisorState.externalHeartbeatRequired),
    safeToStop: Boolean(mission?.missionLoop?.safeToStop || mission?.state?.safe_to_stop),
    budgetGuard: mission?.run_budget?.run_until_behavior || mission?.state?.run_until_behavior || "pause_on_failure",
    routePreservation: {
      selectedSkills: plannerSelectedSkills,
      designPrompts: plannerDesignPrompts,
      nextIdea: plannerNextIdea,
      model:
        mission?.model_route?.executor?.model ||
        mission?.model_route?.planner?.model ||
        mission?.state?.model ||
        "unrecorded",
      provider:
        mission?.model_route?.executor?.provider ||
        mission?.model_route?.planner?.provider ||
        mission?.state?.model_provider ||
        "unrecorded",
      effort:
        mission?.model_route?.executor?.effort ||
        mission?.model_route?.planner?.effort ||
        mission?.state?.model_effort ||
        "unrecorded",
      executionRoot:
        mission?.execution_scope?.execution_root || mission?.state?.execution_root || workspace?.root_path || "unrecorded",
    },
  };

  const events = [
    {
      id: "evt-file-change",
      kind: "file_change",
      label: "File changes",
      title: missionFiles[0] || "No tracked file changes yet",
      detail: missionFiles.length > 0 ? `${missionFiles.join(" · ")}` : "Run a mission to capture changed paths.",
      tone: missionFiles.length > 0 ? "good" : "neutral",
      timestamp: progressWindow,
      artifactPaths: missionFiles,
      source: "workspace_diff",
    },
    {
      id: "evt-browser-qa",
      kind: "browser_qa",
      label: "Browser QA",
      title: "Browser-use actions",
      detail: `Preview URL: ${previewUrl}`,
      tone: previewMode === "live" ? "good" : "neutral",
      timestamp: nowTimestamp,
      previewUrl,
      browserActions: ["open_page", "audit_layout", "report_issue"],
      deepLink: { type: "review_target", targetId: reviewTargets[0]?.id || "" },
    },
    {
      id: "evt-computer-use",
      kind: "computer_use",
      label: "Computer-use",
      title: "Program launch and handoff",
      detail:
        mission?.state?.current_runtime_lane || mission?.runtime_id
          ? `Lane ${mission?.state?.current_runtime_lane || mission?.runtime_id} active`
          : "No runtime lane reported yet",
      tone: mission?.state?.current_runtime_lane || mission?.runtime_id ? "good" : "warn",
      timestamp: nowTimestamp,
      launchedPrograms: asList(mission?.state?.launched_programs).slice(0, 3),
      runtimeActivity: runtimeActivitySignals,
      deepLink: { type: "drawer", drawerId: "runtime" },
    },
    {
      id: "evt-screenshot",
      kind: "preview_refresh",
      label: "Preview refresh",
      title: "Screenshot and preview sync",
      detail: `Latest screenshot artifact: ${screenshotPath}`,
      tone: liveSyncSuspended ? "warn" : "good",
      timestamp: mission?.state?.last_preview_refresh_at || nowTimestamp,
      screenshotFrames: [
        {
          id: "frame-latest",
          label: "Latest",
          path: screenshotPath,
          thumbnailPath: screenshotPath,
          timestamp: mission?.state?.last_preview_refresh_at || nowTimestamp,
        },
        {
          id: "frame-previous",
          label: "Previous",
          path: mission?.state?.previous_screenshot_path || "screenshots/previous.png",
          thumbnailPath: mission?.state?.previous_screenshot_path || "screenshots/previous.png",
          timestamp: mission?.state?.previous_preview_refresh_at || mission?.updated_at || nowTimestamp,
        },
      ],
    },
    {
      id: "evt-verification",
      kind: "verification",
      label: "Verification",
      title: "Test and gate checks",
      detail: verificationStep,
      tone: asList(mission?.state?.verification_failures).length > 0 ? "bad" : "warn",
      timestamp: mission?.state?.last_verification_at || nowTimestamp,
      tests:
        asList(mission?.proof?.passed_checks).length > 0
          ? asList(mission?.proof?.passed_checks).slice(0, 4)
          : ["python -m compileall -q src", "frontend build pending"],
      deepLink: { type: "drawer", drawerId: "proof" },
    },
    {
      id: "evt-image-playground",
      kind: "image_playground",
      label: "Image Playground",
      title: "Provider route, queue timeline, and layer handoff",
      detail: imageArtifacts.length > 0 ? `Artifacts: ${imageArtifacts.join(" · ")}` : "Awaiting generated image artifacts",
      tone: imageArtifacts.length > 0 ? "good" : "neutral",
      timestamp: mission?.state?.last_image_event_at || nowTimestamp,
      queueTimeline: ["queued", "provider", "layer_handoff", "artifact", "verified"],
      providerEvents: ["provider_selected", "image_generated", "artifact_registered"],
      layerHandoff: ["prompt_layer", "render_layer", "artifact_layer"],
      generatedImages:
        imageArtifacts.length > 0
          ? imageArtifacts.map(path => ({ path, label: path.split("/").slice(-1)[0] || "artifact" }))
          : [{ path: "screenshots/latest.png", label: "latest.png" }],
      artifactPaths: imageArtifacts,
    },
    {
      id: "evt-operator-followup",
      kind: "operator_followup",
      label: "Operator follow-up",
      title: "Messages and acknowledgements",
      detail:
        asList(mission?.state?.operator_notes).length > 0
          ? `${asList(mission?.state?.operator_notes).length} follow-up note(s) recorded`
          : "No operator follow-up message recorded yet",
      tone: asList(mission?.state?.operator_notes).length > 0 ? "good" : "neutral",
      timestamp: mission?.state?.last_operator_note_at || nowTimestamp,
      operatorMessages: asList(mission?.state?.operator_notes).slice(0, 3),
      acknowledgedBy: asList(mission?.state?.operator_acks).slice(0, 3),
    },
    {
      id: "evt-progress-window",
      kind: "progress_update",
      label: "10-20 min update",
      title: "Periodic progress snapshot",
      detail:
        mission
          ? `Changed: ${missionFiles[0] || "none"} · Blocker: ${asList(mission?.state?.verification_failures)[0] || "none"} · Next: ${deriveNextCheckpoint(mission)}`
          : "Progress updates appear every 10-20 minutes once a mission is running.",
      tone: mission ? "warn" : "neutral",
      timestamp: progressWindow || nowTimestamp,
      cadenceMinutes: "10-20",
      cadenceState: progressCadenceState,
      cadenceAgeMinutes: progressWindowAgeMinutes,
      progressUpdate: {
        changed: missionFiles[0] || "none",
        blocker: asList(mission?.state?.verification_failures)[0] || "none",
        tests:
          asList(mission?.proof?.passed_checks).length > 0
            ? mission.proof.passed_checks.slice(0, 2).join(" · ")
            : "pending",
        next: mission ? deriveNextCheckpoint(mission) : "Start mission",
      },
      selectedSkills: plannerSelectedSkills,
      plannerRules,
      designPrompts: plannerDesignPrompts,
      nextIdea: plannerNextIdea,
      structuredFeedbackReceipt,
    },
    {
      id: "evt-runtime-activity",
      kind: "runtime_activity",
      label: "Runtime activity",
      title: "Recent tool and lane actions",
      detail:
        runtimeActivitySignals.length > 0
          ? runtimeActivitySignals.join(" · ")
          : "No runtime activity stream captured yet.",
      tone: runtimeActivitySignals.length > 0 ? "good" : "neutral",
      timestamp: asList(snapshot?.activity)[0]?.timestamp || nowTimestamp,
      runtimeActivity: runtimeActivitySignals,
      deepLink: { type: "drawer", drawerId: "context" },
    },
    {
      id: "evt-continuation-supervisor",
      kind: "continuation_supervisor",
      label: "Internal supervisor",
      title: "Immediate continuation reconcile",
      detail: `State ${titleizeToken(continuationSupervisor.state)} · dispatch window ${continuationSupervisor.expectedDispatchWindowMinutes}m`,
      tone:
        continuationSupervisor.state === "failed" || continuationSupervisor.state === "stale"
          ? "bad"
          : continuationSupervisor.state === "queued"
            ? "warn"
            : "good",
      timestamp: continuationSupervisor.lastCompletionAt || nowTimestamp,
      continuationSupervisor,
      selectedSkills: continuationSupervisor.routePreservation.selectedSkills,
      designPrompts: continuationSupervisor.routePreservation.designPrompts,
      nextIdea: continuationSupervisor.routePreservation.nextIdea,
      structuredFeedbackReceipt,
      deepLink: { type: "drawer", drawerId: "context" },
    },
    {
      id: "evt-replay",
      kind: "replay_marker",
      label: "Replay marker",
      title: "Rewind and timelapse snapshot",
      detail:
        asList(builderBoard?.nexuses || builderBoard?.nexus).length > 0
          ? `${asList(builderBoard?.nexuses || builderBoard?.nexus).length} timeline marker(s) available for replay`
          : "No timeline markers yet",
      tone: asList(builderBoard?.nexuses || builderBoard?.nexus).length > 0 ? "good" : "neutral",
      timestamp: nowTimestamp,
      replayMarkers: asList(builderBoard?.nexuses || builderBoard?.nexus)
        .slice(0, 3)
        .map((item, index) => ({
          id: item?.id || `marker-${index}`,
          label: item?.title || item?.label || "marker",
          timestamp: item?.updatedAt || item?.timestamp || nowTimestamp,
          snapshotPath: item?.artifactPath || item?.path || screenshotPath,
          frameId: index === 0 ? "frame-latest" : "frame-previous",
          deepLink: {
            proofTarget: item?.proofId || mission?.id || "",
            threadTarget: item?.threadId || mission?.mission_id || mission?.id || "",
          },
        })),
    },
  ];

  const annotationReadiness = {
    enabled: true,
    blocks: [
      {
        id: "anno-home-hero",
        label: "Hero layout",
        severity: "high",
        note: "CTA stack overlaps in compact width; preserve hierarchy and spacing rhythm.",
        recoveryAction: "Reduce heading width, keep CTA buttons stacked with safe gap.",
        page: "landing",
        rectangle: { x: 6, y: 14, width: 88, height: 34, layer: "preview" },
      },
      {
        id: "anno-right-panel",
        label: "Live panel card",
        severity: "medium",
        note: "Queue chips become dense during long runs; trim microcopy before wrapping.",
        recoveryAction: "Collapse details under a disclosure after 3 visible lines.",
        page: "review-panel",
        rectangle: { x: 54, y: 48, width: 42, height: 42, layer: "live-review" },
      },
      {
        id: "anno-operator-pin",
        label: "Operator follow-up pin",
        severity: "low",
        note: "Acknowledge follow-up quickly so mission thread and review panel stay in sync.",
        recoveryAction: "Auto-add acknowledgement row after send succeeds.",
        page: "operator-thread",
        pin: { x: 80, y: 26, layer: "sidebar" },
      },
    ],
  };

  return {
    headline: "Live UI review",
    summary:
      "Pick a visible block, annotate what feels wrong, and push the feedback back into the mission without leaving Builder.",
    statusLine:
      previewMode === "live"
        ? `${isRefreshing ? "Refreshing" : "Live"} · ${liveSyncSeconds === "off" ? "manual sync" : `${liveSyncSeconds}s sync`}`
        : `${previewLabel(previewMode, snapshot?.previewMeta)} · repeatable review`,
    targets: reviewTargets.slice(0, 6),
    compareHint:
      builderBoard.activeConversations.length > 0
        ? "Use live review targets to steer the active mission, then jump back through nexuses if the direction changes."
        : "Use fixture review now, then launch the UI review loop once a real mission is active.",
    events,
    annotationReadiness,
    plannerProof: {
      selectedSkills: plannerSelectedSkills,
      plannerRules,
      designPrompts: plannerDesignPrompts,
      nextIdea: plannerNextIdea,
      structuredFeedbackReceipt,
      latestStructuredFeedbackReceipt,
      decisionInfluence,
    },
    continuationSupervisor,
    missionWatchdog,
    builderArtifactReadiness,
  };
}

function deriveMissionActivityPulse({ mission, workspace, snapshot, pendingQuestions, pendingApprovals }) {
  const delegatedSessions = asList(mission?.delegated_runtime_sessions).filter(
    item => !["completed", "failed", "stopped"].includes(String(item?.status || "").toLowerCase()),
  );
  const approvals = asList(mission?.proof?.pending_approvals).length + asList(pendingApprovals).length;
  const questions = asList(pendingQuestions).length;
  const verificationFailures = asList(mission?.state?.verification_failures).length;
  const changedFiles = deriveChanged(mission, workspace).slice(0, 5);
  const toolMentions = uniq([
    ...asList(mission?.action_history).map(item => item?.proposal?.tool_id || item?.proposal?.toolId || ""),
    ...delegatedSessions.map(item => item?.runtime_id || ""),
    ...asList(snapshot?.activity)
      .slice(0, 20)
      .map(item => {
        const message = String(item?.message || "").toLowerCase();
        if (message.includes("browser")) return "browser";
        if (message.includes("terminal")) return "terminal";
        if (message.includes("pytest") || message.includes("test")) return "tests";
        if (message.includes("build")) return "build";
        return "";
      }),
  ]).slice(0, 6);
  const current = deriveCurrentTask(mission);
  const next = deriveNextCheckpoint(mission);
  const timeline = asList(snapshot?.activity).slice(0, 8);
  const stage =
    mission?.state?.status === "running"
      ? "Executing"
      : mission?.state?.status === "completed"
        ? "Completed"
        : mission?.state?.status === "failed"
          ? "Failed"
          : approvals > 0 || questions > 0
            ? "Awaiting operator"
            : delegatedSessions.length > 0
              ? "Delegating"
              : "Planning";
  const tone =
    mission?.state?.status === "failed"
      ? "bad"
      : verificationFailures > 0 || approvals > 0 || questions > 0
        ? "warn"
        : mission?.state?.status === "completed"
          ? "good"
          : "neutral";

  return {
    stage,
    tone,
    current,
    next,
    changedFiles,
    toolMentions,
    delegatedCount: delegatedSessions.length,
    approvals,
    questions,
    verificationFailures,
    backgroundSummary:
      delegatedSessions[0]?.detail ||
      delegatedSessions[0]?.last_event ||
      (delegatedSessions.length > 0 ? `${delegatedSessions.length} delegated lane(s) active.` : "No delegated lane active."),
    timeline: timeline.map(item => ({
      label: titleizeToken(item?.kind || "activity"),
      message: item?.message || "Activity event",
      timestamp: item?.timestamp || "",
    })),
  };
}

export function buildRecentRuns(snapshot) {
  const missionRuns = asList(snapshot?.missions)
    .slice()
    .reverse()
    .slice(0, 4)
    .map(item => ({
      title: item?.title || item?.objective || "Mission",
      subtitle: `${runtimeLabel(item?.runtime_id)} · ${titleizeToken(item?.state?.status || "run")}`,
      tone: missionStatusTone(item?.state?.status),
    }));

  const harnessRuns = asList(snapshot?.harnessLab?.recentRuns).map(item => ({
    title: `${runtimeLabel(item?.runtimeId)} · ${titleizeToken(item?.autopilotStatus || "run")}`,
    subtitle: item?.harnessId || "Harness",
    tone: missionStatusTone(item?.autopilotStatus),
  }));

  return [...missionRuns, ...harnessRuns].slice(0, 6);
}

export function buildMissionControlModel({
  mission,
  workspace,
  setupHealth,
  snapshot,
  pendingQuestions,
  pendingApprovals,
  telegramReady,
  profileId,
  profileParams,
  inbox,
  previewMode = "live",
  uiMode = "agent",
  lastPushReason = "",
  isRefreshing = false,
  liveSyncSeconds = "off",
  liveSyncSuspended = false,
}) {
  const queueItems = deriveQueueItems(mission, pendingQuestions, pendingApprovals);
  const primaryAction = derivePrimaryAction(mission, queueItems);
  const liveStatus = topBarLiveStatus(mission, pendingQuestions, pendingApprovals);
  const events = deriveEvents(mission, snapshot);
  const inboxPreview = asList(inbox)[0];
  const featureTruth = classifyFeatureTruth({ mission, snapshot, setupHealth, previewMode });
  const confidence = deriveConfidenceSurface({
    mission,
    snapshot,
    setupHealth,
    queueItems,
    pendingQuestions,
    pendingApprovals,
  });
  const profileStudio = deriveProfileStudio(snapshot, workspace, profileId, profileParams);
  const serviceStudio = deriveServiceStudio(workspace, setupHealth);
  const skillStudio = deriveSkillStudio(snapshot, workspace);
  const workflowStudio = deriveWorkflowStudio(snapshot, profileId);
  const builderOps = deriveBuilderOps(workspace);
  const stateAudit = deriveStateAudit({ mission, setupHealth });
  const qualityRoadmap = deriveQualityRoadmap({
    confidence,
    mission,
    setupHealth,
    serviceStudio,
    skillStudio,
    workflowStudio,
    builderOps,
  });
  const builderBoard = deriveBuilderBoard({ mission, workspace, snapshot, confidence, uiMode });
  const tutorialStudio = deriveTutorialStudio({
    mission,
    snapshot,
    setupHealth,
    profileId,
    workflowStudio,
  });
  const recommendationStudio = deriveRecommendationStudio({
    mission,
    workspace,
    setupHealth,
    serviceStudio,
    skillStudio,
    workflowStudio,
    qualityRoadmap,
    builderBoard,
  });
  const proofTone =
    asList(mission?.state?.verification_failures).length > 0
      ? "bad"
      : asList(mission?.proof?.pending_approvals).length > 0
        ? "warn"
        : mission?.state?.status === "completed"
          ? "good"
          : "neutral";

  const proofSections = [
    {
      title: "Files touched",
      items: deriveChanged(mission, workspace),
    },
    {
      title: "Checks and commands",
      items: deriveChecks(mission),
    },
    {
      title: "Artifacts",
      items: deriveArtifacts(mission, inboxPreview),
    },
  ];

  const contextGroups = [
    {
      title: "Guardrails",
      items: [
        {
          label: "Approval mode",
          value: titleizeToken(
            mission?.execution_policy?.approval_mode || profileParams?.approvalStrictness || "tiered",
          ),
        },
        {
          label: "Run until",
          value: titleizeToken(
            mission?.missionLoop?.timeBudget?.runUntilBehavior ||
              mission?.run_budget?.run_until_behavior ||
              profileParams?.autoContinueBehavior ||
              "pause_on_failure",
          ),
          note: resolveMissionPauseReason(mission) || "No active pause",
        },
        {
          label: "Setup blockers",
          value: `${asList(setupHealth?.blockerExplanations).length}`,
          note: asList(setupHealth?.blockerExplanations)[0] || "None",
        },
      ],
    },
    {
      title: "Runtime and scope",
      items: [
        {
          label: "Current lane",
          value: resolveCurrentRuntimeLane(mission),
        },
        {
          label: "Workspace root",
          value: workspace?.root_path || snapshot?.workspaceRoot || "Not selected",
        },
        {
          label: "Execution",
          value: mission?.execution_scope?.execution_root || "Not recorded",
          note: titleizeToken(mission?.execution_scope?.strategy || "direct"),
        },
      ],
    },
    {
      title: "Context",
      items: [
        {
          label: "Profile",
          value: titleizeToken(profileId),
        },
        {
          label: "Known state",
          value: describeMissionKnownState(mission),
        },
        {
          label: "Escalation",
          value: telegramReady ? "Telegram ready" : "Not configured",
          note: inboxPreview?.previewMessage || "",
        },
      ],
    },
    {
      title: "Confidence",
      items: [
        {
          label: "1.0 progress",
          value: confidence.label,
          note: confidence.phase,
        },
        {
          label: "Release status",
          value: confidence.releaseStatus,
          note: confidence.requiredGateSummary.label,
        },
        {
          label: "Quality score",
          value: `${confidence.qualityScore}%`,
          note: confidence.nextActions[0] || "No blocker reported.",
        },
      ],
    },
  ];

  const threadSections = deriveThreadSections({ mission, pendingQuestions, workspace });

  const emptyReadiness = uniq([
    ...asList(setupHealth?.blockerExplanations),
    asList(snapshot?.workspaces).length === 0 ? "Add at least one workspace" : "",
    previewMode !== "live" ? "Preview mode is active; actions are read-only." : "",
  ]);
  const activeAuditCount = stateAudit.filter(item => item.state === "active").length;
  const requiredGateFailures = confidence.gates.filter(
    item => item.required && item.passed === false,
  ).length;
  const builderReviewCount =
    featureTruth.notReady.length +
    activeAuditCount +
    asInt(serviceStudio.summary.needsAttentionCount) +
    asInt(skillStudio.summary.needsTestCount) +
    qualityRoadmap.nextCount +
    qualityRoadmap.blockedCount +
    requiredGateFailures;
  const activityPulse = deriveMissionActivityPulse({
    mission,
    workspace,
    snapshot,
    pendingQuestions,
    pendingApprovals,
  });

  return {
    topBar: {
      liveStatus,
      environmentLabel: deriveEnvironmentLabel(setupHealth, mission, workspace),
      inboxCount:
        queueItems.filter(item => item.tone === "warn" || item.tone === "bad").length +
        asList(inbox).length,
      primaryAction,
      confidence,
    },
    shell: {
      isEmpty: !mission,
      missionLabel: mission ? mission.title || mission.objective : "No mission",
    },
    emptyState: {
      title: "Ready for a focused first mission",
      summary:
        emptyReadiness[0] ||
        "Launch one real mission to replace scaffolding with a thread, proof, and review boundaries.",
      readiness: emptyReadiness.length > 0 ? emptyReadiness : ["Environment appears ready."],
      recommendedAction: primaryAction.label,
      confidenceLabel: confidence.label,
      confidencePhase: confidence.phase,
      qualityRoadmapHeadline: qualityRoadmap.headline,
      recommendedWorkflow:
        workflowStudio?.recommended?.label || "Long-Run Agent Session",
      launchEntryLabel: asList(snapshot?.workspaces).length > 0 ? "Launch mission" : "Add workspace",
    },
    thread: {
      title: mission ? mission.title || mission.objective : "Mission thread",
      objective: mission?.objective || "",
      summary:
        mission?.state?.last_plan_summary ||
        mission?.proof?.summary ||
        "The mission thread captures task, assumptions, operator needs, and proof deltas.",
      status: liveStatus,
      chips: mission
        ? [
            { label: runtimeLabel(mission?.runtime_id), tone: "neutral" },
            { label: titleizeToken(mission?.state?.status || "active"), tone: missionStatusTone(mission?.state?.status) },
            { label: `Elapsed ${deriveElapsed(mission)}`, tone: "neutral" },
            { label: `Remaining ${deriveRemaining(mission)}`, tone: "neutral" },
            {
              label: `${confidence.score}% confidence`,
              tone: confidence.tone,
            },
          ]
        : [],
      sections: threadSections,
      events,
      proofItems: uniq([
        deriveVerificationSummary(mission),
        ...proofSections.flatMap(section => section.items),
      ]).slice(0, 8),
      composerPlaceholder:
        "Write an operator note, scope clarification, or approval rationale for this mission thread.",
      activityPulse,
    },
    drawers: {
      queue: {
        label: "Queue",
        urgent: queueItems.some(item => item.tone === "warn" || item.tone === "bad"),
        count: queueItems.filter(item => item.tone === "warn" || item.tone === "bad").length,
        items: queueItems,
        recommendation: {
          title: describeNextOperatorAction(mission, pendingQuestions),
          reason: queueItems[0]?.reason || "",
        },
      },
      proof: {
        label: "Proof",
        tone: proofTone,
        headline: deriveVerificationSummary(mission),
        diffSummary: deriveDiffSummary(workspace),
        sections: proofSections,
        itemsCount: proofSections.reduce((total, section) => total + section.items.length, 0),
      },
      context: {
        label: "Context",
        count: contextGroups.reduce((total, group) => total + group.items.length, 0),
        groups: contextGroups,
      },
      builder: {
        label: "Builder review",
        reviewCount: builderReviewCount,
        confidence,
        liveSurface: {
          previewMode,
          liveSyncSeconds,
          liveSyncSuspended,
          lastPushReason,
          isRefreshing,
          note:
            previewMode === "live"
              ? liveSyncSuspended
                ? "Live sync paused while the window is hidden."
                : `Live backend${lastPushReason ? ` · last push ${lastPushReason}` : ""}`
              : "Fixture-backed review mode is active.",
        },
        tutorialStudio,
        recommendationStudio,
        liveReviewStudio: checkedLiveReviewProjection(deriveLiveReviewStudio({
          mission,
          workspace,
          snapshot,
          previewMode,
          liveSyncSeconds,
          liveSyncSuspended,
          lastPushReason,
          isRefreshing,
          builderBoard,
        })),
        profileStudio,
        serviceStudio,
        skillStudio,
        workflowStudio,
        gitActions: builderOps.gitActions,
        validationActions: builderOps.validationActions,
        qualityRoadmap,
        featureTruth,
        stateAudit,
        events: events.slice(0, 10),
        board: builderBoard,
        activityPulse,
        mode: uiMode,
      },
    },
  };
}
