import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
export const APP_FACTORY_COMMANDS = Object.freeze({
  catalog: "get_app_factory_catalog_command",
  getJob: "get_app_factory_job_command",
  create: "create_app_factory_job_command",
  createFromCapability: "create_app_factory_from_materialization_command",
  resume: "resume_app_factory_job_command",
  buildNative: "start_app_factory_native_build_command",
  testJob: "test_app_factory_job_command",
  installNative: "install_app_factory_job_command",
  rollbackNative: "rollback_app_factory_install_command",
  importOutcomes: "import_capability_run_bundle_command",
});

export const APP_FACTORY_STAGE_ORDER = Object.freeze([
  "brief",
  "scaffold",
  "assemble",
  "verify",
  "register",
]);

function appFactoryProgressUnchecked(job) {
  const stages = Array.isArray(job?.stages) ? job.stages : [];
  const completed = stages.filter(stage => stage?.state === "completed").length;
  return {
    completed,
    total: APP_FACTORY_STAGE_ORDER.length,
    percent: Math.round((completed / APP_FACTORY_STAGE_ORDER.length) * 100),
  };
}

function appFactoryJobToneUnchecked(job) {
  const nativeState = String(job?.nativeBuild?.state || "");
  if (nativeState === "failed" || ["failed", "needs_attention"].includes(job?.status)) {
    return "danger";
  }
  if (nativeState === "queued" || nativeState === "running" || job?.status === "building") {
    return "working";
  }
  if (job?.verification?.state === "passed" && job?.registration?.state === "draft-ready") {
    return "ready";
  }
  return "neutral";
}

function normalizeAppFactoryCatalogUnchecked(value = {}) {
  const jobs = Array.isArray(value?.jobs) ? value.jobs.filter(Boolean) : [];
  const targets = Array.isArray(value?.targets) ? value.targets.filter(Boolean) : [];
  const capabilityHandoffs = Array.isArray(value?.capabilityHandoffs)
    ? value.capabilityHandoffs.filter(Boolean)
    : [];
  return {
    ...value,
    jobs,
    targets,
    capabilityHandoffs,
    pipeline: Array.isArray(value?.pipeline) ? value.pipeline.filter(Boolean) : [],
    summary: {
      total: Number(value?.summary?.total || jobs.length),
      ready: Number(value?.summary?.ready || 0),
      building: Number(value?.summary?.building || 0),
      needsAttention: Number(value?.summary?.needsAttention || 0),
      capabilityReady: Number(
        value?.summary?.capabilityReady
          ?? capabilityHandoffs.filter(item => item?.state === "review_required").length,
      ),
      capabilityDrafts: Number(
        value?.summary?.capabilityDrafts
          ?? capabilityHandoffs.filter(
            item => ["draft_ready", "draft_maintenance_due"].includes(item?.state),
          ).length,
      ),
      capabilityMaintenanceDue: Number(
        value?.summary?.capabilityMaintenanceDue
          ?? capabilityHandoffs.filter(
            item => [
              "proof_lease_required",
              "maintenance_required",
              "draft_maintenance_due",
            ].includes(item?.state),
          ).length,
      ),
    },
  };
}

function appFactoryCreatePayloadUnchecked(form, root = "") {
  const payload = {
    name: String(form?.name || "").trim(),
    brief: String(form?.brief || "").trim(),
    target: String(form?.target || "desktop").trim(),
    template: String(form?.template || "auto").trim(),
    theme: String(form?.theme || "midnight").trim(),
    directory: String(form?.directory || "").trim(),
  };
  if (String(root || "").trim()) payload.root = String(root).trim();
  return payload;
}

function appFactoryJobPayloadUnchecked(jobId, root = "") {
  const payload = { jobId: String(jobId || "").trim() };
  if (String(root || "").trim()) payload.root = String(root).trim();
  return payload;
}

function appFactoryOutcomeImportPayloadUnchecked(bundle, root = "") {
  if (
    !bundle
    || typeof bundle !== "object"
    || Array.isArray(bundle)
    || bundle.schema !== "neyvia.capability-run-bundle/v2"
    || !String(bundle.appFactoryJobId || "").trim()
    || !Array.isArray(bundle.runs)
    || bundle.runs.length === 0
  ) {
    return null;
  }
  const payload = {
    bundle,
    importedBy: "operator",
  };
  if (String(root || "").trim()) payload.root = String(root).trim();
  return payload;
}

function appFactoryCapabilityPayloadUnchecked(
  handoff,
  form,
  root = "",
  reviewConfirmed = false,
) {
  if (
    handoff?.canCreateApp !== true
    || handoff?.state !== "review_required"
    || !handoff?.materializationId
    || !handoff?.candidateDigest
    || reviewConfirmed !== true
  ) {
    return null;
  }
  const payload = {
    materializationId: String(handoff.materializationId).trim(),
    candidateDigest: String(handoff.candidateDigest).trim(),
    reviewConfirmed: true,
    reviewedBy: "operator",
    name: String(form?.name || "").trim(),
    brief: String(form?.brief || "").trim(),
    target: String(form?.target || "neyvia").trim(),
    theme: String(form?.theme || "midnight").trim(),
    directory: String(form?.directory || "").trim(),
  };
  if (String(root || "").trim()) payload.root = String(root).trim();
  return payload;
}

function appFactoryEligibleHandoffsUnchecked(catalog) {
  return (Array.isArray(catalog?.capabilityHandoffs)
    ? catalog.capabilityHandoffs
    : []
  ).filter(
    item => item?.state === "review_required" && item?.canCreateApp === true,
  );
}

function appFactoryHandoffForJobUnchecked(catalog, job) {
  const handoff = job?.capabilityHandoff;
  if (!handoff?.materializationId) return null;
  return (
    (Array.isArray(catalog?.capabilityHandoffs)
      ? catalog.capabilityHandoffs
      : []
    ).find(
      item => item?.materializationId === handoff.materializationId,
    ) || null
  );
}

function compactFactoryHashUnchecked(value) {
  const hash = String(value || "").trim();
  if (!hash) return "Not recorded";
  return hash.length > 18 ? `${hash.slice(0, 10)}…${hash.slice(-6)}` : hash;
}

export function appFactoryProgress(...args) {
  const before = frontendContractBefore("factory.progress", args);
  return checkedFrontendAction("factory.progress", args, appFactoryProgressUnchecked(...args), before);
}

export function appFactoryJobTone(...args) {
  const before = frontendContractBefore("factory.tone", args);
  return checkedFrontendAction("factory.tone", args, appFactoryJobToneUnchecked(...args), before);
}

export function normalizeAppFactoryCatalog(...args) {
  const before = frontendContractBefore("factory.catalog", args);
  return checkedFrontendAction("factory.catalog", args, normalizeAppFactoryCatalogUnchecked(...args), before);
}

export function appFactoryCreatePayload(...args) {
  const before = frontendContractBefore("factory.create", args);
  return checkedFrontendAction("factory.create", args, appFactoryCreatePayloadUnchecked(...args), before);
}

export function appFactoryJobPayload(...args) {
  const before = frontendContractBefore("factory.job", args);
  return checkedFrontendAction("factory.job", args, appFactoryJobPayloadUnchecked(...args), before);
}

export function appFactoryOutcomeImportPayload(...args) {
  const before = frontendContractBefore("factory.import", args);
  return checkedFrontendAction("factory.import", args, appFactoryOutcomeImportPayloadUnchecked(...args), before);
}

export function appFactoryCapabilityPayload(...args) {
  const before = frontendContractBefore("factory.capability", args);
  return checkedFrontendAction("factory.capability", args, appFactoryCapabilityPayloadUnchecked(...args), before);
}

export function appFactoryEligibleHandoffs(...args) {
  const before = frontendContractBefore("factory.eligible", args);
  return checkedFrontendAction("factory.eligible", args, appFactoryEligibleHandoffsUnchecked(...args), before);
}

export function appFactoryHandoffForJob(...args) {
  const before = frontendContractBefore("factory.handoff", args);
  return checkedFrontendAction("factory.handoff", args, appFactoryHandoffForJobUnchecked(...args), before);
}

export function compactFactoryHash(...args) {
  const before = frontendContractBefore("factory.hash", args);
  return checkedFrontendAction("factory.hash", args, compactFactoryHashUnchecked(...args), before);
}

export function appFactoryCommands() { return checkedFrontendAction("factory.commands", [], APP_FACTORY_COMMANDS); }
appFactoryCommands();
