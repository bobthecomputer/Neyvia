"""Per-session "last seen" markers, so the session list can show an unread dot.

One small JSON file under the state root, written only by the persistent service. A session
counts as unread when the app reported activity after the moment a client last marked it
seen. A session the service has never listed gets a silent baseline first, so history from
before Neyvia looked at it is not shown as unread.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from .. import proofs_a_sessions as _proofs

_MAX_ENTRIES = 5000


def _epoch(value: Any) -> float | None:
    """ISO-8601 (or epoch) timestamp to seconds, None when it cannot be read."""
    if isinstance(value, (int, float)):
        return float(value) / 1000 if value > 10_000_000_000 else float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


class SeenStore:
    def __init__(self, root: Path):
        self.path = Path(root) / ".agent_control" / "connected_sessions_seen.json"
        self._lock = threading.RLock()
        self._sessions: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        rows = value.get("sessions") if isinstance(value, dict) else None
        return {str(key): dict(row) for key, row in rows.items() if isinstance(row, dict)} if isinstance(rows, dict) else {}

    def _save(self) -> None:
        if len(self._sessions) > _MAX_ENTRIES:
            keep = sorted(self._sessions.items(), key=lambda item: float(item[1].get("at") or 0), reverse=True)[:_MAX_ENTRIES]
            self._sessions = dict(keep)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".seen-", suffix=".tmp", dir=self.path.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                    json.dump({"version": 1, "sessions": self._sessions}, stream, separators=(",", ":"))
                os.replace(temporary, self.path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        except OSError:
            # An unread dot is a convenience; a full disk must not break the service.
            pass

    def get(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._sessions.get(session_id)
            return dict(row) if row else None

    def mark(self, session_id: str, seq: int | None, updated_at: str | None) -> dict[str, Any]:
        """Record that a client has seen everything up to ``seq`` at the app's ``updated_at``."""
        with self._lock:
            old = self._sessions.get(session_id) or {}
            row = {
                "seq": seq if seq is not None else old.get("seq"),
                "updatedAt": updated_at if updated_at is not None else old.get("updatedAt"),
                "at": time.time(),
            }
            self._sessions[session_id] = row
            self._save()
            return dict(row)

    def baseline(self, rows: Iterable[tuple[str, str | None]]) -> None:
        """Silently start tracking sessions this store has not seen yet (one write)."""
        with self._lock:
            changed = False
            for session_id, updated_at in rows:
                row = self._sessions.get(session_id)
                if row is None:
                    self._sessions[session_id] = {"seq": None, "updatedAt": updated_at, "at": time.time()}
                    changed = True
                elif row.get("updatedAt") is None and updated_at is not None:
                    row["updatedAt"] = updated_at
                    changed = True
            if changed:
                self._save()

    def unread(self, session_id: str, updated_at: str | None, latest_seq: int | None = None) -> bool:
        with self._lock:
            row = self._sessions.get(session_id)
        if row is None:
            _proofs.check_unread(row, updated_at, latest_seq, False)
            return False
        seen_seq = row.get("seq")
        if latest_seq is not None and isinstance(seen_seq, int) and latest_seq > seen_seq:
            _proofs.check_unread(row, updated_at, latest_seq, True)
            return True
        seen_at, current = _epoch(row.get("updatedAt")), _epoch(updated_at)
        result = seen_at is not None and current is not None and current > seen_at + 0.001
        _proofs.check_unread(row, updated_at, latest_seq, result)
        return result
