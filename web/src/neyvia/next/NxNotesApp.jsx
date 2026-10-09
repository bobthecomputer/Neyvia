import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, FolderOpen, MessageSquarePlus, MessageSquareQuote, NotebookPen, Pin, Plus, Search, Trash2, X } from "lucide-react";

import "./nxDocs.css";
import NeyviaMessageBody from "../NeyviaMessageBody.jsx";
import { DictationGhost, DictationStrip, MicButton, useTextareaDictation } from "./NxDictation.jsx";
import { Button, Icon, IconButton, Segmented, Spinner, ago, local } from "./nxPrimitives.jsx";
import { os, useOs } from "./nxOsStore.js";
import { filesCall, notesCall, sendToChat } from "./nxDocsApi.js";
import { NotesWelcome } from "./NxNotesWelcome.jsx";

// Notes (Documents suite): Markdown notes in a folder (default ~/Neyvia Notes).
// The bot side (neyvia.notes.*) works on the same files; its changes arrive as
// notes.changed and refresh this screen. Autosave never overwrites a note that
// changed elsewhere: that becomes a choice for Paul.

const SAVE_DELAY = 700;
const VIEWS = [{ value: "write", label: "Write" }, { value: "split", label: "Split" }, { value: "preview", label: "Preview" }];

export function NxNotesApp({ target, session, nav, onShowChat }) {
  const [list, setList] = useState({ status: "loading", notes: [], tags: [], folder: "", exists: true });
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [note, setNote] = useState(null); // { path, title, modified, pinned, tags, file }
  const [draft, setDraft] = useState("");
  const [saved, setSaved] = useState("");
  const [save, setSave] = useState({ status: "idle" }); // idle | saving | saved | error | conflict
  const [view, setView] = useState(() => local.get("notes.view", "split"));
  const [pane, setPane] = useState("list"); // phone: list or editor
  const [folderEdit, setFolderEdit] = useState(null);
  const editor = useRef(null);
  // Some embedded engines leave a newly mounted controlled textarea empty.
  // Keep the actual editor synchronized with the loaded draft, as File does.
  useLayoutEffect(() => {
    if (editor.current && editor.current.value !== draft) editor.current.value = draft;
  }, [draft, note, view, pane]);
  const live = useRef({ note, draft, saved });
  live.current = { note, draft, saved };
  const signal = useOs(state => state.appSignals?.notes);
  const dirty = Boolean(note) && draft !== saved;

  const loadList = useCallback(async (text = query) => {
    try {
      const result = await notesCall("list", { query: text });
      setList({ status: "ready", ...result });
    } catch (error) {
      setList(current => ({ ...current, status: "error", error: error.message }));
    }
  }, [query]);

  useEffect(() => {
    const timer = setTimeout(() => void loadList(query), query ? 200 : 0);
    return () => clearTimeout(timer);
  }, [query, loadList]);

  const openNote = useCallback(async path => {
    const current = live.current;
    if (current.note && current.draft !== current.saved) await saveNow();
    try {
      const result = await notesCall("read", { path });
      setNote(result); setDraft(result.body); setSaved(result.body);
      setSave({ status: "idle" }); setPane("editor");
    } catch (error) {
      os.notify({ level: "error", message: error.message });
    }
    // saveNow is stable through refs
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { if (target) void openNote(target); }, [target, openNote]);

  const saveNow = useCallback(async ({ force = false } = {}) => {
    const { note: current, draft: text } = live.current;
    if (!current) return;
    setSave({ status: "saving" });
    try {
      const result = await notesCall("write", { path: current.path, body: text, ...(force ? {} : { expectedModified: current.modified }) });
      setNote(previous => (previous?.path === result.path ? { ...previous, ...result } : previous));
      setSaved(text);
      setSave({ status: "saved", at: Date.now() });
      setList(previous => ({ ...previous, notes: previous.notes.map(row => (row.path === result.path ? { ...row, ...result } : row)) }));
    } catch (error) {
      setSave(error.status === 409 ? { status: "conflict", by: "elsewhere" } : { status: "error", message: error.message });
    }
  }, []);

  // Autosave a moment after typing stops.
  useEffect(() => {
    if (!dirty || save.status === "conflict" || save.status === "saving") return undefined;
    const timer = setTimeout(() => void saveNow(), SAVE_DELAY);
    return () => clearTimeout(timer);
  }, [draft, dirty, save.status, saveNow]);

  // Save before leaving the app or the page.
  useEffect(() => {
    const onLeave = () => { if (live.current.note && live.current.draft !== live.current.saved) void saveNow(); };
    window.addEventListener("beforeunload", onLeave);
    return () => { window.removeEventListener("beforeunload", onLeave); onLeave(); };
  }, [saveNow]);

  // A model changed notes: refresh, and reload the open note if Paul has nothing unsaved.
  useEffect(() => {
    if (!signal) return;
    void loadList();
    const { note: current, draft: text, saved: base } = live.current;
    if (current && signal.payload?.path === current.path && signal.payload?.op === "write") {
      if (text === base) void openNote(current.path);
      else setSave({ status: "conflict", by: "model" });
    }
    // only on a new signal
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signal?.seq]);

  const newNote = async (body = "") => {
    if (dirty) await saveNow();
    try {
      const result = await notesCall("write", { body: typeof body === "string" ? body : "" });
      await loadList("");
      setQuery("");
      await openNote(result.path);
      requestAnimationFrame(() => editor.current?.focus());
    } catch (error) { os.notify({ level: "error", message: error.message }); }
  };

  const togglePin = async () => {
    if (!note) return;
    try {
      const result = await notesCall("pin", { path: note.path, pinned: !note.pinned });
      setNote(current => ({ ...current, pinned: result.pinned }));
      void loadList();
    } catch (error) { os.notify({ level: "error", message: error.message }); }
  };

  const remove = async () => {
    if (!note) return;
    try {
      await filesCall("trash", { path: note.file });
      const title = note.title;
      setNote(null); setDraft(""); setSaved(""); setPane("list");
      void loadList();
      os.notify({ level: "success", message: `“${title}” is in the Recycle Bin`, action: { label: "Undo", run: async () => {
        try { await filesCall("undo"); void loadList(); } catch (error) { os.notify({ level: "error", message: error.message }); }
      } } });
    } catch (error) { os.notify({ level: "error", message: error.message }); }
  };

  const editorPane = useRef(null);
  // Dictation writes at the cursor; "send it" sends the note to the chat after a short preview.
  const chatRef = useRef(null);
  const dictation = useTextareaDictation({ inputRef: editor, setText: setDraft, containerRef: editorPane, kind: "notes", onSend: () => chatRef.current?.("send") });

  const chat = mode => {
    if (!note) return;
    const text = mode === "ask"
      ? `About my note “${note.title}” (${note.file}):\n\n`
      : `${draft.trim()}\n\n(from my note “${note.title}”)`;
    const where = sendToChat(text, { session, onNewChat: nav?.onNewChat, onShowChat, local });
    os.notify({ level: "success", message: where === "chat" ? (mode === "ask" ? "Note added to your message. Type your question." : "Note added to your message.") : "Note added to a new chat." });
  };
  chatRef.current = chat;

  const changeFolder = async () => {
    const folder = String(folderEdit || "").trim();
    if (!folder) return;
    try {
      await notesCall("folder", { folder });
      setFolderEdit(null); setNote(null); setDraft(""); setSaved("");
      void loadList();
    } catch (error) { os.notify({ level: "error", message: error.message }); }
  };

  const shown = useMemo(() => {
    if (filter === "pinned") return list.notes.filter(row => row.pinned);
    if (filter.startsWith("tag:")) return list.notes.filter(row => row.tags.includes(filter.slice(4)));
    return list.notes;
  }, [list.notes, filter]);
  const pinnedCount = list.notes.filter(row => row.pinned).length;
  const setViewSaved = value => { setView(value); local.set("notes.view", value); };

  const statusText = save.status === "saving" ? "Saving…" : save.status === "error" ? "Not saved" : save.status === "conflict" ? "Not saved" : dirty ? "Editing" : save.status === "saved" ? "Saved" : "";

  return (
    <div className="nx-notes" data-pane={pane}>
      <aside className="nx-notes-list" aria-label="Notes">
        <div className="nx-notes-listhead">
          <label className="nx-docs-search">
            <Icon as={Search} size={14} />
            <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search notes" aria-label="Search notes" />
            {query ? <button type="button" aria-label="Clear search" onClick={() => setQuery("")}><Icon as={X} size={13} /></button> : null}
          </label>
          <IconButton icon={Plus} label="New note" onClick={() => void newNote()} />
        </div>
        {/* Filters appear once there is something to filter by; a lone "All" chip says nothing. */}
        {pinnedCount || list.tags.length || filter !== "all" ? (
          <div className="nx-notes-filters" role="radiogroup" aria-label="Show">
            {[["all", "All"], ...(pinnedCount ? [["pinned", "Pinned"]] : []), ...list.tags.slice(0, 12).map(row => [`tag:${row.tag}`, `#${row.tag}`])].map(([value, label]) => (
              <button key={value} type="button" role="radio" aria-checked={filter === value} className={filter === value ? "is-on" : ""} onClick={() => setFilter(value)}>{label}</button>
            ))}
          </div>
        ) : null}
        <div className="nx-notes-rows nx-scroll">
          {list.status === "loading" ? <div className="nx-docs-empty"><Spinner size={16} /></div> : null}
          {list.status === "error" ? <div className="nx-docs-empty"><strong>Notes didn't load</strong><p>{list.error}</p><Button size="sm" variant="outline" onClick={() => void loadList()}>Try again</Button></div> : null}
          {list.status === "ready" && !shown.length ? (
            <div className="nx-docs-empty nx-notes-listempty">
              <Icon as={NotebookPen} size={22} />
              <strong>{query ? "No notes match" : "No notes yet"}</strong>
              <p>{query ? "Try other words, or a #tag." : "Your notes line up here, newest first."}</p>
              {!query ? <Button size="sm" variant="outline" icon={Plus} onClick={() => void newNote()}>New note</Button> : null}
            </div>
          ) : null}
          {shown.map(row => (
            <button key={row.path} type="button" className={`nx-notes-row${note?.path === row.path ? " is-on" : ""}`} onClick={() => void openNote(row.path)}>
              <span className="nx-notes-rowtop">
                <span className="nx-notes-rowtitle">{row.title}</span>
                {row.pinned ? <Icon as={Pin} size={12} className="nx-notes-pin" /> : null}
                <span className="nx-notes-rowtime">{ago(row.changed)}</span>
              </span>
              <span className="nx-notes-rowtext">{row.snippet || row.excerpt || "Empty note"}</span>
              {row.tags.length ? <span className="nx-notes-rowtags">{row.tags.slice(0, 4).map(tag => <span key={tag}>#{tag}</span>)}</span> : null}
            </button>
          ))}
        </div>
        <footer className="nx-notes-folder">
          {folderEdit != null ? (
            <form onSubmit={event => { event.preventDefault(); void changeFolder(); }}>
              <input className="nx-input" autoFocus value={folderEdit} onChange={event => setFolderEdit(event.target.value)} aria-label="Notes folder" onKeyDown={event => { if (event.key === "Escape") setFolderEdit(null); }} />
              <Button size="sm" variant="outline" type="submit">Use</Button>
            </form>
          ) : (
            <>
              <button type="button" className="nx-notes-folderpath" title={`Open ${list.folder} in Files`} onClick={() => os.openApp("files", "documents", list.folder)}>
                <Icon as={FolderOpen} size={13} /><span>{list.folder || "Notes folder"}</span>
              </button>
              <button type="button" className="nx-link" onClick={() => setFolderEdit(list.folder)}>Change</button>
            </>
          )}
        </footer>
      </aside>

      <section ref={editorPane} className="nx-notes-editor" aria-label={note ? note.title : "No note open"}>
        {note ? (
          <>
            <div className="nx-docs-bar">
              <IconButton className="nx-notes-back" icon={ArrowLeft} label="All notes" onClick={() => setPane("list")} />
              <strong className="nx-docs-title" title={note.file}>{note.title}</strong>
              <span className={`nx-notes-status is-${save.status}`} role="status">{statusText}</span>
              <span className="nx-docs-spacer" />
              <Segmented size="sm" label="Editor view" value={view} options={VIEWS} onChange={setViewSaved} />
              <MicButton dictation={dictation} size={28} />
              <IconButton icon={Pin} label={note.pinned ? "Unpin" : "Pin"} active={note.pinned} onClick={() => void togglePin()} />
              <IconButton icon={MessageSquarePlus} label={session?.id ? "Send to chat" : "Send to a new chat"} onClick={() => chat("send")} />
              <IconButton icon={MessageSquareQuote} label="Ask about this note" onClick={() => chat("ask")} />
              <IconButton icon={Trash2} label="Delete (to the Recycle Bin)" onClick={() => void remove()} />
            </div>
            <div className="nx-notes-dictation"><DictationStrip dictation={dictation} /></div>
            {save.status === "conflict" ? (
              <div className="nx-notes-banner is-warning" role="alert">
                <span>{save.by === "model" ? "A model changed this note while you were typing." : "This note changed somewhere else since you opened it."}</span>
                <Button size="sm" variant="outline" onClick={() => void openNote(note.path)}>Load theirs</Button>
                <Button size="sm" onClick={() => void saveNow({ force: true })}>Keep mine</Button>
              </div>
            ) : null}
            {save.status === "error" ? (
              <div className="nx-notes-banner is-error" role="alert"><span>{save.message}</span><Button size="sm" variant="outline" onClick={() => void saveNow()}>Try again</Button></div>
            ) : null}
            <div className={`nx-notes-panes is-${view}`} data-nx-comment-target={`notes:${String(note.file || note.path).replace(/\\/g, "/")}`} data-nx-comment-kind="text" data-nx-comment-label={note.title}
              ref={element => { if (element) element.__nxText = () => live.current.draft; }}>
              {view !== "preview" ? (
                <textarea ref={editor} className="nx-notes-text nx-scroll" value={draft} spellCheck
                  placeholder={"Start with a # Title line, or just write.\nAdd #tags anywhere."}
                  aria-label="Note text"
                  onChange={event => setDraft(event.target.value)}
                  onKeyDown={event => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); void saveNow(); } }} />
              ) : null}
              {view !== "preview" ? (
                <DictationGhost dictation={dictation} />
              ) : null}
              {view !== "write" ? (
                <div className="nx-notes-preview nx-scroll" aria-label="Preview">
                  {draft.trim() ? <NeyviaMessageBody text={draft} /> : <p className="nx-notes-hint">The preview shows here as you write.</p>}
                </div>
              ) : null}
            </div>
          </>
        ) : (
          <NotesWelcome notes={list.notes} folder={list.folder} busy={list.status === "loading"} onStart={body => void newNote(body)}
            onOpen={path => { setPane("editor"); void openNote(path); }} />
        )}
      </section>
    </div>
  );
}
