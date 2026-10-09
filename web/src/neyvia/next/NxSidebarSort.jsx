import { useCallback, useRef, useState } from "react";
import { FolderPlus, FolderSymlink, FolderTree, RotateCcw, TriangleAlert } from "lucide-react";

import { Button, Icon, Popover, Sheet, Spinner, local, useMedia } from "./nxPrimitives.jsx";
import { callNx } from "./nxApi.js";
import { os } from "./nxOsStore.js";
import { refreshObserved, rememberFolders } from "./nxSidebarObserve.js";

// Sort No folder chats into folders by subject (plan 15 T7). The PC reads the
// chats with a local model (no cloud) and proposes groups; nothing moves until
// Paul picks the groups and presses Move. A move only changes where the chat
// shows in the sidebar; its files and folder on disk stay as they are. Undo
// puts every chat back exactly where it was, unless Paul moved it again since.

const PREVIEW_MAX = 40; // the PC reads each transcript and runs the model on CPU: about 2-5 s per chat when it is busy
const SHOWN_PER_GROUP = 5;
const LAST_KEY = "side.sort.last"; // { undoId, before: { id: { present, value } }, count, at }

const SKIP_WORDS = {
  active: "running or waiting for you",
  archived: "archived",
  already_filed: "already in a folder",
};

// A refused sidebar command (ok:false) arrives as an error; its answer is in error.data (HTTP) or error.data.data.
const answerOf = error => (error?.data?.data && typeof error.data.data === "object" ? error.data.data : error?.data) || {};

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Put the chats of the last sort back (sidebar.undo). Shared by the toast and the Sort panel. */
export async function undoSort(last = local.get(LAST_KEY, null)) {
  if (!last?.undoId) return null;
  try {
    const receipt = await callNx("sidebar_undo_command", { undoId: last.undoId });
    // The bus sends the same moves; applying them here too makes the sidebar change at once.
    for (const id of receipt.restored || []) {
      const before = last.before?.[id];
      if (before?.present) os.patchSession(id, { project: before.value ?? null });
      else os.patchSession(id, { project: undefined });
    }
    refreshObserved(receipt.restored);
    local.set(LAST_KEY, null);
    const kept = receipt.conflicts?.length || 0;
    const back = receipt.restored?.length || 0;
    os.notify({ level: kept ? "warning" : "success",
      message: back ? `Put back ${plural(back, "chat")}${kept ? `. ${kept} stayed where you moved ${kept === 1 ? "it" : "them"} since.` : "."}`
        : kept ? `Nothing put back: you moved ${kept === 1 ? "that chat" : "those chats"} again since.` : "Those chats are already back." });
    return receipt;
  } catch (error) {
    os.notify({ level: "warning", message: `Couldn't undo the sort: ${answerOf(error).error || error?.message || "the PC didn't answer"}. Try again from Sort.` });
    return null;
  }
}

function useSort() {
  const [state, setState] = useState({ status: "idle" });
  const preview = useCallback(async ids => {
    setState({ status: "reading", count: ids.length });
    try {
      const result = await callNx("sidebar_preview_command", { ids, limit: Math.min(PREVIEW_MAX, Math.max(1, ids.length)) });
      if (result?.ok === false || result?.status === "model_unavailable") {
        setState({ status: "model", error: result?.error || "" });
        return;
      }
      setState({ status: "preview", result, chosen: new Set((result.groups || []).map(group => group.id)) });
    } catch (error) {
      const answer = answerOf(error);
      if (answer.status === "model_unavailable") setState({ status: "model", error: answer.error || "" });
      else setState({ status: "error", error: error?.message || "The PC didn't answer." });
    }
  }, []);
  const toggle = id => setState(current => {
    const chosen = new Set(current.chosen);
    if (chosen.has(id)) chosen.delete(id); else chosen.add(id);
    return { ...current, chosen };
  });
  const confirm = useCallback(async snapshot => {
    setState({ ...snapshot, status: "moving", error: "" });
    const { result, chosen } = snapshot;
    const groups = (result.groups || []).filter(group => chosen.has(group.id));
    try {
      const receipt = await callNx("sidebar_confirm_command", { previewId: result.previewId, confirmed: true, groupIds: groups.map(group => group.id) });
      if (receipt?.status !== "completed") {
        setState({ ...snapshot, status: "stale", conflicts: receipt?.conflicts || [] });
        return null;
      }
      rememberFolders(groups.map(group => group.target).filter(target => target.path === null));
      const before = {};
      for (const suggestion of result.suggestions || []) before[suggestion.id] = suggestion.before;
      for (const group of groups) for (const id of group.ids) if (receipt.moved.includes(id)) os.patchSession(id, { project: group.target.id });
      refreshObserved(receipt.moved);
      const last = { undoId: receipt.undoId, before, count: receipt.moved.length, at: Date.now() };
      if (receipt.undoId) local.set(LAST_KEY, last);
      os.notify({ level: "success",
        message: `Moved ${plural(receipt.moved.length, "chat")} into ${plural(groups.length, "folder")}${receipt.replayed ? " (already done)" : ""}.`,
        action: receipt.undoId ? { label: "Undo", run: () => undoSort(last) } : undefined });
      setState({ status: "idle" });
      return receipt;
    } catch (error) {
      const answer = answerOf(error);
      if (answer.status === "stale_preview") setState({ ...snapshot, status: "stale", conflicts: answer.conflicts || [] });
      else setState({ ...snapshot, status: "preview", error: answer.error || error?.message || "The move didn't finish. Nothing changed." });
      return null;
    }
  }, []);
  const reset = useCallback(() => setState({ status: "idle" }), []);
  return { state, preview, toggle, confirm, reset };
}

function GroupCard({ group, chosen, onToggle, titleOf }) {
  const subject = group.target?.path === null;
  const shown = group.ids.slice(0, SHOWN_PER_GROUP);
  return (
    <li className={`nx-sort-group${chosen ? " is-chosen" : ""}`}>
      <label className="nx-sort-group-head" title={group.reason}>
        <input type="checkbox" checked={chosen} onChange={() => onToggle(group.id)} />
        <Icon as={subject ? FolderPlus : FolderSymlink} size={14} />
        <span className="nx-sort-group-name">{group.target?.name || group.name}</span>
        <span className="nx-tag">{subject ? "New folder" : "Project"}</span>
      </label>
      <ul className="nx-sort-chats">
        {shown.map(id => <li key={id}>{titleOf(id)}</li>)}
        {group.ids.length > SHOWN_PER_GROUP ? <li className="is-more">and {group.ids.length - SHOWN_PER_GROUP} more</li> : null}
      </ul>
    </li>
  );
}

function SortBody({ sort, leaves, rows, onClose, phone }) {
  const { state, preview, toggle, confirm } = sort;
  const ids = leaves.filter(leaf => leaf.state !== "running" && leaf.state !== "needs").map(leaf => leaf.session.id).slice(0, PREVIEW_MAX);
  const titleOf = id => rows.find(row => row.id === id)?.title || leaves.find(leaf => leaf.session.id === id)?.session.title || "Untitled chat";
  const last = local.get(LAST_KEY, null);

  if (state.status === "idle") {
    return (
      <div className="nx-sort">
        {phone ? null : <strong>Sort into folders</strong>}
        <p>Neyvia reads {ids.length === PREVIEW_MAX ? `the ${PREVIEW_MAX} newest chats` : plural(ids.length, "chat")} in No folder on your PC and groups the ones about the same thing. Nothing moves until you choose.</p>
        <p className="nx-cleanup-never">Only the sidebar changes: files and folders on disk stay where they are.</p>
        <div className="nx-cleanup-actions">
          {last?.undoId ? <Button size="sm" variant="ghost" icon={RotateCcw} onClick={() => { void undoSort(last); onClose(); }}>Undo last sort</Button> : <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>}
          <Button size="sm" variant="primary" disabled={!ids.length} onClick={() => void preview(ids)}>{ids.length ? "Find groups" : "Nothing to sort"}</Button>
        </div>
      </div>
    );
  }
  if (state.status === "reading") {
    return (
      <div className="nx-sort is-busy" aria-live="polite">
        <Spinner size={14} />
        <span>Reading {plural(state.count, "chat")} on your PC… <small>This can take a minute; it runs offline.</small></span>
      </div>
    );
  }
  if (state.status === "model" || state.status === "error") {
    return (
      <div className="nx-sort">
        <p className="nx-sort-alert" role="alert">
          <Icon as={TriangleAlert} size={14} />
          <span>{state.status === "model"
            ? "The folder model isn't on this PC yet, so Neyvia can't group chats by subject. Nothing moved."
            : `Couldn't read the chats: ${state.error}. Nothing moved.`}</span>
        </p>
        {state.status === "model" && state.error ? <p className="nx-cleanup-never" title={state.error}>Set it up once from the PC (about 92 MB, it runs offline).</p> : null}
        <div className="nx-cleanup-actions">
          <Button size="sm" variant="ghost" onClick={onClose}>Close</Button>
          <Button size="sm" variant="outline" onClick={() => void preview(ids)}>Try again</Button>
        </div>
      </div>
    );
  }
  const { result, chosen } = state;
  const groups = result.groups || [];
  const moving = groups.filter(group => chosen.has(group.id)).reduce((sum, group) => sum + group.ids.length, 0);
  const skipped = (result.skipped || []).reduce((map, row) => {
    const word = SKIP_WORDS[row.reason] || "couldn't be read";
    return { ...map, [word]: (map[word] || 0) + 1 };
  }, {});
  return (
    <div className="nx-sort">
      <strong>{groups.length ? `${plural(groups.length, "group")} found` : "No groups found"}</strong>
      {groups.length ? (
        <ul className="nx-sort-groups nx-scroll" aria-label="Folders to make">
          {groups.map(group => <GroupCard key={group.id} group={group} chosen={chosen.has(group.id)} onToggle={toggle} titleOf={titleOf} />)}
        </ul>
      ) : <p>These chats don't share a subject yet. Try again after a few more.</p>}
      {Object.keys(skipped).length ? (
        <p className="nx-cleanup-never">Left alone: {Object.entries(skipped).map(([word, n]) => `${n} ${word}`).join(", ")}.</p>
      ) : null}
      {state.status === "stale" ? (
        <p className="nx-sort-alert" role="alert"><Icon as={TriangleAlert} size={14} />
          <span>{plural(state.conflicts.length || 1, "chat")} changed after this preview, so nothing moved. Find groups again.</span></p>
      ) : null}
      {state.error ? <p className="nx-sort-alert" role="alert"><Icon as={TriangleAlert} size={14} /><span>{state.error}</span></p> : null}
      <div className="nx-cleanup-actions">
        <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
        {state.status === "stale"
          ? <Button size="sm" variant="outline" onClick={() => void preview(ids)}>Find groups again</Button>
          : groups.length ? (
            <Button size="sm" variant="primary" disabled={!moving || state.status === "moving"} onClick={() => void confirm(state).then(receipt => { if (receipt) onClose(); })}>
              {state.status === "moving" ? "Moving…" : moving ? `Move ${plural(moving, "chat")}` : "Choose a group"}
            </Button>
          ) : null}
      </div>
    </div>
  );
}

/** The Sort button on the No folder header, and its preview panel. */
export function SortChip({ leaves, rows }) {
  const phone = useMedia("(max-width: 760px)");
  const anchor = useRef(null);
  const [open, setOpen] = useState(false);
  const sort = useSort();
  const close = useCallback(() => { setOpen(false); sort.reset(); }, [sort.reset]);
  const body = open ? <SortBody sort={sort} leaves={leaves} rows={rows} onClose={close} phone={phone} /> : null;
  return (
    <>
      <Button ref={anchor} size="sm" variant="ghost" icon={FolderTree} className="nx-sort-go" aria-expanded={open}
        aria-label="Sort No folder chats into folders" onClick={() => (open ? close() : setOpen(true))}>Sort</Button>
      {phone
        ? <Sheet open={open} onClose={close} title="Sort into folders">{body}</Sheet>
        : <Popover anchor={anchor} open={open} onClose={close} placement="bottom-end" width={360} label="Sort into folders">{body}</Popover>}
    </>
  );
}
