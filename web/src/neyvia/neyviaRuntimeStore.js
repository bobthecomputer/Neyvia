/**
 * Shared Neyvia runtime invocation store.
 *
 * The three invocation modes have to be readable from more than the window that
 * renders them: the chat send path needs to know which runtime powers the
 * conversation loop, the shell needs to know whether a runtime owns the session
 * surface, and the ecosystem host needs to render the effective composition.
 * One process-wide registry, one durable backend record per invocation.
 */

import {
  NEYVIA_RUNTIME_INVOCATION_COMMANDS,
  canTransitionInvocation,
  closeRuntimeInvocation,
  createRuntimeInvocation,
  describeEffectiveRuntimeComposition,
  emptyRuntimeInvocationRegistry,
  isInvocationOpen,
  invocationsOwnedBySession,
  recordRuntimeReturn,
  resolveRuntimeReadiness,
  selectEcosystemOverrides,
  selectInlineInvocations,
  selectPrimaryRuntimeInvocation,
  transitionRuntimeInvocation,
  upsertRuntimeInvocation,
} from "./neyviaRuntimeInvocation.js";

let registry = emptyRuntimeInvocationRegistry();
let readiness = null;
let readinessPromise = null;
const listeners = new Set();

function emit() {
  for (const listener of listeners) {
    try {
      listener(registry);
    } catch {
      // One failing consumer must not stop the others from updating.
    }
  }
}

function setRegistry(next) {
  if (next === registry) return;
  registry = next;
  emit();
}

export function getRuntimeRegistry() {
  return registry;
}

export function subscribeRuntimeRegistry(listener) {
  if (typeof listener !== "function") return () => {};
  listeners.add(listener);
  return () => listeners.delete(listener);
}

async function callBackend(command, payload = {}) {
  const response = await fetch("/api/backend", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, payload }),
  });
  const result = await response.json();
  if (!response.ok || !result?.ok) throw new Error(result?.error || `${command} failed`);
  return result.data;
}

/* ---------------------------------------------------------------- readiness */

/** Loaded once and reused. Never assumed — a failure is reported as such. */
export function loadRuntimeReadiness({ force = false } = {}) {
  if (!force && readiness) return Promise.resolve(readiness);
  if (!force && readinessPromise) return readinessPromise;
  readinessPromise = callBackend(NEYVIA_RUNTIME_INVOCATION_COMMANDS.readiness, {})
    .then(data => {
      readiness = data;
      readinessPromise = null;
      emit();
      return data;
    })
    .catch(error => {
      readiness = { runtimeStatus: {}, error: String(error?.message || error) };
      readinessPromise = null;
      emit();
      return readiness;
    });
  return readinessPromise;
}

export function getRuntimeReadiness() {
  return readiness;
}

/* -------------------------------------------------------------- lifecycle */

/**
 * Register an invocation locally and durably. Neither side claims the runtime
 * ran: the record starts `ready`/`requested`/`blocked` from real readiness.
 */
export async function openRuntimeInvocation(detail = {}) {
  const evidence = await loadRuntimeReadiness();
  const local = createRuntimeInvocation({
    ...detail,
    readiness: resolveRuntimeReadiness(detail.runtime, evidence),
  });
  setRegistry(upsertRuntimeInvocation(registry, local));

  let durable = null;
  try {
    durable = await callBackend(NEYVIA_RUNTIME_INVOCATION_COMMANDS.open, {
      mode: local.mode,
      runtime: local.runtime,
      model: local.model,
      parentSessionId: local.parentSessionId,
      parentMissionId: local.parentMissionId,
      purpose: local.purpose,
      contextScope: local.contextScope,
      contextSelection: [...local.contextSelection],
      delegate: [...local.delegated],
      presentation: local.presentation,
      permissions: {
        inheritSession: local.permissions.inheritSession,
        approvalRequired: local.permissions.approvalRequired,
        grants: [...local.permissions.grants],
      },
    });
  } catch (error) {
    const blocked = transitionRuntimeInvocation(local, "blocked", {
      problems: Object.freeze([String(error?.message || error)]),
    });
    setRegistry(upsertRuntimeInvocation(registry, blocked));
    return blocked;
  }

  const bound = Object.freeze({ ...local, durableInvocationId: durable?.invocationId || null });
  setRegistry(upsertRuntimeInvocation(registry, bound));
  return bound;
}

export function findRuntimeInvocation(invocationId) {
  const id = String(invocationId || "");
  return (
    registry.invocations.find(
      item => item.invocationId === id || item.durableInvocationId === id,
    ) || null
  );
}

/**
 * Move an invocation along its lifecycle and mirror the move durably.
 *
 * Suspend and close are deliberately different operations. `suspended` keeps
 * the runtime session, transcript, artifacts and lineage so it can be resumed
 * without a restart; `closed` is terminal and says so.
 */
export async function transitionRuntimeInvocationById(invocationId, nextState, reason = "") {
  const record = findRuntimeInvocation(invocationId);
  if (!record) return null;
  if (!canTransitionInvocation(record.state, nextState)) return record;
  const moved = transitionRuntimeInvocation(record, nextState, reason ? { lastReason: reason } : {});
  setRegistry(upsertRuntimeInvocation(registry, moved));
  if (record.durableInvocationId) {
    try {
      await callBackend(NEYVIA_RUNTIME_INVOCATION_COMMANDS.update, {
        invocationId: record.durableInvocationId,
        state: nextState,
        reason,
      });
    } catch {
      // The durable log stays authoritative and is reconciled on next load.
    }
  }
  return moved;
}

/** Leave the runtime without ending it. Resumable, nothing restarts. */
export function suspendRuntimeInvocation(invocationId, reason = "Suspended by the operator.") {
  return transitionRuntimeInvocationById(invocationId, "suspended", reason);
}

/** Come back to the same invocation and its surrounding Neyvia session. */
export function resumeRuntimeInvocation(invocationId, reason = "Resumed by the operator.") {
  return transitionRuntimeInvocationById(invocationId, "active", reason);
}

/**
 * Merge what a runtime handed back. Nothing here is treated as proof by itself
 * — the caller still records artifacts and receipts through the normal
 * ecosystem paths; this only attaches them to the invocation that produced them.
 */
export function recordRuntimeInvocationReturn(invocationId, returns = {}) {
  const record = findRuntimeInvocation(invocationId);
  if (!record) return null;
  const updated = recordRuntimeReturn(record, returns);
  setRegistry(upsertRuntimeInvocation(registry, updated));
  return updated;
}

/** Send one real turn to the invocation's backend runtime and reconcile its return. */
export async function sendRuntimeInvocationTurn(invocationId, message, options = {}) {
  const record = findRuntimeInvocation(invocationId);
  if (!record) throw new Error("Runtime invocation not found.");
  const durableId = record.durableInvocationId || record.invocationId;
  const text = String(message || "").trim();
  if (!text) throw new Error("Write a message for the runtime.");
  const result = await callBackend(NEYVIA_RUNTIME_INVOCATION_COMMANDS.turn, {
    invocationId: durableId,
    message: text,
    idempotencyKey: options.idempotencyKey || undefined,
    workspacePath: options.workspacePath || undefined,
    effort: options.effort || undefined,
    taskProfile: options.taskProfile || undefined,
    allowMutation: options.allowMutation === true,
  });
  await refreshRuntimeInvocations({ parentSessionId: record.parentSessionId });
  return {
    ...result,
    invocation: findRuntimeInvocation(invocationId),
  };
}

/**
 * Reconcile with the durable registry.
 *
 * The backend owns runtime execution and persistence, so anything it reports —
 * state moves, returned messages, artifacts, receipts — replaces what the
 * client believed. Records the client has that the backend does not are left
 * alone rather than deleted, so an in-flight open is never dropped.
 */
export async function refreshRuntimeInvocations({ parentSessionId = null } = {}) {
  let durable = null;
  try {
    durable = await callBackend(NEYVIA_RUNTIME_INVOCATION_COMMANDS.registry, {
      parentSessionId: parentSessionId || undefined,
      includeClosed: false,
    });
  } catch {
    return null;
  }
  const rows = Array.isArray(durable?.invocations) ? durable.invocations : [];
  if (!rows.length) return durable;
  let next = registry;
  for (const row of rows) {
    const local = registry.invocations.find(
      item => item.durableInvocationId === row.invocationId || item.invocationId === row.invocationId,
    );
    if (!local) continue;
    const merged = Object.freeze({
      ...local,
      state: String(row.state || local.state),
      readiness: row.readiness && typeof row.readiness === "object" ? row.readiness : local.readiness,
      returns: Object.freeze({
        messages: Object.freeze(row.returns?.messages || local.returns.messages || []),
        artifacts: Object.freeze(row.returns?.artifacts || local.returns.artifacts || []),
        receipts: Object.freeze(row.returns?.receipts || local.returns.receipts || []),
        changes: Object.freeze(row.returns?.changes || local.returns.changes || []),
      }),
      lastTransitionAt: row.lastTransitionAt || local.lastTransitionAt,
    });
    next = upsertRuntimeInvocation(next, merged);
  }
  setRegistry(next);
  return durable;
}

export async function closeRuntimeInvocationById(invocationId, reason = "") {
  const record = findRuntimeInvocation(invocationId);
  setRegistry(closeRuntimeInvocation(registry, record?.invocationId || invocationId, reason));
  const durableId = record?.durableInvocationId;
  if (!durableId) return;
  try {
    await callBackend(NEYVIA_RUNTIME_INVOCATION_COMMANDS.close, {
      invocationId: durableId,
      reason: reason || "Closed by the operator.",
    });
  } catch {
    // The durable log stays authoritative and is reconciled on next load.
  }
}

/**
 * Close every invocation whose owning Neyvia session is gone — locally and in
 * the durable registry, so no provider lane survives without an owner.
 */
export async function reapRuntimeInvocations(liveSessionIds = [], options = {}) {
  // Cleanup is intentionally owner-scoped. A UI lifecycle callback must never
  // infer that every durable invocation absent from its snapshot is orphaned.
  const ownerSessionId = String(options?.ownerSessionId || "").trim();
  if (!ownerSessionId) return [];
  const orphans = invocationsOwnedBySession(registry, ownerSessionId);
  for (const item of orphans) {
    setRegistry(
      closeRuntimeInvocation(registry, item.invocationId, "Owning Neyvia session ended."),
    );
  }
  for (const item of orphans) {
    if (!item.durableInvocationId) continue;
    try {
      await callBackend(NEYVIA_RUNTIME_INVOCATION_COMMANDS.close, {
        invocationId: item.durableInvocationId,
        reason: "Owning Neyvia session ended.",
      });
    } catch {
      // The durable log remains authoritative and can be reconciled later.
    }
  }
  return orphans;
}

/* -------------------------------------------------------------- selectors */

export function primaryRuntimeInvocation(sessionId = null) {
  return selectPrimaryRuntimeInvocation(registry, sessionId);
}

export function ecosystemOverrides() {
  return selectEcosystemOverrides(registry);
}

export function inlineInvocations(sessionId = null) {
  return selectInlineInvocations(registry, sessionId);
}

export function runtimeComposition(sessionId = null) {
  return describeEffectiveRuntimeComposition(registry, sessionId);
}

/**
 * Which runtime powers one responsibility right now, if any.
 *
 * A `primary-session` runtime owns every responsibility for its own surface; an
 * `ecosystem-override` owns only what it named. Returns null when Neyvia's own
 * runtime is still responsible, and never returns a runtime whose readiness the
 * backend has not confirmed — an unavailable delegate must not silently
 * redirect real work.
 */
export function delegatedRuntimeFor(responsibility, sessionId = null) {
  const id = String(responsibility || "").trim();
  if (!id) return null;
  const usable = record =>
    record && record.readiness?.ready === true && ["ready", "active", "suspended", "returned"].includes(record.state);

  const primary = primaryRuntimeInvocation(sessionId);
  if (usable(primary) && primary.delegated.includes(id)) {
    return Object.freeze({
      runtime: primary.runtime,
      model: primary.model,
      mode: primary.mode,
      invocationId: primary.durableInvocationId || primary.invocationId,
      responsibility: id,
    });
  }
  const override = ecosystemOverrides().find(item => usable(item) && item.delegated.includes(id));
  if (override) {
    return Object.freeze({
      runtime: override.runtime,
      model: override.model,
      mode: override.mode,
      invocationId: override.durableInvocationId || override.invocationId,
      responsibility: id,
    });
  }
  return null;
}

/**
 * The runtime that owns the session surface, when one does. This is what makes
 * `primary-session` different from an override: the visible interface adapts.
 */
export function sessionSurfaceRuntime(sessionId = null) {
  const primary = primaryRuntimeInvocation(sessionId);
  if (!primary || !isInvocationOpen(primary.state)) return null;
  return Object.freeze({
    runtime: primary.runtime,
    model: primary.model,
    state: primary.state,
    ready: primary.readiness?.ready === true,
    readinessDetail: primary.readiness?.detail || "",
    invocationId: primary.durableInvocationId || primary.invocationId,
    parentSessionId: primary.parentSessionId,
    problems: primary.problems || [],
  });
}

/** Test/reset seam. */
export function resetRuntimeStore() {
  registry = emptyRuntimeInvocationRegistry();
  readiness = null;
  readinessPromise = null;
  emit();
}
