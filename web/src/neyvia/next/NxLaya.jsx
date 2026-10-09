import { useCallback, useEffect, useRef, useState } from "react";
import { BrainCircuit, PanelRight, RotateCw } from "lucide-react";
import { LayaLearned } from "./NxLayaLearned.jsx";

import { backendBase } from "./nxApi.js";
import { os } from "./nxOsStore.js";
import { Button, Icon, Popover, StatusDot, ago } from "./nxPrimitives.jsx";
import { computerUseView, formatMs, formatTokens, hasDecisions, layaHealth, outcomeLabel, stripView, taskRows } from "./nxLayaModel.js";
import "./nxLaya.css";

// The LAYA item in the status strip and the LAYA window: whether the small local model is running
// (and if not, why, in plain words, with one way to start it), what it answered instead of the big
// one, how fast, roughly how many tokens that saved, and what computer use did. Every number is read
// from GET /api/ui/laya, which aggregates receipts written when each decision was made; Start and
// Try again call POST /api/ui/laya {operation: "restart"}.

function base() {
  const source = globalThis.window?.__NEYVIA_UI_SOURCE__;
  return backendBase() || (typeof source === "string" && source.startsWith("http") ? source : "");
}

async function callLaya(signal, body) {
  const response = await fetch(`${base()}/api/ui/laya`, body
    ? { method: "POST", credentials: "include", signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : { credentials: "include", signal });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result?.ok === false) throw new Error(result?.error || `LAYA ${body ? "restart" : "report"} failed (HTTP ${response.status})`);
  return result?.data ?? result;
}

/** Polls the report: slowly in the background, quickly while the detail is open. */
export function useLayaReport(fast) {
  const [state, setState] = useState({ report: null, error: "" });
  useEffect(() => {
    let alive = true;
    const controller = new AbortController();
    const load = async () => {
      if (document.visibilityState === "hidden") return;
      try {
        const report = await callLaya(controller.signal);
        if (alive) setState({ report, error: "" });
      } catch (error) {
        if (alive && error?.name !== "AbortError") setState(current => ({ ...current, error: error.message }));
      }
    };
    void load();
    const timer = setInterval(load, fast ? 3000 : 15000);
    return () => { alive = false; controller.abort(); clearInterval(timer); };
  }, [fast]);
  const apply = useCallback(report => setState({ report, error: "" }), []);
  return { ...state, apply };
}

function Stat({ label, value, tone }) {
  return (
    <div className="nx-laya-stat">
      <span className={`nx-laya-num${tone ? ` is-${tone}` : ""}`}>{value}</span>
      <span className="nx-laya-label">{label}</span>
    </div>
  );
}

/** Running or not, why in plain words, one action, and the technical reason behind Details. */
function Health({ report, onReport }) {
  const health = layaHealth(report);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const restart = async () => {
    setBusy(true);
    setFailure("");
    try {
      onReport(await callLaya(undefined, { operation: "restart" }));
    } catch (error) {
      setFailure(`LAYA couldn't be started. ${error.message}`);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className={`nx-laya-card nx-laya-health is-${health.kind}`} aria-label="LAYA status" aria-live="polite">
      <div className="nx-laya-health-head">
        <StatusDot tone={health.tone} pulse={health.kind === "starting"} />
        <strong>{health.title}</strong>
      </div>
      {health.line ? <p>{health.line}</p> : null}
      {health.after ? <p className="nx-laya-quiet">{health.after}</p> : null}
      {health.action ? (
        <div className="nx-laya-actions">
          <Button variant={health.action.variant} size="sm" icon={RotateCw} loading={busy} onClick={restart}>
            {busy ? "Starting…" : health.action.label}
          </Button>
        </div>
      ) : null}
      {failure ? <p className="nx-laya-failure" role="alert">{failure}</p> : null}
      {health.details.length ? (
        <details className="nx-laya-details">
          <summary>Details</summary>
          <dl>
            {health.details.map(([label, value]) => (
              <div key={label}><dt>{label}</dt><dd>{String(value)}</dd></div>
            ))}
          </dl>
        </details>
      ) : null}
    </section>
  );
}

function ComputerUse({ cu }) {
  if (!cu) return null;
  return (
    <section className="nx-laya-card" aria-label="Computer use">
      <h4 className="nx-laya-h">Computer use</h4>
      <p className="nx-laya-state"><StatusDot tone={cu.tone} /> {cu.line}</p>
      {cu.hint ? <p className="nx-laya-quiet">{cu.hint}</p> : null}
      {cu.used ? (
        <>
          <div className="nx-laya-stats">
            <Stat label="actions" value={cu.actions} />
            <Stat label="by agents / by you" value={`${cu.byAgent} / ${cu.byPaul}`} />
            <Stat label="times it got in your way" value={cu.disturbances} tone={cu.disturbanceTone === "red" ? "bad" : ""} />
            <Stat label="average action" value={cu.avg} />
          </div>
          {cu.refused || cu.workflows ? (
            <p className="nx-laya-quiet">{[cu.refused ? `${cu.refused} refused or failed` : "", cu.workflows].filter(Boolean).join(". ")}.</p>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function Detail({ report, error, onReport }) {
  if (!report) {
    return (
      <section className="nx-laya-card nx-laya-health" aria-live="polite">
        <div className="nx-laya-health-head"><StatusDot tone="idle" /><strong>LAYA</strong></div>
        <p title={error || undefined}>{error ? "LAYA's activity couldn't be read just now. Neyvia will try again in a moment." : "Reading LAYA activity…"}</p>
      </section>
    );
  }
  const { totals } = report;
  const decided = hasDecisions(report);
  const tasks = taskRows(report);
  const health = layaHealth(report);
  return (
    <>
      <Health report={report} onReport={onReport} />
      <LayaLearned instant={report.instant} />
      {decided ? (
        <section className="nx-laya-card" aria-label="LAYA decisions">
          <h4 className="nx-laya-h">Decisions</h4>
          <div className="nx-laya-stats">
            <Stat label="answered by LAYA" value={totals.answered || 0} tone={totals.answered ? "ok" : ""} />
            <Stat label="handed to your main model" value={totals.escalated || 0} />
            <Stat label="median answer" value={formatMs(totals.p50Ms)} />
            <Stat label="tokens saved (est.)" value={formatTokens(totals.tokensSavedEstimate)} />
          </div>
          {tasks.length ? (
            <>
              <h4 className="nx-laya-h">By task</h4>
              <div className="nx-laya-rows">
                {tasks.map(row => (
                  <div key={row.key} className="nx-laya-row">
                    <span className="nx-laya-task" title={row.path}>{row.task}</span>
                    <span className="nx-laya-figures">
                      <span>{row.answered} answered</span>
                      <span>{row.escalated} handed up</span>
                      <span>{row.p50}</span>
                      <span className="nx-laya-saved">~{row.saved} tokens</span>
                    </span>
                  </div>
                ))}
              </div>
            </>
          ) : null}
          {report.recent?.length ? (
            <>
              <h4 className="nx-laya-h">Latest</h4>
              <div className="nx-laya-rows">
                {report.recent.slice(0, 5).map((row, index) => (
                  <div key={`${row.at}-${index}`} className="nx-laya-recent">
                    <span className={`nx-laya-dot is-${row.outcome}`} />
                    <span className="nx-laya-task">{row.task}: {outcomeLabel(row.outcome)}</span>
                    <span className="nx-laya-when">{ago(row.at)}</span>
                  </div>
                ))}
              </div>
            </>
          ) : null}
          <p className="nx-laya-note">{report.boundary}</p>
        </section>
      ) : health.kind === "ready" ? (
        <p className="nx-laya-quiet nx-laya-empty">Nothing answered yet. Each routine decision a task hands to LAYA shows up here.</p>
      ) : null}
      <ComputerUse cu={computerUseView(report.computerUse)} />
    </>
  );
}

/** LAYA as a window of its own (NxStage app "laya"): the same report, placeable like any app. */
export function NxLayaApp() {
  const { report, error, apply } = useLayaReport(true);
  return <div className="nx-laya-app nx-scroll"><div className="nx-laya-detail"><Detail report={report} error={error} onReport={apply} /></div></div>;
}

export function LayaIndicator({ calm = false }) {
  const anchor = useRef(null);
  const [open, setOpen] = useState(false);
  const { report, error, apply } = useLayaReport(open);
  const view = stripView(report);
  // Calm density keeps the strip quiet, but LAYA appears as soon as it has decided something.
  if (calm && !open && !((report?.totals?.answered || 0) + (report?.totals?.escalated || 0))) return null;
  return (
    <>
      <button ref={anchor} type="button" className={`nx-ind nx-strip-secondary nx-laya${open ? " is-open" : ""}`} aria-label="LAYA activity"
        title="LAYA: routine decisions answered locally, and what computer use did" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Icon as={BrainCircuit} size={12} />
        <StatusDot tone={view.tone} />
        <span>{view.text}</span>
      </button>
      <Popover anchor={anchor} open={open} onClose={() => setOpen(false)} placement="top-start" width={380} label="LAYA activity">
        <div className="nx-ind-detail nx-laya-detail is-popover"><Detail report={report} error={error} onReport={apply} /></div>
        <div className="nx-laya-window">
          <button type="button" className="nx-btn nx-btn-ghost nx-btn-sm" onClick={() => { setOpen(false); os.openApp("laya", "", null); }}>
            <Icon as={PanelRight} size={14} />Open as a window
          </button>
        </div>
      </Popover>
    </>
  );
}
