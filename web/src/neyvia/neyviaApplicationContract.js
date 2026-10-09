/**
 * Neyvia application contract.
 *
 * Two opposite developer propositions, one set of low-level contracts:
 *
 *   sdk-external      "I keep my own product, brand and interface, but I don't
 *                      want to build AI infrastructure." Neyvia is a set of
 *                      services behind a stable SDK. The application never
 *                      renders the Neyvia shell, and is *not* automatically a
 *                      marketplace application.
 *
 *   ecosystem-native  "I like this ecosystem and want to build through it."
 *                      The application uses Neyvia surfaces, sessions, context,
 *                      files, permissions, runtime services, artifacts and
 *                      evidence, can be exercised from inside, and can be
 *                      packaged and proposed to the Marketplace.
 *
 * They share identity, capability descriptions, events, artifacts, permissions
 * and receipts. They are not the same product proposition and must not be
 * presented as one.
 */

import { normalizeEmbedPresentation } from "./neyviaEmbeddedWorkspace.js";

export const NEYVIA_APPLICATION_CONTRACT_SCHEMA = "neyvia.application.contract.v1";

export const NEYVIA_APPLICATION_KINDS = Object.freeze([
  Object.freeze({
    id: "sdk-external",
    label: "SDK application",
    summary:
      "An independent product using Neyvia services through the SDK. Keeps its own interface and brand.",
    rendersNeyviaShell: false,
    marketplaceEligible: false,
    embeddable: false,
  }),
  Object.freeze({
    id: "ecosystem-native",
    label: "Ecosystem application",
    summary:
      "Built through Neyvia. Uses Neyvia surfaces, sessions and services; can be packaged for the Marketplace.",
    rendersNeyviaShell: true,
    marketplaceEligible: true,
    embeddable: true,
  }),
]);

const KIND_IDS = new Set(NEYVIA_APPLICATION_KINDS.map(item => item.id));

export function normalizeApplicationKind(value) {
  const id = String(value || "").trim();
  return KIND_IDS.has(id) ? id : "sdk-external";
}

export function applicationKindMeta(id) {
  return NEYVIA_APPLICATION_KINDS.find(item => item.id === normalizeApplicationKind(id)) || null;
}

/* --------------------------------------------------------- shared services */

/**
 * The service surface both directions consume. An SDK application adopts a
 * subset and can adopt more later without rewriting its integration — so each
 * service is independently declarable.
 */
export const NEYVIA_SERVICE_CONTRACTS = Object.freeze([
  Object.freeze({ id: "provider-routing", label: "Provider routing", externalSafe: true }),
  Object.freeze({ id: "agents", label: "Agents", externalSafe: true }),
  Object.freeze({ id: "memory", label: "Durable memory", externalSafe: true }),
  Object.freeze({ id: "tools", label: "Tools", externalSafe: true }),
  Object.freeze({ id: "permissions", label: "Permissions", externalSafe: true }),
  Object.freeze({ id: "evidence", label: "Evidence and receipts", externalSafe: true }),
  Object.freeze({ id: "artifacts", label: "Artifact custody", externalSafe: true }),
  Object.freeze({ id: "orchestration", label: "Orchestration", externalSafe: true }),
  Object.freeze({ id: "runtime-supervision", label: "Runtime supervision", externalSafe: true }),
  Object.freeze({ id: "sessions", label: "Session identity", externalSafe: true }),
  Object.freeze({ id: "events", label: "Event stream", externalSafe: true }),
  /** Shell-only: rendering inside Neyvia surfaces is not an SDK capability. */
  Object.freeze({ id: "shell-surfaces", label: "Neyvia surfaces", externalSafe: false }),
  Object.freeze({ id: "embedded-workspace", label: "Embedded workspace", externalSafe: false }),
]);

const SERVICE_IDS = new Map(NEYVIA_SERVICE_CONTRACTS.map(item => [item.id, item]));

export function serviceContract(id) {
  return SERVICE_IDS.get(String(id || "").trim()) || null;
}

/* --------------------------------------------------------------- manifest */

function asList(value) {
  return Array.isArray(value) ? value : [];
}

function asRecord(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function text(value, fallback = "") {
  const out = String(value ?? "").trim();
  return out || fallback;
}

/**
 * Normalize an application manifest from either direction. Validation is
 * refusal-based: an application that claims a service or presentation its kind
 * cannot have gets a problem, not a silent grant.
 */
export function normalizeApplicationManifest(value) {
  const item = asRecord(value);
  const kind = normalizeApplicationKind(item.kind || item.applicationKind);
  const meta = applicationKindMeta(kind);
  const problems = [];

  const applicationId = text(item.applicationId || item.moduleId || item.id);
  if (!applicationId) problems.push("Manifest has no application id.");

  const requestedServices = asList(item.services || item.capabilitiesRequested).map(value => text(value));
  const services = [];
  for (const id of requestedServices) {
    const contract = serviceContract(id);
    if (!contract) {
      problems.push(`Unknown service contract: ${id}.`);
      continue;
    }
    if (kind === "sdk-external" && !contract.externalSafe) {
      problems.push(`${contract.label} is only available to ecosystem applications.`);
      continue;
    }
    if (!services.includes(id)) services.push(id);
  }

  /**
   * Embedding declaration. An application must say where and how it may be
   * embedded; it does not get to place itself anywhere in the UI.
   */
  const declaredSurfaces = asList(item.surfaces || item.embedIn).map(value => text(value)).filter(Boolean);
  const declaredPresentations = asList(item.presentations)
    .map(value => normalizeEmbedPresentation(value))
    .filter((value, index, list) => list.indexOf(value) === index);
  if (!meta?.embeddable && (declaredSurfaces.length || declaredPresentations.length)) {
    problems.push("An SDK application cannot declare Neyvia embedding surfaces.");
  }
  if (meta?.embeddable && !declaredSurfaces.length) {
    problems.push("An ecosystem application must declare the surfaces it can appear in.");
  }

  const provenance = asRecord(item.provenance);
  const version = text(item.version);
  if (meta?.marketplaceEligible && item.marketplaceProposed === true) {
    if (!version) problems.push("Marketplace publication requires a version.");
    if (!text(provenance.publisher || asRecord(item.publisher).id)) {
      problems.push("Marketplace publication requires a publisher identity.");
    }
    if (!text(item.previousVersion) && item.rollbackTarget === undefined) {
      // Not a problem for a first version — rollback becomes available later.
    }
  }

  return Object.freeze({
    schema: NEYVIA_APPLICATION_CONTRACT_SCHEMA,
    applicationId,
    kind,
    kindLabel: meta?.label || kind,
    name: text(item.name, applicationId),
    summary: text(item.summary),
    version: version || null,
    previousVersion: text(item.previousVersion) || null,
    services: Object.freeze(services),
    /** Capabilities the application *provides* to the ecosystem, if any. */
    provides: Object.freeze(
      asList(item.provides || item.capabilities).map(entry =>
        Object.freeze({
          capabilityId: text(asRecord(entry).capabilityId || asRecord(entry).id || entry),
          label: text(asRecord(entry).label || asRecord(entry).name),
        }),
      ).filter(entry => entry.capabilityId),
    ),
    permissions: Object.freeze(asList(item.permissions).map(value => text(value)).filter(Boolean)),
    surfaces: Object.freeze(meta?.embeddable ? declaredSurfaces : []),
    presentations: Object.freeze(
      meta?.embeddable
        ? declaredPresentations.length
          ? declaredPresentations
          : ["inline-card"]
        : [],
    ),
    /**
     * Served entry point for an embedded ecosystem application. Null until the
     * backend hosts one: a marketplace tile is not a running application, and
     * the embedded adapter refuses to render without this.
     */
    entryPointUrl:
      text(item.entryPointUrl)
      || text(asRecord(item.runtime).entryPointUrl)
      || text(asRecord(item.runtime).servedUrl)
      || null,
    rendersNeyviaShell: meta?.rendersNeyviaShell === true,
    marketplaceEligible: meta?.marketplaceEligible === true,
    marketplaceProposed: meta?.marketplaceEligible === true && item.marketplaceProposed === true,
    provenance: Object.freeze({
      publisher: text(provenance.publisher || asRecord(item.publisher).id) || null,
      origin: text(provenance.origin || item.origin) || null,
      signature: text(provenance.signature) || null,
      compatibility: text(provenance.compatibility || item.compatibility) || null,
    }),
    problems: Object.freeze(problems),
    valid: problems.length === 0,
  });
}

/**
 * The runtime binding an activated ecosystem application gets. Installing must
 * connect real declared capabilities — never only a marketplace tile — and
 * disabling must remove them again.
 */
export function bindApplicationCapabilities(manifest, { state = "installed" } = {}) {
  const item = manifest?.schema === NEYVIA_APPLICATION_CONTRACT_SCHEMA
    ? manifest
    : normalizeApplicationManifest(manifest);
  const active = String(state || "").toLowerCase() === "active";
  return Object.freeze({
    schema: "neyvia.application.binding.v1",
    applicationId: item.applicationId,
    kind: item.kind,
    state: String(state || "installed"),
    /** Empty while not active: a disabled application provides nothing. */
    capabilities: Object.freeze(
      active
        ? item.provides.map(entry =>
            Object.freeze({
              capabilityId: entry.capabilityId,
              label: entry.label || entry.capabilityId,
              moduleId: item.applicationId,
              surfaces: item.surfaces,
              presentations: item.presentations,
              adapterId: "marketplace-app",
            }),
          )
        : [],
    ),
    services: item.services,
    permissions: item.permissions,
    detail: active
      ? "Active: declared capabilities are connected to their declared surfaces."
      : "Not active: declared capabilities are not connected. Activation is required.",
  });
}

/**
 * Where an installed application may actually render. Returns a refusal
 * instead of a guess when the manifest never declared the surface.
 */
export function resolveApplicationEmbedding(manifest, zoneId, presentation = null) {
  const item = manifest?.schema === NEYVIA_APPLICATION_CONTRACT_SCHEMA
    ? manifest
    : normalizeApplicationManifest(manifest);
  if (!item.marketplaceEligible) {
    return Object.freeze({
      allowed: false,
      reason: "SDK applications run in their own product and are not embedded in Neyvia surfaces.",
    });
  }
  const zone = text(zoneId);
  if (!item.surfaces.includes(zone)) {
    return Object.freeze({
      allowed: false,
      reason: `${item.name} did not declare the ${zone || "requested"} surface.`,
      surfaces: item.surfaces,
    });
  }
  const requested = presentation
    ? normalizeEmbedPresentation(presentation, item.presentations[0])
    : item.presentations[0];
  if (!item.presentations.includes(requested)) {
    return Object.freeze({
      allowed: false,
      reason: `${item.name} did not declare the "${requested}" presentation.`,
      presentations: item.presentations,
    });
  }
  return Object.freeze({
    allowed: true,
    applicationId: item.applicationId,
    zoneId: zone,
    presentation: requested,
    adapterId: "marketplace-app",
    permissions: item.permissions,
  });
}

/**
 * Describe the two propositions for the developer-facing surface, so the UI
 * never merges them into one "build an app" button.
 */
export function describeDeveloperPropositions() {
  return Object.freeze(
    NEYVIA_APPLICATION_KINDS.map(kind =>
      Object.freeze({
        ...kind,
        services: Object.freeze(
          NEYVIA_SERVICE_CONTRACTS.filter(
            service => kind.id === "ecosystem-native" || service.externalSafe,
          ).map(service => service.id),
        ),
        publication:
          kind.id === "ecosystem-native"
            ? "Can be packaged and proposed to the Marketplace with origin, version, capabilities, permissions, compatibility, provenance and rollback."
            : "Runs as an independent product. Using the SDK does not make it a marketplace application.",
      }),
    ),
  );
}

export const NEYVIA_APPLICATION_COMMANDS = Object.freeze({
  registry: "get_neyvia_application_registry_command",
  installBundledApplication: "install_bundled_application_command",
  uninstallBundledApplication: "uninstall_bundled_application_command",
  validateManifest: "validate_neyvia_application_manifest_command",
  resolveEmbedding: "resolve_application_embedding_command",
  registerSdkApplication: "register_sdk_application_command",
  unregisterSdkApplication: "unregister_sdk_application_command",
  validateModuleManifest: "validate_module_manifest_command",
  install: "install_module_package_command",
  activate: "activate_installed_module_command",
  disable: "disable_module_command",
  rollback: "rollback_module_command",
});
