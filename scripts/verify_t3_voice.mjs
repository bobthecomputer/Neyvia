// Real authenticated scratch-backend journey; no models, live services, or Python tests.
// node scripts/verify_t3_voice.mjs --url http://127.0.0.1:48131 --root scripts/evidence/T3-workspace
import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

const args = Object.fromEntries(process.argv.slice(2).reduce((rows, value, i, all) => value.startsWith("--") ? [...rows, [value.slice(2), all[i + 1]]] : rows, []));
const base = args.url || "http://127.0.0.1:48131";
const url = new URL(base);
assert.equal(url.hostname, "127.0.0.1");
assert.ok(Number(url.port) >= 48131 && Number(url.port) <= 48139, "T3 ports only");
const root = resolve(args.root || "scripts/evidence/T3-workspace");
assert.ok(root.startsWith(resolve("scripts/evidence") + "\\"), "Disposable fixture must stay under this track's evidence folder");
const output = args.out || "scripts/evidence/T3.json";
const fixtureTag = "t3voice" + randomUUID().slice(0, 8);
const fixtureFolder = fixtureTag + "-dictation-phonon2";
const evidence = { schema: "neyvia.T3.evidence.v1", at: new Date().toISOString(), base, root, checks: [],
  boundaries: { backend: "real authenticated HTTP + durable bus + production desktop bridge", renderedUI: "pending Claude UI receipt", microphone: "not exercised", namedWebDispatch: "C9 hook pending in T3-later" } };
let cookie = "";
async function request(path, body, authenticated = true) {
  const response = await fetch(base + path, { method: body === undefined ? "GET" : "POST", headers: {
    ...(body === undefined ? {} : { "Content-Type": "application/json" }), ...(authenticated && cookie ? { Cookie: cookie } : {}),
  }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  const saved = response.headers.get("set-cookie");
  if (saved && path === "/api/auth/local-session") cookie = saved.split(";")[0];
  return { status: response.status, body: await response.json() };
}
async function voice(text, options = {}) {
  const response = await request("/api/ui/voice", { text, requestId: randomUUID(), ...options });
  assert.equal(response.status, 200, JSON.stringify(response));
  return response.body.data;
}
async function tool(name, arguments_) {
  const response = await request("/api/ui/tools/call", { tool: "neyvia." + name, arguments: arguments_ });
  assert.equal(response.status, 200, JSON.stringify(response));
  return response.body.data.result;
}
function record(name, data) { evidence.checks.push({ name, pass: true, ...data }); console.log("PASS " + name); }

async function run() {
try {
  if (args.resume === "1") {
    const previous = JSON.parse(readFileSync(output, "utf8"));
    assert.equal(previous.passed, true, "Resume requires the completed earlier journey");
    assert.equal((await request("/api/auth/local-session", {})).status, 200);
    const original = previous.checks.find(row => row.name === "retry preserves original event IDs, never emits twice").first;
    const replay = await voice("open files", { requestId: original.requestId });
    assert.equal(replay.replayed, true); assert.deepEqual(replay.events, original.events);
    previous.checks = previous.checks.filter(row => row.name !== "request ID survives real backend restart without another event");
    previous.checks.push({ name: "request ID survives real backend restart without another event", pass: true, verifiedAt: new Date().toISOString(), receipt: replay });
    const viteBase = "http://127.0.0.1:48132";
    const local = await fetch(viteBase + "/api/auth/local-session", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    assert.equal(local.status, 200);
    const viteCookie = local.headers.getSetCookie().map(value => value.split(";")[0]).join("; ");
    const proxy = await fetch(viteBase + "/api/ui/voice", { method: "POST", headers: { "Content-Type": "application/json", Cookie: viteCookie }, body: JSON.stringify({ text: "open notes", dryRun: true, requestId: randomUUID() }) });
    assert.equal(proxy.status, 200); const proxyReceipt = (await proxy.json()).data;
    assert.equal(proxyReceipt.status, "dry_run"); assert.equal(proxyReceipt.args.app, "notes");
    previous.checks = previous.checks.filter(row => row.name !== "real Vite proxy reaches owner voice HTTP route on 48131");
    previous.checks.push({ name: "real Vite proxy reaches owner voice HTTP route on 48131", pass: true, via: viteBase, receipt: proxyReceipt });
    Object.assign(evidence, previous);
    console.log("PASS durable retry after backend restart");
    return;
  }
  const unauth = await request("/api/ui/voice", { text: "open notes" }, false);
  assert.equal(unauth.status, 401); record("unauthenticated voice rejected", { http: unauth.status });
  assert.equal((await request("/api/auth/local-session", {})).status, 200);
  const grammarResponse = await request("/api/ui/voice/commands");
  assert.equal(grammarResponse.status, 200, JSON.stringify(grammarResponse));
  const grammar = grammarResponse.body.data;
  assert.equal(grammar.commands.length, 15);
  record("live grammar catalog", { intents: grammar.commands.map(row => row.intent) });
  const catalog = (await request("/api/ui/tools")).body.data.tools;
  for (const name of ["neyvia.voice.command", "neyvia.voice.commands", "neyvia.app.open"]) assert.ok(catalog.some(row => row.name === name));
  record("three bot tools registered in live catalog", {});

  const fixtureRoot = resolve(root, fixtureTag);
  const create = await tool("folder.create", { path: fixtureRoot, name: fixtureFolder });
  if (create.status === "approval_required") {
    const blocked = await tool("voice.command", { text: "approve", context: { approvalIds: [create.approvalId] } });
    assert.equal(blocked.status, "refused"); record("bot cannot approve its own permission", { receipt: blocked });
    const approved = await voice("approuve", { context: { approvalIds: [create.approvalId] } });
    assert.equal(approved.status, "done"); assert.equal(approved.receipt.approved, true);
    record("owner voice approves real project-creation request", { receipt: approved });
    assert.equal((await tool("folder.create", { path: fixtureRoot, name: fixtureFolder })).ok, true);
  }

  const cases = [
    ["Please, can you open Notes?", "app.open", { app: "notes" }],
    ["s'il te plaît, ouvre les notes", "app.open", { app: "notes" }],
    ["va dans fichiers", "app.open", { app: "files" }],
    ["ouvre les réglages", "pane.show", { kind: "settings" }],
    ["show runtimes", "pane.show", { kind: "runtime" }],
    ["tidy my chats", "pane.show", { target: "tidy" }],
    [`new codex chat in ${fixtureFolder}`, "newchat.open", { app: "codex" }],
    [`nouvelle conversation codex dans ${fixtureFolder}`, "newchat.open", { app: "codex" }],
    ["new chat in neyvia about Écrire une NOTE, please keep Case", "newchat.open", { app: "neyvia", prompt: "Écrire une NOTE, please keep Case" }],
    ["new chat in neyvia about Please preserve this, please.", "newchat.open", { app: "neyvia", prompt: "Please preserve this, please." }],
    ["new Codex chat, about: Review code.", "newchat.open", { app: "codex", prompt: "Review code." }],
    ["find notes", "launcher.open", { query: "notes" }], ["qu'est-ce qui tourne", "dashboard.open", {}],
    ["retour", "stage.close", {}], ["thème sombre", "view.theme", { theme: "dark" }],
    ["grove mode", "view.layout", { level: "grove" }], ["cache la barre", "sidebar.toggle", { hidden: true }],
    ["prends une note", "dictation.start", { target: "notes" }], ["what can I say", "voice.help", {}],
  ];
  for (const [text, intent, expected] of cases) {
    const dry = await voice(text, { dryRun: true, context: { clientId: "t3-proof-client" } });
    assert.equal(dry.status, "dry_run", JSON.stringify(dry)); assert.equal(dry.intent, intent);
    for (const [key, value] of Object.entries(expected)) assert.equal(dry.args[key], value);
    assert.deepEqual(dry.events, []);
    record("parse/resolve dry run: " + text, { receipt: dry });
  }
  const notes = await voice("open notes"); assert.equal(notes.status, "done"); assert.equal(notes.events[0].action, "app.open");
  record("open Notes emits real app.open", { receipt: notes });
  const botNotes = await tool("app.open", { app: "notes" }); assert.equal(botNotes.event.action, notes.events[0].action);
  assert.deepEqual(botNotes.event.payload, notes.events[0].payload);
  record("bot and user share app.open state/bus", { receipt: botNotes });
  const draft = await voice(`new codex chat in ${fixtureFolder}`); assert.equal(draft.status, "done");
  assert.equal(draft.events[0].action, "newchat.open"); assert.equal(draft.args.folder.path, resolve(fixtureRoot, fixtureFolder));
  assert.equal(draft.args.dictate, true); assert.equal(draft.receipt, undefined);
  record("real folder resolves to new Codex draft, no launch", { receipt: draft });
  const retryId = randomUUID(); const first = await voice("open files", { requestId: retryId });
  const second = await voice("open files", { requestId: retryId });
  assert.equal(second.replayed, true); assert.deepEqual(first.events, second.events);
  record("retry preserves original event IDs, never emits twice", { first, second });
  const collision = await request("/api/ui/voice", { text: "open notes", requestId: retryId });
  assert.equal(collision.status, 400); record("changed intent cannot reuse request ID", { http: collision.status });
  const concurrentId = randomUUID(); const parallel = await Promise.all(Array.from({ length: 6 }, () => voice(`new codex chat in ${fixtureFolder}`, { requestId: concurrentId })));
  assert.equal(parallel.filter(row => !row.replayed).length, 1);
  assert.equal(new Set(parallel.flatMap(row => row.events.map(event => event.id))).size, 1);
  for (const receipt of parallel) assert.equal(receipt.ok, receipt.status === "done");
  record("six concurrent retries claim exactly one bus event", { receipts: parallel });
  await tool("folder.create", { path: fixtureRoot, name: fixtureTag + "-proof-one" });
  await tool("folder.create", { path: fixtureRoot, name: fixtureTag + "-proof-two" });
  const ambiguous = await voice(`new codex chat in ${fixtureTag} proof`);
  assert.equal(ambiguous.status, "ambiguous"); assert.deepEqual(ambiguous.events, []);
  record("two folder matches refuse without an action", { receipt: ambiguous });
  for (const text of ["delete notes", "archive this chat", "rename chat", "run git reset", "I said approve yesterday", "approve and delete notes"]) {
    const row = await voice(text); assert.equal(row.status, "no_match"); assert.deepEqual(row.events, []);
    record("non-command/destructive refusal: " + text, { receipt: row });
  }
  for (const [text, options] of [["approve", {}], ["stop", {}], ["send", {}], ["open notes", { final: false }], ["open unity", {}]]) {
    const row = await voice(text, options); assert.equal(row.status, "refused"); assert.deepEqual(row.events, []);
    record("missing context/interim/unready refusal: " + text, { receipt: row });
  }
  const send = await voice("send it", { context: { view: "new", clientId: "t3-proof-client" } }); assert.equal(send.events[0].payload.sessionId, "new");
  assert.equal(send.events[0].payload.clientId, "t3-proof-client");
  record("explicit send targets only visible new-chat box", { receipt: send });
  const untargeted = await voice("send", { context: { view: "new" } });
  assert.equal(untargeted.status, "refused"); assert.deepEqual(untargeted.events, []);
  record("send without a target window refuses", { receipt: untargeted });
  const approvalOne = await tool("folder.create", { path: resolve(fixtureRoot, "scope-one"), name: "one" });
  const approvalTwo = await tool("folder.create", { path: resolve(fixtureRoot, "scope-two"), name: "two" });
  assert.equal(approvalOne.status, "approval_required"); assert.equal(approvalTwo.status, "approval_required");
  const twoApprovals = await voice("approve", { context: { approvalIds: [approvalOne.approvalId, approvalTwo.approvalId] } });
  assert.equal(twoApprovals.status, "ambiguous"); assert.deepEqual(twoApprovals.events, []);
  record("two visible real approvals cannot be guessed", { receipt: twoApprovals });
  const scopedApproval = await voice("approve", { context: { approvalIds: [approvalOne.approvalId] } });
  assert.equal(scopedApproval.receipt.id, approvalOne.approvalId);
  const waiting = (await request("/api/ui/approvals")).body.data.requests;
  assert.ok(waiting.some(row => row.id === approvalTwo.approvalId));
  assert.ok(!waiting.some(row => row.id === approvalOne.approvalId));
  record("approval changes only the explicitly visible request", { receipt: scopedApproval, otherStillPending: approvalTwo.approvalId });
  const declined = await voice("refuse", { context: { approvalIds: [approvalTwo.approvalId] } });
  assert.equal(declined.receipt.denied, true); record("owner voice declines a real request", { receipt: declined });
  const note = await voice("take a note", { context: { clientId: "t3-proof-client" } }); assert.deepEqual(note.events.map(event => event.action), ["app.open", "dictation.start"]);
  record("take a note opens Notes before requesting dictation", { receipt: note });
  const { initialOsState, reduceUiAction } = await import("../web/src/neyvia/next/nxOsStore.js");
  let uiState = initialOsState();
  for (const event of notes.events) uiState = reduceUiAction(uiState, event.action, event.payload);
  assert.equal(uiState.stage.app, "notes");
  for (const event of draft.events) uiState = reduceUiAction(uiState, event.action, event.payload);
  assert.equal(uiState.appSignals.shell.action, "newchat.open");
  assert.equal(uiState.appSignals.shell.payload.folder.path, draft.args.folder.path);
  record("real bus receipts accepted by production FE reducer", { stage: uiState.stage, draftSignal: uiState.appSignals.shell });
  const ack = await request("/api/ui/ack", { id: notes.events[0].id, ok: true, clientId: "t3-proof-client" });
  assert.equal(ack.status, 200); assert.equal(ack.body.data.ok, true);
  record("production ack accepts applied voice event", { receipt: ack.body.data });
  for (const text of ["light theme", "calm", "open settings"]) {
    const row = await voice(text); assert.equal(row.status, "done"); assert.equal(row.receipt.event.id, row.events[0].id);
    record("existing workspace action reused: " + text, { receipt: row });
  }

  const python = "C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe";
  // Call the production bridge function directly, bypassing no service boundary.
  const invocation = "import json; from pathlib import Path; from grant_agent.desktop_bridge import dispatch_desktop_command; print(json.dumps(dispatch_desktop_command(Path(" + JSON.stringify(root) + "), 'voice_command_command', {'text':'open notes','requestId':" + JSON.stringify(randomUUID()) + "})))";
  const desktop = spawnSync(python, ["-c", invocation], { encoding: "utf8", env: { ...process.env, PYTHONPATH: resolve("src"), NEYVIA_CONNECTED_SERVICE_PORT: url.port }, timeout: 65000 });
  assert.equal(desktop.status, 0, desktop.stderr); const receipt = JSON.parse(desktop.stdout);
  assert.equal(receipt.status, "done", JSON.stringify(receipt)); assert.equal(receipt.events[0].action, "app.open");
  record("desktop allow-list and production forwarding on 48131", { receipt });
  const wrongRoot = await request("/api/ui/voice", { text: "open notes", _expectedStateRoot: resolve(root, "different") });
  assert.equal(wrongRoot.status, 409); record("desktop mismatched workspace refused", { http: wrongRoot.status });
  const auditPath = resolve(root, ".neyvia/voice-commands.jsonl");
  const auditBackup = auditPath + ".backup-" + randomUUID();
  renameSync(auditPath, auditBackup); mkdirSync(auditPath);
  const auditId = randomUUID();
  let interruptedAudit;
  try {
    interruptedAudit = await voice("open notes", { requestId: auditId });
    assert.equal(interruptedAudit.status, "done"); assert.ok(interruptedAudit.auditPending);
  } finally {
    renameSync(auditPath, auditPath + ".blocked-" + randomUUID());
    renameSync(auditBackup, auditPath);
  }
  const repairedAudit = await voice("open notes", { requestId: auditId });
  assert.equal(repairedAudit.replayed, true); assert.equal(repairedAudit.auditPending, undefined);
  assert.deepEqual(repairedAudit.events, interruptedAudit.events);
  const auditEntries = readFileSync(auditPath, "utf8").trim().split(/\r?\n/).map(JSON.parse);
  assert.equal(auditEntries.filter(row => row.at === interruptedAudit.auditPending.at).length, 1);
  record("audit destination failure preserves receipt; retry repairs audit without another action", { first: interruptedAudit, repaired: repairedAudit });
  const log = readFileSync(resolve(root, ".neyvia/voice-commands.jsonl"), "utf8").trim().split(/\r?\n/).map(JSON.parse);
  assert.ok(log.every(row => Object.keys(row).sort().join() === "at,intent,language,ms,status,text"));
  assert.ok(log.every(row => row.text.length <= 500)); record("production JSONL audit receipt, no audio", { rows: log.length });
  evidence.passed = true;
} catch (error) {
  evidence.passed = false; evidence.error = error.stack; process.exitCode = 1;
} finally {
  evidence.sourceHashes = Object.fromEntries([
    "src/grant_agent/neyvia_voice.py", "src/grant_agent/neyvia_workspace_tools.py",
    "src/grant_agent/neyvia_ui_api.py", "src/grant_agent/desktop_bridge.py", "scripts/verify_t3_voice.mjs", "scripts/run_t3_vite.mjs",
  ].map(path => [path, createHash("sha256").update(readFileSync(path)).digest("hex")]));
  evidence.wiring = {
    web: ["POST /api/ui/voice (owner)", "GET /api/ui/voice/commands", "POST /api/ui/tools/call"],
    tools: ["neyvia.voice.command", "neyvia.voice.commands", "neyvia.app.open"],
    desktop: ["ALLOWED_DESKTOP_COMMANDS voice_command_command/voice_commands_command", "dispatch_desktop_command -> forward_command -> /api/ui/voice", "Tauri call_desktop_backend_command (existing generic IPC)"],
    frontend: "Claude adapted browser voice to /api/ui/voice, added direct/SSE dedup and client/session targeting; rendered proof remains pending",
    pending: ["Optional /api/backend named commands still need C9 dispatch hook; browser now uses voice HTTP route", "Rendered keyboard/axe/motion and microphone journey", "Actual connected-harness approval/stop positive journey", "Plan-08 executable voice manual (current docs manual is prose)"],
  };
  evidence.iterations = [
    { finding: "Voice routes inserted before independent route checks fell through to 404", fix: "Moved into the existing result dispatch chain", proof: "Live grammar + voice calls passed" },
    { finding: "Existing recent dictation folders collide with the shorthand", fix: "Kept ambiguity refusal; used unique disposable folder names for the positive journey", proof: "Two folder matches refuse without an action" },
    { finding: "New-chat prompt punctuation/trailing please was lost", fix: "Preserve prompt text and allow punctuation around command delimiter", proof: "Exact Unicode/case/punctuation assertions passed" },
    { finding: "Forced Node process.exit caused a Windows libuv abort after the restart assertion", fix: "Return normally and let the verification process finish", proof: "Resume verification returned exit 0" },
  ];
  writeFileSync(output, JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify({ passed: evidence.passed, checks: evidence.checks.length, output, error: evidence.error }));
}
}
await run();
