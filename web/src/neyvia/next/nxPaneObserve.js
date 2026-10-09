// Renderer observations for pane.show (plans/15-handoff.md "## FIXCL renderer").
// A pane.show event that asks for observation is acknowledged by the pane that
// actually mounted, once its real content is on screen, never by the bus on
// delivery: POST /api/ui/ack {id, ok, clientId, observation:{paneId, runtimeId,
// kind, target, contentHash, mounted, visible}}. These helpers are pure so the
// node tests and the pane share them.

export const HEARTBEAT_MS = 4000; // the backend wants a fresh report at least every 5 s while visible
export const SETTLE_MS = 350; // a DOM projection is read once the pane has been quiet this long

const HEX = /^[0-9a-f]{64}$/;

/** The text a file pane displays, normalized the way the backend reads the file (LF, no BOM). */
export function normalizeText(value) {
  return String(value ?? "").replace(/^﻿/, "").replace(/\r\n?/g, "\n");
}

/** Whitespace-stable text of a DOM projection (innerText differs in spacing between engines). */
export function projectText(value) {
  return String(value ?? "").replace(/ /g, " ").split("\n").map(line => line.replace(/\s+/g, " ").trim()).filter(Boolean).join("\n");
}

/** Lowercase SHA-256 of UTF-8 text: WebCrypto where it exists, a small pure implementation elsewhere. */
export async function sha256Hex(text) {
  const bytes = new TextEncoder().encode(String(text ?? ""));
  const subtle = globalThis.crypto?.subtle;
  if (subtle) {
    try {
      const digest = new Uint8Array(await subtle.digest("SHA-256", bytes));
      return Array.from(digest, byte => byte.toString(16).padStart(2, "0")).join("");
    } catch { /* not a secure context: fall through */ }
  }
  return sha256Fallback(bytes);
}

const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

export function sha256Fallback(bytes) {
  const length = bytes.length;
  const padded = new Uint8Array(((length + 9 + 63) >> 6) << 6);
  padded.set(bytes);
  padded[length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(padded.length - 8, Math.floor(length / 0x20000000));
  view.setUint32(padded.length - 4, (length << 3) >>> 0);
  const h = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
  const w = new Uint32Array(64);
  const rotr = (x, n) => (x >>> n) | (x << (32 - n));
  for (let offset = 0; offset < padded.length; offset += 64) {
    for (let i = 0; i < 16; i += 1) w[i] = view.getUint32(offset + i * 4);
    for (let i = 16; i < 64; i += 1) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, hh] = h;
    for (let i = 0; i < 64; i += 1) {
      const t1 = (hh + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i]) >>> 0;
      const t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
      hh = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
  }
  return Array.from(h, word => word.toString(16).padStart(8, "0")).join("");
}

/** The pane.show request a stage carries, or null when nobody asked for an observation. */
export function paneRequest(eventId, payload) {
  if (!payload || payload.observationRequired !== true || !eventId || !payload.paneId) return null;
  return {
    eventId: String(eventId),
    paneId: String(payload.paneId),
    kind: String(payload.kind ?? ""),
    target: String(payload.target ?? ""),
    expectedContentHash: typeof payload.expectedContentHash === "string" ? payload.expectedContentHash : null,
  };
}

/** Is a report complete enough to send as an observation (never a placeholder)? */
export function reportReady(report) {
  return Boolean(report && typeof report.runtimeId === "string" && report.runtimeId.trim() && report.runtimeId.length <= 128
    && HEX.test(report.contentHash || "") && report.empty !== true);
}

/**
 * The ack body for one state of a mounted pane.
 *   state: { failure?, report?: {runtimeId, contentHash}, mounted, visible }
 * Returns null when there is nothing honest to send yet (still loading).
 */
export function ackBody(request, state, clientId) {
  if (!request) return null;
  if (state.failure) return { id: request.eventId, ok: false, error: String(state.failure).slice(0, 900), clientId };
  if (!reportReady(state.report)) {
    // Gone before it ever showed real content: say so, never invent a hash.
    return state.mounted === false ? { id: request.eventId, ok: false, error: "The pane closed before its content loaded", clientId } : null;
  }
  return {
    id: request.eventId, ok: true, clientId,
    observation: {
      paneId: request.paneId, runtimeId: state.report.runtimeId, kind: request.kind, target: request.target,
      contentHash: state.report.contentHash, mounted: state.mounted !== false, visible: state.mounted !== false && state.visible === true,
    },
  };
}

/** Same observation as the last one sent (heartbeats resend it anyway). */
export const sameAck = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/** Is this element really on screen in this document (not hidden, not detached, page visible)? */
export function elementVisible(element) {
  if (!element?.isConnected) return false;
  if (globalThis.document?.visibilityState === "hidden") return false;
  if (typeof element.checkVisibility === "function") return element.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true });
  for (let node = element; node && node.nodeType === 1; node = node.parentElement) {
    if (node.hidden) return false;
    const style = globalThis.getComputedStyle?.(node);
    if (style && (style.display === "none" || style.visibility === "hidden")) return false;
  }
  return true;
}

/** A loading veil or busy region inside the pane: its text is not the pane's content yet. */
export function elementBusy(element) {
  return Boolean(element?.querySelector?.(".nx-stage-loading, [aria-busy='true'], .nx-tp-veil, .nx-br-center .nx-spinner"));
}
