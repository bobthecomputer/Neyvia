import { THEMES, DEFAULT_THEME } from "./nxThemeRegistry.js";
import { ModelContractError } from "./nxModelContracts.js";
import { BUILTIN_SCENES, normalizeLayout, sceneId } from "./nxLayoutModel.js";

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const ensure = (id, okay) => { if (!okay) throw new ModelContractError(id); };
const day = 86400000;
const need = (s, now) => ["waiting_approval", "waiting_input"].includes(s.status) || s.status === "failed" && now - Date.parse(s.updated_at || 0) < day;
const lane = s => ["images", "quick", "other"].includes(s?.sidebar?.kind) ? s.sidebar.kind : "other";
const base = p => String(p || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop() || "";
const scratch = /[\\/]documents[\\/]codex[\\/]\d{4}-\d{2}-\d{2}(?:[\\/]|$)|[\\/]\.codex[\\/]generated_images(?:[\\/]|$)|[\\/]appdata[\\/]local[\\/]temp(?:[\\/]|$)|^[a-z]:[\\/](?:tmp|temp)(?:[\\/]|$)|^\/tmp(?:\/|$)|[\\/](?:scratch|scratchpad|\.sandbox-scratch|sandbox-scratch|scratch-workspaces)(?:[\\/]|$)|[\\/]scratch-[^\\/]*$|[\\/](?:read_only_workspaces|read-only-chat)(?:[\\/]|$)|[\\/]\.agent_control[\\/]/i;
const loose = /^([a-z]:[\\/]users[\\/][^\\/]+|\/home\/[^/]+|\/users\/[^/]+)([\\/](desktop|downloads|documents))?[\\/]?$/i;
function placement(s) {
  if (s.projectOverride !== undefined) return s.projectOverride ? { group: "project", project: s.projectOverride.name, path: s.projectOverride.path, subject: s.projectOverride.subject === true } : { group: "nofolder", kind: lane(s) };
  const path = String(s.cwd || ""), name = path ? base(path) : s.project;
  if (s.background === true) return { group: "project", project: "CLI", path: null, background: true };
  return !name || scratch.test(path) || loose.test(path) && !s.git_branch || s.project_known === false || s.project_known !== true && !s.git_branch
    ? { group: "nofolder", kind: lane(s) } : { group: "project", project: s.project || name, path: path || null };
}
function safeStale(s, policy, now) {
  const days = placement(s).group === "nofolder" ? policy.noFolderDays : policy.projectDays;
  return !s.pinned && !s.archived && s.status !== "working" && !need(s, now) && !s.has_uncommitted && !s.has_running_jobs && s.cleanup_safety?.status === "observed"
    && Number.isFinite(Date.parse(s.updated_at || "")) && days > 0 && now - Date.parse(s.updated_at) > days * day;
}
export function checkSidebar(name, args, result, defaultPolicy) {
  const [input, options, time] = args;
  const id = `proofs-e.shell.${name}`;
  if (name === "kindOf") ensure(id, result === lane(input));
  if (name === "placeSession") ensure(id, same(result, placement(input)));
  if (name === "agentSummary") {
    const rows = [], walk = nodes => { for (const row of nodes || []) { rows.push(row); walk(row.children); } }; walk(input);
    const live = ["running", "in_progress", "started", "working", "queued"], failed = ["error", "failed"];
    ensure(id, same(result, { total: rows.length, running: rows.filter(s => live.includes(String(s.status || "").toLowerCase())).length, failed: rows.filter(s => failed.includes(String(s.status || "").toLowerCase())).length }));
  }
  if (name === "staleCandidates") ensure(id, defaultPolicy?.autoArchive === false && same(result, input.filter(s => safeStale(s, options, time))));
  if (name === "shouldOfferTidy") ensure(id, result === (options > 0 && (input > time.tidyThreshold || options >= 10)));
  if (name === "buildTree") {
    const now = options?.now ?? Date.now(), child = new Set();
    const walk = nodes => { for (const node of nodes || []) { if (node.sessionId) child.add(node.sessionId); walk(node.children); } };
    for (const s of input.filter(s => s && !s.archived)) walk(s.sidebar?.agents);
    const visible = input.filter(s => s && !s.archived && !child.has(s.id));
    const leaves = [...result.needsYou, ...result.pinned, ...result.projects.flatMap(p => p.sessions), ...Object.values(result.noFolder).flat()];
    const leafSessions = new Set(leaves.map(l => l.session));
    ensure(id, result.total === visible.length && result.folded === child.size && leaves.length === visible.length && leafSessions.size === visible.length && visible.every(s => leafSessions.has(s))
      && result.needsYou.every(l => need(l.session, now)) && result.pinned.every(l => l.session.pinned && !need(l.session, now))
      && visible.filter(s => need(s, now)).every(s => result.needsYou.some(l => l.session === s))
      && result.projects.every(p => p.sessions.every(l => !need(l.session, now) && !l.session.pinned && same(l.place, placement(l.session)) && l.place.project.toLowerCase() === p.name.toLowerCase()))
      && Object.entries(result.noFolder).every(([kind, rows]) => rows.every(l => placement(l.session).group === "nofolder" && lane(l.session) === kind))
      && (options?.projects || []).every(p => result.projects.some(b => b.name.toLowerCase() === p.name.toLowerCase()))
      && result.noFolderCount === Object.values(result.noFolder).flat().length
      && result.projects.every((p, i, rows) => i === 0 || rows[i - 1].updated.localeCompare(p.updated) >= 0)
      && leaves.every(l => { const s = l.session, place = placement(s), policy = options?.policy || { noFolderDays: 7, projectDays: 30 }; const age = now - Date.parse(s.updated_at || ""), days = place.group === "nofolder" ? policy.noFolderDays : policy.projectDays; const expected = s.status === "working" ? "running" : need(s, now) ? s.status === "failed" ? "error" : "needs" : Number.isFinite(age) && days > 0 && age > days * day ? "stale" : "ok"; return l.state === expected && same(l.place, place) && same(l.agents, s.sidebar?.agents || []); }));
  }
  return result;
}

export function checkInitial(saved, state) {
  const bubbles = [], seen = new Set();
  for (const b of Array.isArray(saved.bubbles) ? saved.bubbles : []) if (b?.id && !seen.has(b.id) && bubbles.length < 6) { seen.add(b.id); bubbles.push({ id: String(b.id), x: Math.min(1, Math.max(0, Number(b.x ?? 1) || 0)), y: Math.min(1, Math.max(0, Number(b.y ?? 0.3) || 0)) }); }
  ensure("proofs-e.shell.initial", state.theme === (THEMES.includes(saved.theme) ? saved.theme : DEFAULT_THEME) && same(state.bubbles, bubbles) && state.stage === null && state.notices.length === 0);
  return state;
}
export function checkOverrides(session, overrides, projects, result) {
  const patch = overrides[session.id];
  if (!patch) { ensure("proofs-e.shell.overrides", result === session); return result; }
  const expected = { ...session };
  if (patch.title) expected.title = patch.title;
  for (const key of ["pinned", "archived"]) if (patch[key] !== undefined) expected[key] = patch[key];
  if (patch.project !== undefined) expected.projectOverride = patch.project === null ? null : projects[patch.project] || (String(patch.project || "").startsWith("subject:") ? { id: patch.project, name: "Sorted chats", path: null, subject: true } : { name: base(patch.project) || patch.project, path: patch.project });
  ensure("proofs-e.shell.overrides", same(result, expected)); return result;
}
export function checkUiAction(before, action, p, next) {
  const id = "proofs-e.shell.reducer";
  ensure(id, next && THEMES.includes(next.theme) && next.bubbles.length <= 6 && new Set(next.bubbles.map(b => b.id)).size === next.bubbles.length && next.bubbles.every(b => b.x >= 0 && b.x <= 1 && b.y >= 0 && b.y <= 1));
  const eq = (a, b) => ensure(id, same(a, b));
  const override = next.overrides[p.id];
  if (action === "pane.show") {
    const desc = { type: "pane", kind: p.kind, target: String(p.target ?? "") };
    if (!p.placement) eq(next.stage, desc);
    else {
      const win = next.windows.find(row => row.id === `pane:${p.kind}:${p.target ?? ""}`);
      ensure(id, win?.placement === p.placement && same(win.desc, desc));
      if (p.side) ensure(id, p.side === "right" ? next.layout.order.indexOf("panel") > next.layout.order.indexOf("main") : next.layout.order.indexOf("panel") < next.layout.order.indexOf("main"));
    }
  }
  if (action === "session.moved") { if (p.clearOverride) ensure(id, !Object.hasOwn(override, "project") && Object.keys(before.overrides[p.id] || {}).filter(k => k !== "project").every(k => same(override[k], before.overrides[p.id][k]))); else eq(override.project, p.project == null ? null : String(p.project)); }
  if (action === "session.renamed") eq(override.title, String(p.title));
  if (action === "session.pinned") eq(override.pinned, p.pinned !== false);
  if (action === "session.archived") eq(override.archived, p.archived !== false);
  if (action === "session.created") ensure(id, next.created[p.id]?.id === p.id && next.created[p.id].cwd === (p.folder || null) && next.created[p.id].app === (p.app || "neyvia"));
  if (action === "project.created") eq(next.projects[String(p.path || p.name)], { name: String(p.name), path: String(p.path || p.name) });
  if (action === "view.layout") eq(next.density, p.level);
  if (action === "notify") ensure(id, next.notices.at(-1).message === String(p.message) && next.notices.at(-1).approvalId === (p.approvalId || null));
  if (action === "nightshift.task.updated") ensure(id, Object.entries(p).every(([k, v]) => same(next.nightshift[p.id][k], v)));
  if (action === "view.theme") eq(next.theme, p.theme);
  if (action === "view.arrange") eq(next.layout, normalizeLayout({ ...before.layout, ...p }));
  if (action === "view.scene") { if (p.save) { const scene = next.scenes[sceneId(p.save)]; eq(scene.layout, before.layout); eq(scene.density, before.density); eq(scene.theme, before.theme); } else { const scene = BUILTIN_SCENES[sceneId(p.name)] || before.scenes[sceneId(p.name)]; eq(next.density, scene.density || before.density); eq(next.theme, scene.theme || before.theme); eq(next.layout, normalizeLayout({ ...before.layout, ...scene.layout })); } }
  if (action === "view.float") { const ids = before.bubbles.map(b => b.id), key = String(p.id); eq(next.bubbles.map(b => b.id), p.floating === false ? ids.filter(i => i !== key) : ids.includes(key) ? ids : [...ids, key].slice(-6)); eq(next.bubbleOpen, p.floating === false ? before.bubbleOpen === key ? null : before.bubbleOpen : key); }
  if (action.startsWith("pdf.")) { const queued = next.inbox.at(-1); ensure(id, next.inbox.length === before.inbox.length + 1 && queued.app === "pdf" && queued.action === action && queued.seq > (before.inbox.at(-1)?.seq || 0)); eq(queued.payload, action === "pdf.open" ? { ...p, source: String(p.source || p.path || p.url || "") } : p); if (action === "pdf.open") eq(next.stage, { type: "app", app: "pdf", suite: "documents", target: queued.payload.source }); else eq(next.stage, before.stage); }
  if (action === "artifact.published") { const signal = next.appSignals.outputs; eq(signal.payload, p); eq(signal.seq, (before.appSignals.outputs?.seq || 0) + 1); const open = before.stage?.type === "pane" && before.stage.kind === "outputs"; eq(next.notices.length, open ? before.notices.length : Math.min(5, before.notices.length + 1)); }
  if (action === "app.open") { const suites = { notes: "documents", pdf: "documents", files: "documents" }; ensure(id, next.stage.type === "app" && next.stage.app === String(p.app) && next.stage.target === (p.target ?? null) && !next.launcher && (!suites[p.app] || next.stage.suite === (p.suite || suites[p.app]))); }
  if (action === "stage.close") eq(next.stage, null);
  if (action === "launcher.open") ensure(id, next.launcher && next.launcherQuery === String(p.query || "") && !next.dashboard);
  if (action === "sidebar.toggle") eq(next.layout.sidebarHidden, typeof p.hidden === "boolean" ? p.hidden : !before.layout.sidebarHidden);
  if (["newchat.open", "session.open", "session.approve", "session.interrupt"].includes(action)) { const signal = next.appSignals.shell; ensure(id, signal.action === action && same(signal.payload, p) && signal.seq > (before.appSignals.shell?.seq || 0)); }
  return next;
}

export function checkNewChat(query, result) {
  const match = /^new\s+(.+?)\s+(?:chat|conversation|session)(?:\s+in\s+(.+))?$/i.exec(query.trim());
  const aliases = [["codex", "codex"], ["claude code", "claude-code"], ["claude", "claude-code"], ["neyvia", "neyvia"], ["opencode", "opencode"], ["open code", "opencode"]];
  const found = match && aliases.find(([word]) => match[1].toLowerCase().startsWith(word));
  ensure("proofs-e.shell.parseNewChat", found ? same(result, { app: found[1], project: (match[2] || "").trim() || null }) : result === null); return result;
}
export function checkLauncher(query, sources, limit, result) {
  const id = "proofs-e.shell.searchLauncher";
  ensure(id, (limit < 0 || result.length <= limit) && result.every((r, i) => r.rank > 0 && (i === 0 || result[i - 1].rank >= r.rank)));
  for (const r of result) { if (r.payload.type === "app") { const app = sources.suites.flatMap(s => s.apps).find(a => a.id === r.payload.app); ensure(id, r.disabled === (app.status !== "ready") && r.title === app.name); } if (r.payload.type === "new-chat") { const labels = { codex: "Codex", "claude-code": "Claude Code", neyvia: "Neyvia", opencode: "OpenCode" }; ensure(id, r.rank === 200 && r.disabled === false && r.title === `New ${labels[r.payload.app] || r.payload.app} chat${r.payload.folder ? ` in ${r.payload.folder.name}` : ""}` && (!r.payload.folder || sources.projects.some(p => same(p, r.payload.folder)))); } }
  const q = query.trim(), value = (text, term = q) => { const h = String(text || "").toLowerCase(), n = term.trim().toLowerCase(); if (!n) return 0; if (h === n) return 100; if (h.startsWith(n)) return 80; if (new RegExp(`\\b${n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`).test(h)) return 60; if (h.includes(n)) return 40; if (/\s/.test(n) || n.length > 10) return 0; let position = 0; for (const letter of n) { position = h.indexOf(letter, position); if (position < 0) return 0; position++; } return 15; };
  const candidates = [], add = (key, rank, disabled = false, group) => { if (rank > 0) candidates.push({ key, rank, disabled, group }); };
  for (const suite of sources.suites || []) { { const v = value(suite.name); add(`suite:${suite.id}`, v > 0 ? v + 5 : 0, false, 1); } for (const app of suite.apps) add(`app:${app.id}`, Math.max(value(app.name), value(`${suite.name} ${app.name}`) - 5, value(app.description) - 20), app.status !== "ready", 1); }
  for (const a of sources.actions || []) add(`action:${a.id}`, Math.max(value(a.title), ...(a.keywords || []).map(w => value(w) - 10)), false, 0);
  for (const p of sources.projects || []) add(`project:${p.name}`, value(p.name), false, 2);
  for (const c of sources.chats || []) add(`chat:${c.id}`, Math.max(value(c.title), value(c.project) - 25), false, 3);
  const phrase = /^new\s+(.+?)\s+(?:chat|conversation|session)(?:\s+in\s+(.+))?$/i.exec(q);
  if (phrase) { const aliases = [["codex", "codex"], ["claude code", "claude-code"], ["claude", "claude-code"], ["neyvia", "neyvia"], ["opencode", "opencode"], ["open code", "opencode"]], app = aliases.find(([word]) => phrase[1].toLowerCase().startsWith(word))?.[1]; if (app) { const project = phrase[2] && (sources.projects || []).map(p => ({ p, rank: value(p.name, phrase[2]) })).sort((a, b) => b.rank - a.rank)[0]; const folder = project?.rank ? project.p : null; add(`new:${app}:${folder?.path || ""}`, 200, false, 0); const actual = result.find(r => r.payload.type === "new-chat"); if (limit > 0) ensure(id, actual && same(actual.payload, { type: "new-chat", app, folder })); } }
  const expected = q ? candidates.sort((a, b) => b.rank - a.rank || Number(a.disabled) - Number(b.disabled) || a.group - b.group).slice(0, limit) : [];
  ensure(id, same(result.map(r => [r.key, r.rank]), expected.map(r => [r.key, r.rank])));
  return result;
}
