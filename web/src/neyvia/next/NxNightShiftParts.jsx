import { useEffect, useState } from "react";
import { AlertTriangle, Check, Clock, Copy, FileText, Gauge, Hand, MessageSquare, Moon, RotateCcw, Terminal } from "lucide-react";

import "./nxNightShift.css";
import { Button, Icon, StatusDot, compactTokens, useTick } from "./nxPrimitives.jsx";
import { callNx } from "./nxApi.js";
import { os } from "./nxOsStore.js";
import { nightshift } from "./nxNightShiftApi.js";
import { HARNESSES, duration, evidenceView, harnessLabel, policyForm, policyPatch, quietNow, reasonText } from "./nxNightShiftModel.js";

// Pieces of the Night Shift board (NxNightShift.jsx) that also show elsewhere:
// the growing tree, the morning card (home widget too) and the budget panel.

export { NightTree } from "./NxAgentTree.jsx";
import { NightTree } from "./NxAgentTree.jsx";

/** Opens what a piece of evidence points at: the file, the agent's chat, or copies a commit. */
export function EvidenceLink({ evidence, onOpenChat }) {
  const view = evidenceView(evidence);
  if (!view) return null;
  const copy = async () => {
    try { await navigator.clipboard.writeText(view.hash || view.detail || ""); os.notify({ level: "success", message: "Commit copied" }); }
    catch { os.notify({ level: "warning", message: "Couldn't copy. Select the text instead." }); }
  };
  if (view.kind === "file") return <button type="button" className="nx-ns-ev" title={view.detail} onClick={() => os.showPane("file", view.path)}><Icon as={FileText} size={12} />{view.label}</button>;
  if (view.kind === "run" && view.sessionId && onOpenChat) return <button type="button" className="nx-ns-ev" title={view.detail} onClick={() => onOpenChat(view.sessionId)}><Icon as={MessageSquare} size={12} />Open the agent's chat</button>;
  if (view.kind === "commit") return <button type="button" className="nx-ns-ev is-mono" title={`${view.detail} · copy`} onClick={copy}><Icon as={Copy} size={12} />{view.label}</button>;
  if (view.kind === "command") return <span className="nx-ns-ev is-static" title={view.detail}><Icon as={Terminal} size={12} />{view.label}<em>your word</em></span>;
  return <span className="nx-ns-ev is-static" title={view.detail}><Icon as={Check} size={12} />{view.label}</span>;
}

const clock = iso => {
  const time = iso ? new Date(iso) : null;
  return time && Number.isFinite(time.getTime()) ? time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
};

/**
 * The morning card (07 R6): done with evidence, blocked and why, waiting on
 * you, tokens and time. Built only from the backend's measured summary.
 */
export function MorningCard({ data, board, onOpenChat, selectedId, onNewNight, busy, compact = false }) {
  useTick(Boolean(data?.running?.length), 30000);
  if (!data) return null;
  const lines = compact ? 3 : 6;
  const unreported = data.tokenBreakdownUnknownRuns || data.unknownRuns;
  return (
    <section className={`nx-ns-morning${compact ? " is-compact" : ""}`} aria-label="Morning summary">
      {compact ? null : <NightTree board={board} size={200} selectedId={selectedId} />}
      <div className="nx-ns-morning-body">
        <header className="nx-ns-morning-head">
          <Icon as={Moon} size={14} />
          <strong>{data.empty ? "Nothing ran yet" : `${data.done.length} done${data.blocked.length ? ` · ${data.blocked.length} blocked` : ""}${data.needsReview?.length ? ` · ${data.needsReview.length} need review` : ""}${data.waitingOnPaul.length ? ` · ${data.waitingOnPaul.length} waiting on you` : ""}`}</strong>
          {onNewNight ? <Button size="sm" icon={RotateCcw} disabled={busy || Boolean(data.running.length)} onClick={onNewNight}
            title={data.running.length ? "Stop or finish running tasks first" : "Start counting a new night's budget"}>New night</Button> : null}
        </header>
        <p className="nx-ns-morning-meta">
          <span><Icon as={Clock} size={12} />{data.nightStarted ? `Night started ${clock(data.nightStarted)} · ${duration(data.nightSeconds)} ago` : "Night not started"}</span>
          <span title="Input not read from cache, plus output"><Icon as={Gauge} size={12} /><strong>{data.newTokens == null ? "New tokens not reported" : `${compactTokens(data.newTokens) || 0} new tokens`}</strong>{unreported ? ` · ${unreported} run${unreported === 1 ? "" : "s"} without a token breakdown` : ""}</span>
          {data.cacheReadTokens == null ? null : <span>{compactTokens(data.cacheReadTokens) || 0} tokens read from cache</span>}
          <span>{duration(data.workSeconds)} of agent time</span>
        </p>
        {data.done.length ? (
          <ul className="nx-ns-morning-list" aria-label="Done">
            {data.done.slice(-lines).map(({ task, evidence }) => (
              <li key={task.id}><StatusDot tone="green" /><span className="nx-ns-morning-title">{task.title || task.id}</span><EvidenceLink evidence={evidence} onOpenChat={onOpenChat} /></li>
            ))}
          </ul>
        ) : null}
        {data.blocked.length ? (
          <ul className="nx-ns-morning-list" aria-label="Blocked">
            {data.blocked.slice(0, lines).map(task => (
              <li key={task.id}><StatusDot tone="red" /><span className="nx-ns-morning-title">{task.title || task.id}</span><span className="nx-ns-morning-why">{reasonText(task) || "Blocked"}</span></li>
            ))}
          </ul>
        ) : null}
        {data.needsReview?.length ? (
          <ul className="nx-ns-morning-list" aria-label="Needs review">
            {data.needsReview.slice(0, lines).map(task => (
              <li key={task.id}><StatusDot tone="gold" /><span className="nx-ns-morning-title">{task.title || task.id}</span><span className="nx-ns-morning-why">{reasonText(task) || "Needs review"}</span></li>
            ))}
          </ul>
        ) : null}
        {data.waitingOnPaul.length ? (
          <ul className="nx-ns-morning-list" aria-label="Waiting on you">
            {data.waitingOnPaul.slice(0, lines).map(task => (
              <li key={task.id}><Icon as={Hand} size={12} className="nx-ns-needs" /><span className="nx-ns-morning-title">{task.title || task.id}</span><span className="nx-ns-morning-why">Waiting on you</span></li>
            ))}
          </ul>
        ) : null}
        {!compact && data.harnesses.length ? (
          <div className="nx-ns-usage" aria-label="Time and tokens per agent">
            {data.harnesses.map(row => (
              <span key={row.id}>
                <strong>{row.label}</strong>
                {compactTokens(row.reportedTokens) || 0}{row.maxTokens ? ` / ${compactTokens(row.maxTokens)}` : ""} tokens with cache reads · {duration(row.elapsedSeconds)}{row.maxSeconds ? ` / ${duration(row.maxSeconds)}` : ""}
                {row.running ? " · running" : ""}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function NumberField({ label, value, onChange, unit, hint, disabled }) {
  return (
    <label className="nx-ns-num">
      <span>{label}</span>
      <span className="nx-ns-num-box">
        <input className="nx-input" inputMode="decimal" value={value} disabled={disabled} placeholder="No limit" onChange={event => onChange(event.target.value)} />
        {unit ? <em>{unit}</em> : null}
      </span>
      {hint ? <small>{hint}</small> : null}
    </label>
  );
}

function usePlanLimits() {
  const [limits, setLimits] = useState(null);
  useEffect(() => {
    let alive = true;
    callNx("connected_agents_dashboard_command", {}).then(result => { if (alive) setLimits(result?.limits || []); }).catch(() => { if (alive) setLimits([]); });
    return () => { alive = false; };
  }, []);
  return limits;
}

/** Night budget, per-agent budgets, GPU quiet hours and the plan hold. Saved through nightshift.resources. */
export function BudgetPanel({ policy, summary, onSaved, onClose }) {
  const [form, setForm] = useState(() => policyForm(policy || {}));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const limits = usePlanLimits();
  useEffect(() => { setForm(policyForm(policy || {})); }, [policy]);
  const { patch, problems } = policyPatch(form);
  const set = change => setForm(current => ({ ...current, ...change }));
  const setBudget = (id, change) => setForm(current => ({ ...current, budgets: { ...current.budgets, [id]: { ...current.budgets[id], ...change } } }));
  const save = async () => {
    setBusy(true); setError("");
    try { await nightshift("resources", patch); os.notify({ level: "success", message: "Night Shift budget saved" }); onSaved?.(); }
    catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  };
  const usage = summary?.perHarness || {};
  const planRows = (limits || []).filter(row => row.app === "codex" || row.app === "claude-code");
  const holdAt = Number(form.holdAt) || 70;
  const quietOn = form.quietOn && quietNow({ start: form.quietStart, end: form.quietEnd, timeZone: form.quietTz });

  return (
    <form className="nx-ns-budget" aria-label="Budget and quiet hours" onSubmit={event => { event.preventDefault(); if (!problems.length) void save(); }}>
      <header><strong>Budget and quiet hours</strong><span>Checked before every launch and while tasks run.</span></header>

      <label className="nx-ns-check"><input type="checkbox" checked={form.paused} onChange={event => set({ paused: event.target.checked })} />
        <span><strong>Pause Night Shift</strong><small>Nothing new starts. Running tasks finish.</small></span></label>

      <fieldset className="nx-ns-group">
        <legend>The whole night</legend>
        <div className="nx-ns-grid">
          <NumberField label="Hours per night" unit="h" value={form.maxNightHours} onChange={value => set({ maxNightHours: value })} hint="Running tasks stop when it's reached" />
          <NumberField label="Tasks at once" value={form.maxConcurrent} onChange={value => set({ maxConcurrent: value })} hint="Never two in the same repo" />
          <NumberField label="Minutes per task" unit="min" value={form.maxTaskMinutes} onChange={value => set({ maxTaskMinutes: value })} />
          <NumberField label="Tokens per task" value={form.maxTaskTokens} onChange={value => set({ maxTaskTokens: value })} />
        </div>
      </fieldset>

      <fieldset className="nx-ns-group">
        <legend>Per agent</legend>
        <div className="nx-ns-harness-rows">
          <div className="nx-ns-harness-head" aria-hidden="true"><span>Used this night</span><span>Tokens</span><span>Hours</span></div>
          {HARNESSES.map(({ id, label }) => {
            const row = usage[id] || {};
            return (
              <div key={id} className="nx-ns-harness-row">
                <span className="nx-ns-harness-name">{label}<small>{compactTokens(row.reportedTokens) || 0} tokens · {duration(row.elapsedSeconds)} used{row.unknownRuns ? ` · ${row.unknownRuns} not reported` : ""}</small></span>
                <NumberField label={`${label} tokens`} value={form.budgets[id]?.tokens || ""} disabled={id === "opencode"}
                  onChange={value => setBudget(id, { tokens: value })} hint={id === "opencode" ? "Not reported live yet" : ""} />
                <NumberField label={`${label} hours`} unit="h" value={form.budgets[id]?.hours || ""} onChange={value => setBudget(id, { hours: value })} />
              </div>
            );
          })}
        </div>
        <p className="nx-ns-fine">Token caps act on the usage the agent reports, so one task can overshoot a little between reports. A capped agent runs one task at a time.</p>
      </fieldset>

      <fieldset className="nx-ns-group">
        <legend>Plan limits</legend>
        <label className="nx-ns-check"><input type="checkbox" checked={form.holdOn} onChange={event => set({ holdOn: event.target.checked })} />
          <span><strong>Hold new tasks when a plan limit reaches</strong><small>Codex and Claude Code. They wait for the reset, then start on their own.</small></span></label>
        {form.holdOn ? <NumberField label="Hold at" unit="%" value={form.holdAt} onChange={value => set({ holdAt: value })} /> : null}
        {limits === null ? <p className="nx-ns-fine">Reading plan limits…</p> : planRows.length ? (
          <ul className="nx-ns-plan">
            {planRows.map(row => {
              const used = Math.round(Number(row.usedPercent));
              const held = form.holdOn && Number.isFinite(used) && used >= holdAt;
              return (
                <li key={`${row.app}-${row.window}`} className={held ? "is-held" : ""}>
                  <span>{harnessLabel(row.app)} · {row.label || row.window}</span>
                  <span className="nx-ns-plan-bar" aria-hidden="true"><i style={{ transform: `scaleX(${Math.min(1, Math.max(0, used / 100)) || 0})` }} /></span>
                  <span>{Number.isFinite(used) ? `${used}%` : "—"}{held ? " · holding" : ""}</span>
                </li>
              );
            })}
          </ul>
        ) : <p className="nx-ns-fine">No plan limits reported yet. Codex and Claude send them during a turn.</p>}
      </fieldset>

      <fieldset className="nx-ns-group">
        <legend>GPU</legend>
        <label className="nx-ns-check"><input type="checkbox" checked={form.gpuForAsr} onChange={event => set({ gpuForAsr: event.target.checked })} />
          <span><strong>Keep the GPU for dictation</strong><small>Tasks marked as needing the GPU wait.</small></span></label>
        <label className="nx-ns-check"><input type="checkbox" checked={form.quietOn} onChange={event => set({ quietOn: event.target.checked })} />
          <span><strong>Quiet GPU hours</strong><small>When you use the PC. GPU tasks wait, and running ones stop.</small></span></label>
        {form.quietOn ? (
          <div className="nx-ns-quiet">
            <label><span>From</span><input className="nx-input" type="time" value={form.quietStart} onChange={event => set({ quietStart: event.target.value })} /></label>
            <label><span>To</span><input className="nx-input" type="time" value={form.quietEnd} onChange={event => set({ quietEnd: event.target.value })} /></label>
            <label><span>Clock</span>
              <select className="nx-input" value={form.quietTz} onChange={event => set({ quietTz: event.target.value })}>
                <option value="local">This PC</option><option value="UTC">UTC</option>
              </select>
            </label>
            <span className={`nx-ns-quiet-now${quietOn ? " is-on" : ""}`}>{quietOn ? "Quiet now" : "Not quiet now"}</span>
          </div>
        ) : null}
        <p className="nx-ns-fine">Only tasks marked as needing the GPU are held; other programs aren't watched.</p>
      </fieldset>

      {problems.length ? <ul className="nx-ns-problems">{problems.map(problem => <li key={problem}><Icon as={AlertTriangle} size={12} />{problem}</li>)}</ul> : null}
      {error ? <p className="nx-ns-error" role="alert">{error}</p> : null}
      <footer className="nx-ns-foot">
        {onClose ? <Button size="sm" onClick={onClose}>Close</Button> : null}
        <Button size="sm" variant="primary" type="submit" disabled={busy || Boolean(problems.length)}>{busy ? "Saving…" : "Save budget"}</Button>
      </footer>
    </form>
  );
}
