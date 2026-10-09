import { useEffect, useMemo, useRef } from "react";
import { ArrowUpRight, Plus } from "lucide-react";

import "./nxDashboard.css";
import "./nxSessions.css";
import { ProviderMark } from "./ProviderMark.jsx";
import { ModLine, useDashboard } from "./NxAgentDashboard.jsx";
import { followThread, isWorkingElsewhere, openThread, useNx } from "./nxStore.js";
import { Button, Icon, Spinner, StatusDot, compactTokens, elapsed, useTick } from "./nxPrimitives.jsx";
import { appLabel, markFor } from "./NxSidebarParts.jsx";

// Sessions (plan 29, MODH): every running session side by side, any provider, Claude Code first. Each tile shows the
// live tail of its transcript, checklist progress, tokens, the mod's status chips and the same actions as the Agents
// popover. Nothing here polls on its own: the rows come from the one dashboard read (the popover's cadence, paused while
// the page is hidden), the transcripts from the chat store, which the event stream keeps live. A session another app
// runs (no events) is re-read on that same dashboard tick.

const TAIL_LINES = 8;
const STATE = { working: ["Working", "live"], waiting_approval: ["Waiting for you", "gold"], waiting_input: ["Waiting for you", "gold"] };

/** The last few readable lines of a transcript: what was said and which tools ran, newest last. */
export function tailLines(items, count = TAIL_LINES) {
  const out = [];
  for (let index = (items || []).length - 1; index >= 0 && out.length < count; index -= 1) {
    const item = items[index];
    const data = item?.data || {};
    let lines = [];
    if (item.kind === "assistant") lines = String(data.text || "").split(/\r?\n/);
    else if (item.kind === "user") lines = String(data.text || "").split(/\r?\n/).map((line, at) => (at === 0 ? `> ${line}` : line));
    else if (item.kind === "tool" && data.title) lines = [`${data.status === "running" ? "…" : "·"} ${data.title}`];
    else if (item.kind === "approval" || item.kind === "question") lines = [`? ${data.title || "Waiting for your answer"}`];
    for (const line of lines.reverse()) {
      if (line.trim() && out.length < count) out.push(line.length > 220 ? `${line.slice(0, 217)}…` : line);
    }
  }
  return out.reverse();
}

function Tail({ lines, streaming }) {
  const box = useRef(null);
  const stuck = useRef(true);
  const onScroll = () => {
    const element = box.current;
    if (element) stuck.current = element.scrollTop + element.clientHeight >= element.scrollHeight - 8;
  };
  useEffect(() => {
    const element = box.current;
    if (element && stuck.current) element.scrollTop = element.scrollHeight; // follows new lines unless the person scrolled up
  }, [lines.join("\n")]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div ref={box} className={`nx-ss-tail${streaming ? " is-streaming" : ""}`} onScroll={onScroll} role="log" aria-live="off" tabIndex={0} aria-label="Latest transcript lines">
      {lines.length ? lines.map((line, index) => <p key={`${index}:${line.slice(0, 24)}`}>{line}</p>) : <p className="is-quiet">Nothing said yet.</p>}
    </div>
  );
}

function Tile({ row, nav }) {
  const thread = useNx(state => state.threads[row.id]);
  useEffect(() => { void openThread(row.id); }, [row.id]);
  const lines = useMemo(() => tailLines(thread?.items), [thread?.items]);
  const [label, tone] = STATE[row.status] || ["Idle", "idle"];
  const plan = row.plan;
  const percent = plan?.total ? Math.round((plan.done / plan.total) * 100) : null;
  const openChat = () => nav?.onOpenChat?.(row.id);
  const meta = [plan ? `${plan.done}/${plan.total}` : null, row.tokens != null ? `${compactTokens(row.tokens)} tok` : null, elapsed(row.since) || null].filter(Boolean).join(" · ");
  const chatButton = <button type="button" className="nx-dash-act" onClick={openChat}><Icon as={ArrowUpRight} size={12} /><span>Open chat</span></button>;
  return (
    <li className={`nx-ss-tile is-${row.status}`}>
      <header className="nx-ss-head">
        <span className="nx-ss-mark"><ProviderMark id={markFor(row)} size={20} title={appLabel(row.app)} /></span>
        <button type="button" className="nx-ss-title" onClick={openChat} title={`Open ${row.title}`}>{row.title}</button>
        <span className={`nx-dash-chip nx-ss-state is-${tone}`}><StatusDot tone={tone} pulse={row.status === "working"} />{label}</span>
      </header>
      {row.now?.text ? <p className="nx-ss-now">{row.now.text}</p> : null}
      <Tail lines={lines} streaming={row.status === "working"} />
      <div className="nx-ss-meta">
        {percent != null ? <span className="nx-ss-bar" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label="Checklist progress"><i style={{ width: `${percent}%` }} /></span> : null}
        <span className="nx-dash-meta">{meta}</span>
      </div>
      {row.app === "claude-code" ? <ModLine row={row} extra={chatButton} /> : (
        <div className="nx-dash-mod"><div className="nx-dash-actions"><span className="nx-dash-chips" /><span className="nx-dash-btns">{chatButton}</span></div></div>
      )}
    </li>
  );
}

export function NxSessionsPane({ nav }) {
  const { data, busy, error } = useDashboard(true);
  useTick(Boolean(data?.sessions?.length), 1000);
  const rows = useMemo(() => {
    const list = data?.sessions || [];
    return [...list.filter(row => row.app === "claude-code"), ...list.filter(row => row.app !== "claude-code")];
  }, [data]);
  // A session another app runs sends no events: re-read it when the dashboard refreshes (the same cadence, no new loop).
  useEffect(() => {
    for (const row of rows) {
      if (isWorkingElsewhere({ status: row.status, live_owner: row.liveOwner, app: row.app }, null)) void followThread(row.id);
    }
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <section className="nx-ss" aria-label="Running sessions">
      <header className="nx-ss-top">
        <span className="nx-dash-meta">{rows.length ? `${rows.length} running` : data ? "Nothing running" : "Reading…"}</span>
        {busy && !data ? <Spinner size={12} /> : null}
      </header>
      {rows.length ? (
        <ul className="nx-ss-grid">{rows.map(row => <Tile key={row.id} row={row} nav={nav} />)}</ul>
      ) : data ? (
        <div className="nx-ss-empty">
          <p>Nothing is running right now. Runs from Claude Code, Codex and Neyvia appear here as they start.</p>
          <Button size="sm" icon={Plus} onClick={() => nav?.onNewChat?.({ app: "claude-code" })}>Start a Claude Code run</Button>
        </div>
      ) : <div className="nx-stage-loading"><Spinner size={16} /></div>}
      {error ? <p className="nx-dash-error" role="alert">{error}</p> : null}
    </section>
  );
}
