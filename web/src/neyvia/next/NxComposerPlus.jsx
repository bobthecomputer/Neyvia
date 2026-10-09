import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { FileText, GitBranch, ImagePlus, Minimize2, Paperclip, Plus, ShieldAlert, Sparkles, Wrench, X } from "lucide-react";

import { Button, Icon, IconButton, Popover, Spinner, useRovingKeys } from "./nxPrimitives.jsx";
import { callNx, isDesktopApp } from "./nxApi.js";
import { approveUiRequest, callTool } from "./nxBus.js";
import {
  IMAGE_TYPES, argumentSkeleton, attachToDraft, createDraftStore, filterTools, isUiTool, parseArguments, stripDataUrl,
  toolMutates, toolScope,
} from "./nxComposerModel.js";

// The composer's + menu: images (picked, pasted or dropped) and a manual
// runner for Neyvia's own tools. Image bytes live in memory only; drafts in
// localStorage stay text.

export const imageDrafts = createDraftStore();
// Other files (PDF, logs, archives…): sent as base64, saved on the PC, named in the message.
export const fileDrafts = createDraftStore();
const MAX_FILES = 10;
const MAX_FILE_BYTES = 25 * 1024 * 1024;

export function useFileDraft(sessionId) {
  const files = useSyncExternalStore(fileDrafts.subscribe, () => fileDrafts.get(sessionId));
  const update = useCallback(next => fileDrafts.update(sessionId, next), [sessionId]);
  return [files, update];
}

const sizeLabel = bytes => (bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);

/** Any picked, pasted or dropped files: images to the image draft, the rest to the file draft. Returns a notice or "". */
export async function attachAny(files, sessionId) {
  const list = [...(files || [])];
  const images = list.filter(file => IMAGE_TYPES.includes(file.type));
  const others = list.filter(file => !IMAGE_TYPES.includes(file.type));
  const notices = [];
  if (images.length) {
    const notice = await attachFiles(images, sessionId);
    if (notice) notices.push(notice);
  }
  const current = fileDrafts.get(sessionId);
  const room = Math.max(0, MAX_FILES - current.length);
  const accepted = [];
  for (const file of others) {
    if (file.size > MAX_FILE_BYTES) { notices.push(`${file.name} is larger than 25 MB.`); continue; }
    if (accepted.length >= room) { notices.push(`Attach at most ${MAX_FILES} files.`); break; }
    const url = await readAsDataUrl(file);
    accepted.push({ id: `file-${Date.now()}-${accepted.length}`, name: file.name || "file", size: file.size, data: stripDataUrl(url) });
  }
  if (accepted.length) fileDrafts.update(sessionId, existing => [...existing, ...accepted]);
  return notices.join(" ");
}

export function FileTray({ files, onRemove, disabled }) {
  if (!files.length) return null;
  return (
    <ul className="nx-filetray" aria-label="Files to send">
      {files.map(file => (
        <li key={file.id} className="nx-filechip">
          <Icon as={FileText} size={13} />
          <span className="nx-filechip-name" title={file.name}>{file.name}</span>
          <span className="nx-filechip-size">{sizeLabel(file.size)}</span>
          <button type="button" aria-label={`Remove ${file.name}`} disabled={disabled} onClick={() => onRemove(file.id)}><Icon as={X} size={12} /></button>
        </li>
      ))}
    </ul>
  );
}

/** The paperclip: pick any files from this device. */
export function AttachButton({ disabled, onFiles, inputRef }) {
  const own = useRef(null);
  const input = inputRef || own;
  return (
    <>
      <IconButton icon={Paperclip} label="Attach files" disabled={disabled} onClick={() => input.current?.click()} />
      <input ref={input} type="file" multiple hidden onChange={event => { onFiles(event.target.files); event.target.value = ""; }} />
    </>
  );
}

/** Compact the conversation now (Claude Code /compact, Codex compact). */
export function CompactButton({ available, reason, busy, onCompact }) {
  return (
    <IconButton icon={busy ? undefined : Minimize2} label={available ? "Compact the conversation now" : reason || "This chat can't be compacted from here right now"}
      disabled={!available || busy} onClick={onCompact} className="nx-compact-btn">
      {busy ? <Spinner size={12} /> : null}
    </IconButton>
  );
}

/** Images waiting to be sent, per chat, kept across chat switches but never written to disk. */
export function useImageDraft(sessionId) {
  const images = useSyncExternalStore(imageDrafts.subscribe, () => imageDrafts.get(sessionId));
  const update = useCallback(next => imageDrafts.update(sessionId, next), [sessionId]);
  return [images, update];
}

const readAsDataUrl = file => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result || ""));
  reader.onerror = () => reject(reader.error || new Error("The image couldn't be read."));
  reader.readAsDataURL(file);
});

let pasted = 0;
/** Turn picked, pasted or dropped files into {id, mime, name, data, url}. */
export async function readImages(files) {
  const out = [];
  for (const file of files) {
    const url = await readAsDataUrl(file);
    pasted += 1;
    const name = file.name && file.name !== "image.png" ? file.name : `Pasted image ${pasted}.${(file.type.split("/")[1] || "png").replace("jpeg", "jpg")}`;
    out.push({ id: `img-${Date.now()}-${pasted}`, mime: file.type, name, data: stripDataUrl(url), url });
  }
  return out;
}

/** Attach files to one chat's in-memory draft; returns why any were refused ("" when all fit). */
export const attachFiles = (files, sessionId) => attachToDraft(imageDrafts, sessionId, files, readImages);

export function AttachmentTray({ images, onRemove, disabled }) {
  if (!images.length) return null;
  return (
    <ul className="nx-tray" aria-label="Images to send">
      {images.map(image => (
        <li key={image.id} className="nx-tray-item">
          <img src={image.url} alt={image.name} />
          <button type="button" className="nx-tray-remove" aria-label={`Remove ${image.name}`} title={`Remove ${image.name}`}
            disabled={disabled} onClick={() => onRemove(image.id)}><Icon as={X} size={12} /></button>
        </li>
      ))}
    </ul>
  );
}

export function PlusMenu({ appName, imagesUnavailable, disabled, onFiles, onOpenTools, onAttach, compact, branch, amplify }) {
  const anchor = useRef(null);
  const listRef = useRef(null);
  const fileInput = useRef(null);
  const [open, setOpen] = useState(false);
  const onKeyDown = useRovingKeys(listRef);
  return (
    <>
      <IconButton ref={anchor} icon={Plus} label="More: images, files, tools, compact, branch" className="nx-plus" disabled={disabled && !branch}
        aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)} />
      <input ref={fileInput} type="file" accept={IMAGE_TYPES.join(",")} multiple hidden
        onChange={event => { onFiles(event.target.files); event.target.value = ""; }} />
      <Popover anchor={anchor} open={open} onClose={() => setOpen(false)} width={300} label="Add to this message">
        <div className="nx-picker" role="menu" ref={listRef} onKeyDown={onKeyDown}>
          <button type="button" role="menuitem" className="nx-picker-row" aria-disabled={imagesUnavailable ? true : undefined}
            onClick={() => { if (imagesUnavailable) return; setOpen(false); fileInput.current?.click(); }}>
            <Icon as={ImagePlus} size={15} />
            <span className="nx-picker-main"><strong>Add images</strong>
              <span>{imagesUnavailable || "PNG, JPEG, WebP or GIF, up to 6. Paste or drop works too."}</span></span>
          </button>
          <button type="button" role="menuitem" className="nx-picker-row" onClick={() => { setOpen(false); onAttach(); }}>
            <Icon as={Paperclip} size={15} />
            <span className="nx-picker-main"><strong>Attach files</strong>
              <span>Any file, up to 25 MB each. It's saved on the PC and {appName} opens it.</span></span>
          </button>
          {compact ? (
            <button type="button" role="menuitem" className="nx-picker-row" aria-disabled={compact.available ? undefined : true}
              onClick={() => { if (!compact.available) return; setOpen(false); compact.onCompact(); }}>
              <Icon as={Minimize2} size={15} />
              <span className="nx-picker-main"><strong>Compact now</strong>
                <span>{compact.available ? "Summarise the conversation so far to free up context." : compact.reason}</span></span>
            </button>
          ) : null}
          {branch ? (
            <button type="button" role="menuitem" className="nx-picker-row" onClick={() => { setOpen(false); branch.onToggle(); }}>
              <Icon as={GitBranch} size={15} />
              <span className="nx-picker-main"><strong>{branch.on ? "Cancel the branch" : "Continue as a branch"}</strong>
                <span>Your next message starts a new chat with this whole history; this one stays as it is.</span></span>
            </button>
          ) : null}
          {amplify ? (
            <button type="button" role="menuitem" className="nx-picker-row" onClick={() => { setOpen(false); amplify.onToggle(); }}>
              <Icon as={Sparkles} size={15} />
              <span className="nx-picker-main"><strong>{amplify.on ? "Turn off prompt rewriting" : "Turn on prompt rewriting"}</strong>
                <span>{amplify.on ? "Messages go exactly as typed, with no card." : "Your message gets a goal, checks and assumptions you can edit before it goes."}</span></span>
            </button>
          ) : null}
          <button type="button" role="menuitem" className="nx-picker-row" onClick={() => { setOpen(false); onOpenTools(); }}>
            <Icon as={Wrench} size={15} />
            <span className="nx-picker-main"><strong>Run a Neyvia tool…</strong>
              <span>Neyvia's own tools, run by you. {appName}'s built-in tools aren't listed here.</span></span>
          </button>
        </div>
      </Popover>
    </>
  );
}

const MUTABILITY = {
  read: "Read only", none: "Changes Neyvia", file_write: "Writes files", artifact_write: "Writes records",
  external_write: "Writes outside Neyvia", external_action: "Acts on your PC", process_execute: "Runs programs",
};
const mutabilityLabel = kind => MUTABILITY[kind] || "Changes things";

function show(value) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return text.length > 20000 ? `${text.slice(0, 20000)}\n… (${(text.length - 20000).toLocaleString()} more characters)` : text;
}

/** Pick one of Neyvia's tools, read its schema, and run it only when the person presses Run. */
export function ToolRunner({ session, appName, onClose }) {
  const desktop = isDesktopApp();
  const cwd = session?.cwd || "";
  const catalogRoot = desktop ? null : cwd || null;
  const [catalog, setCatalog] = useState({ status: "loading", tools: [], error: "" });
  const [query, setQuery] = useState("");
  const [name, setName] = useState("");
  const [detail, setDetail] = useState({ status: "idle", data: null, error: "" });
  const [argsText, setArgsText] = useState("{}");
  const [confirmed, setConfirmed] = useState(false);
  const [run, setRun] = useState({ status: "idle" });

  useEffect(() => {
    let alive = true;
    callNx("get_native_tool_catalog_command", catalogRoot ? { root: catalogRoot } : {})
      .then(result => { if (alive) setCatalog({ status: "ready", tools: Array.isArray(result?.tools) ? result.tools : [], error: "" }); })
      .catch(failure => { if (alive) setCatalog({ status: "error", tools: [], error: failure?.message || "Neyvia's tool list couldn't be loaded." }); });
    return () => { alive = false; };
  }, [catalogRoot]);

  const choose = useCallback(tool => {
    setName(tool); setRun({ status: "idle" }); setConfirmed(false);
    setDetail({ status: "loading", data: null, error: "" });
    callNx("get_native_tool_catalog_command", { describe: tool, ...(catalogRoot ? { root: catalogRoot } : {}) })
      .then(data => { setDetail({ status: "ready", data, error: "" }); setArgsText(argumentSkeleton(data?.inputSchema)); })
      .catch(failure => setDetail({ status: "error", data: null, error: failure?.message || "That tool couldn't be described." }));
  }, [catalogRoot]);

  const tool = detail.data;
  const mutates = toolMutates(tool);
  const parsed = parseArguments(argsText);
  const scope = toolScope({ tool: name, cwd, desktop });
  const ready = tool && tool.available !== false && !parsed.error && (!mutates || confirmed) && run.status !== "running";

  const execute = async ({ approved = false } = {}) => {
    if (!tool || parsed.error) return;
    setRun({ status: "running" });
    try {
      if (isUiTool(name)) {
        const data = await callTool(name, parsed.value);
        setRun({ status: "done", receipt: data });
      } else {
        const receipt = await callNx("call_native_tool_command", {
          tool: name, arguments: parsed.value, ...(scope.root ? { root: scope.root } : {}), ...(approved ? { approved: true } : {}),
        });
        if (receipt?.status === "approval_required") setRun({ status: "approval", permission: receipt.requiredPermission || "", receipt });
        else setRun({ status: "done", receipt });
      }
    } catch (failure) {
      if (failure?.data?.status === "approval_required" && failure.data.approvalId) {
        setRun({ status: "approval", approvalId: failure.data.approvalId, receipt: failure.data });
      } else {
        setRun({ status: "error", error: failure?.message || "The tool call didn't reach Neyvia.", receipt: failure?.data || null });
      }
    } finally {
      setConfirmed(false);
    }
  };

  const approve = async () => {
    if (run.approvalId) {
      setRun(current => ({ ...current, approving: true }));
      try {
        await approveUiRequest(run.approvalId);
        setRun({ status: "approved" });
      } catch (failure) {
        setRun(current => ({ ...current, approving: false, approveError: failure?.message || "The approval didn't reach Neyvia." }));
      }
    } else {
      void execute({ approved: true });
    }
  };

  const receipt = run.receipt;
  const failed = run.status === "error" || (run.status === "done" && receipt?.ok === false);
  const visible = filterTools(catalog.tools, query);

  return (
    <section className="nx-toolrun" aria-label="Run a Neyvia tool">
      <header className="nx-toolrun-head">
        <Icon as={Wrench} size={15} />
        <strong>Run a Neyvia tool</strong>
        <IconButton size="sm" icon={X} label="Close tool runner" onClick={onClose} />
      </header>
      <p className="nx-toolrun-note">
        These are Neyvia's own tools, run by you and not by {appName}. {appName}'s built-in tools (its shell, file edits, web) aren't listed here; ask {appName} in the chat for those.
      </p>
      <div className="nx-toolrun-body">
        <div className="nx-toolrun-list">
          <input className="nx-input" type="search" placeholder="Filter tools" aria-label="Filter tools" value={query} onChange={event => setQuery(event.target.value)} />
          {catalog.status === "loading" ? <p className="nx-toolrun-muted"><Spinner size={11} /> Loading tools…</p> : null}
          {catalog.status === "error" ? <p className="nx-pending-error" role="alert">{catalog.error}</p> : null}
          {catalog.status === "ready" ? (
            <div role="listbox" aria-label="Neyvia tools" className="nx-toolrun-options">
              {visible.map(entry => (
                <button key={entry.name} type="button" role="option" aria-selected={entry.name === name}
                  className={`nx-toolrun-option${entry.name === name ? " is-on" : ""}${entry.available === false ? " is-off" : ""}`}
                  onClick={() => choose(entry.name)} title={entry.available === false ? entry.availabilityDetail || "Unavailable" : entry.description}>
                  <code>{entry.name}</code>
                  <span className={`nx-toolrun-tag${toolMutates(entry) ? " is-warn" : ""}`}>{mutabilityLabel(entry.mutability_class)}</span>
                  {entry.available === false ? <span className="nx-toolrun-tag">Unavailable</span> : null}
                </button>
              ))}
              {!visible.length ? <p className="nx-toolrun-muted">No tool matches “{query}”.</p> : null}
            </div>
          ) : null}
        </div>
        <div className="nx-toolrun-detail">
          {!name ? <p className="nx-toolrun-muted">Choose a tool to see what it takes.</p> : null}
          {detail.status === "loading" ? <p className="nx-toolrun-muted"><Spinner size={11} /> Reading {name}…</p> : null}
          {detail.status === "error" ? <p className="nx-pending-error" role="alert">{detail.error}</p> : null}
          {tool ? (
            <>
              <p className="nx-toolrun-title"><code>{tool.name}</code>
                <span className={`nx-toolrun-tag${mutates ? " is-warn" : ""}`}>{mutabilityLabel(tool.mutability_class)}</span>
                {tool.risk_level && tool.risk_level !== "low" ? <span className="nx-toolrun-tag is-warn">Risk: {tool.risk_level}</span> : null}
                {tool.requires_approval ? <span className="nx-toolrun-tag is-warn">Asks first</span> : null}
              </p>
              {tool.description ? <p className="nx-toolrun-desc">{tool.description}</p> : null}
              <p className={`nx-toolrun-scope${desktop && !isUiTool(name) ? " is-warn" : ""}`}>{scope.label}</p>
              {tool.available === false ? <p className="nx-pending-error" role="alert">Unavailable: {tool.availabilityDetail || "Neyvia reports this tool can't run here."}</p> : null}
              <details className="nx-toolrun-schema">
                <summary>Input schema</summary>
                <pre className="nx-pre">{show(tool.inputSchema || {})}</pre>
              </details>
              <label className="nx-toolrun-label" htmlFor="nx-toolrun-args">Arguments (JSON)</label>
              <textarea id="nx-toolrun-args" className="nx-toolrun-args" spellCheck={false} rows={5} value={argsText}
                onChange={event => { setArgsText(event.target.value); setConfirmed(false); }} aria-invalid={Boolean(parsed.error)} />
              {parsed.error ? <p className="nx-pending-error">{parsed.error}</p> : null}
              {mutates ? (
                <label className="nx-toolrun-confirm">
                  <input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />
                  <span>Run <code>{tool.name}</code> anyway. It is marked “{mutabilityLabel(tool.mutability_class)}”, and its changes may not be undoable.</span>
                </label>
              ) : null}
              <div className="nx-pending-actions">
                <Button variant={mutates ? "outline" : "primary"} disabled={!ready} onClick={() => void execute()}>
                  {run.status === "running" ? "Running…" : mutates ? "Run (makes changes)" : "Run"}
                </Button>
              </div>
            </>
          ) : null}
          {run.status === "approval" ? (
            <div className="nx-toolrun-approval" role="alert">
              <p><Icon as={ShieldAlert} size={14} /> Neyvia asks before running <code>{name}</code>{run.permission ? ` (${run.permission})` : ""}.</p>
              {run.approveError ? <p className="nx-pending-error">{run.approveError}</p> : null}
              <div className="nx-pending-actions">
                <Button variant="outline" onClick={() => setRun({ status: "idle" })}>Don't approve</Button>
                <Button variant="primary" disabled={run.approving} onClick={() => void approve()}>{run.approvalId ? "Approve" : "Approve and run"}</Button>
              </div>
            </div>
          ) : null}
          {run.status === "approved" ? <p className="nx-toolrun-muted" role="status">Approved. Press Run to run it now.</p> : null}
          {run.status === "error" ? <p className="nx-pending-error" role="alert">{run.error}</p> : null}
          {run.status === "done" ? (
            <div className={`nx-toolrun-result${failed ? " is-error" : ""}`} role="status">
              <p>{failed ? `Failed${receipt?.status ? ` (${receipt.status})` : ""}: ${receipt?.error || "the tool reported a failure."}` : "Done."}
                {receipt?.duration_ms ? ` ${receipt.duration_ms} ms.` : ""}</p>
              <pre className="nx-pre">{show(receipt?.result ?? receipt ?? {})}</pre>
              {receipt?.receipt_path ? <p className="nx-tool-cwd">Receipt: {receipt.receipt_path}</p> : null}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
