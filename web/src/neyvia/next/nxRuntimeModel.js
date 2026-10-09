import { checkedProofsEModel } from "./nxProofsEContracts.js";
// The Runtime page's rows: the harness catalog (get_harness_catalog_command:
// found, version, readiness, sign-in) joined with the live matrix
// (GET /api/ui/runtime: connected adapter, what it can do, models, owner
// ceilings). The pure join checks its executable manual postcondition.

// Matrix ids (neyvia_runtime.py) -> catalog ids (harness_registry.py).
const CATALOG_ID = { neyvia: "neyvia-agent", kimi: "kimi-code", grok: "grok-build" };
export const POLICY_APPS = new Set(["neyvia", "codex", "claude-code", "opencode"]);
export const CEILINGS = [
  { value: "read-only", label: "Read only" },
  { value: "workspace", label: "Workspace" },
  { value: "full-access", label: "Full access" },
];
const MODES = { native: "Native", connected: "Connected", wrapped: "Wrapped", planned: "Not wired yet" };
const AUTH = {
  "authenticated-live": "Signed in",
  "account-action-required": "Sign-in needed",
  "provider-setup-required": "Provider setup needed",
  "route-setup-required": "Route setup needed",
  "route-dependent": "Uses the chosen model's sign-in",
  "security-scope-required": "Security profile needed",
  "not-installed": "Not installed",
  unverified: "Not checked",
};

function raw_mergeRuntimes(catalog, matrix) {
  const harnesses = Array.isArray(catalog?.harnesses) ? catalog.harnesses : [];
  const live = Array.isArray(matrix?.runtimes) ? matrix.runtimes : [];
  const byCatalog = new Map(live.map(row => [CATALOG_ID[row.id] || row.id, row]));
  const used = new Set();
  const rows = harnesses.map(harness => {
    const runtime = byCatalog.get(harness.harnessId) || null;
    if (runtime) used.add(runtime.id);
    return row(harness, runtime, matrix);
  });
  for (const runtime of live) if (!used.has(runtime.id)) rows.push(row(null, runtime, matrix));
  return rows.sort((a, b) => b.rank - a.rank);
}

function row(harness, runtime, matrix) {
  const id = runtime?.id || harness?.harnessId;
  const installed = Boolean(harness?.installed ?? runtime?.installed);
  const connected = Boolean(runtime?.connected);
  const ready = connected || harness?.readiness === "ready";
  const models = runtime?.options?.models || [];
  const policy = runtime ? matrix?.policies?.[runtime.id] || null : null;
  const authState = harness?.authState || (runtime?.auth?.authenticated || runtime?.auth?.loggedIn ? "authenticated-live" : null);
  return {
    id,
    policyId: runtime && POLICY_APPS.has(runtime.id) ? runtime.id : null,
    name: harness?.label || runtime?.id,
    accent: harness?.accent || "",
    description: harness?.description || "",
    installed,
    detected: Boolean(harness?.detected),
    version: harness?.version || runtime?.version || "",
    mode: runtime ? MODES[runtime.kind] || runtime.kind : "Catalog only",
    starts: Boolean(runtime?.capabilities?.start),
    can: runtime ? ["start", "continue", "interrupt", "approve"].filter(key => runtime.capabilities?.[key]) : [],
    status: connected ? "Ready" : ready ? "Ready" : installed ? "Installed, not usable yet" : "Not installed",
    tone: ready ? "green" : installed ? "caution" : "idle",
    reason: connected ? "" : runtime?.reason || harness?.readinessDetail || "",
    command: harness?.command || "",
    docsUrl: harness?.docsUrl || "",
    defaultModel: harness?.defaultModel || models.find(model => model.default)?.id || "",
    modelPolicy: harness?.modelPolicy || "",
    models,
    modelError: runtime?.optionError || "",
    permissionModes: runtime?.options?.permissionModes || [],
    auth: authState ? AUTH[authState] || authState : runtime?.auth?.status && runtime.auth.status !== "unknown" ? runtime.auth.status : "Not checked",
    authHint: harness?.setupAction && harness.setupAction !== "Ready." ? harness.setupAction : "",
    capabilities: (harness?.capabilities || []).map(item => ({ key: item.key, label: item.label, available: Boolean(item.available) })),
    ceiling: policy?.permissionCeiling || "",
    allowedModels: policy?.allowedModels || [],
    securityOnly: Boolean(harness?.securityOnly),
    rank: (connected ? 8 : 0) + (ready ? 4 : 0) + (installed ? 2 : 0) + (runtime ? 1 : 0),
  };
}

/** The strip's one-line reading: how many runtimes can be used now. */
function raw_runtimeSummary(rows) {
  const ready = rows.filter(row => row.tone === "green").length;
  return { ready, installed: rows.filter(row => row.installed).length, total: rows.length };
}

// Public observers check the executable manual claims on every invocation.
export function mergeRuntimes(...args) { return checkedProofsEModel("runtime.mergeRuntimes", args, raw_mergeRuntimes(...args)); }
export function runtimeSummary(...args) { return checkedProofsEModel("runtime.runtimeSummary", args, raw_runtimeSummary(...args)); }
