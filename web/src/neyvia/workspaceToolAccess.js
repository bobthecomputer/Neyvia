import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
export const WORKSPACE_PERMISSION_MODES = Object.freeze([
  "read-only",
  "workspace",
  "full-access",
]);

export const WORKSPACE_PERMISSION_STORAGE_KEY = "fluxio.chat.workspacePermissionModes";

function normalizeWorkspacePermissionModeUnchecked(value, fallback = "read-only") {
  const normalized = String(value || "").trim().toLowerCase();
  if (WORKSPACE_PERMISSION_MODES.includes(normalized)) return normalized;
  if (normalized === "readonly" || normalized === "read_only") return "read-only";
  if (normalized === "workspace-tools" || normalized === "workspace_tools") return "workspace";
  if (normalized === "full" || normalized === "full_access") return "full-access";
  if (value === true) return "workspace";
  return WORKSPACE_PERMISSION_MODES.includes(fallback) ? fallback : "read-only";
}

function workspacePermissionAllowsToolsUnchecked(value) {
  return normalizeWorkspacePermissionMode(value) !== "read-only";
}

function supportsNativeWorkspacePermissionModesUnchecked(runtime) {
  return ["neyvia-agent", "neyvia", "own", "codex", "claude-code", "hermes"].includes(String(runtime || "").trim().toLowerCase());
}

function buildWorkspacePermissionScopeUnchecked(workspaceId, workspacePath, conversationId) {
  return JSON.stringify([
    String(workspaceId || "").trim(),
    String(workspacePath || "").trim(),
    String(conversationId || "").trim(),
  ]);
}

function workspacePermissionGrantForScopeUnchecked(grant, scope, fallback = "full-access") {
  const normalizedGrant = grant && typeof grant === "object" ? grant : {};
  return normalizedGrant.scope === scope
    ? normalizeWorkspacePermissionMode(normalizedGrant.permissionMode, fallback)
    : normalizeWorkspacePermissionMode(fallback, "full-access");
}

function readWorkspacePermissionModesUnchecked(storage) {
  try {
    const parsed = JSON.parse(storage?.getItem(WORKSPACE_PERMISSION_STORAGE_KEY) || "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return Object.fromEntries(Object.entries(parsed)
      .filter(([scope]) => typeof scope === "string" && scope.length > 0)
      .map(([scope, mode]) => [scope, normalizeWorkspacePermissionMode(mode)]));
  } catch {
    return {};
  }
}

function writeWorkspacePermissionModeUnchecked(storage, scope, mode) {
  if (!storage || typeof scope !== "string" || !scope) return false;
  const normalizedMode = normalizeWorkspacePermissionMode(mode, "full-access");
  const saved = readWorkspacePermissionModes(storage);
  saved[scope] = normalizedMode;
  try {
    storage.setItem(WORKSPACE_PERMISSION_STORAGE_KEY, JSON.stringify(saved));
    return true;
  } catch {
    return false;
  }
}

function workspacePermissionModeForScopeUnchecked(storage, scope, fallback = "full-access") {
  const saved = readWorkspacePermissionModes(storage);
  return Object.hasOwn(saved, scope)
    ? saved[scope]
    : normalizeWorkspacePermissionMode(fallback, "full-access");
}

function transferDraftWorkspacePermissionModeUnchecked(storage, previousScope, nextScope) {
  if (!storage || !previousScope || !nextScope || previousScope === nextScope) return false;
  let previousIdentity;
  let nextIdentity;
  try {
    previousIdentity = JSON.parse(previousScope);
    nextIdentity = JSON.parse(nextScope);
  } catch {
    return false;
  }
  if (!Array.isArray(previousIdentity) || !Array.isArray(nextIdentity) ||
      previousIdentity.length !== 3 || nextIdentity.length !== 3 ||
      previousIdentity[0] !== nextIdentity[0] || previousIdentity[1] !== nextIdentity[1] ||
      !["new-chat", "mission-draft"].includes(previousIdentity[2]) ||
      !nextIdentity[2] || ["new-chat", "mission-draft"].includes(nextIdentity[2])) return false;
  const saved = readWorkspacePermissionModes(storage);
  if (!Object.hasOwn(saved, previousScope) || Object.hasOwn(saved, nextScope)) return false;
  saved[nextScope] = saved[previousScope];
  try {
    storage.setItem(WORKSPACE_PERMISSION_STORAGE_KEY, JSON.stringify(saved));
    return true;
  } catch {
    return false;
  }
}

export function normalizeWorkspacePermissionMode(...args) {
  const before = frontendContractBefore("permission.normalize", args);
  return checkedFrontendAction("permission.normalize", args, normalizeWorkspacePermissionModeUnchecked(...args), before);
}

export function workspacePermissionAllowsTools(...args) {
  const before = frontendContractBefore("permission.tools", args);
  return checkedFrontendAction("permission.tools", args, workspacePermissionAllowsToolsUnchecked(...args), before);
}

export function supportsNativeWorkspacePermissionModes(...args) {
  const before = frontendContractBefore("permission.runtime", args);
  return checkedFrontendAction("permission.runtime", args, supportsNativeWorkspacePermissionModesUnchecked(...args), before);
}

export function buildWorkspacePermissionScope(...args) {
  const before = frontendContractBefore("permission.scope", args);
  return checkedFrontendAction("permission.scope", args, buildWorkspacePermissionScopeUnchecked(...args), before);
}

export function workspacePermissionGrantForScope(...args) {
  const before = frontendContractBefore("permission.grant", args);
  return checkedFrontendAction("permission.grant", args, workspacePermissionGrantForScopeUnchecked(...args), before);
}

export function readWorkspacePermissionModes(...args) {
  const before = frontendContractBefore("permission.read", args);
  return checkedFrontendAction("permission.read", args, readWorkspacePermissionModesUnchecked(...args), before);
}

export function writeWorkspacePermissionMode(...args) {
  const before = frontendContractBefore("permission.write", args);
  return checkedFrontendAction("permission.write", args, writeWorkspacePermissionModeUnchecked(...args), before);
}

export function workspacePermissionModeForScope(...args) {
  const before = frontendContractBefore("permission.get", args);
  return checkedFrontendAction("permission.get", args, workspacePermissionModeForScopeUnchecked(...args), before);
}

export function transferDraftWorkspacePermissionMode(...args) {
  const before = frontendContractBefore("permission.transfer", args);
  return checkedFrontendAction("permission.transfer", args, transferDraftWorkspacePermissionModeUnchecked(...args), before);
}
