import { useEffect, useState } from "react";

import { callNx } from "./nxApi.js";
import { THEME_REGISTRY } from "./nxThemeRegistry.js";
import { THEME_TO_SETTINGS, getLookVersions, getOs, holdSettingsLook, os, subscribeOs, useOs } from "./nxOsStore.js";

// Canonical Settings (plan 15 T11). The PC service owns them: one revisioned
// record for density, theme, initiative, cleanup rules, Night Shift resources
// and local-only, read and written with settings_<get|update|setup|network_check>_command
// (the same call on the desktop and in a browser). Every write carries the
// revision it was based on; a 409 means someone else saved first, so the page
// re-reads and, for look changes, tries once more. Theme and density chosen
// anywhere in the shell (launcher, Canopy, voice) are pushed here too, so a
// reload or another device shows the same look.

export const INITIATIVE = [
  { value: "suggest", label: "Suggest", hint: "Agents propose the next step and wait for you." },
  { value: "act-and-tell", label: "Act and tell", hint: "Agents do reversible next steps and tell you what they did." },
  { value: "silent", label: "Silent", hint: "Agents do reversible housekeeping without telling you. Anything that can't be undone still asks." },
];

const BACKEND_THEME = Object.fromEntries(THEME_REGISTRY.map(theme => [theme.setting, theme.label]));
export const backendThemeLabel = theme => BACKEND_THEME[theme] || theme;

/** Plain words for a refused save. `kind` lets the page show the right next step. */
export function explainSettingsError(error) {
  const message = String(error?.message || "");
  if (/child jobs/i.test(message)) return { kind: "children", message: "Some programs Neyvia started are still running. They could reach the internet, so local-only waits until they stop." };
  if (/Settings changed/i.test(message) || error?.status === 409) return { kind: "conflict", message: "Settings were changed somewhere else. The page now shows the latest; try again." };
  if (error?.code === "network") return { kind: "offline", message: "Couldn't reach the PC service. Check Neyvia is running, then try again." };
  if (error?.status === 401 || error?.code === "login_required") return { kind: "login", message: "Sign in again to change settings." };
  if (error?.status === 403) return { kind: "owner", message: "Only the owner of this PC can change settings." };
  return { kind: "error", message: message || "Settings couldn't be saved. Try again." };
}

async function deliverEvents(events) {
  if (!Array.isArray(events) || !events.length) return;
  const { deliver } = await import("./nxBus.js");
  for (const event of events) deliver(event, { direct: true });
}

/** Read the canonical record and apply it (theme, density, cleanup, local-only). */
export async function refreshSettings() {
  const data = await callNx("settings_get_command", {});
  // A look change still on its way to the PC keeps showing; the save brings the record up to date.
  os.setPrefs(data, { look: !inflight && !lookPending });
  return data;
}

let chain = Promise.resolve();
let inflight = 0;
let lookPending = false;

/**
 * Save a Settings patch against the current revision. Look-only patches
 * (theme, density, look) retry once after a conflict; anything else returns the
 * conflict so the person sees the latest values before deciding again.
 */
export function saveSettings(patch) {
  const submittedVersions = getLookVersions();
  const requestId = globalThis.crypto?.randomUUID?.() || `settings-${Date.now()}-${Math.random()}`;
  const releaseLook = holdSettingsLook(requestId);
  inflight += 1;
  const run = chain.then(async () => {
    if (!getOs().prefs) await refreshSettings();
    const attempt = () => callNx("settings_update_command", { patch, expectedRevision: getOs().prefs?.revision ?? 0, requestId });
    let data;
    try {
      data = await attempt();
    } catch (error) {
      const lookOnly = Object.keys(patch).every(key => key === "theme" || key === "density" || key === "look");
      if (explainSettingsError(error).kind !== "conflict") throw error;
      await refreshSettings();
      if (!lookOnly) throw error;
      data = await attempt();
    }
    // A scene or look chosen while this request was pending is newer than
    // its response. Retain those fields while advancing the canonical record;
    // the existing drift subscriber saves the newer choice at that revision.
    const current = getOs();
    const currentVersions = getLookVersions();
    // Version comparisons retain an away-and-back scene choice (ABA) too.
    const newerTheme = currentVersions.theme !== submittedVersions.theme ? current.theme : null;
    const newerDensity = currentVersions.density !== submittedVersions.density ? current.density : null;
    await deliverEvents(data?.events);
    os.setPrefs(data);
    if (newerTheme) os.setTheme(newerTheme);
    if (newerDensity) os.setDensity(newerDensity);
    if (drift()) scheduleSync();
    return data;
  }).finally(() => { inflight -= 1; releaseLook(); });
  chain = run.catch(() => {});
  return run;
}

/** Re-enter setup: the service emits setup.open, which opens setup on this screen. Nothing installed is reset. */
export async function reenterSetup() {
  const data = await callNx("settings_setup_command", {});
  await deliverEvents(data?.events);
  // A service without the bus event still opens setup here.
  if (!getOs().onboarding) os.openOnboarding("welcome");
  return data;
}

/** Real refused attempts (TCP, UDP, DNS, HTTP, HTTPS, child programs) while local-only is on. */
export function checkLocalOnly() {
  return callNx("settings_network_check_command", {});
}

// ---- keeping the shell's look and the canonical record together ----------

let started = false;
let syncTimer = 0;
let warned = false;

function drift() {
  const state = getOs();
  const saved = state.prefs?.settings;
  if (!saved) return null;
  const patch = {};
  if (THEME_TO_SETTINGS[state.theme] && THEME_TO_SETTINGS[state.theme] !== saved.theme) patch.theme = THEME_TO_SETTINGS[state.theme];
  if (state.density !== saved.density) patch.density = state.density;
  return Object.keys(patch).length ? patch : null;
}

function scheduleSync() {
  clearTimeout(syncTimer);
  lookPending = true;
  syncTimer = setTimeout(() => {
    if (inflight) { scheduleSync(); return; }
    lookPending = false;
    const patch = drift();
    if (!patch) return;
    saveSettings(patch).then(() => { warned = false; }).catch(error => {
      if (warned) return;
      warned = true;
      os.notify({ level: "warning", message: `Look not saved on the PC: ${explainSettingsError(error).message}` });
    });
  }, 500);
}

const hasLocal = key => { try { return localStorage.getItem(`nx.os.${key}`) != null; } catch { return false; } };

/**
 * First read after sign-in. A PC that never saved Settings (revision 0) takes
 * the look this browser already had, so nobody's chosen theme jumps back to
 * the defaults; afterwards the PC's record wins.
 */
export async function startSettings() {
  const local = { theme: getOs().theme, density: getOs().density, look: getOs().look };
  const data = await callNx("settings_get_command", {});
  if (!started) {
    started = true;
    subscribeOs(() => { if (drift()) scheduleSync(); });
  }
  if (data?.revision === 0) {
    const patch = {};
    if (hasLocal("theme") && THEME_TO_SETTINGS[local.theme] !== data.settings?.theme) patch.theme = THEME_TO_SETTINGS[local.theme];
    if (hasLocal("density") && local.density !== data.settings?.density) patch.density = local.density;
    if (hasLocal("look") && JSON.stringify(local.look) !== JSON.stringify(data.settings?.look)) patch.look = local.look;
    if (Object.keys(patch).length) {
      os.setPrefs({ ...data, settings: { ...data.settings, ...patch } });
      await saveSettings(patch).catch(() => os.setPrefs(data));
      return;
    }
  }
  os.setPrefs(data);
}

// ---- local-only in the interface ------------------------------------------

const LOOPBACK = /^(localhost|127(?:\.\d{1,3}){3}|\[?::1\]?)$/i;

/** True when local-only is on and `url` would leave this PC. */
export function blockedByLocalOnly(url, localOnly) {
  if (!localOnly) return false;
  try {
    const parsed = new URL(String(url), globalThis.location?.href);
    if (!/^https?:$|^wss?:$/.test(parsed.protocol)) return false;
    return !LOOPBACK.test(parsed.hostname) && parsed.host !== globalThis.location?.host;
  } catch { return false; }
}

/** Is local-only on (as the PC service reported it)? */
export function useLocalOnly() {
  return useOs(state => Boolean(state.prefs?.network?.localOnly ?? state.prefs?.settings?.localOnly));
}

/** Poll the canonical record while a Settings view is open (network status changes as programs stop). */
export function useSettingsPoll(active, ms = 6000) {
  const [error, setError] = useState(null);
  useEffect(() => {
    if (!active) return undefined;
    let alive = true;
    const tick = () => {
      if (document.hidden) return;
      refreshSettings().then(() => { if (alive) setError(null); }).catch(failure => { if (alive) setError(explainSettingsError(failure)); });
    };
    tick();
    const timer = setInterval(tick, ms);
    return () => { alive = false; clearInterval(timer); };
  }, [active, ms]);
  return error;
}
