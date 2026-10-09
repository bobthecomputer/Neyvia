import { useCallback, useEffect, useRef, useState } from "react";

import { callNx } from "./nxApi.js";
import { isRunActive, useNx } from "./nxStore.js";
import { errorKind } from "./nxWorkspaceModel.js";

// Last good picture per chat, so switching between the Workspace and Details
// tabs (or reopening the panel) shows something at once and refreshes quietly.
const snapshots = new Map();
// Last commit message made from this panel, used to prefill the pull request.
const lastCommits = new Map();

export const rememberCommit = (sessionId, message) => lastCommits.set(sessionId, message);
export const recallCommit = sessionId => lastCommits.get(sessionId) || "";

const STALE_MS = 30000;
const POLL_MS = 20000;

/**
 * The workspace of one chat. Refreshes on mount, on demand, when the chat's run
 * finishes, while a run is active (the agent is editing files), and when the
 * tab becomes visible again after a while.
 */
export function useWorkspace(sessionId) {
  const cached = snapshots.get(sessionId);
  const [snap, setSnap] = useState(() => ({
    status: cached ? "ready" : "loading", data: cached?.data || null, at: cached?.at || 0, error: null, busy: false, version: 0,
  }));
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setSnap(current => ({ ...current, busy: true }));
    try {
      const data = await callNx("connected_session_workspace_command", { id: sessionId });
      if (mine !== seq.current) return;
      const at = Date.now();
      snapshots.set(sessionId, { data, at });
      setSnap(current => ({ status: "ready", data, at, error: null, busy: false, version: current.version + 1 }));
    } catch (error) {
      if (mine !== seq.current) return;
      setSnap(current => ({
        ...current, busy: false, status: current.data ? "ready" : "error",
        error: { message: error?.message || "The workspace could not be read.", kind: errorKind(error), code: error?.code || "" },
      }));
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
    return () => { seq.current += 1; };
  }, [load]);

  const runState = useNx(state => state.runs[sessionId]?.state);
  const previous = useRef(runState);
  useEffect(() => {
    const wasActive = isRunActive({ state: previous.current });
    previous.current = runState;
    if (wasActive && !isRunActive({ state: runState })) void load();
  }, [runState, load]);

  const active = isRunActive({ state: runState });
  useEffect(() => {
    if (!active) return undefined;
    const timer = setInterval(() => { if (!document.hidden) void load(); }, POLL_MS);
    return () => clearInterval(timer);
  }, [active, load]);

  useEffect(() => {
    const onVisible = () => {
      if (!document.hidden && Date.now() - (snapshots.get(sessionId)?.at || 0) > STALE_MS) void load();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [sessionId, load]);

  return { ...snap, refresh: load };
}

/** One file's diff. `version` changes with every workspace refresh, which re-reads it quietly. */
export function useFileDiff(sessionId, path, version) {
  const [state, setState] = useState({ path, status: "loading", diff: null, error: null });
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const diff = await callNx("connected_session_file_diff_command", { id: sessionId, path });
      if (mine === seq.current) setState({ path, status: "ready", diff, error: null });
    } catch (error) {
      if (mine !== seq.current) return;
      setState(current => (current.path === path && current.diff
        ? current
        : { path, status: "error", diff: null, error: { message: error?.message || "The diff could not be read.", kind: errorKind(error) } }));
    }
  }, [sessionId, path]);

  useEffect(() => {
    void load();
    return () => { seq.current += 1; };
  }, [load, version]);

  const retry = useCallback(() => { setState({ path, status: "loading", diff: null, error: null }); void load(); }, [path, load]);
  // Moving to another file shows its skeleton at once instead of the previous file's lines.
  const current = state.path === path ? state : { status: "loading", diff: null, error: null };
  return { ...current, retry };
}
