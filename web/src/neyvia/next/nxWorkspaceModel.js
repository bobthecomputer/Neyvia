// Pure helpers for the Workspace panel. No React and no network, so the diff
// parser and the "which buttons make sense" rules can be checked in isolation.

const STATUSES = {
  modified: { letter: "M", label: "Modified", tone: "mod" },
  added: { letter: "A", label: "Added", tone: "add" },
  deleted: { letter: "D", label: "Deleted", tone: "del" },
  renamed: { letter: "R", label: "Renamed", tone: "mod" },
  copied: { letter: "C", label: "Copied", tone: "add" },
  untracked: { letter: "?", label: "Untracked", tone: "new" },
  conflicted: { letter: "U", label: "Conflicted", tone: "del" },
  typechange: { letter: "T", label: "Type changed", tone: "mod" },
};
const BY_LETTER = { M: "modified", A: "added", D: "deleted", R: "renamed", C: "copied", "?": "untracked", U: "conflicted", T: "typechange" };

export function statusOf(change) {
  const raw = String(change?.status || "");
  return STATUSES[raw.toLowerCase()] || STATUSES[BY_LETTER[raw.toUpperCase()]] || STATUSES.modified;
}

/** Commit runs `git commit -a`: tracked changes and anything already staged, never untracked files. */
export const isCommittable = change => statusOf(change).letter !== "?";

export function splitPath(path) {
  const clean = String(path || "").replaceAll("\\", "/");
  const cut = clean.lastIndexOf("/");
  return { dir: clean.slice(0, cut + 1), name: clean.slice(cut + 1) };
}

/** Head and tail of a path for middle truncation: the tail keeps the last segments visible. */
export function splitPathTail(path, keep = 18) {
  const text = String(path || "");
  const parts = text.split(/([\\/])/);
  let tail = "";
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    if (tail.length >= keep) break;
    tail = parts[index] + tail;
  }
  return [text.slice(0, text.length - tail.length), tail];
}

export function baseName(path) {
  return String(path || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop() || "";
}

export function sumChanges(changes) {
  let additions = 0;
  let deletions = 0;
  for (const change of changes) {
    additions += Number(change.additions) || 0;
    deletions += Number(change.deletions) || 0;
  }
  return { additions, deletions };
}

export const plural = (count, one, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;

const DEFAULT_BRANCHES = new Set(["main", "master", "trunk"]);
export const isDefaultBranch = branch => DEFAULT_BRANCHES.has(String(branch || "").toLowerCase());

export const ghReady = gh => Boolean(gh?.installed && gh?.authenticated);

/** Which actions are possible right now. Anything not possible is simply absent from the UI. */
export function planActions(data) {
  const plan = { commit: null, push: null, pr: null, prBlocked: null, diverged: false };
  const repo = data?.repo;
  if (!repo) return plan;
  const tracked = (data.changes || []).filter(isCommittable);
  if (tracked.length) plan.commit = { files: tracked };

  const branch = data.branch;
  const onBranch = Boolean(branch) && !data.detached;
  const upstream = data.upstream || null;
  const ahead = Number.isFinite(data.ahead) ? data.ahead : null;
  const behind = Number.isFinite(data.behind) ? data.behind : 0;

  if (onBranch) {
    if (upstream) {
      if (ahead > 0 && behind > 0) plan.diverged = true;
      else if (ahead > 0) plan.push = { mode: "push", ahead };
    } else if (repo.remoteUrl) {
      plan.push = { mode: "publish" };
    }
  }

  if (repo.github && ghReady(data.gh) && onBranch && !data.pullRequest && !isDefaultBranch(branch)) {
    if (upstream && ahead === 0 && behind === 0) plan.pr = {};
    else plan.prBlocked = plan.diverged ? "diverged" : "unpushed";
  }
  return plan;
}

const BRANCH_VERBS = { fix: "Fix", bugfix: "Fix", hotfix: "Fix" };
const BRANCH_PREFIXES = /^(feature|feat|chore|refactor|docs|test|perf|build|ci|style)$/i;

/** A readable pull request title from a branch name, the way `gh pr create --fill` reads it. */
export function titleFromBranch(branch) {
  const parts = String(branch || "").split("/").filter(Boolean);
  let verb = "";
  if (parts.length > 1 && BRANCH_VERBS[parts[0].toLowerCase()]) verb = `${BRANCH_VERBS[parts.shift().toLowerCase()]} `;
  else if (parts.length > 1 && BRANCH_PREFIXES.test(parts[0])) parts.shift();
  const words = parts.join("/").replace(/[-_]+/g, " ").trim();
  const text = `${verb}${words}`.trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

export function splitCommitMessage(message) {
  const [first = "", ...rest] = String(message || "").trim().split("\n");
  return { title: first.trim(), body: rest.join("\n").trim() };
}

export function githubLinks(github, branch) {
  if (!github?.url) return {};
  const encoded = branch ? branch.split("/").map(encodeURIComponent).join("/") : "";
  return {
    repo: github.url,
    branch: encoded ? `${github.url}/tree/${encoded}` : null,
    compare: encoded ? `${github.url}/compare/${encoded}?expand=1` : null,
  };
}

/** "offline" when the PC could not be reached, so the panel can say so instead of showing an error. */
export function errorKind(error) {
  const code = String(error?.code || "");
  return code === "network" || code === "pc_service_offline" ? "offline" : "error";
}

/* ---------- unified diff ---------- */

const HUNK = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$/;

/**
 * Parse `git diff` text into files, hunks and numbered lines.
 * A line is { t: "add" | "del" | "ctx" | "note", o, n, text }, where o and n are the old and new line numbers.
 */
export function parsePatch(text) {
  const files = [];
  let file = null;
  let hunk = null;
  let oldNo = 0;
  let newNo = 0;
  let oldLeft = 0;
  let newLeft = 0;
  let additions = 0;
  let deletions = 0;

  const open = () => { file = { notes: [], hunks: [], binary: false, oldPath: "", newPath: "", similarity: "" }; files.push(file); hunk = null; };

  for (const raw of String(text || "").split("\n")) {
    const line = raw.endsWith("\r") ? raw.slice(0, -1) : raw;
    if (line.startsWith("... [diff truncated]")) break; // the backend's own marker; the panel shows a banner

    if (hunk && (oldLeft > 0 || newLeft > 0 || line.startsWith("\\"))) {
      const sign = line[0];
      if (line.startsWith("\\")) hunk.lines.push({ t: "note", o: null, n: null, text: line.replace(/^\\ ?/, "") });
      else if (sign === "+") { hunk.lines.push({ t: "add", o: null, n: newNo++, text: line.slice(1) }); newLeft -= 1; additions += 1; }
      else if (sign === "-") { hunk.lines.push({ t: "del", o: oldNo++, n: null, text: line.slice(1) }); oldLeft -= 1; deletions += 1; }
      else { hunk.lines.push({ t: "ctx", o: oldNo++, n: newNo++, text: line.slice(1) }); oldLeft -= 1; newLeft -= 1; }
      continue;
    }

    if (line.startsWith("diff --git ")) { open(); continue; }
    const start = HUNK.exec(line);
    if (start) {
      if (!file) open();
      oldNo = Number(start[1]);
      newNo = Number(start[3]);
      oldLeft = start[2] === undefined ? 1 : Number(start[2]);
      newLeft = start[4] === undefined ? 1 : Number(start[4]);
      hunk = { header: line, section: start[5] || "", lines: [] };
      file.hunks.push(hunk);
      continue;
    }
    if (!file) continue;
    if (line.startsWith("new file mode")) file.notes.push("New file");
    else if (line.startsWith("deleted file mode")) file.notes.push("Deleted file");
    else if (line.startsWith("rename from ")) file.oldPath = line.slice(12);
    else if (line.startsWith("rename to ")) file.newPath = line.slice(10);
    else if (line.startsWith("similarity index ")) file.similarity = line.slice(17);
    else if (line.startsWith("old mode ")) file.mode = { from: line.slice(9) };
    else if (line.startsWith("new mode ") && file.mode) file.notes.push(`Mode ${file.mode.from} to ${line.slice(9)}`);
    else if (line.startsWith("Binary files ") || line.startsWith("GIT binary patch")) file.binary = true;
  }

  for (const entry of files) {
    if (entry.oldPath && entry.newPath) entry.notes.unshift(`Renamed from ${entry.oldPath}${entry.similarity ? ` (${entry.similarity} similar)` : ""}`);
  }
  return { files, additions, deletions, lines: files.reduce((sum, entry) => sum + entry.hunks.reduce((inner, item) => inner + item.lines.length, 0), 0) };
}
