import { backendBase } from "./nxApi.js";

// The Notes and Files apps' user side. Both call the same backend functions as the
// bot side (neyvia.notes.* / neyvia.files.*) through POST /api/ui/notes and
// /api/ui/files, so Paul and a model always see the same folders.

function base() {
  const source = globalThis.window?.__NEYVIA_UI_SOURCE__;
  return backendBase() || (typeof source === "string" && source.startsWith("http") ? source : "");
}

export async function docsCall(app, op, args = {}) {
  let response;
  try {
    response = await fetch(`${base()}/api/ui/${app}`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op, args }),
    });
  } catch {
    throw new Error("The PC service can't be reached.");
  }
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result?.ok === false) {
    throw Object.assign(new Error(result?.error || `${app} ${op} failed (HTTP ${response.status})`), { status: response.status, data: result?.data ?? null });
  }
  return result?.data ?? result;
}

export const notesCall = (op, args) => docsCall("notes", op, args);
export const filesCall = (op, args) => docsCall("files", op, args);
// Other PCs (cross-pc): the same functions as neyvia.devices.* (POST /api/ui/devices).
export const devicesCall = (op, args) => docsCall("devices", op, args);

/** Quick look bytes (images and PDFs) for a path on a paired PC, fetched through this PC. */
export function deviceRawUrl(device, path) {
  return `${base()}/api/ui/devices/raw?device=${encodeURIComponent(device)}&path=${encodeURIComponent(path)}`;
}

/** Quick look bytes (images and PDFs) for a path inside the Files places. */
export function rawUrl(path, absolute = false) {
  const url = `${base()}/api/ui/files/raw?path=${encodeURIComponent(path)}`;
  return absolute ? new URL(url, globalThis.location?.href).href : url;
}

export function formatSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return `${value >= 10 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

/** Insert dictated text at the caret with sensible spacing; returns the new text and caret. */
export function insertSpoken(text, caret, spoken) {
  const at = Math.max(0, Math.min(caret ?? text.length, text.length));
  const before = text.slice(0, at);
  const after = text.slice(at);
  const lead = before && !/\s$/.test(before) ? " " : "";
  const trail = after && !/^\s/.test(after) ? " " : "";
  const value = `${before}${lead}${spoken}${trail}${after}`;
  return { value, caret: before.length + lead.length + spoken.length };
}

export const parentOf = path => {
  const trimmed = String(path || "").replace(/[\\/]+$/, "");
  const at = Math.max(trimmed.lastIndexOf("\\"), trimmed.lastIndexOf("/"));
  return at > 0 ? trimmed.slice(0, at + (at === 2 && trimmed[1] === ":" ? 1 : 0)) : trimmed;
};
export const joinPath = (folder, name) => `${String(folder).replace(/[\\/]+$/, "")}${folder.includes("/") && !folder.includes("\\") ? "/" : "\\"}${name}`;
export const nameOf = path => String(path || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop();

/** Put text in the open chat's message box, or in a new chat's when none is open. */
export function sendToChat(text, { session, onNewChat, onShowChat, local }) {
  if (session?.id) {
    const key = `draft.${session.id}`;
    const current = String(local.get(key, "") || "").trimEnd();
    local.set(key, current ? `${current}\n\n${text}` : text);
    window.dispatchEvent(new CustomEvent("nx:compose", { detail: { sessionId: session.id } }));
    onShowChat?.();
    return "chat";
  }
  const current = String(local.get("draft.new", "") || "").trimEnd();
  local.set("draft.new", current ? `${current}\n\n${text}` : text);
  onNewChat?.();
  return "new";
}
