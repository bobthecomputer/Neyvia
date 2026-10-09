import { useCallback, useEffect, useRef, useState } from "react";
import { Archive, Leaf as LeafIcon, ShieldCheck, SlidersHorizontal } from "lucide-react";

import { Button, Icon, IconButton, Popover, Spinner } from "./nxPrimitives.jsx";
import { DEFAULT_CLEANUP, shouldOfferTidy } from "./nxSidebarModel.js";
import { os } from "./nxOsStore.js";
import { callTool } from "./nxBus.js";

// "Seasons" (07 §4): a tidy chip that appears once stale chats pile up, and
// the cleanup rules behind it. Tidying is preview → confirm → undo: the PC
// lists what it would archive (with fresh worktree and job checks), archives
// only after Archive is pressed, and the toast's Undo restores them all.
// Archived chats stay in Fallen leaves; nothing is deleted.

const KEPT_REASON = {
  pinned: "pinned",
  running_or_needs_you: "running or waiting for you",
  recent_failure: "failed today",
  dirty_worktree: "with uncommitted changes",
  running_jobs: "with a program running in the folder",
  safety_unknown: "whose folder couldn't be checked",
  archive_failed: "that didn't archive",
};

export async function saveCleanupPolicy(policy) {
  const receipt = await callTool("neyvia.sidebar.policy", { policy });
  const saved = receipt.result?.policy;
  if (!saved || typeof saved.autoArchive !== "boolean") throw new Error("Cleanup settings were not saved");
  os.setCleanup(saved);
  return saved;
}

/** Put back everything the last tidy archived (also an automatic one), in one call. */
export async function undoLastTidy() {
  try {
    const result = (await callTool("neyvia.sidebar.tidy", { undoLast: true })).result || {};
    const restored = result.restored || [];
    if (restored.length) os.patchMany(restored, { archived: false });
    os.notify({ level: "success", message: restored.length ? `Restored ${restored.length} chat${restored.length === 1 ? "" : "s"}.` : "Nothing to restore: those chats are already back." });
    window.dispatchEvent(new CustomEvent("nx:tidy-changed"));
    return restored;
  } catch (error) {
    os.notify({ level: "warning", message: error?.message || "The chats couldn't be restored." });
    return [];
  }
}

/** The PC's own tidy: preview first, archive on confirm, undo from the toast. */
export function useTidy() {
  const [state, setState] = useState({ status: "idle", candidates: [], protected: [], error: "" });
  const preview = useCallback(async () => {
    setState(current => ({ ...current, status: "checking", error: "" }));
    try {
      const result = (await callTool("neyvia.sidebar.tidy", { dryRun: true })).result || {};
      setState({ status: "preview", candidates: result.candidates || [], protected: result.protected || [], error: "" });
    } catch (error) {
      setState({ status: "error", candidates: [], protected: [], error: error?.message || "The PC didn't answer." });
    }
  }, []);
  const confirm = useCallback(async () => {
    setState(current => ({ ...current, status: "archiving" }));
    try {
      const result = (await callTool("neyvia.sidebar.tidy", { confirmed: true })).result || {};
      const archived = result.archived || [];
      if (archived.length) {
        os.patchMany(archived, { archived: true });
        os.notify({ level: "success", message: `Archived ${archived.length} stale chat${archived.length === 1 ? "" : "s"}. They're in Fallen leaves.`,
          action: { label: "Undo", run: undoLastTidy } });
        window.dispatchEvent(new CustomEvent("nx:tidy-changed"));
      } else os.notify({ level: "info", message: "Nothing was archived: every chat was kept safe." });
      setState({ status: "done", candidates: [], protected: result.protected || [], error: "" });
      return archived;
    } catch (error) {
      setState(current => ({ ...current, status: "error", error: error?.message || "Archiving didn't finish." }));
      return [];
    }
  }, []);
  const reset = useCallback(() => setState({ status: "idle", candidates: [], protected: [], error: "" }), []);
  return { state, preview, confirm, reset };
}

/** What a tidy would do, in plain words, with Archive and Cancel. */
export function TidyPreview({ rows, tidy, onClose, autoStart = true }) {
  const { state, preview, confirm } = tidy;
  const started = useRef(false);
  useEffect(() => {
    if (!autoStart || started.current) return;
    started.current = true;
    void preview();
  }, [autoStart, preview]);
  const title = id => rows.find(row => row.id === id)?.title || "Untitled chat";
  const kept = state.protected.reduce((map, row) => ({ ...map, [row.reason]: (map[row.reason] || 0) + 1 }), {});

  if (state.status === "checking" || state.status === "idle") {
    return <div className="nx-tidy-preview is-busy"><Spinner size={14} /> Checking each chat's folder and running programs…</div>;
  }
  if (state.status === "error") {
    return (
      <div className="nx-tidy-preview">
        <p className="nx-tidy-error" role="alert">{state.error}</p>
        <div className="nx-cleanup-actions"><Button size="sm" variant="ghost" onClick={onClose}>Close</Button><Button size="sm" variant="outline" onClick={() => void preview()}>Try again</Button></div>
      </div>
    );
  }
  if (state.status === "done") {
    return (
      <div className="nx-tidy-preview">
        <p>Done. The chats are in Fallen leaves; restore one there, or put them all back.</p>
        <div className="nx-cleanup-actions">
          <Button size="sm" variant="ghost" onClick={() => { void undoLastTidy(); onClose(); }}>Undo this tidy</Button>
          <Button size="sm" variant="outline" onClick={onClose}>Close</Button>
        </div>
      </div>
    );
  }
  const count = state.candidates.length;
  return (
    <div className="nx-tidy-preview">
      <strong>{count ? `Archive ${count} stale chat${count === 1 ? "" : "s"}?` : "Nothing to tidy"}</strong>
      {count ? (
        <ul className="nx-tidy-list nx-scroll" aria-label="Chats that would be archived">
          {state.candidates.slice(0, 60).map(id => <li key={id}><Icon as={Archive} size={12} /><span>{title(id)}</span></li>)}
          {count > 60 ? <li className="is-more">and {count - 60} more</li> : null}
        </ul>
      ) : <p>No chat is past your cleanup rules right now.</p>}
      {state.protected.length ? (
        <p className="nx-tidy-kept"><Icon as={ShieldCheck} size={12} /> Kept {state.protected.length}: {Object.entries(kept).map(([reason, n]) => `${n} ${KEPT_REASON[reason] || reason.replace(/_/g, " ")}`).join(", ")}.</p>
      ) : null}
      <p className="nx-cleanup-never">Archived chats move to Fallen leaves. You can undo right after, or restore any of them later.</p>
      <div className="nx-cleanup-actions">
        <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
        {count ? <Button size="sm" variant="primary" disabled={state.status === "archiving"} onClick={() => void confirm()}>{state.status === "archiving" ? "Archiving…" : `Archive ${count}`}</Button> : null}
      </div>
    </div>
  );
}

export function TidyChip({ stale, total, policy, rows }) {
  const anchor = useRef(null);
  const [open, setOpen] = useState(false);
  const tidy = useTidy();
  if (!open && !shouldOfferTidy(total, stale.length, policy)) return null;
  const close = () => { setOpen(false); tidy.reset(); };
  return (
    <div className="nx-tidy" role="status">
      <Icon as={LeafIcon} size={14} />
      <span>{stale.length} stale chat{stale.length === 1 ? "" : "s"}</span>
      <button ref={anchor} type="button" className="nx-tidy-go" aria-expanded={open} onClick={() => (open ? close() : setOpen(true))}>Tidy…</button>
      <Popover anchor={anchor} open={open} onClose={close} placement="bottom-end" width={320} label="Tidy the sidebar">
        {open ? <TidyPreview rows={rows} tidy={tidy} onClose={close} /> : null}
      </Popover>
    </div>
  );
}

function DaysField({ label, hint, value, onChange }) {
  return (
    <label className="nx-field">
      <span className="nx-field-label">{label}</span>
      <span className="nx-field-input">
        <input type="number" min={1} max={365} value={value}
          onChange={event => onChange(Math.max(1, Math.min(365, Number(event.target.value) || 1)))} />
        <span>{hint}</span>
      </span>
    </label>
  );
}

/** The rules themselves; used in the sidebar popover and on the Settings page. */
export function CleanupForm({ policy }) {
  const update = async patch => {
    try {
      await saveCleanupPolicy({ ...policy, ...patch });
    } catch (error) { os.notify({ level: "warning", message: error.message || "Cleanup settings could not be saved" }); }
  };
  return (
    <>
      <label className="nx-field nx-cleanup-auto">
        <span className="nx-field-label">Archive stale chats automatically<small>{policy.autoArchive ? "On: checked every minute while Neyvia runs." : "Off: you tidy when you choose."}</small></span>
        <input type="checkbox" role="switch" aria-label="Archive stale chats automatically" checked={policy.autoArchive === true} onChange={event => void update({ autoArchive: event.target.checked })} />
      </label>
      <DaysField label="No folder chats" hint="days inactive" value={policy.noFolderDays} onChange={noFolderDays => update({ noFolderDays })} />
      <DaysField label="Project chats" hint="days inactive" value={policy.projectDays} onChange={projectDays => update({ projectDays })} />
      <DaysField label="Offer to tidy above" hint="chats" value={policy.tidyThreshold} onChange={tidyThreshold => update({ tidyThreshold })} />
      <p className="nx-cleanup-never">Kept safe: pinned, needs you, uncommitted changes and running programs.</p>
      <Button size="sm" variant="ghost" onClick={() => void update(DEFAULT_CLEANUP)}
        disabled={Object.keys(DEFAULT_CLEANUP).every(key => policy[key] === DEFAULT_CLEANUP[key])}>Back to defaults</Button>
    </>
  );
}

export function CleanupSettings({ policy, rows }) {
  const anchor = useRef(null);
  const [open, setOpen] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const tidy = useTidy();
  const close = () => { setOpen(false); setPreviewing(false); tidy.reset(); };
  return (
    <>
      <IconButton ref={anchor} icon={SlidersHorizontal} size="sm" label="Cleanup rules" active={open} onClick={() => (open ? close() : setOpen(true))} />
      <Popover anchor={anchor} open={open} onClose={close} placement="bottom-end" width={300} label="Cleanup rules">
        {previewing ? <TidyPreview rows={rows} tidy={tidy} onClose={close} /> : (
          <div className="nx-cleanup">
            <strong>Cleanup rules</strong>
            <p>Restore archived chats from Fallen leaves.</p>
            <CleanupForm policy={policy} />
            <div className="nx-cleanup-actions">
              <Button size="sm" variant="ghost" onClick={() => { close(); os.showPane("settings", "cleanup"); }}>All settings</Button>
              <Button size="sm" variant="outline" onClick={() => setPreviewing(true)}>Tidy now…</Button>
            </div>
          </div>
        )}
      </Popover>
    </>
  );
}
