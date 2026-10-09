"""SQLite task board. Completion events, rather than a polling script, release work."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import uuid
import atexit
from contextlib import contextmanager
from pathlib import Path

from .ui_command_bus import bus_for, now, state_root
from .neyvia_workspace_tools import workspace_for


class NightShift:
    def __init__(self, root: Path, backend):
        self.root, self.backend = state_root(root), backend
        self.bus = bus_for(root)
        self.path = self.root / ".agent_control" / "nightshift.sqlite3"
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.workers = set()
        self.workers_lock = threading.Lock()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, body TEXT NOT NULL, status TEXT NOT NULL,
                    armed INTEGER NOT NULL DEFAULT 0, folder TEXT NOT NULL, run_id TEXT,
                    evidence TEXT, reason TEXT, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS locks (folder TEXT PRIMARY KEY, task TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (run_id TEXT PRIMARY KEY, task TEXT NOT NULL, usage TEXT);
            """)
        self.broker = workspace_for(root, backend).broker()
        from .nightshift_resources import Resources
        from . import nightshift_ledger
        nightshift_ledger.initialize(self)
        self.resources = Resources(self)
        from .connected_sessions.live_limits import service_for
        self.plan_limits = service_for(self.broker.root)
        self.plan_limits.listeners.append(self.on_limits)
        self.broker.add_event_listener(self.on_event)
        atexit.register(self.close)
        # An interrupted service is never blindly resent into the same repository.
        for task in self.tasks():
            if task["status"] == "done" and (task.get("evidence") or {}).get("type") == "run" and not (task.get("evidence") or {}).get("verified"):
                self.needs_review(task["id"], "Saved run completion has no verified task-matching evidence")
            if task["status"] == "running":
                nightshift_ledger.finish(self, task)
                self.block(task["id"], "Service restarted; inspect the saved harness run before retrying")
        self.resources.refresh_timers()
        self.spawn(self.dispatch, name="nightshift-recovery")

    def spawn(self, target, args=(), name="nightshift"):
        def work():
            try:
                if not self.closed.is_set():
                    target(*args)
            finally:
                with self.workers_lock:
                    self.workers.discard(threading.current_thread())
        with self.workers_lock:
            if self.closed.is_set():
                return
            thread = threading.Thread(target=work, name=name, daemon=True)
            self.workers.add(thread)
            thread.start()

    def close(self):
        self.closed.set()
        if self.on_limits in self.plan_limits.listeners:
            self.plan_limits.listeners.remove(self.on_limits)
        self.broker.remove_event_listener(self.on_event)
        with self.lock:
            for identity in list(self.resources.timers):
                self.resources.release(identity)
        with self.workers_lock:
            workers = list(self.workers)
        for thread in workers:
            if thread is not threading.current_thread():
                thread.join(2)

    def on_limits(self):
        """Fresh quotas release waiting tasks; crossed quotas stop owned attempts."""
        with self.lock:
            if self.closed.is_set():
                return
            for task in self.tasks():
                if task["status"] == "running" and task.get("runId"):
                    self.resources.watch(task)
            self.dispatch()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def tasks(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM tasks ORDER BY rowid").fetchall()
        return [{**json.loads(row["body"]), "status": row["status"], "armed": bool(row["armed"]),
                 "runId": row["run_id"], "evidence": json.loads(row["evidence"]) if row["evidence"] else None,
                 "reason": row["reason"], "updatedAt": row["updated"]} for row in rows]

    def get(self, identity):
        return next((task for task in self.tasks() if task["id"] == identity), None)

    def emit(self, identity):
        task = self.get(identity)
        self.bus.emit("nightshift.task.updated", task)
        return task

    def prepare(self, args):
        identity = str(args.get("id") or uuid.uuid4().hex)
        if not re.fullmatch(r"[\w:.-]{1,160}", identity):
            raise ValueError("Use a task ID of 1–160 letters, numbers, dots, colons or hyphens")
        owner = str(args.get("owner") or "Codex")
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("A stored prompt is required")
        folder = workspace_for(self.root).safe_path(args.get("folder") or self.root)
        if not folder.is_dir():
            raise ValueError("Task folder does not exist")
        needs = args.get("needs") or []
        if not isinstance(args.get("requiresGpu", False), bool):
            raise ValueError("requiresGpu must be a boolean")
        if not isinstance(needs, list) or not all(isinstance(item, str) for item in needs) or identity in needs:
            raise ValueError("needs must contain other task IDs")
        task = {"id": identity, "owner": owner, "title": str(args.get("title") or prompt[:100]),
                "prompt": prompt, "folder": str(folder), "harness": args.get("harness") or
                {"Codex": "codex", "Claude": "claude-code", "Paul": None}.get(owner),
                "model": args.get("model"), "permissionMode": args.get("permissionMode") or "read-only",
                "effort": args.get("effort"), "needs": needs, "requiresGpu": bool(args.get("requiresGpu", False)),
                "completionEvidence": args.get("completionEvidence")}
        if args.get("transport") is not None:
            from .connected_sessions.broker import ConnectedBroker
            task["transport"] = ConnectedBroker._turn_options(args).transport
        if args.get("routingProfile") is not None:
            from .neyvia_runtime import PROFILE_NAMES
            if args["routingProfile"] not in PROFILE_NAMES:
                raise ValueError("Unknown routing profile")
            task["routingProfile"] = args["routingProfile"]
        from .nightshift_resources import positive
        if not isinstance(args.get("limits") or {}, dict):
            raise ValueError("limits must be an object")
        task["limits"] = {key: positive(value, key) for key, value in (args.get("limits") or {}).items()}
        if set(task["limits"]) - {"maxTaskSeconds", "maxTaskTokens"}:
            raise ValueError("Unknown task limit")
        if args.get("missionId"):
            task["missionId"] = str(args["missionId"])
        return task

    def create(self, args):
        task = self.prepare(args)
        with self.lock, self.connect() as db:
            if db.execute("SELECT 1 FROM tasks WHERE id=?", (task["id"],)).fetchone():
                raise ValueError("Task ID already exists")
            db.execute("INSERT INTO tasks(id,body,status,folder,updated) VALUES(?,?,?,?,?)",
                       (task["id"], json.dumps(task), "waiting", os.path.normcase(task["folder"]), now()))
        return self.emit(task["id"])

    def edit(self, identity, patch, expected_updated_at):
        """Replace a dormant task under CAS, preserving attempts and completion evidence."""
        fields = {"title", "prompt", "owner", "folder", "harness", "model", "effort", "permissionMode", "transport",
                  "needs", "requiresGpu", "limits", "completionEvidence", "routingProfile"}
        if not isinstance(patch, dict) or not patch or set(patch) - fields:
            raise ValueError("Supply a nonempty patch of editable task fields")
        if not isinstance(expected_updated_at, str) or not expected_updated_at:
            raise ValueError("Read nightshift.tasks and supply the task's expectedUpdatedAt")
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT * FROM tasks").fetchall()
            row = next((item for item in rows if item["id"] == identity), None)
            if row is None:
                raise ValueError("Unknown task")
            if row["updated"] != expected_updated_at:
                raise ValueError("Task changed. Read nightshift.tasks and retry with its current updatedAt")
            if row["status"] not in {"waiting", "blocked"} or row["run_id"] or row["evidence"]:
                raise ValueError("Only dormant tasks without a harness attempt or completed evidence can be edited")
            if db.execute("SELECT 1 FROM attempts WHERE task=?", (identity,)).fetchone():
                raise ValueError("A task with a recorded attempt cannot be edited; create a new task")
            task = self.prepare({**json.loads(row["body"]), **patch, "id": identity})
            graph = {item["id"]: json.loads(item["body"]) for item in rows}
            graph[identity] = task
            self.validate_graph([identity], graph)
            db.execute("UPDATE tasks SET body=?,folder=?,armed=0,updated=? WHERE id=?",
                       (json.dumps(task), os.path.normcase(task["folder"]), now(), identity))
        return self.emit(identity)

    def tick(self, identity, evidence):
        with self.lock:
            task = self.get(identity)
            if not task:
                raise ValueError("Unknown task")
            if task["status"] == "done":
                if self.check_evidence(task, evidence) != task["evidence"]:
                    raise ValueError("Completed task evidence is immutable")
                return task
            if any(not self.get(need) or self.get(need)["status"] != "done" for need in task["needs"]):
                raise ValueError("Prerequisites are not done")
            if task["status"] == "running" and (not task.get("runId") or self.broker.get_run(task["runId"])["state"] != "completed"):
                raise ValueError("Wait for the running harness to complete before ticking")
            checked = self.check_evidence(task, evidence)
            with self.connect() as db:
                db.execute("UPDATE tasks SET status='done',evidence=?,reason=NULL,updated=? WHERE id=?",
                           (json.dumps(checked), now(), identity))
                db.execute("DELETE FROM locks WHERE task=?", (identity,))
            result = self.emit(identity)
            self.resources.release(identity)
            self.dispatch()
            return result

    def check_evidence(self, task, evidence):
        from .nightshift_evidence import check
        return check(self, task, evidence)

    def needs_review(self, identity, reason):
        """Release the attempt's lock, but never release its dependent tasks."""
        with self.connect() as db:
            db.execute("UPDATE tasks SET status='needs_review',armed=0,evidence=NULL,reason=?,updated=? WHERE id=?",
                       (reason, now(), identity))
            db.execute("DELETE FROM locks WHERE task=?", (identity,))
        self.resources.release(identity)
        return self.emit(identity)

    def block(self, identity, reason):
        with self.lock:
            return self._block(identity, reason)

    def _block(self, identity, reason):
        task = self.get(identity)
        if not task:
            raise ValueError("Unknown task")
        if task["status"] == "done":
            raise ValueError("Completed task evidence is immutable")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("A blocked reason is required")
        if task["status"] == "running" and task.get("runId"):
            try:
                run = self.broker.get_run(task["runId"])
            except Exception as exc:
                if getattr(exc, "code", None) != "run_not_found":
                    raise
                run = {"state": "interrupted"}
            if run["state"] not in {"completed", "failed", "interrupted", "cancelled"}:
                raise ValueError("Stop the active harness before releasing its folder lock")
        with self.connect() as db:
            db.execute("UPDATE tasks SET status='blocked',armed=0,reason=?,updated=? WHERE id=?", (reason, now(), identity))
            db.execute("DELETE FROM locks WHERE task=?", (identity,))
        self.resources.release(identity)
        return self.emit(identity)

    def stop(self, identity, reason="Stopped by owner"):
        with self.lock:
            task = self.get(identity)
            if not task:
                raise ValueError("Unknown task")
            if task["status"] == "done":
                return task
            with self.connect() as db:
                db.execute("UPDATE tasks SET armed=0,reason=?,updated=? WHERE id=?", (reason, now(), identity))
            self.emit(identity)
            if task["status"] == "running" and task.get("runId"):
                try:
                    self.broker.stop(task["runId"])
                except Exception as exc:
                    # A launch still being claimed observes the disarm in on_event.
                    if getattr(exc, "code", None) != "run_not_found":
                        raise
            elif task["status"] != "done":
                self.block(identity, reason)
            return self.get(identity)

    def start(self, identities, *, validate_only=False):
        if not isinstance(identities, list) or not identities:
            raise ValueError("Select task IDs to start; import never starts tasks implicitly")
        with self.lock:
            selected = [self.get(identity) for identity in identities]
            if any(task is None for task in selected):
                raise ValueError("Unknown task")
            self.validate_graph(identities)
            for task in selected:
                if task["owner"] == "Paul":
                    continue
                if task["harness"] not in {"codex", "claude-code", "neyvia", "opencode"}:
                    raise ValueError("Unsupported harness; no provider substitution")
                workspace_for(self.root).safe_path(task["folder"])
                if not Path(task["folder"]).is_dir():
                    raise ValueError("Task folder does not exist")
                from .neyvia_workspace_tools import harness_mode
                harness_mode(task["harness"], task["permissionMode"])
            if validate_only:
                return {"tasks": selected}
            for task in selected:
                if task["owner"] == "Paul":
                    continue
                with self.connect() as db:
                    db.execute("UPDATE tasks SET armed=1, status=CASE WHEN status='blocked' THEN 'waiting' ELSE status END WHERE id=?",
                               (task["id"],))
            self.dispatch()
        return {"tasks": self.tasks()}

    def validate_graph(self, identities, tasks=None):
        tasks = tasks if tasks is not None else {task["id"]: task for task in self.tasks()}
        visited = set()
        def visit(identity, path):
            if identity not in tasks:
                raise ValueError("Missing prerequisite: " + identity)
            if identity in path:
                raise ValueError("Cyclic prerequisites")
            if identity in visited:
                return
            for need in tasks[identity]["needs"]:
                visit(need, path | {identity})
            visited.add(identity)
        for identity in identities:
            visit(identity, set())

    def dispatch(self):
        with self.lock:
            if self.closed.is_set():
                return
            tasks = self.tasks()
            done = {task["id"] for task in tasks if task["status"] == "done"}
            running = [task for task in tasks if task["status"] == "running"]
            for task in tasks:
                if task["status"] != "waiting" or not task["armed"] or task["owner"] == "Paul" or not set(task["needs"]) <= done:
                    continue
                reason = self.resources.wait_reason(task, running)
                if task.get("missionId"):
                    from .neyvia_missions import admission, remaining_limits
                    reason = admission(self, task["missionId"]) or reason
                if reason:
                    if task.get("reason") != reason:
                        with self.connect() as db:
                            db.execute("UPDATE tasks SET reason=? WHERE id=?", (reason, task["id"]))
                        self.emit(task["id"])
                    continue
                folder = folder_lock_key(task["folder"])
                if task.get("missionId"):
                    task["limits"] = remaining_limits(self, task)
                effective_limits = self.resources.remaining_limits(task)
                from .nightshift_evidence import baseline
                try:
                    task["evidenceBefore"] = baseline(self, task)
                except (ValueError, OSError) as exc:
                    self.needs_review(task["id"], "Completion contract cannot be observed: " + str(exc))
                    continue
                # Persist an attempt ID before contacting the harness. A crash is never resent.
                run_id = "night-" + uuid.uuid4().hex
                with self.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    if db.execute("SELECT 1 FROM locks WHERE folder=?", (folder,)).fetchone():
                        continue
                    db.execute("INSERT INTO locks VALUES(?,?)", (folder, task["id"]))
                    db.execute("UPDATE tasks SET body=?,status='running',run_id=?,reason=NULL,updated=? WHERE id=?",
                               (json.dumps({k: v for k, v in task.items() if k not in {"status", "armed", "runId", "evidence", "reason", "updatedAt"}}),
                                run_id, now(), task["id"]))
                    db.execute("INSERT INTO attempts(run_id,task) VALUES(?,?)", (run_id, task["id"]))
                task = self.get(task["id"])
                from .nightshift_ledger import record
                record(self, task, effective_limits)
                running.append(task)
                self.emit(task["id"])
                self.spawn(self.launch, (task,), "nightshift-" + task["id"])

    def launch(self, task):
        try:
            if not self.get(task["id"])["armed"]:
                from .nightshift_ledger import finish
                finish(self, task)
                self.block(task["id"], self.get(task["id"])["reason"])
                self.dispatch()
                return
            from .neyvia_workspace_tools import harness_mode
            run = self.broker.new(task["harness"], task["folder"], task["prompt"], task["runId"],
                                  {"model": task["model"], "effort": task.get("effort"),
                                   "transport": task.get("transport"),
                                   "permissionMode": harness_mode(task["harness"], task["permissionMode"])})
            with self.connect() as db:
                db.execute("UPDATE tasks SET run_id=? WHERE id=?", (run["runId"], task["id"]))
                db.execute("UPDATE attempts SET run_id=? WHERE run_id=?", (run["runId"], task["runId"]))
            from .nightshift_ledger import rename_run
            rename_run(self, task["runId"], run["runId"])
            self.emit(task["id"])
            self.resources.watch(self.get(task["id"]))
            # A short task may finish before new() returns its session ID.
            self.finish_run(self.broker.get_run(run["runId"]))
        except Exception as exc:
            from .nightshift_ledger import finish
            finish(self, self.get(task["id"]))
            self.block(task["id"], str(exc))
            self.dispatch()

    def on_event(self, event):
        if self.closed.is_set():
            return
        if event.get("type") == "usage.updated":
            with self.connect() as db:
                db.execute("UPDATE attempts SET usage=? WHERE run_id=?", (json.dumps(event.get("usage")), event.get("runId")))
        if event.get("type") == "usage.updated" or (event.get("type") == "run.state" and event.get("state") in {"running", "queued"}):
            task = next((task for task in self.tasks() if task["status"] == "running" and task["runId"] == event.get("runId")), None)
            if task:
                action = (lambda: self.resources.watch(self.get(task["id"]))) if task["armed"] else (lambda: self.stop(task["id"], task["reason"]))
                self.spawn(action, name="nightshift-resources")
        if event.get("type") == "run.state" and event.get("state") in {"completed", "failed", "interrupted", "cancelled"}:
            self.spawn(self.finish_run, (event,), "nightshift-completion")

    def finish_run(self, run):
        if run.get("state") not in {"completed", "failed", "interrupted", "cancelled"}:
            return
        with self.lock:
            task = next((task for task in self.tasks() if task["status"] == "running" and task["runId"] == run.get("runId")), None)
            if not task:
                return
            from .nightshift_ledger import finish
            finish(self, task)
            self.resources.release(task["id"])
            if not task["armed"]:
                self.block(task["id"], task["reason"] or "Stopped by owner")
            elif run["state"] == "completed":
                try:
                    self.tick(task["id"], task["completionEvidence"] or {"type": "run", "runId": run["runId"]})
                except Exception as exc:
                    self.needs_review(task["id"], "Completion evidence rejected: " + str(exc))
            elif run["state"] in {"failed", "interrupted", "cancelled"}:
                self.block(task["id"], str(run.get("error") or run["state"]))
            self.dispatch()

    def request(self, action, body, method):
        if action == "resources":
            return self.resources.policy() if method == "GET" else self.resources.update(body)
        if method == "GET" and action == "tasks":
            return {"tasks": self.tasks()}
        if method == "GET" and action == "task":
            task = self.get(body["id"])
            if task is None:
                raise ValueError("Unknown task")
            return task
        if method == "GET" and action == "summary":
            from .nightshift_summary import summary
            return summary(self)
        if method != "POST":
            raise ValueError("Unknown Night Shift route")
        if action == "create":
            return self.create(body)
        if action in {"edit", "reparent"}:
            patch = {"needs": body["needs"]} if action == "reparent" else body["patch"]
            return self.edit(body["id"], patch, body.get("expectedUpdatedAt"))
        if action == "begin":
            from .nightshift_ledger import begin
            result = begin(self)
            self.dispatch()
            return result
        if action == "tick":
            return self.tick(body["id"], body["evidence"])
        if action == "start":
            return self.start(body["ids"])
        if action == "block":
            return self.block(body["id"], body["reason"])
        if action == "stop":
            return self.stop(body["id"])
        if action == "import":
            from .nightshift_import import import_board
            return import_board(self, body)
        raise ValueError("Unknown Night Shift route")


_services = {}
_lock = threading.Lock()


def folder_lock_key(folder):
    path = Path(folder).resolve()
    # Nested working directories in one checkout still share the same write lock.
    repository = next((parent for parent in (path, *path.parents) if (parent / ".git").exists()), path)
    return os.path.normcase(str(repository))


def nightshift_for(root, backend):
    key = str(state_root(root))
    with _lock:
        if key not in _services:
            _services[key] = NightShift(root, backend)
        return _services[key]


def refresh_settings(root):
    """Apply changed limits to an already-live scheduler without creating one."""
    with _lock:
        service = _services.get(str(state_root(root)))
    if service is not None:
        with service.lock:
            for task in service.tasks():
                if task["status"] == "running" and task.get("runId"):
                    service.resources.watch(task)
            service.dispatch()
