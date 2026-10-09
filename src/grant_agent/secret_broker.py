"""Opaque, one-time secret injection over a Bitwarden-compatible vault."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .capability_contracts import utc_now
from .durability import atomic_write_json
from .subprocess_utils import hidden_windows_subprocess_kwargs


SECRET_LEASE_SCHEMA = "neyvia.secret-lease-plan/v1"
SECRET_RECEIPT_SCHEMA = "neyvia.secret-use-receipt/v1"
SECRET_APPROVAL_SCHEMA = "neyvia.secret-delivery-approval/v1"
SECRET_REVOCATION_SCHEMA = "neyvia.secret-subject-revocation/v1"
_HANDLE_REF = re.compile(r"^secret-[a-f0-9]{16}$")
_DELIVERY_HANDLE = re.compile(r"^delivery-[a-f0-9]{32}$")
_APPROVAL_ID = re.compile(r"^approval_[a-f0-9]{20}$")
_SUBJECT_REF = re.compile(
    r"^(?:device|session)-[a-z0-9][a-z0-9._-]{7,63}$"
)
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SAFE_PRINCIPAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@-]{0,79}$")
_SECRET_FIELD = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|session|credential)"
)
_MAX_SECRET_BYTES = 64 * 1024
_REVOCATION_REASONS = {
    "compromised",
    "device-removed",
    "lost",
    "manual-security-action",
    "policy-change",
    "session-ended",
}


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


def _stable_ref(value: str) -> str:
    return "secret-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


BrokerRunner = Callable[
    [list[str], bytes | None, dict[str, str], float, Path | None],
    subprocess.CompletedProcess[bytes],
]


class SecretBrokerService:
    """Resolve secrets only inside a destination-bound execution boundary."""

    def __init__(
        self,
        root: str | Path,
        *,
        config_path: str | Path | None = None,
        runner: BrokerRunner | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        project_root = Path(__file__).resolve().parents[2]
        selected = Path(
            config_path
            or self.root / "config" / "neyvia_secret_broker.json"
        )
        if not selected.is_file():
            selected = project_root / "config" / "neyvia_secret_broker.json"
        if not selected.is_file():
            raise FileNotFoundError(selected)
        self.config_path = selected.resolve()
        self.config = json.loads(
            self.config_path.read_text(encoding="utf-8")
        )
        self._runner = runner or self._run_subprocess
        self.receipt_root = (
            self.root / ".agent_control" / "secret_broker" / "receipts"
        )
        self.revocation_root = (
            self.root / ".agent_control" / "secret_broker" / "revocations"
        )

    @property
    def stack(self) -> dict[str, Any]:
        value = self.config.get("stack")
        return dict(value) if isinstance(value, dict) else {}

    @property
    def policy(self) -> dict[str, Any]:
        value = self.config.get("policy")
        return dict(value) if isinstance(value, dict) else {}

    def compatibility_snapshot(self) -> dict[str, Any]:
        client = dict(self.stack.get("client") or {})
        executable = Path(str(client.get("installPath") or "")).resolve()
        expected = str(client.get("executableSha256") or "").casefold()
        actual = _sha256_file(executable) if executable.is_file() else ""
        server = dict(self.stack.get("server") or {})
        catalog = self.catalog()
        server_ready = str(server.get("state") or "").casefold() == "active"
        client_ready = bool(actual and expected and actual == expected)
        configured = bool(
            catalog["summary"]["accounts"]
            and catalog["summary"]["handles"]
            and catalog["summary"]["destinations"]
        )
        session_ready = bool(catalog["summary"]["sessionsAvailable"])
        delivery_ready = bool(
            server_ready and client_ready and configured and session_ready
        )
        return {
            "schema": "neyvia.secret-broker-compatibility/v1",
            "provider": "bitwarden-compatible",
            "deliveryReady": delivery_ready,
            "status": "ready" if delivery_ready else "unavailable",
            "unavailableReason": (
                ""
                if delivery_ready
                else "Vault service, verified client, account, or session is unavailable"
            ),
            "server": {
                "name": str(server.get("name") or ""),
                "version": str(server.get("version") or ""),
                "state": str(server.get("state") or ""),
            },
            "client": {
                "name": str(client.get("name") or ""),
                "version": str(client.get("version") or ""),
                "state": str(client.get("state") or ""),
                "installed": executable.is_file(),
                "hashVerified": bool(
                    actual and expected and actual == expected
                ),
                "signature": str(client.get("signature") or ""),
                "malwareScan": str(client.get("malwareScan") or ""),
            },
            "catalog": catalog,
            "policy": {
                "allowClipboard": bool(
                    self.policy.get("allowClipboard", False)
                ),
                "allowSecretInArguments": bool(
                    self.policy.get("allowSecretInArguments", False)
                ),
                "oneTimeLeases": bool(
                    self.policy.get("oneTimeLeases", True)
                ),
                "maxTtlSeconds": int(
                    self.policy.get("maxTtlSeconds") or 300
                ),
                "explicitApprovalRequired": True,
                "boundDeviceRequired": True,
                "boundSessionRequired": True,
                "subjectRevocation": True,
            },
            "sessionKeysExposed": False,
            "itemIdsExposed": False,
            "secretValuesExposed": False,
        }

    def bootstrap(self) -> dict[str, Any]:
        catalog = self.catalog()
        compatibility = self.compatibility_snapshot()
        return {
            "schema": "neyvia.secret-broker-bootstrap/v1",
            "provider": "vaultwarden-bitwarden-cli",
            "configuredAccounts": catalog["summary"]["accounts"],
            "configuredHandles": catalog["summary"]["handles"],
            "configuredDestinations": catalog["summary"]["destinations"],
            "deliveryReady": compatibility["deliveryReady"],
            "status": compatibility["status"],
            "clipboardDisabled": not bool(
                self.policy.get("allowClipboard", False)
            ),
            "secretValuesExposed": False,
            "detailsDeferred": True,
        }

    def catalog(self) -> dict[str, Any]:
        accounts = []
        for account in self._accounts():
            session_ref = str(account.get("sessionEnvRef") or "")
            accounts.append(
                {
                    "accountId": str(account.get("accountId") or ""),
                    "label": str(account.get("label") or ""),
                    "serverRef": self._server_ref(
                        str(account.get("serverUrl") or "")
                    ),
                    "sessionAvailable": bool(
                        self._read_env_reference(
                            session_ref,
                            required=False,
                        )
                    ),
                }
            )
        destinations = [
            {
                "destinationId": str(item.get("destinationId") or ""),
                "label": str(item.get("label") or ""),
                "worker": str(item.get("worker") or ""),
                "operations": self._string_list(item.get("operations")),
                "injectionMode": str(item.get("injectionMode") or "env"),
            }
            for item in self._destinations()
        ]
        handles = []
        for handle in self._handles():
            handles.append(
                {
                    "handleRef": self._handle_ref(handle),
                    "label": str(handle.get("label") or "Private secret"),
                    "kind": str(handle.get("kind") or "credential"),
                    "accountId": str(handle.get("accountId") or ""),
                    "allowedDestinations": self._string_list(
                        handle.get("allowedDestinations")
                    ),
                    "allowedOperations": self._string_list(
                        handle.get("allowedOperations")
                    ),
                }
            )
        return {
            "schema": "neyvia.secret-broker-catalog/v1",
            "accounts": accounts,
            "handles": handles,
            "destinations": destinations,
            "summary": {
                "accounts": len(accounts),
                "handles": len(handles),
                "destinations": len(destinations),
                "sessionsAvailable": sum(
                    1 for item in accounts if item["sessionAvailable"]
                ),
            },
            "sessionKeysExposed": False,
            "itemIdsExposed": False,
            "secretValuesExposed": False,
        }

    def plan_use(
        self,
        *,
        handle_ref: str,
        destination_id: str,
        operation: str,
        worker: str,
        actor: str,
        purpose: str,
        device_id: str,
        session_id: str,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        handle = self._resolve_handle(handle_ref)
        destination = self._resolve_destination(destination_id)
        normalized_destination = str(
            destination.get("destinationId") or ""
        ).casefold()
        normalized_operation = str(operation or "").strip().casefold()
        normalized_worker = str(worker or "").strip().casefold()
        if normalized_operation not in self._string_list(
            destination.get("operations")
        ):
            raise PermissionError(
                "Operation is outside the destination allowlist"
            )
        if normalized_operation not in self._string_list(
            handle.get("allowedOperations")
        ):
            raise PermissionError(
                "Operation is outside the secret-handle allowlist"
            )
        if normalized_destination not in self._string_list(
            handle.get("allowedDestinations")
        ):
            raise PermissionError(
                "Destination is outside the secret-handle allowlist"
            )
        if normalized_worker != str(
            destination.get("worker") or ""
        ).casefold():
            raise PermissionError("Worker does not match the destination policy")
        actor_label = self._validate_principal(actor, label="actor")
        purpose_text = str(purpose or "").strip()[:240]
        if not purpose_text:
            raise ValueError("purpose is required")
        normalized_device = self._validate_subject_ref(
            device_id,
            subject_type="device",
        )
        normalized_session = self._validate_subject_ref(
            session_id,
            subject_type="session",
        )
        default_ttl = int(self.policy.get("defaultTtlSeconds") or 60)
        maximum_ttl = int(self.policy.get("maxTtlSeconds") or 300)
        ttl = int(ttl_seconds if ttl_seconds is not None else default_ttl)
        if ttl < 1 or ttl > maximum_ttl:
            raise ValueError(f"ttlSeconds must be between 1 and {maximum_ttl}")
        now = datetime.now(timezone.utc)
        plan = {
            "schema": SECRET_LEASE_SCHEMA,
            "leaseId": f"secretlease_{uuid.uuid4().hex[:20]}",
            "deliveryHandle": f"delivery-{uuid.uuid4().hex}",
            "createdAt": now.isoformat().replace("+00:00", "Z"),
            "expiresAt": (
                now + timedelta(seconds=ttl)
            ).isoformat().replace("+00:00", "Z"),
            "ttlSeconds": ttl,
            "handleRef": handle_ref,
            "destinationId": normalized_destination,
            "operation": normalized_operation,
            "worker": normalized_worker,
            "actor": actor_label,
            "purpose": purpose_text,
            "deviceId": normalized_device,
            "sessionId": normalized_session,
            "injectionMode": str(
                destination.get("injectionMode") or "env"
            ),
            "oneTime": True,
            "summary": {
                "secretValueVisible": False,
                "approvalRequired": True,
                "clipboardUsed": False,
                "argumentsContainSecret": False,
                "destinationBound": True,
                "deviceBound": True,
                "sessionBound": True,
            },
        }
        plan["planHash"] = self._plan_hash(plan)
        return plan

    def use(
        self,
        plan: dict[str, Any],
        *,
        approved: bool = False,
        approval: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not approved or not isinstance(approval, dict):
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "secret.use",
                "reason": (
                    "A secret may be released only to its bound destination "
                    "after explicit approval."
                ),
            }
        self._validate_plan(plan)
        approval_record = self._validate_approval(
            approval,
            scope_hash=str(plan["planHash"]),
        )
        self._assert_subjects_active(plan)
        handle = self._resolve_handle(str(plan.get("handleRef") or ""))
        destination = self._resolve_destination(
            str(plan.get("destinationId") or "")
        )
        self._validate_binding(plan, handle, destination)
        reservation = self._reserve_delivery(plan)
        try:
            revoked = self._subject_revocation(plan)
            if revoked is not None:
                receipt = self._receipt_base(
                    plan,
                    approval_record=approval_record,
                    status="subject_revoked",
                    ok=False,
                )
                receipt["revokedSubjectType"] = revoked["subjectType"]
                atomic_write_json(reservation, receipt)
                return receipt
            secret = self._resolve_secret(handle)
            target = self._run_destination(
                destination,
                secret=secret,
            )
            stdout_raw = target.stdout.decode(
                "utf-8",
                errors="replace",
            )
            stderr_raw = target.stderr.decode(
                "utf-8",
                errors="replace",
            )
            leaked = bool(
                secret
                and (secret in stdout_raw or secret in stderr_raw)
            )
            stdout = self._sanitize_output(stdout_raw, secret)
            stderr = self._sanitize_output(stderr_raw, secret)
            ok = target.returncode == 0 and not leaked
            receipt = self._receipt_base(
                plan,
                approval_record=approval_record,
                status=(
                    "completed"
                    if ok
                    else (
                        "secret_output_policy_violation"
                        if leaked
                        else "destination_failed"
                    )
                ),
                ok=ok,
            )
            receipt.update({
                "exitCode": int(target.returncode),
                "stdoutSha256": hashlib.sha256(
                    stdout.encode("utf-8")
                ).hexdigest(),
                "stderrSha256": hashlib.sha256(
                    stderr.encode("utf-8")
                ).hexdigest(),
                "secretOutputDetected": leaked,
            })
            atomic_write_json(reservation, receipt)
            return receipt
        except BaseException as exc:
            failure = self._receipt_base(
                plan,
                approval_record=approval_record,
                status="broker_failed",
                ok=False,
            )
            failure.update({
                "reason": type(exc).__name__,
            })
            atomic_write_json(reservation, failure)
            return failure

    def revoke(
        self,
        plan: dict[str, Any],
        *,
        approved: bool = False,
        approval: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not approved or not isinstance(approval, dict):
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "secret.use",
            }
        self._validate_plan(plan, allow_expired=True)
        approval_record = self._validate_approval(
            approval,
            scope_hash=str(plan["planHash"]),
        )
        reservation = self._reserve_delivery(plan)
        receipt = self._receipt_base(
            plan,
            approval_record=approval_record,
            status="revoked",
            ok=True,
        )
        atomic_write_json(reservation, receipt)
        return receipt

    def revoke_subject(
        self,
        *,
        subject_type: str,
        subject_id: str,
        actor: str,
        reason_code: str,
        approved: bool = False,
        approval: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Durably block future deliveries for one device or session."""

        normalized_type = str(subject_type or "").strip().casefold()
        normalized_id = self._validate_subject_ref(
            subject_id,
            subject_type=normalized_type,
        )
        actor_label = self._validate_principal(actor, label="actor")
        normalized_reason = str(reason_code or "").strip().casefold()
        if normalized_reason not in _REVOCATION_REASONS:
            raise ValueError("Unsupported revocation reasonCode")
        scope_hash = self.subject_revocation_scope_hash(
            subject_type=normalized_type,
            subject_id=normalized_id,
            reason_code=normalized_reason,
        )
        if not approved or not isinstance(approval, dict):
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "secret.use",
                "scopeHash": scope_hash,
            }
        approval_record = self._validate_approval(
            approval,
            scope_hash=scope_hash,
        )
        self.revocation_root.mkdir(parents=True, exist_ok=True)
        target = self._revocation_path(normalized_type, normalized_id)
        if target.is_file():
            return {
                "schema": SECRET_REVOCATION_SCHEMA,
                "ok": True,
                "status": "already_revoked",
                "subjectType": normalized_type,
                "subjectId": normalized_id,
                "secretValuesExposed": False,
            }
        record = {
            "schema": SECRET_REVOCATION_SCHEMA,
            "revocationId": f"revocation_{uuid.uuid4().hex[:20]}",
            "createdAt": utc_now(),
            "subjectType": normalized_type,
            "subjectId": normalized_id,
            "actorRef": self._principal_ref(actor_label),
            "reasonCode": normalized_reason,
            "approvalId": approval_record["approvalId"],
            "scopeHash": scope_hash,
            "ok": True,
            "status": "revoked",
            "secretPersisted": False,
            "sessionKeysExposed": False,
            "itemIdsExposed": False,
            "secretValuesExposed": False,
        }
        self._atomic_create_json(target, record)
        return record

    def revocation_status(
        self,
        *,
        device_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        device = self._validate_subject_ref(device_id, subject_type="device")
        session = self._validate_subject_ref(
            session_id,
            subject_type="session",
        )
        device_revoked = self._revocation_path("device", device).is_file()
        session_revoked = self._revocation_path("session", session).is_file()
        return {
            "schema": "neyvia.secret-subject-status/v1",
            "deviceId": device,
            "sessionId": session,
            "deviceRevoked": device_revoked,
            "sessionRevoked": session_revoked,
            "deliveryAllowed": not (device_revoked or session_revoked),
            "secretValuesExposed": False,
        }

    @staticmethod
    def subject_revocation_scope_hash(
        *,
        subject_type: str,
        subject_id: str,
        reason_code: str,
    ) -> str:
        return _canonical_hash(
            {
                "action": "secret.subject-revoke",
                "subjectType": str(subject_type or "").strip().casefold(),
                "subjectId": str(subject_id or "").strip().casefold(),
                "reasonCode": str(reason_code or "").strip().casefold(),
            }
        )

    def audit(self, *, limit: int = 50) -> dict[str, Any]:
        bounded = max(1, min(int(limit), 200))
        rows = []
        files: list[Path] = []
        if self.receipt_root.is_dir():
            files.extend(self.receipt_root.glob("*.json"))
        if self.revocation_root.is_dir():
            files.extend(self.revocation_root.glob("*.json"))
        if files:
            files = sorted(
                files,
                key=lambda item: item.stat().st_mtime_ns,
                reverse=True,
            )
            for path in files[:bounded]:
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if value.get("schema") not in {
                    SECRET_RECEIPT_SCHEMA,
                    SECRET_REVOCATION_SCHEMA,
                }:
                    continue
                rows.append(
                    {
                        key: value.get(key)
                        for key in (
                            "receiptId",
                            "leaseId",
                            "deliveryHandle",
                            "revocationId",
                            "createdAt",
                            "handleRef",
                            "destinationId",
                            "operation",
                            "worker",
                            "actorRef",
                            "approverRef",
                            "approvalId",
                            "deviceId",
                            "sessionId",
                            "subjectType",
                            "subjectId",
                            "reasonCode",
                            "ok",
                            "status",
                            "exitCode",
                            "secretOutputDetected",
                            "leaseConsumed",
                        )
                        if key in value
                    }
                )
        return {
            "schema": "neyvia.secret-broker-audit/v1",
            "events": rows,
            "summary": {"events": len(rows), "limit": bounded},
            "sessionKeysExposed": False,
            "itemIdsExposed": False,
            "secretValuesExposed": False,
        }

    def _resolve_secret(self, handle: dict[str, Any]) -> str:
        account = self._resolve_account(str(handle.get("accountId") or ""))
        client = dict(self.stack.get("client") or {})
        executable = Path(str(client.get("installPath") or "")).resolve()
        expected = str(client.get("executableSha256") or "").casefold()
        if not executable.is_file() or _sha256_file(executable) != expected:
            raise RuntimeError("Verified Bitwarden CLI is unavailable")
        session = self._read_env_reference(
            str(account.get("sessionEnvRef") or ""),
            required=True,
        )
        app_data = self._validated_app_data(account)
        item_id = str(handle.get("itemId") or "")
        if not item_id or len(item_id) > 200:
            raise ValueError("Invalid internal vault item binding")
        field = str(handle.get("field") or "password").casefold()
        if field not in {"password", "username", "totp", "notes"}:
            raise ValueError("Unsupported vault field binding")
        arguments = [
            str(executable),
            "--nointeraction",
            "get",
            field,
            item_id,
            "--raw",
        ]
        environment = self._minimal_environment()
        environment["BW_SESSION"] = session
        environment["BITWARDENCLI_APPDATA_DIR"] = str(app_data)
        completed = self._runner(
            arguments,
            None,
            environment,
            float(self.policy.get("commandTimeoutSeconds") or 60),
            app_data,
        )
        if completed.returncode != 0:
            raise RuntimeError("Vault client could not resolve the secret")
        value = completed.stdout.decode("utf-8", errors="strict").rstrip(
            "\r\n"
        )
        size = len(value.encode("utf-8"))
        if not value or size > _MAX_SECRET_BYTES:
            raise RuntimeError("Vault returned an invalid secret payload")
        return value

    def _run_destination(
        self,
        destination: dict[str, Any],
        *,
        secret: str,
    ) -> subprocess.CompletedProcess[bytes]:
        executable = Path(str(destination.get("executable") or "")).resolve()
        expected = str(destination.get("executableSha256") or "").casefold()
        if not executable.is_file() or _sha256_file(executable) != expected:
            raise RuntimeError("Bound destination executable is unavailable")
        arguments = [str(executable), *self._string_list(destination.get("argv"))]
        serialized = "\0".join(arguments)
        if secret in serialized:
            raise RuntimeError("Secret would be placed in process arguments")
        mode = str(destination.get("injectionMode") or "env").casefold()
        if mode not in {"env", "stdin"}:
            raise ValueError("Only env and stdin injection are supported")
        environment = self._minimal_environment()
        fixed_env = destination.get("environment")
        if isinstance(fixed_env, dict):
            for key, value in fixed_env.items():
                name = str(key or "")
                if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", name):
                    raise ValueError("Invalid fixed destination environment name")
                if _SECRET_FIELD.search(name):
                    raise ValueError(
                        "Fixed destination environment may not contain secrets"
                    )
                environment[name] = str(value)
        stdin: bytes | None = None
        if mode == "env":
            env_name = str(destination.get("envName") or "")
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", env_name):
                raise ValueError("Invalid destination secret environment name")
            environment[env_name] = secret
        else:
            stdin = secret.encode("utf-8")
        working_directory = self._validated_working_directory(destination)
        return self._runner(
            arguments,
            stdin,
            environment,
            float(destination.get("timeoutSeconds") or 60),
            working_directory,
        )

    def _validate_plan(
        self,
        plan: dict[str, Any],
        *,
        allow_expired: bool = False,
    ) -> None:
        if not isinstance(plan, dict) or plan.get("schema") != SECRET_LEASE_SCHEMA:
            raise ValueError("Invalid secret lease schema")
        if str(plan.get("planHash") or "") != self._plan_hash(plan):
            raise ValueError("Secret lease hash does not match")
        if not _HANDLE_REF.fullmatch(str(plan.get("handleRef") or "")):
            raise ValueError("Invalid secret handle reference")
        if not _DELIVERY_HANDLE.fullmatch(
            str(plan.get("deliveryHandle") or "")
        ):
            raise ValueError("Invalid opaque delivery handle")
        self._validate_subject_ref(
            str(plan.get("deviceId") or ""),
            subject_type="device",
        )
        self._validate_subject_ref(
            str(plan.get("sessionId") or ""),
            subject_type="session",
        )
        if not bool(plan.get("oneTime")):
            raise ValueError("Secret leases must be one-time")
        expires = self._parse_timestamp(
            plan.get("expiresAt"),
            label="expiresAt",
        )
        if not allow_expired and expires <= datetime.now(timezone.utc):
            raise TimeoutError("Secret lease expired")

    def _validate_approval(
        self,
        approval: dict[str, Any],
        *,
        scope_hash: str,
    ) -> dict[str, Any]:
        if approval.get("schema") != SECRET_APPROVAL_SCHEMA:
            raise PermissionError("Invalid secret delivery approval")
        if approval.get("approved") is not True:
            raise PermissionError("Secret delivery was not approved")
        approval_id = str(approval.get("approvalId") or "")
        if not _APPROVAL_ID.fullmatch(approval_id):
            raise PermissionError("Invalid secret delivery approval")
        if str(approval.get("scopeHash") or "") != scope_hash:
            raise PermissionError("Secret delivery approval scope changed")
        approved_by = self._validate_principal(
            approval.get("approvedBy"),
            label="approvedBy",
        )
        approved_at = self._parse_timestamp(
            approval.get("approvedAt"),
            label="approvedAt",
        )
        now = datetime.now(timezone.utc)
        if approved_at > now + timedelta(seconds=30):
            raise PermissionError("Secret delivery approval time is invalid")
        maximum_ttl = int(self.policy.get("maxTtlSeconds") or 300)
        if approved_at < now - timedelta(seconds=maximum_ttl):
            raise PermissionError("Secret delivery approval expired")
        return {
            "approvalId": approval_id,
            "approverRef": self._principal_ref(approved_by),
            "approvedAt": approved_at.isoformat().replace("+00:00", "Z"),
        }

    def _validate_binding(
        self,
        plan: dict[str, Any],
        handle: dict[str, Any],
        destination: dict[str, Any],
    ) -> None:
        destination_id = str(plan.get("destinationId") or "")
        operation = str(plan.get("operation") or "")
        if destination_id != str(destination.get("destinationId") or ""):
            raise PermissionError("Destination binding changed")
        if destination_id not in self._string_list(
            handle.get("allowedDestinations")
        ):
            raise PermissionError("Secret is not allowed for this destination")
        if operation not in self._string_list(handle.get("allowedOperations")):
            raise PermissionError("Secret is not allowed for this operation")
        if operation not in self._string_list(destination.get("operations")):
            raise PermissionError("Destination does not allow this operation")
        if str(plan.get("worker") or "") != str(
            destination.get("worker") or ""
        ).casefold():
            raise PermissionError("Worker binding changed")
        if str(plan.get("injectionMode") or "") != str(
            destination.get("injectionMode") or "env"
        ).casefold():
            raise PermissionError("Injection mode binding changed")

    @staticmethod
    def _plan_hash(plan: dict[str, Any]) -> str:
        payload = copy.deepcopy(plan)
        payload.pop("planHash", None)
        return _canonical_hash(payload)

    def _reserve_delivery(self, plan: dict[str, Any]) -> Path:
        lease_id = str(plan.get("leaseId") or "")
        if not re.fullmatch(r"secretlease_[a-f0-9]{20}", lease_id):
            raise ValueError("Invalid leaseId")
        delivery_handle = str(plan.get("deliveryHandle") or "")
        if not _DELIVERY_HANDLE.fullmatch(delivery_handle):
            raise ValueError("Invalid opaque delivery handle")
        self.receipt_root.mkdir(parents=True, exist_ok=True)
        target = self.receipt_root / f"{delivery_handle}.json"
        self._atomic_create_json(
            target,
            {
                "schema": "neyvia.secret-lease-reservation/v1",
                "leaseId": lease_id,
                "deliveryHandle": delivery_handle,
                "reservedAt": utc_now(),
            },
            conflict_message="Secret delivery handle was already consumed",
        )
        return target

    def _receipt_base(
        self,
        plan: dict[str, Any],
        *,
        approval_record: dict[str, Any],
        status: str,
        ok: bool,
    ) -> dict[str, Any]:
        return {
            "schema": SECRET_RECEIPT_SCHEMA,
            "receiptId": f"secretreceipt_{uuid.uuid4().hex[:20]}",
            "leaseId": str(plan["leaseId"]),
            "deliveryHandle": str(plan["deliveryHandle"]),
            "planHash": str(plan["planHash"]),
            "createdAt": utc_now(),
            "handleRef": str(plan["handleRef"]),
            "destinationId": str(plan["destinationId"]),
            "operation": str(plan["operation"]),
            "worker": str(plan["worker"]),
            "actorRef": self._principal_ref(str(plan["actor"])),
            "deviceId": str(plan["deviceId"]),
            "sessionId": str(plan["sessionId"]),
            "approvalId": str(approval_record["approvalId"]),
            "approverRef": str(approval_record["approverRef"]),
            "ok": bool(ok),
            "status": str(status),
            "secretPersisted": False,
            "secretInArguments": False,
            "clipboardUsed": False,
            "sessionKeysExposed": False,
            "itemIdsExposed": False,
            "secretValuesExposed": False,
            "outputReturned": False,
            "leaseConsumed": True,
            "deliveryConsumed": True,
        }

    def _assert_subjects_active(self, plan: dict[str, Any]) -> None:
        if self._subject_revocation(plan) is not None:
            raise PermissionError("Secret delivery subject is revoked")

    def _subject_revocation(
        self,
        plan: dict[str, Any],
    ) -> dict[str, str] | None:
        subjects = (
            ("device", str(plan.get("deviceId") or "")),
            ("session", str(plan.get("sessionId") or "")),
        )
        for subject_type, subject_id in subjects:
            if self._revocation_path(subject_type, subject_id).is_file():
                return {
                    "subjectType": subject_type,
                    "subjectId": subject_id,
                }
        return None

    def _revocation_path(self, subject_type: str, subject_id: str) -> Path:
        digest = hashlib.sha256(
            f"{subject_type}\0{subject_id}".encode("utf-8")
        ).hexdigest()
        return self.revocation_root / f"{subject_type}-{digest}.json"

    @staticmethod
    def _atomic_create_json(
        target: Path,
        value: dict[str, Any],
        *,
        conflict_message: str = "Revocation already exists",
    ) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                target,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:
            raise PermissionError(conflict_message) from exc
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    value,
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            target.unlink(missing_ok=True)
            raise

    @staticmethod
    def _validate_subject_ref(value: object, *, subject_type: str) -> str:
        normalized_type = str(subject_type or "").strip().casefold()
        if normalized_type not in {"device", "session"}:
            raise ValueError("subjectType must be device or session")
        normalized = str(value or "").strip().casefold()
        if (
            not _SUBJECT_REF.fullmatch(normalized)
            or not normalized.startswith(f"{normalized_type}-")
        ):
            raise ValueError(f"Invalid {normalized_type}Id")
        return normalized

    @staticmethod
    def _validate_principal(value: object, *, label: str) -> str:
        normalized = str(value or "").strip()
        if not _SAFE_PRINCIPAL.fullmatch(normalized):
            raise ValueError(f"Invalid {label}")
        return normalized

    @staticmethod
    def _principal_ref(value: str) -> str:
        return "principal-" + hashlib.sha256(
            value.encode("utf-8")
        ).hexdigest()[:16]

    @staticmethod
    def _parse_timestamp(value: object, *, label: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(
                str(value or "").replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(f"Invalid {label}") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"Invalid {label}")
        return parsed.astimezone(timezone.utc)

    def _resolve_handle(self, handle_ref: str) -> dict[str, Any]:
        if not _HANDLE_REF.fullmatch(str(handle_ref or "")):
            raise ValueError("Invalid opaque secret handle")
        handle = next(
            (
                item
                for item in self._handles()
                if self._handle_ref(item) == handle_ref
            ),
            None,
        )
        if handle is None:
            raise KeyError("Unknown or disallowed secret handle")
        return handle

    def _resolve_destination(self, destination_id: str) -> dict[str, Any]:
        normalized = str(destination_id or "").strip().casefold()
        if not _SAFE_ID.fullmatch(normalized):
            raise ValueError("Invalid destinationId")
        destination = next(
            (
                item
                for item in self._destinations()
                if str(item.get("destinationId") or "").casefold()
                == normalized
            ),
            None,
        )
        if destination is None:
            raise KeyError("Unknown secret destination")
        return destination

    def _resolve_account(self, account_id: str) -> dict[str, Any]:
        normalized = str(account_id or "").strip().casefold()
        if not _SAFE_ID.fullmatch(normalized):
            raise ValueError("Invalid vault accountId")
        account = next(
            (
                item
                for item in self._accounts()
                if str(item.get("accountId") or "").casefold() == normalized
            ),
            None,
        )
        if account is None:
            raise KeyError("Unknown vault account")
        return account

    def _validated_app_data(self, account: dict[str, Any]) -> Path:
        state_root = Path(str(self.policy.get("stateRoot") or "")).resolve()
        app_data = Path(str(account.get("appDataDir") or "")).resolve()
        try:
            app_data.relative_to(state_root)
        except ValueError as exc:
            raise ValueError(
                "Vault client state must remain under the configured state root"
            ) from exc
        app_data.mkdir(parents=True, exist_ok=True)
        return app_data

    def _validated_working_directory(
        self,
        destination: dict[str, Any],
    ) -> Path:
        value = str(destination.get("workingDirectory") or self.root)
        path = Path(value)
        if not path.is_absolute():
            path = self.root / path
        path = path.resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(
                "Secret destination working directory must be in the workspace"
            ) from exc
        if not path.is_dir():
            raise ValueError("Secret destination working directory is missing")
        return path

    def _accounts(self) -> list[dict[str, Any]]:
        return self._objects(self.policy.get("accounts"))

    def _handles(self) -> list[dict[str, Any]]:
        return self._objects(self.policy.get("handles"))

    def _destinations(self) -> list[dict[str, Any]]:
        return self._objects(self.policy.get("destinations"))

    @staticmethod
    def _objects(value: object) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [dict(item) for item in value if isinstance(item, dict)]

    @staticmethod
    def _string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        result = []
        for item in value:
            text = str(item or "").strip().casefold()
            if text and text not in result:
                result.append(text)
        return result

    @staticmethod
    def _server_ref(server_url: str) -> str:
        return "server-" + hashlib.sha256(
            server_url.encode("utf-8")
        ).hexdigest()[:16]

    @staticmethod
    def _handle_ref(handle: dict[str, Any]) -> str:
        material = "\0".join(
            [
                str(handle.get("accountId") or ""),
                str(handle.get("itemId") or ""),
                str(handle.get("field") or "password"),
            ]
        )
        return _stable_ref(material)

    @staticmethod
    def _read_env_reference(
        reference: str,
        *,
        required: bool,
    ) -> str:
        if not reference.startswith("env:"):
            if required:
                raise ValueError("Session must use an environment reference")
            return ""
        name = reference[4:]
        if not re.fullmatch(r"NEYVIA_[A-Z0-9_]{1,96}", name):
            if required:
                raise ValueError("Invalid session environment reference")
            return ""
        value = os.environ.get(name, "")
        if required and not value:
            raise RuntimeError("Vault session is unavailable")
        return value

    @staticmethod
    def _minimal_environment() -> dict[str, str]:
        result: dict[str, str] = {}
        for name in (
            "SystemRoot",
            "WINDIR",
            "ComSpec",
            "TEMP",
            "TMP",
            "PATH",
            "LANG",
        ):
            value = os.environ.get(name)
            if value:
                result[name] = value
        return result

    @staticmethod
    def _sanitize_output(value: str, secret: str) -> str:
        result = value.replace(secret, "[REDACTED]") if secret else value
        result = re.sub(
            r"(?i)\b(password|passwd|secret|token|api[_ -]?key)"
            r"\s*[:=]\s*\S+",
            r"\1=[REDACTED]",
            result,
        )
        return result[:16_384]

    @staticmethod
    def _run_subprocess(
        arguments: list[str],
        stdin: bytes | None,
        environment: dict[str, str],
        timeout: float,
        working_directory: Path | None,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            arguments,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=max(1.0, min(float(timeout), 300.0)),
            env=environment,
            cwd=str(working_directory) if working_directory else None,
            **hidden_windows_subprocess_kwargs(),
        )
