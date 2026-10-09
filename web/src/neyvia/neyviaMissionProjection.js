import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
/**
 * Neyvia shared mission projection.
 *
 * Builder and Agent Live are two projections of one record set — not two
 * stores with copied data:
 *
 *   Builder    — supervisory/historical. Compare and supervise many tasks;
 *                drill into a mission's complete dated event sequence.
 *   Agent Live — the live working room for one mission: messages, runtime
 *                state, approvals, evidence, delivered artifacts, and
 *                exercising what the agent produced.
 *
 * Both read `MissionRecord`s from this store. Events arrive incrementally via
 * a cursor so a long timeline is never re-fetched whole, artifact *contents*
 * are never held here (only light descriptors), and several surfaces watching
 * the same mission share one backend subscription.
 */

export const NEYVIA_MISSION_PROJECTION_SCHEMA = "neyvia.mission.projection.v1";

/** Hard ceiling so a long-running mission cannot grow the client without bound. */
export const MISSION_EVENT_WINDOW = 600;

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

/* ------------------------------------------------------------ identity */

export function missionIdOf(value) {
  const item = asRecord(value);
  return text(item.missionId || item.mission_id || item.id);
}

/**
 * Stable event identity. The backend event log is append-only JSONL without a
 * guaranteed id field, so identity is derived deterministically from the
 * content that makes an event unique. Same event ⇒ same id ⇒ no duplicates
 * when a delta overlaps what we already hold.
 */
export function missionEventId(event, index = 0) {
  const item = asRecord(event);
  const explicit = text(item.eventId || item.event_id);
  if (explicit) return explicit;
  const at = text(item.timestamp || item.created_at || item.createdAt || item.at);
  const kind = text(item.kind || item.event || item.type, "event");
  const body = text(item.message || item.detail || item.summary).slice(0, 160);
  return `${at}|${kind}|${body}|${index}`;
}

export function normalizeMissionEvent(event, index = 0) {
  const item = asRecord(event);
  const at = text(item.timestamp || item.created_at || item.createdAt || item.at);
  return Object.freeze({
    eventId: missionEventId(item, index),
    missionId: missionIdOf(item),
    at,
    kind: text(item.kind || item.event || item.type, "event"),
    actor: text(item.actor || item.agent || item.author || item.runtime, "") || null,
    runtime: text(item.runtime || item.provider || item.model, "") || null,
    message: text(item.message || item.detail || item.summary),
    /** Descriptor only — artifact bodies are fetched when opened. */
    artifactRefs: Object.freeze(
      asList(item.artifacts || item.artifactRefs).map(value =>
        typeof value === "string"
          ? Object.freeze({ artifactId: value })
          : Object.freeze({
              artifactId: text(asRecord(value).artifactId || asRecord(value).id || asRecord(value).path),
              kind: text(asRecord(value).kind),
              label: text(asRecord(value).label || asRecord(value).name),
            }),
      ),
    ),
    raw: item,
  });
}

/** Descriptor for a delivered artifact — no bytes, no inline preview payloads. */
export function normalizeArtifactDescriptor(value) {
  const item = asRecord(value);
  const artifactId = text(
    item.artifactId || item.id || item.path || item.url || item.servedUrl,
  );
  if (!artifactId) return null;
  return Object.freeze({
    artifactId,
    missionId: missionIdOf(item),
    kind: text(item.kind || item.type, "artifact"),
    label: text(item.label || item.name || item.title, artifactId),
    mediaType: text(item.mediaType || item.media_type || item.contentType) || null,
    /** How to *open* it — resolved lazily by the embedded-workspace adapter. */
    contentRef: Object.freeze({
      path: text(item.path) || null,
      url: text(item.url || item.servedUrl || item.previewUrl) || null,
      endpoint: text(item.safeEndpoint || item.endpoint) || null,
    }),
    producedByEventId: text(item.eventId || item.event_id) || null,
    at: text(item.timestamp || item.created_at || item.at) || null,
  });
}

/* --------------------------------------------------------- mission record */

export function createMissionRecord(summary = {}) {
  const item = asRecord(summary);
  const missionId = missionIdOf(item);
  return Object.freeze({
    schema: NEYVIA_MISSION_PROJECTION_SCHEMA,
    missionId,
    summary: Object.freeze({ ...item }),
    detail: null,
    events: Object.freeze([]),
    eventCursor: null,
    artifacts: Object.freeze([]),
    runtime: null,
    /** Set once the mission's full timeline has been loaded at least once. */
    timelineLoadedAt: null,
    updatedAt: text(
      item.updatedAt || item.updated_at || item.createdAt || item.created_at,
    ) || null,
  });
}

export function createMissionProjectionStore() {
  return Object.freeze({
    schema: NEYVIA_MISSION_PROJECTION_SCHEMA,
    missions: Object.freeze({}),
    order: Object.freeze([]),
    subscriptions: Object.freeze({}),
    selectedMissionId: null,
  });
}

function withMissions(store, missions, order = null) {
  return Object.freeze({
    ...store,
    missions: Object.freeze(missions),
    order: Object.freeze(order || store.order),
  });
}

/**
 * Merge a control-room snapshot. Summaries are cheap and refresh often;
 * loaded details, events and artifacts are preserved across refreshes so a
 * snapshot poll never discards an open Agent Live timeline.
 */
export function mergeMissionSummaries(store, summaries = []) {
  const next = { ...store.missions };
  const order = [];
  for (const summary of asList(summaries)) {
    const missionId = missionIdOf(summary);
    if (!missionId) continue;
    order.push(missionId);
    const existing = next[missionId];
    next[missionId] = existing
      ? Object.freeze({
          ...existing,
          summary: Object.freeze({ ...asRecord(summary) }),
          updatedAt:
            text(asRecord(summary).updatedAt || asRecord(summary).updated_at) || existing.updatedAt,
        })
      : createMissionRecord(summary);
  }
  // Keep records the snapshot did not include (e.g. an open mission detail).
  for (const missionId of Object.keys(store.missions)) {
    if (!order.includes(missionId)) order.push(missionId);
  }
  return withMissions(store, next, order);
}

/**
 * Merge a mission detail snapshot (`get_control_room_mission_detail_command`).
 * The detail's events are treated as a delta, not as a replacement.
 */
export function mergeMissionDetail(store, missionId, detail) {
  const id = text(missionId);
  if (!id) return store;
  const item = asRecord(detail);
  const existing = store.missions[id] || createMissionRecord({ missionId: id });
  const merged = Object.freeze({
    ...existing,
    detail: Object.freeze({ ...item }),
    runtime: asRecord(item.delegatedRuntime || item.runtime) || existing.runtime,
    timelineLoadedAt: new Date().toISOString(),
  });
  const withDetail = withMissions(store, { ...store.missions, [id]: merged });
  const events = asList(item.events || item.timeline || item.missionEvents);
  const artifacts = asList(item.artifacts || item.deliverables);
  let next = events.length
    ? applyMissionEventDelta(withDetail, id, events, item.eventCursor || item.cursor || null)
    : withDetail;
  if (artifacts.length) next = mergeMissionArtifacts(next, id, artifacts);
  return next;
}

/**
 * Incremental event application. Deduped by derived event id, ordered oldest →
 * newest, and trimmed to the retained window so a long Builder timeline stays
 * cheap to hold and to render.
 */
function applyMissionEventDeltaUnchecked(
  store,
  missionId,
  events = [],
  cursor = null,
  { reset = false } = {},
) {
  const id = text(missionId);
  if (!id) return store;
  const existing = store.missions[id] || createMissionRecord({ missionId: id });
  const seen = new Map(
    (reset ? [] : existing.events).map(event => [event.eventId, event]),
  );
  asList(events).forEach((event, index) => {
    const normalized = normalizeMissionEvent(event, seen.size + index);
    if (!seen.has(normalized.eventId)) seen.set(normalized.eventId, normalized);
  });
  const ordered = [...seen.values()].sort((left, right) => {
    const delta = String(left.at).localeCompare(String(right.at));
    return delta || String(left.eventId).localeCompare(String(right.eventId));
  });
  const trimmed = ordered.length > MISSION_EVENT_WINDOW
    ? ordered.slice(ordered.length - MISSION_EVENT_WINDOW)
    : ordered;
  const merged = Object.freeze({
    ...existing,
    events: Object.freeze(trimmed),
    eventCursor: cursor != null ? cursor : existing.eventCursor,
    updatedAt: trimmed.length ? trimmed[trimmed.length - 1].at : existing.updatedAt,
  });
  return withMissions(store, { ...store.missions, [id]: merged });
}

function mergeMissionArtifactsUnchecked(store, missionId, artifacts = []) {
  const id = text(missionId);
  if (!id) return store;
  const existing = store.missions[id] || createMissionRecord({ missionId: id });
  const byId = new Map(existing.artifacts.map(item => [item.artifactId, item]));
  for (const value of asList(artifacts)) {
    const descriptor = normalizeArtifactDescriptor({ missionId: id, ...asRecord(value) });
    if (descriptor) byId.set(descriptor.artifactId, descriptor);
  }
  const merged = Object.freeze({
    ...existing,
    artifacts: Object.freeze([...byId.values()]),
  });
  return withMissions(store, { ...store.missions, [id]: merged });
}

export function selectMissionRecord(store, missionId) {
  return store?.missions?.[text(missionId)] || null;
}

/**
 * Where to resume incremental polling from. `null` means "load the window".
 */
export function missionEventCursor(store, missionId) {
  return selectMissionRecord(store, missionId)?.eventCursor ?? null;
}

/* ------------------------------------------------------- subscriptions */

/**
 * Refcounted subscriptions: Builder and Agent Live watching the same mission
 * share one backend poll/stream instead of opening two.
 */
export function acquireMissionSubscription(store, missionId, subscriberId) {
  const id = text(missionId);
  if (!id) return { store, shouldStart: false };
  const current = asRecord(store.subscriptions[id]);
  const subscribers = new Set(asList(current.subscribers));
  const shouldStart = subscribers.size === 0;
  subscribers.add(text(subscriberId, "anonymous"));
  return {
    store: Object.freeze({
      ...store,
      subscriptions: Object.freeze({
        ...store.subscriptions,
        [id]: Object.freeze({ subscribers: Object.freeze([...subscribers]) }),
      }),
    }),
    shouldStart,
  };
}

export function releaseMissionSubscription(store, missionId, subscriberId) {
  const id = text(missionId);
  const current = asRecord(store.subscriptions[id]);
  const subscribers = new Set(asList(current.subscribers));
  subscribers.delete(text(subscriberId, "anonymous"));
  const nextSubscriptions = { ...store.subscriptions };
  if (subscribers.size) {
    nextSubscriptions[id] = Object.freeze({ subscribers: Object.freeze([...subscribers]) });
  } else {
    delete nextSubscriptions[id];
  }
  return {
    store: Object.freeze({ ...store, subscriptions: Object.freeze(nextSubscriptions) }),
    shouldStop: subscribers.size === 0,
  };
}

export function missionSubscriberCount(store, missionId) {
  return asList(asRecord(store?.subscriptions?.[text(missionId)]).subscribers).length;
}

/* --------------------------------------------------------- projections */

const TERMINAL_STATUSES = new Set(["completed", "done", "failed", "stopped", "cancelled", "canceled"]);

function missionStatus(record) {
  const summary = asRecord(record?.summary);
  return text(
    summary.status || asRecord(summary.state).status || summary.statusLabel,
    "unknown",
  ).toLowerCase();
}

/**
 * Builder projection — the supervisory row. Comparable across missions,
 * derived only from what the record actually holds.
 */
export function projectBuilderRow(record) {
  if (!record) return null;
  const summary = asRecord(record.summary);
  const state = asRecord(summary.state);
  const status = missionStatus(record);
  const approvals = asList(asRecord(summary.proof).pending_approvals).length;
  const blockers = asList(state.verification_failures).length;
  const lastEvent = record.events[record.events.length - 1] || null;
  return Object.freeze({
    schema: NEYVIA_MISSION_PROJECTION_SCHEMA,
    projection: "builder",
    missionId: record.missionId,
    title: text(summary.title || summary.goal || summary.name, record.missionId),
    status,
    terminal: TERMINAL_STATUSES.has(status),
    stage: text(state.stage || summary.stage || summary.phase) || null,
    responsible: text(
      asRecord(summary.delegatedRuntime).runtime || summary.agent || summary.owner,
    ) || null,
    approvals,
    blockers,
    artifactCount: record.artifacts.length,
    eventCount: record.events.length,
    /** Truthful: null when the backend has not reported usage. */
    usage: asRecord(summary.usage).total != null ? asRecord(summary.usage) : null,
    progress: Number.isFinite(Number(asRecord(summary.liveProgress).value))
      ? Number(asRecord(summary.liveProgress).value)
      : null,
    lastEventAt: lastEvent?.at || record.updatedAt || null,
    lastEventSummary: lastEvent?.message || null,
    timelineLoaded: Boolean(record.timelineLoadedAt),
  });
}

export function projectBuilderRows(store) {
  return asList(store?.order)
    .map(missionId => projectBuilderRow(selectMissionRecord(store, missionId)))
    .filter(Boolean);
}

/**
 * Builder timeline projection — chronological, windowed for efficient render.
 * `offset` counts from the newest end so the default view is the recent tail.
 */
export function projectMissionTimeline(store, missionId, { limit = 80, offset = 0 } = {}) {
  const record = selectMissionRecord(store, missionId);
  if (!record) return Object.freeze({ missionId: text(missionId), events: Object.freeze([]), total: 0, hasMore: false });
  const total = record.events.length;
  const end = Math.max(0, total - Math.max(0, offset));
  const start = Math.max(0, end - Math.max(1, limit));
  return Object.freeze({
    schema: NEYVIA_MISSION_PROJECTION_SCHEMA,
    projection: "builder-timeline",
    missionId: record.missionId,
    events: Object.freeze(record.events.slice(start, end)),
    total,
    hasMore: start > 0,
    windowStart: start,
    windowEnd: end,
  });
}

/**
 * Agent Live projection — the live room for one mission. Same records, live
 * emphasis: current activity, approvals, evidence, and delivered artifacts
 * that can be exercised in place.
 */
function projectAgentLiveViewUnchecked(store, missionId) {
  const record = selectMissionRecord(store, missionId);
  if (!record) return null;
  const summary = asRecord(record.summary);
  const detail = asRecord(record.detail);
  const status = missionStatus(record);
  const recent = record.events.slice(-40);
  return Object.freeze({
    schema: NEYVIA_MISSION_PROJECTION_SCHEMA,
    projection: "agent-live",
    missionId: record.missionId,
    title: text(summary.title || summary.goal, record.missionId),
    status,
    // A resumable or queued mission is not evidence of active execution.
    live: ["running", "working", "active"].includes(status),
    runtime: record.runtime || null,
    /** Same event objects as Builder — one identity, two emphases. */
    messages: Object.freeze(recent),
    latestEvent: recent[recent.length - 1] || null,
    approvals: Object.freeze(asList(asRecord(summary.proof).pending_approvals)),
    evidence: Object.freeze(asList(detail.evidence || detail.receipts)),
    artifacts: record.artifacts,
    detailLoaded: Boolean(record.detail),
    timelineLoadedAt: record.timelineLoadedAt,
  });
}

/* ------------------------------------------------------------- handoff */

/**
 * The Builder → Agent Live transition contract. Everything the live surface
 * needs to open in the same context the user was already looking at.
 */
export function buildMissionHandoff(store, missionId, {
  artifactId = null,
  timelineEventId = null,
  origin = "builder",
  intent = "inspect",
} = {}) {
  const record = selectMissionRecord(store, missionId);
  if (!record) return null;
  const artifact = artifactId
    ? record.artifacts.find(item => item.artifactId === artifactId) || null
    : null;
  const event = timelineEventId
    ? record.events.find(item => item.eventId === timelineEventId) || null
    : null;
  return Object.freeze({
    schema: "neyvia.mission.handoff.v1",
    missionId: record.missionId,
    origin: text(origin, "builder"),
    intent: text(intent, "inspect"),
    title: text(asRecord(record.summary).title, record.missionId),
    timelineEventId: event?.eventId || null,
    timelineEventAt: event?.at || null,
    artifact: artifact || null,
    runtime: record.runtime || null,
    /** The route back to the supervisory overview — never a dead end. */
    returnTo: Object.freeze({ surface: text(origin, "builder"), missionId: record.missionId }),
  });
}

/** Reverse route: Agent Live → Builder, keeping the selected mission. */
export function buildSupervisoryReturn(handoff) {
  const item = asRecord(handoff);
  return Object.freeze({
    schema: "neyvia.mission.handoff.v1",
    missionId: text(item.missionId),
    origin: "agent-live",
    intent: "supervise",
    surface: text(asRecord(item.returnTo).surface, "builder"),
    timelineEventId: item.timelineEventId || null,
  });
}

/** Backend commands this projection reads from. */
export const NEYVIA_MISSION_PROJECTION_COMMANDS = Object.freeze({
  summary: "get_control_room_summary_command",
  detail: "get_control_room_mission_detail_command",
  events: "get_control_room_mission_events_command",
});

export function projectAgentLiveView(...args) {
  const before = frontendContractBefore("mission.live", args);
  return checkedFrontendAction("mission.live", args, projectAgentLiveViewUnchecked(...args), before);
}

export function applyMissionEventDelta(...args) {
  const before = frontendContractBefore("mission.delta", args);
  return checkedFrontendAction("mission.delta", args, applyMissionEventDeltaUnchecked(...args), before);
}

export function mergeMissionArtifacts(...args) {
  const before = frontendContractBefore("mission.artifacts", args);
  return checkedFrontendAction("mission.artifacts", args, mergeMissionArtifactsUnchecked(...args), before);
}
