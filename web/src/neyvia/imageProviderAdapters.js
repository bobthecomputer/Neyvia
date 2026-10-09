import { checkedImageAction } from "./imagePlaygroundContracts.js";
import { addHistoryEntry, makeId, nowIso, projectToProviderPayload } from "./imagePlaygroundState.js";

export const QUEUE_TIMELINE_STAGES = [
  "queued",
  "provider accepted",
  "generating",
  "artifact written",
  "layer handoff",
  "verified",
];

// The backend stops its own generation at 300s; the UI gives up shortly after
// so the spinner can never outlive the request.
const IMAGE_REQUEST_DEADLINE_MS = 330000;

const BUILT_IN_IMAGE_PROVIDER_ADAPTERS = [
  {
    id: "codex-gpt-image2",
    name: "OpenAI GPT-Image-2",
    model: "gpt-image-2",
    statusLabel: "OpenAI image route",
    description:
      "Generates through the Codex app's own image tool on this PC (needs a Codex sign-in) and shows the real error, with what to do, when it cannot.",
    capabilities: ["generate", "edit", "composition", "region", "variations"],
    async request({ project, operation, payload, callBackend }) {
      if (typeof callBackend !== "function") {
        return {
          kind: "provider-blocked",
          status: "unavailable",
          provider: "OpenAI GPT-Image-2",
          providerId: "codex-gpt-image2",
          model: "gpt-image-2",
          route: "codex_subscription",
          blockedReason: "backend_unavailable",
          message: "Live backend is required for GPT-Image-2 generation.",
          details: {},
          meta: {},
        };
      }
      try {
        let deadlineTimer = 0;
        const deadline = new Promise((_, reject) => {
          deadlineTimer = setTimeout(
            () => reject(new Error(`Image generation did not answer within ${IMAGE_REQUEST_DEADLINE_MS / 1000} seconds. Check that Codex is signed in (run "codex login status" in a terminal) and try again.`)),
            IMAGE_REQUEST_DEADLINE_MS,
          );
        });
        let response;
        try {
          response = await Promise.race([
            callBackend("image_playground_operation_command", payload, { throwOnError: true }),
            deadline,
          ]);
        } finally {
          clearTimeout(deadlineTimer);
        }
        if (response?.layer) {
          return {
            kind: "provider",
            provider: response.providerName || response.receipt?.providerName || "OpenAI GPT-Image-2",
            message: response.message || "Provider returned an editable layer.",
            layer: normalizeGeneratedLayer(response.layer, project),
            meta: {
              ...response,
              providerStatus: response.providerStatus || "available",
              outputArtifactPath: response.outputArtifactPath || response.imagePath || "",
              receipt: response.receipt || {},
            },
          };
        }
        if (response?.status === "unavailable") {
          return {
            kind: "provider-blocked",
            status: "unavailable",
            provider: response.providerName || response.provider || "OpenAI GPT-Image-2",
            providerId: response.providerId || "codex-gpt-image2",
            model: response.model || "gpt-image-2",
            route: response.route || "codex_subscription",
            blockedReason: response.blockedReason || "provider_unavailable",
            message: response.message || "GPT-Image-2 is not available in this runtime yet.",
            details: response.details || {},
            meta: response,
          };
        }
      } catch (error) {
        return {
          kind: "provider-blocked",
          status: "failed",
          provider: "OpenAI GPT-Image-2",
          providerId: "codex-gpt-image2",
          model: "gpt-image-2",
          route: "codex_subscription",
          blockedReason: "provider_request_failed",
          message: String(error?.message || error || "Provider request failed."),
          details: {},
          meta: { error: String(error?.message || error || "Provider request failed.") },
        };
      }
      return {
        kind: "provider-blocked",
        status: "failed",
        provider: "OpenAI GPT-Image-2",
        providerId: "codex-gpt-image2",
        model: "gpt-image-2",
        route: "codex_subscription",
        blockedReason: "missing_editable_layer",
        message: "GPT-Image-2 backend did not return an editable layer.",
        details: {},
        meta: {},
      };
    },
  },
  {
    id: "local-composition-draft",
    name: "Local composition draft",
    model: "canvas-only",
    statusLabel: "Offline fallback",
    description:
      "Creates editable draft layers locally so the canvas workflow remains usable without a remote image provider.",
    capabilities: ["generate", "edit", "composition", "region"],
    async request({ project, operation }) {
      return createLocalDraftResult(
        project,
        operation,
        "Using local composition draft. Connect the OpenAI GPT-Image-2 route when auth and runtime transport are configured.",
      );
    },
  },
];

const imageProviderRegistry = [...BUILT_IN_IMAGE_PROVIDER_ADAPTERS];

export const IMAGE_PROVIDER_ADAPTERS = imageProviderRegistry;

function tinyHash(value) {
  const source = String(value || "");
  let hash = 2166136261;
  for (let index = 0; index < source.length; index += 1) {
    hash ^= source.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return Math.abs(hash >>> 0).toString(16).padStart(8, "0").slice(0, 8);
}

export function buildIssueThreadRef(receiptHash, requestId) {
  const hash = String(receiptHash || "unknown").trim() || "unknown";
  const request = String(requestId || "pending-request-id").trim() || "pending-request-id";
  return `${hash}:${request}`;
}

export function snapshotOverlayAnnotations(project, threadRef = "") {
  const source = project?.annotationReadiness || {};
  const normalizePoint = pin => ({
    id: pin?.id || makeId("pin"),
    x: Number(pin?.x || 0),
    y: Number(pin?.y || 0),
    comment: String(pin?.comment || ""),
    threadRef: pin?.threadRef || threadRef || "",
  });
  const normalizeRect = rect => ({
    id: rect?.id || makeId("rect"),
    x: Number(rect?.x || 0),
    y: Number(rect?.y || 0),
    width: Number(rect?.width || rect?.w || 0),
    height: Number(rect?.height || rect?.h || 0),
    comment: String(rect?.comment || ""),
    threadRef: rect?.threadRef || threadRef || "",
  });
  return {
    canvasWidth: Number(project?.canvas?.width || 1),
    canvasHeight: Number(project?.canvas?.height || 1),
    pins: Array.isArray(source.pins) ? source.pins.map(normalizePoint).slice(0, 24) : [],
    rectangles: Array.isArray(source.rectangles) ? source.rectangles.map(normalizeRect).slice(0, 24) : [],
  };
}

function registerImageProviderAdapterImplementation(adapter) {
  if (!adapter || typeof adapter !== "object") {
    throw new TypeError("Image provider adapter must be an object.");
  }
  const id = String(adapter.id || "").trim();
  if (!id) {
    throw new TypeError("Image provider adapter requires an id.");
  }
  if (imageProviderRegistry.some(provider => provider.id === id)) {
    throw new Error(`Image provider adapter already registered: ${id}`);
  }
  const request = typeof adapter.request === "function"
    ? adapter.request
    : async ({ project, operation }) => createLocalDraftResult(project, operation, `${adapter.name || id} has no request transport configured yet.`);
  const normalized = {
    statusLabel: "Provider adapter",
    description: "Modular image provider adapter.",
    capabilities: [],
    ...adapter,
    id,
    request,
  };
  imageProviderRegistry.push(normalized);
  return normalized;
}

export function getProviderAdapter(providerId) {
  return imageProviderRegistry.find(provider => provider.id === providerId) || imageProviderRegistry[0];
}

async function requestProviderOperationImplementation(project, operation, { callBackend, imagePluginMode = false, snapshotDataUrl } = {}) {
  const basePayload = projectToProviderPayload(project, operation);
  const requestId = makeId("imgreq");
  const queuedAt = nowIso();
  const payload = {
    ...basePayload,
    requestId,
    snapshotDataUrl,
    ...(imagePluginMode
      ? {
          skillInvocation: {
            skillId: "imagegen",
            mode: "installed-skill",
            requireReceipt: true,
          },
        }
      : {}),
    inputs: {
      ...(basePayload.inputs || {}),
      snapshotDataUrl: snapshotDataUrl || "",
    },
  };
  const adapter = getProviderAdapter(project.provider.id);
  const startedAt = nowIso();
  const result = await adapter.request({ project, operation, payload, callBackend, snapshotDataUrl });
  const completedAt = nowIso();
  const requestTimeline = {
    queuedAt,
    startedAt: queuedAt,
    completedAt,
    durationMs: Math.max(0, new Date(completedAt).getTime() - new Date(queuedAt).getTime()),
  };
  const mergedMeta = {
    ...(result?.meta || {}),
    requestId: result?.meta?.requestId || requestId,
    providerStatus: result?.meta?.providerStatus || (result?.kind === "provider" ? "available" : result?.kind === "provider-blocked" ? "blocked" : "fallback"),
    outputArtifactPath: result?.meta?.outputArtifactPath || "",
    requestTimeline: {
      ...requestTimeline,
      ...(result?.meta?.requestTimeline || {}),
    },
    queueTimeline: result?.meta?.queueTimeline || buildQueueTimeline({
      queuedAt,
      startedAt,
      completedAt,
      outcome: result?.kind === "provider" ? "done" : result?.kind === "provider-blocked" ? "failed" : "draft",
    }),
    layerHandoff: {
      layerId: result?.layer?.id || "",
      layerName: result?.layer?.name || "",
      stage: result?.layer ? "layer_ready" : "no_layer",
      at: completedAt,
      ...(result?.meta?.layerHandoff || {}),
    },
  };
  const promptHash = mergedMeta?.receipt?.promptHash || tinyHash(project?.prompt?.text || payload?.prompt?.text || "");
  mergedMeta.receipt = {
    ...(mergedMeta.receipt || {}),
    promptHash,
  };
  if (mergedMeta.providerStatus !== "available") {
    mergedMeta.receipt = {
      ...mergedMeta.receipt,
      failureReason:
        mergedMeta.receipt.failureReason ||
        result?.blockedReason ||
        "OpenAI image route unavailable: set OPENAI_API_KEY or FLUXIO_GPT_IMAGE2_COMMAND",
      promptEvidence: project?.prompt?.text || "",
      specEvidence: payload?.compositionIntent || "",
    };
  }

  if (result?.layer) {
    return {
      ...result,
      provider: result.provider || adapter.name,
      layer: normalizeGeneratedLayer(result.layer, project),
      meta: mergedMeta,
    };
  }

  const fallbackResult = result || createLocalDraftResult(project, operation, `${adapter.name} did not return an editable layer.`);
  return {
    ...fallbackResult,
    meta: {
      ...mergedMeta,
      ...(fallbackResult?.meta || {}),
    },
  };
}

function normalizeGeneratedLayer(layer, project) {
  return {
    id: layer.id || makeId("layer-provider"),
    name: layer.name || "Provider result",
    type: layer.src ? "image" : "shape",
    visible: true,
    locked: false,
    opacity: 1,
    blendMode: "normal",
    x: Number(layer.x ?? 0),
    y: Number(layer.y ?? 0),
    width: Number(layer.width ?? project.canvas.width),
    height: Number(layer.height ?? project.canvas.height),
    rotation: Number(layer.rotation || 0),
    src: layer.src || "",
    fill: layer.fill || "linear-gradient(135deg, rgba(255,255,255,.26), rgba(214,168,79,.22))",
    radius: layer.radius || 24,
    promptRole: layer.promptRole || "provider output",
  };
}

export function buildQueueTimeline({ queuedAt, startedAt, completedAt, outcome = "done" }) {
  if (outcome === "failed") {
    // A failed request never reached later stages; do not time-stamp them.
    return [
      { stage: "queued", at: queuedAt, severity: "info", recoveryAction: "Monitor queue" },
      { stage: "provider accepted", at: "", severity: "info", recoveryAction: "Check provider status" },
      { stage: "generating", at: "", severity: "info", recoveryAction: "Retry generation" },
      { stage: "artifact written", at: "", severity: "info", recoveryAction: "Retry generation" },
      { stage: "layer handoff", at: "", severity: "info", recoveryAction: "Retry generation" },
      { stage: "verified", at: completedAt, severity: "bad", recoveryAction: "Read the error above, then retry" },
    ];
  }
  return [
    { stage: "queued", at: queuedAt, severity: "info", recoveryAction: "Monitor queue" },
    { stage: "provider accepted", at: startedAt, severity: "info", recoveryAction: "Check provider status" },
    { stage: "generating", at: startedAt, severity: "info", recoveryAction: "Wait for generation" },
    { stage: "artifact written", at: completedAt, severity: "info", recoveryAction: "Open artifact preview" },
    { stage: "layer handoff", at: completedAt, severity: "info", recoveryAction: "Apply output as layer" },
    { stage: "verified", at: completedAt, severity: "good", recoveryAction: "Publish receipt evidence" },
  ];
}

export function createLocalDraftResult(project, operation, message) {
  const selected = project.layers.find(layer => layer.id === project.selectedLayerId) || project.layers[1] || project.layers[0];
  const palette = operation === "edit" ? ["#f4f0e8", "#d6a84f", "#8ecb6f"] : ["#93c5fd", "#d6a84f", "#f4f0e8"];
  const svg = encodeSvgDataUrl(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${project.canvas.width} ${project.canvas.height}">
      <defs>
        <linearGradient id="g" x1="0" x2="1" y1="0" y2="1">
          <stop stop-color="${palette[0]}" stop-opacity="0.94"/>
          <stop offset="0.52" stop-color="${palette[1]}" stop-opacity="0.68"/>
          <stop offset="1" stop-color="${palette[2]}" stop-opacity="0.46"/>
        </linearGradient>
        <radialGradient id="halo" cx="50%" cy="35%" r="55%">
          <stop stop-color="#ffffff" stop-opacity="0.58"/>
          <stop offset="1" stop-color="#ffffff" stop-opacity="0"/>
        </radialGradient>
      </defs>
      <rect width="100%" height="100%" fill="#111313"/>
      <rect x="96" y="104" width="${project.canvas.width - 192}" height="${project.canvas.height - 208}" rx="72" fill="url(#g)" opacity="0.84"/>
      <circle cx="${project.selection.x + project.selection.width / 2}" cy="${project.selection.y + project.selection.height / 2}" r="${Math.max(project.selection.width, project.selection.height) * 0.62}" fill="url(#halo)"/>
      <rect x="${selected?.x || 300}" y="${selected?.y || 300}" width="${selected?.width || 260}" height="${selected?.height || 220}" rx="38" fill="#ffffff" opacity="0.18" stroke="#ffffff" stroke-opacity="0.42"/>
      <text x="50%" y="88%" text-anchor="middle" font-family="Inter, system-ui, sans-serif" font-size="28" fill="#f4f0e8" opacity="0.72">Composition draft · ${operation}</text>
    </svg>
  `);
  return {
    kind: "local-draft",
    provider: "Local composition draft",
    message,
    layer: {
      id: makeId("layer-draft"),
      name: operation === "edit" ? "Edited composition draft" : "Generated composition draft",
      type: "image",
      visible: true,
      locked: false,
      opacity: 0.92,
      blendMode: "normal",
      x: 0,
      y: 0,
      width: project.canvas.width,
      height: project.canvas.height,
      rotation: 0,
      src: svg,
      promptRole: "draft output from modular provider adapter",
    },
  };
}

function applyProviderResultImplementation(project, result, operation) {
  const nextLayers = result.layer ? [...project.layers, result.layer] : project.layers;
  const nextProject = {
    ...project,
    selectedLayerId: result.layer?.id || project.selectedLayerId,
    layers: nextLayers,
    updatedAt: nowIso(),
  };
  const receiptHash = result?.meta?.receipt?.promptHash || tinyHash(project.prompt.text || "");
  const requestId = result?.meta?.requestId || "pending-request-id";
  const threadRef = buildIssueThreadRef(receiptHash, requestId);
  const annotationSnapshot = snapshotOverlayAnnotations(project, threadRef);
  return addHistoryEntry(nextProject, {
    title: operation === "edit" ? "Composition edit" : "Image generation",
    prompt: project.prompt.text,
    provider: result.provider,
    providerId: project.provider.id,
    status: result.kind === "provider" ? "generated" : result.kind === "provider-blocked" ? "provider_blocked" : "fallback_draft",
    note: result.message,
    requestId: result?.meta?.requestId || "",
    providerStatus: result?.meta?.providerStatus || (result.kind === "provider" ? "available" : result.kind === "provider-blocked" ? "blocked" : "fallback"),
    outputArtifactPath: result?.meta?.outputArtifactPath || "",
    requestTimeline: result?.meta?.requestTimeline || {},
    queueTimeline: result?.meta?.queueTimeline || [],
    layerHandoff: result?.meta?.layerHandoff || {},
    receipt: result?.meta?.receipt || {},
    annotationSnapshot,
    issueThread: {
      id: threadRef,
      requestId,
      receiptHash,
      href: `#issue-thread-${encodeURIComponent(threadRef)}`,
    },
  });
}

function encodeSvgDataUrl(svg) {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg.replace(/\s+/g, " ").trim())}`;
}

export function registerImageProviderAdapter(adapter) {
  const before = imageProviderRegistry.map(row => row.id);
  return checkedImageAction("registerImageProviderAdapter", [adapter, before], registerImageProviderAdapterImplementation(adapter));
}

export async function requestProviderOperation(...args) {
  return checkedImageAction("requestProviderOperation", args, await requestProviderOperationImplementation(...args));
}

export function applyProviderResult(...args) {
  return checkedImageAction("applyProviderResult", args, applyProviderResultImplementation(...args));
}
