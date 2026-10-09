// Manual claims are enforced at the model boundary on every UI action.
// Contract failures identify the claim, never image prompts or provider secrets.
export class ImageContractError extends Error {
  constructor(id) { super(`Image contract ${id} failed`); this.name = "ImageContractError"; this.contract = id; }
}
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const list = value => Array.isArray(value) ? value : [];
const coords = ["x", "y", "width", "height"];
const annotationFields = ["pins", "rectangles", "layers", "comments"];
const realSession = item => {
  const provider = String(item?.provider || item?.providerId || "").toLowerCase();
  if (!item || provider.includes("local composition") || provider === "local project") return false;
  const request = String(item.requestId || "").trim();
  if (String(item.status || "").includes("provider_blocked") || item.providerStatus === "blocked") return Boolean(request) && (provider.includes("codex") || provider.includes("openai"));
  const artifact = [item.outputArtifactPath, item.manifestPath, item.manifestUrl, item.artifactPath, item.previewSrc].some(path => String(path || "").trim() && !String(path).startsWith("data:"));
  return Boolean(request && String(item.receipt?.promptHash || "").trim()) || Boolean(request && artifact && (/generated|edited/.test(item.status || "") || item.providerStatus === "available"));
};

export const IMAGE_CONTRACTS = Object.freeze({
  projectToProviderPayload: { id: "image.payload.geometry", claim: "Provider payload preserves canvas, selection, prompt intent, layer roles and rounded geometry; only visible layers are counted", check: ([project, operation = "edit", options = {}], out) =>
    out.operation === operation && same(out.canvas, project.canvas) && same(out.selection, project.selection) && same(out.prompt, project.prompt) && out.layers.length === project.layers.length && out.layers.every((layer, index) => coords.every(key => layer[key] === Math.round(project.layers[index][key])) && layer.rotation === Number(project.layers[index].rotation || 0) && layer.id === project.layers[index].id && layer.promptRole === (project.layers[index].promptRole || "") && layer.visible === project.layers[index].visible) && out.inputs.visibleLayerCount === out.layers.filter(row => row.visible !== false).length && out.inputs.snapshotDataUrl === (options.snapshotDataUrl || "") && out.compositionIntent.startsWith(project.prompt.preserveComposition ? "Preserve the manual layer positions" : "Use the canvas as loose visual context") && coords.every(key => out.inputs.editRegion[key] === Math.round(project.selection[key] || 0)) && out.inputs.editRegion.feather === Math.round(project.selection.feather || 0) },
  createLayerFromSelection: { id: "image.layers.selection", claim: "Selection becomes one editable selected shape with rounded geometry, positive extent and nonnegative feather", check: ([project, options = {}], out) => {
    const layer = out.layers.at(-1);
    return out.layers.length === project.layers.length + 1 && same(out.layers.slice(0, -1), project.layers) && out.selectedLayerId === layer.id && layer.type === "shape" && layer.name === (options.name || "Selected region") && layer.promptRole === (options.promptRole || "selected region") && layer.x === Math.round(project.selection.x || 0) && layer.y === Math.round(project.selection.y || 0) && layer.width === Math.max(1, Math.round(project.selection.width || 1)) && layer.height === Math.max(1, Math.round(project.selection.height || 1)) && layer.mask.feather === Math.max(0, Math.round(project.selection.feather || 0));
  } },
  updateLayerInProject: { id: "image.layers.update", claim: "A patch affects only its addressed layer and preserves the other layers", check: ([project, id, patch = {}], out) => out.layers.length === project.layers.length && out.layers.every((row, index) => same(row, project.layers[index].id === id ? { ...project.layers[index], ...patch } : project.layers[index])) },
  removeLayerFromProject: { id: "image.layers.delete", claim: "Deletion preserves at least one layer and selects the last survivor when removing the selected layer", check: ([project, id], out) => {
    const survivors = project.layers.filter(row => row.id !== id);
    const keep = project.layers.length <= 1 || !survivors.length;
    return same(out.layers, keep ? project.layers : survivors) && out.layers.length > 0 && out.selectedLayerId === (keep || project.selectedLayerId !== id ? project.selectedLayerId : survivors.at(-1).id);
  } },
  setFocusedHistoryItem: { id: "image.history.focus", claim: "Only an existing retained session can become focused; its annotations replace the overlay", check: ([project, id], out) => {
    const row = out.history.find(item => item.id === String(id || ""));
    return out.focusedHistoryId === (row?.id || "") && annotationFields.every(key => same(out.annotationReadiness[key], list(row?.annotationSnapshot?.[key])));
  } },
  updateFocusedHistoryAnnotations: { id: "image.history.annotations", claim: "Overlay changes persist on the focused history session and preserve other sessions", check: ([project, patch = {}], out) => {
    const id = project.focusedHistoryId || out.history[0]?.id || "";
    return out.focusedHistoryId === id && Object.entries(patch).every(([key, value]) => same(out.annotationReadiness[key], value)) && out.history.every(row => row.id !== id || annotationFields.every(key => same(row.annotationSnapshot[key], list(out.annotationReadiness[key])))) && project.history.filter(row => row.id !== id && realSession(row)).every(row => same(out.history.find(item => item.id === row.id), row));
  } },
  createOpsThreadForFocusedHistory: { id: "image.history.thread", claim: "History, overlay and one idempotent issue thread share the receipt/request proof handle", check: ([project, options = {}], out) => {
    const focused = out.history.find(row => row.id === out.focusedHistoryId);
    if (!out.focusedHistoryId) return same(out.opsThreads, project.opsThreads);
    const handle = focused?.issueThread?.id;
    const thread = out.opsThreads.find(row => row.id === handle);
    return Boolean(thread) && out.opsThreads.filter(row => row.id === handle).length === 1 && out.annotationReadiness.activeThreadRef === handle && thread.requestId === focused.issueThread.requestId && thread.receiptHash === focused.issueThread.receiptHash && focused.issueThread.href === `#issue-thread-${encodeURIComponent(handle)}` && (project.opsThreads.some(row => row.id === handle) || thread.title === (options.title || `Image Playground issue ${handle}`));
  } },
  buildKeyboardTraversalAnnouncement: { id: "image.keyboard.announcement", claim: "Scope/edge jumps announce both scoped positions; focus announces the destination", check: ([change = {}], out) => {
    const position = (scope, index, count) => `${scope === "queue" ? "Queue" : "History"} ${Math.max(0, Number(index) || 0)}/${Math.max(0, Number(count) || 0)}`;
    const to = position(change.toScope || "history", change.toIndex, change.toCount);
    return out === (["group-jump", "edge-jump"].includes(change.reason) ? `${position(change.fromScope || "history", change.fromIndex, change.fromCount)} -> ${to}` : `${to} focused`);
  } },
  appendKeyboardJumpTrail: { id: "image.keyboard.trail", claim: "Recent traversal trail is bounded, retains newest records, and carries scope/reason/time", check: ([trail = [], change = {}, options = {}], out) => {
    const max = Math.max(1, Number(options.maxEntries) || 3), latest = out.at(-1);
    return out.length === Math.min(list(trail).length + 1, Math.floor(max)) && same(out.slice(0, -1), list(trail).slice(Math.max(0, list(trail).length - out.length + 1))) && IMAGE_CONTRACTS.buildKeyboardTraversalAnnouncement.check([change], latest.announcement) && latest.reason === String(change.reason || "focus") && latest.fromScope === (change.fromScope || "history") && latest.toScope === (change.toScope || "history") && typeof latest.at === "string" && (!options.at || latest.at === String(options.at));
  } },
  formatKeyboardJumpTrailEntry: { id: "image.keyboard.entry", claim: "Trail entry shows its traversal text with a local clock, or an explicit recent fallback for invalid time", check: ([entry = {}], out) => {
    const label = String(entry.announcement || "").trim() || "Traversal";
    if (!entry.at) return out === label;
    return Number.isFinite(Date.parse(entry.at)) ? out.endsWith(` ${label}`) && /\d{2}:\d{2}:\d{2}/.test(out) : out === `Recently ${label}`;
  } },
  formatKeyboardJumpTrailTooltip: { id: "image.keyboard.tooltip", claim: "Traversal tooltip preserves scope/reason, full local time when valid, and announcement", check: ([entry = {}], out) => {
    const label = String(entry.announcement || "").trim() || "Traversal";
    const reason = ({ "group-jump": "Scope jump", "edge-jump": "Edge jump", arrow: "Arrow move" })[String(entry.reason || "focus").toLowerCase()] || "Focus";
    const suffix = `${reason} • ${label}`;
    return !entry.at || !Number.isFinite(Date.parse(entry.at)) ? out === suffix : out.endsWith(` • ${suffix}`) && /\d{2}:\d{2}:\d{2}/.test(out);
  } },
  registerImageProviderAdapter: { id: "image.provider.adapter", claim: "Registered adapter has its trimmed unique identity and callable transport", check: ([adapter, before], out) => out.id === String(adapter.id).trim() && !before.includes(out.id) && typeof out.request === "function" && out.name === adapter.name },
  requestProviderOperation: { id: "image.provider.receipt", claim: "Every available, blocked or draft operation has a traceable request, timing, handoff and prompt receipt; nonavailable operations preserve failure evidence", check: ([project, _operation, options = {}], out) => {
    const meta = out.meta;
    return Boolean(meta?.requestId) && Number.isFinite(meta.requestTimeline?.durationMs) && meta.requestTimeline.durationMs >= 0 && ["queuedAt", "startedAt", "completedAt"].every(key => Number.isFinite(Date.parse(meta.requestTimeline[key]))) && list(meta.queueTimeline).length > 0 && meta.queueTimeline.every((row, index, rows) => typeof row.stage === "string" && (Number.isFinite(Date.parse(row.at)) || (meta.providerStatus === "blocked" && row.at === "" && index > 0 && index < rows.length - 1))) && Boolean(meta.receipt?.promptHash) && meta.layerHandoff?.stage === (out.layer ? "layer_ready" : "no_layer") && meta.layerHandoff.layerId === (out.layer?.id || "") && (meta.providerStatus === "available" || (Boolean(meta.receipt.failureReason) && meta.receipt.promptEvidence === project.prompt.text && typeof meta.receipt.specEvidence === "string")) && (out.kind !== "local-draft" || (meta.providerStatus === "fallback" && /^imgreq-/.test(meta.requestId) && same(meta.queueTimeline.map(row => row.stage), ["queued", "provider accepted", "generating", "artifact written", "layer handoff", "verified"]))) && (!options.imagePluginMode || meta.requestId);
  } },
  applyProviderResult: { id: "image.provider.history", claim: "Provider application preserves receipt/artifact/timing/handoff and annotation proof links, while draft results never masquerade as persisted sessions", check: ([project, result], out) => {
    if (out.layers.length !== project.layers.length + Number(Boolean(result.layer)) || (result.layer && out.selectedLayerId !== result.layer.id)) return false;
    const row = out.history.find(item => item.requestId === result.meta?.requestId);
    if (result.kind === "local-draft") return !row;
    if (!row) return !realSession({ ...result.meta, provider: result.provider, status: result.kind === "provider" ? "generated" : "provider_blocked" });
    const handle = `${result.meta?.receipt?.promptHash || row.receipt.promptHash}:${result.meta?.requestId || "pending-request-id"}`;
    const pins = list(project.annotationReadiness?.pins).slice(0, 24), rectangles = list(project.annotationReadiness?.rectangles).slice(0, 24);
    return row.status === (result.kind === "provider" ? "generated" : "provider_blocked") && row.providerStatus === (result.meta?.providerStatus || (result.kind === "provider" ? "available" : "blocked")) && row.outputArtifactPath === (result.meta?.outputArtifactPath || "") && same(row.receipt, result.meta?.receipt || {}) && same(row.requestTimeline, result.meta?.requestTimeline || {}) && same(row.layerHandoff, result.meta?.layerHandoff || {}) && row.issueThread.id === handle && row.issueThread.requestId === (result.meta?.requestId || "pending-request-id") && row.issueThread.receiptHash === row.receipt.promptHash && row.issueThread.href === `#issue-thread-${encodeURIComponent(handle)}` && row.annotationSnapshot.pins.length === pins.length && row.annotationSnapshot.rectangles.length === rectangles.length && row.annotationSnapshot.pins.every((pin, index) => pin.threadRef === (pins[index].threadRef || handle) && pin.id === pins[index].id && pin.x === Number(pins[index].x || 0) && pin.y === Number(pins[index].y || 0) && pin.comment === String(pins[index].comment || "")) && row.annotationSnapshot.rectangles.every((rect, index) => rect.threadRef === (rectangles[index].threadRef || handle) && rect.id === rectangles[index].id && rect.x === Number(rectangles[index].x || 0) && rect.y === Number(rectangles[index].y || 0) && rect.width === Number(rectangles[index].width || rectangles[index].w || 0) && rect.height === Number(rectangles[index].height || rectangles[index].h || 0) && rect.comment === String(rectangles[index].comment || ""));
  } },
});

export function checkedImageAction(name, args, result) {
  const contract = IMAGE_CONTRACTS[name];
  let valid = false;
  try { valid = Boolean(contract?.check(args, result)); } catch { /* malformed output fails closed */ }
  if (!valid) throw new ImageContractError(contract?.id || name);
  return result;
}

export function checkImagePromptPresets(presets) {
  const ids = ["saas-workbench", "artifact-review", "mobile-safe-controls"];
  if (!same(presets.map(row => row.id), ids) || !presets.every(row => row.strength > 0 && row.strength < 1) || !presets[0].intent.includes("Linear") || !presets[0].style.includes("monochrome") || !presets[1].negative.includes("fake charts") || !presets[2].style.includes("responsive")) throw new ImageContractError("image.prompt.presets");
  return presets;
}
