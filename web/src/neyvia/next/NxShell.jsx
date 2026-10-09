import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { LazyMotion, MotionConfig } from "motion/react";

import "./nxTokens.css";
import "./nxThemes.css";
import "./nxShell.css";
import "./nxOs.css";
import "./nxMotion.css";
import "./nxIdentities.css";
import "./nxLook.css";
import { NxBackdrop } from "./NxBackdrop.jsx";
import { NxRain } from "./NxRain.jsx";
import { NxKomorebi } from "./NxKomorebi.jsx";
import { NxThemeAmbient } from "./NxThemeAmbient.jsx";
import { useSunState } from "./nxSun.js";
import { lookAttributes, useLookView } from "./nxLookApi.js";
import { SPRING } from "./nxSpring.js";

const motionFeatures = () => import("./nxMotionFeatures.js").then(module => module.default);
import { NxComposer } from "./NxComposer.jsx";
import { NxNewChat } from "./NxNewChat.jsx";
import { NxSidebar, appLabel, useSidebarRows } from "./NxSidebar.jsx";
import { NxSidebarRail } from "./NxSidebarRail.jsx";
import { NxThread } from "./NxThread.jsx";
import { NxSurfaces, SurfaceSlot } from "./NxPlacement.jsx";
import { NxLauncher } from "./NxLauncher.jsx";
import { NxOnboarding } from "./NxOnboarding.jsx";
import { NxIndicators } from "./NxIndicators.jsx";
import { NxToasts } from "./NxToasts.jsx";
import { NxRemoteBanner } from "./NxRemoteBanner.jsx";
import { NxRemote } from "./NxRemote.jsx";
import { NxCanopy } from "./NxCanopy.jsx";
import { NxSwitcher, useLayers } from "./NxSwitcher.jsx";
import { ArrangeBar, Region, Splitter, WIDTH_VARS, useViewportWidth } from "./NxArrange.jsx";
import { NxHomeWidgets } from "./NxHomeWidgets.jsx";
import { NxBubbles } from "./NxBubbles.jsx";
import { NxPopout } from "./NxPopout.jsx";
import { usePopout } from "./nxPopout.js";
import { DockDragGhost, useDockDrag } from "./NxDockDrag.jsx";
import { NxKeysHelp, NxVoice } from "./NxVoice.jsx";
import { NxBrowserPip } from "./NxBrowserPip.jsx";
import { startDictationIn } from "./NxDictation.jsx";
import { SidePanel, ThreadHeader } from "./NxShellParts.jsx";
import { REGION_LABELS, fitLayout, resetWidth, setWidth, sideOf } from "./nxLayoutModel.js";
import { launcherActions, launcherProjects, runInterfaceAction } from "./nxShellLauncher.js";
import { Sheet, local, useMedia } from "./nxPrimitives.jsx";
import { loadList, openThread, startLive, useNx } from "./nxStore.js";
import { os, useOs } from "./nxOsStore.js";
import { useEmbeddedWorkspaceBridge } from "./NxToolScreens.jsx";
import { startBus } from "./nxBus.js";
import { morph } from "./nxMorph.js";
import { useShellObservation } from './nxShellObserve.js';

function readRoute() {
  const params = new URLSearchParams(window.location.search);
  return { chat: params.get("chat") || "", view: params.get("view") || "" };
}

function writeRoute(next, { replace = false } = {}) {
  const params = new URLSearchParams(window.location.search);
  for (const [key, value] of Object.entries(next)) {
    if (value) params.set(key, value); else params.delete(key);
  }
  const query = params.toString();
  const url = `${window.location.pathname}${query ? `?${query}` : ""}`;
  if (replace) window.history.replaceState(null, "", url); else window.history.pushState(null, "", url);
}

export function NxShell() {
  const phone = useMedia("(max-width: 760px)");
  const sessions = useNx(state => state.sessions);
  const density = useOs(state => state.density);
  const stage = useOs(state => state.stage); // the window beside the chat (nxPlacementModel)
  const sideWindow = useOs(state => state.windows.some(win => win.placement === "side"));
  const fullWindow = useOs(state => state.windows.some(win => win.placement === "full"));
  const layout = useOs(state => state.layout);
  const arranging = useOs(state => state.arranging);
  const viewport = useViewportWidth();
  const rootRef = useRef(null);
  const setupOpen = useOs(state => Boolean(state.onboarding));
  useShellObservation(rootRef);
  useEmbeddedWorkspaceBridge();
  const rows = useSidebarRows();
  const [route, setRoute] = useState(readRoute);
  const [newKey, setNewKey] = useState(0);
  const [panelOpen, setPanelOpen] = useState(() => local.get("panelOpen", false));
  const [panelTab, setPanelTab] = useState(() => local.get("panelTab", "workspace"));
  const [sheetOpen, setSheetOpen] = useState(false);
  const [chatHidden, setChatHidden] = useState(false);
  // The theme on screen: the picked one, or its day/night twin when Follow the sun is on (nxSun.js).
  const sun = useSunState();
  const theme = sun.shown;
  // Ambient light follows activity: still while idle, the sun while a chat works.
  const ambientOn = useOs(state => state.ambient);
  const motion = useOs(state => state.motion);
  const lookView = useLookView();
  const lookProps = lookAttributes(lookView.look, lookView.background);
  const shellSignal = useOs(state => state.appSignals.shell);
  const session = route.chat ? (rows.find(row => row.id === route.chat) || sessions[route.chat]) : null;
  const appName = session ? (session.category === "connected" ? appLabel(session.app) : "Neyvia") : "";
  const calm = density === "calm";
  const layers = useLayers(route.chat);
  const ambient = !ambientOn ? "off" : rows.some(row => row.status === "working") ? "active" : "still";
  // Night Shift running deepens Forest's night (nxMotion.css); any theme may read it.
  const nightShiftRunning = useOs(state => Object.values(state.nightshift).some(task => task.status === "running"));

  useEffect(() => {
    void loadList().then(() => startLive());
    const stopBus = startBus();
    const onPop = () => setRoute(readRoute());
    window.addEventListener("popstate", onPop);
    return () => { window.removeEventListener("popstate", onPop); stopBus(); };
  }, []);

  useEffect(() => { if (route.chat) void openThread(route.chat); }, [route.chat]);
  useEffect(() => { setSheetOpen(false); }, [route.chat]);
  // On a phone the stage opens full screen; on a desktop the chat docks beside it.
  useEffect(() => { setChatHidden(Boolean(stage) && phone); }, [stage, phone]);
  // The chat popped out over the app leaves the dock: the app takes the width, and the chat comes back when the pop-out closes.
  const poppedOut = usePopout(popout => popout.open && Boolean(route.chat) && popout.sessionId === route.chat);
  const dockHidden = useRef(false);
  useEffect(() => {
    if (poppedOut && stage && !phone) { dockHidden.current = true; setChatHidden(true); } else if (!poppedOut && dockHidden.current) { dockHidden.current = false; setChatHidden(false); }
  }, [poppedOut, stage, phone]);
  useLayoutEffect(() => {
    if (!stage || !chatHidden) return;
    const active = document.activeElement;
    if (active === document.body || rootRef.current?.querySelector(".nx-work-chat")?.contains(active)) {
      rootRef.current?.querySelector(".nx-surface.is-main button:not([disabled])")?.focus();
    }
  }, [stage, chatHidden]);

  useEffect(() => {
    document.title = session?.title ? `${session.title} · Neyvia` : "Neyvia";
  }, [session?.title]);

  // The pressed leaf or card grows into the chat column (nxMorph).
  const select = useCallback(id => {
    const go = () => { writeRoute({ chat: id, view: "" }); setRoute({ chat: id, view: "" }); };
    if (id && id !== readRoute().chat) morph(go, ".nx-main .nx-work-chat"); else go();
  }, []);

  const newChat = useCallback((preset = null) => {
    if (preset?.app) local.set("new.app", preset.app);
    if (preset?.folder) local.set("new.folder", { path: preset.folder.path, name: preset.folder.name });
    setNewKey(key => key + 1);
    writeRoute({ chat: "", view: "new" });
    setRoute({ chat: "", view: "new" });
  }, []);

  const back = useCallback(() => {
    writeRoute({ chat: "", view: "" });
    setRoute({ chat: "", view: "" });
  }, []);

  // Bus actions that need the shell's own state (voice control, plan 15 T3).
  const handled = useRef(0);
  useEffect(() => {
    if (!shellSignal || shellSignal.seq <= handled.current) return;
    handled.current = shellSignal.seq;
    const { action, payload } = shellSignal;
    if (action === "session.open") select(String(payload.id));
    else if (action === "newchat.open") {
      if (payload.prompt) local.set("draft.new", String(payload.prompt));
      const app = payload.app === "claude" ? "claude-code" : payload.app;
      newChat({ app, folder: payload.folder?.path ? { path: payload.folder.path, name: payload.folder.name || payload.folder.path } : null });
      if (payload.dictate) setTimeout(() => startDictationIn("new-chat"), 350);
    } else if (action === "composer.send") {
      // Only the box of the chat the command was said in: if Paul moved on meanwhile, nothing is sent.
      const now = readRoute();
      const onScreen = now.chat || "new"; // without a chat, the new-chat box is the one on screen
      const form = document.querySelector(".nx-main .nx-composer");
      const box = form?.querySelector("textarea");
      if (payload.sessionId && String(payload.sessionId) !== onScreen) os.notify({ level: "info", message: "Not sent: a different chat is on screen now." });
      else if (!form || !box?.value.trim()) os.notify({ level: "info", message: "There's nothing in the message box to send." });
      else form.requestSubmit();
    } else if (action === "dictation.start") {
      const kind = payload.target === "notes" ? "notes" : readRoute().chat ? "composer" : "new-chat";
      // The app or chat may still be opening: try for a moment.
      let tries = 0;
      const attempt = () => { if (!startDictationIn(kind) && ++tries < 12) setTimeout(attempt, 150); };
      attempt();
    }
  }, [shellSignal, select, newChat]);

  const sidebarHidden = layout.sidebarHidden;
  const scenes = useOs(state => state.scenes);
  const bubbles = useOs(state => state.bubbles);

  const onAction = useCallback(action => {
    if (action === "refresh") void loadList();
    else if (action === "theme") os.cycleTheme();
    else if (action.startsWith("theme:")) os.setTheme(action.slice(6));
    else runInterfaceAction(action);
  }, []);

  // ---- launcher: what it can search and what its results do (nxShellLauncher) ----
  const floating = bubbles.some(bubble => bubble.id === route.chat);
  // The docked chat can be dragged (or, by keyboard, sent) out of the dock to float; its bubble's Dock button brings it back.
  const docked = Boolean(stage) && !chatHidden && !phone && Boolean(route.chat);
  const { drag: dockDrag, handlers: dockHandlers } = useDockDrag({ sessionId: route.chat, enabled: docked, onFloated: () => setChatHidden(true) });
  const floatOut = useCallback(id => { os.float(id); setChatHidden(true); }, []);
  const dockBubble = useCallback(id => {
    os.unfloat(id);
    if (id !== readRoute().chat) select(id);
    setChatHidden(false);
  }, [select]);
  const toggleChat = useCallback(() => { if (chatHidden && floating) os.unfloat(route.chat); setChatHidden(hidden => !hidden); }, [chatHidden, floating, route.chat]);
  const shellNav = useMemo(() => ({ rows, onOpenChat: select, onNewChat: newChat }), [rows, select, newChat]);
  const projects = useMemo(() => launcherProjects(rows), [rows]);
  const chats = useMemo(() => rows.filter(row => !row.archived).map(row => ({ id: row.id, title: row.title, project: row.project })), [rows]);
  const launcherList = useMemo(() => launcherActions({
    density, theme, arranging, scenes, sidebarHidden, stage, chatId: route.chat, floating, hasPrevious: Boolean(layers[1]),
  }), [density, theme, arranging, scenes, sidebarHidden, stage, route.chat, floating, layers]);

  const onLaunch = useCallback(payload => {
    if (payload.type === "chat") select(payload.id);
    else if (payload.type === "new-chat") newChat({ app: payload.app, folder: payload.folder });
    else if (payload.type === "project") {
      if (payload.project.latest) select(payload.project.latest); else newChat({ folder: payload.project });
    } else if (payload.type === "action") {
      const id = payload.id;
      if (runInterfaceAction(id, { chatId: route.chat, floating })) return;
      if (id === "new-chat") newChat();
      else if (id === "previous-chat" && layers[1]) select(layers[1]);
    }
  }, [select, newChat, layers, route.chat, floating]);

  const selectTab = tab => { setPanelTab(tab); local.set("panelTab", tab); };
  const closePanel = () => { setSheetOpen(false); setPanelOpen(false); local.set("panelOpen", null); };
  // A header button opens its tab, or closes the panel when that tab is already showing.
  const showPanel = tab => {
    const closing = (phone ? sheetOpen : panelOpen) && panelTab === tab;
    selectTab(tab);
    if (phone) setSheetOpen(!closing);
    else { setPanelOpen(!closing); local.set("panelOpen", !closing || null); }
  };

  const showList = phone ? !route.chat && route.view !== "new" && !stage : !sidebarHidden;
  const showMain = !phone || Boolean(route.chat) || route.view === "new" || Boolean(stage);
  // Calm keeps chat + sidebar only; with an app open, the side panel waits unless in Grove.
  const panels = !calm && (!stage || density === "grove");

  // ---- the movable layout: what wants to show, then what fits (nxLayoutModel) ----
  // A window placed in the side panel shows there whatever the density; otherwise the chat's panel as before.
  const panelWanted = !phone && (sideWindow || (panels && panelOpen && Boolean(route.chat && session)));
  const canopyWanted = !phone && !stage && (layout.canopy === "on" || (layout.canopy === "auto" && density === "grove"));
  const defaults = { sidebar: density === "calm" ? 288 : density === "grove" ? 260 : 276, panel: sideWindow ? 480 : 400, canopy: 292, dock: density === "grove" ? 360 : 380 };
  const fit = fitLayout(layout, { viewport, present: { sidebar: showList && !phone, panel: panelWanted, canopy: canopyWanted }, defaults });
  const widthStyle = phone ? undefined : Object.fromEntries(Object.entries(WIDTH_VARS).map(([id, name]) => [name, `${fit.widths[id]}px`]));
  // While dragging only the CSS variable moves; the width is saved on release.
  const liveWidth = id => px => rootRef.current?.style.setProperty(WIDTH_VARS[id], `${px}px`);
  const commitWidth = id => px => os.updateLayout(current => setWidth(current, id, px));
  const splitter = (id, side) => (phone ? null : (
    <Splitter id={id} label={REGION_LABELS[id] || "Chat"} side={side} width={fit.widths[id]}
      live={liveWidth(id)} onCommit={commitWidth(id)} onReset={() => os.updateLayout(current => resetWidth(current, id))} />
  ));
  const dockSide = layout.dock === "left" ? "start" : "end";

  const chat = route.view === "new" || !route.chat ? (
    <NxNewChat key={newKey} phone={phone} onBack={phone ? back : null} onStarted={select}
      sidebarHidden={false} onShowSidebar={os.toggleSidebar}
      home={phone ? null : <NxHomeWidgets rows={rows} onOpenChat={select} onNewChat={newChat} />} />
  ) : (
    <>
      <ThreadHeader session={session || { title: "Loading…" }} onBack={back} phone={phone} panels={panels}
        sidebarHidden={false} onToggleSidebar={os.toggleSidebar}
        panelOpen={phone ? sheetOpen : panelOpen} panelTab={panelTab} onPanel={showPanel}
        floating={bubbles.some(bubble => bubble.id === route.chat)}
        docked={docked} dragHandlers={dockHandlers} onFloatOut={floatOut} />
      <div className="nx-main-body">
        <NxThread sessionId={route.chat} appName={appName} />
        <NxComposer sessionId={route.chat} session={session} appName={appName} onOpenChat={select} />
      </div>
    </>
  );

  const order = id => layout.order.indexOf(id);
  const regions = {
    sidebar: showList ? (
      <Region key="sidebar" id="sidebar" order={order("sidebar")} side={sideOf(layout.order, "sidebar")} landmark={{ role: "complementary", label: "Chats" }}
        splitter={fit.show.sidebar ? splitter("sidebar", sideOf(layout.order, "sidebar")) : null}>
        <NxSidebar activeId={route.chat} onSelect={select} onNewChat={() => newChat()} onAction={onAction}
          onCollapse={phone ? null : os.toggleSidebar} />
      </Region>
    ) : !phone ? (
      // Hidden on a wide screen = the icon rail (T7): chats stay one click away, with hover previews.
      <div key="sidebar" className="nx-region nx-region-rail" data-region="sidebar-rail" style={{ order: order("sidebar") }}
        role="complementary" aria-label="Chats (collapsed)">
        <NxSidebarRail activeId={route.chat} onSelect={select} onNewChat={() => newChat()} onExpand={os.toggleSidebar} />
      </div>
    ) : null,
    main: showMain ? (
      <main key="main" id="nx-main" tabIndex={-1} className="nx-main" data-label="Conversation" style={{ order: order("main") }}>
        <div className="nx-ambient" aria-hidden="true"><NxKomorebi /><NxRain /><NxThemeAmbient /></div>
        <div className={`nx-work${stage ? " is-docked" : ""}${stage && chatHidden ? " is-chat-hidden" : ""}${dockDrag ? " is-dragging-out" : ""}`} data-dock={layout.dock}>
          <div className="nx-work-app" inert={!stage}>
            {stage ? <SurfaceSlot name="main" /> : null}
          </div>
          <div className="nx-work-chat" inert={Boolean(stage && chatHidden)}>
            {chat}
            {stage && !chatHidden ? splitter("dock", dockSide) : null}
          </div>
        </div>
      </main>
    ) : null,
    panel: fit.show.panel ? (
      fit.floatPanel ? (
        <div key="panel" className="nx-panel-overlay" data-side={sideOf(layout.order, "panel")}>{sideWindow ? <SurfaceSlot name="side" /> : <SidePanel session={session} tab={panelTab} onTab={selectTab} onClose={closePanel} />}</div>
      ) : (
        <Region key="panel" id="panel" order={order("panel")} side={sideOf(layout.order, "panel")} splitter={splitter("panel", sideOf(layout.order, "panel"))}
          landmark={sideWindow ? null : { role: "complementary", label: "Chat panel" }}>
          {sideWindow ? <SurfaceSlot name="side" /> : <SidePanel session={session} tab={panelTab} onTab={selectTab} onClose={closePanel} inRegion />}
        </Region>
      )
    ) : null,
    canopy: fit.show.canopy ? (
      <Region key="canopy" id="canopy" order={order("canopy")} side={sideOf(layout.order, "canopy")} splitter={splitter("canopy", sideOf(layout.order, "canopy"))}
        landmark={{ role: "complementary", label: "Canopy" }}>
        <NxCanopy rows={rows} activeId={route.chat} onOpenChat={select} />
      </Region>
    ) : null,
  };

  // Remote control on its own (?view=remote): the same screen and backend state as the pane (plan 15 T19).
  if (route.view === "remote") {
    const params = new URLSearchParams(window.location.search);
    const side = params.get("side") === "host" ? "remote:host" : params.get("connection") ? `remote:${params.get("connection")}` : "remote:use";
    return (
      <div className={`nx nx-root${phone ? " is-phone" : ""}`} data-nx-theme={theme} data-nx-density={density} data-nx-motion={motion === "reduce" ? "reduce" : undefined} {...lookProps} {...sun.attrs} style={sun.style}>
        <NxRemote target={side} standalone />
        <NxRemoteBanner />
        <NxToasts onOpenChat={select} />
      </div>
    );
  }

  return (
    <LazyMotion features={motionFeatures} strict>
    <MotionConfig reducedMotion={motion === "reduce" ? "always" : "user"} transition={SPRING.settle}>
    <div ref={rootRef} className={`nx nx-root${phone ? " is-phone" : ""}${arranging && !phone ? " is-arranging" : ""}${fullWindow ? " has-full" : ""}${setupOpen ? " has-onboarding" : ""}`}
      data-nx-theme={theme} data-nx-density={density} data-nx-ambient={ambient} data-nx-nightshift={nightShiftRunning ? "running" : undefined} data-nx-motion={motion === "reduce" ? "reduce" : undefined} {...lookProps} {...sun.attrs} style={{ ...widthStyle, ...sun.style }}>
      <NxBackdrop background={lookView.background} imageUrl={lookView.image.url} />
      <a className="nx-skip" href="#nx-main" onClick={event => { event.preventDefault(); document.getElementById("nx-main")?.focus(); }}>Skip to conversation</a>
      <div className={`nx-os${phone && sideWindow ? " has-split" : ""}`} inert={setupOpen} aria-hidden={setupOpen || undefined}>
        {layout.order.map(id => regions[id])}
        {phone && sideWindow ? <SurfaceSlot name="side" /> : null}
        {phone && route.chat && session ? (
          <Sheet open={sheetOpen} onClose={closePanel} label="Chat panel">
            <SidePanel session={session} tab={panelTab} onTab={selectTab} onClose={closePanel} sheet />
          </Sheet>
        ) : null}
        {arranging && !phone ? <ArrangeBar showing={{ ...fit.show, panel: fit.show.panel && !fit.floatPanel }} /> : null}
        <NxToasts onOpenChat={select} />
      </div>
      <NxIndicators rows={rows} onOpenChat={select} />
      <NxRemoteBanner />
      {phone ? null : <NxBubbles rows={rows} onOpenChat={select} onDock={stage ? dockBubble : null} />}
      <NxPopout session={session} rows={rows} onOpenChat={select} phone={phone} />
      <DockDragGhost drag={dockDrag} session={session} />
      <NxSwitcher layers={layers} rows={rows} onSelect={select} />
      <NxLauncher actions={launcherList} projects={projects} chats={chats} onRun={onLaunch} />
      <NxOnboarding />
      <NxVoice />
      <NxKeysHelp />
      <NxBrowserPip />
      {/* Every open app and pane, wherever it is placed: beside the chat, side, full screen or a bubble. */}
      <NxSurfaces phone={phone} shell={{ session, nav: shellNav, chatDocked: !chatHidden, onToggleChat: toggleChat }} />
    </div>
    </MotionConfig>
    </LazyMotion>
  );
}
