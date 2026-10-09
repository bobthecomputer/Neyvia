import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight, BookOpen, Download, Globe, History, Layers, Plus, ScanText, Search, ShieldAlert, ShieldCheck, TriangleAlert, X,
} from "lucide-react";

import { Button, Icon, IconButton, Popover, Segmented, Spinner, StatusDot, ago, useFocusTrap, useRovingKeys } from "./nxPrimitives.jsx";
import { ProviderMark } from "./ProviderMark.jsx";
import { act, browserCall, coverNative, observeTab, readTab, rememberFrame, sizeAgentPage, useAgentPresence } from "./nxBrowserApi.js";
import { actionLabel, agentIdentity, agentState, displayUrl, framePoint, highlightRect, hostOf, parseAddress, suggest, viewportOf } from "./nxBrowserModel.js";
import { approxTokens, outline } from "./nxOutputsApi.js";
import { callTool } from "./nxBus.js";
import { formatSize } from "./nxDocsApi.js";

// Pieces of the integrated browser (NxBrowser.jsx): the command bar, the
// agent's live tab, reader mode, the agent's view (T18), shield and downloads.

/** The native favicon, with a site's initial while it loads or if it fails. */
export function Monogram({ url, favicon, size = "md" }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [favicon]);
  const host = hostOf(url);
  return <span className={`nx-br-mono nx-br-mono-${size}`} aria-hidden="true">{favicon && !failed
    ? <img src={favicon} alt="" width="16" height="16" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
    : host && !/^[\d[]/.test(host) ? host[0].toUpperCase() : <Icon as={Globe} size={12} />}</span>;
}

/** Native pages draw above the interface: while an overlay is open they step aside. */
export function useCover(open) {
  useEffect(() => {
    if (!open) return undefined;
    coverNative(true);
    return () => coverNative(false);
  }, [open]);
}

/** Consent belongs to the owner, separate from any grant to control a tab. */
export function PermissionRequests({ requests }) {
  const pending = requests.filter(row => row.state === "pending" || row.state === "answering");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  useCover(pending.length > 0);
  const answer = async (row, decision) => {
    setBusy(row.requestId); setError("");
    try {
      await act("permission.answer", { requestId: row.requestId, decision, origin: row.origin,
        profileId: row.profileId, navigationEpoch: row.navigationEpoch }, { wait: true });
    } catch (failure) { setError(failure?.message || String(failure)); }
    finally { setBusy(""); }
  };
  if (!pending.length) return null;
  return <section className="nx-br-permissions" aria-label="Website permission requests">
    {pending.map(row => <div key={row.requestId} className="nx-br-permission">
      <Icon as={ShieldAlert} size={18} />
      <div><strong>{row.origin} wants to send notifications</strong>
        <p>{row.private ? "Private tab. " : ""}Allow only this request. Nothing is remembered. It expires after 30 seconds.</p>
        <details><summary>Request details</summary><p>Profile: {row.profileId}. Tab: {row.tabId}. Navigation: {row.navigationEpoch}.</p><code>{row.requestId}</code></details></div>
      <Button size="sm" disabled={Boolean(busy) || row.state === "answering"} onClick={() => void answer(row, "deny")} aria-label={`Deny notifications for ${row.origin}`}>Deny</Button>
      <Button size="sm" disabled={Boolean(busy) || row.state === "answering"} onClick={() => void answer(row, "allow")} aria-label={`Allow notifications for ${row.origin}`}>Allow</Button>
    </div>)}
    {error ? <p role="alert">{error}</p> : null}
  </section>;
}

// ---------------------------------------------------------------- command bar

/**
 * Arc-like command bar (Ctrl T / Ctrl K): one field for an address, a search,
 * an open tab, a page from history or a browser action.
 */
export function CommandBar({ open, onClose, state, title = "Open", actions = [], onGo, onPeek, onTab }) {
  const box = useRef(null);
  const list = useRef(null);
  const [text, setText] = useState("");
  const [index, setIndex] = useState(0);
  useFocusTrap(box, open);
  useCover(open);
  useEffect(() => { if (open) { setText(""); setIndex(0); } }, [open]);
  const onKeys = useRovingKeys(list);

  const rows = useMemo(() => {
    if (!open) return [];
    const parsed = parseAddress(text);
    const out = [];
    if (parsed.kind === "url") out.push({ id: "go", kind: "go", icon: ArrowRight, title: `Open ${displayUrl(parsed.url)}`, url: parsed.url, peek: true });
    else if (parsed.kind === "search") out.push({ id: "go", kind: "go", icon: Search, title: `Search for “${parsed.query}”`, url: parsed.url, peek: true });
    else if (parsed.kind === "blocked") out.push({ id: "blocked", kind: "blocked", icon: TriangleAlert, title: parsed.reason });
    for (const row of suggest(text, { tabs: state?.tabs || [], history: state?.history || [] }, text ? 6 : 5)) {
      out.push({ id: `${row.type}:${row.tabId || row.url}`, kind: row.type, icon: row.type === "tab" ? Layers : History, title: row.title || displayUrl(row.url), sub: row.type === "tab" ? "Switch to tab" : displayUrl(row.url), url: row.url, tabId: row.tabId, peek: row.type === "history" });
    }
    const words = text.trim().toLowerCase();
    for (const action of actions) {
      if (!words || action.title.toLowerCase().includes(words) || action.keywords?.some(word => word.startsWith(words))) out.push({ ...action, kind: "action" });
    }
    return out.slice(0, 14);
  }, [open, text, state, actions]);

  useEffect(() => { setIndex(0); }, [text]);
  if (!open) return null;

  const run = (row, { peek = false } = {}) => {
    if (!row || row.kind === "blocked") return;
    onClose();
    if (row.kind === "action") row.run();
    else if (row.kind === "tab") onTab(row.tabId);
    else if (peek && row.url) onPeek(row.url);
    else if (row.url) onGo(row.url);
  };
  const onKey = event => {
    if (event.key === "Escape") { event.preventDefault(); onClose(); }
    else if (event.key === "ArrowDown") { event.preventDefault(); setIndex(value => Math.min(rows.length - 1, value + 1)); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setIndex(value => Math.max(0, value - 1)); }
    else if (event.key === "Enter") { event.preventDefault(); run(rows[index], { peek: event.shiftKey && rows[index]?.peek }); }
  };
  return (
    <div className="nx-br-cmd-scrim" onPointerDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div ref={box} className="nx-br-cmd" role="dialog" aria-modal="true" aria-label={title}>
        <label className="nx-br-cmd-field">
          <Icon as={Search} size={16} />
          <input autoFocus value={text} onChange={event => setText(event.target.value)} onKeyDown={onKey}
            placeholder="Search or type an address" aria-label="Search or type an address" role="combobox"
            aria-expanded="true" aria-controls="nx-br-cmd-list" aria-activedescendant={rows[index] ? `nx-br-cmd-${index}` : undefined} />
        </label>
        <ul ref={list} id="nx-br-cmd-list" className="nx-br-cmd-list nx-scroll" role="listbox" aria-label="Results" onKeyDown={onKeys}>
          {rows.map((row, position) => (
            <li key={row.id} role="presentation">
              <button type="button" id={`nx-br-cmd-${position}`} role="option" aria-selected={position === index}
                className={`nx-br-cmd-row${position === index ? " is-on" : ""}${row.kind === "blocked" ? " is-blocked" : ""}`}
                onMouseEnter={() => setIndex(position)} onClick={() => run(row)}>
                {row.url && row.kind !== "go" ? <Monogram url={row.url} size="sm" /> : <Icon as={row.icon || ArrowRight} size={15} />}
                <span className="nx-br-cmd-main"><strong>{row.title}</strong>{row.sub ? <small>{row.sub}</small> : null}</span>
                {row.kind === "action" && row.hint ? <small className="nx-br-cmd-hint">{row.hint}</small> : null}
              </button>
            </li>
          ))}
        </ul>
        <footer className="nx-br-cmd-foot">
          <span><kbd className="nx-kbd">Enter</kbd> open</span>
          <span><kbd className="nx-kbd">Shift Enter</kbd> peek without leaving this tab</span>
          <span><kbd className="nx-kbd">Esc</kbd> close</span>
        </footer>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- the agent's headless tab, live

const clean = text => String(text || "").replace(/\s+/g, " ").trim();
const keyOf = element => `${element.role}|${clean(element.name)}`;

/** Follow a tab's page as the agent reads it (a fresh DOM projection every couple of seconds). */
/** The page as the agent reads it, polled; `tab` null polls nothing. */
export function useProjection(tab, every = 2000) {
  const [view, setView] = useState({ status: "loading" });
  const previous = useRef(new Map());
  const changed = useRef(new Set());
  const revision = useRef("");
  useEffect(() => {
    if (!tab?.id) return undefined;
    let live = true;
    let timer = 0;
    const read = async () => {
      try {
        let value;
        try { value = tab.engine === "obscura" ? await observeTab(tab) : await browserCall("observe", { tabId: tab.id, cached: true }); }
        catch (error) {
          if (error.code !== "projection_unavailable") throw error;
          value = await observeTab(tab);
        }
        if (!live) return;
        if (value.revision !== revision.current) {
          // Values that differ from the previous read: what the agent (or the page) just changed.
          const next = new Map((value.elements || []).map(element => [keyOf(element), element.value]));
          changed.current = previous.current.size
            ? new Set([...next].filter(([key, item]) => previous.current.has(key) && previous.current.get(key) !== item).map(([key]) => key))
            : new Set();
          previous.current = next;
          revision.current = value.revision;
          setView({ status: "ready", value, at: Date.now() });
        } else setView(current => ({ ...current, error: "", at: Date.now() }));
      } catch (error) {
        if (live) setView(current => ({ ...current, status: current.value ? "ready" : "error", error: error.message }));
      }
      if (live) timer = setTimeout(read, every);
    };
    void read();
    return () => { live = false; clearTimeout(timer); };
  }, [tab?.id, tab?.engine, every]);
  return { ...view, changed: changed.current };
}

// ------------------------------------------------ an agent's tab, seen through the browser

/**
 * The live picture of a headless tab: the newest frame, kept until the next one
 * has decoded (no flashing between them). Frames come quickly while an agent is
 * acting and slowly otherwise. `kick()` asks for one now (after a resize).
 */
export function useFrameStream(tab, { enabled = true, fast = false } = {}) {
  const [state, setState] = useState({ frame: null, error: "" });
  const [tick, setTick] = useState(0);
  const speed = useRef(fast);
  speed.current = fast;
  useEffect(() => { setState({ frame: null, error: "" }); }, [tab.id]);
  useEffect(() => {
    if (!enabled) return undefined;
    let live = true, timer = 0, fails = 0;
    const next = () => { if (live) timer = setTimeout(loop, document.hidden ? 4000 : fails ? Math.min(6000, 1500 * fails) : speed.current ? 600 : 2200); };
    const loop = async () => {
      try {
        const frame = await browserCall("frame", { tabId: tab.id });
        fails = 0;
        if (!live) return;
        const image = new Image();
        image.src = frame.dataUrl;
        await image.decode().catch(() => {});
        if (live) setState(current => (current.frame?.dataUrl === frame.dataUrl ? { ...current, error: "" } : { frame, error: "" }));
      } catch (error) {
        fails += 1;
        if (live) setState(current => ({ frame: current.frame, error: error.message || String(error) }));
      }
      next();
    };
    void loop();
    return () => { live = false; clearTimeout(timer); };
  }, [tab.id, enabled, tick]);
  return { ...state, kick: useCallback(() => setTick(value => value + 1), []) };
}

/** What Paul can do about an agent tab: let it act, take the page, or (desktop) watch it in a visible tab. */
export function useAgentControls(tab, presence, { canPromote = false, onWatch, onTakeOver } = {}) {
  const [mine, setMine] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { if (tab?.agentGranted) setMine(false); }, [tab?.agentGranted]);
  useEffect(() => { setMine(false); setError(""); }, [tab?.id]);
  const grant = async enabled => {
    setBusy(true); setError("");
    try { await act("tab.grant", { tabId: tab.id, enabled }); setMine(!enabled); }
    catch (failure) { setError(failure.message || String(failure)); }
    finally { setBusy(false); }
  };
  const resume = async () => {
    setBusy(true); setError("");
    try {
      const result = await act("task.resume", { taskId: tab.ownerTask.taskId });
      if (result.status === "needs_owner") setError("The page still needs your help. Resolve its check, then resume.");
    } catch (failure) { setError(failure.message || String(failure)); }
    finally { setBusy(false); }
  };
  return {
    state: agentState(tab, presence, { mine }), identity: agentIdentity(tab, presence), busy, error, canPromote,
    allow: () => grant(true), notNow: () => setMine(true), handBack: () => grant(true), resume,
    watch: () => onWatch?.(), takeOver: () => (canPromote && onTakeOver ? onTakeOver() : grant(false)),
  };
}

const PILL_SAY = {
  working: name => `${name} is browsing`, allowed: name => `${name} is browsing`,
  waiting: name => `${name} wants to act on this page`, mine: name => `${name} is paused`, asleep: () => "The agent engine is off",
};

/**
 * The agent's quiet presence, a pill in the address field: its mark, one line
 * and at most two choices. A request is a small inline ask, never a banner.
 */
export function AgentPill({ tab, controls, drawerOpen, onDrawer }) {
  const { state, identity, busy, canPromote } = controls;
  const task = tab.ownerTask?.status === "needs_owner";
  const say = task ? "This task needs your help" : (PILL_SAY[state] || PILL_SAY.waiting)(identity.name);
  return (
    <span className={`nx-br-pill is-${state}`} role="status" aria-live="polite" title={task ? tab.ownerTask.prompt : controls.error || undefined}>
      <span className="nx-br-pill-mark"><ProviderMark id={identity.id} size={14} /></span>
      <span className="nx-br-pill-say">{controls.error ? controls.error : !task && state === "waiting" ? <><span className="nx-br-pill-long">{say}</span><span className="nx-br-pill-short">{identity.name} wants to act</span></> : say}</span>
      <span className="nx-br-pill-acts">
        {task ? <button type="button" disabled={busy} onClick={() => void controls.resume()}>Resume</button> : null}
        {!task && state === "waiting" ? <><button type="button" className="is-main" disabled={busy} onClick={() => void controls.allow()}>Allow</button><button type="button" disabled={busy} onClick={controls.notNow}>Not now</button></> : null}
        {!task && state === "mine" ? <button type="button" className="is-main" disabled={busy} onClick={() => void controls.handBack()}>Let it act</button> : null}
        {!task && (state === "working" || state === "allowed") ? <>
          {canPromote ? <button type="button" disabled={busy} onClick={controls.watch}>Watch</button> : null}
          <button type="button" disabled={busy} onClick={() => void controls.takeOver()}>Take over</button>
        </> : null}
        {state === "waiting" && canPromote ? <button type="button" disabled={busy} onClick={() => void controls.takeOver()}>Take over</button> : null}
        {state !== "asleep" ? <button type="button" className="nx-br-pill-eye" aria-label="What the agent sees" aria-pressed={Boolean(drawerOpen)} title="What the agent sees" onClick={onDrawer}><Icon as={ScanText} size={13} /></button> : null}
      </span>
    </span>
  );
}

/**
 * An agent's tab in the headless engine (Obscura), drawn like any page: the
 * live frame at the pane's real size, nothing around it. The agent's presence
 * is a thin warm edge while it acts and a soft label on the element it touches.
 * `bar` (on by default) adds the pill for panes with no address field of their own.
 */
export function AgentLive({ tab, sessionId, presence: given, controls: givenControls, readOnly = false, bar = true, onWatch, onTakeOver, runtimeConnected, desktop, onDrawer, drawerOpen }) {
  const own = useAgentPresence(given === undefined && !readOnly ? tab : null);
  const presence = given === undefined ? own : given;
  const ownControls = useAgentControls(tab, presence, { canPromote: Boolean(desktop && runtimeConnected), onWatch, onTakeOver });
  const controls = givenControls || ownControls;
  const acting = !readOnly && tab.agentGranted && Boolean(presence?.working || presence?.focus);
  const { frame, error, kick } = useFrameStream(tab, { fast: acting || controls.state === "working" });
  const view = useRef(null);
  const [shown, setShown] = useState(null);
  const [behind, setBehind] = useState(""); // the last picture that finished loading stays under the next one, so a frame swap never shows a blank page
  const [inputError, setInputError] = useState("");
  const asked = useRef("");
  const density = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;

  // The page is exactly as large as the area that shows it.
  useLayoutEffect(() => {
    const element = view.current;
    if (!element) return undefined;
    let timer = 0;
    const measure = () => {
      const size = viewportOf(element.getBoundingClientRect(), density);
      if (!size) return;
      const key = `${tab.id}:${size.width}x${size.height}@${size.scale}`;
      if (asked.current === key) return;
      asked.current = key;
      sizeAgentPage(tab.id, size).then(kick, failure => { asked.current = ""; if (failure.code !== "not_live") setInputError(failure.message || ""); });
    };
    const soon = () => { clearTimeout(timer); timer = setTimeout(measure, 200); };
    measure();
    const observer = new ResizeObserver(soon);
    observer.observe(element);
    return () => { clearTimeout(timer); observer.disconnect(); };
  }, [tab.id, tab.live, density, kick]);

  // Acknowledge a frame only once it is on screen: that is what the owner's pane has actually shown.
  useEffect(() => {
    if (!shown || !sessionId || shown.sessionId !== sessionId) return undefined;
    let live = true;
    void browserCall("pane.ack", { tabId: tab.id, sessionId, revision: shown.revision })
      .catch(failure => { if (live && failure.code !== "stale_projection") setInputError(failure.message); });
    return () => { live = false; };
  }, [tab.id, sessionId, shown?.revision, shown?.capturedAt]);

  useEffect(() => { rememberFrame(tab.id, frame?.dataUrl); }, [tab.id, frame?.dataUrl]);
  // Something the agent just did: take a fresh picture now rather than at the next tick.
  const doing = presence?.focus ? `${presence.focus.phase}|${presence.focus.tool}|${presence.focus.label}` : "";
  useEffect(() => { if (doing) { const timer = setTimeout(kick, 120); return () => clearTimeout(timer); } return undefined; }, [doing, kick]);
  const focus = presence?.focus;
  const box = highlightRect(focus, frame);
  const label = actionLabel(focus);
  const click = event => {
    if (readOnly || !shown) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const point = framePoint(event, rect, shown);
    if (!point) return;
    setInputError("");
    void browserCall("frame.input", { tabId: tab.id, sessionId: shown.sessionId, revision: shown.revision, ...point }).catch(failure => setInputError(failure.message));
  };
  return (
    <div className={`nx-br-view${acting ? " is-acting" : ""}${readOnly ? " is-readonly" : ""}`} ref={view} data-agent-tab={tab.id}>
      {frame?.dataUrl ? (
        <div className="nx-br-frame" style={{ width: frame.width || undefined, height: frame.height || undefined, backgroundImage: behind ? `url(${behind})` : undefined }} onClick={click}
          data-nx-comment-target={`browser:${tab.url || tab.id}`} data-nx-comment-kind="browser" data-nx-comment-label={tab.title || tab.url || "Page"}>
          <img src={frame.dataUrl} alt={tab.title || "Current page"} width={frame.width || undefined} height={frame.height || undefined} draggable={false}
            onLoad={event => { if (event.currentTarget.naturalWidth > 0) setBehind(frame.dataUrl); if (event.currentTarget.naturalWidth > 0) setShown({ sessionId: frame.sessionId, revision: frame.revision, capturedAt: frame.capturedAt, width: frame.width, height: frame.height }); }} />
          {box && label ? (
            <span className={`nx-br-hl${focus.phase === "done" ? " is-done" : ""}`} aria-hidden="true" style={{ left: `${box.x}%`, top: `${box.y}%`, width: `${box.w}%`, height: `${box.h}%` }}>
            </span>
          ) : null}
        </div>
      ) : error ? (
        <div className="nx-br-center"><Icon as={TriangleAlert} size={22} /><strong>The page picture isn't available</strong><span>{error}</span>
          <div className="nx-br-row"><Button size="sm" variant="outline" onClick={kick}>Try again</Button>{onDrawer ? <Button size="sm" variant="outline" icon={ScanText} onClick={onDrawer}>What the agent sees</Button> : null}</div></div>
      ) : (
        <div className="nx-br-center" aria-busy="true"><Spinner size={16} /><span>Opening {displayUrl(tab.url)}…</span></div>
      )}
      {box && label && frame?.dataUrl && !inputError ? <span className="nx-br-view-say" role="status">{label}</span> : null}
      {inputError ? <p className="nx-br-view-note" role="alert">{inputError}</p> : null}
      {bar ? <div className="nx-br-view-pill"><AgentPill tab={tab} controls={controls} drawerOpen={drawerOpen} onDrawer={onDrawer} /></div> : null}
    </div>
  );
}

/** The agent's lens on the page (fields, headings, buttons, links) and its text form: closed until asked for. */
export function AgentDrawer({ tab, laya, onClose }) {
  const projection = useProjection(tab);
  const [mode, setMode] = useState("page");
  const { status, value, changed, error, at } = projection;
  const [draft, setDraft] = useState({});
  const [inputError, setInputError] = useState("");
  const input = async (element, action, content) => {
    setInputError("");
    try { await browserCall("action", { tabId: tab.id, revision: value.revision, element: element.id, action, ...(content === undefined ? {} : { value: content }) }); }
    catch (failure) { setInputError(failure.message); }
  };
  const elements = value?.elements || [];
  const fields = elements.filter(element => element.actions?.includes("fill") || element.actions?.includes("select") || element.secret);
  const buttons = elements.filter(element => element.role === "button" && clean(element.name)).slice(0, 18);
  const links = elements.filter(element => element.role === "link" && clean(element.name)).slice(0, 24);
  const headings = elements.filter(element => /^h[1-3]$/.test(element.role || "") && clean(element.name)).slice(0, 12);
  const text = clean(value?.text).slice(0, 1600);
  return (
    <aside className="nx-br-drawer" aria-label="What the agent sees">
      <header>
        <Icon as={ScanText} size={15} /><strong>What the agent sees</strong>
        <span className="nx-head-spacer" />
        <IconButton size="sm" icon={X} label="Close" onClick={onClose} />
      </header>
      <div className="nx-br-drawer-meta">
        <Segmented size="sm" label="How to show it" value={mode} onChange={setMode} options={[{ value: "page", label: "On the page" }, { value: "text", label: "As text" }]} />
        {value ? <span><StatusDot tone={tab.agentGranted ? "live" : "gold"} pulse={tab.agentGranted} />{tab.agentGranted ? "Agent can act" : "Paused"} · {ago(new Date(at).toISOString()) || "now"}</span> : null}
      </div>
      {mode === "text" ? <AgentSees tab={tab} laya={laya} embedded /> : (
        <div className="nx-br-drawer-body nx-scroll" aria-live="polite" aria-busy={status === "loading"}>
          {status === "loading" ? <div className="nx-br-center"><Spinner size={16} /><span>Reading the page…</span></div> : null}
          {status === "error" ? <div className="nx-br-center"><Icon as={TriangleAlert} size={20} /><span>{error || "The page couldn't be read."}</span></div> : null}
          {inputError ? <p className="nx-br-view-note is-inline" role="alert">{inputError}</p> : null}
          {value ? (
            <article className="nx-br-wire">
              <header><h2>{value.title || displayUrl(value.url)}</h2><span className="nx-br-wire-url">{displayUrl(value.url)}</span></header>
              {fields.length ? (
                <section><h3>Fields</h3>
                  <ul className="nx-br-wire-fields">
                    {fields.map(element => (
                      <li key={element.id} className={changed.has(keyOf(element)) ? "is-changed" : ""}>
                        <span>{clean(element.name) || element.role}</span>
                        <span className="nx-br-wire-value">{element.secret ? "Hidden from the agent" : element.value ? String(element.value).slice(0, 160) : "empty"}</span>
                        {!element.secret && element.actions?.includes("fill") ? <form onSubmit={event => { event.preventDefault(); void input(element, "fill", draft[element.id] ?? String(element.value || "")); }}><input aria-label={clean(element.name) || element.role} value={draft[element.id] ?? String(element.value || "")} onChange={event => setDraft(current => ({ ...current, [element.id]: event.target.value }))} /><Button type="submit" size="sm">Apply</Button>{element.actions.includes("submit") ? <Button size="sm" onClick={() => void input(element, "submit")}>Submit</Button> : null}</form> : null}
                        {changed.has(keyOf(element)) ? <small>Just changed</small> : null}
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}
              {headings.length ? <section><h3>Headings</h3><ul className="nx-br-wire-list">{headings.map(element => <li key={element.id}>{clean(element.name)}</li>)}</ul></section> : null}
              {buttons.length ? <section><h3>Buttons</h3><div className="nx-br-wire-chips">{buttons.map(element => <Button key={element.id} size="sm" disabled={!element.actions?.includes("click")} onClick={() => void input(element, "click")}>{clean(element.name)}</Button>)}</div></section> : null}
              {links.length ? <section><h3>Links</h3><div className="nx-br-wire-chips is-links">{links.map(element => <Button key={element.id} size="sm" disabled={!element.actions?.includes("click")} onClick={() => void input(element, "click")}>{clean(element.name)}</Button>)}</div></section> : null}
              {text ? <section><h3>Text</h3><p className="nx-br-wire-text">{text}{value.text?.length > 1600 ? "…" : ""}</p></section> : null}
            </article>
          ) : null}
        </div>
      )}
    </aside>
  );
}

// ---------------------------------------------------------------- reader mode

export function ReaderView({ tab, onClose }) {
  const [view, setView] = useState({ status: "loading" });
  const request = useRef(0);
  const load = useCallback(async () => {
    const ticket = ++request.current;
    setView({ status: "loading" });
    if (tab.loading) return;
    try { const reader = await readTab(tab); if (ticket === request.current) setView({ status: "ready", reader }); }
    catch (error) { if (ticket === request.current) setView({ status: "error", error: error.message || String(error), code: error.code }); }
  }, [tab.id, tab.url, tab.loading, tab.reader?.revision]);
  useEffect(() => { void load(); return () => { request.current += 1; }; }, [load]);
  if (view.status === "loading") return <div className="nx-br-center"><Spinner size={16} /><span>Getting the text of this page…</span></div>;
  if (view.status === "error") {
    return (
      <div className="nx-br-center">
        <Icon as={BookOpen} size={22} />
        <strong>Reader mode couldn't read this page</strong>
        <span>{view.code === "runtime_unavailable" ? "The page has to be open in the Neyvia desktop app first." : view.error}</span>
        <div className="nx-br-row"><Button size="sm" variant="outline" onClick={() => void load()}>Try again</Button><Button size="sm" onClick={onClose}>Show the page</Button></div>
      </div>
    );
  }
  const { reader } = view;
  return (
    <div className="nx-br-reader nx-scroll">
      <article>
        <p className="nx-br-reader-site">{hostOf(reader.url)} · {Math.max(1, Math.round(reader.text.split(/\s+/).length / 230))} min read{reader.truncated ? " · text shortened" : ""}</p>
        <h1>{reader.title}</h1>
        {reader.blocks.length ? reader.blocks.filter(block => block.type !== "h" || block.text !== reader.title).map((block, index) => (block.type === "h" ? <h2 key={index}>{block.text}</h2> : <p key={index}>{block.text}</p>))
          : <p className="nx-br-reader-empty">This page has no article text to read. Show the page instead.</p>}
      </article>
    </div>
  );
}

// ---------------------------------------------------------------- what the agent sees (T18)

function unwrap(data) {
  const result = data?.result ?? data;
  if (result?.ok === false) throw new Error(result.error?.message || result.error || "The agent's view couldn't be read");
  return result;
}

/** The page as the agent's perception layer gives it (neyvia.perception.observe, layer browser). */
export function AgentSees({ tab, laya, embedded = false }) {
  const [state, setState] = useState({ status: "loading" });
  const [view, setView] = useState("readable");
  const read = useCallback(async () => {
    setState(current => ({ ...current, status: current.value ? "refreshing" : "loading" }));
    try {
      // The agent's own path: observe returns the value, or a handle for a large page that it then reads part by part.
      const observe = unwrap(await callTool("neyvia.perception.observe", { layer: "browser", source: { tabId: tab.id } }));
      let value = observe.observed;
      let parts = null;
      if (!value && observe.handle) {
        const part = async (path, limit, offset = 0) => unwrap(await callTool("neyvia.perception.project", { handle: observe.handle, path, limit, offset }));
        const [title, url] = await Promise.all([part("/state/title", 100), part("/state/url", 100)]);
        // Controls come in pages, as the agent reads them; a page too large to paste is asked again smaller.
        const elements = [];
        let total = 0;
        for (let offset = 0, limit = 40; offset < 120 && elements.length < 120;) {
          const page = await part("/state/elements", limit, offset);
          total = page.total ?? total;
          if (page.tooLarge) { if (limit <= 5) break; limit = Math.floor(limit / 2); continue; }
          elements.push(...(page.value || []));
          if (page.nextOffset == null || !page.value?.length) break;
          offset = page.nextOffset;
        }
        value = { layer: "browser", source: { tabId: tab.id }, trust: "untrusted-data", state: { title: title.value, url: url.value, elements } };
        parts = { handle: observe.handle, total, shown: elements.length };
      }
      setState({ status: "ready", value, observe, parts });
    } catch (error) {
      setState({ status: "error", error: error.message });
    }
  }, [tab.id]);
  useEffect(() => { void read(); }, [read, tab.url]);
  const value = state.value;
  const characters = state.observe?.characters ?? (value ? JSON.stringify(value).length : 0);
  const page = value?.state && typeof value.state === "object" ? value.state : null;
  const elements = Array.isArray(page?.elements) ? page.elements : [];
  const Wrap = embedded ? "div" : "aside";
  return (
    <Wrap className="nx-br-sees" aria-label="What the agent sees">
      {embedded ? null : <header className="nx-br-sees-head">
        <Icon as={ScanText} size={15} /><strong>Agent's view</strong>
        <span className="nx-head-spacer" />
        {state.status === "refreshing" ? <Spinner size={12} /> : null}
        <Button size="sm" onClick={() => void read()} disabled={state.status === "loading" || state.status === "refreshing"}>Read again</Button>
      </header>}
      <div className="nx-br-sees-meta">
        <Segmented size="sm" label="How to show the agent's view" value={view} onChange={setView} options={[{ value: "readable", label: "Readable" }, { value: "exact", label: "Exact" }]} />
        {value ? <span>{characters.toLocaleString()} characters · about {approxTokens(characters).toLocaleString()} tokens, no pixels</span> : null}
      </div>
      <div className="nx-br-sees-body nx-scroll" aria-live="polite">
        {state.status === "loading" ? <div className="nx-br-center"><Spinner size={14} /><span>Reading the page as text…</span></div> : null}
        {state.status === "error" ? <div className="nx-br-center"><Icon as={TriangleAlert} size={20} /><span>{state.error}</span></div> : null}
        {value && view === "exact" ? <pre className="nx-br-pre">{JSON.stringify(value, null, 2)}</pre> : null}
        {value && view === "readable" ? (
          <>
            {state.parts ? <p className="nx-br-sees-note">Too large to read at once ({characters.toLocaleString()} characters): the agent gets a handle and reads it part by part. Shown: {state.parts.shown} of {state.parts.total} controls.</p> : null}
            {page?.title ? <p className="nx-br-sees-note"><strong>{page.title}</strong></p> : null}
            {elements.length ? (
              <ul className="nx-br-sees-list">
                {elements.filter(element => element.actions?.length && !(element.actions.length === 1 && element.actions[0] === "scroll")).slice(0, 80).map(element => (
                  <li key={element.id}><code>{element.id}</code><span className="nx-br-sees-role">{element.role}</span><span className="nx-br-sees-name">{clean(element.name) || "(no name)"}{element.value ? <em> = {String(element.value).slice(0, 60)}</em> : null}</span><small>{element.actions.join(", ")}</small></li>
                ))}
              </ul>
            ) : <pre className="nx-br-pre">{outline(value.state).replace(/^\n/, "")}</pre>}
          </>
        ) : null}
      </div>
      <footer className="nx-br-sees-foot">
        <span><Icon as={ShieldAlert} size={12} /> Page text is read as data; it can't give the agent orders.</span>
        <span>Quick judgements (LAYA): {laya?.available ? "ready" : "not connected yet"}</span>
      </footer>
    </Wrap>
  );
}

// ---------------------------------------------------------------- shield

export function ShieldPopover({ anchor, open, onClose, tab, headless }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { setError(""); }, [open, tab?.id]);
  useCover(open);
  if (!tab) return null;
  const agent = tab.engine === "obscura";
  const enabled = tab.shield?.enabled !== false;
  let site = "";
  try { site = new URL(tab.url).hostname; } catch { /* no site on an empty tab */ }
  const allowed = tab.shield?.allowSites?.includes(site) || false;
  const change = async args => {
    setBusy(true); setError("");
    try { await act("shield", { tabId: tab.id, ...args }, { wait: true }); }
    catch (failure) { setError(failure.message || "The protection change didn't complete."); }
    finally { setBusy(false); }
  };
  return (
    <Popover anchor={anchor} open={open} onClose={onClose} placement="bottom-start" width={320} label="Privacy for this site">
      <div className="nx-br-pop">
        <header><Icon as={agent || (enabled && !allowed) ? ShieldCheck : ShieldAlert} size={16} /><strong>{hostOf(tab.url) || "This page"}</strong></header>
        {agent ? (
          <>
            <p>Trackers can't load here: this agent tab only fetches from {hostOf(tab.url)} itself. Every other site's requests are blocked.</p>
            <p>The agent says it is automation ({headless?.automationUserAgent || "automation user agent"}). It never disguises itself.</p>
          </>
        ) : (
          <>
            <p><output aria-label="Blocked requests">{Number(tab.shield?.blockedCount || 0).toLocaleString()}</output> requests blocked in this tab.</p>
            <label className="nx-br-row"><input type="checkbox" checked={enabled} disabled={busy} onChange={event => void change({ enabled: event.target.checked })} />Block known trackers</label>
            <label className="nx-br-row"><input type="checkbox" checked={allowed} disabled={busy || !enabled} onChange={event => void change({ allowSite: event.target.checked })} />Allow requests on this site</label>
            <p>{allowed ? "Requests are allowed on this site. Other sites keep their protection." : enabled ? "Known tracker requests are stopped before they leave the page." : "Tracker blocking is off in this tab."}</p>
            <p>{tab.private ? "Private tab: its temporary profile is deleted when you close it; it isn't saved or added to history." : "This tab uses its space's profile. Your own browsers' profiles are never read."}</p>
            {busy ? <p role="status">Updating protection…</p> : null}
            {error ? <p role="alert">{error}</p> : null}
          </>
        )}
      </div>
    </Popover>
  );
}

// ---------------------------------------------------------------- downloads

export function DownloadsPopover({ anchor, open, onClose, downloads = [] }) {
  useCover(open);
  const rows = [...downloads].reverse().slice(0, 20);
  return (
    <Popover anchor={anchor} open={open} onClose={onClose} placement="top-start" width={320} label="Downloads">
      <div className="nx-br-pop">
        <header><Icon as={Download} size={16} /><strong>Downloads</strong></header>
        {rows.length ? (
          <ul className="nx-br-downloads">
            {rows.map(row => (
              <li key={row.id}>
                <span className="nx-br-dl-name" title={row.path}>{String(row.path || "").split(/[\\/]/).pop()?.replace(/^[0-9a-f-]{36}-/, "") || "download"}</span>
                <small>{row.status === "completed" ? `${formatSize(row.bytes)} · saved` : row.status === "failed" ? "Failed" : row.status === "interrupted" ? "Stopped when the app closed" : "Downloading…"}</small>
              </li>
            ))}
          </ul>
        ) : <p>Nothing downloaded yet. Files land in the browser's own downloads folder on your PC.</p>}
      </div>
    </Popover>
  );
}

// ---------------------------------------------------------------- spaces

/** Arc-like spaces: each its own tabs; a new space can keep its own sign-ins (a separate profile). */
export function SpacesBar({ state, space, onSpace }) {
  const add = useRef(null);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [separate, setSeparate] = useState(false);
  const [error, setError] = useState("");
  useCover(open);
  const current = state.spaces.find(row => row.id === space) || state.spaces[0];
  const create = async event => {
    event.preventDefault();
    setError("");
    try {
      const profileId = separate ? (await act("profile.create", { name })).id : current?.profileId || "default";
      const created = await act("space.create", { name, profileId });
      setOpen(false); setName(""); setSeparate(false);
      onSpace(created.id);
    } catch (failure) { setError(failure.message); }
  };
  return (
    <div className="nx-br-spaces" role="radiogroup" aria-label="Spaces">
      {state.spaces.map(row => (
        <button key={row.id} type="button" role="radio" aria-checked={row.id === space} title={row.name}
          className={`nx-br-space${row.id === space ? " is-on" : ""}`} onClick={() => onSpace(row.id)}>
          <span aria-hidden="true">{row.name.slice(0, 1).toUpperCase()}</span><span className="nx-br-space-name">{row.name}</span>
        </button>
      ))}
      <button ref={add} type="button" className="nx-br-space is-add" aria-label="New space" title="New space" onClick={() => setOpen(true)}><Icon as={Plus} size={14} /></button>
      <Popover anchor={add} open={open} onClose={() => setOpen(false)} placement="top-start" width={280} label="New space">
        <form className="nx-br-pop" onSubmit={create}>
          <header><Icon as={Layers} size={16} /><strong>New space</strong></header>
          <label className="nx-br-field"><span>Name</span><input className="nx-input" value={name} onChange={event => setName(event.target.value)} placeholder="Work" maxLength={80} required /></label>
          <label className="nx-br-check"><input type="checkbox" checked={separate} onChange={event => setSeparate(event.target.checked)} /><span>Separate sign-ins (its own cookies and storage)</span></label>
          {error ? <p className="nx-br-error">{error}</p> : null}
          <div className="nx-br-row"><Button type="submit" size="sm" variant="primary" disabled={!name.trim()}>Create space</Button><Button size="sm" onClick={() => setOpen(false)}>Cancel</Button></div>
        </form>
      </Popover>
    </div>
  );
}
