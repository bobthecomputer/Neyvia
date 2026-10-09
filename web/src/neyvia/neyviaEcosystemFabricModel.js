import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
const PER_ACTION_PERMISSIONS = new Set(["send", "delete", "unsubscribe"]);

export const COMMUNICATION_ROUTES = Object.freeze([
  { id: "delegated-oauth", label: "Provider connection (OAuth)" },
  { id: "imap-smtp", label: "Mail server (IMAP / SMTP)" },
  { id: "jmap", label: "Mail server (JMAP)" },
  { id: "outlook-bridge", label: "Outlook local bridge" },
  { id: "thunderbird-bridge", label: "Thunderbird local bridge" },
  { id: "file-import", label: "Local EML / MSG import" },
  { id: "forward-ingestion", label: "Forward into Neyvia" },
]);

export const COMMUNICATION_STATES = Object.freeze([
  { id: "not-configured", label: "Not configured" },
  { id: "connected", label: "Connected" },
  { id: "limited", label: "Connected with limits" },
  { id: "approval-required", label: "Administrator approval required" },
  { id: "blocked-by-organization", label: "Blocked by organization" },
  { id: "credentials-missing", label: "Credentials missing" },
]);

export const PRESENTATION_PROFILES = Object.freeze([
  { id: "implementation", label: "Implementation" },
  { id: "diagnosis", label: "Diagnosis" },
  { id: "research", label: "Research" },
  { id: "writing", label: "Writing" },
  { id: "image-generation", label: "Image generation" },
  { id: "explanation", label: "Explanation" },
]);

function normalizeCommunicationFabricUnchecked(value) {
  const record = value && typeof value === "object" ? value : {};
  return {
    schema: String(record.schema || ""),
    accounts: Array.isArray(record.accounts) ? record.accounts : [],
    imports: Array.isArray(record.imports) ? record.imports : [],
    permissionLadder: Array.isArray(record.permissionLadder) ? record.permissionLadder : [],
  };
}

function communicationStateToneUnchecked(value) {
  const state = String(value || "").trim().toLowerCase();
  if (state === "connected") return "good";
  if (state === "limited" || state === "approval-required" || state === "credentials-missing") {
    return "warning";
  }
  if (state === "blocked-by-organization") return "blocked";
  return "neutral";
}

function buildCommunicationAccountPayloadUnchecked(form = {}) {
  const route = String(form.route || "file-import").trim();
  const permissions = Array.from(
    new Set(
      (Array.isArray(form.permissions) ? form.permissions : ["read", "draft"])
        .map(value => String(value || "").trim().toLowerCase())
        .filter(Boolean),
    ),
  ).sort();
  return {
    label: String(form.label || "Communication account").trim(),
    addressHint: String(form.addressHint || "").trim(),
    organization: String(form.organization || "").trim(),
    route,
    state: String(form.state || "not-configured").trim(),
    limitation: String(form.limitation || "").trim(),
    permissions,
    configuration: {},
  };
}

function permissionApprovalLabelUnchecked(permission) {
  return PER_ACTION_PERMISSIONS.has(String(permission || "").toLowerCase())
    ? "Confirm each action"
    : "Approve for this account";
}

function canInsertPresentationPromptUnchecked(result) {
  return Boolean(
    result &&
      result.requiresExplicitInsert === true &&
      result.automatedLogin === false &&
      result.transcriptHarvesting === false &&
      String(result.compiled || "").trim(),
  );
}

export function normalizeCommunicationFabric(...args) {
  const before = frontendContractBefore("fabric.normalize", args);
  return checkedFrontendAction("fabric.normalize", args, normalizeCommunicationFabricUnchecked(...args), before);
}

export function communicationStateTone(...args) {
  const before = frontendContractBefore("fabric.tone", args);
  return checkedFrontendAction("fabric.tone", args, communicationStateToneUnchecked(...args), before);
}

export function buildCommunicationAccountPayload(...args) {
  const before = frontendContractBefore("fabric.account", args);
  return checkedFrontendAction("fabric.account", args, buildCommunicationAccountPayloadUnchecked(...args), before);
}

export function permissionApprovalLabel(...args) {
  const before = frontendContractBefore("fabric.approval", args);
  return checkedFrontendAction("fabric.approval", args, permissionApprovalLabelUnchecked(...args), before);
}

export function canInsertPresentationPrompt(...args) {
  const before = frontendContractBefore("fabric.insert", args);
  return checkedFrontendAction("fabric.insert", args, canInsertPresentationPromptUnchecked(...args), before);
}
