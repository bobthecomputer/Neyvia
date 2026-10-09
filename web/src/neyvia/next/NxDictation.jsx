import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { BookA, Mic, Send, Square, Undo2, X } from "lucide-react";

import "./nxDictation.css";
import { createReveal } from "./nxDictationReveal.js";
import { Button, Icon, Popover, Spinner } from "./nxPrimitives.jsx";
import {
  dictationNames, engineStatus, micMessage, prepareAudio, processSpoken, redecodeDictation, startBrowserDictation, startDictation,
} from "./nxDictation.js";
import {
  COMMAND_LABELS, LANGUAGE_LABELS, applySegments, liveCommands, normalizeAnswer, previewParts, shiftAnchor,
} from "./nxDictationEdit.js";

// Prompt dictation for the composer, the new-chat box and Notes.
// Click the mic: talk, click again to insert. Hold (button or Ctrl+Shift+Space): talk while held, release to insert.
// Esc cancels. While talking, the words appear in the text box itself: settled words in the normal colour, the
// newest ones grey until the engine is sure of them. Spoken commands ("new paragraph", "scratch that", "undo that",
// "delete the last sentence", "send it", "cancel") are done, not typed. Every insert can be undone with one tap.

const HOLD_MS = 350;
const LOG_KEY = "neyvia.dictation.log";
const SEND_PREVIEW_MS = 2000;
const NOTICE_MS = 12000;
let cachedStatus = null;
let prewarmed = false;
let statusAt = 0;
const targets = []; // mounted dictation targets, most recently used last

// The engine exits after 20 idle minutes. Focusing a dictation box wakes it (at most every 20 s), so by the time
// the mic is pressed it is often ready again.
let wokeAt = 0;
function wakeSoon() {
  if (cachedStatus?.state === "ready" && Date.now() - statusAt < 20000) return;
  if (Date.now() - wokeAt < 20000) return;
  wokeAt = Date.now();
  void readStatus({ start: true });
}

async function readStatus({ start = false, fresh = false } = {}) {
  if (!fresh && !start && cachedStatus && Date.now() - statusAt < 5000) return cachedStatus;
  try { cachedStatus = noteStatus(await engineStatus({ start })); }
  catch (error) { cachedStatus = { state: "unreachable", error: error.message, code: error.code || "" }; }
  statusAt = Date.now();
  return cachedStatus;
}

function remember(entry) {
  try {
    const log = JSON.parse(localStorage.getItem(LOG_KEY) || "[]");
    log.push(entry);
    localStorage.setItem(LOG_KEY, JSON.stringify(log.slice(-50)));
  } catch { /* the log is only for measuring */ }
  (globalThis.__nxDictationLog ||= []).push(entry);
}

// A cold engine start: a few seconds on a warm GPU, minutes on a CPU that just booted. The wait is generous and
// cancellable; the recording is held in memory the whole time and decoded the moment the engine is ready.
const START_WAIT_MS = 600000;
const START_KEY = "neyvia.dictation.engineStartMs";
let engineDownSince = 0; // first time this page saw the engine not ready (for "usually about N")
let lastStartedInMs = null; // how long the last cold start took, as seen from this page

function typicalStart() {
  try { return Number(localStorage.getItem(START_KEY)) || 0; } catch { return 0; }
}

function noteStatus(status) {
  if (status.state === "ready") {
    const took = engineDownSince ? Date.now() - engineDownSince : 0;
    engineDownSince = 0;
    if (took > 3000) {
      try { localStorage.setItem(START_KEY, String(took)); } catch { /* only for the estimate */ }
      lastStartedInMs = took;
    }
  } else if (["starting", "loading", "off"].includes(status.state) && !engineDownSince) engineDownSince = Date.now();
  return status;
}

function formatSpan(ms) {
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  return seconds % 60 ? `${minutes} min ${seconds % 60} s` : `${minutes} min`;
}

/** What the strip says while a held recording waits for the engine. */
function startingMessage(elapsedMs, audioMs, typicalMs) {
  const usual = typicalMs > 5000 && typicalMs > elapsedMs ? `, usually about ${formatSpan(Math.ceil(typicalMs / 30000) * 30000)}` : "";
  const kept = audioMs > 0 ? `Your ${formatSpan(Math.max(1000, audioMs))} of speech is kept` : "Your words are kept";
  return `The speech model is starting (${formatSpan(elapsedMs)} so far${usual}). ${kept} and will be written when it's ready.`;
}

const sleep = (ms, signal) => new Promise((resolve, reject) => {
  const timer = setTimeout(resolve, ms);
  signal?.addEventListener("abort", () => { clearTimeout(timer); reject(Object.assign(new Error("Cancelled"), { name: "AbortError" })); }, { once: true });
});

async function waitReady(say, { signal, audioMs = 0 } = {}) {
  const began = Date.now();
  const since = engineDownSince || began;
  let lostSince = 0;  // the backend didn't answer: a restart or a blip shouldn't drop minutes of speech
  for (;;) {
    if (signal?.aborted) throw Object.assign(new Error("Cancelled"), { name: "AbortError" });
    const status = await readStatus({ fresh: true, start: true });
    if (status.state === "ready") return { ...status, startedInMs: lastStartedInMs };
    if (status.state === "unreachable" && status.code !== "login_required") {
      lostSince ||= Date.now();
      if (Date.now() - lostSince > 60000) throw new Error("Neyvia's backend stopped answering while the speech model started.");
      say(`Can't reach Neyvia right now, still trying. Your ${formatSpan(Math.max(1000, audioMs))} of speech is kept.`);
    } else if (["missing", "error", "unreachable"].includes(status.state)) {
      throw new Error(status.error || "The speech engine couldn't start.");
    } else {
      lostSince = 0;
      say(startingMessage(Date.now() - since, audioMs, typicalStart()));
    }
    if (Date.now() - began > START_WAIT_MS) throw new Error("The speech model still isn't ready after 10 minutes.");
    await sleep(1500, signal);
  }
}

/** The language note after a dictation, in plain words: what was heard, and what's missing to write it properly. */
function explainRoute(final) {
  if (!final.route_note || final.route !== "qwen") return final.route_note || "";
  const heard = final.language === "mixed" ? "That sounded partly French." : "That sounded French.";
  const missing = cachedStatus?.qwen
    ? "The French engine here can't take live speech yet,"
    : "Neyvia has no French speech engine on this PC yet,";
  return `${heard} ${missing} so the English engine wrote its best guess. Check it, or Undo.`;
}

/** The live words with the grey tail written out word by word (nxDictationReveal) rather than in engine-sized batches. */
function useRevealedLive(live) {
  const reveal = useRef(null);
  const [, tick] = useState(0);
  const frame = useRef(0);
  if (!reveal.current) reveal.current = createReveal();
  const seen = useRef(null);
  if (!live) { reveal.current.reset(); seen.current = null; }
  else if (seen.current !== live) {
    seen.current = live;
    reveal.current.push(live.stable, live.provisional, performance.now());
  }
  const view = live ? reveal.current.visible(performance.now()) : null;
  useEffect(() => {
    if (!view?.pending) return undefined;
    frame.current = requestAnimationFrame(() => tick(count => count + 1));
    return () => cancelAnimationFrame(frame.current);
  });
  if (!live) return live;
  return view.provisionalWords >= live.provisional.split(/\s+/).filter(Boolean).length ? live : { ...live, provisional: view.words.join(" ") };
}

/**
 * Dictation core: mic, engine, live words. onBegin() runs on press; onFinal(answer, info) gets the normalised final
 * answer (segments, language, route, redecode, fixes). live = {stable, provisional, commands, revision} while talking.
 */
export function useDictation({ onBegin, onFinal, onText, containerRef, kind = "field", extra }) {
  const [state, setState] = useState({ status: "idle", message: "" });
  const [live, setLive] = useState(null);
  const shown = useRevealedLive(live);
  const levels = useRef(new Array(40).fill(0));
  const capture = useRef(null);
  const kept = useRef(null);
  const pressedAt = useRef(0);
  const latest = useRef({ onBegin, onFinal, onText });
  latest.current = { onBegin, onFinal, onText };
  const active = ["starting", "listening"].includes(state.status);
  const feedback = useRef(null);
  useLayoutEffect(() => {
    if (state.status === "starting" && feedback.current == null) feedback.current = Math.round(performance.now() - pressedAt.current);
  }, [state.status]);
  const busy = active || state.status === "finishing";

  const beginning = useRef(false);
  const endEarly = useRef(false);
  const begin = useCallback(async () => {
    if (capture.current || beginning.current) return;
    beginning.current = true;
    endEarly.current = false;
    kept.current = null;  // a new dictation replaces a failed one's kept recording
    pressedAt.current = performance.now();
    levels.current.fill(0);
    latest.current.onBegin?.();
    setLive({ stable: "", provisional: "", commands: [], revision: null });
    setState({ status: "starting", message: "Listening…" });  // feedback first, before any await
    feedback.current = null;  // set when the live strip is committed to the page (the "within 100 ms" check)
    const log = entry => remember({ ...entry, feedbackMs: feedback.current });
    // The mic opens at once; the engine's state only decides how the audio travels. A ready engine seen recently is
    // trusted (if it idled out since, the audio is held and decoded when it's back); otherwise ask, without waiting.
    const trusted = cachedStatus?.state === "ready" && Date.now() - statusAt < 60000;
    const status = trusted ? cachedStatus : readStatus();
    if (trusted && Date.now() - statusAt > 5000) void readStatus({ fresh: true });
    const deliver = (final, info) => {
      if (latest.current.onFinal) latest.current.onFinal(final, info);
      else if (final.text) latest.current.onText?.(final.text, info);
    };
    const callbacks = {
      onState: next => {
        setState(next);
        if (["idle", "error"].includes(next.status)) {
          kept.current = next.canRetry ? capture.current : null;  // a failed decode keeps its recording for "Try again"
          capture.current = null;
          setLive(null);
        }
      },
      onLevel: level => { const row = levels.current; row.shift(); row.push(level); },
      onPartial: answer => setLive(current => {
        // Settled words are shown as they will land: line breaks and scratches already applied.
        const stable = answer.segments.length ? applySegments("", 0, answer.segments).value : answer.stable;
        const revision = answer.revision && stable === answer.stable ? { ...answer.revision, key: performance.now() } : null;
        return { stable, provisional: answer.provisional, commands: liveCommands(answer.segments), revision: revision || (current?.revision && performance.now() - current.revision.key < 1000 ? current.revision : null) };
      }),
      onFinal: deliver,
    };
    const toBrowser = current => {
      const reason = current.chosen ? "You chose the browser's speech input." : current.state === "missing" ? "Neyvia's speech engine isn't set up on this PC." : "Neyvia's speech engine isn't reachable.";
      if (!(window.SpeechRecognition || window.webkitSpeechRecognition)) {
        capture.current = null;
        setState({ status: "error", message: `${reason} This browser has no speech input either.` });
        setLive(null);
        return;
      }
      // The browser's words get the same prompt policy (commands, names, cleanup) from the backend.
      capture.current = startBrowserDictation({
        ...callbacks,
        note: current.chosen ? reason : `${reason} Using the browser's speech input.`,
        onPartial: text => setLive({ stable: "", provisional: text, commands: [], revision: null }),
        onFinal: (text, info) => {
          if (!text.trim()) return;
          void processSpoken(text).then(answer => normalizeAnswer(answer, true), () => normalizeAnswer({ text }, true))
            .then(final => deliver({ ...final, engine: "browser", route_note: explainRoute(final) }, info));
        },
      });
    };
    if (status && !status.then && status.providerWanted === "browser") toBrowser({ ...status, chosen: true });
    else if (status && !status.then && !["ready", "starting", "loading", "off"].includes(status.state)) toBrowser(status);
    else {
      capture.current = startDictation({
        status, waitReady, explain: explainRoute, ...callbacks, log,
        wakeEngine: () => void readStatus({ start: true }),
        onUnavailable: current => { capture.current = null; toBrowser(current); },
      });
    }
    beginning.current = false;
    if (endEarly.current && capture.current) void capture.current.stop();  // released while the mic was opening
  }, []);

  const finish = useCallback(() => { const current = capture.current; if (current) void current.stop(); }, []);
  const cancel = useCallback(() => { const current = capture.current; capture.current = null; current?.cancel(); setLive(null); }, []);
  const clear = useCallback(() => { kept.current = null; setState({ status: "idle", message: "" }); }, []);
  const retry = useCallback(() => {
    const again = kept.current;
    if (!again || capture.current) return;
    kept.current = null;
    capture.current = again;
    void again.retry();
  }, []);

  // A press that turns out to be a hold ends on release; a short click keeps listening until the next click.
  const press = useCallback(() => {
    if (beginning.current) endEarly.current = true;  // second click while the mic opens: stop once it's open
    else if (capture.current) finish();
    else void begin();
  }, [begin, finish]);
  const release = useCallback(() => {
    if (performance.now() - pressedAt.current < HOLD_MS) return;  // a click: keep listening
    if (beginning.current) endEarly.current = true;
    else if (capture.current) finish();
  }, [finish]);

  useEffect(() => () => capture.current?.cancel(), []);
  // Paul dictates most prompts: the first text box on screen starts the engine (~35 s cold), so the
  // first press is usually instant. The engine stays warm; "enabled: false" in settings turns this off.
  useEffect(() => { if (!prewarmed) { prewarmed = true; void readStatus({ start: true }); } }, []);

  // Keyboard: hold Ctrl+Shift+Space in this target (or the last one used), Esc cancels.
  const extraRef = useRef(extra);
  extraRef.current = extra;
  useEffect(() => {
    const target = {
      kind, containerRef, press, release,
      cancel: () => { if (capture.current || beginning.current) cancel(); else extraRef.current?.stopSending?.(); },
      busy: () => Boolean(capture.current || beginning.current || extraRef.current?.sending?.()),
    };
    const unregister = register(target);
    const onFocus = () => {
      const at = targets.indexOf(target);
      if (at >= 0) { targets.splice(at, 1); targets.push(target); }
      wakeSoon();  // clicking into the box is the earliest hint Paul may dictate: start an idle engine now
    };
    const container = containerRef?.current;
    container?.addEventListener("focusin", onFocus);
    return () => {
      container?.removeEventListener("focusin", onFocus);
      unregister();
    };
  }, [containerRef, press, release, cancel, kind]);

  return { state, live: shown, levels, active, busy, press, release, cancel, clear, retry, prewarm: () => { void readStatus({ start: true }); void prepareAudio(); } };
}

/**
 * Prompt dictation into a textarea (value in React state). Words show in the box while talking, the final text
 * goes in at the cursor, spoken commands run in order, and every change can be undone with one tap.
 * onSend() is called after a short visible preview when Paul says "send it".
 */
export function useTextareaDictation({ inputRef, setText, containerRef, onSend, kind = "composer" }) {
  const anchor = useRef({ at: 0, value: "" });
  const lastCaret = useRef(null);
  const history = useRef([]); // [{before, after, caretBefore, start, end, sid, label}]
  const [notice, setNotice] = useState(null); // {text, tone, undo, fixes, language, busy}
  const [sending, setSending] = useState(null); // {until}
  const [shimmer, setShimmer] = useState(null); // {start, end, key}: a late revision, in value coordinates
  const sendTimer = useRef(0);
  const noticeTimer = useRef(0);
  const latest = useRef({ setText, onSend });
  latest.current = { setText, onSend };

  const valueNow = () => inputRef.current?.value ?? "";
  const write = (value, caret, { focus = true } = {}) => {
    latest.current.setText(value);
    requestAnimationFrame(() => {
      const element = inputRef.current;
      if (!element || caret == null) return;
      if (focus) element.focus();
      if (focus || document.activeElement === element) element.setSelectionRange(caret, caret);
    });
  };
  const say = (next, ms = NOTICE_MS) => {
    clearTimeout(noticeTimer.current);
    setNotice(next);
    if (next && ms) noticeTimer.current = setTimeout(() => setNotice(null), ms);
  };

  const sendingNow = useRef(false);
  sendingNow.current = Boolean(sending);
  const stopSending = (why = "") => {
    clearTimeout(sendTimer.current);
    if (sendingNow.current && why) say({ text: why, tone: "info" }, 4000);
    sendingNow.current = false;
    setSending(null);
  };
  const startSending = () => {
    clearTimeout(sendTimer.current);
    if (!latest.current.onSend) { say({ text: "“Send it” was heard, but there's nothing to send from here.", tone: "warn" }); return; }
    const until = Date.now() + SEND_PREVIEW_MS;
    sendingNow.current = true;
    setSending({ until });
    sendTimer.current = setTimeout(() => { sendingNow.current = false; setSending(null); latest.current.onSend?.(); }, SEND_PREVIEW_MS);
  };
  const sendNow = () => { clearTimeout(sendTimer.current); sendingNow.current = false; setSending(null); latest.current.onSend?.(); };

  const undoLast = (why = "Undone.") => {
    const entry = history.current.pop();
    if (!entry) { say({ text: "Nothing dictated to undo.", tone: "info" }, 4000); return false; }
    if (valueNow() !== entry.after) {
      say({ text: "Can't undo that: the text changed since.", tone: "warn" });
      return false;
    }
    write(entry.before, entry.caretBefore);
    setShimmer(null);
    say({ text: why, tone: "info", redo: entry }, 6000);
    return true;
  };
  const redo = entry => {
    if (valueNow() !== entry.before) return;
    history.current.push(entry);
    write(entry.after, entry.end);
    say(null);
  };

  const revise = (sid, answer) => {
    const entry = [...history.current].reverse().find(item => item.sid === sid);
    if (!entry) return;
    const final = normalizeAnswer(answer, true);
    const result = applySegments(entry.before, entry.at, final.segments);
    const current = valueNow();
    const language = LANGUAGE_LABELS[final.language] || "";
    if (current !== entry.after) {
      say({ text: `${final.engine === "qwen" ? "Qwen" : "The second engine"} read it as: “${final.text}”. Not applied: the text changed since.`, tone: "warn" }, 0);
      return;
    }
    if (result.value === current) { say({ text: `Checked again with Qwen${language ? ` (${language})` : ""}: no change.`, tone: "info" }, 5000); return; }
    // Keep the caret where Paul left it: behind the change it stays put, after it moves with the text.
    const element = inputRef.current;
    const caret = element ? element.selectionStart : null;
    const shifted = caret == null ? null : caret >= entry.end ? caret + (result.end - entry.end) : Math.min(caret, result.end);
    history.current.push({ before: current, after: result.value, caretBefore: caret ?? entry.end, at: entry.at, start: result.start, end: result.end, sid, label: "qwen" });
    write(result.value, shifted, { focus: false });
    setShimmer({ start: result.start, end: result.end, key: performance.now() });
    say({ text: `Rewritten with Qwen${language ? ` (${language})` : ""}.`, tone: "info", undo: true, fixes: final.fixes });
    if (final.segments.some(segment => segment.op === "send")) startSending();
  };

  const onFinal = (final, info) => {
    const current = valueNow();
    const at = shiftAnchor(anchor.current.value, current, anchor.current.at);
    const result = applySegments(current, at, final.segments);
    const language = final.language && final.language !== "en" ? LANGUAGE_LABELS[final.language] : "";
    const done = result.done.filter(op => !["undo", "send", "cancel", "scratch"].includes(op) || (op === "scratch" && !result.actions.scratchPrevious));
    if (result.actions.cancel) { say({ text: "Dropped that dictation.", tone: "info" }, 4000); return; }
    if (result.actions.undo || result.actions.scratchPrevious) {
      undoLast(result.actions.undo ? "Undone." : "Scratched the last dictation.");
      return;
    }
    if (result.value !== current) {
      history.current.push({ before: current, after: result.value, caretBefore: at, at, start: result.start, end: result.end, sid: info?.sid, label: "dictation" });
      if (history.current.length > 30) history.current.shift();
      write(result.value, result.caret);
    }
    if (final.redecode && info?.sid) {
      say({ text: "That sounded French: checking it with the French engine…", tone: "info", busy: true, undo: result.value !== current }, 0);
      void redecodeDictation(info.sid).then(answer => revise(info.sid, answer), error => say({ text: error?.code === "qwen_pcm_unavailable"
        ? "The French engine here can't check live speech yet, so the English engine's guess stays. Check it, or Undo."
        : `The French check didn't answer (${error.message}). Check the text.`, tone: "warn", undo: true }, 0));
      return;
    }
    if (result.actions.send) startSending();
    if (result.value !== current || final.fixes.length || final.route_note) {
      say({ text: final.route_note || "", tone: final.route_note ? "warn" : "info", undo: result.value !== current, fixes: final.fixes, language, done });
    }
  };

  const dictation = useDictation({
    containerRef, kind, onFinal,
    onBegin: () => {
      const element = inputRef.current;
      const value = valueNow();
      const caret = element && document.activeElement === element ? element.selectionStart : lastCaret.current;
      anchor.current = { at: caret ?? value.length, value };
      stopSending();
      setShimmer(null);
      say(null);
    },
    extra: { sending: () => sendingNow.current, stopSending: () => stopSending("Send stopped.") },
  });

  // Where the caret was, for a mic click that took the focus; editing stops a pending send.
  useEffect(() => {
    const element = inputRef.current;
    if (!element) return undefined;
    const track = () => { lastCaret.current = element.selectionStart; };
    const edited = () => { track(); stopSending("Send stopped: you edited the text."); };
    element.addEventListener("select", track);
    element.addEventListener("keyup", track);
    element.addEventListener("pointerup", track);
    element.addEventListener("input", edited);
    return () => {
      element.removeEventListener("select", track);
      element.removeEventListener("keyup", track);
      element.removeEventListener("pointerup", track);
      element.removeEventListener("input", edited);
    };
  });
  useEffect(() => () => { clearTimeout(sendTimer.current); clearTimeout(noticeTimer.current); }, []);
  useEffect(() => {
    if (!shimmer) return undefined;
    const timer = setTimeout(() => setShimmer(null), 900);
    return () => clearTimeout(timer);
  }, [shimmer]);

  return {
    ...dictation,
    field: { inputRef, anchor, shimmer },
    notice, sending,
    undo: () => undoLast(),
    redo,
    dismiss: () => say(null),
    keepNotice: () => clearTimeout(noticeTimer.current),
    stopSending: () => stopSending("Send stopped."),
    sendNow,
  };
}

/** Start dictating in a mounted target by kind ("composer", "new-chat", "notes"); for voice control. */
export function startDictationIn(kind = "composer") {
  const target = [...targets].reverse().find(item => item.containerRef?.current?.isConnected && (!kind || item.kind === kind));
  if (!target || target.busy()) return false;
  target.press();
  return true;
}

function pickTarget() {
  const focused = document.activeElement;
  return targets.find(target => target.busy()) ||
    [...targets].reverse().find(target => target.containerRef?.current?.contains(focused)) ||
    targets[targets.length - 1];
}

let keyHeld = null;
const onKeyDown = event => {
  if (event.code === "Space" && event.ctrlKey && event.shiftKey && !event.altKey) {
    event.preventDefault();
    if (event.repeat || keyHeld) return;
    keyHeld = pickTarget();
    keyHeld?.press();
  } else if (event.key === "Escape") {
    const target = targets.find(item => item.busy());
    if (target) { event.preventDefault(); event.stopPropagation(); target.cancel(); }
  }
};
const onKeyUp = event => {
  if (keyHeld && (event.code === "Space" || event.key === "Control" || event.key === "Shift")) {
    const target = keyHeld;
    keyHeld = null;
    target.release();
  }
};
const onBlur = () => { if (keyHeld) { const target = keyHeld; keyHeld = null; target.release(); } };

// Listening only while some dictation target is on screen.
function register(target) {
  targets.push(target);
  if (targets.length === 1) {
    window.addEventListener("keydown", onKeyDown, true);
    window.addEventListener("keyup", onKeyUp, true);
    window.addEventListener("blur", onBlur);
  }
  return () => {
    const at = targets.indexOf(target);
    if (at >= 0) targets.splice(at, 1);
    if (!targets.length) {
      window.removeEventListener("keydown", onKeyDown, true);
      window.removeEventListener("keyup", onKeyUp, true);
      window.removeEventListener("blur", onBlur);
    }
  };
}

/** The mic button. */
export function MicButton({ dictation, disabled = false, size = 32 }) {
  const { state, busy, press, release, prewarm } = dictation;
  const listening = ["starting", "listening"].includes(state.status);
  const englishOnly = cachedStatus && cachedStatus.state !== "missing" && !(cachedStatus.languages || []).includes("fr");
  const label = listening ? "Stop and insert (or release)" : state.status === "finishing" ? (state.waiting ? "Waiting for the speech model" : "Writing…")
    : `Dictate (click, or hold Ctrl+Shift+Space)${englishOnly ? ". English only for now: no French speech engine yet" : ""}`;
  return (
    <button type="button" className={`nx-mic${listening ? " is-live" : ""}${state.status === "finishing" ? " is-busy" : ""}`}
      style={{ "--nx-mic-size": `${size}px` }} aria-label={label} title={label} aria-pressed={listening || undefined}
      disabled={disabled || state.status === "finishing"}
      onPointerEnter={prewarm} onFocus={prewarm}
      onPointerDown={event => { if (event.button !== 0) return; event.preventDefault(); press(); }}
      onPointerUp={() => release()}
      onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); if (!event.repeat) press(); } }}
      onKeyUp={event => { if (event.key === "Enter" || event.key === " ") release(); }}>
      {state.status === "finishing" ? <Spinner size={13} /> : <Icon as={busy ? Square : Mic} size={busy ? 13 : 16} />}
    </button>
  );
}

const MIRRORED = ["fontFamily", "fontSize", "fontWeight", "fontStyle", "lineHeight", "letterSpacing", "wordSpacing", "textTransform",
  "textIndent", "tabSize", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "borderTopWidth", "borderRightWidth",
  "borderBottomWidth", "borderLeftWidth", "borderTopLeftRadius", "borderTopRightRadius", "borderBottomLeftRadius", "borderBottomRightRadius"];

/**
 * The words while talking, drawn in the text box itself: an overlay with the box's exact font and wrapping shows
 * the text around the dictation point, the settled words, and the grey provisional ones. Also shows a late
 * revision's brief shimmer. Place it right after the textarea.
 */
export function DictationGhost({ dictation }) {
  const ghost = useRef(null);
  const field = dictation.field;
  const element = field?.inputRef.current;
  const live = dictation.live;
  const talking = Boolean(live && ["starting", "listening", "finishing"].includes(dictation.state.status) && (live.stable || live.provisional || live.commands.length));
  const shimmer = field?.shimmer;
  const shown = Boolean(element && (talking || shimmer));
  const [, rerender] = useState(0);

  // Typing while talking re-draws the overlay.
  useEffect(() => {
    if (!element || !talking) return undefined;
    const onInput = () => rerender(value => value + 1);
    element.addEventListener("input", onInput);
    return () => element.removeEventListener("input", onInput);
  }, [element, talking]);

  useLayoutEffect(() => {
    const box = ghost.current;
    if (!element) return undefined;
    element.classList.toggle("nx-dict-masked", shown);
    element.classList.toggle("is-talking", talking);
    if (!shown || !box) return undefined;
    const style = getComputedStyle(element);
    for (const name of MIRRORED) box.style[name] = style[name];
    const scrollbar = element.offsetWidth - element.clientWidth - parseFloat(style.borderLeftWidth) - parseFloat(style.borderRightWidth);
    box.style.paddingRight = `${parseFloat(style.paddingRight) + Math.max(0, scrollbar)}px`;
    box.style.left = `${element.offsetLeft}px`;
    box.style.top = `${element.offsetTop}px`;
    box.style.width = `${element.offsetWidth}px`;
    // The composer grows with its text: let it grow with the spoken words too.
    const max = parseFloat(style.maxHeight) || Infinity;
    box.style.height = "auto";
    const needed = Math.min(box.scrollHeight, max);
    if (element.style.height && needed > element.offsetHeight) element.style.height = `${needed}px`;
    box.style.height = `${element.offsetHeight}px`;
    // Keep the newest words in view.
    const end = box.querySelector(".nx-ghost-end");
    if (talking && end && end.offsetTop + end.offsetHeight > element.scrollTop + element.clientHeight) {
      element.scrollTop = end.offsetTop + end.offsetHeight - element.clientHeight;
    }
    box.scrollTop = element.scrollTop;
    const sync = () => { box.scrollTop = element.scrollTop; };
    element.addEventListener("scroll", sync);
    return () => element.removeEventListener("scroll", sync);
  });
  useEffect(() => () => element?.classList.remove("nx-dict-masked", "is-talking"), [element]);

  if (!shown) return null;
  const value = element.value;
  if (talking) {
    const at = shiftAnchor(field.anchor.current.value, value, field.anchor.current.at);
    const parts = previewParts(value, at, live.stable, live.provisional);
    const revision = live.revision;
    let stable = parts.stable;
    let flash = null;
    if (revision && typeof revision.at === "number" && revision.to) {
      // Offsets are in the stable text; the joined copy may start with one space.
      const lead = stable.length - live.stable.length;
      const from = Math.max(0, revision.at + lead);
      const to = Math.min(stable.length, from + revision.to.length);
      if (to > from) { flash = stable.slice(from, to); stable = [stable.slice(0, from), stable.slice(to)]; }
    }
    return (
      <div ref={ghost} className="nx-dict-ghost" aria-hidden="true">
        <span>{parts.before}</span>
        {Array.isArray(stable) ? <span className="nx-ghost-stable">{stable[0]}<span key={revision.key} className="nx-ghost-revised">{flash}</span>{stable[1]}</span>
          : <span className="nx-ghost-stable">{stable}</span>}
        <span className="nx-ghost-provisional">{parts.provisional}</span>
        <span className="nx-ghost-end">{"​"}</span>
        <span>{parts.after}</span>
        {"\n"}
      </div>
    );
  }
  const start = Math.min(shimmer.start, value.length);
  const end = Math.min(shimmer.end, value.length);
  return (
    <div ref={ghost} className="nx-dict-ghost is-settled" aria-hidden="true">
      <span>{value.slice(0, start)}</span>
      <span key={shimmer.key} className="nx-ghost-revised">{value.slice(start, end)}</span>
      <span>{value.slice(end)}</span>
      {"\n"}
    </div>
  );
}

const LIVE_LABEL = { starting: "Listening…", listening: "Listening…", finishing: "Writing…" };

/** Above the box: waveform, state, spoken commands as chips; afterwards Undo, name fixes, language, send preview. */
export function DictationStrip({ dictation }) {
  const { state, live, levels, cancel, clear, notice, sending } = dictation;
  const canvas = useRef(null);
  const talking = ["starting", "listening", "finishing"].includes(state.status);
  const inBox = Boolean(dictation.field?.inputRef.current?.isConnected);
  useEffect(() => {
    if (!talking) return undefined;
    let frame = 0;
    const draw = () => {
      const element = canvas.current;
      if (element) {
        const context = element.getContext("2d");
        const { width, height } = element;
        context.clearRect(0, 0, width, height);
        context.fillStyle = getComputedStyle(element).color;
        const row = levels.current;
        const bar = width / row.length;
        row.forEach((level, index) => {
          const h = Math.max(2, Math.min(1, Math.sqrt(level) * 1.4) * height);
          context.fillRect(index * bar + 1, (height - h) / 2, Math.max(1, bar - 2), h);
        });
      }
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [talking, levels]);

  if (sending) return <SendPreview dictation={dictation} />;
  if (talking) {
    const words = live ? `${live.stable}${live.stable && live.provisional ? " " : ""}${live.provisional}` : "";
    const hint = state.status === "finishing" ? state.message : words && inBox ? LIVE_LABEL[state.status] : words ? "" : state.message;
    return (
      <div className={`nx-dictation-strip is-${state.status}${state.cold || state.waiting ? " is-cold" : ""}`} role="status" aria-live="polite">
        <canvas ref={canvas} width={96} height={24} aria-hidden="true" />
        <span className={`nx-dictation-text${inBox || !words ? " is-hint" : ""}`}>
          {inBox || !words ? hint : <><span>{live.stable}</span> <span className="nx-ghost-provisional">{live.provisional}</span></>}
        </span>
        {live?.commands?.length ? (
          <span className="nx-dictation-chips">{live.commands.map((op, index) => <span key={`${op}${index}`} className="nx-dictation-chip">{COMMAND_LABELS[op] || op}</span>)}</span>
        ) : null}
        {state.status !== "finishing" || state.waiting ? (
          <button type="button" className="nx-dictation-cancel" onClick={cancel} title={state.waiting ? "Drop this recording (Esc)" : "Cancel (Esc)"} aria-label="Cancel dictation"><Icon as={X} size={13} /></button>
        ) : null}
      </div>
    );
  }
  if (notice) return <DictationNotice dictation={dictation} />;
  if (!state.message) return null;
  return (
    <div className={`nx-dictation-note${state.status === "error" ? " is-error" : state.tone === "warn" ? " is-warn" : ""}`} role={state.status === "error" ? "alert" : "status"}>
      <Icon as={Mic} size={13} /><span>{state.message}</span>
      {state.canRetry ? <Button size="sm" variant="ghost" onClick={dictation.retry}>Try again</Button> : null}
      <button type="button" aria-label="Dismiss" onClick={clear}><Icon as={X} size={13} /></button>
    </div>
  );
}

function DictationNotice({ dictation }) {
  const { notice, undo, redo, dismiss } = dictation;
  const [namesOpen, setNamesOpen] = useState(false);
  const namesButton = useRef(null);
  const closeNames = useCallback(() => setNamesOpen(false), []);
  const fixes = (notice.fixes || []).filter(fix => fix.kind === "name");
  const done = notice.done || [];
  return (
    <div className={`nx-dictation-note is-after${notice.tone === "warn" ? " is-warn" : ""}`} role="status" aria-live="polite">
      {notice.busy ? <Spinner size={12} /> : <Icon as={Mic} size={13} />}
      <span className="nx-dictation-after">
        {notice.text ? <span className="nx-dictation-msg">{notice.text}</span> : null}
        {done.map((op, index) => <span key={`${op}${index}`} className="nx-dictation-chip is-done">{COMMAND_LABELS[op] || op}</span>)}
        {fixes.map(fix => <span key={`${fix.from}${fix.to}`} className="nx-dictation-fix" title="Name fixed from what was heard">{fix.from} → <strong>{fix.to}</strong></span>)}
        {notice.language ? <span className="nx-dictation-lang">{notice.language}</span> : null}
        {!notice.text && !done.length && !fixes.length && !notice.language ? <span>Inserted.</span> : null}
      </span>
      {notice.undo ? <Button size="sm" variant="ghost" icon={Undo2} onClick={undo}>Undo</Button> : null}
      {notice.redo ? <Button size="sm" variant="ghost" onClick={() => redo(notice.redo)}>Redo</Button> : null}
      <button ref={namesButton} type="button" className="nx-dictation-names-btn" aria-label="Names Neyvia should write correctly" title="Names" onClick={() => { dictation.keepNotice?.(); setNamesOpen(open => !open); }}>
        <Icon as={BookA} size={13} />
      </button>
      <button type="button" aria-label="Dismiss" onClick={dismiss}><Icon as={X} size={13} /></button>
      <NamesPopover anchor={namesButton} open={namesOpen} onClose={closeNames} />
    </div>
  );
}

function SendPreview({ dictation }) {
  const { sending, stopSending, sendNow } = dictation;
  const [left, setLeft] = useState(() => Math.max(0, sending.until - Date.now()));
  useEffect(() => {
    const timer = setInterval(() => setLeft(Math.max(0, sending.until - Date.now())), 100);
    return () => clearInterval(timer);
  }, [sending.until]);
  return (
    <div className="nx-dictation-note is-sending" role="status" aria-live="assertive" style={{ "--nx-send-ms": `${SEND_PREVIEW_MS}ms` }}>
      <Icon as={Send} size={13} />
      <span>Sending in {Math.ceil(left / 1000)} s. Check the text, or stop.</span>
      <Button size="sm" variant="outline" onClick={stopSending}>Stop (Esc)</Button>
      <Button size="sm" variant="primary" onClick={sendNow}>Send now</Button>
      <i className="nx-send-progress" aria-hidden="true" />
    </div>
  );
}

/** Names Neyvia writes correctly: built-ins and Paul's own "when I say X, write Y". */
function NamesPopover({ anchor, open, onClose }) {
  const [names, setNames] = useState(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ from: "", to: "" });
  useEffect(() => {
    if (!open) return;
    setError("");
    dictationNames({ action: "list" }).then(answer => setNames(answer?.names || []), failure => setError(failure.message));
  }, [open]);
  const change = async payload => {
    setError("");
    try { const answer = await dictationNames(payload); setNames(answer?.names || []); return true; }
    catch (failure) { setError(failure.message); return false; }
  };
  const add = async event => {
    // The popover renders in a portal, but React still bubbles its submit to the composer's <form>: without this,
    // Enter here also sent the prompt.
    event.preventDefault();
    event.stopPropagation();
    if (!form.from.trim() || !form.to.trim()) return;
    if (await change({ action: "add", from: form.from.trim(), to: form.to.trim() })) setForm({ from: "", to: "" });
  };
  return (
    <Popover anchor={anchor} open={open} onClose={onClose} placement="top-end" width={340} label="Names" className="nx-names-pop">
      <div className="nx-names" onKeyDown={event => { if (event.key !== "Escape") event.stopPropagation(); }}>
        <strong>Names Neyvia writes correctly</strong>
        <p>When dictation hears a sound-alike, it writes the name.</p>
        <ul className="nx-names-list nx-scroll">
          {names == null && !error ? <li className="is-muted"><Spinner size={11} /> Loading…</li> : null}
          {(names || []).map(name => (
            <li key={name.to}>
              <span className="nx-names-to">{name.to}</span>
              <span className="nx-names-from">{(name.from || []).join(", ")}</span>
              {!name.builtin ? (
                <button type="button" aria-label={`Remove ${name.to}`} onClick={() => void change({ action: "remove", to: name.to })}><Icon as={X} size={12} /></button>
              ) : null}
            </li>
          ))}
        </ul>
        <form className="nx-names-add" onSubmit={add}>
          <input className="nx-input" placeholder="When I say…" aria-label="Heard as" value={form.from} onChange={event => setForm(current => ({ ...current, from: event.target.value }))} />
          <input className="nx-input" placeholder="write" aria-label="Write" value={form.to} onChange={event => setForm(current => ({ ...current, to: event.target.value }))} />
          <Button size="sm" type="submit" disabled={!form.from.trim() || !form.to.trim()}>Add</Button>
        </form>
        {error ? <p className="nx-names-error" role="alert">{error}</p> : null}
      </div>
    </Popover>
  );
}

export { micMessage };

