import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, CornerDownLeft, MessageSquare, MessageCirclePlus, MessageSquareText, Pencil, RotateCcw, Send, Trash2, X } from "lucide-react";

import "./nxComments.css";
import { ProviderMark } from "./ProviderMark.jsx";
import { Icon, IconButton, Spinner, ago, local } from "./nxPrimitives.jsx";
import { getNx, loadList, openThread, useNx } from "./nxStore.js";
import { markFor } from "./NxSidebarParts.jsx";
import { backendBase } from "./nxApi.js";
import { os, useOs } from "./nxOsStore.js";
import { windowKey } from "./nxPlacementModel.js";
import {
  TARGET_ATTR, anchorFromRange, anchorLabel, boxOf, domAnchor, lineOf, locate, quoteOf, regionAnchor, slashes, targetAround, targetKindOf, targetsIn, textAnchor, windowTarget,
} from "./nxCommentAnchors.js";
import {
  addComment, deleteComment, editComment, ensureTargets, focusedWindowId, openCommentsFor, reopenComment, reportTargets, resolveComment, sendComments, setCommentUi,
  loadAllOpen, startCommentsBus, trackFocusedWindow, useCommentUi, windowTargetsOf, useOpenElsewhere, useTargetComments, useWindowCounts,
} from "./nxComments.js";
import { bindPopoutSession, closePopout, getPopout, openPopout, setPopoutPending, usePopout } from "./nxPopout.js";

// Comments on anything (plan 29 B). Comment mode (the header button, or C) lets
// you point at an element, select words or drag a region; the comment is pinned
// there with a number. A pin opens a small card (words, Send, Resolve); the list
// shows every comment on the window. "Send" posts one or all open comments to
// the pop-out chat (or another chat) as one message with each comment's anchor.
// Anchors and their geometry are nxCommentAnchors.js; the store is nxComments.js.

const who = comment => (comment.author === "you" || !comment.author ? "You" : String(comment.author).replace(/^./, letter => letter.toUpperCase()));
const isAgent = comment => comment.author && comment.author !== "you";
const typing = element => Boolean(element && (element.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(element.tagName)));
const same = (a, b) => (a === b) || JSON.stringify(a) === JSON.stringify(b);

// ---- sending ---------------------------------------------------------------------------------------------------

/**
 * Send comments as one message. By default to the pop-out chat (opened over this window if it isn't, on the chat that is open;
 * with none, a new Claude Code chat only when a folder is known). `destination` picks another chat or a live run.
 */
export async function sendCommentsFrom({ ids, winId, desc, title, sessionId = undefined, destination = null }) {
  const popout = getPopout();
  const newChat = popout.newChat;
  const chat = destination || (sessionId !== undefined && sessionId ? { sessionId } : popout.open && popout.sessionId ? { sessionId: popout.sessionId } : null);
  let target = chat;
  if (!target) {
    const app = newChat?.app || local.get("new.app", "neyvia");
    const cwd = newChat?.cwd || local.get("new.folder", null)?.path;
    if (!cwd) throw new Error("Open a chat first, or start one in a folder, then send the comments there.");
    target = { newSession: { app, cwd, ...(newChat?.model ? { model: newChat.model } : {}), ...(newChat?.effort ? { effort: newChat.effort } : {}), ...(newChat?.transport ? { transport: newChat.transport } : {}) } };
  }
  const receipt = await sendComments({ ids, destination: target });
  const chatId = receipt.sessionId || target.sessionId || null;
  if (chatId) { void openThread(chatId); void loadList(); }
  else void loadList();
  openPopout({ winId, desc, title, sessionId: chatId || popout.sessionId || null });
  // A new Claude Code chat takes a while to exist: the pop-out says so, then shows it the moment it does.
  if (!chatId && receipt.runId) {
    setPopoutPending(receipt.runId);
    void chatOfRun({ runId: receipt.runId, cwd: target.newSession?.cwd, sentAt: Date.parse(receipt.delivery?.sentAt) || Date.now(), ms: 300000 }).then(found => {
      setPopoutPending(null);
      if (found && !getPopout().sessionId) { bindPopoutSession(found); void openThread(found); }
    });
  }
  if (winId) setCommentUi(winId, { list: false, active: null });
  return receipt;
}

const sameFolder = (a, b) => String(a || "").split(String.fromCharCode(92)).join("/").toLowerCase() === String(b || "").split(String.fromCharCode(92)).join("/").toLowerCase();

/**
 * The chat a run of comments started. The live events name it as soon as they know it; failing that, the newest chat in the folder
 * it was started in (titled by the comments message) that appeared after the send. Null when it has not shown up within `ms`.
 */
async function chatOfRun({ runId, cwd, sentAt, ms }) {
  const end = Date.now() + ms;
  let round = 0;
  while (Date.now() < end) {
    const state = getNx();
    const live = Object.entries(state.runs).find(([id, run]) => id !== "undefined" && run?.runId === runId);
    if (live) return live[0];
    if (round % 3 === 2) {
      await loadList();
      const listed = Object.values(getNx().sessions).filter(row => row?.id && sameFolder(row.cwd, cwd) && /^Comments requested/i.test(row.title || "") && Date.parse(row.created_at || row.updated_at || 0) >= sentAt - 5000);
      listed.sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
      if (listed[0]) return listed[0].id;
    }
    round += 1;
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  return null;
}

function useSendState() {
  const [state, setState] = useState({ busy: false, error: "" });
  const run = useCallback(async task => {
    setState({ busy: true, error: "" });
    try { const result = await task(); setState({ busy: false, error: "" }); return result; } catch (failure) {
      setState({ busy: false, error: failure?.message || "The comments weren't sent." });
      return null;
    }
  }, []);
  return [state, run, () => setState(current => ({ ...current, error: "" }))];
}

// ---- where "Send all" can go ------------------------------------------------------------------------------------

function useDestinations(open, sessionId) {
  const rows = useNx(current => current.sessions);
  const [parallel, setParallel] = useState(null);
  useEffect(() => {
    if (!open) return undefined;
    let alive = true;
    const base = backendBase() || (typeof window.__NEYVIA_UI_SOURCE__ === "string" ? window.__NEYVIA_UI_SOURCE__ : "");
    fetch(`${base}/api/ui/parallel`, { credentials: "include" }).then(response => response.json()).then(result => {
      const run = (result?.data?.runs || result?.runs || []).find(entry => entry.main && !["settled", "stopped"].includes(entry.state || entry.status));
      if (alive) setParallel(run?.main?.session || run?.main?.runId ? { id: run.id, title: run.goal || "Parallel run", session: run.main.session, runId: run.main.runId, state: run.main.state } : null);
    }).catch(() => { if (alive) setParallel(null); });
    return () => { alive = false; };
  }, [open]);
  return useMemo(() => {
    const working = Object.values(rows).filter(row => ["working", "waiting_approval", "waiting_input"].includes(row.status) && row.id !== sessionId).slice(0, 5);
    return { parallel, working };
  }, [rows, parallel, sessionId]);
}

function DestinationMenu({ open, onClose, onPick, sessionId, popoutLabel }) {
  const { parallel, working } = useDestinations(open, sessionId);
  const menu = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const away = event => { if (!menu.current?.contains(event.target) && !event.target.closest?.("[data-dest-toggle]")) onClose(); };
    const key = event => { if (event.key === "Escape") { event.stopPropagation(); onClose(); } };
    document.addEventListener("pointerdown", away, true);
    document.addEventListener("keydown", key, true);
    return () => { document.removeEventListener("pointerdown", away, true); document.removeEventListener("keydown", key, true); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div ref={menu} className="nx-cm-menu nx-cm-ui" role="menu" aria-label="Send comments to">
      <button type="button" role="menuitem" onClick={() => onPick(null)}><Icon as={MessageSquare} size={14} /><span><strong>The pop-out chat</strong><small>{popoutLabel}</small></span></button>
      {parallel ? (
        <button type="button" role="menuitem" onClick={() => onPick(parallel.runId ? { runId: parallel.runId } : { sessionId: parallel.session })}>
          <ProviderMark id="neyvia" size={14} /><span><strong>The Parallel main agent</strong><small>{parallel.title}</small></span>
        </button>
      ) : null}
      {working.map(row => (
        <button key={row.id} type="button" role="menuitem" onClick={() => onPick({ sessionId: row.id })}>
          <ProviderMark id={markFor(row)} size={14} /><span><strong>{row.title || "Untitled chat"}</strong><small>Working now</small></span>
        </button>
      ))}
    </div>
  );
}

/** "Send all open" with a destination menu: the list panel's footer. */
function SendAll({ ids, winId, desc, title, sessionId, popoutLabel, extra = null }) {
  const [state, run, clear] = useSendState();
  const [menu, setMenu] = useState(false);
  const send = destination => { setMenu(false); void run(() => sendCommentsFrom({ ids, winId, desc, title, sessionId, destination })); };
  return (
    <div className="nx-cm-sendall nx-cm-ui">
      {extra}
      <div className="nx-cm-split">
        <button type="button" className="nx-cm-primary" disabled={!ids.length || state.busy} onClick={() => send(null)}>
          {state.busy ? <Spinner size={13} /> : <Icon as={Send} size={14} />}<span>Send all open{ids.length ? ` (${ids.length})` : ""}</span>
        </button>
        <button type="button" className="nx-cm-primary nx-cm-chev" data-dest-toggle aria-label="Choose where to send" aria-haspopup="menu" aria-expanded={menu} disabled={!ids.length || state.busy} onClick={() => setMenu(open => !open)}>
          <Icon as={ChevronDown} size={14} />
        </button>
        <DestinationMenu open={menu} onClose={() => setMenu(false)} onPick={send} sessionId={sessionId} popoutLabel={popoutLabel} />
      </div>
      {state.error ? <p className="nx-cm-error" role="alert">{state.error}<button type="button" aria-label="Dismiss" onClick={clear}><Icon as={X} size={12} /></button></p> : null}
    </div>
  );
}

// ---- the strip above the pop-out's message box ----------------------------------------------------------------------

/** "3 open comments · Send all": the pop-out's own way to send what is pinned on the window it floats over. */
export function CommentsStrip({ winId, desc, title, sessionId, onSent }) {
  const { open, unsent } = useWindowCounts(winId);
  const others = useOpenElsewhere(windowTargetsOf(winId)).filter(comment => !comment.delivery?.sentAt);
  const [include, setInclude] = useState(false);
  const [state, run, clear] = useSendState();
  useEffect(() => { void loadAllOpen(); }, [winId]);
  if (!winId || (!open && !others.length)) return null;
  const count = unsent + (include ? others.length : 0);
  const send = () => void run(async () => {
    const ids = [...openCommentsFor(winId, { unsent: true }), ...(include ? others : [])].map(comment => comment.id);
    const receipt = await sendCommentsFrom({ ids, winId, desc, title, sessionId: sessionId || undefined });
    if (receipt?.sessionId && receipt.sessionId !== sessionId) onSent?.(receipt.sessionId);
  });
  return (
    <div className="nx-cm-strip">
      <button type="button" className="nx-cm-strip-count" onClick={() => setCommentUi(winId, { list: true })} title="Show the comments">
        <Icon as={MessageSquareText} size={14} />
        <span>{unsent ? `${unsent} comment${unsent === 1 ? "" : "s"} to send` : open ? `${open} sent, waiting for the agent` : "Comments elsewhere"}{title ? ` · ${title}` : ""}</span>
      </button>
      {count ? (
        <button type="button" className="nx-cm-primary nx-cm-small" disabled={state.busy} onClick={send}>
          {state.busy ? <Spinner size={12} /> : <Icon as={Send} size={13} />}<span>Send {count === 1 ? "it" : `all ${count}`}</span>
        </button>
      ) : null}
      {others.length ? (
        <label className="nx-cm-include nx-cm-strip-more"><input type="checkbox" checked={include} onChange={event => setInclude(event.target.checked)} /><span>With {others.length} more from elsewhere</span></label>
      ) : null}
      {state.error ? <p className="nx-cm-error" role="alert">{state.error}<button type="button" aria-label="Dismiss" onClick={clear}><Icon as={X} size={12} /></button></p> : null}
    </div>
  );
}

// ---- header buttons ----------------------------------------------------------------------------------------------------

/** Chat (pop-out) and Comment mode: the two buttons every app and pane header carries. */
export function StageTools({ stage, session, title, phone = false }) {
  const winId = windowKey(stage);
  const ui = useCommentUi(winId);
  const counts = useWindowCounts(winId);
  const popout = usePopout();
  const chatOn = popout.open && popout.winId === winId;
  const toggleChat = () => {
    if (chatOn) { closePopout(); return; }
    setCommentUi(winId, { active: null }); // the chat takes the room a comment card was using
    openPopout({ winId, desc: stage, title, sessionId: popout.open && popout.sessionId ? undefined : session?.id || null });
  };
  return (
    <>
      {!phone ? (
        <button type="button" className={`nx-st-chat${chatOn ? " is-on" : ""}`} aria-pressed={chatOn} aria-label={`Chat about ${title}`} title={`Chat about ${title} (Ctrl J)`} onClick={toggleChat}>
          <Icon as={MessageSquare} size={14} /><span>Chat</span>
        </button>
      ) : null}
      <span className="nx-st-comments">
        <IconButton icon={MessageCirclePlus} label={ui.mode ? "Finish commenting (C)" : "Comment mode (C)"} active={ui.mode} onClick={() => setCommentUi(winId, { mode: !ui.mode, active: null, draft: null })} />
        {counts.total || ui.list ? (
          <button type="button" className={`nx-st-count${ui.list ? " is-on" : ""}${counts.open ? "" : " is-done"}`} aria-pressed={ui.list} aria-label={`Comments: ${counts.open} open`} title={`Comments on this window: ${counts.open} open`} onClick={() => setCommentUi(winId, { list: !ui.list })}>
            <Icon as={counts.open ? MessageSquareText : Check} size={14} /><span>{counts.open || counts.total}</span>
          </button>
        ) : null}
      </span>
    </>
  );
}

// ---- cards: a new comment and an existing one ---------------------------------------------------------------------------

function useFocusOnMount(ref) { useEffect(() => { requestAnimationFrame(() => ref.current?.focus()); }, [ref]); }

function Quote({ anchor }) {
  const quote = anchor?.quote;
  return quote ? <blockquote className="nx-cm-quote">{quote}</blockquote> : null;
}

function DraftCard({ draft, place, onSave, onCancel }) {
  const [text, setText] = useState("");
  const [state, setState] = useState({ busy: false, error: "" });
  const input = useRef(null);
  useFocusOnMount(input);
  const save = async () => {
    if (!text.trim() || state.busy) return;
    setState({ busy: true, error: "" });
    try { await onSave(text); } catch (failure) { setState({ busy: false, error: failure?.message || "The comment wasn't saved." }); }
  };
  return (
    <div className="nx-cm-card nx-cm-ui is-draft" style={place} role="dialog" aria-label="New comment"
      onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); onCancel(); } }}>
      <div className="nx-cm-card-head"><span className="nx-cm-where">{anchorLabel(draft.anchor)}</span></div>
      <Quote anchor={draft.anchor} />
      <textarea ref={input} rows={3} value={text} placeholder="Say what should change…" aria-label="Comment" onChange={event => setText(event.target.value)}
        onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); void save(); } }} />
      {state.error ? <p className="nx-cm-error" role="alert">{state.error}</p> : null}
      <div className="nx-cm-actions">
        <button type="button" className="nx-cm-ghost" onClick={onCancel}>Cancel</button>
        <button type="button" className="nx-cm-primary nx-cm-small" disabled={!text.trim() || state.busy} onClick={() => void save()}>
          {state.busy ? <Spinner size={12} /> : <Icon as={CornerDownLeft} size={13} />}<span>Comment</span>
        </button>
      </div>
    </div>
  );
}

function CommentCard({ comment, place, onClose, winId, desc, title, sessionId }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(comment.text);
  const [confirm, setConfirm] = useState(false);
  const [state, run, clear] = useSendState();
  const input = useRef(null);
  useEffect(() => { setText(comment.text); }, [comment.text]);
  useEffect(() => { if (editing) requestAnimationFrame(() => input.current?.focus()); }, [editing]);
  const open = comment.status === "open";
  const save = () => void run(async () => { await editComment(comment, { text }); setEditing(false); });
  return (
    <div className={`nx-cm-card nx-cm-ui${isAgent(comment) ? " is-agent" : ""}${open ? "" : " is-resolved"}`} style={place} role="dialog" aria-label={`Comment ${comment.number}`}
      onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); if (editing) setEditing(false); else onClose(); } }}>
      <div className="nx-cm-card-head">
        <span className="nx-cm-num" aria-hidden="true">{comment.number}</span>
        <strong>{who(comment)}</strong>
        <span className="nx-cm-when">{ago(Date.parse(comment.updatedAt || comment.createdAt))}</span>
        {!open ? <span className="nx-cm-badge"><Icon as={Check} size={11} />Resolved</span> : null}
        <span className="nx-head-spacer" />
        <IconButton icon={X} size="sm" label="Close" onClick={onClose} />
      </div>
      <div className="nx-cm-where">{anchorLabel(comment.anchor)}</div>
      <Quote anchor={comment.anchor} />
      {editing ? (
        <textarea ref={input} rows={3} value={text} aria-label="Edit the comment" onChange={event => setText(event.target.value)}
          onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); save(); } }} />
      ) : <p className="nx-cm-text">{comment.text}</p>}
      {comment.delivery?.sentAt ? <p className="nx-cm-sent"><Icon as={Send} size={11} />Sent {ago(Date.parse(comment.delivery.sentAt))}{comment.delivery.channel ? ` · ${String(comment.delivery.channel).replace("-", " ")}` : ""}</p> : null}
      {state.error ? <p className="nx-cm-error" role="alert">{state.error}<button type="button" aria-label="Dismiss" onClick={clear}><Icon as={X} size={12} /></button></p> : null}
      <div className="nx-cm-actions">
        {editing ? (
          <>
            <button type="button" className="nx-cm-ghost" onClick={() => { setEditing(false); setText(comment.text); }}>Cancel</button>
            <button type="button" className="nx-cm-primary nx-cm-small" disabled={!text.trim() || state.busy} onClick={save}>Save</button>
          </>
        ) : (
          <>
            {confirm ? (
              <button type="button" className="nx-cm-ghost is-danger" onClick={() => void run(() => deleteComment(comment))} onBlur={() => setConfirm(false)} autoFocus>Delete this comment</button>
            ) : <IconButton icon={Trash2} size="sm" label="Delete" onClick={() => setConfirm(true)} />}
            <IconButton icon={Pencil} size="sm" label="Edit" onClick={() => setEditing(true)} />
            <span className="nx-head-spacer" />
            {open ? (
              <>
                <button type="button" className="nx-cm-ghost" disabled={state.busy} onClick={() => void run(() => resolveComment(comment))}><Icon as={Check} size={13} />Resolve</button>
                <button type="button" className="nx-cm-primary nx-cm-small" disabled={state.busy} onClick={() => void run(() => sendCommentsFrom({ ids: [comment.id], winId, desc, title, sessionId }))}>
                  {state.busy ? <Spinner size={12} /> : <Icon as={Send} size={13} />}<span>{comment.delivery?.sentAt ? "Send again" : "Send"}</span>
                </button>
              </>
            ) : <button type="button" className="nx-cm-ghost" disabled={state.busy} onClick={() => void run(() => reopenComment(comment))}><Icon as={RotateCcw} size={13} />Reopen</button>}
          </>
        )}
      </div>
    </div>
  );
}

// ---- the list ------------------------------------------------------------------------------------------------------------

/** "Notes · launch-plan.md": what a comment's target is called when it isn't on this window. */
export function targetName(target) {
  const [lead, ...rest] = String(target || "").split(":");
  const path = rest.join(":");
  const leaf = path.split(/[\\/]/).filter(Boolean).pop() || path;
  const names = { notes: "Notes", pdf: "PDF", files: "Files", code: "Code", "app-factory": "App Factory", browser: "Browser", preview: "Preview", artifact: "Artifact", image: "Image", dom: "App" };
  return `${names[lead] || lead}${leaf ? ` · ${leaf}` : ""}`;
}

/** Bring the app a comment is pinned in to the front, so its pin is there to see. */
function openTarget(target) {
  const [lead, ...rest] = String(target || "").split(":");
  const path = rest.join(":");
  if (lead === "notes") os.openApp("notes", "documents", path);
  else if (lead === "pdf" && !path.startsWith("upload:")) os.openApp("pdf", "documents", path);
  else if (lead === "files") os.openApp("files", "documents", path.replace(/[\\/][^\\/]*$/, ""));
  else if (lead === "app-factory") os.openApp("app-factory", "build");
}

function ListPanel({ comments, loading, labels, activeId, others, onPick, onClose, sendProps }) {
  const [include, setInclude] = useState(false);
  const open = comments.filter(comment => comment.status === "open");
  const resolved = comments.filter(comment => comment.status !== "open");
  const row = (comment, elsewhere = false) => (
    <li key={comment.id}>
      <button type="button" className={`nx-cm-row${comment.id === activeId ? " is-active" : ""}${isAgent(comment) ? " is-agent" : ""}${comment.status === "open" ? "" : " is-resolved"}`} onClick={() => (elsewhere ? openTarget(comment.target) : onPick(comment))}>
        <span className="nx-cm-num" aria-hidden="true">{comment.status === "open" ? comment.number : <Icon as={Check} size={11} />}</span>
        <span className="nx-cm-row-main">
          <span className="nx-cm-row-meta"><strong>{who(comment)}</strong><span>{elsewhere ? targetName(comment.target) : `${labels[comment.target] ? `${labels[comment.target]} · ` : ""}${anchorLabel(comment.anchor)}`}</span>{comment.delivery?.sentAt ? <Icon as={Send} size={10} /> : null}</span>
          <span className="nx-cm-row-text">{comment.text}</span>
        </span>
      </button>
    </li>
  );
  const othersUnsent = others.filter(comment => !comment.delivery?.sentAt);
  const ids = [...open, ...(include ? othersUnsent : [])].filter(comment => !comment.delivery?.sentAt).map(comment => comment.id);
  return (
    <aside className="nx-cm-list nx-cm-ui" aria-label="Comments">
      <header><strong>Comments</strong><span className="nx-head-spacer" /><IconButton icon={X} size="sm" label="Close the list" onClick={onClose} /></header>
      <div className="nx-cm-list-body nx-scroll">
        {loading && !comments.length ? <div className="nx-cm-empty"><Spinner size={14} /></div> : null}
        {!loading && !comments.length && !others.length ? <p className="nx-cm-empty">No comments yet. Press <kbd className="nx-kbd">C</kbd> and point at something.</p> : null}
        {open.length ? <><h4>Open · {open.length}</h4><ul>{open.map(comment => row(comment))}</ul></> : null}
        {resolved.length ? <><h4>Resolved · {resolved.length}</h4><ul>{resolved.map(comment => row(comment))}</ul></> : null}
        {others.length ? <><h4>Elsewhere · {others.length}</h4><ul>{others.map(comment => row(comment, true))}</ul></> : null}
      </div>
      <SendAll ids={ids} {...sendProps}
        extra={othersUnsent.length ? (
          <label className="nx-cm-include"><input type="checkbox" checked={include} onChange={event => setInclude(event.target.checked)} /><span>Include {othersUnsent.length} more from elsewhere</span></label>
        ) : null} />
    </aside>
  );
}

// ---- the layer -------------------------------------------------------------------------------------------------------------

const PIN = 24;
const CARD_W = 300;

/** Beside the anchor, else under it, else over it: wherever the whole card fits without covering what it is about. */
function placeNear(box, bounds, height = 190) {
  const gap = 10; const edge = 8;
  const clampX = x => Math.min(Math.max(x, edge), Math.max(edge, bounds.w - CARD_W - edge));
  const clampY = y => Math.min(Math.max(y, edge), Math.max(edge, bounds.h - height - edge));
  if (box.x + box.w + gap + CARD_W <= bounds.w - edge) return { left: box.x + box.w + gap, top: clampY(box.y - 6), width: CARD_W };
  if (box.y + box.h + gap + height <= bounds.h - edge) return { left: clampX(box.x), top: box.y + box.h + gap, width: CARD_W };
  if (box.y - gap - height >= edge) return { left: clampX(box.x), top: box.y - gap - height, width: CARD_W };
  if (box.x - gap - CARD_W >= edge) return { left: box.x - gap - CARD_W, top: clampY(box.y - 6), width: CARD_W };
  return { left: clampX(box.x + box.w + gap), top: clampY(box.y - 6), width: CARD_W };
}

/**
 * The comments of one window: markers, the card being written or read, the list and the comment-mode listeners.
 * It sits over the window's body (NxStage renders it after the body) and never takes a click unless comment mode is on.
 */
export function CommentsLayer({ stage, session, title }) {
  const winId = windowKey(stage);
  const ui = useCommentUi(winId);
  const placement = useOs(current => current.windows.find(win => win.id === winId)?.placement || "main");
  const layer = useRef(null);
  const [found, setFound] = useState([]);
  const [boxes, setBoxes] = useState({});
  const [hover, setHover] = useState(null);
  const [band, setBand] = useState(null);
  const [bounds, setBounds] = useState({ w: 0, h: 0 });
  const [inset, setInset] = useState(0); // the layer starts where the window's body does, under its title bar
  const [shields, setShields] = useState([]);
  const popoutSession = usePopout(current => current.sessionId);
  const sessionId = popoutSession || session?.id || null;
  const sessionTitle = useNx(current => (sessionId ? current.sessions[sessionId]?.title : ""));

  const stageEl = () => layer.current?.parentElement || null;
  const bodyEl = () => stageEl()?.querySelector(":scope > .nx-stage-body") || null;

  // The targets on screen: what the app marked, else the window itself.
  const fallback = useMemo(() => windowTarget(stage), [stage]);
  const targets = useMemo(() => (found.length ? found : [{ id: fallback.id, kind: fallback.kind, label: fallback.label, targetKind: fallback.targetKind, element: null }]), [found, fallback]);
  const ids = useMemo(() => targets.map(target => target.id), [targets]);
  const idsKey = ids.join("\n");
  const labels = useMemo(() => Object.fromEntries(targets.map(target => [target.id, target.label])), [targets]);
  const { comments, loading } = useTargetComments(ids);
  const others = useOpenElsewhere(ids);
  useEffect(() => { if (ui.list) void loadAllOpen(); }, [ui.list]);

  useEffect(() => { startCommentsBus(); return trackFocusedWindow(); }, []);
  useEffect(() => { void ensureTargets(ids); reportTargets(winId, ids); }, [idsKey, winId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => reportTargets(winId, []), [winId]);

  const elementOf = useCallback(id => {
    const marked = targetsIn(bodyEl()).find(entry => entry.id === id);
    return marked?.element || (id === fallback.id ? bodyEl() : null);
  }, [fallback.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- find targets, measure anchors ----
  const frame = useRef(0);
  const measure = useCallback(() => {
    frame.current = 0;
    const host = layer.current; const body = bodyEl();
    if (!host || !body) return;
    const origin = host.getBoundingClientRect();
    // A floating chat over this pane's right side narrows where cards may open, so a card never hides under it.
    const chat = document.querySelector(".nx-pw")?.getBoundingClientRect();
    const covered = chat && chat.left > origin.left + CARD_W + 40 && chat.left < origin.right && chat.bottom > origin.top && chat.top < origin.bottom;
    const cardW = covered ? chat.left - origin.left - 8 : origin.width;
    setBounds(current => (current.w === origin.width && current.h === origin.height && current.cardW === cardW ? current : { w: origin.width, h: origin.height, cardW }));
    setInset(current => (current === body.offsetTop ? current : body.offsetTop));
    const marked = targetsIn(body).map(entry => ({ id: entry.id, kind: entry.kind, label: entry.label, targetKind: targetKindOf(entry.id), element: entry.element }));
    setFound(current => (same(current.map(entry => [entry.id, entry.kind, entry.label]), marked.map(entry => [entry.id, entry.kind, entry.label])) ? current : marked));
    const frames = [...body.querySelectorAll("iframe")].map(element => ({ element, box: boxOf(element) })).filter(entry => entry.box && entry.box.w > 40);
    setShields(current => { const next = frames.map(entry => ({ x: entry.box.x - origin.left, y: entry.box.y - origin.top, w: entry.box.w, h: entry.box.h })); return same(current, next) ? current : next; });
    const next = {};
    for (const comment of comments) {
      const root = marked.find(entry => entry.id === comment.target)?.element || (comment.target === fallback.id ? body : null);
      if (!root) continue;
      const box = locate(comment.anchor, root);
      next[comment.id] = !box ? { lost: true } : box.hidden ? { hidden: true } : { x: box.x - origin.left, y: box.y - origin.top, w: box.w, h: box.h };
    }
    setBoxes(current => (same(current, next) ? current : next));
  }, [comments, fallback.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const schedule = useCallback(() => { if (!frame.current) frame.current = requestAnimationFrame(measure); }, [measure]);
  useLayoutEffect(() => { schedule(); }, [schedule, ui.mode, ui.list]);
  useEffect(() => {
    const stageNode = stageEl();
    if (!stageNode) return undefined;
    const observer = new MutationObserver(schedule);
    observer.observe(stageNode, { subtree: true, childList: true, attributes: true, attributeFilter: [TARGET_ATTR, "style", "class", "src"] });
    const resize = typeof ResizeObserver === "function" ? new ResizeObserver(schedule) : null;
    resize?.observe(stageNode);
    window.addEventListener("resize", schedule);
    stageNode.addEventListener("scroll", schedule, true);
    const timer = setInterval(schedule, 900);
    return () => { observer.disconnect(); resize?.disconnect(); window.removeEventListener("resize", schedule); stageNode.removeEventListener("scroll", schedule, true); clearInterval(timer); cancelAnimationFrame(frame.current); frame.current = 0; };
  }, [schedule]);

  // ---- keyboard: C toggles comment mode in the window you last used; Escape finishes ----
  useEffect(() => {
    const onKey = event => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.key === "Escape" && ui.mode && !ui.draft && !event.target.closest?.("[role=dialog], [role=menu]")) { event.preventDefault(); setCommentUi(winId, { mode: false, active: null }); return; }
      if ((event.key !== "c" && event.key !== "C") || typing(event.target) || typing(document.activeElement)) return;
      const focused = focusedWindowId();
      const mine = focused ? focused === winId : placement === "main" || placement === "full";
      if (!mine) return;
      event.preventDefault();
      setCommentUi(winId, { mode: !ui.mode, active: null, draft: null });
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [ui.mode, ui.draft, winId, placement]);

  // ---- comment mode: point at an element, select words, drag a region ----
  const pending = useRef(null);
  const draftFrom = useCallback((target, anchor, box) => {
    const origin = layer.current.getBoundingClientRect();
    setHover(null);
    setCommentUi(winId, { active: null, draft: { target: target.id, targetKind: target.targetKind || targetKindOf(target.id), anchor, box: { x: box.x - origin.left, y: box.y - origin.top, w: box.w, h: box.h } } });
  }, [winId]);

  useEffect(() => {
    const host = stageEl();
    if (!ui.mode || !host) return undefined;
    const inBody = event => { const body = bodyEl(); return body && body.contains(event.target) && !event.target.closest?.(".nx-cm-ui"); };
    const targetFor = event => {
      const marked = targetAround(event.target, bodyEl());
      if (marked) return { ...marked, targetKind: targetKindOf(marked.id), element: marked.element };
      if (found.length) return null; // the app marked its targets: pointing outside them says nothing
      return { id: fallback.id, kind: fallback.kind, label: fallback.label, targetKind: fallback.targetKind, element: bodyEl() };
    };
    const stop = event => { if (inBody(event)) event.stopPropagation(); };
    const onClick = event => { if (inBody(event)) { event.preventDefault(); event.stopPropagation(); } };
    const onMove = event => {
      if (!inBody(event) || pending.current?.drag) return;
      const target = targetFor(event);
      if (!target) { setHover(null); return; }
      const origin = layer.current.getBoundingClientRect();
      let element = event.target;
      if (element.closest(".textLayer") && target.kind === "pdf") { setHover(null); return; }
      if (element.tagName === "TEXTAREA" || (element === target.element && found.length === 0)) { setHover(null); return; }
      const box = boxOf(element);
      setHover(box && box.w > 2 ? { x: box.x - origin.left, y: box.y - origin.top, w: box.w, h: box.h } : null);
    };
    const onDown = event => {
      if (!inBody(event) || event.button !== 0) return;
      const target = targetFor(event);
      pending.current = { target, x0: event.clientX, y0: event.clientY, hit: event.target, drag: false, region: Boolean(target && ["pdf", "image", "browser"].includes(target.kind) && !event.target.closest(".textLayer span, textarea")) };
      if (pending.current.region) event.preventDefault(); // a picture would start a drag-and-drop of its own and swallow the gesture
      event.stopPropagation();
    };
    const onDrag = event => {
      const current = pending.current;
      if (!current?.region || event.buttons !== 1) return;
      if (!current.drag && Math.hypot(event.clientX - current.x0, event.clientY - current.y0) < 6) return;
      current.drag = true;
      const origin = layer.current.getBoundingClientRect();
      const x = Math.min(current.x0, event.clientX) - origin.left; const y = Math.min(current.y0, event.clientY) - origin.top;
      setHover(null);
      setBand({ x, y, w: Math.abs(event.clientX - current.x0), h: Math.abs(event.clientY - current.y0) });
    };
    const onUp = event => {
      const current = pending.current;
      pending.current = null;
      setBand(null);
      if (!current?.target || !inBody(event) || event.button !== 0) return;
      const { target } = current;
      // The browser settles a text selection after mouseup.
      setTimeout(() => {
        const area = event.target.closest?.("textarea") || (document.activeElement?.tagName === "TEXTAREA" && target.element.contains(document.activeElement) ? document.activeElement : null);
        const selection = window.getSelection();
        if (area && area.selectionStart !== undefined && target.kind === "text") {
          const path = target.id.replace(/^[a-z-]+:/, "");
          const anchor = textAnchor(area, path);
          const box = locate(anchor, target.element);
          draftFrom(target, anchor, box && !box.hidden ? box : { x: event.clientX, y: event.clientY, w: 4, h: 18 });
          return;
        }
        if (selection && !selection.isCollapsed && selection.rangeCount && target.element.contains(selection.getRangeAt(0).commonAncestorContainer)) {
          const made = anchorFromRange(selection.getRangeAt(0), target);
          if (made) {
            const anchor = target.kind === "text" ? textFromRendered(made.anchor, target) : made.anchor;
            draftFrom(target, anchor, made.box);
            selection.removeAllRanges();
            return;
          }
        }
        if (current.drag) {
          const x0 = Math.min(current.x0, event.clientX); const y0 = Math.min(current.y0, event.clientY);
          const box = { x: x0, y: y0, w: Math.abs(event.clientX - current.x0), h: Math.abs(event.clientY - current.y0) };
          draftFrom(target, regionAnchor(box, target, current.hit), box);
          return;
        }
        if (["pdf", "image", "browser"].includes(target.kind)) {
          const box = { x: event.clientX - 12, y: event.clientY - 12, w: 24, h: 24 };
          draftFrom(target, regionAnchor(box, target, current.hit), box);
          return;
        }
        const element = current.hit.nodeType === 1 ? current.hit : current.hit.parentElement;
        if (!element || element === target.element && found.length === 0 && target.kind === "dom" && element === bodyEl()) return;
        const box = boxOf(element);
        if (target.kind === "text") {
          const text = textFromRendered(domAnchor(element, target, { quote: element.innerText || "" }), target);
          draftFrom(target, text, box);
          return;
        }
        draftFrom(target, domAnchor(element, target, { box }), box);
      }, 0);
    };
    const events = [["pointerdown", stop], ["mousedown", onDown], ["mouseup", onUp], ["click", onClick], ["dblclick", onClick], ["auxclick", onClick], ["contextmenu", onClick], ["mousemove", onMove], ["mousemove", onDrag], ["submit", onClick], ["dragstart", onClick], ["keydown", event => { if (inBody(event) && event.key === "Enter") event.stopPropagation(); }]];
    for (const [name, handler] of events) host.addEventListener(name, handler, true);
    return () => { for (const [name, handler] of events) host.removeEventListener(name, handler, true); setHover(null); setBand(null); pending.current = null; };
  }, [ui.mode, found, fallback, draftFrom]); // eslint-disable-line react-hooks/exhaustive-deps

  // A same-origin iframe (an app preview): its elements answer; any other one answers with the region.
  const shieldClick = (event, index) => {
    const body = bodyEl();
    const frames = [...body.querySelectorAll("iframe")].filter(element => (boxOf(element)?.w || 0) > 40);
    const frameEl = frames[index];
    if (!frameEl) return;
    const target = targetAround(frameEl, body);
    const entry = target ? { ...target, targetKind: targetKindOf(target.id), element: target.element } : { id: fallback.id, kind: fallback.kind, label: fallback.label, targetKind: fallback.targetKind, element: body };
    const outer = frameEl.getBoundingClientRect();
    const scale = frameEl.clientWidth ? outer.width / frameEl.clientWidth : 1;
    let inner = null;
    try { inner = frameEl.contentDocument?.elementFromPoint((event.clientX - outer.left) / scale, (event.clientY - outer.top) / scale); } catch { inner = null; }
    if (inner && inner !== frameEl.contentDocument.body && inner !== frameEl.contentDocument.documentElement) {
      const box = boxOf(inner);
      draftFrom(entry, domAnchor(inner, entry, { box }), box);
    } else {
      const box = { x: event.clientX - 14, y: event.clientY - 14, w: 28, h: 28 };
      draftFrom(entry, regionAnchor(box, entry, frameEl), box);
    }
  };

  const saveDraft = async text => {
    const draft = ui.draft;
    const comment = await addComment({ target: draft.target, targetKind: draft.targetKind, anchor: draft.anchor, text });
    setCommentUi(winId, { draft: null, active: comment.id });
  };

  const active = comments.find(comment => comment.id === ui.active) || null;
  const activeBox = active ? boxes[active.id] : null;
  const showResolved = ui.list;
  const pins = comments.filter(comment => (comment.status === "open" || showResolved) && boxes[comment.id]?.w != null);
  const popoutLabel = sessionTitle || (sessionId ? "The chat you have open" : "A new chat");
  const sendProps = { winId, desc: stage, title, sessionId: sessionId || undefined, popoutLabel };

  const pinPlace = box => ({ left: Math.min(Math.max(box.x + box.w - PIN * 0.15, 4), Math.max(4, bounds.w - PIN - 4)), top: Math.min(Math.max(box.y - PIN * 0.9, 4), Math.max(4, bounds.h - PIN - 4)) });
  const focusPin = comment => {
    setCommentUi(winId, { active: comment.id, draft: null });
    const box = boxes[comment.id];
    if (!box?.w && box?.hidden) { const root = elementOf(comment.target); root?.scrollIntoView?.({ block: "nearest" }); }
  };

  return (
    <div ref={layer} className={`nx-cm-layer${ui.mode ? " is-mode" : ""}`} style={{ top: inset }} data-comment-layer={winId}>
      {ui.mode ? (
        <div className="nx-cm-modebar nx-cm-ui" role="status">
          <MessageCirclePlus size={14} aria-hidden="true" />
          <span>Click something, select words or drag a region</span>
          <button type="button" onClick={() => setCommentUi(winId, { mode: false, active: null, draft: null })}>Done <kbd className="nx-kbd">Esc</kbd></button>
        </div>
      ) : null}
      {ui.mode && hover && !ui.draft && !ui.active ? <div className="nx-cm-hover" style={{ left: hover.x, top: hover.y, width: hover.w, height: hover.h }} /> : null}
      {band ? <div className="nx-cm-band" style={{ left: band.x, top: band.y, width: band.w, height: band.h }} /> : null}
      {ui.mode ? shields.map((box, index) => <div key={index} className="nx-cm-shield nx-cm-ui" style={{ left: box.x, top: box.y, width: box.w, height: box.h }} onClick={event => shieldClick(event, index)} aria-hidden="true" />) : null}
      {active && activeBox?.w != null ? <div className="nx-cm-hl" style={{ left: activeBox.x, top: activeBox.y, width: activeBox.w, height: activeBox.h }} /> : null}
      {ui.draft ? <div className="nx-cm-hl is-draft" style={{ left: ui.draft.box.x, top: ui.draft.box.y, width: ui.draft.box.w, height: ui.draft.box.h }} /> : null}
      {pins.map(comment => {
        const box = boxes[comment.id];
        const place = pinPlace(box);
        return (
          <button key={comment.id} type="button" style={place} data-comment-id={comment.id}
            className={`nx-cm-pin nx-cm-ui${isAgent(comment) ? " is-agent" : ""}${comment.status === "open" ? "" : " is-resolved"}${comment.id === ui.active ? " is-active" : ""}${comment.delivery?.sentAt ? " is-sent" : ""}`}
            aria-label={`Comment ${comment.number} by ${who(comment)}${comment.status === "open" ? "" : " (resolved)"}: ${quoteOf(comment.text, 80)}`} aria-expanded={comment.id === ui.active}
            onClick={() => (comment.id === ui.active ? setCommentUi(winId, { active: null }) : focusPin(comment))}>
            {comment.status === "open" ? comment.number : <Icon as={Check} size={12} />}
          </button>
        );
      })}
      {ui.draft ? <DraftCard draft={ui.draft} place={placeNear(ui.draft.box, { w: bounds.cardW ?? bounds.w, h: bounds.h })} onSave={saveDraft} onCancel={() => setCommentUi(winId, { draft: null })} /> : null}
      {active && activeBox?.w != null && !ui.draft ? (
        <CommentCard key={`${active.id}:${active.revision}`} comment={active} place={placeNear(activeBox, { w: bounds.cardW ?? bounds.w, h: bounds.h }, 210)} onClose={() => setCommentUi(winId, { active: null })} {...sendProps} />
      ) : null}
      {ui.list ? (
        <ListPanel comments={comments} loading={loading} labels={found.length > 1 ? labels : {}} activeId={ui.active} others={others} onClose={() => setCommentUi(winId, { list: false })}
          onPick={focusPin} sendProps={sendProps} />
      ) : null}
    </div>
  );
}

/** A selection in rendered Markdown becomes a text anchor on the note's source: the lines come from finding the words there. */
function textFromRendered(anchor, target) {
  const path = target.id.replace(/^[a-z-]+:/, "");
  const source = target.element.querySelector("textarea")?.value ?? target.element.__nxText?.() ?? "";
  const quote = String(anchor.quote || "");
  const first = quote.split("\n").map(line => line.trim()).find(line => line.length >= 4) || quote;
  const at = source && first ? source.indexOf(first.slice(0, 80)) : -1;
  if (at < 0) return { kind: "text", path: slashes(path), startLine: 1, endLine: 1, quote };
  const end = at + Math.max(quote.length, first.length);
  return { kind: "text", path: slashes(path), startLine: lineOf(source, at), endLine: lineOf(source, end), quote, range: { start: at, end: Math.min(end, source.length) } };
}
