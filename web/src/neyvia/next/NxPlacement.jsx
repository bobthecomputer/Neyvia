import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  AppWindow, ArrowLeftRight, BookOpen, Box, BrainCircuit, Columns2, FileText, Folder, GitCompare, Globe, Image, Maximize2, Minimize2, MonitorPlay, NotebookPen, PanelLeft, PanelRight, PictureInPicture2, Settings, Smartphone, SquareTerminal, Bot, Eye, FileCheck2, FlaskConical, Gamepad2, PanelsTopLeft, ScrollText, Sparkles, Hammer, Layers, Mountain, Play, Radar,
} from "lucide-react";

import "./nxPlacement.css";
import { NxStage, stageTitle } from "./NxStage.jsx";
import { Icon, IconButton } from "./nxPrimitives.jsx";
import { os, useOs } from "./nxOsStore.js";
import { useShownTheme } from "./nxSun.js";
import { useApps } from "./nxApps.js";
import { PLACEMENT_LABELS, dropZone } from "./nxPlacementModel.js";
import { COMPACT_PX, SurfaceSize } from "./nxSurfaceSize.js";
import { cachedSkinTokens, skinFor, skinTone } from "./nxAppSkinModel.js";
import "./nxAppSkins.css";

// Every open app or pane is drawn here, once, in one layer keyed by its window
// id (nxPlacementModel). Its place on screen comes from a slot: the area
// beside the chat (<SurfaceSlot name="main">), the side-panel region
// (<SurfaceSlot name="side">), the whole window (full) or the peek next to its
// bubble. Moving a window only changes where it is drawn, never where it sits
// in the tree, so the app keeps its state, scroll, selection and iframes (an
// iframe that is moved in the DOM reloads; this one never moves).

const BUBBLE = 52;
const EDGE = 10;
const START_PX = 6; // movement before a press on the title bar becomes a drag

// ---- slots: where main and side windows are drawn -----------------------------

const slots = new Map();
const slotListeners = new Set();
const slotChanged = () => { for (const listener of slotListeners) listener(); };

/** A placeholder in the layout; the window placed there is drawn over it. */
export function SurfaceSlot({ name, className = "" }) {
  const ref = useCallback(element => {
    if (element) slots.set(name, element);
    else if (slots.get(name) && !slots.get(name).isConnected) slots.delete(name);
    slotChanged();
  }, [name]);
  return <div ref={ref} className={`nx-slot nx-slot-${name}${className ? ` ${className}` : ""}`} data-slot={name} />;
}

const sameRect = (a, b) => (a === b) || (a && b && a.left === b.left && a.top === b.top && a.width === b.width && a.height === b.height && a.float === b.float);

function measure(name) {
  const element = slots.get(name);
  if (!element?.isConnected) return null;
  const box = element.getBoundingClientRect();
  if (box.width < 2 || box.height < 2) return null;
  return { left: Math.round(box.left), top: Math.round(box.top), width: Math.round(box.width), height: Math.round(box.height), float: Boolean(element.closest(".nx-panel-overlay")) };
}

/**
 * The slots' rectangles, kept current: on resize, on any slot or layout
 * change, and for a moment after each change so CSS transitions (the chat
 * docking, a region sliding) are followed to the end.
 */
function useSlotRects(active, version) {
  const [rects, setRects] = useState({ main: null, side: null });
  const update = useCallback(() => {
    setRects(current => {
      const next = { main: measure("main"), side: measure("side") };
      return sameRect(next.main, current.main) && sameRect(next.side, current.side) ? current : next;
    });
  }, []);
  useLayoutEffect(() => {
    if (!active) return undefined;
    update();
    // Follow transitions for a moment after any change.
    let frame = 0;
    const until = performance.now() + 520;
    const tick = () => { update(); if (performance.now() < until) frame = requestAnimationFrame(tick); };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [active, version, update]);
  useEffect(() => {
    if (!active) return undefined;
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    const watch = () => { observer?.disconnect(); observer?.observe(document.documentElement); for (const element of slots.values()) if (element.isConnected) observer?.observe(element); update(); };
    watch();
    slotListeners.add(watch);
    window.addEventListener("resize", update);
    // A region can move without changing size (Arrange, the dock side): a slow check catches it.
    const timer = setInterval(update, 400);
    return () => { observer?.disconnect(); slotListeners.delete(watch); window.removeEventListener("resize", update); clearInterval(timer); };
  }, [active, update]);
  return rects;
}

function useViewport() {
  const [size, setSize] = useState(() => ({ width: window.innerWidth, height: window.innerHeight }));
  useEffect(() => {
    const onResize = () => setSize(current => (current.width === window.innerWidth && current.height === window.innerHeight ? current : { width: window.innerWidth, height: window.innerHeight }));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return size;
}

// ---- what a window looks like as a bubble -----------------------------------------

const APP_ICONS = {
  // The same mark the launcher shows for each app, so a bubble is recognisable at a glance.
  pdf: FileText, notes: NotebookPen, files: Folder, browser: Globe, "mobile-studio": Smartphone, "3d-studio": Box, playtest: Play,
  godot: Gamepad2, unity: Box, roblox: Layers, "asset-checks": Mountain, laya: BrainCircuit, "image-studio": Image, "image-playground": Image, lumaforge: Image,
  research: BookOpen, citecraft: BookOpen, notebook: BookOpen, "ios-studio": Smartphone, preview: AppWindow,
  "app-factory": Hammer, "agent-view": Eye, awareness: Radar, "hill-climb": FlaskConical, "scroll-generator": ScrollText,
};
const PANE_ICONS = { terminal: SquareTerminal, preview: MonitorPlay, browser: Globe, file: FileText, artifact: FileText, diff: GitCompare, settings: Settings, perception: MonitorPlay };
export const windowIcon = desc => (desc?.type === "pane" ? PANE_ICONS[desc.kind] : APP_ICONS[desc?.app]) || AppWindow;

/** Where a bubble's live app shows when it peeks: beside the bubble, or along the bottom on a phone. */
export function peekRect(win, { width, height }, phone) {
  if (phone) {
    const h = Math.min(Math.round(height * 0.62), 560);
    return { left: 8, top: Math.max(8, height - h - 76), width: width - 16, height: h };
  }
  const w = Math.min(560, width - BUBBLE - EDGE * 2 - 40);
  const h = Math.min(560, height - 120);
  const left = win.x < 0.5 ? EDGE + BUBBLE + 12 : width - EDGE - BUBBLE - 12 - w;
  const top = Math.round(Math.min(height - h - 44, Math.max(12, win.y * height - 60)));
  return { left, top, width: w, height: h };
}

export function bubblePoint(win, { width, height }) {
  return { x: win.x < 0.5 ? EDGE : width - BUBBLE - EDGE, y: Math.round(Math.min(height - BUBBLE - 40, Math.max(EDGE, win.y * height - BUBBLE / 2))) };
}

// ---- the placement buttons --------------------------------------------------------

const KEYS_HINT = "Alt+Shift+arrows";

export function PlacementControls({ win, phone, sideOnLeft, title, onPlace = os.placeWindow, onRestore = os.restoreWindow }) {
  const place = (placement, side = null) => onPlace(win.id, placement, side);
  const at = win.placement;
  return (
    <div className="nx-place" role="group" aria-label={`Place ${title}`}>
      {at === "side" && !phone ? (
        <IconButton icon={ArrowLeftRight} size="sm" label={`Move to the ${sideOnLeft ? "right" : "left"} side (${sideOnLeft ? "Alt+Shift+Right" : "Alt+Shift+Left"})`}
          onClick={() => place("side", sideOnLeft ? "right" : "left")} />
      ) : null}
      <IconButton icon={sideOnLeft && !phone ? PanelLeft : PanelRight} size="sm" active={at === "side"}
        label={phone ? "Split the screen" : `${PLACEMENT_LABELS.side} (${sideOnLeft ? "Alt+Shift+Left" : "Alt+Shift+Right"})`} onClick={() => place("side")} />
      <IconButton icon={Columns2} size="sm" active={at === "main"} label={`${PLACEMENT_LABELS.main} (Alt+Shift+Home)`} onClick={() => place("main")} />
      <IconButton icon={at === "full" ? Minimize2 : Maximize2} size="sm" active={at === "full"}
        label={at === "full" ? "Exit full screen (Esc)" : `${PLACEMENT_LABELS.full} (Alt+Shift+Up)`} onClick={() => (at === "full" ? onRestore(win.id) : place("full"))} />
      <IconButton icon={PictureInPicture2} size="sm" active={at === "bubble"} label={`Collapse to a bubble (Alt+Shift+Down)`} onClick={() => place("bubble")} />
    </div>
  );
}

/** Keyboard placement from anywhere inside a window. Returns true when the key was used. */
function placementKey(event, win, sideOnLeft) {
  if (event.defaultPrevented) return false;
  if (event.key === "Escape" && win.placement === "full") { os.restoreWindow(win.id); return true; }
  if (event.key === "Escape" && win.placement === "bubble" && win.peek) { os.peekWindow(win.id, false); focusBubble(win.id); return true; }
  if (!event.altKey || !event.shiftKey) return false;
  const moves = { ArrowLeft: ["side", "left"], ArrowRight: ["side", "right"], ArrowUp: ["full", null], ArrowDown: ["bubble", null], Home: ["main", null] };
  const move = moves[event.key];
  if (!move) return false;
  os.placeWindow(win.id, move[0], move[1] || (move[0] === "side" ? (sideOnLeft ? "left" : "right") : null));
  if (move[0] === "bubble") focusBubble(win.id);
  return true;
}

// Pointer capture keeps a drag going outside the element; a pointer the browser no longer tracks can't be captured.
const capture = event => { try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* the drag still works over the element */ } };
const focusBubble = id => requestAnimationFrame(() => document.querySelector(`[data-bubble-for="${CSS.escape(id)}"]`)?.focus());
const focusWindow = id => requestAnimationFrame(() => document.querySelector(`[data-window="${CSS.escape(id)}"] .nx-stage-head button`)?.focus());

// ---- drag a window by its title bar to another place -------------------------------

function useWindowDrag(win, title, onDrop, onDrag) {
  const press = useRef(null);
  const [drag, setDragState] = useState(null); // { x, y, zone }
  // The drop zones are drawn once by the layer (outside every window, so nothing clips them).
  const setDrag = useCallback(next => { setDragState(next); onDrag(next ? { ...next, title } : null); }, [onDrag, title]);
  const cancel = useCallback(() => { press.current = null; setDrag(null); }, [setDrag]);
  useEffect(() => {
    if (!drag) return undefined;
    const onKey = event => { if (event.key === "Escape") { event.preventDefault(); cancel(); } };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [drag, cancel]);
  const onPointerDown = event => {
    if (event.button !== 0 || event.target.closest("button, a, input, textarea, select, [role=tab]")) return;
    press.current = { x0: event.clientX, y0: event.clientY, id: event.pointerId };
    capture(event);
  };
  const onPointerMove = event => {
    const current = press.current;
    if (!current || current.id !== event.pointerId) return;
    if (!drag && Math.hypot(event.clientX - current.x0, event.clientY - current.y0) < START_PX) return;
    setDrag({ x: event.clientX, y: event.clientY, zone: dropZone({ x: event.clientX, y: event.clientY }, window.innerWidth, window.innerHeight) });
  };
  const onPointerUp = event => {
    const current = press.current;
    press.current = null;
    if (!current || !drag) { setDrag(null); return; }
    setDrag(null);
    onDrop(dropZone({ x: event.clientX, y: event.clientY }, window.innerWidth, window.innerHeight));
  };
  return { drag, handlers: { onPointerDown, onPointerMove, onPointerUp, onPointerCancel: cancel, title: `Drag to move ${win.placement === "full" ? "out of full screen" : "this window"}: sides, full screen (top) or a bubble (bottom)` } };
}

const ZONES = [
  { key: "side-left", placement: "side", side: "left", label: "Left side" },
  { key: "full", placement: "full", side: null, label: "Full screen" },
  { key: "main", placement: "main", side: null, label: "Beside the chat" },
  { key: "bubble", placement: "bubble", side: null, label: "Bubble" },
  { key: "side-right", placement: "side", side: "right", label: "Right side" },
];

function DropZones({ drag }) {
  if (!drag) return null;
  const { title } = drag;
  const over = drag.zone.placement === "side" ? `side-${drag.zone.side}` : drag.zone.placement;
  return (
    <div className="nx-dropzones" aria-hidden="true">
      {ZONES.map(zone => (
        <div key={zone.key} className={`nx-dropzone is-${zone.key}${over === zone.key ? " is-over" : ""}`}><span>{zone.label}</span></div>
      ))}
      <div className="nx-drop-ghost" style={{ transform: `translate3d(${drag.x + 14}px, ${drag.y + 10}px, 0)` }}>{title}</div>
    </div>
  );
}

// ---- one window ----------------------------------------------------------------

// Memoised: a drag re-renders the layer on every pointer move, never the apps inside the windows.
const SurfaceWindow = memo(function SurfaceWindow({ win, rect, phone, viewport, sideOnLeft, shell, onDrag, leaving = false }) {
  const { suites } = useApps();
  const title = stageTitle(win.desc, suites);
  const frame = useRef(null);
  // How the window gets to its new place (Paul: "windows morph between placements instead of
  // jumping"). move = it glides from its old box to the new one on a spring; fold = it shrinks into
  // its bubble and fades; unfold = it grows back out of the bubble into its place. Reduced motion:
  // none of them (CSS), the window is simply where it belongs.
  const peeking = win.placement === "bubble" && win.peek;
  const folded = win.placement === "bubble" && !peeking;
  const [motion, setMotion] = useState(null);
  const last = useRef({ placement: win.placement, folded });
  useLayoutEffect(() => {
    const before = last.current;
    if (before.placement === win.placement && before.folded === folded) return undefined;
    last.current = { placement: win.placement, folded };
    setMotion(folded && !before.folded ? "fold" : before.folded && !folded ? "unfold" : "move");
    const timer = setTimeout(() => setMotion(null), 340);
    return () => clearTimeout(timer);
  }, [win.placement, folded]);

  // A window fades in when it opens and out when it closes, so one app replacing another crossfades.
  const [entering, setEntering] = useState(true);
  useEffect(() => { const timer = setTimeout(() => setEntering(false), 300); return () => clearTimeout(timer); }, []);

  const onDrop = useCallback(zone => {
    if (zone.placement === win.placement && (zone.placement !== "side" || (zone.side === "left") === sideOnLeft)) return;
    os.placeWindow(win.id, zone.placement, zone.side);
    if (zone.placement === "bubble") focusBubble(win.id);
  }, [win.id, win.placement, sideOnLeft]);
  const { drag, handlers } = useWindowDrag(win, title, onDrop, onDrag);

  // Where it is drawn. While a slot is being measured (a region appearing), it stays where it was
  // and glides on from there, rather than starting from a corner.
  const lastBox = useRef(null);
  const target = win.placement === "full" ? { left: 0, top: 0, width: viewport.width, height: viewport.height }
    : win.placement === "bubble" ? peekRect(win, viewport, phone)
      : rect;
  const box = (motion === "fold" && lastBox.current) || target || lastBox.current;
  useLayoutEffect(() => { if (target && !(win.placement === "bubble" && !peeking)) lastBox.current = target; });
  const hidden = !box || (folded && motion !== "fold");
  // The bubble's point relative to the box: the fold ends there and the unfold starts there.
  const dot = bubblePoint(win, viewport);
  const toward = box ? { "--nx-fold-x": `${dot.x - box.left}px`, "--nx-fold-y": `${dot.y - box.top}px`, "--nx-fold-s": Math.max(0.05, BUBBLE / Math.max(1, box.width)) } : null;
  // The app's own look (nxAppSkinModel): the window wears its skin; the shell around it keeps the theme.
  const theme = useShownTheme();
  const skin = useMemo(() => skinFor(win.desc), [win.desc]);
  const skinStyle = skin ? cachedSkinTokens(skin, theme) : null;
  const place = box ? { left: box.left, top: box.top, width: box.width, height: box.height } : { left: 0, top: 0, width: 1, height: 1 };
  const motionStyle = (motion === "fold" || motion === "unfold") && toward ? { ...place, ...toward } : place;
  const style = skinStyle ? { ...skinStyle, ...motionStyle } : motionStyle;
  const width = box?.width || 0;
  const height = box?.height || 0;
  const size = useMemo(() => ({ width, height, compact: width > 0 && width < COMPACT_PX, placement: win.placement }), [width, height, win.placement]);
  const className = ["nx-surface", `is-${win.placement}`, hidden ? "is-hidden" : "", motion ? `is-${motion === "move" ? "moving" : motion === "fold" ? "folding" : "unfolding"}` : "", drag ? "is-dragged" : "",
    leaving ? "is-leaving" : entering && !hidden ? "is-entering" : "",
    win.placement === "side" && rect?.float ? "is-floating" : "", win.placement === "side" ? (sideOnLeft ? "is-left" : "is-right") : ""].filter(Boolean).join(" ");
  return (
    <div ref={frame} className={className} style={style} data-window={win.id} data-placement={win.placement} data-compact={size.compact || undefined}
      data-nx-skin={skin || undefined} data-nx-skin-tone={skin ? skinTone(theme) : undefined} inert={hidden || folded || leaving || undefined}
      aria-hidden={hidden || folded || leaving || undefined} onKeyDown={event => { if (placementKey(event, win, sideOnLeft)) { event.preventDefault(); event.stopPropagation(); } }}>
      <SurfaceSize.Provider value={size}>
      <NxStage stage={win.desc} session={shell.session} phone={phone} nav={shell.nav} placement={win.placement}
        chatDocked={shell.chatDocked} onToggleChat={win.placement === "main" ? shell.onToggleChat : null}
        onClose={() => os.closeWindow(win.id)} headProps={handlers}
        controls={<PlacementControls win={win} phone={phone} sideOnLeft={sideOnLeft} title={title} />} />
      </SurfaceSize.Provider>
    </div>
  );
});

// ---- a window as a bubble ----------------------------------------------------------

function WindowBubble({ win, viewport, title }) {
  const drag = useRef(null);
  const [dragAt, setDragAt] = useState(null);
  const place = dragAt || bubblePoint(win, viewport);
  const Glyph = windowIcon(win.desc);
  const onPointerDown = event => {
    if (event.button !== 0) return;
    capture(event);
    drag.current = { dx: event.clientX - place.x, dy: event.clientY - place.y, moved: false, x0: event.clientX, y0: event.clientY };
  };
  const onPointerMove = event => {
    if (!drag.current) return;
    if (!drag.current.moved && Math.hypot(event.clientX - drag.current.x0, event.clientY - drag.current.y0) < 5) return;
    drag.current.moved = true;
    setDragAt({ x: event.clientX - drag.current.dx, y: event.clientY - drag.current.dy });
  };
  const onPointerUp = event => {
    const current = drag.current;
    drag.current = null;
    if (!current) return;
    if (!current.moved) { os.peekWindow(win.id); return; }
    os.moveWindowBubble(win.id, event.clientX < viewport.width / 2 ? 0 : 1, (event.clientY - current.dy + BUBBLE / 2) / viewport.height);
    setDragAt(null);
  };
  const onKeyDown = event => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); os.peekWindow(win.id); }
    else if (event.key === "r" || event.key === "R") { event.preventDefault(); os.restoreWindow(win.id); focusWindow(win.id); }
    else if (event.key === "Delete") { event.preventDefault(); os.closeWindow(win.id); }
    else if (event.key === "ArrowUp" || event.key === "ArrowDown") { event.preventDefault(); os.moveWindowBubble(win.id, win.x, win.y + (event.key === "ArrowUp" ? -0.06 : 0.06)); }
    else if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); os.moveWindowBubble(win.id, event.key === "ArrowLeft" ? 0 : 1, win.y); }
    else if (event.key === "Escape" && win.peek) { event.preventDefault(); os.peekWindow(win.id, false); }
  };
  const label = `${title}, in a bubble. Enter shows it, R puts it back, Delete closes it, arrows move it.`;
  return (
    <div className="nx-wbubble-wrap" style={{ transform: `translate3d(${place.x}px, ${place.y}px, 0)` }}>
      <button type="button" data-bubble-for={win.id} className={`nx-wbubble${dragAt ? " is-dragging" : ""}${win.peek ? " is-open" : ""}`}
        aria-label={label} title={title} aria-expanded={win.peek}
        onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
        onPointerCancel={() => { drag.current = null; setDragAt(null); }} onKeyDown={onKeyDown}>
        <Icon as={Glyph} size={22} />
      </button>
      <span className={`nx-wbubble-name${win.x < 0.5 ? " is-left" : ""}`} aria-hidden="true">{title}</span>
    </div>
  );
}

// ---- the layer ----------------------------------------------------------------------

/**
 * All windows. `shell` carries what NxShell owns: the open chat, navigation,
 * and whether the chat is docked beside the main window.
 */
export function NxSurfaces({ phone, shell }) {
  const windows = useOs(state => state.windows);
  const layout = useOs(state => state.layout);
  const { suites } = useApps();
  const viewport = useViewport();
  const [dragging, setDragging] = useState(null);
  const sideOnLeft = layout.order.indexOf("panel") < layout.order.indexOf("main");
  const placed = windows.some(win => win.placement === "main" || win.placement === "side");
  // Re-measure after any change of windows, layout or chat docking.
  const version = useMemo(() => `${windows.map(win => `${win.id}=${win.placement}`).join(",")}|${layout.order.join(",")}|${layout.dock}|${shell.chatDocked}|${phone}`, [windows, layout, shell.chatDocked, phone]);
  const rects = useSlotRects(placed, version);
  // Windows that just closed stay drawn for a moment while they fade (the same instance: nothing remounts).
  const [leaving, setLeaving] = useState([]);
  const before = useRef(windows);
  useLayoutEffect(() => {
    const gone = before.current.filter(win => win.placement !== "bubble" && !windows.some(next => next.id === win.id));
    before.current = windows;
    if (!gone.length || globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches || document.querySelector(".nx")?.dataset.nxMotion === "reduce") return undefined;
    setLeaving(current => [...current.filter(row => !gone.some(win => win.id === row.win.id)), ...gone.map(win => ({ win, rect: win.placement === "side" ? rects.side : rects.main }))]);
    const timer = setTimeout(() => setLeaving(current => current.filter(row => !gone.some(win => win.id === row.win.id))), 240);
    return () => clearTimeout(timer);
  }, [windows]); // eslint-disable-line react-hooks/exhaustive-deps
  // Clicking outside a peeking bubble's window tucks it away again.
  const peeking = windows.find(win => win.placement === "bubble" && win.peek);
  useEffect(() => {
    if (!peeking) return undefined;
    const onDown = event => {
      if (event.target.closest?.(`[data-window="${CSS.escape(peeking.id)}"], [data-bubble-for="${CSS.escape(peeking.id)}"], .nx-portal-host`)) return;
      os.peekWindow(peeking.id, false);
    };
    document.addEventListener("pointerdown", onDown, true);
    return () => document.removeEventListener("pointerdown", onDown, true);
  }, [peeking]);
  if (!windows.length && !leaving.length) return null;
  const bubbles = windows.filter(win => win.placement === "bubble");
  return (
    <>
      {/* One stable list: a window's position in this list never depends on its placement. */}
      <div className="nx-surfaces">
        {/* One keyed list, so a closing window keeps its instance (and its app) while it fades. */}
        {[
          ...windows.map(win => (
            <SurfaceWindow key={win.id} win={win} rect={win.placement === "main" ? rects.main : win.placement === "side" ? rects.side : null}
              phone={phone} viewport={viewport} sideOnLeft={sideOnLeft} shell={shell} onDrag={setDragging} />
          )),
          ...leaving.filter(row => !windows.some(win => win.id === row.win.id)).map(row => (
            <SurfaceWindow key={row.win.id} win={row.win} rect={row.rect} phone={phone} viewport={viewport} sideOnLeft={sideOnLeft} shell={shell} onDrag={setDragging} leaving />
          )),
        ]}
      </div>
      <DropZones drag={dragging} />
      {bubbles.length ? (
        <div className="nx-wbubbles" aria-label="Apps in bubbles">
          {bubbles.map(win => <WindowBubble key={win.id} win={win} viewport={viewport} title={stageTitle(win.desc, suites)} />)}
        </div>
      ) : null}
    </>
  );
}
