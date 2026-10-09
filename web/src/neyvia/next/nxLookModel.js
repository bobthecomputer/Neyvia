import { THEME_INK } from "./nxThemeRegistry.js";

// Settings > Look: typeface pairs, text size and the background behind the
// chats, plus the contrast guard that keeps text readable on any background.
// Pure data and functions (no React, no DOM), shared by the Look card, the
// shell and the tests. The PC service validates the same names and limits
// (src/grant_agent/neyvia_settings.py: FONTS, TEXT_SIZES, LOOK_DEFAULTS).

// ---- typefaces ---------------------------------------------------------------
// Every family is bundled (SIL OFL 1.1 via @fontsource-variable, see
// neyviaFonts.css) or ships with Windows, so the app looks the same offline.

const SEGOE_TEXT = '"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif';
const GEIST = '"Geist", "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif';
const INTER = '"Inter", "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif';
const NEWSREADER = '"Newsreader", "Iowan Old Style", "Palatino Linotype", Georgia, serif';

export const FONTS = [
  { id: "neyvia", label: "Neyvia", hint: "Geist, with Newsreader for titles", text: GEIST, display: NEWSREADER, displayWeight: 500, tracking: "-0.01em" },
  { id: "windows", label: "Windows", hint: "Segoe UI Variable, like Windows 11", text: SEGOE_TEXT, display: '"Segoe UI Variable Display", "Segoe UI", system-ui, sans-serif', displayWeight: 600, tracking: "-0.015em", mono: '"Cascadia Code", "Cascadia Mono", Consolas, ui-monospace, monospace' },
  { id: "inter", label: "Inter", hint: "Very clear at small sizes", text: INTER, display: INTER, displayWeight: 600, tracking: "-0.025em" },
  { id: "geist", label: "Geist", hint: "One clean typeface everywhere", text: GEIST, display: GEIST, displayWeight: 600, tracking: "-0.03em" },
  { id: "editorial", label: "Editorial", hint: "Fraunces titles over Inter text", text: INTER, display: '"Fraunces", "Iowan Old Style", Georgia, serif', displayWeight: 560, tracking: "-0.015em" },
];
export const FONT_IDS = FONTS.map(font => font.id);

export const TEXT_SIZES = [
  { id: "s", label: "Small", scale: 0.92 },
  { id: "m", label: "Medium", scale: 1 },
  { id: "l", label: "Large", scale: 1.1 },
];

export const BACKGROUND_KINDS = ["theme", "preset", "solid", "image"];
export const DIM_MAX = 90;
export const BLUR_MAX = 40;

// Follow the sun (plan 29 THEMES2, nxSunModel.js): off by default; sunrise and sunset are the person's own local times.
export const SUN_DEFAULTS = Object.freeze({ follow: false, intoNight: false, sunrise: "07:00", sunset: "19:30" });
const TIME = /^([01]\d|2[0-3]):([0-5]\d)$/;
const MIN_DAYLIGHT = 240; // a day shorter than four hours is a typo, not a place

export const toMinutes = value => { const match = TIME.exec(String(value || "")); return match ? Number(match[1]) * 60 + Number(match[2]) : NaN; };

/** Whatever was saved (or nothing), as a complete, valid Follow-the-sun setting. */
export function normalizeSun(raw) {
  const sun = raw && typeof raw === "object" ? raw : {};
  let sunrise = TIME.test(sun.sunrise) ? sun.sunrise : SUN_DEFAULTS.sunrise;
  let sunset = TIME.test(sun.sunset) ? sun.sunset : SUN_DEFAULTS.sunset;
  if (toMinutes(sunset) - toMinutes(sunrise) < MIN_DAYLIGHT) { sunrise = SUN_DEFAULTS.sunrise; sunset = SUN_DEFAULTS.sunset; }
  return { follow: sun.follow === true, intoNight: sun.intoNight === true, sunrise, sunset };
}

export const LOOK_DEFAULTS = Object.freeze({
  font: "neyvia", textSize: "m",
  background: Object.freeze({ kind: "theme", preset: "", color: "", image: "", dim: 0, blur: 0 }),
  sun: SUN_DEFAULTS,
});

const HEX = /^#[0-9a-f]{6}$/;
const IMAGE = /^bg-[0-9a-f]{16}\.(png|jpg|webp)$/;
const int = (value, top) => (Number.isInteger(value) && value >= 0 && value <= top ? value : 0);

/** Whatever was saved (or nothing), as a complete, valid look. */
export function normalizeLook(raw) {
  const look = raw && typeof raw === "object" ? raw : {};
  const bg = look.background && typeof look.background === "object" ? look.background : {};
  const color = typeof bg.color === "string" && HEX.test(bg.color.toLowerCase()) ? bg.color.toLowerCase() : "";
  const image = typeof bg.image === "string" && IMAGE.test(bg.image) ? bg.image : "";
  const preset = typeof bg.preset === "string" && /^[a-z0-9-]{1,40}$/.test(bg.preset) ? bg.preset : "";
  let kind = BACKGROUND_KINDS.includes(bg.kind) ? bg.kind : "theme";
  if ((kind === "solid" && !color) || (kind === "image" && !image) || (kind === "preset" && !preset)) kind = "theme";
  return {
    font: FONT_IDS.includes(look.font) ? look.font : LOOK_DEFAULTS.font,
    textSize: TEXT_SIZES.some(size => size.id === look.textSize) ? look.textSize : LOOK_DEFAULTS.textSize,
    background: { kind, preset, color, image, dim: int(bg.dim, DIM_MAX), blur: int(bg.blur, BLUR_MAX) },
    sun: normalizeSun(look.sun),
  };
}

export const fontFor = id => FONTS.find(font => font.id === id) || FONTS[0];
export const textScale = id => (TEXT_SIZES.find(size => size.id === id) || TEXT_SIZES[1]).scale;

// ---- colour and contrast (WCAG 2.x) -----------------------------------------------

export function hexToRgb(hex) {
  const value = String(hex).replace("#", "");
  return [0, 2, 4].map(at => parseInt(value.slice(at, at + 2), 16));
}
export const rgbToHex = rgb => `#${rgb.map(c => Math.round(Math.min(255, Math.max(0, c))).toString(16).padStart(2, "0")).join("")}`;

/** `top` at `alpha` over `base`, the way the browser composites (sRGB). */
export function over(base, top, alpha) {
  const a = hexToRgb(base), b = hexToRgb(top);
  return rgbToHex(a.map((c, i) => c * (1 - alpha) + b[i] * alpha));
}

export function luminance(hex) {
  const [r, g, b] = hexToRgb(hex).map(c => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

export const AA_BODY = 4.5;

/**
 * The smallest dim (0..DIM_MAX, in %) of `overlay` over every sample so each
 * ink reads at `target` or better. Returns DIM_MAX + 1 when even the most dim
 * is not enough (only possible if the overlay itself fails).
 */
export function requiredDim(inks, overlay, samples, target = AA_BODY) {
  const passes = dim => samples.every(sample => {
    const seen = over(sample, overlay, dim / 100);
    return inks.every(ink => contrast(ink, seen) >= target);
  });
  if (passes(0)) return 0;
  for (let dim = 1; dim <= DIM_MAX; dim += 1) if (passes(dim)) return dim;
  return DIM_MAX + 1;
}

// ---- the themes' ink: mirrored from nxThemes.css by the registry --------------
// (a test reads nxThemes.css and fails if the registry drifts from it)

export { THEME_INK };

// ---- background presets ---------------------------------------------------------
// The same four names in every theme, each drawn in that theme's light, so a
// chosen preset follows a theme change. `samples` are the colours the text can
// land on (the brightest or darkest spots), for the contrast guard.

export const GRAIN = "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='180' height='180'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0.5  0 0 0 0 0.5  0 0 0 0 0.5  0 0 0 0.6 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>\")";

const rgba = (hex, alpha) => { const [r, g, b] = hexToRgb(hex); return `rgba(${r}, ${g}, ${b}, ${alpha})`; };

function preset(id, label, base, glows, grain = 0) {
  // glows: [{ at, size, color, alpha }]; samples are each glow's centre over the base.
  const layers = glows.map(g => g.linear
    ? `linear-gradient(${g.linear}, ${g.stops.join(", ")})`
    : `radial-gradient(${g.size} at ${g.at}, ${rgba(g.color, g.alpha)} 0%, transparent 62%)`);
  const samples = [base, ...glows.flatMap(g => (g.linear ? g.stops : [over(base, g.color, g.alpha)]))];
  return { id, label, base, css: [...layers, base].join(", "), samples, grain };
}

export const PRESETS = {
  dark: [
    preset("glow", "Glow", "#0c1611", [
      { at: "82% -12%", size: "1100px 680px", color: "#2f7a52", alpha: 0.42 },
      { at: "-8% 112%", size: "900px 600px", color: "#1e5a3c", alpha: 0.38 }]),
    preset("horizon", "Horizon", "#0b1510", [
      { at: "50% 122%", size: "1500px 560px", color: "#e0893a", alpha: 0.26 },
      { at: "50% -20%", size: "1400px 500px", color: "#245c40", alpha: 0.3 }]),
    preset("mist", "Mist", "#0e1a15", [{ linear: "160deg", stops: ["#15291f", "#0d1814", "#11231f"] }]),
    preset("grain", "Grain", "#0d1712", [{ at: "50% 0%", size: "1400px 700px", color: "#1c3a2a", alpha: 0.5 }], 0.07),
  ],
  light: [
    preset("glow", "Glow", "#f6f2e8", [
      { at: "84% -12%", size: "1100px 680px", color: "#cfe3c8", alpha: 0.75 },
      { at: "-8% 112%", size: "900px 600px", color: "#dbe6cd", alpha: 0.7 }]),
    preset("horizon", "Horizon", "#f7f3ea", [
      { at: "50% 122%", size: "1500px 560px", color: "#ffbf80", alpha: 0.42 },
      { at: "50% -20%", size: "1400px 500px", color: "#d7e7d0", alpha: 0.6 }]),
    preset("mist", "Mist", "#f4f2ea", [{ linear: "160deg", stops: ["#eaf2e6", "#f6f2e8", "#e6efea"] }]),
    preset("grain", "Grain", "#f3eee2", [{ at: "50% 0%", size: "1400px 700px", color: "#fffaf0", alpha: 0.7 }], 0.06),
  ],
  sunset: [
    preset("glow", "Glow", "#141020", [
      { at: "80% -12%", size: "1100px 680px", color: "#5a3a9a", alpha: 0.42 },
      { at: "-8% 112%", size: "900px 600px", color: "#8a3a6a", alpha: 0.26 }]),
    preset("horizon", "Horizon", "#130f1e", [
      { at: "50% 124%", size: "1500px 560px", color: "#ff8a3d", alpha: 0.24 },
      { at: "50% -20%", size: "1400px 500px", color: "#3a2a72", alpha: 0.45 }]),
    preset("mist", "Mist", "#16112a", [{ linear: "160deg", stops: ["#221a3c", "#141020", "#22142a"] }]),
    preset("grain", "Grain", "#151022", [{ at: "50% 0%", size: "1400px 700px", color: "#2c2050", alpha: 0.6 }], 0.07),
  ],
  night: [
    preset("glow", "Glow", "#05141a", [
      { at: "28% -14%", size: "1100px 600px", color: "#1d6e8c", alpha: 0.36 },
      { at: "86% -10%", size: "900px 560px", color: "#178a6c", alpha: 0.3 }]),
    preset("horizon", "Horizon", "#04131a", [
      { at: "50% 124%", size: "1500px 560px", color: "#f0a850", alpha: 0.18 },
      { at: "50% -20%", size: "1400px 500px", color: "#11506a", alpha: 0.4 }]),
    preset("mist", "Mist", "#071a20", [{ linear: "160deg", stops: ["#0c2a32", "#06161c", "#0a2622"] }]),
    preset("grain", "Grain", "#06161c", [{ at: "50% 0%", size: "1400px 700px", color: "#0e3340", alpha: 0.6 }], 0.07),
  ],
  terminal: [
    preset("glow", "Glow", "#040a06", [
      { at: "50% -14%", size: "1200px 620px", color: "#1f8f52", alpha: 0.3 },
      { at: "-8% 112%", size: "900px 560px", color: "#0f5a30", alpha: 0.3 }]),
    preset("horizon", "Horizon", "#040906", [
      { at: "50% 124%", size: "1500px 560px", color: "#ffb52e", alpha: 0.14 },
      { at: "50% -20%", size: "1400px 500px", color: "#136b3a", alpha: 0.34 }]),
    preset("mist", "Mist", "#05100a", [{ linear: "160deg", stops: ["#0a1d12", "#040a06", "#08180f"] }]),
    preset("grain", "Grain", "#050c07", [{ at: "50% 0%", size: "1400px 700px", color: "#0e3a20", alpha: 0.5 }], 0.08),
  ],
  paper: [
    preset("glow", "Glow", "#f5f4ef", [
      { at: "84% -12%", size: "1100px 680px", color: "#dfe5f2", alpha: 0.8 },
      { at: "-8% 112%", size: "900px 600px", color: "#e6e8ee", alpha: 0.7 }]),
    preset("horizon", "Horizon", "#f6f4ee", [
      { at: "50% 122%", size: "1500px 560px", color: "#f1d8bc", alpha: 0.55 },
      { at: "50% -20%", size: "1400px 500px", color: "#e0e6f1", alpha: 0.6 }]),
    preset("mist", "Mist", "#f3f2ed", [{ linear: "160deg", stops: ["#e8ecf3", "#f5f4ef", "#ebeaf0"] }]),
    preset("grain", "Grain", "#f3f2ec", [{ at: "50% 0%", size: "1400px 700px", color: "#fffefb", alpha: 0.7 }], 0.07),
  ],
  ember: [
    preset("glow", "Glow", "#15100d", [
      { at: "80% -12%", size: "1100px 680px", color: "#8a3a1e", alpha: 0.4 },
      { at: "-8% 112%", size: "900px 600px", color: "#6a2a18", alpha: 0.36 }]),
    preset("horizon", "Horizon", "#140f0c", [
      { at: "50% 124%", size: "1500px 560px", color: "#e8573d", alpha: 0.3 },
      { at: "50% -20%", size: "1400px 500px", color: "#4a2616", alpha: 0.4 }]),
    preset("mist", "Mist", "#181210", [{ linear: "160deg", stops: ["#251a15", "#140f0c", "#22160f"] }]),
    preset("grain", "Grain", "#17110e", [{ at: "50% 0%", size: "1400px 700px", color: "#3a2218", alpha: 0.55 }], 0.07),
  ],
};
export const PRESET_IDS = ["glow", "horizon", "mist", "grain"];

/** Suggested solid colours per theme (the picker allows any colour). */
export const SWATCHES = {
  dark: ["#0d1612", "#13241b", "#1a2a22", "#16201c", "#1f1a14"],
  light: ["#f5f1e6", "#eef3ea", "#f7efe2", "#eceee8", "#f3ece6"],
  sunset: ["#141020", "#1c1530", "#24142a", "#121a2a", "#1e1018"],
  night: ["#05141a", "#08202a", "#0a1c1a", "#0c1626", "#101a1e"],
  terminal: ["#040906", "#06130b", "#0a1a10", "#030a0a", "#0c1208"],
  paper: ["#f4f3ee", "#eef0f4", "#f6f1ea", "#ececea", "#f2f4ee"],
  ember: ["#15100d", "#1d130f", "#201510", "#171212", "#1b1410"],
};

const WORST_IMAGE = { dark: ["#ffffff"], light: ["#000000"], sunset: ["#ffffff"], night: ["#ffffff"], terminal: ["#ffffff"], paper: ["#000000"], ember: ["#ffffff"] };

/**
 * What to draw behind the chats for this theme and look. `imageSamples` are
 * colours measured from the picture (null until it has been measured, when the
 * worst case is assumed). The result's `dim` already includes the guard:
 * never lower than what WCAG AA body text needs (`minDim`).
 */
export function resolveBackground(theme, rawLook, imageSamples = null) {
  const ink = THEME_INK[theme] || THEME_INK.dark;
  const look = normalizeLook(rawLook);
  const bg = look.background;
  const inks = [ink.text, ink.muted];
  let samples = null, layer = null, grain = 0, label = "";
  if (bg.kind === "preset") {
    const found = (PRESETS[theme] || PRESETS.dark).find(p => p.id === bg.preset);
    if (found) { samples = found.samples; layer = found.css; grain = found.grain; label = found.label; }
  } else if (bg.kind === "solid") {
    samples = [bg.color]; layer = bg.color; label = bg.color;
  } else if (bg.kind === "image") {
    samples = imageSamples?.length ? imageSamples : WORST_IMAGE[theme] || WORST_IMAGE.dark; label = "Your image";
  }
  if (!samples) return { kind: "theme", dim: 0, minDim: 0, raised: false, overlay: ink.bg, blur: 0, grain: 0, layer: null, label: "Theme" };
  // Grain moves pixels a little either way: keep a small margin above 4.5:1.
  const minDim = Math.min(DIM_MAX, requiredDim(inks, ink.bg, samples, grain ? AA_BODY + 0.25 : AA_BODY));
  const dim = Math.max(bg.dim, minDim);
  return { kind: bg.kind, dim, minDim, raised: minDim > bg.dim, overlay: ink.bg, blur: bg.kind === "image" ? bg.blur : 0, grain, layer, label, measured: bg.kind !== "image" || Boolean(imageSamples?.length) };
}

/** The darkened colour a solid background actually shows at `dim`. */
export const shownColor = (theme, color, dim) => over(color, (THEME_INK[theme] || THEME_INK.dark).bg, dim / 100);
