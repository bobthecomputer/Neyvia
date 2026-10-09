"""Durable recovery objects for ambiguous or failed operations.

Recovery objects deliberately separate an operation's known effects from its
unknown effects.  They are persisted before a repair is attempted, so a
process restart cannot turn an ambiguous mutation into an unsafe replay.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .durability import atomic_write_json


SCHEMA = "fluxio.recovery_object.v1"
REPAIR_SCHEMA = "fluxio.repair_ledger_entry.v1"
_STATUSES = {"open", "reconciling", "recovered", "closed", "blocked"}
_RETRY_SAFETY = {"safe", "unsafe", "requires_reconciliation", "unknown"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _rows(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Recovery collections must be lists")
    result: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("Recovery collection entries must be objects")
        result.append(dict(row))
    return result


@dataclass
class RecoveryObject:
    """A self-contained record of a failed operation and its safe next steps."""

    recovery_id: str
    failed_operation: dict[str, Any]
    confirmed_steps: list[dict[str, Any]] = field(default_factory=list)
    uncertain_effects: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    retry_safety: str = "requires_reconciliation"
    available_recovery_paths: list[dict[str, Any]] = field(default_factory=list)
    required_authority: list[str] = field(default_factory=list)
    status: str = "open"
    repair_ledger: list[dict[str, Any]] = field(default_factory=list)
    operation_id: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    lineage: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.recovery_id.strip() or len(self.recovery_id) > 160:
            raise ValueError("recovery_id must contain 1-160 characters")
        if not isinstance(self.failed_operation, dict) or not self.failed_operation:
            raise ValueError("failed_operation must be a non-empty object")
        if self.status not in _STATUSES:
            raise ValueError(f"Unsupported recovery status: {self.status}")
        if self.retry_safety not in _RETRY_SAFETY:
            raise ValueError(f"Unsupported retry safety: {self.retry_safety}")
        self.confirmed_steps = _rows(self.confirmed_steps)
        self.uncertain_effects = _rows(self.uncertain_effects)
        self.evidence = _rows(self.evidence)
        self.available_recovery_paths = _rows(self.available_recovery_paths)
        self.repair_ledger = _rows(self.repair_ledger)
        self.required_authority = [str(item) for item in self.required_authority]

    @property
    def content_hash(self) -> str:
        value = self.to_dict(include_hash=False)
        return _digest(value)

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema": SCHEMA,
            "recoveryId": self.recovery_id,
            "operationId": self.operation_id,
            "failedOperation": self.failed_operation,
            "confirmedSteps": self.confirmed_steps,
            "uncertainEffects": self.uncertain_effects,
            "evidence": self.evidence,
            "retrySafety": self.retry_safety,
            "availableRecoveryPaths": self.available_recovery_paths,
            "requiredAuthority": self.required_authority,
            "status": self.status,
            "repairLedger": self.repair_ledger,
            "lineage": self.lineage,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }
        if include_hash:
            value["contentHash"] = _digest(value)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RecoveryObject":
        if value.get("schema") != SCHEMA:
            raise ValueError("Unsupported recovery object schema")
        obj = cls(
            recovery_id=str(value.get("recoveryId") or ""),
            operation_id=str(value["operationId"]) if value.get("operationId") is not None else None,
            failed_operation=dict(value.get("failedOperation") or {}),
            confirmed_steps=_rows(value.get("confirmedSteps")),
            uncertain_effects=_rows(value.get("uncertainEffects")),
            evidence=_rows(value.get("evidence")),
            retry_safety=str(value.get("retrySafety") or "unknown"),
            available_recovery_paths=_rows(value.get("availableRecoveryPaths")),
            required_authority=list(value.get("requiredAuthority") or []),
            status=str(value.get("status") or "open"),
            repair_ledger=_rows(value.get("repairLedger")),
            lineage=dict(value.get("lineage") or {}),
            created_at=str(value.get("createdAt") or _now()),
            updated_at=str(value.get("updatedAt") or _now()),
        )
        expected = value.get("contentHash")
        if expected is not None and expected != obj.content_hash:
            raise ValueError("Recovery object content hash mismatch")
        return obj

    def add_evidence(self, kind: str, *, detail: str = "", path: str = "", sha256: str = "", **metadata: Any) -> dict[str, Any]:
        row = {"evidenceId": f"ev_{uuid.uuid4().hex[:12]}", "kind": str(kind), "detail": str(detail), "path": str(path), "sha256": str(sha256), "observedAt": _now(), **metadata}
        self.evidence.append(row)
        self.updated_at = _now()
        return row

    def append_repair(self, *, diagnosis: str, mechanism_changed: str, proof: Mapping[str, Any] | None = None, recurrence_applicability: str = "", outcome: str = "pending", failure_signature: str = "") -> dict[str, Any]:
        if not diagnosis.strip() or not mechanism_changed.strip():
            raise ValueError("Repair diagnosis and mechanism_changed are required")
        entry = {"schema": REPAIR_SCHEMA, "repairId": f"repair_{uuid.uuid4().hex[:12]}", "failureSignature": failure_signature, "diagnosis": diagnosis, "mechanismChanged": mechanism_changed, "regressionProof": dict(proof or {}), "recurrenceApplicability": recurrence_applicability, "outcome": outcome, "recordedAt": _now()}
        self.repair_ledger.append(entry)
        self.updated_at = _now()
        return entry

    def transition(self, status: str, *, note: str = "") -> None:
        if status not in _STATUSES:
            raise ValueError(f"Unsupported recovery status: {status}")
        self.status = status
        if note:
            self.lineage.setdefault("transitionNotes", []).append({"status": status, "note": note, "at": _now()})
        self.updated_at = _now()


class RecoveryObjectStore:
    """Atomic, process-safe-enough persistence for recovery objects."""

    def __init__(self, root: Path, scope: str = "default") -> None:
        if not str(scope).strip():
            raise ValueError("scope is required")
        self.base = Path(root) / ".agent_control" / "recovery_objects" / _digest(scope)[:24]
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, recovery_id: str) -> Path:
        if not recovery_id or len(recovery_id) > 160:
            raise ValueError("recovery_id must contain 1-160 characters")
        return self.base / f"{_digest(recovery_id)}.json"

    def save(self, recovery: RecoveryObject) -> Path:
        path = self._path(recovery.recovery_id)
        atomic_write_json(path, recovery.to_dict())
        return path

    def create(self, failed_operation: Mapping[str, Any], **kwargs: Any) -> RecoveryObject:
        recovery = RecoveryObject(recovery_id=str(kwargs.pop("recovery_id", "") or f"recovery_{uuid.uuid4().hex[:12]}"), failed_operation=dict(failed_operation), **kwargs)
        self.save(recovery)
        return recovery

    def load(self, recovery_id: str) -> RecoveryObject:
        path = self._path(recovery_id)
        if not path.exists():
            raise FileNotFoundError(path)
        return RecoveryObject.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def update(self, recovery_id: str, **changes: Any) -> RecoveryObject:
        recovery = self.load(recovery_id)
        for key, value in changes.items():
            field_name = {"retrySafety": "retry_safety", "requiredAuthority": "required_authority", "availableRecoveryPaths": "available_recovery_paths", "uncertainEffects": "uncertain_effects", "confirmedSteps": "confirmed_steps"}.get(key, key)
            if not hasattr(recovery, field_name):
                raise ValueError(f"Unknown recovery field: {key}")
            setattr(recovery, field_name, value)
        recovery.__post_init__()
        recovery.updated_at = _now()
        self.save(recovery)
        return recovery

    def list(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.base.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if status and value.get("status") != status:
                    continue
                rows.append({key: value.get(key) for key in ("recoveryId", "operationId", "status", "retrySafety", "updatedAt", "contentHash")})
            except (OSError, ValueError, TypeError):
                rows.append({"status": "unreadable", "path": str(path)})
            if len(rows) >= max(1, min(int(limit), 200)):
                break
        return rows

