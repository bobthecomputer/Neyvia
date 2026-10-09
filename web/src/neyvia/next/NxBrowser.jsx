import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  ArrowLeft, ArrowRight, BookOpen, Bot, Columns2, Download, Ellipsis, Globe, History, Layers, MonitorPlay, PanelLeft, PanelTop,
  PictureInPicture2, Pin, PinOff, Plus, Power, RotateCw, ScanText, Search, ShieldAlert, ShieldCheck, TriangleAlert, X,
} from "lucide-react";

import { Button, Icon, IconButton, Popover, Sheet, Spinner, StatusDot, local, useMedia } from "./nxPrimitives.jsx";
import { isDesktopApp } from "./nxApi.js";
import { os } from "./nxOsStore.js";
import { reportAppState } from "./nxBus.js";
import { act, attachRuntime, recallFrame, setPip, setSlot, settled, useAgentRuns, useBrowser, usePip } from "./nxBrowserApi.js";
import { agentIdentity, agentState, displayUrl, groupTabs, hostOf, mirrorOf, parseAddress, presenceOf, rectOf, searchQueryOf, suggest } from "./nxBrowserModel.js";
import { AgentDrawer, AgentLive, AgentPill, CommandBar, DownloadsPopover, Monogram, PermissionRequests, ReaderView, ShieldPopover, SpacesBar, useAgentControls, useCover } from "./NxBrowserParts.jsx";
import { ProviderMark } from "./ProviderMark.jsx";
import "./nxBrowser.css";
import { useSurfaceSize } from "./nxSurfaceSize.js";

// The integrated browser (plan 15 T20, Search + Obscura, plan 29): one browser
// look for every tab. Tabs down the left, one field for the address and the
// search, and the page filling the rest. Paul's own tabs are real WebView2
// pages drawn by the desktop app over the measured area; an agent's tab is the
// same page driven in Obscura, shown as a live frame at the area's real size,
// with the agent's presence kept quiet. State and every change go through the
// PC service (plans/15-handoff.md "## T20").

const desktop = isDesktopApp();

/** A measured place on screen where a native tab is drawn (also used by the stage's browser pane). */
export function NativeSlot({ slot, tabId, className = "", children }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    if (!desktop || !tabId) return undefined;
    const element = ref.current;
    const measure = () => setSlot(slot, { tabId, rect: rectOf(element.getBoundingClientRect()) });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    window.addEventListener("resize", measure);
    return () => { observer.disconnect(); window.removeEventListener("resize", measure); setSlot(slot, null); };
  }, [slot, tabId]);
  return <div ref={ref} className={`nx-br-native ${className}`} data-tab={tabId}>{children}</div>;
}

function Honest({ icon = Globe, title, children, action }) {
  return (
    <div className="nx-br-center">
      <Icon as={icon} size={22} />
      <strong>{title}</strong>
      {children ? <span>{children}</span> : null}
      {action ? <div className="nx-br-row">{action}</div> : null}
    </div>
  );
}

/**
 * What fills one page area: Paul's live page, reader mode, the agent's page as a
 * live frame, or an honest note. Never an empty box.
 */
function PageArea({ tab, slot, ctx, reader, pip, onCloseReader, onOpenReader }) {
  const { state, tabs, presence, controls, startEngine, drawer, toggleDrawer } = ctx;
  const runtime = state.runtime?.connected;
  if (!tab) return null;
  if (tab.engine === "obscura") {
    return <AgentLive tab={tab} sessionId={state.headless?.sessionId} presence={presence(tab)} controls={controls(tab)} bar={false} desktop={desktop} runtimeConnected={runtime}
      drawerOpen={drawer} onDrawer={toggleDrawer} />;
  }
  if (reader) return <ReaderView tab={tab} onClose={onCloseReader} />;
  if (pip === tab.id) {
    return <Honest icon={PictureInPicture2} title="Playing in picture-in-picture" action={<Button size="sm" variant="outline" onClick={() => setPip(null)}>Bring it back here</Button>}>It floats in the corner while you use the rest of Neyvia.</Honest>;
  }
  if (!desktop || !runtime) {
    // No desktop app to draw it: the page is shown through a read-only headless mirror of the same address.
    const mirror = mirrorOf(tabs, tab);
    if (mirror) return <AgentLive tab={mirror} sessionId={state.headless?.sessionId} readOnly bar={false} desktop={desktop} runtimeConnected={runtime} />;
    if (state.headless?.connected) return <div className="nx-br-center" aria-busy="true"><Spinner size={16} /><span>Opening {displayUrl(tab.url)}…</span></div>;
    if (desktop) return <Honest icon={MonitorPlay} title="Starting the page view"><Spinner size={14} /></Honest>;
    return (
      <Honest icon={MonitorPlay} title="This page is drawn by the Neyvia desktop app"
        action={<Button size="sm" variant="outline" icon={Power} onClick={startEngine}>Preview it here</Button>}>
        {displayUrl(tab.url)} opens on your PC in the desktop app. To see it here, start the agent engine: it shows a read-only picture of the page.
      </Honest>
    );
  }
  const last = recallFrame(tab.id);
  return (
    <NativeSlot slot={slot} tabId={runtime && tab.live ? tab.id : null}>
      {runtime && tab.status === "error" ? <Honest icon={TriangleAlert} title="This page didn't load" action={<Button size="sm" variant="outline" icon={RotateCw} onClick={() => void act("tab.reload", { tabId: tab.id })}>Try again</Button>}>{displayUrl(tab.url)}</Honest> : null}
      {/* A tab that was an agent's keeps its last picture while the visible page opens in the same place. */}
      {runtime && !tab.live && tab.status !== "error" ? (last ? <img className="nx-br-last" src={last} alt="" draggable={false} /> : <Honest icon={Globe} title={tab.status === "suspended" ? "Waking this tab" : "Opening"}><Spinner size={14} /></Honest>) : null}
    </NativeSlot>
  );
}

/** One row in the tab column: a page, or an agent's page with its coin. */
function TabRow({ tab, alt, active, onSelect, onClose, presence }) {
  const agent = tab.engine === "obscura";
  const state = agentState(tab, presence);
  const identity = agentIdentity(tab, presence);
  const word = agent ? (state === "waiting" ? "Waiting" : state === "asleep" ? "Engine off" : "") : tab.private ? "Private" : tab.status === "suspended" ? "Asleep" : tab.status === "runtime_needed" ? "" : tab.loading ? "Loading" : "";
  return (
    <li className={`nx-br-tab${active ? " is-on" : ""}${agent ? ` is-agent is-${state}` : ""}${tab.status === "suspended" ? " is-asleep" : ""}`}>
      <button type="button" className="nx-br-tab-main" aria-current={active || undefined} onClick={() => onSelect(tab)} title={`${tab.title || displayUrl(tab.url)}\n${displayUrl(tab.url)}${agent ? `\n${identity.name} is driving this tab` : ""}`}>
        {agent
          ? <span className="nx-br-coin" aria-hidden="true"><ProviderMark id={identity.id} size={13} /></span>
          : <Monogram url={tab.url} favicon={tab.favicon} />}
        <span className="nx-br-tab-title">{(tab.title && tab.title !== hostOf(tab.url) ? tab.title : alt) || tab.title || displayUrl(tab.url)}</span>
        {word ? <span className="nx-br-tab-state">{word}</span> : null}
      </button>
      <IconButton size="sm" icon={X} label={`Close ${tab.title || "tab"}`} className="nx-br-tab-x" onClick={() => onClose(tab)} />
    </li>
  );
}

export function NxBrowser({ target, nav }) {
  const { status, state, error } = useBrowser();
  // A phone, or a narrow window (side panel, bubble): tabs go in a sheet behind one button.
  const narrowScreen = useMedia("(max-width: 760px)");
  const narrowWindow = useSurfaceSize().compact;
  const phone = narrowScreen || narrowWindow;
  const pip = usePip();
  const [space, setSpace] = useState(() => local.get("browser.space", "default"));
  const [placement, setPlacement] = useState(() => local.get("browser.tabs", "vertical"));
  const [sideOpen, setSideOpen] = useState(true);
  const [readers, setReaders] = useState(() => new Set());
  const [drawer, setDrawer] = useState(false);
  const [command, setCommand] = useState(null); // null | "new" | "go"
  const [menu, setMenu] = useState(false);
  const [shield, setShield] = useState(false);
  const [downloads, setDownloads] = useState(false);
  const [sheet, setSheet] = useState(false);
  const [runtimeError, setRuntimeError] = useState("");
  const [busy, setBusy] = useState("");
  const root = useRef(null);
  const menuRef = useRef(null);
  const shieldRef = useRef(null);
  const downloadsRef = useRef(null);
  const addressRef = useRef(null);
  useCover(menu);

  // The desktop app draws visible tabs; attach its runtime when the browser opens.
  useEffect(() => {
    if (!desktop || status !== "ready" || state?.runtime?.connected) return;
    setRuntimeError("");
    attachRuntime().catch(failure => setRuntimeError(failure.message || String(failure)));
  }, [status, state?.runtime?.connected]);

  const allTabs = state?.tabs || [];
  const tabs = useMemo(() => allTabs.filter(tab => !tab.mirrorOf), [allTabs]);
  const spaces = state?.spaces || [];
  const spaceId = spaces.some(row => row.id === space) ? space : spaces[0]?.id || "default";
  // A peeked page floats over the current tab and is not listed until it is opened as a tab.
  const groups = useMemo(() => groupTabs(tabs.filter(tab => tab.id !== state?.peekTabId), spaceId), [tabs, spaceId, state?.peekTabId]);
  const active = tabs.find(tab => tab.id === state?.activeTabId && (tab.spaceId || "default") === spaceId) || null;
  const split = state?.split && tabs.some(tab => tab.id === state.split.left) && tabs.some(tab => tab.id === state.split.right) ? state.split : null;
  const peek = state?.peekTabId ? tabs.find(tab => tab.id === state.peekTabId) : null;
  // History and tab suggestions stay inside the space's profile: a space with separate sign-ins doesn't see the others' pages.
  const profileId = spaces.find(row => row.id === spaceId)?.profileId || "default";
  const scoped = useMemo(() => state && ({ ...state, history: (state.history || []).filter(row => (row.profileId || "default") === profileId), tabs: tabs.filter(tab => (tab.profileId || "default") === profileId) }), [state, tabs, profileId]);
  const runtime = Boolean(state?.runtime?.connected);
  const engineOn = Boolean(state?.headless?.connected);

  useEffect(() => { local.set("browser.space", spaceId); }, [spaceId]);
  useEffect(() => { if (active) local.set(`browser.last.${spaceId}`, active.id); }, [active, spaceId]);
  const sharedView = JSON.stringify({ space: spaceId, activeTabId: active?.id || null,
    reader: active ? readers.has(active.id) : false, split, peek: peek?.id || null,
    tabsPlacement: placement, pip });
  useEffect(() => { if (status === "ready") reportAppState("browser", JSON.parse(sharedView)); }, [status, sharedView]);

  // Who is driving which agent tab (the agent view's runs), only while an agent tab exists.
  const agentTabs = tabs.filter(tab => tab.engine === "obscura");
  const runs = useAgentRuns(agentTabs.length > 0, 600);
  const presenceFor = useCallback(tab => (tab?.engine === "obscura" ? presenceOf(runs, tab) : null), [runs]);

  const run = useCallback(async (label, work) => {
    setBusy(label);
    try { return await work(); }
    catch (failure) { os.notify({ level: "warning", message: failure.message || "The browser refused that." }); return null; }
    finally { setBusy(""); }
  }, []);

  const openUrl = useCallback((url, { engine, private: privateTab = false } = {}) => run("open", () => act("tab.open", { url, spaceId, private: privateTab, ...(engine ? { engine } : {}) })), [run, spaceId]);
  const go = useCallback(url => {
    if (active && active.engine !== "obscura") return run("navigate", () => act("tab.navigate", { tabId: active.id, url }));
    return openUrl(url);
  }, [active, openUrl, run]);
  const select = useCallback(tab => {
    if (!tab) return;
    setSheet(false);
    if ((tab.spaceId || "default") !== spaceId) setSpace(tab.spaceId || "default");
    void run("activate", () => act("tab.activate", { tabId: tab.id }));
  }, [run, spaceId]);
  // Opened for an address (app.open browser <url>, "Open in Browser"): show it, reusing a tab already there.
  const opened = useRef("");
  useEffect(() => {
    if (status !== "ready" || !target || opened.current === target) return;
    opened.current = target;
    const parsed = parseAddress(target);
    if (parsed.kind !== "url" && parsed.kind !== "search") return;
    const existing = tabs.find(tab => tab.url === parsed.url && tab.engine !== "obscura" && !tab.private);
    if (existing) select(existing); else void openUrl(parsed.url);
  }, [status, target, tabs, select, openUrl]);
  const close = useCallback(tab => {
    if (pip === tab.id) setPip(null);
    void run("close", () => act("tab.close", { tabId: tab.id }));
  }, [pip, run]);
  const peekAt = useCallback(url => run("peek", async () => {
    const before = active?.id;
    const opened = await act("tab.open", { url, spaceId });
    await act("peek", { tabId: opened.tabId });
    if (before) await act("tab.activate", { tabId: before });
  }), [active, run, spaceId]);
  const switchSpace = useCallback(id => {
    setSpace(id);
    const remembered = local.get(`browser.last.${id}`, null);
    const target = tabs.find(tab => tab.id === remembered && (tab.spaceId || "default") === id) || tabs.filter(tab => (tab.spaceId || "default") === id).pop();
    if (target) void run("activate", () => act("tab.activate", { tabId: target.id }));
  }, [run, tabs]);
  const promote = useCallback((tab, { keepAgent }) => run("promote", async () => {
    await act("promote", { tabId: tab.id }, { wait: true });
    await act("tab.activate", { tabId: tab.id });
    // A page load revokes agent access, so the grant waits until the visible page has finished loading.
    if (keepAgent) {
      await settled(tab.id);
      await act("tab.grant", { tabId: tab.id, enabled: true });
    }
    os.notify({ level: "success", message: keepAgent ? "The agent's tab is visible now; it keeps working here." : "You have the tab now; the agent is stopped." });
  }), [run]);
  const toggleReader = useCallback(tab => setReaders(current => {
    const next = new Set(current);
    if (next.has(tab.id)) next.delete(tab.id); else next.add(tab.id);
    return next;
  }), []);
  const startSplit = useCallback(() => run("split", async () => {
    if (split) return act("split", { left: null, right: null });
    const other = [...groups.open, ...groups.pinned].reverse().find(tab => tab.id !== active?.id);
    if (!active || !other) { os.notify({ level: "info", message: "Open a second tab to see two side by side." }); return null; }
    return act("split", { left: active.id, right: other.id });
  }), [active, groups, run, split]);
  const startEngine = useCallback(() => run("engine", () => act(engineOn ? "headless.stop" : "headless.start", { port: 48725, assignedPorts: "48725-48729" })), [run, engineOn]);
  const askAgent = useCallback(() => {
    local.set("draft.new", "In the Neyvia browser, open an agent tab (neyvia.browser.open with engine \"obscura\") and ");
    nav?.onNewChat?.();
  }, [nav]);
  const toggleDrawer = useCallback(() => setDrawer(value => !value), []);

  // The page Paul is looking at: his tab, or the mirror that shows it in the web build.
  const needsMirror = !desktop || !runtime;
  const viewTab = active && active.engine !== "obscura" && needsMirror ? mirrorOf(allTabs, active) || active : active;
  const viewPresence = presenceFor(viewTab);
  const agentControls = useAgentControls(viewTab, viewPresence, { canPromote: desktop && runtime, onWatch: () => viewTab && promote(viewTab, { keepAgent: true }), onTakeOver: () => viewTab && promote(viewTab, { keepAgent: false }) });
  const reader = active ? readers.has(active.id) : false;
  const readable = active && active.engine !== "obscura" && desktop && runtime;

  // The web build can't draw Paul's own tabs: each is shown through a read-only headless mirror of its address.
  const mirrorAsked = useRef(new Set());
  useEffect(() => {
    if (status !== "ready" || !engineOn || !needsMirror) return;
    const shown = [active, ...(split ? [tabs.find(tab => tab.id === split.left), tabs.find(tab => tab.id === split.right)] : [])].filter(tab => tab && tab.engine !== "obscura");
    for (const tab of shown) {
      const key = `${tab.id}|${tab.url}`;
      if (mirrorOf(allTabs, tab) || mirrorAsked.current.has(key)) continue;
      mirrorAsked.current.add(key);
      void act("tab.open", { url: tab.url, spaceId: tab.spaceId || "default", engine: "obscura", mirrorOf: tab.id })
        .catch(failure => { mirrorAsked.current.delete(key); if (!/engine_missing|limit/.test(failure.code || "")) os.notify({ level: "info", message: `Can't preview ${displayUrl(tab.url)} here: ${failure.message}` }); });
    }
  }, [status, engineOn, needsMirror, active, split, tabs, allTabs]);
  // A mirror lasts as long as the tab it shows at the address it showed.
  useEffect(() => {
    for (const mirror of allTabs.filter(tab => tab.mirrorOf)) {
      const own = allTabs.find(tab => tab.id === mirror.mirrorOf);
      if (!own || own.url !== mirror.url) { mirrorAsked.current.delete(`${mirror.mirrorOf}|${mirror.url}`); void act("tab.close", { tabId: mirror.id }).catch(() => {}); }
    }
  }, [allTabs]);

  // Keys while the browser is open: Ctrl T new tab, Ctrl K command bar, Ctrl L address, Ctrl W close, Alt arrows back/forward.
  useEffect(() => {
    const onKey = event => {
      const inside = !document.activeElement || document.activeElement === document.body || document.activeElement.closest?.(".nx-br");
      if (!inside) return;
      const key = event.key.toLowerCase();
      if ((event.ctrlKey || event.metaKey) && key === "t") { event.preventDefault(); setCommand("new"); }
      else if ((event.ctrlKey || event.metaKey) && key === "k") { event.preventDefault(); setCommand("go"); }
      else if ((event.ctrlKey || event.metaKey) && key === "l") { event.preventDefault(); addressRef.current?.focus(); addressRef.current?.select(); }
      else if ((event.ctrlKey || event.metaKey) && key === "w" && active) { event.preventDefault(); close(active); }
      else if (event.altKey && event.key === "ArrowLeft" && active) { event.preventDefault(); void act("tab.back", { tabId: active.id }); }
      else if (event.altKey && event.key === "ArrowRight" && active) { event.preventDefault(); void act("tab.forward", { tabId: active.id }); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, close]);

  // When the browser is the pane's content, its top line IS the pane's title line: the controls move into the
  // pane's own header (which stays the drag handle where nothing is pressed), so no second bar sits above the page.
  const [headHost, setHeadHost] = useState(null);
  useLayoutEffect(() => {
    const head = phone ? null : root.current?.closest(".nx-stage")?.querySelector(":scope > .nx-stage-head");
    if (!head) { setHeadHost(null); return undefined; }
    const host = document.createElement("div");
    host.className = "nx-br-headbar";
    head.insertBefore(host, head.querySelector(".nx-head-spacer"));
    setHeadHost(host);
    return () => { host.remove(); setHeadHost(null); };
  }, [status, phone]);

  if (status === "loading") return <div className="nx-br"><Honest icon={Globe} title="Opening the browser"><Spinner size={14} /></Honest></div>;
  if (status === "error") {
    return <div className="nx-br"><Honest icon={TriangleAlert} title="The browser couldn't be reached" action={<Button size="sm" variant="outline" onClick={() => window.location.reload()}>Try again</Button>}>{error}</Honest></div>;
  }

  const actions = [
    { id: "split", icon: Columns2, title: split ? "Close split view" : "Split view with the last tab", hint: "", keywords: ["split", "side"], run: startSplit },
    ...(readable ? [{ id: "reader", icon: BookOpen, title: reader ? "Show the page" : "Reader mode", keywords: ["reader", "read", "article"], run: () => toggleReader(active) }] : []),
    ...(active && desktop && active.engine !== "obscura" ? [{ id: "pip", icon: PictureInPicture2, title: "Picture in picture", keywords: ["pip", "float", "video"], run: () => setPip(active.id) }] : []),
    { id: "tabs", icon: placement === "vertical" ? PanelTop : PanelLeft, title: placement === "vertical" ? "Tabs on top" : "Tabs on the side", keywords: ["tabs", "vertical", "top", "layout"], run: () => { const next = placement === "vertical" ? "top" : "vertical"; setPlacement(next); local.set("browser.tabs", next); } },
    { id: "agent-tab", icon: Bot, title: "Give an agent a task in the browser", keywords: ["agent", "task", "automate", "obscura"], run: askAgent },
    { id: "engine", icon: Power, title: engineOn ? "Stop the agent engine" : "Start the agent engine", keywords: ["engine", "obscura", "headless", "agent"], run: startEngine },
    { id: "sees", icon: ScanText, title: drawer ? "Hide what the agent sees" : "What the agent sees", keywords: ["agent", "text", "perception", "see"], run: toggleDrawer },
  ];

  const toolbarTab = active;
  const addressValue = toolbarTab ? (searchQueryOf(toolbarTab.url) || displayUrl(toolbarTab.url)) : "";

  // One pill in the address field, for whatever the page is: an agent's tab or the web build's read-only preview.
  const ctx = { state, tabs: allTabs, presence: presenceFor, startEngine, drawer, toggleDrawer, controls: tab => (tab && tab.id === viewTab?.id ? agentControls : null) };
  const pill = viewTab?.engine === "obscura" && !viewTab.mirrorOf
    ? <AgentPill tab={viewTab} controls={agentControls} drawerOpen={drawer} onDrawer={toggleDrawer} />
    : viewTab?.mirrorOf
      ? <span className="nx-br-pill is-preview" role="status"><span className="nx-br-pill-mark"><Icon as={MonitorPlay} size={14} /></span><span className="nx-br-pill-say">Read-only preview. Open it in the desktop app to use this page yourself.</span></span>
      : null;

  const sidebar = (
    <nav className="nx-br-side" aria-label="Tabs">
      <div className="nx-br-side-head">
        <SpacesBar state={state} space={spaceId} onSpace={switchSpace} />
        {phone ? null : <IconButton size="sm" icon={PanelLeft} label="Hide tabs" onClick={() => setSideOpen(false)} />}
      </div>
      {groups.pinned.length ? (
        <ul className="nx-br-pins" aria-label="Pinned tabs">
          {groups.pinned.map(tab => (
            <li key={tab.id}>
              <button type="button" className={`nx-br-pin${tab.id === active?.id ? " is-on" : ""}`} title={tab.title || displayUrl(tab.url)} aria-label={tab.title || displayUrl(tab.url)} onClick={() => select(tab)}>
                <Monogram url={tab.url} favicon={tab.favicon} size="lg" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <button type="button" className="nx-br-newtab" onClick={() => setCommand("new")}>
        <Icon as={Plus} size={15} /><span>New tab</span><kbd className="nx-kbd">Ctrl T</kbd>
      </button>
      <div className="nx-br-side-scroll nx-scroll">
        <ul className="nx-br-tabs">
          {groups.list.map(tab => <TabRow key={tab.id} tab={tab} alt={mirrorOf(allTabs, tab)?.title} active={tab.id === active?.id} presence={presenceFor(tab)} onSelect={select} onClose={close} />)}
        </ul>
      </div>
      <footer className="nx-br-side-foot">
        <span className="nx-head-spacer" />
        <IconButton ref={downloadsRef} size="sm" icon={Download} label="Downloads" onClick={() => setDownloads(value => !value)} />
        <IconButton ref={menuRef} size="sm" icon={Ellipsis} label="More" onClick={() => setMenu(value => !value)} />
      </footer>
    </nav>
  );

  const topTabs = (
    <div className="nx-br-strip" role="tablist" aria-label="Tabs">
      {[...groups.pinned, ...groups.list].map(tab => (
        <div key={tab.id} className={`nx-br-chip${tab.id === active?.id ? " is-on" : ""}`}>
          <button type="button" role="tab" aria-selected={tab.id === active?.id} onClick={() => select(tab)} title={tab.title || displayUrl(tab.url)}>
            {tab.engine === "obscura" ? <span className="nx-br-coin" aria-hidden="true"><ProviderMark id={agentIdentity(tab, presenceFor(tab)).id} size={12} /></span> : <Monogram url={tab.url} favicon={tab.favicon} size="sm" />}
            <span>{tab.pinned ? "" : tab.title || displayUrl(tab.url)}</span>
          </button>
          {tab.pinned ? null : <IconButton size="sm" icon={X} label={`Close ${tab.title || "tab"}`} onClick={() => close(tab)} />}
        </div>
      ))}
      <IconButton size="sm" icon={Plus} label="New tab (Ctrl T)" onClick={() => setCommand("new")} />
      <span className="nx-head-spacer" />
      <IconButton size="sm" icon={PanelLeft} label="Tabs on the side" onClick={() => { setPlacement("vertical"); local.set("browser.tabs", "vertical"); }} />
    </div>
  );

  const splitTabs = split ? [tabs.find(tab => tab.id === split.left), tabs.find(tab => tab.id === split.right)] : null;
  const showSide = !phone && placement === "vertical" && sideOpen;

  const barContent = (
    <>
          {phone ? <IconButton icon={Layers} label="Tabs and spaces" onClick={() => setSheet(true)} /> : placement === "vertical" && !sideOpen ? <IconButton icon={PanelLeft} label="Show tabs" onClick={() => setSideOpen(true)} /> : null}
          {phone ? null : (
            <>
              <IconButton icon={ArrowLeft} label="Back (Alt Left)" disabled={!toolbarTab} onClick={() => void act("tab.back", { tabId: toolbarTab.id })} />
              <IconButton icon={ArrowRight} label="Forward (Alt Right)" disabled={!toolbarTab} onClick={() => void act("tab.forward", { tabId: toolbarTab.id })} />
              <IconButton icon={RotateCw} label="Reload" disabled={!toolbarTab} onClick={() => void act("tab.reload", { tabId: toolbarTab.id })} />
            </>
          )}
          <AddressField key={toolbarTab?.id || "none"} inputRef={addressRef} value={addressValue} state={scoped} tab={toolbarTab} pill={pill}
            onGo={go} onTab={id => select(tabs.find(tab => tab.id === id))} onNewTab={openUrl} />
          {readable ? <IconButton icon={BookOpen} label={reader ? "Show the page" : "Reader mode"} active={reader} onClick={() => toggleReader(toolbarTab)} /> : null}
          {phone ? null : <IconButton icon={Columns2} label={split ? "Close split view" : "Split view"} active={Boolean(split)} onClick={() => void startSplit()} />}
          <IconButton ref={shieldRef} icon={toolbarTab && toolbarTab.engine !== "obscura" && toolbarTab.shield?.enabled === false ? ShieldAlert : ShieldCheck} label="Privacy for this site" disabled={!toolbarTab} onClick={() => setShield(value => !value)} />
          {toolbarTab?.agentGranted && toolbarTab.engine !== "obscura" ? (
            <button type="button" className="nx-br-agentchip" onClick={() => void act("tab.grant", { tabId: toolbarTab.id, enabled: false })} title="An agent can act in this tab. Take it back."><StatusDot tone="gold" /><span>Agent on</span><strong>Stop</strong></button>
          ) : null}
          {phone || showSide ? null : <IconButton ref={menuRef} icon={Ellipsis} label="More" onClick={() => setMenu(value => !value)} />}
    </>
  );

  const pageFor = (tab, slot) => (
    <PageArea tab={tab} slot={slot} ctx={ctx} reader={readers.has(tab.id)} pip={pip}
      onCloseReader={() => toggleReader(tab)} onOpenReader={() => toggleReader(tab)} />
  );

  return (
    <div ref={root} className={`nx-br${showSide ? " has-side" : ""}${drawer && viewTab ? " has-drawer" : ""}`}>
      {showSide ? sidebar : null}
      <section className="nx-br-main" aria-label="Browser">
        {!phone && placement === "top" ? topTabs : null}
        {headHost ? createPortal(barContent, headHost) : <div className="nx-br-bar">{barContent}</div>}
        {runtimeError ? <p className="nx-br-banner is-error" role="status"><Icon as={TriangleAlert} size={14} />Pages can't be drawn in this window: {runtimeError}</p> : null}
        <PermissionRequests requests={state.permissions || []} />
        <div className="nx-br-stage">
          {splitTabs ? (
            <div className="nx-br-split">
              {splitTabs.map((tab, index) => (
                <div key={tab.id} className={`nx-br-pane${tab.id === active?.id ? " is-on" : ""}`}>
                  <header className="nx-br-pane-head">
                    <button type="button" onClick={() => select(tab)}><Monogram url={tab.url} size="sm" /><span>{tab.title || displayUrl(tab.url)}</span></button>
                    {index === 1 ? <IconButton size="sm" icon={X} label="Close split view" onClick={() => void act("split", { left: null, right: null })} /> : null}
                  </header>
                  {peek ? <div className="nx-br-native" /> : pageFor(tab, `split-${index}`)}
                </div>
              ))}
            </div>
          ) : active ? (peek ? <div className="nx-br-native" /> : pageFor(active, "main")) : (
            <StartPage state={scoped} onGo={openUrl} />
          )}
          {peek ? (
            <div className="nx-br-peek-scrim">
              <div className="nx-br-peek" role="dialog" aria-label={`Peek: ${peek.title || displayUrl(peek.url)}`}>
                <header className="nx-br-pane-head">
                  <Monogram url={peek.url} favicon={peek.favicon} size="sm" /><span className="nx-br-peek-title">{peek.title || displayUrl(peek.url)}</span>
                  <Button size="sm" variant="outline" onClick={() => void run("peek", async () => { await act("peek", { tabId: null }); await act("tab.activate", { tabId: peek.id }); })}>Open as a tab</Button>
                  <IconButton size="sm" icon={X} label="Close peek" onClick={() => void run("peek", async () => { await act("peek", { tabId: null }); await act("tab.close", { tabId: peek.id }); })} />
                </header>
                {pageFor(peek, "peek")}
              </div>
            </div>
          ) : null}
          {drawer && viewTab ? <AgentDrawer tab={viewTab} laya={state.laya} onClose={() => setDrawer(false)} /> : null}
        </div>
      </section>

      <Popover anchor={menuRef} open={menu} onClose={() => setMenu(false)} placement={showSide || phone ? "top-start" : "bottom-end"} width={260} label="Browser menu">
        <div className="nx-menu" role="menu">
          {[
            { icon: ShieldCheck, label: "New private tab", run: () => setCommand("private") },
            ...(active && active.engine !== "obscura" ? [
              { icon: active.pinned ? PinOff : Pin, label: active.pinned ? "Unpin tab" : "Pin tab", run: () => act("tab.update", { tabId: active.id, pinned: !active.pinned }) },
              { icon: active.agentGranted ? ShieldCheck : Bot, label: active.agentGranted ? "Stop agents in this tab" : "Let agents act in this tab", run: () => act("tab.grant", { tabId: active.id, enabled: !active.agentGranted }) },
              ...(desktop ? [{ icon: PictureInPicture2, label: "Picture in picture", run: () => setPip(active.id) }] : []),
            ] : []),
            { icon: History, label: "History", run: () => setCommand("go") },
            { icon: History, label: "Clear this profile's history", run: () => run("history", async () => {
              const result = await act("history.clear", { profileId }, { wait: true });
              os.notify({ level: "success", message: result.status === "native_cleanup_pending" ? "History cleared. Native cleanup will finish when this profile opens a tab." : "History cleared for this profile." });
            }) },
            { icon: placement === "vertical" ? PanelTop : PanelLeft, label: placement === "vertical" ? "Tabs on top" : "Tabs on the side", run: () => { const next = placement === "vertical" ? "top" : "vertical"; setPlacement(next); local.set("browser.tabs", next); } },
            { icon: Bot, label: "Give an agent a task", run: askAgent },
            { icon: Power, label: engineOn ? "Stop the agent engine" : "Start the agent engine", run: startEngine },
            { icon: Search, label: "Command bar (Ctrl K)", run: () => setCommand("go") },
          ].map(item => (
            <button key={item.label} type="button" role="menuitem" className="nx-menu-item" onClick={() => { setMenu(false); void Promise.resolve(item.run()).catch(failure => os.notify({ level: "warning", message: failure.message })); }}>
              <Icon as={item.icon} size={15} /><span>{item.label}</span>
            </button>
          ))}
          <div className="nx-menu-sep" />
          <p className="nx-br-menu-note">Private tabs use temporary profiles. Agents always say they are automation.</p>
        </div>
      </Popover>
      <ShieldPopover anchor={shieldRef} open={shield} onClose={() => setShield(false)} tab={toolbarTab} headless={state.headless} />
      <DownloadsPopover anchor={downloadsRef} open={downloads} onClose={() => setDownloads(false)} downloads={state.downloads} />
      <CommandBar open={Boolean(command)} onClose={() => setCommand(null)} state={scoped} title={command === "private" ? "New private tab" : command === "new" ? "New tab" : "Command bar"} actions={command === "private" ? [] : actions}
        onGo={url => (command === "private" ? openUrl(url, { private: true }) : command === "new" ? openUrl(url) : go(url))} onPeek={command === "private" ? url => openUrl(url, { private: true }) : peekAt} onTab={id => select(tabs.find(tab => tab.id === id))} />
      {phone ? <Sheet open={sheet} onClose={() => setSheet(false)} title="Tabs">{sidebar}</Sheet> : null}
    </div>
  );
}

/** The single address and search field, with history autocomplete and, for an agent's page, its pill. */
function AddressField({ inputRef, value, state, tab, pill, onGo, onTab, onNewTab }) {
  const [text, setText] = useState(value);
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(-1);
  const wrap = useRef(null);
  useEffect(() => { setText(value); }, [value]);
  // Nothing open: the field is ready for typing, with recent pages listed below it.
  useEffect(() => { if (!tab) inputRef.current?.focus(); }, [tab, inputRef]);
  useCover(open);
  const rows = useMemo(() => (open && (tab || text) ? suggest(text === value ? "" : text, { tabs: state.tabs, history: state.history }, 6) : []), [open, tab, text, value, state.tabs, state.history]);
  const submit = (raw, { newTab = false } = {}) => {
    const parsed = parseAddress(raw);
    if (parsed.kind === "blocked") { os.notify({ level: "info", message: parsed.reason }); return; }
    if (parsed.kind === "empty") return;
    setOpen(false);
    inputRef.current?.blur();
    if (newTab || !tab) void onNewTab(parsed.url); else void onGo(parsed.url);
  };
  const choose = row => {
    setOpen(false);
    if (row.type === "tab") onTab(row.tabId); else submit(row.url);
  };
  const onKey = event => {
    if (event.key === "Escape") { setText(value); setOpen(false); }
    else if (event.key === "ArrowDown") { event.preventDefault(); setOpen(true); setIndex(current => Math.min(rows.length - 1, current + 1)); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setIndex(current => Math.max(-1, current - 1)); }
    else if (event.key === "Enter") { event.preventDefault(); if (index >= 0 && rows[index]) choose(rows[index]); else submit(text, { newTab: event.altKey }); }
  };
  return (
    <div ref={wrap} className={`nx-br-address${pill ? " has-pill" : ""}`}>
      <span className="nx-br-address-mark" aria-hidden="true">{tab ? <Monogram url={tab.url} favicon={tab.favicon} size="sm" /> : <Icon as={Search} size={14} />}</span>
      <input ref={inputRef} value={text} spellCheck={false} placeholder="Search or type an address" aria-label="Address and search"
        role="combobox" aria-expanded={open && rows.length > 0} aria-controls="nx-br-suggest" aria-autocomplete="list"
        aria-activedescendant={index >= 0 ? `nx-br-suggest-${index}` : undefined}
        onFocus={event => { event.target.select(); setOpen(true); setIndex(-1); }} onBlur={() => setTimeout(() => setOpen(false), 120)}
        onChange={event => { setText(event.target.value); setOpen(true); setIndex(-1); }} onKeyDown={onKey} />
      {tab?.loading && tab.status !== "runtime_needed" ? <Spinner size={12} /> : null}
      {pill}
      {open && rows.length ? (
        <ul id="nx-br-suggest" className="nx-br-suggest" role="listbox" aria-label="Suggestions">
          {rows.map((row, position) => (
            <li key={`${row.type}:${row.tabId || row.url}`} id={`nx-br-suggest-${position}`} role="option" aria-selected={position === index}
              className={position === index ? "is-on" : ""} onMouseDown={event => { event.preventDefault(); choose(row); }}>
              <Monogram url={row.url} size="sm" />
              <span className="nx-br-suggest-title">{row.title || displayUrl(row.url)}</span>
              <small>{row.type === "tab" ? "Switch to tab" : displayUrl(row.url)}</small>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** No tab open: no start page, only the pages visited before, in one quiet list under the field. */
function StartPage({ state, onGo }) {
  const recent = suggest("", { history: state.history }, 8);
  return (
    <div className="nx-br-start nx-scroll">
      {recent.length ? (
        <ul className="nx-br-start-list" aria-label="Recent pages">
          {recent.map(row => (
            <li key={row.url}><button type="button" onClick={() => void onGo(row.url)}><Monogram url={row.url} size="sm" /><span>{row.title || displayUrl(row.url)}</span><small>{displayUrl(row.url)}</small></button></li>
          ))}
        </ul>
      ) : <p className="nx-br-start-note">Type an address or a search above. Pages you visit appear here.</p>}
    </div>
  );
}

/**
 * Picture in picture, shell-wide: the chosen tab keeps playing in a corner
 * while Paul uses the rest of Neyvia (desktop app only: the page is native).
 */
export function PipFrame({ pip }) {
  const { state } = useBrowser();
  const tab = pip ? state?.tabs?.find(row => row.id === pip) : null;
  useEffect(() => { if (pip && state && !tab) setPip(null); }, [pip, state, tab]);
  if (!tab) return null;
  return (
    <div className="nx-br-pip" role="complementary" aria-label={`Picture in picture: ${tab.title || displayUrl(tab.url)}`}>
      <header>
        <Monogram url={tab.url} size="sm" /><span>{tab.title || displayUrl(tab.url)}</span>
        <IconButton size="sm" icon={Globe} label="Back to the tab" onClick={() => { setPip(null); os.openApp("browser", "", null); void act("tab.activate", { tabId: tab.id }); }} />
        <IconButton size="sm" icon={X} label="Close picture in picture" onClick={() => setPip(null)} />
      </header>
      <NativeSlot slot="pip" tabId={state.runtime?.connected && tab.live ? tab.id : null} />
    </div>
  );
}
