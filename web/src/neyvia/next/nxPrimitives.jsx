import { forwardRef, useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { m } from "motion/react";

import { SPRING } from "./nxSpring.js";

// Portals render outside the shell, so they copy its theme and look attributes.
function portalTheme() {
  return document.querySelector(".nx-root")?.getAttribute("data-nx-theme") || "dark";
}
export function portalLook() {
  const root = document.querySelector(".nx-root");
  return { "data-nx-font": root?.getAttribute("data-nx-font") || undefined, "data-nx-text": root?.getAttribute("data-nx-text") || undefined };
}

const TABBABLE = ":is(a[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), select:not([disabled]), textarea:not([disabled]), [tabindex]):not([tabindex='-1'])";

/**
 * Keep Tab inside a modal while it is open, and give focus back to what had it when it closes.
 * `ref` is the dialog element. Focus that starts outside (a click on the scrim) is pulled back in.
 */
export function useFocusTrap(ref, open) {
  useEffect(() => {
    if (!open) return undefined;
    const previous = document.activeElement;
    const onKey = event => {
      const box = ref.current;
      if (event.key !== "Tab" || !box) return;
      const items = [...box.querySelectorAll(TABBABLE)].filter(element => element.offsetParent !== null || element === document.activeElement);
      if (!items.length) { event.preventDefault(); box.focus?.(); return; }
      const first = items[0];
      const last = items[items.length - 1];
      const inside = box.contains(document.activeElement);
      if (event.shiftKey && (document.activeElement === first || !inside)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !inside)) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      if (previous && typeof previous.focus === "function" && document.contains(previous)) previous.focus();
    };
  }, [ref, open]);
}

// One icon family (lucide) at one weight everywhere in the new shell.
export function Icon({ as: Glyph, size = 16, className = "", ...rest }) {
  return <Glyph aria-hidden="true" className={`nx-icon ${className}`} size={size} strokeWidth={1.75} {...rest} />;
}

export const Button = forwardRef(function Button({ variant = "ghost", size = "md", icon, children, loading = false, disabled = false, className = "", ...rest }, ref) {
  return (
    <button ref={ref} type="button" className={`nx-btn nx-btn-${variant} nx-btn-${size} ${className}`} {...rest} disabled={disabled || loading} aria-busy={loading || rest["aria-busy"]}>
      {loading ? <Spinner size={size === "sm" ? 12 : 14} /> : icon ? <Icon as={icon} size={size === "sm" ? 14 : 16} /> : null}
      {children != null ? <span className="nx-btn-label">{children}</span> : null}
    </button>
  );
});

export const IconButton = forwardRef(function IconButton({ icon, label, size = "md", active = false, loading = false, disabled = false, className = "", children, ...rest }, ref) {
  return (
    <button ref={ref} type="button" aria-label={label} title={label} aria-pressed={active || undefined}
      className={`nx-iconbtn nx-iconbtn-${size}${active ? " is-active" : ""} ${className}`} {...rest} disabled={disabled || loading} aria-busy={loading || rest["aria-busy"]}>
      {loading ? <Spinner size={size === "sm" ? 12 : 14} /> : icon ? <Icon as={icon} size={size === "sm" ? 14 : 16} /> : null}
      {children}
    </button>
  );
});

export function Spinner({ size = 12, className = "" }) {
  return <span aria-hidden="true" className={`nx-spinner ${className}`} style={{ width: size, height: size }} />;
}

export function StatusDot({ tone = "idle", pulse = false }) {
  return <span aria-hidden="true" className={`nx-dot nx-dot-${tone}${pulse ? " is-pulse" : ""}`} />;
}

export function Kbd({ children }) {
  return <kbd className="nx-kbd">{children}</kbd>;
}

/** Radio groups have one Tab stop; arrows select and focus the next enabled choice. */
export function radioGroupKeys(event) {
  if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
  const items = [...event.currentTarget.querySelectorAll("[role=radio]:not([disabled]):not([aria-disabled=true])")];
  const index = items.indexOf(event.target);
  if (index < 0 || !items.length) return;
  event.preventDefault();
  const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1
    : (index + (["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : -1) + items.length) % items.length;
  items[next].focus();
  items[next].click();
}

export function Segmented({ value, options, onChange, label, size = "md", disabled = false }) {
  const enabled = options.filter(option => !option.disabled);
  const tabValue = enabled.some(option => option.value === value) ? value : enabled[0]?.value;
  const group = useId();
  return (
    <div role="radiogroup" aria-label={label} className={`nx-seg nx-seg-${size}`} onKeyDown={radioGroupKeys}>
      {options.map(option => (
        <button key={option.value} type="button" role="radio" aria-checked={value === option.value} disabled={disabled || option.disabled} tabIndex={!disabled && tabValue === option.value ? 0 : -1}
          className={value === option.value ? "is-on" : ""} onClick={() => onChange(option.value)}>
          {/* The selection slides to the new choice on a spring (none with reduced motion). */}
          {value === option.value ? <m.span layoutId={`nx-seg-${group}`} className="nx-seg-pill" transition={SPRING.snappy} aria-hidden="true" /> : null}
          <span className="nx-seg-label">{option.label}</span>{option.count ? <span className="nx-seg-count">{option.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

/** Anchored popover with outside-click, Escape, and focus return. */
export function Popover({ anchor, open, onClose, placement = "top-start", width, className = "", children, label }) {
  const panel = useRef(null);
  const focused = useRef(false);
  const [position, setPosition] = useState(null);

  useLayoutEffect(() => {
    if (!open) { focused.current = false; return; }
    // A hidden panel cannot receive focus. Wait for its measured placement.
    if (!position || focused.current) return;
    panel.current?.querySelector("[data-autofocus], [role=menuitem], [role=option], button, input")?.focus();
    focused.current = true;
  }, [open, position]);

  useLayoutEffect(() => {
    if (!open || !anchor?.current) return;
    const place = () => {
      const rect = anchor.current.getBoundingClientRect();
      const panelRect = panel.current?.getBoundingClientRect();
      const height = panelRect?.height || 0;
      const panelWidth = width || panelRect?.width || 260;
      const margin = 8;
      let left = placement.endsWith("end") ? rect.right - panelWidth : rect.left;
      left = Math.max(margin, Math.min(left, window.innerWidth - panelWidth - margin));
      const above = rect.top - height - 6;
      const below = rect.bottom + 6;
      const preferTop = placement.startsWith("top");
      let top = preferTop ? (above >= margin ? above : below) : (below + height <= window.innerHeight - margin ? below : above);
      top = Math.max(margin, Math.min(top, window.innerHeight - height - margin));
      setPosition({ left, top });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    // Content that loads after opening (a dashboard, a list) changes the height: keep it in view.
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(place) : null;
    if (observer && panel.current) observer.observe(panel.current);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      observer?.disconnect();
    };
  }, [open, anchor, placement, width]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = event => { if (event.key === "Escape") { event.stopPropagation(); onClose(); anchor?.current?.focus(); } };
    const onDown = event => {
      if (panel.current?.contains(event.target) || anchor?.current?.contains(event.target)) return;
      onClose();
    };
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onDown, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onDown, true);
    };
  }, [open, onClose, anchor]);

  if (!open) return null;
  return createPortal(
    <div className="nx nx-portal-host" data-nx-theme={portalTheme()} {...portalLook()}>
      <div ref={panel} role="dialog" aria-label={label} className={`nx-pop ${className}`}
        style={{ width, left: position?.left ?? -9999, top: position?.top ?? -9999, visibility: position ? "visible" : "hidden" }}>
        {children}
      </div>
    </div>,
    document.body,
  );
}

/** Arrow-key navigation for a list of role=option / menuitem buttons. */
export function useRovingKeys(containerRef) {
  return useCallback(event => {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    const items = [...(containerRef.current?.querySelectorAll("[role=option]:not([aria-disabled=true]), [role=menuitem]:not([aria-disabled=true]), [data-roving]") || [])];
    if (!items.length) return;
    event.preventDefault();
    const index = items.indexOf(document.activeElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1
      : event.key === "ArrowDown" ? (index + 1) % items.length : (index - 1 + items.length) % items.length;
    items[next].focus();
  }, [containerRef]);
}

/** Bottom sheet for phone-sized screens. */
export function Sheet({ open, onClose, title, label, children }) {
  const box = useRef(null);
  useFocusTrap(box, open);
  useEffect(() => { if (open) requestAnimationFrame(() => box.current?.querySelector(TABBABLE)?.focus()); }, [open]);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = event => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(
    <div className="nx nx-portal-host" data-nx-theme={portalTheme()} {...portalLook()}>
      <div className="nx-sheet-backdrop" onClick={onClose} />
      <div ref={box} role="dialog" aria-modal="true" aria-label={title || label} className="nx-sheet">
        <div className="nx-sheet-grip" aria-hidden="true" />
        {title ? <header className="nx-sheet-head"><strong>{title}</strong></header> : null}
        <div className="nx-sheet-body nx-scroll">{children}</div>
      </div>
    </div>,
    document.body,
  );
}

export function useMedia(query) {
  const get = () => typeof window !== "undefined" && window.matchMedia(query).matches;
  const [matches, setMatches] = useState(get);
  useEffect(() => {
    const media = window.matchMedia(query);
    const onChange = () => setMatches(media.matches);
    media.addEventListener("change", onChange);
    onChange();
    return () => media.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

const UNITS = [["y", 31536000], ["mo", 2592000], ["d", 86400], ["h", 3600], ["m", 60]];
export function ago(value, now = Date.now()) {
  const time = value ? Date.parse(value) : NaN;
  if (!Number.isFinite(time)) return "";
  const seconds = Math.max(0, Math.round((now - time) / 1000));
  if (seconds < 45) return "now";
  for (const [unit, size] of UNITS) if (seconds >= size) return `${Math.floor(seconds / size)}${unit}`;
  return "1m";
}

export function elapsed(since, now = Date.now()) {
  const time = since ? Date.parse(since) : NaN;
  if (!Number.isFinite(time)) return "";
  const seconds = Math.max(0, Math.round((now - time) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

/** Re-render every `ms` while `active`, for live "Working 3m" clocks. */
export function useTick(active, ms = 1000) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return undefined;
    const timer = setInterval(() => { if (!document.hidden) setTick(value => value + 1); }, ms);
    return () => clearInterval(timer);
  }, [active, ms]);
}

export function compactTokens(value) {
  if (value == null || !Number.isFinite(Number(value))) return "";
  const number = Number(value);
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(number >= 10_000_000 ? 0 : 1).replace(/\.0$/, "")}M`;
  if (number >= 1000) return `${Math.round(number / 1000)}k`;
  return String(number);
}

/** Per-viewer UI memory (drafts, collapsed sections). Never required state. */
export const local = {
  get(key, fallback) {
    try { const raw = localStorage.getItem(`nx.${key}`); return raw == null ? fallback : JSON.parse(raw); } catch { return fallback; }
  },
  set(key, value) {
    try { if (value == null || value === "") localStorage.removeItem(`nx.${key}`); else localStorage.setItem(`nx.${key}`, JSON.stringify(value)); } catch { /* Private mode: memory is best effort. */ }
  },
};
