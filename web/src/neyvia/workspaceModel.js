import { checkedChatAction } from "./neyviaChatContracts.js";
export const WORKSPACE_SURFACES = Object.freeze([
  { id: "home", label: "Home", section: "global" },
  { id: "agent", label: "Chat", section: "workspace" },
  { id: "notebook", label: "Notebook", section: "workspace" },
  { id: "lab", label: "Lab", section: "workspace" },
  { id: "builder", label: "Orchestration", section: "workspace" },
  { id: "workflows", label: "Workflow picker", section: "workspace", hidden: true },
  { id: "library", label: "Library", section: "workspace" },
  { id: "builder-review", label: "Agent Review", section: "workspace", hidden: true },
  { id: "phone", label: "Phone", section: "workspace", hidden: true },
  { id: "harnesses", label: "Harnesses", section: "workspace" },
  { id: "skills", label: "Skills", section: "workspace" },
  { id: "rule-sets", label: "Workflows", section: "workspace" },
  { id: "images", label: "Images", section: "workspace" },
  { id: "app-factory", label: "App Factory", section: "workspace", hidden: true },
  { id: "ios-studio", label: "iOS Studio", section: "workspace", hidden: true },
  { id: "lumaforge", label: "LumaForge", section: "workspace", hidden: true },
  { id: "frameweave", label: "FrameWeave", section: "workspace", hidden: true },
  { id: "citecraft", label: "CiteCraft", section: "workspace", hidden: true },
  { id: "aegis-range", label: "Aegis Range", section: "workspace", hidden: true },
  { id: "cueledger", label: "CueLedger", section: "workspace", hidden: true },
  { id: "browser", label: "Browser", section: "workspace", hidden: true },
  { id: "preview", label: "Preview", section: "workspace", hidden: true },
  { id: "workbench", label: "Workbench", section: "workspace" },
  { id: "settings", label: "Settings", section: "global" },
]);

export const WORKSPACE_SURFACE_IDS = Object.freeze(checkedChatAction("surfaces", [WORKSPACE_SURFACES], WORKSPACE_SURFACES.map(surface => surface.id)));

export const AGENT_STATUS_DEFINITIONS = Object.freeze({
  idle: { label: "Idle", tone: "neutral" },
  queued: { label: "Queued", tone: "neutral" },
  planning: { label: "Planning", tone: "info" },
  running: { label: "Running", tone: "good" },
  needs_approval: { label: "Needs approval", tone: "warn" },
  blocked: { label: "Blocked", tone: "bad" },
  verification_failed: { label: "Verification failed", tone: "bad" },
  completed: { label: "Completed", tone: "good" },
  failed: { label: "Failed", tone: "bad" },
  stopped: { label: "Stopped", tone: "neutral" },
});

export const ROUTE_ROLE_OPTIONS = Object.freeze(["planner", "backend", "frontend", "executor", "verifier"]);

export const MODEL_PROVIDER_OPTIONS = Object.freeze([
  { value: "openai-codex", label: "OpenAI provider (Codex auth)" },
  { value: "kimi-code", label: "Kimi Code account" },
  { value: "claude-code", label: "Claude Code account" },
  { value: "claude-subscription-directsdk-experimental", label: "Claude subscription · Hermes (experimental)" },
  { value: "grok-build", label: "Grok Build account" },
  { value: "minimax", label: "MiniMax" },
  { value: "opencode-go", label: "OpenCodeGo" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "openai", label: "OpenAI API" },
  { value: "anthropic", label: "Anthropic" },
]);

export const MODEL_EFFORT_OPTIONS = Object.freeze([
  { value: "default", label: "Default" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "xhigh", label: "X High" },
  { value: "max", label: "Max" },
  { value: "ultra", label: "Ultra" },
]);

export const EXECUTION_TARGET_OPTIONS = Object.freeze([
  { value: "profile_default", label: "Profile Default" },
  { value: "workspace_root", label: "Workspace Root" },
  { value: "isolated_worktree", label: "Isolated Worktree" },
]);

export const PERMISSION_MODE_OPTIONS = Object.freeze([
  {
    value: "always_ask",
    label: "Always ask",
    tone: "warn",
    description: "Require approval before commands, writes, and external actions.",
  },
  {
    value: "workspace_safe",
    label: "Workspace safe",
    tone: "good",
    description: "Allow low-risk reads and writes inside the selected workspace.",
  },
  {
    value: "review_only",
    label: "Review only",
    tone: "neutral",
    description: "Inspect, plan, and propose changes without mutating files.",
  },
  {
    value: "autonomous_scoped",
    label: "Autonomous scoped",
    tone: "warn",
    description: "Allow broader autonomous work only inside an explicit folder scope.",
  },
]);

function list(value) {
  return Array.isArray(value) ? value : [];
}

function runtimeServiceMatch(service) {
  const haystack = `${service?.serviceId || ""} ${service?.label || ""} ${service?.category || ""}`.toLowerCase();
  return (
    haystack.includes("runtime") ||
    haystack.includes("openclaw") ||
    haystack.includes("hermes") ||
    haystack.includes("wsl") ||
    haystack.includes("uv") ||
    haystack.includes("image tools")
  );
}

export function deriveRuntimeOperations(serviceStudio = {}) {
  const managedServices = list(serviceStudio.services);
  const runtimeServices = managedServices.filter(runtimeServiceMatch);
  const updateServices = managedServices.filter(service => {
    const status = String(service?.status || "").toLowerCase();
    return Boolean(service?.updateAvailable) || status.includes("update");
  });
  const runtimeActions = runtimeServices.flatMap(service =>
    list(service?.actions).map(action => ({
      ...action,
      serviceId: service.serviceId,
      serviceLabel: service.label,
    })),
  );

  return {
    summary: serviceStudio.summary || {},
    services: runtimeServices,
    updates: updateServices,
    actions: runtimeActions,
    autoVerifyCount: runtimeActions.filter(action => action.autoRunVerify).length,
    updateActionCount: runtimeActions.filter(action =>
      String(action.actionId || action.label || "").toLowerCase().includes("update"),
    ).length,
  };
}

export function statusDefinition(status) {
  return AGENT_STATUS_DEFINITIONS[String(status || "").toLowerCase()] || AGENT_STATUS_DEFINITIONS.idle;
}
