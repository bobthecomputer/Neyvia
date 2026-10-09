// Development only (`?fixtures=1` under `vite dev`): a small stand-in for the backend's
// voice grammar (plans/15-handoff.md "## T3"), so the voice UI can be designed and
// checked before the real command lands. Same answer shape; English only; a subset.
// The real parser lives in src/grant_agent/neyvia_voice.py.

const APPS = { notes: ["notes", "note"], files: ["files", "file", "explorer"], pdf: ["pdf", "pdf viewer"], "mobile-studio": ["mobile studio", "mobile"], "image-studio": ["image studio", "images"] };
const LABEL = { notes: "Notes", files: "Files", pdf: "PDF viewer", "mobile-studio": "Mobile Studio", "image-studio": "Image Studio" };
const PANES = { settings: ["settings", "setting"], runtime: ["runtimes", "runtime"], accounts: ["accounts", "account"] };
const HARNESS = { codex: "codex", claude: "claude-code", "claude code": "claude-code", neyvia: "neyvia", opencode: "opencode" };
const FOLDERS = [
  { path: "C:\\Users\\dev\\Projects\\sero", name: "sero" },
  { path: "C:\\Users\\dev\\Projects\\rtx-3090", name: "rtx-3090" },
  { path: "C:\\Users\\dev\\Projects\\dictation-phonon2", name: "dictation-phonon2" },
  { path: "C:\\Users\\dev\\Projects\\litter", name: "litter" },
];
let bus = 900000;
const event = (action, payload) => ({ id: String(++bus), ts: new Date().toISOString(), action, payload });

const normalize = text => ` ${String(text).toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, " ")} `
  .replace(/\b(please|can you|could you|hey neyvia|neyvia,|ok|okay|um|uh)\b/g, " ").replace(/\s+/g, " ").trim();
const find = (table, words) => Object.entries(table).find(([, names]) => names.some(name => words === name || words === `the ${name}` || words === `my ${name}`))?.[0];

export function fixtureVoice(command, payload, { threads, sessions }) {
  if (command === "voice_commands_command") return null; // the UI's built-in list
  const text = String(payload?.text || "");
  const said = normalize(text);
  const context = payload?.context || {};
  const base = { requestId: payload?.requestId, text, normalized: said, events: [], choices: [], error: "" };
  const done = (intent, args, say, events = []) => ({ ...base, status: payload?.dryRun ? "dry_run" : "done", intent, args, say, events: payload?.dryRun ? [] : events });
  const refused = (intent, error) => ({ ...base, status: "refused", intent, args: {}, say: error, error });
  let match;

  if ((match = said.match(/^(?:open|show|go to|switch to) (.+)$/))) {
    const target = match[1];
    const app = find(APPS, target);
    if (app) return done("app.open", { app }, `Opening ${LABEL[app]}`, [event("app.open", { app })]);
    const pane = find(PANES, target);
    if (pane) return done("pane.show", { kind: pane }, `Opening ${pane === "runtime" ? "Runtimes" : pane[0].toUpperCase() + pane.slice(1)}`, [event("pane.show", { kind: pane, target: "" })]);
    if (/^(the )?(launcher|apps)$/.test(target)) return done("launcher.open", {}, "Opening the launcher", [event("launcher.open", { query: "" })]);
    if (/^(the )?(agents|dashboard|agent dashboard)$/.test(target)) return done("dashboard.open", {}, "Here's everything working right now", [event("dashboard.open", {})]);
    const chatWords = target.replace(/^(the )?chat /, "").replace(/ chat$/, "");
    const hits = sessions.filter(session => chatWords.split(" ").every(word => session.title.toLowerCase().includes(word)));
    if (hits.length === 1) return done("session.open", { id: hits[0].id }, `Opening “${hits[0].title}”`, [event("session.open", { id: hits[0].id, title: hits[0].title })]);
    if (hits.length > 1) return { ...base, status: "ambiguous", intent: "session.open", args: {}, say: "Which chat?", choices: hits.slice(0, 5).map(hit => ({ label: hit.title, text: `open chat ${hit.title}` })) };
  }
  if (/^(close|close the app|go home|back to the chat)$/.test(said)) return done("stage.close", {}, "Back to the chat", [event("stage.close", {})]);
  if ((match = said.match(/^(?:search for|find) (.+)$/))) return done("launcher.open", { query: match[1] }, `Searching for ${match[1]}`, [event("launcher.open", { query: match[1] })]);
  if (/^(show agents|what s running|whats running)$/.test(said)) return done("dashboard.open", {}, "Here's everything working right now", [event("dashboard.open", {})]);
  if ((match = said.match(/^(?:start a |a )?new (?:(codex|claude code|claude|neyvia|opencode) )?chat(?: in ([\w -]+?))?(?: (?:about|saying) (.+))?$/))) {
    const app = match[1] ? HARNESS[match[1]] : undefined;
    let folder;
    if (match[2]) {
      const hits = FOLDERS.filter(entry => entry.name.includes(match[2].trim().replace(/\s+/g, "-")));
      if (!hits.length) return refused("newchat.open", `No folder called ${match[2]}.`);
      if (hits.length > 1) return { ...base, status: "ambiguous", intent: "newchat.open", args: {}, say: "Which folder?", choices: hits.map(hit => ({ label: hit.name, text: `new ${match[1] || ""} chat in ${hit.name}`.replace(/\s+/g, " ") })) };
      folder = hits[0];
    }
    const label = { codex: "Codex", "claude-code": "Claude Code", neyvia: "Neyvia", opencode: "OpenCode" }[app] || "";
    return done("newchat.open", { app, folder, prompt: match[3] || "" }, `New ${label ? `${label} ` : ""}chat${folder ? ` in ${folder.name}` : ""}`,
      [event("newchat.open", { app, folder, prompt: match[3] || "", dictate: !match[3] })]);
  }
  if (/^(send|send it)$/.test(said)) {
    if (context.view === "home") return refused("composer.send", "There's no message box on screen.");
    return done("composer.send", {}, "Sending", [event("composer.send", { sessionId: context.sessionId || "new" })]);
  }
  if (/^(yes )?(approve|allow it|allow)$|^(deny|reject)$/.test(said)) {
    const decision = /deny|reject/.test(said) ? "deny" : "approve";
    const pending = threads[context.sessionId]?.run?.pendingRequest;
    if (!pending || pending.kind !== "approval") return refused("run.answer", "Nothing here is waiting for your approval.");
    return done("run.answer", { sessionId: context.sessionId, decision }, `${decision === "approve" ? "Approved" : "Denied"}: ${pending.title}`,
      [event("notify", { level: decision === "approve" ? "success" : "info", message: `${decision === "approve" ? "Approved" : "Denied"}: ${pending.title}` })]);
  }
  if ((match = said.match(/^(dark|forest|light|morning|sunset|night green|night|terminal|matrix|paper|ember) theme$/))) {
    const theme = { dark: "dark", forest: "dark", light: "light", morning: "light", sunset: "sunset", "night green": "night", night: "night", terminal: "terminal", matrix: "terminal", paper: "paper", ember: "ember" }[match[1]];
    return done("view.theme", { theme }, `${match[1][0].toUpperCase()}${match[1].slice(1)} theme`, [event("view.theme", { theme })]);
  }
  if ((match = said.match(/^(calm|workshop|grove)( mode)?$/))) return done("view.layout", { level: match[1] }, `${match[1][0].toUpperCase()}${match[1].slice(1)}`, [event("view.layout", { level: match[1] })]);
  if ((match = said.match(/^(hide|show) the sidebar$/))) return done("sidebar.toggle", { hidden: match[1] === "hide" }, match[1] === "hide" ? "Sidebar hidden" : "Sidebar shown", [event("sidebar.toggle", { hidden: match[1] === "hide" })]);
  if (/^(dictate|start dictation)$/.test(said)) return done("dictation.start", { target: "composer" }, "Dictating", [event("dictation.start", { target: "composer" })]);
  if (/^take a note$/.test(said)) return done("dictation.start", { target: "notes" }, "Opening Notes to dictate", [event("app.open", { app: "notes" }), event("dictation.start", { target: "notes" })]);
  if (/^(help|what can i say)$/.test(said)) return done("voice.help", {}, "Here's what you can say", [event("voice.help", {})]);
  return { ...base, status: "no_match", intent: null, args: {}, say: `I didn't catch a command in “${text}”.`, choices: [{ label: "open notes", text: "open notes" }, { label: "show agents", text: "show agents" }, { label: "what can I say", text: "what can I say" }] };
}
