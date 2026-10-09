"""Durable run records for connected sessions, in ``.agent_control/connected_chats.sqlite3``.

One row per run: idempotent by request id, at most one active run per session, and a run whose
owner process is gone is marked ``interrupted`` and never resent. The store knows nothing about
threads or adapters; the broker tells it which runs it still owns (``is_live``).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..chat_run_control import process_started_at
from .registry import ConnectedError

log = logging.getLogger("neyvia.connected_sessions")

ACTIVE_STATES = frozenset({"queued", "running", "waiting_approval", "waiting_input"})
TERMINAL_STATES = frozenset({"completed", "failed", "interrupted", "cancelled"})
_ACTIVE_SQL = ",".join(f"'{state}'" for state in sorted(ACTIVE_STATES))
_RETENTION_SECONDS = 30 * 24 * 3600
INTERRUPTED_BY_RESTART = ("The service that was running this turn stopped before it finished. "
                          "Neyvia did not resend it; check the session before trying again.")


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def public_run(data: dict[str, Any]) -> dict[str, Any]:
    """A stored run as the ``RunRecord`` clients see; only an active run can be stopped or steered."""
    active = data.get("state") in ACTIVE_STATES
    return {"runId": data["runId"], "sessionId": data.get("sessionId"), "app": data.get("app"), "state": data["state"],
            "startedAt": data.get("startedAt"), "updatedAt": data.get("updatedAt"),
            "pendingRequest": data.get("pendingRequest"), "error": data.get("error"),
            "canStop": bool(active and data.get("canStop")), "canSteer": bool(active and data.get("canSteer")),
            "usage": data.get("usage"), "model": data.get("model"), "effort": data.get("effort"),
            "permissionMode": data.get("permissionMode"), "promptCharacters": data.get("promptCharacters"),
            "impact": data.get("impact"), "feedback": data.get("feedback"),
            "memoryRecall": data.get('memoryRecall'), "memoryWrite": data.get('memoryWrite'),
            "memoryCandidate": data.get('memoryCandidate')}


def request_fingerprint(kind, identity, message, options):
    import hashlib
    from dataclasses import asdict
    return hashlib.sha256(json.dumps([kind, identity, message, asdict(options)],
                                     sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class RunStore:
    def __init__(self, path: Path, token: str, is_live: Callable[[str], bool]):
        self.path, self.token, self._is_live = path, token, is_live
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS connected_session_runs (run_id TEXT PRIMARY KEY, session_key TEXT NOT NULL, "
                "app TEXT NOT NULL, fingerprint TEXT NOT NULL, state TEXT NOT NULL, pid INTEGER, owner_token TEXT, "
                "owner_started REAL, started REAL, updated REAL, data TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS connected_session_runs_session ON connected_session_runs(session_key, updated)")
            db.execute("DELETE FROM connected_session_runs WHERE state NOT IN (" + _ACTIVE_SQL + ") AND updated < ?",
                       (time.time() - _RETENTION_SECONDS,))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _owner_alive(self, row: sqlite3.Row) -> bool:
        if row["owner_token"] == self.token:
            return self._is_live(row["run_id"])
        if int(row["pid"] or 0) == os.getpid():
            return False  # an earlier broker in this process is gone
        started = process_started_at(row["pid"])
        if started is None:
            return False
        recorded = float(row["owner_started"] or 0)
        return not (started and recorded and abs(started - recorded) > 2.0)

    def recover(self, *, session_key: str | None = None, run_id: str | None = None,
                session_keys: list[str] | None = None) -> list[dict[str, Any]]:
        """Mark active runs whose owner is gone as ``interrupted``; returns their records."""
        sql, args = "SELECT * FROM connected_session_runs WHERE state IN (" + _ACTIVE_SQL + ")", []
        if session_key is not None:
            sql, args = sql + " AND session_key=?", args + [session_key]
        if run_id is not None:
            sql, args = sql + " AND run_id=?", args + [run_id]
        if session_keys is not None:
            keys = list(dict.fromkeys(session_keys))
            if not keys:
                return []
            sql += " AND session_key IN (" + ",".join("?" for _ in keys) + ")"
            args += keys
        with self.connect() as db:  # the common case finds nothing stale and never takes the write lock
            stale = {row["run_id"] for row in db.execute(sql, args).fetchall() if not self._owner_alive(row)}
        if not stale:
            return []
        recovered: list[dict[str, Any]] = []
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute(sql, args).fetchall():
                if row["run_id"] not in stale or self._owner_alive(row):
                    continue
                data = json.loads(row["data"])
                data.update(state="interrupted", error=INTERRUPTED_BY_RESTART, pendingRequest=None, updatedAt=iso(time.time()))
                db.execute("UPDATE connected_session_runs SET state=?, updated=?, data=? WHERE run_id=?",
                           ("interrupted", time.time(), json.dumps(data), row["run_id"]))
                recovered.append(data)
        return recovered

    def load(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT data FROM connected_session_runs WHERE run_id=?", (run_id,)).fetchone()
        return json.loads(row["data"]) if row else None

    def latest(self, session_key: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT data FROM connected_session_runs WHERE session_key=? ORDER BY updated DESC, rowid DESC LIMIT 1",
                             (session_key,)).fetchone()
        return json.loads(row["data"]) if row else None

    def latest_many(self, session_keys: list[str]) -> dict[str, dict[str, Any]]:
        """One read snapshot for a sidebar page; same ordering as latest()."""
        keys = list(dict.fromkeys(session_keys))
        if not keys:
            return {}
        with self.connect() as db:
            rows = db.execute(
                "SELECT session_key, data FROM (SELECT session_key, data, "
                "ROW_NUMBER() OVER (PARTITION BY session_key ORDER BY updated DESC, rowid DESC) AS position "
                "FROM connected_session_runs WHERE session_key IN (" + ",".join("?" for _ in keys) + ")) "
                "WHERE position=1", keys).fetchall()
        return {row["session_key"]: json.loads(row["data"]) for row in rows}

    def active(self) -> list[dict[str, Any]]:
        """Current persisted owners, including detached workers in other processes."""
        with self.connect() as db:
            rows = db.execute("SELECT data FROM connected_session_runs WHERE state IN (" + _ACTIVE_SQL + ")").fetchall()
        return [json.loads(row["data"]) for row in rows]

    def has_request(self, run_id: str, fingerprint: str) -> bool:
        """True when this request id was already used for the same request; a different one is refused."""
        with self.connect() as db:
            row = db.execute("SELECT fingerprint FROM connected_session_runs WHERE run_id=?", (run_id,)).fetchone()
        return self._matches(row, fingerprint)

    @staticmethod
    def _matches(row: sqlite3.Row | None, fingerprint: str) -> bool:
        if row is None:
            return False
        if row["fingerprint"] != fingerprint:
            raise ConnectedError("request_id_conflict", "This request ID was already used for a different message.", 409)
        return True

    def save(self, data: dict[str, Any]) -> None:
        key = data.get("sessionId") or f"new:{data['runId']}"
        try:
            with self.connect() as db:
                db.execute("UPDATE connected_session_runs SET state=?, session_key=?, updated=?, data=? WHERE run_id=?",
                           (data["state"], key, time.time(), json.dumps(data), data["runId"]))
        except sqlite3.Error:
            log.exception("Could not record run %s", data["runId"])

    def claim(self, data: dict[str, Any], fingerprint: str, owner_started: float | None, *,
              is_free: Callable[[str], bool], register: Callable[[], None], unregister: Callable[[], None]) -> bool:
        """Record a new queued run unless its session already has an active one.

        Returns False for a replay of the same request. ``is_free`` says an active row is really
        over (it just ended in memory); ``register``/``unregister`` bracket the insert so the run is
        known to its owner before any other thread can look at the row.
        """
        run_id = data["runId"]
        key = data.get("sessionId") or f"new:{run_id}"
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if self._matches(db.execute("SELECT fingerprint FROM connected_session_runs WHERE run_id=?", (run_id,)).fetchone(),
                             fingerprint):
                return False
            active = [row["run_id"] for row in db.execute(
                "SELECT run_id FROM connected_session_runs WHERE session_key=? AND state IN (" + _ACTIVE_SQL + ")", (key,))]
            active = [other for other in active if not is_free(other)]
            if active:
                raise ConnectedError("session_busy", "This session already has a turn in progress. Stop it or wait for it to finish.",
                                     409, runId=active[0])
            register()
            try:
                db.execute("INSERT INTO connected_session_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (run_id, key, data["app"], fingerprint, "queued", os.getpid(), self.token, owner_started or 0.0, now, now,
                            json.dumps(data)))
            except Exception:
                unregister()
                raise
        return True
