import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
/**
 * Pure helpers for the LibreOffice / Pandoc operator workspace.
 * Never invents availability, artifacts, verification, or lineage —
 * only shapes backend-returned tool-suite payloads for display.
 */

export const OFFICE_SUITE_TOOL_IDS = Object.freeze([
  "tool.libreoffice",
  "tool.pandoc",
]);

export const OFFICE_SUITE_DEFAULT_TOOL_ID = "tool.libreoffice";

/** Primary operator fields for common Office workflows; schema extras stay advanced. */
export const OFFICE_COMMON_FIELDS_BY_OPERATION = Object.freeze({
  "office.version": Object.freeze([]),
  "office.convert": Object.freeze(["path", "outputFormat", "outputPath"]),
  "office.render-pdf": Object.freeze(["path", "outputPath"]),
  "document.list-formats": Object.freeze([]),
  "document.inspect-ast": Object.freeze(["path", "inputFormat"]),
  "document.convert": Object.freeze([
    "path",
    "outputFormat",
    "outputPath",
    "inputFormat",
  ]),
});

/** Friendly presets for Pandoc convert when the lock schema leaves outputFormat open. */
export const OFFICE_PANDOC_COMMON_OUTPUT_FORMATS = Object.freeze([
  "docx",
  "odt",
  "html",
  "markdown",
  "plain",
  "rst",
  "epub",
  "latex",
]);

const ARTIFACT_FIELDS = Object.freeze([
  "outputPath",
  "sha256",
  "bytes",
  "sourcePath",
  "mediaType",
  "engine",
]);

function asList(value) {
  return Array.isArray(value) ? value : [];
}

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : null;
}

function text(value, fallback = "") {
  const raw = String(value ?? "").trim();
  return raw || fallback;
}

/**
 * Classify a tool-suite describe / execute outcome for the operator strip.
 * @returns {"unavailable"|"available"|"invalid"|"verified"|"completed"|"backend-error"|"approval"|"denied"|"idle"}
 */
function classifyOfficeSuiteOutcomeUnchecked(payload = {}, { kind = "execute" } = {}) {
  if (payload == null) return "unavailable";
  if (payload instanceof Error) return "backend-error";

  const status = text(payload.status || payload.error || "").toLowerCase();
  const ok = payload.ok === true;

  if (kind === "describe") {
    if (payload.connectionState === "unavailable" || payload.unavailable === true) {
      return "unavailable";
    }
    if (payload.agentReady === true) return "available";
    if (status.includes("error") || payload.error) return "backend-error";
    if (payload.toolId || payload.state) return "unavailable";
    return "unavailable";
  }

  if (status === "invalid_arguments" || status === "invalid") return "invalid";
  if (status === "permission_denied" || status === "denied") return "denied";
  if (status === "approval_required") return "approval";
  if (
    status === "tool_not_ready" ||
    status === "adapter_required" ||
    status === "unavailable"
  ) {
    return "unavailable";
  }
  if (ok && (status === "completed" || status === "" || status === "ok")) {
    const verification = asObject(payload.result)?.verification || asObject(payload.verification);
    const verificationStatus = text(verification?.status).toLowerCase();
    if (verificationStatus === "failed") {
      return "backend-error";
    }
    if (verificationStatus === "passed" || verificationStatus === "verified") {
      return "verified";
    }
    return "completed";
  }
  if (status === "output_schema_invalid" || status === "failed" || status === "error") {
    return "backend-error";
  }
  if (payload.error || status) return "backend-error";
  return "unavailable";
}

function normalizeOfficeToolDescribeUnchecked(raw = null, { connectionError = null } = {}) {
  if (connectionError) {
    return Object.freeze({
      toolId: "",
      name: "",
      state: "unavailable",
      agentReady: false,
      health: "unavailable",
      selectedVersion: "",
      operations: Object.freeze([]),
      adapters: Object.freeze([]),
      capabilities: Object.freeze([]),
      outcome: "backend-error",
      error: text(connectionError.message || connectionError),
      raw: null,
    });
  }
  if (!raw || typeof raw !== "object") {
    return Object.freeze({
      toolId: "",
      name: "",
      state: "unavailable",
      agentReady: false,
      health: "unavailable",
      selectedVersion: "",
      operations: Object.freeze([]),
      adapters: Object.freeze([]),
      capabilities: Object.freeze([]),
      outcome: "unavailable",
      error: "No describe_tool_suite_command payload returned.",
      raw: null,
    });
  }

  const operations = asList(raw.operations).map(op =>
    Object.freeze({
      operationId: text(op.operationId || op.id),
      name: text(op.name || op.operationId || op.id),
      description: text(op.description),
      inputSchema: asObject(op.inputSchema) || Object.freeze({}),
      outputSchema: asObject(op.outputSchema) || Object.freeze({}),
      verifier: text(op.verifier),
      permissions: Object.freeze(asList(op.permissions).map(String)),
      supportsCancel: op.supportsCancel === true,
      supportsPreview: op.supportsPreview === true,
    }),
  );

  const normalized = {
    toolId: text(raw.toolId || raw.id),
    name: text(raw.name || raw.toolId || raw.id),
    state: text(raw.state, "unknown").toLowerCase(),
    agentReady: raw.agentReady === true,
    health: text(raw.health?.status || raw.health, "unknown").toLowerCase(),
    selectedVersion: text(raw.selectedVersion || raw.version),
    operations: Object.freeze(operations),
    adapters: Object.freeze(asList(raw.adapters).map(String)),
    capabilities: Object.freeze(asList(raw.capabilities).map(String)),
    error: "",
    raw,
  };
  normalized.outcome = classifyOfficeSuiteOutcome(normalized, { kind: "describe" });
  return Object.freeze(normalized);
}

function pickArtifactFields(result) {
  const source = asObject(result) || {};
  const out = {};
  for (const key of ARTIFACT_FIELDS) {
    if (source[key] !== undefined && source[key] !== null && source[key] !== "") {
      out[key] = source[key];
    }
  }
  return out;
}

export function normalizeOfficePermissionSummary(raw = null) {
  const summary = asObject(raw);
  if (!summary) return null;
  const modeledPermissions = asList(summary.modeledPermissions).flatMap(row => {
    const decision = asObject(row);
    return decision ? [Object.freeze({ ...decision })] : [];
  });
  return Object.freeze({
    modeledPermissions: Object.freeze(modeledPermissions),
    allowed: Object.freeze(asList(summary.allowed).map(String)),
    approvalRequired: Object.freeze(
      asList(summary.approvalRequired).map(String),
    ),
    denied: Object.freeze(asList(summary.denied).map(String)),
    canStart:
      typeof summary.canStart === "boolean" ? summary.canStart : null,
    canRunWithoutApproval:
      typeof summary.canRunWithoutApproval === "boolean"
        ? summary.canRunWithoutApproval
        : null,
  });
}

/**
 * Shape an execute_tool_suite_command response for the proof strip.
 * Only surfaces fields the backend actually returned.
 */
function normalizeOfficeExecuteResultUnchecked(raw = null, { connectionError = null, inputs = null } = {}) {
  if (connectionError) {
    return Object.freeze({
      ok: false,
      status: "backend_error",
      outcome: "backend-error",
      summary: text(connectionError.message || connectionError),
      toolId: "",
      operationId: "",
      inputs: asObject(inputs),
      permissionSummary: null,
      artifact: null,
      verification: null,
      lineage: Object.freeze([]),
      telemetry: null,
      toolReceipt: null,
      inputValidation: null,
      outputValidation: null,
      raw: null,
    });
  }

  if (!raw || typeof raw !== "object") {
    return Object.freeze({
      ok: false,
      status: "unavailable",
      outcome: "unavailable",
      summary: "No execute_tool_suite_command payload returned.",
      toolId: "",
      operationId: "",
      inputs: asObject(inputs),
      permissionSummary: null,
      artifact: null,
      verification: null,
      lineage: Object.freeze([]),
      telemetry: null,
      toolReceipt: null,
      inputValidation: null,
      outputValidation: null,
      raw: null,
    });
  }

  const result = asObject(raw.result) || {};
  const permissionSummary = asObject(raw.permissionSummary);
  const artifactReceipt = asObject(raw.artifactReceipt);
  const artifactFields = pickArtifactFields(result);
  const hasArtifact = Object.keys(artifactFields).length > 0;
  const verification = asObject(result.verification) || asObject(raw.verification);
  const relations = asList(artifactReceipt?.relations).map(row =>
    Object.freeze({
      relation: text(row.relation),
      from: text(row.from || row.parentArtifactId || row.sourceArtifactId),
      to: text(row.to || row.childArtifactId || row.targetArtifactId),
      capabilityId: text(row.capabilityId),
      runId: text(row.runId),
    }),
  );
  const artifacts = asList(artifactReceipt?.artifacts).map(row =>
    Object.freeze({
      artifactId: text(row.artifactId || row.id),
      path: text(row.path),
      kind: text(row.kind),
      sha256: text(row.sha256 || row.hash),
      role: text(row.metadata?.role || row.role),
    }),
  );

  const outcome = classifyOfficeSuiteOutcome(raw, { kind: "execute" });

  return Object.freeze({
    ok: raw.ok === true,
    status: text(raw.status, outcome),
    outcome,
    summary: text(raw.summary || result.summary),
    toolId: text(raw.toolId),
    operationId: text(raw.operationId),
    adapterId: text(raw.adapterId),
    capabilityId: text(raw.capabilityId),
    inputs: asObject(inputs) || asObject(raw.arguments) || null,
    permissionSummary: normalizeOfficePermissionSummary(permissionSummary),
    artifact: hasArtifact
      ? Object.freeze({
          ...artifactFields,
          registeredCount: artifacts.length,
        })
      : null,
    verification: verification ? Object.freeze({ ...verification }) : null,
    lineage: Object.freeze(relations),
    registeredArtifacts: Object.freeze(artifacts),
    telemetry: asObject(raw.telemetry),
    toolReceipt: asObject(raw.toolReceipt),
    inputValidation: asObject(raw.inputValidation),
    outputValidation: asObject(raw.outputValidation),
    raw,
  });
}

/** Build execute payload — workspace paths only; no shell or binary shortcuts. */
function buildOfficeSuiteExecutePayloadUnchecked({
  toolId,
  operationId,
  arguments: args = {},
  approvedPermissions = [],
  permissionMode = "workspace_safe",
  capabilityId = "",
} = {}) {
  const payload = {
    toolId: text(toolId),
    operationId: text(operationId),
    permissionMode: text(permissionMode, "workspace_safe"),
    arguments: { ...(asObject(args) || {}) },
  };
  if (approvedPermissions?.length) {
    payload.approvedPermissions = [...approvedPermissions];
  }
  if (capabilityId) {
    payload.capabilityId = text(capabilityId);
  }
  return payload;
}

export function defaultArgumentsForOperation(operation = null) {
  const schema = asObject(operation?.inputSchema) || {};
  const properties = asObject(schema.properties) || {};
  const defaults = {};
  for (const [key, spec] of Object.entries(properties)) {
    if (key === "operation") continue;
    const detail = asObject(spec) || {};
    if (detail.const !== undefined) {
      defaults[key] = detail.const;
      continue;
    }
    if (detail.default !== undefined) {
      defaults[key] = detail.default;
      continue;
    }
    if (detail.type === "boolean") {
      defaults[key] = false;
      continue;
    }
    if (detail.type === "integer" || detail.type === "number") {
      continue;
    }
    if (detail.type === "array") {
      defaults[key] = [];
      continue;
    }
    defaults[key] = "";
  }
  return defaults;
}

/**
 * Split operation schema keys into common operator fields vs advanced extras.
 * Unknown operations keep every key in common so nothing is hidden by accident.
 */
export function partitionOfficeFormFields(operation = null) {
  const keys = Object.keys(asObject(operation?.inputSchema?.properties) || {}).filter(
    key => key !== "operation",
  );
  const operationId = text(operation?.operationId || operation?.id);
  if (!Object.prototype.hasOwnProperty.call(OFFICE_COMMON_FIELDS_BY_OPERATION, operationId)) {
    return Object.freeze({
      common: Object.freeze([...keys]),
      advanced: Object.freeze([]),
    });
  }
  const preferred = OFFICE_COMMON_FIELDS_BY_OPERATION[operationId];
  const common = preferred.filter(key => keys.includes(key));
  const advanced = keys.filter(key => !common.includes(key));
  return Object.freeze({
    common: Object.freeze(common),
    advanced: Object.freeze(advanced),
  });
}

export function officeOutputFormatChoices(operation = null) {
  const schema = asObject(
    asObject(operation?.inputSchema)?.properties?.outputFormat,
  );
  if (Array.isArray(schema?.enum) && schema.enum.length) {
    return schema.enum.map(String);
  }
  const operationId = text(operation?.operationId || operation?.id);
  if (operationId === "document.convert") {
    return [...OFFICE_PANDOC_COMMON_OUTPUT_FORMATS];
  }
  return [];
}

export function officeSuiteOutcomeLabel(outcome) {
  switch (outcome) {
    case "verified":
      return "Verified";
    case "completed":
      return "Completed · unverified";
    case "available":
      return "Available";
    case "invalid":
      return "Invalid inputs";
    case "unavailable":
      return "Unavailable";
    case "approval":
      return "Approval required";
    case "denied":
      return "Permission denied";
    case "backend-error":
      return "Backend error";
    default:
      return "Idle";
  }
}

export function classifyOfficeSuiteOutcome(...args) {
  const before = frontendContractBefore("office.classify", args);
  return checkedFrontendAction("office.classify", args, classifyOfficeSuiteOutcomeUnchecked(...args), before);
}

export function normalizeOfficeToolDescribe(...args) {
  const before = frontendContractBefore("office.describe", args);
  return checkedFrontendAction("office.describe", args, normalizeOfficeToolDescribeUnchecked(...args), before);
}

export function normalizeOfficeExecuteResult(...args) {
  const before = frontendContractBefore("office.execute", args);
  return checkedFrontendAction("office.execute", args, normalizeOfficeExecuteResultUnchecked(...args), before);
}

export function buildOfficeSuiteExecutePayload(...args) {
  const before = frontendContractBefore("office.payload", args);
  return checkedFrontendAction("office.payload", args, buildOfficeSuiteExecutePayloadUnchecked(...args), before);
}
