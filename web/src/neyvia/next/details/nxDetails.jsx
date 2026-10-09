import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";

import "./nxDetails.css";
import { announce } from "../nxAnnounce.js";
import { Button, Icon } from "../nxPrimitives.jsx";
import { calmVisible, meterFraction, numberCells, wheelRest, wheelTarget } from "./nxDetailsModel.js";

// Neyvia's details library (plan 17 A2): small moments that make the product feel finished.
// Each one has a design-manual entry (manuals/design.manual.json, chapter "details"), a
// design-lab specimen (lab/specimens/details-*.jsx) and its sources in
// docs/design/details-library.md. Motion uses the duration and spring tokens only; the
// global reduced-motion rule in nxTokens.css turns every transition here into a cut, and
// JS that would move something checks prefers-reduced-motion first (haptic below).
// Generated apps get this folder through the app template (details.manifest.json).

/** The press class: a 0.97 press on --nx-snappy for buttons that act (Emil Kowalski, MIT). */
export const PRESS = "nx-press";

const reducedMotion = () => typeof window !== "undefined" && Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

/**
 * Haptic-like feedback on phones: a very short vibration where the browser supports it,
 * never on a mouse, never when the person asked for reduced motion. Returns true if it ran.
 */
export function haptic(kind = "tick") {
  try {
    if (typeof navigator === "undefined" || typeof navigator.vibrate !== "function") return false;
    if (!window.matchMedia?.("(pointer: coarse)").matches || reducedMotion()) return false;
    return navigator.vibrate(kind === "confirm" ? [8, 40, 12] : 8);
  } catch {
    return false;
  }
}

/* ---------- rolling number ---------- */

function Column({ digit, dir, fresh }) {
  const [state, setState] = useState(() => ({ pos: 10 + digit, snap: false }));
  const [born] = useState(fresh);
  const strip = useRef(null);
  const pos = useRef(10 + digit);

  useLayoutEffect(() => {
    const inBand = pos.current >= 10 && pos.current < 20;
    const to = wheelTarget(inBand ? pos.current : wheelRest(pos.current), digit, dir);
    if (to === pos.current) return;
    pos.current = to;
    setState({ pos: to, snap: !inBand });
  }, [digit]); // eslint-disable-line react-hooks/exhaustive-deps -- a change of direction alone must not move the wheel

  useLayoutEffect(() => {
    if (!state.snap) return undefined;
    void strip.current?.getBoundingClientRect(); // apply the jump before the transition comes back
    const frame = requestAnimationFrame(() => setState(current => ({ ...current, snap: false })));
    return () => cancelAnimationFrame(frame);
  }, [state.snap]);

  const onEnd = event => {
    if (event.target !== event.currentTarget || event.propertyName !== "transform") return;
    const rest = wheelRest(pos.current);
    if (rest === pos.current) return;
    pos.current = rest;
    setState({ pos: rest, snap: true });
  };

  return (
    <span className={`nx-roll-col${born ? " is-new" : ""}`}>
      <span ref={strip} className={`nx-roll-strip${state.snap ? " is-snap" : ""}`} style={{ "--nx-roll-p": state.pos }} onTransitionEnd={onEnd} />
    </span>
  );
}

/**
 * A number that rolls to its new value, one wheel per digit, the short way in the
 * direction the value moved. A screen reader hears the whole number once.
 */
export function RollingNumber({ value, decimals = 0, locale, prefix, suffix, className = "" }) { // prefix/suffix: plain strings
  const amount = Number.isFinite(value) ? value : 0;
  const previous = useRef(amount);
  const dir = amount >= previous.current ? 1 : -1;
  useEffect(() => { previous.current = amount; }, [amount]);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; }, []);
  const { text, cells } = numberCells(amount, { decimals, locale });
  return (
    <span className={`nx-roll ${className}`}>
      <span className="nx-visually-hidden">{prefix}{text}{suffix}</span>
      {/* The faces are CSS-generated text: the page's text (and an agent reading it) holds the number once. */}
      <span className="nx-roll-face" aria-hidden="true">
        {prefix != null ? <span className="nx-roll-mark" data-c={prefix} /> : null}
        {cells.map(cell => cell.kind === "digit"
          ? <Column key={cell.key} digit={cell.digit} dir={dir} fresh={mounted.current} />
          : <span key={cell.key} className="nx-roll-mark" data-c={cell.char} />)}
        {suffix != null ? <span className="nx-roll-mark" data-c={suffix} /> : null}
      </span>
    </span>
  );
}

/* ---------- meter ---------- */

function useNow(active, ms) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return undefined;
    const timer = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(timer);
  }, [active, ms]);
  return now;
}

/**
 * A thin progress meter. With `value`/`max` it shows the real fraction; with `startedAt`
 * and `estimateMs` it creeps (fast, then slower) and never passes 90 % until `done`.
 * It fills with transform (no layout), on the drift spring. `decorative` hides it from
 * screen readers when the text beside it already says the same.
 */
export function Meter({ value, max = 1, done = false, startedAt, estimateMs, tone = "ok", label, decorative = false, className = "" }) {
  const estimating = !done && !Number.isFinite(value) && Number.isFinite(startedAt) && Number(estimateMs) > 0;
  const now = useNow(estimating, 500);
  const fraction = meterFraction({ value, max, done, startedAt, estimateMs, now }) ?? 0;
  const known = !estimating;
  // decorative: the words beside it already say the same (e.g. "Night Shift 3/5").
  const a11y = decorative ? { "aria-hidden": true } : {
    role: "progressbar", "aria-label": label, "aria-valuemin": 0, "aria-valuemax": 100,
    "aria-valuenow": known ? Math.round(fraction * 100) : undefined, "aria-valuetext": known ? undefined : "In progress",
  };
  return (
    <span {...a11y}
      className={`nx-meter is-${done ? "ok" : tone}${estimating ? " is-estimating" : ""} ${className}`}>
      <i style={{ "--nx-meter": fraction }} />
    </span>
  );
}

/* ---------- confirm in place ---------- */

const FOCUSABLE = "button, [href], [tabindex]";

/**
 * Ask "Delete this?" right where the button was, no dialog. `children(open)` renders the
 * trigger. Focus goes to Keep (the safe choice); Escape or a click elsewhere keeps; after
 * Keep focus returns to the trigger; after the action a screen reader hears `doneText`.
 */
export function ConfirmInPlace({ question, confirmLabel, keepLabel = "Keep", doneText, onConfirm, onKeep, children, defaultOpen = false, className = "" }) {
  const [open, setOpen] = useState(Boolean(defaultOpen));
  const group = useRef(null);
  const keep = useRef(null);
  const host = useRef(null);
  const refocus = useRef(false);
  const opener = useRef(0); // which of the trigger's controls opened it, to hand focus back on Keep

  const close = useCallback(confirmed => {
    setOpen(false);
    if (confirmed) {
      haptic("confirm");
      if (doneText) announce(doneText);
      onConfirm?.();
    } else {
      refocus.current = true;
      onKeep?.();
    }
  }, [doneText, onConfirm, onKeep]);

  useEffect(() => {
    if (open) { keep.current?.focus(); return undefined; }
    if (refocus.current) {
      refocus.current = false;
      const controls = [...(host.current?.querySelectorAll(FOCUSABLE) || [])];
      (controls[opener.current] || controls[0])?.focus();
    }
    return undefined;
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const outside = event => { if (!group.current?.contains(event.target)) close(false); };
    document.addEventListener("pointerdown", outside, true);
    return () => document.removeEventListener("pointerdown", outside, true);
  }, [open, close]);

  if (open) {
    return (
      <span ref={group} className={`nx-confirm ${className}`} role="group" aria-label={question}
        onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); close(false); } }}>
        <span className="nx-confirm-q">{question}</span>
        <Button size="sm" variant="warn" className={PRESS} onClick={() => close(true)}>{confirmLabel}</Button>
        <Button ref={keep} size="sm" className={PRESS} onClick={() => close(false)}>{keepLabel}</Button>
      </span>
    );
  }
  const ask = () => {
    const controls = [...(host.current?.querySelectorAll(FOCUSABLE) || [])];
    opener.current = Math.max(0, controls.indexOf(document.activeElement));
    setOpen(true);
  };
  return <span ref={host} className="nx-confirm-host">{children(ask)}</span>;
}

/* ---------- strike ---------- */

/** Text that gets a line drawn through it when `on` turns true (a done task), per line. */
export function Strike({ on, children }) {
  return <span className={`nx-strike${on ? " is-on" : ""}`}>{children}</span>;
}

/* ---------- copy ---------- */

/** Copy with a result: state is idle | done | failed for `resetMs`, announced either way. */
export function useCopy({ doneLabel = "Copied", failedLabel = "Copy failed", resetMs = 1600 } = {}) {
  const [state, setState] = useState("idle");
  const timer = useRef(0);
  useEffect(() => () => clearTimeout(timer.current), []);
  const copy = useCallback(async text => {
    clearTimeout(timer.current);
    let next = "failed";
    try {
      if (!navigator.clipboard?.writeText) throw new Error("no clipboard");
      await navigator.clipboard.writeText(String(text ?? ""));
      next = "done";
      haptic("tick");
    } catch { /* the label says it failed */ }
    setState(next);
    announce(next === "done" ? doneLabel : failedLabel);
    timer.current = setTimeout(() => setState("idle"), resetMs);
    return next === "done";
  }, [doneLabel, failedLabel, resetMs]);
  return [state, copy];
}

/**
 * Copy button whose icon turns into a drawn check for a moment. Icon only by default
 * (`label` is its name); `showLabel` also writes the word, which changes to "Copied".
 */
export function CopyButton({ text, label = "Copy", doneLabel = "Copied", failedLabel = "Copy failed", showLabel = false, size = "sm", className = "" }) {
  const [state, copy] = useCopy({ doneLabel, failedLabel });
  const word = state === "done" ? doneLabel : state === "failed" ? failedLabel : label;
  return (
    <button type="button" className={`nx-copybtn is-${size} is-${state} ${PRESS} ${className}`}
      aria-label={showLabel ? undefined : label} title={word} onClick={() => void copy(text)}>
      <span className="nx-copybtn-icons" aria-hidden="true">
        <Icon as={Copy} size={size === "xs" ? 12 : 14} className="nx-copybtn-copy" />
        <Icon as={Check} size={size === "xs" ? 12 : 14} className="nx-copybtn-check" />
      </span>
      {showLabel ? <span className="nx-copybtn-label">{word}</span> : null}
    </button>
  );
}

/* ---------- empty state ---------- */

/**
 * An honest empty state: what is (not) here, and one way forward. tone: first (nothing
 * yet), filtered (nothing matches; the action clears the filter), done (all finished).
 */
export function EmptyState({ icon, title, hint, action, tone = "first", className = "" }) {
  return (
    <div className={`nx-blank is-${tone} ${className}`}>
      {icon ? <span className="nx-blank-mark"><Icon as={icon} size={18} /></span> : null}
      {title ? <strong className="nx-blank-title">{title}</strong> : null}
      {hint ? <p className="nx-blank-hint">{hint}</p> : null}
      {action ? <Button size="sm" variant="outline" icon={action.icon} className={PRESS} onClick={action.onClick}>{action.label}</Button> : null}
    </div>
  );
}

/* ---------- calm loading ---------- */

/**
 * True while a loading state should show: only after `delay` ms of waiting (a fast load
 * shows nothing), and then for at least `min` ms (it never flashes on and off).
 */
export function useCalmLoading(loading, { delay = 240, min = 480 } = {}) {
  const [visible, setVisible] = useState(false);
  const marks = useRef({ since: null, shownAt: null });
  useEffect(() => {
    const at = marks.current;
    if (loading && at.since == null) at.since = Date.now();
    if (!loading) at.since = null;
    let timer = 0;
    const look = () => {
      const now = Date.now();
      const next = calmVisible({ loading, since: at.since, shownAt: at.shownAt, now, delay, min });
      if (next.visible && at.shownAt == null) at.shownAt = now;
      if (!next.visible) at.shownAt = null;
      setVisible(next.visible);
      if (next.wakeIn != null) timer = setTimeout(look, next.wakeIn);
    };
    look();
    return () => clearTimeout(timer);
  }, [loading, delay, min]);
  return visible;
}
