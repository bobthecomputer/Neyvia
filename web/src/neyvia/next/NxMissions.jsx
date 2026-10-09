import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Flag, FolderOpen, GitBranch, Pause, Play, Plus, ShieldCheck, Sparkles, Square, Trash2, X } from "lucide-react";

import "./nxMissions.css";
import { ProviderMark } from "./ProviderMark.jsx";
import { NxGrowingTree } from "./NxGrowingTree.jsx";
import { Button, Icon, IconButton, Segmented, Spinner, StatusDot, ago } from "./nxPrimitives.jsx";
import { NxNightShift } from "./NxNightShift.jsx";
import { approveUiRequest, listMissions, missionRequest } from "./nxBus.js";
import { os, useOs } from "./nxOsStore.js";
import { startSession } from "./nxStore.js";
import { HARNESSES, createRequest, draftProblems, emptyDraft, emptyTask, harnessLabel, markForHarness, planPrompt, shapeMission } from "./nxMissionsModel.js";

// Missions: real orchestration on the Night Shift engine. A goal is split
// into tasks routed to Codex, Claude Code, Neyvia or OpenCode, with
// prerequisites; nothing runs until the owner approves the exact prompts,
// routes and budget. Opens as the "mission" stage pane.

const PHASE_LABEL = { draft: "Draft", waiting: "Waiting", running: "Running", blocked: "Blocked", finished: "Evidence ready", paused: "Paused", stopped: "Stopped" };
const TONE = { waiting: "idle", running: "live", blocked: "red", needs_review: "gold", done: "green" };

/** Missions, refreshed while shown and whenever Night Shift reports a task change. */
export function useMissions() {
  const nightshift = useOs(state => state.nightshift);
  const [state, setState] = useState({ status: "loading", missions: [] });
  const refresh = useCallback(async () => {
    const data = await listMissions();
    setState(data ? { status: "ready", missions: (data.missions || []).map(shapeMission) } : { status: "offline", missions: [] });
  }, []);
  useEffect(() => { void refresh(); }, [refresh, nightshift]);
  useEffect(() => {
    const timer = setInterval(() => void refresh(), 6000);
    return () => clearInterval(timer);
  }, [refresh]);
  return { ...state, refresh };
}

function Phase({ phase }) {
  return <span className={`nx-ms-phase is-${phase}`}>{phase === "running" ? <Spinner size={10} /> : null}{PHASE_LABEL[phase] || phase}</span>;
}

function TaskNode({ task, selected, onSelect, byId }) {
  const after = task.needs.map(need => byId.get(need)?.localId).filter(Boolean);
  return (
    <button type="button" className={`nx-ms-task is-${task.status}${selected ? " is-selected" : ""}`} onClick={() => onSelect(task.id)}>
      <span className="nx-ms-task-top">
        <ProviderMark id={markForHarness(task.harness)} size={14} />
        <span className="nx-ms-task-route">{harnessLabel(task.harness)}{task.model ? ` · ${task.model}` : ""}</span>
        {task.status === "running" ? <NxGrowingTree size={16} /> : <StatusDot tone={TONE[task.status]} />}
      </span>
      <span className="nx-ms-task-title">{task.title || task.localId}</span>
      {after.length ? <span className="nx-ms-task-after">after {after.join(", ")}</span> : null}
    </button>
  );
}

function TaskDetail({ mission, task, onDone }) {
  const [prompt, setPrompt] = useState(task.prompt || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { setPrompt(task.prompt || ""); setError(""); }, [task.id, task.prompt]);
  const editable = task.status === "waiting" || task.status === "blocked";
  const redirect = async () => {
    setBusy(true); setError("");
    try { await missionRequest("control", { id: mission.id, action: "redirect", taskId: task.id, prompt }); onDone(); }
    catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  };
  return (
    <aside className="nx-ms-detail" aria-label={`Task ${task.title || task.localId}`}>
      <header><strong>{task.title || task.localId}</strong><StatusDot tone={TONE[task.status]} /><span>{task.status === "needs_review" ? "Needs review" : task.status}</span></header>
      <dl className="nx-ms-route">
        <div><dt>Harness</dt><dd>{harnessLabel(task.harness)}</dd></div>
        {task.model ? <div><dt>Model</dt><dd>{task.model}</dd></div> : null}
        <div><dt>Permission</dt><dd>{task.permissionMode || "read-only"}</dd></div>
        {task.reason ? <div><dt>Why</dt><dd>{task.reason}</dd></div> : null}
        {task.evidence ? <div><dt>Evidence</dt><dd>{typeof task.evidence === "string" ? task.evidence : JSON.stringify(task.evidence)}</dd></div> : null}
      </dl>
      {editable ? (
        <>
          <textarea className="nx-ms-input" rows={6} value={prompt} onChange={event => setPrompt(event.target.value)} aria-label="Task prompt" />
          <Button size="sm" variant="primary" disabled={busy || !prompt.trim() || prompt === task.prompt} onClick={redirect}>Save new prompt</Button>
        </>
      ) : <p className="nx-ms-prompt">{task.prompt}</p>}
      {error ? <p className="nx-ms-error" role="alert">{error}</p> : null}
    </aside>
  );
}

/** One mission: goal, phase, task tree and acceptance. Exported for the tour, which shows it with example data. */
export function MissionView({ mission, onChanged }) {
  const [busy, setBusy] = useState("");
  const [approval, setApproval] = useState(null);
  const [error, setError] = useState("");
  const [taskId, setTaskId] = useState(null);
  const byId = useMemo(() => new Map(mission.tasks.map(task => [task.id, task])), [mission.tasks]);
  const task = taskId ? byId.get(taskId) : null;
  useEffect(() => { setApproval(null); setError(""); setTaskId(null); }, [mission.id]);

  const act = async action => {
    setBusy(action); setError("");
    try {
      const result = await missionRequest("control", { id: mission.id, action });
      if (result?.status === "approval_required") setApproval(result.approvalId);
      else { setApproval(null); onChanged(); }
    } catch (failure) { setError(failure.message); }
    finally { setBusy(""); }
  };
  const approveAndStart = async () => {
    setBusy("start"); setError("");
    try { await approveUiRequest(approval); setApproval(null); await act("start"); }
    catch (failure) { setError(failure.message); setBusy(""); }
  };
  const canStart = ["draft", "paused", "stopped", "waiting", "blocked"].includes(mission.phase) && mission.status !== "running";

  return (
    <div className="nx-ms-view">
      <header className="nx-ms-head">
        <div className="nx-ms-head-main">
          <h2>{mission.goal}</h2>
          <span className="nx-ms-meta"><Icon as={FolderOpen} size={12} />{mission.folder}{mission.updatedAt ? ` · updated ${ago(mission.updatedAt)}` : ""}</span>
        </div>
        <Phase phase={mission.phase} />
        {canStart ? <Button size="sm" variant="primary" icon={Play} disabled={Boolean(busy)} onClick={() => act("start")}>{mission.phase === "draft" ? "Start" : "Resume"}</Button> : null}
        {mission.status === "running" ? <Button size="sm" icon={Pause} disabled={Boolean(busy)} onClick={() => act("pause")}>Pause</Button> : null}
        {mission.status === "running" || mission.status === "paused" ? <Button size="sm" icon={Square} disabled={Boolean(busy)} onClick={() => act("stop")}>Stop</Button> : null}
      </header>

      {approval ? (
        <div className="nx-ms-approval" role="alert">
          <Icon as={ShieldCheck} size={16} />
          <p>Starting runs these {mission.tasks.length} prompts with their routes, permissions and budget. Approve once to start.</p>
          <Button size="sm" variant="primary" disabled={busy === "start"} onClick={approveAndStart}>Approve and start</Button>
          <IconButton icon={X} size="sm" label="Not now" onClick={() => setApproval(null)} />
        </div>
      ) : null}
      {error ? <p className="nx-ms-error" role="alert">{error}</p> : null}

      <div className="nx-ms-progress" aria-label={`${mission.counts.done} of ${mission.tasks.length} tasks done`}>
        <span style={{ transform: `scaleX(${mission.progress})` }} />
      </div>
      <p className="nx-ms-counts">
        {mission.counts.done}/{mission.tasks.length} done · {mission.counts.running} running · {mission.counts.blocked} blocked · {mission.counts.needs_review} need review
        {mission.usage ? ` · ${mission.usage.reportedTokens?.toLocaleString() || 0} reported tokens${mission.usage.complete ? "" : " (some runs not reported yet)"}` : ""}
      </p>

      <div className="nx-ms-body">
        <div className="nx-ms-tree nx-scroll" aria-label="Tasks, in the order they can run">
          {mission.levels.map((level, index) => (
            <div key={index} className="nx-ms-level">
              <span className="nx-ms-level-label">{index === 0 ? "First" : `Then (${index})`}</span>
              {level.map(item => <TaskNode key={item.id} task={item} byId={byId} selected={item.id === taskId} onSelect={setTaskId} />)}
            </div>
          ))}
        </div>
        {task ? <TaskDetail mission={mission} task={task} onDone={onChanged} /> : (
          <aside className="nx-ms-detail">
            <header><strong>Acceptance</strong><span>{mission.acceptance === "evidence_ready_for_review" ? "Evidence ready for your review" : "Pending"}</span></header>
            <ul className="nx-ms-checks">
              {(mission.acceptanceChecks || []).map(check => <li key={check}><Icon as={mission.acceptance === "evidence_ready_for_review" ? Check : Flag} size={13} />{check}</li>)}
            </ul>
            <p className="nx-ms-hint">Pick a task to see its prompt, route and evidence.</p>
          </aside>
        )}
      </div>
    </div>
  );
}

function NewMission({ folders, folder, onCreated, onCancel, onOpenChat }) {
  const [draft, setDraft] = useState(() => emptyDraft(folder || folders[0]?.path || ""));
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const problems = draftProblems(draft);
  const patch = change => setDraft(current => ({ ...current, ...change }));
  const patchTask = (id, change) => setDraft(current => ({ ...current, tasks: current.tasks.map(task => (task.id === id ? { ...task, ...change } : task)) }));
  const addTask = () => setDraft(current => {
    let index = current.tasks.length + 1;
    while (current.tasks.some(task => task.id === `t${index}`)) index += 1;
    return { ...current, tasks: [...current.tasks, emptyTask(index)] };
  });
  const save = async () => {
    setBusy("save"); setError("");
    try { const result = await missionRequest("create", createRequest(draft)); onCreated(result?.mission?.id); }
    catch (failure) { setError(failure.message); setBusy(""); }
  };
  const plan = async () => {
    setBusy("plan"); setError("");
    try {
      const run = await startSession("neyvia", draft.folder.trim(), planPrompt(draft.goal, draft.folder));
      if (run?.sessionId) onOpenChat(run.sessionId);
      os.notify({ level: "info", message: "Neyvia is planning the mission. It shows up here when stored." });
      onCancel();
    } catch (failure) { setError(failure.message); setBusy(""); }
  };

  return (
    <form className="nx-ms-new nx-scroll" onSubmit={event => { event.preventDefault(); if (!problems.length) void save(); }}>
      <h2>New mission</h2>
      <label className="nx-ms-field"><span>Goal</span>
        <input className="nx-ms-input" value={draft.goal} onChange={event => patch({ goal: event.target.value })} placeholder="What should be true when it's done?" />
      </label>
      <label className="nx-ms-field"><span>Project folder</span>
        <input className="nx-ms-input is-mono" list="nx-ms-folders" value={draft.folder} onChange={event => patch({ folder: event.target.value })} placeholder="C:\Users\you\Projects\app" />
        <datalist id="nx-ms-folders">{folders.map(folder => <option key={folder.path} value={folder.path}>{folder.name}</option>)}</datalist>
      </label>
      <div className="nx-ms-plan">
        <Icon as={Sparkles} size={15} />
        <p>Let Neyvia read the project and split the work into routed tasks. You review and start it here.</p>
        <Button size="sm" disabled={!draft.goal.trim() || !draft.folder.trim() || Boolean(busy)} onClick={plan}>{busy === "plan" ? "Asking…" : "Plan with Neyvia"}</Button>
      </div>

      <h3>Tasks</h3>
      {draft.tasks.map((task, index) => (
        <fieldset key={task.id} className="nx-ms-draft-task">
          <legend>Task {index + 1} <code>{task.id}</code></legend>
          <div className="nx-ms-row">
            <input className="nx-ms-input" value={task.title} onChange={event => patchTask(task.id, { title: event.target.value })} placeholder="Short title" aria-label={`Task ${index + 1} title`} />
            <select className="nx-ms-input" value={task.harness} onChange={event => patchTask(task.id, { harness: event.target.value })} aria-label={`Task ${index + 1} harness`}>
              {HARNESSES.map(harness => <option key={harness.id} value={harness.id}>{harness.label}</option>)}
            </select>
            <input className="nx-ms-input" value={task.model} onChange={event => patchTask(task.id, { model: event.target.value })} placeholder="Model (optional)" aria-label={`Task ${index + 1} model`} />
            {draft.tasks.length > 1 ? <IconButton icon={Trash2} size="sm" label={`Remove task ${index + 1}`} onClick={() => patch({ tasks: draft.tasks.filter(item => item.id !== task.id) })} /> : null}
          </div>
          <textarea className="nx-ms-input" rows={3} value={task.prompt} onChange={event => patchTask(task.id, { prompt: event.target.value })} placeholder="What this agent should do, in full" aria-label={`Task ${index + 1} prompt`} />
          {index > 0 ? (
            <div className="nx-ms-needs" role="group" aria-label={`Task ${index + 1} starts after`}>
              <span>Starts after</span>
              {draft.tasks.slice(0, index).map(other => (
                <label key={other.id}><input type="checkbox" checked={task.needs.includes(other.id)}
                  onChange={event => patchTask(task.id, { needs: event.target.checked ? [...task.needs, other.id] : task.needs.filter(need => need !== other.id) })} />{other.title || other.id}</label>
              ))}
            </div>
          ) : null}
        </fieldset>
      ))}
      <Button size="sm" icon={Plus} onClick={addTask}>Add a task</Button>

      <label className="nx-ms-field"><span>Acceptance checks, one per line</span>
        <textarea className="nx-ms-input" rows={3} value={draft.acceptance} onChange={event => patch({ acceptance: event.target.value })} placeholder={"Tests pass\nThe new screen works on a phone"} />
      </label>
      <label className="nx-ms-field is-narrow"><span>Token budget (optional)</span>
        <input className="nx-ms-input" inputMode="numeric" value={draft.maxTokens} onChange={event => patch({ maxTokens: event.target.value })} placeholder="e.g. 2000000" />
      </label>

      {problems.length && (draft.goal || draft.tasks.some(task => task.prompt)) ? <ul className="nx-ms-problems">{problems.map(problem => <li key={problem}>{problem}</li>)}</ul> : null}
      {error ? <p className="nx-ms-error" role="alert">{error}</p> : null}
      <footer className="nx-ms-new-foot">
        <Button size="sm" onClick={onCancel}>Cancel</Button>
        <Button size="sm" variant="primary" type="submit" disabled={Boolean(problems.length) || Boolean(busy)}>{busy === "save" ? "Saving…" : "Save mission"}</Button>
        <span>It stays dormant until you start it.</span>
      </footer>
    </form>
  );
}

/**
 * The Canopy's work view: Missions (one goal, many agents) and Night Shift
 * (07 R6: a task board whose ticks launch the next tasks). target "nightshift"
 * opens the board; anything else is a mission id or "new[:folder]".
 */
export function NxMissions({ target, folders, onOpenChat }) {
  const [tab, setTab] = useState(target === "nightshift" ? "nightshift" : "missions");
  useEffect(() => { if (target === "nightshift") setTab("nightshift"); else if (target) setTab("missions"); }, [target]);
  const tasks = useOs(state => state.nightshift);
  const live = Object.values(tasks).filter(task => !task.missionId && task.status === "running").length;
  return (
    <div className="nx-ms-shell">
      <div className="nx-ms-tabs">
        <Segmented size="sm" label="Work view" value={tab} onChange={setTab}
          options={[{ value: "missions", label: "Missions" }, { value: "nightshift", label: "Night Shift", count: live }]} />
        <Button size="sm" className="nx-ms-parallel" icon={GitBranch} onClick={() => os.showPane("parallel", "")} title="Several agents on their own worktrees, merged back into one branch">Parallel branches</Button>
      </div>
      {tab === "nightshift" ? <NxNightShift folders={folders} onOpenChat={onOpenChat} />
        : <MissionsBoard target={target === "nightshift" ? "" : target} folders={folders} onOpenChat={onOpenChat} />}
    </div>
  );
}

function MissionsBoard({ target, folders, onOpenChat }) {
  const { status, missions, refresh } = useMissions();
  // target: a mission id, "new", or "new:<folder>" (from a Builder project card).
  const fresh = String(target || "").startsWith("new");
  const [selected, setSelected] = useState(fresh ? null : target || null);
  const [creating, setCreating] = useState(fresh);
  const presetFolder = fresh ? String(target).slice(4) : "";
  const mission = missions.find(item => item.id === selected) || (!creating ? missions[0] : null);

  return (
    <section className="nx-ms" aria-label="Missions">
      <nav className="nx-ms-list nx-scroll" aria-label="Missions">
        <Button size="sm" variant="primary" icon={Plus} onClick={() => setCreating(true)}>New mission</Button>
        {status === "loading" ? <div className="nx-ms-empty"><Spinner size={14} /></div> : null}
        {status === "offline" ? <p className="nx-ms-empty">Missions need the Neyvia backend on your PC, signed in as its owner.</p> : null}
        {status === "ready" && !missions.length ? <p className="nx-ms-empty">No missions yet. A mission splits one goal into tasks for several agents, and runs only after you approve it.</p> : null}
        {missions.map(item => (
          <button key={item.id} type="button" className={`nx-ms-card${item.id === mission?.id && !creating ? " is-on" : ""}`} onClick={() => { setSelected(item.id); setCreating(false); }}>
            <span className="nx-ms-card-goal">{item.goal}</span>
            <span className="nx-ms-card-meta"><Phase phase={item.phase} /><span>{item.counts.done}/{item.tasks.length}</span></span>
            <span className="nx-ms-card-bar"><span style={{ transform: `scaleX(${item.progress})` }} /></span>
          </button>
        ))}
      </nav>
      <div className="nx-ms-main">
        {creating ? (
          <NewMission folders={folders} folder={presetFolder} onOpenChat={onOpenChat} onCancel={() => setCreating(false)}
            onCreated={id => { setCreating(false); if (id) setSelected(id); void refresh(); }} />
        ) : mission ? <MissionView mission={mission} onChanged={refresh} /> : (
          <div className="nx-ms-empty is-big"><NxGrowingTree size={56} growing={false} /><p>Missions grow here: one goal, many agents, every step with evidence.</p></div>
        )}
      </div>
    </section>
  );
}
