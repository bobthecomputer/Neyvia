import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Maximize2, Minimize2, PanelRightOpen, SquarePen, X } from "lucide-react";

import "./nxPopout.css";
import { ProviderMark } from "./ProviderMark.jsx";
import { NxThread } from "./NxThread.jsx";
import { ModelPicker, NxComposer, useProviderOptions } from "./NxComposer.jsx";
import { CommentsStrip } from "./NxComments.jsx";
import { RoutePicker, billingNote, preferredTransport } from "./NxRoutePicker.jsx";
import { appLabel } from "./NxSidebar.jsx";
import { markFor } from "./NxSidebarParts.jsx";
import { Icon, IconButton, Spinner, local } from "./nxPrimitives.jsx";
import { loadList, openThread, startSession, useNx, waitForRunSession } from "./nxStore.js";
import { useOs } from "./nxOsStore.js";
import { stageTitle } from "./NxStage.jsx";
import { useApps } from "./nxApps.js";
import { focusedWindowId, trackFocusedWindow } from "./nxComments.js";
import { POPOUT_HINT, POPOUT_MIN, bindPopoutSession, closePopout, contextBlock, geometryFor, getPopout, openPopout, saveGeometry, setPopoutNewChat, toggleExpanded, usePopout, windowForShortcut } from "./nxPopout.js";

// The pop-out chat (plan 29 A): see nxPopout.js. The window is a plain floating
// section: drag it by its title bar, resize it from any edge or corner, expand
// it nearly full, close it. Its place is remembered per app. The chat inside is
// the real one (NxThread + NxComposer), so replies stream here and the full
// chat stays in the sidebar as usual.

const EDGES = ["n", "e", "s", "w", "ne", "nw", "se", "sw"];
const viewportNow = () => ({ width: window.innerWidth, height: window.innerHeight });

function usePopoutGeometry(desc, expanded) {
  const [viewport, setViewport] = useState(viewportNow);
  const [geom, setGeom] = useState(() => geometryFor(desc, viewportNow()));
  const key = desc ? `${desc.type}:${desc.app || desc.kind}` : "chat";
  const lastKey = useRef(key);
  useEffect(() => {
    const onResize = () => setViewport(viewportNow());
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  // A different app brings its own remembered place; a resize keeps the place inside the window.
  useEffect(() => { setGeom(geometryFor(desc, viewport)); lastKey.current = key; }, [key, viewport]); // eslint-disable-line react-hooks/exhaustive-deps
  const commit = useCallback(next => { setGeom(next); saveGeometry(desc, next); }, [desc]);
  const shown = expanded ? { x: Math.round(viewport.width * 0.06), y: Math.round(viewport.height * 0.06), w: Math.round(viewport.width * 0.88), h: Math.round(viewport.height * 0.88) } : geom;
  return { geom: shown, setGeom, commit, viewport };
}

function useDragResize({ geom, setGeom, commit, viewport, enabled }) {
  const press = useRef(null);
  const start = (mode, event) => {
    if (!enabled || event.button !== 0) return;
    if (mode === "move" && event.target.closest("button, a, input, textarea, select")) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    press.current = { mode, x0: event.clientX, y0: event.clientY, from: geom, id: event.pointerId, last: geom };
  };
  const move = event => {
    const current = press.current;
    if (!current || current.id !== event.pointerId) return;
    const dx = event.clientX - current.x0; const dy = event.clientY - current.y0;
    const from = current.from;
    const right = from.x + from.w; const bottom = from.y + from.h;
    const clamp = (value, low, high) => Math.min(Math.max(value, low), Math.max(low, high));
    let { x, y, w, h } = from;
    if (current.mode === "move") {
      // The window stays whole on screen: moving never loses its title bar or its edges.
      x = clamp(from.x + dx, 8, viewport.width - w - 8);
      y = clamp(from.y + dy, 8, viewport.height - h - 8);
    } else {
      if (current.mode.includes("e")) w = clamp(from.w + dx, POPOUT_MIN.w, viewport.width - 8 - from.x);
      if (current.mode.includes("s")) h = clamp(from.h + dy, POPOUT_MIN.h, viewport.height - 8 - from.y);
      if (current.mode.includes("w")) { x = clamp(from.x + dx, 8, right - POPOUT_MIN.w); w = right - x; }
      if (current.mode.includes("n")) { y = clamp(from.y + dy, 8, bottom - POPOUT_MIN.h); h = bottom - y; }
    }
    current.last = { x, y, w, h };
    setGeom(current.last);
  };
  const end = event => {
    const current = press.current;
    if (!current || current.id !== event.pointerId) return;
    press.current = null;
    commit(current.last);
  };
  return { start, move, end };
}

// A new chat about this app, for when there is no chat to carry over: the agent, a model and route, one send.
const AGENTS = [["neyvia", "neyvia"], ["claude-code", "claude"], ["codex", "codex"], ["opencode", "opencode"]];

function PopoutNewChat({ winId, desc, title, sessions }) {
  const [app, setApp] = useState(() => local.get("new.app", "neyvia"));
  const sources = useNx(current => current.list.sources);
  const agents = AGENTS.filter(([id]) => !sources?.length || sources.some(source => source.app === id && source.available !== false));
  const folder = useMemo(() => {
    const saved = local.get("new.folder", null);
    if (saved?.path) return saved;
    const recent = Object.values(sessions).filter(row => row?.cwd).sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")))[0];
    return recent ? { path: recent.cwd, name: recent.project } : null;
  }, [sessions]);
  const options = useProviderOptions(app, null);
  const [draft, setDraft] = useState("");
  const [choice, setChoice] = useState({});
  const [state, setState] = useState({ busy: false, error: "" });
  const input = useRef(null);
  const pending = usePopout(current => current.pendingRun);
  const transports = app === "claude-code" && options?.transports?.length ? options.transports : null;
  const transport = transports ? (choice.transport || preferredTransport(transports)) : null;
  useEffect(() => { input.current?.focus(); }, []);
  useEffect(() => { setPopoutNewChat({ app, cwd: folder?.path, model: choice.model || null, effort: choice.effort || null, transport }); return () => setPopoutNewChat(null); }, [app, folder?.path, choice.model, choice.effort, transport]);
  const pick = next => { setApp(next); setChoice({}); local.set("new.app", next); };
  const start = async () => {
    const message = draft.trim();
    if (!message || state.busy) return;
    if (!folder?.path) { setState({ busy: false, error: "Open a chat in a folder once, then this can start new ones." }); return; }
    setState({ busy: true, error: "" });
    try {
      const block = contextBlock({ winId, desc, title });
      const run = await startSession(app, folder.path, block ? `${block}\n\n${message}` : message, { model: choice.model || null, effort: choice.effort || null, transport });
      const sessionId = run?.sessionId || await waitForRunSession(run?.runId || run?.run?.runId);
      void loadList();
      if (sessionId) { local.set(`choice.${sessionId}`, { model: choice.model || null, effort: choice.effort || null, transport }); bindPopoutSession(sessionId); }
      setDraft("");
      setState({ busy: false, error: "" });
    } catch (failure) {
      setState({ busy: false, error: failure?.message || "The chat couldn't be started." });
    }
  };
  return (
    <div className="nx-pw-new">
      <div className="nx-pw-new-intro">
        <strong>New chat about {title || "this"}</strong>
        <span>{folder?.name ? `In ${folder.name}` : "No folder yet"}</span>
        <div className="nx-pw-agents" role="radiogroup" aria-label="Agent">
          {agents.map(([id, mark]) => (
            <button key={id} type="button" role="radio" aria-checked={app === id} className={app === id ? "is-on" : ""} onClick={() => pick(id)}>
              <ProviderMark id={mark} size={14} /><span>{appLabel(id)}</span>
            </button>
          ))}
        </div>
      </div>
      {pending ? <p className="nx-pw-pending" role="status"><Spinner size={13} />Comments sent. The chat appears here the moment it starts.</p> : null}
      <CommentsStrip winId={winId} desc={desc} title={title} sessionId={null} onSent={bindPopoutSession} />
      <form className="nx-composer nx-pw-form" onSubmit={event => { event.preventDefault(); void start(); }}>
        <textarea ref={input} rows={3} value={draft} placeholder={POPOUT_HINT} aria-label="First message" onChange={event => setDraft(event.target.value)}
          onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); void start(); } }} />
        <div className="nx-composer-bar">
          <div className="nx-composer-left">
            <ModelPicker app={app} models={options?.models || []} value={choice.model || null} effort={choice.effort || null}
              billing={app === "claude-code" ? "agent-sdk-credits" : null} note={billingNote(transports ? options : null, transport)} onChange={patch => setChoice(current => ({ ...current, ...patch }))} />
            <RoutePicker transports={transports} value={transport} onChange={next => setChoice(current => ({ ...current, transport: next }))} />
          </div>
          <div className="nx-composer-right">
            <button type="submit" className="nx-send" aria-label="Start chat" disabled={!draft.trim() || state.busy}>
              {state.busy ? <Spinner size={13} /> : <Icon as={ArrowUp} size={16} />}
            </button>
          </div>
        </div>
      </form>
      {state.error ? <p className="nx-pw-error" role="alert">{state.error}</p> : null}
    </div>
  );
}

function PopoutWindow({ rows, onOpenChat }) {
  const { winId, desc, title, sessionId, expanded } = usePopout();
  const sessions = useNx(state => state.sessions);
  const session = sessionId ? (rows.find(row => row.id === sessionId) || sessions[sessionId]) : null;
  const appName = session ? (session.category === "connected" ? appLabel(session.app) : "Neyvia") : "Neyvia";
  const { geom, setGeom, commit, viewport } = usePopoutGeometry(desc, expanded);
  const { start, move, end } = useDragResize({ geom, setGeom, commit, viewport, enabled: !expanded });
  const frame = useRef(null);
  const getBlock = useCallback(() => contextBlock({ winId, desc, title }), [winId, desc, title]);
  useEffect(() => { if (sessionId) void openThread(sessionId); }, [sessionId]);
  // Focus goes to the message box when it opens and returns to where it was when it closes.
  useEffect(() => {
    const previous = document.activeElement;
    requestAnimationFrame(() => frame.current?.querySelector("textarea")?.focus());
    return () => { if (previous?.isConnected) previous.focus?.(); };
  }, []);
  const label = session?.title || (sessionId ? "Chat" : "New chat");
  return (
    <section ref={frame} className={`nx-pw${expanded ? " is-expanded" : ""}`} role="dialog" aria-label={`Chat about ${title || "this"}`}
      style={{ left: geom.x, top: geom.y, width: geom.w, height: geom.h }} data-popout-for={winId || undefined}
      onKeyDown={event => { if (event.key === "Escape" && !event.defaultPrevented && !event.target.closest?.("[role=listbox], [role=menu], .nx-portal-host")) { event.stopPropagation(); closePopout(); } }}>
      <header className={`nx-pw-head${expanded ? "" : " is-handle"}`} onPointerDown={event => start("move", event)} onPointerMove={move} onPointerUp={end} onPointerCancel={end}>
        <ProviderMark id={session ? markFor(session) : "neyvia"} size={16} />
        <div className="nx-pw-title">
          <strong title={label}>{label}</strong>
          {title ? <span title={`About ${title}`}>about {title}</span> : null}
        </div>
        {sessionId ? <IconButton icon={SquarePen} size="sm" label="Start a new chat about this" onClick={() => bindPopoutSession(null)} /> : null}
        {sessionId ? <IconButton icon={PanelRightOpen} size="sm" label="Open this chat in the main view" onClick={() => { closePopout(); onOpenChat(sessionId); }} /> : null}
        <IconButton icon={expanded ? Minimize2 : Maximize2} size="sm" label={expanded ? "Smaller" : "Expand"} active={expanded} onClick={toggleExpanded} />
        <IconButton icon={X} size="sm" label="Close the chat" onClick={closePopout} />
      </header>
      {sessionId ? (
        <>
          <div className="nx-pw-thread"><NxThread sessionId={sessionId} appName={appName} /></div>
          <CommentsStrip winId={winId} desc={desc} title={title} sessionId={sessionId} onSent={bindPopoutSession} />
          <NxComposer key={sessionId} className="nx-pw-composer" sessionId={sessionId} session={session} appName={appName} onOpenChat={onOpenChat}
            placeholder={POPOUT_HINT} contextBlock={getBlock} />
        </>
      ) : <PopoutNewChat key={winId || "chat"} winId={winId} desc={desc} title={title} sessions={sessions} />}
      {expanded ? null : EDGES.map(edge => (
        <span key={edge} className={`nx-pw-edge is-${edge}`} aria-hidden="true"
          onPointerDown={event => start(edge, event)} onPointerMove={move} onPointerUp={end} onPointerCancel={end} />
      ))}
    </section>
  );
}

/** The pop-out chat, plus its keyboard shortcut. NxShell mounts it once, beside the other floating layers. */
export function NxPopout({ session, rows, onOpenChat, phone = false }) {
  const open = usePopout(current => current.open);
  const { suites } = useApps();
  useEffect(() => trackFocusedWindow(), []);
  // Ctrl+J: pop the chat out over the app you are in, or put it away. (Ctrl+Shift+Space is dictation.)
  useEffect(() => {
    const onKey = event => {
      if (!(event.ctrlKey && !event.shiftKey && !event.altKey && !event.metaKey && (event.code === "KeyJ" || event.key === "j"))) return;
      event.preventDefault();
      if (open) { closePopout(); return; }
      const win = windowForShortcut(focusedWindowId());
      openPopout({ winId: win?.id || "", desc: win?.desc || null, title: win ? stageTitle(win.desc, suites) : "Neyvia", sessionId: session?.id || null });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, session?.id, suites]);
  // The window the pop-out is about closed: it carries on as a chat about Neyvia in general.
  const windows = useOs(current => current.windows);
  useEffect(() => {
    const { winId } = getPopout();
    if (open && winId && !windows.some(win => win.id === winId)) openPopout({ winId: "", desc: null, title: "Neyvia" });
  }, [windows, open]);
  if (!open || phone) return null;
  return <PopoutWindow rows={rows} onOpenChat={onOpenChat} />;
}
