// Launcher search (07 §R7.4): one ranked list across apps, actions, projects
// and chats. Pure, so the ranking can be tested without a browser.

import { checkNewChat, checkLauncher } from "./nxProofsEShellContracts.js";
const HARNESSES = [
  { app: "codex", words: ["codex"] },
  { app: "claude-code", words: ["claude code", "claude"] },
  { app: "neyvia", words: ["neyvia"] },
  { app: "opencode", words: ["opencode", "open code"] },
];
// Every harness with a write adapter can start a chat (OpenCode joined with plan 15 T9).
export const STARTABLE = new Set(["codex", "claude-code", "neyvia", "opencode"]);

/** Score how well `query` matches `text`: 0 = no match, higher is better. */
export function score(text, query) {
  const hay = String(text || "").toLowerCase();
  const needle = query.trim().toLowerCase();
  if (!needle) return 0;
  if (hay === needle) return 100;
  if (hay.startsWith(needle)) return 80;
  if (new RegExp(`\\b${needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`).test(hay)) return 60;
  if (hay.includes(needle)) return 40;
  // Loose letter-by-letter matching only for short single words ("pdfv", "hcl").
  if (/\s/.test(needle) || needle.length > 10) return 0;
  let at = 0;
  for (const char of needle) {
    at = hay.indexOf(char, at);
    if (at < 0) return 0;
    at += 1;
  }
  return 15;
}

/** "new codex chat in dictation" -> { app: "codex", project: "dictation" } */
export function parseNewChat(query) {
  return checkNewChat(query, parseChatPhrase(query));
}
function parseChatPhrase(query) {
  const match = /^new\s+(.+?)\s+(?:chat|conversation|session)(?:\s+in\s+(.+))?$/i.exec(query.trim());
  if (!match) return null;
  const said = match[1].toLowerCase();
  const harness = HARNESSES.find(entry => entry.words.some(word => said === word || said.startsWith(word)));
  if (!harness) return null;
  return { app: harness.app, project: (match[2] || "").trim() || null };
}

/**
 * Build ranked results. `sources` = { suites, actions, projects, chats };
 * each result is { key, group, title, subtitle, disabled?, run } with `run`
 * left to the caller via `payload`.
 */
export function searchLauncher(query, { suites = [], actions = [], projects = [], chats = [] }, limit = 24) {
  return checkLauncher(query, { suites, actions, projects, chats }, limit, collectLauncherResults(query, { suites, actions, projects, chats }, limit));
}
function collectLauncherResults(query, { suites, actions, projects, chats }, limit) {
  const q = query.trim();
  if (!q) return [];
  const results = [];
  const add = (group, key, title, subtitle, value, extra = {}) => { if (value > 0) results.push({ group, key, title, subtitle, rank: value, ...extra }); };

  const wanted = parseNewChat(q);
  if (wanted) {
    const project = wanted.project ? projects.map(entry => ({ entry, value: score(entry.name, wanted.project) })).sort((a, b) => b.value - a.value)[0] : null;
    const folder = project?.value ? project.entry : null;
    const startable = STARTABLE.has(wanted.app);
    results.push({
      group: "Actions", key: `new:${wanted.app}:${folder?.path || ""}`, rank: 200,
      title: `New ${labelOf(wanted.app)} chat${folder ? ` in ${folder.name}` : ""}`,
      subtitle: !startable ? `${labelOf(wanted.app)} chats can't be started from Neyvia yet` : wanted.project && !folder ? `No project matches “${wanted.project}”` : "Opens the composer ready to type",
      disabled: !startable, payload: { type: "new-chat", app: wanted.app, folder },
    });
  }
  for (const suite of suites) {
    const suiteScore = score(suite.name, q);  // the +5 favours a matching suite over its apps; it must not list unmatched suites
    add("Apps", `suite:${suite.id}`, suite.name, suite.description, suiteScore > 0 ? suiteScore + 5 : 0, { payload: { type: "suite", suite: suite.id } });
    for (const app of suite.apps) {
      const value = Math.max(score(app.name, q), score(`${suite.name} ${app.name}`, q) - 5, score(app.description, q) - 20);
      add("Apps", `app:${app.id}`, app.name, app.status === "ready" ? suite.name : `${suite.name} · Coming`, value,
        { disabled: app.status !== "ready", payload: { type: "app", app: app.id, suite: suite.id } });
    }
  }
  for (const action of actions) {
    add("Actions", `action:${action.id}`, action.title, action.subtitle || "", Math.max(score(action.title, q), ...(action.keywords || []).map(word => score(word, q) - 10)), { payload: { type: "action", id: action.id } });
  }
  for (const project of projects) {
    add("Projects", `project:${project.name}`, project.name, project.path || "Project", score(project.name, q), { payload: { type: "project", project } });
  }
  for (const chat of chats) {
    add("Chats", `chat:${chat.id}`, chat.title || "Untitled chat", chat.project || "", Math.max(score(chat.title, q), score(chat.project, q) - 25), { payload: { type: "chat", id: chat.id } });
  }
  const order = ["Actions", "Apps", "Projects", "Chats"];
  return results
    .sort((a, b) => (b.rank - a.rank) || (a.disabled ? 1 : 0) - (b.disabled ? 1 : 0) || order.indexOf(a.group) - order.indexOf(b.group))
    .slice(0, limit);
}

function labelOf(app) {
  return { codex: "Codex", "claude-code": "Claude Code", neyvia: "Neyvia", opencode: "OpenCode" }[app] || app;
}
