import { useEffect, useRef } from "react";
import { createPoller } from "./pollingModel.js";

/**
 * Poll `run` while `enabled`. Hidden pages are not polled; unchanged answers slow the poll down.
 * `run` returns the value to compare; `onValue(value)` receives each fresh answer. Returns nothing:
 * call `wake` from the ref the hook exposes through `pollerRef` after a user action to refresh at once.
 */
export function usePoller(run, { enabled = true, activeMs = 2500, maxMs = 30000, onValue, onError, pollerRef } = {}) {
  const latest = useRef({ run, onValue, onError });
  latest.current = { run, onValue, onError };
  useEffect(() => {
    if (!enabled) return undefined;
    const poller = createPoller({
      activeMs, maxMs,
      run: () => latest.current.run(),
      onValue: value => latest.current.onValue?.(value),
      onError: error => latest.current.onError?.(error),
    });
    if (pollerRef) pollerRef.current = poller;
    const visible = () => { if (!document.hidden) poller.resume(); };
    document.addEventListener("visibilitychange", visible);
    poller.start();
    return () => { document.removeEventListener("visibilitychange", visible); poller.stop(); if (pollerRef) pollerRef.current = null; };
  }, [enabled, activeMs, maxMs, pollerRef]);
}
