import { checkedProofsEModel } from "./nxProofsEContracts.js";
// Autopilot (plan 15 T17): one intent becomes a checklist; each item runs a
// manual procedure or its compiled script with executable checks, and only real
// judgement points go to a model. This module turns the durable run
// (src/grant_agent/neyvia_autopilot.py) into what the chat shows: which items
// ran with no model at all, which needed one and why, and the model calls with
// their actual tokens. Nothing here is inferred from prose.

export const READ_TOOLS = ["workspace.read", "workspace.search", "runtime.environment", "neyvia.manual.compiled",
  "neyvia.manual.versions", "neyvia.manual.index", "neyvia.notes.list", "neyvia.notes.read",
  "neyvia.files.list", "neyvia.files.stat", "neyvia.files.read"];
export const SCOPES = [
  { value: "look", label: "Look only", tools: READ_TOOLS },
  { value: "edit", label: "Look and edit", tools: [...READ_TOOLS, "workspace.write"] },
];
const raw_scopeTools = scope => (SCOPES.find(entry => entry.value === scope) || SCOPES[0]).tools;
const raw_scopeOf = tools => (Array.isArray(tools) && tools.includes("workspace.write") ? "edit" : "look");

const STATUS = {
  planning: { label: "Making the checklist", tone: "live" },
  running: { label: "Working", tone: "live" },
  completed: { label: "Done", tone: "green" },
  blocked: { label: "Stopped on a problem", tone: "red" },
  waiting_approval: { label: "Needs you", tone: "gold" },
  stopped: { label: "Stopped", tone: "idle" },
};
export const statusOf = status => STATUS[status] || { label: status || "Unknown", tone: "idle" };
export const isLive = run => run?.status === "planning" || run?.status === "running";

const tokenTotal = tokens => {
  if (!tokens || typeof tokens !== "object") return null;
  if (Number.isFinite(tokens.total)) return tokens.total;
  const sum = ["input", "output"].reduce((total, key) => total + (Number(tokens[key]) || 0), 0);
  return sum || null;
};

/** What a model call was for, in plain words. */
export function callPurpose(reason = "") {
  const text = String(reason);
  if (/^intent checklist/i.test(text)) return { kind: "plan", text: "Made the checklist and picked a manual step for each item" };
  if (/^judgement:/i.test(text)) return { kind: "judge", text: `Made the choice "${text.replace(/^judgement:\s*/i, "")}"` };
  if (/^disagreement:/i.test(text)) return { kind: "second", text: `Second opinion at "${text.replace(/^disagreement:\s*/i, "")}"` };
  if (/^frontier/i.test(text)) return { kind: "frontier", text: "Explored a gap in the manual and proposed a fix" };
  return { kind: "other", text: text || "Model call" };
}

/**
 * Each model call belongs to the run (the checklist) or to one item. Calls are
 * saved in the order they happened and items run in order, so the n-th item's
 * judgement rounds are the next judgement calls (plus any second opinion right
 * after each), and its frontier calls are the next frontier calls.
 */
function raw_attributeCalls(run) {
  const calls = (run?.models || []).map((call, index) => ({ ...call, index, purpose: callPurpose(call.reason), total: tokenTotal(call.tokens) }));
  const perItem = (run?.items || []).map(() => []);
  const runLevel = calls.filter(call => call.purpose.kind === "plan" || call.purpose.kind === "other");
  const judging = calls.filter(call => call.purpose.kind === "judge" || call.purpose.kind === "second");
  const exploring = calls.filter(call => call.purpose.kind === "frontier");
  let j = 0;
  let f = 0;
  (run?.items || []).forEach((item, index) => {
    for (let round = 0; round < (item.modelReasons || []).length && j < judging.length; round += 1) {
      perItem[index].push(judging[j++]);
      while (j < judging.length && judging[j].purpose.kind === "second") perItem[index].push(judging[j++]);
    }
    for (let k = 0; k < (item.frontier || []).length && f < exploring.length; k += 1) perItem[index].push(exploring[f++]);
  });
  // A call still in flight (item in progress) or one we could not place stays visible at run level.
  const placed = new Set(perItem.flat().map(call => call.index));
  const loose = calls.filter(call => !placed.has(call.index) && !runLevel.includes(call));
  return { calls, runLevel: [...runLevel, ...loose], perItem };
}

/** How one item ran, and why it did or didn't need a model. */
export function itemRoute(item, calls = []) {
  const reasons = item?.modelReasons || [];
  const frontier = item?.frontier || [];
  const tokens = calls.reduce((sum, call) => sum + (call.total || 0), 0);
  const checks = (item?.receipt?.checks || []).length + (item?.verification ? 1 : 0);
  const passed = (item?.receipt?.checks || []).filter(check => check.passed).length + (item?.verification?.passed ? 1 : 0);
  let kind = item?.route === "script" ? "script" : "manual";
  let why = kind === "script"
    ? "Done exactly this way before, so it ran as a saved script with no model."
    : "The manual covers every step here, so no model was needed.";
  if (reasons.length) {
    kind = "model";
    why = `The manual leaves a choice here, so a model decided: ${reasons[reasons.length - 1]}`;
  }
  if (frontier.length) {
    kind = "frontier";
    why = `The manual had a gap. A larger model looked around and proposed a fix, kept aside for review: ${frontier[frontier.length - 1].reason || "see receipt"}`;
  }
  const label = { script: "Saved script", manual: "Manual step", model: "Model choice", frontier: "Gap explored" }[kind];
  return { kind, label, why, tokens: calls.length ? tokens : 0, calls: calls.length, checks, passed };
}

/** The whole run, ready to draw. */
function raw_shapeRun(run) {
  if (!run) return null;
  const { calls, runLevel, perItem } = attributeCalls(run);
  const items = (run.items || []).map((item, index) => ({ ...item, index, how: itemRoute(item, perItem[index]), modelCalls: perItem[index] }));
  const done = items.filter(item => item.status === "completed").length;
  const noModel = items.filter(item => item.status === "completed" && (item.how.kind === "script" || item.how.kind === "manual")).length;
  const scripts = items.filter(item => item.status === "completed" && item.how.kind === "script").length;
  return {
    ...run,
    items,
    calls,
    runLevel,
    done,
    noModel,
    scripts,
    total: items.length,
    totalTokens: tokenTotal(run.tokens) ?? calls.reduce((sum, call) => sum + (call.total || 0), 0),
    state: statusOf(run.status),
    live: isLive(run),
    current: items.find(item => item.status === "in_progress") || null,
  };
}

/** What a selection did, as "workspace › files › read-and-confirm". */
export const procedureName = selection => (selection ? [selection.id, selection.chapter, selection.procedure].filter(Boolean).join(" › ") : "");

/** One line for the final check: "workspace.read alpha.txt: content contains “cobalt orchard”". */
function raw_checkLine(verification) {
  if (!verification) return "";
  const target = verification.args?.path || verification.args?.query || "";
  const expect = verification.expect || {};
  const value = typeof expect.value === "string" ? `“${expect.value}”` : JSON.stringify(expect.value);
  const op = { contains: "contains", eq: "is", exists: "exists" }[expect.op] || expect.op;
  return `${verification.tool}${target ? ` ${target}` : ""}: ${expect.path || "result"} ${op}${expect.op === "exists" ? "" : ` ${value}`}`;
}

/** A stable request id for one send, so a retry never starts a second run. */
export function newRequestId(sessionId) {
  const random = globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  return `ui-${String(sessionId || "chat").slice(-24)}-${random}`;
}

// Public observers check the executable manual claims on every invocation.
export function scopeTools(...args) { return checkedProofsEModel("autopilot.scopeTools", args, raw_scopeTools(...args)); }
export function scopeOf(...args) { return checkedProofsEModel("autopilot.scopeOf", args, raw_scopeOf(...args)); }
export function attributeCalls(...args) { return checkedProofsEModel("autopilot.attributeCalls", args, raw_attributeCalls(...args)); }
export function shapeRun(...args) { return checkedProofsEModel("autopilot.shapeRun", args, raw_shapeRun(...args)); }
export function checkLine(...args) { return checkedProofsEModel("autopilot.checkLine", args, raw_checkLine(...args)); }
