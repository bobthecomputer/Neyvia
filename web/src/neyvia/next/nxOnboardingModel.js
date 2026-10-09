import { checkedProofsEModel } from "./nxProofsEContracts.js";
// First-run setup, pure parts: what interests recommend, how long the tour
// lasts, and what the download and runtime cards say. The catalog comes from
// the backend (config/neyvia_onboarding.json) so the bot side reads the same.

export const STEPS = ["welcome", "unique", "downloads", "connections", "done"];
export const STEP_LABELS = { welcome: "Welcome", unique: "What's different", downloads: "Downloads", connections: "Connect", done: "Done" };
// Older callers (the model's neyvia.onboarding.open, saved links) still say runtimes, interests or tour.
const LEGACY_STEPS = { runtimes: "connections", interests: "downloads", tour: "unique" };
export const stepFor = id => (STEPS.includes(id) ? id : LEGACY_STEPS[id] || "welcome");

/** What unlocks a feature: the download group it belongs to (config/neyvia_onboarding.json, chapter.unlockedBy). */
export const UNLOCKS = {
  core: { label: "Included in Core", step: "" },
  connections: { label: "Needs a connection", step: "connections" },
  "claude-mod": { label: "Claude Code mod", step: "downloads" },
  "codex-skills": { label: "Codex skills", step: "downloads" },
};
export const uniqueChapters = chapters => (chapters || []).filter(row => row.unique);
export const TOUR_MIN_MS = 60000;
export const TOUR_MAX_MS = 90000;

/** Interests chosen directly win; a tier only fills in when none are picked. */
function raw_interestsFor(catalog, { interests = [], tier = "" } = {}) {
  if (interests.length) return interests;
  return catalog?.tiers?.find(row => row.id === tier)?.interests || [];
}

/** Union of what the chosen interests recommend, in catalog order (same rule as the backend). */
function raw_recommend(catalog, chosen) {
  const set = new Set(chosen);
  const union = key => {
    const out = [];
    for (const row of catalog?.interests || []) {
      if (!set.has(row.id)) continue;
      for (const value of row[key] || []) if (!out.includes(value)) out.push(value);
    }
    return out;
  };
  const wanted = new Set(union("chapters"));
  const chapters = (catalog?.tutorial?.chapters || []).filter(row => !row.interests.length || wanted.has(row.id));
  return { apps: union("apps"), packs: union("packs"), runtimes: union("runtimes"), chapters };
}

/** Stretch or speed every chapter evenly so the whole tour lasts 60–90 s. */
function raw_timeline(chapters) {
  const total = chapters.reduce((sum, row) => sum + row.durationMs, 0);
  if (!total) return { chapters: [], totalMs: 0 };
  const target = Math.min(TOUR_MAX_MS, Math.max(TOUR_MIN_MS, total));
  const scale = target / total;
  let start = 0;
  let elapsed = 0;
  const rows = chapters.map((row, index) => {
    // Round cumulative boundaries so thousands of chapters cannot accumulate
    // rounding error and leave a negative final duration.
    elapsed += row.durationMs;
    const end = index === chapters.length - 1 ? Math.round(target) : Math.round(elapsed * scale);
    const durationMs = end - start;
    const placed = { ...row, start, durationMs };
    start += durationMs;
    return placed;
  });
  return { chapters: rows, totalMs: start };
}

/** Which chapter is playing at `ms`, and how far into it (0–1). */
function raw_locate(plan, ms) {
  const clamped = Math.max(0, Math.min(ms, plan.totalMs));
  if (!plan.chapters.length) return { index: 0, chapter: null, progress: 0 };
  const found = plan.chapters.findIndex(row => clamped < row.start + row.durationMs);
  const index = found === -1 ? plan.chapters.length - 1 : found;
  const chapter = plan.chapters[index];
  return { index, chapter, progress: chapter.durationMs > 0 ? Math.max(0, Math.min(1, (clamped - chapter.start) / chapter.durationMs)) : 1 };
}

/** Toggle an id in a list, keeping order. */
export function toggle(list, id) {
  return list.includes(id) ? list.filter(value => value !== id) : [...list, id];
}

export function formatBytes(bytes) {
  const value = Number(bytes) || 0;
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(0)} KB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${(value / 1024 ** 3).toFixed(2)} GB`;
}

/** The download card's words and numbers. */
function raw_downloadView(status) {
  const state = status?.state || "idle";
  const total = Number(status?.totalBytes) || 0;
  const done = Math.min(total || Infinity, Number(status?.doneBytes) || 0);
  const percent = total ? Math.floor((done / total) * 100) : state === "done" ? 100 : 0;
  const speed = Number(status?.bytesPerSecond) || 0;
  const left = speed && total ? Math.ceil((total - done) / speed) : null;
  const headline = {
    idle: "Getting the essentials",
    starting: "Getting the essentials",
    running: "Getting the essentials",
    verifying: "Getting the essentials",
    paused: "Paused",
    done: "Essentials ready",
    failed: "The download stopped",
  }[state] || "Getting the essentials";
  const detail = state === "done" ? `${formatBytes(total)} · every file checked`
    : state === "failed" ? (status?.error || "Something went wrong.")
      : state === "paused" ? `${formatBytes(done)} of ${formatBytes(total)} · resumes where it left off`
        : total ? `${formatBytes(done)} of ${formatBytes(total)}${left != null && left > 0 ? ` · about ${left < 60 ? `${left} s` : `${Math.ceil(left / 60)} min`} left` : ""}`
          : "Starting…";
  return { state, percent, headline, detail, busy: ["starting", "running", "verifying"].includes(state) };
}

/**
 * The Core download as one truthful line (UI words over downloadView's measured numbers):
 * idle = ready, running = progress with no Start, done = installed.
 */
export function essentialsView(status) {
  const view = downloadView(status);
  const failed = view.state === "failed";
  const headline = view.state === "idle" ? "Ready to download"
    : view.busy ? `Downloading… ${view.percent} %`
      : view.state === "done" ? "Installed" : failed ? "The download stopped" : "Paused";
  const detail = view.state === "idle" ? "Press Start when you are ready." : view.busy ? view.detail.replace(/^Starting…$/, "Starting the download") : view.detail;
  return { ...view, headline, detail };
}

/**
 * One add-on pack row: what it says and which button it offers. `row` is the
 * catalog entry from onboarding_state_command; `status` the matching entry of
 * onboarding_pack_status_command (state unavailable | not-installed | queued |
 * installing | installed | failed).
 */
function raw_packView(row, status) {
  const state = status?.state || (row?.ready === false ? "unavailable" : "not-installed");
  const total = Number(status?.totalBytes) || 0;
  const done = Math.min(total || Infinity, Number(status?.doneBytes) || 0);
  const percent = total ? Math.floor((done / total) * 100) : state === "installed" ? 100 : 0;
  const files = status?.files?.total || 0;
  const missing = status?.missing?.length ? status.missing : row?.missing || [];
  const size = row?.resourceClass === "heavy" ? "Large" : row?.resourceClass === "light" ? "Tiny" : "Small";
  const detail = {
    unavailable: `Not ready yet · ${missing.length || "some"} thing${missing.length === 1 ? "" : "s"} missing`,
    "not-installed": `${size} pack · ${missing.length ? "some parts still to come" : "installs on its own"}`,
    queued: "Starting…",
    installing: total ? `${formatBytes(done)} of ${formatBytes(total)}` : "Installing…",
    installed: `Installed · ${files ? `${files} file${files === 1 ? "" : "s"} checked` : "checked"}${total ? ` · ${formatBytes(total)}` : ""}`,
    failed: status?.error || "The install stopped.",
  }[state] || "";
  return {
    state, percent, detail, missing,
    busy: state === "queued" || state === "installing",
    canInstall: state === "not-installed" || state === "failed",
  };
}

const TOOL_NAMES = { "latex-suite": "LaTeX", "pytorch-huggingface": "PyTorch and Hugging Face", "scientific-python": "Scientific Python", "docker-engine": "Docker", "android-sdk": "Android SDK", glmocr: "GLM-OCR", paddleocr: "PaddleOCR", ocrmypdf: "OCRmyPDF", libreoffice: "LibreOffice", languagetool: "LanguageTool", "argos-translate": "Argos Translate", libretranslate: "LibreTranslate", ffmpeg: "FFmpeg", imagemagick: "ImageMagick", kicad: "KiCad", freecad: "FreeCAD", openscad: "OpenSCAD", postgresql: "PostgreSQL", duckdb: "DuckDB", gimp: "GIMP" };
const toolName = id => TOOL_NAMES[id] || id.charAt(0).toUpperCase() + id.slice(1);

/** The catalog's gap notes in plain words: "tool.pandoc … bundle absent" → "Pandoc isn't packaged yet". */
function raw_plainMissing(text) {
  const tool = /No scoped redistributable runtime payload for tool\.([\w.-]+)/.exec(String(text || ""));
  if (tool) return `${toolName(tool[1])} isn't packaged yet`;
  return String(text || "").replace(/\btool\.([\w-]+)/g, (_, id) => toolName(id));
}

/**
 * One download row (a component from components_status_command, config/components.json): the words under
 * its title and what the switch does. State: not-installed | current | update-available | broken |
 * unavailable | check-only | unknown.
 */
export function componentView(row, busy = "") {
  const state = row?.state || "unknown";
  const installed = state === "current" || state === "update-available" || state === "broken";
  const version = row?.installedVersion ? `v${String(row.installedVersion).replace(/^v/, "")}` : "";
  const latest = row?.bundledVersion ? `v${String(row.bundledVersion).replace(/^v/, "")}` : "";
  const detail = busy ? (busy === "remove" ? "Removing…" : busy === "update" ? "Updating…" : "Installing…")
    : state === "current" ? `Installed${version ? ` · ${version}` : ""} · stays current on its own`
      : state === "update-available" ? `Update ready${version && latest ? ` · ${version} to ${latest}` : ""}`
        : state === "broken" ? (row?.detail || "Something is missing. Repair puts it back.")
          : state === "unavailable" ? (row?.detail || "Not available on this PC.")
            : state === "check-only" ? `${version || latest || "Present"} · updated with Neyvia`
              : state === "not-installed" ? "Off. Nothing has been changed on this PC."
                : "Checking this PC…";
  return {
    state, installed, detail, busy: Boolean(busy),
    on: installed || busy === "install", // the switch shows the wish while an install runs
    canToggle: !busy && state !== "unavailable" && state !== "unknown" && (row?.actions || []).some(name => name === "install" || name === "remove"),
    canUpdate: !busy && state === "update-available" && (row?.actions || []).includes("update"),
    canRepair: !busy && state === "broken" && (row?.actions || []).includes("install"),
    tone: state === "broken" ? "bad" : state === "update-available" ? "warn" : state === "current" ? "good" : "idle",
  };
}

/** Components by group, in the order the downloads step shows them. */
export function componentGroups(rows) {
  const list = rows || [];
  return {
    core: list.filter(row => row.group === "core"),
    claudeMod: list.find(row => row.group === "claude-mod" || row.id === "claude-mod") || null,
    codexSkills: list.find(row => row.group === "codex-skills" || row.id === "codex-skills") || null,
    optional: list.filter(row => row.group === "optional"),
  };
}

/** True while any pack is still copying, so the screen keeps asking. */
export function packsBusy(statuses) {
  return Object.values(statuses || {}).some(row => row?.state === "queued" || row?.state === "installing");
}

/** "You're set to start" when something was found, "Begin with…" when not. */
function raw_runtimeHeadline(result) {
  const found = (result?.runtimes || []).filter(row => row.found);
  if (!result) return { title: "Looking at this PC…", sub: "" };
  if (found.length) {
    const names = found.map(row => row.label);
    return { title: "You're set to start", sub: `Found ${names.length === 1 ? names[0] : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`} on this PC.` };
  }
  return { title: "Begin with…", sub: "No agent app was found on this PC yet. Pick one to set up, or start with Neyvia Native." };
}

// Public observers check the executable manual claims on every invocation.
export function interestsFor(...args) { return checkedProofsEModel("onboarding.interestsFor", args, raw_interestsFor(...args)); }
export function recommend(...args) { return checkedProofsEModel("onboarding.recommend", args, raw_recommend(...args)); }
export function timeline(...args) { return checkedProofsEModel("onboarding.timeline", args, raw_timeline(...args)); }
export function locate(...args) { return checkedProofsEModel("onboarding.locate", args, raw_locate(...args)); }
export function downloadView(...args) { return checkedProofsEModel("onboarding.downloadView", args, raw_downloadView(...args)); }
export function packView(...args) { return checkedProofsEModel("onboarding.packView", args, raw_packView(...args)); }
export function plainMissing(...args) { return checkedProofsEModel("onboarding.plainMissing", args, raw_plainMissing(...args)); }
export function runtimeHeadline(...args) { return checkedProofsEModel("onboarding.runtimeHeadline", args, raw_runtimeHeadline(...args)); }
