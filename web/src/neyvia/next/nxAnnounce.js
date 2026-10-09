import { useEffect, useRef } from "react";

// One place that speaks to screen readers. Two hidden live regions (polite and
// assertive) live at the end of <body>; `announce` puts a short sentence in one.
// The same text twice in a row is still read: the region is cleared first.

const regions = {};

function region(kind) {
  if (regions[kind]?.isConnected) return regions[kind];
  const element = document.createElement("div");
  element.className = "nx-live-region";
  element.setAttribute("aria-live", kind);
  element.setAttribute("aria-atomic", "true");
  element.setAttribute("role", kind === "assertive" ? "alert" : "status");
  // Visually hidden, still read (inline so it works outside the .nx root).
  Object.assign(element.style, { position: "fixed", width: "1px", height: "1px", overflow: "hidden", clip: "rect(0 0 0 0)", clipPath: "inset(50%)", whiteSpace: "nowrap", left: "0", top: "0" });
  document.body.appendChild(element);
  regions[kind] = element;
  return element;
}

/** Read `text` to a screen reader. `assertive` interrupts (use for things that need Paul). */
export function announce(text, { assertive = false } = {}) {
  if (!text || typeof document === "undefined") return;
  const element = region(assertive ? "assertive" : "polite");
  element.textContent = "";
  setTimeout(() => { element.textContent = String(text); }, 60);
  (globalThis.__nxAnnounced ||= []).push({ at: Date.now(), text: String(text), assertive });
}

const SAY = {
  waiting_approval: (app, run) => `${app} needs your approval${run?.pendingRequest?.title ? `: ${run.pendingRequest.title}` : ""}.`,
  waiting_input: app => `${app} has a question for you.`,
  failed: app => `${app} stopped with an error.`,
  interrupted: app => `${app} was stopped.`,
};
const WORKING = new Set(["queued", "running", "starting", "working"]);

/** Say when the chat on screen changes state: it needs Paul, finished, or failed. Not on first sight. */
export function useRunAnnouncer(sessionId, run, appName) {
  const last = useRef({ sessionId: null, state: null });
  useEffect(() => {
    const state = run?.state || null;
    const before = last.current;
    last.current = { sessionId, state };
    if (before.sessionId !== sessionId || before.state === state || !state) return;
    const app = appName || "The agent";
    if (SAY[state]) announce(SAY[state](app, run), { assertive: state.startsWith("waiting") });
    else if (WORKING.has(before.state) && !WORKING.has(state)) announce(`${app} finished.`);
  }, [sessionId, run, appName]);
}
