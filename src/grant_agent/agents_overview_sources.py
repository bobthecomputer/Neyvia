"""Read orchestration owners into the shared graph without activating workers."""
from __future__ import annotations

import json
import sqlite3

from .agents_overview import node


def session_subagents(items, parent):
    """Settle cached transcript activity against the current persisted parent."""
    from .claude_code_activity import settle_subagents
    from .connected_sessions.dashboard import subagents
    return subagents(settle_subagents(items, parent) if parent.get("app") == "claude-code" else items)


def orchestration(service, rows, edges, source):
    def put(identity, kind, title, raw, parent=None, app="neyvia", session=None, run=None):
        # A lane/task and its connected session are one agent, with the richer
        # session activity/actions retained under the orchestration parent.
        key = "session:" + session if session and "session:" + session in rows else identity
        previous = rows.get(key)
        row = node(key, kind, title, raw, parent=parent, app=app, session=session, run=run)
        if previous:
            row = {**row, **previous, "parentId": parent, "source": kind,
                   "worktree": raw.get("worktree") or previous.get("worktree"),
                   "branch": raw.get("branch") or previous.get("branch")}
        rows[key] = row
        return row

    def tasks():
        path = service.bus.root / ".agent_control" / "nightshift.sqlite3"
        if not path.exists():
            return [], []
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2) as db:
            db.row_factory = sqlite3.Row
            saved = [{**json.loads(row["body"]), "id": row["id"], "status": row["status"],
                      "runId": row["run_id"], "reason": row["reason"], "updatedAt": row["updated"]}
                     for row in db.execute("SELECT * FROM tasks")]
            have_missions = db.execute("SELECT name FROM sqlite_master WHERE name='missions'").fetchone()
            missions = [{**json.loads(row["body"]), "id": row["id"], "status": row["status"], "updatedAt": row["updated"]}
                        for row in db.execute("SELECT * FROM missions")] if have_missions else []
        return saved, missions

    saved = source("nightshift", tasks)
    tasks, missions = saved if saved else ([], [])
    for mission in missions:
        root = put("mission:" + mission["id"], "missions", mission.get("goal"), mission)
        root["isAgent"] = False
        root["openTarget"] = {"kind": "mission", "target": mission["id"]}
        if mission.get("status") == "running":
            root["actions"]["stop"] = {"kind": "mission", "id": mission["id"]}
    source("missions", lambda: missions)
    task_ids = {}
    for task in tasks:
        run = service.broker().get_run(task["runId"]) if task.get("runId") else {}
        parent = "mission:" + task["missionId"] if task.get("missionId") else None
        row = put("nightshift:" + task["id"], "missions" if parent else "nightshift", task.get("title"),
                  {**task, "usage": run.get("usage"), "startedAt": run.get("startedAt")},
                  parent=parent, app=task.get("harness"), session=run.get("sessionId"), run=task.get("runId"))
        if task.get("paul") or str(task.get("owner") or "").casefold() == "paul":
            row["app"], row["isAgent"] = "you", False
        if task.get("status") == "waiting" and not row.get("isAgent") is False:
            row["state"] = "unknown"  # a dormant queue item is not waiting for the person
        row["openTarget"] = {"kind": "mission", "target": "nightshift"}
        if task.get("status") == "running":
            row["actions"]["stop"] = {"kind": "nightshift", "id": task["id"]}
        task_ids[task["id"]] = row["id"]
    for task in tasks:
        for need in task.get("needs") or []:
            if need in task_ids:
                edges.append({"from": task_ids[task["id"]], "to": task_ids[need], "kind": "waiting on"})

    from .neyvia_conductor import request
    for job in source("conductor", lambda: request(service.bus.root, "list", {"limit": 100})["jobs"]):
        tree = job.get("conductor") or (job.get("result") or {}).get("conductor") or {}
        intent = (job.get("request") or {}).get("intent") or {}
        root = put("conductor:" + job["id"], "conductor", intent.get("goal"),
                   {**job, "state": tree.get("phase") or job.get("status"), "folder": intent.get("folder")})
        root["isAgent"] = False
        root["openTarget"] = {"kind": "mission", "target": "conductor:" + job["id"]}
        root["actions"]["stop"] = {"kind": "conductor", "id": job["id"]} if job.get("status") == "running" else None
        keys = {}
        for task in tree.get("tasks") or []:
            run = task.get("run") or {}
            row = put(root["id"] + ":" + task["id"], "conductor", task.get("title"),
                      {**task, "folder": intent.get("folder")}, parent=root["id"], app=task.get("harness"),
                      session=task.get("sessionId") or run.get("sessionId"), run=task.get("runId") or run.get("runId"))
            row["openTarget"] = root["openTarget"]
            keys[task["id"]] = row["id"]
        for task in tree.get("tasks") or []:
            for need in task.get("needs") or []:
                if need in keys:
                    edges.append({"from": keys[task["id"]], "to": keys[need], "kind": "waiting on"})

    def parallel():
        # Public owner API; never read the parallel files or create worktrees.
        return service.call("parallel.state", {}).get("runs", [])

    for run in source("parallel", parallel):
        main = run.get("main") or {}
        root = put("parallel:" + run["id"], "parallel", run.get("goal"),
                   {**run, **main, "state": main.get("liveState") or run.get("state"), "repo": run.get("repo")},
                   app=main.get("agent"), session=main.get("session"), run=main.get("runId"))
        root["openTarget"] = {"kind": "parallel", "target": run["id"]}
        if run.get("state") not in {"finished", "settled", "stopped", "failed"}:
            root["actions"]["stop"] = {"kind": "parallel", "id": run["id"]}
        for lane in run.get("tracks") or []:
            child = put("parallel:" + run["id"] + ":" + lane["id"], "parallel", lane.get("title"),
                        {**lane, "state": lane.get("liveState") or lane.get("state"), "repo": run.get("repo")},
                        parent=root["id"], app=lane.get("agent"), session=lane.get("session"), run=lane.get("runId"))
            child["openTarget"] = root["openTarget"]
            for question in lane.get("questions") or []:
                edges.append({"from": child["id"] if not question.get("answer") else root["id"],
                              "to": root["id"] if not question.get("answer") else child["id"],
                              "kind": "asked" if not question.get("answer") else "answered", "questionId": question["id"]})
                if not question.get("answer"):
                    child["state"], child["activity"] = "asking", question.get("question")
