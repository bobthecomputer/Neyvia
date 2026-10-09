import { checkPresentationAction } from "./neyviaPresentationContracts.js";
import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
/**
 * Neyvia Phase B — Chat | Orchestration product mode helpers.
 * Shared by NeyviaShell / NeyviaWorkspace. Runtime family stays independent of mode.
 */

export const PRODUCT_MODE_CHAT = "chat";
export const PRODUCT_MODE_ORCHESTRATION = "orchestration";

export const PRODUCT_MODE_STORAGE_KEY = "fluxio.product.mode";

/** Managed CLI runtime ids (wired by parallel runtime-merge; UI lists them regardless). */
export const MANAGED_CLI_RUNTIME_OPTIONS = Object.freeze([
  Object.freeze({ value: "neyvia-agent", label: "Neyvia Native", family: "neyvia" }),
  Object.freeze({ value: "codex", label: "Codex", family: "codex" }),
  Object.freeze({ value: "claude-code", label: "Claude Code", family: "claude" }),
  Object.freeze({ value: "grok-build", label: "Grok Build", family: "grok" }),
  Object.freeze({ value: "kimi-code", label: "Kimi Code", family: "kimi" }),
  Object.freeze({ value: "opencode", label: "OpenCode", family: "opencode" }),
]);

export const OTHER_RUNTIME_OPTIONS = Object.freeze([
  Object.freeze({ value: "hermes", label: "Hermes", family: "hermes" }),
  Object.freeze({ value: "openclaw", label: "OpenClaw", family: "openclaw" }),
  Object.freeze({ value: "opencode-go", label: "OpenCodeGo", family: "opencode" }),
]);

export const MANAGED_CLI_RUNTIME_DEFAULT_ROUTES = Object.freeze({
  codex: Object.freeze({ provider: "openai-codex", model: "gpt-5.6-sol" }),
  "kimi-code": Object.freeze({ provider: "kimi-code", model: "k3" }),
  "claude-code": Object.freeze({ provider: "claude-code", model: "sonnet" }),
  "grok-build": Object.freeze({ provider: "grok-build", model: "grok-4.5" }),
  opencode: Object.freeze({ provider: "opencode", model: "" }),
});

/** Red-team chat roles for Chat mode. */
export const RED_TEAM_ROLE_OPTIONS = Object.freeze([
  Object.freeze({
    id: "operator",
    label: "Operator",
    brief: "Mission lead — coordinate, approve, and hand off.",
    skillPack: "operator-core",
  }),
  Object.freeze({
    id: "attacker",
    label: "Attacker",
    brief: "Offensive probe — find weaknesses without live exploitation.",
    skillPack: "red-team-attacker",
  }),
  Object.freeze({
    id: "defender",
    label: "Defender",
    brief: "Hardening and detection — close gaps the attacker finds.",
    skillPack: "red-team-defender",
  }),
  Object.freeze({
    id: "auditor",
    label: "Auditor",
    brief: "Evidence and compliance — verify claims with receipts.",
    skillPack: "security-auditor",
  }),
]);

export const RED_TEAM_SKILL_PACKS = Object.freeze([
  Object.freeze({ id: "operator-core", label: "Operator core", roles: ["operator"] }),
  Object.freeze({ id: "red-team-attacker", label: "Attacker pack", roles: ["attacker"] }),
  Object.freeze({ id: "red-team-defender", label: "Defender pack", roles: ["defender"] }),
  Object.freeze({ id: "security-auditor", label: "Auditor pack", roles: ["auditor"] }),
  Object.freeze({ id: "security_red_team", label: "Full red-team", roles: ["attacker", "defender", "auditor"] }),
]);

export const LEAD_WORKERS_PRESET_ID = "lead-workers";

const LEAD_WORKERS_ROUTE = Object.freeze({
  runtimeId: "codex",
  provider: "openai-codex",
});

function buildLeadWorkersRolesUnchecked(workerCount = 2, sequentialIntegration = false) {
  const count = Math.min(4, Math.max(2, Number(workerCount) || 2));
  const roles = [
    {
      roleId: "lead",
      label: "Sol lead",
      brief: "Decompose and coordinate the bounded objective.",
      skillPack: "operator-core",
      routeSelection: { ...LEAD_WORKERS_ROUTE, role: "planner", model: "gpt-5.6-sol", effort: "xhigh" },
    },
    ...Array.from({ length: count }, (_, index) => ({
      roleId: "worker",
      label: `Luna worker ${index + 1}`,
      brief: "Implement a disjoint, evidenced slice of the objective.",
      skillPack: "operator-core",
      routeSelection: { ...LEAD_WORKERS_ROUTE, role: "executor", model: "gpt-5.6-luna", effort: "high" },
    })),
  ];
  if (sequentialIntegration) {
    roles.push({
      roleId: "integration",
      label: "Luna sequential integration",
      brief: "Integrate the completed worker deltas before verification.",
      skillPack: "operator-core",
      routeSelection: { ...LEAD_WORKERS_ROUTE, role: "executor", model: "gpt-5.6-luna", effort: "high" },
    });
  }
  roles.push({
    roleId: "barrier",
    label: "Terra verification barrier",
    brief: "Verify receipts, changed scope, and evidence.",
    skillPack: "security-auditor",
    routeSelection: { ...LEAD_WORKERS_ROUTE, role: "verifier", model: "gpt-5.6-terra", effort: "medium" },
  });
  return roles.map((role, index) => ({
    ...role,
    id: `lead-workers-role-${role.roleId}-${index + 1}`,
    role: role.roleId,
    goal: role.brief,
    runtime: "codex",
    status: index === 0 ? "ready" : "queued",
  }));
}

export function surfaceToProductMode(surface) {
  const normalized = String(surface || "").trim().toLowerCase();
  if (normalized === "builder" || normalized === "builder-review" || normalized === "orchestration") {
    return PRODUCT_MODE_ORCHESTRATION;
  }
  // notebook / lab / library stay Chat-mode family for runtime routing
  return PRODUCT_MODE_CHAT;
}

export function productModeToSurface(mode) {
  return String(mode || "").trim().toLowerCase() === PRODUCT_MODE_ORCHESTRATION ? "builder" : "agent";
}

export function normalizeProductMode(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === PRODUCT_MODE_ORCHESTRATION || normalized === "builder" || normalized === "mission") {
    return PRODUCT_MODE_ORCHESTRATION;
  }
  return PRODUCT_MODE_CHAT;
}

export function runtimeFamilyForId(runtimeId) {
  const id = String(runtimeId || "").trim().toLowerCase();
  if (!id) return "";
  const managed = MANAGED_CLI_RUNTIME_OPTIONS.find(item => item.value === id);
  if (managed) return managed.family;
  const other = OTHER_RUNTIME_OPTIONS.find(item => item.value === id);
  if (other) return other.family;
  if (id.includes("claude")) return "claude";
  if (id.includes("grok")) return "grok";
  if (id.includes("kimi")) return "kimi";
  if (id.includes("opencode")) return "opencode";
  if (id.includes("hermes")) return "hermes";
  if (id.includes("openclaw")) return "openclaw";
  return id;
}

/**
 * Merge backend runtime rows with managed CLI + other catalog entries.
 * Does not drop unknown backend runtimes.
 */
function mergeRuntimePickerOptionsUnchecked(backendOptions = []) {
  const rows = [];
  const seen = new Set();
  const push = option => {
    const value = String(option?.value || option?.runtime_id || "").trim();
    if (!value || seen.has(value)) return;
    seen.add(value);
    rows.push({
      ...option,
      value,
      label: String(option?.label || option?.name || value).trim() || value,
      family: option?.family || runtimeFamilyForId(value),
    });
  };
  (Array.isArray(backendOptions) ? backendOptions : []).forEach(push);
  MANAGED_CLI_RUNTIME_OPTIONS.forEach(push);
  OTHER_RUNTIME_OPTIONS.forEach(push);
  return rows;
}

export function buildDefaultOrchestrationRoles() {
  return buildLeadWorkersRoles();
}

function explicitRoleLabel(role) {
  return String(role || "role")
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map(token => token.charAt(0).toUpperCase() + token.slice(1))
    .join(" ");
}

/**
 * Resolve the task-role rows for one durable orchestration conversation.
 * Explicit conversations own their ordered role list and frozen routes;
 * automatic conversations retain the caller's task-fit defaults.
 */
function resolveOrchestrationRolesUnchecked(conversation = {}, fallbackRoles = [], selectedRuntime = "hermes", graph = null) {
  const metadata = conversation?.metadata && typeof conversation.metadata === "object"
    ? conversation.metadata
    : {};
  const teamSelection = metadata.teamSelection && typeof metadata.teamSelection === "object"
    ? metadata.teamSelection
    : {};
  const explicitRoles = teamSelection.mode === "explicit" && Array.isArray(teamSelection.roles)
    ? teamSelection.roles.map(role => String(role || "").trim().toLowerCase()).filter(Boolean)
    : [];
  if (!explicitRoles.length) {
    const persistedPreset = graph?.preset && typeof graph.preset === "object" ? graph.preset : null;
    if (persistedPreset?.id === LEAD_WORKERS_PRESET_ID) {
      const presetRoles = buildLeadWorkersRoles(
        persistedPreset.workerCount,
        persistedPreset.sequentialIntegration,
      );
      const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
      return presetRoles.map(role => {
        const node = nodes.find(item => String(item?.title || "").trim() === role.label);
        if (!node) return role;
        return {
          ...role,
          goal: String(node.objective || role.goal || role.brief),
          runtime: String(node.runtime || role.runtime || selectedRuntime || "hermes"),
          routeSelection: node.routeSelection || role.routeSelection,
          status: String(node.lifecycleStage || node.status || role.status),
        };
      });
    }
    return fallbackRoles;
  }
  const routeSnapshot = metadata.routeSnapshot && typeof metadata.routeSnapshot === "object"
    ? metadata.routeSnapshot
    : {};
  const conversationObjective = String(
    conversation?.objective
      || metadata.objective
      || metadata.goal
      || conversation?.title
      || conversation?.name
      || "the orchestration objective",
  ).trim().slice(0, 320);
  const roleVerbs = { planner: "Plan", executor: "Execute", verifier: "Verify" };
  return explicitRoles.map((role, index) => {
    const route = routeSnapshot[role] && typeof routeSnapshot[role] === "object"
      ? { ...routeSnapshot[role], role }
      : { role, runtimeId: selectedRuntime || "hermes" };
    const label = String(route.label || explicitRoleLabel(role));
    const objective = String(
      route.objective
        || route.goal
        || `${roleVerbs[role] || "Handle"} the bounded ${label.toLowerCase()} responsibility for: ${conversationObjective}.`,
    );
    return {
      id: `explicit-${conversation?.conversationId || "orchestration"}-${role}-${index + 1}`,
      roleId: role,
      role,
      label,
      brief: objective,
      goal: objective,
      runtime: route.runtimeId || route.runtime || selectedRuntime || "hermes",
      routeSelection: route,
      status: "ready",
    };
  });
}

export function summarizeMissionCard(row = {}) {
  const missionId = String(row?.id || row?.missionId || row?.mission_id || "").trim();
  const status = String(row?.status || row?.statusTone || "draft").trim();
  const title = String(row?.name || row?.title || row?.objective || "Mission").trim();
  const summaryParts = [
    row?.turningPoint,
    row?.progressLabel,
    row?.progress,
    row?.description,
  ]
    .map(part => String(part || "").trim())
    .filter(Boolean);
  return {
    id: missionId,
    title,
    status,
    statusTone: String(row?.statusTone || "paused").toLowerCase(),
    summary: summaryParts[0] || "No build summary yet.",
    runtime: String(row?.runtimeId || row?.runtime || "").trim(),
    updated: String(row?.lastRunMeta || row?.updated || "").trim(),
    selected: Boolean(row?.selected),
    agentCount: Number(row?.delegatedCount || row?.runtimeLaneCount || 0),
    raw: row,
  };
}

export function summarizeEventTimeline(moments = [], missionEvents = [], actionHistory = []) {
  const rows = [];
  const push = item => {
    if (!item) return;
    const title = String(item.title || item.label || item.kind || item.message || "").trim();
    if (!title) return;
    rows.push({
      id: String(item.id || `${title}-${rows.length}`),
      time: String(item.time || item.meta || item.createdAt || item.timestamp || item.executed_at || "").trim(),
      title,
      detail: String(item.detail || item.technicalDetail || item.message || item.summary || "").trim(),
      tone: String(item.tone || "neutral").toLowerCase(),
      kind: String(item.kind || item.type || "event").toLowerCase(),
    });
  };
  (Array.isArray(moments) ? moments : []).forEach(push);
  (Array.isArray(missionEvents) ? missionEvents : []).forEach(item =>
    push({
      id: item?.id || item?.event_id,
      time: item?.created_at || item?.timestamp || item?.time,
      title: item?.title || item?.kind || item?.type || "Mission event",
      detail: item?.detail || item?.message || item?.summary,
      tone: item?.tone || "neutral",
      kind: item?.kind || item?.type || "event",
    }),
  );
  (Array.isArray(actionHistory) ? actionHistory : []).forEach(item =>
    push({
      id: item?.id || item?.action_id,
      time: item?.executed_at || item?.created_at,
      title: item?.proposal?.title || item?.title || item?.kind || "Action",
      detail: item?.proposal?.detail || item?.detail || item?.result_summary,
      tone: item?.status === "failed" ? "failed" : "neutral",
      kind: "action",
    }),
  );
  return rows.slice(-80);
}

export function classifyLiveActionRows(messages = [], timelineMoments = []) {
  const rows = [];
  const push = item => {
    if (!item) return;
    const title = String(item.title || item.label || "").trim();
    const detail = String(item.detail || item.technicalDetail || "").trim();
    const blob = `${title} ${detail}`.toLowerCase();
    let kind = "status";
    if (/\b(tool|function.?call|mcp|shell|command|bash|powershell)\b/.test(blob)) kind = "tool";
    else if (/\b(edit|write|patch|diff|file|save)\b/.test(blob)) kind = "edit";
    else if (/\b(run|execut|command|terminal|npm|pytest|cargo)\b/.test(blob)) kind = "command";
    else if (item.messageKind === "process" || item.role === "process") kind = "tool";
    const toolId =
      item.toolId ||
      item.tool_id ||
      item.toolName ||
      item.name ||
      (kind === "tool" || kind === "edit" || kind === "command" ? `${title} ${detail}` : "");
    rows.push({
      id: String(item.id || `${kind}-${rows.length}`),
      kind,
      toolId: toolId || undefined,
      title: title || kind,
      detail,
      meta: String(item.meta || item.createdAt || item.time || "").trim(),
      pending: Boolean(item.pending),
      tone: String(item.tone || "neutral").toLowerCase(),
    });
  };
  (Array.isArray(messages) ? messages : [])
    .filter(item => {
      const role = String(item?.role || "").toLowerCase();
      const kind = String(item?.messageKind || item?.kind || "").toLowerCase();
      return (
        role === "process" ||
        kind === "process" ||
        kind === "tool" ||
        item?.emphasis ||
        item?.technicalDetail ||
        Boolean(item?.pending)
      );
    })
    .slice(-40)
    .forEach(push);
  (Array.isArray(timelineMoments) ? timelineMoments : []).slice(-20).forEach(push);
  return rows.slice(-36);
}

export function mergeRuntimePickerOptions(...args) {
  const before = frontendContractBefore("batch.runtime-options", args);
  return checkedFrontendAction("batch.runtime-options", args, mergeRuntimePickerOptionsUnchecked(...args), before);
}

export function buildLeadWorkersRoles(...args) { return checkPresentationAction("orchestration.preset", args, buildLeadWorkersRolesUnchecked(...args)); }

export function resolveOrchestrationRoles(...args) { return checkPresentationAction("orchestration.resolve", args, resolveOrchestrationRolesUnchecked(...args)); }
