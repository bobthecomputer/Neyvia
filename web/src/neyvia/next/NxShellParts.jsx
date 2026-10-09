import { Brain, ChevronLeft, FolderOpen, GitBranch, History, Info, Monitor, PanelLeftOpen, PictureInPicture2, X } from "lucide-react";
import { NxMemoryPanel } from "./NxMemoryPanel.jsx";

import { ProviderMark } from "./ProviderMark.jsx";
import { NxWorkspacePanel } from "./NxWorkspacePanel.jsx";
import { appLabel, markFor } from "./NxSidebar.jsx";
import { Icon, IconButton } from "./nxPrimitives.jsx";
import { os } from "./nxOsStore.js";

// The chat's header and its side panel (Workspace, Details), split from NxShell.

function DetailsBody({ session }) {
  const rows = [
    ["App", session.category === "connected" ? appLabel(session.app) : session.category === "hybrid" ? `Neyvia Hybrid · ${appLabel(session.runtime) || session.runtime}` : "Neyvia Native"],
    ["Runs on", session.host_device_name],
    ["Folder", session.cwd],
    ["Branch", session.git_branch],
    ["Model", session.model],
    ["Billing", session.capabilities?.billing === "agent-sdk-credits" ? "Chosen in the composer: Agent SDK credit or plan limits" : null],
  ].filter(([, value]) => value);
  return (
    <div className="nx-panel-body nx-scroll" role="tabpanel" aria-label="Details">
      <dl className="nx-facts">
        {rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd title={value}>{value}</dd></div>)}
      </dl>
      {session.capabilities?.reason ? <p className="nx-panel-note">{session.capabilities.reason}</p> : null}
    </div>
  );
}

const PANEL_TABS = [["workspace", "Workspace"], ["details", "Details"], ["memory", "Memory"]];

/** The right panel: Workspace (folder, git, GitHub) and Details. A side panel, or a sheet on phones. */
export function SidePanel({ session, tab, onTab, onClose, sheet = false, inRegion = false }) {
  const Frame = sheet || inRegion ? "div" : "aside"; // inside a landmark region, the region is the landmark
  return (
    <Frame className={sheet ? "nx-panel-sheet" : "nx-panel"} aria-label={sheet || inRegion ? undefined : "Chat panel"}>
      <header className="nx-panel-head is-tabs">
        <div role="tablist" aria-label="Panel" className="nx-seg nx-panel-tabs">
          {PANEL_TABS.map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? "is-on" : ""} onClick={() => onTab(id)}>{label}</button>
          ))}
        </div>
        <IconButton icon={X} label="Close panel" onClick={onClose} />
      </header>
      {tab === "workspace" ? <NxWorkspacePanel key={session.id} session={session} /> : tab === "memory" ? <NxMemoryPanel key={session.id} session={session} /> : <DetailsBody session={session} />}
    </Frame>
  );
}

export function ThreadHeader({ session, onBack, onToggleSidebar, sidebarHidden, panelOpen, panelTab, onPanel, phone, panels, floating, docked = false, dragHandlers = null, onFloatOut = null }) {
  // Docked beside an app, the header is also a handle: drag it out to float the chat (NxDockDrag).
  return (
    <header className={`nx-head${docked && dragHandlers ? " is-draggable" : ""}`} {...(docked && dragHandlers ? dragHandlers : {})}
      title={docked && dragHandlers ? "Drag out of the dock to float this chat" : undefined}>
      {phone ? <IconButton icon={ChevronLeft} label="All chats" onClick={onBack} /> : null}
      {!phone && sidebarHidden ? <IconButton icon={PanelLeftOpen} label="Show sidebar" onClick={onToggleSidebar} /> : null}
      <div className="nx-head-title">
        <ProviderMark id={markFor(session)} size={16} />
        <h1 title={session?.title}>{session?.title || "Chat"}</h1>
      </div>
      {!phone && session?.project ? (
        <span className="nx-head-chip" title={session.cwd || session.project}><Icon as={FolderOpen} size={13} />{session.project}</span>
      ) : null}
      {!phone && session?.git_branch ? (
        <span className="nx-head-chip"><Icon as={GitBranch} size={13} />{session.git_branch}</span>
      ) : null}
      <div className="nx-head-spacer" />
      {!phone && session?.host_device_name ? (
        <span className="nx-head-chip is-quiet" title="Where this chat runs"><Icon as={Monitor} size={13} />{session.host_device_name}</span>
      ) : null}
      {session?.id ? <IconButton icon={History} label="Replay this chat, fast" onClick={() => os.showPane("replay", session.id)} /> : null}
      {!phone && session?.id ? (
        <IconButton icon={PictureInPicture2} label={floating ? "Floating as a bubble" : docked ? "Float out of the dock" : "Float as a bubble"} active={floating}
          onClick={() => (floating ? os.unfloat(session.id) : docked && onFloatOut ? onFloatOut(session.id) : os.float(session.id))} />
      ) : null}
      {panels ? (
        <>
          <IconButton icon={GitBranch} label="Workspace" active={panelOpen && panelTab === "workspace"} onClick={() => onPanel("workspace")} />
          <IconButton icon={Info} label="Details" active={panelOpen && panelTab === "details"} onClick={() => onPanel("details")} />
          <IconButton icon={Brain} label="Memory" active={panelOpen && panelTab === "memory"} onClick={() => onPanel("memory")} />
        </>
      ) : null}
    </header>
  );
}

