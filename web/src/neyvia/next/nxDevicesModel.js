import { checkedProofsEModel } from "./nxProofsEContracts.js";
// Other PCs (cross-pc): pure helpers shared by the Files app and Accounts.
// No DOM or network effects; public observers enforce the manual postconditions.

export const LOCAL_DRAG = "application/x-neyvia-path"; // a path on this PC (the Files app's own drag type)
export const REMOTE_DRAG = "application/x-neyvia-remote"; // JSON {device, path, name} on another PC

/** What a drop does: "move" inside this PC, "take" from another PC, "send" to another PC, or null. */
function raw_dropIntent(source, target) {
  if (!source?.path || !target) return null;
  const from = source.device || null;
  const to = target.device || null;
  if (!from && !to) return "move";
  if (from && !to) return "take";
  if (!from && to) return "send";
  return null; // PC to PC directly isn't supported; take it here first
}

/** Read a drag's source from a DataTransfer (local path or remote JSON). */
export function dragSource(dataTransfer) {
  const remote = dataTransfer.getData(REMOTE_DRAG);
  if (remote) {
    try {
      const value = JSON.parse(remote);
      if (value?.device && value?.path) return { device: String(value.device), path: String(value.path), name: String(value.name || "") };
    } catch { /* not ours */ }
    return null;
  }
  const path = dataTransfer.getData(LOCAL_DRAG);
  return path ? { device: null, path } : null;
}

export const hasDrag = (dataTransfer, ...types) => types.some(type => dataTransfer.types.includes(type));

export const ACTIVE = new Set(["queued", "running", "verifying", "paused"]);
export const isActive = transfer => ACTIVE.has(transfer?.status);

function size(bytes) {
  if (bytes == null || !Number.isFinite(Number(bytes))) return "";
  const value = Number(bytes);
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let scaled = value / 1024;
  let unit = 0;
  while (scaled >= 1024 && unit < units.length - 1) { scaled /= 1024; unit += 1; }
  return `${scaled >= 10 ? Math.round(scaled) : scaled.toFixed(1)} ${units[unit]}`;
}

function duration(seconds) {
  if (!(seconds > 0) || !Number.isFinite(seconds)) return "";
  if (seconds < 60) return "less than a minute";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `about ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return `about ${hours} h${rest ? ` ${rest} min` : ""}`;
}

/** 0..1, or null while the size is unknown. */
function raw_transferFraction(transfer) {
  const total = Number(transfer?.size);
  if (!(total > 0)) return transfer?.status === "done" ? 1 : null;
  return Math.max(0, Math.min(1, Number(transfer.done || 0) / total));
}

/** One short line under a transfer's name. */
function raw_transferLine(transfer) {
  if (!transfer) return "";
  const { status, done = 0, size: total, bytesPerSecond: speed, files, error } = transfer;
  const count = files?.total > 1 ? ` · ${files.done || 0} of ${files.total} files` : "";
  if (status === "done") return `Done · ${size(total ?? done)}${files?.total > 1 ? ` · ${files.total} files` : ""} · checked`;
  if (status === "failed") return error ? `Stopped: ${error}` : "Stopped";
  if (status === "cancelled") return "Cancelled";
  if (status === "queued") return "Waiting to start";
  if (status === "verifying") return `Checking the copy${count}`;
  const progress = total > 0 ? `${size(done)} of ${size(total)}` : size(done);
  if (status === "paused") return `Paused at ${progress}${count}`;
  const left = total > 0 && speed > 0 ? duration((total - done) / speed) : "";
  return [progress + count, speed > 0 ? `${size(speed)}/s` : "", left ? `${left} left` : ""].filter(Boolean).join(" · ");
}

/** Plain words for a device's state. */
export function deviceStatusText(device) {
  switch (device?.status) {
    case "paired": return device.online ? "Paired · online" : "Paired · offline right now";
    case "waiting": return "Waiting for its owner to approve";
    case "asked-you": return "Wants to reach this PC's files";
    case "available": return "Neyvia is running there · not paired";
    case "not-neyvia": return "Online, but Neyvia isn't running there";
    case "offline": return "Offline";
    default: return "";
  }
}

/** Where a send to `device` lands when dropped in `folder` (null = its inbox). */
function raw_sendTarget(device, place, folder) {
  if (!folder) return null;
  const share = device?.theyShare;
  if (place?.kind === "inbox" || place?.write || share?.writeAnywhere) return folder;
  return null;
}

/** The Files app target for another PC's folder: "pc:<id>" or "pc:<id>|<path>". */
function raw_pcTarget(device, path = "") {
  return `pc:${device}${path ? `|${path}` : ""}`;
}

function raw_parsePcTarget(target) {
  const text = String(target || "");
  if (!text.startsWith("pc:")) return null;
  const [device, ...rest] = text.slice(3).split("|");
  return device ? { device, path: rest.join("|") || null } : null;
}

/** Folder names shared, for one line of text. */
export function shareSummary(share) {
  if (!share) return "Nothing yet";
  const folders = (share.folders || []).map(folder => `${folder.name || folder.path}${folder.write ? " (can save)" : ""}`);
  return folders.length ? folders.join(", ") : "No folders";
}

// Public observers check the executable manual claims on every invocation.
export function dropIntent(...args) { return checkedProofsEModel("devices.dropIntent", args, raw_dropIntent(...args)); }
export function sendTarget(...args) { return checkedProofsEModel("devices.sendTarget", args, raw_sendTarget(...args)); }
export function transferFraction(...args) { return checkedProofsEModel("devices.transferFraction", args, raw_transferFraction(...args)); }
export function transferLine(...args) { return checkedProofsEModel("devices.transferLine", args, raw_transferLine(...args)); }
export function pcTarget(...args) { return checkedProofsEModel("devices.pcTarget", args, raw_pcTarget(...args)); }
export function parsePcTarget(...args) { return checkedProofsEModel("devices.parsePcTarget", args, raw_parsePcTarget(...args)); }
