"""Verify-only operator authority for paired-device command approvals.

The canonical device-command lifecycle remains NativeDeviceCommandStore. This
adapter adds one gate for the Native RPC runtime: an approval that grants a
paired-device side effect must carry an Ed25519 signature over the exact,
server-prepared transaction. Only the public verifier is loaded; the signer
private key remains outside the workspace and this process.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .native_device_commands import NativeDeviceCommandStore, _iso, _parse


OPERATOR_DECISION_SCHEMA = "neyvia.device-command-operator-decision/v1"
OPERATOR_DECISION_PAYLOAD_SCHEMA = "neyvia.device-command-operator-decision-payload/v1"
_PURPOSE = "paired-device-command-authorization"
_MAX_ENVELOPE_BYTES = 32 * 1024
_CLOCK_SKEW = timedelta(seconds=60)
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_KEY_ID_RE = re.compile(r"^sha256:[a-f0-9]{64}$")


def _json_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("operator decision must be canonical JSON") from exc
    if len(encoded) > _MAX_ENVELOPE_BYTES:
        raise ValueError(f"operator decision exceeds {_MAX_ENVELOPE_BYTES} bytes")
    return encoded


def _same_json(left: Any, right: Any) -> bool:
    """Type-strict JSON equality for what-you-see-is-what-you-sign."""

    return hmac.compare_digest(_json_bytes(left), _json_bytes(right))


def _identity(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not _IDENTITY_RE.fullmatch(normalized):
        raise ValueError(
            f"{label} must be a non-empty bounded identifier using letters, digits, . _ : / or -"
        )
    return normalized


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("operator decision timestamp must include a timezone")
    return value.astimezone(timezone.utc)


def _parse_utc(value: object, label: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    return _utc(parsed)


class OperatorDecisionVerifier:
    """Pinned Ed25519 public verifier provisioned outside the workspace."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        public_key_path: str | Path | None = None,
        key_id: str | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        raw_path = str(
            public_key_path
            or os.environ.get("NEYVIA_DEVICE_OPERATOR_PUBLIC_KEY_PATH")
            or ""
        ).strip()
        raw_key_id = str(
            key_id or os.environ.get("NEYVIA_DEVICE_OPERATOR_KEY_ID") or ""
        ).strip().lower()

        self.public_key_path: Path | None = None
        self.key_id = ""
        self.public_key: Ed25519PublicKey | None = None

        if not raw_path and not raw_key_id:
            return
        if not raw_path or not raw_key_id:
            raise ValueError(
                "Both NEYVIA_DEVICE_OPERATOR_PUBLIC_KEY_PATH and "
                "NEYVIA_DEVICE_OPERATOR_KEY_ID are required together."
            )
        if not _KEY_ID_RE.fullmatch(raw_key_id):
            raise ValueError(
                "device operator key id must be sha256:<64 lowercase hex characters>"
            )

        candidate = Path(raw_path)
        if not candidate.is_absolute():
            raise ValueError("device operator public key path must be absolute")
        if candidate.is_symlink():
            raise ValueError("device operator public key path cannot be a symlink")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise ValueError("device operator public key path is unavailable") from exc
        if not resolved.is_file():
            raise ValueError("device operator public key path must be a regular file")
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError:
            pass
        else:
            raise ValueError(
                "device operator public key must be provisioned outside the mutable workspace"
            )

        try:
            loaded = serialization.load_pem_public_key(resolved.read_bytes())
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError("device operator public key is not valid PEM") from exc
        if not isinstance(loaded, Ed25519PublicKey):
            raise ValueError("device operator public key must be Ed25519")

        raw = loaded.public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        fingerprint = f"sha256:{hashlib.sha256(raw).hexdigest()}"
        if not hmac.compare_digest(fingerprint, raw_key_id):
            raise ValueError(
                "device operator public key fingerprint does not match configured key id"
            )

        self.public_key_path = resolved
        self.key_id = fingerprint
        self.public_key = loaded

    @property
    def ready(self) -> bool:
        return self.public_key is not None

    def status(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "algorithm": "ed25519" if self.ready else None,
            "keyId": self.key_id or None,
            "publicKeyPinnedOutsideWorkspace": bool(self.public_key_path),
            "privateKeyLoaded": False,
            "truthBoundary": (
                "Ready means this process can verify the configured external "
                "operator key. It does not prove biometric presence, physical "
                "personhood, or native-phone execution."
            ),
        }

    @staticmethod
    def _expected_payload(
        approval: sqlite3.Row,
        *,
        key_id: str,
        decided_by: str,
        note: str,
    ) -> dict[str, Any]:
        return {
            "schema": OPERATOR_DECISION_PAYLOAD_SCHEMA,
            "purpose": _PURPOSE,
            "operatorAuthorityKeyId": key_id,
            "approvalId": approval["approval_id"],
            "deviceId": approval["device_id"],
            "action": approval["action"],
            "arguments": json.loads(approval["arguments_json"]),
            "requestHash": approval["request_hash"],
            "actorId": approval["actor_id"],
            "sessionId": approval["session_id"],
            "runId": approval["run_id"],
            "requestedAt": approval["requested_at"],
            "approvalExpiresAt": approval["expires_at"],
            "decision": "approved",
            "decidedBy": _identity(decided_by, "decidedBy"),
            "decisionNote": str(note or "").strip()[:500],
        }

    def verify_approval(
        self,
        envelope: dict[str, Any],
        approval: sqlite3.Row,
        *,
        decided_by: str,
        note: str,
        now: datetime,
        enforce_freshness: bool,
    ) -> dict[str, str]:
        if not self.ready or self.public_key is None:
            raise PermissionError(
                "Cryptographic device-operator verifier is not configured."
            )
        if not isinstance(envelope, dict):
            raise PermissionError("Signed operator decision must be an object.")
        if set(envelope) != {
            "schema",
            "algorithm",
            "keyId",
            "payload",
            "signature",
        }:
            raise PermissionError(
                "Signed operator decision contains missing or unknown fields."
            )
        if envelope.get("schema") != OPERATOR_DECISION_SCHEMA:
            raise PermissionError("Signed operator decision schema is invalid.")
        if envelope.get("algorithm") != "ed25519":
            raise PermissionError("Signed operator decision algorithm is invalid.")
        if not hmac.compare_digest(
            str(envelope.get("keyId") or "").lower(), self.key_id
        ):
            raise PermissionError("Signed operator decision key id is not trusted.")

        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            raise PermissionError("Signed operator decision payload must be an object.")
        expected = self._expected_payload(
            approval,
            key_id=self.key_id,
            decided_by=decided_by,
            note=note,
        )
        if set(payload) != set(expected) | {"issuedAt"}:
            raise PermissionError(
                "Signed operator decision payload contains missing or unknown fields."
            )

        payload_bytes = _json_bytes(payload)
        signature_text = str(envelope.get("signature") or "").strip()
        try:
            signature = base64.b64decode(signature_text, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise PermissionError(
                "Signed operator decision signature is not valid base64."
            ) from exc
        if len(signature) != 64:
            raise PermissionError("Signed operator decision signature length is invalid.")
        try:
            self.public_key.verify(signature, payload_bytes)
        except InvalidSignature as exc:
            raise PermissionError("Signed operator decision signature is invalid.") from exc

        for key, expected_value in expected.items():
            if not _same_json(payload.get(key), expected_value):
                raise PermissionError(
                    f"Signed operator decision does not match approval field: {key}"
                )

        issued_at = _parse_utc(payload.get("issuedAt"), "issuedAt")
        requested_at = _parse(approval["requested_at"])
        expires_at = _parse(approval["expires_at"])
        current = _utc(now)
        if issued_at < requested_at - _CLOCK_SKEW:
            raise PermissionError(
                "Signed operator decision predates the approval request."
            )
        if issued_at > expires_at:
            raise PermissionError(
                "Signed operator decision was issued after approval expiry."
            )
        if issued_at > current + _CLOCK_SKEW:
            raise PermissionError(
                "Signed operator decision timestamp is too far in the future."
            )
        if enforce_freshness and current >= expires_at:
            raise PermissionError("Signed operator decision approval has expired.")

        return {
            "payloadJson": payload_bytes.decode("utf-8"),
            "payloadHash": hashlib.sha256(payload_bytes).hexdigest(),
            "signature": signature_text,
            "keyId": self.key_id,
            "issuedAt": _iso(issued_at),
        }


class OperatorAuthorizedDeviceCommandStore(NativeDeviceCommandStore):
    """Canonical command store with an external signed-approval execution gate."""

    def __init__(
        self,
        root: Path,
        *,
        operator_public_key_path: str | Path | None = None,
        operator_key_id: str | None = None,
    ) -> None:
        super().__init__(root)
        self.operator_verifier = OperatorDecisionVerifier(
            self.root,
            public_key_path=operator_public_key_path,
            key_id=operator_key_id,
        )
        with self.connection(immediate=True) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS device_command_operator_authority (
                    approval_id TEXT PRIMARY KEY,
                    schema TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    signature_base64 TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    verified_at TEXT NOT NULL,
                    FOREIGN KEY(approval_id)
                        REFERENCES device_command_approvals(approval_id)
                )
                """
            )

    def operator_authority_status(self) -> dict[str, Any]:
        return self.operator_verifier.status()

    def build_operator_decision_payload(
        self,
        approval_id: str,
        *,
        decision: str,
        decided_by: str,
        note: str = "",
        issued_at: datetime | None = None,
    ) -> dict[str, Any]:
        if str(decision or "").strip().lower() != "approved":
            raise ValueError(
                "Only approved device-command decisions are signed; denial is a fail-safe host action."
            )
        if not self.operator_verifier.ready:
            raise PermissionError(
                "Cryptographic device-operator verifier is not configured."
            )
        approver = _identity(decided_by, "decidedBy")
        bounded_note = str(note or "").strip()[:500]
        now = _utc(issued_at or datetime.now(timezone.utc))

        with self.connection(immediate=True) as connection:
            self._reconcile_locked(connection, now=now)
            approval = connection.execute(
                "SELECT * FROM device_command_approvals WHERE approval_id = ?",
                (str(approval_id),),
            ).fetchone()
            if approval is None:
                raise KeyError("Unknown device command approval.")
            if approval["status"] != "pending":
                raise ValueError(
                    f"Device command approval cannot be signed from state: {approval['status']}"
                )
            if _parse(approval["expires_at"]) <= now:
                raise PermissionError("Device command approval expired.")

        payload = self.operator_verifier._expected_payload(
            approval,
            key_id=self.operator_verifier.key_id,
            decided_by=approver,
            note=bounded_note,
        )
        payload["issuedAt"] = _iso(now)
        return payload

    def decide_approval(
        self,
        approval_id: str,
        *,
        decision: str,
        decided_by: str,
        human_confirmed: bool,
        note: str = "",
        signed_decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = str(decision or "").strip().lower()
        if normalized not in {"approved", "denied"}:
            raise ValueError("decision must be approved or denied")

        if normalized == "denied":
            if signed_decision is not None:
                raise ValueError(
                    "Signed denial is not an executable authorization and is not persisted."
                )
            return super().decide_approval(
                approval_id,
                decision="denied",
                decided_by=decided_by,
                human_confirmed=human_confirmed,
                note=note,
            )

        if human_confirmed is not True:
            raise PermissionError(
                "A signed device-command approval requires explicit human confirmation."
            )
        if signed_decision is None:
            raise PermissionError(
                "Approved device commands require an externally signed operator decision."
            )
        if not self.operator_verifier.ready:
            raise PermissionError(
                "Cryptographic device-operator verifier is not configured."
            )

        approver = _identity(decided_by, "decidedBy")
        bounded_note = str(note or "").strip()[:500]
        now = datetime.now(timezone.utc)
        with self.connection(immediate=True) as connection:
            self._reconcile_locked(connection, now=now)
            approval = connection.execute(
                "SELECT * FROM device_command_approvals WHERE approval_id = ?",
                (str(approval_id),),
            ).fetchone()
            if approval is None:
                raise KeyError("Unknown device command approval.")

            authority = self._authority_row(connection, approval_id)
            if approval["status"] == "approved" and authority is not None:
                verified = self.operator_verifier.verify_approval(
                    signed_decision,
                    approval,
                    decided_by=approver,
                    note=bounded_note,
                    now=now,
                    enforce_freshness=False,
                )
                if not hmac.compare_digest(
                    str(authority["payload_hash"]), verified["payloadHash"]
                ) or not hmac.compare_digest(
                    str(authority["signature_base64"]), verified["signature"]
                ):
                    raise ValueError(
                        "Device command approval is already bound to a different signed decision."
                    )
                return self._approval_receipt_with_authority(
                    approval, authority, verified=True
                )

            if approval["status"] != "pending":
                raise ValueError(
                    f"Device command approval cannot be decided from state: {approval['status']}"
                )
            if _parse(approval["expires_at"]) <= now:
                self._reconcile_locked(connection, now=now)
                expired = connection.execute(
                    "SELECT * FROM device_command_approvals WHERE approval_id = ?",
                    (str(approval_id),),
                ).fetchone()
                return self._approval_receipt_with_authority(
                    expired, None, verified=False
                )

            verified = self.operator_verifier.verify_approval(
                signed_decision,
                approval,
                decided_by=approver,
                note=bounded_note,
                now=now,
                enforce_freshness=True,
            )
            connection.execute(
                """
                INSERT INTO device_command_operator_authority(
                    approval_id, schema, key_id, payload_json, payload_hash,
                    signature_base64, issued_at, verified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(approval_id),
                    OPERATOR_DECISION_SCHEMA,
                    verified["keyId"],
                    verified["payloadJson"],
                    verified["payloadHash"],
                    verified["signature"],
                    verified["issuedAt"],
                    _iso(now),
                ),
            )
            changed = connection.execute(
                """
                UPDATE device_command_approvals
                SET status = 'approved', decided_at = ?, decided_by = ?,
                    decision_note = ?
                WHERE approval_id = ? AND status = 'pending'
                """,
                (_iso(now), approver, bounded_note, str(approval_id)),
            )
            if changed.rowcount != 1:
                raise PermissionError(
                    "Device command approval could not be decided exactly once."
                )
            updated = connection.execute(
                "SELECT * FROM device_command_approvals WHERE approval_id = ?",
                (str(approval_id),),
            ).fetchone()
            authority = self._authority_row(connection, approval_id)

        return self._approval_receipt_with_authority(
            updated, authority, verified=True
        )

    @staticmethod
    def _authority_row(
        connection: sqlite3.Connection, approval_id: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT * FROM device_command_operator_authority
            WHERE approval_id = ?
            """,
            (str(approval_id),),
        ).fetchone()

    def get_approval(self, approval_id: str) -> dict[str, Any]:
        with self.connection(immediate=True) as connection:
            self._reconcile_locked(connection)
            approval = connection.execute(
                "SELECT * FROM device_command_approvals WHERE approval_id = ?",
                (str(approval_id),),
            ).fetchone()
            if approval is None:
                raise KeyError("Unknown device command approval.")
            authority = self._authority_row(connection, approval_id)
            verified = self._authority_valid(
                approval,
                authority,
                now=datetime.now(timezone.utc),
                enforce_freshness=False,
            )
        return self._approval_receipt_with_authority(
            approval, authority, verified=verified
        )

    def _authorization_valid_locked(
        self,
        connection: sqlite3.Connection,
        command: sqlite3.Row,
        *,
        now: datetime,
    ) -> tuple[bool, str]:
        valid, reason = super()._authorization_valid_locked(
            connection, command, now=now
        )
        if not valid:
            return valid, reason
        if not self.operator_verifier.ready:
            return False, "operator-verifier-unavailable"

        approval = connection.execute(
            "SELECT * FROM device_command_approvals WHERE approval_id = ?",
            (str(command["approval_id"] or ""),),
        ).fetchone()
        if approval is None:
            return False, "approval-missing"
        authority = self._authority_row(connection, str(command["approval_id"] or ""))
        if authority is None:
            return False, "operator-signature-missing"
        if not self._authority_valid(
            approval,
            authority,
            now=now,
            enforce_freshness=True,
        ):
            return False, "operator-signature-invalid"
        return True, ""

    def _authority_valid(
        self,
        approval: sqlite3.Row,
        authority: sqlite3.Row | None,
        *,
        now: datetime,
        enforce_freshness: bool,
    ) -> bool:
        if authority is None or not self.operator_verifier.ready:
            return False
        if authority["schema"] != OPERATOR_DECISION_SCHEMA:
            return False
        if not hmac.compare_digest(
            str(authority["key_id"] or ""), self.operator_verifier.key_id
        ):
            return False
        try:
            payload = json.loads(authority["payload_json"])
            if payload.get("decision") != "approved":
                return False
            envelope = {
                "schema": OPERATOR_DECISION_SCHEMA,
                "algorithm": "ed25519",
                "keyId": authority["key_id"],
                "payload": payload,
                "signature": authority["signature_base64"],
            }
            verified = self.operator_verifier.verify_approval(
                envelope,
                approval,
                decided_by=str(approval["decided_by"] or ""),
                note=str(approval["decision_note"] or ""),
                now=now,
                enforce_freshness=enforce_freshness,
            )
        except (KeyError, TypeError, ValueError, PermissionError):
            return False
        return (
            hmac.compare_digest(
                str(authority["payload_hash"] or ""), verified["payloadHash"]
            )
            and hmac.compare_digest(
                str(authority["signature_base64"] or ""), verified["signature"]
            )
        )

    def _approval_receipt_with_authority(
        self,
        approval: sqlite3.Row,
        authority: sqlite3.Row | None,
        *,
        verified: bool,
    ) -> dict[str, Any]:
        receipt = super()._approval_receipt(approval)
        receipt.update(
            {
                "operatorSignatureRecorded": authority is not None,
                "operatorAuthorityKeyId": (
                    authority["key_id"] if authority is not None else None
                ),
                "operatorDecisionSignatureVerified": bool(verified),
                "humanIdentityCryptographicallyVerified": False,
                "truthBoundary": (
                    "A verified operator signature authenticates the configured "
                    "external signing key and binds it to this exact transaction. "
                    "It does not prove biometric presence or physical personhood. "
                    "Approved work is re-verified at the final device-claim gate."
                ),
            }
        )
        return receipt
