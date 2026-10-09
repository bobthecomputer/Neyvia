import { useEffect, useRef, useState } from "react";

import { ProviderMark } from "./ProviderMark.jsx";
import { Kbd, StatusDot, ago, local } from "./nxPrimitives.jsx";
import { markFor } from "./NxSidebarParts.jsx";

// Conversation layers (07 §R3): the chats you opened recently stay stacked
// like a phone's recent apps. Hold Ctrl and tap ` to walk the stack (Shift
// walks back); let go of Ctrl to switch. Esc cancels. Cards are clickable.

const MAX_LAYERS = 8;
const TONE = { working: "live", waiting_approval: "gold", waiting_input: "gold", failed: "red" };

/** Keeps the most recently opened chats, newest first, per viewer. */
export function useLayers(activeId) {
  const [layers, setLayers] = useState(() => local.get("layers", []));
  useEffect(() => {
    if (!activeId) return;
    setLayers(current => {
      const next = [activeId, ...current.filter(id => id !== activeId)].slice(0, MAX_LAYERS);
      local.set("layers", next);
      return next;
    });
  }, [activeId]);
  return layers;
}

export function NxSwitcher({ layers, rows, onSelect }) {
  const [index, setIndex] = useState(-1);
  const current = useRef(-1);
  const byId = new Map(rows.map(row => [row.id, row]));
  const stack = layers.map(id => byId.get(id)).filter(row => row && !row.archived);
  const count = useRef(0);
  count.current = stack.length;
  const choose = useRef(onSelect);
  choose.current = id => onSelect(id);
  const ids = useRef([]);
  ids.current = stack.map(row => row.id);

  useEffect(() => {
    const move = next => { current.current = next; setIndex(next); };
    const onDown = event => {
      if (event.ctrlKey && event.code === "Backquote") {
        event.preventDefault();
        if (count.current < 2) return;
        const step = event.shiftKey ? -1 : 1;
        move(current.current < 0 ? (step > 0 ? 1 : count.current - 1) : (current.current + step + count.current) % count.current);
      } else if (event.key === "Escape" && current.current >= 0) {
        event.preventDefault();
        move(-1);
      }
    };
    const onUp = event => {
      if (event.key !== "Control" || current.current < 0) return;
      const id = ids.current[current.current];
      move(-1);
      if (id) choose.current(id);
    };
    window.addEventListener("keydown", onDown, true);
    window.addEventListener("keyup", onUp, true);
    return () => { window.removeEventListener("keydown", onDown, true); window.removeEventListener("keyup", onUp, true); };
  }, []);

  if (index < 0 || stack.length < 2) return null;
  const now = Date.now();
  return (
    <div className="nx-switcher-scrim" onMouseDown={event => { if (event.target === event.currentTarget) { current.current = -1; setIndex(-1); } }}>
      <div className="nx-switcher" role="listbox" aria-label="Recent conversations">
        {stack.map((row, position) => (
          <button key={row.id} type="button" role="option" aria-selected={position === index} data-nx-morph="chat"
            className={`nx-layer${position === index ? " is-on" : ""}`} style={{ "--depth": Math.abs(position - index) }}
            onMouseEnter={() => { current.current = position; setIndex(position); }}
            onClick={() => { current.current = -1; setIndex(-1); onSelect(row.id); }}>
            <span className="nx-layer-top">
              <ProviderMark id={markFor(row)} size={14} />
              <span className="nx-layer-where">{row.project || "No folder"}</span>
              {TONE[row.status] ? <StatusDot tone={TONE[row.status]} pulse={row.status === "working"} /> : null}
              <time>{ago(row.updated_at, now)}</time>
            </span>
            <span className="nx-layer-title">{row.title || "Untitled chat"}</span>
          </button>
        ))}
      </div>
      <p className="nx-switcher-hint">Hold <Kbd>Ctrl</Kbd> and tap <Kbd>`</Kbd> to move · release to switch · <Kbd>Esc</Kbd> cancels</p>
    </div>
  );
}
