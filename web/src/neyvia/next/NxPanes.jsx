import { Copy, ExternalLink, FileText } from "lucide-react";
import { useEffect, useState } from "react";
import { act, useBrowser } from "./nxBrowserApi.js";
import { AgentLive, useProjection } from "./NxBrowserParts.jsx";
import { NativeSlot } from "./NxBrowser.jsx";
import "./nxBrowser.css";

import { NxAccounts } from "./NxAccounts.jsx";
import { NxAgentRun } from "./agentview/NxAgentView.jsx";
import { NxSessionsPane } from "./NxSessionsPane.jsx";
import { NxParallel } from "./NxParallel.jsx";
import { NxArtifactPane } from "./NxArtifactPane.jsx";
import { OwnedBrowserPane, pageProjection } from "./NxBrowserPane.jsx";
import { NxOutputs } from "./NxOutputs.jsx";
import { NxPerception } from "./NxPerception.jsx";
import { NxFilePane } from "./NxFilePane.jsx";
import { NxPreviewPane } from "./NxPreviewPane.jsx";
import { ObservedPane, PaneRefused, usePaneObservation } from "./NxPaneObserver.jsx";
import { NxRemote } from "./NxRemote.jsx";
import { NxRuntime } from "./NxRuntime.jsx";
import { NxUsage } from "./NxUsage.jsx";
import { NxAgentsOverview } from "./NxAgentsOverview.jsx";
import { NxTerminalPane } from "./NxTerminalPane.jsx";
import { NxBuilder } from "./NxBuilder.jsx";
import { NxMissions } from "./NxMissions.jsx";
import { NxConductor } from "./NxConductor.jsx";
import { NxReplay } from "./NxReplay.jsx";
import { NxSettings } from "./NxSettings.jsx";
import { LocalOnlyGate } from "./NxLocalOnly.jsx";
import { launcherProjects } from "./nxShellLauncher.js";
import { NxWorkspaceDiff } from "./NxWorkspaceDiff.jsx";
import { NxWorkspacePanel } from "./NxWorkspacePanel.jsx";
import { Button, Icon } from "./nxPrimitives.jsx";
import { os } from "./nxOsStore.js";

// What `pane.show {kind, target}` puts on the stage: a real surface for every
// kind (git diff, the workspace, a web page, a file editor, an agent's
// artifact, a live terminal, the runtime matrix, the app an agent drives).
// Each pane is an ObservedPane: when a pane.show event asked for it, the pane
// that really mounted acknowledges it with what it shows (NxPaneObserver.jsx).

const isUrl = value => /^https?:\/\//i.test(String(value || ""));

function Honest({ icon, title, target, refused, children }) {
  return (
    <div className="nx-pane-honest">
      {refused ? <PaneRefused reason={`${title}${children ? `: ${children}` : ""}`} /> : null}
      <Icon as={icon} size={22} />
      <strong>{title}</strong>
      {target ? (
        <code className="nx-pane-target" title={target}>
          {target}
          <button type="button" aria-label="Copy" title="Copy" onClick={() => void navigator.clipboard?.writeText(target)}><Icon as={Copy} size={13} /></button>
        </code>
      ) : null}
      {children ? <p>{children}</p> : null}
    </div>
  );
}

function BrowserPane({ target }) {
  if (isUrl(target)) return <OwnedBrowserPane target={target} />;
  return <OwnedTabPane target={target} />;
}

function NativeOwnerHandoff({ tab }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (tab.ownerTask?.status !== "needs_owner") return null;
  const resume = async () => {
    setBusy(true); setError("");
    try {
      const result = await act("task.resume", { taskId: tab.ownerTask.taskId });
      if (result.status === "needs_owner") setError("The page still needs your help. Resolve its check here, then resume.");
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  };
  return <div className="nx-br-agent-banner is-waiting">
    <div className="nx-br-agent-say"><strong>This task needs your help</strong><span>{tab.ownerTask.prompt}</span>{error ? <p role="alert">{error}</p> : null}</div>
    <Button size="sm" disabled={busy} onClick={() => void resume()}>{busy ? "Resuming…" : "Resume task"}</Button>
  </div>;
}

function OwnedTabPane({ target }) {
  const { state, error } = useBrowser();
  const observation = usePaneObservation();
  const tab = state?.tabs?.find(row => row.id === target);
  const projection = useProjection(tab);
  const value = projection.status === "ready" ? projection.value : null;
  useEffect(() => {
    if (tab && value) void observation.report({ runtimeId: `browser:${tab.engine || "webview2"}:${tab.id}`, content: pageProjection(value) });
  }, [observation, tab?.id, tab?.engine, value]);
  useEffect(() => {
    if (projection.status === "error" && !value) observation.fail(projection.error || "The page could not be read");
  }, [observation, projection.status, projection.error, value]);
  useEffect(() => { if (tab && tab.live === false) observation.withdraw(); }, [observation, tab?.live]);
  if (!tab) return <Honest icon={ExternalLink} title="Select an owned browser tab" target={target} refused>{error || "Open a browser tab, then show its tab id here."}</Honest>;
  if (tab.engine === "obscura") return <AgentLive tab={tab} projection={projection} sessionId={state?.headless?.sessionId} />;
  if (!state.runtime?.connected) return <Honest icon={ExternalLink} title="The page view is disconnected" target={tab.url} refused>Reconnect Neyvia's desktop page view to use this tab.</Honest>;
  return <div className="nx-pane-browser"><NativeOwnerHandoff tab={tab} /><NativeSlot slot="owner-handoff" tabId={tab.id} className="nx-pane-native" /></div>;
}

// Panes with a runtime of their own report it themselves; every other pane is its own DOM content.
const explicitPane = (kind, target) => ["file", "artifact", "browser", "terminal"].includes(kind)
  || (kind === "preview" && !String(target || "").startsWith("remote"));

/** The pane for a stage, observed when a pane.show event asked for it. */
export function StagePane({ kind, target, request, session, nav }) {
  return (
    <ObservedPane request={request} kind={kind} explicit={explicitPane(kind, target)}>
      <PaneView kind={kind} target={target} session={session} nav={nav} />
    </ObservedPane>
  );
}

export function PaneView({ kind, target, session, nav }) {
  switch (kind) {
    case "accounts":
      return <NxAccounts target={target} />;
    case "settings":
      return <NxSettings target={target} rows={nav.rows} />;
    case "builder":
      return <NxBuilder rows={nav.rows} onOpenChat={nav.onOpenChat} onNewChat={nav.onNewChat} />;
    case "replay":
      return <NxReplay key={target || session?.id} sessionId={target || session?.id} title={session?.title} />;
    case "browser":
      return <BrowserPane target={target} />;
    case "diff":
      if (!session) return <Honest icon={FileText} title="Open a chat to see its diff" target={target} refused>Diffs are read from the open chat's workspace.</Honest>;
      if (!target || target === "workspace" || target === session.cwd) return <NxWorkspacePanel key={session.id} session={session} />;
      return (
        <NxWorkspaceDiff sessionId={session.id} change={{ path: target }} index={0} total={1} version={0}
          onBack={() => os.showPane("diff", "workspace")} onStep={() => {}} />
      );
    case "file":
      if (isUrl(target)) return <NxArtifactPane target={target} />;
      return <NxFilePane target={target} />;
    case "artifact":
      return <NxArtifactPane target={target} />;
    case "terminal":
      return <NxTerminalPane target={target} session={session} />;
    case "runtime":
      return <NxRuntime />;
    case "usage":
      return <NxUsage />;
    case "agents":
      return <NxAgentsOverview onOpenChat={nav.onOpenChat} />;
    case "preview":
      // "remote", "remote:host" or "remote:<connection>": an app on another PC, live (plan 15 T19).
      if (String(target || "").startsWith("remote")) return <NxRemote target={target} />;
      return <NxPreviewPane target={target} session={session} />;
    case "outputs":
      return <NxOutputs key={target} target={target} session={session} />;
    case "perception":
      return <NxPerception key={target} target={target} />;
    case "sessions":
      // Every running session side by side (plan 29): live tails, checklist, tokens, mod chips and actions.
      return <NxSessionsPane nav={nav} />;
    case "parallel":
      // One parallel run (plan 29): the main agent, a lane per track, the merge order and the four actions (target = run id, or the newest).
      return <NxParallel target={target} nav={nav} />;
    case "agentview":
      // One agent run, live and as a time-lapse (target = run key, or its computer-use session / chat id).
      return <NxAgentRun key={target} target={target} />;
    case "mission":
      // "conductor", "conductor:<job id>" or "conductor:new": the Conductor (plan 15 T9) on the same pane kind.
      if (String(target || "").startsWith("conductor")) return <NxConductor target={target} folders={launcherProjects(nav.rows)} onOpenChat={nav.onOpenChat} />;
      return <NxMissions target={target} folders={launcherProjects(nav.rows)} onOpenChat={nav.onOpenChat} />;
    default:
      return <Honest icon={FileText} title={`Unknown pane: ${kind}`} target={target} refused />;
  }
}
