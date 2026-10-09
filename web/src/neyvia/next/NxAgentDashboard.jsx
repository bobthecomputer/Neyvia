import { useEffect, useMemo, useRef, useState } from "react";
import { ChartColumn, CornerDownRight, Gauge, Hand, ListChecks, MonitorPlay, LayoutGrid, RefreshCw, Route, SquareTerminal } from "lucide-react";

import "./nxDashboard.css";
import { ProviderMark } from "./ProviderMark.jsx";
import { callNx } from "./nxApi.js";
import { cuaClient, isMissing } from "./nxCuaApi.js";
import { os } from "./nxOsStore.js";
import { Icon, Spinner, StatusDot, compactTokens, elapsed, useTick } from "./nxPrimitives.jsx";
import { appLabel, markFor } from "./NxSidebarParts.jsx";
import { DASH_PAGE, fallbackSessions, limitPercent, limitTone, limitsByApp, mergePages, nowText, providerStatus, resetsIn } from "./nxDashboardModel.js";
import { conductorList } from "./nxAgentsApi.js";
import { panesCall } from "./nxPanesApi.js";
import { shapeJob } from "./nxConductorModel.js";

// Everything working right now (plan 12 §1B): every running chat with its sub-agents nested
// under it, what each is doing, for how long and with how many tokens, and the plan limits on
// top so Paul sees when to slow down. One backend read (connected_agents_dashboard_command),
// refreshed while open. The bot reads the same thing with neyvia.agents.state. A chat whose agent
// drives an app through the computer-use driver gets "Watch", which opens the live preview.

const REFRESH_MS = 5000;
// Dev only: ?dashPage=4 shows paging with today's real chats even when fewer than a page are running.
const PAGE = (import.meta.env?.DEV && Number(new URLSearchParams(globalThis.location?.search || "").get("dashPage"))) || DASH_PAGE;

export function useDashboard(open) {
  const [data, setData] = useState(null);
  const [state, setState] = useState({ busy: false, error: "", missing: false });
  const [limitsBusy, setLimitsBusy] = useState(false);
  const [limitsError, setLimitsError] = useState("");
  const alive = useRef(true);
  const load = useRef(null);
  const pages = useRef(1); // how many pages Paul has opened with "Show more"; each refresh rereads them all
  load.current = async () => {
    setState(current => ({ ...current, busy: true }));
    try {
      const read = [];
      for (let page = 0; page < pages.current; page += 1) {
        const result = await callNx("connected_agents_dashboard_command", { limit: PAGE, offset: page * PAGE });
        read.push(result);
        if (result?.nextOffset == null) break;
      }
      const result = mergePages(read);
      if (alive.current) { setData(result); setState({ busy: false, error: "", missing: false }); }
    } catch (error) {
      // An older PC service has no dashboard yet: the strip's own list still works.
      const missing = error?.code === "unknown_command" || /unknown|not allowed/i.test(error?.message || "");
      if (alive.current) setState({ busy: false, error: missing ? "" : (error?.message || "The dashboard could not be read."), missing });
    }
  };
  useEffect(() => {
    alive.current = true;
    if (!open) return () => { alive.current = false; };
    void load.current();
    const timer = setInterval(() => { if (!document.hidden) void load.current(); }, REFRESH_MS);
    return () => { alive.current = false; clearInterval(timer); };
  }, [open]);
  const refreshLimits = async () => {
    if (limitsBusy) return;
    setLimitsBusy(true);
    setLimitsError("");
    try {
      const result = await callNx("connected_limits_command", { refresh: true, wait: false });
      if (alive.current) setData(current => ({ ...current, limits: result.limits || [], limitProviders: result.providers || [] }));
    } catch (error) {
      if (alive.current) setLimitsError(error?.message || "Limits could not be refreshed.");
    } finally {
      setLimitsBusy(false);
    }
  };
  return { data, ...state, limitsBusy, limitsError, refreshLimits, refresh: () => void load.current(), more: () => { pages.current += 1; void load.current(); } };
}

/** Conductor goals whose worker is alive, so a running goal is visible beside its chats. */
function useGoals(open) {
  const [goals, setGoals] = useState([]);
  useEffect(() => {
    if (!open) return undefined;
    let alive = true;
    let timer = 0;
    const read = async () => {
      try {
        const result = await conductorList({ limit: 25, offset: 0 });
        if (alive) setGoals((result?.jobs || []).filter(job => ["queued", "running"].includes(job.status)).map(shapeJob));
      } catch { if (alive) setGoals([]); } // no Conductor on this PC's service: nothing to show
      if (alive) timer = setTimeout(read, REFRESH_MS);
    };
    void read();
    return () => { alive = false; clearTimeout(timer); };
  }, [open]);
  return goals;
}

function Goals({ goals }) {
  if (!goals.length) return null;
  return (
    <section className="nx-dash-goals" aria-label="Goals">
      <h3>Goals</h3>
      <ul>
        {goals.map(goal => (
          <li key={goal.id}>
            <button type="button" data-close onClick={() => os.showPane("mission", `conductor:${goal.id}`)} title="Open in the Conductor">
              <Icon as={Route} size={13} />
              <span className="nx-dash-goal-text">{goal.goal}</span>
              <span className="nx-dash-meta">{goal.label}{goal.tasks.length ? ` · ${goal.done}/${goal.tasks.length}` : ""}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Chats whose agent is driving an app through the computer-use driver: chat id -> session id. */
function useDriverSessions(open) {
  const [owners, setOwners] = useState({});
  useEffect(() => {
    if (!open) return undefined;
    let alive = true;
    let timer = 0;
    const read = async () => {
      try {
        const state = await (await cuaClient()).state("");
        const next = {};
        for (const session of state?.sessions || []) if (session.status !== "ended" && session.owner?.chatId) next[session.owner.chatId] = session.id;
        if (alive) { setOwners(next); timer = setTimeout(read, REFRESH_MS); }
      } catch (error) {
        if (alive && !isMissing(error)) timer = setTimeout(read, REFRESH_MS * 3); // no driver on this PC: stop asking
      }
    };
    void read();
    return () => { alive = false; clearTimeout(timer); };
  }, [open]);
  return owners;
}

function Limits({ limits, providers = [], refreshing, error, onRefresh }) {
  const groups = limitsByApp(limits);
  return (
    <section className="nx-dash-limits" aria-label="Plan limits">
      <div className="nx-dash-limits-head">
        <strong>Plan limits</strong>
        <button type="button" className="nx-dash-limits-refresh" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? <Spinner size={11} /> : <Icon as={RefreshCw} size={11} />}Refresh limits
        </button>
      </div>
      {groups.map(group => {
        const provider = providers.find(item => item.app === group.app);
        return (
        <div key={group.app} className="nx-dash-limit-app">
          <span className="nx-dash-limit-name"><ProviderMark id={group.app === "claude-code" ? "claude" : group.app} size={13} />{appLabel(group.app)}</span>
          <span className="nx-dash-limit-checked" title={provider?.error || (provider?.checkedAt ? new Date(provider.checkedAt).toLocaleString() : "")}>
            {providerStatus(provider, group.rows)}
          </span>
          {group.rows.length ? group.rows.map(limit => {
            const used = limitPercent(limit);
            const known = used !== null;
            const tone = limitTone(limit);
            return (
              <div key={limit.window} className={`nx-dash-limit is-${tone}`}
                title={`${limit.label}: ${known ? `${used}% used` : "share not reported"}${limit.resetsAt ? `, resets ${new Date(limit.resetsAt).toLocaleString()}` : ""}${limit.at ? ` · Read ${new Date(limit.at).toLocaleString()}` : ""}${limit.stale ? " · Last known, stale" : ""}${limit.source ? ` · ${limit.source}` : ""}`}>
                <span className="nx-dash-limit-label">{limit.label}</span>
                <span className="nx-dash-bar" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={known ? used : undefined}
                  aria-label={`${appLabel(group.app)} ${limit.label} limit`}><i style={{ width: `${known ? Math.max(0, Math.min(100, used)) : 0}%` }} /></span>
                <span className="nx-dash-limit-value">{known ? `${Math.round(used)}%` : limit.status === "allowed_warning" ? "Close" : "—"}</span>
                <span className="nx-dash-limit-reset">{limit.stale ? "stale · " : ""}{limit.resetsAt ? `resets ${resetsIn(limit.resetsAt)}` : ""}</span>
              </div>
            );
          }) : (
            <span className="nx-dash-limit-none">
              {provider?.error || "No reading available yet."}
            </span>
          )}
        </div>
      );})}
      {error ? <p className="nx-dash-error" role="alert">{error}</p> : null}
    </section>
  );
}

const TONE = { working: "live", waiting_approval: "gold", waiting_input: "gold" };

function SubAgent({ agent }) {
  const running = agent.status === "running";
  return (
    <li className={`nx-dash-sub is-${agent.status || "ok"}`}>
      <Icon as={CornerDownRight} size={12} className="nx-dash-sub-hook" />
      {running ? <Spinner size={9} /> : <StatusDot tone={agent.status === "error" ? "red" : "green"} />}
      <span className="nx-dash-sub-main">
        <span className="nx-dash-sub-title" title={agent.title}>{agent.title}</span>
        <span className="nx-dash-meta">
          {[agent.type, running && agent.now ? agent.now : null, agent.tokens != null ? `${compactTokens(agent.tokens)} tok` : null].filter(Boolean).join(" · ")}
        </span>
      </span>
      <span className="nx-dash-time">{running ? elapsed(agent.startedAt) : "done"}</span>
    </li>
  );
}

/** Open Claude Code's real CLI for this session: the live read-only view of a running turn, else a terminal window. */
function OpenCli({ row, onNote }) {
  const open = async () => {
    onNote("");
    try {
      const result = await panesCall("claude.open", { session: row.id });
      if (result.mode === "view") os.showPane("terminal", result.target);
      else onNote("Opened in a terminal window");
    } catch (error) { onNote(error.message || "Could not open it"); }
  };
  return (
    <button type="button" data-close className="nx-dash-act" onClick={() => void open()}
      title="Show Claude Code's own terminal for this session (read-only until you take over)">
      <Icon as={SquareTerminal} size={12} /><span>Open CLI</span>
    </button>
  );
}

/** Claude Code rows, one action row: status chips on the left; Open CLI and Message on the right (Message expands a box, Esc closes). */
export function ModLine({ row, extra = null }) {
  const [open, setOpen] = useState(false);
  const [receipt, setReceipt] = useState(false);
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const mod = row.mod;
  const send = async event => {
    event.preventDefault();
    if (!text.trim()) return;
    try {
      const result = await panesCall("claude.message", { session: row.id, text });
      setNote(result.delivery === "steered" ? "Sent into the running turn" : "Queued for its next turn");
      setText("");
    } catch (error) { setNote(error.message || "Could not send"); }
  };
  const gate = mod?.gate;
  const held = mod?.blocks ? `Held back ${mod.blocks}× by checks` : null;
  return (
    <div className="nx-dash-mod">
      <div className="nx-dash-actions">
        <span className="nx-dash-chips">
          {mod ? <span className="nx-dash-chip">{mod.loaded ? "Mod on" : "Mod not seen yet"}</span> : null}
          {held ? <button type="button" className="nx-dash-chip is-link" aria-expanded={receipt} onClick={() => setReceipt(value => !value)}>{held}</button> : null}
          {mod?.held ? <span className="nx-dash-chip">Open in a terminal</span> : null}
          {mod?.queued ? <span className="nx-dash-chip">{`${mod.queued} message${mod.queued > 1 ? "s" : ""} waiting`}</span> : null}
        </span>
        <span className="nx-dash-btns">
          {extra}
          <OpenCli row={row} onNote={setNote} />
          <button type="button" className="nx-dash-act" onClick={() => setOpen(value => !value)} aria-expanded={open}><span>Message</span></button>
        </span>
      </div>
      {receipt && gate ? (
        <p className="nx-dash-meta nx-dash-receipt">{`Last check ${gate.passed ? "passed" : "failed"}: ${(gate.failing || []).join(", ") || "all contracts"} · ${gate.note || ""}`}</p>
      ) : null}
      {open ? (
        <form className="nx-dash-msg" onSubmit={send}>
          <input autoFocus value={text} onChange={event => setText(event.target.value)} onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); setOpen(false); } }}
            placeholder="Tell this session something" aria-label="Message this Claude Code session" maxLength={2000} />
          <button type="submit" className="nx-dash-act" disabled={!text.trim()}><span>Send</span></button>
        </form>
      ) : null}
      {note ? <p className="nx-dash-meta" role="status">{note}</p> : null}
    </div>
  );
}

function Row({ row, onOpenChat, driverSession }) {
  const subs = row.subagents || [];
  const watch = row.driver?.sessionId || driverSession;
  const text = nowText(row);
  return (
    <li className="nx-dash-row">
      <button type="button" data-close className="nx-dash-chat" onClick={() => onOpenChat(row.id)} title={`Open ${row.title}`}>
        <ProviderMark id={markFor(row)} size={16} />
        <span className="nx-dash-main">
          <span className="nx-dash-title">{row.title}</span>
          <span className="nx-dash-now">
            {row.now?.kind === "plan" ? <Icon as={ListChecks} size={12} /> : row.now?.kind === "waiting" || row.status !== "working" ? <Icon as={Hand} size={12} /> : null}
            <span>{text || "Working"}</span>
          </span>
          <span className="nx-dash-meta nx-dash-meta-line">
            <StatusDot tone={TONE[row.status] || "idle"} pulse={row.status === "working"} />
            <span>{[row.plan ? `${row.plan.done}/${row.plan.total}` : null, row.tokens != null ? `${compactTokens(row.tokens)} tok` : null, elapsed(row.since) || null].filter(Boolean).join(" · ")}</span>
          </span>
        </span>
      </button>
      {watch ? (
        <button type="button" data-close className="nx-dash-watch" onClick={() => os.showPane("agentview", watch)}
          title="Watch the app this agent is using, live, comment on it, or catch up with its time-lapse">
          <Icon as={MonitorPlay} size={12} />Watch{row.driver?.app ? ` ${row.driver.app}` : ""}
        </button>
      ) : null}
      {row.app === "claude-code" ? <ModLine row={row} /> : null}
      {subs.length ? <ul className="nx-dash-subs">{subs.map(agent => <SubAgent key={agent.id} agent={agent} />)}</ul> : null}
    </li>
  );
}

function Claimed({ board }) {
  if (!board?.available) return null;
  const claims = board.claims || [];
  return (
    <section className="nx-dash-claimed" aria-label="Claimed work">
      <h3>Claimed</h3>
      {claims.length ? (
        <ul>
          {claims.slice(0, 8).map((claim, index) => {
            const files = Array.isArray(claim.files) ? claim.files : [];
            return (
              <li key={claim.id || index} className={claim.stale ? "is-stale" : ""}>
                <strong>{claim.agent || "Someone"}</strong>
                <span title={files.join("\n")}>{claim.intent || "Working"}{files.length ? ` · ${files.length === 1 ? files[0].split(/[\\/]/).pop() : `${files.length} files`}` : ""}</span>
              </li>
            );
          })}
        </ul>
      ) : <p>No one has claimed any files.</p>}
      {board.error ? <p className="is-error">{board.error}</p> : null}
    </section>
  );
}

/** The dashboard body; rendered inside the strip's Agents popover. */
export function NxAgentDashboard({ open, rows, onOpenChat }) {
  const { data, busy, error, missing, refresh, more, refreshLimits, limitsBusy, limitsError } = useDashboard(open);
  const drivers = useDriverSessions(open);
  const goals = useGoals(open);
  const sessions = useMemo(() => (data?.sessions ? data.sessions : fallbackSessions(rows)), [data, rows]);
  useTick(open && sessions.length > 0, 1000);
  const total = Number.isFinite(data?.total) ? Math.max(data.total, sessions.length) : sessions.length;
  const working = sessions.filter(row => row.status === "working").length;
  const waiting = sessions.length - working;
  const hidden = total - sessions.length;
  return (
    <div className="nx-dash">
      <header className="nx-dash-head">
        <strong>Agents</strong>
        <span className="nx-dash-sum">
          {sessions.length ? `${hidden > 0 ? `${total} running · showing ${sessions.length}` : `${working} working${waiting ? ` · ${waiting} waiting for you` : ""}`}` : "Nothing running"}
        </span>
        <button type="button" data-close className="nx-dash-act nx-dash-all" onClick={() => os.showPane("sessions", "")} title="Watch every running session in one grid">
          <Icon as={LayoutGrid} size={12} /><span>View all side by side</span>
        </button>
        <button type="button" data-close className="nx-dash-refresh" onClick={() => os.showPane("usage", "")} aria-label="Open Usage" title="Usage: plan windows, tokens and estimated API cost">
          <Icon as={ChartColumn} size={12} />
        </button>
        <button type="button" className="nx-dash-refresh" onClick={refresh} aria-label="Refresh" title="Refresh">
          {busy ? <Spinner size={11} /> : <Icon as={RefreshCw} size={12} />}
        </button>
      </header>
      {data ? <Limits limits={data.limits || []} providers={data.limitProviders || []} refreshing={limitsBusy || Boolean(data.limitProviders?.some(provider => provider.refreshing))} error={limitsError} onRefresh={refreshLimits} /> : missing ? null : (
        <section className="nx-dash-limits is-loading" aria-label="Plan limits"><Icon as={Gauge} size={13} /><span>Reading plan limits…</span></section>
      )}
      {sessions.length ? (
        <>
          <ul className="nx-dash-list">{sessions.map(row => <Row key={row.id} row={row} onOpenChat={onOpenChat} driverSession={drivers[row.id]} />)}</ul>
          {data?.hasMore && hidden > 0 ? (
            <button type="button" className="nx-dash-more" onClick={more} disabled={busy}>
              {busy ? <Spinner size={11} /> : null}Show {Math.min(PAGE, hidden)} more of {hidden}
            </button>
          ) : null}
        </>
      ) : (
        <p className="nx-dash-empty">No chat is running. Claude Code, Codex and Neyvia chats show here while they work, with their helpers under them.</p>
      )}
      <Goals goals={goals} />
      <Claimed board={data?.board} />
      {error ? <p className="nx-dash-error" role="alert">{error}</p> : null}
      {missing ? <p className="nx-dash-note">This PC's Neyvia service doesn't send the full dashboard yet, so only chat names show.</p> : null}
    </div>
  );
}
