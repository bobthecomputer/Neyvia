import { checkedImageAction, checkImagePromptPresets } from "./imagePlaygroundContracts.js";
export const IMAGE_PLAYGROUND_STORAGE_KEY = "fluxio.image_playground.project.v1";

export const CANVAS_SIZE_PRESETS = [
  { id: "square", label: "Square", width: 1024, height: 1024 },
  { id: "portrait", label: "Portrait", width: 1024, height: 1536 },
  { id: "landscape", label: "Landscape", width: 1536, height: 1024 },
  { id: "wide", label: "Wide", width: 1792, height: 1024 },
];

export const IMAGE_PROMPT_PRESETS = [
  {
    id: "saas-workbench",
    label: "Calm SaaS workbench",
    intent: "Operational product interface influenced by Linear, with clear supervision hierarchy.",
    style: "precise monochrome structure, restrained accent color, dense but readable controls",
    negative: "generic AI-purple glow, marketing hero, decorative dashboards, illegible text",
    strength: 0.72,
  },
  {
    id: "artifact-review",
    label: "Artifact review",
    intent: "Evidence-first review surface with editable annotations and a visible provenance trail.",
    style: "editorial proof layout, grounded typography, practical comparison controls",
    negative: "fake charts, invented metrics, decorative terminal text, generic AI-purple glow",
    strength: 0.68,
  },
  {
    id: "mobile-safe-controls",
    label: "Mobile-safe controls",
    intent: "Operator controls that remain obvious and reachable on a phone-sized first viewport.",
    style: "responsive compact cards, 44px targets, strong focus states, concise labels",
    negative: "desktop-only sidebars, hover-only actions, tiny controls, generic AI-purple glow",
    strength: 0.64,
  },
];

export const IMAGE_TOOL_DEFINITIONS = [
  { id: "select", label: "Select", hint: "Move, resize, and reorder layers." },
  { id: "region", label: "Region", hint: "Mark an area for inpainting or continuation." },
  { id: "mask", label: "Mask", hint: "Prepare mask-guided edits." },
  { id: "compare", label: "Compare", hint: "Review previous generations." },
];

// Fresh workspaces are empty. Existing stored layers and receipts are preserved.
export const DEFAULT_IMAGE_PROJECT = {
  id: "image-project-local", title: "Untitled image workspace", updatedAt: "",
  canvas: { width: 1024, height: 1024, background: "#111313", zoom: 0.62 },
  prompt: { mode: "generate", text: "", negative: "", style: "", strength: 0.72, preserveComposition: true },
  provider: { id: "codex_subscription_gpt_image2", model: "gpt-image-2", quality: "high", size: "1024x1024" },
  designReferences: [], annotationReadiness: { pins: [], rectangles: [], layers: [], comments: [] },
  skillsEvidence: [], focusedHistoryId: "", opsThreads: [], selectedLayerId: "", activeTool: "select",
  selection: { x: 0, y: 0, width: 0, height: 0, feather: 18, visible: false }, layers: [], history: [],
};

// Builds before 6 Oct seeded every new workspace with demo content (two Codex reference images, two
// prompt packs, three shape layers and a demo prompt) and normalizeProject saved them into each stored
// project. They are not the user's work: drop exactly those seeds on load, by their fixed ids and
// values, and leave everything the user made untouched.
const RETIRED_SEED_REFERENCE_IDS = new Set([
  "design-ref-imagegen-cyberpunk-20260513", "design-ref-a", "design-ref-b", "design-ref-codex-20260511T071327Z",
]);
const RETIRED_SEED_REQUEST_IDS = new Set([
  "imagegen_cyberpunk_gallery_20260513T005434Z", "codex_image_playground_live_review_reference_20260511T071327Z",
]);
const RETIRED_SEED_HISTORY_IDS = new Set(["hist-imagegen-cyberpunk-20260513"]);
const RETIRED_SEED_LAYERS = { "layer-background": "Generated base", "layer-subject": "Movable hero object", "layer-shadow": "Contact shadow" };
const RETIRED_SEED_PROMPT = {
  text: "A cinematic product workspace for autonomous creative agents, elegant dark glass interface, precise lighting, high-end editorial design",
  negative: "blurry, low quality, distorted typography",
  style: "editorial photoreal, subtle gold accents, cinematic lighting",
};

export function isRetiredSeed(item) {
  if (!item || typeof item !== "object") return false;
  return RETIRED_SEED_REFERENCE_IDS.has(item.id) || RETIRED_SEED_HISTORY_IDS.has(item.id)
    || RETIRED_SEED_REQUEST_IDS.has(item.requestId) || RETIRED_SEED_REQUEST_IDS.has(item.artifactId);
}

function withoutRetiredSeeds(project) {
  const layers = project.layers.filter(layer => RETIRED_SEED_LAYERS[layer?.id] !== layer?.name);
  const prompt = { ...project.prompt };
  for (const key of Object.keys(RETIRED_SEED_PROMPT)) if (prompt[key] === RETIRED_SEED_PROMPT[key]) prompt[key] = "";
  return {
    ...project,
    prompt,
    layers,
    selectedLayerId: layers.some(layer => layer.id === project.selectedLayerId) ? project.selectedLayerId : "",
    designReferences: project.designReferences.filter(item => !isRetiredSeed(item)),
    history: project.history.filter(item => !isRetiredSeed(item)),
  };
}

export function isRealImageSession(item) {
  if (!item || typeof item !== "object") return false;
  const provider = String(item.provider || item.providerId || "").toLowerCase();
  if (provider.includes("local composition") || provider === "local project") return false;
  const requestId = String(item.requestId || "").trim();
  const status = String(item.status || "").toLowerCase();
  const providerStatus = String(item.providerStatus || "").toLowerCase();
  if (status === 'imported' && provider === 'local file') {
    return Boolean(requestId && item.outputArtifactPath && /^[a-f0-9]{64}$/.test(item.receipt?.sourceSha256 || ''));
  }
  const traceableAnnotationSession = Boolean(
    requestId && String(item?.receipt?.promptHash || "").trim()
  );
  const persistedArtifact = [
    item.outputArtifactPath,
    item.manifestPath,
    item.manifestUrl,
    item.artifactPath,
    item.previewSrc,
  ].some(value => {
    const source = String(value || "").trim();
    return source && !source.startsWith("data:");
  });
  if (status.includes("provider_blocked") || providerStatus === "blocked") {
    return Boolean(requestId) && (provider.includes("codex") || provider.includes("openai"));
  }
  return traceableAnnotationSession || (Boolean(requestId && persistedArtifact) && (
    status.includes("generated") ||
    status.includes("edited") ||
    providerStatus === "available"
  ));
}

export function nowIso() {
  return new Date().toISOString();
}

export function makeId(prefix = "id") {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function keyboardScopeLabel(scope) {
  return scope === "queue" ? "Queue" : "History";
}

function buildKeyboardTraversalAnnouncementImplementation({
  fromScope = "history",
  fromIndex = 0,
  fromCount = 0,
  toScope = "history",
  toIndex = 0,
  toCount = 0,
  reason = "focus",
} = {}) {
  const fromText = `${keyboardScopeLabel(fromScope)} ${Math.max(0, Number(fromIndex) || 0)}/${Math.max(0, Number(fromCount) || 0)}`;
  const toText = `${keyboardScopeLabel(toScope)} ${Math.max(0, Number(toIndex) || 0)}/${Math.max(0, Number(toCount) || 0)}`;
  if (reason === "group-jump" || reason === "edge-jump") {
    return `${fromText} -> ${toText}`;
  }
  return `${toText} focused`;
}

function appendKeyboardJumpTrailImplementation(trail = [], transition = {}, options = {}) {
  const maxEntries = Math.max(1, Number(options.maxEntries) || 3);
  const nextEntry = {
    at: String(options.at || nowIso()),
    announcement: buildKeyboardTraversalAnnouncement(transition),
    fromScope: transition.fromScope || "history",
    toScope: transition.toScope || "history",
    reason: String(transition.reason || "focus"),
  };
  return [...(Array.isArray(trail) ? trail : []), nextEntry].slice(-maxEntries);
}

export function keyboardTraversalReasonLabel(reason = "focus") {
  const normalized = String(reason || "focus").toLowerCase();
  if (normalized === "group-jump") return "Scope jump";
  if (normalized === "edge-jump") return "Edge jump";
  if (normalized === "arrow") return "Arrow move";
  return "Focus";
}

function formatKeyboardJumpTrailEntryImplementation(entry = {}) {
  const label = String(entry.announcement || "").trim() || "Traversal";
  const at = entry.at;
  if (!at) return label;
  try {
    const time = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(at));
    return `${time} ${label}`;
  } catch {
    return `Recently ${label}`;
  }
}

function formatKeyboardJumpTrailTooltipImplementation(entry = {}) {
  const label = String(entry.announcement || "").trim() || "Traversal";
  const reason = keyboardTraversalReasonLabel(entry.reason);
  const at = entry.at;
  if (!at) return `${reason} • ${label}`;
  try {
    const fullTime = new Intl.DateTimeFormat(undefined, {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(new Date(at));
    return `${fullTime} • ${reason} • ${label}`;
  } catch {
    return `${reason} • ${label}`;
  }
}

// Generation is a single awaited request and history entries are only written when it
// ends, so a stored entry still marked running/queued/generating belongs to an earlier
// session that ended mid-request. It can never complete: mark it failed.
export function settleStaleHistoryItem(item) {
  const status = String(item?.status || "").toLowerCase();
  if (!/^(running|queued|pending|generating|in_progress)/.test(status)) return item;
  return {
    ...item,
    status: "failed",
    providerStatus: "blocked",
    note: "This generation was interrupted before it finished (an earlier session ended). Generate again.",
  };
}

export function normalizeProject(project) {
  const base = structuredCloneSafe(DEFAULT_IMAGE_PROJECT);
  const next = { ...base, ...(project && typeof project === "object" ? project : {}) };
  next.canvas = { ...base.canvas, ...(next.canvas || {}) };
  next.prompt = { ...base.prompt, ...(next.prompt || {}) };
  next.provider = { ...base.provider, ...(next.provider || {}) };
  next.designReferences = Array.isArray(next.designReferences) ? [...next.designReferences] : base.designReferences;
  for (const reference of base.designReferences) {
    if (!next.designReferences.some(item => item?.id === reference.id || item?.artifactId === reference.artifactId)) {
      next.designReferences.unshift(reference);
    }
  }
  next.annotationReadiness = { ...base.annotationReadiness, ...(next.annotationReadiness || {}) };
  next.skillsEvidence = Array.isArray(next.skillsEvidence) ? next.skillsEvidence : base.skillsEvidence;
  next.focusedHistoryId = String(next.focusedHistoryId || "");
  next.opsThreads = Array.isArray(next.opsThreads) ? next.opsThreads : base.opsThreads;
  next.selection = { ...base.selection, ...(next.selection || {}) };
  next.layers = Array.isArray(next.layers) ? next.layers : base.layers;
  next.history = (Array.isArray(next.history) ? next.history : base.history)
    .filter(isRealImageSession)
    .map(settleStaleHistoryItem);
  for (const item of base.history) {
    if (!next.history.some(entry => entry?.id === item.id || entry?.requestId === item.requestId)) {
      next.history.unshift(item);
    }
  }
  next.history = next.history.filter(isRealImageSession);
  next.updatedAt = next.updatedAt || nowIso();
  return withoutRetiredSeeds(next);
}

export function structuredCloneSafe(value) {
  if (typeof structuredClone === "function") {
    return structuredClone(value);
  }
  return JSON.parse(JSON.stringify(value));
}

export function loadImageProject() {
  if (typeof window === "undefined") {
    return normalizeProject();
  }
  try {
    const raw = window.localStorage.getItem(IMAGE_PLAYGROUND_STORAGE_KEY);
    return normalizeProject(raw ? JSON.parse(raw) : undefined);
  } catch {
    return normalizeProject();
  }
}

export function saveImageProject(project) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(IMAGE_PLAYGROUND_STORAGE_KEY, JSON.stringify(project));
  } catch {
    return;
  }
}

export function addHistoryEntry(project, entry) {
  const nextEntry = {
    id: makeId("hist"),
    createdAt: nowIso(),
    layerCount: project.layers.length,
    ...entry,
  };
  if (!isRealImageSession(nextEntry)) {
    return {
      ...project,
      updatedAt: nowIso(),
      history: (Array.isArray(project.history) ? project.history : []).filter(isRealImageSession),
    };
  }
  return {
    ...project,
    updatedAt: nowIso(),
    history: [nextEntry, ...(Array.isArray(project.history) ? project.history : [])]
      .filter(isRealImageSession)
      .slice(0, 40),
  };
}

function projectToProviderPayloadImplementation(project, operation = "edit", options = {}) {
  const normalized = normalizeProject(project);
  const layers = normalized.layers.map(layer => ({
    id: layer.id,
    name: layer.name,
    type: layer.type,
    visible: layer.visible,
    opacity: layer.opacity,
    blendMode: layer.blendMode,
    x: Math.round(layer.x),
    y: Math.round(layer.y),
    width: Math.round(layer.width),
    height: Math.round(layer.height),
    rotation: Number(layer.rotation || 0),
    promptRole: layer.promptRole || "",
    hasImage: Boolean(layer.src),
  }));
  const visibleLayers = layers.filter(layer => layer.visible !== false);
  return {
    operation,
    provider: normalized.provider,
    canvas: normalized.canvas,
    prompt: normalized.prompt,
    selection: normalized.selection,
    layers,
    compositionIntent: normalized.prompt.preserveComposition
      ? "Preserve the manual layer positions and selected region geometry as much as possible. Treat the canvas as the source composition for the next image operation."
      : "Use the canvas as loose visual context and allow broader reinterpretation.",
    inputs: {
      snapshotDataUrl: options.snapshotDataUrl || "",
      visibleLayerCount: visibleLayers.length,
      editRegion: {
        x: Math.round(normalized.selection.x || 0),
        y: Math.round(normalized.selection.y || 0),
        width: Math.round(normalized.selection.width || 0),
        height: Math.round(normalized.selection.height || 0),
        feather: Math.round(normalized.selection.feather || 0),
      },
    },
  };
}

function createLayerFromSelectionImplementation(project, options = {}) {
  const normalized = normalizeProject(project);
  const selection = normalized.selection || {};
  const layer = {
    id: options.id || makeId("layer-selection"),
    name: options.name || "Selected region",
    type: "shape",
    locked: false,
    visible: true,
    opacity: 0.78,
    blendMode: "screen",
    x: Math.round(selection.x || 0),
    y: Math.round(selection.y || 0),
    width: Math.max(1, Math.round(selection.width || 1)),
    height: Math.max(1, Math.round(selection.height || 1)),
    rotation: 0,
    fill: "linear-gradient(145deg, rgba(255,255,255,.58), rgba(214,168,79,.24))",
    radius: 20,
    mask: {
      feather: Math.max(0, Math.round(selection.feather || 0)),
    },
    promptRole: options.promptRole || "selected region",
  };
  return {
    ...normalized,
    selectedLayerId: layer.id,
    updatedAt: nowIso(),
    layers: [...normalized.layers, layer],
  };
}

function updateLayerInProjectImplementation(project, layerId, patch = {}) {
  const normalized = normalizeProject(project);
  return {
    ...normalized,
    updatedAt: nowIso(),
    layers: normalized.layers.map(layer => (layer.id === layerId ? { ...layer, ...patch } : layer)),
  };
}

function removeLayerFromProjectImplementation(project, layerId) {
  const normalized = normalizeProject(project);
  if (normalized.layers.length <= 1) {
    return normalized;
  }
  const nextLayers = normalized.layers.filter(layer => layer.id !== layerId);
  if (nextLayers.length === 0) {
    return normalized;
  }
  const selectedLayerId =
    normalized.selectedLayerId === layerId
      ? nextLayers[nextLayers.length - 1].id
      : normalized.selectedLayerId;
  return {
    ...normalized,
    updatedAt: nowIso(),
    layers: nextLayers,
    selectedLayerId,
  };
}

function setFocusedHistoryItemImplementation(project, historyId) {
  const normalized = normalizeProject(project);
  const nextFocusedId = String(historyId || "");
  const target = normalized.history.find(item => item.id === nextFocusedId);
  const snapshot = target?.annotationSnapshot || {
    pins: [],
    rectangles: [],
    layers: [],
    comments: [],
  };
  return {
    ...normalized,
    focusedHistoryId: target ? target.id : "",
    annotationReadiness: {
      ...normalized.annotationReadiness,
      pins: Array.isArray(snapshot.pins) ? snapshot.pins : [],
      rectangles: Array.isArray(snapshot.rectangles) ? snapshot.rectangles : [],
      layers: Array.isArray(snapshot.layers) ? snapshot.layers : [],
      comments: Array.isArray(snapshot.comments) ? snapshot.comments : [],
    },
  };
}

function updateFocusedHistoryAnnotationsImplementation(project, annotationPatch = {}) {
  const normalized = normalizeProject(project);
  const focusedHistoryId = normalized.focusedHistoryId || normalized.history[0]?.id || "";
  const nextAnnotationReadiness = {
    ...normalized.annotationReadiness,
    ...annotationPatch,
  };
  const nextHistory = normalized.history.map(item => {
    if (item.id !== focusedHistoryId) {
      return item;
    }
    return {
      ...item,
      annotationSnapshot: {
        ...(item.annotationSnapshot || {}),
        pins: Array.isArray(nextAnnotationReadiness.pins) ? nextAnnotationReadiness.pins : [],
        rectangles: Array.isArray(nextAnnotationReadiness.rectangles) ? nextAnnotationReadiness.rectangles : [],
        layers: Array.isArray(nextAnnotationReadiness.layers) ? nextAnnotationReadiness.layers : [],
        comments: Array.isArray(nextAnnotationReadiness.comments) ? nextAnnotationReadiness.comments : [],
      },
    };
  });
  return {
    ...normalized,
    focusedHistoryId,
    updatedAt: nowIso(),
    annotationReadiness: nextAnnotationReadiness,
    history: nextHistory,
  };
}

function createOpsThreadForFocusedHistoryImplementation(project, options = {}) {
  const normalized = normalizeProject(project);
  const focusedHistoryId = normalized.focusedHistoryId || normalized.history[0]?.id || "";
  if (!focusedHistoryId) {
    return normalized;
  }
  const focused = normalized.history.find(item => item.id === focusedHistoryId);
  const requestId = focused?.requestId || "pending-request-id";
  const receiptHash = focused?.receipt?.promptHash || "unknown";
  const threadId = focused?.issueThread?.id || `${receiptHash}:${requestId}`;
  const existing = normalized.opsThreads.find(thread => thread.id === threadId);
  const stamp = nowIso();
  const threadRecord = existing || {
    id: threadId,
    historyId: focusedHistoryId,
    requestId,
    receiptHash,
    title: options.title || `Image Playground issue ${threadId}`,
    status: "open",
    createdAt: stamp,
    updatedAt: stamp,
    messages: [],
  };
  const opsThreads = existing
    ? normalized.opsThreads.map(thread => (thread.id === threadId ? { ...thread, updatedAt: stamp } : thread))
    : [threadRecord, ...normalized.opsThreads];
  const history = normalized.history.map(item => (
    item.id === focusedHistoryId
      ? {
          ...item,
          issueThread: {
            id: threadId,
            requestId,
            receiptHash,
            href: `#issue-thread-${encodeURIComponent(threadId)}`,
            status: "open",
            syncedAt: stamp,
          },
        }
      : item
  ));
  return {
    ...normalized,
    focusedHistoryId,
    updatedAt: stamp,
    opsThreads,
    history,
    annotationReadiness: {
      ...normalized.annotationReadiness,
      activeThreadRef: threadId,
    },
  };
}

checkImagePromptPresets(IMAGE_PROMPT_PRESETS);

export function projectToProviderPayload(project, ...args) { const normalized = normalizeProject(project); return checkedImageAction('projectToProviderPayload', [normalized, ...args], projectToProviderPayloadImplementation(normalized, ...args)); }

export function createLayerFromSelection(project, ...args) { const normalized = normalizeProject(project); return checkedImageAction('createLayerFromSelection', [normalized, ...args], createLayerFromSelectionImplementation(normalized, ...args)); }

export function updateLayerInProject(project, ...args) { const normalized = normalizeProject(project); return checkedImageAction('updateLayerInProject', [normalized, ...args], updateLayerInProjectImplementation(normalized, ...args)); }

export function removeLayerFromProject(project, ...args) { const normalized = normalizeProject(project); return checkedImageAction('removeLayerFromProject', [normalized, ...args], removeLayerFromProjectImplementation(normalized, ...args)); }

export function setFocusedHistoryItem(project, ...args) { const normalized = normalizeProject(project); return checkedImageAction('setFocusedHistoryItem', [normalized, ...args], setFocusedHistoryItemImplementation(normalized, ...args)); }

export function updateFocusedHistoryAnnotations(project, ...args) { const normalized = normalizeProject(project); return checkedImageAction('updateFocusedHistoryAnnotations', [normalized, ...args], updateFocusedHistoryAnnotationsImplementation(normalized, ...args)); }

export function createOpsThreadForFocusedHistory(project, ...args) { const normalized = normalizeProject(project); return checkedImageAction('createOpsThreadForFocusedHistory', [normalized, ...args], createOpsThreadForFocusedHistoryImplementation(normalized, ...args)); }

export function buildKeyboardTraversalAnnouncement(...args) { return checkedImageAction('buildKeyboardTraversalAnnouncement', args, buildKeyboardTraversalAnnouncementImplementation(...args)); }

export function appendKeyboardJumpTrail(...args) { return checkedImageAction('appendKeyboardJumpTrail', args, appendKeyboardJumpTrailImplementation(...args)); }

export function formatKeyboardJumpTrailEntry(...args) { return checkedImageAction('formatKeyboardJumpTrailEntry', args, formatKeyboardJumpTrailEntryImplementation(...args)); }

export function formatKeyboardJumpTrailTooltip(...args) { return checkedImageAction('formatKeyboardJumpTrailTooltip', args, formatKeyboardJumpTrailTooltipImplementation(...args)); }
