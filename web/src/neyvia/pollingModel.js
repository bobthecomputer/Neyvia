// One scheduler for every UI poll that has no push channel yet (EFF, token and request waste).
//
// - Nothing runs while the page is hidden; becoming visible polls once right away.
// - While answers keep coming back unchanged the gap grows (x1.6 up to maxMs); a change, `wake()` or a
//   user action drops it back to activeMs.
// - One request at a time: a slow answer never stacks a second one behind it.
// Pure: timers, clock and visibility are injected so the same code is measured under a virtual clock.

export function createPoller({
  run,                       // async () => value; its JSON is the fingerprint
  activeMs = 2500,
  maxMs = 30000,
  growth = 1.6,
  unchangedBeforeGrowth = 2, // this many identical answers in a row before the gap grows
  isHidden = () => (typeof document !== "undefined" ? document.hidden : false),
  setTimer = (fn, ms) => setTimeout(fn, ms),
  clearTimer = handle => clearTimeout(handle),
  onValue = () => {},
  onError = () => {},
  fingerprint = value => JSON.stringify(value ?? null),
} = {}) {
  let handle = null, stopped = true, busy = false, gap = activeMs, same = 0, last, requests = 0;

  const schedule = () => {
    if (stopped || handle !== null) return;
    handle = setTimer(() => { handle = null; void tick(); }, gap);
  };
  const tick = async () => {
    if (stopped || busy) return;
    if (isHidden()) return; // resumed by `resume()` on visibilitychange
    busy = true; requests += 1;
    try {
      const value = await run();
      const print = fingerprint(value);
      if (print === last) { same += 1; if (same >= unchangedBeforeGrowth) gap = Math.min(maxMs, Math.round(gap * growth)); }
      else { same = 0; gap = activeMs; last = print; }
      if (!stopped) onValue(value);
    } catch (error) {
      gap = Math.min(maxMs, Math.round(gap * growth)); // a failing backend is not asked faster
      if (!stopped) onError(error);
    } finally {
      busy = false;
      schedule();
    }
  };
  const cancel = () => { if (handle !== null) { clearTimer(handle); handle = null; } };
  return {
    start() { if (!stopped) return; stopped = false; gap = activeMs; same = 0; last = undefined; void tick(); },
    stop() { stopped = true; cancel(); },
    /** Something happened (user action, focus, event): ask now and return to the fast gap. */
    wake() { if (stopped) return; gap = activeMs; same = 0; cancel(); void tick(); },
    /** The page became visible again. */
    resume() { if (stopped || handle !== null || busy) return; void tick(); },
    stats: () => ({ requests, gap, same }),
  };
}
