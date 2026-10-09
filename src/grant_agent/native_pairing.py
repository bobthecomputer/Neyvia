"""Scoped one-time pairing for Neyvia computer, phone, and NAS surfaces."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


PAIRING_SCHEMA = "neyvia.device-pairing/v1"
DEVICE_SCHEMA = "neyvia.paired-device/v1"
_ALLOWED_TARGETS = {"computer", "phone", "tablet", "nas", "worker"}
_ALLOWED_SCOPES = {
    "mission.read",
    "mission.control",
    "proof.read",
    "workspace.read",
    "workspace.write",
    "device.health",
    "device.commands",
    "runtime.connect",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat().replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _digest(value: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()


class NativePairingStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.path = self.root / ".agent_control" / "neyvia_agent" / "devices.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS pairing_requests (
                    pairing_id TEXT PRIMARY KEY,
                    target TEXT NOT NULL,
                    token_salt TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    redeemed_at TEXT,
                    revoked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS paired_devices (
                    device_id TEXT PRIMARY KEY,
                    pairing_id TEXT NOT NULL,
                    target TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    secret_salt TEXT NOT NULL,
                    secret_hash TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT,
                    revoked_at TEXT,
                    FOREIGN KEY(pairing_id) REFERENCES pairing_requests(pairing_id)
                );
                CREATE INDEX IF NOT EXISTS idx_pairing_expiry
                    ON pairing_requests(expires_at, redeemed_at, revoked_at);
                """
            )

    @staticmethod
    def _scopes(values: list[str] | tuple[str, ...] | None) -> list[str]:
        scopes = []
        for raw in values or ["mission.read", "proof.read", "device.health"]:
            scope = str(raw).strip()
            if scope not in _ALLOWED_SCOPES:
                raise ValueError(f"Unsupported pairing scope: {scope}")
            if scope not in scopes:
                scopes.append(scope)
        return scopes

    def create(
        self,
        target: str,
        *,
        scopes: list[str] | None = None,
        ttl_seconds: int = 600,
        base_url: str = "",
    ) -> dict[str, Any]:
        normalized_target = str(target or "").strip().lower()
        if normalized_target not in _ALLOWED_TARGETS:
            raise ValueError(f"Unsupported pairing target: {normalized_target or 'missing'}")
        resolved_scopes = self._scopes(scopes)
        ttl = max(60, min(3600, int(ttl_seconds)))
        token = secrets.token_urlsafe(32)
        salt = secrets.token_hex(16)
        pairing_id = f"pair_{uuid.uuid4().hex}"
        created = _now()
        expires = created + timedelta(seconds=ttl)
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO pairing_requests(
                    pairing_id, target, token_salt, token_hash, scopes_json,
                    created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pairing_id,
                    normalized_target,
                    salt,
                    _digest(token, salt),
                    json.dumps(resolved_scopes),
                    _iso(created),
                    _iso(expires),
                ),
            )
            from .proofs_d_native import check_pairing
            check_pairing(connection, pairing_id, token, resolved_scopes)
        fragment = f"neyvia-pair={pairing_id}.{token}"
        url = f"{base_url.rstrip('/')}/pair#{fragment}" if base_url else f"neyvia://pair#{fragment}"
        return {
            "schema": PAIRING_SCHEMA,
            "pairingId": pairing_id,
            "target": normalized_target,
            "scopes": resolved_scopes,
            "createdAt": _iso(created),
            "expiresAt": _iso(expires),
            "pairingToken": token,
            "pairingUrl": url,
            "tokenStored": False,
            "providerSecretsIncluded": False,
            "truthBoundary": "The high-entropy pairing token is returned once and stored only as a salted digest.",
        }

    def redeem(self, pairing_id: str, token: str, display_name: str) -> dict[str, Any]:
        with self.connection() as connection:
            # Serialize the read/check/write authority transition across callers.
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM pairing_requests WHERE pairing_id = ?",
                (str(pairing_id),),
            ).fetchone()
            if row is None:
                raise KeyError("Unknown pairing request.")
            if row["revoked_at"]:
                raise ValueError("Pairing request was revoked.")
            if row["redeemed_at"]:
                raise ValueError("Pairing request was already redeemed.")
            if _parse(row["expires_at"]) <= _now():
                raise ValueError("Pairing request expired.")
            supplied = _digest(str(token), row["token_salt"])
            if not hmac.compare_digest(supplied, row["token_hash"]):
                raise ValueError("Pairing token is invalid.")
            device_id = f"device_{uuid.uuid4().hex}"
            device_secret = secrets.token_urlsafe(40)
            secret_salt = secrets.token_hex(16)
            created = _iso()
            connection.execute(
                "UPDATE pairing_requests SET redeemed_at = ? WHERE pairing_id = ?",
                (created, pairing_id),
            )
            connection.execute(
                """
                INSERT INTO paired_devices(
                    device_id, pairing_id, target, display_name, secret_salt,
                    secret_hash, scopes_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device_id,
                    pairing_id,
                    row["target"],
                    str(display_name or row["target"]).strip()[:160],
                    secret_salt,
                    _digest(device_secret, secret_salt),
                    row["scopes_json"],
                    created,
                ),
            )
            from .proofs_d_native import check_redemption
            check_redemption(connection, pairing_id, device_id, device_secret)
        return {
            "schema": DEVICE_SCHEMA,
            "deviceId": device_id,
            "target": row["target"],
            "displayName": str(display_name or row["target"]).strip()[:160],
            "scopes": json.loads(row["scopes_json"]),
            "createdAt": created,
            "deviceSecret": device_secret,
            "secretStored": False,
            "providerSecretsIncluded": False,
            "truthBoundary": "The device credential is returned once; Neyvia stores only its salted digest.",
        }

    def authenticate(self, device_id: str, secret: str, required_scope: str = "") -> bool:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM paired_devices WHERE device_id = ?",
                (str(device_id),),
            ).fetchone()
            if row is None or row["revoked_at"]:
                from .proofs_d_native import check_auth
                check_auth(row, secret, required_scope, False)
                return False
            valid = hmac.compare_digest(
                _digest(str(secret), row["secret_salt"]), row["secret_hash"]
            )
            scopes = json.loads(row["scopes_json"])
            if required_scope and required_scope not in scopes:
                valid = False
            from .proofs_d_native import check_auth
            check_auth(row, secret, required_scope, valid)
            if valid:
                connection.execute(
                    "UPDATE paired_devices SET last_seen_at = ? WHERE device_id = ?",
                    (_iso(), device_id),
                )
            return valid

    def revoke(self, device_id: str) -> dict[str, Any]:
        revoked_at = _iso()
        with self.connection() as connection:
            result = connection.execute(
                "UPDATE paired_devices SET revoked_at = ? WHERE device_id = ? AND revoked_at IS NULL",
                (revoked_at, str(device_id)),
            )
            if result.rowcount == 1:
                from .proofs_d_native import require
                saved = connection.execute("SELECT revoked_at FROM paired_devices WHERE device_id=?", (str(device_id),)).fetchone()
                require(saved["revoked_at"] == revoked_at, "native.pairing.authority", "revocation was not durable")
            commands_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='device_commands'"
            ).fetchone()
            if result.rowcount == 1 and commands_table is not None:
                connection.execute(
                    """
                    UPDATE device_commands
                    SET status = 'rejected', completed_at = ?, error_code = 'device-revoked',
                        error_message = 'Device credential was revoked before command claim.'
                    WHERE device_id = ? AND status = 'queued'
                    """,
                    (revoked_at, str(device_id)),
                )
                connection.execute(
                    """
                    UPDATE device_commands
                    SET status = 'uncertain', completed_at = ?, error_code = 'device-revoked-after-claim',
                        error_message = 'Device was revoked after command claim; execution outcome is unknown.'
                    WHERE device_id = ? AND status = 'claimed'
                    """,
                    (revoked_at, str(device_id)),
                )
        return {
            "schema": DEVICE_SCHEMA,
            "deviceId": str(device_id),
            "revoked": result.rowcount == 1,
        }

    def list_devices(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT device_id, target, display_name, scopes_json, created_at,
                       last_seen_at, revoked_at
                FROM paired_devices ORDER BY created_at DESC
                """
            ).fetchall()
        return [
            {
                "schema": DEVICE_SCHEMA,
                "deviceId": row["device_id"],
                "target": row["target"],
                "displayName": row["display_name"],
                "scopes": json.loads(row["scopes_json"]),
                "createdAt": row["created_at"],
                "lastSeenAt": row["last_seen_at"],
                "revokedAt": row["revoked_at"],
            }
            for row in rows
        ]
