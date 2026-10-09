import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, ChevronLeft, GitBranch, PanelLeftOpen } from "lucide-react";

import { ProviderMark } from "./ProviderMark.jsx";
import { ModelPicker, PermissionPicker, forgetProviderOptions, useProviderOptions } from "./NxComposer.jsx";
import { NxFolderPicker } from "./NxFolderPicker.jsx";
import { RoutePicker, billingNote, preferredTransport } from "./NxRoutePicker.jsx";
import { MARKS_NOTICE } from "./nxLegal.js";
import { SignInCard } from "./NxSignIn.jsx";
import { appLabel } from "./NxSidebar.jsx";
import { callNx } from "./nxApi.js";
import { Icon, IconButton, Spinner, local, radioGroupKeys } from "./nxPrimitives.jsx";
import { loadList, startSession, useNx, waitForRunSession } from "./nxStore.js";
import { DictationGhost, DictationStrip, MicButton, useTextareaDictation } from "./NxDictation.jsx";

const APPS = [
  { app: "neyvia", mark: "neyvia" },
  { app: "claude-code", mark: "claude" },
  { app: "codex", mark: "codex" },
  { app: "opencode", mark: "opencode" },
];

function folderName(path) {
  return String(path || "").split(/[\\/]/).filter(Boolean).pop() || path;
}

function recentFolders(sessions) {
  const seen = new Map();
  for (const session of Object.values(sessions)) {
    if (!session?.cwd || session.origin === "neyvia-harness") continue;
    const current = seen.get(session.cwd);
    if (!current || String(session.updated_at || "") > String(current.updated_at || "")) {
      seen.set(session.cwd, { path: session.cwd, name: session.project || folderName(session.cwd), branch: session.git_branch, updated_at: session.updated_at });
    }
  }
  return [...seen.values()].sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || ""))).slice(0, 8);
}

export function NxNewChat({ phone, onBack, onStarted, sidebarHidden, onShowSidebar, home = null }) {
  const sessions = useNx(state => state.sessions);
  const sources = useNx(state => state.list.sources);
  const available = useMemo(() => APPS.filter(entry => !sources?.length || sources.some(source => source.app === entry.app && source.available !== false)), [sources]);
  const folders = useMemo(() => recentFolders(sessions), [sessions]);
  const [app, setApp] = useState(() => local.get("new.app", "neyvia"));
  const [folder, setFolder] = useState(() => local.get("new.folder", null));
  const [worktree, setWorktree] = useState(() => local.get("new.worktree", { on: false, branch: "" }));
  const [worktreeJob, setWorktreeJob] = useState(() => local.get("new.worktreeJob", null));
  const [draft, setDraft] = useState(() => local.get("draft.new", ""));
  const [choice, setChoice] = useState({});
  const [state, setState] = useState({ busy: false, error: "" });
  const input = useRef(null);
  const mounted = useRef(true);
  const formRef = useRef(null);
  const startRef = useRef(null);
  const dictation = useTextareaDictation({ inputRef: input, setText: setDraft, containerRef: formRef, kind: "new-chat", onSend: () => void startRef.current?.() });
  const [authVersion, setAuthVersion] = useState(0);
  const options = useProviderOptions(app, null, authVersion);
  const isGit = Boolean(folder?.isGit || folder?.branch || folder?.github);
  const transports = app === "claude-code" && options?.transports?.length ? options.transports : null;
  const transport = transports ? (choice.transport || preferredTransport(transports)) : null;

  useEffect(() => { if (!folder && folders[0]) setFolder(folders[0]); }, [folders, folder]);
  useEffect(() => { const timer = setTimeout(() => local.set("draft.new", draft || null), 250); return () => clearTimeout(timer); }, [draft]);
  useLayoutEffect(() => {
    const element = input.current;
    if (!element) return;
    element.style.height = "0px";
    element.style.height = `${Math.min(element.scrollHeight, 280)}px`;
  }, [draft]);
  useEffect(() => { input.current?.focus(); }, []);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { local.set("new.worktree", worktree); }, [worktree]);
  const saveJob = job => { local.set("new.worktreeJob", job); if (mounted.current) setWorktreeJob(job); };
  useEffect(() => {
    if (!worktreeJob?.jobId || !["queued", "running"].includes(worktreeJob.status) || state.busy) return;
    let alive = true, timer;
    const poll = async () => {
      try {
        const next = await callNx("connected_folder_worktree_command", { jobId: worktreeJob.jobId });
        if (!alive) return;
        saveJob({ ...next, sourcePath: worktreeJob.sourcePath });
        if (!["queued", "running"].includes(next.status)) return;
      } catch { /* Keep the durable job visible through a temporary disconnect. */ }
      if (alive) timer = setTimeout(poll, 1000);
    };
    void poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [worktreeJob?.jobId, state.busy]);

  const start = async () => {
    const message = draft.trim();
    if (!message || !folder?.path || state.busy) return;
    if (worktree.on && !worktree.branch.trim()) { setState({ busy: false, error: "Name the new branch for the worktree." }); return; }
    setState({ busy: true, error: "" });
    local.set("new.app", app);
    local.set("new.folder", folder);
    try {
      let cwd = folder.path;
      if (worktree.on) {
        const existing = worktreeJob?.sourcePath === folder.path && worktreeJob.branch === worktree.branch.trim() && worktreeJob.status !== "failed" ? worktreeJob : null;
        let created = existing || await callNx("connected_folder_worktree_command", { path: folder.path, branch: worktree.branch.trim(), confirm: true });
        saveJob({ ...created, sourcePath: folder.path });
        while (["queued", "running"].includes(created.status)) {
          await new Promise(resolve => setTimeout(resolve, 750));
          created = await callNx("connected_folder_worktree_command", { jobId: created.jobId });
          saveJob({ ...created, sourcePath: folder.path });
        }
        if (created.status === "failed") throw new Error(created.error || "The worktree couldn't be created. Check the destination folder before trying again.");
        cwd = created.path;
        setWorktree({ on: false, branch: "" });
        saveJob(null);
      }
      const run = await startSession(app, cwd, message, { model: choice.model || null, effort: choice.effort || null, permission_mode: choice.permission || null, transport });
      // Text written during checkout belongs to the next message.
      setDraft(current => current.trim() === message ? "" : current);
      if (local.get("draft.new", "").trim() === message) local.set("draft.new", null);
      // A Neyvia run names its chat a moment after it starts; open it as soon as it does.
      const sessionId = run?.sessionId || await waitForRunSession(run?.runId || run?.run?.runId);
      // Open the chat now; the full chat list (slow on a PC with many chats) catches up behind it.
      void loadList();
      if (sessionId) {
        local.set(`choice.${sessionId}`, { model: choice.model || null, effort: choice.effort || null, permission: choice.permission || null, transport });
        if (mounted.current) onStarted(sessionId);
      }
      setState({ busy: false, error: "" });
    } catch (failure) {
      setState({ busy: false, error: failure?.message || "The chat couldn't be started." });
    }
  };

  startRef.current = start;
  return (
    <div className="nx-new">
      <header className="nx-head is-bare">
        {onBack ? <IconButton icon={ChevronLeft} label="All chats" onClick={onBack} /> : null}
        {sidebarHidden ? <IconButton icon={PanelLeftOpen} label="Show sidebar" onClick={onShowSidebar} /> : null}
      </header>
      <div className="nx-new-body nx-scroll">
        <div className="nx-new-col">
          <p className="nx-new-eyebrow">A brighter tomorrow</p>
          <h1 className="nx-new-title">What would you like to do today?</h1>

          <div className="nx-new-apps" role="radiogroup" aria-label="Agent" onKeyDown={radioGroupKeys}>
            {available.map(entry => (
              <button key={entry.app} type="button" role="radio" aria-checked={app === entry.app} tabIndex={app === entry.app ? 0 : -1}
                className={`nx-app-card${app === entry.app ? " is-on" : ""}`} onClick={() => setApp(entry.app)}>
                <ProviderMark id={entry.mark} size={20} />
                <span>{appLabel(entry.app)}</span>
              </button>
            ))}
          </div>

          <div className="nx-new-folders">
            <NxFolderPicker value={folder} recent={folders} onChange={next => { setFolder(next); setWorktree({ on: false, branch: "" }); }} />
            {isGit ? (
              <label className={`nx-worktree${worktree.on ? " is-on" : ""}`}>
                <input type="checkbox" checked={worktree.on} onChange={event => setWorktree(current => ({ ...current, on: event.target.checked }))} />
                <Icon as={GitBranch} size={14} />
                <span>Work in a new worktree</span>
                {worktree.on ? (
                  <input className="nx-input is-mono" value={worktree.branch} placeholder="new-branch-name" aria-label="New branch name" spellCheck={false}
                    onChange={event => setWorktree(current => ({ ...current, branch: event.target.value }))} />
                ) : <span className="nx-worktree-hint">keeps {folder?.branch || "the current branch"} untouched</span>}
              </label>
            ) : null}
          </div>

          {worktreeJob ? <div className="nx-worktree-progress" role="status" aria-live="polite">
            <span>{worktreeJob.error || worktreeJob.message || "Preparing worktree"}{worktreeJob.progress != null ? ` · ${worktreeJob.progress}%` : "…"}</span>
            {["queued", "running"].includes(worktreeJob.status) ? <><progress max="100" value={worktreeJob.progress ?? undefined} aria-label="Worktree checkout" /><small>Runs in the background. You can keep writing or open another chat.</small></> : null}
          </div> : null}

          <form ref={formRef} className="nx-composer is-hero" onSubmit={event => { event.preventDefault(); void start(); }}>
            <DictationStrip dictation={dictation} />
            <textarea ref={input} rows={3} value={draft} placeholder={`Ask ${appLabel(app)} to…`} aria-label="First message"
              onChange={event => setDraft(event.target.value)}
              onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); void start(); } }} />
            <DictationGhost dictation={dictation} />
            <div className="nx-composer-bar">
              <div className="nx-composer-left">
                <ModelPicker app={app} models={options?.models || []} value={choice.model || null} effort={choice.effort || null}
                  billing={app === "claude-code" ? "agent-sdk-credits" : null} note={billingNote(transports ? options : null, transport)}
                  onChange={patch => setChoice(current => ({ ...current, ...patch }))} />
                <PermissionPicker modes={options?.permissionModes || []} value={choice.permission} onChange={permission => setChoice(current => ({ ...current, permission }))} />
                <RoutePicker transports={transports} value={transport} onChange={next => setChoice(current => ({ ...current, transport: next }))} />
              </div>
              <div className="nx-composer-right">
                <MicButton dictation={dictation} />
                <button type="submit" className="nx-send" aria-label="Start chat" disabled={!draft.trim() || !folder?.path || state.busy}>
                  {state.busy ? <Spinner size={13} /> : <Icon as={ArrowUp} size={16} />}
                </button>
              </div>
            </div>
          </form>
          {state.error ? <p className="nx-new-error" role="alert">{state.error}</p> : null}
          {app !== "neyvia" ? (
            <SignInCard app={app} auth={options?.auth} onSignedIn={() => { forgetProviderOptions(app); setAuthVersion(value => value + 1); }} />
          ) : null}
          {!phone ? <p className="nx-new-hint">{app === "neyvia" ? "Runs in Neyvia with your chosen model." : app === "opencode" ? "Runs in OpenCode on your PC with its own sign-in. You approve its edits here, see the changes, and can stop it and carry on in the same chat." : `Runs in ${appLabel(app)} on your PC with its own sign-in, and shows up in ${appLabel(app)} too.`}</p> : null}
          <p className="nx-legal">{MARKS_NOTICE}</p>
        </div>
        {home}
      </div>
    </div>
  );
}
