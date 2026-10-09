// The one list of themes. Everything that names a theme (the store, Settings,
// the launcher, the sidebar menu, the sign-in page, app skins, the Look
// contrast guard, the lab, voice) reads it from here, so adding a theme is one
// entry plus one block in nxThemes.css. Pure data: no React, no DOM.
//
//   id       the data-nx-theme value and the shell's internal name
//   setting  the name canonical Settings stores (src/grant_agent/neyvia_settings.py: THEMES)
//   scheme   dark | light: drives color-scheme-aware parts such as the sign-in icon
//   ink      mirror of the CSS tokens the contrast guard needs (a test reads nxThemes.css
//            and fails when these drift from it)
//   accent   the theme's action colour, panel its card colour (the picker draws a preview from them; tests check both against nxThemes.css)
//   shift    how app skins (nxAppSkinModel) lean toward this theme: { toward, amount } or null
//   blurb    one line for the picker
//   idea     the theme's one idea (plan 29 THEMES2): it shows in the ambient layer, the working light and the motion signature
//   ambient  what moves (or deliberately does not) behind the reading column, for the picker, the lab and the LAYA proof:
//            { kind, moves } where moves is true when the layer has slow ambient motion
//   daypair  the optional day/night twin used by Settings > Look > Follow the sun (null: no natural pair, the switch is hidden):
//            { day: id } the theme shown by day (Forest), { night: id } the theme shown by night (Morning),
//            { night: id, option: "intoNight" } a second, optional night twin (Sunset into Night Green),
//            { lamp: true } the same theme, warmer and dimmer after sunset (Paper, palette in `lamp`)
//   lamp     Paper's lamplight palette: the surfaces and inks it blends to after sunset (contrast-checked in nxLookModel.test.js)

export const THEME_REGISTRY = Object.freeze([
  { id: "dark", label: "Forest", setting: "forest", scheme: "dark", blurb: "Sunlight through leaves, warm light where agents work",
    idea: "Komorebi: sun through leaves at night", ambient: { kind: "canopy", moves: true }, daypair: { day: "light" },
    accent: "#46b077", panel: "#0f1b15",
    ink: { bg: "#0c1612", sidebar: "#08100c", text: "#edf2ea", muted: "#a5b6a9" }, shift: null },
  { id: "light", label: "Morning", setting: "morning", scheme: "light", blurb: "Warm paper, first sun through the trees",
    idea: "The same forest at first light", ambient: { kind: "leaf shadows", moves: true }, daypair: { night: "dark" },
    accent: "#3a774b", panel: "#faf7f0",
    ink: { bg: "#f5f1e6", sidebar: "#ebe9da", text: "#17221a", muted: "#465143" }, shift: { toward: "#f5efe0", amount: 0.4 } },
  { id: "sunset", label: "Sunset", setting: "sunset", scheme: "dark", blurb: "A warm horizon that follows the real sun",
    idea: "Horizon: the sun going down", ambient: { kind: "horizon band", moves: false }, daypair: { night: "night", option: "intoNight" },
    accent: "#ff7a3d", panel: "#181325",
    ink: { bg: "#141020", sidebar: "#110d1b", text: "#fbf1ea", muted: "#a99cb4" }, shift: { toward: "#3a2760", amount: 0.2 } },
  { id: "night", label: "Night Green", setting: "night-green", scheme: "dark", blurb: "Dark water, slow ripples, a moon path",
    idea: "Dark water", ambient: { kind: "caustics", moves: true }, daypair: null,
    accent: "#1aa98a", panel: "#081b22",
    ink: { bg: "#05141a", sidebar: "#041017", text: "#e2f1ef", muted: "#93aeb1" }, shift: { toward: "#0a3550", amount: 0.22 } },
  { id: "terminal", label: "Terminal", setting: "terminal", scheme: "dark", blurb: "Green phosphor, monospace, scanlines",
    idea: "Green phosphor", ambient: { kind: "scanlines and rain", moves: true }, daypair: null,
    accent: "#34e07a", panel: "#07100a",
    ink: { bg: "#040906", sidebar: "#020503", text: "#c8f7d6", muted: "#78c28f" }, shift: null },
  { id: "paper", label: "Paper", setting: "paper", scheme: "light", blurb: "Ink on paper, flat and calm",
    idea: "Ink on paper, calm", ambient: { kind: "paper grain", moves: false }, daypair: { lamp: true },
    lamp: { bg: "#eee4d0", sidebar: "#e3d8c1", panel: "#f4ecdb", raised: "#f8f1e2", raised2: "#fbf5e8", text: "#1b1813", text2: "#352f26", muted: "#51473a", faint: "#5b5143", accentText: "#1b3478", green: "#1b6140", red: "#a3322a", gold: "#8a4a0c" },
    accent: "#23408e", panel: "#faf9f5",
    ink: { bg: "#f4f3ee", sidebar: "#e9e8e1", text: "#15171c", muted: "#4b4f58" }, shift: { toward: "#f4f3ee", amount: 0.45 } },
  { id: "ember", label: "Ember", setting: "ember", scheme: "dark", blurb: "Warm coals under the sunset logo",
    idea: "Coals in the dark", ambient: { kind: "breathing coals", moves: true }, daypair: null,
    accent: "#e8573d", panel: "#1a1411",
    ink: { bg: "#15100d", sidebar: "#0f0b09", text: "#f6ece3", muted: "#bfad9f" }, shift: { toward: "#4a2416", amount: 0.22 } },
]);

export const THEMES = THEME_REGISTRY.map(theme => theme.id);
export const DEFAULT_THEME = "dark";
export const THEME_LABELS = Object.fromEntries(THEME_REGISTRY.map(theme => [theme.id, theme.label]));
export const THEME_FROM_SETTINGS = Object.fromEntries(THEME_REGISTRY.map(theme => [theme.setting, theme.id]));
export const THEME_TO_SETTINGS = Object.fromEntries(THEME_REGISTRY.map(theme => [theme.id, theme.setting]));
export const THEME_INK = Object.fromEntries(THEME_REGISTRY.map(theme => [theme.id, theme.ink]));
export const THEME_SHIFT = Object.fromEntries(THEME_REGISTRY.map(theme => [theme.id, theme.shift]));
export const THEME_SCHEME = Object.fromEntries(THEME_REGISTRY.map(theme => [theme.id, theme.scheme]));
export const THEME_BLURBS = Object.fromEntries(THEME_REGISTRY.map(theme => [theme.id, theme.blurb]));
export const THEME_IDEAS = Object.fromEntries(THEME_REGISTRY.map(theme => [theme.id, theme.idea]));
export const THEME_DAYPAIR = Object.fromEntries(THEME_REGISTRY.map(theme => [theme.id, theme.daypair]));
/** Themes that can follow the sun: the Settings switch is hidden for the rest. */
export const canFollowSun = id => Boolean(THEME_DAYPAIR[id]);
export const isTheme = id => THEMES.includes(id);
