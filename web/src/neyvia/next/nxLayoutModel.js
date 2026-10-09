import { checkedProofsEModel } from "./nxProofsEContracts.js";
// The movable layout (07 §2 "Grove: windows and panels can be arranged"),
// for every density: the user orders the shell's regions, drags their widths,
// picks which side the chat docks on, and arranges the home widgets. Pure
// functions only; nxOsStore keeps the state and NxShell renders it.
//
// "Adapts automatically": the saved layout is what the user wants; `fitLayout`
// is what fits the window right now. Narrow windows shrink the side regions
// together, keeping the conversation comfortable; then Canopy gives way; then
// the conversation goes down to its minimum; then the side panel floats over it. The saved layout is never rewritten
// by a resize, so widening the window brings everything back.

export const REGIONS = ["sidebar", "main", "panel", "canopy"];
export const REGION_LABELS = { sidebar: "Chats", main: "Conversation", panel: "Side panel", canopy: "Canopy" };
export const LIMITS = { sidebar: [220, 440], panel: [300, 600], canopy: [240, 440], dock: [300, 680] };
export const MAIN_MIN = 440;
export const MAIN_COMFORT = 640; // what the conversation keeps before Canopy gives way
const STEP = 16;

export const WIDGETS = {
  continue: { title: "Continue", sizes: ["m", "l"] },
  needs: { title: "Needs you", sizes: ["s", "m", "l"] },
  running: { title: "Running", sizes: ["s", "m", "l"] },
  nightshift: { title: "Night Shift", sizes: ["s", "m"] },
  projects: { title: "Projects", sizes: ["s", "m", "l"] },
  usage: { title: "Usage", sizes: ["s", "m"] },
};
export const WIDGET_SPAN = { s: 1, m: 2, l: 4 };
const SIZE_LABELS = { s: "Small", m: "Medium", l: "Large" };
export const sizeLabel = size => SIZE_LABELS[size] || size;

export const DEFAULT_LAYOUT = Object.freeze({
  order: ["sidebar", "main", "panel", "canopy"],
  widths: {},
  canopy: "auto", // auto: with Grove; on: always (when there's room); off
  dock: "right", // where the chat docks while an app fills the stage
  sidebarHidden: false,
  widgets: [
    { id: "continue", size: "l" },
    { id: "needs", size: "m" },
    { id: "running", size: "m" },
    { id: "nightshift", size: "s" },
    { id: "usage", size: "s" },
    { id: "projects", size: "m" },
  ],
});

export const clampWidth = (id, px) => {
  const [min, max] = LIMITS[id] || [0, Infinity];
  return Math.round(Math.min(max, Math.max(min, Number(px) || min)));
};

/** Validate anything read from storage or sent by the bus into a usable layout. */
function raw_normalizeLayout(saved) {
  const source = saved && typeof saved === "object" ? saved : {};
  const order = Array.isArray(source.order) ? source.order.filter((id, index, list) => REGIONS.includes(id) && list.indexOf(id) === index) : [];
  for (const id of DEFAULT_LAYOUT.order) if (!order.includes(id)) order.splice(id === "sidebar" ? 0 : order.length, 0, id);
  const widths = {};
  for (const [id, px] of Object.entries(source.widths || {})) if (LIMITS[id] && Number.isFinite(Number(px))) widths[id] = clampWidth(id, px);
  const seen = new Set();
  const widgets = (Array.isArray(source.widgets) ? source.widgets : DEFAULT_LAYOUT.widgets)
    .filter(widget => widget && WIDGETS[widget.id] && !seen.has(widget.id) && seen.add(widget.id))
    .map(widget => ({ id: widget.id, size: WIDGETS[widget.id].sizes.includes(widget.size) ? widget.size : WIDGETS[widget.id].sizes[0] }));
  return {
    order,
    widths,
    canopy: ["auto", "on", "off"].includes(source.canopy) ? source.canopy : "auto",
    dock: source.dock === "left" ? "left" : "right",
    sidebarHidden: source.sidebarHidden === true,
    widgets,
  };
}

const move = (list, from, to) => {
  if (from < 0 || from === to) return list;
  const next = [...list];
  const [item] = next.splice(from, 1);
  next.splice(Math.max(0, Math.min(next.length, to)), 0, item);
  return next;
};

const raw_moveRegion = (layout, id, to) => ({ ...layout, order: move(layout.order, layout.order.indexOf(id), to) });
const raw_nudgeRegion = (layout, id, delta) => moveRegion(layout, id, layout.order.indexOf(id) + delta);
export const setRegionOrder = (layout, order) => normalizeLayout({ ...layout, order });

function raw_setWidth(layout, id, px) {
  return { ...layout, widths: { ...layout.widths, [id]: clampWidth(id, px) } };
}
export function resetWidth(layout, id) {
  const widths = { ...layout.widths };
  delete widths[id];
  return { ...layout, widths };
}
/** Keyboard resizing: arrows step 16 px (48 with Shift), Home/End jump to the limits. */
function raw_keyWidth(id, current, key, shift = false) {
  const [min, max] = LIMITS[id];
  if (key === "Home") return min;
  if (key === "End") return max;
  const step = shift ? STEP * 3 : STEP;
  if (key === "ArrowLeft") return clampWidth(id, current - step);
  if (key === "ArrowRight") return clampWidth(id, current + step);
  return null;
}

/** Which side of the conversation a region sits on; its splitter is on the edge facing it. */
function raw_sideOf(order, id) {
  return order.indexOf(id) < order.indexOf("main") ? "start" : "end";
}

/**
 * What fits now. `present` says which side regions want to show (the shell's
 * own rules: phone, density, an open chat...), `defaults` are the density's
 * widths. Returns the widths to use, which regions had to go, and whether the
 * side panel should float over the chat instead of taking a column.
 */
function raw_fitLayout(layout, { viewport, present, defaults }) {
  const wanted = ["sidebar", "panel", "canopy"].filter(id => present[id]);
  const attempt = (shown, floatPanel, mainWidth) => {
    const widths = {};
    for (const id of ["sidebar", "panel", "canopy", "dock"]) widths[id] = clampWidth(id, layout.widths[id] ?? defaults[id]);
    const columns = shown.filter(id => !(id === "panel" && floatPanel));
    const over = columns.reduce((sum, id) => sum + widths[id], 0) + mainWidth - viewport;
    const slack = columns.reduce((sum, id) => sum + widths[id] - LIMITS[id][0], 0);
    // Every column gives in proportion to what it has above its minimum.
    if (over > 0 && slack > 0) for (const id of columns) widths[id] -= Math.ceil(Math.min(over, slack) * (widths[id] - LIMITS[id][0]) / slack);
    return { widths, shown, floatPanel, fits: over <= slack };
  };
  // The conversation comes first: keep it comfortable before keeping Canopy,
  // then let it go down to its minimum, then float the panel over it.
  const withoutCanopy = wanted.filter(id => id !== "canopy");
  const tries = [attempt(wanted, false, MAIN_COMFORT), attempt(withoutCanopy, false, MAIN_COMFORT),
    attempt(withoutCanopy, false, MAIN_MIN), attempt(withoutCanopy, wanted.includes("panel"), MAIN_MIN)];
  const chosen = tries.find(result => result.fits) || tries[tries.length - 1];
  return {
    widths: chosen.widths,
    show: Object.fromEntries(["sidebar", "panel", "canopy"].map(id => [id, chosen.shown.includes(id)])),
    dropped: wanted.filter(id => !chosen.shown.includes(id)),
    floatPanel: chosen.floatPanel,
  };
}

// ---- home widgets -----------------------------------------------------------

function raw_moveWidget(layout, id, toId) {
  const from = layout.widgets.findIndex(widget => widget.id === id);
  const to = layout.widgets.findIndex(widget => widget.id === toId);
  if (from < 0 || to < 0) return layout;
  return { ...layout, widgets: move(layout.widgets, from, to) };
}
function raw_nudgeWidget(layout, id, delta) {
  const from = layout.widgets.findIndex(widget => widget.id === id);
  return from < 0 ? layout : { ...layout, widgets: move(layout.widgets, from, from + delta) };
}
/** Next size in the widget's own list, wrapping: S → M → L → S. */
function raw_cycleWidgetSize(layout, id) {
  return {
    ...layout,
    widgets: layout.widgets.map(widget => {
      if (widget.id !== id) return widget;
      const sizes = WIDGETS[id].sizes;
      return { ...widget, size: sizes[(sizes.indexOf(widget.size) + 1) % sizes.length] };
    }),
  };
}
const raw_removeWidget = (layout, id) => ({ ...layout, widgets: layout.widgets.filter(widget => widget.id !== id) });
function raw_addWidget(layout, id) {
  if (!WIDGETS[id] || layout.widgets.some(widget => widget.id === id)) return layout;
  return { ...layout, widgets: [...layout.widgets, { id, size: WIDGETS[id].sizes[0] }] };
}
const raw_hiddenWidgets = layout => Object.keys(WIDGETS).filter(id => !layout.widgets.some(widget => widget.id === id));

// ---- scenes ---------------------------------------------------------------
// One tap switches the whole setup, like a phone's modes: density, which
// regions show, Canopy, dock side and theme. Built-ins can't be overwritten;
// saved scenes keep the user's own arrangement under a name.

export const BUILTIN_SCENES = {
  focus: { label: "Focus", hint: "Just the conversation", density: "calm", layout: { sidebarHidden: true, canopy: "off" } },
  workshop: { label: "Workshop", hint: "Chats, conversation and tools", density: "workshop", layout: { sidebarHidden: false, canopy: "auto" } },
  cockpit: { label: "Cockpit", hint: "Every agent in view", density: "grove", layout: { sidebarHidden: false, canopy: "on" } },
};
const SCENE_NAME = /^[\p{L}\p{N}][\p{L}\p{N} _-]{0,31}$/u;

export const sceneId = name => String(name || "").trim().toLowerCase().replace(/\s+/g, "-");

/** A scene from what's on screen now, ready to save. */
export function captureScene(name, { density, theme, layout }) {
  const label = String(name || "").trim();
  if (!SCENE_NAME.test(label)) throw new Error("A scene name is 1–32 letters, digits, spaces, - or _");
  if (BUILTIN_SCENES[sceneId(label)]) throw new Error(`${label} is a built-in scene; choose another name`);
  return { label, density, theme, layout: normalizeLayout(layout) };
}

/** Apply a scene onto the current state; fields a scene doesn't name stay as they are. */
export function applyScene(current, scene) {
  if (!scene) throw new Error("Unknown scene");
  return {
    density: scene.density || current.density,
    theme: scene.theme || current.theme,
    layout: normalizeLayout({ ...current.layout, ...scene.layout }),
  };
}

// Public observers check the executable manual claims on every invocation.
export function normalizeLayout(...args) { return checkedProofsEModel("layout.normalizeLayout", args, raw_normalizeLayout(...args)); }
export function moveRegion(...args) { return checkedProofsEModel("layout.moveRegion", args, raw_moveRegion(...args)); }
export function nudgeRegion(...args) { return checkedProofsEModel("layout.nudgeRegion", args, raw_nudgeRegion(...args)); }
export function setWidth(...args) { return checkedProofsEModel("layout.setWidth", args, raw_setWidth(...args)); }
export function keyWidth(...args) { return checkedProofsEModel("layout.keyWidth", args, raw_keyWidth(...args)); }
export function sideOf(...args) { return checkedProofsEModel("layout.sideOf", args, raw_sideOf(...args)); }
export function fitLayout(...args) { return checkedProofsEModel("layout.fitLayout", args, raw_fitLayout(...args)); }
export function moveWidget(...args) { return checkedProofsEModel("layout.moveWidget", args, raw_moveWidget(...args)); }
export function nudgeWidget(...args) { return checkedProofsEModel("layout.nudgeWidget", args, raw_nudgeWidget(...args)); }
export function cycleWidgetSize(...args) { return checkedProofsEModel("layout.cycleWidgetSize", args, raw_cycleWidgetSize(...args)); }
export function removeWidget(...args) { return checkedProofsEModel("layout.removeWidget", args, raw_removeWidget(...args)); }
export function addWidget(...args) { return checkedProofsEModel("layout.addWidget", args, raw_addWidget(...args)); }
export function hiddenWidgets(...args) { return checkedProofsEModel("layout.hiddenWidgets", args, raw_hiddenWidgets(...args)); }
