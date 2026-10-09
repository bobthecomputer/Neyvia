import { useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";

import "./nxChecklist.css";
import { Icon, local } from "./nxPrimitives.jsx";
import { useNx } from "./nxStore.js";
import { RollingNumber, Strike } from "./details/nxDetails.jsx";
import { planOf, planProgress, showChecklist } from "./nxPlanModel.js";

// The agent's own checklist, pinned just above the composer (plan 12 §1A). It comes from the
// agent's plan tool calls (Claude Code todos and tasks, Codex's plan, a Neyvia run's plan) as
// data the backend reads from each call's input; nothing here parses tool text.

function Ring({ done, total }) {
  const r = 7;
  const circumference = 2 * Math.PI * r;
  const ratio = total ? done / total : 0;
  return (
    <svg className="nx-checklist-ring" width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <circle cx="9" cy="9" r={r} className="nx-checklist-ring-track" />
      <circle cx="9" cy="9" r={r} className="nx-checklist-ring-fill" transform="rotate(-90 9 9)"
        strokeDasharray={`${circumference * ratio} ${circumference}`} />
    </svg>
  );
}

function Mark({ status }) {
  if (status === "completed") {
    return (
      <svg className="nx-checklist-mark is-done" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="7" />
        <path d="M4.8 8.3 7 10.4l4.2-4.6" pathLength="1" />
      </svg>
    );
  }
  return <span className={`nx-checklist-mark is-${status === "in_progress" ? "current" : "pending"}`} aria-hidden="true" />;
}

const STATUS_WORDS = { completed: "done", in_progress: "working on it", pending: "to do" };

export function NxChecklist({ sessionId, working }) {
  const thread = useNx(state => state.threads[sessionId]);
  const plan = useMemo(() => planOf(thread), [thread]);
  const [open, setOpen] = useState(() => Boolean(local.get("checklist.open", false)));
  if (!showChecklist(plan, working)) return null;
  const { items, done, total, current, next, finished } = planProgress(plan);
  const headline = current ? (current.active || current.text) : finished ? "All done" : next ? `Next: ${next.text}` : "";
  const toggle = () => { setOpen(!open); local.set("checklist.open", !open || null); };
  return (
    <section className={`nx-checklist${open ? " is-open" : ""}${finished ? " is-finished" : ""}${working ? " is-live" : ""}`} aria-label="Agent checklist">
      <button type="button" className="nx-checklist-head" aria-expanded={open} onClick={toggle}
        title={open ? "Hide the checklist" : "Show the whole checklist"}>
        <Ring done={done} total={total} />
        <span className="nx-checklist-count"><RollingNumber value={done} /> of {total}</span>
        {headline ? <span className="nx-checklist-sep" aria-hidden="true">·</span> : null}
        <span className={`nx-checklist-now${current ? " is-current" : ""}`} aria-live="polite">{headline}</span>
        <Icon as={ChevronDown} size={14} className="nx-checklist-caret" />
      </button>
      {open ? (
        <ol className="nx-checklist-list nx-scroll">
          {plan.explanation ? <li className="nx-checklist-why">{plan.explanation}</li> : null}
          {items.map((item, index) => (
            <li key={item.id || index} className={`nx-checklist-item is-${item.status === "in_progress" ? "current" : item.status === "completed" ? "done" : "pending"}`}
              style={{ "--i": index }}>
              <Mark status={item.status} />
              <span className="nx-checklist-text"><Strike on={item.status === "completed"}>{item.status === "in_progress" && item.active ? item.active : item.text}</Strike></span>
              <span className="nx-visually-hidden">, {STATUS_WORDS[item.status] || "to do"}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
