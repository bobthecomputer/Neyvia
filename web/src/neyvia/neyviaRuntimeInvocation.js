/**
 * Neyvia external runtime invocation contract.
 *
 * Product rule: an external AI runtime (Claude Code, Grok Build, OpenCodeGo,
 * Kimi Code, …) has three *different* relationships with Neyvia. They are not
 * one overloaded "open provider" boolean:
 *
 *   1. primary-session    — the runtime *is* the session surface. Neyvia keeps
 *                           context, files, tools, permissions, artifacts,
 *                           receipts, memory and continuity around it.
 *   2. ecosystem-override — Neyvia stays the interface; the runtime powers a
 *                           *named subset* of responsibilities. Explicit and
 *                           inspectable. Reserved responsibilities never move.
 *   3. inline-tool        — a scoped invocation inside a live parent session.
 *                           Returns into the transcript as an embedded window,
 *                           expandable to fullscreen, collapsible back to the
 *                           exact parent context. Never a hidden side thread.
 *
 * Every invocation carries: mode, runtime identity, parent session, context
 * scope, delegated responsibilities, presentation, lifecycle, permissions and
 * a return channel. One execution backend, three lifecycles.
 *
 * Honesty rule: readiness is derived from backend evidence only. An unavailable
 * runtime is reported as unavailable — never as an optimistic "ready" button.
 */

import { managedCliRouteForRuntime } from "./providerModelCatalog.js";

export const NEYVIA_RUNTIME_INVOCATION_SCHEMA = "neyvia.runtime.invocation.v1";

/* ------------------------------------------------------------------ modes */

export const NEYVIA_INVOCATION_MODES = Object.freeze([
  Object.freeze({
    id: "primary-session",
    label: "Start the session with this runtime",
    summary:
      "The runtime becomes the working surface for this session. Neyvia keeps context, files, tools, permissions, artifacts, receipts and continuity around it.",
    ownsSurface: true,
    requiresParent: false,
    defaultPresentation: "session-surface",
  }),
  Object.freeze({
    id: "ecosystem-override",
    label: "Keep Neyvia, borrow this runtime",
    summary:
      "Neyvia stays the interface and the ecosystem. The runtime powers a named set of responsibilities; everything else stays Neyvia-owned.",
    ownsSurface: false,
    requiresParent: false,
    defaultPresentation: "inline-badge",
  }),
  Object.freeze({
    id: "inline-tool",
    label: "Use this runtime for one task",
    summary:
      "A scoped invocation inside the live session. Returns an embedded window in the transcript; expand to focus, collapse back to the parent context.",
    ownsSurface: false,
    requiresParent: true,
    defaultPresentation: "inline-card",
  }),
]);

const MODE_IDS = new Set(NEYVIA_INVOCATION_MODES.map(item => item.id));

export function normalizeInvocationMode(value) {
  const id = String(value || "").trim();
  return MODE_IDS.has(id) ? id : "inline-tool";
}

export function invocationModeMeta(modeId) {
  return NEYVIA_INVOCATION_MODES.find(item => item.id === normalizeInvocationMode(modeId)) || null;
}

/* ------------------------------------------------- delegable responsibility */

/**
 * Responsibilities a runtime may take over in `ecosystem-override` (and which a
 * `primary-session` runtime implicitly owns for its own surface).
 */
export const NEYVIA_DELEGABLE_RESPONSIBILITIES = Object.freeze([
  Object.freeze({
    id: "conversation-loop",
    label: "Conversation loop",
    detail: "The runtime produces the assistant turns for this session.",
  }),
  Object.freeze({
    id: "coding-loop",
    label: "Coding loop",
    detail: "Plan → edit → run → repair cycles are driven by the runtime.",
  }),
  Object.freeze({
    id: "repo-awareness",
    label: "Repository awareness",
    detail: "The runtime indexes and reasons over the working tree.",
  }),
  Object.freeze({
    id: "code-editing",
    label: "Editing mechanism",
    detail: "File edits are produced by the runtime's own patch mechanism.",
  }),
  Object.freeze({
    id: "tool-execution",
    label: "Tool execution",
    detail: "The runtime executes its own tools inside the approved sandbox.",
  }),
  Object.freeze({
    id: "reasoning",
    label: "Reasoning behaviour",
    detail: "Long-form planning/reasoning is delegated to the runtime.",
  }),
]);

/**
 * Responsibilities Neyvia never hands to an external runtime. A runtime that
 * asks for one of these is refused at the contract level, not by a UI check.
 */
export const NEYVIA_RESERVED_RESPONSIBILITIES = Object.freeze([
  "permissions",
  "artifact-custody",
  "durable-memory",
  "evidence-capture",
  "orchestration-state",
  "identity",
]);

const DELEGABLE_IDS = new Set(NEYVIA_DELEGABLE_RESPONSIBILITIES.map(item => item.id));
const RESERVED_IDS = new Set(NEYVIA_RESERVED_RESPONSIBILITIES);

export function responsibilityMeta(id) {
  return NEYVIA_DELEGABLE_RESPONSIBILITIES.find(item => item.id === id) || null;
}

/**
 * Split a requested delegation into what is actually granted and what is
 * refused, so the UI can state the effective combination truthfully.
 */
export function partitionDelegation(requested = []) {
  const list = Array.isArray(requested) ? requested.map(value => String(value || "").trim()) : [];
  const delegated = [];
  const refused = [];
  for (const id of list) {
    if (!id) continue;
    if (RESERVED_IDS.has(id)) {
      refused.push({ id, reason: "Neyvia-reserved responsibility — never delegated to an external runtime." });
      continue;
    }
    if (!DELEGABLE_IDS.has(id)) {
      refused.push({ id, reason: "Unknown responsibility — not part of the delegation contract." });
      continue;
    }
    if (!delegated.includes(id)) delegated.push(id);
  }
  return { delegated, refused };
}

/** Responsibilities that stay with Neyvia for a given delegation. */
export function retainedResponsibilities(delegated = []) {
  const taken = new Set(delegated);
  return [
    ...NEYVIA_DELEGABLE_RESPONSIBILITIES.filter(item => !taken.has(item.id)).map(item => item.id),
    ...NEYVIA_RESERVED_RESPONSIBILITIES,
  ];
}

/* --------------------------------------------------------- context scoping */

export const NEYVIA_CONTEXT_SCOPES = Object.freeze([
  Object.freeze({
    id: "inherit",
    label: "Inherit session context",
    detail: "The invocation sees the parent session transcript, files and artifacts.",
  }),
  Object.freeze({
    id: "selected",
    label: "Selected context only",
    detail: "Only the explicitly selected messages, files or artifacts are passed.",
  }),
  Object.freeze({
    id: "isolated",
    label: "Isolated",
    detail: "No parent context is passed. Results still return to the parent session.",
  }),
]);

const CONTEXT_SCOPE_IDS = new Set(NEYVIA_CONTEXT_SCOPES.map(item => item.id));

export function normalizeContextScope(value, mode) {
  const id = String(value || "").trim();
  if (CONTEXT_SCOPE_IDS.has(id)) return id;
  return normalizeInvocationMode(mode) === "inline-tool" ? "selected" : "inherit";
}

/* ------------------------------------------------------------- presentation */

export const NEYVIA_INVOCATION_PRESENTATIONS = Object.freeze([
  "session-surface",
  "inline-card",
  "inline-badge",
  "dock-right",
  "dock-left",
  "floating-center",
  "fullscreen",
]);

export function normalizeInvocationPresentation(value, mode) {
  const id = String(value || "").trim();
  if (NEYVIA_INVOCATION_PRESENTATIONS.includes(id)) return id;
  return invocationModeMeta(mode)?.defaultPresentation || "inline-card";
}

/* ----------------------------------------------------------------- lifecycle */

/**
 * requested → ready → active → suspended ⇄ active → closed
 *                   ↘ blocked (truthful unavailable state, terminal until retried)
 *
 * `ready → suspended` is allowed on purpose: an operator may step away from a
 * runtime that has been resolved but has not yet run a turn. Without it the
 * Suspend control would be a button with no effect, which is worse than not
 * offering it.
 */
export const NEYVIA_INVOCATION_LIFECYCLE = Object.freeze({
  requested: Object.freeze(["ready", "blocked", "closed"]),
  ready: Object.freeze(["active", "suspended", "blocked", "closed"]),
  active: Object.freeze(["suspended", "returned", "blocked", "closed"]),
  suspended: Object.freeze(["active", "returned", "closed"]),
  returned: Object.freeze(["active", "closed"]),
  blocked: Object.freeze(["requested", "closed"]),
  closed: Object.freeze([]),
});

export function canTransitionInvocation(from, to) {
  const allowed = NEYVIA_INVOCATION_LIFECYCLE[String(from || "")] || [];
  return allowed.includes(String(to || ""));
}

/**
 * `suspended` means the window is collapsed / the surface is not visible.
 * It is NOT a teardown: the runtime session and its state survive so that
 * collapsing an inline window never restarts the provider.
 */
export function isInvocationResumable(state) {
  return ["ready", "active", "suspended", "returned"].includes(String(state || ""));
}

/**
 * Still owned by the session. `blocked` stays open on purpose: an unavailable
 * runtime must be visible and truthful, not silently dropped from the registry.
 */
export function isInvocationOpen(state) {
  return String(state || "") !== "closed" && String(state || "") !== "";
}

/* --------------------------------------------------------------- readiness */

/**
 * Truthful readiness. `evidence` comes from the backend only:
 *   providerPresence  — get_provider_secret_presence_command
 *   runtimeStatus     — runtime invocation registry / managed CLI probe
 * No evidence means `unknown`, never `ready`.
 */
export function resolveRuntimeReadiness(runtimeId, evidence = {}) {
  const runtime = String(runtimeId || "").trim().toLowerCase();
  if (!runtime) {
    return Object.freeze({ state: "unknown", ready: false, detail: "No runtime selected." });
  }
  const status = evidence.runtimeStatus && typeof evidence.runtimeStatus === "object"
    ? evidence.runtimeStatus[runtime]
    : null;
  if (status && typeof status === "object") {
    if (status.available === true) {
      return Object.freeze({
        state: "ready",
        ready: true,
        detail: String(status.detail || "Runtime reported available by the backend."),
      });
    }
    if (status.available === false) {
      return Object.freeze({
        state: "unavailable",
        ready: false,
        detail: String(status.detail || status.reason || "Runtime reported unavailable by the backend."),
      });
    }
  }
  const presence = evidence.providerPresence && typeof evidence.providerPresence === "object"
    ? evidence.providerPresence
    : null;
  if (presence) {
    const entry = presence[runtime] ?? presence[runtime.replace(/-/g, "_")];
    if (entry === false || entry?.present === false) {
      return Object.freeze({
        state: "credentials-missing",
        ready: false,
        detail: "No stored credential for this runtime. Connect it before starting a session.",
      });
    }
  }
  return Object.freeze({
    state: "unknown",
    ready: false,
    detail: "Readiness has not been reported by the backend yet.",
  });
}

/* --------------------------------------------------------------- records */

let invocationCounter = 0;

function nextInvocationId(mode, runtime) {
  invocationCounter += 1;
  const stamp = Date.now().toString(36);
  return `inv-${normalizeInvocationMode(mode)}-${String(runtime || "runtime")}-${stamp}-${invocationCounter}`;
}

function frozenList(value) {
  return Object.freeze(Array.isArray(value) ? value.filter(Boolean).map(String) : []);
}

/**
 * Build a normalized invocation record. This is the single object the shell,
 * the transcript, the embedded-window host and the backend all agree on.
 */
export function createRuntimeInvocation({
  mode = "inline-tool",
  runtime = "",
  model = null,
  parentSessionId = null,
  parentMissionId = null,
  purpose = "",
  contextScope = null,
  contextSelection = null,
  delegate = [],
  presentation = null,
  permissions = null,
  readiness = null,
  requestedAt = null,
} = {}) {
  const modeId = normalizeInvocationMode(mode);
  const meta = invocationModeMeta(modeId);
  const runtimeId = String(runtime || "").trim().toLowerCase();
  const route = managedCliRouteForRuntime(runtimeId);
  const parent = parentSessionId ? String(parentSessionId) : null;
  const requestedDelegation = modeId === "primary-session"
    ? NEYVIA_DELEGABLE_RESPONSIBILITIES.map(item => item.id)
    : delegate;
  const { delegated, refused } = partitionDelegation(requestedDelegation);
  const resolvedReadiness = readiness && typeof readiness === "object"
    ? readiness
    : resolveRuntimeReadiness(runtimeId, {});

  const problems = [];
  if (!runtimeId) problems.push("A runtime must be named.");
  if (meta?.requiresParent && !parent) {
    problems.push("An inline runtime invocation requires the parent session it returns into.");
  }
  if (modeId === "ecosystem-override" && !delegated.length) {
    problems.push("An ecosystem override must name at least one delegated responsibility.");
  }

  return Object.freeze({
    schema: NEYVIA_RUNTIME_INVOCATION_SCHEMA,
    invocationId: nextInvocationId(modeId, runtimeId),
    mode: modeId,
    modeLabel: meta?.label || modeId,
    runtime: runtimeId,
    model: model ? String(model) : route?.defaultModel || null,
    routeSource: route?.source || null,
    parentSessionId: parent,
    parentMissionId: parentMissionId ? String(parentMissionId) : null,
    purpose: String(purpose || "").trim(),
    contextScope: normalizeContextScope(contextScope, modeId),
    contextSelection: Object.freeze(
      Array.isArray(contextSelection) ? contextSelection.map(item => Object.freeze({ ...item })) : [],
    ),
    delegated: frozenList(delegated),
    retained: frozenList(retainedResponsibilities(delegated)),
    refusedDelegation: Object.freeze(refused.map(item => Object.freeze({ ...item }))),
    presentation: normalizeInvocationPresentation(presentation, modeId),
    permissions: Object.freeze({
      inheritSession: permissions?.inheritSession !== false,
      approvalRequired: permissions?.approvalRequired !== false,
      grants: frozenList(permissions?.grants),
    }),
    readiness: Object.freeze({ ...resolvedReadiness }),
    state: problems.length ? "blocked" : resolvedReadiness.ready ? "ready" : "requested",
    problems: frozenList(problems),
    requestedAt: requestedAt || new Date().toISOString(),
    returns: Object.freeze({ messages: [], artifacts: [], receipts: [], changes: [] }),
    lastTransitionAt: requestedAt || new Date().toISOString(),
  });
}

/** Apply a lifecycle transition, refusing illegal moves instead of guessing. */
export function transitionRuntimeInvocation(record, nextState, patch = {}) {
  if (!record || typeof record !== "object") return record;
  const target = String(nextState || "");
  if (!canTransitionInvocation(record.state, target)) return record;
  return Object.freeze({
    ...record,
    ...patch,
    state: target,
    lastTransitionAt: new Date().toISOString(),
  });
}

/**
 * Everything an invocation hands back enters Neyvia's normal evidence and
 * artifact flow. Nothing returned here is treated as proof by itself — the
 * caller still records artifacts/receipts through the ecosystem paths.
 */
export function recordRuntimeReturn(record, { messages = [], artifacts = [], receipts = [], changes = [] } = {}) {
  if (!record || typeof record !== "object") return record;
  const merge = (current, incoming) =>
    Object.freeze([...(current || []), ...(Array.isArray(incoming) ? incoming : [])]);
  const next = Object.freeze({
    ...record,
    returns: Object.freeze({
      messages: merge(record.returns?.messages, messages),
      artifacts: merge(record.returns?.artifacts, artifacts),
      receipts: merge(record.returns?.receipts, receipts),
      changes: merge(record.returns?.changes, changes),
    }),
  });
  return canTransitionInvocation(next.state, "returned")
    ? transitionRuntimeInvocation(next, "returned")
    : next;
}

/* --------------------------------------------------------------- registry */

export function emptyRuntimeInvocationRegistry() {
  return Object.freeze({
    schema: NEYVIA_RUNTIME_INVOCATION_SCHEMA,
    invocations: Object.freeze([]),
  });
}

/**
 * Registry rules that keep the three modes distinct:
 *  - at most one live `primary-session` invocation per session;
 *  - at most one live `ecosystem-override` per delegated responsibility;
 *  - any number of `inline-tool` invocations, each with a parent session.
 */
export function upsertRuntimeInvocation(registry, record) {
  const current = Array.isArray(registry?.invocations) ? registry.invocations : [];
  if (!record?.invocationId) return registry || emptyRuntimeInvocationRegistry();
  const withoutSelf = current.filter(item => item.invocationId !== record.invocationId);

  let retained = withoutSelf;
  if (record.mode === "primary-session" && isInvocationOpen(record.state)) {
    retained = retained.map(item =>
      item.mode === "primary-session"
        && item.parentSessionId === record.parentSessionId
        && isInvocationOpen(item.state)
        ? transitionRuntimeInvocation(item, "closed", { closedReason: "Replaced by a new primary runtime." })
        : item,
    );
  }
  if (record.mode === "ecosystem-override" && isInvocationOpen(record.state)) {
    const taken = new Set(record.delegated);
    retained = retained.map(item => {
      if (item.mode !== "ecosystem-override" || !isInvocationOpen(item.state)) return item;
      const overlap = (item.delegated || []).some(id => taken.has(id));
      if (!overlap) return item;
      const remaining = (item.delegated || []).filter(id => !taken.has(id));
      if (!remaining.length) {
        return transitionRuntimeInvocation(item, "closed", {
          closedReason: "Its delegated responsibilities moved to another runtime.",
        });
      }
      return Object.freeze({
        ...item,
        delegated: frozenList(remaining),
        retained: frozenList(retainedResponsibilities(remaining)),
      });
    });
  }

  return Object.freeze({
    schema: NEYVIA_RUNTIME_INVOCATION_SCHEMA,
    invocations: Object.freeze([...retained, record]),
  });
}

export function closeRuntimeInvocation(registry, invocationId, reason = "") {
  const current = Array.isArray(registry?.invocations) ? registry.invocations : [];
  return Object.freeze({
    schema: NEYVIA_RUNTIME_INVOCATION_SCHEMA,
    invocations: Object.freeze(
      current.map(item =>
        item.invocationId === invocationId
          ? transitionRuntimeInvocation(item, "closed", { closedReason: String(reason || "") })
          : item,
      ),
    ),
  });
}

export function selectPrimaryRuntimeInvocation(registry, sessionId = null) {
  const current = Array.isArray(registry?.invocations) ? registry.invocations : [];
  return (
    current.find(
      item =>
        item.mode === "primary-session"
        && isInvocationOpen(item.state)
        && (sessionId == null || item.parentSessionId === sessionId || item.parentSessionId == null),
    ) || null
  );
}

export function selectEcosystemOverrides(registry) {
  const current = Array.isArray(registry?.invocations) ? registry.invocations : [];
  return current.filter(item => item.mode === "ecosystem-override" && isInvocationOpen(item.state));
}

export function selectInlineInvocations(registry, parentSessionId) {
  const current = Array.isArray(registry?.invocations) ? registry.invocations : [];
  return current.filter(
    item =>
      item.mode === "inline-tool"
      && isInvocationOpen(item.state)
      && (parentSessionId == null || item.parentSessionId === String(parentSessionId)),
  );
}

/**
 * Effective ownership for the session — what the UI must state plainly:
 * "Neyvia is the ecosystem; <runtime> is powering <responsibilities>."
 */
export function describeEffectiveRuntimeComposition(registry, sessionId = null) {
  const primary = selectPrimaryRuntimeInvocation(registry, sessionId);
  const overrides = selectEcosystemOverrides(registry);
  const inline = selectInlineInvocations(registry, sessionId);
  const delegatedBy = new Map();
  for (const item of overrides) {
    for (const responsibility of item.delegated) delegatedBy.set(responsibility, item.runtime);
  }
  return Object.freeze({
    schema: NEYVIA_RUNTIME_INVOCATION_SCHEMA,
    surfaceOwner: primary ? primary.runtime : "neyvia",
    surfaceOwnerLabel: primary ? `${primary.runtime} session inside Neyvia` : "Neyvia",
    ecosystemOwner: "neyvia",
    delegations: Object.freeze(
      [...delegatedBy.entries()].map(([responsibility, runtime]) =>
        Object.freeze({
          responsibility,
          label: responsibilityMeta(responsibility)?.label || responsibility,
          runtime,
        }),
      ),
    ),
    reserved: NEYVIA_RESERVED_RESPONSIBILITIES,
    inlineCount: inline.length,
    summary: primary
      ? `${primary.runtime} is the session surface. Neyvia keeps context, permissions, artifacts, evidence and continuity.`
      : delegatedBy.size
        ? `Neyvia is the interface. ${[...new Set(delegatedBy.values())].join(", ")} powering ${delegatedBy.size} responsibility${delegatedBy.size === 1 ? "" : "ies"}.`
        : "Neyvia runtime, no external delegation.",
  });
}

/**
 * Nothing may outlive its owning Neyvia session. Returns the invocations that
 * must be closed when a session ends, so no orphan provider process survives.
 */
export function orphanedInvocations(registry, liveSessionIds = []) {
  const live = new Set((liveSessionIds || []).map(String));
  const current = Array.isArray(registry?.invocations) ? registry.invocations : [];
  return current.filter(
    item =>
      isInvocationOpen(item.state)
      && item.parentSessionId != null
      && !live.has(String(item.parentSessionId)),
  );
}

/** Cleanup candidates for one UI owner; never a process-wide orphan sweep. */
export function invocationsOwnedBySession(registry, ownerSessionId) {
  const owner = String(ownerSessionId || "").trim();
  if (!owner) return [];
  const current = Array.isArray(registry?.invocations) ? registry.invocations : [];
  return current.filter(
    item => isInvocationOpen(item.state) && String(item.parentSessionId || "") === owner,
  );
}

/** Backend command names for the durable side of this contract. */
export const NEYVIA_RUNTIME_INVOCATION_COMMANDS = Object.freeze({
  readiness: "get_runtime_invocation_readiness_command",
  registry: "get_runtime_invocation_registry_command",
  open: "open_runtime_invocation_command",
  update: "update_runtime_invocation_command",
  close: "close_runtime_invocation_command",
  turn: "run_runtime_invocation_turn_command",
});
