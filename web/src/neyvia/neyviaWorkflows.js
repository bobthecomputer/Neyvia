import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
/**
 * Workflows — the third permanent thing in the sidebar.
 *
 * Chat is one turn at a time. Orchestration is a graph you assemble. A workflow
 * sits between them: a named sequence someone has already worked out, which you
 * start rather than design. That is the shape most repeated work actually has,
 * and it is why it earns a permanent place rather than living in a menu.
 *
 * The suggestion rule is the important part. A suggestion is only offered when
 * every step it needs is actually available — a workflow that opens and then
 * says "you need to connect something first" is worse than one that was never
 * offered, because it has already cost the user a decision and a click.
 * `explain` therefore always returns why a workflow is or is not runnable.
 */

/** What a workflow needs before it can run. */
export const REQUIREMENT_LABELS = Object.freeze({
  model: "a connected model",
  browser: "the connected browser",
  cli: "a coding CLI",
  files: "a workspace folder",
  mcp: "an MCP server",
});

/** Selected labels alone are never connection evidence. */
function workflowAvailabilityUnchecked({ route = {}, selectedRuntime = "", evidence = {}, tools = [], workspacePath = "" } = {}) {
  const runtime = evidence?.runtimeStatus?.[selectedRuntime || route.runtimeId || route.runtime];
  const runtimeReady = runtime?.available === true && runtime?.credentialPresent === true;
  const rows = Array.isArray(tools) ? tools : [];
  return {
    model: Boolean(route.provider && route.model && runtimeReady),
    cli: runtimeReady,
    files: Boolean(workspacePath),
    browser: rows.some(row => row?.toolId === "tool.playwright" && row?.agentReady === true),
    mcp: rows.some(row => String(row?.toolId || "").startsWith("mcp.") && row?.agentReady === true),
  };
}

/**
 * Catalogue. Kept as data so a workflow can be added without touching logic,
 * and so the sidebar and the suggestion engine read from one list.
 */
export const WORKFLOWS = Object.freeze([
  Object.freeze({
    id: "research-brief",
    name: "Research a topic",
    summary: "Search, read the good sources, and write a brief with citations.",
    goals: ["research", "writing"],
    requires: ["model"],
    steps: ["Search", "Read and filter", "Draft", "Cite and check"],
  }),
  Object.freeze({
    id: "fix-failing-test",
    name: "Fix a failing test",
    summary: "Reproduce, find the cause, change the code, and prove it passes.",
    goals: ["software"],
    requires: ["model", "files"],
    steps: ["Reproduce", "Locate", "Change", "Re-run"],
  }),
  Object.freeze({
    id: "review-changes",
    name: "Review my changes",
    summary: "Read the diff, flag real problems, and skip the noise.",
    goals: ["software"],
    requires: ["model", "files"],
    steps: ["Read the diff", "Check the risky parts", "Report"],
  }),
  Object.freeze({
    id: "watch-a-run",
    name: "Watch a long run",
    summary: "Check on something running elsewhere and tell you only when it matters.",
    goals: ["automation", "compute"],
    requires: ["model", "browser"],
    steps: ["Open the console", "Read the state", "Report or wait"],
  }),
  Object.freeze({
    id: "document-this",
    name: "Document what changed",
    summary: "Turn a set of changes into something a person can read.",
    goals: ["writing", "software"],
    requires: ["model", "files"],
    steps: ["Collect changes", "Group by intent", "Write"],
  }),
  Object.freeze({
    id: "extract-from-documents",
    name: "Pull data out of documents",
    summary: "Read a pile of files and produce one table.",
    goals: ["data", "research"],
    requires: ["model", "files"],
    steps: ["Read each file", "Extract fields", "Assemble a table"],
  }),
]);

/**
 * Explain whether a workflow can run right now.
 *
 * @param {object} workflow
 * @param {{model?: boolean, browser?: boolean, cli?: boolean, files?: boolean, mcp?: boolean}} available
 */
function explainUnchecked(workflow, available = {}) {
  const missing = (workflow?.requires || []).filter((key) => !available[key]);
  if (missing.length === 0) {
    return { runnable: true, missing: [], reason: "Prerequisites detected. The runtime checks the connection at launch." };
  }
  const names = missing.map((key) => REQUIREMENT_LABELS[key] || key);
  const listed = names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}` : names[0];
  return {
    runnable: false,
    missing,
    reason: `Needs ${listed}.`,
  };
}

/**
 * Suggest workflows for the user's goals.
 *
 * Only runnable workflows are suggested — see the module note. Unrunnable ones
 * are returned separately so a settings surface can still show them with the
 * honest reason, rather than them silently not existing.
 */
export function suggestWorkflows(goals = [], available = {}, { limit = 3 } = {}) {
  const wanted = new Set((Array.isArray(goals) ? goals : []).map((goal) => String(goal).toLowerCase()));

  const scored = WORKFLOWS.map((workflow) => {
    const overlap = workflow.goals.filter((goal) => wanted.has(goal)).length;
    return { workflow, overlap, ...explain(workflow, available) };
  }).filter((row) => row.overlap > 0);

  scored.sort((a, b) => b.overlap - a.overlap || a.workflow.name.localeCompare(b.workflow.name));

  return {
    suggested: scored.filter((row) => row.runnable).slice(0, limit).map(present),
    blocked: scored.filter((row) => !row.runnable).map(present),
  };
}

function present(row) {
  return {
    id: row.workflow.id,
    name: row.workflow.name,
    summary: row.workflow.summary,
    steps: row.workflow.steps,
    runnable: row.runnable,
    reason: row.reason,
    missing: row.missing,
  };
}

/** Everything, with its current runnability — for the Workflows surface. */
function listWorkflowsUnchecked(available = {}) {
  return WORKFLOWS.map((workflow) => present({ workflow, ...explain(workflow, available) }));
}

export function workflowAvailability(...args) {
  const before = frontendContractBefore("workflow.availability", args);
  return checkedFrontendAction("workflow.availability", args, workflowAvailabilityUnchecked(...args), before);
}

export function explain(...args) {
  const before = frontendContractBefore("workflow.explain", args);
  return checkedFrontendAction("workflow.explain", args, explainUnchecked(...args), before);
}

export function listWorkflows(...args) {
  const before = frontendContractBefore("workflow.list", args);
  return checkedFrontendAction("workflow.list", args, listWorkflowsUnchecked(...args), before);
}
