import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, Check, CircleAlert, Flag, FolderOpen, Pause, Play, Plus, RefreshCw, Route, ShieldCheck, Square, X } from "lucide-react";

import "./nxConductor.css";
import { ProviderMark } from "./ProviderMark.jsx";
import { NxGrowingTree } from "./NxGrowingTree.jsx";
import { appLabel } from "./NxSidebarParts.jsx";
import { Button, Icon, IconButton, Spinner, StatusDot, ago, compactTokens, useTick } from "./nxPrimitives.jsx";
import { conductorControl, conductorGet, conductorList, conductorPlan, runtimeMatrix, saveProfile } from "./nxAgentsApi.js";
import { PROFILES, checkLines, durationText, mergeJobs, phaseOf, planProblems, routeLine, shapeJob, taskTone } from "./nxConductorModel.js";
import { os } from "./nxOsStore.js";

// The Conductor (plan 15 T9, pane.show {kind:"mission", target:"conductor"}):
// one goal becomes a routed task tree. Planner, executor, verifier (and an
// optional classifier) are routes Paul picks once; the plan is frozen before
// he starts it; each task leaves a receipt; a final verifier proves the checks.
// The job is a detached worker on the PC, so it keeps going and reattaches when
// Neyvia restarts. The bot side is neyvia.conductor.* on the same jobs.

const PAGE = 20;
const LIVE_MS = 1500;
const LIST_MS = 5000;
const markOf = app => (app === "claude-code" ? "claude" : app || "neyvia");
const ROUTE_APPS = ["codex", "claude-code", "opencode", "neyvia"];

function newRequestId() {
  return `ui-conductor-${globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`}`;
}

/** Every page of jobs read so far, refreshed while the screen is open. */
function useJobs() {
  const [state, setState] = useState({ status: "loading", jobs: [], total: 0, nextOffset: null, fault: "" });
  const pages = useRef(1);
  const load = useCallback(async () => {
    try {
      let jobs = [];
      let last = null;
      for (let page = 0; page < pages.current; page += 1) {
        last = await conductorList({ limit: PAGE, offset: page * PAGE });
        jobs = mergeJobs(jobs, last.jobs || []);
        if (last.nextOffset == null) break;
      }
      setState({ status: "ready", jobs, total: last?.total ?? jobs.length, nextOffset: last?.nextOffset ?? null, fault: "" });
    } catch (error) {
      setState(current => ({ ...current, status: current.jobs.length ? "ready" : "offline", fault: error.message }));
    }
  }, []);
  useEffect(() => {
    void load();
    const timer = setInterval(() => { if (!document.hidden) void load(); }, LIST_MS);
    return () => clearInterval(timer);
  }, [load]);
  const more = () => { pages.current += 1; void load(); };
  return { ...state, refresh: load, more };
}

/** One job, read every 1.5 s while its worker is alive (the saved file is the truth). */
function useJob(id, seed) {
  const [job, setJob] = useState(seed || null);
  const [error, setError] = useState("");
  useEffect(() => { setJob(seed || null); setError(""); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  // A newer copy from the list (it polls too) replaces an older read, never the other way round.
  useEffect(() => { if (seed && seed.id === id && String(seed.updatedAt || "") > String(job?.updatedAt || "")) setJob(seed); }, [seed]); // eslint-disable-line react-hooks/exhaustive-deps
  const read = useCallback(async () => {
    if (!id) return;
    try { setJob(await conductorGet(id)); setError(""); }
    catch (failure) { setError(failure.message); }
  }, [id]);
  const live = job ? ["queued", "running"].includes(job.status) : true;
  useEffect(() => {
    if (!id) return undefined;
    void read();
    if (!live) return undefined;
    const timer = setInterval(() => { if (!document.hidden) void read(); }, LIVE_MS);
    return () => clearInterval(timer);
  }, [id, live, read]);
  return { job, readFault: error, read, setJob };
}

function Phase({ phase }) {
  const { label, tone } = phaseOf(phase);
  return <span className={`nx-cd-phase is-${tone}`}>{tone === "live" ? <Spinner size={10} /> : <StatusDot tone={tone} />}{label}</span>;
}

// ---- routes -------------------------------------------------------------------

/** The four routing profiles, chosen from what each runtime on this PC reports. */
function Routes({ matrix, onSaved, compact = false }) {
  const runtimes = useMemo(() => (matrix?.runtimes || []).filter(row => ROUTE_APPS.includes(row.id) && row.connected && row.options?.models?.length), [matrix]);
  const profiles = matrix?.profiles || {};
  return (
    <section className={`nx-cd-routes${compact ? " is-compact" : ""}`} aria-label="Who does what">
      <header>
        <h3>Who does what</h3>
        <p>Saved on this PC for every goal. A plan keeps the routes it started with.</p>
      </header>
      {!matrix ? <p className="nx-cd-muted"><Spinner size={11} /> Reading the runtimes on this PC…</p> : null}
      {matrix && !runtimes.length ? <p className="nx-cd-muted">No runtime on this PC reports its models yet. Open Runtimes to check.</p> : null}
      {matrix && runtimes.length ? PROFILES.map(profile => (
        <RouteRow key={profile.name} profile={profile} saved={profiles[profile.name] || null} runtimes={runtimes} onSaved={onSaved} />
      )) : null}
    </section>
  );
}

function RouteRow({ profile, saved, runtimes, onSaved }) {
  const [draft, setDraft] = useState(saved);
  const [state, setState] = useState({ busy: false, fault: "" });
  useEffect(() => { setDraft(saved); }, [saved]);
  const runtime = runtimes.find(row => row.id === draft?.app) || null;
  const models = runtime?.options?.models || [];
  const model = models.find(row => row.id === draft?.model) || null;
  const modes = runtime?.options?.permissionModes || [];
  const changed = JSON.stringify(draft || null) !== JSON.stringify(saved || null);
  const complete = !draft || (draft.app && draft.model && draft.permissionMode);
  const patch = change => setDraft(current => {
    const next = { ...(current || {}), ...change };
    if (change.app) { next.model = ""; next.effort = ""; next.permissionMode = ""; }
    if (change.model !== undefined) next.effort = "";
    return next;
  });
  const save = async () => {
    setState({ busy: true, fault: "" });
    try {
      const route = draft ? Object.fromEntries(Object.entries(draft).filter(([, value]) => value)) : null;
      const result = await saveProfile(profile.name, route);
      onSaved(result.profiles);
      setState({ busy: false, fault: "" });
    } catch (error) { setState({ busy: false, fault: error.message }); }
  };
  return (
    <div className="nx-cd-route">
      <div className="nx-cd-route-name">
        <strong>{profile.label}</strong>
        <span>{profile.help}</span>
      </div>
      <div className="nx-cd-route-pick">
        <select className="nx-cd-input" aria-label={`${profile.label} app`} value={draft?.app || ""} onChange={event => (event.target.value ? patch({ app: event.target.value }) : setDraft(null))}>
          <option value="">{profile.required ? "Choose an app" : "Not used"}</option>
          {runtimes.map(row => <option key={row.id} value={row.id}>{appLabel(row.id)}</option>)}
        </select>
        {draft?.app ? (
          <>
            <select className="nx-cd-input" aria-label={`${profile.label} model`} value={draft.model || ""} onChange={event => patch({ model: event.target.value })}>
              <option value="">Model</option>
              {models.map(row => <option key={row.id} value={row.id}>{row.label || row.id}</option>)}
            </select>
            {model?.efforts?.length ? (
              <select className="nx-cd-input is-short" aria-label={`${profile.label} effort`} value={draft.effort || ""} onChange={event => patch({ effort: event.target.value })}>
                <option value="">Effort</option>
                {model.efforts.map(effort => <option key={effort} value={effort}>{effort}</option>)}
              </select>
            ) : null}
            <select className="nx-cd-input is-short" aria-label={`${profile.label} permission`} value={draft.permissionMode || ""} onChange={event => patch({ permissionMode: event.target.value })}>
              <option value="">Permission</option>
              {modes.map(row => <option key={row.id} value={row.id}>{row.label || row.id}</option>)}
            </select>
          </>
        ) : null}
        {changed ? <Button size="sm" variant="primary" disabled={state.busy || !complete} onClick={() => void save()}>{state.busy ? "Saving…" : "Save"}</Button> : saved ? <span className="nx-cd-ok"><Icon as={Check} size={12} />Saved</span> : null}
      </div>
      {state.fault ? <p className="nx-cd-error" role="alert">{state.fault}</p> : null}
    </div>
  );
}

// ---- new goal -------------------------------------------------------------------

function NewGoal({ folders, matrix, onMatrix, onPlanned, onCancel }) {
  const [draft, setDraft] = useState({ goal: "", folder: folders[0]?.path || "", checks: "", minutes: "30" });
  const [state, setState] = useState({ busy: false, fault: "" });
  const requestId = useRef(newRequestId()); // one per goal: a retry after a network blip attaches to the same job
  const profiles = matrix?.profiles || {};
  const problems = planProblems(draft, profiles);
  const patch = change => { requestId.current = newRequestId(); setDraft(current => ({ ...current, ...change })); };
  const plan = async () => {
    setState({ busy: true, fault: "" });
    try {
      const minutes = Math.round(Number(draft.minutes));
      const result = await conductorPlan({
        requestId: requestId.current, goal: draft.goal.trim(), folder: draft.folder.trim(), acceptanceChecks: checkLines(draft.checks),
        maxRuntimeSeconds: minutes >= 1 ? Math.min(86400, minutes * 60) : undefined,
      });
      onPlanned(result.job);
    } catch (error) { setState({ busy: false, fault: error.message }); }
  };
  return (
    <form className="nx-cd-new nx-scroll" onSubmit={event => { event.preventDefault(); if (!problems.length) void plan(); }}>
      <h2>New goal</h2>
      <p className="nx-cd-lead">Say what should be true at the end. The planner splits it into tasks, you read the plan, then start it. Nothing changes in your folder before you press Start.</p>
      <label className="nx-cd-field"><span>Goal</span>
        <textarea className="nx-cd-input" rows={3} value={draft.goal} onChange={event => patch({ goal: event.target.value })} placeholder="Add a sum tool with tests to this folder" />
      </label>
      <label className="nx-cd-field"><span>Folder</span>
        <input className="nx-cd-input is-mono" list="nx-cd-folders" value={draft.folder} onChange={event => patch({ folder: event.target.value })} placeholder="C:\Users\you\Projects\app" spellCheck={false} />
        <datalist id="nx-cd-folders">{folders.map(folder => <option key={folder.path} value={folder.path}>{folder.name}</option>)}</datalist>
      </label>
      <label className="nx-cd-field"><span>Checks the verifier must prove, one per line</span>
        <textarea className="nx-cd-input" rows={3} value={draft.checks} onChange={event => patch({ checks: event.target.value })} placeholder={"node verify.cjs exits with code 0\nruns.txt has exactly one line"} />
      </label>
      <label className="nx-cd-field is-narrow"><span>Time limit, minutes</span>
        <input className="nx-cd-input" inputMode="numeric" value={draft.minutes} onChange={event => patch({ minutes: event.target.value })} />
      </label>
      <Routes matrix={matrix} onSaved={profilesNow => onMatrix(current => ({ ...(current || {}), profiles: profilesNow }))} />
      {problems.length && (draft.goal || draft.checks) ? <ul className="nx-cd-problems">{problems.map(problem => <li key={problem}>{problem}</li>)}</ul> : null}
      {state.fault ? <p className="nx-cd-error" role="alert">{state.fault}</p> : null}
      <footer className="nx-cd-new-foot">
        <Button size="sm" onClick={onCancel}>Cancel</Button>
        <Button size="sm" variant="primary" type="submit" icon={Route} disabled={Boolean(problems.length) || state.busy}>{state.busy ? "Asking the planner…" : "Plan it"}</Button>
      </footer>
    </form>
  );
}

// ---- one job ------------------------------------------------------------------------

function TaskCard({ task, byId, selected, onSelect }) {
  const after = task.needs.map(need => byId.get(need)?.title || need);
  const waiting = Boolean(task.pendingRequest);
  return (
    <button type="button" className={`nx-cd-task is-${task.status}${selected ? " is-selected" : ""}${waiting ? " is-needs" : ""}`} onClick={() => onSelect(task.id)} aria-pressed={selected}>
      <span className="nx-cd-task-top">
        <ProviderMark id={markOf(task.route?.app)} size={14} />
        <span className="nx-cd-task-route">{task.routingProfile} · {task.route?.model || appLabel(task.route?.app)}</span>
        {task.status === "running" && !waiting ? <NxGrowingTree size={16} /> : <StatusDot tone={waiting ? "gold" : taskTone(task.status)} />}
      </span>
      <span className="nx-cd-task-title">{task.title || task.id}</span>
      {waiting ? <span className="nx-cd-task-note is-needs">Waiting for your approval</span>
        : task.receipt ? <span className="nx-cd-task-note">{[compactTokens(task.receipt.usage?.totalTokens) ? `${compactTokens(task.receipt.usage.totalTokens)} tokens` : "tokens not reported", durationText(task.receipt.durationMs)].filter(Boolean).join(" · ")}</span>
          : after.length ? <span className="nx-cd-task-note">after {after.join(", ")}</span> : null}
    </button>
  );
}

function Receipt({ receipt, onOpenChat }) {
  if (!receipt) return null;
  return (
    <div className="nx-cd-receipt">
      <dl>
        <div><dt>Result</dt><dd>{receipt.state}{receipt.error ? `: ${receipt.error}` : ""}</dd></div>
        <div><dt>Tokens</dt><dd>{receipt.usage?.totalTokens != null ? `${receipt.usage.totalTokens.toLocaleString()}${receipt.usage.cachedInputTokens ? ` (${receipt.usage.cachedInputTokens.toLocaleString()} cached)` : ""}` : "Not reported by the app"}</dd></div>
        <div><dt>Time</dt><dd>{durationText(receipt.durationMs)}</dd></div>
        <div><dt>Run</dt><dd className="is-mono">{receipt.runId}</dd></div>
      </dl>
      {receipt.sessionId ? <Button size="sm" icon={ArrowUpRight} onClick={() => onOpenChat?.(receipt.sessionId)}>Open its chat</Button> : null}
      {receipt.reply ? <pre className="nx-cd-reply nx-scroll">{receipt.reply}</pre> : null}
    </div>
  );
}

function TaskDetail({ task, onOpenChat, onClose }) {
  return (
    <aside className="nx-cd-detail nx-scroll" aria-label={`Task ${task.title || task.id}`}>
      <header>
        <strong>{task.title || task.id}</strong>
        <StatusDot tone={task.pendingRequest ? "gold" : taskTone(task.status)} /><span>{task.pendingRequest ? "needs you" : task.status}</span>
        <IconButton icon={X} size="sm" label="Back to the checks" onClick={onClose} />
      </header>
      <dl className="nx-cd-facts">
        <div><dt>Role</dt><dd>{task.routingProfile}</dd></div>
        <div><dt>Route</dt><dd>{routeLine(task.route, appLabel)}</dd></div>
        {task.needs.length ? <div><dt>After</dt><dd>{task.needs.join(", ")}</dd></div> : null}
      </dl>
      {task.pendingRequest ? (
        <div className="nx-cd-needs" role="status">
          <Icon as={ShieldCheck} size={15} />
          <p>This task asks before it acts. Answer in its chat; the worker picks your answer up.</p>
          {task.sessionId ? <Button size="sm" variant="primary" onClick={() => onOpenChat?.(task.sessionId)}>Open chat</Button> : null}
        </div>
      ) : null}
      {task.error ? <p className="nx-cd-error">{task.error}</p> : null}
      <h4>Prompt</h4>
      <p className="nx-cd-prompt">{task.prompt}</p>
      {task.receipt ? <><h4>Receipt</h4><Receipt receipt={task.receipt} onOpenChat={onOpenChat} /></> : task.runId ? <p className="nx-cd-muted">Running as <span className="is-mono">{task.runId}</span></p> : null}
    </aside>
  );
}

function Checks({ job, onOpenChat }) {
  const observed = new Map((job.verification?.checks || []).map(check => [check.check, check]));
  return (
    <aside className="nx-cd-detail nx-scroll" aria-label="Checks and receipts">
      <header><strong>Checks</strong><span>{job.verification ? (job.verification.passed ? "proved by the verifier" : "not proved") : job.phase === "completed" ? "" : "proved at the end"}</span></header>
      <ul className="nx-cd-checks">
        {job.acceptanceChecks.map(check => {
          const row = observed.get(check);
          return (
            <li key={check} className={row ? (row.passed ? "is-ok" : "is-bad") : ""}>
              <Icon as={row ? (row.passed ? Check : CircleAlert) : Flag} size={13} />
              <span>{check}{row?.evidence ? <small>{row.evidence}</small> : null}</span>
            </li>
          );
        })}
      </ul>
      {job.classification?.kind ? <p className="nx-cd-muted">Sorted as {job.classification.kind}, {job.classification.risk} risk. {job.classification.reason}</p>
        : job.classification?.status === "not_configured" ? <p className="nx-cd-muted">No classifier set, so the goal went straight to the planner.</p> : null}
      {job.planning.length ? (
        <>
          <h4>Before the tasks</h4>
          <ul className="nx-cd-turns">
            {job.planning.map(receipt => (
              <li key={receipt.runId}>
                <button type="button" onClick={() => receipt.sessionId && onOpenChat?.(receipt.sessionId)} disabled={!receipt.sessionId}>
                  <ProviderMark id={markOf(receipt.route?.app)} size={13} />
                  <span>{receipt.kind === "classify" ? "Sorted the goal" : "Wrote the plan"}</span>
                  <small>{[receipt.route?.model, receipt.tokens != null ? `${compactTokens(receipt.tokens)} tokens` : "tokens not reported", durationText(receipt.durationMs)].filter(Boolean).join(" · ")}</small>
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <p className="nx-cd-hint">Pick a task to see its prompt, route and receipt.</p>
    </aside>
  );
}

export function ConductorJobView({ job, onChanged, onOpenChat }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [taskId, setTaskId] = useState(null);
  useTick(job.live, 1000);
  useEffect(() => { setTaskId(null); setError(""); }, [job.id]);
  const byId = useMemo(() => new Map(job.tasks.map(task => [task.id, task])), [job.tasks]);
  const task = taskId ? byId.get(taskId) : null;
  const act = async action => {
    setBusy(action); setError("");
    try { onChanged(await conductorControl(job.id, action)); }
    catch (failure) { setError(failure.message); }
    finally { setBusy(""); }
  };
  const running = job.tasks.filter(item => item.status === "running").length;
  return (
    <div className="nx-cd-view">
      <header className="nx-cd-head">
        <div className="nx-cd-head-main">
          <h2>{job.goal}</h2>
          <span className="nx-cd-meta"><Icon as={FolderOpen} size={12} />{job.folder}{job.createdAt ? ` · planned ${ago(job.createdAt) === "now" ? "just now" : `${ago(job.createdAt)} ago`}` : ""}</span>
        </div>
        <div className="nx-cd-actions">
        <Phase phase={job.phase} />
        {job.canStart ? <Button size="sm" variant="primary" icon={Play} disabled={Boolean(busy)} onClick={() => void act("start")}>Start</Button> : null}
        {job.canPause ? <Button size="sm" icon={Pause} disabled={Boolean(busy)} onClick={() => void act("pause")}>Pause</Button> : null}
        {job.canResume ? <Button size="sm" variant="primary" icon={Play} disabled={Boolean(busy)} onClick={() => void act("resume")}>Resume</Button> : null}
        {job.canStop ? <Button size="sm" icon={Square} disabled={Boolean(busy)} onClick={() => void act("stop")}>Stop</Button> : null}
        </div>
      </header>

      {job.phase === "ready" && !job.approved ? (
        <div className="nx-cd-banner is-needs" role="status">
          <Icon as={ShieldCheck} size={16} />
          <p>The plan is ready. Read the tasks and their routes, then start. The routes are fixed now, so changing your settings won't change this job.</p>
        </div>
      ) : null}
      {job.phase === "interrupted" ? (
        <div className="nx-cd-banner is-bad" role="status">
          <Icon as={CircleAlert} size={16} />
          <p>The worker stopped before it finished (for example, the PC shut down). Its receipts are saved below. Neyvia never starts it again by itself; plan the goal again when you're ready.</p>
        </div>
      ) : null}
      {job.phase === "failed" && job.error ? (
        <div className="nx-cd-banner is-bad" role="status"><Icon as={CircleAlert} size={16} /><p>{job.error}</p></div>
      ) : null}
      {error ? <p className="nx-cd-error" role="alert">{error}</p> : null}

      <div className="nx-cd-progress" role="progressbar" aria-valuemin={0} aria-valuemax={job.tasks.length || 1} aria-valuenow={job.done} aria-label={`${job.done} of ${job.tasks.length} tasks done`}>
        <span style={{ transform: `scaleX(${job.progress})` }} />
      </div>
      <p className="nx-cd-counts">
        {job.tasks.length ? `${job.done}/${job.tasks.length} tasks done${running ? ` · ${running} running` : ""}` : job.live ? "Planning the tasks…" : "No tasks"}
        {job.receipts.length ? ` · ${job.receipts.length} turns` : ""}
        {job.tokens != null ? ` · ${job.tokens.toLocaleString()} tokens${job.tokensComplete ? "" : " (some not reported)"}` : ""}
        {job.durationMs ? ` · ${durationText(job.durationMs)}` : ""}
      </p>
      <p className="nx-cd-worker">
        <StatusDot tone={job.live ? "live" : "idle"} pulse={job.live && job.phase === "running"} />
        {job.live ? `Worker running on this PC${job.pid ? ` (process ${job.pid})` : ""}. It carries on if Neyvia or its service restarts; this page reattaches to the same job and runs.` : "Worker finished. Everything below is the saved record."}
      </p>

      <div className="nx-cd-body">
        <div className="nx-cd-tree nx-scroll" aria-label="Tasks, in the order they can run">
          {job.levels.length ? job.levels.map((level, index) => (
            <div key={index} className="nx-cd-level">
              <span className="nx-cd-level-label">{index === 0 ? "First" : index === job.levels.length - 1 && level.every(item => item.routingProfile === "verifier") ? "Last: verify" : `Then (${index})`}</span>
              {level.map(item => <TaskCard key={item.id} task={item} byId={byId} selected={item.id === taskId} onSelect={setTaskId} />)}
            </div>
          )) : (
            <div className="nx-cd-planning">
              {job.live ? <><NxGrowingTree size={36} /><p>{job.phase === "classifying" ? "Sorting the goal…" : "The planner is writing the task tree…"}</p></> : <p>No task tree was saved.</p>}
            </div>
          )}
        </div>
        {task ? <TaskDetail task={task} onOpenChat={onOpenChat} onClose={() => setTaskId(null)} /> : <Checks job={job} onOpenChat={onOpenChat} />}
      </div>
    </div>
  );
}

export function NxConductor({ target, folders = [], onOpenChat }) {
  const { status, jobs, total, nextOffset, fault, refresh, more } = useJobs();
  const preset = String(target || "").startsWith("conductor:") ? String(target).slice("conductor:".length) : "";
  const [selected, setSelected] = useState(preset === "new" ? null : preset || null);
  const [creating, setCreating] = useState(preset === "new");
  const [matrix, setMatrix] = useState(null);
  const [routesOpen, setRoutesOpen] = useState(false);
  useEffect(() => { void runtimeMatrix().then(setMatrix).catch(() => setMatrix({ runtimes: [], profiles: {} })); }, []);
  const chosenId = creating ? null : selected || jobs[0]?.id || null;
  const seed = jobs.find(job => job.id === chosenId) || null;
  const { job: raw, readFault: readError, setJob } = useJob(chosenId, seed);
  const job = useMemo(() => shapeJob(raw), [raw]);
  const shaped = useMemo(() => jobs.map(shapeJob), [jobs]);

  return (
    <section className="nx-cd" aria-label="Conductor">
      <nav className="nx-cd-list nx-scroll" aria-label="Goals">
        <div className="nx-cd-list-head">
          <Button size="sm" variant="primary" icon={Plus} onClick={() => setCreating(true)}>New goal</Button>
          <IconButton icon={Route} size="sm" label="Who does what" active={routesOpen} onClick={() => setRoutesOpen(open => !open)} />
          <IconButton icon={RefreshCw} size="sm" label="Refresh" onClick={() => void refresh()} />
        </div>
        {status === "loading" ? <div className="nx-cd-empty"><Spinner size={14} /></div> : null}
        {status === "offline" ? <p className="nx-cd-empty">The Conductor needs the Neyvia service on your PC, signed in as its owner. {fault}</p> : null}
        {status === "ready" && !jobs.length ? <p className="nx-cd-empty">No goals yet. Give one goal; the planner splits it into tasks for your agents and a verifier proves it at the end.</p> : null}
        {shaped.map(item => (
          <button key={item.id} type="button" className={`nx-cd-card${item.id === chosenId ? " is-on" : ""}`} aria-current={item.id === chosenId ? "true" : undefined}
            onClick={() => { setSelected(item.id); setCreating(false); }}>
            <span className="nx-cd-card-goal">{item.goal}</span>
            <span className="nx-cd-card-meta"><Phase phase={item.phase} /><span>{item.tasks.length ? `${item.done}/${item.tasks.length}` : ""}</span></span>
            <span className="nx-cd-card-bar"><span style={{ transform: `scaleX(${item.progress})` }} /></span>
          </button>
        ))}
        {nextOffset != null ? <Button size="sm" onClick={more}>Show more ({total - jobs.length} left)</Button> : null}
        <button type="button" className="nx-cd-switch" onClick={() => os.showPane("mission", "")}>Night Shift missions<Icon as={ArrowUpRight} size={12} /></button>
      </nav>
      <div className="nx-cd-main">
        {routesOpen && !creating ? (
          <div className="nx-cd-routes-pop">
            <Routes matrix={matrix} compact onSaved={profiles => setMatrix(current => ({ ...(current || {}), profiles }))} />
          </div>
        ) : null}
        {creating ? (
          <NewGoal folders={folders} matrix={matrix} onMatrix={setMatrix} onCancel={() => setCreating(false)}
            onPlanned={planned => { setCreating(false); setSelected(planned.id); setJob(planned); void refresh(); }} />
        ) : job ? (
          <>
            {readError ? <p className="nx-cd-error is-top" role="alert">Couldn't read the latest state: {readError}. Showing the last saved one.</p> : null}
            <ConductorJobView job={job} onOpenChat={onOpenChat} onChanged={next => { if (next) setJob(next); void refresh(); }} />
          </>
        ) : status === "ready" ? (
          <div className="nx-cd-empty is-big">
            <NxGrowingTree size={56} growing={false} />
            <p>One goal, routed to the right agents, checked at the end.</p>
            <Button size="sm" variant="primary" icon={Plus} onClick={() => setCreating(true)}>New goal</Button>
          </div>
        ) : null}
      </div>
    </section>
  );
}
