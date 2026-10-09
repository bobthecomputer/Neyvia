import { Suspense, lazy } from "react";
import { AppWindow, BookOpen, MessageSquare, X } from "lucide-react";

import { StagePane } from "./NxPanes.jsx";
import { Icon, IconButton, Spinner } from "./nxPrimitives.jsx";
import { os } from "./nxOsStore.js";
import { SHELL_APPS, findApp, useApps } from "./nxApps.js";
import { TOOL_TITLES, NxToolScreen, isToolScreen } from "./NxToolScreens.jsx";
import { CommentsLayer, StageTools } from "./NxComments.jsx";

// The stage: an app or a pane fills the main area while the conversation
// docks beside it (NxShell owns the dock). App screens load on demand so the
// chat bundle stays small.

// App id -> its user side. An app the registry marks ready without an entry
// here is usable by the model only; the stage says so.
const APP_VIEWS = {
  "scroll-generator": lazy(() => import("./NxScrollStudy.jsx").then(module => ({ default: module.NxScrollStudy }))),
  pdf: lazy(() => import("./NxPdfApp.jsx").then(module => ({ default: module.NxPdfApp }))),
  awareness: lazy(() => import("./NxAwareness.jsx").then(module => ({ default: module.NxAwareness }))),
  notes: lazy(() => import("./NxNotesApp.jsx").then(module => ({ default: module.NxNotesApp }))),
  files: lazy(() => import("./NxFilesApp.jsx").then(module => ({ default: module.NxFilesApp }))),
  "mobile-studio": lazy(() => import("./NxMobileStudio.jsx").then(module => ({ default: module.NxMobileStudio }))),
  browser: lazy(() => import("./NxBrowser.jsx").then(module => ({ default: module.NxBrowser }))),
  "hill-climb": lazy(() => import("./NxEvolver.jsx").then(module => ({ default: module.NxEvolver }))),
  laya: lazy(() => import("./NxLaya.jsx").then(module => ({ default: module.NxLayaApp }))),
  // The 3D studio is Game Dev's Browser 3D scene editor, opened on its own.
  ...gameDevViews(["godot", "unity", "roblox", "asset-checks", "playtest", "3d-studio"]),
  ...Object.fromEntries(SHELL_APPS.map(app => [app.id, app.view])),
};

// Registry apps whose user side is a tool screen (NxToolScreens), reused as is.
const APP_ALIASES = { "image-studio": "image-playground", research: "citecraft" };

// The Game Dev suite is one screen (NxGameDev.jsx) with a tab per editor; each launcher app opens its tab.
function gameDevViews(apps) {
  return Object.fromEntries(apps.map(app => [app, lazy(() => import("./NxGameDev.jsx").then(module => ({
    default: function GameDevApp(props) { return <module.NxGameDev {...props} app={app} />; },
  })))]));
}

// Apps of the shell itself, not in the launcher registry.
const APP_TITLES = { browser: "Browser", "3d-studio": "3D Studio", laya: "LAYA", research: "Research", "image-studio": "Image Studio", ...Object.fromEntries(SHELL_APPS.map(app => [app.id, app.name])) };

const PANE_TITLES = { diff: "Changes", file: "File", artifact: "Artifact", terminal: "Terminal", browser: "Browser", mission: "Missions", replay: "Replay", builder: "Builder", accounts: "Accounts", runtime: "Runtimes", settings: "Settings", preview: "Preview", outputs: "Outputs", perception: "What the agent sees", agentview: "Agent at work", sessions: "Sessions", usage: "Usage", agents: "Agents overview", parallel: "Parallel branches" };

function AppBody({ stage, session, nav, onShowChat, readOnly }) {
  const { suites } = useApps();
  const found = findApp(suites, stage.app);
  const View = APP_VIEWS[stage.app];
  const tool = APP_ALIASES[stage.app] || stage.app;
  // Tool screens (App Factory, Harnesses, Lab…) run here unchanged, on the same backend (NxToolScreens).
  if (!View && (isToolScreen(tool) || tool === "agent")) {
    return <NxToolScreen app={tool} target={stage.target} session={session} nav={nav} onShowChat={onShowChat} readOnly={readOnly} />;
  }
  // A user side that exists opens when asked (the model's pdf.open), whatever the registry says.
  if (View) {
    return <Suspense fallback={<div className="nx-stage-loading"><Spinner size={16} /></div>}><View target={stage.target} session={session} nav={nav} onShowChat={onShowChat} /></Suspense>;
  }
  return (
    <div className="nx-pane-honest">
      <Icon as={AppWindow} size={22} />
      <strong>{found?.app.name || stage.app}</strong>
      <p>{found?.app.status === "ready"
        ? "The model can already use this app. Its screen is not in this build of the interface yet."
        : "This app is coming. It is announced in the launcher and not usable yet."}</p>
      {found?.app.manual ? <p className="nx-stage-manual"><Icon as={BookOpen} size={13} /> Manual: <code>{found.app.manual}</code></p> : null}
    </div>
  );
}

export function stageTitle(stage, suites) {
  if (!stage) return "";
  if (stage.type === "pane" && stage.kind === "preview" && String(stage.target || "").startsWith("remote")) return "Remote control";
  if (stage.type === "pane") return stage.kind === "mission" && String(stage.target || "").startsWith("conductor") ? "Conductor" : PANE_TITLES[stage.kind] || stage.kind;
  return findApp(suites, stage.app)?.app.name || TOOL_TITLES[stage.app] || APP_TITLES[stage.app] || stage.app;
}

/**
 * One open app or pane, in whatever place it has (NxPlacement draws the
 * window; this is its title bar and body). `controls` are the placement
 * buttons; `headProps` make the title bar a drag handle.
 */
export function NxStage({ stage, session, chatDocked, onToggleChat, phone, nav, placement = "main", controls = null, headProps = null, onClose = os.closeStage, readOnly = false }) {
  const { suites } = useApps();
  const found = stage.type === "app" ? findApp(suites, stage.app) : null;
  const title = stageTitle(stage, suites);
  const detail = stage.type === "app" && !found && TOOL_TITLES[stage.app] ? "" : stage.type === "pane" ? (stage.kind === "replay" ? session?.title : stage.kind === "browser" || stage.kind === "mission" || stage.kind === "builder" || stage.kind === "accounts" || stage.kind === "runtime" || stage.kind === "settings" || stage.kind === "preview" || stage.kind === "outputs" || stage.kind === "perception" || stage.kind === "agentview" || stage.kind === "sessions" || stage.kind === "usage" || stage.kind === "parallel" ? "" : stage.target) : found?.suite.name;
  const beside = placement === "main";
  return (
    <section className="nx-stage" aria-label={title} data-placement={placement}>
      <header className={`nx-stage-head${headProps ? " is-handle" : ""}`} {...(headProps || {})}>
        <div className="nx-stage-title">
          <strong>{title}</strong>
          {detail && placement !== "bubble" ? <span title={detail}>{detail}</span> : null}
        </div>
        <div className="nx-head-spacer" />
        <StageTools stage={stage} session={session} title={title} phone={phone} />
        {controls}
        {beside && onToggleChat && (phone || !chatDocked) ? <IconButton icon={MessageSquare} label={chatDocked ? "Hide chat" : "Show chat"} active={chatDocked} onClick={onToggleChat} /> : null}
        <IconButton icon={X} label={`Close ${title}`} onClick={onClose} />
      </header>
      <div className="nx-stage-body" key={stage.type === "pane" ? `${stage.kind}:${stage.target}` : stage.app}>
        {stage.type === "pane" ? <StagePane kind={stage.kind} target={stage.target} request={stage.request} session={session} nav={nav} /> : <AppBody stage={stage} session={session} nav={nav} onShowChat={chatDocked ? undefined : onToggleChat} readOnly={readOnly} />}
      </div>
      <CommentsLayer stage={stage} session={session} title={title} />
    </section>
  );
}
