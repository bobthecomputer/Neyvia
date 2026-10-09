import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
/**
 * Neyvia shell preferences — durable local UI state.
 * Backend owns capability truth; this store only owns visual/a11y preferences.
 * Visual language inspired by capability-OS mockups; product name is always Neyvia.
 */

export const NEYVIA_SHELL_PREFERENCES_KEY = "neyvia.shell.preferences.v1";

export const NEYVIA_SHELL_SURFACES = Object.freeze([
  Object.freeze({ id: "chat", surface: "agent", label: "Chat" }),
  Object.freeze({ id: "notebook", surface: "notebook", label: "Notebook" }),
  Object.freeze({ id: "lab", surface: "lab", label: "Lab" }),
  Object.freeze({ id: "orchestration", surface: "builder", label: "Orchestration" }),
  Object.freeze({ id: "library", surface: "library", label: "Library" }),
]);

export const NEYVIA_UI_PRESETS = Object.freeze([
  Object.freeze({
    id: "minimal",
    label: "Minimal",
    description: "Clean and focused — fewer chrome labels, calm density.",
    toolbar: ["attach", "search"],
    showLabels: false,
    showToolNames: false,
    compactMode: true,
    detailLevel: "minimal",
  }),
  Object.freeze({
    id: "creator",
    label: "Creator",
    description: "Images, 3D, and media tools near the canvas.",
    toolbar: ["attach", "images", "canvas", "search"],
    showLabels: true,
    showToolNames: true,
    compactMode: false,
    detailLevel: "balanced",
  }),
  Object.freeze({
    id: "researcher",
    label: "Researcher",
    description: "Docs, citations, data, and proof-forward layout.",
    toolbar: ["attach", "pdf", "search", "data", "citations"],
    showLabels: true,
    showToolNames: true,
    compactMode: false,
    detailLevel: "expanded",
  }),
  Object.freeze({
    id: "engineer",
    label: "Engineer",
    description: "Code, infra, and DevOps tools on the bar.",
    toolbar: ["attach", "terminal", "search", "diff", "canvas"],
    showLabels: true,
    showToolNames: false,
    compactMode: true,
    detailLevel: "balanced",
  }),
]);

export const NEYVIA_APPEARANCE_THEMES = Object.freeze([
  Object.freeze({
    id: "light",
    label: "Light",
    bestFor: "Daytime reading",
    tokens: {
      bg: "#f6f7f9",
      panel: "#ffffff",
      panelSoft: "#eef0f4",
      sidebar: "#eff1f5",
      raised: "#ffffff",
      hover: "rgba(18, 28, 52, 0.05)",
      selected: "rgba(31, 95, 224, 0.1)",
      line: "rgba(18, 28, 52, 0.11)",
      lineStrong: "rgba(18, 28, 52, 0.2)",
      text: "#11151f",
      textSoft: "#374052",
      muted: "#515b6d",
      faint: "#606a7a",
      accent: "#1f5fe0",
      accentText: "#1f5fe0",
      accentInk: "#ffffff",
      accentSoft: "rgba(31, 95, 224, 0.12)",
      glow: "rgba(31, 95, 224, 0.28)",
      star: "#b7791f",
      starSoft: "rgba(183, 121, 31, 0.14)",
      good: "#178a47",
      warn: "#b36b00",
      bad: "#c42f3f",
    },
  }),
  Object.freeze({
    id: "warm",
    label: "Warm",
    bestFor: "Long sessions",
    tokens: {
      bg: "#f3ebe1",
      panel: "#faf6f0",
      panelSoft: "#ebe1d4",
      sidebar: "#eee4d7",
      raised: "#fbf8f3",
      hover: "rgba(60, 42, 24, 0.06)",
      selected: "rgba(138, 90, 43, 0.12)",
      line: "rgba(60, 42, 24, 0.14)",
      lineStrong: "rgba(60, 42, 24, 0.24)",
      text: "#2a2118",
      textSoft: "#4a3d30",
      muted: "#665443",
      faint: "#715f4d",
      accent: "#8a5a2b",
      accentText: "#8a5a2b",
      accentInk: "#fffaf3",
      accentSoft: "rgba(138, 90, 43, 0.14)",
      glow: "rgba(138, 90, 43, 0.25)",
      star: "#a86a12",
      starSoft: "rgba(168, 106, 18, 0.14)",
      good: "#2f7a45",
      warn: "#a86a12",
      bad: "#b43a3a",
    },
  }),
  Object.freeze({
    id: "neutral",
    label: "Neutral",
    bestFor: "Neyvia daily shell",
    // Night route: a deep ink canvas from the brand's navy, one luminous route
    // color for action and live work, and north-star gold for verified outcomes.
    tokens: {
      bg: "#0a0d14",
      panel: "#11151f",
      panelSoft: "#151a26",
      sidebar: "#0d1018",
      raised: "#151a25",
      hover: "rgba(160, 182, 230, 0.07)",
      selected: "rgba(96, 140, 255, 0.13)",
      line: "rgba(150, 172, 220, 0.11)",
      lineStrong: "rgba(150, 172, 220, 0.2)",
      text: "#eef2fa",
      textSoft: "#b7c0d2",
      // Both clear 4.5:1 on every surface from the canvas to a selected row.
      muted: "#95a0b5",
      faint: "#7f8a9f",
      accent: "#2f6bff",
      accentText: "#7aa5ff",
      accentInk: "#ffffff",
      accentSoft: "rgba(61, 123, 255, 0.16)",
      glow: "rgba(61, 123, 255, 0.45)",
      star: "#f5b94c",
      starSoft: "rgba(245, 185, 76, 0.14)",
      good: "#3fcf8e",
      warn: "#f2a93b",
      bad: "#ff6b76",
    },
  }),
  Object.freeze({
    id: "high-contrast",
    label: "High Contrast",
    bestFor: "Maximum legibility",
    tokens: {
      bg: "#000000",
      panel: "#0a0a0a",
      panelSoft: "#141414",
      sidebar: "#000000",
      raised: "#0a0a0a",
      hover: "rgba(255, 255, 255, 0.12)",
      selected: "rgba(255, 255, 0, 0.18)",
      line: "rgba(255, 255, 255, 0.35)",
      lineStrong: "rgba(255, 255, 255, 0.6)",
      text: "#ffffff",
      textSoft: "#f0f0f0",
      muted: "#d0d0d0",
      faint: "#c8c8c8",
      accent: "#ffff00",
      accentText: "#ffff00",
      accentInk: "#000000",
      accentSoft: "rgba(255, 255, 0, 0.18)",
      glow: "rgba(255, 255, 0, 0.4)",
      star: "#ffcc00",
      starSoft: "rgba(255, 204, 0, 0.2)",
      good: "#00ff66",
      warn: "#ffcc00",
      bad: "#ff4444",
    },
  }),
]);

export const NEYVIA_TOOLBAR_CATALOG = Object.freeze([
  Object.freeze({ id: "attach", label: "Attach", hint: "Add files to the session" }),
  Object.freeze({ id: "search", label: "Web Search", hint: "Search the web when permitted" }),
  Object.freeze({ id: "pdf", label: "PDF Reader", hint: "Open document artifacts" }),
  Object.freeze({ id: "data", label: "Data Analyst", hint: "Sheets and charts" }),
  Object.freeze({ id: "images", label: "Image Playground", hint: "Tool drawer — not a mini-app" }),
  Object.freeze({ id: "canvas", label: "Canvas", hint: "Open mixed artifact canvas" }),
  Object.freeze({ id: "citations", label: "Citations", hint: "Show source receipts" }),
  Object.freeze({ id: "terminal", label: "Terminal", hint: "Runtime command surface" }),
  Object.freeze({ id: "diff", label: "Diff", hint: "Review file changes" }),
]);

export const NEYVIA_TEXT_SIZES = Object.freeze(["sm", "md", "lg", "xl"]);
export const NEYVIA_EFFECT_INTENSITIES = Object.freeze([
  "off",
  "subtle",
  "balanced",
  "vivid",
]);
export const NEYVIA_TRANSPARENCY_LEVELS = Object.freeze([
  "solid",
  "soft",
  "glass",
]);

/** Session tool pane layouts — see neyviaEcosystem.js / docs/NEYVIA_ECOSYSTEM_INTEGRATION.md */
export const NEYVIA_SESSION_TOOL_PANE_LAYOUTS = Object.freeze([
  "dock-right",
  "dock-left",
  "fullscreen",
  "floating-center",
]);

export const NEYVIA_SYSTEM_PROMPT_PROFILES = Object.freeze([
  Object.freeze({ value: "auto", label: "Auto", description: "Neyvia selects the task contract from your request." }),
  Object.freeze({ value: "general", label: "General", description: "Direct, balanced assistance without a specialist bias." }),
  Object.freeze({ value: "implementation", label: "Build", description: "Durable implementation with focused verification." }),
  Object.freeze({ value: "diagnosis", label: "Debug", description: "Evidence-first diagnosis and a clearly proven cause." }),
  Object.freeze({ value: "ui_ux", label: "UI / UX", description: "Accessible interface hierarchy and realistic user proof." }),
  Object.freeze({ value: "research", label: "Research", description: "Source-grounded investigation with uncertainty made visible." }),
  Object.freeze({ value: "writing", label: "Writing", description: "Clear structure, voice, and audience-aware editing." }),
  Object.freeze({ value: "creative", label: "Creative", description: "Exploratory concepts with a concrete finished artifact." }),
  Object.freeze({ value: "security", label: "Security", description: "Bounded defensive analysis with explicit scope and proof." }),
]);

export const DEFAULT_NEYVIA_SHELL_PREFERENCES = Object.freeze({
  uiPreset: "researcher",
  appearanceTheme: "neutral",
  colorMode: "auto",
  textSize: "md",
  reduceMotion: false,
  effectIntensity: "balanced",
  transparencyLevel: "soft",
  focusIndicators: true,
  showLabels: true,
  showToolNames: true,
  compactMode: false,
  detailLevel: "expanded",
  toolbar: ["attach", "search", "pdf", "data", "canvas"],
  /** Default dock-right: tool panes sit beside the live session/agent. */
  sessionToolPaneLayout: "dock-right",
  /**
   * Silent ecosystem prompt rewrite for integrated lanes (Claude Code, etc.).
   * Default ON — intentional coaching so inside-Neyvia > standalone; not a thin clone.
   */
  silentEcosystemPromptRewrite: true,
  systemPromptProfile: "auto",
});

function safeParse(raw) {
  try {
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function clampToolbar(ids) {
  const allowed = new Set(NEYVIA_TOOLBAR_CATALOG.map(item => item.id));
  const next = [];
  const seen = new Set();
  for (const id of Array.isArray(ids) ? ids : []) {
    const key = String(id || "").trim();
    if (!allowed.has(key) || seen.has(key)) continue;
    seen.add(key);
    next.push(key);
  }
  return next.length ? next : [...DEFAULT_NEYVIA_SHELL_PREFERENCES.toolbar];
}

function normalizeNeyviaShellPreferencesUnchecked(value = {}) {
  const preset = NEYVIA_UI_PRESETS.find(item => item.id === value.uiPreset) || NEYVIA_UI_PRESETS[2];
  const theme = NEYVIA_APPEARANCE_THEMES.find(item => item.id === value.appearanceTheme)
    || NEYVIA_APPEARANCE_THEMES.find(item => item.id === "neutral");
  const textSize = NEYVIA_TEXT_SIZES.includes(value.textSize) ? value.textSize : "md";
  const colorMode = ["auto", "light", "dark"].includes(value.colorMode) ? value.colorMode : "auto";
  const effectIntensity = NEYVIA_EFFECT_INTENSITIES.includes(value.effectIntensity)
    ? value.effectIntensity
    : DEFAULT_NEYVIA_SHELL_PREFERENCES.effectIntensity;
  const transparencyLevel = NEYVIA_TRANSPARENCY_LEVELS.includes(value.transparencyLevel)
    ? value.transparencyLevel
    : DEFAULT_NEYVIA_SHELL_PREFERENCES.transparencyLevel;
  const detailLevel = ["minimal", "balanced", "expanded"].includes(value.detailLevel)
    ? value.detailLevel
    : (preset.detailLevel || "balanced");

  const sessionToolPaneLayout = NEYVIA_SESSION_TOOL_PANE_LAYOUTS.includes(value.sessionToolPaneLayout)
    ? value.sessionToolPaneLayout
    : DEFAULT_NEYVIA_SHELL_PREFERENCES.sessionToolPaneLayout;
  const silentEcosystemPromptRewrite = value.silentEcosystemPromptRewrite !== false;
  const systemPromptProfile = NEYVIA_SYSTEM_PROMPT_PROFILES.some(
    profile => profile.value === value.systemPromptProfile,
  ) ? value.systemPromptProfile : DEFAULT_NEYVIA_SHELL_PREFERENCES.systemPromptProfile;

  return {
    uiPreset: preset.id,
    appearanceTheme: theme.id,
    colorMode,
    textSize,
    reduceMotion: Boolean(value.reduceMotion),
    effectIntensity,
    transparencyLevel,
    focusIndicators: value.focusIndicators !== false,
    showLabels: value.showLabels !== undefined ? Boolean(value.showLabels) : preset.showLabels,
    showToolNames: value.showToolNames !== undefined ? Boolean(value.showToolNames) : preset.showToolNames,
    compactMode: value.compactMode !== undefined ? Boolean(value.compactMode) : preset.compactMode,
    detailLevel,
    toolbar: clampToolbar(value.toolbar?.length ? value.toolbar : preset.toolbar),
    sessionToolPaneLayout,
    silentEcosystemPromptRewrite,
    systemPromptProfile,
  };
}

export function loadNeyviaShellPreferences() {
  if (typeof window === "undefined") return { ...DEFAULT_NEYVIA_SHELL_PREFERENCES };
  const stored = safeParse(window.localStorage?.getItem(NEYVIA_SHELL_PREFERENCES_KEY));
  return normalizeNeyviaShellPreferences(stored || {});
}

export function saveNeyviaShellPreferences(preferences) {
  const normalized = normalizeNeyviaShellPreferences(preferences);
  if (typeof window !== "undefined") {
    window.localStorage?.setItem(NEYVIA_SHELL_PREFERENCES_KEY, JSON.stringify(normalized));
  }
  return normalized;
}

export function densityForUiPreset(presetId) {
  if (presetId === "minimal" || presetId === "engineer") return "compact";
  if (presetId === "researcher") return "spacious";
  return "comfortable";
}

export function applyNeyviaUiPreset(preferences, presetId) {
  const preset = NEYVIA_UI_PRESETS.find(item => item.id === presetId) || NEYVIA_UI_PRESETS[0];
  return normalizeNeyviaShellPreferences({
    ...preferences,
    uiPreset: preset.id,
    toolbar: [...preset.toolbar],
    showLabels: preset.showLabels,
    showToolNames: preset.showToolNames,
    compactMode: preset.compactMode,
    detailLevel: preset.detailLevel,
  });
}

export function applyNeyviaAdaptiveExperience(preferences, experience = {}) {
  const current = normalizeNeyviaShellPreferences(preferences);
  const requestedPreset = String(experience?.uiPreset || "").trim();
  const presetId = NEYVIA_UI_PRESETS.some(item => item.id === requestedPreset)
    ? requestedPreset
    : current.uiPreset;
  const next = applyNeyviaUiPreset(current, presetId);
  const requestedPromptProfile = String(experience?.systemPromptProfile || "").trim();
  const systemPromptProfile = NEYVIA_SYSTEM_PROMPT_PROFILES.some(
    profile => profile.value === requestedPromptProfile,
  ) ? requestedPromptProfile : next.systemPromptProfile;
  return normalizeNeyviaShellPreferences({
    ...next,
    systemPromptProfile,
  });
}

export function shellSurfaceToNeyviaId(surface) {
  const normalized = String(surface || "").trim().toLowerCase();
  if (normalized === "builder" || normalized === "builder-review" || normalized === "orchestration") {
    return "orchestration";
  }
  if (normalized === "notebook") return "notebook";
  if (normalized === "lab") return "lab";
  if (normalized === "library") return "library";
  if (normalized === "agent" || normalized === "home" || normalized === "chat") return "chat";
  return "";
}

export function neyviaIdToShellSurface(surfaceId) {
  const row = NEYVIA_SHELL_SURFACES.find(item => item.id === surfaceId);
  return row?.surface || "agent";
}

export function resolveEffectiveColorScheme(preferences, systemPrefersDark = true) {
  if (preferences.colorMode === "light") return "light";
  if (preferences.colorMode === "dark") return "dark";
  return systemPrefersDark ? "dark" : "light";
}

export function appearanceThemeForScheme(preferences, scheme) {
  if (preferences.appearanceTheme === "high-contrast") return "high-contrast";
  if (scheme === "light" && ["neutral", "high-contrast"].includes(preferences.appearanceTheme)) {
    return "light";
  }
  if (scheme === "dark" && ["light", "warm"].includes(preferences.appearanceTheme)) {
    return "neutral";
  }
  return preferences.appearanceTheme;
}

// "#7aa5ff" -> "122 165 255", for layers that compose rgb(var(--x) / alpha).
function hexChannels(value) {
  const hex = String(value || "").trim().replace(/^#/, "");
  if (!/^[0-9a-f]{6}$/i.test(hex)) return "";
  return [0, 2, 4].map(index => parseInt(hex.slice(index, index + 2), 16)).join(" ");
}

export function neyviaShellCssVariables(preferences, scheme = "dark") {
  const themeId = appearanceThemeForScheme(preferences, scheme);
  const theme = NEYVIA_APPEARANCE_THEMES.find(item => item.id === themeId) || NEYVIA_APPEARANCE_THEMES[2];
  const t = theme.tokens;
  const d = t;
  return {
    "--neyvia-bg": t.bg,
    "--neyvia-panel": t.panel,
    "--neyvia-panel-soft": t.panelSoft,
    "--neyvia-line": t.line,
    "--neyvia-text": t.text,
    "--neyvia-muted": t.muted,
    "--neyvia-accent": t.accent,
    "--neyvia-accent-soft": t.accentSoft,
    "--neyvia-good": t.good,
    "--neyvia-warn": t.warn,
    "--neyvia-bad": t.bad,
    // Canonical design-system tokens (neyviaDesignSystem.css). Older layers
    // redefine the --neyvia-* names with !important; nothing redefines these.
    "--ny-bg": d.bg,
    "--ny-panel": d.panel,
    "--ny-panel-soft": d.panelSoft,
    "--ny-sidebar": d.sidebar || d.panel,
    "--ny-raised": d.raised || d.panelSoft,
    "--ny-hover": d.hover || d.accentSoft,
    "--ny-selected": d.selected || d.accentSoft,
    "--ny-line": d.line,
    "--ny-line-strong": d.lineStrong || d.line,
    "--ny-text": d.text,
    "--ny-text-soft": d.textSoft || d.text,
    "--ny-muted": d.muted,
    "--ny-faint": d.faint || d.muted,
    "--ny-accent": d.accent,
    "--ny-accent-text": d.accentText || d.accent,
    "--ny-accent-rgb": hexChannels(d.accentText || d.accent) || "122 165 255",
    "--ny-accent-ink": d.accentInk || d.bg,
    "--ny-accent-soft": d.accentSoft,
    "--ny-glow": d.glow || d.accentSoft,
    "--ny-star": d.star || d.warn,
    "--ny-star-soft": d.starSoft || d.accentSoft,
    "--ny-good": d.good,
    "--ny-warn": d.warn,
    "--ny-bad": d.bad,
    "--ny-scheme": themeId === "light" || themeId === "warm" ? "light" : "dark",
  };
}

export function normalizeNeyviaShellPreferences(...args) {
  const before = frontendContractBefore("preferences.normalize", args);
  return checkedFrontendAction("preferences.normalize", args, normalizeNeyviaShellPreferencesUnchecked(...args), before);
}
