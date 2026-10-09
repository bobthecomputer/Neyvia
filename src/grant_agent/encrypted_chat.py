"""Scoped encrypted Matrix chat using a Rust SDK compatibility transport."""

from __future__ import annotations

from .proofs_b_engine import checked as _proofs_b_checked

import copy
import hashlib
import json
import re
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlparse

from .capability_contracts import utc_now
from .durability import append_jsonl_durable, atomic_write_json
from .subprocess_utils import hidden_windows_subprocess_kwargs


CHAT_PLAN_SCHEMA = "neyvia.encrypted-chat-plan/v1"
CHAT_RECEIPT_SCHEMA = "neyvia.encrypted-chat-receipt/v1"
CHAT_ENROLLMENT_SCHEMA = "neyvia.matrix-enrollment/v1"
CHAT_DEVICE_SCHEMA = "neyvia.matrix-device/v1"
CHAT_SESSION_SCHEMA = "neyvia.matrix-session/v1"
CHAT_RECOVERY_SCHEMA = "neyvia.matrix-recovery/v1"
SELF_CHAT_SCHEMA = "neyvia.self-chat-payload/v1"
_ACCOUNT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ROOM_REF = re.compile(r"^room-[a-f0-9]{16}$")
_DEVICE_REF = re.compile(r"^device-[a-f0-9]{16}$")
_MATRIX_USER_ID = re.compile(r"^@[^\s:]{1,255}:[^\s]{1,255}$")
_MATRIX_DEVICE_ID = re.compile(r"^[^\s]{1,255}$")
_SELF_CHAT_KINDS = {"link", "file", "clipboard", "note"}
_SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "key",
    "password",
    "secret",
    "sig",
    "signature",
    "token",
}
_LIKELY_SECRETS = (
    re.compile(r"(?i)\b(?:password|passwd|api[_ -]?key|secret)\s*[:=]\s*\S+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\." r"[A-Za-z0-9_-]{10,}\b"
    ),
    re.compile(r"\b[A-Fa-f0-9]{48,}\b"),
)


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_ref(prefix: str, value: str) -> str:
    return f"{prefix}-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _matrix_device_ref(
    *,
    account_id: str,
    homeserver: str,
    user_id: str,
    device_id: str,
) -> str:
    return _stable_ref(
        "device",
        "\0".join(
            (
                str(account_id).casefold(),
                str(homeserver).casefold().rstrip("/"),
                str(user_id),
                str(device_id),
            )
        ),
    )


ChatRunner = Callable[
    [list[str], bytes | None, float],
    subprocess.CompletedProcess[bytes],
]


class EncryptedChatService:
    """A room-scoped agent boundary over Matrix SDK encryption."""

    def __init__(
        self,
        root: str | Path,
        *,
        config_path: str | Path | None = None,
        runner: ChatRunner | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        project_root = Path(__file__).resolve().parents[2]
        selected = Path(config_path or self.root / "config" / "neyvia_chat.json")
        if not selected.is_file():
            selected = project_root / "config" / "neyvia_chat.json"
        if not selected.is_file():
            raise FileNotFoundError(selected)
        self.config_path = selected.resolve()
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self._runner = runner or self._run_subprocess
        self.receipt_root = self.root / ".agent_control" / "encrypted_chat" / "receipts"
        self.lifecycle_root = (
            self.root / ".agent_control" / "encrypted_chat" / "lifecycle"
        )
        self.enrollment_root = self.lifecycle_root / "enrollments"
        self.device_root = self.lifecycle_root / "devices"
        self.session_root = self.lifecycle_root / "sessions"
        self.recovery_root = self.lifecycle_root / "recoveries"
        self.lifecycle_event_path = self.lifecycle_root / "events.jsonl"

    @property
    def stack(self) -> dict[str, Any]:
        value = self.config.get("stack")
        return dict(value) if isinstance(value, dict) else {}

    @property
    def policy(self) -> dict[str, Any]:
        value = self.config.get("policy")
        return dict(value) if isinstance(value, dict) else {}

    @property
    def transport(self) -> dict[str, Any]:
        value = self.stack.get("agentTransport")
        return dict(value) if isinstance(value, dict) else {}

    @_proofs_b_checked("proofs-b.engine.chat-public")
    def compatibility_snapshot(self) -> dict[str, Any]:
        transport_path, transport_actual = self._binary_integrity(self.transport)
        desktop = dict(self.stack.get("desktopClient") or {})
        desktop_path, desktop_actual = self._binary_integrity(desktop)
        expected_transport = str(
            self.transport.get("executableSha256") or ""
        ).casefold()
        expected_desktop = str(desktop.get("executableSha256") or "").casefold()
        return {
            "schema": "neyvia.encrypted-chat-compatibility/v1",
            "homeserver": self._public_component("homeserver"),
            "sdk": self._public_component("sdk"),
            "agentTransport": {
                "name": str(self.transport.get("name") or ""),
                "version": str(self.transport.get("version") or ""),
                "state": str(self.transport.get("state") or ""),
                "path": str(transport_path),
                "installed": transport_path.is_file(),
                "hashVerified": bool(
                    transport_actual
                    and expected_transport
                    and transport_actual == expected_transport
                ),
                "expectedSha256": expected_transport,
                "actualSha256": transport_actual,
                "e2ee": True,
                "matrixSdk": str(
                    dict(self.stack.get("sdk") or {}).get("version") or ""
                ),
            },
            "desktopClient": {
                "name": str(desktop.get("name") or ""),
                "version": str(desktop.get("version") or ""),
                "state": str(desktop.get("state") or ""),
                "path": str(desktop_path),
                "installed": desktop_path.is_file(),
                "hashVerified": bool(
                    desktop_actual
                    and expected_desktop
                    and desktop_actual == expected_desktop
                ),
                "expectedSha256": expected_desktop,
                "actualSha256": desktop_actual,
                "signature": str(desktop.get("signature") or ""),
                "malwareScan": str(desktop.get("malwareScan") or ""),
            },
            "androidClient": self._public_component("androidClient"),
            "accounts": self.account_catalog(),
            "credentialPathsExposed": False,
            "tokensExposed": False,
            "limitations": {
                "nativeIpcSidecarImplemented": False,
                "roomMetadataInCompatibilityProcessArgs": bool(
                    self.policy.get(
                        "roomMetadataInCompatibilityProcessArgs",
                        True,
                    )
                ),
                "homeserverDeployed": (self._homeserver_deployed()),
                "serverEnrollmentImplemented": False,
                "serverDeviceRemovalImplemented": False,
                "crossSigningRecoveryImplemented": False,
            },
        }

    def _public_component(self, key: str) -> dict[str, Any]:
        value = dict(self.stack.get(key) or {})
        return {
            field: value.get(field)
            for field in ("name", "version", "state", "federationDefault")
            if field in value
        }

    @staticmethod
    def _binary_integrity(
        configured: dict[str, Any],
    ) -> tuple[Path, str]:
        path = Path(str(configured.get("installPath") or "")).resolve()
        return path, _sha256_file(path) if path.is_file() else ""

    def bootstrap(self) -> dict[str, Any]:
        homeserver = dict(self.stack.get("homeserver") or {})
        return {
            "schema": "neyvia.encrypted-chat-bootstrap/v1",
            "provider": "matrix",
            "homeserverVersion": str(homeserver.get("version") or ""),
            "homeserverState": str(homeserver.get("state") or ""),
            "transportVersion": str(self.transport.get("version") or ""),
            "configuredAccounts": len(self._accounts()),
            "lifecycle": self.lifecycle_snapshot()["summary"],
            "federationDefault": bool(self.policy.get("federationDefault", False)),
            "credentialsExposed": False,
            "detailsDeferred": True,
        }

    def lifecycle_snapshot(
        self,
        *,
        account_id: str = "",
    ) -> dict[str, Any]:
        """Return durable, opaque account/device/session lifecycle state."""

        normalized_account = str(account_id or "").strip().casefold()
        if normalized_account and not _ACCOUNT_ID.fullmatch(normalized_account):
            raise ValueError("Invalid accountId")
        enrollments = self._load_lifecycle_records(
            self.enrollment_root,
            CHAT_ENROLLMENT_SCHEMA,
        )
        devices = self._load_lifecycle_records(
            self.device_root,
            CHAT_DEVICE_SCHEMA,
        )
        sessions = self._load_lifecycle_records(
            self.session_root,
            CHAT_SESSION_SCHEMA,
        )
        recoveries = self._load_lifecycle_records(
            self.recovery_root,
            CHAT_RECOVERY_SCHEMA,
        )
        if normalized_account:
            enrollments = [
                row for row in enrollments if row.get("accountId") == normalized_account
            ]
            devices = [
                row for row in devices if row.get("accountId") == normalized_account
            ]
            sessions = [
                row for row in sessions if row.get("accountId") == normalized_account
            ]
            recoveries = [
                row for row in recoveries if row.get("accountId") == normalized_account
            ]
        return {
            "schema": "neyvia.matrix-lifecycle-snapshot/v1",
            "generatedAt": utc_now(),
            "homeserver": {
                "state": self._homeserver_state(),
                "configuredActive": self._homeserver_deployed(),
                "serverReachabilityProven": False,
            },
            "enrollments": enrollments,
            "devices": devices,
            "sessions": sessions,
            "recoveries": recoveries,
            "summary": {
                "enrollments": len(enrollments),
                "devices": len(devices),
                "sessions": len(sessions),
                "activeSessions": sum(
                    1 for row in sessions if row.get("state") == "active"
                ),
                "expiredSessions": sum(
                    1 for row in sessions if row.get("state") == "expired"
                ),
                "pendingRemovals": sum(
                    1 for row in devices if row.get("state") == "removal_pending"
                ),
            },
            "identifiersOpaque": True,
            "tokensExposed": False,
            "credentialsExposed": False,
        }

    def prepare_device_enrollment(
        self,
        *,
        account_id: str,
        homeserver: str,
        user_id: str,
        device_id: str,
        device_label: str,
        platform: str,
        session_ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Persist a secret-free enrollment intent without claiming login."""

        normalized_account = str(account_id or "").strip().casefold()
        if not _ACCOUNT_ID.fullmatch(normalized_account):
            raise ValueError("Invalid accountId")
        normalized_homeserver = self._validate_homeserver(homeserver)
        normalized_user = str(user_id or "").strip()
        if not _MATRIX_USER_ID.fullmatch(normalized_user):
            raise ValueError("Invalid Matrix userId")
        normalized_device = str(device_id or "").strip()
        if not _MATRIX_DEVICE_ID.fullmatch(normalized_device):
            raise ValueError("Invalid Matrix deviceId")
        label = str(device_label or "").strip()
        if not label or len(label) > 120:
            raise ValueError("deviceLabel must contain 1 to 120 characters")
        self._assert_no_likely_secret(label, field="deviceLabel")
        normalized_platform = str(platform or "").strip().casefold()
        if normalized_platform not in {
            "windows",
            "android",
            "ios",
            "macos",
            "linux",
            "nas",
            "web",
        }:
            raise ValueError("Unsupported Matrix device platform")
        ttl = int(
            session_ttl_seconds
            if session_ttl_seconds is not None
            else self.policy.get("sessionTtlSeconds") or 30 * 24 * 60 * 60
        )
        minimum_ttl = int(self.policy.get("minSessionTtlSeconds") or 300)
        maximum_ttl = int(self.policy.get("maxSessionTtlSeconds") or 90 * 24 * 60 * 60)
        if ttl < minimum_ttl or ttl > maximum_ttl:
            raise ValueError(
                f"sessionTtlSeconds must be between {minimum_ttl} and " f"{maximum_ttl}"
            )

        created_at = utc_now()
        expires_at = (
            (datetime.now(UTC) + timedelta(seconds=ttl))
            .isoformat()
            .replace("+00:00", "Z")
        )
        enrollment_ref = f"enrollment-{uuid.uuid4().hex[:20]}"
        session_ref = f"session-{uuid.uuid4().hex[:20]}"
        user_ref = _stable_ref("user", normalized_user)
        device_ref = _matrix_device_ref(
            account_id=normalized_account,
            homeserver=normalized_homeserver,
            user_id=normalized_user,
            device_id=normalized_device,
        )
        homeserver_ref = _stable_ref("homeserver", normalized_homeserver)
        deployed = self._homeserver_deployed()
        enrollment_state = (
            "server_verification_required" if deployed else "homeserver_unavailable"
        )
        enrollment = {
            "schema": CHAT_ENROLLMENT_SCHEMA,
            "enrollmentRef": enrollment_ref,
            "accountId": normalized_account,
            "userRef": user_ref,
            "deviceRef": device_ref,
            "homeserverRef": homeserver_ref,
            "deviceLabel": label,
            "platform": normalized_platform,
            "state": enrollment_state,
            "createdAt": created_at,
            "updatedAt": created_at,
            "serverEnrollmentProven": False,
            "credentialsStored": False,
            "cryptoStoreCreated": False,
            "tokensExposed": False,
            "credentialsExposed": False,
        }
        previous_device = self._load_lifecycle_record(
            self.device_root / f"{device_ref}.json",
            CHAT_DEVICE_SCHEMA,
            required=False,
        )
        if previous_device.get("localDisabled") is True:
            raise PermissionError(
                "Matrix device is locally disabled; an approved recovery "
                "transition is required before re-enrollment"
            )
        session_refs = list(previous_device.get("sessionRefs") or [])
        if session_ref not in session_refs:
            session_refs.append(session_ref)
        device = {
            "schema": CHAT_DEVICE_SCHEMA,
            "deviceRef": device_ref,
            "accountId": normalized_account,
            "userRef": user_ref,
            "homeserverRef": homeserver_ref,
            "label": label,
            "platform": normalized_platform,
            "state": "pending_enrollment",
            "createdAt": str(previous_device.get("createdAt") or created_at),
            "updatedAt": created_at,
            "sessionRefs": session_refs,
            "localDisabled": False,
            "serverEnrollmentProven": False,
            "serverRemovalProven": False,
            "secretsStored": False,
        }
        session = {
            "schema": CHAT_SESSION_SCHEMA,
            "sessionRef": session_ref,
            "enrollmentRef": enrollment_ref,
            "accountId": normalized_account,
            "deviceRef": device_ref,
            "state": "pending_enrollment",
            "createdAt": created_at,
            "updatedAt": created_at,
            "expiresAt": expires_at,
            "localAccessDisabled": False,
            "serverSessionProven": False,
            "remoteInvalidationProven": False,
            "tokenStored": False,
        }
        atomic_write_json(
            self.enrollment_root / f"{enrollment_ref}.json",
            enrollment,
        )
        atomic_write_json(self.device_root / f"{device_ref}.json", device)
        atomic_write_json(self.session_root / f"{session_ref}.json", session)
        self._append_lifecycle_event(
            "enrollment_prepared",
            account_id=normalized_account,
            enrollment_ref=enrollment_ref,
            device_ref=device_ref,
            session_ref=session_ref,
            state=enrollment_state,
        )
        return {
            "schema": "neyvia.matrix-enrollment-result/v1",
            "ok": False,
            "status": enrollment_state,
            "enrollment": enrollment,
            "device": device,
            "session": session,
            "serverActionPerformed": False,
            "nextAction": (
                "Deploy and verify the configured Matrix homeserver before "
                "attempting account login."
                if not deployed
                else "Complete Matrix login outside model context, create the "
                "encrypted crypto store, then verify the server session."
            ),
            "identifiersOpaque": True,
            "tokensExposed": False,
            "credentialsExposed": False,
        }

    def request_device_removal(
        self,
        device_ref: str,
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        """Disable a device locally and retain remote removal as pending."""

        normalized_ref = str(device_ref or "").strip()
        if not _DEVICE_REF.fullmatch(normalized_ref):
            raise ValueError("Invalid opaque deviceRef")
        device_path = self.device_root / f"{normalized_ref}.json"
        device = self._load_lifecycle_record(
            device_path,
            CHAT_DEVICE_SCHEMA,
            required=True,
        )
        if not approved:
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "communication.account.manage",
                "deviceRef": normalized_ref,
                "reason": (
                    "Removing a Matrix device can invalidate an external "
                    "session and requires explicit approval."
                ),
            }
        now = utc_now()
        device.update(
            {
                "state": "removal_pending",
                "updatedAt": now,
                "localDisabled": True,
                "localDisabledAt": now,
                "serverRemovalProven": False,
            }
        )
        atomic_write_json(device_path, device)
        for session_ref in device.get("sessionRefs") or []:
            path = self.session_root / f"{session_ref}.json"
            session = self._load_lifecycle_record(
                path,
                CHAT_SESSION_SCHEMA,
                required=False,
            )
            if not session:
                continue
            session.update(
                {
                    "state": "local_disabled",
                    "updatedAt": now,
                    "localAccessDisabled": True,
                    "remoteInvalidationProven": False,
                }
            )
            atomic_write_json(path, session)
        status = (
            "remote_removal_required"
            if self._homeserver_deployed()
            else "blocked_homeserver_unavailable"
        )
        self._append_lifecycle_event(
            "device_removal_requested",
            account_id=str(device.get("accountId") or ""),
            device_ref=normalized_ref,
            state=status,
        )
        return {
            "schema": "neyvia.matrix-device-removal-result/v1",
            "ok": False,
            "status": status,
            "deviceRef": normalized_ref,
            "localDeviceDisabled": True,
            "serverActionPerformed": False,
            "serverRemovalProven": False,
            "tokensExposed": False,
            "credentialsExposed": False,
        }

    def expire_sessions(self) -> dict[str, Any]:
        """Expire due local sessions without claiming remote token revocation."""

        now = datetime.now(UTC)
        now_text = now.isoformat().replace("+00:00", "Z")
        expired: list[str] = []
        sessions = self._load_lifecycle_records(
            self.session_root,
            CHAT_SESSION_SCHEMA,
        )
        for session in sessions:
            if session.get("state") in {"expired", "removed"}:
                continue
            expires_at = self._parse_utc(str(session.get("expiresAt") or ""))
            if expires_at > now:
                continue
            session.update(
                {
                    "state": "expired",
                    "updatedAt": now_text,
                    "expiredAt": now_text,
                    "localAccessDisabled": True,
                    "remoteInvalidationProven": False,
                }
            )
            session_ref = str(session.get("sessionRef") or "")
            atomic_write_json(
                self.session_root / f"{session_ref}.json",
                session,
            )
            expired.append(session_ref)
            self._append_lifecycle_event(
                "session_expired",
                account_id=str(session.get("accountId") or ""),
                device_ref=str(session.get("deviceRef") or ""),
                session_ref=session_ref,
                state="expired",
            )
        for device in self._load_lifecycle_records(
            self.device_root,
            CHAT_DEVICE_SCHEMA,
        ):
            refs = [
                str(value) for value in device.get("sessionRefs") or [] if str(value)
            ]
            if not refs:
                continue
            current = {str(row.get("sessionRef") or ""): row for row in sessions}
            for session_ref in expired:
                current[session_ref] = self._load_lifecycle_record(
                    self.session_root / f"{session_ref}.json",
                    CHAT_SESSION_SCHEMA,
                    required=True,
                )
            if all(
                current.get(ref, {}).get("localAccessDisabled") is True for ref in refs
            ):
                device.update(
                    {
                        "state": "sessions_expired",
                        "updatedAt": now_text,
                        "localDisabled": True,
                        "localDisabledAt": now_text,
                    }
                )
                atomic_write_json(
                    self.device_root / f"{device['deviceRef']}.json",
                    device,
                )
        return {
            "schema": "neyvia.matrix-session-expiration-result/v1",
            "ok": True,
            "status": "local_sessions_expired" if expired else "no_due_sessions",
            "expiredSessionRefs": expired,
            "summary": {"expired": len(expired)},
            "serverActionPerformed": False,
            "remoteInvalidationProven": False,
            "tokensExposed": False,
            "credentialsExposed": False,
        }

    def request_account_recovery(
        self,
        *,
        account_id: str,
        reason: str,
        approved: bool = False,
    ) -> dict[str, Any]:
        """Record a recovery request while keeping recovery secrets external."""

        normalized_account = str(account_id or "").strip().casefold()
        if not _ACCOUNT_ID.fullmatch(normalized_account):
            raise ValueError("Invalid accountId")
        known = any(
            str(account.get("accountId") or "").casefold() == normalized_account
            for account in self._accounts()
        ) or bool(self.lifecycle_snapshot(account_id=normalized_account)["enrollments"])
        if not known:
            raise KeyError(f"Unknown encrypted-chat account: {account_id}")
        reason_text = str(reason or "").strip()
        if not reason_text or len(reason_text.encode("utf-8")) > 2000:
            raise ValueError("reason must contain 1 to 2000 UTF-8 bytes")
        self._assert_no_likely_secret(reason_text, field="reason")
        if not approved:
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "communication.account.recover",
                "accountId": normalized_account,
                "reason": ("Account recovery can rotate trust and invalidate devices."),
            }
        recovery_ref = f"recovery-{uuid.uuid4().hex[:20]}"
        now = utc_now()
        status = (
            "operator_action_required"
            if self._homeserver_deployed()
            else "blocked_homeserver_unavailable"
        )
        record = {
            "schema": CHAT_RECOVERY_SCHEMA,
            "recoveryRef": recovery_ref,
            "accountId": normalized_account,
            "state": status,
            "createdAt": now,
            "updatedAt": now,
            "reasonSha256": hashlib.sha256(reason_text.encode("utf-8")).hexdigest(),
            "reasonBytes": len(reason_text.encode("utf-8")),
            "serverRecoveryProven": False,
            "crossSigningResetProven": False,
            "recoverySecretStored": False,
            "tokensExposed": False,
            "credentialsExposed": False,
        }
        atomic_write_json(
            self.recovery_root / f"{recovery_ref}.json",
            record,
        )
        self._append_lifecycle_event(
            "account_recovery_requested",
            account_id=normalized_account,
            state=status,
        )
        return {
            "schema": "neyvia.matrix-recovery-result/v1",
            "ok": False,
            "status": status,
            "recovery": record,
            "serverActionPerformed": False,
            "serverRecoveryProven": False,
            "recoverySecretsExposed": False,
            "tokensExposed": False,
            "credentialsExposed": False,
        }

    @_proofs_b_checked("proofs-b.engine.chat-public")
    def account_catalog(self) -> dict[str, Any]:
        accounts = []
        for account in self._accounts():
            rooms = []
            for room in account.get("rooms") or []:
                if not isinstance(room, dict):
                    continue
                room_id = str(room.get("roomId") or "")
                rooms.append(
                    {
                        "roomRef": _stable_ref("room", room_id),
                        "label": str(room.get("label") or "Private room"),
                        "kind": str(room.get("kind") or "private"),
                        "readable": bool(room.get("agentReadable")),
                        "writable": bool(room.get("agentWritable")),
                        "attachments": bool(room.get("agentAttachments")),
                        "encryptedRequired": True,
                    }
                )
            accounts.append(
                {
                    "accountId": str(account.get("accountId") or ""),
                    "label": str(account.get("label") or ""),
                    "userRef": _stable_ref(
                        "user",
                        str(account.get("userId") or ""),
                    ),
                    "deviceRef": _matrix_device_ref(
                        account_id=str(account.get("accountId") or ""),
                        homeserver=str(account.get("homeserver") or ""),
                        user_id=str(account.get("userId") or ""),
                        device_id=str(account.get("deviceId") or ""),
                    ),
                    "homeserverRef": _stable_ref(
                        "homeserver",
                        str(account.get("homeserver") or ""),
                    ),
                    "credentialAvailable": Path(
                        str(account.get("credentialsPath") or "")
                    ).is_file(),
                    "cryptoStoreAvailable": Path(
                        str(account.get("storePath") or "")
                    ).is_dir(),
                    "rooms": rooms,
                }
            )
        return {
            "schema": "neyvia.encrypted-chat-account-catalog/v1",
            "accounts": accounts,
            "summary": {
                "accounts": len(accounts),
                "rooms": sum(len(row["rooms"]) for row in accounts),
                "readableRooms": sum(
                    1 for row in accounts for room in row["rooms"] if room["readable"]
                ),
                "writableRooms": sum(
                    1 for row in accounts for room in row["rooms"] if room["writable"]
                ),
            },
            "credentialsExposed": False,
        }

    def _accounts(self) -> list[dict[str, Any]]:
        values = self.policy.get("accounts")
        if not isinstance(values, list):
            return []
        return [dict(item) for item in values if isinstance(item, dict)]

    @_proofs_b_checked("proofs-b.engine.chat-plan")
    def build_message_plan(
        self,
        *,
        account_id: str,
        room_ref: str,
        actor: str,
        message: str = "",
        attachments: list[str | Path] | None = None,
        format: str = "text",
    ) -> dict[str, Any]:
        account, room = self._resolve_room(
            account_id,
            room_ref,
            require="write",
        )
        normalized_format = str(format or "text").casefold()
        if normalized_format not in {"text", "markdown", "code"}:
            raise ValueError("format must be text, markdown, or code")
        text = str(message or "")
        text_bytes = text.encode("utf-8")
        maximum = int(self.policy.get("maxMessageBytes") or 65_536)
        if len(text_bytes) > maximum:
            raise ValueError(f"Message exceeds {maximum} UTF-8 bytes")
        if text and bool(self.policy.get("blockLikelySecrets", True)):
            if any(pattern.search(text) for pattern in _LIKELY_SECRETS):
                raise ValueError(
                    "Likely password, token, or API key detected. Use a vault "
                    "secret handle instead of putting credentials in chat."
                )
        files = self._attachment_manifest(attachments or [], room)
        if not text and not files:
            raise ValueError("A message or at least one attachment is required")
        actor_label = str(actor or "Agent").strip()[:80]
        if not actor_label:
            raise ValueError("actor is required for visible attribution")
        template = str(
            self.policy.get("agentAttributionTemplate") or "Neyvia · {actor}\n{message}"
        )
        attributed = template.format(actor=actor_label, message=text) if text else ""
        plan = {
            "schema": CHAT_PLAN_SCHEMA,
            "planId": f"chatplan_{uuid.uuid4().hex[:20]}",
            "createdAt": utc_now(),
            "accountId": str(account.get("accountId") or ""),
            "roomRef": room_ref,
            "roomLabel": str(room.get("label") or "Private room"),
            "actor": actor_label,
            "format": normalized_format,
            "message": attributed,
            "messageSha256": hashlib.sha256(text_bytes).hexdigest(),
            "messageBytes": len(text_bytes),
            "attachments": files,
            "encryptionRequired": True,
            "summary": {
                "hasMessage": bool(text),
                "attachments": len(files),
                "attachmentBytes": sum(int(item["bytes"]) for item in files),
                "visibleAttribution": True,
                "agentWritable": True,
            },
        }
        plan["planHash"] = self._plan_hash(plan)
        return plan

    def build_self_chat_plan(
        self,
        *,
        account_id: str,
        actor: str,
        payloads: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build one encrypted self-room plan for typed personal payloads."""

        if not isinstance(payloads, list) or not payloads:
            raise ValueError("payloads must be a non-empty array")
        maximum = int(self.policy.get("maxSelfChatPayloads") or 16)
        if len(payloads) > maximum:
            raise ValueError(f"At most {maximum} self-chat payloads are allowed")
        account, room = self._resolve_self_room(account_id)
        rendered: list[str] = []
        attachments: list[str | Path] = []
        summaries: list[dict[str, Any]] = []
        for index, raw_payload in enumerate(payloads):
            if not isinstance(raw_payload, dict):
                raise ValueError(f"payloads[{index}] must be an object")
            kind = str(raw_payload.get("kind") or "").strip().casefold()
            if kind not in _SELF_CHAT_KINDS:
                raise ValueError(
                    "self-chat kind must be link, file, clipboard, or note"
                )
            if kind == "file":
                path_value = str(raw_payload.get("path") or "").strip()
                if not path_value:
                    raise ValueError(f"payloads[{index}].path is required")
                path = Path(path_value)
                if not path.is_absolute():
                    path = self.root / path
                path = path.resolve()
                caption = str(raw_payload.get("caption") or "").strip()
                self._validate_self_chat_text(caption, field="caption")
                attachments.append(path)
                content = f"[File] {path.name}" + (f"\n{caption}" if caption else "")
                digest_source = (
                    path.name.encode("utf-8") + b"\0" + caption.encode("utf-8")
                )
                summaries.append(
                    {
                        "kind": kind,
                        "payloadSha256": hashlib.sha256(digest_source).hexdigest(),
                        "metadataBytes": len(digest_source),
                        "contentPersisted": False,
                    }
                )
                rendered.append(content)
                continue
            if kind == "link":
                url = self._validate_self_chat_link(str(raw_payload.get("url") or ""))
                title = str(raw_payload.get("title") or "").strip()
                self._validate_self_chat_text(title, field="title")
                content = f"[Link] {title}\n{url}" if title else f"[Link]\n{url}"
            else:
                text = str(raw_payload.get("text") or "")
                if not text:
                    raise ValueError(f"payloads[{index}].text is required")
                self._validate_self_chat_text(text, field=kind)
                if kind == "clipboard":
                    content = f"[Clipboard]\n```\n{text}\n```"
                else:
                    content = f"[Note]\n{text}"
            encoded = content.encode("utf-8")
            summaries.append(
                {
                    "kind": kind,
                    "payloadSha256": hashlib.sha256(encoded).hexdigest(),
                    "metadataBytes": len(encoded),
                    "contentPersisted": False,
                }
            )
            rendered.append(content)
        room_ref = _stable_ref("room", str(room.get("roomId") or ""))
        plan = self.build_message_plan(
            account_id=str(account.get("accountId") or ""),
            room_ref=room_ref,
            actor=actor,
            message="\n\n".join(rendered),
            attachments=attachments,
            format="markdown",
        )
        plan["selfChat"] = {
            "schema": SELF_CHAT_SCHEMA,
            "payloads": summaries,
            "summary": {
                "payloads": len(summaries),
                "kinds": sorted({row["kind"] for row in summaries}),
                "opaqueReceiptMetadata": True,
                "contentPersisted": False,
            },
        }
        plan["planHash"] = self._plan_hash(plan)
        return plan

    def _resolve_self_room(
        self,
        account_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        normalized_account = str(account_id or "").strip().casefold()
        if not _ACCOUNT_ID.fullmatch(normalized_account):
            raise ValueError("Invalid accountId")
        account = next(
            (
                item
                for item in self._accounts()
                if str(item.get("accountId") or "").casefold() == normalized_account
            ),
            None,
        )
        if account is None:
            raise KeyError(f"Unknown encrypted-chat account: {account_id}")
        self_rooms = [
            dict(item)
            for item in account.get("rooms") or []
            if isinstance(item, dict)
            and str(item.get("kind") or "").casefold() == "self"
            and bool(item.get("agentWritable"))
        ]
        if len(self_rooms) != 1:
            raise RuntimeError(
                "Account must expose exactly one writable self-chat room"
            )
        room = self_rooms[0]
        return self._resolve_room(
            normalized_account,
            _stable_ref("room", str(room.get("roomId") or "")),
            require="write",
        )

    def _validate_self_chat_text(self, value: str, *, field: str) -> None:
        encoded = str(value or "").encode("utf-8")
        maximum = int(self.policy.get("maxSelfChatMetadataBytes") or 65_536)
        if len(encoded) > maximum:
            raise ValueError(f"{field} exceeds {maximum} UTF-8 bytes")
        if value:
            self._assert_no_likely_secret(value, field=field)

    def _validate_self_chat_link(self, value: str) -> str:
        normalized = str(value or "").strip()
        parsed = urlparse(normalized)
        if (
            parsed.scheme.casefold() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError(
                "Self-chat links must use HTTP(S) without embedded credentials"
            )
        sensitive = {
            key.casefold() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
        } & _SENSITIVE_QUERY_KEYS
        if sensitive:
            raise ValueError("Self-chat link query contains likely credential material")
        self._assert_no_likely_secret(normalized, field="url")
        return normalized

    def _attachment_manifest(
        self,
        values: list[str | Path],
        room: dict[str, Any],
    ) -> list[dict[str, Any]]:
        maximum_count = int(self.policy.get("maxAttachments") or 8)
        if len(values) > maximum_count:
            raise ValueError(f"At most {maximum_count} attachments are allowed")
        if values and not bool(room.get("agentAttachments")):
            raise PermissionError("Attachments are not enabled for this room scope")
        maximum_file = int(self.policy.get("maxAttachmentBytes") or 20 * 1024 * 1024)
        maximum_total = int(
            self.policy.get("maxTotalAttachmentBytes") or 64 * 1024 * 1024
        )
        total = 0
        result = []
        for value in values:
            path = Path(value)
            if not path.is_absolute():
                path = self.root / path
            path = path.resolve()
            try:
                relative = path.relative_to(self.root)
            except ValueError as exc:
                raise ValueError(
                    "Chat attachments must be inside the workspace"
                ) from exc
            if not path.is_file():
                raise ValueError(f"Chat attachment does not exist: {path}")
            size = path.stat().st_size
            if size > maximum_file:
                raise ValueError(
                    f"Chat attachment exceeds {maximum_file} bytes: {path.name}"
                )
            total += size
            if total > maximum_total:
                raise ValueError(f"Chat attachments exceed {maximum_total} total bytes")
            result.append(
                {
                    "path": str(path),
                    "workspacePath": relative.as_posix(),
                    "name": path.name,
                    "bytes": size,
                    "sha256": _sha256_file(path),
                }
            )
        return result

    @staticmethod
    def _plan_hash(plan: dict[str, Any]) -> str:
        payload = copy.deepcopy(plan)
        payload.pop("planHash", None)
        return _canonical_hash(payload)

    def send(
        self,
        plan: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        if not approved:
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "communication.send",
                "reason": "Sending a message represents the user or agent externally.",
            }
        self._validate_plan(plan)
        account, room = self._resolve_room(
            str(plan.get("accountId") or ""),
            str(plan.get("roomRef") or ""),
            require="write",
        )
        room_id = str(room.get("roomId") or "")
        self._assert_encrypted(account, room_id)
        results: list[dict[str, Any]] = []
        for attachment in plan.get("attachments") or []:
            path = Path(str(attachment.get("path") or "")).resolve()
            if (
                not path.is_file()
                or path.stat().st_size != int(attachment.get("bytes") or -1)
                or _sha256_file(path) != str(attachment.get("sha256") or "")
            ):
                raise ValueError(f"Attachment changed after preview: {path.name}")
            completed = self._invoke(
                account,
                room_id,
                [
                    "--file",
                    "-",
                    "--file-name",
                    str(attachment.get("name") or "attachment"),
                ],
                stdin=path.read_bytes(),
            )
            results.append(
                {
                    "kind": "attachment",
                    "name": str(attachment.get("name") or ""),
                    "sha256": str(attachment.get("sha256") or ""),
                    "transport": self._public_transport_result(completed),
                }
            )
        message = str(plan.get("message") or "")
        if message:
            flags = ["--message", "-"]
            message_format = str(plan.get("format") or "text")
            if message_format == "markdown":
                flags.append("--markdown")
            elif message_format == "code":
                flags.append("--code")
            completed = self._invoke(
                account,
                room_id,
                flags,
                stdin=message.encode("utf-8"),
            )
            results.append(
                {
                    "kind": "message",
                    "sha256": str(plan.get("messageSha256") or ""),
                    "transport": self._public_transport_result(completed),
                }
            )
        ok = bool(results) and all(
            int(item["transport"]["exitCode"]) == 0 for item in results
        )
        receipt = {
            "schema": CHAT_RECEIPT_SCHEMA,
            "receiptId": f"chatreceipt_{uuid.uuid4().hex[:20]}",
            "createdAt": utc_now(),
            "planId": str(plan.get("planId") or ""),
            "planHash": str(plan.get("planHash") or ""),
            "accountId": str(plan.get("accountId") or ""),
            "roomRef": str(plan.get("roomRef") or ""),
            "actor": str(plan.get("actor") or ""),
            "ok": ok,
            "status": "sent" if ok else "transport_failed",
            "encryptedRoomVerified": True,
            "items": results,
            "messagePersisted": False,
            "tokensExposed": False,
            "credentialsExposed": False,
        }
        if isinstance(plan.get("selfChat"), dict):
            receipt["selfChat"] = copy.deepcopy(plan["selfChat"])
        persisted = copy.deepcopy(receipt)
        atomic_write_json(
            self.receipt_root / f"{receipt['receiptId']}.json",
            persisted,
        )
        return receipt

    def history(
        self,
        *,
        account_id: str,
        room_ref: str,
        limit: int = 25,
    ) -> dict[str, Any]:
        account, room = self._resolve_room(
            account_id,
            room_ref,
            require="read",
        )
        room_id = str(room.get("roomId") or "")
        self._assert_encrypted(account, room_id)
        bounded = max(
            1,
            min(int(limit), int(self.policy.get("maxHistoryEvents") or 100)),
        )
        completed = self._invoke(
            account,
            room_id,
            [
                "--listen",
                "tail",
                "--tail",
                str(bounded),
                "--listen-self",
            ],
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "Matrix history transport failed: "
                + completed.stderr.decode("utf-8", errors="replace")[:2000]
            )
        parsed = self._parse_json_output(completed.stdout)
        public = self._sanitize(parsed)
        return {
            "schema": "neyvia.encrypted-chat-history/v1",
            "generatedAt": utc_now(),
            "accountId": str(account.get("accountId") or ""),
            "roomRef": room_ref,
            "roomLabel": str(room.get("label") or "Private room"),
            "encryptedRoomVerified": True,
            "events": public if isinstance(public, list) else [public],
            "summary": {"limit": bounded},
            "tokensExposed": False,
            "credentialsExposed": False,
        }

    def _validate_plan(self, plan: dict[str, Any]) -> None:
        if not isinstance(plan, dict) or plan.get("schema") != CHAT_PLAN_SCHEMA:
            raise ValueError("Invalid encrypted-chat plan schema")
        if str(plan.get("planHash") or "") != self._plan_hash(plan):
            raise ValueError("Encrypted-chat plan hash does not match")
        if not bool(plan.get("encryptionRequired")):
            raise ValueError("Encrypted-chat plan must require encryption")
        if not _ROOM_REF.fullmatch(str(plan.get("roomRef") or "")):
            raise ValueError("Invalid roomRef")
        self_chat = plan.get("selfChat")
        if self_chat is not None:
            self._validate_self_chat_metadata(self_chat)

    @staticmethod
    def _validate_self_chat_metadata(value: object) -> None:
        if not isinstance(value, dict) or value.get("schema") != SELF_CHAT_SCHEMA:
            raise ValueError("Invalid self-chat payload schema")
        payloads = value.get("payloads")
        if not isinstance(payloads, list) or not payloads:
            raise ValueError("Invalid self-chat payload metadata")
        for item in payloads:
            if (
                not isinstance(item, dict)
                or item.get("kind") not in _SELF_CHAT_KINDS
                or not re.fullmatch(
                    r"[a-f0-9]{64}",
                    str(item.get("payloadSha256") or ""),
                )
                or item.get("contentPersisted") is not False
            ):
                raise ValueError("Invalid opaque self-chat payload metadata")

    def _resolve_room(
        self,
        account_id: str,
        room_ref: str,
        *,
        require: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        normalized_account = str(account_id or "").strip().casefold()
        if not _ACCOUNT_ID.fullmatch(normalized_account):
            raise ValueError("Invalid accountId")
        if not _ROOM_REF.fullmatch(str(room_ref or "")):
            raise ValueError("Invalid opaque roomRef")
        account = next(
            (
                item
                for item in self._accounts()
                if str(item.get("accountId") or "").casefold() == normalized_account
            ),
            None,
        )
        if account is None:
            raise KeyError(f"Unknown encrypted-chat account: {account_id}")
        self._validate_account_paths(account)
        room = next(
            (
                dict(item)
                for item in account.get("rooms") or []
                if isinstance(item, dict)
                and _stable_ref("room", str(item.get("roomId") or "")) == room_ref
            ),
            None,
        )
        if room is None:
            raise KeyError("Room is outside this account's agent allowlist")
        permission_key = "agentReadable" if require == "read" else "agentWritable"
        if not bool(room.get(permission_key)):
            raise PermissionError(f"Room does not grant agent {require} access")
        return account, room

    def _validate_account_paths(self, account: dict[str, Any]) -> None:
        secret_root = Path(str(self.policy.get("secretRoot") or "")).resolve()
        credentials = Path(str(account.get("credentialsPath") or "")).resolve()
        store = Path(str(account.get("storePath") or "")).resolve()
        for path in (credentials, store):
            try:
                path.relative_to(secret_root)
            except ValueError as exc:
                raise ValueError(
                    "Matrix credentials and crypto store must stay inside "
                    "the configured secret root"
                ) from exc
        if not credentials.is_file():
            raise RuntimeError("Matrix credential file is unavailable")
        if not store.is_dir():
            raise RuntimeError("Matrix encrypted store is unavailable")
        device_ref = _matrix_device_ref(
            account_id=str(account.get("accountId") or ""),
            homeserver=str(account.get("homeserver") or ""),
            user_id=str(account.get("userId") or ""),
            device_id=str(account.get("deviceId") or ""),
        )
        device = self._load_lifecycle_record(
            self.device_root / f"{device_ref}.json",
            CHAT_DEVICE_SCHEMA,
            required=False,
        )
        if device.get("localDisabled") is True:
            raise RuntimeError(
                "Matrix device is locally disabled pending lifecycle recovery"
            )

    def _homeserver_state(self) -> str:
        return str(dict(self.stack.get("homeserver") or {}).get("state") or "")

    def _homeserver_deployed(self) -> bool:
        return self._homeserver_state() == "active"

    @staticmethod
    def _validate_homeserver(value: str) -> str:
        normalized = str(value or "").strip().rstrip("/")
        parsed = urlparse(normalized)
        if (
            parsed.scheme.casefold() != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Matrix homeserver must be an HTTPS origin without "
                "credentials, query, or fragment"
            )
        return normalized

    @staticmethod
    def _parse_utc(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError("Invalid durable Matrix session timestamp") from exc
        if parsed.tzinfo is None:
            raise RuntimeError("Matrix session timestamp must be timezone-aware")
        return parsed.astimezone(UTC)

    def _load_lifecycle_record(
        self,
        path: Path,
        schema: str,
        *,
        required: bool,
    ) -> dict[str, Any]:
        if not path.is_file():
            if required:
                raise KeyError(f"Unknown Matrix lifecycle reference: {path.stem}")
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Unreadable durable Matrix lifecycle record: {path.name}"
            ) from exc
        if not isinstance(value, dict) or value.get("schema") != schema:
            raise RuntimeError(f"Invalid durable Matrix lifecycle record: {path.name}")
        return value

    def _load_lifecycle_records(
        self,
        root: Path,
        schema: str,
    ) -> list[dict[str, Any]]:
        if not root.is_dir():
            return []
        return [
            self._load_lifecycle_record(path, schema, required=True)
            for path in sorted(root.glob("*.json"))
        ]

    def _append_lifecycle_event(
        self,
        event: str,
        *,
        account_id: str,
        state: str,
        enrollment_ref: str = "",
        device_ref: str = "",
        session_ref: str = "",
    ) -> None:
        append_jsonl_durable(
            self.lifecycle_event_path,
            {
                "schema": "neyvia.matrix-lifecycle-event/v1",
                "createdAt": utc_now(),
                "event": event,
                "accountId": account_id,
                "state": state,
                "enrollmentRef": enrollment_ref,
                "deviceRef": device_ref,
                "sessionRef": session_ref,
                "secretsPersisted": False,
            },
        )

    @staticmethod
    def _assert_no_likely_secret(value: str, *, field: str) -> None:
        if any(pattern.search(str(value)) for pattern in _LIKELY_SECRETS):
            raise ValueError(
                f"Likely credential detected in {field}; use an opaque "
                "secret handle instead"
            )

    def _assert_encrypted(
        self,
        account: dict[str, Any],
        room_id: str,
    ) -> None:
        if not bool(self.policy.get("requireEncryptedRooms", True)):
            return
        completed = self._invoke(
            account,
            "",
            ["--rooms"],
            include_room=False,
        )
        if completed.returncode != 0:
            raise RuntimeError("Could not verify Matrix room encryption state")
        parsed = self._parse_json_output(completed.stdout)
        rooms = parsed if isinstance(parsed, list) else [parsed]
        target = next(
            (
                item
                for item in rooms
                if isinstance(item, dict) and str(item.get("room_id") or "") == room_id
            ),
            None,
        )
        if target is None:
            raise RuntimeError(
                "Allowed Matrix room is not present in the current account"
            )
        if not self._room_encryption_proven(target):
            raise RuntimeError(
                "Refusing Matrix operation because encrypted room state "
                "was not proven"
            )

    @staticmethod
    def _room_encryption_proven(value: object) -> bool:
        """Accept only explicit positive Matrix transport encryption fields."""

        def visit(item: object) -> bool:
            if isinstance(item, dict):
                for key, child in item.items():
                    normalized = str(key).casefold().replace("-", "_")
                    if normalized == "encrypted":
                        if child is True:
                            return True
                        if isinstance(child, str) and child.casefold() in {
                            "true",
                            "encrypted",
                        }:
                            return True
                        continue
                    if normalized == "encryption_state":
                        if (
                            isinstance(child, str)
                            and child.casefold() == "encrypted"
                        ):
                            return True
                        continue
                    if visit(child):
                        return True
            elif isinstance(item, list):
                return any(visit(child) for child in item)
            return False

        return visit(value)

    def _invoke(
        self,
        account: dict[str, Any],
        room_id: str,
        flags: list[str],
        *,
        stdin: bytes | None = None,
        include_room: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        executable = Path(str(self.transport.get("installPath") or "")).resolve()
        if not executable.is_file():
            raise RuntimeError("Matrix Commander transport is not installed")
        expected = str(self.transport.get("executableSha256") or "").casefold()
        if not expected or _sha256_file(executable) != expected:
            raise RuntimeError("Matrix Commander transport hash is not verified")
        arguments = [
            str(executable),
            "--credentials",
            str(Path(str(account.get("credentialsPath") or "")).resolve()),
            "--store",
            str(Path(str(account.get("storePath") or "")).resolve()),
            "--output",
            "json",
            "--timeout",
            str(
                max(
                    1,
                    min(
                        int(self.policy.get("commandTimeoutSeconds") or 60),
                        120,
                    ),
                )
            ),
        ]
        if include_room:
            arguments.extend(["--room", room_id])
        arguments.extend(flags)
        timeout = float(
            max(
                2,
                min(
                    int(self.policy.get("commandTimeoutSeconds") or 60) + 5,
                    125,
                ),
            )
        )
        return self._runner(arguments, stdin, timeout)

    @staticmethod
    def _run_subprocess(
        arguments: list[str],
        stdin: bytes | None,
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            arguments,
            input=stdin,
            capture_output=True,
            timeout=timeout,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )

    def _public_transport_result(
        self,
        completed: subprocess.CompletedProcess[bytes],
    ) -> dict[str, Any]:
        stdout = completed.stdout.decode("utf-8", errors="replace")
        stderr = completed.stderr.decode("utf-8", errors="replace")
        parsed = self._parse_json_output(completed.stdout)
        sanitized = self._sanitize(parsed)
        return {
            "exitCode": int(completed.returncode),
            "result": {
                "eventRefs": self._event_refs(sanitized),
                "responseItems": (
                    len(sanitized)
                    if isinstance(sanitized, list)
                    else 1 if sanitized else 0
                ),
            },
            "stderr": self._redact_text(stderr[:2000]),
            "stdoutBytes": len(stdout.encode("utf-8")),
        }

    @staticmethod
    def _event_refs(value: Any) -> list[str]:
        result: list[str] = []

        def visit(item: Any) -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    if str(key).casefold().replace("-", "_") in {
                        "event_id",
                        "eventid",
                    }:
                        result.append(_stable_ref("event", str(child)))
                    else:
                        visit(child)
            elif isinstance(item, list):
                for child in item:
                    visit(child)

        visit(value)
        return list(dict.fromkeys(result))

    @staticmethod
    def _parse_json_output(raw: bytes) -> Any:
        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            return []
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            rows = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    rows.append({"transportText": line[:2000]})
            return rows

    def _sanitize(self, value: Any) -> Any:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                normalized = str(key).casefold().replace("-", "_")
                if normalized in {
                    "access_token",
                    "refresh_token",
                    "password",
                    "secret",
                    "api_key",
                    "recovery_key",
                    "session_key",
                }:
                    continue
                if normalized == "user_id":
                    result[key] = _stable_ref("user", str(item))
                elif normalized == "device_id":
                    result[key] = _stable_ref("device", str(item))
                elif normalized == "room_id":
                    result[key] = _stable_ref("room", str(item))
                else:
                    result[key] = self._sanitize(item)
            return result
        if isinstance(value, list):
            return [self._sanitize(item) for item in value]
        if isinstance(value, str):
            return self._redact_text(value)
        return value

    @staticmethod
    def _redact_text(value: str) -> str:
        result = value
        for pattern in _LIKELY_SECRETS:
            result = pattern.sub("[REDACTED]", result)
        return result
