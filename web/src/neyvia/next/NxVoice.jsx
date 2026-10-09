import { useCallback, useEffect, useRef, useState } from "react";
import { AudioLines, CircleAlert, CircleCheck, CircleHelp, Keyboard, Mic, Square, X } from "lucide-react";

import "./nxVoice.css";
import { Icon, Kbd, Spinner, useFocusTrap } from "./nxPrimitives.jsx";
import { engineStatus, startBrowserDictation, startDictation } from "./nxDictation.js";
import { isVoiceUnavailable, loadVoiceCommands, runVoiceCommand } from "./nxVoice.js";
import { announce } from "./nxAnnounce.js";
import { os, useOs } from "./nxOsStore.js";

// Voice control (plan 15 T3): hold Ctrl+Alt+Space (or press the Voice button in the strip),
// say a command, release. The words go to the same speech engine as dictation; the command
// goes to the backend grammar, which acts through the command bus. A small card shows what
// was heard and what happened, and says it to screen readers. Commands can be typed too.

const HOLD_MS = 350;
const KEY_HINT = "Ctrl Alt Space";

async function waitReady(say) {
  const began = Date.now();
  for (;;) {
    let status;
    try { status = await engineStatus({ start: true }); } catch (error) { status = { state: "unreachable", error: error.message }; }
    if (status.state === "ready") return status;
    if (["missing", "error", "unreachable"].includes(status.state)) throw new Error(status.error || "The speech engine couldn't start.");
    const seconds = Math.round((Date.now() - began) / 1000);
    if (seconds > 120) throw new Error("The speech engine is taking too long to start.");
    say(`The speech model is starting (${seconds} s)… keep talking, your words are kept.`);
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
}

const voice = { api: null };
/** Start listening for a command from anywhere (the strip button, the launcher). */
export function startVoiceCommand() { voice.api?.toggle(); }

function useVoiceControl() {
  // status: idle | listening | finishing | working | answered | error
  const [state, setState] = useState({ status: "idle", heard: "", partial: "", answer: null, message: "" });
  const capture = useRef(null);
  const pressedAt = useRef(0);
  const opening = useRef(false);
  const stopEarly = useRef(false);

  const run = useCallback(async (text, language = "") => {
    // A typed command (or a picked choice) while the mic is open: the typed one wins, the recording is dropped.
    const recording = capture.current;
    if (recording) { capture.current = null; recording.cancel(); }
    const words = String(text || "").trim();
    if (!words) { setState(current => ({ ...current, status: "error", partial: "", message: "Nothing was heard. Try again a little closer to the mic." })); return; }
    setState(current => ({ ...current, status: "working", heard: words, partial: "", answer: null, message: "" }));
    try {
      const answer = await runVoiceCommand(words, { language });
      setState(current => ({ ...current, status: "answered", answer, message: "" }));
      const say = answer.say || answer.error || (answer.status === "no_match" ? "I didn't catch a command." : "");
      announce(say, { assertive: answer.status === "refused" || answer.status === "failed" });
    } catch (error) {
      const message = isVoiceUnavailable(error)
        ? "Voice commands need a newer Neyvia service on this PC. Update Neyvia, then try again."
        : error?.message || "That command didn't reach Neyvia.";
      setState(current => ({ ...current, status: "error", message }));
      announce(message, { assertive: true });
    }
  }, []);

  const begin = useCallback(async () => {
    if (capture.current || opening.current) return;
    opening.current = true;
    stopEarly.current = false;
    pressedAt.current = performance.now();
    setState({ status: "listening", heard: "", partial: "", answer: null, message: "Listening for a command…" });
    let status;
    try { status = await engineStatus({ start: true }); } catch (error) { status = { state: "unreachable", error: error.message }; }
    const callbacks = {
      onState: next => {
        if (next.status === "error") { capture.current = null; setState(current => ({ ...current, status: "error", message: next.message })); }
        else if (next.status === "finishing") setState(current => ({ ...current, status: "finishing", message: next.message }));
        else if (next.status === "idle") capture.current = null;
        else if (next.message) setState(current => ({ ...current, message: next.message }));
      },
      onLevel: () => {},
      onPartial: text => setState(current => ({ ...current, partial: text })),
      onFinal: text => { capture.current = null; void run(text); },
    };
    if (status.state === "ready") capture.current = startDictation({ status, ...callbacks });
    else if (["starting", "off"].includes(status.state)) capture.current = startDictation({ status, buffered: true, waitReady, ...callbacks });
    else if (window.SpeechRecognition || window.webkitSpeechRecognition) capture.current = startBrowserDictation({ ...callbacks, note: "Using the browser's speech input." });
    else setState({ status: "error", heard: "", partial: "", answer: null, message: "Neyvia's speech engine isn't reachable. Type the command instead." });
    opening.current = false;
    if (stopEarly.current && capture.current) void capture.current.stop();
  }, [run]);

  const finish = useCallback(() => {
    if (opening.current) { stopEarly.current = true; return; }
    const current = capture.current;
    if (current) void current.stop();
  }, []);
  const cancel = useCallback(() => {
    const current = capture.current;
    capture.current = null;
    current?.cancel();
    setState({ status: "idle", heard: "", partial: "", answer: null, message: "" });
  }, []);
  const toggle = useCallback(() => { if (capture.current || opening.current) finish(); else void begin(); }, [begin, finish]);
  const release = useCallback(() => { if (performance.now() - pressedAt.current >= HOLD_MS) finish(); }, [finish]);
  const dismiss = useCallback(() => setState({ status: "idle", heard: "", partial: "", answer: null, message: "" }), []);
  const open = useCallback(() => setState(current => (current.status === "idle" ? { ...current, status: "answered", answer: null, message: "" } : current)), []);

  useEffect(() => () => capture.current?.cancel(), []);
  return { state, begin, finish, cancel, toggle, release, run, dismiss, open };
}

const STATUS_ICON = { done: CircleCheck, dry_run: CircleCheck, refused: CircleAlert, failed: CircleAlert, ambiguous: CircleHelp, no_match: CircleHelp };

/** The card above the strip: what was heard, what happened, choices, a box to type a command. */
function VoiceCard({ control }) {
  const { state, toggle, cancel, run, dismiss } = control;
  const [typed, setTyped] = useState("");
  const box = useRef(null);
  const input = useRef(null);
  const listening = state.status === "listening";
  const busy = state.status === "finishing" || state.status === "working";
  const answer = state.answer;
  const tone = state.status === "error" || answer?.status === "refused" || answer?.status === "failed" ? "error"
    : answer?.status === "ambiguous" || answer?.status === "no_match" ? "ask" : answer ? "done" : "";

  // A finished command fades away by itself; anything that needs Paul stays.
  useEffect(() => {
    if (tone !== "done") return undefined;
    const timer = setTimeout(() => { if (!box.current?.contains(document.activeElement)) dismiss(); }, 4500);
    return () => clearTimeout(timer);
  }, [tone, answer, dismiss]);

  const submit = event => {
    event.preventDefault();
    const text = typed.trim();
    if (!text || busy) return;
    setTyped("");
    void run(text);
  };

  return (
    <section ref={box} className={`nx-voice-card${tone ? ` is-${tone}` : ""}${listening ? " is-listening" : ""}`} aria-label="Voice command"
      onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); if (listening) cancel(); else dismiss(); } }}>
      <header className="nx-voice-head">
        <button type="button" className={`nx-voice-mic${listening ? " is-live" : ""}`} onClick={toggle} disabled={busy}
          aria-pressed={listening} aria-label={listening ? "Stop listening and run the command" : "Say a command"}>
          {busy ? <Spinner size={13} /> : <Icon as={listening ? Square : Mic} size={listening ? 12 : 15} />}
        </button>
        <div className="nx-voice-status" role="status" aria-live="polite">
          {listening ? <span className={state.partial ? "" : "is-hint"}>{state.partial || state.message || "Listening for a command…"}</span>
            : state.status === "finishing" ? <span className="is-hint">{state.message || "Writing…"}</span>
            : state.status === "working" ? <span><q>{state.heard}</q> <span className="is-hint">…</span></span>
            : state.status === "error" ? <span className="nx-voice-say"><Icon as={CircleAlert} size={14} />{state.message}</span>
            : answer ? (
              <span className="nx-voice-say">
                <Icon as={STATUS_ICON[answer.status] || CircleHelp} size={14} />
                <span>{answer.say || answer.error || "Done."}{state.heard ? <span className="nx-voice-heard"> · heard <q>{state.heard}</q></span> : null}</span>
              </span>
            ) : <span className="is-hint">Say or type a command. Hold <Kbd>{KEY_HINT}</Kbd> to talk.</span>}
        </div>
        <button type="button" className="nx-voice-x" aria-label="Close voice commands" onClick={() => { if (listening) cancel(); dismiss(); }}><Icon as={X} size={13} /></button>
      </header>
      {answer?.choices?.length ? (
        <div className="nx-voice-choices" role="group" aria-label={answer.status === "ambiguous" ? "Did you mean" : "Try one of these"}>
          {answer.choices.slice(0, 5).map(choice => (
            <button key={choice.text} type="button" className="nx-voice-choice" title={choice.text} onClick={() => void run(choice.text)}>{choice.label || choice.text}</button>
          ))}
        </div>
      ) : null}
      <form className="nx-voice-type" onSubmit={submit}>
        <Icon as={Keyboard} size={13} />
        <input ref={input} value={typed} onChange={event => setTyped(event.target.value)} placeholder="Type a command, like “open notes”"
          aria-label="Type a voice command" autoComplete="off" spellCheck={false} />
        <button type="button" className="nx-voice-help" onClick={() => os.setHelp(true)}>What can I say?</button>
      </form>
    </section>
  );
}

/** Ctrl+Alt+Space (hold to talk, or tap to start and tap again to run) and the card. */
export function NxVoice() {
  const control = useVoiceControl();
  const latest = useRef(control);
  latest.current = control;
  voice.api = control;
  const held = useRef(false);

  useEffect(() => {
    const down = event => {
      if (event.code === "Space" && event.ctrlKey && event.altKey && !event.shiftKey) {
        event.preventDefault();
        if (event.repeat || held.current) return;
        held.current = true;
        latest.current.toggle();
      } else if (event.key === "Escape" && ["listening", "finishing"].includes(latest.current.state.status)) {
        event.preventDefault();
        latest.current.cancel();
      }
    };
    const up = event => {
      if (held.current && (event.code === "Space" || event.key === "Control" || event.key === "Alt")) {
        held.current = false;
        latest.current.release();
      }
    };
    const blur = () => { if (held.current) { held.current = false; latest.current.release(); } };
    window.addEventListener("keydown", down, true);
    window.addEventListener("keyup", up, true);
    window.addEventListener("blur", blur);
    return () => { window.removeEventListener("keydown", down, true); window.removeEventListener("keyup", up, true); window.removeEventListener("blur", blur); };
  }, []);

  if (control.state.status === "idle") return null;
  return <VoiceCard control={control} />;
}

/** The strip's Voice button. */
export function VoiceButton() {
  return (
    <button type="button" className="nx-ind" onClick={() => { voice.api?.open(); voice.api?.toggle(); }}
      aria-label={`Voice commands (hold ${KEY_HINT})`} title={`Voice commands: hold ${KEY_HINT}, say “open notes”, release`}>
      <Icon as={AudioLines} size={12} /><span>Voice</span>
    </button>
  );
}

// ---- the "Keyboard and voice" sheet ------------------------------------------------------

export const KEYMAP = [
  { group: "Everywhere", keys: [
    ["Ctrl Space", "Apps and search (the launcher)"],
    ["Ctrl K", "Search chats"],
    ["Ctrl `", "Switch to a recent chat (keep Ctrl down, tap ` to go further)"],
    ["Ctrl J", "Pop the chat out over the app you are in (again to put it away)"],
    ["C", "Comment mode in an app: point at something, pin a comment, send it to the chat"],
    ["Ctrl Shift Space", "Dictate into the message box or note: hold to talk, release to insert"],
    [KEY_HINT, "Voice command: hold, say it, release (or tap, talk, tap)"],
    ["Ctrl /", "This list (also ? when you're not typing)"],
    ["Tab · Shift Tab", "Move between controls; the first Tab offers “Skip to conversation”"],
    ["Esc", "Close a menu, dialog or app card; cancel dictation"],
  ] },
  { group: "Chats", keys: [
    ["↑ ↓ · Home End", "Move through the chat list, menus and results"],
    ["Enter", "Send (Shift Enter for a new line)"],
    ["Ctrl Enter", "Run a git action or tool form"],
  ] },
  { group: "Files and notes", keys: [
    ["↑ ↓ · Enter", "Pick a file, open it"],
    ["F2", "Rename"],
    ["Delete", "Move to the Recycle Bin"],
    ["Backspace", "Up one folder"],
    ["Space", "Quick look"],
    ["Ctrl Z", "Undo the last file action"],
    ["Ctrl S", "Save the note or file"],
  ] },
  { group: "PDF and panes", keys: [
    ["Page Up · Page Down", "Previous or next page"],
    ["Ctrl F", "Search the PDF"],
    ["H", "Highlight the selection"],
    ["← →", "Resize a region (on a divider) · step through the tour"],
  ] },
];

/** Modal sheet: every keyboard shortcut and every voice command. Ctrl+/, ?, "what can I say", the launcher. */
export function NxKeysHelp() {
  const open = useOs(state => state.help);
  const [grammar, setGrammar] = useState(null);
  const box = useRef(null);
  useFocusTrap(box, open);

  useEffect(() => {
    const onKey = event => {
      const typing = event.target?.closest?.("input, textarea, select, [contenteditable=true]");
      if ((event.ctrlKey && event.key === "/") || (event.key === "?" && !typing && !event.ctrlKey && !event.altKey)) {
        event.preventDefault();
        os.setHelp(!open);
      } else if (open && event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        os.setHelp(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let live = true;
    void loadVoiceCommands().then(result => { if (live) setGrammar(result); });
    requestAnimationFrame(() => box.current?.querySelector("button")?.focus());
    return () => { live = false; };
  }, [open]);

  if (!open) return null;
  return (
    <div className="nx-help-scrim" onMouseDown={event => { if (event.target === event.currentTarget) os.setHelp(false); }}>
      <div ref={box} className="nx-help" role="dialog" aria-modal="true" aria-labelledby="nx-help-title">
        <header className="nx-help-head">
          <h2 id="nx-help-title">Keyboard and voice</h2>
          <button type="button" className="nx-voice-x" aria-label="Close" onClick={() => os.setHelp(false)}><Icon as={X} size={14} /></button>
        </header>
        <div className="nx-help-body nx-scroll" tabIndex={0} role="group" aria-label="Shortcuts and commands">
          <section aria-labelledby="nx-help-keys">
            <h3 id="nx-help-keys">Keyboard</h3>
            {KEYMAP.map(group => (
              <div key={group.group} className="nx-help-group">
                <h4>{group.group}</h4>
                <dl>
                  {group.keys.map(([keys, what]) => (
                    <div key={keys} className="nx-help-row"><dt><Kbd>{keys}</Kbd></dt><dd>{what}</dd></div>
                  ))}
                </dl>
              </div>
            ))}
          </section>
          <section aria-labelledby="nx-help-voice">
            <h3 id="nx-help-voice">Voice</h3>
            <p className="nx-help-note">Hold <Kbd>{KEY_HINT}</Kbd> or press <strong>Voice</strong> in the bottom strip, say one of these, release. English or French. Approve, stop and send only act on what's on screen.</p>
            {grammar ? (
              <dl>
                {grammar.commands.map(command => (
                  <div key={command.intent} className="nx-help-row is-voice">
                    <dt>{command.description}</dt>
                    <dd>{(command.examples || []).map(example => <q key={example}>{example}</q>)}</dd>
                  </div>
                ))}
              </dl>
            ) : <p className="nx-help-note"><Spinner size={12} /> Loading the commands…</p>}
            {grammar?.unavailable ? <p className="nx-help-note is-warn" role="note">This PC's Neyvia service doesn't take voice commands yet; the list shows what it will understand.</p> : null}
          </section>
        </div>
      </div>
    </div>
  );
}

