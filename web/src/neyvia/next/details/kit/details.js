// Neyvia details for generated apps (plan 17 A2): the same small moments as Neyvia's own
// React details (../nxDetails.jsx), as plain DOM functions with no framework and no
// dependencies, so a web/PWA app made by `neyvia app new web` gets them from its first
// commit. Copy this folder as `details/` (details.manifest.json says which files), link
// details.css, import from details.js. The pure logic is shared with Neyvia (model.js).
// Sources and credits: docs/design/details-library.md.

import { calmVisible, meterFraction, numberCells, wheelRest, wheelTarget } from "./model.js";

const reduced = () => Boolean(globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

/** A very short vibration on touch phones; never on a mouse or with reduced motion. */
export function haptic(kind = "tick") {
  try {
    if (typeof navigator.vibrate !== "function" || !matchMedia("(pointer: coarse)").matches || reduced()) return false;
    return navigator.vibrate(kind === "confirm" ? [8, 40, 12] : 8);
  } catch {
    return false;
  }
}

let live = null;
/** Read a short sentence to screen readers (one polite live region per page). */
export function announce(text) {
  if (!text) return;
  if (!live?.isConnected) {
    live = document.createElement("div");
    live.className = "nxd-sr";
    live.setAttribute("role", "status");
    live.setAttribute("aria-live", "polite");
    document.body.append(live);
  }
  live.textContent = "";
  setTimeout(() => { live.textContent = String(text); }, 60);
}

const el = (tag, className, attrs = {}) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  for (const [key, value] of Object.entries(attrs)) if (value != null) node.setAttribute(key, value);
  return node;
};

/* ---------- rolling number ---------- */

const wheels = new WeakMap();

/**
 * Show `value` in `host`, rolling each digit the short way in the direction it moved.
 * Call again with the new value. The digits are CSS-generated, so the page text holds
 * the number once (for screen readers and for agents reading the app).
 */
export function rollingNumber(host, value, { decimals = 0, locale, suffix = "" } = {}) {
  let state = wheels.get(host);
  if (!state) {
    host.classList.add("nxd-roll");
    host.textContent = "";
    const sr = el("span", "nxd-sr");
    const face = el("span", "nxd-roll-face", { "aria-hidden": "true" });
    host.append(sr, face);
    state = { sr, face, cols: new Map(), last: null };
    wheels.set(host, state);
  }
  const amount = Number.isFinite(value) ? value : 0;
  const dir = state.last == null || amount >= state.last ? 1 : -1;
  const { text, cells } = numberCells(amount, { decimals, locale });
  state.sr.textContent = text + suffix;
  const keep = new Set();
  const nodes = [];
  for (const cell of cells) {
    keep.add(cell.key);
    let col = state.cols.get(cell.key);
    if (cell.kind === "mark") {
      if (!col) { col = { node: el("span", "nxd-roll-mark") }; state.cols.set(cell.key, col); }
      col.node.dataset.c = cell.char;
    } else {
      if (!col) {
        const node = el("span", `nxd-roll-col${state.last == null ? "" : " is-new"}`);
        const strip = el("span", "nxd-roll-strip");
        node.append(strip);
        col = { node, strip, pos: 10 + cell.digit };
        strip.style.setProperty("--nxd-roll-p", col.pos);
        strip.addEventListener("transitionend", event => {
          if (event.propertyName !== "transform") return;
          const rest = wheelRest(col.pos);
          if (rest === col.pos) return;
          col.pos = rest;
          strip.classList.add("is-snap");
          strip.style.setProperty("--nxd-roll-p", rest);
          void strip.getBoundingClientRect();
          strip.classList.remove("is-snap");
        });
        state.cols.set(cell.key, col);
      } else {
        const inBand = col.pos >= 10 && col.pos < 20;
        const to = wheelTarget(inBand ? col.pos : wheelRest(col.pos), cell.digit, dir);
        if (to !== col.pos) {
          if (!inBand) col.strip.classList.add("is-snap");
          col.pos = to;
          col.strip.style.setProperty("--nxd-roll-p", to);
          if (!inBand) { void col.strip.getBoundingClientRect(); col.strip.classList.remove("is-snap"); }
        }
      }
    }
    nodes.push(col.node);
  }
  if (suffix) {
    state.suffix ||= el("span", "nxd-roll-mark");
    state.suffix.dataset.c = suffix;
    nodes.push(state.suffix);
  }
  for (const [key, col] of state.cols) if (!keep.has(key)) state.cols.delete(key);
  // Move only what changed place: a column taken out of the page loses its running roll.
  for (const child of [...state.face.children]) if (!nodes.includes(child)) child.remove();
  nodes.forEach((node, index) => { if (state.face.children[index] !== node) state.face.insertBefore(node, state.face.children[index] || null); });
  state.last = amount;
}

/* ---------- meter ---------- */

const meters = new WeakMap();

/**
 * A thin progress meter in `host`. Pass {value, max} for real progress, or {startedAt,
 * estimateMs} for work with only an estimate (it creeps and stays under 90 % until done).
 */
export function meter(host, { value, max = 1, done = false, startedAt, estimateMs, tone = "ok", label } = {}) {
  let state = meters.get(host);
  if (!state) {
    host.classList.add("nxd-meter");
    host.setAttribute("role", "progressbar");
    host.setAttribute("aria-valuemin", "0");
    host.setAttribute("aria-valuemax", "100");
    const fill = el("i");
    host.replaceChildren(fill);
    state = { fill, timer: 0 };
    meters.set(host, state);
  }
  clearInterval(state.timer);
  if (label) host.setAttribute("aria-label", label);
  host.dataset.tone = done ? "ok" : tone;
  const estimating = !done && !Number.isFinite(value) && Number.isFinite(startedAt) && Number(estimateMs) > 0;
  const paint = () => {
    const fraction = meterFraction({ value, max, done, startedAt, estimateMs, now: Date.now() }) ?? 0;
    state.fill.style.setProperty("--nxd-meter", fraction);
    if (estimating) { host.removeAttribute("aria-valuenow"); host.setAttribute("aria-valuetext", "In progress"); }
    else { host.setAttribute("aria-valuenow", String(Math.round(fraction * 100))); host.removeAttribute("aria-valuetext"); }
  };
  paint();
  if (estimating) state.timer = setInterval(paint, 500);
}

/* ---------- confirm in place ---------- */

/**
 * Make `trigger` ask "Delete this?" right where it is. Focus goes to Keep; Escape or a
 * click elsewhere keeps; Delete calls onConfirm and announces doneText.
 */
export function confirmInPlace(trigger, { question, confirmLabel = "Delete", keepLabel = "Keep", doneText, onConfirm, onKeep } = {}) {
  let group = null;
  const close = confirmed => {
    if (!group) return;
    document.removeEventListener("pointerdown", outside, true);
    group.remove();
    group = null;
    trigger.hidden = false;
    if (confirmed) { haptic("confirm"); if (doneText) announce(doneText); onConfirm?.(); }
    else { trigger.focus(); onKeep?.(); }
  };
  const outside = event => { if (group && !group.contains(event.target)) close(false); };
  trigger.addEventListener("click", () => {
    if (group) return;
    group = el("span", "nxd-confirm", { role: "group", "aria-label": question });
    const ask = el("span", "nxd-confirm-q");
    ask.textContent = question;
    const yes = el("button", "nxd-btn is-danger", { type: "button" });
    yes.textContent = confirmLabel;
    const no = el("button", "nxd-btn", { type: "button" });
    no.textContent = keepLabel;
    yes.addEventListener("click", () => close(true));
    no.addEventListener("click", () => close(false));
    group.addEventListener("keydown", event => { if (event.key === "Escape") { event.stopPropagation(); close(false); } });
    group.append(ask, yes, no);
    trigger.after(group);
    trigger.hidden = true;
    no.focus();
    document.addEventListener("pointerdown", outside, true);
  });
  return { close: () => close(false) };
}

/* ---------- copy ---------- */

const COPY_ICON = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
const CHECK_ICON = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';

/**
 * Turn `button` into a copy button: its icon becomes a drawn check when the copy worked,
 * and it says "Copy failed" when the clipboard refused. `text` is a string or a function.
 */
export function copyButton(button, text, { label = "Copy", doneLabel = "Copied", failedLabel = "Copy failed", showLabel = false } = {}) {
  button.type = "button";
  button.classList.add("nxd-copy", "nxd-press");
  button.innerHTML = `<span class="nxd-copy-icons">${COPY_ICON.replace("<svg", '<svg class="nxd-copy-a"')}${CHECK_ICON.replace("<svg", '<svg class="nxd-copy-b"')}</span>`;
  const word = el("span", "nxd-copy-label");
  if (showLabel) { word.textContent = label; button.append(word); } else button.setAttribute("aria-label", label);
  button.title = label;
  let timer = 0;
  button.addEventListener("click", async () => {
    clearTimeout(timer);
    let state = "failed";
    try {
      await navigator.clipboard.writeText(String(typeof text === "function" ? text() : text));
      state = "done";
      haptic("tick");
    } catch { /* the label says it failed */ }
    button.dataset.state = state;
    button.title = state === "done" ? doneLabel : failedLabel;
    if (showLabel) word.textContent = button.title;
    announce(button.title);
    timer = setTimeout(() => { button.dataset.state = "idle"; button.title = label; if (showLabel) word.textContent = label; }, 1600);
  });
}

/* ---------- strike, empty state, calm loading ---------- */

/** Cross out `node`'s text (a finished task); the line draws in. */
export function strike(node, on) {
  node.classList.add("nxd-strike");
  node.classList.toggle("is-on", Boolean(on));
}

/**
 * An honest empty state: what is (not) here and one way forward.
 * tone: first | filtered | done. action: {label, onClick}.
 */
export function emptyState({ title, hint, action, tone = "first" } = {}) {
  const box = el("div", `nxd-empty is-${tone}`);
  if (title) { const node = el("strong"); node.textContent = title; box.append(node); }
  if (hint) { const node = el("p"); node.textContent = hint; box.append(node); }
  if (action) {
    const button = el("button", "nxd-btn nxd-press", { type: "button" });
    button.textContent = action.label;
    button.addEventListener("click", action.onClick);
    box.append(button);
  }
  return box;
}

/**
 * Show a loading state only for waits long enough to notice (after `delay` ms), and then
 * for at least `min` ms. Call start() when loading begins and stop() when it ends.
 */
export function calmLoading({ show, hide, delay = 240, min = 480 }) {
  const at = { since: null, shownAt: null, loading: false, visible: false, timer: 0 };
  const look = () => {
    clearTimeout(at.timer);
    const now = Date.now();
    const next = calmVisible({ loading: at.loading, since: at.since, shownAt: at.shownAt, now, delay, min });
    if (next.visible && at.shownAt == null) at.shownAt = now;
    if (!next.visible) at.shownAt = null;
    if (next.visible !== at.visible) { at.visible = next.visible; (next.visible ? show : hide)?.(); }
    if (next.wakeIn != null) at.timer = setTimeout(look, next.wakeIn);
  };
  return {
    start() { at.loading = true; at.since ??= Date.now(); look(); },
    stop() { at.loading = false; at.since = null; look(); },
  };
}
