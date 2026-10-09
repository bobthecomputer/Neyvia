import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { THEMES, THEME_REGISTRY } from "./nxThemeRegistry.js";
import {
  BLEND_MINUTES, PALETTE_VARS, blendVars, daylightAt, dayPartAt, followedTheme, horizonAt, mixPalettes, normalizeSun, SUN_DEFAULTS,
} from "./nxSunModel.js";

import {
  AA_BODY, DIM_MAX, FONTS, LOOK_DEFAULTS, PRESETS, PRESET_IDS, SWATCHES, THEME_INK, contrast, normalizeLook, over, requiredDim,
  resolveBackground,
} from "./nxLookModel.js";

const css = readFileSync(new URL("./nxThemes.css", import.meta.url), "utf8");
const THEME_SELECTOR = Object.fromEntries(THEMES.map(id => [id, `.nx[data-nx-theme="${id}"]`]));

/** The custom properties of one theme's main block in nxThemes.css. */
function themeVars(theme) {
  const start = css.indexOf(`${THEME_SELECTOR[theme]} {`);
  assert.ok(start >= 0, `theme block for ${theme}`);
  const body = css.slice(start, css.indexOf("\n}", start));
  return Object.fromEntries([...body.matchAll(/(--nx-[a-z0-9-]+):\s*([^;]+);/g)].map(match => [match[1], match[2].trim()]));
}
const rgbaOver = (base, value) => {
  const match = /rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)/.exec(value);
  if (!match) return value;
  const hex = `#${[1, 2, 3].map(i => Number(match[i]).toString(16).padStart(2, "0")).join("")}`;
  return over(base, hex, Number(match[4]));
};

test("the JS mirror of each theme's ink matches nxThemes.css", () => {
  for (const theme of Object.keys(THEME_INK)) {
    const vars = themeVars(theme);
    const ink = THEME_INK[theme];
    assert.equal(vars["--nx-bg"], ink.bg, `${theme} bg`);
    assert.equal(vars["--nx-sidebar"], ink.sidebar, `${theme} sidebar`);
    assert.equal(vars["--nx-text"], ink.text, `${theme} text`);
    assert.equal(vars["--nx-muted"], ink.muted, `${theme} muted`);
    const entry = THEME_REGISTRY.find(item => item.id === theme);
    assert.equal(vars["--nx-accent"], entry.accent, `${theme} accent`);
    assert.equal(vars["--nx-panel"], entry.panel, `${theme} panel`);
  }
});

test("every theme: each text colour reads at 4.5:1 on every surface, hover and selection included", () => {
  for (const theme of THEMES) {
    const vars = themeVars(theme);
    const surfaces = ["--nx-bg", "--nx-sidebar", "--nx-panel", "--nx-raised", "--nx-raised-2"].map(name => vars[name]);
    const states = surfaces.flatMap(surface => [surface, rgbaOver(surface, vars["--nx-hover"]), rgbaOver(surface, vars["--nx-active"])]);
    for (const ink of ["--nx-text", "--nx-text-2", "--nx-muted", "--nx-faint", "--nx-accent-text", "--nx-green", "--nx-red", "--nx-gold", "--nx-amber"]) {
      // Morning and Paper keep a bright sun for marks and a deeper ochre for running text.
      const name = ink === "--nx-amber" && vars["--nx-state-running-text"] ? "--nx-state-running-text" : ink;
      for (const surface of states) {
        assert.ok(contrast(vars[name], surface) >= AA_BODY, `${theme} ${name} ${vars[name]} on ${surface}: ${contrast(vars[name], surface).toFixed(2)}`);
      }
    }
    assert.ok(contrast(vars["--nx-on-accent"], vars["--nx-accent"]) >= AA_BODY, `${theme} button text on the accent`);
    assert.ok(contrast(vars["--nx-on-accent"], vars["--nx-accent-hi"]) >= AA_BODY, `${theme} button text on the hover accent`);
  }
});

test("normalizeLook keeps valid looks and repairs anything else", () => {
  assert.deepEqual(normalizeLook(undefined), { ...LOOK_DEFAULTS, background: { ...LOOK_DEFAULTS.background } });
  const look = { font: "inter", textSize: "l", background: { kind: "solid", color: "#12261C", preset: "", image: "", dim: 30, blur: 0 } };
  assert.deepEqual(normalizeLook(look), { ...look, background: { ...look.background, color: "#12261c" }, sun: SUN_DEFAULTS });
  assert.equal(normalizeLook({ font: "papyrus" }).font, "neyvia");
  assert.equal(normalizeLook({ textSize: "xxl" }).textSize, "m");
  // A background missing what it needs falls back to the theme's own.
  assert.equal(normalizeLook({ background: { kind: "image", image: "" } }).background.kind, "theme");
  assert.equal(normalizeLook({ background: { kind: "image", image: "../x.png" } }).background.kind, "theme");
  assert.equal(normalizeLook({ background: { kind: "solid", color: "red" } }).background.kind, "theme");
  assert.equal(normalizeLook({ background: { dim: 400, blur: -3 } }).background.dim, 0);
  assert.equal(FONTS.length, 5);
});

test("requiredDim finds the least dim that makes every ink pass", () => {
  // White text on white needs the dark overlay almost all the way.
  const dim = requiredDim(["#edf2ea"], "#0d1612", ["#ffffff"]);
  assert.ok(dim > 0 && dim <= DIM_MAX);
  assert.ok(contrast("#edf2ea", over("#ffffff", "#0d1612", dim / 100)) >= AA_BODY);
  assert.ok(contrast("#edf2ea", over("#ffffff", "#0d1612", (dim - 1) / 100)) < AA_BODY, "one less would fail");
  assert.equal(requiredDim(["#edf2ea"], "#0d1612", ["#0d1612"]), 0);
});

test("contrast guard: a too-light solid colour in a dark theme is dimmed until body text passes", () => {
  for (const theme of ["dark", "sunset", "night"]) {
    const look = { background: { kind: "solid", color: "#f0f0f0", dim: 0 } };
    const bg = resolveBackground(theme, look);
    assert.ok(bg.raised && bg.dim === bg.minDim && bg.dim > 0, theme);
    const shown = over("#f0f0f0", bg.overlay, bg.dim / 100);
    for (const ink of [THEME_INK[theme].text, THEME_INK[theme].muted]) assert.ok(contrast(ink, shown) >= AA_BODY, `${theme} ${ink} on ${shown}`);
  }
  // Morning: a too-dark colour is lightened the same way (its overlay is paper).
  const morning = resolveBackground("light", { background: { kind: "solid", color: "#101010" } });
  assert.ok(morning.raised);
  assert.ok(contrast(THEME_INK.light.muted, over("#101010", morning.overlay, morning.dim / 100)) >= AA_BODY);
});

test("contrast guard never lowers a dim the person chose", () => {
  const bg = resolveBackground("dark", { background: { kind: "solid", color: "#13241b", dim: 40 } });
  assert.equal(bg.dim, 40);
  assert.equal(bg.raised, false);
});

test("an unmeasured picture assumes the worst; a measured one uses its own colours", () => {
  const unmeasured = resolveBackground("dark", { background: { kind: "image", image: "bg-0123456789abcdef.webp", dim: 10, blur: 12 } });
  assert.equal(unmeasured.measured, false);
  assert.ok(unmeasured.dim >= 80, `worst case dims a lot (${unmeasured.dim})`);
  const darkPhoto = resolveBackground("dark", { background: { kind: "image", image: "bg-0123456789abcdef.webp", dim: 10, blur: 12 } }, ["#0a1a10", "#1d2e22", "#24402c"]);
  assert.equal(darkPhoto.dim, 10);
  assert.equal(darkPhoto.blur, 12);
  const brightPhoto = resolveBackground("dark", { background: { kind: "image", image: "bg-0123456789abcdef.webp", dim: 10 } }, ["#9ec9e8", "#f5f7fa", "#3a5a2a"]);
  assert.ok(brightPhoto.raised && brightPhoto.dim > 10);
  for (const sample of ["#9ec9e8", "#f5f7fa", "#3a5a2a"]) assert.ok(contrast(THEME_INK.dark.muted, over(sample, brightPhoto.overlay, brightPhoto.dim / 100)) >= AA_BODY);
});

test("every preset and suggested colour passes on its own (no forced dim)", () => {
  for (const [theme, presets] of Object.entries(PRESETS)) {
    assert.deepEqual(presets.map(p => p.id), PRESET_IDS, `${theme} has the shared preset names`);
    for (const preset of presets) {
      const bg = resolveBackground(theme, { background: { kind: "preset", preset: preset.id } });
      assert.equal(bg.minDim, 0, `${theme}/${preset.id} needs dim ${bg.minDim}`);
    }
    for (const color of SWATCHES[theme]) assert.equal(resolveBackground(theme, { background: { kind: "solid", color } }).minDim, 0, `${theme} swatch ${color}`);
  }
});

test("the theme's own background needs no guard", () => {
  const bg = resolveBackground("dark", LOOK_DEFAULTS);
  assert.equal(bg.kind, "theme");
  assert.equal(bg.dim, 0);
});

// ---- plan 29 THEMES2: identities, Follow the sun ---------------------------------------------------------------

/** A theme's palette (hex tokens the blend moves) read from nxThemes.css, in nxSunModel's names. */
const paletteOf = theme => { const vars = themeVars(theme); return Object.fromEntries(Object.entries(PALETTE_VARS).map(([name, variable]) => [name, vars[variable] || (name === "running" ? vars["--nx-amber"] : undefined)])); };

test("every theme has its one idea, an ambient description and a valid day/night pair", () => {
  for (const theme of THEME_REGISTRY) {
    assert.ok(typeof theme.idea === "string" && theme.idea.length > 3, `${theme.id} idea`);
    assert.ok(theme.ambient && typeof theme.ambient.kind === "string" && typeof theme.ambient.moves === "boolean", `${theme.id} ambient`);
    const pair = theme.daypair;
    if (!pair) continue;
    for (const twin of [pair.day, pair.night].filter(Boolean)) assert.ok(THEMES.includes(twin), `${theme.id} twin ${twin}`);
    assert.equal(Boolean(pair.lamp), Boolean(theme.lamp), `${theme.id} lamp palette goes with a lamp pair`);
  }
  // Paper is the one still theme; Terminal, Night Green and Ember have no day pair (the switch is hidden for them).
  assert.equal(THEME_REGISTRY.find(theme => theme.id === "paper").ambient.moves, false);
  for (const id of ["terminal", "night", "ember"]) assert.equal(THEME_REGISTRY.find(theme => theme.id === id).daypair, null);
});

test("Paper's lamplight reads: every ink on every lamp surface, and every step of the blend toward it", () => {
  const paper = paletteOf("paper"), lamp = THEME_REGISTRY.find(theme => theme.id === "paper").lamp;
  const surfaces = ["bg", "sidebar", "panel", "raised", "raised2"];
  for (const ink of ["text", "text2", "muted", "faint", "accentText", "green", "red", "gold"]) {
    for (const surface of surfaces) assert.ok(contrast(lamp[ink], lamp[surface]) >= AA_BODY, `lamp ${ink} on ${surface}: ${contrast(lamp[ink], lamp[surface]).toFixed(2)}`);
  }
  for (let step = 0; step <= 50; step += 1) {
    const mixed = mixPalettes(paper, lamp, step / 50);
    for (const ink of ["text", "text2", "muted", "faint", "accentText", "green", "red", "gold", "running"]) {
      for (const surface of surfaces) assert.ok(contrast(mixed[ink], mixed[surface]) >= AA_BODY, `lamp blend ${step}/50 ${ink} on ${surface}`);
    }
  }
});

test("a crossfade never lowers text contrast: every step between Forest and Morning, and Sunset and Night Green, reads", () => {
  const surfaces = ["bg", "sidebar", "panel", "raised", "raised2"];
  const inks = ["text", "text2", "muted", "faint", "accentText", "green", "red", "gold", "running"];
  for (const [day, night] of [["light", "dark"], ["sunset", "night"]]) {
    const palettes = { [day]: paletteOf(day), [night]: paletteOf(night) };
    for (let step = 0; step <= 200; step += 1) {
      const nightness = step / 200;
      const shown = nightness < 0.5 ? day : night;
      const vars = blendVars({ blending: nightness > 0 && nightness < 1, lamp: false, day, night, shown, nightness }, id => palettes[id], null);
      const own = palettes[shown];
      for (const ink of inks) {
        for (const surface of surfaces) {
          const painted = vars[PALETTE_VARS[surface]] || own[surface], inkPainted = vars[PALETTE_VARS[ink]] || own[ink];
          assert.ok(contrast(inkPainted, painted) >= AA_BODY, `${day}/${night} at ${nightness}: ${ink} ${inkPainted} on ${surface} ${painted}: ${contrast(inkPainted, painted).toFixed(2)}`);
        }
      }
    }
  }
});

test("the crossfade has no jump in the surfaces: the page background is the same colour either side of the swap", () => {
  const palettes = { light: paletteOf("light"), dark: paletteOf("dark") };
  const frame = nightness => blendVars({ blending: true, lamp: false, day: "light", night: "dark", shown: nightness < 0.5 ? "light" : "dark", nightness }, id => palettes[id], null);
  const before = frame(0.4999)["--nx-bg"], after = frame(0.5001)["--nx-bg"];
  assert.ok(before && after);
  const [r1, g1, b1] = [1, 3, 5].map(i => parseInt(before.slice(i, i + 2), 16)), [r2, g2, b2] = [1, 3, 5].map(i => parseInt(after.slice(i, i + 2), 16));
  assert.ok(Math.abs(r1 - r2) + Math.abs(g1 - g2) + Math.abs(b1 - b2) <= 4, `${before} vs ${after}`);
  // And it moves steadily: no step between neighbouring frames (40 minutes in 200 steps) is more than a few levels.
  let last = frame(0)["--nx-bg"] || palettes.light.bg;
  for (let step = 1; step <= 200; step += 1) {
    const now = frame(step / 200)["--nx-bg"] || palettes.dark.bg;
    const delta = [1, 3, 5].reduce((sum, i) => sum + Math.abs(parseInt(last.slice(i, i + 2), 16) - parseInt(now.slice(i, i + 2), 16)), 0);
    assert.ok(delta <= 30, `step ${step}: ${last} to ${now}`);
    last = now;
  }
});

test("Follow the sun: off by default, hidden for themes with no pair, a 40-minute crossfade at sunrise and sunset", () => {
  const at = (hour, minute = 0) => new Date(2026, 9, 8, hour, minute);
  const on = { follow: true };
  // Off (the default): the picked theme, always.
  assert.equal(followedTheme("dark", undefined, at(12)).shown, "dark");
  assert.equal(followedTheme("dark", { follow: false }, at(12)).shown, "dark");
  // On: Forest by night, Morning by day (default 07:00 / 19:30).
  assert.equal(followedTheme("dark", on, at(12)).shown, "light");
  assert.equal(followedTheme("dark", on, at(23)).shown, "dark");
  assert.equal(followedTheme("dark", on, at(3)).shown, "dark");
  assert.equal(followedTheme("light", on, at(23)).shown, "dark");
  assert.equal(followedTheme("light", on, at(12)).shown, "light");
  // The crossfade is 40 minutes centred on sunrise and sunset, never a jump.
  assert.equal(followedTheme("dark", on, at(6, 39)).blending, false);
  assert.equal(followedTheme("dark", on, at(7, 0)).blending, true);
  assert.equal(followedTheme("dark", on, at(7, 21)).blending, false);
  assert.equal(followedTheme("dark", on, at(19, 20)).blending, true);
  assert.ok(Math.abs(followedTheme("dark", on, at(19, 30)).nightness - 0.5) < 0.01);
  const before = followedTheme("dark", on, at(19, 10)).nightness, after = followedTheme("dark", on, at(19, 11)).nightness;
  assert.ok(after > before && after - before < 0.06, "one minute moves the blend by a few percent at most");
  // Themes with no pair never change; Paper stays Paper (its lamp is a palette); Sunset needs "into the night".
  for (const id of ["terminal", "night", "ember"]) assert.equal(followedTheme(id, on, at(12)).shown, id);
  assert.equal(followedTheme("paper", on, at(23)).shown, "paper");
  assert.equal(followedTheme("paper", on, at(23)).lamp, true);
  assert.equal(followedTheme("paper", on, at(12)).blending, false);
  assert.equal(followedTheme("sunset", on, at(23)).shown, "sunset");
  assert.equal(followedTheme("sunset", { follow: true, intoNight: true }, at(23)).shown, "night");
  assert.equal(followedTheme("sunset", { follow: true, intoNight: true }, at(19, 45)).shown, "sunset");
  // The sun's own times are editable and checked.
  assert.deepEqual(normalizeSun({ follow: true, sunrise: "06:15", sunset: "21:05" }), { follow: true, intoNight: false, sunrise: "06:15", sunset: "21:05" });
  assert.deepEqual(normalizeSun({ sunrise: "25:00", sunset: "nope" }), SUN_DEFAULTS);
  assert.deepEqual(normalizeSun({ sunrise: "12:00", sunset: "13:00" }), SUN_DEFAULTS, "a one-hour day is a typo");
  assert.equal(BLEND_MINUTES, 40);
});

test("the time-of-day source: dayparts, daylight and Sunset's horizon follow the clock", () => {
  const sun = normalizeSun({});
  assert.equal(dayPartAt(6 * 60 + 30, sun), "dawn");
  assert.equal(dayPartAt(12 * 60, sun), "day");
  assert.equal(dayPartAt(19 * 60, sun), "dusk");
  assert.equal(dayPartAt(23 * 60, sun), "night");
  assert.equal(daylightAt(12 * 60, sun), 1);
  assert.equal(daylightAt(23 * 60, sun), 0);
  assert.ok(daylightAt(7 * 60, sun) > 0.4 && daylightAt(7 * 60, sun) < 0.6, "half light at sunrise");
  // High in the afternoon, sinking toward evening, a last glow after sunset, never gone.
  const afternoon = horizonAt(15 * 60, sun), evening = horizonAt(19 * 60, sun), glow = horizonAt(20 * 60, sun), dark = horizonAt(2 * 60, sun);
  assert.ok(afternoon.height > evening.height && evening.height > glow.height && glow.height > dark.height - 0.001);
  assert.ok(evening.glow > afternoon.glow, "warmest toward sunset");
  assert.ok(glow.glow > dark.glow, "a last glow after sunset");
  assert.ok(dark.height > 0.03);
});
