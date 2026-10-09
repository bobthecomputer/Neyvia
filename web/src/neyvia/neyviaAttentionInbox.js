import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
/**
 * Neyvia attention inbox.
 *
 * The sidebar is not a list of chats. It is the user's set of open mental
 * obligations, ordered so that what needs them rises and what has been accepted
 * visibly leaves without being lost.
 *
 * Five states, in attention order:
 *
 *   needs-action     Something is blocked on this person: an approval, an
 *                    answer, a failed verification, an unavailable runtime, a
 *                    security or policy decision.
 *   active           Work is genuinely moving: running, delegated, waiting on a
 *                    runtime or an external system, or paused but resumable.
 *   ready-for-review Work finished but has not been accepted: a delivered
 *                    artifact, a ready PR, verification evidence to look at.
 *   quiet            Deliberately not asking for attention: snoozed until a time
 *                    or an event, or waiting without needing anyone.
 *   settled          Accepted or intentionally closed. Collapsed toward the
 *                    bottom, still searchable, still openable by durable link.
 *
 * Two rules this module exists to enforce:
 *
 *   1. A runtime reporting "completed" never settles a thread. Completion is
 *      `ready-for-review`. Settlement requires an explicit acceptance recorded
 *      by the backend (`settledAt` / `settledBy`).
 *   2. Blocking approvals, security decisions and verification failures are
 *      never hidden by a snooze. They escape `quiet` and return to
 *      `needs-action`.
 *
 * Truthfulness: every thread records how its state was decided. `durable` means
 * the backend supplied the lifecycle fields. `derived` means this projection
 * inferred a state from real mission/conversation signals because the durable
 * attention fields do not exist yet. Nothing is invented in either mode, and
 * controls that would require durable persistence stay unavailable while the
 * inbox is `derived`.
 */

export const NEYVIA_ATTENTION_INBOX_SCHEMA = "neyvia.attention.inbox.v1";

/* ------------------------------------------------------------------ states */

export const NEYVIA_ATTENTION_STATES = Object.freeze([
  Object.freeze({
    id: "needs-action",
    label: "Needs action",
    order: 0,
    tone: "blocked",
    detail: "Blocked on you. Nothing moves until you decide.",
  }),
  Object.freeze({
    id: "active",
    label: "Active",
    order: 1,
    tone: "running",
    detail: "Open. Check the run for its current progress.",
  }),
  Object.freeze({
    id: "ready-for-review",
    label: "Ready for review",
    order: 2,
    tone: "review",
    detail: "Finished but not accepted. Accepting it settles the thread.",
  }),
  Object.freeze({
    id: "quiet",
    label: "Quiet",
    order: 3,
    tone: "quiet",
    detail: "Deliberately not asking for attention.",
  }),
  Object.freeze({
    id: "settled",
    label: "Settled",
    order: 4,
    tone: "settled",
    detail: "Accepted or closed. Still searchable and recoverable.",
  }),
]);

const STATE_BY_ID = new Map(NEYVIA_ATTENTION_STATES.map(item => [item.id, item]));

export const NEYVIA_ATTENTION_PRIORITY_STATES = Object.freeze([
  "needs-action",
  "active",
  "ready-for-review",
]);

const PRIORITY_STATE_SET = new Set(NEYVIA_ATTENTION_PRIORITY_STATES);

export function attentionStateMeta(id) {
  return STATE_BY_ID.get(String(id || "")) || null;
}

export function normalizeAttentionState(value) {
  const id = String(value || "").trim();
  return STATE_BY_ID.has(id) ? id : "active";
}

/* ----------------------------------------------------------------- reasons */

/**
 * Why a thread sits where it does. `blocking` reasons are the ones that
 * outrank a snooze — they are the user's responsibility, not a notification.
 */
export const NEYVIA_ATTENTION_REASONS = Object.freeze({
  blocked: Object.freeze({ id: "blocked", state: "needs-action", label: "Run blocked", blocking: true }),
  "approval-required": Object.freeze({
    id: "approval-required",
    state: "needs-action",
    label: "Approval required",
    blocking: true,
  }),
  "answer-required": Object.freeze({
    id: "answer-required",
    state: "needs-action",
    label: "Answer required",
    blocking: true,
  }),
  "verification-failed": Object.freeze({
    id: "verification-failed",
    state: "needs-action",
    label: "Verification failed",
    blocking: true,
  }),
  "runtime-unavailable": Object.freeze({
    id: "runtime-unavailable",
    state: "needs-action",
    label: "Runtime unavailable",
    blocking: true,
  }),
  "security-decision": Object.freeze({
    id: "security-decision",
    state: "needs-action",
    label: "Security or policy decision",
    blocking: true,
  }),
  running: Object.freeze({ id: "running", state: "active", label: "Running", blocking: false }),
  delegated: Object.freeze({ id: "delegated", state: "active", label: "Delegated", blocking: false }),
  "waiting-runtime": Object.freeze({
    id: "waiting-runtime",
    state: "active",
    label: "Waiting on a runtime",
    blocking: false,
  }),
  "waiting-external": Object.freeze({
    id: "waiting-external",
    state: "active",
    label: "Waiting on an external system",
    blocking: false,
  }),
  "paused-resumable": Object.freeze({
    id: "paused-resumable",
    state: "active",
    label: "Paused but resumable",
    blocking: false,
  }),
  "work-complete-unaccepted": Object.freeze({
    id: "work-complete-unaccepted",
    state: "ready-for-review",
    label: "Completed, not accepted",
    blocking: false,
  }),
  "artifact-delivered": Object.freeze({
    id: "artifact-delivered",
    state: "ready-for-review",
    label: "Artifact delivered",
    blocking: false,
  }),
  "pr-ready": Object.freeze({
    id: "pr-ready",
    state: "ready-for-review",
    label: "PR ready",
    blocking: false,
  }),
  "evidence-ready": Object.freeze({
    id: "evidence-ready",
    state: "ready-for-review",
    label: "Evidence ready",
    blocking: false,
  }),
  snoozed: Object.freeze({ id: "snoozed", state: "quiet", label: "Snoozed", blocking: false }),
  "waiting-no-attention": Object.freeze({
    id: "waiting-no-attention",
    state: "quiet",
    label: "Waiting, no attention needed",
    blocking: false,
  }),
  accepted: Object.freeze({ id: "accepted", state: "settled", label: "Accepted", blocking: false }),
  closed: Object.freeze({ id: "closed", state: "settled", label: "Closed", blocking: false }),
});

export function attentionReasonMeta(id) {
  return NEYVIA_ATTENTION_REASONS[String(id || "")] || null;
}

export function isBlockingReason(id) {
  return attentionReasonMeta(id)?.blocking === true;
}

/* ------------------------------------------------------------------ helpers */

function asList(value) {
  return Array.isArray(value) ? value : [];
}

function asRecord(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function text(value, fallback = "") {
  const out = String(value ?? "").trim();
  return out || fallback;
}

function timeValue(value) {
  if (!value) return 0;
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

function attentionActivityTierUnchecked(value, now = Date.now()) {
  const occurredAt = timeValue(value);
  if (!occurredAt) return "unknown";
  const age = Math.max(0, timeValue(now) - occurredAt);
  if (age < 15 * 60 * 1000) return "now";
  if (age < 6 * 60 * 60 * 1000) return "recent";
  if (age < 24 * 60 * 60 * 1000) return "today";
  return "older";
}

function attentionThreadDescriptionUnchecked(thread) {
  const item = asRecord(thread);
  const explicit = text(item.lastActivitySummary);
  if (explicit) return explicit;
  if (Number(item.approvals || 0) > 0) return "Waiting for your approval before work can continue.";
  if (Number(item.blockers || 0) > 0) return "Verification found a blocker that needs attention.";
  const primaryReason = asList(item.blockingReasons)[0] || asList(item.reasons)[0];
  const reason = attentionReasonMeta(primaryReason);
  if (reason) return reason.label;
  const state = attentionStateMeta(item.attentionState);
  return state?.detail || "No recent activity summary was reported.";
}

const TERMINAL_STATUSES = new Set(["completed", "done", "failed", "stopped", "cancelled", "canceled"]);
const RUNNING_STATUSES = new Set(["running", "active", "launching", "executing"]);
const BLOCKED_STATUSES = new Set(["failed", "error", "blocked", "needs_approval", "verification_failed", "awaiting_input"]);

/* -------------------------------------------------------------- projection */

/**
 * Project one thread.
 *
 * `conversation` is the durable conversation row. `mission` is the shared
 * Builder projection for the same work when there is one — that is where the
 * real approval, blocker and artifact counts live today. `runtimeStatus` is the
 * readiness map, used only to report a runtime the backend says is unavailable.
 */
function projectAttentionThreadUnchecked({
  conversation = null,
  mission = null,
  runtimeStatus = null,
  now = Date.now(),
} = {}) {
  const row = asRecord(conversation);
  const task = asRecord(mission);
  const threadId = text(row.conversationId || task.missionId);
  if (!threadId) return null;

  // Durable lifecycle fields, when the backend provides them.
  const durableState = text(row.attentionState);
  const settledAt = text(row.settledAt);
  const snoozedUntil = text(row.snoozedUntil);
  const hasDurableLifecycle = Boolean(durableState || settledAt || snoozedUntil);

  const reasons = [];
  const add = id => {
    if (attentionReasonMeta(id) && !reasons.includes(id)) reasons.push(id);
  };

  /* --- signals that block the user ------------------------------------- */

  const approvals = Number(task.approvals || row.pendingApprovalCount || 0);
  const blockers = Number(task.blockers || row.verificationFailureCount || 0);
  if (approvals > 0 || row.hasBlockingApproval === true) add("approval-required");
  if (blockers > 0 || row.hasVerificationFailure === true) add("verification-failed");
  if (row.awaitingUserAnswer === true) add("answer-required");
  if (row.securityDecisionPending === true) add("security-decision");

  const runtimeId = text(task.responsible || row.runtime).toLowerCase();
  if (runtimeId && runtimeStatus && runtimeStatus[runtimeId]?.available === false) {
    add("runtime-unavailable");
  }

  /* --- movement --------------------------------------------------------- */

  const status = text(task.status || row.status).toLowerCase();
  if (BLOCKED_STATUSES.has(status) && !reasons.some(isBlockingReason)) {
    add(status === "needs_approval" ? "approval-required" : status === "awaiting_input" ? "answer-required" : status === "verification_failed" ? "verification-failed" : "blocked");
  }
  const terminal = task.terminal === true || TERMINAL_STATUSES.has(status);
  if (!terminal) {
    // Conversation status "active" means open, not an executing agent.
    if (RUNNING_STATUSES.has(status) && (status !== "active" || text(task.status))) add("running");
    if (text(task.responsible)) add("delegated");
    if (status === "queued" || status === "waiting") add("waiting-runtime");
    if (status === "paused" || status === "suspended") add("paused-resumable");
  }

  /* --- finished but not accepted ---------------------------------------- */

  const artifactCount = Number(task.artifactCount || 0);
  if (terminal && !settledAt && ["completed", "done", "succeeded"].includes(status)) {
    // A runtime saying "completed" is not acceptance. It is a review request.
    add("work-complete-unaccepted");
    if (artifactCount > 0) add("artifact-delivered");
  }
  if (text(row.pullRequest?.state || row.pullRequest?.url)) add("pr-ready");
  if (row.hasVerificationEvidence === true) add("evidence-ready");

  /* --- resolution ------------------------------------------------------- */

  const blockingReasons = reasons.filter(isBlockingReason);
  const snoozeActive = Boolean(snoozedUntil) && timeValue(snoozedUntil) > now;

  let state;
  let settlementBlockedBySnooze = false;
  if (blockingReasons.length) {
    // Blocking obligations escape a snooze. They are never hidden.
    state = "needs-action";
    settlementBlockedBySnooze = snoozeActive;
  } else if (settledAt) {
    state = "settled";
    add(text(row.settlementReason) === "closed" ? "closed" : "accepted");
  } else if (snoozeActive) {
    state = "quiet";
    add("snoozed");
  } else if (durableState) {
    state = normalizeAttentionState(durableState);
  } else if (reasons.some(id => attentionReasonMeta(id)?.state === "ready-for-review")) {
    state = "ready-for-review";
  } else if (reasons.some(id => attentionReasonMeta(id)?.state === "active")) {
    state = "active";
  } else if (BLOCKED_STATUSES.has(status)) {
    state = "needs-action";
    add("blocked");
  } else {
    // No signal at all: a conversation nobody is waiting on.
    state = "quiet";
    add("waiting-no-attention");
  }

  const lastActivityAt = [
    row.lastMeaningfulActivityAt, task.lastEventAt, row.updatedAt, row.createdAt,
  ].map(value => text(value)).filter(Boolean).sort((left, right) => timeValue(right) - timeValue(left))[0] || "";
  const archivedReport = text(row.kind) === "orchestration" &&
    Boolean(row.conversationId) && timeValue(lastActivityAt) > 0 &&
    now - timeValue(lastActivityAt) > 14 * 24 * 60 * 60 * 1000;

  return Object.freeze({
    schema: NEYVIA_ATTENTION_INBOX_SCHEMA,
    threadId,
    conversationId: text(row.conversationId) || null,
    missionId: text(task.missionId || row.missionId) || null,
    kind: text(row.kind, task.missionId ? "orchestration" : "chat"),
    title: text(row.title || task.title, "New conversation"),
    attentionState: state,
    reasons: Object.freeze(reasons),
    blockingReasons: Object.freeze(blockingReasons),
    /** True when a blocking obligation overrode an active snooze. */
    escapedSnooze: settlementBlockedBySnooze,
    snoozedUntil: snoozedUntil || null,
    snoozeReason: text(row.snoozeReason) || null,
    settledAt: settledAt || null,
    settledBy: text(row.settledBy) || null,
    settlementReason: text(row.settlementReason) || null,
    /** workspaceId is the real grouping key today; projectId when supplied. */
    projectId: text(row.projectId) || null,
    workspaceId: text(row.workspaceId || task.workspaceId) || null,
    branch: text(row.branch) || null,
    pullRequest: row.pullRequest && typeof row.pullRequest === "object" ? row.pullRequest : null,
    unreadMeaningfulChanges: Number(row.unreadMeaningfulChanges || 0),
    lastMeaningfulActivityAt: lastActivityAt || null,
    activityTier: attentionActivityTier(lastActivityAt, now),
    archivedReport,
    lastActivitySummary: text(task.lastEventSummary || row.lastActivitySummary) || null,
    nextWakeCondition: text(row.nextWakeCondition) || null,
    artifactCount,
    approvals,
    blockers,
    progress: Number.isFinite(Number(task.progress)) ? Number(task.progress) : null,
    /** How this classification was reached. */
    derivation: hasDurableLifecycle ? "durable" : "derived",
  });
}

/* ----------------------------------------------------------------- ordering */

/**
 * Within a group: blocking first, then most recently meaningful. Settled sorts
 * newest-accepted first so the most recent completion is the easiest to recover.
 */
export function compareAttentionThreads(left, right) {
  const blockingDelta = right.blockingReasons.length - left.blockingReasons.length;
  if (blockingDelta) return blockingDelta;
  const unreadDelta = right.unreadMeaningfulChanges - left.unreadMeaningfulChanges;
  if (unreadDelta) return unreadDelta;
  const leftAt = timeValue(left.settledAt || left.lastMeaningfulActivityAt);
  const rightAt = timeValue(right.settledAt || right.lastMeaningfulActivityAt);
  if (leftAt !== rightAt) return rightAt - leftAt;
  const titleDelta = String(left.title).localeCompare(String(right.title));
  if (titleDelta) return titleDelta;
  return String(left.threadId).localeCompare(String(right.threadId));
}

/** Recent is chronological, even when an older report still has a blocker. */
function compareRecentThreadsUnchecked(left, right) {
  const delta = timeValue(right.lastMeaningfulActivityAt) - timeValue(left.lastMeaningfulActivityAt);
  return delta || compareAttentionThreads(left, right);
}

/** Priority is state-first; recency only orders rows within one state. */
export function comparePriorityThreads(left, right) {
  const leftState = attentionStateMeta(left.attentionState);
  const rightState = attentionStateMeta(right.attentionState);
  const stateDelta = (leftState?.order ?? Number.MAX_SAFE_INTEGER) -
    (rightState?.order ?? Number.MAX_SAFE_INTEGER);
  if (stateDelta) return stateDelta;
  return compareAttentionThreads(left, right);
}

function validTimeZone(value) {
  const candidate = text(value) || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  try {
    new Intl.DateTimeFormat("en", { timeZone: candidate }).format();
    return candidate;
  } catch {
    return "UTC";
  }
}

function calendarParts(value, timeZone) {
  const parts = new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "2-digit",
    timeZone,
    year: "numeric",
  }).formatToParts(new Date(value));
  return Object.fromEntries(parts.filter(part => part.type !== "literal").map(part => [part.type, part.value]));
}

function calendarKey(value, timeZone) {
  const parts = calendarParts(timeValue(value), timeZone);
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function previousCalendarKey(key) {
  const [year, month, day] = key.split("-").map(Number);
  const previous = new Date(Date.UTC(year, month - 1, day) - 24 * 60 * 60 * 1000);
  return previous.toISOString().slice(0, 10);
}

function olderDateLabel(key, { locale, timeZone }) {
  const [year, month, day] = key.split("-").map(Number);
  return new Intl.DateTimeFormat(locale || undefined, {
    day: "numeric",
    month: "short",
    timeZone,
    year: "numeric",
  }).format(new Date(Date.UTC(year, month - 1, day, 12)));
}

function attentionActivityAt(thread) {
  return thread.settledAt || thread.lastMeaningfulActivityAt;
}

function makeAttentionSection({ id, label, kind, stateIds, threads, dateKey = null }) {
  return Object.freeze({
    id,
    label,
    kind,
    stateIds: Object.freeze([...stateIds]),
    dateKey,
    threads: Object.freeze([...threads]),
  });
}

/**
 * Build the visible Priority/history sections without changing row state.
 * Calendar calculations use the supplied IANA timezone, so DST transitions
 * and local midnight boundaries do not become accidental 24-hour windows.
 */
function projectAttentionSectionsUnchecked(
  threads = [],
  { locale, timeZone, now = Date.now() } = {},
) {
  const zone = validTimeZone(timeZone);
  const todayKey = calendarKey(now, zone);
  const yesterdayKey = previousCalendarKey(todayKey);
  const priority = [];
  const history = new Map();

  for (const thread of asList(threads)) {
    if (PRIORITY_STATE_SET.has(thread.attentionState)) {
      priority.push(thread);
      continue;
    }
    const key = calendarKey(attentionActivityAt(thread) || 0, zone);
    if (!history.has(key)) history.set(key, []);
    history.get(key).push(thread);
  }

  const sections = [
    makeAttentionSection({
      id: "priority",
      label: "Priority",
      kind: "priority",
      stateIds: NEYVIA_ATTENTION_PRIORITY_STATES,
      threads: priority.sort(comparePriorityThreads),
    }),
    makeAttentionSection({
      id: "today",
      label: "Today",
      kind: "date",
      stateIds: ["quiet", "settled"],
      dateKey: todayKey,
      threads: (history.get(todayKey) || []).sort(compareAttentionThreads),
    }),
    makeAttentionSection({
      id: "yesterday",
      label: "Yesterday",
      kind: "date",
      stateIds: ["quiet", "settled"],
      dateKey: yesterdayKey,
      threads: (history.get(yesterdayKey) || []).sort(compareAttentionThreads),
    }),
  ];

  [...history.keys()]
    .filter(key => key !== todayKey && key !== yesterdayKey)
    .sort((left, right) => right.localeCompare(left))
    .forEach(key => {
      sections.push(makeAttentionSection({
        id: `date:${key}`,
        label: olderDateLabel(key, { locale, timeZone: zone }),
        kind: "date",
        stateIds: ["quiet", "settled"],
        dateKey: key,
        threads: history.get(key).sort(compareAttentionThreads),
      }));
    });

  return Object.freeze(sections);
}

/* -------------------------------------------------------------------- inbox */

/**
 * Build the whole inbox.
 *
 * `capabilities.durableLifecycle` tells the UI whether settle/snooze can be
 * offered at all. When false, the grouping is still real — it is derived from
 * live mission and conversation signals — but nothing pretends the user's
 * decisions can be stored yet.
 */
function buildAttentionInboxUnchecked({
  conversations = [],
  missions = [],
  runtimeStatus = null,
  now = Date.now(),
  durableLifecycle = false,
  locale,
  timeZone,
} = {}) {
  const missionById = new Map(
    asList(missions)
      .map(item => [text(asRecord(item).missionId), asRecord(item)])
      .filter(([id]) => id),
  );

  const threads = [];
  const claimedMissionIds = new Set();
  const seenThreadIds = new Set();
  const addThread = thread => {
    if (!thread || seenThreadIds.has(thread.threadId)) return;
    seenThreadIds.add(thread.threadId);
    threads.push(thread);
  };

  for (const conversation of asList(conversations)) {
    const row = asRecord(conversation);
    const linkedMissionId = text(row.missionId || asRecord(row.metadata).missionId);
    const mission = linkedMissionId ? missionById.get(linkedMissionId) : null;
    if (mission) claimedMissionIds.add(linkedMissionId);
    const thread = projectAttentionThread({ conversation: row, mission, runtimeStatus, now });
    addThread(thread);
  }

  // Missions with no conversation of their own are still obligations.
  for (const [missionId, mission] of missionById) {
    if (claimedMissionIds.has(missionId)) continue;
    // Old unlinked mission reports belong in Session map, not the daily
    // conversation inbox. A linked durable conversation remains here.
    const missionAt = timeValue(mission.lastEventAt || mission.updatedAt || mission.createdAt);
    const agedMissionReport = missionAt > 0 &&
      now - missionAt > 14 * 24 * 60 * 60 * 1000;
    if (agedMissionReport) continue;
    const thread = projectAttentionThread({ mission, runtimeStatus, now });
    addThread(thread);
  }

  const sortedThreads = threads.slice().sort((left, right) => {
    const stateDelta = attentionStateMeta(left.attentionState).order - attentionStateMeta(right.attentionState).order;
    return stateDelta || compareAttentionThreads(left, right);
  });
  const groups = projectAttentionSections(sortedThreads, { locale, timeZone, now });

  const needsActionCount = sortedThreads.filter(item => item.attentionState === "needs-action").length;
  const derivedCount = threads.filter(item => item.derivation === "derived").length;

  return Object.freeze({
    schema: NEYVIA_ATTENTION_INBOX_SCHEMA,
    generatedAt: new Date(now).toISOString(),
    groups,
    threads: Object.freeze(sortedThreads),
    counts: Object.freeze(
      Object.fromEntries(
        NEYVIA_ATTENTION_STATES.map(state => [
          state.id,
          sortedThreads.filter(thread => thread.attentionState === state.id).length,
        ]),
      ),
    ),
    needsActionCount,
    /** Lifecycle controls are only real when the backend can persist them. */
    durableLifecycle: Boolean(durableLifecycle),
    derivedCount,
    disclosure: durableLifecycle
      ? "Attention states are read from the durable conversation lifecycle."
      : "Attention states are derived from live mission and conversation signals. Settle and snooze need the durable lifecycle commands before they can be offered.",
  });
}

/* -------------------------------------------------------------- grouping */

/**
 * Project grouping for pickers, filters and mobile lists. Uses `projectId` when
 * the backend supplies one and falls back to `workspaceId`, which is real today.
 */
function groupThreadsByProjectUnchecked(threads = [], { labels = {} } = {}) {
  const groups = new Map();
  for (const thread of asList(threads)) {
    const key = thread.projectId || thread.workspaceId || "";
    const id = key || "unassigned";
    if (!groups.has(id)) {
      groups.set(id, {
        id,
        label: labels[id] || (key ? key : "No project"),
        assigned: Boolean(key),
        threads: [],
      });
    }
    groups.get(id).threads.push(thread);
  }
  return [...groups.values()]
    .map(group => ({ ...group, threads: group.threads.sort(compareAttentionThreads) }))
    .sort((left, right) => {
      if (left.assigned !== right.assigned) return left.assigned ? -1 : 1;
      return String(left.label).localeCompare(String(right.label));
    });
}

/* -------------------------------------------------------------- filtering */

export const NEYVIA_ATTENTION_FILTERS = Object.freeze([
  Object.freeze({ id: "open", label: "Open", states: ["needs-action", "active", "ready-for-review"] }),
  Object.freeze({ id: "needs-action", label: "Needs you", states: ["needs-action"] }),
  Object.freeze({ id: "review", label: "Review", states: ["ready-for-review"] }),
  Object.freeze({ id: "quiet", label: "Quiet", states: ["quiet"] }),
  Object.freeze({ id: "settled", label: "Settled", states: ["settled"] }),
  Object.freeze({
    id: "all",
    label: "All",
    states: ["needs-action", "active", "ready-for-review", "quiet", "settled"],
  }),
]);

export function attentionFilterMeta(id) {
  return NEYVIA_ATTENTION_FILTERS.find(item => item.id === String(id || "")) || NEYVIA_ATTENTION_FILTERS[0];
}

function filterInboxGroupsUnchecked(inbox, filterId) {
  const filter = attentionFilterMeta(filterId);
  return asList(inbox?.groups).map(group => ({
    ...group,
    threads: Object.freeze(
      asList(group.threads).filter(thread =>
        filter.states.includes(thread.attentionState) && (filter.id !== "open" || !thread.archivedReport)),
    ),
  }));
}

/* --------------------------------------------------------------- commands */

/**
 * The durable lifecycle commands this projection needs. They do not exist yet;
 * `probeAttentionLifecycle` reports that truthfully instead of the UI assuming.
 */
export const NEYVIA_ATTENTION_COMMANDS = Object.freeze({
  inbox: "get_neyvia_attention_inbox_command",
  settle: "settle_neyvia_conversation_command",
  reopen: "reopen_neyvia_conversation_command",
  snooze: "snooze_neyvia_conversation_command",
  wake: "wake_neyvia_conversation_command",
  setProject: "set_neyvia_conversation_project_command",
});

/**
 * Ask the backend whether the durable attention lifecycle exists.
 *
 * A failure is not an error state for the user — it means the sidebar runs in
 * derived mode with lifecycle controls unavailable and says so.
 */
export async function probeAttentionLifecycle(callBackend) {
  if (typeof callBackend !== "function") return { available: false, reason: "No backend bridge." };
  try {
    const data = await callBackend(NEYVIA_ATTENTION_COMMANDS.inbox, { probe: true });
    if (data && typeof data === "object" && data.schema === NEYVIA_ATTENTION_INBOX_SCHEMA) {
      return { available: true, inbox: data };
    }
    return {
      available: false,
      reason: "The attention inbox command answered with an unexpected schema.",
    };
  } catch (error) {
    return {
      available: false,
      reason: String(error?.message || error || "Attention lifecycle command is not available."),
    };
  }
}

export function projectAttentionThread(...args) {
  const before = frontendContractBefore("attention.thread", args);
  return checkedFrontendAction("attention.thread", args, projectAttentionThreadUnchecked(...args), before);
}

export function attentionActivityTier(...args) {
  const before = frontendContractBefore("attention.activity", args);
  return checkedFrontendAction("attention.activity", args, attentionActivityTierUnchecked(...args), before);
}

export function attentionThreadDescription(...args) {
  const before = frontendContractBefore("attention.description", args);
  return checkedFrontendAction("attention.description", args, attentionThreadDescriptionUnchecked(...args), before);
}

export function projectAttentionSections(...args) {
  const before = frontendContractBefore("attention.sections", args);
  return checkedFrontendAction("attention.sections", args, projectAttentionSectionsUnchecked(...args), before);
}

export function buildAttentionInbox(...args) {
  const before = frontendContractBefore("attention.inbox", args);
  return checkedFrontendAction("attention.inbox", args, buildAttentionInboxUnchecked(...args), before);
}

export function filterInboxGroups(...args) {
  const before = frontendContractBefore("attention.filter", args);
  return checkedFrontendAction("attention.filter", args, filterInboxGroupsUnchecked(...args), before);
}

export function groupThreadsByProject(...args) {
  const before = frontendContractBefore("attention.projects", args);
  return checkedFrontendAction("attention.projects", args, groupThreadsByProjectUnchecked(...args), before);
}

export function compareRecentThreads(...args) {
  const before = frontendContractBefore("attention.recent", args);
  return checkedFrontendAction("attention.recent", args, compareRecentThreadsUnchecked(...args), before);
}
