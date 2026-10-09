import { checkPresentationAction } from "./neyviaPresentationContracts.js";
/**
 * Neyvia embedded workspace contract.
 *
 * One presentation foundation for every in-session window: external runtime
 * windows, PDF/Office readers, Image Playground results, browser and app
 * previews, marketplace applications, and other artifact-aware tools.
 *
 * The content adapter varies. Embedding, expansion, collapse, lineage,
 * permissions, retained state and return behaviour do not.
 *
 * Rules encoded here:
 *  - collapsing never unmounts the owner's state (no provider restart);
 *  - a closed workspace stops being orchestration clutter;
 *  - context and permissions are what was explicitly granted, nothing more;
 *  - every workspace knows its parent session/mission and its lineage;
 *  - heavy content is loaded on open, not with the summary record.
 */

export const NEYVIA_EMBEDDED_WORKSPACE_SCHEMA = "neyvia.embedded.workspace.v1";

/* ------------------------------------------------------------ presentation */

export const NEYVIA_EMBED_PRESENTATIONS = Object.freeze([
  Object.freeze({
    id: "inline-card",
    label: "Inline card",
    detail: "Sits in the transcript beside the message that produced it.",
    occupiesViewport: false,
  }),
  Object.freeze({
    id: "dock-right",
    label: "Dock right",
    detail: "Beside the session; chat and orchestration keep running.",
    occupiesViewport: false,
  }),
  Object.freeze({
    id: "dock-left",
    label: "Dock left",
    detail: "Left of the session; the main surface stays interactive.",
    occupiesViewport: false,
  }),
  Object.freeze({
    id: "floating-center",
    label: "Floating window",
    detail: "A focused window over the session without interrupting it.",
    occupiesViewport: false,
  }),
  Object.freeze({
    id: "fullscreen",
    label: "Fullscreen",
    detail: "The workspace owns the viewport; exit returns to the parent context.",
    occupiesViewport: true,
  }),
]);

const PRESENTATION_IDS = new Set(NEYVIA_EMBED_PRESENTATIONS.map(item => item.id));

export function normalizeEmbedPresentation(value, fallback = "inline-card") {
  const id = String(value || "").trim();
  if (PRESENTATION_IDS.has(id)) return id;
  return PRESENTATION_IDS.has(fallback) ? fallback : "inline-card";
}

export function embedPresentationMeta(id) {
  return NEYVIA_EMBED_PRESENTATIONS.find(item => item.id === normalizeEmbedPresentation(id)) || null;
}

/* ---------------------------------------------------------------- adapters */

/**
 * Content adapters. `lazy` adapters are only imported when a workspace is
 * actually opened — a closed PDF or provider window costs nothing.
 */
const ADAPTERS = new Map();

export function registerEmbeddedAdapter(definition = {}) {
  const id = String(definition.id || "").trim();
  if (!id) throw new TypeError("An embedded adapter requires an id");
  const record = Object.freeze({
    id,
    label: String(definition.label || id),
    kind: String(definition.kind || "artifact"),
    /** Presentations this adapter can honestly render. */
    presentations: Object.freeze(
      (Array.isArray(definition.presentations) ? definition.presentations : ["inline-card", "fullscreen"])
        .map(value => normalizeEmbedPresentation(value))
        .filter((value, index, list) => list.indexOf(value) === index),
    ),
    /** Permissions the adapter needs; unmet permissions block the open. */
    requiredPermissions: Object.freeze(
      Array.isArray(definition.requiredPermissions) ? definition.requiredPermissions.map(String) : [],
    ),
    /** Does the adapter keep live state that must survive a collapse? */
    retainsState: definition.retainsState === true,
    /** () => Promise<Component> — only called on first open. */
    load: typeof definition.load === "function" ? definition.load : null,
  });
  ADAPTERS.set(id, record);
  return record;
}

export function embeddedAdapter(id) {
  return ADAPTERS.get(String(id || "").trim()) || null;
}

export function registeredEmbeddedAdapters() {
  return [...ADAPTERS.values()];
}

/* --------------------------------------------------------------- lifecycle */

export const NEYVIA_EMBED_STATES = Object.freeze([
  "opening",
  "open",
  "collapsed",
  "blocked",
  "closed",
]);

/** Collapsed keeps state; closed releases it. */
export function isEmbedRetained(state) {
  return state === "open" || state === "collapsed" || state === "opening";
}

let embedCounter = 0;

function nextEmbedId(kind) {
  embedCounter += 1;
  return `embed-${String(kind || "workspace")}-${Date.now().toString(36)}-${embedCounter}`;
}

/**
 * Create a workspace record. Note what is *not* here: the artifact body.
 * Summary records stay light; `contentRef` is resolved when the user opens it.
 */
export function createEmbeddedWorkspace({
  adapterId,
  title = "",
  subtitle = "",
  parentSessionId = null,
  parentMissionId = null,
  originEventId = null,
  originInvocationId = null,
  contentRef = null,
  context = null,
  permissions = null,
  presentation = null,
} = {}) {
  const adapter = embeddedAdapter(adapterId);
  const grants = Array.isArray(permissions?.grants) ? permissions.grants.map(String) : [];
  const missing = (adapter?.requiredPermissions || []).filter(id => !grants.includes(id));
  const requested = normalizeEmbedPresentation(presentation, adapter?.presentations?.[0]);
  const supported = !adapter || adapter.presentations.includes(requested);

  const problems = [];
  if (!adapter) problems.push(`No embedded adapter registered for "${adapterId}".`);
  if (missing.length) problems.push(`Missing granted permissions: ${missing.join(", ")}.`);
  if (adapter && !supported) {
    problems.push(`${adapter.label} does not declare the "${requested}" presentation.`);
  }

  return Object.freeze({
    schema: NEYVIA_EMBEDDED_WORKSPACE_SCHEMA,
    workspaceId: nextEmbedId(adapter?.kind || adapterId),
    adapterId: String(adapterId || ""),
    kind: adapter?.kind || "artifact",
    title: String(title || adapter?.label || adapterId || "Embedded workspace"),
    subtitle: String(subtitle || ""),
    parentSessionId: parentSessionId ? String(parentSessionId) : null,
    parentMissionId: parentMissionId ? String(parentMissionId) : null,
    lineage: Object.freeze({
      originEventId: originEventId ? String(originEventId) : null,
      originInvocationId: originInvocationId ? String(originInvocationId) : null,
    }),
    /** Pointer only — heavy content loads on open. */
    contentRef: contentRef && typeof contentRef === "object" ? Object.freeze({ ...contentRef }) : null,
    context: Object.freeze(
      context && typeof context === "object" ? { ...context } : {},
    ),
    permissions: Object.freeze({
      grants: Object.freeze(grants),
      approvalRequired: permissions?.approvalRequired !== false,
    }),
    presentation: supported ? requested : normalizeEmbedPresentation(adapter?.presentations?.[0]),
    restorePresentation: supported ? requested : normalizeEmbedPresentation(adapter?.presentations?.[0]),
    retainsState: adapter?.retainsState === true,
    state: problems.length ? "blocked" : "opening",
    problems: Object.freeze(problems),
    openedAt: new Date().toISOString(),
    lastFocusedAt: new Date().toISOString(),
  });
}

/* ---------------------------------------------------------------- host store */

const DEFAULT_RETAINED_LIMIT = 4;

function createEmbeddedWorkspaceHostUnchecked({ retainedLimit = DEFAULT_RETAINED_LIMIT } = {}) {
  return Object.freeze({
    schema: NEYVIA_EMBEDDED_WORKSPACE_SCHEMA,
    workspaces: Object.freeze([]),
    focusedId: null,
    retainedLimit: Math.max(1, Number(retainedLimit) || DEFAULT_RETAINED_LIMIT),
  });
}

function rebuild(host, workspaces, focusedId) {
  return Object.freeze({
    ...host,
    workspaces: Object.freeze(workspaces),
    focusedId: focusedId || null,
  });
}

/**
 * Bounded retention: a session cannot grow embedded windows forever. The
 * oldest un-focused retained workspace is closed once the limit is passed.
 */
function enforceRetentionLimit(host, workspaces, focusedId) {
  const retained = workspaces.filter(item => isEmbedRetained(item.state));
  if (retained.length <= host.retainedLimit) return workspaces;
  const evictable = retained
    .filter(item => item.workspaceId !== focusedId)
    .sort((left, right) => String(left.lastFocusedAt).localeCompare(String(right.lastFocusedAt)));
  const evictCount = retained.length - host.retainedLimit;
  const evicting = new Set(evictable.slice(0, evictCount).map(item => item.workspaceId));
  return workspaces.map(item =>
    evicting.has(item.workspaceId)
      ? Object.freeze({ ...item, state: "closed", closedReason: "Retention limit — reopen from its origin event." })
      : item,
  );
}

function openEmbeddedWorkspaceUnchecked(host, record) {
  if (!record?.workspaceId) return host;

  // Opening the same subject again is a focus, not a second window. The
  // existing workspace keeps its retained state and its original lineage, and
  // only picks up a newly requested presentation.
  const equivalent = findEquivalentWorkspace(host, record);
  if (equivalent) {
    const refreshed = Object.freeze({
      ...equivalent,
      state: "open",
      presentation: record.presentation || equivalent.presentation,
      restorePresentation: record.presentation || equivalent.restorePresentation,
      lastFocusedAt: new Date().toISOString(),
    });
    const others = host.workspaces.filter(item => item.workspaceId !== equivalent.workspaceId);
    return rebuild(
      host,
      enforceRetentionLimit(host, [...others, refreshed], refreshed.workspaceId),
      refreshed.workspaceId,
    );
  }

  const existing = host.workspaces.filter(item => item.workspaceId !== record.workspaceId);
  const opened = record.state === "blocked" ? record : Object.freeze({ ...record, state: "open" });
  const focusedId = opened.state === "blocked" ? host.focusedId : opened.workspaceId;
  return rebuild(host, enforceRetentionLimit(host, [...existing, opened], focusedId), focusedId);
}

function focusEmbeddedWorkspaceUnchecked(host, workspaceId) {
  const existing = host.workspaces.find(item => item.workspaceId === workspaceId);
  if (!existing || !isEmbedRetained(existing.state)) return host;
  const next = host.workspaces.map(item =>
    item.workspaceId === workspaceId
      ? Object.freeze({
          ...item,
          state: item.state === "collapsed" ? "open" : item.state,
          lastFocusedAt: new Date().toISOString(),
        })
      : item,
  );
  return rebuild(host, next, workspaceId);
}

/**
 * Collapse ≠ close. The record and its retained adapter state survive so the
 * runtime/provider does not restart when the user returns to it.
 */
function collapseEmbeddedWorkspaceUnchecked(host, workspaceId) {
  const next = host.workspaces.map(item =>
    item.workspaceId === workspaceId && isEmbedRetained(item.state)
      ? Object.freeze({ ...item, state: "collapsed", presentation: item.restorePresentation })
      : item,
  );
  const focusedId = host.focusedId === workspaceId ? null : host.focusedId;
  return rebuild(host, next, focusedId);
}

function expandEmbeddedWorkspaceUnchecked(host, workspaceId, presentation = "fullscreen") {
  const existing = host.workspaces.find(item => item.workspaceId === workspaceId);
  if (!existing || !isEmbedRetained(existing.state)) return host;
  const target = normalizeEmbedPresentation(presentation, "fullscreen");
  const next = host.workspaces.map(item => {
    if (item.workspaceId !== workspaceId) return item;
    const adapter = embeddedAdapter(item.adapterId);
    if (adapter && !adapter.presentations.includes(target)) return item;
    return Object.freeze({
      ...item,
      state: "open",
      presentation: target,
      restorePresentation: item.presentation === "fullscreen" ? item.restorePresentation : item.presentation,
      lastFocusedAt: new Date().toISOString(),
    });
  });
  return rebuild(host, next, workspaceId);
}

/** Return to the exact parent context: restore the pre-expansion presentation. */
function restoreEmbeddedWorkspaceUnchecked(host, workspaceId) {
  const existing = host.workspaces.find(item => item.workspaceId === workspaceId);
  if (!existing || !isEmbedRetained(existing.state)) return host;
  const next = host.workspaces.map(item =>
    item.workspaceId === workspaceId
      ? Object.freeze({ ...item, state: "open", presentation: item.restorePresentation })
      : item,
  );
  return rebuild(host, next, workspaceId);
}

function closeEmbeddedWorkspaceUnchecked(host, workspaceId, reason = "") {
  const next = host.workspaces.map(item =>
    item.workspaceId === workspaceId
      ? Object.freeze({ ...item, state: "closed", closedReason: String(reason || "") })
      : item,
  );
  const focusedId = host.focusedId === workspaceId ? null : host.focusedId;
  return rebuild(host, next, focusedId);
}

/** Closed workspaces are dropped — they must not linger as orchestration clutter. */
export function pruneClosedWorkspaces(host) {
  return rebuild(
    host,
    host.workspaces.filter(item => item.state !== "closed"),
    host.focusedId,
  );
}

export function closeWorkspacesForSession(host, sessionId, reason = "Parent session ended.") {
  const next = host.workspaces.map(item =>
    item.parentSessionId === String(sessionId) && isEmbedRetained(item.state)
      ? Object.freeze({ ...item, state: "closed", closedReason: reason })
      : item,
  );
  return rebuild(host, next, host.focusedId);
}

/* ---------------------------------------------------------------- selectors */

/**
 * Mount policy.
 *
 * An open workspace is mounted whether or not it is focused — a visible PDF or
 * preview must not blank when the user clicks another window. A *collapsed*
 * workspace stays mounted only when its adapter declared retained state, which
 * is what makes "reopening does not restart it" true; adapters without retained
 * state are unmounted on collapse and reload when reopened.
 */
function shouldMountEmbeddedWorkspaceUnchecked(host, workspaceId) {
  const item = host.workspaces.find(entry => entry.workspaceId === workspaceId);
  if (!item || !isEmbedRetained(item.state)) return false;
  if (item.state === "collapsed") return item.retainsState === true;
  return true;
}

/**
 * Identity of what a workspace is showing, so opening the same artifact,
 * document or invocation twice focuses the existing window instead of stacking
 * duplicates of the same thing in the session.
 */
export function embeddedWorkspaceIdentity(record) {
  if (!record) return "";
  const context = record.context || {};
  const ref = record.contentRef || {};
  const subject =
    context.artifactId
    || context.applicationId
    || context.imageSessionId
    || record.lineage?.originInvocationId
    || ref.path
    || ref.url
    || ref.endpoint
    || record.title
    || "";
  return `${record.adapterId}::${subject}`;
}

/** Find an open workspace already showing the same subject. */
export function findEquivalentWorkspace(host, record) {
  const identity = embeddedWorkspaceIdentity(record);
  if (!identity) return null;
  return (
    host.workspaces.find(
      item => isEmbedRetained(item.state) && embeddedWorkspaceIdentity(item) === identity,
    ) || null
  );
}

function visibleEmbeddedWorkspacesUnchecked(host, { parentSessionId = null, parentMissionId = null } = {}) {
  return host.workspaces.filter(item => {
    if (!isEmbedRetained(item.state)) return false;
    if (parentSessionId != null && item.parentSessionId !== String(parentSessionId)) return false;
    if (parentMissionId != null && item.parentMissionId !== String(parentMissionId)) return false;
    return true;
  });
}

function fullscreenEmbeddedWorkspaceUnchecked(host) {
  return (
    host.workspaces.find(item => item.state === "open" && item.presentation === "fullscreen") || null
  );
}

/**
 * The event/receipt an embedded interaction must emit so nothing an embedded
 * app does is invisible to the ecosystem. Callers pass the result to the normal
 * evidence path; this only shapes it.
 */
export function embeddedInteractionEvent(workspace, { action, detail = "", artifacts = [], receipts = [] } = {}) {
  if (!workspace) return null;
  return Object.freeze({
    schema: "neyvia.embedded.interaction.v1",
    workspaceId: workspace.workspaceId,
    adapterId: workspace.adapterId,
    parentSessionId: workspace.parentSessionId,
    parentMissionId: workspace.parentMissionId,
    originEventId: workspace.lineage?.originEventId || null,
    originInvocationId: workspace.lineage?.originInvocationId || null,
    action: String(action || "interaction"),
    detail: String(detail || ""),
    artifacts: Object.freeze(Array.isArray(artifacts) ? artifacts : []),
    receipts: Object.freeze(Array.isArray(receipts) ? receipts : []),
    at: new Date().toISOString(),
  });
}

/**
 * Pick the adapter for a delivered artifact from what it actually is. A shared
 * mapping, so the same artifact opens the same way from Agent Live, Builder,
 * Office or Chat instead of each surface inventing its own viewer.
 */
export function adapterForArtifact(artifact = {}) {
  const kind = String(artifact.kind || artifact.type || "").toLowerCase();
  const media = String(artifact.mediaType || artifact.media_type || artifact.contentType || "").toLowerCase();
  const target = String(
    artifact.path || artifact.url || artifact.title || artifact.label || artifact.id || "",
  ).toLowerCase();
  const endsWith = (...extensions) => extensions.some(extension => target.endsWith(extension));

  if (media.includes("pdf") || endsWith(".pdf") || kind.includes("pdf")) return "pdf-reader";
  if (endsWith(".docx", ".doc", ".odt", ".xlsx", ".xls", ".ods", ".pptx", ".ppt", ".odp")) {
    return "office-document";
  }
  if (media.startsWith("image/") || endsWith(".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")) {
    return kind.includes("playground") ? "image-playground" : "browser-capture";
  }
  if (kind.includes("screenshot") || kind.includes("capture")) return "browser-capture";
  if (kind.includes("preview") || endsWith(".html", ".htm") || media.includes("text/html")) {
    return "app-preview";
  }
  if (kind.includes("runtime") || kind.includes("session")) return "runtime-window";
  if (kind.includes("module") || kind.includes("application")) return "marketplace-app";
  return "app-preview";
}

/* ------------------------------------------------- default adapter registry */

/**
 * Built-in adapters. `load` is intentionally lazy: none of these modules are
 * pulled into the shell bundle until a workspace of that kind is opened.
 */
registerEmbeddedAdapter({
  id: "runtime-window",
  label: "External runtime",
  kind: "runtime",
  presentations: ["inline-card", "dock-right", "floating-center", "fullscreen"],
  retainsState: true,
  requiredPermissions: [],
});

registerEmbeddedAdapter({
  id: "pdf-reader",
  label: "PDF reader",
  kind: "document",
  presentations: ["inline-card", "dock-right", "fullscreen"],
  retainsState: false,
});

registerEmbeddedAdapter({
  id: "office-document",
  label: "Office document",
  kind: "document",
  presentations: ["inline-card", "dock-right", "fullscreen"],
  retainsState: false,
});

registerEmbeddedAdapter({
  id: "image-playground",
  label: "Image Playground result",
  kind: "image",
  presentations: ["inline-card", "floating-center", "fullscreen"],
  retainsState: true,
});

registerEmbeddedAdapter({
  id: "app-preview",
  label: "Application preview",
  kind: "preview",
  presentations: ["inline-card", "dock-right", "fullscreen"],
  retainsState: true,
});

registerEmbeddedAdapter({
  id: "browser-capture",
  label: "Browser capture",
  kind: "capture",
  presentations: ["inline-card", "fullscreen"],
  retainsState: false,
});

registerEmbeddedAdapter({
  id: "marketplace-app",
  label: "Marketplace application",
  kind: "application",
  presentations: ["inline-card", "dock-right", "floating-center", "fullscreen"],
  retainsState: true,
  requiredPermissions: [],
});

export function createEmbeddedWorkspaceHost(...args) { return checkPresentationAction("embed.host", args, createEmbeddedWorkspaceHostUnchecked(...args), registeredEmbeddedAdapters()); }

export function openEmbeddedWorkspace(...args) { return checkPresentationAction("embed.open", args, openEmbeddedWorkspaceUnchecked(...args), registeredEmbeddedAdapters()); }

export function focusEmbeddedWorkspace(...args) { return checkPresentationAction("embed.focus", args, focusEmbeddedWorkspaceUnchecked(...args), registeredEmbeddedAdapters()); }

export function collapseEmbeddedWorkspace(...args) { return checkPresentationAction("embed.collapse", args, collapseEmbeddedWorkspaceUnchecked(...args), registeredEmbeddedAdapters()); }

export function expandEmbeddedWorkspace(...args) { return checkPresentationAction("embed.expand", args, expandEmbeddedWorkspaceUnchecked(...args), registeredEmbeddedAdapters()); }

export function restoreEmbeddedWorkspace(...args) { return checkPresentationAction("embed.restore", args, restoreEmbeddedWorkspaceUnchecked(...args), registeredEmbeddedAdapters()); }

export function closeEmbeddedWorkspace(...args) { return checkPresentationAction("embed.close", args, closeEmbeddedWorkspaceUnchecked(...args), registeredEmbeddedAdapters()); }

export function shouldMountEmbeddedWorkspace(...args) { return checkPresentationAction("embed.mount", args, shouldMountEmbeddedWorkspaceUnchecked(...args), registeredEmbeddedAdapters()); }

export function visibleEmbeddedWorkspaces(...args) { return checkPresentationAction("embed.visible", args, visibleEmbeddedWorkspacesUnchecked(...args), registeredEmbeddedAdapters()); }

export function fullscreenEmbeddedWorkspace(...args) { return checkPresentationAction("embed.fullscreen", args, fullscreenEmbeddedWorkspaceUnchecked(...args), registeredEmbeddedAdapters()); }
