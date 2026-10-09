import { backendBase } from "./nxApi.js";
import { applyUiAction, os, seedFromSnapshot } from "./nxOsStore.js";
import { shellDelivered, shellReady } from './nxShellObserve.js';

// Command bus client (11-tonight contract).
//   backend -> UI: SSE GET /api/ui/events, messages { id, ts, action, payload }
//   UI -> backend: POST /api/ui/ack { id, ok, error?, clientId }
// Every message is applied once (ids are increasing integers as strings) and
// acknowledged with the outcome, so a model's neyvia.* tool call can learn
// whether the UI really reacted. The cursor is remembered per browser; events
// emitted while this page was closed are replayed quietly: their state
// changes apply, their moments (toasts, opening a pane) are skipped and not
// acknowledged, because nobody saw them.
// `?bus=mock` under `vite dev` swaps the backend for a local emitter;
// `?bus=off` disables the bus.

const params = new URLSearchParams(globalThis.location?.search || "");
const mode = import.meta.env.DEV && params.get("bus") === "mock" ? "mock" : params.get("bus") === "off" ? "off" : "live";
const MOMENTS = new Set(["notify", "pane.show", "session.created", "view.layout", "view.place", "notes.open", "onboarding.open", "devices.pair_request",
  // voice control (plan 15 T3): moments too, never replayed after a reconnect
  "app.open", "stage.close", "launcher.open", "dashboard.open", "session.open", "newchat.open", "composer.send", "sidebar.toggle", "dictation.start", "voice.help",
  // Settings > Re-enter setup (T11): opening setup is a moment too
  "setup.open", "image.open", "image.edited"]);
const REPLAY_SLACK_MS = 3000;
const bootAt = Date.now();
const clientId = (() => {
  try {
    const saved = sessionStorage.getItem("nx.bus.client");
    if (saved) return saved;
    const made = `ui-${Math.random().toString(36).slice(2, 10)}`;
    sessionStorage.setItem("nx.bus.client", made);
    return made;
  } catch { return "ui"; }
})();
const CURSOR_KEY = `nx.bus.cursor.${mode}`;

function base() {
  const source = globalThis.window?.__NEYVIA_UI_SOURCE__;
  return backendBase() || (typeof source === "string" && source.startsWith("http") ? source : "");
}

/** This page's bus client id (voice commands send it as context). */
export const busClientId = () => clientId;

let lastId = mode === "live" ? Number(readCursor()) || 0 : 0;
let mock = null; // { ack, callTool } while the mock backend runs

function readCursor() { try { return localStorage.getItem(CURSOR_KEY); } catch { return null; } }
function saveCursor(id) { try { localStorage.setItem(CURSOR_KEY, String(id)); } catch { /* best effort */ } }

async function post(path, body) {
  const response = await fetch(`${base()}${path}`, {
    method: "POST", credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result?.ok === false) {
    // Keep the backend's answer: a refused tool call carries its approvalId there.
    throw Object.assign(new Error(result?.error || `HTTP ${response.status}`), { status: response.status, data: result?.data ?? null });
  }
  return result?.data ?? result;
}

/** Grant a pending neyvia.* approval. The person asked for it by pressing Approve. */
export function approveUiRequest(approvalId) {
  if (mock) return Promise.resolve({ approved: true, id: approvalId });
  return post("/api/ui/approve", { id: approvalId });
}

function ack(message) {
  if (mock) { mock.ack(message); return; }
  void post("/api/ui/ack", { ...message, clientId }).catch(() => { /* an unacknowledged event stays visible to the backend */ });
}

/**
 * A mounted pane's own report for the pane.show event that opened it (FIXCL renderer contract):
 * {id, ok, clientId, observation} or {id, ok:false, error}. Resolves with the backend's answer;
 * a refused report (wrong pane, runtime or content) rejects with the backend's reason.
 */
export function ackPane(body) {
  if (mock) { mock.ack(body); return Promise.resolve({ id: body.id, ok: body.ok }); }
  if (mode === "off") return Promise.resolve(null);
  return post("/api/ui/ack", { ...body, clientId });
}

const timerListeners = new Set();
export function subscribeTimers(listener) {
  timerListeners.add(listener);
  return () => timerListeners.delete(listener);
}
export const ackTimer = body => post("/api/ui/ack", { ...body, clientId });

// pane.show events that ask for a renderer observation are acknowledged by the pane once it
// shows real content (NxPaneObserver.jsx), never here on delivery.
const observedByPane = message => message?.action === "pane.show" && message?.payload?.observationRequired === true;

export function isReplay(message, now = bootAt) {
  const ts = Date.parse(message?.ts || "");
  return Number.isFinite(ts) && ts < now - REPLAY_SLACK_MS;
}

// Ids applied on this page, from the stream or from a direct receipt (a voice command's answer
// carries its events), so neither path applies one twice. The stream's resume cursor (lastId)
// moves only with the stream: a direct receipt for event 100 must not make the stream skip 96-99.
const applied = new Set();
function remember(id) {
  applied.add(id);
  if (applied.size > 500) applied.delete(applied.values().next().value);
}
// Actions aimed at one window (the one Paul spoke to): other windows leave them alone, unacknowledged.
const TARGETED = new Set(["composer.send", "dictation.start"]);
const elsewhere = message => Boolean(message?.payload?.clientId) && message.payload.clientId !== clientId;

/**
 * Apply one bus message and acknowledge it. Exported for the mock and tests.
 * `direct`: it came in an HTTP answer, not the stream (applied once, cursor untouched).
 */
export function deliver(message, { direct = false } = {}) {
  const id = String(message?.id ?? "");
  const numeric = Number(message?.id);
  if (direct) {
    if (!id || applied.has(id) || (Number.isFinite(numeric) && numeric <= lastId)) return null; // the stream got it first
  } else if (Number.isFinite(numeric)) {
    if (numeric <= lastId) return null; // already applied (reconnect replay)
    lastId = numeric;
    if (mode === "live") saveCursor(numeric);
    if (applied.has(id)) return null; // a direct receipt applied (and acknowledged) it already
  }
  if (TARGETED.has(message?.action) && elsewhere(message)) return null;
  // A new chat opened by voice in another window shows here too, but only the speaker's window records.
  const payload = message?.action === "newchat.open" && elsewhere(message) ? { ...message.payload, dictate: false } : message?.payload || {};
  const replay = !direct && isReplay(message);
  if (replay && (MOMENTS.has(message?.action) || /^(pdf|mobile)\./.test(String(message?.action)))) return null;
  if (id) remember(id);
  if (message?.action === 'renderer.probe') {
    if (replay || elsewhere(message)) return null;
    const result = { id, ok: shellReady(payload.runtimeId) };
    ack(result);
    return result; // control packet: never changes state or records an effect
  }
  if (message?.action === 'timer.changed') {
    // The timer component ACKs after its committed DOM, never on delivery.
    if (!replay) for (const listener of timerListeners) listener(message);
    return null;
  }
  let result;
  try {
    if (!message?.action) throw new Error("message.action is required");
    applyUiAction(message.action, payload, id, { quiet: replay });
    if (!replay) shellDelivered(message);
    result = { id, ok: true };
  } catch (error) {
    result = { id, ok: false, error: error?.message || String(error) };
  }
  if (!replay && !(result.ok && observedByPane(message))) ack(result);
  return result;
}

/** Call a neyvia.* tool as the user (sidebar pin/archive/move/rename). */
export async function callTool(tool, args) {
  if (mock) return mock.callTool(tool, args);
  if (mode === "off") throw new Error("The command bus is off");
  const result = await post("/api/ui/tools/call", { tool, arguments: args });
  if (result?.ok === false) throw Object.assign(new Error(result.error || result.reason || "The action was refused"), { data: result });
  return result;
}

/** The user's own session actions: shown at once, then made durable through the backend. */
export async function sessionsAction(ids, verb, args, patch) {
  const accepted = [];
  const failures = [];
  for (const id of ids) {
    try {
      await callTool(`neyvia.session.${verb}`, { id, ...args });
      os.patchMany([id], patch);
      accepted.push(id);
    } catch (error) { failures.push(error?.message || "refused"); }
  }
  if (failures.length) {
    os.notify({ level: "warning", message: `${failures.length} kept: ${failures[0]}` });
  }
  return accepted;
}

export const sessionAction = (id, verb, args, patch) => sessionsAction([id], verb, args, patch);

/** Archive (or restore) with an undo toast. */
export async function archiveSessions(ids, message) {
  if (!ids.length) return;
  const accepted = await sessionsAction(ids, "archive", { archived: true }, { archived: true });
  if (accepted.length) os.notify({ level: "success", message: accepted.length === ids.length ? message : `Archived ${accepted.length} chats`,
    undo: { ids: accepted, verb: "archive", args: { archived: false }, patch: { archived: false } } });
}

// What an app's user side shows right now (page, selection…), for its bot
// side. Proposed route: POST /api/ui/app-state { app, state, clientId }.
// A backend without it answers 404 once and is not asked again.
const appStatePending = new Map();
const appStateFlights = new Set();
let appStateUnsupported = false;
export function reportAppState(app, state) {
  if (mock) { mock.appState[app] = state; return; }
  if (appStateUnsupported || mode === "off") return;
  appStatePending.set(app, state);
  if (appStateFlights.has(app)) return;
  appStateFlights.add(app);
  void (async () => {
    try {
      while (appStatePending.has(app) && !appStateUnsupported && mode !== "off") {
        const latest = appStatePending.get(app);
        appStatePending.delete(app);
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 8000);
        try {
          const response = await fetch(`${base()}/api/ui/app-state`, {
            method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ app, state: latest, clientId }), signal: controller.signal,
          });
          if (response.status === 404) appStateUnsupported = true;
          if (!response.ok) break;
        } catch { break; /* offline: the next observation retries */ }
        finally { clearTimeout(timeout); }
      }
    } finally { appStateFlights.delete(app); }
  })();
}

async function getJson(path) {
  try {
    const response = await fetch(`${base()}${path}`, { credentials: "include" });
    if (!response.ok) return null;
    const result = await response.json();
    return result?.data ?? result;
  } catch { return null; }
}

/** Durable state first (bus snapshot, Night Shift board), then the live stream. */
async function loadSnapshot() {
  const [snapshot, board] = await Promise.all([getJson("/api/ui/state"), getJson("/api/nightshift/tasks")]);
  seedFromSnapshot({ ...(snapshot || {}), nightshift: Array.isArray(board) ? board : board?.tasks });
  // Canonical Settings (T11): theme, density, local-only and the rest come from the PC service.
  await import("./nxSettingsApi.js").then(module => module.startSettings()).catch(() => {});
}

function openLive() {
  let source = null;
  let timer = 0;
  let retry = 0;
  let closed = false;
  let pollTimer = 0;
  let pollFlight = null;
  const reconcile = async () => {
    if (closed) return;
    pollFlight = new AbortController();
    const deadline = setTimeout(() => pollFlight?.abort(), 12000);
    try {
      const response = await fetch(`${base()}/api/ui/events?poll=1&cursor=${lastId}`, {
        credentials: "include", signal: pollFlight.signal,
      });
      if (!response.ok) throw new Error(`Bus reconciliation failed (${response.status})`);
      const result = await response.json();
      for (const event of result?.data?.events || []) deliver(event);
    } catch { /* Existing stream and reconnect state remain authoritative. */ }
    finally {
      clearTimeout(deadline);
      pollFlight = null;
      if (!closed) pollTimer = setTimeout(reconcile, 1000);
    }
  };
  const connect = () => {
    if (closed) return;
    os.setBus({ state: retry ? "reconnecting" : "connecting", source: "live" });
    source = new EventSource(`${base()}/api/ui/events?cursor=${lastId}`, { withCredentials: true });
    source.onopen = () => { retry = 0; os.setBus({ state: "live" }); };
    const onFrame = frame => {
      try { deliver(JSON.parse(frame.data)); } catch { /* malformed frame: skipped, never acked as ok */ }
    };
    source.onmessage = onFrame;
    source.addEventListener("ui", onFrame);
    source.onerror = () => {
      source?.close();
      source = null;
      if (closed) return;
      os.setBus({ state: retry > 2 ? "offline" : "reconnecting" });
      timer = setTimeout(connect, Math.min(20000, 800 * 2 ** retry++));
    };
  };
  void loadSnapshot().finally(() => { if (!closed) { connect(); void reconcile(); } });
  return () => { closed = true; clearTimeout(timer); clearTimeout(pollTimer); pollFlight?.abort(); source?.close(); };
}

let stop = null;
export function startBus() {
  if (stop) return stop;
  if (mode === "off" || (mode === "live" && typeof EventSource === "undefined")) {
    os.setBus({ state: "off", source: "none" });
    stop = () => {};
  } else if (import.meta.env.DEV && mode === "mock") {
    os.setBus({ state: "live", source: "mock" });
    let cancel = () => {};
    void import("./nxBusMock.js").then(({ startMock }) => {
      const started = startMock({ deliver });
      mock = started;
      cancel = started.stop;
    });
    stop = () => { cancel(); mock = null; };
  } else {
    stop = openLive();
  }
  return () => { stop?.(); stop = null; };
}

// ---- missions (orchestration) over the UI API, owner session required ----

/** Missions with their task trees; null when the backend can't be reached. */
export function listMissions() {
  return getJson("/api/ui/missions");
}

/** create | control. A start that needs the owner's approval answers { status: "approval_required", approvalId }. */
export function missionRequest(operation, body) {
  return post("/api/ui/missions", { operation, ...body });
}
