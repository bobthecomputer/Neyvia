// Development-only stand-in for the backend command bus (`?bus=mock` under
// `vite dev`). It plays a short, believable evening so every indicator and
// sidebar reaction can be seen, and exposes `window.__nxBus` to emit any
// contract action by hand:
//   __nxBus.emit("pane.show", { kind: "browser", target: "https://example.com" })
//   __nxBus.acks  -> every acknowledgement the UI sent
// `&busscript=0` starts it silent.

const SCRIPT = [
  [600, "notify", { message: "Mock command bus connected", level: "info" }],
  [900, "indicator.updated", { key: "gpu", busy: true, label: "RTX 4060 · LAYA service", percent: 62 }],
  [900, "indicator.updated", { key: "usage", label: "Codex", used: 41, limit: 100, unit: "%" }],
  [1200, "nightshift.task.updated", { id: "T06", title: "Neyvia catalog truth", status: "done", evidence: "a1b2c3d" }],
  [1300, "nightshift.task.updated", { id: "T07", title: "Command bus + neyvia.* tools", status: "running" }],
  [1400, "nightshift.task.updated", { id: "T08", title: "Night Shift backend", status: "waiting" }],
  [1500, "nightshift.task.updated", { id: "T17", title: "Sidebar", status: "running" }],
  [1600, "nightshift.task.updated", { id: "T11", title: "LAYA resident GPU service", status: "blocked", reason: "GPU busy with a training run" }],
  [2400, "project.created", { name: "chronos", path: "C:\\Users\\dev\\Projects\\chronos" }],
  [2600, "session.moved", { id: "s-opencode", project: "C:\\Users\\dev\\Projects\\chronos" }],
  [2800, "session.renamed", { id: "s-opencode", title: "Chronos release notes draft" }],
];

// neyvia.* tool -> the bus event the real backend emits for it.
const TOOL_EVENTS = {
  "neyvia.session.pin": args => ["session.pinned", { id: args.id, pinned: args.pinned !== false }],
  "neyvia.session.archive": args => ["session.archived", { id: args.id, archived: args.archived !== false }],
  "neyvia.session.move": args => ["session.moved", { id: args.id, project: args.project ?? null }],
  "neyvia.session.rename": args => ["session.renamed", { id: args.id, title: args.title }],
  "neyvia.project.create": args => ["project.created", { name: args.name, path: args.path || `C:\\Users\\dev\\Projects\\${args.name}` }],
  "neyvia.pane.show": args => ["pane.show", args],
  "neyvia.view.layout": args => ["view.layout", args],
  "neyvia.view.arrange": args => ["view.arrange", args],
  "neyvia.view.scene": args => ["view.scene", args],
  "neyvia.view.float": args => ["view.float", args],
  "neyvia.view.theme": args => ["view.theme", args],
  "neyvia.notify": args => ["notify", args],
};

export function startMock({ deliver }) {
  const acks = [];
  let seq = 0;
  const emit = (action, payload = {}) => deliver({ id: String(++seq), ts: new Date().toISOString(), action, payload });
  const silent = new URLSearchParams(globalThis.location?.search || "").get("busscript") === "0";
  const timers = silent ? [] : SCRIPT.map(([at, action, payload]) => setTimeout(() => emit(action, payload), at));
  const callTool = async (tool, args = {}) => {
    const make = TOOL_EVENTS[tool];
    if (!make) throw new Error(`The mock backend has no ${tool}`);
    const [action, payload] = make(args);
    return { ok: true, event: emit(action, payload) };
  };
  const appState = {};
  globalThis.window.__nxBus = { emit, acks, callTool, appState };
  return {
    ack: message => acks.push(message),
    callTool,
    appState,
    stop: () => { timers.forEach(clearTimeout); delete globalThis.window.__nxBus; },
  };
}

/** The registry the mock backend serves: the plan's suites, with the apps that have a user side marked ready. */
export function mockRegistry(planSuites, ready = ["pdf"]) {
  return { suites: planSuites.map(suite => ({ ...suite, apps: suite.apps.map(app => ({ ...app, status: ready.includes(app.id) ? "ready" : "coming", manual: ready.includes(app.id) ? `docs/manuals/${app.id}.md` : null })) })) };
}
