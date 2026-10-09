import { useSyncExternalStore } from "react";
import { backendBase, callNx, isDesktopApp, subscribeEvents } from "./nxApi.js";
import { sendIdentity } from "./nxComposerModel.js";
import { planFromPage } from "./nxPlanModel.js";

// Single client-side store for the control UI. The backend is the source of
// truth; this only mirrors the list, open threads and live runs, and applies
// the cursor-ordered event stream on top.

const ACTIVE = new Set(["queued", "running", "waiting_approval", "waiting_input"]);
export const isRunActive = run => Boolean(run && ACTIVE.has(run.state));

let state = {
  connection: "connecting",
  host: null,
  list: { status: "idle", error: "", sources: [], total: 0 },
  sessions: {},
  order: [],
  threads: {},
  runs: {},
  feedback: {}, // runId -> {verdict, at, lessons: {lessonId: {state, title}}} from after-task feedback (plan 20 C9)
  amplify: {}, // sessionId -> last prompt.amplified|edited|consumed event (plan 20 C14)
  amplifyLearning: {}, // amplificationId -> {state, reason, lessonIds}: where Paul's edit went (C9 lesson gate)
};
const listeners = new Set();

function set(patch) {
  state = { ...state, ...(typeof patch === "function" ? patch(state) : patch) };
  for (const listener of listeners) listener();
}

export function useNx(selector) {
  return useSyncExternalStore(
    listener => { listeners.add(listener); return () => listeners.delete(listener); },
    () => selector(state),
  );
}

export const getNx = () => state;

function sortOrder(sessions) {
  return Object.values(sessions)
    .sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")))
    .map(session => session.id);
}

function withThread(id, update) {
  const current = state.threads[id];
  if (!current) return;
  set({ threads: { ...state.threads, [id]: { ...current, ...update(current) } } });
}

export function insertItem(items, item) {
  const next = items.filter(existing => existing.id !== item.id && !(existing.optimistic && item.kind === "user" && existing.data?.text === item.data?.text));
  let index = next.length;
  while (index > 0 && Number(next[index - 1].seq) > Number(item.seq)) index -= 1;
  next.splice(index, 0, item);
  return next;
}

export function nextMessageSequence(items) {
  return Math.max(-1, ...items.map(item => Number(item.seq) || 0)) + 1;
}

let lastQuery = "";

let listRetries = 0;
const listRequests = new Map();
export function loadList({ query = lastQuery } = {}) {
  lastQuery = query;
  const payload = { query, limit: 300 };
  // The shell and sidebar may mount together. Share only the exact owner read
  // in the same transport context; a different search still starts immediately.
  const identity = JSON.stringify(["connected_sessions_list_command", payload,
    backendBase(), isDesktopApp(), globalThis.window?.location?.origin || ""]);
  const pending = listRequests.get(identity);
  if (pending) return pending;
  const request = (async () => {
    set(current => ({ list: { ...current.list, status: current.list.status === "ready" ? "refreshing" : "loading", error: "" } }));
    try {
      const result = await callNx("connected_sessions_list_command", payload);
      if (query !== lastQuery) return;
      const sessions = {};
      for (const session of result?.sessions || []) sessions[session.id] = session;
      const order = sortOrder(sessions);
      // A chat opened directly (a link, or one the list hides) keeps its details while it is open.
      for (const id of Object.keys(state.threads)) if (!sessions[id] && state.sessions[id]) sessions[id] = state.sessions[id];
      set({
        host: result?.host || state.host,
        eventCursor: typeof result?.cursor === "number" ? result.cursor : state.eventCursor || 0,
        sessions,
        order,
        list: { status: "ready", error: "", sources: result?.sources || [], total: result?.total ?? Object.keys(sessions).length },
      });
      // A source that was still starting up gets a couple of quiet retries.
      const slow = (result?.sources || []).some(source => source.available === false && (source.state === "loading" || /in time/i.test(source.reason || "")));
      if (slow && listRetries < 3) { listRetries += 1; setTimeout(() => void loadList(), 3000); }
      else if (!slow) listRetries = 0;
    } catch (error) {
      if (query !== lastQuery) return;
      set(current => ({ list: { ...current.list, status: "error", error: error?.message || "Chats could not be loaded.", code: error?.code || "" } }));
    } finally {
      listRequests.delete(identity);
    }
  })();
  listRequests.set(identity, request);
  return request;
}

export async function openThread(id) {
  if (!id) return;
  const existing = state.threads[id];
  if (existing && existing.status === "ready") {
    // Re-read quietly so a thread opened earlier catches up after a reconnect.
    void refreshThread(id);
    return;
  }
  set({ threads: { ...state.threads, [id]: { status: "loading", error: "", items: [], context: null, hasEarlier: false } } });
  await refreshThread(id);
}

// Live events are newer than any read that started before them. A read that
// comes back late must not roll a finished run back to "running" or a new
// title back to "New conversation", so each session remembers the last
// event applied to it and reads only fill in what events have not covered.
let eventClock = 0;
const touchedAt = new Map();
function touch(id) { eventClock += 1; if (id) touchedAt.set(id, eventClock); }

function mergeItems(read, live) {
  const byId = new Map(read.map(item => [item.id, item]));
  for (const item of live) {
    if (item.optimistic) {
      if (!read.some(other => other.kind === "user" && other.data?.text === item.data?.text)) byId.set(item.id, item);
      continue;
    }
    const known = byId.get(item.id);
    if (!known || item.streaming) byId.set(item.id, item);
  }
  return [...byId.values()].sort((a, b) => Number(a.seq) - Number(b.seq));
}

// The tour plays real chat components on example threads under "tour:" ids: written
// only into threads/runs (never the session list), never read from or sent to the PC.
const FIXTURE = /^tour:/;
export const isFixtureId = id => FIXTURE.test(String(id || ""));
/** Show an example thread (and run) under a "tour:" id, for the tour's real chat scenes. */
export function stageFixture(id, { thread, run = null }) {
  if (!isFixtureId(id)) throw new Error("Example threads use a tour: id");
  set(current => ({
    threads: { ...current.threads, [id]: { status: "ready", error: "", context: null, hasEarlier: false, plan: null, planSeq: null, ...thread } },
    runs: { ...current.runs, [id]: run },
  }));
}
export function clearFixture(id) {
  if (!isFixtureId(id)) return;
  set(current => {
    const threads = { ...current.threads };
    const runs = { ...current.runs };
    delete threads[id];
    delete runs[id];
    return { threads, runs };
  });
}

async function refreshThread(id) {
  if (isFixtureId(id)) return;
  const startedAt = eventClock;
  try {
    const page = await callNx("connected_session_read_command", { id, limit: 160 });
    const stale = (touchedAt.get(id) || 0) > startedAt;
    set(current => ({
      threads: {
        ...current.threads,
        [id]: {
          status: "ready", error: "",
          transportTruncated: stale && Boolean(current.threads[id]?.transportTruncated),
          items: stale ? mergeItems(page?.items || [], current.threads[id]?.items || []) : page?.items || [],
          // Keep the live meter when a read has no usage of its own.
          context: (stale || (page?.context?.used_tokens ?? page?.context?.usedTokens) == null) && current.threads[id]?.context
            ? current.threads[id].context : page?.context || null,
          hasEarlier: Boolean(page?.has_earlier ?? page?.hasEarlier),
          loadingEarlier: false,
          cursor: page?.cursor ?? null,
          // The agent's checklist as the backend folded it; live items after planSeq fold on top (nxPlanModel).
          ...planFromPage(page, current.threads[id]),
        },
      },
      sessions: page?.session && !stale ? { ...current.sessions, [id]: { ...current.sessions[id], ...page.session } } : current.sessions,
      runs: page?.run && !(stale && current.runs[id]) ? { ...current.runs, [id]: page.run } : current.runs,
    }));
    if (stale && state.threads[id]?.transportTruncated) recoverTruncatedThread(id);
  } catch (error) {
    set(current => ({
      threads: { ...current.threads, [id]: { ...(current.threads[id] || { items: [] }), status: "error", error: error?.message || "This chat could not be read.", code: error?.code || "" } },
    }));
  }
}

// A chat another app is running (the Codex app, Claude Code in a terminal) sends
// Neyvia no live events, so while it works the open chat is re-read on a short
// timer. The read passes the adapter's cursor, which returns only what changed.
const followBusy = new Set();
export function isWorkingElsewhere(session, run) {
  if (!session || isRunActive(run)) return false;
  const working = ["working", "waiting_approval", "waiting_input"].includes(session.status);
  return working && session.live_owner !== "neyvia" && ["codex", "claude-code"].includes(session.app);
}

export async function followThread(id) {
  const thread = state.threads[id];
  if (!thread || thread.status !== "ready" || followBusy.has(id)) return;
  followBusy.add(id);
  const startedAt = eventClock;
  try {
    const page = await callNx("connected_session_read_command", { id, limit: 160, ...(thread.cursor ? { cursor: thread.cursor } : {}) });
    if ((touchedAt.get(id) || 0) > startedAt) return;  // a live event got there first; the next round catches up
    set(current => {
      const existing = current.threads[id];
      if (!existing) return {};
      let items = existing.items;
      for (const item of page?.items || []) items = insertItem(items, item);
      const usage = page?.context?.used_tokens ?? page?.context?.usedTokens;
      return {
        threads: { ...current.threads, [id]: { ...existing, items, cursor: page?.cursor ?? existing.cursor, context: usage != null ? page.context : existing.context, ...planFromPage(page, existing) } },
        sessions: page?.session ? { ...current.sessions, [id]: { ...current.sessions[id], ...page.session } } : current.sessions,
      };
    });
  } catch {
    /* the next round tries again */
  } finally {
    followBusy.delete(id);
  }
}

export async function loadEarlier(id) {
  const thread = state.threads[id];
  if (!thread?.hasEarlier || thread.loadingEarlier || !thread.items.length) return;
  withThread(id, () => ({ loadingEarlier: true }));
  try {
    const page = await callNx("connected_session_read_command", { id, beforeSeq: thread.items[0].seq, limit: 160 });
    withThread(id, current => ({
      items: [...(page?.items || []).filter(item => !current.items.some(existing => existing.id === item.id)), ...current.items],
      hasEarlier: Boolean(page?.has_earlier ?? page?.hasEarlier),
      loadingEarlier: false,
    }));
  } catch {
    withThread(id, () => ({ loadingEarlier: false }));
  }
}

const requestIds = new Map();
function requestIdFor(key) {
  if (!requestIds.has(key)) requestIds.set(key, globalThis.crypto?.randomUUID?.() || `nx-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  return requestIds.get(key);
}

export async function sendMessage(id, message, options = {}) {
  // An exact retry reuses its request ID; a changed model, route or image is a new request.
  const key = sendIdentity(id, message, options);
  const requestId = requestIdFor(key);
  const attachments = (options.images || []).map((image, index) => ({
    id: `optimistic-${requestId}-${index}`, kind: "image", label: image.name || "Image", url: `data:${image.mime};base64,${image.data}`,
  }));
  withThread(id, current => ({
    items: insertItem(current.items, {
      // Reserve its position at submission, before the new turn's effects.
      id: `optimistic-${requestId}`, seq: nextMessageSequence(current.items), kind: "user", optimistic: true,
      at: new Date().toISOString(), data: { text: message, attachments },
    }),
  }));
  try {
    const run = await callNx("connected_session_send_command", { id, message, requestId, options });
    requestIds.delete(key);
    set(current => ({ runs: { ...current.runs, [id]: run } }));
    return run;
  } catch (error) {
    withThread(id, current => ({ items: current.items.filter(item => item.id !== `optimistic-${requestId}`) }));
    throw error;
  }
}

/** Compact a chat now; the run shows like any other turn. */
export async function compactSession(sessionId, options = null, instructions = null) {
  const next = await callNx("connected_session_compact_command", { id: sessionId, options, instructions });
  set(current => ({ runs: { ...current.runs, [sessionId]: next } }));
  return next;
}

/** Add a message to the run that is working now (Codex turn/steer, Claude Code's input stream). */
export async function steerRun(sessionId, message, options = {}) {
  const run = state.runs[sessionId];
  if (!run?.runId) throw new Error("Nothing is running in this chat any more. Send your message as a new one.");
  const next = await callNx("connected_session_steer_command", { runId: run.runId, message, options });
  set(current => ({ runs: { ...current.runs, [sessionId]: next } }));
  return next;
}

export async function startSession(app, cwd, message, options = {}) {
  const requestId = requestIdFor(sendIdentity(`new\0${app}\0${cwd}`, message, options));
  return callNx("connected_session_new_command", { app, cwd, message, requestId, options });
}

const sessionWaiters = new Map(); // runId -> resolve, for a new chat whose session id comes after the start
/** The chat a just-started run created; null if it hasn't said within `ms`. */
export function waitForRunSession(runId, ms = 30000) {
  if (!runId) return Promise.resolve(null);
  const known = Object.entries(state.runs).find(([, run]) => run?.runId === runId)?.[0];
  if (known) return Promise.resolve(known);
  return new Promise(resolve => {
    const timer = setTimeout(() => { sessionWaiters.delete(runId); resolve(null); }, ms);
    sessionWaiters.set(runId, id => { clearTimeout(timer); sessionWaiters.delete(runId); resolve(id); });
  });
}

export async function stopRun(sessionId) {
  const run = state.runs[sessionId];
  if (!run?.runId) return;
  const next = await callNx("connected_session_stop_command", { runId: run.runId });
  set(current => ({ runs: { ...current.runs, [sessionId]: next } }));
}

export async function answerRun(sessionId, response) {
  const run = state.runs[sessionId];
  if (!run?.runId || !run.pendingRequest?.requestId) return;
  const next = await callNx("connected_session_answer_command", { runId: run.runId, requestId: run.pendingRequest.requestId, response });
  set(current => ({ runs: { ...current.runs, [sessionId]: next } }));
}

export function markSeen(id) {
  const items = state.threads[id]?.items || [];
  const seq = items.filter(item => !item.optimistic).at(-1)?.seq;
  const session = state.sessions[id];
  if (seq == null || !session?.unread) return;
  set(current => ({ sessions: { ...current.sessions, [id]: { ...current.sessions[id], unread: false } } }));
  void callNx("connected_session_mark_seen_command", { id, seq }).catch(() => {});
}

const recoveryTimers = new Map();
function recoverTruncatedThread(id) {
  if (!state.threads[id] || recoveryTimers.has(id)) return;
  recoveryTimers.set(id, setTimeout(() => {
    recoveryTimers.delete(id);
    void refreshThread(id);
  }, 400));
}

function applyEvent(event) {
  const sid = event.sessionId || event.session?.id;
  touch(sid);
  // The bounded event ring can shorten any field, or omit the item entirely.
  // Never apply that partial payload as if it were the complete provider item.
  if (event.truncated && sid) {
    withThread(sid, () => ({ transportTruncated: true }));
    recoverTruncatedThread(sid);
    return;
  }
  switch (event.type) {
    case "item.added":
    case "item.updated":
      withThread(sid, current => ({ items: insertItem(current.items, event.item) }));
      break;
    case "item.delta":
      withThread(sid, current => {
        const index = current.items.findIndex(item => item.id === event.itemId);
        if (index < 0) return {};
        const item = current.items[index];
        const field = item.kind === "reasoning" ? "summary" : item.kind === "tool" ? "output" : "text";
        const items = current.items.slice();
        items[index] = { ...item, streaming: true, data: { ...item.data, [field]: `${item.data?.[field] || ""}${event.textDelta || ""}` } };
        return { items };
      });
      break;
    case "run.state":
      if (sid && sessionWaiters.has(event.runId)) sessionWaiters.get(event.runId)(sid);
      set(current => ({ runs: { ...current.runs, [sid]: { ...(current.runs[sid] || {}), ...event, state: event.state } } }));
      if (!isRunActive(event)) {
        withThread(sid, current => ({ items: current.items.map(item => (item.streaming ? { ...item, streaming: false } : item)) }));
        // Reconcile once with what the app stored (final text, title, usage).
        if (state.threads[sid]) setTimeout(() => void refreshThread(sid), 400);
      }
      break;
    case "feedback.saved":
      setFeedback(event.runId, { verdict: event.verdict, at: event.at });
      break;
    case "prompt.amplified":
    case "prompt.edited":
    case "prompt.consumed":
      if (sid) set(current => ({ amplify: { ...current.amplify, [sid]: { ...event } } }));
      if (event.type === "prompt.edited" && event.learning) setAmplifyLearning(event.amplificationId, event.learning);
      break;
    case "lesson.state":
      // An edit's lessons run as "prompt:<amplificationId>:<revision>" (plans/15-handoff.md ## C14).
      if (String(event.runId || "").startsWith("prompt:")) {
        const id = String(event.runId).split(":")[1];
        const known = state.amplifyLearning[id] || {};
        setAmplifyLearning(id, event.lessonId
          ? { state: event.state, reason: event.reason || "", lessonIds: [...new Set([...(known.lessonIds || []), event.lessonId])] }
          : { state: "failed", reason: event.reason || event.title || "", lessonIds: known.lessonIds || [] });
      } else if (event.runId) {
        const lessons = { ...(state.feedback[event.runId]?.lessons || {}), [event.lessonId]: { state: event.state, title: event.title || "" } };
        setFeedback(event.runId, { lessons });
      }
      break;
    case "context.updated":
      withThread(sid, () => ({ context: event.context }));
      break;
    case "session.updated": {
      const session = event.session;
      if (!session?.id) break;
      const before = state.sessions[session.id];
      if (state.threads[session.id]?.status === "ready" && before && before.status !== session.status
          && !isRunActive(state.runs[session.id])) {
        setTimeout(() => void refreshThread(session.id), 300);
      }
      set(current => {
        const sessions = { ...current.sessions, [session.id]: { ...current.sessions[session.id], ...session } };
        // Chats the list hides (Neyvia's own test runs) stay out of the sidebar even while open.
        const listed = Object.fromEntries(Object.entries(sessions).filter(([id, row]) => current.order.includes(id) || row.origin !== "neyvia-harness"));
        return { sessions, order: sortOrder(listed) };
      });
      break;
    }
    case "resync":
      void loadList();
      for (const id of Object.keys(state.threads)) void refreshThread(id);
      break;
    default:
      break;
  }
}

/** After-task feedback (plan 20 C9): merge what the backend saved or reported for one run. */
export function setFeedback(runId, patch) {
  if (!runId) return;
  set(current => ({ feedback: { ...current.feedback, [runId]: { ...(current.feedback[runId] || {}), ...patch } } }));
}

/** Where an edit of an amplified prompt went (plan 20 C14). */
export function setAmplifyLearning(id, learning) {
  if (!id || !learning) return;
  set(current => ({ amplifyLearning: { ...current.amplifyLearning, [id]: { ...(current.amplifyLearning[id] || {}), ...learning } } }));
}

let unsubscribe = null;
/** Subscribe after the first list load, from the cursor that list reported. */
export function startLive() {
  if (unsubscribe) return unsubscribe;
  unsubscribe = subscribeEvents({
    cursor: state.eventCursor || 0,
    onEvent: applyEvent,
    onState: connection => {
      const wasDown = state.connection === "reconnecting" || state.connection === "offline";
      set({ connection });
      // After an outage, re-read what the user is looking at.
      if (connection === "live" && wasDown) applyEvent({ type: "resync" });
    },
  });
  return () => { unsubscribe?.(); unsubscribe = null; };
}
