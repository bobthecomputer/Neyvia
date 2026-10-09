// The startup splash in index.html covers every loading step (bundle, auth,
// workspace snapshot, shell chunk, conversation list) as one screen, so the
// workspace never appears half-empty. Screens report here once they can.

function boot() {
  return typeof window === "undefined" ? null : window.__neyviaBoot || null;
}

/** App code is running; reveal the workspace within `ms` even if content is slow. */
export function neyviaBootMounted(ms) {
  boot()?.mounted(ms);
}

/** Real content is on screen (conversation list loaded, or a screen that has none). */
export function neyviaBootReady() {
  boot()?.ready();
}
