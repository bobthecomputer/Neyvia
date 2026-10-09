import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
/**
 * Neyvia motion preference wiring.
 * Settings "Reduce motion" sets data attributes; CSS also honors prefers-reduced-motion.
 */

export const NEYVIA_REDUCE_MOTION_ATTR = "data-neyvia-reduce-motion";
export const NEYVIA_REDUCE_MOTION_FALLBACK_ATTR = "data-reduce-motion";

/**
 * Apply user reduce-motion preference to document + shell roots.
 * Does not override OS prefers-reduced-motion (CSS handles that separately).
 */
export function applyNeyviaReduceMotion(reduceMotion, root = typeof document !== "undefined" ? document.documentElement : null) {
  if (!root) return false;
  const value = reduceMotion ? "true" : "false";
  root.setAttribute(NEYVIA_REDUCE_MOTION_ATTR, value);
  root.setAttribute(NEYVIA_REDUCE_MOTION_FALLBACK_ATTR, value);
  root.classList.toggle("neyvia-reduce-motion", Boolean(reduceMotion));

  if (typeof document !== "undefined") {
    document.querySelectorAll(".fluxos-shell, .fluxio-shell, .reference-shell").forEach(node => {
      node.setAttribute(NEYVIA_REDUCE_MOTION_ATTR, value);
      node.setAttribute(NEYVIA_REDUCE_MOTION_FALLBACK_ATTR, value);
    });
  }
  return Boolean(reduceMotion);
}

/** True when the Settings toggle is on or the OS requests reduced motion. */
export function isNeyviaMotionReduced(preferences = {}) {
  if (preferences?.reduceMotion) return true;
  if (typeof window !== "undefined" && window.matchMedia) {
    try {
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch {
      return false;
    }
  }
  return false;
}

/** CSS custom properties for purposeful Neyvia motion (consumed by neyviaMotion.css). */
function neyviaMotionCssVariablesUnchecked(preferences = {}) {
  const reduced = Boolean(preferences?.reduceMotion);
  const effectIntensity = ["off", "subtle", "balanced", "vivid"].includes(preferences?.effectIntensity)
    ? preferences.effectIntensity
    : "balanced";
  const transparencyLevel = ["solid", "soft", "glass"].includes(preferences?.transparencyLevel)
    ? preferences.transparencyLevel
    : "soft";
  const effect = {
    off: { fast: 0, med: 0, slow: 0, pulse: 0, lift: 0, shadow: 0 },
    subtle: { fast: 120, med: 170, slow: 240, pulse: 1.8, lift: 4, shadow: 0.24 },
    balanced: { fast: 160, med: 220, slow: 320, pulse: 1.35, lift: 8, shadow: 0.35 },
    vivid: { fast: 180, med: 260, slow: 380, pulse: 1.1, lift: 12, shadow: 0.45 },
  }[effectIntensity];
  const transparency = {
    solid: { opacity: "100%", blur: "0px" },
    soft: { opacity: "97%", blur: "6px" },
    glass: { opacity: "92%", blur: "12px" },
  }[transparencyLevel];
  return {
    "--neyvia-motion-fast": reduced ? "0ms" : `${effect.fast}ms`,
    "--neyvia-motion-med": reduced ? "0ms" : `${effect.med}ms`,
    "--neyvia-motion-slow": reduced ? "0ms" : `${effect.slow}ms`,
    "--neyvia-motion-pulse": reduced || effect.pulse === 0 ? "0ms" : `${effect.pulse}s`,
    "--neyvia-effect-lift": reduced ? "0px" : `${effect.lift}px`,
    "--neyvia-effect-shadow-alpha": String(effect.shadow),
    "--neyvia-surface-opacity": transparency.opacity,
    "--neyvia-surface-blur": transparency.blur,
    "--neyvia-motion-spring": "cubic-bezier(0.22, 1, 0.36, 1)",
    "--neyvia-motion-ease-out": "cubic-bezier(0.16, 1, 0.3, 1)",
  };
}

/** App icon paths for Settings / Library / about chrome. */
export { NEYVIA_APP_ICON_PATHS } from "./neyviaToolVisuals.js";

/**
 * Data attributes for panel / tool motion hooks (pair with neyviaMotion.css).
 * @param {string} [target]
 * @param {Record<string, string|boolean|undefined>} [extra]
 */
export function neyviaMotionTargetAttrs(target = "", extra = {}) {
  const attrs = { "data-neyvia-motion-target": target || undefined };
  for (const [key, value] of Object.entries(extra || {})) {
    if (value === undefined || value === false) continue;
    attrs[key] = value === true ? "true" : String(value);
  }
  return attrs;
}

export function neyviaMotionCssVariables(...args) {
  const before = frontendContractBefore("preferences.motion", args);
  return checkedFrontendAction("preferences.motion", args, neyviaMotionCssVariablesUnchecked(...args), before);
}
