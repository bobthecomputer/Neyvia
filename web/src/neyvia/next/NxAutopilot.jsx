import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight, CircleAlert, Copy, Play, PlaneTakeoff, Square } from "lucide-react";

import "./nxAutopilot.css";
import { Icon, Spinner, StatusDot, compactTokens, local, useTick } from "./nxPrimitives.jsx";
import { autopilotGet, autopilotList, autopilotResume, autopilotStart, autopilotStop } from "./nxAgentsApi.js";
import { SCOPES, checkLine, newRequestId, procedureName, scopeOf, scopeTools, shapeRun } from "./nxAutopilotModel.js";
import { durationText } from "./nxConductorModel.js";
import { useOs } from "./nxOsStore.js";

// Autopilot mode on a chat (plan 15 T17). Paul writes a few asks; Neyvia turns
// them into a checklist, runs each item through a manual procedure or its saved
// script with executable checks, and asks a model only where the manual leaves a
// real choice (GPT-6 Luna first, GPT-6.1 Sol on disagreement or a gap). No
// check-ins unless an action would be irreversible or out of scope. The panel
// shows the checklist ticking, which items needed no model at all, which did and
// why, and every model call with its actual tokens. The run is durable on the
// PC: the bus pushes each change (autopilot.state) and a read every 1.5 s while
// it runs stays the truth, also across a service restart.

const POLL_MS = 1500;

/** This chat's runs: listed once, then kept fresh by the bus and by reading the live one. */
export function useAutopilotRuns(sessionId) {
  const pushed = useOs(state => state.autopilot);
  const [runs, setRuns] = useState({});
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    setRuns({});
    if (!sessionId) return undefined;
    autopilotList()
      .then(result => { if (alive) setRuns(Object.fromEntries((result?.runs || []).filter(run => run.sessionId === sessionId).map(run => [run.runId, run]))); })
      .catch(failure => { if (alive) setError(failure.message); });
    return () => { alive = false; };
  }, [sessionId]);
  // The bus copy wins when it is newer (it carries elapsedMs that only grows).
  const merged = useMemo(() => {
    const next = { ...runs };
    for (const run of Object.values(pushed || {})) {
      if (run.sessionId !== sessionId) continue;
      const known = next[run.runId];
      if (!known || (run.elapsedMs || 0) >= (known.elapsedMs || 0)) next[run.runId] = run;
    }
    return Object.values(next).sort((a, b) => (a.startedAt || 0) - (b.startedAt || 0));
  }, [runs, pushed, sessionId]);
  const latest = merged[merged.length - 1] || null;
  const live = latest && (latest.status === "planning" || latest.status === "running");
  const latestId = latest?.runId;
  useEffect(() => {
    if (!live || !latestId) return undefined;
    let alive = true;
    const timer = setInterval(async () => {
      if (document.hidden) return;
      try {
        const result = await autopilotGet(latestId);
        if (alive && result?.run) setRuns(current => ({ ...current, [latestId]: result.run }));
      } catch (failure) { if (alive) setError(failure.message); }
    }, POLL_MS);
    return () => { alive = false; clearInterval(timer); };
  }, [live, latestId]);
  const put = useCallback(run => { if (run?.runId) setRuns(current => ({ ...current, [run.runId]: run })); }, []);
  return { runs: merged, latest, error, put };
}

/** The composer's Autopilot switch. */
export function AutopilotToggle({ on, onChange, disabled }) {
  return (
    <button type="button" className={`nx-ap-toggle${on ? " is-on" : ""}`} aria-pressed={on} disabled={disabled} onClick={() => onChange(!on)}
      title={on ? "Autopilot is on: your message becomes a checklist Neyvia finishes without asking" : "Autopilot: finish a list of asks without check-ins"}>
      <Icon as={PlaneTakeoff} size={14} />
      <span>Autopilot</span>
    </button>
  );
}

/** What Autopilot may touch, chosen per chat. */
export function AutopilotScope({ value, onChange }) {
  return (
    <span className="nx-ap-scope" role="radiogroup" aria-label="What Autopilot may do">
      {SCOPES.map(scope => (
        <button key={scope.value} type="button" role="radio" aria-checked={value === scope.value} className={value === scope.value ? "is-on" : ""} onClick={() => onChange(scope.value)}>
          {scope.label}
        </button>
      ))}
    </span>
  );
}

/** Per-chat Autopilot choice (on/off, scope), kept in this browser. */
export function useAutopilotMode(sessionId) {
  const [mode, setMode] = useState(() => local.get(`autopilot.${sessionId}`, { on: false, scope: "look" }));
  useEffect(() => { setMode(local.get(`autopilot.${sessionId}`, { on: false, scope: "look" })); }, [sessionId]);
  const update = patch => setMode(current => {
    const next = { ...current, ...patch };
    local.set(`autopilot.${sessionId}`, next.on || next.scope !== "look" ? next : null);
    return next;
  });
  return [mode, update];
}

/** Start a run for this chat. Returns the run so the panel shows it before the first bus event. */
export async function startAutopilot({ sessionId, text, scope }) {
  const result = await autopilotStart({ requestId: newRequestId(sessionId), text, sessionId, scopeTools: scopeTools(scope) });
  if (result?.ok === false && !result.run) throw new Error(result.error || "Autopilot didn't start");
  return result.run;
}

function Mark({ status }) {
  if (status === "completed") {
    return (
      <svg className="nx-checklist-mark is-done" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="7" />
        <path d="M4.8 8.3 7 10.4l4.2-4.6" pathLength="1" />
      </svg>
    );
  }
  if (status === "blocked") return <Icon as={CircleAlert} size={16} className="nx-ap-mark-bad" />;
  return <span className={`nx-checklist-mark is-${status === "in_progress" ? "current" : "pending"}`} aria-hidden="true" />;
}

function CallLine({ call }) {
  return (
    <li className={`nx-ap-call${call.status === "failed" ? " is-failed" : ""}`}>
      <span className="nx-ap-call-model">{call.model}</span>
      <span className="nx-ap-call-why">{call.purpose.text}</span>
      <span className="nx-ap-call-cost">{call.total != null ? `${call.total.toLocaleString()} tokens` : "tokens not reported"}{call.elapsedMs ? ` · ${durationText(call.elapsedMs)}` : ""}{call.status === "failed" ? " · failed" : ""}</span>
    </li>
  );
}

function Item({ item, open, onToggle }) {
  const { how } = item;
  const cost = how.calls ? `${compactTokens(how.tokens) || 0} tokens` : "0 tokens";
  const copy = () => { void navigator.clipboard?.writeText(JSON.stringify({ selection: item.selection, receipt: item.receipt, verification: item.verification, frontier: item.frontier }, null, 2)); };
  return (
    <li className={`nx-ap-item is-${item.status}`}>
      <button type="button" className="nx-ap-item-line" aria-expanded={open} onClick={onToggle}>
        <Mark status={item.status} />
        <span className="nx-ap-item-ask">{item.ask}</span>
        {item.status !== "completed" && item.status !== "blocked" ? null : (
          <span className={`nx-ap-route is-${how.kind}`} title={how.why}>{how.label} · {cost}</span>
        )}
        <Icon as={open ? ChevronDown : ChevronRight} size={13} className="nx-ap-caret" />
      </button>
      {open ? (
        <div className="nx-ap-item-more">
          <p className="nx-ap-why">{item.status === "pending" ? "Not started yet." : how.why}</p>
          <dl>
            <div><dt>Step</dt><dd className="is-mono">{procedureName(item.selection)}{item.scriptId ? " (saved script)" : ""}</dd></div>
            <div><dt>Done when</dt><dd>{item.doneWhen}</dd></div>
            {item.verification || item.selection?.verify ? (
              <div><dt>Final check</dt><dd className="is-mono">{checkLine(item.verification || item.selection.verify)}{item.verification ? (item.verification.passed ? " · passed" : " · failed") : ""}</dd></div>
            ) : null}
            {how.checks ? <div><dt>Checks</dt><dd>{how.passed} of {how.checks} passed, no model needed for them</dd></div> : null}
          </dl>
          {item.modelCalls.length ? <ul className="nx-ap-calls">{item.modelCalls.map(call => <CallLine key={call.index} call={call} />)}</ul> : null}
          {(item.frontier || []).map((patch, index) => (
            <p key={index} className="nx-ap-frontier">Proposed manual fix, kept aside for review: {patch.reason}{patch.patchId || patch.id ? <span className="is-mono"> ({patch.patchId || patch.id})</span> : null}</p>
          ))}
          {item.receipt ? <button type="button" className="nx-ap-copy" onClick={copy}><Icon as={Copy} size={12} />Copy receipt</button> : null}
        </div>
      ) : null}
    </li>
  );
}

/** The latest Autopilot run of this chat, above the composer. */
export function AutopilotPanel({ sessionId, runs, latest, readError, onChanged }) {
  const run = useMemo(() => shapeRun(latest), [latest]);
  const [open, setOpen] = useState(() => Boolean(local.get("autopilot.open", true)));
  const [expanded, setExpanded] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const seen = useRef(null);
  useTick(Boolean(run?.live), 1000);
  useEffect(() => { setExpanded(null); setError(""); }, [sessionId, run?.runId]);
  // A new run opens the panel so Paul sees it start.
  useEffect(() => { if (run?.runId && seen.current && seen.current !== run.runId) setOpen(true); seen.current = run?.runId || null; }, [run?.runId]);
  if (!run) return null;
  const toggle = () => { setOpen(!open); local.set("autopilot.open", open ? false : null); };
  const control = async action => {
    setBusy(action); setError("");
    try {
      const result = action === "stop" ? await autopilotStop(run.runId) : await autopilotResume(run.runId);
      if (result?.run) onChanged(result.run);
      if (result?.ok === false && result.error) setError(result.error);
    } catch (failure) { setError(failure.message); }
    finally { setBusy(""); }
  };
  const elapsedMs = run.live && run.startedAt ? Math.max(run.elapsedMs || 0, Date.now() - run.startedAt * 1000) : run.elapsedMs;
  const headline = run.status === "planning" ? "Making the checklist…" : run.current ? run.current.ask : run.state.label;
  const usedModel = run.items.filter(item => item.status === "completed" && (item.how.kind === "model" || item.how.kind === "frontier")).length;
  return (
    <section className={`nx-ap${open ? " is-open" : ""}${run.live ? " is-live" : ""}`} aria-label="Autopilot">
      <div className="nx-ap-head">
        <button type="button" className="nx-ap-head-main" aria-expanded={open} onClick={toggle} title={open ? "Hide Autopilot" : "Show the whole run"}>
          <Icon as={PlaneTakeoff} size={15} className="nx-ap-icon" />
          <strong>Autopilot</strong>
          <span className={`nx-ap-status is-${run.state.tone}`}>{run.live ? <Spinner size={10} /> : <StatusDot tone={run.state.tone} />}{run.state.label}</span>
          {run.total ? <span className="nx-ap-count">{run.done} of {run.total}</span> : null}
          <span className="nx-ap-now" aria-live="polite">{run.live ? headline : ""}</span>
          <Icon as={ChevronDown} size={14} className="nx-ap-caret-head" />
        </button>
        {run.live ? (
          <button type="button" className="nx-ap-act" disabled={Boolean(busy)} onClick={() => void control("stop")}><Icon as={Square} size={11} />Stop</button>
        ) : run.status === "stopped" ? (
          <button type="button" className="nx-ap-act" disabled={Boolean(busy)} onClick={() => void control("resume")}><Icon as={Play} size={11} />Resume</button>
        ) : null}
      </div>
      {open ? (
        <div className="nx-ap-body nx-scroll">
          <p className="nx-ap-sum">
            {[
              run.total ? `${run.noModel} of ${run.done || 0} done with no model${run.scripts ? ` (${run.scripts} as saved scripts)` : ""}` : null,
              usedModel ? `${usedModel} needed a model` : null,
              `${run.calls.length} model ${run.calls.length === 1 ? "call" : "calls"}`,
              run.totalTokens != null ? `${run.totalTokens.toLocaleString()} tokens` : null,
              elapsedMs ? durationText(elapsedMs) : null,
            ].filter(Boolean).join(" · ")}
          </p>
          {run.items.length ? (
            <ol className="nx-ap-items">
              {run.items.map(item => <Item key={item.index} item={item} open={expanded === item.index} onToggle={() => setExpanded(expanded === item.index ? null : item.index)} />)}
            </ol>
          ) : <p className="nx-ap-wait">{run.live ? "GPT-6 Luna is turning your message into a checklist and picking a manual step for each item…" : "No checklist was saved."}</p>}
          {run.waiting ? <p className="nx-ap-note is-needs"><Icon as={CircleAlert} size={13} />Needs you: {run.waiting.reason}{run.waiting.asks?.length ? ` (${run.waiting.asks.join("; ")})` : ""}</p> : null}
          {run.error && run.status !== "completed" ? <p className="nx-ap-note is-bad"><Icon as={CircleAlert} size={13} />{run.error}</p> : null}
          {(run.dropped || []).length ? <p className="nx-ap-note">Left out: {run.dropped.map(row => `${row.ask} (${row.reason})`).join("; ")}</p> : null}
          {(run.needsPaul || []).length && !run.waiting ? <p className="nx-ap-note is-needs">Needs you: {run.needsPaul.join("; ")}</p> : null}
          {run.runLevel.length ? (
            <>
              <h4>Model calls for the whole run</h4>
              <ul className="nx-ap-calls">{run.runLevel.map(call => <CallLine key={call.index} call={call} />)}</ul>
            </>
          ) : null}
          <p className="nx-ap-foot">
            {scopeOf(run.scopeTools) === "edit" ? "May read and edit files in Neyvia's workspace; every edit checks the file didn't change first." : "Reads files in Neyvia's workspace; changes nothing."}
            {runs.length > 1 ? ` ${runs.length - 1} earlier ${runs.length === 2 ? "run" : "runs"} in this chat.` : ""}
          </p>
          {error || readError ? <p className="nx-ap-note is-bad" role="alert">{error || readError}</p> : null}
        </div>
      ) : null}
    </section>
  );
}
