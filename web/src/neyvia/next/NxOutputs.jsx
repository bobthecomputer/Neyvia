import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, Copy, ExternalLink, FileDiff, FileText, FolderOpen, Image as ImageIcon, Inbox, Plus, Receipt, RefreshCw, ScanText, ScrollText, TriangleAlert, X } from "lucide-react";

import NeyviaMessageBody from "../NeyviaMessageBody.jsx";
import { DiffLines, PaneMessage } from "./NxFilePane.jsx";
import { formatSize, parentOf, rawUrl } from "./nxDocsApi.js";
import { KIND_LABELS, KIND_ONE, OUTPUT_KINDS, layerForOutput, openOutput, outputsCall, perceptionTarget } from "./nxOutputsApi.js";
import { backendUrl, panesCall } from "./nxPanesApi.js";
import { Button, Icon, IconButton, Spinner, ago, local, useMedia } from "./nxPrimitives.jsx";
import { os, useOs } from "./nxOsStore.js";
import "./nxPanes.css";
import "./nxOutputs.css";

// pane.show {kind: "outputs"} (plan 15 T8): every output an agent or Paul
// published, of every kind, from the durable registry (artifact.list), not
// from whatever chat text happens to be on screen. A row opens its preview
// beside the list; "Open" asks the backend to check the published bytes and
// show the full pane; "See as the agent" opens the perception view.

const NxPdfApp = lazy(() => import("./NxPdfApp.jsx").then(module => ({ default: module.NxPdfApp })));
const PAGE = 30;
const KIND_ICON = { file: FileText, diff: FileDiff, image: ImageIcon, report: ScrollText, receipt: Receipt };

function KindFilter({ value, counts, onChange }) {
  const options = [["", "All"], ...OUTPUT_KINDS.map(kind => [kind, KIND_LABELS[kind]])];
  return (
    <div role="radiogroup" aria-label="Show" className="nx-out-filters">
      {options.map(([kind, label]) => (
        <button key={kind || "all"} type="button" role="radio" aria-checked={value === kind} className={`nx-out-filter${value === kind ? " is-on" : ""}`}
          onClick={() => onChange(kind)}>
          {kind ? <Icon as={KIND_ICON[kind]} size={14} /> : null}
          {label}
          {counts[kind || "all"] != null ? <span className="nx-out-count">{counts[kind || "all"]}</span> : null}
        </button>
      ))}
    </div>
  );
}

function PublishForm({ session, onDone, onCancel }) {
  const [path, setPath] = useState("");
  const [kind, setKind] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const input = useRef(null);
  useEffect(() => { input.current?.focus(); }, []);
  const submit = async event => {
    event.preventDefault();
    if (!path.trim() || busy) return;
    setBusy(true); setError("");
    try {
      const data = await outputsCall("publish", {
        path: path.trim(), ...(kind ? { kind } : {}), ...(title.trim() ? { title: title.trim() } : {}),
        ...(session?.id ? { sessionId: session.id } : {}), requestId: `ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
      });
      onDone(data.artifact, data.replayed);
    } catch (failure) {
      setError(failure.status === 404 ? "That file doesn't exist. Check the path." : failure.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="nx-out-publish" onSubmit={submit} aria-label="Add an output">
      <label className="nx-out-field is-wide">
        <span>File</span>
        <input ref={input} className="nx-input is-mono" value={path} onChange={event => setPath(event.target.value)} placeholder="outputs/report.md or a full path" />
      </label>
      <label className="nx-out-field">
        <span>Kind</span>
        <select className="nx-input" value={kind} onChange={event => setKind(event.target.value)}>
          <option value="">Guess from the file</option>
          {OUTPUT_KINDS.map(option => <option key={option} value={option}>{KIND_ONE[option]}</option>)}
        </select>
      </label>
      <label className="nx-out-field">
        <span>Title</span>
        <input className="nx-input" value={title} onChange={event => setTitle(event.target.value)} placeholder="Optional" />
      </label>
      <div className="nx-out-publish-actions">
        <Button variant="primary" size="sm" type="submit" disabled={!path.trim() || busy}>{busy ? <Spinner size={12} /> : null}Add</Button>
        <Button size="sm" onClick={onCancel}>Cancel</Button>
      </div>
      {error ? <p className="nx-out-error" role="alert"><Icon as={TriangleAlert} size={14} />{error}</p> : null}
    </form>
  );
}

function Thumb({ row }) {
  const [failed, setFailed] = useState(false);
  if (row.kind === "image" && !failed) return <img className="nx-out-thumb" src={rawUrl(row.path)} alt="" loading="lazy" onError={() => setFailed(true)} />;
  return <span className={`nx-out-glyph is-${row.kind}`}><Icon as={KIND_ICON[row.kind] || FileText} size={16} /></span>;
}

function OutputRow({ row, selected, onSelect }) {
  return (
    <li>
      <button type="button" className={`nx-out-row${selected ? " is-on" : ""}`} aria-current={selected || undefined} onClick={() => onSelect(row.id)}>
        <Thumb row={row} />
        <span className="nx-out-row-main">
          <strong title={row.title}>{row.title || row.name}</strong>
          <small>
            {KIND_ONE[row.kind] || row.kind}
            {row.title && row.title !== row.name ? <> · <span className="nx-out-mono" title={row.path}>{row.name}</span></> : null}
            {row.previousId ? " · new version" : ""}
          </small>
        </span>
        <span className="nx-out-row-side">
          <small>{ago(row.createdAt)}</small>
          <small>{formatSize(row.size)}</small>
        </span>
      </button>
    </li>
  );
}

const prettyJson = text => { try { return JSON.stringify(JSON.parse(text), null, 2); } catch { return text; } };

/** The current bytes at the published path, rendered by type. */
export function OutputPreview({ row, availability }) {
  const [state, setState] = useState({ status: "loading" });
  useEffect(() => {
    if (availability === "missing") return undefined;
    let live = true;
    setState({ status: "loading" });
    panesCall("artifact.open", { path: row.path })
      .then(data => { if (live) setState({ status: "ready", ...data }); })
      .catch(error => { if (live) setState({ status: "error", error: error.message }); });
    return () => { live = false; };
  }, [row.path, row.sha256, availability]);
  if (availability === "missing") return <PaneMessage icon={TriangleAlert} title="The file is gone">It was moved or deleted after it was published. The record stays here.</PaneMessage>;
  if (state.status === "loading") return <div className="nx-stage-loading"><Spinner size={16} /></div>;
  if (state.status === "error") return <PaneMessage icon={TriangleAlert} title="This output can't be shown">{state.error}</PaneMessage>;
  const isDiff = row.kind === "diff" || /\.(diff|patch)$/i.test(row.name);
  if (state.kind === "html") return <iframe className="nx-ap-frame" title={row.title} src={backendUrl(state.url)} referrerPolicy="no-referrer" />;
  if (state.kind === "markdown") return <div className="nx-ap-doc nx-scroll"><div className="nx-ap-prose"><NeyviaMessageBody text={state.text} /></div></div>;
  if (state.kind === "image") return <div className="nx-pane-image"><img src={rawUrl(row.path)} alt={row.title} /></div>;
  if (state.kind === "pdf") return <Suspense fallback={<div className="nx-stage-loading"><Spinner size={16} /></div>}><NxPdfApp target={row.path} /></Suspense>;
  if (state.kind === "text" && isDiff) return <DiffLines patch={state.text} />;
  if (state.kind === "text") return <pre className="nx-ap-text nx-scroll">{/\.json$/i.test(row.name) ? prettyJson(state.text) : state.text}</pre>;
  return <PaneMessage title={row.name}>{state.reason || "This kind of file has no preview. Open it to see it in the file pane."}</PaneMessage>;
}

function Detail({ row, phone, onBack, onClose }) {
  const [check, setCheck] = useState({ status: "loading" });
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    setCheck({ status: "loading" }); setError("");
    outputsCall("get", { id: row.id })
      .then(data => { if (live) setCheck({ status: "ready", availability: data.availability }); })
      .catch(failure => { if (live) setCheck({ status: "ready", availability: failure.status === 404 ? "gone" : "unknown", error: failure.message }); });
    return () => { live = false; };
  }, [row.id]);
  const availability = check.availability;
  const open = async () => {
    setOpening(true); setError("");
    try { await openOutput(row.id); } catch (failure) {
      setError(failure.status === 409 ? "It changed after it was published, so it can't be opened as that version." : failure.status === 404 ? "The file is gone." : failure.message);
    } finally { setOpening(false); }
  };
  return (
    <section className="nx-out-detail" aria-label={row.title || row.name}>
      <div className="nx-fp-bar">
        {phone ? <IconButton size="sm" icon={ChevronLeft} label="All outputs" onClick={onBack} /> : null}
        <Icon as={KIND_ICON[row.kind] || FileText} size={15} />
        <span className="nx-fp-name" title={row.path}>{row.title || row.name}</span>
        <span className="nx-fp-chip">{KIND_ONE[row.kind] || row.kind}</span>
        {check.status === "loading" ? <Spinner size={12} />
          : availability === "available" ? <span className="nx-fp-chip is-ok">Same as published</span>
            : availability === "changed" ? <span className="nx-fp-chip is-changed">Changed since</span>
              : availability === "missing" ? <span className="nx-fp-chip is-changed">File gone</span> : null}
        <span className="nx-out-actions">
        <Button size="sm" icon={ExternalLink} onClick={() => void open()} disabled={opening || availability === "missing" || availability === "changed"}>Open</Button>
        <Button size="sm" icon={ScanText} disabled={availability === "missing"} onClick={() => os.showPane("perception", perceptionTarget(layerForOutput(row), row.path))}>See as the agent</Button>
        <IconButton size="sm" icon={FolderOpen} label="Show in Files" onClick={() => os.openApp("files", "documents", parentOf(row.path))} />
        <IconButton size="sm" icon={Copy} label="Copy the path" onClick={() => void navigator.clipboard?.writeText(row.path)} />
        {!phone ? <IconButton size="sm" icon={X} label="Close the preview" onClick={onClose} /> : null}
        </span>
      </div>
      {availability === "changed" ? (
        <div className="nx-fp-banner is-warn"><Icon as={TriangleAlert} size={15} /><span>This file changed after it was published. Below is the file as it is now, not the published version.</span></div>
      ) : null}
      {error ? <div className="nx-fp-banner is-warn" role="alert"><Icon as={TriangleAlert} size={15} /><span>{error}</span></div> : null}
      <div className="nx-out-preview">
        {check.status === "loading" ? <div className="nx-stage-loading"><Spinner size={16} /></div> : <OutputPreview row={row} availability={availability} />}
      </div>
      <div className="nx-fp-foot">
        <span className="nx-out-mono" title={row.sha256}>sha256 {String(row.sha256 || "").slice(0, 12)}</span>
        <span>{formatSize(row.size)}</span>
        <span>{row.createdAt ? new Date(row.createdAt).toLocaleString() : ""}</span>
        {row.sessionId ? <span title={row.sessionId}>From a chat</span> : null}
      </div>
    </section>
  );
}

export function NxOutputs({ target, session }) {
  const phone = useMedia("(max-width: 760px)");
  const signal = useOs(state => state.appSignals.outputs);
  const busState = useOs(state => state.bus.state);
  const [kind, setKind] = useState(() => (OUTPUT_KINDS.includes(target) ? target : local.get("outputs.kind", "")));
  const [mine, setMine] = useState(false);
  const [list, setList] = useState({ status: "loading", rows: [], total: 0 });
  const [counts, setCounts] = useState({});
  const [selected, setSelected] = useState(() => (target && !OUTPUT_KINDS.includes(target) ? target : ""));
  const [adding, setAdding] = useState(false);
  const [more, setMore] = useState(false);
  const sessionId = mine && session?.id ? session.id : "";

  const filters = useMemo(() => ({ ...(kind ? { kind } : {}), ...(sessionId ? { sessionId } : {}) }), [kind, sessionId]);
  const load = useCallback(async ({ quiet = false } = {}) => {
    if (!quiet) setList(current => ({ ...current, status: current.rows.length ? "refreshing" : "loading" }));
    try {
      const data = await outputsCall("list", { ...filters, limit: PAGE, offset: 0 });
      setList({ status: "ready", rows: data.artifacts || [], total: data.total || 0 });
    } catch (error) {
      setList(current => ({ ...current, status: "error", error: error.message }));
    }
    // The chips' counts: one small read per kind, in parallel.
    const scope = sessionId ? { sessionId } : {};
    const totals = await Promise.all(["", ...OUTPUT_KINDS].map(item => outputsCall("list", { ...scope, ...(item ? { kind: item } : {}), limit: 1 }).then(data => data.total).catch(() => null)));
    setCounts(Object.fromEntries(["all", ...OUTPUT_KINDS].map((item, index) => [item, totals[index]])));
  }, [filters, sessionId]);

  useEffect(() => { void load(); }, [load]);
  // A new publication (artifact.published on the bus) or a reconnect: read the registry again.
  const lastSignal = useRef(signal?.seq || 0);
  useEffect(() => {
    if (!signal || signal.seq === lastSignal.current) return;
    lastSignal.current = signal.seq;
    void load({ quiet: true });
  }, [signal, load]);
  const wasLive = useRef(busState === "live");
  useEffect(() => {
    if (busState === "live" && !wasLive.current) void load({ quiet: true });
    wasLive.current = busState === "live";
  }, [busState, load]);

  const loadMore = async () => {
    setMore(true);
    try {
      const data = await outputsCall("list", { ...filters, limit: PAGE, offset: list.rows.length });
      setList(current => ({ ...current, rows: [...current.rows, ...(data.artifacts || []).filter(row => !current.rows.some(known => known.id === row.id))], total: data.total || current.total }));
    } catch (error) {
      os.notify({ level: "error", message: `More outputs couldn't be read: ${error.message}` });
    } finally { setMore(false); }
  };

  const chooseKind = value => { setKind(value); local.set("outputs.kind", value || null); };
  const row = list.rows.find(item => item.id === selected) || null;
  const showList = !phone || !row;

  return (
    <div className={`nx-out${row ? " has-detail" : ""}`}>
      <div className="nx-out-bar">
        <KindFilter value={kind} counts={counts} onChange={chooseKind} />
        <span className="nx-head-spacer" />
        {session?.id ? (
          <button type="button" className={`nx-out-filter${mine ? " is-on" : ""}`} aria-pressed={mine} onClick={() => setMine(value => !value)} title="Only what this chat published">This chat</button>
        ) : null}
        <IconButton size="sm" icon={RefreshCw} label="Refresh" onClick={() => void load()} />
        <Button size="sm" icon={Plus} onClick={() => setAdding(value => !value)} aria-expanded={adding}>Add</Button>
      </div>
      {adding ? (
        <PublishForm session={session} onCancel={() => setAdding(false)} onDone={(artifact, replayed) => {
          setAdding(false);
          os.notify({ level: "success", message: replayed ? `${artifact.title} was already published` : `${artifact.title} added to Outputs` });
          setSelected(artifact.id);
          void load({ quiet: true });
        }} />
      ) : null}
      <div className="nx-out-body">
        {showList ? (
          <div className="nx-out-list nx-scroll" aria-busy={list.status === "loading" || list.status === "refreshing"}>
            {list.status === "loading" ? <div className="nx-stage-loading"><Spinner size={16} /></div> : null}
            {list.status === "error" && !list.rows.length ? (
              <PaneMessage icon={TriangleAlert} title="Outputs can't be read" action={<Button size="sm" onClick={() => void load()}>Try again</Button>}>{list.error}</PaneMessage>
            ) : null}
            {list.status === "ready" && !list.rows.length ? (
              <PaneMessage icon={Inbox} title={kind || sessionId ? "Nothing here with these filters" : "Nothing published yet"}
                action={kind || sessionId ? <Button size="sm" onClick={() => { chooseKind(""); setMine(false); }}>Show everything</Button> : <Button size="sm" icon={Plus} onClick={() => setAdding(true)}>Add a file</Button>}>
                {kind || sessionId ? "Try another kind, or show everything." : "When an agent saves a file, a change, an image, a report or a receipt, it shows here."}
              </PaneMessage>
            ) : null}
            {list.status === "error" && list.rows.length ? <p className="nx-out-error" role="alert"><Icon as={TriangleAlert} size={14} />Couldn't refresh: {list.error}</p> : null}
            {list.rows.length ? (
              <ul className="nx-out-rows" aria-label="Outputs">
                {list.rows.map(item => <OutputRow key={item.id} row={item} selected={item.id === selected} onSelect={setSelected} />)}
              </ul>
            ) : null}
            {list.rows.length < list.total ? (
              <div className="nx-out-more"><Button size="sm" onClick={() => void loadMore()} disabled={more}>{more ? <Spinner size={12} /> : null}Show more ({list.total - list.rows.length})</Button></div>
            ) : null}
          </div>
        ) : null}
        {row ? <Detail key={row.id} row={row} phone={phone} onBack={() => setSelected("")} onClose={() => setSelected("")} /> : null}
        {!row && !phone && list.rows.length ? (
          <div className="nx-out-empty-detail"><PaneMessage icon={ScrollText} title="Choose an output">Its preview shows here, with the agent's view of it one click away.</PaneMessage></div>
        ) : null}
      </div>
    </div>
  );
}
