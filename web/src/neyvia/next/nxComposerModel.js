import { checkedProofsEModel } from "./nxProofsEContracts.js";
// Pure rules behind the composer's + menu: image limits, which route can take
// images, the retry identity of a send, and how a Neyvia tool is labelled.

// Mirrors the backend's limits (connected_sessions/broker.py) so a refusal is
// explained before the bytes travel.
export const MAX_IMAGES = 6;
export const MAX_IMAGE_CHARS = 12 * 1024 * 1024;
export const MAX_IMAGES_TOTAL_CHARS = 24 * 1024 * 1024;
export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];

/** Base64 payload of a data URL, without the `data:...;base64,` prefix. */
function raw_stripDataUrl(dataUrl) {
  const comma = String(dataUrl || "").indexOf(",");
  return comma < 0 ? "" : dataUrl.slice(comma + 1);
}

/** Which new images fit next to the ones already attached, and why the rest don't. */
function raw_admitImages(current, incoming) {
  const accepted = [];
  const refused = [];
  let total = current.reduce((sum, image) => sum + image.data.length, 0);
  for (const image of incoming) {
    if (!IMAGE_TYPES.includes(image.mime)) refused.push(`${image.name || "That file"} isn't a PNG, JPEG, WebP or GIF image.`);
    else if (current.length + accepted.length >= MAX_IMAGES) refused.push(`At most ${MAX_IMAGES} images go with one message.`);
    else if (image.data.length > MAX_IMAGE_CHARS) refused.push(`${image.name || "That image"} is larger than about 9 MB.`);
    else if (total + image.data.length > MAX_IMAGES_TOTAL_CHARS) refused.push("The images together would be larger than about 18 MB.");
    else { accepted.push(image); total += image.data.length; }
  }
  return { accepted, refused: [...new Set(refused)] };
}

/** Base64 length of a file of `bytes` bytes. */
const raw_base64Chars = bytes => 4 * Math.ceil(Math.max(0, Number(bytes) || 0) / 3);

/**
 * Decide from file metadata alone (type, size) which files are worth reading,
 * so an unsupported or oversized drop never reaches FileReader. Uses the same
 * limits as admitImages, on the base64 size each file would become.
 */
function raw_planImageReads(current, files) {
  const read = [];
  const refused = [];
  let total = current.reduce((sum, image) => sum + image.data.length, 0);
  for (const file of files) {
    const size = base64Chars(file.size);
    if (!IMAGE_TYPES.includes(file.type)) refused.push(`${file.name || "That file"} isn't a PNG, JPEG, WebP or GIF image.`);
    else if (current.length + read.length >= MAX_IMAGES) refused.push(`At most ${MAX_IMAGES} images go with one message.`);
    else if (size > MAX_IMAGE_CHARS) refused.push(`${file.name || "That image"} is larger than about 9 MB.`);
    else if (total + size > MAX_IMAGES_TOTAL_CHARS) refused.push("The images together would be larger than about 18 MB.");
    else { read.push(file); total += size; }
  }
  return { read, refused: [...new Set(refused)] };
}

/**
 * In-memory image drafts keyed by chat. Every write names its chat, so an
 * attachment that finishes reading after the person moved on lands in the
 * chat it was dropped on, never in the one now on screen.
 */
const NO_IMAGES = Object.freeze([]);  // one stable empty value, so a subscribed view doesn't re-render forever
export function createDraftStore() {
  const drafts = new Map();
  const listeners = new Set();
  const store = {
    get: id => drafts.get(id) || NO_IMAGES,
    update(id, next) {
      const before = [...drafts];
      const current = drafts.get(id) || NO_IMAGES;
      const value = typeof next === "function" ? next(current) : next;
      if (value === current) return value;
      if (value.length) drafts.set(id, value); else drafts.delete(id);
      checkedProofsEModel("composer.draftUpdate", [id, current, before, value, store, NO_IMAGES], value);
      for (const listener of listeners) listener(id);
      return value;
    },
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
  };
  return store;
}

/**
 * Attach files to the draft of the chat they were added in. Type, count and
 * size are checked from metadata before `read` sees a byte; the read images
 * are checked again against the draft as it is when they arrive. Returns the
 * explanation for anything refused ("" when all fit).
 */
export async function attachToDraft(store, sessionId, files, read) {
  const { read: worth, refused } = planImageReads(store.get(sessionId), [...(files || [])]);
  if (!worth.length) return checkedProofsEModel("composer.attachResult", [sessionId, store], refused.join(" "));
  let images;
  try { images = await read(worth); } catch (failure) { return checkedProofsEModel("composer.attachResult", [sessionId, store], [...refused, failure?.message || "The image couldn't be read."].join(" ")); }
  let late = [];
  store.update(sessionId, current => {
    const { accepted, refused: over } = admitImages(current, images);
    late = over;
    return accepted.length ? [...current, ...accepted] : current;
  });
  return checkedProofsEModel("composer.attachResult", [sessionId, store], [...new Set([...refused, ...late])].join(" "));
}

/**
 * Whether this chat's chosen route can carry images. Returns null when it can,
 * otherwise a plain reason; `switchTo` names a route the person may pick instead.
 */
function raw_imageBlocker({ app, appName, capabilities, transport, transports, model }) {
  if (!capabilities?.images) return { reason: `${appName || "This app"} chats from Neyvia can't carry images yet.` };
  // Plan limits (Claude Code's terminal) takes images too: the PC saves them and names their paths.
  if (model && model.images === false) return { reason: `${model.label || model.id} doesn't accept images. Pick another model to send them.` };
  return null;
}

// FNV-1a over the whole string: cheap enough for a few MB, stable across retries.
function digest(text) {
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(36);
}

function stable(value) {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().filter(key => value[key] !== undefined).map(key => `${JSON.stringify(key)}:${stable(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value ?? null);
}

/**
 * What makes two sends "the same request". An exact retry keeps its request ID
 * (so the backend can deduplicate it); a changed model, route or image does not.
 * Image bytes are folded into a short digest so the key stays small.
 */
function raw_sendIdentity(scope, message, options = {}) {
  const images = (options.images || []).map(image => ({ mime: image.mime, name: image.name || "", size: image.data.length, digest: digest(image.data) }));
  return `${scope}\0${message}\0${stable({ ...options, images })}`;
}

// --- Neyvia's own tools -------------------------------------------------------

/** "read" tools only look; everything else may change something. */
const raw_toolMutates = tool => String(tool?.mutability_class || "read") !== "read";

/** neyvia.* tools are the UI's own actions and go through /api/ui/tools/call. */
export const isUiTool = name => String(name || "").startsWith("neyvia.");

const EXAMPLE = { string: "", integer: 0, number: 0, boolean: false, array: [], object: {} };

/** A starting argument object with the schema's required fields filled with empty values. */
function raw_argumentSkeleton(schema) {
  const properties = schema?.properties || {};
  const out = {};
  for (const name of schema?.required || []) {
    const field = properties[name] || {};
    out[name] = field.enum?.length ? field.enum[0] : field.default ?? EXAMPLE[field.type] ?? "";
  }
  return JSON.stringify(out, null, 2);
}

/** Parse the arguments box; a tool takes a JSON object and nothing else. */
function raw_parseArguments(text) {
  const source = String(text || "").trim() || "{}";
  try {
    const value = JSON.parse(source);
    if (!value || typeof value !== "object" || Array.isArray(value)) return { error: "Arguments must be a JSON object, like {\"query\": \"…\"}." };
    return { value };
  } catch (failure) {
    return { error: `That isn't valid JSON: ${failure.message}` };
  }
}

/** Filter the catalog by a typed query over name, category and description. */
function raw_filterTools(tools, query) {
  const terms = String(query || "").toLowerCase().split(/\s+/).filter(Boolean);
  return (tools || [])
    .filter(tool => {
      const haystack = `${tool.name} ${tool.category || ""} ${tool.description || ""} ${(tool.aliases || []).join(" ")}`.toLowerCase();
      return terms.every(term => haystack.includes(term));
    })
    .sort((a, b) => Number(b.available) - Number(a.available) || a.name.localeCompare(b.name));
}

/** Where a manual call actually runs, said plainly. */
function raw_toolScope({ tool, cwd, desktop }) {
  if (isUiTool(tool)) return { root: null, label: "Runs in Neyvia's own workspace (sidebar, projects, sessions), not in this chat's folder." };
  if (desktop) return { root: cwd || null, label: "The desktop app runs a short list of Neyvia tools in Neyvia's own state folder, not in this chat's folder." };
  if (cwd) return { root: cwd, label: `Runs in this chat's folder: ${cwd}` };
  return { root: null, label: "This chat has no folder, so the tool runs in Neyvia's own state folder." };
}

// Public observers check the executable manual claims on every invocation.
export function stripDataUrl(...args) { return checkedProofsEModel("composer.stripDataUrl", args, raw_stripDataUrl(...args)); }
export function admitImages(...args) { return checkedProofsEModel("composer.admitImages", args, raw_admitImages(...args)); }
export function base64Chars(...args) { return checkedProofsEModel("composer.base64Chars", args, raw_base64Chars(...args)); }
export function planImageReads(...args) { return checkedProofsEModel("composer.planImageReads", args, raw_planImageReads(...args)); }
export function imageBlocker(...args) { return checkedProofsEModel("composer.imageBlocker", args, raw_imageBlocker(...args)); }
export function sendIdentity(...args) { return checkedProofsEModel("composer.sendIdentity", args, raw_sendIdentity(...args)); }
export function toolMutates(...args) { return checkedProofsEModel("composer.toolMutates", args, raw_toolMutates(...args)); }
export function argumentSkeleton(...args) { return checkedProofsEModel("composer.argumentSkeleton", args, raw_argumentSkeleton(...args)); }
export function parseArguments(...args) { return checkedProofsEModel("composer.parseArguments", args, raw_parseArguments(...args)); }
export function filterTools(...args) { return checkedProofsEModel("composer.filterTools", args, raw_filterTools(...args)); }
export function toolScope(...args) { return checkedProofsEModel("composer.toolScope", args, raw_toolScope(...args)); }
