import { memo, useState } from "react";
import { m } from "motion/react";
import { SPRING } from "./nxSpring.js";
import { Archive, ArchiveRestore, Bot, ChevronRight, Folder, FolderSymlink, GitBranch, Image, Pin, PinOff, Terminal, Zap, Shapes } from "lucide-react";

import { ProviderMark } from "./ProviderMark.jsx";
import { Icon, Spinner, StatusDot, ago, elapsed, local } from "./nxPrimitives.jsx";
import { archiveSessions, sessionAction } from "./nxBus.js";
import { agentStatus, agentSummary, basename, orderAgents } from "./nxSidebarModel.js";
import { SortChip } from "./NxSidebarSort.jsx";

// Leaves (chats) and branches (projects) of the sidebar tree. The small dot
// on the branch line is the leaf's light: running, needs you, error, stale, ok.

const ROWS_PER_BRANCH = 6;
const LIGHT_LABEL = { running: "Running", needs: "Needs you", error: "Stopped with an error", stale: "Stale: the cleanup policy may archive it", ok: "Up to date" };

export function markFor(session) {
  if (!session) return "neyvia";
  if (session.category === "native") return "neyvia";
  if (session.category === "hybrid") return session.runtime || "neyvia";
  return session.app === "claude-code" ? "claude" : session.app;
}

export function appLabel(app) {
  return { "claude-code": "Claude Code", codex: "Codex", opencode: "OpenCode", neyvia: "Neyvia", hermes: "Hermes", openclaw: "OpenClaw", gptme: "gptme", "kimi-code": "Kimi Code", cursor: "Cursor", gemini: "Gemini", "grok-build": "Grok Build", pi: "Pi" }[app] || app || "";
}

export function statusLine(session, now) {
  switch (session.status) {
    case "working": return { tone: "live", text: `Working${session.status_since ? ` · ${elapsed(session.status_since, now)}` : ""}` };
    case "waiting_approval": return { tone: "gold", text: "Needs your approval" };
    case "waiting_input": return { tone: "gold", text: "Waiting for your answer" };
    case "failed": return { tone: "red", text: "Stopped with an error" };
    case "interrupted": return { tone: "muted", text: "Interrupted" };
    default: return null;
  }
}

function Meta({ session, now, quiet }) {
  const status = statusLine(session, now);
  if (status) {
    return (
      <span className={`nx-row-meta is-${status.tone}`}>
        {status.tone === "live" ? <Spinner size={10} /> : <StatusDot tone={status.tone} />}
        <span>{status.text}</span>
      </span>
    );
  }
  if (quiet) return null;
  return (
    <span className="nx-row-meta">
      {session.git_branch
        ? <><Icon as={GitBranch} size={11} /><span className="nx-row-branch">{session.git_branch}</span></>
        : <span>{session.category === "connected" ? appLabel(session.app) : session.category === "hybrid" ? "Neyvia Hybrid" : "Neyvia"}</span>}
    </span>
  );
}

/** Marks a CLI chat (codex exec, Claude Code terminal) with a terminal icon in every state; its folder is in the tooltip (the row already sits under that folder). */
function BackgroundMark({ session }) {
  const folder = basename(session.cwd);
  return (
    <span className="nx-row-bg" data-background="true" title={`CLI chat${folder ? ` in ${folder}` : ""}, started from a terminal or script`}>
      <Icon as={Terminal} size={10} />
    </span>
  );
}

const AGENTS_SHOWN = 8;

/** Plain words for an agent count: ["3 agents", "1 working", "1 failed"]. */
export function agentWords(summary) {
  const parts = [`${summary.total} agent${summary.total === 1 ? "" : "s"}`];
  if (summary.running) parts.push(`${summary.running} working`);
  if (summary.failed) parts.push(`${summary.failed} failed`);
  return parts;
}

const hasChild = (nodes, id) => (nodes || []).some(node => node.sessionId === id || hasChild(node.children, id));

function AgentNode({ node, activeId, onSelect, depth }) {
  const { tone, word } = agentStatus(node.status);
  const title = node.title || "Agent";
  const body = (
    <>
      <StatusDot tone={tone} pulse={tone === "live"} />
      <span className="nx-kid-title">{title}</span>
      <span className={`nx-kid-state is-${tone}`}>{word}</span>
    </>
  );
  return (
    <li className="nx-kid">
      {node.sessionId ? (
        <button type="button" data-roving className={`nx-kid-row is-link${node.sessionId === activeId ? " is-active" : ""}`}
          aria-current={node.sessionId === activeId ? "page" : undefined} title={`${title}: open its own chat`}
          onClick={() => onSelect(node.sessionId)}>{body}</button>
      ) : (
        // Seen in the transcript, but not as a chat Neyvia can open: shown, not linked.
        <div className="nx-kid-row" title={`${title}: ran inside this chat`}>{body}</div>
      )}
      {node.children?.length ? (
        <ul className="nx-kids-list">
          {node.children.map(child => <AgentNode key={child.id} node={child} activeId={activeId} onSelect={onSelect} depth={depth + 1} />)}
        </ul>
      ) : null}
    </li>
  );
}

/** The agents a chat started, folded under it (sidebar.state agents, any harness). */
function AgentTree({ agents, chatTitle, activeId, onSelect, startOpen }) {
  const summary = agentSummary(agents);
  const [open, setOpen] = useState(startOpen);
  const [all, setAll] = useState(false);
  const ordered = orderAgents(agents);
  const shown = all ? ordered : ordered.slice(0, AGENTS_SHOWN);
  const words = agentWords(summary);
  return (
    <div className="nx-kids">
      <button type="button" className="nx-kids-toggle" aria-expanded={open} onClick={() => setOpen(!open)}
        aria-label={`${words.join(", ")} in ${chatTitle}`}>
        <Icon as={ChevronRight} size={11} className="nx-chev" />
        <Icon as={Bot} size={12} />
        <span>{words[0]}</span>
        {summary.running ? <span className="is-live">· {summary.running} working</span> : null}
        {summary.failed ? <span className="is-red">· {summary.failed} failed</span> : null}
      </button>
      {open ? (
        <ul className="nx-kids-list is-root" aria-label={`Agents in ${chatTitle}`}>
          {shown.map(node => <AgentNode key={node.id} node={node} activeId={activeId} onSelect={onSelect} depth={0} />)}
          {agents.length > AGENTS_SHOWN ? (
            <li><button type="button" className="nx-kids-more" onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show ${agents.length - AGENTS_SHOWN} more`}</button></li>
          ) : null}
        </ul>
      ) : null}
    </div>
  );
}

export const Leaf = memo(function Leaf({ leaf, active, activeId = "", onSelect, now, quiet = false }) {
  const { session, state, agents = [] } = leaf;
  const hybrid = session.category === "hybrid";
  return (
    <div className={`nx-leaf is-${state}${agents.length ? " has-agents" : ""}`} data-session-id={session.id}>
      <div className="nx-leaf-head">
        <span className="nx-leaf-light" title={LIGHT_LABEL[state]} aria-hidden="true" />
        <button type="button" data-roving aria-current={active ? "page" : undefined} aria-description={LIGHT_LABEL[state]} data-nx-morph="chat"
          className={`nx-row${active ? " is-active" : ""}${session.unread ? " is-unread" : ""}`}
          onClick={() => onSelect(session.id)}>
          {active ? <m.span layoutId="nx-row-active" className="nx-row-bar" transition={SPRING.settle} aria-hidden="true" /> : null}
          <span className="nx-row-mark">
            <ProviderMark id={markFor(session)} size={16} />
            {hybrid ? <span className="nx-row-badge" title="Run by Neyvia"><ProviderMark id="neyvia" size={9} /></span> : null}
          </span>
          <span className="nx-row-main">
            <span className="nx-row-title">{session.background ? <BackgroundMark session={session} /> : null}{session.title || "Untitled chat"}</span>
            <Meta session={session} now={now} quiet={quiet} />
          </span>
          <span className="nx-row-side">
            {session.unread ? <span className="nx-unread" aria-label="Unread" /> : null}
            <time dateTime={session.updated_at || undefined}>{ago(session.updated_at, now)}</time>
          </span>
        </button>
        <span className="nx-leaf-actions">
          <button type="button" className="nx-leaf-act" aria-label={session.pinned ? "Unpin" : "Pin"} title={session.pinned ? "Unpin" : "Pin"}
            onClick={() => void sessionAction(session.id, "pin", { pinned: !session.pinned }, { pinned: !session.pinned })}>
            <Icon as={session.pinned ? PinOff : Pin} size={13} />
          </button>
          <button type="button" className="nx-leaf-act" aria-label="Archive" title="Archive (restorable from Fallen leaves)"
            onClick={() => archiveSessions([session.id], `Archived “${session.title || "chat"}”`)}>
            <Icon as={Archive} size={13} />
          </button>
        </span>
      </div>
      {agents.length ? (
        <AgentTree agents={agents} chatTitle={session.title || "this chat"} activeId={activeId} onSelect={onSelect}
          startOpen={active || hasChild(agents, activeId)} />
      ) : null}
    </div>
  );
});

export function Section({ id, title, icon, tone, count, children, defaultOpen = true, action = null, hint = undefined }) {
  const [open, setOpen] = useState(() => local.get(`side.open.${id}`, defaultOpen));
  return (
    <section className={`nx-side-section${tone ? ` is-${tone}` : ""}`} role="group" aria-label={title}>
      <div className="nx-side-section-row">
        <button type="button" className="nx-side-section-head" aria-expanded={open} title={hint}
          onClick={() => { setOpen(!open); local.set(`side.open.${id}`, open === defaultOpen ? !open : null); }}>
          <Icon as={ChevronRight} size={12} className="nx-chev" />
          {icon ? <Icon as={icon} size={13} /> : null}
          <span className="nx-side-section-title">{title}</span>
          {count ? <span className="nx-side-section-count">{count}</span> : null}
        </button>
        {action}
      </div>
      {open ? <div className="nx-side-section-body">{children}</div> : null}
    </section>
  );
}

function Leaves({ leaves, activeId, onSelect, now, quiet }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? leaves : leaves.slice(0, ROWS_PER_BRANCH);
  return (
    <div className="nx-branch" role="group">
      {shown.map(leaf => <Leaf key={leaf.session.id} leaf={leaf} active={leaf.session.id === activeId} activeId={activeId} onSelect={onSelect} now={now} quiet={quiet} />)}
      {leaves.length > ROWS_PER_BRANCH ? (
        <button type="button" className="nx-row-more" onClick={() => setExpanded(!expanded)}>
          {expanded ? "Show fewer" : `Show ${leaves.length - ROWS_PER_BRANCH} more`}
        </button>
      ) : null}
    </div>
  );
}

export function Branch({ branch, activeId, onSelect, now, quiet }) {
  const running = branch.sessions.filter(leaf => leaf.state === "running").length;
  return (
    <Section id={`p.${branch.name}`} title={branch.name} icon={branch.subject ? FolderSymlink : Folder} count={branch.sessions.length || null}
      tone={running ? "running" : undefined}
      hint={branch.subject ? "Sorted by subject: a sidebar group, nothing moved on disk" : branch.path || undefined}>
      {branch.sessions.length
        ? <Leaves leaves={branch.sessions} activeId={activeId} onSelect={onSelect} now={now} quiet={quiet} />
        : <p className="nx-branch-empty" title={branch.path || ""}>New project · no chats yet</p>}
    </Section>
  );
}

const KINDS = [["images", "Images", Image], ["quick", "Quick", Zap], ["other", "Other", Shapes]];

export function NoFolder({ groups, count, activeId, onSelect, now, quiet, reading = 0, rows }) {
  if (!count) return null;
  const leaves = [...groups.images, ...groups.quick, ...groups.other];
  return (
    <Section id="nofolder" title="No folder" count={count} tone="nofolder" action={<SortChip leaves={leaves} rows={rows} />}>
      {reading ? (
        <p className="nx-nofolder-reading" aria-live="polite"><Spinner size={10} /> Reading {reading} chat{reading === 1 ? "" : "s"} to sort them</p>
      ) : null}
      {KINDS.map(([kind, label, glyph]) => (groups[kind].length ? (
        <div key={kind} className="nx-nofolder-group">
          <div className="nx-nofolder-head"><Icon as={glyph} size={12} /><span>{label}</span><span className="nx-side-section-count">{groups[kind].length}</span></div>
          <Leaves leaves={groups[kind]} activeId={activeId} onSelect={onSelect} now={now} quiet={quiet} />
        </div>
      ) : null))}
    </Section>
  );
}

export function FallenLeaves({ sessions, onSelect }) {
  if (!sessions.length) return null;
  return (
    <Section id="fallen" title="Fallen leaves" icon={Archive} count={sessions.length} defaultOpen={false} tone="fallen">
      {sessions.map(session => (
        <div key={session.id} className="nx-fallen">
          <button type="button" className="nx-fallen-title" onClick={() => onSelect(session.id)} title={session.title}>{session.title || "Untitled chat"}</button>
          <button type="button" className="nx-leaf-act" aria-label="Restore" title="Restore"
            onClick={() => void sessionAction(session.id, "archive", { archived: false }, { archived: false })}>
            <Icon as={ArchiveRestore} size={13} />
          </button>
        </div>
      ))}
    </Section>
  );
}
