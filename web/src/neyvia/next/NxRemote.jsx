import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AppWindow, Check, Copy, ExternalLink, KeyRound, Keyboard, MonitorSmartphone, MonitorUp, Plug, Power, RefreshCw, ShieldCheck, TriangleAlert, Unplug,
} from "lucide-react";

import { PaneMessage } from "./NxFilePane.jsx";
import { ProviderMark } from "./ProviderMark.jsx";
import { remoteCall, remoteFrame, remoteTargets, remoteWindows } from "./nxRemoteApi.js";
import {
  clickableAt, countdown, endsConnection, liveSessions, normalizeAddress, pngSize, refusalText, remoteEntryText, remoteKey, scrollerAt,
  stopReason, textBoxAt, timeLeft,
} from "./nxRemoteModel.js";
import { boxStyle, effectLabel, mergeLog, toCapture } from "./nxCuaModel.js";
import { refreshRemote, stopSharing, useRemoteState } from "./NxRemoteBanner.jsx";
import { Button, Icon, IconButton, Kbd, Segmented, Spinner, StatusDot, local, useTick } from "./nxPrimitives.jsx";
import "./nxPreview.css";
import "./nxRemote.css";

// Remote control (plan 15 T19). Two sides of one screen:
// - Share an app (on the PC that has the app, e.g. Zen with ChatGPT signed in): tick the open
//   windows to share, pick a time, get a one-use code. While shared, a warning with Stop now
//   stays on top of Neyvia and a native warning window stays on the desktop.
// - Use another PC (on the other PC): paste the code, then use the shared window live: click its
//   buttons, pick a text box and type, scroll. Passwords are never typed or sent from here.
// Opened by pane.show {kind: "preview", target: "remote" | "remote:host" | "remote:<connection>"}
// and on its own at ?view=remote. Both read the same backend state.

const FRAME_MS = 500;     // at most 2 pictures a second (the contract allows 4)
const LOG_MS = 1000;      // the shared log, once a second
const TREE_MIN_MS = 1500; // controls under the pointer, refreshed when the picture changes
const TYPE_FLUSH_MS = 300;
const SCROLL_GAP_MS = 250;
const HINT_MS = 3500;
const MINUTES = [{ value: 5, label: "5 min" }, { value: 15, label: "15 min" }, { value: 30, label: "30 min" }, { value: 60, label: "1 hour" }];
const CONTROL_ROLES = new Set(["Button", "CheckBox", "RadioButton", "ListItem", "TabItem", "MenuItem", "Hyperlink", "Edit", "Document", "ComboBox", "TreeItem"]);
const BLOCKING = new Set(["protected_window", "protection_unknown", "window_not_allowed", "driver_unavailable"]);

const message = error => refusalText(error?.code) || error?.message || "That didn't work.";

/** Which side and connection a pane target names. */
function parseRemoteTarget(target) {
  const value = String(target || "").replace(/^remote:?/, "");
  if (value === "host" || value === "share") return { side: "host", connectionId: "" };
  if (value === "use" || !value) return { side: value ? "use" : "", connectionId: "" };
  return { side: "use", connectionId: value };
}

// ---- share an app (this PC) -----------------------------------------------------------------------

function useTargets() {
  const [state, setState] = useState({ status: "loading", targets: [], error: null });
  const load = useCallback(async () => {
    setState(current => ({ ...current, status: current.targets.length ? "refreshing" : "loading" }));
    try {
      const data = await remoteTargets();
      setState({ status: "ready", targets: data?.targets || [], error: null });
    } catch (error) {
      setState(current => ({ ...current, status: "error", error }));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);
  return { ...state, reload: load };
}

function InviteCard({ invite, session, onDone }) {
  useTick(true);
  const [copied, setCopied] = useState(false);
  const left = invite.until - Date.now();
  const used = session?.status === "connected";
  const stopped = session?.status === "stopped";
  useEffect(() => { if (used || stopped || left <= 0) { const timer = setTimeout(onDone, used ? 2500 : 0); return () => clearTimeout(timer); } return undefined; }, [used, stopped, left <= 0]); // eslint-disable-line react-hooks/exhaustive-deps
  const copy = async () => {
    try { await navigator.clipboard.writeText(invite.code); setCopied(true); setTimeout(() => setCopied(false), 1800); } catch { setCopied(false); }
  };
  if (used) return <div className="nx-rm-invite is-used" role="status"><Icon as={Check} size={15} /><span>The other PC connected. The code is used up.</span></div>;
  return (
    <section className="nx-rm-invite" aria-label="Code for the other PC">
      <header>
        <strong>Code for the other PC</strong>
        <span className="nx-rm-count" aria-live="off">{countdown(invite.until)}</span>
      </header>
      <code className="nx-rm-code">{invite.code}</code>
      <p>Paste it into Neyvia on the other PC, under Remote control. It works once, for 2 minutes.</p>
      <div className="nx-rm-row">
        <Button size="sm" variant="primary" icon={copied ? Check : Copy} onClick={() => void copy()}>{copied ? "Copied" : "Copy code"}</Button>
        <Button size="sm" onClick={onDone}>Hide</Button>
      </div>
    </section>
  );
}

function ShareRow({ session, codeGone = false }) {
  useTick(session.status !== "stopped");
  const live = session.status !== "stopped";
  return (
    <li className={`nx-rm-share is-${session.status}`}>
      <StatusDot tone={session.status === "connected" ? "live" : session.status === "enabled" ? "gold" : "idle"} pulse={session.status === "connected"} />
      <span className="nx-rm-share-main">
        <strong>{session.name}</strong>
        <small>
          {session.status === "connected" ? "In use by the other PC" : session.status === "enabled" ? "Waiting for the other PC" : stopReason(session.reason)}
          {live ? ` · ${timeLeft(session.expiresAt)}` : ""}
          {` · ${session.windowIds.length} window${session.windowIds.length === 1 ? "" : "s"}`}
        </small>
        {codeGone && session.status === "enabled" ? <small>Its code is no longer shown. Stop it and allow again for a new code.</small> : null}
      </span>
      {live ? <Button size="sm" variant="warn" icon={Power} onClick={() => void stopSharing(session.id)}>Stop now</Button> : null}
    </li>
  );
}

function ShareSide() {
  const { data } = useRemoteState();
  const { status, targets, error, reload } = useTargets();
  const [chosen, setChosen] = useState(() => new Set());
  const [minutes, setMinutes] = useState(15);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [invite, setInvite] = useState(null); // {code, until, sessionId}: memory only, never stored
  const sessions = data?.sessions || [];
  const live = liveSessions(sessions);
  const ended = sessions.filter(session => session.status === "stopped").slice(-3).reverse();

  // The desktop itself ("Program Manager") and untitled helper windows aren't apps to share.
  const titled = targets.filter(row => row.title.trim() && !(row.app === "explorer" && row.title === "Program Manager"));
  const untitled = targets.length - titled.length;
  const rows = [...titled].sort((a, b) => Number(b.eligible) - Number(a.eligible) || a.app.localeCompare(b.app));
  const picked = rows.filter(row => chosen.has(row.windowId) && row.eligible);

  const toggle = (row, on) => setChosen(current => {
    const next = new Set(current);
    if (on) next.add(row.windowId); else next.delete(row.windowId);
    return next;
  });

  const allow = async () => {
    if (!picked.length) return;
    setBusy(true);
    setNotice("");
    try {
      const name = picked.length === 1 ? picked[0].title : `${picked[0].title} and ${picked.length - 1} more`;
      const result = await remoteCall("enable", { windowIds: picked.map(row => row.windowId), minutes, name: name.slice(0, 80) });
      setInvite({ code: result.invite, until: Date.now() + 120000, sessionId: result.session.id });
      setChosen(new Set());
      await refreshRemote().catch(() => {});
    } catch (failure) {
      setNotice(message(failure));
      if (failure.code === "window_not_allowed" || failure.code === "protected_window") void reload();
    } finally {
      setBusy(false);
    }
  };

  if (status === "error" && (error?.code === "host_owner_required" || error?.code === "owner_required" || error?.code === "missing")) {
    return (
      <PaneMessage icon={MonitorUp} title={error.code === "missing" ? "Remote control isn't on this PC's service yet" : "Sharing is turned on at the PC itself"}>
        {error.code === "host_owner_required"
          ? "For safety, only someone sitting at this PC can choose which apps another PC may use. Open Neyvia there."
          : refusalText(error.code)}
      </PaneMessage>
    );
  }

  return (
    <div className="nx-rm-share-side nx-scroll">
      <div className="nx-rm-column">
        {invite ? <InviteCard invite={invite} session={sessions.find(row => row.id === invite.sessionId)} onDone={() => setInvite(null)} /> : null}
        {live.length ? (
          <section className="nx-rm-card" aria-label="Shared now">
            <header className="nx-rm-card-head">
              <h3>Shared now</h3>
              {live.length > 1 ? <Button size="sm" variant="warn" icon={Power} onClick={() => void stopSharing()}>Stop all now</Button> : null}
            </header>
            <ul className="nx-rm-shares">{live.map(session => <ShareRow key={session.id} session={session} codeGone={invite?.sessionId !== session.id} />)}</ul>
            <p className="nx-rm-note">A warning window with Stop now also stays on this PC's desktop. Using this PC's mouse or keyboard yourself stops sharing too.</p>
          </section>
        ) : null}

        <section className="nx-rm-card" aria-label="Share an app">
          <header className="nx-rm-card-head">
            <div>
              <h3>Let another PC use an app here</h3>
              <p>Only the windows you tick, for the time you pick. Passwords stay here: type them on this PC.</p>
            </div>
            <IconButton size="sm" icon={RefreshCw} label="Look again at open windows" onClick={() => void reload()} disabled={status === "loading" || status === "refreshing"} />
          </header>
          {status === "loading" ? <p className="nx-rm-wait"><Spinner size={12} /> Checking each open window for password fields. This takes up to 30 s.</p> : null}
          {status === "error" ? <p className="nx-pv-error" role="alert">{message(error)}</p> : null}
          {rows.length ? (
            <ul className="nx-rm-targets" aria-label="Open windows">
              {rows.map(row => (
                <li key={row.windowId} className={row.eligible ? "" : "is-off"}>
                  <label>
                    <input type="checkbox" checked={chosen.has(row.windowId)} disabled={!row.eligible || busy} onChange={event => toggle(row, event.target.checked)} />
                    <Icon as={AppWindow} size={14} />
                    <span className="nx-rm-target-main">
                      <span className="nx-rm-target-title" title={row.title}>{row.title}</span>
                      <small>{[row.app !== row.title ? row.app : "", row.eligible ? "" : "has a password field, or Neyvia can't tell"].filter(Boolean).join(" · ") || "App window"}</small>
                    </span>
                    {row.eligible ? null : <Icon as={KeyRound} size={13} className="nx-rm-lock" />}
                  </label>
                </li>
              ))}
            </ul>
          ) : status === "ready" ? <p className="nx-rm-note">No windows are open that could be shared.</p> : null}
          {untitled > 0 ? <p className="nx-rm-note">{untitled === 1 ? "1 background window isn't listed." : `${untitled} background windows aren't listed.`}</p> : null}
          <div className="nx-rm-allow">
            <span className="nx-rm-label" id="nx-rm-for">For</span>
            <Segmented size="sm" label="How long" value={minutes} onChange={setMinutes} options={MINUTES} />
            <span className="nx-head-spacer" />
            <Button variant="primary" icon={busy ? undefined : ShieldCheck} disabled={!picked.length || busy} onClick={() => void allow()}>
              {busy ? <><Spinner size={12} /> Allowing…</> : picked.length > 1 ? `Allow ${picked.length} windows` : "Allow"}
            </Button>
          </div>
          {notice ? <p className="nx-pv-error" role="alert">{notice}</p> : null}
        </section>

        {ended.length ? (
          <section className="nx-rm-card is-quiet" aria-label="Ended">
            <header className="nx-rm-card-head"><h3>Ended</h3></header>
            <ul className="nx-rm-shares">{ended.map(session => <ShareRow key={session.id} session={session} />)}</ul>
          </section>
        ) : null}
      </div>
    </div>
  );
}

// ---- use another PC -------------------------------------------------------------------------------

function ConnectForm({ onConnected, endedNote }) {
  const [address, setAddress] = useState(() => local.get("remote.address", ""));
  const [code, setCode] = useState(""); // never stored
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const connect = async event => {
    event.preventDefault();
    const url = normalizeAddress(address);
    if (!url || !code.trim()) return;
    setBusy(true);
    setNotice("");
    try {
      const result = await remoteCall("connect", { url, invite: code.trim() });
      local.set("remote.address", url);
      setCode("");
      await refreshRemote().catch(() => {});
      onConnected(result.connection);
    } catch (failure) {
      setNotice(message(failure));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="nx-rm-share-side nx-scroll">
      <div className="nx-rm-column">
        {endedNote ? <div className="nx-fp-banner is-warn nx-rm-ended" role="status"><Icon as={Unplug} size={15} /><span>{endedNote}</span></div> : null}
        <form className="nx-rm-card" onSubmit={event => void connect(event)} aria-label="Use an app on another PC">
          <header className="nx-rm-card-head">
            <div>
              <h3>Use an app on another PC</h3>
              <p>On that PC, open Remote control, tick the app under Share an app, then paste its code here.</p>
            </div>
          </header>
          <label className="nx-rm-field">
            <span>That PC's address</span>
            <input className="nx-input" value={address} onChange={event => setAddress(event.target.value)} placeholder="http://192.0.2.10:47880"
              spellCheck={false} autoComplete="off" inputMode="url" />
          </label>
          <label className="nx-rm-field">
            <span>Code</span>
            <input className="nx-input nx-rm-code-input" value={code} onChange={event => setCode(event.target.value)} placeholder="Paste the code from that PC"
              spellCheck={false} autoComplete="off" autoCorrect="off" autoCapitalize="off" data-1p-ignore data-lpignore="true" />
          </label>
          <div className="nx-rm-allow">
            <span className="nx-rm-note">The code works once. Nothing is recorded.</span>
            <span className="nx-head-spacer" />
            <Button type="submit" variant="primary" icon={busy ? undefined : Plug} disabled={busy || !address.trim() || !code.trim()}>
              {busy ? <><Spinner size={12} /> Connecting…</> : "Connect"}
            </Button>
          </div>
          {notice ? <p className="nx-pv-error" role="alert">{notice}</p> : null}
        </form>
      </div>
    </div>
  );
}

/** The latest picture of one shared window, polled while shown (never faster than FRAME_MS). */
function useRemoteFrame(connectionId, windowId, { paused, onRefusal }) {
  const [frame, setFrame] = useState(null); // {src, captureId, seq, width, height}
  const [problem, setProblem] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const kick = useRef(() => {});
  const refusal = useRef(onRefusal);
  refusal.current = onRefusal;

  useEffect(() => {
    if (!connectionId || windowId == null || paused) return undefined;
    let alive = true;
    let timer = 0;
    let inflight = false;
    let again = false;
    let sha = "";
    let src = "";
    const tick = async () => {
      clearTimeout(timer);
      if (inflight) { again = true; return; }
      inflight = true;
      const started = Date.now();
      let stop = false;
      try {
        const next = await remoteFrame(connectionId, windowId);
        if (!alive) return;
        setProblem(null);
        if (next.sha !== sha || !src) {
          const size = pngSize(next.buffer) || { width: 0, height: 0 };
          const old = src;
          src = URL.createObjectURL(new Blob([next.buffer], { type: "image/png" }));
          sha = next.sha;
          setFrame({ src, captureId: next.captureId, seq: next.seq, ...size });
          if (old) setTimeout(() => URL.revokeObjectURL(old), 2000);
        } else {
          setFrame(current => (current && current.captureId !== next.captureId ? { ...current, captureId: next.captureId } : current));
        }
      } catch (error) {
        if (!alive) return;
        setProblem(error);
        refusal.current?.(error);
        stop = endsConnection(error.code) || BLOCKING.has(error.code);
      } finally {
        inflight = false;
      }
      if (!alive || stop) return;
      const wait = again ? 0 : document.hidden ? 3000 : Math.max(120, FRAME_MS - (Date.now() - started));
      again = false;
      timer = setTimeout(tick, wait);
    };
    kick.current = () => { clearTimeout(timer); timer = setTimeout(tick, 80); };
    void tick();
    return () => {
      alive = false;
      clearTimeout(timer);
      kick.current = () => {};
      if (src) setTimeout(() => URL.revokeObjectURL(src), 2000);
    };
  }, [connectionId, windowId, paused, attempt]);

  return { frame, problem, refresh: () => kick.current(), retry: () => { setProblem(null); setAttempt(value => value + 1); } };
}

/** The controls of the shown window (fresh tokens), refreshed when the picture changes. */
function useRemoteElements(connectionId, windowId, captureId, paused) {
  const [elements, setElements] = useState([]);
  const last = useRef(0);
  const [ask, setAsk] = useState(0);
  useEffect(() => { setElements([]); }, [connectionId, windowId]);
  useEffect(() => {
    if (!connectionId || windowId == null || !captureId || paused) return undefined;
    let alive = true;
    const wait = Math.max(150, TREE_MIN_MS - (Date.now() - last.current));
    const timer = setTimeout(async () => {
      last.current = Date.now();
      try {
        const data = await remoteCall("snapshot", { connectionId, windowId });
        if (alive) setElements(Array.isArray(data?.elements) ? data.elements : []);
      } catch { /* the picture's own refusal says what's wrong */ }
    }, wait);
    return () => { alive = false; clearTimeout(timer); };
  }, [connectionId, windowId, captureId, paused, ask]);
  return { elements, reload: () => setAsk(value => value + 1) };
}

/** The shared log (redacted on the owning PC), from where this view started. */
function useRemoteLog(connectionId, paused) {
  const [entries, setEntries] = useState([]);
  const kick = useRef(() => {});
  useEffect(() => {
    if (!connectionId || paused) return undefined;
    let alive = true;
    let since = 0;
    let timer = 0;
    const tick = async () => {
      clearTimeout(timer);
      try {
        const data = await remoteCall("log", { connectionId, since_seq: since });
        if (!alive) return;
        for (const entry of data?.entries || []) setEntries(current => mergeLog(current, entry, 200));
        const newest = (data?.entries || []).reduce((max, entry) => Math.max(max, entry.seq || 0), 0);
        if (newest) since = Math.max(since, newest);
      } catch (error) {
        if (!alive || endsConnection(error.code)) return;
      }
      if (alive) timer = setTimeout(tick, document.hidden ? 4000 : LOG_MS);
    };
    kick.current = () => { clearTimeout(timer); timer = setTimeout(tick, 150); };
    void tick();
    return () => { alive = false; clearTimeout(timer); kick.current = () => {}; };
  }, [connectionId, paused]);
  return { entries, refresh: () => kick.current() };
}

const time = value => { try { return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); } catch { return ""; } };

function Who({ entry }) {
  if (entry.by === "remote") return <span className="nx-pv-who is-paul" aria-label="You, from this PC">You</span>;
  if (entry.by === "paul") return <span className="nx-pv-who" aria-label="Someone at that PC">PC</span>;
  if (entry.by === "driver") return <span className="nx-pv-who is-driver" aria-label="Driver"><Icon as={ShieldCheck} size={12} /></span>;
  return <span className="nx-pv-who is-agent" aria-label={entry.who || "Agent"}><ProviderMark id="neyvia" size={14} /></span>;
}

function RemoteLog({ entries }) {
  const list = useRef(null);
  useEffect(() => { if (list.current) list.current.scrollTop = list.current.scrollHeight; }, [entries.length]);
  return (
    <section className="nx-pv-log" aria-label="Activity">
      <header><strong>Activity</strong></header>
      <ol ref={list} className="nx-scroll" aria-live="polite" aria-relevant="additions">
        {entries.length ? entries.map(entry => {
          const refused = entry.result?.error?.code;
          const effect = entry.status === "ok" ? effectLabel(entry.result) : "";
          return (
            <li key={entry.id} className={`nx-pv-entry is-${entry.by === "remote" ? "paul" : entry.by} is-${entry.status}`}>
              <Who entry={entry} />
              <div className="nx-pv-entry-main">
                <span className="nx-pv-entry-text">{remoteEntryText(entry)}</span>
                <span className="nx-pv-entry-meta">{[effect, refused ? refusalText(refused) || "refused" : entry.status === "failed" ? "failed" : "", time(entry.at)].filter(Boolean).join(" · ")}</span>
              </div>
            </li>
          );
        }) : <li className="nx-pv-log-empty">Nothing yet. What you do here, and anything done at that PC, shows up here. Typed text isn't shown or kept.</li>}
      </ol>
    </section>
  );
}

function ControlsList({ elements, typing, onClick, onType, blocked }) {
  const controls = elements.filter(element => CONTROL_ROLES.has(element.role) && element.enabled && !element.offscreen && element.label
    && ((element.actions || []).length || element.role === "Edit" || element.role === "Document")).slice(0, 30);
  return (
    <section className="nx-pv-apps nx-rm-controls" aria-label="Controls in this window">
      <header><strong>Controls</strong></header>
      {controls.length ? (
        <ul>
          {controls.map(element => {
            const text = (element.actions || []).includes("set_value");
            const on = typing?.element_token === element.element_token;
            return (
              <li key={element.element_token}>
                <button type="button" className={`nx-rm-control${on ? " is-on" : ""}`} onClick={() => (text ? onType(element) : onClick(element))}
                  title={text ? `Type into ${element.label}` : `Click ${element.label}`}>
                  <Icon as={text ? Keyboard : AppWindow} size={13} />
                  <span>{element.label}</span>
                  <small>{text ? (on ? "typing here" : "type") : element.role === "CheckBox" ? "toggle" : "click"}</small>
                </button>
              </li>
            );
          })}
        </ul>
      ) : <p>{blocked ? "None shown while the window can't be shown." : "Looking at the window…"}</p>}
    </section>
  );
}

function Viewer({ connection, onEnded }) {
  const connectionId = connection.id;
  const [windows, setWindows] = useState(connection.windows || []);
  const [windowId, setWindowId] = useState(connection.windows?.[0]?.window_id ?? null);
  const [notice, setNotice] = useState("");
  const [hint, setHint] = useState("");
  const [hover, setHover] = useState(null);
  const [typing, setTyping] = useState(null); // the picked text box {element_token, label, screenshot_frame}
  const [ripple, setRipple] = useState(null);
  const [busy, setBusy] = useState(false);
  const [ended, setEnded] = useState(null);
  const canvas = useRef(null);
  const queue = useRef(Promise.resolve());
  const pending = useRef({ text: "", textTimer: 0, scrollAt: 0, down: null });
  const hintTimer = useRef(0);

  const stop = useCallback(error => { setEnded(error); onEnded?.(error); }, [onEnded]);
  const onRefusal = useCallback(error => { if (endsConnection(error.code)) stop(error); }, [stop]);
  const { frame, problem, refresh, retry } = useRemoteFrame(connectionId, windowId, { paused: Boolean(ended), onRefusal });
  const { elements, reload: reloadElements } = useRemoteElements(connectionId, windowId, frame?.captureId, Boolean(ended));
  const log = useRemoteLog(connectionId, Boolean(ended));
  const windowRow = windows.find(row => row.window_id === windowId) || null;

  useEffect(() => {
    let alive = true;
    remoteWindows(connectionId).then(data => {
      if (!alive || !Array.isArray(data?.windows)) return;
      setWindows(data.windows);
      if (!data.windows.some(row => row.window_id === windowId)) setWindowId(data.windows[0]?.window_id ?? null);
    }).catch(error => { if (alive && endsConnection(error.code)) stop(error); });
    return () => { alive = false; };
  }, [connectionId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setTyping(null); }, [windowId]);
  // A picked text box stays picked only while it is still in the window.
  useEffect(() => {
    if (typing && elements.length && !elements.some(element => element.element_token === typing.element_token)) setTyping(null);
  }, [elements]); // eslint-disable-line react-hooks/exhaustive-deps

  const say = text => {
    clearTimeout(hintTimer.current);
    setHint(text);
    hintTimer.current = setTimeout(() => setHint(""), HINT_MS);
  };

  const send = useCallback((kind, args) => {
    if (ended || windowId == null) return;
    queue.current = queue.current.then(async () => {
      setBusy(true);
      try {
        await remoteCall("input", { connectionId, windowId, kind, ...args });
        setNotice("");
      } catch (error) {
        if (endsConnection(error.code)) stop(error);
        else {
          setNotice(message(error));
          if (error.code === "stale_element_token") reloadElements();
        }
      } finally {
        setBusy(false);
        refresh();
        log.refresh();
      }
    });
  }, [ended, windowId, connectionId, stop, refresh, log, reloadElements]);

  const flushText = useCallback(() => {
    const state = pending.current;
    clearTimeout(state.textTimer);
    if (state.text && typing) send("type_text", { element_token: typing.element_token, text: state.text });
    state.text = "";
  }, [send, typing]);

  const pickText = element => {
    flushText();
    setTyping(element);
    canvas.current?.focus({ preventScroll: true });
    say(`Typing goes to “${element.label || "the text box"}”. Ctrl+] to stop.`);
  };
  const clickElement = element => {
    flushText();
    setTyping(null);
    send("click", { element_token: element.element_token });
  };

  const point = event => toCapture(event.clientX, event.clientY, canvas.current?.getBoundingClientRect(), frame);

  const onPointerDown = event => {
    if (!frame || ended) return;
    const at = point(event);
    if (!at) return;
    canvas.current?.focus({ preventScroll: true });
    pending.current.down = { ...at, button: event.button };
  };
  const onPointerUp = event => {
    const down = pending.current.down;
    pending.current.down = null;
    if (!down || !frame) return;
    const at = point(event) || down;
    if (down.button !== 0) { say("Right-click only works at that PC itself."); return; }
    if (Math.hypot(at.x - down.x, at.y - down.y) > 8) { say("Dragging only works at that PC itself."); return; }
    setRipple({ ...at, id: Date.now() });
    const box = textBoxAt(elements, at.x, at.y);
    if (box) { pickText(box); return; }
    flushText();
    setTyping(null);
    send("click", { captureId: frame.captureId, x: at.x, y: at.y });
  };

  const onKeyDown = event => {
    if (event.key === "Tab") return; // keeps moving focus here; Tab isn't sent
    if (event.ctrlKey && event.key === "]") { event.preventDefault(); flushText(); setTyping(null); say("Stopped typing into that PC."); return; }
    const input = remoteKey(event);
    if (!input) return;
    if (!typing) {
      if (input.kind !== "blocked" || input.label !== "Enter") { event.preventDefault(); say("Click a text box in the window first, then type."); }
      return;
    }
    event.preventDefault();
    const state = pending.current;
    if (input.kind === "text") {
      state.text += input.text;
      clearTimeout(state.textTimer);
      state.textTimer = setTimeout(flushText, TYPE_FLUSH_MS);
      return;
    }
    if (input.kind === "blocked") { say(`${input.label} only works at that PC itself. Click its button here instead.`); return; }
    flushText();
    send("press_key", { element_token: typing.element_token, key: input.key });
  };
  const onPaste = event => {
    event.preventDefault();
    say("Pasting isn't sent to the other PC. Type it instead.");
  };

  useEffect(() => {
    const element = canvas.current;
    if (!element) return undefined;
    const onWheel = event => {
      event.preventDefault();
      if (!frame || ended) return;
      const now = Date.now();
      if (now - pending.current.scrollAt < SCROLL_GAP_MS || !event.deltaY) return;
      pending.current.scrollAt = now;
      const at = toCapture(event.clientX, event.clientY, element.getBoundingClientRect(), frame);
      const target = at && scrollerAt(elements, at.x, at.y);
      if (!target) { say("Nothing to scroll there."); return; }
      send("scroll", { element_token: target.element_token, direction: event.deltaY > 0 ? "down" : "up", amount: 1 });
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }); // re-bound every render: it reads the current frame and controls

  if (ended) return null;

  const hovered = hover ? clickableAt(elements, hover.x, hover.y) : null;
  const typingBox = typing?.screenshot_frame && frame ? boxStyle(typing.screenshot_frame, frame) : null;
  let blocked = null;
  if (windowId == null) blocked = { text: "That PC shared no window that is still open." };
  else if (problem && BLOCKING.has(problem.code)) blocked = { text: message(problem), lock: problem.code.startsWith("protect"), retry: true };
  else if (problem && !frame) blocked = { text: message(problem), retry: true };
  else if (!frame) blocked = { text: "Waiting for the first picture…", wait: true };

  return (
    <div className="nx-pv nx-rm-viewer">
      <div className="nx-fp-bar nx-pv-bar">
        <div className="nx-pv-tabs" role="tablist" aria-label="Shared windows">
          {windows.map(row => (
            <button key={row.window_id} type="button" role="tab" aria-selected={row.window_id === windowId}
              className={`nx-pv-tab${row.window_id === windowId ? " is-on" : ""}`} title={row.title} onClick={() => setWindowId(row.window_id)}>
              <Icon as={AppWindow} size={13} />
              <span>{row.title || row.app_name}</span>
            </button>
          ))}
        </div>
        <span className="nx-head-spacer" />
        <span className="nx-pv-control is-paul" title={connection.url}>
          {busy ? <Spinner size={10} /> : <StatusDot tone="live" pulse />}
          <span>Connected · {connection.url.replace(/^https?:\/\//, "")}</span>
        </span>
        <IconButton size="sm" icon={RefreshCw} label="Look again" onClick={() => { retry(); reloadElements(); }} />
        <Button size="sm" icon={Unplug} onClick={() => void remoteCall("disconnect", { connectionId }).catch(() => {}).finally(() => { void refreshRemote().catch(() => {}); stop({ code: "disconnected" }); })}>Disconnect</Button>
      </div>
      {notice ? (
        <div className="nx-fp-banner is-warn nx-pv-banner" role="alert">
          <Icon as={TriangleAlert} size={15} /><span>{notice}</span>
          <IconButton size="sm" icon={Check} label="Dismiss" onClick={() => setNotice("")} />
        </div>
      ) : null}
      <div className="nx-pv-body">
        <div className="nx-pv-view">
          {blocked ? (
            <div className="nx-pv-blocked nx-rm-blocked">
              {blocked.wait ? <Spinner size={14} /> : <Icon as={blocked.lock ? KeyRound : TriangleAlert} size={18} />}
              <span>{blocked.text}</span>
              {blocked.retry ? <Button size="sm" icon={RefreshCw} onClick={() => { retry(); reloadElements(); }}>Refresh</Button> : null}
            </div>
          ) : (
            <div
              ref={canvas}
              className={`nx-pv-canvas${typing ? " is-typing" : ""}`}
              style={frame?.width ? { "--pv-w": frame.width, "--pv-h": frame.height } : undefined}
              tabIndex={0}
              role="application"
              aria-roledescription="window on another PC"
              aria-label={`${windowRow?.title || "Shared window"} on ${connection.url}. Click a button to press it, click a text box to type into it. Control and right bracket stops typing.`}
              onPointerDown={onPointerDown}
              onPointerUp={onPointerUp}
              onPointerMove={event => setHover(point(event))}
              onPointerLeave={() => setHover(null)}
              onContextMenu={event => event.preventDefault()}
              onKeyDown={onKeyDown}
              onPaste={onPaste}
              onBlur={flushText}
            >
              <img src={frame.src} alt="" draggable={false} />
              {hovered && hovered.element_token !== typing?.element_token && boxStyle(hovered.screenshot_frame, frame) ? (
                <span className="nx-pv-hover" style={boxStyle(hovered.screenshot_frame, frame)}>
                  <span className="nx-pv-tag">{[hovered.label, (hovered.actions || []).includes("set_value") ? "type here" : "click"].filter(Boolean).join(" · ")}</span>
                </span>
              ) : null}
              {typingBox ? (
                <span className="nx-pv-focus is-paul nx-rm-target" style={typingBox}>
                  <span className="nx-pv-tag">Typing goes here</span>
                </span>
              ) : null}
              {ripple ? <span key={ripple.id} className="nx-pv-ripple" style={{ left: `${(ripple.x / frame.width) * 100}%`, top: `${(ripple.y / frame.height) * 100}%` }} /> : null}
              {hint ? <span className="nx-pv-typing nx-rm-hint" role="status">{hint}</span> : typing ? (
                <span className="nx-pv-typing"><Icon as={Keyboard} size={12} />Typing goes to {typing.label || "the text box"} · <Kbd>Ctrl</Kbd>+<Kbd>]</Kbd> to stop</span>
              ) : null}
            </div>
          )}
        </div>
        <aside className="nx-pv-side">
          <div className="nx-pv-owner">
            <Icon as={MonitorSmartphone} size={16} />
            <span>
              <strong>{windowRow?.app_name || "Shared app"}</strong>
              <small title={connection.url}>On {connection.url.replace(/^https?:\/\//, "")} · nothing is recorded</small>
            </span>
          </div>
          <ControlsList elements={blocked && !blocked.wait ? [] : elements} typing={typing} onClick={clickElement} onType={pickText} blocked={Boolean(blocked && !blocked.wait)} />
          <RemoteLog entries={log.entries} />
        </aside>
      </div>
      <div className="nx-fp-foot nx-pv-foot">
        <span>Click buttons, pick a text box and type. Enter, Tab and shortcuts only work at that PC. Passwords: type them there.</span>
      </div>
    </div>
  );
}

function UseSide({ connectionId: wanted, onPick }) {
  const { data, error } = useRemoteState();
  const connections = data?.connections || [];
  const [chosen, setChosen] = useState(wanted || "");
  const [endedNote, setEndedNote] = useState("");
  const [form, setForm] = useState(false);
  useEffect(() => { if (wanted) setChosen(wanted); }, [wanted]);
  const connected = connections.filter(row => row.status === "connected");
  const connection = (chosen && connected.find(row => row.id === chosen)) || (!form && !chosen ? connected[connected.length - 1] : null) || null;

  const ended = useCallback(error => {
    if (error?.code !== "disconnected") setEndedNote(`${refusalText(error?.code) || "The connection ended."} To use it again, ask that PC for a new code.`);
    else setEndedNote("");
    setChosen("");
    setForm(true);
    void refreshRemote().catch(() => {});
  }, []);

  if (!data && !error) return <div className="nx-stage-loading"><Spinner size={16} /></div>;
  if (!connection) {
    return (
      <>
        {connected.length ? (
          <div className="nx-fp-banner nx-pv-banner">
            <Icon as={Plug} size={15} /><span>{connected.length === 1 ? "You're connected to another PC." : `You're connected to ${connected.length} other PCs.`}</span>
            {connected.map(row => <Button key={row.id} size="sm" onClick={() => { setForm(false); setChosen(row.id); onPick?.(row.id); }}>Show {row.url.replace(/^https?:\/\//, "")}</Button>)}
          </div>
        ) : null}
        <ConnectForm endedNote={endedNote} onConnected={next => { setEndedNote(""); setForm(false); setChosen(next.id); onPick?.(next.id); }} />
      </>
    );
  }
  return <Viewer key={connection.id} connection={connection} onEnded={ended} />;
}

/** The remote control screen: embedded as a pane, or standalone at ?view=remote. */
export function NxRemote({ target, standalone = false }) {
  const parsed = useMemo(() => parseRemoteTarget(target), [target]);
  const { data, error } = useRemoteState();
  const [side, setSide] = useState(parsed.side || "");
  const [connectionId, setConnectionId] = useState(parsed.connectionId);
  useEffect(() => { if (parsed.side) setSide(parsed.side); setConnectionId(parsed.connectionId); }, [parsed.side, parsed.connectionId]);
  // Without a named side: the one that's in use, else using another PC.
  const shown = side || (liveSessions(data?.sessions).length && !(data?.connections || []).some(row => row.status === "connected") ? "host" : "use");

  if (error && !data && (error.code === "owner_required" || error.code === "missing" || error.code === "login_required")) {
    return <PaneMessage icon={MonitorUp} title="Remote control isn't available here">{refusalText(error.code)}</PaneMessage>;
  }
  const solo = () => {
    const query = new URLSearchParams({ view: "remote", side: shown, ...(shown === "use" && connectionId ? { connection: connectionId } : {}) });
    window.open(`${window.location.pathname}?${query}`, "_blank", "noopener");
  };
  return (
    <div className={`nx-rm${standalone ? " is-solo" : ""}`}>
      <div className="nx-fp-bar nx-rm-head">
        <Segmented size="sm" label="Remote control" value={shown} onChange={setSide}
          options={[{ value: "use", label: "Use another PC" }, { value: "host", label: "Share an app" }]} />
        <span className="nx-head-spacer" />
        {standalone ? (
          <a className="nx-btn nx-btn-ghost nx-btn-sm" href={window.location.pathname}><Icon as={ExternalLink} size={14} /><span className="nx-btn-label">Open Neyvia</span></a>
        ) : (
          <IconButton size="sm" icon={ExternalLink} label="Open in its own tab" onClick={solo} />
        )}
      </div>
      <div className="nx-rm-body">
        {shown === "host" ? <ShareSide /> : <UseSide connectionId={connectionId} onPick={setConnectionId} />}
      </div>
    </div>
  );
}
