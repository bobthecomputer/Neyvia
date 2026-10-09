import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft, ArrowUp, ChevronRight, Eye, EyeOff, File, FileImage, FileText, Folder, FolderInput, FolderPlus,
  Home, LayoutGrid, List, NotebookPen, PencilLine, RotateCcw, Search, Trash2, Undo2, X,
} from "lucide-react";

import "./nxDocs.css";
import { Button, Icon, IconButton, Spinner, ago, local } from "./nxPrimitives.jsx";
import { os, useOs } from "./nxOsStore.js";
import { filesCall, formatSize, joinPath, nameOf, parentOf, rawUrl } from "./nxDocsApi.js";
import { LOCAL_DRAG, REMOTE_DRAG, dragSource, dropIntent, hasDrag, parsePcTarget } from "./nxDevicesModel.js";
import { OtherPcsTree, RemotePane, SendToPc, TransfersStrip, pairedDevices, takeFrom, useDevices } from "./NxOtherPcs.jsx";
import { CopyButton } from "./details/nxDetails.jsx";

// Files (Documents suite): a file explorer over Home, the workspace, Neyvia
// Notes and project folders. Paul and the bot side (neyvia.files.*) change the
// same folders; delete always goes to the Recycle Bin and the last move,
// rename, new folder or delete can be undone from either side.

const PLACE_ICONS = { home: Home, workspace: Folder, notes: NotebookPen, project: Folder };
const KIND_ICONS = { folder: Folder, image: FileImage, pdf: FileText, notes: NotebookPen, text: FileText };
const DRAG_TYPE = LOCAL_DRAG;

function TreeNode({ place, path, name, icon, depth, cwd, onGo, onDropPath, refreshKey }) {
  const [open, setOpen] = useState(false);
  const [children, setChildren] = useState(null);
  const [over, setOver] = useState(false);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    filesCall("list", { path }).then(result => { if (!cancelled) setChildren(result.entries.filter(entry => entry.kind === "folder" && !entry.protected)); })
      .catch(() => { if (!cancelled) setChildren([]); });
    return () => { cancelled = true; };
  }, [open, path, refreshKey]);
  const here = cwd && cwd.toLowerCase() === path.toLowerCase();
  return (
    <li>
      <div className={`nx-files-node${here ? " is-on" : ""}${over ? " is-drop" : ""}`} style={{ paddingLeft: `calc(var(--nx-space-4) + ${depth} * var(--nx-space-12))` }}
        onDragOver={event => { if (hasDrag(event.dataTransfer, DRAG_TYPE, REMOTE_DRAG)) { event.preventDefault(); setOver(true); } }}
        onDragLeave={() => setOver(false)}
        onDrop={event => { event.preventDefault(); setOver(false); onDropPath(dragSource(event.dataTransfer), path); }}>
        <button type="button" className={`nx-files-twist${open ? " is-open" : ""}`} aria-label={open ? `Collapse ${name}` : `Expand ${name}`} onClick={() => setOpen(!open)}>
          <Icon as={ChevronRight} size={12} />
        </button>
        <button type="button" className="nx-files-nodename" onClick={() => onGo(path)} title={path}>
          <Icon as={icon || Folder} size={14} /><span>{name}</span>
        </button>
      </div>
      {open && children?.length ? (
        <ul>{children.map(child => <TreeNode key={child.path} place={place} path={child.path} name={child.name} depth={depth + 1} cwd={cwd} onGo={onGo} onDropPath={onDropPath} refreshKey={refreshKey} />)}</ul>
      ) : null}
    </li>
  );
}

function QuickLook({ item, info, onOpen, onRename, onMove, onTrash, onClose, devices = [] }) {
  if (!item) return null;
  const kind = item.openWith;
  return (
    <aside className="nx-files-look nx-scroll" aria-label={`Quick look: ${item.name}`} data-nx-comment-target={`files:${String(item.path).replace(/\\/g, "/")}`} data-nx-comment-kind={kind === "image" ? "image" : kind === "text" || kind === "notes" ? "text" : "dom"} data-nx-comment-label={item.name}
      ref={element => { if (element) element.__nxText = () => info?.preview || ""; }}>
      <div className="nx-files-lookhead">
        <strong title={item.name}>{item.name}</strong>
        <IconButton size="sm" icon={X} label="Close quick look" onClick={onClose} />
      </div>
      <div className="nx-files-lookbody">
        {kind === "image" ? <img src={rawUrl(item.path)} alt={item.name} /> : null}
        {(kind === "text" || kind === "notes") && info?.preview != null ? (
          <pre>{info.preview}{info.previewTruncated ? "\n…" : ""}</pre>
        ) : null}
        {(kind === "text" || kind === "notes") && !info ? <Spinner size={14} /> : null}
        {kind === "pdf" || kind === "folder" || kind === "none" ? (
          <div className="nx-files-lookicon"><Icon as={KIND_ICONS[kind] || File} size={36} /></div>
        ) : null}
      </div>
      <dl className="nx-files-facts">
        {item.kind === "file" ? <><dt>Size</dt><dd>{formatSize(item.size)}</dd></> : <><dt>Items</dt><dd>{info?.items ?? "…"}</dd></>}
        <dt>Changed</dt><dd>{new Date(item.modified).toLocaleString()}</dd>
        <dt>Where</dt><dd className="nx-files-where" title={item.path}>{parentOf(item.path)}
          <CopyButton text={item.path} label="Copy path" size="xs" />
        </dd>
      </dl>
      <div className="nx-files-lookactions">
        {kind === "pdf" ? <Button size="sm" variant="outline" icon={FileText} onClick={onOpen}>Open in PDF viewer</Button> : null}
        {kind === "notes" ? <Button size="sm" variant="outline" icon={NotebookPen} onClick={onOpen}>Open in Notes</Button> : null}
        {kind === "folder" ? <Button size="sm" variant="outline" icon={Folder} onClick={onOpen}>Open</Button> : null}
        <Button size="sm" icon={PencilLine} onClick={onRename}>Rename</Button>
        <Button size="sm" icon={FolderInput} onClick={onMove}>Move to…</Button>
        <Button size="sm" icon={Trash2} onClick={onTrash}>Delete</Button>
        {!item.protected ? <SendToPc path={item.path} devices={devices} /> : null}
      </div>
    </aside>
  );
}

/** A picture's thumbnail in the grid: it fades in once loaded and quietly gives way to the icon if it can't load. */
function Thumb({ path }) {
  const [state, setState] = useState("loading");
  if (state === "failed") return null;
  return <img className={`nx-files-thumb is-${state}`} src={rawUrl(path)} alt="" loading="lazy" decoding="async" onLoad={() => setState("ready")} onError={() => setState("failed")} />;
}

/** The folder you're in, named, with what it holds. */
function FolderHead({ name, entries, hidden }) {
  const folders = entries.filter(entry => entry.kind === "folder").length;
  const files = entries.length - folders;
  const parts = [folders ? `${folders} ${folders === 1 ? "folder" : "folders"}` : "", files ? `${files} ${files === 1 ? "file" : "files"}` : "", hidden ? `${hidden} hidden` : ""].filter(Boolean);
  return (
    <div className="nx-files-head">
      <span className="nx-files-tile is-folder is-big" aria-hidden="true"><Icon as={Folder} size={18} /></span>
      <div><h2>{name}</h2><p>{parts.join(" · ") || "Empty"}</p></div>
    </div>
  );
}

export function NxFilesApp({ target }) {
  const [places, setPlaces] = useState([]);
  const [cwd, setCwd] = useState(null);
  const [listing, setListing] = useState({ status: "loading", entries: [], crumbs: [] });
  const [history, setHistory] = useState([]);
  const [selected, setSelected] = useState(null);
  const [info, setInfo] = useState(null);
  const [look, setLook] = useState(false);
  const [filter, setFilter] = useState("");
  const [showHidden, setShowHidden] = useState(() => local.get("files.hidden", false));
  const [renaming, setRenaming] = useState(null); // { path, value } | { path: null, value } for a new folder
  const [moving, setMoving] = useState(null); // { path, value }
  const [dropOver, setDropOver] = useState(null);
  const [treeKey, setTreeKey] = useState(0);
  const [canUndo, setCanUndo] = useState(false);
  // Another PC's folders (cross-pc): { device, path } while one is open; side by side keeps this PC's list beside it.
  const [remote, setRemote] = useState(() => parsePcTarget(target));
  const [split, setSplit] = useState(() => local.get("files.split", false));
  // List or grid (pictures as thumbnails), remembered.
  const [layout, setLayout] = useState(() => (local.get("files.layout", "list") === "grid" ? "grid" : "list"));
  const toggleLayout = () => { const next = layout === "grid" ? "list" : "grid"; setLayout(next); local.set("files.layout", next); };
  const { data: deviceData } = useDevices();
  const paired = useMemo(() => pairedDevices(deviceData), [deviceData]);
  const remoteDevice = remote ? (deviceData?.devices || []).find(device => device.id === remote.device) : null;
  // A Take that just landed in the folder on screen shows up without a refresh.
  const landed = (deviceData?.transfers || []).filter(transfer => transfer.direction === "take" && transfer.status === "done"
    && cwd && parentOf(transfer.to || "").toLowerCase() === cwd.toLowerCase()).length;
  const listRef = useRef(null);
  const request = useRef(0); // only the latest listing request may land (fast clicks)
  const reveal = useRef(null); // a path to select once its folder has loaded (a finished Take's "Show")
  const signal = useOs(state => state.appSignals?.files);
  const now = cwd;

  const load = useCallback(async (path, { keepSelection = false } = {}) => {
    const ticket = ++request.current;
    setListing(current => ({ ...current, status: "loading" }));
    try {
      const result = await filesCall("list", { path, showHidden });
      if (ticket !== request.current) return;
      setListing({ status: "ready", ...result });
      setCwd(result.path);
      local.set("files.cwd", result.path);
      if (!keepSelection) { setSelected(null); setInfo(null); }
      if (reveal.current && result.entries?.some(entry => entry.path === reveal.current)) setSelected(reveal.current);
      reveal.current = null;
    } catch (error) {
      if (ticket === request.current) setListing(current => ({ ...current, status: "error", error: error.message }));
    }
  }, [showHidden]);

  const go = useCallback(path => {
    if (!path || path === cwd) return;
    if (cwd) setHistory(current => [...current.slice(-30), cwd]);
    setFilter(""); setRenaming(null); setMoving(null);
    void load(path);
  }, [cwd, load]);

  useEffect(() => {
    let cancelled = false;
    filesCall("list", {}).then(result => {
      if (cancelled) return;
      setPlaces(result.places);
      const start = (parsePcTarget(target) ? null : target) || local.get("files.cwd", null) || result.places[0]?.path;
      if (start) void load(start);
    }).catch(error => !cancelled && setListing({ status: "error", error: error.message, entries: [], crumbs: [] }));
    return () => { cancelled = true; };
    // the first folder only; later targets are handled below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    const pc = parsePcTarget(target);
    if (pc) { setRemote(pc); return; } // Accounts › Other PCs › Open
    if (target && places.length) {
      setRemote(null);
      go(target); /* a model or Notes asked for a folder */
    }
  }, [target]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (cwd) void load(cwd, { keepSelection: true }); }, [showHidden]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { if (landed && cwd) void load(cwd, { keepSelection: true }); }, [landed]); // eslint-disable-line react-hooks/exhaustive-deps

  // A model changed files: refresh what's on screen.
  useEffect(() => {
    if (!signal || !cwd) return;
    setCanUndo(true);
    void load(cwd, { keepSelection: true });
    setTreeKey(key => key + 1);
  }, [signal?.seq]); // eslint-disable-line react-hooks/exhaustive-deps

  const item = useMemo(() => listing.entries.find(entry => entry.path === selected) || null, [listing.entries, selected]);
  useEffect(() => {
    if (!item) { setInfo(null); return undefined; }
    let cancelled = false;
    setInfo(null);
    const timer = setTimeout(() => {
      filesCall("stat", { path: item.path, preview: item.openWith === "text" || item.openWith === "notes" })
        .then(result => { if (!cancelled) setInfo(result); }).catch(() => {});
    }, 120);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [item]);

  const refresh = () => { void load(cwd, { keepSelection: true }); setTreeKey(key => key + 1); };
  const fail = error => os.notify({ level: "error", message: error.message });
  const undoable = message => {
    setCanUndo(true);
    os.notify({ level: "success", message, action: { label: "Undo", run: () => void undo() } });
  };

  const undo = async () => {
    try {
      const result = await filesCall("undo");
      setCanUndo(false);
      os.notify({ level: "success", message: result.message });
      refresh();
    } catch (error) { setCanUndo(false); fail(error); }
  };

  const open = entry => {
    if (!entry) return;
    if (entry.kind === "folder") { if (!entry.protected) go(entry.path); return; }
    if (entry.openWith === "pdf") {
      void filesCall("stat", { path: entry.path }).then(result => {
        os.openApp("pdf", "documents", result.pdfApp ? entry.path : rawUrl(entry.path, true));
      }).catch(fail);
      return;
    }
    if (entry.openWith === "notes") { os.openApp("notes", "documents", entry.path); return; }
    setSelected(entry.path); setLook(true);
  };

  const commitRename = async () => {
    if (!renaming) return;
    const value = renaming.value.trim();
    const current = renaming;
    setRenaming(null);
    if (!value || /[\\/:*?"<>|]/.test(value)) { if (value) os.notify({ level: "warning", message: "A name can't contain \\ / : * ? \" < > |" }); return; }
    try {
      if (current.path === null) {
        const result = await filesCall("mkdir", { path: joinPath(cwd, value) });
        setSelected(result.entry.path);
        undoable(`Folder “${value}” created`);
      } else {
        if (value === nameOf(current.path)) return;
        const result = await filesCall("move", { from: current.path, to: joinPath(parentOf(current.path), value) });
        setSelected(result.to);
        undoable(`Renamed to “${value}”`);
      }
      refresh();
    } catch (error) { fail(error); }
  };

  const moveTo = async (from, to) => {
    if (!from || !to || parentOf(from).toLowerCase() === to.toLowerCase() || from.toLowerCase() === to.toLowerCase()) return;
    try {
      const result = await filesCall("move", { from, to });
      setMoving(null);
      undoable(`Moved “${nameOf(from)}” to ${nameOf(parentOf(result.to)) || parentOf(result.to)}`);
      refresh();
    } catch (error) { fail(error); }
  };

  const trash = async entry => {
    if (!entry) return;
    try {
      await filesCall("trash", { path: entry.path });
      setSelected(null); setLook(false);
      undoable(`“${entry.name}” is in the Recycle Bin`);
      refresh();
    } catch (error) { fail(error); }
  };

  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return needle ? listing.entries.filter(entry => entry.name.toLowerCase().includes(needle)) : listing.entries;
  }, [listing.entries, filter]);

  const onKeyDown = event => {
    if (event.target.closest("input")) return;
    const index = shown.findIndex(entry => entry.path === selected);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const next = shown[Math.max(0, Math.min(shown.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)))];
      if (next) { setSelected(next.path); listRef.current?.querySelector(`[data-path="${CSS.escape(next.path)}"]`)?.scrollIntoView({ block: "nearest" }); }
    } else if (event.key === "Enter" && item) { event.preventDefault(); open(item); }
    else if (event.key === "F2" && item) { event.preventDefault(); setRenaming({ path: item.path, value: item.name }); }
    else if (event.key === "Delete" && item) { event.preventDefault(); void trash(item); }
    else if (event.key === "Backspace" && listing.parent) { event.preventDefault(); go(listing.parent); }
    else if (event.key === " " && item) { event.preventDefault(); setLook(value => !value); }
    else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") { event.preventDefault(); void undo(); }
  };

  const back = () => {
    const previous = history.at(-1);
    if (!previous) return;
    setHistory(current => current.slice(0, -1));
    void load(previous);
  };

  // A drop from this PC moves; a drop from another PC takes a copy into that folder.
  const dropInto = (source, folder) => {
    if (!folder) return;
    const intent = dropIntent(source, { path: folder });
    if (intent === "move") { void moveTo(source.path, folder); return; }
    if (intent !== "take") return;
    const device = (deviceData?.devices || []).find(row => row.id === source.device);
    if (device) void takeFrom(device, source.path, folder);
  };
  const dropProps = path => ({
    onDragOver: event => {
      if (!hasDrag(event.dataTransfer, DRAG_TYPE, REMOTE_DRAG)) return;
      event.preventDefault(); event.stopPropagation();
      event.dataTransfer.dropEffect = hasDrag(event.dataTransfer, REMOTE_DRAG) ? "copy" : "move";
      setDropOver(path);
    },
    onDragLeave: () => setDropOver(null),
    onDrop: event => { event.preventDefault(); event.stopPropagation(); setDropOver(null); dropInto(dragSource(event.dataTransfer), path); },
  });
  // The list itself takes another PC's files into the folder on screen.
  const listDrop = {
    onDragOver: event => { if (cwd && hasDrag(event.dataTransfer, REMOTE_DRAG)) { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; setDropOver(cwd); } },
    onDragLeave: event => { if (!event.currentTarget.contains(event.relatedTarget)) setDropOver(null); },
    onDrop: event => { const source = dragSource(event.dataTransfer); if (source?.device) { event.preventDefault(); setDropOver(null); dropInto(source, cwd); } },
  };
  const openRemote = device => { setRemote({ device: device.id, path: null }); setLook(false); };
  const toggleSplit = () => { setSplit(!split); local.set("files.split", !split || null); };

  return (
    <div className={`nx-files${look && item ? " has-look" : ""}${remoteDevice && split ? " is-split" : ""}`} onKeyDown={onKeyDown}>
      <nav className="nx-files-tree nx-scroll" aria-label="Places">
        <ul>
          {places.map(place => (
            <TreeNode key={place.path} place={place} path={place.path} name={place.name} icon={PLACE_ICONS[place.kind]} depth={0} cwd={now}
              onGo={path => { if (remote && !split) setRemote(null); go(path); }} onDropPath={dropInto} refreshKey={treeKey} />
          ))}
        </ul>
        <OtherPcsTree data={deviceData} current={remote?.device} onOpen={openRemote} />
      </nav>

      <div className="nx-files-stack">
      <div className="nx-files-panes">
      <section className={`nx-files-main${remoteDevice && !split ? " is-hidden" : ""}`} aria-label="This PC">
        <div className="nx-docs-bar">
          <IconButton icon={ArrowLeft} label="Back" disabled={!history.length} onClick={back} />
          <IconButton icon={ArrowUp} label="Up one folder" disabled={!listing.parent} onClick={() => go(listing.parent)} />
          <select className="nx-files-placepick" aria-label="Place" value={listing.place?.path || ""} onChange={event => go(event.target.value)}>
            {places.map(place => <option key={place.path} value={place.path}>{place.name}</option>)}
          </select>
          <ol className="nx-files-crumbs" aria-label="Folder path">
            {(listing.crumbs || []).map((crumb, index) => (
              <li key={crumb.path} className={dropOver === crumb.path ? "is-drop" : ""} {...dropProps(crumb.path)}>
                {index ? <Icon as={ChevronRight} size={12} /> : null}
                <button type="button" onClick={() => go(crumb.path)} aria-current={crumb.path === cwd ? "page" : undefined} title={crumb.path}>{crumb.name}</button>
              </li>
            ))}
          </ol>
          <span className="nx-docs-spacer" />
          <label className="nx-docs-search is-small">
            <Icon as={Search} size={13} />
            <input value={filter} onChange={event => setFilter(event.target.value)} placeholder="Filter" aria-label="Filter this folder" />
          </label>
          <IconButton icon={layout === "grid" ? List : LayoutGrid} label={layout === "grid" ? "Show as a list" : "Show as a grid"} onClick={toggleLayout} />
          <IconButton icon={FolderPlus} label="New folder" onClick={() => setRenaming({ path: null, value: "New folder" })} />
          <IconButton icon={showHidden ? EyeOff : Eye} label={showHidden ? "Hide hidden files" : `Show hidden files${listing.hiddenCount ? ` (${listing.hiddenCount})` : ""}`} active={showHidden}
            onClick={() => { setShowHidden(!showHidden); local.set("files.hidden", !showHidden || null); }} />
          <IconButton icon={Undo2} label="Undo last change" disabled={!canUndo} onClick={() => void undo()} />
          <IconButton icon={RotateCcw} label="Refresh" onClick={refresh} />
        </div>

        {moving ? (
          <form className="nx-files-moveform" onSubmit={event => { event.preventDefault(); void moveTo(moving.path, moving.value.trim()); }}>
            <span>Move “{nameOf(moving.path)}” to</span>
            <input className="nx-input" autoFocus value={moving.value} onChange={event => setMoving({ ...moving, value: event.target.value })} aria-label="Destination folder"
              onKeyDown={event => { if (event.key === "Escape") setMoving(null); }} />
            <Button size="sm" variant="outline" type="submit">Move</Button>
            <Button size="sm" onClick={() => setMoving(null)}>Cancel</Button>
            <span className="nx-files-movehint">Or drag it onto a folder on the left.</span>
          </form>
        ) : null}

        {listing.status === "ready" ? <FolderHead name={listing.crumbs?.[listing.crumbs.length - 1]?.name || nameOf(cwd) || "Files"} entries={shown} hidden={showHidden ? 0 : listing.hiddenCount} /> : null}
        <div className="nx-files-body">
          <div ref={listRef} key={cwd || "places"} className={`nx-files-list nx-scroll is-${layout}${dropOver && dropOver === cwd ? " is-drop" : ""}`} role="listbox" aria-label={cwd || "Files"} tabIndex={0} {...listDrop}>
            {renaming?.path === null ? (
              <div className="nx-files-row is-new">
                <Icon as={Folder} size={15} />
                <input className="nx-files-rename" autoFocus value={renaming.value} aria-label="New folder name" onFocus={event => event.target.select()}
                  onChange={event => setRenaming({ ...renaming, value: event.target.value })} onBlur={() => void commitRename()}
                  onKeyDown={event => { if (event.key === "Enter") void commitRename(); if (event.key === "Escape") setRenaming(null); }} />
              </div>
            ) : null}
            {listing.status === "error" ? <div className="nx-docs-empty"><strong>This folder didn't open</strong><p>{listing.error}</p></div> : null}
            {listing.status === "loading" ? <div className="nx-files-skeleton" aria-hidden="true">{[0, 1, 2, 3, 4, 5].map(index => <span key={index} />)}</div> : null}
            {listing.status === "ready" && !shown.length && renaming?.path !== null ? (
              <div className="nx-files-empty">
                <span className="nx-files-empty-art" aria-hidden="true"><Icon as={Folder} size={30} /></span>
                <strong>{filter ? "Nothing matches" : "This folder is empty"}</strong>
                <p>{filter ? `Nothing here is called “${filter}”.` : "Drop files here from another PC, make a folder, or ask a chat to save something here."}</p>
                {listing.hiddenCount && !filter ? <p>{listing.hiddenCount} hidden {listing.hiddenCount === 1 ? "item" : "items"}.</p> : null}
                {!filter ? <Button size="sm" variant="outline" icon={FolderPlus} onClick={() => setRenaming({ path: null, value: "New folder" })}>New folder</Button> : null}
              </div>
            ) : null}
            {shown.map(entry => {
              const glyph = entry.kind === "folder" ? Folder : KIND_ICONS[entry.openWith] || File;
              const editing = renaming?.path === entry.path;
              return (
                <div key={entry.path} data-path={entry.path} role="option" aria-selected={selected === entry.path}
                  className={`nx-files-row${selected === entry.path ? " is-on" : ""}${entry.hidden ? " is-hidden" : ""}${entry.protected ? " is-locked" : ""}${dropOver === entry.path ? " is-drop" : ""}`}
                  draggable={!editing && !entry.protected}
                  onDragStart={event => { event.dataTransfer.setData(DRAG_TYPE, entry.path); event.dataTransfer.effectAllowed = "copyMove"; }}
                  {...(entry.kind === "folder" && !entry.protected ? dropProps(entry.path) : {})}
                  onClick={() => setSelected(entry.path)} onDoubleClick={() => open(entry)}
                  title={entry.protected ? "Protected: the live Neyvia folder" : entry.path}>
                  <span className={`nx-files-tile is-${entry.kind === "folder" ? "folder" : entry.openWith || "file"}`} aria-hidden="true">
                    {layout === "grid" && entry.openWith === "image" ? <Thumb path={entry.path} /> : null}
                    <Icon as={glyph} size={layout === "grid" ? 26 : 15} className={`nx-files-glyph is-${entry.kind === "folder" ? "folder" : entry.openWith}`} />
                  </span>
                  {editing ? (
                    <input className="nx-files-rename" autoFocus value={renaming.value} aria-label={`Rename ${entry.name}`}
                      onFocus={event => { const dot = entry.kind === "file" ? event.target.value.lastIndexOf(".") : -1; event.target.setSelectionRange(0, dot > 0 ? dot : event.target.value.length); }}
                      onChange={event => setRenaming({ ...renaming, value: event.target.value })} onBlur={() => void commitRename()}
                      onKeyDown={event => { if (event.key === "Enter") void commitRename(); if (event.key === "Escape") setRenaming(null); }} />
                  ) : <span className="nx-files-name">{entry.name}</span>}
                  <span className="nx-files-time">{ago(entry.modified)}</span>
                  <span className="nx-files-size">{entry.kind === "file" ? formatSize(entry.size) : ""}</span>
                </div>
              );
            })}
            {listing.truncated ? <p className="nx-files-more">Showing the first 2,000 items.</p> : null}
          </div>
          {look && item ? (
            <QuickLook item={item} info={info} onOpen={() => open(item)} onClose={() => setLook(false)}
              onRename={() => setRenaming({ path: item.path, value: item.name })}
              onMove={() => setMoving({ path: item.path, value: parentOf(item.path) })}
              onTrash={() => void trash(item)} devices={paired} />
          ) : null}
        </div>
        {item && !look ? (
          <div className="nx-files-selbar">
            <span title={item.path}>{item.name}</span>
            <span className="nx-docs-spacer" />
            <Button size="sm" icon={Eye} onClick={() => setLook(true)}>Quick look</Button>
            <Button size="sm" icon={PencilLine} onClick={() => setRenaming({ path: item.path, value: item.name })}>Rename</Button>
            <Button size="sm" icon={FolderInput} onClick={() => setMoving({ path: item.path, value: parentOf(item.path) })}>Move</Button>
            <Button size="sm" icon={Trash2} onClick={() => void trash(item)}>Delete</Button>
            {!item.protected ? <SendToPc path={item.path} devices={paired} /> : null}
          </div>
        ) : null}
      </section>
      {remoteDevice ? (
        <RemotePane key={remoteDevice.id} device={remoteDevice} path={remote.path} onPath={path => setRemote({ device: remoteDevice.id, path })}
          split={split} onToggleSplit={toggleSplit} onClose={() => setRemote(null)} localFolder={cwd} />
      ) : null}
      </div>
      <TransfersStrip transfers={deviceData?.transfers} onShow={path => {
        if (!split) setRemote(null);
        reveal.current = path;
        if (parentOf(path).toLowerCase() === String(cwd || "").toLowerCase()) void load(cwd); else go(parentOf(path));
      }} />
      </div>
    </div>
  );
}
