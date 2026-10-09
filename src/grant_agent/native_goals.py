"""Durable goals, milestones, heartbeats, and due-work queries for Neyvia Native."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


GOAL_SCHEMA = "neyvia.native-goal/v1"
HEARTBEAT_SCHEMA = "neyvia.native-goal-heartbeat/v1"
_VALID_STATUS = {"active", "paused", "blocked", "completed", "cancelled"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat().replace("+00:00", "Z")


def _safe_id(value: object, fallback: str = "goal") -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip(".-")
    return (clean or fallback)[:120]


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class NativeGoalStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.path = self.root / ".agent_control" / "neyvia_agent" / "goals.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS native_goals (
                    goal_id TEXT PRIMARY KEY,
                    objective TEXT NOT NULL,
                    success_checks_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    next_action TEXT NOT NULL,
                    schedule_seconds INTEGER,
                    next_due_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_heartbeat_at TEXT,
                    last_run_id TEXT,
                    completion_receipt TEXT,
                    goal_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS native_goal_milestones (
                    milestone_id TEXT PRIMARY KEY,
                    goal_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    status TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(goal_id) REFERENCES native_goals(goal_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS native_goal_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(goal_id) REFERENCES native_goals(goal_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_native_goals_due
                    ON native_goals(status, next_due_at, priority);
                """
            )

    def _append_event(self, connection: sqlite3.Connection, goal_id: str, event_type: str, payload: dict[str, Any]) -> None:
        connection.execute(
            "INSERT INTO native_goal_events(goal_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (goal_id, event_type, json.dumps(payload, ensure_ascii=False), _iso()),
        )
        from .proofs_d_native import check_goal_event
        check_goal_event(connection, goal_id, event_type, payload)

    def create(
        self,
        objective: str,
        *,
        goal_id: str = "",
        success_checks: list[str] | None = None,
        priority: int = 50,
        next_action: str = "Inspect current state and compile the next bounded run.",
        schedule_seconds: int | None = None,
        milestones: list[str] | None = None,
    ) -> dict[str, Any]:
        clean_objective = str(objective or "").strip()
        if not clean_objective:
            raise ValueError("A goal objective is required.")
        identifier = _safe_id(goal_id or f"goal-{uuid.uuid4().hex[:12]}")
        checks = [str(item).strip() for item in (success_checks or []) if str(item).strip()]
        schedule = None if schedule_seconds is None else max(60, int(schedule_seconds))
        now = _now()
        next_due = _iso(now + timedelta(seconds=schedule)) if schedule else None
        payload = {
            "goalId": identifier,
            "objective": clean_objective,
            "successChecks": checks,
            "priority": max(0, min(100, int(priority))),
            "scheduleSeconds": schedule,
        }
        goal_hash = _hash(payload)
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO native_goals(
                    goal_id, objective, success_checks_json, status, priority,
                    next_action, schedule_seconds, next_due_at, created_at,
                    updated_at, goal_hash
                ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    clean_objective,
                    json.dumps(checks, ensure_ascii=False),
                    payload["priority"],
                    str(next_action or "")[:4000],
                    schedule,
                    next_due,
                    _iso(now),
                    _iso(now),
                    goal_hash,
                ),
            )
            for index, label in enumerate(milestones or []):
                milestone_id = f"{identifier}.m{index + 1}.{uuid.uuid4().hex[:6]}"
                connection.execute(
                    """
                    INSERT INTO native_goal_milestones(
                        milestone_id, goal_id, label, status, evidence_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, 'pending', '[]', ?, ?)
                    """,
                    (milestone_id, identifier, str(label)[:1000], _iso(now), _iso(now)),
                )
            self._append_event(connection, identifier, "goal.created", payload)
            from .proofs_d_native import check_goal, require
            check_goal(connection, identifier, {"status": "active", "objective": clean_objective,
                "success_checks_json": json.dumps(checks, ensure_ascii=False), "schedule_seconds": schedule})
            saved_labels = [row[0] for row in connection.execute(
                "SELECT label FROM native_goal_milestones WHERE goal_id=? ORDER BY rowid", (identifier,))]
            require(saved_labels == [str(label)[:1000] for label in (milestones or [])],
                    "native.goals.durable", "created goal lost milestones")
        return self.get(identifier)

    def get(self, goal_id: str) -> dict[str, Any]:
        identifier = _safe_id(goal_id)
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM native_goals WHERE goal_id = ?", (identifier,)
            ).fetchone()
            milestones = connection.execute(
                "SELECT * FROM native_goal_milestones WHERE goal_id = ? ORDER BY created_at ASC",
                (identifier,),
            ).fetchall()
        if row is None:
            raise KeyError(f"Unknown Native goal: {identifier}")
        payload = dict(row)
        payload["successChecks"] = json.loads(payload.pop("success_checks_json"))
        payload["goalId"] = payload.pop("goal_id")
        payload["nextAction"] = payload.pop("next_action")
        payload["scheduleSeconds"] = payload.pop("schedule_seconds")
        payload["nextDueAt"] = payload.pop("next_due_at")
        payload["createdAt"] = payload.pop("created_at")
        payload["updatedAt"] = payload.pop("updated_at")
        payload["lastHeartbeatAt"] = payload.pop("last_heartbeat_at")
        payload["lastRunId"] = payload.pop("last_run_id")
        payload["completionReceipt"] = payload.pop("completion_receipt")
        payload["goalHash"] = payload.pop("goal_hash")
        payload["milestones"] = [
            {
                "milestoneId": item["milestone_id"],
                "label": item["label"],
                "status": item["status"],
                "evidence": json.loads(item["evidence_json"]),
                "createdAt": item["created_at"],
                "updatedAt": item["updated_at"],
            }
            for item in milestones
        ]
        payload["schema"] = GOAL_SCHEMA
        return payload

    def heartbeat(
        self,
        goal_id: str,
        *,
        run_id: str = "",
        next_action: str = "",
        status: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        identifier = _safe_id(goal_id)
        now = _now()
        with self.connection() as connection:
            current = connection.execute(
                "SELECT * FROM native_goals WHERE goal_id = ?", (identifier,)
            ).fetchone()
            if current is None:
                raise KeyError(f"Unknown Native goal: {identifier}")
            resolved_status = str(status or current["status"]).lower()
            if resolved_status not in _VALID_STATUS:
                raise ValueError(f"Unsupported goal status: {resolved_status}")
            schedule = current["schedule_seconds"]
            next_due = (
                _iso(now + timedelta(seconds=int(schedule)))
                if schedule and resolved_status == "active"
                else current["next_due_at"]
            )
            resolved_action = str(next_action or current["next_action"] or "")[:4000]
            connection.execute(
                """
                UPDATE native_goals
                SET status = ?, next_action = ?, next_due_at = ?, updated_at = ?,
                    last_heartbeat_at = ?, last_run_id = ?
                WHERE goal_id = ?
                """,
                (
                    resolved_status,
                    resolved_action,
                    next_due,
                    _iso(now),
                    _iso(now),
                    str(run_id or current["last_run_id"] or ""),
                    identifier,
                ),
            )
            event = {
                "schema": HEARTBEAT_SCHEMA,
                "runId": str(run_id or ""),
                "status": resolved_status,
                "nextAction": resolved_action,
                "evidence": dict(evidence or {}),
            }
            self._append_event(connection, identifier, "goal.heartbeat", event)
            from .proofs_d_native import check_goal
            check_goal(connection, identifier, {"status": resolved_status, "next_action": resolved_action,
                "last_run_id": str(run_id or current["last_run_id"] or ""), "last_heartbeat_at": _iso(now),
                "goal_hash": current["goal_hash"], "success_checks_json": current["success_checks_json"]})
        return self.get(identifier)

    def update_milestone(
        self,
        goal_id: str,
        milestone_id: str,
        *,
        status: str,
        evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        identifier = _safe_id(goal_id)
        resolved = str(status or "").lower()
        if resolved not in {"pending", "active", "blocked", "completed", "cancelled"}:
            raise ValueError(f"Unsupported milestone status: {resolved}")
        with self.connection() as connection:
            result = connection.execute(
                """
                UPDATE native_goal_milestones
                SET status = ?, evidence_json = ?, updated_at = ?
                WHERE goal_id = ? AND milestone_id = ?
                """,
                (
                    resolved,
                    json.dumps(evidence or [], ensure_ascii=False),
                    _iso(),
                    identifier,
                    str(milestone_id),
                ),
            )
            if result.rowcount != 1:
                raise KeyError(f"Unknown milestone {milestone_id} for {identifier}")
            self._append_event(
                connection,
                identifier,
                "milestone.updated",
                {"milestoneId": milestone_id, "status": resolved, "evidence": evidence or []},
            )
        return self.get(identifier)

    def complete(self, goal_id: str, receipt_path: str) -> dict[str, Any]:
        identifier = _safe_id(goal_id)
        if not receipt_path:
            raise ValueError("A completion receipt is required.")
        with self.connection() as connection:
            result = connection.execute(
                """
                UPDATE native_goals
                SET status='completed', completion_receipt=?, next_due_at=NULL,
                    updated_at=?, last_heartbeat_at=?
                WHERE goal_id=?
                """,
                (receipt_path, _iso(), _iso(), identifier),
            )
            if result.rowcount != 1:
                raise KeyError(f"Unknown Native goal: {identifier}")
            self._append_event(
                connection,
                identifier,
                "goal.completed",
                {"completionReceipt": receipt_path},
            )
            from .proofs_d_native import check_goal
            check_goal(connection, identifier, {"status": "completed", "completion_receipt": receipt_path, "next_due_at": None})
        return self.get(identifier)

    def due(self, limit: int = 20) -> list[dict[str, Any]]:
        now = _iso()
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT goal_id, status, schedule_seconds, next_due_at FROM native_goals
                WHERE status='active' AND next_due_at IS NOT NULL AND next_due_at <= ?
                ORDER BY priority DESC, next_due_at ASC
                LIMIT ?
                """,
                (now, max(1, min(200, int(limit)))),
            ).fetchall()
            from .proofs_d_native import require
            require(all(row["status"] == "active" and row["schedule_seconds"] and row["next_due_at"] <= now for row in rows),
                    "native.goals.due", "due query returned unscheduled, inactive or future work")
        return [self.get(row["goal_id"]) for row in rows]

    def list(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT goal_id FROM native_goals"
        parameters: list[Any] = []
        if status:
            resolved = str(status).lower()
            if resolved not in _VALID_STATUS:
                raise ValueError(f"Unsupported goal status: {resolved}")
            query += " WHERE status = ?"
            parameters.append(resolved)
        query += " ORDER BY priority DESC, updated_at DESC LIMIT ?"
        parameters.append(max(1, min(500, int(limit))))
        with self.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self.get(row["goal_id"]) for row in rows]
