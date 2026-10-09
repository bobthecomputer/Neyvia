import { checkPresentationAction } from "../neyviaPresentationContracts.js";
// Provider-independent presentation of the canonical connected-session items.
export const TRANSPARENCY_LEVELS = ["everything", "summaries", "minimal"];
export const TRANSPARENCY_LABELS = { everything: "Show everything", summaries: "Summaries", minimal: "Minimal" };
// Keep recorded output intact; terminal escapes have no meaning in a <pre>.
export function stripAnsi(value) {
  return String(value ?? "")
    .replace(/(?:\x1b\]|\x9d)[\s\S]*?(?:\x07|\x1b\\|\x9c)/g, "")
    .replace(/(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]/g, "")
    .replace(/\x1b[ -/]*[@-Z\\-_]/g, "");
}
function normalizeTransparencyUnchecked(value) { return TRANSPARENCY_LEVELS.includes(value) ? value : "everything"; }

function detailTextUnchecked(value) {
  if (value == null) return "";
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

export function toolFailed(data = {}) {
  return data.status === "error" || (data.exitCode != null && Number(data.exitCode) !== 0);
}

/** Provider availability belongs to a turn, not to every streamed message fragment. */
export function visibleTranscriptItems(items, level) {
  const turns = [[]];
  for (const item of items) {
    if (item.kind === "user") turns.push([]);
    turns.at(-1).push(item);
  }
  return turns.flatMap(turn => {
    const visible = turn.filter(item => itemVisible(item, level));
    const hasTools = visible.some(item => item.kind === "tool");
    // Minimal may hide summaries, but available reasoning is still available.
    const hasReasoning = turn.some(item => item.kind === "reasoning" && String(item.data?.summary || "").trim());
    let shown = false;
    return visible.filter(item => {
      if (hasReasoning && item.kind === "reasoning" && !item.data?.summary && item.data?.hidden) return false;
      if (item.kind !== "reasoning" || item.data?.exposure !== "not_reported" || item.data?.summary) return true;
      if (hasTools || hasReasoning || shown) return false;
      shown = true;
      return true;
    });
  });
}

function itemVisibleUnchecked(item, level) {
  if (normalizeTransparency(level) !== "minimal") return true;
  if (item.kind === "tool") return toolFailed(item.data);
  if (item.kind === "diff") return false;
  if (item.kind === "reasoning") return Boolean(item.data?.hidden || item.data?.notice);
  return true;
}

// In Show everything the saved set records collapsed items; in Summaries it
// records expanded items. Preferences use separate sets for each level.
function detailExpandedUnchecked(id, level, toggled, failed = false) {
  return normalizeTransparency(level) === "everything" || failed ? !toggled.has(id) : toggled.has(id);
}

function reasoningNoticeUnchecked(data = {}, provider = "The provider") {
  return data.notice || `${data.provider || provider} didn’t share its reasoning for this step`;
}

function toolDetailsUnchecked(data = {}) {
  const input = detailText(data.input);
  const command = detailText(data.command || (data.category === "command" ? input : ""));
  const args = detailText(data.args);
  const fields = [];
  if (command) fields.push({ label: "Command", text: command });
  if (args && args !== command) fields.push({ label: "Arguments", text: args });
  if (input && input !== command && input !== args) fields.push({ label: "Input", text: input });
  const output = detailText(data.output);
  if (output || data.output === "") fields.push({ label: "Output", text: output || "(empty output)" });
  const result = detailText(data.result);
  if (result && result !== output) fields.push({ label: "Result", text: result });
  return fields;
}

function toolMetadataUnchecked(data = {}) {
  const parts = [];
  if (data.exitCode != null) parts.push(`Exit ${data.exitCode}`);
  else if (data.category === "command" && data.status !== "running") parts.push("Exit not reported");
  if (Number.isFinite(data.durationMs)) parts.push(`${["transcript-timestamps", "transport-observed"].includes(data.durationSource) ? "Observed " : ""}${(data.durationMs / 1000).toFixed(data.durationMs < 1000 ? 3 : 2)} s`);
  else if (data.category === "command" && data.status !== "running") parts.push("Duration not reported");
  if (data.status === "running") parts.push("Running");
  return parts.join(" · ");
}

function diffTextUnchecked(data = {}) {
  if (data.patch != null) return detailText(data.patch);
  return (data.files || []).map(file => detailText(file.patch ?? file.diff ?? "")).filter(Boolean).join("\n\n");
}

export function normalizeTransparency(...args) { return checkPresentationAction("transparency.normalize", args, normalizeTransparencyUnchecked(...args)); }

export function detailText(...args) { return checkPresentationAction("transparency.text", args, detailTextUnchecked(...args)); }

export function itemVisible(...args) { return checkPresentationAction("transparency.visible", args, itemVisibleUnchecked(...args)); }

export function detailExpanded(...args) { return checkPresentationAction("transparency.expanded", args, detailExpandedUnchecked(...args)); }

export function reasoningNotice(...args) { return checkPresentationAction("transparency.notice", args, reasoningNoticeUnchecked(...args)); }

export function toolDetails(...args) { return checkPresentationAction("transparency.details", args, toolDetailsUnchecked(...args)); }

export function toolMetadata(...args) { return checkPresentationAction("transparency.metadata", args, toolMetadataUnchecked(...args)); }

export function diffText(...args) { return checkPresentationAction("transparency.patch", args, diffTextUnchecked(...args)); }
