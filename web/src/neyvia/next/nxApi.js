import { invoke } from "@tauri-apps/api/core";

// One call path for the desktop app (Tauri IPC into the Python bridge) and
// the browser/phone (authenticated HTTP to the PC service).
export function isDesktopApp() {
  return Boolean(globalThis.window?.__TAURI_INTERNALS__);
}

export function backendBase() {
  const configured = String(
    import.meta.env?.VITE_FLUXIO_BACKEND_URL || globalThis.window?.__FLUXIO_BACKEND_URL__ || "",
  ).trim().replace(/\/$/, "");
  return configured;
}

export class NxError extends Error {
  constructor(message, { code = "", status = 0, data = null } = {}) {
    super(message);
    this.code = code;
    this.status = status;
    this.data = data; // the backend's own answer, kept so a failed git action can still show its output
  }
}

const useFixtures = import.meta.env?.DEV === true && new URLSearchParams(globalThis.location?.search || "").get("fixtures") === "1";

export async function callNx(command, payload = {}, { signal } = {}) {
  if (useFixtures) {
    const { devFixtureCall } = await import("./nxDevFixtures.js");
    return devFixtureCall(command, payload);
  }
  if (isDesktopApp()) {
    const result = await invoke("call_desktop_backend_command", { request: { command, payload } });
    if (result && result.ok === false) throw new NxError(result.message || result.error || `${command} failed`, { code: result.code, data: result });
    return result;
  }
  let response;
  try {
    response = await fetch(`${backendBase()}/api/backend`, {
      signal,
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command, payload }),
    });
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw new NxError("The PC service can't be reached.", { code: "network" });
  }
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result?.ok === false) {
    throw new NxError(result?.error || result?.message || `${command} failed (HTTP ${response.status})`, {
      code: result?.code || (response.status === 401 ? "login_required" : ""),
      status: response.status,
      data: result,
    });
  }
  return result?.data ?? result;
}

/**
 * Live connected-session events. Browsers use Server-Sent Events; the desktop
 * app long-polls through its bridge. Both resume from the last cursor, so a
 * reconnect never loses or repeats an event.
 */
export function subscribeEvents({ cursor = 0, onEvent, onState }) {
  let closed = false;
  let last = cursor;
  let source = null;
  let retry = 0;
  let timer = 0;

  const deliver = event => {
    if (typeof event?.cursor === "number") last = Math.max(last, event.cursor);
    onEvent(event);
  };
  const backoff = () => Math.min(15000, 600 * 2 ** retry++);

  const openSse = () => {
    if (closed) return;
    onState(retry ? "reconnecting" : "connecting");
    source = new EventSource(`${backendBase()}/api/connected/events?cursor=${last}`, { withCredentials: true });
    source.onopen = () => { retry = 0; onState("live"); };
    source.onmessage = message => {
      try { deliver(JSON.parse(message.data)); } catch { /* A malformed frame is skipped; the cursor keeps order. */ }
    };
    source.onerror = () => {
      source?.close();
      source = null;
      if (closed) return;
      onState("reconnecting");
      timer = setTimeout(openSse, backoff());
    };
  };

  const poll = async () => {
    while (!closed) {
      try {
        const result = await callNx("connected_events_poll_command", { cursor: last, waitSeconds: 20 });
        if (closed) return;
        retry = 0;
        onState("live");
        if (result?.resync) deliver({ type: "resync", cursor: result.cursor });
        for (const event of result?.events || []) deliver(event);
        if (typeof result?.cursor === "number") last = Math.max(last, result.cursor);
      } catch (error) {
        if (closed) return;
        onState(error?.code === "pc_service_offline" ? "offline" : "reconnecting");
        await new Promise(resolve => { timer = setTimeout(resolve, backoff()); });
      }
    }
  };

  if (useFixtures) onState("live");
  else if (isDesktopApp() || typeof EventSource === "undefined") void poll();
  else openSse();

  return () => {
    closed = true;
    clearTimeout(timer);
    source?.close();
  };
}

/** Sign this browser out of Neyvia and go back to the sign-in page. */
export async function signOutHere() {
  try {
    await fetch(`${backendBase()}/api/auth/logout`, { method: "POST", credentials: "include" });
  } catch { /* the reload shows whatever the PC answers next */ }
  globalThis.location?.reload();
}
