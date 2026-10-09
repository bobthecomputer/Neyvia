import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AppWindow, BookOpen, Check, Hand, Keyboard, MonitorPlay, MonitorUp, Plus, Power, ScanEye, ScanText, ShieldCheck, TriangleAlert, X,
} from "lucide-react";

import { ProviderMark } from "./ProviderMark.jsx";
import { PaneMessage } from "./NxFilePane.jsx";
import { cuaClient, isMissing, switchToDemoDriver } from "./nxCuaApi.js";
import {
  agentName, boxStyle, effectLabel, elementAt, entryText, keyToInput, mergeLog, pickSession, refusalText, toCapture, wheelToScroll,
} from "./nxCuaModel.js";
import { Button, Icon, IconButton, Kbd, Popover, Segmented, Spinner, StatusDot } from "./nxPrimitives.jsx";
import { os } from "./nxOsStore.js";
import { PaneRefused, usePaneObservation } from "./NxPaneObserver.jsx";
import "./nxPreview.css";

// pane.show {kind: "preview"}: the live view of an app an agent is driving through the computer-use
// driver (plan 15 T16; contract in plans/15-handoff.md "## T16"). The window streams from the
// driver, the element the agent is about to act on is outlined, and one log shows the agent's
// actions and Paul's. Paul uses the app right here (click, type, scroll): his input goes to the
// background window through the same driver, without taking focus from what he is doing, and
// the agent sees it on its next step. Take over pauses the agent; Give back hands it a note.

const CLICK_WAIT_MS = 230; // a second click within this time makes a double-click
const TYPE_FLUSH_MS = 280; // characters typed within this time go as one type_text
const SCROLL_FLUSH_MS = 90;
const FOCUS_SHOW_MS = 2400;
const REPORT_EVERY_MS = 1000; // frames stream fast; the observation follows them at most once a second

/** The driver's state for this pane: sessions, the shown session's frames, focus and log. */
function useCuaLive(target) {
  const [client, setClient] = useState(null);
  const [status, setStatus] = useState("loading"); // loading | ready | missing | error
  const [error, setError] = useState("");
  const [driver, setDriver] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [chosen, setChosen] = useState(target || "");
  const [frames, setFrames] = useState({});
  const [focus, setFocus] = useState(null);
  const [log, setLog] = useState([]);
  const [stream, setStream] = useState("connecting");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => { setChosen(target || ""); }, [target]);

  useEffect(() => {
    let alive = true;
    setStatus("loading");
    (async () => {
      try {
        const next = await cuaClient();
        const state = await next.state("");
        if (!alive) return;
        setClient(next);
        setDriver(state.driver || null);
        setSessions(state.sessions || []);
        setStatus("ready");
      } catch (failure) {
        if (!alive) return;
        setStatus(isMissing(failure) ? "missing" : "error");
        setError(failure?.message || "The computer-use driver could not be read.");
      }
    })();
    return () => { alive = false; };
  }, [attempt]);

  const session = useMemo(() => pickSession(sessions, chosen), [sessions, chosen]);
  const sessionId = session?.id || "";

  // One stream for the shown session (all sessions while there is none, to notice a new one).
  useEffect(() => {
    if (!client || status !== "ready") return undefined;
    setLog([]);
    setFrames({});
    setFocus(null);
    return client.subscribe(sessionId, {
      onState: setStream,
      onEvent: event => {
        const { type, data } = event;
        if (type === "session" && data?.id) {
          setSessions(current => (current.some(row => row.id === data.id) ? current.map(row => (row.id === data.id ? data : row)) : [...current, data]));
        } else if (event.sessionId && sessionId && event.sessionId !== sessionId) {
          // another session's frame or log: not shown here
        } else if (type === "frame" && data) {
          setFrames(current => (current[data.windowId]?.seq >= data.seq ? current : { ...current, [data.windowId]: data }));
        } else if (type === "focus" && data) {
          setFocus({ ...data, shownAt: Date.now() });
        } else if (type === "log" && data?.id) {
          setLog(current => mergeLog(current, data));
        }
      },
    });
  }, [client, status, sessionId]);

  const call = useCallback(async (op, args = {}) => {
    const result = await client.call(op, { sessionId, ...args });
    if (result && result.id && Array.isArray(result.windows)) setSessions(current => current.map(row => (row.id === result.id ? result : row)));
    return result;
  }, [client, sessionId]);

  return {
    client, status, error, driver, sessions, session, frames, focus, log, stream, call, choose: setChosen,
    retry: () => setAttempt(value => value + 1),
    setFocus,
  };
}

/** The latest image of a window, swapped only once the next one has loaded (no flashing). */
function useFrameImage(client, sessionId, windowId, frame) {
  const [shown, setShown] = useState(null);
  useEffect(() => {
    if (!client || !sessionId || windowId == null || !frame || frame.unavailable) return undefined;
    const url = client.frameUrl(sessionId, windowId, frame.seq);
    let cancelled = false;
    const image = new Image();
    image.onload = () => { if (!cancelled) setShown({ src: url, frame, sessionId, windowId }); };
    image.src = url;
    return () => { cancelled = true; };
  }, [client, sessionId, windowId, frame?.seq, frame?.unavailable]);
  return shown?.sessionId === sessionId && shown?.windowId === windowId ? shown : null;
}

/** The helper isn't set up: say so in plain words and offer the one action that fixes it.
 * The technical route (file names, script, folder) stays folded under Details. */
function DriverSetup({ live }) {
  const driver = live.driver || {};
  const [install, setInstall] = useState(driver.install || { state: "idle" });
  const [problem, setProblem] = useState("");
  const running = install.state === "running";
  const failed = install.state === "failed" ? install.error : problem;
  const canInstall = Boolean(driver.setup?.canInstall);
  const { client, retry } = live;
  // While the helper is being set up, read its progress quietly every two seconds (no reload
  // flicker); once it verifies, the pane reloads into its normal view by itself.
  useEffect(() => {
    if (!running || !client) return undefined;
    const timer = setInterval(async () => {
      try {
        const next = (await client.state(""))?.driver || {};
        if (next.available) retry(); else setInstall(next.install || { state: "idle" });
      } catch { /* keep the last state; the next tick tries again */ }
    }, 2000);
    return () => clearInterval(timer);
  }, [running, client, retry]);
  const start = async () => {
    setProblem(""); setInstall({ state: "running" });
    try { const result = await client.call("install_driver", {}); if (result?.install?.state === "done") retry(); else if (result?.install) setInstall(result.install); }
    catch (failure) { setInstall({ state: "idle" }); setProblem(failure?.message || "The helper couldn't be set up."); }
  };
  return (
    <div className="nx-pv-idle nx-pv-setup" data-driver-state={running ? "installing" : failed ? "failed" : driver.code || "missing"}>
      <PaneRefused reason={driver.reason || "The screen-control helper isn't set up on this PC yet."} />
      {/* What this view is for: an app window an agent is driving, its cursor and the control it is about to use. */}
      <div className="nx-pv-idle-art" aria-hidden="true">
        <span className="nx-pv-idle-win"><i /><i /><i /><b /><b /><b className="is-target" /></span>
        <span className="nx-pv-idle-cursor" />
      </div>
      <strong>Watch agents use apps, live</strong>
      <p>When an agent uses an app on this PC, you see it here, follow every click and can take over.</p>
      <p className="nx-pv-setup-why">
        {running ? "Setting up the screen-control helper. This takes a moment…"
          : canInstall ? `This needs Neyvia's screen-control helper (${driver.setup.sizeMb || 31} MB, open source). It stays inside Neyvia: nothing is installed system-wide.`
            : driver.reason || "The screen-control helper isn't ready on this PC."}
      </p>
      {failed ? <p className="nx-pv-setup-problem" role="alert"><Icon as={TriangleAlert} size={13} />{failed}</p> : null}
      <div className="nx-pv-idle-actions">
        {canInstall ? (
          <Button variant="primary" onClick={start} disabled={running}>{running ? <><Spinner size={13} /> Setting up…</> : failed ? "Try again" : "Set up the helper"}</Button>
        ) : null}
        <Button variant={canInstall ? "ghost" : "primary"} onClick={retry} disabled={running}>Check again</Button>
      </div>
      {driver.detail ? (
        <details className="nx-pv-setup-details">
          <summary>Details</summary>
          <p>{driver.detail}</p>
        </details>
      ) : null}
    </div>
  );
}

/** The window itself: Paul's mouse, wheel and keys go to it through the driver. */
function Viewer({ live, windowRow, frame: incomingFrame, agent, showElements, onRetryForeground }) {
  const { client, session, focus } = live;
  const canvas = useRef(null);
  const viewer = useRef(null);
  const [available, setAvailable] = useState(null);
  const shown = useFrameImage(client, session.id, windowRow?.window_id, incomingFrame);
  // Image preload and SSE arrival are independent. Pixels, dimensions and
  // forwarded captureId must change together when the image has loaded.
  const src = shown?.src || "";
  const frame = incomingFrame?.unavailable ? incomingFrame : shown?.frame;
  const [elements, setElements] = useState([]);
  const [hover, setHover] = useState(null);
  const [typing, setTyping] = useState(false);
  const [ripple, setRipple] = useState(null);
  const [, setTick] = useState(0);
  const queue = useRef(Promise.resolve());
  const pending = useRef({ click: null, text: "", textTimer: 0, scroll: null, scrollTimer: 0, down: null, last: null });
  const windowId = windowRow?.window_id;
  const ended = session.status !== "active";
  const observation = usePaneObservation();

  // Use the viewer's actual content box. Embedded engines can resolve cq
  // units against a different container, clipping the native controls.
  useEffect(() => {
    const element = viewer.current;
    if (!element) return undefined;
    const measure = () => setAvailable({ width: Math.max(0, element.clientWidth - 24), height: Math.max(0, element.clientHeight - 24) });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const scale = available && frame?.width && frame?.height
    ? Math.min(available.width / frame.width, available.height / frame.height, 1.5) : null;

  // The element tree (cua get_window_state) for hover labels and "Show elements", refreshed per frame.
  const wantTree = showElements || hover != null;
  useEffect(() => {
    if (!wantTree || windowId == null || !frame || frame.unavailable) return undefined;
    let alive = true;
    const timer = setTimeout(async () => {
      try {
        const tree = await live.call("snapshot", { windowId });
        if (alive) setElements(Array.isArray(tree?.elements) ? tree.elements : []);
      } catch { if (alive) setElements([]); }
    }, 250);
    return () => { alive = false; clearTimeout(timer); };
  }, [wantTree, windowId, frame?.seq]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fade the agent's highlight after a moment.
  useEffect(() => {
    if (!focus) return undefined;
    const timer = setTimeout(() => setTick(value => value + 1), FOCUS_SHOW_MS + 50);
    return () => clearTimeout(timer);
  }, [focus]);

  const send = useCallback((kind, args) => {
    if (ended || !frame) return;
    const payload = { windowId, kind, captureId: frame.captureId, ...args };
    queue.current = queue.current.then(async () => {
      try {
        const entry = await live.call("input", payload);
        if (entry?.result?.error?.code === "background_unavailable") onRetryForeground(payload);
      } catch { /* the log shows what the service answered */ }
    });
  }, [ended, frame, windowId, live, onRetryForeground]);

  const flushText = useCallback(() => {
    const state = pending.current;
    clearTimeout(state.textTimer);
    if (state.text) { send("type_text", { text: state.text }); state.text = ""; }
  }, [send]);

  const point = event => toCapture(event.clientX, event.clientY, canvas.current?.getBoundingClientRect(), frame);

  const onPointerDown = event => {
    if (event.button !== 0 && event.button !== 2) return;
    const at = point(event);
    if (!at) return;
    canvas.current?.focus({ preventScroll: true });
    setTyping(true);
    pending.current.down = { ...at, button: event.button };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };
  const onPointerUp = event => {
    const state = pending.current;
    const down = state.down;
    state.down = null;
    if (!down) return;
    const at = point(event) || down;
    flushText();
    setRipple({ ...at, id: Date.now() });
    if (down.button === 0 && Math.hypot(at.x - down.x, at.y - down.y) > 6) {
      send("drag", { x: down.x, y: down.y, to_x: at.x, to_y: at.y });
      return;
    }
    if (down.button === 2) { send("right_click", { x: at.x, y: at.y }); return; }
    if (state.click && Math.hypot(at.x - state.click.x, at.y - state.click.y) < 8) {
      clearTimeout(state.click.timer);
      state.click = null;
      send("double_click", { x: at.x, y: at.y });
      return;
    }
    const timer = setTimeout(() => { state.click = null; send("click", { x: at.x, y: at.y }); }, CLICK_WAIT_MS);
    state.click = { ...at, timer };
  };
  const onPointerMove = event => {
    const at = point(event);
    pending.current.last = at;
    setHover(at);
  };

  // The wheel needs a non-passive listener to keep the pane itself from scrolling.
  useEffect(() => {
    const element = canvas.current;
    if (!element) return undefined;
    const onWheel = event => {
      event.preventDefault();
      const state = pending.current;
      const at = toCapture(event.clientX, event.clientY, element.getBoundingClientRect(), frame);
      if (!at) return;
      const acc = state.scroll || { dx: 0, dy: 0, mode: event.deltaMode, at };
      state.scroll = { dx: acc.dx + event.deltaX, dy: acc.dy + event.deltaY, mode: event.deltaMode, at };
      clearTimeout(state.scrollTimer);
      state.scrollTimer = setTimeout(() => {
        const done = state.scroll;
        state.scroll = null;
        const scroll = done && wheelToScroll(done.dx, done.dy, done.mode);
        if (scroll) send("scroll", { ...scroll, x: done.at.x, y: done.at.y });
      }, SCROLL_FLUSH_MS);
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }, [frame, send]);

  const onKeyDown = event => {
    if (event.ctrlKey && event.key === "]") { event.preventDefault(); flushText(); setTyping(false); return; }
    if (!typing) {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setTyping(true); }
      return;
    }
    const input = keyToInput(event);
    if (!input) return;
    event.preventDefault();
    const state = pending.current;
    if (input.kind === "text") {
      state.text += input.text;
      clearTimeout(state.textTimer);
      state.textTimer = setTimeout(flushText, TYPE_FLUSH_MS);
      return;
    }
    flushText();
    if (input.kind === "hotkey") send("hotkey", { keys: input.keys });
    else send("press_key", input.modifiers ? { key: input.key, modifiers: input.modifiers } : { key: input.key });
  };
  const onPaste = event => {
    if (!typing) return;
    const text = event.clipboardData?.getData("text/plain");
    if (!text) return;
    event.preventDefault();
    flushText();
    send("type_text", { text: text.slice(0, 5000) });
  };

  const hovered = hover ? elementAt(elements, hover.x, hover.y) : null;
  const focusHere = focus && focus.windowId === windowId && (focus.phase === "about" || Date.now() - focus.shownAt < FOCUS_SHOW_MS) ? focus : null;
  const focusBox = focusHere?.element?.frame ? boxStyle(focusHere.element.frame, frame) : null;
  const focusPoint = focusHere?.point && frame ? { left: `${(focusHere.point.x / frame.width) * 100}%`, top: `${(focusHere.point.y / frame.height) * 100}%` } : null;
  const byPaul = focusHere?.by === "paul";

  let blocked = null;
  if (!windowRow) blocked = "Pick a window above.";
  else if (!windowRow.allowed || frame?.unavailable === "not_allowed") blocked = `${windowRow.app_name} isn't on the allowed list, so it isn't shown or used.`;
  else if (frame?.unavailable === "minimized" || windowRow.minimized) blocked = `${windowRow.app_name} is minimized. The driver can't see a minimized window.`;
  else if (frame?.unavailable === "closed") blocked = `${windowRow.app_name} was closed.`;
  else if (frame?.unavailable === "protected") blocked = `${windowRow.app_name} protects its content from capture.`;
  else if (frame?.unavailable === "capture_unavailable") blocked = `Couldn't capture ${windowRow.app_name}. Try a fresh observation.`;
  else if (!frame) blocked = "Waiting for the first picture…";

  // Observation: the driver session's window and the frame this view has really loaded and shows.
  const shownFrame = !blocked && src ? frame : null;
  const lastReport = useRef(0);
  useEffect(() => {
    if (!shownFrame) { observation.withdraw(); return undefined; }
    const send = () => {
      lastReport.current = Date.now();
      void observation.report({
        runtimeId: `cua:${session.id}:${windowId}`.slice(0, 128),
        content: JSON.stringify({ app: windowRow.app_name, title: windowRow.title, captureId: shownFrame.captureId ?? null, seq: shownFrame.seq ?? null, width: shownFrame.width, height: shownFrame.height, src }),
      });
    };
    const wait = REPORT_EVERY_MS - (Date.now() - lastReport.current);
    if (wait <= 0) { send(); return undefined; }
    const timer = setTimeout(send, wait);
    return () => clearTimeout(timer);
  }, [observation, session.id, windowId, shownFrame, src]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="nx-pv-view" ref={viewer}>
      {blocked ? (
        <div className="nx-pv-blocked">{!frame && !windowRow?.minimized && windowRow?.allowed ? <Spinner size={14} /> : <Icon as={AppWindow} size={18} />}<span>{blocked}</span></div>
      ) : (
        <div
          ref={canvas}
          className={`nx-pv-canvas${typing ? " is-typing" : ""}${ended ? " is-ended" : ""}`}
          style={frame?.width ? { "--pv-w": frame.width, "--pv-h": frame.height,
            ...(scale != null ? { width: frame.width * scale, height: frame.height * scale } : {}) } : undefined}
          tabIndex={0}
          data-nx-comment-target={`preview:${session.id}:${windowId}`} data-nx-comment-kind="image" data-nx-comment-label={windowRow.app_name}
          role="application"
          aria-roledescription="app window"
          aria-label={`${windowRow.app_name}: ${windowRow.title}. Click or press Enter to use it here; Control and right bracket to stop typing into it.`}
          onPointerDown={onPointerDown}
          onPointerUp={onPointerUp}
          onPointerMove={onPointerMove}
          onPointerLeave={() => setHover(null)}
          onContextMenu={event => event.preventDefault()}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
          onBlur={() => { flushText(); setTyping(false); }}
        >
          {src ? <img src={src} alt="" draggable={false} /> : <span className="nx-pv-wait"><Spinner size={14} /></span>}
          {showElements ? elements.map(element => {
            const style = boxStyle(element.screenshot_frame, frame);
            return style ? <span key={element.element_token || element.element_index} className="nx-pv-el" style={style} /> : null;
          }) : null}
          {hovered && boxStyle(hovered.screenshot_frame, frame) ? (
            <span className="nx-pv-hover" style={boxStyle(hovered.screenshot_frame, frame)}>
              <span className="nx-pv-tag">{[hovered.role, hovered.label].filter(Boolean).join(" Â· ")}</span>
            </span>
          ) : null}
          {focusBox ? (
            <span className={`nx-pv-focus is-${focusHere.phase}${byPaul ? " is-paul" : ""}`} style={focusBox}>
              <span className="nx-pv-tag">{byPaul ? "You" : agent}{focusHere.element?.label ? ` Â· ${focusHere.element.label}` : ""}</span>
            </span>
          ) : null}
          {focusPoint && !byPaul ? <span className={`nx-pv-cursor is-${focusHere.phase}`} style={focusPoint} /> : null}
          {ripple && frame ? <span key={ripple.id} className="nx-pv-ripple" style={{ left: `${(ripple.x / frame.width) * 100}%`, top: `${(ripple.y / frame.height) * 100}%` }} /> : null}
          {typing ? (
            <span className="nx-pv-typing"><Icon as={Keyboard} size={12} />Typing goes to {windowRow.app_name} Â· <Kbd>Ctrl</Kbd>+<Kbd>]</Kbd> to stop</span>
          ) : null}
        </div>
      )}
    </div>
  );
}

function Who({ entry, owner }) {
  if (entry.by === "paul") return <span className="nx-pv-who is-paul" aria-label="You">You</span>;
  if (entry.by === "driver") return <span className="nx-pv-who is-driver" aria-label="Driver"><Icon as={ShieldCheck} size={12} /></span>;
  return <span className="nx-pv-who is-agent" aria-label={entry.who || "Agent"}><ProviderMark id={owner?.app === "claude-code" ? "claude" : owner?.app || "neyvia"} size={14} /></span>;
}

const time = value => { try { return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); } catch { return ""; } };

function ActivityLog({ log, session, agent, onApprove, onShow }) {
  const [filter, setFilter] = useState("all");
  const list = useRef(null);
  const shown = filter === "all" ? log : log.filter(entry => (filter === "paul" ? entry.by === "paul" : entry.by !== "paul"));
  const stick = useRef(true);
  useEffect(() => {
    const element = list.current;
    if (element && stick.current) element.scrollTop = element.scrollHeight;
  }, [shown.length, shown[shown.length - 1]?.status]);
  const pendingIds = new Set((session.approvals || []).map(row => row.id));
  return (
    <section className="nx-pv-log" aria-label="Activity">
      <header>
        <strong>Activity</strong>
        <Segmented size="sm" label="Show" value={filter} onChange={setFilter}
          options={[{ value: "all", label: "All" }, { value: "agent", label: agent }, { value: "paul", label: "You" }]} />
      </header>
      <ol ref={list} className="nx-scroll" aria-live="polite" aria-relevant="additions"
        onScroll={event => { const element = event.currentTarget; stick.current = element.scrollHeight - element.scrollTop - element.clientHeight < 40; }}>
        {shown.length ? shown.map(entry => {
          const refusal = entry.result?.error?.code;
          const effect = entry.status === "ok" && entry.tool !== "note" && entry.tool !== "control" && entry.tool !== "allow" ? effectLabel(entry.result) : "";
          const pending = entry.status === "pending_approval" && (!entry.approvalId || pendingIds.has(entry.approvalId));
          return (
            <li key={entry.id} className={`nx-pv-entry is-${entry.by} is-${entry.status}${entry.tool === "note" ? " is-note" : ""}`}>
              <Who entry={entry} owner={session.owner} />
              <div className="nx-pv-entry-main">
                <button type="button" className="nx-pv-entry-text" disabled={!entry.element} onClick={() => onShow(entry)}
                  title={entry.element ? "Show where this happened" : undefined}>{entryText(entry)}</button>
                <span className="nx-pv-entry-meta">
                  {[entry.app, effect, refusal ? refusalText(refusal) || refusal : entry.status === "failed" ? "failed" : entry.status === "denied" ? "you said no" : "", time(entry.at)].filter(Boolean).join(" Â· ")}
                </span>
                {pending && entry.approvalId ? (
                  <span className="nx-pv-entry-ask">
                    <Button size="sm" variant="primary" icon={Check} onClick={() => onApprove(entry.approvalId, "allow")}>Allow</Button>
                    <Button size="sm" icon={X} onClick={() => onApprove(entry.approvalId, "deny")}>Don't</Button>
                  </span>
                ) : null}
              </div>
            </li>
          );
        }) : <li className="nx-pv-log-empty">{filter === "paul" ? "Nothing from you yet. Click or type in the window to use the app." : "Nothing yet."}</li>}
      </ol>
    </section>
  );
}

function AllowedApps({ session, call }) {
  const anchor = useRef(null);
  const [open, setOpen] = useState(false);
  const [apps, setApps] = useState(null);
  const [busy, setBusy] = useState("");
  const allowed = session.allow || [];
  const openPicker = async () => {
    setOpen(true);
    setApps(null);
    try {
      const result = await call("apps", {});
      setApps(Array.isArray(result?.apps) ? result.apps : Array.isArray(result) ? result : []);
    } catch { setApps([]); }
  };
  const change = async (app, name, on) => {
    setBusy(app);
    try { await call("allow", { app, name, allowed: on }); } catch { /* the session event shows the truth */ }
    setBusy("");
  };
  const processOf = app => app.process || app.aumid || app.bundle_id || app.name;
  const candidates = (apps || []).filter(app => !allowed.some(row => row.app === processOf(app)));
  return (
    <section className="nx-pv-apps" aria-label="Allowed apps">
      <header>
        <strong>Allowed apps</strong>
        <Button ref={anchor} size="sm" icon={Plus} onClick={openPicker} disabled={session.status === "ended"}>Allow an app</Button>
      </header>
      {allowed.length ? (
        <ul>
          {allowed.map(row => (
            <li key={row.app}>
              <Icon as={AppWindow} size={13} />
              <span title={row.app}>{row.name || row.app}</span>
              {row.by === "agent" ? <small>asked by the agent</small> : null}
              <IconButton size="sm" icon={busy === row.app ? undefined : X} label={`Remove ${row.name || row.app}`} onClick={() => change(row.app, row.name, false)} disabled={busy === row.app}>
                {busy === row.app ? <Spinner size={10} /> : null}
              </IconButton>
            </li>
          ))}
        </ul>
      ) : <p>No app yet. The agent can only see and use the apps listed here.</p>}
      {session.foregroundAvailable ? <label className="nx-pv-switch">
        <input type="checkbox" checked={Boolean(session.foreground)} disabled={session.status === "ended"}
          onChange={event => void call("foreground", { allowed: event.target.checked }).catch(() => {})} />
        <span>Let it bring a window to the front when it must</span>
      </label> : null}
      <Popover anchor={anchor} open={open} onClose={() => setOpen(false)} placement="top-end" width={260} label="Apps on this PC">
        <div className="nx-pv-picker">
          {apps == null ? <p><Spinner size={11} /> Looking at what's open…</p> : candidates.length ? candidates.map(app => (
            <button key={processOf(app)} type="button" onClick={() => { setOpen(false); void change(processOf(app), app.name, true); }}>
              <Icon as={AppWindow} size={13} /><span>{app.name}</span><small>{processOf(app)}</small>
            </button>
          )) : <p>Every open app is already allowed.</p>}
        </div>
      </Popover>
    </section>
  );
}

function GiveBack({ agent, onGive }) {
  const anchor = useRef(null);
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const give = () => { setOpen(false); onGive(note.trim()); setNote(""); };
  return (
    <>
      <Button ref={anchor} size="sm" variant="primary" icon={MonitorPlay} onClick={() => setOpen(value => !value)}>Give back</Button>
      <Popover anchor={anchor} open={open} onClose={() => setOpen(false)} placement="bottom-end" width={300} label="Give control back">
        <div className="nx-pv-give">
          <label htmlFor="nx-pv-note">Anything {agent} should know? <small>(optional)</small></label>
          <textarea id="nx-pv-note" data-autofocus rows={3} maxLength={1000} value={note} placeholder="I fixed the total, check the Save button next"
            onChange={event => setNote(event.target.value)}
            onKeyDown={event => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) give(); }} />
          <Button size="sm" variant="primary" onClick={give}>Give back to {agent}</Button>
        </div>
      </Popover>
    </>
  );
}

function Approvals({ session, agent, onApprove }) {
  const approvals = session.approvals || [];
  if (!approvals.length) return null;
  return approvals.map(row => (
    <div key={row.id} className="nx-fp-banner is-needs nx-pv-banner" role="alert">
      <Icon as={Hand} size={15} />
      <span>
        <strong>{row.kind === "session" ? `${agent} wants to use ${row.app || "an app"}.` : row.kind === "app" ? `${agent} wants to open ${row.app || "an app"}.` : `${agent} wants to:`}</strong>{" "}
        {row.kind === "action" ? row.summary : row.summary && row.kind !== "session" ? row.summary : ""}
      </span>
      <Button size="sm" variant="primary" icon={Check} onClick={() => onApprove(row.id, "allow")}>Allow</Button>
      <Button size="sm" icon={X} onClick={() => onApprove(row.id, "deny")}>Don't</Button>
    </div>
  ));
}

function StartSession({ chat, call, title, children }) {
  const anchor = useRef(null);
  const [open, setOpen] = useState(false);
  const [apps, setApps] = useState(null);
  const [error, setError] = useState("");
  const pick = async () => {
    setOpen(true);
    try { const result = await call("apps", {}); setApps(result?.apps || []); } catch (failure) { setApps([]); setError(failure?.message || ""); }
  };
  const start = async app => {
    setOpen(false);
    try { await call("open", { chatId: chat?.id || null, apps: [app.process || app.aumid || app.name] }); } catch (failure) { setError(failure?.message || "Couldn't start."); }
  };
  return (
    <PaneMessage icon={MonitorPlay} title={title} action={(
      <>
        <Button ref={anchor} variant="primary" icon={Plus} onClick={pick}>Let an agent use an app…</Button>
        <Popover anchor={anchor} open={open} onClose={() => setOpen(false)} placement="bottom-start" width={260} label="Apps on this PC">
          <div className="nx-pv-picker">
            {apps == null ? <p><Spinner size={11} /> Looking at what's open…</p> : apps.length ? apps.map(app => (
              <button key={app.process || app.name} type="button" onClick={() => void start(app)}>
                <Icon as={AppWindow} size={13} /><span>{app.name}</span><small>{app.process || ""}</small>
              </button>
            )) : <p>No open apps found.</p>}
          </div>
        </Popover>
        {error ? <p className="nx-pv-error">{error}</p> : null}
      </>
    )}>{children}</PaneMessage>
  );
}

export function NxPreviewPane({ target, session: chat }) {
  const live = useCuaLive(target);
  const { status, session, frames, log, stream, call } = live;
  const [windowId, setWindowId] = useState(null);
  const [showElements, setShowElements] = useState(false);
  const [retry, setRetry] = useState(null);
  const [notice, setNotice] = useState("");

  const windows = session?.windows || [];
  const shownWindows = windows.filter(row => row.allowed);
  const following = useRef(true); // follow the window the agent works in until Paul picks one
  useEffect(() => {
    if (!session) return;
    const known = windows.some(row => row.window_id === windowId);
    // A bounded native read may temporarily omit a busy window. Preserve an
    // explicit choice rather than redirecting its preview input to a helper.
    if (following.current && (!known || (session.focusWindow != null && session.focusWindow !== windowId))) {
      setWindowId(following.current && session.focusWindow != null ? session.focusWindow : (shownWindows[0] || windows[0])?.window_id ?? null);
    }
  }, [session?.focusWindow, windows.length]); // eslint-disable-line react-hooks/exhaustive-deps
  // The agent moved to another window: follow it (unless Paul picked a window himself).
  useEffect(() => {
    const focus = live.focus;
    if (focus?.by === "agent" && following.current && focus.windowId != null && focus.windowId !== windowId) setWindowId(focus.windowId);
  }, [live.focus]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = useCallback(async (op, args) => {
    setNotice("");
    try { return await call(op, args); } catch (failure) { setNotice(failure?.message || "That didn't work."); return null; }
  }, [call]);

  if (status === "loading") return <div className="nx-stage-loading"><Spinner size={16} /></div>;
  if (status === "missing") {
    return (
      <PaneMessage icon={MonitorPlay} title="Computer use isn't on this PC's service yet"
        action={import.meta.env.DEV ? <Button icon={MonitorPlay} onClick={() => { switchToDemoDriver(); live.retry(); }}>Show the demo</Button> : null}>
        <PaneRefused reason="Computer use isn't on this PC's service yet" />When it is, every app an agent drives shows here live, and you can use the app together with it.
      </PaneMessage>
    );
  }
  if (status === "error") return <PaneMessage icon={TriangleAlert} title="Computer use can't be read" action={<Button onClick={live.retry}>Try again</Button>}><PaneRefused reason={live.error} />{live.error}</PaneMessage>;
  if (live.driver && live.driver.available === false) return <DriverSetup live={live} />;
  if (!session) {
    return (
      <StartSession chat={chat} call={act} title={target ? "That session isn't here any more" : "No agent is using an app right now"}>
        <PaneRefused reason={target ? "That computer-use session isn't here any more" : "No agent is using an app right now"} />When an agent asks to use an app, you're asked here first and then see it live. You can also start one now and tell the agent in chat.
      </StartSession>
    );
  }

  const agent = agentName(session);
  const windowRow = windows.find(row => row.window_id === windowId) || null;
  const frame = (windowId != null && frames[windowId]) || windowRow?.frame || null;
  const paulHas = session.control === "paul";
  const ended = session.status === "ended";
  const pendingSession = session.status === "pending";

  const approve = (approvalId, decision) => void act("approve", { approvalId, decision });
  const showEntry = entry => {
    if (entry.windowId != null) { following.current = false; setWindowId(entry.windowId); }
    if (entry.element) live.setFocus({ windowId: entry.windowId, by: entry.by, tool: entry.tool, phase: "done", element: entry.element, point: null, shownAt: Date.now() });
  };

  return (
    <div className="nx-pv">
      <div className="nx-fp-bar nx-pv-bar">
        <div className="nx-pv-tabs" role="tablist" aria-label="Windows">
          {windows.map(row => (
            <button key={row.window_id} type="button" role="tab" aria-selected={row.window_id === windowId}
              className={`nx-pv-tab${row.window_id === windowId ? " is-on" : ""}${row.allowed ? "" : " is-off"}`}
              title={row.allowed ? row.title : `${row.app_name} isn't allowed`}
              onClick={() => { following.current = false; setWindowId(row.window_id); }}>
              <Icon as={AppWindow} size={13} />
              <span>{row.app_name}</span>
              {row.window_id === session.focusWindow && !paulHas && !ended ? <StatusDot tone="live" pulse /> : null}
            </button>
          ))}
        </div>
        <span className="nx-head-spacer" />
        {windowRow?.manual ? <span className="nx-fp-chip" title={`Manual: ${windowRow.manual}`}><Icon as={BookOpen} size={11} /> Manual</span> : null}
        <span className={`nx-pv-control${paulHas ? " is-paul" : ""}${ended ? " is-ended" : ""}`}>
          {ended ? "Ended" : pendingSession ? "Waiting for you" : paulHas ? "You have control" : <><StatusDot tone="live" pulse />{agent} is working Â· you can use it too</>}
        </span>
        <IconButton size="sm" icon={ScanEye} label={showElements ? "Hide elements" : "Show elements"} active={showElements} onClick={() => setShowElements(value => !value)} />
        {windowId != null && !ended ? <IconButton size="sm" icon={ScanText} label="See it as the agent reads it" onClick={() => os.showPane("perception", `window:${session.id}:${windowId}`)} /> : null}
        {ended ? (
          <Button size="sm" icon={MonitorPlay} onClick={() => void act("open", { chatId: session.owner?.chatId || chat?.id || null, apps: (session.allow || []).map(row => row.app) })}>Start again</Button>
        ) : paulHas ? (
          <GiveBack agent={agent} onGive={note => void act("control", { mode: "agent", note })} />
        ) : (
          <Button size="sm" icon={Hand} onClick={() => void act("control", { mode: "paul" })} disabled={pendingSession}>Take over</Button>
        )}
        {!ended ? <IconButton size="sm" icon={Power} label="End this session" onClick={() => void act("end", {})} /> : null}
      </div>
      <Approvals session={session} agent={agent} onApprove={approve} />
      {paulHas && session.pausedReason === "real_input" ? (
        <div className="nx-fp-banner is-warn nx-pv-banner"><Icon as={Hand} size={15} /><span>{agent} paused because you used {windowRow?.app_name || "the app"} yourself. Give it back when you're done.</span></div>
      ) : null}
      {retry ? (
        <div className="nx-fp-banner is-warn nx-pv-banner">
          <Icon as={TriangleAlert} size={15} />
          <span>{windowRow?.app_name || "The app"} didn't take that in the background.{session.foregroundAvailable ? " Bringing it forward once will take focus for a moment." : " Refresh its state before trying again."}</span>
          {session.foregroundAvailable ? <Button size="sm" icon={MonitorUp} onClick={() => { const payload = retry; setRetry(null); void act("input", { ...payload, delivery_mode: "foreground" }); }}>Bring forward once</Button> : null}
          <IconButton size="sm" icon={X} label="Dismiss" onClick={() => setRetry(null)} />
        </div>
      ) : null}
      {notice ? <div className="nx-fp-banner is-warn nx-pv-banner" role="alert"><Icon as={TriangleAlert} size={15} /><span>{notice}</span><IconButton size="sm" icon={X} label="Dismiss" onClick={() => setNotice("")} /></div> : null}
      <div className="nx-pv-body">
        <Viewer live={live} windowRow={windowRow} frame={frame} agent={agent} showElements={showElements} onRetryForeground={setRetry} />
        <aside className="nx-pv-side">
          <div className="nx-pv-owner">
            <ProviderMark id={session.owner?.app === "claude-code" ? "claude" : session.owner?.app || "neyvia"} size={16} />
            <span>
              <strong>{agent}</strong>
              <small title={session.owner?.title || ""}>{session.owner?.title || "Not tied to a chat"}</small>
            </span>
            <small className="nx-pv-counts">{session.counts?.agent || 0} by {agent} Â· {session.counts?.paul || 0} by you</small>
          </div>
          <ActivityLog log={log} session={session} agent={agent} onApprove={approve} onShow={showEntry} />
          <AllowedApps session={session} call={act} />
        </aside>
      </div>
      <div className="nx-fp-foot nx-pv-foot">
        <span>Click, type and scroll in the window to use it yourself. It stays in the background; your own windows keep focus.</span>
        <span className="nx-head-spacer" />
        {live.client?.demo ? <span className="nx-fp-chip">Demo driver</span> : null}
        <span>{stream === "live" ? "Live" : stream === "reconnecting" ? "Reconnecting…" : "Connecting…"}</span>
      </div>
    </div>
  );
}
