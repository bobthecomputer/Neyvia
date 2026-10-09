import { checkPresentationAction } from "./neyviaPresentationContracts.js";
export const MARKETPLACE_UNAVAILABLE = "Not reported";

/** Display the host's range check; missing declarations never imply compatibility. */
export function marketplaceCompatibility(value) {
  const fit = asObject(value);
  const status = asText(fit.status, "unreported");
  return {
    status,
    label: status === "compatible" ? "Works with this Neyvia"
      : asText(fit.message, status === "undeclared" ? "Compatibility not declared" : "Compatibility not reported"),
    detail: asText(fit.message, "The backend has not reported an API compatibility check."),
  };
}

export const MARKETPLACE_BACKEND_COMMANDS = Object.freeze({
  catalog: "get_installed_module_catalog_command",
  toolchain: "get_module_marketplace_toolchain_command",
  install: "install_module_package_command",
  installFromPaths: "install_module_package_from_paths_command",
  reviewPermissions: "review_module_permissions_command",
  trustPublisher: "trust_module_publisher_command",
  activate: "activate_installed_module_command",
  disable: "disable_module_command",
  rollback: "rollback_module_command",
});

const CATALOG_SCHEMA = "neyvia.installed-module-catalog/v1";
const TOOLCHAIN_SCHEMA = "neyvia.marketplace-toolchain-snapshot/v1";

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function asList(value) {
  return Array.isArray(value) ? value : [];
}

function asText(value, fallback = MARKETPLACE_UNAVAILABLE) {
  const text = String(value ?? "").trim();
  return text || fallback;
}

export function marketplaceStateTone(value) {
  const state = String(value || "").toLowerCase();
  if (state === "active") return "good";
  if (state.includes("blocked") || state === "failed" || state === "error") return "blocked";
  if (state === "disabled" || state === "staged" || state === "installed") return "warn";
  return "neutral";
}

export function shortMarketplaceIdentity(value) {
  const text = String(value ?? "").trim();
  if (!text) return MARKETPLACE_UNAVAILABLE;
  if (text.length <= 42) return text;
  return `${text.slice(0, 24)}…${text.slice(-12)}`;
}

function normalizeTool(name, value) {
  const tool = asObject(value);
  const healthy = tool.healthy === true;
  return {
    name,
    healthy,
    status: healthy ? "Verified locally" : "Unavailable or hash mismatch",
    detail: asText(tool.reason || tool.error || tool.path),
  };
}

function normalizeModule(value, toolchain) {
  const item = asObject(value);
  const publisher = asObject(item.publisher);
  const state = asText(item.state, "unknown");
  const securityErrors = asList(item.securityErrors).map(error => asText(error));
  const integrityError = String(item.integrityError || "").trim();
  const blocked = state.includes("blocked") || Boolean(integrityError) || securityErrors.length > 0;
  const cosign = asObject(asObject(toolchain.tools).cosign);
  const trust = asObject(item.publisherTrust);
  const signature = asObject(item.signatureReceipt);
  const staging = asObject(item.staging);
  const actions = asObject(item.actions);
  const activationBlockedBy = asList(item.activationBlockedBy).map(value => asText(value, ""));
  const previousVersion = String(item.previousVersion || "").trim();
  const trustState = asText(trust.state, MARKETPLACE_UNAVAILABLE);
  const signatureState = asText(signature.state, MARKETPLACE_UNAVAILABLE);
  const stagingState =
    staging.state === "staged" || state === "staged"
      ? "Staged"
      : staging.state === "none"
        ? "None"
        : MARKETPLACE_UNAVAILABLE;

  let activationDetail =
    "Activate runs the reviewed OCI stage+promote path for an installed version.";
  if (blocked) {
    activationDetail = "Activation is blocked by reported integrity or security evidence.";
  } else if (state === "active") {
    activationDetail = "This version is already active.";
  } else if (activationBlockedBy.length) {
    activationDetail = `Install recorded activation blockers: ${activationBlockedBy.join(", ")}.`;
  } else if (!actions.activate) {
    activationDetail =
      "Activation is unavailable until a verified install (and attested OCI evidence) exists.";
  }

  return {
    id: asText(item.moduleId),
    name: asText(item.name, asText(item.moduleId, "Unnamed module")),
    summary: asText(item.summary, "No summary in the installed manifest."),
    version: asText(item.version),
    previousVersion,
    compatibility: marketplaceCompatibility(item.compat),
    state,
    tone: marketplaceStateTone(state),
    blocked,
    blockedReasons: [integrityError, ...securityErrors].filter(Boolean),
    publisher: {
      id: asText(publisher.id),
      name: asText(publisher.name, asText(publisher.id)),
      identity: asText(publisher.identity),
    },
    permissions: asList(item.permissions),
    capabilityCount: Number.isFinite(Number(item.capabilityCount))
      ? Number(item.capabilityCount)
      : null,
    trust: {
      state: trust.trusted === true ? "Trusted" : trustState === "untrusted" ? "Untrusted" : trustState,
      detail: asText(
        trust.detail,
        "The installed catalog reports publisher identity, but not the current trust-store binding.",
      ),
    },
    signature: {
      state:
        signatureState === "verified"
          ? "Verified"
          : signatureState === "blocked"
            ? "Blocked"
            : signatureState === "missing"
              ? "Missing"
              : MARKETPLACE_UNAVAILABLE,
      toolReady: cosign.healthy === true,
      detail: asText(
        signature.detail,
        "The installed catalog does not expose the detached signature receipt for this version.",
      ),
    },
    staging: {
      state: stagingState,
      detail: asText(
        staging.detail,
        state === "staged"
          ? "The catalog explicitly reports a staged package."
          : "The installed catalog does not expose the separate OCI staged pointer.",
      ),
      digest: asText(staging.ociManifestDigest, ""),
    },
    actions: {
      activate: actions.activate === true && !blocked && state !== "active",
      disable: actions.disable === true && state === "active",
      rollback: actions.rollback === true && Boolean(previousVersion),
    },
    activation: {
      allowed: actions.activate === true && !blocked && state !== "active",
      detail: activationDetail,
    },
  };
}

function normalizeMarketplaceSnapshotsUnchecked(catalogValue, toolchainValue) {
  const catalog = asObject(catalogValue);
  const toolchain = asObject(toolchainValue);
  const errors = [];

  const catalogValid = catalog.schema === CATALOG_SCHEMA;
  const toolchainValid = toolchain.schema === TOOLCHAIN_SCHEMA;

  if (!catalogValid) {
    errors.push(
      catalog.schema
        ? `Unsupported installed catalog schema: ${catalog.schema}`
        : "Installed marketplace catalog was not returned.",
    );
  }
  if (!toolchainValid) {
    errors.push(
      toolchain.schema
        ? `Unsupported marketplace toolchain schema: ${toolchain.schema}`
        : "Marketplace toolchain snapshot was not returned.",
    );
  }

  const tools = toolchainValid
    ? ["cosign", "syft", "grype", "defender", "wasmtime"].map(name =>
        normalizeTool(name, asObject(toolchain.tools)[name]),
      )
    : [];
  const modules = catalogValid
    ? asList(catalog.modules).map(item => normalizeModule(item, toolchainValid ? toolchain : {}))
    : [];

  return {
    schema: "neyvia.marketplace-operator-view/v1",
    catalogSchema: catalogValid ? catalog.schema : null,
    toolchainSchema: toolchainValid ? toolchain.schema : null,
    errors,
    modules,
    moduleCount: modules.length,
    activeCount: modules.filter(item => item.state === "active").length,
    disabledCount: modules.filter(item => item.state === "disabled").length,
    installedCount: modules.filter(item => item.state === "installed").length,
    blockedCount: modules.filter(item => item.blocked).length,
    activationGateReady: toolchainValid ? toolchain.activationGateReady === true : false,
    tools,
    policy: toolchainValid ? asObject(toolchain.policy) : {},
    sourceDisclosure:
      "Bundled apps activate from this signed Neyvia build. Independent apps download only a catalog-pinned GitHub release and verify its SHA-256 before installation. Third-party modules keep the reviewed install/activate/disable/rollback lifecycle.",
    installDisclosure:
      "Install verifies a local signed package into an immutable version directory. Activation requires externally attested OCI evidence. Disable and rollback change the activation pointer without deleting versions.",
  };
}

export async function loadMarketplaceView(callBackend) {
  if (typeof callBackend !== "function") {
    throw new TypeError("callBackend must be a function");
  }

  const [catalogResult, toolchainResult] = await Promise.allSettled([
    callBackend(MARKETPLACE_BACKEND_COMMANDS.catalog, {}),
    callBackend(MARKETPLACE_BACKEND_COMMANDS.toolchain, {}),
  ]);

  const view = normalizeMarketplaceSnapshots(
    catalogResult.status === "fulfilled" ? catalogResult.value : null,
    toolchainResult.status === "fulfilled" ? toolchainResult.value : null,
  );

  if (catalogResult.status === "rejected") {
    view.errors.push(`Installed catalog unavailable: ${String(catalogResult.reason?.message || catalogResult.reason)}`);
  }
  if (toolchainResult.status === "rejected") {
    view.errors.push(`Toolchain snapshot unavailable: ${String(toolchainResult.reason?.message || toolchainResult.reason)}`);
  }
  return view;
}

export async function runMarketplaceLifecycleAction(callBackend, action, item, options = {}) {
  if (typeof callBackend !== "function") {
    throw new TypeError("callBackend must be a function");
  }
  const moduleId = item?.id;
  if (!moduleId) {
    throw new Error("No marketplace package selected");
  }
  const requestedBy = String(options.requestedBy || "marketplace-panel").trim();
  if (action === "activate") {
    const result = await callBackend(MARKETPLACE_BACKEND_COMMANDS.activate, {
      moduleId,
      version: item.version,
      requestedBy,
    });
    if (result?.activated !== true) {
      const blockers = [
        ...(result?.blockedBy || []),
        ...(result?.securityEvidenceErrors || []),
      ].filter(Boolean);
      throw new Error(
        blockers.length
          ? `Activation blocked: ${blockers.join("; ")}`
          : "Activation did not complete",
      );
    }
    return result;
  }
  if (action === "disable") {
    return callBackend(MARKETPLACE_BACKEND_COMMANDS.disable, {
      moduleId,
      requestedBy,
      reason: String(options.reason || "Operator disabled module from Marketplace panel."),
    });
  }
  if (action === "rollback") {
    if (!item.previousVersion) {
      throw new Error("No previous verified version is available to roll back to");
    }
    return callBackend(MARKETPLACE_BACKEND_COMMANDS.rollback, {
      moduleId,
      requestedBy,
      reason: String(options.reason || "Operator rolled back module from Marketplace panel."),
      targetVersion: item.previousVersion,
    });
  }
  throw new Error(`Unsupported marketplace action: ${action}`);
}

export function normalizeMarketplaceSnapshots(...args) { return checkPresentationAction("marketplace.snapshots", args, normalizeMarketplaceSnapshotsUnchecked(...args)); }
