"""Provider-neutral private-mesh control and service-discovery boundary."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .capability_contracts import canonical_hash, normalized_strings, utc_now
from .durability import atomic_write_json
from .subprocess_utils import hidden_windows_subprocess_kwargs


MESH_SNAPSHOT_SCHEMA = "neyvia.mesh-snapshot/v1"
MESH_PROBE_SCHEMA = "neyvia.mesh-probe/v1"
MESH_SERVICE_CATALOG_SCHEMA = "neyvia.mesh-service-catalog/v1"
MESH_MIGRATION_PLAN_SCHEMA = "neyvia.mesh-migration-plan/v1"
MESH_IDENTITY_STATE_SCHEMA = "neyvia.mesh-identity-state/v1"
MESH_IDENTITY_SNAPSHOT_SCHEMA = "neyvia.mesh-identity-snapshot/v1"
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
_PROBE_TARGET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.:%_-]{0,254}$")
_OPAQUE_REF = re.compile(
    r"^(?:mesh-enroll|mesh-device|mesh-rotation|mesh-recovery|mesh-acl|"
    r"mesh-plan|mesh-approval|mesh-provider)"
    r"-[a-f0-9]{20}$"
)
_KEY_FINGERPRINT = re.compile(r"^(?:sha256:)?[a-fA-F0-9]{64}$")
_VERIFIER_KEY_ID = re.compile(r"^sha256:[a-f0-9]{64}$")
_ACL_ACTION = re.compile(r"^[a-z][a-z0-9._:-]{0,127}$")
_FORBIDDEN_KEY = re.compile(
    r"(?:password|passwd|secret|token|private.?key|credential)",
    re.IGNORECASE,
)
_PLATFORMS = frozenset(
    {"windows", "android", "ios", "macos", "linux", "nas", "web"}
)
_MUTATION_OPERATIONS = frozenset(
    {
        "prepare_enrollment",
        "stage_identity",
        "request_key_rotation",
        "transition_key_rotation",
        "revoke_device",
        "set_device_trust",
        "upsert_acl_rule",
        "request_device_recovery",
        "transition_device_recovery",
        "advertise_service",
        "revoke_service",
    }
)
_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


def _process_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(str(path.resolve()))
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(key, threading.RLock())


@contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    """Serialize state transitions across instances and worker processes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with _process_lock(path):
        with path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
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


class MeshService:
    """Expose mesh truth without leaking provider credentials or control keys."""

    def __init__(
        self,
        root: str | Path,
        *,
        config_path: str | Path | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        project_root = Path(__file__).resolve().parents[2]
        trusted_config_text = str(
            os.environ.get("NEYVIA_MESH_TRUSTED_CONFIG") or ""
        ).strip()
        explicitly_provisioned_config = (
            config_path is not None or bool(trusted_config_text)
        )
        selected = Path(
            config_path
            or trusted_config_text
            or self.root / "config" / "neyvia_mesh.json"
        )
        if not selected.is_file():
            selected = project_root / "config" / "neyvia_mesh.json"
        if not selected.is_file():
            raise FileNotFoundError(selected)
        self.config_path = selected.resolve()
        self.config = json.loads(
            self.config_path.read_text(encoding="utf-8")
        )
        try:
            self.config_path.relative_to(self.root)
        except ValueError:
            config_outside_workspace = True
        else:
            config_outside_workspace = False
        self.verifier_config_authoritative = (
            explicitly_provisioned_config and config_outside_workspace
        )
        self.state_root = self.root / ".agent_control" / "mesh"
        self.probe_path = self.state_root / "probes.json"
        self.services_path = self.state_root / "services.json"
        self.identity_path = self.state_root / "identity.json"
        self.state_lock_path = self.state_root / "state.lock"
        self.services_lock_path = self.state_root / "services.lock"
        self.probes_lock_path = self.state_root / "probes.lock"
        verifier = (
            dict(self.config.get("approvalVerifier") or {})
            if self.verifier_config_authoritative
            else {}
        )
        protected_text = str(
            verifier.get("protectedStateRoot") or ""
        ).strip()
        public_key_text = str(
            verifier.get("publicKeyPath") or ""
        ).strip()
        self.protected_state_root = (
            Path(protected_text).resolve() if protected_text else None
        )
        self.protected_state_root_configured_absolute = bool(
            protected_text and Path(protected_text).is_absolute()
        )
        self.approval_public_key_path = (
            Path(public_key_text).resolve() if public_key_text else None
        )
        self.approval_public_key_configured_absolute = bool(
            public_key_text and Path(public_key_text).is_absolute()
        )
        self.approval_verifier_key_id = str(
            verifier.get("keyId") or ""
        ).strip().casefold()
        enrollment_verifier = (
            dict(self.config.get("providerEnrollmentVerifier") or {})
            if self.verifier_config_authoritative
            else {}
        )
        enrollment_public_key_text = str(
            enrollment_verifier.get("publicKeyPath") or ""
        ).strip()
        self.enrollment_public_key_path = (
            Path(enrollment_public_key_text).resolve()
            if enrollment_public_key_text
            else None
        )
        self.enrollment_public_key_configured_absolute = bool(
            enrollment_public_key_text
            and Path(enrollment_public_key_text).is_absolute()
        )
        self.enrollment_verifier_key_id = str(
            enrollment_verifier.get("keyId") or ""
        ).strip().casefold()
        self.approval_ledger_path = (
            self.protected_state_root / "consumed_mesh_approvals.json"
            if self.protected_state_root is not None
            else None
        )
        self.approval_ledger_lock_path = (
            self.protected_state_root / "approval_ledger.lock"
            if self.protected_state_root is not None
            else None
        )
        self._lock = threading.RLock()
        self._snapshot_cache: tuple[float, dict[str, Any]] | None = None

    @property
    def policy(self) -> dict[str, Any]:
        value = self.config.get("policy")
        return dict(value) if isinstance(value, dict) else {}

    @property
    def budgets(self) -> dict[str, Any]:
        value = self.config.get("performanceBudgets")
        return dict(value) if isinstance(value, dict) else {}

    def snapshot(self, *, refresh: bool = False) -> dict[str, Any]:
        if not isinstance(refresh, bool):
            raise TypeError("refresh must be a boolean")
        started = time.perf_counter()
        ttl = max(
            0.1,
            float(self.budgets.get("statusCacheTtlSeconds") or 3),
        )
        with self._lock:
            cached = self._snapshot_cache
            if (
                not refresh
                and cached is not None
                and time.monotonic() - cached[0] <= ttl
            ):
                result = dict(cached[1])
                result["cache"] = "hit"
                result["durationMs"] = round(
                    (time.perf_counter() - started) * 1000.0,
                    3,
                )
                return result

        selected = str(
            self.config.get("selectedProvider") or "tailscale-bridge"
        )
        provider = (
            self._tailscale_snapshot()
            if selected == "tailscale-bridge"
            else self._netbird_snapshot()
            if selected == "netbird"
            else {
                "providerId": selected,
                "available": False,
                "state": "unsupported",
                "error": "The selected mesh provider has no approved adapter.",
                "self": None,
                "peers": [],
            }
        )
        result = {
            "schema": MESH_SNAPSHOT_SCHEMA,
            "generatedAt": utc_now(),
            "selectedProvider": selected,
            "targetProvider": str(
                self.config.get("targetProvider") or ""
            ),
            "cutoverEnabled": bool(self.config.get("cutoverEnabled")),
            "policy": self.policy,
            "performanceBudgets": self.budgets,
            "provider": provider,
            "recentProbes": self._recent_probes(),
            "summary": {
                "available": bool(provider.get("available")),
                "onlinePeers": sum(
                    1 for row in provider.get("peers") or [] if row["online"]
                ),
                "totalPeers": len(provider.get("peers") or []),
                "directActive": sum(
                    1
                    for row in provider.get("peers") or []
                    if row["routeState"] == "direct"
                ),
                "relayedActive": sum(
                    1
                    for row in provider.get("peers") or []
                    if row["routeState"] in {"relay", "peer-relay"}
                ),
            },
            "cache": "miss",
        }
        result["durationMs"] = round(
            (time.perf_counter() - started) * 1000.0,
            3,
        )
        with self._lock:
            self._snapshot_cache = (time.monotonic(), dict(result))
        return result

    def bootstrap(self) -> dict[str, Any]:
        """Return only static mesh routing metadata for compact app bootstrap."""

        services = self._read_services()["services"]
        identity = self._read_identity_state()
        return {
            "schema": "neyvia.mesh-bootstrap/v1",
            "selectedProvider": str(
                self.config.get("selectedProvider") or ""
            ),
            "targetProvider": str(
                self.config.get("targetProvider") or ""
            ),
            "cutoverEnabled": bool(self.config.get("cutoverEnabled")),
            "registeredServices": len(services),
            "knownDeviceIdentities": len(identity["devices"]),
            "detailsDeferred": True,
        }

    def identity_snapshot(self) -> dict[str, Any]:
        """Return durable local identity intent and policy state."""

        with self._identity_transaction() as state:
            expired_changed = self._expire_enrollment_intents(state)
            lifecycle_changed = self._expire_lifecycle_requests(state)
            snapshot_revision = int(state.get("revision") or 0) + int(
                expired_changed or lifecycle_changed
            )
            enrollments = sorted(
                (dict(row) for row in state["enrollments"].values()),
                key=lambda row: str(row.get("createdAt") or ""),
            )
            devices = sorted(
                (dict(row) for row in state["devices"].values()),
                key=lambda row: str(row.get("createdAt") or ""),
            )
            rotations = sorted(
                (dict(row) for row in state["rotations"].values()),
                key=lambda row: str(row.get("createdAt") or ""),
            )
            recoveries = sorted(
                (dict(row) for row in state["recoveries"].values()),
                key=lambda row: str(row.get("createdAt") or ""),
            )
            acl_rules = sorted(
                (dict(row) for row in state["aclRules"]),
                key=lambda row: (
                    -int(row.get("priority") or 0),
                    str(row.get("ruleRef") or ""),
                ),
            )
        return {
            "schema": MESH_IDENTITY_SNAPSHOT_SCHEMA,
            "revision": snapshot_revision,
            "generatedAt": utc_now(),
            "enrollments": enrollments,
            "devices": devices,
            "keyRotations": rotations,
            "recoveries": recoveries,
            "aclRules": acl_rules,
            "summary": {
                "pendingEnrollments": sum(
                    1
                    for row in enrollments
                    if row.get("state")
                    in {"pending", "local_identity_staged"}
                ),
                "devices": len(devices),
                "trustedLocal": sum(
                    1
                    for row in devices
                    if row.get("trustState") == "trusted_local"
                ),
                "quarantined": sum(
                    1
                    for row in devices
                    if row.get("trustState")
                    in {"quarantined", "recovery_pending"}
                ),
                "revoked": sum(
                    1 for row in devices if row.get("state") == "revoked"
                ),
                "pendingRotations": sum(
                    1
                    for row in rotations
                    if row.get("state") in {"requested", "staged_local"}
                ),
                "aclRules": len(acl_rules),
            },
            "identifiersOpaque": True,
            "privateKeysStored": False,
            "credentialsExposed": False,
            "providerActionsPerformed": False,
        }

    def enrollment_and_trust_status(self) -> dict[str, Any]:
        """Combine enrollment, route trust, service, and migration truth for operators."""

        identity = self.identity_snapshot()
        network = self.snapshot()
        services = self.service_catalog()
        migration = self.migration_plan()
        provider = dict(network.get("provider") or {})
        peers = [
            dict(row)
            for row in provider.get("peers") or []
            if isinstance(row, dict)
        ]
        devices = [
            dict(row)
            for row in identity.get("devices") or []
            if isinstance(row, dict)
        ]
        enrollments = [
            dict(row)
            for row in identity.get("enrollments") or []
            if isinstance(row, dict)
        ]
        return {
            "schema": "neyvia.mesh-enrollment-trust/v1",
            "generatedAt": utc_now(),
            "enrollment": {
                "pending": [
                    row
                    for row in enrollments
                    if row.get("state") in {"pending", "local_identity_staged"}
                ],
                "all": enrollments,
                "providerVerifierReady": self._enrollment_verifier_ready(),
                "providerActionsPerformed": False,
            },
            "trust": {
                "devices": devices,
                "peers": peers,
                "summary": {
                    **dict(identity.get("summary") or {}),
                    "directActive": sum(
                        1 for row in peers if row.get("routeState") == "direct"
                    ),
                    "relayedActive": sum(
                        1
                        for row in peers
                        if row.get("routeState") in {"relay", "peer-relay"}
                    ),
                },
                "credentialsExposed": False,
            },
            "services": {
                **services,
                "deviceRevocationImplemented": True,
            },
            "migration": migration,
        }

    def plan_identity_mutation(
        self,
        operation: str,
        *,
        device_ref: str,
        payload: dict[str, Any],
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        """Return a non-authoritative plan for an external approval broker."""

        normalized_operation = str(operation or "").strip().casefold()
        if normalized_operation not in _MUTATION_OPERATIONS:
            raise ValueError("Unsupported mesh identity mutation operation")
        if not isinstance(payload, dict):
            raise TypeError("payload must be an object")
        self._reject_secret_keys(payload)
        normalized_device = str(device_ref or "").strip().casefold()
        if normalized_device not in {"", "*"}:
            if not _OPAQUE_REF.fullmatch(normalized_device):
                raise ValueError("Invalid mutation device binding")
        ttl = int(ttl_seconds)
        if ttl < 60 or ttl > 900:
            raise ValueError("ttlSeconds must be between 60 and 900")
        now = datetime.now(UTC)
        with self._identity_transaction() as state:
            plan_ref = self._new_ref("mesh-plan")
            plan = {
                "schema": "neyvia.mesh-mutation-plan/v1",
                "planRef": plan_ref,
                "operation": normalized_operation,
                "deviceRef": normalized_device,
                "payloadHash": canonical_hash(payload),
                "policyHash": self._identity_policy_hash(state),
                "baseRevision": int(state.get("revision") or 0),
                "createdAt": now.isoformat().replace("+00:00", "Z"),
                "expiresAt": (
                    now + timedelta(seconds=ttl)
                ).isoformat().replace("+00:00", "Z"),
                "oneTime": True,
                "credentialsExposed": False,
            }
            plan["planHash"] = self._mesh_plan_hash(plan)
        return {
            "schema": "neyvia.mesh-mutation-plan-result/v1",
            "ok": True,
            "status": "operator_approval_required",
            "plan": plan,
            "requiredPermission": "network.write",
            "authority": "external-signed-broker-receipt-required",
            "planPersisted": False,
            "credentialsExposed": False,
        }

    def prepare_device_enrollment(
        self,
        *,
        device_label: str,
        platform: str,
        requested_by: str,
        ttl_seconds: int = 900,
        approval_receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a short-lived, secret-free enrollment intent."""

        if not isinstance(approval_receipt, dict):
            return self._approval_required(
                "network.write",
                "Preparing a device enrollment requires explicit approval.",
            )
        label = self._bounded_text(
            device_label,
            field="deviceLabel",
            maximum=120,
        )
        normalized_platform = str(platform or "").strip().casefold()
        if normalized_platform not in _PLATFORMS:
            raise ValueError("Unsupported mesh device platform")
        actor = self._bounded_text(
            requested_by,
            field="requestedBy",
            maximum=120,
        )
        ttl = int(ttl_seconds)
        if ttl < 300 or ttl > 3600:
            raise ValueError("ttlSeconds must be between 300 and 3600")
        mutation_payload = {
            "deviceLabel": label,
            "platform": normalized_platform,
            "requestedBy": actor,
            "ttlSeconds": ttl,
        }
        now = datetime.now(UTC)
        now_text = now.isoformat().replace("+00:00", "Z")
        enrollment_ref = self._new_ref("mesh-enroll")
        record = {
            "schema": "neyvia.mesh-enrollment-intent/v1",
            "enrollmentRef": enrollment_ref,
            "deviceLabel": label,
            "platform": normalized_platform,
            "requestedBy": actor,
            "state": "pending",
            "createdAt": now_text,
            "updatedAt": now_text,
            "expiresAt": (
                now + timedelta(seconds=ttl)
            ).isoformat().replace("+00:00", "Z"),
            "deviceRef": "",
            "providerEnrollmentProven": False,
            "providerActionPerformed": False,
            "enrollmentSecretStored": False,
            "credentialsExposed": False,
        }
        with self._identity_transaction() as state:
            self._consume_approval(
                approval_receipt,
                operation="prepare_enrollment",
                device_ref="",
                payload=mutation_payload,
                state=state,
            )
            self._expire_enrollment_intents(state)
            state["enrollments"][enrollment_ref] = record
        return {
            "schema": "neyvia.mesh-enrollment-intent-result/v1",
            "ok": True,
            "status": "intent_prepared",
            "enrollment": record,
            "providerActionPerformed": False,
            "providerEnrollmentProven": False,
            "nextAction": (
                "Bind a public-key fingerprint locally, then complete "
                "enrollment through a verified provider control-plane adapter."
            ),
            "identifiersOpaque": True,
            "credentialsExposed": False,
        }

    def stage_device_identity(
        self,
        enrollment_ref: str,
        *,
        public_key_fingerprint: str,
        provider_enrollment_receipt: dict[str, Any] | None = None,
        approval_receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Import a provider-verified immutable identity without private keys."""

        normalized_ref = self._validate_ref(
            enrollment_ref,
            prefix="mesh-enroll",
        )
        if not isinstance(approval_receipt, dict):
            return self._approval_required(
                "network.write",
                "Staging a device identity requires explicit approval.",
                enrollmentRef=normalized_ref,
            )
        if not isinstance(provider_enrollment_receipt, dict):
            return {
                "ok": False,
                "status": "provider_enrollment_proof_required",
                "enrollmentRef": normalized_ref,
                "providerActionPerformed": False,
                "providerEnrollmentProven": False,
            }
        fingerprint_hash = self._fingerprint_hash(public_key_fingerprint)
        verified_enrollment = self._verify_provider_enrollment_receipt(
            provider_enrollment_receipt,
            enrollment_ref=normalized_ref,
            fingerprint_hash=fingerprint_hash,
        )
        device_ref = verified_enrollment["deviceRef"]
        mutation_payload = {
            "enrollmentRef": normalized_ref,
            "publicKeyFingerprint": self._normalized_fingerprint(
                public_key_fingerprint
            ),
            "providerEnrollmentReceiptHash": canonical_hash(
                provider_enrollment_receipt
            ),
        }
        now = utc_now()
        with self._identity_transaction() as state:
            self._consume_approval(
                approval_receipt,
                operation="stage_identity",
                device_ref="",
                payload=mutation_payload,
                state=state,
            )
            self._expire_enrollment_intents(state)
            enrollment = state["enrollments"].get(normalized_ref)
            if not isinstance(enrollment, dict):
                raise KeyError(
                    f"Unknown mesh enrollment intent: {normalized_ref}"
                )
            if enrollment.get("state") == "expired":
                raise RuntimeError("Mesh enrollment intent has expired")
            if enrollment.get("state") != "pending":
                raise RuntimeError(
                    "Mesh enrollment intent is not in the pending state"
                )
            duplicate_key = next(
                (
                    row
                    for row in state["devices"].values()
                    if row.get("keyFingerprintSha256") == fingerprint_hash
                    and row.get("state") != "revoked"
                ),
                None,
            )
            if duplicate_key is not None:
                raise RuntimeError(
                    "This public-key fingerprint already has an active "
                    "local mesh identity"
                )
            duplicate_node = next(
                (
                    row
                    for row in state["devices"].values()
                    if row.get("providerId")
                    == verified_enrollment["providerId"]
                    and row.get("providerNodeIdSha256")
                    == verified_enrollment["providerNodeIdSha256"]
                ),
                None,
            )
            if duplicate_node is not None or device_ref in state["devices"]:
                raise RuntimeError(
                    "This immutable provider node identity already exists"
                )
            device = {
                "schema": "neyvia.mesh-device-identity/v1",
                "deviceRef": device_ref,
                "enrollmentRef": normalized_ref,
                "deviceLabel": str(enrollment.get("deviceLabel") or ""),
                "platform": str(enrollment.get("platform") or ""),
                "state": "provider_enrollment_verified",
                "trustState": "unverified",
                "recoveryState": "none",
                "stateVersion": 1,
                "keyGeneration": 1,
                "keyFingerprintSha256": fingerprint_hash,
                "providerId": verified_enrollment["providerId"],
                "providerNodeIdSha256": verified_enrollment[
                    "providerNodeIdSha256"
                ],
                "providerEnrollmentReceiptId": verified_enrollment[
                    "receiptId"
                ],
                "createdAt": now,
                "updatedAt": now,
                "localAccessDisabled": False,
                "providerEnrollmentProven": True,
                "providerRevocationProven": False,
                "privateKeyStored": False,
                "credentialsExposed": False,
            }
            enrollment.update(
                {
                    "state": "provider_enrollment_verified",
                    "updatedAt": now,
                    "deviceRef": device_ref,
                    "providerEnrollmentProven": True,
                    "providerActionPerformed": False,
                }
            )
            state["devices"][device_ref] = device
        return {
            "schema": "neyvia.mesh-device-stage-result/v1",
            "ok": True,
            "status": "verified_identity_staged",
            "device": device,
            "enrollment": enrollment,
            "localIdentityCreated": True,
            "providerActionPerformed": False,
            "providerEnrollmentProven": True,
            "identityDerivedFromImmutableProviderNodeId": True,
            "credentialsExposed": False,
        }

    def request_key_rotation(
        self,
        device_ref: str,
        *,
        requested_by: str,
        reason: str,
        ttl_seconds: int = 3600,
        approval_receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a local rotation record; no transport key is generated."""

        normalized_ref = self._validate_ref(
            device_ref,
            prefix="mesh-device",
        )
        if not isinstance(approval_receipt, dict):
            return self._approval_required(
                "network.write",
                "Rotating a device identity key requires explicit approval.",
                deviceRef=normalized_ref,
            )
        actor = self._bounded_text(
            requested_by,
            field="requestedBy",
            maximum=120,
        )
        reason_text = self._bounded_text(
            reason,
            field="reason",
            maximum=1000,
        )
        ttl = int(ttl_seconds)
        if ttl < 300 or ttl > 86_400:
            raise ValueError("ttlSeconds must be between 300 and 86400")
        mutation_payload = {
            "deviceRef": normalized_ref,
            "requestedBy": actor,
            "reason": reason_text,
            "ttlSeconds": ttl,
        }
        with self._identity_transaction() as state:
            self._consume_approval(
                approval_receipt,
                operation="request_key_rotation",
                device_ref=normalized_ref,
                payload=mutation_payload,
                state=state,
            )
            self._expire_lifecycle_requests(state)
            device = self._require_device(state, normalized_ref)
            self._assert_device_not_revoked(device)
            active = next(
                (
                    row
                    for row in state["rotations"].values()
                    if row.get("deviceRef") == normalized_ref
                    and row.get("state") in {"requested", "staged_local"}
                ),
                None,
            )
            if active is not None:
                raise RuntimeError(
                    "A key rotation is already pending for this device"
                )
            now_value = datetime.now(UTC)
            now = now_value.isoformat().replace("+00:00", "Z")
            rotation_ref = self._new_ref("mesh-rotation")
            rotation = {
                "schema": "neyvia.mesh-key-rotation/v1",
                "rotationRef": rotation_ref,
                "deviceRef": normalized_ref,
                "state": "requested",
                "requestedBy": actor,
                "reasonSha256": hashlib.sha256(
                    reason_text.encode("utf-8")
                ).hexdigest(),
                "reasonBytes": len(reason_text.encode("utf-8")),
                "fromGeneration": int(device.get("keyGeneration") or 1),
                "toGeneration": int(device.get("keyGeneration") or 1) + 1,
                "deviceStateVersion": int(
                    device.get("stateVersion") or 1
                ),
                "candidateFingerprintSha256": "",
                "createdAt": now,
                "updatedAt": now,
                "expiresAt": (
                    now_value + timedelta(seconds=ttl)
                ).isoformat().replace("+00:00", "Z"),
                "providerRotationProven": False,
                "providerActionPerformed": False,
                "privateKeyStored": False,
            }
            state["rotations"][rotation_ref] = rotation
        return {
            "schema": "neyvia.mesh-key-rotation-result/v1",
            "ok": True,
            "status": "rotation_requested",
            "rotation": rotation,
            "providerActionPerformed": False,
            "providerRotationProven": False,
        }

    def transition_key_rotation(
        self,
        rotation_ref: str,
        *,
        transition: str,
        public_key_fingerprint: str = "",
        approval_receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Advance the bounded local rotation state machine fail-closed."""

        normalized_ref = self._validate_ref(
            rotation_ref,
            prefix="mesh-rotation",
        )
        if not isinstance(approval_receipt, dict):
            return self._approval_required(
                "network.write",
                "Changing key-rotation state requires explicit approval.",
                rotationRef=normalized_ref,
            )
        action = str(transition or "").strip().casefold()
        if action not in {"stage", "activate", "cancel"}:
            raise ValueError(
                "transition must be stage, activate, or cancel"
            )
        normalized_fingerprint = (
            self._normalized_fingerprint(public_key_fingerprint)
            if action == "stage"
            else ""
        )
        with self._identity_transaction() as state:
            rotation = state["rotations"].get(normalized_ref)
            if not isinstance(rotation, dict):
                raise KeyError(f"Unknown mesh key rotation: {normalized_ref}")
            if self._parse_utc(
                rotation.get("expiresAt")
            ) <= datetime.now(UTC):
                raise TimeoutError("Mesh key rotation request expired")
            device_ref = str(rotation.get("deviceRef") or "")
            device = self._require_device(state, device_ref)
            self._assert_device_not_revoked(device)
            if int(rotation.get("deviceStateVersion") or 0) != int(
                device.get("stateVersion") or 0
            ):
                raise RuntimeError(
                    "Key rotation is stale for the current device revision"
                )
            self._consume_approval(
                approval_receipt,
                operation="transition_key_rotation",
                device_ref=device_ref,
                payload={
                    "rotationRef": normalized_ref,
                    "transition": action,
                    "publicKeyFingerprint": normalized_fingerprint,
                },
                state=state,
            )
            current = str(rotation.get("state") or "")
            if action == "activate":
                return {
                    "schema": "neyvia.mesh-key-rotation-result/v1",
                    "ok": False,
                    "status": "provider_activation_proof_required",
                    "rotation": dict(rotation),
                    "providerActionPerformed": False,
                    "providerRotationProven": False,
                    "blocker": (
                        "No approved provider adapter can rotate and verify "
                        "the device key, so local activation is refused."
                    ),
                }
            if action == "stage":
                if current != "requested":
                    raise RuntimeError(
                        "Only a requested key rotation can be staged"
                    )
                candidate_hash = self._fingerprint_hash(
                    normalized_fingerprint
                )
                if candidate_hash == device.get("keyFingerprintSha256"):
                    raise ValueError(
                        "Rotation candidate must differ from the current key"
                    )
                if any(
                    row.get("deviceRef") != device_ref
                    and row.get("state") != "revoked"
                    and row.get("keyFingerprintSha256") == candidate_hash
                    for row in state["devices"].values()
                ):
                    raise ValueError(
                        "Rotation candidate is already bound to another device"
                    )
                if any(
                    row.get("rotationRef") != normalized_ref
                    and row.get("state") == "staged_local"
                    and row.get("candidateFingerprintSha256")
                    == candidate_hash
                    for row in state["rotations"].values()
                ):
                    raise ValueError(
                        "Rotation candidate is already staged elsewhere"
                    )
                rotation.update(
                    {
                        "state": "staged_local",
                        "candidateFingerprintSha256": candidate_hash,
                        "updatedAt": utc_now(),
                        "providerActionPerformed": False,
                        "providerRotationProven": False,
                    }
                )
                status = "provider_activation_required"
            else:
                if current not in {"requested", "staged_local"}:
                    raise RuntimeError(
                        "Only a pending key rotation can be cancelled"
                    )
                rotation.update(
                    {
                        "state": "cancelled",
                        "updatedAt": utc_now(),
                        "providerActionPerformed": False,
                        "providerRotationProven": False,
                    }
                )
                status = "rotation_cancelled"
        return {
            "schema": "neyvia.mesh-key-rotation-result/v1",
            "ok": action == "cancel",
            "status": status,
            "rotation": rotation,
            "providerActionPerformed": False,
            "providerRotationProven": False,
        }

    def revoke_device(
        self,
        device_ref: str,
        *,
        revoked_by: str,
        reason: str,
        approval_receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Revoke local identity access and leave remote revocation pending."""

        normalized_ref = self._validate_ref(
            device_ref,
            prefix="mesh-device",
        )
        if not isinstance(approval_receipt, dict):
            return self._approval_required(
                "network.write",
                "Device revocation requires explicit approval.",
                deviceRef=normalized_ref,
            )
        actor = self._bounded_text(
            revoked_by,
            field="revokedBy",
            maximum=120,
        )
        reason_text = self._bounded_text(
            reason,
            field="reason",
            maximum=1000,
        )
        mutation_payload = {
            "deviceRef": normalized_ref,
            "revokedBy": actor,
            "reason": reason_text,
        }
        now = utc_now()
        with self._identity_transaction() as state:
            self._consume_approval(
                approval_receipt,
                operation="revoke_device",
                device_ref=normalized_ref,
                payload=mutation_payload,
                state=state,
            )
            device = self._require_device(state, normalized_ref)
            if device.get("state") == "revoked":
                return {
                    "schema": "neyvia.mesh-device-revocation-result/v1",
                    "ok": False,
                    "status": "already_revoked",
                    "deviceRef": normalized_ref,
                    "localAccessDisabled": True,
                    "providerActionPerformed": False,
                    "providerRevocationProven": False,
                }
            device.update(
                {
                    "state": "revoked",
                    "trustState": "revoked",
                    "recoveryState": "blocked_revoked",
                    "updatedAt": now,
                    "revokedAt": now,
                    "revokedBy": actor,
                    "revocationReasonSha256": hashlib.sha256(
                        reason_text.encode("utf-8")
                    ).hexdigest(),
                    "revocationReasonBytes": len(
                        reason_text.encode("utf-8")
                    ),
                    "localAccessDisabled": True,
                    "providerRevocationProven": False,
                    "stateVersion": int(
                        device.get("stateVersion") or 1
                    ) + 1,
                }
            )
            for rotation in state["rotations"].values():
                if (
                    rotation.get("deviceRef") == normalized_ref
                    and rotation.get("state")
                    in {"requested", "staged_local"}
                ):
                    rotation.update(
                        {
                            "state": "cancelled_by_revocation",
                            "updatedAt": now,
                        }
                    )
            self._disable_services_for_device(
                normalized_ref,
                revoked_by=actor,
                reason="Owning mesh identity was locally revoked",
            )
        return {
            "schema": "neyvia.mesh-device-revocation-result/v1",
            "ok": False,
            "status": "provider_revocation_required",
            "deviceRef": normalized_ref,
            "localAccessDisabled": True,
            "providerActionPerformed": False,
            "providerRevocationProven": False,
            "credentialsExposed": False,
        }

    def set_device_trust(
        self,
        device_ref: str,
        *,
        trust_state: str,
        changed_by: str,
        approval_receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Set local trust without presenting it as provider enforcement."""

        normalized_ref = self._validate_ref(
            device_ref,
            prefix="mesh-device",
        )
        if not isinstance(approval_receipt, dict):
            return self._approval_required(
                "network.write",
                "Changing device trust requires explicit approval.",
                deviceRef=normalized_ref,
            )
        target = str(trust_state or "").strip().casefold()
        if target not in {"unverified", "trusted_local", "quarantined"}:
            raise ValueError(
                "trustState must be unverified, trusted_local, or quarantined"
            )
        actor = self._bounded_text(
            changed_by,
            field="changedBy",
            maximum=120,
        )
        with self._identity_transaction() as state:
            self._consume_approval(
                approval_receipt,
                operation="set_device_trust",
                device_ref=normalized_ref,
                payload={
                    "deviceRef": normalized_ref,
                    "trustState": target,
                    "changedBy": actor,
                },
                state=state,
            )
            device = self._require_device(state, normalized_ref)
            self._assert_device_not_revoked(device)
            if device.get("trustState") == "recovery_pending":
                raise RuntimeError(
                    "Complete or cancel device recovery before changing trust"
                )
            now = utc_now()
            device.update(
                {
                    "trustState": target,
                    "updatedAt": now,
                    "trustChangedAt": now,
                    "trustChangedBy": actor,
                    "localAccessDisabled": target == "quarantined",
                    "stateVersion": int(
                        device.get("stateVersion") or 1
                    ) + 1,
                }
            )
        return {
            "schema": "neyvia.mesh-device-trust-result/v1",
            "ok": True,
            "status": "local_trust_updated",
            "device": device,
            "providerActionPerformed": False,
            "transportPolicyEnforced": False,
        }

    def upsert_acl_rule(
        self,
        rule: dict[str, Any],
        *,
        approval_receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist one bounded local ACL rule with deny-by-default semantics."""

        if not isinstance(approval_receipt, dict):
            return self._approval_required(
                "network.write",
                "Changing mesh ACL policy requires explicit approval.",
            )
        self._reject_secret_keys(rule)
        rule_ref_text = str(rule.get("ruleRef") or "").strip()
        rule_ref = (
            self._validate_ref(rule_ref_text, prefix="mesh-acl")
            if rule_ref_text
            else self._new_ref("mesh-acl")
        )
        effect = str(rule.get("effect") or "").strip().casefold()
        if effect not in {"allow", "deny"}:
            raise ValueError("ACL effect must be allow or deny")
        subjects = normalized_strings(rule.get("subjects"))
        if not subjects or len(subjects) > 50:
            raise ValueError("ACL subjects must contain 1 to 50 values")
        for subject in subjects:
            if subject != "*":
                self._validate_ref(subject, prefix="mesh-device")
        actions = [
            value.casefold()
            for value in normalized_strings(rule.get("actions"))
        ]
        if not actions or len(actions) > 50:
            raise ValueError("ACL actions must contain 1 to 50 values")
        if any(action != "*" and not _ACL_ACTION.fullmatch(action) for action in actions):
            raise ValueError("ACL action is invalid")
        resources = normalized_strings(rule.get("resources"))
        if not resources or len(resources) > 50:
            raise ValueError("ACL resources must contain 1 to 50 values")
        if any(
            not resource
            or len(resource) > 256
            or ("\\" in resource)
            for resource in resources
        ):
            raise ValueError("ACL resource is invalid")
        priority = int(rule.get("priority") or 0)
        if priority < 0 or priority > 1000:
            raise ValueError("ACL priority must be between 0 and 1000")
        enabled_value = rule.get("enabled", True)
        if not isinstance(enabled_value, bool):
            raise TypeError("ACL enabled must be a boolean")
        mutation_payload = {
            "ruleRef": rule_ref_text,
            "effect": effect,
            "subjects": sorted(set(subjects)),
            "actions": sorted(set(actions)),
            "resources": sorted(set(resources)),
            "priority": priority,
            "enabled": enabled_value,
        }
        now = utc_now()
        row = {
            "schema": "neyvia.mesh-acl-rule/v1",
            "ruleRef": rule_ref,
            "effect": effect,
            "subjects": sorted(set(subjects)),
            "actions": sorted(set(actions)),
            "resources": sorted(set(resources)),
            "priority": priority,
            "enabled": enabled_value,
            "createdAt": now,
            "updatedAt": now,
            "providerPolicyApplied": False,
        }
        with self._identity_transaction() as state:
            self._consume_approval(
                approval_receipt,
                operation="upsert_acl_rule",
                device_ref="*",
                payload=mutation_payload,
                state=state,
            )
            previous = next(
                (
                    item
                    for item in state["aclRules"]
                    if item.get("ruleRef") == rule_ref
                ),
                None,
            )
            if previous is not None:
                row["createdAt"] = str(previous.get("createdAt") or now)
            state["aclRules"] = [
                item
                for item in state["aclRules"]
                if item.get("ruleRef") != rule_ref
            ]
            state["aclRules"].append(row)
        return {
            "schema": "neyvia.mesh-acl-rule-result/v1",
            "ok": True,
            "status": "local_acl_updated",
            "rule": row,
            "providerActionPerformed": False,
            "transportPolicyEnforced": False,
        }

    def evaluate_acl(
        self,
        device_ref: str,
        *,
        action: str,
        resource: str,
    ) -> dict[str, Any]:
        """Evaluate local policy while reporting that transport is not wired."""

        normalized_ref = self._validate_ref(
            device_ref,
            prefix="mesh-device",
        )
        normalized_action = str(action or "").strip().casefold()
        if not _ACL_ACTION.fullmatch(normalized_action):
            raise ValueError("ACL action is invalid")
        normalized_resource = str(resource or "").strip()
        if (
            not normalized_resource
            or len(normalized_resource) > 256
            or "\\" in normalized_resource
        ):
            raise ValueError("ACL resource is invalid")
        with self._identity_transaction() as state:
            device = self._require_device(state, normalized_ref)
            matching = [
                dict(rule)
                for rule in state["aclRules"]
                if rule.get("enabled") is not False
                and self._acl_rule_matches(
                    rule,
                    device_ref=normalized_ref,
                    action=normalized_action,
                    resource=normalized_resource,
                )
            ]
        matching.sort(
            key=lambda row: (
                -int(row.get("priority") or 0),
                0 if row.get("effect") == "deny" else 1,
                str(row.get("ruleRef") or ""),
            )
        )
        selected = matching[0] if matching else None
        policy_allowed = bool(selected and selected.get("effect") == "allow")
        trust_state = str(device.get("trustState") or "unverified")
        trust_eligible = (
            device.get("state") != "revoked"
            and device.get("localAccessDisabled") is not True
            and trust_state == "trusted_local"
        )
        allowed = policy_allowed and trust_eligible
        reason = (
            "device_revoked"
            if device.get("state") == "revoked"
            else "device_not_locally_trusted"
            if not trust_eligible
            else "rule_allow"
            if policy_allowed
            else "rule_deny"
            if selected
            else "default_deny"
        )
        return {
            "schema": "neyvia.mesh-acl-decision/v1",
            "deviceRef": normalized_ref,
            "action": normalized_action,
            "resource": normalized_resource,
            "allowed": allowed,
            "reason": reason,
            "trustState": trust_state,
            "matchedRuleRef": (
                str(selected.get("ruleRef") or "") if selected else ""
            ),
            "matchingRuleRefs": [
                str(row.get("ruleRef") or "") for row in matching
            ],
            "precedence": "highest_priority_then_deny",
            "defaultDeny": selected is None,
            "transportPolicyEnforced": False,
            "providerPolicyApplied": False,
        }

    def request_device_recovery(
        self,
        device_ref: str,
        *,
        requested_by: str,
        reason: str,
        ttl_seconds: int = 3600,
        approval_receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Quarantine a device and persist a secret-free recovery request."""

        normalized_ref = self._validate_ref(
            device_ref,
            prefix="mesh-device",
        )
        if not isinstance(approval_receipt, dict):
            return self._approval_required(
                "network.write",
                "Device recovery requires explicit approval.",
                deviceRef=normalized_ref,
            )
        actor = self._bounded_text(
            requested_by,
            field="requestedBy",
            maximum=120,
        )
        reason_text = self._bounded_text(
            reason,
            field="reason",
            maximum=1000,
        )
        ttl = int(ttl_seconds)
        if ttl < 300 or ttl > 86_400:
            raise ValueError("ttlSeconds must be between 300 and 86400")
        mutation_payload = {
            "deviceRef": normalized_ref,
            "requestedBy": actor,
            "reason": reason_text,
            "ttlSeconds": ttl,
        }
        with self._identity_transaction() as state:
            self._expire_lifecycle_requests(state)
            if any(
                row.get("deviceRef") == normalized_ref
                and row.get("state")
                in {"blocked_provider_recovery", "local_identity_reset"}
                for row in state["recoveries"].values()
            ):
                raise RuntimeError(
                    "A nonterminal recovery already exists for this device"
                )
            self._consume_approval(
                approval_receipt,
                operation="request_device_recovery",
                device_ref=normalized_ref,
                payload=mutation_payload,
                state=state,
            )
            device = self._require_device(state, normalized_ref)
            self._assert_device_not_revoked(device)
            now_value = datetime.now(UTC)
            now = now_value.isoformat().replace("+00:00", "Z")
            next_device_version = int(
                device.get("stateVersion") or 1
            ) + 1
            recovery_ref = self._new_ref("mesh-recovery")
            recovery = {
                "schema": "neyvia.mesh-device-recovery/v1",
                "recoveryRef": recovery_ref,
                "deviceRef": normalized_ref,
                "state": "blocked_provider_recovery",
                "requestedBy": actor,
                "reasonSha256": hashlib.sha256(
                    reason_text.encode("utf-8")
                ).hexdigest(),
                "reasonBytes": len(reason_text.encode("utf-8")),
                "createdAt": now,
                "updatedAt": now,
                "expiresAt": (
                    now_value + timedelta(seconds=ttl)
                ).isoformat().replace("+00:00", "Z"),
                "deviceStateVersion": next_device_version,
                "providerRecoveryProven": False,
                "providerActionPerformed": False,
                "recoverySecretStored": False,
            }
            device.update(
                {
                    "trustState": "recovery_pending",
                    "recoveryState": "pending",
                    "localAccessDisabled": True,
                    "updatedAt": now,
                    "stateVersion": next_device_version,
                }
            )
            state["recoveries"][recovery_ref] = recovery
        return {
            "schema": "neyvia.mesh-device-recovery-result/v1",
            "ok": False,
            "status": "blocked_provider_recovery",
            "recovery": recovery,
            "localAccessDisabled": True,
            "providerActionPerformed": False,
            "providerRecoveryProven": False,
        }

    def transition_device_recovery(
        self,
        recovery_ref: str,
        *,
        transition: str,
        approval_receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Cancel or locally reset recovery without claiming remote success."""

        normalized_ref = self._validate_ref(
            recovery_ref,
            prefix="mesh-recovery",
        )
        if not isinstance(approval_receipt, dict):
            return self._approval_required(
                "network.write",
                "Changing device recovery state requires explicit approval.",
                recoveryRef=normalized_ref,
            )
        action = str(transition or "").strip().casefold()
        if action not in {"cancel", "reset_local_identity", "complete"}:
            raise ValueError(
                "transition must be cancel, reset_local_identity, or complete"
            )
        with self._identity_transaction() as state:
            recovery = state["recoveries"].get(normalized_ref)
            if not isinstance(recovery, dict):
                raise KeyError(
                    f"Unknown mesh device recovery: {normalized_ref}"
                )
            if self._parse_utc(
                recovery.get("expiresAt")
            ) <= datetime.now(UTC):
                raise TimeoutError("Mesh device recovery request expired")
            if recovery.get("state") not in {
                "blocked_provider_recovery",
                "local_identity_reset",
            }:
                raise RuntimeError("Device recovery is already terminal")
            device = self._require_device(
                state,
                str(recovery.get("deviceRef") or ""),
            )
            device_ref = str(device.get("deviceRef") or "")
            self._assert_device_not_revoked(device)
            if int(recovery.get("deviceStateVersion") or 0) != int(
                device.get("stateVersion") or 0
            ):
                raise RuntimeError(
                    "Device recovery is stale for the current device revision"
                )
            self._consume_approval(
                approval_receipt,
                operation="transition_device_recovery",
                device_ref=device_ref,
                payload={
                    "recoveryRef": normalized_ref,
                    "transition": action,
                },
                state=state,
            )
            if action == "complete":
                return {
                    "schema": "neyvia.mesh-device-recovery-result/v1",
                    "ok": False,
                    "status": "provider_recovery_proof_required",
                    "recovery": dict(recovery),
                    "providerActionPerformed": False,
                    "providerRecoveryProven": False,
                }
            now = utc_now()
            next_device_version = int(
                device.get("stateVersion") or 1
            ) + 1
            if action == "cancel":
                recovery.update(
                    {"state": "cancelled", "updatedAt": now}
                )
                device.update(
                    {
                        "trustState": "quarantined",
                        "recoveryState": "cancelled",
                        "localAccessDisabled": True,
                        "updatedAt": now,
                        "stateVersion": next_device_version,
                    }
                )
                status = "recovery_cancelled"
            else:
                if recovery.get("state") != "blocked_provider_recovery":
                    raise RuntimeError(
                        "Local identity reset has already been performed"
                    )
                recovery.update(
                    {
                        "state": "local_identity_reset",
                        "updatedAt": now,
                    }
                )
                device.update(
                    {
                        "trustState": "unverified",
                        "recoveryState": "provider_reenrollment_required",
                        "localAccessDisabled": True,
                        "updatedAt": now,
                        "stateVersion": next_device_version,
                    }
                )
                recovery["deviceStateVersion"] = next_device_version
                status = "provider_reenrollment_required"
        return {
            "schema": "neyvia.mesh-device-recovery-result/v1",
            "ok": action == "cancel",
            "status": status,
            "recovery": recovery,
            "device": device,
            "providerActionPerformed": False,
            "providerRecoveryProven": False,
        }

    def identity_deployment_readiness(self) -> dict[str, Any]:
        """Report implemented local policy separately from external deployment."""

        selected = str(self.config.get("selectedProvider") or "")
        target = str(self.config.get("targetProvider") or "")
        target_config = dict(
            (self.config.get("providers") or {}).get(target) or {}
        )
        client_found = (
            self._tailscale_executable() is not None
            if selected == "tailscale-bridge"
            else shutil.which(selected) is not None
        )
        blockers = [
            {
                "gate": "provider-identity-adapter",
                "passed": False,
                "reason": (
                    "No approved adapter executes enrollment, rotation, "
                    "revocation, ACL publication, or recovery."
                ),
            },
            {
                "gate": "self-hosted-control-plane",
                "passed": False,
                "reason": (
                    "The selected self-hosted control plane has not been "
                    "deployed and verified."
                ),
            },
            {
                "gate": "provider-action-receipts",
                "passed": False,
                "reason": (
                    "No provider-issued receipts prove identity lifecycle "
                    "changes were applied."
                ),
            },
        ]
        return {
            "schema": "neyvia.mesh-identity-readiness/v1",
            "generatedAt": utc_now(),
            "selectedProvider": selected,
            "targetProvider": target,
            "targetInstallState": str(
                target_config.get("installState") or "unknown"
            ),
            "localLifecycleImplemented": True,
            "localAclEvaluationImplemented": True,
            "externalApprovalVerificationImplemented": True,
            "externalApprovalVerifierProvisioned": (
                self._approval_verifier_ready()
            ),
            "verifierConfigOutsideWorkspace": (
                self.verifier_config_authoritative
            ),
            "providerEnrollmentVerifierProvisioned": (
                self._enrollment_verifier_ready()
            ),
            "mutationEnabled": self._approval_verifier_ready(),
            "approvalLedgerOutsideWorkspace": (
                self.protected_state_root is not None
                and self._approval_verifier_ready()
            ),
            "crossProcessSerializationImplemented": True,
            "revisionCasImplemented": True,
            "providerClientObserved": client_found,
            "providerIdentityActionsImplemented": False,
            "providerActionsPerformed": False,
            "ready": False,
            "blockers": blockers,
            "nextAction": (
                "Implement and verify a receipt-producing provider adapter "
                "before enabling transport identity enforcement."
            ),
        }

    def probe_peer(
        self,
        target: str,
        *,
        count: int = 3,
        timeout_seconds: int = 5,
    ) -> dict[str, Any]:
        normalized = str(target or "").strip()
        if not _PROBE_TARGET.fullmatch(normalized):
            raise ValueError("target is not a valid private-mesh name or address")
        bounded_count = max(1, min(int(count), 5))
        bounded_timeout = max(1, min(int(timeout_seconds), 15))
        provider = str(self.config.get("selectedProvider") or "")
        if provider != "tailscale-bridge":
            raise RuntimeError(
                "Live peer probing is not enabled for the selected provider"
            )
        executable = self._tailscale_executable()
        if executable is None:
            raise RuntimeError("Tailscale CLI is not installed")
        started = time.perf_counter()
        completed = subprocess.run(
            [
                str(executable),
                "ping",
                "-c",
                str(bounded_count),
                "--timeout",
                f"{bounded_timeout}s",
                normalized,
            ],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=(bounded_count * bounded_timeout) + 5,
            shell=False,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
        output = (completed.stdout + completed.stderr).strip()
        observations = self._parse_ping_output(output)
        route = (
            observations[-1]["route"]
            if observations
            else "unreachable"
        )
        latencies = [
            int(row["latencyMs"])
            for row in observations
            if row.get("latencyMs") is not None
        ]
        passed = completed.returncode == 0 and bool(observations)
        receipt = {
            "schema": MESH_PROBE_SCHEMA,
            "target": normalized,
            "provider": provider,
            "passed": passed,
            "status": "reachable" if passed else "unreachable",
            "route": route,
            "latencyMs": min(latencies) if latencies else None,
            "observations": observations,
            "attempts": bounded_count,
            "durationMs": round(
                (time.perf_counter() - started) * 1000.0,
                3,
            ),
            "probedAt": utc_now(),
            "error": "" if passed else output[-1000:],
        }
        self._store_probe(receipt)
        return receipt

    def service_catalog(self) -> dict[str, Any]:
        state = self._read_services()
        snapshot = self.snapshot()
        online_ids = {
            row["deviceId"]
            for row in snapshot["provider"].get("peers") or []
            if row["online"]
        }
        own = snapshot["provider"].get("self")
        if isinstance(own, dict) and own.get("online"):
            online_ids.add(str(own.get("deviceId") or ""))
        services = []
        for raw in state["services"]:
            row = dict(raw)
            row["ownerOnline"] = row.get("deviceId") in online_ids
            services.append(row)
        return {
            "schema": MESH_SERVICE_CATALOG_SCHEMA,
            "revision": int(state.get("revision") or 0),
            "generatedAt": utc_now(),
            "services": services,
            "summary": {
                "total": len(services),
                "available": sum(
                    1
                    for row in services
                    if row.get("enabled") is not False
                    and row["ownerOnline"]
                ),
            },
        }

    def advertise_service(
        self,
        payload: dict[str, Any],
        *,
        approval_receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(approval_receipt, dict):
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "network.write",
            }
        self._reject_secret_keys(payload)
        service_id = str(payload.get("serviceId") or "").strip().casefold()
        device_id = self._validate_ref(
            payload.get("deviceId"),
            prefix="mesh-device",
        )
        service_type = str(payload.get("serviceType") or "").strip().casefold()
        endpoint = str(payload.get("endpoint") or "").strip()
        if not _IDENTIFIER.fullmatch(service_id):
            raise ValueError("serviceId is invalid")
        if not device_id:
            raise ValueError("deviceId is required")
        allowed_types = {
            str(item).casefold()
            for item in self.config.get("serviceTypes") or []
        }
        if service_type not in allowed_types:
            raise ValueError("serviceType is not registered")
        self._validate_private_endpoint(endpoint)
        health_path = str(payload.get("healthPath") or "").strip()
        if health_path and (
            not health_path.startswith("/")
            or len(health_path) > 512
        ):
            raise ValueError("healthPath must be a bounded absolute path")
        row = {
            "serviceId": service_id,
            "deviceId": device_id,
            "serviceType": service_type,
            "endpoint": endpoint,
            "healthPath": health_path,
            "authMode": str(
                payload.get("authMode") or "opaque-handle"
            ),
            "capabilities": normalized_strings(
                payload.get("capabilities")
            )[:50],
            "enabled": True,
            "advertisedAt": utc_now(),
            "advertisedBy": str(payload.get("advertisedBy") or "").strip(),
        }
        mutation_payload = {
            key: row[key]
            for key in (
                "serviceId",
                "deviceId",
                "serviceType",
                "endpoint",
                "healthPath",
                "authMode",
                "capabilities",
                "advertisedBy",
            )
        }
        with self._identity_transaction() as identity:
            self._expire_enrollment_intents(identity)
            device = self._require_device(identity, device_id)
            if (
                device.get("state")
                in {"revoked", "provider_reenrollment_required"}
                or device.get("trustState")
                in {"quarantined", "recovery_pending", "revoked"}
                or device.get("recoveryState")
                == "provider_reenrollment_required"
                or device.get("localAccessDisabled") is True
            ):
                raise PermissionError(
                    "Mesh service owner is quarantined, disabled, or revoked"
                )
            self._consume_approval(
                approval_receipt,
                operation="advertise_service",
                device_ref=device_id,
                payload=mutation_payload,
                state=identity,
            )
            with self._service_transaction() as services:
                services["services"] = [
                    item
                    for item in services["services"]
                    if item.get("serviceId") != service_id
                ]
                services["services"].append(row)
        return {"ok": True, "status": "advertised", "service": row}

    def revoke_service(
        self,
        service_id: str,
        *,
        approval_receipt: dict[str, Any] | None = None,
        revoked_by: str,
        reason: str,
    ) -> dict[str, Any]:
        if not isinstance(approval_receipt, dict):
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "network.write",
            }
        normalized = str(service_id or "").strip().casefold()
        if not _IDENTIFIER.fullmatch(normalized):
            raise ValueError("serviceId is invalid")
        actor = self._bounded_text(
            revoked_by,
            field="revokedBy",
            maximum=120,
        )
        reason_text = self._bounded_text(
            reason,
            field="reason",
            maximum=1000,
        )
        changed = 0
        with self._identity_transaction() as identity:
            with self._service_transaction() as services:
                owner_ref = next(
                    (
                        str(row.get("deviceId") or "")
                        for row in services["services"]
                        if row.get("serviceId") == normalized
                    ),
                    "",
                )
                if not owner_ref:
                    return {
                        "ok": False,
                        "status": "not_found",
                        "serviceId": normalized,
                        "changed": 0,
                    }
                self._require_device(identity, owner_ref)
                self._consume_approval(
                approval_receipt,
                    operation="revoke_service",
                    device_ref=owner_ref,
                    payload={
                        "serviceId": normalized,
                        "revokedBy": actor,
                        "reason": reason_text,
                    },
                    state=identity,
                )
                for row in services["services"]:
                    if (
                        row.get("serviceId") == normalized
                        and row.get("enabled") is not False
                    ):
                        row["enabled"] = False
                        row["revokedAt"] = utc_now()
                        row["revokedBy"] = actor
                        row["revocationReason"] = reason_text
                        changed += 1
        return {
            "ok": bool(changed),
            "status": "revoked" if changed else "not_found",
            "serviceId": normalized,
            "changed": changed,
        }

    def migration_plan(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        target = str(self.config.get("targetProvider") or "")
        target_config = dict(
            (self.config.get("providers") or {}).get(target) or {}
        )
        return {
            "schema": MESH_MIGRATION_PLAN_SCHEMA,
            "generatedAt": utc_now(),
            "currentProvider": snapshot["selectedProvider"],
            "targetProvider": target,
            "cutoverAllowed": bool(self.config.get("cutoverEnabled")),
            "currentTransportHealthy": snapshot["summary"]["available"],
            "targetInstallState": str(
                target_config.get("installState") or "unknown"
            ),
            "preconditions": [
                {
                    "gate": "nas-control-plane",
                    "passed": False,
                    "reason": "The self-hosted control plane is not deployed.",
                },
                {
                    "gate": "windows-client",
                    "passed": shutil.which("netbird") is not None,
                    "reason": "NetBird client must pass daemon/API probes.",
                },
                {
                    "gate": "android-client",
                    "passed": False,
                    "reason": "Android enrollment and reconnect proof is pending.",
                },
                {
                    "gate": "direct-and-relay",
                    "passed": False,
                    "reason": "Both direct peer and relay fallback require proof.",
                },
                {
                    "gate": "recovery",
                    "passed": False,
                    "reason": "Tailscale bridge remains until rollback is proven.",
                },
                {
                    "gate": "provider-identity-lifecycle",
                    "passed": False,
                    "reason": (
                        "Local identity policy exists, but no approved adapter "
                        "has proven provider enrollment, rotation, revocation, "
                        "ACL publication, or recovery."
                    ),
                },
            ],
            "action": (
                "keep-current-bridge"
                if not self.config.get("cutoverEnabled")
                else "eligible-after-gates"
            ),
        }

    def _tailscale_snapshot(self) -> dict[str, Any]:
        executable = self._tailscale_executable()
        if executable is None:
            return {
                "providerId": "tailscale-bridge",
                "available": False,
                "state": "not-installed",
                "version": "",
                "self": None,
                "peers": [],
                "credentialsExposed": False,
            }
        status = self._run_json(
            [str(executable), "status", "--json"],
            timeout=5,
        )
        version_result = subprocess.run(
            [str(executable), "version"],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            shell=False,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
        own = status.get("Self")
        peers_raw = status.get("Peer")
        peer_objects = [
            item
            for item in (
                peers_raw.values()
                if isinstance(peers_raw, dict)
                else []
            )
            if isinstance(item, dict)
        ]
        system_peers = [
            item
            for item in peer_objects
            if self._is_system_tailscale_node(item)
        ]
        peers = [
            self._sanitize_tailscale_node(item)
            for item in peer_objects
            if not self._is_system_tailscale_node(item)
        ]
        backend = str(status.get("BackendState") or "unknown")
        return {
            "providerId": "tailscale-bridge",
            "available": backend.casefold() == "running",
            "state": backend.casefold(),
            "version": (
                version_result.stdout.splitlines()[0].strip()
                if version_result.returncode == 0
                and version_result.stdout.strip()
                else ""
            ),
            "executable": str(executable),
            "self": (
                self._sanitize_tailscale_node(own)
                if isinstance(own, dict)
                else None
            ),
            "peers": sorted(
                peers,
                key=lambda item: (
                    not item["online"],
                    item["hostName"].casefold(),
                ),
            ),
            "systemPeersExcluded": len(system_peers),
            "credentialsExposed": False,
        }

    def _netbird_snapshot(self) -> dict[str, Any]:
        provider = dict(
            (self.config.get("providers") or {}).get("netbird") or {}
        )
        executable = shutil.which("netbird")
        return {
            "providerId": "netbird",
            "available": bool(executable),
            "state": "installed-unconfigured" if executable else "not-installed",
            "version": str(provider.get("version") or ""),
            "executable": str(Path(executable).resolve()) if executable else "",
            "controlInterface": str(
                provider.get("controlInterface") or ""
            ),
            "self": None,
            "peers": [],
            "credentialsExposed": False,
        }

    @staticmethod
    def _sanitize_tailscale_node(node: dict[str, Any]) -> dict[str, Any]:
        stable = str(node.get("ID") or "")
        if not stable:
            raise ValueError(
                "Mesh provider node is missing its immutable node ID"
            )
        device_id = MeshService._canonical_device_ref(
            "tailscale-bridge",
            stable,
        )
        current_endpoint = str(node.get("CurAddr") or "")
        peer_relay = str(node.get("PeerRelay") or "")
        online = bool(node.get("Online"))
        active = bool(node.get("Active"))
        route_state = (
            "offline"
            if not online
            else "direct"
            if current_endpoint
            else "peer-relay"
            if peer_relay
            else "relay"
            if active and node.get("Relay")
            else "idle"
        )
        return {
            "deviceId": device_id,
            "hostName": str(node.get("HostName") or ""),
            "dnsName": str(node.get("DNSName") or "").rstrip("."),
            "os": str(node.get("OS") or ""),
            "addresses": [
                str(item) for item in node.get("TailscaleIPs") or []
            ],
            "online": online,
            "active": active,
            "routeState": route_state,
            "directEndpoint": current_endpoint,
            "relayRegion": str(node.get("Relay") or ""),
            "peerRelay": peer_relay,
            "rxBytes": int(node.get("RxBytes") or 0),
            "txBytes": int(node.get("TxBytes") or 0),
            "lastHandshake": str(node.get("LastHandshake") or ""),
            "lastSeen": str(node.get("LastSeen") or ""),
            "keyExpiry": str(node.get("KeyExpiry") or ""),
            "exitNode": bool(node.get("ExitNode")),
            "exitNodeOption": bool(node.get("ExitNodeOption")),
        }

    @staticmethod
    def _is_system_tailscale_node(node: dict[str, Any]) -> bool:
        return (
            str(node.get("HostName") or "").casefold()
            == "funnel-ingress-node"
            and not str(node.get("OS") or "").strip()
            and not str(node.get("DNSName") or "").strip()
        )

    @staticmethod
    def _parse_ping_output(output: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        pattern = re.compile(
            r"pong from (?P<name>.+?) \((?P<address>[^)]+)\) "
            r"via (?P<via>.+?) in (?P<latency>\d+)ms",
            re.IGNORECASE,
        )
        for line in output.splitlines():
            match = pattern.search(line.strip())
            if not match:
                continue
            via = match.group("via")
            route = (
                "relay"
                if via.casefold().startswith("derp(")
                else "peer-relay"
                if "peer-relay" in via.casefold()
                else "direct"
            )
            rows.append(
                {
                    "peerName": match.group("name"),
                    "address": match.group("address"),
                    "route": route,
                    "via": via,
                    "latencyMs": int(match.group("latency")),
                }
            )
        return rows

    def _tailscale_executable(self) -> Path | None:
        configured = dict(
            (self.config.get("providers") or {}).get(
                "tailscale-bridge"
            )
            or {}
        )
        path_text = str(configured.get("executable") or "").strip()
        if path_text and Path(path_text).is_file():
            return Path(path_text).resolve()
        found = shutil.which("tailscale")
        return Path(found).resolve() if found else None

    def _run_json(self, args: list[str], *, timeout: int) -> dict[str, Any]:
        completed = subprocess.run(
            args,
            cwd=str(self.root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Mesh provider command failed: {completed.stderr[-1000:]}"
            )
        payload = json.loads(completed.stdout)
        if not isinstance(payload, dict):
            raise RuntimeError("Mesh provider returned an invalid status object")
        return payload

    def _store_probe(self, receipt: dict[str, Any]) -> None:
        with self._probe_transaction() as state:
            state["probes"] = [
                row
                for row in state["probes"]
                if row.get("target") != receipt.get("target")
            ][-199:]
            state["probes"].append(receipt)

    def _recent_probes(self) -> list[dict[str, Any]]:
        payload = self._read_probe_state()
        return list(payload["probes"][-50:])

    def _read_probe_state(self) -> dict[str, Any]:
        empty = {
            "schema": "neyvia.mesh-probes/v1",
            "revision": 0,
            "updatedAt": "",
            "probes": [],
        }
        if not self.probe_path.is_file():
            return empty
        try:
            payload = json.loads(
                self.probe_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return empty
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("probes"), list)
        ):
            raise RuntimeError("Mesh probe registry is invalid")
        revision = payload.get("revision", 0)
        if not isinstance(revision, int) or revision < 0:
            raise RuntimeError("Mesh probe registry revision is invalid")
        payload["revision"] = revision
        return payload

    @contextmanager
    def _probe_transaction(self) -> Iterator[dict[str, Any]]:
        with _exclusive_file_lock(self.probes_lock_path):
            state = self._read_probe_state()
            expected_revision = int(state.get("revision") or 0)
            before = canonical_hash(state)
            yield state
            if canonical_hash(state) == before:
                return
            current_revision = int(
                self._read_probe_state().get("revision") or 0
            )
            if current_revision != expected_revision:
                raise RuntimeError(
                    "Mesh probe registry revision changed during update"
                )
            state["schema"] = "neyvia.mesh-probes/v1"
            state["revision"] = expected_revision + 1
            state["updatedAt"] = utc_now()
            atomic_write_json(self.probe_path, state)

    def _read_services(self) -> dict[str, Any]:
        if not self.services_path.is_file():
            return {
                "schema": "neyvia.mesh-services/v1",
                "revision": 0,
                "updatedAt": "",
                "services": [],
            }
        try:
            payload = json.loads(
                self.services_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return {
                "schema": "neyvia.mesh-services/v1",
                "revision": 0,
                "updatedAt": "",
                "services": [],
            }
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("services"), list)
        ):
            raise RuntimeError("Mesh service registry is invalid")
        revision = payload.get("revision", 0)
        if not isinstance(revision, int) or revision < 0:
            raise RuntimeError("Mesh service registry revision is invalid")
        payload["revision"] = revision
        return payload

    @staticmethod
    def _new_ref(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:20]}"

    @staticmethod
    def _approval_required(
        permission: str,
        reason: str,
        **context: str,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "approval_required",
            "requiredPermission": permission,
            "reason": reason,
            **context,
        }

    @staticmethod
    def _bounded_text(
        value: object,
        *,
        field: str,
        maximum: int,
    ) -> str:
        text = str(value or "").strip()
        if (
            not text
            or len(text.encode("utf-8")) > maximum
            or any(ord(character) < 32 for character in text)
        ):
            raise ValueError(
                f"{field} must contain 1 to {maximum} safe UTF-8 bytes"
            )
        return text

    @staticmethod
    def _validate_ref(value: object, *, prefix: str) -> str:
        normalized = str(value or "").strip().casefold()
        if (
            not _OPAQUE_REF.fullmatch(normalized)
            or not normalized.startswith(f"{prefix}-")
        ):
            raise ValueError(f"Invalid opaque {prefix} reference")
        return normalized

    @staticmethod
    def _fingerprint_hash(value: object) -> str:
        fingerprint = MeshService._normalized_fingerprint(value)
        return hashlib.sha256(
            fingerprint.encode("ascii")
        ).hexdigest()

    @staticmethod
    def _normalized_fingerprint(value: object) -> str:
        normalized = str(value or "").strip()
        if not _KEY_FINGERPRINT.fullmatch(normalized):
            raise ValueError(
                "publicKeyFingerprint must be a SHA-256 fingerprint"
            )
        return normalized.split(":", 1)[-1].casefold()

    @staticmethod
    def _canonical_device_ref(
        provider_id: object,
        provider_node_id: object,
    ) -> str:
        provider = str(provider_id or "").strip().casefold()
        node_id = str(provider_node_id or "").strip()
        if not _IDENTIFIER.fullmatch(provider):
            raise ValueError("providerId is invalid")
        if (
            not node_id
            or len(node_id.encode("utf-8")) > 256
            or any(ord(character) < 32 for character in node_id)
        ):
            raise ValueError(
                "providerNodeId must contain 1 to 256 safe UTF-8 bytes"
            )
        digest = canonical_hash(
            {
                "providerId": provider,
                "providerNodeId": node_id,
            }
        )
        return f"mesh-device-{digest[:20]}"

    @staticmethod
    def _empty_identity_state() -> dict[str, Any]:
        return {
            "schema": MESH_IDENTITY_STATE_SCHEMA,
            "revision": 0,
            "approvalSequence": 0,
            "updatedAt": "",
            "enrollments": {},
            "devices": {},
            "rotations": {},
            "recoveries": {},
            "aclRules": [],
        }

    def _read_identity_state(self) -> dict[str, Any]:
        if not self.identity_path.is_file():
            return self._empty_identity_state()
        try:
            payload = json.loads(
                self.identity_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Mesh identity registry is unreadable"
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != MESH_IDENTITY_STATE_SCHEMA
            or not isinstance(payload.get("enrollments"), dict)
            or not isinstance(payload.get("devices"), dict)
            or not isinstance(payload.get("rotations"), dict)
            or not isinstance(payload.get("recoveries"), dict)
            or not isinstance(payload.get("aclRules"), list)
        ):
            raise RuntimeError("Mesh identity registry is invalid")
        revision = payload.get("revision", 0)
        sequence = payload.get("approvalSequence", 0)
        if (
            not isinstance(revision, int)
            or revision < 0
            or not isinstance(sequence, int)
            or sequence < 0
        ):
            raise RuntimeError("Mesh identity registry revision is invalid")
        payload["revision"] = revision
        payload["approvalSequence"] = sequence
        return payload

    def _write_identity_state(
        self,
        state: dict[str, Any],
        *,
        expected_revision: int,
    ) -> None:
        current_revision = int(
            self._read_identity_state().get("revision") or 0
        )
        if current_revision != expected_revision:
            raise RuntimeError(
                "Mesh identity revision changed during update"
            )
        state["schema"] = MESH_IDENTITY_STATE_SCHEMA
        state["revision"] = expected_revision + 1
        state["updatedAt"] = utc_now()
        atomic_write_json(self.identity_path, state)

    def _write_services_state(
        self,
        state: dict[str, Any],
        *,
        expected_revision: int,
    ) -> None:
        current_revision = int(
            self._read_services().get("revision") or 0
        )
        if current_revision != expected_revision:
            raise RuntimeError(
                "Mesh service registry revision changed during update"
            )
        state["schema"] = "neyvia.mesh-services/v1"
        state["revision"] = expected_revision + 1
        state["updatedAt"] = utc_now()
        atomic_write_json(self.services_path, state)

    @contextmanager
    def _identity_transaction(self) -> Iterator[dict[str, Any]]:
        with _exclusive_file_lock(self.state_lock_path):
            state = self._read_identity_state()
            expected_revision = int(state.get("revision") or 0)
            before = canonical_hash(state)
            yield state
            if canonical_hash(state) != before:
                self._write_identity_state(
                    state,
                    expected_revision=expected_revision,
                )

    @contextmanager
    def _service_transaction(self) -> Iterator[dict[str, Any]]:
        with _exclusive_file_lock(self.services_lock_path):
            state = self._read_services()
            expected_revision = int(state.get("revision") or 0)
            before = canonical_hash(state)
            yield state
            if canonical_hash(state) != before:
                self._write_services_state(
                    state,
                    expected_revision=expected_revision,
                )

    @staticmethod
    def _mesh_plan_hash(plan: dict[str, Any]) -> str:
        payload = dict(plan)
        payload.pop("planHash", None)
        return canonical_hash(payload)

    def _identity_policy_hash(self, state: dict[str, Any]) -> str:
        return canonical_hash(
            {
                "configPolicy": self.policy,
                "aclRules": state.get("aclRules") or [],
            }
        )

    @staticmethod
    def _signed_receipt_bytes(receipt: dict[str, Any]) -> bytes:
        payload = dict(receipt)
        payload.pop("signature", None)
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @staticmethod
    def _is_within(path: Path, parent: Path) -> bool:
        try:
            path.resolve().relative_to(parent.resolve())
        except ValueError:
            return False
        return True

    def _verifier_path_ready(
        self,
        public_key_path: Path | None,
        key_id: str,
        *,
        configured_absolute: bool,
    ) -> bool:
        protected_root = self.protected_state_root
        if (
            protected_root is None
            or public_key_path is None
            or not self.protected_state_root_configured_absolute
            or not configured_absolute
            or not _VERIFIER_KEY_ID.fullmatch(key_id)
            or not protected_root.is_dir()
            or not public_key_path.is_file()
            or self._is_within(protected_root, self.root)
            or self._is_within(public_key_path, self.root)
            or not self._is_within(public_key_path, protected_root)
        ):
            return False
        try:
            pem = public_key_path.read_bytes()
        except OSError:
            return False
        if (
            len(pem) > 16_384
            or b"PRIVATE KEY" in pem
        ):
            return False
        return True

    def _approval_verifier_ready(self) -> bool:
        return self._verifier_path_ready(
            self.approval_public_key_path,
            self.approval_verifier_key_id,
            configured_absolute=(
                self.approval_public_key_configured_absolute
            ),
        )

    def _enrollment_verifier_ready(self) -> bool:
        return self._verifier_path_ready(
            self.enrollment_public_key_path,
            self.enrollment_verifier_key_id,
            configured_absolute=(
                self.enrollment_public_key_configured_absolute
            ),
        )

    def _load_verifier_public_key(
        self,
        *,
        public_key_path: Path | None,
        key_id: str,
        configured_absolute: bool,
        label: str,
    ) -> Ed25519PublicKey:
        if not self._verifier_path_ready(
            public_key_path,
            key_id,
            configured_absolute=configured_absolute,
        ):
            raise PermissionError(
                f"External mesh {label} verifier is not provisioned"
            )
        assert public_key_path is not None
        try:
            loaded = serialization.load_pem_public_key(
                public_key_path.read_bytes()
            )
        except (OSError, ValueError, TypeError) as exc:
            raise PermissionError(
                f"External mesh {label} verifier key is invalid"
            ) from exc
        if not isinstance(loaded, Ed25519PublicKey):
            raise PermissionError(
                f"External mesh {label} verifier must use Ed25519"
            )
        raw = loaded.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        actual_key_id = f"sha256:{hashlib.sha256(raw).hexdigest()}"
        if actual_key_id != key_id:
            raise PermissionError(
                f"External mesh {label} verifier keyId does not match"
            )
        return loaded

    def _approval_public_key(self) -> Ed25519PublicKey:
        return self._load_verifier_public_key(
            public_key_path=self.approval_public_key_path,
            key_id=self.approval_verifier_key_id,
            configured_absolute=(
                self.approval_public_key_configured_absolute
            ),
            label="approval",
        )

    def _enrollment_public_key(self) -> Ed25519PublicKey:
        return self._load_verifier_public_key(
            public_key_path=self.enrollment_public_key_path,
            key_id=self.enrollment_verifier_key_id,
            configured_absolute=(
                self.enrollment_public_key_configured_absolute
            ),
            label="provider-enrollment",
        )

    def _verify_provider_enrollment_receipt(
        self,
        receipt: dict[str, Any],
        *,
        enrollment_ref: str,
        fingerprint_hash: str,
    ) -> dict[str, str]:
        if (
            not isinstance(receipt, dict)
            or receipt.get("schema")
            != "neyvia.mesh-provider-enrollment-receipt/v1"
        ):
            raise PermissionError(
                "Invalid provider enrollment receipt"
            )
        if set(receipt) != {
            "schema",
            "receiptId",
            "providerId",
            "providerNodeId",
            "enrollmentRef",
            "keyFingerprintSha256",
            "enrolledAt",
            "expiresAt",
            "keyId",
            "signature",
        }:
            raise PermissionError(
                "Provider enrollment receipt fields are invalid"
            )
        receipt_id = self._validate_ref(
            receipt.get("receiptId"),
            prefix="mesh-provider",
        )
        provider_id = str(
            receipt.get("providerId") or ""
        ).strip().casefold()
        allowed_providers = {
            str(self.config.get("selectedProvider") or "").casefold(),
            str(self.config.get("targetProvider") or "").casefold(),
        }
        if (
            not _IDENTIFIER.fullmatch(provider_id)
            or provider_id not in allowed_providers
        ):
            raise PermissionError(
                "Provider enrollment receipt provider is not configured"
            )
        provider_node_id = self._bounded_text(
            receipt.get("providerNodeId"),
            field="providerNodeId",
            maximum=256,
        )
        if (
            str(receipt.get("enrollmentRef") or "").casefold()
            != enrollment_ref
            or str(
                receipt.get("keyFingerprintSha256") or ""
            ).casefold()
            != fingerprint_hash
            or str(receipt.get("keyId") or "").casefold()
            != self.enrollment_verifier_key_id
        ):
            raise PermissionError(
                "Provider enrollment receipt binding changed"
            )
        signature_text = str(receipt.get("signature") or "").strip()
        if len(signature_text) > 256:
            raise PermissionError(
                "Provider enrollment receipt signature is invalid"
            )
        try:
            signature = base64.b64decode(
                signature_text.encode("ascii"),
                validate=True,
            )
            self._enrollment_public_key().verify(
                signature,
                self._signed_receipt_bytes(receipt),
            )
        except (
            InvalidSignature,
            ValueError,
            UnicodeEncodeError,
        ) as exc:
            raise PermissionError(
                "Provider enrollment receipt signature verification failed"
            ) from exc
        now = datetime.now(UTC)
        enrolled_at = self._parse_utc(receipt.get("enrolledAt"))
        expires_at = self._parse_utc(receipt.get("expiresAt"))
        if enrolled_at > now + timedelta(minutes=5):
            raise PermissionError(
                "Provider enrollment receipt timestamp is in the future"
            )
        if expires_at <= now:
            raise TimeoutError("Provider enrollment receipt expired")
        if expires_at - enrolled_at > timedelta(hours=24):
            raise PermissionError(
                "Provider enrollment receipt lifetime exceeds 24 hours"
            )
        device_ref = self._canonical_device_ref(
            provider_id,
            provider_node_id,
        )
        return {
            "receiptId": receipt_id,
            "providerId": provider_id,
            "providerNodeIdSha256": hashlib.sha256(
                provider_node_id.encode("utf-8")
            ).hexdigest(),
            "deviceRef": device_ref,
            "enrolledAt": enrolled_at.isoformat().replace(
                "+00:00", "Z"
            ),
            "expiresAt": expires_at.isoformat().replace(
                "+00:00", "Z"
            ),
        }

    def _reserve_approval_receipt(
        self,
        *,
        receipt_id: str,
        receipt_hash: str,
        operation: str,
        device_ref: str,
    ) -> None:
        if (
            self.approval_ledger_path is None
            or self.approval_ledger_lock_path is None
            or not self._approval_verifier_ready()
        ):
            raise PermissionError(
                "External mesh approval ledger is not provisioned"
            )
        with _exclusive_file_lock(self.approval_ledger_lock_path):
            try:
                ledger = json.loads(
                    self.approval_ledger_path.read_text(encoding="utf-8")
                )
            except FileNotFoundError:
                ledger = {
                    "schema": "neyvia.mesh-approval-ledger/v1",
                    "revision": 0,
                    "consumed": {},
                }
            except (OSError, json.JSONDecodeError) as exc:
                raise PermissionError(
                    "External mesh approval ledger is unreadable"
                ) from exc
            if (
                not isinstance(ledger, dict)
                or ledger.get("schema")
                != "neyvia.mesh-approval-ledger/v1"
                or not isinstance(ledger.get("consumed"), dict)
            ):
                raise PermissionError(
                    "External mesh approval ledger is invalid"
                )
            consumed = ledger["consumed"]
            if receipt_id in consumed:
                raise PermissionError(
                    "Mesh mutation approval was already consumed"
                )
            consumed[receipt_id] = {
                "receiptHash": receipt_hash,
                "operation": operation,
                "deviceRef": device_ref,
                "consumedAt": utc_now(),
            }
            ledger["revision"] = int(ledger.get("revision") or 0) + 1
            atomic_write_json(self.approval_ledger_path, ledger)
            try:
                self.approval_ledger_path.chmod(0o600)
            except OSError:
                pass

    def _consume_approval(
        self,
        approval_receipt: dict[str, Any],
        *,
        operation: str,
        device_ref: str,
        payload: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(approval_receipt, dict):
            raise TypeError("approvalReceipt must be an object")
        if (
            approval_receipt.get("schema")
            != "neyvia.mesh-external-approval/v1"
        ):
            raise PermissionError("Invalid external mesh approval receipt")
        if set(approval_receipt) != {
            "schema",
            "receiptId",
            "decision",
            "approvedBy",
            "approvedAt",
            "oneTime",
            "keyId",
            "plan",
            "signature",
        }:
            raise PermissionError(
                "External mesh approval receipt fields are invalid"
            )
        normalized_ref = self._validate_ref(
            approval_receipt.get("receiptId"),
            prefix="mesh-approval",
        )
        if (
            str(approval_receipt.get("keyId") or "").casefold()
            != self.approval_verifier_key_id
        ):
            raise PermissionError(
                "External mesh approval receipt keyId is not trusted"
            )
        self._bounded_text(
            approval_receipt.get("approvedBy"),
            field="approvedBy",
            maximum=120,
        )
        signature_text = str(
            approval_receipt.get("signature") or ""
        ).strip()
        if len(signature_text) > 256:
            raise PermissionError(
                "External mesh approval signature is invalid"
            )
        try:
            signature = base64.b64decode(
                signature_text.encode("ascii"),
                validate=True,
            )
        except (ValueError, UnicodeEncodeError) as exc:
            raise PermissionError(
                "External mesh approval signature is invalid"
            ) from exc
        try:
            self._approval_public_key().verify(
                signature,
                self._signed_receipt_bytes(approval_receipt),
            )
        except InvalidSignature as exc:
            raise PermissionError(
                "External mesh approval signature verification failed"
            ) from exc
        if approval_receipt.get("decision") != "approve":
            raise PermissionError("Mesh mutation approval was denied")
        if approval_receipt.get("oneTime") is not True:
            raise PermissionError("Mesh mutation approval must be one-time")
        plan = approval_receipt.get("plan")
        if (
            not isinstance(plan, dict)
            or plan.get("schema") != "neyvia.mesh-mutation-plan/v1"
        ):
            raise PermissionError("Invalid signed mesh mutation plan")
        self._validate_ref(plan.get("planRef"), prefix="mesh-plan")
        if (
            plan.get("oneTime") is not True
            or plan.get("credentialsExposed") is not False
        ):
            raise PermissionError("Invalid signed mesh mutation plan")
        if str(plan.get("planHash") or "") != self._mesh_plan_hash(plan):
            raise PermissionError("Mesh mutation plan hash changed")
        now = datetime.now(UTC)
        expires_at = self._parse_utc(plan.get("expiresAt"))
        created_at = self._parse_utc(plan.get("createdAt"))
        approved_at = self._parse_utc(
            approval_receipt.get("approvedAt")
        )
        if expires_at <= now:
            raise TimeoutError("Mesh mutation approval expired")
        if expires_at - created_at > timedelta(seconds=900):
            raise PermissionError(
                "Mesh mutation approval lifetime exceeds the allowed bound"
            )
        if created_at > approved_at or approved_at > expires_at:
            raise PermissionError(
                "Mesh mutation approval timestamp is outside its plan"
            )
        if approved_at > now + timedelta(minutes=5):
            raise PermissionError(
                "Mesh mutation approval timestamp is in the future"
            )
        bindings = {
            "operation": operation,
            "deviceRef": device_ref,
            "payloadHash": canonical_hash(payload),
            "policyHash": self._identity_policy_hash(state),
            "baseRevision": int(state.get("revision") or 0),
        }
        for field, expected in bindings.items():
            if plan.get(field) != expected:
                raise PermissionError(
                    f"Mesh mutation approval {field} binding changed"
                )
        self._reserve_approval_receipt(
            receipt_id=normalized_ref,
            receipt_hash=canonical_hash(approval_receipt),
            operation=operation,
            device_ref=device_ref,
        )
        state["approvalSequence"] = int(
            state.get("approvalSequence") or 0
        ) + 1
        return approval_receipt

    @staticmethod
    def _parse_utc(value: object) -> datetime:
        text = str(value or "").strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError(
                "Mesh identity record contains an invalid timestamp"
            ) from exc
        if parsed.tzinfo is None:
            raise RuntimeError(
                "Mesh identity record timestamp must include a timezone"
            )
        return parsed.astimezone(UTC)

    def _expire_enrollment_intents(
        self,
        state: dict[str, Any],
    ) -> bool:
        changed = False
        now = datetime.now(UTC)
        now_text = now.isoformat().replace("+00:00", "Z")
        for row in state["enrollments"].values():
            if row.get("state") not in {
                "pending",
                "local_identity_staged",
            }:
                continue
            if self._parse_utc(row.get("expiresAt")) > now:
                continue
            device_ref = str(row.get("deviceRef") or "")
            row.update({"state": "expired", "updatedAt": now_text})
            device = state["devices"].get(device_ref)
            if isinstance(device, dict) and device.get("state") != "revoked":
                device.update(
                    {
                        "state": "enrollment_expired",
                        "trustState": "quarantined",
                        "localAccessDisabled": True,
                        "updatedAt": now_text,
                        "stateVersion": int(
                            device.get("stateVersion") or 1
                        ) + 1,
                    }
                )
            changed = True
        return changed

    def _expire_lifecycle_requests(
        self,
        state: dict[str, Any],
    ) -> bool:
        changed = False
        now = datetime.now(UTC)
        now_text = now.isoformat().replace("+00:00", "Z")
        for rotation in state["rotations"].values():
            if rotation.get("state") not in {
                "requested",
                "staged_local",
            }:
                continue
            expires_at = rotation.get("expiresAt")
            if not expires_at or self._parse_utc(expires_at) > now:
                continue
            rotation.update(
                {
                    "state": "expired",
                    "candidateFingerprintSha256": "",
                    "updatedAt": now_text,
                }
            )
            changed = True
        for recovery in state["recoveries"].values():
            if recovery.get("state") not in {
                "blocked_provider_recovery",
                "local_identity_reset",
            }:
                continue
            expires_at = recovery.get("expiresAt")
            if not expires_at or self._parse_utc(expires_at) > now:
                continue
            recovery.update(
                {
                    "state": "expired",
                    "updatedAt": now_text,
                }
            )
            device = state["devices"].get(
                str(recovery.get("deviceRef") or "")
            )
            if isinstance(device, dict) and device.get("state") != "revoked":
                device.update(
                    {
                        "trustState": "quarantined",
                        "recoveryState": "expired",
                        "localAccessDisabled": True,
                        "updatedAt": now_text,
                        "stateVersion": int(
                            device.get("stateVersion") or 1
                        ) + 1,
                    }
                )
            changed = True
        return changed

    @staticmethod
    def _require_device(
        state: dict[str, Any],
        device_ref: str,
    ) -> dict[str, Any]:
        device = state["devices"].get(device_ref)
        if not isinstance(device, dict):
            raise KeyError(f"Unknown mesh device identity: {device_ref}")
        return device

    @staticmethod
    def _assert_device_not_revoked(device: dict[str, Any]) -> None:
        if (
            device.get("state") == "revoked"
            or device.get("trustState") == "revoked"
        ):
            raise PermissionError(
                "Revoked mesh device identities cannot transition"
            )

    @staticmethod
    def _acl_rule_matches(
        rule: dict[str, Any],
        *,
        device_ref: str,
        action: str,
        resource: str,
    ) -> bool:
        subjects = {
            str(value).casefold()
            for value in rule.get("subjects") or []
        }
        actions = {
            str(value).casefold()
            for value in rule.get("actions") or []
        }
        resources = [
            str(value) for value in rule.get("resources") or []
        ]
        if "*" not in subjects and device_ref not in subjects:
            return False
        if "*" not in actions and action not in actions:
            return False
        return any(
            pattern == "*"
            or pattern == resource
            or (
                pattern.endswith("*")
                and resource.startswith(pattern[:-1])
            )
            for pattern in resources
        )

    def _disable_services_for_device(
        self,
        device_ref: str,
        *,
        revoked_by: str,
        reason: str,
    ) -> int:
        changed = 0
        with self._service_transaction() as services:
            now = utc_now()
            for row in services["services"]:
                if (
                    row.get("deviceId") == device_ref
                    and row.get("enabled") is not False
                ):
                    row.update(
                        {
                            "enabled": False,
                            "revokedAt": now,
                            "revokedBy": revoked_by,
                            "revocationReason": reason,
                        }
                    )
                    changed += 1
        return changed

    def _validate_private_endpoint(self, endpoint: str) -> None:
        parsed = urlparse(endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "endpoint must be a credential-free private HTTP(S) URL"
            )
        host = parsed.hostname.casefold()
        allowed_names: set[str] = set()
        provider = self.snapshot()["provider"]
        for row in [
            provider.get("self"),
            *(provider.get("peers") or []),
        ]:
            if not isinstance(row, dict):
                continue
            allowed_names.update(
                {
                    str(row.get("hostName") or "").casefold(),
                    str(row.get("dnsName") or "").casefold(),
                    *(
                        str(item).casefold()
                        for item in row.get("addresses") or []
                    ),
                }
            )
        if host in allowed_names or host.endswith(".neyvia.mesh"):
            return
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError(
                "endpoint host is not an enrolled private-mesh peer"
            ) from exc
        tailscale_range = ipaddress.ip_network("100.64.0.0/10")
        if (
            address.is_loopback
            or address.is_private
            or (
                isinstance(address, ipaddress.IPv4Address)
                and address in tailscale_range
            )
        ):
            return
        raise ValueError("endpoint must stay on a private network")

    @classmethod
    def _reject_secret_keys(cls, value: object, path: str = "$") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if _FORBIDDEN_KEY.search(str(key)):
                    raise ValueError(
                        f"{path}.{key}: secret-bearing keys are forbidden"
                    )
                cls._reject_secret_keys(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                cls._reject_secret_keys(item, f"{path}[{index}]")
