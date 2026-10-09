import { useEffect, useMemo, useState } from "react";
import { Bot, Check, Star, TriangleAlert } from "lucide-react";

import { callNx } from "./nxApi.js";
import { Button, Icon, Spinner, StatusDot, compactTokens, elapsed, useTick } from "./nxPrimitives.jsx";
import { useNx } from "./nxStore.js";

// Sub-agents come only from what the app recorded: Agent/Task tool calls and
// their side-chains. Nothing here is estimated.
function agentRows(items) {
  return items
    .filter(item => item.kind === "tool" && item.data?.category === "agent")
    .map(item => {
      const agent = item.data.agent || {};
      return {
        id: item.id,
        title: agent.description || item.data.title || "Sub-agent",
        type: agent.subagentType || null,
        model: agent.model || null,
        status: agent.status || (item.data.status === "running" ? "running" : item.data.status === "error" ? "error" : "ok"),
        startedAt: agent.startedAt || item.at,
        durationMs: agent.durationMs ?? null,
        toolCount: agent.toolCount ?? null,
        tokens: agent.inputTokens != null || agent.outputTokens != null ? (agent.inputTokens || 0) + (agent.outputTokens || 0) : null,
      };
    })
    .sort((a, b) => (a.status === "running" ? -1 : 0) - (b.status === "running" ? -1 : 0));
}

function duration(ms) {
  if (ms == null) return "";
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return minutes < 60 ? `${minutes}m ${seconds % 60}s` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function GoalCard({ sessionId, session }) {
  const [goal, setGoal] = useState(null);
  const [state, setState] = useState({ busy: true, error: "" });
  const [draft, setDraft] = useState("");
  useEffect(() => {
    let alive = true;
    setState({ busy: true, error: "" });
    callNx("connected_session_goal_command", { id: sessionId, action: "get" })
      .then(result => { if (alive) { setGoal(result?.goal || null); setState({ busy: false, error: "" }); } })
      .catch(error => { if (alive) setState({ busy: false, error: error?.message || "Goal state is unavailable." }); });
    return () => { alive = false; };
  }, [sessionId]);
  const act = async (action, text) => {
    setState(current => ({ ...current, busy: true, error: "" }));
    try {
      const result = await callNx("connected_session_goal_command", { id: sessionId, action, ...(text ? { text } : {}) });
      setGoal(result?.goal || null);
      setDraft("");
      setState({ busy: false, error: "" });
    } catch (error) {
      setState({ busy: false, error: error?.message || "The goal didn't reach the app." });
    }
  };
  return (
    <section className="nx-goal-card" aria-label="Goal">
      <header><Icon as={Star} size={14} /><strong>Goal</strong>{state.busy ? <Spinner size={11} /> : null}</header>
      {goal?.text ? (
        <>
          <p className="nx-goal-text">{goal.text}</p>
          <div className="nx-goal-actions"><Button size="sm" variant="outline" disabled={state.busy} onClick={() => void act("clear")}>Clear goal</Button></div>
        </>
      ) : (
        <form className="nx-goal-form" onSubmit={event => { event.preventDefault(); if (draft.trim()) void act("set", draft.trim()); }}>
          <input className="nx-input" value={draft} onChange={event => setDraft(event.target.value)} placeholder={`What should ${session?.app === "codex" ? "Codex" : "it"} keep working toward?`} aria-label="Goal" />
          <Button size="sm" variant="primary" type="submit" disabled={state.busy || !draft.trim()}>Set</Button>
        </form>
      )}
      {state.error ? <p className="nx-panel-note is-error">{state.error}</p> : null}
    </section>
  );
}

export function NxAgentsPanel({ sessionId, session }) {
  const items = useNx(state => state.threads[sessionId]?.items || []);
  const rows = useMemo(() => agentRows(items), [items]);
  const working = rows.filter(row => row.status === "running").length;
  useTick(working > 0, 1000);
  const settled = rows.length - working;
  const tokenTotal = rows.reduce((sum, row) => sum + (row.tokens || 0), 0);
  const anyTokens = rows.some(row => row.tokens != null);

  return (
    <div className="nx-agents">
      {session?.capabilities?.goal ? <GoalCard sessionId={sessionId} session={session} /> : null}
      {rows.length ? (
        <ul className="nx-agent-list">
          {rows.map(row => (
            <li key={row.id} className={`nx-agent is-${row.status}`}>
              <span className="nx-agent-state">
                {row.status === "running" ? <Spinner size={11} /> : row.status === "error" ? <Icon as={TriangleAlert} size={13} /> : <Icon as={Check} size={13} />}
              </span>
              <div className="nx-agent-main">
                <strong title={row.title}>{row.title}</strong>
                <span className="nx-agent-meta">
                  {[row.type, row.model, row.tokens != null ? `${compactTokens(row.tokens)} tok` : null, row.toolCount != null ? `${row.toolCount} tool${row.toolCount === 1 ? "" : "s"}` : null].filter(Boolean).join(" · ")}
                </span>
              </div>
              <span className="nx-agent-time">{row.status === "running" ? elapsed(row.startedAt) : duration(row.durationMs)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="nx-agents-empty">
          <Icon as={Bot} size={18} />
          <p>No sub-agents in this chat yet. When the agent delegates work, each helper shows up here with its model, tokens and tools.</p>
        </div>
      )}
      {rows.length ? (
        <footer className="nx-agents-foot">
          {working ? <span className="is-live"><StatusDot tone="live" /> {working} working</span> : null}
          <span>{settled} settled</span>
          {anyTokens ? <span className="nx-agents-total">Σ {compactTokens(tokenTotal)} tok</span> : null}
        </footer>
      ) : null}
    </div>
  );
}

