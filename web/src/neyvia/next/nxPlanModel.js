import { checkedProofsEModel } from "./nxProofsEContracts.js";
// An agent's own checklist (Claude Code's todos and tasks, Codex's plan, a Neyvia run's plan).
// The backend reads it from each tool call's input and puts a small operation on the item
// (`item.data.plan`), and folds them into `page.plan` for what it read
// (src/grant_agent/connected_sessions/plan.py). Here the same operations are applied to items
// that arrive live after that read, so the checklist moves as the agent works. No tool text is parsed.

const STATUS = new Set(["pending", "in_progress", "completed"]);

function nextId(items) {
  const numbers = items.map(item => Number(item.id)).filter(Number.isInteger);
  return String((numbers.length ? Math.max(...numbers) : 0) + 1);
}

/** The plan after one operation; a replace with no items, or deleting the last item, clears it. */
function raw_applyPlanOp(plan, op, { at = null, seq = null } = {}) {
  if (!op || typeof op !== "object") return plan;
  const source = op.source || plan?.source || null;
  let items = (plan?.items || []).map(item => ({ ...item }));
  let explanation = plan?.explanation ?? null;
  if (op.op === "replace") {
    items = (op.items || []).filter(Boolean).map(item => ({ ...item }));
    explanation = op.explanation ?? null;
    if (!items.length) return null;
  } else if (op.op === "add") {
    if (plan?.source !== op.source) { items = []; explanation = null; }
    const entry = { ...(op.item || {}) };
    entry.id = entry.id || nextId(items);
    items = [...items.filter(item => item.id !== entry.id), entry];
  } else if (op.op === "update") {
    if (!plan) return null;
    const index = items.findIndex(item => item.id === op.id);
    if (index < 0) return plan;
    if (op.status === "deleted") items.splice(index, 1);
    else for (const field of ["status", "text", "active"]) if (op[field]) items[index][field] = op[field];
    if (!items.length) return null;
  } else {
    return plan;
  }
  return { items, source, explanation, updatedAt: at ?? plan?.updatedAt ?? null, throughSeq: seq ?? plan?.throughSeq ?? null };
}

/** The plan a thread shows: what the read returned, plus every live operation that came after it. */
function raw_planOf(thread) {
  if (!thread) return null;
  const after = Number.isFinite(thread.planSeq) ? thread.planSeq : -Infinity;
  let plan = thread.plan || null;
  for (const item of thread.items || []) {
    if (!item?.data?.plan || item.optimistic || !(Number(item.seq) > after)) continue;
    plan = applyPlanOp(plan, item.data.plan, { at: item.at, seq: Number(item.seq) });
  }
  return plan;
}

/** Counts and the item being worked on, for the one-line view. */
function raw_planProgress(plan) {
  const items = (plan?.items || []).map(item => ({ ...item, status: STATUS.has(item.status) ? item.status : "pending" }));
  const done = items.filter(item => item.status === "completed").length;
  const current = items.find(item => item.status === "in_progress") || null;
  const next = current ? null : items.find(item => item.status === "pending") || null;
  return { items, done, total: items.length, current, next, finished: items.length > 0 && done === items.length };
}

/** Pinned while something is left to do, or while the agent works (so the last check can land). */
function raw_showChecklist(plan, working) {
  const { total, finished } = planProgress(plan);
  return total > 0 && (!finished || Boolean(working));
}

/** Where a page's plan leaves off, so live items after it are folded on top. */
function raw_planFromPage(page, existing = null) {
  if (!page || !("plan" in page)) return existing ? { plan: existing.plan ?? null, planSeq: existing.planSeq ?? null } : { plan: null, planSeq: null };
  const seqs = (page.items || []).map(item => Number(item.seq)).filter(Number.isFinite);
  const planSeq = Number.isFinite(page.plan?.throughSeq) ? page.plan.throughSeq : (seqs.length ? Math.max(...seqs) : null);
  return { plan: page.plan || null, planSeq };
}

// Public observers check the executable manual claims on every invocation.
export function applyPlanOp(...args) { return checkedProofsEModel("plan.applyPlanOp", args, raw_applyPlanOp(...args)); }
export function planOf(...args) { return checkedProofsEModel("plan.planOf", args, raw_planOf(...args)); }
export function planProgress(...args) { return checkedProofsEModel("plan.planProgress", args, raw_planProgress(...args)); }
export function showChecklist(...args) { return checkedProofsEModel("plan.showChecklist", args, raw_showChecklist(...args)); }
export function planFromPage(...args) { return checkedProofsEModel("plan.planFromPage", args, raw_planFromPage(...args)); }
