/**
 * Neyvia capability identity and placement.
 *
 * One capability = one identity, wherever it appears. A PDF tool discovered in
 * Library, installed through Marketplace, opened from Office and embedded
 * inside Agent Live is *the same object* — not four unrelated tiles with four
 * copies of state.
 *
 * Placement is decided by user intention, not by "where do new features go".
 * Each zone below has a product meaning; a capability declares where it is
 * discovered, where it is used, and how it may be presented.
 */

import { NEYVIA_EMBED_PRESENTATIONS, normalizeEmbedPresentation } from "./neyviaEmbeddedWorkspace.js";

export const NEYVIA_CAPABILITY_IDENTITY_SCHEMA = "neyvia.capability.identity.v1";

/* ------------------------------------------------------------------ zones */

/**
 * `tab` zones are primary shell surfaces; `panel` zones are full surfaces
 * reached from them. `intent` states what the user is trying to do there —
 * the deciding factor for placement.
 */
export const NEYVIA_ZONES = Object.freeze([
  Object.freeze({
    id: "chat",
    label: "Chat",
    kind: "tab",
    shellSurface: "agent",
    intent: "Conversational work and transient tool invocation.",
    durability: "transient",
  }),
  Object.freeze({
    id: "notebook",
    label: "Notebook",
    kind: "tab",
    shellSurface: "notebook",
    intent: "Durable knowledge, notes, structured context, material kept and revisited.",
    durability: "durable",
  }),
  Object.freeze({
    id: "lab",
    label: "Lab",
    kind: "tab",
    shellSurface: "lab",
    intent: "Experiments, media and device work, prototypes, staged tools.",
    durability: "experimental",
  }),
  Object.freeze({
    id: "orchestration",
    label: "Orchestration",
    kind: "tab",
    shellSurface: "builder",
    intent: "Missions, agents, execution, Builder supervision, Agent Live, approvals, evidence.",
    durability: "durable",
  }),
  Object.freeze({
    id: "library",
    label: "Library",
    kind: "tab",
    shellSurface: "library",
    intent: "Reusable capabilities, skills, templates and references to apply repeatedly.",
    durability: "durable",
  }),
  Object.freeze({
    id: "marketplace",
    label: "Marketplace",
    kind: "panel",
    shellSurface: "library",
    intent: "Discovery, installation, activation, disabling, versioning, provenance, rollback.",
    durability: "durable",
  }),
  Object.freeze({
    id: "office",
    label: "Office",
    kind: "panel",
    shellSurface: "notebook",
    intent: "Document-oriented creation, transformation, viewing and editing.",
    durability: "durable",
  }),
  Object.freeze({
    id: "personal-mesh",
    label: "Personal Mesh",
    kind: "panel",
    shellSurface: "lab",
    intent: "Connected computers, NAS, devices and the trusted relationships between them.",
    durability: "durable",
  }),
  Object.freeze({
    id: "image-playground",
    label: "Image Playground",
    kind: "panel",
    shellSurface: "lab",
    intent: "Image generation and iteration, comparisons, manifests, image artifact workflows.",
    durability: "experimental",
  }),
]);

const ZONE_IDS = new Set(NEYVIA_ZONES.map(item => item.id));

export function zoneMeta(zoneId) {
  return NEYVIA_ZONES.find(item => item.id === String(zoneId || "").trim()) || null;
}

export function isNeyviaZone(zoneId) {
  return ZONE_IDS.has(String(zoneId || "").trim());
}

/* ----------------------------------------------------------- capability kind */

/**
 * What the thing *is* decides how it behaves, not where it is listed.
 *   capability  — a managed operation Neyvia can run (tool suite, skill).
 *   application — an installed ecosystem-native or SDK-external application.
 *   artifact    — something produced; opened, not executed.
 *   runtime     — a live external runtime lane.
 */
export const NEYVIA_CAPABILITY_KINDS = Object.freeze([
  "capability",
  "application",
  "artifact",
  "runtime",
]);

export function normalizeCapabilityKind(value) {
  const id = String(value || "").trim();
  return NEYVIA_CAPABILITY_KINDS.includes(id) ? id : "capability";
}

/* ------------------------------------------------------------- registration */

const REGISTRY = new Map();

/**
 * Register one capability identity. `discoverIn` and `useIn` are deliberately
 * separate: a PDF tool is *discovered* in Library/Marketplace and *used* in
 * Office, Chat and Orchestration — without becoming several objects.
 */
export function defineCapability(definition = {}) {
  const id = String(definition.id || "").trim();
  if (!id) throw new TypeError("A capability identity requires an id");

  const discoverIn = (Array.isArray(definition.discoverIn) ? definition.discoverIn : [])
    .map(value => String(value || "").trim())
    .filter(isNeyviaZone);
  const useIn = (Array.isArray(definition.useIn) ? definition.useIn : [])
    .map(value => String(value || "").trim())
    .filter(isNeyviaZone);
  const presentations = (Array.isArray(definition.presentations) ? definition.presentations : ["inline-card"])
    .map(value => normalizeEmbedPresentation(value))
    .filter((value, index, list) => list.indexOf(value) === index);

  const record = Object.freeze({
    schema: NEYVIA_CAPABILITY_IDENTITY_SCHEMA,
    id,
    kind: normalizeCapabilityKind(definition.kind),
    label: String(definition.label || id),
    summary: String(definition.summary || ""),
    /** Managed tool-suite id, when this maps onto backend readiness truth. */
    suiteToolId: definition.suiteToolId ? String(definition.suiteToolId) : null,
    /** Installed module id, when this capability is provided by an application. */
    moduleId: definition.moduleId ? String(definition.moduleId) : null,
    discoverIn: Object.freeze(discoverIn),
    useIn: Object.freeze(useIn),
    presentations: Object.freeze(presentations),
    /** Which embedded adapter renders it when used in place. */
    adapterId: definition.adapterId ? String(definition.adapterId) : null,
    /** Does using it produce something the user keeps? */
    durability: ["transient", "durable", "experimental"].includes(definition.durability)
      ? definition.durability
      : "transient",
    requiresApproval: definition.requiresApproval === true,
  });
  REGISTRY.set(id, record);
  return record;
}

export function capabilityIdentity(id) {
  return REGISTRY.get(String(id || "").trim()) || null;
}

export function registeredCapabilities() {
  return [...REGISTRY.values()];
}

export function capabilitiesForZone(zoneId, { role = "any" } = {}) {
  const zone = String(zoneId || "").trim();
  return registeredCapabilities().filter(item => {
    if (role === "discover") return item.discoverIn.includes(zone);
    if (role === "use") return item.useIn.includes(zone);
    return item.discoverIn.includes(zone) || item.useIn.includes(zone);
  });
}

/**
 * Placement answer for a concrete request: can this capability be used here,
 * and in which presentation? Refuses instead of inventing a surface.
 */
export function resolveCapabilityPlacement(capabilityId, zoneId, requestedPresentation = null) {
  const capability = capabilityIdentity(capabilityId);
  const zone = zoneMeta(zoneId);
  if (!capability) {
    return Object.freeze({ allowed: false, reason: `Unknown capability "${capabilityId}".` });
  }
  if (!zone) {
    return Object.freeze({ allowed: false, reason: `Unknown zone "${zoneId}".` });
  }
  if (!capability.useIn.includes(zone.id)) {
    return Object.freeze({
      allowed: false,
      reason: `${capability.label} is not declared for use in ${zone.label}.`,
      discoverIn: capability.discoverIn,
      useIn: capability.useIn,
    });
  }
  const presentation = requestedPresentation
    ? normalizeEmbedPresentation(requestedPresentation, capability.presentations[0])
    : capability.presentations[0];
  if (!capability.presentations.includes(presentation)) {
    return Object.freeze({
      allowed: false,
      reason: `${capability.label} does not declare the "${presentation}" presentation.`,
      presentations: capability.presentations,
    });
  }
  return Object.freeze({
    allowed: true,
    capabilityId: capability.id,
    zoneId: zone.id,
    presentation,
    adapterId: capability.adapterId,
    requiresApproval: capability.requiresApproval,
    presentationMeta:
      NEYVIA_EMBED_PRESENTATIONS.find(item => item.id === presentation) || null,
  });
}

/**
 * Placement review used while correcting the information architecture: reports
 * capabilities that were dropped into a generic drawer without a use zone, or
 * that claim a zone whose intent does not match their durability.
 */
export function reviewCapabilityPlacement() {
  const problems = [];
  for (const capability of registeredCapabilities()) {
    if (!capability.useIn.length) {
      problems.push({
        capabilityId: capability.id,
        problem: "Discoverable but has no declared use zone.",
      });
    }
    if (capability.durability === "durable" && capability.useIn.every(zone => zone === "chat")) {
      problems.push({
        capabilityId: capability.id,
        problem: "Produces material the user keeps, but is only usable in Chat (transient).",
      });
    }
    if (capability.kind === "application" && !capability.moduleId) {
      problems.push({
        capabilityId: capability.id,
        problem: "Declared as an application but carries no installed module identity.",
      });
    }
  }
  return Object.freeze({
    schema: NEYVIA_CAPABILITY_IDENTITY_SCHEMA,
    capabilityCount: REGISTRY.size,
    problems: Object.freeze(problems),
  });
}

/* -------------------------------------------------- built-in placements */

defineCapability({
  id: "pdf",
  kind: "capability",
  label: "PDF reader",
  summary: "Read, extract and cite PDF content.",
  suiteToolId: "tool.poppler",
  adapterId: "pdf-reader",
  discoverIn: ["library", "marketplace"],
  useIn: ["chat", "office", "orchestration", "notebook"],
  presentations: ["inline-card", "dock-right", "fullscreen"],
  durability: "durable",
});

defineCapability({
  id: "office-convert",
  kind: "capability",
  label: "Document convert",
  summary: "Convert and render document formats through the verified toolchain.",
  suiteToolId: "tool.pandoc",
  adapterId: "office-document",
  discoverIn: ["library"],
  useIn: ["office", "chat", "orchestration"],
  presentations: ["inline-card", "dock-right", "fullscreen"],
  durability: "durable",
});

defineCapability({
  id: "image-playground",
  kind: "capability",
  label: "Image Playground",
  summary: "Generate, iterate and compare images with manifest-backed artifacts.",
  adapterId: "image-playground",
  discoverIn: ["lab", "library"],
  useIn: ["image-playground", "chat", "orchestration"],
  presentations: ["inline-card", "floating-center", "fullscreen"],
  durability: "experimental",
});

defineCapability({
  id: "web-capture",
  kind: "capability",
  label: "Web capture",
  summary: "Capture a page with the managed browser runtime.",
  suiteToolId: "tool.playwright",
  adapterId: "browser-capture",
  discoverIn: ["library"],
  useIn: ["chat", "lab", "orchestration"],
  presentations: ["inline-card", "fullscreen"],
  durability: "transient",
  requiresApproval: true,
});

defineCapability({
  id: "app-preview",
  kind: "artifact",
  label: "Application preview",
  summary: "Exercise what an agent delivered without leaving the mission.",
  adapterId: "app-preview",
  discoverIn: ["orchestration"],
  useIn: ["orchestration", "lab"],
  presentations: ["inline-card", "dock-right", "fullscreen"],
  durability: "durable",
});

defineCapability({
  id: "external-runtime",
  kind: "runtime",
  label: "External runtime",
  summary: "Claude Code, Grok Build, OpenCodeGo and other external runtimes.",
  adapterId: "runtime-window",
  discoverIn: ["library", "marketplace"],
  useIn: ["chat", "orchestration", "lab"],
  presentations: ["inline-card", "dock-right", "floating-center", "fullscreen"],
  durability: "durable",
  requiresApproval: true,
});

defineCapability({
  id: "personal-mesh",
  kind: "capability",
  label: "Personal Mesh",
  summary: "Connected computers, NAS and devices, and the trust between them.",
  discoverIn: ["lab"],
  useIn: ["personal-mesh", "orchestration"],
  presentations: ["inline-card", "fullscreen"],
  durability: "durable",
});
