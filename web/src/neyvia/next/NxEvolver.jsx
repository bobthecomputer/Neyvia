import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FlaskConical, MessageSquarePlus, Play, RefreshCw, X } from "lucide-react";

import "./nxEvolver.css";
import { callNx } from "./nxApi.js";
import { sendToChat } from "./nxDocsApi.js";
import { os } from "./nxOsStore.js";
import { Button, Icon, IconButton, Popover, Segmented, Sheet, Spinner, StatusDot, local, useMedia } from "./nxPrimitives.jsx";
import {
  explainTrial, formatValue, groupFamilies, headlineStats, jobActive, jobOutcomes, jobState, latestDecisive, objectiveLabel,
  objectiveOrder, percentChange, runBudget, seconds, shortHash, stageLabel,
} from "./nxEvolverModel.js";
import { Hash, Lineage, LockState, Panels, ParetoFront, TrialCard, Verdict } from "./NxEvolverParts.jsx";

// Lab > Hill climbing: the Evolver's user side. It reads the same frozen state
// the model reads with neyvia.evolver.* (state, receipt, lineage, genome, run,
// job) through the evolver_*_command backend commands. Only built-in domains
// run; judges, panels and scoring are locked and never editable here.

const DOMAIN_KEY = "evolver.domain";
const JOB_KEY = "evolver.job";

function useEvolverState() {
  const [state, setState] = useState({ status: "loading", domains: [], error: "" });
  const alive = useRef(true);
  const load = useCallback(async () => {
    setState(previous => ({ ...previous, refreshing: previous.status === "ready" }));
    try {
      const result = await callNx("evolver_state_command", {});
      if (alive.current) setState({ status: "ready", domains: result?.domains || [], scope: result?.scope || "", error: "" });
    } catch (error) {
      if (alive.current) setState(previous => ({ ...previous, status: previous.domains.length ? "ready" : "error", refreshing: false, error: error?.message || "The Optimization Lab can't be read right now." }));
    }
  }, []);
  useEffect(() => { alive.current = true; void load(); return () => { alive.current = false; }; }, [load]);
  return { ...state, refresh: load };
}

/** The last run started from this screen, followed until it finishes (also after a reload). */
function useJob(onFinished) {
  const [saved, setSaved] = useState(() => local.get(JOB_KEY, null));
  const [job, setJob] = useState(null);
  const [error, setError] = useState("");
  const finished = useRef(onFinished);
  finished.current = onFinished;
  useEffect(() => {
    if (!saved?.id) { setJob(null); return undefined; }
    let alive = true;
    let timer = 0;
    let wasActive = false;
    const poll = async () => {
      try {
        const result = await callNx("evolver_job_command", { requestId: saved.id });
        if (!alive) return;
        setJob(result?.job || null); setError("");
        if (jobActive(result?.job)) { wasActive = true; timer = setTimeout(poll, 4000); }
        else if (wasActive) finished.current?.();
      } catch (problem) {
        if (!alive) return;
        setError(problem?.message || "The run can't be read.");
        timer = setTimeout(poll, 8000);
      }
    };
    void poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [saved?.id]);
  const follow = useCallback(value => { local.set(JOB_KEY, value); setSaved(value); }, []);
  return { saved, job, error, follow };
}

function RunForm({ domain, family, budget, onStarted, onClose }) {
  const [trials, setTrials] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef("");
  const start = async () => {
    setBusy(true); setError("");
    // One id per attempt: a retry after a network error replays the same job instead of starting a second one.
    if (!requestId.current) requestId.current = `ui-${domain.id}-${Date.now().toString(36)}`;
    try {
      const result = await callNx("evolver_run_command", { domain: domain.id, requestId: requestId.current, maxTrials: trials });
      onStarted({ id: requestId.current, domain: domain.id }, result?.job);
    } catch (problem) {
      setError(problem?.message || "The run didn't start.");
      if (problem?.code !== "network") requestId.current = "";
    } finally { setBusy(false); }
  };
  const minutes = Math.round((Number(domain.budget?.max_seconds) || 0) / 60);
  return (
    <div className="nx-evo-run">
      <p><strong>{family.name} v{domain.version}</strong> · {budget.left} of {budget.max} trials left</p>
      {budget.options.length > 1 ? <Segmented label="Trials to run" value={trials} onChange={setTrials} options={budget.options.map(value => ({ value, label: value === 1 ? "1 trial" : `${value} trials` }))} size="sm" /> : null}
      <p className="nx-evo-muted">GPT-6 Luna proposes a shorter text. It is then paired with the current version on {domain.budget?.min_pairs || 10} discovery tasks, held-out tasks and fresh tasks, with the same seed for both. Up to {minutes} min per trial. Only this workspace's current version can change; nothing is published.</p>
      {error ? <p className="nx-evo-error" role="alert">{error}</p> : null}
      <div className="nx-evo-run-actions">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" icon={Play} disabled={busy} onClick={start}>{busy ? "Starting" : trials === 1 ? "Start trial" : `Start ${trials} trials`}</Button>
      </div>
    </div>
  );
}

function RunButton({ domain, family, budget, onStarted, phone, disabled }) {
  const [open, setOpen] = useState(false);
  const anchor = useRef(null);
  const started = (saved, job) => { setOpen(false); onStarted(saved, job); };
  const form = <RunForm domain={domain} family={family} budget={budget} onStarted={started} onClose={() => setOpen(false)} />;
  return (
    <>
      <Button ref={anchor} variant="primary" icon={Play} disabled={disabled || Boolean(budget.blocked)} title={budget.blocked || "Run an evolution trial"} onClick={() => setOpen(true)}>Run a trial</Button>
      {phone
        ? <Sheet open={open} onClose={() => setOpen(false)} title="Run a trial">{form}</Sheet>
        : <Popover anchor={anchor} open={open} onClose={() => setOpen(false)} placement="bottom-end" width={360} label="Run a trial">{form}</Popover>}
    </>
  );
}

function JobCard({ job, saved, error, onDismiss, onShowTrial }) {
  if (!saved?.id) return null;
  const view = jobState(job?.state);
  const outcomes = jobOutcomes(job);
  const took = job?.finished && job?.created ? seconds(job.finished - job.created) : "";
  return (
    <section className="nx-evo-card nx-evo-job" aria-live="polite" aria-label="Latest run">
      <header>
        <h2>Latest run</h2>
        <code className="nx-evo-muted" title={saved.id}>{saved.id}</code>
        <span className="nx-evo-spacer" />
        <IconButton icon={X} size="sm" label="Stop following this run" onClick={onDismiss} />
      </header>
      {!job && !error ? <div className="nx-evo-empty"><Spinner size={14} /> Reading the run</div> : null}
      {error ? <p className="nx-evo-error">{error}</p> : null}
      {job ? (
        <>
          <p className="nx-evo-job-line">
            <span className={`nx-evo-verdict is-${view.tone}`}><StatusDot tone={view.tone} pulse={view.pulse} />{view.word}</span>
            <span>{job.domain}{job.payload?.maxTrials ? ` · ${job.payload.maxTrials} trial${job.payload.maxTrials > 1 ? "s" : ""}` : ""}{took ? ` · took ${took}` : ""}</span>
          </p>
          {job.state === "failed" && job.error ? <p className="nx-evo-muted">{job.error.split(/;\s*raw receipt/i)[0]}. The current version stays.</p> : null}
          {outcomes.length ? (
            <p className="nx-evo-job-line">
              <span className="nx-evo-muted">Outcome</span>
              {outcomes.map(outcome => (
                <button key={`${outcome.domain}-${outcome.trial}`} type="button" className="nx-evo-link" onClick={() => onShowTrial(outcome.domain, outcome.trial)}>
                  Trial {outcome.trial ?? "?"}: <Verdict state={outcome.state} />
                </button>
              ))}
            </p>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function Summary({ domain, family }) {
  const receipt = latestDecisive(domain.receipts);
  const why = explainTrial(receipt, domain.objectives, family.id);
  const headline = headlineStats(receipt);
  const budget = runBudget(domain);
  return (
    <section className={`nx-evo-card nx-evo-hero is-${why.tone}`} aria-label="Current state">
      <div className="nx-evo-hero-top">
        <div className="nx-evo-hero-title">
          <h2>{family.name}</h2>
          <p className="nx-evo-muted">{family.goal}</p>
        </div>
        <LockState domain={domain} />
      </div>
      {domain.frozen_lock?.ok === false ? (
        <p className="nx-evo-error" role="alert">A locked check changed: {domain.frozen_lock.error || "a judge file no longer matches its hash"}. Trials stay blocked and the current version stays until the change is reviewed as a new version.</p>
      ) : null}
      {receipt ? (
        <>
          <p className="nx-evo-hero-verdict"><Verdict state={receipt.state} /><span>Trial {receipt.trial_number}: {why.headline}</span></p>
          <ul className="nx-evo-reasons">{why.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
          {headline ? (
            <div className="nx-evo-metrics" aria-label={`Measured on ${stageLabel(headline.stage).toLowerCase()}`}>
              {objectiveOrder(headline.statistics).map(name => {
                const stat = headline.statistics[name];
                return (
                  <div key={name} className="nx-evo-metric">
                    <span className="nx-evo-metric-label">{objectiveLabel(name, family.id)}</span>
                    <span className="nx-evo-metric-value">{formatValue(name, stat.incumbent_mean)} <span aria-hidden="true">→</span><span className="nx-evo-sr"> to </span> {formatValue(name, stat.candidate_mean)}</span>
                    <span className={`nx-evo-metric-change${stat.noninferior === false ? " is-bad" : stat.improved ? " is-good" : ""}`}>{percentChange(stat.incumbent_mean, stat.candidate_mean) || "same"}{stat.noninferior === false ? " · could be worse" : ""}</span>
                  </div>
                );
              })}
              <p className="nx-evo-muted nx-evo-metrics-note">Current → candidate, {stageLabel(headline.stage).toLowerCase()} ({headline.stage.sample_count} paired tasks). Fitness: {family.fitness} (× 1,000).</p>
            </div>
          ) : null}
        </>
      ) : <p className="nx-evo-empty">No trial yet in this version.</p>}
      <dl className="nx-evo-facts is-hero">
        <div><dt>Current version</dt><dd><Hash value={domain.incumbent} /></dd></div>
        <div><dt>Trials</dt><dd>{budget.used} of {budget.max} in v{domain.version} · {family.totalTrials} across versions</dd></div>
        <div><dt>Evaluations</dt><dd>{domain.evaluations} of {domain.budget?.max_evaluations}</dd></div>
        <div><dt>Held-out tasks</dt><dd>{(domain.held_out_used || []).length} of {(domain.panels || []).filter(panel => panel.role !== "discovery").length} panels used</dd></div>
        <div><dt>Gate</dt><dd>α {domain.budget?.alpha} · at least {domain.budget?.min_pairs} pairs</dd></div>
      </dl>
    </section>
  );
}

// What the lab is for, said plainly, and a first step that goes through the chat (never sent by itself).
const START_DRAFT = "In the Optimization Lab, start an optimization: try a shorter version of the Notes manual, test it against the current one on the same tasks, and keep it only if it does at least as well. Show me the result there before anything changes.";

function LabIntro({ session, nav, onShowChat }) {
  const start = () => {
    const where = sendToChat(START_DRAFT, { session, onNewChat: nav?.onNewChat, onShowChat, local });
    os.notify({ level: "success", message: where === "chat" ? "A draft is in your message box. Read it, then send it." : "A draft is in a new chat's message box. Read it, then send it." });
  };
  return (
    <div className="nx-evo nx-evo-center">
      <section className="nx-evo-intro" aria-labelledby="nx-evo-intro-title">
        <Icon as={FlaskConical} size={22} />
        <h2 id="nx-evo-intro-title">Optimization Lab</h2>
        <p>The lab makes the instructions your agents read shorter, without making the agents worse.</p>
        <ol className="nx-evo-intro-steps">
          <li>It writes a shorter version of a set of instructions.</li>
          <li>It tests the new and the current version side by side on the same tasks.</li>
          <li>It keeps the new one only when it does at least as well, and shows you why.</li>
        </ol>
        <Button variant="primary" icon={MessageSquarePlus} onClick={start}>Start an optimization</Button>
        <p className="nx-evo-muted">This puts a ready-to-send message in the chat. Nothing runs until you send it.</p>
      </section>
    </div>
  );
}

export function NxEvolver({ target, session, nav, onShowChat }) {
  const phone = useMedia("(max-width: 760px)");
  const data = useEvolverState();
  const families = useMemo(() => groupFamilies(data.domains), [data.domains]);
  const [domainId, setDomainId] = useState(() => (typeof target === "string" && target) || local.get(DOMAIN_KEY, ""));
  const [focusTrial, setFocusTrial] = useState(null);
  const run = useJob(data.refresh);

  const all = families.flatMap(family => family.versions);
  const domain = all.find(row => row.id === domainId) || families[0]?.current || null;
  const family = domain ? families.find(entry => entry.versions.includes(domain)) : null;
  const choose = id => { setDomainId(id); local.set(DOMAIN_KEY, id); setFocusTrial(null); };

  if (data.status === "loading") return <div className="nx-evo nx-evo-center"><Spinner size={16} /></div>;
  if (data.status === "error") {
    return (
      <div className="nx-evo nx-evo-center">
        <div className="nx-pane-honest">
          <Icon as={FlaskConical} size={22} />
          <strong>The Optimization Lab can't be read right now</strong>
          <p>{data.error}</p>
          <Button variant="outline" icon={RefreshCw} onClick={data.refresh}>Try again</Button>
        </div>
      </div>
    );
  }
  if (!domain) return <LabIntro session={session} nav={nav} onShowChat={onShowChat} />;
  const budget = runBudget(domain, family.current);
  const receipts = [...(domain.receipts || [])].sort((a, b) => b.trial_number - a.trial_number);
  const showTrial = (id, trial) => { choose(id); setFocusTrial(trial); };
  const started = (saved, job) => { run.follow(saved); if (job) void data.refresh(); };

  return (
    <div className="nx-evo">
      <div className="nx-evo-tools">
        <Segmented label="What is being improved" value={family.id} onChange={id => choose(families.find(entry => entry.id === id).current.id)}
          options={families.map(entry => ({ value: entry.id, label: entry.name }))} />
        {family.versions.length > 1 ? (
          <Segmented label="Version" size="sm" value={domain.id} onChange={choose}
            options={family.versions.map(row => ({ value: row.id, label: row === family.current ? `v${row.version} · current` : `v${row.version}` }))} />
        ) : null}
        <span className="nx-evo-spacer" />
        {data.refreshing ? <Spinner size={12} /> : null}
        <IconButton icon={RefreshCw} label="Refresh" onClick={data.refresh} />
        <RunButton domain={domain} family={family} budget={budget} phone={phone} disabled={jobActive(run.job)} onStarted={started} />
      </div>
      {budget.blocked ? <p className="nx-evo-muted nx-evo-budget-note">{budget.blocked}</p> : null}
      {data.error ? <p className="nx-evo-error" role="alert">{data.error}</p> : null}
      {domain !== family.current ? <p className="nx-evo-note-bar">You're looking at v{domain.version}, an earlier version kept with all its trials. Its scores are measured on its own tasks and are not combined with v{family.current.version}.</p> : null}

      <JobCard job={run.job} saved={run.saved} error={run.error} onDismiss={() => run.follow(null)} onShowTrial={showTrial} />
      <Summary domain={domain} family={family} />

      <div className="nx-evo-grid">
        <section className="nx-evo-card" aria-labelledby="nx-evo-front">
          <header><h2 id="nx-evo-front">Pareto front</h2><span className="nx-evo-muted">{objectiveLabel("success", family.id)} against instruction tokens</span></header>
          <ParetoFront domain={domain} family={family.id} />
        </section>
        <section className="nx-evo-card" aria-labelledby="nx-evo-panels">
          <header><h2 id="nx-evo-panels">Task panels</h2><span className="nx-evo-muted">Each held-out panel is used once, then rotated</span></header>
          <Panels domain={domain} />
        </section>
      </div>

      <section className="nx-evo-card" aria-labelledby="nx-evo-trials">
        <header><h2 id="nx-evo-trials">Trials</h2><span className="nx-evo-muted">{receipts.length ? `${receipts.length} in v${domain.version}, every one kept` : ""}</span></header>
        {receipts.length
          ? <ul className="nx-evo-trials">{receipts.map(receipt => <TrialCard key={`${domain.id}-${receipt.id}-${focusTrial === receipt.trial_number}`} receipt={receipt} domain={domain} family={family.id} defaultOpen={focusTrial === receipt.trial_number} />)}</ul>
          : <p className="nx-evo-empty">No trial yet. Run one to compare a candidate with the current version.</p>}
      </section>

      <section className="nx-evo-card" aria-labelledby="nx-evo-lineage">
        <header><h2 id="nx-evo-lineage">Lineage</h2><span className="nx-evo-muted">Where each candidate came from · current <code>{shortHash(domain.incumbent)}</code></span></header>
        <Lineage domain={domain} />
      </section>
    </div>
  );
}
