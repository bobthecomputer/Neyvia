import { useCallback, useEffect, useRef, useState } from "react";

import { ProviderMark } from "./ProviderMark.jsx";
import { markFor } from "./NxSidebarParts.jsx";
import { os } from "./nxOsStore.js";
import { dropSpot, outsideDock } from "./nxOutputsModel.js";
import "./nxDockDrag.css";

// Drag the docked chat out of the dock to float it (plan 15 T8). While an app
// or pane fills the stage, the chat docks beside it; grab its header and drop
// it anywhere outside the dock: it becomes a floating bubble (the same
// nxOsStore bubble Paul or a model can make), the stage takes the whole width,
// and the chat keeps running untouched: same chat, same run, nothing restarted.
// The bubble's "Dock" button puts it back. Keyboard: the header's float button.

const START_PX = 6; // movement before a press becomes a drag

export function useDockDrag({ sessionId, enabled, onFloated }) {
  const [drag, setDrag] = useState(null); // { x, y, out }
  const press = useRef(null);

  const cancel = useCallback(() => { press.current = null; setDrag(null); }, []);
  useEffect(() => {
    if (!drag) return undefined;
    const onKey = event => { if (event.key === "Escape") cancel(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drag, cancel]);

  const onPointerDown = useCallback(event => {
    if (!enabled || !sessionId || event.button !== 0) return;
    if (event.target.closest("button, a, input, textarea, select")) return; // the header's own buttons stay buttons
    press.current = { x0: event.clientX, y0: event.clientY, id: event.pointerId, rect: event.currentTarget.closest(".nx-work-chat")?.getBoundingClientRect() || null };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }, [enabled, sessionId]);

  const onPointerMove = useCallback(event => {
    const current = press.current;
    if (!current || event.pointerId !== current.id) return;
    if (!drag && Math.hypot(event.clientX - current.x0, event.clientY - current.y0) < START_PX) return;
    const point = { x: Math.min(window.innerWidth - 8, Math.max(8, event.clientX)), y: Math.min(window.innerHeight - 8, Math.max(8, event.clientY)) };
    setDrag({ ...point, out: outsideDock(point, current.rect) });
  }, [drag]);

  const onPointerUp = useCallback(event => {
    const current = press.current;
    press.current = null;
    if (!current || !drag) { setDrag(null); return; }
    setDrag(null);
    const point = { x: event.clientX, y: event.clientY };
    if (!outsideDock(point, current.rect)) return; // dropped back on the dock: nothing changes
    const spot = dropSpot(point, window.innerWidth, window.innerHeight);
    os.float(sessionId);
    os.moveBubble(sessionId, spot.x, spot.y);
    onFloated?.(sessionId);
  }, [drag, sessionId, onFloated]);

  const handlers = enabled ? { onPointerDown, onPointerMove, onPointerUp, onPointerCancel: cancel } : {};
  return { drag, handlers };
}

/** What follows the pointer while the chat is being dragged out. */
export function DockDragGhost({ drag, session }) {
  if (!drag) return null;
  return (
    <div className={`nx-dock-ghost${drag.out ? " is-out" : ""}`} style={{ transform: `translate3d(${drag.x - 26}px, ${drag.y - 26}px, 0)` }} aria-hidden="true">
      <span className="nx-dock-ghost-bubble"><ProviderMark id={session ? markFor(session) : "neyvia"} size={24} /></span>
      <span className="nx-dock-ghost-label">{drag.out ? "Release to float" : "Drag out of the dock"}</span>
    </div>
  );
}
