import { checkedProofsEModel } from "./nxProofsEContracts.js";
// Missions (orchestration): one goal, explicit tasks routed to harnesses,
// prerequisites between them, acceptance checks a person reviews. The engine
// is Night Shift (src/grant_agent/neyvia_missions.py); this module only shapes
// its records for the screen and turns a draft into a create request.

export const HARNESSES = [
  { id: "codex", label: "Codex" },
  { id: "claude-code", label: "Claude Code" },
  { id: "neyvia", label: "Neyvia" },
  { id: "opencode", label: "OpenCode" },
];
export const harnessLabel = id => HARNESSES.find(harness => harness.id === id)?.label || id || "Unassigned";
export const markForHarness = id => (id === "claude-code" ? "claude" : id || "neyvia");

const TASK_STATES = ["waiting", "running", "blocked", "needs_review", "done"];
const localId = (missionId, taskId) => (String(taskId).startsWith(`${missionId}:`) ? String(taskId).slice(missionId.length + 1) : String(taskId));

/**
 * A mission ready to draw: tasks with their local ids, a dependency level
 * (0 = can start first) and counts. Levels come from `needs`, so the tree
 * reads left to right in the order work can happen.
 */
function raw_shapeMission(mission) {
  const tasks = (mission.tasks || []).map(task => ({
    ...task,
    key: task.id,
    localId: localId(mission.id, task.id),
    status: TASK_STATES.includes(task.status) ? task.status : "waiting",
    needs: (task.needs || []).map(need => need),
  }));
  const byId = new Map(tasks.map(task => [task.id, task]));
  const level = new Map();
  const depth = (task, seen = new Set()) => {
    if (level.has(task.id)) return level.get(task.id);
    if (seen.has(task.id)) return 0; // cycles are refused by the backend; never loop here
    seen.add(task.id);
    const value = task.needs.reduce((max, need) => (byId.has(need) ? Math.max(max, depth(byId.get(need), seen) + 1) : max), 0);
    level.set(task.id, value);
    return value;
  };
  for (const task of tasks) task.level = depth(task);
  const counts = Object.fromEntries(TASK_STATES.map(state => [state, tasks.filter(task => task.status === state).length]));
  const levels = [];
  for (const task of tasks) (levels[task.level] ||= []).push(task);
  return {
    ...mission,
    tasks,
    levels,
    counts,
    progress: tasks.length ? counts.done / tasks.length : 0,
    phase: mission.status === "draft" ? "draft" : mission.status === "paused" || mission.status === "stopped" ? mission.status : mission.executionStatus || "waiting",
  };
}

export function emptyDraft(folder = "") {
  return { goal: "", folder, acceptance: "", maxTokens: "", tasks: [emptyTask(1)] };
}
export function emptyTask(index) {
  return { id: `t${index}`, title: "", prompt: "", harness: "codex", model: "", needs: [] };
}

/** Problems that would stop the backend from storing the draft, in plain words. */
function raw_draftProblems(draft) {
  const problems = [];
  if (!draft.goal.trim()) problems.push("Say what the mission should achieve.");
  if (!draft.folder.trim()) problems.push("Choose the project folder it works in.");
  if (!draft.tasks.length) problems.push("Add at least one task.");
  draft.tasks.forEach((task, index) => { if (!task.prompt.trim()) problems.push(`Task ${index + 1} needs a prompt.`); });
  if (!acceptanceLines(draft).length) problems.push("Add at least one acceptance check: how you'll know it's done.");
  if (draft.maxTokens && !(Number(draft.maxTokens) > 0)) problems.push("The token budget must be a positive number.");
  return problems;
}

const acceptanceLines = draft => draft.acceptance.split("\n").map(line => line.trim()).filter(Boolean);

/** The mission.create request for a draft. Prerequisites that point at removed tasks are dropped. */
function raw_createRequest(draft) {
  const ids = new Set(draft.tasks.map(task => task.id));
  return {
    goal: draft.goal.trim(),
    folder: draft.folder.trim(),
    acceptanceChecks: acceptanceLines(draft),
    ...(Number(draft.maxTokens) > 0 ? { budget: { maxTokens: Math.round(Number(draft.maxTokens)) } } : {}),
    tasks: draft.tasks.map(task => ({
      id: task.id,
      prompt: task.prompt.trim(),
      ...(task.title.trim() ? { title: task.title.trim() } : {}),
      harness: task.harness,
      ...(task.model.trim() ? { model: task.model.trim() } : {}),
      needs: task.needs.filter(need => need !== task.id && ids.has(need)),
    })),
  };
}

/** The message that asks Neyvia to plan the tasks itself, with the mission tool. */
function raw_planPrompt(goal, folder) {
  return [
    `Plan a Neyvia mission for this goal: ${goal.trim()}`,
    `Project folder: ${folder.trim()}`,
    "Read the project first. Then split the work into 3-8 tasks a single agent can finish, each with a clear prompt,",
    "the best harness for it (codex for implementation, claude-code for review and refactoring, neyvia for research and docs),",
    "and prerequisites (needs) where one task depends on another. Add 2-4 acceptance checks a person can verify.",
    "Store it with neyvia.mission.create. Do not start it: I'll review and start it from Missions.",
  ].join("\n");
}

// Public observers check the executable manual claims on every invocation.
export function shapeMission(...args) { return checkedProofsEModel("missions.shapeMission", args, raw_shapeMission(...args)); }
export function draftProblems(...args) { return checkedProofsEModel("missions.draftProblems", args, raw_draftProblems(...args)); }
export function createRequest(...args) { return checkedProofsEModel("missions.createRequest", args, raw_createRequest(...args)); }
export function planPrompt(...args) { return checkedProofsEModel("missions.planPrompt", args, raw_planPrompt(...args)); }
