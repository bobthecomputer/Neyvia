import { checkedProofsEModel } from "./nxProofsEContracts.js";
// Where an app or pane lives on screen (Paul: "the 3D and all the apps must be
// usable from the side, or full screen, or in other places if the user moves
// them, or in a little bubble"). One window per open surface; each window has
// one placement:
//
//   main    beside the chat, in the conversation's place
//   side    the side-panel region, on whichever side the user put it
//   full    over the whole window
//   bubble  a small floating bubble; tapping it peeks the live app
//
// Pure functions only. nxOsStore keeps `windows`; NxPlacement renders every
// window in one layer keyed by its id, so moving a window only changes where
// it is drawn: the app keeps its state, its scroll and its iframes.

export const PLACEMENTS = ["main", "side", "full", "bubble"];
export const PLACEMENT_LABELS = { main: "Beside the chat", side: "Side panel", full: "Full screen", bubble: "Bubble" };
const SINGLE = new Set(["main", "side", "full"]); // one window each; bubbles stack
export const MAX_BUBBLES = 6;
const REMEMBERED = new Set(["main", "side"]); // where an app opens next time

const clamp01 = value => Math.min(1, Math.max(0, Number.isFinite(Number(value)) ? Number(value) : 0));

/** A window's identity: an app is one window whatever it shows; a pane is one per kind and target. */
function raw_windowKey(desc) {
  if (!desc || typeof desc !== "object") return "";
  if (desc.type === "pane") return `pane:${desc.kind}:${desc.target ?? ""}`;
  if (desc.type === "app" && desc.app) return `app:${desc.app}`;
  return "";
}

/** What "remember where this opens" is keyed by: the app, or the pane kind (any target). */
export const prefKey = desc => (desc?.type === "pane" ? `pane:${desc.kind}` : desc?.type === "app" ? `app:${desc.app}` : "");

export const findWindow = (windows, id) => windows.find(win => win.id === id) || null;
export const windowAt = (windows, placement) => windows.find(win => win.placement === placement) || null;
/** The stage the shell docks the chat beside: the window placed beside the chat. */
export const mainDesc = windows => windowAt(windows, "main")?.desc || null;

const bubbleSpot = windows => ({ x: 1, y: clamp01(0.22 + windows.filter(win => win.placement === "bubble").length * 0.11) });

function asBubble(win, windows, back) {
  const spot = win.placement === "bubble" ? { x: win.x, y: win.y } : bubbleSpot(windows);
  return { ...win, placement: "bubble", back: back && back !== "bubble" && back !== "full" ? back : win.back || "main", peek: false, x: spot.x, y: spot.y };
}

/** Keep at most MAX_BUBBLES: the oldest bubble closes first (its app was already out of sight). */
function capBubbles(windows) {
  const bubbles = windows.filter(win => win.placement === "bubble");
  if (bubbles.length <= MAX_BUBBLES) return windows;
  const drop = new Set(bubbles.slice(0, bubbles.length - MAX_BUBBLES).map(win => win.id));
  return windows.filter(win => !drop.has(win.id));
}

/**
 * Move a window. A single slot (main, side, full) holds one window: whoever is
 * there swaps into the mover's old place when that is main or side, and
 * otherwise becomes a bubble, so nothing a user moved is ever closed by a move.
 */
function raw_placeWindow(windows, id, placement) {
  if (!PLACEMENTS.includes(placement)) throw new Error(`Unknown placement: ${placement}`);
  const mover = findWindow(windows, id);
  if (!mover) return windows;
  if (mover.placement === placement) return placement === "bubble" ? windows : windows.map(win => (win.id === id ? { ...win, peek: false } : win));
  const from = mover.placement;
  // Full screen and the bubble remember where the window came from, for "restore".
  const back = from === "main" || from === "side" ? from : mover.back || "main";
  const occupant = SINGLE.has(placement) ? windowAt(windows, placement) : null;
  const next = windows.map(win => {
    if (win.id === id) {
      if (placement === "bubble") return asBubble(win, windows, back);
      return { ...win, placement, back: placement === "full" ? back : null, peek: false };
    }
    if (occupant && win.id === occupant.id) {
      if (from === "main" || from === "side") return { ...win, placement: from, back: null, peek: false };
      return asBubble(win, windows, occupant.placement);
    }
    return win;
  });
  return capBubbles(next);
}

/** Back from full screen or a bubble to where the window was before. */
function raw_restoreWindow(windows, id) {
  const win = findWindow(windows, id);
  if (!win || (win.placement !== "full" && win.placement !== "bubble")) return windows;
  return raw_placeWindow(windows, id, win.back === "side" ? "side" : "main");
}

/**
 * Open (or show again) a surface. A new window opens where its app last lived
 * (main or side), beside the chat by default, replacing what was there: the
 * same as opening an app always did. A window that is already open stays where
 * the user put it and only takes the new target; a bubble peeks open.
 */
function raw_openWindow(windows, desc, { prefs = {}, placement = null } = {}) {
  const id = raw_windowKey(desc);
  if (!id) throw new Error("Nothing to open: a window needs an app or a pane kind");
  const existing = findWindow(windows, id);
  if (existing) {
    const moved = placement && placement !== existing.placement ? raw_placeWindow(windows, id, placement) : windows;
    const shown = findWindow(moved, id)?.placement === "bubble" ? raw_peekBubble(moved, id, true) : moved;
    return shown.map(win => (win.id === id ? { ...win, desc } : win));
  }
  const where = PLACEMENTS.includes(placement) ? placement : REMEMBERED.has(prefs[prefKey(desc)]) ? prefs[prefKey(desc)] : "main";
  const fresh = { id, desc, placement: where, back: where === "full" ? "main" : null, peek: false, x: 1, y: 0.3 };
  if (where === "bubble") Object.assign(fresh, bubbleSpot(windows), { back: "main", peek: true });
  const kept = SINGLE.has(where) ? windows.filter(win => win.placement !== where) : where === "bubble" ? raw_peekBubble(windows, "", false) : windows;
  return capBubbles([...kept, fresh]);
}

const raw_closeWindow = (windows, id) => windows.filter(win => win.id !== id);

function raw_moveBubble(windows, id, x, y) {
  return windows.map(win => (win.id === id && win.placement === "bubble" ? { ...win, x: clamp01(x), y: clamp01(y) } : win));
}

/** Show or hide a bubble's live app (one peeks at a time). */
function raw_peekBubble(windows, id, open) {
  return windows.map(win => {
    if (win.placement !== "bubble") return win;
    if (win.id !== id) return win.peek ? { ...win, peek: false } : win;
    return { ...win, peek: open === undefined ? !win.peek : Boolean(open) };
  });
}

/** Remember main/side per app so it opens there next time. Full screen and bubbles are moments, not homes. */
function raw_rememberPlacement(prefs, desc, placement) {
  const key = prefKey(desc);
  if (!key || !REMEMBERED.has(placement) || prefs[key] === placement) return prefs;
  return { ...prefs, [key]: placement };
}

/**
 * Older code (and every bus action) sets `stage` directly. Turn that change
 * into window operations: a new stage opens (or shows) its window; a cleared
 * stage closes the window beside the chat, or the full-screen one when no
 * window is beside the chat.
 */
function raw_syncStage(windows, before, after, { prefs = {} } = {}) {
  if (after === before) return windows;
  if (after) return raw_openWindow(windows, after, { prefs });
  const target = windowAt(windows, "main") || windowAt(windows, "full");
  return target ? raw_closeWindow(windows, target.id) : windows;
}

/** Validate prefs read from storage. */
function raw_normalizePrefs(saved) {
  if (!saved || typeof saved !== "object" || Array.isArray(saved)) return {};
  return Object.fromEntries(Object.entries(saved).filter(([key, value]) => /^(app|pane):/.test(key) && REMEMBERED.has(value)));
}

/**
 * Which drop zone a pointer is over while a window is dragged (NxPlacement):
 * the outer fifths are the left and right side, the top band is full screen,
 * the bottom band is the bubble, the rest is beside the chat.
 */
function raw_dropZone(point, width, height) {
  const x = point.x / Math.max(1, width);
  const y = point.y / Math.max(1, height);
  if (x < 0.2) return { placement: "side", side: "left" };
  if (x > 0.8) return { placement: "side", side: "right" };
  if (y < 0.16) return { placement: "full", side: null };
  if (y > 0.84) return { placement: "bubble", side: null };
  return { placement: "main", side: null };
}

/** Region order with the side panel moved to the left or right of the conversation. */
function raw_orderWithPanel(order, side) {
  const rest = order.filter(id => id !== "panel");
  const at = rest.indexOf("main");
  if (at < 0) return order;
  rest.splice(side === "left" ? at : at + 1, 0, "panel");
  return rest;
}

// Public observers check the placement contracts (nxProofsEContracts.js, manual design.proofs-e-models) on every call.
export function windowKey(...args) { return checkedProofsEModel("placement.windowKey", args, raw_windowKey(...args)); }
export function placeWindow(...args) { return checkedProofsEModel("placement.placeWindow", args, raw_placeWindow(...args)); }
export function restoreWindow(...args) { return checkedProofsEModel("placement.restoreWindow", args, raw_restoreWindow(...args)); }
export function openWindow(...args) { return checkedProofsEModel("placement.openWindow", args, raw_openWindow(...args)); }
export function closeWindow(...args) { return checkedProofsEModel("placement.closeWindow", args, raw_closeWindow(...args)); }
export function moveBubble(...args) { return checkedProofsEModel("placement.moveBubble", args, raw_moveBubble(...args)); }
export function peekBubble(...args) { return checkedProofsEModel("placement.peekBubble", args, raw_peekBubble(...args)); }
export function syncStage(...args) { return checkedProofsEModel("placement.syncStage", args, raw_syncStage(...args)); }
export function rememberPlacement(...args) { return checkedProofsEModel("placement.rememberPlacement", args, raw_rememberPlacement(...args)); }
export function normalizePrefs(...args) { return checkedProofsEModel("placement.normalizePrefs", args, raw_normalizePrefs(...args)); }
export function dropZone(...args) { return checkedProofsEModel("placement.dropZone", args, raw_dropZone(...args)); }
export function orderWithPanel(...args) { return checkedProofsEModel("placement.orderWithPanel", args, raw_orderWithPanel(...args)); }
