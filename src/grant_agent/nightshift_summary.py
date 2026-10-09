"""Morning card projection from persisted evidence and measured run receipts."""
from __future__ import annotations

from .nightshift_ledger import summary as ledger_summary
from .nightshift import folder_lock_key


def summary(service):
    tasks = service.tasks()
    by_id = {task["id"]: task for task in tasks}
    projected, links = [], []
    running = [task for task in tasks if task["status"] == "running"]
    locked_folders = {folder_lock_key(task["folder"]) for task in running}
    for task in tasks:
        row = dict(task)
        if task["status"] == "waiting":
            needs = [identity for identity in task["needs"] if identity not in by_id or by_id[identity]["status"] != "done"]
            if task["owner"] == "Paul":
                row["reason"] = "Waiting on Paul"
            elif needs:
                row["reason"] = "Waiting for prerequisites: " + ", ".join(needs)
            elif not task["armed"]:
                row["reason"] = "Not started"
            else:
                row["reason"] = service.resources.wait_reason(task, running)
                if not row["reason"] and folder_lock_key(task["folder"]) in locked_folders:
                    row["reason"] = "Working folder is held by another task"
        projected.append(row)
        if task.get("evidence"):
            links.append({"taskId": task["id"], **task["evidence"]})
    return {"tasks": projected,
            "counts": {state: sum(task["status"] == state for task in tasks) for state in ("waiting", "running", "done", "blocked", "needs_review")},
            **ledger_summary(service), "waitingOnPaul": [row for row in projected if row["owner"] == "Paul" and row["status"] != "done"],
            "blocked": [row for row in projected if row["status"] == "blocked"], "evidenceLinks": links,
            "needsReview": [row for row in projected if row["status"] == "needs_review"],
            "completionVerified": all((row.get("evidence") or {}).get("verified") is True for row in projected if row["status"] == "done"),
            "scope": "Verified saved evidence and transport-reported usage; quality and unreported token cost require review"}
