"""Durable, bounded cross-device task resume checkpoints.

This store deliberately contains no authentication or device trust logic.  The
caller must authenticate and scope ``device_id`` before invoking it.  SQLite's
transaction and compare-and-swap revision make a phone/computer pair converge
without silently overwriting one another.
"""

from __future__ import annotations

import json
import hashlib
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA = "neyvia.task-continuity.v1"
MAX_DRAFT_BYTES = 64 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _id(value: Any, field: str, *, allow_empty: bool = False) -> str:
    result = str(value or "").strip()
    if not result and allow_empty:
        return ""
    if not _IDENTIFIER.fullmatch(result):
        raise ValueError(f"{field} must be a bounded identifier")
    return result


def _draft_json(value: Any) -> str | None:
    if value is None:
        return None
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("draft must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > MAX_DRAFT_BYTES:
        raise ValueError(f"draft exceeds {MAX_DRAFT_BYTES} UTF-8 bytes")
    return encoded


def _decode(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


class TaskContinuityStore:
    """Shared latest and per-device checkpoints with global optimistic CAS."""

    def __init__(self, root: str | Path, owner_id: str = "local", *, database_path: str | Path | None = None) -> None:
        self.root = Path(root).resolve()
        self.database_path = Path(database_path) if database_path else self.root / ".agent_control" / "task_continuity.sqlite3"
        owner = str(owner_id or "local").strip()
        if not owner or len(owner) > 256:
            raise ValueError("owner_id must be a non-empty bounded value")
        self.owner_id = owner
        self.owner_hash = hashlib.sha256(owner.encode("utf-8")).hexdigest()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.database_path, timeout=30.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=30000")
        try:
            yield db
        finally:
            db.close()

    def _ensure_schema(self) -> None:
        with self._connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS continuity_meta (
                    owner_hash TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL DEFAULT 0,
                    shared_device_id TEXT,
                    shared_conversation_id TEXT,
                    shared_draft_json TEXT,
                    shared_updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS continuity_checkpoints (
                    owner_hash TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    draft_json TEXT,
                    cursor TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(owner_hash, device_id)
                );
                """
            )
            db.execute("INSERT OR IGNORE INTO continuity_meta(owner_hash, revision) VALUES (?, 0)", (self.owner_hash,))
            db.commit()

    @staticmethod
    def _checkpoint(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "deviceId": row["device_id"],
            "conversationId": row["conversation_id"],
            "draft": _decode(row["draft_json"]),
            "cursor": row["cursor"],
            "revision": int(row["revision"]),
            "updatedAt": row["updated_at"],
        }

    def _read_db(self, db: sqlite3.Connection, device_id: str) -> dict[str, Any]:
        meta = db.execute("SELECT * FROM continuity_meta WHERE owner_hash = ?", (self.owner_hash,)).fetchone()
        row = db.execute("SELECT * FROM continuity_checkpoints WHERE owner_hash = ? AND device_id = ?", (self.owner_hash, device_id)).fetchone()
        shared = None
        if meta and meta["shared_conversation_id"]:
            shared = {
                "deviceId": meta["shared_device_id"],
                "conversationId": meta["shared_conversation_id"],
                "draft": _decode(meta["shared_draft_json"]),
                "revision": int(meta["revision"]),
                "updatedAt": meta["shared_updated_at"],
            }
        return {
            "schema": SCHEMA,
            "deviceId": device_id,
            "revision": int(meta["revision"] if meta else 0),
            "sharedLatest": shared,
            "lastResumed": shared,
            "deviceCheckpoint": self._checkpoint(row),
            "perDevice": self._checkpoint(row),
        }

    def read(self, device_id: str) -> dict[str, Any]:
        device_id = _id(device_id, "device_id")
        with self._connection() as db:
            db.execute("BEGIN")
            result = self._read_db(db, device_id)
            db.commit()
            return result

    def save(
        self,
        device_id: str,
        conversation_id: str,
        expected_revision: int,
        draft: Any = None,
    ) -> dict[str, Any]:
        device_id = _id(device_id, "device_id")
        conversation_id = _id(conversation_id, "conversation_id")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        draft_json = _draft_json(draft)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO continuity_meta(owner_hash, revision) VALUES (?, 0)", (self.owner_hash,))
            meta = db.execute("SELECT revision FROM continuity_meta WHERE owner_hash = ?", (self.owner_hash,)).fetchone()
            current_revision = int(meta["revision"] if meta else 0)
            if expected_revision != current_revision:
                current = self._read_db(db, device_id)
                db.rollback()
                return {"ok": False, "status": "conflict", "conflict": True, "current": current}
            revision = current_revision + 1
            timestamp = _now()
            cursor = f"r{revision}"
            db.execute(
                """INSERT INTO continuity_checkpoints(owner_hash, device_id, conversation_id, draft_json, cursor, revision, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(owner_hash, device_id) DO UPDATE SET conversation_id=excluded.conversation_id,
                     draft_json=excluded.draft_json, cursor=excluded.cursor,
                     revision=excluded.revision, updated_at=excluded.updated_at""",
                (self.owner_hash, device_id, conversation_id, draft_json, cursor, revision, timestamp),
            )
            db.execute(
                """UPDATE continuity_meta SET revision=?, shared_device_id=?, shared_conversation_id=?,
                   shared_draft_json=?, shared_updated_at=? WHERE owner_hash=?""",
                (revision, device_id, conversation_id, draft_json, timestamp, self.owner_hash),
            )
            checkpoint = self._read_db(db, device_id)
            db.commit()
            return {
                "ok": True,
                "status": "saved",
                "conflict": False,
                "revision": checkpoint["revision"],
                "checkpoint": checkpoint["deviceCheckpoint"],
                "state": checkpoint,
            }


__all__ = ["TaskContinuityStore", "SCHEMA", "MAX_DRAFT_BYTES"]
