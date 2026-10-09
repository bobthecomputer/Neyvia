import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckSquare, Download, FolderOpen, Hand, Pause, Play, Plus, SlidersHorizontal, Square, X } from "lucide-react";

import "./nxNightShift.css";
import { ProviderMark } from "./ProviderMark.jsx";
import { NxGrowingTree } from "./NxGrowingTree.jsx";
import { Button, Icon, IconButton, Segmented, Spinner, StatusDot, ago, useMedia } from "./nxPrimitives.jsx";
import { applyUiAction, os } from "./nxOsStore.js";
import { nightshift, useNightShift } from "./nxNightShiftApi.js";
import { BudgetPanel, EvidenceLink, MorningCard } from "./NxNightShiftParts.jsx";
import { HARNESSES, MODEL_HINTS, OWNER_FOR, PERMISSIONS, harnessLabel, morning, noteText, shapeBoard, startable, stateText } from "./nxNightShiftModel.js";
import { AgentTree as Graph, TONE } from "./NxAgentTree.jsx";

// Night Shift (plan 07 R6, plan 15 T10): a board of tasks with prerequisites.
// Ticking a task needs evidence (a file, a commit, its agent's finished run, or
// a command you vouch for); the tick is an event, and every started task whose
// prerequisites are now all done launches at once in its agent. Nothing runs
// until you start it. Lives in the Canopy as the Missions pane's second tab.

const EVIDENCE = [
  { value: "run", label: "Agent run" },
  { value: "file", label: "File" },
  { value: "commit", label: "Commit" },
  { value: "command", label: "Command" },
];

function TickForm({ task, onDone, onCancel }) {
  const [kind, setKind] = useState(task.runId && !task.paul ? "run" : "file");
  const [value, setValue] = useState({ path: "", hash: "", command: "", output: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const options = EVIDENCE.filter(option => option.value !== "run" || (task.runId && !task.paul));
  const evidence = kind === "run" ? { type: "run", runId: task.runId }
    : kind === "file" ? { type: "file", path: value.path.trim() }
      : kind === "commit" ? { type: "commit", hash: value.hash.trim() }
        : { type: "command", command: value.command.trim(), exitCode: 0, output: value.output };
  const ready = kind === "run" || (kind === "file" && evidence.path) || (kind === "commit" && evidence.hash) || (kind === "command" && evidence.command);
  const submit = async () => {
    setBusy(true); setError("");
    try {
      await nightshift("tick", { id: task.id, evidence });
      os.notify({ level: "success", message: task.dependents?.length ? `${task.title || task.id} done. Started tasks that waited for it launch now.` : `${task.title || task.id} done` });
      onDone();
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  };
  const field = (key, label, props = {}) => (
    <label className="nx-ns-field"><span>{label}</span>
      <input className={`nx-input${props.mono ? " is-mono" : ""}`} value={value[key]} placeholder={props.placeholder} onChange={event => setValue(current => ({ ...current, [key]: event.target.value }))} />
    </label>
  );
  return (
    <form className="nx-ns-form" aria-label="Mark done with evidence" onSubmit={event => { event.preventDefault(); if (ready) void submit(); }}>
      <strong>Mark done</strong>
      <p className="nx-ns-fine">A tick needs proof. Neyvia checks it before the task counts as done.</p>
      <Segmented size="sm" label="Evidence" value={kind} options={options} onChange={setKind} />
      {kind === "run" ? <p className="nx-ns-fine">Uses this task's own agent run. It must have finished.</p> : null}
      {kind === "file" ? field("path", "File, inside the task's folder", { mono: true, placeholder: "notes\\result.md" }) : null}
      {kind === "commit" ? field("hash", "Commit in the task's folder", { mono: true, placeholder: "a1b2c3d" }) : null}
      {kind === "command" ? (
        <>
          {field("command", "Command you ran", { mono: true, placeholder: "npm test" })}
          <label className="nx-ns-field"><span>What it printed</span>
            <textarea className="nx-input is-mono nx-ns-area" rows={3} value={value.output} onChange={event => setValue(current => ({ ...current, output: event.target.value }))} />
          </label>
          <p className="nx-ns-fine">Saved as your word that it passed. Neyvia doesn't run it again.</p>
        </>
      ) : null}
      {error ? <p className="nx-ns-error" role="alert">{error}</p> : null}
      <footer className="nx-ns-foot">
        <Button size="sm" onClick={onCancel}>Cancel</Button>
        <Button size="sm" variant="primary" type="submit" disabled={busy || !ready}>{busy ? "Checking…" : "Mark done"}</Button>
      </footer>
    </form>
  );
}

function BlockForm({ task, onDone, onCancel }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async () => {
    setBusy(true); setError("");
    try { await nightshift("block", { id: task.id, reason: reason.trim() }); onDone(); }
    catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  };
  return (
    <form className="nx-ns-form" aria-label="Block this task" onSubmit={event => { event.preventDefault(); if (reason.trim()) void submit(); }}>
      <label className="nx-ns-field"><span>Why it's blocked</span>
        <input className="nx-input" value={reason} autoFocus placeholder="Waiting for the new icons" onChange={event => setReason(event.target.value)} />
      </label>
      {error ? <p className="nx-ns-error" role="alert">{error}</p> : null}
      <footer className="nx-ns-foot">
        <Button size="sm" onClick={onCancel}>Cancel</Button>
        <Button size="sm" variant="warn" type="submit" disabled={busy || !reason.trim()}>Block</Button>
      </footer>
    </form>
  );
}

function EditTask({ task, board, onDone, onCancel }) {
  const [expectedUpdatedAt] = useState(task.updatedAt);
  const [title, setTitle] = useState(task.title || task.id);
  const [prompt, setPrompt] = useState(task.prompt || "");
  const [needs, setNeeds] = useState(task.needs);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const save = async () => {
    setBusy(true); setError("");
    try {
      await nightshift("edit", { id: task.id, expectedUpdatedAt, patch: { title: title.trim(), prompt: prompt.trim(), needs } });
      os.notify({ level: "success", message: "Task saved and stopped. Review it before starting again." });
      onDone();
    } catch (failure) {
      const message = failure?.message || String(failure || "Task could not be saved");
      setError(/Task changed/.test(message) ? "This task changed elsewhere. Cancel and reopen Edit task to review the latest version." : message);
    }
    finally { setBusy(false); }
  };
  return <form className="nx-ns-form" aria-label="Edit task" onSubmit={event => { event.preventDefault(); if (title.trim() && prompt.trim()) void save(); }}>
    <label className="nx-ns-field"><span>Short title</span><input className="nx-input" value={title} onChange={event => setTitle(event.target.value)} autoFocus /></label>
    <label className="nx-ns-field"><span>Task prompt</span><textarea className="nx-input nx-ns-area" rows={4} value={prompt} onChange={event => setPrompt(event.target.value)} /></label>
    <div className="nx-ns-needs" role="group" aria-label="Prerequisites"><span>Starts after</span>
      {Array.from(board.byId.values()).filter(other => other.id !== task.id).map(other => <label key={other.id}><input type="checkbox" checked={needs.includes(other.id)} onChange={event => setNeeds(current => event.target.checked ? [...current, other.id] : current.filter(id => id !== other.id))} />{other.id}</label>)}
    </div>
    <p className="nx-ns-fine">Saving stops this task. Missing prerequisites, cycles and edits to attempted tasks are refused.</p>
    {error ? <p className="nx-ns-error" role="alert">{error}</p> : null}
    <footer className="nx-ns-foot"><Button size="sm" disabled={busy} onClick={onCancel}>Cancel</Button><Button size="sm" variant="primary" type="submit" disabled={busy || !title.trim() || !prompt.trim()}>{busy ? "Saving…" : "Save changes"}</Button></footer>
  </form>;
}

function TaskDetail({ task, board, onChanged, onOpenChat, onClose }) {
  const [mode, setMode] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { setMode(""); setError(""); }, [task.id, task.status]);
  const act = async (action, payload, message) => {
    setBusy(action); setError("");
    try { await nightshift(action, payload); if (message) os.notify({ level: "info", message }); onChanged(); }
    catch (failure) { setError(failure.message); }
    finally { setBusy(""); }
  };
  const canStart = !task.paul && !task.armed && (task.status === "waiting" || task.status === "blocked");
  const canStop = !task.paul && (task.status === "running" || (task.status === "waiting" && task.armed));
  const canTick = task.status !== "done" && task.status !== "running" && !task.open?.length;
  const canBlock = task.status === "waiting";
  const canEdit = ["waiting", "blocked"].includes(task.status) && !task.runId && !task.evidence;
  const waitsFor = task.needs.map(need => board.byId.get(need) || { id: need, title: need, status: "missing" });
  const unlocks = (task.dependents || []).map(id => board.byId.get(id)).filter(Boolean);

  return (
    <aside className="nx-ns-detail nx-scroll" aria-label={`Task ${task.title || task.id}`}>
      <header>
        <StatusDot tone={task.paul && task.status === "waiting" ? "gold" : TONE[task.status]} pulse={task.status === "running"} />
        <strong>{task.title || task.id}</strong>
        <IconButton icon={X} size="sm" label="Close task" onClick={onClose} />
      </header>
      <p className="nx-ns-detail-state">{stateText(task)}{noteText(task) ? ` · ${noteText(task)}` : ""}</p>

      <div className="nx-ns-actions">
        {canStart ? <Button size="sm" variant="primary" icon={Play} disabled={Boolean(busy)} onClick={() => act("start", { ids: [task.id] }, task.open?.length ? "Started. It launches when its prerequisites are done." : "")}>{task.status === "blocked" ? "Start again" : "Start"}</Button> : null}
        {canStop ? <Button size="sm" icon={Square} disabled={Boolean(busy)} onClick={() => act("stop", { id: task.id })}>Stop</Button> : null}
        {canTick ? <Button size="sm" icon={CheckSquare} onClick={() => setMode(mode === "tick" ? "" : "tick")} aria-expanded={mode === "tick"}>Mark done…</Button> : null}
        {canBlock ? <Button size="sm" onClick={() => setMode(mode === "block" ? "" : "block")} aria-expanded={mode === "block"}>Block…</Button> : null}
        {canEdit ? <Button size="sm" onClick={() => setMode(mode === "edit" ? "" : "edit")} aria-expanded={mode === "edit"}>Edit task…</Button> : null}
      </div>
      {error ? <p className="nx-ns-error" role="alert">{error}</p> : null}
      {mode === "tick" ? <TickForm task={task} onCancel={() => setMode("")} onDone={() => { setMode(""); onChanged(); }} /> : null}
      {mode === "block" ? <BlockForm task={task} onCancel={() => setMode("")} onDone={() => { setMode(""); onChanged(); }} /> : null}
      {mode === "edit" ? <EditTask key={task.id} task={task} board={board} onCancel={() => setMode("")} onDone={() => { setMode(""); onChanged(); }} /> : null}

      {task.evidence ? (
        <div className="nx-ns-detail-ev"><span>Evidence</span><EvidenceLink evidence={task.evidence} onOpenChat={onOpenChat} /></div>
      ) : null}
      <dl className="nx-ns-route">
        <div><dt>Who</dt><dd>{task.paul ? "You" : `${harnessLabel(task.harness)}${task.model ? ` · ${task.model}` : ""}${task.effort ? ` · ${task.effort}` : ""}`}</dd></div>
        {!task.paul ? <div><dt>Can</dt><dd>{PERMISSIONS.find(item => item.value === task.permissionMode)?.label || task.permissionMode}</dd></div> : null}
        <div><dt>Folder</dt><dd className="is-mono">{task.folder}</dd></div>
        {waitsFor.length ? <div><dt>After</dt><dd>{waitsFor.map(item => <span key={item.id} className={`nx-ns-chip is-${item.status}`}>{item.id}</span>)}</dd></div> : null}
        {unlocks.length ? <div><dt>Unlocks</dt><dd>{unlocks.map(item => <span key={item.id} className={`nx-ns-chip is-${item.status}`}>{item.id}</span>)}</dd></div> : null}
        {task.requiresGpu ? <div><dt>GPU</dt><dd>Needs the GPU</dd></div> : null}
        {task.limits?.maxTaskTokens || task.limits?.maxTaskSeconds ? <div><dt>Limit</dt><dd>{[task.limits.maxTaskTokens ? `${task.limits.maxTaskTokens.toLocaleString()} tokens` : "", task.limits.maxTaskSeconds ? `${Math.round(task.limits.maxTaskSeconds / 60)} min` : ""].filter(Boolean).join(" · ")}</dd></div> : null}
        {task.updatedAt ? <div><dt>Changed</dt><dd>{ago(task.updatedAt) === "now" ? "just now" : `${ago(task.updatedAt)} ago`}</dd></div> : null}
      </dl>
      <p className="nx-ns-prompt">{task.prompt}</p>
    </aside>
  );
}

function NewTask({ board, folders, onDone, onCancel }) {
  const [draft, setDraft] = useState({ id: "", title: "", prompt: "", harness: "codex", model: "", effort: "", permissionMode: "read-only", folder: folders[0]?.path || "", needs: [], requiresGpu: false, maxTaskTokens: "", maxTaskMinutes: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const patch = change => setDraft(current => ({ ...current, ...change }));
  const paul = draft.harness === "paul";
  const save = async () => {
    setBusy(true); setError("");
    const limits = {};
    if (Number(draft.maxTaskTokens) > 0) limits.maxTaskTokens = Math.round(Number(draft.maxTaskTokens));
    if (Number(draft.maxTaskMinutes) > 0) limits.maxTaskSeconds = Math.round(Number(draft.maxTaskMinutes) * 60);
    try {
      const task = await nightshift("create", {
        ...(draft.id.trim() ? { id: draft.id.trim() } : {}),
        ...(draft.title.trim() ? { title: draft.title.trim() } : {}),
        prompt: draft.prompt.trim(),
        owner: paul ? "Paul" : OWNER_FOR[draft.harness],
        ...(paul ? {} : { harness: draft.harness, permissionMode: draft.permissionMode, ...(draft.model.trim() ? { model: draft.model.trim() } : {}), ...(draft.effort ? { effort: draft.effort } : {}) }),
        ...(draft.folder.trim() ? { folder: draft.folder.trim() } : {}),
        needs: draft.needs,
        requiresGpu: draft.requiresGpu,
        ...(Object.keys(limits).length ? { limits } : {}),
      });
      onDone(task?.id);
    } catch (failure) { setError(failure.message); setBusy(false); }
  };
  return (
    <form className="nx-ns-form is-wide" aria-label="New task" onSubmit={event => { event.preventDefault(); if (draft.prompt.trim()) void save(); }}>
      <strong>New task</strong>
      <div className="nx-ns-row">
        <label className="nx-ns-field"><span>Short title</span><input className="nx-input" value={draft.title} onChange={event => patch({ title: event.target.value })} placeholder="Write the release notes" /></label>
        <label className="nx-ns-field is-id"><span>ID (optional)</span><input className="nx-input is-mono" value={draft.id} onChange={event => patch({ id: event.target.value })} placeholder="B2" /></label>
      </div>
      <label className="nx-ns-field"><span>{paul ? "What you need to do" : "Prompt the agent gets, in full"}</span>
        <textarea className="nx-input nx-ns-area" rows={4} value={draft.prompt} onChange={event => patch({ prompt: event.target.value })} />
      </label>
      <div className="nx-ns-row">
        <label className="nx-ns-field"><span>Who does it</span>
          <select className="nx-input" value={draft.harness} onChange={event => patch({ harness: event.target.value })}>
            {HARNESSES.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
            <option value="paul">Me (Paul)</option>
          </select>
        </label>
        {paul ? null : (
          <>
            <label className="nx-ns-field"><span>Model</span>
              <input className="nx-input" list="nx-ns-models" value={draft.model} onChange={event => patch({ model: event.target.value })} placeholder="Default" />
              <datalist id="nx-ns-models">{MODEL_HINTS.map(model => <option key={model} value={model} />)}</datalist>
            </label>
            <label className="nx-ns-field"><span>The agent can</span>
              <select className="nx-input" value={draft.permissionMode} onChange={event => patch({ permissionMode: event.target.value })}>
                {PERMISSIONS.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </label>
          </>
        )}
      </div>
      <label className="nx-ns-field"><span>Folder</span>
        <input className="nx-input is-mono" list="nx-ns-folders" value={draft.folder} onChange={event => patch({ folder: event.target.value })} placeholder="Neyvia's own folder" />
        <datalist id="nx-ns-folders">{folders.map(folder => <option key={folder.path} value={folder.path}>{folder.name}</option>)}</datalist>
      </label>
      {board.tasks.length ? (
        <div className="nx-ns-needs" role="group" aria-label="Starts after">
          <span>Starts after</span>
          {board.tasks.map(other => (
            <label key={other.id}><input type="checkbox" checked={draft.needs.includes(other.id)}
              onChange={event => patch({ needs: event.target.checked ? [...draft.needs, other.id] : draft.needs.filter(need => need !== other.id) })} />{other.id}</label>
          ))}
        </div>
      ) : null}
      {paul ? null : (
        <div className="nx-ns-row">
          <label className="nx-ns-field"><span>Token limit</span><input className="nx-input" inputMode="numeric" value={draft.maxTaskTokens} onChange={event => patch({ maxTaskTokens: event.target.value })} placeholder="No limit" /></label>
          <label className="nx-ns-field"><span>Minutes limit</span><input className="nx-input" inputMode="numeric" value={draft.maxTaskMinutes} onChange={event => patch({ maxTaskMinutes: event.target.value })} placeholder="No limit" /></label>
          <label className="nx-ns-check is-inline"><input type="checkbox" checked={draft.requiresGpu} onChange={event => patch({ requiresGpu: event.target.checked })} /><span>Needs the GPU</span></label>
        </div>
      )}
      {error ? <p className="nx-ns-error" role="alert">{error}</p> : null}
      <footer className="nx-ns-foot">
        <Button size="sm" onClick={onCancel}>Cancel</Button>
        <Button size="sm" variant="primary" type="submit" disabled={busy || !draft.prompt.trim()}>{busy ? "Saving…" : "Add task"}</Button>
        <span>It waits until you start it.</span>
      </footer>
    </form>
  );
}

function ImportTasks({ folders, onDone, onCancel }) {
  const [source, setSource] = useState("path");
  const [path, setPath] = useState("");
  const [text, setText] = useState("");
  const [folder, setFolder] = useState(folders[0]?.path || "");
  const [model, setModel] = useState("");
  const [permissionMode, setPermissionMode] = useState("read-only");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const ready = source === "path" ? path.trim() : text.trim();
  const submit = async () => {
    setBusy(true); setError(""); setResult(null);
    try {
      const answer = await nightshift("import", {
        ...(source === "path" ? { path: path.trim() } : { text }),
        ...(folder.trim() ? { folder: folder.trim() } : {}),
        defaults: { permissionMode, ...(model.trim() ? { model: model.trim() } : {}) },
      });
      setResult(answer);
      onDone();
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  };
  return (
    <form className="nx-ns-form is-wide" aria-label="Import a task board" onSubmit={event => { event.preventDefault(); if (ready) void submit(); }}>
      <strong>Import TASKS.md</strong>
      <p className="nx-ns-fine">Rows like <code>- [ ] B1 · Codex · needs: A1 · prompt</code>. Everything comes in stopped; ticked rows still need fresh evidence.</p>
      <Segmented size="sm" label="Source" value={source} onChange={setSource} options={[{ value: "path", label: "A file on this PC" }, { value: "text", label: "Paste it" }]} />
      {source === "path" ? (
        <label className="nx-ns-field"><span>Path to the .md file</span>
          <input className="nx-input is-mono" value={path} onChange={event => setPath(event.target.value)} placeholder="C:\Users\user\Projects\plans\TASKS.md" />
        </label>
      ) : (
        <label className="nx-ns-field"><span>Board text</span>
          <textarea className="nx-input is-mono nx-ns-area" rows={7} value={text} onChange={event => setText(event.target.value)} placeholder={"## TASKS\n- [ ] A1 · Codex · needs: none · Write the parser\n- [ ] B1 · Codex · needs: A1 · Test the parser"} />
        </label>
      )}
      <div className="nx-ns-row">
        <label className="nx-ns-field"><span>Folder for rows that don't name one</span>
          <input className="nx-input is-mono" list="nx-ns-folders-import" value={folder} onChange={event => setFolder(event.target.value)} placeholder="Neyvia's own folder" />
          <datalist id="nx-ns-folders-import">{folders.map(item => <option key={item.path} value={item.path}>{item.name}</option>)}</datalist>
        </label>
        <label className="nx-ns-field"><span>Model for every row</span>
          <input className="nx-input" list="nx-ns-models-import" value={model} onChange={event => setModel(event.target.value)} placeholder="Default" />
          <datalist id="nx-ns-models-import">{MODEL_HINTS.map(item => <option key={item} value={item} />)}</datalist>
        </label>
        <label className="nx-ns-field"><span>The agents can</span>
          <select className="nx-input" value={permissionMode} onChange={event => setPermissionMode(event.target.value)}>
            {PERMISSIONS.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </label>
      </div>
      {result ? (
        <p className="nx-ns-ok" role="status">
          {result.imported?.length ? `Added ${result.imported.join(", ")}.` : "Nothing new."}
          {result.existing?.length ? ` Already on the board: ${result.existing.join(", ")}.` : ""}
        </p>
      ) : null}
      {error ? <p className="nx-ns-error" role="alert">{error}</p> : null}
      <footer className="nx-ns-foot">
        <Button size="sm" onClick={onCancel}>{result ? "Close" : "Cancel"}</Button>
        <Button size="sm" variant="primary" type="submit" icon={Download} disabled={busy || !ready}>{busy ? "Importing…" : "Import"}</Button>
      </footer>
    </form>
  );
}

/** The Night Shift board. `folders`: known project folders for the pickers. */
export function NxNightShift({ folders = [], onOpenChat }) {
  const { status, summary, policy, error, refresh } = useNightShift(true);
  const [selected, setSelected] = useState(null);
  const [panel, setPanel] = useState(""); // "" | new | import | budget
  const [busy, setBusy] = useState("");
  const [showMissions, setShowMissions] = useState(false);
  const phone = useMedia("(max-width: 760px)");
  const board = useMemo(() => shapeBoard(summary?.tasks || [], { includeMissions: showMissions }), [summary, showMissions]);
  const card = useMemo(() => morning(summary), [summary]);
  const task = selected ? board.byId.get(selected) : null;
  const ready = startable(board.tasks);

  const run = async (key, action, payload, message) => {
    setBusy(key);
    try { const result = await nightshift(action, payload); if (message) os.notify({ level: "success", message: message(result) }); await refresh(); }
    catch (failure) { os.notify({ level: "warning", message: failure.message }); }
    finally { setBusy(""); }
  };
  const startReady = () => run("start", "start", { ids: ready.map(item => item.id) }, () => `Started ${ready.length} task${ready.length === 1 ? "" : "s"}. Each launches when its prerequisites are done.`);
  const togglePause = () => run("pause", "resources", { paused: !policy?.paused }, () => (policy?.paused ? "Night Shift resumed" : "Night Shift paused. Running tasks finish."));
  const newNight = () => run("night", "begin", {}, () => "New night started. Its budget counts from now.");

  if (status === "loading") return <section className="nx-ns is-center" aria-label="Night Shift"><Spinner size={16} /></section>;
  if (status === "offline" || (status === "error" && !summary)) {
    return (
      <section className="nx-ns is-center" aria-label="Night Shift">
        <div className="nx-pane-honest"><NxGrowingTree size={40} growing={false} /><strong>Night Shift isn't reachable</strong>
          <p>{status === "offline" ? "It needs the Neyvia service on your PC, signed in as its owner." : error}</p>
          <Button size="sm" onClick={refresh}>Try again</Button></div>
      </section>
    );
  }

  const side = panel === "new" ? <NewTask board={board} folders={folders} onCancel={() => setPanel("")} onDone={id => { setPanel(""); if (id) setSelected(id); void refresh(); }} />
    : panel === "import" ? <ImportTasks folders={folders} onCancel={() => setPanel("")} onDone={refresh} />
      : panel === "budget" ? <BudgetPanel policy={policy} summary={summary} onClose={() => setPanel("")} onSaved={refresh} />
        : task ? <TaskDetail task={task} board={board} onChanged={refresh} onOpenChat={onOpenChat} onClose={() => setSelected(null)} /> : null;

  return (
    <section className="nx-ns" aria-label="Night Shift">
      <div className="nx-ns-tools">
        <Button size="sm" icon={Plus} onClick={() => setPanel(panel === "new" ? "" : "new")} aria-pressed={panel === "new"}>Add task</Button>
        <Button size="sm" icon={Download} onClick={() => setPanel(panel === "import" ? "" : "import")} aria-pressed={panel === "import"}>Import</Button>
        <Button size="sm" icon={SlidersHorizontal} onClick={() => setPanel(panel === "budget" ? "" : "budget")} aria-pressed={panel === "budget"}>Budget</Button>
        <Button size="sm" onClick={() => applyUiAction("pane.show", { kind: "agents", target: "", placement: "full" })}>See every agent working now</Button>
        <span className="nx-ns-tools-gap" />
        {policy ? <Button size="sm" icon={policy.paused ? Play : Pause} disabled={Boolean(busy)} onClick={togglePause}>{policy.paused ? "Resume" : "Pause"}</Button> : null}
        {ready.length ? <button type="button" className="nx-ns-start" disabled={Boolean(busy)} onClick={startReady}><Icon as={Play} size={14} />Start {ready.length} {ready.length === 1 ? "task" : "tasks"}</button> : null}
      </div>
      {policy?.paused ? <p className="nx-ns-banner" role="status"><Icon as={Pause} size={13} />Paused. Nothing new starts until you resume.</p> : null}

      <div className="nx-ns-body">
        <div className="nx-ns-main nx-scroll">
          <MorningCard data={card} board={board} onOpenChat={onOpenChat} selectedId={selected} onNewNight={newNight} busy={Boolean(busy)} />
          {board.tasks.length ? (
            <Graph board={board} selectedId={selected} onSelect={id => { setPanel(""); setSelected(id === selected ? null : id); }} />
          ) : (
            <div className="nx-pane-honest nx-ns-empty">
              <Icon as={FolderOpen} size={22} />
              <strong>No tasks yet</strong>
              <p>Add a task or import a TASKS.md. Tasks wait for their prerequisites, and nothing runs until you start it.</p>
              <Button size="sm" variant="primary" icon={Plus} onClick={() => setPanel("new")}>Add task</Button>
            </div>
          )}
          {board.missionCount ? (
            <label className="nx-ns-check is-inline nx-ns-missions"><input type="checkbox" checked={showMissions} onChange={event => setShowMissions(event.target.checked)} />
              <span>Show {board.missionCount} mission task{board.missionCount === 1 ? "" : "s"} too</span></label>
          ) : null}
        </div>
        {side ? <div className={`nx-ns-side${phone ? " is-phone" : ""}`}>{side}</div> : null}
      </div>
    </section>
  );
}
