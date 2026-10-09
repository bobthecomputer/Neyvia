import { useCallback, useEffect, useRef, useState } from "react";
import { callNx } from "./nxApi.js";

// Awareness data: the work board (who changes which files) and the impact map.
// The agent dashboard reads the same hook for its "Claimed" column.

export const loadWorkBoard = (filter = {}) => callNx("work_board_list_command", filter);
export const releaseClaim = id => callNx("work_board_release_command", { id });
export const claimFiles = (files, intent) => callNx("work_board_claim_command", { files, intent, agent: "Paul" });
export const checkImpact = paths => callNx("impact_map_command", { paths, gaps: true });

/** Paths typed one per line (or comma separated); blank lines dropped, duplicates removed. */
export function parsePaths(text) {
  return [...new Set(String(text || "").split(/[\n,]+/).map(line => line.trim().replace(/^["']|["']$/g, "")).filter(Boolean))];
}

/** Shorten a claimed path for a chip: keep the file and its folder. */
export function shortPath(path) {
  const parts = String(path || "").replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.length > 2 ? `…/${parts.slice(-2).join("/")}` : parts.join("/");
}

/** Polls the board while mounted; refresh() after an action. */
export function useWorkBoard({ pollMs = 15000 } = {}) {
  const [state, setState] = useState({ status: "loading", claims: [], error: "" });
  const alive = useRef(true);
  const refresh = useCallback(async () => {
    try {
      const board = await loadWorkBoard();
      if (alive.current) setState({ status: "ready", claims: board?.claims || [], released: board?.recentlyReleased || [], error: "" });
    } catch (error) {
      if (alive.current) setState(previous => ({ ...previous, status: "error", error: error?.message || "The work board can't be read." }));
    }
  }, []);
  useEffect(() => {
    alive.current = true;
    void refresh();
    const timer = pollMs ? setInterval(refresh, pollMs) : 0;
    return () => { alive.current = false; clearInterval(timer); };
  }, [refresh, pollMs]);
  return { ...state, refresh };
}
