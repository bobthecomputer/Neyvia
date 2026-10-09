import { useMemo, useRef, useState } from "react";
import { ArrowUpRight, Clock, Eye, MessageSquare, Moon, RefreshCw, Square } from "lucide-react";
import "./nxAgentsOverview.css";
import { AgentTree, NightTree } from "./NxAgentTree.jsx";
import { ProviderMark } from "./ProviderMark.jsx";
import { NxGrowingTree } from "./NxGrowingTree.jsx";
import { Button, Icon, IconButton, Segmented, Spinner, StatusDot, compactTokens, useFocusTrap, useTick } from "./nxPrimitives.jsx";
import { applyUiAction, os } from "./nxOsStore.js";
import { appLabel } from "./NxSidebarParts.jsx";
import { markForHarness as markFor } from "./nxMissionsModel.js";
import { duration, shapeBoard } from "./nxNightShiftModel.js";
import { limitPercent, resetsIn } from "./nxDashboardModel.js";
import { messageOverviewAgent, stopOverviewAgent, useAgentsOverview } from "./nxAgentsOverviewApi.js";
import { overviewGroups, SOURCE_NAMES, STATE_NAMES } from "./nxAgentsOverviewModel.js";

const TONES = { working: "live", waiting: "gold", asking: "gold", done: "green", failed: "red", stopped: "idle", ended: "idle", unknown: "idle" };
const openPane = (kind, target = "") => applyUiAction("pane.show", { kind, target, placement: "full" });

function AgentCard({ row, selected, onSelect, onOpenChat, onAction }) {
  const open = () => {
    if (row.sessionId) { os.closeWindow("pane:agents:"); onOpenChat?.(row.sessionId); }
    else if (row.openTarget) openPane(row.openTarget.kind, row.openTarget.target);
  };
  const started = Date.parse(row.startedAt);
  const seconds = row.state === "working" && Number.isFinite(started) ? Math.max(0, (Date.now() - started) / 1000) : row.elapsedSeconds;
  return <article data-ns-task={row.id} className={`nx-ns-card nx-am-card is-${row.status}${row.context ? " is-context" : ""}${selected ? " is-selected" : ""}`}>
    <span className="nx-ns-card-top"><ProviderMark id={markFor(row.app)} size={20} title={appLabel(row.app)} />
      <span className="nx-ns-card-route">{row.app === "you" ? "You" : appLabel(row.app)}{row.model ? ` · ${row.model}` : ""}</span></span>
    <button className="nx-ns-card-title nx-am-title" type="button" onClick={() => onSelect(row.id)} aria-pressed={selected}>{row.title}</button>
    <span className="nx-ns-card-state">{row.state === "working" ? <NxGrowingTree size={15} /> : <StatusDot tone={TONES[row.state]} />}<span>{STATE_NAMES[row.state]}</span>{row.context ? <em>Parent</em> : null}</span>
    <span className="nx-ns-card-note nx-am-activity" title={row.activity || "No activity line reported"}>{row.activity || "No activity line reported"}</span>
    {row.worktree || row.branch || row.project ? <span className="nx-am-place" title={[row.worktree || row.project, row.branch].filter(Boolean).join(" · ")}>{row.branch && row.branch !== "HEAD" ? row.branch : row.worktree || row.project || row.branch}</span> : null}
    <span className="nx-am-measures"><span><Icon as={Clock} size={11} />{seconds == null ? "Time unreported" : duration(seconds)}</span>
      <span title="Input not read from cache, plus output">{row.newTokens == null ? "Tokens unreported" : `${compactTokens(row.newTokens) || 0} new tokens`}</span></span>
    <footer className="nx-am-actions">
      <Button size="sm" icon={MessageSquare} disabled={!row.sessionId && !row.openTarget} onClick={open}>{row.sessionId ? "Chat" : "Open"}</Button>
      <IconButton size="sm" icon={Eye} label={`Watch ${row.title}`} disabled={!row.actions.watch} onClick={() => openPane("agentview", row.sessionId || row.runId)} />
      <IconButton size="sm" icon={ArrowUpRight} label={`Message ${row.title}`} disabled={!row.actions.message} onClick={() => onAction("message", row)} />
      <IconButton size="sm" icon={Square} label={`Stop ${row.title}`} disabled={!row.actions.stop} onClick={() => onAction("stop", row)} />
    </footer>
  </article>;
}

function PlanLimits({ limits }) {
  return <div className="nx-am-limits" aria-label="Plan limits from Usage">
    {["claude-code", "codex"].map(app => {
      const rows = limits.filter(row => row.app === app);
      return <div key={app} className="nx-am-limit-provider"><ProviderMark id={markFor(app)} size={15} /><strong>{appLabel(app)}</strong>
        {rows.length ? rows.map(row => { const used = limitPercent(row); return <span key={row.window} className="nx-am-limit" title={`${row.source || "Reported by the app"}${row.at ? ` · ${row.at}` : ""}`}>
          <span>{row.label || row.window}</span><span className="nx-am-meter" role="meter" aria-label={`${appLabel(app)} ${row.label || row.window}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={used ?? undefined}>
            <i style={{ transform: `scaleX(${Math.min(1, Math.max(0, (used || 0) / 100))})` }} /></span>
          <span>{used == null ? "Unreported" : `${Math.round(used)}%`}{row.stale ? " · stale" : ""}</span>{row.resetsAt ? <small>{resetsIn(row.resetsAt) === "now" ? "window has reset" : `resets ${resetsIn(row.resetsAt)}`}</small> : null}
        </span>; }) : <span className="nx-am-unreported">No plan reading yet</span>}
      </div>;
    })}
    <Button className="nx-am-usage" size="sm" onClick={() => openPane("usage")}>Usage <Icon as={ArrowUpRight} size={12} /></Button>
  </div>;
}

function AgentAction({ action, onClose, onDone }) {
  const dialog = useRef(null);
  useFocusTrap(dialog, true);
  const [text, setText] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const stop = action.kind === "stop";
  const submit = async event => {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const reply = stop ? await stopOverviewAgent(action.row.actions.stop) : await messageOverviewAgent(action.row, text.trim());
      if (reply?.ok === false || reply?.result?.ok === false) throw new Error(reply.error || reply.result?.error || "The agent refused that action");
      os.notify({ level: "success", message: stop ? "Stop requested" : `Message ${reply.delivery || reply.result?.delivery || "sent"}` }); onDone();
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  };
  return <div className="nx-am-action-scrim" onKeyDown={event => { if (event.key === "Escape" && !busy) onClose(); }}>
    <form ref={dialog} className="nx-am-action" role={stop ? "alertdialog" : "dialog"} aria-modal="true" aria-labelledby="nx-am-action-title" onSubmit={submit}>
      <h3 id="nx-am-action-title">{stop ? "Stop" : "Message"} {action.row.title}?</h3>
      <p>{stop ? "Stops this owned run. Its files and recorded work are kept." : "Delivered through the agent's existing inbox or live turn."}</p>
      {!stop ? <textarea className="nx-input" autoFocus rows={3} aria-label="Message to agent" value={text} onChange={e => setText(e.target.value)} /> : null}
      {error ? <p role="alert">{error}</p> : null}
      <footer><Button size="sm" autoFocus={stop} disabled={busy} onClick={onClose}>Cancel</Button>
        <Button size="sm" variant="primary" type="submit" disabled={busy || !stop && !text.trim()}>{busy ? "Sending…" : stop ? "Stop run" : "Send message"}</Button></footer>
    </form>
  </div>;
}

export function NxAgentsOverview({ onOpenChat }) {
  const pane = useRef(null);
  const { data, error, busy, reload } = useAgentsOverview(pane);
  const [filter, setFilter] = useState("all"), [grouping, setGrouping] = useState("source"), [project, setProject] = useState("");
  const [selected, setSelected] = useState(null), [action, setAction] = useState(null);
  const groups = useMemo(() => overviewGroups(data, filter, grouping, project), [data, filter, grouping, project]);
  const projects = useMemo(() => [...new Set((data?.nodes || []).map(row => row.project).filter(Boolean))].sort(), [data]);
  const totals = data?.totals;
  const board = useMemo(() => shapeBoard((data?.nodes || []).filter(row => row.source === "nightshift").map(row => ({ id: row.id,
    title: row.title, status: row.state === "working" ? "running" : row.state === "done" ? "done" : row.state === "failed" ? "blocked" : "waiting", needs: [] }))), [data]);
  useTick(Boolean(totals?.working), 30000);
  const connections = (data?.edges || []).filter(edge => edge.kind !== "parent");
  const byId = new Map((data?.nodes || []).map(row => [row.id, row]));
  return <section ref={pane} className="nx-am" aria-label="Agents overview">
    <header className="nx-am-head">
      <div className="nx-am-heading"><span className="nx-am-eyebrow">Across your workspace</span><h2>Agents at work</h2>
        <p>{totals && !data.loading ? <>{totals.partial ? "Observed" : null}<strong>{totals.working}</strong> working <span>·</span> <strong>{totals.waiting}</strong> waiting for you <span>·</span> <strong>{totals.newTokensLastHour == null ? "—" : compactTokens(totals.newTokensLastHour) || 0}</strong> new tokens in the last hour</> : "Reading the live workspace…"}</p>
      </div>
      <div className="nx-am-head-actions"><Button size="sm" icon={Moon} onClick={() => openPane("mission", "nightshift")}>Tonight's queue</Button>
        <IconButton size="sm" icon={RefreshCw} label="Refresh agents overview" disabled={busy} onClick={reload} /></div>
    </header>
    <PlanLimits limits={data?.limits || []} />
    <div className="nx-am-tools">
      <Segmented label="Filter agents" value={filter} onChange={setFilter} size="sm" options={[{ value: "all", label: "All" }, { value: "working", label: "Working" }, { value: "needs", label: "Needs you" }]} />
      <label><span>Group by</span><select className="nx-input" aria-label="Group agents by" value={grouping} onChange={e => setGrouping(e.target.value)}><option value="source">Source</option><option value="project">Project</option></select></label>
      <label><span>Project</span><select className="nx-input" aria-label="Filter by project" value={project} onChange={e => setProject(e.target.value)}><option value="">Every project</option>{projects.map(p => <option key={p} value={p} title={p}>{p.split(/[\\/]/).filter(Boolean).pop() || p}</option>)}</select></label>
    </div>
    <div className="nx-am-body nx-scroll">
      {error ? <p className="nx-am-error" role="alert">{error}<Button size="sm" onClick={reload}>Try again</Button></p> : null}
      {data?.loading || !data && !error ? <p className="nx-am-empty" role="status"><Spinner size={15} />Reading agents and their activity…</p> : null}
      {groups.map(group => <section className={`nx-am-group${group.levels.length === 1 ? " is-flat" : ""}`} key={group.key} aria-label={group.title}>
        <header><h3 title={group.title}>{group.title}</h3><span>{group.byId.size} {group.byId.size === 1 ? "agent" : "agents"}</span></header>
        <AgentTree board={group} label={`${group.title}: live agents and relationships`} labels={["Lead agents", "Delegated work", "Helpers"]}
          renderCard={row => <AgentCard row={row} selected={selected === row.id} onSelect={setSelected} onOpenChat={onOpenChat} onAction={(kind, row) => setAction({ kind, row })} />} />
      </section>)}
      {data && !data.loading && !groups.length && !error ? <div className="nx-am-empty"><NightTree board={board} size={150} /><strong>{filter === "needs" ? "Nobody needs you right now" : filter === "working" ? "No agents working right now" : "Your workspace is quiet"}</strong><p>Connected sessions and delegated work appear here as they run.</p><Button size="sm" icon={Moon} onClick={() => openPane("mission", "nightshift")}>Open Tonight's queue</Button></div> : null}
      {connections.length ? <details className="nx-am-connections"><summary>{connections.length} connections · messages, questions and dependencies</summary>
        <ul>{connections.map((edge, i) => <li key={`${edge.from}:${edge.to}:${edge.kind}:${i}`}><span>{byId.get(edge.from)?.title}</span><em>{edge.kind}</em><span>{byId.get(edge.to)?.title}</span></li>)}</ul></details> : null}
      {data?.sources?.some(s => !s.available) ? <p className="nx-am-coverage" role="status">Some sources are unavailable: {data.sources.filter(s => !s.available).map(s => `${SOURCE_NAMES[s.id] || s.id}: ${s.error}`).join(" · ")}</p> : null}
    </div>
    {data?.at ? <footer className="nx-am-foot">Observed {new Date(data.at).toLocaleTimeString()} · New tokens exclude cache reads{totals?.usageObservedAt ? ` · Usage scanned ${new Date(totals.usageObservedAt * 1000).toLocaleTimeString()}` : " · Usage scan pending"}</footer> : null}
    {action ? <AgentAction key={`${action.kind}:${action.row.id}`} action={action} onClose={() => setAction(null)} onDone={() => { setAction(null); void reload(); }} /> : null}
  </section>;
}
