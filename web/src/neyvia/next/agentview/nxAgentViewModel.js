// Agent view (watch and steer agents): pure rules the surfaces render.
//
// The agent works on its own surface (an app on the private agent desktop, an
// Obscura page, the app it is building). Paul sees a rendered mirror: frames
// arrive as changed regions stacked on a base picture, actions are said in
// plain words, his comments are bound to the exact frame and action, and a
// time-lapse replays what happened while he was away. Backend contract:
// src/grant_agent/neyvia_agentview.py.

// Executable postconditions (manuals/cl/agent-view.cl, proof contracts agentview.*), checked on
// every call before the value reaches the view. The error names the contract only.
export class AgentViewContractError extends Error {
  constructor(id) { super(`Agent view contract ${id} failed`); this.name = "AgentViewContractError"; this.contract = id; }
}
function checked(id, ok, value) {
  if (!ok) throw new AgentViewContractError(id);
  return value;
}

// ---- frame stream ------------------------------------------------------------------

export const MAX_LAYERS = 32; // past this many stacked patches, ask for one fresh full frame
export const POLL = {
  full: { ms: 250, slowest: 1000 },   // the run's own window: 4 fps, 1 fps when nothing moves
  side: { ms: 333, slowest: 1000 },   // a side panel: 3 fps
  thumb: { ms: 2000, slowest: 4000 }, // a card or bubble: 0.5 fps
};
export const QUIET_POLLS = 8; // unchanged answers before slowing down
export const ERROR_MS = 3000;

/** The size class of a mirror from its width in CSS pixels. */
export function sizeClass(width) {
  if (!Number.isFinite(width) || width <= 0) return "thumb";
  if (width < 280) return "thumb";
  if (width < 600) return "side";
  return "full";
}

/**
 * How long until the next frame request, or null to stop polling. Hidden
 * tabs and views scrolled or tucked out of sight (a closed bubble) cost
 * nothing; a still picture is polled less and less often.
 */
export function pollDelay(state = {}) {
  const delay = rawPollDelay(state);
  const rule = POLL[state.size] || POLL.full;
  const hidden = state.visible === false || state.inView === false;
  return checked("agentview.poll", hidden ? delay === null
    : state.failed ? delay >= ERROR_MS : delay >= rule.ms && delay <= Math.max(rule.slowest, rule.ms), delay);
}
function rawPollDelay({ visible = true, inView = true, size = "full", quiet = 0, failed = false } = {}) {
  if (!visible || !inView) return null;
  const rule = POLL[size] || POLL.full;
  if (failed) return Math.max(ERROR_MS, rule.ms);
  if (quiet < QUIET_POLLS) return rule.ms;
  const steps = Math.floor((quiet - QUIET_POLLS) / QUIET_POLLS) + 1;
  return Math.min(rule.slowest, rule.ms * 2 ** steps);
}

/** The capture rate to ask the PC for, matching the poll delay (0.2-5 fps). */
export function fpsFor(delay) {
  const fps = !delay ? 0.2 : Math.min(5, Math.max(0.2, Math.round((1000 / delay) * 10) / 10));
  return checked("agentview.poll", fps >= 0.2 && fps <= 5, fps);
}

export const emptyStack = () => ({ v: 0, w: 0, h: 0, layers: [], needsFull: false, at: null });

/**
 * Apply one answer of GET /frame to the picture being shown. A delta only
 * applies on top of the version it was computed from; anything else asks for
 * a full frame on the next request.
 */
export function applyFrame(stack, answer) {
  const next = rawApplyFrame(stack, answer);
  const kind = answer?.kind;
  const ok = kind === "full" ? next.v === answer.v && !next.needsFull
    : kind === "delta" ? (answer.base === stack.v && answer.w === stack.w && answer.h === stack.h
      ? next.v === answer.v && next.layers.length === stack.layers.length + (answer.patches || []).length
      : next.needsFull && next.v === stack.v)
      : next === stack;
  return checked("agentview.applyFrame", ok, next);
}
function rawApplyFrame(stack, answer) {
  if (!answer || answer.kind === "none" || answer.kind === "same") return stack;
  const layer = (patch, index) => ({ key: `${answer.v}-${index}`, x: patch.x, y: patch.y, w: patch.w, h: patch.h, src: patch.src });
  if (answer.kind === "full") {
    return { v: answer.v, w: answer.w, h: answer.h, at: answer.at, needsFull: false, layers: (answer.patches || []).map(layer) };
  }
  if (answer.kind === "delta") {
    if (answer.base !== stack.v || answer.w !== stack.w || answer.h !== stack.h) return { ...stack, needsFull: true };
    const layers = [...stack.layers, ...(answer.patches || []).map(layer)];
    return { v: answer.v, w: answer.w, h: answer.h, at: answer.at, layers, needsFull: layers.length > MAX_LAYERS };
  }
  return stack;
}

/** The `since` to send: the version shown, or 0 when a full frame is needed. */
export const sinceFor = stack => (stack.needsFull ? 0 : stack.v);

/** A layer's place on the frame, in percent so the picture scales with its box. */
export function layerStyle(layer, stack) {
  if (!stack.w || !stack.h) return null;
  const pct = (value, total) => `${(value / total) * 100}%`;
  return { left: pct(layer.x, stack.w), top: pct(layer.y, stack.h), width: pct(layer.w, stack.w), height: pct(layer.h, stack.h) };
}

/** A normalised box (0-1) as percentages for an overlay. */
export function boxPct(box) {
  if (!box || ![box.x, box.y, box.w, box.h].every(Number.isFinite)) return null;
  const pct = value => `${Math.max(0, Math.min(100, value * 100))}%`;
  return { left: pct(box.x), top: pct(box.y), width: pct(box.w), height: pct(box.h) };
}

/** Merge new log entries (by their run-local number `n`), in order, bounded. */
export function mergeEntries(current, incoming, limit = 400) {
  if (!incoming?.length) return current;
  const byN = new Map(current.map(entry => [entry.n, entry]));
  for (const entry of incoming) byN.set(entry.n, { ...byN.get(entry.n), ...entry });
  const rows = [...byN.values()].sort((a, b) => a.n - b.n);
  return rows.length > limit ? rows.slice(rows.length - limit) : rows;
}

// ---- plain words ----------------------------------------------------------------------

const NOUNS = {
  edit: "box", textbox: "box", text: "box", searchbox: "search box", document: "document", button: "button", menuitem: "menu item",
  menu: "menu", listitem: "item", option: "option", checkbox: "checkbox", radio: "option", radiobutton: "option", link: "link",
  hyperlink: "link", combobox: "list", tab: "tab", tabitem: "tab", treeitem: "item", slider: "slider", image: "picture",
  heading: "heading", h1: "heading", h2: "heading", h3: "heading", table: "table",
};
const CELL = new Set(["dataitem", "cell", "gridcell"]);
const HOTKEYS = { "ctrl+s": "save", "ctrl+c": "copy", "ctrl+v": "paste", "ctrl+x": "cut", "ctrl+z": "undo", "ctrl+y": "redo", "ctrl+a": "select all", "ctrl+f": "find", "ctrl+n": "new", "ctrl+o": "open", "ctrl+p": "print", "alt+f4": "close", "ctrl+w": "close" };
const KEY_NAMES = { enter: "Enter", tab: "Tab", escape: "Escape", backspace: "Backspace", delete: "Delete", space: "Space", up: "Up", down: "Down", left: "Left", right: "Right", home: "Home", end: "End", pageup: "Page Up", pagedown: "Page Down", ctrl: "Ctrl", alt: "Alt", shift: "Shift", win: "Win" };

const quote = (text, max = 48) => {
  const value = String(text ?? "").replace(/\s+/g, " ").trim();
  return `“${value.length > max ? `${value.slice(0, max - 1)}…` : value}”`;
};
const keyLabel = key => KEY_NAMES[String(key).toLowerCase()] || (String(key).length === 1 ? String(key).toUpperCase() : String(key));

/** "the “Apply” button", "cell B4", "the text box", "the window". */
export function targetText(element) {
  const label = String(element?.label || "").replace(/\s+/g, " ").trim().slice(0, 60);
  const role = String(element?.role || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  if (CELL.has(role) && label) return `cell ${label}`;
  const noun = NOUNS[role] || "";
  if (label) return noun ? `the ${quote(label, 40)} ${noun}` : quote(label, 40);
  return noun ? `the ${noun}` : "the window";
}

function keysText(say) {
  const keys = Array.isArray(say?.keys) && say.keys.length ? say.keys : [...(say?.modifiers || []), say?.key].filter(Boolean);
  if (!keys.length) return "a key";
  const combo = keys.map(keyLabel).join("+");
  const meaning = HOTKEYS[keys.map(key => String(key).toLowerCase()).join("+")];
  return meaning ? `${combo} (${meaning})` : combo;
}

const host = url => { try { return new URL(url).host; } catch { return String(url || "").slice(0, 60); } };

/**
 * One sentence for what the agent is about to do ("about") or did ("done"):
 * "Typing “42” into the “Task input” box in TaskApp".
 */
export function describeAction(entry, phase = "done") {
  if (!entry) return "";
  if (entry.kind === "feedback") return `You: ${quote(entry.text, 90)}`;
  const say = entry.say || {};
  const about = phase === "about";
  const where = about && entry.app ? ` in ${entry.app}` : "";
  const target = targetText(entry.element);
  const verb = (doing, did) => (about ? doing : did);
  let text;
  switch (entry.tool) {
    case "type_text": text = `${verb("Typing", "Typed")} ${quote(say.text)} into ${target}${where}`; break;
    case "fill": text = `${verb("Typing", "Typed")} ${quote(say.value)} into ${target}${where}`; break;
    case "set_value": text = `${verb("Setting", "Set")} ${target} to ${quote(say.value ?? say.text)}${where}`; break;
    case "select": text = `${verb("Choosing", "Chose")} ${quote(say.value)} in ${target}${where}`; break;
    case "click": text = `${verb("Clicking", "Clicked")} ${target}${where}`; break;
    case "double_click": text = `${verb("Double-clicking", "Double-clicked")} ${target}${where}`; break;
    case "right_click": text = `${verb("Opening the menu on", "Opened the menu on")} ${target}${where}`; break;
    case "invoke_menu": text = `${verb("Choosing", "Chose")} ${target}${where}`; break;
    case "press_key":
    case "hotkey": text = `${verb("Pressing", "Pressed")} ${keysText(say)}${where}`; break;
    case "scroll": text = `${verb("Scrolling", "Scrolled")} ${say.direction || ""}${entry.app ? ` in ${entry.app}` : ""}`.replace(/\s+/g, " ").trim(); break;
    case "drag": text = `${verb("Dragging", "Dragged")} ${target}${where}`; break;
    case "launch_app": text = `${verb("Opening", "Opened")} ${say.name || entry.app || "an app"}`; break;
    case "open": text = `${verb("Opening", "Opened")} ${host(say.url)}`; break;
    case "navigate": text = `${verb("Going to", "Went to")} ${host(say.url)}`; break;
    case "back": text = verb("Going back", "Went back"); break;
    case "forward": text = verb("Going forward", "Went forward"); break;
    case "reload": text = verb("Reloading the page", "Reloaded the page"); break;
    case "note": return entry.summary || say.text || "Left a note";
    case "feedback": return `You: ${quote(entry.text, 90)}`;
    default: return entry.summary || String(entry.tool || "Working").replace(/_/g, " ");
  }
  if (entry.by === "paul" && !about) return `You ${text.charAt(0).toLowerCase()}${text.slice(1)}`;
  return text;
}

/** What the check after an action says, or "" when there is nothing to say. */
export function resultText(entry) {
  if (!entry) return "";
  if (entry.status === "refused" || entry.status === "denied") return `Stopped: ${entry.summary || "not allowed"}`;
  if (entry.status === "failed") return `Didn't work${entry.summary ? `: ${entry.summary}` : ""}`;
  switch (entry.effect) {
    case "confirmed": return entry.readback ? `Checked: it now reads ${quote(entry.readback, 40)}` : "Checked";
    case "partial": return "Partly done";
    case "suspected_noop": return "No change seen";
    case "unverifiable": return "Not checked";
    default: return entry.summary && entry.kind === "action" && /^Page changed/.test(entry.summary) ? entry.summary : "";
  }
}

/** The tone of a step's result chip. */
export function resultTone(entry) {
  if (!entry) return "idle";
  if (["refused", "denied", "failed"].includes(entry.status)) return "error";
  if (entry.effect === "confirmed") return "ok";
  if (entry.effect === "suspected_noop" || entry.effect === "partial") return "caution";
  return "idle";
}

const STATUS = { working: "Working", idle: "Thinking", waiting: "Waiting for you", ended: "Finished", live: "Working" };
/** The run's state in words, with what it is doing when that is known. */
export function statusText(run) {
  if (!run) return "";
  if (run.status === "waiting") {
    return {
      approval: "Waiting for your yes",
      real_input: "Paused: you used the app yourself",
      take_over: "Paused: you have control",
      driver_unavailable: "Paused: the agent desktop can't be watched (is the PC locked?)",
      focus_changed: "Paused: a window tried to take focus",
      action_outcome_unknown: "Paused: checking what the last step did",
      backend_restarted: "Paused after Neyvia restarted",
    }[run.pausedReason] || "Paused: you have control";
  }
  return STATUS[run.status] || "Working";
}

// ---- feedback ---------------------------------------------------------------------

/** A pointer position on the shown frame as 0-1 coordinates, or null outside it. */
export function pointOnFrame(clientX, clientY, rect) {
  if (!rect?.width || !rect?.height) return null;
  const x = (clientX - rect.left) / rect.width;
  const y = (clientY - rect.top) / rect.height;
  if (x < 0 || y < 0 || x > 1 || y > 1) return null;
  return { x: Math.round(x * 10000) / 10000, y: Math.round(y * 10000) / 10000 };
}

/**
 * The comment as sent: bound to the frame version Paul is looking at (live)
 * or a time-lapse keyframe, to the action he picked, and to the point he
 * clicked. The PC keeps that exact picture and delivers the text to the agent.
 */
export function feedbackPayload(args) {
  const payload = rawFeedbackPayload(args);
  const { keyframe, stack, action, point } = args || {};
  return checked("agentview.feedbackPayload", payload === null || ((keyframe ? payload.keyframe === keyframe && !("v" in payload) : !stack?.v || payload.v === stack.v)
    && (!action || payload.action === action) && (!point || (payload.point.x === point.x && payload.point.y === point.y)) && payload.text.length <= 2000), payload);
}
function rawFeedbackPayload({ run, surface, stack, keyframe, action, point, text }) {
  const body = String(text || "").trim();
  if (!run || !body) return null;
  return {
    run, text: body.slice(0, 2000),
    ...(surface ? { surface } : {}),
    ...(keyframe ? { keyframe } : stack?.v ? { v: stack.v } : {}),
    ...(action ? { action } : {}),
    ...(point ? { point: { x: point.x, y: point.y } } : {}),
  };
}

/** "Sent · read by the agent 3 s later" style status for a comment. */
export function deliveryText(row, now = Date.now()) {
  const delivery = row?.delivery || {};
  if (delivery.state === "delivered") {
    if (delivery.channel === "steer") return "Delivered to the running turn";
    return "Read by the agent";
  }
  const waited = Math.max(0, Math.round((now - Date.parse(row?.at || "")) / 1000));
  const next = delivery.channel === "browser" ? "its next browser step" : "its next step";
  return Number.isFinite(waited) && waited > 1 ? `Waiting for ${next} · ${waited}s` : `Waiting for ${next}`;
}

// ---- time-lapse -----------------------------------------------------------------------

export const SPEEDS = [1, 4, 16];
export const IDLE_CAP_MS = 2500; // a silence in the replay lasts at most this long

/**
 * Keyframes and steps on one replay axis. Every gap in recorded time is kept
 * up to IDLE_CAP_MS, so an hour of mostly waiting plays in a minute.
 */
export function buildTimelapse(keyframes = [], entries = [], { idleCap = IDLE_CAP_MS } = {}) {
  const events = [
    ...keyframes.map(row => ({ type: "frame", t: row.t * 1000, row })),
    ...entries.filter(row => row.kind !== "control").map(row => ({ type: "step", t: row.t * 1000, row })),
  ].filter(event => Number.isFinite(event.t)).sort((a, b) => a.t - b.t || (a.type === "frame") - (b.type === "frame"));
  let rt = 0;
  let previous = events[0]?.t ?? 0;
  for (const event of events) {
    rt += Math.min(Math.max(0, event.t - previous), idleCap);
    previous = event.t;
    event.rt = rt;
  }
  const frames = events.filter(event => event.type === "frame");
  const steps = events.filter(event => event.type === "step");
  return { events, frames, steps, duration: rt, startedAt: events[0]?.t ?? null, endedAt: events[events.length - 1]?.t ?? null };
}

const lastAtOrBefore = (list, rt) => {
  let low = 0;
  let high = list.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (list[mid].rt <= rt) low = mid + 1; else high = mid;
  }
  return low ? list[low - 1] : null;
};

/** The picture and the step shown at a replay position. */
export function stateAt(timelapse, rt) {
  const frame = lastAtOrBefore(timelapse.frames, rt) || timelapse.frames[0] || null;
  const step = lastAtOrBefore(timelapse.steps, rt);
  return { frame: frame?.row || null, step: step?.row || null, at: (step && frame ? Math.max(step.t, frame.t) : (step || frame)?.t) ?? null };
}

/** Replay position of a recorded moment (ms), for "jump to" and "where you left". */
export function rtAt(timelapse, t) {
  let rt = 0;
  for (const event of timelapse.events) {
    if (event.t > t) break;
    rt = event.rt;
  }
  return rt;
}

export const SEGMENT_GAP_S = 45;
export const SEGMENT_STEPS = 10;

function joinWords(parts) {
  if (parts.length <= 1) return parts.join("");
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

/** "Typed “17” and “42” into the “Task input” box, clicked the “Apply” button" for a run of steps. */
export function progressText(steps) {
  const actions = steps.filter(step => step.kind === "action");
  const parts = [];
  const groups = new Map();
  for (const step of actions) {
    const key = `${step.tool}|${targetText(step.element)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(step);
  }
  for (const rows of groups.values()) {
    const first = rows[0];
    const target = targetText(first.element);
    if (first.tool === "type_text" || first.tool === "fill" || first.tool === "set_value") {
      const texts = [...new Set(rows.map(row => quote(row.say?.text ?? row.say?.value, 24)))];
      parts.push(`typed ${joinWords(texts.slice(0, 3))}${texts.length > 3 ? ` and ${texts.length - 3} more` : ""} into ${target}`);
    } else if (first.tool === "click" || first.tool === "double_click") {
      parts.push(`clicked ${target}${rows.length > 1 ? ` ${rows.length} times` : ""}`);
    } else if (first.tool === "press_key" || first.tool === "hotkey") {
      parts.push(`pressed ${joinWords([...new Set(rows.map(row => keysText(row.say)))])}`);
    } else if (first.tool === "launch_app" || first.tool === "open" || first.tool === "navigate") {
      parts.push(describeAction(first, "done").replace(/^./, c => c.toLowerCase()));
    } else {
      parts.push(describeAction(first, "done").replace(/^./, c => c.toLowerCase()) + (rows.length > 1 ? ` (${rows.length}×)` : ""));
    }
  }
  const shown = parts.slice(0, 5);
  const more = actions.length - [...groups.values()].slice(0, 5).reduce((sum, rows) => sum + rows.length, 0);
  const text = joinWords(more > 0 ? [...shown, `${more} more ${more === 1 ? "step" : "steps"}`] : shown);
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

/**
 * What progressed, in segments: a new segment starts after a pause of
 * SEGMENT_GAP_S, when the agent moves to another window or page, or every
 * SEGMENT_STEPS steps. Each says what was done, how it checked out, and the
 * keyframes before and after it.
 */
export function buildSegments(entries = [], keyframes = [], surfaces = []) {
  const label = id => surfaces.find(surface => surface.id === id)?.label || "";
  const rows = [...entries].filter(row => row.kind !== "control").sort((a, b) => a.t - b.t);
  const segments = [];
  let current = null;
  for (const row of rows) {
    const actionCount = current ? current.steps.filter(step => step.kind === "action").length : 0;
    const moved = row.kind === "action" && current?.surface && row.surface && row.surface !== current.surface;
    if (!current || row.t - current.end > SEGMENT_GAP_S || moved || actionCount >= SEGMENT_STEPS) {
      current = { start: row.t, end: row.t, surface: row.surface || null, steps: [] };
      segments.push(current);
    }
    current.steps.push(row);
    current.end = row.t;
    if (!current.surface && row.surface) current.surface = row.surface;
  }
  const sorted = [...keyframes].sort((a, b) => a.t - b.t);
  return segments.map((segment, index) => {
    const actions = segment.steps.filter(step => step.kind === "action");
    const checked = actions.filter(step => step.effect === "confirmed").length;
    const failed = actions.filter(step => ["failed", "refused", "denied"].includes(step.status)).length;
    const comments = segment.steps.filter(step => step.kind === "feedback").length;
    const before = [...sorted].reverse().find(row => row.t <= segment.start && (!segment.surface || row.surface === segment.surface)) || sorted.find(row => row.t >= segment.start) || null;
    const after = [...sorted].reverse().find(row => row.t <= segment.end + 3 && (!segment.surface || row.surface === segment.surface)) || before;
    const notes = segment.steps.filter(step => step.kind === "note").map(step => step.summary).filter(Boolean);
    return {
      id: `s${index + 1}`, start: segment.start, end: segment.end, surface: segment.surface, where: label(segment.surface),
      steps: segment.steps.length, actions: actions.length, checked, failed, comments,
      text: progressText(segment.steps) || notes[0] || (comments ? "You left a comment" : "Looked around"),
      before: before?.id || null, after: after?.id || null, first: segment.steps[0],
    };
  });
}

/** What happened since Paul last looked (seconds since epoch), for the "while you were away" banner. */
export function awaySummary(entries = [], lastSeen = 0) {
  const since = entries.filter(row => row.t > lastSeen && row.kind === "action");
  if (!lastSeen || !since.length) return null;
  const span = since[since.length - 1].t - since[0].t;
  return { steps: since.length, from: since[0].t, span, checked: since.filter(row => row.effect === "confirmed").length };
}

/** "3m 05s", "42s", "1h 12m". */
export function spanText(seconds) {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes}m ${String(total % 60).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

/** "1.4 MB". */
export function sizeText(bytes) {
  if (!Number.isFinite(bytes)) return "";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
