import { useEffect, useState, useSyncExternalStore } from "react";
import { invoke } from "@tauri-apps/api/core";

import { NxError, backendBase, callNx, isDesktopApp } from "./nxApi.js";
import { layoutPlan, presenceOf } from "./nxBrowserModel.js";
import { listRuns } from "./agentview/nxAgentViewApi.js";

// The integrated browser's user side (plans/15-handoff.md "## T20"): one
// shared state for Paul and agents, read from the PC service and changed only
// through its ops. The bot side (neyvia.browser.*) works on the same state.
//   browser_call_command {op, args}  (web: POST /api/backend, desktop: the bridge)
// Native work (opening a visible tab, observing it) is queued: the answer has an
// actionId, and the real effect arrives later through state / action.get.

/** One browser op. Errors carry the backend's own words and code. */
export async function browserCall(op, args = {}) {
  try {
    let result;
    if (isDesktopApp()) result = await callNx("browser_call_command", { op, args });
    else {
      // The owner-authenticated browser endpoint carries renderer authority.
      // Generic command dispatch intentionally has no owner capability.
      const response = await fetch(`${backendBase()}/api/ui/browser`, {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ op, args }),
      });
      result = await response.json();
      if (!response.ok) throw new NxError(result.error?.message || "The browser refused that", { code: result.error?.code, status: response.status, data: result });
    }
    if (result?.ok === false) throw new NxError(result.error?.message || result.message || "The browser refused that", { code: result.error?.code || result.code, data: result });
    return result;
  } catch (error) {
    const detail = error?.data?.error;
    if (detail && typeof detail === "object") throw new NxError(detail.message || error.message, { code: detail.code || error.code, status: error.status, data: error.data });
    if (typeof error === "string") {
      const offline = /error sending request|connection refused|os error 10061/i.test(error);
      throw new NxError(offline ? "The PC service can't be reached. Try again when it is connected." : error,
        { code: offline ? "network" : "", data: error });
    }
    throw error;
  }
}

/** Wait for a queued native operation's real outcome (never replays it). */
export async function waitAction(actionId, { timeoutMs = 30000, every = 250 } = {}) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    const row = await browserCall("action.get", { actionId });
    if (row.status === "done") return row;
    if (row.status === "failed") throw new NxError(typeof row.error === "string" ? row.error : row.error?.message || "The page didn't do it", { code: row.error?.code || "action_failed", data: row });
    await new Promise(resolve => setTimeout(resolve, every));
  }
  throw new NxError("The page hasn't answered yet. Its state shows what really happened.", { code: "action_timeout" });
}

/**
 * Fresh DOM projection of a tab (what the agent reads). Headless tabs answer at
 * once; visible tabs answer through the native runtime.
 */
export async function observeTab(tab) {
  const result = await browserCall("observe", { tabId: tab.id });
  if (!result.actionId) return result;
  const row = await waitAction(result.actionId, { timeoutMs: 15000 });
  return row.result?.observation || browserCall("observe", { tabId: tab.id, cached: true });
}

/** Fresh article text, acknowledged by the native observer at its actual document revision. */
export async function readTab(tab) {
  const result = await browserCall("reader", { tabId: tab.id });
  if (!result.actionId) return result.reader || result;
  const row = await waitAction(result.actionId, { timeoutMs: 15000 });
  if (!row.result?.reader) throw new NxError("This page didn't return readable text. Show the page and try Reader again.", { code: "reader_unavailable", data: row });
  return row.result.reader;
}

// ---------------------------------------------------------------- the shared state

let snapshot = { status: "loading", state: null, error: "" };
const listeners = new Set();
let timer = 0;
let inflight = null;
let users = 0;

function publish(next) {
  snapshot = next;
  for (const listener of listeners) listener();
}

/** Something is moving: poll quickly until it settles. */
function busy(state) {
  return Boolean(state?.tabs?.some(tab => tab.loading || ["queued", "promoting"].includes(tab.status))) || pending.size > 0;
}

export async function refreshBrowser() {
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      const state = await browserCall("state");
      publish({ status: "ready", state, error: "" });
      flushLayout();
    } catch (error) {
      publish({ ...snapshot, status: snapshot.state ? "ready" : "error", error: error.message, code: error.code });
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

function schedule() {
  clearTimeout(timer);
  if (!users) return;
  const fast = busy(snapshot.state) || followers > 0;
  timer = setTimeout(async () => {
    if (!document.hidden) await refreshBrowser();
    schedule();
  }, fast ? 700 : 2500);
}

function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The shared browser state; polls while any screen shows it. */
export function useBrowser() {
  useEffect(() => {
    users += 1;
    void refreshBrowser().then(schedule);
    return () => { users -= 1; if (!users) clearTimeout(timer); };
  }, []);
  return useSyncExternalStore(subscribe, () => snapshot);
}

// A view that follows an agent closely (the live agent view) asks for quick polls.
let followers = 0;
export function useFastPoll(active) {
  useEffect(() => {
    if (!active) return undefined;
    followers += 1;
    schedule();
    return () => { followers -= 1; };
  }, [active]);
}

/** Wait (at most 20 s) until a visible tab is live and done loading. */
export async function settled(tabId, timeoutMs = 20000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    const state = await browserCall("state");
    const tab = state.tabs?.find(row => row.id === tabId);
    if (!tab) throw new NxError("The tab was closed.", { code: "unknown_tab" });
    if (tab.live && !tab.loading && tab.engine !== "obscura") return tab;
    await new Promise(resolve => setTimeout(resolve, 300));
  }
  throw new NxError("The page is still loading. Let the agent act from the tab once it has.", { code: "still_loading" });
}

const pending = new Set();
/** Run an op; queued native work is followed until it lands, then state refreshes. */
export async function act(op, args = {}, { wait = false } = {}) {
  const result = await browserCall(op, args);
  if (result?.actionId) {
    pending.add(result.actionId);
    schedule();
    const settle = waitAction(result.actionId).finally(() => { pending.delete(result.actionId); void refreshBrowser(); });
    if (wait) return settle;
    settle.catch(() => {});
  }
  if (result?.revision != null && Array.isArray(result.tabs)) publish({ status: "ready", state: result, error: "" });
  else void refreshBrowser();
  flushLayout();
  return result;
}

// ---------------------------------------------------------------- native runtime (desktop app)

let attaching = null;

/** Where the native runtime reaches the PC service (loopback only). */
function runtimeBase() {
  const configured = backendBase();
  if (/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(configured)) return configured;
  const here = globalThis.location;
  if (here?.protocol === "http:" && /^(127\.0\.0\.1|localhost)$/.test(here.hostname)) return here.origin;
  return "";
}

/**
 * In the desktop app, attach the WebView2 runtime that draws visible tabs
 * (runtime.connect, then browser_runtime_start with the memory-only grant).
 * Elsewhere (a browser, a phone) pages can't be embedded; the UI says so.
 */
export function attachRuntime() {
  if (!isDesktopApp()) return Promise.resolve({ attached: false, reason: "web" });
  if (snapshot.state?.runtime?.connected) return Promise.resolve({ attached: true });
  if (attaching) return attaching;
  attaching = (async () => {
    const start = async () => {
      const grant = await browserCall("runtime.connect");
      const baseUrl = grant.baseUrl || runtimeBase();
      if (!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(baseUrl)) throw new NxError("The PC service must supply its explicit local address and port before pages can be drawn here.", { code: "runtime_base" });
      return invoke("browser_runtime_start", { baseUrl, token: grant.token });
    };
    try {
      await start();
    } catch (error) {
      // The window kept an older runtime (the service restarted): stop it and attach again.
      if (!/previous browser runtime/i.test(String(error?.message || error))) throw error;
      await invoke("browser_runtime_stop");
      await start();
    }
    await refreshBrowser();
    return { attached: true };
  })().finally(() => { attaching = null; });
  return attaching;
}

// ---------------------------------------------------------------- native layout

// Each screen that shows a page registers a slot: where on screen that tab goes.
// Native views draw above the interface, so an overlay (command bar, menu) covers them.
const slots = new Map();
let covers = 0;
let lastSent = "";
let layoutTimer = 0;

export function setSlot(key, slot) {
  if (slot) slots.set(key, slot); else slots.delete(key);
  flushLayout();
}

export function coverNative(on) {
  covers = Math.max(0, covers + (on ? 1 : -1));
  flushLayout(true);
}

export function flushLayout(now = false) {
  if (!isDesktopApp() || !snapshot.state?.runtime?.connected) return;
  clearTimeout(layoutTimer);
  layoutTimer = setTimeout(() => {
    const plan = layoutPlan(snapshot.state.tabs, [...slots.values()], covers > 0);
    const key = JSON.stringify(plan);
    if (!plan.length || key === lastSent) return;
    lastSent = key;
    browserCall("layout", { tabs: plan }).catch(() => { lastSent = ""; });
  }, now ? 0 : 60);
}

// ---------------------------------------------------------------- picture in picture

let pip = null;
const pipListeners = new Set();
export function setPip(tabId) {
  pip = tabId || null;
  for (const listener of pipListeners) listener();
}
export function usePip() {
  return useSyncExternalStore(listener => { pipListeners.add(listener); return () => pipListeners.delete(listener); }, () => pip);
}

// ---------------------------------------------------------------- the agent's page, at the pane's size

/** Make a headless tab's page the size of the area that shows it, so its frame is the page at 1:1. */
export function sizeAgentPage(tabId, { width, height, scale }) {
  return browserCall("viewport", { tabId, width, height, scale });
}

/**
 * Who is driving a headless tab and what it is about to touch (the agent
 * view's run for that tab), polled while the tab is on screen. null: nobody
 * known, or the tab is not a headless one.
 */
export function useAgentPresence(tab, every = 1000) {
  const [presence, setPresence] = useState(null);
  const id = tab?.engine === "obscura" ? tab.id : "";
  useEffect(() => {
    setPresence(null);
    if (!id) return undefined;
    let live = true, timer = 0;
    const read = async () => {
      try {
        const { runs } = await listRuns();
        if (live) setPresence(presenceOf(runs, { id }));
      } catch { /* the pill still works from the tab's own state */ }
      if (live) timer = setTimeout(read, document.hidden ? 4000 : every);
    };
    void read();
    return () => { live = false; clearTimeout(timer); };
  }, [id, every]);
  return presence;
}

/** Every agent run the agent view knows (who is driving which tab), polled while `enabled`. */
export function useAgentRuns(enabled, every = 1000) {
  const [runs, setRuns] = useState([]);
  useEffect(() => {
    if (!enabled) { setRuns([]); return undefined; }
    let live = true, timer = 0;
    const read = async () => {
      try { const result = await listRuns(); if (live) setRuns(result.runs || []); }
      catch { /* tabs still show their own state */ }
      if (live) timer = setTimeout(read, document.hidden ? 4000 : every);
    };
    void read();
    return () => { live = false; clearTimeout(timer); };
  }, [enabled, every]);
  return runs;
}

// The last picture of each headless tab, so a tab that becomes a visible page keeps its look while the page opens.
const lastFrames = new Map();
export function rememberFrame(tabId, dataUrl) { if (dataUrl) { lastFrames.set(tabId, dataUrl); if (lastFrames.size > 12) lastFrames.delete(lastFrames.keys().next().value); } }
export function recallFrame(tabId) { return lastFrames.get(tabId) || ""; }
