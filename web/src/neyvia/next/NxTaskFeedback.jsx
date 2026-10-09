import { useEffect, useRef, useState } from "react";
import { Check, CircleAlert, ThumbsUp, X } from "lucide-react";

import { DictationGhost, DictationStrip, MicButton, useTextareaDictation } from "./NxDictation.jsx";
import { Button, Icon } from "./nxPrimitives.jsx";
import { callNx } from "./nxApi.js";
import { setFeedback, useNx } from "./nxStore.js";
import { MAX_REASON, VERDICTS, asksFeedback, lessonSummary, needsReasonStep, submitPayload, verdictLabel } from "./nxFeedbackModel.js";
import "./nxFeedback.css";

const ICONS = { good: ThumbsUp, not_quite: CircleAlert, wrong: X };
const newRequestId = () => `fb-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

/**
 * One row under a finished task: Good / Not quite / Wrong, then an optional typed or dictated reason.
 * The backend turns the reason into quarantined lessons (plans/15-handoff.md ## C9); this only saves and shows state.
 */
export function NxTaskFeedback({ sessionId, run }) {
  const saved = useNx(state => state.feedback[run?.runId]);
  const known = saved?.verdict ? saved : run?.feedback ? { verdict: run.feedback.verdict, at: run.feedback.at } : null;
  const [choice, setChoice] = useState(null); // verdict picked, reason box open
  const [reason, setReason] = useState("");
  const [status, setStatus] = useState({ busy: false, error: "" });
  const [editing, setEditing] = useState(false);
  const dictated = useRef(false);
  const inputRef = useRef(null);
  const boxRef = useRef(null);
  const dictation = useTextareaDictation({ inputRef, setText: setReason, containerRef: boxRef, kind: "feedback", onSend: () => void send(choice, true) });

  useEffect(() => {
    if (["starting", "listening"].includes(dictation.state.status)) dictated.current = true;
  }, [dictation.state.status]);
  useEffect(() => {
    if (choice) requestAnimationFrame(() => inputRef.current?.focus());
  }, [choice]);

  if (!asksFeedback(run)) return null;

  async function send(verdict, withReason) {
    if (!verdict || status.busy) return;
    setStatus({ busy: true, error: "" });
    try {
      const result = await callNx("task_feedback_submit_command", submitPayload({
        run, sessionId, verdict, reason: withReason ? reason : "", reasonSource: dictated.current ? "dictated" : "typed", requestId: newRequestId(),
      }));
      const lessons = Object.fromEntries((result?.lessons || []).map(row => [row.id, { state: row.state, title: row.title || "" }]));
      setFeedback(run.runId, { verdict, at: result?.feedback?.at || new Date().toISOString(), reason: withReason ? reason.trim() : "", lessons });
      setChoice(null);
      setEditing(false);
      setReason("");
      dictated.current = false;
      setStatus({ busy: false, error: "" });
    } catch (error) {
      setStatus({ busy: false, error: error?.message || "The PC service did not answer." });
    }
  }

  function pick(verdict) {
    if (needsReasonStep(verdict) || editing) setChoice(verdict);
    else void send(verdict, false);
  }

  if (known && !editing) {
    const summary = lessonSummary(saved?.lessons);
    return (
      <div className="nx-feedback is-saved" role="status">
        <Icon as={Check} size={13} />
        <span>Rated: <strong>{verdictLabel(known.verdict)}</strong>{summary ? ` · ${summary}` : ""}</span>
        <Button size="sm" onClick={() => { setEditing(true); setChoice(known.verdict); setReason(saved?.reason || ""); }}>Change</Button>
      </div>
    );
  }

  return (
    <section className="nx-feedback" aria-label="Rate this result">
      <div className="nx-feedback-row">
        <span className="nx-feedback-label" id={`fb-${run.runId}`}>Rate this result</span>
        <div className="nx-feedback-choices" role="group" aria-labelledby={`fb-${run.runId}`}>
          {VERDICTS.map(row => (
            <Button key={row.id} size="sm" variant={choice === row.id ? "primary" : "outline"} icon={ICONS[row.id]}
              aria-pressed={choice === row.id} disabled={status.busy} onClick={() => pick(row.id)}>{row.label}</Button>
          ))}
        </div>
      </div>
      {choice ? (
        <div className="nx-feedback-reason" ref={boxRef}>
          <label className="nx-feedback-sub" htmlFor={`fb-reason-${run.runId}`}>What should change? Optional</label>
          <div className="nx-feedback-field">
            <textarea id={`fb-reason-${run.runId}`} ref={inputRef} rows={2} maxLength={MAX_REASON} value={reason}
              placeholder="For example: put the result in a table" onChange={event => setReason(event.target.value)}
              onKeyDown={event => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); void send(choice, true); } }} />
            <DictationGhost dictation={dictation} />
            <MicButton dictation={dictation} size={28} />
          </div>
          <DictationStrip dictation={dictation} />
          <div className="nx-feedback-actions">
            <Button size="sm" variant="primary" disabled={status.busy} onClick={() => void send(choice, true)}>{status.busy ? "Saving…" : "Send"}</Button>
            <Button size="sm" disabled={status.busy} onClick={() => (editing && known ? (setEditing(false), setChoice(null)) : void send(choice, false))}>
              {editing && known ? "Cancel" : "Skip reason"}
            </Button>
          </div>
        </div>
      ) : null}
      {status.error ? (
        <p className="nx-feedback-error" role="alert">Couldn't save the rating. {status.error}</p>
      ) : null}
    </section>
  );
}
