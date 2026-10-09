import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, Check, CornerDownRight, Eraser, GitBranch, GitCommitHorizontal, GitMerge, GitPullRequestArrow, MessageCircleQuestion, OctagonX, TriangleAlert } from "lucide-react";

import "./nxParallel.css";
import { ProviderMark } from "./ProviderMark.jsx";
import { NxGrowingTree } from "./NxGrowingTree.jsx";
import { Button, Icon, Spinner, StatusDot, ago, elapsed, useTick } from "./nxPrimitives.jsx";
import { parallelAction, readParallel } from "./nxParallelApi.js";
import {
  AGENT_LABEL, NODE_LABEL, activityLine, RUN_LABEL, RUN_TONE, actionNote, laneBranchLabel, laneQuestions, laneStatus, markForAgent,
  mergeNodes, railSegments, runActions, runActive, runSummary, shapeRuns,
} from "./nxParallelModel.js";

// Parallel branches (plan 29): one main agent and a worker per track, each on its own worktree and branch, merged
// one at a time into an integration branch. The pane shows the lanes live, the merge order, and the four things a
// person may do: Merge now, Finish into base, Settle worktrees, Stop all. Only the irreversible ones ask first.
// Rows come from GET /api/ui/parallel, re-read every 2 s while a run can still change (8 s otherwise, never while the
// page is hidden). The agents themselves start, ask, answer and resolve through neyvia.parallel.*.

/** Every run, kept live. `apply` puts an action's reply in without waiting for the next read. */
export function useParallel() {
  const [state, setState] = useState({ status: "loading", runs: [], error: "" });
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const inflight = useRef(false);
  const refresh = useCallback(async () => {
    if (inflight.current) return; // a slow read is never joined by another: the next tick waits for it
    inflight.current = true;
    try {
      const runs = shapeRuns(await readParallel());
      if (alive.current) setState({ status: "ready", runs, error: "" });
    } catch (failure) {
      if (alive.current) setState(previous => ({ status: previous.runs.length ? "ready" : "offline", runs: previous.runs, error: failure.message }));
    } finally { inflight.current = false; }
  }, []);
  const active = state.runs.some(runActive);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    const timer = setInterval(() => { if (!document.hidden) void refresh(); }, active ? 2000 : 8000);
    return () => clearInterval(timer);
  }, [refresh, active]);
  const apply = useCallback(run => {
    const [shaped] = shapeRuns({ run });
    if (shaped) setState(previous => ({ ...previous, runs: previous.runs.map(row => (row.id === shaped.id ? shaped : row)) }));
  }, []);
  return { ...state, refresh, apply };
}

function Chip({ tone, pulse = false, working = false, children }) {
  return (
    <span className={`nx-pl-chip is-${tone}`}>
      {working ? <NxGrowingTree size={15} /> : <StatusDot tone={tone} pulse={pulse} />}
      {children}
    </span>
  );
}

/** One question a worker asked the main agent, and the answer once it is given. */
function Exchange({ row, onAnswer, canAnswer }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const waiting = row.answer == null;
  const send = async () => {
    setBusy(true);
    try { await onAnswer(text.trim()); setOpen(false); setText(""); } finally { setBusy(false); }
  };
  return (
    <div className={`nx-pl-qa${waiting ? " is-waiting" : ""}`}>
      <p className="nx-pl-q"><Icon as={MessageCircleQuestion} size={13} /><span>{row.question}</span>{row.askedAt ? <time>{ago(row.askedAt) === "now" ? "just now" : `${ago(row.askedAt)} ago`}</time> : null}</p>
      {waiting ? (
        <p className="nx-pl-a is-wait"><Icon as={CornerDownRight} size={13} /><span>Waiting for the main agent to answer</span>
          {canAnswer && !open ? <button type="button" className="nx-pl-link" onClick={() => setOpen(true)}>Answer it yourself</button> : null}
        </p>
      ) : (
        <p className="nx-pl-a"><Icon as={CornerDownRight} size={13} /><span>{row.answer}</span></p>
      )}
      {waiting && open ? (
        <form className="nx-pl-reply" onSubmit={event => { event.preventDefault(); if (text.trim()) void send(); }}>
          <input className="nx-pl-input" value={text} onChange={event => setText(event.target.value)} placeholder="Your answer, sent to this worker" aria-label="Your answer" autoFocus />
          <Button size="sm" variant="primary" type="submit" disabled={!text.trim() || busy}>Send</Button>
          <Button size="sm" onClick={() => setOpen(false)}>Cancel</Button>
        </form>
      ) : null}
    </div>
  );
}

function Lane({ lane, run, isMain = false, onOpenChat, onAnswer, index }) {
  const status = laneStatus(lane, run);
  const questions = laneQuestions(lane);
  const shown = questions.slice(-2);
  const agent = AGENT_LABEL[lane.agent] || lane.agent;
  const route = [agent, [lane.model, lane.effort].filter(Boolean).join(" ")].filter(Boolean).join(" · ");
  const branch = isMain ? lane.branch || run.integrationBranch : laneBranchLabel(lane, run);
  const say = activityLine(lane.lastActivity);
  const asking = questions.some(row => row.answer == null); // the question below already says what it waits for
  // A lane whose work is in (merged, or done while the run moves on) keeps its answered questions one tap away; lanes at work show them open.
  const folded = shown.length > 0 && shown.every(row => row.answer != null) && (["merged", "settled"].includes(lane.state) || (lane.state === "done" && run.state !== "working"));
  const exchanges = shown.map(row => <Exchange key={row.id} row={row} canAnswer={!isMain && run.state !== "settled" && run.state !== "stopped"} onAnswer={answer => onAnswer(lane.id, row.id, answer)} />);
  const open = () => lane.session && onOpenChat?.(lane.session);
  return (
    <li className={`nx-pl-lane is-s-${status.key}${status.working ? " is-working" : ""}${isMain ? " is-main" : ""}`} style={{ "--i": index }}>
      <span className="nx-pl-node" aria-hidden="true" />
      <header className="nx-pl-head">
        <span className="nx-pl-coin"><ProviderMark id={markForAgent(lane.agent)} size={20} title={agent} /></span>
        <div className="nx-pl-id">
          {lane.session && onOpenChat ? <button type="button" className="nx-pl-title" onClick={open} title={`Open ${lane.title} chat`}>{lane.title}</button> : <span className="nx-pl-title">{lane.title}</span>}
          <span className="nx-pl-sub"><span className="nx-pl-branch" title={lane.branch}><Icon as={GitBranch} size={11} />{branch}</span><span>{route}</span></span>
          {say && !(status.key === "asking" && asking) ? <p className={`nx-pl-say${status.working ? " is-live" : ""}`} title={String(lane.lastActivity).slice(-600)}>{say}</p> : null}
        </div>
        <div className="nx-pl-end">
          {!isMain && !["starting", "settled"].includes(lane.state) ? <span className="nx-pl-ahead" title={`${lane.commitsAhead} ${lane.commitsAhead === 1 ? "commit" : "commits"} ahead of ${run.base}`}><Icon as={GitCommitHorizontal} size={13} />{lane.commitsAhead}<span className="nx-pl-ahead-word">ahead</span></span> : null}
          <Chip tone={status.tone} pulse={status.key === "asking"} working={status.working}>{isMain && status.key === "working" && run.state === "conflict" ? "Resolving" : status.label}</Chip>
        </div>
      </header>
      {lane.error ? <p className="nx-pl-error" role="alert">{lane.error}</p> : null}
      {folded ? (
        <details className="nx-pl-fold">
          <summary>{shown.length === 1 ? "1 question, answered" : `${shown.length} questions, answered`}</summary>
          {exchanges}
        </details>
      ) : exchanges}
    </li>
  );
}

function Rail({ run }) {
  const segments = railSegments(run);
  if (!segments.length) return null;
  return (
    <div className="nx-pl-rail" role="img" aria-label={runSummary(run)}>
      {segments.map(segment => <span key={segment.id} className={`nx-pl-seg is-${segment.key}${segment.working ? " is-working" : ""}`} title={`${segment.title}: ${segment.key}`} />)}
    </div>
  );
}

function NodeIcon({ status }) {
  if (status === "merged") return <Icon as={Check} size={12} />;
  if (status === "conflict") return <Icon as={TriangleAlert} size={12} />;
  if (status === "merging") return <Spinner size={10} />;
  return <span className="nx-pl-pip" aria-hidden="true" />;
}

function MergeStrip({ run, onOpenMain }) {
  const nodes = mergeNodes(run);
  const conflict = nodes.find(node => node.status === "conflict");
  const merged = nodes.filter(node => node.status === "merged").length;
  const landed = ["finished", "settled"].includes(run.state);
  return (
    <section className="nx-pl-merge" aria-label="Merge order">
      <header className="nx-pl-merge-head">
        <strong>Merge order</strong>
        <span>{merged} of {nodes.length} merged into <code>{run.integrationBranch}</code></span>
      </header>
      <ol className="nx-pl-nodes">
        <li className="nx-pl-end-node is-base" title={run.baseCommit ? `${run.base} at ${run.baseCommit.slice(0, 7)}` : run.base}><Icon as={GitBranch} size={12} />{run.base}</li>
        {nodes.map(node => (
          <li key={node.id} className={`nx-pl-nodewrap is-${node.status}`}>
            <span className="nx-pl-link-line" aria-hidden="true" />
            <span className={`nx-pl-mnode is-${node.status}`} title={node.commit ? `${node.title} · ${node.commit.slice(0, 7)}` : node.title}>
              <NodeIcon status={node.status} /><b>{node.id}</b><em>{NODE_LABEL[node.status]}</em>
            </span>
          </li>
        ))}
        <li className="nx-pl-nodewrap is-end"><span className={`nx-pl-link-line${landed ? " is-lit" : ""}`} aria-hidden="true" /></li>
        <li className={`nx-pl-end-node is-integration${landed ? " is-landed" : ""}`} title={run.integrationBranch}><Icon as={GitMerge} size={12} />{landed && run.finish ? run.finish.into : "integration"}</li>
      </ol>
      {conflict ? (
        <div className="nx-pl-conflict" role="alert">
          <Icon as={TriangleAlert} size={16} />
          <div>
            <strong>{conflict.id} conflicts with {run.conflict?.previousTracks?.length ? run.conflict.previousTracks.join(", ") : "the merged tracks"}</strong>
            <ul>{conflict.files.map(file => <li key={file}><code>{file}</code></li>)}</ul>
          </div>
          <Button size="sm" variant="primary" icon={ArrowUpRight} disabled={!run.main.session} onClick={onOpenMain}>Open in main agent</Button>
        </div>
      ) : null}
      {run.checks ? (
        <details className={`nx-pl-checks${run.checks.passed ? " is-pass" : " is-fail"}`}>
          <summary><Icon as={run.checks.passed ? Check : TriangleAlert} size={13} />{run.checks.passed ? "Checks passed" : "Checks failed"}{run.checks.command ? <code>{run.checks.command}</code> : null}</summary>
          {run.checks.output ? <pre>{run.checks.output}</pre> : null}
        </details>
      ) : null}
    </section>
  );
}

const CONFIRM = {
  finish: run => ({ title: `Finish into ${run.base}?`, body: <>This merges <code>{run.integrationBranch}</code> into <code>{run.base}</code>. Your checkout of <code>{run.base}</code> has to be clean.</>, action: `Finish into ${run.base}`, variant: "primary" }),
  settle: run => ({ title: "Settle the worktrees?", body: <>This removes the {run.tracks.length + 1} worktrees and deletes the merged branches. A branch that was never merged is kept, and the receipt says so.</>, action: "Settle worktrees", variant: "primary" }),
  stop: () => ({ title: "Stop everything?", body: <>This ends the agent sessions this run started. Their commits and worktrees stay as they are.</>, action: "Stop all", variant: "warn" }),
};

function Actions({ run, onRun, busy, note, error }) {
  const [confirming, setConfirming] = useState("");
  useEffect(() => { setConfirming(""); }, [run.id, run.state]);
  const actions = runActions(run);
  const ask = CONFIRM[confirming]?.(run);
  const go = async operation => {
    setConfirming("");
    await onRun(operation, operation === "finish" ? { into: run.base, approved: true } : {});
  };
  const button = (key, label, icon, props = {}) => (
    <Button size="sm" icon={icon} disabled={!actions[key]?.enabled || Boolean(busy)} loading={busy === key} title={actions[key]?.enabled ? undefined : actions[key]?.why} {...props}>{label}</Button>
  );
  return (
    <footer className="nx-pl-actions">
      <div className="nx-pl-note" aria-live="polite">
        {error ? <p className="is-error" role="alert">{error}</p> : note ? <p>{note}</p> : null}
      </div>
      {ask ? (
        <div className={`nx-pl-confirm is-${ask.variant}`} role="alertdialog" aria-label={ask.title}>
          <div><strong>{ask.title}</strong><p>{ask.body}</p></div>
          <Button size="sm" onClick={() => setConfirming("")}>Cancel</Button>
          <Button size="sm" variant={ask.variant} autoFocus onClick={() => void go(confirming)}>{ask.action}</Button>
        </div>
      ) : (
        <div className="nx-pl-btns">
          {button("merge", "Merge now", GitMerge, { variant: "outline", onClick: () => void onRun("merge", {}) })}
          {button("finish", `Finish into ${run.base}`, GitPullRequestArrow, { variant: actions.finish.enabled ? "primary" : "outline", onClick: () => setConfirming("finish") })}
          {button("settle", "Settle worktrees", Eraser, { variant: "outline", onClick: () => setConfirming("settle") })}
          <span className="nx-pl-gap" />
          {button("stop", "Stop all", OctagonX, { variant: "outline", className: "nx-pl-stop", onClick: () => setConfirming("stop") })}
        </div>
      )}
    </footer>
  );
}

function Header({ run, runs, onPick }) {
  const live = runActive(run);
  useTick(live, 1000);
  const tone = RUN_TONE[run.state] || "idle";
  const since = elapsed(run.createdAt);
  return (
    <header className="nx-pl-top">
      <div className="nx-pl-top-main">
        <h2>{run.goal}</h2>
        <div className="nx-pl-flow">
          <span className="nx-pl-ref" title="Base branch"><Icon as={GitBranch} size={11} />{run.base}</span>
          <span className="nx-pl-arrow" aria-hidden="true" />
          <span className="nx-pl-ref is-int" title="Integration branch"><Icon as={GitMerge} size={11} />{run.integrationBranch}</span>
          <span className="nx-pl-sum">{runSummary(run)}{live && since ? ` · ${since}` : ""}</span>
        </div>
      </div>
      <div className="nx-pl-top-side">
        <Chip tone={tone} pulse={run.state === "conflict"} working={live && tone === "live"}>{RUN_LABEL[run.state] || run.state}</Chip>
        {runs.length > 1 ? (
          <select className="nx-pl-select" value={run.id} onChange={event => onPick(event.target.value)} aria-label="Run">
            {runs.map(row => <option key={row.id} value={row.id}>{row.goal.length > 44 ? `${row.goal.slice(0, 43)}…` : row.goal}</option>)}
          </select>
        ) : null}
      </div>
    </header>
  );
}

function Empty({ status, error }) {
  if (status === "loading") return <div className="nx-stage-loading"><Spinner size={16} /></div>;
  return (
    <div className="nx-pl-empty">
      <NxGrowingTree size={56} growing={false} />
      {status === "offline" ? (
        <p>Parallel branches need the Neyvia service on your PC, signed in as its owner.{error ? ` ${error}` : ""}</p>
      ) : (
        <>
          <h3>No parallel runs yet</h3>
          <p>A run gives each task its own worktree and branch, lets the agents ask a main agent when they are stuck, and merges everything back into one branch.</p>
          <p className="nx-pl-try">In Claude Code or Neyvia, say <q>spin up 3 worktrees for this and merge them back</q>.</p>
        </>
      )}
    </div>
  );
}

/** The Parallel branches pane. `target` is a run id, or empty for the newest run. */
export function NxParallel({ target = "", nav }) {
  const { status, runs, error, refresh, apply } = useParallel();
  const [picked, setPicked] = useState(target || "");
  useEffect(() => { setPicked(target || ""); }, [target]);
  const run = runs.find(row => row.id === picked) || runs[0] || null;
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");
  const [failure, setFailure] = useState("");
  useEffect(() => { setNote(""); setFailure(""); }, [run?.id]);

  const onRun = useCallback(async (operation, extra) => {
    if (!run) return;
    setBusy(operation); setFailure(""); setNote("");
    try {
      const reply = await parallelAction(operation, { run: run.id, ...extra });
      if (reply?.run) apply(reply.run);
      setNote(actionNote(operation, reply));
    } catch (problem) { setFailure(problem.message); }
    finally { setBusy(""); void refresh(); } // state is read again either way: files and sessions may already have changed
  }, [run?.id, apply, refresh]);

  const onAnswer = useCallback(async (track, questionId, answer) => {
    try { apply((await parallelAction("answer", { run: run.id, track, answer, questionId })).run); setFailure(""); }
    catch (problem) { setFailure(problem.message); throw problem; }
    void refresh();
  }, [run?.id, apply, refresh]);

  const openMain = useCallback(() => run?.main?.session && nav?.onOpenChat?.(run.main.session), [run, nav]);
  const receipt = run?.state === "settled" && run.receipt ? actionNote("settle", { receipt: run.receipt }) : "";
  const finished = run?.finish ? `Finished into ${run.finish.into}${run.finish.commit ? ` at ${run.finish.commit.slice(0, 7)}` : ""}.` : "";
  const lanes = useMemo(() => run?.tracks || [], [run]);

  if (!run) return <section className="nx-pl" aria-label="Parallel branches"><Empty status={status} error={error} /></section>;
  return (
    <section className="nx-pl" aria-label="Parallel branches">
      <Header run={run} runs={runs} onPick={setPicked} />
      <Rail run={run} />
      <ol className="nx-pl-lanes nx-scroll" aria-label="Agents, the main agent first">
        <Lane lane={run.main} run={run} isMain onOpenChat={nav?.onOpenChat} index={0} />
        {lanes.map((lane, index) => <Lane key={lane.id} lane={lane} run={run} onOpenChat={nav?.onOpenChat} onAnswer={onAnswer} index={index + 1} />)}
      </ol>
      <div className="nx-pl-foot">
        <MergeStrip run={run} onOpenMain={openMain} />
        <Actions run={run} onRun={onRun} busy={busy} note={note || [receipt, finished].filter(Boolean).join(" ") || (run.error ? run.error : "")} error={failure || (status === "ready" ? error : "")} />
      </div>
    </section>
  );
}
