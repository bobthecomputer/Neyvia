import { useMemo, useSyncExternalStore } from "react";

import { backendBase } from "./nxApi.js";
import { getOs, subscribeOs } from "./nxOsStore.js";

// Comments on anything (plan 29 B). The backend keeps them per target in
// `.agent_control/comments.sqlite3` (append-only events; the current view is
// derived) and serves them at /api/ui/comments (plans/logs/COMMENTS-contract.md):
//
//   GET  /api/ui/comments?target=&status=      -> { comments: [...], total }
//   POST /api/ui/comments {op: add|edit|resolve|reopen|delete|send, ...}
//
// This module is the browser side: one store of the comments the screen has
// read, the calls that change them, and per-window UI state (comment mode, the
// list, the comment being edited). Comments change for every viewer: the
// `comments.changed` bus event refetches the target it names.

const useFixtures = import.meta.env?.DEV === true && new URLSearchParams(globalThis.location?.search || "").get("fixtures") === "1";

function base() {
  const source = globalThis.window?.__NEYVIA_UI_SOURCE__;
  return backendBase() || (typeof source === "string" && source.startsWith("http") ? source : "");
}

async function fixture() { return import("./nxCommentsFixture.js"); }

async function request(path, init) {
  let response;
  try { response = await fetch(`${base()}${path}`, { credentials: "include", ...init }); } catch { throw new Error("The PC service can't be reached."); }
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result?.ok === false) throw Object.assign(new Error(result?.error || `Comments failed (HTTP ${response.status})`), { status: response.status });
  return result?.data ?? result;
}

export async function readComments({ target = "", status = "all" } = {}) {
  if (useFixtures) return (await fixture()).read({ target, status });
  const query = new URLSearchParams({ status });
  if (target) query.set("target", target);
  return request(`/api/ui/comments?${query}`);
}

async function write(body) {
  if (useFixtures) return (await fixture()).write(body);
  return request("/api/ui/comments", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

// ---- the store ------------------------------------------------------------------------------------

let state = { byId: {}, loaded: {}, ui: {} }; // loaded: target -> "loading" | "ready" | "error"; ui: window id -> { mode, list, active, draft }
const listeners = new Set();
const set = patch => { state = { ...state, ...(typeof patch === "function" ? patch(state) : patch) }; for (const listener of listeners) listener(); };
const subscribe = listener => { listeners.add(listener); return () => listeners.delete(listener); };
export const getComments = () => state;

function useComments(selector) {
  return useSyncExternalStore(subscribe, () => selector(state));
}

const live = comment => comment && comment.status !== "deleted" && !comment.deleted;

function upsert(comments) {
  if (!comments.length) return;
  set(current => {
    const byId = { ...current.byId };
    for (const comment of comments) {
      if (!comment?.id) continue;
      // A newer revision wins; a stale read never overwrites a change made here.
      const known = byId[comment.id];
      if (!known || (comment.revision ?? 0) >= (known.revision ?? 0)) byId[comment.id] = comment;
    }
    return { byId };
  });
}

const inflight = new Map();
/** Read one target's comments (all statuses). Concurrent reads of a target share one request. */
export function loadTarget(target, { force = false } = {}) {
  if (!target) return Promise.resolve();
  if (!force && state.loaded[target] === "ready") return Promise.resolve();
  if (inflight.has(target)) return inflight.get(target);
  if (state.loaded[target] !== "ready") set(current => ({ loaded: { ...current.loaded, [target]: "loading" } }));
  const run = readComments({ target }).then(result => {
    const comments = result?.comments || [];
    set(current => {
      // The target's rows are replaced by what the PC says now (a deleted comment disappears). A comment made here a moment ago
      // stays until the PC lists it: a read that raced its write must not make it vanish.
      const fresh = Date.now() - 15000;
      const listed = new Set(comments.map(comment => comment.id));
      const byId = Object.fromEntries(Object.entries(current.byId).filter(([id, comment]) => comment.target !== target || (!listed.has(id) && comment.__madeAt > fresh)));
      for (const comment of comments) byId[comment.id] = comment;
      return { byId, loaded: { ...current.loaded, [target]: "ready" } };
    });
  }).catch(error => {
    set(current => ({ loaded: { ...current.loaded, [target]: current.loaded[target] === "ready" ? "ready" : "error" }, errors: { ...(current.errors || {}), [target]: error.message } }));
  }).finally(() => inflight.delete(target));
  inflight.set(target, run);
  return run;
}

/** Every open comment in the workspace (the other apps' too): the list offers sending them along. */
export async function loadAllOpen() {
  try { upsert((await readComments({ status: "open" }))?.comments || []); } catch { /* the list still works for this window */ }
}

export const ensureTargets = targets => Promise.all([...new Set(targets)].map(target => loadTarget(target)));

/** The comments of these targets, oldest marker number first, with the read state of each. */
export function useTargetComments(targets) {
  const key = [...targets].sort().join("\n");
  const byId = useComments(current => current.byId);
  const loaded = useComments(current => current.loaded);
  return useMemo(() => {
    const wanted = new Set(key ? key.split("\n") : []);
    const comments = Object.values(byId).filter(comment => wanted.has(comment.target) && live(comment))
      .sort((a, b) => String(a.target).localeCompare(String(b.target)) || (a.number ?? 0) - (b.number ?? 0));
    const loading = [...wanted].some(target => loaded[target] !== "ready" && loaded[target] !== "error");
    return { comments, loading, failed: [...wanted].some(target => loaded[target] === "error") };
  }, [key, byId, loaded]);
}

/** Open comments on targets other than these (comments pinned in other apps). */
export function useOpenElsewhere(targets) {
  const key = [...targets].sort().join("\n");
  const byId = useComments(current => current.byId);
  return useMemo(() => {
    const here = new Set(key ? key.split("\n") : []);
    return Object.values(byId).filter(comment => live(comment) && comment.status === "open" && !here.has(comment.target))
      .sort((a, b) => String(a.target).localeCompare(String(b.target)) || (a.number ?? 0) - (b.number ?? 0));
  }, [key, byId]);
}

// ---- changes ---------------------------------------------------------------------------------------

const author = "you";

export async function addComment({ target, targetKind, anchor, text }) {
  const result = await write({ op: "add", target, targetKind, anchor, text: String(text).trim(), author });
  upsert([{ ...result.comment, __madeAt: Date.now() }]);
  // The PC's bus event can reach us before its own read shows the comment: look again once it has settled.
  setTimeout(() => { if (state.loaded[target]) void loadTarget(target, { force: true }); }, 1500);
  return result.comment;
}

export async function editComment(comment, patch) {
  const result = await write({ op: "edit", id: comment.id, ...patch, expectedRevision: comment.revision });
  upsert([result.comment]);
  return result.comment;
}

async function transition(op, comment) {
  const result = await write({ op, id: comment.id, expectedRevision: comment.revision });
  upsert([result.comment]);
  return result.comment;
}
export const resolveComment = comment => transition("resolve", comment);
export const reopenComment = comment => transition("reopen", comment);

export async function deleteComment(comment) {
  await write({ op: "delete", id: comment.id, expectedRevision: comment.revision });
  set(current => { const byId = { ...current.byId }; delete byId[comment.id]; return { byId }; });
}

const requestId = () => `comments-send-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`}`;

/**
 * Send comments to a chat as one message. `ids` are the comments (open ones are sent), `destination` is
 * { sessionId } for a chat, { runId } for a live turn or { newSession: {app, cwd, model, effort, transport} }.
 * The backend composes the message with each comment's anchor and answers with the delivery receipt.
 */
export async function sendComments({ ids, target = "", destination }) {
  const body = { op: "send", requestId: requestId(), ...destination };
  if (ids?.length) body.ids = ids; else if (target) body.target = target;
  const receipt = await write(body);
  const stamp = receipt.delivery ? { ...receipt.delivery, messageId: receipt.messageId, channel: receipt.channel, sessionId: receipt.sessionId, runId: receipt.runId } : { messageId: receipt.messageId, channel: receipt.channel, sessionId: receipt.sessionId };
  set(current => {
    const byId = { ...current.byId };
    for (const id of receipt.commentIds || ids || []) if (byId[id]) byId[id] = { ...byId[id], delivery: byId[id].delivery || stamp };
    return { byId };
  });
  return receipt;
}

// ---- the bus: another viewer or an agent changed a comment -------------------------------------------

let busSeq = 0;
let refetchTimer = 0;
const dirty = new Set();
function onBus() {
  const signal = getOs().appSignals?.comments;
  if (!signal || signal.seq <= busSeq) return;
  busSeq = signal.seq;
  const target = signal.payload?.target;
  if (target) dirty.add(target); else for (const known of Object.keys(state.loaded)) dirty.add(known);
  clearTimeout(refetchTimer);
  refetchTimer = setTimeout(() => { for (const next of dirty) if (state.loaded[next]) void loadTarget(next, { force: true }); dirty.clear(); }, 120);
}
let busStarted = false;
export function startCommentsBus() {
  if (busStarted) return;
  busStarted = true;
  busSeq = getOs().appSignals?.comments?.seq || 0;
  subscribeOs(onBus);
}

// ---- per-window UI state ---------------------------------------------------------------------------------

const EMPTY_UI = Object.freeze({ mode: false, list: false, active: null, draft: null });
export const uiOf = (windowId, snapshot = state) => snapshot.ui[windowId] || EMPTY_UI;
export function useCommentUi(windowId) { return useComments(current => uiOf(windowId, current)); }
export function setCommentUi(windowId, patch) {
  set(current => ({ ui: { ...current.ui, [windowId]: { ...uiOf(windowId, current), ...(typeof patch === "function" ? patch(uiOf(windowId, current)) : patch) } } }));
}

/** Header numbers for a window: which targets it shows and how many open comments they hold. */
export function reportTargets(windowId, targets) {
  const same = state.windowTargets?.[windowId];
  if (same && same.join("\n") === targets.join("\n")) return;
  set(current => ({ windowTargets: { ...(current.windowTargets || {}), [windowId]: targets } }));
}
/** Header numbers for a window: open comments, unsent ones, and every comment there is. */
export function useWindowCounts(windowId) {
  const byId = useComments(current => current.byId);
  const targets = useComments(current => current.windowTargets?.[windowId]);
  return useMemo(() => {
    const wanted = new Set(targets || []);
    const mine = Object.values(byId).filter(comment => wanted.has(comment.target) && live(comment));
    const open = mine.filter(comment => comment.status === "open");
    return { open: open.length, unsent: open.filter(comment => !comment.delivery?.sentAt).length, total: mine.length };
  }, [byId, targets]);
}
export const useWindowOpenCount = windowId => useWindowCounts(windowId).open;

export const windowTargetsOf = windowId => state.windowTargets?.[windowId] || [];

/** Open comments on a window's targets (the unsent ones only, when `unsent`): what the pop-out's context block and Send all take. */
export function openCommentsFor(windowId, { unsent = false } = {}) {
  const wanted = new Set(windowTargetsOf(windowId));
  return Object.values(state.byId).filter(comment => wanted.has(comment.target) && live(comment) && comment.status === "open" && !(unsent && comment.delivery?.sentAt))
    .sort((a, b) => String(a.target).localeCompare(String(b.target)) || (a.number ?? 0) - (b.number ?? 0));
}

// The window the last pointer press or focus was in: the C key and Ctrl+Shift+Space act on it.
let focusedWindow = "";
export const focusedWindowId = () => focusedWindow;
export function trackFocusedWindow() {
  const note = event => { const id = event.target?.closest?.("[data-window]")?.getAttribute("data-window"); if (id) focusedWindow = id; };
  document.addEventListener("pointerdown", note, true);
  document.addEventListener("focusin", note, true);
  return () => { document.removeEventListener("pointerdown", note, true); document.removeEventListener("focusin", note, true); };
}

// Development only: lets the design harness reload what the screen shows after a fixture agent changed a comment.
if (import.meta.env?.DEV && globalThis.window) globalThis.window.__nxComments = { get state() { return state; }, reload: () => Promise.all(Object.keys(state.loaded).map(target => loadTarget(target, { force: true }))) };
