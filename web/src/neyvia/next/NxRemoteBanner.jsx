import { useSyncExternalStore } from "react";
import { Power } from "lucide-react";

import { remoteCall, remoteState } from "./nxRemoteApi.js";
import { liveSessions, stopReason, timeLeft } from "./nxRemoteModel.js";
import { Button, StatusDot, useTick } from "./nxPrimitives.jsx";
import { os } from "./nxOsStore.js";
import "./nxRemote.css";

// Remote control's shared state (GET /api/ui/remote/state), polled once a second while this
// PC shares a window or uses another PC, every few seconds otherwise. The warning below reads
// it, and so does the remote screen, so both always agree.

const IDLE_MS = 5000;
const LIVE_MS = 1000;

const store = { data: null, error: null, users: 0, timer: 0, inflight: null, gone: false, listeners: new Set() };
const emit = () => { for (const listener of store.listeners) listener(); };

function busy(data) {
  return liveSessions(data?.sessions).length > 0 || (data?.connections || []).some(row => row.status === "connected");
}

function schedule(ms) {
  clearTimeout(store.timer);
  if (!store.users || store.gone) return;
  store.timer = setTimeout(() => void refreshRemote().catch(() => {}), ms ?? (busy(store.data) ? LIVE_MS : IDLE_MS));
}

let announced = new Map(); // session id -> last status, to say once when a share ends

function announce(previous, next) {
  for (const session of next?.sessions || []) {
    const before = announced.get(session.id);
    if (before && before !== "stopped" && session.status === "stopped") {
      os.notify({ level: "info", message: `Remote control stopped: ${stopReason(session.reason).toLowerCase()}.` });
    }
    announced.set(session.id, session.status);
  }
  if (!previous) for (const session of next?.sessions || []) announced.set(session.id, session.status);
}

export function refreshRemote() {
  if (store.inflight) return store.inflight;
  store.inflight = remoteState().then(data => {
    const previous = store.data;
    store.data = data;
    store.error = null;
    announce(previous, data);
    return data;
  }).catch(error => {
    store.error = error;
    // Not this PC's owner, or a service without remote control: nothing to warn about here.
    if (error.status === 403 || error.code === "missing") store.gone = true;
    throw error;
  }).finally(() => {
    store.inflight = null;
    emit();
    schedule(store.error?.status === 401 ? 30000 : undefined);
  });
  return store.inflight;
}

function subscribe(listener) {
  store.listeners.add(listener);
  store.users += 1;
  if (store.users === 1) { store.gone = false; void refreshRemote().catch(() => {}); }
  return () => {
    store.listeners.delete(listener);
    store.users -= 1;
    if (!store.users) clearTimeout(store.timer);
  };
}

let snapshot = { data: null, error: null };
const read = () => {
  if (snapshot.data !== store.data || snapshot.error !== store.error) snapshot = { data: store.data, error: store.error };
  return snapshot;
};

/** {data: {sessions, connections}, error} kept fresh while mounted. */
export function useRemoteState() {
  return useSyncExternalStore(subscribe, read);
}

/** Stop one share, or every share when no id is given (POST kill). */
export async function stopSharing(sessionId) {
  try {
    await remoteCall("kill", sessionId ? { sessionId } : {});
  } catch (error) {
    os.notify({ level: "error", message: error.message === error.code ? "Couldn't stop it from here. Use Stop now in the warning window." : error.message });
  }
  await refreshRemote().catch(() => {});
}

/**
 * The always-visible "being controlled remotely" warning on the PC that shares. It sits above
 * everything in Neyvia (the native warning window with its own Stop button is separate and
 * works even when Neyvia's page is closed).
 */
export function NxRemoteBanner() {
  const { data } = useRemoteState();
  const live = liveSessions(data?.sessions);
  useTick(live.length > 0);
  if (!live.length) return null;
  const connected = live.filter(session => session.status === "connected");
  const first = connected[0] || live[0];
  const others = live.length - 1;
  const used = connected.length > 0;
  return (
    <div className={`nx-rm-banner${used ? " is-used" : ""}`} role="status" aria-live="polite">
      <StatusDot tone={used ? "live" : "gold"} pulse={used} />
      <button type="button" className="nx-rm-banner-text" onClick={() => os.showPane("preview", "remote:host")} title="Open remote control">
        <strong>{used ? "Being controlled remotely" : "Waiting for the other PC"}</strong>
        <span>
          {first.name}
          {others ? ` and ${others} more` : ""}
          {" · "}
          {timeLeft(first.expiresAt)}
        </span>
      </button>
      <Button size="sm" variant="warn" icon={Power} onClick={() => void stopSharing(live.length > 1 ? undefined : first.id)}>
        {live.length > 1 ? "Stop all now" : "Stop now"}
      </Button>
    </div>
  );
}
