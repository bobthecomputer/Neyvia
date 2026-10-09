import { checkPresentationAction } from "./neyviaPresentationContracts.js";
import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
export const NEYVIA_CHAT_STARTERS = Object.freeze([
  Object.freeze({ id: "explain", title: "Explain a concept", detail: "Get a clear, useful explanation", prompt: "Explain this concept clearly, with a practical example: " }),
  Object.freeze({ id: "code", title: "Write or refactor code", detail: "Improve behavior, structure, or clarity", prompt: "Help me write or refactor this code: " }),
  Object.freeze({ id: "question", title: "Answer a technical question", detail: "Reason through a concrete problem", prompt: "Answer this technical question and explain the key tradeoffs: " }),
  Object.freeze({ id: "document", title: "Summarize a document", detail: "Extract decisions and next actions", prompt: "Summarize this document into key points, decisions, and next actions: " }),
  Object.freeze({ id: "logs", title: "Analyze data or logs", detail: "Find patterns and likely causes", prompt: "Analyze this data or these logs. Identify the strongest signal and likely cause: " }),
  Object.freeze({ id: "ideas", title: "Brainstorm ideas", detail: "Explore focused possibilities", prompt: "Brainstorm several strong approaches for this goal, then recommend one: " }),
]);

export const NEYVIA_ORCHESTRATION_STARTERS = Object.freeze([
  Object.freeze({ id: "codebase", title: "Analyze a codebase", detail: "Map structure, dependencies, and risks", prompt: "Analyze this codebase, map the important dependencies, and identify the highest-risk gaps." }),
  Object.freeze({ id: "feature", title: "Build a feature", detail: "Plan, implement, and validate", prompt: "Build this feature from requirements through verified implementation: " }),
  Object.freeze({ id: "investigate", title: "Investigate an issue", detail: "Find the root cause and repair it", prompt: "Investigate this issue, prove the root cause, implement the repair, and verify the user path: " }),
  Object.freeze({ id: "system", title: "Document a system", detail: "Produce an evidence-backed system map", prompt: "Inspect and document this system, including architecture, data flow, operational risks, and recovery steps." }),
]);

export const NEYVIA_DEFAULT_ORCHESTRATION_ROLES = Object.freeze(["planner", "executor", "verifier"]);

const ROLE_META = Object.freeze({
  planner: Object.freeze({ label: "Planner", detail: "Breaks the goal into a bounded plan.", tone: "plan" }),
  executor: Object.freeze({ label: "Executor", detail: "Carries out the work using tools and code.", tone: "execute" }),
  verifier: Object.freeze({ label: "Verifier", detail: "Challenges claims and validates the result.", tone: "verify" }),
  backend: Object.freeze({ label: "Backend specialist", detail: "Handles services, storage, and data contracts.", tone: "backend" }),
  frontend: Object.freeze({ label: "Frontend specialist", detail: "Handles interface behavior and visual proof.", tone: "frontend" }),
  operator: Object.freeze({ label: "Operator", detail: "Coordinates an authorized specialist mission.", tone: "operator" }),
  attacker: Object.freeze({ label: "Attacker", detail: "Runs bounded offensive probes in the approved scope.", tone: "attacker" }),
  defender: Object.freeze({ label: "Defender", detail: "Hardens the system and adds detection.", tone: "defender" }),
  auditor: Object.freeze({ label: "Auditor", detail: "Reviews evidence, controls, and compliance.", tone: "auditor" }),
});

function neyviaOrchestrationRoleMetaUnchecked(role) {
  const normalized = String(role || "").trim().toLowerCase();
  if (ROLE_META[normalized]) return ROLE_META[normalized];
  const label = normalized
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map(value => value.charAt(0).toUpperCase() + value.slice(1))
    .join(" ") || "Specialist";
  return Object.freeze({ label, detail: "Uses the configured route for this specialist role.", tone: "specialist" });
}

function normalizeNeyviaOrchestrationRoleIdsUnchecked(roles = []) {
  const requested = Array.isArray(roles) ? roles : [];
  return [...new Set([
    ...NEYVIA_DEFAULT_ORCHESTRATION_ROLES,
    ...requested.map(role => String(role || "").trim().toLowerCase()).filter(Boolean),
  ])];
}

function isNeyviaDefaultOrchestrationRoleUnchecked(role) {
  return NEYVIA_DEFAULT_ORCHESTRATION_ROLES.includes(String(role || "").trim().toLowerCase());
}

export function normalizeNeyviaOrchestrationRoleIds(...args) {
  const before = frontendContractBefore("roles.normalize", args);
  return checkedFrontendAction("roles.normalize", args, normalizeNeyviaOrchestrationRoleIdsUnchecked(...args), before);
}

export function isNeyviaDefaultOrchestrationRole(...args) {
  const before = frontendContractBefore("roles.default", args);
  return checkedFrontendAction("roles.default", args, isNeyviaDefaultOrchestrationRoleUnchecked(...args), before);
}

export function neyviaOrchestrationRoleMeta(...args) {
  const before = frontendContractBefore("roles.meta", args);
  return checkedFrontendAction("roles.meta", args, neyviaOrchestrationRoleMetaUnchecked(...args), before);
}

export function modeStarterCatalog() { return checkPresentationAction("starters.catalog", [], { chat: NEYVIA_CHAT_STARTERS, orchestration: NEYVIA_ORCHESTRATION_STARTERS }); }
modeStarterCatalog();
