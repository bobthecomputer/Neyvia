"""Offline, fail-closed contract for signed Neyvia desktop updates.

This module deliberately does not fetch releases or install artifacts.  It
turns already-discovered metadata and local verification receipts into a
bounded update plan.  Network and process execution stay in supervised
adapters outside this trust decision.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .dependency_inventory import DependencyInventory, DependencyInventoryError


UPDATER_POLICY_SCHEMA = "neyvia.updater-policy/v1"
UPDATE_MANIFEST_SCHEMA = "neyvia.update-manifest/v1"
UPDATE_PLAN_SCHEMA = "neyvia.update-plan/v1"
UPDATE_PROGRESS_SCHEMA = "neyvia.update-progress/v1"
LOCAL_EVIDENCE_SCHEMA = "neyvia.local-verification-receipt/v1"
ARTIFACT_IDENTITY_SCHEMA = "neyvia.update-artifact-identity/v1"
DELTA_IDENTITY_SCHEMA = "neyvia.update-delta-identity/v1"

CHANNELS = ("stable", "beta", "development")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_LEAF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,254}$")
UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
CONTEXT_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,160}$")
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{22,160}$")
WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
VERSION_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)

REQUIRED_GATES = ("compatibility", "license", "malware", "performance")
PROGRESS_STATES = {
    "idle": 0,
    "discovering": 5,
    "candidate_found": 10,
    "verifying_signature": 15,
    "gating": 25,
    "ready": 35,
    "downloading": 55,
    "verifying_artifact": 70,
    "staging": 80,
    "installing": 90,
    "health_check": 95,
    "completed": 100,
    "restored_previous": 100,
    "rollback": 60,
    "recovery": 70,
    "failed": 100,
    "blocked": 100,
}
STATE_TRANSITIONS = {
    "idle": {"discovering"},
    "discovering": {"candidate_found", "idle", "failed", "blocked"},
    "candidate_found": {"verifying_signature", "idle", "failed", "blocked"},
    "verifying_signature": {"gating", "failed", "blocked"},
    "gating": {"ready", "failed", "blocked"},
    "ready": {"downloading", "idle", "blocked"},
    "downloading": {"verifying_artifact", "failed", "blocked"},
    "verifying_artifact": {"staging", "failed", "blocked"},
    "staging": {"installing", "failed", "blocked"},
    "installing": {"health_check", "rollback", "failed"},
    "health_check": {"completed", "rollback", "failed"},
    "rollback": {"recovery", "failed", "blocked"},
    "recovery": {"restored_previous", "failed", "blocked"},
    "completed": set(),
    "restored_previous": set(),
    "failed": {"rollback", "recovery"},
    "blocked": {"idle"},
}
TERMINAL_STATES = frozenset(
    state for state, outgoing in STATE_TRANSITIONS.items() if not outgoing
)


class UpdaterContractError(ValueError):
    """Raised when an update cannot safely cross the contract boundary."""


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise UpdaterContractError(
            "signed payload must be canonical JSON data"
        ) from exc
    return (serialized + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_leaf_name(value: object, *, field: str) -> str:
    name = str(value or "")
    if (
        not SAFE_LEAF_RE.fullmatch(name)
        or name in {".", ".."}
        or name.endswith(".")
        or "/" in name
        or "\\" in name
        or ":" in name
        or name.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES
    ):
        raise UpdaterContractError(f"{field} must be a safe leaf filename")
    return name


def _context_id(value: object, *, field: str) -> str:
    text = str(value or "")
    if not CONTEXT_ID_RE.fullmatch(text):
        raise UpdaterContractError(f"{field} is not a bounded opaque identifier")
    return text


def _sanitize_detail(value: object) -> str:
    if not isinstance(value, str):
        raise UpdaterContractError("update progress detail must be a string")
    detail = "".join(character if character >= " " else " " for character in value)
    detail = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", detail)
    detail = re.sub(
        r"(?i)\b(authorization|password|token|secret|api[_-]?key|"
        r"private[_-]?key)\s*[:=]\s*\S+",
        lambda match: f"{match.group(1)}=[REDACTED]",
        detail,
    )
    return detail[:500]


def _parse_utc(value: object, *, field: str) -> datetime:
    text = str(value or "")
    if not UTC_TIMESTAMP_RE.fullmatch(text):
        raise UpdaterContractError(f"{field} must be an exact UTC timestamp")
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )


def _decode_base64(value: object, *, field: str, expected_bytes: int) -> bytes:
    try:
        decoded = base64.b64decode(str(value or ""), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise UpdaterContractError(f"{field} must be canonical base64") from exc
    if len(decoded) != expected_bytes:
        raise UpdaterContractError(
            f"{field} must decode to exactly {expected_bytes} bytes"
        )
    if base64.b64encode(decoded).decode("ascii") != value:
        raise UpdaterContractError(f"{field} must use canonical base64 encoding")
    return decoded


def _verify_ed25519(
    public_key_base64: object,
    signature_base64: object,
    payload: bytes,
    *,
    field: str,
) -> None:
    public_key = _decode_base64(
        public_key_base64,
        field=f"{field} public key",
        expected_bytes=32,
    )
    signature = _decode_base64(
        signature_base64,
        field=f"{field} signature",
        expected_bytes=64,
    )
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload)
    except InvalidSignature as exc:
        raise UpdaterContractError(f"{field} signature verification failed") from exc


def _parse_version(
    value: str,
) -> tuple[tuple[int, int, int], tuple[int | str, ...] | None]:
    match = VERSION_RE.fullmatch(str(value or "").strip())
    if not match:
        raise UpdaterContractError(f"invalid semantic version: {value!r}")
    core = tuple(int(match.group(index)) for index in (1, 2, 3))
    raw_prerelease = match.group(4)
    if raw_prerelease is None:
        return core, None
    prerelease: list[int | str] = []
    for identifier in raw_prerelease.split("."):
        if identifier.isdigit():
            if len(identifier) > 1 and identifier.startswith("0"):
                raise UpdaterContractError(
                    f"invalid semantic version prerelease: {value!r}"
                )
            prerelease.append(int(identifier))
        else:
            prerelease.append(identifier)
    return core, tuple(prerelease)


def _compare_versions(left: str, right: str) -> int:
    left_core, left_prerelease = _parse_version(left)
    right_core, right_prerelease = _parse_version(right)
    if left_core != right_core:
        return -1 if left_core < right_core else 1
    if left_prerelease is None:
        return 0 if right_prerelease is None else 1
    if right_prerelease is None:
        return -1
    for left_part, right_part in zip(left_prerelease, right_prerelease):
        if left_part == right_part:
            continue
        if isinstance(left_part, int) and isinstance(right_part, str):
            return -1
        if isinstance(left_part, str) and isinstance(right_part, int):
            return 1
        return -1 if left_part < right_part else 1
    if len(left_prerelease) == len(right_prerelease):
        return 0
    return -1 if len(left_prerelease) < len(right_prerelease) else 1


def _range_allows(version: str, expression: str) -> bool:
    _parse_version(version)
    tokens = [token for token in re.split(r"[\s,]+", expression.strip()) if token]
    if not tokens:
        return False
    for token in tokens:
        match = re.fullmatch(r"(>=|<=|>|<|==|=)?(.+)", token)
        if not match:
            return False
        operator = match.group(1) or "="
        try:
            comparison = _compare_versions(version, match.group(2))
        except UpdaterContractError:
            return False
        if operator in {"=", "=="} and comparison != 0:
            return False
        if operator == ">=" and comparison < 0:
            return False
        if operator == "<=" and comparison > 0:
            return False
        if operator == ">" and comparison <= 0:
            return False
        if operator == "<" and comparison >= 0:
            return False
    return True


def manifest_signature_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in manifest.items() if key != "signature"}


def artifact_signature_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    artifact = manifest["artifact"]
    return {
        "schema": ARTIFACT_IDENTITY_SCHEMA,
        "channel": manifest["channel"],
        "version": manifest["version"],
        "name": artifact["name"],
        "bytes": artifact["bytes"],
        "sha256": artifact["sha256"],
        "reproducibleBuildId": artifact["reproducibleBuildId"],
    }


def delta_signature_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    delta = manifest["delta"]
    return {
        "schema": DELTA_IDENTITY_SCHEMA,
        "channel": manifest["channel"],
        "version": manifest["version"],
        "name": delta["name"],
        "fromVersion": delta["fromVersion"],
        "fromArtifactSha256": delta["fromArtifactSha256"],
        "bytes": delta["bytes"],
        "sha256": delta["sha256"],
        "finalArtifactSha256": manifest["artifact"]["sha256"],
    }


def local_receipt_payload(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in receipt.items()
        if key not in {"proof", "receiptSha256"}
    }


@dataclass(frozen=True)
class UpdateProgress:
    state: str = "idle"
    percent: int = 0
    detail: str = ""

    def __post_init__(self) -> None:
        if self.state not in PROGRESS_STATES:
            raise UpdaterContractError(
                f"unknown update state: {self.state or '<missing>'}"
            )
        if type(self.percent) is not int or self.percent != PROGRESS_STATES[self.state]:
            raise UpdaterContractError(
                f"invalid percent for update state {self.state}"
            )
        object.__setattr__(self, "detail", _sanitize_detail(self.detail))

    def transition(self, target: str, *, detail: str = "") -> "UpdateProgress":
        target = str(target or "").strip()
        if target not in PROGRESS_STATES:
            raise UpdaterContractError(f"unknown update state: {target or '<missing>'}")
        if target not in STATE_TRANSITIONS[self.state]:
            raise UpdaterContractError(
                f"invalid update transition: {self.state} -> {target}"
            )
        return UpdateProgress(
            state=target,
            percent=PROGRESS_STATES[target],
            detail=detail,
        )

    def as_receipt(self) -> dict[str, Any]:
        return {
            "schema": UPDATE_PROGRESS_SCHEMA,
            "state": self.state,
            "percent": self.percent,
            "detail": self.detail,
            "terminal": self.state in TERMINAL_STATES,
            "outcome": (
                "target-installed"
                if self.state == "completed"
                else (
                    "previous-version-restored"
                    if self.state == "restored_previous"
                    else "pending"
                )
            ),
        }


class UpdaterContract:
    """Validate local update evidence and produce a side-effect-free plan."""

    def __init__(
        self,
        root: str | Path,
        *,
        config_path: str | Path | None = None,
        _clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        project_root = Path(__file__).resolve().parents[2]
        local_config = self.root / "config" / "neyvia_updater.json"
        selected = Path(config_path or local_config)
        if not selected.is_file():
            selected = project_root / "config" / "neyvia_updater.json"
        if not selected.is_file():
            raise FileNotFoundError(selected)
        self.config_path = selected.resolve()
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self._validate_policy()
        self._clock = _clock or (lambda: datetime.now(timezone.utc))
        inventory_relative = Path(
            str(self.config["dependencyInventory"]["path"])
        )
        self.dependency_inventory_path = (
            self.root / inventory_relative
        ).resolve()
        try:
            self.dependency_inventory_path.relative_to(self.root)
        except ValueError as exc:
            raise UpdaterContractError(
                "dependency inventory path escapes the updater root"
            ) from exc
        ledger_relative = Path(str(self.config["consumedReceiptLedger"]))
        if (
            ledger_relative.is_absolute()
            or not ledger_relative.parts
            or any(part in {"", ".", ".."} for part in ledger_relative.parts)
        ):
            raise UpdaterContractError(
                "consumed receipt ledger must be a safe root-relative path"
            )
        self.consumed_receipt_ledger = (self.root / ledger_relative).resolve()
        try:
            self.consumed_receipt_ledger.relative_to(self.root)
        except ValueError as exc:
            raise UpdaterContractError(
                "consumed receipt ledger escapes the updater root"
            ) from exc

    def _validate_policy(self) -> None:
        if self.config.get("schema") != UPDATER_POLICY_SCHEMA:
            raise UpdaterContractError("unsupported updater policy schema")
        channels = self.config.get("channels")
        if not isinstance(channels, dict) or tuple(channels) != CHANNELS:
            raise UpdaterContractError(
                "updater policy must declare stable, beta, development in order"
            )
        if self.config.get("networkExecution") != "external-supervised-adapter":
            raise UpdaterContractError("updater contract must not own network execution")
        if not str(self.config.get("consumedReceiptLedger") or "").strip():
            raise UpdaterContractError("consumed receipt ledger is required")
        upstream = self.config.get("upstreamDiscovery") or {}
        if upstream.get("manifestRequired") is not True:
            raise UpdaterContractError("signed upstream manifests are required")
        if upstream.get("allowUnsigned") is not False:
            raise UpdaterContractError("unsigned upstream metadata is forbidden")
        allowed_origins = upstream.get("allowedOrigins") or []
        if not allowed_origins or any(
            not self._is_exact_https_origin(origin) for origin in allowed_origins
        ):
            raise UpdaterContractError("discovery origins must be explicit HTTPS origins")
        self._validate_manifest_template(upstream.get("manifestPathTemplate"))
        if set(self.config.get("requiredGates") or []) != set(REQUIRED_GATES):
            raise UpdaterContractError("all required updater gates must be configured")
        inventory = self.config.get("dependencyInventory") or {}
        inventory_path = Path(str(inventory.get("path") or ""))
        if (
            inventory.get("required") is not True
            or inventory.get("rebuildAndCompare") is not True
            or inventory.get("failOnCriticalUnresolved") is not True
            or inventory_path.is_absolute()
            or bool(inventory_path.drive)
            or not inventory_path.parts
            or any(part in {"", ".", ".."} for part in inventory_path.parts)
            or "\\" in str(inventory.get("path") or "")
            or ":" in str(inventory.get("path") or "")
        ):
            raise UpdaterContractError(
                "dependency inventory policy must require a safe canonical rebuild"
            )
        signing = self.config.get("signing") or {}
        if signing.get("allowedSchemes") != ["ed25519-detached"]:
            raise UpdaterContractError("only raw Ed25519 detached signatures are allowed")
        self._validate_pinned_keys(signing.get("trustedKeys"), "release")
        evidence = self.config.get("localEvidence") or {}
        self._validate_pinned_keys(evidence.get("trustedVerifiers"), "verifier")
        if (
            type(evidence.get("maxAgeSeconds")) is not int
            or not 1 <= evidence["maxAgeSeconds"] <= 86_400
            or type(evidence.get("maxFutureSkewSeconds")) is not int
            or not 0 <= evidence["maxFutureSkewSeconds"] <= 300
        ):
            raise UpdaterContractError("local evidence freshness bounds are invalid")
        peer_policy = (self.config.get("delivery") or {}).get("peerAssisted") or {}
        if not SHA256_RE.fullmatch(
            str(peer_policy.get("allowlistPolicySha256") or "")
        ):
            raise UpdaterContractError("peer allowlist policy hash is required")
        if (
            not isinstance(peer_policy.get("allowlistPolicy"), dict)
            or not hmac.compare_digest(
                peer_policy["allowlistPolicySha256"],
                _sha256_bytes(
                    _canonical_bytes(peer_policy["allowlistPolicy"])
                ),
            )
        ):
            raise UpdaterContractError(
                "peer allowlist policy hash does not match its policy"
            )
        _context_id(
            peer_policy.get("transportIdentity"),
            field="peer transport identity",
        )

    @staticmethod
    def _is_exact_https_origin(value: object) -> bool:
        text = str(value or "")
        try:
            parsed = urlsplit(text)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError:
            return False
        if (
            parsed.scheme != "https"
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            return False
        expected = f"https://{hostname}"
        if port is not None:
            expected += f":{port}"
        return text == expected

    @staticmethod
    def _validate_manifest_template(value: object) -> None:
        template = str(value or "")
        if (
            not template.startswith("/")
            or template.count("{channel}") != 1
            or "\\" in template
            or ".." in template
            or "//" in template
            or "?" in template
            or "#" in template
            or "%" in template
            or "{" in template.replace("{channel}", "")
            or "}" in template.replace("{channel}", "")
            or not re.fullmatch(r"/[A-Za-z0-9._{}/-]+", template)
        ):
            raise UpdaterContractError("manifest path template is unsafe")
        for channel in CHANNELS:
            rendered = template.replace("{channel}", channel)
            if not rendered.startswith("/") or any(
                part in {"", ".", ".."} for part in rendered[1:].split("/")
            ):
                raise UpdaterContractError("manifest path template is unsafe")

    @staticmethod
    def _validate_pinned_keys(value: object, label: str) -> None:
        if not isinstance(value, dict) or not value:
            raise UpdaterContractError(f"trusted {label} keys are required")
        for key_id, key in value.items():
            if not isinstance(key, dict) or key.get("keyId") != key_id:
                raise UpdaterContractError(f"{label} key identity is inconsistent")
            if type(key.get("provisioned")) is not bool:
                raise UpdaterContractError(
                    f"{label} key provisioned state must be explicit"
                )
            public = _decode_base64(
                key.get("publicKeyBase64"),
                field=f"{label} public key",
                expected_bytes=32,
            )
            fingerprint = _sha256_bytes(public)
            if not hmac.compare_digest(
                str(key.get("fingerprintSha256") or ""), fingerprint
            ):
                raise UpdaterContractError(f"{label} key fingerprint is invalid")
            if not str(key.get("identity") or "").strip():
                raise UpdaterContractError(f"{label} verifier identity is required")

    def channel(self, name: str) -> dict[str, Any]:
        value = str(name or "").strip().lower()
        if value not in CHANNELS:
            raise UpdaterContractError(f"unsupported update channel: {value or '<missing>'}")
        return dict(self.config["channels"][value])

    def discovery_plan(self, channel: str) -> dict[str, Any]:
        metadata = self.channel(channel)
        upstream = self.config["upstreamDiscovery"]
        return {
            "schema": "neyvia.update-discovery-plan/v1",
            "channel": channel,
            "track": metadata["track"],
            "source": upstream["source"],
            "allowedOrigins": list(upstream["allowedOrigins"]),
            "manifestPathTemplate": upstream["manifestPathTemplate"],
            "networkExecution": self.config["networkExecution"],
            "limits": dict(upstream["limits"]),
            "requirements": [
                "https-only",
                "no-redirect-outside-allowlist",
                "bounded-response",
                "detached-signature-before-candidate-use",
                "canonical-dependency-inventory-digest",
                "resolved-critical-dependency-ownership-and-license",
            ],
            "cryptographicAcceptance": self.config["signing"]["acceptanceState"],
        }

    def _dependency_inventory_preflight(self) -> dict[str, Any]:
        policy = self.config["dependencyInventory"]
        try:
            return DependencyInventory(self.root).verify_written(
                self.dependency_inventory_path,
                require_critical_resolved=bool(
                    policy["failOnCriticalUnresolved"]
                ),
            )
        except DependencyInventoryError as exc:
            raise UpdaterContractError(
                f"dependency inventory preflight failed: {exc}"
            ) from exc

    def _recheck_dependency_inventory(
        self, inventory: Mapping[str, Any], *, stage: str
    ) -> None:
        try:
            digest = DependencyInventory(self.root).recheck_sources(inventory)
        except DependencyInventoryError as exc:
            raise UpdaterContractError(
                f"dependency inventory {stage} recheck failed: {exc}"
            ) from exc
        if not hmac.compare_digest(
            digest, str(inventory["inventorySha256"])
        ):
            raise UpdaterContractError(
                f"dependency inventory digest changed during {stage}"
            )

    def assess_candidate(
        self,
        manifest: Mapping[str, Any],
        evidence: Mapping[str, Any],
        *,
        current_version: str,
        platform: str,
        architecture: str,
        requested_channel: str,
        device_ref: str,
        update_request_id: str,
        request_nonce: str,
        peer_identity: str = "",
        peer_session_id: str = "",
    ) -> dict[str, Any]:
        """Return a deterministic plan or raise before any artifact is accepted."""

        if not isinstance(manifest, Mapping) or not isinstance(evidence, Mapping):
            raise UpdaterContractError("manifest and local evidence must be objects")
        checked_at = self._clock()
        if not isinstance(checked_at, datetime):
            raise UpdaterContractError("trusted updater clock returned an invalid value")
        if checked_at.tzinfo is None:
            raise UpdaterContractError("trusted updater clock must be timezone-aware")
        checked_at = checked_at.astimezone(timezone.utc)
        device_ref = _context_id(device_ref, field="deviceRef")
        update_request_id = _context_id(
            update_request_id, field="updateRequestId"
        )
        if not NONCE_RE.fullmatch(str(request_nonce or "")):
            raise UpdaterContractError("request nonce is invalid")
        request_nonce = str(request_nonce)
        peer_identity = str(peer_identity or "")
        peer_session_id = str(peer_session_id or "")
        dependency_inventory = self._dependency_inventory_preflight()
        errors = self._manifest_errors(
            manifest,
            current_version=current_version,
            platform=platform,
            architecture=architecture,
            requested_channel=requested_channel,
            dependency_inventory_sha256=dependency_inventory["inventorySha256"],
        )
        errors.extend(
            self._evidence_errors(
                manifest,
                evidence,
                current_version=current_version,
                platform=platform,
                architecture=architecture,
                requested_channel=requested_channel,
                device_ref=device_ref,
                update_request_id=update_request_id,
                request_nonce=request_nonce,
                now=checked_at,
            )
        )
        if errors:
            raise UpdaterContractError("; ".join(sorted(set(errors))))

        artifact = dict(manifest["artifact"])
        optional = self._optional_delivery_evidence(
            manifest,
            evidence,
            current_version=current_version,
            platform=platform,
            architecture=architecture,
            requested_channel=requested_channel,
            device_ref=device_ref,
            update_request_id=update_request_id,
            request_nonce=request_nonce,
            peer_identity=peer_identity,
            peer_session_id=peer_session_id,
            now=checked_at,
        )
        delivery = self._delivery_plan(
            manifest,
            current_version=current_version,
            delta_eligible=optional["deltaEligible"],
            peer_eligible=optional["peerEligible"],
            optional_fallback_reasons=optional["fallbackReasons"],
        )
        receipts = self._selected_receipts(
            evidence,
            include_delta=optional["deltaEligible"],
            include_peer=optional["peerEligible"],
        )
        receipt_digests = sorted(
            str(receipt["receiptSha256"]) for receipt in receipts
        )
        receipt_set_sha256 = _sha256_bytes(
            _canonical_bytes({"receiptSha256": receipt_digests})
        )
        valid_until = min(
            _parse_utc(receipt["expiresAt"], field="receipt expiresAt")
            for receipt in receipts
        )
        self._recheck_dependency_inventory(
            dependency_inventory, stage="pre-consumption"
        )
        self._consume_receipts_once(
            evidence,
            include_delta=optional["deltaEligible"],
            include_peer=optional["peerEligible"],
            update_request_id=update_request_id,
            consumed_at=checked_at,
        )
        self._recheck_dependency_inventory(
            dependency_inventory, stage="pre-return"
        )
        signed_payload = manifest_signature_payload(manifest)
        return {
            "schema": UPDATE_PLAN_SCHEMA,
            "accepted": True,
            "channel": requested_channel,
            "currentVersion": current_version,
            "targetVersion": manifest["version"],
            "deviceRef": device_ref,
            "updateRequestId": update_request_id,
            "requestNonceSha256": _sha256_bytes(
                request_nonce.encode("utf-8")
            ),
            "createdAt": checked_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "validUntil": valid_until.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "receiptSetSha256": receipt_set_sha256,
            "manifestSha256": hashlib.sha256(
                _canonical_bytes(signed_payload)
            ).hexdigest(),
            "dependencyInventorySha256": dependency_inventory[
                "inventorySha256"
            ],
            "artifact": {
                "name": artifact["name"],
                "bytes": artifact["bytes"],
                "sha256": artifact["sha256"],
                "reproducibleBuildId": artifact["reproducibleBuildId"],
                "signature": dict(artifact["signature"]),
            },
            "delivery": delivery,
            "gates": {
                name: evidence["gates"][name]["receiptSha256"]
                for name in REQUIRED_GATES
            },
            "cryptographicAcceptance": "proven-locally",
            "execution": {
                "executable": False,
                "state": "preflight-only",
                "requiresFreshInventoryRecheck": True,
                "requiresFreshArtifactVerification": True,
                "reason": (
                    "Execution must rerun preflight against the request nonce, "
                    "receipt set, artifact, and current dependency inputs."
                ),
            },
            "rollback": {
                "required": True,
                "previousVersion": current_version,
                "healthWindowSeconds": self.config["rollback"]["healthWindowSeconds"],
                "recovery": list(self.config["rollback"]["recoveryOrder"]),
            },
        }

    def _manifest_errors(
        self,
        manifest: Mapping[str, Any],
        *,
        current_version: str,
        platform: str,
        architecture: str,
        requested_channel: str,
        dependency_inventory_sha256: str,
    ) -> list[str]:
        errors: list[str] = []
        if manifest.get("schema") != UPDATE_MANIFEST_SCHEMA:
            errors.append("unsupported or missing update manifest schema")
        try:
            channel = self.channel(requested_channel)
        except UpdaterContractError as exc:
            return [str(exc)]
        if manifest.get("channel") != requested_channel:
            errors.append("manifest channel does not match the requested channel")
        declared_inventory = str(
            manifest.get("dependencyInventorySha256") or ""
        )
        if not SHA256_RE.fullmatch(declared_inventory):
            errors.append(
                "manifest dependency inventory SHA-256 is required"
            )
        elif not hmac.compare_digest(
            declared_inventory, dependency_inventory_sha256
        ):
            errors.append(
                "manifest dependency inventory digest does not match current canonical inventory"
            )
        version = str(manifest.get("version") or "")
        try:
            if _compare_versions(version, current_version) <= 0:
                errors.append("candidate version must be newer than the installed version")
        except UpdaterContractError as exc:
            errors.append(str(exc))
        try:
            prerelease = _parse_version(version)[1]
            if channel.get("prereleaseAllowed") is False and prerelease is not None:
                errors.append("stable channel cannot accept prerelease versions")
        except UpdaterContractError:
            pass

        compatibility = manifest.get("compatibility") or {}
        if platform not in compatibility.get("platforms", []):
            errors.append(f"candidate is not compatible with platform {platform}")
        if architecture not in compatibility.get("architectures", []):
            errors.append(f"candidate is not compatible with architecture {architecture}")
        if not _range_allows(current_version, str(compatibility.get("fromVersions") or "")):
            errors.append("installed version is outside the declared upgrade range")

        artifact = manifest.get("artifact")
        if not isinstance(artifact, dict):
            return errors + ["manifest artifact is required"]
        try:
            _safe_leaf_name(artifact.get("name"), field="artifact name")
        except UpdaterContractError as exc:
            errors.append(str(exc))
        if type(artifact.get("bytes")) is not int or artifact.get("bytes", 0) <= 0:
            errors.append("artifact bytes must be a positive integer")
        if not SHA256_RE.fullmatch(str(artifact.get("sha256") or "")):
            errors.append("artifact SHA-256 must be a lowercase 64-character digest")
        build_id = str(artifact.get("reproducibleBuildId") or "")
        if (
            not build_id
            or len(build_id) > 200
            or any(character < " " for character in build_id)
        ):
            errors.append("artifact reproducible build identity is required")
        try:
            artifact_payload = artifact_signature_payload(manifest)
        except (KeyError, TypeError):
            artifact_payload = {}
        errors.extend(
            self._release_signature_errors(
                artifact.get("signature"),
                "artifact",
                artifact_payload,
            )
        )

        delta = manifest.get("delta")
        if delta is not None:
            if not isinstance(delta, dict):
                errors.append("delta must be an object")
            else:
                try:
                    _safe_leaf_name(delta.get("name"), field="delta name")
                except UpdaterContractError as exc:
                    errors.append(str(exc))
                if type(delta.get("bytes")) is not int or delta.get("bytes", 0) <= 0:
                    errors.append("delta bytes must be a positive integer")
                if not SHA256_RE.fullmatch(str(delta.get("sha256") or "")):
                    errors.append("delta SHA-256 is invalid")
                if not SHA256_RE.fullmatch(
                    str(delta.get("fromArtifactSha256") or "")
                ):
                    errors.append("delta base artifact SHA-256 is invalid")
                try:
                    delta_payload = delta_signature_payload(manifest)
                except (KeyError, TypeError):
                    delta_payload = {}
                errors.extend(
                    self._release_signature_errors(
                        delta.get("signature"),
                        "delta",
                        delta_payload,
                    )
                )
        errors.extend(
            self._release_signature_errors(
                manifest.get("signature"),
                "manifest",
                manifest_signature_payload(manifest),
            )
        )
        return errors

    def _release_signature_errors(
        self,
        value: object,
        subject: str,
        payload: Mapping[str, Any],
    ) -> list[str]:
        if not isinstance(value, dict):
            return [f"{subject} signature is required"]
        signing = self.config["signing"]
        expected_fields = {"scheme", "keyId", "keyFingerprintSha256", "value"}
        errors: list[str] = []
        if set(value) != expected_fields:
            errors.append(f"{subject} signature fields are invalid")
        if value.get("scheme") != "ed25519-detached":
            errors.append(f"{subject} signature scheme is not allowed")
        trusted_key = (signing.get("trustedKeys") or {}).get(value.get("keyId"))
        if not isinstance(trusted_key, dict):
            errors.append(f"{subject} signature key is not trusted")
            return errors
        if trusted_key.get("provisioned") is not True:
            errors.append(
                f"{subject} cryptographic acceptance is unproven: "
                "release trust root is not provisioned"
            )
        if not hmac.compare_digest(
            str(value.get("keyFingerprintSha256") or ""),
            trusted_key["fingerprintSha256"],
        ):
            errors.append(f"{subject} signature fingerprint is not trusted")
        try:
            _verify_ed25519(
                trusted_key["publicKeyBase64"],
                value.get("value"),
                _canonical_bytes(payload),
                field=subject,
            )
        except UpdaterContractError as exc:
            errors.append(str(exc))
        return errors

    def _evidence_errors(
        self,
        manifest: Mapping[str, Any],
        evidence: Mapping[str, Any],
        *,
        current_version: str,
        platform: str,
        architecture: str,
        requested_channel: str,
        device_ref: str,
        update_request_id: str,
        request_nonce: str,
        now: datetime,
    ) -> list[str]:
        errors: list[str] = []
        allowed_fields = {
            "artifactReceipt",
            "gates",
            "optInReceipt",
            "deltaReceipt",
            "peerReceipt",
        }
        unknown = sorted(set(evidence) - allowed_fields)
        if unknown:
            errors.append(f"unsupported caller evidence fields: {unknown}")
        common = self._common_evidence_subject(
            manifest,
            current_version=current_version,
            platform=platform,
            architecture=architecture,
            requested_channel=requested_channel,
            device_ref=device_ref,
            update_request_id=update_request_id,
            request_nonce=request_nonce,
        )
        artifact = manifest.get("artifact") or {}
        artifact_subject = {
            **common,
            "name": artifact.get("name"),
            "bytes": artifact.get("bytes"),
            "reproducibleBuildId": artifact.get("reproducibleBuildId"),
        }
        errors.extend(
            self._local_receipt_errors(
                evidence.get("artifactReceipt"),
                kind="artifact-content",
                subject=artifact_subject,
                now=now,
            )
        )
        gates = evidence.get("gates")
        if not isinstance(gates, dict):
            return errors + ["all update gate receipts are required"]
        if set(gates) != set(REQUIRED_GATES):
            errors.append("gate receipt set must exactly match required gates")
        for name in REQUIRED_GATES:
            receipt = gates.get(name)
            errors.extend(
                self._local_receipt_errors(
                    receipt,
                    kind=f"gate:{name}",
                    subject={**common, "gate": name},
                    now=now,
                )
            )
        opt_in_required = self.channel(requested_channel).get("operatorOptIn") is True
        if opt_in_required:
            errors.extend(
                self._local_receipt_errors(
                    evidence.get("optInReceipt"),
                    kind="channel-opt-in",
                    subject=common,
                    now=now,
                )
            )
        elif evidence.get("optInReceipt") is not None:
            errors.append("stable channel must not accept an unrelated opt-in receipt")
        return errors

    @staticmethod
    def _common_evidence_subject(
        manifest: Mapping[str, Any],
        *,
        current_version: str,
        platform: str,
        architecture: str,
        requested_channel: str,
        device_ref: str,
        update_request_id: str,
        request_nonce: str,
    ) -> dict[str, Any]:
        artifact = manifest.get("artifact") or {}
        return {
            "manifestSha256": hash_signed_manifest_payload(manifest),
            "dependencyInventorySha256": manifest.get(
                "dependencyInventorySha256"
            ),
            "artifactSha256": artifact.get("sha256"),
            "platform": platform,
            "architecture": architecture,
            "currentVersion": current_version,
            "targetVersion": manifest.get("version"),
            "channel": requested_channel,
            "channelOptIn": requested_channel != "stable",
            "deviceRef": device_ref,
            "updateRequestId": update_request_id,
            "requestNonce": request_nonce,
        }

    def _optional_delivery_evidence(
        self,
        manifest: Mapping[str, Any],
        evidence: Mapping[str, Any],
        *,
        current_version: str,
        platform: str,
        architecture: str,
        requested_channel: str,
        device_ref: str,
        update_request_id: str,
        request_nonce: str,
        peer_identity: str,
        peer_session_id: str,
        now: datetime,
    ) -> dict[str, Any]:
        common = self._common_evidence_subject(
            manifest,
            current_version=current_version,
            platform=platform,
            architecture=architecture,
            requested_channel=requested_channel,
            device_ref=device_ref,
            update_request_id=update_request_id,
            request_nonce=request_nonce,
        )
        artifact = manifest["artifact"]
        delta = manifest.get("delta")
        delta_eligible = False
        reasons: list[str] = []
        if isinstance(delta, dict):
            receipt = evidence.get("deltaReceipt")
            delta_eligible = (
                delta.get("fromVersion") == current_version
                and isinstance(receipt, dict)
                and not self._local_receipt_errors(
                    receipt,
                    kind="delta-content",
                    subject={
                        **common,
                        "baseArtifactSha256": delta.get("fromArtifactSha256"),
                        "deltaSha256": delta.get("sha256"),
                        "finalArtifactSha256": artifact.get("sha256"),
                    },
                    now=now,
                )
            )
            if not delta_eligible:
                reasons.append("delta-ineligible-use-full-artifact")

        selected_hash = (
            delta["sha256"] if delta_eligible else artifact["sha256"]
        )
        peer_policy = self.config["delivery"]["peerAssisted"]
        peer_receipt = evidence.get("peerReceipt")
        peer_eligible = (
            isinstance(peer_receipt, dict)
            and CONTEXT_ID_RE.fullmatch(peer_identity) is not None
            and CONTEXT_ID_RE.fullmatch(peer_session_id) is not None
            and not self._local_receipt_errors(
                peer_receipt,
                kind="peer-content",
                subject={
                    **common,
                    "contentSha256": selected_hash,
                    "peerIdentity": peer_identity,
                    "allowlistPolicySha256": peer_policy[
                        "allowlistPolicySha256"
                    ],
                    "sessionIdentity": peer_session_id,
                    "transportIdentity": peer_policy["transportIdentity"],
                },
                now=now,
            )
        )
        if not peer_eligible:
            reasons.append("peer-ineligible-use-supervised-upstream")
        return {
            "deltaEligible": delta_eligible,
            "peerEligible": peer_eligible,
            "fallbackReasons": reasons,
        }

    def _local_receipt_errors(
        self,
        receipt: object,
        *,
        kind: str,
        subject: Mapping[str, Any],
        now: datetime,
    ) -> list[str]:
        if not isinstance(receipt, dict):
            return [f"{kind} signed local receipt is required"]
        expected_fields = {
            "schema",
            "kind",
            "verifier",
            "issuedAt",
            "expiresAt",
            "subject",
            "result",
            "receiptSha256",
            "proof",
        }
        errors: list[str] = []
        if set(receipt) != expected_fields:
            errors.append(f"{kind} receipt fields are invalid")
        if receipt.get("schema") != LOCAL_EVIDENCE_SCHEMA:
            errors.append(f"{kind} receipt schema is invalid")
        if receipt.get("kind") != kind:
            errors.append(f"{kind} receipt kind does not match")
        if receipt.get("result") != "passed":
            errors.append(f"{kind} receipt did not pass")
        if receipt.get("subject") != dict(subject):
            errors.append(f"{kind} receipt subject binding does not match")

        verifier = receipt.get("verifier")
        proof = receipt.get("proof")
        if not isinstance(verifier, dict) or set(verifier) != {
            "identity",
            "keyId",
            "keyFingerprintSha256",
        }:
            return errors + [f"{kind} verifier identity is invalid"]
        pinned = (
            self.config["localEvidence"]["trustedVerifiers"].get(
                verifier.get("keyId")
            )
        )
        if not isinstance(pinned, dict):
            return errors + [f"{kind} verifier key is not pinned"]
        if pinned.get("provisioned") is not True:
            errors.append(
                f"{kind} cryptographic acceptance is unproven: "
                "local verifier trust root is not provisioned"
            )
        if (
            verifier.get("identity") != pinned.get("identity")
            or not hmac.compare_digest(
                str(verifier.get("keyFingerprintSha256") or ""),
                pinned["fingerprintSha256"],
            )
        ):
            errors.append(f"{kind} verifier identity or fingerprint does not match")
        allowed_kinds = pinned.get("allowedKinds") or []
        if kind not in allowed_kinds:
            errors.append(f"{kind} is not allowed for this verifier")
        try:
            issued = _parse_utc(receipt.get("issuedAt"), field=f"{kind} issuedAt")
            expires = _parse_utc(receipt.get("expiresAt"), field=f"{kind} expiresAt")
            policy = self.config["localEvidence"]
            if issued > now + timedelta(seconds=policy["maxFutureSkewSeconds"]):
                errors.append(f"{kind} receipt is future-dated")
            if (now - issued).total_seconds() > policy["maxAgeSeconds"]:
                errors.append(f"{kind} receipt is stale")
            if expires <= now or expires <= issued:
                errors.append(f"{kind} receipt is expired")
            if (expires - issued).total_seconds() > policy["maxAgeSeconds"]:
                errors.append(f"{kind} receipt validity window is too long")
        except UpdaterContractError as exc:
            errors.append(str(exc))

        payload = local_receipt_payload(receipt)
        expected_digest = _sha256_bytes(_canonical_bytes(payload))
        if not hmac.compare_digest(
            str(receipt.get("receiptSha256") or ""), expected_digest
        ):
            errors.append(f"{kind} receipt deterministic digest does not match")
        if not isinstance(proof, dict) or set(proof) != {
            "scheme",
            "keyId",
            "value",
        }:
            errors.append(f"{kind} receipt proof is invalid")
        else:
            if (
                proof.get("scheme") != "ed25519-detached"
                or proof.get("keyId") != verifier.get("keyId")
            ):
                errors.append(f"{kind} receipt proof identity does not match")
            try:
                _verify_ed25519(
                    pinned["publicKeyBase64"],
                    proof.get("value"),
                    _canonical_bytes(payload),
                    field=f"{kind} receipt",
                )
            except UpdaterContractError as exc:
                errors.append(str(exc))
        return errors

    def _consume_receipts_once(
        self,
        evidence: Mapping[str, Any],
        *,
        include_delta: bool,
        include_peer: bool,
        update_request_id: str,
        consumed_at: datetime,
    ) -> None:
        receipts = self._selected_receipts(
            evidence,
            include_delta=include_delta,
            include_peer=include_peer,
        )
        digests = [str(receipt["receiptSha256"]) for receipt in receipts]
        if len(digests) != len(set(digests)):
            raise UpdaterContractError(
                "signed local receipts must be unique per update request"
            )

        self.consumed_receipt_ledger.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.consumed_receipt_ledger,
            timeout=10,
            isolation_level=None,
        )
        try:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS consumed_receipts (
                    receipt_sha256 TEXT PRIMARY KEY,
                    update_request_id TEXT NOT NULL,
                    consumed_at TEXT NOT NULL
                )
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            placeholders = ",".join("?" for _ in digests)
            replayed = connection.execute(
                f"SELECT receipt_sha256 FROM consumed_receipts "
                f"WHERE receipt_sha256 IN ({placeholders}) LIMIT 1",
                digests,
            ).fetchone()
            if replayed is not None:
                connection.execute("ROLLBACK")
                raise UpdaterContractError(
                    "signed local receipt was already consumed"
                )
            consumed_text = consumed_at.strftime("%Y-%m-%dT%H:%M:%SZ")
            connection.executemany(
                """
                INSERT INTO consumed_receipts (
                    receipt_sha256,
                    update_request_id,
                    consumed_at
                ) VALUES (?, ?, ?)
                """,
                [
                    (digest, update_request_id, consumed_text)
                    for digest in digests
                ],
            )
            connection.execute("COMMIT")
        except sqlite3.Error as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise UpdaterContractError(
                "consumed receipt ledger transaction failed"
            ) from exc
        finally:
            connection.close()

    @staticmethod
    def _selected_receipts(
        evidence: Mapping[str, Any],
        *,
        include_delta: bool,
        include_peer: bool,
    ) -> list[Mapping[str, Any]]:
        receipts: list[Mapping[str, Any]] = [evidence["artifactReceipt"]]
        receipts.extend(evidence["gates"][gate] for gate in REQUIRED_GATES)
        if isinstance(evidence.get("optInReceipt"), dict):
            receipts.append(evidence["optInReceipt"])
        if include_delta:
            receipts.append(evidence["deltaReceipt"])
        if include_peer:
            receipts.append(evidence["peerReceipt"])
        return receipts

    def _delivery_plan(
        self,
        manifest: Mapping[str, Any],
        *,
        current_version: str,
        delta_eligible: bool,
        peer_eligible: bool,
        optional_fallback_reasons: list[str],
    ) -> dict[str, Any]:
        policy = self.config["delivery"]
        artifact = manifest["artifact"]
        full = {
            "mode": "full",
            "name": artifact["name"],
            "bytes": artifact["bytes"],
            "sha256": artifact["sha256"],
            "reproducibleBuildId": artifact["reproducibleBuildId"],
            "signature": dict(artifact["signature"]),
            "verifyFinalArtifactSha256": artifact["sha256"],
        }
        selected = dict(full)
        fallback_reasons = list(optional_fallback_reasons)

        delta = manifest.get("delta")
        if policy["delta"]["enabled"] and isinstance(delta, dict):
            eligible = (
                delta_eligible
                and delta.get("fromVersion") == current_version
                and SHA256_RE.fullmatch(
                    str(delta.get("fromArtifactSha256") or "")
                )
                is not None
                and SHA256_RE.fullmatch(str(delta.get("sha256") or "")) is not None
                and type(delta.get("bytes")) is int
                and delta["bytes"] > 0
                and delta["bytes"]
                < artifact["bytes"] * policy["delta"]["maxRatio"]
            )
            if eligible:
                selected = {
                    "mode": "delta",
                    "name": delta["name"],
                    "bytes": delta["bytes"],
                    "sha256": delta["sha256"],
                    "signature": dict(delta["signature"]),
                    "fromArtifactSha256": delta["fromArtifactSha256"],
                    "verifyFinalArtifactSha256": artifact["sha256"],
                }
            else:
                if "delta-ineligible-use-full-artifact" not in fallback_reasons:
                    fallback_reasons.append(
                        "delta-ineligible-use-full-artifact"
                    )

        if policy["peerAssisted"]["enabled"] and peer_eligible:
            selected["transport"] = "private-peer-cache"
        else:
            selected["transport"] = "supervised-upstream"
            if "peer-ineligible-use-supervised-upstream" not in fallback_reasons:
                fallback_reasons.append(
                    "peer-ineligible-use-supervised-upstream"
                )
        selected["fallback"] = full
        selected["fallbackReasons"] = fallback_reasons
        return selected


def hash_signed_manifest_payload(manifest: Mapping[str, Any]) -> str:
    """Hash exactly the canonical payload a detached signature must bind."""

    payload = {key: value for key, value in manifest.items() if key != "signature"}
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()
