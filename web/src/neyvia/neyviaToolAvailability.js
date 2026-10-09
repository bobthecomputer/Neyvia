/**
 * Live managed-suite readiness for Neyvia Chat/Library tiles.
 * Never invents agentReady — values come from get_capability_os_snapshot_command / describe_tool_suite_command.
 */

/** Wave-1 winners from the claim audit / master plan — deepen these before catalog width. */
export const NEYVIA_WAVE1_TOOL_IDS = Object.freeze([
  "tool.pandoc",
  "tool.libreoffice",
  "tool.poppler",
  "tool.tesseract",
  "tool.playwright",
]);

/** Structured computer-use progressive ids — backend-strong, UI console still thin. */
export const NEYVIA_CU_TOOL_IDS = Object.freeze([
  "ui.observe",
  "ui.do",
  "ui.ls",
  "ui.find",
  "ui.diff",
  "ui.see",
  "computer_use.verify",
  "cu.twin.run",
]);

export const NEYVIA_AVAILABILITY_FILTERS = Object.freeze([
  Object.freeze({ id: "ready", label: "Agent-ready" }),
  Object.freeze({ id: "wave1", label: "Wave-1" }),
  Object.freeze({ id: "upcoming", label: "Upcoming" }),
  Object.freeze({ id: "all", label: "All catalog" }),
]);

function asList(value) {
  return Array.isArray(value) ? value : [];
}

async function callNeyvia(command, payload = {}) {
  const response = await fetch("/api/backend", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, payload }),
  });
  const result = await response.json();
  if (!response.ok || !result?.ok) throw new Error(result?.error || `${command} failed`);
  return result.data;
}

/**
 * @typedef {Object} NeyviaToolAvailability
 * @property {string} toolId
 * @property {string} state
 * @property {boolean} agentReady
 * @property {number|null} wave
 * @property {number} operationCount
 * @property {string} health
 * @property {string[]} capabilities
 * @property {string} name
 * @property {"agent_ready"|"operator_surface"|"wave1_candidate"|"installed"|"verified"|"planned"|"blocked"|"unknown"} tier
 * @property {string} badge
 */

export function classifyNeyviaToolTier(row = {}) {
  const toolId = String(row.toolId || row.id || "").trim();
  const state = String(row.state || "").trim().toLowerCase();
  const agentReady = row.agentReady === true;
  const wave = Number.isFinite(Number(row.wave)) ? Number(row.wave) : null;
  if (agentReady) return "agent_ready";
  if (row.operatorSurface === true) return "operator_surface";
  if (state === "blocked") return "blocked";
  if (state === "planned") return "planned";
  if (NEYVIA_WAVE1_TOOL_IDS.includes(toolId) || wave === 1) return "wave1_candidate";
  if (state === "verified") return "verified";
  if (state === "installed") return "installed";
  return "unknown";
}

export function neyviaAvailabilityBadge(tier) {
  switch (tier) {
    case "agent_ready":
      return "Agent-ready";
    case "operator_surface":
      return "Operator surface";
    case "wave1_candidate":
      return "Wave-1 · not agent-ready";
    case "verified":
      return "Verified · ops incomplete";
    case "installed":
      return "Installed · not ready";
    case "planned":
      return "Upcoming";
    case "blocked":
      return "Blocked";
    default:
      return "Catalog only";
  }
}

export function normalizeNeyviaToolAvailability(row = {}) {
  const toolId = String(row.toolId || row.id || "").trim();
  const tier = classifyNeyviaToolTier(row);
  return Object.freeze({
    toolId,
    name: String(row.name || toolId),
    state: String(row.state || "unknown").toLowerCase(),
    agentReady: row.agentReady === true,
    wave: Number.isFinite(Number(row.wave)) ? Number(row.wave) : null,
    operationCount: Number(row.operationCount || asList(row.operations).length || 0),
    health: String(row.health?.status || row.health || "unknown").toLowerCase(),
    capabilities: asList(row.capabilities).map(String),
    operatorSurface: row.operatorSurface === true,
    tier,
    badge: neyviaAvailabilityBadge(tier),
  });
}

/**
 * Load suite readiness from the capability OS snapshot (honest backend truth).
 */
export async function loadNeyviaToolSuiteAvailability() {
  const snapshot = await callNeyvia("get_capability_os_snapshot_command", {});
  const tools = asList(snapshot?.toolSuite?.tools).map(normalizeNeyviaToolAvailability);
  const byId = new Map(tools.map(row => [row.toolId, row]));
  return {
    connectionState: "ready",
    summary: snapshot?.toolSuite?.summary || snapshot?.summary || {},
    tools,
    byId,
    agentReadyCount: tools.filter(row => row.agentReady).length,
    loadedAt: snapshot?.generatedAt || new Date().toISOString(),
  };
}

export function emptyNeyviaToolSuiteAvailability(reason = "unavailable") {
  return {
    connectionState: reason,
    summary: {},
    tools: [],
    byId: new Map(),
    agentReadyCount: 0,
    loadedAt: null,
  };
}

/** Map a chat/library tile id onto a managed suite tool id when possible. */
export function resolveNeyviaSuiteToolId(toolId = "") {
  const id = String(toolId || "").trim();
  if (!id) return "";
  if (id.startsWith("tool.") && !id.startsWith("tool.suite") && !id.startsWith("tool.author")) return id;
  const aliases = {
    pdf: "tool.poppler",
    "document.pdf-analysis": "tool.poppler",
    "document.fast-ocr": "tool.tesseract",
    "document.latex-production": "tool.latex-suite",
    "pdf.extract-text": "tool.poppler",
    "document.convert": "tool.pandoc",
    "office.spreadsheet-analysis": "tool.libreoffice",
    "office.spreadsheet-edit": "tool.libreoffice",
    translate: "tool.argos-translate",
    "writing.translation-alignment": "tool.argos-translate",
    "grammar-correct": "tool.languagetool",
    "incorrect-grammar": "tool.languagetool",
    "writing.editorial-redline": "tool.languagetool",
    "web-capture": "tool.playwright",
    "three-d.blender-scene": "tool.blender",
  };
  return aliases[id] || "";
}

export function resolveTileAvailability(toolId, availability) {
  const suiteId = resolveNeyviaSuiteToolId(toolId) || (String(toolId || "").startsWith("tool.") ? toolId : "");
  const row = suiteId ? availability?.byId?.get(suiteId) : null;
  if (row) return row;
  const id = String(toolId || "");
  const operatorSurface =
    NEYVIA_CU_TOOL_IDS.includes(id) ||
    id.startsWith("ui.") ||
    id.startsWith("cu.") ||
    id.startsWith("computer_use.") ||
    id.startsWith("security.") ||
    id.startsWith("tool.author.") ||
    id.startsWith("mcp.");
  if (operatorSurface) {
    return normalizeNeyviaToolAvailability({
      toolId: id,
      name: id,
      state: "installed",
      agentReady: false,
      operatorSurface: true,
      wave: NEYVIA_CU_TOOL_IDS.includes(id) ? 1 : null,
      operationCount: 0,
      health: { status: "backend_present" },
      capabilities: [],
    });
  }
  return normalizeNeyviaToolAvailability({
    toolId: id,
    name: id,
    state: "planned",
    agentReady: false,
    wave: null,
    operationCount: 0,
    health: { status: "unknown" },
    capabilities: [],
  });
}

export function tileMatchesAvailabilityFilter(toolId, availability, filter = "ready") {
  const row = resolveTileAvailability(toolId, availability);
  if (filter === "all") return true;
  if (filter === "ready") return row.agentReady === true;
  if (filter === "wave1") {
    return row.agentReady || row.tier === "operator_surface" || row.tier === "wave1_candidate" || NEYVIA_WAVE1_TOOL_IDS.includes(row.toolId) || NEYVIA_CU_TOOL_IDS.includes(String(toolId));
  }
  if (filter === "upcoming") {
    return row.tier === "planned" || row.tier === "blocked" || row.tier === "unknown";
  }
  return true;
}

export async function describeNeyviaSuiteTool(toolId) {
  return callNeyvia("describe_tool_suite_command", { toolId });
}

export async function planNeyviaCapability(payload = {}) {
  return callNeyvia("plan_capability_run_command", payload);
}

export async function executeNeyviaCapability(payload = {}) {
  return callNeyvia("execute_capability_command", payload);
}

export async function executeNeyviaSuiteOperation(payload = {}) {
  return callNeyvia("execute_tool_suite_command", payload);
}

export async function describeNeyviaCapability(capabilityId) {
  return callNeyvia("describe_capability_command", { capabilityId });
}

/**
 * Open overlay host panels from NeyviaShell without inventing success.
 */
export function openNeyviaOverlay(panel, detail = {}) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent("neyvia:open-overlay", {
      detail: { panel, ...detail },
    }),
  );
}

export function emitNeyviaPlanContext(planContext) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent("neyvia:plan-context", {
      detail: planContext || null,
    }),
  );
}
