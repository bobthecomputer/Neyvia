import { checkedProofsEModel } from "./nxProofsEContracts.js";
// Game Dev (07 §8, T12): pure helpers for the Game Dev screen. The backend
// (gamedev_*_command, the same state as neyvia.gamedev.*) is the truth; this
// file only names things, builds action arguments and reads receipts.

export const ENGINE_TABS = [
  { id: "babylon", name: "Browser 3D", editor: "your browser", blurb: "A 3D scene editor that runs right here, no install." },
  { id: "godot", name: "Godot", editor: "the Godot 4 editor", blurb: "Nodes, scripts, runs and the running game." },
  { id: "unity", name: "Unity", editor: "the Unity editor", blurb: "Scenes, components, Play mode and tests." },
  { id: "roblox", name: "Roblox Studio", editor: "Roblox Studio", blurb: "Instances, scripts and playtests, per Studio and context." },
  { id: "blender", name: "Blender", editor: "Blender", blurb: "Render, export to glTF, then load the file in an engine." },
  { id: "assets", name: "Asset checks", editor: "", blurb: "Check a glTF or GLB file before an engine loads it." },
];

// Launcher app id -> the tab it opens (the five Game Dev apps share one screen).
export const APP_TABS = { godot: "godot", unity: "unity", roblox: "roblox", "asset-checks": "assets", playtest: "babylon" };

function raw_tabForStage(app, target) {
  const wanted = String(target || "").toLowerCase();
  if (ENGINE_TABS.some(tab => tab.id === wanted)) return wanted;
  return APP_TABS[app] || "babylon";
}

/** One engine's row from gamedev_status_command, in words Paul reads. */
export function engineState(engine) {
  if (!engine) return { tone: "idle", word: "Checking", detail: "" };
  if (engine.status === "connected") return { tone: "green", word: "Connected", detail: "An editor is talking to Neyvia now." };
  if (engine.engine === "babylon") return { tone: "idle", word: "Not open", detail: "Open the scene below to connect it." };
  if (engine.installed) return { tone: "idle", word: "Editor found", detail: "Installed, but not connected. Set up a project, then open it in the editor." };
  return { tone: "gold", word: "Needs you", detail: "The editor isn't installed on this PC." };
}

const CONTEXT_WORDS = { Edit: "Editor", Play: "Running game", Client: "Client", Server: "Server" };
const ENV_WORDS = { "native-editor": "", "headless-native-proof": "Headless check, nothing drawn" };
/** The embedded Browser 3D scene registers as browser-webgl, or browser-null when the PC draws no 3D picture. */
export const isBrowserScene = session => /^browser-/.test(String(session?.environment || ""));

/** A session's name in words: never an adapter id, a raw environment or a literal null. */
export function sessionLabel(session) {
  if (isBrowserScene(session)) {
    const name = session.context && session.context !== "Edit" ? `Browser 3D ${String(CONTEXT_WORDS[session.context] || "").toLowerCase()}`.trim() : "Browser 3D editor";
    return session.environment === "browser-webgl" ? name : `${name} · no 3D picture`;
  }
  const context = CONTEXT_WORDS[session.context] || "Editor";
  const env = ENV_WORDS[session.environment] ?? "";
  return [context, env].filter(Boolean).join(" · ");
}

export function sessionState(session) {
  if (session.status === "connected") return { tone: "green", word: "Connected" };
  if (session.status === "needs_inspection") return { tone: "gold", word: "Check it in the editor" };
  return { tone: "idle", word: "Ended" };
}

/** Connected first, then most recently seen; ended ones after. */
export function sortSessions(sessions) {
  const rank = session => (session.status === "connected" ? 0 : session.status === "needs_inspection" ? 1 : 2);
  return [...sessions].sort((a, b) => rank(a) - rank(b) || (b.lastSeen || 0) - (a.lastSeen || 0));
}

/** The selection never moves to another session by itself; the first pick is automatic only when there is one choice. */
function raw_keepSelection(current, sessions) {
  const live = sessions.filter(session => session.status === "connected");
  const picked = sessions.find(session => session.sessionId === current);
  // The embedded Browser 3D scene registers again on every reload: follow it when it is the
  // only live scene for the same project and context. Native editors never switch by themselves.
  if (current && isBrowserScene(picked) && picked.status !== "connected") {
    const same = live.filter(session => isBrowserScene(session) && session.projectPath === picked.projectPath && session.context === picked.context);
    if (same.length === 1) return same[0].sessionId;
  }
  if (current && (picked || sessions.length)) return current; // ended: stays selected and shows as ended
  if (current && !sessions.length) return current;
  return live.length === 1 ? live[0].sessionId : "";
}

export const ACTION_WORDS = {
  inspect: "Inspect", select: "Select", edit: "Edit", validate: "Check script", run: "Run", interact: "Interact",
  console: "Console", stop: "Stop", reload: "Reload", test: "Test", render: "Render", export: "Export", load_asset: "Load asset",
};

// Typed fields per engine and action. kind: text | vec3 | number | bool | choice | json.
// Anything not listed sends {} or, for editors Neyvia hasn't been proven on, an arguments box.
const FIELDS = {
  godot: {
    select: [{ key: "node", label: "Node", kind: "text", placeholder: "Player", initial: "Player" }],
    edit: [
      { key: "node", label: "Node", kind: "text", placeholder: "Player", initial: "Player" },
      { key: "property", label: "Property", kind: "choice", options: ["position", "rotation", "scale", "visible"], initial: "position" },
      { key: "value", label: "Value", kind: "vec3", initial: [0, 0, 0], when: values => values.property !== "visible" },
      { key: "value", label: "Visible", kind: "bool", initial: true, when: values => values.property === "visible" },
    ],
    validate: [{ key: "path", label: "Script", kind: "text", placeholder: "res://player.gd", initial: "res://player.gd" }],
    interact: [
      { key: "node", label: "Node", kind: "text", placeholder: "Player", initial: "Player" },
      { key: "input", label: "Input", kind: "json", initial: { action: "jump" } },
    ],
    load_asset: [{ key: "path", label: "File", kind: "text", placeholder: "res://exports/model.glb", initial: "" }],
  },
  babylon: {
    select: [{ key: "name", label: "Mesh", kind: "text", placeholder: "Room", initial: "" }],
    edit: [
      { key: "op", label: "Change", kind: "choice", options: ["create", "transform", "material"], initial: "create" },
      { key: "name", label: "Mesh", kind: "text", placeholder: "Crate", initial: "Crate" },
      { key: "shape", label: "Shape", kind: "choice", options: ["box", "sphere", "ground"], initial: "box", when: values => values.op === "create" },
      { key: "position", label: "Position", kind: "vec3", initial: [0, 0.5, 0], when: values => values.op !== "material" },
      { key: "color", label: "Colour (0–1)", kind: "vec3", initial: [0.25, 0.65, 0.5], when: values => values.op === "material" },
      { key: "spin", label: "Spins when running", kind: "bool", initial: true, when: values => values.op !== "material" },
    ],
    interact: [
      { key: "name", label: "Mesh", kind: "text", placeholder: "Crate", initial: "" },
      { key: "rotateY", label: "Turn (radians)", kind: "number", initial: 0.5 },
    ],
    test: [
      { key: "name", label: "Mesh", kind: "text", placeholder: "Crate", initial: "" },
      { key: "minVertices", label: "At least this many vertices", kind: "number", initial: 8 },
    ],
    export: [{ key: "path", label: "Save as", kind: "text", placeholder: "exports/scene.glb", initial: "exports/scene.glb" }],
    load_asset: [{ key: "path", label: "File", kind: "text", placeholder: "exports/scene.glb", initial: "exports/scene.glb" }],
  },
};

// Examples from each bridge's own README, for editors whose actions take free arguments here.
const EXAMPLES = {
  unity: { inspect: {}, select: { path: "Main Camera" }, edit: { path: "Cube", component: "Transform", property: "m_LocalPosition", vector: [0, 1, 0] }, load_asset: { path: "Assets/Model.prefab" }, test: { mode: "EditMode" } },
  roblox: { inspect: { path: "game/Workspace", depth: 2 }, select: { path: "game/Workspace/Part" }, edit: { path: "game/Workspace/Part", property: "Anchored", value: true }, run: { mode: "play" }, stop: { mode: "play" } },
  blender: { select: { object: "Cube" }, edit: { object: "Cube", location: [0, 0, 1] }, render: { path: "exports/view.png", camera: "Camera" }, export: { path: "exports/model.glb", selectedOnly: false }, load_asset: { path: "exports/model.glb" } },
};

function raw_actionFields(engine, action) {
  const typed = FIELDS[engine]?.[action];
  if (typed) return typed;
  const example = EXAMPLES[engine]?.[action];
  if (example && Object.keys(example).length) return [{ key: "*", label: "Arguments", kind: "json", initial: example }];
  return [];
}

function raw_initialValues(fields) {
  const values = {};
  for (const field of fields) if (!(field.key in values) || (field.when && field.when(values))) values[field.key] = field.initial;
  return values;
}

/** Fields shown for the current values (some depend on others, like Godot's visible). */
const raw_visibleFields = (fields, values) => fields.filter(field => !field.when || field.when(values));

/** Turn form values into the action's args; throws a plain message for a bad entry. */
function raw_buildArgs(fields, values) {
  const args = {};
  for (const field of visibleFields(fields, values)) {
    const value = values[field.key];
    if (field.kind === "json") {
      const parsed = typeof value === "string" ? parseJson(value, field.label) : value;
      if (field.key === "*") Object.assign(args, parsed);
      else args[field.key] = parsed;
    } else if (field.kind === "vec3") {
      const numbers = (Array.isArray(value) ? value : []).map(Number);
      if (numbers.length !== 3 || numbers.some(number => !Number.isFinite(number))) throw new Error(`${field.label} needs three numbers.`);
      args[field.key] = numbers;
    } else if (field.kind === "number") {
      const number = Number(value);
      if (!Number.isFinite(number)) throw new Error(`${field.label} needs a number.`);
      args[field.key] = number;
    } else if (field.kind === "bool") {
      args[field.key] = Boolean(value);
    } else {
      const text = String(value ?? "").trim();
      if (text) args[field.key] = text;
    }
  }
  return args;
}

function parseJson(text, label) {
  try {
    const value = JSON.parse(text || "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("not an object");
    return value;
  } catch {
    throw new Error(`${label} must be written as {"key": value}.`);
  }
}

export const isDone = status => ["succeeded", "failed", "timed_out"].includes(status);

export function receiptState(receipt) {
  switch (receipt?.status) {
    case "succeeded": return { tone: "green", word: "Done" };
    case "failed": return { tone: "red", word: "Failed" };
    case "timed_out": return { tone: "red", word: "Timed out" };
    case "running": return { tone: "live", word: "Working", pulse: true };
    case "queued": return { tone: "live", word: "Waiting for the editor", pulse: true };
    default: return { tone: "idle", word: receipt?.status || "Sending" };
  }
}

// Backend refusals are written for the bots; Paul gets the next step.
const FRIENDLY = [
  [/Select a connected editor session/i, "That editor isn't connected any more. Open it again, then pick its session."],
  [/does not support this action/i, "This session can't do that. Pick the session that can (the editor or the running game)."],
  [/needs Paul: install/i, "The editor isn't installed on this PC yet."],
  [/Path must stay inside/i, "That is outside the game workspace. Pick something inside it."],
  [/Select an existing project directory/i, "That folder doesn't exist in the game workspace."],
  [/Existing export needs/i, "A file with that name is already there. Pick a new name so nothing is overwritten."],
  [/Choose a new mesh name/i, "There's already a mesh with that name. Pick a new one."],
  [/Preserving existing file/i, "A different file is already there, so nothing was overwritten."],
];

export function friendlyError(message) {
  const text = String(message || "");
  const hit = FRIENDLY.find(([pattern]) => pattern.test(text));
  return hit ? hit[1] : text || "That didn't work.";
}

/** The newest inspect result with a tree, for the inspection view. */
export function latestTree(receipts) {
  for (const receipt of receipts) {
    if (receipt.action === "inspect" && receipt.status === "succeeded" && receipt.result?.tree) return receipt;
    if (receipt.action === "interact" && receipt.status === "succeeded" && receipt.result?.tree) return receipt;
  }
  return null;
}

export function formatVector(value) {
  if (!Array.isArray(value)) return "";
  return value.map(number => (Number.isFinite(number) ? (Math.round(number * 100) / 100).toString() : "?")).join(", ");
}

/** The last folder of a path, for display; the full path stays in a tooltip. */
export const folderName = path => String(path || "").split(/[\\/]/).filter(Boolean).pop() || "";

export function shortPath(path, keep = 2) {
  const parts = String(path || "").split(/[\\/]/).filter(Boolean);
  return parts.length > keep + 1 ? `…\\${parts.slice(-keep).join("\\")}` : String(path || "");
}

export function newRequestId() {
  return globalThis.crypto?.randomUUID?.() || `r${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}

// Public observers check the executable manual claims on every invocation.
export function actionFields(...args) { return checkedProofsEModel("gamedev.actionFields", args, raw_actionFields(...args)); }
export function keepSelection(...args) { return checkedProofsEModel("gamedev.keepSelection", args, raw_keepSelection(...args)); }
export function tabForStage(...args) { return checkedProofsEModel("gamedev.tabForStage", args, raw_tabForStage(...args)); }
export function visibleFields(...args) { return checkedProofsEModel("gamedev.visibleFields", args, raw_visibleFields(...args)); }
export function initialValues(...args) { return checkedProofsEModel("gamedev.initialValues", args, raw_initialValues(...args)); }
export function buildArgs(...args) { return checkedProofsEModel("gamedev.buildArgs", args, raw_buildArgs(...args)); }
