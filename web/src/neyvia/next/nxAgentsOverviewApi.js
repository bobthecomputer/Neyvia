import { useCallback, useEffect, useRef, useState } from "react";
import { backendBase, callNx } from "./nxApi.js";
import { callTool } from "./nxBus.js";
import { useOs } from "./nxOsStore.js";
import { conductorControl } from "./nxAgentsApi.js";
import { nightshift } from "./nxNightShiftApi.js";

export async function readOverview() {
  const response = await fetch(`${backendBase()}/api/ui/agents/overview`, { credentials: "include" });
  const value = await response.json();
  if (!response.ok || value.ok === false) throw new Error(value.error || `Agents overview is unavailable (${response.status})`);
  return value.data ?? value;
}

export function useAgentsOverview(pane) {
  const [state, setState] = useState({ data: null, error: "", busy: false });
  const revision = useOs(s => s.agentsOverviewRevision);
  const night = useOs(s => s.nightshift);
  const bus = useOs(s => s.bus.state);
  const flight = useRef(false), alive = useRef(true), last = useRef(0);
  const load = useCallback(async () => {
    if (flight.current || document.hidden || pane.current?.closest('[aria-hidden="true"], [inert]')) return;
    flight.current = true; last.current = Date.now();
    setState(s => ({ ...s, busy: true }));
    try { const data = await readOverview(); if (alive.current) setState({ data, error: data.error || "", busy: false }); }
    catch (error) { if (alive.current) setState(s => ({ ...s, busy: false, error: error.message })); }
    finally { flight.current = false; }
  }, [pane]);
  useEffect(() => {
    alive.current = true; void load();
    // One aggregate fallback for sources without events. No per-source polls;
    // hidden panes/pages stop requesting, event bursts coalesce below.
    const timer = setInterval(load, 15000);
    const visible = () => { if (!document.hidden) void load(); };
    const surface = pane.current?.closest(".nx-surface");
    const observer = new MutationObserver(visible);
    if (surface) observer.observe(surface, { attributes: true, attributeFilter: ["aria-hidden", "inert"] });
    document.addEventListener("visibilitychange", visible);
    return () => { alive.current = false; clearInterval(timer); observer.disconnect(); document.removeEventListener("visibilitychange", visible); };
  }, [load]);
  useEffect(() => {
    const timer = setTimeout(load, Math.max(400, 3000 - (Date.now() - last.current)));
    return () => clearTimeout(timer);
  }, [revision, night, bus, load]);
  useEffect(() => {
    if (!state.data?.loading) return;
    const timer = setTimeout(load, 3000);
    return () => clearTimeout(timer);
  }, [state.data, load]);
  return { ...state, reload: load };
}

export function stopOverviewAgent(target) {
  if (target.kind === "session") return callNx("connected_session_stop_command", { runId: target.id });
  if (target.kind === "nightshift") return nightshift("stop", { id: target.id });
  if (target.kind === "conductor") return conductorControl(target.id, "stop");
  if (target.kind === "mission") return callTool("neyvia.mission.control", { id: target.id, action: "stop" });
  return callTool(`neyvia.${target.kind}.stop`, { run: target.id });
}

export async function messageOverviewAgent(row, text) {
  const target = JSON.stringify(row.sessionId);
  const receipt = await callTool("neyvia.agents.deliveries", { to: row.sessionId });
  const before = receipt.result?.lastId ?? receipt.lastId;
  if (!Number.isSafeInteger(before)) throw new Error("Message delivery could not be observed");
  const result = await callTool("neyvia.cl", { lines: `G: agents.deliveries(to=${target}).lastId > ${before}\ndo message(to=${target}, text=${JSON.stringify(text)}, from="You")\ndone()` });
  if (!result.ok || result.status !== "ok") throw new Error(result.results?.find(r => r.error)?.error || "Message delivery could not be verified");
  return result;
}
