import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
/**
 * Overview of running subagents.
 *
 * The requirement is that you can always tell what is happening no matter how
 * many subagents are running — which is exactly the case where a transcript
 * stops working. Ten agents each narrating themselves is not an overview; it is
 * ten transcripts interleaved.
 *
 * So the model here is a roll-up rather than a feed:
 *
 *   * one line per subagent, carrying its own state;
 *   * a parent state derived from its children, never stored separately, so
 *     the two can never disagree;
 *   * ordering by what needs a person first, so the top of the list is always
 *     the thing to look at.
 *
 * The parent's state is the highest-priority child state. A parent that shows
 * "working" while a child sits blocked on approval is the specific failure this
 * prevents — the work looks healthy and quietly is not.
 */

/** Ordered by how much they need a person. Higher wins a roll-up. */
export const SUBAGENT_STATES = Object.freeze({
  failed: 5,
  approval: 4,
  input: 3,
  blocked: 3,
  paused: 2.7,
  working: 2.5,
  launching: 2,
  queued: 1.5,
  ready: 1,
  planned: 0.5,
  cancelled: 0.3,
  completed: 0.2,
  unknown: 0.1,
  idle: 0,
});

export const SUBAGENT_STATE_LABELS = Object.freeze({
  failed: "Failed",
  approval: "Needs approval",
  input: "Needs you",
  blocked: "Blocked",
  paused: "Paused",
  working: "Working",
  launching: "Launching",
  queued: "Queued",
  ready: "Ready",
  planned: "Planned",
  idle: "Idle",
  completed: "Completed",
  cancelled: "Cancelled",
  unknown: "Unknown status",
});

/** States that mean a person is blocking progress. */
export const BLOCKING_STATES = Object.freeze(["failed", "approval", "input", "blocked"]);

function normalizeState(value) {
  const state = String(value || "").trim().toLowerCase();
  const aliases = {
    running: "working", active: "working", pending: "queued",
    waiting_for_approval: "approval", waiting_for_input: "input", waiting: "paused",
    done: "completed", returned: "completed", succeeded: "completed",
    canceled: "cancelled", error: "failed", requested: "planned",
    allocating: "launching", packing_context: "launching", isolating_workspace: "launching", connecting_tools: "launching",
  };
  const normalized = aliases[state] || state;
  return Object.hasOwn(SUBAGENT_STATES, normalized) ? normalized : "unknown";
}

/**
 * Normalise one subagent record from whatever the runtime reported.
 *
 * @param {object} raw
 * @returns {{id: string, name: string, state: string, task: string, startedAt: number|null,
 *            openable: boolean, blocking: boolean, detail: string}|null}
 */
export function normalizeSubagent(raw) {
  if (!raw || typeof raw !== "object") return null;
  const id = String(raw.id || raw.invocationId || raw.sessionId || "").trim();
  if (!id) return null;

  const state = normalizeState(raw.state || raw.status);
  const parsedStart = typeof raw.startedAt === "string" ? Date.parse(raw.startedAt) : raw.startedAt;
  const startedAt = Number.isFinite(parsedStart) ? Number(parsedStart) : null;

  return {
    id,
    // Falling back to the id keeps a nameless agent addressable rather than
    // rendering an empty row you cannot click.
    name: String(raw.name || raw.label || raw.runtime || id).trim(),
    state,
    task: String(raw.task || raw.purpose || "").trim(),
    startedAt,
    openable: raw.openable !== false,
    blocking: BLOCKING_STATES.includes(state),
    detail: String(raw.detail || "").trim(),
  };
}

/**
 * Roll a set of subagents into one overview.
 *
 * @param {Array<object>} rawAgents
 */
function summarizeSubagentsUnchecked(rawAgents = []) {
  const agents = (Array.isArray(rawAgents) ? rawAgents : [])
    .map(normalizeSubagent)
    .filter(Boolean);

  const counts = {};
  for (const agent of agents) {
    counts[agent.state] = (counts[agent.state] || 0) + 1;
  }

  const rolled = agents.reduce(
    (worst, agent) =>
      SUBAGENT_STATES[agent.state] > SUBAGENT_STATES[worst] ? agent.state : worst,
    "idle",
  );

  const blocking = agents.filter((agent) => agent.blocking);

  return {
    agents: sortSubagents(agents),
    total: agents.length,
    counts,
    // Derived, never stored: a parent cannot drift from its children.
    state: rolled,
    stateLabel: SUBAGENT_STATE_LABELS[rolled],
    blockingCount: blocking.length,
    needsYou: blocking.length > 0,
    label: describeSubagents(agents.length, counts, blocking.length),
  };
}

/**
 * Sort so the thing needing a person is first, then longest-running, then name.
 *
 * Stable and total: equal-priority agents keep a deterministic order so the
 * list does not reshuffle underneath a cursor on every poll.
 */
export function sortSubagents(agents = []) {
  return [...agents].sort((a, b) => {
    const priority = SUBAGENT_STATES[b.state] - SUBAGENT_STATES[a.state];
    if (priority !== 0) return priority;
    const aStart = a.startedAt ?? Infinity;
    const bStart = b.startedAt ?? Infinity;
    if (aStart !== bStart) return aStart - bStart;
    return a.name.localeCompare(b.name);
  });
}

/** One line for the collapsed header. */
export function describeSubagents(total, counts = {}, blockingCount = 0) {
  if (!total) return "No subagents running";
  const agents = `${total} subagent${total === 1 ? "" : "s"}`;
  if (blockingCount > 0) {
    return `${agents} · ${blockingCount} need${blockingCount === 1 ? "s" : ""} you`;
  }
  const working = counts.working || 0;
  if (working > 0) return `${agents} · ${working} working`;
  if (counts.launching) return `${agents} · ${counts.launching} launching`;
  if (counts.queued) return `${agents} · ${counts.queued} queued`;
  if (counts.completed === total) return `${agents} · all completed`;
  if (counts.cancelled === total) return `${agents} · all cancelled`;
  if (counts.completed || counts.cancelled) {
    return `${agents} · ${counts.completed || 0} completed · ${counts.cancelled || 0} cancelled`;
  }
  return agents;
}

/**
 * Whether the overview should be expanded by default.
 *
 * Expands when something is blocked, or when there are enough agents that the
 * collapsed line stops being a useful summary. Below that, an expanded panel is
 * just noise above a conversation.
 */
export function shouldExpandOverview(summary, { threshold = 3 } = {}) {
  if (!summary || !summary.total) return false;
  return summary.needsYou || summary.total >= threshold;
}

export function summarizeSubagents(...args) {
  const before = frontendContractBefore("attention.subagents", args);
  return checkedFrontendAction("attention.subagents", args, summarizeSubagentsUnchecked(...args), before);
}
