import { useSyncExternalStore } from "react";

import { callNx } from "./nxApi.js";

// What the PC read in each chat's transcript (plan 15 T7, sidebar.state):
// its lane (Images / Quick / Other), the agents it started, and the hover
// preview. The sidebar never guesses these from titles or folders; a chat
// that hasn't been read yet stays in Other until its observation arrives.
//
// Reads go by id in small batches (about 0.1 s per chat on the PC), most
// important first, and are cached by the chat's last update so a chat is
// read again only after it changed. The cache is a per-browser convenience;
// the PC stays the source of truth.

const BATCH = 10;
const MIN_REREAD_MS = 10000; // a streaming chat changes every second; read it at most this often
const CACHE_KEY = "nx.sidebar.observed.v1";
const CACHE_MAX = 400;

const stampOf = row => `${row.updated_at || ""}|${row.status || ""}`;

function readCache() {
  try {
    const saved = JSON.parse(localStorage.getItem(CACHE_KEY) || "null");
    return saved && typeof saved === "object" ? saved : {};
  } catch { return {}; }
}

let state = { byId: readCache(), folders: {}, errors: {}, pending: {}, failure: "" };
const listeners = new Set();
function set(patch) {
  state = { ...state, ...(typeof patch === "function" ? patch(state) : patch) };
  for (const listener of listeners) listener();
}

export function useObserved(selector) {
  return useSyncExternalStore(
    listener => { listeners.add(listener); return () => listeners.delete(listener); },
    () => selector(state),
  );
}
export const getObserved = () => state;

let cacheTimer = null;
function saveCache() {
  clearTimeout(cacheTimer);
  cacheTimer = setTimeout(() => {
    try {
      const entries = Object.entries(state.byId).sort((a, b) => String(b[1].stamp).localeCompare(String(a[1].stamp))).slice(0, CACHE_MAX);
      localStorage.setItem(CACHE_KEY, JSON.stringify(Object.fromEntries(entries)));
    } catch { /* storage full or blocked: the PC is read again next time */ }
  }, 800);
}

/** Subject folders the PC knows (sidebar groups, not disk folders): id -> { id, name, path: null }. */
export function rememberFolders(list) {
  const folders = { ...state.folders };
  let changed = false;
  for (const folder of list || []) {
    if (!folder?.id || !folder.name || folders[folder.id]?.name === folder.name) continue;
    folders[folder.id] = { id: folder.id, name: String(folder.name), path: null, subject: true };
    changed = true;
  }
  if (changed) set({ folders });
}

const queue = new Map(); // id -> stamp, in priority order
const lastRead = {}; // id -> ms
let running = false;
let laterTimer = null;

async function drain() {
  if (running) return;
  running = true;
  try {
    while (queue.size) {
      const now = Date.now();
      const batch = [];
      for (const [id, stamp] of queue) {
        if (now - (lastRead[id] || 0) < MIN_REREAD_MS) continue;
        batch.push([id, stamp]);
        if (batch.length >= BATCH) break;
      }
      if (!batch.length) {
        // Only chats read moments ago are left: come back for them.
        clearTimeout(laterTimer);
        laterTimer = setTimeout(() => void drain(), MIN_REREAD_MS);
        break;
      }
      for (const [id] of batch) { queue.delete(id); lastRead[id] = now; }
      const ids = batch.map(([id]) => id);
      set(current => ({ pending: { ...current.pending, ...Object.fromEntries(ids.map(id => [id, true])) } }));
      try {
        const result = await callNx("sidebar_state_command", { ids });
        rememberFolders(result?.subjectFolders);
        const stamps = Object.fromEntries(batch);
        set(current => {
          const byId = { ...current.byId };
          const errors = { ...current.errors };
          const pending = { ...current.pending };
          for (const id of ids) delete pending[id];
          for (const row of result?.sessions || []) {
            if (!row?.id || !row.sidebar) continue;
            const asked = stamps[row.id];
            byId[row.id] = { stamp: asked && !asked.startsWith("refresh:") ? asked : stampOf(row), sidebar: row.sidebar };
            delete errors[row.id];
          }
          for (const failure of result?.errors || []) if (failure?.id) errors[failure.id] = failure.error || "Couldn't read this chat";
          return { byId, errors, pending, failure: "" };
        });
        saveCache();
      } catch (error) {
        set(current => {
          const pending = { ...current.pending };
          for (const id of ids) delete pending[id];
          return { pending, failure: error?.message || "The PC didn't answer" };
        });
        if (error?.code === "network" || error?.status === 401) break; // the shell already says the PC is unreachable
      }
    }
  } finally {
    running = false;
  }
}

/**
 * Ask the PC to read these chats (in this order) when they're new or changed
 * since the last read. Safe to call on every render: unchanged chats are skipped.
 */
export function observeRows(rows) {
  const wanted = [];
  for (const row of rows) {
    if (!row?.id || row.archived || /^fixture:/.test(row.id)) continue;
    const stamp = stampOf(row);
    if (state.byId[row.id]?.stamp === stamp) continue;
    wanted.push([row.id, stamp]);
  }
  if (!wanted.length) return;
  // The caller's order is the priority (the open chat first, then newest): a chat that just
  // changed must not wait behind a backlog of hundreds of older chats still being read.
  jumpQueue(wanted);
  void drain();
}

function jumpQueue(entries) {
  const ids = new Set(entries.map(([id]) => id));
  const rest = [...queue].filter(([id]) => !ids.has(id));
  queue.clear();
  for (const [id, stamp] of entries) queue.set(id, stamp);
  for (const [id, stamp] of rest) queue.set(id, stamp);
}

/** Read these chats again now (after a move, an undo or a finished run), ahead of the backlog. */
export function refreshObserved(ids) {
  for (const id of ids || []) delete lastRead[id];
  jumpQueue((ids || []).map(id => [id, `refresh:${Date.now()}`]));
  void drain();
}

/** The observation for one chat: { sidebar, pending, error } (sidebar is null until read). */
export function observationOf(observed, id) {
  return { sidebar: observed.byId[id]?.sidebar || null, pending: Boolean(observed.pending[id]), error: observed.errors[id] || "" };
}
