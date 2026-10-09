import { checkedProofsEModel } from "./nxProofsEContracts.js";
// Night Shift (plan 07 R6, plan 15 T10): tasks that launch each other. The
// engine is src/grant_agent/nightshift*.py; this module only shapes its
// records for the board, the growing tree and the morning card, and turns
// the budget form into a resources patch. No state lives here.

import { HARNESSES, harnessLabel } from "./nxMissionsModel.js";
import { freshTokens } from "./nxUsageModel.js";

export { HARNESSES, harnessLabel };
export const STATES = ["waiting", "running", "blocked", "needs_review", "done"];
export const OWNER_FOR = { codex: "Codex", "claude-code": "Claude", neyvia: "Neyvia", opencode: "OpenCode" };
export const PERMISSIONS = [
  { value: "read-only", label: "Read only" },
  { value: "workspace-write", label: "Can edit the folder" },
  { value: "full-access", label: "Full access" },
];
export const MODEL_HINTS = ["gpt-6-luna", "gpt-6.1-sol", "claude-sonnet-5", "claude-opus-5-5"];

const isPaul = task => String(task?.owner || "").toLowerCase() === "paul";
export { isPaul };

/**
 * The board: tasks with their dependency level (0 = can start first), the
 * prerequisites that don't exist, who waits on whom, and counts. Mission
 * tasks are Night Shift tasks too; they live on the Missions tab unless asked.
 */
function raw_shapeBoard(rows = [], { includeMissions = false } = {}) {
  const all = rows.filter(task => task && task.id);
  const missionCount = all.filter(task => task.missionId).length;
  const tasks = all.filter(task => includeMissions || !task.missionId).map(task => ({
    ...task,
    status: STATES.includes(task.status) ? task.status : "waiting",
    needs: Array.isArray(task.needs) ? task.needs.map(String) : [],
    paul: isPaul(task),
  }));
  const known = new Map(all.map(task => [task.id, task]));
  const byId = new Map(tasks.map(task => [task.id, task]));
  const level = new Map();
  const depth = (task, seen = new Set()) => {
    if (level.has(task.id)) return level.get(task.id);
    if (seen.has(task.id)) return 0; // the backend refuses cycles; never loop here
    seen.add(task.id);
    const value = task.needs.reduce((max, need) => (byId.has(need) ? Math.max(max, depth(byId.get(need), seen) + 1) : max), 0);
    level.set(task.id, value);
    return value;
  };
  for (const task of tasks) {
    task.level = depth(task);
    task.missing = task.needs.filter(need => !known.has(need));
    task.dependents = tasks.filter(other => other.needs.includes(task.id)).map(other => other.id);
    task.open = task.needs.filter(need => known.get(need)?.status !== "done");
  }
  const levels = [];
  for (const task of tasks) (levels[task.level] ||= []).push(task);
  const edges = tasks.flatMap(task => task.needs.filter(need => byId.has(need)).map(need => ({ from: need, to: task.id })));
  const counts = Object.fromEntries(STATES.map(state => [state, tasks.filter(task => task.status === state).length]));
  return { tasks, byId, levels: levels.filter(Boolean), edges, counts, missionCount, progress: tasks.length ? counts.done / tasks.length : 0 };
}

/**
 * Tasks "Start all" arms: waiting, not armed, not Paul's. Blocked tasks are
 * left out on purpose: each one is restarted on its own, after reading why.
 */
function raw_startable(tasks = []) {
  return tasks.filter(task => !task.paul && !isPaul(task) && !task.armed && task.status === "waiting");
}

/** The reason line under the state, without repeating it. */
export function noteText(task) {
  if (!task || task.status === "done") return "";
  const reason = reasonText(task);
  const state = stateText(task);
  if (!reason || reason === state) return "";
  if (reason.startsWith(state)) return reason.slice(state.length).replace(/^[.\s·]+/, "");
  return reason;
}

/** What a task is doing, in Paul's words. `reason` is the summary's effective reason when present. */
export function stateText(task) {
  if (!task) return "";
  if (task.status === "done") return "Done";
  if (task.status === "running") return "Running";
  if (task.status === "blocked") return "Blocked";
  if (task.status === "needs_review") return "Needs review";
  if (isPaul(task)) return "Waiting on you";
  if (task.missing?.length) return "Missing a prerequisite";
  if (!task.armed) return "Not started";
  if (task.open?.length) return "Waiting for prerequisites";
  return task.reason ? "On hold" : "Ready";
}

/** Plain words for a backend reason. Unknown reasons pass through unchanged. */
export function reasonText(task) {
  const reason = String(task?.reason || "").trim();
  if (!reason) {
    if (task?.status === "waiting" && task?.missing?.length) return `Needs ${task.missing.join(", ")}, which isn't on the board`;
    return "";
  }
  if (reason === "Not started") return "Not started. Choose Start when you want it to run.";
  if (reason === "Waiting on Paul") return "Waiting on you";
  if (reason.startsWith("Waiting for prerequisites: ")) return `Starts after ${reason.slice(27)}`;
  return reason;
}

const base = path => String(path || "").split(/[\\/]/).filter(Boolean).pop() || String(path || "");

/** One line for a piece of evidence, plus what opening it means. */
function raw_evidenceView(evidence) {
  if (!evidence) return null;
  if (typeof evidence === "string") return { kind: "note", label: evidence, detail: evidence };
  switch (evidence.type) {
    case "file": return { kind: "file", label: base(evidence.path), detail: `${evidence.path}${evidence.sha256 ? `\nSHA-256 ${evidence.sha256}` : ""}`, path: evidence.path };
    case "commit": return { kind: "commit", label: `Commit ${String(evidence.hash || "").slice(0, 8)}`, detail: evidence.hash, hash: evidence.hash };
    case "run": return { kind: "run", label: "Agent run finished", detail: evidence.runId, sessionId: evidence.sessionId || "", runId: evidence.runId };
    case "command": return { kind: "command", label: `Command: ${String(evidence.command || "").slice(0, 60)}`, detail: `${evidence.command}\nexit ${evidence.exitCode}\n${evidence.output || ""}`, owner: true };
    default: return { kind: "note", label: String(evidence.type || "Evidence"), detail: JSON.stringify(evidence) };
  }
}

/** "45s", "12m", "2h 5m": for measured seconds. */
export function duration(seconds) {
  const value = Math.max(0, Math.round(Number(seconds) || 0));
  if (value < 60) return `${value}s`;
  const minutes = Math.floor(value / 60);
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h${minutes % 60 ? ` ${minutes % 60}m` : ""}`;
}

/**
 * The morning card, derived only from the summary the backend measured:
 * done with evidence, blocked with the reason, waiting on Paul, tokens and time.
 */
function raw_morning(summary) {
  if (!summary) return null;
  const tasks = (summary.tasks || []).filter(task => !task.missionId);
  const links = new Map((summary.evidenceLinks || []).map(link => [link.taskId, link]));
  const done = tasks.filter(task => task.status === "done").map(task => ({ task, evidence: links.get(task.id) || task.evidence || null }));
  const blocked = (summary.blocked || []).filter(task => !task.missionId);
  const needsReview = (summary.needsReview || []).filter(task => !task.missionId);
  const waitingOnPaul = (summary.waitingOnPaul || []).filter(task => !task.missionId);
  const usage = summary.usage || {};
  const hasTokenBreakdown = [usage.inputTokens, usage.outputTokens, usage.cachedInputTokens].every(value => Number.isFinite(value) && value >= 0);
  const harnesses = Object.entries(summary.perHarness || {})
    .filter(([, row]) => row && (row.knownRuns || row.unknownRuns || row.running || row.maxTokens || row.maxSeconds))
    .map(([id, row]) => ({ id, label: harnessLabel(id), ...row }));
  return {
    done, blocked, needsReview, waitingOnPaul, harnesses,
    running: tasks.filter(task => task.status === "running"),
    tokens: usage.reportedTokens || 0,
    newTokens: hasTokenBreakdown ? freshTokens({ input: usage.inputTokens, cached: usage.cachedInputTokens, output: usage.outputTokens }) : null,
    cacheReadTokens: hasTokenBreakdown ? usage.cachedInputTokens : null,
    tokenBreakdownUnknownRuns: usage.tokenBreakdownUnknownRuns || 0,
    tokensComplete: usage.complete !== false,
    // only finished runs that never reported; a running one hasn't had its chance yet
    unknownRuns: Object.values(summary.perHarness || {}).reduce((sum, row) => sum + (row?.unknownCompletedRuns || 0), 0),
    attempts: usage.attempts || 0,
    workSeconds: summary.elapsedSeconds || 0,
    nightSeconds: summary.night?.elapsedSeconds || 0,
    nightStarted: summary.night?.startedAt || "",
    empty: !tasks.length,
  };
}

// ---- budget and quiet hours: form <-> resources policy ----

const blank = value => (value == null ? "" : String(value));
const round1 = value => String(Math.round(value * 10) / 10);
const hours = seconds => (seconds ? round1(seconds / 3600) : "");
const minutes = seconds => (seconds ? round1(seconds / 60) : "");

function raw_policyForm(policy = {}) {
  const budgets = policy.perHarnessBudgets || {};
  return {
    paused: Boolean(policy.paused),
    maxConcurrent: blank(policy.maxConcurrent),
    maxNightHours: hours(policy.maxNightSeconds),
    maxTaskMinutes: minutes(policy.maxTaskSeconds),
    maxTaskTokens: blank(policy.maxTaskTokens),
    holdOn: policy.holdAtPlanPercent != null,
    holdAt: blank(policy.holdAtPlanPercent ?? 70),
    gpuForAsr: Boolean(policy.gpuReservedFor),
    gpuReservedFor: policy.gpuReservedFor || "ASR",
    quietOn: Boolean(policy.quietGpuHours),
    quietStart: policy.quietGpuHours?.start || "08:00",
    quietEnd: policy.quietGpuHours?.end || "23:00",
    quietTz: policy.quietGpuHours?.timeZone || "local",
    budgets: Object.fromEntries(HARNESSES.map(({ id }) => [id, { tokens: blank(budgets[id]?.maxTokens), hours: hours(budgets[id]?.maxSeconds) }])),
  };
}

const TIME = /^(?:[01]\d|2[0-3]):[0-5]\d$/;

/** The resources patch for a form, or the problems that stop it, in plain words. */
function raw_policyPatch(form) {
  const problems = [];
  const count = (value, label, { max } = {}) => {
    const text = String(value ?? "").trim().replace(/[\s,_]/g, "");
    if (!text) return null;
    const number = Number(text);
    if (!Number.isInteger(number) || number < 1 || (max && number > max)) { problems.push(`${label} must be a whole number${max ? ` from 1 to ${max}` : " above 0"}.`); return null; }
    return number;
  };
  const seconds = (value, label, unit) => {
    const text = String(value ?? "").trim().replace(",", ".");
    if (!text) return null;
    const number = Number(text);
    if (!Number.isFinite(number) || number <= 0) { problems.push(`${label} must be more than 0.`); return null; }
    return Math.max(1, Math.round(number * unit));
  };
  const patch = {
    paused: Boolean(form.paused),
    maxConcurrent: count(form.maxConcurrent, "Tasks at once"),
    maxNightSeconds: seconds(form.maxNightHours, "Hours per night", 3600),
    maxTaskSeconds: seconds(form.maxTaskMinutes, "Minutes per task", 60),
    maxTaskTokens: count(form.maxTaskTokens, "Tokens per task"),
    holdAtPlanPercent: form.holdOn ? count(form.holdAt, "The plan hold", { max: 100 }) ?? 70 : null,
    gpuReservedFor: form.gpuForAsr ? (form.gpuReservedFor || "ASR") : null,
    quietGpuHours: null,
    perHarnessBudgets: {},
  };
  if (form.quietOn) {
    if (!TIME.test(form.quietStart) || !TIME.test(form.quietEnd)) problems.push("Quiet hours need times like 08:00 and 23:00.");
    else patch.quietGpuHours = { start: form.quietStart, end: form.quietEnd, timeZone: form.quietTz === "UTC" ? "UTC" : "local" };
  }
  for (const { id, label } of HARNESSES) {
    const row = form.budgets?.[id] || {};
    const maxTokens = count(row.tokens, `${label} tokens`);
    const maxSeconds = seconds(row.hours, `${label} hours`, 3600);
    if (maxTokens != null && id === "opencode") problems.push("OpenCode doesn't report tokens while it works yet, so it can only have an hours budget.");
    if (maxTokens != null || maxSeconds != null) patch.perHarnessBudgets[id] = { maxTokens, maxSeconds };
  }
  return { patch, problems };
}

/** Is a quiet window active at `now` (local or UTC)? Same start and end = all day. */
function raw_quietNow(quiet, now = new Date()) {
  if (!quiet || !TIME.test(quiet.start || "") || !TIME.test(quiet.end || "")) return false;
  const minute = quiet.timeZone === "UTC" ? now.getUTCHours() * 60 + now.getUTCMinutes() : now.getHours() * 60 + now.getMinutes();
  const toMinutes = value => Number(value.slice(0, 2)) * 60 + Number(value.slice(3));
  const start = toMinutes(quiet.start);
  const end = toMinutes(quiet.end);
  if (start === end) return true;
  return start < end ? minute >= start && minute < end : minute >= start || minute < end;
}

// ---- the growing tree: one leaf per task, branches per prerequisite level ----

/**
 * Leaf positions for the tree drawing (viewBox 0 0 280 180). Each prerequisite
 * level is a branch pair, lowest first; a task's leaf sits on its level's
 * branch, alternating sides. Leaves grow as tasks complete.
 */
function raw_treeLayout(board, { width = 280, height = 180 } = {}) {
  const mid = width / 2;
  const ground = height - 12;
  const levels = board?.levels || [];
  const count = Math.max(1, levels.length);
  const step = Math.min(34, (ground - 44) / count);
  const branches = [];
  const leaves = [];
  levels.forEach((level, index) => {
    const y = ground - 26 - index * step;
    const sides = [[], []];
    level.forEach((task, at) => sides[(at + index) % 2].push(task));
    sides.forEach((side, sideIndex) => {
      if (!side.length) return;
      const sign = sideIndex === 0 ? -1 : 1;
      const spacing = Math.min(22, (mid - 30) / side.length);
      const reach = 16 + spacing * side.length;
      branches.push({ key: `${index}-${sign}`, d: `M${mid} ${y + 10} Q${mid + sign * reach * 0.45} ${y + 2} ${mid + sign * reach} ${y - 6 - side.length}` });
      side.forEach((task, at) => {
        const x = mid + sign * (18 + spacing * at + spacing * 0.6);
        leaves.push({ task, x: Math.round(x * 10) / 10, y: Math.round((y + 4 - at * 1.6 - (x - mid) * sign * 0.06) * 10) / 10, sign });
      });
    });
  });
  const top = ground - 26 - (count - 1) * step - 14;
  return { width, height, ground, mid, top, branches, leaves };
}

// Public observers check the executable manual claims on every invocation.
export function shapeBoard(...args) { return checkedProofsEModel("nightshift.shapeBoard", args, raw_shapeBoard(...args)); }
export function startable(...args) { return checkedProofsEModel("nightshift.startable", args, raw_startable(...args)); }
export function evidenceView(...args) { return checkedProofsEModel("nightshift.evidenceView", args, raw_evidenceView(...args)); }
export function morning(...args) { return checkedProofsEModel("nightshift.morning", args, raw_morning(...args)); }
export function quietNow(...args) { return checkedProofsEModel("nightshift.quietNow", args, raw_quietNow(...args)); }
export function treeLayout(...args) { return checkedProofsEModel("nightshift.treeLayout", args, raw_treeLayout(...args)); }
export function policyForm(...args) { return checkedProofsEModel("nightshift.policyForm", args, raw_policyForm(...args)); }
export function policyPatch(...args) { return checkedProofsEModel("nightshift.policyPatch", args, raw_policyPatch(...args)); }
