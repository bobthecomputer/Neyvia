import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Clock, Download, Folder, GitBranch, Lock, Search, TriangleAlert } from "lucide-react";

import { ProviderMark } from "./ProviderMark.jsx";
import { callNx } from "./nxApi.js";
import { Button, Icon, Popover, Spinner, ago, useRovingKeys } from "./nxPrimitives.jsx";

function shortPath(path) {
  const parts = String(path || "").split(/[\\/]/).filter(Boolean);
  return parts.length > 3 ? `…\\${parts.slice(-2).join("\\")}` : path;
}

/** Folder chooser for a new chat: recent chat folders, local projects, and GitHub repos. */
export function NxFolderPicker({ value, onChange, recent, placeholder = "Choose a folder", title = placeholder, hint = "Where the agent should work" }) {
  const anchor = useRef(null);
  const listRef = useRef(null);
  const onKeyDown = useRovingKeys(listRef);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [local, setLocal] = useState({ status: "idle", rows: [] });
  const [github, setGithub] = useState({ status: "idle", repos: [], gh: null });
  const [cloning, setCloning] = useState({ repo: "", confirm: "", error: "" });

  useEffect(() => {
    if (!open) return undefined;
    let alive = true;
    const timer = setTimeout(() => {
      setLocal(current => ({ ...current, status: current.rows.length ? "refreshing" : "loading" }));
      callNx("connected_folders_command", { query, recent })
        .then(result => { if (alive) setLocal({ status: "ready", rows: result?.local || [], direct: result?.direct, projectsRoot: result?.projectsRoot }); })
        .catch(error => { if (alive) setLocal({ status: "error", rows: [], error: error?.message }); });
      setGithub(current => ({ ...current, status: current.repos.length ? "refreshing" : "loading" }));
      callNx("connected_github_repos_command", { query })
        .then(result => { if (alive) setGithub({ status: "ready", repos: result?.repos || [], gh: result?.gh || null }); })
        .catch(error => { if (alive) setGithub({ status: "error", repos: [], gh: null, error: error?.message }); });
    }, query ? 220 : 0);
    return () => { alive = false; clearTimeout(timer); };
  }, [open, query, recent]);

  const recentRows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (recent || []).filter(row => !needle || `${row.name} ${row.path}`.toLowerCase().includes(needle)).slice(0, 5);
  }, [recent, query]);

  const choose = folder => { onChange(folder); setOpen(false); setQuery(""); setCloning({ repo: "", confirm: "", error: "" }); };

  const clone = async repo => {
    setCloning({ repo: repo.repo, confirm: "", error: "", busy: true });
    try {
      const result = await callNx("connected_folder_clone_command", { repo: repo.repo, confirm: true });
      choose({ path: result.path, name: repo.repo.split("/")[1], github: repo.repo, branch: repo.defaultBranch || null });
    } catch (error) {
      setCloning({ repo: repo.repo, confirm: "", error: error?.message || "Clone failed." });
    }
  };

  const row = (key, { icon, mark, title, detail, meta, selected, onClick, trailing }) => (
    <div key={key} className={`nx-folder-row${selected ? " is-on" : ""}`}>
      <button type="button" role="option" aria-selected={selected} className="nx-folder-row-main" onClick={onClick}>
        <span className="nx-folder-row-icon">{mark ? <ProviderMark id={mark} size={15} /> : <Icon as={icon} size={15} />}</span>
        <span className="nx-folder-row-text"><strong>{title}</strong>{detail ? <span>{detail}</span> : null}</span>
        {meta ? <span className="nx-folder-row-meta">{meta}</span> : null}
        {selected ? <Icon as={Check} size={14} className="nx-picker-check" /> : null}
      </button>
      {trailing}
    </div>
  );

  return (
    <>
      <button ref={anchor} type="button" className="nx-folder-trigger" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Icon as={Folder} size={15} />
        {value?.path ? (
          <span className="nx-folder-trigger-text">
            <strong>{value.name || shortPath(value.path)}</strong>
            <span title={value.path}>{shortPath(value.path)}</span>
          </span>
        ) : <span className="nx-folder-trigger-text is-placeholder"><strong>{title}</strong><span>{hint}</span></span>}
        {value?.github ? <span className="nx-folder-trigger-chip"><ProviderMark id="github" size={12} />{value.github}</span> : null}
        {value?.branch ? <span className="nx-folder-trigger-chip"><Icon as={GitBranch} size={12} />{value.branch}</span> : null}
        <Icon as={ChevronDown} size={14} className="nx-chip-caret" />
      </button>
      <Popover anchor={anchor} open={open} onClose={() => setOpen(false)} width={460} placement="bottom-start" label="Choose a folder">
        <div className="nx-folder-pop">
          <label className="nx-search is-pop">
            <Icon as={Search} size={14} />
            <input data-autofocus value={query} onChange={event => setQuery(event.target.value)} placeholder="Search folders and repositories" aria-label="Search folders" />
            {local.status === "refreshing" || github.status === "refreshing" ? <Spinner size={11} /> : null}
          </label>
          <div className="nx-folder-lists nx-scroll" role="listbox" ref={listRef} onKeyDown={onKeyDown}>
            {recentRows.length ? <div className="nx-picker-head">Recent</div> : null}
            {recentRows.map(folder => row(`r:${folder.path}`, {
              icon: Clock, title: folder.name, detail: shortPath(folder.path), meta: folder.branch ? <><Icon as={GitBranch} size={11} />{folder.branch}</> : null,
              selected: value?.path === folder.path, onClick: () => choose(folder),
            }))}

            <div className="nx-picker-head">On this PC</div>
            {local.direct ? row(`direct:${local.direct.path}`, {
              icon: Folder, title: "Use this folder", detail: local.direct.path,
              selected: value?.path === local.direct.path, onClick: () => choose(local.direct),
            }) : null}
            {local.status === "loading" ? <div className="nx-folder-loading"><Spinner size={11} /> Looking in your Projects folder…</div> : null}
            {local.status === "error" ? <div className="nx-folder-loading is-error"><Icon as={TriangleAlert} size={13} />{local.error || "Folders couldn't be listed."}</div> : null}
            {local.rows.map(folder => row(`l:${folder.path}`, {
              mark: folder.github ? "github" : null, icon: Folder, title: folder.name,
              detail: folder.github || (folder.isGit ? "Git repository" : "Folder"),
              meta: folder.branch ? <><Icon as={GitBranch} size={11} />{folder.branch}</> : null,
              selected: value?.path === folder.path,
              onClick: () => choose({ path: folder.path, name: folder.name, github: folder.github, branch: folder.branch, isGit: folder.isGit }),
            }))}
            {local.status === "ready" && !local.rows.length && !local.direct ? <p className="nx-folder-empty">No folders{query ? " match" : ` in ${local.projectsRoot || "Projects"}`}.</p> : null}

            <div className="nx-picker-head is-github"><ProviderMark id="github" size={12} /> GitHub</div>
            {github.status === "loading" ? <div className="nx-folder-loading"><Spinner size={11} /> Asking GitHub…</div> : null}
            {github.gh && !github.gh.authenticated ? <p className="nx-folder-empty">{github.gh.reason}</p> : null}
            {github.repos.filter(repo => !repo.localPath || !local.rows.some(folder => folder.path === repo.localPath)).map(repo => row(`g:${repo.repo}`, {
              mark: "github", title: repo.repo, detail: repo.description || (repo.localPath ? shortPath(repo.localPath) : "Not on this PC yet"),
              meta: <>{repo.private ? <Icon as={Lock} size={11} /> : null}{ago(repo.updatedAt)}</>,
              selected: Boolean(repo.localPath) && value?.path === repo.localPath,
              onClick: () => repo.localPath
                ? choose({ path: repo.localPath, name: repo.repo.split("/")[1], github: repo.repo, isGit: true })
                : setCloning({ repo: repo.repo, confirm: repo.repo, error: "" }),
              trailing: cloning.repo === repo.repo && (cloning.confirm || cloning.busy || cloning.error) ? (
                <div className="nx-folder-clone">
                  {cloning.error ? <span className="is-error">{cloning.error}</span> : <span>Clone into {local.projectsRoot || "Projects"}?</span>}
                  <Button size="sm" variant="ghost" onClick={() => setCloning({ repo: "", confirm: "", error: "" })}>Cancel</Button>
                  <Button size="sm" variant="primary" icon={Download} disabled={cloning.busy} onClick={() => void clone(repo)}>{cloning.busy ? "Cloning…" : "Clone"}</Button>
                </div>
              ) : null,
            }))}
          </div>
        </div>
      </Popover>
    </>
  );
}
