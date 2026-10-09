import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Activity, Folder, FolderSymlink, PanelLeftOpen, Search, SquarePen } from "lucide-react";

import { ProviderMark } from "./ProviderMark.jsx";
import { Icon, IconButton, Spinner, StatusDot, ago, local, portalLook, useRovingKeys } from "./nxPrimitives.jsx";
import { useNx } from "./nxStore.js";
import { os, useOs } from "./nxOsStore.js";
import { DEFAULT_CLEANUP, agentStatus, agentSummary, buildTree, orderAgents } from "./nxSidebarModel.js";
import { useObserved } from "./nxSidebarObserve.js";
import { agentWords, appLabel, markFor, statusLine } from "./NxSidebarParts.jsx";
import { useObserveSidebar, useSidebarRows } from "./NxSidebar.jsx";

// The collapsed sidebar (plan 15 T7): a thin rail of icons for the chats that
// matter now (needs you, pinned, recent) and the projects. Hovering or
// focusing an icon shows a preview card with what the PC read in that chat:
// its last words, when it last moved and the agents it started. Clicking
// opens the chat; the top button brings the full sidebar back.

const MAX_CHATS = 12;
const MAX_PROJECTS = 6;
const OPEN_DELAY_MS = 140;
const LIGHT_TONE = { running: "live", needs: "gold", error: "red" };

const portalTheme = () => document.querySelector(".nx-root")?.getAttribute("data-nx-theme") || "dark";

function placeLabel(leaf) {
  return leaf.place.group === "project" ? leaf.place.project : "No folder";
}

function ChatPeek({ leaf, now, reading, readError }) {
  const { session } = leaf;
  const sidebar = session.sidebar;
  const status = statusLine(session, now);
  const summary = agentSummary(sidebar?.agents);
  const last = sidebar?.preview?.lastActivity || session.updated_at;
  // The last words as plain text: markdown marks (bold, code ticks, headings) would show as symbols here.
  const text = String(sidebar?.preview?.text || "").replace(/\*\*|__|`+/g, "").replace(/^#{1,6}\s+/gm, "").trim();
  return (
    <>
      <div className="nx-peek-head">
        <ProviderMark id={markFor(session)} size={14} />
        <strong>{session.title || "Untitled chat"}</strong>
      </div>
      <div className="nx-peek-meta">
        <span>{session.category === "connected" ? appLabel(session.app) : "Neyvia"}</span>
        <span>· {placeLabel(leaf)}</span>
        {last ? <span>· {ago(last, now) === "now" ? "just now" : `${ago(last, now)} ago`}</span> : null}
      </div>
      {status ? (
        <div className={`nx-peek-status is-${status.tone}`}><StatusDot tone={status.tone} pulse={status.tone === "live"} /><span>{status.text}</span></div>
      ) : null}
      {sidebar ? (text ? <p className="nx-peek-text">{text}</p> : <p className="nx-peek-note">No messages to show yet.</p>)
        : readError ? <p className="nx-peek-note">Couldn't read this chat's history on the PC.</p>
          : reading ? <p className="nx-peek-note"><Spinner size={10} /> Reading this chat…</p> : null}
      {summary.total ? (
        <div className="nx-peek-agents">
          <span className="nx-peek-agents-head">{agentWords(summary).join(" · ")}</span>
          <ul>
            {orderAgents(sidebar.agents).slice(0, 3).map(node => {
              const { tone, word } = agentStatus(node.status);
              return <li key={node.id}><StatusDot tone={tone} /><span>{node.title || "Agent"}</span><em>{word}</em></li>;
            })}
          </ul>
        </div>
      ) : null}
    </>
  );
}

function ProjectPeek({ branch, now }) {
  const running = branch.sessions.filter(leaf => leaf.state === "running").length;
  return (
    <>
      <div className="nx-peek-head">
        <Icon as={branch.subject ? FolderSymlink : Folder} size={14} />
        <strong>{branch.name}</strong>
      </div>
      <div className="nx-peek-meta">
        <span>{branch.sessions.length} chat{branch.sessions.length === 1 ? "" : "s"}</span>
        {running ? <span className="is-live">· {running} working</span> : null}
        {branch.subject ? <span>· sorted by subject</span> : null}
      </div>
      {branch.sessions.length ? (
        <ul className="nx-peek-list">
          {branch.sessions.slice(0, 4).map(leaf => (
            <li key={leaf.session.id}><span>{leaf.session.title || "Untitled chat"}</span><time>{ago(leaf.session.updated_at, now)}</time></li>
          ))}
        </ul>
      ) : <p className="nx-peek-note">No chats yet.</p>}
    </>
  );
}

/** A hover/focus card beside the rail. It never takes focus; the icon it describes keeps it. */
function Peek({ peek, children }) {
  const box = useRef(null);
  const [top, setTop] = useState(null);
  useLayoutEffect(() => {
    if (!peek) return;
    const height = box.current?.getBoundingClientRect().height || 0;
    setTop(Math.max(8, Math.min(peek.rect.top - 6, window.innerHeight - height - 8)));
  }, [peek]);
  if (!peek) return null;
  return createPortal(
    <div className="nx nx-portal-host" data-nx-theme={portalTheme()} {...portalLook()}>
      <div ref={box} id="nx-rail-peek" role="tooltip" className="nx-peek"
        style={{ left: peek.rect.right + 10, top: top ?? peek.rect.top, visibility: top == null ? "hidden" : "visible" }}>
        {children}
      </div>
    </div>,
    document.body,
  );
}

function usePeek() {
  const [peek, setPeek] = useState(null);
  const timer = useRef(null);
  const show = useCallback((key, element, delay) => {
    clearTimeout(timer.current);
    const open = () => setPeek({ key, rect: element.getBoundingClientRect() });
    if (delay) timer.current = setTimeout(open, delay); else open();
  }, []);
  const hide = useCallback(() => { clearTimeout(timer.current); timer.current = setTimeout(() => setPeek(null), 60); }, []);
  useEffect(() => {
    const onKey = event => { if (event.key === "Escape") { clearTimeout(timer.current); setPeek(null); } };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); clearTimeout(timer.current); };
  }, []);
  const bind = key => ({
    onPointerEnter: event => { if (event.pointerType !== "touch") show(key, event.currentTarget, OPEN_DELAY_MS); },
    onPointerLeave: hide,
    onFocus: event => show(key, event.currentTarget, 0),
    onBlur: hide,
    "aria-describedby": peek?.key === key ? "nx-rail-peek" : undefined,
  });
  return { peek, bind, close: () => setPeek(null) };
}

export function NxSidebarRail({ activeId, onSelect, onNewChat, onExpand }) {
  const rows = useSidebarRows();
  const savedPolicy = useOs(state => state.cleanup);
  const connection = useNx(state => state.connection);
  const host = useNx(state => state.host);
  const pending = useObserved(state => state.pending);
  const errors = useObserved(state => state.errors);
  useObserveSidebar(rows, activeId);
  const listRef = useRef(null);
  const onKeys = useRovingKeys(listRef);
  const { peek, bind, close } = usePeek();
  const now = Date.now();

  const { chats, projects } = useMemo(() => {
    const policy = savedPolicy ? { ...DEFAULT_CLEANUP, ...savedPolicy } : DEFAULT_CLEANUP;
    const tree = buildTree(rows, { policy, now: Date.now() });
    const seen = new Set();
    const take = (leaves, limit) => leaves.filter(leaf => !seen.has(leaf.session.id)).slice(0, limit).map(leaf => { seen.add(leaf.session.id); return leaf; });
    const urgent = take(tree.needsYou, 6);
    const pinned = take(tree.pinned, 6);
    const everything = [...tree.projects.flatMap(branch => branch.sessions), ...tree.noFolder.images, ...tree.noFolder.quick, ...tree.noFolder.other]
      .sort((a, b) => String(b.session.updated_at || "").localeCompare(String(a.session.updated_at || "")));
    const recent = take(everything, Math.max(0, MAX_CHATS - urgent.length - pinned.length));
    return { chats: [urgent, pinned, recent].filter(group => group.length), projects: tree.projects.filter(branch => branch.sessions.length).slice(0, MAX_PROJECTS) };
  }, [rows, savedPolicy]);

  const leafByKey = key => chats.flat().find(leaf => `c:${leaf.session.id}` === key);
  const branchByKey = key => projects.find(branch => `p:${branch.name}` === key);
  const peekLeaf = peek ? leafByKey(peek.key) : null;
  const peekBranch = peek ? branchByKey(peek.key) : null;
  const hostTone = connection === "live" ? "green" : connection === "offline" ? "red" : "caution";
  const hostText = connection === "live" ? "Connected" : connection === "offline" ? "PC offline" : "Connecting…";

  const openSearch = () => { local.set("side.focusSearch", true); onExpand(); window.dispatchEvent(new CustomEvent("nx:focus-search")); };

  return (
    <div className="nx-rail" data-testid="sidebar-rail">
      <div className="nx-rail-top">
        <IconButton icon={PanelLeftOpen} label="Show sidebar" onClick={onExpand} />
        <IconButton icon={SquarePen} label="New chat" onClick={onNewChat} />
        <IconButton icon={Search} label="Search chats (Ctrl K)" onClick={openSearch} />
        <IconButton icon={Activity} label="Agents: everything working right now" onClick={() => os.setDashboard(true)} />
      </div>
      <nav className="nx-rail-list nx-scroll" aria-label="Chats" ref={listRef} onKeyDown={onKeys} onScroll={close}>
        {chats.map((group, index) => (
          <div key={index} className="nx-rail-group" role="group">
            {group.map(leaf => {
              const { session, state } = leaf;
              const tone = LIGHT_TONE[state];
              const status = statusLine(session, now);
              const label = `${session.title || "Untitled chat"}${status ? `, ${status.text}` : ""}${session.unread ? ", unread" : ""}`;
              return (
                <button key={session.id} type="button" data-roving aria-label={label} aria-current={session.id === activeId ? "page" : undefined}
                  className={`nx-rail-chat${session.id === activeId ? " is-active" : ""}`}
                  onClick={() => { close(); onSelect(session.id); }} {...bind(`c:${session.id}`)}>
                  <ProviderMark id={markFor(session)} size={18} />
                  {tone ? <span className={`nx-rail-light is-${tone}`} aria-hidden="true" /> : null}
                  {session.unread && !tone ? <span className="nx-rail-unread" aria-hidden="true" /> : null}
                </button>
              );
            })}
          </div>
        ))}
        {projects.length ? (
          <div className="nx-rail-group" role="group" aria-label="Projects">
            {projects.map(branch => {
              const latest = branch.sessions[0]?.session;
              const running = branch.sessions.some(leaf => leaf.state === "running");
              return (
                <button key={branch.name} type="button" data-roving className="nx-rail-project"
                  aria-label={`${branch.name}: ${branch.sessions.length} chats. Opens the latest.`}
                  onClick={() => { close(); if (latest) onSelect(latest.id); }} {...bind(`p:${branch.name}`)}>
                  <Icon as={branch.subject ? FolderSymlink : Folder} size={17} />
                  <span className="nx-rail-initial" aria-hidden="true">{branch.name.slice(0, 1).toUpperCase()}</span>
                  {running ? <span className="nx-rail-light is-live" aria-hidden="true" /> : null}
                </button>
              );
            })}
          </div>
        ) : null}
      </nav>
      <div className="nx-rail-foot" title={`${host?.deviceName || "This PC"} · ${hostText}`} role="status" aria-label={`${host?.deviceName || "This PC"}: ${hostText}`}>
        <StatusDot tone={hostTone} pulse={hostTone === "caution"} />
      </div>
      <Peek peek={peekLeaf || peekBranch ? peek : null}>
        {peekLeaf ? <ChatPeek leaf={peekLeaf} now={now} reading={Boolean(pending[peekLeaf.session.id]) || !peekLeaf.session.sidebar} readError={errors[peekLeaf.session.id]} /> : null}
        {peekBranch ? <ProjectPeek branch={peekBranch} now={now} /> : null}
      </Peek>
    </div>
  );
}
