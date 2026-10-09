// After-task feedback (plan 20 C9.2): which runs ask for it, the three answers, and the request shape.
// Backend contract: plans/15-handoff.md ## C9 (task_feedback_submit_command, feedback.saved, lesson.state).

export const VERDICTS = [
  { id: "good", label: "Good" },
  { id: "not_quite", label: "Not quite" },
  { id: "wrong", label: "Wrong" },
];

const FINISHED = new Set(["completed", "failed"]);
export const MAX_REASON = 4000;

/** Feedback is asked once a run has ended with a result (stopped runs did not finish the task). */
export function asksFeedback(run) {
  return Boolean(run?.runId && FINISHED.has(run.state));
}

export function verdictLabel(id) {
  return VERDICTS.find(row => row.id === id)?.label || "";
}

/** A "good" with no reason is saved at once; "not quite" and "wrong" open the reason box first. */
export function needsReasonStep(verdict) {
  return verdict === "not_quite" || verdict === "wrong";
}

export function submitPayload({ run, sessionId, verdict, reason, reasonSource, requestId }) {
  const text = String(reason || "").trim().slice(0, MAX_REASON);
  return {
    runId: run.runId, sessionId, verdict, requestId,
    ...(text ? { reason: text, reasonSource: reasonSource === "dictated" ? "dictated" : "typed" } : {}),
  };
}

/** Lessons the backend drafted from this feedback, still waiting for the Evolver or decided. */
export function lessonSummary(lessons) {
  const rows = Object.values(lessons || {});
  const testing = rows.filter(row => row.state === "quarantined" || row.state === "testing").length;
  const promoted = rows.filter(row => row.state === "promoted").length;
  const parts = [];
  if (testing) parts.push(`${testing} ${testing === 1 ? "lesson" : "lessons"} to test`);
  if (promoted) parts.push(`${promoted} learned`);
  return parts.join(" · ");
}
