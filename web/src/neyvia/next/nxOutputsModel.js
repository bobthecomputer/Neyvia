import { checkedProofsEModel } from "./nxProofsEContracts.js";
// Pure helpers of the Outputs panel, the perception view and dragging the
// docked chat out (plan 15 T8, T18). No DOM or network: executable manual
// postconditions run before each public observer returns.

/** Pane targets of the perception view: "image:<path>", "file:<path>", "browser:<url>", "window:<sessionId>:<windowId>". */
function raw_parsePerceptionTarget(target) {
  const text = String(target || "");
  const at = text.indexOf(":");
  const kind = at > 0 ? text.slice(0, at) : "";
  const rest = at > 0 ? text.slice(at + 1) : "";
  if (kind === "image" || kind === "file") return rest ? { layer: kind, path: rest } : null;
  if (kind === "browser") return /^https?:\/\//i.test(rest) ? { layer: "browser", url: rest } : null;
  if (kind === "window") {
    const split = rest.lastIndexOf(":");
    const sessionId = split > 0 ? rest.slice(0, split) : "";
    const windowId = Number(rest.slice(split + 1));
    return sessionId && Number.isInteger(windowId) ? { layer: "window", sessionId, windowId } : null;
  }
  return null;
}

const raw_perceptionTarget = (layer, value, windowId) => (layer === "window" ? `window:${value}:${windowId}` : `${layer}:${value}`);

/** The layer an output is read as: images through the image observer, everything else as a file. */
export const layerForOutput = row => (row?.kind === "image" || String(row?.mediaType || "").startsWith("image/") ? "image" : "file");

/**
 * The value as indented plain text, close to what a model reads: keys, short
 * lists inline, nothing invented. Used for the "Readable" view.
 */
export function outline(value, depth = 0) {
  const pad = "  ".repeat(depth);
  if (value === null || value === undefined) return "—";
  if (typeof value !== "object") return String(value);
  if (Array.isArray(value)) {
    if (!value.length) return "(none)";
    if (value.every(item => item === null || typeof item !== "object")) return value.map(item => (item === null ? "—" : String(item))).join(", ");
    return value.map(item => `\n${pad}- ${outline(item, depth + 1).replace(/^\n\s*/, "")}`).join("");
  }
  const entries = Object.entries(value).filter(([, item]) => item !== undefined);
  if (!entries.length) return "(empty)";
  return entries.map(([key, item]) => {
    const inner = outline(item, depth + 1);
    return `\n${pad}${key}: ${inner.startsWith("\n") ? inner : inner}`;
  }).join("");
}

/** Rough token count of the text a model receives (about 4 characters per token). */
export const approxTokens = characters => Math.max(1, Math.round((Number(characters) || 0) / 4));


// ---- dragging the docked chat out to float (NxDockDrag) ----

const OUT_PX = 28; // how far past the dock's edge counts as "out"

/** Is this point outside the docked chat column (by a margin)? */
function raw_outsideDock(point, rect, margin = OUT_PX) {
  if (!rect) return false;
  return point.x < rect.left - margin || point.x > rect.right + margin || point.y < rect.top - margin || point.y > rect.bottom + margin;
}

/** Where a bubble dropped at a point lands: the nearer side, at that height (fractions of the window). */
function raw_dropSpot(point, width, height) {
  return { x: point.x < width / 2 ? 0 : 1, y: Math.min(1, Math.max(0, point.y / Math.max(1, height))) };
}


// Public observers check the executable manual claims on every invocation.
export function perceptionTarget(...args) { return checkedProofsEModel("outputs.perceptionTarget", args, raw_perceptionTarget(...args)); }
export function parsePerceptionTarget(...args) { return checkedProofsEModel("outputs.parsePerceptionTarget", args, raw_parsePerceptionTarget(...args)); }
export function outsideDock(...args) { return checkedProofsEModel("outputs.outsideDock", args, raw_outsideDock(...args)); }
export function dropSpot(...args) { return checkedProofsEModel("outputs.dropSpot", args, raw_dropSpot(...args)); }
