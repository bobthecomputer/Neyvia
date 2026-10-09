import { useRef, useSyncExternalStore } from "react";

import { getOs, useOs } from "./nxOsStore.js";
import { fadeTheme } from "./nxMorph.js";
import { PALETTE_VARS, blendVars, followedTheme, lampPaletteOf, normalizeSun } from "./nxSunModel.js";

// The time-of-day source of the shell (plan 29 THEMES2), as hooks. One shared 20-second clock feeds
//   data-nx-daypart  dawn | day | dusk | night       on the shell root, always (themes read it)
//   --nx-sun-phase   0 (dark) .. 1 (full day)         on the shell root, always
//   data-nx-theme    the theme shown: the picked one, or its day/night twin when Settings > Look > Follow the sun is on
//   inline surfaces  the blended surface colours during a 40-minute crossfade (nxSunModel.blendVars)
// A shown-theme change that comes from the clock (not from a person picking a theme) is one 320 ms cross-fade of the
// page, the same fadeTheme every theme change uses. Components that style by theme read useShownTheme, never state.theme.

export const SUN_TICK_MS = 20000;
const clock = { now: Date.now(), listeners: new Set(), timer: 0 };

const shownFor = now => { const os = getOs(); return followedTheme(os.theme, os.look?.sun, new Date(now)).shown; };
function refresh() {
  const now = Date.now();
  const swap = shownFor(now) !== shownFor(clock.now);
  const commit = () => { clock.now = now; for (const listener of [...clock.listeners]) listener(); };
  if (swap) fadeTheme(commit); else commit();
}
const visible = () => { if (document.visibilityState === "visible") refresh(); };
function subscribe(listener) {
  clock.listeners.add(listener);
  if (!clock.timer) {
    clock.now = Date.now();
    clock.timer = setInterval(refresh, SUN_TICK_MS);
    document.addEventListener("visibilitychange", visible);
  }
  return () => {
    clock.listeners.delete(listener);
    if (!clock.listeners.size) { clearInterval(clock.timer); clock.timer = 0; document.removeEventListener("visibilitychange", visible); }
  };
}

// Theme palettes are read from the live CSS once (a hidden .nx element per theme), so the blend always uses the real tokens.
const palettes = new Map();
const REQUIRED = ["bg", "sidebar", "panel", "raised", "raised2", "text", "text2", "muted", "faint", "accentText", "green", "red", "gold"];
function paletteOf(id) {
  if (palettes.has(id)) return palettes.get(id);
  const probe = document.createElement("div");
  probe.className = "nx"; probe.dataset.nxTheme = id; probe.hidden = true;
  document.body.appendChild(probe);
  const style = getComputedStyle(probe), palette = {};
  for (const [name, variable] of Object.entries(PALETTE_VARS)) {
    const value = style.getPropertyValue(variable).trim();
    if (/^#[0-9a-f]{6}$/i.test(value)) palette[name] = value.toLowerCase();
  }
  probe.remove();
  if (REQUIRED.every(name => palette[name])) palettes.set(id, palette);
  return palette;
}

function varsFor(state) {
  if (!state.blending) return {};
  try {
    const have = id => REQUIRED.every(name => paletteOf(id)[name]);
    if (state.lamp) { const lamp = lampPaletteOf(state.shown); return lamp && have(state.shown) ? blendVars(state, paletteOf, lamp) : {}; }
    return have(state.day) && have(state.night) ? blendVars(state, paletteOf, null) : {};
  } catch { return {}; }
}

/**
 * The sun's view of the shell: { shown, daypart, daylight, vars, attrs, style } for the picked theme and the settings.
 * Stable between ticks (the same object while nothing visible changed), so the shell re-renders only when it must.
 */
export function useSunState() {
  const picked = useOs(state => state.theme);
  const sun = useOs(state => state.look?.sun);
  const cache = useRef(null);
  const snapshot = () => {
    const state = followedTheme(picked, sun, new Date(clock.now));
    const key = [picked, state.shown, state.daypart, Math.round(state.nightness * 400), Math.round(state.daylight * 50), state.lamp, state.setting.follow].join("|");
    if (cache.current?.key !== key) {
      const vars = varsFor(state);
      cache.current = { key, value: {
        shown: state.shown, daypart: state.daypart, daylight: state.daylight, nightness: state.nightness, blending: state.blending, following: state.setting.follow,
        vars, attrs: { "data-nx-daypart": state.daypart, "data-nx-follow": state.setting.follow ? (state.blending ? "blending" : "on") : undefined },
        style: { "--nx-sun-phase": String(Math.round(state.daylight * 1000) / 1000), ...vars },
      } };
    }
    return cache.current.value;
  };
  return useSyncExternalStore(subscribe, snapshot);
}

/** The theme on screen: the picked theme, or its day/night twin while Follow the sun is on. */
export const useShownTheme = () => useSunState().shown;

/** The sun settings, complete and valid. */
export const useSunSetting = () => normalizeSun(useOs(state => state.look?.sun));
