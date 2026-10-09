// Shared-element transitions (07 §2 motion, 15 · T2): the thing you pressed
// grows into what it opens. A sidebar leaf becomes the thread; a tool card
// becomes its pane. Nothing teleports.
//
// Built on the browser's View Transitions API (Chromium / WebView2): the
// pressed element and the opened surface share one `view-transition-name`
// for the length of the swap, so the browser morphs one box into the other.
// Where the API is missing, or reduced motion is on, the swap is instant.
//
// Elements that can be pressed to open something carry `data-nx-morph`. The
// last one pressed (within a moment) is the source; callers only say what
// opens and where it lands, so every way of opening a chat (sidebar, home
// cards, canopy, switcher) morphs without threading elements through props.

import { flushSync } from "react-dom";

const NAME = "nx-morph";
const RECENT_MS = 600;
let pressed = null;

if (typeof document !== "undefined") {
  const remember = event => {
    const source = event.target?.closest?.("[data-nx-morph]");
    pressed = source ? { element: source, at: performance.now() } : null;
  };
  document.addEventListener("pointerdown", remember, true);
  document.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") remember(event); }, true);
}

const reduced = () => globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches
  || (typeof document !== "undefined" && document.querySelector(".nx-root")?.getAttribute("data-nx-motion") === "reduce");

/**
 * Run a theme change as one cross-fade of the whole page (nxMotion.css times it with the
 * motion tokens) instead of a hard cut. Where View Transitions are missing, or motion is
 * reduced, or a morph is already running, the change is applied directly.
 */
export function fadeTheme(update) {
  if (typeof document === "undefined" || !document.startViewTransition || reduced()
    || document.visibilityState !== "visible" || document.documentElement.dataset.nxMorph) { update(); return; }
  try {
    const transition = document.startViewTransition(() => { flushSync(update); });
    transition.updateCallbackDone.catch(() => {});
    const guard = setTimeout(() => { try { transition.skipTransition(); } catch { /* already done */ } }, 1000);
    transition.finished.then(() => clearTimeout(guard), () => clearTimeout(guard));
  } catch { update(); }
}

/** The source element pressed just now, if any (consumed once). */
function takePressed() {
  const hit = pressed && performance.now() - pressed.at < RECENT_MS && pressed.element.isConnected ? pressed.element : null;
  pressed = null;
  return hit;
}

/**
 * Run `update` (a React state change) as a morph from the element just pressed
 * into the element `target` selects once the update has rendered.
 * Returns true when a morph ran, false when the update was applied directly.
 */
export function morph(update, target, { from = null } = {}) {
  const source = from || takePressed();
  if (!source || !document.startViewTransition || reduced() || document.visibilityState !== "visible") {
    update();
    return false;
  }
  const root = document.documentElement;
  let landed = null;
  source.style.viewTransitionName = NAME;
  root.dataset.nxMorph = "on";
  let transition;
  try {
    transition = document.startViewTransition(() => {
      source.style.viewTransitionName = "";
      flushSync(update);
      landed = typeof target === "function" ? target() : document.querySelector(target);
      if (landed) landed.style.viewTransitionName = NAME;
    });
  } catch {
    source.style.viewTransitionName = "";
    delete root.dataset.nxMorph;
    update();
    return false;
  }
  const done = () => {
    clearTimeout(guard);
    if (landed) landed.style.viewTransitionName = "";
    delete root.dataset.nxMorph;
  };
  // A window that stops painting mid-swap (minimised, a hidden pane) would hold
  // the frozen snapshot; past a second the morph is skipped and the page is live.
  const guard = setTimeout(() => { try { transition.skipTransition(); } catch { /* already done */ } done(); }, 1000);
  transition.finished.then(done, done);
  // A swap that throws inside the callback still finishes; nothing else to undo.
  transition.updateCallbackDone.catch(() => {});
  return true;
}
