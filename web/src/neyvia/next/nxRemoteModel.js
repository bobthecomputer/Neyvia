// Pure helpers for remote control (plan 15 T19; contract in plans/15-handoff.md "## T19").
// The other PC sees and uses only the windows Paul allowed here, through the computer-use
// driver: clicks on buttons, text into a text box he picked, a few navigation keys and
// one-step scrolls. Everything else is refused by the PC that owns the app, so the UI
// only offers what will work and says why the rest doesn't.

/** Navigation keys the owning PC accepts (browser KeyboardEvent.key -> driver key). */
export const REMOTE_KEYS = {
  Backspace: "backspace", ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down",
  Home: "home", End: "end", PageUp: "pageup", PageDown: "pagedown", Escape: "escape",
};

const QUIET_KEYS = new Set(["Control", "Shift", "Alt", "Meta", "AltGraph", "CapsLock", "NumLock", "ScrollLock", "OS", "Dead", "Unidentified", "Process"]);

/**
 * One keydown as remote input: printable characters become text (the caller batches them),
 * the navigation keys above are press_key, and anything else (Enter, Tab, Delete, shortcuts)
 * is "blocked" with a word for the hint. Null for keys that do nothing on their own.
 */
export function remoteKey({ key, ctrlKey, altKey, metaKey }) {
  if (!key || QUIET_KEYS.has(key)) return null;
  if (ctrlKey || altKey || metaKey) return { kind: "blocked", label: "Shortcuts" };
  if (key.length === 1) return { kind: "text", text: key };
  if (REMOTE_KEYS[key]) return { kind: "press_key", key: REMOTE_KEYS[key] };
  return { kind: "blocked", label: key === "Enter" ? "Enter" : key === "Tab" ? "Tab" : key === "Delete" ? "Delete" : "That key" };
}

const TEXT_ROLES = new Set(["Edit", "Document"]);

function smallest(elements, x, y, keep) {
  let best = null;
  for (const element of elements || []) {
    const box = element.screenshot_frame;
    if (!box || !element.enabled || element.offscreen || x < box.x || y < box.y || x >= box.x + box.w || y >= box.y + box.h || !keep(element)) continue;
    if (!best || box.w * box.h < best.screenshot_frame.w * best.screenshot_frame.h) best = element;
  }
  return best;
}

/** The text box under a point (the only kind of control that takes typing from the other PC). */
export const textBoxAt = (elements, x, y) => smallest(elements, x, y, element => TEXT_ROLES.has(element.role) && (element.actions || []).includes("set_value"));

/** The control under a point that can scroll one step. */
export const scrollerAt = (elements, x, y) => smallest(elements, x, y, element => (element.actions || []).includes("scroll"));

/** The control a click would reach, for the hover outline (anything with a background action). */
export const clickableAt = (elements, x, y) => smallest(elements, x, y, element => (element.actions || []).some(action => action !== "set_value") || TEXT_ROLES.has(element.role));

/** Width and height from a PNG's header, so the frame can be mapped before it is decoded. */
export function pngSize(buffer) {
  const bytes = new Uint8Array(buffer || new ArrayBuffer(0));
  if (bytes.length < 24 || bytes[0] !== 0x89 || bytes[1] !== 0x50 || bytes[12] !== 0x49 || bytes[13] !== 0x48) return null;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const width = view.getUint32(16);
  const height = view.getUint32(20);
  return width && height ? { width, height } : null;
}

/** "12 min left", "45 s left", "Time's up". */
export function timeLeft(expiresAt, now = Date.now()) {
  const end = Date.parse(expiresAt || "");
  if (!Number.isFinite(end)) return "";
  const seconds = Math.round((end - now) / 1000);
  if (seconds <= 0) return "Time's up";
  if (seconds < 60) return `${seconds} s left`;
  return `${Math.ceil(seconds / 60)} min left`;
}

/** "1:52" for the one-use code's two minutes. */
export function countdown(until, now = Date.now()) {
  const seconds = Math.max(0, Math.ceil((until - now) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/** Sessions this PC is sharing right now (the warning shows while any is not stopped). */
export const liveSessions = sessions => (sessions || []).filter(session => session.status !== "stopped");

/** A typed PC address as the backend wants it: scheme, no path, no trailing slash. */
export function normalizeAddress(value) {
  let text = String(value || "").trim();
  if (!text) return "";
  if (!/^https?:\/\//i.test(text)) text = `http://${text}`;
  return text.replace(/\/+$/, "");
}

/** Refusals that end a connection: a new code from that PC is needed, never a silent reconnect. */
const ENDING = new Set(["session_stopped", "capability_invalid", "host_takeover", "host_indicator_missing", "connection_missing", "invite_invalid"]);
export const endsConnection = code => ENDING.has(code);

/** Plain words for the contract's refusal codes. */
export function refusalText(code) {
  return {
    session_stopped: "That PC stopped sharing, or the time ran out.",
    capability_invalid: "That PC no longer accepts this connection (it may have restarted).",
    host_takeover: "Someone used that PC directly, so sharing stopped.",
    host_indicator_missing: "The warning on that PC was closed, so sharing stopped.",
    connection_missing: "This connection is gone. Connect again with a new code.",
    invite_invalid: "That code didn't work. It works once, for 2 minutes. Ask that PC for a new one.",
    pairing_rate_limited: "Too many tries. Wait a minute, then try again.",
    tailnet_address_required: "Use that PC's Tailscale address, like http://192.0.2.10:47880.",
    proof_port_not_allowed: "That address isn't allowed for remote control.",
    protected_service: "That address isn't allowed for remote control.",
    host_unavailable: "Couldn't reach that PC. Check it's on and Neyvia is running, then try again.",
    host_owner_required: "Sharing can only be turned on at the PC itself.",
    owner_required: "Only the PC's owner can use remote control.",
    login_required: "Sign in first.",
    origin_not_allowed: "This page isn't allowed to use remote control.",
    choose_windows_and_expiry: "Pick at least one window (up to 8) and a time.",
    end_existing_session: "Four shares are already on. Stop one first.",
    window_not_allowed: "That window can't be shared. It may have closed; refresh the list.",
    protected_window: "This window has a password field. Type passwords on that PC itself, then refresh here.",
    protection_unknown: "Neyvia can't tell whether this window asks for a password, so it isn't shown. Use it on that PC.",
    host_indicator_unavailable: "The warning window couldn't open on this PC, so nothing was shared.",
    stale_element_token: "The window changed. Look again and retry.",
    select_control: "Click a text box first, then type.",
    background_unavailable: "That control can't be used from another PC. Use it on that PC.",
    background_input_refused: "That PC didn't accept the input.",
    host_approval_required: "That looks like a button with lasting effects. Press it on that PC itself.",
    key_not_allowed: "That key only works on that PC itself.",
    input_not_allowed: "That kind of input only works on that PC itself.",
    scroll_not_allowed: "Only one step up or down at a time.",
    input_too_large: "That's too much text at once.",
    driver_unavailable: "The computer-use driver isn't running on that PC.",
    response_too_large: "That window's picture is too large to send.",
    unreachable: "Couldn't reach this PC's Neyvia service.",
    missing: "This PC's Neyvia service doesn't have remote control yet.",
  }[code] || "";
}

/** Why a share ended, in words (RemoteSession.reason). */
export function stopReason(reason) {
  return {
    host_stop: "You stopped it",
    expired: "Time ran out",
    host_takeover: "Stopped because the PC was used directly",
    remote_disconnected: "The other PC disconnected",
    backend_stopped: "Neyvia restarted",
    host_indicator_missing: "The warning window was closed",
  }[reason] || "Stopped";
}

/** The plain line for a remote log entry (texts are redacted by the owning PC). */
export function remoteEntryText(entry) {
  const label = entry.element?.label ? ` "${entry.element.label}"` : "";
  switch (entry.tool) {
    case "type_text": return `Typed into${label || " a text box"} (text not kept)`;
    case "press_key": return `Pressed ${entry.args?.key || "a key"}`;
    case "scroll": return `Scrolled ${entry.args?.direction || ""}`.trim();
    case "click": return `Clicked${label || " a control"}`;
    default: return entry.text || entry.tool || "Action";
  }
}
