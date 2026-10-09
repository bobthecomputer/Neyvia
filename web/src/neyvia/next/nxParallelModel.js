// Parallel branches (plan 29): the pure side of the pane. One run = a main agent plus a worker per track, each on its own
// worktree and branch, merged one at a time into the integration branch. The wire shape is PARALLEL-contract.md
// (GET/POST /api/ui/parallel); everything here only reads a Run and says what to draw and which buttons are live.

export const RUN_LABEL = {
  starting: "Starting", working: "Working", merging: "Merging", conflict: "Conflict to resolve", checking: "Running checks",
  ready: "Ready to finish", checks_failed: "Checks failed", finished: "Finished", settled: "Settled", stopped: "Stopped", failed: "Failed",
};
export const RUN_TONE = {
  starting: "live", working: "live", merging: "live", conflict: "red", checking: "live", ready: "green", checks_failed: "red",
  finished: "green", settled: "idle", stopped: "idle", failed: "red",
};
export const LANE_LABEL = {
  starting: "Starting", working: "Working", asking: "Asking", done: "Done", merging: "Merging", conflict: "In conflict", merged: "Merged", settled: "Settled",
};
export const LANE_TONE = { starting: "live", working: "live", asking: "gold", done: "green", merging: "live", conflict: "red", merged: "green", settled: "idle" };

const ACTIVE_RUN = ["starting", "working", "merging", "conflict", "checking"];
const SETTLEABLE = ["ready", "checks_failed", "finished", "stopped", "failed"];
const QUIET_RUN = ["settled", "stopped", "failed", "finished", "ready"];

export const AGENT_LABEL = { "claude-code": "Claude Code", codex: "Codex", opencode: "OpenCode", neyvia: "Neyvia" };
export const markForAgent = agent => (agent === "claude-code" ? "claude" : agent || "neyvia");

/** A run is worth polling quickly while anything in it can still change. */
export const runActive = run => Boolean(run) && ACTIVE_RUN.includes(run.state);

// A session that has ended while its lane still says working: the agent stopped without calling done (or the run was stopped).
const ENDED = ["completed", "failed", "stopped", "cancelled", "error", "ended"];
export const sessionEnded = lane => ENDED.includes(String(lane?.liveState || ""));

/** The warm working light sits on a lane while its agent is really at work. */
export function laneWorking(lane, run = null) {
  if (!lane) return false;
  if (["done", "merged", "settled", "asking"].includes(lane.state)) return false;
  if (run && QUIET_RUN.includes(run.state)) return false;
  return ["starting", "working", "merging"].includes(lane.state) && !sessionEnded(lane);
}

/** Tone and label of a lane, the main agent's included. */
export function laneStatus(lane, run) {
  const key = lane.state in LANE_LABEL ? lane.state : "working";
  const working = laneWorking(lane, run);
  if (!working && ["working", "merging"].includes(key)) {
    const ended = sessionEnded(lane) && !(run && QUIET_RUN.includes(run.state));
    return { key, label: ended ? "Session ended" : "Idle", tone: ended ? "caution" : "idle", working };
  }
  return { key, label: LANE_LABEL[key], tone: LANE_TONE[key], working };
}

/** The last readable line of what an agent said or did: the backend sends the tail of its text, markdown and all. */
export function activityLine(text, max = 220) {
  const lines = String(text || "").split(String.fromCharCode(10)).map(line => line.replace(/^[\s>*#-]+/, "").replace(/\*+|`/g, "").replace(/\s+/g, " ").trim()).filter(Boolean);
  const last = lines[lines.length - 1] || "";
  return last.length > max ? `${last.slice(0, max - 1)}…` : last;
}

/** Questions a lane asked, oldest first, normalised. */
export function laneQuestions(lane) {
  return (lane?.questions || []).map(row => ({
    id: String(row.id), question: String(row.question || ""), answer: row.answer == null || row.answer === "" ? null : String(row.answer),
    askedAt: row.askedAt || null, answeredAt: row.answeredAt || null,
  }));
}

/** The merge strip: tracks in merge order, each merged, in conflict, merging, ready (done, not yet merged) or waiting. */
export function mergeNodes(run) {
  const byId = new Map((run?.tracks || []).map(track => [track.id, track]));
  const order = (run?.mergeOrder?.length ? run.mergeOrder : (run?.tracks || []).map(track => track.id)).filter(id => byId.has(id));
  return order.map(id => {
    const lane = byId.get(id);
    const result = lane.mergeResult?.status;
    let status = "waiting";
    if (lane.state === "settled" || lane.state === "merged" || result === "merged") status = "merged";
    else if (lane.state === "conflict" || result === "conflict") status = "conflict";
    else if (lane.state === "merging") status = "merging";
    else if (lane.state === "done") status = "ready";
    const files = status === "conflict" ? (lane.mergeResult?.files || (run.conflict?.track === id ? run.conflict.files : null) || []) : [];
    return { id, title: lane.title || id, status, files, commit: lane.mergeResult?.commit || null };
  });
}

export const NODE_LABEL = { merged: "Merged", conflict: "Conflict", merging: "Merging", ready: "Ready", waiting: "Waiting" };

/** One segment per track for the progress rail under the header. */
export function railSegments(run) {
  return (run?.tracks || []).map(track => ({ id: track.id, title: track.title || track.id, key: laneStatus(track, run).key, working: laneWorking(track, run) }));
}

export function runCounts(run) {
  const tracks = run?.tracks || [];
  const count = test => tracks.filter(test).length;
  return {
    total: tracks.length,
    merged: count(track => track.state === "merged" || track.state === "settled"),
    done: count(track => track.state === "done"),
    working: count(track => ["starting", "working", "merging"].includes(track.state)),
    asking: count(track => track.state === "asking"),
    conflict: count(track => track.state === "conflict"),
  };
}

/** How the run stands, in a line under the goal. */
export function runSummary(run) {
  const counts = runCounts(run);
  const parts = [`${counts.total} ${counts.total === 1 ? "track" : "tracks"}`];
  if (counts.merged) parts.push(`${counts.merged} merged`);
  if (counts.done) parts.push(`${counts.done} done`);
  if (counts.working) parts.push(`${counts.working} working`);
  if (counts.asking) parts.push(`${counts.asking} asking`);
  if (counts.conflict) parts.push(`${counts.conflict} in conflict`);
  return parts.join(" · ");
}

/** Which buttons can be pressed right now, and why not when they can't. */
export function runActions(run) {
  if (!run) return {};
  const someDone = (run.tracks || []).some(track => track.state === "done");
  const merge = run.state === "working" && someDone;
  const finish = run.state === "ready";
  const settle = SETTLEABLE.includes(run.state);
  const stop = ACTIVE_RUN.includes(run.state);
  return {
    merge: { enabled: merge, why: merge ? "" : run.state === "conflict" ? "Resolve the conflict first" : "No track is done yet" },
    finish: { enabled: finish, why: finish ? "" : run.state === "finished" ? "Already finished" : "Every track has to be merged and the checks passed first" },
    settle: { enabled: settle, why: settle ? "" : run.state === "settled" ? "Already settled" : "Stop the run or finish it first" },
    stop: { enabled: stop, why: stop ? "" : "Nothing is running" },
  };
}

/** `parallel/<run>/<track>` shown without the run, so a lane reads `track`. */
export function laneBranchLabel(lane, run) {
  const prefix = `parallel/${run?.id}/`;
  const branch = String(lane?.branch || "");
  return branch.startsWith(prefix) ? branch.slice(prefix.length) : branch;
}

/** The runs a read gave, newest first, filled in so the pane never meets a missing array. */
export function shapeRuns(raw) {
  const list = Array.isArray(raw?.runs) ? raw.runs : raw?.run ? [raw.run] : [];
  const lane = row => ({ questions: [], commitsAhead: 0, lastActivity: "", summary: null, mergeResult: null, ...row });
  return list.filter(run => run && run.id).map(run => ({
    mergeOrder: [], conflict: null, checks: null, settings: {}, finish: null, receipt: null, error: null, ...run,
    main: lane(run.main || { id: "main", title: "Main agent", state: "working" }),
    tracks: (run.tracks || []).map(lane),
  }));
}

/** What an action's reply says to the person, when it says more than "done". */
export function actionNote(operation, reply) {
  if (!reply) return "";
  if (operation === "finish" && reply.needsApproval) return "This run is set not to finish by itself, so the integration branch was left as it is. Allow finishing for the run, then press Finish again.";
  if (operation === "settle" && reply.receipt) {
    const { removed = [], deletedBranches = [], keptBranches = [] } = reply.receipt;
    const count = (n, one, many) => `${n} ${n === 1 ? one : many}`;
    return `Settled: ${count(removed.length, "worktree", "worktrees")} removed, ${count(deletedBranches.length, "branch", "branches")} deleted${keptBranches.length ? `, ${keptBranches.length} kept` : ""}.`;
  }
  return "";
}
