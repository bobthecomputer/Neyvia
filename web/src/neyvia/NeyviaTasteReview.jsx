import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, CircleDot, Info, Loader2, ScanEye } from "lucide-react";
import "./neyviaTasteReview.css";

const SEVERITY = {
  block: { label: "Blocking", Icon: AlertTriangle },
  warn: { label: "Warning", Icon: CircleDot },
  note: { label: "Note", Icon: Info },
};

function artifactUrl(path) {
  const base = String(import.meta.env?.VITE_FLUXIO_BACKEND_URL || globalThis.window?.__FLUXIO_BACKEND_URL__ || "").trim().replace(/\/$/, "");
  return `${base}/api/artifact?path=${encodeURIComponent(path)}`;
}

// The same preview.taste tool the agent uses, run on demand for the page in
// Preview: rendered screenshots plus measured findings, never a beauty score.
export function NeyviaTasteReview({ url = "", goal = "", savedJourney = null, callBackend }) {
  const [state, setState] = useState({ status: "idle" });
  const [reviewGoal, setReviewGoal] = useState(String(goal || ""));
  const requestRef = useRef(0);
  const target = String(url || "").trim();
  const reviewable = /^(https?|file):/i.test(target);
  const purpose = reviewGoal.trim();

  useEffect(() => {
    requestRef.current += 1;
    setState({ status: "idle", url: target });
  }, [target]);

  useEffect(() => { setReviewGoal(String(goal || "")); }, [goal]);

  const run = async () => {
    if (!reviewable || typeof callBackend !== "function") return;
    const requestId = ++requestRef.current;
    setState({ status: "running", url: target, goal: purpose });
    try {
      const response = await callBackend(
        "call_native_tool_command",
        { tool: "preview.taste", arguments: { url: target, goal: purpose, delayMs: 1200, includeImageData: Boolean(globalThis.__TAURI_INTERNALS__) } },
        { throwOnError: true },
      );
      const report = response?.result || response;
      if (response?.ok === false || !report?.gate) throw new Error(response?.error || "The review did not return a report.");
      if (requestRef.current === requestId) setState({ status: "ready", url: target, goal: purpose, report });
    } catch (error) {
      if (requestRef.current === requestId) setState({ status: "error", url: target, goal: purpose, error: String(error?.message || error) });
    }
  };

  const currentState = state.url === target && state.goal === purpose ? state : { status: "idle" };
  const report = currentState.report;
  const shots = Object.entries(report?.screenshots || {});
  return (
    <section className="neyvia-taste-review" data-taste-gate={report?.gate || ""} data-taste-state={currentState.status}>
      <header>
        <div>
          <strong>Design review</strong>
          <span>Renders this page on desktop and phone and measures what people meet first.</span>
        </div>
        <button disabled={!reviewable || currentState.status === "running"} onClick={run} type="button">
          {currentState.status === "running" ? <Loader2 aria-hidden="true" className="neyvia-taste-spin" size={14} /> : <ScanEye aria-hidden="true" size={14} />}
          {currentState.status === "running" ? "Reviewing…" : report ? "Review again" : "Review"}
        </button>
      </header>
      <label className="neyvia-taste-goal">
        <span>Goal to review</span>
        <textarea aria-label="Design review goal" maxLength={600} onChange={event => {
          requestRef.current += 1;
          setReviewGoal(event.target.value);
        }} placeholder="What should this page help someone do?" rows={2} value={reviewGoal} />
      </label>
      {!reviewable ? <p className="neyvia-taste-note">Open a served page in Preview to review it.</p> : null}
      {currentState.status === "error" ? <p className="neyvia-taste-note" role="alert">{currentState.error}</p> : null}
      {report ? (
        <>
          <div className="neyvia-taste-summary" role="status">
            <span className="neyvia-taste-gate" data-gate={report.gate}>
              {report.gate === "clear" ? <CheckCircle2 aria-hidden="true" size={14} /> : <AlertTriangle aria-hidden="true" size={14} />}
              {report.gate === "clear" ? "No blocking defect" : "Blocking defects"}
            </span>
            <span>{report.counts?.block || 0} blocking · {report.counts?.warn || 0} warnings · {report.counts?.note || 0} notes</span>
          </div>
          <div className="neyvia-taste-scope" aria-label="Review coverage">
            <span>Checked: desktop and phone render</span>
            <span>{report.journey?.passed ? "L-A-Y-A: goal flow passed" : report.journey ? "L-A-Y-A: goal flow failed" : savedJourney?.state === "passed" ? "Saved app journey passed" : "Goal flow not tested here"}</span>
            <span>Human taste and full intent still need review</span>
          </div>
          {savedJourney?.state === "passed" && !report.journey ? <p className="neyvia-taste-note">Saved app journey {savedJourney.runId ? `· ${savedJourney.runId}` : ""} is separate from this visual review.</p> : null}
          {shots.length ? (
            <details className="neyvia-taste-captures">
              <summary>Desktop and phone captures <span>{shots.length}</span></summary>
              <div className="neyvia-taste-shots">
                {shots.map(([viewport, shot]) => (
                  <a href={shot.dataUrl || artifactUrl(shot.path)} key={viewport} rel="noopener noreferrer" target="_blank">
                    <img alt={`${viewport} render of the page`} loading="lazy" src={shot.dataUrl || artifactUrl(shot.path)} />
                    <span>{viewport}</span>
                  </a>
                ))}
              </div>
            </details>
          ) : null}
          {report.findings?.length ? (
            <ol className="neyvia-taste-findings">
              {report.findings.slice(0, 12).map((finding, index) => {
                const meta = SEVERITY[finding.severity] || SEVERITY.note;
                return (
                  <li data-severity={finding.severity} key={`${finding.rule}-${finding.viewport}-${index}`}>
                    <meta.Icon aria-hidden="true" size={14} />
                    <div>
                      <strong>{finding.title}</strong>
                      <small>{meta.label} · {finding.viewport}</small>
                      <p>{finding.fix}</p>
                    </div>
                  </li>
                );
              })}
            </ol>
          ) : null}
          <p className="neyvia-taste-note">{report.boundary}</p>
        </>
      ) : null}
    </section>
  );
}

export default NeyviaTasteReview;
