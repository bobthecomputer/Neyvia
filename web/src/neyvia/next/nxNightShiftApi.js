import { useCallback, useEffect, useRef, useState } from "react";

import { callNx } from "./nxApi.js";
import { useOs } from "./nxOsStore.js";

// Night Shift over the generic backend command (plan 15 T10 contract):
// nightshift_<action>_command, the same call on the desktop (Tauri IPC) and in
// a browser (owner-authenticated HTTP). Actions: tasks, create, import, tick,
// start, stop, block, resources, summary, begin. The backend reads tasks,
// summary and an empty resources call as reads; everything else writes.

export function nightshift(action, payload = {}) {
  return callNx(`nightshift_${action}_command`, payload);
}

const RUNNING_TICK_MS = 15000;

/**
 * The saved board as the morning card sees it (summary: tasks with their
 * effective reasons, evidence links, measured time and tokens) plus the
 * budget policy. Re-read after every Night Shift event and after reconnects;
 * persisted state is the truth, events only say "look again".
 */
export function useNightShift(active = true) {
  const tasks = useOs(state => state.nightshift);
  const meta = useOs(state => state.nightshiftMeta);
  const bus = useOs(state => state.bus.state);
  const [state, setState] = useState({ status: "loading", summary: null, policy: null, error: "" });
  const alive = useRef(true);
  const timer = useRef(0);

  const load = useCallback(async () => {
    try {
      const [summary, policy] = await Promise.all([nightshift("summary"), nightshift("resources")]);
      if (alive.current) setState({ status: "ready", summary, policy, error: "" });
    } catch (error) {
      if (!alive.current) return;
      const offline = error?.code === "network" || error?.status === 401 || error?.status === 403 || /unknown command|not allowed/i.test(error?.message || "");
      setState(current => ({ ...current, status: current.summary ? "ready" : offline ? "offline" : "error", error: error?.message || "Night Shift could not be read." }));
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; clearTimeout(timer.current); };
  }, []);

  // Coalesce bursts of task events (a tick releases several dependents at once).
  useEffect(() => {
    if (!active) return undefined;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => void load(), 250);
    return () => clearTimeout(timer.current);
  }, [active, load, tasks, meta.rev, bus]);

  const running = Boolean(state.summary?.counts?.running);
  useEffect(() => {
    if (!active || !running) return undefined;
    const interval = setInterval(() => { if (!document.hidden) void load(); }, RUNNING_TICK_MS);
    return () => clearInterval(interval);
  }, [active, running, load]);

  return { ...state, refresh: load };
}
