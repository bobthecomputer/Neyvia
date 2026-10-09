// Rough prompt in, good prompt out (plan 20 C14): the rules behind the card under the composer.
// Backend contract: plans/15-handoff.md ## C14 (prompt_amplify_command, prompt_amplification_edit_command,
// prompt.amplified / prompt.edited / prompt.consumed). The host never sends anything on a timer:
// the auto-send window lives here, in the UI, and an edit or an open question stops it.

export const AUTO_SEND_MS = 5000;
export const DEBOUNCE_MS = 1200;
export const MIN_CHARS = 12;
export const MAX_TEXT = 40000;
export const MODES = [
  { value: "auto", label: "Auto-send" },
  { value: "review", label: "Review" },
  { value: "off", label: "Off" },
];
const CHAT_TURNS = 6;
const CHAT_CHARS = 1200;

export function normalMode(value) {
  return MODES.some(mode => mode.value === value) ? value : "auto";
}

/** Whether this send goes through the card; steering, Autopilot, /compact and attachment-only sends do not. */
export function shouldAmplify({ mode, message, autopilot = false, steering = false, attachmentsOnly = false, command = false }) {
  const text = String(message || "").trim();
  return normalMode(mode) !== "off" && !autopilot && !steering && !attachmentsOnly && !command
    && text.length >= MIN_CHARS && text.length <= MAX_TEXT;
}

/** The last few turns of the chat as bounded text, so "that" and "the thing from before" can be resolved. */
export function chatContext(items) {
  const turns = [];
  for (const item of items || []) {
    if (item?.optimistic) continue;
    if (item?.kind !== "user" && item?.kind !== "assistant") continue;
    const text = String(item.data?.text || "").trim();
    if (!text) continue;
    turns.push({ role: item.kind, text: text.length > CHAT_CHARS ? `${text.slice(0, CHAT_CHARS)}…` : text });
  }
  return turns.slice(-CHAT_TURNS);
}

export function amplifyPayload({ text, requestId, sessionId, items, project, mode }) {
  // With a chat, the PC reads its turns from the broker itself; sending them again only doubles them.
  const chat = sessionId ? [] : chatContext(items);
  const context = {
    ...(project ? { project: String(project) } : {}),
    ...(chat.length ? { chat } : {}),
  };
  return {
    text: String(text || "").trim(),
    requestId,
    ...(sessionId ? { sessionId } : {}),
    ...(Object.keys(context).length ? { context } : {}),
    mode: normalMode(mode) === "review" ? "review" : "auto",
  };
}

/** A deliverable may be a sentence or a {form, path, ...} object; the card shows one line. */
export function deliverableText(value) {
  if (!value) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object") {
    const form = value.form || value.kind || value.type || "";
    const where = value.path || value.target || value.where || "";
    const words = [form, where].filter(Boolean).join(": ");
    return words || value.text || value.summary || "";
  }
  return String(value);
}

const asList = value => (Array.isArray(value) ? value : []).map(row => (typeof row === "string" ? row : row?.text || row?.target || "")).map(text => String(text).trim()).filter(Boolean);

/** The fields Paul can change on the card, starting from what the backend understood. */
export function fieldsFrom(amplification) {
  const a = amplification || {};
  return {
    goal: String(a.goal || "").trim(),
    deliverable: deliverableText(a.deliverable).trim(),
    checks: asList(a.checks),
    assumptions: asList(a.assumptions),
    constraints: asList(a.constraints),
    answers: asList(a.questions).map(() => ""),
  };
}

const sameList = (a, b) => a.length === b.length && a.every((value, index) => value.trim() === b[index].trim());

export function isEdited(amplification, fields) {
  if (!amplification || !fields) return false;
  const base = fieldsFrom(amplification);
  return base.goal !== fields.goal.trim() || base.deliverable !== fields.deliverable.trim()
    || !sameList(base.checks, fields.checks) || !sameList(base.assumptions, fields.assumptions)
    || !sameList(base.constraints, fields.constraints) || fields.answers.some(answer => answer.trim());
}

/** Questions the backend asks; each must have an answer before the prompt can go. */
export function openQuestions(amplification, fields) {
  return asList(amplification?.questions).filter((_, index) => !String(fields?.answers?.[index] || "").trim());
}

/**
 * Preserve the selected prompt and append only Paul's explicit changes.
 * Unchanged card checks and assumptions never become hidden prompt overhead.
 */
export function composeEdit(amplification, fields) {
  const base = fieldsFrom(amplification);
  const lines = [String(amplification?.agentPrompt ?? amplification?.original ?? "").trim(), ""];
  const add = (label, value) => { if (value.trim()) lines.push(`${label}: ${value.trim()}`); };
  const list = (label, values) => {
    const kept = values.map(value => value.trim()).filter(Boolean);
    if (!kept.length) return;
    lines.push(`${label}:`);
    for (const value of kept) lines.push(`- ${value}`);
  };
  if (fields.goal.trim() !== base.goal) add("Goal", fields.goal);
  if (fields.deliverable.trim() !== base.deliverable) add("Deliverable", fields.deliverable);
  if (!sameList(base.checks, fields.checks)) list("Checks", fields.checks);
  if (!sameList(base.constraints, fields.constraints)) list("Constraints", fields.constraints);
  if (!sameList(base.assumptions, fields.assumptions)) list("Assumptions", fields.assumptions);
  asList(amplification?.questions).forEach((question, index) => {
    const answer = String(fields.answers[index] || "").trim();
    if (answer) lines.push(`${question} ${answer}`);
  });
  return lines.join("\n").trim().slice(0, MAX_TEXT);
}

/**
 * What the card does next. "wait" = still amplifying or failed; "ask" = a question blocks sending;
 * "edited" = Paul changed something, he sends it himself; "count" = the auto-send window runs;
 * "review" = ready, he sends it himself.
 */
export function cardPhase({ amplification, fields, mode, held }) {
  if (!amplification) return "wait";
  if (openQuestions(amplification, fields).length) return "ask";
  if (isEdited(amplification, fields)) return "edited";
  if (amplification.status === "needs_input") return "ask";
  if (normalMode(mode) === "auto" && !held) return "count";
  return "review";
}

export function sendOptions(amplification) {
  return amplification?.id ? { amplificationId: amplification.id, amplificationRevision: amplification.revision } : {};
}

export function secondsLeft(deadline, now = Date.now()) {
  return Math.max(0, Math.ceil((deadline - now) / 1000));
}

/** One plain line about where an edit went (C9 lesson gate); never claims a lesson was learned when it was not. */
export function learningLine(learning) {
  if (!learning?.state) return "";
  const count = (learning.lessonIds || []).length;
  const lessons = count ? ` (${count} ${count === 1 ? "lesson" : "lessons"})` : "";
  switch (learning.state) {
    case "pending_gate": return "Edit kept for learning. The lesson gate hasn't tested it, so the manuals are unchanged.";
    case "submitted":
    case "queued":
    case "quarantined":
    case "testing": return `Edit sent to the lesson gate${lessons}. It is tested before any manual changes.`;
    case "promoted": return `Learned from your edit${lessons}.`;
    case "rejected": return "Edit kept. The lesson gate didn't promote it.";
    case "skipped":
    case "none": return "Edit saved. No lesson was drafted from it.";
    case "failed": return `Edit sent, but the learning step failed${learning.reason ? `: ${learning.reason}` : "."}`;
    default: return learning.reason ? `Learning: ${learning.reason}` : `Learning: ${learning.state.replaceAll("_", " ")}`;
  }
}

/** Route and time as the backend measured them, e.g. "script · 140 ms" or "gpt-6-luna · 1.8 s · 412 tokens". */
export function receiptLine(amplification) {
  if (!amplification) return "";
  const route = typeof amplification.route === "string" ? amplification.route : amplification.route?.tier || amplification.route?.name || amplification.route?.model || "";
  const ms = Number(amplification.elapsedMs);
  const time = Number.isFinite(ms) ? (ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`) : "";
  const total = typeof amplification.tokens === "number" ? amplification.tokens : amplification.tokens?.total ?? null;
  const tokens = total ? `${total.toLocaleString()} tokens` : "";
  return [route, time, tokens].filter(Boolean).join(" · ");
}

/** Context pointers the backend resolved ("that file", "plan 20"), shown as short names. */
export function pointerLabels(amplification) {
  return (amplification?.contextPointers || []).map(pointer => {
    const target = String(pointer?.target || "");
    const short = target.split(/[\\/]/).filter(Boolean).pop() || target;
    return { kind: String(pointer?.kind || ""), label: short, title: target };
  }).filter(pointer => pointer.label);
}
