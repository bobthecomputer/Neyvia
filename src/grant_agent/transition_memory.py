"""Positive, scope-bound executable transitions backed by immutable journey receipts.

Only successful observed effects may be learned. Retrieval does not confer authority:
replay rechecks scope, expiry, provenance and live preconditions before execution.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


@contextmanager
def locked(path: Path):
    """Serialize readers/writers across threads and local processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCKS_GUARD:
        mutex = _LOCKS.setdefault(str(path.resolve()), threading.RLock())
    with mutex, path.with_suffix(path.suffix + ".lock").open("a+b") as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(canonical(value))
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def checked_receipt(value: dict) -> bool:
    if value.get("status") != "completed":
        return False
    checks = value.get("checks")
    if isinstance(checks, list) and checks:
        return all(isinstance(check, dict) and check.get("passed") is True for check in checks)
    validation = value.get("validation", {})
    return validation.get("schema") is True and validation.get("semantic") is True


class TransitionStore:
    MAX_ROWS = 2000

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.path = self.root / ".neyvia" / "efficiency" / "transitions.json"

    def _receipt(self, reference: dict, effect: dict, operation: dict | None = None) -> dict:
        raw_path = reference.get("receiptPath") or reference.get("path")
        if not raw_path:
            raise ValueError("A persisted source receipt is required.")
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.root / path
        path = path.resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ValueError("Source receipt must exist inside the selected workspace.")
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Source receipt exceeds the 2 MiB trust boundary.")
        raw = path.read_bytes()
        value = json.loads(raw)
        if not checked_receipt(value) or value.get("effect") != effect:
            raise ValueError("Source receipt must prove the completed, checked effect.")
        if operation is not None and value.get("operation") != operation:
            raise ValueError("Source receipt operation does not match learned operation.")
        expected_hash = reference.get("sha256")
        actual_hash = hashlib.sha256(raw).hexdigest()
        if expected_hash and expected_hash != actual_hash:
            raise ValueError("Source receipt changed.")
        return {"receiptPath": str(path), "sha256": actual_hash,
                "source": value.get("source", "observed-journey")}

    def _eligible(self, row: dict) -> bool:
        if row.get("trust") != "verified" or row.get("expiresAt", 0) <= time.time():
            return False
        if row.get("scope", {}).get("workspace") != str(self.root):
            return False
        try:
            self._receipt(row["provenance"], row["effect"], row["operation"])
            admission_path = Path(row["provenance"]["admissionPath"]).resolve()
            if not admission_path.is_relative_to(self.root):
                return False
            raw = admission_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != row["provenance"]["admissionSha256"]:
                return False
            admission = json.loads(raw)
            authority = {key: value for key, value in row.items() if key != "provenance"}
            if admission.get("row") != authority or admission.get("source") != {
                    key: value for key, value in row["provenance"].items() if not key.startswith("admission")}:
                return False
        except (OSError, ValueError, KeyError, TypeError):
            return False
        return True

    def learn(self, goal: dict, preconditions: dict, operation: dict, effect: dict,
              failure: dict, receipt: dict, scope: dict, ttl_seconds: float = 86400,
              trust: str = "verified") -> dict:
        if not all(isinstance(item, dict) for item in (goal, preconditions, operation, effect, failure, receipt, scope)):
            raise ValueError("Transitions require typed goal, preconditions, operation, effect, failure, receipt and scope objects.")
        if not goal.get("type") or not operation.get("type") or not failure.get("type"):
            raise ValueError("Goal, operation and failure require explicit type tags.")
        if scope.get("workspace") != str(self.root) or not math.isfinite(ttl_seconds) or ttl_seconds <= 0 or trust != "verified":
            raise ValueError("Learning requires exact workspace scope, positive expiry and verified trust.")
        provenance = self._receipt(receipt, effect, operation)
        now = time.time()
        row = {"id": uuid.uuid4().hex, "version": 1, "goal": goal, "preconditions": preconditions,
               "operation": operation, "effect": effect, "failure": failure, "scope": scope,
               "trust": trust, "createdAt": now, "expiresAt": now + min(ttl_seconds, 30 * 86400),
               "provenance": provenance}
        source_value = read_json(Path(provenance["receiptPath"]), {})
        for field, value in (("goal", goal), ("preconditions", preconditions), ("scope", scope), ("failure", failure)):
            if field in source_value and source_value[field] != value:
                raise ValueError("Source receipt authority does not match learned " + field + ".")
        # Serialization also rejects NaN and unsupported opaque values.
        canonical(row)
        admission_path = self.path.parent / "admissions" / (row["id"] + ".json")
        admission = {"version": 1, "row": {key: value for key, value in row.items() if key != "provenance"},
                     "source": dict(provenance)}
        atomic_json(admission_path, admission)
        provenance.update({"admissionPath": str(admission_path), "admissionSha256": digest(admission)})
        with locked(self.path):
            rows = read_json(self.path, [])
            rows = [item for item in rows if self._eligible(item)]
            rows.append(row)
            atomic_json(self.path, rows[-self.MAX_ROWS:])
        return row

    def lookup(self, goal: dict, preconditions: dict, scope: dict) -> dict:
        with locked(self.path):
            rows = read_json(self.path, [])
        candidates = [row for row in rows if row.get("goal") == goal and row.get("preconditions") == preconditions
                      and row.get("scope") == scope and row.get("trust") == "verified"
                      and row.get("expiresAt", 0) > time.time()]
        matches = [row for row in candidates if self._eligible(row)]
        if len(matches) != len(candidates):
            return {"status": "conflict", "rows": candidates, "reason": "provenance-or-authority-changed"}
        if not matches:
            return {"status": "missing", "rows": []}
        effects = {digest(row["effect"]) for row in matches}
        operations = {digest(row["operation"]) for row in matches}
        if len(effects) > 1 or len(operations) > 1:
            return {"status": "conflict", "rows": matches}
        return {"status": "match", "row": matches[-1], "rows": matches}

    def rows(self) -> list[dict]:
        """Return only current rows with intact successful source receipts."""
        with locked(self.path):
            rows = read_json(self.path, [])
        return [row for row in rows if self._eligible(row)]

    def get(self, row_id: str) -> dict | None:
        return next((row for row in self.rows() if row["id"] == row_id), None)

    def replay(self, row: dict, execute, observe, scope: dict, preconditions: dict) -> dict:
        if not callable(execute) or not callable(observe):
            raise ValueError("Replay requires an executor and an independent live observer.")
        with locked(self.path):
            known = next((item for item in read_json(self.path, []) if item.get("id") == row.get("id")), None)
        if known != row or not self._eligible(row) or row["scope"] != scope or row["preconditions"] != preconditions:
            raise ValueError("Transition is stale, untrusted, changed or outside the current authority scope.")
        steps = row["operation"].get("steps") if row["operation"].get("type") == "sequence" else None
        if steps is None:
            steps = [{"operation": row["operation"], "preconditions": row["preconditions"], "effect": row["effect"]}]
        outputs = []
        for step in steps:
            # Scope includes the caller's current authority grant. The caller must
            # still authorize each typed operation in execute.
            if not self._eligible(row) or observe() != step["preconditions"]:
                raise ValueError("Live preconditions changed; transition escalation required.")
            output = execute(step["operation"])
            observed = observe()
            if not isinstance(observed, dict) or any(observed.get(key) != value for key, value in step["effect"].items()):
                raise ValueError("Observed effect disagrees; transition escalation required.")
            outputs.append(output)
        effect = observe()
        if any(effect.get(key) != value for key, value in row["effect"].items()):
            raise ValueError("Final composite effect changed; transition escalation required.")
        receipt_path = self.path.parent / "replays" / (uuid.uuid4().hex + ".json")
        receipt = {"status": "completed", "operation": row["operation"], "effect": effect,
                   "preconditions": preconditions, "scope": scope, "goal": row["goal"],
                   "checks": [{"passed": True, "kind": "independent-live-preconditions-and-effects"}],
                   "transitionId": row["id"], "source": row["provenance"], "outputs": outputs,
                   "receiptPath": str(receipt_path)}
        atomic_json(receipt_path, receipt)
        return receipt

    def compose(self, rows: list[dict], goal: dict, receipt: dict, scope: dict) -> dict:
        if len(rows) < 2:
            raise ValueError("A composite requires at least two successful transitions.")
        with locked(self.path):
            known = read_json(self.path, [])
        if any(row not in known or not self._eligible(row) or row["scope"] != scope for row in rows):
            raise ValueError("Composite members must be verified transitions in the same scope.")
        if any(left["effect"] != right["preconditions"] for left, right in zip(rows, rows[1:])):
            raise ValueError("Composite effect/precondition chain does not match exactly.")
        operation = {"type": "sequence", "steps": [
            {"operation": row["operation"], "preconditions": row["preconditions"], "effect": row["effect"]}
            for row in rows]}
        return self.learn(goal, rows[0]["preconditions"], operation, rows[-1]["effect"],
                          {"type": "escalate", "reason": "precondition-or-effect-disagreement"}, receipt, scope,
                          ttl_seconds=min(row["expiresAt"] - time.time() for row in rows))
