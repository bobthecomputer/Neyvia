// What the LAYA strip item says, from the backend report (/api/ui/laya). Pure, so it is testable.

const pct = value => (Number.isFinite(value) ? `${Math.round(value * 100)}%` : "—");

export function formatTokens(value) {
  if (!Number.isFinite(value)) return "—";
  if (value >= 10000) return `${(value / 1000).toFixed(value >= 100000 ? 0 : 1)}k`;
  return String(Math.round(value));
}

export function formatMs(value) {
  if (!Number.isFinite(value)) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
}

/** The service's state in plain words, and the strip's tone. */
export function serviceView(service) {
  if (!service) return { tone: "idle", label: "LAYA not read yet" };
  if (service.ready) return { tone: "green", label: service.owned ? "LAYA is running (started by Neyvia)" : "LAYA service answering" };
  if (service.status === "starting" || service.status === "restarting") return { tone: "caution", label: `LAYA is ${service.status}: ${service.reason || "loading the local model"}` };
  return { tone: service.configured ? "red" : "idle", label: "LAYA isn't running. Your main model answers instead." };
}

/** One line for the strip: answered of asked, or the reason it has nothing to say. */
export function stripView(report) {
  if (!report) return { text: "LAYA —", tone: "idle" };
  const { totals, service } = report;
  const asked = (totals?.answered || 0) + (totals?.escalated || 0);
  const state = serviceView(service);
  const warming = ["waiting", "warming", "loading"].includes(service?.host?.instantEncoders?.state);
  if (!asked) return { text: service?.ready ? (warming ? "LAYA warming up" : "LAYA ready") : service?.status === "starting" || service?.status === "restarting" ? "LAYA starting" : service?.configured ? "LAYA offline" : "LAYA off", tone: state.tone };
  const savings = totals.tokensSavedEstimate > 0 ? ` · ~${formatTokens(totals.tokensSavedEstimate)} tok saved` : "";
  return { text: `LAYA ${totals.answered}/${asked}${savings}`, tone: state.tone };
}

const OUTCOME_LABEL = { answered: "LAYA answered", escalated: "handed up", unavailable: "unavailable", bypassed: "exact value, skipped", deterministic: "rule, no model needed" };
export const outcomeLabel = outcome => OUTCOME_LABEL[outcome] || outcome;

export function taskRows(report) {
  return (report?.tasks || []).map(row => ({
    key: `${row.task}|${row.path}`, task: row.task, path: row.path,
    answered: row.answered, escalated: row.escalated, unavailable: row.unavailable,
    answerRate: pct(row.answerRate), p50: formatMs(row.p50Ms), saved: formatTokens(row.tokensSavedEstimate),
  }));
}

/** Computer-use line items; every figure is a count of recorded driver receipts. Figures are only
 *  offered once something was done (`used`), so an unused setup reads as one plain sentence. */
export function computerUseView(cu) {
  if (!cu) return null;
  const ready = Boolean(cu.driver?.available);
  const used = (cu.actions || 0) + (cu.refused || 0) + (cu.layaWorkflowRuns || 0) > 0;
  return {
    ready, used, tone: ready ? "green" : "idle",
    line: ready ? (used ? "Computer use is set up." : "Computer use is set up. Agents haven't used it yet.") : "Computer use isn't set up yet.",
    hint: ready ? "" : "Agents can't use apps on this PC until its driver is installed.",
    actions: cu.actions || 0, byAgent: cu.byAgent || 0, byPaul: cu.byPaul || 0,
    disturbances: cu.disturbances || 0, disturbanceTone: cu.disturbances ? "red" : "green",
    refused: cu.refused || 0, avg: formatMs(cu.avgMs), active: cu.activeSessions,
    workflows: cu.layaWorkflowRuns ? `${cu.layaWorkflowVerified || 0} of ${cu.layaWorkflowRuns} LAYA workflow runs checked out` : "",
  };
}

/** Did LAYA decide anything yet? Until it has, the pane shows no figures (they would all be zero). */
export function hasDecisions(report) {
  const totals = report?.totals || {};
  return (totals.answered || 0) + (totals.escalated || 0) + (totals.unavailable || 0) > 0 || Boolean(report?.tasks?.length || report?.recent?.length);
}

// Why LAYA is not running, in plain words, from the host's problem code (laya_host.py).
const PROBLEM_LINE = {
  "runtime-missing": "Its Python runtime wasn't found on this PC.",
  "model-missing": "Its model files weren't found on this PC.",
  "code-missing": "Its program files aren't part of this install.",
  off: "It's switched off in Neyvia's LAYA settings.",
  "port-reserved": "The connection it's set to use isn't allowed.",
  "port-taken": "Another program is using the connection it needs.",
  "local-only": "Local-only mode doesn't let Neyvia start it.",
  "spawn-failed": "It couldn't be started on this PC.",
  crashed: "It stopped unexpectedly several times in a row.",
  lost: "The LAYA already running on this PC stopped answering.",
  "not-started": "Neyvia hasn't started it yet.",
  stopped: "It was stopped.",
  "not-answering": "It isn't answering right now.",
};

/** The pane's headline: is LAYA running, why not (plain words), what to do, and the technical
 *  reason kept for a Details disclosure. */
export function layaHealth(report) {
  const service = report?.service;
  if (!service) return { kind: "unknown", tone: "idle", title: "Checking LAYA…", line: "", details: [] };
  const host = service.host || {};
  const warming = ["waiting", "warming", "loading"].includes(host.instantEncoders?.state);
  if (service.ready && warming) {
    return { kind: "starting", tone: "caution", title: "LAYA is warming up", details: [],
      line: "It's loading its instant memory in the background. Until then your main model answers." };
  }
  if (service.ready) {
    return { kind: "ready", tone: "green", title: "LAYA is running", details: [],
      line: host.state === "external" ? "Using the LAYA already running on this PC." : service.owned ? "Neyvia started it and keeps it running." : "It's answering." };
  }
  if (service.status === "starting" || service.status === "restarting") {
    return { kind: "starting", tone: "caution", title: service.status === "restarting" ? "LAYA is restarting" : "LAYA is starting", details: [],
      line: "Loading the local model. This can take a minute or two." };
  }
  const problem = host.problem || (host.state === "not-started" ? "not-started" : host.state === "stopped" ? "stopped"
    : service.status === "service_unavailable" ? "not-answering" : "");
  const setup = ["runtime-missing", "model-missing", "code-missing", "off", "not-started", "stopped"].includes(problem);
  const details = [
    ["Reason", service.reason || host.reason],
    ["Technical detail", host.detail],
    ["Model folder", host.model?.path],
    ["Log", host.log],
    ["Address", service.endpoint || (host.port ? `127.0.0.1:${host.port}` : "")],
  ].filter(([, value]) => value !== undefined && value !== null && value !== "");
  const instant = report?.instant?.episodes || 0;
  return {
    kind: "down", problem, tone: setup ? "idle" : "red",
    title: problem === "off" ? "LAYA is switched off" : "LAYA isn't running",
    line: PROBLEM_LINE[problem] || "It isn't available right now.",
    after: instant ? "What it has already learned still answers here; everything else goes to your main model."
      : "Until it runs, your main model answers every decision.",
    action: problem === "not-started" || problem === "stopped" ? { label: "Start LAYA", variant: "primary" } : { label: "Try again", variant: "outline" },
    details,
  };
}
