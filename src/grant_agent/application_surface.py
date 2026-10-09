"""Bounded contracts for optional workspace-built application surfaces.

The contract deliberately stops at validation, truthful status inspection, and
launch planning.  It never builds, installs, launches, or publishes an app.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import re
import stat
import struct
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterable
from urllib.parse import urlparse

from jsonschema import Draft202012Validator

from .capability_contracts import (
    VALID_PERMISSION_CLASSES,
    canonical_hash,
    normalized_strings,
    utc_now,
)
from .capability_runtime import CapabilityPermissionEngine
from .subprocess_utils import hidden_windows_subprocess_kwargs
from .proofs_a_capabilities import (checked_action, check_surface_validation,
    check_surface_target, check_launch_plan, check_authority_receipt,
    check_lifecycle_stream, check_lifecycle_status, check_log_observer)


APPLICATION_SURFACE_SCHEMA_VERSION = "neyvia.application-surface/v1"
APPLICATION_SURFACE_STATUS_SCHEMA = "neyvia.application-surface-status/v1"
APPLICATION_SURFACE_LAUNCH_PLAN_SCHEMA = "neyvia.application-surface-launch-plan/v1"
APPLICATION_SURFACE_OBSERVABILITY_SCHEMA = "neyvia.application-surface-observability/v1"
APPLICATION_SURFACE_CATALOG_SCHEMA = "neyvia.application-surface-catalog/v1"
APPLICATION_SURFACE_APPROVAL_SCHEMA = "neyvia.application-surface-approval/v1"
APPLICATION_SURFACE_WEB_PROOF_SCHEMA = "neyvia.application-surface-web-proof/v1"
APPLICATION_SURFACE_DESKTOP_PROOF_SCHEMA = "neyvia.application-surface-desktop-proof/v1"
APPLICATION_SURFACE_LIFECYCLE_SCHEMA = "neyvia.application-surface-lifecycle/v1"
EXTERNAL_RECEIPT_ENVELOPE_SCHEMA = "neyvia.external-receipt-envelope/v1"

SURFACE_KINDS = frozenset({"web", "desktop"})
TARGET_PLATFORMS = frozenset({"web", "windows", "macos", "linux", "android", "ios"})
MOBILE_PLATFORMS = frozenset({"android", "ios"})
BUILD_STATUSES = frozenset({"available", "unavailable", "not_required"})
BASELINE_PERMISSIONS = {
    "desktop": ("process.execute",),
    "web": ("network.read", "device.control"),
}
LIFECYCLE_STATES = (
    "declared",
    "ready",
    "launching",
    "running",
    "stopped",
    "failed",
    "unavailable",
)
LIFECYCLE_TRANSITIONS = frozenset(
    {
        ("declared", "ready"),
        ("ready", "launching"),
        ("launching", "running"),
        ("launching", "failed"),
        ("running", "stopped"),
        ("running", "failed"),
        ("stopped", "launching"),
        ("failed", "launching"),
    }
)
MAX_LOG_FILE_BYTES = 8 * 1024 * 1024
MAX_LOG_READ_BYTES = 64 * 1024
LOG_BOUNDARY_OVERLAP_BYTES = 4096
MAX_LOG_TOTAL_BYTES = 256 * 1024
MAX_PROOF_FILE_BYTES = 16 * 1024 * 1024
MAX_PROOF_TOTAL_BYTES = 64 * 1024 * 1024
MAX_STRUCTURED_RECEIPT_BYTES = 256 * 1024
MAX_ARTIFACT_HASH_BYTES = 512 * 1024 * 1024

SECRET_PATTERNS = (
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)",
        re.I | re.S,
    ),
    re.compile(r"\b(?:bearer|basic)\s+\S+", re.I),
    re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{16,}|xox[baprs]-[A-Za-z0-9-]{16,}|AIza[\w-]{20,})"
    ),
    re.compile(
        r"(?i)\b(?:api[_-]?key|authorization|credential|password|private[_-]?key|secret|token)\b\s*[=:]\s*[^\s,;]+"
    ),
    re.compile(
        r'(?i)"(?:api[_-]?key|authorization|credential|password|private[_-]?key|secret|token)"\s*:\s*"[^"]*"'
    ),
    re.compile(r"(?m)^[A-Za-z0-9+/]{40,}={0,2}\s*$"),
)


def _parse_iso_timestamp(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _windows_final_path_from_fd(descriptor: int) -> Path | None:
    """Return the kernel-resolved path for a Windows file descriptor."""

    if os.name != "nt":
        return None
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        handle = msvcrt.get_osfhandle(descriptor)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_final_path = kernel32.GetFinalPathNameByHandleW
        get_final_path.argtypes = [
            wintypes.HANDLE,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        get_final_path.restype = wintypes.DWORD
        required = get_final_path(handle, None, 0, 0)
        if not required:
            return None
        buffer = ctypes.create_unicode_buffer(required + 1)
        written = get_final_path(handle, buffer, len(buffer), 0)
        if not written or written >= len(buffer):
            return None
        raw = buffer.value
        if raw.startswith("\\\\?\\UNC\\"):
            raw = "\\\\" + raw[8:]
        elif raw.startswith("\\\\?\\"):
            raw = raw[4:]
        return Path(raw).resolve()
    except Exception:
        return None


class ExternalReceiptAuthority:
    """Verify, but never mint, HMAC receipts from an external ledger."""

    def __init__(self, ledger_root: str | Path, verification_key: bytes) -> None:
        self.ledger_root = Path(ledger_root).expanduser().resolve()
        self.verification_key = bytes(verification_key)
        if len(self.verification_key) < 32:
            raise ValueError("External receipt verification key must be at least 32 bytes")

    @staticmethod
    def _signature_material(envelope: dict[str, Any]) -> bytes:
        unsigned = {key: value for key, value in envelope.items() if key != "signature"}
        return json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def verify_receipt(
        self,
        receipt_id: str,
        *,
        expected_kind: str,
    ) -> dict[str, Any]:
        clean_id = str(receipt_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", clean_id):
            return self._invalid(clean_id, "invalid external receipt id")
        path = self.ledger_root / "receipts" / f"{clean_id}.json"
        result = self._verify_path(path, expected_kind=expected_kind)
        if result.get("verified"):
            consumed = self.ledger_root / "consumed" / f"{clean_id}.json"
            if consumed.exists():
                return self._invalid(clean_id, "external receipt has already been consumed")
        return result

    @checked_action(check_lifecycle_stream)
    def verify_lifecycle_stream(self, stream_id: str) -> dict[str, Any]:
        clean_id = str(stream_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", clean_id):
            return self._invalid(clean_id, "invalid lifecycle stream id")
        directory = self.ledger_root / "lifecycle" / clean_id
        try:
            directory.relative_to(self.ledger_root)
        except ValueError:
            return self._invalid(clean_id, "lifecycle stream escapes authority ledger")
        if not directory.is_dir() or directory.is_symlink():
            return self._invalid(clean_id, "trusted lifecycle stream is unavailable")
        try:
            self._assert_no_reparse_components(directory)
        except OSError as exc:
            return self._invalid(clean_id, str(exc))
        verified_rows: list[dict[str, Any]] = []
        for path in sorted(directory.glob("*.json")):
            row = self._verify_path(path, expected_kind="lifecycle")
            if not row.get("verified"):
                return row
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            if payload.get("streamId") != clean_id:
                return self._invalid(clean_id, "lifecycle stream binding mismatch")
            verified_rows.append(row)
        if not verified_rows:
            return self._invalid(clean_id, "trusted lifecycle stream has no receipts")
        if any(
            not isinstance((row.get("payload") or {}).get("sequence"), int)
            or isinstance((row.get("payload") or {}).get("sequence"), bool)
            for row in verified_rows
        ):
            return self._invalid(clean_id, "lifecycle sequence must be an integer")
        verified_rows.sort(key=lambda item: item["payload"]["sequence"])
        previous_hash = ""
        previous_state = ""
        run_binding: dict[str, object] | None = None
        expected_sequence = 1
        for row in verified_rows:
            payload = row["payload"]
            if payload.get("sequence") != expected_sequence:
                return self._invalid(clean_id, "lifecycle sequence is not monotonic")
            if str(payload.get("previousReceiptHash") or "") != previous_hash:
                return self._invalid(clean_id, "lifecycle previous-receipt hash mismatch")
            state = str(payload.get("state") or "").strip().lower()
            declared_previous = str(payload.get("previousState") or "").strip().lower()
            if expected_sequence == 1:
                if declared_previous != "declared":
                    return self._invalid(
                        clean_id,
                        "first lifecycle receipt must transition from declared",
                    )
            elif declared_previous != previous_state:
                return self._invalid(
                    clean_id,
                    "lifecycle previous-state chain mismatch",
                )
            if (declared_previous, state) not in LIFECYCLE_TRANSITIONS:
                return self._invalid(clean_id, "lifecycle state transition is invalid")
            current_binding = {
                field: payload.get(field)
                for field in (
                    "runId",
                    "manifestHash",
                    "planHash",
                    "targetId",
                    "artifactSha256",
                )
            }
            if not all(
                isinstance(value, str) and bool(value)
                for field, value in current_binding.items()
                if field != "artifactSha256"
            ) or not isinstance(current_binding["artifactSha256"], str):
                return self._invalid(
                    clean_id,
                    "lifecycle run binding is incomplete",
                )
            if run_binding is None:
                run_binding = current_binding
            elif current_binding != run_binding:
                return self._invalid(
                    clean_id,
                    "lifecycle run binding changed inside the stream",
                )
            previous_hash = str(row.get("receiptHash") or "")
            previous_state = state
            expected_sequence += 1
        latest = dict(verified_rows[-1])
        latest["chainLength"] = len(verified_rows)
        latest["streamId"] = clean_id
        return latest

    @checked_action(check_authority_receipt)
    def _verify_path(
        self,
        path: Path,
        *,
        expected_kind: str,
    ) -> dict[str, Any]:
        try:
            current = self.ledger_root
            relative = path.relative_to(self.ledger_root)
            for part in relative.parts[:-1]:
                current = current / part
                component = os.lstat(current)
                if stat.S_ISLNK(component.st_mode) or (
                    getattr(component, "st_file_attributes", 0) & 0x400
                ):
                    raise OSError("authority ledger path crosses a link or reparse point")
            parent = path.parent.resolve()
            parent.relative_to(self.ledger_root)
            self._assert_no_reparse_components(path)
            before = os.lstat(path)
            if stat.S_ISLNK(before.st_mode) or (
                getattr(before, "st_file_attributes", 0) & 0x400
            ):
                raise OSError("authority receipt cannot be a link or reparse point")
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            try:
                opened = os.fstat(descriptor)
                if not stat.S_ISREG(opened.st_mode):
                    raise OSError("authority receipt is not a regular file")
                if (
                    getattr(before, "st_ino", 0)
                    and getattr(opened, "st_ino", 0)
                    and (
                        before.st_ino != opened.st_ino
                        or before.st_dev != opened.st_dev
                    )
                ):
                    raise OSError(
                        "authority receipt changed before a stable handle was acquired"
                    )
                if opened.st_size > MAX_STRUCTURED_RECEIPT_BYTES:
                    raise OSError("authority receipt exceeds size limit")
                self._verify_windows_handle_path(descriptor, path)
                chunks: list[bytes] = []
                remaining = opened.st_size + 1
                while remaining > 0:
                    chunk = os.read(descriptor, min(65536, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                content = b"".join(chunks)
                after = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            if (
                len(content) > MAX_STRUCTURED_RECEIPT_BYTES
                or opened.st_size != after.st_size
                or opened.st_mtime_ns != after.st_mtime_ns
            ):
                raise OSError("authority receipt changed during verification")
            envelope = json.loads(content.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            return self._invalid(path.stem, str(exc) or "authority receipt is unreadable")
        if not isinstance(envelope, dict):
            return self._invalid(path.stem, "authority receipt must be an object")
        signature = str(envelope.get("signature") or "").lower()
        expected_signature = hmac.new(
            self.verification_key,
            self._signature_material(envelope),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            return self._invalid(path.stem, "authority receipt signature is invalid")
        checks = {
            "schema": EXTERNAL_RECEIPT_ENVELOPE_SCHEMA,
            "receiptId": path.stem,
            "kind": expected_kind,
            "singleUse": True,
        }
        errors = [
            f"authority receipt {field} binding mismatch"
            for field, expected in checks.items()
            if envelope.get(field) != expected
        ]
        issued = _parse_iso_timestamp(envelope.get("issuedAt"))
        expires = _parse_iso_timestamp(envelope.get("expiresAt"))
        now = datetime.now(timezone.utc)
        if issued is None or issued > now + timedelta(seconds=30):
            errors.append("authority receipt issuedAt is invalid")
        if expires is None or expires <= now:
            errors.append("authority receipt is expired")
        if issued is not None and expires is not None:
            if expires <= issued or (expires - issued).total_seconds() > 86400:
                errors.append("authority receipt validity window is invalid")
        if not str(envelope.get("nonce") or "").strip():
            errors.append("authority receipt nonce is required")
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            errors.append("authority receipt payload must be an object")
            payload = {}
        if errors:
            return self._invalid(path.stem, errors[0], errors=errors)
        return {
            "verified": True,
            "receiptId": path.stem,
            "receiptHash": hashlib.sha256(content).hexdigest(),
            "payload": payload,
            "issuedAt": str(envelope.get("issuedAt") or ""),
            "expiresAt": str(envelope.get("expiresAt") or ""),
            "singleUse": True,
            "errors": [],
        }

    def _assert_no_reparse_components(self, path: Path) -> None:
        """Reject links/junctions from the authority root to the selected entry."""

        resolved = path.resolve(strict=False)
        resolved.relative_to(self.ledger_root)
        try:
            relative = path.relative_to(self.ledger_root)
        except ValueError as exc:
            raise OSError("authority path escapes ledger root") from exc
        current = self.ledger_root
        for part in relative.parts:
            current = current / part
            try:
                info = os.lstat(current)
            except FileNotFoundError:
                if current == path:
                    raise
                continue
            if stat.S_ISLNK(info.st_mode) or (
                getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise OSError("authority paths cannot contain links or reparse points")

    def _verify_windows_handle_path(self, descriptor: int, expected_path: Path) -> None:
        if os.name != "nt":
            return
        final_path = _windows_final_path_from_fd(descriptor)
        if final_path is None:
            raise OSError("Windows authority handle path could not be verified")
        expected = Path(expected_path).resolve()
        if os.path.normcase(str(final_path)) != os.path.normcase(str(expected)):
            raise OSError("Windows authority handle resolved to an unexpected path")

    @staticmethod
    def _invalid(
        receipt_id: str,
        reason: str,
        *,
        errors: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "verified": False,
            "receiptId": receipt_id,
            "receiptHash": "",
            "payload": {},
            "singleUse": True,
            "reason": reason,
            "errors": list(errors or [reason]),
        }


def application_surface_schema() -> dict[str, Any]:
    """Return the JSON Schema used for the optional manifest block."""

    permission_list = {
        "type": "array",
        "items": {"type": "string", "enum": sorted(VALID_PERMISSION_CLASSES)},
        "uniqueItems": True,
    }
    relative_path = {
        "type": "string",
        "minLength": 1,
        "maxLength": 1024,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://neyvia.local/schemas/application-surface-v1.json",
        "title": "N-E-Y-V-I-A optional application surface",
        "type": "object",
        "required": [
            "schema_version",
            "surface_id",
            "title",
            "description",
            "control_modes",
            "permissions",
            "targets",
        ],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": APPLICATION_SURFACE_SCHEMA_VERSION},
            "surface_id": {
                "type": "string",
                "pattern": "^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
                "maxLength": 96,
            },
            "title": {"type": "string", "minLength": 1, "maxLength": 120},
            "description": {"type": "string", "minLength": 1, "maxLength": 500},
            "control_modes": {
                "type": "array",
                "items": {"type": "string", "enum": ["agent", "user"]},
                "minItems": 1,
                "uniqueItems": True,
            },
            "permissions": {
                "type": "object",
                "required": ["inspect", "launch", "control"],
                "additionalProperties": False,
                "properties": {
                    "inspect": permission_list,
                    "launch": permission_list,
                    "control": permission_list,
                },
            },
            "targets": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": {
                    "type": "object",
                    "required": [
                        "target_id",
                        "kind",
                        "platform",
                        "build",
                        "required_permissions",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "target_id": {
                            "type": "string",
                            "pattern": "^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
                            "maxLength": 96,
                        },
                        "kind": {"type": "string", "enum": sorted(SURFACE_KINDS)},
                        "platform": {
                            "type": "string",
                            "enum": sorted(TARGET_PLATFORMS),
                        },
                        "build": {
                            "type": "object",
                            "required": ["status"],
                            "additionalProperties": False,
                            "properties": {
                                "status": {
                                    "type": "string",
                                    "enum": sorted(BUILD_STATUSES),
                                },
                                "artifact": relative_path,
                                "sha256": {
                                    "type": "string",
                                    "pattern": "^[0-9a-f]{64}$",
                                },
                                "size_bytes": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": MAX_ARTIFACT_HASH_BYTES,
                                },
                                "media_type": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 120,
                                },
                                "architecture": {
                                    "type": "string",
                                    "enum": ["x86_64", "arm64", "x86"],
                                },
                                "reason": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 500,
                                },
                                "proof_paths": {
                                    "type": "array",
                                    "items": relative_path,
                                    "maxItems": 20,
                                    "uniqueItems": True,
                                },
                                "evidence": {
                                    "type": "object",
                                    "required": ["receipt_id"],
                                    "additionalProperties": False,
                                    "properties": {
                                        "receipt_id": {
                                            "type": "string",
                                            "pattern": "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$",
                                        },
                                        "max_age_seconds": {
                                            "type": "integer",
                                            "minimum": 1,
                                            "maximum": 604800,
                                        },
                                    },
                                },
                            },
                        },
                        "launch": {
                            "type": "object",
                            "required": ["kind"],
                            "additionalProperties": False,
                            "properties": {
                                "kind": {
                                    "type": "string",
                                    "enum": ["url", "artifact"],
                                },
                                "url": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 2048,
                                },
                                "artifact": relative_path,
                                "arguments": {
                                    "type": "array",
                                    "items": {
                                        "type": "string",
                                        "maxLength": 1024,
                                    },
                                    "maxItems": 64,
                                },
                                "working_directory": relative_path,
                            },
                        },
                        "required_permissions": permission_list,
                        "readiness": {
                            "type": "object",
                            "required": ["receipt_id"],
                            "additionalProperties": False,
                            "properties": {
                                "receipt_id": {
                                    "type": "string",
                                    "pattern": "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$",
                                },
                                "max_age_seconds": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 604800,
                                },
                            },
                        },
                    },
                },
            },
            "lifecycle": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "status_file": relative_path,
                    "stream_id": {
                        "type": "string",
                        "pattern": "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$",
                    },
                    "max_age_seconds": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 86400,
                    },
                    "states": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": list(LIFECYCLE_STATES),
                        },
                        "uniqueItems": True,
                    },
                },
            },
            "observability": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "log_paths": {
                        "type": "array",
                        "items": relative_path,
                        "maxItems": 20,
                        "uniqueItems": True,
                    },
                    "proof_paths": {
                        "type": "array",
                        "items": relative_path,
                        "maxItems": 20,
                        "uniqueItems": True,
                    },
                },
            },
        },
    }


def _surface_block(payload: object) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if "application_surface" in payload:
        value = payload.get("application_surface")
        return dict(value) if isinstance(value, dict) else None
    if payload.get("schema_version") == APPLICATION_SURFACE_SCHEMA_VERSION or any(
        key in payload
        for key in (
            "surface_id",
            "control_modes",
            "targets",
            "lifecycle",
            "observability",
        )
    ):
        return dict(payload)
    return None


def _json_path(parts: Iterable[object]) -> str:
    values = [str(item) for item in parts]
    return ".".join(values) if values else "$"


def _is_safe_relative_path(value: object) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    candidate = Path(raw)
    if candidate.is_absolute():
        return False
    return ".." not in candidate.parts


def _safe_http_url(value: object) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


@checked_action(check_surface_validation)
def validate_application_surface_manifest(payload: object) -> dict[str, Any]:
    """Validate an optional application surface without touching the workspace."""

    surface = _surface_block(payload)
    if surface is None:
        declared = isinstance(payload, dict) and "application_surface" in payload
        return {
            "schema": APPLICATION_SURFACE_SCHEMA_VERSION,
            "valid": not declared,
            "declared": False,
            "errors": (
                ["application_surface must be an object when declared"]
                if declared
                else []
            ),
            "warnings": [],
            "manifestHash": "",
        }

    validator = Draft202012Validator(application_surface_schema())
    errors = [
        f"{_json_path(item.absolute_path)}: {item.message}"
        for item in sorted(
            validator.iter_errors(surface),
            key=lambda item: _json_path(item.absolute_path),
        )
    ]
    warnings: list[str] = []
    targets = surface.get("targets")
    seen_target_ids: set[str] = set()
    if isinstance(targets, list):
        for index, value in enumerate(targets):
            if not isinstance(value, dict):
                continue
            target_id = str(value.get("target_id") or "")
            if target_id in seen_target_ids:
                errors.append(f"targets.{index}.target_id: duplicate target_id {target_id!r}")
            seen_target_ids.add(target_id)
            kind = str(value.get("kind") or "")
            platform = str(value.get("platform") or "")
            build = value.get("build") if isinstance(value.get("build"), dict) else {}
            build_status = str(build.get("status") or "")
            launch = value.get("launch") if isinstance(value.get("launch"), dict) else {}
            prefix = f"targets.{index}"

            if platform == "web" and kind != "web":
                errors.append(f"{prefix}: platform 'web' requires kind 'web'")
            if platform != "web" and kind == "web":
                errors.append(f"{prefix}: kind 'web' requires platform 'web'")
            if kind == "web" and build_status != "not_required":
                errors.append(f"{prefix}.build.status: web targets must use 'not_required'")
            if kind == "desktop" and build_status == "not_required":
                errors.append(f"{prefix}.build.status: desktop targets require an explicit build status")
            if build_status == "unavailable" and not str(build.get("reason") or "").strip():
                errors.append(f"{prefix}.build.reason: unavailable targets require a reason")
            if build_status == "available" and kind == "desktop":
                artifact = build.get("artifact")
                if not _is_safe_relative_path(artifact):
                    errors.append(f"{prefix}.build.artifact: a workspace-relative artifact is required")
                for evidence_field in (
                    "sha256",
                    "size_bytes",
                    "media_type",
                    "architecture",
                    "evidence",
                ):
                    if not build.get(evidence_field):
                        errors.append(
                            f"{prefix}.build.{evidence_field}: required for an available desktop target"
                        )
            if platform in MOBILE_PLATFORMS and build_status != "unavailable":
                errors.append(
                    f"{prefix}.build.status: {platform} must remain unavailable until separately proven"
                )
            if platform in MOBILE_PLATFORMS and build_status == "unavailable":
                warnings.append(
                    f"{target_id or prefix} is declared unavailable; no {platform} build proof is claimed"
                )
            if build_status in {"available", "not_required"} and not launch:
                errors.append(f"{prefix}.launch: launch metadata is required for a launchable target")
            if launch:
                launch_kind = str(launch.get("kind") or "")
                if kind == "web":
                    if launch_kind != "url" or not _safe_http_url(launch.get("url")):
                        errors.append(f"{prefix}.launch: web targets require an http(s) URL")
                elif launch_kind != "artifact":
                    errors.append(f"{prefix}.launch.kind: desktop targets require 'artifact'")
                else:
                    launch_artifact = launch.get("artifact")
                    build_artifact = build.get("artifact")
                    if not _is_safe_relative_path(launch_artifact):
                        errors.append(f"{prefix}.launch.artifact: must be workspace-relative")
                    elif build_status == "available" and launch_artifact != build_artifact:
                        errors.append(
                            f"{prefix}.launch.artifact: must match build.artifact"
                        )
                    working_directory = launch.get("working_directory")
                    if working_directory and not _is_safe_relative_path(working_directory):
                        errors.append(
                            f"{prefix}.launch.working_directory: must stay inside the workspace"
                        )
            for proof_index, path in enumerate(build.get("proof_paths") or []):
                if not _is_safe_relative_path(path):
                    errors.append(
                        f"{prefix}.build.proof_paths.{proof_index}: must stay inside the workspace"
                    )

    lifecycle = surface.get("lifecycle")
    if isinstance(lifecycle, dict) and lifecycle.get("status_file"):
        if not _is_safe_relative_path(lifecycle["status_file"]):
            errors.append("lifecycle.status_file: must stay inside the workspace")
    observability = surface.get("observability")
    if isinstance(observability, dict):
        for field_name in ("log_paths", "proof_paths"):
            for index, path in enumerate(observability.get(field_name) or []):
                if not _is_safe_relative_path(path):
                    errors.append(
                        f"observability.{field_name}.{index}: must stay inside the workspace"
                    )

    return {
        "schema": APPLICATION_SURFACE_SCHEMA_VERSION,
        "valid": not errors,
        "declared": True,
        "errors": errors,
        "warnings": warnings,
        "manifestHash": canonical_hash(
            {
                "appId": (
                    str(
                        payload.get("app_id")
                        or payload.get("appId")
                        or ""
                    )
                    if isinstance(payload, dict)
                    and "application_surface" in payload
                    else ""
                ),
                "applicationSurface": surface,
            }
        ),
    }


class ApplicationSurfaceService:
    """Inspect optional app surfaces and create non-executing launch plans."""

    def __init__(
        self,
        root: str | Path,
        *,
        receipt_authority: ExternalReceiptAuthority | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.permission_engine = CapabilityPermissionEngine()
        self.receipt_authority = receipt_authority
        if self.receipt_authority is not None:
            try:
                self.receipt_authority.ledger_root.relative_to(self.root)
            except ValueError:
                pass
            else:
                raise ValueError(
                    "External receipt authority ledger must be outside the editable workspace"
                )
        self.host_platform = (
            "windows"
            if sys.platform == "win32"
            else "macos"
            if sys.platform == "darwin"
            else "linux"
            if sys.platform.startswith("linux")
            else "unknown"
        )
        machine = platform.machine().strip().lower()
        self.host_architecture = (
            "x86_64"
            if machine in {"amd64", "x86_64"}
            else "arm64"
            if machine in {"arm64", "aarch64"}
            else "x86"
            if machine in {"x86", "i386", "i686"}
            else machine or "unknown"
        )

    def validate(self, payload: object) -> dict[str, Any]:
        return validate_application_surface_manifest(payload)

    def catalog(self) -> dict[str, Any]:
        manifests = self._load_manifests()
        rows: list[dict[str, Any]] = []
        for manifest in manifests:
            if "application_surface" not in manifest:
                continue
            validation = self.validate(manifest)
            row = {
                "appId": str(manifest.get("app_id") or manifest.get("appId") or ""),
                "appName": str(manifest.get("name") or ""),
                "valid": validation["valid"],
                "errors": validation["errors"],
                "manifestHash": validation["manifestHash"],
            }
            surface = _surface_block(manifest)
            if surface:
                row.update(
                    {
                        "surfaceId": surface.get("surface_id"),
                        "title": surface.get("title"),
                        "description": surface.get("description"),
                        "controlModes": list(surface.get("control_modes") or []),
                        "targets": [
                            self._target_status(
                                surface,
                                target,
                                manifest_hash=validation["manifestHash"],
                            )
                            for target in (surface.get("targets") or [])
                            if isinstance(target, dict)
                        ]
                        if validation["valid"]
                        else [],
                    }
                )
            rows.append(row)
        return {
            "schema": APPLICATION_SURFACE_CATALOG_SCHEMA,
            "generatedAt": utc_now(),
            "surfaces": rows,
            "summary": {
                "declared": len(rows),
                "valid": sum(1 for row in rows if row["valid"]),
                "launchReadyTargets": sum(
                    1
                    for row in rows
                    for target in row.get("targets") or []
                    if target.get("available")
                ),
            },
        }

    def status(
        self,
        payload: object,
        *,
        target_id: str = "",
    ) -> dict[str, Any]:
        validation = self.validate(payload)
        surface = _surface_block(payload)
        if not validation["declared"]:
            return {
                "schema": APPLICATION_SURFACE_STATUS_SCHEMA,
                "generatedAt": utc_now(),
                "declared": False,
                "valid": validation["valid"],
                "status": "undeclared",
                "targets": [],
                "errors": validation["errors"],
            }
        if not validation["valid"] or surface is None:
            return {
                "schema": APPLICATION_SURFACE_STATUS_SCHEMA,
                "generatedAt": utc_now(),
                "declared": True,
                "valid": False,
                "status": "invalid",
                "targets": [],
                "errors": validation["errors"],
            }

        selected = [
            item
            for item in surface.get("targets") or []
            if isinstance(item, dict)
            and (not target_id or str(item.get("target_id") or "") == target_id)
        ]
        targets = [
            self._target_status(
                surface,
                item,
                manifest_hash=validation["manifestHash"],
            )
            for item in selected
        ]
        errors: list[str] = []
        if target_id and not selected:
            errors.append(f"Unknown application surface target: {target_id}")
        lifecycle = self._lifecycle_status(
            surface,
            manifest_hash=validation["manifestHash"],
            targets=targets,
        )
        if errors:
            status = "unknown_target"
        elif not targets:
            status = "unavailable"
        elif any(item["status"] == "ready" for item in targets):
            status = "ready"
        elif any(item["status"] == "present" for item in targets):
            status = "present"
        elif any(item["status"] == "declared" for item in targets):
            status = "declared"
        else:
            status = "unavailable"
        if (
            any(item["status"] == "ready" for item in targets)
            and lifecycle.get("verified")
            and lifecycle.get("state") in {"launching", "running", "stopped", "failed"}
        ):
            status = str(lifecycle["state"])
        return {
            "schema": APPLICATION_SURFACE_STATUS_SCHEMA,
            "generatedAt": utc_now(),
            "declared": True,
            "valid": True,
            "surfaceId": surface["surface_id"],
            "status": status,
            "lifecycle": lifecycle,
            "targets": targets,
            "errors": errors,
            "manifestHash": validation["manifestHash"],
        }

    @checked_action(check_launch_plan)
    def plan_launch(
        self,
        payload: object,
        *,
        target_id: str,
        permission_mode: str = "workspace_safe",
        approval_id: str = "",
    ) -> dict[str, Any]:
        surface = _surface_block(payload)
        status = self.status(payload, target_id=target_id)
        target_status = (status.get("targets") or [{}])[0]
        target = next(
            (
                item
                for item in (surface or {}).get("targets") or []
                if isinstance(item, dict)
                and str(item.get("target_id") or "") == target_id
            ),
            {},
        )
        permissions = self._effective_permissions(surface or {}, target)
        plan_hash = str(target_status.get("planHash") or "")
        approval = self._approval_receipt(
            approval_id,
            plan_hash=plan_hash,
            manifest_hash=str(status.get("manifestHash") or ""),
            target_id=target_id,
            permissions=permissions,
        )
        decisions = self.permission_engine.decide(
            permissions,
            mode=permission_mode,
            approved_permissions=(
                permissions if approval.get("valid") else []
            ),
            workspace_scoped=True,
        )
        binding = self.permission_engine.summarize(decisions)
        blockers = list(status.get("errors") or [])
        if not target_status.get("available"):
            blockers.extend(target_status.get("blockers") or ["target_unavailable"])
        if binding["denied"]:
            blockers.append("permission_denied")
            plan_status = "blocked"
        elif target_status.get("status") != "ready":
            plan_status = "unavailable"
        elif not approval.get("valid"):
            blockers.append(
                str(approval.get("reason") or "bound_approval_receipt_required")
            )
            plan_status = "approval_required"
        else:
            plan_status = "ready"
        return {
            "schema": APPLICATION_SURFACE_LAUNCH_PLAN_SCHEMA,
            "generatedAt": utc_now(),
            "surfaceId": (surface or {}).get("surface_id", ""),
            "targetId": target_id,
            "manifestHash": str(status.get("manifestHash") or ""),
            "status": plan_status,
            "blockers": list(dict.fromkeys(str(item) for item in blockers if item)),
            "permissionBinding": binding,
            "approval": approval,
            "launch": dict(target.get("launch") or {}),
            "target": target_status,
            "planHash": plan_hash,
            "steps": [
                "Validate the application surface manifest and selected target.",
                "Resolve declared build availability against current workspace evidence.",
                "Bind launch permissions to the selected operator permission mode.",
                "Hand the launch descriptor to an approved user or runtime launcher.",
                "Read lifecycle, logs, and proof hooks before claiming the surface is running.",
            ],
            "executionPolicy": {
                "executes": False,
                "builds": False,
                "installs": False,
                "publishes": False,
                "reason": "This SDK operation creates a bounded launch plan only.",
            },
        }

    def observe(
        self,
        payload: object,
        *,
        max_log_lines: int = 80,
        max_proof_files: int = 20,
    ) -> dict[str, Any]:
        validation = self.validate(payload)
        surface = _surface_block(payload)
        if not validation["valid"] or surface is None:
            return {
                "schema": APPLICATION_SURFACE_OBSERVABILITY_SCHEMA,
                "generatedAt": utc_now(),
                "status": "invalid" if validation["declared"] else "undeclared",
                "logs": [],
                "proof": [],
                "errors": validation["errors"],
            }
        observability = dict(surface.get("observability") or {})
        log_paths = list(observability.get("log_paths") or [])
        proof_paths = list(observability.get("proof_paths") or [])
        for target in surface.get("targets") or []:
            if isinstance(target, dict):
                build = target.get("build")
                if isinstance(build, dict):
                    proof_paths.extend(build.get("proof_paths") or [])
        logs: list[dict[str, Any]] = []
        log_budget = MAX_LOG_TOTAL_BYTES
        for path in log_paths[:20]:
            row = self._read_log(
                path,
                max_lines=max_log_lines,
                remaining_bytes=log_budget,
            )
            logs.append(row)
            log_budget -= int(row.get("bytesRead") or 0)
        proof: list[dict[str, Any]] = []
        proof_budget = MAX_PROOF_TOTAL_BYTES
        for path in list(dict.fromkeys(proof_paths))[
            : max(1, min(max_proof_files, 20))
        ]:
            row = self._proof_metadata(path, remaining_bytes=proof_budget)
            proof.append(row)
            proof_budget -= int(row.get("bytesRead") or 0)
        return {
            "schema": APPLICATION_SURFACE_OBSERVABILITY_SCHEMA,
            "generatedAt": utc_now(),
            "status": "observed",
            "surfaceId": surface["surface_id"],
            "logs": logs,
            "proof": proof,
            "bounds": {
                "maxLogLinesPerFile": max(1, min(int(max_log_lines), 200)),
                "maxLogBytesPerFile": 65536,
                "maxLogSourceBytesPerFile": MAX_LOG_FILE_BYTES,
                "maxLogBytesTotal": MAX_LOG_TOTAL_BYTES,
                "maxProofFiles": max(1, min(int(max_proof_files), 20)),
                "maxProofBytesPerFile": MAX_PROOF_FILE_BYTES,
                "maxProofBytesTotal": MAX_PROOF_TOTAL_BYTES,
            },
            "redaction": {
                "applied": True,
                "filesWithRedactions": sum(
                    1 for item in logs if item.get("redacted")
                ),
                "replacement": "[REDACTED]",
            },
            "errors": [],
        }

    def _load_manifests(self) -> list[dict[str, Any]]:
        path = self.root / "config" / "connected_apps.json"
        if not path.is_file():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [dict(item) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    @checked_action(check_surface_target)
    def _target_status(
        self,
        surface: dict[str, Any],
        target: dict[str, Any],
        *,
        manifest_hash: str,
    ) -> dict[str, Any]:
        build = dict(target.get("build") or {})
        platform = str(target.get("platform") or "")
        kind = str(target.get("kind") or "")
        build_status = str(build.get("status") or "")
        blockers: list[str] = []
        artifact_status: dict[str, Any] = {}
        readiness_evidence: dict[str, Any] = {}
        status = "unavailable"
        if platform in MOBILE_PLATFORMS:
            blockers.append(
                str(build.get("reason") or f"{platform} target has no verified build")
            )
        elif build_status == "unavailable":
            blockers.append(str(build.get("reason") or "build_target_unavailable"))
        elif kind == "web":
            readiness_evidence = self._web_readiness_evidence(target)
            if readiness_evidence.get("verified"):
                status = "ready"
            else:
                status = "declared"
                blockers.extend(
                    readiness_evidence.get("errors")
                    or ["fresh bound web readiness proof required"]
                )
        elif kind == "desktop":
            if platform != self.host_platform:
                blockers.append(
                    f"{platform} target is not launchable on the current {self.host_platform} host"
                )
                status = "unavailable"
            else:
                artifact_status = self._desktop_artifact_evidence(target)
                if not artifact_status.get("present"):
                    status = "unavailable"
                elif artifact_status.get("verified"):
                    status = "ready"
                else:
                    status = "present"
                blockers.extend(artifact_status.get("errors") or [])
        permissions = self._effective_permissions(surface, target)
        row = {
            "targetId": str(target.get("target_id") or ""),
            "kind": kind,
            "platform": platform,
            "declaredBuildStatus": build_status,
            "available": status == "ready",
            "status": status,
            "blockers": blockers,
            "artifact": artifact_status,
            "readinessEvidence": readiness_evidence,
            "launchKind": str((target.get("launch") or {}).get("kind") or ""),
            "baselinePermissions": list(BASELINE_PERMISSIONS.get(kind, ())),
            "effectivePermissions": permissions,
        }
        row["planHash"] = self._plan_hash(
            surface,
            target,
            row,
            manifest_hash=manifest_hash,
            permissions=permissions,
        )
        return row

    def _effective_permissions(
        self,
        surface: dict[str, Any],
        target: dict[str, Any],
    ) -> list[str]:
        kind = str(target.get("kind") or "")
        return sorted(
            {
                *(
                    str(item).strip().lower()
                    for item in ((surface.get("permissions") or {}).get("launch") or [])
                    if str(item).strip()
                ),
                *(
                    str(item).strip().lower()
                    for item in (target.get("required_permissions") or [])
                    if str(item).strip()
                ),
                *BASELINE_PERMISSIONS.get(kind, ()),
            }
        )

    def _plan_hash(
        self,
        surface: dict[str, Any],
        target: dict[str, Any],
        target_status: dict[str, Any],
        *,
        manifest_hash: str,
        permissions: list[str],
    ) -> str:
        artifact = dict(target_status.get("artifact") or {})
        readiness = dict(target_status.get("readinessEvidence") or {})
        material = {
            "schema": APPLICATION_SURFACE_LAUNCH_PLAN_SCHEMA,
            "manifestHash": manifest_hash,
            "surfaceId": str(surface.get("surface_id") or ""),
            "targetId": str(target.get("target_id") or ""),
            "launch": dict(target.get("launch") or {}),
            "effectivePermissions": list(permissions),
            "targetEvidence": {
                "status": target_status.get("status"),
                "declaredBuildStatus": target_status.get("declaredBuildStatus"),
                "artifact": {
                    key: artifact.get(key)
                    for key in (
                        "path",
                        "sha256",
                        "sizeBytes",
                        "mediaType",
                        "architecture",
                        "executable",
                        "signatureVerified",
                        "buildReceiptId",
                        "buildReceiptHash",
                    )
                },
                "readiness": {
                    key: readiness.get(key)
                    for key in (
                        "verified",
                        "receiptId",
                        "receiptHash",
                        "url",
                        "verifiedAt",
                    )
                },
            },
        }
        return canonical_hash(material)

    def _desktop_artifact_evidence(
        self,
        target: dict[str, Any],
    ) -> dict[str, Any]:
        target_id = str(target.get("target_id") or "")
        build = dict(target.get("build") or {})
        raw = str(build.get("artifact") or "")
        base = {
            "path": raw,
            "present": False,
            "verified": False,
            "sha256": "",
            "sizeBytes": 0,
            "mediaType": "",
            "architecture": "",
            "executable": False,
            "signatureVerified": False,
            "signatureReported": {},
            "buildReceiptId": "",
            "buildReceiptHash": "",
            "errors": [],
        }
        try:
            path = self._resolve_workspace_path(raw)
            handle, opened = self._open_regular_file(path)
        except (ValueError, OSError) as exc:
            base["errors"].append(
                str(exc) if str(exc) else f"declared build artifact is missing: {raw}"
            )
            return base
        with handle:
            size = int(opened.st_size)
            base["present"] = True
            base["sizeBytes"] = size
            if size > MAX_ARTIFACT_HASH_BYTES:
                base["errors"].append(
                    f"artifact exceeds {MAX_ARTIFACT_HASH_BYTES} byte verification limit"
                )
                return base
            header = handle.read(min(size, 4096))
            digest = hashlib.sha256()
            digest.update(header)
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
            closed_stat = os.fstat(handle.fileno())
            if (
                closed_stat.st_size != opened.st_size
                or closed_stat.st_mtime_ns != opened.st_mtime_ns
            ):
                base["errors"].append("artifact changed while it was being verified")
                return base
        actual_hash = digest.hexdigest()
        executable = self._detect_executable(header, path, opened.st_mode)
        base.update(
            {
                "sha256": actual_hash,
                "mediaType": executable["mediaType"],
                "architecture": executable["architecture"],
                "executable": executable["executable"],
            }
        )
        expected = {
            "sha256": str(build.get("sha256") or "").lower(),
            "sizeBytes": int(build.get("size_bytes") or 0),
            "mediaType": str(build.get("media_type") or ""),
            "architecture": str(build.get("architecture") or ""),
        }
        for field, actual in (
            ("sha256", actual_hash),
            ("sizeBytes", size),
            ("mediaType", executable["mediaType"]),
            ("architecture", executable["architecture"]),
        ):
            if expected[field] != actual:
                base["errors"].append(
                    f"artifact {field} does not match declared build evidence"
                )
        if not executable["executable"]:
            base["errors"].append("artifact is not a recognized executable for its platform")
        if executable["architecture"] != self.host_architecture:
            base["errors"].append(
                f"artifact architecture {executable['architecture'] or 'unknown'} "
                f"does not match host {self.host_architecture}"
            )
        proof_config = dict(build.get("evidence") or {})
        receipt_id = str(proof_config.get("receipt_id") or "")
        if self.receipt_authority is None:
            proof = ExternalReceiptAuthority._invalid(
                receipt_id,
                "external receipt authority is unavailable",
            )
        else:
            proof = self.receipt_authority.verify_receipt(
                receipt_id,
                expected_kind="desktop_build",
            )
        base["buildReceiptId"] = str(proof.get("receiptId") or receipt_id)
        base["buildReceiptHash"] = str(proof.get("receiptHash") or "")
        proof_payload = proof.get("payload") if isinstance(proof.get("payload"), dict) else {}
        proof_errors = list(proof.get("errors") or [])
        if proof_payload:
            checks = {
                "schema": APPLICATION_SURFACE_DESKTOP_PROOF_SCHEMA,
                "targetId": target_id,
                "artifactSha256": actual_hash,
                "sizeBytes": size,
                "mediaType": executable["mediaType"],
                "architecture": executable["architecture"],
            }
            for field, expected_value in checks.items():
                if proof_payload.get(field) != expected_value:
                    proof_errors.append(f"desktop build proof {field} binding mismatch")
            max_age = int(proof_config.get("max_age_seconds") or 86400)
            if not self._timestamp_is_fresh(proof_payload.get("verifiedAt"), max_age):
                proof_errors.append("desktop build proof is missing, invalid, or stale")
            signature = (
                proof_payload.get("signature")
                if isinstance(proof_payload.get("signature"), dict)
                else {}
            )
            verifier = (
                signature.get("verifier")
                if isinstance(signature.get("verifier"), dict)
                else {}
            )
            base["signatureReported"] = {
                "status": str(signature.get("status") or ""),
                "verifierKind": str(verifier.get("kind") or ""),
                "verifierId": str(verifier.get("id") or ""),
            }
            receipt_signature_claim = (
                signature.get("status") == "verified"
                and str(signature.get("artifactSha256") or "").lower() == actual_hash
                and verifier.get("kind")
                in {"authenticode", "codesign", "sigstore", "package-signature"}
                and bool(str(verifier.get("id") or "").strip())
                and self._timestamp_is_fresh(
                    signature.get("verifiedAt"),
                    max_age,
                )
            )
            signature_ok = (
                receipt_signature_claim
                and self.host_platform == "windows"
                and self._windows_signature_valid(path)
            )
            if signature_ok and not self._artifact_identity_matches(
                path,
                expected_hash=actual_hash,
                expected_size=size,
            ):
                signature_ok = False
                proof_errors.append(
                    "artifact identity changed after signature verification"
                )
            base["signatureVerified"] = bool(signature_ok)
            if not signature_ok:
                proof_errors.append(
                    "artifact signature has no actual trusted platform verification"
                )
        base["errors"].extend(proof_errors)
        base["verified"] = not base["errors"]
        return base

    def _web_readiness_evidence(self, target: dict[str, Any]) -> dict[str, Any]:
        readiness = dict(target.get("readiness") or {})
        launch = dict(target.get("launch") or {})
        receipt_id = str(readiness.get("receipt_id") or "")
        if self.receipt_authority is None:
            result = ExternalReceiptAuthority._invalid(
                receipt_id,
                "external receipt authority is unavailable",
            )
        else:
            result = self.receipt_authority.verify_receipt(
                receipt_id,
                expected_kind="web_readiness",
            )
        payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
        errors = list(result.get("errors") or [])
        checks = {
            "schema": APPLICATION_SURFACE_WEB_PROOF_SCHEMA,
            "targetId": str(target.get("target_id") or ""),
            "url": str(launch.get("url") or ""),
            "status": "verified",
        }
        if payload:
            for field, expected in checks.items():
                if payload.get(field) != expected:
                    errors.append(f"web readiness proof {field} binding mismatch")
            max_age = int(readiness.get("max_age_seconds") or 300)
            if not self._timestamp_is_fresh(payload.get("verifiedAt"), max_age):
                errors.append("web readiness proof is missing, invalid, or stale")
            if not (200 <= int(payload.get("httpStatus") or 0) < 400):
                errors.append("web readiness proof has no successful observed HTTP status")
            verifier = (
                payload.get("verifier")
                if isinstance(payload.get("verifier"), dict)
                else {}
            )
            if verifier.get("kind") not in {"browser", "health_probe"}:
                errors.append("web readiness proof requires a trusted verifier kind")
            if not str(verifier.get("id") or "").strip():
                errors.append("web readiness proof verifier id is required")
        return {
            "verified": bool(payload) and not errors,
            "receiptId": str(result.get("receiptId") or receipt_id),
            "receiptHash": str(result.get("receiptHash") or ""),
            "url": str(launch.get("url") or ""),
            "verifiedAt": str(payload.get("verifiedAt") or ""),
            "errors": errors or (
                ["fresh bound web readiness proof required"] if not payload else []
            ),
        }

    def _approval_receipt(
        self,
        approval_id: str,
        *,
        plan_hash: str,
        manifest_hash: str,
        target_id: str,
        permissions: list[str],
    ) -> dict[str, Any]:
        clean_id = str(approval_id or "").strip()
        base = {
            "approvalId": clean_id,
            "valid": False,
            "approvedBy": "",
            "approvedAt": "",
            "receiptHash": "",
            "singleUse": True,
            "consumptionRequired": True,
            "reason": "bound_approval_receipt_required",
        }
        if not clean_id:
            return base
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", clean_id):
            base["reason"] = "invalid_approval_id"
            return base
        if self.receipt_authority is None:
            base["reason"] = "external_receipt_authority_unavailable"
            return base
        receipt = self.receipt_authority.verify_receipt(
            clean_id,
            expected_kind="approval",
        )
        base["receiptHash"] = str(receipt.get("receiptHash") or "")
        payload = receipt.get("payload") if isinstance(receipt.get("payload"), dict) else {}
        if not payload:
            base["reason"] = str(
                (receipt.get("errors") or ["approval_receipt_missing"])[0]
            )
            return base
        expected = {
            "schema": APPLICATION_SURFACE_APPROVAL_SCHEMA,
            "approvalId": clean_id,
            "status": "approved",
            "planHash": plan_hash,
            "manifestHash": manifest_hash,
            "targetId": target_id,
        }
        errors = [
            f"approval receipt {field} binding mismatch"
            for field, expected_value in expected.items()
            if payload.get(field) != expected_value
        ]
        approved = sorted(normalized_strings(payload.get("approvedPermissions")))
        if approved != sorted(permissions):
            errors.append("approval receipt permissions binding mismatch")
        approved_by = str(payload.get("approvedBy") or "").strip()
        if not re.fullmatch(r"(?:operator|user):[A-Za-z0-9_.@-]{1,128}", approved_by):
            errors.append("approval receipt approvedBy must identify an operator or user")
        approved_at = str(payload.get("approvedAt") or "")
        approved_at_value = self._parse_timestamp(approved_at)
        if not self._timestamp_is_fresh(approved_at, 3600):
            errors.append("approval receipt approvedAt is missing, invalid, or stale")
        expires_at = self._parse_timestamp(payload.get("expiresAt"))
        if expires_at is None or expires_at <= datetime.now(timezone.utc):
            errors.append("approval receipt is expired or has no valid expiresAt")
        elif (
            approved_at_value is None
            or expires_at <= approved_at_value
            or (expires_at - approved_at_value).total_seconds() > 3600
        ):
            errors.append("approval receipt validity window must be positive and at most one hour")
        if errors:
            base["reason"] = errors[0]
            return base
        base.update(
            {
                "valid": True,
                "approvedBy": approved_by,
                "approvedAt": approved_at,
                "reason": "",
            }
        )
        return base

    @checked_action(check_lifecycle_status)
    def _lifecycle_status(
        self,
        surface: dict[str, Any],
        *,
        manifest_hash: str,
        targets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        lifecycle = dict(surface.get("lifecycle") or {})
        status_file = str(lifecycle.get("status_file") or "")
        stream_id = str(lifecycle.get("stream_id") or "")
        workspace_report = (
            self._read_json_receipt(
                status_file,
                max_bytes=MAX_STRUCTURED_RECEIPT_BYTES,
            )
            if status_file
            else {"payload": {}, "sha256": "", "errors": []}
        )
        workspace_payload = (
            workspace_report.get("payload")
            if isinstance(workspace_report.get("payload"), dict)
            else {}
        )
        if not stream_id or self.receipt_authority is None:
            reported = str(workspace_payload.get("state") or "").strip().lower()
            detail, detail_redactions = self._redact_log_text(
                str(workspace_payload.get("detail") or "")
            )
            reason = (
                "external lifecycle authority is unavailable"
                if stream_id
                else "trusted lifecycle stream is not declared"
            )
            return {
                "state": "declared",
                "reportedState": reported,
                "verified": False,
                "source": status_file or "manifest",
                "workspaceReportTrusted": False,
                "detail": detail,
                "detailRedacted": detail_redactions > 0,
                "verificationErrors": [reason],
            }
        receipt = self.receipt_authority.verify_lifecycle_stream(stream_id)
        payload = receipt.get("payload") if isinstance(receipt.get("payload"), dict) else {}
        reported = str(payload.get("state") or "").strip().lower()
        previous = str(payload.get("previousState") or "").strip().lower()
        errors = list(receipt.get("errors") or [])
        declared_states = {
            str(item).strip().lower()
            for item in (lifecycle.get("states") or LIFECYCLE_STATES)
        }
        if payload.get("schema") != APPLICATION_SURFACE_LIFECYCLE_SCHEMA:
            errors.append("lifecycle schema binding mismatch")
        if reported not in LIFECYCLE_STATES or reported not in declared_states:
            errors.append(
                f"reported lifecycle state is not declared: {reported or '<empty>'}"
            )
        if previous not in declared_states or (previous, reported) not in LIFECYCLE_TRANSITIONS:
            errors.append(
                f"invalid lifecycle transition: {previous or '<empty>'}->{reported or '<empty>'}"
            )
        max_age = int(lifecycle.get("max_age_seconds") or 120)
        updated_at = str(payload.get("updatedAt") or "")
        if not self._timestamp_is_fresh(updated_at, max_age):
            errors.append("lifecycle report is missing, invalid, or stale")
        target_id = str(payload.get("targetId") or "")
        target = next(
            (item for item in targets if item.get("targetId") == target_id),
            {},
        )
        if not target:
            errors.append("lifecycle targetId is not part of the current status request")
        expected = {
            "manifestHash": manifest_hash,
            "planHash": target.get("planHash"),
            "artifactSha256": (target.get("artifact") or {}).get("sha256") or "",
        }
        for field, expected_value in expected.items():
            if payload.get(field, "") != expected_value:
                errors.append(f"lifecycle {field} binding mismatch")
        run_id = str(payload.get("runId") or "").strip()
        if not run_id:
            errors.append("lifecycle runId is required")
        process = payload.get("process") if isinstance(payload.get("process"), dict) else {}
        pid = process.get("pid")
        if reported in {"launching", "running"}:
            if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
                errors.append("lifecycle running state requires a bound process identity")
            else:
                actual_process = self._process_identity(pid)
                if not actual_process.get("verified"):
                    errors.append("lifecycle process identity cannot be verified")
                for field in (
                    "imagePath",
                    "imageSha256",
                    "commandHash",
                    "creationIdentity",
                ):
                    if not process.get(field) or process.get(field) != actual_process.get(field):
                        errors.append(f"lifecycle process {field} binding mismatch")
                if target.get("kind") == "desktop":
                    artifact = target.get("artifact") or {}
                    if process.get("imageSha256") != artifact.get("sha256"):
                        errors.append("desktop process image hash is not bound to artifact")
                    if actual_process.get("imageSha256") != artifact.get("sha256"):
                        errors.append("active desktop process image does not match artifact")
                elif target.get("kind") == "web":
                    listener = (
                        payload.get("listener")
                        if isinstance(payload.get("listener"), dict)
                        else {}
                    )
                    readiness = target.get("readinessEvidence") or {}
                    expected_listener = {
                        "url": readiness.get("url"),
                        "readinessReceiptId": readiness.get("receiptId"),
                        "readinessReceiptHash": readiness.get("receiptHash"),
                        "pid": pid,
                        "protocol": "tcp",
                    }
                    for field, expected_value in expected_listener.items():
                        if not expected_value or listener.get(field) != expected_value:
                            errors.append(f"web listener {field} binding mismatch")
                    parsed_url = urlparse(str(readiness.get("url") or ""))
                    expected_host = parsed_url.hostname or ""
                    expected_port = parsed_url.port or (
                        443 if parsed_url.scheme == "https" else 80
                    )
                    if listener.get("host") != expected_host:
                        errors.append("web listener host binding mismatch")
                    if listener.get("port") != expected_port:
                        errors.append("web listener port binding mismatch")
                    if not self._timestamp_is_fresh(
                        listener.get("observedAt"),
                        max_age,
                    ):
                        errors.append("web listener observation is missing, invalid, or stale")
        verified = bool(payload) and not errors
        detail, detail_redactions = self._redact_log_text(
            str(payload.get("detail") or "")
        )
        return {
            "state": reported if verified else "declared",
            "reportedState": reported,
            "previousState": previous,
            "verified": verified,
            "source": f"external:{stream_id}",
            "workspaceReportTrusted": False,
            "receiptId": str(receipt.get("receiptId") or ""),
            "receiptHash": str(receipt.get("receiptHash") or ""),
            "chainLength": int(receipt.get("chainLength") or 0),
            "updatedAt": updated_at,
            "runId": run_id,
            "planHash": str(payload.get("planHash") or ""),
            "pid": pid if isinstance(pid, int) and not isinstance(pid, bool) else None,
            "detail": detail,
            "detailRedacted": detail_redactions > 0,
            "verificationErrors": errors,
        }

    def _resolve_workspace_path(self, value: object) -> Path:
        raw = str(value or "").strip()
        if not _is_safe_relative_path(raw):
            raise ValueError(f"Application surface path must stay inside the workspace: {raw}")
        unresolved = self.root / raw
        current = self.root
        for part in Path(raw).parts[:-1]:
            current = current / part
            try:
                component = os.lstat(current)
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(component.st_mode) or (
                getattr(component, "st_file_attributes", 0) & 0x400
            ):
                raise ValueError(
                    f"Application surface path crosses a link or reparse point: {raw}"
                )
        parent = unresolved.parent.resolve()
        try:
            parent.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(
                f"Application surface path resolves outside the workspace: {raw}"
            ) from exc
        return parent / unresolved.name

    def _open_regular_file(self, path: Path) -> tuple[BinaryIO, os.stat_result]:
        before = os.lstat(path)
        reparse_point = bool(
            getattr(before, "st_file_attributes", 0) & 0x400
        )
        if stat.S_ISLNK(before.st_mode) or reparse_point:
            raise OSError("symbolic links and reparse points are not readable hooks")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise OSError("path is not a regular file")
            if (
                getattr(before, "st_ino", 0)
                and getattr(opened, "st_ino", 0)
                and (
                    before.st_ino != opened.st_ino
                    or before.st_dev != opened.st_dev
                )
            ):
                raise OSError("file changed before a stable handle was acquired")
            if os.name == "nt" and not self._windows_handle_matches_path(
                descriptor,
                path,
            ):
                raise OSError("Windows final file path does not match the requested hook")
            return os.fdopen(descriptor, "rb", closefd=True), opened
        except Exception:
            os.close(descriptor)
            raise

    def _windows_handle_matches_path(self, descriptor: int, path: Path) -> bool:
        if os.name != "nt":
            return True
        try:
            import ctypes
            import msvcrt
            from ctypes import wintypes

            handle = wintypes.HANDLE(msvcrt.get_osfhandle(descriptor))
            buffer = ctypes.create_unicode_buffer(32768)
            length = ctypes.windll.kernel32.GetFinalPathNameByHandleW(
                handle,
                buffer,
                len(buffer),
                0,
            )
            if not length or length >= len(buffer):
                return False
            final_raw = buffer.value
            if final_raw.startswith("\\\\?\\UNC\\"):
                final_raw = "\\\\" + final_raw[8:]
            elif final_raw.startswith("\\\\?\\"):
                final_raw = final_raw[4:]
            final_path = Path(final_raw).resolve()
            expected = path.resolve()
            final_path.relative_to(self.root)
            return os.path.normcase(str(final_path)) == os.path.normcase(str(expected))
        except Exception:
            return False

    def _read_json_receipt(
        self,
        value: object,
        *,
        max_bytes: int,
        already_resolved: bool = False,
    ) -> dict[str, Any]:
        raw = str(value or "").strip()
        if not raw:
            return {"payload": {}, "sha256": "", "errors": ["receipt path is not declared"]}
        try:
            if already_resolved:
                unresolved = Path(raw)
                parent = unresolved.parent.resolve()
                parent.relative_to(self.root)
                path = parent / unresolved.name
            else:
                path = self._resolve_workspace_path(raw)
            handle, opened = self._open_regular_file(path)
        except (ValueError, OSError) as exc:
            return {
                "payload": {},
                "sha256": "",
                "errors": [str(exc) or f"receipt is missing: {raw}"],
            }
        with handle:
            if opened.st_size > max_bytes:
                return {
                    "payload": {},
                    "sha256": "",
                    "errors": [f"receipt exceeds {max_bytes} byte limit"],
                }
            content = handle.read(opened.st_size + 1)
            after = os.fstat(handle.fileno())
            if (
                len(content) > max_bytes
                or after.st_size != opened.st_size
                or after.st_mtime_ns != opened.st_mtime_ns
            ):
                return {
                    "payload": {},
                    "sha256": "",
                    "errors": ["receipt changed while it was being read"],
                }
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {
                "payload": {},
                "sha256": hashlib.sha256(content).hexdigest(),
                "errors": ["receipt is not valid UTF-8 JSON"],
            }
        if not isinstance(payload, dict):
            return {
                "payload": {},
                "sha256": hashlib.sha256(content).hexdigest(),
                "errors": ["receipt JSON must be an object"],
            }
        return {
            "payload": payload,
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytesRead": len(content),
            "errors": [],
        }

    @staticmethod
    def _parse_timestamp(value: object) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)

    def _timestamp_is_fresh(self, value: object, max_age_seconds: int) -> bool:
        parsed = self._parse_timestamp(value)
        if parsed is None:
            return False
        age = (datetime.now(timezone.utc) - parsed).total_seconds()
        return -30 <= age <= max(1, int(max_age_seconds))

    @staticmethod
    def _pid_is_active(pid: int) -> bool:
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes

                process_query_limited_information = 0x1000
                still_active = 259
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                handle = kernel32.OpenProcess(
                    process_query_limited_information,
                    False,
                    int(pid),
                )
                if not handle:
                    return False
                try:
                    exit_code = wintypes.DWORD()
                    if not kernel32.GetExitCodeProcess(
                        handle,
                        ctypes.byref(exit_code),
                    ):
                        return False
                    return int(exit_code.value) == still_active
                finally:
                    kernel32.CloseHandle(handle)
            except Exception:
                return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _process_identity(self, pid: int) -> dict[str, Any]:
        base = {
            "verified": False,
            "pid": pid,
            "imagePath": "",
            "imageSha256": "",
            "commandHash": "",
            "creationIdentity": "",
        }
        if not self._pid_is_active(pid):
            return base
        try:
            if os.name == "nt":
                script = (
                    "$p=Get-CimInstance Win32_Process -Filter "
                    f"'ProcessId = {int(pid)}';"
                    "if($null -eq $p){exit 3};"
                    "$p|Select-Object ExecutablePath,CommandLine,CreationDate|"
                    "ConvertTo-Json -Compress"
                )
                completed = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        script,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if completed.returncode != 0:
                    return base
                row = json.loads(completed.stdout)
                image_path = str(row.get("ExecutablePath") or "")
                command = str(row.get("CommandLine") or "")
                creation = str(row.get("CreationDate") or "")
            elif sys.platform.startswith("linux"):
                proc_root = Path("/proc") / str(int(pid))
                image_path = os.readlink(proc_root / "exe")
                command = (proc_root / "cmdline").read_bytes().replace(b"\0", b"\x1f").decode(
                    "utf-8",
                    errors="replace",
                )
                fields = (proc_root / "stat").read_text(encoding="utf-8").split()
                boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(
                    encoding="ascii"
                ).strip()
                creation = f"{boot_id}:{fields[21]}"
            else:
                completed = subprocess.run(
                    ["ps", "-p", str(int(pid)), "-o", "lstart=,command="],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5,
                    **hidden_windows_subprocess_kwargs(),
                )
                if completed.returncode != 0 or not completed.stdout.strip():
                    return base
                image_path = ""
                command = completed.stdout.strip()
                creation = command[:24]
            image_hash = self._hash_external_file(Path(image_path)) if image_path else ""
            if not image_path or not command or not creation or not image_hash:
                return base
            base.update(
                {
                    "verified": True,
                    "imagePath": os.path.normcase(str(Path(image_path).resolve())),
                    "imageSha256": image_hash,
                    "commandHash": hashlib.sha256(command.encode("utf-8")).hexdigest(),
                    "creationIdentity": creation,
                }
            )
        except (OSError, ValueError, IndexError, json.JSONDecodeError, subprocess.SubprocessError):
            return base
        return base

    @staticmethod
    def _hash_external_file(path: Path) -> str:
        try:
            resolved = path.resolve(strict=True)
            before = os.lstat(resolved)
            if (
                not stat.S_ISREG(before.st_mode)
                or getattr(before, "st_file_attributes", 0) & 0x400
                or before.st_size > MAX_ARTIFACT_HASH_BYTES
            ):
                return ""
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(resolved, flags)
            digest = hashlib.sha256()
            try:
                opened = os.fstat(descriptor)
                if not stat.S_ISREG(opened.st_mode):
                    return ""
                if os.name == "nt":
                    final_path = _windows_final_path_from_fd(descriptor)
                    if final_path is None or os.path.normcase(
                        str(final_path)
                    ) != os.path.normcase(str(resolved)):
                        return ""
                while chunk := os.read(descriptor, 1024 * 1024):
                    digest.update(chunk)
                after = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            if (
                opened.st_size != before.st_size
                or after.st_size != opened.st_size
                or after.st_mtime_ns != before.st_mtime_ns
            ):
                return ""
            return digest.hexdigest()
        except OSError:
            return ""

    def _artifact_identity_matches(
        self,
        path: Path,
        *,
        expected_hash: str,
        expected_size: int,
    ) -> bool:
        try:
            handle, opened = self._open_regular_file(path)
            if opened.st_size != expected_size:
                handle.close()
                return False
            digest = hashlib.sha256()
            with handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
                after = os.fstat(handle.fileno())
            return (
                after.st_size == opened.st_size
                and after.st_mtime_ns == opened.st_mtime_ns
                and hmac.compare_digest(digest.hexdigest(), expected_hash)
            )
        except (OSError, ValueError):
            return False

    def _detect_executable(
        self,
        header: bytes,
        path: Path,
        mode: int,
    ) -> dict[str, Any]:
        if header.startswith(b"MZ") and len(header) >= 64:
            offset = int.from_bytes(header[0x3C:0x40], "little")
            if offset + 6 <= len(header) and header[offset : offset + 4] == b"PE\0\0":
                machine = int.from_bytes(header[offset + 4 : offset + 6], "little")
                architecture = {
                    0x8664: "x86_64",
                    0xAA64: "arm64",
                    0x14C: "x86",
                }.get(machine, "")
                return {
                    "executable": path.suffix.lower() == ".exe",
                    "mediaType": "application/vnd.microsoft.portable-executable",
                    "architecture": architecture,
                }
        if header.startswith(b"\x7fELF") and len(header) >= 20:
            byte_order = "little" if header[5] == 1 else "big"
            machine = int.from_bytes(header[18:20], byte_order)
            return {
                "executable": bool(mode & 0o111),
                "mediaType": "application/x-elf",
                "architecture": {62: "x86_64", 183: "arm64", 3: "x86"}.get(machine, ""),
            }
        if len(header) >= 8:
            magic = struct.unpack(">I", header[:4])[0]
            if magic in {0xFEEDFACF, 0xCFFAEDFE, 0xFEEDFACE, 0xCEFAEDFE}:
                cpu = int.from_bytes(
                    header[4:8],
                    "big" if magic in {0xFEEDFACF, 0xFEEDFACE} else "little",
                )
                return {
                    "executable": bool(mode & 0o111),
                    "mediaType": "application/x-mach-binary",
                    "architecture": {
                        0x01000007: "x86_64",
                        0x0100000C: "arm64",
                        7: "x86",
                    }.get(cpu, ""),
                }
        return {"executable": False, "mediaType": "", "architecture": ""}

    def _windows_signature_valid(self, path: Path) -> bool:
        if self.host_platform != "windows":
            return False
        try:
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "(Get-AuthenticodeSignature -LiteralPath $args[0]).Status",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0 and completed.stdout.strip() == "Valid"

    @staticmethod
    def _redact_log_text(text: str) -> tuple[str, int]:
        redacted = text
        count = 0
        for pattern in SECRET_PATTERNS:
            redacted, replacements = pattern.subn("[REDACTED]", redacted)
            count += replacements
        return redacted, count

    @checked_action(check_log_observer)
    def _read_log(
        self,
        value: object,
        *,
        max_lines: int,
        remaining_bytes: int,
    ) -> dict[str, Any]:
        raw = str(value or "")
        try:
            path = self._resolve_workspace_path(raw)
            handle, opened = self._open_regular_file(path)
        except ValueError as exc:
            return {"path": raw, "status": "blocked", "lines": [], "error": str(exc)}
        except OSError as exc:
            return {
                "path": raw,
                "status": "missing",
                "lines": [],
                "error": str(exc),
            }
        bounded_lines = max(1, min(int(max_lines), 200))
        if opened.st_size > MAX_LOG_FILE_BYTES:
            handle.close()
            return {
                "path": raw,
                "status": "too_large",
                "lines": [],
                "sizeBytes": opened.st_size,
                "bytesRead": 0,
                "redacted": False,
                "redactionCount": 0,
                "error": f"log exceeds {MAX_LOG_FILE_BYTES} byte source limit",
            }
        allowed = min(
            MAX_LOG_READ_BYTES + LOG_BOUNDARY_OVERLAP_BYTES,
            max(0, remaining_bytes),
        )
        if allowed <= 0:
            handle.close()
            return {
                "path": raw,
                "status": "budget_exhausted",
                "lines": [],
                "sizeBytes": opened.st_size,
                "bytesRead": 0,
                "redacted": False,
                "redactionCount": 0,
            }
        with handle:
            tail_bytes = min(
                MAX_LOG_READ_BYTES,
                max(0, allowed - LOG_BOUNDARY_OVERLAP_BYTES),
            )
            if opened.st_size <= MAX_LOG_READ_BYTES:
                read_start = 0
                read_size = min(opened.st_size, allowed)
            else:
                overlap = min(LOG_BOUNDARY_OVERLAP_BYTES, allowed - tail_bytes)
                read_size = min(opened.st_size, tail_bytes + overlap)
                read_start = max(0, opened.st_size - read_size)
            handle.seek(read_start)
            content = handle.read(read_size)
            after = os.fstat(handle.fileno())
            if (
                after.st_size != opened.st_size
                or after.st_mtime_ns != opened.st_mtime_ns
            ):
                return {
                    "path": raw,
                    "status": "changed_during_read",
                    "lines": [],
                    "sizeBytes": opened.st_size,
                    "bytesRead": len(content),
                    "redacted": False,
                    "redactionCount": 0,
                }
        partial_line_dropped = False
        if read_start > 0:
            boundary = content.find(b"\n")
            if boundary < 0:
                content_for_output = b""
            else:
                content_for_output = content[boundary + 1 :]
            partial_line_dropped = True
        else:
            content_for_output = content
        # A writer may have appended only part of its final record. Keep
        # complete newline-terminated records; the next observation can admit
        # that record after its writer finishes it.
        if content_for_output and not content_for_output.endswith(b"\n"):
            boundary = content_for_output.rfind(b"\n")
            content_for_output = content_for_output[: boundary + 1] if boundary >= 0 else b""
            partial_line_dropped = True
        text = content_for_output.decode("utf-8", errors="replace")
        safe_text, redaction_count = self._redact_log_text(text)
        lines = safe_text.splitlines()[-bounded_lines:]
        return {
            "path": raw,
            "status": "available",
            "lines": lines,
            "sizeBytes": opened.st_size,
            "bytesRead": len(content),
            "truncated": read_start > 0 or len(safe_text.splitlines()) > bounded_lines,
            "partialLineDropped": partial_line_dropped,
            "boundaryOverlapBytes": max(0, len(content) - min(len(content), tail_bytes)),
            "redacted": redaction_count > 0,
            "redactionCount": redaction_count,
        }

    def _proof_metadata(
        self,
        value: object,
        *,
        remaining_bytes: int,
    ) -> dict[str, Any]:
        raw = str(value or "")
        try:
            path = self._resolve_workspace_path(raw)
            handle, opened = self._open_regular_file(path)
        except ValueError as exc:
            return {
                "path": raw,
                "status": "blocked",
                "sha256": "",
                "sizeBytes": 0,
                "error": str(exc),
            }
        except OSError as exc:
            return {
                "path": raw,
                "status": "missing",
                "sha256": "",
                "sizeBytes": 0,
                "bytesRead": 0,
                "error": str(exc),
            }
        if opened.st_size > MAX_PROOF_FILE_BYTES or opened.st_size > remaining_bytes:
            handle.close()
            reason = (
                f"proof exceeds {MAX_PROOF_FILE_BYTES} byte per-file limit"
                if opened.st_size > MAX_PROOF_FILE_BYTES
                else "proof total byte budget exhausted"
            )
            return {
                "path": raw,
                "status": "too_large",
                "sha256": "",
                "sizeBytes": opened.st_size,
                "bytesRead": 0,
                "error": reason,
            }
        digest = hashlib.sha256()
        bytes_read = 0
        with handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                bytes_read += len(chunk)
            after = os.fstat(handle.fileno())
            if (
                after.st_size != opened.st_size
                or after.st_mtime_ns != opened.st_mtime_ns
            ):
                return {
                    "path": raw,
                    "status": "changed_during_read",
                    "sha256": "",
                    "sizeBytes": opened.st_size,
                    "bytesRead": bytes_read,
                }
        return {
            "path": raw,
            "status": "available",
            "sha256": digest.hexdigest(),
            "sizeBytes": opened.st_size,
            "bytesRead": bytes_read,
            "modifiedAt": opened.st_mtime,
        }
