// The one time-of-day source for the themes (plan 29 THEMES2): where the sun is, which part of the day it is, and
// what "Follow the sun" shows. Pure data and arithmetic, no React and no DOM, so the contracts and the
// theme tests can run it. nxSun.js turns it into a hook and into the root attributes the CSS reads.
//
// Times come from the person's local clock. Sunrise and sunset are the settings' two times (default 07:00 and 19:30, editable
// in Settings > Look): a system time zone gives no latitude cheaply, so they are never guessed.
//
//   daypart   dawn | day | dusk | night, a 40-minute window of change is centred on sunrise and on sunset
//   daylight  0 (full dark) .. 1 (full day), eased through those windows: the --nx-sun-phase variable
//   nightness 0 (the day twin) .. 1 (the night twin), the eased progress of the 40-minute crossfade
//
// A crossfade never lowers text contrast. Between a dark and a light theme the surfaces pass through a mid grey where
// only pure white or pure black text reads (4.5:1 at relative luminance 0.179, and only if every surface is that one colour).
// So the blend moves the surfaces of the theme being shown toward ONE meeting colour (the two backgrounds' hues at luminance 0.179)
// while its inks are pushed toward white or black exactly as far as 4.5:1 needs; at the midpoint the surfaces are the same colour
// on both sides, the theme swaps (text only changes: one 320 ms cross-fade of the page, nxMorph.fadeTheme) and the other theme's
// surfaces leave the meeting colour the same way. Two dark themes (Sunset, Night Green) read all the way and blend directly.

import { THEME_DAYPAIR, THEME_REGISTRY } from "./nxThemeRegistry.js";
import { SUN_DEFAULTS, contrast, hexToRgb, normalizeSun, rgbToHex, toMinutes } from "./nxLookModel.js";

export const BLEND_MINUTES = 40;
export { SUN_DEFAULTS, normalizeSun, toMinutes };

const clamp01 = value => Math.min(1, Math.max(0, value));
const smooth = value => { const x = clamp01(value); return x * x * (3 - 2 * x); };
export const minutesOfDay = date => date.getHours() * 60 + date.getMinutes() + date.getSeconds() / 60;

/** dawn: an hour either side of the rising sun; dusk: the golden hour and an hour after; night: the rest. */
export function dayPartAt(minutes, sun) {
  const rise = toMinutes(sun.sunrise), set = toMinutes(sun.sunset);
  if (minutes >= rise - 40 && minutes < rise + 60) return "dawn";
  if (minutes >= rise + 60 && minutes < set - 90) return "day";
  if (minutes >= set - 90 && minutes < set + 60) return "dusk";
  return "night";
}

/** 0 in the dark .. 1 in full day, eased through the two 40-minute windows centred on sunrise and sunset. */
export function daylightAt(minutes, sun) {
  const rise = toMinutes(sun.sunrise), set = toMinutes(sun.sunset), half = BLEND_MINUTES / 2;
  if (minutes < rise - half || minutes >= set + half) return 0;
  if (minutes < rise + half) return smooth((minutes - (rise - half)) / BLEND_MINUTES);
  if (minutes < set - half) return 1;
  return 1 - smooth((minutes - (set - half)) / BLEND_MINUTES);
}

/**
 * Sunset's horizon band: how tall it is (a share of the shell, high in the afternoon, sinking toward evening) and how
 * warm and bright it burns (it peaks at sunset and leaves a last glow for an hour). Never fully gone, so the theme keeps its horizon.
 */
export function horizonAt(minutes, sun) {
  const rise = toMinutes(sun.sunrise), set = toMinutes(sun.sunset);
  if (minutes >= rise && minutes < set) {
    const along = (minutes - rise) / (set - rise), height = Math.sin(Math.PI * along);
    // Warmest in the last two hours before the sun goes down.
    const warm = smooth(1 - (set - minutes) / 150);
    return { height: 0.12 + 0.24 * height, glow: 0.3 + 0.7 * warm, sunHeight: height };
  }
  const since = minutes >= set ? minutes - set : minutes + 1440 - set;
  if (since <= 75) { const fade = 1 - smooth(since / 75); return { height: 0.12 - 0.07 * (1 - fade), glow: 0.14 + 0.86 * fade, sunHeight: 0 }; }
  const untilRise = minutes < rise ? rise - minutes : rise + 1440 - minutes;
  return { height: 0.05, glow: untilRise <= 40 ? 0.14 + 0.2 * (1 - untilRise / 40) : 0.12, sunHeight: 0 };
}

/**
 * What the shell shows for the picked theme at `date`.
 *   shown      the theme id on the root (the picked theme when the switch is off or the theme has no pair)
 *   nightness  0..1 progress from the day twin to the night twin
 *   lamp       Paper only: blend toward the lamplight palette instead of swapping themes
 *   day/night  the two twins (ids), for blending
 *   blending   true while the shell must paint blended surfaces
 */
export function followedTheme(picked, sun, date) {
  const setting = normalizeSun(sun), minutes = minutesOfDay(date), part = dayPartAt(minutes, setting), daylight = daylightAt(minutes, setting);
  const idle = { shown: picked, nightness: 0, lamp: false, day: picked, night: picked, blending: false, daypart: part, daylight, minutes, setting };
  const pair = THEME_DAYPAIR[picked];
  if (!setting.follow || !pair) return idle;
  const rise = toMinutes(setting.sunrise), set = toMinutes(setting.sunset), half = BLEND_MINUTES / 2;
  let day = picked, night = picked, duskStart = set - half, lamp = false;
  if (pair.lamp) lamp = true;
  else if (pair.day) { day = pair.day; night = picked; }
  else if (pair.night) {
    if (pair.option === "intoNight") { if (!setting.intoNight) return idle; duskStart = set + 60; }
    night = pair.night;
  }
  let nightness;
  if (minutes < rise - half) nightness = 1;
  else if (minutes < rise + half) nightness = 1 - smooth((minutes - (rise - half)) / BLEND_MINUTES);
  else if (minutes < duskStart) nightness = 0;
  else if (minutes < duskStart + BLEND_MINUTES) nightness = smooth((minutes - duskStart) / BLEND_MINUTES);
  else nightness = 1;
  const shown = lamp ? picked : nightness < 0.5 ? day : night;
  return { shown, nightness, lamp, day, night, blending: lamp ? nightness > 0 : nightness > 0 && nightness < 1, daypart: part, daylight, minutes, setting };
}

// ---- blended surfaces -------------------------------------------------------------------------------------------

export const SURFACES = ["bg", "sidebar", "panel", "raised", "raised2"];
export const INKS = ["text", "text2", "muted", "faint", "accentText", "green", "red", "gold", "running"];
const VAR = { bg: "--nx-bg", sidebar: "--nx-sidebar", panel: "--nx-panel", raised: "--nx-raised", raised2: "--nx-raised-2",
  text: "--nx-text", text2: "--nx-text-2", muted: "--nx-muted", faint: "--nx-faint", accentText: "--nx-accent-text", green: "--nx-green", red: "--nx-red", gold: "--nx-gold", running: "--nx-state-running-text" };
export const PALETTE_VARS = VAR;
/** AA for body text, with a hair of room (the meeting colour allows 4.58 with pure white or black). */
export const BLEND_TARGET = 4.51;
const MEETING_LUMINANCE = 0.179;

export const mixHex = (from, to, amount) => {
  const a = hexToRgb(from), b = hexToRgb(to);
  return rgbToHex(a.map((value, index) => value + (b[index] - value) * amount));
};
const luminanceOf = hex => { const [r, g, b] = hexToRgb(hex).map(c => { const v = c / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };

/** The colour both themes' surfaces meet at: their backgrounds' hues, at the luminance where white and black text both read. */
export function meetingColor(a, b) {
  const base = mixHex(a.bg, b.bg, 0.5);
  let low = 0, high = 1;
  const toward = luminanceOf(base) > MEETING_LUMINANCE ? "#000000" : "#ffffff";
  for (let step = 0; step < 24; step += 1) {
    const mid = (low + high) / 2;
    const reached = luminanceOf(mixHex(base, toward, mid));
    if ((toward === "#000000") === (reached > MEETING_LUMINANCE)) low = mid; else high = mid;
  }
  return mixHex(base, toward, (low + high) / 2);
}

/** `ink`, pushed toward white or black only as far as it takes to read at BLEND_TARGET on every surface. */
export function inkOn(ink, surfaces) {
  const reads = value => surfaces.every(surface => contrast(value, surface) >= BLEND_TARGET);
  if (reads(ink)) return ink;
  const mean = surfaces.reduce((sum, surface) => sum + luminanceOf(surface), 0) / surfaces.length;
  const toward = mean > MEETING_LUMINANCE ? "#000000" : "#ffffff";
  let low = 0, high = 1;
  for (let step = 0; step < 14; step += 1) { const mid = (low + high) / 2; if (reads(mixHex(ink, toward, mid))) high = mid; else low = mid; }
  return mixHex(ink, toward, high);
}

const clampAmount = value => Math.min(1, Math.max(0, value));

/** Both inks and surfaces of two palettes mixed (Paper to its lamplight): every step reads, which the theme test samples. */
export function mixPalettes(from, to, amount) {
  return Object.fromEntries(Object.keys(VAR).map(name => [name, to[name] ? mixHex(from[name], to[name], clampAmount(amount)) : from[name]]));
}

/**
 * The inline custom properties for a followed theme (empty when nothing is blending).
 * `palettes(id)` gives { bg, sidebar, ..., text, ... } hex values for a theme id; `lampPalette` is the registry's lamp.
 */
export function blendVars(state, palettes, lampPalette) {
  if (!state.blending) return {};
  let palette, extra = {};
  if (state.lamp) palette = mixPalettes(palettes(state.shown), lampPalette, state.nightness);
  else {
    const day = palettes(state.day), night = palettes(state.night), own = state.shown === state.day ? day : night, other = own === day ? night : day;
    const direct = [day, night].every(side => INKS.every(ink => !side[ink] || SURFACES.every(name => contrast(side[ink], (side === day ? night : day)[name]) >= BLEND_TARGET)));
    if (direct) palette = Object.fromEntries(SURFACES.map(name => [name, mixHex(day[name], night[name], state.nightness)]));
    else {
      // Zero at the far ends, one at the midpoint where both sides' surfaces are the meeting colour.
      const reach = clampAmount(state.shown === state.day ? state.nightness * 2 : (1 - state.nightness) * 2);
      const meet = meetingColor(day, night);
      const surfaces = Object.fromEntries(SURFACES.map(name => [name, mixHex(own[name], meet, reach)]));
      palette = { ...surfaces, ...Object.fromEntries(INKS.filter(ink => own[ink]).map(ink => [ink, inkOn(own[ink], Object.values(surfaces))])) };
      // Forest's layered undergrowth and moss would show through as a dark foot under grey surfaces: flat while the surfaces meet.
      extra = { "--nx-undergrowth": surfaces.sidebar, "--nx-moss": surfaces.sidebar };
    }
  }
  return { ...Object.fromEntries(Object.entries(palette).filter(([name]) => VAR[name]).map(([name, value]) => [VAR[name], value])), ...extra };
}

/** Paper's lamplight palette from the registry (the tests check it reads on its own surfaces). */
export const lampPaletteOf = id => THEME_REGISTRY.find(theme => theme.id === id)?.lamp || null;
