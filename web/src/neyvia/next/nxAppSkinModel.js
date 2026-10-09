import { THEMES, THEME_SCHEME, THEME_SHIFT } from "./nxThemeRegistry.js";
import { checkedProofsEModel } from "./nxProofsEContracts.js";
// Each app's own look, in every theme (Paul: "having the theme green doesn't mean everything must
// be green; the apps need real themes, real design"). The shell chrome carries the theme; an app's
// window carries a skin made from what the app is:
//
//   code      Terminal, files and diffs: ink-dark (or clean light) code surfaces, a cyan cursor
//   reader    PDF: a neutral desk under white paper, a reading blue
//   notebook  Notes: warm paper and terracotta ink
//   finder    Files: cool neutral system surfaces, blue folders
//   web       Browser and app previews: neutral browser chrome around the page
//   monitor   Apps agents are using, LAYA: a quiet control room, agent violet
//   studio    App Factory, Mobile Studio, iOS Studio: a design canvas, build indigo
//   graphite  3D Studio and Game Dev: a neutral graphite viewport, selection blue
//   darkroom  Image Studio: photo-neutral grey (no hue at all), paper-white actions, a soft violet for links
//   scholar   Research (CiteCraft, Notebook): ink and parchment, a citation blue
//
// A skin has a dark and a light base. Morning uses the light base; Forest the dark base as is;
// Sunset and Night Green shift only the surfaces toward their dusk violet or deep-water blue, by
// an amount each skin allows (the darkroom never shifts: photos are judged on neutral grey). Text
// and accents never take the theme's hue, so nothing in an app is painted green.
//
// Pure functions. NxPlacement puts skinTokens() on the window as CSS custom properties; every
// component inside already draws with the --nx-* names, so it follows the skin.

export const SKINS = ["code", "reader", "notebook", "finder", "web", "monitor", "studio", "graphite", "darkroom", "scholar"];
export const THEME_IDS = THEMES;

// App id (or tool screen) -> skin.
const APP_SKIN = {
  terminal: "code", pdf: "reader", notes: "notebook", files: "finder", browser: "web", preview: "web",
  "3d-studio": "graphite", godot: "graphite", unity: "graphite", roblox: "graphite", "asset-checks": "graphite", playtest: "graphite",
  "image-studio": "darkroom", "image-playground": "darkroom", lumaforge: "darkroom",
  research: "scholar", citecraft: "scholar", notebook: "scholar", "scroll-generator": "scholar",
  "app-factory": "studio", "mobile-studio": "studio", "ios-studio": "studio", frameweave: "studio",
  laya: "monitor", "hill-climb": "graphite", awareness: "code",
};
// Pane kind -> skin (pane.show). The preview pane is the computer-use view unless it is remote control.
const PANE_SKIN = { terminal: "code", file: "code", diff: "code", browser: "web", preview: "monitor", perception: "monitor" };

// Dark and light bases. Keys: bg sidebar panel raised raised2 | text text2 muted faint | accent accentHi accentText onAccent.
const BASES = {
  code: {
    tint: 1,
    dark: { bg: "#0d1014", sidebar: "#0a0d10", panel: "#0f1317", raised: "#151a20", raised2: "#1b2129", text: "#e6eaf0", text2: "#c4cbd5", muted: "#9ba5b3", faint: "#97a1af", accent: "#3ab0d8", accentHi: "#58c4e6", accentText: "#84d5f0", onAccent: "#03151c" },
    light: { bg: "#f6f7f9", sidebar: "#edf0f3", panel: "#fbfcfd", raised: "#ffffff", raised2: "#ffffff", text: "#1b2128", text2: "#343c46", muted: "#4e5763", faint: "#59626e", accent: "#0a6d93", accentHi: "#1083ad", accentText: "#085d7d", onAccent: "#ffffff" },
  },
  reader: {
    tint: 0.5,
    dark: { bg: "#1b1b1d", sidebar: "#18181a", panel: "#222225", raised: "#29292d", raised2: "#303035", text: "#ececee", text2: "#cfcfd4", muted: "#b3b3ba", faint: "#a9a9b0", accent: "#6ea6ff", accentHi: "#86b4ff", accentText: "#a6c8ff", onAccent: "#071a33" },
    light: { bg: "#e3e1dc", sidebar: "#ebe9e4", panel: "#f6f5f2", raised: "#fdfcfa", raised2: "#ffffff", text: "#1f1f22", text2: "#38383d", muted: "#4d4d54", faint: "#57575e", accent: "#1f5fbf", accentHi: "#2b6fd6", accentText: "#1a52a6", onAccent: "#ffffff" },
  },
  notebook: {
    tint: 0.7,
    dark: { bg: "#1a1816", sidebar: "#161412", panel: "#1d1b18", raised: "#24211d", raised2: "#2b2823", text: "#efe9df", text2: "#d5cdc1", muted: "#aea698", faint: "#aba396", accent: "#e0855f", accentHi: "#ea9a77", accentText: "#f2ae8f", onAccent: "#2a1208" },
    light: { bg: "#fbf8f2", sidebar: "#f3eee4", panel: "#fffdf8", raised: "#fffefb", raised2: "#ffffff", text: "#2a241d", text2: "#433b31", muted: "#5a5145", faint: "#645b4f", accent: "#b4532f", accentHi: "#c4633d", accentText: "#9a4425", onAccent: "#ffffff" },
  },
  finder: {
    tint: 1,
    dark: { bg: "#15171b", sidebar: "#111316", panel: "#17191d", raised: "#1d2025", raised2: "#23272d", text: "#eceef2", text2: "#ccd1d9", muted: "#a4abb6", faint: "#9ea5b1", accent: "#5b9cf5", accentHi: "#78aff7", accentText: "#97c0fa", onAccent: "#04162e" },
    light: { bg: "#fbfbfc", sidebar: "#f0f2f5", panel: "#ffffff", raised: "#ffffff", raised2: "#ffffff", text: "#1c1f24", text2: "#353a42", muted: "#50565f", faint: "#5b616b", accent: "#1f6fd1", accentHi: "#2f7fe0", accentText: "#1a5fb4", onAccent: "#ffffff" },
  },
  web: {
    tint: 1,
    dark: { bg: "#1d1e21", sidebar: "#18191c", panel: "#222327", raised: "#292a2f", raised2: "#303137", text: "#ececef", text2: "#cfd0d6", muted: "#b4b6bf", faint: "#abadb6", accent: "#7aa7ff", accentHi: "#8fb5ff", accentText: "#abc7ff", onAccent: "#08183a" },
    light: { bg: "#eef0f3", sidebar: "#e6e9ed", panel: "#f7f8fa", raised: "#ffffff", raised2: "#ffffff", text: "#1d2025", text2: "#363a42", muted: "#4e535c", faint: "#595e68", accent: "#1a66d6", accentHi: "#2a76e6", accentText: "#1557b8", onAccent: "#ffffff" },
  },
  monitor: {
    tint: 1,
    dark: { bg: "#121318", sidebar: "#0f1014", panel: "#15161c", raised: "#1b1d24", raised2: "#22242c", text: "#ebecf2", text2: "#cbcdd8", muted: "#a3a6b5", faint: "#9ea1b0", accent: "#b57cf0", accentHi: "#c391f3", accentText: "#d2adf7", onAccent: "#1e0733" },
    light: { bg: "#f6f6fa", sidebar: "#eeeef5", panel: "#fbfbfe", raised: "#ffffff", raised2: "#ffffff", text: "#1c1d26", text2: "#353746", muted: "#505367", faint: "#5b5e71", accent: "#8a3fc0", accentHi: "#9a50d0", accentText: "#7535a6", onAccent: "#ffffff" },
  },
  studio: {
    tint: 1,
    dark: { bg: "#141519", sidebar: "#111216", panel: "#18191e", raised: "#1e2026", raised2: "#25272e", text: "#eef0f4", text2: "#cfd2db", muted: "#a6aab7", faint: "#a0a4b2", accent: "#7c83ff", accentHi: "#949aff", accentText: "#b2b6ff", onAccent: "#0b0d33" },
    light: { bg: "#f1f2f5", sidebar: "#e9eaef", panel: "#f8f8fb", raised: "#ffffff", raised2: "#ffffff", text: "#1b1d24", text2: "#343744", muted: "#4f5262", faint: "#5a5d6d", accent: "#4f55e0", accentHi: "#6066ea", accentText: "#4146c2", onAccent: "#ffffff" },
  },
  graphite: {
    tint: 0.6,
    dark: { bg: "#1c1e22", sidebar: "#18191d", panel: "#202226", raised: "#272a2f", raised2: "#2e3137", text: "#eceef1", text2: "#cdd1d7", muted: "#b2b7bf", faint: "#a9aeb7", accent: "#4da3ff", accentHi: "#69b2ff", accentText: "#90c6ff", onAccent: "#051a33" },
    light: { bg: "#e8eaed", sidebar: "#e1e4e8", panel: "#f3f4f6", raised: "#fbfbfc", raised2: "#ffffff", text: "#1d2025", text2: "#353941", muted: "#4c5159", faint: "#565b64", accent: "#1769d1", accentHi: "#2679e0", accentText: "#155cb6", onAccent: "#ffffff" },
  },
  darkroom: {
    tint: 0,
    dark: { bg: "#161616", sidebar: "#121212", panel: "#1a1a1a", raised: "#222222", raised2: "#2a2a2a", text: "#ededed", text2: "#cfcfcf", muted: "#a9a9a9", faint: "#a3a3a3", accent: "#e9e6e1", accentHi: "#ffffff", accentText: "#c9c2f2", onAccent: "#161616" },
    light: { bg: "#f2f2f2", sidebar: "#e9e9e9", panel: "#f8f8f8", raised: "#ffffff", raised2: "#ffffff", text: "#1e1e1e", text2: "#383838", muted: "#505050", faint: "#5a5a5a", accent: "#1f1f1f", accentHi: "#3a3a3a", accentText: "#5747c2", onAccent: "#ffffff" },
  },
  scholar: {
    tint: 0.8,
    dark: { bg: "#14161c", sidebar: "#111318", panel: "#171a21", raised: "#1d2029", raised2: "#242833", text: "#ece9e2", text2: "#d0ccc2", muted: "#aaa69d", faint: "#a7a39b", accent: "#7da2f0", accentHi: "#93b2f3", accentText: "#abc3f7", onAccent: "#08183a" },
    light: { bg: "#faf8f3", sidebar: "#f2efe7", panel: "#fffdf9", raised: "#ffffff", raised2: "#ffffff", text: "#23211d", text2: "#3b3833", muted: "#54504a", faint: "#5e5a53", accent: "#2a5298", accentHi: "#3561ab", accentText: "#244a8a", onAccent: "#ffffff" },
  },
};

// How each theme moves an app's surfaces (never its text or accent): Morning toward its warm paper,
// Sunset toward dusk violet,
// Night Green toward deep water. Forest uses the bases as they are.

// The ANSI colours the terminal draws with (xterm), one set per tone.
const ANSI = {
  dark: { black: "#1b2129", red: "#f07178", green: "#9ad285", yellow: "#e6c07b", blue: "#6cb6ff", magenta: "#d4a0f7", cyan: "#5fd1e6", white: "#d7dde5",
    brightBlack: "#6b7686", brightRed: "#ff8f95", brightGreen: "#b5e6a0", brightYellow: "#f2d398", brightBlue: "#8dc7ff", brightMagenta: "#e2bbfb", brightCyan: "#86e0f0", brightWhite: "#f3f6fa" },
  light: { black: "#24292f", red: "#c4262e", green: "#2a7a2e", yellow: "#8a5a00", blue: "#0b5cc4", magenta: "#8a3fb8", cyan: "#0a6d85", white: "#6e7781",
    brightBlack: "#57606a", brightRed: "#a40e26", brightGreen: "#1f6a28", brightYellow: "#7a4d00", brightBlue: "#0a4fae", brightMagenta: "#6e2fa0", brightCyan: "#085a6e", brightWhite: "#8c959f" },
};

// ---- colour helpers ----------------------------------------------------------------------

const hex = value => {
  const match = /^#([0-9a-f]{6})$/i.exec(String(value || ""));
  if (!match) throw new Error(`Not a colour: ${value}`);
  const n = parseInt(match[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const toHex = rgb => `#${rgb.map(v => Math.round(Math.min(255, Math.max(0, v))).toString(16).padStart(2, "0")).join("")}`;
const mix = (a, b, amount) => { const x = hex(a), y = hex(b); return toHex(x.map((v, i) => v + (y[i] - v) * amount)); };
const rgba = (color, alpha) => { const [r, g, b] = hex(color); return `rgba(${r}, ${g}, ${b}, ${alpha})`; };

/** The skin an open window wears, or null when it is the shell's own (settings, missions…). */
function raw_skinFor(desc) {
  if (!desc || typeof desc !== "object") return null;
  if (desc.type === "pane") {
    if (desc.kind === "preview" && String(desc.target || "").startsWith("remote")) return null;
    return PANE_SKIN[desc.kind] || null;
  }
  if (desc.type === "app") return APP_SKIN[desc.app] || null;
  return null;
}

/** Light or dark, from the theme registry (Morning and Paper are light). */
export const skinTone = theme => (THEME_SCHEME[theme] === "light" ? "light" : "dark");

/** The skin's colours in a theme: base, then the theme's surface shift. */
function raw_skinPalette(skin, theme) {
  const spec = BASES[skin];
  if (!spec) return null;
  const tone = skinTone(theme);
  const base = spec[tone];
  const shift = THEME_SHIFT[theme] || null;
  const amount = shift ? shift.amount * spec.tint : 0;
  const surface = color => (amount ? mix(color, shift.toward, amount) : color);
  return {
    skin, theme, tone,
    bg: surface(base.bg), sidebar: surface(base.sidebar), panel: surface(base.panel), raised: surface(base.raised), raised2: surface(base.raised2),
    text: base.text, text2: base.text2, muted: base.muted, faint: base.faint,
    accent: base.accent, accentHi: base.accentHi, accentText: base.accentText, onAccent: base.onAccent,
  };
}

/** CSS custom properties for a window wearing `skin` in `theme` (null: the shell's own colours). */
function raw_skinTokens(skin, theme) {
  const p = raw_skinPalette(skin, theme);
  if (!p) return null;
  const dark = p.tone === "dark";
  const ansi = ANSI[p.tone];
  return {
    "--nx-bg": p.bg, "--nx-sidebar": p.sidebar, "--nx-panel": p.panel, "--nx-raised": p.raised, "--nx-raised-2": p.raised2,
    "--nx-hover": rgba(p.text, dark ? 0.055 : 0.05), "--nx-active": rgba(p.text, dark ? 0.09 : 0.085),
    "--nx-line": rgba(p.text, dark ? 0.09 : 0.11), "--nx-line-strong": rgba(p.text, dark ? 0.16 : 0.2),
    "--nx-text": p.text, "--nx-text-2": p.text2, "--nx-muted": p.muted, "--nx-faint": p.faint,
    "--nx-accent": p.accent, "--nx-accent-hi": p.accentHi, "--nx-accent-text": p.accentText, "--nx-on-accent": p.onAccent,
    "--nx-accent-soft": rgba(p.accent, dark ? 0.16 : 0.11), "--nx-selection": rgba(p.accent, dark ? 0.32 : 0.22),
    "--nx-scrollbar": rgba(p.text, dark ? 0.18 : 0.22), "--nx-focus-ring": dark ? p.accentHi : p.accent,
    "--nx-focus": `0 0 0 2px ${p.bg}, 0 0 0 4px ${dark ? p.accentHi : p.accent}`,
    "--nx-shade": dark ? "rgba(0, 0, 0, 0.6)" : "rgba(22, 26, 34, 0.18)",
    "--nx-card-shadow": dark
      ? `0 0 0 1px ${rgba(p.text, 0.09)}, inset 0 1px 0 ${rgba(p.text, 0.04)}, 6px 14px 30px -20px rgba(0, 0, 0, 0.8)`
      : `0 0 0 1px ${rgba(p.text, 0.11)}, inset 0 1px 0 rgba(255, 255, 255, 0.9), 1px 2px 3px -1px rgba(22, 26, 34, 0.1), 7px 15px 30px -18px rgba(22, 26, 34, 0.22)`,
    "--nx-shadow-pop": dark
      ? `0 0 0 1px ${rgba(p.text, 0.16)}, 8px 18px 48px -12px rgba(0, 0, 0, 0.75), 1px 2px 6px rgba(0, 0, 0, 0.4)`
      : `0 0 0 1px ${rgba(p.text, 0.2)}, 9px 20px 48px -14px rgba(22, 26, 34, 0.28), 1px 2px 6px rgba(22, 26, 34, 0.08)`,
    ...Object.fromEntries(Object.entries(ansi).map(([name, value]) => [`--nx-ansi-${name.replace(/[A-Z]/g, c => `-${c.toLowerCase()}`)}`, value])),
  };
}

export const skinFor = desc => checkedProofsEModel("appskin.skinFor", [desc], raw_skinFor(desc));
export const skinPalette = (skin, theme) => checkedProofsEModel("appskin.skinPalette", [skin, theme], raw_skinPalette(skin, theme));
export const skinTokens = (skin, theme) => checkedProofsEModel("appskin.skinTokens", [skin, theme], raw_skinTokens(skin, theme));

// Every skin in every theme, checked once (the contracts measure contrast and hue): the
// proofs-e-models runner calls this; the shell calls skinTokens per window and caches it.
export function allSkins() {
  return SKINS.flatMap(skin => THEME_IDS.map(theme => ({ skin, theme, tokens: skinTokens(skin, theme) })));
}

const cache = new Map();
/** skinTokens, computed (and checked) once per skin and theme. */
export function cachedSkinTokens(skin, theme) {
  if (!skin) return null;
  const key = `${skin}|${theme}`;
  if (!cache.has(key)) cache.set(key, skinTokens(skin, THEME_IDS.includes(theme) ? theme : "dark"));
  return cache.get(key);
}
