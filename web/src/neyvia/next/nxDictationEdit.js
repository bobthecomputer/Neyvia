// Prompt dictation: applying one spoken utterance to a text field.
import { checkedDictationAction } from "./nxDictationContracts.js";
// The backend parses the utterance into ordered segments (text, or a command like new_line / scratch / send);
// this file executes them on the field's text, in order, under executable manual contracts.

// Words that start a sentence with a capital only because the engine thinks a sentence starts there.
const SOFT_STARTS = new Set("the a an and but or so then also it this that these those we you they he she there here to for of in on at with if when because please just now maybe".split(" "));

/** Where the dictation point moves when the text changed while Paul was talking (he typed, or a model wrote). */
function _shiftAnchor(previous, next, anchor) {
  if (previous === next) return anchor;
  const at = Math.max(0, Math.min(anchor, previous.length));
  const head = previous.slice(0, at);
  const tail = previous.slice(at);
  const grew = next.length - previous.length;
  // Typed exactly at the dictation point: the dictation follows the typing, like the caret does.
  if (grew > 0 && next.startsWith(head) && next.slice(at + grew) === tail) return at + grew;
  if (next.startsWith(head)) return Math.min(at, next.length);
  if (next.endsWith(tail)) return Math.max(0, next.length - tail.length);
  return Math.min(at, next.length);
}

/** Does the text end in the middle of a sentence (so the next words continue it)? */
function _endsMidSentence(text) {
  const trimmed = text.replace(/[ \t]+$/, "");
  if (!trimmed || /\n$/.test(trimmed)) return false;
  return !/[.!?:;…]["')\]]*$/.test(trimmed);
}

/** Join spoken text onto what's already there: one space, and no capital when it continues a sentence. */
function _joinSpoken(before, spoken) {
  let text = spoken.replace(/^\s+/, "");
  if (!text) return before;
  if (!before.trim() || !endsMidSentence(before)) {
    // A new sentence starts with a capital (after a scratch, a new line, or at the start of the box).
    text = text.replace(/^(["'(]?)(\p{Ll})/u, (all, open, letter) => open + letter.toUpperCase());
  } else {
    const first = text.match(/^([A-Za-zÀ-ÿ']+)/)?.[1] || "";
    if (first && SOFT_STARTS.has(first.toLowerCase()) && first[0] !== first[0].toLowerCase() && first.slice(1) === first.slice(1).toLowerCase()) {
      text = first[0].toLowerCase() + text.slice(1);
    }
  }
  const lead = before && !/\s$/.test(before) && !/^[,.;:!?)]/.test(text) ? " " : "";
  return `${before}${lead}${text}`;
}

/** Start index of the last sentence in text (after the last . ! ? or line break that has text after it). */
function _lastSentenceStart(text) {
  const body = text.replace(/\s+$/, "");
  if (!body) return 0;
  let cut = 0;
  const pattern = /([.!?…]["')\]]*)(\s+)|(\n+)/g;
  let match;
  while ((match = pattern.exec(body))) {
    const end = match.index + match[0].length;
    if (end < body.length) cut = end;
  }
  return cut;
}

/** Remove the last phrase: back to the previous comma or sentence end (what "scratch that" takes back). */
function _dropLastPhrase(text) {
  const body = text.replace(/\s+$/, "");
  let cut = 0;
  const pattern = /[.!?…,;:]["')\]]*\s+|\n+/g;
  let match;
  while ((match = pattern.exec(body))) {
    const end = match.index + match[0].length;
    if (end < body.length) cut = end;
  }
  return body.slice(0, cut).replace(/[ \t]+$/, "");
}

/** Remove the last sentence (and the space before it). */
function _dropLastSentence(text) {
  const start = lastSentenceStart(text);
  return text.slice(0, start).replace(/[ \t]+$/, "");
}

function trimEndSpaces(text) {
  return text.replace(/[ \t]+$/, "");
}

/**
 * Apply one utterance's segments at `anchor`.
 * - text: joined with spacing/capital rules
 * - new_line / new_paragraph: a line break / blank line
 * - scratch: drops the last sentence spoken in this utterance; with nothing spoken yet, the previous dictation
 * - delete_last_sentence: drops the last sentence before this point (this utterance's or the field's)
 * - undo: the previous dictation is undone (the caller does it: it owns the history)
 * - send: the caller sends after a short preview
 * - cancel: nothing from this utterance is kept
 * Returns { value, caret, inserted, start, end, actions: { undo, send, cancel, scratchPrevious }, done: [ops] }.
 */
function _applySegments(value, anchor, segments) {
  const at = Math.max(0, Math.min(anchor ?? value.length, value.length));
  let before = value.slice(0, at);
  const after = value.slice(at);
  const base = before;  // the field before this utterance (may shrink with delete_last_sentence)
  let spoken = "";      // this utterance's own text
  const actions = { undo: false, send: false, cancel: false, scratchPrevious: false };
  const done = [];
  for (const segment of segments || []) {
    if (!segment) continue;
    if (segment.type === "text") {
      let text = String(segment.text || "");
      if (!spoken.trim() || /[\n.,;:!?…]\s*$/.test(spoken)) text =text.replace(/^[\s.,;:!?…]+/, "");
      // The engine's own full stop after a command ("New paragraph.") is not content.
      if (/[\p{L}\p{N}]/u.test(text)) spoken = spoken ? joinSpoken(spoken, text) : text.trim();
      continue;
    }
    if (segment.type !== "command") continue;
    const op = segment.op || segment.name;
    done.push(op);
    if (op === "new_line") spoken = `${trimEndSpaces(spoken)}\n`;
    else if (op === "new_paragraph") spoken = `${trimEndSpaces(spoken).replace(/\n+$/, "")}\n\n`;
    else if (op === "scratch") {
      if (spoken.trim()) spoken = dropLastPhrase(spoken);
      else actions.scratchPrevious = true;
    } else if (op === "delete_last_sentence") {
      if (spoken.trim()) spoken = dropLastSentence(spoken);
      else before = dropLastSentence(before);
    } else if (op === "undo") actions.undo = true;
    else if (op === "send") actions.send = true;
    else if (op === "cancel") actions.cancel = true;
  }
  if (actions.cancel) return { value, caret: at, inserted: "", start: at, end: at, actions, done };
  // Line breaks spoken at the very start attach to the field without a joining space.
  let joined;
  if (!spoken) joined = before;
  else if (/^\n/.test(spoken)) joined = `${trimEndSpaces(before)}${spoken}`;
  else joined = joinSpoken(before, spoken);
  const start = Math.min(before.length, base.length);
  const trail = spoken && after && !/^\s/.test(after) && !/\s$/.test(joined) ? " " : "";
  const result = `${joined}${trail}${after}`;
  return { value: result, caret: joined.length, inserted: joined.slice(start), start, end: joined.length, actions, done };
}

/** Render text for the field overlay: the stable words and the grey provisional ones, joined like the final will be. */
function _previewParts(value, anchor, stable, provisional) {
  const at = Math.max(0, Math.min(anchor ?? value.length, value.length));
  const before = value.slice(0, at);
  const after = value.slice(at);
  const withStable = stable ? joinSpoken(before, stable) : before;
  const stableText = withStable.slice(before.length);
  const withAll = provisional ? joinSpoken(withStable, provisional) : withStable;
  const provisionalText = withAll.slice(withStable.length);
  const trail = after && !/^\s/.test(after) && (stableText || provisionalText) ? " " : "";
  return { before, stable: stableText, provisional: provisionalText, after: `${trail}${after}` };
}

const wordKey = word => word.toLowerCase().replace(/[^\p{L}\p{N}']/gu, "");

/** The provisional words without the ones already settled (a decode window can start inside the stable text). */
function _withoutOverlap(stable, provisional) {
  const settled = stable.split(/\s+/).filter(Boolean);
  const fresh = provisional.split(/\s+/).filter(Boolean);
  // A whole-utterance decode repeats everything: drop the settled words from its start.
  const settledKeys = settled.map(wordKey).filter(Boolean);
  const freshKeys = fresh.map(wordKey);
  if (settledKeys.length && freshKeys.length > settledKeys.length) {
    let at = 0;
    let index = 0;
    for (; index < fresh.length && at < settledKeys.length; index++) {
      if (!freshKeys[index]) continue;
      if (freshKeys[index] !== settledKeys[at]) break;
      at++;
    }
    if (at === settledKeys.length) return fresh.slice(index).join(" ");
  }
  for (let size = Math.min(settled.length, fresh.length); size > 0; size--) {
    const tail = settled.slice(settled.length - size).map(wordKey).join(" ");
    const head = fresh.slice(0, size).map(wordKey).join(" ");
    if (tail && tail === head) return fresh.slice(size).join(" ");
  }
  return provisional.trim();
}

/** One answer from the stream (append or finish), normalised so an older backend still works. */
function _normalizeAnswer(answer, final = false) {
  const data = answer || {};
  const hasStable = typeof data.stable === "string";
  const stable = hasStable ? data.stable : final ? String(data.text || "") : "";
  const provisional = hasStable ? withoutOverlap(stable, String(data.provisional || "")) : final ? "" : String(data.partial || "");
  let segments = Array.isArray(data.segments) ? data.segments : null;
  if (!segments && final) segments = String(data.text || "").trim() ? [{ type: "text", text: String(data.text).trim() }] : [];
  return {
    ...data,
    stable, provisional, segments: segments || [],
    revision: data.revision && typeof data.revision === "object" ? data.revision : null,
    fixes: Array.isArray(data.fixes) ? data.fixes : [],
    policy: hasStable || Array.isArray(data.segments),  // false: the backend predates prompt dictation
  };
}

/** Commands to show as chips while talking (only the ones already decided). */
function _liveCommands(segments) {
  return (segments || []).filter(segment => segment?.type === "command").map(segment => segment.op || segment.name);
}

export const COMMAND_LABELS = {
  new_line: "New line",
  new_paragraph: "New paragraph",
  scratch: "Scratch that",
  undo: "Undo",
  delete_last_sentence: "Delete last sentence",
  send: "Send",
  cancel: "Cancel",
};

export const LANGUAGE_LABELS = { en: "English", fr: "French", mixed: "French and English" };

// Every composer/Notes call passes the manual postcondition before it can expose
// changed text. Startup procedures enter through these same public functions.
export function shiftAnchor(previous, next, anchor) { return checkedDictationAction("shiftAnchor", [previous, next, anchor], _shiftAnchor(previous, next, anchor)); }
export function endsMidSentence(text) { return checkedDictationAction("endsMidSentence", [text], _endsMidSentence(text)); }
export function joinSpoken(before, spoken) { return checkedDictationAction("joinSpoken", [before, spoken], _joinSpoken(before, spoken)); }
export function lastSentenceStart(text) { return checkedDictationAction("lastSentenceStart", [text], _lastSentenceStart(text)); }
export function dropLastPhrase(text) { return checkedDictationAction("dropLastPhrase", [text], _dropLastPhrase(text)); }
export function dropLastSentence(text) { return checkedDictationAction("dropLastSentence", [text], _dropLastSentence(text)); }
export function applySegments(value, anchor, segments) { return checkedDictationAction("applySegments", [value, anchor, segments], _applySegments(value, anchor, segments)); }
export function previewParts(value, anchor, stable, provisional) { return checkedDictationAction("previewParts", [value, anchor, stable, provisional], _previewParts(value, anchor, stable, provisional)); }
export function withoutOverlap(stable, provisional) { return checkedDictationAction("withoutOverlap", [stable, provisional], _withoutOverlap(stable, provisional)); }
export function normalizeAnswer(answer, final = false) { return checkedDictationAction("normalizeAnswer", [answer, final], _normalizeAnswer(answer, final)); }
export function liveCommands(segments) { return checkedDictationAction("liveCommands", [segments], _liveCommands(segments)); }
