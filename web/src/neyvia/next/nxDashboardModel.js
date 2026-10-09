import { checkedProofsEModel } from "./nxProofsEContracts.js";
// Pure helpers for the agents dashboard (NxAgentDashboard.jsx).

export const WORKING = new Set(["working", "waiting_approval", "waiting_input"]);

/** "in 3h 12m", "in 2d 4h", "now"; empty when the app gave no reset time. */
function raw_resetsIn(iso, now = Date.now()) {
  const time = iso ? Date.parse(iso) : NaN;
  if (!Number.isFinite(time)) return "";
  const minutes = Math.round((time - now) / 60000);
  if (minutes <= 0) return "now";
  if (minutes < 60) return `in ${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `in ${hours}h${minutes % 60 ? ` ${minutes % 60}m` : ""}`;
  return `in ${Math.floor(hours / 24)}d${hours % 24 ? ` ${hours % 24}h` : ""}`;
}

/** How worried to look: the app's own warning first, then the share used. */
function raw_limitTone(limit) {
  if (!limit) return "idle";
  if (limit.stale || limit.availability === "unavailable") return "idle";
  if (limit.status === "rejected") return "red";
  const used = limitPercent(limit);
  if (used === null && limit.status !== "allowed_warning") return "idle";
  if (Number.isFinite(used) && used >= 90) return "red";
  if (limit.status === "allowed_warning" || (Number.isFinite(used) && used >= 75)) return "caution";
  return "green";
}

/** Limits grouped per app, in a fixed order; apps that reported nothing get an empty group. */
export function limitsByApp(limits = [], apps = ["claude-code", "codex", "opencode"]) {
  const groups = apps.map(app => ({ app, rows: [] }));
  for (const limit of limits) {
    let group = groups.find(entry => entry.app === limit.app);
    if (!group) { group = { app: limit.app, rows: [] }; groups.push(group); }
    group.rows.push(limit);
  }
  return groups;
}

/** Missing percentages must never become a reassuring 0% meter. */
export function limitPercent(limit) {
  const value = limit?.usedPercent;
  if (value == null || value === "") return null;
  const percent = Number(value);
  return Number.isFinite(percent) ? percent : null;
}

export function providerStatus(provider, rows = []) {
  const at = provider?.checkedAt || rows.find(row => row.at)?.at;
  const checked = at ? ` · ${new Date(at).toLocaleTimeString()}` : "";
  if (provider?.refreshing) return "Refreshing…";
  if (provider?.status === "error") return `${rows.length ? "Refresh failed · last known" : "Could not read limits"}${checked}`;
  if (provider?.status === "unavailable") return `${rows.length ? "Unavailable · last known" : "Limits unavailable"}${checked}`;
  if (rows.some(row => row.stale)) return `Last known · stale${checked}`;
  return at ? `Checked ${new Date(at).toLocaleTimeString()}` : "Not checked yet";
}

/** Until the backend answers (or on one without the dashboard), the chat list's own working rows. */
export function fallbackSessions(rows = []) {
  return rows.filter(row => !row.archived && WORKING.has(row.status)).map(row => ({
    id: row.id, app: row.app, category: row.category, runtime: row.runtime, title: row.title || "Untitled chat",
    status: row.status, since: row.status_since, now: null, plan: null, tokens: null, subagents: [], fallback: true,
  }));
}

/** One line for what a chat is doing, from the dashboard row. */
export function nowText(row) {
  if (row?.now?.text) return row.now.text;
  if (row?.plan?.next) return `Next: ${row.plan.next}`;
  if (row?.status === "waiting_approval") return "Waiting for your approval";
  if (row?.status === "waiting_input") return "Waiting for your answer";
  return "";
}

export const DASH_PAGE = 16;

/**
 * Pages of running chats read one after another, merged into one list. A chat can move
 * between pages while they are read (its status changed); it shows once, where it was seen first.
 */
function raw_mergePages(pages = []) {
  const seen = new Set();
  const sessions = [];
  for (const page of pages) {
    for (const row of page?.sessions || []) {
      if (!row?.id || seen.has(row.id)) continue;
      seen.add(row.id);
      sessions.push(row);
    }
  }
  const last = pages[pages.length - 1] || {};
  const first = pages[0] || {};
  const total = Number.isFinite(last.total) ? last.total : sessions.length;
  return { ...first, sessions, total, nextOffset: last.nextOffset ?? null, hasMore: Boolean(last.hasMore ?? last.nextOffset != null) };
}

// Public observers check the executable manual claims on every invocation.
export function resetsIn(...args) { return checkedProofsEModel("dashboard.resetsIn", args, raw_resetsIn(...args)); }
export function limitTone(...args) { return checkedProofsEModel("dashboard.limitTone", args, raw_limitTone(...args)); }
export function mergePages(...args) { return checkedProofsEModel("dashboard.mergePages", args, raw_mergePages(...args)); }
