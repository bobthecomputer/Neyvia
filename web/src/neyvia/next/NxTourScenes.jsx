import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, Check, LayoutGrid, Search, SquarePen } from "lucide-react";

import "./nxPdf.css";
import "./nxDocs.css";
import "./nxWorkspace.css";
import NeyviaMessageBody from "../NeyviaMessageBody.jsx";
import { ProviderMark } from "./ProviderMark.jsx";
import { Icon, IconButton, Kbd } from "./nxPrimitives.jsx";
import { buildTree, DEFAULT_CLEANUP } from "./nxSidebarModel.js";
import { Branch, Leaf, Section } from "./NxSidebarParts.jsx";
import { ThreadHeader } from "./NxShellParts.jsx";
import { NxThread } from "./NxThread.jsx";
import { NxComposer } from "./NxComposer.jsx";
import { NxLauncher } from "./NxLauncher.jsx";
import { launcherActions, launcherProjects } from "./nxShellLauncher.js";
import { MissionView } from "./NxMissions.jsx";
import { shapeMission } from "./nxMissionsModel.js";
import { ChangesSection, RepoSection } from "./NxWorkspacePanel.jsx";
import { Phone } from "./NxMobileStudio.jsx";
import { DictationStrip, MicButton } from "./NxDictation.jsx";
import { NxPdfToolbar } from "./NxPdfToolbar.jsx";
import { NxPdfPage } from "./NxPdfPage.jsx";
import { openDocument, pageTexts, searchTexts } from "./nxPdfModel.js";
import { clearFixture, stageFixture } from "./nxStore.js";
import { LookScene, WatchingScene, FactoryScene, ConnectorsScene, ImagesScene, PlacementScene } from "./NxTourFeatureScenes.jsx";

// The tour's scenes: Neyvia's own components (sidebar rows, chat thread, composer,
// checklist, launcher, missions, workspace, PDF, dictation, phone frame) fed with
// example data and driven by the chapter's progress p (0 → 1). Nothing here is
// drawn by hand; example chats live under "tour:" ids that never reach the PC.
// The canvas is inert, so nothing in a scene can be clicked or focused.

export const TOUR_W = 1120;
export const TOUR_H = 640;

const span = (p, a, b) => Math.max(0, Math.min(1, (p - a) / (b - a)));
const typed = (text, k) => text.slice(0, Math.round(text.length * k));
const words = (text, k) => text.split(" ").slice(0, Math.max(0, Math.ceil(text.split(" ").length * k))).join(" ");
const minutesAgo = minutes => new Date(Date.now() - minutes * 60000).toISOString();
const NOOP = () => {};

const PC = { host_device_id: "tour", host_device_name: "This PC" };
const CAPS = { continue_session: true, new_session: true, stop: true, approvals: true, images: true, model_choice: true, permission_choice: true, compact: true };

/** Example chats for the sidebar (the same shape the PC's chat list returns). */
function exampleSessions(activeId, activeTitle, activeStatus = "working", activeApp = "neyvia") {
  const row = (id, app, title, project, minutes, extra = {}) => ({
    id, app, title, project, cwd: `C:\\Users\\you\\Projects\\${project}`, git_branch: "main", category: app === "neyvia" ? "native" : "connected",
    status: "idle", updated_at: minutesAgo(minutes), project_known: true, capabilities: CAPS, ...PC, ...extra,
  });
  return [
    row(activeId, activeApp, activeTitle, "pocket-garden", 0, { status: activeStatus, status_since: minutesAgo(1) }),
    row("tour:s2", "claude-code", "Fix the sign-in redirect", "pocket-garden", 42),
    row("tour:s3", "codex", "Release notes for 1.4", "pocket-garden", 180),
    row("tour:s4", "codex", "Speed up the photo upload", "pocket-garden", 60 * 26, { status: "waiting_approval", unread: true }),
    row("tour:s5", "claude-code", "Chapter 4 summary", "biology", 60 * 50),
    row("tour:s6", "neyvia", "Weekly plan", "notes", 60 * 72),
  ];
}

function TourSidebar({ sessions, activeId }) {
  const tree = useMemo(() => buildTree(sessions, { policy: DEFAULT_CLEANUP }), [sessions]);
  const now = Date.now();
  return (
    <aside className="nx-side nx-tour-side" aria-label="Chats">
      <div className="nx-side-top">
        <div className="nx-brand"><ProviderMark id="neyvia" size={20} /><span>Neyvia</span></div>
        <div className="nx-side-top-actions">
          <IconButton icon={Activity} label="Agents" />
          <IconButton icon={LayoutGrid} label="Apps" />
          <IconButton icon={SquarePen} label="New chat" />
        </div>
      </div>
      <label className="nx-search"><Icon as={Search} size={14} /><input type="search" placeholder="Search chats" readOnly tabIndex={-1} /><Kbd>Ctrl K</Kbd></label>
      <nav className="nx-side-list nx-scroll" aria-label="Chats">
        {tree.needsYou.length ? (
          <Section id="tour.needs" title="Needs you" tone="gold" count={tree.needsYou.length}>
            <div className="nx-branch is-flat">{tree.needsYou.map(leaf => <Leaf key={leaf.session.id} leaf={leaf} active={false} onSelect={NOOP} now={now} />)}</div>
          </Section>
        ) : null}
        <div className="nx-side-label"><span>Projects</span></div>
        {tree.projects.map(branch => <Branch key={branch.name} branch={branch} activeId={activeId} onSelect={NOOP} now={now} />)}
      </nav>
    </aside>
  );
}

/** Put an example thread on screen under a tour: id; it is removed when the scene ends. */
function useExampleThread(id, frame) {
  const key = JSON.stringify(frame);
  useEffect(() => {
    stageFixture(id, { thread: { items: frame.items, context: frame.context || null }, run: frame.run || null });
  }, [id, key]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => clearFixture(id), [id]);
}

let seq = 0;
const at = minutesAgo(1);
function item(id, kind, data, extra = {}) { seq += 1; return { id, seq: Number(id.replace(/\D/g, "")) || seq, kind, at, data, ...extra }; }
const planOp = (steps, current) => ({ op: "replace", source: "neyvia-intent", items: steps.map((text, index) => ({ id: String(index + 1), text, active: null, status: index < current ? "completed" : index === current ? "in_progress" : "pending" })) });

/** A chat column: the real header, thread and composer for one example session. */
function ChatColumn({ session }) {
  return (
    <main className="nx-main">
      <ThreadHeader session={session} onBack={NOOP} phone={false} panels sidebarHidden={false} onToggleSidebar={NOOP} panelOpen={false} panelTab="workspace" onPanel={NOOP} floating={false} />
      <div className="nx-main-body">
        <NxThread sessionId={session.id} appName="Neyvia" />
        <NxComposer sessionId={session.id} session={session} appName="Neyvia" onOpenChat={NOOP} />
      </div>
    </main>
  );
}

// ---------------------------------------------------------------- chapters

const ASK = "Three things: sum up notes.md, draft release notes from the last commits, and remind me tomorrow at 9 to send them.";
const STEPS = ["Sum up notes.md", "Draft the release notes", "Reminder tomorrow at 9"];
const ANSWER = "Done. **notes.md**: the beta ships Friday and the sign-in fix is in review. **Release notes** are in `RELEASE.md` (6 changes). I'll remind you **tomorrow at 9:00** to send them.";

function Basics({ p }) {
  const id = "tour:basics";
  const done = p > 0.92;
  const sessions = useMemo(() => exampleSessions(id, "Sum up, release notes, reminder", done ? "idle" : "working"), [done]);
  const session = sessions[0];
  const items = [];
  if (p > 0.04) items.push(item("i1", "user", { text: ASK }));
  if (p > 0.12) items.push(item("i2", "reasoning", { summary: "Three separate asks. I'll put them on the checklist, then do them one by one." }));
  if (p > 0.2) items.push(item("i3", "tool", { name: "update_plan", category: "other", title: "Checklist", status: "ok", plan: planOp(STEPS, 0) }));
  if (p > 0.3) items.push(item("i4", "tool", { name: "neyvia_workspace_read", category: "read", title: "notes.md", status: p > 0.36 ? "ok" : "running", output: "# Notes\nBeta ships Friday…" }));
  if (p > 0.38) items.push(item("i5", "tool", { name: "update_plan", category: "other", title: "Checklist", status: "ok", plan: planOp(STEPS, 1) }));
  if (p > 0.44) items.push(item("i6", "tool", { name: "terminal_exec", category: "command", title: "git log --oneline -6", status: p > 0.5 ? "ok" : "running", output: "a1c9e2 Fix sign-in redirect\n…" }));
  if (p > 0.53) items.push(item("i7", "tool", { name: "workspace_write", category: "edit", title: "RELEASE.md", status: "ok" }));
  if (p > 0.58) items.push(item("i8", "tool", { name: "update_plan", category: "other", title: "Checklist", status: "ok", plan: planOp(STEPS, 2) }));
  if (p > 0.64) items.push(item("i9", "tool", { name: "neyvia.schedule.create", category: "other", title: "Tomorrow 09:00 · send the release notes", status: "ok" }));
  if (p > 0.7) items.push(item("i10", "tool", { name: "update_plan", category: "other", title: "Checklist", status: "ok", plan: planOp(STEPS, 3) }));
  if (p > 0.74) items.push(item("i11", "assistant", { text: words(ANSWER, span(p, 0.74, 0.92)) }, { streaming: !done }));
  const run = p > 0.04 && !done ? { runId: "tour-run", state: "running", startedAt: minutesAgo(0.2), canStop: true } : null;
  useExampleThread(id, { items, run, context: { used_tokens: 18400, window_tokens: 200000 } });
  return (
    <div className="nx-tour-os">
      <TourSidebar sessions={sessions} activeId={id} />
      <ChatColumn session={session} />
    </div>
  );
}

function useLauncherData(sessions) {
  return useMemo(() => ({
    actions: launcherActions({ density: "workshop", theme: "dark", arranging: false, scenes: {}, sidebarHidden: false, stage: null, chatId: null, floating: false, hasPrevious: false }),
    projects: launcherProjects(sessions),
    chats: sessions.map(row => ({ id: row.id, title: row.title, project: row.project })),
  }), [sessions]);
}

function Launcher({ p }) {
  const id = "tour:launcher";
  const sessions = useMemo(() => exampleSessions(id, "Chapter 4 questions", "idle"), []);
  useExampleThread(id, { items: [item("i1", "user", { text: "Can you check chapter 4 with me?" }), item("i2", "assistant", { text: "Sure. Open the notes and I'll follow along." })] });
  const data = useLauncherData(sessions);
  const open = p > 0.18;
  const suite = p > 0.4 && p < 0.62 ? "documents" : null;
  const query = p >= 0.66 ? typed("notes", span(p, 0.66, 0.78)) : "";
  return (
    <div className="nx-tour-os">
      <TourSidebar sessions={sessions} activeId={id} />
      <ChatColumn session={sessions[0]} />
      {p > 0.04 && !open ? <div className="nx-tour-keys"><Kbd>Ctrl</Kbd><Kbd>Space</Kbd></div> : null}
      {open ? <NxLauncher demo={{ query, suite }} actions={data.actions} projects={data.projects} chats={data.chats} onRun={NOOP} /> : null}
    </div>
  );
}

const CHANGES = [
  { path: "src/auth/redirect.ts", status: "M", additions: 12, deletions: 3 },
  { path: "src/auth/redirect.test.ts", status: "A", additions: 28, deletions: 0 },
  { path: "CHANGELOG.md", status: "M", additions: 2, deletions: 0 },
];

function Workspace({ p }) {
  const id = "tour:workspace";
  const done = p > 0.8;
  const sessions = useMemo(() => exampleSessions(id, "Return to the page after sign-in", done ? "idle" : "working"), [done]);
  const shown = CHANGES.filter((_, index) => p > 0.25 + index * 0.17);
  const items = [item("i1", "user", { text: "After sign-in we land on / instead of the page we came from. Fix it and add a test." })];
  if (p > 0.18) items.push(item("i2", "tool", { name: "Edit", category: "edit", title: "src/auth/redirect.ts", status: "ok" }));
  if (p > 0.38) items.push(item("i3", "tool", { name: "Write", category: "edit", title: "src/auth/redirect.test.ts", status: "ok" }));
  if (p > 0.55) items.push(item("i4", "tool", { name: "Bash", category: "command", title: "npm test -- redirect", status: p > 0.66 ? "ok" : "running", output: "✓ returns to the page you came from" }));
  if (p > 0.72) items.push(item("i5", "assistant", { text: "Sign-in now returns you to the page you came from, with a test for it. Three files changed; they're in the Workspace panel." }));
  useExampleThread(id, { items, run: done ? null : { runId: "tour-ws", state: "running", startedAt: minutesAgo(0.5) } });
  const data = {
    cwd: "C:\\Users\\you\\Projects\\pocket-garden", branch: "fix/sign-in", upstream: "origin/fix/sign-in", ahead: done ? 1 : 0, behind: 0,
    repo: { name: "pocket-garden", root: "C:\\Users\\you\\Projects\\pocket-garden", remoteUrl: "https://github.com/you/pocket-garden.git", github: { owner: "you", name: "pocket-garden", url: "https://github.com/you/pocket-garden" } },
    worktrees: [], changes: shown,
  };
  return (
    <div className="nx-tour-os">
      <TourSidebar sessions={sessions} activeId={id} />
      <ChatColumn session={sessions[0]} />
      <aside className="nx-tour-panel nx-ws" aria-label="Workspace">
        <RepoSection data={data} />
        <ChangesSection data={data} plan={{ commit: false }} onOpen={NOOP} />
      </aside>
    </div>
  );
}

// ---- what is unique to Neyvia: three chapters that need their own example threads ----

const LOOK_STEPS = ["Look at the page", "Fix what is off", "Look again"];
function LayaLook({ p }) {
  const id = "tour:laya";
  const done = p > 0.9;
  const sessions = useMemo(() => exampleSessions(id, "Settings on a phone", done ? "idle" : "working"), [done]);
  const items = [item("i1", "user", { text: "The Settings page looks off on my phone. Can you check it?" })];
  if (p > 0.12) items.push(item("i2", "tool", { name: "update_plan", category: "other", title: "Checklist", status: "ok", plan: planOp(LOOK_STEPS, p > 0.72 ? 3 : p > 0.5 ? 1 : 0) }));
  if (p > 0.2) items.push(item("i3", "tool", { name: "neyvia.laya_glance", category: "read", title: "LAYA: Settings at 390 px", status: p > 0.34 ? "ok" : "running",
    output: p > 0.34 ? "The theme list runs 24 px past the right edge.\nThe Save button sits under the bottom bar." : "looking…" }));
  if (p > 0.5) items.push(item("i4", "tool", { name: "Edit", category: "edit", title: "src/settings.css", status: "ok" }));
  if (p > 0.6) items.push(item("i5", "tool", { name: "neyvia.laya_glance", category: "read", title: "LAYA: Settings at 390 px, again", status: p > 0.72 ? "ok" : "running", output: p > 0.72 ? "Everything fits. Nothing is clipped." : "looking…" }));
  if (p > 0.76) items.push(item("i6", "assistant", { text: words("Fixed. The theme list now wraps and Save sits above the bar. LAYA looked at the page before and after, on the small local model, so no screenshot went to the big one.", span(p, 0.76, 0.93)) }, { streaming: !done }));
  const run = p > 0.04 && !done ? { runId: "tour-laya", state: "running", startedAt: minutesAgo(0.2), canStop: true } : null;
  useExampleThread(id, { items, run, context: { used_tokens: 9800, window_tokens: 200000 } });
  return (
    <div className="nx-tour-os">
      <TourSidebar sessions={sessions} activeId={id} />
      <ChatColumn session={sessions[0]} />
    </div>
  );
}

const MANUAL_STEPS = ["Run the Notes manual", "Look at the window", "Report with receipts"];
function Manuals({ p }) {
  const id = "tour:manuals";
  const done = p > 0.9;
  const sessions = useMemo(() => exampleSessions(id, "Check that Notes saves", done ? "idle" : "working"), [done]);
  const items = [item("i1", "user", { text: "Check that Notes saves what I type, and prove it." })];
  if (p > 0.14) items.push(item("i2", "tool", { name: "update_plan", category: "other", title: "Checklist", status: "ok", plan: planOp(MANUAL_STEPS, p > 0.7 ? 3 : p > 0.5 ? 1 : 0) }));
  if (p > 0.24) items.push(item("i3", "tool", { name: "neyvia.manual_run", category: "other", title: "notes: save-and-read", status: p > 0.48 ? "ok" : "running",
    output: p > 0.48 ? "pass  opens with an empty note\npass  typed text is saved to the file\npass  the file reads back the same text" : "running the procedure…" }));
  if (p > 0.56) items.push(item("i4", "tool", { name: "neyvia.laya_glance", category: "read", title: "Look at the Notes window", status: p > 0.66 ? "ok" : "running", output: "The note title shows in the header and the text is visible." }));
  if (p > 0.74) items.push(item("i5", "assistant", { text: words("Notes passes **4 of 4** checks. Each one has a receipt saved with this chat, so you can open it and see what was checked.", span(p, 0.74, 0.92)) }, { streaming: !done }));
  const run = p > 0.04 && !done ? { runId: "tour-manual", state: "running", startedAt: minutesAgo(0.2), canStop: true } : null;
  useExampleThread(id, { items, run, context: { used_tokens: 12100, window_tokens: 200000 } });
  return (
    <div className="nx-tour-os">
      <TourSidebar sessions={sessions} activeId={id} />
      <ChatColumn session={sessions[0]} />
    </div>
  );
}

const MOD_STEPS = ["See who else is working here", "Fix the redirect", "Run the checks"];
function ClaudeMod({ p }) {
  const id = "tour:claudemod";
  const done = p > 0.9;
  const sessions = useMemo(() => exampleSessions(id, "Fix the sign-in redirect", done ? "idle" : "working", "claude-code"), [done]);
  const items = [item("i1", "user", { text: "Fix the sign-in redirect so it returns to the page I came from." })];
  if (p > 0.12) items.push(item("i2", "tool", { name: "update_plan", category: "other", title: "Checklist", status: "ok", plan: planOp(MOD_STEPS, p > 0.7 ? 3 : p > 0.5 ? 2 : p > 0.34 ? 1 : 0) }));
  if (p > 0.2) items.push(item("i3", "tool", { name: "mcp__neyvia__activity", category: "read", title: "neyvia activity", status: p > 0.3 ? "ok" : "running", output: "Codex is writing release notes in RELEASE.md. Nothing else touches src/auth." }));
  if (p > 0.38) items.push(item("i4", "tool", { name: "Edit", category: "edit", title: "src/auth/redirect.ts", status: "ok" }));
  if (p > 0.54) items.push(item("i5", "tool", { name: "mcp__neyvia__manual_run", category: "other", title: "sign-in: return-to-page", status: p > 0.68 ? "ok" : "running", output: p > 0.68 ? "pass  lands on the page the visitor came from" : "running the procedure…" }));
  if (p > 0.74) items.push(item("i6", "assistant", { text: words("Fixed. After sign-in you land on the page you came from, and the check for it passes.", span(p, 0.74, 0.92)) }, { streaming: !done }));
  const run = p > 0.04 && !done ? { runId: "tour-claude", state: "running", startedAt: minutesAgo(0.2), canStop: true } : null;
  useExampleThread(id, { items, run, context: { used_tokens: 31200, window_tokens: 200000 } });
  return (
    <div className="nx-tour-os">
      <TourSidebar sessions={sessions} activeId={id} />
      <ChatColumn session={sessions[0]} />
    </div>
  );
}

function CodexSkills({ p }) {
  const id = "tour:codexskills";
  const done = p > 0.9;
  const sessions = useMemo(() => exampleSessions(id, "Numbers from the lab report", done ? "idle" : "working", "codex"), [done]);
  const items = [item("i1", "user", { text: "Read lab-report.pdf and pull out the three measurements." })];
  if (p > 0.12) items.push(item("i2", "tool", { name: "skill", category: "read", title: "neyvia-pdf", status: "ok", output: "Open a PDF, search it, read a page, highlight." }));
  if (p > 0.3) items.push(item("i3", "tool", { name: "neyvia_pdf_search", category: "read", title: "\"mg/L\" in lab-report.pdf", status: p > 0.44 ? "ok" : "running", output: "page 2: 4.8 mg/L\npage 3: 12.1 mg/L\npage 3: 0.6 mg/L" }));
  if (p > 0.5) items.push(item("i4", "tool", { name: "neyvia_pdf_highlight", category: "edit", title: "3 highlights on pages 2 and 3", status: "ok" }));
  if (p > 0.66) items.push(item("i5", "assistant", { text: words("The three measurements are **4.8**, **12.1** and **0.6 mg/L**. I highlighted each one in the PDF.", span(p, 0.66, 0.9)) }, { streaming: !done }));
  const run = p > 0.04 && !done ? { runId: "tour-codex", state: "running", startedAt: minutesAgo(0.2), canStop: true } : null;
  useExampleThread(id, { items, run, context: { used_tokens: 22800, window_tokens: 200000 } });
  return (
    <div className="nx-tour-os">
      <TourSidebar sessions={sessions} activeId={id} />
      <ChatColumn session={sessions[0]} />
    </div>
  );
}

function missionAt(p) {
  const status = (start, end) => (p > end ? "done" : p > start ? "running" : "waiting");
  return shapeMission({
    id: "tour-m", goal: "Ship the Pocket Garden beta by Friday", folder: "C:\\Users\\you\\Projects\\pocket-garden", updatedAt: minutesAgo(2),
    status: p < 0.25 ? "draft" : "running", executionStatus: p > 0.92 ? "finished" : "running",
    acceptance: p > 0.92 ? "evidence_ready_for_review" : "pending", acceptanceChecks: ["Tests pass", "The new screen works on a phone", "Release notes list every change"],
    usage: p > 0.25 ? { reportedTokens: Math.round(span(p, 0.25, 0.92) * 184000), complete: p > 0.92 } : null,
    tasks: [
      { id: "tour-m:fix", title: "Fix the open bugs", harness: "claude-code", model: "Sonnet", status: status(0.28, 0.55), needs: [], prompt: "Fix the two open sign-in bugs with tests." },
      { id: "tour-m:notes", title: "Write the release notes", harness: "codex", model: "GPT-5.6", status: status(0.3, 0.62), needs: [], prompt: "Draft release notes from the commits since 1.3." },
      { id: "tour-m:phone", title: "Check it on a phone", harness: "neyvia", status: status(0.6, 0.9), needs: ["tour-m:fix"], prompt: "Preview the app on an iPhone frame and report layout problems." },
    ],
  });
}

function Missions({ p }) {
  const mission = useMemo(() => missionAt(p), [Math.round(p * 50)]); // eslint-disable-line react-hooks/exhaustive-deps
  return <div className="nx-tour-stage nx-ms"><MissionView mission={mission} onChanged={NOOP} /></div>;
}

const PDF_URL = "/tour/sample-notes.pdf";
function usePdf() {
  const [state, setState] = useState(null);
  useEffect(() => {
    let live = true;
    let doc = null;
    openDocument({ url: new URL(PDF_URL, window.location.href).href })
      .then(async result => { doc = result.doc; const texts = await pageTexts(result.doc); if (live) setState({ ...result, texts }); else void doc.destroy(); })
      .catch(() => { if (live) setState({ error: true }); });
    return () => { live = false; void doc?.destroy(); };
  }, []);
  return state;
}

function Pdf({ p }) {
  const pdf = usePdf();
  const query = typed("photosynthesis", span(p, 0.12, 0.34));
  const hits = useMemo(() => (pdf?.texts && query.length > 3 ? searchTexts(pdf.texts, query).map((hit, index) => ({ ...hit, key: `${hit.page}:${index}` })) : []), [pdf, query]);
  const active = hits.length ? Math.min(hits.length - 1, Math.floor(span(p, 0.4, 0.62) * hits.length)) : 0;
  const id = "tour:pdf";
  const sessions = useMemo(() => exampleSessions(id, "Chapter 4 questions", p > 0.9 ? "idle" : "working"), [p > 0.9]); // eslint-disable-line react-hooks/exhaustive-deps
  const items = [];
  if (p > 0.5) items.push(item("i1", "user", { text: "Where is photosynthesis explained?" }));
  if (p > 0.62) items.push(item("i2", "assistant", { text: words(`On page 1, in ${hits.length || 3} places; the first is the second paragraph. I highlighted them for you.`, span(p, 0.62, 0.86)) }, { streaming: p < 0.86 }));
  useExampleThread(id, { items, run: p > 0.5 && p < 0.86 ? { runId: "tour-pdf", state: "running", startedAt: minutesAgo(0.1) } : null });
  return (
    <div className="nx-tour-os">
      <div className="nx-tour-app nx-pdf">
        <NxPdfToolbar name="biology-notes.pdf" page={1} pages={pdf?.doc?.numPages || 0} scale={1} fitWidth onOpen={NOOP} onGo={NOOP} onZoom={NOOP} onFit={NOOP}
          query={query} onQuery={NOOP} hits={hits.length} activeHit={active} onStepHit={NOOP} searchRef={null}
          canHighlight={false} onHighlight={NOOP} marks={0} marksOpen={false} onToggleMarks={NOOP} searching={false} />
        <div className="nx-pdf-body">
          <div className="nx-pdf-scroll nx-scroll">
            {pdf?.doc ? (
              <NxPdfPage doc={pdf.doc} pdfjs={pdf.pdfjs} number={1} scale={1} query={query} hits={hits} activeHit={hits[active]?.key} highlights={[]} onVisible={NOOP} pageRef={NOOP} />
            ) : <div className="nx-pdf-empty">{pdf?.error ? "The example PDF didn't load." : "Opening biology-notes.pdf…"}</div>}
          </div>
        </div>
      </div>
      <ChatColumn session={sessions[0]} />
    </div>
  );
}

const NOTE = "# Garden plan\n\nWater the basil on Mondays and Thursdays. Move the tomatoes to the sunny side next week, and ask Maya for mint cuttings.";
const SPOKEN = "Move the tomatoes to the sunny side next week, and ask Maya for mint cuttings.";

function useLevels(live) {
  const levels = useRef(Array.from({ length: 24 }, () => 0));
  if (live) levels.current = levels.current.map((_, index) => 0.15 + Math.abs(Math.sin(Date.now() / 140 + index * 0.9)) * 0.55);
  return levels;
}

function Notes({ p }) {
  const listening = p > 0.18 && p < 0.7;
  const finishing = p >= 0.7 && p < 0.78;
  const partial = listening ? words(SPOKEN, span(p, 0.22, 0.68)) : "";
  const levels = useLevels(listening);
  const dictation = {
    state: { status: listening ? "listening" : finishing ? "finishing" : "idle", message: listening ? "Listening… release to stop" : finishing ? "Writing…" : "" },
    partial, levels, busy: listening, active: listening, press: NOOP, release: NOOP, cancel: NOOP, clear: NOOP, prewarm: NOOP,
  };
  const head = NOTE.slice(0, NOTE.indexOf("Move the"));
  const text = p >= 0.74 ? NOTE : head;
  return (
    <div className="nx-tour-stage">
      <section className="nx-notes-editor nx-tour-note" aria-label="Garden plan">
        <div className="nx-docs-bar">
          <strong className="nx-docs-title">Garden plan</strong>
          <span className={`nx-notes-status is-${p >= 0.78 ? "saved" : "idle"}`}>{p >= 0.78 ? "Saved" : ""}</span>
          <span className="nx-docs-spacer" />
          <MicButton dictation={dictation} size={30} />
        </div>
        <div className="nx-notes-dictation"><DictationStrip dictation={dictation} /></div>
        <div className="nx-notes-panes is-split">
          <textarea className="nx-notes-text nx-scroll" value={text} readOnly tabIndex={-1} aria-label="Note text" />
          <div className="nx-notes-preview nx-scroll" aria-label="Preview"><NeyviaMessageBody text={text} /></div>
        </div>
      </section>
    </div>
  );
}

const IPHONE = { id: "iphone-16", name: "iPhone 16", platform: "ios", width: 393, height: 852, radius: 55, cutout: "island", statusBar: 54, home: "indicator", safe: { portrait: [59, 0, 34, 0], landscape: [0, 59, 21, 59] } };
const PIXEL = { id: "pixel-9", name: "Pixel 9", platform: "android", width: 412, height: 923, radius: 46, cutout: "punch", statusBar: 40, home: "gesture", safe: { portrait: [40, 0, 24, 0], landscape: [24, 0, 24, 40] } };

function Studio({ p }) {
  const landscape = p > 0.55 && p < 0.85;
  return (
    <div className="nx-tour-stage is-center nx-tour-phone">
      <div className="nx-tour-phone-label"><b>Mobile Studio</b><span>{IPHONE.name} · {landscape ? "landscape" : "portrait"}{p > 0.85 ? " · dark" : ""}</span><small>Your web app, live as you edit</small></div>
      <Phone device={IPHONE} orientation={landscape ? "landscape" : "portrait"} dark={p > 0.85} src="/tour/phone-demo.html" sandbox="allow-same-origin" scale={landscape ? 0.62 : 0.68} app={null} />
    </div>
  );
}

function PhoneChats({ p }) {
  const id = "tour:phone";
  const sessions = useMemo(() => exampleSessions(id, "Faster uploads on slow Wi-Fi", p > 0.88 ? "idle" : "working"), [p > 0.88]); // eslint-disable-line react-hooks/exhaustive-deps
  const tree = useMemo(() => buildTree(sessions, { policy: DEFAULT_CLEANUP }), [sessions]);
  const openChat = p > 0.42;
  const items = [item("i1", "user", { text: "Make the photo upload faster on slow Wi-Fi." })];
  if (p > 0.5) items.push(item("i2", "tool", { name: "Edit", category: "edit", title: "src/upload.ts", status: "ok" }));
  if (p > 0.64) items.push(item("i3", "assistant", { text: words("Photos are now resized on the phone before upload, so a 12 MB picture sends as about 900 KB. Tests pass.", span(p, 0.64, 0.88)) }, { streaming: p < 0.88 }));
  useExampleThread(id, { items, run: openChat && p < 0.88 ? { runId: "tour-phone", state: "running", startedAt: minutesAgo(0.3) } : null });
  return (
    <div className="nx-tour-stage is-center nx-tour-phone">
      <div className="nx-tour-phone-label"><b>Neyvia on your phone</b><span>Same chats, running on your PC</span><small>Open it from the browser over your private network</small></div>
      <Phone device={PIXEL} orientation="portrait" dark scale={0.62} app={null}>
        {openChat ? (
          <div className="nx-tour-phone-chat"><NxThread sessionId={id} appName="Neyvia" /></div>
        ) : (
          <div className="nx-side nx-tour-phone-side">
            <div className="nx-side-top"><div className="nx-brand"><ProviderMark id="neyvia" size={20} /><span>Neyvia</span></div></div>
            <nav className="nx-side-list">
              {tree.needsYou.length ? <Section id="tour.phone.needs" title="Needs you" tone="gold" count={tree.needsYou.length}><div className="nx-branch is-flat">{tree.needsYou.map(leaf => <Leaf key={leaf.session.id} leaf={leaf} active={false} onSelect={NOOP} now={Date.now()} />)}</div></Section> : null}
              {tree.projects.map(branch => <Branch key={branch.name} branch={branch} activeId={p > 0.34 ? id : null} onSelect={NOOP} now={Date.now()} quiet />)}
            </nav>
          </div>
        )}
      </Phone>
    </div>
  );
}

function AsksFirst({ p }) {
  const id = "tour:asks";
  const approved = p > 0.68;
  const done = p > 0.9;
  const sessions = useMemo(() => exampleSessions(id, "Publish the 1.4 release", done ? "idle" : approved ? "working" : "waiting_approval"), [done, approved]);
  const items = [item("i1", "user", { text: "Tag 1.4 and push it." }), item("i2", "tool", { name: "terminal_exec", category: "command", title: "git tag v1.4", status: "ok" })];
  if (approved) items.push(item("i3", "tool", { name: "terminal_exec", category: "command", title: "git push origin main --tags", status: p > 0.8 ? "ok" : "running", output: "To github.com:you/pocket-garden.git\n * [new tag] v1.4 -> v1.4" }));
  if (p > 0.82) items.push(item("i4", "assistant", { text: "Pushed. v1.4 is on GitHub." }));
  const pending = p > 0.18 && !approved ? {
    requestId: "tour-approve", kind: "approval", title: "Neyvia wants to run a command", command: "git push origin main --tags",
    cwd: "C:\\Users\\you\\Projects\\pocket-garden", detail: "This sends your commits and the new tag to GitHub.", choices: ["approve", "deny"],
  } : null;
  const run = done ? null : { runId: "tour-ask", state: pending ? "waiting_approval" : "running", startedAt: minutesAgo(0.4), canStop: true, pendingRequest: pending };
  useExampleThread(id, { items, run });
  return (
    <div className="nx-tour-os">
      <TourSidebar sessions={sessions} activeId={id} />
      <ChatColumn session={sessions[0]} />
    </div>
  );
}

function Help({ p }) {
  const id = "tour:help";
  const sessions = useMemo(() => exampleSessions(id, "Weekly plan", "idle"), []);
  useExampleThread(id, { items: [item("i1", "user", { text: "What's on this week?" }), item("i2", "assistant", { text: "Friday: the beta ships. Thursday: book the room." })] });
  const data = useLauncherData(sessions);
  const open = p > 0.14;
  const query = p > 0.5 ? typed("settings", span(p, 0.5, 0.66)) : typed("tour", span(p, 0.2, 0.32));
  return (
    <div className="nx-tour-os">
      <TourSidebar sessions={sessions} activeId={id} />
      <ChatColumn session={sessions[0]} />
      {p > 0.02 && !open ? <div className="nx-tour-keys"><Kbd>Ctrl</Kbd><Kbd>Space</Kbd></div> : null}
      {open ? <NxLauncher demo={{ query }} actions={data.actions} projects={data.projects} chats={data.chats} onRun={NOOP} /> : null}
    </div>
  );
}

/** Chapter id → scene. The chapters and their words live in config/neyvia_onboarding.json. */
export const SCENES = {
  laya: LayaLook,
  look: LookScene,
  watching: WatchingScene,
  factory: FactoryScene,
  connectors: ConnectorsScene,
  images: ImagesScene,
  placement: PlacementScene,
  basics: Basics,
  launcher: Launcher,
  workspace: Workspace,
  orchestration: Missions,
  manuals: Manuals,
  claudemod: ClaudeMod,
  codexskills: CodexSkills,
  missions: Missions,
  pdf: Pdf,
  notes: Notes,
  studio: Studio,
  phone: PhoneChats,
  lab: AsksFirst,
  help: Help,
};
