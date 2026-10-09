"""Demand-start adapter registry for capability execution.

Adapters never pretend that an external program exists. Executable-backed
descriptors are discovered from the current machine and remain unavailable
until their real binary is present. Only explicitly registered handlers can
execute; discovery alone does not grant command execution.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen
from zipfile import ZIP_DEFLATED, ZipFile

from .capability_contracts import ADAPTER_CATALOG_SCHEMA, AdapterDescriptor, utc_now
from .encrypted_chat import EncryptedChatService
from .folder_sync import FolderSyncService
from .git_reference_adapter import GitReferenceAdapter
from .proofs_b_adapters import checked as _proofs_b_checked
from .managed_local_service import ManagedLocalService, ManagedServiceSpec
from .module_marketplace import ModuleMarketplace
from .mesh_service import MeshService
from .nearby_send import NearbySendService
from .p2p_cache import P2PCacheService
from .p2p_provider import P2PProviderService
from .secret_broker import SecretBrokerService
from .subprocess_utils import hidden_windows_subprocess_kwargs
from .proofs_a_capabilities import checked_action, check_adapter_descriptor, check_adapter_execution
from .proofs_a_capability_tools import check_adapter_private, check_pdf, check_direct_path


AdapterHandler = Callable[[dict[str, Any]], dict[str, Any]]
ADAPTER_SESSION_SCHEMA = "neyvia.capability_adapter_sessions.v1"


def _required_boolean_argument(
    arguments: dict[str, Any],
    name: str,
) -> bool:
    value = arguments.get(name)
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


class CapabilityAdapterSessionStore:
    """Persist scoped external-program bridges without persisting credentials."""

    ALLOWED_TRANSPORTS = frozenset(
        {"local_ipc", "stdio", "http", "websocket", "remote_runner"}
    )
    FORBIDDEN_KEYS = frozenset(
        {"token", "password", "secret", "apikey", "api_key", "cookie"}
    )

    def __init__(self, root: str | Path, *, stale_seconds: int = 120) -> None:
        self.root = Path(root).resolve()
        self.path = (
            self.root
            / ".agent_control"
            / "capability_os"
            / "adapter_sessions.json"
        )
        self.stale_seconds = max(15, int(stale_seconds))
        self._lock = threading.RLock()

    def _empty(self) -> dict[str, Any]:
        return {
            "schema": ADAPTER_SESSION_SCHEMA,
            "updatedAt": utc_now(),
            "sessions": {},
        }

    def _load_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty()
        if not isinstance(payload, dict) or payload.get("schema") != ADAPTER_SESSION_SCHEMA:
            return self._empty()
        if not isinstance(payload.get("sessions"), dict):
            payload["sessions"] = {}
        return payload

    @classmethod
    def _forbidden_paths(
        cls,
        value: object,
        *,
        prefix: str = "",
    ) -> list[str]:
        matches: list[str] = []
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key)
                path = f"{prefix}.{key_text}" if prefix else key_text
                normalized = key_text.casefold().replace("-", "_")
                if normalized in cls.FORBIDDEN_KEYS:
                    matches.append(path)
                matches.extend(cls._forbidden_paths(child, prefix=path))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                path = f"{prefix}[{index}]"
                matches.extend(cls._forbidden_paths(child, prefix=path))
        return matches

    @staticmethod
    def _public_session(row: dict[str, Any]) -> dict[str, Any]:
        public = dict(row)
        public.pop("heartbeatKeyHash", None)
        return public

    def register(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not bool(payload.get("approved")):
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "external.side_effect",
                "reason": "Connecting an external program requires explicit approval.",
            }
        forbidden = sorted(set(self._forbidden_paths(payload)))
        if forbidden:
            raise ValueError(
                "Adapter session payload must use authRef instead of secret fields: "
                + ", ".join(forbidden)
            )
        adapter_id = str(payload.get("adapterId") or "").strip().lower()
        if not adapter_id:
            raise ValueError("adapterId is required")
        transport = str(payload.get("transport") or "local_ipc").strip().lower()
        if transport not in self.ALLOWED_TRANSPORTS:
            raise ValueError(f"Unsupported adapter transport: {transport}")
        session_id = str(
            payload.get("sessionId") or f"adaptersession_{uuid.uuid4().hex[:20]}"
        ).strip()
        if not session_id or any(
            character
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for character in session_id
        ):
            raise ValueError("Invalid sessionId")
        now = utc_now()
        heartbeat_key = secrets.token_urlsafe(24)
        row = {
            "sessionId": session_id,
            "adapterId": adapter_id,
            "label": str(payload.get("label") or adapter_id),
            "transport": transport,
            "endpoint": str(payload.get("endpoint") or ""),
            "authRef": str(payload.get("authRef") or ""),
            "capabilities": [
                str(item)
                for item in (payload.get("capabilities") or [])
                if str(item).strip()
            ],
            "grantedPermissions": [
                str(item)
                for item in (payload.get("grantedPermissions") or [])
                if str(item).strip()
            ],
            "resourceClass": str(payload.get("resourceClass") or "heavy"),
            "status": "connected",
            "supportsExecution": bool(payload.get("supportsExecution", False)),
            "metadata": dict(payload.get("metadata") or {}),
            "createdAt": now,
            "lastSeenAt": now,
            "expiresAt": str(payload.get("expiresAt") or ""),
            "heartbeatKeyHash": hashlib.sha256(
                heartbeat_key.encode("utf-8")
            ).hexdigest(),
        }
        with self._lock:
            state = self._load_unlocked()
            previous = state["sessions"].get(session_id) or {}
            row["createdAt"] = str(previous.get("createdAt") or now)
            state["sessions"][session_id] = row
            state["updatedAt"] = now
            _atomic_json(self.path, state)
        return {
            "ok": True,
            "status": "connected",
            "session": self._public_session(row),
            "heartbeatKey": heartbeat_key,
        }

    def heartbeat(self, session_id: str, heartbeat_key: str) -> dict[str, Any]:
        normalized = str(session_id or "").strip()
        with self._lock:
            state = self._load_unlocked()
            row = state["sessions"].get(normalized)
            if not isinstance(row, dict):
                raise KeyError(f"Unknown adapter session: {normalized}")
            expected_hash = str(row.get("heartbeatKeyHash") or "")
            supplied_hash = hashlib.sha256(
                str(heartbeat_key or "").encode("utf-8")
            ).hexdigest()
            if not expected_hash or not hmac.compare_digest(
                expected_hash,
                supplied_hash,
            ):
                raise PermissionError("Invalid adapter session heartbeat key")
            row["status"] = "connected"
            row["lastSeenAt"] = utc_now()
            state["updatedAt"] = row["lastSeenAt"]
            _atomic_json(self.path, state)
            return self._public_session(row)

    def disconnect(self, session_id: str, *, approved: bool = False) -> dict[str, Any]:
        if not approved:
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "external.side_effect",
            }
        normalized = str(session_id or "").strip()
        with self._lock:
            state = self._load_unlocked()
            row = state["sessions"].get(normalized)
            if not isinstance(row, dict):
                raise KeyError(f"Unknown adapter session: {normalized}")
            row["status"] = "disconnected"
            row["lastSeenAt"] = utc_now()
            state["updatedAt"] = row["lastSeenAt"]
            _atomic_json(self.path, state)
            return {
                "ok": True,
                "status": "disconnected",
                "session": self._public_session(row),
            }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = self._load_unlocked()
        now = datetime.now(timezone.utc)
        rows: list[dict[str, Any]] = []
        for session_id in sorted(state["sessions"]):
            row = dict(state["sessions"][session_id])
            row.pop("heartbeatKeyHash", None)
            last_seen = _parse_datetime(row.get("lastSeenAt"))
            expires = _parse_datetime(row.get("expiresAt"))
            stale = (
                last_seen is None
                or (now - last_seen).total_seconds() > self.stale_seconds
            )
            expired = expires is not None and now >= expires
            connected = (
                row.get("status") == "connected"
                and not stale
                and not expired
            )
            row["available"] = connected
            row["health"] = (
                "expired"
                if expired
                else "stale"
                if stale
                else "connected"
                if connected
                else "disconnected"
            )
            rows.append(row)
        return {
            "schema": ADAPTER_SESSION_SCHEMA,
            "updatedAt": state.get("updatedAt") or "",
            "sessions": rows,
            "summary": {
                "total": len(rows),
                "available": sum(1 for item in rows if item["available"]),
                "stale": sum(1 for item in rows if item["health"] == "stale"),
            },
        }


@dataclass(frozen=True)
class AdapterExecution:
    adapter_id: str
    ok: bool
    status: str
    summary: str
    duration_ms: float
    result: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "adapterId": self.adapter_id,
            "ok": self.ok,
            "status": self.status,
            "summary": self.summary,
            "durationMs": round(self.duration_ms, 3),
            "result": dict(self.result),
            "completedAt": utc_now(),
        }


class CapabilityAdapterRegistry:
    """Registry of honest adapter availability and explicitly safe handlers."""

    EXECUTABLE_ADAPTERS = (
        ("ocr.glm", "GLM-OCR fast visual recognition", ("ollama",), "accelerated"),
        ("ocr.paddle", "PaddleOCR hybrid document OCR", ("python",), "accelerated"),
        ("ocr.tesseract", "Tesseract OCR", ("tesseract",), "accelerated"),
        ("pdf.pdftotext", "Poppler pdftotext", ("pdftotext",), "light"),
        (
            "document.libreoffice",
            "LibreOffice",
            ("soffice", "libreoffice"),
            "heavy",
        ),
        ("document.pandoc", "Pandoc", ("pandoc",), "standard"),
        ("latex.compiler", "LaTeX compiler", ("latexmk", "tectonic", "pdflatex"), "heavy"),
        ("media.ffmpeg", "FFmpeg", ("ffmpeg",), "accelerated"),
        ("three_d.blender", "Blender", ("blender",), "heavy"),
        (
            "game.unity",
            "Unity Editor",
            ("Unity", "Unity.exe", "unity-editor"),
            "heavy",
        ),
        ("device.android", "Android ADB", ("adb",), "heavy"),
        ("marketplace.cosign", "Sigstore Cosign", ("cosign",), "light"),
        ("marketplace.wasmtime", "Wasmtime", ("wasmtime",), "light"),
        ("marketplace.syft", "Syft SBOM generator", ("syft",), "standard"),
        ("marketplace.grype", "Grype vulnerability scanner", ("grype",), "standard"),
        (
            "marketplace.defender",
            "Microsoft Defender module scanner",
            ("MpCmdRun",),
            "standard",
        ),
        ("code.git", "Git", ("git",), "light"),
        ("runtime.python", "Python", ("python", "python3"), "standard"),
        ("runtime.node", "Node.js", ("node",), "standard"),
    )
    _ANDROID_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:$-]+$")
    _PANDOC_FORMAT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_+.-]{0,79}$")
    _PANDOC_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")
    _LIBREOFFICE_SOURCE_FAMILIES = {
        ".doc": "writer",
        ".docx": "writer",
        ".odt": "writer",
        ".rtf": "writer",
        ".txt": "writer",
        ".html": "writer",
        ".htm": "writer",
        ".xls": "calc",
        ".xlsx": "calc",
        ".ods": "calc",
        ".csv": "calc",
        ".ppt": "impress",
        ".pptx": "impress",
        ".odp": "impress",
        ".odg": "draw",
    }
    _LIBREOFFICE_OUTPUT_FILTERS = {
        "docx": ("writer", "Office Open XML Text"),
        "odt": ("writer", "writer8"),
        "rtf": ("writer", "Rich Text Format"),
        "txt": ("writer", "Text"),
        "html": ("writer", "HTML (StarWriter)"),
        "xlsx": ("calc", "Calc MS Excel 2007 XML"),
        "ods": ("calc", "calc8"),
        "pptx": ("impress", "Impress MS PowerPoint 2007 XML"),
        "odp": ("impress", "impress8"),
        "odg": ("draw", "draw8"),
    }
    _LIBREOFFICE_PDF_FILTERS = {
        "writer": "writer_pdf_Export",
        "calc": "calc_pdf_Export",
        "impress": "impress_pdf_Export",
        "draw": "draw_pdf_Export",
    }
    _ANDROID_MUTATIONS = frozenset(
        {"install", "launch", "tap", "swipe", "text", "screenshot", "start_emulator"}
    )

    def __init__(
        self,
        root: str | Path,
        *,
        tool_manifests: Any | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.tool_manifests = tool_manifests
        self.sessions = CapabilityAdapterSessionStore(self.root)
        self._descriptors: dict[str, AdapterDescriptor] = {}
        self._handlers: dict[str, AdapterHandler] = {}
        self._register_core()
        self.refresh_executable_adapters()
        self.refresh_bridge_sessions()

    def _register_core(self) -> None:
        self.register(
            AdapterDescriptor(
                adapter_id="neyvia.agent",
                label="N-E-Y-V-I-A agent runtime",
                kind="resident_agent",
                available=True,
                reason="Delegates reasoning work to the selected N-E-Y-V-I-A runtime lane.",
                resource_class="standard",
                supports_execution=False,
                metadata={"handoff": "neyvia.stage_scheduler", "resident": True},
            )
        )
        self.register(
            AdapterDescriptor(
                adapter_id="builtin.artifact.inspect",
                label="Artifact inspector",
                kind="builtin",
                available=True,
                reason="Reads file metadata and hashes without mutating the source.",
                resource_class="light",
                supports_execution=True,
            ),
            self._inspect_artifact,
        )
        self.register(
            AdapterDescriptor(
                adapter_id="builtin.text.extract",
                label="Native text extractor",
                kind="builtin",
                available=True,
                reason="Reads bounded UTF-8-compatible text files without OCR.",
                resource_class="light",
                supports_execution=True,
            ),
            self._extract_text,
        )
        self.register(
            AdapterDescriptor(
                adapter_id="mesh.control",
                label="Neyvia private-mesh control",
                kind="builtin",
                available=True,
                reason=(
                    "Provider-neutral mesh health, route probes, migration gates, "
                    "and private service discovery are available."
                ),
                resource_class="light",
                supports_execution=True,
                metadata={
                    "operations": [
                        "status",
                        "probe_peer",
                        "list_services",
                        "advertise_service",
                        "revoke_service",
                        "migration_plan",
                        "identity_status",
                        "plan_identity_mutation",
                        "prepare_enrollment",
                        "stage_identity",
                        "request_key_rotation",
                        "transition_key_rotation",
                        "revoke_device",
                        "set_device_trust",
                        "upsert_acl_rule",
                        "evaluate_acl",
                        "request_device_recovery",
                        "transition_device_recovery",
                        "identity_readiness",
                    ],
                    "credentialsExposed": False,
                    "detailsDeferred": True,
                    "providerIdentityActionsImplemented": False,
                },
            ),
            self._execute_mesh_control,
        )
        self.register(
            AdapterDescriptor(
                adapter_id="nearby.control",
                label="Neyvia Nearby Send",
                kind="builtin",
                available=True,
                reason=(
                    "A bounded LocalSend v2.1 discovery and sender client is "
                    "available with certificate pinning and artifact receipts."
                ),
                resource_class="light",
                supports_execution=True,
                metadata={
                    "operations": [
                        "compatibility",
                        "discover",
                        "plan_send",
                        "send",
                    ],
                    "protocol": "localsend-v2.1",
                    "receiverSidecarImplemented": False,
                },
            ),
            self._execute_nearby_control,
        )
        self.register(
            AdapterDescriptor(
                adapter_id="sync.control",
                label="Neyvia continuous folder sync",
                kind="builtin",
                available=True,
                reason=(
                    "A credential-hiding Syncthing REST client is available "
                    "with paused plans, versioning gates, events, and receipts."
                ),
                resource_class="standard",
                supports_execution=True,
                metadata={
                    "operations": [
                        "compatibility",
                        "health",
                        "plan_folder",
                        "apply_folder",
                        "pause",
                        "resume",
                        "rescan",
                        "events",
                        "observe_conflict",
                        "plan_conflict_resolution",
                        "authorize_conflict_resolution",
                        "record_connectivity",
                        "override",
                        "revert",
                    ],
                    "provider": "syncthing",
                    "credentialsExposed": False,
                    "dangerousRecoverySeparated": True,
                },
            ),
            self._execute_folder_sync,
        )
        self.register(
            AdapterDescriptor(
                adapter_id="chat.control",
                label="Neyvia encrypted multi-device chat",
                kind="builtin",
                available=True,
                reason=(
                    "A room-scoped Matrix Rust SDK transport is available "
                    "with E2EE proof, opaque identities, previews, and receipts."
                ),
                resource_class="standard",
                supports_execution=True,
                metadata={
                    "operations": [
                        "compatibility",
                        "account_catalog",
                        "lifecycle",
                        "prepare_enrollment",
                        "remove_device",
                        "expire_sessions",
                        "recover_account",
                        "plan_message",
                        "plan_self_chat",
                        "send",
                        "history",
                    ],
                    "provider": "matrix",
                    "credentialsExposed": False,
                    "messageContentInProcessArgs": False,
                    "nativeIpcSidecarImplemented": False,
                },
            ),
            self._execute_encrypted_chat,
        )
        self.register(
            AdapterDescriptor(
                adapter_id="secret.broker",
                label="Neyvia opaque secret broker",
                kind="builtin",
                available=True,
                reason=(
                    "Destination-bound one-time leases inject vault values "
                    "without exposing them to the agent or process arguments."
                ),
                resource_class="standard",
                supports_execution=True,
                metadata={
                    "operations": [
                        "compatibility",
                        "catalog",
                        "plan_use",
                        "use",
                        "revoke",
                        "revoke_subject",
                        "revocation_status",
                        "audit",
                    ],
                    "provider": "vaultwarden-bitwarden-cli",
                    "secretValuesExposed": False,
                    "oneTimeLeases": True,
                    "explicitApprovalArtifacts": True,
                    "deviceSessionRevocation": True,
                    "clipboardDefault": "disabled",
                },
            ),
            self._execute_secret_broker,
        )
        self.register(
            AdapterDescriptor(
                adapter_id="cache.p2p",
                label="Neyvia local-first peer object cache",
                kind="builtin",
                available=True,
                reason=(
                    "A BLAKE3 local CAS and SQLite index provide bounded "
                    "offline lookup, allowlisted Iroh fetch, and supervised "
                    "approval-gated publication."
                ),
                resource_class="standard",
                supports_execution=True,
                metadata={
                    "operations": [
                        "compatibility",
                        "plan_import",
                        "import_object",
                        "read_text",
                        "stats",
                        "provider_status",
                        "plan_publication",
                        "apply_publication",
                        "provider_receipts",
                    ],
                    "hash": "blake3",
                    "localCasImplemented": True,
                    "irohSidecarImplemented": True,
                    "supervisedPublicationImplemented": True,
                },
            ),
            self._execute_p2p_cache,
        )
        for adapter_id, label, resource_class, reason in (
            (
                "device.apple-remote",
                "Remote Apple Xcode runner",
                "remote",
                "No healthy authenticated Mac/Xcode runner is registered.",
            ),
            (
                "browser.firefox-bidi",
                "Firefox or Zen browser bridge",
                "standard",
                "No healthy Firefox WebDriver BiDi bridge is registered.",
            ),
            (
                "office.document-session",
                "Connected Office document session",
                "standard",
                "No healthy connected Office document session is registered.",
            ),
            (
                "game.unity-bridge",
                "Unity Editor live bridge",
                "heavy",
                "No healthy Unity Editor package session is registered.",
            ),
            (
                "three_d.blender-bridge",
                "Blender live scene bridge",
                "heavy",
                "No healthy Blender add-on session is registered.",
            ),
        ):
            self.register(
                AdapterDescriptor(
                    adapter_id=adapter_id,
                    label=label,
                    kind="external_bridge",
                    available=False,
                    reason=reason,
                    resource_class=resource_class,
                    supports_execution=False,
                    metadata={"demandStart": True, "sessionRequired": True},
                )
            )

    def register(
        self,
        descriptor: AdapterDescriptor,
        handler: AdapterHandler | None = None,
    ) -> None:
        adapter_id = str(descriptor.adapter_id or "").strip().lower()
        if not adapter_id:
            raise ValueError("adapterId is required")
        self._descriptors[adapter_id] = descriptor
        if handler is not None:
            self._handlers[adapter_id] = handler

    def refresh_executable_adapters(self) -> None:
        for adapter_id, label, candidates, resource_class in self.EXECUTABLE_ADAPTERS:
            executable, managed_metadata = self._managed_executable(
                adapter_id,
                candidates,
            )
            if not executable:
                # Git readiness is fail-closed against the locked launcher identity.
                # Do not PATH-fallback to an unverified executable when the lock pin misses.
                if adapter_id != "code.git":
                    for candidate in candidates:
                        found = shutil.which(candidate)
                        if found:
                            executable = str(Path(found).resolve())
                            break
            handler = self._handler_for(adapter_id)
            self.register(
                AdapterDescriptor(
                    adapter_id=adapter_id,
                    label=label,
                    kind="external_executable",
                    available=bool(executable),
                    reason=(
                        f"Discovered executable at {executable}."
                        if executable
                        else f"None of {', '.join(candidates)} was found on PATH."
                    ),
                    executable=executable,
                    resource_class=resource_class,
                    supports_execution=bool(executable and handler),
                    metadata={
                        "demandStart": True,
                        "probeCandidates": list(candidates),
                        "executionRequiresExplicitHandler": handler is None,
                        "boundedExecutionHandler": bool(handler),
                        **managed_metadata,
                        **self._handler_metadata(adapter_id),
                    },
                ),
                handler if executable else None,
            )

    def _managed_executable(
        self,
        adapter_id: str,
        candidates: tuple[str, ...],
    ) -> tuple[str, dict[str, Any]]:
        registry = self.tool_manifests
        tools = getattr(registry, "tools", {}) if registry is not None else {}
        for tool_id in sorted(tools):
            manifest = tools[tool_id]
            if adapter_id not in manifest.adapters or not manifest.agent_ready:
                continue
            install_path = Path(str(manifest.install_path or ""))
            if not install_path.is_file():
                return "", {
                    "toolId": manifest.tool_id,
                    "managedInstallation": True,
                    "toolState": manifest.state,
                    "toolHealth": manifest.health_status,
                    "managedPathMissing": str(install_path),
                }
            candidate_names = {
                item.casefold()
                for candidate in candidates
                for item in (candidate, f"{candidate}.exe", f"{candidate}.com")
            }
            if install_path.name.casefold() not in candidate_names:
                return "", {
                    "toolId": manifest.tool_id,
                    "managedInstallation": True,
                    "toolState": manifest.state,
                    "toolHealth": manifest.health_status,
                    "managedPathInvalid": str(install_path),
                }
            resolved_path = str(install_path.resolve())
            identity_metadata: dict[str, Any] = {}
            if adapter_id == "code.git":
                try:
                    probe = GitReferenceAdapter(
                        self.root,
                        executable=resolved_path,
                        expected_sha256=manifest.package_sha256,
                        expected_version=manifest.selected_version,
                    )
                    identity_metadata = {
                        "runtimeIdentityVerified": True,
                        "resolvedVersion": probe.version,
                        "resolvedSha256": probe.executable_sha256,
                    }
                except Exception as exc:
                    return "", {
                        "toolId": manifest.tool_id,
                        "managedInstallation": True,
                        "toolState": manifest.state,
                        "toolHealth": manifest.health_status,
                        "runtimeIdentityVerified": False,
                        "runtimeIdentityError": str(exc),
                    }
            elif adapter_id == "marketplace.defender":
                try:
                    resolved_sha256 = hashlib.sha256(install_path.read_bytes()).hexdigest()
                    expected_hashes = {
                        value
                        for value in (
                            str(manifest.package_sha256 or "").strip().lower(),
                            str(
                                (manifest.health or {}).get("executableSha256") or ""
                            ).strip().lower(),
                        )
                        if value
                    }
                    if expected_hashes and resolved_sha256 not in expected_hashes:
                        raise RuntimeError(
                            "The current Defender executable hash does not match "
                            "the pinned package or health receipt."
                        )
                    resolved_version = install_path.parent.name
                    if not resolved_version:
                        raise RuntimeError(
                            "The current Defender platform version could not be resolved."
                        )
                    identity_metadata = {
                        "runtimeIdentityVerified": True,
                        "resolvedVersion": resolved_version,
                        "resolvedSha256": resolved_sha256,
                    }
                except Exception as exc:
                    return "", {
                        "toolId": manifest.tool_id,
                        "managedInstallation": True,
                        "toolState": manifest.state,
                        "toolHealth": manifest.health_status,
                        "runtimeIdentityVerified": False,
                        "runtimeIdentityError": str(exc),
                    }
            return resolved_path, {
                "toolId": manifest.tool_id,
                "managedInstallation": True,
                "toolState": manifest.state,
                "toolHealth": manifest.health_status,
                "packageSha256": manifest.package_sha256,
                **identity_metadata,
            }
        return "", {}

    def _handler_for(self, adapter_id: str) -> AdapterHandler | None:
        return {
            "ocr.glm": self._execute_glm,
            "ocr.paddle": self._execute_paddle,
            "ocr.tesseract": self._execute_tesseract,
            "pdf.pdftotext": self._execute_pdftotext,
            "document.libreoffice": self._execute_libreoffice,
            "document.pandoc": self._execute_pandoc,
            "device.android": self._execute_android,
            "marketplace.cosign": self._execute_marketplace_cosign,
            "marketplace.wasmtime": self._execute_marketplace_wasmtime,
            "marketplace.syft": self._execute_marketplace_syft,
            "marketplace.grype": self._execute_marketplace_grype,
            "marketplace.defender": self._execute_marketplace_defender,
            "code.git": self._execute_git_reference,
        }.get(adapter_id)

    @staticmethod
    def _handler_metadata(adapter_id: str) -> dict[str, Any]:
        return {
            "ocr.glm": {
                "operations": [
                    "health",
                    "service_status",
                    "service_start",
                    "service_stop",
                    "service_restart",
                    "extract_text",
                    "recognize_formula",
                    "recognize_table",
                ],
                "acceptedInputs": ["pdf", "image"],
                "progressive": True,
                "artifactAware": True,
                "modelProfiles": ["glm-ocr-bf16"],
                "routing": {
                    "fullPageText": "glm-ocr-bf16",
                    "structuredLayout": "ocr.paddle",
                    "wordBoxes": "ocr.paddle",
                    "cpuEmergency": "ocr.tesseract",
                },
                "limits": {
                    "maxPages": 20,
                    "dpi": 300,
                    "maxNewTokens": 4096,
                    "timeoutSeconds": 900,
                },
            },
            "pdf.pdftotext": {
                "operations": ["extract"],
                "acceptedInputs": ["pdf"],
                "progressive": True,
                "limits": {"maxChars": 5_000_000, "timeoutSeconds": 300},
            },
            "ocr.tesseract": {
                "operations": [
                    "version",
                    "languages",
                    "extract_text",
                    "extract_layout",
                    "export",
                ],
                "acceptedInputs": ["pdf", "image"],
                "progressive": True,
                "artifactAware": True,
                "modelProfiles": ["fast", "accurate"],
                "limits": {"maxPages": 100, "workers": 4, "dpi": 400},
            },
            "ocr.paddle": {
                "operations": [
                    "health",
                    "service_status",
                    "service_start",
                    "service_stop",
                    "service_restart",
                    "extract_text",
                    "extract_layout",
                    "parse_document",
                ],
                "acceptedInputs": ["pdf", "image"],
                "progressive": True,
                "artifactAware": True,
                "modelProfiles": [
                    "pp-ocrv6-medium",
                    "paddleocr-vl-1.6",
                ],
                "routing": {
                    "printedText": "pp-ocrv6-medium",
                    "complexStructure": "paddleocr-vl-1.6",
                    "cpuEmergency": "ocr.tesseract",
                },
                "limits": {
                    "maxPages": 50,
                    "dpi": 300,
                    "timeoutSeconds": 900,
                },
            },
            "document.pandoc": {
                "operations": ["formats", "inspect_ast", "convert"],
                "acceptedInputs": ["local-document"],
                "sandboxed": True,
                "artifactAware": True,
                "limits": {
                    "maxAstChars": 5_000_000,
                    "maxBibliographies": 20,
                    "timeoutSeconds": 600,
                },
            },
            "document.libreoffice": {
                "operations": ["version", "convert", "render_pdf"],
                "acceptedInputs": ["writer", "calc", "impress", "draw"],
                "profileIsolation": True,
                "artifactAware": True,
                "limits": {
                    "maxSourceBytes": 1_073_741_824,
                    "timeoutSeconds": 900,
                },
            },
            "device.android": {
                "operations": [
                    "devices",
                    "device_info",
                    "packages",
                    "logcat",
                    "install",
                    "launch",
                    "tap",
                    "swipe",
                    "text",
                    "screenshot",
                    "list_avds",
                    "start_emulator",
                ],
                "mutationsRequireApproval": sorted(
                    CapabilityAdapterRegistry._ANDROID_MUTATIONS
                ),
            },
            "marketplace.cosign": {
                "operations": ["verify_signature"],
                "identityBound": True,
                "detachedBundle": True,
            },
            "marketplace.wasmtime": {
                "operations": ["smoke_test_wasm"],
                "filesystemAccess": "none-by-default",
                "environmentAccess": "none-by-default",
                "networkAccess": "none-by-default",
            },
            "marketplace.syft": {
                "operations": ["generate_sbom"],
                "formats": ["spdx-json", "cyclonedx-json", "syft-json"],
            },
            "marketplace.grype": {
                "operations": ["scan_vulnerabilities"],
                "databaseAware": True,
            },
            "marketplace.defender": {
                "operations": ["scan_malware"],
                "disableRemediation": True,
            },
            "code.git": {
                "operations": [
                    "repository.inspect",
                    "repository.history",
                    "repository.show",
                    "commit.ancestry-verify",
                ],
                "surface": "object-only-v1",
                "readOnly": True,
                "networkAccess": "denied",
                "credentialPrompts": "denied",
                "hooks": "disabled",
                "externalDiff": "disabled",
                "textconv": "disabled",
                "repositoryExtensions": "rejected",
                "linkedWorktrees": "rejected",
                "alternatesAndPromisors": "rejected",
                "artifactAware": True,
                "limits": {
                    "maxPaths": GitReferenceAdapter.MAX_PATHS,
                    "maxCommits": GitReferenceAdapter.MAX_COMMITS,
                    "maxOutputBytes": GitReferenceAdapter.MAX_OUTPUT_BYTES,
                    "maxTimeoutSeconds": GitReferenceAdapter.MAX_TIMEOUT_SECONDS,
                },
            },
        }.get(adapter_id, {})

    def refresh_bridge_sessions(self) -> None:
        snapshot = self.sessions.snapshot()
        selected: dict[str, dict[str, Any]] = {}
        for row in snapshot["sessions"]:
            adapter_id = str(row.get("adapterId") or "").strip().lower()
            if not adapter_id:
                continue
            current = selected.get(adapter_id)
            if current is None or (
                bool(row.get("available"))
                and not bool(current.get("available"))
            ):
                selected[adapter_id] = row
        for adapter_id, row in selected.items():
            self.register(
                AdapterDescriptor(
                    adapter_id=adapter_id,
                    label=str(row.get("label") or adapter_id),
                    kind="external_bridge",
                    available=bool(row.get("available")),
                    reason=(
                        f"Bridge session {row.get('sessionId')} is healthy."
                        if row.get("available")
                        else (
                            f"Bridge session {row.get('sessionId')} is "
                            f"{row.get('health') or row.get('status')}."
                        )
                    ),
                    resource_class=str(row.get("resourceClass") or "heavy"),
                    supports_execution=False,
                    metadata={
                        "sessionId": row.get("sessionId"),
                        "transport": row.get("transport"),
                        "endpoint": row.get("endpoint"),
                        "authRef": row.get("authRef"),
                        "capabilities": list(row.get("capabilities") or []),
                        "grantedPermissions": list(
                            row.get("grantedPermissions") or []
                        ),
                        "health": row.get("health"),
                        "executionRequiresInProcessClient": True,
                    },
                )
            )

    @checked_action(check_adapter_private)
    def register_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.sessions.register(payload)
        self.refresh_bridge_sessions()
        return result

    @checked_action(check_adapter_private)
    def heartbeat_session(
        self,
        session_id: str,
        heartbeat_key: str,
    ) -> dict[str, Any]:
        result = self.sessions.heartbeat(session_id, heartbeat_key)
        self.refresh_bridge_sessions()
        return result

    @checked_action(check_adapter_private)
    def disconnect_session(
        self,
        session_id: str,
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        result = self.sessions.disconnect(session_id, approved=approved)
        self.refresh_bridge_sessions()
        return result

    @checked_action(check_adapter_descriptor)
    def descriptor(self, adapter_id: str) -> AdapterDescriptor:
        normalized = str(adapter_id or "").strip().lower()
        descriptor = self._descriptors.get(normalized)
        if descriptor is None:
            return AdapterDescriptor(
                adapter_id=normalized or "unknown",
                label=normalized or "Unknown adapter",
                kind="unregistered",
                available=False,
                reason="No adapter descriptor is registered.",
                supports_execution=False,
            )
        return descriptor

    def available(self, adapter_id: str) -> tuple[bool, str]:
        descriptor = self.descriptor(adapter_id)
        return descriptor.available, descriptor.reason

    def list_descriptors(self) -> list[dict[str, Any]]:
        return [
            self._descriptors[key].as_dict()
            for key in sorted(self._descriptors)
        ]

    def snapshot(self) -> dict[str, Any]:
        self.refresh_bridge_sessions()
        rows = self.list_descriptors()
        return {
            "schema": ADAPTER_CATALOG_SCHEMA,
            "generatedAt": utc_now(),
            "adapters": rows,
            "summary": {
                "total": len(rows),
                "available": sum(1 for item in rows if item["available"]),
                "executable": sum(1 for item in rows if item["supportsExecution"]),
                "unavailable": sum(1 for item in rows if not item["available"]),
            },
            "bridgeSessions": self.sessions.snapshot(),
        }

    @checked_action(check_adapter_execution)
    @checked_action(check_pdf)
    def execute(self, adapter_id: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized = str(adapter_id or "").strip().lower()
        descriptor = self.descriptor(normalized)
        if not descriptor.available:
            return AdapterExecution(
                adapter_id=normalized,
                ok=False,
                status="unavailable",
                summary=descriptor.reason,
                duration_ms=0.0,
                result={},
            ).as_dict()
        handler = self._handlers.get(normalized)
        if handler is None or not descriptor.supports_execution:
            return AdapterExecution(
                adapter_id=normalized,
                ok=False,
                status="not_executable",
                summary=(
                    "The adapter is discoverable but has no approved execution handler. "
                    "N-E-Y-V-I-A will not synthesize an external result."
                ),
                duration_ms=0.0,
                result={},
            ).as_dict()
        started = time.perf_counter()
        try:
            result = handler(dict(arguments or {}))
            ok = bool(result.get("ok", True))
            status = str(result.get("status") or ("completed" if ok else "failed"))
            summary = str(result.get("summary") or descriptor.label)
        except Exception as exc:
            result = {"error": str(exc)}
            ok = False
            status = "failed"
            summary = f"{descriptor.label} failed: {exc}"
        return AdapterExecution(
            adapter_id=normalized,
            ok=ok,
            status=status,
            summary=summary,
            duration_ms=(time.perf_counter() - started) * 1000.0,
            result=result,
        ).as_dict()

    def _resolve_existing_file(self, value: object) -> Path:
        text = str(value or "").strip()
        if not text:
            raise ValueError("path is required")
        path = Path(text)
        if not path.is_absolute():
            path = self.root / path
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    @checked_action(check_direct_path)
    def _resolve_existing_workspace_path(self, value: object) -> Path:
        text = str(value or "").strip()
        if not text:
            raise ValueError("path is required")
        path = Path(text)
        if not path.is_absolute():
            path = self.root / path
        path = path.resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise PermissionError(
                "Direct tool operations are limited to the active workspace"
            ) from exc
        if not path.exists():
            raise FileNotFoundError(path)
        return path

    def _resolve_existing_workspace_file(self, value: object) -> Path:
        path = self._resolve_existing_workspace_path(value)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def _execute_git_reference(self, arguments: dict[str, Any]) -> dict[str, Any]:
        descriptor = self.descriptor("code.git")
        if not descriptor.executable:
            raise RuntimeError("The resolved Git executable is unavailable")
        tool = getattr(self.tool_manifests, "tools", {}).get("tool.git")
        return GitReferenceAdapter(
            self.root,
            executable=descriptor.executable,
            expected_sha256=str(getattr(tool, "package_sha256", "") or ""),
            expected_version=str(getattr(tool, "selected_version", "") or ""),
        ).execute(arguments)

    @staticmethod
    def _bounded_int(
        value: object,
        *,
        default: int,
        minimum: int,
        maximum: int,
        name: str,
    ) -> int:
        try:
            parsed = int(value) if value not in (None, "") else default
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be an integer") from exc
        if parsed < minimum or parsed > maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")
        return parsed

    def _resolve_output_file(self, value: object, *, default_name: str) -> Path:
        text = str(value or "").strip()
        path = Path(text) if text else (
            self.root
            / ".agent_control"
            / "capability_os"
            / "outputs"
            / default_name
        )
        if not path.is_absolute():
            path = self.root / path
        resolved = path.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise PermissionError("Output path must stay inside the workspace") from exc
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved

    @staticmethod
    def _completed_process(
        argv: list[str],
        *,
        timeout: int,
        cwd: Path | None = None,
        text: bool = True,
    ) -> subprocess.CompletedProcess[Any]:
        kwargs: dict[str, Any] = {
            "cwd": str(cwd) if cwd else None,
            "capture_output": True,
            "timeout": timeout,
            "shell": False,
            "check": False,
            **hidden_windows_subprocess_kwargs(),
        }
        if text:
            kwargs.update(
                {
                    "text": True,
                    "encoding": "utf-8",
                    "errors": "replace",
                }
            )
        return subprocess.run(argv, **kwargs)

    def _execute_pdftotext(self, arguments: dict[str, Any]) -> dict[str, Any]:
        source = self._resolve_existing_file(
            arguments.get("path") or arguments.get("sourcePath")
        )
        if source.suffix.casefold() != ".pdf":
            raise ValueError("pdf.pdftotext requires a PDF file")
        descriptor = self.descriptor("pdf.pdftotext")
        first_page = self._bounded_int(
            arguments.get("firstPage"),
            default=1,
            minimum=1,
            maximum=1_000_000,
            name="firstPage",
        )
        last_page_value = arguments.get("lastPage")
        last_page = (
            self._bounded_int(
                last_page_value,
                default=first_page,
                minimum=first_page,
                maximum=1_000_000,
                name="lastPage",
            )
            if last_page_value not in (None, "")
            else None
        )
        max_chars = self._bounded_int(
            arguments.get("maxChars"),
            default=1_000_000,
            minimum=1_000,
            maximum=5_000_000,
            name="maxChars",
        )
        timeout = self._bounded_int(
            arguments.get("timeoutSeconds"),
            default=90,
            minimum=5,
            maximum=300,
            name="timeoutSeconds",
        )
        with tempfile.TemporaryDirectory(prefix="neyvia-pdf-") as temp_dir:
            # Some Windows Poppler builds use a narrow-character file API.
            # Keep the selected workspace path for scope and provenance, and
            # execute against a private ASCII-named copy of its actual bytes.
            staged_source = Path(temp_dir) / "source.pdf"
            shutil.copyfile(source, staged_source)
            output = Path(temp_dir) / "extracted.txt"
            argv = [
                descriptor.executable,
                "-enc",
                "UTF-8",
                "-f",
                str(first_page),
            ]
            if last_page is not None:
                argv.extend(["-l", str(last_page)])
            if bool(arguments.get("layout", True)):
                argv.append("-layout")
            argv.extend([str(staged_source), str(output)])
            completed = self._completed_process(argv, timeout=timeout)
            if completed.returncode != 0:
                return {
                    "ok": False,
                    "status": "failed",
                    "summary": "Poppler could not extract text from the PDF.",
                    "exitCode": completed.returncode,
                    "stderr": str(completed.stderr or "")[:20_000],
                }
            raw = output.read_text(encoding="utf-8", errors="replace")
        text = raw[:max_chars]
        pages = [page for page in raw.split("\f") if page.strip()]
        return {
            "ok": True,
            "status": "completed",
            "summary": f"Extracted {len(text):,} characters from {source.name}.",
            "sourcePath": str(source),
            "text": text,
            "characterCount": len(raw),
            "pageCountExtracted": len(pages),
            "firstPage": first_page,
            "lastPage": last_page,
            "truncated": len(raw) > len(text),
            "engine": "poppler-pdftotext",
        }

    def _pandoc_formats(
        self,
        executable: str,
        *,
        timeout: int,
    ) -> tuple[list[str], list[str]]:
        input_result = self._completed_process(
            [executable, "--list-input-formats"],
            timeout=timeout,
        )
        output_result = self._completed_process(
            [executable, "--list-output-formats"],
            timeout=timeout,
        )
        if input_result.returncode != 0 or output_result.returncode != 0:
            detail = str(input_result.stderr or output_result.stderr or "")[:8_000]
            raise RuntimeError(f"Pandoc format discovery failed: {detail}")
        input_formats = sorted(
            {
                line.strip().lower()
                for line in str(input_result.stdout or "").splitlines()
                if line.strip()
            }
        )
        output_formats = sorted(
            {
                line.strip().lower()
                for line in str(output_result.stdout or "").splitlines()
                if line.strip()
            }
        )
        if not input_formats or not output_formats:
            raise RuntimeError("Pandoc returned an empty format inventory")
        return input_formats, output_formats

    @classmethod
    def _pandoc_format_base(cls, value: object, *, name: str) -> str:
        text = str(value or "").strip().lower()
        if not text or not cls._PANDOC_FORMAT.fullmatch(text):
            raise ValueError(f"{name} is not a valid Pandoc format")
        base = re.split(r"[+-]", text, maxsplit=1)[0]
        if not base:
            raise ValueError(f"{name} is not a valid Pandoc format")
        return base

    @staticmethod
    def _pandoc_output_suffix(output_format: str) -> str:
        base = re.split(r"[+-]", output_format, maxsplit=1)[0]
        return {
            "asciidoc": ".adoc",
            "asciidoc_legacy": ".adoc",
            "beamer": ".tex",
            "commonmark": ".md",
            "commonmark_x": ".md",
            "context": ".tex",
            "docbook": ".xml",
            "docbook4": ".xml",
            "docbook5": ".xml",
            "docx": ".docx",
            "epub": ".epub",
            "epub2": ".epub",
            "epub3": ".epub",
            "fb2": ".fb2",
            "gfm": ".md",
            "html": ".html",
            "html4": ".html",
            "html5": ".html",
            "ipynb": ".ipynb",
            "jats": ".xml",
            "jats_archiving": ".xml",
            "jats_articleauthoring": ".xml",
            "jats_publishing": ".xml",
            "jira": ".txt",
            "json": ".json",
            "latex": ".tex",
            "man": ".man",
            "markdown": ".md",
            "markdown_github": ".md",
            "markdown_mmd": ".md",
            "markdown_phpextra": ".md",
            "markdown_strict": ".md",
            "mediawiki": ".wiki",
            "ms": ".ms",
            "native": ".native",
            "odt": ".odt",
            "opml": ".opml",
            "org": ".org",
            "pptx": ".pptx",
            "rst": ".rst",
            "rtf": ".rtf",
            "t2t": ".t2t",
            "texinfo": ".texi",
            "textile": ".textile",
            "typst": ".typ",
            "xwiki": ".xwiki",
            "zimwiki": ".zim",
        }.get(base, f".{base}")

    def _libreoffice_manifest(self) -> Any:
        registry = self.tool_manifests
        manifest = (
            getattr(registry, "tools", {}).get("tool.libreoffice")
            if registry is not None
            else None
        )
        if manifest is None:
            raise RuntimeError("LibreOffice managed-tool manifest is unavailable")
        return manifest

    def _libreoffice_profile_root(self) -> Path:
        manifest = self._libreoffice_manifest()
        value = str(manifest.metadata.get("profileRoot") or "").strip()
        if not value:
            raise RuntimeError("LibreOffice profileRoot is not configured")
        root = Path(value).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _libreoffice_pdfinfo(self) -> Path:
        manifest = self._libreoffice_manifest()
        value = str(manifest.metadata.get("pdfInfoPath") or "").strip()
        expected_hash = str(
            manifest.metadata.get("pdfInfoSha256") or ""
        ).strip().lower()
        if not value or not expected_hash:
            raise RuntimeError(
                "LibreOffice PDF verification requires a pinned pdfinfo path "
                "and SHA-256"
            )
        executable = Path(value).resolve()
        if not executable.is_file():
            raise FileNotFoundError(
                f"Pinned LibreOffice PDF verifier is missing: {executable}"
            )
        actual_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
        if not hmac.compare_digest(actual_hash, expected_hash):
            raise RuntimeError(
                "Pinned LibreOffice PDF verifier hash does not match the "
                "tool manifest"
            )
        return executable

    def _libreoffice_convert_file(
        self,
        *,
        source: Path,
        output_format: str,
        filter_name: str,
        staging_dir: Path,
        timeout: int,
    ) -> tuple[Path, subprocess.CompletedProcess[Any]]:
        descriptor = self.descriptor("document.libreoffice")
        profile = Path(
            tempfile.mkdtemp(
                prefix="job-",
                dir=self._libreoffice_profile_root(),
            )
        ).resolve()
        try:
            completed = self._completed_process(
                [
                    descriptor.executable,
                    f"-env:UserInstallation={profile.as_uri()}",
                    "--headless",
                    "--nologo",
                    "--nodefault",
                    "--nolockcheck",
                    "--nofirststartwizard",
                    "--convert-to",
                    f"{output_format}:{filter_name}",
                    "--outdir",
                    str(staging_dir),
                    str(source),
                ],
                timeout=timeout,
                cwd=source.parent,
            )
        finally:
            shutil.rmtree(profile, ignore_errors=True)
        if completed.returncode != 0:
            raise RuntimeError(
                "LibreOffice conversion failed with exit code "
                f"{completed.returncode}: "
                f"{str(completed.stderr or completed.stdout or '')[:20_000]}"
            )
        expected_name = f"{source.stem}.{output_format}".casefold()
        produced = next(
            (
                candidate
                for candidate in staging_dir.iterdir()
                if candidate.is_file()
                and candidate.name.casefold() == expected_name
            ),
            None,
        )
        if produced is None or produced.stat().st_size <= 0:
            raise RuntimeError(
                "LibreOffice reported success without the expected non-empty "
                f"{output_format} artifact"
            )
        return produced.resolve(), completed

    def _verify_pdf_with_pdfinfo(
        self,
        path: Path,
        *,
        timeout: int,
    ) -> dict[str, Any]:
        completed = self._completed_process(
            [str(self._libreoffice_pdfinfo()), str(path)],
            timeout=min(timeout, 120),
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "pdfinfo could not verify LibreOffice output: "
                f"{str(completed.stderr or completed.stdout or '')[:20_000]}"
            )
        match = re.search(
            r"(?im)^Pages:\s*(\d+)\s*$",
            str(completed.stdout or ""),
        )
        if match is None or int(match.group(1)) < 1:
            raise RuntimeError(
                "pdfinfo did not report a positive page count for "
                "LibreOffice output"
            )
        return {
            "status": "passed",
            "mode": "pdfinfo-page-count",
            "pageCount": int(match.group(1)),
            "pdfSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    def _verify_libreoffice_output(
        self,
        path: Path,
        *,
        family: str,
        timeout: int,
    ) -> dict[str, Any]:
        if path.suffix.casefold() == ".pdf":
            return self._verify_pdf_with_pdfinfo(path, timeout=timeout)
        verify_dir = Path(
            tempfile.mkdtemp(
                prefix=".neyvia-libreoffice-readback-",
                dir=path.parent,
            )
        ).resolve()
        try:
            rendered, _completed = self._libreoffice_convert_file(
                source=path,
                output_format="pdf",
                filter_name=self._LIBREOFFICE_PDF_FILTERS[family],
                staging_dir=verify_dir,
                timeout=timeout,
            )
            verification = self._verify_pdf_with_pdfinfo(
                rendered,
                timeout=timeout,
            )
            return {
                **verification,
                "mode": "libreoffice-roundtrip-pdf",
                "sourceReopened": True,
            }
        finally:
            shutil.rmtree(verify_dir, ignore_errors=True)

    def _execute_libreoffice(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        operation = str(arguments.get("operation") or "version").strip().lower()
        if operation not in {"version", "convert", "render_pdf"}:
            raise ValueError(f"Unsupported LibreOffice operation: {operation}")
        descriptor = self.descriptor("document.libreoffice")
        timeout = self._bounded_int(
            arguments.get("timeoutSeconds"),
            default=180,
            minimum=5,
            maximum=900,
            name="timeoutSeconds",
        )
        version_result = self._completed_process(
            [descriptor.executable, "--version"],
            timeout=min(timeout, 30),
        )
        if version_result.returncode != 0:
            raise RuntimeError(
                "LibreOffice version probe failed: "
                f"{str(version_result.stderr or version_result.stdout or '')[:20_000]}"
            )
        engine = str(
            version_result.stdout or version_result.stderr or "LibreOffice"
        ).splitlines()[0].strip()
        if operation == "version":
            return {
                "ok": True,
                "status": "completed",
                "summary": f"Verified managed runtime {engine}.",
                "engine": engine,
                "conversionFormats": sorted(
                    self._LIBREOFFICE_OUTPUT_FILTERS
                ),
                "renderFamilies": sorted(self._LIBREOFFICE_PDF_FILTERS),
                "profileIsolation": True,
                "managedInstallation": bool(
                    descriptor.metadata.get("managedInstallation")
                ),
            }

        source = self._resolve_existing_workspace_file(
            arguments.get("path") or arguments.get("sourcePath")
        )
        family = self._LIBREOFFICE_SOURCE_FAMILIES.get(
            source.suffix.casefold()
        )
        if family is None:
            raise ValueError(
                "LibreOffice input must be a supported Writer, Calc, Impress, "
                "or Draw document"
            )
        max_source_bytes = self._bounded_int(
            arguments.get("maxSourceBytes"),
            default=500 * 1024 * 1024,
            minimum=1_024,
            maximum=1_073_741_824,
            name="maxSourceBytes",
        )
        if source.stat().st_size > max_source_bytes:
            raise ValueError(
                f"Source exceeds the {max_source_bytes:,}-byte LibreOffice limit"
            )

        if operation == "render_pdf":
            output_format = "pdf"
            filter_name = self._LIBREOFFICE_PDF_FILTERS[family]
        else:
            output_format = str(
                arguments.get("outputFormat") or ""
            ).strip().lower()
            selected_filter = self._LIBREOFFICE_OUTPUT_FILTERS.get(
                output_format
            )
            if selected_filter is None:
                raise ValueError(
                    f"Unsupported LibreOffice output format: {output_format}"
                )
            target_family, filter_name = selected_filter
            if target_family != family:
                raise ValueError(
                    f"LibreOffice {family} sources cannot be converted to "
                    f"{output_format}"
                )
        default_name = (
            f"{source.stem}-{uuid.uuid4().hex[:8]}.{output_format}"
        )
        output = self._resolve_output_file(
            arguments.get("outputPath"),
            default_name=default_name,
        )
        if output.suffix.casefold() != f".{output_format}":
            raise ValueError(f"outputPath must end with .{output_format}")
        if output.exists():
            raise FileExistsError(
                f"LibreOffice will not overwrite an existing artifact: {output}"
            )
        staging_dir = Path(
            tempfile.mkdtemp(
                prefix=".neyvia-libreoffice-",
                dir=output.parent,
            )
        ).resolve()
        completed: subprocess.CompletedProcess[Any] | None = None
        try:
            produced, completed = self._libreoffice_convert_file(
                source=source,
                output_format=output_format,
                filter_name=filter_name,
                staging_dir=staging_dir,
                timeout=timeout,
            )
            verification = self._verify_libreoffice_output(
                produced,
                family=family,
                timeout=timeout,
            )
            os.replace(produced, output)
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        relation = (
            "rendered_from" if operation == "render_pdf" else "exported_from"
        )
        return {
            "ok": True,
            "status": "completed",
            "summary": (
                f"LibreOffice converted {source.name} to "
                f"{output.name} and verified "
                f"{verification['pageCount']} page(s)."
            ),
            "sourcePath": str(source),
            "outputPath": str(output),
            "sourceFamily": family,
            "outputFormat": output_format,
            "filter": filter_name,
            "bytes": output.stat().st_size,
            "sha256": digest,
            "mediaType": (
                mimetypes.guess_type(output.name)[0]
                or "application/octet-stream"
            ),
            "verification": verification,
            "profileIsolation": True,
            "engine": engine,
            "warnings": str(
                (completed.stderr if completed is not None else "") or ""
            )[:20_000],
            "artifacts": [
                {
                    "path": str(source),
                    "role": "source",
                    "kind": "document",
                },
                {
                    "path": str(output),
                    "role": "output",
                    "kind": "document",
                    "relation": relation,
                    "verifiedBy": verification["mode"],
                },
            ],
        }

    @staticmethod
    def _normalize_docx_list_markers(path: Path) -> dict[str, Any]:
        """Replace legacy Symbol/Wingdings bullets with portable Unicode glyphs."""

        numbering_name = "word/numbering.xml"
        word_namespace = (
            "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        )
        value_name = f"{{{word_namespace}}}val"
        with ZipFile(path, "r") as package:
            if numbering_name not in package.namelist():
                return {"bulletLevelsNormalized": 0}
            numbering = ET.fromstring(package.read(numbering_name))
            changed = 0
            glyphs = ("•", "◦", "▪")
            for level in numbering.findall(f".//{{{word_namespace}}}lvl"):
                number_format = level.find(f"{{{word_namespace}}}numFmt")
                if (
                    number_format is None
                    or number_format.get(value_name) != "bullet"
                ):
                    continue
                level_index = int(
                    level.get(f"{{{word_namespace}}}ilvl", "0") or "0"
                )
                level_text = level.find(f"{{{word_namespace}}}lvlText")
                if level_text is None:
                    level_text = ET.SubElement(
                        level,
                        f"{{{word_namespace}}}lvlText",
                    )
                level_text.set(value_name, glyphs[level_index % len(glyphs)])
                run_properties = level.find(f"{{{word_namespace}}}rPr")
                if run_properties is None:
                    run_properties = ET.SubElement(
                        level,
                        f"{{{word_namespace}}}rPr",
                    )
                run_fonts = run_properties.find(
                    f"{{{word_namespace}}}rFonts"
                )
                if run_fonts is None:
                    run_fonts = ET.SubElement(
                        run_properties,
                        f"{{{word_namespace}}}rFonts",
                    )
                for attribute in ("ascii", "hAnsi", "cs"):
                    run_fonts.set(
                        f"{{{word_namespace}}}{attribute}",
                        "Calibri",
                    )
                changed += 1
            if not changed:
                return {"bulletLevelsNormalized": 0}
            updated_numbering = ET.tostring(
                numbering,
                encoding="utf-8",
                xml_declaration=True,
            )
            temporary = path.with_name(
                f".{path.name}.{uuid.uuid4().hex}.normalized"
            )
            with ZipFile(
                temporary,
                "w",
                compression=ZIP_DEFLATED,
                compresslevel=9,
            ) as output:
                for item in package.infolist():
                    payload = (
                        updated_numbering
                        if item.filename == numbering_name
                        else package.read(item.filename)
                    )
                    output.writestr(item, payload)
        os.replace(temporary, path)
        return {
            "bulletLevelsNormalized": changed,
            "bulletEncoding": "unicode",
            "bulletFont": "Calibri",
        }

    @staticmethod
    def _pandoc_readback_format(output_format: str) -> str:
        base = re.split(r"[+-]", output_format, maxsplit=1)[0]
        return {
            "beamer": "latex",
            "commonmark_x": "commonmark",
            "docbook4": "docbook",
            "docbook5": "docbook",
            "epub2": "epub",
            "epub3": "epub",
            "html4": "html",
            "html5": "html",
            "jats_archiving": "jats",
            "jats_articleauthoring": "jats",
            "jats_publishing": "jats",
            "markdown_github": "markdown",
            "markdown_mmd": "markdown",
            "markdown_phpextra": "markdown",
            "markdown_strict": "markdown",
        }.get(base, base)

    def _execute_pandoc(self, arguments: dict[str, Any]) -> dict[str, Any]:
        operation = str(arguments.get("operation") or "convert").strip().lower()
        if operation not in {"formats", "inspect_ast", "convert"}:
            raise ValueError(f"Unsupported Pandoc operation: {operation}")
        descriptor = self.descriptor("document.pandoc")
        timeout = self._bounded_int(
            arguments.get("timeoutSeconds"),
            default=120,
            minimum=5,
            maximum=600,
            name="timeoutSeconds",
        )
        input_formats, output_formats = self._pandoc_formats(
            descriptor.executable,
            timeout=min(timeout, 60),
        )
        version_result = self._completed_process(
            [descriptor.executable, "--version"],
            timeout=min(timeout, 30),
        )
        engine = str(version_result.stdout or "pandoc").splitlines()[0].strip()

        if operation == "formats":
            return {
                "ok": True,
                "status": "completed",
                "summary": (
                    f"Pandoc exposes {len(input_formats)} input and "
                    f"{len(output_formats)} output formats."
                ),
                "inputFormats": input_formats,
                "outputFormats": output_formats,
                "engine": engine,
                "managedInstallation": bool(
                    descriptor.metadata.get("managedInstallation")
                ),
            }

        source = self._resolve_existing_workspace_file(
            arguments.get("path") or arguments.get("sourcePath")
        )
        max_source_bytes = self._bounded_int(
            arguments.get("maxSourceBytes"),
            default=100 * 1024 * 1024,
            minimum=1_024,
            maximum=500 * 1024 * 1024,
            name="maxSourceBytes",
        )
        if source.stat().st_size > max_source_bytes:
            raise ValueError(
                f"Source exceeds the {max_source_bytes:,}-byte Pandoc limit"
            )
        requested_input = str(arguments.get("inputFormat") or "").strip().lower()
        input_format = ""
        if requested_input:
            input_base = self._pandoc_format_base(
                requested_input,
                name="inputFormat",
            )
            if input_base not in input_formats:
                raise ValueError(
                    f"Pandoc build does not support input format {input_base!r}"
                )
            input_format = requested_input

        if operation == "inspect_ast":
            max_chars = self._bounded_int(
                arguments.get("maxChars"),
                default=5_000_000,
                minimum=1_000,
                maximum=5_000_000,
                name="maxChars",
            )
            argv = [descriptor.executable, "--sandbox", "--to=json"]
            if input_format:
                argv.append(f"--from={input_format}")
            argv.append(str(source))
            completed = self._completed_process(argv, timeout=timeout)
            if completed.returncode != 0:
                return {
                    "ok": False,
                    "status": "failed",
                    "summary": "Pandoc could not parse the source document.",
                    "exitCode": completed.returncode,
                    "stderr": str(completed.stderr or "")[:20_000],
                    "engine": engine,
                }
            raw = str(completed.stdout or "")
            if len(raw) > max_chars:
                return {
                    "ok": False,
                    "status": "output_limit_exceeded",
                    "summary": (
                        f"Pandoc AST contains {len(raw):,} characters, above "
                        f"the {max_chars:,}-character response limit."
                    ),
                    "astSha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                    "characterCount": len(raw),
                    "engine": engine,
                }
            try:
                ast = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError("Pandoc returned invalid JSON AST") from exc
            blocks = ast.get("blocks") if isinstance(ast, dict) else None
            return {
                "ok": True,
                "status": "completed",
                "summary": f"Parsed {source.name} into a valid Pandoc AST.",
                "sourcePath": str(source),
                "ast": ast,
                "astSha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                "characterCount": len(raw),
                "blockCount": len(blocks) if isinstance(blocks, list) else 0,
                "engine": engine,
                "artifacts": [
                    {
                        "path": str(source),
                        "role": "source",
                        "kind": "document",
                    }
                ],
            }

        requested_output = str(arguments.get("outputFormat") or "").strip().lower()
        output_base = self._pandoc_format_base(
            requested_output,
            name="outputFormat",
        )
        if output_base not in output_formats:
            raise ValueError(
                f"Pandoc build does not support output format {output_base!r}"
            )
        if output_base == "pdf":
            raise ValueError(
                "PDF production requires the separate document.publish-pdf "
                "operation so its external engine and render verifier are explicit"
            )
        default_name = (
            f"{source.stem}-{uuid.uuid4().hex[:8]}"
            f"{self._pandoc_output_suffix(requested_output)}"
        )
        output = self._resolve_output_file(
            arguments.get("outputPath"),
            default_name=default_name,
        )
        if output.exists():
            raise FileExistsError(
                f"Pandoc will not overwrite an existing artifact: {output}"
            )
        staging = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
        argv = [
            descriptor.executable,
            "--sandbox",
            f"--to={requested_output}",
            f"--output={staging}",
        ]
        if input_format:
            argv.append(f"--from={input_format}")
        if bool(arguments.get("standalone", True)):
            argv.append("--standalone")
        if bool(arguments.get("tableOfContents", False)):
            argv.append("--table-of-contents")
        if bool(arguments.get("numberSections", False)):
            argv.append("--number-sections")
        if bool(arguments.get("citeproc", False)):
            argv.append("--citeproc")
        if bool(arguments.get("failIfWarnings", False)):
            argv.append("--fail-if-warnings")

        bibliography_paths = arguments.get("bibliographyPaths") or []
        if not isinstance(bibliography_paths, list) or len(bibliography_paths) > 20:
            raise ValueError("bibliographyPaths must be a list with at most 20 files")
        for path_value in bibliography_paths:
            bibliography = self._resolve_existing_workspace_file(path_value)
            argv.append(f"--bibliography={bibliography}")
        csl_value = arguments.get("cslPath")
        if csl_value:
            argv.append(
                f"--csl={self._resolve_existing_workspace_file(csl_value)}"
            )
        reference_value = arguments.get("referenceDocPath")
        reference_document: Path | None = None
        applied_lua_filters: list[dict[str, str]] = []
        docx_normalization: dict[str, Any] = {}
        if reference_value:
            reference_document = self._resolve_existing_workspace_file(
                reference_value
            )
        elif output_base == "docx" and self.tool_manifests is not None:
            pandoc_manifest = self.tool_manifests.tools.get("tool.pandoc")
            default_reference = str(
                (
                    pandoc_manifest.metadata.get("defaultReferenceDoc")
                    if pandoc_manifest is not None
                    else ""
                )
                or ""
            ).strip()
            if default_reference:
                reference_candidate = Path(default_reference)
                if not reference_candidate.is_absolute():
                    reference_candidate = (
                        self.tool_manifests.lock_path.parent.parent
                        / reference_candidate
                    )
                reference_candidate = reference_candidate.resolve()
                if not reference_candidate.is_file():
                    raise FileNotFoundError(
                        f"Pinned Pandoc reference document is missing: "
                        f"{reference_candidate}"
                    )
                expected_reference_hash = str(
                    pandoc_manifest.metadata.get(
                        "defaultReferenceDocSha256"
                    )
                    or ""
                ).strip().lower()
                actual_reference_hash = hashlib.sha256(
                    reference_candidate.read_bytes()
                ).hexdigest()
                if (
                    not expected_reference_hash
                    or actual_reference_hash != expected_reference_hash
                ):
                    raise RuntimeError(
                        "Pinned Pandoc reference document hash does not match "
                        "the tool manifest"
                    )
                reference_document = reference_candidate
        if reference_document is not None:
            argv.append(f"--reference-doc={reference_document}")

        if output_base == "docx" and self.tool_manifests is not None:
            pandoc_manifest = self.tool_manifests.tools.get("tool.pandoc")
            configured_filters = (
                pandoc_manifest.metadata.get("defaultLuaFilters", [])
                if pandoc_manifest is not None
                else []
            )
            if not isinstance(configured_filters, list):
                raise RuntimeError("Pandoc defaultLuaFilters must be a list")
            for filter_entry in configured_filters:
                if not isinstance(filter_entry, dict):
                    raise RuntimeError(
                        "Each Pandoc default Lua filter must be an object"
                    )
                relative_path = str(filter_entry.get("path") or "").strip()
                expected_hash = str(
                    filter_entry.get("sha256") or ""
                ).strip().lower()
                if not relative_path or not expected_hash:
                    raise RuntimeError(
                        "Pinned Pandoc Lua filters require path and sha256"
                    )
                filter_path = Path(relative_path)
                if not filter_path.is_absolute():
                    filter_path = (
                        self.tool_manifests.lock_path.parent.parent / filter_path
                    )
                filter_path = filter_path.resolve()
                if not filter_path.is_file():
                    raise FileNotFoundError(
                        f"Pinned Pandoc Lua filter is missing: {filter_path}"
                    )
                actual_hash = hashlib.sha256(filter_path.read_bytes()).hexdigest()
                if actual_hash != expected_hash:
                    raise RuntimeError(
                        f"Pinned Pandoc Lua filter hash mismatch: {filter_path}"
                    )
                argv.append(f"--lua-filter={filter_path}")
                applied_lua_filters.append(
                    {"path": str(filter_path), "sha256": actual_hash}
                )

        for field_name, option in (("metadata", "--metadata"), ("variables", "--variable")):
            values = arguments.get(field_name) or {}
            if not isinstance(values, dict) or len(values) > 50:
                raise ValueError(f"{field_name} must be an object with at most 50 keys")
            for raw_key, raw_value in sorted(values.items()):
                key = str(raw_key).strip()
                if not self._PANDOC_KEY.fullmatch(key):
                    raise ValueError(f"Invalid Pandoc {field_name} key: {key!r}")
                if isinstance(raw_value, (dict, list)):
                    raise ValueError(
                        f"Pandoc {field_name} values must be scalar"
                    )
                argv.append(f"{option}={key}:{raw_value}")
        argv.append(str(source))

        try:
            completed = self._completed_process(
                argv,
                timeout=timeout,
                cwd=source.parent,
            )
            if completed.returncode != 0:
                return {
                    "ok": False,
                    "status": "failed",
                    "summary": "Pandoc document conversion failed.",
                    "exitCode": completed.returncode,
                    "stderr": str(completed.stderr or "")[:20_000],
                    "engine": engine,
                }
            if not staging.is_file() or staging.stat().st_size <= 0:
                raise RuntimeError("Pandoc reported success without a non-empty output")
            if output_base == "docx":
                docx_normalization = self._normalize_docx_list_markers(
                    staging
                )
            os.replace(staging, output)
        finally:
            if staging.exists():
                staging.unlink()

        readback_format = self._pandoc_readback_format(requested_output)
        verification: dict[str, Any]
        if readback_format in input_formats:
            readback = self._completed_process(
                [
                    descriptor.executable,
                    "--sandbox",
                    f"--from={readback_format}",
                    "--to=json",
                    str(output),
                ],
                timeout=timeout,
            )
            if readback.returncode != 0:
                return {
                    "ok": False,
                    "status": "verification_failed",
                    "summary": "Pandoc created the artifact but could not read it back.",
                    "outputPath": str(output),
                    "stderr": str(readback.stderr or "")[:20_000],
                    "engine": engine,
                }
            try:
                readback_ast = json.loads(str(readback.stdout or ""))
            except json.JSONDecodeError as exc:
                raise RuntimeError("Pandoc readback produced invalid JSON") from exc
            readback_blocks = (
                readback_ast.get("blocks")
                if isinstance(readback_ast, dict)
                else None
            )
            verification = {
                "status": "passed",
                "mode": "pandoc-readback",
                "inputFormat": readback_format,
                "blockCount": (
                    len(readback_blocks)
                    if isinstance(readback_blocks, list)
                    else 0
                ),
            }
        else:
            verification = {
                "status": "passed",
                "mode": "non-empty-hash",
                "readbackUnsupported": readback_format,
            }
        output_hash = hashlib.sha256(output.read_bytes()).hexdigest()
        return {
            "ok": True,
            "status": "completed",
            "summary": (
                f"Converted {source.name} to {requested_output} and verified "
                f"{output.name}."
            ),
            "sourcePath": str(source),
            "outputPath": str(output),
            "inputFormat": input_format or "auto",
            "outputFormat": requested_output,
            "bytes": output.stat().st_size,
            "sha256": output_hash,
            "mediaType": mimetypes.guess_type(output.name)[0]
            or "application/octet-stream",
            "verification": verification,
            "referenceDocPath": (
                str(reference_document) if reference_document is not None else ""
            ),
            "referenceDocSha256": (
                hashlib.sha256(reference_document.read_bytes()).hexdigest()
                if reference_document is not None
                else ""
            ),
            "luaFilters": applied_lua_filters,
            "normalization": docx_normalization,
            "warnings": str(completed.stderr or "")[:20_000],
            "engine": engine,
            "artifacts": [
                {
                    "path": str(source),
                    "role": "source",
                    "kind": "document",
                },
                {
                    "path": str(output),
                    "role": "output",
                    "kind": "document",
                    "relation": "exported_from",
                    "verifiedBy": verification["mode"],
                },
            ],
        }

    def _glm_manifest(self) -> Any:
        registry = self.tool_manifests
        manifest = (
            getattr(registry, "tools", {}).get("tool.glmocr")
            if registry is not None
            else None
        )
        if manifest is None:
            raise RuntimeError("GLM-OCR managed-tool manifest is unavailable")
        if not manifest.agent_ready:
            raise RuntimeError("GLM-OCR managed-tool manifest is not agent ready")
        return manifest

    def _glm_ollama_service(self) -> ManagedLocalService:
        manifest = self._glm_manifest()
        metadata = dict(manifest.metadata or {})
        serving = dict(metadata.get("optimizedServing") or {})
        executable = Path(str(manifest.install_path or "")).resolve()
        endpoint = str(serving.get("serverUrl") or "").rstrip("/")
        if endpoint != "http://127.0.0.1:11435":
            raise RuntimeError(
                "GLM-OCR Ollama endpoint must be the pinned loopback address"
            )
        model_files = dict(serving.get("modelFiles") or {})
        required_files: list[tuple[Path, str]] = []
        for value in model_files.values():
            if not isinstance(value, dict):
                raise RuntimeError("GLM-OCR modelFiles entries must be objects")
            required_files.append(
                (
                    Path(str(value.get("path") or "")).resolve(),
                    str(value.get("sha256") or ""),
                )
            )
        if len(required_files) < 4:
            raise RuntimeError("GLM-OCR requires all Ollama model files to be pinned")
        model_store = Path(str(serving.get("modelStore") or "")).resolve()
        spec = ManagedServiceSpec(
            service_id=str(serving.get("serviceId") or "glm-ocr.ollama"),
            executable=executable,
            executable_sha256=str(
                manifest.health.get("executableSha256") or ""
            ),
            argv=("serve",),
            state_root=Path(
                str(serving.get("stateRoot") or r"D:\Neyvia\state\services")
            ),
            health_url=f"{endpoint}/api/version",
            health_expected={"version": str(serving.get("ollamaVersion") or "")},
            identity_url=f"{endpoint}/api/tags",
            identity_value=str(serving.get("modelDigest") or ""),
            required_files=tuple(required_files),
            cwd=executable.parent,
            environment={
                "OLLAMA_HOST": "127.0.0.1:11435",
                "OLLAMA_MODELS": str(model_store),
                "OLLAMA_KEEP_ALIVE": str(
                    serving.get("keepAlive") or "5m"
                ),
                "OLLAMA_CONTEXT_LENGTH": str(
                    int(serving.get("contextLength") or 32768)
                ),
                "OLLAMA_MAX_LOADED_MODELS": "1",
                "OLLAMA_NO_CLOUD": "1",
            },
            startup_timeout_seconds=float(
                serving.get("startupTimeoutSeconds") or 60
            ),
            stop_timeout_seconds=30,
        )
        return ManagedLocalService(spec)

    @staticmethod
    @_proofs_b_checked("ocr-renderer")
    def _repair_glm_renderer_duplicate(
        value: str,
    ) -> tuple[str, dict[str, Any] | None]:
        marker = "\n```markdown\n"
        if marker not in value:
            return value, None
        before, after = value.split(marker, 1)
        expected = before.strip()
        repeated = after.lstrip()
        comparable = repeated[: min(128, len(repeated))]
        if len(comparable) < 32 or not expected.startswith(comparable):
            return value, None
        return expected, {
            "applied": True,
            "reason": (
                "The Ollama GLM-OCR renderer inserted a markdown fence followed "
                "by a verified duplicate of the emitted page prefix."
            ),
            "marker": marker.strip(),
            "removedCharacters": len(value) - len(expected),
        }

    @staticmethod
    @_proofs_b_checked("ocr-table")
    def _repair_glm_table_boundary(
        value: str,
    ) -> tuple[str, dict[str, Any] | None]:
        start = value.find("<table")
        end = value.find("</table>", start + 1)
        if start < 0 or end < 0:
            return value, None
        end += len("</table>")
        table = value[start:end]
        if "<tr" not in table or "<td" not in table:
            return value, None
        return table, {
            "applied": True,
            "reason": (
                "The table task produced one balanced HTML table followed by "
                "unrelated page text; only the verified table boundary is output."
            ),
            "boundary": "balanced-html-table",
            "removedCharacters": len(value) - len(table),
        }

    @staticmethod
    @_proofs_b_checked("ocr-formula")
    def _repair_glm_formula_boundary(
        value: str,
    ) -> tuple[str, dict[str, Any] | None]:
        start = value.find("$$")
        end = value.find("$$", start + 2)
        if start < 0 or end < 0:
            return value, None
        end += 2
        formula = value[start:end].strip()
        repeated = value[end:].strip()
        if len(formula) < 8 or not repeated.startswith(formula):
            return value, None
        return formula, {
            "applied": True,
            "reason": (
                "The formula task emitted one complete display-math block "
                "followed by an exact duplicate; only the first block is output."
            ),
            "boundary": "exact-duplicate-display-math",
            "removedCharacters": len(value) - len(formula),
        }

    def _run_glm_ollama(
        self,
        image_path: Path,
        *,
        prompt: str,
        max_new_tokens: int,
        timeout: int,
    ) -> dict[str, Any]:
        manifest = self._glm_manifest()
        serving = dict(manifest.metadata.get("optimizedServing") or {})
        endpoint = str(serving.get("serverUrl") or "").rstrip("/")
        model_name = str(serving.get("modelName") or "")
        if not model_name:
            raise RuntimeError("GLM-OCR Ollama modelName is not pinned")
        encoded_image = base64.b64encode(image_path.read_bytes()).decode("ascii")
        request_payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [encoded_image],
                }
            ],
            "stream": True,
            "keep_alive": str(serving.get("keepAlive") or "5m"),
            "options": {
                "temperature": 0,
                "num_predict": max_new_tokens,
            },
        }
        request = Request(
            f"{endpoint}/api/chat",
            data=json.dumps(request_payload).encode("utf-8"),
            headers={
                "accept": "application/x-ndjson",
                "content-type": "application/json",
            },
            method="POST",
        )
        raw_text = ""
        final_chunk: dict[str, Any] = {}
        renderer_repair: dict[str, Any] | None = None
        completion_reason = ""
        started = time.perf_counter()
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            for raw_line in response:
                if not raw_line.strip():
                    continue
                try:
                    chunk = json.loads(raw_line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise RuntimeError(
                        "GLM-OCR Ollama stream returned invalid NDJSON"
                    ) from exc
                if not isinstance(chunk, dict):
                    raise RuntimeError("GLM-OCR Ollama stream returned a non-object")
                if chunk.get("error"):
                    raise RuntimeError(f"GLM-OCR Ollama error: {chunk['error']}")
                message = chunk.get("message")
                if isinstance(message, dict):
                    raw_text += str(message.get("content") or "")
                if len(raw_text) > 20_000_000:
                    raise RuntimeError("GLM-OCR output exceeded the 20 MB limit")
                repaired, repair = self._repair_glm_renderer_duplicate(raw_text)
                if repair is not None:
                    renderer_repair = repair
                    completion_reason = "verified-renderer-duplicate-boundary"
                    raw_text = raw_text
                    final_text = repaired
                    break
                if chunk.get("done") is True:
                    final_chunk = chunk
                    completion_reason = str(chunk.get("done_reason") or "done")
                    final_text = raw_text
                    break
            else:
                if prompt == "Table Recognition:":
                    repaired, repair = self._repair_glm_table_boundary(raw_text)
                    if repair is not None:
                        renderer_repair = repair
                        completion_reason = "verified-html-table-boundary"
                        final_text = repaired
                    else:
                        raise RuntimeError(
                            "GLM-OCR table stream lacked a balanced table: "
                            f"{raw_text[:4000]}"
                        )
                elif prompt == "Formula Recognition:":
                    repaired, repair = self._repair_glm_formula_boundary(raw_text)
                    if repair is not None:
                        renderer_repair = repair
                        completion_reason = (
                            "verified-duplicate-display-math-boundary"
                        )
                        final_text = repaired
                    else:
                        raise RuntimeError(
                            "GLM-OCR formula stream lacked a verified formula "
                            f"boundary: {raw_text[:4000]}"
                        )
                else:
                    raise RuntimeError(
                        "GLM-OCR Ollama stream ended without completion: "
                        f"{raw_text[:4000]}"
                    )
        wall_seconds = time.perf_counter() - started
        if not completion_reason:
            raise RuntimeError("GLM-OCR Ollama stream did not establish completion")
        if completion_reason == "length" and renderer_repair is None:
            raise RuntimeError(
                "GLM-OCR reached maxNewTokens before a verified completion boundary"
            )
        return {
            "text": final_text,
            "rawText": raw_text,
            "rendererRepair": renderer_repair,
            "completionReason": completion_reason,
            "wallSeconds": round(wall_seconds, 3),
            "totalSeconds": (
                round(float(final_chunk["total_duration"]) / 1_000_000_000, 3)
                if final_chunk.get("total_duration") is not None
                else None
            ),
            "loadSeconds": (
                round(float(final_chunk["load_duration"]) / 1_000_000_000, 3)
                if final_chunk.get("load_duration") is not None
                else None
            ),
            "promptTokens": final_chunk.get("prompt_eval_count"),
            "generatedTokens": final_chunk.get("eval_count"),
        }

    def _execute_glm(self, arguments: dict[str, Any]) -> dict[str, Any]:
        operation = str(arguments.get("operation") or "extract_text").strip().lower()
        allowed = {
            "health",
            "service_status",
            "service_start",
            "service_stop",
            "service_restart",
            "extract_text",
            "recognize_formula",
            "recognize_table",
        }
        if operation not in allowed:
            raise ValueError(f"Unsupported GLM-OCR operation: {operation}")
        timeout = self._bounded_int(
            arguments.get("timeoutSeconds"),
            default=300,
            minimum=10,
            maximum=900,
            name="timeoutSeconds",
        )
        service = self._glm_ollama_service()
        if operation in {
            "service_status",
            "service_start",
            "service_stop",
            "service_restart",
        }:
            action = operation.removeprefix("service_")
            if action == "status":
                service_result = service.status()
            elif action == "start":
                service_result = service.start()
            elif action == "stop":
                service_result = service.stop()
            else:
                service_result = service.restart()
            return {
                "ok": True,
                "status": "completed",
                "summary": (
                    f"GLM-OCR Ollama service {action} completed with state "
                    f"{service_result.get('status')}."
                ),
                "action": action,
                "service": service_result,
                "healthy": bool(service_result.get("healthy")),
                "engine": "glm-ocr-ollama-bf16",
            }
        service_result = service.start()
        if not service_result.get("healthy"):
            raise RuntimeError("GLM-OCR service lacks verified model identity")
        manifest = self._glm_manifest()
        serving = dict(manifest.metadata.get("optimizedServing") or {})
        if operation == "health":
            return {
                "ok": True,
                "status": "completed",
                "summary": (
                    f"Verified GLM-OCR revision {serving.get('modelRevision')} "
                    f"through Ollama {serving.get('ollamaVersion')}."
                ),
                "modelRevision": serving.get("modelRevision"),
                "modelDigest": serving.get("modelDigest"),
                "ollamaVersion": serving.get("ollamaVersion"),
                "service": service_result,
                "engine": "glm-ocr-ollama-bf16",
            }

        source = self._resolve_existing_file(
            arguments.get("path") or arguments.get("sourcePath")
        )
        accepted_extensions = {
            ".pdf",
            ".png",
            ".jpg",
            ".jpeg",
            ".bmp",
            ".tif",
            ".tiff",
            ".webp",
        }
        if source.suffix.casefold() not in accepted_extensions:
            raise ValueError("GLM-OCR accepts PDF and supported raster images")
        max_pages = self._bounded_int(
            arguments.get("maxPages"),
            default=10,
            minimum=1,
            maximum=20,
            name="maxPages",
        )
        first_page = self._bounded_int(
            arguments.get("firstPage"),
            default=1,
            minimum=1,
            maximum=1_000_000,
            name="firstPage",
        )
        last_page = min(
            self._bounded_int(
                arguments.get("lastPage"),
                default=first_page + max_pages - 1,
                minimum=first_page,
                maximum=1_000_000,
                name="lastPage",
            ),
            first_page + max_pages - 1,
        )
        dpi = self._bounded_int(
            arguments.get("dpi"),
            default=200,
            minimum=96,
            maximum=300,
            name="dpi",
        )
        max_new_tokens = self._bounded_int(
            arguments.get("maxNewTokens"),
            default=4096,
            minimum=64,
            maximum=4096,
            name="maxNewTokens",
        )
        max_chars = self._bounded_int(
            arguments.get("maxChars"),
            default=2_000_000,
            minimum=1_000,
            maximum=5_000_000,
            name="maxChars",
        )
        prompt = {
            "extract_text": "Text Recognition:",
            "recognize_formula": "Formula Recognition:",
            "recognize_table": "Table Recognition:",
        }[operation]
        with tempfile.TemporaryDirectory(prefix="neyvia-glm-pages-") as temp_dir:
            paths = (
                self._tesseract_source_images(
                    source,
                    first_page=first_page,
                    last_page=last_page,
                    dpi=dpi,
                    timeout=min(timeout, 300),
                    temp_dir=Path(temp_dir),
                )
                if source.suffix.casefold() == ".pdf"
                else [source]
            )
            pages = []
            for offset, image_path in enumerate(paths[:max_pages]):
                result = self._run_glm_ollama(
                    image_path,
                    prompt=prompt,
                    max_new_tokens=max_new_tokens,
                    timeout=timeout,
                )
                pages.append(
                    {
                        "page": first_page + offset,
                        "text": result["text"],
                        "rawText": result["rawText"],
                        "rendererRepair": result["rendererRepair"],
                        "completionReason": result["completionReason"],
                        "wallSeconds": result["wallSeconds"],
                        "loadSeconds": result["loadSeconds"],
                        "promptTokens": result["promptTokens"],
                        "generatedTokens": result["generatedTokens"],
                    }
                )
        full_text = "\n\n".join(str(page["text"]) for page in pages)
        text = full_text[:max_chars]
        truncated = len(text) < len(full_text)
        if operation == "extract_text":
            payload = text.encode("utf-8")
            suffix = ".txt"
            default_name = f"{source.stem}-glm-ocr-{uuid.uuid4().hex[:8]}.txt"
            verification_mode = "glm-ocr-text-readback"
            artifact_role = "structured-text"
        else:
            document = {
                "schema": "neyvia.glm-ocr-recognition.v1",
                "sourcePath": str(source),
                "operation": operation,
                "modelRevision": serving.get("modelRevision"),
                "modelDigest": serving.get("modelDigest"),
                "pageCount": len(pages),
                "text": text,
                "truncated": truncated,
                "pages": pages,
            }
            payload = json.dumps(
                document,
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            suffix = ".json"
            default_name = (
                f"{source.stem}-{operation}-{uuid.uuid4().hex[:8]}.json"
            )
            verification_mode = "glm-ocr-structured-readback"
            artifact_role = "structured-recognition"
        output = self._resolve_output_file(
            arguments.get("outputPath"),
            default_name=default_name,
        )
        if output.suffix.casefold() != suffix:
            raise ValueError(f"GLM-OCR outputPath must end in {suffix}")
        if output.exists():
            raise FileExistsError(
                f"GLM-OCR will not overwrite an existing artifact: {output}"
            )
        temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, output)
        finally:
            if temporary.exists():
                temporary.unlink()
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        verification = {
            "status": "passed",
            "mode": verification_mode,
            "pageCount": len(pages),
            "nonEmpty": output.stat().st_size > 0,
            "modelIdentityVerified": True,
            "modelDigest": serving.get("modelDigest"),
        }
        return {
            "ok": True,
            "status": "completed",
            "summary": (
                f"GLM-OCR {operation} processed {len(pages)} page(s) from "
                f"{source.name} with verified model identity."
            ),
            "sourcePath": str(source),
            "text": text,
            "pages": pages,
            "pageCount": len(pages),
            "characterCount": len(full_text),
            "truncated": truncated,
            "outputPath": str(output),
            "bytes": output.stat().st_size,
            "sha256": digest,
            "latencyMs": round(
                sum(float(page["wallSeconds"]) for page in pages) * 1000,
                3,
            ),
            "backend": "ollama-chat-stream",
            "verification": verification,
            "engine": "glm-ocr-ollama-bf16",
            "artifacts": [
                {"path": str(source), "role": "source", "kind": "document"},
                {
                    "path": str(output),
                    "role": artifact_role,
                    "kind": "document",
                    "relation": "derived_from",
                    "verifiedBy": verification_mode,
                },
            ],
        }

    def _paddle_manifest(self) -> Any:
        registry = self.tool_manifests
        manifest = (
            getattr(registry, "tools", {}).get("tool.paddleocr")
            if registry is not None
            else None
        )
        if manifest is None:
            raise RuntimeError("PaddleOCR managed-tool manifest is unavailable")
        if not manifest.agent_ready:
            raise RuntimeError("PaddleOCR managed-tool manifest is not agent ready")
        return manifest

    def _paddle_runtime(self) -> tuple[Path, Path, Any]:
        manifest = self._paddle_manifest()
        executable = Path(str(manifest.install_path or "")).resolve()
        expected_hash = str(
            manifest.health.get("executableSha256") or ""
        ).strip().lower()
        if not executable.is_file() or not expected_hash:
            raise RuntimeError(
                "PaddleOCR requires a pinned Python executable and SHA-256"
            )
        actual_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
        if not hmac.compare_digest(actual_hash, expected_hash):
            raise RuntimeError(
                "Pinned PaddleOCR Python executable hash does not match its manifest"
            )
        worker = Path(__file__).with_name("paddle_ocr_worker.py").resolve()
        if not worker.is_file():
            raise RuntimeError(f"PaddleOCR worker is missing: {worker}")
        return executable, worker, manifest

    def _paddle_llama_service(self) -> ManagedLocalService:
        manifest = self._paddle_manifest()
        serving = dict(manifest.metadata.get("optimizedServing") or {})
        server_path = Path(str(serving.get("serverPath") or "")).resolve()
        model_path = Path(str(serving.get("modelPath") or "")).resolve()
        mmproj_path = Path(str(serving.get("mmprojPath") or "")).resolve()
        server_url = str(serving.get("serverUrl") or "").strip()
        if not server_url.endswith("/v1"):
            raise RuntimeError("PaddleOCR llama.cpp server URL must end in /v1")
        origin = server_url[:-3].rstrip("/")
        port_text = server_url.rsplit(":", 1)[-1].split("/", 1)[0]
        try:
            port = int(port_text)
        except ValueError as exc:
            raise RuntimeError("PaddleOCR llama.cpp server port is invalid") from exc
        alias = str(
            serving.get("modelAlias")
            or "neyvia-paddleocr-vl-1.6-b10098"
        ).strip()
        state_root = Path(
            str(
                serving.get("stateRoot")
                or r"D:\Neyvia\state\services"
            )
        ).resolve()
        spec = ManagedServiceSpec(
            service_id=str(
                serving.get("serviceId")
                or "paddleocr-vl.llama-cpp"
            ),
            executable=server_path,
            executable_sha256=str(
                serving.get("serverExecutableSha256") or ""
            ),
            argv=(
                "-m",
                str(model_path),
                "--mmproj",
                str(mmproj_path),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--temp",
                "0",
                "-ngl",
                "99",
                "-np",
                "1",
                "-c",
                "16384",
                "--alias",
                alias,
                "--no-webui",
                "--cors-origins",
                "localhost",
                "--sleep-idle-seconds",
                str(int(serving.get("sleepIdleSeconds") or 120)),
            ),
            state_root=state_root,
            health_url=f"{origin}/health",
            health_expected={"status": "ok"},
            identity_url=f"{server_url}/models",
            identity_value=alias,
            required_files=(
                (
                    model_path,
                    str(serving.get("modelSha256") or ""),
                ),
                (
                    mmproj_path,
                    str(serving.get("mmprojSha256") or ""),
                ),
            ),
            cwd=server_path.parent,
            startup_timeout_seconds=float(
                serving.get("startupTimeoutSeconds") or 90
            ),
            stop_timeout_seconds=30,
        )
        return ManagedLocalService(spec)

    def _run_paddle_worker(
        self,
        request: dict[str, Any],
        *,
        timeout: int,
    ) -> dict[str, Any]:
        executable, worker, manifest = self._paddle_runtime()
        metadata = manifest.metadata
        cache_path = Path(str(metadata.get("modelCache") or "")).resolve()
        if not cache_path.is_dir():
            raise RuntimeError(f"PaddleOCR model cache is missing: {cache_path}")
        with tempfile.TemporaryDirectory(prefix="neyvia-paddle-ocr-") as temp_dir:
            request_path = Path(temp_dir) / "request.json"
            response_path = Path(temp_dir) / "response.json"
            request_path.write_text(
                json.dumps(request, ensure_ascii=False),
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment.update(
                {
                    "PADDLE_PDX_CACHE_HOME": str(cache_path),
                    "FLAGS_allocator_strategy": "auto_growth",
                    "PYTHONUTF8": "1",
                }
            )
            completed = subprocess.run(
                [
                    str(executable),
                    str(worker),
                    "--request",
                    str(request_path),
                    "--response",
                    str(response_path),
                ],
                cwd=str(self.root),
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=False,
                check=False,
                **hidden_windows_subprocess_kwargs(),
            )
            if not response_path.is_file():
                raise RuntimeError(
                    "PaddleOCR worker did not produce a protocol response: "
                    f"{str(completed.stderr or completed.stdout or '')[:20_000]}"
                )
            if response_path.stat().st_size > 100 * 1024 * 1024:
                raise RuntimeError("PaddleOCR response exceeded the 100 MiB limit")
            try:
                response = json.loads(response_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError("PaddleOCR worker returned invalid JSON") from exc
            if completed.returncode != 0 or not response.get("ok"):
                raise RuntimeError(
                    f"{response.get('error') or 'PaddleOCR inference failed'}: "
                    f"{response.get('traceback') or str(completed.stderr or '')[:20_000]}"
                )
            response["workerStdout"] = str(completed.stdout or "")[-20_000:]
            response["workerStderr"] = str(completed.stderr or "")[-20_000:]
            return response

    def _execute_paddle(self, arguments: dict[str, Any]) -> dict[str, Any]:
        operation = str(arguments.get("operation") or "extract_text").strip().lower()
        if operation not in {
            "health",
            "service_status",
            "service_start",
            "service_stop",
            "service_restart",
            "extract_text",
            "extract_layout",
            "parse_document",
        }:
            raise ValueError(f"Unsupported PaddleOCR operation: {operation}")
        timeout = self._bounded_int(
            arguments.get("timeoutSeconds"),
            default=300,
            minimum=10,
            maximum=900,
            name="timeoutSeconds",
        )
        if operation in {
            "service_status",
            "service_start",
            "service_stop",
            "service_restart",
        }:
            service = self._paddle_llama_service()
            action = operation.removeprefix("service_")
            if action == "status":
                service_result = service.status()
            elif action == "start":
                service_result = service.start()
            elif action == "stop":
                service_result = service.stop()
            else:
                service_result = service.restart()
            healthy = bool(service_result.get("healthy"))
            return {
                "ok": True,
                "status": "completed",
                "summary": (
                    f"PaddleOCR-VL optimized service {action} completed with "
                    f"state {service_result.get('status')}."
                ),
                "action": action,
                "service": service_result,
                "healthy": healthy,
                "engine": "llama.cpp-paddleocr-vl-1.6",
            }
        if operation == "health":
            response = self._run_paddle_worker(
                {"operation": "health"},
                timeout=min(timeout, 60),
            )
            manifest = self._paddle_manifest()
            expected = dict(manifest.metadata.get("runtimeVersions") or {})
            mismatches = {
                key: {"expected": value, "actual": response.get(key)}
                for key, value in expected.items()
                if str(response.get(key)) != str(value)
            }
            if mismatches or not response.get("compiledWithCuda"):
                raise RuntimeError(
                    f"PaddleOCR runtime health mismatch: {mismatches}"
                )
            return {
                **response,
                "status": "completed",
                "summary": (
                    f"Verified PaddleOCR {response.get('paddleocr')} on "
                    f"{response.get('device')} with cuDNN "
                    f"{response.get('cudnnRuntime')}."
                ),
                "engine": "paddleocr-hybrid",
                "packageSha256": manifest.package_sha256,
                "optimizedService": self._paddle_llama_service().status(),
            }

        source = self._resolve_existing_file(
            arguments.get("path") or arguments.get("sourcePath")
        )
        accepted_extensions = {
            ".pdf",
            ".png",
            ".jpg",
            ".jpeg",
            ".bmp",
            ".tif",
            ".tiff",
            ".webp",
        }
        if source.suffix.casefold() not in accepted_extensions:
            raise ValueError("PaddleOCR accepts PDF and supported raster images")
        max_pages = self._bounded_int(
            arguments.get("maxPages"),
            default=10,
            minimum=1,
            maximum=50,
            name="maxPages",
        )
        first_page = self._bounded_int(
            arguments.get("firstPage"),
            default=1,
            minimum=1,
            maximum=1_000_000,
            name="firstPage",
        )
        last_page = min(
            self._bounded_int(
                arguments.get("lastPage"),
                default=first_page + max_pages - 1,
                minimum=first_page,
                maximum=1_000_000,
                name="lastPage",
            ),
            first_page + max_pages - 1,
        )
        dpi = self._bounded_int(
            arguments.get("dpi"),
            default=200,
            minimum=96,
            maximum=300,
            name="dpi",
        )
        max_chars = self._bounded_int(
            arguments.get("maxChars"),
            default=2_000_000,
            minimum=1_000,
            maximum=5_000_000,
            name="maxChars",
        )
        requested_engine = str(arguments.get("engine") or "").strip().lower()
        engine = requested_engine or (
            "paddleocr-vl-1.6"
            if operation == "parse_document"
            else "pp-ocrv6-medium"
        )
        if engine not in {"pp-ocrv6-medium", "paddleocr-vl-1.6"}:
            raise ValueError("engine must be pp-ocrv6-medium or paddleocr-vl-1.6")
        if operation == "parse_document" and engine != "paddleocr-vl-1.6":
            raise ValueError("parse_document requires paddleocr-vl-1.6")
        vl_backend = "paddle"
        vl_server_url = ""
        backend_fallback_reason = ""
        if engine == "paddleocr-vl-1.6":
            requested_backend = str(
                arguments.get("vlBackend") or "auto"
            ).strip().lower()
            if requested_backend not in {
                "auto",
                "paddle",
                "llama-cpp-server",
            }:
                raise ValueError(
                    "vlBackend must be auto, paddle, or llama-cpp-server"
                )
            serving = dict(
                self._paddle_manifest().metadata.get("optimizedServing") or {}
            )
            if requested_backend in {"auto", "llama-cpp-server"}:
                service = self._paddle_llama_service()
                try:
                    service_result = service.start()
                except Exception as exc:
                    if requested_backend == "llama-cpp-server":
                        raise
                    backend_fallback_reason = (
                        "Managed llama.cpp service could not start; used the "
                        f"verified local Paddle VLM backend instead: {exc}"
                    )
                else:
                    if not service_result.get("healthy"):
                        raise RuntimeError(
                            "Managed llama.cpp service started without healthy identity"
                        )
                    vl_backend = "llama-cpp-server"
                    vl_server_url = str(serving.get("serverUrl") or "")

        with tempfile.TemporaryDirectory(prefix="neyvia-paddle-pages-") as temp_dir:
            paths = (
                self._tesseract_source_images(
                    source,
                    first_page=first_page,
                    last_page=last_page,
                    dpi=dpi,
                    timeout=min(timeout, 300),
                    temp_dir=Path(temp_dir),
                )
                if source.suffix.casefold() == ".pdf"
                else [source]
            )
            response = self._run_paddle_worker(
                {
                    "operation": operation,
                    "sourcePath": str(source),
                    "paths": [str(path) for path in paths[:max_pages]],
                    "firstPage": first_page,
                    "engine": engine,
                    "device": str(arguments.get("device") or "gpu:0"),
                    "classifyOrientation": bool(
                        arguments.get("classifyOrientation", False)
                    ),
                    "unwarp": bool(arguments.get("unwarp", False)),
                    "textlineOrientation": bool(
                        arguments.get("textlineOrientation", False)
                    ),
                    "recognizeCharts": bool(
                        arguments.get("recognizeCharts", True)
                    ),
                    "recognizeSeals": bool(
                        arguments.get("recognizeSeals", True)
                    ),
                    "vlBackend": vl_backend,
                    "vlServerUrl": vl_server_url,
                    "vlMaxConcurrency": self._bounded_int(
                        arguments.get("vlMaxConcurrency"),
                        default=1,
                        minimum=1,
                        maximum=4,
                        name="vlMaxConcurrency",
                    ),
                },
                timeout=timeout,
            )

        full_text = str(response.get("text") or "")
        text = full_text[:max_chars]
        truncated = len(text) < len(full_text)
        pages = list(response.get("pages") or [])
        if operation == "extract_text":
            payload = text.encode("utf-8")
            suffix = ".txt"
            default_name = (
                f"{source.stem}-ppocr-{uuid.uuid4().hex[:8]}.txt"
            )
        else:
            document = {
                "schema": "neyvia.ocr-structured-document.v1",
                "sourcePath": str(source),
                "engine": engine,
                "pageCount": len(pages),
                "text": text,
                "truncated": truncated,
                "pages": pages,
            }
            payload = json.dumps(
                document,
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            suffix = ".json"
            default_name = (
                f"{source.stem}-{engine}-"
                f"{uuid.uuid4().hex[:8]}.json"
            )
        output = self._resolve_output_file(
            arguments.get("outputPath"),
            default_name=default_name,
        )
        if output.suffix.casefold() != suffix:
            raise ValueError(f"PaddleOCR outputPath must end in {suffix}")
        if output.exists():
            raise FileExistsError(
                f"PaddleOCR will not overwrite an existing artifact: {output}"
            )
        temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, output)
        finally:
            if temporary.exists():
                temporary.unlink()
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        verification = {
            "status": "passed",
            "mode": (
                "paddle-text-readback"
                if operation == "extract_text"
                else "paddle-structured-json-readback"
            ),
            "pageCount": len(pages),
            "nonEmpty": output.stat().st_size > 0,
            "runtimeHealthy": True,
        }
        return {
            "ok": True,
            "status": "completed",
            "summary": (
                f"{engine} processed {len(pages)} page(s) from {source.name} "
                "and the artifact passed readback verification."
            ),
            "sourcePath": str(source),
            "text": text,
            "pages": pages,
            "pageCount": len(pages),
            "characterCount": len(full_text),
            "truncated": truncated,
            "outputPath": str(output),
            "bytes": output.stat().st_size,
            "sha256": digest,
            "latencyMs": response.get("latencyMs"),
            "backend": response.get("backend"),
            "backendFallbackReason": backend_fallback_reason,
            "verification": verification,
            "engine": engine,
            "artifacts": [
                {
                    "path": str(source),
                    "role": "source",
                    "kind": (
                        "document"
                        if source.suffix.casefold() == ".pdf"
                        else "image"
                    ),
                },
                {
                    "path": str(output),
                    "role": (
                        "structured-text"
                        if operation == "extract_text"
                        else "structured-layout"
                    ),
                    "kind": "document",
                    "relation": "derived_from",
                    "verifiedBy": verification["mode"],
                },
            ],
            "workerWarnings": str(response.get("workerStderr") or "")[-20_000:],
        }

    def _tesseract_manifest(self) -> Any:
        registry = self.tool_manifests
        manifest = (
            getattr(registry, "tools", {}).get("tool.tesseract")
            if registry is not None
            else None
        )
        if manifest is None:
            raise RuntimeError("Tesseract managed-tool manifest is unavailable")
        return manifest

    def _tesseract_runtime(
        self,
        model: str = "fast",
        *,
        languages: str = "",
    ) -> tuple[Path, Path, Any]:
        manifest = self._tesseract_manifest()
        if not manifest.agent_ready:
            raise RuntimeError("Tesseract managed-tool manifest is not agent ready")
        executable = Path(str(manifest.install_path or "")).resolve()
        expected_executable_hash = str(
            manifest.health.get("executableSha256") or ""
        ).strip().lower()
        if not executable.is_file() or not expected_executable_hash:
            raise RuntimeError(
                "Tesseract requires a pinned executable path and SHA-256"
            )
        actual_executable_hash = hashlib.sha256(
            executable.read_bytes()
        ).hexdigest()
        if not hmac.compare_digest(
            actual_executable_hash,
            expected_executable_hash,
        ):
            raise RuntimeError(
                "Pinned Tesseract executable hash does not match the tool manifest"
            )

        normalized_model = str(model or "fast").strip().lower()
        model_profiles = manifest.metadata.get("modelProfiles") or {}
        profile = model_profiles.get(normalized_model)
        if not isinstance(profile, dict):
            raise ValueError(
                f"Unsupported Tesseract model profile: {normalized_model}"
            )
        tessdata = Path(str(profile.get("path") or "")).resolve()
        if not tessdata.is_dir():
            raise FileNotFoundError(
                f"Pinned Tesseract model directory is missing: {tessdata}"
            )
        expected_hashes = profile.get("modelSha256") or {}
        requested_languages = {
            item.strip()
            for item in str(languages or "").split("+")
            if item.strip()
        }
        for language in sorted(requested_languages):
            model_path = tessdata / f"{language}.traineddata"
            if not model_path.is_file():
                raise ValueError(
                    f"Language {language!r} is not installed for the "
                    f"{normalized_model} profile"
                )
            expected_hash = str(expected_hashes.get(language) or "").strip().lower()
            if expected_hash:
                actual_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
                if not hmac.compare_digest(actual_hash, expected_hash):
                    raise RuntimeError(
                        f"Pinned Tesseract {normalized_model}/{language} model "
                        "hash does not match the tool manifest"
                    )
        return executable, tessdata, manifest

    def _tesseract_pdf_renderer(self) -> Path:
        manifest = self._tesseract_manifest()
        value = str(manifest.metadata.get("pdfRendererPath") or "").strip()
        expected_hash = str(
            manifest.metadata.get("pdfRendererSha256") or ""
        ).strip().lower()
        if not value or not expected_hash:
            raise RuntimeError(
                "Tesseract PDF OCR requires a pinned pdftoppm path and SHA-256"
            )
        executable = Path(value).resolve()
        if not executable.is_file():
            raise FileNotFoundError(
                f"Pinned Tesseract PDF renderer is missing: {executable}"
            )
        actual_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
        if not hmac.compare_digest(actual_hash, expected_hash):
            raise RuntimeError(
                "Pinned Tesseract PDF renderer hash does not match the tool manifest"
            )
        return executable

    @staticmethod
    def _tesseract_output_suffix(output_format: str) -> str:
        return {
            "text": ".txt",
            "tsv": ".tsv",
            "hocr": ".hocr",
            "alto": ".xml",
            "pdf": ".pdf",
        }[output_format]

    def _tesseract_image(
        self,
        image_path: Path,
        *,
        executable: Path,
        tessdata: Path,
        language: str,
        psm: int,
        timeout: int,
        output_format: str,
    ) -> dict[str, Any]:
        descriptor = self.descriptor("ocr.tesseract")
        with tempfile.TemporaryDirectory(prefix="neyvia-ocr-page-") as temp_dir:
            output_base = Path(temp_dir) / "ocr"
            argv = [
                str(executable),
                str(image_path),
                str(output_base),
                "--tessdata-dir",
                str(tessdata),
                "-l",
                language,
                "--oem",
                "1",
                "--psm",
                str(psm),
            ]
            renderer_flags = {
                "tsv": "tessedit_create_tsv=1",
                "hocr": "tessedit_create_hocr=1",
                "alto": "tessedit_create_alto=1",
                "pdf": "tessedit_create_pdf=1",
            }
            if output_format in renderer_flags:
                argv.extend(["-c", renderer_flags[output_format]])
            completed = self._completed_process(argv, timeout=timeout)
            output_path = output_base.with_suffix(
                self._tesseract_output_suffix(output_format)
            )
            raw = output_path.read_bytes() if output_path.exists() else b""
        return {
            "ok": completed.returncode == 0 and bool(raw),
            "raw": raw,
            "stderr": str(completed.stderr or "")[:8_000],
            "exitCode": completed.returncode,
            "engine": str(descriptor.metadata.get("toolId") or "tool.tesseract"),
        }

    @staticmethod
    def _parse_tesseract_tsv(
        raw: bytes,
        *,
        page: int,
        max_words: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        decoded = raw.decode("utf-8", errors="replace")
        words: list[dict[str, Any]] = []
        truncated = False
        for row in csv.DictReader(decoded.splitlines(), delimiter="\t"):
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            if len(words) >= max_words:
                truncated = True
                break
            try:
                confidence = float(row.get("conf") or -1)
            except (TypeError, ValueError):
                confidence = -1.0
            words.append(
                {
                    "page": page,
                    "block": int(row.get("block_num") or 0),
                    "paragraph": int(row.get("par_num") or 0),
                    "line": int(row.get("line_num") or 0),
                    "word": int(row.get("word_num") or 0),
                    "text": text,
                    "confidence": confidence,
                    "bbox": {
                        "x": int(row.get("left") or 0),
                        "y": int(row.get("top") or 0),
                        "width": int(row.get("width") or 0),
                        "height": int(row.get("height") or 0),
                    },
                }
            )
        return words, truncated

    def _tesseract_source_images(
        self,
        source: Path,
        *,
        first_page: int,
        last_page: int,
        dpi: int,
        timeout: int,
        temp_dir: Path,
    ) -> list[Path]:
        image_extensions = {
            ".bmp",
            ".gif",
            ".jpg",
            ".jpeg",
            ".png",
            ".pnm",
            ".tif",
            ".tiff",
            ".webp",
        }
        if source.suffix.casefold() in image_extensions:
            return [source]
        if source.suffix.casefold() != ".pdf":
            raise ValueError("Tesseract requires a PDF or supported image")
        prefix = temp_dir / "page"
        render = self._completed_process(
            [
                str(self._tesseract_pdf_renderer()),
                "-f",
                str(first_page),
                "-l",
                str(last_page),
                "-r",
                str(dpi),
                "-png",
                str(source),
                str(prefix),
            ],
            timeout=timeout,
        )
        if render.returncode != 0:
            raise RuntimeError(
                "PDF pages could not be rendered for OCR: "
                f"{str(render.stderr or render.stdout or '')[:20_000]}"
            )
        return sorted(temp_dir.glob("page-*.png"))

    def _write_tesseract_output(
        self,
        payload: bytes,
        *,
        requested_path: object,
        default_name: str,
        suffix: str,
    ) -> Path:
        output = self._resolve_output_file(
            requested_path,
            default_name=default_name,
        )
        if output.suffix.casefold() != suffix.casefold():
            raise ValueError(f"outputPath must end with {suffix}")
        if output.exists():
            raise FileExistsError(
                f"Tesseract will not overwrite an existing artifact: {output}"
            )
        temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(payload)
            if temporary.stat().st_size <= 0:
                raise RuntimeError("Tesseract produced an empty artifact")
            os.replace(temporary, output)
        finally:
            if temporary.exists():
                temporary.unlink()
        return output

    def _execute_tesseract(self, arguments: dict[str, Any]) -> dict[str, Any]:
        operation = str(arguments.get("operation") or "extract_text").strip().lower()
        if operation not in {
            "version",
            "languages",
            "extract_text",
            "extract_layout",
            "export",
        }:
            raise ValueError(f"Unsupported Tesseract operation: {operation}")
        timeout = self._bounded_int(
            arguments.get("timeoutSeconds"),
            default=120,
            minimum=5,
            maximum=600,
            name="timeoutSeconds",
        )
        model = str(arguments.get("model") or "fast").strip().lower()
        if operation in {"version", "languages"}:
            executable, tessdata, manifest = self._tesseract_runtime(model)
            if operation == "version":
                completed = self._completed_process(
                    [str(executable), "--version"],
                    timeout=min(timeout, 60),
                )
                version_output = str(
                    completed.stdout or completed.stderr or ""
                ).strip()
                if completed.returncode != 0 or manifest.selected_version not in version_output:
                    raise RuntimeError(
                        "Tesseract version probe did not match the pinned release"
                    )
                return {
                    "ok": True,
                    "status": "completed",
                    "summary": (
                        f"Verified Tesseract {manifest.selected_version} with "
                        f"the {model} model profile."
                    ),
                    "version": manifest.selected_version,
                    "versionOutput": version_output[:20_000],
                    "executableSha256": manifest.health["executableSha256"],
                    "model": model,
                    "tessdataPath": str(tessdata),
                    "engine": f"tesseract-{manifest.selected_version}",
                }
            languages = sorted(
                path.stem for path in tessdata.glob("*.traineddata")
            )
            return {
                "ok": True,
                "status": "completed",
                "summary": (
                    f"Tesseract {model} profile exposes "
                    f"{len(languages)} language model(s)."
                ),
                "model": model,
                "languages": languages,
                "languageCount": len(languages),
                "tessdataPath": str(tessdata),
                "engine": f"tesseract-{manifest.selected_version}",
            }

        source = self._resolve_existing_file(
            arguments.get("path") or arguments.get("sourcePath")
        )
        language = str(arguments.get("language") or "eng").strip()
        if not re.fullmatch(r"[A-Za-z0-9_+.-]{1,80}", language):
            raise ValueError("language contains unsupported characters")
        psm = self._bounded_int(
            arguments.get("pageSegmentationMode"),
            default=3,
            minimum=0,
            maximum=13,
            name="pageSegmentationMode",
        )
        executable, tessdata, manifest = self._tesseract_runtime(
            model,
            languages=language,
        )
        max_chars = self._bounded_int(
            arguments.get("maxChars"),
            default=1_000_000,
            minimum=1_000,
            maximum=5_000_000,
            name="maxChars",
        )
        max_pages = self._bounded_int(
            arguments.get("maxPages"),
            default=25,
            minimum=1,
            maximum=100,
            name="maxPages",
        )
        workers = self._bounded_int(
            arguments.get("workers"),
            default=2,
            minimum=1,
            maximum=4,
            name="workers",
        )
        first_page = self._bounded_int(
            arguments.get("firstPage"),
            default=1,
            minimum=1,
            maximum=1_000_000,
            name="firstPage",
        )
        last_page = min(
            self._bounded_int(
                arguments.get("lastPage"),
                default=first_page + max_pages - 1,
                minimum=first_page,
                maximum=1_000_000,
                name="lastPage",
            ),
            first_page + max_pages - 1,
        )
        dpi = self._bounded_int(
            arguments.get("dpi"),
            default=200,
            minimum=96,
            maximum=400,
            name="dpi",
        )

        if operation == "export":
            if source.suffix.casefold() == ".pdf":
                raise ValueError(
                    "Tesseract export accepts one image; use OCRmyPDF for "
                    "searchable multi-page PDF production"
                )
            output_format = str(
                arguments.get("outputFormat") or "pdf"
            ).strip().lower()
            if output_format not in {"pdf", "hocr", "alto"}:
                raise ValueError(
                    "Tesseract export outputFormat must be pdf, hocr, or alto"
                )
            page = self._tesseract_image(
                source,
                executable=executable,
                tessdata=tessdata,
                language=language,
                psm=psm,
                timeout=timeout,
                output_format=output_format,
            )
            if not page["ok"]:
                return {
                    "ok": False,
                    "status": "failed",
                    "summary": "Tesseract image export failed.",
                    "exitCode": page["exitCode"],
                    "stderr": page["stderr"],
                    "engine": f"tesseract-{manifest.selected_version}",
                }
            suffix = self._tesseract_output_suffix(output_format)
            output = self._write_tesseract_output(
                page["raw"],
                requested_path=arguments.get("outputPath"),
                default_name=(
                    f"{source.stem}-ocr-{uuid.uuid4().hex[:8]}{suffix}"
                ),
                suffix=suffix,
            )
            verification: dict[str, Any] = {
                "status": "passed",
                "mode": f"tesseract-{output_format}-readback",
                "nonEmpty": output.stat().st_size > 0,
            }
            if output_format == "pdf":
                verification = self._verify_pdf_with_pdfinfo(
                    output,
                    timeout=timeout,
                )
                verification["mode"] = "tesseract-searchable-pdf-readback"
            elif output_format == "hocr":
                verification["htmlRoot"] = (
                    b"<html" in output.read_bytes().lower()
                )
                if not verification["htmlRoot"]:
                    raise RuntimeError("Tesseract hOCR readback failed")
            else:
                try:
                    root = ET.fromstring(output.read_bytes())
                except ET.ParseError as exc:
                    raise RuntimeError("Tesseract ALTO XML readback failed") from exc
                verification["xmlRoot"] = root.tag
            digest = hashlib.sha256(output.read_bytes()).hexdigest()
            return {
                "ok": True,
                "status": "completed",
                "summary": (
                    f"Tesseract exported {source.name} as "
                    f"{output_format.upper()} and verified the result."
                ),
                "sourcePath": str(source),
                "outputPath": str(output),
                "outputFormat": output_format,
                "bytes": output.stat().st_size,
                "sha256": digest,
                "verification": verification,
                "model": model,
                "language": language,
                "engine": f"tesseract-{manifest.selected_version}",
                "artifacts": [
                    {
                        "path": str(source),
                        "role": "source",
                        "kind": "image",
                    },
                    {
                        "path": str(output),
                        "role": "output",
                        "kind": "document",
                        "relation": "exported_from",
                        "verifiedBy": verification["mode"],
                    },
                ],
            }

        output_format = "text" if operation == "extract_text" else "tsv"
        max_words = self._bounded_int(
            arguments.get("maxWords"),
            default=100_000,
            minimum=100,
            maximum=500_000,
            name="maxWords",
        )
        with tempfile.TemporaryDirectory(prefix="neyvia-ocr-pdf-") as temp_dir:
            images = self._tesseract_source_images(
                source,
                first_page=first_page,
                last_page=last_page,
                dpi=dpi,
                timeout=timeout,
                temp_dir=Path(temp_dir),
            )
            with ThreadPoolExecutor(max_workers=min(workers, max(1, len(images)))) as pool:
                pages = list(
                    pool.map(
                        lambda path: self._tesseract_image(
                            path,
                            executable=executable,
                            tessdata=tessdata,
                            language=language,
                            psm=psm,
                            timeout=timeout,
                            output_format=output_format,
                        ),
                        images[:max_pages],
                    )
                )
        ok = bool(pages) and all(bool(page["ok"]) for page in pages)
        if not ok:
            return {
                "ok": False,
                "status": "failed",
                "summary": "One or more Tesseract OCR pages failed.",
                "pages": [
                    {
                        "page": index,
                        "exitCode": page["exitCode"],
                        "stderr": page["stderr"],
                    }
                    for index, page in enumerate(pages, start=first_page)
                ],
                "engine": f"tesseract-{manifest.selected_version}",
            }

        if operation == "extract_text":
            full_text = "\n\f\n".join(
                page["raw"].decode("utf-8", errors="replace")
                for page in pages
            )
            text = full_text[:max_chars]
            payload = text.encode("utf-8")
            suffix = ".txt"
            default_name = f"{source.stem}-ocr-{uuid.uuid4().hex[:8]}.txt"
            structured_pages = [
                {
                    "page": index,
                    "characterCount": len(
                        page["raw"].decode("utf-8", errors="replace")
                    ),
                }
                for index, page in enumerate(pages, start=first_page)
            ]
            word_count = None
            truncated = len(full_text) > len(text)
        else:
            all_words: list[dict[str, Any]] = []
            truncated = False
            structured_pages = []
            for index, page in enumerate(pages, start=first_page):
                remaining = max(0, max_words - len(all_words))
                words, page_truncated = self._parse_tesseract_tsv(
                    page["raw"],
                    page=index,
                    max_words=remaining,
                )
                all_words.extend(words)
                structured_pages.append(
                    {"page": index, "wordCount": len(words)}
                )
                truncated = truncated or page_truncated or len(all_words) >= max_words
            layout = {
                "schema": "neyvia.ocr-layout/v1",
                "sourcePath": str(source),
                "model": model,
                "language": language,
                "pages": structured_pages,
                "words": all_words,
                "truncated": truncated,
            }
            payload = json.dumps(
                layout,
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            suffix = ".json"
            default_name = (
                f"{source.stem}-ocr-layout-{uuid.uuid4().hex[:8]}.json"
            )
            text = " ".join(word["text"] for word in all_words)[:max_chars]
            full_text = text
            word_count = len(all_words)

        output = self._write_tesseract_output(
            payload,
            requested_path=arguments.get("outputPath"),
            default_name=default_name,
            suffix=suffix,
        )
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        verification = {
            "status": "passed",
            "mode": (
                "tesseract-text-readback"
                if operation == "extract_text"
                else "tesseract-layout-json-readback"
            ),
            "pageCount": len(pages),
            "nonEmpty": output.stat().st_size > 0,
        }
        return {
            "ok": True,
            "status": "completed",
            "summary": f"OCR processed {len(pages)} PDF page(s) from {source.name}.",
            "sourcePath": str(source),
            "text": text,
            "pages": structured_pages,
            "characterCount": len(full_text),
            "wordCount": word_count,
            "truncated": truncated,
            "firstPage": first_page,
            "lastPage": first_page + len(pages) - 1 if pages else None,
            "outputPath": str(output),
            "bytes": output.stat().st_size,
            "sha256": digest,
            "verification": verification,
            "model": model,
            "language": language,
            "engine": (
                f"pdftoppm+tesseract-{manifest.selected_version}"
                if source.suffix.casefold() == ".pdf"
                else f"tesseract-{manifest.selected_version}"
            ),
            "artifacts": [
                {
                    "path": str(source),
                    "role": "source",
                    "kind": (
                        "document"
                        if source.suffix.casefold() == ".pdf"
                        else "image"
                    ),
                },
                {
                    "path": str(output),
                    "role": (
                        "structured-text"
                        if operation == "extract_text"
                        else "structured-layout"
                    ),
                    "kind": "document",
                    "relation": "extracted_from",
                    "verifiedBy": verification["mode"],
                },
            ],
        }

    def _execute_marketplace_cosign(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        operation = str(arguments.get("operation") or "verify_signature").strip()
        if operation != "verify_signature":
            raise ValueError(f"Unsupported Cosign operation: {operation}")
        manifest = arguments.get("manifest")
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be an object")
        archive = self._resolve_existing_workspace_path(
            arguments.get("archivePath")
        )
        if not archive.is_file():
            raise ValueError("archivePath must be a file")
        marketplace = ModuleMarketplace(self.root)
        inspection = marketplace.inspect_package(manifest, archive)
        trust, binding = marketplace._publisher_trust_receipt(manifest)
        with tempfile.TemporaryDirectory(
            prefix="neyvia-cosign-verify-",
            dir=str(self.root),
        ) as temporary:
            signature = marketplace._signature_receipt(
                manifest,
                inspection,
                binding,
                Path(temporary),
            )
        passed = bool(
            inspection["safeToVerify"]
            and trust["passed"]
            and signature["passed"]
        )
        return {
            "ok": passed,
            "status": "completed" if passed else "blocked",
            "summary": (
                "Cosign verified the canonical manifest and trusted publisher."
                if passed
                else "Signature verification or publisher trust failed."
            ),
            "passed": passed,
            "inspection": inspection,
            "gateReceipts": [trust, signature],
        }

    def _execute_mesh_control(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        operation = str(arguments.get("operation") or "status").strip()
        mesh = MeshService(self.root)
        approval_receipt = arguments.get("approvalReceipt")
        if (
            approval_receipt is not None
            and not isinstance(approval_receipt, dict)
        ):
            raise TypeError("approvalReceipt must be an object")
        if operation == "status":
            refresh = arguments.get("refresh", False)
            if not isinstance(refresh, bool):
                raise TypeError("refresh must be a boolean")
            return mesh.snapshot(refresh=refresh)
        if operation == "probe_peer":
            return mesh.probe_peer(
                str(arguments.get("target") or ""),
                count=int(arguments.get("count") or 3),
                timeout_seconds=int(arguments.get("timeoutSeconds") or 5),
            )
        if operation == "list_services":
            return mesh.service_catalog()
        if operation == "advertise_service":
            service = arguments.get("service")
            if not isinstance(service, dict):
                raise ValueError("service must be an object")
            return mesh.advertise_service(
                service,
                approval_receipt=approval_receipt,
            )
        if operation == "revoke_service":
            return mesh.revoke_service(
                str(arguments.get("serviceId") or ""),
                approval_receipt=approval_receipt,
                revoked_by=str(arguments.get("revokedBy") or ""),
                reason=str(arguments.get("reason") or ""),
            )
        if operation == "migration_plan":
            return mesh.migration_plan()
        if operation == "identity_status":
            return mesh.identity_snapshot()
        if operation == "plan_identity_mutation":
            payload = arguments.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            return mesh.plan_identity_mutation(
                str(arguments.get("mutationOperation") or ""),
                device_ref=str(arguments.get("deviceRef") or ""),
                payload=payload,
                ttl_seconds=int(arguments.get("ttlSeconds") or 300),
            )
        if operation == "prepare_enrollment":
            return mesh.prepare_device_enrollment(
                device_label=str(arguments.get("deviceLabel") or ""),
                platform=str(arguments.get("platform") or ""),
                requested_by=str(arguments.get("requestedBy") or ""),
                ttl_seconds=int(arguments.get("ttlSeconds") or 900),
                approval_receipt=approval_receipt,
            )
        if operation == "stage_identity":
            provider_enrollment_receipt = arguments.get(
                "providerEnrollmentReceipt"
            )
            if not isinstance(provider_enrollment_receipt, dict):
                raise TypeError(
                    "providerEnrollmentReceipt must be an object"
                )
            return mesh.stage_device_identity(
                str(arguments.get("enrollmentRef") or ""),
                public_key_fingerprint=str(
                    arguments.get("publicKeyFingerprint") or ""
                ),
                provider_enrollment_receipt=(
                    provider_enrollment_receipt
                ),
                approval_receipt=approval_receipt,
            )
        if operation == "request_key_rotation":
            return mesh.request_key_rotation(
                str(arguments.get("deviceRef") or ""),
                requested_by=str(arguments.get("requestedBy") or ""),
                reason=str(arguments.get("reason") or ""),
                ttl_seconds=int(arguments.get("ttlSeconds") or 3600),
                approval_receipt=approval_receipt,
            )
        if operation == "transition_key_rotation":
            return mesh.transition_key_rotation(
                str(arguments.get("rotationRef") or ""),
                transition=str(arguments.get("transition") or ""),
                public_key_fingerprint=str(
                    arguments.get("publicKeyFingerprint") or ""
                ),
                approval_receipt=approval_receipt,
            )
        if operation == "revoke_device":
            return mesh.revoke_device(
                str(arguments.get("deviceRef") or ""),
                revoked_by=str(arguments.get("revokedBy") or ""),
                reason=str(arguments.get("reason") or ""),
                approval_receipt=approval_receipt,
            )
        if operation == "set_device_trust":
            return mesh.set_device_trust(
                str(arguments.get("deviceRef") or ""),
                trust_state=str(arguments.get("trustState") or ""),
                changed_by=str(arguments.get("changedBy") or ""),
                approval_receipt=approval_receipt,
            )
        if operation == "upsert_acl_rule":
            rule = arguments.get("rule")
            if not isinstance(rule, dict):
                raise ValueError("rule must be an object")
            return mesh.upsert_acl_rule(
                rule,
                approval_receipt=approval_receipt,
            )
        if operation == "evaluate_acl":
            return mesh.evaluate_acl(
                str(arguments.get("deviceRef") or ""),
                action=str(arguments.get("action") or ""),
                resource=str(arguments.get("resource") or ""),
            )
        if operation == "request_device_recovery":
            return mesh.request_device_recovery(
                str(arguments.get("deviceRef") or ""),
                requested_by=str(arguments.get("requestedBy") or ""),
                reason=str(arguments.get("reason") or ""),
                ttl_seconds=int(arguments.get("ttlSeconds") or 3600),
                approval_receipt=approval_receipt,
            )
        if operation == "transition_device_recovery":
            return mesh.transition_device_recovery(
                str(arguments.get("recoveryRef") or ""),
                transition=str(arguments.get("transition") or ""),
                approval_receipt=approval_receipt,
            )
        if operation == "identity_readiness":
            return mesh.identity_deployment_readiness()
        if operation == "enrollment_trust":
            return mesh.enrollment_and_trust_status()
        raise ValueError(f"Unsupported mesh operation: {operation}")

    def _execute_nearby_control(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        operation = str(
            arguments.get("operation") or "compatibility"
        ).strip()
        nearby = NearbySendService(self.root)
        if operation == "compatibility":
            return nearby.compatibility_snapshot()
        if operation == "discover":
            return nearby.discover(
                timeout_seconds=arguments.get("timeoutSeconds"),
            )
        if operation == "plan_send":
            paths = arguments.get("paths")
            if not isinstance(paths, list):
                raise ValueError("paths must be an array")
            return nearby.build_plan(
                paths,
                recipient_endpoint=str(
                    arguments.get("recipientEndpoint") or ""
                ),
                recipient_fingerprint=str(
                    arguments.get("recipientFingerprint") or ""
                ),
            )
        if operation == "send":
            plan = arguments.get("plan")
            if not isinstance(plan, dict):
                raise ValueError("plan must be an object")
            return nearby.send(
                plan,
                approved=bool(arguments.get("approved")),
            )
        raise ValueError(f"Unsupported nearby-send operation: {operation}")

    def _execute_folder_sync(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        operation = str(
            arguments.get("operation") or "compatibility"
        ).strip()
        sync = FolderSyncService(self.root)
        if operation == "compatibility":
            return sync.compatibility_snapshot()
        if operation == "health":
            return sync.health(
                include_folder_status=bool(
                    arguments.get("includeFolderStatus")
                ),
                refresh=bool(arguments.get("refresh")),
            )
        if operation == "plan_folder":
            device_ids = arguments.get("deviceIds")
            if not isinstance(device_ids, list):
                raise ValueError("deviceIds must be an array")
            ignore_patterns = arguments.get("ignorePatterns")
            if ignore_patterns is not None and not isinstance(
                ignore_patterns,
                list,
            ):
                raise ValueError("ignorePatterns must be an array")
            versioning = arguments.get("versioning")
            if versioning is not None and not isinstance(versioning, dict):
                raise ValueError("versioning must be an object")
            return sync.build_folder_plan(
                folder_id=str(arguments.get("folderId") or ""),
                path=str(arguments.get("path") or ""),
                device_ids=device_ids,
                label=str(arguments.get("label") or ""),
                folder_type=str(arguments.get("folderType") or "sendonly"),
                ignore_patterns=ignore_patterns,
                versioning=versioning,
            )
        if operation == "apply_folder":
            plan = arguments.get("plan")
            if not isinstance(plan, dict):
                raise ValueError("plan must be an object")
            return sync.apply_folder_plan(
                plan,
                approved=bool(arguments.get("approved")),
            )
        if operation == "pause":
            return sync.pause_folder(
                str(arguments.get("folderId") or ""),
                approved=bool(arguments.get("approved")),
            )
        if operation == "resume":
            return sync.resume_folder(
                str(arguments.get("folderId") or ""),
                approved=bool(arguments.get("approved")),
                approved_deletion_propagation=bool(
                    arguments.get("approvedDeletionPropagation")
                ),
            )
        if operation == "rescan":
            return sync.rescan_folder(
                str(arguments.get("folderId") or ""),
                sub_path=str(arguments.get("subPath") or ""),
                approved=bool(arguments.get("approved")),
            )
        if operation == "events":
            return sync.events(
                since=int(arguments.get("since") or 0),
                limit=int(arguments.get("limit") or 25),
                timeout_seconds=int(arguments.get("timeoutSeconds") or 1),
                disk_only=bool(arguments.get("diskOnly")),
            )
        if operation == "observe_conflict":
            local = arguments.get("local")
            remote = arguments.get("remote")
            if not isinstance(local, dict) or not isinstance(remote, dict):
                raise ValueError("local and remote must be objects")
            return sync.observe_conflict(
                folder_id=str(arguments.get("folderId") or ""),
                relative_path=str(arguments.get("relativePath") or ""),
                local=local,
                remote=remote,
                expected_revision=arguments.get("expectedRevision"),
            )
        if operation == "plan_conflict_resolution":
            conflict = sync.conflict_observation(
                str(arguments.get("conflictId") or "")
            )
            return sync.build_conflict_resolution_plan(
                conflict,
                resolution=str(arguments.get("resolution") or ""),
            )
        if operation == "authorize_conflict_resolution":
            approved = _required_boolean_argument(arguments, "approved")
            deletion_approved = _required_boolean_argument(
                arguments,
                "deletionApproved",
            )
            plan = sync.conflict_resolution_plan(
                str(arguments.get("planId") or "")
            )
            current_conflict = sync.conflict_observation(
                str(arguments.get("conflictId") or "")
            )
            return sync.authorize_conflict_resolution(
                plan,
                current_conflict=current_conflict,
                approved=approved,
                deletion_approved=deletion_approved,
                expected_revision=arguments.get("expectedRevision"),
            )
        if operation == "record_connectivity":
            online = _required_boolean_argument(arguments, "online")
            return sync.record_connectivity_observation(
                folder_id=str(arguments.get("folderId") or ""),
                online=online,
                device_id=str(arguments.get("deviceId") or ""),
                reason=str(arguments.get("reason") or ""),
                expected_revision=arguments.get("expectedRevision"),
            )
        if operation == "override":
            return sync.override_folder(
                str(arguments.get("folderId") or ""),
                confirmation=str(arguments.get("confirmation") or ""),
                approved=bool(arguments.get("approved")),
            )
        if operation == "revert":
            return sync.revert_folder(
                str(arguments.get("folderId") or ""),
                confirmation=str(arguments.get("confirmation") or ""),
                approved=bool(arguments.get("approved")),
            )
        raise ValueError(f"Unsupported folder-sync operation: {operation}")

    def _execute_encrypted_chat(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        operation = str(
            arguments.get("operation") or "compatibility"
        ).strip()
        chat = EncryptedChatService(self.root)
        if operation == "compatibility":
            return chat.compatibility_snapshot()
        if operation == "account_catalog":
            return chat.account_catalog()
        if operation == "lifecycle":
            return chat.lifecycle_snapshot(
                account_id=str(arguments.get("accountId") or ""),
            )
        if operation == "prepare_enrollment":
            return chat.prepare_device_enrollment(
                account_id=str(arguments.get("accountId") or ""),
                homeserver=str(arguments.get("homeserver") or ""),
                user_id=str(arguments.get("userId") or ""),
                device_id=str(arguments.get("deviceId") or ""),
                device_label=str(arguments.get("deviceLabel") or ""),
                platform=str(arguments.get("platform") or ""),
                session_ttl_seconds=(
                    int(arguments["sessionTtlSeconds"])
                    if arguments.get("sessionTtlSeconds") is not None
                    else None
                ),
            )
        if operation == "remove_device":
            return chat.request_device_removal(
                str(arguments.get("deviceRef") or ""),
                approved=bool(arguments.get("approved")),
            )
        if operation == "expire_sessions":
            return chat.expire_sessions()
        if operation == "recover_account":
            return chat.request_account_recovery(
                account_id=str(arguments.get("accountId") or ""),
                reason=str(arguments.get("reason") or ""),
                approved=bool(arguments.get("approved")),
            )
        if operation == "plan_message":
            attachments = arguments.get("attachments")
            if attachments is not None and not isinstance(attachments, list):
                raise ValueError("attachments must be an array")
            return chat.build_message_plan(
                account_id=str(arguments.get("accountId") or ""),
                room_ref=str(arguments.get("roomRef") or ""),
                actor=str(arguments.get("actor") or ""),
                message=str(arguments.get("message") or ""),
                attachments=attachments,
                format=str(arguments.get("format") or "text"),
            )
        if operation == "plan_self_chat":
            payloads = arguments.get("payloads")
            if not isinstance(payloads, list):
                raise ValueError("payloads must be an array")
            return chat.build_self_chat_plan(
                account_id=str(arguments.get("accountId") or ""),
                actor=str(arguments.get("actor") or ""),
                payloads=payloads,
            )
        if operation == "send":
            plan = arguments.get("plan")
            if not isinstance(plan, dict):
                raise ValueError("plan must be an object")
            return chat.send(
                plan,
                approved=bool(arguments.get("approved")),
            )
        if operation == "history":
            return chat.history(
                account_id=str(arguments.get("accountId") or ""),
                room_ref=str(arguments.get("roomRef") or ""),
                limit=int(arguments.get("limit") or 25),
            )
        raise ValueError(f"Unsupported encrypted-chat operation: {operation}")

    def _execute_secret_broker(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        operation = str(
            arguments.get("operation") or "compatibility"
        ).strip()
        broker = SecretBrokerService(self.root)
        if operation == "compatibility":
            return broker.compatibility_snapshot()
        if operation == "catalog":
            return broker.catalog()
        if operation == "plan_use":
            return broker.plan_use(
                handle_ref=str(arguments.get("handleRef") or ""),
                destination_id=str(arguments.get("destinationId") or ""),
                operation=str(arguments.get("destinationOperation") or ""),
                worker=str(arguments.get("worker") or ""),
                actor=str(arguments.get("actor") or ""),
                purpose=str(arguments.get("purpose") or ""),
                device_id=str(arguments.get("deviceId") or ""),
                session_id=str(arguments.get("sessionId") or ""),
                ttl_seconds=(
                    int(arguments["ttlSeconds"])
                    if arguments.get("ttlSeconds") is not None
                    else None
                ),
            )
        if operation == "use":
            plan = arguments.get("plan")
            if not isinstance(plan, dict):
                raise ValueError("plan must be an object")
            return broker.use(
                plan,
                approved=bool(arguments.get("approved")),
                approval=(
                    dict(arguments["approval"])
                    if isinstance(arguments.get("approval"), dict)
                    else None
                ),
            )
        if operation == "revoke":
            plan = arguments.get("plan")
            if not isinstance(plan, dict):
                raise ValueError("plan must be an object")
            return broker.revoke(
                plan,
                approved=bool(arguments.get("approved")),
                approval=(
                    dict(arguments["approval"])
                    if isinstance(arguments.get("approval"), dict)
                    else None
                ),
            )
        if operation == "revoke_subject":
            return broker.revoke_subject(
                subject_type=str(arguments.get("subjectType") or ""),
                subject_id=str(arguments.get("subjectId") or ""),
                actor=str(arguments.get("actor") or ""),
                reason_code=str(arguments.get("reasonCode") or ""),
                approved=bool(arguments.get("approved")),
                approval=(
                    dict(arguments["approval"])
                    if isinstance(arguments.get("approval"), dict)
                    else None
                ),
            )
        if operation == "revocation_status":
            return broker.revocation_status(
                device_id=str(arguments.get("deviceId") or ""),
                session_id=str(arguments.get("sessionId") or ""),
            )
        if operation == "audit":
            return broker.audit(limit=int(arguments.get("limit") or 50))
        raise ValueError(f"Unsupported secret-broker operation: {operation}")

    def _execute_p2p_cache(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        operation = str(
            arguments.get("operation") or "compatibility"
        ).strip()
        cache = P2PCacheService(self.root)
        if operation == "compatibility":
            return cache.compatibility_snapshot()
        if operation == "plan_import":
            return cache.plan_import(
                str(arguments.get("path") or ""),
                kind=str(arguments.get("kind") or "artifact"),
                pin=bool(arguments.get("pin", True)),
            )
        if operation == "import_object":
            plan = arguments.get("plan")
            if not isinstance(plan, dict):
                raise ValueError("plan must be an object")
            return cache.import_object(
                plan,
                approved=bool(arguments.get("approved")),
            )
        if operation == "plan_fetch":
            return cache.plan_fetch(
                str(arguments.get("objectHash") or ""),
                peer_ref=str(arguments.get("peerRef") or ""),
                kind=str(arguments.get("kind") or "artifact"),
                pin=bool(arguments.get("pin", True)),
            )
        if operation == "fetch_object":
            plan = arguments.get("plan")
            if not isinstance(plan, dict):
                raise ValueError("plan must be an object")
            return cache.fetch_object(
                plan,
                approved=bool(arguments.get("approved")),
            )
        if operation == "read_text":
            return cache.read_text(
                str(arguments.get("objectHash") or ""),
                offset=int(arguments.get("offset") or 0),
                length=(
                    int(arguments["length"])
                    if arguments.get("length") is not None
                    else None
                ),
                encoding=str(arguments.get("encoding") or "utf-8"),
            )
        if operation == "stats":
            return cache.stats()
        provider = P2PProviderService(self.root)
        if operation == "provider_status":
            return provider.status()
        if operation == "plan_publication":
            object_hashes = arguments.get("objectHashes")
            peer_refs = arguments.get("peerRefs")
            if not isinstance(object_hashes, list):
                raise ValueError("objectHashes must be an array")
            if not isinstance(peer_refs, list):
                raise ValueError("peerRefs must be an array")
            return provider.plan_publication(
                [str(value) for value in object_hashes],
                peer_refs=[str(value) for value in peer_refs],
                actor=str(arguments.get("actor") or "agent"),
            )
        if operation == "apply_publication":
            plan = arguments.get("plan")
            if not isinstance(plan, dict):
                raise ValueError("plan must be an object")
            return provider.apply_publication(
                plan,
                approved=bool(arguments.get("approved")),
            )
        if operation == "provider_receipts":
            return provider.receipts(
                limit=int(arguments.get("limit") or 50)
            )
        raise ValueError(f"Unsupported P2P-cache operation: {operation}")

    def _execute_marketplace_wasmtime(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        operation = str(arguments.get("operation") or "smoke_test_wasm").strip()
        if operation != "smoke_test_wasm":
            raise ValueError(f"Unsupported Wasmtime operation: {operation}")
        entrypoint = self._resolve_existing_workspace_path(
            arguments.get("entrypoint")
        )
        if not entrypoint.is_file() or entrypoint.suffix.casefold() != ".wasm":
            raise ValueError("entrypoint must be a workspace WebAssembly file")
        target = str(arguments.get("healthTarget") or "").strip()
        if not target or len(target) > 300:
            raise ValueError("healthTarget is required and must be bounded")
        timeout = self._bounded_int(
            arguments.get("timeoutSeconds"),
            default=10,
            minimum=1,
            maximum=120,
            name="timeoutSeconds",
        )
        descriptor = self.descriptor("marketplace.wasmtime")
        completed = subprocess.run(
            [
                descriptor.executable,
                "run",
                "-W",
                f"timeout={timeout}s",
                "-W",
                "fuel=10000000",
                "-W",
                "max-memory-size=268435456",
                "-W",
                "max-wasm-stack=2097152",
                "--invoke",
                target,
                str(entrypoint),
            ],
            cwd=str(entrypoint.parent),
            env={"PATH": os.environ.get("PATH", "")},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout + 5,
            shell=False,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
        passed = completed.returncode == 0
        return {
            "ok": passed,
            "status": "completed" if passed else "failed",
            "summary": (
                "Wasmtime health export completed in the zero-grant sandbox."
                if passed
                else "Wasmtime health export failed."
            ),
            "passed": passed,
            "returnCode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
            "entrypoint": str(entrypoint),
            "healthTarget": target,
            "filesystemAccess": "none",
            "inheritedEnvironment": [],
            "networkAccess": "none",
            "limits": {
                "timeoutSeconds": timeout,
                "fuel": 10_000_000,
                "maxMemoryBytes": 256 * 1024 * 1024,
                "maxWasmStackBytes": 2 * 1024 * 1024,
                "parentProcessTimeoutSeconds": timeout + 5,
            },
        }

    def _execute_marketplace_syft(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        operation = str(arguments.get("operation") or "generate_sbom").strip()
        if operation != "generate_sbom":
            raise ValueError(f"Unsupported Syft operation: {operation}")
        source = self._resolve_existing_workspace_path(arguments.get("path"))
        format_name = str(arguments.get("format") or "spdx-json").strip()
        if format_name not in {"spdx-json", "cyclonedx-json", "syft-json"}:
            raise ValueError("Unsupported SBOM format")
        output = self._resolve_output_file(
            arguments.get("outputPath"),
            default_name=f"{source.name}.{format_name}.json",
        )
        descriptor = self.descriptor("marketplace.syft")
        source_spec = (
            f"dir:{source}" if source.is_dir() else f"file:{source}"
        )
        completed = self._completed_process(
            [
                descriptor.executable,
                source_spec,
                "-o",
                f"{format_name}={output}",
            ],
            timeout=180,
            cwd=self.root,
        )
        if completed.returncode != 0 or not output.is_file():
            raise RuntimeError(
                f"Syft failed ({completed.returncode}): {completed.stderr[-2000:]}"
            )
        report = json.loads(output.read_text(encoding="utf-8"))
        packages = report.get("packages") if isinstance(report, dict) else []
        package_count = len(packages) if isinstance(packages, list) else 0
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        return {
            "ok": True,
            "status": "completed",
            "summary": f"Syft generated {format_name} with {package_count} packages.",
            "outputPath": str(output),
            "sha256": digest,
            "packageCount": package_count,
            "format": format_name,
            "artifacts": [
                {"path": str(source), "role": "source", "kind": "directory" if source.is_dir() else "file"},
                {
                    "path": str(output),
                    "role": "verification",
                    "kind": "sbom",
                    "relation": "cataloged_from",
                    "verifiedBy": "syft-json-readback",
                },
            ],
        }

    def _execute_marketplace_grype(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        operation = str(
            arguments.get("operation") or "scan_vulnerabilities"
        ).strip()
        if operation != "scan_vulnerabilities":
            raise ValueError(f"Unsupported Grype operation: {operation}")
        sbom = self._resolve_existing_workspace_path(arguments.get("sbomPath"))
        if not sbom.is_file():
            raise ValueError("sbomPath must be a file")
        threshold = str(arguments.get("failOn") or "high").casefold()
        if threshold not in {"negligible", "low", "medium", "high", "critical"}:
            raise ValueError("failOn is not a supported severity")
        descriptor = self.descriptor("marketplace.grype")
        environment = dict(os.environ)
        environment["GRYPE_DB_AUTO_UPDATE"] = (
            "true" if arguments.get("updateDatabase") is not False else "false"
        )
        completed = subprocess.run(
            [
                descriptor.executable,
                f"sbom:{sbom}",
                "-o",
                "json",
                "--fail-on",
                threshold,
            ],
            cwd=str(self.root),
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            shell=False,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
        try:
            report = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            report = {}
        matches = report.get("matches") if isinstance(report, dict) else []
        blocking = []
        for item in matches if isinstance(matches, list) else []:
            vulnerability = item.get("vulnerability") if isinstance(item, dict) else {}
            severity = str((vulnerability or {}).get("severity") or "unknown").casefold()
            if {
                "unknown": 0,
                "negligible": 1,
                "low": 2,
                "medium": 3,
                "high": 4,
                "critical": 5,
            }.get(severity, 0) >= {
                "negligible": 1,
                "low": 2,
                "medium": 3,
                "high": 4,
                "critical": 5,
            }[threshold]:
                blocking.append(item)
        database_result = self._completed_process(
            [descriptor.executable, "db", "status", "-o", "json"],
            timeout=30,
            cwd=self.root,
        )
        try:
            database = json.loads(database_result.stdout or "{}")
        except json.JSONDecodeError:
            database = {}
        passed = completed.returncode == 0 and not blocking
        if completed.returncode not in {0, 2}:
            raise RuntimeError(
                f"Grype failed ({completed.returncode}): {completed.stderr[-2000:]}"
            )
        return {
            "ok": passed,
            "status": "completed" if passed else "blocked",
            "summary": (
                "Grype found no vulnerabilities at the blocking threshold."
                if passed
                else f"Grype found {len(blocking)} blocking vulnerabilities."
            ),
            "passed": passed,
            "blockingFindingCount": len(blocking),
            "findings": blocking[:200],
            "database": database,
            "threshold": threshold,
        }

    def _execute_marketplace_defender(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        operation = str(arguments.get("operation") or "scan_malware").strip()
        if operation != "scan_malware":
            raise ValueError(f"Unsupported Defender operation: {operation}")
        target = self._resolve_existing_workspace_path(arguments.get("path"))
        timeout = self._bounded_int(
            arguments.get("timeoutSeconds"),
            default=300,
            minimum=1,
            maximum=600,
            name="timeoutSeconds",
        )
        descriptor = self.descriptor("marketplace.defender")
        completed = self._completed_process(
            [
                descriptor.executable,
                "-Scan",
                "-ScanType",
                "3",
                "-File",
                str(target),
                "-DisableRemediation",
            ],
            timeout=timeout,
            cwd=self.root,
        )
        passed = completed.returncode == 0
        scanner = Path(descriptor.executable)
        return {
            "ok": passed,
            "status": "completed" if passed else "blocked",
            "summary": (
                "Defender found no threats."
                if passed
                else "Defender did not clear the target."
            ),
            "passed": passed,
            "scannerPath": str(scanner),
            "scannerSha256": hashlib.sha256(scanner.read_bytes()).hexdigest(),
            "output": (completed.stdout + completed.stderr)[-4000:],
            "targetPath": str(target),
        }

    def _execute_android(self, arguments: dict[str, Any]) -> dict[str, Any]:
        operation = str(arguments.get("operation") or "devices").strip().lower()
        allowed = {
            "devices",
            "device_info",
            "packages",
            "logcat",
            "install",
            "launch",
            "tap",
            "swipe",
            "text",
            "screenshot",
            "list_avds",
            "start_emulator",
        }
        if operation not in allowed:
            raise ValueError(f"Unsupported Android operation: {operation}")
        if operation in self._ANDROID_MUTATIONS and not bool(arguments.get("approved")):
            return {
                "ok": False,
                "status": "approval_required",
                "summary": f"Android operation '{operation}' requires explicit approval.",
                "requiredPermission": "external.side_effect",
            }
        descriptor = self.descriptor("device.android")
        timeout = self._bounded_int(
            arguments.get("timeoutSeconds"),
            default=60,
            minimum=5,
            maximum=300,
            name="timeoutSeconds",
        )
        serial = str(arguments.get("serial") or "").strip()
        if serial and not self._ANDROID_IDENTIFIER.fullmatch(serial):
            raise ValueError("serial contains unsupported characters")
        prefix = [descriptor.executable]
        if serial:
            prefix.extend(["-s", serial])

        if operation in {"list_avds", "start_emulator"}:
            emulator = shutil.which("emulator")
            if not emulator:
                return {
                    "ok": False,
                    "status": "adapter_required",
                    "summary": "Android Emulator is not available on PATH.",
                }
            if operation == "list_avds":
                argv = [str(emulator), "-list-avds"]
            else:
                avd = str(arguments.get("avd") or "").strip()
                if not avd or not self._ANDROID_IDENTIFIER.fullmatch(avd):
                    raise ValueError("A valid avd is required")
                argv = [str(emulator), "-avd", avd, "-no-boot-anim"]
                process = subprocess.Popen(
                    argv,
                    cwd=str(self.root),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                    **hidden_windows_subprocess_kwargs(new_process_group=True),
                )
                return {
                    "ok": True,
                    "status": "started",
                    "summary": f"Started Android emulator AVD '{avd}'.",
                    "operation": operation,
                    "avd": avd,
                    "pid": process.pid,
                }
        elif operation == "devices":
            argv = [descriptor.executable, "devices", "-l"]
        elif operation == "device_info":
            argv = prefix + ["shell", "getprop"]
        elif operation == "packages":
            argv = prefix + ["shell", "pm", "list", "packages", "-3"]
        elif operation == "logcat":
            lines = self._bounded_int(
                arguments.get("lines"),
                default=300,
                minimum=1,
                maximum=5_000,
                name="lines",
            )
            argv = prefix + ["logcat", "-d", "-t", str(lines)]
        elif operation == "install":
            apk = self._resolve_existing_file(arguments.get("path"))
            if apk.suffix.casefold() != ".apk":
                raise ValueError("Android install requires an APK file")
            argv = prefix + ["install", "-r", str(apk)]
        elif operation == "launch":
            package = str(arguments.get("package") or "").strip()
            if not package or not self._ANDROID_IDENTIFIER.fullmatch(package):
                raise ValueError("A valid package is required")
            activity = str(arguments.get("activity") or "").strip()
            if activity and not self._ANDROID_IDENTIFIER.fullmatch(activity):
                raise ValueError("activity contains unsupported characters")
            argv = (
                prefix + ["shell", "am", "start", "-n", f"{package}/{activity}"]
                if activity
                else prefix
                + [
                    "shell",
                    "monkey",
                    "-p",
                    package,
                    "-c",
                    "android.intent.category.LAUNCHER",
                    "1",
                ]
            )
        elif operation in {"tap", "swipe"}:
            coordinate_names = ("x", "y") if operation == "tap" else ("x1", "y1", "x2", "y2")
            coordinates = [
                self._bounded_int(
                    arguments.get(name),
                    default=0,
                    minimum=0,
                    maximum=100_000,
                    name=name,
                )
                for name in coordinate_names
            ]
            argv = prefix + ["shell", "input", operation, *map(str, coordinates)]
        elif operation == "text":
            value = str(arguments.get("value") or "")
            if (
                not value
                or len(value) > 2_000
                or not re.fullmatch(r"[A-Za-z0-9 .,_@%+\-:/'()]+", value)
            ):
                raise ValueError(
                    "Android input text must contain 1-2000 safe single-line characters"
                )
            argv = prefix + ["shell", "input", "text", value.replace(" ", "%s")]
        else:
            output = self._resolve_output_file(
                arguments.get("outputPath"),
                default_name=f"android-{int(time.time())}.png",
            )
            completed = self._completed_process(
                prefix + ["exec-out", "screencap", "-p"],
                timeout=timeout,
                text=False,
            )
            if completed.returncode == 0:
                output.write_bytes(bytes(completed.stdout or b""))
            return {
                "ok": completed.returncode == 0,
                "status": "completed" if completed.returncode == 0 else "failed",
                "summary": (
                    f"Saved Android screenshot to {output}."
                    if completed.returncode == 0
                    else "Android screenshot failed."
                ),
                "operation": operation,
                "outputPath": str(output) if completed.returncode == 0 else "",
                "sizeBytes": output.stat().st_size if output.exists() else 0,
                "stderr": bytes(completed.stderr or b"")[:20_000].decode(
                    "utf-8", errors="replace"
                ),
            }
        completed = self._completed_process(argv, timeout=timeout)
        stdout = str(completed.stdout or "")[:1_000_000]
        stderr = str(completed.stderr or "")[:100_000]
        return {
            "ok": completed.returncode == 0,
            "status": "completed" if completed.returncode == 0 else "failed",
            "summary": (
                f"Android operation '{operation}' completed."
                if completed.returncode == 0
                else f"Android operation '{operation}' failed."
            ),
            "operation": operation,
            "exitCode": completed.returncode,
            "output": stdout,
            "stderr": stderr,
            "outputTruncated": len(str(completed.stdout or "")) > len(stdout),
        }

    def _inspect_artifact(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_existing_file(arguments.get("path"))
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        stat = path.stat()
        return {
            "ok": True,
            "status": "completed",
            "summary": f"Inspected {path.name}",
            "path": str(path),
            "name": path.name,
            "mediaType": media_type,
            "sizeBytes": stat.st_size,
            "modifiedNs": stat.st_mtime_ns,
            "sha256": digest.hexdigest(),
        }

    def _extract_text(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_existing_file(arguments.get("path"))
        limit = max(1, min(int(arguments.get("maxBytes") or 1_000_000), 4_000_000))
        raw = path.read_bytes()[:limit]
        encoding = str(arguments.get("encoding") or "utf-8")
        text = raw.decode(encoding, errors="replace")
        return {
            "ok": True,
            "status": "completed",
            "summary": f"Extracted {len(text)} characters from {path.name}",
            "path": str(path),
            "text": text,
            "truncated": path.stat().st_size > limit,
            "bytesRead": len(raw),
            "contentSha256": hashlib.sha256(raw).hexdigest(),
        }
