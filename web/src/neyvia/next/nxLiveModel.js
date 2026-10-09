// The live preview's change detector, kept pure so the timing rules can be tested.
//
// The pane asks the backend for a cheap marker (artifact.stat) about once a second. A marker that
// changed means an agent is writing. Reloading on every tick would show half-written files and
// flash, so a change is only acted on once the marker has held still for one more tick (debounce);
// a file that keeps changing keeps waiting, up to a ceiling so the preview never stalls forever.

export const POLL_MS = 1000;
export const MAX_WAIT_TICKS = 6;

export function initialWatch(version = null) {
  return { shown: version, seen: version, quietTicks: 0, waitedTicks: 0 };
}

/**
 * One tick. `version` is the backend's latest marker (null when it could not be read).
 * Returns the next watch state and whether the pane should reload now.
 */
export function tick(watch, version) {
  if (version == null) return { watch, reload: false };
  if (version === watch.shown && version === watch.seen) return { watch: { ...watch, quietTicks: 0, waitedTicks: 0 }, reload: false };
  if (version !== watch.seen) {
    // Still moving: remember it and wait for it to hold still.
    const waitedTicks = watch.waitedTicks + 1;
    if (waitedTicks >= MAX_WAIT_TICKS) return { watch: { shown: version, seen: version, quietTicks: 0, waitedTicks: 0 }, reload: true };
    return { watch: { ...watch, seen: version, quietTicks: 0, waitedTicks }, reload: false };
  }
  // seen === version !== shown: it held still for this tick, so show it.
  return { watch: { shown: version, seen: version, quietTicks: 0, waitedTicks: 0 }, reload: true };
}

/** "Live · 3 s ago" style label; empty until something has been shown. */
export function liveLabel(updatedAt, now = Date.now()) {
  if (!Number.isFinite(updatedAt)) return "Live";
  const seconds = Math.max(0, Math.round((now - updatedAt) / 1000));
  if (seconds < 2) return "Live · just updated";
  if (seconds < 60) return `Live · updated ${seconds} s ago`;
  return `Live · updated ${Math.round(seconds / 60)} min ago`;
}
