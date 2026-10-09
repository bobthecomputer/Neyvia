import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDown, ArrowUp, ChevronRight, CircleCheck, CircleDashed, CircleX, ExternalLink, FolderGit2, FolderOpen, FolderX, GitBranch,
  GitMerge, GitPullRequest, GitPullRequestClosed, GitPullRequestDraft, Layers, RefreshCw, TriangleAlert, WifiOff,
} from "lucide-react";

import "./nxWorkspace.css";
import { NxWorkspaceDiff } from "./NxWorkspaceDiff.jsx";
import { WorkspaceFooter, useGitFlow } from "./NxWorkspaceActions.jsx";
import { CopyCommand, Counts, FilePath, MiddlePath, StateNote, StatusBadge } from "./NxWorkspaceBits.jsx";
import { ProviderMark } from "./ProviderMark.jsx";
import { Button, Icon, IconButton, Spinner, ago, useTick } from "./nxPrimitives.jsx";
import { useNx } from "./nxStore.js";
import { useWorkspace } from "./nxWorkspaceHooks.js";
import { baseName, ghReady, githubLinks, isCommittable, isDefaultBranch, planActions, plural, sumChanges } from "./nxWorkspaceModel.js";

function remoteHost(url) {
  const match = /^[\w.-]+@([^:]+):/.exec(url || "");
  if (match) return match[1];
  try { return new URL(url).host; } catch { return ""; }
}

/* ---------- states ---------- */

function Skeleton({ cwd }) {
  return (
    <div className="nx-ws-scroll nx-scroll" role="status" aria-label="Loading workspace" aria-busy="true">
      <section className="nx-ws-section nx-ws-repo">
        <div className="nx-ws-repohead"><span className="nx-ws-skel is-round" /><span className="nx-ws-skel" style={{ width: "46%" }} /></div>
        {cwd ? <ul className="nx-ws-rows"><li><Icon as={FolderOpen} size={14} /><MiddlePath path={cwd} /></li></ul> : <span className="nx-ws-skel" style={{ width: "72%" }} />}
        <span className="nx-ws-skel" style={{ width: "58%" }} />
      </section>
      <section className="nx-ws-section"><span className="nx-ws-skel is-card" /></section>
      <section className="nx-ws-section">
        {[64, 82, 48, 72].map((width, index) => <span key={index} className="nx-ws-skel is-row" style={{ width: `${width}%` }} />)}
      </section>
    </div>
  );
}

function Unavailable({ ws, host }) {
  const offline = ws.error?.kind === "offline";
  return (
    <div className="nx-ws-scroll nx-scroll">
      <StateNote icon={offline ? WifiOff : TriangleAlert} tone={offline ? "" : "red"}
        title={offline ? "Can't reach your PC" : "The workspace couldn't be read"}
        action={<Button size="sm" variant="outline" onClick={ws.refresh}>{ws.busy ? <><Spinner size={12} />Trying</> : "Try again"}</Button>}>
        {offline ? `The workspace is read from ${host || "the PC that runs this chat"}, which isn't answering. Check that it is on and Neyvia is running.` : ws.error?.message}
      </StateNote>
    </div>
  );
}

function NoRepo({ data, host }) {
  if (!data.cwd) {
    return (
      <div className="nx-ws-scroll nx-scroll">
        <StateNote icon={FolderX} title="No folder for this chat">
          This chat isn't tied to a folder, so there is no repository, branch or changed files to show. Start a chat in a project folder to see its workspace.
        </StateNote>
      </div>
    );
  }
  const where = <p className="nx-ws-statepath"><FolderOpen size={14} aria-hidden="true" /><MiddlePath path={data.cwd} /></p>;
  if (!data.exists) {
    return (
      <div className="nx-ws-scroll nx-scroll">
        <StateNote icon={FolderX} title="Folder not found">{`It isn't on ${host || "this PC"} anymore. It may have been moved or deleted.`}</StateNote>
        {where}
      </div>
    );
  }
  return (
    <div className="nx-ws-scroll nx-scroll">
      <StateNote icon={data.gitError ? TriangleAlert : FolderGit2} tone={data.gitError ? "red" : ""}
        title={data.gitError ? "Git can't read this folder" : "Not a git repository"}>
        {data.gitError || "This folder isn't tracked by git, so there is no branch, changes or pull request to show."}
      </StateNote>
      {where}
      {!data.gitError ? (
        <div className="nx-ws-hintblock">
          <p>To start tracking it, run this in that folder:</p>
          <CopyCommand text="git init" />
        </div>
      ) : null}
    </div>
  );
}

/* ---------- repository ---------- */

function WorktreeRow({ data }) {
  const [open, setOpen] = useState(false);
  const trees = data.worktrees || [];
  const main = trees[0];
  const current = trees.find(tree => tree.current);
  const linked = Boolean(current && main && current !== main);
  if (!linked && trees.length < 2) return null;
  const label = linked ? `Linked worktree of ${baseName(main.path)}` : `${plural(trees.length - 1, "other worktree")}`;
  return (
    <li className="nx-ws-wt">
      <Icon as={Layers} size={14} />
      <div>
        <button type="button" className="nx-ws-wthead" aria-expanded={open} onClick={() => setOpen(value => !value)}>
          <span>{label}</span><Icon as={ChevronRight} size={12} className="nx-ws-caret" />
        </button>
        {open ? (
          <ul className="nx-ws-wtlist">
            {trees.map(tree => (
              <li key={tree.path} className={tree.current ? "is-current" : ""}>
                <span className="nx-ws-wtbranch">{tree.branch || "detached"}{tree.current ? <em>this chat</em> : null}</span>
                <MiddlePath path={tree.path} />
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </li>
  );
}

function BranchRow({ data, links }) {
  const detached = data.detached || !data.branch;
  const tracked = Boolean(data.upstream);
  const counted = tracked && Number.isFinite(data.ahead);
  return (
    <li>
      <Icon as={GitBranch} size={14} />
      <div className="nx-ws-branch">
        <div className="nx-ws-branchline">
          {detached ? <span className="nx-ws-detached" title="HEAD is not on a branch">Detached HEAD</span>
            : links.branch && tracked
              ? <a className="nx-ws-branchname" href={links.branch} target="_blank" rel="noreferrer noopener" title={`Open ${data.branch} on GitHub`}>{data.branch}</a>
              : <span className="nx-ws-branchname" title={data.branch}>{data.branch}</span>}
          {counted ? (
            <span className="nx-ws-ab" title={`${plural(data.ahead, "commit")} ahead of ${data.upstream}, ${data.behind || 0} behind`}>
              <span className={data.ahead > 0 ? "is-up" : ""}><Icon as={ArrowUp} size={12} />{data.ahead}</span>
              <span className={data.behind > 0 ? "is-down" : ""}><Icon as={ArrowDown} size={12} />{data.behind || 0}</span>
            </span>
          ) : null}
        </div>
        {!detached ? <span className="nx-ws-sub" title={data.upstream || undefined}>{tracked ? `Tracks ${data.upstream}` : "No upstream branch"}</span> : null}
      </div>
    </li>
  );
}

export function RepoSection({ data }) {
  const { repo } = data;
  const { github } = repo;
  const links = githubLinks(github, data.branch);
  return (
    <section className="nx-ws-section nx-ws-repo" aria-label="Repository">
      <div className="nx-ws-repohead">
        {github ? <ProviderMark id="github" size={18} /> : <Icon as={FolderGit2} size={18} />}
        {github ? (
          <a className="nx-ws-reponame" href={github.url} target="_blank" rel="noreferrer noopener" title={`Open ${github.owner}/${github.name} on GitHub`}>
            <span className="nx-ws-owner">{github.owner}/</span><strong>{github.name}</strong><Icon as={ExternalLink} size={12} />
          </a>
        ) : <strong className="nx-ws-reponame" title={repo.root}>{repo.name}</strong>}
        {!github && repo.remoteUrl ? <span className="nx-ws-remote" title={repo.remoteUrl}>{remoteHost(repo.remoteUrl)}</span> : null}
        {!repo.remoteUrl ? <span className="nx-tag" title="This repository has no remote">Local only</span> : null}
      </div>
      <ul className="nx-ws-rows">
        <li title={data.cwd}><Icon as={FolderOpen} size={14} /><MiddlePath path={data.cwd} /></li>
        <BranchRow data={data} links={links} />
        <WorktreeRow data={data} />
      </ul>
    </section>
  );
}

/* ---------- pull request ---------- */

const PR_STATES = {
  open: { label: "Open", tone: "green", icon: GitPullRequest },
  draft: { label: "Draft", tone: "muted", icon: GitPullRequestDraft },
  merged: { label: "Merged", tone: "accent", icon: GitMerge },
  closed: { label: "Closed", tone: "red", icon: GitPullRequestClosed },
};
const CHECKS = {
  passing: { label: "All checks passed", icon: CircleCheck },
  failing: { label: "Some checks failed", icon: CircleX },
  pending: { label: "Checks are running", icon: CircleDashed },
};

function PullRequestCard({ pr }) {
  const state = PR_STATES[pr.isDraft ? "draft" : String(pr.state || "").toLowerCase()] || PR_STATES.open;
  const live = state.label === "Open" || state.label === "Draft";
  const checks = live ? CHECKS[pr.checks] : null;
  return (
    <article className="nx-ws-pr">
      <div className="nx-ws-prtop">
        <Icon as={state.icon} size={16} className={`nx-ws-pricon is-${state.tone}`} />
        <span className="nx-ws-prnum">#{pr.number}</span>
        <span className={`nx-ws-prstate is-${state.tone}`}>{state.label}</span>
        <span className="nx-ws-spacer" />
        <a className="nx-iconbtn nx-iconbtn-sm" href={pr.url} target="_blank" rel="noreferrer noopener" aria-label={`Open pull request #${pr.number} on GitHub`} title="Open on GitHub">
          <Icon as={ExternalLink} size={14} />
        </a>
      </div>
      <a className="nx-ws-prtitle" href={pr.url} target="_blank" rel="noreferrer noopener">{pr.title}</a>
      {checks ? (
        <a className={`nx-ws-checks is-${pr.checks}`} href={`${pr.url}/checks`} target="_blank" rel="noreferrer noopener">
          {pr.checks === "pending" ? <Spinner size={12} /> : <Icon as={checks.icon} size={14} />}
          <span>{checks.label}</span><Icon as={ChevronRight} size={12} className="nx-ws-caret" />
        </a>
      ) : null}
    </article>
  );
}

function GhNote({ data, links }) {
  const { gh } = data;
  const slow = /did not answer/i.test(gh?.reason || "");
  const missing = gh && !gh.installed;
  return (
    <div className="nx-ws-note">
      <Icon as={GitPullRequest} size={16} />
      <div>
        <strong>{slow ? "The GitHub CLI didn't answer" : missing ? "Install the GitHub CLI on your PC" : "Sign in to GitHub CLI on your PC"}</strong>
        {slow ? <p>{gh.reason} Refresh to try again.</p> : (
          <>
            <p>{missing ? "Install it from cli.github.com, then sign in:" : "Then pull requests and checks show up here, and you can create them from this panel:"}</p>
            <CopyCommand text="gh auth login" />
          </>
        )}
        {links.compare && data.upstream && !isDefaultBranch(data.branch) ? (
          <a className="nx-ws-outlink" href={links.compare} target="_blank" rel="noreferrer noopener">Or open a pull request on github.com<Icon as={ExternalLink} size={13} /></a>
        ) : null}
      </div>
    </div>
  );
}

function PullRequestSection({ data, plan, onCreate }) {
  const { github } = data.repo;
  if (!github) return null;
  const pr = data.pullRequest;
  let body = null;
  if (!ghReady(data.gh)) body = <GhNote data={data} links={githubLinks(github, data.branch)} />;
  else if (pr) body = <PullRequestCard pr={pr} />;
  else if (plan.pr) {
    body = (
      <div className="nx-ws-pr is-empty">
        <p>No pull request for <code>{data.branch}</code> yet.</p>
        {onCreate ? <Button size="sm" variant={plan.commit || plan.push ? "outline" : "primary"} icon={GitPullRequest} onClick={onCreate}>Create pull request</Button> : null}
      </div>
    );
  } else if (plan.prBlocked) {
    body = (
      <p className="nx-ws-fine">
        {plan.prBlocked === "diverged"
          ? "No pull request yet. Bring the branch back in line with its upstream first."
          : <>No pull request yet. Push <code>{data.branch}</code> to GitHub first, then you can create one here.</>}
      </p>
    );
  }
  if (!body && !data.pullRequestError) return null;
  return (
    <section className="nx-ws-section" aria-label="Pull request">
      <div className="nx-ws-h"><h3>Pull request</h3></div>
      {body}
      {data.pullRequestError && !pr ? <p className="nx-ws-fine is-warn">Couldn't read the pull request: {data.pullRequestError}</p> : null}
    </section>
  );
}

/* ---------- changes ---------- */

export function ChangesSection({ data, plan, onOpen }) {
  const changes = data.changes || [];
  const totals = useMemo(() => sumChanges(changes), [changes]);
  const untracked = changes.length - changes.filter(isCommittable).length;
  return (
    <section className="nx-ws-section nx-ws-changes" aria-label="Changes">
      <div className="nx-ws-h">
        <h3>Changes</h3>
        {changes.length ? <span className="nx-ws-count">{changes.length}</span> : null}
        <span className="nx-ws-spacer" />
        {changes.length ? <Counts additions={totals.additions} deletions={totals.deletions} /> : null}
      </div>
      {!changes.length ? (
        <p className="nx-ws-clean"><Icon as={CircleCheck} size={15} /><span>Working tree clean</span><em>Nothing to commit</em></p>
      ) : (
        <ul className="nx-ws-files">
          {changes.map(change => (
            <li key={change.path}>
              <button type="button" className="nx-ws-file" data-path={change.path} onClick={() => onOpen(change.path)}
                title={change.oldPath ? `${change.path}\nRenamed from ${change.oldPath}` : undefined} aria-label={`Show changes in ${change.path}`}>
                <StatusBadge change={change} />
                <FilePath path={change.path} />
                <Counts additions={change.additions} deletions={change.deletions} />
                <Icon as={ChevronRight} size={13} className="nx-ws-caret" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {data.changesTruncated ? <p className="nx-ws-fine is-warn">Showing the first {changes.length} changed files. The rest are on your PC.</p> : null}
      {untracked > 0 && plan.commit ? <p className="nx-ws-fine">{plural(untracked, "untracked file")} won't be included in a commit from here.</p> : null}
      {untracked > 0 && !plan.commit ? <p className="nx-ws-fine">Untracked files aren't committed from here. Stage them with <code>git add</code> on your PC to commit them.</p> : null}
    </section>
  );
}

/* ---------- panel ---------- */

function Toolbar({ ws, host }) {
  useTick(Boolean(ws.at), 15000);
  const age = ws.at ? ago(new Date(ws.at).toISOString()) : "";
  return (
    <div className="nx-ws-bar">
      <span className="nx-ws-bartext" aria-live="polite">
        {ws.at ? `Updated ${age === "now" ? "just now" : `${age} ago`}` : ws.error ? (ws.error.kind === "offline" ? "PC not reachable" : "Couldn't read the workspace") : "Reading the workspace"}{host ? <> <i>on</i> {host}</> : null}
      </span>
      <IconButton size="sm" icon={RefreshCw} label="Refresh workspace" className={ws.busy ? "is-spinning" : ""} aria-busy={ws.busy || undefined} onClick={ws.refresh} />
    </div>
  );
}

function StaleBanner({ ws, host }) {
  if (!ws.error || !ws.data) return null;
  const offline = ws.error.kind === "offline";
  return (
    <p className="nx-ws-banner is-warn" role="status">
      <Icon as={offline ? WifiOff : TriangleAlert} size={14} />
      <span>{offline ? `Can't reach ${host || "your PC"}. This is the last state it reported.` : `Couldn't refresh: ${ws.error.message}`}</span>
      <button type="button" onClick={ws.refresh}>Retry</button>
    </p>
  );
}

/** Which folder, repository, branch and worktree this chat uses, what changed, and what GitHub says about it. */
export function NxWorkspacePanel({ session }) {
  const ws = useWorkspace(session.id);
  const { data } = ws;
  const hostName = useNx(state => state.host?.deviceName);
  const host = session.host_device_name || hostName || "";
  const plan = useMemo(() => planActions(data), [data]);
  const flows = useGitFlow({ sessionId: session.id, data, plan, refresh: ws.refresh });
  const [diffPath, setDiffPath] = useState(null);
  const list = useRef(null);
  const saved = useRef(0);
  const opened = useRef("");

  const changes = data?.changes || [];
  const diffIndex = diffPath ? changes.findIndex(change => change.path === diffPath) : -1;

  // A refresh can remove the open file (it was committed or reverted). Go back to the list.
  useEffect(() => { if (diffPath && data && diffIndex < 0) setDiffPath(null); }, [diffPath, data, diffIndex]);

  const open = useCallback(path => { saved.current = list.current?.scrollTop || 0; opened.current = path; setDiffPath(path); }, []);
  const back = useCallback(() => setDiffPath(null), []);
  const step = useCallback(delta => { const next = changes[diffIndex + delta]; if (next) setDiffPath(next.path); }, [changes, diffIndex]);
  useLayoutEffect(() => {
    if (diffPath || !list.current) return;
    list.current.scrollTop = saved.current;
    if (opened.current) list.current.querySelector(`[data-path="${CSS.escape(opened.current)}"]`)?.focus();
  }, [diffPath]);

  const onKeyDown = event => {
    if (event.key === "Escape" && diffIndex >= 0 && !flows.flow) { event.stopPropagation(); back(); }
  };

  let content;
  if (ws.status === "loading") content = <Skeleton cwd={session.cwd} />;
  else if (ws.status === "error") content = <Unavailable ws={ws} host={host} />;
  else if (!data.repo) content = <NoRepo data={data} host={host} />;
  else if (diffIndex >= 0) {
    content = <NxWorkspaceDiff sessionId={session.id} change={changes[diffIndex]} index={diffIndex} total={changes.length}
      version={ws.version} onBack={back} onStep={step} />;
  } else {
    content = (
      <div className="nx-ws-scroll nx-scroll" ref={list}>
        <RepoSection data={data} />
        <PullRequestSection data={data} plan={plan} onCreate={flows.flow ? null : () => flows.start("create_pr")} />
        <ChangesSection data={data} plan={plan} onOpen={open} />
      </div>
    );
  }

  return (
    <div className="nx-ws" onKeyDown={onKeyDown}>
      <Toolbar ws={ws} host={host} />
      <StaleBanner ws={ws} host={host} />
      {content}
      {data?.repo ? <WorkspaceFooter flows={flows} data={data} plan={plan} /> : null}
    </div>
  );
}
