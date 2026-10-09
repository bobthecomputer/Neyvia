import { Suspense, lazy, memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Copy, FileText, Folder, FolderOpen, GitCompare, RotateCcw, Save, TriangleAlert } from "lucide-react";

import { filesCall, formatSize, nameOf, parentOf, rawUrl } from "./nxDocsApi.js";
import { indentUnit, panesCall } from "./nxPanesApi.js";
import { Button, Icon, Segmented, Spinner } from "./nxPrimitives.jsx";
import { os, useOs } from "./nxOsStore.js";
import { parsePatch } from "./nxWorkspaceModel.js";
import { ObserveDom, ObservedImage, PaneRefused, usePaneObservation } from "./NxPaneObserver.jsx";
import { normalizeText } from "./nxPaneObserve.js";
import "./nxWorkspace.css";
import "./nxPanes.css";

// pane.show {kind: "file"}: open any file under Home, the workspace or a project
// folder, edit it and save (refused when the file changed on disk meanwhile),
// and see it against the last git commit, unsaved edits included. A folder
// target lists the folder. Same backend as the Files app's guard.

const NxPdfApp = lazy(() => import("./NxPdfApp.jsx").then(module => ({ default: module.NxPdfApp })));
const SIGNS = { add: "+", del: "−", ctx: "", note: "" };
const GIT_LABEL = { clean: "No changes", M: "Changed", A: "Added", D: "Deleted", R: "Renamed", "??": "Not in git yet", MM: "Changed", AM: "Added" };

export function PaneMessage({ icon = FileText, title, children, action }) {
  return (
    <div className="nx-pane-honest">
      <Icon as={icon} size={22} />
      <strong>{title}</strong>
      {children ? <p>{children}</p> : null}
      {action}
    </div>
  );
}

export const DiffLines = memo(function DiffLines({ patch }) {
  const parsed = useMemo(() => parsePatch(patch), [patch]);
  const rows = [];
  parsed.files.forEach((file, fileIndex) => file.hunks.forEach((hunk, hunkIndex) => {
    rows.push(
      <div key={`h${fileIndex}-${hunkIndex}`} className="nx-dl is-hunk">
        <span className="nx-dl-nums" aria-hidden="true" />
        <span className="nx-dl-code">{hunk.header}</span>
      </div>,
    );
    hunk.lines.forEach((line, lineIndex) => rows.push(
      <div key={`l${fileIndex}-${hunkIndex}-${lineIndex}`} className={`nx-dl is-${line.t}`}>
        <span className="nx-dl-nums" aria-hidden="true"><i>{line.o ?? ""}</i><i>{line.n ?? ""}</i><b>{SIGNS[line.t]}</b></span>
        <span className="nx-dl-code">{line.text}</span>
      </div>,
    ));
  }));
  return (
    <div className="nx-diff nx-scroll nx-fp-diff" tabIndex={0} aria-label="Changes">
      <div className="nx-diff-body">{rows}</div>
    </div>
  );
});

function FolderList({ path }) {
  const [state, setState] = useState({ status: "loading", entries: [] });
  const observation = usePaneObservation();
  useEffect(() => {
    if (state.status !== "ready") return;
    // What the folder pane shows: its path and the visible entries, in order.
    const shown = state.entries.filter(entry => !entry.hidden).map(entry => `${entry.kind === "folder" ? "d" : "f"} ${entry.name}`);
    void observation.report({ runtimeId: `folder:${path}`.slice(0, 128), content: [path, ...shown].join("\n") });
  }, [observation, state, path]);
  useEffect(() => {
    let live = true;
    filesCall("list", { path })
      .then(data => { if (live) setState({ status: "ready", entries: data.entries || [] }); })
      .catch(error => { if (live) setState({ status: "error", error: error.message, entries: [] }); });
    return () => { live = false; };
  }, [path]);
  if (state.status === "loading") return <div className="nx-stage-loading"><Spinner size={16} /></div>;
  if (state.status === "error") return <PaneMessage icon={TriangleAlert} title="This folder can't be opened"><PaneRefused reason={state.error} />{state.error}</PaneMessage>;
  return (
    <div className="nx-fp-folder nx-scroll">
      <div className="nx-fp-bar">
        <Icon as={FolderOpen} size={15} />
        <span className="nx-fp-name" title={path}>{nameOf(path) || path}</span>
        <span className="nx-fp-meta">{state.entries.length} items</span>
        <span className="nx-head-spacer" />
        {parentOf(path) !== path ? <Button size="sm" onClick={() => os.showPane("file", parentOf(path))}>Up</Button> : null}
        <Button size="sm" icon={FolderOpen} onClick={() => os.openApp("files", "documents", path)}>Open in Files</Button>
      </div>
      <ul className="nx-fp-entries">
        {state.entries.filter(entry => !entry.hidden).map(entry => (
          <li key={entry.path}>
            <button type="button" onClick={() => os.showPane(entry.kind === "folder" ? "file" : entry.openWith === "image" || entry.openWith === "pdf" ? "artifact" : "file", entry.path)}>
              <Icon as={entry.kind === "folder" ? Folder : FileText} size={15} />
              <span>{entry.name}</span>
              <small>{entry.kind === "folder" ? "" : formatSize(entry.size)}</small>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

let editorSeq = 0;

function Editor({ value, onChange, onSave, unit, readOnly }) {
  const area = useRef(null);
  const gutter = useRef(null);
  const observation = usePaneObservation();
  const runtime = useMemo(() => `file-editor:${Date.now().toString(36)}-${(editorSeq += 1)}`, []);
  // The textarea must display the loaded text. React keeps a controlled textarea in sync, but some
  // embedded engines leave a freshly mounted one empty; put the text in place where that happened.
  useLayoutEffect(() => {
    const element = area.current;
    if (element && element.value !== value) element.value = value;
  }, [value]);
  // The observation is the text the editor really displays (its textarea), LF and no BOM, reported
  // once the textarea shows the loaded text (some engines fill it a moment after mount; after ~5 s
  // whatever it shows is reported as is). When the editor leaves (Changes view), it isn't shown any more.
  useEffect(() => {
    let tries = 0;
    let timer = 0;
    const read = () => {
      const shown = area.current ? normalizeText(area.current.value) : null;
      if (shown === null || (shown !== normalizeText(value) && tries < 25)) { tries += 1; timer = setTimeout(read, 200); return; }
      void observation.report({ runtimeId: runtime, content: shown, allowEmpty: true });
    };
    read(); // React's committed textarea is already the content witness.
    return () => clearTimeout(timer);
  }, [observation, runtime, value]);
  useEffect(() => () => observation.withdraw(), [observation]);
  const lines = useMemo(() => value.split("\n").length, [value]);
  const numbers = useMemo(() => Array.from({ length: lines }, (_, index) => index + 1).join("\n"), [lines]);
  const onKeyDown = event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); onSave(); return; }
    if (event.key === "Tab" && !event.ctrlKey && !event.altKey && !readOnly) {
      event.preventDefault();
      const element = event.currentTarget;
      const { selectionStart: start, selectionEnd: end } = element;
      const before = value.slice(0, start);
      const lineStart = before.lastIndexOf("\n") + 1;
      if (event.shiftKey) {
        const line = value.slice(lineStart);
        const remove = line.startsWith(unit) ? unit.length : line.startsWith("\t") ? 1 : (/^ +/.exec(line)?.[0].length || 0) && Math.min(unit.length, /^ +/.exec(line)[0].length);
        if (!remove) return;
        onChange(value.slice(0, lineStart) + value.slice(lineStart + remove));
        requestAnimationFrame(() => element.setSelectionRange(Math.max(lineStart, start - remove), Math.max(lineStart, end - remove)));
        return;
      }
      onChange(before + unit + value.slice(end));
      requestAnimationFrame(() => element.setSelectionRange(start + unit.length, start + unit.length));
    }
  };
  return (
    <div className="nx-fp-editor">
      <pre ref={gutter} className="nx-fp-gutter" aria-hidden="true">{numbers}</pre>
      <textarea ref={area} className="nx-fp-text" value={value} spellCheck={false} readOnly={readOnly} aria-label="File text"
        wrap="off" autoCapitalize="off" autoComplete="off" autoCorrect="off"
        onChange={event => onChange(event.target.value)} onKeyDown={onKeyDown}
        onScroll={event => { if (gutter.current) gutter.current.scrollTop = event.currentTarget.scrollTop; }} />
    </div>
  );
}

function TextFile({ file, onReload }) {
  const [text, setText] = useState(file.text);
  const [base, setBase] = useState({ hash: file.hash, text: file.text, git: file.git || {} });
  const [view, setView] = useState("edit");
  const [save, setSave] = useState({ status: "idle" });
  const [conflict, setConflict] = useState(null);
  const [diff, setDiff] = useState({ status: "idle" });
  const [external, setExternal] = useState(false);
  const signal = useOs(state => state.appSignals?.files);
  const dirty = text !== base.text;
  const unit = useMemo(() => indentUnit(file.text), [file.text]);

  const doSave = useCallback(async (overwrite = false) => {
    if (!dirty && !overwrite) return;
    setSave({ status: "saving" });
    try {
      const result = await panesCall("file.write", { path: file.path, text, baseHash: overwrite ? conflict?.currentHash : base.hash, eol: file.eol, bom: file.bom });
      setBase({ hash: result.hash, text, git: result.git || base.git });
      setConflict(null);
      setExternal(false);
      setSave({ status: "saved", at: Date.now() });
    } catch (error) {
      if (error.status === 409) { setConflict(error.data || { error: error.message }); setSave({ status: "idle" }); }
      else setSave({ status: "error", error: error.message });
    }
  }, [base, conflict, dirty, file, text]);

  // An agent or another window changed the file: reload quietly when nothing is unsaved, else say so.
  const check = useCallback(async () => {
    try {
      const fresh = await panesCall("file.read", { path: file.path });
      if (!fresh.hash || fresh.hash === base.hash) return;
      if (text === base.text && fresh.editable) { setText(fresh.text); setBase({ hash: fresh.hash, text: fresh.text, git: fresh.git || {} }); }
      else setExternal(true);
    } catch { /* the next focus checks again */ }
  }, [base, file.path, text]);
  const seen = useRef(signal?.seq || 0);
  useEffect(() => {
    if (!signal || signal.seq === seen.current) return;
    seen.current = signal.seq;
    void check();
  }, [signal, check]);
  useEffect(() => {
    const onFocus = () => void check();
    window.addEventListener("focus", onFocus);
    const timer = setInterval(() => { if (document.visibilityState === "visible") void check(); }, 1500);
    return () => { window.removeEventListener("focus", onFocus); clearInterval(timer); };
  }, [check]);

  useEffect(() => {
    if (view !== "diff") return undefined;
    let live = true;
    setDiff(current => ({ ...current, status: "loading" }));
    const timer = setTimeout(() => {
      panesCall("file.diff", { path: file.path, ...(dirty ? { text } : {}) })
        .then(data => { if (live) setDiff({ status: "ready", ...data }); })
        .catch(error => { if (live) setDiff({ status: "error", error: error.message }); });
    }, 150);
    return () => { live = false; clearTimeout(timer); };
  }, [view, dirty, text, file.path, base.hash]);

  useEffect(() => {
    const warn = event => { if (dirty) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const git = base.git || {};
  const gitLabel = git.repo ? (dirty ? "Unsaved edits" : GIT_LABEL[git.status] || git.status) : "Not in git";
  return (
    <div className="nx-fp">
      <div className="nx-fp-bar">
        <Icon as={FileText} size={15} />
        <span className="nx-fp-name" title={file.path}>{file.name}</span>
        {dirty ? <span className="nx-fp-dirty" title="Unsaved edits" aria-label="Unsaved edits" /> : null}
        <span className={`nx-fp-chip${git.status && git.status !== "clean" ? " is-changed" : ""}`} title={git.repo ? `In ${git.repo}` : "This file is not in a git repository"}>{gitLabel}</span>
        <span className="nx-fp-meta">{file.eol === "crlf" ? "CRLF" : "LF"}</span>
        <span className="nx-head-spacer" />
        <Segmented size="sm" label="View" value={view} onChange={setView}
          options={[{ value: "edit", label: "Edit" }, { value: "diff", label: "Changes" }]} />
        <Button size="sm" icon={RotateCcw} disabled={!dirty} onClick={() => setText(base.text)} title="Undo all unsaved edits">Revert</Button>
        <Button size="sm" variant={dirty ? "primary" : "ghost"} icon={save.status === "saving" ? undefined : Save} disabled={!dirty || save.status === "saving"} onClick={() => void doSave()} title="Save (Ctrl S)">
          {save.status === "saving" ? "Saving…" : "Save"}
        </Button>
      </div>
      {conflict ? (
        <div className="nx-fp-banner is-needs" role="alert">
          <Icon as={TriangleAlert} size={15} />
          <span>{conflict.error || "This file changed on disk since you opened it."} Your edits are still here.</span>
          <Button size="sm" icon={Copy} onClick={() => void navigator.clipboard?.writeText(text)}>Copy mine</Button>
          <Button size="sm" onClick={() => { setConflict(null); onReload(); }}>Load the new version</Button>
          {conflict.currentHash ? <Button size="sm" variant="primary" onClick={() => void doSave(true)}>Save mine over it</Button> : null}
        </div>
      ) : external ? (
        <div className="nx-fp-banner" role="status">
          <Icon as={TriangleAlert} size={15} />
          <span>Someone else changed this file. Saving will ask before replacing their version.</span>
          <Button size="sm" onClick={onReload}>Load their version</Button>
        </div>
      ) : save.status === "error" ? (
        <div className="nx-fp-banner is-warn" role="alert"><Icon as={TriangleAlert} size={15} /><span>Not saved: {save.error}</span></div>
      ) : null}
      {view === "edit" ? (
        <Editor value={text} onChange={setText} onSave={() => void doSave()} unit={unit} readOnly={false} />
      ) : diff.status === "loading" && !diff.patch ? (
        <div className="nx-stage-loading"><Spinner size={16} /></div>
      ) : diff.status === "error" ? (
        <PaneMessage icon={TriangleAlert} title="Changes can't be shown">{diff.error}</PaneMessage>
      ) : !diff.git?.repo ? (
        <PaneMessage icon={GitCompare} title="Not in a git repository">{diff.reason || "There is no last commit to compare with."}</PaneMessage>
      ) : !diff.patch ? (
        <PaneMessage icon={GitCompare} title="No changes">This file is the same as in the last commit.</PaneMessage>
      ) : (
        <>
          <p className="nx-fp-note">Compared with {diff.against}{diff.unsaved ? ", including your unsaved edits" : ""}.</p>
          <DiffLines patch={diff.patch} />
        </>
      )}
      <div className="nx-fp-foot" aria-live="polite">
        {save.status === "saved" ? <span>Saved at {new Date(save.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span> : <span>{formatSize(file.size)}</span>}
        <span className="nx-head-spacer" />
        <span>{text.split("\n").length} lines</span>
      </div>
    </div>
  );
}

export function NxFilePane({ target }) {
  const [file, setFile] = useState({ status: "loading" });
  const [version, setVersion] = useState(0);
  useEffect(() => {
    if (!target) return undefined;
    let live = true;
    setFile({ status: "loading" });
    panesCall("file.read", { path: target })
      .then(data => { if (live) setFile({ status: "ready", ...data }); })
      .catch(error => { if (live) setFile({ status: "error", error: error.message, missing: error.status === 404 }); });
    return () => { live = false; };
  }, [target, version]);

  if (!target) return <PaneMessage title="No file chosen"><PaneRefused reason="No file chosen" />Ask for a file by its path, or open one from Files.</PaneMessage>;
  if (file.status === "loading") return <div className="nx-stage-loading"><Spinner size={16} /></div>;
  if (file.status === "error") {
    return (
      <PaneMessage icon={TriangleAlert} title={file.missing ? "File not found" : "This file can't be opened"}
        action={<Button size="sm" onClick={() => setVersion(value => value + 1)}>Try again</Button>}>
        <PaneRefused reason={file.error} />{file.error}
      </PaneMessage>
    );
  }
  if (file.kind === "folder") return <FolderList path={file.path} />;
  if (file.editable) return <TextFile key={`${file.path}:${version}`} file={file} onReload={() => setVersion(value => value + 1)} />;
  if (file.openWith === "image") return <div className="nx-pane-image"><ObservedImage src={rawUrl(file.path)} alt={file.name} runtime={`image:${file.path}`.slice(0, 128)} /></div>;
  if (file.openWith === "pdf") return <Suspense fallback={<div className="nx-stage-loading"><Spinner size={16} /></div>}><ObserveDom /><NxPdfApp target={file.path} /></Suspense>;
  return (
    <PaneMessage title={file.name} action={<Button size="sm" icon={FolderOpen} onClick={() => os.openApp("files", "documents", parentOf(file.path))}>Show in Files</Button>}>
      <PaneRefused reason={file.reason || "Neyvia can't show this kind of file"} />{file.reason || "Neyvia can't show this kind of file."} {formatSize(file.size)}, last changed {new Date(file.modified * 1000).toLocaleString()}.
    </PaneMessage>
  );
}
