import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
/**
 * Settle chat turns whose response was running when this window was not.
 *
 * A reply shows as "Thinking…" until the window that sent it hears back. If
 * the app crashed or was closed mid-response, the reopened window restores
 * that pending turn but nothing will ever answer it: its stream never ends and
 * Stop reaches no one. The backend knows better — it can tell whether the
 * turn's process is still alive, and it keeps the final result — so this
 * module turns the backend's run status into one of three decisions:
 *
 *   watch   the response is really still running; keep showing its progress
 *   settle  it ended (finished, stopped, failed, or interrupted); show that
 *   wait    not enough is known yet; ask again shortly
 *
 * It never invents a reply. A partial streamed answer is kept as partial and
 * labelled as interrupted.
 */

import { cancelledChatTurnPatch, isChatCancellationResult } from "./chatCancellation.js";
import { normalizeNeyviaChatStreamToolCalls } from "./neyviaChatStream.js";

export const INTERRUPTED_CHAT_SOURCE = "chat-interrupted";
/** A turn with no run record may just not have registered yet. */
export const UNREGISTERED_TURN_GRACE_MS = 2 * 60 * 1000;
/** The run record can reach "finished" a moment before its result is saved. */
export const MISSING_RESULT_GRACE_MS = 8 * 1000;
/** After this long without output, the running indicator says it is quiet. */
export const QUIET_RESPONSE_MS = 90 * 1000;

const PLACEHOLDER_TITLE = /^(thinking|working|starting with)\b/i;

function epochMs(value) {
  if (value == null || value === "") return NaN;
  if (typeof value === "number") return value < 1e12 ? value * 1000 : value;
  const parsed = Date.parse(String(value));
  return Number.isFinite(parsed) ? parsed : NaN;
}

function hasStreamedText(turn) {
  const title = String(turn?.title || "").trim();
  return Boolean(title) && !PLACEHOLDER_TITLE.test(title);
}

/**
 * Fold a fully replayed event stream into a restored turn. The saved copy
 * can lag the stream by the last few seconds before a crash; the stream file
 * is the complete record of what arrived.
 */
function mergeStreamedTraceUnchecked(turn = {}, streamed = null) {
  if (!streamed) return turn;
  const answer = String(streamed.answer || "");
  const current = hasStreamedText(turn) ? String(turn.title) : "";
  const toolCalls = Array.isArray(streamed.toolCalls) && streamed.toolCalls.length
    ? normalizeNeyviaChatStreamToolCalls(streamed.toolCalls)
    : turn.toolCalls;
  return {
    ...turn,
    title: answer.trim() && answer.length >= current.length ? answer : turn.title,
    source: answer.trim() && answer.length >= current.length ? "runtime-stream" : turn.source,
    reasoningSummary: streamed.reasoningSummary || turn.reasoningSummary || "",
    toolCalls,
    activitySegments: Array.isArray(streamed.activitySegments) && streamed.activitySegments.length
      ? streamed.activitySegments
      : turn.activitySegments,
    activityOrderKnown: Array.isArray(streamed.activitySegments) && streamed.activitySegments.length
      ? true
      : Boolean(turn.activityOrderKnown),
  };
}

/** Tool calls that never reported an outcome did not finish. */
export function interruptedToolCalls(calls) {
  return (Array.isArray(calls) ? calls : []).map(call =>
    ["started", "running"].includes(String(call?.status || "").toLowerCase())
      ? { ...call, status: "interrupted" }
      : call,
  );
}

/**
 * Pending assistant turns that no request in this window is waiting for.
 * Newest first, so the conversation the person is looking at settles first.
 */
function unownedPendingChatTurnsUnchecked(transcripts, ownedTurnIds = new Set(), limit = 12) {
  const rows = [];
  for (const [sessionId, turns] of Object.entries(transcripts || {})) {
    for (const turn of Array.isArray(turns) ? turns : []) {
      if (turn?.role !== "assistant" || !turn.pending || !turn.id) continue;
      if (ownedTurnIds.has(String(turn.id))) continue;
      rows.push({ sessionId, turn });
    }
  }
  rows.sort((left, right) => (epochMs(right.turn.createdAt) || 0) - (epochMs(left.turn.createdAt) || 0));
  return rows.slice(0, Math.max(0, limit));
}

function interruptedChatTurnPatchUnchecked(turn = {}, message = "") {
  const reason = String(message || "").trim() || "Neyvia closed while this response was running, so it could not finish.";
  const partial = hasStreamedText(turn);
  return {
    title: partial ? String(turn.title) : "This response was interrupted before a reply arrived.",
    detail: partial ? `${reason} The text above is what arrived before it stopped.` : reason,
    pending: false,
    tone: "warn",
    source: INTERRUPTED_CHAT_SOURCE,
    toolCalls: interruptedToolCalls(turn.toolCalls),
  };
}

/** Map a recorded backend result onto the turn, mirroring the live send path. */
function recordedResultChatTurnPatchUnchecked(turn = {}, result = {}, { cleanReply = value => String(value || "").trim() } = {}) {
  const compartment = result?.compartment && typeof result.compartment === "object" ? result.compartment : {};
  const reply = cleanReply(result?.reply || result?.finalMessage || result?.message);
  if (isChatCancellationResult(result)) {
    return { ...cancelledChatTurnPatch(turn, reply), toolCalls: interruptedToolCalls(turn.toolCalls) };
  }
  const status = String(result?.status || compartment.state || "").toLowerCase();
  const failed = result?.ok === false || ["failed", "error", "timeout", "stop_unconfirmed"].includes(status);
  const error = String(result?.error || (Array.isArray(compartment.errors) ? compartment.errors[0] : "") || "").trim();
  return {
    title: reply || (failed ? "The runtime failed before a readable reply." : "The runtime finished without a readable reply."),
    detail: failed ? error || "The runtime failed." : "",
    pending: false,
    tone: failed ? "bad" : reply ? "neutral" : "warn",
    source: failed ? "backend-runtime-error" : reply ? "backend-runtime-reply" : "backend-runtime-empty",
    runtimeId: result?.runtime || compartment.runtime || turn.runtimeId || "",
    rawTurnReceipt: compartment.turnReceipt || result?.turnReceipt || null,
    rawReceiptFallback: {
      runtime: compartment.runtime || result?.runtime,
      route: compartment.route || result?.route,
      changedFiles: compartment.filesChanged || result?.filesChanged,
      proofArtifacts: compartment.proofArtifacts || result?.proofArtifacts,
      toolTimeline: compartment.toolTimeline || result?.toolTimeline,
      durationMs: compartment.lastRoundtripMs ?? result?.elapsedMs,
      finalMessage: reply,
    },
  };
}

/**
 * Decide what a pending turn needs, given `get_agent_chat_run_status_command`.
 * @returns {{action: "wait"|"watch"|"settle", patch?: object, lastActivityAt?: number}}
 */
function chatRecoveryDecisionUnchecked(status, turn = {}, { now = Date.now(), cleanReply } = {}) {
  if (!status || typeof status !== "object") return { action: "wait" };
  const state = String(status.status || "").toLowerCase();
  const lastActivityAt = epochMs(status.lastActivityAt);
  if (state === "running") {
    return { action: "watch", ...(Number.isFinite(lastActivityAt) ? { lastActivityAt } : {}) };
  }
  if (status.result && typeof status.result === "object" && state !== "interrupted") {
    return { action: "settle", patch: recordedResultChatTurnPatch(turn, status.result, { cleanReply }) };
  }
  if (state === "interrupted") {
    return { action: "settle", patch: interruptedChatTurnPatch(turn, status.message) };
  }
  if (["finished", "failed", "cancelled"].includes(state)) {
    const finishedAt = epochMs(status.finishedAt);
    if (Number.isFinite(finishedAt) && now - finishedAt < MISSING_RESULT_GRACE_MS) return { action: "wait" };
    if (state === "cancelled") {
      return { action: "settle", patch: { ...cancelledChatTurnPatch(turn), toolCalls: interruptedToolCalls(turn.toolCalls) } };
    }
    return {
      action: "settle",
      patch: interruptedChatTurnPatch(
        turn,
        state === "failed"
          ? "The runtime failed while this window was away, and its error was not saved."
          : "This response ended while this window was away, and its final text was not saved.",
      ),
    };
  }
  // No run record: it either has not registered yet or predates run records.
  const createdAt = epochMs(turn.createdAt);
  if (Number.isFinite(createdAt) && now - createdAt < UNREGISTERED_TURN_GRACE_MS) return { action: "wait" };
  return {
    action: "settle",
    patch: interruptedChatTurnPatch(turn, "No running process owns this response anymore, so it cannot finish."),
  };
}

/** Human label for a running response that has gone quiet, or "". */
function quietResponseLabelUnchecked(lastActivityAt, now = Date.now()) {
  const last = epochMs(lastActivityAt);
  if (!Number.isFinite(last)) return "";
  const quietMs = now - last;
  if (quietMs < QUIET_RESPONSE_MS) return "";
  const minutes = Math.floor(quietMs / 60000);
  return minutes < 2 ? "No new output for over a minute" : `No new output for ${minutes} min`;
}

export function interruptedChatTurnPatch(...args) {
  const before = frontendContractBefore("recovery.interrupted", args);
  return checkedFrontendAction("recovery.interrupted", args, interruptedChatTurnPatchUnchecked(...args), before);
}

export function chatRecoveryDecision(...args) {
  const before = frontendContractBefore("recovery.decision", args);
  return checkedFrontendAction("recovery.decision", args, chatRecoveryDecisionUnchecked(...args), before);
}

export function recordedResultChatTurnPatch(...args) {
  const before = frontendContractBefore("recovery.recorded", args);
  return checkedFrontendAction("recovery.recorded", args, recordedResultChatTurnPatchUnchecked(...args), before);
}

export function unownedPendingChatTurns(...args) {
  const before = frontendContractBefore("recovery.unowned", args);
  return checkedFrontendAction("recovery.unowned", args, unownedPendingChatTurnsUnchecked(...args), before);
}

export function quietResponseLabel(...args) {
  const before = frontendContractBefore("recovery.quiet", args);
  return checkedFrontendAction("recovery.quiet", args, quietResponseLabelUnchecked(...args), before);
}

export function mergeStreamedTrace(...args) {
  const before = frontendContractBefore("recovery.merge", args);
  return checkedFrontendAction("recovery.merge", args, mergeStreamedTraceUnchecked(...args), before);
}
