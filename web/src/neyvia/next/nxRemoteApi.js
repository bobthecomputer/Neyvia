import { backendBase, callNx, isDesktopApp } from "./nxApi.js";

// Remote control's user side (plans/15-handoff.md "## T19"). All calls need this PC's owner:
//   POST /api/ui/remote {op, args}                 enable, kill (this PC only) · connect, disconnect, snapshot, input, log
//   GET  /api/ui/remote/state                      {sessions (this PC's shares), connections (to other PCs)}
//   GET  /api/ui/remote/targets                    windows this PC could share {windowId, app, title, eligible, reason}
//   GET  /api/ui/remote/windows?connectionId=      the windows the other PC allowed
//   GET  /api/ui/remote/frame?connectionId=&windowId=  PNG + X-Frame-Seq, X-Capture-Id
// Refusals are {ok:false, code, error}. The one-use code and the connection's capability never
// go into a URL, a log or storage: the code lives in component state, the capability only in
// the backend.

function base() {
  const source = globalThis.window?.__NEYVIA_UI_SOURCE__;
  return backendBase() || (typeof source === "string" && source.startsWith("http") ? source : "");
}

export class RemoteError extends Error {
  constructor(code, status, message) {
    super(message || code);
    this.code = code;
    this.status = status;
  }
}

async function refusal(response) {
  const body = await response.json().catch(() => ({}));
  const code = body?.code || (response.status === 404 ? "missing" : response.status === 401 ? "login_required" : "refused");
  return new RemoteError(code, response.status, body?.error || `HTTP ${response.status}`);
}

async function send(path, init) {
  let response;
  try {
    response = await fetch(`${base()}${path}`, { credentials: "include", cache: "no-store", ...init });
  } catch {
    throw new RemoteError("unreachable", 0, "This PC's Neyvia service can't be reached.");
  }
  return response;
}

async function json(path, init) {
  const response = await send(path, init);
  if (!response.ok) throw await refusal(response);
  const body = await response.json().catch(() => ({}));
  if (body?.ok === false) throw new RemoteError(body.code || "refused", response.status, body.error);
  return body?.data ?? body;
}

// The desktop app reaches the same backend state through its bridge (remote_<op>_command).
async function desktop(op, args) {
  try {
    return await callNx(`remote_${op}_command`, args);
  } catch (error) {
    throw new RemoteError(error?.code || error?.data?.code || "refused", error?.status || 0, error?.message);
  }
}

export const remoteCall = (op, args = {}) => (isDesktopApp() ? desktop(op, args) : json("/api/ui/remote", {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ op, args }),
}));

export const remoteState = () => (isDesktopApp() ? desktop("state", {}) : json("/api/ui/remote/state"));
export const remoteTargets = () => (isDesktopApp() ? desktop("targets", {}) : json("/api/ui/remote/targets"));
export const remoteWindows = connectionId => (isDesktopApp() ? desktop("windows", { connectionId })
  : json(`/api/ui/remote/windows?connectionId=${encodeURIComponent(connectionId)}`));

/** The latest picture of an allowed window on the other PC, with the capture it belongs to. */
export async function remoteFrame(connectionId, windowId) {
  if (isDesktopApp()) {
    const frame = await desktop("frame", { connectionId, windowId });
    const bytes = Uint8Array.from(atob(frame.png), character => character.charCodeAt(0));
    return { buffer: bytes.buffer, captureId: frame.captureId, seq: frame.seq, sha: frame.sha };
  }
  const response = await send(`/api/ui/remote/frame?connectionId=${encodeURIComponent(connectionId)}&windowId=${encodeURIComponent(windowId)}`);
  if (!response.ok) throw await refusal(response);
  const buffer = await response.arrayBuffer();
  return {
    buffer,
    captureId: response.headers.get("X-Capture-Id") || "",
    seq: Number(response.headers.get("X-Frame-Seq")) || 0,
    sha: response.headers.get("X-CUA-Frame-SHA256") || "",
  };
}
