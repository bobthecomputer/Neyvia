import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import {
  ArrowDownToLine, ArrowUpFromLine, ChevronRight, Columns2, Copy, File, FileImage, FileText, Folder, FolderOpen, Inbox,
  Laptop, Link2, Monitor, NotebookPen, Pause, Play, RefreshCw, Search, Unlink, X,
} from "lucide-react";

import "./nxOtherPcs.css";
import { Button, Icon, IconButton, Popover, Spinner, StatusDot, ago } from "./nxPrimitives.jsx";
import { os, useOs } from "./nxOsStore.js";
import { devicesCall, deviceRawUrl, filesCall, formatSize, nameOf, parentOf } from "./nxDocsApi.js";
import {
  LOCAL_DRAG, REMOTE_DRAG, deviceStatusText, dragSource, dropIntent, hasDrag, isActive, pcTarget, sendTarget, shareSummary, transferFraction, transferLine,
} from "./nxDevicesModel.js";

// Other PCs (cross-pc): reach the files of another PC running Neyvia on the
// tailnet. Paul's side lives in Files ("Other PCs" under Places, Take / Send,
// side by side) and Accounts (pair, approve, what each PC shares). The bot side
// is neyvia.devices.*; both call the same backend (POST /api/ui/devices).

// ---- one shared, polled view of the devices and transfers --------------------------------------

const store = { data: null, status: "loading", error: "", listeners: new Set(), timer: null, inflight: null, users: 0 };
const emit = () => { for (const listener of store.listeners) listener(); };

export async function refreshDevices(op = "list") {
  if (op === "list" && store.inflight) return store.inflight;
  const run = devicesCall(op, {}).then(data => {
    store.data = data; store.status = "ready"; store.error = "";
    return data;
  }).catch(error => {
    store.status = store.data ? "ready" : "error"; store.error = error.message;
    throw error;
  }).finally(() => { if (op === "list") store.inflight = null; emit(); schedule(); });
  if (op === "list") store.inflight = run;
  return run;
}

function busy(data) {
  return Boolean(data?.transfers?.some(isActive) || data?.devices?.some(device => device.status === "waiting") || data?.requests?.length);
}

function schedule() {
  clearTimeout(store.timer);
  if (!store.users) return;
  store.timer = setTimeout(() => void refreshDevices().catch(() => {}), busy(store.data) ? 1000 : 12000);
}

function subscribe(listener) {
  store.listeners.add(listener);
  store.users += 1;
  if (store.users === 1) void refreshDevices().catch(() => {});
  return () => {
    store.listeners.delete(listener);
    store.users -= 1;
    if (!store.users) clearTimeout(store.timer);
  };
}

const snapshot = () => store.data;

/** The devices list (polled faster while something moves) plus a refresh. */
export function useDevices() {
  const data = useSyncExternalStore(subscribe, snapshot);
  const signal = useOs(state => state.appSignals?.devices?.seq);
  useEffect(() => { if (signal) void refreshDevices().catch(() => {}); }, [signal]);
  return { data, status: store.status, error: store.error, refresh: refreshDevices };
}

export const pairedDevices = data => (data?.devices || []).filter(device => device.status === "paired");

// ---- take and send --------------------------------------------------------------------------------

export async function takeFrom(device, from, to = undefined) {
  try {
    const result = await devicesCall("files.fetch", { device: device.id, from, ...(to ? { to } : {}) });
    os.notify({ level: "info", message: `Taking “${nameOf(from)}” from ${device.name}` });
    void refreshDevices().catch(() => {});
    return result;
  } catch (error) {
    os.notify({ level: "error", message: error.message });
    return null;
  }
}

export async function sendTo(device, from, to = null) {
  try {
    const result = await devicesCall("files.send", { device: device.id, from, ...(to ? { to } : {}) });
    os.notify({ level: "info", message: `Sending “${nameOf(from)}” to ${device.name}${to ? "" : "’s inbox"}` });
    void refreshDevices().catch(() => {});
    return result;
  } catch (error) {
    os.notify({ level: "error", message: error.message });
    return null;
  }
}

/** "Send to a PC" for a file or folder on this PC: one PC sends straight away, several open a picker. */
export function SendToPc({ path, devices, size = "sm" }) {
  const anchor = useRef(null);
  const [open, setOpen] = useState(false);
  if (!devices.length || !path) return null;
  const one = devices.length === 1 ? devices[0] : null;
  return (
    <>
      <Button ref={anchor} size={size} icon={ArrowUpFromLine} onClick={() => (one ? void sendTo(one, path) : setOpen(true))}
        title={one ? `Copy to ${one.name}’s inbox` : "Copy to another PC"}>
        {one ? `Send to ${one.name}` : "Send to a PC"}
      </Button>
      <Popover anchor={anchor} open={open} onClose={() => setOpen(false)} placement="top-end" label="Send to a PC">
        <div className="nx-menu">
          {devices.map(device => (
            <button key={device.id} type="button" className="nx-menu-item" disabled={!device.online}
              onClick={() => { setOpen(false); void sendTo(device, path); }}>
              <Icon as={Laptop} size={14} /><span>{device.name}{device.online ? "" : " (offline)"}</span>
            </button>
          ))}
        </div>
      </Popover>
    </>
  );
}

// ---- transfers strip ------------------------------------------------------------------------------

const RECENT_MS = 10 * 60 * 1000;

function TransferRow({ transfer, onShow }) {
  const [working, setWorking] = useState(false);
  const act = async op => {
    setWorking(true);
    try { await devicesCall(`transfer.${op}`, { id: transfer.id }); await refreshDevices(); }
    catch (error) { os.notify({ level: "error", message: error.message }); }
    finally { setWorking(false); }
  };
  const fraction = transferFraction(transfer);
  const take = transfer.direction === "take";
  const where = take ? `from ${transfer.deviceName}` : `to ${transfer.deviceName}`;
  return (
    <li className={`nx-pc-transfer is-${transfer.status}`}>
      <Icon as={take ? ArrowDownToLine : ArrowUpFromLine} size={15} className="nx-pc-transfer-dir" />
      <div className="nx-pc-transfer-text">
        <div className="nx-pc-transfer-name"><strong title={transfer.from}>{transfer.name || nameOf(transfer.from)}</strong><span>{where}</span></div>
        {isActive(transfer) ? (
          <div className="nx-pc-bar" role="progressbar" aria-label={`${transfer.name} progress`} aria-valuemin={0} aria-valuemax={100}
            aria-valuenow={fraction == null ? undefined : Math.round(fraction * 100)}>
            <span className={fraction == null ? "is-unknown" : ""} style={fraction == null ? undefined : { transform: `scaleX(${fraction})` }} />
          </div>
        ) : null}
        <span className="nx-pc-transfer-line">{transferLine(transfer)}</span>
      </div>
      <div className="nx-pc-transfer-actions">
        {transfer.status === "running" || transfer.status === "queued" ? <IconButton size="sm" icon={Pause} label="Pause" disabled={working} onClick={() => void act("pause")} /> : null}
        {transfer.status === "paused" || transfer.status === "failed" ? <IconButton size="sm" icon={Play} label={transfer.status === "failed" ? "Try again from where it stopped" : "Resume"} disabled={working} onClick={() => void act("resume")} /> : null}
        {isActive(transfer) || transfer.status === "failed" ? <IconButton size="sm" icon={X} label="Cancel" disabled={working} onClick={() => void act("cancel")} /> : null}
        {transfer.status === "done" && take && onShow ? <Button size="sm" icon={FolderOpen} onClick={() => onShow(transfer.to)}>Show</Button> : null}
      </div>
    </li>
  );
}

/** Running transfers, plus the ones that finished in the last few minutes. */
export function TransfersStrip({ transfers, onShow }) {
  const [hidden, setHidden] = useState(() => new Set());
  const now = Date.now();
  const shown = (transfers || []).filter(transfer => !hidden.has(transfer.id) && (isActive(transfer)
    || now - Date.parse(transfer.finishedAt || transfer.updatedAt || 0) < RECENT_MS));
  if (!shown.length) return null;
  const running = shown.filter(isActive).length;
  return (
    <section className="nx-pc-transfers" aria-label="Copies between PCs">
      <header>
        <span>{running ? `Copying ${running} ${running === 1 ? "item" : "items"} between PCs` : "Copies between PCs"}</span>
        {!running ? <IconButton size="sm" icon={X} label="Clear finished" onClick={() => setHidden(new Set(shown.map(transfer => transfer.id)))} /> : null}
      </header>
      <ul>{shown.slice(0, 6).map(transfer => <TransferRow key={transfer.id} transfer={transfer} onShow={onShow} />)}</ul>
    </section>
  );
}

// ---- another PC's folders, inside Files ---------------------------------------------------------

const KIND_ICONS = { folder: Folder, image: FileImage, pdf: FileText, notes: NotebookPen, text: FileText };

function RemoteLook({ device, item, info, onTake, takeLabel, onClose }) {
  if (!item) return null;
  const kind = item.kind === "folder" ? "folder" : item.openWith;
  return (
    <aside className="nx-files-look nx-scroll" aria-label={`Quick look: ${item.name}`}>
      <div className="nx-files-lookhead">
        <strong title={item.name}>{item.name}</strong>
        <IconButton size="sm" icon={X} label="Close quick look" onClick={onClose} />
      </div>
      <div className="nx-files-lookbody">
        {kind === "image" ? <img src={deviceRawUrl(device.id, item.path)} alt={item.name} /> : null}
        {(kind === "text" || kind === "notes") && info?.preview != null ? <pre>{info.preview}{info.previewTruncated ? "\n…" : ""}</pre> : null}
        {(kind === "text" || kind === "notes") && !info ? <Spinner size={14} /> : null}
        {!["image", "text", "notes"].includes(kind) ? <div className="nx-files-lookicon"><Icon as={KIND_ICONS[kind] || File} size={36} /></div> : null}
      </div>
      <dl className="nx-files-facts">
        {item.kind === "file" ? <><dt>Size</dt><dd>{formatSize(item.size)}</dd></> : <><dt>Items</dt><dd>{info?.items ?? "…"}</dd></>}
        <dt>Changed</dt><dd>{item.modified ? new Date(item.modified).toLocaleString() : "—"}</dd>
        <dt>On</dt><dd>{device.name}</dd>
        <dt>Where</dt><dd className="nx-files-where" title={item.path}>{parentOf(item.path)}
          <button type="button" aria-label="Copy path" title="Copy path" onClick={() => void navigator.clipboard?.writeText(item.path)}><Icon as={Copy} size={12} /></button>
        </dd>
      </dl>
      <div className="nx-files-lookactions">
        <Button size="sm" variant="outline" icon={ArrowDownToLine} onClick={onTake}>{takeLabel}</Button>
      </div>
    </aside>
  );
}

/**
 * One pane showing a paired PC's shared folders. Rows drag out (Take) and
 * this PC's files drop in (Send). `localFolder` is where Take lands when the
 * two PCs are side by side; otherwise Take uses this PC's Downloads.
 */
export function RemotePane({ device, path, onPath, split, onToggleSplit, onClose, localFolder }) {
  const [listing, setListing] = useState({ status: "loading", entries: [], crumbs: [] });
  const [selected, setSelected] = useState(null);
  const [info, setInfo] = useState(null);
  const [look, setLook] = useState(false);
  const [filter, setFilter] = useState("");
  const [over, setOver] = useState(null); // folder path (or "" for this pane) under a drag
  const ticket = useRef(0);

  const load = useCallback(async () => {
    const mine = ++ticket.current;
    setListing(current => ({ ...current, status: "loading" }));
    try {
      const result = await devicesCall("files.list", { device: device.id, ...(path ? { path } : {}) });
      if (mine === ticket.current) setListing({ status: "ready", ...result });
    } catch (error) {
      if (mine === ticket.current) setListing({ status: "error", error: error.message, code: error.status, entries: [], crumbs: [] });
    }
  }, [device.id, path]);
  useEffect(() => { setSelected(null); setFilter(""); void load(); }, [load]);
  // A Send to this PC that just finished shows up without a manual refresh.
  const { data } = useDevices();
  const sent = (data?.transfers || []).filter(transfer => transfer.device === device.id && transfer.direction === "send" && transfer.status === "done").length;
  useEffect(() => { if (sent) void load(); }, [sent]); // eslint-disable-line react-hooks/exhaustive-deps

  const rows = useMemo(() => {
    if (!path) return (listing.places || []).map(place => ({ name: place.name, path: place.path, kind: "folder", place: place.kind, write: place.write }));
    const needle = filter.trim().toLowerCase();
    return needle ? listing.entries.filter(entry => entry.name.toLowerCase().includes(needle)) : listing.entries;
  }, [listing, path, filter]);
  const item = rows.find(row => row.path === selected) || null;

  useEffect(() => {
    if (!item || item.kind === "folder" && !look) { setInfo(null); return undefined; }
    let cancelled = false;
    setInfo(null);
    const timer = setTimeout(() => {
      devicesCall("files.stat", { device: device.id, path: item.path, preview: item.openWith === "text" || item.openWith === "notes" })
        .then(result => { if (!cancelled) setInfo(result); }).catch(() => {});
    }, 140);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [item, look, device.id]);

  const place = listing.place || null;
  const inbox = device.theyShare?.inbox;
  const landing = sendTarget(device, place, path);
  const landingText = landing ? `into ${nameOf(landing) || landing}` : `into ${device.name}’s inbox`;
  const take = entry => void takeFrom(device, entry.path, split ? localFolder : undefined);
  const takeLabel = split && localFolder ? `Take to ${nameOf(localFolder) || localFolder}` : "Take to this PC";

  const dropOn = (event, folder) => {
    event.preventDefault();
    setOver(null);
    const source = dragSource(event.dataTransfer);
    if (dropIntent(source, { device: device.id, path: folder || path || inbox }) !== "send") return;
    const target = folder ? sendTarget(device, folder === path ? place : { kind: "shared", write: place?.write }, folder) : landing;
    void sendTo(device, source.path, target).then(result => { if (result) setTimeout(() => void load(), 600); });
  };
  const dragOver = (event, key) => {
    if (!hasDrag(event.dataTransfer, LOCAL_DRAG)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setOver(key);
  };

  const offline = !device.online;
  const crumbs = [{ name: device.name, path: null }, ...(path ? listing.crumbs || [] : [])];

  return (
    <section className={`nx-files-main nx-pc-pane${over === "" ? " is-dropping" : ""}`} aria-label={`${device.name}’s files`}
      onDragOver={event => dragOver(event, "")} onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOver(null); }}
      onDrop={event => dropOn(event, null)}>
      <div className="nx-docs-bar">
        <span className="nx-pc-badge" title={deviceStatusText(device)}><StatusDot tone={device.online ? "green" : "idle"} /><Icon as={Laptop} size={14} /></span>
        <ol className="nx-files-crumbs" aria-label="Folder path">
          {crumbs.map((crumb, index) => (
            <li key={crumb.path || "root"}>
              {index ? <Icon as={ChevronRight} size={12} /> : null}
              <button type="button" onClick={() => onPath(crumb.path)} aria-current={(crumb.path || null) === (path || null) ? "page" : undefined} title={crumb.path || device.name}>{crumb.name}</button>
            </li>
          ))}
        </ol>
        <span className="nx-docs-spacer" />
        {path ? (
          <label className="nx-docs-search is-small">
            <Icon as={Search} size={13} />
            <input value={filter} onChange={event => setFilter(event.target.value)} placeholder="Filter" aria-label={`Filter this folder on ${device.name}`} />
          </label>
        ) : null}
        <IconButton icon={RefreshCw} label="Refresh" onClick={() => void load()} />
        <IconButton icon={Columns2} label={split ? "Show only this PC’s folders" : "Side by side with this PC"} active={split} onClick={onToggleSplit} />
        <IconButton icon={X} label={`Close ${device.name}`} onClick={onClose} />
      </div>

      <div className="nx-files-body">
        <div className="nx-files-list nx-scroll" role="listbox" aria-label={`${device.name}: ${path || "shared folders"}`} tabIndex={0}>
          {listing.status === "loading" && !rows.length ? <div className="nx-docs-empty"><Spinner size={14} /><p>Asking {device.name}…</p></div> : null}
          {listing.status === "error" ? (
            <div className="nx-docs-empty">
              <Icon as={Laptop} size={22} />
              <strong>{offline ? `${device.name} is offline right now` : `${device.name} didn't answer`}</strong>
              <p>{offline ? "Turn it on and open Neyvia there; its folders show up here again." : listing.error}</p>
              <div className="nx-ac-actions">
                <Button size="sm" variant="outline" icon={RefreshCw} onClick={() => void load()}>Try again</Button>
                {listing.code === 401 || listing.code === 403 ? <Button size="sm" icon={Link2} onClick={() => os.showPane("accounts", "other-pcs")}>Pair again</Button> : null}
              </div>
            </div>
          ) : null}
          {listing.status === "ready" && !rows.length ? (
            <div className="nx-docs-empty"><Icon as={Folder} size={22} />
              <strong>{path ? (filter ? "Nothing matches" : "This folder is empty") : `${device.name} shares no folders yet`}</strong>
              {!path ? <p>On {device.name}, open Accounts › Other PCs and choose what this PC can see.</p> : null}
            </div>
          ) : null}
          {rows.map(entry => {
            const glyph = entry.place === "inbox" ? Inbox : entry.kind === "folder" ? Folder : KIND_ICONS[entry.openWith] || File;
            return (
              <div key={entry.path} role="option" aria-selected={selected === entry.path} data-path={entry.path}
                className={`nx-files-row${selected === entry.path ? " is-on" : ""}${entry.hidden ? " is-hidden" : ""}${over === entry.path ? " is-drop" : ""}`}
                draggable
                onDragStart={event => {
                  event.dataTransfer.setData(REMOTE_DRAG, JSON.stringify({ device: device.id, path: entry.path, name: entry.name }));
                  event.dataTransfer.effectAllowed = "copy";
                }}
                {...(entry.kind === "folder" ? {
                  onDragOver: event => { event.stopPropagation(); dragOver(event, entry.path); },
                  onDrop: event => { event.stopPropagation(); dropOn(event, entry.path); },
                } : {})}
                onClick={() => setSelected(entry.path)}
                onDoubleClick={() => (entry.kind === "folder" ? onPath(entry.path) : (setSelected(entry.path), setLook(true)))}
                onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); if (entry.kind === "folder") onPath(entry.path); else setLook(true); } }}
                tabIndex={-1} title={entry.path}>
                <Icon as={glyph} size={15} className={`nx-files-glyph is-${entry.kind === "folder" ? "folder" : entry.openWith}`} />
                <span className="nx-files-name">{entry.name}{entry.place === "inbox" ? <span className="nx-pc-tag">Inbox</span> : entry.write ? <span className="nx-pc-tag">Can save</span> : null}</span>
                <span className="nx-files-time">{entry.modified ? ago(entry.modified) : ""}</span>
                <span className="nx-files-size">{entry.kind === "file" ? formatSize(entry.size) : ""}</span>
              </div>
            );
          })}
          {listing.truncated ? <p className="nx-files-more">Showing the first 2,000 items.</p> : null}
          {over === "" ? <div className="nx-pc-dropnote" aria-hidden="true"><Icon as={ArrowUpFromLine} size={16} />Drop to send {landingText}</div> : null}
        </div>
        {look && item ? (
          <RemoteLook device={device} item={item} info={info} onTake={() => take(item)} takeLabel={takeLabel} onClose={() => setLook(false)} />
        ) : null}
      </div>

      {item && !look ? (
        <div className="nx-files-selbar">
          <span title={item.path}>{item.name}</span>
          <span className="nx-docs-spacer" />
          {item.kind === "file" ? <Button size="sm" icon={FileText} onClick={() => setLook(true)}>Quick look</Button> : null}
          <Button size="sm" variant="outline" icon={ArrowDownToLine} onClick={() => take(item)}>{takeLabel}</Button>
        </div>
      ) : (
        <p className="nx-pc-hint">
          {split ? "Drag between the two sides to copy. Nothing is moved or deleted on either PC." : `Drag files here from this PC to send them ${landingText}.`}
          {inbox && !landing ? <> Its inbox is <code title={inbox}>{nameOf(inbox) || inbox}</code>.</> : null}
        </p>
      )}
    </section>
  );
}

/** The "Other PCs" part of the Files places tree. */
export function OtherPcsTree({ data, current, onOpen }) {
  const [over, setOver] = useState(null);
  const devices = (data?.devices || []).filter(device => device.status === "paired" || device.status === "waiting");
  return (
    <div className="nx-pc-tree">
      <div className="nx-pc-treehead">Other PCs</div>
      <ul>
        {devices.map(device => {
          const paired = device.status === "paired";
          return (
            <li key={device.id}>
              <button type="button" className={`nx-files-node nx-pc-node${current === device.id ? " is-on" : ""}${over === device.id ? " is-drop" : ""}${paired ? "" : " is-waiting"}`}
                disabled={!paired} title={deviceStatusText(device)} onClick={() => onOpen(device)}
                onDragOver={event => { if (paired && hasDrag(event.dataTransfer, LOCAL_DRAG)) { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; setOver(device.id); } }}
                onDragLeave={() => setOver(null)}
                onDrop={event => { event.preventDefault(); setOver(null); const source = dragSource(event.dataTransfer); if (dropIntent(source, { device: device.id }) === "send") void sendTo(device, source.path); }}>
                <span className="nx-files-nodename"><Icon as={Laptop} size={14} /><span>{device.name}</span></span>
                <StatusDot tone={!paired ? "idle" : device.online ? "green" : "idle"} />
              </button>
            </li>
          );
        })}
      </ul>
      <button type="button" className="nx-pc-add" onClick={() => os.showPane("accounts", "other-pcs")}>
        <Icon as={Link2} size={13} /><span>{devices.length ? "Add or manage PCs" : "Reach another PC"}</span>
      </button>
    </div>
  );
}

// ---- Accounts › Other PCs: pair, approve, what each side shares ---------------------------------

function useAction() {
  const [busyFlag, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async (work, done) => {
    setBusy(true); setError("");
    try { const result = await work(); done?.(result); await refreshDevices().catch(() => {}); return true; }
    catch (failure) { setError(failure?.message || "That didn't work."); return false; }
    finally { setBusy(false); }
  };
  return { busy: busyFlag, error, run };
}

/** Pick which of this PC's folders another PC can see, which it can save into, and its inbox. */
function ShareForm({ initial, submitLabel, onSubmit, onCancel, busy: working }) {
  const [places, setPlaces] = useState(null);
  const [folders, setFolders] = useState(() => initial?.folders || null);
  const [inbox, setInbox] = useState(initial?.inbox || "");
  const [anywhere, setAnywhere] = useState(Boolean(initial?.writeAnywhere));
  useEffect(() => {
    let cancelled = false;
    filesCall("list", {}).then(result => {
      if (cancelled) return;
      setPlaces(result.places || []);
      setFolders(current => current || (result.places || []).filter(place => place.kind === "home").map(place => ({ path: place.path, name: place.name, write: false })));
    }).catch(() => !cancelled && setPlaces([]));
    return () => { cancelled = true; };
  }, []);
  const chosen = new Map((folders || []).map(folder => [folder.path.toLowerCase(), folder]));
  const options = [...(places || []), ...(folders || []).filter(folder => !(places || []).some(place => place.path.toLowerCase() === folder.path.toLowerCase()))];
  const toggle = (place, on) => setFolders(current => (on ? [...(current || []), { path: place.path, name: place.name, write: false }] : (current || []).filter(folder => folder.path.toLowerCase() !== place.path.toLowerCase())));
  const setWrite = (place, write) => setFolders(current => (current || []).map(folder => (folder.path.toLowerCase() === place.path.toLowerCase() ? { ...folder, write } : folder)));
  return (
    <form className="nx-pc-share" onSubmit={event => { event.preventDefault(); onSubmit({ folders: (folders || []).map(({ path, write }) => ({ path, write: Boolean(write) })), inbox: inbox.trim() || undefined, writeAnywhere: anywhere }); }}>
      <fieldset>
        <legend>Folders it can see</legend>
        {places == null ? <Spinner size={13} /> : options.map(place => {
          const on = chosen.get(place.path.toLowerCase());
          return (
            <div key={place.path} className="nx-pc-share-row">
              <label><input type="checkbox" checked={Boolean(on)} onChange={event => toggle(place, event.target.checked)} /><span title={place.path}>{place.name || nameOf(place.path)}</span></label>
              {on ? <label className="nx-pc-share-write"><input type="checkbox" checked={Boolean(on.write)} onChange={event => setWrite(place, event.target.checked)} /><span>can save here</span></label> : null}
            </div>
          );
        })}
      </fieldset>
      <label className="nx-ac-field">
        <span>Inbox for files it sends</span>
        <input value={inbox} onChange={event => setInbox(event.target.value)} placeholder="Downloads\Neyvia inbox (default)" spellCheck={false} />
      </label>
      <label className="nx-pc-share-row"><input type="checkbox" checked={anywhere} onChange={event => setAnywhere(event.target.checked)} />
        <span>Let it save into any folder it can see (otherwise only the inbox and folders marked “can save”)</span></label>
      <div className="nx-ac-actions">
        <Button type="submit" variant="primary" size="sm" disabled={working}>{submitLabel}</Button>
        {onCancel ? <Button size="sm" onClick={onCancel}>Cancel</Button> : null}
      </div>
    </form>
  );
}

function RequestCard({ request }) {
  const action = useAction();
  const [choosing, setChoosing] = useState(false);
  return (
    <li className="nx-ac-confirm nx-pc-request">
      <p><strong>{request.fromName}</strong> wants to reach this PC's files.</p>
      <p className="nx-pc-code">Check the code matches the one on {request.fromName}: <code>{request.code}</code></p>
      {choosing ? (
        <ShareForm submitLabel={`Approve ${request.fromName}`} busy={action.busy} onCancel={() => setChoosing(false)}
          onSubmit={share => void action.run(() => devicesCall("approve", { request: request.id, ...share }), () => os.notify({ level: "success", message: `${request.fromName} is paired.` }))} />
      ) : (
        <div className="nx-ac-actions">
          <Button variant="primary" size="sm" disabled={action.busy} onClick={() => setChoosing(true)}>Choose folders and approve</Button>
          <Button size="sm" disabled={action.busy} onClick={() => void action.run(() => devicesCall("deny", { request: request.id }))}>Deny</Button>
          {request.expiresAt ? <span className="nx-pc-muted">Expires at {new Date(request.expiresAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span> : null}
        </div>
      )}
      {action.error ? <p className="nx-ac-error" role="alert">{action.error}</p> : null}
    </li>
  );
}

// The 4-digit code a pair request showed, kept so the row can repeat it while waiting.
const pairCodes = new Map();
const remember = result => { if (result?.device?.id && result.code) pairCodes.set(result.device.id, result.code); return result; };

function DeviceRow({ device }) {
  const action = useAction();
  const [mode, setMode] = useState("");
  const status = device.status;
  const pairCode = device.code || pairCodes.get(device.id);
  return (
    <li className="nx-ac-person">
      <div className="nx-ac-person-row">
        <span className="nx-ac-device-icon"><Icon as={device.os?.toLowerCase().includes("mac") ? Laptop : Monitor} size={17} /></span>
        <span className="nx-ac-device-text">
          <strong>{device.name}<StatusDot tone={status === "paired" ? (device.online ? "green" : "idle") : status === "waiting" ? "live" : "idle"} /></strong>
          <span>{deviceStatusText(device)}{device.pairedAt ? ` · paired ${ago(device.pairedAt)}` : ""}</span>
          {status === "paired" ? <span>They share: {shareSummary(device.theyShare)} · You share: {shareSummary(device.iShare)}</span> : null}
          {status === "waiting" && pairCode ? <span>Code on their screen: <code>{pairCode}</code></span> : null}
          {device.error ? <span className="nx-pc-muted">{device.error}</span> : null}
        </span>
        <span className="nx-ac-person-tools">
          {status === "paired" ? <>
            <Button size="sm" icon={FolderOpen} disabled={!device.online} onClick={() => os.openApp("files", "documents", pcTarget(device.id))}>Open</Button>
            <Button size="sm" onClick={() => setMode(mode === "share" ? "" : "share")}>What you share</Button>
            <Button size="sm" icon={Unlink} aria-label={`Unpair ${device.name}`} onClick={() => setMode("revoke")} />
          </> : null}
          {status === "available" ? <Button size="sm" variant="primary" icon={Link2} disabled={action.busy}
            onClick={() => void action.run(() => devicesCall("pair", { device: device.id }).then(remember), result => os.notify({ level: "info", message: `Asked ${device.name}. Code ${result.code}: approve it there.` }))}>Pair</Button> : null}
          {status === "waiting" ? <Button size="sm" disabled={action.busy} onClick={() => void action.run(() => devicesCall("pair.cancel", { device: device.id }))}>Cancel</Button> : null}
        </span>
      </div>
      {mode === "share" ? (
        <div className="nx-ac-confirm">
          <ShareForm initial={device.iShare} submitLabel="Save" busy={action.busy} onCancel={() => setMode("")}
            onSubmit={share => void action.run(() => devicesCall("shares.set", { device: device.id, ...share }), () => { setMode(""); os.notify({ level: "success", message: `Saved what ${device.name} can see.` }); })} />
        </div>
      ) : null}
      {mode === "revoke" ? (
        <div className="nx-ac-confirm is-danger">
          <p>Unpair {device.name}? Neither PC can reach the other's files until you pair again. Files already copied stay.</p>
          <div className="nx-ac-actions">
            <Button variant="warn" size="sm" icon={Unlink} disabled={action.busy}
              onClick={() => void action.run(() => devicesCall("revoke", { device: device.id }), () => { setMode(""); os.notify({ level: "info", message: `${device.name} is unpaired.` }); })}>Unpair</Button>
            <Button size="sm" onClick={() => setMode("")}>Keep</Button>
          </div>
        </div>
      ) : null}
      {action.error ? <p className="nx-ac-error" role="alert">{action.error}</p> : null}
    </li>
  );
}

function AddByAddress() {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const action = useAction();
  if (!open) return <button type="button" className="nx-pc-link" onClick={() => setOpen(true)}>Add a PC by its address</button>;
  return (
    <form className="nx-ac-inline" onSubmit={event => {
      event.preventDefault();
      void action.run(() => devicesCall("pair", { url: url.trim() }).then(remember), result => { setOpen(false); setUrl(""); os.notify({ level: "info", message: `Asked ${result.device?.name || "that PC"}. Code ${result.code}: approve it there.` }); });
    }}>
      <input value={url} onChange={event => setUrl(event.target.value)} placeholder="https://other-pc.your-tailnet.ts.net:8443" aria-label="The other PC's Neyvia address" spellCheck={false} autoFocus />
      <Button type="submit" size="sm" variant="primary" disabled={action.busy || !url.trim()}>Pair</Button>
      <Button size="sm" onClick={() => setOpen(false)}>Cancel</Button>
      {action.error ? <p className="nx-ac-error" role="alert">{action.error}</p> : null}
    </form>
  );
}

/** Accounts card: the PCs this one can reach, and the ones asking to reach it. */
export function OtherPcsCard({ focus = false }) {
  const { data, status, error } = useDevices();
  const ref = useRef(null);
  const [finding, setFinding] = useState(false);
  useEffect(() => { if (focus) ref.current?.scrollIntoView({ block: "start", behavior: "smooth" }); }, [focus, status]);
  const find = async () => {
    setFinding(true);
    try { await refreshDevices("discover"); } catch (failure) { os.notify({ level: "error", message: failure.message }); } finally { setFinding(false); }
  };
  const devices = (data?.devices || []).filter(device => device.status !== "asked-you");
  const order = { paired: 0, waiting: 1, available: 2, "not-neyvia": 3, offline: 4 };
  const sorted = [...devices].sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9) || a.name.localeCompare(b.name));
  return (
    <section ref={ref} className="nx-ac-card" id="other-pcs">
      <header className="nx-ac-head">
        <div>
          <h3>Other PCs</h3>
          <p>Your other computers with Neyvia on your private network. Pair once, then take and send their files from Files.</p>
        </div>
        <Button variant="outline" size="sm" icon={finding ? undefined : RefreshCw} disabled={finding} onClick={() => void find()}>
          {finding ? <><Spinner size={12} /> Looking…</> : "Find PCs"}
        </Button>
      </header>
      {status === "loading" && !data ? <Spinner size={14} /> : null}
      {status === "error" && !data ? <p className="nx-ac-error" role="alert">{error}</p> : null}
      {data?.tailnet && data.tailnet !== "ok" ? (
        <p className="nx-ac-note">{data.tailnet === "missing" ? "Tailscale isn't installed on this PC, so other PCs can't be found." : "Tailscale is stopped on this PC, so other PCs can't be found."} You can still add one by its address.</p>
      ) : null}
      {data?.requests?.length ? <ul className="nx-ac-list nx-pc-requests">{data.requests.map(request => <RequestCard key={request.id} request={request} />)}</ul> : null}
      {sorted.length ? (
        <ul className="nx-ac-list">{sorted.map(device => <DeviceRow key={device.id} device={device} />)}</ul>
      ) : data ? <p className="nx-ac-note">No other PCs yet. Press Find PCs to look on your network.</p> : null}
      <AddByAddress />
      <button type="button" className="nx-pc-link" onClick={() => os.showPane("preview", "remote")}>Use an app on another PC live, or let one use an app here</button>
    </section>
  );
}
