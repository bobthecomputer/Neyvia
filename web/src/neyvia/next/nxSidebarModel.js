// Sidebar grouping and cleanup rules (plan 07 §4). Pure functions over the
// session list, so the tree is the same in every density and easy to test.
//
// Projects are branches, chats are leaves. Chats whose folder is not a real
// project (Codex's dated scratch folders, generated images, temp dirs) go to
// "No folder", sub-grouped into Images / Quick / Other by what the PC read in
// the transcript (sidebar.state): never by title or folder name.

import { checkSidebar } from "./nxProofsEShellContracts.js";
export const DEFAULT_CLEANUP = { noFolderDays: 7, projectDays: 30, tidyThreshold: 30, autoArchive: false };
const DAY = 24 * 60 * 60 * 1000;
const FRESH_FAILURE_MS = DAY;

const NO_FOLDER_PATTERNS = [
  /[\\/]documents[\\/]codex[\\/]\d{4}-\d{2}-\d{2}([\\/]|$)/i, // Codex chats started without a project
  /[\\/]\.codex[\\/]generated_images([\\/]|$)/i,
  /[\\/]appdata[\\/]local[\\/]temp([\\/]|$)/i,
  /^[a-z]:[\\/](tmp|temp)([\\/]|$)/i,
  /^\/tmp(\/|$)/,
  /[\\/](scratch|scratchpad|\.sandbox-scratch|sandbox-scratch|scratch-workspaces)([\\/]|$)/i,
  /[\\/]scratch-[^\\/]*$/i,
  // Neyvia's own throwaway workspaces: read-only chat copies, proofs, previews, NAS pulls.
  /[\\/](read_only_workspaces|read-only-chat)([\\/]|$)/i,
  /[\\/]\.agent_control[\\/]/i,
];
// A bare home, Desktop, Downloads or Documents folder is a place, not a project.
const LOOSE_FOLDER = /^([a-z]:[\\/]users[\\/][^\\/]+|\/home\/[^/]+|\/users\/[^/]+)([\\/](desktop|downloads|documents))?[\\/]?$/i;

/** CLI chats (`codex exec`, a Claude Code terminal or `claude -p`) share one branch whatever the app; their folders are often throwaway worktrees. */
export const CLI_BRANCH = "CLI";
export const cliBranch = () => CLI_BRANCH;

export const basename = path => String(path || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop() || "";

export function isNeedsYou(session, now = Date.now()) {
  if (session.status === "waiting_approval" || session.status === "waiting_input") return true;
  return session.status === "failed" && now - Date.parse(session.updated_at || 0) < FRESH_FAILURE_MS;
}

/** Where a chat belongs: a project branch, or "No folder" with a kind. */
export function placeSession(session) {
  return checkSidebar("placeSession", [session], resolvePlacement(session));
}
function resolvePlacement(session) {
  if (session.projectOverride !== undefined) {
    if (session.projectOverride) return { group: "project", project: session.projectOverride.name, path: session.projectOverride.path, subject: session.projectOverride.subject === true };
    return { group: "nofolder", kind: kindOf(session) };
  }
  const cwd = String(session.cwd || "");
  if (session.background === true) return { group: "project", project: cliBranch(session), path: null, background: true };
  if (cwd && NO_FOLDER_PATTERNS.some(pattern => pattern.test(cwd))) return { group: "nofolder", kind: kindOf(session) };
  if (cwd && LOOSE_FOLDER.test(cwd) && !session.git_branch) return { group: "nofolder", kind: kindOf(session) };
  if (session.project_known === false || session.project_known !== true && !session.git_branch) return { group: "nofolder", kind: kindOf(session) };
  const name = cwd ? basename(cwd) : session.project;
  if (!name) return { group: "nofolder", kind: kindOf(session) };
  return { group: "project", project: session.project || name, path: cwd || null };
}

const KINDS = new Set(["images", "quick", "other"]);

/**
 * The No folder lane from the transcript observation: Images when the chat
 * made an image, Quick when the whole transcript has fewer than 3 prompts,
 * Other otherwise, and Other while it hasn't been read (or couldn't be).
 */
export function kindOf(session) {
  const kind = session?.sidebar?.kind;
  return checkSidebar("kindOf", [session], KINDS.has(kind) ? kind : "other");
}

const AGENT_TONE = {
  running: ["live", "Working"], in_progress: ["live", "Working"], started: ["live", "Working"], working: ["live", "Working"], queued: ["live", "Starting"],
  ok: ["green", "Done"], completed: ["green", "Done"], done: ["green", "Done"], success: ["green", "Done"],
  error: ["red", "Failed"], failed: ["red", "Failed"],
  interrupted: ["idle", "Stopped"], cancelled: ["idle", "Stopped"], canceled: ["idle", "Stopped"], idle: ["idle", "Idle"],
  ended: ["idle", "Ended"],
};

/** An agent's status as a dot tone and a word ("unknown" says so). */
export function agentStatus(status) {
  const [tone, word] = AGENT_TONE[String(status || "").toLowerCase()] || ["idle", "Unknown"];
  return { tone, word };
}

const AGENT_RANK = { live: 0, red: 1, green: 2, idle: 3 };
/** Working first, then failed, then the rest, each in the order they started. */
export function orderAgents(agents = []) {
  return [...agents].sort((a, b) => AGENT_RANK[agentStatus(a.status).tone] - AGENT_RANK[agentStatus(b.status).tone]);
}

/** Counts over an agent tree: total, working, failed. */
export function agentSummary(agents = []) {
  const summary = { total: 0, running: 0, failed: 0 };
  const walk = nodes => {
    for (const node of nodes || []) {
      summary.total += 1;
      const { tone } = agentStatus(node.status);
      if (tone === "live") summary.running += 1;
      if (tone === "red") summary.failed += 1;
      walk(node.children);
    }
  };
  walk(agents);
  return checkSidebar("agentSummary", [agents], summary);
}

/** Chat ids that are an observed child of another chat (they show under it, not on their own). */
export function childChatIds(sessions) {
  const ids = new Set();
  const walk = nodes => { for (const node of nodes || []) { if (node.sessionId) ids.add(node.sessionId); walk(node.children); } };
  for (const session of sessions) walk(session?.sidebar?.agents);
  return ids;
}

/** A leaf's light: running, needs you, error, stale (a candidate to fall), or ok. */
export function leafState(session, place, policy = DEFAULT_CLEANUP, now = Date.now()) {
  if (session.status === "working") return "running";
  if (isNeedsYou(session, now)) return session.status === "failed" ? "error" : "needs";
  if (isStale(session, place, policy, now)) return "stale";
  return "ok";
}

function isStale(session, place, policy, now) {
  const days = place.group === "nofolder" ? policy.noFolderDays : policy.projectDays;
  const updated = Date.parse(session.updated_at || "");
  return Number.isFinite(updated) && days > 0 && now - updated > days * DAY;
}

/** Chats the cleanup policy may archive. Never: pinned, needs you, running. */
export function staleCandidates(sessions, policy = DEFAULT_CLEANUP, now = Date.now()) {
  const result = sessions.filter(session => {
    if (session.pinned || session.archived) return false;
    if (session.status === "working" || isNeedsYou(session, now)) return false;
    if (session.has_uncommitted || session.has_running_jobs) return false;
    if (session.cleanup_safety?.status !== "observed") return false;
    return isStale(session, placeSession(session), policy, now);
  });
  return checkSidebar("staleCandidates", [sessions, policy, now], result, DEFAULT_CLEANUP);
}

export function shouldOfferTidy(total, stale, policy = DEFAULT_CLEANUP) {
  return checkSidebar("shouldOfferTidy", [total, stale, policy], stale > 0 && (total > policy.tidyThreshold || stale >= 10));
}

const byRecent = (a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || ""));

/**
 * The whole tree: Needs you, Pinned, project branches (most recent first,
 * including empty projects the model just created), and No folder.
 */
export function buildTree(sessions, { projects = [], policy = DEFAULT_CLEANUP, now = Date.now() } = {}) {
  // A chat that another chat started (an observed agent link) hangs under its parent instead.
  const children = childChatIds(sessions.filter(session => session && !session.archived));
  const visible = sessions.filter(session => session && !session.archived && !children.has(session.id)).sort(byRecent);
  const needsYou = [];
  const pinned = [];
  const branches = new Map();
  const noFolder = { images: [], quick: [], other: [] };
  for (const project of projects) {
    const key = project.name.toLowerCase();
    if (!branches.has(key)) branches.set(key, { name: project.name, path: project.path || null, sessions: [], updated: "" });
  }
  for (const session of visible) {
    const place = placeSession(session);
    const leaf = { session, place, state: leafState(session, place, policy, now), agents: session.sidebar?.agents || [] };
    if (isNeedsYou(session, now)) { needsYou.push(leaf); continue; }
    if (session.pinned) { pinned.push(leaf); continue; }
    if (place.group === "nofolder") { noFolder[place.kind].push(leaf); continue; }
    const key = place.project.toLowerCase();
    if (!branches.has(key)) branches.set(key, { name: place.project, path: place.path, subject: place.subject === true, background: place.background === true, sessions: [], updated: "" });
    const branch = branches.get(key);
    branch.sessions.push(leaf);
    if (!branch.path && place.path) branch.path = place.path;
    if (String(session.updated_at || "") > branch.updated) branch.updated = String(session.updated_at || "");
  }
  const projectList = [...branches.values()].sort((a, b) => b.updated.localeCompare(a.updated));
  const noFolderCount = noFolder.images.length + noFolder.quick.length + noFolder.other.length;
  return checkSidebar("buildTree", [sessions, { projects, policy, now }], { needsYou, pinned, projects: projectList, noFolder, noFolderCount, total: visible.length, folded: children.size });
}
