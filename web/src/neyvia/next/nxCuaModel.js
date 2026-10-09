import { checkedProofsEModel } from "./nxProofsEContracts.js";
// Pure helpers for the computer-use preview (plan 15 T16, contract in plans/15-handoff.md "## T16").
// Geometry is always in the pixels of one capture (`captureId`): the driver maps them to the
// window the same way cua-driver maps `click {capture_id, x, y}`.

/** A pointer position on the shown frame, as pixels of that frame's capture. */
function raw_toCapture(clientX, clientY, rect, frame) {
  if (!rect?.width || !rect?.height || !frame?.width || !frame?.height) return null;
  const x = ((clientX - rect.left) / rect.width) * frame.width;
  const y = ((clientY - rect.top) / rect.height) * frame.height;
  if (x < 0 || y < 0 || x > frame.width || y > frame.height) return null;
  return { x: Math.min(frame.width - 1, Math.round(x)), y: Math.min(frame.height - 1, Math.round(y)) };
}

/** A box in capture pixels as percentages of the frame, for an overlay that scales with the image. */
export function boxStyle(box, frame) {
  if (!box || !frame?.width || !frame?.height) return null;
  const pct = (value, total) => `${Math.max(0, Math.min(100, (value / total) * 100))}%`;
  return { left: pct(box.x, frame.width), top: pct(box.y, frame.height), width: pct(box.w, frame.width), height: pct(box.h, frame.height) };
}

/** The smallest element under a capture point (elements carry `screenshot_frame`, cua's shape). */
function raw_elementAt(elements, x, y) {
  let best = null;
  for (const element of elements || []) {
    const box = element.screenshot_frame;
    if (!box || x < box.x || y < box.y || x > box.x + box.w || y > box.y + box.h) continue;
    if (!best || box.w * box.h < best.screenshot_frame.w * best.screenshot_frame.h) best = element;
  }
  return best;
}

// cua-driver key names (press_key / hotkey) for the browser's KeyboardEvent.key values.
const NAMED = {
  Enter: "enter", Backspace: "backspace", Tab: "tab", Escape: "escape", Delete: "delete", Insert: "insert",
  ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right", Home: "home", End: "end",
  PageUp: "pageup", PageDown: "pagedown", " ": "space", ContextMenu: "menu",
};
const MODIFIER_KEYS = new Set(["Control", "Shift", "Alt", "Meta", "AltGraph", "CapsLock", "NumLock", "ScrollLock", "OS", "Dead", "Unidentified", "Process"]);

function keyName(key) {
  if (NAMED[key]) return NAMED[key];
  if (/^F([1-9]|1[0-9]|2[0-4])$/.test(key)) return key.toLowerCase();
  if (key.length === 1) return key.toLowerCase();
  return null;
}

/**
 * One keydown as what the driver receives: plain characters are text (batched by the caller
 * into one type_text), named keys are press_key, anything held with Ctrl/Alt/Win is a hotkey.
 * Returns null for keys that do nothing on their own (Shift, Caps Lock, dead keys).
 */
function raw_keyToInput(event) {
  const { key, ctrlKey, altKey, metaKey, shiftKey } = event;
  if (!key || MODIFIER_KEYS.has(key)) return null;
  const combo = ctrlKey || altKey || metaKey;
  if (!combo && key.length === 1) return { kind: "text", text: key };
  const name = keyName(key);
  if (!name) return null;
  const modifiers = [ctrlKey && "ctrl", altKey && "alt", shiftKey && "shift", metaKey && "win"].filter(Boolean);
  if (combo) return { kind: "hotkey", keys: [...modifiers, name] };
  return modifiers.length ? { kind: "press_key", key: name, modifiers } : { kind: "press_key", key: name };
}

/** One wheel gesture as a cua scroll: the dominant axis, in lines (1 to 10). */
function raw_wheelToScroll(deltaX, deltaY, deltaMode = 0) {
  const scale = deltaMode === 1 ? 1 : deltaMode === 2 ? 10 : 1 / 40; // pixels -> lines
  const vertical = Math.abs(deltaY) >= Math.abs(deltaX);
  const delta = vertical ? deltaY : deltaX;
  if (!delta) return null;
  const amount = Math.max(1, Math.min(10, Math.round(Math.abs(delta) * scale)));
  return { direction: vertical ? (delta > 0 ? "down" : "up") : (delta > 0 ? "right" : "left"), amount };
}

/** The session the pane shows: the named one, else the newest active (pending counts: it needs Paul). */
function raw_pickSession(sessions, target) {
  const list = sessions || [];
  if (target) return list.find(session => session.id === target) || null;
  const live = list.filter(session => session.status !== "ended");
  const newest = rows => [...rows].sort((a, b) => String(b.lastActionAt || b.startedAt || "").localeCompare(String(a.lastActionAt || a.startedAt || "")))[0] || null;
  return newest(live) || newest(list);
}

/** Who the agent is, in words ("Codex", "Claude Code"). */
export function agentName(session) {
  const app = session?.owner?.app || "";
  return { codex: "Codex", claude: "Claude Code", "claude-code": "Claude Code", neyvia: "Neyvia", opencode: "OpenCode" }[app] || (app ? app[0].toUpperCase() + app.slice(1) : "The agent");
}

/** Merge one log entry into the list (new, or an update of the same id), kept in seq order and bounded. */
function raw_mergeLog(entries, entry, limit = 400) {
  const index = entries.findIndex(row => row.id === entry.id);
  const next = index === -1 ? [...entries, entry] : entries.map((row, at) => (at === index ? { ...row, ...entry } : row));
  if (next.length > 1) next.sort((a, b) => a.seq - b.seq);
  return next.length > limit ? next.slice(next.length - limit) : next;
}

const VERB = { click: "Clicked", double_click: "Double-clicked", right_click: "Right-clicked", type_text: "Typed", press_key: "Pressed", hotkey: "Pressed", scroll: "Scrolled", drag: "Dragged", set_value: "Set", launch_app: "Opened", invoke_menu: "Chose" };

/** The plain line for an entry when the service sent none. */
export function entryText(entry) {
  if (entry.text) return entry.text;
  const args = entry.args || {};
  const label = entry.element?.label ? `"${entry.element.label}"` : "";
  switch (entry.tool) {
    case "type_text": return `Typed "${String(args.text || "").slice(0, 80)}"`;
    case "press_key": return `Pressed ${[...(args.modifiers || []), args.key].filter(Boolean).join("+")}`;
    case "hotkey": return `Pressed ${(args.keys || []).join("+")}`;
    case "scroll": return `Scrolled ${args.direction || ""}`.trim();
    case "note": return String(args.text || args.note || "");
    default: {
      const where = !label && args.x != null && args.y != null ? `at ${Math.round(args.x)}, ${Math.round(args.y)}` : label;
      return [VERB[entry.tool] || entry.tool, where].filter(Boolean).join(" ");
    }
  }
}

/** What the result of an action says, in one or two words (cua ActionResult.effect). */
export function effectLabel(result) {
  return { confirmed: "checked", partial: "partly", unverifiable: "not checked", suspected_noop: "no change seen", refused: "refused" }[result?.effect] || "";
}

/** Plain reasons for the refusal codes of the contract. */
export function refusalText(code) {
  return {
    paused_by_user: "Paused: you have control",
    app_not_allowed: "That app isn't allowed",
    denied_by_user: "You said no",
    approval_timeout: "No answer in time",
    session_ended: "The session ended",
    session_pending: "Waiting for you to allow the session",
    foreground_not_allowed: "Bringing windows forward isn't allowed",
    background_unavailable: "Couldn't reach it without bringing the window forward",
    stale_element_token: "The window changed; looked again",
  }[code] || "";
}

// Public observers check the executable manual claims on every invocation.
export function toCapture(...args) { return checkedProofsEModel("cua.toCapture", args, raw_toCapture(...args)); }
export function keyToInput(...args) { return checkedProofsEModel("cua.keyToInput", args, raw_keyToInput(...args)); }
export function wheelToScroll(...args) { return checkedProofsEModel("cua.wheelToScroll", args, raw_wheelToScroll(...args)); }
export function elementAt(...args) { return checkedProofsEModel("cua.elementAt", args, raw_elementAt(...args)); }
export function pickSession(...args) { return checkedProofsEModel("cua.pickSession", args, raw_pickSession(...args)); }
export function mergeLog(...args) { return checkedProofsEModel("cua.mergeLog", args, raw_mergeLog(...args)); }
