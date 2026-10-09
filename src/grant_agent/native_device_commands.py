"""Receipt-bound, human-authorized command queue for paired Neyvia devices.

The store is the canonical authority for paired-device side effects. Device
capabilities are declarations, not proof. Human approval is recorded against the
exact device/action/arguments and actor/session/run provenance, consumed once by
one command, and re-checked immediately before a device claim. A lost claim is
``uncertain`` and is never automatically replayed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .native_pairing import NativePairingStore


COMMAND_SCHEMA = "neyvia.device-command/v2"
CAPABILITY_SCHEMA = "neyvia.device-capabilities/v1"
APPROVAL_SCHEMA = "neyvia.device-command-approval/v1"

_ACTION_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_MAX_CAPABILITIES = 64
_MAX_ARGUMENT_BYTES = 16 * 1024
_MAX_RESULT_BYTES = 16 * 1024
_TERMINAL = {"succeeded", "failed", "rejected", "expired", "uncertain", "cancelled"}
_LATE_RECEIPT_UNCERTAINTY = {
    "claim-lost",
    "command-expired-after-claim",
    "capability-withdrawn-after-claim",
    "device-revoked-after-claim",
}
_SENSITIVE_KEY_MARKERS = {
    "authorization",
    "cookie",
    "credential",
    "password",
    "providersecret",
    "secret",
    "token",
    "apikey",
    "api_key",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat().replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _canonical_json(value: Any, *, maximum: int, label: str) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > maximum:
        raise ValueError(f"{label} exceeds {maximum} bytes")
    return encoded


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = re.sub(r"[^a-z0-9_]", "", str(raw_key).lower())
            if any(marker in key for marker in _SENSITIVE_KEY_MARKERS):
                return True
            if _contains_sensitive_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _idempotency_digest(value: str) -> str:
    normalized = str(value or "").strip()
    if not 8 <= len(normalized) <= 200:
        raise ValueError("idempotencyKey must contain 8-200 characters")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _identity(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not _IDENTITY_RE.fullmatch(normalized):
        raise ValueError(
            f"{label} must be a non-empty bounded identifier using letters, digits, . _ : / or -"
        )
    return normalized


def _prepare_request(
    action: str,
    arguments: dict[str, Any] | None,
) -> tuple[str, dict[str, Any], str, str]:
    normalized_action = str(action or "").strip().lower()
    if not _ACTION_RE.fullmatch(normalized_action):
        raise ValueError("action must be a bounded lowercase capability identifier")
    payload = dict(arguments or {})
    if _contains_sensitive_key(payload):
        raise ValueError("Device command arguments cannot contain credential/secret fields.")
    arguments_json = _canonical_json(
        payload, maximum=_MAX_ARGUMENT_BYTES, label="arguments"
    )
    request_hash = hashlib.sha256(
        f"{normalized_action}\0{arguments_json}".encode("utf-8")
    ).hexdigest()
    return normalized_action, payload, arguments_json, request_hash


class NativeDeviceCommandStore:
    """Durable, replay-resistant queue bound to explicit human authority."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        pairing = NativePairingStore(self.root)
        self.path = pairing.path
        self._initialize()

    @contextmanager
    def connection(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        ddl: str,
    ) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def _initialize(self) -> None:
        with self.connection(immediate=True) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS device_capabilities (
                    device_id TEXT PRIMARY KEY,
                    capabilities_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(device_id) REFERENCES paired_devices(device_id)
                );

                CREATE TABLE IF NOT EXISTS device_commands (
                    command_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    idempotency_hash TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    claim_id TEXT,
                    claimed_at TEXT,
                    claim_expires_at TEXT,
                    completed_at TEXT,
                    result_json TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    approval_id TEXT,
                    actor_id TEXT,
                    session_id TEXT,
                    run_id TEXT,
                    FOREIGN KEY(device_id) REFERENCES paired_devices(device_id),
                    UNIQUE(device_id, idempotency_hash)
                );

                CREATE TABLE IF NOT EXISTS device_command_approvals (
                    approval_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    decided_at TEXT,
                    decided_by TEXT,
                    decision_note TEXT,
                    consumed_at TEXT,
                    command_id TEXT,
                    FOREIGN KEY(device_id) REFERENCES paired_devices(device_id)
                );

                CREATE INDEX IF NOT EXISTS idx_device_commands_claim
                    ON device_commands(device_id, status, created_at);
                CREATE INDEX IF NOT EXISTS idx_device_commands_expiry
                    ON device_commands(status, expires_at, claim_expires_at);
                CREATE INDEX IF NOT EXISTS idx_device_command_approvals_status
                    ON device_command_approvals(device_id, status, expires_at);
                """
            )
            self._ensure_column(connection, "device_commands", "approval_id", "TEXT")
            self._ensure_column(connection, "device_commands", "actor_id", "TEXT")
            self._ensure_column(connection, "device_commands", "session_id", "TEXT")
            self._ensure_column(connection, "device_commands", "run_id", "TEXT")

    @staticmethod
    def _normalize_capabilities(values: list[str] | tuple[str, ...]) -> list[str]:
        if not isinstance(values, (list, tuple)):
            raise ValueError("capabilities must be an array")
        if len(values) > _MAX_CAPABILITIES:
            raise ValueError(f"capabilities cannot exceed {_MAX_CAPABILITIES} actions")
        result: list[str] = []
        for raw in values:
            action = str(raw or "").strip().lower()
            if not _ACTION_RE.fullmatch(action):
                raise ValueError(f"Invalid device capability: {action or 'missing'}")
            if action not in result:
                result.append(action)
        return result

    @staticmethod
    def _authenticate(
        connection: sqlite3.Connection,
        device_id: str,
        device_secret: str,
        required_scope: str = "device.commands",
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM paired_devices WHERE device_id = ?",
            (str(device_id),),
        ).fetchone()
        if row is None or row["revoked_at"]:
            raise PermissionError("Paired device is unknown or revoked.")
        supplied = hashlib.sha256(
            f"{row['secret_salt']}:{str(device_secret)}".encode("utf-8")
        ).hexdigest()
        if not hmac.compare_digest(supplied, row["secret_hash"]):
            raise PermissionError("Paired-device credential is invalid.")
        scopes = json.loads(row["scopes_json"])
        if required_scope and required_scope not in scopes:
            raise PermissionError(f"Paired device lacks required scope: {required_scope}")
        connection.execute(
            "UPDATE paired_devices SET last_seen_at = ? WHERE device_id = ?",
            (_iso(), str(device_id)),
        )
        return row

    @staticmethod
    def _device_row(connection: sqlite3.Connection, device_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM paired_devices WHERE device_id = ?",
            (str(device_id),),
        ).fetchone()
        if row is None:
            raise KeyError("Unknown paired device.")
        if row["revoked_at"]:
            raise ValueError("Paired device is revoked.")
        return row

    @staticmethod
    def _capabilities(connection: sqlite3.Connection, device_id: str) -> list[str]:
        row = connection.execute(
            "SELECT capabilities_json FROM device_capabilities WHERE device_id = ?",
            (str(device_id),),
        ).fetchone()
        return json.loads(row["capabilities_json"]) if row is not None else []

    def publish_capabilities(
        self,
        device_id: str,
        device_secret: str,
        capabilities: list[str],
    ) -> dict[str, Any]:
        normalized = self._normalize_capabilities(capabilities)
        updated_at = _iso()
        with self.connection(immediate=True) as connection:
            device = self._authenticate(connection, device_id, device_secret)
            previous = set(self._capabilities(connection, device_id))
            connection.execute(
                """
                INSERT INTO device_capabilities(device_id, capabilities_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    capabilities_json = excluded.capabilities_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(device_id),
                    json.dumps(normalized, separators=(",", ":")),
                    updated_at,
                ),
            )
            withdrawn = previous - set(normalized)
            if withdrawn:
                placeholders = ",".join("?" for _ in withdrawn)
                connection.execute(
                    f"""
                    UPDATE device_commands
                    SET status = 'rejected', completed_at = ?,
                        error_code = 'capability-withdrawn',
                        error_message = 'The paired app withdrew this capability before command claim.'
                    WHERE device_id = ? AND status = 'queued'
                      AND action IN ({placeholders})
                    """,
                    [updated_at, str(device_id), *sorted(withdrawn)],
                )
                connection.execute(
                    f"""
                    UPDATE device_commands
                    SET status = 'uncertain', completed_at = ?,
                        error_code = 'capability-withdrawn-after-claim',
                        error_message = 'The app withdrew this capability after claim; execution outcome is unknown.'
                    WHERE device_id = ? AND status = 'claimed'
                      AND action IN ({placeholders})
                    """,
                    [updated_at, str(device_id), *sorted(withdrawn)],
                )
        return {
            "schema": CAPABILITY_SCHEMA,
            "deviceId": str(device_id),
            "target": device["target"],
            "capabilities": normalized,
            "updatedAt": updated_at,
            "providerSecretsIncluded": False,
            "truthBoundary": (
                "These capabilities are declarations from the authenticated app. "
                "NEYVIA does not infer that an action executed until a command receipt is returned."
            ),
        }

    def request_approval(
        self,
        device_id: str,
        action: str,
        *,
        arguments: dict[str, Any] | None = None,
        actor_id: str,
        session_id: str,
        run_id: str,
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        normalized_action, _, arguments_json, request_hash = _prepare_request(
            action, arguments
        )
        actor = _identity(actor_id, "actorId")
        session = _identity(session_id, "sessionId")
        run = _identity(run_id, "runId")
        ttl = max(30, min(900, int(ttl_seconds)))
        requested = _now()
        expires = requested + timedelta(seconds=ttl)

        with self.connection(immediate=True) as connection:
            self._reconcile_locked(connection, device_id=str(device_id), now=requested)
            self._device_row(connection, device_id)
            if normalized_action not in self._capabilities(connection, device_id):
                raise ValueError(
                    f"Device has not advertised capability: {normalized_action}"
                )
            approval_id = f"approval_{uuid.uuid4().hex}"
            connection.execute(
                """
                INSERT INTO device_command_approvals(
                    approval_id, device_id, action, arguments_json, request_hash,
                    actor_id, session_id, run_id, requested_at, expires_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    approval_id,
                    str(device_id),
                    normalized_action,
                    arguments_json,
                    request_hash,
                    actor,
                    session,
                    run,
                    _iso(requested),
                    _iso(expires),
                ),
            )
            row = connection.execute(
                "SELECT * FROM device_command_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        return self._approval_receipt(row)

    def decide_approval(
        self,
        approval_id: str,
        *,
        decision: str,
        decided_by: str,
        human_confirmed: bool,
        note: str = "",
    ) -> dict[str, Any]:
        normalized = str(decision or "").strip().lower()
        if normalized not in {"approved", "denied"}:
            raise ValueError("decision must be approved or denied")
        approver = _identity(decided_by, "decidedBy")
        if human_confirmed is not True:
            raise PermissionError(
                "A device-command approval decision requires explicit human confirmation."
            )
        bounded_note = str(note or "").strip()[:500]
        now = _now()
        with self.connection(immediate=True) as connection:
            self._reconcile_locked(connection, now=now)
            row = connection.execute(
                "SELECT * FROM device_command_approvals WHERE approval_id = ?",
                (str(approval_id),),
            ).fetchone()
            if row is None:
                raise KeyError("Unknown device command approval.")
            if row["status"] == normalized:
                if row["decided_by"] == approver and (row["decision_note"] or "") == bounded_note:
                    return self._approval_receipt(row)
                raise ValueError(
                    f"Device command approval is already terminal as {row['status']}."
                )
            if row["status"] != "pending":
                raise ValueError(
                    f"Device command approval cannot be decided from state: {row['status']}"
                )
            if _parse(row["expires_at"]) <= now:
                self._reconcile_locked(connection, now=now)
                expired = connection.execute(
                    "SELECT * FROM device_command_approvals WHERE approval_id = ?",
                    (str(approval_id),),
                ).fetchone()
                return self._approval_receipt(expired)
            connection.execute(
                """
                UPDATE device_command_approvals
                SET status = ?, decided_at = ?, decided_by = ?, decision_note = ?
                WHERE approval_id = ? AND status = 'pending'
                """,
                (normalized, _iso(now), approver, bounded_note, str(approval_id)),
            )
            updated = connection.execute(
                "SELECT * FROM device_command_approvals WHERE approval_id = ?",
                (str(approval_id),),
            ).fetchone()
        return self._approval_receipt(updated)

    def get_approval(self, approval_id: str) -> dict[str, Any]:
        with self.connection(immediate=True) as connection:
            self._reconcile_locked(connection)
            row = connection.execute(
                "SELECT * FROM device_command_approvals WHERE approval_id = ?",
                (str(approval_id),),
            ).fetchone()
            if row is None:
                raise KeyError("Unknown device command approval.")
        return self._approval_receipt(row)

    def enqueue(
        self,
        device_id: str,
        action: str,
        *,
        arguments: dict[str, Any] | None = None,
        idempotency_key: str,
        approval_id: str,
        actor_id: str,
        session_id: str,
        run_id: str,
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        normalized_action, _, arguments_json, request_hash = _prepare_request(
            action, arguments
        )
        idempotency_hash = _idempotency_digest(idempotency_key)
        actor = _identity(actor_id, "actorId")
        session = _identity(session_id, "sessionId")
        run = _identity(run_id, "runId")
        approval_key = str(approval_id or "").strip()
        if not approval_key:
            raise PermissionError("approvalId is required for paired-device commands.")
        ttl = max(30, min(3600, int(ttl_seconds)))
        created = _now()

        with self.connection(immediate=True) as connection:
            self._reconcile_locked(connection, device_id=str(device_id), now=created)
            self._device_row(connection, device_id)
            capabilities = self._capabilities(connection, device_id)
            if normalized_action not in capabilities:
                raise ValueError(
                    f"Device has not advertised capability: {normalized_action}"
                )

            existing = connection.execute(
                """
                SELECT * FROM device_commands
                WHERE device_id = ? AND idempotency_hash = ?
                """,
                (str(device_id), idempotency_hash),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise ValueError(
                        "idempotencyKey was already used for a different device command"
                    )
                expected = (approval_key, actor, session, run)
                observed = (
                    str(existing["approval_id"] or ""),
                    str(existing["actor_id"] or ""),
                    str(existing["session_id"] or ""),
                    str(existing["run_id"] or ""),
                )
                if observed != expected:
                    raise ValueError(
                        "idempotencyKey was already bound to different approval/provenance"
                    )
                return self._receipt(existing)

            approval = connection.execute(
                "SELECT * FROM device_command_approvals WHERE approval_id = ?",
                (approval_key,),
            ).fetchone()
            if approval is None:
                raise PermissionError("Unknown device command approval.")
            if approval["status"] != "approved":
                raise PermissionError(
                    f"Device command approval is not executable: {approval['status']}"
                )
            if _parse(approval["expires_at"]) <= created:
                self._reconcile_locked(connection, now=created)
                raise PermissionError("Device command approval expired.")
            expected = (
                str(device_id),
                normalized_action,
                request_hash,
                actor,
                session,
                run,
            )
            observed = (
                approval["device_id"],
                approval["action"],
                approval["request_hash"],
                approval["actor_id"],
                approval["session_id"],
                approval["run_id"],
            )
            if observed != expected:
                raise PermissionError(
                    "Approval does not match the exact device command and actor/session/run context."
                )
            if approval["command_id"] or approval["consumed_at"]:
                raise PermissionError("Device command approval was already consumed.")

            expires = min(
                created + timedelta(seconds=ttl),
                _parse(approval["expires_at"]),
            )
            command_id = f"command_{uuid.uuid4().hex}"
            connection.execute(
                """
                INSERT INTO device_commands(
                    command_id, device_id, action, arguments_json, idempotency_hash,
                    request_hash, created_at, expires_at, status, approval_id,
                    actor_id, session_id, run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?)
                """,
                (
                    command_id,
                    str(device_id),
                    normalized_action,
                    arguments_json,
                    idempotency_hash,
                    request_hash,
                    _iso(created),
                    _iso(expires),
                    approval_key,
                    actor,
                    session,
                    run,
                ),
            )
            consumed = connection.execute(
                """
                UPDATE device_command_approvals
                SET status = 'consumed', consumed_at = ?, command_id = ?
                WHERE approval_id = ? AND status = 'approved'
                  AND consumed_at IS NULL AND command_id IS NULL
                """,
                (_iso(created), command_id, approval_key),
            )
            if consumed.rowcount != 1:
                raise PermissionError(
                    "Device command approval could not be consumed exactly once."
                )
            row = connection.execute(
                "SELECT * FROM device_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
        return self._receipt(row)

    @staticmethod
    def _authorization_valid_locked(
        connection: sqlite3.Connection,
        command: sqlite3.Row,
        *,
        now: datetime,
    ) -> tuple[bool, str]:
        approval_id = str(command["approval_id"] or "")
        if not approval_id:
            return False, "missing-approval"
        approval = connection.execute(
            "SELECT * FROM device_command_approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        if approval is None:
            return False, "approval-missing"
        if approval["status"] != "consumed" or approval["command_id"] != command["command_id"]:
            return False, "approval-not-bound"
        if not approval["decided_by"] or not approval["decided_at"]:
            return False, "approval-decision-missing"
        if _parse(approval["expires_at"]) <= now:
            return False, "approval-expired"
        if _parse(command["expires_at"]) > _parse(approval["expires_at"]):
            return False, "command-outlives-approval"
        expected = (
            approval["device_id"],
            approval["action"],
            approval["request_hash"],
            approval["actor_id"],
            approval["session_id"],
            approval["run_id"],
        )
        observed = (
            command["device_id"],
            command["action"],
            command["request_hash"],
            command["actor_id"],
            command["session_id"],
            command["run_id"],
        )
        if observed != expected:
            return False, "approval-command-mismatch"
        return True, ""

    def claim(
        self,
        device_id: str,
        device_secret: str,
        *,
        lease_seconds: int = 45,
    ) -> dict[str, Any] | None:
        lease = max(15, min(300, int(lease_seconds)))
        now = _now()
        with self.connection(immediate=True) as connection:
            self._authenticate(connection, device_id, device_secret)
            self._reconcile_locked(connection, device_id=str(device_id), now=now)
            while True:
                row = connection.execute(
                    """
                    SELECT * FROM device_commands
                    WHERE device_id = ? AND status = 'queued'
                    ORDER BY created_at ASC, command_id ASC
                    LIMIT 1
                    """,
                    (str(device_id),),
                ).fetchone()
                if row is None:
                    return None
                expires_at = _parse(row["expires_at"])
                if expires_at <= now:
                    self._reconcile_locked(connection, device_id=str(device_id), now=now)
                    continue
                authorized, reason = self._authorization_valid_locked(
                    connection, row, now=now
                )
                if not authorized:
                    connection.execute(
                        """
                        UPDATE device_commands
                        SET status = 'rejected', completed_at = ?,
                            error_code = 'authorization-invalid',
                            error_message = ?
                        WHERE command_id = ? AND status = 'queued'
                        """,
                        (
                            _iso(now),
                            f"Final execution gate rejected the command: {reason}.",
                            row["command_id"],
                        ),
                    )
                    continue
                claim_id = f"claim_{secrets.token_hex(16)}"
                claim_expires = min(now + timedelta(seconds=lease), expires_at)
                changed = connection.execute(
                    """
                    UPDATE device_commands
                    SET status = 'claimed', claim_id = ?, claimed_at = ?, claim_expires_at = ?
                    WHERE command_id = ? AND status = 'queued'
                    """,
                    (claim_id, _iso(now), _iso(claim_expires), row["command_id"]),
                )
                if changed.rowcount != 1:
                    continue
                claimed = connection.execute(
                    "SELECT * FROM device_commands WHERE command_id = ?",
                    (row["command_id"],),
                ).fetchone()
                return self._receipt(claimed, include_arguments=True)

    def cancel(
        self,
        command_id: str,
        *,
        actor_id: str,
        session_id: str,
        run_id: str,
        cancelled_by: str,
        human_confirmed: bool,
        reason: str = "",
    ) -> dict[str, Any]:
        actor = _identity(actor_id, "actorId")
        session = _identity(session_id, "sessionId")
        run = _identity(run_id, "runId")
        operator = _identity(cancelled_by, "cancelledBy")
        if human_confirmed is not True:
            raise PermissionError("Command cancellation requires explicit human confirmation.")
        bounded_reason = str(reason or "").strip()[:500]
        with self.connection(immediate=True) as connection:
            self._reconcile_locked(connection)
            row = connection.execute(
                "SELECT * FROM device_commands WHERE command_id = ?",
                (str(command_id),),
            ).fetchone()
            if row is None:
                raise KeyError("Unknown device command.")
            if (
                row["actor_id"] != actor
                or row["session_id"] != session
                or row["run_id"] != run
            ):
                raise PermissionError(
                    "Cancellation context does not match the command actor/session/run."
                )
            if row["status"] == "cancelled":
                return self._receipt(row)
            if row["status"] != "queued":
                raise ValueError(
                    f"Device command can only be cancelled before claim; current state: {row['status']}"
                )
            connection.execute(
                """
                UPDATE device_commands
                SET status = 'cancelled', completed_at = ?,
                    error_code = 'cancelled-by-human',
                    error_message = ?
                WHERE command_id = ? AND status = 'queued'
                """,
                (
                    _iso(),
                    (
                        f"Cancelled by {operator}: {bounded_reason}"
                        if bounded_reason
                        else f"Cancelled by {operator} before device claim."
                    ),
                    str(command_id),
                ),
            )
            updated = connection.execute(
                "SELECT * FROM device_commands WHERE command_id = ?",
                (str(command_id),),
            ).fetchone()
        return self._receipt(updated)

    def complete(
        self,
        device_id: str,
        device_secret: str,
        command_id: str,
        claim_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error_code: str = "",
        error_message: str = "",
    ) -> dict[str, Any]:
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in {"succeeded", "failed", "rejected"}:
            raise ValueError("status must be succeeded, failed, or rejected")
        result_json = _canonical_json(
            dict(result or {}), maximum=_MAX_RESULT_BYTES, label="result"
        )
        bounded_code = str(error_code or "").strip()[:80]
        bounded_message = str(error_message or "").strip()[:500]
        if _contains_sensitive_key(result or {}):
            raise ValueError("Device command result cannot contain credential/secret fields.")

        with self.connection(immediate=True) as connection:
            self._authenticate(connection, device_id, device_secret)
            self._reconcile_locked(connection, device_id=str(device_id))
            row = connection.execute(
                """
                SELECT * FROM device_commands
                WHERE command_id = ? AND device_id = ?
                """,
                (str(command_id), str(device_id)),
            ).fetchone()
            if row is None:
                raise KeyError("Unknown device command.")
            late_receipt = (
                row["status"] == "uncertain"
                and row["error_code"] in _LATE_RECEIPT_UNCERTAINTY
                and hmac.compare_digest(str(row["claim_id"] or ""), str(claim_id or ""))
            )
            if row["status"] in _TERMINAL and not late_receipt:
                if (
                    row["status"] == normalized_status
                    and (row["result_json"] or "{}") == result_json
                    and (row["error_code"] or "") == bounded_code
                    and (row["error_message"] or "") == bounded_message
                ):
                    return self._receipt(row)
                raise ValueError(
                    f"Device command is already terminal as {row['status']}."
                )
            if row["status"] != "claimed" and not late_receipt:
                raise ValueError(
                    f"Device command cannot complete from state: {row['status']}"
                )
            if not hmac.compare_digest(str(row["claim_id"] or ""), str(claim_id or "")):
                raise PermissionError("Device command claim does not match.")
            completed = _iso()
            connection.execute(
                """
                UPDATE device_commands
                SET status = ?, completed_at = ?, result_json = ?,
                    error_code = ?, error_message = ?
                WHERE command_id = ? AND device_id = ?
                  AND status IN ('claimed', 'uncertain')
                """,
                (
                    normalized_status,
                    completed,
                    result_json,
                    bounded_code,
                    bounded_message,
                    str(command_id),
                    str(device_id),
                ),
            )
            updated = connection.execute(
                "SELECT * FROM device_commands WHERE command_id = ?",
                (str(command_id),),
            ).fetchone()
        return self._receipt(updated)

    def get(self, command_id: str) -> dict[str, Any]:
        with self.connection(immediate=True) as connection:
            self._reconcile_locked(connection)
            row = connection.execute(
                "SELECT * FROM device_commands WHERE command_id = ?",
                (str(command_id),),
            ).fetchone()
            if row is None:
                raise KeyError("Unknown device command.")
        return self._receipt(row)

    def list(
        self,
        *,
        device_id: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        bounded = max(1, min(200, int(limit)))
        with self.connection(immediate=True) as connection:
            self._reconcile_locked(connection, device_id=str(device_id) or None)
            if device_id:
                rows = connection.execute(
                    """
                    SELECT * FROM device_commands
                    WHERE device_id = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (str(device_id), bounded),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM device_commands ORDER BY created_at DESC LIMIT ?",
                    (bounded,),
                ).fetchall()
        return [self._receipt(row) for row in rows]

    def _reconcile_locked(
        self,
        connection: sqlite3.Connection,
        *,
        device_id: str | None = None,
        now: datetime | None = None,
    ) -> None:
        current = now or _now()
        approval_clauses = ["status IN ('pending', 'approved')", "expires_at <= ?"]
        approval_params: list[Any] = [_iso(current)]
        if device_id:
            approval_clauses.append("device_id = ?")
            approval_params.append(str(device_id))
        connection.execute(
            f"""
            UPDATE device_command_approvals
            SET status = 'expired'
            WHERE {' AND '.join(approval_clauses)}
            """,
            approval_params,
        )

        clauses = ["status = 'queued'", "expires_at <= ?"]
        params: list[Any] = [_iso(current)]
        if device_id:
            clauses.append("device_id = ?")
            params.append(str(device_id))
        connection.execute(
            f"""
            UPDATE device_commands
            SET status = 'expired', completed_at = ?,
                error_code = 'command-expired',
                error_message = 'Command expired before the paired device claimed it.'
            WHERE {' AND '.join(clauses)}
            """,
            [_iso(current), *params],
        )

        clauses = ["status = 'claimed'", "expires_at <= ?"]
        params = [_iso(current)]
        if device_id:
            clauses.append("device_id = ?")
            params.append(str(device_id))
        connection.execute(
            f"""
            UPDATE device_commands
            SET status = 'uncertain', completed_at = ?,
                error_code = 'command-expired-after-claim',
                error_message = 'The command authority expired after claim without a receipt; execution outcome is unknown and automatic replay is disabled.'
            WHERE {' AND '.join(clauses)}
            """,
            [_iso(current), *params],
        )

        clauses = [
            "status = 'claimed'",
            "claim_expires_at IS NOT NULL",
            "claim_expires_at <= ?",
        ]
        params = [_iso(current)]
        if device_id:
            clauses.append("device_id = ?")
            params.append(str(device_id))
        connection.execute(
            f"""
            UPDATE device_commands
            SET status = 'uncertain', completed_at = ?,
                error_code = 'claim-lost',
                error_message = 'The device claim lease ended without a receipt; automatic replay is disabled.'
            WHERE {' AND '.join(clauses)}
            """,
            [_iso(current), *params],
        )

    @staticmethod
    def _approval_receipt(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema": APPROVAL_SCHEMA,
            "approvalId": row["approval_id"],
            "deviceId": row["device_id"],
            "action": row["action"],
            "arguments": json.loads(row["arguments_json"]),
            "requestHash": row["request_hash"],
            "actorId": row["actor_id"],
            "sessionId": row["session_id"],
            "runId": row["run_id"],
            "status": row["status"],
            "requestedAt": row["requested_at"],
            "expiresAt": row["expires_at"],
            "decidedAt": row["decided_at"],
            "decidedBy": row["decided_by"],
            "decisionNote": row["decision_note"],
            "consumedAt": row["consumed_at"],
            "commandId": row["command_id"],
            "humanIdentityCryptographicallyVerified": False,
            "truthBoundary": (
                "The server binds the decision to these exact transaction details and consumes "
                "an approval once. decidedBy/human confirmation are attestations from the trusted "
                "operator surface; this record does not cryptographically prove a person's identity."
            ),
        }

    @staticmethod
    def _receipt(row: sqlite3.Row, *, include_arguments: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": COMMAND_SCHEMA,
            "commandId": row["command_id"],
            "deviceId": row["device_id"],
            "action": row["action"],
            "status": row["status"],
            "approvalId": row["approval_id"],
            "actorId": row["actor_id"],
            "sessionId": row["session_id"],
            "runId": row["run_id"],
            "humanApprovalBound": bool(row["approval_id"]),
            "createdAt": row["created_at"],
            "expiresAt": row["expires_at"],
            "claimedAt": row["claimed_at"],
            "claimExpiresAt": row["claim_expires_at"],
            "completedAt": row["completed_at"],
            "errorCode": row["error_code"],
            "errorMessage": row["error_message"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "automaticRetry": False,
            "executionProven": row["status"] == "succeeded",
            "truthBoundary": (
                "Queued/claimed are control-plane states only. Claim is allowed only after a final "
                "server-side check that a single-use approval remains bound to the exact device, "
                "action, arguments and actor/session/run context. A side effect is proven only by "
                "an authenticated terminal device receipt; lost/expired claims are never replayed."
            ),
        }
        if row["status"] == "claimed":
            payload["claimId"] = row["claim_id"]
        if include_arguments:
            payload["arguments"] = json.loads(row["arguments_json"])
        from .proofs_d_native import check_command
        check_command(row, payload)
        return payload
