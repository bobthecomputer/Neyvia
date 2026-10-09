import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowUp,
  Ban,
  CheckCircle2,
  CircleAlert,
  CircleDashed,
  FileCode2,
  LoaderCircle,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldCheck,
  Square,
  TerminalSquare,
  Trophy,
} from "lucide-react";

import "./harnesses.css";
import { NeyviaProviderAuthQueue } from "./NeyviaProviderAuthQueue.jsx";
import { NeyviaHarnessBatches } from "./NeyviaHarnessBatches.jsx";
import { checkHarnessView } from "./proofsBViewContracts.js";

const ACTIVE_STATUSES = new Set(["queued", "running", "cancelling"]);
const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled", "interrupted"]);
const ATTENTION_STATUSES = new Set(["blocked", "failed", "interrupted"]);
const CLEANUP_STATUSES = new Set(["queued", "running", "cancelling", "blocked"]);
const RETRYABLE_STATUSES = new Set(["completed", "failed", "cancelled", "interrupted", "blocked"]);
const FLAGSHIP_HARNESS_IDS = Object.freeze([
  "neyvia-agent",
  "fluxio-hybrid",
  "deepseek-harness",
  "rook",
  "claude-code",
  "pi",
  "wallbreaker",
]);

function list(value) {
  return Array.isArray(value) ? value : [];
}

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error || "Unknown backend error");
}

async function withDeadline(promise, milliseconds, label) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = window.setTimeout(
          () => reject(new Error(`${label} did not answer within ${Math.round(milliseconds / 1000)} seconds.`)),
          milliseconds,
        );
      }),
    ]);
  } finally {
    window.clearTimeout(timer);
  }
}

function timeLabel(value) {
  if (!value) return "not started";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? String(value) : parsed.toLocaleString();
}

function median(values) {
  const measured = list(values)
    .filter(value => Number.isFinite(value) && value >= 0)
    .slice()
    .sort((left, right) => left - right);
  if (!measured.length) return null;
  const middle = Math.floor(measured.length / 2);
  return measured.length % 2
    ? measured[middle]
    : Math.round((measured[middle - 1] + measured[middle]) / 2);
}

function durationLabel(value) {
  if (!Number.isFinite(value) || value < 0) return "—";
  if (value < 1000) return `${Math.round(value)} ms`;
  if (value < 60000) return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)} s`;
  const minutes = Math.floor(value / 60000);
  const seconds = Math.round((value % 60000) / 1000);
  return `${minutes}m ${seconds}s`;
}

function summarizeHarnessJobs(jobs, harnessId, mode) {
  const terminal = list(jobs)
    .filter(job => job.harnessId === harnessId && job.mode === mode && TERMINAL_STATUSES.has(job.status))
    .slice(0, 10);
  const completed = terminal.filter(job => job.status === "completed").length;
  const receipts = terminal.filter(job => job.metrics?.receiptPresent).length;
  return {
    sampleSize: terminal.length,
    completionRate: terminal.length ? Math.round((completed / terminal.length) * 100) : null,
    receiptCoverage: terminal.length ? Math.round((receipts / terminal.length) * 100) : null,
    medianQueueMs: median(terminal.map(job => job.metrics?.queueLatencyMs)),
    medianExecutionMs: median(terminal.map(job => job.metrics?.executionDurationMs)),
  };
}

function jobOutput(job) {
  if (!job) return "Select a run to see its durable receipt.";
  const result = job.result;
  if ((job.status === "blocked" || job.cancelOutcome === "blocked-cleanup") && result) return JSON.stringify(result, null, 2);
  if (job.error) return job.error;
  if (!result) {
    if (job.waitingReason === "execution-capacity") {
      return "The worker is running and safely queued. Provider/model execution is waiting for a workspace capacity slot; no execution slot is claimed yet.";
    }
    if (ACTIVE_STATUSES.has(job.status)) {
      return "The worker is active. This view will reconnect to its saved record automatically.";
    }
    if (job.status === "blocked") {
      return "The worker stopped at a recoverable blocker. The saved run remains available for review, retry preparation, or explicit cleanup.";
    }
    return "No result was recorded.";
  }
  if (typeof result.reply === "string" && result.reply.trim()) return result.reply.trim();
  if (typeof result.summary === "string" && result.summary.trim()) return result.summary.trim();
  return JSON.stringify(result, null, 2);
}

function statusIcon(status) {
  if (status === "completed") return CheckCircle2;
  if (status === "blocked" || status === "failed" || status === "interrupted") return CircleAlert;
  if (status === "cancelled") return Ban;
  return CircleDashed;
}

function statusLabel(status, waitingReason = "") {
  if (waitingReason === "execution-capacity") return "waiting for capacity";
  if (status === "blocked") return "needs attention";
  return String(status || "unknown").replaceAll("-", " ");
}

function readinessLabel(value) {
  const normalized = String(value || "").trim();
  const labels = {
    "not-installed": "not installed",
    "provider-configured": "provider configured",
    "provider-setup-required": "provider setup required",
    "provider-unverified": "provider unverified",
  };
  return labels[normalized] || normalized.replaceAll("-", " ") || "not reported";
}

function harnessPresentation(item, catalog) {
  const hasJSpace = item.harnessId === "deepseek-harness" && list(catalog?.extensions).some(extension =>
    extension.hostHarnessId === "deepseek-harness" &&
    /j[- ]?space/i.test(`${extension.id || ""} ${extension.label || ""}`) &&
    (extension.detected === true || String(extension.readiness || "").toLowerCase() === "installed"),
  );
  const authStatus = {
    "authenticated-live": "live auth confirmed",
    "account-action-required": "account login required",
    "provider-setup-required": "provider setup required",
    "route-setup-required": "route setup required",
    "configured-unverified": "configured · live run unverified",
    "route-dependent": "model-route auth",
    "security-scope-required": "authorized security profile required",
    "not-installed": "not installed",
    "unverified": "authentication unverified",
  }[String(item.authState || "")];
  return {
    label: item.label === "Fluxio Hybrid"
      ? "Neyvia Hybrid"
      : hasJSpace
        ? "DSH + J-Space"
        : item.label,
    status: authStatus || (hasJSpace
      ? `J-Space installed · ${readinessLabel(item.readiness)}`
      : readinessLabel(item.readiness)),
  };
}

function emptyProfile(harnessId = "") {
  const isKimi = harnessId === "kimi-code";
  return {
    id: `${harnessId || "harness"}-default`,
    harnessId,
    label: "Default route",
    model: isKimi ? "k3" : "",
    smallModel: isKimi ? "k3-256k" : "",
    baseUrl: "",
    credentialEnv: isKimi ? "KIMI_API_KEY" : "",
    credentialKind: "api-key",
    compatibilityMode: "native",
  };
}

export function HarnessesSurface({ callBackend, workspaceRoot, onSetSurface }) {
  const [catalog, setCatalog] = useState(null);
  const [catalogError, setCatalogError] = useState("");
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [comparison, setComparison] = useState(null);
  const [htmlBenchmark, setHtmlBenchmark] = useState(null);
  const [comparisonError, setComparisonError] = useState("");
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [comparisonOpened, setComparisonOpened] = useState(false);
  const [jobs, setJobs] = useState([]);
  const [selectedHarnessId, setSelectedHarnessId] = useState(() => {
    try {
      return window.localStorage?.getItem("neyvia.harnesses.selected")
        || window.localStorage?.getItem("fluxio.harnesses.selected")
        || "neyvia-agent";
    } catch {
      return "neyvia-agent";
    }
  });
  const [selectedJobId, setSelectedJobId] = useState("");
  const [mode, setMode] = useState("direct");
  const [taskLane, setTaskLane] = useState("routine");
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [inspection, setInspection] = useState(null);
  const [inspectionBusy, setInspectionBusy] = useState(false);
  const [cliProxyBusy, setCliProxyBusy] = useState(false);
  const [contextTab, setContextTab] = useState("capabilities");
  const [instructionPath, setInstructionPath] = useState("AGENTS.md");
  const [instructionContent, setInstructionContent] = useState("");
  const [instructionStatus, setInstructionStatus] = useState("");
  const [securityAuthorized, setSecurityAuthorized] = useState(false);
  const [profileDraft, setProfileDraft] = useState(() => emptyProfile("neyvia-agent"));

  const workspacePath = workspaceRoot || catalog?.workspace || "";
  const harnesses = useMemo(() => {
    const rank = new Map(FLAGSHIP_HARNESS_IDS.map((id, index) => [id, index]));
    return list(catalog?.harnesses).slice().sort((left, right) => {
      const leftRank = rank.has(left.harnessId) ? rank.get(left.harnessId) : FLAGSHIP_HARNESS_IDS.length;
      const rightRank = rank.has(right.harnessId) ? rank.get(right.harnessId) : FLAGSHIP_HARNESS_IDS.length;
      return leftRank - rightRank;
    });
  }, [catalog?.harnesses]);
  const selectedHarness = harnesses.find(item => item.harnessId === selectedHarnessId) || harnesses[0];
  const harnessChoices = useMemo(() => harnesses.map(item => ({
    ...item,
    ...harnessPresentation(item, catalog),
  })), [catalog, harnesses]);
  const detectedHarnessCount = useMemo(
    () => harnesses.filter(item => item.detected).length,
    [harnesses],
  );
  const selectedJob = jobs.find(item => item.id === selectedJobId) || jobs[0] || null;
  const profiles = list(catalog?.profiles).filter(item => item.harnessId === selectedHarness?.harnessId);
  const extensions = list(catalog?.extensions).filter(
    item => item.hostHarnessId === selectedHarness?.harnessId,
  );
  const instructions = list(catalog?.context?.instructions);
  const providerSetupRequired =
    selectedHarness?.readiness === "provider-setup-required";
  const authenticationRequired = [
    "account-action-required",
    "provider-setup-required",
    "route-setup-required",
  ].includes(String(selectedHarness?.authState || ""));
  const executorModel = (
    selectedHarness?.harnessId === "kimi-code" && taskLane === "routine"
      ? profileDraft.smallModel || "k3-256k"
      : profileDraft.model || selectedHarness?.defaultModel || "reported after start"
  );
  const selectedJobRoutes = list(
    selectedJob?.request?.routeOverrides || selectedJob?.request?.route_overrides,
  );
  const selectedJobResultRoute = selectedJob?.result?.route
    || selectedJob?.result?.receipt?.route
    || selectedJob?.result?.routeReceipt
    || {};
  const savedRoute = role => selectedJobRoutes.find(item => item?.role === role) || {};
  const readRoute = savedRoute("context-reader");
  const planRoute = savedRoute("planner");
  const executeRoute = savedRoute("executor");
  const verifyRoute = savedRoute("verifier");
  const executedModel = selectedJobResultRoute.model
    || selectedJobResultRoute.modelId
    || executeRoute.model
    || executorModel;
  const visibleRoute = [
    ["Read", "Neyvia cache", readRoute.model || "receipt-bound"],
    ["Plan", planRoute.model || "GPT-5.6 Sol", planRoute.effort || "high"],
    ["Execute", selectedJob?.harnessLabel || selectedHarness?.label || "Harness", executedModel],
    ["Verify", verifyRoute.model || "GPT-5.6 Sol", verifyRoute.effort || "high"],
  ];

  const refreshCatalog = useCallback(async () => {
    setCatalogLoading(true);
    if (typeof callBackend !== "function") {
      setCatalogError("The desktop bridge is unavailable. Restart Neyvia, then retry.");
      setCatalogLoading(false);
      return;
    }
    try {
      const value = await withDeadline(
        callBackend("get_harness_catalog_command", { workspacePath }),
        18000,
        "The harness catalog",
      );
      setCatalog(value || null);
      setCatalogError("");
    } catch (error) {
      setCatalogError(errorMessage(error));
    } finally {
      setCatalogLoading(false);
    }
  }, [callBackend, workspacePath]);

  const refreshJobs = useCallback(async () => {
    if (typeof callBackend !== "function") return;
    try {
      const value = await callBackend("list_harness_jobs_command", { limit: 50 });
      const rows = list(value?.jobs);
      setJobs(rows);
      setSelectedJobId(current => current || rows[0]?.id || "");
    } catch (error) {
      setNotice(`Could not refresh recent runs: ${errorMessage(error)}`);
    }
  }, [callBackend]);

  const refreshComparison = useCallback(async () => {
    if (typeof callBackend !== "function") return;
    setComparisonLoading(true);
    try {
      const [value, htmlValue] = await withDeadline(
        Promise.all([
          callBackend("get_harness_comparison_command", {}),
          callBackend("get_html_site_benchmark_command", {}),
        ]),
        8000,
        "The measured harness comparison",
      );
      setComparison(value || null);
      setHtmlBenchmark(htmlValue || null);
      setComparisonError("");
    } catch (error) {
      setComparisonError(errorMessage(error));
    } finally {
      setComparisonLoading(false);
    }
  }, [callBackend]);

  useEffect(() => {
    void refreshCatalog();
    void refreshJobs();
  }, [refreshCatalog, refreshJobs]);

  useEffect(() => {
    let pending = false;
    const timer = window.setInterval(async () => {
      if (pending || document.hidden) return;
      pending = true;
      try { await refreshJobs(); } finally { pending = false; }
    }, jobs.some(job => ACTIVE_STATUSES.has(job.status)) ? 1800 : 15000);
    return () => window.clearInterval(timer);
  }, [refreshJobs, jobs.some(job => ACTIVE_STATUSES.has(job.status))]);

  useEffect(() => {
    if (!selectedHarness) return;
    try {
      window.localStorage?.setItem("neyvia.harnesses.selected", selectedHarness.harnessId);
    } catch {
      // Storage can be unavailable in hardened browser contexts.
    }
    const saved = list(catalog?.profiles).find(item => item.harnessId === selectedHarness.harnessId);
    setProfileDraft(saved ? { ...emptyProfile(selectedHarness.harnessId), ...saved } : emptyProfile(selectedHarness.harnessId));
    setTaskLane(selectedHarness.harnessId === "kimi-code" ? "routine" : "standard");
    if (selectedHarness.securityOnly || selectedHarness.harnessId === "fluxio-hybrid") setMode("orchestration");
    setSecurityAuthorized(false);
    setInspection(null);
  }, [catalog?.profiles, selectedHarness]);

  const queueCounts = useMemo(() => ({
    active: jobs.filter(item => ACTIVE_STATUSES.has(item.status)).length,
    needsReview: jobs.filter(item => ATTENTION_STATUSES.has(item.status)).length,
  }), [jobs]);
  const telemetry = useMemo(
    () => summarizeHarnessJobs(jobs, selectedHarness?.harnessId, mode),
    [jobs, mode, selectedHarness?.harnessId],
  );
  const selectedJobTimeline = list(selectedJob?.timeline);
  const selectedJobBlocked = selectedJob?.status === "blocked";
  const comparisonRows = useMemo(
    () => list(comparison?.summaries).filter(item => item.eligible),
    [comparison?.summaries],
  );
  const excludedComparisonRows = useMemo(
    () => list(comparison?.eligibility).filter(item => item.included !== true),
    [comparison?.eligibility],
  );
  const comparisonLeader = comparisonRows.find(
    item => item.harnessId === comparison?.leader?.harnessId,
  );
  const htmlBenchmarkLeader = list(htmlBenchmark?.attempts).find(
    item => item.id === htmlBenchmark?.leader,
  );
  const failureReasons = useMemo(() => {
    const values = new Map();
    list(comparison?.attempts).forEach(attempt => {
      if (!attempt?.failureReason || values.has(attempt.harnessId)) return;
      values.set(attempt.harnessId, attempt.failureReason);
    });
    return values;
  }, [comparison?.attempts]);

  async function launch() {
    const message = prompt.trim();
    if (
      !message
      || !selectedHarness
      || busy
      || (selectedHarness.securityOnly && !securityAuthorized)
    ) return;
    setBusy(true);
    setNotice("");
    try {
      const catalogModel = String(selectedHarness.defaultModel || "").trim();
      const isKimi = selectedHarness.harnessId === "kimi-code";
      const requestedModel = (
        isKimi && taskLane === "routine"
          ? String(profileDraft.smallModel || "").trim()
            || (profileDraft.baseUrl
              ? String(profileDraft.model || "").trim()
              : "k3-256k")
          : String(profileDraft.model || "").trim()
      ) || (["provider-selected", "route-selected", "auto"].includes(catalogModel) ? "" : catalogModel);
      const job = await callBackend("start_harness_job_command", {
        mode,
        authorizedSecurity: selectedHarness.securityOnly && securityAuthorized,
        taskLane: isKimi ? taskLane : "standard",
        harnessId: selectedHarness.harnessId,
        harnessLabel: selectedHarness.label,
        runtime: selectedHarness.executionAdapter,
        runtimeId: selectedHarness.executionAdapter,
        defaultRuntime: selectedHarness.executionAdapter,
        harnessProfileId: profileDraft.id || "",
        model: requestedModel,
        route: {
          provider: selectedHarness.executionAdapter,
          model: requestedModel,
          role: "executor",
          taskLane: isKimi ? taskLane : "standard",
          budgetClass: isKimi && taskLane === "routine" ? "efficient" : "premium",
        },
        routeOverrides: [
          {
            role: "context-reader",
            runtimeId: "neyvia-context",
            provider: "neyvia-context",
            model: "receipt-bound-cache",
            effort: "retrieval",
            budgetClass: "efficient",
          },
          {
            role: "planner",
            runtimeId: "codex",
            provider: "openai-codex",
            model: "gpt-5.6-sol",
            effort: "high",
            budgetClass: "premium",
          },
          {
            role: "executor",
            runtimeId: selectedHarness.executionAdapter,
            provider: selectedHarness.executionAdapter,
            model: requestedModel,
            effort: "high",
            budgetClass: isKimi && taskLane === "routine" ? "efficient" : "premium",
          },
          {
            role: "verifier",
            runtimeId: "codex",
            provider: "openai-codex",
            model: "gpt-5.6-sol",
            effort: "high",
            budgetClass: "premium",
          },
        ],
        workspacePath,
        message,
        objective: message,
      });
      setPrompt("");
      setSelectedJobId(job.id);
      setJobs(current => [job, ...current.filter(item => item.id !== job.id)]);
      setNotice(`Run ${job.id.slice(-8)} is saved in run history.`);
    } catch (error) {
      setNotice(`Launch failed: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function cancelSelected() {
    if (!selectedJob || !CLEANUP_STATUSES.has(selectedJob.status) || busy) return;
    const wasBlocked = selectedJob.status === "blocked";
    setBusy(true);
    try {
      const job = await callBackend("cancel_harness_job_command", { jobId: selectedJob.id });
      setJobs(current => current.map(item => item.id === job.id ? job : item));
      setNotice(
        wasBlocked
          ? `Blocked run ${job.id.slice(-8)} was explicitly cleaned up as ${job.status}.`
          : `Run ${job.id.slice(-8)} is ${job.status}.`,
      );
    } catch (error) {
      setNotice(`${wasBlocked ? "Blocked-run cleanup" : "Cancellation"} failed safely: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function retrySelected() {
    if (!selectedJob || !RETRYABLE_STATUSES.has(selectedJob.status)) return;
    const wasBlocked = selectedJob.status === "blocked";
    setPrompt(selectedJob.prompt || selectedJob.request?.message || "");
    setMode(selectedJob.mode === "orchestration" ? "orchestration" : "direct");
    const matching = harnesses.find(item => item.harnessId === selectedJob.harnessId);
    if (matching) setSelectedHarnessId(matching.harnessId);
    setNotice(
      wasBlocked
        ? "The blocked request is prepared as a new run. Fix the blocker, review the request, then send; the original receipt stays preserved until you clean it up."
        : "The saved request is restored. Review it, then send it as a new run.",
    );
  }

  async function inspectRuntime() {
    if (!selectedHarness || selectedHarness.harnessId === "fluxio-hybrid") return;
    setInspectionBusy(true);
    try {
      const value = await callBackend("get_harness_runtime_inspection_command", {
        workspacePath,
        harnessId: selectedHarness.harnessId,
      });
      setInspection(value);
      setNotice("");
    } catch (error) {
      setNotice(`Inspection failed: ${errorMessage(error)}`);
    } finally {
      setInspectionBusy(false);
    }
  }

  async function manageCliProxy(action) {
    if (cliProxyBusy) return;
    setCliProxyBusy(true);
    try {
      const value = await callBackend("manage_cli_proxy_api_command", {
        workspacePath,
        action,
      });
      setInspection(current => ({ ...(current || {}), cliProxyApi: value?.status || null }));
      setNotice(value?.message || `CLIProxyAPI ${action} completed.`);
      await inspectRuntime();
    } catch (error) {
      setNotice(`CLIProxyAPI ${action} failed: ${errorMessage(error)}`);
    } finally {
      setCliProxyBusy(false);
    }
  }

  async function loadInstruction(path) {
    setInstructionStatus("Loading…");
    try {
      const value = await callBackend("get_harness_instruction_command", { workspacePath, path });
      setInstructionPath(value.relativePath || path);
      setInstructionContent(value.content || "");
      setInstructionStatus(value.exists ? "Loaded from the workspace." : "New supported instruction file.");
    } catch (error) {
      setInstructionStatus(errorMessage(error));
    }
  }

  async function saveInstruction() {
    setInstructionStatus("Saving with a recovery copy…");
    try {
      const value = await callBackend("save_harness_instruction_command", {
        workspacePath,
        path: instructionPath,
        content: instructionContent,
      });
      setInstructionStatus(value.backupPath ? `Saved. Backup: ${value.backupPath}` : "Saved.");
      await refreshCatalog();
    } catch (error) {
      setInstructionStatus(errorMessage(error));
    }
  }

  async function saveProfile() {
    setNotice("Saving the secret-free route profile…");
    try {
      const value = await callBackend("save_harness_profile_command", {
        workspacePath,
        profile: { ...profileDraft, harnessId: selectedHarness.harnessId },
      });
      setProfileDraft(current => ({ ...current, ...value }));
      setNotice("Profile saved. Credentials remain environment-variable references only.");
      await refreshCatalog();
    } catch (error) {
      setNotice(`Profile save failed: ${errorMessage(error)}`);
    }
  }

  const StatusIcon = statusIcon(selectedJob?.status);
  const receiptView = checkHarnessView({
    job: selectedJob,
    label: selectedJob ? statusLabel(selectedJob.status, selectedJob.waitingReason) : "No run selected",
    output: jobOutput(selectedJob),
    terminal: Boolean(selectedJob && TERMINAL_STATUSES.has(selectedJob.status)),
    attention: Boolean(selectedJob && ATTENTION_STATUSES.has(selectedJob.status)),
    cleanup: Boolean(selectedJob && CLEANUP_STATUSES.has(selectedJob.status)),
    retry: Boolean(selectedJob && RETRYABLE_STATUSES.has(selectedJob.status)),
    rows: jobs.map(job => ({ job, label: statusLabel(job.status, job.waitingReason) })),
  });

  return (
    <section
      className="neyvia-harnesses"
      data-catalog-state={catalogLoading ? "loading" : selectedHarness ? "ready" : "unavailable"}
      data-harnesses-surface="true"
      style={{ "--harness-accent": selectedHarness?.accent || "#70e1b2" }}
    >
      <header className="neyvia-harnesses__header">
        <div>
          {onSetSurface && <button className="neyvia-surface-back" type="button" onClick={() => onSetSurface('agent')}>← Agent</button>}
          <h1>Harnesses</h1>
          <p>Choose an agent runtime, check its connection, and run a task.</p>
        </div>
      </header>

      <details className="neyvia-harnesses__provider-connections">
        <summary>Provider connections</summary>
        <NeyviaProviderAuthQueue callBackend={callBackend} />
      </details>
      <section className="neyvia-harnesses__chooser" aria-label="Harness environment">
        <label>
          <span>Environment</span>
          <select
            aria-label="Execution environment"
            disabled={catalogLoading || !harnessChoices.length}
            onChange={event => {
              setSelectedHarnessId(event.target.value);
              setNotice("");
            }}
            value={selectedHarness?.harnessId || ""}
          >
            {!harnessChoices.length ? <option value="">{catalogLoading ? 'Checking environments…' : 'No environments available'}</option> : null}
            {harnessChoices.map(item => (
              <option key={item.harnessId} value={item.harnessId}>{item.label} — {item.status}</option>
            ))}
          </select>
        </label>
        <div
          aria-label={`${detectedHarnessCount} of ${harnessChoices.length} harnesses detected`}
          className="neyvia-harnesses__constellation"
          role="img"
        >
          {harnessChoices.map(item => (
            <span
              data-active={item.harnessId === selectedHarness?.harnessId ? "true" : "false"}
              data-readiness={item.detected ? (item.readiness === "provider-setup-required" ? "setup" : "ready") : "blocked"}
              key={item.harnessId}
              style={{ "--harness-node": item.accent }}
              title={`${item.label}: ${item.status}`}
            />
          ))}
        </div>
        <p><strong>{detectedHarnessCount}</strong><span> detected</span><em>{harnessChoices.length - detectedHarnessCount} need setup</em></p>
      </section>

      {harnessChoices.length > 0 && <details className="neyvia-harnesses__explanation"><summary>About the {harnessChoices.length} integrations</summary><p>Native uses Neyvia’s agent loop. Hybrid coordinates selected harnesses. The list includes installed runtimes and those that need setup.</p></details>}
      {catalogError || (!catalogLoading && !catalog) ? (
        <div className="neyvia-harnesses__alert" role="alert">
          <CircleAlert size={18} />
          <span><strong>Catalog unavailable.</strong> {catalogError || "No readiness data was returned."}</span>
          <button onClick={() => void refreshCatalog()} type="button">Retry</button>
        </div>
      ) : null}

      <div className="neyvia-harnesses__layout">
        <main className="neyvia-harnesses__console">
          <div className="neyvia-harnesses__console-head">
            <div>
              <span
                className={`neyvia-harnesses__readiness ${
                  selectedHarness?.detected && !providerSetupRequired && !authenticationRequired
                    ? "ready"
                    : selectedHarness?.detected
                      ? ""
                      : "blocked"
                }`}
              />
              <strong>{
                selectedHarness?.label === "Fluxio Hybrid"
                  ? "Neyvia Hybrid"
                  : selectedHarness?.label
                    || (catalogLoading ? "Checking local runtimes" : "Harness catalog unavailable")
              }</strong>
              <small>{
                selectedHarness?.version
                  || selectedHarness?.command
                  || selectedHarness?.readiness
                  || (catalogLoading ? "Reading installed environments…" : "Retry the readiness check above")
              }</small>
            </div>
            <div className="neyvia-harnesses__console-controls">
              <label className="neyvia-harnesses__mode-switch">
                <span>Inspect</span>
                <input
                  aria-label="Orchestration mode"
                  checked={mode === "orchestration"}
                  disabled={selectedHarness?.securityOnly || selectedHarness?.harnessId === "fluxio-hybrid"}
                  onChange={event => setMode(event.target.checked ? "orchestration" : "direct")}
                  type="checkbox"
                />
                <i aria-hidden="true" />
                <span>Orchestrate</span>
              </label>
              <span className="neyvia-harnesses__workspace" title={workspacePath}>{workspacePath || "Workspace pending"}</span>
            </div>
          </div>

          {!catalogLoading && !selectedHarness ? (
            <div className="neyvia-harnesses__unavailable" role="status">
              <CircleAlert size={20} />
              <div>
                <strong>Execution environments could not be read</strong>
                <p>Restore the desktop bridge, then retry. No model route or harness activity is inferred while readiness is unknown.</p>
              </div>
            </div>
          ) : null}

          {mode === "orchestration" ? <div className="neyvia-harnesses__route" aria-label="Current orchestration route">
            {visibleRoute.map(([role, owner, detail], index) => (
              <div className={index === 2 ? "active" : ""} key={role}>
                <span>{index + 1}</span>
                <p><small>{role}</small><strong>{owner}</strong><em>{detail}</em></p>
              </div>
            ))}
          </div> : null}

          <div className="neyvia-harnesses__composer">
            <div className="neyvia-harnesses__composer-title">
              <strong>Run a task</strong>
              <span>Describe the work for the selected runtime.</span>
            </div>
            {selectedHarness?.harnessId === "kimi-code" ? (
              <div className="neyvia-harnesses__lane" aria-label="Kimi task lane">
                <span>Task lane</span>
                <button
                  className={taskLane === "routine" ? "active" : ""}
                  onClick={() => setTaskLane("routine")}
                  type="button"
                >
                  Routine · {profileDraft.smallModel || "k3-256k"}
                </button>
                <button
                  className={taskLane === "deep" ? "active" : ""}
                  onClick={() => setTaskLane("deep")}
                  type="button"
                >
                  Deep · {profileDraft.model || "k3"}
                </button>
                <small>
                  The selected model is written into the durable run receipt. Neyvia never swaps lanes silently.
                </small>
              </div>
            ) : null}
            {selectedHarness?.securityOnly ? (
              <label className="neyvia-harnesses__security-ack">
                <input
                  checked={securityAuthorized}
                  onChange={event => setSecurityAuthorized(event.target.checked)}
                  type="checkbox"
                />
                <span>
                  <strong>Authorized security campaign</strong>
                  I confirm the target is controlled or explicitly authorized. {selectedHarness.label} runs only in the executor lane.
                </span>
              </label>
            ) : null}
            <textarea
              aria-label="Harness objective"
              onChange={event => setPrompt(event.target.value)}
              onKeyDown={event => {
                if ((event.ctrlKey || event.metaKey) && event.key === "Enter") void launch();
              }}
              placeholder={mode === "direct" ? "Ask the selected CLI to inspect or explain…" : "Describe the change Neyvia should plan, apply, and verify…"}
              rows={4}
              value={prompt}
            />
            <div className="neyvia-harnesses__composer-foot">
              <span>
                <ShieldCheck size={15} />
                {providerSetupRequired || authenticationRequired
                  ? selectedHarness?.setupAction || "Provider setup required before Neyvia can launch this runner"
                  : mode === "direct"
                    ? "Isolated source mirror · writes cannot reach the workspace"
                    : "Executor may write only inside the registered workspace · planner and verifier stay read-only"}
              </span>
              <div>
                {receiptView.cleanup && !selectedJobBlocked ? <button className="secondary" disabled={busy} onClick={() => void cancelSelected()} type="button"><Square size={14} /> Stop</button> : null}
                {receiptView.cleanup && selectedJobBlocked ? <button className="secondary" disabled={busy} onClick={() => void cancelSelected()} type="button"><Ban size={14} /> Cancel & clean up</button> : null}
                {receiptView.retry ? (
        selectedJobBlocked
          ? <button className="secondary" data-harness-action="prepare-retry" disabled={busy} onClick={() => void retrySelected()} type="button"><RotateCcw size={14} /> Prepare retry</button>
          : <button className="secondary" data-harness-action="retry" disabled={busy} onClick={() => void retrySelected()} type="button"><RotateCcw size={14} /> Retry</button>
      ) : null}
                <button
                  aria-label={busy ? "Mission is starting" : "Send objective"}
                  className="neyvia-harnesses__send"
                  disabled={
                    busy
                    || !prompt.trim()
                    || !selectedHarness?.detected
                    || providerSetupRequired
                    || authenticationRequired
                    || (selectedHarness?.securityOnly && !securityAuthorized)
                  }
                  onClick={() => void launch()}
                  title={busy ? "Mission is starting" : "Send objective"}
                  type="button"
                >{busy ? <LoaderCircle className="spin" size={17} /> : <ArrowUp size={18} />}</button>
              </div>
            </div>
          </div>
          <article
            className="neyvia-harnesses__receipt"
            aria-live="polite"
            data-empty={selectedJob ? "false" : "true"}
            data-harness-attention={receiptView.attention ? "true" : "false"}
            data-harness-receipt="true"
            data-harness-terminal={receiptView.terminal ? "true" : "false"}
            id="neyvia-harness-receipt"
          >
            <div className="neyvia-harnesses__receipt-meta">
              <StatusIcon aria-hidden="true" size={17} />
              <span>{selectedJob ? `${receiptView.label}${selectedJobBlocked ? " · needs attention" : ""} · ${selectedJob.harnessLabel || selectedJob.runtime} · ${selectedJob.mode}` : "No run selected"}</span>
              {selectedJob ? <time>{timeLabel(selectedJob.updatedAt)}</time> : null}
            </div>
            {receiptView.terminal ? (
              <span aria-hidden="true" data-harness-terminal="true" hidden />
            ) : null}
            {selectedJobTimeline.length ? (
              <section aria-label="Run time-lapse" className="neyvia-harnesses__timeline">
                <header><span>Run time-lapse</span><strong>{durationLabel(selectedJob?.metrics?.totalDurationMs)}</strong></header>
                <ol>
                  {selectedJobTimeline.map((phase, index) => (
                    <li
                      data-current={index === selectedJobTimeline.length - 1 ? "true" : "false"}
                      data-phase={phase.phase}
                      key={`${phase.phase}-${phase.at}`}
                    >
                      <i aria-hidden="true" />
                      <div><strong>{phase.label}</strong><time>{timeLabel(phase.at)}</time></div>
                      <em>+{durationLabel(phase.elapsedMs)}</em>
                    </li>
                  ))}
                </ol>
              </section>
            ) : null}
            {selectedJobBlocked ? (
              <div className="neyvia-harnesses__alert" data-harness-blocker="true" role="status">
                <CircleAlert aria-hidden="true" size={18} />
                <span>
                  <strong>Run needs attention.</strong> The worker has stopped at a recoverable blocker. Fix the blocker, prepare a new retry when useful, or explicitly clean up this saved run. Neyvia keeps the original receipt intact until you decide.
                </span>
              </div>
            ) : null}
            {selectedJob?.prompt ? <div className="neyvia-harnesses__prompt"><span>neyvia›</span><p>{selectedJob.prompt}</p></div> : null}
            <pre>{receiptView.output}</pre>
          </article>

          {notice ? <p className="neyvia-harnesses__notice">{notice}</p> : null}
        </main>

        <div className="neyvia-harnesses__side">
        <aside className="neyvia-harnesses__queue">
          <div className="neyvia-harnesses__section-head">
            <span>Recent runs</span>
            <button aria-label="Refresh queue" onClick={() => void refreshJobs()} type="button"><RefreshCw size={15} /></button>
          </div>
          <div className="neyvia-harnesses__counts"><span>{queueCounts.active} active</span><span>{queueCounts.needsReview} needs review</span></div>
          <div className="neyvia-harnesses__jobs">
            {jobs.length ? receiptView.rows.map(({ job, label }) => {
              const Icon = statusIcon(job.status);
              return (
                <button
                  aria-label={`${job.harnessLabel || job.harnessId}: ${label}`}
                  className={job.id === selectedJob?.id ? "active" : ""}
                  data-status={job.status}
                  key={job.id}
                  onClick={() => setSelectedJobId(job.id)}
                  type="button"
                >
                  <Icon aria-hidden="true" size={16} />
                  <span><strong>{job.harnessLabel || job.harnessId}</strong><small>{job.promptPreview || "Saved run"}</small></span>
                  <em>{label}</em>
                </button>
              );
            }) : <p className="neyvia-harnesses__empty">Completed and active runs are saved here across sessions.</p>}
          </div>
        </aside>

        <aside className="neyvia-harnesses__context">
          <div className="neyvia-harnesses__tabs" role="tablist">
            {[["capabilities", "Runtime"], ["instructions", "Context"], ["profile", "Profile"]].map(([id, label]) => (
              <button aria-selected={contextTab === id} className={contextTab === id ? "active" : ""} key={id} onClick={() => setContextTab(id)} role="tab" type="button">{label}</button>
            ))}
          </div>

          {contextTab === "capabilities" ? (
            <div className="neyvia-harnesses__panel">
              <p>{selectedHarness?.description}</p>
              {selectedHarness?.readinessDetail ? <div className="neyvia-harnesses__alert"><CircleAlert size={16} /><span>{selectedHarness.readinessDetail}</span></div> : null}
              <div className="neyvia-harnesses__capabilities">
                {list(selectedHarness?.capabilities).map(item => <span key={item.key}><CheckCircle2 size={14} />{item.label}<small>{item.support}</small></span>)}
              </div>
              {extensions.length ? (
                <div className="neyvia-harnesses__extensions">
                  <span>Harness extensions</span>
                  {extensions.map(item => (
                    <article key={item.id}>
                      <div><strong>{item.label}</strong><small>{readinessLabel(item.readiness)}</small></div>
                      <p>{item.description}</p>
                      <footer><span>{item.licenseId}</span><a href={item.docsUrl} rel="noreferrer" target="_blank">Inspect source</a></footer>
                    </article>
                  ))}
                </div>
              ) : null}
              <dl>
                <dt>Model policy</dt><dd>{selectedHarness?.modelPolicy}</dd>
                <dt>Transport</dt><dd>{list(selectedHarness?.transports).join(" · ") || "native CLI"}</dd>
                <dt>Integration</dt><dd>{readinessLabel(selectedHarness?.integrationTier || "first-class")}</dd>
                {selectedHarness?.licenseId ? <><dt>License</dt><dd>{selectedHarness.licenseId}</dd></> : null}
              </dl>
              {selectedHarness?.harnessId !== "fluxio-hybrid" ? <button className="wide" disabled={inspectionBusy} onClick={() => void inspectRuntime()} type="button"><TerminalSquare size={15} /> {inspectionBusy ? "Inspecting…" : "Inspect native runtime"}</button> : null}
              {inspection ? (
                <div className="neyvia-harnesses__inspection">
                  <strong>{inspection.ready ? "Runtime ready" : "Runtime needs attention"}</strong>
                  {list(inspection.checks).map(check => <p key={check.key}><span>{check.status}</span>{check.detail}</p>)}
                  {selectedHarness?.harnessId === "claude-code" ? (
                    <p className="neyvia-harnesses__policy">
                      <ShieldCheck size={15} />
                      Official Claude authentication and CLIProxyAPI model routing are separate.
                      Neyvia never reports a proxy credential as a Claude account login.
                    </p>
                  ) : null}
                  {selectedHarness?.harnessId === "claude-code" && inspection.cliProxyApi ? (
                    <section className="neyvia-harnesses__proxy" data-ready={inspection.cliProxyApi.ready ? "true" : "false"}>
                      <header>
                        <div>
                          <span>Alternative model route</span>
                          <strong>CLIProxyAPI {inspection.cliProxyApi.version || ""}</strong>
                        </div>
                        <em>{inspection.cliProxyApi.ready ? "connected" : inspection.cliProxyApi.serviceRunning ? "service only" : "stopped"}</em>
                      </header>
                      <dl>
                        <dt>Endpoint</dt><dd>{inspection.cliProxyApi.recommendedBaseUrl}</dd>
                        <dt>Providers</dt><dd>{inspection.cliProxyApi.providerCount || 0}</dd>
                        <dt>Models</dt><dd>{inspection.cliProxyApi.modelCount || 0}</dd>
                      </dl>
                      {!inspection.cliProxyApi.ready ? <p>{inspection.cliProxyApi.blocker}</p> : null}
                      <div>
                        {!inspection.cliProxyApi.ready && inspection.cliProxyApi.installed ? (
                          <button disabled={cliProxyBusy} onClick={() => void manageCliProxy("connect-codex")} type="button">
                            <ShieldCheck size={14} /> {cliProxyBusy ? "Connecting…" : "Connect existing Codex login"}
                          </button>
                        ) : null}
                        <button disabled={cliProxyBusy || !inspection.cliProxyApi.installed} onClick={() => void manageCliProxy(inspection.cliProxyApi.serviceRunning ? "restart" : "start")} type="button">
                          <RefreshCw size={14} /> {cliProxyBusy ? "Working…" : inspection.cliProxyApi.serviceRunning ? "Restart proxy" : "Start proxy"}
                        </button>
                        {inspection.cliProxyApi.serviceRunning ? <button className="secondary" disabled={cliProxyBusy} onClick={() => void manageCliProxy("stop")} type="button"><Square size={13} /> Stop</button> : null}
                      </div>
                    </section>
                  ) : null}
                </div>
              ) : null}
              {selectedHarness?.docsUrl ? <a href={selectedHarness.docsUrl} rel="noreferrer" target="_blank">Open official CLI documentation</a> : null}
            </div>
          ) : null}

          {contextTab === "instructions" ? (
            <div className="neyvia-harnesses__panel">
              <label>Instruction file<select onChange={event => { setInstructionPath(event.target.value); void loadInstruction(event.target.value); }} value={instructionPath}>
                <option value="AGENTS.md">AGENTS.md</option>
                <option value="CLAUDE.md">CLAUDE.md</option>
                <option value="CLAUDE.local.md">CLAUDE.local.md</option>
                {instructions.filter(item => !["AGENTS.md", "CLAUDE.md", "CLAUDE.local.md"].includes(item.path)).map(item => <option key={item.path} value={item.path}>{item.path}</option>)}
              </select></label>
              <button className="wide" onClick={() => void loadInstruction(instructionPath)} type="button"><FileCode2 size={15} /> Load workspace file</button>
              <textarea aria-label="Harness instruction content" onChange={event => setInstructionContent(event.target.value)} rows={12} value={instructionContent} />
              <button className="wide primary" onClick={() => void saveInstruction()} type="button"><Save size={15} /> Save with backup</button>
              <small>{instructionStatus || `${catalog?.context?.instructionCount || 0} instruction files · ${catalog?.context?.skillCount || 0} skills discovered`}</small>
            </div>
          ) : null}

          {contextTab === "profile" ? (
            <div className="neyvia-harnesses__panel">
              {profiles.length ? <label>Saved profile<select onChange={event => {
                const value = profiles.find(item => item.id === event.target.value);
                if (value) setProfileDraft({ ...emptyProfile(selectedHarness.harnessId), ...value });
              }} value={profileDraft.id}>{profiles.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label> : null}
              <label>Label<input onChange={event => setProfileDraft(current => ({ ...current, label: event.target.value }))} value={profileDraft.label} /></label>
              <label>Model alias<input onChange={event => setProfileDraft(current => ({ ...current, model: event.target.value }))} placeholder={selectedHarness?.defaultModel} value={profileDraft.model} /></label>
              {["kimi-code", "claude-code"].includes(selectedHarness?.harnessId) ? (
                <label>
                  {selectedHarness.harnessId === "kimi-code" ? "Routine model alias" : "Small model alias"}
                  <input
                    onChange={event => setProfileDraft(current => ({ ...current, smallModel: event.target.value }))}
                    placeholder={selectedHarness.harnessId === "kimi-code" ? "k3-256k" : "haiku"}
                    value={profileDraft.smallModel}
                  />
                </label>
              ) : null}
              <label>Gateway URL<input onChange={event => setProfileDraft(current => ({ ...current, baseUrl: event.target.value }))} placeholder="https://…" value={profileDraft.baseUrl} /></label>
              <label>Credential environment name<input onChange={event => setProfileDraft(current => ({ ...current, credentialEnv: event.target.value.toUpperCase() }))} placeholder="PROVIDER_API_KEY" value={profileDraft.credentialEnv} /></label>
              <label>Compatibility<select onChange={event => {
                const compatibilityMode = event.target.value;
                setProfileDraft(current => ({
                  ...current,
                  compatibilityMode,
                  ...(selectedHarness?.harnessId === "claude-code" && compatibilityMode === "cliproxy" ? {
                    baseUrl: current.baseUrl || "http://127.0.0.1:8317",
                    credentialEnv: current.credentialEnv || "CLIPROXY_API_KEY",
                  } : {}),
                }));
              }} value={profileDraft.compatibilityMode}>
                {selectedHarness?.harnessId === "claude-code" ? (
                  <>
                    <option value="native">Official Claude login</option>
                    <option value="api-key">Anthropic API key</option>
                    <option value="cliproxy">CLIProxyAPI · other models</option>
                    <option value="anthropic-gateway">Anthropic Messages API gateway</option>
                    <option value="aws-bedrock">Amazon Bedrock</option>
                    <option value="google-vertex">Google Vertex AI</option>
                  </>
                ) : (
                  <>
                    <option value="native">Native</option>
                    <option value="api-key">API key</option>
                    <option value="xai-native">xAI native</option>
                    <option value="openai-compatible">OpenAI compatible</option>
                    <option value="local-proxy">Local proxy</option>
                  </>
                )}
              </select></label>
              {selectedHarness?.harnessId === "kimi-code" ? (
                <p className="neyvia-harnesses__policy">
                  Managed Kimi Code uses its official <code>kimi login</code> flow
                  and the <code>k3</code> / <code>k3-256k</code> aliases. Custom
                  API profiles must use the exact model IDs accepted by their
                  gateway; Neyvia never converts provider-specific IDs silently.
                </p>
              ) : null}
              {selectedHarness?.harnessId === "claude-code" && profileDraft.compatibilityMode === "anthropic-gateway" ? (
                <p className="neyvia-harnesses__policy neyvia-harnesses__policy--warning">
                  <CircleAlert size={15} />
                  Routing an Anthropic consumer subscription through a proxy or gateway can violate
                  Anthropic terms and may put that Anthropic account at risk. Use an API key or an
                  approved enterprise gateway. This warning does not apply to official OpenAI Codex OAuth.
                </p>
              ) : null}
              {selectedHarness?.harnessId === "claude-code" && profileDraft.compatibilityMode === "cliproxy" ? (
                <p className="neyvia-harnesses__policy">
                  <ShieldCheck size={15} />
                  This launches Claude Code against the loopback CLIProxyAPI endpoint. Its Codex
                  or provider login pays for the model route; it does not authenticate a Claude account.
                </p>
              ) : null}
              <p className="neyvia-harnesses__policy"><ShieldCheck size={15} />Neyvia stores only the environment-variable name, never its secret value.</p>
              <button className="wide primary" onClick={() => void saveProfile()} type="button"><Save size={15} /> Save route profile</button>
            </div>
          ) : null}
        </aside>
        </div>
      </div>

      <NeyviaHarnessBatches callBackend={callBackend} workspacePath={workspacePath} harness={selectedHarness} profile={profileDraft} onInspectJob={async id => {
        try {
          const job = await callBackend("get_harness_job_command", { jobId: id });
          setJobs(current => [job, ...current.filter(item => item.id !== id)]);
          setSelectedJobId(id);
          document.getElementById("neyvia-harness-receipt")?.scrollIntoView({ block: "center", behavior: "smooth" });
        } catch (error) { setNotice(`Could not read this batch result: ${errorMessage(error)}`); }
      }} />

      <details
        aria-label="Harness evidence summary"
        className="neyvia-harnesses__pulse"
        data-sample-size={telemetry.sampleSize}
      >
        <summary>
          <div>
            <span>Observed evidence</span>
            <strong>{selectedHarness?.label || "Harness"} · {mode}</strong>
          </div>
          <p>{selectedHarness?.installed ? "Installed" : "Setup needed"} · {selectedHarness?.authenticatedLive === true ? "live auth confirmed" : "auth proof pending"} · {telemetry.sampleSize} terminal receipts</p>
          <em>Details</em>
        </summary>
        <div className="neyvia-harnesses__metrics">
          <article data-state={selectedHarness?.installed ? "ready" : "blocked"}>
            <span>Installed</span>
            <strong>{selectedHarness?.installed ? "Yes" : "No"}</strong>
            <small>{selectedHarness?.version || readinessLabel(selectedHarness?.readiness)}</small>
          </article>
          <article data-state={selectedHarness?.providerConfigured === true ? "ready" : "blocked"}>
            <span>Provider</span>
            <strong>{selectedHarness?.providerConfigured === true ? "Configured" : selectedHarness?.providerConfigured === false ? "Setup needed" : "Route-owned"}</strong>
            <small>{selectedHarness?.authenticationOwner || "Not reported"}</small>
          </article>
          <article data-state={selectedHarness?.authenticatedLive === true ? "ready" : "blocked"}>
            <span>Live auth</span>
            <strong>{selectedHarness?.authenticatedLive === true ? "Confirmed" : selectedHarness?.authenticatedLive === null ? "Per route" : "Not confirmed"}</strong>
            <small>{selectedHarness?.evidence || "A live status probe is required"}</small>
          </article>
          <article data-state={selectedHarness?.benchmarkEligible ? "ready" : "blocked"}>
            <span>Site benchmark</span>
            <strong>{selectedHarness?.benchmarkEligible ? "Eligible" : "Excluded"}</strong>
            <small>{selectedHarness?.securityOnly ? "Security-only route" : selectedHarness?.setupAction || "Needs live auth proof"}</small>
          </article>
          <article>
            <span>Completion</span>
            <strong>{telemetry.completionRate === null ? "—" : `${telemetry.completionRate}%`}</strong>
            <small>{telemetry.sampleSize ? `${telemetry.sampleSize} terminal receipts` : "No terminal sample yet"}</small>
          </article>
          <article>
            <span>Median start</span>
            <strong>{durationLabel(telemetry.medianQueueMs)}</strong>
            <small>saved → worker</small>
          </article>
          <article>
            <span>Median run</span>
            <strong>{durationLabel(telemetry.medianExecutionMs)}</strong>
            <small>worker → terminal</small>
          </article>
          <article>
            <span>Receipts</span>
            <strong>{telemetry.receiptCoverage === null ? "—" : `${telemetry.receiptCoverage}%`}</strong>
            <small>terminal runs with result evidence</small>
          </article>
        </div>
      </details>

      <details
        className="neyvia-harnesses__measurement-lab"
        onToggle={event => { if (event.currentTarget.open && !comparisonOpened) { setComparisonOpened(true); void refreshComparison(); } }}
        data-measurement-state={comparisonLoading ? "loading" : comparison?.status || htmlBenchmark?.status || "unavailable"}
      >
        <summary>
          <span>Measured quality</span>
          <strong>{comparison?.leader?.status === "measured-leader" || htmlBenchmarkLeader ? "Leader evidence available" : "Evidence has not cleared the gate"}</strong>
          <em>Open two distinct protocols</em>
        </summary>
        <div className="neyvia-harnesses__measurement-lab-body">
          <section
            aria-label="Measured HTML site challenge"
            className="neyvia-harnesses__html-benchmark"
            data-benchmark-state={htmlBenchmark?.status || "not-measured"}
          >
        <header>
          <div>
            <span>Real build challenge · {htmlBenchmark?.protocolId || "evidence pending"}</span>
            <h2>{htmlBenchmarkLeader ? `${htmlBenchmarkLeader.harness} + ${htmlBenchmarkLeader.model} leads` : "No measured site leader yet"}</h2>
            <p>One frozen offline HTML brief, isolated folders, exact routes, no fallback. Scores combine structure, accessibility, responsive behavior, live interactions, reliability, and latency.</p>
          </div>
          <Trophy aria-hidden="true" size={22} />
        </header>
        <div className="neyvia-harnesses__html-results">
          {list(htmlBenchmark?.attempts).map(attempt => (
            <article data-result={attempt.status} key={attempt.id}>
              <span>{attempt.harness}</span>
              <strong>{attempt.score?.score ?? 0}<small>/100</small></strong>
              <p>{attempt.model} · {durationLabel(attempt.elapsedMs)}</p>
              <em>{attempt.status === "completed" ? "Completed exact route" : attempt.artifact ? "Artifact made; terminal budget exceeded" : "Route failed"}</em>
            </article>
          ))}
        </div>
        <footer>
          <span>Route + model measurement. Codex and OpenCode use the same GPT-5.6 Sol model, making their reliability difference more attributable to harness behavior.</span>
          <strong>Negative control: {htmlBenchmark?.negativeControl?.passed === false ? "rejected" : "pending"}</strong>
        </footer>
          </section>

          <section
            aria-label="Measured cross-harness comparison"
            className="neyvia-harnesses__comparison"
            data-comparison-state={comparisonLoading ? "loading" : comparison?.status || "unavailable"}
          >
        <header className="neyvia-harnesses__comparison-head">
          <div className="neyvia-harnesses__comparison-title">
            <span>Live proof · {comparison?.protocolId || "waiting for evidence"}</span>
            <h2>{comparison?.leader?.status === "measured-leader" ? "Neyvia Native leads this NAS" : "No verified leader yet"}</h2>
            <p>{list(comparison?.tasks).length || 2} identical read-only tasks. Exact route. Exact fields. Every claim opens back to a terminal receipt; speed breaks ties last.</p>
          </div>
          <div className="neyvia-harnesses__comparison-score" data-state={comparison?.leader?.status || "pending"}>
            <span><strong>{comparisonLeader?.correctnessRate ?? "—"}</strong><small>/100</small></span>
            <p><Trophy size={14} /><strong>{comparisonLeader?.label || "Evidence pending"}</strong><small>{comparison?.leader?.status === "measured-leader" ? "unique measured leader" : "threshold not met"}</small></p>
          </div>
          <button aria-label="Refresh measured comparison" onClick={() => void refreshComparison()} type="button"><RefreshCw size={15} /></button>
        </header>

        {comparisonLeader ? (
          <div className="neyvia-harnesses__comparison-proof" aria-label="Leader proof metrics">
            <article data-proof="pass"><CheckCircle2 size={14} /><span><small>Exact fields</small><strong>{comparisonLeader.correctnessPoints}/{comparisonLeader.correctnessMax}</strong></span></article>
            <article data-proof="pass"><CheckCircle2 size={14} /><span><small>Terminal</small><strong>{comparisonLeader.completionRate}%</strong></span></article>
            <article data-proof="pass"><CheckCircle2 size={14} /><span><small>Receipted</small><strong>{comparisonLeader.receiptCoverage}%</strong></span></article>
            <article data-proof="pass"><CheckCircle2 size={14} /><span><small>Route + isolation</small><strong>{Math.min(comparisonLeader.routeIntegrity || 0, comparisonLeader.readOnlyCoverage || 0)}%</strong></span></article>
            <article data-proof="pass"><CheckCircle2 size={14} /><span><small>Native groups</small><strong>{comparisonLeader.capabilityCoverage?.count}/{comparisonLeader.capabilityCoverage?.total}</strong></span></article>
            <article data-proof="neutral"><CircleDashed size={14} /><span><small>Median, tie-break last</small><strong>{durationLabel(comparisonLeader.medianExecutionMs)}</strong></span></article>
          </div>
        ) : null}

        {comparisonRows.length ? (
          <div className="neyvia-harnesses__comparison-table" role="table" aria-label="Eligible harness results">
            <div className="neyvia-harnesses__comparison-row is-header" role="row">
              <span>Challenge lane</span><span>Proof chain</span><span>Median</span><span>Attention</span>
            </div>
            {comparisonRows.map(row => {
              const isLeader = row.harnessId === comparison?.leader?.harnessId;
              const checks = [
                ["Exact", row.correctnessRate === 100],
                ["Complete", row.completionRate === 100],
                ["Receipt", row.receiptCoverage === 100],
                ["Route", row.routeIntegrity === 100 && row.readOnlyCoverage === 100],
              ];
              return (
                <div className={`neyvia-harnesses__comparison-row ${isLeader ? "is-leader" : ""}`} key={row.harnessId} role="row">
                  <span className="neyvia-harnesses__comparison-identity"><i aria-hidden="true" /><strong>{row.label}</strong><small>{list(row.models).join(" · ") || "route selected"}</small></span>
                  <span className="neyvia-harnesses__comparison-checks" aria-label={`${row.label} proof chain`}>
                    {checks.map(([label, passed]) => <em data-pass={passed ? "true" : "false"} key={label}>{passed ? <CheckCircle2 size={12} /> : <CircleAlert size={12} />}{label}</em>)}
                  </span>
                  <span className="neyvia-harnesses__comparison-latency"><small>Median</small>{durationLabel(row.medianExecutionMs)}</span>
                  <span className="neyvia-harnesses__comparison-result" data-result={isLeader ? "leader" : "failed"}>{isLeader ? "All gates passed" : failureReasons.get(row.harnessId) || "Did not meet threshold"}</span>
                </div>
              );
            })}
          </div>
        ) : comparisonLoading ? <p className="neyvia-harnesses__comparison-empty">Loading signed run evidence…</p> : null}

        <footer>
          <span><strong>{list(comparison?.attempts).length}</strong> live attempts <i /> <strong>{comparisonRows.length}</strong> comparable <i /> <strong>{excludedComparisonRows.length}</strong> excluded with reasons</span>
          <a
            href="#neyvia-harness-receipt"
            onClick={() => {
              const receiptJob = jobs.find(job =>
                job.harnessId === comparison?.leader?.harnessId && TERMINAL_STATUSES.has(job.status),
              );
              if (receiptJob) setSelectedJobId(receiptJob.id);
            }}
          >Inspect live receipt</a>
          <small>{comparison?.limitations?.[0] || comparisonError || "No comparison receipt has been published yet."}</small>
        </footer>
          </section>
        </div>
      </details>

    </section>
  );
}
