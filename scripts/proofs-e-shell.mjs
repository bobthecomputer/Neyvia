#!/usr/bin/env node
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { initialOsState, reduceUiAction, withOverrides } from "../web/src/neyvia/next/nxOsStore.js";
import { buildTree, kindOf, placeSession, agentSummary, staleCandidates, shouldOfferTidy, DEFAULT_CLEANUP } from "../web/src/neyvia/next/nxSidebarModel.js";
import { searchLauncher, parseNewChat } from "../web/src/neyvia/next/nxLauncherModel.js";
import { checkSidebar, checkInitial, checkUiAction, checkOverrides, checkLauncher, checkNewChat } from "../web/src/neyvia/next/nxProofsEShellContracts.js";
import { ModelContractError } from "../web/src/neyvia/next/nxModelContracts.js";

const repository = fileURLToPath(new URL("../", import.meta.url));
export async function runProofsEShell({ root = resolve(repository, ".agent_control/proofs-e/shell") } = {}) {
  const started = performance.now(), failures = [], procedures = [], observers = [], witnesses = new Map();
  const manual = JSON.parse(await readFile(resolve(repository, "config/proofs/proofs-e-shell.json"), "utf8"));
  const require = (okay, message) => { if (!okay) throw new Error(message); };
  const procedure = (id, execute) => { try { const calls = execute(); procedures.push({ id, status: "passed", calls }); } catch (error) { failures.push({ id, error: error.message }); procedures.push({ id, status: "failed", error: error.message }); } };
  const witness = (name, execute, corrupt) => witnesses.set(name, { execute, corrupt });
  const now = Date.now(), ago = days => new Date(now - days * 86400000).toISOString();
  const row = (id, cwd, extra = {}) => ({ id, cwd, title: id, updated_at: ago(0.1), status: "idle", ...extra });
  procedure("shell.classify-group-protect", () => {
    const scratchPaths = ["C:/Users/proof/Documents/Codex/2026-09-29/logo", "C:/Users/proof/.codex/generated_images/x", "C:/Users/proof/AppData/Local/Temp/x", "C:/Users/proof/Projects/app/.sandbox-scratch", "C:/Users/proof", "C:/Users/proof/AppData/Roaming/Claude/scratch-workspaces/9175/8ae6/scratch-2026-09-30-x", "C:/Users/proof/Projects/app/.agent_control/read_only_workspaces/x/workspace", "C:/Users/proof/AppData/Local/Neyvia/read-only-chat/x", "C:/Users/proof/Projects/app/.agent_control/nas_pull/source", "C:/Users/proof/Documents/Codex/2026-09-20/laya/outputs"];
    for (const cwd of scratchPaths) require(placeSession(row(cwd, cwd)).group === "nofolder", "Scratch chat entered a project");
    const worktree = row("worktree", "C:/Users/proof/.codex/worktrees/abc/app", { project_known: true, project: "app" });
    require(placeSession(worktree).project === "app" && placeSession(row("home", "C:/Users/proof", { git_branch: "main" })).group === "project" && placeSession(row("unknown", "C:/unknown/app", { project: "app" })).group === "nofolder", "Observed project authority lost");
    const unknown = row("unknown-folder", "C:/unknown/random", { project: "random" });
    require(placeSession(unknown).group === "nofolder" && placeSession({ ...unknown, project_known: false, git_branch: "stale" }).group === "nofolder" && placeSession({ ...unknown, project_known: true }).group === "project" && placeSession({ ...unknown, projectOverride: { name: "Chosen", path: "C:/chosen" } }).project === "Chosen" && placeSession({ ...unknown, project_known: true, projectOverride: null }).group === "nofolder", "Folder labels overrode current project evidence");
    for (const kind of ["images", "quick", "other", "bogus"]) require(kindOf(row(kind, "", { sidebar: { kind } })) === (kind === "bogus" ? "other" : kind), "Transcript lane lost");
    require(kindOf(row("unread", scratchPaths[1], { title: "Make a logo", turn_count: 1 })) === "other", "Title guessed a lane");
    const agents = [{ id: "a1", status: "running", sessionId: "child", children: [{ id: "a1.1", status: "error", children: [] }] }, { id: "a2", status: "ok", children: [] }];
    const sessions = [row("parent", "C:/proof/project", { project_known: true, sidebar: { agents } }), row("child", "C:/proof/project", { project_known: true }), row("ask", "C:/proof/project", { status: "waiting_approval" }), row("pin", "", { pinned: true }), row("gone", "", { archived: true }), row("img", "", { sidebar: { kind: "images" } }), row("live", "C:/proof/project", { project_known: true, status: "working" })];
    const tree = buildTree(sessions, { now, projects: [{ name: "empty", path: "C:/proof/empty" }] });
    require(tree.folded === 1 && tree.total === 5 && tree.needsYou[0].session.id === "ask" && tree.pinned[0].session.id === "pin" && tree.projects[0].sessions.some(l => l.state === "running") && tree.projects.at(-1).name === "empty" && tree.noFolder.images.length === 1, "Partitioned sidebar does not reflect current sessions");
    const summary = agentSummary(agents); require(summary.total === 3 && summary.running === 1 && summary.failed === 1, "Nested agent counts lost");
    witness("placeSession", () => checkSidebar("placeSession", [worktree], placeSession(worktree)), () => checkSidebar("placeSession", [worktree], { group: "nofolder", kind: "other" }));
    witness("kindOf", () => checkSidebar("kindOf", [sessions[5]], "images"), () => checkSidebar("kindOf", [sessions[5]], "other"));
    witness("agentSummary", () => checkSidebar("agentSummary", [agents], summary), () => checkSidebar("agentSummary", [agents], { ...summary, total: 2 }));
    witness("buildTree", () => checkSidebar("buildTree", [sessions, { now, projects: [{ name: "empty" }] }], tree), () => checkSidebar("buildTree", [sessions, { now }], { ...tree, needsYou: [], noFolder: { ...tree.noFolder, other: tree.needsYou } }));
    const safety = { cleanup_safety: { status: "observed" }, has_uncommitted: false, has_running_jobs: false };
    const old = row("old", "C:/proof/app", { ...safety, project_known: true, updated_at: ago(31) });
    const pool = [old, row("mid", old.cwd, { ...safety, project_known: true, updated_at: ago(20) }), row("scratch", scratchPaths[0], { ...safety, updated_at: ago(8) }), row("recent", scratchPaths[0], { ...safety, updated_at: ago(6) }), ...[{ pinned: true }, { status: "working" }, { status: "waiting_input" }, { has_uncommitted: true }, { has_running_jobs: true }, { cleanup_safety: null }, { archived: true }].map((extra, i) => ({ ...old, id: `protected-${i}`, ...extra }))];
    const stale = staleCandidates(pool, DEFAULT_CLEANUP, now); require(stale.map(s => s.id).join() === "old,scratch" && staleCandidates(pool, { ...DEFAULT_CLEANUP, projectDays: 10 }, now).map(s => s.id).join() === "old,mid,scratch", "Cleanup included a protected session");
    const unknownOld = { ...unknown, updated_at: ago(40), cleanup_safety: { status: "observed" } };
    require(staleCandidates([unknownOld], DEFAULT_CLEANUP, now).length === 1 && DEFAULT_CLEANUP.autoArchive === false, "Unobserved default cleanup authority");
    for (const patch of [{ cleanup_safety: undefined }, { cleanup_safety: { status: "unknown" } }, { has_uncommitted: true }, { has_running_jobs: true }, { pinned: true }, { status: "working" }, { status: "waiting_input" }]) require(staleCandidates([{ ...unknownOld, ...patch }], DEFAULT_CLEANUP, now).length === 0, "Unsafe tidy candidate");
    require(!shouldOfferTidy(12, 2) && shouldOfferTidy(40, 2) && shouldOfferTidy(12, 10), "Tidy threshold changed");
    witness("staleCandidates", () => checkSidebar("staleCandidates", [pool, DEFAULT_CLEANUP, now], stale, DEFAULT_CLEANUP), () => checkSidebar("staleCandidates", [pool, DEFAULT_CLEANUP, now], [...stale, pool[4]], DEFAULT_CLEANUP));
    witness("shouldOfferTidy", () => checkSidebar("shouldOfferTidy", [40, 2, DEFAULT_CLEANUP], true), () => checkSidebar("shouldOfferTidy", [40, 2, DEFAULT_CLEANUP], false));
    return scratchPaths.length + 18;
  });
  procedure("shell.bus-to-sidebar-undo", () => {
    let state = initialOsState(), calls = 0; const send = (a, p) => { state = reduceUiAction(state, a, p); calls++; };
    send("pane.show", { kind: "diff", target: "src/app.py" }); send("project.created", { name: "proof", path: "C:/proof/app" });
    send("session.moved", { id: "s1", project: "C:/proof/app" }); send("session.renamed", { id: "s1", title: "Renamed" }); send("session.pinned", { id: "s1" }); send("session.archived", { id: "s2" }); send("session.created", { id: "s3", app: "codex", folder: "C:/proof/app" }); send("view.layout", { level: "grove" }); send("notify", { message: "Review", level: "warning", approvalId: "approval" }); send("nightshift.task.updated", { id: "task", status: "done", evidence: "receipt" });
    const source = row("s1", ""), display = withOverrides(source, state.overrides, state.projects);
    require(display.title === "Renamed" && display.pinned && placeSession(display).project === "proof" && state.created.s3.cwd === "C:/proof/app" && state.notices.at(-1).approvalId === "approval" && state.nightshift.task.evidence === "receipt" && withOverrides({ id: "s2" }, state.overrides, state.projects).archived, "Bus action did not reach display state");
    const observedOverrides = state.overrides, observedProjects = state.projects;
    witness("overrides", () => checkOverrides(source, observedOverrides, observedProjects, display), () => checkOverrides(source, observedOverrides, observedProjects, { ...display, title: "Old" }));
    const before = initialOsState(), payload = { id: "new", title: "New title" }, next = reduceUiAction(before, "session.renamed", payload);
    witness("reducer", () => checkUiAction(before, "session.renamed", payload, next), () => checkUiAction(before, "session.renamed", payload, { ...next, overrides: { new: { title: "Old title" } } }));
    send("session.moved", { id: "s1", project: "subject:x" }); require(withOverrides(source, state.overrides, {}).projectOverride.name === "Sorted chats" && withOverrides(source, state.overrides, { "subject:x": { name: "Planning", path: null, subject: true } }).projectOverride.name === "Planning", "Subject folder name missing");
    send("session.moved", { id: "s1", clearOverride: true }); require(!Object.hasOwn(state.overrides.s1, "project") && withOverrides(source, state.overrides, {}).title === "Renamed", "Undo replaced the original folder rule");
    require(placeSession(withOverrides({ id: "x", cwd: "C:/proof/app" }, { x: { project: null } }, {})).group === "nofolder", "Explicit No folder lost");
    for (const [a, p] of [["pane.show", { kind: "unknown" }], ["view.layout", { level: "max" }], ["session.renamed", { id: "x" }], ["nightshift.task.updated", { id: "x", status: "later" }], ["unknown", {}]]) { let failed = false; try { send(a, p); } catch { failed = true; } require(failed, "Malformed bus payload was acknowledged"); }
    return calls + 7;
  });
  procedure("shell.scene-bubble-theme", () => {
    const saved = { theme: "neon", bubbles: [{ id: "x", x: 7, y: -1 }, { id: "x" }, null] }, initial = initialOsState(saved);
    witness("initial", () => checkInitial(saved, initial), () => checkInitial(saved, { ...initial, theme: "neon" }));
    require(initial.bubbles[0].x === 1 && initial.bubbles[0].y === 0 && initial.bubbles.length === 1 && initial.theme === "dark", "Stored junk reached shell");
    let state = initialOsState(), calls = 0; const send = (a, p) => { state = reduceUiAction(state, a, p); calls++; };
    send("view.arrange", { order: ["main", "sidebar"], dock: "left", widgets: [{ id: "needs", size: "l" }] }); require(state.layout.order.join() === "main,sidebar,panel,canopy" && state.layout.canopy === "auto", "Arrangement lost unspecified fields");
    send("view.scene", { name: "Focus" }); require(state.density === "calm" && state.layout.sidebarHidden, "Focus did not simplify setup"); send("view.scene", { name: "cockpit" }); require(state.density === "grove" && state.layout.canopy === "on" && !state.layout.sidebarHidden, "Cockpit scene did not restore regions"); send("view.scene", { save: "Review" }); send("view.scene", { name: "focus" }); send("view.arrange", { dock: "right" }); send("view.scene", { name: "review" }); require(state.layout.dock === "left" && state.density === "grove", "Saved arrangement was not restored");
    send("view.float", { id: "a" }); send("view.float", { id: "b" }); send("view.float", { id: "a" }); require(state.bubbles.length === 2 && state.bubbleOpen === "a" && state.bubbles[1].y > state.bubbles[0].y && state.bubbles.every(b => b.x === 1), "Floating duplicated or misplaced a chat"); send("view.float", { id: "a", floating: false }); require(state.bubbleOpen === null && state.bubbles.length === 1 && state.bubbles[0].id === "b", "Chat did not return from bubble");
    send("view.theme", { theme: "sunset" }); require(state.theme === "sunset", "Theme was not applied");
    for (const [a, p] of [["view.arrange", "bad"], ["view.scene", { save: "Focus" }], ["view.scene", { name: "missing" }], ["view.theme", { theme: "neon" }]]) { let failed = false; try { send(a, p); } catch { failed = true; } require(failed, "Invalid saved scene/layout accepted"); }
    return calls;
  });
  procedure("shell.launcher-to-voice", () => {
    const sources = { suites: [{ id: "documents", name: "Documents", apps: [{ id: "pdf", name: "PDF viewer", status: "ready" }, { id: "latex", name: "LaTeX", status: "coming" }] }], projects: [{ name: "proof-workbench", path: "C:/proof/workbench" }], chats: [{ id: "chat", title: "Fix PDF export", project: "proof" }] };
    const query = "new opencode chat in proof", result = searchLauncher(query, sources);
    require(result[0].payload.folder === sources.projects[0] && result[0].disabled === false && result[0].title === "New OpenCode chat in proof-workbench", "Launcher lost startable folder target");
    const pdf = searchLauncher("pdf", sources); require(pdf[0].key === "app:pdf" && pdf.some(r => r.key === "chat:chat") && searchLauncher("latex", sources)[0].disabled && parseNewChat("newsletter") === null && parseNewChat("new claude code chat").app === "claude-code", "Launcher ranking/readiness changed");
    witness("searchLauncher", () => checkLauncher(query, sources, 24, result), () => checkLauncher(query, sources, 24, result.slice(1)));
    const parsed = parseNewChat(query); witness("parseNewChat", () => checkNewChat(query, parsed), () => checkNewChat(query, { ...parsed, app: "codex" }));
    let state = initialOsState(), calls = 0; const send = (a, p) => { state = reduceUiAction(state, a, p); calls++; };
    send("newchat.open", { app: result[0].payload.app, folder: result[0].payload.folder, dictate: true }); const first = state.appSignals.shell.seq; send("session.open", { id: "chat" }); require(state.appSignals.shell.seq > first && state.appSignals.shell.action === "session.open", "Shell signal would replay an old action");
    send("app.open", { app: "notes" }); require(state.stage.suite === "documents" && state.stage.target === null, "Voice app navigation lost suite"); send("stage.close", {}); require(state.stage === null, "Close failed"); send("launcher.open", { query: "release notes" }); require(state.launcherQuery === "release notes", "Voice query lost"); const hidden = state.layout.sidebarHidden; send("sidebar.toggle", {}); require(state.layout.sidebarHidden === !hidden, "Sidebar toggle failed");
    for (const [a, p] of [["app.open", {}], ["session.open", {}], ["newchat.open", { app: "notepad" }]]) { let failed = false; try { send(a, p); } catch { failed = true; } require(failed, "Malformed voice action accepted"); }
    return calls + 6;
  });
  procedure("shell.pdf-queue-output-refresh", () => {
    let state = initialOsState(), calls = 0; const send = (a, p) => { state = reduceUiAction(state, a, p); calls++; };
    let refused = false; try { send("pdf.goto", { page: 2 }); } catch (error) { refused = /not open/.test(error.message); } require(refused, "PDF goto reached a closed app");
    send("pdf.open", { source: "C:/proof/report.pdf", page: 3 }); send("pdf.goto", { page: 2 }); send("pdf.zoom", { scale: "fit-width" }); send("pdf.search", { query: "manual" }); send("pdf.highlight", { page: 1, text: "same state" }); require(state.stage.app === "pdf" && state.stage.suite === "documents" && state.stage.target === "C:/proof/report.pdf" && state.inbox.map(e => e.action).join() === "pdf.open,pdf.goto,pdf.zoom,pdf.search,pdf.highlight", "PDF queue order or destination lost");
    for (const [a, p] of [["pdf.goto", { page: 0 }], ["pdf.zoom", { scale: 9 }], ["pdf.search", {}], ["pdf.highlight", { page: 1 }], ["pdf.open", {}], ["artifact.published", {}]]) { let failed = false; try { send(a, p); } catch { failed = true; } require(failed, "Malformed app payload accepted"); }
    const notices = state.notices.length; send("artifact.published", { artifact: { id: "report", title: "Weekly report" } }); require(state.notices.length === notices + 1 && state.appSignals.outputs.payload.artifact.id === "report", "Offscreen output did not announce itself"); send("pane.show", { kind: "outputs" }); const openNotices = state.notices.length, seq = state.appSignals.outputs.seq; send("artifact.published", { artifact: { id: "next" } }); require(state.notices.length === openNotices && state.appSignals.outputs.seq > seq, "Visible Outputs did not refresh quietly"); send("pane.show", { kind: "perception" });
    return calls;
  });
  for (const contract of manual.contracts) {
    const w = witnesses.get(contract.action); let rejected = false;
    try { require(w, "Missing witness"); w.execute(); try { w.corrupt(); } catch (error) { rejected = error instanceof ModelContractError && error.contract === contract.id; } require(rejected, "Semantic corruption escaped contract"); } catch (error) { failures.push({ id: contract.id, error: error.message }); }
    observers.push({ id: contract.id, status: rejected ? "passed" : "failed", corrupt_result_rejected: rejected });
  }
  const report = { area: manual.area, status: failures.length ? "failed" : "passed", ok: !failures.length, scratchRoot: resolve(root), contractCount: manual.contracts.length, contracts: observers.map(o => ({ id: o.id, status: o.status })), procedures, observers, coverage: manual.coverage, elapsedMs: Math.round((performance.now() - started) * 100) / 100, failures, boundary: "Real shell bus reducers, sidebar grouping/cleanup, launcher, queued PDF commands, scene persistence and Outputs refresh signals. Rendering, PDF files and provider execution remain separate proof boundaries." };
  await mkdir(root, { recursive: true }); await writeFile(resolve(root, "proofs-e-shell-receipt.json"), JSON.stringify(report, null, 2) + "\n"); return report;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) { const args = process.argv.slice(2), at = args.indexOf("--root"); if (at >= 0 && !args[at + 1]) throw new Error("--root requires directory"); const report = await runProofsEShell({ root: at >= 0 ? resolve(args[at + 1]) : undefined }); console.log(JSON.stringify(report, null, args.includes("--json") ? 0 : 2)); process.exitCode = report.ok ? 0 : 1; }
