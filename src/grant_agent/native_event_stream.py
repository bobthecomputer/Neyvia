"""Append-only, hash-chained event stream for Neyvia Native."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO


EVENT_SCHEMA = "neyvia.native-event/v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class NativeEventStream:
    def __init__(
        self,
        root: Path,
        run_id: str,
        *,
        output: TextIO | None = None,
    ) -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.path = (
            self.root
            / ".agent_control"
            / "neyvia_agent"
            / "events"
            / f"{run_id}.jsonl"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.output = output
        self._lock = threading.Lock()
        self._sequence = 0
        self._previous_hash = "0" * 64
        self._recover_tail()

    def _recover_tail(self) -> None:
        if not self.path.is_file():
            return
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        if not lines:
            return
        try:
            tail = json.loads(lines[-1])
        except json.JSONDecodeError:
            return
        self._sequence = int(tail.get("sequence") or len(lines))
        self._previous_hash = str(tail.get("eventHash") or self._previous_hash)

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        parent_event_id: str = "",
        phase: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            sequence = self._sequence + 1
            event = {
                "schema": EVENT_SCHEMA,
                "runId": self.run_id,
                "eventId": f"{self.run_id}:{sequence}",
                "sequence": sequence,
                "type": str(event_type or "event"),
                "phase": str(phase or ""),
                "parentEventId": str(parent_event_id or ""),
                "timestamp": _utc_now(),
                "payload": dict(payload or {}),
                "previousHash": self._previous_hash,
            }
            event["eventHash"] = hashlib.sha256(_canonical(event)).hexdigest()
            from .proofs_d_native import check_event, require
            check_event(event, sequence, self._previous_hash)
            line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            descriptor = os.open(
                self.path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_BINARY", 0),
                0o600,
            )
            try:
                offset = os.lseek(descriptor, 0, os.SEEK_END)
                encoded = (line + "\n").encode("utf-8")
                written = 0
                while written < len(encoded):
                    count = os.write(descriptor, encoded[written:])
                    require(count > 0, "native.events.append", "event append made no progress")
                    written += count
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            with self.path.open("rb") as persisted:
                persisted.seek(offset)
                require(persisted.read(len(encoded)) == encoded, "native.events.append", "durable event differs from emitted event")
            self._sequence = sequence
            self._previous_hash = event["eventHash"]
            if self.output is not None:
                self.output.write(line + "\n")
                self.output.flush()
            return event

    def verify(self) -> dict[str, Any]:
        previous = "0" * 64
        count = 0
        failures: list[str] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return {
                "valid": False,
                "events": 0,
                "failures": [str(exc)],
                "path": str(self.path),
            }
        for index, line in enumerate(lines, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                failures.append(f"line {index}: invalid JSON")
                continue
            supplied_hash = str(event.pop("eventHash", ""))
            expected_hash = hashlib.sha256(_canonical(event)).hexdigest()
            if supplied_hash != expected_hash:
                failures.append(f"line {index}: event hash mismatch")
            if event.get("previousHash") != previous:
                failures.append(f"line {index}: chain mismatch")
            if int(event.get("sequence") or 0) != index:
                failures.append(f"line {index}: sequence mismatch")
            previous = supplied_hash
            count += 1
        return {
            "schema": "neyvia.native-event-stream-verification/v1",
            "valid": not failures,
            "events": count,
            "lastHash": previous,
            "failures": failures,
            "path": str(self.path),
        }
