"""Permissioned Syncthing control with scoped checksums and safe activation."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator

from .capability_contracts import utc_now
from .durability import atomic_write_json
from .proofs_b_adapters import checked as _proofs_b_checked


FOLDER_SYNC_PLAN_SCHEMA = "neyvia.folder-sync-plan/v1"
FOLDER_SYNC_RECEIPT_SCHEMA = "neyvia.folder-sync-receipt/v1"
FOLDER_SYNC_CONFLICT_SCHEMA = "neyvia.folder-sync-conflict/v1"
FOLDER_SYNC_CONFLICT_PLAN_SCHEMA = "neyvia.folder-sync-conflict-plan/v1"
FOLDER_SYNC_CONNECTIVITY_SCHEMA = "neyvia.folder-sync-connectivity/v1"
FOLDER_SYNC_AUTH_TRANSACTION_SCHEMA = (
    "neyvia.folder-sync-authorization-transaction/v1"
)
_FOLDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_DEVICE_ID_PATTERN = re.compile(r"^[A-Z0-9-]{20,80}$")
_DEVICE_REF_PATTERN = re.compile(r"^device-[a-f0-9]{16}$")
_CONTENT_HASH_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")
_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:api[_-]?key|authorization|cookie|credential|password|"
    r"private[_-]?key|secret|token)",
    re.IGNORECASE,
)
_SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(?:basic|bearer)\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(
        r"(?i)\b(?:api[_ -]?key|authorization|cookie|credential|password|"
        r"private[_ -]?key|secret|token)\s*[:=]\s*\S+"
    ),
    re.compile(
        r"(?i)([?&](?:api[_-]?key|authorization|credential|password|"
        r"secret|token)=)[^&#\s]+"
    ),
)
_LOCAL_LOCKS_GUARD = threading.Lock()
_LOCAL_LOCKS: dict[str, threading.Lock] = {}


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


def _redact_text(value: str) -> str:
    result = str(value)
    for pattern in _SENSITIVE_TEXT_PATTERNS:
        result = pattern.sub(_REDACTED, result)
    return result


def _redact_value(value: object) -> object:
    """Return a persistable copy with secret-bearing fields removed."""

    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, item in value.items():
            normalized_key = str(key)
            result[normalized_key] = (
                _REDACTED
                if _SENSITIVE_KEY_PATTERN.search(normalized_key)
                else _redact_value(item)
            )
        return result
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return copy.deepcopy(value)


@contextmanager
def _exclusive_file_lock(
    path: Path,
    *,
    timeout_seconds: float = 5.0,
) -> Iterator[None]:
    """Hold a same-host process and cross-process lock for one relationship."""

    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    key = str(target)
    with _LOCAL_LOCKS_GUARD:
        local_lock = _LOCAL_LOCKS.setdefault(key, threading.Lock())
    if not local_lock.acquire(timeout=max(0.1, timeout_seconds)):
        raise TimeoutError("Timed out waiting for folder-sync relationship lock")
    handle = None
    locked = False
    deadline = time.monotonic() + max(0.1, timeout_seconds)
    try:
        handle = target.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        while not locked:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(
                        handle.fileno(),
                        fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
                locked = True
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "Timed out waiting for cross-process folder-sync lock"
                    ) from exc
                time.sleep(0.025)
        yield
    finally:
        if locked and handle is not None:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        if handle is not None:
            handle.close()
        local_lock.release()


class FolderSyncService:
    """Neyvia's credential-hiding, fail-closed Syncthing REST client."""

    def __init__(
        self,
        root: str | Path,
        *,
        config_path: str | Path | None = None,
        credential_resolver: Callable[[str], str] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        project_root = Path(__file__).resolve().parents[2]
        selected = Path(
            config_path
            or self.root / "config" / "neyvia_folder_sync.json"
        )
        if not selected.is_file():
            selected = project_root / "config" / "neyvia_folder_sync.json"
        if not selected.is_file():
            raise FileNotFoundError(selected)
        self.config_path = selected.resolve()
        self.config = json.loads(
            self.config_path.read_text(encoding="utf-8")
        )
        self._credential_resolver = (
            credential_resolver or self._resolve_environment_credential
        )
        self.plan_root = (
            self.root / ".agent_control" / "folder_sync" / "plans"
        )
        self.receipt_root = (
            self.root / ".agent_control" / "folder_sync" / "receipts"
        )
        self.conflict_root = (
            self.root / ".agent_control" / "folder_sync" / "conflicts"
        )
        self.connectivity_root = (
            self.root / ".agent_control" / "folder_sync" / "connectivity"
        )
        self.lock_root = (
            self.root / ".agent_control" / "folder_sync" / "locks"
        )
        self.transaction_root = (
            self.root / ".agent_control" / "folder_sync" / "transactions"
        )
        self.transaction_archive_root = self.transaction_root / "archive"
        self._cache_lock = threading.RLock()
        self._health_cache: tuple[float, dict[str, Any]] | None = None
        self._validate_endpoint()

    @property
    def transport(self) -> dict[str, Any]:
        value = self.config.get("transport")
        return dict(value) if isinstance(value, dict) else {}

    @property
    def policy(self) -> dict[str, Any]:
        value = self.config.get("policy")
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _resolve_environment_credential(reference: str) -> str:
        prefix = "env:"
        if not reference.startswith(prefix):
            raise RuntimeError(
                "Syncthing apiKeyRef must resolve through an approved secret "
                "provider; only env: references are available in this slice."
            )
        variable = reference[len(prefix) :].strip()
        if not variable:
            raise RuntimeError("Syncthing API-key environment reference is empty")
        value = os.environ.get(variable, "").strip()
        if not value:
            raise RuntimeError(
                f"Syncthing credential reference {reference} is not available"
            )
        return value

    def _validate_endpoint(self) -> None:
        parsed = urllib.parse.urlparse(
            str(self.transport.get("endpoint") or "")
        )
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Syncthing endpoint must use HTTP or HTTPS")
        if parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError(
                "Syncthing REST control is loopback-only; remote access belongs "
                "behind Neyvia's authenticated mesh service."
            )
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Syncthing endpoint must not contain credentials")

    def _api_key(self) -> str:
        reference = str(self.transport.get("apiKeyRef") or "")
        value = self._credential_resolver(reference)
        if not value:
            raise RuntimeError("Syncthing API key resolver returned no credential")
        return value

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, object] | None = None,
        payload: object | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        endpoint = str(self.transport.get("endpoint") or "").rstrip("/")
        encoded_query = urllib.parse.urlencode(
            {
                str(key): str(value)
                for key, value in (query or {}).items()
                if value is not None and str(value) != ""
            }
        )
        url = f"{endpoint}{path}"
        if encoded_query:
            url = f"{url}?{encoded_query}"
        body = None
        headers = {
            "Accept": "application/json",
            "X-API-Key": self._api_key(),
            "User-Agent": "Neyvia-Folder-Sync/1",
        }
        if payload is not None:
            body = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=method.upper(),
        )
        timeout = max(
            0.2,
            min(
                float(
                    timeout_seconds
                    if timeout_seconds is not None
                    else self.transport.get("timeoutSeconds") or 5
                ),
                60.0,
            ),
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(4 * 1024 * 1024)
        except urllib.error.HTTPError as exc:
            detail = exc.read(16 * 1024).decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Syncthing REST {method.upper()} {path} failed "
                f"with HTTP {exc.code}: {detail[:2000]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Syncthing REST endpoint is unavailable: {exc.reason}"
            ) from exc
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Syncthing REST {path} returned invalid JSON"
            ) from exc

    @_proofs_b_checked("sync")
    def compatibility_snapshot(self) -> dict[str, Any]:
        binary = dict(self.config.get("binary") or {})
        path = Path(str(binary.get("installPath") or "")).resolve()
        expected = str(binary.get("executableSha256") or "").casefold()
        actual = _sha256_file(path) if path.is_file() else ""
        return {
            "schema": "neyvia.folder-sync-compatibility/v1",
            "transport": {
                "name": str(self.transport.get("name") or ""),
                "version": str(self.transport.get("version") or ""),
                "endpointScope": "loopback",
                "credentialReferenceConfigured": bool(
                    self.transport.get("apiKeyRef")
                ),
                "credentialAvailable": self._credential_available(),
                "credentialsExposed": False,
            },
            "binary": {
                "version": str(binary.get("version") or ""),
                "path": str(path),
                "installed": path.is_file(),
                "hashVerified": bool(
                    actual and expected and actual.casefold() == expected
                ),
                "expectedSha256": expected,
                "actualSha256": actual,
                "serviceState": str(binary.get("serviceState") or ""),
                "signature": str(binary.get("signature") or ""),
                "malwareScan": str(binary.get("malwareScan") or ""),
            },
            "features": {
                "folderTypes": list(self.policy.get("folderTypes") or []),
                "versioningTypes": list(
                    self.policy.get("versioningTypes") or []
                ),
                "hashBoundPlans": True,
                "pausedCreation": True,
                "boundedEvents": True,
                "dangerousRecoverySeparated": True,
                "stableConflictIdentities": True,
                "conflictResolutionPlans": [
                    "keep-local",
                    "keep-remote",
                    "keep-both",
                ],
                "conflictExecutionImplemented": False,
                "durableConnectivityObservations": True,
                "relationshipRevisionCAS": True,
                "peerBoundConflictIdentity": True,
                "providerVerifiedConflictVersioning": True,
                "workspaceIntegrityChecksums": "accidental-corruption-only",
                "authorizationJournalRecovery": True,
                "redactedReceipts": True,
            },
        }

    def _credential_available(self) -> bool:
        try:
            return bool(self._api_key())
        except RuntimeError:
            return False

    def bootstrap(self) -> dict[str, Any]:
        binary = dict(self.config.get("binary") or {})
        return {
            "schema": "neyvia.folder-sync-bootstrap/v1",
            "provider": "syncthing",
            "version": str(binary.get("version") or ""),
            "state": str(binary.get("serviceState") or ""),
            "createPaused": bool(self.policy.get("createPaused", True)),
            "deletionApprovalRequired": bool(
                self.policy.get("requireDeletionPropagationApproval", True)
            ),
            "credentialsExposed": False,
            "detailsDeferred": True,
        }

    def health(
        self,
        *,
        include_folder_status: bool = False,
        refresh: bool = False,
    ) -> dict[str, Any]:
        ttl = max(
            0.0,
            min(float(self.policy.get("healthCacheSeconds") or 3), 30.0),
        )
        now = time.monotonic()
        if not include_folder_status and not refresh:
            with self._cache_lock:
                cached = self._health_cache
                if cached and now - cached[0] <= ttl:
                    result = copy.deepcopy(cached[1])
                    result["cache"] = {
                        "hit": True,
                        "ttlSeconds": ttl,
                    }
                    return result
        started = time.perf_counter()
        compatibility = self.compatibility_snapshot()
        binary = compatibility["binary"]
        enablement = {
            "serviceState": binary["serviceState"],
            "binaryInstalled": binary["installed"],
            "binaryHashVerified": binary["hashVerified"],
            "credentialAvailable": compatibility["transport"]["credentialAvailable"],
        }
        unavailable = False
        try:
            status = self._request("GET", "/rest/system/status")
            connections = self._request("GET", "/rest/system/connections")
            folders = self._request("GET", "/rest/config/folders")
            if not isinstance(status, dict) or not isinstance(connections, dict) or not isinstance(folders, list):
                raise RuntimeError("Invalid Syncthing health response")
        except RuntimeError:
            # Do not expose REST response bodies or transport credentials in health.
            unavailable = True
            status, connections, folders = {}, {}, []
        folder_rows = [
            self._public_folder(folder)
            for folder in folders[: int(self.policy.get("maxFolders") or 50)]
            if isinstance(folder, dict)
        ]
        if include_folder_status:
            for row in folder_rows:
                self._folder_health(row)
        connection_rows = []
        raw_connections = (
            connections.get("connections")
            if isinstance(connections, dict)
            else {}
        )
        if isinstance(raw_connections, dict):
            for device_id, detail in sorted(raw_connections.items()):
                if not isinstance(detail, dict):
                    continue
                connection_rows.append(
                    {
                        "deviceRef": self._device_ref(str(device_id)),
                        "connected": bool(detail.get("connected")),
                        "paused": bool(detail.get("paused")),
                        "transport": str(detail.get("type") or ""),
                        "route": self._connection_route(detail),
                        "inBytesTotal": int(detail.get("inBytesTotal") or 0),
                        "outBytesTotal": int(detail.get("outBytesTotal") or 0),
                    }
                )
        routes = {route: sum(row["route"] == route for row in connection_rows)
                  for route in ("direct", "relay", "offline", "unknown")}
        routes["connected"] = sum(row["connected"] for row in connection_rows)
        result = {
            "schema": "neyvia.folder-sync-health/v1",
            "generatedAt": utc_now(),
            "provider": "syncthing",
            "available": not unavailable,
            "state": "unavailable" if unavailable else "running",
            "enablement": enablement,
            "physicalDeviceProof": {"available": False, "reason": "REST health does not prove a physical peer transfer"},
            "routes": routes,
            "version": str(status.get("version") or self.transport.get("version") or ""),
            "localDeviceRef": self._device_ref(str(status.get("myID") or "")),
            "uptimeSeconds": int(status.get("uptime") or 0),
            "discoveryEnabled": bool(status.get("discoveryEnabled")),
            "folders": folder_rows,
            "connections": connection_rows,
            "summary": {
                "folders": len(folder_rows),
                "pausedFolders": sum(
                    1 for row in folder_rows if row["paused"]
                ),
                "connectedDevices": sum(
                    1 for row in connection_rows if row["connected"]
                ),
                "relayConnections": routes["relay"],
                "unknownConnections": routes["unknown"],
                "foldersWithPullErrors": sum(bool((row.get("status") or {}).get("pullErrors")) for row in folder_rows),
                "foldersWithStatusUnavailable": sum(row.get("statusAvailable") is False for row in folder_rows),
                "folderStatusIncluded": include_folder_status,
                "durationMs": round(
                    (time.perf_counter() - started) * 1000.0,
                    3,
                ),
            },
            "cache": {"hit": False, "ttlSeconds": ttl},
            "credentialsExposed": False,
        }
        if unavailable:
            result["reason"] = "Syncthing REST health is unavailable"
        if not include_folder_status:
            with self._cache_lock:
                self._health_cache = (now, copy.deepcopy(result))
        return result

    @staticmethod
    def _connection_route(detail: dict[str, Any]) -> str:
        connection_type = str(detail.get("type") or "").casefold()
        if not detail.get("connected"):
            return "offline"
        if "relay" in connection_type:
            return "relay"
        if connection_type:
            return "direct"
        return "unknown"

    def _folder_health(self, row: dict[str, Any]) -> None:
        row.update(statusAvailable=False, errors=[], errorsAvailable=False)
        row["issueSummary"] = {"operationalState": "status_unavailable", "conflictCopiesEnumerated": False}
        try:
            status = self._request("GET", "/rest/db/status", query={"folder": row["folderId"]})
            if not isinstance(status, dict):
                return
        except RuntimeError:
            return
        row["statusAvailable"] = True
        row["status"] = self._public_folder_status(status)
        try:
            errors = self._request("GET", "/rest/folder/errors", query={"folder": row["folderId"], "page": 1, "perpage": 100})
            if isinstance(errors, dict) and isinstance(errors.get("errors"), list):
                row["errorsAvailable"] = True
                for error in errors["errors"][:100]:
                    if not isinstance(error, dict):
                        continue
                    path = str(error.get("path") or "").replace("\\", "/")
                    if PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts or re.match(r"^[A-Za-z]:", path):
                        path = "outside-policy"
                    row["errors"].append({"path": _redact_text(path)[:1000], "error": _redact_text(str(error.get("error") or ""))[:2000]})
        except RuntimeError:
            pass
        state = ("paused" if row["paused"] else "error" if status.get("pullErrors") or row["errors"] else str(status.get("state") or "unknown"))
        row["issueSummary"]["operationalState"] = state

    @staticmethod
    def _public_folder_status(value: Any) -> dict[str, Any]:
        row = value if isinstance(value, dict) else {}
        keys = (
            "state",
            "stateChanged",
            "globalBytes",
            "globalFiles",
            "inSyncBytes",
            "inSyncFiles",
            "needBytes",
            "needFiles",
            "needDeletes",
            "pullErrors",
            "receiveOnlyChangedBytes",
            "receiveOnlyChangedFiles",
            "receiveOnlyChangedDeletes",
        )
        return {key: row.get(key) for key in keys}

    def _public_folder(self, folder: dict[str, Any]) -> dict[str, Any]:
        versioning = folder.get("versioning")
        devices = folder.get("devices")
        return {
            "folderId": str(folder.get("id") or ""),
            "label": str(folder.get("label") or folder.get("id") or ""),
            "path": self._display_path(str(folder.get("path") or "")),
            "type": str(folder.get("type") or "sendreceive"),
            "paused": bool(folder.get("paused")),
            "group": str(folder.get("group") or ""),
            "versioning": {
                "type": str(
                    versioning.get("type") if isinstance(versioning, dict) else ""
                ),
                "enabled": bool(
                    isinstance(versioning, dict) and versioning.get("type")
                ),
            },
            "devices": [
                {
                    "deviceRef": self._device_ref(str(item.get("deviceID") or "")),
                    "introducedBy": self._device_ref(
                        str(item.get("introducedBy") or "")
                    ),
                }
                for item in (devices if isinstance(devices, list) else [])
                if isinstance(item, dict)
            ],
        }

    def _display_path(self, value: str) -> str:
        try:
            path = Path(value).resolve()
        except (OSError, RuntimeError):
            return "invalid"
        try:
            return f"workspace:{path.relative_to(self.root).as_posix()}"
        except ValueError:
            pass
        for index, allowed in enumerate(self._allowed_roots()):
            if allowed == self.root:
                continue
            try:
                relative = path.relative_to(allowed)
            except ValueError:
                continue
            return f"allowed-root-{index}:{relative.as_posix()}"
        return "outside-policy"

    @staticmethod
    def _device_ref(device_id: str) -> str:
        if not device_id:
            return ""
        return "device-" + hashlib.sha256(
            device_id.encode("utf-8")
        ).hexdigest()[:16]

    @staticmethod
    def _device_identity_digest(device_id: str) -> str:
        if not device_id:
            return ""
        return hashlib.sha256(device_id.encode("utf-8")).hexdigest()

    @_proofs_b_checked("sync-plan")
    def build_folder_plan(
        self,
        *,
        folder_id: str,
        path: str | Path,
        device_ids: list[str],
        label: str = "",
        folder_type: str = "sendonly",
        ignore_patterns: list[str] | None = None,
        versioning: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_id = str(folder_id or "").strip()
        if not _FOLDER_ID_PATTERN.fullmatch(normalized_id):
            raise ValueError(
                "folderId must contain only letters, numbers, dot, dash, or underscore"
            )
        selected_path = self._allowed_folder_path(path)
        normalized_type = str(folder_type or "").strip().casefold()
        allowed_types = set(self.policy.get("folderTypes") or [])
        if normalized_type not in allowed_types:
            raise ValueError(f"Unsupported folder type: {normalized_type}")
        normalized_devices = self._validate_device_ids(device_ids)
        ignores = self._validate_ignore_patterns(ignore_patterns or [])
        # Reject unsupported local policy before making any provider request.
        selected_versioning = self._validated_versioning(normalized_type, versioning)
        folders = self._request("GET", "/rest/config/folders")
        default = self._request("GET", "/rest/config/defaults/folder")
        if not isinstance(folders, list) or not isinstance(default, dict):
            raise RuntimeError("Syncthing configuration responses are invalid")
        existing = next(
            (
                copy.deepcopy(item)
                for item in folders
                if isinstance(item, dict)
                and str(item.get("id") or "") == normalized_id
            ),
            None,
        )
        current_ignores: list[str] = []
        if existing is not None:
            raw_ignores = self._request(
                "GET",
                "/rest/db/ignores",
                query={"folder": normalized_id},
            )
            if isinstance(raw_ignores, dict):
                current_ignores = [
                    str(item)
                    for item in (raw_ignores.get("ignore") or [])
                ]
        desired = copy.deepcopy(existing if existing is not None else default)
        desired.update(
            {
                "id": normalized_id,
                "label": str(label or normalized_id)[:128],
                "path": str(selected_path),
                "type": normalized_type,
                "paused": True,
                "group": "Neyvia",
                "devices": [
                    {"deviceID": device_id}
                    for device_id in normalized_devices
                ],
            }
        )
        desired["versioning"] = selected_versioning
        base_state = {
            "folder": existing,
            "ignores": current_ignores,
        }
        deletion_risk = self._deletion_risk(normalized_type)
        plan = {
            "schema": FOLDER_SYNC_PLAN_SCHEMA,
            "planId": f"syncplan_{uuid.uuid4().hex[:20]}",
            "createdAt": utc_now(),
            "folderId": normalized_id,
            "mode": normalized_type,
            "path": str(selected_path),
            "pathDisplay": self._display_path(str(selected_path)),
            "desiredFolder": desired,
            "ignorePatterns": ignores,
            "baseStateHash": _canonical_hash(base_state),
            "baseState": base_state,
            "risk": {
                "deletionPropagation": True,
                "reasons": deletion_risk,
                "createdPaused": True,
                "activationRequiresExplicitApproval": True,
                "versioningProtectsRemoteChangesOnly": True,
            },
            "summary": {
                "existingFolder": existing is not None,
                "devices": len(normalized_devices),
                "ignorePatterns": len(ignores),
                "versioning": str(selected_versioning.get("type") or ""),
                "appliesDataChanges": False,
            },
        }
        plan["planHash"] = self._plan_hash(plan)
        atomic_write_json(
            self.plan_root / f"{plan['planId']}.json",
            plan,
        )
        return plan

    def _allowed_roots(self) -> list[Path]:
        result: list[Path] = []
        for raw in self.policy.get("allowedRoots") or ["${workspace}"]:
            value = str(raw)
            path = self.root if value == "${workspace}" else Path(value)
            result.append(path.resolve())
        return result

    @_proofs_b_checked("sync-path")
    def _allowed_folder_path(self, value: str | Path) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self.root / path
        path = path.resolve()
        if not path.is_dir():
            raise ValueError(f"Folder-sync path does not exist: {path}")
        for allowed in self._allowed_roots():
            try:
                path.relative_to(allowed)
                return path
            except ValueError:
                continue
        raise ValueError("Folder-sync path is outside configured allowed roots")

    def _validate_device_ids(self, values: list[str]) -> list[str]:
        if not isinstance(values, list):
            raise ValueError("deviceIds must be an array")
        maximum = int(self.policy.get("maxDevicesPerFolder") or 32)
        normalized = list(dict.fromkeys(str(item).strip() for item in values))
        if not normalized or len(normalized) > maximum:
            raise ValueError(
                f"deviceIds must contain between 1 and {maximum} devices"
            )
        for device_id in normalized:
            if not _DEVICE_ID_PATTERN.fullmatch(device_id):
                raise ValueError(f"Invalid Syncthing device ID: {device_id}")
        return normalized

    @_proofs_b_checked("sync-ignores")
    def _validate_ignore_patterns(self, values: list[str]) -> list[str]:
        maximum = int(self.policy.get("maxIgnorePatterns") or 256)
        if len(values) > maximum:
            raise ValueError(f"At most {maximum} ignore patterns are allowed")
        result: list[str] = []
        for value in values:
            line = str(value)
            if not line.strip():
                continue
            if "\n" in line or "\r" in line or "\x00" in line:
                raise ValueError("Ignore patterns must be single lines")
            if line.lstrip().casefold().startswith("#include"):
                raise ValueError(
                    "Syncthing #include directives are not allowed in agent plans"
                )
            if len(line) > 1024:
                raise ValueError("Ignore pattern exceeds 1024 characters")
            result.append(line)
        return list(dict.fromkeys(result))

    @_proofs_b_checked("sync-versioning")
    def _validated_versioning(
        self,
        folder_type: str,
        value: dict[str, Any] | None,
    ) -> dict[str, Any]:
        selected = copy.deepcopy(
            value
            if value is not None
            else self.policy.get("defaultVersioning") or {}
        )
        if not isinstance(selected, dict):
            raise ValueError("versioning must be an object")
        version_type = str(selected.get("type") or "").casefold()
        allowed = set(self.policy.get("versioningTypes") or [])
        required = set(
            self.policy.get("inboundVersioningRequiredFor") or []
        )
        if version_type and version_type not in allowed:
            raise ValueError(
                "Only trashcan, simple, and staggered versioning are allowed; "
                "external versioner commands are intentionally blocked."
            )
        if folder_type in required and version_type not in allowed:
            raise ValueError(
                f"{folder_type} folders require local file versioning"
            )
        if not version_type:
            return {}
        selected["type"] = version_type
        selected["params"] = {
            str(key): str(item)
            for key, item in dict(selected.get("params") or {}).items()
        }
        selected["cleanupIntervalS"] = max(
            0,
            min(int(selected.get("cleanupIntervalS") or 3600), 31_536_000),
        )
        selected["fsPath"] = str(selected.get("fsPath") or "")
        selected["fsType"] = str(selected.get("fsType") or "basic")
        return selected

    @staticmethod
    def _deletion_risk(folder_type: str) -> list[str]:
        if folder_type == "sendonly":
            return [
                "Local deletions can propagate to receiving devices.",
                "Override can enforce local absence across the cluster.",
            ]
        if folder_type == "receiveonly":
            return [
                "Remote deletions can remove local files.",
                "Revert can discard local-only modifications.",
            ]
        return [
            "Local and remote deletions can propagate in both directions.",
            "Conflicting edits can create conflict copies.",
        ]

    @staticmethod
    def _plan_hash(plan: dict[str, Any]) -> str:
        payload = copy.deepcopy(plan)
        payload.pop("planHash", None)
        return _canonical_hash(payload)

    @_proofs_b_checked("sync-apply")
    def apply_folder_plan(
        self,
        plan: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        if not approved:
            return self._approval_required(
                "sync.configure",
                "Applying a continuous folder relationship requires approval.",
            )
        self._validate_plan(plan)
        folder_id = str(plan["folderId"])
        folders = self._request("GET", "/rest/config/folders")
        if not isinstance(folders, list):
            raise RuntimeError("Syncthing folders response must be an array")
        current = next(
            (
                copy.deepcopy(item)
                for item in folders
                if isinstance(item, dict)
                and str(item.get("id") or "") == folder_id
            ),
            None,
        )
        current_ignores: list[str] = []
        if current is not None:
            raw_ignores = self._request(
                "GET",
                "/rest/db/ignores",
                query={"folder": folder_id},
            )
            if isinstance(raw_ignores, dict):
                current_ignores = list(raw_ignores.get("ignore") or [])
        current_hash = _canonical_hash(
            {"folder": current, "ignores": current_ignores}
        )
        if current_hash != str(plan.get("baseStateHash") or ""):
            return {
                "ok": False,
                "status": "stale_plan",
                "folderId": folder_id,
                "expectedBaseStateHash": str(
                    plan.get("baseStateHash") or ""
                ),
                "actualBaseStateHash": current_hash,
            }
        desired = copy.deepcopy(plan["desiredFolder"])
        desired["paused"] = True
        try:
            self._request(
                "POST",
                "/rest/config/folders",
                payload=desired,
            )
            self._request(
                "POST",
                "/rest/db/ignores",
                query={"folder": folder_id},
                payload={"ignore": list(plan.get("ignorePatterns") or [])},
            )
        except Exception:
            self._restore_folder(
                folder_id,
                folder=current,
                ignores=current_ignores,
            )
            raise
        verified = self._request(
            "GET",
            f"/rest/config/folders/{urllib.parse.quote(folder_id, safe='')}",
        )
        if (
            not isinstance(verified, dict)
            or str(verified.get("id") or "") != folder_id
            or not bool(verified.get("paused"))
            or str(verified.get("type") or "") != str(plan.get("mode") or "")
        ):
            self._restore_folder(
                folder_id,
                folder=current,
                ignores=current_ignores,
            )
            raise RuntimeError(
                "Syncthing folder readback did not match the paused plan"
            )
        receipt = self._receipt(
            "apply-folder-plan",
            folder_id,
            ok=True,
            status="configured_paused",
            details={
                "planId": str(plan.get("planId") or ""),
                "planHash": str(plan.get("planHash") or ""),
                "mode": str(plan.get("mode") or ""),
                "pathDisplay": str(plan.get("pathDisplay") or ""),
                "activationRequired": True,
                "dataMovementStarted": False,
                "rollbackAvailable": current is not None,
            },
        )
        self._invalidate_cache()
        return receipt

    @_proofs_b_checked("sync-restore")
    def _restore_folder(
        self,
        folder_id: str,
        *,
        folder: dict[str, Any] | None,
        ignores: list[str],
    ) -> None:
        if folder is None:
            self._request(
                "DELETE",
                f"/rest/config/folders/{urllib.parse.quote(folder_id, safe='')}",
            )
            return
        self._request("POST", "/rest/config/folders", payload=folder)
        self._request(
            "POST",
            "/rest/db/ignores",
            query={"folder": folder_id},
            payload={"ignore": ignores},
        )

    def _validate_plan(self, plan: dict[str, Any]) -> None:
        if not isinstance(plan, dict) or plan.get("schema") != FOLDER_SYNC_PLAN_SCHEMA:
            raise ValueError("Invalid folder-sync plan schema")
        expected = str(plan.get("planHash") or "")
        if not expected or expected != self._plan_hash(plan):
            raise ValueError("Folder-sync plan hash does not match its contents")
        desired = plan.get("desiredFolder")
        if not isinstance(desired, dict) or not bool(desired.get("paused")):
            raise ValueError("Folder-sync plans must configure a paused folder")
        path = self._allowed_folder_path(str(plan.get("path") or ""))
        if str(path) != str(plan.get("path") or ""):
            raise ValueError("Folder-sync plan path changed after preview")

    def pause_folder(
        self,
        folder_id: str,
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        if not approved:
            return self._approval_required(
                "sync.pause",
                "Pausing a continuous relationship requires approval.",
            )
        folder = self._folder_config(folder_id)
        self._request(
            "PATCH",
            f"/rest/config/folders/{urllib.parse.quote(folder_id, safe='')}",
            payload={"paused": True},
        )
        self._invalidate_cache()
        return self._receipt(
            "pause-folder",
            folder_id,
            ok=True,
            status="paused",
            details={
                "previouslyPaused": bool(folder.get("paused")),
                "dataMovementActive": False,
            },
        )

    @_proofs_b_checked("sync-activation")
    def resume_folder(
        self,
        folder_id: str,
        *,
        approved: bool = False,
        approved_deletion_propagation: bool = False,
    ) -> dict[str, Any]:
        if not approved or not approved_deletion_propagation:
            return self._approval_required(
                "sync.deletion-propagation",
                "Activation can propagate deletions and requires explicit approval.",
            )
        folder = self._folder_config(folder_id)
        folder_type = str(folder.get("type") or "sendreceive")
        versioning = folder.get("versioning")
        version_type = str(
            versioning.get("type") if isinstance(versioning, dict) else ""
        )
        if (
            folder_type
            in set(self.policy.get("inboundVersioningRequiredFor") or [])
            and version_type
            not in set(self.policy.get("versioningTypes") or [])
        ):
            raise RuntimeError(
                f"Refusing to activate {folder_type} without local versioning"
            )
        self._request(
            "PATCH",
            f"/rest/config/folders/{urllib.parse.quote(folder_id, safe='')}",
            payload={"paused": False},
        )
        readback = self._folder_config(folder_id)
        if bool(readback.get("paused")):
            raise RuntimeError("Syncthing folder remained paused after activation")
        self._invalidate_cache()
        return self._receipt(
            "resume-folder",
            folder_id,
            ok=True,
            status="active",
            details={
                "mode": folder_type,
                "deletionPropagationApproved": True,
                "versioning": version_type,
                "riskReasons": self._deletion_risk(folder_type),
            },
        )

    def rescan_folder(
        self,
        folder_id: str,
        *,
        sub_path: str = "",
        approved: bool = False,
    ) -> dict[str, Any]:
        if not approved:
            return self._approval_required(
                "sync.rescan",
                "A rescan can consume substantial disk and CPU resources.",
            )
        self._folder_config(folder_id)
        normalized_sub_path = str(sub_path or "").replace("\\", "/").strip("/")
        if (
            normalized_sub_path.startswith("../")
            or "/../" in normalized_sub_path
            or "\x00" in normalized_sub_path
        ):
            raise ValueError("subPath must stay inside the synchronized folder")
        self._request(
            "POST",
            "/rest/db/scan",
            query={
                "folder": folder_id,
                "sub": normalized_sub_path or None,
            },
            timeout_seconds=60,
        )
        return self._receipt(
            "rescan-folder",
            folder_id,
            ok=True,
            status="scan_requested",
            details={"subPath": normalized_sub_path},
        )

    def events(
        self,
        *,
        since: int = 0,
        limit: int = 25,
        timeout_seconds: int = 1,
        disk_only: bool = False,
    ) -> dict[str, Any]:
        bounded_limit = max(
            1,
            min(int(limit), int(self.policy.get("maxEvents") or 100)),
        )
        bounded_timeout = max(0, min(int(timeout_seconds), 15))
        path = "/rest/events/disk" if disk_only else "/rest/events"
        rows = self._request(
            "GET",
            path,
            query={
                "since": max(0, int(since)),
                "limit": bounded_limit,
                "timeout": bounded_timeout,
            },
            timeout_seconds=bounded_timeout + 2,
        )
        if not isinstance(rows, list):
            raise RuntimeError("Syncthing events response must be an array")
        public = [
            self._sanitize_event(item)
            for item in rows[:bounded_limit]
            if isinstance(item, dict)
        ]
        return {
            "schema": "neyvia.folder-sync-events/v1",
            "generatedAt": utc_now(),
            "events": public,
            "cursor": max(
                [int(item.get("id") or 0) for item in public] + [int(since)]
            ),
            "summary": {
                "events": len(public),
                "diskOnly": disk_only,
                "boundedLimit": bounded_limit,
            },
            "credentialsExposed": False,
        }

    def _sanitize_event(self, value: dict[str, Any]) -> dict[str, Any]:
        data = copy.deepcopy(
            value.get("data") if isinstance(value.get("data"), dict) else {}
        )
        for key in list(data):
            normalized = str(key).casefold()
            if normalized in {"device", "deviceid", "myid"}:
                data[key] = self._device_ref(str(data[key]))
            elif normalized in {
                "apikey",
                "api_key",
                "password",
                "secret",
                "token",
            }:
                data.pop(key, None)
        return {
            "id": int(value.get("id") or 0),
            "globalId": int(value.get("globalID") or 0),
            "time": str(value.get("time") or ""),
            "type": str(value.get("type") or ""),
            "data": data,
        }

    def observe_conflict(
        self,
        *,
        folder_id: str,
        relative_path: str,
        local: dict[str, Any],
        remote: dict[str, Any],
        expected_revision: int,
    ) -> dict[str, Any]:
        """Persist a content-bound conflict observation without resolving it."""

        expected = self._validated_revision(expected_revision)
        normalized_folder = self._validated_folder_id(folder_id)
        normalized_path = self._normalized_relative_path(relative_path)
        if _redact_text(normalized_path) != normalized_path:
            raise ValueError("Conflict path must not contain secret-like text")
        local_state = self._normalized_conflict_side(local, side="local")
        remote_state = self._normalized_conflict_side(remote, side="remote")
        if local_state["deviceRef"] == remote_state["deviceRef"]:
            raise ValueError("Local and remote conflict devices must be distinct")
        if local_state["deleted"] and remote_state["deleted"]:
            raise ValueError("A conflict cannot contain two deleted sides")
        if (
            not local_state["deleted"]
            and not remote_state["deleted"]
            and local_state.get("contentHash") == remote_state.get("contentHash")
        ):
            raise ValueError("The local and remote observations are not in conflict")
        base_state = {
            "folderId": normalized_folder,
            "relativePath": normalized_path,
            "local": local_state,
            "remote": remote_state,
        }
        identity = {
            "folderId": normalized_folder,
            "relativePath": normalized_path,
            "local": self._conflict_side_identity(local_state),
            "remote": self._conflict_side_identity(remote_state),
        }
        conflict_id = "syncconflict_" + _canonical_hash(identity)[:24]
        with self._relationship_lock(conflict_id):
            conflict_path = self.conflict_root / f"{conflict_id}.json"
            current_revision = 0
            current_conflict: dict[str, Any] | None = None
            if conflict_path.is_file():
                current_conflict = self._persisted_conflict(conflict_id)
                current_revision = int(current_conflict.get("revision") or 0)
            journal = self._observation_journal(
                conflict_id,
                current_conflict,
            )
            if expected != current_revision:
                return self._stale_revision(
                    expected=expected,
                    actual=current_revision,
                    conflict_id=conflict_id,
                )
            conflict = {
                "schema": FOLDER_SYNC_CONFLICT_SCHEMA,
                "conflictId": conflict_id,
                "revision": current_revision + 1,
                "observedAt": utc_now(),
                "folderId": normalized_folder,
                "relativePath": normalized_path,
                "local": local_state,
                "remote": remote_state,
                "baseStateChecksum": _canonical_hash(base_state),
                "observationTrust": "unverifiedObservation",
                "resolutionApplied": False,
                "providerProcessInspected": False,
                "credentialsExposed": False,
            }
            conflict["conflictChecksum"] = self._conflict_checksum(conflict)
            supersession = self._prepare_observation_supersession(
                conflict_id,
                journal=journal,
                current_conflict=current_conflict,
                next_conflict=conflict,
            )
            if supersession.get("blocked"):
                return dict(supersession["result"])
            atomic_write_json(conflict_path, conflict)
            prepared_journal = supersession.get("journal")
            if isinstance(prepared_journal, dict):
                self._retire_observation_journal(
                    conflict_id,
                    prepared_journal,
                )
            return conflict

    def conflict_observation(self, conflict_id: str) -> dict[str, Any]:
        """Load one durable conflict observation under its relationship lock."""

        normalized = str(conflict_id or "").strip()
        with self._relationship_lock(normalized):
            return copy.deepcopy(self._persisted_conflict(normalized))

    def conflict_resolution_plan(self, plan_id: str) -> dict[str, Any]:
        """Load one immutable durable conflict resolution plan."""

        return copy.deepcopy(
            self._persisted_conflict_plan(str(plan_id or "").strip())
        )

    def build_conflict_resolution_plan(
        self,
        conflict: dict[str, Any],
        *,
        resolution: str,
    ) -> dict[str, Any]:
        """Create a non-executing, checksum-bound conflict resolution plan."""

        self._validate_conflict(conflict)
        selected = str(resolution or "").strip().casefold().replace("_", "-")
        if selected not in {"keep-local", "keep-remote", "keep-both"}:
            raise ValueError(
                "resolution must be keep-local, keep-remote, or keep-both"
            )
        local = dict(conflict["local"])
        remote = dict(conflict["remote"])
        actions = self._conflict_actions(
            selected,
            conflict_id=str(conflict["conflictId"]),
            relative_path=str(conflict["relativePath"]),
            local=local,
            remote=remote,
        )
        destructive = any(
            bool(action.get("destructive")) for action in actions
        )
        plan = {
            "schema": FOLDER_SYNC_CONFLICT_PLAN_SCHEMA,
            "planId": f"syncconflictplan_{uuid.uuid4().hex[:20]}",
            "createdAt": utc_now(),
            "conflictId": str(conflict["conflictId"]),
            "conflictRevision": int(conflict["revision"]),
            "folderId": str(conflict["folderId"]),
            "relativePath": str(conflict["relativePath"]),
            "resolution": selected,
            "baseStateChecksum": str(conflict["baseStateChecksum"]),
            "actions": actions,
            "guards": {
                "approvalRequired": True,
                "deletionApprovalRequired": destructive,
                "providerVersioningRequired": destructive,
                "contentHashesRequired": True,
                "peerIdentityBound": True,
                "observationTrust": "unverifiedObservation",
                "baseStateMustMatch": True,
            },
            "risk": {
                "destructive": destructive,
                "deletionOrReplacement": destructive,
                "keepsBothVersions": selected == "keep-both",
            },
            "summary": {
                "actions": len(actions),
                "executionPerformed": False,
                "providerProcessInspected": False,
            },
            "credentialsExposed": False,
            "integrityScope": "accidental-corruption-only",
        }
        plan["planChecksum"] = self._conflict_plan_checksum(plan)
        atomic_write_json(
            self.plan_root / f"{plan['planId']}.json",
            plan,
        )
        return plan

    def authorize_conflict_resolution(
        self,
        plan: dict[str, Any],
        *,
        current_conflict: dict[str, Any],
        approved: bool,
        deletion_approved: bool,
        expected_revision: int,
    ) -> dict[str, Any]:
        """Authorize a still-current plan; filesystem execution is out of scope."""

        self._require_boolean(approved, field="approved")
        self._require_boolean(deletion_approved, field="deletionApproved")
        expected = self._validated_revision(expected_revision)
        if not approved:
            return self._approval_required(
                "sync.conflict-resolution",
                "Resolving a folder conflict requires explicit approval.",
            )
        self._validate_conflict_plan(plan)
        persisted_plan = self._persisted_conflict_plan(
            str(plan.get("planId") or "")
        )
        if _canonical_hash(persisted_plan) != _canonical_hash(plan):
            raise ValueError(
                "Conflict resolution plan does not match its durable preview"
            )
        self._validate_conflict(current_conflict)
        expected_conflict_id = str(plan.get("conflictId") or "")
        if str(current_conflict.get("conflictId") or "") != expected_conflict_id:
            return {
                "ok": False,
                "status": "conflict_changed",
                "expectedConflictId": expected_conflict_id,
                "actualConflictId": str(
                    current_conflict.get("conflictId") or ""
                ),
                "executionPerformed": False,
            }
        with self._relationship_lock(expected_conflict_id):
            persisted_conflict = self._persisted_conflict(expected_conflict_id)
            actual_revision = int(persisted_conflict.get("revision") or 0)
            recovery = self._recover_authorization_journal(
                expected_conflict_id,
                persisted_conflict,
            )
            if recovery is not None:
                return recovery
            if expected != actual_revision:
                return self._stale_revision(
                    expected=expected,
                    actual=actual_revision,
                    conflict_id=expected_conflict_id,
                )
            if int(current_conflict.get("revision") or -1) != actual_revision:
                return self._stale_observation(
                    expected_conflict_id,
                    persisted_conflict,
                    current_conflict,
                )
            supplied_base_checksum = str(
                current_conflict.get("baseStateChecksum") or ""
            )
            actual_base_checksum = str(
                persisted_conflict.get("baseStateChecksum") or ""
            )
            if supplied_base_checksum != actual_base_checksum:
                return self._stale_observation(
                    expected_conflict_id,
                    persisted_conflict,
                    current_conflict,
                )
            if (
                actual_base_checksum
                != str(plan.get("baseStateChecksum") or "")
                or int(plan.get("conflictRevision") or -1) != actual_revision
            ):
                return {
                    "ok": False,
                    "status": "stale_plan",
                    "conflictId": expected_conflict_id,
                    "expectedBaseStateChecksum": str(
                        plan.get("baseStateChecksum") or ""
                    ),
                    "actualBaseStateChecksum": actual_base_checksum,
                    "expectedRevision": int(
                        plan.get("conflictRevision") or -1
                    ),
                    "actualRevision": actual_revision,
                    "executionPerformed": False,
                }
            actions = [
                dict(item)
                for item in (plan.get("actions") or [])
                if isinstance(item, dict)
            ]
            expected_actions = self._conflict_actions(
                str(plan.get("resolution") or ""),
                conflict_id=expected_conflict_id,
                relative_path=str(persisted_conflict["relativePath"]),
                local=dict(persisted_conflict["local"]),
                remote=dict(persisted_conflict["remote"]),
            )
            if actions != expected_actions:
                return {
                    "ok": False,
                    "status": "plan_semantics_unverified",
                    "conflictId": expected_conflict_id,
                    "executionPerformed": False,
                }
            destructive_actions = [
                item for item in actions if bool(item.get("destructive"))
            ]
            destructive = bool(destructive_actions)
            provider_evidence = self._provider_resolution_evidence(
                str(plan.get("folderId") or ""),
                str(plan.get("relativePath") or ""),
                persisted_conflict,
                actions,
            )
            if not provider_evidence["providerVerified"]:
                return {
                    "ok": False,
                    "status": "provider_evidence_unverified",
                    "conflictId": expected_conflict_id,
                    "providerEvidence": provider_evidence,
                    "observationTrust": "unverifiedObservation",
                    "executionPerformed": False,
                }
            verified_local_ref = str(
                provider_evidence.get("localDeviceRef") or ""
            )
            remote_destination_actions = [
                item
                for item in actions
                if (
                    str(item.get("destinationDeviceRef") or "")
                    != verified_local_ref
                )
            ]
            if remote_destination_actions:
                return {
                    "ok": False,
                    "status": "remote_versioning_unverified",
                    "conflictId": expected_conflict_id,
                    "reason": (
                        "Local Syncthing evidence cannot attest or protect any "
                        "remote destination action."
                    ),
                    "remoteAttestationAvailable": False,
                    "providerEvidence": provider_evidence,
                    "executionPerformed": False,
                }
            if destructive and not deletion_approved:
                return self._approval_required(
                    "sync.conflict-deletion",
                    "This resolution can delete or replace a version and needs "
                    "separate deletion approval.",
                )
            if destructive and not provider_evidence["activeVersioning"]:
                return {
                    "ok": False,
                    "status": "versioning_evidence_unverified",
                    "conflictId": expected_conflict_id,
                    "providerEvidence": provider_evidence,
                    "executionPerformed": False,
                }
            persisted_remote = dict(persisted_conflict["remote"])
            expected_remote_ref = str(
                persisted_remote.get("deviceRef") or ""
            )
            remote_source_contracts: list[dict[str, Any]] = []
            for index, action in enumerate(actions):
                if (
                    str(action.get("sourceDeviceRef") or "")
                    == verified_local_ref
                ):
                    continue
                if bool(persisted_remote.get("deleted")):
                    continue
                expected_source_contract = (
                    self._remote_source_verification_contract(
                        persisted_remote
                    )
                )
                if (
                    str(action.get("sourceDeviceRef") or "")
                    != expected_remote_ref
                    or action.get("sourceVerification")
                    != expected_source_contract
                ):
                    return {
                        "ok": False,
                        "status": "remote_source_verification_unavailable",
                        "conflictId": expected_conflict_id,
                        "observationTrust": "unverifiedObservation",
                        "executionPerformed": False,
                    }
                remote_source_contracts.append(
                    {
                        "actionIndex": index,
                        "operation": str(action.get("operation") or ""),
                        "sourceDeviceRef": expected_remote_ref,
                        "destinationDeviceRef": verified_local_ref,
                        **expected_source_contract,
                    }
                )
            next_revision = actual_revision + 1
            receipt_id = f"syncreceipt_{uuid.uuid4().hex[:20]}"
            journal = self._write_authorization_journal(
                expected_conflict_id,
                {
                    "transactionId": (
                        f"synctxn_{uuid.uuid4().hex[:20]}"
                    ),
                    "status": "prepared",
                    "createdAt": utc_now(),
                    "receiptId": receipt_id,
                    "planId": str(plan.get("planId") or ""),
                    "planChecksum": str(
                        plan.get("planChecksum") or ""
                    ),
                    "baseStateChecksum": actual_base_checksum,
                    "sourceRevision": actual_revision,
                    "targetRevision": next_revision,
                    "providerEvidenceChecksum": str(
                        provider_evidence.get(
                            "providerEvidenceChecksum"
                        )
                        or ""
                    ),
                },
            )
            receipt = self._receipt(
                "authorize-conflict-resolution",
                str(plan.get("folderId") or ""),
                ok=True,
                status="resolution_authorized",
                receipt_id=receipt_id,
                details={
                    "journalTransactionRef": str(
                        journal.get("transactionId") or ""
                    ),
                    "commitRequirement": (
                        "matching-committed-journal-and-conflict-binding"
                    ),
                    "planId": str(plan.get("planId") or ""),
                    "planChecksum": str(plan.get("planChecksum") or ""),
                    "conflictId": expected_conflict_id,
                    "baseStateChecksum": actual_base_checksum,
                    "revision": next_revision,
                    "executorExpectedRevision": next_revision,
                    "observationTrust": "providerVerifiedLocalObservation",
                    "localObservationTrust": (
                        "providerVerifiedLocalObservation"
                    ),
                    "remoteObservationTrust": "unverifiedObservation",
                    "resolution": str(plan.get("resolution") or ""),
                    "localDeviceRef": str(
                        persisted_conflict["local"]["deviceRef"]
                    ),
                    "remoteDeviceRef": str(
                        persisted_conflict["remote"]["deviceRef"]
                    ),
                    "actions": actions,
                    "deletionApproved": deletion_approved,
                    "providerResolutionEvidence": provider_evidence,
                    "executorExpectedProviderEvidenceChecksum": str(
                        provider_evidence.get(
                            "providerEvidenceChecksum"
                        )
                        or ""
                    ),
                    "executorRecheck": {
                        "conflictRevision": next_revision,
                        "baseStateChecksum": actual_base_checksum,
                        "localFileSha256": str(
                            provider_evidence.get("localFileSha256")
                            or ""
                        ),
                        "folderMembershipChecksum": str(
                            provider_evidence.get(
                                "folderMembershipChecksum"
                            )
                            or ""
                        ),
                        "providerEvidenceChecksum": str(
                            provider_evidence.get(
                                "providerEvidenceChecksum"
                            )
                            or ""
                        ),
                        "localDeviceRef": verified_local_ref,
                        "remoteDeviceRef": str(
                            provider_evidence.get("remoteDeviceRef")
                            or ""
                        ),
                        "remoteSourceStaging": remote_source_contracts,
                        "exclusiveDestinations": copy.deepcopy(
                            provider_evidence.get(
                                "exclusiveDestinations"
                            )
                            or []
                        ),
                        "requiredChecks": [
                            "revision",
                            "base-state",
                            "provider-folder-metadata",
                            "local-file-sha256-or-absence",
                            "peer-membership",
                            *(
                                [
                                    "stage-remote-bytes-separately",
                                    "persisted-remote-sha256-before-commit",
                                ]
                                if remote_source_contracts
                                else []
                            ),
                            *(
                                [
                                    "exclusive-destination-absence",
                                    "create-exclusive-commit",
                                ]
                                if provider_evidence.get(
                                    "exclusiveDestinations"
                                )
                                else []
                            ),
                        ],
                    },
                    "executionPerformed": False,
                    "nextStep": (
                        "A separately implemented executor must revalidate the "
                        "exact revision, base-state binding, provider evidence "
                        "checksum, local file SHA-256 or verified absence, and "
                        "peer membership; remote bytes must be staged and "
                        "SHA-256 verified before local commit, and exclusive "
                        "destinations must still be absent at create time."
                    ),
                },
            )
            journal["status"] = "receipt_written"
            journal["receiptWrittenAt"] = utc_now()
            journal = self._write_authorization_journal(
                expected_conflict_id,
                journal,
            )
            persisted_conflict["revision"] = next_revision
            persisted_conflict["authorizedAt"] = utc_now()
            persisted_conflict["authorizationReceiptId"] = str(
                receipt["receiptId"]
            )
            persisted_conflict["conflictChecksum"] = self._conflict_checksum(
                persisted_conflict
            )
            atomic_write_json(
                self.conflict_root / f"{expected_conflict_id}.json",
                persisted_conflict,
            )
            journal["status"] = "committed"
            journal["committedAt"] = utc_now()
            self._write_authorization_journal(
                expected_conflict_id,
                journal,
            )
            return receipt

    def record_connectivity_observation(
        self,
        *,
        folder_id: str,
        online: bool,
        device_id: str,
        reason: str = "",
        expected_revision: int,
    ) -> dict[str, Any]:
        """Durably record caller-observed offline/reconnect state."""

        self._require_boolean(online, field="online")
        expected = self._validated_revision(expected_revision)
        normalized_folder = self._validated_folder_id(folder_id)
        device_ref = self._required_device_ref(device_id)
        state_key = f"{normalized_folder}-{device_ref}"
        state_path = self.connectivity_root / f"{state_key}.json"
        with self._relationship_lock(f"connectivity:{state_key}"):
            previous = self._load_connectivity_state(
                state_path,
                folder_id=normalized_folder,
                device_ref=device_ref,
            )
            actual_revision = int(previous.get("revision") or 0)
            if expected != actual_revision:
                return self._stale_revision(
                    expected=expected,
                    actual=actual_revision,
                    device_ref=device_ref,
                )
            now = utc_now()
            previous_status = str(previous.get("status") or "")
            reconnect = bool(online and previous_status == "offline")
            receipt_status = (
                "reconnected"
                if reconnect
                else "observed_online"
                if online
                else "offline"
            )
            connection_status = "online" if online else "offline"
            reconnect_count = int(previous.get("reconnectCount") or 0) + int(
                reconnect
            )
            offline_since = (
                ""
                if online
                else str(previous.get("offlineSince") or now)
            )
            last_offline_interval = copy.deepcopy(
                previous.get("lastOfflineInterval")
            )
            if reconnect:
                last_offline_interval = {
                    "startedAt": str(previous.get("offlineSince") or ""),
                    "endedAt": now,
                }
            state = {
                "schema": FOLDER_SYNC_CONNECTIVITY_SCHEMA,
                "revision": actual_revision + 1,
                "folderId": normalized_folder,
                "deviceRef": device_ref,
                "status": connection_status,
                "lastObservation": receipt_status,
                "onlineObserved": online,
                "previousStatus": previous_status,
                "offlineSince": offline_since,
                "lastOfflineInterval": last_offline_interval,
                "lastObservedAt": now,
                "lastTransitionAt": (
                    now
                    if connection_status != previous_status
                    else str(previous.get("lastTransitionAt") or now)
                ),
                "reconnectCount": reconnect_count,
                "reconciliationRequired": bool(
                    reconnect or previous.get("reconciliationRequired")
                ),
                "observationSource": "caller",
                "providerProcessInspected": False,
                "serviceRunningClaimed": False,
                "reason": _redact_text(str(reason or ""))[:1000],
                "credentialsExposed": False,
            }
            state["integrityScope"] = "accidental-corruption-only"
            state["stateChecksum"] = self._connectivity_state_checksum(state)
            atomic_write_json(state_path, state)
            return self._receipt(
                "record-connectivity-observation",
                normalized_folder,
                ok=True,
                status=receipt_status,
                details={
                    "deviceRef": device_ref,
                    "revision": state["revision"],
                    "previousStatus": previous_status,
                    "onlineObserved": online,
                    "offlineSince": offline_since,
                    "lastOfflineInterval": last_offline_interval,
                    "reconnectCount": reconnect_count,
                    "reconciliationRequired": state[
                        "reconciliationRequired"
                    ],
                    "stateChecksum": state["stateChecksum"],
                    "reason": state["reason"],
                    "observationSource": "caller",
                    "providerProcessInspected": False,
                    "serviceRunningClaimed": False,
                },
            )

    @staticmethod
    def _conflict_checksum(conflict: dict[str, Any]) -> str:
        payload = copy.deepcopy(conflict)
        payload.pop("conflictChecksum", None)
        return _canonical_hash(payload)

    @staticmethod
    def _conflict_plan_checksum(plan: dict[str, Any]) -> str:
        payload = copy.deepcopy(plan)
        payload.pop("planChecksum", None)
        return _canonical_hash(payload)

    def _validate_conflict(self, conflict: dict[str, Any]) -> None:
        if (
            not isinstance(conflict, dict)
            or conflict.get("schema") != FOLDER_SYNC_CONFLICT_SCHEMA
        ):
            raise ValueError("Invalid folder-sync conflict schema")
        expected = str(conflict.get("conflictChecksum") or "")
        if not expected or expected != self._conflict_checksum(conflict):
            raise ValueError(
                "Folder-sync conflict accidental-corruption checksum "
                "does not match its contents"
            )
        self._validated_revision(conflict.get("revision"))
        self._validated_folder_id(str(conflict.get("folderId") or ""))
        self._normalized_relative_path(str(conflict.get("relativePath") or ""))
        local_value = conflict.get("local")
        remote_value = conflict.get("remote")
        if not isinstance(local_value, dict) or not isinstance(
            remote_value,
            dict,
        ):
            raise ValueError("Conflict sides must be objects")
        normalized_local = self._normalized_conflict_side(
            local_value,
            side="local",
        )
        normalized_remote = self._normalized_conflict_side(
            remote_value,
            side="remote",
        )
        if local_value != normalized_local or remote_value != normalized_remote:
            raise ValueError("Conflict sides are not in canonical form")
        if normalized_local["deleted"] and normalized_remote["deleted"]:
            raise ValueError("A conflict cannot contain two deleted sides")
        if normalized_local["deviceRef"] == normalized_remote["deviceRef"]:
            raise ValueError("Local and remote conflict devices must be distinct")
        identity = {
            "folderId": str(conflict.get("folderId") or ""),
            "relativePath": str(conflict.get("relativePath") or ""),
            "local": self._conflict_side_identity(normalized_local),
            "remote": self._conflict_side_identity(normalized_remote),
        }
        expected_conflict_id = "syncconflict_" + _canonical_hash(identity)[:24]
        if str(conflict.get("conflictId") or "") != expected_conflict_id:
            raise ValueError("Conflict identity does not match its contents")
        base_state = {
            "folderId": str(conflict.get("folderId") or ""),
            "relativePath": str(conflict.get("relativePath") or ""),
            "local": conflict.get("local"),
            "remote": conflict.get("remote"),
        }
        if _canonical_hash(base_state) != str(
            conflict.get("baseStateChecksum") or ""
        ):
            raise ValueError(
                "Conflict base-state accidental-corruption checksum does not "
                "match its contents"
            )

    def _persisted_conflict(self, conflict_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"syncconflict_[a-f0-9]{24}", conflict_id):
            raise ValueError("Invalid folder-sync conflict ID")
        path = self.conflict_root / f"{conflict_id}.json"
        if not path.is_file():
            raise RuntimeError(
                "Conflict authorization requires a durable current observation"
            )
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Stored folder-sync conflict observation is unreadable"
            ) from exc
        if not isinstance(value, dict):
            raise RuntimeError(
                "Stored folder-sync conflict observation must be an object"
            )
        self._validate_conflict(value)
        return value

    @staticmethod
    def _connectivity_state_checksum(state: dict[str, Any]) -> str:
        return _canonical_hash(
            {
                key: value
                for key, value in state.items()
                if key != "stateChecksum"
            }
        )

    def _validate_conflict_plan(self, plan: dict[str, Any]) -> None:
        if (
            not isinstance(plan, dict)
            or plan.get("schema") != FOLDER_SYNC_CONFLICT_PLAN_SCHEMA
        ):
            raise ValueError("Invalid folder-sync conflict plan schema")
        expected = str(plan.get("planChecksum") or "")
        if not expected or expected != self._conflict_plan_checksum(plan):
            raise ValueError(
                "Folder-sync conflict plan accidental-corruption checksum "
                "does not match its contents"
            )
        self._validated_folder_id(str(plan.get("folderId") or ""))
        self._normalized_relative_path(str(plan.get("relativePath") or ""))
        self._validated_revision(plan.get("conflictRevision"))

    def _persisted_conflict_plan(self, plan_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"syncconflictplan_[a-f0-9]{20}", plan_id):
            raise ValueError("Invalid folder-sync conflict plan ID")
        path = self.plan_root / f"{plan_id}.json"
        if not path.is_file():
            raise RuntimeError(
                "Conflict authorization requires a durable resolution plan"
            )
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Stored folder-sync conflict plan is unreadable"
            ) from exc
        if not isinstance(value, dict):
            raise RuntimeError(
                "Stored folder-sync conflict plan must be an object"
            )
        self._validate_conflict_plan(value)
        return value

    @staticmethod
    def _validated_folder_id(folder_id: str) -> str:
        normalized = str(folder_id or "").strip()
        if not _FOLDER_ID_PATTERN.fullmatch(normalized):
            raise ValueError("Invalid folder ID")
        return normalized

    @staticmethod
    def _validated_revision(value: object) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("expectedRevision must be a non-negative integer")
        return value

    @staticmethod
    def _require_boolean(value: object, *, field: str) -> bool:
        if not isinstance(value, bool):
            raise ValueError(f"{field} must be a boolean")
        return value

    def _required_device_ref(self, value: object) -> str:
        normalized = str(value or "").strip()
        if _DEVICE_REF_PATTERN.fullmatch(normalized):
            return normalized
        if not _DEVICE_ID_PATTERN.fullmatch(normalized):
            raise ValueError("A valid Syncthing device identity is required")
        return self._device_ref(normalized)

    def _relationship_lock(self, relationship_key: str) -> Any:
        digest = hashlib.sha256(
            str(relationship_key).encode("utf-8")
        ).hexdigest()
        return _exclusive_file_lock(self.lock_root / f"{digest}.lock")

    @staticmethod
    def _stale_revision(
        *,
        expected: int,
        actual: int,
        conflict_id: str = "",
        device_ref: str = "",
    ) -> dict[str, Any]:
        result = {
            "ok": False,
            "status": "stale_revision",
            "expectedRevision": expected,
            "actualRevision": actual,
            "executionPerformed": False,
        }
        if conflict_id:
            result["conflictId"] = conflict_id
        if device_ref:
            result["deviceRef"] = device_ref
        return result

    @staticmethod
    def _stale_observation(
        conflict_id: str,
        persisted: dict[str, Any],
        supplied: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "stale_observation",
            "conflictId": conflict_id,
            "suppliedBaseStateChecksum": str(
                supplied.get("baseStateChecksum") or ""
            ),
            "actualBaseStateChecksum": str(
                persisted.get("baseStateChecksum") or ""
            ),
            "suppliedRevision": int(supplied.get("revision") or -1),
            "actualRevision": int(persisted.get("revision") or 0),
            "executionPerformed": False,
        }

    def _load_connectivity_state(
        self,
        path: Path,
        *,
        folder_id: str,
        device_ref: str,
    ) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Stored folder-sync connectivity state is unreadable"
            ) from exc
        if not isinstance(candidate, dict):
            raise RuntimeError(
                "Stored folder-sync connectivity state must be an object"
            )
        if candidate.get("schema") != FOLDER_SYNC_CONNECTIVITY_SCHEMA:
            raise RuntimeError(
                "Stored folder-sync connectivity state has an invalid schema"
            )
        if (
            str(candidate.get("folderId") or "") != folder_id
            or str(candidate.get("deviceRef") or "") != device_ref
        ):
            raise RuntimeError(
                "Stored connectivity state does not match its relationship"
            )
        self._validated_revision(candidate.get("revision"))
        expected_state_checksum = str(candidate.get("stateChecksum") or "")
        if (
            not expected_state_checksum
            or expected_state_checksum
            != self._connectivity_state_checksum(candidate)
        ):
            raise RuntimeError(
                "Stored folder-sync connectivity state failed accidental-"
                "corruption integrity validation"
            )
        return candidate

    def _provider_resolution_evidence(
        self,
        folder_id: str,
        relative_path: str,
        conflict: dict[str, Any],
        actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            folder = self._folder_config(folder_id)
            status = self._request("GET", "/rest/system/status")
            if not isinstance(status, dict):
                raise RuntimeError("Syncthing status response must be an object")
            local_device_id = str(status.get("myID") or "")
            if not _DEVICE_ID_PATTERN.fullmatch(local_device_id):
                raise RuntimeError("Syncthing local device identity is unavailable")
            folder_path = self._allowed_folder_path(
                str(folder.get("path") or "")
            )
            target_path = (folder_path / relative_path).resolve()
            target_path.relative_to(folder_path)
        except (KeyError, RuntimeError, ValueError, OSError):
            return {
                "required": True,
                "providerVerified": False,
                "providerMetadataVerified": False,
                "localBytesVerified": False,
                "folderMembershipVerified": False,
                "activeVersioning": False,
                "reason": "provider-resolution-evidence-unavailable",
            }
        local_device_ref = self._device_ref(local_device_id)
        local_observation = dict(conflict.get("local") or {})
        remote_observation = dict(conflict.get("remote") or {})
        local_identity_verified = (
            str(local_observation.get("deviceRef") or "")
            == local_device_ref
        )
        configured_peer_identities = sorted(
            [
                {
                    "deviceRef": self._device_ref(
                        str(item.get("deviceID") or "")
                    ),
                    "deviceIdentityDigest": self._device_identity_digest(
                        str(item.get("deviceID") or "")
                    ),
                }
                for item in (
                    folder.get("devices")
                    if isinstance(folder.get("devices"), list)
                    else []
                )
                if (
                    isinstance(item, dict)
                    and _DEVICE_ID_PATTERN.fullmatch(
                        str(item.get("deviceID") or "")
                    )
                )
            ],
            key=lambda item: (
                item["deviceRef"],
                item["deviceIdentityDigest"],
            ),
        )
        configured_peer_refs = [
            item["deviceRef"] for item in configured_peer_identities
        ]
        remote_device_ref = str(remote_observation.get("deviceRef") or "")
        remote_identity_digest = str(
            remote_observation.get("deviceIdentityDigest") or ""
        )
        membership_verified = any(
            remote_device_ref == item["deviceRef"]
            and remote_identity_digest == item["deviceIdentityDigest"]
            for item in configured_peer_identities
        )
        local_identity_digest = self._device_identity_digest(local_device_id)
        local_identity_verified = bool(
            local_identity_verified
            and str(
                local_observation.get("deviceIdentityDigest") or ""
            )
            == local_identity_digest
        )
        exclusive_destinations: list[dict[str, Any]] = []
        try:
            for action in actions:
                if (
                    action.get("destinationWriteMode")
                    != "create-exclusive"
                    or str(action.get("destinationDeviceRef") or "")
                    != local_device_ref
                ):
                    continue
                action_path = self._normalized_relative_path(
                    str(action.get("path") or "")
                )
                destination_path = (folder_path / action_path).resolve()
                destination_path.relative_to(folder_path)
                exclusive_destinations.append(
                    {
                        "relativePath": action_path,
                        "absenceVerified": not os.path.lexists(
                            str(destination_path)
                        ),
                        "writeMode": "create-exclusive",
                        "collisionResistanceBits": int(
                            action.get("collisionResistanceBits") or 0
                        ),
                    }
                )
        except (OSError, ValueError):
            return {
                "required": True,
                "providerVerified": False,
                "providerMetadataVerified": False,
                "localBytesVerified": False,
                "folderMembershipVerified": False,
                "exclusiveDestinationAbsenceVerified": False,
                "activeVersioning": False,
                "reason": "provider-resolution-evidence-unavailable",
            }
        exclusive_destinations_verified = all(
            bool(item["absenceVerified"])
            and int(item["collisionResistanceBits"]) >= 96
            for item in exclusive_destinations
        )
        observed_local_hash = str(
            local_observation.get("contentHash") or ""
        )
        actual_local_hash = ""
        local_deleted = bool(local_observation.get("deleted"))
        if local_deleted:
            local_bytes_verified = not target_path.exists()
        else:
            try:
                actual_local_hash = (
                    _sha256_file(target_path) if target_path.is_file() else ""
                )
            except OSError:
                actual_local_hash = ""
            local_bytes_verified = bool(
                actual_local_hash
                and actual_local_hash == observed_local_hash
            )
        versioning = folder.get("versioning")
        versioning_row = (
            dict(versioning) if isinstance(versioning, dict) else {}
        )
        version_type = str(versioning_row.get("type") or "").casefold()
        active = version_type in set(
            self.policy.get("versioningTypes") or []
        )
        membership_state = {
            "folderId": folder_id,
            "localDeviceRef": local_device_ref,
            "localDeviceIdentityDigest": local_identity_digest,
            "remoteDeviceRef": remote_device_ref,
            "remoteDeviceIdentityDigest": remote_identity_digest,
            "configuredPeerIdentities": configured_peer_identities,
        }
        provider_state = {
            **membership_state,
            "relativePath": relative_path,
            "pathDisplay": self._display_path(str(target_path)),
            "versioningType": version_type,
            "versioningParams": {
                str(key): str(value)
                for key, value in dict(
                    versioning_row.get("params") or {}
                ).items()
            },
            "cleanupIntervalS": str(
                versioning_row.get("cleanupIntervalS") or "0"
            ),
            "localFileSha256": actual_local_hash,
            "localAbsenceVerified": bool(
                local_deleted and local_bytes_verified
            ),
            "exclusiveDestinations": exclusive_destinations,
        }
        provider_verified = bool(
            local_identity_verified
            and membership_verified
            and local_bytes_verified
            and exclusive_destinations_verified
        )
        return {
            "required": True,
            "providerVerified": provider_verified,
            "providerMetadataVerified": True,
            "localIdentityVerified": local_identity_verified,
            "localBytesVerified": local_bytes_verified,
            "folderMembershipVerified": membership_verified,
            "folderPathVerified": True,
            "exclusiveDestinationAbsenceVerified": (
                exclusive_destinations_verified
            ),
            "exclusiveDestinations": exclusive_destinations,
            "activeVersioning": active,
            "localDeviceRef": local_device_ref,
            "remoteDeviceRef": remote_device_ref,
            "configuredPeerRefs": configured_peer_refs,
            "localFileSha256": actual_local_hash,
            "observedLocalContentHash": observed_local_hash,
            "localAbsenceVerified": bool(
                local_deleted and local_bytes_verified
            ),
            "versioningType": version_type,
            "folderMembershipChecksum": _canonical_hash(membership_state),
            "providerEvidenceChecksum": _canonical_hash(provider_state),
            "verifiedAt": utc_now(),
            "reason": (
                "provider-local-bytes-and-membership-verified"
                if provider_verified
                else (
                    "exclusive-destination-absence-or-name-unverified"
                    if not exclusive_destinations_verified
                    else "provider-local-bytes-or-membership-unverified"
                )
            ),
            "callerObservationAuthoritative": False,
            "remoteFileContentVerified": False,
            "remoteDestinationVersioningVerified": False,
            "evidenceScope": (
                "authenticated-local-provider-config-and-local-filesystem"
            ),
            "integrityScope": "executor-must-recheck-provider-facts",
        }

    @staticmethod
    def _journal_checksum(value: dict[str, Any]) -> str:
        payload = copy.deepcopy(value)
        payload.pop("journalChecksum", None)
        return _canonical_hash(payload)

    def _write_authorization_journal(
        self,
        conflict_id: str,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        row = copy.deepcopy(value)
        row["schema"] = FOLDER_SYNC_AUTH_TRANSACTION_SCHEMA
        row["conflictId"] = conflict_id
        row["integrityScope"] = "accidental-corruption-only"
        row["journalChecksum"] = self._journal_checksum(row)
        atomic_write_json(
            self.transaction_root / f"{conflict_id}.json",
            row,
        )
        return row

    def _archive_authorization_journal(
        self,
        value: dict[str, Any],
    ) -> None:
        transaction_id = str(value.get("transactionId") or "")
        if not re.fullmatch(r"synctxn_[a-f0-9]{20}", transaction_id):
            return
        atomic_write_json(
            self.transaction_archive_root / f"{transaction_id}.json",
            copy.deepcopy(value),
        )

    @staticmethod
    def _supersession_matches_conflict(
        journal: dict[str, Any],
        conflict: dict[str, Any] | None,
    ) -> bool:
        if not conflict:
            return False
        return bool(
            int(conflict.get("revision") or -1)
            == int(journal.get("supersededByRevision") or -2)
            and str(conflict.get("baseStateChecksum") or "")
            == str(journal.get("supersededByBaseStateChecksum") or "")
            and str(conflict.get("conflictChecksum") or "")
            == str(journal.get("supersededByConflictChecksum") or "")
        )

    def _retire_observation_journal(
        self,
        conflict_id: str,
        journal: dict[str, Any],
    ) -> dict[str, Any]:
        retired = copy.deepcopy(journal)
        retired["status"] = "superseded-by-new-observation"
        retired["classification"] = "superseded-by-new-observation"
        retired["supersededAt"] = utc_now()
        retired = self._write_authorization_journal(
            conflict_id,
            retired,
        )
        self._archive_authorization_journal(retired)
        return retired

    def _observation_journal(
        self,
        conflict_id: str,
        conflict: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        journal = self._load_authorization_journal(conflict_id)
        if not journal:
            return None
        status = str(journal.get("status") or "")
        if status in {
            "abandoned_pre_receipt",
            "orphan_receipt",
            "superseded-by-new-observation",
        }:
            self._archive_authorization_journal(journal)
            return None
        if status == "observation_supersession_prepared":
            if self._supersession_matches_conflict(journal, conflict):
                self._retire_observation_journal(
                    conflict_id,
                    journal,
                )
                return None
        return journal

    def _committed_journal_matches_conflict(
        self,
        journal: dict[str, Any],
        conflict: dict[str, Any] | None,
    ) -> bool:
        if not conflict:
            return False
        source_revision = journal.get("sourceRevision")
        target_revision = journal.get("targetRevision")
        transaction_id = str(journal.get("transactionId") or "")
        receipt_id = str(journal.get("receiptId") or "")
        if (
            not isinstance(source_revision, int)
            or isinstance(source_revision, bool)
            or not isinstance(target_revision, int)
            or isinstance(target_revision, bool)
            or target_revision != source_revision + 1
            or not re.fullmatch(r"synctxn_[a-f0-9]{20}", transaction_id)
            or not re.fullmatch(r"syncreceipt_[a-f0-9]{20}", receipt_id)
            or not _CONTENT_HASH_PATTERN.fullmatch(
                str(journal.get("planChecksum") or "")
            )
            or not _CONTENT_HASH_PATTERN.fullmatch(
                str(journal.get("baseStateChecksum") or "")
            )
        ):
            return False
        receipt = self._load_authorization_receipt(receipt_id)
        return bool(
            int(conflict.get("revision") or -1) == target_revision
            and str(conflict.get("authorizationReceiptId") or "")
            == receipt_id
            and str(conflict.get("baseStateChecksum") or "")
            == str(journal.get("baseStateChecksum") or "")
            and self._authorization_receipt_matches(receipt, journal)
        )

    def _prepare_observation_supersession(
        self,
        conflict_id: str,
        *,
        journal: dict[str, Any] | None,
        current_conflict: dict[str, Any] | None,
        next_conflict: dict[str, Any],
    ) -> dict[str, Any]:
        if not journal:
            return {"blocked": False}
        status = str(journal.get("status") or "")
        if status not in {
            "committed",
            "committed_recovered",
            "observation_supersession_prepared",
        }:
            return {
                "blocked": True,
                "result": {
                    "ok": False,
                    "status": "authorization_journal_blocks_observation",
                    "conflictId": conflict_id,
                    "journalStatus": status,
                    "authoritative": False,
                    "retryAllowed": False,
                    "executionPerformed": False,
                },
            }
        if not self._committed_journal_matches_conflict(
            journal,
            current_conflict,
        ):
            return {
                "blocked": True,
                "result": self._journal_inconsistent(
                    conflict_id,
                    journal,
                    classification=(
                        "committed-binding-invalid-for-new-observation"
                    ),
                    actual_revision=(
                        int(current_conflict.get("revision") or 0)
                        if current_conflict
                        else 0
                    ),
                ),
            }
        current_revision = int(current_conflict.get("revision") or 0)
        next_revision = int(next_conflict.get("revision") or 0)
        current_base = str(
            current_conflict.get("baseStateChecksum") or ""
        )
        next_base = str(next_conflict.get("baseStateChecksum") or "")
        if (
            next_revision <= current_revision
            or next_revision <= int(journal.get("targetRevision") or 0)
            or next_base == current_base
        ):
            return {
                "blocked": True,
                "result": {
                    "ok": False,
                    "status": "observation_not_strictly_newer",
                    "conflictId": conflict_id,
                    "expectedRevision": current_revision,
                    "actualRevision": next_revision,
                    "executionPerformed": False,
                },
            }
        expected_supersession = {
            "supersededFromRevision": current_revision,
            "supersededFromBaseStateChecksum": current_base,
            "supersededFromConflictChecksum": str(
                current_conflict.get("conflictChecksum") or ""
            ),
            "supersededByRevision": next_revision,
            "supersededByBaseStateChecksum": next_base,
            "supersededByConflictChecksum": str(
                next_conflict.get("conflictChecksum") or ""
            ),
        }
        if status == "observation_supersession_prepared":
            stable_keys = {
                "supersededFromRevision",
                "supersededFromBaseStateChecksum",
                "supersededFromConflictChecksum",
                "supersededByRevision",
                "supersededByBaseStateChecksum",
            }
            if any(
                journal.get(key) != value
                for key, value in expected_supersession.items()
                if key in stable_keys
            ):
                return {
                    "blocked": True,
                    "result": self._journal_inconsistent(
                        conflict_id,
                        journal,
                        classification="prepared-supersession-mismatch",
                        actual_revision=current_revision,
                    ),
                }
            if (
                journal.get("supersededByConflictChecksum")
                != expected_supersession["supersededByConflictChecksum"]
            ):
                journal = {
                    **journal,
                    "supersededByConflictChecksum": (
                        expected_supersession[
                            "supersededByConflictChecksum"
                        ]
                    ),
                    "supersessionPreparedAt": utc_now(),
                }
                journal = self._write_authorization_journal(
                    conflict_id,
                    journal,
                )
            return {"blocked": False, "journal": journal}
        prepared = {
            **journal,
            **expected_supersession,
            "status": "observation_supersession_prepared",
            "supersessionPreparedAt": utc_now(),
        }
        prepared = self._write_authorization_journal(
            conflict_id,
            prepared,
        )
        return {"blocked": False, "journal": prepared}

    def _load_authorization_journal(
        self,
        conflict_id: str,
    ) -> dict[str, Any] | None:
        path = self.transaction_root / f"{conflict_id}.json"
        if not path.is_file():
            return None
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Stored folder-sync authorization journal is unreadable"
            ) from exc
        if (
            not isinstance(row, dict)
            or row.get("schema") != FOLDER_SYNC_AUTH_TRANSACTION_SCHEMA
            or str(row.get("conflictId") or "") != conflict_id
            or str(row.get("journalChecksum") or "")
            != self._journal_checksum(row)
        ):
            raise RuntimeError(
                "Stored folder-sync authorization journal failed accidental-"
                "corruption integrity validation"
            )
        return row

    def _recover_authorization_journal(
        self,
        conflict_id: str,
        conflict: dict[str, Any],
    ) -> dict[str, Any] | None:
        journal = self._load_authorization_journal(conflict_id)
        if not journal:
            return None
        status = str(journal.get("status") or "")
        if status in {
            "abandoned_pre_receipt",
            "orphan_receipt",
            "superseded-by-new-observation",
        }:
            # These records are classifications, not authorization. A fresh
            # explicitly approved retry may replace the current transaction
            # after the orphan has been durably identified.
            self._archive_authorization_journal(journal)
            return None
        if status == "observation_supersession_prepared":
            if self._supersession_matches_conflict(journal, conflict):
                self._retire_observation_journal(
                    conflict_id,
                    journal,
                )
                return None
            return {
                "ok": False,
                "status": "authorization_journal_supersession_incomplete",
                "conflictId": conflict_id,
                "receiptId": str(journal.get("receiptId") or ""),
                "authoritative": False,
                "retryAllowed": False,
                "executionPerformed": False,
            }
        if status == "inconsistent":
            return {
                "ok": False,
                "status": "authorization_journal_inconsistent",
                "conflictId": conflict_id,
                "receiptId": str(journal.get("receiptId") or ""),
                "classification": str(
                    journal.get("classification") or ""
                ),
                "authoritative": False,
                "retryAllowed": False,
                "executionPerformed": False,
            }
        if status not in {
            "prepared",
            "receipt_written",
            "committed",
            "committed_recovered",
        }:
            return self._journal_inconsistent(
                conflict_id,
                journal,
                classification="unknown-transaction-state",
            )
        target_revision = self._validated_revision(
            journal.get("targetRevision")
        )
        source_revision = self._validated_revision(
            journal.get("sourceRevision")
        )
        transaction_id = str(journal.get("transactionId") or "")
        receipt_id = str(journal.get("receiptId") or "")
        if (
            not re.fullmatch(r"synctxn_[a-f0-9]{20}", transaction_id)
            or not re.fullmatch(r"syncreceipt_[a-f0-9]{20}", receipt_id)
            or target_revision != source_revision + 1
            or not re.fullmatch(
                r"syncconflictplan_[a-f0-9]{20}",
                str(journal.get("planId") or ""),
            )
            or not _CONTENT_HASH_PATTERN.fullmatch(
                str(journal.get("planChecksum") or "")
            )
            or not _CONTENT_HASH_PATTERN.fullmatch(
                str(journal.get("baseStateChecksum") or "")
            )
        ):
            return self._journal_inconsistent(
                conflict_id,
                journal,
                classification="invalid-transaction-binding",
            )
        actual_revision = int(conflict.get("revision") or 0)
        receipt = self._load_authorization_receipt(receipt_id)
        receipt_matches = self._authorization_receipt_matches(
            receipt,
            journal,
        )
        conflict_matches = bool(
            actual_revision == target_revision
            and str(conflict.get("authorizationReceiptId") or "")
            == receipt_id
        )
        if status in {"committed", "committed_recovered"}:
            if conflict_matches and receipt_matches:
                return None
            return self._journal_inconsistent(
                conflict_id,
                journal,
                classification="committed-binding-incomplete",
                actual_revision=actual_revision,
            )
        if conflict_matches and receipt_matches:
            journal["status"] = "committed_recovered"
            journal["classification"] = "receipt-and-conflict-binding-observed"
            journal["classifiedAt"] = utc_now()
            self._write_authorization_journal(conflict_id, journal)
            return None
        if conflict_matches:
            return self._journal_inconsistent(
                conflict_id,
                journal,
                classification="conflict-bound-receipt-missing-or-invalid",
                actual_revision=actual_revision,
            )
        if receipt is not None:
            journal["status"] = "orphan_receipt"
            journal["classification"] = (
                "receipt-written-before-conflict-binding"
                if receipt_matches
                else "receipt-content-does-not-match-transaction"
            )
            journal["classifiedAt"] = utc_now()
            recovered = self._write_authorization_journal(
                conflict_id,
                journal,
            )
            self._archive_authorization_journal(recovered)
            return {
                "ok": False,
                "status": "orphan_receipt_detected",
                "conflictId": conflict_id,
                "receiptId": receipt_id,
                "classification": recovered["classification"],
                "expectedRevision": target_revision,
                "actualRevision": actual_revision,
                "authoritative": False,
                "retryAllowed": True,
                "executionPerformed": False,
            }
        if actual_revision != source_revision:
            return self._journal_inconsistent(
                conflict_id,
                journal,
                classification="revision-changed-without-transaction-binding",
                actual_revision=actual_revision,
            )
        journal["status"] = "abandoned_pre_receipt"
        journal["classification"] = "prepared-without-receipt"
        journal["classifiedAt"] = utc_now()
        classified = self._write_authorization_journal(conflict_id, journal)
        self._archive_authorization_journal(classified)
        return None

    def _load_authorization_receipt(
        self,
        receipt_id: str,
    ) -> dict[str, Any] | None:
        if not re.fullmatch(r"syncreceipt_[a-f0-9]{20}", receipt_id):
            return None
        path = self.receipt_root / f"{receipt_id}.json"
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _authorization_receipt_matches(
        receipt: dict[str, Any] | None,
        journal: dict[str, Any],
    ) -> bool:
        if not receipt:
            return False
        details = receipt.get("details")
        if not isinstance(details, dict):
            return False
        return bool(
            receipt.get("schema") == FOLDER_SYNC_RECEIPT_SCHEMA
            and receipt.get("operation") == "authorize-conflict-resolution"
            and receipt.get("ok") is True
            and receipt.get("status") == "resolution_authorized"
            and str(receipt.get("receiptId") or "")
            == str(journal.get("receiptId") or "")
            and str(details.get("journalTransactionRef") or "")
            == str(journal.get("transactionId") or "")
            and str(details.get("conflictId") or "")
            == str(journal.get("conflictId") or "")
            and str(details.get("planId") or "")
            == str(journal.get("planId") or "")
            and str(details.get("planChecksum") or "")
            == str(journal.get("planChecksum") or "")
            and str(details.get("baseStateChecksum") or "")
            == str(journal.get("baseStateChecksum") or "")
            and details.get("revision") == journal.get("targetRevision")
            and details.get("executorExpectedRevision")
            == journal.get("targetRevision")
            and details.get("commitRequirement")
            == "matching-committed-journal-and-conflict-binding"
            and str(
                details.get(
                    "executorExpectedProviderEvidenceChecksum"
                )
                or ""
            )
            == str(journal.get("providerEvidenceChecksum") or "")
            and details.get("executionPerformed") is False
        )

    def _journal_inconsistent(
        self,
        conflict_id: str,
        journal: dict[str, Any],
        *,
        classification: str,
        actual_revision: int | None = None,
    ) -> dict[str, Any]:
        journal["status"] = "inconsistent"
        journal["classification"] = classification
        journal["classifiedAt"] = utc_now()
        self._write_authorization_journal(conflict_id, journal)
        result = {
            "ok": False,
            "status": "authorization_journal_inconsistent",
            "conflictId": conflict_id,
            "receiptId": str(journal.get("receiptId") or ""),
            "classification": classification,
            "authoritative": False,
            "retryAllowed": False,
            "executionPerformed": False,
        }
        if actual_revision is not None:
            result["actualRevision"] = actual_revision
        return result

    @staticmethod
    def _normalized_relative_path(value: str) -> str:
        raw = str(value or "")
        normalized = raw.replace("\\", "/").strip("/")
        candidate = PurePosixPath(normalized)
        if (
            not normalized
            or raw.startswith(("/", "\\"))
            or ":" in candidate.parts[0]
            or any(part in {"", ".", ".."} for part in candidate.parts)
            or "\x00" in normalized
            or len(normalized) > 1024
        ):
            raise ValueError(
                "Conflict path must be a bounded relative path inside the folder"
            )
        return candidate.as_posix()

    def _normalized_conflict_side(
        self,
        value: dict[str, Any],
        *,
        side: str,
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"{side} conflict state must be an object")
        deleted_value = value.get("deleted")
        self._require_boolean(deleted_value, field=f"{side}.deleted")
        deleted = deleted_value
        if "version" in value or "versioningEnabled" in value:
            raise ValueError(
                f"{side} conflict state must not supply versioning assertions"
            )
        content_hash = str(value.get("contentHash") or "").strip().casefold()
        if content_hash and not _CONTENT_HASH_PATTERN.fullmatch(content_hash):
            raise ValueError(f"{side} contentHash must be a SHA-256 digest")
        if not deleted and not content_hash:
            raise ValueError(
                f"{side} conflict state requires a SHA-256 contentHash"
            )
        modified_at = str(value.get("modifiedAt") or "")[:64]
        if _redact_text(modified_at) != modified_at:
            raise ValueError(
                f"{side} conflict metadata must not contain secret-like text"
            )
        supplied_device_ref = str(value.get("deviceRef") or "").strip()
        supplied_identity_digest = str(
            value.get("deviceIdentityDigest") or ""
        ).strip().casefold()
        if supplied_identity_digest and not _CONTENT_HASH_PATTERN.fullmatch(
            supplied_identity_digest
        ):
            raise ValueError(
                f"{side} deviceIdentityDigest must be a SHA-256 digest"
            )
        device_ref: str
        device_identity_digest = supplied_identity_digest
        if value.get("deviceId"):
            device_id = str(value.get("deviceId") or "").strip()
            device_ref = self._required_device_ref(device_id)
            calculated_digest = self._device_identity_digest(device_id)
            if (
                supplied_identity_digest
                and supplied_identity_digest != calculated_digest
            ):
                raise ValueError(
                    f"{side} device identity digest does not match deviceId"
                )
            device_identity_digest = calculated_digest
        elif supplied_device_ref:
            device_ref = self._required_device_ref(supplied_device_ref)
        else:
            raise ValueError(f"{side} conflict state requires a device identity")
        try:
            normalized_size = int(value.get("size") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{side} size must be an integer") from exc
        return {
            "deleted": deleted,
            "contentHash": "" if deleted else content_hash,
            "modifiedAt": modified_at,
            "size": max(0, min(normalized_size, 9_223_372_036_854_775_807)),
            "deviceRef": device_ref,
            "deviceIdentityDigest": device_identity_digest,
            "observationTrust": "unverifiedObservation",
        }

    @staticmethod
    def _conflict_side_identity(value: dict[str, Any]) -> dict[str, Any]:
        # Content/version drift belongs in baseStateChecksum. The opaque identity
        # remains stable for the same folder path and observed peer.
        return {
            "deviceRef": str(value.get("deviceRef") or ""),
            "deviceIdentityDigest": str(
                value.get("deviceIdentityDigest") or ""
            ),
        }

    @staticmethod
    def _conflict_copy_path(relative_path: str, conflict_id: str) -> str:
        path = PurePosixPath(relative_path)
        suffix = path.suffix
        stem = path.name[: -len(suffix)] if suffix else path.name
        marker = (
            ".neyvia-conflict-"
            f"{conflict_id.removeprefix('syncconflict_')[:24]}"
        )
        maximum_stem = max(1, 240 - len(marker) - len(suffix))
        copy_name = (
            f"{stem[:maximum_stem]}{marker}"
            f"{suffix}"
        )
        return str(path.with_name(copy_name))

    @staticmethod
    def _remote_source_verification_contract(
        remote: dict[str, Any],
    ) -> dict[str, Any]:
        expected_sha256 = str(remote.get("contentHash") or "")
        if not _CONTENT_HASH_PATTERN.fullmatch(expected_sha256):
            raise ValueError(
                "Remote byte source requires an exact persisted SHA-256"
            )
        return {
            "stagingRequired": True,
            "stageSeparateFromDestination": True,
            "expectedPersistedRemoteSha256": expected_sha256,
            "verifyStagedSha256BeforeCommit": True,
            "commitOnlyAfterVerification": True,
            "observationTrust": "unverifiedObservation",
        }

    def _conflict_actions(
        self,
        resolution: str,
        *,
        conflict_id: str,
        relative_path: str,
        local: dict[str, Any],
        remote: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if resolution == "keep-both":
            if local["deleted"]:
                return [
                    {
                        "operation": "restore-local-from-remote",
                        "source": "remote",
                        "destination": "local",
                        "sourceDeviceRef": remote["deviceRef"],
                        "destinationDeviceRef": local["deviceRef"],
                        "path": relative_path,
                        "destructive": False,
                        "sourceVerification": (
                            self._remote_source_verification_contract(remote)
                        ),
                        "destinationWriteMode": "create-exclusive",
                        "destinationMustBeAbsent": True,
                        "collisionResistanceBits": 96,
                    }
                ]
            if remote["deleted"]:
                return [
                    {
                        "operation": "restore-remote-from-local",
                        "source": "local",
                        "destination": "remote",
                        "sourceDeviceRef": local["deviceRef"],
                        "destinationDeviceRef": remote["deviceRef"],
                        "path": relative_path,
                        "destructive": False,
                    }
                ]
            return [
                {
                    "operation": "copy-remote-to-local-sibling",
                    "source": "remote",
                    "destination": "local",
                    "sourceDeviceRef": remote["deviceRef"],
                    "destinationDeviceRef": local["deviceRef"],
                    "path": self._conflict_copy_path(
                        relative_path,
                        conflict_id,
                    ),
                    "destructive": False,
                    "sourceVerification": (
                        self._remote_source_verification_contract(remote)
                    ),
                    "destinationWriteMode": "create-exclusive",
                    "destinationMustBeAbsent": True,
                    "collisionResistanceBits": 96,
                }
            ]
        source_name, destination_name = (
            ("local", "remote")
            if resolution == "keep-local"
            else ("remote", "local")
        )
        source = local if source_name == "local" else remote
        destination = remote if destination_name == "remote" else local
        if source["deleted"]:
            operation = f"delete-{destination_name}"
            destructive = not bool(destination["deleted"])
        elif destination["deleted"]:
            operation = f"restore-{destination_name}-from-{source_name}"
            destructive = False
        else:
            operation = f"replace-{destination_name}-from-{source_name}"
            destructive = True
        action = {
            "operation": operation,
            "source": source_name,
            "destination": destination_name,
            "sourceDeviceRef": source["deviceRef"],
            "destinationDeviceRef": destination["deviceRef"],
            "path": relative_path,
            "destructive": destructive,
        }
        if source_name == "remote" and not bool(remote["deleted"]):
            action["sourceVerification"] = (
                self._remote_source_verification_contract(remote)
            )
        return [action]

    def override_folder(
        self,
        folder_id: str,
        *,
        confirmation: str,
        approved: bool = False,
    ) -> dict[str, Any]:
        return self._dangerous_recovery(
            "override",
            folder_id,
            confirmation=confirmation,
            approved=approved,
            required_type="sendonly",
        )

    def revert_folder(
        self,
        folder_id: str,
        *,
        confirmation: str,
        approved: bool = False,
    ) -> dict[str, Any]:
        return self._dangerous_recovery(
            "revert",
            folder_id,
            confirmation=confirmation,
            approved=approved,
            required_type="receiveonly",
        )

    @_proofs_b_checked("sync-recovery")
    def _dangerous_recovery(
        self,
        action: str,
        folder_id: str,
        *,
        confirmation: str,
        approved: bool,
        required_type: str,
    ) -> dict[str, Any]:
        if not approved or str(confirmation) != str(folder_id):
            return self._approval_required(
                f"sync.{action}",
                f"{action.title()} can delete files; confirm with the exact folder ID.",
            )
        folder = self._folder_config(folder_id)
        folder_type = str(folder.get("type") or "")
        if folder_type != required_type:
            raise ValueError(
                f"{action} is valid only for {required_type} folders"
            )
        self._request(
            "POST",
            f"/rest/db/{action}",
            query={"folder": folder_id},
            timeout_seconds=60,
        )
        return self._receipt(
            f"{action}-folder",
            folder_id,
            ok=True,
            status=f"{action}_requested",
            details={
                "mode": folder_type,
                "exactFolderConfirmation": True,
                "canDeleteFiles": True,
            },
        )

    def _folder_config(self, folder_id: str) -> dict[str, Any]:
        normalized = str(folder_id or "").strip()
        if not _FOLDER_ID_PATTERN.fullmatch(normalized):
            raise ValueError("Invalid folder ID")
        value = self._request(
            "GET",
            f"/rest/config/folders/{urllib.parse.quote(normalized, safe='')}",
        )
        if not isinstance(value, dict) or str(value.get("id") or "") != normalized:
            raise KeyError(f"Unknown Syncthing folder: {normalized}")
        return value

    @staticmethod
    def _approval_required(
        permission: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "approval_required",
            "requiredPermission": permission,
            "reason": reason,
        }

    def _receipt(
        self,
        operation: str,
        folder_id: str,
        *,
        ok: bool,
        status: str,
        details: dict[str, Any],
        receipt_id: str | None = None,
    ) -> dict[str, Any]:
        selected_receipt_id = str(
            receipt_id or f"syncreceipt_{uuid.uuid4().hex[:20]}"
        )
        if not re.fullmatch(r"syncreceipt_[a-f0-9]{20}", selected_receipt_id):
            raise ValueError("Invalid folder-sync receipt ID")
        receipt = {
            "schema": FOLDER_SYNC_RECEIPT_SCHEMA,
            "receiptId": selected_receipt_id,
            "createdAt": utc_now(),
            "provider": "syncthing",
            "operation": operation,
            "folderId": folder_id,
            "ok": bool(ok),
            "status": status,
            "details": _redact_value(details),
            "credentialsExposed": False,
        }
        atomic_write_json(
            self.receipt_root / f"{receipt['receiptId']}.json",
            receipt,
        )
        return receipt

    def _invalidate_cache(self) -> None:
        with self._cache_lock:
            self._health_cache = None
