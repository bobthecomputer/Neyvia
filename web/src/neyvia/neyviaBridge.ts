import { invoke } from "@tauri-apps/api/core";

type JsonRecord = Record<string, unknown>;

const COMMANDS: Record<string, string> = {
  "mission.start": "start_control_room_mission_command",
  "mission.action": "apply_control_room_mission_action_command",
  "approval.resolve": "resolve_action_approval",
  "workspace.action": "apply_control_room_workspace_action_command",
  "bridge.permission": "set_connected_device_bridge_permission_command",
  "bridge.evaluate": "evaluate_connected_device_bridge_action_command",
  "bridge.planOperation": "plan_connected_device_bridge_operation_command",
  "agent.structuredFeedback": "record_live_review_structured_feedback_command",
  "agent:structured-feedback": "record_live_review_structured_feedback_command",
  "runtimeProof.status": "get_real_agent_runtime_proof_status_command",
  "runtimeProof.run": "run_real_agent_runtime_proof_command",
  "runtimeProof.agentUi": "run_authenticated_live_agent_proof_command",
  "runtimeProof.authenticatedAgentRun": "run_authenticated_live_agent_proof_command",
};

function hasTauriBackend(): boolean {
  return Boolean((globalThis as any).window?.__TAURI__ || (globalThis as any).window?.__TAURI_INTERNALS__);
}

function webBackendBaseUrl(): string {
  const configured =
    (import.meta as any).env?.VITE_FLUXIO_BACKEND_URL ||
    (globalThis as any).window?.__FLUXIO_BACKEND_URL__ ||
    "";
  return String(configured || "").trim().replace(/\/$/, "");
}

async function callNeyviaBackend(command: string, payload: JsonRecord | null = null): Promise<JsonRecord> {
  if (hasTauriBackend()) {
    const result = payload === null ? await invoke(command) : await invoke(command, payload);
    return asRecord(result);
  }

  const response = await fetch(`${webBackendBaseUrl()}/api/backend`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, payload }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result?.ok === false) {
    throw new Error(result?.error || `${command} failed with HTTP ${response.status}`);
  }
  return asRecord(result?.data);
}

function asList(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? (value as JsonRecord[]) : [];
}

function asRecord(value: unknown): JsonRecord {
  if (value && typeof value === "object") {
    return value as JsonRecord;
  }
  return {};
}

export async function getSnapshot(root: string | null = null): Promise<JsonRecord> {
  try {
    const snapshot = await callNeyviaBackend("get_control_room_snapshot_command", {
      payload: { root },
    });
    return asRecord(snapshot);
  } catch {
    return {};
  }
}

export async function dispatchCommand(
  command: string,
  payload: JsonRecord = {},
): Promise<JsonRecord> {
  const tauriCommand = COMMANDS[command];
  if (!tauriCommand) {
    throw new Error(`Unsupported bridge command: ${command}`);
  }
  const result = await callNeyviaBackend(tauriCommand, { payload });
  return asRecord(result);
}

export function getTurnDiff(snapshot: JsonRecord, missionId?: string): JsonRecord {
  const missions = asList(snapshot.missions);
  const target =
    missions.find(item => String(item.mission_id || "") === String(missionId || "")) ||
    missions[missions.length - 1] ||
    {};
  const changedFiles = asList(asRecord(target).changed_files).map(String);
  const actionHistory = asList(asRecord(target).action_history);
  return {
    missionId: asRecord(target).mission_id || "",
    changedFiles,
    actionCount: actionHistory.length,
  };
}

export function getFullThreadDiff(snapshot: JsonRecord): JsonRecord {
  const missions = asList(snapshot.missions);
  const changed = new Set<string>();
  for (const mission of missions) {
    const files = asList(asRecord(mission).changed_files);
    for (const file of files) {
      changed.add(String(file));
    }
  }
  return {
    missionCount: missions.length,
    changedFiles: [...changed],
  };
}

function textValue(value: unknown, fallback = ""): string {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function firstTextValue(values: unknown[], fallback = ""): string {
  for (const value of values) {
    const next = textValue(value);
    if (next) {
      return next;
    }
  }
  return fallback;
}

function textList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map(item => textValue(item)).filter(Boolean);
  }
  const single = textValue(value);
  return single ? [single] : [];
}

export function replayEvents(snapshot: JsonRecord): JsonRecord[] {
  const timeline = asList(snapshot.activity);
  return timeline.map(item => ({
    kind: item.kind || "activity",
    message: item.message || "",
    timestamp: item.timestamp || "",
  }));
}

export function buildLiveReviewWorkbench(snapshot: JsonRecord): JsonRecord {
  const missions = asList(snapshot.missions);
  const latestMission = asRecord(missions[missions.length - 1]);
  const activity = replayEvents(snapshot);
  const reportedTargetKind = textValue(
    snapshot.reviewTargetKind || snapshot.targetKind || latestMission.target_kind,
  );
  const targetKind = reportedTargetKind || "browser";
  const changedFiles = textList(latestMission.changed_files).slice(0, 6);
  const connectedDeviceBridge = asRecord(snapshot.connectedDeviceBridge);
  const bridgeAuditTrail = asList(connectedDeviceBridge.auditTrail);
  const bridgeReceipts = asList(connectedDeviceBridge.receipts);
  const latestBridgeAction = asRecord(bridgeAuditTrail[bridgeAuditTrail.length - 1]);
  const latestBridgeReceipt = asRecord(bridgeReceipts[bridgeReceipts.length - 1]);
  const dualPathBridge = {
    status: textValue(connectedDeviceBridge.status, "not_reported"),
    hosts: asList(connectedDeviceBridge.hosts),
    pendingApprovals: asList(connectedDeviceBridge.pendingApprovals),
    denials: asList(connectedDeviceBridge.denials),
    syncStatus: asList(connectedDeviceBridge.sync).map(item => ({
      workspaceId: item.workspaceId || item.workspace_id || "",
      direction: item.direction || "not_reported",
      status: item.status || "unknown",
      localPath: item.localPath || item.local_path || "",
      nasPath: item.nasPath || item.nas_path || "",
    })),
    performedByHost: latestBridgeAction.performedByHost || latestBridgeAction.performed_by_host || "",
    latestAction: latestBridgeAction,
    receipts: bridgeReceipts,
    latestReceipt: latestBridgeReceipt,
    manualGitHubBridge: asRecord(connectedDeviceBridge.manualGitHubBridge),
    uiEvidence: asRecord(connectedDeviceBridge.uiEvidence),
  };
  const targetMap: Record<string, JsonRecord> = {
    app: {
      kind: "app",
      label: firstTextValue(
        [snapshot.targetApp, latestMission.app_name, latestMission.workspace_name, snapshot.productName],
        "No app target reported",
      ),
      detail: firstTextValue(
        [snapshot.targetWindow, latestMission.window_title, snapshot.windowTitle],
        "Connect an app window to begin review.",
      ),
    },
    browser: {
      kind: "browser",
      label: firstTextValue(
        [snapshot.browserLabel, latestMission.browser_label, snapshot.browserUrl],
        "No browser target reported",
      ),
      detail: firstTextValue(
        [snapshot.browserUrl, latestMission.browser_url, latestMission.url],
        "Connect a browser session to begin review.",
      ),
    },
    html: {
      kind: "html",
      label: firstTextValue(
        [snapshot.htmlLabel, latestMission.html_label, snapshot.pageTitle],
        "No HTML target reported",
      ),
      detail: firstTextValue(
        [snapshot.pageTitle, latestMission.page_title, snapshot.htmlPath],
        "Attach a rendered document or component tree to begin review.",
      ),
    },
    program: {
      kind: "program",
      label: firstTextValue(
        [snapshot.programLabel, latestMission.program_name, latestMission.command],
        "No program target reported",
      ),
      detail: firstTextValue(
        [latestMission.command, snapshot.programPath, latestMission.program_path],
        "Attach an executable, script, or CLI trace to begin review.",
      ),
    },
    window: {
      kind: "window",
      label: firstTextValue(
        [snapshot.windowLabel, latestMission.window_title, snapshot.windowTitle],
        "No window target reported",
      ),
      detail: firstTextValue(
        [snapshot.windowTitle, latestMission.window_title, latestMission.session_id],
        "Connect a focused window to begin review.",
      ),
    },
  };
  const target = targetMap[targetKind] || targetMap.browser;
  const hasLiveTarget = Boolean(
    reportedTargetKind
    || firstTextValue([
      snapshot.targetApp,
      latestMission.app_name,
      snapshot.browserLabel,
      snapshot.browserUrl,
      latestMission.browser_url,
      snapshot.htmlLabel,
      snapshot.pageTitle,
      snapshot.programLabel,
      snapshot.programPath,
      snapshot.windowLabel,
      snapshot.windowTitle,
      latestMission.window_title,
    ]),
  );
  const runtimeStatus = {
    browser: firstTextValue(
      [snapshot.browserStatus, snapshot.runtimeBrowserStatus, latestMission.browser_status],
      "not_reported",
    ),
    computerUse: firstTextValue(
      [snapshot.computerUseStatus, snapshot.runtimeComputerUseStatus, latestMission.computer_use_status],
      "not_reported",
    ),
    autotest: firstTextValue(
      [snapshot.autotestStatus, snapshot.runtimeAutotestStatus, latestMission.autotest_status],
      "not_reported",
    ),
  };
  const panes = [
    {
      id: "agent-instructions",
      label: "Agent feedback",
      purpose: "Convert visual comments into structured guidance for the next agent turn.",
      status: modeText(runtimeStatus.autotest),
    },
    {
      id: "live-preview",
      label: "Live preview",
      purpose: `Show the selected ${target.kind} surface with pins, panes, and region context.`,
      status: modeText(runtimeStatus.browser),
    },
    {
      id: "proof-evidence",
      label: "Evidence",
      purpose: "Keep screenshots, timelapse, files, tools, and replay activity attached to each review.",
      status: modeText(runtimeStatus.computerUse),
    },
  ];
  const evidence = {
    screenshots: textList(snapshot.screenshots || snapshot.screenshotEvidence || latestMission.screenshots || latestMission.screenshot),
    timelapse: textList(snapshot.timelapse || snapshot.timelapseFrames || latestMission.timelapse || latestMission.timelapse_frames),
    files: textList(snapshot.files || snapshot.fileEvidence || latestMission.file_evidence).concat(changedFiles).slice(0, 8),
    tools: textList(snapshot.tools || snapshot.toolEvidence || latestMission.tools || latestMission.tool_history),
    activity: activity.slice(-6),
  };
  const liveReview = asRecord(snapshot.liveReview || latestMission.live_review);
  const annotations = asList(
    snapshot.annotations
    || latestMission.annotations
    || liveReview.annotations,
  )
    .map((item, index) => ({
      id: textValue(item.id, `annotation-${index + 1}`),
      pin: textValue(item.pin, String(index + 1)),
      target: textValue(item.target, String(target.kind)),
      pane: textValue(item.pane, "live-preview"),
      region: textValue(item.region, "reported region"),
      selector: textValue(item.selector),
      comment: textValue(item.comment || item.feedback),
      feedback: textValue(item.feedbackType || item.kind, "Review comment"),
      evidence: textValue(item.evidence, "not_reported"),
    }))
    .filter(item => item.comment || item.selector);
  const targetOptions = Object.values(targetMap);
  const routeContext = asRecord(latestMission.routeContext || snapshot.routeContext);
  const taskContext = asRecord(latestMission.taskContext || snapshot.taskContext);
  const verifierFeedback = asRecord(latestMission.verifierFeedback || snapshot.verifierFeedback);
  const selectedSkills = textList(latestMission.selectedSkills || snapshot.selectedSkills).slice(0, 6);
  const plannerRules = textList(latestMission.plannerRules || snapshot.plannerRules).slice(0, 6);
  const designPrompts = textList(latestMission.designPrompts || snapshot.designPrompts).slice(0, 4);
  const statusUpdates = asList(latestMission.statusUpdates || snapshot.statusUpdates)
    .map(item => ({
      kind: textValue(item.kind || item.type, "update"),
      message: textValue(item.message || item.summary, ""),
      at: textValue(item.at || item.timestamp, ""),
    }))
    .filter(item => item.message)
    .slice(-4);
  const skillInfluence = {
    selectedSkills,
    plannerRules,
    designPrompts,
    nextIdea: firstTextValue([latestMission.nextIdea, snapshot.nextIdea]),
    decisionInfluence: firstTextValue(
      [latestMission.decisionInfluence, snapshot.decisionInfluence],
    ),
  };
  const coworkStatus = {
    sideBySidePreview: textValue(snapshot.sideBySidePreview, "not_reported"),
    feedbackBridge: textValue(snapshot.feedbackBridge, "not_reported"),
    evidenceTimeline: textValue(snapshot.evidenceTimeline, "not_reported"),
    statusUpdates,
  };
  const plannerBridgePacket = {
    routeContext: {
      strategy: firstTextValue([routeContext.strategy, latestMission.routingStrategy], "not_reported"),
      plannerModel: firstTextValue([routeContext.plannerModel, latestMission.planner_model]),
      executorModel: firstTextValue([routeContext.executorModel, latestMission.executor_model]),
      verifierModel: firstTextValue([routeContext.verifierModel, latestMission.verifier_model]),
    },
    taskContext: {
      objective: firstTextValue([taskContext.objective, latestMission.objective]),
      check: firstTextValue([taskContext.check, latestMission.success_checks]),
      nextAction: firstTextValue([taskContext.nextAction, latestMission.next_actions]),
    },
    verifierFeedback: {
      verdict: firstTextValue([verifierFeedback.verdict, latestMission.verifier_verdict], "not_reported"),
      summary: firstTextValue([verifierFeedback.summary, latestMission.verifier_summary], "Verifier feedback not attached yet."),
    },
  };
  const agentFeedback = {
    target,
    targetOptions,
    selectedTargetKind: target.kind,
    panes: panes.map(pane => ({ id: pane.id, label: pane.label, status: pane.status })),
    annotations: annotations.map(annotation => ({
      pin: annotation.pin,
      target: annotation.target,
      pane: annotation.pane,
      region: annotation.region,
      selector: annotation.selector,
      comment: annotation.comment,
      feedback: annotation.feedback,
      evidence: annotation.evidence,
    })),
    runtimeStatus,
    hasLiveTarget,
    evidence,
    evidenceCounts: {
      screenshots: evidence.screenshots.length,
      timelapse: evidence.timelapse.length,
      files: evidence.files.length,
      tools: evidence.tools.length,
      activity: evidence.activity.length,
    },
    replayWindow: activity.slice(-4),
    dualPathBridge,
    skillInfluence,
    coworkStatus,
    plannerBridgePacket,
    replaySummary: firstTextValue(
      [snapshot.replaySummary, latestMission.summary, snapshot.status],
      "No live review evidence has been reported yet.",
    ),
  };

  return {
    target,
    hasLiveTarget,
    targetOptions,
    panes,
    annotations,
    agentFeedback,
    runtimeStatus,
    evidence,
    activity,
    replayWindow: activity.slice(-4),
    dualPathBridge,
    replaySummary: firstTextValue(
      [snapshot.replaySummary, latestMission.summary, snapshot.status],
      "No live review evidence has been reported yet.",
    ),
  };
}

function modeText(value: unknown): string {
  return textValue(value, "not_reported");
}
