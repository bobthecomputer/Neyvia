import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
export const MESH_UNAVAILABLE = "Unavailable";

export function asList(value) {
  return Array.isArray(value) ? value : [];
}

function formatValueUnchecked(value, unavailable = MESH_UNAVAILABLE) {
  if (value === null || value === undefined) return unavailable;
  if (typeof value === "string" && !value.trim()) return unavailable;
  return String(value);
}

function formatBooleanStatusUnchecked(
  value,
  { trueLabel = "Enabled", falseLabel = "Disabled", unavailableLabel = MESH_UNAVAILABLE } = {},
) {
  if (value === true) return trueLabel;
  if (value === false) return falseLabel;
  return unavailableLabel;
}

function formatCountUnchecked(value, unavailable = MESH_UNAVAILABLE) {
  if (value === null || value === undefined || value === "") return unavailable;
  const count = Number(value);
  return Number.isFinite(count) ? String(count) : unavailable;
}

function formatDurationUnchecked(value) {
  if (value === null || value === undefined || value === "") return MESH_UNAVAILABLE;
  const duration = Number(value);
  return Number.isFinite(duration) ? `${duration} ms` : MESH_UNAVAILABLE;
}

function formatBytesUnchecked(value) {
  if (value === null || value === undefined || value === "") return MESH_UNAVAILABLE;
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return MESH_UNAVAILABLE;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MiB`;
}

function shortHashUnchecked(value) {
  const text = formatValue(value);
  if (text === MESH_UNAVAILABLE || text.length <= 16) return text;
  return `${text.slice(0, 8)}…${text.slice(-6)}`;
}

export function routeTone(routeState) {
  const normalized = String(routeState || "").trim().toLowerCase();
  if (normalized === "direct") return "good";
  if (normalized === "relay" || normalized === "peer-relay") return "warn";
  if (normalized === "offline") return "failed";
  return "neutral";
}

export function settledValue(result) {
  return result?.status === "fulfilled" ? result.value : null;
}

export function settledError(result, fallback) {
  if (result?.status !== "rejected") return "";
  const message = result.reason?.message || result.reason;
  return formatValue(message, fallback);
}

function hasMeshSnapshotUnchecked(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return false;
  return Object.values(snapshot).some(value => value !== null && value !== undefined);
}

export function formatValue(...args) {
  const before = frontendContractBefore("mesh.value", args);
  return checkedFrontendAction("mesh.value", args, formatValueUnchecked(...args), before);
}

export function formatBooleanStatus(...args) {
  const before = frontendContractBefore("mesh.boolean", args);
  return checkedFrontendAction("mesh.boolean", args, formatBooleanStatusUnchecked(...args), before);
}

export function formatCount(...args) {
  const before = frontendContractBefore("mesh.count", args);
  return checkedFrontendAction("mesh.count", args, formatCountUnchecked(...args), before);
}

export function formatDuration(...args) {
  const before = frontendContractBefore("mesh.duration", args);
  return checkedFrontendAction("mesh.duration", args, formatDurationUnchecked(...args), before);
}

export function formatBytes(...args) {
  const before = frontendContractBefore("mesh.bytes", args);
  return checkedFrontendAction("mesh.bytes", args, formatBytesUnchecked(...args), before);
}

export function shortHash(...args) {
  const before = frontendContractBefore("mesh.hash", args);
  return checkedFrontendAction("mesh.hash", args, shortHashUnchecked(...args), before);
}

export function hasMeshSnapshot(...args) {
  const before = frontendContractBefore("mesh.snapshot", args);
  return checkedFrontendAction("mesh.snapshot", args, hasMeshSnapshotUnchecked(...args), before);
}
