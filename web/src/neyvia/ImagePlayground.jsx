import { useEffect, useMemo, useRef, useState } from "react";
import "./imagePlaygroundScoped.css";
import {
  Blend,
  Boxes,
  BringToFront,
  Check,
  ChevronsUpDown,
  Crop,
    Eye,
  EyeOff,
  ImagePlus,
  Layers3,
  Lock,
    Move,
  Plus,
  RefreshCw,
  Scissors,
  Sparkles,
  SplitSquareHorizontal,
  WandSparkles,
} from "lucide-react";

import {
  CANVAS_SIZE_PRESETS,
  DEFAULT_IMAGE_PROJECT,
  IMAGE_TOOL_DEFINITIONS,
  addHistoryEntry,
  appendKeyboardJumpTrail,
  buildKeyboardTraversalAnnouncement,
  createOpsThreadForFocusedHistory,
  formatKeyboardJumpTrailEntry,
  formatKeyboardJumpTrailTooltip,
  isRealImageSession,
  keyboardScopeLabel,
  loadImageProject,
  makeId,
  normalizeProject,
  nowIso,
  saveImageProject,
  setFocusedHistoryItem,
  structuredCloneSafe,
  updateFocusedHistoryAnnotations,
} from "./imagePlaygroundState.js";
import {
  IMAGE_PROVIDER_ADAPTERS,
  QUEUE_TIMELINE_STAGES,
  applyProviderResult,
  buildIssueThreadRef,
  getProviderAdapter,
  requestProviderOperation,
} from "./imageProviderAdapters.js";

function cx(...values) {
  return values.filter(Boolean).join(" ");
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, Number(value) || 0));
}

function formatTime(value) {
  if (!value) return "Just now";
  try {
    return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
  } catch {
    return "Recently";
  }
}

function formatDateTime(value) {
  if (!value) return "Not recorded";
  try {
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(value));
  } catch {
    return "Not recorded";
  }
}


function queueTimelineFromItem(item, fallbackTimestamp = "") {
  if (item?.status === "imported" && item.provider === "local file") {
    return [{ stage: "opened source", at: item.createdAt || "", severity: "info", recoveryAction: "Review source image" }];
  }
  const source = Array.isArray(item?.queueTimeline) && item.queueTimeline.length
    ? item.queueTimeline
    : QUEUE_TIMELINE_STAGES.map(stage => ({ stage, at: item?.requestTimeline?.completedAt || item?.requestTimeline?.queuedAt || fallbackTimestamp || "", severity: "info", recoveryAction: "Review evidence" }));
  return QUEUE_TIMELINE_STAGES.map(stageName => (
    source.find(entry => String(entry.stage || "").toLowerCase() === stageName) || {
      stage: stageName,
      at: "",
      severity: stageName === "verified" ? "warn" : "info",
      recoveryAction: "Retry generation",
    }
  ));
}

function tinyPromptHash(value) {
  const source = String(value || "");
  let hash = 2166136261;
  for (let index = 0; index < source.length; index += 1) {
    hash ^= source.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return Math.abs(hash >>> 0).toString(16).padStart(8, "0").slice(0, 8);
}

function shortHash(value) {
  const source = String(value || "").trim();
  if (!source) return "n/a";
  if (source.length <= 16) return source;
  return `${source.slice(0, 8)}…${source.slice(-8)}`;
}

function artifactBackendBaseUrl() {
  const configured =
    import.meta.env?.VITE_FLUXIO_BACKEND_URL ||
    globalThis.window?.__FLUXIO_BACKEND_URL__ ||
    "";
  return String(configured || "").trim().replace(/\/$/, "");
}

function resolveArtifactUrl(value) {
  const source = String(value || "").trim();
  if (!source) return "";
  if (/^(data:|blob:|https?:\/\/)/i.test(source)) return source;
  if (source.startsWith("/api/artifact")) return `${artifactBackendBaseUrl()}${source}`;
  const params = new URLSearchParams({ path: source });
  return `${artifactBackendBaseUrl()}/api/artifact?${params.toString()}`;
}

/**
 * A library thumbnail that is honest about loading: a soft shimmer while the file arrives, the
 * picture fading in once decoded, and a quiet card saying the file isn't on this PC when it can't
 * be read (receipts can outlive their images).
 */
export function ArtifactThumb({ src, alt, onMissing }) {
  const [state, setState] = useState(src ? "loading" : "missing");
  useEffect(() => { setState(src ? "loading" : "missing"); }, [src]);
  useEffect(() => { if (state === "missing") onMissing?.(); }, [state]);
  return (
    <div className="image-thumb" data-state={state}>
      {src && state !== "missing" ? (
        <img alt={alt} src={src} loading="lazy" decoding="async" onLoad={() => setState("ready")} onError={() => setState("missing")} />
      ) : null}
      {state === "missing" ? (
        <span className="image-thumb-missing">
          <svg aria-hidden="true" viewBox="0 0 64 44" width="64" height="44"><rect x="1" y="1" width="62" height="42" rx="5" fill="none" stroke="currentColor" strokeOpacity=".35" /><circle cx="46" cy="13" r="5" fill="currentColor" fillOpacity=".35" /><path d="M4 38 L22 18 L34 30 L42 23 L60 38 Z" fill="currentColor" fillOpacity=".22" /></svg>
          <small>Image file not on this PC</small>
        </span>
      ) : null}
    </div>
  );
}

function imageSourceForRecord(record) {
  return resolveArtifactUrl(
    record?.artifactUrl ||
      record?.previewUrl ||
      record?.generatedPreview ||
      record?.previewSrc ||
      record?.outputPreview ||
      record?.imagePath ||
      record?.outputArtifactPath ||
      record?.artifactPath ||
      "",
  );
}

/** Where an image came from, in words: "Made with Codex", "Imported"; nothing when unknown. */
function friendlyImageSource(record) {
  const source = [record?.provider, record?.providerId, record?.source].map(value => String(value || "").toLowerCase()).join(" ");
  if (source.includes("local file") || String(record?.status || "").toLowerCase() === "imported") return "Imported";
  if (source.includes("codex")) return "Made with Codex";
  if (source.includes("gpt-image") || source.includes("openai")) return "Made with GPT Image";
  return "";
}

/** A library card's title: what the user asked for, else the record's own title. */
function libraryTitle(record) {
  const prompt = String(record?.prompt || "").trim();
  return prompt || String(record?.title || "").trim() || "Untitled image";
}

function manifestUrlForRecord(record) {
  return resolveArtifactUrl(record?.manifestUrl || record?.manifestPath || "");
}

function providerRouteFromReceipt(receipt) {
  const route = String(receipt?.route || receipt?.fallback || "").trim();
  return route || "Unknown";
}

function canvasLayerStyle(layer, selected) {
  return {
    left: `${layer.x}px`,
    top: `${layer.y}px`,
    width: `${layer.width}px`,
    height: `${layer.height}px`,
    opacity: layer.opacity ?? 1,
    mixBlendMode: layer.blendMode || "normal",
    transform: `rotate(${layer.rotation || 0}deg)`,
    borderRadius: `${layer.radius ?? (layer.type === "shape" ? 24 : 12)}px`,
    background: layer.type === "shape" ? layer.fill : "transparent",
    outline: selected ? "2px solid var(--nx-accent)" : "1px solid color-mix(in srgb, var(--nx-text) 6%, transparent)",
  };
}

function normalizeOverlaySnapshot(snapshot) {
  return {
    canvasWidth: Number(snapshot?.canvasWidth || 1),
    canvasHeight: Number(snapshot?.canvasHeight || 1),
    pins: Array.isArray(snapshot?.pins) ? snapshot.pins : [],
    rectangles: Array.isArray(snapshot?.rectangles) ? snapshot.rectangles : [],
  };
}

function renderOverlayShapes(snapshot, scope = "canvas") {
  const normalized = normalizeOverlaySnapshot(snapshot);
  const xValue = value => (scope === "canvas" ? `${value}px` : `${(Number(value || 0) / normalized.canvasWidth) * 100}%`);
  const yValue = value => (scope === "canvas" ? `${value}px` : `${(Number(value || 0) / normalized.canvasHeight) * 100}%`);
  return (
    <>
      {normalized.rectangles.map(rect => (
        <div
          className={cx("image-annotation-rect", scope)}
          key={`rect-${scope}-${rect.id || `${rect.x}-${rect.y}`}`}
          style={{
            left: xValue(rect.x),
            top: yValue(rect.y),
            width: xValue(rect.width),
            height: yValue(rect.height),
          }}
          title={rect.comment || "Annotation region"}
        />
      ))}
      {normalized.pins.map((pin, index) => (
        <div
          className={cx("image-annotation-pin", scope)}
          key={`pin-${scope}-${pin.id || `${pin.x}-${pin.y}-${index}`}`}
          style={{ left: xValue(pin.x), top: yValue(pin.y) }}
          title={pin.comment || "Annotation pin"}
        >
          <span>{index + 1}</span>
        </div>
      ))}
    </>
  );
}

const SKILL_RECOMMENDATIONS = [
  {
    id: "brand-typography-system",
    title: "Brand-ready typography system",
    track: "Design skill",
    reason: "Improves readability and visual consistency across Image Playground and chat notifications.",
  },
  {
    id: "mobile-gesture-safe-zones",
    title: "Mobile gesture-safe zones",
    track: "Front-end skill",
    reason: "Prevents accidental canvas drags and keeps controls tappable on small screens.",
  },
  {
    id: "prompt-version-diffing",
    title: "Prompt version diffing",
    track: "Agent workflow",
    reason: "Makes generation changes auditable before review and test gates.",
  },
];

const DESIGN_DECISION_MATRIX = [
  {
    id: "artifact-hierarchy",
    title: "Evidence-first hierarchy",
    usedArtifact: "Codex generated live-review reference",
    appliedDecision: "Promote receipt, queue, and issue-thread evidence before decorative controls.",
    skillImplication: "Design-taste prompts must cite the artifact receipt and explain what changed.",
    mobileCheck: "Cards collapse to one column and keep primary actions thumb-safe.",
  },
  {
    id: "annotation-density",
    title: "Annotation density guardrail",
    usedArtifact: "Layered playground overlay study",
    appliedDecision: "Keep pins, rectangles, queue chips, and status copy in separate evidence bands.",
    skillImplication: "Skill drafts require verifier/test gates before publish.",
    mobileCheck: "Horizontal overflow is avoided except deliberate chip rails.",
  },
];

const DRAFT_STATE_LABELS = {
  draft: "Draft",
  review: "Review",
  test: "Test",
  published: "Published",
};

const KEYBOARD_JUMP_TRAIL_LIMIT = 3;
const KEYBOARD_JUMP_TRAIL_IDLE_MS = 30000;

export function ImagePlaygroundSurface({ callBackend, nativeAsset, onNativeImageState, readOnly = false }) {
  const [project, setProject] = useState(() => loadImageProject());
  const [nativeDecoded, setNativeDecoded] = useState(null);
  const nativeImageRef = useRef(null);
  useEffect(() => {
    if (!nativeAsset?.id || nativeDecoded !== nativeAsset.id) return;
    const report = () => {
      const image = nativeImageRef.current;
      const rect = image?.getBoundingClientRect();
      let left = Math.max(0, rect?.left ?? 0), top = Math.max(0, rect?.top ?? 0);
      let right = Math.min(innerWidth, rect?.right ?? 0), bottom = Math.min(innerHeight, rect?.bottom ?? 0);
      let shown = Boolean(image?.complete && image.naturalWidth > 0);
      for (let parent = image; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent), box = parent.getBoundingClientRect();
        if (style.display === 'none' || style.visibility === 'hidden') shown = false;
        if (/(auto|scroll|hidden|clip)/.test(style.overflowX)) { left = Math.max(left, box.left); right = Math.min(right, box.right); }
        if (/(auto|scroll|hidden|clip)/.test(style.overflowY)) { top = Math.max(top, box.top); bottom = Math.min(bottom, box.bottom); }
      }
      onNativeImageState?.({ status: shown && right > left && bottom > top ? 'ready' : 'hidden', assetId: nativeAsset.id, zoom: project.canvas.zoom });
    };
    report(); const heartbeat = setInterval(report, 2000);
    return () => { clearInterval(heartbeat); onNativeImageState?.({ status: 'closed', assetId: nativeAsset.id }); };
  }, [nativeAsset?.id, nativeDecoded, project.canvas.zoom, onNativeImageState]);
  useEffect(() => {
    if (!nativeAsset?.id || !nativeAsset.url) return;
    updateProject(current => {
      const existing = current.layers.find(layer => layer.nativeAssetId === nativeAsset.id);
      if (existing) return { ...current, selectedLayerId: existing.id,
        layers: current.layers.map(layer => layer.nativeAssetId ? { ...layer, visible: layer.nativeAssetId === nativeAsset.id } : layer) };
      const width = nativeAsset.dimensions.width, height = nativeAsset.dimensions.height;
      const scale = Math.min(1, 620 / width, 620 / height);
      const layer = { id: makeId('layer-agent'), nativeAssetId: nativeAsset.id,
        name: nativeAsset.path.split(/[\\/]/).pop(), type: 'image', src: nativeAsset.url,
        locked: false, visible: true, opacity: 1, blendMode: 'normal',
        x: (current.canvas.width - width * scale) / 2, y: (current.canvas.height - height * scale) / 2,
        width: width * scale, height: height * scale, rotation: 0, promptRole: 'agent opened source image' };
      return addHistoryEntry({ ...current, selectedLayerId: layer.id,
        layers: [...current.layers.map(row => row.nativeAssetId ? { ...row, visible: false } : row), layer], updatedAt: nowIso() },
        { title: 'Opened agent image', prompt: layer.name, provider: 'local file', status: 'imported',
          requestId: nativeAsset.id, outputArtifactPath: nativeAsset.path, artifactUrl: nativeAsset.url,
          layerHandoff: { stage: 'opened source' }, receipt: { sourceSha256: nativeAsset.sha256, route: 'local file' } });
    });
  }, [nativeAsset?.id]);
  const [busy, setBusy] = useState(false);
  const [editorOpen, setEditorOpen] = useState(() => project.layers.length > 0 || Boolean(nativeAsset?.id));
  const editorRef = useRef(null);
  useEffect(() => { if (nativeAsset?.id) setEditorOpen(true); }, [nativeAsset?.id]);
  const [providerMessage, setProviderMessage] = useState("");
  const [providerBlockedState, setProviderBlockedState] = useState(null);
  const [compareHistoryId, setCompareHistoryId] = useState(project.history[0]?.id || "");
  const [dragState, setDragState] = useState(null);
  const [activeAnnotationTarget, setActiveAnnotationTarget] = useState({ kind: "", id: "" });
  const [annotationLegendCollapsed, setAnnotationLegendCollapsed] = useState(true);
  const [annotationOnboardingDismissed, setAnnotationOnboardingDismissed] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem("image-playground-annotation-onboarding-dismissed") === "1";
  });
  const [skillDrafts, setSkillDrafts] = useState(() => ([
    {
      id: makeId("skill-draft"),
      title: "Layer-aware art direction helper",
      summary: "Agent proposes a reusable style-check skill before generation so layers stay coherent.",
      state: "draft",
      recommendationId: "prompt-version-diffing",
      reviewerSignedOff: false,
      updatedAt: nowIso(),
    },
  ]));
  const [activeReadinessDraftId, setActiveReadinessDraftId] = useState("");
  const [skillNotice, setSkillNotice] = useState("Agent can propose a new skill draft from each validated generation slice.");
  const [operationEvents, setOperationEvents] = useState(() => ([
    {
      id: makeId("event"),
      title: "Workspace ready",
      detail: "Load a background, then run Generate or Continue from adjusted composition.",
      tone: "info",
      createdAt: nowIso(),
    },
  ]));
  const [collapsedOutcomeIds, setCollapsedOutcomeIds] = useState(() => new Set());
  const [activeOpsThreadId, setActiveOpsThreadId] = useState("");
  const [handoffStateByDraftId, setHandoffStateByDraftId] = useState({});
  const [keyboardTraversalAnnouncement, setKeyboardTraversalAnnouncement] = useState("");
  const [keyboardJumpTrail, setKeyboardJumpTrail] = useState([]);
  const [activeJumpTrailChipId, setActiveJumpTrailChipId] = useState("");
  const [activeJumpTrailTooltip, setActiveJumpTrailTooltip] = useState("");
  const lastTraversalAnnouncementRef = useRef("");
  const jumpTrailLongPressRef = useRef(null);
  const canvasRef = useRef(null);
  const fileInputRef = useRef(null);
  const historyCardRefs = useRef(new Map());
  const queueCardRefs = useRef(new Map());

  const selectedLayer = useMemo(
    () => project.layers.find(layer => layer.id === project.selectedLayerId) || project.layers[0],
    [project.layers, project.selectedLayerId],
  );
  const provider = getProviderAdapter(project.provider.id);
  const visibleLayers = project.layers.filter(layer => layer.visible !== false);
  const realImageSessions = useMemo(
    () => project.history.filter(isRealImageSession),
    [project.history],
  );
  const queueItems = useMemo(() => {
    const stateFromStatus = status => {
      const normalized = String(status || "").toLowerCase();
      if (normalized.includes("fail") || normalized.includes("error")) return "failed";
      if (normalized.includes("run") || normalized.includes("queue") || normalized.includes("pending")) return "running";
      if (normalized.includes("generate") || normalized.includes("edit") || normalized.includes("import")) return "done";
      return "pending";
    };

    const base = realImageSessions.map(item => {
      const state = stateFromStatus(item.status);
      const imported = item.status === "imported" && item.provider === "local file";
      const providerName = item.providerId || item.provider || project.provider.id;
      const providerStatusRaw = String(item.providerStatus || "").toLowerCase();
      const hasBlockedRoute =
        providerStatusRaw === "blocked" || String(item.status || "").toLowerCase().includes("provider_blocked");
      const routeLabel = imported ? "local file" : providerRouteFromReceipt(item.receipt) !== "Unknown"
        ? providerRouteFromReceipt(item.receipt)
        : (hasBlockedRoute ? "codex_subscription_blocked" : "codex_subscription");
      return {
        id: item.id,
        title: item.title,
        status: item.status,
        createdAt: item.createdAt,
        prompt: item.prompt,
        state,
        requestId: item.requestId || "pending-request-id",
        providerStatus: item.providerStatus || (hasBlockedRoute ? "blocked" : "available"),
        outputArtifactPath: item.outputArtifactPath || "Not persisted",
        requestTimeline: item.requestTimeline || {},
        queueTimeline: queueTimelineFromItem(item, item.createdAt),
        layerHandoff: item.layerHandoff || {},
        generatedPreview: imageSourceForRecord(item),
        annotationSnapshot: normalizeOverlaySnapshot(item.annotationSnapshot),
        failureSeverity: state === "failed" ? "high" : "low",
        recoveryAction: state === "failed" ? "Retry generation" : "Use as reference",
        receipt: {
          promptHash: item.receipt?.promptHash || tinyPromptHash(item.prompt || project.prompt.text),
          layerCount: Math.max(1, visibleLayers.length),
          providerName,
          route: routeLabel,
          routeProof: imported ? "source hash recorded" : hasBlockedRoute ? "blocked" : "verified",
          testStatus: imported ? "Source hash recorded" : state === "failed" ? "Needs fix" : state === "running" ? "Verifying" : "Checked",
          failureReason: item.receipt?.failureReason || "",
          promptEvidence: item.receipt?.promptEvidence || "",
        },
        issueThread: item.issueThread || {
          id: buildIssueThreadRef(item.receipt?.promptHash || tinyPromptHash(item.prompt || project.prompt.text), item.requestId || "pending-request-id"),
          requestId: item.requestId || "pending-request-id",
          receiptHash: item.receipt?.promptHash || tinyPromptHash(item.prompt || project.prompt.text),
          href: `#issue-thread-${encodeURIComponent(buildIssueThreadRef(item.receipt?.promptHash || tinyPromptHash(item.prompt || project.prompt.text), item.requestId || "pending-request-id"))}`,
        },
      };
    });

    if (busy) {
      base.unshift({
        id: "active-run",
        title: "Current generation",
        status: "Running",
        createdAt: nowIso(),
        prompt: project.prompt.text,
        state: "running",
        requestId: "active-request",
        providerStatus: providerBlockedState ? "blocked" : "running",
        outputArtifactPath: "Awaiting provider artifact",
        requestTimeline: {
          queuedAt: nowIso(),
          startedAt: nowIso(),
        },
        queueTimeline: queueTimelineFromItem({ requestTimeline: { queuedAt: nowIso(), completedAt: "" }, queueTimeline: [] }, nowIso()),
        layerHandoff: {
          stage: "composing",
        },
        annotationSnapshot: normalizeOverlaySnapshot(project.annotationReadiness),
        receipt: {
          promptHash: tinyPromptHash(project.prompt.text),
          layerCount: Math.max(1, visibleLayers.length),
          providerName: project.provider.id,
          route: providerBlockedState ? "codex_subscription_blocked" : "codex_subscription_pending",
          routeProof: providerBlockedState ? "blocked" : "pending",
          testStatus: "Verifying",
        },
        issueThread: {
          id: buildIssueThreadRef(tinyPromptHash(project.prompt.text), "active-request"),
          requestId: "active-request",
          receiptHash: tinyPromptHash(project.prompt.text),
          href: `#issue-thread-${encodeURIComponent(buildIssueThreadRef(tinyPromptHash(project.prompt.text), "active-request"))}`,
        },
      });
    }

    return base.slice(0, 10);
  }, [busy, realImageSessions, project.prompt.text, project.provider.id, providerBlockedState, visibleLayers.length]);

  const queueSummary = useMemo(() => ({
    running: queueItems.filter(item => item.state === "running").length,
    failed: queueItems.filter(item => item.state === "failed").length,
    pending: queueItems.filter(item => item.state === "pending").length,
    done: queueItems.filter(item => item.state === "done").length,
  }), [queueItems]);

  const queueFlow = useMemo(() => {
    const stageMeta = {
      pending: { label: "Queued", detail: "Waiting for an execution slot" },
      running: { label: "Executing", detail: "Provider request is currently running" },
      done: { label: "Output ready", detail: "Result stored in history and available for compare" },
      failed: { label: "Needs attention", detail: "Request failed or blocked provider route needs review" },
    };
    const total = Math.max(1, queueItems.length);
    const completedWeight = queueSummary.done + (queueSummary.failed * 0.75);
    const percent = Math.round((completedWeight / total) * 100);
    return {
      stageMeta,
      percent,
      headline:
        queueSummary.running > 0
          ? `${queueSummary.running} request${queueSummary.running > 1 ? "s" : ""} executing now`
          : queueSummary.pending > 0
            ? `${queueSummary.pending} request${queueSummary.pending > 1 ? "s" : ""} queued`
            : queueSummary.done > 0
              ? "Queue is clear — latest output is ready"
              : "Queue is idle",
    };
  }, [queueItems.length, queueSummary.done, queueSummary.failed, queueSummary.pending, queueSummary.running]);

  const providerBlockedDiagnostics = useMemo(() => {
    if (!providerBlockedState) return [];
    const details = providerBlockedState.details && typeof providerBlockedState.details === "object"
      ? providerBlockedState.details
      : {};
    const authStatus = details.authStatus && typeof details.authStatus === "object" ? details.authStatus : {};
    const expected = details.expected && typeof details.expected === "object" ? details.expected : {};
    const reported = details.reported && typeof details.reported === "object" ? details.reported : {};
    return [
      ["Provider", providerBlockedState.provider || ""],
      ["Provider id", providerBlockedState.providerId || ""],
      ["Model", providerBlockedState.model || ""],
      ["Route", providerBlockedState.route || ""],
      ["Reason", providerBlockedState.blockedReason || ""],
      ["Request", providerBlockedState.requestId || ""],
      ["Expected", [expected.provider, expected.model].filter(Boolean).join(" / ")],
      ["Reported", [reported.provider, reported.model].filter(Boolean).join(" / ")],
      ["Auth", authStatus.source ? `${authStatus.source}${authStatus.authenticated ? " authenticated" : " not authenticated"}` : ""],
    ].filter(([, value]) => String(value || "").trim());
  }, [providerBlockedState]);

  const skillSummary = useMemo(() => ({
    draft: skillDrafts.filter(item => item.state === "draft").length,
    review: skillDrafts.filter(item => item.state === "review").length,
    test: skillDrafts.filter(item => item.state === "test").length,
    published: skillDrafts.filter(item => item.state === "published").length,
  }), [skillDrafts]);

  const latestValidatedReceipt = useMemo(
    () => queueItems.find(item => item.state === "done" || item.state === "running") || queueItems[0] || null,
    [queueItems],
  );

  const queueById = useMemo(() => {
    const map = new Map();
    queueItems.forEach(item => {
      map.set(item.id, item);
    });
    return map;
  }, [queueItems]);

  const syncedFocusedHistoryId = project.focusedHistoryId || compareHistoryId;
  const focusedHistoryItem = useMemo(
    () => project.history.find(item => item.id === syncedFocusedHistoryId) || null,
    [project.history, syncedFocusedHistoryId],
  );
  const historyKeyboardReadyIds = useMemo(
    () => project.history.filter(item => hasKeyboardReadyAnnotations(item.annotationSnapshot)).map(item => item.id),
    [project.history],
  );
  const queueKeyboardReadyIds = useMemo(
    () => queueItems.filter(item => hasKeyboardReadyAnnotations(item.annotationSnapshot)).map(item => item.id),
    [queueItems],
  );
  const keyboardReadyCardIds = useMemo(() => {
    const ordered = [...queueKeyboardReadyIds, ...historyKeyboardReadyIds];
    return [...new Set(ordered.filter(Boolean))];
  }, [historyKeyboardReadyIds, queueKeyboardReadyIds]);
  const focusedOverlaySnapshot = useMemo(
    () => normalizeOverlaySnapshot(focusedHistoryItem?.annotationSnapshot),
    [focusedHistoryItem],
  );
  const selectedGeneratedDesignReference = useMemo(
    () => (project.designReferences || []).find(ref => ref.selected && ref.kind === "generated-image" && (ref.manifestPath || ref.artifactPath)) || null,
    [project.designReferences],
  );
  const selectedGeneratedDesignReferenceUrl = imageSourceForRecord(selectedGeneratedDesignReference);
  const selectedGeneratedManifestUrl = manifestUrlForRecord(selectedGeneratedDesignReference);
  const selectedGeneratedDesignReferenceRequestId = String(selectedGeneratedDesignReference?.requestId || "").trim();
  const libraryItems = useMemo(() => {
    const fromReferences = (project.designReferences || [])
      .filter(item => item?.kind === "generated-image" && imageSourceForRecord(item))
      .map(item => ({
        id: item.id || item.artifactId || item.requestId,
        title: libraryTitle(item),
        source: friendlyImageSource(item),
        src: imageSourceForRecord(item),
        manifestUrl: manifestUrlForRecord(item),
        requestId: item.requestId || "",
        historyId: item.historyId || "",
      }));
    const fromHistory = project.history
      .filter(item => imageSourceForRecord(item))
      .map(item => ({
        id: item.id || item.requestId,
        title: libraryTitle(item),
        source: friendlyImageSource(item),
        src: imageSourceForRecord(item),
        manifestUrl: manifestUrlForRecord(item),
        requestId: item.requestId || "",
        historyId: item.id || "",
      }));
    const seen = new Set();
    return [...fromReferences, ...fromHistory].filter(item => {
      const key = item.src || item.id;
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    }).slice(0, 12);
  }, [project.designReferences, project.history]);
  // Files that can't be read on this PC leave the grid for a compact "Missing · Remove" row.
  const [missingLibrarySrcs, setMissingLibrarySrcs] = useState(() => new Set());
  const shownLibraryItems = libraryItems.filter(item => !missingLibrarySrcs.has(item.src));
  const missingLibraryItems = libraryItems.filter(item => missingLibrarySrcs.has(item.src));
  function markLibraryFileMissing(src) {
    setMissingLibrarySrcs(current => (current.has(src) ? current : new Set(current).add(src)));
  }
  // Only on the user's Remove: drops the entry whose file is already gone from this PC.
  function removeLibraryItem(item) {
    updateProject(current => ({
      ...current,
      history: current.history.filter(entry => entry.id !== item.historyId && imageSourceForRecord(entry) !== item.src),
      designReferences: (current.designReferences || []).filter(ref => (ref.id || ref.artifactId || ref.requestId) !== item.id && imageSourceForRecord(ref) !== item.src),
    }));
  }

  function resolveManifestReceiptLink(item) {
    const requestId = String(item?.requestId || "").trim();
    if (!requestId || !selectedGeneratedDesignReferenceRequestId) return null;
    if (requestId !== selectedGeneratedDesignReferenceRequestId) return null;
    return {
      href: "#artifact-manifest-receipt",
      label: "Manifest receipt linked",
      requestId,
    };
  }
  const annotationKeyLabels = useMemo(() => {
    if (typeof navigator === "undefined") {
      return {
        move: "Arrows",
        fastMove: "Shift + Arrows",
        deleteKey: "Delete/Backspace",
        closeKey: "Escape",
      };
    }
    const touch = navigator.maxTouchPoints > 0;
    const platform = `${navigator.platform || ""} ${navigator.userAgent || ""}`.toLowerCase();
    const isApple = platform.includes("mac") || platform.includes("iphone") || platform.includes("ipad");
    return {
      move: "Arrows",
      fastMove: "Shift + Arrows",
      deleteKey: touch ? "Delete/Backspace" : (isApple ? "Delete" : "Delete/Backspace"),
      closeKey: touch ? "Escape (if keyboard shown)" : "Escape",
    };
  }, []);

  const approvalBuckets = useMemo(() => {
    const buckets = {
      missingReceipt: [],
      receiptNotVerified: [],
      notInTestState: [],
      publishReady: [],
    };
    skillDrafts.forEach(draft => {
      const linkedReceipt = draft.linkedReceiptId ? queueById.get(draft.linkedReceiptId) : null;
      const reviewGate = Boolean(linkedReceipt);
      const testGate = linkedReceipt?.state === "done";
      const publishGate = draft.state === "test" && testGate;
      if (publishGate) {
        buckets.publishReady.push(draft);
      } else if (!reviewGate) {
        buckets.missingReceipt.push(draft);
      } else if (!testGate) {
        buckets.receiptNotVerified.push(draft);
      } else {
        buckets.notInTestState.push(draft);
      }
    });
    return buckets;
  }, [queueById, skillDrafts]);

  const activeReadinessDraft = useMemo(() => {
    if (!skillDrafts.length) return null;
    return skillDrafts.find(item => item.id === activeReadinessDraftId) || approvalBuckets.publishReady[0] || skillDrafts[0];
  }, [activeReadinessDraftId, approvalBuckets.publishReady, skillDrafts]);

  const readinessChecklist = useMemo(() => {
    if (!activeReadinessDraft) return null;
    const linkedReceipt = activeReadinessDraft.linkedReceiptId ? queueById.get(activeReadinessDraft.linkedReceiptId) : null;
    const currentHash = linkedReceipt?.receipt?.promptHash || "";
    const expectedHash = linkedReceipt ? tinyPromptHash(linkedReceipt.prompt || project.prompt.text) : "";
    const receiptHashMatch = Boolean(linkedReceipt && currentHash && expectedHash && currentHash === expectedHash);
    const routeLabel = providerRouteFromReceipt(linkedReceipt?.receipt);
    const routeStable = Boolean(linkedReceipt && linkedReceipt.providerStatus === "available" && routeLabel === "codex_subscription");
    const testPass = linkedReceipt?.state === "done";
    const reviewerSignOff = Boolean(activeReadinessDraft.reviewerSignedOff);
    return {
      linkedReceipt,
      checklist: [
        { key: "hash", label: "Receipt hash match", ok: receiptHashMatch, detail: receiptHashMatch ? currentHash : "Hash missing or stale" },
        { key: "route", label: "Provider route proof", ok: routeStable, detail: routeLabel },
        { key: "test", label: "Latest test pass timestamp", ok: testPass, detail: testPass ? formatDateTime(linkedReceipt?.createdAt) : "No verified queue pass yet" },
        { key: "review", label: "Reviewer sign-off", ok: reviewerSignOff, detail: reviewerSignOff ? formatDateTime(activeReadinessDraft.updatedAt) : "Awaiting reviewer confirmation" },
      ],
      blockedReasons: [
        !linkedReceipt ? "Attach a verification receipt to this draft." : null,
        linkedReceipt && !receiptHashMatch ? "Receipt hash does not match latest prompt evidence." : null,
        linkedReceipt && !routeStable ? "Codex subscription route proof is missing or blocked." : null,
        !testPass ? "Generation queue receipt has not reached verified test state." : null,
        !reviewerSignOff ? "Reviewer sign-off is required before publish." : null,
      ].filter(Boolean),
    };
  }, [activeReadinessDraft, project.prompt.text, queueById]);

  const latestOutcomeEvent = useMemo(
    () => operationEvents.find(item => item.outcome) || null,
    [operationEvents],
  );

  const publishedHandoffRows = useMemo(() => (
    skillDrafts
      .filter(draft => draft.state === "published")
      .map(draft => {
        const linkedReceipt = draft.linkedReceiptId ? queueById.get(draft.linkedReceiptId) : null;
        const handoff = handoffStateByDraftId[draft.id] || {};
        const currentReceiptHash = linkedReceipt?.receipt?.promptHash || "";
        const storedReceiptHash = draft.publishedReceiptHash || "";
        const latestThreadId = latestOutcomeEvent?.id || "";
        const storedThreadId = draft.publishedOutcomeThreadId || "";
        const currentProviderRoute = providerRouteFromReceipt(linkedReceipt?.receipt);
        const storedProviderRoute = draft.publishedProviderRoute || "";
        const currentProviderName = linkedReceipt?.receipt?.providerName || "Unknown";
        const storedProviderName = draft.publishedProviderName || "";
        const currentTestTimestamp = linkedReceipt?.createdAt || "";
        const storedTestTimestamp = draft.publishedTestTimestamp || "";
        const storedReviewerIdentity = draft.publishedReviewerIdentity || "Reviewer pending identity";
        const provenanceCompareRows = [
          {
            key: "hash",
            label: "Receipt hash",
            snapshot: storedReceiptHash || "Missing",
            live: currentReceiptHash || "Missing",
            match: Boolean(storedReceiptHash && currentReceiptHash && storedReceiptHash === currentReceiptHash),
          },
          {
            key: "route",
            label: "Provider route",
            snapshot: storedProviderRoute || "Missing",
            live: currentProviderRoute || "Missing",
            match: Boolean(storedProviderRoute && currentProviderRoute && storedProviderRoute === currentProviderRoute),
          },
          {
            key: "provider",
            label: "Provider",
            snapshot: storedProviderName || "Missing",
            live: currentProviderName || "Missing",
            match: Boolean(storedProviderName && currentProviderName && storedProviderName === currentProviderName),
          },
          {
            key: "test",
            label: "Test timestamp",
            snapshot: storedTestTimestamp ? formatDateTime(storedTestTimestamp) : "Missing",
            live: currentTestTimestamp ? formatDateTime(currentTestTimestamp) : "Missing",
            match: Boolean(storedTestTimestamp && currentTestTimestamp && storedTestTimestamp === currentTestTimestamp),
          },
          {
            key: "reviewer",
            label: "Reviewer",
            snapshot: storedReviewerIdentity,
            live: draft.reviewerSignedOff ? "Signed off" : "Sign-off removed",
            match: draft.reviewerSignedOff,
          },
        ];
        const mismatchReasons = [
          !linkedReceipt ? "Receipt is missing from queue evidence." : null,
          storedReceiptHash && currentReceiptHash && storedReceiptHash !== currentReceiptHash
            ? `Receipt hash drift: published ${storedReceiptHash}, current ${currentReceiptHash}.`
            : null,
          latestThreadId && storedThreadId && latestThreadId !== storedThreadId
            ? "Notification thread drift: newer slice outcome thread exists."
            : null,
          storedProviderRoute && currentProviderRoute && storedProviderRoute !== currentProviderRoute
            ? `Provider route drift: published ${storedProviderRoute}, current ${currentProviderRoute}.`
            : null,
          storedProviderName && currentProviderName && storedProviderName !== currentProviderName
            ? `Provider drift: published ${storedProviderName}, current ${currentProviderName}.`
            : null,
          storedTestTimestamp && currentTestTimestamp && storedTestTimestamp !== currentTestTimestamp
            ? "Test timestamp drift: linked receipt changed since publish snapshot."
            : null,
          !storedReceiptHash ? "Published metadata is missing stored receipt hash." : null,
          !storedThreadId ? "Published metadata is missing stored outcome thread." : null,
          !storedProviderRoute ? "Published metadata is missing provider route snapshot." : null,
          !storedProviderName ? "Published metadata is missing provider snapshot." : null,
          !storedTestTimestamp ? "Published metadata is missing test timestamp snapshot." : null,
          !storedReviewerIdentity ? "Published metadata is missing reviewer identity placeholder." : null,
        ].filter(Boolean);
        return {
          draft,
          linkedReceipt,
          outcomeEvent: latestOutcomeEvent,
          syncConfirmedAt: handoff.syncConfirmedAt || "",
          backendConfirmedAt: handoff.backendConfirmedAt || "",
          currentReceiptHash,
          storedReceiptHash,
          latestThreadId,
          storedThreadId,
          mismatchReasons,
          storedProviderRoute,
          currentProviderRoute,
          storedProviderName,
          currentProviderName,
          storedTestTimestamp,
          currentTestTimestamp,
          storedReviewerIdentity,
          provenanceCompareRows,
        };
      })
  ), [handoffStateByDraftId, latestOutcomeEvent, queueById, skillDrafts]);

  function pushOperationEvent(title, detail, tone = "info", outcome = null) {
    const eventId = makeId("event");
    setOperationEvents(current => ([
      { id: eventId, title, detail, tone, createdAt: nowIso(), outcome },
      ...current,
    ].slice(0, 14)));
    if (outcome) {
      setCollapsedOutcomeIds(current => {
        const next = new Set(current);
        next.add(eventId);
        return next;
      });
    }
  }

  function toggleOutcomeDetails(eventId) {
    setCollapsedOutcomeIds(current => {
      const next = new Set(current);
      if (next.has(eventId)) {
        next.delete(eventId);
      } else {
        next.add(eventId);
      }
      return next;
    });
  }

  function postSliceOutcomeSummary(label = "Manual slice checkpoint", overrides = {}) {
    const buildStatus = overrides.buildStatus || "Passed";
    const testStatus = overrides.testStatus || (queueSummary.failed > 0 ? "Needs attention" : "Passed");
    const syncStatus = overrides.syncStatus || (providerBlockedState ? "Provider blocked" : "Ready to sync");
    const backendStatus = overrides.backendStatus || "Restart queued";
    const changedScope = overrides.changedScope || `${Math.max(1, visibleLayers.length)} visible layers`;
    const severity =
      testStatus.toLowerCase().includes("attention") || syncStatus.toLowerCase().includes("blocked")
        ? "warn"
        : buildStatus.toLowerCase().includes("fail")
          ? "bad"
          : "good";

    pushOperationEvent(
      "Slice outcome notifier",
      `${label}: Build ${buildStatus} · Tests ${testStatus} · Sync ${syncStatus}`,
      severity,
      {
        changedScope,
        buildStatus,
        testStatus,
        syncStatus,
        backendStatus,
      },
    );
  }

  function moveSkillDraftState(draftId, nextState) {
    const publishedReceiptHash = latestValidatedReceipt?.receipt?.promptHash || "";
    const publishedOutcomeThreadId = latestOutcomeEvent?.id || "";
    const publishedOutcomeSummary = latestOutcomeEvent?.outcome
      ? `${latestOutcomeEvent.outcome.buildStatus} · ${latestOutcomeEvent.outcome.testStatus} · ${latestOutcomeEvent.outcome.syncStatus}`
      : "";
    const publishedProviderRoute = providerRouteFromReceipt(latestValidatedReceipt?.receipt);
    const publishedProviderName = latestValidatedReceipt?.receipt?.providerName || "Unknown";
    const publishedTestTimestamp = latestValidatedReceipt?.createdAt || "";
    setSkillDrafts(current => current.map(item => {
      if (item.id !== draftId) return item;
      if (nextState !== "published") {
        return { ...item, state: nextState, updatedAt: nowIso() };
      }
      return {
        ...item,
        state: nextState,
        publishedReceiptHash,
        publishedOutcomeThreadId,
        publishedOutcomeSummary,
        publishedProviderRoute,
        publishedProviderName,
        publishedTestTimestamp,
        publishedReviewerIdentity: item.publishedReviewerIdentity || "Reviewer pending identity",
        updatedAt: nowIso(),
      };
    }));
    const label = DRAFT_STATE_LABELS[nextState] || nextState;
    setSkillNotice(`Moved draft to ${label}.`);
    pushOperationEvent("Skill lifecycle update", `Draft moved to ${label}.`, "info");
  }

  function createDraftFromRecommendation(recommendation) {
    const linkedReceiptId = latestValidatedReceipt?.id || null;
    const freshDraft = {
      id: makeId("skill-draft"),
      title: recommendation.title,
      summary: recommendation.reason,
      state: "draft",
      recommendationId: recommendation.id,
      linkedReceiptId,
      reviewerSignedOff: false,
      updatedAt: nowIso(),
    };
    setSkillDrafts(current => [freshDraft, ...current].slice(0, 8));
    if (linkedReceiptId) {
      setSkillNotice(`Created agent-proposed draft with receipt evidence: ${recommendation.title}`);
      pushOperationEvent("Agent proposed skill draft", `${recommendation.title} linked to latest verification receipt.`, "good");
    } else {
      setSkillNotice(`Created agent-proposed draft: ${recommendation.title}`);
      pushOperationEvent("Agent proposed skill draft", recommendation.title, "good");
    }
  }

  function attachLatestReceiptToDraft(draftId) {
    if (!latestValidatedReceipt?.id) {
      setSkillNotice("No verification receipt available yet. Run Generate to create evidence.");
      pushOperationEvent("Receipt link blocked", "No queue receipt exists to attach to the skill draft yet.", "warn");
      return;
    }
    setSkillDrafts(current => current.map(item => (
      item.id === draftId ? { ...item, linkedReceiptId: latestValidatedReceipt.id, updatedAt: nowIso() } : item
    )));
    setSkillNotice("Linked draft to the latest verification receipt.");
    pushOperationEvent("Skill evidence linked", `Draft linked to receipt ${latestValidatedReceipt.receipt?.promptHash || latestValidatedReceipt.id}.`, "good");
  }

  function openDraftEvidence(draft) {
    if (!draft?.linkedReceiptId) {
      setSkillNotice("Draft has no receipt evidence linked yet.");
      return;
    }
    focusHistoryItem(draft.linkedReceiptId);
    pushOperationEvent("Evidence opened", `Jumped to receipt evidence for ${draft.title}.`, "info");
  }

  function runApprovalQuickFix(reason, draft) {
    if (!draft) return;
    if (reason === "missing-receipt") {
      attachLatestReceiptToDraft(draft.id);
      pushOperationEvent("Approval quick fix", `Linked latest receipt for ${draft.title}.`, "good");
      return;
    }
    if (reason === "receipt-not-verified") {
      openDraftEvidence(draft);
      setSkillNotice("Receipt is linked but not yet verified. Complete generation/test checks first.");
      pushOperationEvent("Approval quick fix", `Opened receipt evidence for ${draft.title} to finish verification.`, "warn");
      return;
    }
    if (reason === "not-in-test") {
      if (draft.state === "draft") {
        moveSkillDraftState(draft.id, "review");
      } else if (draft.state === "review") {
        moveSkillDraftState(draft.id, "test");
      }
      pushOperationEvent("Approval quick fix", `Advanced ${draft.title} toward test/publish readiness.`, "good");
    }
  }

  function setReviewerSignOff(draftId, signed) {
    setSkillDrafts(current => current.map(item => (
      item.id === draftId ? { ...item, reviewerSignedOff: signed, updatedAt: nowIso() } : item
    )));
    setSkillNotice(signed ? "Reviewer sign-off recorded." : "Reviewer sign-off removed.");
    pushOperationEvent("Publish readiness", signed ? "Reviewer sign-off completed." : "Reviewer sign-off cleared for rework.", signed ? "good" : "warn");
  }

  function runReadinessRemediation(action, draft) {
    if (!draft) return;
    if (action === "link") {
      attachLatestReceiptToDraft(draft.id);
      return;
    }
    if (action === "evidence") {
      openDraftEvidence(draft);
      return;
    }
    if (action === "test") {
      runOperation("edit");
      return;
    }
    if (action === "review") {
      if (draft.state === "draft") moveSkillDraftState(draft.id, "review");
      if (draft.state === "review") moveSkillDraftState(draft.id, "test");
      return;
    }
    if (action === "signoff") {
      setReviewerSignOff(draft.id, true);
    }
  }

  function setHandoffCheckpoint(draftId, checkpoint) {
    const timestamp = nowIso();
    setHandoffStateByDraftId(current => ({
      ...current,
      [draftId]: {
        ...(current[draftId] || {}),
        [checkpoint]: timestamp,
      },
    }));
    if (checkpoint === "syncConfirmedAt") {
      pushOperationEvent("Handoff receipt", "Web-control export sync confirmed for published draft.", "good");
      return;
    }
    pushOperationEvent("Handoff receipt", "Backend live-state confirmation recorded for published draft.", "good");
  }

  function openOpsThread(eventId) {
    if (!eventId) {
      pushOperationEvent("Handoff receipt", "No slice outcome thread available yet. Post a slice outcome summary first.", "warn");
      return;
    }
    setActiveOpsThreadId(eventId);
    pushOperationEvent("Handoff receipt", "Opened linked notification thread for published draft handoff.", "info");
  }

  function remediateHandoffIntegrity(action, row) {
    if (!row?.draft) return;
    if (action === "link-receipt") {
      attachLatestReceiptToDraft(row.draft.id);
      return;
    }
    if (action === "refresh-metadata") {
      setSkillDrafts(current => current.map(item => (
        item.id === row.draft.id
          ? {
            ...item,
            publishedReceiptHash: row.currentReceiptHash || "",
            publishedOutcomeThreadId: latestOutcomeEvent?.id || "",
            publishedOutcomeSummary: latestOutcomeEvent?.outcome
              ? `${latestOutcomeEvent.outcome.buildStatus} · ${latestOutcomeEvent.outcome.testStatus} · ${latestOutcomeEvent.outcome.syncStatus}`
              : "",
            publishedProviderRoute: row.currentProviderRoute || "Unknown",
            publishedProviderName: row.currentProviderName || "Unknown",
            publishedTestTimestamp: row.currentTestTimestamp || "",
            publishedReviewerIdentity: row.storedReviewerIdentity || "Reviewer pending identity",
            updatedAt: nowIso(),
          }
          : item
      )));
      setSkillNotice(`Refreshed handoff metadata for ${row.draft.title}.`);
      pushOperationEvent("Handoff integrity", `Metadata refreshed for ${row.draft.title}.`, "good");
      return;
    }
    if (action === "open-thread") {
      openOpsThread(latestOutcomeEvent?.id || row.outcomeEvent?.id || "");
      return;
    }
    if (action === "open-evidence") {
      openDraftEvidence(row.draft);
    }
  }

  const workflowSteps = useMemo(() => {
    const hasBackground = Boolean(project.canvas.background && project.canvas.background.trim());
    const hasImageLayer = project.layers.some(layer => layer.type === "image" && layer.visible !== false);
    const hasQueuedOrHistory = queueItems.length > 0;
    const hasGeneration = realImageSessions.some(item => {
      const status = String(item.status || "").toLowerCase();
      return status.includes("generate") || status.includes("edit");
    });
    return [
      { id: "background", label: "Background selected", complete: hasBackground },
      { id: "layers", label: "Visible image layers", complete: hasImageLayer },
      { id: "queue", label: "Queue/history recorded", complete: hasQueuedOrHistory },
      { id: "generation", label: "Generation executed", complete: hasGeneration },
    ];
  }, [project.canvas.background, project.layers, realImageSessions, queueItems.length]);

  const nextGuidedAction = useMemo(() => {
    const firstIncomplete = workflowSteps.find(step => !step.complete);
    if (!firstIncomplete) {
      return {
        id: "publish",
        title: "Workflow verified",
        detail: "Create or publish a skill draft from this validated slice.",
        cta: "Open skill lifecycle",
      };
    }
    if (firstIncomplete.id === "layers") {
      return {
        id: "import",
        title: "Add a source layer",
        detail: "Import an image so edits and queue tracking use a real visual source.",
        cta: "Import image",
      };
    }
    if (firstIncomplete.id === "queue") {
      return {
        id: "generate",
        title: "Create first tracked run",
        detail: "Run Generate once to initialize queue telemetry and status history.",
        cta: "Run generate",
      };
    }
    if (firstIncomplete.id === "generation") {
      return {
        id: "continue",
        title: "Continue from composition",
        detail: "Run Continue from adjusted composition to validate edit flow.",
        cta: "Run continue",
      };
    }
    return {
      id: "background",
      title: "Tune background",
      detail: "Adjust background tone to define the composition baseline.",
      cta: "Set background",
    };
  }, [workflowSteps]);

  function handleNextGuidedAction() {
    if (nextGuidedAction.id === "import") {
      fileInputRef.current?.click();
      return;
    }
    if (nextGuidedAction.id === "generate") {
      runOperation("generate", { imagePluginMode: true });
      return;
    }
    if (nextGuidedAction.id === "continue") {
      runOperation("edit");
      return;
    }
    if (nextGuidedAction.id === "publish") {
      pushOperationEvent("Next idea", "Publish a tested skill draft to capture this verified image workflow.", "good");
      setSkillNotice("Workflow verified. Promote a tested draft to Published to lock in the process.");
      return;
    }
    setSkillNotice("Background can be tuned in Prompt stack before the next generation step.");
  }

  useEffect(() => {
    if (!skillDrafts.length) {
      setActiveReadinessDraftId("");
      return;
    }
    const currentValid = skillDrafts.some(item => item.id === activeReadinessDraftId);
    if (!currentValid) {
      setActiveReadinessDraftId(skillDrafts[0].id);
    }
  }, [activeReadinessDraftId, skillDrafts]);

  useEffect(() => {
    if (!project.history.length) return;
    const nextId = compareHistoryId || project.focusedHistoryId || project.history[0]?.id || "";
    if (nextId && nextId !== project.focusedHistoryId) {
      setProject(current => setFocusedHistoryItem(current, nextId));
    }
  }, [compareHistoryId, project.focusedHistoryId, project.history]);

  useEffect(() => {
    if (project.annotationReadiness?.activeThreadRef) {
      setActiveOpsThreadId(project.annotationReadiness.activeThreadRef);
    }
  }, [project.annotationReadiness?.activeThreadRef]);

  useEffect(() => {
    if (!readOnly) saveImageProject(project);
  }, [project, readOnly]);

  useEffect(() => {
    function handleAnnotationKeyboardNudge(event) {
      const targetTag = String(event.target?.tagName || "").toLowerCase();
      if (targetTag === "input" || targetTag === "textarea" || event.target?.isContentEditable) {
        if (event.key === "Escape" && activeAnnotationTarget.kind) {
          setActiveAnnotationTarget({ kind: "", id: "" });
          event.target?.blur?.();
        }
        return;
      }
      if (!activeAnnotationTarget.kind) return;
      if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) {
        event.preventDefault();
        const delta = event.shiftKey ? 10 : 1;
        if (event.key === "ArrowUp") nudgeActiveAnnotation(0, -delta);
        if (event.key === "ArrowDown") nudgeActiveAnnotation(0, delta);
        if (event.key === "ArrowLeft") nudgeActiveAnnotation(-delta, 0);
        if (event.key === "ArrowRight") nudgeActiveAnnotation(delta, 0);
        return;
      }
      if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        deleteActiveAnnotation();
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setActiveAnnotationTarget({ kind: "", id: "" });
      }
    }

    window.addEventListener("keydown", handleAnnotationKeyboardNudge);
    return () => window.removeEventListener("keydown", handleAnnotationKeyboardNudge);
  }, [activeAnnotationTarget, project.canvas.height, project.canvas.width, project.annotationReadiness?.pins, project.annotationReadiness?.rectangles]);

  useEffect(() => {
    if (!activeAnnotationTarget.kind) {
      setAnnotationLegendCollapsed(true);
      return;
    }
    if (!annotationOnboardingDismissed) {
      setAnnotationOnboardingDismissed(true);
      if (typeof window !== "undefined") {
        window.localStorage.setItem("image-playground-annotation-onboarding-dismissed", "1");
      }
    }
  }, [activeAnnotationTarget.kind, annotationOnboardingDismissed]);

  useEffect(() => {
    if (!keyboardJumpTrail.length) {
      hideJumpTrailChipDetails();
      return undefined;
    }
    const timeoutId = window.setTimeout(() => {
      setKeyboardJumpTrail([]);
      hideJumpTrailChipDetails();
    }, KEYBOARD_JUMP_TRAIL_IDLE_MS);
    return () => window.clearTimeout(timeoutId);
  }, [keyboardJumpTrail]);

  useEffect(() => () => clearJumpTrailLongPressTimer(), []);

  function updateProject(updater) {
    setProject(current => normalizeProject(typeof updater === "function" ? updater(current) : updater));
  }

  function focusHistoryItem(historyId) {
    if (!historyId) return;
    setCompareHistoryId(historyId);
    updateProject(current => setFocusedHistoryItem(current, historyId));
  }

  function openIssueThreadForHistoryItem(historyId) {
    if (!historyId) return;
    setCompareHistoryId(historyId);
    let nextActiveThreadId = "";
    updateProject(current => {
      const focused = setFocusedHistoryItem(current, historyId);
      const title = `Issue: ${focused.history.find(item => item.id === historyId)?.title || "Image feedback"}`;
      const threaded = createOpsThreadForFocusedHistory(focused, { title });
      nextActiveThreadId = threaded.annotationReadiness?.activeThreadRef || "";
      return threaded;
    });
    if (nextActiveThreadId) {
      setActiveOpsThreadId(nextActiveThreadId);
    }
  }

  function scopeLabel(scope) {
    return keyboardScopeLabel(scope);
  }

  function scopeKeyboardReadyIds(scope) {
    return scope === "queue" ? queueKeyboardReadyIds : historyKeyboardReadyIds;
  }

  function scopedCardIndexIndicator(scope, historyId) {
    const ids = scopeKeyboardReadyIds(scope);
    const index = ids.indexOf(historyId);
    if (!ids.length) return `${scopeLabel(scope)} 0/0`;
    if (index < 0) return `${scopeLabel(scope)} 0/${ids.length}`;
    return `${scopeLabel(scope)} ${index + 1}/${ids.length}`;
  }

  function groupedCardIndexIndicator(activeScope, historyId) {
    const active = scopedCardIndexIndicator(activeScope, historyId);
    const oppositeScope = activeScope === "queue" ? "history" : "queue";
    const opposite = scopedCardIndexIndicator(oppositeScope, "");
    return `${active} • ${opposite}`;
  }

  function scopedCardIndexMeta(scope, historyId) {
    const ids = scopeKeyboardReadyIds(scope);
    if (!ids.length) return { index: 0, count: 0 };
    const foundIndex = ids.indexOf(historyId);
    const index = foundIndex < 0 ? 1 : foundIndex + 1;
    return { index, count: ids.length };
  }

  function announceKeyboardTraversal(fromScope, fromId, toScope, toId, reason = "focus") {
    const fromMeta = scopedCardIndexMeta(fromScope, fromId);
    const toMeta = scopedCardIndexMeta(toScope, toId);
    const transition = {
      fromScope,
      fromIndex: fromMeta.index,
      fromCount: fromMeta.count,
      toScope,
      toIndex: toMeta.index,
      toCount: toMeta.count,
      reason,
    };
    const announcement = buildKeyboardTraversalAnnouncement(transition);
    if (!announcement || announcement === lastTraversalAnnouncementRef.current) return;
    lastTraversalAnnouncementRef.current = announcement;
    setKeyboardTraversalAnnouncement(announcement);
    setKeyboardJumpTrail(current => appendKeyboardJumpTrail(current, transition, { maxEntries: KEYBOARD_JUMP_TRAIL_LIMIT }));
  }

  function focusKeyboardReadyCard(historyId, scope, context = {}) {
    if (!historyId) return;
    focusHistoryItem(historyId);
    const refMap = scope === "queue" ? queueCardRefs.current : historyCardRefs.current;
    refMap.get(historyId)?.focus?.();
    if (context.fromScope && context.fromId) {
      announceKeyboardTraversal(context.fromScope, context.fromId, scope, historyId, context.reason || "focus");
    } else {
      announceKeyboardTraversal(scope, historyId, scope, historyId, "focus");
    }
  }

  function moveKeyboardReadyCardFocus(direction, historyId, scope) {
    const ids = scope === "queue" ? queueKeyboardReadyIds : historyKeyboardReadyIds;
    if (!ids.length) return;
    const currentIndex = Math.max(0, ids.indexOf(historyId));
    const nextIndex = clamp(currentIndex + direction, 0, ids.length - 1);
    const nextId = ids[nextIndex];
    focusKeyboardReadyCard(nextId, scope, { fromScope: scope, fromId: historyId, reason: "arrow" });
  }

  function jumpKeyboardReadyCardFocus(edge, scope, fromId = "") {
    const ids = scope === "queue" ? queueKeyboardReadyIds : historyKeyboardReadyIds;
    if (!ids.length) return;
    const nextId = edge === "start" ? ids[0] : ids[ids.length - 1];
    focusKeyboardReadyCard(nextId, scope, { fromScope: scope, fromId: fromId || nextId, reason: "edge-jump" });
  }

  function moveKeyboardReadyCardGroup(historyId, scope, direction) {
    const sourceIds = scope === "queue" ? queueKeyboardReadyIds : historyKeyboardReadyIds;
    const targetScope = scope === "queue" ? "history" : "queue";
    const targetIds = targetScope === "queue" ? queueKeyboardReadyIds : historyKeyboardReadyIds;
    if (!targetIds.length) return;
    const sourceIndex = Math.max(0, sourceIds.indexOf(historyId));
    const nextIndex = direction > 0
      ? clamp(sourceIndex, 0, targetIds.length - 1)
      : clamp(sourceIndex, 0, targetIds.length - 1);
    const nextId = targetIds[nextIndex];
    focusKeyboardReadyCard(nextId, targetScope, { fromScope: scope, fromId: historyId, reason: "group-jump" });
  }

  function cardIndexIndicator(historyId, scope = "history") {
    return scopedCardIndexIndicator(scope, historyId);
  }

  function handleKeyboardReadyCardKeyDown(event, historyId, scope, keyboardReady) {
    if (!historyId) return;
    if (event.key === "ArrowDown" || event.key === "ArrowRight") {
      event.preventDefault();
      moveKeyboardReadyCardFocus(1, historyId, scope);
      return;
    }
    if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
      event.preventDefault();
      moveKeyboardReadyCardFocus(-1, historyId, scope);
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      jumpKeyboardReadyCardFocus("start", scope, historyId);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      jumpKeyboardReadyCardFocus("end", scope, historyId);
      return;
    }
    if (event.key === "PageDown") {
      event.preventDefault();
      moveKeyboardReadyCardGroup(historyId, scope, 1);
      return;
    }
    if (event.key === "PageUp") {
      event.preventDefault();
      moveKeyboardReadyCardGroup(historyId, scope, -1);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      if (event.shiftKey) {
        openIssueThreadForHistoryItem(historyId);
        return;
      }
      if (keyboardReady) {
        focusFirstAnnotationForHistoryItem(historyId);
      } else {
        focusHistoryItem(historyId);
      }
      return;
    }
    if (event.key === " ") {
      event.preventDefault();
      focusHistoryItem(historyId);
    }
  }

  function patchFocusedAnnotations(annotationPatch) {
    updateProject(current => updateFocusedHistoryAnnotations(current, annotationPatch));
  }

  function updateFocusedPin(pinId, patch) {
    const pins = Array.isArray(project.annotationReadiness?.pins) ? project.annotationReadiness.pins : [];
    patchFocusedAnnotations({
      pins: pins.map(pin => (pin.id === pinId ? { ...pin, ...patch } : pin)),
    });
  }

  function updateFocusedRectangle(rectId, patch) {
    const rectangles = Array.isArray(project.annotationReadiness?.rectangles) ? project.annotationReadiness.rectangles : [];
    patchFocusedAnnotations({
      rectangles: rectangles.map(rect => (rect.id === rectId ? { ...rect, ...patch } : rect)),
    });
  }

  function currentActiveAnnotation() {
    if (activeAnnotationTarget.kind === "pin") {
      return (project.annotationReadiness?.pins || []).find(pin => pin.id === activeAnnotationTarget.id) || null;
    }
    if (activeAnnotationTarget.kind === "rectangle") {
      return (project.annotationReadiness?.rectangles || []).find(rect => rect.id === activeAnnotationTarget.id) || null;
    }
    return null;
  }

  function nudgeActiveAnnotation(deltaX, deltaY) {
    if (activeAnnotationTarget.kind === "pin") {
      const pin = (project.annotationReadiness?.pins || []).find(item => item.id === activeAnnotationTarget.id);
      if (!pin) return;
      updateFocusedPin(pin.id, {
        x: Math.round(clamp(Number(pin.x || 0) + deltaX, 0, project.canvas.width)),
        y: Math.round(clamp(Number(pin.y || 0) + deltaY, 0, project.canvas.height)),
      });
      return;
    }
    if (activeAnnotationTarget.kind === "rectangle") {
      const rect = (project.annotationReadiness?.rectangles || []).find(item => item.id === activeAnnotationTarget.id);
      if (!rect) return;
      updateFocusedRectangle(rect.id, {
        x: Math.round(clamp(Number(rect.x || 0) + deltaX, 0, project.canvas.width)),
        y: Math.round(clamp(Number(rect.y || 0) + deltaY, 0, project.canvas.height)),
      });
    }
  }

  function deleteActiveAnnotation() {
    if (activeAnnotationTarget.kind === "pin") {
      patchFocusedAnnotations({
        pins: (project.annotationReadiness?.pins || []).filter(pin => pin.id !== activeAnnotationTarget.id),
      });
      setActiveAnnotationTarget({ kind: "", id: "" });
      return;
    }
    if (activeAnnotationTarget.kind === "rectangle") {
      patchFocusedAnnotations({
        rectangles: (project.annotationReadiness?.rectangles || []).filter(rect => rect.id !== activeAnnotationTarget.id),
      });
      setActiveAnnotationTarget({ kind: "", id: "" });
    }
  }

  function addFocusedPin() {
    const pins = Array.isArray(project.annotationReadiness?.pins) ? project.annotationReadiness.pins : [];
    const newId = makeId("pin-canvas");
    patchFocusedAnnotations({
      pins: [
        ...pins,
        {
          id: newId,
          x: Math.round(project.canvas.width * 0.5),
          y: Math.round(project.canvas.height * 0.5),
          comment: "UI note",
        },
      ].slice(-24),
    });
    setActiveAnnotationTarget({ kind: "pin", id: newId });
  }

  function addFocusedRectangle() {
    const rectangles = Array.isArray(project.annotationReadiness?.rectangles) ? project.annotationReadiness.rectangles : [];
    const newId = makeId("rect-canvas");
    patchFocusedAnnotations({
      rectangles: [
        ...rectangles,
        {
          id: newId,
          x: Math.round(project.canvas.width * 0.2),
          y: Math.round(project.canvas.height * 0.2),
          width: Math.round(project.canvas.width * 0.28),
          height: Math.round(project.canvas.height * 0.18),
          comment: "Needs adjustment",
        },
      ].slice(-24),
    });
    setActiveAnnotationTarget({ kind: "rectangle", id: newId });
  }

  function addFocusedComment() {
    const comments = Array.isArray(project.annotationReadiness?.comments) ? project.annotationReadiness.comments : [];
    patchFocusedAnnotations({
      comments: [
        ...comments,
        {
          id: makeId("comment"),
          text: `Comment ${comments.length + 1} for focused history item`,
          createdAt: nowIso(),
        },
      ].slice(-40),
    });
  }

  function createIssueThreadFromFocusedHistory() {
    updateProject(current => {
      const threaded = createOpsThreadForFocusedHistory(current, {
        title: `Issue: ${current.history.find(item => item.id === (current.focusedHistoryId || compareHistoryId))?.title || "Image feedback"}`,
      });
      const activeThreadRef = threaded.annotationReadiness?.activeThreadRef || "";
      const stamp = nowIso();
      return {
        ...threaded,
        opsThreads: threaded.opsThreads.map(thread => (
          thread.id !== activeThreadRef
            ? thread
            : {
                ...thread,
                updatedAt: stamp,
                messages: [
                  ...(thread.messages || []),
                  {
                    id: makeId("ops-msg"),
                    text: "Issue thread created from annotation toolbar.",
                    createdAt: stamp,
                  },
                ],
              }
        )),
      };
    });
  }

  function hasKeyboardReadyAnnotations(snapshot) {
    const pins = Array.isArray(snapshot?.pins) ? snapshot.pins : [];
    const rectangles = Array.isArray(snapshot?.rectangles) ? snapshot.rectangles : [];
    return pins.length > 0 || rectangles.length > 0;
  }

  function focusFirstAnnotationForHistoryItem(historyId) {
    const historyItem = project.history.find(item => item.id === historyId);
    if (!historyItem) return;
    focusHistoryItem(historyId);
    const pins = Array.isArray(historyItem.annotationSnapshot?.pins) ? historyItem.annotationSnapshot.pins : [];
    const rectangles = Array.isArray(historyItem.annotationSnapshot?.rectangles) ? historyItem.annotationSnapshot.rectangles : [];
    if (pins[0]?.id) {
      setActiveAnnotationTarget({ kind: "pin", id: pins[0].id });
      setAnnotationLegendCollapsed(false);
      return;
    }
    if (rectangles[0]?.id) {
      setActiveAnnotationTarget({ kind: "rectangle", id: rectangles[0].id });
      setAnnotationLegendCollapsed(false);
    }
  }

  function updateLayer(layerId, patch) {
    updateProject(current => ({
      ...current,
      updatedAt: nowIso(),
      layers: current.layers.map(layer => (layer.id === layerId ? { ...layer, ...patch } : layer)),
    }));
  }

  function selectLayer(layerId) {
    updateProject(current => ({ ...current, selectedLayerId: layerId }));
  }

  function reorderLayer(layerId, direction) {
    updateProject(current => {
      const layers = [...current.layers];
      const index = layers.findIndex(layer => layer.id === layerId);
      if (index < 0) return current;
      const nextIndex = clamp(index + direction, 0, layers.length - 1);
      const [layer] = layers.splice(index, 1);
      layers.splice(nextIndex, 0, layer);
      return { ...current, layers, updatedAt: nowIso() };
    });
  }

  function duplicateLayer(layerId) {
    const layer = project.layers.find(item => item.id === layerId);
    if (!layer) return;
    const copy = {
      ...structuredCloneSafe(layer),
      id: makeId("layer-copy"),
      name: `${layer.name} copy`,
      locked: false,
      x: layer.x + 36,
      y: layer.y + 36,
    };
    updateProject(current => ({
      ...current,
      selectedLayerId: copy.id,
      layers: [...current.layers, copy],
      updatedAt: nowIso(),
    }));
  }

  function addShapeLayer() {
    const layer = {
      id: makeId("layer-shape"),
      name: "New editable region",
      type: "shape",
      locked: false,
      visible: true,
      opacity: 0.72,
      blendMode: "screen",
      x: 250,
      y: 250,
      width: 260,
      height: 210,
      rotation: 0,
      fill: "linear-gradient(135deg, rgba(255,255,255,.36), rgba(214,168,79,.22))",
      radius: 28,
      promptRole: "manual composition layer",
    };
    updateProject(current => ({
      ...current,
      selectedLayerId: layer.id,
      layers: [...current.layers, layer],
      updatedAt: nowIso(),
    }));
  }

  function handleImportFile(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const layer = {
        id: makeId("layer-import"),
        name: file.name.replace(/\.[^.]+$/, "") || "Imported image",
        type: "image",
        src: String(reader.result || ""),
        locked: false,
        visible: true,
        opacity: 1,
        blendMode: "normal",
        x: 140,
        y: 140,
        width: 620,
        height: 620,
        rotation: 0,
        promptRole: "user imported source image",
      };
      setEditorOpen(true);
      updateProject(current => addHistoryEntry({
        ...current,
        selectedLayerId: layer.id,
        layers: [...current.layers, layer],
        updatedAt: nowIso(),
      }, {
        title: "Imported image",
        prompt: file.name,
        provider: "local file",
        status: "imported",
      }));
    };
    reader.readAsDataURL(file);
    event.target.value = "";
  }

  function pointerToCanvas(event) {
    const node = canvasRef.current;
    if (!node) return { x: 0, y: 0 };
    const rect = node.getBoundingClientRect();
    const scaleX = project.canvas.width / rect.width;
    const scaleY = project.canvas.height / rect.height;
    return {
      x: (event.clientX - rect.left) * scaleX,
      y: (event.clientY - rect.top) * scaleY,
    };
  }

  function startLayerDrag(event, layer) {
    if (layer.locked || project.activeTool !== "select") return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const point = pointerToCanvas(event);
    setDragState({ kind: "move", layerId: layer.id, start: point, origin: { x: layer.x, y: layer.y } });
    selectLayer(layer.id);
  }

  function startResize(event, layer) {
    event.stopPropagation();
    if (layer.locked) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const point = pointerToCanvas(event);
    setDragState({ kind: "resize", layerId: layer.id, start: point, origin: { width: layer.width, height: layer.height } });
  }

  function startSelectionDrag(event) {
    if (project.activeTool !== "region" && project.activeTool !== "mask") return;
    event.preventDefault();
    const point = pointerToCanvas(event);
    setDragState({ kind: "selection", start: point, origin: point });
    updateProject(current => ({
      ...current,
      selection: { ...current.selection, x: point.x, y: point.y, width: 1, height: 1, visible: true },
    }));
  }

  function startPinDrag(event, pin) {
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const point = pointerToCanvas(event);
    setActiveAnnotationTarget({ kind: "pin", id: pin.id });
    setDragState({ kind: "annotation-pin-move", pinId: pin.id, start: point, origin: { x: Number(pin.x || 0), y: Number(pin.y || 0) } });
  }

  function startRectangleDrag(event, rect) {
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const point = pointerToCanvas(event);
    setActiveAnnotationTarget({ kind: "rectangle", id: rect.id });
    setDragState({ kind: "annotation-rect-move", rectId: rect.id, start: point, origin: { x: Number(rect.x || 0), y: Number(rect.y || 0) } });
  }

  function startRectangleResize(event, rect) {
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const point = pointerToCanvas(event);
    setActiveAnnotationTarget({ kind: "rectangle", id: rect.id });
    setDragState({
      kind: "annotation-rect-resize",
      rectId: rect.id,
      start: point,
      origin: { width: Number(rect.width || 0), height: Number(rect.height || 0) },
    });
  }

  function handlePointerMove(event) {
    if (!dragState) return;
    const point = pointerToCanvas(event);
    if (dragState.kind === "move") {
      updateLayer(dragState.layerId, {
        x: clamp(dragState.origin.x + point.x - dragState.start.x, -project.canvas.width, project.canvas.width),
        y: clamp(dragState.origin.y + point.y - dragState.start.y, -project.canvas.height, project.canvas.height),
      });
    }
    if (dragState.kind === "resize") {
      updateLayer(dragState.layerId, {
        width: clamp(dragState.origin.width + point.x - dragState.start.x, 24, project.canvas.width * 2),
        height: clamp(dragState.origin.height + point.y - dragState.start.y, 24, project.canvas.height * 2),
      });
    }
    if (dragState.kind === "annotation-pin-move") {
      updateFocusedPin(dragState.pinId, {
        x: Math.round(clamp(dragState.origin.x + point.x - dragState.start.x, 0, project.canvas.width)),
        y: Math.round(clamp(dragState.origin.y + point.y - dragState.start.y, 0, project.canvas.height)),
      });
    }
    if (dragState.kind === "annotation-rect-move") {
      updateFocusedRectangle(dragState.rectId, {
        x: Math.round(clamp(dragState.origin.x + point.x - dragState.start.x, 0, project.canvas.width)),
        y: Math.round(clamp(dragState.origin.y + point.y - dragState.start.y, 0, project.canvas.height)),
      });
    }
    if (dragState.kind === "annotation-rect-resize") {
      updateFocusedRectangle(dragState.rectId, {
        width: Math.round(clamp(dragState.origin.width + point.x - dragState.start.x, 16, project.canvas.width)),
        height: Math.round(clamp(dragState.origin.height + point.y - dragState.start.y, 16, project.canvas.height)),
      });
    }
    if (dragState.kind === "selection") {
      const x = Math.min(dragState.origin.x, point.x);
      const y = Math.min(dragState.origin.y, point.y);
      updateProject(current => ({
        ...current,
        selection: {
          ...current.selection,
          x,
          y,
          width: Math.abs(point.x - dragState.origin.x),
          height: Math.abs(point.y - dragState.origin.y),
          visible: true,
        },
      }));
    }
  }

  function handlePointerUp() {
    setDragState(null);
  }

  function applyCanvasLayerTransform(ctx, layer) {
    ctx.globalAlpha = layer.opacity ?? 1;
    ctx.translate(layer.x + layer.width / 2, layer.y + layer.height / 2);
    ctx.rotate(((layer.rotation || 0) * Math.PI) / 180);
  }

  function shapeFillForCanvas(ctx, layer) {
    const fill = String(layer.fill || "rgba(255,255,255,.16)");
    if (fill.startsWith("#") || fill.startsWith("rgb") || fill.startsWith("hsl")) {
      return fill;
    }
    const gradient = ctx.createLinearGradient(-layer.width / 2, -layer.height / 2, layer.width / 2, layer.height / 2);
    gradient.addColorStop(0, "rgba(255,255,255,.34)");
    gradient.addColorStop(0.58, "rgba(214,168,79,.26)");
    gradient.addColorStop(1, "rgba(142,203,111,.14)");
    return gradient;
  }

  async function composeSnapshotDataUrl() {
    const canvas = document.createElement("canvas");
    canvas.width = project.canvas.width;
    canvas.height = project.canvas.height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return "";
    ctx.fillStyle = project.canvas.background;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    for (const layer of visibleLayers) {
      ctx.save();
      applyCanvasLayerTransform(ctx, layer);
      if (layer.type === "shape") {
        const radius = clamp(layer.radius ?? 18, 0, Math.min(layer.width, layer.height) / 2);
        ctx.fillStyle = shapeFillForCanvas(ctx, layer);
        ctx.beginPath();
        ctx.roundRect(-layer.width / 2, -layer.height / 2, layer.width, layer.height, radius);
        ctx.fill();
        ctx.restore();
        continue;
      }
      if (layer.type !== "image" || !layer.src) {
        ctx.restore();
        continue;
      }
      await new Promise(resolve => {
        const img = new Image();
        img.onload = () => {
          ctx.drawImage(img, -layer.width / 2, -layer.height / 2, layer.width, layer.height);
          ctx.restore();
          resolve();
        };
        img.onerror = () => {
          ctx.restore();
          resolve();
        };
        img.src = layer.src;
      });
    }
    return canvas.toDataURL("image/png");
  }

  async function runOperation(operation, options = {}) {
    const imagePluginMode = operation === "generate" ? options.imagePluginMode !== false : Boolean(options.imagePluginMode);
    setBusy(true);
    resetImageHorizontalScroll();
    setProviderBlockedState(null);
    setProviderMessage(
      imagePluginMode
        ? "Making your image. This can take a minute or two."
        : operation === "edit" ? "Updating the image from your canvas." : "Making your image.",
    );
    pushOperationEvent(
      imagePluginMode ? "Image generation started" : operation === "edit" ? "Edit request started" : "Generation request started",
      imagePluginMode
        ? "Sending the prompt directly to the image artifact lane."
        : operation === "edit" ? "Building snapshot from visible layers." : "Preparing provider payload and queue entry.",
      "info",
    );
    try {
      const snapshotDataUrl = imagePluginMode ? "" : await composeSnapshotDataUrl();
      const result = await requestProviderOperation(project, operation, { callBackend, snapshotDataUrl, imagePluginMode });
      setProject(current => {
        const withResult = applyProviderResult(current, result, operation);
        const skillInvocation = result?.meta?.receipt?.skillInvocation || result?.meta?.skillInvocation || null;
        const evidence = {
          id: makeId("skill-evidence"),
          selectedSkills: skillInvocation?.status === "executed" ? [skillInvocation.skillId] : [],
          why: skillInvocation?.status === "executed"
            ? "The backend loaded the installed SKILL.md before generation and attached its execution receipt."
            : "This provider operation did not return an installed-skill execution receipt.",
          artifacts: [result?.meta?.outputArtifactPath || ""].filter(Boolean),
          requestId: result?.meta?.requestId || "",
          skillInvocation,
          createdAt: nowIso(),
        };
        return { ...withResult, skillsEvidence: [evidence, ...(withResult.skillsEvidence || [])].slice(0, 20) };
      });
      const blocked = result.kind === "provider-blocked" || result.status === "unavailable";
      if (blocked) {
        setProviderBlockedState({
          status: result.status || "unavailable",
          provider: result.provider || provider.name,
          providerId: result.providerId || provider.id,
          model: result.model || provider.model || "",
          route: result.route || result.meta?.route || "codex_subscription",
          blockedReason: result.blockedReason || result.meta?.blockedReason || result.meta?.receipt?.failureReason || "",
          message: result.message || "Codex subscription image route is blocked for this request.",
          details: result.details || result.meta?.details || {},
          requestId: result.meta?.requestId || "",
        });
        pushOperationEvent("Provider blocked", result.message || "Codex subscription route was unavailable for this request.", "warn");
        postSliceOutcomeSummary(operation === "edit" ? "Continue slice blocked" : "Generation slice blocked", {
          syncStatus: "Provider blocked",
          backendStatus: "Restart deferred",
          testStatus: "Needs attention",
        });
      } else {
        pushOperationEvent(
          imagePluginMode ? "Image generated" : operation === "edit" ? "Edit completed" : "Generation completed",
          result.message || "Provider returned a new layer revision.",
          "good",
        );
        postSliceOutcomeSummary(operation === "edit" ? "Continue slice verified" : "Generation slice verified", {
          syncStatus: "Ready to sync",
          backendStatus: "Restart queued",
          testStatus: "Passed",
        });
      }
      setProviderMessage(result.message || "Operation finished.");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown provider error.";
      setProviderMessage(`Couldn't make the image: ${message}`);
      pushOperationEvent("Operation failed", message, "bad");
      postSliceOutcomeSummary(operation === "edit" ? "Continue slice failed" : "Generation slice failed", {
        buildStatus: "Passed",
        testStatus: "Failed",
        syncStatus: "Blocked",
        backendStatus: "Restart blocked",
      });
      throw error;
    } finally {
      setBusy(false);
      resetImageHorizontalScroll();
    }
  }

  function resetImageHorizontalScroll() {
    if (typeof document === "undefined") return;
    requestAnimationFrame(() => {
      if (typeof window !== "undefined" && typeof window.scrollTo === "function") {
        window.scrollTo(0, window.scrollY || 0);
      }
      if (document.scrollingElement) document.scrollingElement.scrollLeft = 0;
      if (document.documentElement) document.documentElement.scrollLeft = 0;
      if (document.body) document.body.scrollLeft = 0;
      document
        .querySelectorAll(".nx-tool-screen-image-playground, .image-playground-shell")
        .forEach(node => {
          node.scrollLeft = 0;
        });
    });
  }

  function useQueueImageAsReference(item) {
    if (!item) return;
    const ref = {
      id: makeId("gen-ref"),
      title: item.title || "Generated reference",
      kind: "generated-image",
      artifactPath: item.outputArtifactPath || "",
      artifactUrl: imageSourceForRecord(item),
      manifestUrl: manifestUrlForRecord(item),
      requestId: item.requestId || "",
      selected: true,
      rationale: `Selected from queue item ${item.id} to improve UI composition and controls.`,
    };
    updateProject(current => ({
      ...current,
      designReferences: [ref, ...(current.designReferences || [])].slice(0, 8),
      prompt: {
        ...current.prompt,
        style: `${current.prompt.style}. Reference request ${item.requestId || "n/a"} artifact ${item.outputArtifactPath || "not persisted"}`,
      },
      annotationReadiness: {
        ...(current.annotationReadiness || {}),
        comments: [
          {
            id: makeId("comment"),
            type: "comment",
            text: `Reference imported from queue: ${item.title}`,
            createdAt: nowIso(),
          },
          ...((current.annotationReadiness || {}).comments || []),
        ].slice(0, 20),
      },
    }));
    pushOperationEvent("Reference captured", `Using ${item.title} as a design reference for next refinement.`, "good");
  }

  function retryQueueItem(item) {
    runOperation(String(item?.status || "").toLowerCase().includes("edit") ? "edit" : "generate");
  }

  // Clears the canvas only: the library (history and references) and the chosen model stay.
  const canGenerate = !busy && Boolean(project.prompt.text.trim());
  function generateFromPrompt() {
    runOperation("generate", { imagePluginMode: true });
  }

  function openInEditor(historyId) {
    setEditorOpen(true);
    focusHistoryItem(historyId);
    focusFirstAnnotationForHistoryItem(historyId);
    requestAnimationFrame(() => editorRef.current?.scrollIntoView({ block: "start", behavior: "smooth" }));
  }

  function resetProject() {
    setProject(current => normalizeProject({
      ...DEFAULT_IMAGE_PROJECT,
      provider: current.provider,
      history: current.history,
      designReferences: current.designReferences,
      opsThreads: current.opsThreads,
      skillsEvidence: current.skillsEvidence,
    }));
    setProviderMessage("Canvas cleared. Your images are kept.");
  }

  function clearJumpTrailLongPressTimer() {
    if (jumpTrailLongPressRef.current) {
      window.clearTimeout(jumpTrailLongPressRef.current);
      jumpTrailLongPressRef.current = null;
    }
  }

  function revealJumpTrailChipDetails(chipId, tooltip) {
    setActiveJumpTrailChipId(chipId);
    setActiveJumpTrailTooltip(tooltip);
  }

  function hideJumpTrailChipDetails() {
    setActiveJumpTrailChipId("");
    setActiveJumpTrailTooltip("");
  }

  function toggleJumpTrailChipDetails(chipId, tooltip) {
    if (activeJumpTrailChipId === chipId) {
      hideJumpTrailChipDetails();
      return;
    }
    revealJumpTrailChipDetails(chipId, tooltip);
  }

  const canvasScale = project.canvas.zoom;
  const selectedPreset = CANVAS_SIZE_PRESETS.find(item => item.width === project.canvas.width && item.height === project.canvas.height)?.id || "custom";

  return (
    <section className="image-playground-shell">
      <input accept="image/*" className="image-hidden-input" onChange={handleImportFile} ref={fileInputRef} type="file" />
      <header className="image-playground-hero">
        <div>
          <h1>Image Studio</h1>
          <p>Describe an image and it is made for you. Everything you make or import is kept in My images.</p>
        </div>
        <div className="image-hero-actions">
          <button className="image-glass-button" onClick={() => fileInputRef.current?.click()} type="button">
            <ImagePlus size={16} /> Import
          </button>
        </div>
      </header>

      <section className="image-simple-generator image-glass-panel" aria-labelledby="image-describe-title">
        <h2 id="image-describe-title">Describe an image</h2>
        <label className="image-field image-simple-prompt">
          <span className="sr-only">Describe an image</span>
          <textarea
            onChange={event => updateProject(current => ({ ...current, prompt: { ...current.prompt, text: event.target.value } }))}
            onKeyDown={event => {
              if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && canGenerate) {
                event.preventDefault();
                generateFromPrompt();
              }
            }}
            placeholder="A quiet harbour at dawn, soft fog, two small boats, film grain"
            value={project.prompt.text}
          />
        </label>
        <div className="image-simple-actions">
          <button className="image-primary-button" disabled={!canGenerate} onClick={generateFromPrompt} type="button">
            <WandSparkles size={17} /> {busy ? "Generating…" : "Generate"}
          </button>
          <span className="image-simple-status" role="status" aria-live="polite">{providerMessage || `Model: ${provider.name}`}</span>
        </div>
      </section>

      <section className="image-library-view image-glass-panel" aria-labelledby="image-library-title">
        <div className="image-library-head">
          <h2 id="image-library-title">My images</h2>
          <span>{shownLibraryItems.length === 1 ? "1 image" : `${shownLibraryItems.length} images`}</span>
        </div>
        {shownLibraryItems.length ? (
          <div className="image-library-grid">
            {shownLibraryItems.map(item => (
              <article className="image-library-card" key={item.id || item.src}>
                <ArtifactThumb alt={item.title} onMissing={() => markLibraryFileMissing(item.src)} src={item.src} />
                <div className="image-library-meta">
                  <strong title={item.title}>{item.title}</strong>
                  {item.source ? <span>{item.source}</span> : null}
                </div>
                {item.historyId ? (
                  <button className="image-library-edit" onClick={() => openInEditor(item.historyId)} type="button">Edit</button>
                ) : null}
              </article>
            ))}
          </div>
        ) : (
          <p className="image-library-empty">Nothing here yet. Images you make or import appear here.</p>
        )}
        {missingLibraryItems.length ? (
          <ul className="image-library-missing" aria-label="Images whose file is no longer on this PC">
            {missingLibraryItems.map(item => (
              <li key={item.id || item.src}>
                <span title={item.title}>{item.title}</span>
                <small>Missing</small>
                <button onClick={() => removeLibraryItem(item)} type="button">Remove</button>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className={cx("image-editor-view image-glass-panel", editorOpen && "is-open")} aria-labelledby="image-editor-title" ref={editorRef}>
        <div className="image-editor-head">
          <div>
            <h2 id="image-editor-title">Editor</h2>
            <p>Change an image with layers, regions and masks.</p>
          </div>
          <div className="image-editor-actions">
            {editorOpen ? (
              <button className="image-glass-button" onClick={resetProject} type="button">
                <RefreshCw size={16} /> Clear canvas
              </button>
            ) : null}
            <button aria-controls="image-editor-body" aria-expanded={editorOpen} className="image-glass-button" onClick={() => setEditorOpen(open => !open)} type="button">
              {editorOpen ? "Close editor" : "Open editor"}
            </button>
          </div>
        </div>
        <div className="image-editor-body" hidden={!editorOpen} id="image-editor-body">
          <div className="image-playground-grid">
            <aside className="image-left-panel image-glass-panel">
              <div className="image-panel-head">
                <strong>Options</strong>
                <span>Model: {provider.name}</span>
              </div>
              <label className="image-field">
                <span>Style</span>
                <input
                  onChange={event => updateProject(current => ({ ...current, prompt: { ...current.prompt, style: event.target.value } }))}
                  value={project.prompt.style}
                />
              </label>
              <label className="image-field">
                <span>Leave out</span>
                <input
                  onChange={event => updateProject(current => ({ ...current, prompt: { ...current.prompt, negative: event.target.value } }))}
                  value={project.prompt.negative}
                />
              </label>
              <div className="image-control-row">
                <label className="image-field compact">
                  <span>Model</span>
                  <select
                    onChange={event => updateProject(current => ({
                      ...current,
                      provider: { ...current.provider, id: event.target.value },
                    }))}
                    value={project.provider.id}
                  >
                    {IMAGE_PROVIDER_ADAPTERS.map(item => (
                      <option key={item.id} value={item.id}>{item.name}</option>
                    ))}
                  </select>
                </label>
                <label className="image-field compact">
                  <span>Size</span>
                  <select
                    onChange={event => {
                      const preset = CANVAS_SIZE_PRESETS.find(item => item.id === event.target.value);
                      if (!preset) return;
                      updateProject(current => ({
                        ...current,
                        canvas: { ...current.canvas, width: preset.width, height: preset.height },
                        provider: { ...current.provider, size: `${preset.width}x${preset.height}` },
                      }));
                    }}
                    value={selectedPreset}
                  >
                    {CANVAS_SIZE_PRESETS.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
                  </select>
                </label>
              </div>
              <label className="image-range">
                <span>Follow the canvas <b>{Math.round(project.prompt.strength * 100)}%</b></span>
                <input
                  max="1"
                  min="0"
                  onChange={event => updateProject(current => ({ ...current, prompt: { ...current.prompt, strength: Number(event.target.value) } }))}
                  step="0.01"
                  type="range"
                  value={project.prompt.strength}
                />
              </label>
              <label className="image-checkbox">
                <input
                  checked={project.prompt.preserveComposition}
                  onChange={event => updateProject(current => ({ ...current, prompt: { ...current.prompt, preserveComposition: event.target.checked } }))}
                  type="checkbox"
                />
                Keep my layout on the next change
              </label>
              <div className="image-provider-card">
                <WandSparkles size={18} />
                <div>
                  <strong>{provider.name}</strong>
                  <p>{provider.description}</p>
                </div>
              </div>
              <button className="image-primary-button full" disabled={busy} onClick={() => runOperation("edit")} type="button">
                <Blend size={17} /> Update image from canvas
              </button>
              {providerBlockedState ? (
                <div className="image-provider-fallback" role="status">
                  <strong>{providerBlockedState.provider} couldn't make this image</strong>
                  <p>{providerBlockedState.message}</p>
                  {providerBlockedDiagnostics.length ? (
                    <dl className="image-provider-diagnostics">
                      {providerBlockedDiagnostics.map(([label, value]) => (
                        <div key={label}>
                          <dt>{label}</dt>
                          <dd>{value}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : null}
                                </div>
              ) : null}
              <p className="image-status-line">{providerMessage}</p>
            </aside>

            <main className="image-canvas-column">
              <div className="image-toolbar image-glass-panel">
                {IMAGE_TOOL_DEFINITIONS.map(tool => (
                  <button
                    className={cx("image-tool", project.activeTool === tool.id && "active")}
                    key={tool.id}
                    onClick={() => updateProject(current => ({ ...current, activeTool: tool.id }))}
                    title={tool.hint}
                    type="button"
                  >
                    {tool.id === "select" ? <Move size={16} /> : tool.id === "region" ? <Crop size={16} /> : tool.id === "mask" ? <Scissors size={16} /> : <SplitSquareHorizontal size={16} />}
                    {tool.label}
                  </button>
                ))}
                <button className="image-tool" onClick={addShapeLayer} type="button"><Plus size={16} /> Layer</button>
                <button className="image-tool" onClick={() => fileInputRef.current?.click()} type="button"><ImagePlus size={16} /> Import</button>
                <span className="image-toolbar-spacer" />
                <label className="image-zoom-control">
                  Zoom
                  <input
                    max="1.15"
                    min="0.32"
                    onChange={event => updateProject(current => ({ ...current, canvas: { ...current.canvas, zoom: Number(event.target.value) } }))}
                    step="0.01"
                    type="range"
                    value={project.canvas.zoom}
                  />
                </label>
              </div>

              <div className="image-toolbar image-glass-panel image-annotation-toolbar" role="status" aria-live="polite">
                <strong>Notes on the image</strong>
                <span>{focusedHistoryItem ? libraryTitle(focusedHistoryItem) : "Pick an image in Versions"}</span>
                <button className="image-tool" onClick={addFocusedPin} type="button">Add pin</button>
                <button className="image-tool" onClick={addFocusedRectangle} type="button">Add rectangle</button>
                <button className="image-tool" onClick={addFocusedComment} type="button">Add comment</button>
                <button className="image-primary-button" onClick={createIssueThreadFromFocusedHistory} type="button">Create issue thread</button>
                {!annotationOnboardingDismissed ? (
                  <div className="image-annotation-onboarding-tip" role="status">
                    <span>Tip: select a pin or rectangle to nudge with keyboard controls.</span>
                    <button
                      className="image-mini-button"
                      onClick={() => {
                        setAnnotationOnboardingDismissed(true);
                        if (typeof window !== "undefined") {
                          window.localStorage.setItem("image-playground-annotation-onboarding-dismissed", "1");
                        }
                      }}
                      type="button"
                    >
                      Got it
                    </button>
                  </div>
                ) : null}
                {currentActiveAnnotation() ? (
                  <label className="image-annotation-toolbar-comment">
                    Note
                    <input
                      onChange={event => {
                        if (activeAnnotationTarget.kind === "pin") {
                          updateFocusedPin(activeAnnotationTarget.id, { comment: event.target.value });
                        } else if (activeAnnotationTarget.kind === "rectangle") {
                          updateFocusedRectangle(activeAnnotationTarget.id, { comment: event.target.value });
                        }
                      }}
                      placeholder="Selected annotation note"
                      value={currentActiveAnnotation()?.comment || ""}
                    />
                  </label>
                ) : null}
                {currentActiveAnnotation() ? (
                  <div className={cx("image-annotation-keyboard-legend", annotationLegendCollapsed && "collapsed")}>
                    <button
                      className="image-mini-button"
                      onClick={() => setAnnotationLegendCollapsed(value => !value)}
                      type="button"
                    >
                      {annotationLegendCollapsed ? "Show keys" : "Hide keys"}
                    </button>
                    <p id="image-annotation-keyboard-legend-hint">
                      {annotationKeyLabels.move} move, {annotationKeyLabels.fastMove} fast move, {annotationKeyLabels.deleteKey} remove, {annotationKeyLabels.closeKey} close.
                    </p>
                  </div>
                ) : (
                  <p className="image-annotation-keyboard-legend sr-only" id="image-annotation-keyboard-legend-hint">
                    Select a history item with kbd ready to use arrows for nudge, delete to remove, and escape to close annotation focus.
                  </p>
                )}
              </div>

              <div className="image-canvas-stage image-glass-panel">
                <div className="image-canvas-rulers">
                  <span>{project.canvas.width} × {project.canvas.height}</span>
                  <span>{project.activeTool === "select" ? "Drag layers" : "Drag to define region"}</span>
                </div>
                <div className="image-canvas-viewport">
                  <div
                    className="image-canvas"
                    onPointerDown={startSelectionDrag}
                    onPointerMove={handlePointerMove}
                    onPointerUp={handlePointerUp}
                    ref={canvasRef}
                    style={{
                      width: `${project.canvas.width}px`,
                      height: `${project.canvas.height}px`,
                      transform: `scale(${canvasScale})`,
                      background: project.canvas.background,
                    }}
                  >
                    <div className="image-canvas-grid" />
                    {visibleLayers.map(layer => (
                      <div
                        className={cx("image-canvas-layer", layer.locked && "locked", layer.id === project.selectedLayerId && "selected")}
                        key={layer.id}
                        data-name={layer.name}
                        onPointerDown={event => startLayerDrag(event, layer)}
                        style={canvasLayerStyle(layer, layer.id === project.selectedLayerId)}
                      >
                        {layer.type === "image" && layer.src ? <img alt={layer.nativeAssetId ? layer.name : ""} draggable="false" src={layer.src}
                          ref={layer.nativeAssetId === nativeAsset?.id ? nativeImageRef : undefined}
                          onLoad={event => { if (layer.nativeAssetId === nativeAsset?.id && event.currentTarget.naturalWidth > 0) { event.currentTarget.scrollIntoView({ block: 'center', inline: 'nearest' }); setNativeDecoded(layer.nativeAssetId); } }}
                          onError={() => { if (layer.nativeAssetId) { setProviderMessage('The requested image could not be loaded. Open the source again to retry.'); onNativeImageState?.({ status: 'error', assetId: layer.nativeAssetId, error: 'Image could not be decoded' }); } }} /> : null}
                        {layer.id === project.selectedLayerId && !layer.locked ? (
                          <button className="image-resize-handle" onPointerDown={event => startResize(event, layer)} type="button" />
                        ) : null}
                      </div>
                    ))}
                    {(focusedOverlaySnapshot.pins.length || focusedOverlaySnapshot.rectangles.length) ? (
                      <div className="image-canvas-overlays" aria-label="Focused queue annotations">
                        {focusedOverlaySnapshot.rectangles.map(rect => {
                          const active = activeAnnotationTarget.kind === "rectangle" && activeAnnotationTarget.id === rect.id;
                          return (
                            <div
                              className={cx("image-annotation-rect", "canvas", active && "active")}
                              key={`rect-canvas-edit-${rect.id}`}
                              onPointerDown={event => startRectangleDrag(event, rect)}
                              style={{
                                left: `${rect.x}px`,
                                top: `${rect.y}px`,
                                width: `${rect.width}px`,
                                height: `${rect.height}px`,
                              }}
                              title={rect.comment || "Annotation region"}
                            >
                              <button className="image-annotation-resize-handle" onPointerDown={event => startRectangleResize(event, rect)} type="button" />
                              {active ? (
                                <input
                                  className="image-annotation-inline-comment"
                                  onChange={event => updateFocusedRectangle(rect.id, { comment: event.target.value })}
                                  onPointerDown={event => event.stopPropagation()}
                                  placeholder="Rectangle note"
                                  value={rect.comment || ""}
                                />
                              ) : null}
                            </div>
                          );
                        })}
                        {focusedOverlaySnapshot.pins.map((pin, index) => {
                          const active = activeAnnotationTarget.kind === "pin" && activeAnnotationTarget.id === pin.id;
                          return (
                            <button
                              className={cx("image-annotation-pin", "canvas", active && "active")}
                              key={`pin-canvas-edit-${pin.id || index}`}
                              onPointerDown={event => startPinDrag(event, pin)}
                              style={{ left: `${pin.x}px`, top: `${pin.y}px` }}
                              title={pin.comment || "Annotation pin"}
                              type="button"
                            >
                              <span>{index + 1}</span>
                              {active ? (
                                <input
                                  className="image-annotation-inline-comment"
                                  onChange={event => updateFocusedPin(pin.id, { comment: event.target.value })}
                                  onPointerDown={event => event.stopPropagation()}
                                  placeholder="Pin note"
                                  value={pin.comment || ""}
                                />
                              ) : null}
                            </button>
                          );
                        })}
                      </div>
                    ) : null}
                    {project.selection.visible ? (
                      <div
                        className={cx("image-region-selection", project.activeTool === "mask" && "mask")}
                        style={{
                          left: `${project.selection.x}px`,
                          top: `${project.selection.y}px`,
                          width: `${project.selection.width}px`,
                          height: `${project.selection.height}px`,
                        }}
                      >
                        <span>{project.activeTool === "mask" ? "Mask" : "Region"}</span>
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            </main>

            <aside className="image-right-panel">
              <section className="image-glass-panel image-layer-panel">
                <div className="image-panel-head">
                  <strong><Layers3 size={16} /> Layers</strong>
                  <button className="image-mini-button" onClick={addShapeLayer} type="button"><Plus size={14} /> Add</button>
                </div>
                <div className="image-layer-list">
                  {[...project.layers].reverse().map(layer => (
                    <article className={cx("image-layer-row", layer.id === project.selectedLayerId && "active")} key={layer.id} onClick={() => selectLayer(layer.id)}>
                      <button onClick={event => { event.stopPropagation(); updateLayer(layer.id, { visible: layer.visible === false }); }} type="button">
                        {layer.visible === false ? <EyeOff size={15} /> : <Eye size={15} />}
                      </button>
                      <div className="image-layer-thumb" style={{ background: layer.type === "shape" ? layer.fill : "color-mix(in srgb, var(--nx-text) 8%, transparent)" }}>
                        {layer.type === "image" && layer.src ? <img alt="" src={layer.src} /> : null}
                      </div>
                      <div>
                        <strong>{layer.name}</strong>
                        <span>{layer.promptRole || layer.type}</span>
                      </div>
                      {layer.locked ? <Lock size={14} /> : null}
                    </article>
                  ))}
                </div>
              </section>

              <section className="image-glass-panel image-inspector-panel">
                <div className="image-panel-head">
                  <strong><ChevronsUpDown size={16} /> Inspector</strong>
                  <span>{selectedLayer?.name || "No layer"}</span>
                </div>
                {selectedLayer ? (
                  <>
                    <input
                      className="image-name-input"
                      onChange={event => updateLayer(selectedLayer.id, { name: event.target.value })}
                      value={selectedLayer.name}
                    />
                    <div className="image-transform-grid">
                      {[
                        ["x", "X"], ["y", "Y"], ["width", "W"], ["height", "H"], ["rotation", "Rot"], ["opacity", "Opacity"],
                      ].map(([key, label]) => (
                        <label key={key}>
                          <span>{label}</span>
                          <input
                            max={key === "opacity" ? 1 : undefined}
                            min={key === "opacity" ? 0 : undefined}
                            onChange={event => updateLayer(selectedLayer.id, { [key]: key === "opacity" ? Number(event.target.value) : Number(event.target.value) })}
                            step={key === "opacity" ? 0.01 : 1}
                            type="number"
                            value={Number(selectedLayer[key] ?? 0)}
                          />
                        </label>
                      ))}
                    </div>
                    <label className="image-field compact">
                      <span>Prompt role</span>
                      <input onChange={event => updateLayer(selectedLayer.id, { promptRole: event.target.value })} value={selectedLayer.promptRole || ""} />
                    </label>
                    <div className="image-inspector-actions">
                      <button onClick={() => reorderLayer(selectedLayer.id, 1)} type="button"><BringToFront size={15} /> Up</button>
                      <button onClick={() => reorderLayer(selectedLayer.id, -1)} type="button"><Layers3 size={15} /> Down</button>
                      <button onClick={() => duplicateLayer(selectedLayer.id)} type="button"><Boxes size={15} /> Duplicate</button>
                    </div>
                  </>
                ) : <p>No layer selected.</p>}
              </section>

              <section className="image-glass-panel image-history-panel">
                <div className="image-panel-head">
                  <strong><SplitSquareHorizontal size={16} /> Versions</strong>
                  <span>{realImageSessions.length}</span>
                </div>
                <p className="image-keyboard-traversal-announcer sr-only" aria-live="off">
                  Keyboard traversal ready
                </p>
                <p className="image-keyboard-traversal-live sr-only" role="status" aria-live="polite" aria-atomic="true">
                  {keyboardTraversalAnnouncement || "Keyboard traversal ready"}
                </p>
                <small className="image-keyboard-traversal-microcopy sr-only" aria-live="off">
                  Arrows move • PageUp/PageDown switch scope • Home/End jump edges
                </small>
                <div className="image-keyboard-jump-trail" aria-live="polite" aria-label="Recent keyboard jumps">
                  {keyboardJumpTrail.length ? keyboardJumpTrail.slice().reverse().map((entry, index) => {
                    const chipTooltip = formatKeyboardJumpTrailTooltip(entry);
                    const chipId = `${entry.at || "na"}-${entry.reason || "focus"}-${index}`;
                    const expanded = activeJumpTrailChipId === chipId;
                    return (
                      <button
                        aria-expanded={expanded}
                        aria-label={chipTooltip}
                        className="image-keyboard-jump-chip"
                        data-reason={entry.reason || "focus"}
                        key={chipId}
                        onBlur={event => {
                          if (!event.currentTarget.contains(event.relatedTarget)) {
                            hideJumpTrailChipDetails();
                          }
                        }}
                        onClick={() => toggleJumpTrailChipDetails(chipId, chipTooltip)}
                        onPointerDown={() => {
                          clearJumpTrailLongPressTimer();
                          jumpTrailLongPressRef.current = window.setTimeout(() => {
                            revealJumpTrailChipDetails(chipId, chipTooltip);
                          }, 420);
                        }}
                        onPointerUp={clearJumpTrailLongPressTimer}
                        onPointerLeave={clearJumpTrailLongPressTimer}
                        title={chipTooltip}
                        type="button"
                      >
                        {formatKeyboardJumpTrailEntry(entry)}
                      </button>
                    );
                  }) : null}
                </div>
                {activeJumpTrailTooltip ? (
                  <div className="image-keyboard-jump-popover" role="status" aria-live="polite">
                    {activeJumpTrailTooltip}
                  </div>
                ) : null}
                <div className="image-history-list">
                  {realImageSessions.map(item => {
                    const keyboardReady = hasKeyboardReadyAnnotations(item.annotationSnapshot);
                    const manifestReceiptLink = resolveManifestReceiptLink(item);
                    const historyPreview = imageSourceForRecord(item);
                    return (
                      <article
                        aria-describedby={keyboardReady ? "image-annotation-keyboard-legend-hint" : undefined}
                        className={cx(
                          "image-history-card",
                          compareHistoryId === item.id && "active",
                          syncedFocusedHistoryId === item.id && "focus-sync",
                          keyboardReady && "kbd-ready",
                        )}
                        key={item.id}
                        onClick={() => focusHistoryItem(item.id)}
                        onFocus={() => focusHistoryItem(item.id)}
                        onKeyDown={event => handleKeyboardReadyCardKeyDown(event, item.id, "history", keyboardReady)}
                        ref={node => {
                          if (node) historyCardRefs.current.set(item.id, node);
                          else historyCardRefs.current.delete(item.id);
                        }}
                        role="button"
                        tabIndex={item.id === syncedFocusedHistoryId ? 0 : -1}
                      >
                        <span><Check size={13} /> {item.status || "ready"}</span>
                        <strong>{item.title || "History item"}</strong>
                        {historyPreview ? (
                          <div className="image-history-preview">
                            <img alt={item.title || "History image preview"} src={historyPreview} />
                          </div>
                        ) : null}
                        {keyboardReady ? <small className="image-kbd-ready-badge">kbd ready</small> : null}
                        <small className="image-card-index-indicator image-card-scope-label" aria-label={`Keyboard card index ${groupedCardIndexIndicator("history", item.id)}`}>{groupedCardIndexIndicator("history", item.id)}</small>
                        {keyboardReady ? (
                          <button
                            className="image-mini-button"
                            onClick={event => {
                              event.stopPropagation();
                              focusFirstAnnotationForHistoryItem(item.id);
                            }}
                            type="button"
                          >
                            Focus first annotation
                          </button>
                        ) : null}
                        {manifestReceiptLink ? (
                          <a
                            className="image-manifest-receipt-link"
                            href={manifestReceiptLink.href}
                            onClick={event => event.stopPropagation()}
                          >
                            {manifestReceiptLink.label}
                          </a>
                        ) : null}
                        <em>{formatTime(item.createdAt)}</em>
                      </article>
                    );
                  })}
                  {realImageSessions.length === 0 ? (
                    <p className="image-queue-empty">No versions yet. Generate an image or import one.</p>
                  ) : null}
                </div>
              </section>
            </aside>
          </div>
          <details className="image-receipts-drawer">
            <summary>Activity and receipts</summary>
            <div className="image-receipts-grid">
              <div className="image-workflow-card" role="status" aria-live="polite">
                <strong>Generation workflow</strong>
                <ol>
                  {workflowSteps.map(step => (
                    <li className={cx(step.complete ? "complete" : "pending")} key={step.id}>
                      <span>{step.complete ? "✓" : "○"}</span>
                      <span>{step.label}</span>
                    </li>
                  ))}
                </ol>
                <div className="image-workflow-next">
                  <div>
                    <b>{nextGuidedAction.title}</b>
                    <p>{nextGuidedAction.detail}</p>
                  </div>
                  <button className="image-mini-button" onClick={handleNextGuidedAction} type="button">{nextGuidedAction.cta}</button>
                </div>
              </div>
              <div className="image-provider-quick-metrics" role="status">
                <span>Visible layers: <b>{visibleLayers.length}</b></span>
                <span>Queue: <b>{queueSummary.running}</b> running / <b>{queueSummary.pending}</b> pending</span>
                <span>Minted sessions: <b>{realImageSessions.length}</b></span>
              </div>
              <div className="image-design-reference-panel" role="status" aria-live="polite">
                <strong>Design references</strong>
                <div className="image-reference-list">
                  {(project.designReferences || []).map(ref => {
                    const referenceImage = imageSourceForRecord(ref);
                    return (
                      <article className={cx("image-reference-row", referenceImage && "has-image")} key={ref.id}>
                        {referenceImage ? (
                          <div className="image-reference-thumb">
                            <img alt={ref.title || "Generated design reference"} src={referenceImage} />
                          </div>
                        ) : null}
                        <div>
                          <b>{ref.title}</b>
                          <small>{ref.rationale || ref.kind}</small>
                          {ref.requestId ? <code>{ref.requestId}</code> : null}
                        </div>
                      </article>
                    );
                  })}
                </div>
              </div>
              {selectedGeneratedDesignReference ? (
                <div className="image-design-reference-panel image-artifact-manifest-receipt" id="artifact-manifest-receipt" role="status" aria-live="polite">
                  <strong>Artifact manifest receipt</strong>
                  <div className="image-reference-list">
                    <article className="image-reference-row">
                      {selectedGeneratedDesignReferenceUrl ? (
                        <div className="image-reference-thumb large">
                          <img alt="Selected generated artifact" src={selectedGeneratedDesignReferenceUrl} />
                        </div>
                      ) : null}
                      <b>{selectedGeneratedDesignReference.artifactId || selectedGeneratedDesignReference.requestId || "generated-reference"}</b>
                      <small>{selectedGeneratedDesignReference.source || "generated-image"}</small>
                      <code>{shortHash(selectedGeneratedDesignReference.artifactSha256)}</code>
                      <code>{shortHash(selectedGeneratedDesignReference.manifestSha256)}</code>
                      {selectedGeneratedDesignReference.artifactPath ? <small>{selectedGeneratedDesignReference.artifactPath}</small> : null}
                      {selectedGeneratedManifestUrl ? (
                        <a className="image-manifest-receipt-link" href={selectedGeneratedManifestUrl} rel="noreferrer" target="_blank">
                          Open manifest JSON
                        </a>
                      ) : selectedGeneratedDesignReference.manifestPath ? <small>{selectedGeneratedDesignReference.manifestPath}</small> : null}
                    </article>
                  </div>
                </div>
              ) : null}
              <div className="image-design-reference-panel" role="status">
                <strong>Annotation readiness</strong>
                <div className="image-queue-summary">
                  <span className="queue-chip pending">Pins {(project.annotationReadiness?.pins || []).length}</span>
                  <span className="queue-chip pending">Rectangles {(project.annotationReadiness?.rectangles || []).length}</span>
                  <span className="queue-chip pending">Layers {(project.annotationReadiness?.layers || []).length}</span>
                  <span className="queue-chip pending">Comments {(project.annotationReadiness?.comments || []).length}</span>
                </div>
              </div>
              <div className="image-design-reference-panel" role="status">
                <strong>Skill evidence</strong>
                <div className="image-reference-list">
                  {(project.skillsEvidence || []).slice(0, 3).map(item => (
                    <article className="image-reference-row" key={item.id}>
                      <b>{item.selectedSkills?.join(", ") || "skills"}</b>
                      <small>{item.why}</small>
                      <code>{item.requestId || "no-request"}</code>
                      {item.skillInvocation?.status ? (
                        <small>{`${item.skillInvocation.status} · ${item.skillInvocation.sourceKind || "installed"} · ${shortHash(item.skillInvocation.skillSha256)}`}</small>
                      ) : null}
                    </article>
                  ))}
                </div>
              </div>

              <section className="image-glass-panel image-history-panel">
                <div className="image-panel-head">
                  <strong>Generation queue</strong>
                  <span>{queueItems.length}</span>
                </div>
                <p className="image-status-line image-queue-headline">{queueFlow.headline}</p>
                <div className="image-queue-progress" role="status" aria-live="polite">
                  <div className="image-queue-progress-bar" style={{ width: `${queueFlow.percent}%` }} />
                </div>
                <div className="image-queue-summary" role="status">
                  <span className="queue-chip running">Running {queueSummary.running}</span>
                  <span className="queue-chip pending">Pending {queueSummary.pending}</span>
                  <span className="queue-chip done">Done {queueSummary.done}</span>
                  <span className="queue-chip failed">Failed {queueSummary.failed}</span>
                </div>
                <div className="image-history-list">
                  {queueItems.length === 0 ? (
                    <p className="image-queue-empty">No queue entries yet. Import a source or run Generate to create a tracked request.</p>
                  ) : queueItems.map(item => {
                    const keyboardReady = hasKeyboardReadyAnnotations(item.annotationSnapshot);
                    const manifestReceiptLink = resolveManifestReceiptLink(item);
                    return (
                    <button
                      aria-describedby={keyboardReady ? "image-annotation-keyboard-legend-hint" : undefined}
                      className={cx(
                        "image-queue-row",
                        `state-${item.state}`,
                        item.state === "running" && "active",
                        compareHistoryId === item.id && "evidence-focus",
                        syncedFocusedHistoryId === item.id && "focus-sync",
                        keyboardReady && "kbd-ready",
                      )}
                      key={item.id}
                      onClick={() => focusHistoryItem(item.id)}
                      onFocus={() => focusHistoryItem(item.id)}
                      onKeyDown={event => handleKeyboardReadyCardKeyDown(event, item.id, "queue", keyboardReady)}
                      ref={node => {
                        if (node) queueCardRefs.current.set(item.id, node);
                        else queueCardRefs.current.delete(item.id);
                      }}
                      tabIndex={item.id === syncedFocusedHistoryId ? 0 : -1}
                      type="button"
                    >
                      <span><Check size={13} /> {item.status}</span>
                      <strong>{item.title}</strong>
                      {keyboardReady ? <small className="image-kbd-ready-badge">kbd ready</small> : null}
                      <small className="image-card-index-indicator image-card-scope-label" aria-label={`Keyboard card index ${groupedCardIndexIndicator("queue", item.id)}`}>{groupedCardIndexIndicator("queue", item.id)}</small>
                      <small>{queueFlow.stageMeta[item.state]?.label || "Pending"} · {queueFlow.stageMeta[item.state]?.detail || "Awaiting update"}</small>
                      {item.generatedPreview ? (
                        <div className="image-queue-preview">
                          <img alt="Generated preview" src={item.generatedPreview} />
                          {(item.annotationSnapshot?.pins?.length || item.annotationSnapshot?.rectangles?.length) ? (
                            <div className="image-queue-preview-overlays" aria-label="Queue annotation overlays">
                              {renderOverlayShapes(item.annotationSnapshot, "queue")}
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                      <div className="image-queue-timeline" role="status" aria-label="Request timeline stages">
                        {item.queueTimeline.map(stage => (
                          <span className={cx("queue-chip", `severity-${stage.severity || "info"}`)} key={`${item.id}-${stage.stage}`}>
                            {stage.stage} · {formatTime(stage.at)}
                          </span>
                        ))}
                      </div>
                      <div className="image-receipt-strip" role="status" aria-label="Verification receipt">
                        <span><b>Hash</b> {item.receipt?.promptHash || "--------"}</span>
                        <span><b>Layers</b> {item.receipt?.layerCount ?? 0}</span>
                        <span><b>Provider</b> {item.receipt?.providerName || "unknown"}</span>
                        <span><b>Route</b> {providerRouteFromReceipt(item.receipt)}</span>
                        <span className={cx("receipt-test-status", item.state === "failed" ? "bad" : item.state === "running" ? "warn" : "good")}><b>Test</b> {item.receipt?.testStatus || "Pending"}</span>
                      </div>
                      <div className="image-request-meta" role="status" aria-label="Provider request metadata">
                        <span><b>Request</b> <code>{item.requestId || "pending-request-id"}</code></span>
                        <span><b>Status</b> {item.providerStatus || "unknown"}</span>
                        <span><b>Artifact</b> <code>{item.outputArtifactPath || "Not persisted"}</code></span>
                        <span><b>Queued</b> {formatDateTime(item.requestTimeline?.queuedAt || item.createdAt)}</span>
                        <span><b>Completed</b> {formatDateTime(item.requestTimeline?.completedAt)}</span>
                        <span><b>Handoff</b> {item.layerHandoff?.stage || "pending"} {item.layerHandoff?.layerId ? `→ ${item.layerHandoff.layerId}` : ""}</span>
                        <span><b>Issue thread</b> <code>{item.issueThread?.id || "pending"}</code></span>
                        <span><b>Failure severity</b> {item.failureSeverity}</span>
                        <span><b>Recovery action</b> {item.recoveryAction}</span>
                      </div>
                      {item.receipt?.failureReason ? (
                        <small className="image-thread-meta">Blocked route receipt: {item.receipt.failureReason} · prompt evidence captured.</small>
                      ) : null}
                      <div className="image-skill-actions image-queue-actions">
                        {keyboardReady ? (
                          <button
                            disabled={busy}
                            onClick={event => { event.stopPropagation(); focusFirstAnnotationForHistoryItem(item.id); }}
                            type="button"
                          >
                            Focus first annotation
                          </button>
                        ) : null}
                        <button disabled={busy} onClick={event => { event.stopPropagation(); useQueueImageAsReference(item); }} type="button">Use as design reference</button>
                        <button disabled={busy} onClick={event => { event.stopPropagation(); retryQueueItem(item); }} type="button">Retry / recover</button>
                        <a className="image-thread-link" href={item.issueThread?.href || "#"} onClick={event => event.stopPropagation()}>{item.issueThread?.id || "Open issue thread"}</a>
                        {manifestReceiptLink ? (
                          <a className="image-manifest-receipt-link" href={manifestReceiptLink.href} onClick={event => event.stopPropagation()}>{manifestReceiptLink.label}</a>
                        ) : null}
                      </div>
                      {item.prompt ? <p>{item.prompt}</p> : null}
                      <em>{formatTime(item.createdAt)}</em>
                    </button>
                  );
                  })}
                </div>
              </section>

              <section className="image-glass-panel image-history-panel image-ops-thread-panel" id="issue-thread-panel">
                <div className="image-panel-head">
                  <strong>Active issue threads</strong>
                  <span>{project.opsThreads?.length || 0}</span>
                </div>
                <div className="image-history-list">
                  {(project.opsThreads || []).length ? (project.opsThreads || []).map(thread => {
                    const activeRef = project.annotationReadiness?.activeThreadRef || activeOpsThreadId;
                    const active = activeRef === thread.id;
                    return (
                      <article className={cx("image-ops-thread-row", active && "active")} id={`issue-thread-${encodeURIComponent(thread.id)}`} key={thread.id}>
                        <header>
                          <strong>{thread.title || "Issue thread"}</strong>
                          <em>{formatTime(thread.updatedAt || thread.createdAt)}</em>
                        </header>
                        <p>{thread.id}</p>
                        <div className="image-thread-message-list">
                          {(thread.messages || []).length ? thread.messages.map(msg => (
                            <span key={msg.id || `${thread.id}-${msg.createdAt}`}>{msg.text || "Update"} · {formatDateTime(msg.createdAt)}</span>
                          )) : <span>No messages yet.</span>}
                        </div>
                        <a className="image-thread-link" href={project.history.find(item => item.issueThread?.id === thread.id)?.issueThread?.href || `#issue-thread-${encodeURIComponent(thread.id)}`}>Open issue thread link</a>
                      </article>
                    );
                  }) : <p className="image-queue-empty">No issue threads yet. Use Create issue thread in the annotation toolbar.</p>}
                </div>
              </section>

              <section className="image-glass-panel image-skill-lifecycle-panel">
                <div className="image-panel-head">
                  <strong>Skill creation lifecycle</strong>
                  <span>{skillDrafts.length}</span>
                </div>
                <div className="image-queue-summary" role="status">
                  <span className="queue-chip pending">Draft {skillSummary.draft}</span>
                  <span className="queue-chip running">Review {skillSummary.review}</span>
                  <span className="queue-chip done">Test {skillSummary.test}</span>
                  <span className="queue-chip complete">Publish {skillSummary.published}</span>
                </div>
                <p className="image-status-line image-skill-notice">{skillNotice}</p>
                <div className="image-design-decision-matrix" aria-label="Design decisions applied">
                  {DESIGN_DECISION_MATRIX.map(item => (
                    <article className="image-design-decision-card" key={item.id}>
                      <span>Design decisions applied</span>
                      <strong>{item.title}</strong>
                      <p>Used artifact: {item.usedArtifact}</p>
                      <small>{item.appliedDecision}</small>
                      <small>Skill draft implication: {item.skillImplication}</small>
                      <small>Mobile-safe check: {item.mobileCheck}</small>
                    </article>
                  ))}
                </div>
                <div className="image-approval-console" role="status" aria-live="polite">
                  <strong>Operator approval console</strong>
                  <div className="image-approval-buckets">
                    <article className="image-approval-bucket tone-warn">
                      <header>
                        <b>Missing receipt</b>
                        <span>{approvalBuckets.missingReceipt.length}</span>
                      </header>
                      <p>Drafts without linked evidence cannot enter formal review.</p>
                      {approvalBuckets.missingReceipt[0] ? (
                        <button onClick={() => runApprovalQuickFix("missing-receipt", approvalBuckets.missingReceipt[0])} type="button">
                          Link receipt for {approvalBuckets.missingReceipt[0].title}
                        </button>
                      ) : <small>All drafts have receipt links.</small>}
                    </article>
                    <article className="image-approval-bucket tone-warn">
                      <header>
                        <b>Receipt not verified</b>
                        <span>{approvalBuckets.receiptNotVerified.length}</span>
                      </header>
                      <p>Evidence exists, but queue/test verification is still pending.</p>
                      {approvalBuckets.receiptNotVerified[0] ? (
                        <button onClick={() => runApprovalQuickFix("receipt-not-verified", approvalBuckets.receiptNotVerified[0])} type="button">
                          Open evidence for {approvalBuckets.receiptNotVerified[0].title}
                        </button>
                      ) : <small>No unverified receipts blocking publish flow.</small>}
                    </article>
                    <article className="image-approval-bucket tone-info">
                      <header>
                        <b>Not yet in test state</b>
                        <span>{approvalBuckets.notInTestState.length}</span>
                      </header>
                      <p>Verified drafts must reach Test before publish approval is allowed.</p>
                      {approvalBuckets.notInTestState[0] ? (
                        <button onClick={() => runApprovalQuickFix("not-in-test", approvalBuckets.notInTestState[0])} type="button">
                          Advance {approvalBuckets.notInTestState[0].title}
                        </button>
                      ) : <small>No drafts waiting for review/test transition.</small>}
                    </article>
                    <article className="image-approval-bucket tone-good">
                      <header>
                        <b>Publish ready</b>
                        <span>{approvalBuckets.publishReady.length}</span>
                      </header>
                      <p>Drafts in Test with verified evidence are ready for publish decision.</p>
                      {approvalBuckets.publishReady[0] ? (
                        <button onClick={() => moveSkillDraftState(approvalBuckets.publishReady[0].id, "published")} type="button">
                          Publish {approvalBuckets.publishReady[0].title}
                        </button>
                      ) : <small>No publish-ready drafts in this slice.</small>}
                    </article>
                  </div>
                </div>
                {activeReadinessDraft ? (
                  <div className="image-publish-readiness-drawer" role="status" aria-live="polite">
                    <div className="image-publish-readiness-head">
                      <strong>Publish readiness drawer</strong>
                      <select value={activeReadinessDraft.id} onChange={event => setActiveReadinessDraftId(event.target.value)}>
                        {skillDrafts.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
                      </select>
                    </div>
                    <p>Acceptance checklist for {activeReadinessDraft.title}</p>
                    <div className="image-publish-checklist">
                      {readinessChecklist?.checklist.map(item => (
                        <article className={cx("image-publish-check", item.ok ? "ok" : "blocked")} key={item.key}>
                          <b>{item.label}</b>
                          <span>{item.detail}</span>
                        </article>
                      ))}
                    </div>
                    {readinessChecklist?.blockedReasons?.length ? (
                      <div className="image-publish-blockers">
                        <strong>Fail reasons</strong>
                        <ul>
                          {readinessChecklist.blockedReasons.map(reason => <li key={reason}>{reason}</li>)}
                        </ul>
                        <div className="image-publish-actions">
                          <button onClick={() => runReadinessRemediation("link", activeReadinessDraft)} type="button">Link receipt</button>
                          <button disabled={!activeReadinessDraft.linkedReceiptId} onClick={() => runReadinessRemediation("evidence", activeReadinessDraft)} type="button">Open evidence</button>
                          <button onClick={() => runReadinessRemediation("test", activeReadinessDraft)} type="button">Run verification</button>
                          <button onClick={() => runReadinessRemediation("review", activeReadinessDraft)} type="button">Advance lifecycle</button>
                          <button onClick={() => runReadinessRemediation("signoff", activeReadinessDraft)} type="button">Reviewer sign-off</button>
                        </div>
                      </div>
                    ) : (
                      <div className="image-publish-ready">All publish checks passed. Draft can be published now.</div>
                    )}
                  </div>
                ) : null}
                <div className="image-publish-readiness-drawer" role="status" aria-live="polite">
                  <div className="image-publish-readiness-head">
                    <strong>Cross-surface handoff receipts</strong>
                    <span>{publishedHandoffRows.length}</span>
                  </div>
                  <p>Each published draft is linked to queue evidence and a notification thread, with explicit sync/live checkpoints.</p>
                  {publishedHandoffRows.length ? (
                    <div className="image-skill-draft-list">
                      {publishedHandoffRows.map(row => (
                        <article className="image-skill-draft" key={`handoff-${row.draft.id}`}>
                          <div className="image-skill-draft-head">
                            <strong>{row.draft.title}</strong>
                            <span className="image-skill-state state-published">Published</span>
                          </div>
                          <div className="image-skill-evidence">
                            <span className={cx("evidence-chip", row.linkedReceipt ? "good" : "pending")}>Receipt {row.linkedReceipt?.receipt?.promptHash || "Missing"}</span>
                            <span className={cx("evidence-chip", row.outcomeEvent ? "good" : "pending")}>Thread {row.outcomeEvent ? formatTime(row.outcomeEvent.createdAt) : "Missing"}</span>
                            <span className={cx("evidence-chip", row.syncConfirmedAt ? "good" : "pending")}>Web-control sync {row.syncConfirmedAt ? "Confirmed" : "Pending"}</span>
                            <span className={cx("evidence-chip", row.backendConfirmedAt ? "good" : "pending")}>Backend live {row.backendConfirmedAt ? "Confirmed" : "Pending"}</span>
                          </div>
                          <small className="image-skill-evidence-meta">
                            Receipt route {providerRouteFromReceipt(row.linkedReceipt?.receipt)} · Provider {row.linkedReceipt?.receipt?.providerName || "unknown"}
                          </small>
                          <div className="image-provenance-strip" role="status" aria-label="Publish provenance snapshot">
                            <span><b>Snapshot hash</b> {row.storedReceiptHash || "Missing"}</span>
                            <span><b>Route</b> {row.storedProviderRoute || "Missing"}</span>
                            <span><b>Provider</b> {row.storedProviderName || "Missing"}</span>
                            <span><b>Test at</b> {row.storedTestTimestamp ? formatDateTime(row.storedTestTimestamp) : "Missing"}</span>
                            <span><b>Reviewer</b> {row.storedReviewerIdentity || "Reviewer pending identity"}</span>
                          </div>
                          <div className="image-provenance-compare" role="status" aria-live="polite">
                            <strong>Snapshot vs live compare</strong>
                            <div className="image-provenance-compare-grid">
                              {row.provenanceCompareRows.map(item => (
                                <article className={cx("image-provenance-row", item.match ? "match" : "drift")} key={`${row.draft.id}-${item.key}`}>
                                  <b>{item.label}</b>
                                  <span>Snapshot: {item.snapshot}</span>
                                  <span>Live: {item.live}</span>
                                </article>
                              ))}
                            </div>
                          </div>
                          <div className={cx("image-handoff-integrity", row.mismatchReasons.length ? "has-mismatch" : "healthy")} role="status" aria-live="polite">
                            <strong>Handoff integrity monitor</strong>
                            <p>
                              Published hash {row.storedReceiptHash || "Missing"} · Current hash {row.currentReceiptHash || "Missing"} ·
                              Thread {row.storedThreadId ? "linked" : "missing"}
                            </p>
                            {row.mismatchReasons.length ? (
                              <ul>
                                {row.mismatchReasons.map(reason => <li key={`${row.draft.id}-${reason}`}>{reason}</li>)}
                              </ul>
                            ) : <small>No drift detected between receipt evidence, published metadata, and notification thread.</small>}
                            <div className="image-skill-actions image-handoff-actions">
                              <button onClick={() => remediateHandoffIntegrity("link-receipt", row)} type="button">Link latest receipt</button>
                              <button onClick={() => remediateHandoffIntegrity("open-evidence", row)} type="button">Open receipt evidence</button>
                              <button onClick={() => remediateHandoffIntegrity("open-thread", row)} type="button">Open latest thread</button>
                              <button onClick={() => remediateHandoffIntegrity("refresh-metadata", row)} type="button">Refresh metadata</button>
                            </div>
                          </div>
                          <div className="image-skill-actions">
                            <button disabled={!row.linkedReceipt} onClick={() => openDraftEvidence(row.draft)} type="button">Open receipt evidence</button>
                            <button disabled={!row.outcomeEvent?.id} onClick={() => openOpsThread(row.outcomeEvent?.id)} type="button">Open notification thread</button>
                            <button onClick={() => setHandoffCheckpoint(row.draft.id, "syncConfirmedAt")} type="button">Mark web-control synced</button>
                            <button onClick={() => setHandoffCheckpoint(row.draft.id, "backendConfirmedAt")} type="button">Confirm backend live</button>
                          </div>
                          <em>Sync {row.syncConfirmedAt ? formatDateTime(row.syncConfirmedAt) : "Not confirmed"} · Backend {row.backendConfirmedAt ? formatDateTime(row.backendConfirmedAt) : "Not confirmed"}</em>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <div className="image-publish-ready">No published drafts yet. Publish a tested draft to generate handoff receipts.</div>
                  )}
                </div>
                <div className="image-skill-draft-list">
                  {skillDrafts.map(draft => {
                    const linkedReceipt = draft.linkedReceiptId ? queueById.get(draft.linkedReceiptId) : null;
                    const reviewGate = Boolean(linkedReceipt);
                    const testGate = linkedReceipt?.state === "done";
                    const publishGate = draft.state === "test" && testGate;
                    return (
                      <article className="image-skill-draft" key={draft.id}>
                        <div className="image-skill-draft-head">
                          <strong>{draft.title}</strong>
                          <span className={cx("image-skill-state", `state-${draft.state}`)}>{DRAFT_STATE_LABELS[draft.state] || draft.state}</span>
                        </div>
                        <p>{draft.summary}</p>
                        <div className="image-skill-evidence">
                          <span className={cx("evidence-chip", reviewGate ? "good" : "pending")}>
                            Receipt {reviewGate ? (linkedReceipt?.receipt?.promptHash || "Linked") : "Missing"}
                          </span>
                          <span className={cx("evidence-chip", testGate ? "good" : "pending")}>
                            Test gate {testGate ? "Verified" : "Pending"}
                          </span>
                          <span className={cx("evidence-chip", publishGate ? "good" : "pending")}>
                            Publish gate {publishGate ? "Ready" : "Blocked"}
                          </span>
                        </div>
                        {linkedReceipt ? (
                          <small className="image-skill-evidence-meta">
                            Evidence provider {linkedReceipt.receipt?.providerName || "unknown"} · layers {linkedReceipt.receipt?.layerCount ?? 0}
                          </small>
                        ) : (
                          <small className="image-skill-evidence-meta">Link a verification receipt before final review.</small>
                        )}
                        <em>Updated {formatTime(draft.updatedAt)}</em>
                        <div className="image-skill-actions">
                          <button disabled={!latestValidatedReceipt?.id} onClick={() => attachLatestReceiptToDraft(draft.id)} type="button">Link latest receipt</button>
                          <button disabled={!reviewGate} onClick={() => openDraftEvidence(draft)} type="button">Open evidence</button>
                          <button disabled={draft.state !== "draft" || !reviewGate} onClick={() => moveSkillDraftState(draft.id, "review")} type="button">Send to review</button>
                          <button disabled={draft.state !== "review" || !testGate} onClick={() => moveSkillDraftState(draft.id, "test")} type="button">Mark tested</button>
                          <button onClick={() => setReviewerSignOff(draft.id, !draft.reviewerSignedOff)} type="button">{draft.reviewerSignedOff ? "Remove sign-off" : "Reviewer sign-off"}</button>
                          <button disabled={draft.state !== "test" || !publishGate || !draft.reviewerSignedOff} onClick={() => moveSkillDraftState(draft.id, "published")} type="button">Publish skill</button>
                        </div>
                      </article>
                    );
                  })}
                </div>
                <div className="image-skill-recommendations">
                  <strong>Recommended next skills</strong>
                  {SKILL_RECOMMENDATIONS.map(item => (
                    <article className="image-skill-rec" key={item.id}>
                      <div>
                        <span>{item.track}</span>
                        <b>{item.title}</b>
                        <p>{item.reason}</p>
                      </div>
                      <button onClick={() => createDraftFromRecommendation(item)} type="button">Create draft</button>
                    </article>
                  ))}
                </div>
              </section>

              <section className="image-glass-panel image-ops-feed" aria-live="polite">
                <div className="image-panel-head">
                  <strong>Chat & progress notifications</strong>
                  <span>{operationEvents.length}</span>
                </div>
                <p className="image-status-line">Every key state change is timestamped for operator review.</p>
                <button className="image-glass-button image-slice-notify-btn" onClick={() => postSliceOutcomeSummary()} type="button">
                  Post slice outcome summary
                </button>
                <div className="image-ops-feed-list">
                  {operationEvents.map(item => {
                    const isOutcome = Boolean(item.outcome);
                    const collapsed = isOutcome && collapsedOutcomeIds.has(item.id);
                    return (
                      <article className={cx("image-ops-item", `tone-${item.tone}`, isOutcome && "slice-outcome", activeOpsThreadId === item.id && "evidence-focus")} key={item.id}>
                        <div>
                          <strong>{item.title}</strong>
                          <p>{item.detail}</p>
                          {isOutcome ? (
                            <>
                              <div className="image-slice-badges" role="status" aria-label="Slice verification badges">
                                <span className="slice-badge">Build {item.outcome.buildStatus}</span>
                                <span className="slice-badge">Test {item.outcome.testStatus}</span>
                                <span className="slice-badge">Sync {item.outcome.syncStatus}</span>
                                <span className="slice-badge">Backend {item.outcome.backendStatus}</span>
                              </div>
                              <button className="image-slice-toggle" onClick={() => toggleOutcomeDetails(item.id)} type="button">
                                {collapsed ? "Show details" : "Hide details"}
                              </button>
                              {!collapsed ? (
                                <dl className="image-slice-details">
                                  <div><dt>Changed scope</dt><dd>{item.outcome.changedScope}</dd></div>
                                  <div><dt>Build</dt><dd>{item.outcome.buildStatus}</dd></div>
                                  <div><dt>Tests</dt><dd>{item.outcome.testStatus}</dd></div>
                                  <div><dt>Sync</dt><dd>{item.outcome.syncStatus}</dd></div>
                                  <div><dt>Backend restart</dt><dd>{item.outcome.backendStatus}</dd></div>
                                </dl>
                              ) : null}
                            </>
                          ) : null}
                        </div>
                        <em>{formatTime(item.createdAt)}</em>
                      </article>
                    );
                  })}
                </div>
              </section>
            </div>
          </details>
        </div>
      </section>
    </section>
  );
}
