from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from .proofs_a_cli import checked


TASK_STATES = {
    "queued",
    "working",
    "waiting",
    "input_required",
    "completed",
    "failed",
    "cancelled",
}
TERMINAL_TASK_STATES = {"completed", "failed", "cancelled"}
TRANSITIONS = {
    "queued": {"working", "waiting", "cancelled"},
    "working": {"queued", "waiting", "input_required", "completed", "failed", "cancelled"},
    "waiting": {"queued", "working", "input_required", "completed", "failed", "cancelled"},
    "input_required": {"queued", "working", "cancelled"},
    "completed": set(),
    "failed": {"queued"},
    "cancelled": set(),
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


class CrashProofStore:
    """Durable N-E-Y-V-I-A task coordination without model-driven polling."""

    def __init__(self, root: str | Path, *, database_path: str | Path | None = None) -> None:
        self.root = Path(root).resolve()
        self.database_path = Path(database_path) if database_path else self.root / ".agent_control" / "crashproof.sqlite3"
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS durable_tasks (
                    task_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    parent_task_id TEXT,
                    payload_json TEXT NOT NULL,
                    result_json TEXT,
                    error_json TEXT,
                    checkpoint_json TEXT,
                    priority INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    worker_id TEXT,
                    lease_until TEXT,
                    deadline_at TEXT,
                    next_wakeup_at TEXT,
                    permission_lease_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY(parent_task_id) REFERENCES durable_tasks(task_id),
                    UNIQUE(mission_id, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_durable_tasks_due
                    ON durable_tasks(status, next_wakeup_at, priority DESC, created_at);
                CREATE INDEX IF NOT EXISTS idx_durable_tasks_mission
                    ON durable_tasks(mission_id, created_at);

                CREATE TABLE IF NOT EXISTS durable_task_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES durable_tasks(task_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS result_sets (
                    result_set_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS result_items (
                    item_id TEXT PRIMARY KEY,
                    result_set_id TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(result_set_id) REFERENCES result_sets(result_set_id) ON DELETE CASCADE,
                    UNIQUE(result_set_id, dedupe_key)
                );

                CREATE TABLE IF NOT EXISTS autonomy_leases (
                    lease_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    session_id TEXT,
                    parent_lease_id TEXT,
                    policy_json TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    FOREIGN KEY(parent_lease_id) REFERENCES autonomy_leases(lease_id)
                );
                CREATE INDEX IF NOT EXISTS idx_autonomy_leases_mission
                    ON autonomy_leases(mission_id, expires_at);

                CREATE TABLE IF NOT EXISTS operation_estimates (
                    operation_kind TEXT PRIMARY KEY,
                    sample_count INTEGER NOT NULL,
                    mean_seconds REAL NOT NULL,
                    last_seconds REAL NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            connection.commit()

    @checked('a-cli.crash.submit')
    def submit_task(
        self,
        *,
        mission_id: str,
        kind: str,
        idempotency_key: str,
        payload: dict[str, Any] | None = None,
        parent_task_id: str | None = None,
        priority: int = 0,
        deadline_at: str | None = None,
        next_wakeup_at: str | None = None,
        permission_lease_id: str | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        if not mission_id.strip() or not kind.strip() or not idempotency_key.strip():
            raise ValueError("mission_id, kind, and idempotency_key are required")
        timestamp = now or utc_now_iso()
        task_id = f"task_{uuid.uuid4().hex}"
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM durable_tasks WHERE mission_id = ? AND idempotency_key = ?",
                (mission_id, idempotency_key),
            ).fetchone()
            if existing:
                connection.rollback()
                task = self._task_from_row(existing)
                task["deduplicated"] = True
                return task
            connection.execute(
                """
                INSERT INTO durable_tasks (
                    task_id, mission_id, kind, status, idempotency_key, parent_task_id,
                    payload_json, priority, deadline_at, next_wakeup_at,
                    permission_lease_id, created_at, updated_at
                ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    mission_id,
                    kind,
                    idempotency_key,
                    parent_task_id,
                    _json(payload or {}),
                    int(priority),
                    deadline_at,
                    next_wakeup_at,
                    permission_lease_id,
                    timestamp,
                    timestamp,
                ),
            )
            self._append_event(connection, task_id, "submitted", {"kind": kind}, timestamp)
            connection.commit()
        task = self.get_task(task_id)
        task["deduplicated"] = False
        return task

    def get_task(self, task_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM durable_tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            raise KeyError(task_id)
        return self._task_from_row(row)

    def list_tasks(self, *, mission_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        query = "SELECT * FROM durable_tasks"
        params: tuple[Any, ...] = ()
        if mission_id:
            query += " WHERE mission_id = ?"
            params = (mission_id,)
        query += " ORDER BY created_at DESC LIMIT ?"
        params += (max(1, min(int(limit), 1000)),)
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._task_from_row(row) for row in rows]

    def operator_snapshot(self, *, limit: int = 500) -> dict[str, Any]:
        """Return critical-first state from new durable tasks only.

        Legacy mission rows are intentionally outside this store, so old blocked
        missions cannot inflate the current block factor.
        """
        tasks = self.list_tasks(limit=limit)
        status_order = {
            "input_required": 0,
            "working": 1,
            "waiting": 2,
            "queued": 3,
            "failed": 4,
            "completed": 5,
            "cancelled": 6,
        }
        active = [task for task in tasks if task["status"] not in TERMINAL_TASK_STATES]
        active.sort(key=lambda task: (status_order.get(task["status"], 99), task["createdAt"]))
        new_blockers = [task for task in tasks if task["status"] in {"input_required", "failed"}]
        counts: dict[str, int] = {}
        for task in tasks:
            counts[task["status"]] = counts.get(task["status"], 0) + 1
        current = active[0] if active else None
        next_action = (
            "Provide the requested input so background work can resume."
            if current and current["status"] == "input_required"
            else "Let the background worker continue; N-E-Y-V-I-A will wake the model at a milestone."
            if current
            else "Start a mission; long work will persist and resume without keeping a model turn open."
        )
        from .neyvia_conversations import NeyviaConversationStore

        conversation_snapshot = NeyviaConversationStore(
            self.root,
            database_path=self.database_path,
        ).snapshot(limit=min(limit, 100))
        return {
            "schema": "neyvia.operator-snapshot.v1",
            "generatedAt": utc_now_iso(),
            "currentTask": current,
            "activeTasks": active[:8],
            "recentTerminalTasks": [task for task in tasks if task["status"] in TERMINAL_TASK_STATES][:8],
            "counts": counts,
            "blockFactor": {
                "value": len(new_blockers),
                "newMissionTasksOnly": True,
                "legacyBlockedMissionsIncluded": False,
            },
            "nextAction": next_action,
            "durability": {
                "database": str(self.database_path),
                "journalMode": "WAL",
                "synchronous": "FULL",
                "wakePolicy": "terminal_or_input_only",
            },
            "conversationFabric": conversation_snapshot,
        }

    @checked('a-cli.crash.claim')
    def claim_next(
        self,
        *,
        worker_id: str,
        kinds: list[str] | None = None,
        lease_seconds: int = 120,
        now: str | None = None,
    ) -> dict[str, Any] | None:
        timestamp = now or utc_now_iso()
        lease_until = (_parse_time(timestamp) + timedelta(seconds=max(1, lease_seconds))).isoformat().replace("+00:00", "Z")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            clauses = ["status = 'queued'", "(next_wakeup_at IS NULL OR next_wakeup_at <= ?)"]
            params: list[Any] = [timestamp]
            if kinds:
                placeholders = ",".join("?" for _ in kinds)
                clauses.append(f"kind IN ({placeholders})")
                params.extend(kinds)
            row = connection.execute(
                f"SELECT * FROM durable_tasks WHERE {' AND '.join(clauses)} ORDER BY priority DESC, created_at LIMIT 1",
                tuple(params),
            ).fetchone()
            if not row:
                connection.rollback()
                return None
            connection.execute(
                """
                UPDATE durable_tasks
                SET status = 'working', worker_id = ?, lease_until = ?, attempts = attempts + 1,
                    next_wakeup_at = NULL, updated_at = ?
                WHERE task_id = ? AND status = 'queued'
                """,
                (worker_id, lease_until, timestamp, row["task_id"]),
            )
            self._append_event(connection, row["task_id"], "claimed", {"workerId": worker_id}, timestamp)
            connection.commit()
        return self.get_task(row["task_id"])

    def heartbeat(self, task_id: str, *, worker_id: str, lease_seconds: int = 120, now: str | None = None) -> dict[str, Any]:
        timestamp = now or utc_now_iso()
        lease_until = (_parse_time(timestamp) + timedelta(seconds=max(1, lease_seconds))).isoformat().replace("+00:00", "Z")
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE durable_tasks SET lease_until = ?, updated_at = ?
                WHERE task_id = ? AND status = 'working' AND worker_id = ?
                """,
                (lease_until, timestamp, task_id, worker_id),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise RuntimeError("task is not owned by this worker")
            connection.commit()
        return self.get_task(task_id)

    @checked('a-cli.crash.transition')
    def transition_task(
        self,
        task_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        checkpoint: dict[str, Any] | None = None,
        next_wakeup_at: str | None = None,
        event_payload: dict[str, Any] | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        if status not in TASK_STATES:
            raise ValueError(f"unknown task status: {status}")
        timestamp = now or utc_now_iso()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM durable_tasks WHERE task_id = ?", (task_id,)).fetchone()
            if not row:
                connection.rollback()
                raise KeyError(task_id)
            previous = row["status"]
            if status != previous and status not in TRANSITIONS[previous]:
                connection.rollback()
                raise ValueError(f"invalid task transition: {previous} -> {status}")
            completed_at = timestamp if status in TERMINAL_TASK_STATES else None
            connection.execute(
                """
                UPDATE durable_tasks
                SET status = ?, result_json = COALESCE(?, result_json),
                    error_json = COALESCE(?, error_json), checkpoint_json = COALESCE(?, checkpoint_json),
                    next_wakeup_at = ?, worker_id = CASE WHEN ? = 'working' THEN worker_id ELSE NULL END,
                    lease_until = CASE WHEN ? = 'working' THEN lease_until ELSE NULL END,
                    updated_at = ?, completed_at = ?
                WHERE task_id = ?
                """,
                (
                    status,
                    _json(result) if result is not None else None,
                    _json(error) if error is not None else None,
                    _json(checkpoint) if checkpoint is not None else None,
                    next_wakeup_at,
                    status,
                    status,
                    timestamp,
                    completed_at,
                    task_id,
                ),
            )
            self._append_event(connection, task_id, f"state.{status}", event_payload or {}, timestamp)
            connection.commit()
        return self.get_task(task_id)

    @checked('a-cli.crash.recover')
    def recover_interrupted(self, *, now: str | None = None) -> list[str]:
        timestamp = now or utc_now_iso()
        recovered: list[str] = []
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT task_id FROM durable_tasks WHERE status = 'working' AND lease_until IS NOT NULL AND lease_until <= ?",
                (timestamp,),
            ).fetchall()
            for row in rows:
                task_id = row["task_id"]
                connection.execute(
                    """
                    UPDATE durable_tasks
                    SET status = 'queued', worker_id = NULL, lease_until = NULL,
                        next_wakeup_at = NULL, updated_at = ? WHERE task_id = ?
                    """,
                    (timestamp, task_id),
                )
                self._append_event(connection, task_id, "recovered.interrupted", {}, timestamp)
                recovered.append(task_id)
            connection.commit()
        return recovered

    def task_events(self, task_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM durable_task_events WHERE task_id = ? ORDER BY event_id",
                (task_id,),
            ).fetchall()
        return [
            {
                "eventId": row["event_id"],
                "taskId": row["task_id"],
                "kind": row["kind"],
                "payload": _decode(row["payload_json"], {}),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def create_result_set(self, *, mission_id: str, kind: str, metadata: dict[str, Any] | None = None, now: str | None = None) -> dict[str, Any]:
        timestamp = now or utc_now_iso()
        result_set_id = f"results_{uuid.uuid4().hex}"
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO result_sets VALUES (?, ?, ?, ?, ?, ?)",
                (result_set_id, mission_id, kind, _json(metadata or {}), timestamp, timestamp),
            )
            connection.commit()
        return {"resultSetId": result_set_id, "missionId": mission_id, "kind": kind, "metadata": metadata or {}}

    @checked('a-cli.crash.result')
    def add_result_item(
        self,
        result_set_id: str,
        *,
        payload: dict[str, Any],
        status: str = "completed",
        source: str = "",
        dedupe_key: str | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        timestamp = now or utc_now_iso()
        key = dedupe_key or hashlib.sha256((source + "\0" + _json(payload)).encode("utf-8")).hexdigest()
        item_id = f"item_{uuid.uuid4().hex}"
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM result_items WHERE result_set_id = ? AND dedupe_key = ?",
                (result_set_id, key),
            ).fetchone()
            if existing:
                connection.rollback()
                return self._result_item(existing, deduplicated=True)
            connection.execute(
                "INSERT INTO result_items VALUES (?, ?, ?, ?, ?, ?, ?)",
                (item_id, result_set_id, key, status, source, _json(payload), timestamp),
            )
            connection.execute("UPDATE result_sets SET updated_at = ? WHERE result_set_id = ?", (timestamp, result_set_id))
            connection.commit()
        return {
            "itemId": item_id,
            "resultSetId": result_set_id,
            "dedupeKey": key,
            "status": status,
            "source": source,
            "payload": payload,
            "deduplicated": False,
        }

    @checked('a-cli.crash.summary')
    def summarize_result_set(self, result_set_id: str, *, sample_limit: int = 5) -> dict[str, Any]:
        with self._connection() as connection:
            result_set = connection.execute("SELECT * FROM result_sets WHERE result_set_id = ?", (result_set_id,)).fetchone()
            if not result_set:
                raise KeyError(result_set_id)
            counts = connection.execute(
                "SELECT status, COUNT(*) AS count FROM result_items WHERE result_set_id = ? GROUP BY status",
                (result_set_id,),
            ).fetchall()
            samples = connection.execute(
                "SELECT * FROM result_items WHERE result_set_id = ? ORDER BY created_at LIMIT ?",
                (result_set_id, max(0, min(int(sample_limit), 20))),
            ).fetchall()
        by_status = {row["status"]: row["count"] for row in counts}
        return {
            "resultSetId": result_set_id,
            "missionId": result_set["mission_id"],
            "kind": result_set["kind"],
            "total": sum(by_status.values()),
            "byStatus": by_status,
            "samples": [self._result_item(row, deduplicated=False) for row in samples],
        }

    def record_operation_duration(self, operation_kind: str, seconds: float, *, now: str | None = None) -> dict[str, Any]:
        timestamp = now or utc_now_iso()
        duration = max(0.0, float(seconds))
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM operation_estimates WHERE operation_kind = ?", (operation_kind,)).fetchone()
            if row:
                count = int(row["sample_count"]) + 1
                mean = float(row["mean_seconds"]) + (duration - float(row["mean_seconds"])) / count
                connection.execute(
                    "UPDATE operation_estimates SET sample_count = ?, mean_seconds = ?, last_seconds = ?, updated_at = ? WHERE operation_kind = ?",
                    (count, mean, duration, timestamp, operation_kind),
                )
            else:
                count, mean = 1, duration
                connection.execute(
                    "INSERT INTO operation_estimates VALUES (?, ?, ?, ?, ?)",
                    (operation_kind, count, mean, duration, timestamp),
                )
            connection.commit()
        return {"operationKind": operation_kind, "sampleCount": count, "meanSeconds": mean, "lastSeconds": duration}

    @checked('a-cli.crash.time')
    def time_snapshot(
        self,
        *,
        deadline_at: str | None,
        estimated_next_seconds: float = 0,
        verification_reserve_seconds: float = 0,
        optional: bool = False,
        now: str | None = None,
    ) -> dict[str, Any]:
        timestamp = now or utc_now_iso()
        current = _parse_time(timestamp)
        deadline = _parse_time(deadline_at)
        if deadline is None:
            return {
                "now": timestamp,
                "deadlineAt": None,
                "remainingSeconds": None,
                "shouldContinue": True,
                "skipOptional": False,
                "reason": "no_deadline",
            }
        remaining = max(0.0, (deadline - current).total_seconds())
        required = max(0.0, float(estimated_next_seconds)) + max(0.0, float(verification_reserve_seconds))
        enough = remaining >= required
        return {
            "now": timestamp,
            "deadlineAt": deadline_at,
            "remainingSeconds": remaining,
            "requiredSeconds": required,
            "shouldContinue": enough or not optional,
            "skipOptional": optional and not enough,
            "deadlineRisk": not enough,
            "reason": "enough_time" if enough else ("skip_optional" if optional else "deadline_risk_required_work"),
        }

    def create_autonomy_lease(
        self,
        *,
        mission_id: str,
        policy: dict[str, Any],
        duration_seconds: int,
        session_id: str = "",
        parent_lease_id: str | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        issued_at = now or utc_now_iso()
        expires_at = (_parse_time(issued_at) + timedelta(seconds=max(1, int(duration_seconds)))).isoformat().replace("+00:00", "Z")
        lease_id = f"autonomy_{uuid.uuid4().hex}"
        if parent_lease_id:
            parent = self.get_autonomy_lease(parent_lease_id)
            if parent["missionId"] != mission_id:
                raise ValueError("child lease must remain in the parent mission")
            if _parse_time(expires_at) > _parse_time(parent["expiresAt"]):
                raise ValueError("child lease cannot outlive its parent")
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO autonomy_leases VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                (lease_id, mission_id, session_id, parent_lease_id, _json(policy), issued_at, expires_at),
            )
            connection.commit()
        return self.get_autonomy_lease(lease_id, now=issued_at)

    def get_autonomy_lease(self, lease_id: str, *, now: str | None = None) -> dict[str, Any]:
        timestamp = now or utc_now_iso()
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM autonomy_leases WHERE lease_id = ?", (lease_id,)).fetchone()
        if not row:
            raise KeyError(lease_id)
        active = not row["revoked_at"] and _parse_time(row["expires_at"]) > _parse_time(timestamp)
        return {
            "leaseId": row["lease_id"],
            "missionId": row["mission_id"],
            "sessionId": row["session_id"],
            "parentLeaseId": row["parent_lease_id"],
            "policy": _decode(row["policy_json"], {}),
            "issuedAt": row["issued_at"],
            "expiresAt": row["expires_at"],
            "revokedAt": row["revoked_at"],
            "active": active,
        }

    def revoke_autonomy_lease(self, lease_id: str, *, now: str | None = None) -> dict[str, Any]:
        timestamp = now or utc_now_iso()
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE autonomy_leases SET revoked_at = COALESCE(revoked_at, ?) WHERE lease_id = ?",
                (timestamp, lease_id),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise KeyError(lease_id)
            connection.commit()
        return self.get_autonomy_lease(lease_id, now=timestamp)

    @checked('a-cli.crash.autonomy')
    def autonomy_allows(self, lease_id: str, *, action: str, context: dict[str, Any] | None = None, now: str | None = None) -> dict[str, Any]:
        lease = self.get_autonomy_lease(lease_id, now=now)
        if not lease["active"]:
            return {"allowed": False, "reason": "lease_inactive", "lease": lease}
        if lease["parentLeaseId"]:
            parent_check = self.autonomy_allows(lease["parentLeaseId"], action=action, context=context, now=now)
            if not parent_check["allowed"]:
                return {
                    "allowed": False,
                    "reason": parent_check["reason"],
                    "deniedByLeaseId": lease["parentLeaseId"],
                    "lease": lease,
                }
        policy = lease["policy"]
        details = context or {}
        actions = policy.get("allowedActions", [])
        if "*" not in actions and action not in actions:
            return {"allowed": False, "reason": "action_out_of_scope", "lease": lease}
        if details.get("destructive") and not policy.get("destructiveAllowed", False):
            return {"allowed": False, "reason": "destructive_not_granted", "lease": lease}
        if details.get("publicCommunication") and not policy.get("publicCommunicationAllowed", False):
            return {"allowed": False, "reason": "public_communication_not_granted", "lease": lease}
        spend = float(details.get("spend", 0) or 0)
        if spend > float(policy.get("maxSpend", 0) or 0):
            return {"allowed": False, "reason": "spend_limit", "lease": lease}
        path = details.get("path")
        roots = policy.get("allowedRoots", [])
        if path and roots and not any(self._path_within(path, root) for root in roots):
            return {"allowed": False, "reason": "path_out_of_scope", "lease": lease}
        domain = str(details.get("domain", "")).lower()
        domains = [str(item).lower() for item in policy.get("allowedDomains", [])]
        if domain and domains and domain not in domains:
            return {"allowed": False, "reason": "domain_out_of_scope", "lease": lease}
        return {"allowed": True, "reason": "granted", "lease": lease}

    def _path_within(self, path: str | Path, root: str | Path) -> bool:
        candidate = Path(path).resolve()
        boundary = Path(root).resolve()
        try:
            candidate.relative_to(boundary)
            return True
        except ValueError:
            return False

    @staticmethod
    def _append_event(connection: sqlite3.Connection, task_id: str, kind: str, payload: dict[str, Any], timestamp: str) -> None:
        connection.execute(
            "INSERT INTO durable_task_events (task_id, kind, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (task_id, kind, _json(payload), timestamp),
        )

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "taskId": row["task_id"],
            "missionId": row["mission_id"],
            "kind": row["kind"],
            "status": row["status"],
            "idempotencyKey": row["idempotency_key"],
            "parentTaskId": row["parent_task_id"],
            "payload": _decode(row["payload_json"], {}),
            "result": _decode(row["result_json"], None),
            "error": _decode(row["error_json"], None),
            "checkpoint": _decode(row["checkpoint_json"], None),
            "priority": row["priority"],
            "attempts": row["attempts"],
            "workerId": row["worker_id"],
            "leaseUntil": row["lease_until"],
            "deadlineAt": row["deadline_at"],
            "nextWakeupAt": row["next_wakeup_at"],
            "permissionLeaseId": row["permission_lease_id"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "completedAt": row["completed_at"],
        }

    @staticmethod
    def _result_item(row: sqlite3.Row, *, deduplicated: bool) -> dict[str, Any]:
        return {
            "itemId": row["item_id"],
            "resultSetId": row["result_set_id"],
            "dedupeKey": row["dedupe_key"],
            "status": row["status"],
            "source": row["source"],
            "payload": _decode(row["payload_json"], {}),
            "deduplicated": deduplicated,
        }
