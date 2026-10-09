import { useEffect, useState } from "react";
import { Activity, FlaskConical, Gauge, Network, Play, RefreshCw, Scale, ShieldCheck, WandSparkles } from "lucide-react";
import {
  buildBenchmarkResultPayload,
  canConcludeExperiment,
  canSubmitBenchmarkResult,
} from "./neyviaEcosystemActionModel.js";
import { NeyviaComputerUseProofPanel } from "./NeyviaComputerUseProofPanel.jsx";
import { NeyviaSecurityRuntimePanel } from "./NeyviaSecurityRuntimePanel.jsx";
import { NeyviaAuthoredToolPanel } from "./NeyviaAuthoredToolPanel.jsx";
import { NeyviaMcpBrokerPanel } from "./NeyviaMcpBrokerPanel.jsx";

const NEYVIA_LAB_TABS = new Set(["experiments", "benchmarks", "computer-use", "security", "authored-tools", "mcp"]);
const NEYVIA_LAB_COPY = Object.freeze({
  experiments: Object.freeze({
    title: "Experiments",
    detail: "Design repeatable trials, keep every observation, and compare outcomes with the same constraints.",
  }),
  benchmarks: Object.freeze({
    title: "Deep benchmark",
    detail: "Compare models and harnesses on the same task, time, and turn budget.",
  }),
  "computer-use": Object.freeze({
    title: "Computer Use proof",
    detail: "Run an approved live or replay journey, then review the interaction record.",
  }),
  security: Object.freeze({
    title: "Security runtime",
    detail: "Review authorized scope, available protections, and supervised security plans.",
  }),
  "authored-tools": Object.freeze({
    title: "Authored tool workbench",
    detail: "Review workspace tools, their permissions, and the results of each real run.",
  }),
  mcp: Object.freeze({
    title: "MCP connections",
    detail: "Review connected tool servers, available actions, and approval history.",
  }),
});

async function callNeyvia(command, payload = {}) {
  const response = await fetch("/api/backend", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, payload }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result?.ok === false) throw new Error(result?.error || `${command} failed`);
  return result?.data || {};
}

function asList(value) {
  return Array.isArray(value) ? value : [];
}

function parseSubjects(value) {
  return Array.from(
    new Set(
      String(value || "")
        .split(/[\n,]/)
        .map(item => item.trim())
        .filter(Boolean),
    ),
  ).map(subjectId => ({ subjectId }));
}

export function NeyviaLabEvidencePanel({ onRequestAction, requestedTab = "experiments" }) {
  const [tab, setTab] = useState(() =>
    NEYVIA_LAB_TABS.has(requestedTab) ? requestedTab : "experiments",
  );
  const [experiments, setExperiments] = useState([]);
  const [benchmarks, setBenchmarks] = useState([]);
  const [state, setState] = useState("loading");
  const [error, setError] = useState("");
  const [experimentForm, setExperimentForm] = useState({
    title: "",
    hypothesis: "",
    lifetime: "session",
    authorizationContext: "",
  });
  const [benchmarkForm, setBenchmarkForm] = useState({
    task: "",
    subjects: "neyvia-native\ncodex",
    maxTurns: "20",
    maxMinutes: "30",
  });
  const [selectedExperiment, setSelectedExperiment] = useState("");
  const [actionTier, setActionTier] = useState("observe");
  const [actionTarget, setActionTarget] = useState("");
  const [actionPlan, setActionPlan] = useState(null);
  const [observation, setObservation] = useState("");
  const [verdict, setVerdict] = useState("");
  const [selectedBenchmark, setSelectedBenchmark] = useState("");
  const [resultForm, setResultForm] = useState({
    subjectId: "",
    success: "not-reported",
    comparableContext: true,
    budgetExceeded: false,
    measuredFacts: "",
  });
  const tabCopy = NEYVIA_LAB_COPY[tab] || NEYVIA_LAB_COPY.experiments;

  const refresh = async () => {
    setState("loading");
    setError("");
    try {
      const [experimentData, benchmarkData] = await Promise.all([
        callNeyvia("get_experimental_systems_command"),
        callNeyvia("get_deep_benchmark_lab_command"),
      ]);
      const experimentRows = asList(experimentData.experiments);
      setExperiments(experimentRows);
      setBenchmarks(asList(benchmarkData.runs));
      setSelectedExperiment(current => current || experimentRows[0]?.experimentId || "");
      setSelectedBenchmark(current => current || benchmarkData.runs?.[0]?.runId || "");
      setState("ready");
    } catch (nextError) {
      setState("unavailable");
      const detail = nextError instanceof Error ? nextError.message : "";
      setError(/login|sign.?in|unauthor/i.test(detail)
        ? "Sign in to use experiments and benchmark runs."
        : "Experiments and benchmarks could not connect.");
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (NEYVIA_LAB_TABS.has(requestedTab)) setTab(requestedTab);
  }, [requestedTab]);

  const createExperiment = async event => {
    event.preventDefault();
    setError("");
    try {
      const created = await callNeyvia("create_experimental_system_command", {
        title: experimentForm.title,
        hypothesis: experimentForm.hypothesis,
        lifetime: { kind: experimentForm.lifetime },
        authorizationContext: experimentForm.authorizationContext,
      });
      setSelectedExperiment(created.experimentId);
      setExperimentForm({ title: "", hypothesis: "", lifetime: "session", authorizationContext: "" });
      await refresh();
      onRequestAction?.("neyvia:lab:experiment-created", { experimentId: created.experimentId });
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Experiment could not be created");
    }
  };

  const planAction = async event => {
    event.preventDefault();
    setError("");
    setActionPlan(null);
    try {
      const plan = await callNeyvia("plan_experimental_system_action_command", {
        experimentId: selectedExperiment,
        tier: actionTier,
        target: actionTarget,
      });
      setActionPlan(plan);
      onRequestAction?.("neyvia:lab:experiment-action-planned", {
        experimentId: selectedExperiment,
        tier: actionTier,
      });
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Action could not be planned");
    }
  };

  const createBenchmark = async event => {
    event.preventDefault();
    setError("");
    try {
      await callNeyvia("create_deep_benchmark_run_command", {
        subjects: parseSubjects(benchmarkForm.subjects),
        taskContract: { task: benchmarkForm.task, contextState: "comparable" },
        budget: {
          maxTurns: Number(benchmarkForm.maxTurns),
          maxMinutes: Number(benchmarkForm.maxMinutes),
        },
      });
      setBenchmarkForm(current => ({ ...current, task: "" }));
      await refresh();
      onRequestAction?.("neyvia:lab:benchmark-created", {});
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Benchmark could not be created");
    }
  };

  const recordObservation = async event => {
    event.preventDefault();
    setError("");
    try {
      await callNeyvia("record_experimental_observation_command", {
        experimentId: selectedExperiment,
        observation,
        kind: "measurement",
      });
      setObservation("");
      await refresh();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Observation could not be recorded");
    }
  };

  const concludeExperiment = async () => {
    const experiment = experiments.find(item => item.experimentId === selectedExperiment);
    if (!canConcludeExperiment(experiment, verdict)) return;
    setError("");
    try {
      await callNeyvia("conclude_experimental_system_command", {
        experimentId: selectedExperiment,
        verdict,
      });
      setVerdict("");
      await refresh();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Experiment could not be concluded");
    }
  };

  const selectedRun = benchmarks.find(item => item.runId === selectedBenchmark) || null;

  const recordBenchmarkResult = async event => {
    event.preventDefault();
    if (!canSubmitBenchmarkResult(selectedRun, resultForm)) return;
    setError("");
    try {
      await callNeyvia("record_deep_benchmark_result_command", {
        runId: selectedRun.runId,
        result: buildBenchmarkResultPayload(resultForm),
      });
      setResultForm(current => ({ ...current, measuredFacts: "" }));
      await refresh();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Benchmark result could not be recorded");
    }
  };

  return (
    <section className="neyvia-lab-evidence" data-neyvia-lab-evidence="true">
      <header>
        <div>
          <span className="neyvia-surface-eyebrow"><Activity aria-hidden="true" size={14} /> Evidence workbench</span>
          <h3>{tabCopy.title}</h3>
          <p>{tabCopy.detail}</p>
        </div>
        <div className="neyvia-lab-evidence-tabs" role="tablist">
          <button aria-selected={tab === "experiments"} className={tab === "experiments" ? "is-selected" : undefined} onClick={() => setTab("experiments")} role="tab" type="button">
            <FlaskConical aria-hidden="true" size={14} /> Experiments
          </button>
          <button aria-selected={tab === "benchmarks"} className={tab === "benchmarks" ? "is-selected" : undefined} onClick={() => setTab("benchmarks")} role="tab" type="button">
            <Scale aria-hidden="true" size={14} /> Deep Benchmark
          </button>
          <button aria-selected={tab === "computer-use"} className={tab === "computer-use" ? "is-selected" : undefined} onClick={() => setTab("computer-use")} role="tab" type="button">
            <Activity aria-hidden="true" size={14} /> Computer Use
          </button>
          <button aria-selected={tab === "security"} className={tab === "security" ? "is-selected" : undefined} onClick={() => setTab("security")} role="tab" type="button">
            <ShieldCheck aria-hidden="true" size={14} /> Security
          </button>
          <button aria-selected={tab === "authored-tools"} className={tab === "authored-tools" ? "is-selected" : undefined} onClick={() => setTab("authored-tools")} role="tab" type="button">
            <WandSparkles aria-hidden="true" size={14} /> Authored tools
          </button>
          <button aria-selected={tab === "mcp"} className={tab === "mcp" ? "is-selected" : undefined} onClick={() => setTab("mcp")} role="tab" type="button">
            <Network aria-hidden="true" size={14} /> MCP
          </button>
          {tab === "experiments" || tab === "benchmarks" ? (
            <button aria-label="Refresh evidence workbench" onClick={refresh} type="button"><RefreshCw aria-hidden="true" size={14} /></button>
          ) : null}
        </div>
      </header>
      {error ? <div className="neyvia-ecosystem-error" role="alert">{error}</div> : null}
      {state === "unavailable" ? <p className="neyvia-empty-hint">Connect Lab services to create experiments and record benchmark runs.</p> : null}

      {tab === "experiments" ? (
        <div className="neyvia-lab-evidence-grid" role="tabpanel">
          <form onSubmit={createExperiment}>
            <strong>New experiment</strong>
            <label>Title<input onChange={event => setExperimentForm(current => ({ ...current, title: event.target.value }))} required value={experimentForm.title} /></label>
            <label>Hypothesis<textarea onChange={event => setExperimentForm(current => ({ ...current, hypothesis: event.target.value }))} required rows={3} value={experimentForm.hypothesis} /></label>
            <label>
              Lifetime
              <select onChange={event => setExperimentForm(current => ({ ...current, lifetime: event.target.value }))} value={experimentForm.lifetime}>
                <option value="session">This session</option>
                <option value="one-day">One day</option>
                <option value="until-concluded">Until concluded</option>
              </select>
            </label>
            <label>Authorization context (required for Act)<input onChange={event => setExperimentForm(current => ({ ...current, authorizationContext: event.target.value }))} placeholder="Owned device / authorized lab scope" value={experimentForm.authorizationContext} /></label>
            <button className="primary" type="submit">Create experiment</button>
          </form>

          <div className="neyvia-experiment-list" role="list">
            {experiments.map(experiment => (
              <button className={selectedExperiment === experiment.experimentId ? "is-selected" : undefined} key={experiment.experimentId} onClick={() => setSelectedExperiment(experiment.experimentId)} role="listitem" type="button">
                <span>{experiment.state}</span>
                <strong>{experiment.title}</strong>
                <p>{experiment.hypothesis}</p>
                <small>{experiment.journal?.length || 0} observations · {experiment.authorizationContextRecorded ? "Act scope recorded" : "Observe / simulate only"}</small>
              </button>
            ))}
            {state === "ready" && !experiments.length ? <p className="neyvia-empty-hint">No experiment yet.</p> : null}
          </div>

          <form onSubmit={planAction}>
            <strong>Plan a bounded action</strong>
            <label>
              Tier
              <select onChange={event => setActionTier(event.target.value)} value={actionTier}>
                <option value="observe">Observe — read or capture</option>
                <option value="simulate">Simulate — dry-run or replay</option>
                <option value="act">Act — named target, per-action approval</option>
              </select>
            </label>
            <label>Named target<input onChange={event => setActionTarget(event.target.value)} placeholder={actionTier === "act" ? "Required device or service" : "Optional"} value={actionTarget} /></label>
            <button disabled={!selectedExperiment} type="submit"><Play aria-hidden="true" size={14} /> Plan, do not execute</button>
            {actionPlan ? (
              <div className="neyvia-action-plan" data-action-tier={actionPlan.tier}>
                <strong>{actionPlan.tier}</strong>
                <span>{actionPlan.state} · {actionPlan.approval} approval</span>
                <small>{actionPlan.executable ? "Executable adapter reported" : "Plan only — no execution claimed"}</small>
              </div>
            ) : null}
            <label>
              Measurement journal
              <textarea onChange={event => setObservation(event.target.value)} rows={3} value={observation} />
            </label>
            <button disabled={!selectedExperiment || !observation.trim()} onClick={recordObservation} type="button">
              Record observation
            </button>
            <label>
              Verdict (failures are retained)
              <textarea onChange={event => setVerdict(event.target.value)} rows={3} value={verdict} />
            </label>
            <button disabled={!canConcludeExperiment(experiments.find(item => item.experimentId === selectedExperiment), verdict)} onClick={concludeExperiment} type="button">
              Conclude experiment
            </button>
          </form>
        </div>
      ) : tab === "benchmarks" ? (
        <div className="neyvia-lab-evidence-grid is-benchmark" role="tabpanel">
          <form onSubmit={createBenchmark}>
            <strong>Comparable run contract</strong>
            <label>Task<textarea onChange={event => setBenchmarkForm(current => ({ ...current, task: event.target.value }))} required rows={3} value={benchmarkForm.task} /></label>
            <label>Subjects (one per line)<textarea onChange={event => setBenchmarkForm(current => ({ ...current, subjects: event.target.value }))} required rows={4} value={benchmarkForm.subjects} /></label>
            <div className="neyvia-benchmark-budget">
              <label>Max turns<input min="1" onChange={event => setBenchmarkForm(current => ({ ...current, maxTurns: event.target.value }))} type="number" value={benchmarkForm.maxTurns} /></label>
              <label>Max minutes<input min="1" onChange={event => setBenchmarkForm(current => ({ ...current, maxMinutes: event.target.value }))} type="number" value={benchmarkForm.maxMinutes} /></label>
            </div>
            <button className="primary" type="submit"><Gauge aria-hidden="true" size={14} /> Create equal-budget run</button>
          </form>

          <div className="neyvia-benchmark-runs" role="list">
            {benchmarks.map(run => (
              <button className={selectedBenchmark === run.runId ? "is-selected" : undefined} key={run.runId} onClick={() => {
                setSelectedBenchmark(run.runId);
                const firstSubject = run.subjects?.[0];
                setResultForm(current => ({
                  ...current,
                  subjectId: String(typeof firstSubject === "object" ? firstSubject?.subjectId || "" : firstSubject || ""),
                }));
              }} role="listitem" type="button">
                <div><strong>{run.taskContract?.task || "Benchmark run"}</strong><span>{run.subjects?.length || 0} subjects · {run.results?.length || 0} results</span></div>
                <p><b>Measured facts:</b> {run.results?.length ? `${run.results.length} reported` : "not reported"}</p>
                <p><b>Interpretation:</b> {run.claim?.interpretation || "not reported"}</p>
                <small>{run.claim?.eligible ? "Comparable claim eligible" : `${run.claim?.exclusions?.length || run.subjects?.length || 0} exclusions or missing results`}</small>
              </button>
            ))}
            {state === "ready" && !benchmarks.length ? <p className="neyvia-empty-hint">No comparable run yet.</p> : null}
          </div>
          <form onSubmit={recordBenchmarkResult}>
            <strong>Record measured facts</strong>
            <label>
              Subject
              <select onChange={event => setResultForm(current => ({ ...current, subjectId: event.target.value }))} value={resultForm.subjectId}>
                <option value="">Choose subject</option>
                {(selectedRun?.subjects || []).map(subject => {
                  const subjectId = String(typeof subject === "object" ? subject.subjectId : subject);
                  return <option key={subjectId} value={subjectId}>{subjectId}</option>;
                })}
              </select>
            </label>
            <label>
              Success
              <select onChange={event => setResultForm(current => ({ ...current, success: event.target.value }))} value={resultForm.success}>
                <option value="not-reported">Not reported</option>
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            </label>
            <label className="neyvia-explicit-checkbox"><input checked={resultForm.comparableContext} onChange={event => setResultForm(current => ({ ...current, comparableContext: event.target.checked }))} type="checkbox" /> Comparable context</label>
            <label className="neyvia-explicit-checkbox"><input checked={resultForm.budgetExceeded} onChange={event => setResultForm(current => ({ ...current, budgetExceeded: event.target.checked }))} type="checkbox" /> Budget exceeded</label>
            <label>Measured facts<textarea onChange={event => setResultForm(current => ({ ...current, measuredFacts: event.target.value }))} rows={4} value={resultForm.measuredFacts} /></label>
            <button disabled={!canSubmitBenchmarkResult(selectedRun, resultForm)} type="submit">Record result</button>
          </form>
        </div>
      ) : tab === "computer-use" ? (
        <NeyviaComputerUseProofPanel />
      ) : tab === "security" ? (
        <NeyviaSecurityRuntimePanel />
      ) : tab === "authored-tools" ? (
        <NeyviaAuthoredToolPanel />
      ) : (
        <NeyviaMcpBrokerPanel />
      )}
    </section>
  );
}
