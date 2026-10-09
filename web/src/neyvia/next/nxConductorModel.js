import { checkedProofsEModel } from "./nxProofsEContracts.js";
// The Conductor (plan 15 T9): one goal becomes a routed task tree. A planner
// writes the tree, the backend checks it and always adds a final verifier, the
// executor and verifier routes are frozen before Paul starts it, and every turn
// leaves a receipt (run and chat ids, tokens, time). The job is a detached
// worker on the PC (src/grant_agent/neyvia_conductor.py on HarnessJobStore), so
// it keeps going when Neyvia or its service restarts. This module shapes the
// saved job for the screen; it never guesses a state the job didn't save.

export const PROFILES = [
  { name: "planner", label: "Planner", help: "Reads the goal and writes the task tree. Never edits.", required: true },
  { name: "executor", label: "Executor", help: "Does each task in your folder.", required: true },
  { name: "verifier", label: "Verifier", help: "Checks the result on its own against your checks.", required: true },
  { name: "classifier", label: "Classifier", help: "Optional: sorts the goal first (kind and risk).", required: false },
];

const PHASES = {
  classifying: { label: "Sorting the goal", tone: "live" },
  planning: { label: "Planning", tone: "live" },
  ready: { label: "Plan ready", tone: "gold" },
  running: { label: "Working", tone: "live" },
  paused: { label: "Paused", tone: "idle" },
  completed: { label: "Done and verified", tone: "green" },
  failed: { label: "Failed", tone: "red" },
  interrupted: { label: "Interrupted", tone: "red" },
  stopped: { label: "Stopped", tone: "idle" },
  queued: { label: "Starting", tone: "live" },
};
export const phaseOf = phase => PHASES[phase] || { label: phase || "Unknown", tone: "idle" };

const TASK = { waiting: "idle", running: "live", completed: "green", failed: "red" };
export const taskTone = status => TASK[status] || "idle";

const tokensOf = usage => {
  if (!usage) return null;
  const total = usage.totalTokens ?? usage.threadTotal?.totalTokens;
  return Number.isFinite(total) ? total : null;
};

/** Which turn a receipt was: the classify and plan turns are the job's own, the rest are tasks. */
function raw_turnKind(runId = "", jobId = "") {
  const tail = String(runId).startsWith(`${jobId}-`) ? String(runId).slice(jobId.length + 1) : String(runId).split("-").pop();
  return tail === "classify" ? "classify" : tail === "plan" ? "plan" : "task";
}

/** The saved conductor state: live on the job while it runs, in its result once it ends. */
export function conductorOf(job) {
  return job?.conductor || job?.result?.conductor || null;
}

/**
 * A job ready to draw: one phase word (the worker's own status wins when it
 * ended without finishing), tasks in dependency levels, receipts and totals.
 */
function raw_shapeJob(job) {
  if (!job) return null;
  const state = conductorOf(job) || {};
  const intent = job.request?.intent || {};
  let phase = state.phase || (job.status === "queued" ? "queued" : "planning");
  if (job.status === "interrupted") phase = "interrupted";
  else if (job.status === "cancelled" || job.status === "cancelling") phase = "stopped";
  else if (job.status === "failed" && phase !== "failed") phase = "failed";
  const tasks = (state.tasks || []).map(task => ({ ...task, needs: task.needs || [] }));
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
  const levels = [];
  for (const task of tasks) (levels[depth(task)] ||= []).push(task);
  const receipts = (state.receipts || []).map(receipt => ({ ...receipt, kind: turnKind(receipt.runId, job.id), tokens: tokensOf(receipt.usage) }));
  const known = receipts.filter(receipt => receipt.tokens != null);
  const verifier = [...tasks].reverse().find(task => task.routingProfile === "verifier" && task.verification) || null;
  const done = tasks.filter(task => task.status === "completed").length;
  const control = job.conductorControl || {};
  const live = ["queued", "running"].includes(job.status);
  return {
    id: job.id,
    status: job.status,
    pid: job.pid || null,
    live,
    phase,
    tone: phaseOf(phase).tone,
    label: phaseOf(phase).label,
    goal: state.goal || intent.goal || job.promptPreview || "",
    folder: state.folder || intent.folder || job.workspacePath || "",
    acceptanceChecks: state.acceptanceChecks || intent.acceptanceChecks || [],
    routes: state.routes || job.request?.routes || {},
    classification: state.classification || null,
    tasks,
    levels,
    receipts,
    planning: receipts.filter(receipt => receipt.kind !== "task"),
    activeRun: state.activeRun || null,
    verification: verifier?.verification || null,
    done,
    progress: tasks.length ? done / tasks.length : 0,
    tokens: known.length ? known.reduce((sum, receipt) => sum + receipt.tokens, 0) : null,
    tokensComplete: known.length === receipts.length,
    durationMs: receipts.reduce((sum, receipt) => sum + (receipt.durationMs || 0), 0),
    createdAt: job.createdAt,
    updatedAt: job.updatedAt,
    error: job.error || job.result?.error || null,
    approved: Boolean(control.approved),
    canStart: live && phase === "ready" && !control.approved,
    canPause: live && phase === "running",
    canResume: live && phase === "paused",
    canStop: live,
  };
}

/** Every page of jobs merged by id, newest first: rows that move between pages never show twice. */
function raw_mergeJobs(current = [], page = []) {
  const byId = new Map(current.map(job => [job.id, job]));
  for (const job of page) byId.set(job.id, job);
  return [...byId.values()].sort((a, b) => String(b.createdAt || "").localeCompare(String(a.createdAt || "")));
}

/** Problems that stop a plan request, in plain words. */
function raw_planProblems({ goal, folder, checks }, profiles = {}) {
  const problems = [];
  if (!String(goal || "").trim()) problems.push("Say what should be true when it's done.");
  if (!String(folder || "").trim()) problems.push("Choose the folder it works in.");
  if (!checkLines(checks).length) problems.push("Add at least one check the verifier can prove.");
  const missing = PROFILES.filter(profile => profile.required && !profiles[profile.name]).map(profile => profile.label.toLowerCase());
  if (missing.length) problems.push(`Choose who does the ${missing.join(", ")} work.`);
  return problems;
}

export const checkLines = text => String(text || "").split("\n").map(line => line.trim()).filter(Boolean);

/** 13400 -> "13s", 97000 -> "1m 37s", 3720000 -> "1h 2m". */
export function durationText(ms) {
  if (!Number.isFinite(ms) || ms < 0) return "";
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m${seconds % 60 ? ` ${seconds % 60}s` : ""}`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

/** "Codex · gpt-6-luna · low · full" for a frozen route. */
export function routeLine(route, appName = id => id) {
  if (!route) return "Not set";
  return [appName(route.app), route.model, route.effort, route.permissionMode].filter(Boolean).join(" · ");
}

// Public observers check the executable manual claims on every invocation.
export function turnKind(...args) { return checkedProofsEModel("conductor.turnKind", args, raw_turnKind(...args)); }
export function shapeJob(...args) { return checkedProofsEModel("conductor.shapeJob", args, raw_shapeJob(...args)); }
export function mergeJobs(...args) { return checkedProofsEModel("conductor.mergeJobs", args, raw_mergeJobs(...args)); }
export function planProblems(...args) { return checkedProofsEModel("conductor.planProblems", args, raw_planProblems(...args)); }
