"""Bounded connected-session plan-history outcomes."""
from __future__ import annotations

import json
import time
from pathlib import Path


CONTRACTS = (
    "sessions.plan-history.order",
    "sessions.plan-history.source-clear",
    "sessions.plan-history.conversation-scope",
)


def _append(path: Path, record: dict) -> None:
    with path.open("ab") as handle:
        handle.write(json.dumps(record, separators=(",", ":")).encode("utf-8") + b"\n")


def _call(path: Path, session: str, identity: str, name: str, arguments: dict, at: str) -> None:
    _append(path, {
        "type": "assistant", "sessionId": session, "timestamp": at,
        "message": {"content": [{"type": "tool_use", "id": identity, "name": name, "input": arguments}]},
    })


def _result(path: Path, session: str, identity: str, *, error: bool = False,
            structured: dict | None = None, at: str = "2026-10-06T00:00:01Z") -> None:
    _append(path, {
        "type": "user", "sessionId": session, "timestamp": at,
        "message": {"content": [{"type": "tool_result", "tool_use_id": identity, "is_error": error}]},
        "toolUseResult": structured or {},
    })


def _items(path: Path):
    from .connected_sessions.claude_plan_history import read_plan_history

    return read_plan_history(path, path.stat().st_size, 12)


def _order_case(root: Path) -> dict:
    from .connected_sessions.plan import latest_plan

    path = root / "ordered.jsonl"
    _call(path, "conversation-order", "create-1", "TaskCreate",
          {"subject": "Inspect the manual", "activeForm": "Inspecting the manual"}, "2026-10-06T00:00:00Z")
    _result(path, "conversation-order", "create-1", structured={"task": {"id": "task-41"}})
    _call(path, "conversation-order", "create-2", "TaskCreate",
          {"subject": "Review the route", "activeForm": "Reviewing the route"}, "2026-10-06T00:00:02Z")
    _result(path, "conversation-order", "create-2", structured={"task": {"id": "task-42"}})
    _call(path, "conversation-order", "complete-1", "TaskUpdate",
          {"taskId": "task-41", "status": "completed"}, "2026-10-06T00:00:03Z")
    _result(path, "conversation-order", "complete-1")
    _call(path, "conversation-order", "start-2", "TaskUpdate",
          {"taskId": "task-42", "status": "in_progress", "activeForm": "Reviewing the route"}, "2026-10-06T00:00:04Z")
    _result(path, "conversation-order", "start-2")
    _call(path, "conversation-order", "refused-2", "TaskUpdate",
          {"taskId": "task-42", "status": "completed"}, "2026-10-06T00:00:05Z")
    _result(path, "conversation-order", "refused-2", error=True)

    history = _items(path)
    plan = latest_plan(history)
    expected = [
        {"id": "task-41", "text": "Inspect the manual", "active": "Inspecting the manual", "status": "completed"},
        {"id": "task-42", "text": "Review the route", "active": "Reviewing the route", "status": "in_progress"},
    ]
    if plan is None or plan["items"] != expected or plan["source"] != "claude-tasks":
        raise ValueError("ordered accepted plan operations or failed-result refusal differed")
    if plan["updatedAt"] != "2026-10-06T00:00:04Z" or plan["throughSeq"] != history[-2].seq:
        raise ValueError("latest accepted plan lost its transcript timestamp or sequence")
    return {"acceptedOrder": [item["id"] for item in plan["items"]], "failedUpdateIgnored": True,
            "completedAndActive": [item["status"] for item in plan["items"]]}


def _source_and_clear_case(root: Path) -> dict:
    from .connected_sessions.plan import latest_plan

    path = root / "source-switch.jsonl"
    _call(path, "conversation-source", "old-create", "TaskCreate", {"subject": "Old source"}, "2026-10-06T00:01:00Z")
    _result(path, "conversation-source", "old-create", structured={"task": {"id": "shared-id"}})
    _call(path, "conversation-source", "replace", "TodoWrite", {"todos": [
        {"content": "Replacement one", "status": "pending"},
        {"content": "Replacement two", "status": "in_progress"},
    ]}, "2026-10-06T00:01:01Z")
    _result(path, "conversation-source", "replace")
    _call(path, "conversation-source", "new-source", "TaskCreate", {"subject": "New source"}, "2026-10-06T00:01:02Z")
    _result(path, "conversation-source", "new-source", structured={"task": {"id": "shared-id"}})
    plan = latest_plan(_items(path))
    if plan is None or plan["source"] != "claude-tasks" or plan["items"] != [
        {"id": "shared-id", "text": "New source", "active": None, "status": "pending"},
    ]:
        raise ValueError("switching plan source retained rows from the prior checklist")

    clear_path = root / "terminal-clear.jsonl"
    _call(clear_path, "conversation-clear", "todo", "TodoWrite", {"todos": [
        {"content": "Finish the task", "status": "completed"},
    ]}, "2026-10-06T00:02:00Z")
    _result(clear_path, "conversation-clear", "todo")
    _call(clear_path, "conversation-clear", "delete", "TaskUpdate",
          {"taskId": "1", "status": "deleted"}, "2026-10-06T00:02:01Z")
    _result(clear_path, "conversation-clear", "delete")
    if latest_plan(_items(clear_path)) is not None:
        raise ValueError("deleting the last checklist item did not clear the plan")

    empty_path = root / "empty-replace.jsonl"
    _call(empty_path, "conversation-empty", "todo", "TodoWrite", {"todos": [
        {"content": "Temporary", "status": "pending"},
    ]}, "2026-10-06T00:03:00Z")
    _result(empty_path, "conversation-empty", "todo")
    _call(empty_path, "conversation-empty", "clear", "TodoWrite", {"todos": []}, "2026-10-06T00:03:01Z")
    _result(empty_path, "conversation-empty", "clear")
    if latest_plan(_items(empty_path)) is not None:
        raise ValueError("empty replacement did not clear the plan")
    return {"sourceSwitchRows": len(plan["items"]), "sourceSwitchOldRowsDiscarded": True,
            "deletedLastItemCleared": True, "emptyReplacementCleared": True}


def _conversation_scope_case(root: Path) -> dict:
    from .connected_sessions.plan import latest_plan

    first = root / "conversation-one.jsonl"
    second = root / "conversation-two.jsonl"
    _call(first, "conversation-one", "same-tool-id", "TaskCreate", {"subject": "Owned by first"}, "2026-10-06T00:04:00Z")
    _call(second, "conversation-two", "other-create", "TaskCreate", {"subject": "Owned by second"}, "2026-10-06T00:04:00Z")
    _result(second, "conversation-two", "same-tool-id", structured={"task": {"id": "wrong-conversation"}})
    _append(second, {
        "type": "assistant", "sessionId": "conversation-two", "isSidechain": True,
        "timestamp": "2026-10-06T00:04:02Z",
        "message": {"content": [{"type": "tool_use", "id": "sidechain", "name": "TaskCreate",
                                    "input": {"subject": "Private subtask"}}]},
    })
    first_plan = latest_plan(_items(first))
    second_items = _items(second)
    second_plan = latest_plan(second_items)
    if first_plan is None or first_plan["items"] != [
        {"id": "1", "text": "Owned by first", "active": None, "status": "pending"},
    ]:
        raise ValueError("result from another conversation altered the first conversation plan")
    if second_plan is None or second_plan["items"] != [
        {"id": "1", "text": "Owned by second", "active": None, "status": "pending"},
    ] or any(item.id == "sidechain" for item in second_items):
        raise ValueError("conversation-local or sidechain plan filtering differed")
    return {"separateConversationPlans": 2, "foreignResultIgnored": True, "sidechainExcluded": True}


def self_check(root: Path) -> dict:
    from .contract_gate import wants
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    cases = []
    started = time.perf_counter()
    for identity, contracts, action in (
        ("ordered-accepted-results", (CONTRACTS[0],), _order_case),
        ("source-terminal-and-clear", (CONTRACTS[1],), _source_and_clear_case),
        ("conversation-scope", (CONTRACTS[2],), _conversation_scope_case),
    ):
        if not wants(contracts):continue
        target = root / identity
        target.mkdir(parents=True, exist_ok=True)
        try:
            observed = action(target)
            cases.append({"id": identity, "contracts": list(contracts), "ok": True, "observed": observed})
        except Exception as error:
            cases.append({"id": identity, "contracts": list(contracts), "ok": False,
                          "error": f"{type(error).__name__}: {error}"})
    report = {"ok": bool(cases) and all(case["ok"] for case in cases), "cases": cases,
              "contracts": sorted({contract for case in cases if case["ok"] for contract in case["contracts"]}),
              "durationMs": round((time.perf_counter() - started) * 1000)}
    (root / "plan-history.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
