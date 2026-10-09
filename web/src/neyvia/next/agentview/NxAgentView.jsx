import { useEffect, useMemo, useRef, useState } from "react";
import {
  AppWindow, Check, CheckCheck, Clock, Command, Globe, Hammer, Hand, History, Keyboard, MessageSquare, MessageSquarePlus,
  MonitorPlay, MousePointerClick, Pause, Play, Radio, Send, SkipBack, StickyNote, X,
} from "lucide-react";

import "./nxAgentView.css";
import { ProviderMark } from "../ProviderMark.jsx";
import { Icon, IconButton, Segmented, Spinner, StatusDot, elapsed, local, useTick } from "../nxPrimitives.jsx";
import { os } from "../nxOsStore.js";
import { keyframeUrl, listRuns, readFrame, readTimeline, sendFeedback } from "./nxAgentViewApi.js";
import {
  SPEEDS, applyFrame, awaySummary, boxPct, buildSegments, buildTimelapse, deliveryText, describeAction, emptyStack, feedbackPayload,
  fpsFor, layerStyle, mergeEntries, pointOnFrame, pollDelay, resultText, resultTone, rtAt, sinceFor, sizeClass, sizeText, spanText,
  stateAt, statusText,
} from "./nxAgentViewModel.js";

// Watch and steer agents (Paul: "the agent works on its own surface, retranscribed
// on the side I watch"). The agent drives apps on the private agent desktop, pages
// in Obscura, or the app it is building; this is a rendered mirror of that, never
// the real windows. Live: changed regions only, at the rate the view can use, with
// the element the agent is about to act on outlined and said in plain words. Click
// the picture or a step to tell the agent something about it. Time-lapse: what
// happened while you were away, in segments, at 1-16x.

const MARKS = { codex: "codex", claude: "claude", neyvia: "neyvia", opencode: "opencode" };
const markOf = agent => MARKS[agent?.app] || "neyvia";
const clock = seconds => (Number.isFinite(seconds) ? new Date(seconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "");
const SURFACE_KIND = { app: { icon: AppWindow, label: "App" }, build: { icon: Hammer, label: "App being built" }, browser: { icon: Globe, label: "Browser" } };
const TOOL_ICON = {
  type_text: Keyboard, fill: Keyboard, set_value: Keyboard, select: Keyboard, click: MousePointerClick, double_click: MousePointerClick,
  right_click: MousePointerClick, press_key: Command, hotkey: Command, launch_app: AppWindow, open: Globe, navigate: Globe,
  back: Globe, forward: Globe, reload: Globe, note: StickyNote, feedback: MessageSquare,
};

// ---- watching: is this view visible, and how big ------------------------------------

// Measured directly (cheap: one rect read), so it also holds where observers are missing
// or late: a view tucked into a closed bubble or a hidden tab reads as not showing.
function measure(element) {
  if (!element) return { inView: false, width: 0 };
  const rect = element.getBoundingClientRect();
  const viewH = globalThis.innerHeight || document.documentElement.clientHeight || 0;
  const viewW = globalThis.innerWidth || document.documentElement.clientWidth || 0;
  const inView = rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0 && rect.top < viewH && rect.left < viewW;
  return { inView, width: Math.round(rect.width) };
}

function useWatch(ref) {
  const [state, setState] = useState({ visible: typeof document === "undefined" || !document.hidden, inView: true, width: 0 });
  useEffect(() => {
    const update = () => {
      const next = { visible: !document.hidden, ...measure(ref.current) };
      setState(current => (current.visible === next.visible && current.inView === next.inView && current.width === next.width ? current : next));
    };
    update();
    document.addEventListener("visibilitychange", update);
    globalThis.addEventListener?.("resize", update);
    const timer = setInterval(update, 700);
    let resize = null;
    if (typeof ResizeObserver === "function" && ref.current) {
      resize = new ResizeObserver(update);
      resize.observe(ref.current);
    }
    return () => { document.removeEventListener("visibilitychange", update); globalThis.removeEventListener?.("resize", update); clearInterval(timer); resize?.disconnect(); };
  }, [ref]);
  return state;
}

/** One run's live frames, steps and state, polled only while the view can be seen. */
function useLiveRun(runKey, surfaceId, watch, sizeOverride) {
  const [stack, setStack] = useState(emptyStack);
  const [run, setRun] = useState(null);
  const [entries, setEntries] = useState([]);
  const [problem, setProblem] = useState("");
  const [rate, setRate] = useState(0);
  const refs = useRef({ stack: emptyStack(), after: 0, quiet: 0, failed: false });
  const size = sizeOverride || sizeClass(watch.width);
  const showing = watch.visible && watch.inView && watch.width > 0;

  useEffect(() => {
    refs.current = { stack: emptyStack(), after: 0, quiet: 0, failed: false };
    setStack(emptyStack());
    setEntries([]);
  }, [runKey, surfaceId]);

  useEffect(() => {
    if (!runKey) return undefined;
    let alive = true;
    let timer = 0;
    const delayNow = () => pollDelay({ visible: watch.visible, inView: showing, size, quiet: refs.current.quiet, failed: refs.current.failed });
    const tick = async () => {
      const delay = delayNow();
      if (delay == null) { setRate(0); return; }
      try {
        const answer = await readFrame({ run: runKey, surface: surfaceId, since: sinceFor(refs.current.stack), fps: fpsFor(delay), after: refs.current.after });
        if (!alive) return;
        refs.current.failed = false;
        const moved = answer.kind === "full" || answer.kind === "delta" || answer.entries?.length;
        refs.current.quiet = moved ? 0 : refs.current.quiet + 1;
        const next = applyFrame(refs.current.stack, answer);
        if (next !== refs.current.stack) { refs.current.stack = next; setStack(next); }
        if (answer.run) setRun(answer.run);
        if (answer.entries?.length) {
          refs.current.after = Math.max(refs.current.after, ...answer.entries.map(entry => entry.n));
          setEntries(current => mergeEntries(current, answer.entries));
        }
        setProblem(answer.unavailable || "");
        setRate(fpsFor(delay));
      } catch (error) {
        if (!alive) return;
        refs.current.failed = true;
        setProblem(error?.message || "The live view could not be read.");
      }
      if (alive) {
        const next = delayNow();
        if (next != null) timer = setTimeout(tick, next);
      }
    };
    void tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [runKey, surfaceId, watch.visible, showing, size]);

  return { stack, run, entries, problem, rate, size, showing };
}

// ---- the picture ------------------------------------------------------------------------

function FrameStack({ stack, alt, children, onPointerDown, className = "", frameRef }) {
  const ratio = stack.w && stack.h ? { "--av-w": stack.w, "--av-h": stack.h } : undefined;
  return (
    <div ref={frameRef} className={`nx-av-frame ${className}`} style={ratio} role="img" aria-label={alt} onPointerDown={onPointerDown}>
      {stack.layers.map(layer => <img key={layer.key} src={layer.src} alt="" draggable={false} style={layerStyle(layer, stack)} />)}
      {children}
    </div>
  );
}

function Pin({ point, index, state }) {
  return (
    <span className={`nx-av-pin is-${state}`} style={{ left: `${point.x * 100}%`, top: `${point.y * 100}%` }}>
      <span>{index}</span>
    </span>
  );
}

/** The comment box: bound to the frame (and point) or to one step. */
function Composer({ agentName, binding, placement, onSend, onCancel }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const area = useRef(null);
  useEffect(() => { area.current?.focus(); }, []);
  const submit = async event => {
    event?.preventDefault();
    if (!text.trim() || busy) return;
    setBusy(true);
    setError("");
    try { await onSend(text); } catch (failure) { setError(failure?.message || "The comment could not be sent."); setBusy(false); }
  };
  return (
    <form className={`nx-av-composer${placement ? " is-floating" : ""}`} style={placement || undefined} onSubmit={submit}
      onPointerDown={event => event.stopPropagation()} aria-label={`Tell ${agentName} something`}>
      <div className="nx-av-composer-bind">
        {binding.map(chip => <span key={chip.key} className="nx-av-chip"><Icon as={chip.icon} size={12} />{chip.text}</span>)}
      </div>
      <textarea ref={area} rows={2} value={text} maxLength={2000} placeholder={`Tell ${agentName} what to change here…`}
        onChange={event => setText(event.target.value)}
        onKeyDown={event => {
          if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submit(); }
          if (event.key === "Escape") { event.preventDefault(); onCancel(); }
        }} />
      {error ? <p className="nx-av-error">{error}</p> : null}
      <div className="nx-av-composer-foot">
        <span>It reaches {agentName} with its next step</span>
        <button type="button" className="nx-btn nx-btn-ghost nx-btn-sm" onClick={onCancel}>Cancel</button>
        <button type="submit" className="nx-btn nx-btn-primary nx-btn-sm" disabled={!text.trim() || busy}>
          {busy ? <Spinner size={12} /> : <Icon as={Send} size={14} />}<span className="nx-btn-label">Send</span>
        </button>
      </div>
    </form>
  );
}

function floatingPlacement(point) {
  if (!point) return null;
  const style = {};
  if (point.x > 0.55) style.right = `${(1 - point.x) * 100}%`; else style.left = `${point.x * 100}%`;
  if (point.y > 0.5) style.bottom = `calc(${(1 - point.y) * 100}% + 16px)`; else style.top = `calc(${point.y * 100}% + 16px)`;
  return style;
}

// ---- the live view ----------------------------------------------------------------------

function focusSentence(focus, surfaces) {
  if (!focus) return "";
  const surface = surfaces?.find(row => row.id === focus.surface);
  return describeAction({ tool: focus.tool, say: focus.say, element: focus.element, app: surface?.label, by: focus.by }, focus.phase === "about" ? "about" : "done");
}

function StepRow({ entry, surfaces, feedback, onComment, active }) {
  const IconFor = TOOL_ICON[entry.tool] || (entry.kind === "feedback" ? MessageSquare : Clock);
  const surface = surfaces?.find(row => row.id === entry.surface);
  const result = entry.kind === "action" ? resultText(entry) : "";
  const comment = entry.kind === "feedback" ? feedback?.find(row => row.id === entry.id) : null;
  return (
    <li className={`nx-av-step is-${entry.kind}${entry.by === "paul" ? " is-paul" : ""}${active ? " is-active" : ""}`}>
      <span className="nx-av-step-icon"><Icon as={IconFor} size={14} /></span>
      <div className="nx-av-step-body">
        <p>{describeAction({ ...entry, app: surface?.label }, "done")}</p>
        <div className="nx-av-step-meta">
          <time>{clock(entry.t)}</time>
          {result ? <span className={`nx-av-result is-${resultTone(entry)}`}>{result}</span> : null}
          {comment ? <span className={`nx-av-delivery is-${comment.delivery?.state}`}><Icon as={comment.delivery?.state === "delivered" ? CheckCheck : Clock} size={12} />{deliveryText(comment)}</span> : null}
        </div>
      </div>
      {entry.kind === "action" && onComment ? (
        <IconButton icon={MessageSquarePlus} size="sm" label="Comment on this step" className="nx-av-step-comment" onClick={() => onComment(entry)} />
      ) : null}
    </li>
  );
}

function SurfaceChips({ surfaces, value, onChange }) {
  if (!surfaces || surfaces.length < 2) return null;
  return (
    <div className="nx-av-surfaces" role="tablist" aria-label="Surfaces">
      {surfaces.map(surface => {
        const kind = SURFACE_KIND[surface.kind] || SURFACE_KIND.app;
        return (
          <button key={surface.id} type="button" role="tab" aria-selected={value === surface.id} className={value === surface.id ? "is-on" : ""} onClick={() => onChange(surface.id)}>
            <Icon as={kind.icon} size={13} /><span>{surface.label}</span>
          </button>
        );
      })}
    </div>
  );
}

function LiveView({ runKey, agentName, onCatchUp, onRun }) {
  const root = useRef(null);
  const frameRef = useRef(null);
  const watch = useWatch(root);
  const [picked, setPicked] = useState(() => local.get(`agentview.surface.${runKey}`, ""));
  const [composer, setComposer] = useState(null); // {point?, action?}
  const [sent, setSent] = useState(null);
  const [follow, setFollow] = useState(!picked);
  const lastSurface = useRef("");
  const probe = useLiveRun(runKey, picked || lastSurface.current || "", watch);
  const { stack, run, entries, problem, rate, size } = probe;
  useTick(Boolean(run && run.status !== "ended"), 1000);
  useEffect(() => { if (run) onRun?.(run); }, [run]); // eslint-disable-line react-hooks/exhaustive-deps

  // Follow the agent across windows and pages unless Paul picked one.
  const followed = run?.focus?.surface || [...entries].reverse().find(entry => entry.surface)?.surface || run?.surfaces?.[0]?.id || "";
  const surfaceId = follow ? followed : picked || followed;
  useEffect(() => { if (follow && surfaceId && surfaceId !== picked) setPicked(surfaceId); }, [follow, surfaceId]); // eslint-disable-line react-hooks/exhaustive-deps
  lastSurface.current = surfaceId;
  const surface = run?.surfaces?.find(row => row.id === surfaceId) || null;

  // Where Paul left off, for "while you were away".
  const [seenAt] = useState(() => local.get(`agentview.seen.${runKey}`, 0));
  useEffect(() => {
    if (!probe.showing) return undefined;
    const mark = () => local.set(`agentview.seen.${runKey}`, Date.now() / 1000);
    const timer = setInterval(mark, 5000);
    return () => { clearInterval(timer); mark(); };
  }, [runKey, probe.showing]);
  const away = useMemo(() => {
    const summary = awaySummary(entries, seenAt);
    return summary && Date.now() / 1000 - seenAt > 30 ? summary : null;
  }, [entries, seenAt]);
  const [awayClosed, setAwayClosed] = useState(false);

  const focus = run?.focus && run.focus.surface === surfaceId ? run.focus : null;
  const focusBox = focus?.element?.box ? boxPct(focus.element.box) : null;
  const latest = [...entries].reverse().find(entry => entry.kind === "action" && entry.surface === surfaceId);
  const sentence = focus ? focusSentence(focus, run?.surfaces) : latest ? describeAction({ ...latest, app: surface?.label }, "done") : "";
  const verdict = !focus || focus.phase !== "about" ? resultText(latest) : "";
  const pins = (run?.feedback || []).filter(row => row.surface === surfaceId && row.point && Date.now() / 1000 - row.t < 1800);
  const ended = run?.status === "ended";

  const onFramePointer = event => {
    if (event.button !== 0 || !stack.w) return;
    const point = pointOnFrame(event.clientX, event.clientY, frameRef.current?.getBoundingClientRect());
    // A click on the picture is about the picture; the step it followed is shown as context, not bound.
    if (point) setComposer({ point, v: stack.v, action: null, context: latest || null });
  };
  const send = async text => {
    const payload = feedbackPayload({ run: runKey, surface: surfaceId, stack: { v: composer.v || stack.v }, action: composer.action?.id, point: composer.point, text });
    const row = await sendFeedback(payload);
    setComposer(null);
    setSent(row);
  };
  useEffect(() => { if (!sent) return undefined; const timer = setTimeout(() => setSent(null), 6000); return () => clearTimeout(timer); }, [sent]);

  const binding = composer ? [
    { key: "frame", icon: MonitorPlay, text: `${surface?.label || "Frame"} · ${clock(Date.now() / 1000)}` },
    ...(composer.point ? [{ key: "point", icon: MousePointerClick, text: "Where you clicked" }] : []),
    ...(composer.action ? [{ key: "action", icon: TOOL_ICON[composer.action.tool] || Clock, text: describeAction({ ...composer.action, app: surface?.label }, "done") }]
      : composer.context ? [{ key: "context", icon: Clock, text: `After: ${describeAction({ ...composer.context, app: surface?.label }, "done")}` }] : []),
  ] : [];
  const steps = [...entries].reverse();
  const compact = size !== "full";

  return (
    <div ref={root} className={`nx-av-live is-${size}`}>
      {away && !awayClosed ? (
        <div className="nx-av-away" role="status">
          <Icon as={History} size={15} />
          <span><strong>While you were away</strong> · {away.steps} {away.steps === 1 ? "step" : "steps"} in {spanText(away.span)}{away.checked ? ` · ${away.checked} checked` : ""}</span>
          <button type="button" className="nx-btn nx-btn-primary nx-btn-sm" onClick={() => onCatchUp(seenAt)}><Icon as={Play} size={13} /><span className="nx-btn-label">Catch up</span></button>
          <IconButton icon={X} size="sm" label="Dismiss" onClick={() => setAwayClosed(true)} />
        </div>
      ) : null}
      <SurfaceChips surfaces={run?.surfaces} value={surfaceId} onChange={id => { setFollow(false); setPicked(id); local.set(`agentview.surface.${runKey}`, id); }} />
      <div className="nx-av-body">
        <div className="nx-av-stage">
          {!stack.layers.length && run?.lastKeyframes?.[surfaceId] ? (
            // Nothing live (finished, or the window is gone): the last kept picture of this surface.
            <FrameStack stack={{ w: run.lastKeyframes[surfaceId].w, h: run.lastKeyframes[surfaceId].h, layers: [{ key: "kf", x: 0, y: 0, w: run.lastKeyframes[surfaceId].w, h: run.lastKeyframes[surfaceId].h, src: keyframeUrl(runKey, run.lastKeyframes[surfaceId].id) }] }}
              frameRef={frameRef} alt={`${surface?.label || "Screen"}, last kept picture`} className="is-ended" />
          ) : !stack.layers.length ? (
            <div className="nx-av-empty">
              {problem && !/^closed$/.test(problem) ? <Icon as={AppWindow} size={18} /> : <Spinner size={14} />}
              <span>{problem ? (ended ? "This run has finished. Its time-lapse keeps what happened." : `Can't show this surface right now: ${problem}`) : "Waiting for the first picture…"}</span>
            </div>
          ) : (
            <FrameStack stack={stack} frameRef={frameRef} alt={`${agentName}'s ${surface?.label || "screen"}`} className={ended ? "is-ended" : ""} onPointerDown={onFramePointer}>
              {focusBox ? (
                <span className={`nx-av-focus is-${focus.phase}`} style={focusBox}>
                  {focus.element?.label ? <span className="nx-av-focus-tag">{focus.element.label}</span> : null}
                </span>
              ) : null}
              {focus?.point ? <span className={`nx-av-cursor is-${focus.phase}`} style={{ left: `${focus.point.x * 100}%`, top: `${focus.point.y * 100}%` }} /> : null}
              {pins.map((row, index) => <Pin key={row.id} point={row.point} index={index + 1} state={row.delivery?.state || "queued"} />)}
              {composer?.point ? <Pin point={composer.point} index="+" state="draft" /> : null}
              {composer?.point && !compact ? (
                <Composer agentName={agentName} binding={binding} placement={floatingPlacement(composer.point)} onSend={send} onCancel={() => setComposer(null)} />
              ) : null}
            </FrameStack>
          )}
          {sentence ? (
            <div className={`nx-av-now is-${focus?.phase || "last"}`} aria-live="polite">
              {focus?.phase === "about" ? <Spinner size={12} /> : <Icon as={verdict.startsWith("Checked") ? Check : Radio} size={13} />}
              <span className="nx-av-now-text">{focus?.phase === "about" ? sentence : latest && !focus ? `Last: ${sentence}` : sentence}</span>
              {verdict ? <span className={`nx-av-result is-${resultTone(latest)}`}>{verdict}</span> : null}
            </div>
          ) : null}
          {composer && (compact || !composer.point) ? <Composer agentName={agentName} binding={binding} onSend={send} onCancel={() => setComposer(null)} /> : null}
          {sent ? (
            <p className="nx-av-sent" role="status"><Icon as={sent.delivery?.state === "delivered" ? CheckCheck : Check} size={13} />Sent to {agentName}. {deliveryText(sent)}.</p>
          ) : !composer && stack.layers.length && !ended ? (
            <p className="nx-av-hint"><Icon as={MessageSquarePlus} size={13} />Click the picture or a step to tell {agentName} something about it{rate ? ` · live ${rate} fps` : ""}</p>
          ) : null}
        </div>
        <aside className="nx-av-steps" aria-label="Steps">
          <header>
            <strong>Steps</strong>
            <span>{run?.counts?.actions ?? entries.filter(entry => entry.kind === "action").length}</span>
          </header>
          {steps.length ? (
            <ol className="nx-scroll">
              {steps.slice(0, compact ? 6 : 60).map((entry, index) => (
                <StepRow key={entry.n} entry={entry} surfaces={run?.surfaces} feedback={run?.feedback} active={index === 0 && run?.status === "working"}
                  onComment={ended ? null : action => setComposer({ action, v: stack.v, point: null })} />
              ))}
            </ol>
          ) : <p className="nx-av-quiet">No steps yet.</p>}
        </aside>
      </div>
    </div>
  );
}

// ---- the time-lapse -------------------------------------------------------------------

function useTimeline(runKey, live) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try { const next = await readTimeline(runKey); if (alive) { setData(next); setError(""); } } catch (failure) { if (alive) setError(failure?.message || "The time-lapse could not be read."); }
    };
    void load();
    const timer = live ? setInterval(() => { if (!document.hidden) void load(); }, 5000) : 0;
    return () => { alive = false; clearInterval(timer); };
  }, [runKey, live]);
  return { data, error };
}

function Timelapse({ runKey, agentName, startAt, live }) {
  const root = useRef(null);
  const watch = useWatch(root);
  const size = sizeClass(watch.width);
  const { data, error } = useTimeline(runKey, live);
  const lapse = useMemo(() => buildTimelapse(data?.keyframes || [], data?.entries || []), [data]);
  const segments = useMemo(() => buildSegments(data?.entries || [], data?.keyframes || [], data?.surfaces || []), [data]);
  const [pos, setPos] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(() => local.get("agentview.speed", 4));
  const [composer, setComposer] = useState(false);
  const [sent, setSent] = useState(null);
  const [seenAt] = useState(() => local.get(`agentview.seen.${runKey}`, 0));
  const [awayClosed, setAwayClosed] = useState(Boolean(startAt));
  const away = useMemo(() => {
    const summary = awaySummary(data?.entries || [], seenAt);
    return summary && Date.now() / 1000 - seenAt > 30 ? summary : null;
  }, [data, seenAt]);
  useEffect(() => () => local.set(`agentview.seen.${runKey}`, Date.now() / 1000), [runKey]);
  const track = useRef(null);
  const started = useRef(false);
  const end = lapse.duration;

  // Open where Paul left off (Catch up), else at the end.
  useEffect(() => {
    if (started.current || !lapse.events.length) return;
    started.current = true;
    if (startAt) { setPos(rtAt(lapse, startAt * 1000)); setPlaying(true); } else setPos(end);
  }, [lapse, startAt, end]);
  useEffect(() => {
    if (!playing) return undefined;
    let frame = 0;
    let last = performance.now();
    const step = now => {
      const dt = now - last;
      last = now;
      setPos(current => {
        const next = Math.min(end, current + dt * speed);
        if (next >= end) setPlaying(false);
        return next;
      });
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [playing, speed, end]);

  const at = stateAt(lapse, pos);
  const keyframe = at.frame;
  const surfaces = data?.surfaces || [];
  const surface = surfaces.find(row => row.id === keyframe?.surface);
  const currentSegment = segments.findLast?.(segment => at.at != null && segment.start * 1000 <= at.at + 1) || null;
  const seekTo = clientX => {
    const rect = track.current.getBoundingClientRect();
    setPos(Math.min(1, Math.max(0, (clientX - rect.left) / rect.width)) * end);
  };
  const jump = t => { setPlaying(false); setPos(rtAt(lapse, t * 1000 + 1)); };
  const send = async text => {
    const payload = feedbackPayload({ run: runKey, surface: keyframe?.surface, keyframe: keyframe?.id, action: at.step?.kind === "action" ? at.step.id : null, text });
    setSent(await sendFeedback(payload));
    setComposer(false);
  };

  const waiting = error && !data ? <span>{error}</span>
    : !data ? <><Spinner size={14} /><span>Gathering the time-lapse…</span></>
      : !lapse.frames.length ? <><Icon as={History} size={18} /><span>Nothing recorded yet. Keyframes are kept after every step.</span></> : null;
  if (waiting) return <div ref={root} className={`nx-av-lapse is-${size}`}><div className="nx-av-empty">{waiting}</div></div>;

  const pct = value => `${end ? (value / end) * 100 : 0}%`;
  const kept = data.keyframes.reduce((sum, row) => sum + row.bytes, 0);
  return (
    <div ref={root} className={`nx-av-lapse is-${size}`}>
      <div className="nx-av-lapse-main">
        {away && !awayClosed ? (
          <div className="nx-av-away" role="status">
            <Icon as={History} size={15} />
            <span><strong>While you were away</strong> · {away.steps} {away.steps === 1 ? "step" : "steps"} in {spanText(away.span)}{away.checked ? ` · ${away.checked} checked` : ""}</span>
            <button type="button" className="nx-btn nx-btn-primary nx-btn-sm" onClick={() => { setAwayClosed(true); setPos(rtAt(lapse, seenAt * 1000)); setPlaying(true); }}>
              <Icon as={Play} size={13} /><span className="nx-btn-label">Catch up</span>
            </button>
            <IconButton icon={X} size="sm" label="Dismiss" onClick={() => setAwayClosed(true)} />
          </div>
        ) : null}
        <div className="nx-av-lapse-stage">
          <div className="nx-av-frame is-keyframe" style={{ "--av-w": keyframe.w, "--av-h": keyframe.h }}>
            <img key={keyframe.id} src={keyframeUrl(runKey, keyframe.id)} alt={`${surface?.label || "Screen"} at ${clock(keyframe.t)}`} draggable={false} />
          </div>
          {at.step ? (
            <div className="nx-av-now is-replay">
              <Icon as={at.step.kind === "feedback" ? MessageSquare : TOOL_ICON[at.step.tool] || Clock} size={13} />
              <span className="nx-av-now-text">{describeAction({ ...at.step, app: surfaces.find(row => row.id === at.step.surface)?.label }, "done")}</span>
              {resultText(at.step) ? <span className={`nx-av-result is-${resultTone(at.step)}`}>{resultText(at.step)}</span> : null}
            </div>
          ) : null}
          {composer ? (
            <Composer agentName={agentName} onSend={send} onCancel={() => setComposer(false)}
              binding={[{ key: "kf", icon: History, text: `${surface?.label || "Frame"} · ${clock(keyframe.t)}` },
                ...(at.step?.kind === "action" ? [{ key: "a", icon: TOOL_ICON[at.step.tool] || Clock, text: describeAction(at.step, "done") }] : [])]} />
          ) : sent ? (
            <p className="nx-av-sent" role="status"><Icon as={Check} size={13} />Sent to {agentName}, bound to this moment. {deliveryText(sent)}.</p>
          ) : null}
        </div>
        <div className="nx-av-transport">
          <IconButton icon={playing ? Pause : Play} label={playing ? "Pause" : pos >= end ? "Play again" : "Play"} onClick={() => { if (pos >= end) setPos(0); setPlaying(value => !value); }} />
          <IconButton icon={SkipBack} label="Back to the start" onClick={() => { setPos(0); }} />
          <div className="nx-av-track" ref={track} role="slider" tabIndex={0} aria-label="Time-lapse position"
            aria-valuemin={0} aria-valuemax={100} aria-valuenow={end ? Math.round((pos / end) * 100) : 0} aria-valuetext={clock(at.at / 1000)}
            onKeyDown={event => {
              const delta = { ArrowLeft: -end * 0.02, ArrowRight: end * 0.02, Home: -end, End: end }[event.key];
              if (delta === undefined) return;
              event.preventDefault();
              setPlaying(false);
              setPos(current => Math.min(end, Math.max(0, current + delta)));
            }}
            onPointerDown={event => { event.currentTarget.setPointerCapture?.(event.pointerId); setPlaying(false); seekTo(event.clientX); }}
            onPointerMove={event => { if (event.buttons === 1) seekTo(event.clientX); }}>
            {segments.map((segment, index) => {
              const from = rtAt(lapse, segment.start * 1000);
              const to = rtAt(lapse, segment.end * 1000);
              return <i key={segment.id} className={`nx-av-band${index % 2 ? " is-alt" : ""}`} style={{ left: pct(from), width: `max(3px, ${pct(to - from)})` }} />;
            })}
            {lapse.steps.map(({ row, rt }) => (
              <i key={row.n} className={`nx-av-tick is-${row.kind === "feedback" ? "feedback" : resultTone(row)}`} style={{ left: pct(rt) }}
                title={`${clock(row.t)} · ${describeAction({ ...row, app: surfaces.find(item => item.id === row.surface)?.label }, "done")}`} />
            ))}
            <span className="nx-av-fill" style={{ width: pct(pos) }} />
            <span className="nx-av-playhead" style={{ left: pct(pos) }} />
          </div>
          <span className="nx-av-clock">{clock(at.at / 1000)}</span>
          <Segmented size="sm" label="Speed" value={speed} options={SPEEDS.map(value => ({ value, label: `${value}×` }))}
            onChange={value => { setSpeed(value); local.set("agentview.speed", value); }} />
          <button type="button" className="nx-btn nx-btn-ghost nx-btn-sm" onClick={() => { setPlaying(false); setComposer(true); }}>
            <Icon as={MessageSquarePlus} size={14} /><span className="nx-btn-label">Comment on this moment</span>
          </button>
        </div>
        <p className="nx-av-kept">
          {data.keyframes.length} keyframes · {sizeText(kept)} of {sizeText(data.bounds?.keyframeBytes)} kept · {data.entries.filter(row => row.kind === "action").length} steps over {spanText((lapse.endedAt - lapse.startedAt) / 1000)} · plays in {spanText(end / 1000 / speed)} at {speed}×
        </p>
      </div>
      <aside className="nx-av-progress" aria-label="What progressed">
        <header><strong>What progressed</strong><span>{segments.length}</span></header>
        <ol className="nx-scroll">
          {segments.map(segment => (
            <li key={segment.id} className={currentSegment?.id === segment.id ? "is-current" : ""}>
              <button type="button" onClick={() => jump(segment.start)}>
                <span className="nx-av-seg-time">{clock(segment.start)}{segment.end - segment.start >= 1 ? ` · ${spanText(segment.end - segment.start)}` : ""}{segment.where ? ` · ${segment.where}` : ""}</span>
                <span className="nx-av-seg-text">{segment.text}</span>
                <span className="nx-av-seg-meta">
                  <span>{`${segment.actions} ${segment.actions === 1 ? "step" : "steps"}`}</span>
                  {segment.checked ? <span className="nx-av-result is-ok">{segment.checked} checked</span> : null}
                  {segment.failed ? <span className="nx-av-result is-error">{segment.failed} failed</span> : null}
                  {segment.comments ? <span className="nx-av-result is-feedback"><Icon as={MessageSquare} size={11} />{segment.comments}</span> : null}
                </span>
                {segment.before && segment.after && segment.before !== segment.after ? (
                  <span className="nx-av-seg-shots" aria-hidden="true">
                    <img src={keyframeUrl(runKey, segment.before)} alt="" loading="lazy" />
                    <span>→</span>
                    <img src={keyframeUrl(runKey, segment.after)} alt="" loading="lazy" />
                  </span>
                ) : null}
              </button>
            </li>
          ))}
        </ol>
      </aside>
    </div>
  );
}

// ---- one run ---------------------------------------------------------------------------

function RunHeader({ run, tab, onTab }) {
  useTick(Boolean(run && run.status !== "ended"), 1000);
  const agent = run?.agent || {};
  const tone = run?.status === "waiting" ? "gold" : run?.status === "working" ? "live" : run?.status === "ended" ? "idle" : "green";
  return (
    <header className="nx-av-head">
      <ProviderMark id={markOf(agent)} size={22} />
      <div className="nx-av-title">
        <strong>{agent.name || "Agent"}{agent.title ? <span> · {agent.title}</span> : null}</strong>
        <span><StatusDot tone={tone} pulse={run?.status === "working"} />{statusText(run)}{run?.startedAt && run.status !== "ended" ? ` · ${elapsed(run.startedAt)}` : ""}</span>
      </div>
      <Segmented size="sm" label="View" value={tab} onChange={onTab}
        options={[{ value: "live", label: run?.status === "ended" ? "Last picture" : "Live" }, { value: "lapse", label: "Time-lapse", count: run?.counts?.keyframes || undefined }]} />
      {run?.cuaSession && run.status !== "ended" ? (
        <button type="button" className="nx-btn nx-btn-ghost nx-btn-sm" title="Use the app yourself; the agent pauses" onClick={() => os.showPane("preview", run.cuaSession)}>
          <Icon as={Hand} size={14} /><span className="nx-btn-label">Take control</span>
        </button>
      ) : null}
    </header>
  );
}

/** One agent run: its live surface and its time-lapse. A pane ("agentview", target = run key), so each run can sit in its own place or bubble. */
export function NxAgentRun({ target }) {
  const wanted = String(target || "");
  const [tab, setTab] = useState("live");
  const [startAt, setStartAt] = useState(0);
  const [run, setRun] = useState(null);
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    let alive = true;
    // The target is a run key, or the computer-use session or chat it belongs to ("Watch" from a toast or the dashboard).
    const load = async () => {
      try {
        const { runs } = await listRuns();
        const found = runs.find(row => row.key === wanted) || runs.find(row => row.cuaSession === wanted) || runs.find(row => row.agent?.chatId === wanted) || null;
        if (alive) { setRun(found); setMissing(!found); }
      } catch { /* the live view says why */ }
    };
    void load();
    const timer = setInterval(() => { if (!document.hidden) void load(); }, 3000);
    return () => { alive = false; clearInterval(timer); };
  }, [wanted]);
  const runKey = run?.key || "";
  // A finished run opens on what it did; a working one on what it is doing.
  const opened = useRef(false);
  useEffect(() => {
    if (!run || opened.current) return;
    opened.current = true;
    if (run.status === "ended" && run.counts?.keyframes) setTab("lapse");
  }, [run]);
  if (missing && !run) return <section className="nx-av"><div className="nx-av-empty is-big"><Icon as={MonitorPlay} size={24} /><strong>This agent run isn't here any more</strong><span>Open Agents at work to see the runs this PC keeps.</span></div></section>;
  if (!runKey) return <section className="nx-av"><div className="nx-av-empty"><Spinner size={14} /><span>Finding the run…</span></div></section>;
  const agentName = run?.agent?.name || "the agent";
  return (
    <section className="nx-av" aria-label={`${agentName} at work`}>
      <RunHeader run={run} tab={tab} onTab={value => { setTab(value); if (value === "live") setStartAt(0); }} />
      {tab === "live"
        ? <LiveView key={runKey} runKey={runKey} agentName={agentName} onRun={live => setRun(current => ({ ...current, ...live }))} onCatchUp={seen => { setStartAt(seen); setTab("lapse"); }} />
        : <Timelapse key={`${runKey}:${startAt}`} runKey={runKey} agentName={agentName} startAt={startAt} live={run?.status !== "ended"} />}
    </section>
  );
}

// ---- every run ----------------------------------------------------------------------------

// A card shows the run's latest keyframe (kept after every step and every few seconds of change),
// so a wall of agents costs no live captures at all; opening one starts its live view.
function RunCard({ run }) {
  const surfaceId = run.focus?.surface || run.recent?.[run.recent.length - 1]?.surface || run.surfaces?.[0]?.id || "";
  const last = [...(run.recent || [])].reverse().find(entry => entry.kind === "action");
  const surface = run.surfaces?.find(row => row.id === (last?.surface || surfaceId));
  const kind = SURFACE_KIND[surface?.kind] || SURFACE_KIND.app;
  const doing = run.focus?.phase === "about" ? focusSentence(run.focus, run.surfaces) : last ? describeAction({ ...last, app: surface?.label }, "done") : "Getting started";
  const tone = run.status === "waiting" ? "gold" : run.status === "working" ? "live" : run.status === "ended" ? "idle" : "green";
  return (
    <li className={`nx-av-card is-${run.status}`}>
      <button type="button" className="nx-av-card-open" onClick={() => os.showPane("agentview", run.key)} aria-label={`Watch ${run.agent?.name}: ${run.title || ""}`}>
        <span className="nx-av-card-shot">
          {run.lastKeyframe ? <img key={run.lastKeyframe} src={keyframeUrl(run.key, run.lastKeyframe)} alt="" loading="lazy" />
            : <span className="nx-av-card-wait"><Icon as={kind.icon} size={20} /></span>}
          {run.status === "working" ? <span className="nx-av-card-live"><StatusDot tone="live" pulse />Live</span> : null}
        </span>
        <span className="nx-av-card-text">
          <span className="nx-av-card-who"><ProviderMark id={markOf(run.agent)} size={16} /><strong>{run.agent?.name}</strong>{run.title ? <span>{run.title}</span> : null}</span>
          <span className="nx-av-card-doing">{doing}</span>
          <span className="nx-av-card-meta">
            <StatusDot tone={tone} pulse={run.status === "working"} />
            <span>{[statusText(run), surface?.label || kind.label, `${run.counts?.actions || 0} ${run.counts?.actions === 1 ? "step" : "steps"}`,
              run.counts?.feedback ? `${run.counts.feedback} ${run.counts.feedback === 1 ? "comment" : "comments"}` : ""].filter(Boolean).join(" · ")}</span>
          </span>
        </span>
      </button>
    </li>
  );
}

/** "Agents at work": every agent run, live, as cards; one opens a run's own view. */
export function NxAgentView({ target }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (target) return undefined;
    let alive = true;
    const load = async () => { try { const next = await listRuns(); if (alive) { setData(next); setError(""); } } catch (failure) { if (alive) setError(failure?.message || "The agent runs could not be read."); } };
    void load();
    const timer = setInterval(() => { if (!document.hidden) void load(); }, 3000);
    return () => { alive = false; clearInterval(timer); };
  }, [target]);
  if (target) return <NxAgentRun target={target} />;
  const runs = data?.runs || [];
  const live = runs.filter(run => run.status !== "ended");
  const earlier = runs.filter(run => run.status === "ended");
  return (
    <section className="nx-av nx-av-all" aria-label="Agents at work">
      <header className="nx-av-head">
        <Icon as={MonitorPlay} size={20} />
        <div className="nx-av-title">
          <strong>Agents at work</strong>
          <span>{live.length ? `${live.length} working on their own screens · you watch a rendered copy` : "Nobody is working on a screen right now"}</span>
        </div>
      </header>
      {error ? <p className="nx-av-error">{error}</p> : null}
      {!data && !error ? <div className="nx-av-empty"><Spinner size={14} /><span>Looking for agent runs…</span></div> : null}
      {data && !runs.length ? (
        <div className="nx-av-empty is-big">
          <Icon as={MonitorPlay} size={26} />
          <strong>When an agent uses an app, the browser or tests what it built, you watch it here</strong>
          <span>It works on its own desktop, never yours. You see each step said in plain words, can click the picture to steer it, and get a time-lapse of what happened while you were away.</span>
        </div>
      ) : null}
      {live.length ? <ul className="nx-av-cards">{live.map(run => <RunCard key={run.key} run={run} />)}</ul> : null}
      {earlier.length ? (
        <>
          <h3 className="nx-av-section">Earlier · time-lapses kept</h3>
          <ul className="nx-av-cards is-earlier">{earlier.map(run => <RunCard key={run.key} run={run} />)}</ul>
        </>
      ) : null}
    </section>
  );
}

export default NxAgentView;
