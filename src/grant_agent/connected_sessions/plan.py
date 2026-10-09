"""An agent's own checklist, as data: Claude Code's TodoWrite and task tools, Codex's plan, Neyvia runs.

Each tool call that changes the plan carries ``data["plan"]``, a small operation read from the
call's own input (never from its text output):

  {"op": "replace", "items": [PlanItem], "source", "explanation"?}   TodoWrite, Codex update_plan
  {"op": "add", "item": PlanItem, "source"}                          Claude TaskCreate
  {"op": "update", "id", "status"?, "text"?, "active"?, "source"}    Claude TaskUpdate ("deleted" removes)

``latest_plan`` folds those operations in transcript order into the plan the chat shows:
  {"items": [{"id","text","active","status"}], "source", "explanation", "updatedAt", "throughSeq"}
``web/src/neyvia/next/nxPlanModel.js`` applies the same operations to items that arrive live.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

STATUSES = ("pending", "in_progress", "completed")
_STATUS = {"pending": "pending", "in_progress": "in_progress", "inprogress": "in_progress", "in-progress": "in_progress",
           "active": "in_progress", "running": "in_progress", "completed": "completed", "complete": "completed",
           "done": "completed"}
MAX_ITEMS = 100
TEXT_LIMIT = 300


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())[:TEXT_LIMIT]


def _status(value: Any) -> str:
    return _STATUS.get(str(value or "").strip().lower(), "pending")


def _entry(ident: Any, text: Any, status: Any, active: Any = None) -> dict[str, Any]:
    return {"id": None if ident in (None, "") else str(ident), "text": _text(text), "active": _text(active) or None,
            "status": _status(status)}


def plan_op(name: str, args: Any) -> dict[str, Any] | None:
    """The plan operation a tool call makes, from its input; None for any other call or an unreadable input."""
    data = args if isinstance(args, dict) else {}
    key = str(name or "").rsplit(".", 1)[-1].replace("-", "_").lower()
    if key == "neyvia_native_call" and data.get("tool_id") == "neyvia.plan.update":
        try:
            return plan_op("neyvia.plan.update", json.loads(data.get("arguments_json") or "{}"))
        except (TypeError, ValueError):
            return None
    if str(name).endswith("neyvia.native.call") and data.get("toolId") == "neyvia.plan.update":
        return plan_op("neyvia.plan.update", data.get("arguments"))
    if key in ("todowrite", "todo_write"):
        todos = data.get("todos")
        if not isinstance(todos, list):
            return None
        items = [_entry(index + 1, todo.get("content"), todo.get("status"), todo.get("activeForm"))
                 for index, todo in enumerate(todos[:MAX_ITEMS]) if isinstance(todo, dict)]
        return {"op": "replace", "items": items, "source": "claude-todos"}
    if key in {"update_plan", "plan_update"} or key.endswith("__plan_update") or str(name).endswith("neyvia.plan.update"):
        steps = data.get("plan")
        if steps is None and isinstance(data.get("plan_json"), str):
            try:
                steps = json.loads(data["plan_json"])
            except ValueError:
                return None
        if not isinstance(steps, list):
            return None
        return replace_steps(steps, data.get("explanation"), source="neyvia-intent" if key != "update_plan" or "plan_json" in data else "codex")
    if key == "taskcreate":
        if not _text(data.get("subject")):
            return None
        return {"op": "add", "item": _entry(None, data.get("subject"), "pending", data.get("activeForm")), "source": "claude-tasks"}
    if key == "taskupdate":
        ident = str(data.get("taskId") or "").strip()
        if not ident:
            return None
        op: dict[str, Any] = {"op": "update", "id": ident, "source": "claude-tasks"}
        if data.get("status") == "deleted":
            op["status"] = "deleted"
        elif data.get("status"):
            op["status"] = _status(data.get("status"))
        if _text(data.get("subject")):
            op["text"] = _text(data.get("subject"))
        if _text(data.get("activeForm")):
            op["active"] = _text(data.get("activeForm"))
        return op if len(op) > 3 else None
    return None


def replace_steps(steps: list[Any], explanation: Any = None, *, source: str) -> dict[str, Any]:
    """A Codex-style plan ({step, status} rows) as a replace operation."""
    items = [_entry(index + 1, step.get("step"), step.get("status")) for index, step in enumerate(steps[:MAX_ITEMS])
             if isinstance(step, dict) and _text(step.get("step"))]
    op: dict[str, Any] = {"op": "replace", "items": items, "source": source}
    if _text(explanation):
        op["explanation"] = _text(explanation)
    return op


def note_task_created(op: Any, structured: Any) -> None:
    """TaskCreate's result names the id Claude gave the task; keep it on the operation."""
    if not isinstance(op, dict) or op.get("op") != "add" or not isinstance(structured, dict):
        return
    task = structured.get("task") if isinstance(structured.get("task"), dict) else {}
    if task.get("id") not in (None, ""):
        op["item"] = {**op["item"], "id": str(task["id"])}


def _next_id(items: list[dict[str, Any]]) -> str:
    numbers = [int(item["id"]) for item in items if str(item.get("id") or "").isdigit()]
    return str(max(numbers, default=0) + 1)


def _apply_op(plan: dict[str, Any] | None, op: Any, *, at: str | None = None, seq: int | None = None) -> dict[str, Any] | None:
    """The plan after one operation. A replace with no items clears the plan."""
    if not isinstance(op, dict):
        return plan
    kind, source = op.get("op"), str(op.get("source") or "")
    items = [dict(item) for item in (plan or {}).get("items", [])]
    explanation = (plan or {}).get("explanation")
    if kind == "replace":
        items = [dict(item) for item in op.get("items") or [] if isinstance(item, dict)]
        explanation = op.get("explanation")
        if not items:
            return None
    elif kind == "add":
        if (plan or {}).get("source") != source:
            items, explanation = [], None
        entry = dict(op.get("item") or {})
        entry["id"] = entry.get("id") or _next_id(items)
        items = [item for item in items if item.get("id") != entry["id"]] + [entry]
    elif kind == "update":
        if plan is None:
            return None  # an update to a task created before what was read: nothing to show yet
        found = False
        for index, item in enumerate(items):
            if item.get("id") == op.get("id"):
                found = True
                if op.get("status") == "deleted":
                    items[index] = None  # type: ignore[call-overload]
                    continue
                for field in ("status", "text", "active"):
                    if op.get(field):
                        item[field] = op[field]
        items = [item for item in items if item is not None]
        if not found:
            return plan
        if not items:
            return None
    else:
        return plan
    return {"items": items[:MAX_ITEMS], "source": source or (plan or {}).get("source"), "explanation": explanation,
            "updatedAt": at or (plan or {}).get("updatedAt"), "throughSeq": seq if seq is not None else (plan or {}).get("throughSeq")}


def apply_op(plan: dict[str, Any] | None, op: Any, *, at: str | None = None, seq: int | None = None) -> dict[str, Any] | None:
    result = _apply_op(plan, op, at=at, seq=seq)
    from ..proofs_a_control import check_plan_transition
    check_plan_transition(plan, op, result, at, seq)
    return result


def _field(item: Any, name: str) -> Any:
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


def latest_plan(items: Iterable[Any], plan: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Fold the plan operations of ``items`` (Item objects or their dicts), oldest first, onto ``plan``."""
    ordered = sorted((item for item in items if isinstance(_field(item, "data"), dict) and _field(item, "data").get("plan")),
                     key=lambda item: _field(item, "seq") or 0)
    for item in ordered:
        plan = apply_op(plan, _field(item, "data")["plan"], at=_field(item, "at"), seq=_field(item, "seq"))
    return plan


def plan_summary(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    """{done, total, current}: the item being worked on (or the next one), for one-line views."""
    if not plan or not plan.get("items"):
        return None
    items = plan["items"]
    done = sum(1 for item in items if item.get("status") == "completed")
    current = next((item for item in items if item.get("status") == "in_progress"), None) \
        or next((item for item in items if item.get("status") == "pending"), None)
    return {"done": done, "total": len(items),
            "current": (current.get("active") or current.get("text")) if current and current.get("status") == "in_progress" else None,
            "next": current.get("text") if current and current.get("status") == "pending" else None}
