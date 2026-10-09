import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, Compass, LayoutDashboard, LayoutGrid, LogOut, Monitor, MonitorSmartphone, MoreHorizontal, Network, PanelLeftClose, Pin,
  CirclePlay, Palette, RefreshCw, Search, Settings, Settings2, Sparkles, SquarePen, TriangleAlert, UsersRound, Workflow,
} from "lucide-react";

import "./nxSidebar.css";
import { ProviderMark } from "./ProviderMark.jsx";
import { Icon, IconButton, Kbd, Popover, Segmented, StatusDot, local, useRovingKeys, useTick } from "./nxPrimitives.jsx";
import { loadList, useNx } from "./nxStore.js";
import { THEMES, THEME_LABELS, os, useOs, withOverrides } from "./nxOsStore.js";
import { DEFAULT_CLEANUP, buildTree, placeSession, staleCandidates } from "./nxSidebarModel.js";
import { observeRows, refreshObserved, useObserved } from "./nxSidebarObserve.js";
import { Branch, FallenLeaves, Leaf, NoFolder, Section, appLabel, markFor } from "./NxSidebarParts.jsx";
import { CleanupSettings, TidyChip } from "./NxTidy.jsx";
import { MARKS_NOTICE } from "./nxLegal.js";
import { isDesktopApp } from "./nxApi.js";

export { appLabel, markFor };

const SCOPES = [
  { value: "all", label: "All" },
  { value: "native", label: "Native" },
  { value: "hybrid", label: "Hybrid" },
  { value: "connected", label: "Connected" },
];

function HostChip() {
  const host = useNx(state => state.host);
  const connection = useNx(state => state.connection);
  const tone = connection === "live" ? "green" : connection === "offline" ? "red" : "caution";
  const text = connection === "live" ? "Connected" : connection === "offline" ? "PC offline" : connection === "connecting" ? "Connecting…" : "Reconnecting…";
  return (
    <div className="nx-host" title={`${host?.deviceName || "PC"} · ${text}`}>
      <Icon as={Monitor} size={14} />
      <span className="nx-host-name">{host?.deviceName || "This PC"}</span>
      <StatusDot tone={tone} pulse={tone === "caution"} />
      <span className="nx-host-state">{text}</span>
    </div>
  );
}

function MoreMenu({ onAction }) {
  const theme = useOs(state => state.theme);
  const anchor = useRef(null);
  const list = useRef(null);
  const [open, setOpen] = useState(false);
  const onKeyDown = useRovingKeys(list);
  const item = (key, label, icon) => (
    <button type="button" role="menuitem" key={key} className="nx-menu-item" onClick={() => { setOpen(false); onAction(key); }}>
      <Icon as={icon} size={15} /><span>{label}</span>
    </button>
  );
  return (
    <>
      <IconButton ref={anchor} icon={MoreHorizontal} label="More" onClick={() => setOpen(!open)} active={open} />
      <Popover anchor={anchor} open={open} onClose={() => setOpen(false)} placement="top-end" width={232} label="More">
        <div role="menu" ref={list} onKeyDown={onKeyDown} className="nx-menu">
          {item("settings", "Settings", Settings)}
          {item("look", "Look: font and background", Palette)}
          {item("refresh", "Refresh chats", RefreshCw)}
          <div className="nx-menu-label">Theme</div>
          {THEMES.map(id => item(`theme:${id}`, `${THEME_LABELS[id]}${id === theme ? " ✓" : ""}`, Settings2))}
          <div className="nx-menu-sep" />
          {item("builder", "Builder", LayoutDashboard)}
          {item("missions", "Missions", Network)}
          {item("accounts", "Accounts", UsersRound)}
          {item("onboarding", "Setup and tour", Compass)}
          {item("unique", "Help: what makes Neyvia different", Sparkles)}
          {item("tour", "Help: replay the full tour", CirclePlay)}
          <div className="nx-menu-sep" />
          {item("agent-view", "Agents at work", MonitorSmartphone)}
          {isDesktopApp() ? null : item("sign-out", "Sign out", LogOut)}
          <p className="nx-menu-legal">{MARKS_NOTICE}</p>
          <p className="nx-menu-legal">Some small details are inspired by <a href="https://rareui.com" target="_blank" rel="noreferrer">Rare UI</a> and NumberFlow.</p>
        </div>
      </Popover>
    </>
  );
}

/**
 * Every chat the sidebar knows, with the bus's and the user's overrides applied,
 * and what the PC read in its transcript (`sidebar`: lane, agents, preview) once read.
 */
export function useSidebarRows() {
  const order = useNx(state => state.order);
  const sessions = useNx(state => state.sessions);
  const overrides = useOs(state => state.overrides);
  const projects = useOs(state => state.projects);
  const created = useOs(state => state.created);
  const observed = useObserved(state => state.byId);
  const folders = useObserved(state => state.folders);
  return useMemo(() => {
    const rows = order.map(id => sessions[id]).filter(Boolean);
    for (const row of Object.values(created)) if (!sessions[row.id]) rows.push(row);
    const known = { ...projects, ...folders };
    return rows.map(session => {
      const row = withOverrides(session, overrides, known);
      const sidebar = observed[session.id]?.sidebar;
      return sidebar ? { ...row, sidebar } : row;
    });
  }, [order, sessions, overrides, projects, created, observed, folders]);
}

/** Keep the PC reading what the sidebar shows: the open chat first, then No folder chats (their lane), then the rest by recency. */
export function useObserveSidebar(rows, activeId) {
  useEffect(() => {
    const live = rows.filter(row => !row.archived);
    const first = live.filter(row => row.id === activeId);
    const unfiled = live.filter(row => row.id !== activeId && placeSession(row).group === "nofolder");
    const rest = live.filter(row => row.id !== activeId && placeSession(row).group !== "nofolder");
    // Rows arrive newest first already.
    const timer = setTimeout(() => observeRows([...first, ...unfiled, ...rest]), 400);
    return () => clearTimeout(timer);
  }, [rows, activeId]);
  // A long turn keeps the same stamp (updated_at and status), so subagents a chat starts
  // mid-turn would only show after the turn ends: read working chats again every 10 s.
  const working = rows.filter(row => !row.archived && row.status === "working").map(row => row.id).join(" ");
  useEffect(() => {
    if (!working) return undefined;
    const ids = working.split(" ");
    const timer = setInterval(() => { if (!document.hidden) refreshObserved(ids); }, 10000);
    return () => clearInterval(timer);
  }, [working]);
}

/** Chat sources that can't be listed right now, as one calm line: who, and a Retry.
 * An app that isn't installed is not a problem and stays out of the list; the raw
 * error is only in the tooltip. */
export function SourceStatus({ sources }) {
  const rows = (sources || []).filter(source => source.available === false && source.reason && source.state !== "missing");
  if (!rows.length) return null;
  const loading = rows.every(source => source.state === "loading");
  const names = rows.map(source => appLabel(source.app));
  const who = names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}` : names[0];
  const text = loading ? `Loading ${who} chats…` : rows.length === 1 ? rows[0].reason : `${who} aren't responding right now.`;
  const details = rows.map(source => `${appLabel(source.app)}: ${source.detail || source.reason}`).join("\n");
  return (
    <div className={`nx-side-sources${loading ? " is-loading" : ""}`} role="status" title={details}>
      <span className="nx-side-sources-marks" aria-hidden="true">{rows.map(source => <ProviderMark key={source.app} id={markFor({ app: source.app })} size={12} />)}</span>
      <span className="nx-side-sources-text">{text}</span>
      {loading ? null : <button type="button" className="nx-link" onClick={() => void loadList()}>Retry</button>}
    </div>
  );
}

export function NxSidebar({ activeId, onSelect, onNewChat, onAction, onCollapse }) {
  const list = useNx(state => state.list);
  const density = useOs(state => state.density);
  const savedPolicy = useOs(state => state.cleanup);
  const projects = useOs(state => state.projects);
  const allRows = useSidebarRows();
  const readErrors = useObserved(state => state.errors);
  const readFailure = useObserved(state => state.failure);
  useObserveSidebar(allRows, activeId);
  const [scope, setScope] = useState(() => local.get("side.scope", "all"));
  const [query, setQuery] = useState("");
  const search = useRef(null);
  const listRef = useRef(null);
  const onListKeys = useRovingKeys(listRef);
  const calm = density === "calm";
  const effectiveScope = calm ? "all" : scope;
  const policy = useMemo(() => (savedPolicy ? { ...DEFAULT_CLEANUP, ...savedPolicy } : DEFAULT_CLEANUP), [savedPolicy]);
  useTick(allRows.some(row => row.status === "working"), 15000);
  const now = Date.now();

  useEffect(() => {
    const timer = setTimeout(() => void loadList({ query: query.trim() }), query ? 220 : 0);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    const onKey = event => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        search.current?.focus();
        search.current?.select();
      }
    };
    // The collapsed rail's search button opens the sidebar and lands here.
    const onFocusSearch = () => { search.current?.focus(); search.current?.select(); };
    window.addEventListener("keydown", onKey);
    window.addEventListener("nx:focus-search", onFocusSearch);
    if (local.get("side.focusSearch", false)) { local.set("side.focusSearch", null); requestAnimationFrame(onFocusSearch); }
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("nx:focus-search", onFocusSearch); };
  }, []);

  const counts = useMemo(() => {
    const result = { all: 0, native: 0, hybrid: 0, connected: 0 };
    for (const row of allRows) { if (row.archived) continue; result.all += 1; result[row.category || "connected"] += 1; }
    return result;
  }, [allRows]);

  const { tree, stale, fallen } = useMemo(() => {
    const scoped = allRows.filter(row => effectiveScope === "all" || (row.category || "connected") === effectiveScope);
    // An empty project the model just created still shows as a branch.
    const knownProjects = query ? [] : Object.values(projects);
    return {
      tree: buildTree(scoped, { projects: knownProjects, policy, now: Date.now() }),
      stale: staleCandidates(scoped, policy, Date.now()),
      fallen: scoped.filter(row => row.archived),
    };
  }, [allRows, effectiveScope, projects, policy, query]);

  const empty = list.status === "ready" && !tree.total && !tree.projects.length;
  const unfiled = [...tree.noFolder.images, ...tree.noFolder.quick, ...tree.noFolder.other];
  // Chats not read yet sit in Other; say so while the PC reads them (a chat it couldn't read stays in Other).
  const reading = readFailure ? 0 : unfiled.filter(leaf => !leaf.session.sidebar && !readErrors[leaf.session.id]).length;
  const leafProps = { activeId, onSelect, now, quiet: calm };

  return (
    <div className="nx-side">
      <div className="nx-side-top">
        <div className="nx-brand">
          <ProviderMark id="neyvia" size={20} />
          <span>Neyvia</span>
        </div>
        <div className="nx-side-top-actions">
          {onCollapse ? <IconButton icon={PanelLeftClose} label="Hide sidebar" onClick={onCollapse} /> : null}
          <IconButton icon={Activity} label="Agents: everything working right now" onClick={() => os.setDashboard(true)} />
          <IconButton icon={LayoutGrid} label="Apps (Ctrl Space)" onClick={() => os.setLauncher(true)} />
          <IconButton icon={SquarePen} label="New chat" onClick={onNewChat} />
        </div>
      </div>

      <label className="nx-search">
        <Icon as={Search} size={14} />
        <input ref={search} type="search" placeholder="Search chats" value={query}
          onChange={event => setQuery(event.target.value)} aria-label="Search chats" />
        {!query ? <Kbd>Ctrl K</Kbd> : null}
      </label>

      {calm ? null : (
        <div className="nx-side-scope">
          <Segmented size="sm" label="Chat category" value={scope}
            onChange={value => { setScope(value); local.set("side.scope", value === "all" ? null : value); }}
            options={SCOPES.map(option => ({ ...option, count: option.value === "all" ? 0 : counts[option.value] }))} />
        </div>
      )}

      <TidyChip stale={stale} total={tree.total} policy={policy} rows={allRows} />

      <nav className="nx-side-list nx-scroll" aria-label="Chat list" ref={listRef} onKeyDown={onListKeys}>
        {list.status === "loading" && !allRows.length ? (
          <div className="nx-side-skeleton" aria-busy="true" aria-label="Loading chats">
            {Array.from({ length: 7 }, (_, index) => <span key={index} style={{ opacity: 1 - index * 0.11 }} />)}
          </div>
        ) : null}
        {list.status === "error" && !allRows.length ? (
          <div className="nx-side-note is-error" role="alert">
            <Icon as={TriangleAlert} size={15} />
            <div>
              <strong>{list.code === "network" ? "Can't reach your PC" : "Chats didn't load"}</strong>
              <p>{list.code === "network" ? "Neyvia on the PC may be closed or offline. Your drafts are kept." : list.error}</p>
              <button type="button" className="nx-link" onClick={() => void loadList()}>Try again</button>
            </div>
          </div>
        ) : null}
        {tree.needsYou.length ? (
          <Section id="needs-you" title="Needs you" tone="gold" count={tree.needsYou.length}>
            <div className="nx-branch is-flat">
              {tree.needsYou.map(leaf => <Leaf key={leaf.session.id} leaf={leaf} active={leaf.session.id === activeId} activeId={activeId} onSelect={onSelect} now={now} />)}
            </div>
          </Section>
        ) : null}
        {tree.pinned.length ? (
          <Section id="pinned" title="Pinned" icon={Pin} count={tree.pinned.length}>
            <div className="nx-branch is-flat">
              {tree.pinned.map(leaf => <Leaf key={leaf.session.id} leaf={leaf} active={leaf.session.id === activeId} activeId={activeId} onSelect={onSelect} now={now} quiet={calm} />)}
            </div>
          </Section>
        ) : null}
        {tree.projects.length ? (
          <div className="nx-side-label">
            <span>Projects</span>
            <CleanupSettings policy={policy} rows={allRows} />
          </div>
        ) : null}
        {tree.projects.map(branch => <Branch key={branch.name} branch={branch} {...leafProps} />)}
        <NoFolder groups={tree.noFolder} count={tree.noFolderCount} reading={reading} rows={allRows} {...leafProps} />
        <FallenLeaves sessions={fallen} onSelect={onSelect} />
        {empty ? (
          <div className="nx-side-note">
            <strong>{query ? "No chats match" : effectiveScope === "all" ? "No chats yet" : `No ${SCOPES.find(option => option.value === effectiveScope)?.label} chats`}</strong>
            <p>{query ? "Try a title, project, or branch name." : "Start one with New chat, or open Claude Code or Codex on your PC."}</p>
          </div>
        ) : null}
        <SourceStatus sources={list.sources} />
      </nav>

      <div className="nx-side-foot">
        <HostChip />
        <IconButton icon={Settings} label="Settings" data-nx-open="settings" onClick={() => onAction("settings")} />
        <MoreMenu onAction={onAction} />
      </div>
    </div>
  );
}

