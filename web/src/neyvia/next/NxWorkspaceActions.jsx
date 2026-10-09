import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, CircleCheck, CircleX, ExternalLink, GitCommitHorizontal, TriangleAlert, Upload } from "lucide-react";

import { Counts, FilePath, StatusBadge } from "./NxWorkspaceBits.jsx";
import { Button, Icon, Spinner } from "./nxPrimitives.jsx";
import { callNx } from "./nxApi.js";
import { recallCommit, rememberCommit } from "./nxWorkspaceHooks.js";
import { errorKind, plural, splitCommitMessage, sumChanges, titleFromBranch } from "./nxWorkspaceModel.js";

// Commit, push and pull request all follow one path: fill in (if needed),
// confirm what will happen, run it on the PC with `confirm: true`, then show
// the real output and re-read the workspace.

const LOST = "The connection to your PC dropped before an answer came back, so it isn't clear whether this went through. Refresh the workspace to check.";

function copyFor(action, mode) {
  if (action === "commit") return { title: "Commit changes", running: "Committing", ok: "Committed", fail: "Commit failed" };
  if (action === "create_pr") return { title: "Create pull request", running: "Creating pull request", ok: "Pull request created", fail: "Pull request failed" };
  return mode === "publish"
    ? { title: "Publish branch", running: "Publishing", ok: "Branch published", fail: "Publish failed" }
    : { title: "Push commits", running: "Pushing", ok: "Pushed", fail: "Push failed" };
}

/** What the confirm step describes, frozen when the action starts so a refresh cannot rewrite it mid-run. */
function viewOf(flow, data, plan) {
  if (flow.frozen) return flow.frozen;
  const files = plan.commit?.files || [];
  return {
    files, untracked: (data.changes || []).length - files.length,
    mode: flow.mode || plan.push?.mode, ahead: plan.push?.ahead || 0,
  };
}

export function useGitFlow({ sessionId, data, plan, refresh }) {
  const [flow, setFlow] = useState(null);

  const start = useCallback(action => {
    if (action === "commit") setFlow({ action, step: "form", message: "" });
    else if (action === "push") setFlow({ action, step: "confirm", mode: plan.push?.mode });
    else {
      const recent = splitCommitMessage(recallCommit(sessionId));
      setFlow({ action, step: "form", title: recent.title || titleFromBranch(data?.branch), body: recent.body });
    }
  }, [sessionId, data?.branch, plan.push?.mode]);

  const patch = useCallback(update => setFlow(current => (current ? { ...current, ...update } : current)), []);
  const close = useCallback(() => setFlow(null), []);

  // The state can change under an open form (the agent commits, the tree is
  // cleaned). An action that is no longer possible closes itself.
  const possible = flow ? Boolean({ commit: plan.commit, push: plan.push, create_pr: plan.pr }[flow.action]) : true;
  useEffect(() => {
    if (flow && !possible && (flow.step === "form" || flow.step === "confirm")) setFlow(null);
  }, [flow, possible]);

  const submit = useCallback(async () => {
    if (!flow || flow.step === "running") return;
    const { action } = flow;
    const payload = { id: sessionId, action, confirm: true };
    if (action === "commit") payload.message = flow.message.trim();
    if (action === "create_pr") Object.assign(payload, { title: flow.title.trim(), body: flow.body.trim() });
    patch({ step: "running", frozen: viewOf(flow, data, plan) });
    try {
      const result = await callNx("connected_session_git_action_command", payload);
      const ok = result?.ok !== false;
      if (ok && action === "commit") rememberCommit(sessionId, payload.message);
      patch({ step: "done", result: { ok, output: String(result?.output || ""), url: result?.url || "" } });
    } catch (error) {
      const offline = errorKind(error) === "offline";
      patch({ step: "done", result: { ok: false, output: String(error?.data?.output || error?.data?.data?.output || ""), error: offline ? LOST : error?.message || "The action failed." } });
    } finally {
      void refresh();
    }
  }, [flow, data, plan, sessionId, patch, refresh]);

  return { flow, start, patch, close, submit };
}

function FileList({ files }) {
  return (
    <ul className="nx-ws-flist nx-scroll" aria-label="Files that will be committed">
      {files.map(change => (
        <li key={change.path}>
          <StatusBadge change={change} />
          <FilePath path={change.path} />
          <Counts additions={change.additions} deletions={change.deletions} />
        </li>
      ))}
    </ul>
  );
}

function Field({ label, children }) {
  return <label className="nx-ws-field"><span>{label}</span>{children}</label>;
}

const repoName = data => (data.repo?.github ? `${data.repo.github.owner}/${data.repo.github.name}` : "GitHub");

function Form({ flow, data, view, patch, first }) {
  const advance = event => {
    if (!((event.ctrlKey || event.metaKey) && event.key === "Enter")) return;
    event.preventDefault();
    if ((flow.action === "commit" ? flow.message : flow.title).trim()) patch({ step: "confirm" });
  };
  if (flow.action === "commit") {
    const totals = sumChanges(view.files);
    return (
      <>
        <Field label="Commit message">
          <textarea ref={first} rows={3} value={flow.message} placeholder="Describe what changed" maxLength={5000}
            onChange={event => patch({ message: event.target.value })} onKeyDown={advance} />
        </Field>
        <p className="nx-ws-summary">
          {plural(view.files.length, "file")} <Counts additions={totals.additions} deletions={totals.deletions} /> will be committed to <code>{data.branch || "HEAD"}</code>
        </p>
      </>
    );
  }
  return (
    <>
      <Field label="Title">
        <input ref={first} type="text" className="nx-input" value={flow.title} maxLength={500} placeholder="Pull request title"
          onChange={event => patch({ title: event.target.value })} onKeyDown={advance} />
      </Field>
      <Field label="Description">
        <textarea rows={4} value={flow.body} placeholder="What does this change, and why? (optional)"
          onChange={event => patch({ body: event.target.value })} onKeyDown={advance} />
      </Field>
      <p className="nx-ws-summary">From <code>{data.branch}</code> on {repoName(data)}</p>
    </>
  );
}

function Confirm({ flow, data, view }) {
  if (flow.action === "commit") {
    return (
      <>
        <blockquote className="nx-ws-quote">{flow.message.trim()}</blockquote>
        <p className="nx-ws-summary">Commits {plural(view.files.length, "file")} to <code>{data.branch || "HEAD"}</code>:</p>
        <FileList files={view.files} />
        {view.untracked > 0 ? <p className="nx-ws-fine">{plural(view.untracked, "untracked file")} won't be included.</p> : null}
      </>
    );
  }
  if (flow.action === "push") {
    return view.mode === "publish" ? (
      <p className="nx-ws-summary">Publishes <code>{data.branch}</code> to its remote and sets it as the upstream branch.</p>
    ) : (
      <p className="nx-ws-summary">Pushes {plural(view.ahead, "commit")} from <code>{data.branch}</code> to <code>{data.upstream}</code>.</p>
    );
  }
  return (
    <>
      <p className="nx-ws-quote is-title">{flow.title.trim()}</p>
      {flow.body.trim() ? <p className="nx-ws-quote is-body">{flow.body.trim()}</p> : null}
      <p className="nx-ws-summary">Opens a pull request from <code>{data.branch}</code> on {repoName(data)}, into the repository's default branch.</p>
    </>
  );
}

function Result({ flow, onClose, onBack, hasForm }) {
  const { result } = flow;
  const words = copyFor(flow.action, flow.frozen?.mode);
  return (
    <>
      <p className={`nx-ws-flowstatus is-${result.ok ? "ok" : "fail"}`}>
        <Icon as={result.ok ? CircleCheck : CircleX} size={15} /><strong>{result.ok ? words.ok : words.fail}</strong>
      </p>
      {result.error ? <p className="nx-ws-fine is-red">{result.error}</p> : null}
      {result.output ? <pre className={`nx-pre nx-ws-output${result.ok ? "" : " is-error"}`} tabIndex={0}>{result.output}</pre> : null}
      {!result.ok && !result.output && !result.error ? <p className="nx-ws-fine is-red">The action failed and produced no output.</p> : null}
      {result.url ? <a className="nx-ws-outlink" href={result.url} target="_blank" rel="noreferrer noopener">View pull request<Icon as={ExternalLink} size={13} /></a> : null}
      <div className="nx-ws-flowactions">
        {!result.ok && hasForm ? <Button size="sm" variant="outline" onClick={onBack}>Edit and retry</Button> : null}
        <Button size="sm" variant={result.ok ? "primary" : "outline"} onClick={onClose}>Close</Button>
      </div>
    </>
  );
}

/** The step-by-step card. It replaces the action buttons while an action is in progress. */
function FlowCard({ flows, data, plan }) {
  const { flow, patch, close, submit } = flows;
  const view = viewOf(flow, data, plan);
  const words = copyFor(flow.action, view.mode);
  const hasForm = flow.action !== "push";
  const first = useRef(null);
  const card = useRef(null);
  const running = flow.step === "running";
  const valid = flow.action === "commit" ? Boolean(flow.message?.trim()) : flow.action === "create_pr" ? Boolean(flow.title?.trim()) : true;

  useEffect(() => {
    if (flow.step === "form") first.current?.focus();
    else if (flow.step !== "running") card.current?.focus();
  }, [flow.step]);

  const onKeyDown = event => {
    if (event.key === "Escape" && !running) { event.stopPropagation(); close(); }
  };

  const confirmLabel = flow.action === "commit"
    ? `Commit ${plural(view.files.length, "file")}`
    : flow.action === "push"
      ? (view.mode === "publish" ? "Publish branch" : `Push ${plural(view.ahead, "commit")}`)
      : "Create pull request";

  return (
    <div ref={card} className="nx-ws-flow" role="group" aria-label={words.title} tabIndex={-1} onKeyDown={onKeyDown}>
      <header className="nx-ws-flowhead">
        <strong>{flow.step === "confirm" || running ? `Confirm: ${words.title.toLowerCase()}` : words.title}</strong>
        {hasForm && flow.step === "form" ? <span className="nx-ws-step">Step 1 of 2</span> : null}
        {hasForm && (flow.step === "confirm" || running) ? <span className="nx-ws-step">Step 2 of 2</span> : null}
      </header>

      {flow.step === "form" ? (
        <>
          <Form flow={flow} data={data} view={view} patch={patch} first={first} />
          <div className="nx-ws-flowactions">
            <Button size="sm" onClick={close}>Cancel</Button>
            <Button size="sm" variant="primary" disabled={!valid} onClick={() => patch({ step: "confirm" })}>Review</Button>
          </div>
        </>
      ) : null}

      {flow.step === "confirm" || running ? (
        <>
          <Confirm flow={flow} data={data} view={view} />
          <div className="nx-ws-flowactions">
            <Button size="sm" disabled={running} onClick={() => (hasForm ? patch({ step: "form" }) : close())}>{hasForm ? "Back" : "Cancel"}</Button>
            <Button size="sm" variant="primary" disabled={running} onClick={submit} aria-busy={running || undefined}>
              {running ? <><Spinner size={12} />{words.running}</> : confirmLabel}
            </Button>
          </div>
        </>
      ) : null}

      {flow.step === "done" ? (
        <Result flow={flow} hasForm={hasForm} onClose={close} onBack={() => patch({ step: "form", result: null, frozen: null })} />
      ) : null}
    </div>
  );
}

/** Commit and Push buttons, only for what is possible right now. Nothing at all when nothing is. */
export function WorkspaceFooter({ flows, data, plan }) {
  if (flows.flow) return <footer className="nx-ws-foot"><FlowCard flows={flows} data={data} plan={plan} /></footer>;

  const items = [];
  if (plan.commit) items.push({ key: "commit", icon: GitCommitHorizontal, label: `Commit ${plural(plan.commit.files.length, "file")}` });
  if (plan.push) {
    items.push(plan.push.mode === "publish"
      ? { key: "push", icon: Upload, label: "Publish branch" }
      : { key: "push", icon: ArrowUp, label: `Push ${plural(plan.push.ahead, "commit")}` });
  }
  if (!items.length && !plan.diverged) return null;
  return (
    <footer className="nx-ws-foot">
      {plan.diverged ? (
        <p className="nx-ws-hint is-warn">
          <Icon as={TriangleAlert} size={14} />
          <span><code>{data.branch}</code> and <code>{data.upstream}</code> have both moved ({data.ahead} ahead, {data.behind} behind). Pull on your PC before pushing.</span>
        </p>
      ) : null}
      {items.length ? (
        <div className="nx-ws-actions">
          {items.map((item, index) => (
            <Button key={item.key} variant={index === 0 ? "primary" : "outline"} icon={item.icon} onClick={() => flows.start(item.key)}>{item.label}</Button>
          ))}
        </div>
      ) : null}
    </footer>
  );
}
