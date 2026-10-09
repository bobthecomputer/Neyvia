import { checkPresentationAction } from "../neyviaPresentationContracts.js";
import { useSyncExternalStore } from "react";
import { checkInitial, checkOverrides, checkUiAction } from "./nxProofsEShellContracts.js";
import { basename } from "./nxSidebarModel.js";
import { BUILTIN_SCENES, applyScene, captureScene, normalizeLayout, sceneId } from "./nxLayoutModel.js";
import { normalizeTransparency, TRANSPARENCY_LEVELS } from "./nxTransparencyModel.js";
import { paneRequest } from "./nxPaneObserve.js";
import { normalizeLook } from "./nxLookModel.js";
import { fadeTheme } from "./nxMorph.js";
import { DEFAULT_THEME, THEMES, THEME_FROM_SETTINGS } from "./nxThemeRegistry.js";
import { closeWindow, findWindow, mainDesc, moveBubble as moveWindowBubble, normalizePrefs, openWindow, orderWithPanel, peekBubble, placeWindow, rememberPlacement, restoreWindow, syncStage, windowKey } from "./nxPlacementModel.js";

// Shell state around the chats: density, what fills the stage (an app or a
// pane, with the chat docked beside it), the launcher, notices, Night Shift
// and indicator readings. Bus actions (11-tonight contract) are applied by
// the pure `reduceUiAction`, so the mock and the real backend drive the same
// code. Chat data itself stays in nxStore.

export const DENSITIES = ["calm", "workshop", "grove"];
// The theme list lives in nxThemeRegistry.js (a leaf module, so the Look model, app skins and the
// sign-in page can read it without importing this store); it is re-exported here as the store's API.
// Canonical Settings name themes forest/morning/sunset/night-green/terminal/paper/ember; the shell uses the ids.
export { THEMES, THEME_LABELS, THEME_FROM_SETTINGS, THEME_TO_SETTINGS, THEME_BLURBS, THEME_SCHEME, DEFAULT_THEME } from "./nxThemeRegistry.js";
export const PANE_KINDS = ["diff", "file", "artifact", "terminal", "browser", "mission", "replay", "builder", "accounts", "runtime", "settings", "preview", "outputs", "perception", "agentview", "sessions", "usage", "parallel", "agents"];
const NS_STATUSES = ["waiting", "running", "done", "blocked"];
const LEVELS = ["info", "success", "warning", "error"];

const ownSettingsRequests = new Set();

/** Retain bounded correlation after HTTP completion: streamed echoes may arrive later. */
export function holdSettingsLook(requestId) {
  ownSettingsRequests.add(requestId);
  if (ownSettingsRequests.size > 256) ownSettingsRequests.delete(ownSettingsRequests.values().next().value);
  return () => {};
}

const read = (key, fallback) => {
  try { const raw = localStorage.getItem(`nx.os.${key}`); return raw == null ? fallback : JSON.parse(raw); } catch { return fallback; }
};
const write = (key, value) => {
  try { if (value == null) localStorage.removeItem(`nx.os.${key}`); else localStorage.setItem(`nx.os.${key}`, JSON.stringify(value)); return true; } catch { return false; /* best effort */ }
};

export function initialOsState(saved = {}) {
  return checkInitial(saved, createOsState(saved));
}
function createOsState(saved) {
  return {
    density: DENSITIES.includes(saved.density) ? saved.density : "workshop",
    theme: THEMES.includes(saved.theme) ? saved.theme : DEFAULT_THEME,
    rain: saved.rain === true, // Matrix rain behind the chat in the Terminal theme (NxRain); off until chosen
    ambient: saved.ambient !== false, // the ambient light layer behind the main surface (Settings > Look)
    look: normalizeLook(saved.look), // typeface pair, text size and background (Settings > Look; canonical in Settings)
    transparency: normalizeTransparency(saved.transparency),
    layout: normalizeLayout(saved.layout), // region order, widths, dock side, home widgets (nxLayoutModel)
    arranging: false, // Arrange mode: regions and widgets show their handles
    scenes: saved.scenes && typeof saved.scenes === "object" ? saved.scenes : {}, // id -> saved scene (nxLayoutModel)
    bubbles: normalizeBubbles(saved.bubbles), // floating chats: [{ id, x, y }] with x/y as 0..1 of the window
    bubbleOpen: null, // the bubble showing its mini window
    stage: null, // { type: "app", app, suite, target? } | { type: "pane", kind, target }: the window beside the chat
    windows: [], // every open app or pane and where it is placed: main, side, full or bubble (nxPlacementModel)
    placements: normalizePrefs(saved.placements), // app or pane kind -> main | side, where it opens next time
    launcher: false,
    dashboard: false, // the agents dashboard (strip and sidebar open it)
    help: false, // the "Keyboard and voice" sheet
    launcherQuery: "", // text a voice "search for …" put in the launcher
    motion: ["system", "reduce", "full"].includes(saved.motion) ? saved.motion : "system", // reduced motion: follow the OS, or force it
    bus: { state: "off", source: "none" },
    projects: saved.projects || {}, // path -> { name, path }
    overrides: saved.overrides || {}, // session id -> { title?, pinned?, archived?, project? (path|null) }
    created: {}, // session id -> minimal row until the chat list reports it
    nightshift: {}, // task id -> { id, status, evidence?, reason?, title?, at }
    nightshiftMeta: { rev: 0, policy: null, night: null }, // budget policy and night period from Night Shift events (T10)
    autopilot: {}, // run id -> the latest Autopilot run the backend sent (autopilot.state); polling stays the truth
    indicators: {}, // key -> reading (gpu, usage)
    notices: [],
    inbox: [], // app commands from the bus, drained by the app that owns them
    appSignals: {}, // app -> { seq, payload }: a model changed that app's files (Notes, Files); the app refreshes
    cleanup: saved.cleanup || null,
    prefs: null, // canonical Settings from the PC service (T11): { revision, settings, network, setup }; null until read
    lastEventId: "",
  };
}

let inboxSeq = 0;
// Which suite an app lives in, for app.open without one (the launcher's suites, 07 §R1).
const SUITE_OF = { pdf: "documents", notes: "documents", files: "documents", "doc-editor": "documents", latex: "documents", spreadsheets: "documents",
  unity: "game-dev", roblox: "game-dev", godot: "game-dev", "asset-checks": "game-dev", playtest: "game-dev",
  "image-studio": "studio", "mobile-studio": "studio", "3d-studio": "studio", video: "studio", visualization: "studio", quiz: "studio",
  decompile: "lab", "hill-climb": "lab", modding: "lab", security: "lab" };
const suiteOf = app => SUITE_OF[app] || "";
let shellSeq = 0;
const shellSignal = (state, action, payload) => ({ ...state, appSignals: { ...state.appSignals, shell: { seq: ++shellSeq, action, payload } } });
function queue(state, app, action, payload) {
  // Only pdf.open may start the app; other commands need it on the stage, or the ack says so.
  const open = (state.stage?.type === "app" && state.stage.app === app) || (state.windows || []).some(win => win.desc?.type === "app" && win.desc.app === app);
  if (!action.endsWith(".open") && !open) throw new Error(`The ${app} app is not open; send ${app}.open first`);
  return { ...state, inbox: [...state.inbox, { seq: ++inboxSeq, app, action, payload }] };
}

const toast = (state, notice) => ({ ...state, notices: [...state.notices.slice(-4), { id: notice.id || `n${Date.now()}${Math.random().toString(36).slice(2, 6)}`, at: Date.now(), ...notice }] });

function patchSession(state, id, patch) {
  if (!id) throw new Error("payload.id is required");
  return { ...state, overrides: { ...state.overrides, [id]: { ...state.overrides[id], ...patch } } };
}

const clamp01 = value => Math.min(1, Math.max(0, Number(value) || 0));
const MAX_BUBBLES = 6;

function normalizeBubbles(saved) {
  if (!Array.isArray(saved)) return [];
  const seen = new Set();
  return saved.filter(bubble => bubble?.id && !seen.has(bubble.id) && seen.add(bubble.id)).slice(0, MAX_BUBBLES)
    .map(bubble => ({ id: String(bubble.id), x: clamp01(bubble.x ?? 1), y: clamp01(bubble.y ?? 0.3) }));
}

// New bubbles line up down the right edge, like a phone's floating chats.
function float(state, id) {
  if (state.bubbles.some(bubble => bubble.id === id)) return { ...state, bubbleOpen: id };
  const bubbles = [...state.bubbles, { id, x: 1, y: clamp01(0.18 + state.bubbles.length * 0.1) }].slice(-MAX_BUBBLES);
  return { ...state, bubbles, bubbleOpen: id };
}

function unfloat(state, id) {
  return { ...state, bubbles: state.bubbles.filter(bubble => bubble.id !== id), bubbleOpen: state.bubbleOpen === id ? null : state.bubbleOpen };
}

/** Apply one bus action. Throws on a malformed payload so the ack can report it. */
export function reduceUiAction(state, action, payload = {}) {
  const next = checkUiAction(state, action, payload, reduceShellAction(state, action, payload));
  return action === "view.transparency" ? checkPresentationAction("transparency.transition", [state, action, payload], next) : next;
}
function reduceShellAction(state, action, payload) {
  switch (action) {
    case "image.open":
    case "image.edited": {
      if (!payload.id || !payload.url?.startsWith("/api/ui/image-file?id=")) throw new Error("Image event needs an owned asset");
      const desc = { type: "app", app: "image-studio", suite: "studio", target: payload.id };
      return { ...state, imageAsset: payload, windows: openWindow(state.windows, desc, { prefs: state.placements }), launcher: false };
    }
    case "pane.show": {
      if (!PANE_KINDS.includes(payload.kind)) throw new Error(`Unknown pane kind: ${payload.kind}`);
      const desc = { type: "pane", kind: payload.kind, target: String(payload.target ?? "") };
      if (!payload.placement) return { ...state, stage: desc };
      if (!["main", "side", "full", "bubble"].includes(payload.placement)) throw new Error("Unknown pane placement");
      if (payload.side && (payload.placement !== "side" || !["left", "right"].includes(payload.side))) throw new Error("side only applies to a side panel");
      const opened = openWindow(state.windows, desc, { prefs: state.placements, placement: findWindow(state.windows, windowKey(desc)) ? null : "bubble" });
      const windows = placeWindow(opened, windowKey(desc), payload.placement);
      const layout = payload.side ? normalizeLayout({ ...state.layout, order: orderWithPanel(state.layout.order, payload.side) }) : state.layout;
      return { ...state, windows, layout };
    }
    case "session.created": {
      if (!payload.id) throw new Error("payload.id is required");
      const row = { id: payload.id, app: payload.app || "neyvia", cwd: payload.folder || null, title: payload.title || "New chat", status: "working", category: payload.app === "neyvia" ? "native" : "connected", updated_at: new Date().toISOString(), created_at: new Date().toISOString() };
      return toast({ ...state, created: { ...state.created, [payload.id]: row } }, { level: "info", message: `New chat started${payload.folder ? ` in ${basename(payload.folder)}` : ""}`, open: payload.id });
    }
    case "session.moved": {
      // sidebar.undo puts back "no override at all" (the chat goes where its folder says), not "No folder".
      if (payload.clearOverride === true) {
        if (!payload.id) throw new Error("payload.id is required");
        const { project: _dropped, ...rest } = state.overrides[payload.id] || {};
        return { ...state, overrides: { ...state.overrides, [payload.id]: rest } };
      }
      const project = payload.project == null ? null : String(payload.project);
      return patchSession(state, payload.id, { project });
    }
    case "session.renamed":
      if (!payload.title) throw new Error("payload.title is required");
      return patchSession(state, payload.id, { title: String(payload.title) });
    case "session.pinned":
      return patchSession(state, payload.id, { pinned: payload.pinned !== false });
    case "session.archived":
      return patchSession(state, payload.id, { archived: payload.archived !== false });
    case "sidebar.policy":
      return { ...state, cleanup: payload.policy };
    case "project.created": {
      if (!payload.name) throw new Error("payload.name is required");
      const path = String(payload.path || payload.name);
      return toast({ ...state, projects: { ...state.projects, [path]: { name: String(payload.name), path } } }, { level: "success", message: `Project ${payload.name} created` });
    }
    case "view.layout":
      if (!DENSITIES.includes(payload.level)) throw new Error(`Unknown layout level: ${payload.level}`);
      return { ...state, density: payload.level };
    // Switch to a scene (built-in or saved), or save what's on screen under a name.
    case "view.scene": {
      if (payload.save) {
        const scene = captureScene(payload.save, state);
        return toast({ ...state, scenes: { ...state.scenes, [sceneId(scene.label)]: scene } }, { level: "success", message: `Scene ${scene.label} saved` });
      }
      const id = sceneId(payload.name);
      return { ...state, ...applyScene(state, BUILTIN_SCENES[id] || state.scenes[id]) };
    }
    // Float a chat as a bubble over everything (or bring it back with floating: false).
    case "view.float": {
      if (!payload.id) throw new Error("payload.id is required");
      return payload.floating === false ? unfloat(state, String(payload.id)) : float(state, String(payload.id));
    }
    case "view.place": {
      const win = findWindow(state.windows, payload.id);
      if (!win) throw new Error("Unknown open window; read view.state again");
      if (payload.side && (payload.placement !== "side" || !["left", "right"].includes(payload.side))) throw new Error("side only applies to a side panel");
      const windows = payload.placement === "close" ? closeWindow(state.windows, win.id) : placeWindow(state.windows, win.id, payload.placement);
      const layout = payload.placement === "side" && payload.side ? normalizeLayout({ ...state.layout, order: orderWithPanel(state.layout.order, payload.side) }) : state.layout;
      return { ...state, windows, layout, placements: rememberPlacement(state.placements, win.desc, payload.placement) };
    }
    case "view.theme":
      if (!THEMES.includes(payload.theme)) throw new Error(`Unknown theme: ${payload.theme}; themes are ${THEMES.join(", ")}`);
      return { ...state, theme: payload.theme };
    case "view.transparency":
      if (!TRANSPARENCY_LEVELS.includes(payload.level)) throw new Error(`Unknown transparency level: ${payload.level}`);
      return { ...state, transparency: payload.level };
    // The ambient light layer behind the main surface (Settings > Look).
    case "view.ambient":
      if (typeof payload.on !== "boolean") throw new Error("payload.on (true or false) is required");
      return { ...state, ambient: payload.on };
    // Rearrange the interface: any of order, widths, canopy, dock, widgets. Left-out fields keep their value.
    case "view.arrange":
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new Error("view.arrange needs an object payload");
      return { ...state, layout: normalizeLayout({ ...state.layout, ...payload }) };
    case "notify":
      if (!payload.message) throw new Error("payload.message is required");
      return toast(state, { level: LEVELS.includes(payload.level) ? payload.level : "info", message: String(payload.message), approvalId: payload.approvalId || null });
    // Computer use (T16): an agent started driving an app, asks before an action, or was paused.
    case "cua.session":
      return toast(state, { level: "info", message: `${payload.title || payload.owner?.title || "An agent"} is using ${payload.app || "an app"}`,
        action: { label: "Watch", run: () => os.showPane("agentview", String(payload.sessionId || "")) } });
    case "cua.approval":
      if (!payload.sessionId) throw new Error("payload.sessionId is required");
      return toast(state, { level: "warning", message: payload.summary ? `An agent asks: ${payload.summary}` : "An agent is waiting for your yes",
        action: { label: "Review", run: () => os.showPane("preview", String(payload.sessionId)) } });
    case "cua.paused":
      return toast(state, { level: "info", message: payload.reason === "real_input" ? "Agent paused: you used the app yourself" : "Agent paused: you have control",
        action: { label: "Open", run: () => os.showPane("preview", String(payload.sessionId || "")) } });
    // Outputs (plan 15 T8): a file, change, image, report or receipt was published. The panel re-reads the registry.
    case "artifact.published": {
      const artifact = payload.artifact || {};
      if (!artifact.id) throw new Error("payload.artifact.id is required");
      const next = { ...state, appSignals: { ...state.appSignals, outputs: { seq: (state.appSignals.outputs?.seq || 0) + 1, payload } } };
      if (state.stage?.type === "pane" && state.stage.kind === "outputs") return next;
      return toast(next, { level: "info", message: `New output: ${artifact.title || artifact.name || "a file"}`,
        action: { label: "Show", run: () => os.showPane("outputs", String(artifact.id)) } });
    }
    case "agents.overview.changed":
    case "agents.message.sent":
    case "parallel.state":
      return { ...state, agentsOverviewRevision: (state.agentsOverviewRevision || 0) + 1 };
    case "nightshift.task.updated": {
      if (!payload.id || !NS_STATUSES.includes(payload.status)) throw new Error("nightshift task needs id and a known status");
      const task = { ...state.nightshift[payload.id], ...payload, at: Date.now() };
      return { ...state, nightshift: { ...state.nightshift, [payload.id]: task } };
    }
    // Night Shift budget changes and a new night (plan 15 T10): the board re-reads its summary.
    case "nightshift.resources.updated":
      return { ...state, nightshiftMeta: { ...state.nightshiftMeta, rev: state.nightshiftMeta.rev + 1, policy: payload } };
    case "nightshift.night.started":
      if (!payload.nightId) throw new Error("nightshift.night.started needs nightId");
      return { ...state, nightshiftMeta: { ...state.nightshiftMeta, rev: state.nightshiftMeta.rev + 1, night: payload } };
    // The PDF app (Documents suite). Proposed to the bot side; queued for the app to run.
    case "pdf.open": {
      const source = String(payload.source || payload.path || payload.url || "");
      if (!source) throw new Error("pdf.open needs source, path or url");
      return queue({ ...state, stage: { type: "app", app: "pdf", suite: "documents", target: source } }, "pdf", action, { ...payload, source });
    }
    case "pdf.goto":
      if (!(Number.isInteger(payload.page) && payload.page >= 1)) throw new Error("pdf.goto needs a page number from 1");
      return queue(state, "pdf", action, payload);
    case "pdf.zoom":
      if (payload.scale !== "fit-width" && !(Number(payload.scale) >= 0.25 && Number(payload.scale) <= 5)) throw new Error("pdf.zoom scale is 0.25–5 or \"fit-width\"");
      return queue(state, "pdf", action, payload);
    case "pdf.search":
      if (typeof payload.query !== "string") throw new Error("pdf.search needs a query (empty clears)");
      return queue(state, "pdf", action, payload);
    case "pdf.highlight":
      if (!(Number.isInteger(payload.page) && payload.page >= 1) || !(payload.text || Array.isArray(payload.rects))) throw new Error("pdf.highlight needs page and text or rects");
      return queue(state, "pdf", action, payload);
    // Notes and Files (Documents suite): a model opened a note, or changed notes or files.
    case "notes.open": {
      if (!payload.path) throw new Error("notes.open needs a path");
      return { ...state, stage: { type: "app", app: "notes", suite: "documents", target: String(payload.path) } };
    }
    case "notes.changed":
    case "files.changed":
    case "comments.changed": { // comments.changed (plan 29): nxComments refetches the target it names
      const app = action.split(".")[0];
      return { ...state, appSignals: { ...state.appSignals, [app]: { seq: (state.appSignals[app]?.seq || 0) + 1, payload } } };
    }
    // Other PCs (cross-pc): a PC asks to pair, a pairing changed, or a copy between PCs moved on.
    case "devices.pair_request": {
      const next = { ...state, appSignals: { ...state.appSignals, devices: { seq: (state.appSignals.devices?.seq || 0) + 1, payload } } };
      return toast(next, { level: "info", message: `${payload.fromName || "Another PC"} wants to reach this PC's files${payload.code ? ` (code ${payload.code})` : ""}`,
        action: { label: "Review", run: () => os.showPane("accounts", "other-pcs") } });
    }
    case "devices.changed":
    case "devices.transfer": {
      const next = { ...state, appSignals: { ...state.appSignals, devices: { seq: (state.appSignals.devices?.seq || 0) + 1, payload } } };
      // Paul sees his own copies in Files; say so only when a model's copy ends.
      if (action === "devices.transfer" && payload.by === "model" && (payload.status === "done" || payload.status === "failed")) {
        const verb = payload.direction === "send" ? `sent to ${payload.deviceName}` : `taken from ${payload.deviceName}`;
        return toast(next, payload.status === "done"
          ? { level: "success", message: `${payload.name || "A file"} ${verb}` }
          : { level: "error", message: `${payload.name || "A file"} wasn't ${verb}: ${String(payload.error || "").slice(0, 140)}` });
      }
      return next;
    }
    // Mobile Studio (Studio suite): the bot side shows a phone, or a build/install moved on.
    case "mobile.preview":
      return queue({ ...state, stage: { type: "app", app: "mobile-studio", suite: "studio", target: state.stage?.app === "mobile-studio" ? state.stage.target : null } }, "mobile-studio", action, payload);
    case "mobile.job": {
      if (!payload.id) throw new Error("mobile.job needs id");
      const label = `${payload.platform === "ios" ? "iPhone" : "Android"} ${payload.kind || "job"}`;
      const next = queue(state, "mobile-studio", action, payload);
      if (payload.status === "done") return toast(next, { level: "success", message: `${label} finished` });
      if (payload.status === "failed") return toast(next, { level: "error", message: `${label} failed: ${String(payload.error || "").slice(0, 160)}` });
      return next;
    }
    // Voice control (plan 15 T3): spoken commands reach the screen through the same bus.
    case "app.open": {
      if (!payload.app) throw new Error("app.open needs app");
      return { ...state, stage: { type: "app", app: String(payload.app), suite: String(payload.suite || suiteOf(payload.app)), target: payload.target ?? null }, launcher: false };
    }
    case "stage.close":
      return { ...state, stage: null };
    case "launcher.open":
      return { ...state, launcher: true, launcherQuery: String(payload.query || ""), dashboard: false };
    case "dashboard.open":
      return { ...state, dashboard: payload.open !== false, launcher: false };
    case "sidebar.toggle": {
      const hidden = typeof payload.hidden === "boolean" ? payload.hidden : !state.layout.sidebarHidden;
      return { ...state, layout: { ...state.layout, sidebarHidden: hidden } };
    }
    case "voice.help":
      return { ...state, help: payload.open !== false, launcher: false };
    // These four need the shell's own state (the open chat, the composer): handed to it as a signal.
    case "session.open":
      if (!payload.id) throw new Error("session.open needs id");
      return shellSignal(state, action, payload);
    case "newchat.open":
      if (payload.app && !["neyvia", "codex", "claude-code", "claude", "opencode"].includes(payload.app)) throw new Error(`Unknown harness: ${payload.app}`);
      return shellSignal(state, action, payload);
    case "composer.send":
    case "dictation.start":
      return shellSignal(state, action, payload);
    // Not in the 11-tonight contract yet: optional readings for the indicators strip.
    case "indicator.updated":
      if (!payload.key) throw new Error("payload.key is required");
      return { ...state, indicators: { ...state.indicators, [payload.key]: { ...payload, at: Date.now() } } };
    // The model's neyvia.onboarding.open: show setup (or only the tour) on this screen.
    // Autopilot (plan 15 T17): every saved change of a run. The chat's Autopilot panel shows it at once.
    case "autopilot.state": {
      const run = payload.run;
      if (!run?.runId) throw new Error("payload.run.runId is required");
      return { ...state, autopilot: { ...state.autopilot, [run.runId]: run } };
    }
    // Canonical Settings were saved (T11): the backend's revision wins over what this browser remembered.
    case "settings.changed": {
      if (!Number.isInteger(payload.revision) || !payload.settings || typeof payload.settings !== "object") throw new Error("settings.changed needs revision and settings");
      const prefs = { ...state.prefs, revision: payload.revision, settings: payload.settings };
      if (!Array.isArray(payload.changedKeys)) return applyPrefs(state, prefs);
      const next = applyPrefs(state, prefs, { look: false });
      // A theme-only model action must not undo a scene's density while its
      // canonical save is still queued. Apply only fields this write changed.
      return { ...next,
        ...(payload.changedKeys.includes("theme") && THEME_FROM_SETTINGS[payload.settings.theme]
          ? { theme: THEME_FROM_SETTINGS[payload.settings.theme] } : {}),
        ...(payload.changedKeys.includes("density") && DENSITIES.includes(payload.settings.density)
          ? { density: payload.settings.density } : {}),
        ...(payload.changedKeys.includes("look") && payload.settings.look
          ? { look: keepSame(state.look, normalizeLook(payload.settings.look)) } : {}) };
    }
    // Settings > Re-enter setup (or neyvia.settings.setup): open setup again; nothing installed is reset.
    case "setup.open":
      return { ...state, onboarding: { step: "welcome", only: "", resume: payload.resume !== false, at: Date.now() }, launcher: false };
    case "onboarding.open":
      return { ...state, onboarding: { step: ["welcome", "unique", "downloads", "connections", "done", "runtimes", "interests", "tour"].includes(payload.step) ? payload.step : "welcome", at: Date.now() } };
    default:
      throw new Error(`Unknown action: ${action}`);
  }
}

// A poll that reads the same look keeps the same object, so nothing re-renders or re-saves.
const keepSame = (current, next) => (JSON.stringify(current) === JSON.stringify(next) ? current : next);

/** Apply canonical Settings ({ revision, settings, network?, setup? }); an older revision never overwrites a newer one. */
export function applyPrefs(state, prefs, { look = true } = {}) {
  if (!prefs || !prefs.settings || typeof prefs.settings !== "object") return state;
  if (state.prefs && Number.isInteger(prefs.revision) && prefs.revision < state.prefs.revision) return state;
  const settings = prefs.settings;
  const theme = THEME_FROM_SETTINGS[settings.theme];
  return {
    ...state,
    prefs: { ...state.prefs, ...prefs },
    theme: look && theme ? theme : state.theme,
    density: look && DENSITIES.includes(settings.density) ? settings.density : state.density,
    look: look && settings.look && typeof settings.look === "object" ? keepSame(state.look, normalizeLook(settings.look)) : state.look,
    cleanup: settings.cleanup && typeof settings.cleanup === "object" ? settings.cleanup : state.cleanup,
  };
}

/** Resolve a session's display fields through the overrides the bus set. */
export function withOverrides(session, overrides, projects) {
  return checkOverrides(session, overrides, projects, resolveOverrides(session, overrides, projects));
}
function resolveOverrides(session, overrides, projects) {
  const patch = overrides[session.id];
  if (!patch) return session;
  const next = { ...session };
  if (patch.title) next.title = patch.title;
  if (patch.pinned !== undefined) next.pinned = patch.pinned;
  if (patch.archived !== undefined) next.archived = patch.archived;
  if (patch.project !== undefined) {
    // A subject folder (sidebar group) has no path; until its name is known it reads "Sorted chats", never its id.
    const subject = String(patch.project || "").startsWith("subject:");
    next.projectOverride = patch.project === null ? null : (projects[patch.project]
      || (subject ? { id: patch.project, name: "Sorted chats", path: null, subject: true } : { name: basename(patch.project) || patch.project, path: patch.project }));
  }
  return next;
}

// ---- the live store ---------------------------------------------------------

// The shell's old `nx.theme` and `nx.sidebarHidden` keys are gone: they are removed once, never read.
try { localStorage.removeItem("nx.theme"); localStorage.removeItem("nx.sidebarHidden"); } catch { /* storage may be unavailable */ }
let state = initialOsState({ placements: read("placements"), motion: read("motion"), density: read("density"), theme: read("theme"), layout: read("layout"), scenes: read("scenes"), bubbles: read("bubbles"), projects: read("projects"), overrides: read("overrides"), cleanup: read("cleanup"), ambient: read("ambient"), rain: read("rain"), transparency: read("transparency"), look: read("look") });
const listeners = new Set();

const lookVersions = { theme: 0, density: 0 };
export const getLookVersions = () => ({ ...lookVersions });

function set(next, { lookIntent = true } = {}) {
  const before = state;
  state = { ...state, ...(typeof next === "function" ? next(state) : next) };
  // Placement (nxPlacementModel): anything that set `stage` directly opens or closes a window;
  // `stage` itself always reads back as the window placed beside the chat.
  if (state.stage !== before.stage && state.windows === before.windows) state = { ...state, windows: syncStage(before.windows, before.stage, state.stage, { prefs: state.placements }) };
  if (state.windows !== before.windows) state = { ...state, stage: mainDesc(state.windows) };
  if (before.placements !== state.placements) write("placements", state.placements);
  if (lookIntent) {
    for (const field of ["theme", "density"]) if (before[field] !== state[field]) lookVersions[field] += 1;
  }
  if (before.density !== state.density) write("density", state.density);
  if (before.layout !== state.layout) write("layout", state.layout);
  if (before.theme !== state.theme) write("theme", state.theme);
  if (before.transparency !== state.transparency) {
    const wrote = write("transparency", state.transparency);
    let persisted;
    try { persisted = localStorage.getItem("nx.os.transparency"); } catch { /* Storage may be unavailable; the in-memory preference still applies. */ }
    if (wrote && persisted !== undefined) checkPresentationAction("transparency.persistence", [state.transparency], { level: state.transparency, key: "nx.os.transparency", value: persisted });
  }
  if (before.rain !== state.rain) write("rain", state.rain ? true : null);
  if (before.ambient !== state.ambient) write("ambient", state.ambient ? null : false);
  if (before.look !== state.look) write("look", state.look); // first paint matches before the PC answers
  if (before.scenes !== state.scenes) write("scenes", state.scenes);
  if (before.bubbles !== state.bubbles) write("bubbles", state.bubbles.length ? state.bubbles : null);
  if (before.projects !== state.projects) write("projects", state.projects);
  if (before.overrides !== state.overrides) write("overrides", state.overrides);
  if (before.cleanup !== state.cleanup) write("cleanup", state.cleanup);
  if (before.motion !== state.motion) write("motion", state.motion === "system" ? null : state.motion);
  for (const listener of listeners) listener();
}

export function useOs(selector) {
  return useSyncExternalStore(
    listener => { listeners.add(listener); return () => listeners.delete(listener); },
    () => selector(state),
  );
}
export const getOs = () => state;
/** Non-React subscription (Settings sync). Returns the unsubscribe function. */
export function subscribeOs(listener) { listeners.add(listener); return () => listeners.delete(listener); }

/** `quiet` applies a replayed event's state without its toast. */
export function applyUiAction(action, payload, id = "", { quiet = false } = {}) {
  set(current => {
    const next = reduceUiAction(current, action, payload);
    const ownPendingLook = ownSettingsRequests.has(payload?.settingsRequestId)
      && ["settings.changed", "view.layout", "view.theme"].includes(action);
    // pane.show that asks for a renderer observation: the event id and paneId travel with the stage
    // into the mounted pane, which acknowledges it once its real content shows (NxPaneObserver.jsx).
    const request = action === "pane.show" && !quiet ? paneRequest(id, payload) : null;
    const placedRequest = request && payload.placement;
    const windows = placedRequest ? next.windows.map(win => win.desc.type === "pane" && win.desc.kind === payload.kind && win.desc.target === String(payload.target ?? "") ? { ...win, desc: { ...win.desc, request } } : win) : next.windows;
    const stage = request && !placedRequest ? { ...next.stage, request } : next.stage;
    return { ...next, windows, stage, ...(ownPendingLook ? { theme: current.theme, density: current.density } : {}),
      notices: quiet ? current.notices : next.notices, lastEventId: id || current.lastEventId };
  }, { lookIntent: !ownSettingsRequests.has(payload?.settingsRequestId) });
}

/** Seed from GET /api/ui/state: the durable sessions and projects the bus recorded. */
export function seedFromSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return;
  set(current => {
    const overrides = { ...current.overrides };
    for (const [id, row] of Object.entries(snapshot.sessions || {})) {
      const patch = {};
      for (const key of ["title", "pinned", "archived", "project"]) if (row && row[key] !== undefined) patch[key] = row[key];
      if (Object.keys(patch).length) overrides[id] = { ...patch, ...overrides[id] };
    }
    const projects = { ...current.projects };
    for (const [path, row] of Object.entries(snapshot.projects || {})) projects[path] = { name: row?.name || path, path: row?.path || path };
    const nightshift = { ...current.nightshift };
    for (const task of Array.isArray(snapshot.nightshift) ? snapshot.nightshift : []) {
      const status = { ticked: "done", ready: "waiting", pending: "waiting" }[task?.status] || task?.status;
      if (task?.id && NS_STATUSES.includes(status)) nightshift[task.id] = { ...task, status, at: Date.now() };
    }
    return { ...current, overrides, projects, nightshift, imageAsset: snapshot['image:requested'] || current.imageAsset, cleanup: snapshot.cleanupPolicy ?? current.cleanup, transparency: snapshot.transparency == null ? current.transparency : normalizeTransparency(snapshot.transparency) };
  });
}

function applyUiActionTo(current, action, payload) {
  try { return reduceUiAction(current, action, payload); } catch (error) { return toast(current, { level: "error", message: error.message }); }
}

export const os = {
  setDensity: density => set({ density }),
  setTheme: theme => { const next = THEMES.includes(theme) ? theme : DEFAULT_THEME; if (next !== state.theme) fadeTheme(() => set({ theme: next })); },
  setAmbient: on => set({ ambient: Boolean(on) }),
  setRain: on => set({ rain: Boolean(on) }),
  setLook: look => set({ look: normalizeLook(look) }),
  setTransparency: level => set({ transparency: normalizeTransparency(level) }),
  cycleTheme: () => fadeTheme(() => set(current => ({ theme: THEMES[(THEMES.indexOf(current.theme) + 1) % THEMES.length] }))),
  arrange: on => set(current => ({ arranging: on === undefined ? !current.arranging : Boolean(on), launcher: false })),
  updateLayout: change => set(current => ({ layout: normalizeLayout(change(current.layout)) })),
  resetLayout: () => set({ layout: normalizeLayout(null) }),
  toggleSidebar: () => set(current => ({ layout: { ...current.layout, sidebarHidden: !current.layout.sidebarHidden } })),
  scene: name => set(current => applyUiActionTo(current, "view.scene", { name })),
  saveScene: name => set(current => applyUiActionTo(current, "view.scene", { save: name })),
  deleteScene: id => set(current => { const scenes = { ...current.scenes }; delete scenes[id]; return { scenes }; }),
  float: id => set(current => float(current, id)),
  unfloat: id => set(current => unfloat(current, id)),
  moveBubble: (id, x, y) => set(current => ({ bubbles: current.bubbles.map(bubble => (bubble.id === id ? { ...bubble, x: clamp01(x), y: clamp01(y) } : bubble)) })),
  openBubble: id => set(current => ({ bubbleOpen: current.bubbleOpen === id ? null : id })),
  openApp: (app, suite, target = null) => set({ stage: { type: "app", app, suite, target }, launcher: false }),
  showPane: (kind, target) => set({ stage: { type: "pane", kind, target } }),
  closeStage: () => set({ stage: null }),
  // Windows (nxPlacementModel): move, restore, close, and the bubble's own position and peek.
  // `side` ("left" | "right") also moves the side panel region to that side of the conversation.
  placeWindow: (id, placement, side = null) => set(current => {
    const win = findWindow(current.windows, id);
    if (!win) return {};
    const layout = placement === "side" && side ? normalizeLayout({ ...current.layout, order: orderWithPanel(current.layout.order, side) }) : current.layout;
    return { windows: placeWindow(current.windows, id, placement), layout, placements: rememberPlacement(current.placements, win.desc, placement) };
  }),
  restoreWindow: id => set(current => ({ windows: restoreWindow(current.windows, id) })),
  closeWindow: id => set(current => ({ windows: closeWindow(current.windows, id) })),
  moveWindowBubble: (id, x, y) => set(current => ({ windows: moveWindowBubble(current.windows, id, x, y) })),
  peekWindow: (id, open) => set(current => ({ windows: peekBubble(current.windows, id, open) })),
  setLauncher: open => set(open ? { launcher: true } : { launcher: false, launcherQuery: "" }),
  setHelp: open => set({ help: Boolean(open), launcher: false }),
  setMotion: motion => set({ motion: ["reduce", "full"].includes(motion) ? motion : "system" }),
  openOnboarding: (step = "welcome", only = "") => set({ onboarding: { step, only, at: Date.now() }, launcher: false }),
  closeOnboarding: () => set({ onboarding: null }),
  setDashboard: open => set({ dashboard: Boolean(open), launcher: false }),
  setBus: bus => set(current => ({ bus: { ...current.bus, ...bus } })),
  setCleanup: cleanup => set({ cleanup }),
  setPrefs: (prefs, options) => set(current => applyPrefs(current, prefs, options), { lookIntent: false }),
  notify: notice => set(current => toast(current, notice)),
  dismiss: id => set(current => ({ notices: current.notices.filter(notice => notice.id !== id) })),
  drain: (app, upTo) => set(current => ({ inbox: current.inbox.filter(entry => entry.app !== app || entry.seq > upTo) })),
  // The user's own sidebar actions use the same overrides as the bus.
  patchSession: (id, patch) => set(current => patchSession(current, id, patch)),
  patchMany: (ids, patch) => set(current => ids.reduce((next, id) => patchSession(next, id, patch), current)),
};

// Development only: lets the accessibility audit (web/a11y) open each view directly.
if (import.meta.env?.DEV && globalThis.window) globalThis.window.__nxOs = os;
