// Executable manual claims. These run on the actual arguments and result of every
// editor action; startup procedures use the same entry points as the composer.
export class DictationContractError extends Error {
  constructor(id, claim) {
    super(`Dictation contract ${id}: ${claim}`);
    this.name = "DictationContractError";
    this.contract = id;
    // Never include dictated content in an error or receipt.
  }
}

const equal = (a, b) => {
  if (Object.is(a, b)) return true;
  if (!a || !b || typeof a !== "object" || typeof b !== "object" || Array.isArray(a) !== Array.isArray(b)) return false;
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every(name => Object.prototype.hasOwnProperty.call(b, name) && equal(a[name], b[name]));
};
const softStarts = new Set("the a an and but or so then also it this that these those we you they he she there here to for of in on at with if when because please just now maybe".split(" "));
const key = word => word.toLowerCase().replace(/[^\p{L}\p{N}']/gu, "");
const bounded = (value, anchor) => Math.max(0, Math.min(anchor ?? value.length, value.length));
const trimSpaces = value => value.replace(/[ \t]+$/, "");

function joinClaim(before, spoken) {
  const content = spoken.replace(/^\s+/, "");
  if (!content) return before;
  const first = content.match(/^([A-Za-zÀ-ÿ']+)/)?.[1] || "";
  const midSentence = !!trimSpaces(before) && !/\n$/.test(trimSpaces(before)) && !/[.!?:;…]["')\]]*$/.test(trimSpaces(before));
  let words = content;
  if (!before.trim() || !midSentence) words = content.replace(/^(["'(]?)(\p{Ll})/u, (_, open, letter) => open + letter.toUpperCase());
  else if (softStarts.has(first.toLowerCase()) && first[0] !== first[0]?.toLowerCase() && first.slice(1) === first.slice(1).toLowerCase()) words = first[0].toLowerCase() + content.slice(1);
  return before + (before && !/\s$/.test(before) && !/^[,.;:!?)]/.test(words) ? " " : "") + words;
}

function sentenceBoundary(text, phrase = false) {
  const body = text.trimEnd();
  // A deletion may only stop at a complete phrase/sentence boundary, keeping
  // every earlier character. The final terminator belongs to the deleted part.
  const delimiters = phrase ? /[.!?…,;:]["')\]]*\s+|\n+/g : /[.!?…]["')\]]*\s+|\n+/g;
  return [...body.matchAll(delimiters)].map(match => match.index + match[0].length).filter(end => end < body.length).at(-1) || 0;
}

function overlapClaim(stable, provisional) {
  const settled = stable.split(/\s+/).filter(Boolean), fresh = provisional.split(/\s+/).filter(Boolean);
  const required = settled.map(key).filter(Boolean);
  const freshKeys = fresh.map(key);
  if (required.length && fresh.length > required.length) {
    const meaningful = freshKeys.map((value, index) => ({ value, index })).filter(row => row.value);
    if (equal(meaningful.slice(0, required.length).map(row => row.value), required)) return fresh.slice(meaningful[required.length - 1].index + 1).join(" ");
  }
  const sizes = Array.from({ length: Math.min(settled.length, fresh.length) }, (_, index) => index + 1).reverse();
  const size = sizes.find(count => settled.slice(-count).map(key).join(" ") && settled.slice(-count).map(key).join(" ") === freshKeys.slice(0, count).join(" "));
  return size ? fresh.slice(size).join(" ") : provisional.trim();
}

function segmentClaim(value, anchor, segments) {
  const at = bounded(value, anchor), originalPrefix = value.slice(0, at), suffix = value.slice(at);
  const state = { prefix: originalPrefix, speech: "", undo: false, send: false, cancel: false, scratchPrevious: false, done: [] };
  for (const segment of segments || []) {
    if (segment?.type === "text") {
      let content = String(segment.text || "");
      if (!state.speech.trim() || /[\n.,;:!?…]\s*$/.test(state.speech)) content = content.replace(/^[\s.,;:!?…]+/, "");
      if (/[\p{L}\p{N}]/u.test(content)) state.speech = state.speech ? joinClaim(state.speech, content) : content.trim();
    } else if (segment?.type === "command") {
      const op = segment.op || segment.name;
      state.done.push(op);
      switch (op) {
        case "new_line": state.speech = trimSpaces(state.speech) + "\n"; break;
        case "new_paragraph": state.speech = trimSpaces(state.speech).replace(/\n+$/, "") + "\n\n"; break;
        case "scratch":
          if (state.speech.trim()) state.speech = trimSpaces(state.speech.trimEnd().slice(0, sentenceBoundary(state.speech, true)));
          else state.scratchPrevious = true;
          break;
        case "delete_last_sentence":
          if (state.speech.trim()) state.speech = trimSpaces(state.speech.slice(0, sentenceBoundary(state.speech)));
          else state.prefix = trimSpaces(state.prefix.slice(0, sentenceBoundary(state.prefix)));
          break;
        case "undo": case "send": case "cancel": state[op] = true; break;
      }
    }
  }
  const actions = { undo: state.undo, send: state.send, cancel: state.cancel, scratchPrevious: state.scratchPrevious };
  if (state.cancel) return { value, caret: at, inserted: "", start: at, end: at, actions, done: state.done };
  const joined = !state.speech ? state.prefix : /^\n/.test(state.speech) ? trimSpaces(state.prefix) + state.speech : joinClaim(state.prefix, state.speech);
  const start = Math.min(state.prefix.length, originalPrefix.length);
  const trail = state.speech && suffix && !/^\s/.test(suffix) && !/\s$/.test(joined) ? " " : "";
  return { value: joined + trail + suffix, caret: joined.length, inserted: joined.slice(start), start, end: joined.length, actions, done: state.done };
}

export const DICTATION_CONTRACTS = Object.freeze({
  shiftAnchor: { id: "dictation.anchor", claim: "Insertion at/before the caret follows typing; edits after it retain the prefix anchor", check: ([previous, next, anchor], result) => {
    if (previous === next) return result === anchor;
    const at = Math.max(0, Math.min(anchor, previous.length)), prefix = previous.slice(0, at), suffix = previous.slice(at), growth = next.length - previous.length;
    const expected = growth > 0 && next.startsWith(prefix) && next.slice(at + growth) === suffix ? at + growth : next.startsWith(prefix) ? Math.min(at, next.length) : next.endsWith(suffix) ? Math.max(0, next.length - suffix.length) : Math.min(at, next.length);
    return Object.is(result, expected);
  } },
  endsMidSentence: { id: "dictation.sentence-state", claim: "Only an unterminated nonblank line continues a sentence", check: ([text], result) => result === (!!trimSpaces(text) && !/\n$/.test(trimSpaces(text)) && !/[.!?:;…]["')\]]*$/.test(trimSpaces(text))) },
  joinSpoken: { id: "dictation.join", claim: "Preserve the field prefix, sentence capitalization, names and punctuation spacing", check: ([before, spoken], result) => result === joinClaim(before, spoken) },
  lastSentenceStart: { id: "dictation.sentence-boundary", claim: "The last sentence starts after the latest complete terminator or line boundary", check: ([text], result) => result === sentenceBoundary(text) },
  dropLastPhrase: { id: "dictation.scratch", claim: "Scratch removes only the final phrase and its joining horizontal spaces", check: ([text], result) => result === trimSpaces(text.trimEnd().slice(0, sentenceBoundary(text, true))) },
  dropLastSentence: { id: "dictation.delete-sentence", claim: "Delete only the final sentence, preserving prior lines", check: ([text], result) => result === trimSpaces(text.slice(0, sentenceBoundary(text))) },
  applySegments: { id: "dictation.edit", claim: "Execute segments in order; preserve suffix; cancel restores original; caller owns send/undo/history", check: (args, result) => equal(result, segmentClaim(...args)) },
  previewParts: { id: "dictation.preview", claim: "Preview uses commit spacing/capitalization while retaining stable/provisional separation", check: ([value, anchor, stable, provisional], result) => {
    const at = bounded(value, anchor), before = value.slice(0, at), after = value.slice(at);
    const settled = stable ? joinClaim(before, stable) : before, all = provisional ? joinClaim(settled, provisional) : settled;
    const stableText = settled.slice(before.length), provisionalText = all.slice(settled.length);
    return equal(result, { before, stable: stableText, provisional: provisionalText, after: (after && !/^\s/.test(after) && (stableText || provisionalText) ? " " : "") + after });
  } },
  withoutOverlap: { id: "dictation.overlap", claim: "Remove the longest settled suffix or complete decode prefix, preserving fresh words", check: ([stable, provisional], result) => result === overlapClaim(stable, provisional) },
  normalizeAnswer: { id: "dictation.answer", claim: "Legacy partial/final text remains usable; current stable words and command segments survive normalization", check: ([answer, final = false], result) => {
    const data = answer || {}, modern = typeof data.stable === "string";
    const stable = modern ? data.stable : final ? String(data.text || "") : "";
    const segments = Array.isArray(data.segments) ? data.segments : final && String(data.text || "").trim() ? [{ type: "text", text: String(data.text).trim() }] : [];
    return equal(result, { ...data, stable, provisional: modern ? overlapClaim(stable, String(data.provisional || "")) : final ? "" : String(data.partial || ""), segments, revision: data.revision && typeof data.revision === "object" ? data.revision : null, fixes: Array.isArray(data.fixes) ? data.fixes : [], policy: modern || Array.isArray(data.segments) });
  } },
  wordsShown: { id: "dictation.reveal", claim: "Paced words never go backwards or past the answer, the first of a batch shows at once, and the whole batch shows by the next answer", check: ([{ startShown, total, elapsedMs, gapMs }], result) => {
    const backlog = Math.max(0, total - startShown);
    if (!backlog) return result === total;
    return result >= Math.min(total, startShown + 1) && result <= total && (elapsedMs < gapMs || result === total);
  } },
  providerChoices: { id: "dictation.providers", claim: "Local is listed first and is the default; an unavailable provider always carries one plain reason; exactly the chosen provider is selected", check: ([status], rows) => {
    if (!Array.isArray(status?.providers)) return rows.length === 0;
    return rows.length === 0 || (rows[0].id === "local" && rows.every(row => row.available || row.reason) && rows.filter(row => row.selected).length <= 1);
  } },
  liveCommands: { id: "dictation.commands", claim: "Command chips contain only decided commands in stream order", check: ([segments], result) => equal(result, (segments || []).filter(row => row?.type === "command").map(row => row.op || row.name)) },
});

export function checkedDictationAction(name, args, result) {
  const contract = DICTATION_CONTRACTS[name];
  if (!contract || !contract.check(args, result)) throw new DictationContractError(contract?.id || name, contract?.claim || "Unknown contract");
  return result;
}
