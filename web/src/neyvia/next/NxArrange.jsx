import { useEffect, useRef, useState } from "react";
import { Check, GripVertical, Move, RotateCcw, Save, X } from "lucide-react";
import { DndContext, KeyboardSensor, PointerSensor, closestCenter, useSensor, useSensors } from "@dnd-kit/core";
import { SortableContext, horizontalListSortingStrategy, sortableKeyboardCoordinates, useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import "./nxArrange.css";

import { Button, Icon, Segmented } from "./nxPrimitives.jsx";
import { os, useOs } from "./nxOsStore.js";
import { ConfirmInPlace } from "./details/nxDetails.jsx";
import { BUILTIN_SCENES, LIMITS, REGION_LABELS, keyWidth, moveRegion, nudgeRegion } from "./nxLayoutModel.js";

// Everything movable (07 §2, Paul's HyperOS reference): each side region of
// the shell sits in a <Region> with a splitter on the edge that faces the
// conversation, and Arrange mode adds a bar to reorder regions, choose the
// chat's dock side and show Canopy. Home widgets join the same mode
// (NxHomeWidgets). Layout state lives in nxOsStore; rules in nxLayoutModel.

export const WIDTH_VARS = { sidebar: "--nx-sidebar-w", panel: "--nx-panel-w", canopy: "--nx-canopy-w", dock: "--nx-dock-w" };

export function useViewportWidth() {
  const [width, setWidth] = useState(() => (typeof window === "undefined" ? 1440 : window.innerWidth));
  useEffect(() => {
    // Watching the root element catches every way the viewport changes size (window
    // resize, zoom, device emulation); React skips equal widths.
    const onResize = () => setWidth(window.innerWidth);
    onResize();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(onResize);
    observer?.observe(document.documentElement);
    window.addEventListener("resize", onResize);
    return () => { observer?.disconnect(); window.removeEventListener("resize", onResize); };
  }, []);
  return width;
}

/**
 * Drag (or arrow keys) to resize one region. `side` is where the region sits
 * relative to the conversation: "start" puts the handle on its right edge.
 * While dragging only a CSS variable changes; the width is saved on release.
 */
export function Splitter({ id, label, side, width, live, onCommit, onReset }) {
  const [min, max] = LIMITS[id];
  const grow = side === "start" ? 1 : -1;
  const drag = useRef(null);
  const latest = useRef(width); // keys that repeat faster than a render build on each other
  const [dragging, setDragging] = useState(false);
  useEffect(() => { latest.current = width; }, [width]);

  const onPointerDown = event => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, start: width, now: width };
    setDragging(true);
  };
  const onPointerMove = event => {
    if (!drag.current) return;
    const next = Math.round(Math.min(max, Math.max(min, drag.current.start + grow * (event.clientX - drag.current.x))));
    if (next !== drag.current.now) { drag.current.now = next; latest.current = next; live(next); }
  };
  const finish = () => {
    if (!drag.current) return;
    const { now, start } = drag.current;
    drag.current = null;
    setDragging(false);
    if (now !== start) onCommit(now);
  };
  const onKeyDown = event => {
    // Arrows follow the screen: on a right-hand region, ArrowLeft makes it wider.
    const key = side === "end" && event.key.startsWith("Arrow") ? (event.key === "ArrowLeft" ? "ArrowRight" : "ArrowLeft") : event.key;
    const next = keyWidth(id, latest.current, key, event.shiftKey);
    if (next == null) return;
    event.preventDefault();
    latest.current = next;
    live(next);
    onCommit(next);
  };

  return (
    <div role="separator" aria-orientation="vertical" aria-label={`Resize ${label}`} tabIndex={0}
      aria-valuenow={width} aria-valuemin={min} aria-valuemax={max} aria-valuetext={`${width} pixels wide`}
      title={`Drag to resize ${label} · double-click to reset`}
      className={`nx-splitter is-${side}${dragging ? " is-dragging" : ""}`}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={finish} onPointerCancel={finish}
      onLostPointerCapture={finish} onDoubleClick={onReset} onKeyDown={onKeyDown} />
  );
}

/** One region of the shell row, in the user's order, with its resize handle. */
/** `landmark` ({ role, label }) makes the region itself the landmark, so its splitter is inside it too. */
export function Region({ id, order, side, children, splitter = null, className = "", landmark = null }) {
  return (
    <div className={`nx-region nx-region-${id}${className ? ` ${className}` : ""}`} data-region={id} data-side={side}
      role={landmark?.role} aria-label={landmark?.label}
      data-label={REGION_LABELS[id]} style={{ order }}>
      {children}
      {splitter}
    </div>
  );
}

function RegionChip({ id, showing }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });
  return (
    <button ref={setNodeRef} type="button" {...attributes} {...listeners}
      className={`nx-arrange-chip${id === "main" ? " is-main" : ""}${showing ? "" : " is-off"}${isDragging ? " is-dragging" : ""}`}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      aria-roledescription="movable region" aria-label={`${REGION_LABELS[id]}${showing ? "" : ", not showing right now"}`}
      title={showing ? "Drag to move" : "Not showing right now: it takes this place when it opens"}>
      <Icon as={GripVertical} size={12} />
      <span>{REGION_LABELS[id]}</span>
    </button>
  );
}

const CANOPY_OPTIONS = [{ value: "auto", label: "With Grove" }, { value: "on", label: "Always" }, { value: "off", label: "Off" }];
const DOCK_OPTIONS = [{ value: "left", label: "Left" }, { value: "right", label: "Right" }];

const announce = id => REGION_LABELS[id] || id;
const ANNOUNCEMENTS = {
  onDragStart: ({ active }) => `Picked up ${announce(active.id)}.`,
  onDragOver: ({ active, over }) => (over ? `${announce(active.id)} is over ${announce(over.id)}.` : `${announce(active.id)} is no longer over a place.`),
  onDragEnd: ({ active, over }) => (over ? `${announce(active.id)} dropped at ${announce(over.id)}.` : `${announce(active.id)} dropped.`),
  onDragCancel: ({ active }) => `Moving ${announce(active.id)} was cancelled.`,
};

/** Scenes: one tap for a whole setup; save the current one under a name. */
function Scenes() {
  const saved = useOs(state => state.scenes);
  const [naming, setNaming] = useState(null);
  const save = event => {
    event.preventDefault();
    if (naming?.trim()) os.saveScene(naming.trim());
    setNaming(null);
  };
  return (
    <span className="nx-arrange-scenes" role="group" aria-label="Scenes">
      {Object.entries(BUILTIN_SCENES).map(([id, scene]) => (
        <button key={id} type="button" className="nx-arrange-scene" title={scene.hint} onClick={() => os.scene(id)}>{scene.label}</button>
      ))}
      {Object.entries(saved).map(([id, scene]) => (
        // A saved scene can't be brought back, so Delete asks right there first (details library).
        <ConfirmInPlace key={id} question={`Delete ${scene.label}?`} confirmLabel="Delete" doneText={`Scene ${scene.label} deleted`}
          onConfirm={() => os.deleteScene(id)}>
          {ask => (
            <span className="nx-arrange-scene is-saved">
              <button type="button" onClick={() => os.scene(id)} title="Saved scene">{scene.label}</button>
              <button type="button" className="nx-arrange-scene-x" aria-label={`Delete scene ${scene.label}`} onClick={ask}><Icon as={X} size={11} /></button>
            </span>
          )}
        </ConfirmInPlace>
      ))}
      {naming === null ? (
        <button type="button" className="nx-arrange-scene is-save" onClick={() => setNaming("")}><Icon as={Save} size={12} />Save as scene</button>
      ) : (
        <form className="nx-arrange-scene-form" onSubmit={save}>
          <input autoFocus value={naming} maxLength={32} placeholder="Scene name" aria-label="Scene name"
            onChange={event => setNaming(event.target.value)} onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); setNaming(null); } }} />
        </form>
      )}
    </span>
  );
}

/** The Arrange bar: scenes, reorder regions, Canopy, dock side, reset, done. */
export function ArrangeBar({ showing }) {
  const layout = useOs(state => state.layout);
  const dragging = useRef(false);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 3 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  useEffect(() => {
    const onKey = event => { if (event.key === "Escape" && !dragging.current && !event.defaultPrevented) os.arrange(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const onDragEnd = ({ active, over }) => {
    dragging.current = false;
    if (over && active.id !== over.id) os.updateLayout(current => {
      const target = current.order.indexOf(over.id);
      const delta = target - current.order.indexOf(active.id);
      return Math.abs(delta) === 1 ? nudgeRegion(current, active.id, delta) : moveRegion(current, active.id, target);
    });
  };

  return (
    <div className="nx-arrange-bar" role="toolbar" aria-label="Arrange the layout">
      <span className="nx-arrange-title"><Icon as={Move} size={14} />Arrange</span>
      <Scenes />
      <DndContext sensors={sensors} collisionDetection={closestCenter} accessibility={{ announcements: ANNOUNCEMENTS }}
        onDragStart={() => { dragging.current = true; }} onDragCancel={() => { dragging.current = false; }} onDragEnd={onDragEnd}>
        <SortableContext items={layout.order} strategy={horizontalListSortingStrategy}>
          <div className="nx-arrange-map" aria-label="Regions, left to right">
            {layout.order.map(id => <RegionChip key={id} id={id} showing={id === "main" || showing[id]} />)}
          </div>
        </SortableContext>
      </DndContext>
      <label className="nx-arrange-field"><span>Canopy</span>
        <Segmented size="sm" label="Canopy" value={layout.canopy} options={CANOPY_OPTIONS}
          onChange={canopy => os.updateLayout(current => ({ ...current, canopy }))} />
      </label>
      <label className="nx-arrange-field"><span>Chat beside an app</span>
        <Segmented size="sm" label="Chat dock side" value={layout.dock} options={DOCK_OPTIONS}
          onChange={dock => os.updateLayout(current => ({ ...current, dock }))} />
      </label>
      <span className="nx-arrange-hint">Drag edges to resize · Esc when done</span>
      <Button size="sm" icon={RotateCcw} onClick={os.resetLayout}>Reset</Button>
      <Button size="sm" variant="primary" icon={Check} onClick={() => os.arrange(false)}>Done</Button>
    </div>
  );
}
