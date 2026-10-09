// Computer use acts on the PC. The installed desktop app calls it directly. A
// browser is routed by the backend to the same app through the desktop
// controller, which enforces the PC owner's account and reports plainly when
// the app is not running. A backend with no paired PC app runs it on its host.
import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

import { fetchBackend } from "./neyviaBackendFetch.js";

export const PC_OFFLINE_MESSAGE = "The PC app is offline. Open Neyvia on the PC, then try again.";
// A live verification drives a browser on the PC and can run for minutes.
const PC_ACTION_TIMEOUT_MS = 20 * 60 * 1000;

export class PcHostError extends Error {
  constructor(message, { offline = false, status = 0, loginRequired = false } = {}) {
    super(message);
    this.name = "PcHostError";
    this.offline = offline;
    this.status = status;
    this.loginRequired = loginRequired;
  }
}

export function runsInDesktopApp() {
  return Boolean(globalThis.window?.__TAURI_INTERNALS__);
}

function requestId() {
  return globalThis.crypto?.randomUUID?.() || `pc-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export async function callPcHost(command, payload = {}) {
  if (runsInDesktopApp()) {
    return invoke("call_desktop_backend_command", { request: { command, payload } });
  }
  const response = await fetchBackend("/api/backend", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, payload, requestId: requestId() }),
  }, { command, timeoutMs: PC_ACTION_TIMEOUT_MS });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result?.ok === false) {
    // Only the controller sets this flag, and only when the PC app is not answering.
    throw new PcHostError(result?.error || `${command} failed`, {
      offline: Boolean(result?.pcOffline),
      status: response.status,
      loginRequired: Boolean(result?.loginRequired),
    });
  }
  return result?.data ?? {};
}

export async function readPcHostStatus(fetchImpl = globalThis.fetch) {
  if (runsInDesktopApp()) return { checked: true, registered: true, online: true, deviceName: "This PC", reason: "" };
  try {
    const response = await fetchImpl("/api/desktop-controller/status", { credentials: "same-origin" });
    const envelope = await response.json().catch(() => ({}));
    if (response.status === 403) {
      return { checked: true, registered: true, online: false, deviceName: "", reason: "Only the PC owner's account can control the PC." };
    }
    if (!response.ok || envelope?.ok === false) {
      return { checked: true, registered: true, online: false, deviceName: "", reason: envelope?.error || PC_OFFLINE_MESSAGE };
    }
    const data = envelope?.data || {};
    // updatedAt is empty until a PC app has connected to this backend at least once.
    return {
      checked: true,
      registered: data.updatedAt != null,
      online: Boolean(data.online),
      deviceName: String(data.deviceName || ""),
      reason: data.online ? "" : PC_OFFLINE_MESSAGE,
    };
  } catch {
    return { checked: true, registered: true, online: false, deviceName: "", reason: "Can't reach Neyvia right now. Check your connection to the PC." };
  }
}

/** Live PC status for a panel: checked once on mount, then while the page is visible. */
export function usePcHostStatus(pollMs = 5000) {
  const [status, setStatus] = useState({ checked: false, registered: false, online: false, deviceName: "", reason: "" });
  useEffect(() => {
    let stopped = false;
    let timer = 0;
    const refresh = async () => {
      if (!document.hidden) {
        const next = await readPcHostStatus();
        if (!stopped) setStatus(next);
      }
      if (!stopped) timer = window.setTimeout(refresh, pollMs);
    };
    void refresh();
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [pollMs]);
  return status;
}
