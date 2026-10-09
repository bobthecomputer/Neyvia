import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChevronDown, CircleHelp, Pause, Play, Plus, Quote, RotateCcw, Send, Sparkles, X } from "lucide-react";

import "./nxAmplify.css";
import { Button, Icon, IconButton, Segmented, Spinner, local, useTick } from "./nxPrimitives.jsx";
import { callNx } from "./nxApi.js";
import { useNx } from "./nxStore.js";
import {
  AUTO_SEND_MS, DEBOUNCE_MS, MODES, amplifyPayload, cardPhase, composeEdit, fieldsFrom, normalMode, openQuestions,
  pointerLabels, receiptLine, secondsLeft, shouldAmplify,
} from "./nxAmplifyModel.js";

// Rough prompt in, good prompt out (plan 20 C14). The composer's text is amplified by the PC
// (prompt_amplify_command) while Paul pauses; on Send the card opens under the composer and,
// in auto mode, sends after a short window unless he edits, holds or a question is open.
// Contract: plans/15-handoff.md ## C14.

const newRequestId = prefix => `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

export function useAmplifyMode() {
  const [mode, setModeState] = useState(() => normalMode(local.get("amplify.mode", "auto")));
  useEffect(() => {
    const onChange = event => setModeState(normalMode(event.detail));
    window.addEventListener("nx:amplify-mode", onChange);
    return () => window.removeEventListener("nx:amplify-mode", onChange);
  }, []);
  const setMode = useCallback(next => {
    const value = normalMode(next);
    local.set("amplify.mode", value === "auto" ? null : value);
    window.dispatchEvent(new CustomEvent("nx:amplify-mode", { detail: value }));
  }, []);
  return [mode, setMode];
}

/**
 * The amplification for the composer's current text. `entry` belongs to one exact text;
 * when the text changes the old entry stops counting and a new one is asked for after a pause.
 */
export function useAmplifier({ sessionId, draft, enabled, items, project, mode }) {
  const [entry, setEntry] = useState(null); // {text, requestId, status: pending|ready|error, amplification, error}
  const [open, setOpen] = useState(null); // null | "staged" (Send pressed) | "peek" (opened to look)
  const live = useRef(null);
  live.current = entry;
  // Streaming turns change `items` often; read them at request time so the pause timer isn't restarted.
  const context = useRef(null);
  context.current = { items, project, mode };
  const text = String(draft || "").trim();
  const current = entry && entry.text === text ? entry : null;
  const event = useNx(state => state.amplify?.[sessionId]);

  const request = useCallback(async value => {
    const requestId = newRequestId("amp");
    setEntry({ text: value, requestId, status: "pending", startedAt: Date.now() });
    try {
      const result = await callNx("prompt_amplify_command", amplifyPayload({ text: value, requestId, sessionId, ...context.current }));
      const amplification = result?.amplification || result;
      if (!amplification?.id) throw new Error("The PC answered without an amplified prompt.");
      if (live.current?.requestId !== requestId) return;
      setEntry({ text: value, requestId, status: "ready", amplification });
      if (sessionId) local.set(`amplify.${sessionId}`, { id: amplification.id, text: value });
    } catch (error) {
      if (live.current?.requestId !== requestId) return;
      setEntry({ text: value, requestId, status: "error", error: { code: error?.code || "", message: error?.message || "The PC service did not answer." } });
    }
  }, [sessionId]);

  // Another chat: its own draft, its own amplification.
  useEffect(() => { setEntry(null); setOpen(null); }, [sessionId]);

  // Ask once Paul pauses; a new text replaces the old entry.
  useEffect(() => {
    if (!enabled || !shouldAmplify({ mode, message: text })) return undefined;
    if (live.current?.text === text) return undefined;
    const timer = setTimeout(() => void request(text), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [enabled, mode, text, request]);

  // Typing on closes the card; the next pause asks again.
  useEffect(() => {
    if (entry && entry.text !== text) setOpen(null);
  }, [entry, text]);

  // After a reload, the saved draft finds its amplification again (prompt_amplification_get_command).
  useEffect(() => {
    if (!enabled || !sessionId) return;
    const saved = local.get(`amplify.${sessionId}`, null);
    if (!saved?.id || saved.text !== String(local.get(`draft.${sessionId}`, "")).trim()) return;
    let alive = true;
    callNx("prompt_amplification_get_command", { id: saved.id })
      .then(result => {
        const amplification = result?.amplification;
        if (alive && amplification?.id && !live.current && amplification.original?.trim() === saved.text) {
          setEntry({ text: saved.text, requestId: amplification.requestId, status: "ready", amplification });
        }
      })
      .catch(() => {});
    return () => { alive = false; };
  }, [enabled, sessionId]);

  // Another device sent or edited this amplification.
  useEffect(() => {
    const ours = live.current?.amplification;
    if (!event || !ours || event.amplificationId !== ours.id) return;
    if (event.type === "prompt.consumed") { setEntry(null); setOpen(null); }
    else if (event.type === "prompt.edited" && event.revision > ours.revision) {
      void callNx("prompt_amplification_get_command", { id: ours.id }).then(result => {
        if (result?.amplification && live.current?.amplification?.id === ours.id) setEntry(row => ({ ...row, amplification: result.amplification }));
      }).catch(() => {});
    }
  }, [event]);

  const stage = useCallback(() => {
    if (!live.current || live.current.text !== text || live.current.status === "error") void request(text);
    setOpen("staged");
  }, [text, request]);

  const reset = useCallback(() => {
    setEntry(null);
    setOpen(null);
    if (sessionId) local.set(`amplify.${sessionId}`, null);
  }, [sessionId]);

  const replace = useCallback(amplification => setEntry(row => (row ? { ...row, amplification } : row)), []);

  return {
    entry: enabled ? current : null,
    open: enabled && current ? open : null,
    stage,
    peek: () => setOpen("peek"),
    close: () => setOpen(null),
    retry: () => void request(text),
    reset,
    replace,
  };
}

/** A field that reads as a line of text and grows with its words (CSS only: a hidden copy sets the height). */
function AmpText({ className = "", value, ...rest }) {
  const field = useRef(null);
  useLayoutEffect(() => {
    // Native Obscura can retain initial textarea children without populating
    // its value property. Keep the same controlled value before first paint.
    const text = String(value ?? "");
    if (field.current && field.current.value !== text) field.current.value = text;
  }, [value]);
  return (
    <span className={`nx-amp-grow ${className}`} data-value={value}>
      <textarea ref={field} rows={1} className={`nx-amp-input ${className}`} value={value} {...rest} />
    </span>
  );
}

function ListField({ label, values, onChange, placeholder, addLabel, mark, disabled }) {
  if (!values.length && !addLabel) return null;
  return (
    <div className="nx-amp-group">
      <span className="nx-amp-label">{label}</span>
      <ul className="nx-amp-list">
        {values.map((value, index) => (
          <li key={index} className="nx-amp-item">
            <span className={`nx-amp-mark is-${mark}`} aria-hidden="true" />
            <AmpText value={value} disabled={disabled} aria-label={`${label} ${index + 1}`} placeholder={placeholder}
              onChange={event => onChange(values.map((row, at) => (at === index ? event.target.value : row)))} />
            <IconButton icon={X} size="sm" label={`Remove ${label.toLowerCase()} ${index + 1}`} className="nx-amp-remove" disabled={disabled}
              onClick={() => onChange(values.filter((_, at) => at !== index))} />
          </li>
        ))}
      </ul>
      {addLabel ? (
        <button type="button" className="nx-amp-add" disabled={disabled} onClick={() => onChange([...values, ""])}>
          <Icon as={Plus} size={12} /> {addLabel}
        </button>
      ) : null}
    </div>
  );
}

/**
 * The card. `onSend(amplification)` sends the original message with the amplification's id and
 * revision; `onSendOriginal()` sends the words as typed, without the card.
 */
export function NxAmplifyCard({ amplifier, appName, mode, onModeChange, onSend, onSendOriginal, sending }) {
  const { entry, open } = amplifier;
  const amplification = entry?.status === "ready" ? entry.amplification : null;
  const [fields, setFields] = useState(() => fieldsFrom(amplification));
  const [held, setHeld] = useState(false);
  const [original, setOriginal] = useState(false);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [deadline, setDeadline] = useState(0);
  const firing = useRef(false);
  const ownEdit = useRef(""); // the revision Paul's own edit created: the card keeps his fields for it
  const before = useRef(null); // the record as amplified, before any of Paul's edits: what an edit is composed on
  const key = amplification ? `${amplification.id}:${amplification.revision}` : "";

  useEffect(() => {
    if (key && key === ownEdit.current) return;
    before.current = amplification;
    setFields(fieldsFrom(amplification));
    setError("");
    firing.current = false;
    // `key` names the record; the object itself changes identity on every store update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  useEffect(() => {
    setHeld(open === "peek");
    setOriginal(false);
    setMore(false);
  }, [open, entry?.requestId]);

  const phase = open ? cardPhase({ amplification, fields, mode, held }) : "closed";
  useTick(Boolean(open) && entry?.status === "pending", 1000);
  const counting = phase === "count" && !busy && !sending;
  useTick(counting, 250);

  const send = useCallback(async ({ edited }) => {
    if (!amplification || busy || firing.current) return;
    firing.current = true;
    setBusy(true);
    setError("");
    try {
      let target = amplification;
      const text = edited ? composeEdit(before.current || amplification, fields) : "";
      // A retry after a failed send reuses the revision that already holds this exact edit.
      if (edited && !(amplification.status === "edited" && amplification.agentPrompt === text)) {
        const result = await callNx("prompt_amplification_edit_command", {
          id: amplification.id, revision: amplification.revision, requestId: newRequestId("amp-edit"), text,
        });
        target = { ...(result?.amplification || amplification), learning: result?.learning || result?.amplification?.learning || null };
        ownEdit.current = `${target.id}:${target.revision}`;
        amplifier.replace(target);
      }
      await onSend(target);
    } catch (failure) {
      firing.current = false;
      setError(failure?.code === "stale_amplification"
        ? "This prompt changed on another device. Close the card and send again."
        : failure?.message || "The PC service did not answer.");
    } finally {
      setBusy(false);
    }
  }, [amplification, amplifier, busy, fields, onSend]);

  // One timer per window: it starts when the card starts counting and is cleared by Hold, an edit,
  // a question, closing or sending. The seconds shown are display only.
  const sendRef = useRef(send);
  sendRef.current = send;
  useEffect(() => {
    if (!counting) { setDeadline(0); return undefined; }
    setDeadline(Date.now() + AUTO_SEND_MS);
    const timer = setTimeout(() => void sendRef.current({ edited: false }), AUTO_SEND_MS);
    return () => clearTimeout(timer);
  }, [counting, key]);

  if (!entry) return null;
  const update = patch => setFields(current => ({ ...current, ...patch }));
  const waiting = busy || sending;

  if (!open) {
    const asks = (amplification?.questions || []).length;
    // Collapsed: one quiet line while Paul types, so the card never jumps in on Send.
    return (
      <button type="button" className={`nx-amp-peek${entry.status === "error" ? " is-error" : ""}`} onClick={amplifier.peek}
        aria-label={entry.status === "ready" ? `Rewritten prompt: ${amplification.goal || "open"}` : undefined}>
        {entry.status === "pending" ? <Spinner size={11} /> : <Icon as={Sparkles} size={13} />}
        <span className="nx-amp-peek-text">
          {entry.status === "pending" ? "Rewriting the prompt…" : entry.status === "error" ? "Couldn't rewrite the prompt" : amplification.goal || "Rewritten prompt"}
        </span>
        {asks ? <span className="nx-amp-peek-ask"><Icon as={CircleHelp} size={12} /> {asks} {asks === 1 ? "question" : "questions"}</span> : null}
        <Icon as={ChevronDown} size={13} className="nx-amp-peek-caret" />
      </button>
    );
  }

  if (entry.status !== "ready") {
    // Waiting or failed: the words can always go as typed; nothing is sent on a timer from here.
    const waited = entry.startedAt ? Math.max(0, Math.round((Date.now() - entry.startedAt) / 1000)) : 0;
    return (
      <section className="nx-amp is-open" aria-label="Rewritten prompt">
        <div className="nx-amp-head">
          {entry.status === "pending" ? <Spinner size={12} /> : <Icon as={Sparkles} size={14} />}
          <span className="nx-amp-title">{entry.status === "pending" ? "Rewriting the prompt…" : "Couldn't rewrite the prompt"}</span>
          {entry.status === "pending" && waited >= 2 ? <span className="nx-amp-receipt">{waited} s</span> : null}
          <IconButton icon={X} size="sm" label="Close" onClick={amplifier.close} />
        </div>
        {entry.status === "error" ? <p className="nx-amp-error" role="alert">{entry.error.message}</p> : null}
        <div className="nx-amp-foot">
          <span className="nx-amp-status">{entry.status === "pending" ? "Waiting for the PC" : ""}</span>
          {entry.status === "error" ? <Button size="sm" icon={RotateCcw} onClick={amplifier.retry}>Try again</Button> : null}
          <Button size="sm" variant={entry.status === "error" ? "primary" : "outline"} disabled={sending} onClick={onSendOriginal}>Send as typed</Button>
        </div>
      </section>
    );
  }

  const questions = (amplification.questions || []).map(row => (typeof row === "string" ? row : row?.text || "")).filter(Boolean);
  const unanswered = openQuestions(amplification, fields);
  const pointers = pointerLabels(amplification);
  const receipt = receiptLine(amplification);
  const left = deadline ? secondsLeft(deadline) : Math.round(AUTO_SEND_MS / 1000);  // the first frame, before the clock starts
  const extra = fields.constraints.length + pointers.length;

  return (
    <section className={`nx-amp is-open is-${phase}`} aria-label="Rewritten prompt"
      onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); if (phase === "count") setHeld(true); else amplifier.close(); } }}>
      <div className="nx-amp-head">
        <Icon as={Sparkles} size={14} className="nx-amp-glyph" />
        <span className="nx-amp-title">Prompt for {appName}</span>
        {receipt ? <span className="nx-amp-receipt" title="Route and time the PC took">{receipt}</span> : null}
        <Button size="sm" icon={Quote} aria-pressed={original} onClick={() => setOriginal(on => !on)}>Original</Button>
        <IconButton icon={X} size="sm" label="Close without sending" onClick={amplifier.close} />
      </div>

      {original ? <blockquote className="nx-amp-original">{amplification.original}</blockquote> : null}

      <div className="nx-amp-body nx-scroll" onFocus={event => { if (event.target.matches("textarea, input")) setHeld(true); }}>
        <label className="nx-amp-group">
          <span className="nx-amp-label">Goal</span>
          <AmpText className="is-goal" value={fields.goal} disabled={waiting} onChange={event => update({ goal: event.target.value })} />
        </label>
        {fields.deliverable || amplification.deliverable ? (
          <label className="nx-amp-group">
            <span className="nx-amp-label">Deliverable</span>
            <AmpText value={fields.deliverable} disabled={waiting} onChange={event => update({ deliverable: event.target.value })} />
          </label>
        ) : null}
        {questions.map((question, index) => (
          <label key={index} className="nx-amp-group is-question">
            <span className="nx-amp-label"><Icon as={CircleHelp} size={12} /> Question</span>
            <span className="nx-amp-ask">{question}</span>
            <AmpText className="is-answer" value={fields.answers[index] || ""} disabled={waiting} placeholder="Your answer"
              onChange={event => update({ answers: fields.answers.map((row, at) => (at === index ? event.target.value : row)) })} />
          </label>
        ))}
        <ListField label="Checks" mark="check" values={fields.checks} disabled={waiting} addLabel="Add check" onChange={checks => update({ checks })} />
        <ListField label="Assumptions" mark="assume" values={fields.assumptions} disabled={waiting} onChange={assumptions => update({ assumptions })} />
        {extra ? (
          <button type="button" className="nx-amp-more" aria-expanded={more} onClick={() => setMore(on => !on)}>
            <Icon as={ChevronDown} size={12} className="nx-amp-more-caret" />
            {[fields.constraints.length ? `${fields.constraints.length} ${fields.constraints.length === 1 ? "constraint" : "constraints"}` : "",
              pointers.length ? `${pointers.length} ${pointers.length === 1 ? "pointer" : "pointers"}` : ""].filter(Boolean).join(" · ")}
          </button>
        ) : null}
        {more ? (
          <>
            <ListField label="Constraints" mark="limit" values={fields.constraints} disabled={waiting} onChange={constraints => update({ constraints })} />
            {pointers.length ? (
              <div className="nx-amp-group">
                <span className="nx-amp-label">Reads</span>
                <ul className="nx-amp-chips">
                  {pointers.map((pointer, index) => <li key={index} title={pointer.title}>{pointer.label}</li>)}
                </ul>
              </div>
            ) : null}
          </>
        ) : null}
      </div>

      {error ? <p className="nx-amp-error" role="alert">{error}</p> : null}

      <div className="nx-amp-foot">
        {phase === "count" ? (
          <>
            <span className="nx-amp-clock" aria-hidden="true"><span key={deadline} className="nx-amp-clock-fill" style={{ "--amp-ms": `${AUTO_SEND_MS}ms` }} /></span>
            <span className="nx-amp-status" role="status">{waiting ? "Sending…" : `Sends in ${left} s`}</span>
            <Button size="sm" icon={Pause} disabled={waiting} onClick={() => setHeld(true)}>Hold</Button>
          </>
        ) : (
          <span className="nx-amp-status" role="status">
            {phase === "ask" ? (unanswered.length > 1 ? `Answer the ${unanswered.length} questions to send` : "Answer the question to send") : phase === "edited" ? "Edited. Sends when you choose." : waiting ? "Sending…" : "Waiting for you"}
          </span>
        )}
        {phase === "review" && mode === "auto" && held ? (
          <Button size="sm" icon={Play} disabled={waiting} onClick={() => setHeld(false)}>Resume</Button>
        ) : null}
        {phase === "edited" ? (
          <Button size="sm" icon={RotateCcw} disabled={waiting} onClick={() => setFields(fieldsFrom(amplification))}>Undo edits</Button>
        ) : null}
        <Button size="sm" variant="primary" icon={Send} disabled={waiting || unanswered.length > 0}
          onClick={() => void send({ edited: phase === "edited" })}>
          {phase === "edited" ? "Send edited" : "Send now"}
        </Button>
      </div>
      <div className="nx-amp-mode">
        <Segmented size="sm" label="When the prompt is ready" value={mode} options={MODES.filter(row => row.value !== "off")} onChange={onModeChange} />
        <button type="button" className="nx-amp-link" disabled={waiting} onClick={onSendOriginal}>Send as typed</button>
      </div>
    </section>
  );
}
