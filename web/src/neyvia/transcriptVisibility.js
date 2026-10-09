import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
/**
 * Which transcript turns are real enough to show the user.
 *
 * This is the most dangerous logic in the interface, so it lives here by itself
 * rather than as literals buried in a 20k-line component.
 *
 * The transcript deliberately hides turns that are not genuine conversation —
 * route metadata, verification probes, generated context follow-ups — because
 * showing them would fake a conversation the provider never had. But the same
 * filter is exactly how real messages disappear: it works from an allowlist of
 * `source` strings, so a provider path that reports an unrecognised source is
 * dropped *silently*, and the interface looks broken while the backend looks
 * fine. That failure previously cost weeks of debugging.
 *
 * Two rules follow from that, and both are enforced by tests:
 *
 *   1. The allowlist is a named, exported constant. Renaming a source breaks a
 *      test instead of quietly emptying somebody's transcript.
 *   2. A dropped turn can always explain itself. `describeHiddenTurn` turns
 *      "nothing appeared" into a specific, checkable reason.
 */

/** Sources that represent genuine dialogue — a person or a provider speaking. */
export const REAL_AGENT_DIALOGUE_SOURCES = Object.freeze([
  "operator-submitted",
  "runtime-error",
  "backend-runtime-error",
  "backend-runtime-empty",
  "chat-cancelled",
  "chat-interrupted",
  "backend-model-message",
  "backend-runtime-reply",
  "runtime-stream",
  "runtime-compartment",
  "runtime_compartment",
]);

/** The subset that represents a provider's own reply, as opposed to the user's. */
export const REAL_RUNTIME_REPLY_SOURCES = Object.freeze([
  "backend-model-message",
  "backend-runtime-reply",
  "runtime-stream",
  "runtime-compartment",
  "runtime_compartment",
]);

/** Roles that can appear in a transcript at all. */
export const TRANSCRIPT_ROLES = Object.freeze(["assistant", "user", "operator"]);

function normalize(value) {
  return String(value ?? "").trim().toLowerCase();
}

export function isRealAgentDialogueSource(source) {
  return REAL_AGENT_DIALOGUE_SOURCES.includes(normalize(source));
}

function isRealRuntimeReplySourceUnchecked(source) {
  return REAL_RUNTIME_REPLY_SOURCES.includes(normalize(source));
}

/** Collect a turn's text the same way every visibility check must. */
export function transcriptTurnText(item) {
  return [item?.title, item?.detail, item?.text, item?.message, item?.content]
    .map(value => String(value ?? "").trim())
    .filter(Boolean)
    .join("\n");
}

/**
 * Explain why a turn is not shown, or return `null` when it is shown.
 *
 * The point is diagnosis: an empty transcript should never be a mystery. Every
 * reason names the specific condition, so "the backend returned it but I can't
 * see it" becomes a one-line answer instead of an investigation.
 *
 * `classifiers` lets the caller pass the shell's content predicates in without
 * this module having to depend on the shell.
 */
function describeHiddenTurnUnchecked(item, classifiers = {}) {
  if (!item) return "The turn was empty.";
  if (item.pending) return "The turn is still pending and has not completed.";

  const role = normalize(item.role);
  if (!TRANSCRIPT_ROLES.includes(role)) {
    return `The turn's role ${JSON.stringify(item.role ?? null)} is not a transcript role.`;
  }

  const text = transcriptTurnText(item);
  if (!text) return "The turn carried no text in any known field.";

  const {
    isRouteMetadataText = () => false,
    isGeneratedContextFollowUpTurnText = () => false,
    isVerificationProbeDialogueTurnText = () => false,
  } = classifiers;

  if (isRouteMetadataText(text)) return "The turn is route metadata, not dialogue.";
  if (isGeneratedContextFollowUpTurnText(text)) return "The turn is a generated context follow-up.";
  if (isVerificationProbeDialogueTurnText(text)) return "The turn is a verification probe.";

  if (!isRealAgentDialogueSource(item.source)) {
    // The silent-drop case, now loud. An unrecognised source is far more often
    // a renamed provider path than genuine noise.
    return (
      `The turn's source ${JSON.stringify(item.source ?? null)} is not a recognised dialogue source. ` +
      `Recognised sources: ${REAL_AGENT_DIALOGUE_SOURCES.join(", ")}. ` +
      `If this is a real provider reply, its source must be added to REAL_AGENT_DIALOGUE_SOURCES.`
    );
  }

  return null;
}

/** Runtime replies store their body in title; detail can contain route receipts. */
function dialogueBodyUnchecked(turn) {
  if (["runtime-error", "backend-runtime-error", "backend-runtime-empty"].includes(turn?.source)) {
    return turn.detail || turn.title || turn.content || "The runtime returned no reply.";
  }
  if (["backend-runtime-reply", "backend-model-message", "operator-submitted", "runtime-pending", "runtime-stream", "chat-cancelled", "chat-interrupted"].includes(turn?.source)) {
    return turn.title || turn.content || turn.message || turn.detail || "";
  }
  return turn?.content || turn?.detail || turn?.message || turn?.title || "";
}

export function isRealRuntimeReplySource(...args) {
  const before = frontendContractBefore("chat.runtime-source", args);
  return checkedFrontendAction("chat.runtime-source", args, isRealRuntimeReplySourceUnchecked(...args), before);
}

export function describeHiddenTurn(...args) {
  const before = frontendContractBefore("chat.stopped-visibility", args);
  return checkedFrontendAction("chat.stopped-visibility", args, describeHiddenTurnUnchecked(...args), before);
}

export function dialogueBody(...args) {
  const before = frontendContractBefore("chat.stopped-body", args);
  return checkedFrontendAction("chat.stopped-body", args, dialogueBodyUnchecked(...args), before);
}
