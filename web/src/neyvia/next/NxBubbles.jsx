import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Maximize2, PanelRightOpen, X } from "lucide-react";

import "./nxBubbles.css";
import { ProviderMark } from "./ProviderMark.jsx";
import { NxGrowingTree } from "./NxGrowingTree.jsx";
import { Icon, IconButton, Spinner, StatusDot, elapsed, local, useTick } from "./nxPrimitives.jsx";
import { openThread, sendMessage, useNx } from "./nxStore.js";
import { os, useOs } from "./nxOsStore.js";
import { isNeedsYou } from "./nxSidebarModel.js";
import { markFor } from "./NxSidebarParts.jsx";

// Floating chats (Paul's Xiaomi reference: floating windows and bubbles).
// Any chat can float as a bubble over every screen: its ring shows the
// agent's state, drag it anywhere and it snaps to the nearest side, tap it for
// a mini window with the latest messages and a quick reply. The agent can
// float a chat too (neyvia.view.float), to keep a long job in view.

const SIZE = 52;
const EDGE = 10;

// The mini window is a glance, not a reader: markdown marks are dropped.
const plain = text => String(text).slice(0, 600).replace(/(\*\*|__|`+|^#+\s|^>\s)/gm, "");

function stateOf(row, now) {
  if (!row) return "idle";
  if (row.status === "working") return "running";
  return isNeedsYou(row, now) ? "needs" : "idle";
}

function MiniWindow({ row, bubble, onOpenChat, onDock }) {
  const thread = useNx(state => state.threads[row.id]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const input = useRef(null);
  useEffect(() => { void openThread(row.id); input.current?.focus(); }, [row.id]);
  const lines = useMemo(() => (thread?.items || [])
    .filter(item => (item.kind === "user" || item.kind === "assistant") && item.data?.text)
    .slice(-6), [thread?.items]);
  const send = async () => {
    const message = draft.trim();
    if (!message || sending) return;
    setSending(true); setError("");
    try {
      // Same model, effort and route the chat was last sent with.
      const choice = local.get(`choice.${row.id}`, {}) || {};
      await sendMessage(row.id, message, { model: choice.model || null, effort: choice.effort || null, permission_mode: choice.permission || null, transport: choice.transport || null });
      setDraft("");
    } catch (failure) {
      setError(failure?.message || "Not sent.");
    } finally {
      setSending(false);
    }
  };
  const left = bubble.x < 0.5;
  return (
    <section className={`nx-mini${left ? " is-left" : ""}`} role="dialog" aria-label={`${row.title || "Chat"}, floating`}
      style={{ top: `clamp(12px, calc(${bubble.y * 100}vh - 40px), calc(100vh - 470px))`, [left ? "left" : "right"]: `${EDGE + SIZE + 10}px` }}
      onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); os.openBubble(row.id); } }}>
      <header className="nx-mini-head">
        <ProviderMark id={markFor(row)} size={16} />
        <strong title={row.title}>{row.title || "Untitled chat"}</strong>
        {onDock ? <IconButton icon={PanelRightOpen} size="sm" label="Dock beside the app" onClick={() => onDock(row.id)} /> : null}
        <IconButton icon={Maximize2} size="sm" label="Open the chat" onClick={() => { os.openBubble(row.id); onOpenChat(row.id); }} />
        <IconButton icon={X} size="sm" label="Close the bubble" onClick={() => os.unfloat(row.id)} />
      </header>
      <div className="nx-mini-body nx-scroll">
        {thread?.status === "loading" && !lines.length ? <div className="nx-mini-empty"><Spinner size={14} /></div> : null}
        {lines.map(item => (
          <p key={item.id} className={`nx-mini-line is-${item.kind}`}>{plain(item.data.text)}</p>
        ))}
        {thread?.status === "ready" && !lines.length ? <p className="nx-mini-empty">No messages yet.</p> : null}
        {row.status === "working" ? <div className="nx-mini-working"><NxGrowingTree size={20} /><span>Working{row.status_since ? ` · ${elapsed(row.status_since)}` : ""}</span></div> : null}
      </div>
      <form className="nx-mini-reply" onSubmit={event => { event.preventDefault(); void send(); }}>
        <input ref={input} value={draft} onChange={event => setDraft(event.target.value)} placeholder="Quick reply…" aria-label="Quick reply" />
        <button type="submit" className="nx-send" aria-label="Send" disabled={!draft.trim() || sending}>{sending ? <Spinner size={12} /> : <Icon as={ArrowUp} size={14} />}</button>
      </form>
      {error ? <p className="nx-mini-error" role="alert">{error}</p> : null}
    </section>
  );
}

function Bubble({ bubble, row, open, onOpenChat, onDock }) {
  const drag = useRef(null);
  const [dragAt, setDragAt] = useState(null); // live position while dragging, in px
  const now = Date.now();
  const tone = stateOf(row, now);
  const place = dragAt || {
    x: bubble.x < 0.5 ? EDGE : window.innerWidth - SIZE - EDGE,
    y: Math.min(window.innerHeight - SIZE - 40, Math.max(EDGE, bubble.y * window.innerHeight - SIZE / 2)),
  };
  const onPointerDown = event => {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
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
    if (!current.moved) { os.openBubble(bubble.id); return; }
    // Snap to the nearer side; keep the height the user chose.
    const x = event.clientX < window.innerWidth / 2 ? 0 : 1;
    os.moveBubble(bubble.id, x, (event.clientY - current.dy + SIZE / 2) / window.innerHeight);
    setDragAt(null);
  };
  const label = `${row?.title || "Chat"}: ${tone === "running" ? "running" : tone === "needs" ? "needs you" : "idle"}`;
  return (
    <>
      <button type="button" data-session-id={bubble.id} className={`nx-bubble-float is-${tone}${dragAt ? " is-dragging" : ""}${open ? " is-open" : ""}`}
        style={{ transform: `translate3d(${place.x}px, ${place.y}px, 0)` }} aria-label={label} title={label} aria-expanded={open}
        onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={() => { drag.current = null; setDragAt(null); }}
        onKeyDown={event => { if (event.key === "Delete") os.unfloat(bubble.id); else if (event.key === "d" && onDock) onDock(bubble.id); }}>
        <span className="nx-bubble-ring" aria-hidden="true" />
        <ProviderMark id={row ? markFor(row) : "neyvia"} size={24} />
        {row?.unread ? <span className="nx-bubble-unread" aria-hidden="true" /> : null}
        {tone === "needs" ? <span className="nx-bubble-badge" aria-hidden="true"><StatusDot tone="gold" /></span> : null}
      </button>
      {open && row ? <MiniWindow row={row} bubble={bubble} onOpenChat={onOpenChat} onDock={onDock} /> : null}
    </>
  );
}

export function NxBubbles({ rows, onOpenChat, onDock = null }) {
  const bubbles = useOs(state => state.bubbles);
  const openId = useOs(state => state.bubbleOpen);
  const byId = useMemo(() => new Map(rows.map(row => [row.id, row])), [rows]);
  useTick(bubbles.some(bubble => byId.get(bubble.id)?.status === "working"), 15000);
  // Re-place bubbles when the window changes size: positions are fractions of it.
  const [, setTick] = useState(0);
  useEffect(() => {
    const onResize = () => setTick(value => value + 1);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  if (!bubbles.length) return null;
  return (
    <div className="nx-bubbles" aria-label="Floating chats">
      {bubbles.map(bubble => (
        <Bubble key={bubble.id} bubble={bubble} row={byId.get(bubble.id)} open={openId === bubble.id} onOpenChat={onOpenChat} onDock={onDock} />
      ))}
    </div>
  );
}
