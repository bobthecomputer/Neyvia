import { useSyncExternalStore } from "react";

import { local } from "./nxPrimitives.jsx";
import { getOs } from "./nxOsStore.js";
import { prefKey } from "./nxPlacementModel.js";
import { currentSelection, targetsIn, windowTarget, anchorLabel } from "./nxCommentAnchors.js";
import { openCommentsFor } from "./nxComments.js";

// The pop-out chat (plan 29 A): a chat in a window of its own over whatever is
// open, like claude.ai's "Describe the change you want…" over an artifact.
// One pop-out at a time. It is bound to a chat (the one open when it popped
// out, or a new one about this app) and carries the app's context with each
// message: what is open, what is selected, which comments are waiting. Where
// it sits and how big it is are remembered per app.

export const POPOUT_HINT = "Describe the change you want…";
export const POPOUT_KEY = "Ctrl+J"; // Ctrl+Shift+Space is dictation (NxDictation), so the pop-out takes Ctrl+J

const MIN = { w: 320, h: 360 };
let state = { open: false, winId: "", desc: null, title: "", sessionId: null, newChat: null, pendingRun: null, expanded: false, geom: local.get("popout.geom", {}) || {} };
const listeners = new Set();
const set = patch => { state = { ...state, ...(typeof patch === "function" ? patch(state) : patch) }; for (const listener of listeners) listener(); };

export function usePopout(selector = value => value) {
  return useSyncExternalStore(listener => { listeners.add(listener); return () => listeners.delete(listener); }, () => selector(state));
}
export const getPopout = () => state;

/** Pop the chat out over a window. `sessionId` is the chat to carry over; none = a new chat about this window. */
export function openPopout({ winId = "", desc = null, title = "", sessionId = undefined } = {}) {
  set(current => ({
    open: true, winId, desc, title,
    // undefined keeps the chat already in the pop-out (pressing Chat on another app); null is a new chat.
    sessionId: sessionId === undefined ? current.sessionId : sessionId,
  }));
}
export const closePopout = () => set({ open: false });
/** What the pop-out's new-chat form has chosen (agent, folder, model, effort, route), for comments sent before any chat exists. */
export const setPopoutNewChat = newChat => set({ newChat });
/** A run comments were sent to whose chat does not exist yet (a new Claude Code chat takes a while to start). */
export const setPopoutPending = pendingRun => set({ pendingRun });
export const bindPopoutSession = sessionId => set({ sessionId });
export const toggleExpanded = () => set(current => ({ expanded: !current.expanded }));

/** The window's saved place, or the default (bottom right, over the app's right edge). */
export function geometryFor(desc, viewport) {
  const saved = state.geom[prefKey(desc) || "chat"];
  const w = Math.min(Math.max(saved?.w ?? 400, MIN.w), viewport.width - 24);
  const h = Math.min(Math.max(saved?.h ?? 560, MIN.h), viewport.height - 24);
  const x = Math.min(Math.max(saved?.x ?? viewport.width - w - 20, 8), Math.max(8, viewport.width - w - 8));
  const y = Math.min(Math.max(saved?.y ?? viewport.height - h - 20, 8), Math.max(8, viewport.height - h - 8));
  return { x, y, w, h };
}
export function saveGeometry(desc, geom) {
  const key = prefKey(desc) || "chat";
  const geomAll = { ...state.geom, [key]: { x: Math.round(geom.x), y: Math.round(geom.y), w: Math.round(geom.w), h: Math.round(geom.h) } };
  local.set("popout.geom", geomAll);
  set({ geom: geomAll });
}
export const POPOUT_MIN = MIN;

// ---- the context a message carries ----------------------------------------------------------------------

const nameOf = path => String(path || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop();

/** What is open in a window: its title and one line per marked target (a note, a PDF, a page). Pure over the DOM it reads. */
export function windowContext(winId, desc) {
  const root = winId ? document.querySelector(`[data-window="${CSS.escape(winId)}"]`) : null;
  const body = root?.querySelector(".nx-stage-body") || root;
  const marked = targetsIn(body);
  const fallback = windowTarget(desc);
  const targets = marked.length ? marked.map(entry => ({ id: entry.id, label: entry.label || nameOf(entry.id.split(":").slice(1).join(":")) })) : [{ id: fallback.id, label: fallback.label }];
  return { root: body, targets, selection: currentSelection(body) };
}

/**
 * The compact block that goes in front of a message sent from the pop-out: where the person is, what they have
 * selected, the comments still open. Text, never a screenshot. Returns "" when there is nothing worth saying.
 */
export function contextBlock({ winId, desc, title }) {
  if (!desc) return "";
  const { targets, selection } = windowContext(winId, desc);
  const lines = [`[Neyvia context · ${title || (desc.type === "app" ? desc.app : desc.kind)}]`];
  const open = targets.filter(target => target.id && !/^(app|pane):/.test(target.id));
  if (open.length) lines.push(`Open: ${open.slice(0, 4).map(target => `${target.label} (${target.id})`).join("; ")}`);
  else if (desc.target) lines.push(`Open: ${desc.target}`);
  if (selection) lines.push(`Selected: "${selection}"`);
  const comments = openCommentsFor(winId, { unsent: true }).slice(0, 12);
  if (comments.length) {
    lines.push(`Comments not sent yet (${comments.length}):`);
    for (const comment of comments) lines.push(`- #${comment.number} ${anchorLabel(comment.anchor)}${comment.anchor?.quote ? ` "${comment.anchor.quote.slice(0, 80)}"` : ""}: ${comment.text} [id ${comment.id}]`);
  }
  return lines.length > 1 ? lines.join("\n") : "";
}

/** The window the pop-out acts on for a shortcut: the one last used, else the window beside the chat. */
export function windowForShortcut(focusedId) {
  const windows = getOs().windows || [];
  return windows.find(win => win.id === focusedId) || windows.find(win => win.placement === "main") || windows.find(win => win.placement === "full") || windows.find(win => win.placement === "side") || null;
}
