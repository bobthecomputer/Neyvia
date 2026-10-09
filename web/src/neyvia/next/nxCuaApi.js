import { backendBase } from "./nxApi.js";
import { docsCall } from "./nxDocsApi.js";

// The computer-use preview's user side (plans/15-handoff.md "## T16"):
//   POST /api/ui/cua {op, args}                       open, snapshot, input, control, allow, foreground, approve, apps, end
//   GET  /api/ui/cua/state?sessionId=                 {driver, sessions}
//   GET  /api/ui/cua/frame?sessionId=&windowId=&seq=  the window's latest capture (image)
//   GET  /api/ui/cua/stream?sessionId=&cursor=        SSE {cursor, type: session|frame|focus|log, sessionId, data}
// Agents reach the same sessions through the MCP server with cua-driver's tool shape, and
// Neyvia's own models through neyvia.cua.*; every action of both lands in one shared log.
// In dev, `?fixtures=1` or `?cua=demo` swaps in a simulated driver with the same shapes.

function base() {
  const source = globalThis.window?.__NEYVIA_UI_SOURCE__;
  return backendBase() || (typeof source === "string" && source.startsWith("http") ? source : "");
}

const params = () => new URLSearchParams(globalThis.location?.search || "");
export const demoRequested = () => Boolean(import.meta.env?.DEV) && (params().get("fixtures") === "1" || params().get("cua") === "demo");

class Missing extends Error {
  constructor() { super("This PC's Neyvia service doesn't have computer use yet."); this.code = "missing"; }
}

const http = {
  demo: false,
  call: (op, args = {}) => docsCall("cua", op, args).catch(error => {
    if (error?.status === 404) throw new Missing();
    throw error;
  }),
  async state(sessionId = "") {
    let response;
    try {
      response = await fetch(`${base()}/api/ui/cua/state?sessionId=${encodeURIComponent(sessionId)}`, { credentials: "include" });
    } catch {
      throw new Error("The PC service can't be reached.");
    }
    if (response.status === 404) throw new Missing();
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result?.ok === false) throw Object.assign(new Error(result?.error || `Computer use state failed (HTTP ${response.status})`), { status: response.status });
    return result?.data ?? result;
  },
  frameUrl: (sessionId, windowId, seq) =>
    `${base()}/api/ui/cua/frame?sessionId=${encodeURIComponent(sessionId)}&windowId=${encodeURIComponent(windowId)}&seq=${encodeURIComponent(seq ?? "")}`,
  /** Live events, resumed from the last cursor after a drop. Returns the unsubscribe function. */
  subscribe(sessionId, { onEvent, onState }) {
    let closed = false;
    let source = null;
    let cursor = 0;
    let retry = 0;
    let timer = 0;
    const open = () => {
      if (closed) return;
      onState?.(retry ? "reconnecting" : "connecting");
      source = new EventSource(`${base()}/api/ui/cua/stream?sessionId=${encodeURIComponent(sessionId || "")}&cursor=${cursor}`, { withCredentials: true });
      source.onopen = () => { retry = 0; onState?.("live"); };
      source.onmessage = message => {
        try {
          const event = JSON.parse(message.data);
          if (typeof event.cursor === "number") cursor = Math.max(cursor, event.cursor);
          onEvent(event);
        } catch { /* a malformed frame is skipped; the cursor keeps order */ }
      };
      source.onerror = () => {
        source?.close();
        source = null;
        if (closed) return;
        onState?.("reconnecting");
        timer = setTimeout(open, Math.min(15000, 600 * 2 ** retry++));
      };
    };
    open();
    return () => { closed = true; clearTimeout(timer); source?.close(); };
  },
};

let demoClient = null;
let forcedDemo = false;

/** The client the preview talks to: the PC service, or (dev only) the simulated driver. */
export async function cuaClient() {
  if (!(forcedDemo || demoRequested())) return http;
  if (!demoClient) demoClient = import("./nxCuaFixture.js").then(module => module.createDemoDriver());
  return demoClient;
}

/** Dev only: switch this tab to the simulated driver (the "Show the demo" button). */
export function switchToDemoDriver() {
  if (import.meta.env?.DEV) forcedDemo = true;
}

export const isMissing = error => error?.code === "missing";
