"""LocalSend-compatible nearby transfer with pinned identity and receipts."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import mimetypes
import os
import socket
import ssl
import threading
import time
import uuid
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlencode, urlparse

from .capability_contracts import utc_now
from .durability import atomic_write_json


NEARBY_DISCOVERY_SCHEMA = "neyvia.nearby-discovery/v1"
NEARBY_TRANSFER_PLAN_SCHEMA = "neyvia.nearby-transfer-plan/v1"
NEARBY_TRANSFER_RECEIPT_SCHEMA = "neyvia.nearby-transfer-receipt/v1"
NEARBY_TRANSFER_HISTORY_SCHEMA = "neyvia.nearby-transfer-history/v1"
NEARBY_TRANSFER_PROGRESS_SCHEMA = "neyvia.nearby-transfer-progress/v1"
NEARBY_TRANSFER_STATE_SCHEMA = "neyvia.nearby-transfer-state/v1"
NEARBY_CANCEL_REQUEST_SCHEMA = "neyvia.nearby-cancel-request/v1"
NEARBY_CHUNK_TRANSFER_SCHEMA = "neyvia.nearby-chunk-transfer/v1"

_ACTIVE_TRANSFER_STATES = frozenset(
    {"preparing", "uploading", "cancel_requested", "cancelling"}
)
_MAX_PUBLIC_HISTORY = 100
_MAX_PUBLIC_FILES = 100
_MAX_STATE_BYTES = 4 * 1024 * 1024
_MAX_RECEIPT_BYTES = 4 * 1024 * 1024
_UPLOAD_CHUNK_BYTES = 256 * 1024
_DEFAULT_TRANSFER_CHUNK_BYTES = 8 * 1024 * 1024
_MAX_TRANSFER_CHUNK_BYTES = 64 * 1024 * 1024
_MAX_TRANSFER_PARTS = 4096
_PROCESS_STATE_LOCKS_GUARD = threading.Lock()
_PROCESS_STATE_LOCKS: dict[str, threading.RLock] = {}


def _process_state_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(str(path.resolve()))
    with _PROCESS_STATE_LOCKS_GUARD:
        return _PROCESS_STATE_LOCKS.setdefault(key, threading.RLock())


class _TransferCancelled(RuntimeError):
    """Internal cooperative-stop signal; never exposed verbatim."""


class _TransferFailure(RuntimeError):
    """Sanitized transport failure with a stable public code."""

    def __init__(self, code: str, *, http_status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_file_with_chunks(
    path: Path,
    *,
    chunk_bytes: int,
) -> tuple[str, list[dict[str, Any]]]:
    """Hash a file and its bounded transfer chunks in one pass."""

    file_digest = hashlib.sha256()
    chunks: list[dict[str, Any]] = []
    offset = 0
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_bytes):
            file_digest.update(chunk)
            chunks.append(
                {
                    "part": len(chunks),
                    "offset": offset,
                    "size": len(chunk),
                    "sha256": hashlib.sha256(chunk).hexdigest(),
                }
            )
            offset += len(chunk)
    return file_digest.hexdigest(), chunks


def _canonical_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class NearbySendService:
    """A bounded agent client for LocalSend protocol v2.1."""

    def __init__(
        self,
        root: str | Path,
        *,
        config_path: str | Path | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        project_root = Path(__file__).resolve().parents[2]
        selected = Path(
            config_path
            or self.root / "config" / "neyvia_nearby_send.json"
        )
        if not selected.is_file():
            selected = (
                project_root / "config" / "neyvia_nearby_send.json"
            )
        if not selected.is_file():
            raise FileNotFoundError(selected)
        self.config_path = selected.resolve()
        self.config = json.loads(
            self.config_path.read_text(encoding="utf-8")
        )
        self.nearby_root = self.root / ".agent_control" / "nearby_send"
        self.receipt_root = self.nearby_root / "receipts"
        self.active_state_path = self.nearby_root / "active-state.json"
        self.cancel_request_path = self.nearby_root / "cancel-request.json"
        self.transfer_claim_path = self.nearby_root / "transfer.claim"
        self.state_lock_path = self.nearby_root / "state.lock"
        self._process_state_lock = _process_state_lock(self.state_lock_path)

    @property
    def protocol(self) -> dict[str, Any]:
        value = self.config.get("protocol")
        return dict(value) if isinstance(value, dict) else {}

    @property
    def policy(self) -> dict[str, Any]:
        value = self.config.get("policy")
        return dict(value) if isinstance(value, dict) else {}

    @property
    def limits(self) -> dict[str, Any]:
        value = self.config.get("limits")
        return dict(value) if isinstance(value, dict) else {}

    def _chunk_limits(self) -> tuple[int, int]:
        limits = self.limits
        raw_chunk_bytes = limits.get(
            "chunkBytes",
            _DEFAULT_TRANSFER_CHUNK_BYTES,
        )
        raw_max_parts = limits.get("maxParts", _MAX_TRANSFER_PARTS)
        try:
            chunk_bytes = int(raw_chunk_bytes)
            max_parts = int(raw_max_parts)
        except (TypeError, ValueError) as exc:
            raise ValueError("Nearby Send chunk limits must be integers") from exc
        if not 1 <= chunk_bytes <= _MAX_TRANSFER_CHUNK_BYTES:
            raise ValueError(
                "Nearby Send chunkBytes must be between 1 and "
                f"{_MAX_TRANSFER_CHUNK_BYTES}"
            )
        if not 1 <= max_parts <= _MAX_TRANSFER_PARTS:
            raise ValueError(
                "Nearby Send maxParts must be between 1 and "
                f"{_MAX_TRANSFER_PARTS}"
            )
        return chunk_bytes, max_parts

    def compatibility_snapshot(self) -> dict[str, Any]:
        configured = dict(self.config.get("compatibilityClient") or {})
        path = Path(str(configured.get("installPath") or "")).resolve()
        expected = str(
            configured.get("executableSha256") or ""
        ).casefold()
        actual = _sha256_file(path) if path.is_file() else ""
        return {
            "schema": "neyvia.nearby-compatibility-client/v1",
            "protocol": dict(self.protocol),
            "client": {
                "name": str(configured.get("name") or ""),
                "version": str(configured.get("version") or ""),
                "path": str(path),
                "installed": path.is_file(),
                "hashVerified": bool(
                    actual
                    and expected
                    and actual == expected
                ),
                "expectedSha256": expected,
                "actualSha256": actual,
                "running": False,
            },
            "agentProtocolClient": True,
            "receiverSidecarImplemented": False,
            "chunkTransfer": {
                "schema": NEARBY_CHUNK_TRANSFER_SCHEMA,
                "contentAddressed": True,
                "resume": True,
                "integrityAcknowledgementRequired": True,
            },
        }

    def bootstrap(self) -> dict[str, Any]:
        configured = dict(self.config.get("compatibilityClient") or {})
        return {
            "schema": "neyvia.nearby-send-bootstrap/v1",
            "protocol": "localsend-v2.1",
            "compatibilityClientVersion": str(
                configured.get("version") or ""
            ),
            "compatibilityClientState": str(
                configured.get("state") or ""
            ),
            "agentProtocolClient": True,
            "receiverSidecarImplemented": False,
            "chunkTransfer": {
                "schema": NEARBY_CHUNK_TRANSFER_SCHEMA,
                "contentAddressed": True,
                "resume": True,
                "integrityAcknowledgementRequired": True,
            },
            "detailsDeferred": True,
        }

    def get_active_transfer(self) -> dict[str, Any]:
        """Return a bounded, redacted view of durable transfer state."""

        recovery_error = ""
        with self._state_guard():
            try:
                state = self._read_json_bounded(
                    self.active_state_path,
                    max_bytes=_MAX_STATE_BYTES,
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                self.active_state_path.unlink(missing_ok=True)
                self.cancel_request_path.unlink(missing_ok=True)
                self._release_transfer_claim_unlocked(force=True)
                state = None
                recovery_error = "corrupt_state_discarded"
            if state is not None and (
                state.get("schema") != NEARBY_TRANSFER_STATE_SCHEMA
                or not str(state.get("transferId") or "")
            ):
                self.active_state_path.unlink(missing_ok=True)
                self.cancel_request_path.unlink(missing_ok=True)
                self._release_transfer_claim_unlocked(force=True)
                state = None
                recovery_error = "invalid_state_discarded"
            if (
                state is not None
                and str(state.get("status") or "") in _ACTIVE_TRANSFER_STATES
                and not self._pid_is_running(int(state.get("ownerPid") or 0))
            ):
                state = {
                    **state,
                    "status": "interrupted",
                    "active": False,
                    "updatedAt": utc_now(),
                    "completedAt": utc_now(),
                    "recipient": {},
                    "sessionId": "",
                    "error": {"code": "owner_process_stopped"},
                }
                atomic_write_json(self.active_state_path, state)
                self.cancel_request_path.unlink(missing_ok=True)
                self._release_transfer_claim_unlocked(force=True)
                recovery_error = "stale_transfer_recovered"

            result = {
                "schema": NEARBY_TRANSFER_PROGRESS_SCHEMA,
                "active": bool(
                    state
                    and str(state.get("status") or "") in _ACTIVE_TRANSFER_STATES
                ),
                "generatedAt": utc_now(),
                "progress": self._public_progress(state) if state else None,
                **({"recovery": recovery_error} if recovery_error else {}),
            }
            from .proofs_d_host import check_nearby_state
            check_nearby_state(self, state, result)
            return result

    def request_cancel_active_transfer(self) -> dict[str, Any]:
        """Durably request cancellation without claiming it already succeeded."""

        state = self._read_active_state_for_update()
        if state is None or str(state.get("status") or "") not in _ACTIVE_TRANSFER_STATES:
            return {
                "ok": False,
                "accepted": False,
                "cancelled": False,
                "status": "not_active",
                "generatedAt": utc_now(),
            }

        transfer_id = str(state["transferId"])
        request = {
            "schema": NEARBY_CANCEL_REQUEST_SCHEMA,
            "transferId": transfer_id,
            "requestedAt": utc_now(),
            "requesterPid": os.getpid(),
            "reason": "operator_request",
        }
        atomic_write_json(self.cancel_request_path, request)
        state = self._mutate_active_state(
            transfer_id,
            lambda current: {
                **current,
                "status": "cancel_requested",
                "updatedAt": utc_now(),
                "cancellation": {
                    **dict(current.get("cancellation") or {}),
                    "requested": True,
                    "requestedAt": request["requestedAt"],
                },
            },
        ) or state

        session_id = str(state.get("sessionId") or "")
        cancel_result = {
            "attempted": False,
            "acknowledged": False,
            "httpStatus": None,
            "errorCode": "",
        }
        if session_id:
            cancel_result = self._cancel(
                str((state.get("recipient") or {}).get("endpoint") or ""),
                str(
                    (state.get("recipient") or {}).get(
                        "certificateFingerprint"
                    )
                    or ""
                ),
                session_id,
            )
            self._merge_cancellation_result(transfer_id, cancel_result)

        result = {
            "ok": True,
            "accepted": True,
            "cancelled": False,
            "status": "cancel_requested",
            "transferId": transfer_id,
            "remoteCancelAttempted": bool(cancel_result["attempted"]),
            "remoteCancelAcknowledged": bool(
                cancel_result["acknowledged"]
            ),
            "remoteCancelHttpStatus": cancel_result["httpStatus"],
            "finalState": "pending",
            "generatedAt": utc_now(),
        }
        from .proofs_d_nearby import check_cancel_request
        check_cancel_request(result, cancel_result)
        return result

    def list_transfer_history(
        self,
        *,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return newest-first receipts with strict limits and allowlisted fields."""

        try:
            requested = int(limit)
        except (TypeError, ValueError) as exc:
            raise ValueError("limit must be an integer") from exc
        bounded = max(1, min(requested, _MAX_PUBLIC_HISTORY))
        rows: list[dict[str, Any]] = []
        skipped = 0
        if self.receipt_root.is_dir():
            paths = sorted(
                self.receipt_root.glob("nearby_receipt_*.json"),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
            for path in paths:
                if len(rows) >= bounded:
                    break
                try:
                    receipt = self._read_json_bounded(
                        path,
                        max_bytes=_MAX_RECEIPT_BYTES,
                    )
                except (
                    OSError,
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                    ValueError,
                ):
                    skipped += 1
                    continue
                if (
                    receipt is None
                    or receipt.get("schema") != NEARBY_TRANSFER_RECEIPT_SCHEMA
                ):
                    skipped += 1
                    continue
                rows.append(self._public_receipt(receipt, artifacts=False))
        result = {
            "schema": NEARBY_TRANSFER_HISTORY_SCHEMA,
            "generatedAt": utc_now(),
            "transfers": rows,
            "summary": {
                "transfers": len(rows),
                "completed": sum(
                    1 for row in rows if row.get("status") == "completed"
                ),
                "cancelled": sum(
                    1 for row in rows if row.get("status") == "cancelled"
                ),
                "failed": sum(
                    1 for row in rows if row.get("status") == "failed"
                ),
                "interrupted": sum(
                    1 for row in rows if row.get("status") == "interrupted"
                ),
                "requestedLimit": requested,
                "effectiveLimit": bounded,
                "skippedInvalidReceipts": skipped,
            },
        }
        from .proofs_d_host import check_nearby_history
        check_nearby_history(result)
        return result

    def discover(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        multicast = str(
            self.protocol.get("multicastAddress") or "224.0.0.167"
        )
        port = int(self.protocol.get("port") or 53317)
        timeout = max(
            0.2,
            min(
                float(
                    timeout_seconds
                    if timeout_seconds is not None
                    else self.limits.get("discoverySeconds") or 2
                ),
                10.0,
            ),
        )
        fingerprint = uuid.uuid4().hex
        announcement = {
            "alias": f"Neyvia-{socket.gethostname()}",
            "version": str(self.protocol.get("version") or "2.1"),
            "deviceModel": socket.gethostname(),
            "deviceType": "headless",
            "fingerprint": fingerprint,
            "port": port,
            "protocol": "https",
            "download": False,
            "announce": True,
        }
        devices: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            udp.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            udp.bind(("", port))
            membership = socket.inet_aton(multicast) + socket.inet_aton(
                "0.0.0.0"
            )
            udp.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_ADD_MEMBERSHIP,
                membership,
            )
            udp.settimeout(min(0.25, timeout))
            udp.sendto(
                json.dumps(announcement, separators=(",", ":")).encode(
                    "utf-8"
                ),
                (multicast, port),
            )
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    raw, origin = udp.recvfrom(64 * 1024)
                except socket.timeout:
                    continue
                try:
                    row = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if (
                    not isinstance(row, dict)
                    or row.get("fingerprint") == fingerprint
                ):
                    continue
                device = self._discovered_device(row, origin[0])
                if device is not None:
                    devices[device["deviceId"]] = device
        except OSError as exc:
            errors.append(str(exc))
        finally:
            udp.close()
        return {
            "schema": NEARBY_DISCOVERY_SCHEMA,
            "generatedAt": utc_now(),
            "protocol": "localsend-v2.1",
            "devices": sorted(
                devices.values(),
                key=lambda item: item["alias"].casefold(),
            ),
            "errors": errors,
            "summary": {
                "devices": len(devices),
                "multicastAvailable": not errors,
                "durationMs": round(
                    (time.perf_counter() - started) * 1000.0,
                    3,
                ),
            },
        }

    def build_plan(
        self,
        paths: list[str | Path],
        *,
        recipient_endpoint: str,
        recipient_fingerprint: str = "",
    ) -> dict[str, Any]:
        endpoint = self._validate_endpoint(
            recipient_endpoint,
            recipient_fingerprint,
        )
        max_files = int(self.limits.get("maxFiles") or 1000)
        if not paths or len(paths) > max_files:
            raise ValueError(f"paths must contain between 1 and {max_files} files")
        max_file = int(
            self.limits.get("maxFileBytes") or 8 * 1024 * 1024 * 1024
        )
        max_total = int(
            self.limits.get("maxTotalBytes") or 32 * 1024 * 1024 * 1024
        )
        chunk_bytes, max_parts = self._chunk_limits()
        files: list[dict[str, Any]] = []
        total = 0
        total_parts = 0
        for raw in paths:
            path = self._workspace_file(raw)
            size = path.stat().st_size
            if size > max_file:
                raise ValueError(f"File exceeds nearby-send limit: {path}")
            total += size
            if total > max_total:
                raise ValueError("Transfer exceeds nearby-send total size limit")
            digest, chunks = _hash_file_with_chunks(
                path,
                chunk_bytes=chunk_bytes,
            )
            total_parts += len(chunks)
            if total_parts > max_parts:
                raise ValueError(
                    "Transfer exceeds nearby-send chunk part limit"
                )
            file_id = hashlib.sha256(
                f"{path.name}\0{size}\0{digest}".encode("utf-8")
            ).hexdigest()[:24]
            files.append(
                {
                    "id": file_id,
                    "path": str(path),
                    "fileName": path.name,
                    "size": size,
                    "fileType": (
                        mimetypes.guess_type(path.name)[0]
                        or "application/octet-stream"
                    ),
                    "sha256": digest,
                    "modified": path.stat().st_mtime_ns,
                    "chunks": chunks,
                }
            )
        plan = {
            "schema": NEARBY_TRANSFER_PLAN_SCHEMA,
            "planId": "nearby_" + uuid.uuid4().hex,
            "createdAt": utc_now(),
            "recipient": {
                "endpoint": endpoint,
                "certificateFingerprint": self._normalize_fingerprint(
                    recipient_fingerprint
                ),
            },
            "files": files,
            "summary": {
                "fileCount": len(files),
                "totalBytes": total,
                "chunkBytes": chunk_bytes,
                "partCount": total_parts,
                "maxParts": max_parts,
                "parallelUploads": min(
                    len(files),
                    max(
                        1,
                        int(
                            self.limits.get("maxParallelUploads") or 4
                        ),
                    ),
                ),
            },
            "requiresApproval": True,
            "tokensRetained": False,
        }
        plan["planHash"] = _canonical_hash(plan)
        from .proofs_d_nearby import check_plan
        check_plan(self, plan)
        return plan

    def send(
        self,
        plan: dict[str, Any],
        *,
        approved: bool,
        pin: str = "",
    ) -> dict[str, Any]:
        if not approved:
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "external.side_effect",
            }
        payload = dict(plan)
        plan_hash = str(payload.pop("planHash", ""))
        if not plan_hash or _canonical_hash(payload) != plan_hash:
            raise ValueError("Nearby-send plan hash does not match")
        if payload.get("schema") != NEARBY_TRANSFER_PLAN_SCHEMA:
            raise ValueError("Nearby-send plan schema is invalid")
        recipient = dict(payload.get("recipient") or {})
        endpoint = self._validate_endpoint(
            str(recipient.get("endpoint") or ""),
            str(recipient.get("certificateFingerprint") or ""),
        )
        fingerprint = self._normalize_fingerprint(
            recipient.get("certificateFingerprint")
        )
        verified_files = [
            self._verify_planned_file(item)
            for item in payload.get("files") or []
        ]
        if not verified_files:
            raise ValueError("Nearby-send plan contains no files")
        max_files = int(self.limits.get("maxFiles") or 1000)
        max_file = int(
            self.limits.get("maxFileBytes") or 8 * 1024 * 1024 * 1024
        )
        max_total = int(
            self.limits.get("maxTotalBytes") or 32 * 1024 * 1024 * 1024
        )
        _, max_parts = self._chunk_limits()
        if len(verified_files) > max_files:
            raise ValueError("Nearby-send plan exceeds the file limit")
        if any(int(item["size"]) > max_file for item in verified_files):
            raise ValueError("Nearby-send plan exceeds the per-file size limit")
        if sum(int(item["size"]) for item in verified_files) > max_total:
            raise ValueError("Nearby-send plan exceeds the total size limit")
        if (
            sum(len(item["chunks"]) for item in verified_files)
            > max_parts
        ):
            raise ValueError("Nearby-send plan exceeds the chunk part limit")

        transfer_id = "nearby_transfer_" + uuid.uuid4().hex
        plan_id = str(payload.get("planId") or "")
        started = time.perf_counter()
        state = {
            "schema": NEARBY_TRANSFER_STATE_SCHEMA,
            "transferId": transfer_id,
            "planId": plan_id,
            "planHash": plan_hash,
            "status": "preparing",
            "active": True,
            "ownerPid": os.getpid(),
            "startedAt": utc_now(),
            "updatedAt": utc_now(),
            "recipient": {
                "endpoint": endpoint,
                "certificateFingerprint": fingerprint,
            },
            "sessionId": "",
            "files": [
                {
                    "fileId": item["id"],
                    "fileName": item["fileName"],
                    "sourceRef": self._workspace_reference(item["path"]),
                    "size": item["size"],
                    "sha256": item["sha256"],
                    "chunkCount": len(item["chunks"]),
                    "chunkManifestMigrated": bool(
                        item.get("chunkManifestMigrated")
                    ),
                    "acknowledgedOffset": 0,
                    "acknowledgedChunks": [],
                    "resumedParts": 0,
                    "uploadedParts": 0,
                    "state": "queued",
                    "bytesSent": 0,
                }
                for item in verified_files
            ],
            "summary": {
                "fileCount": len(verified_files),
                "totalBytes": sum(item["size"] for item in verified_files),
                "completedFiles": 0,
                "failedFiles": 0,
                "bytesSent": 0,
            },
            "cancellation": {
                "requested": False,
                "requestedAt": "",
                "remoteAttempted": False,
                "remoteAcknowledged": False,
                "remoteHttpStatus": None,
                "errorCode": "",
            },
        }
        self._claim_transfer(transfer_id)
        with self._state_guard():
            self.cancel_request_path.unlink(missing_ok=True)
            atomic_write_json(self.active_state_path, state)

        prepare_payload = {
            "info": self._sender_info(),
            "files": {
                item["id"]: {
                    "id": item["id"],
                    "fileName": item["fileName"],
                    "size": item["size"],
                    "fileType": item["fileType"],
                    "sha256": item["sha256"],
                    "preview": None,
                    "metadata": {
                        "modified": str(item.get("modified") or ""),
                    },
                    "chunkTransfer": {
                        "schema": NEARBY_CHUNK_TRANSFER_SCHEMA,
                        "contentAddressed": True,
                        "size": item["size"],
                        "sha256": item["sha256"],
                        "chunks": item["chunks"],
                        "manifestMigrated": bool(
                            item.get("chunkManifestMigrated")
                        ),
                    },
                }
                for item in verified_files
            },
            "capabilities": {
                "chunkTransfer": {
                    "schema": NEARBY_CHUNK_TRANSFER_SCHEMA,
                    "resume": True,
                    "integrityAcknowledgementRequired": True,
                }
            },
        }
        suffix = f"?pin={urlencode({'pin': pin})[4:]}" if pin else ""
        session_id = ""
        results: list[dict[str, Any]] = []
        failure: _TransferFailure | None = None

        def finish(**arguments: Any) -> dict[str, Any]:
            from .proofs_d_nearby import check_transfer_result
            result = self._finalize_transfer(**arguments)
            check_transfer_result(self, verified_files, result)
            return result

        try:
            self._raise_if_cancelled(transfer_id)
            try:
                status, response_body = self._json_request(
                    endpoint,
                    fingerprint,
                    "POST",
                    f"/api/localsend/v2/prepare-upload{suffix}",
                    prepare_payload,
                )
            except _TransferCancelled:
                raise
            except Exception as exc:
                raise _TransferFailure("prepare_transport_failed") from exc
            if status == 204:
                response = {"sessionId": "", "files": {}}
            elif status == 200:
                response = response_body
            else:
                raise _TransferFailure(
                    "recipient_prepare_rejected",
                    http_status=status,
                )
            session_id = str(response.get("sessionId") or "")
            tokens = response.get("files")
            if status != 204 and (
                not session_id or not isinstance(tokens, dict)
            ):
                raise _TransferFailure("invalid_prepare_response")

            self._mutate_active_state(
                transfer_id,
                lambda current: {
                    **current,
                    "status": "uploading",
                    "sessionId": session_id,
                    "updatedAt": utc_now(),
                },
            )
            self._raise_if_cancelled(transfer_id)
            if status == 204:
                results = [
                    {
                        "fileId": item["id"],
                        "httpStatus": 204,
                        "bytesSent": 0,
                        "acknowledgedOffset": item["size"],
                        "chunkCount": len(item["chunks"]),
                        "resumedParts": 0,
                        "uploadedParts": 0,
                        "remoteHashVerified": False,
                        "acknowledgements": [],
                    }
                    for item in verified_files
                ]
            else:
                authorizations = {
                    item["id"]: self._parse_upload_authorization(
                        item,
                        tokens.get(item["id"]),
                    )
                    for item in verified_files
                }
                workers = min(
                    len(verified_files),
                    max(
                        1,
                        int(
                            self.limits.get("maxParallelUploads") or 4
                        ),
                    ),
                )
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = {
                        executor.submit(
                            (
                                self._upload_chunked_file
                                if authorizations[item["id"]]["chunked"]
                                else self._upload_file
                            ),
                            transfer_id,
                            endpoint,
                            fingerprint,
                            session_id,
                            item,
                            authorizations[item["id"]],
                        ): item
                        for item in verified_files
                    }
                    for future in as_completed(futures):
                        item = futures[future]
                        try:
                            results.append(future.result())
                        except _TransferCancelled:
                            continue
                        except _TransferFailure as exc:
                            cancel_request = self._cancel_request_for(
                                transfer_id
                            )
                            if (
                                cancel_request is not None
                                and cancel_request.get("reason")
                                == "operator_request"
                            ):
                                continue
                            failure = failure or exc
                            self._write_cancel_request(
                                transfer_id,
                                reason="transfer_failure",
                            )
                            self._set_file_state(
                                transfer_id,
                                item["id"],
                                state="failed",
                            )
                        except Exception:
                            cancel_request = self._cancel_request_for(
                                transfer_id
                            )
                            if (
                                cancel_request is not None
                                and cancel_request.get("reason")
                                == "operator_request"
                            ):
                                continue
                            failure = failure or _TransferFailure(
                                "upload_transport_failed"
                            )
                            self._write_cancel_request(
                                transfer_id,
                                reason="transfer_failure",
                            )
                            self._set_file_state(
                                transfer_id,
                                item["id"],
                                state="failed",
                            )
                if failure is not None:
                    raise failure
            self._raise_if_cancelled(transfer_id)
            return finish(
                transfer_id=transfer_id,
                plan_id=plan_id,
                plan_hash=plan_hash,
                endpoint=endpoint,
                fingerprint=fingerprint,
                session_id=session_id,
                verified_files=verified_files,
                results=results,
                status="completed",
                started=started,
            )
        except _TransferCancelled:
            cancel_result = self._cancel(endpoint, fingerprint, session_id)
            self._merge_cancellation_result(transfer_id, cancel_result)
            return finish(
                transfer_id=transfer_id,
                plan_id=plan_id,
                plan_hash=plan_hash,
                endpoint=endpoint,
                fingerprint=fingerprint,
                session_id=session_id,
                verified_files=verified_files,
                results=results,
                status="cancelled",
                started=started,
            )
        except _TransferFailure as exc:
            cancel_result = self._cancel(endpoint, fingerprint, session_id)
            self._merge_cancellation_result(transfer_id, cancel_result)
            return finish(
                transfer_id=transfer_id,
                plan_id=plan_id,
                plan_hash=plan_hash,
                endpoint=endpoint,
                fingerprint=fingerprint,
                session_id=session_id,
                verified_files=verified_files,
                results=results,
                status="failed",
                started=started,
                error_code=exc.code,
                remote_http_status=exc.http_status,
            )
        except BaseException:
            self._mark_interrupted(transfer_id)
            raise

    def _upload_file(
        self,
        transfer_id: str,
        endpoint: str,
        fingerprint: str,
        session_id: str,
        item: dict[str, Any],
        authorization: dict[str, Any],
    ) -> dict[str, Any]:
        token = str(authorization.get("token") or "")
        if not token:
            raise _TransferFailure("file_not_authorized")
        self._raise_if_cancelled(transfer_id)
        query = urlencode(
            {
                "sessionId": session_id,
                "fileId": item["id"],
                "token": token,
            }
        )
        connection, base_path = self._connection(endpoint, fingerprint)
        try:
            connection.putrequest(
                "POST",
                f"{base_path}/api/localsend/v2/upload?{query}",
            )
            connection.putheader("Content-Type", "application/octet-stream")
            connection.putheader("Content-Length", str(item["size"]))
            connection.endheaders()
            bytes_sent = 0
            persisted_at = 0
            self._set_file_state(
                transfer_id,
                item["id"],
                state="uploading",
            )
            with Path(item["path"]).open("rb") as handle:
                while chunk := handle.read(_UPLOAD_CHUNK_BYTES):
                    self._raise_if_cancelled(transfer_id)
                    connection.send(chunk)
                    bytes_sent += len(chunk)
                    if (
                        bytes_sent - persisted_at >= 1024 * 1024
                        or bytes_sent == int(item["size"])
                    ):
                        self._set_file_state(
                            transfer_id,
                            item["id"],
                            state="uploading",
                            bytes_sent=bytes_sent,
                        )
                        persisted_at = bytes_sent
            self._raise_if_cancelled(transfer_id)
            response = connection.getresponse()
            response.read()
            if response.status not in {200, 204}:
                raise _TransferFailure(
                    "recipient_upload_rejected",
                    http_status=response.status,
                )
            self._set_file_state(
                transfer_id,
                item["id"],
                state="completed",
                bytes_sent=bytes_sent,
            )
            return {
                "fileId": item["id"],
                "httpStatus": response.status,
                "bytesSent": bytes_sent,
                "acknowledgedOffset": item["size"],
                "chunkCount": len(item["chunks"]),
                "resumedParts": 0,
                "uploadedParts": 0,
                "remoteHashVerified": False,
                "acknowledgements": [],
            }
        finally:
            connection.close()

    def _parse_upload_authorization(
        self,
        item: dict[str, Any],
        value: object,
    ) -> dict[str, Any]:
        """Parse either a legacy token or an explicitly negotiated resume."""

        if isinstance(value, str):
            if not value:
                raise _TransferFailure("file_not_authorized")
            return {
                "chunked": False,
                "token": value,
                "offset": 0,
                "acknowledgements": [],
            }
        if not isinstance(value, dict):
            raise _TransferFailure("file_not_authorized")
        token = str(value.get("token") or "")
        contract = value.get("chunkTransfer")
        if (
            not token
            or not isinstance(contract, dict)
            or contract.get("schema") != NEARBY_CHUNK_TRANSFER_SCHEMA
        ):
            raise _TransferFailure("invalid_chunk_authorization")
        try:
            offset = int(contract.get("offset") or 0)
        except (TypeError, ValueError) as exc:
            raise _TransferFailure("invalid_resume_offset") from exc
        chunks = [
            dict(row)
            for row in item.get("chunks") or []
            if isinstance(row, dict)
        ]
        boundaries = {0, int(item["size"])}
        boundaries.update(
            int(chunk["offset"]) + int(chunk["size"])
            for chunk in chunks
        )
        if offset not in boundaries:
            raise _TransferFailure("invalid_resume_offset")
        expected = [
            chunk
            for chunk in chunks
            if int(chunk["offset"]) < offset
        ]
        raw_receipts = contract.get("acknowledgedChunks")
        if not isinstance(raw_receipts, list) or len(raw_receipts) != len(
            expected
        ):
            raise _TransferFailure("invalid_resume_receipts")
        receipts: list[dict[str, Any]] = []
        for expected_chunk, raw_receipt in zip(
            expected,
            raw_receipts,
            strict=True,
        ):
            if not isinstance(raw_receipt, dict):
                raise _TransferFailure("invalid_resume_receipts")
            receipt = dict(raw_receipt)
            try:
                exact = (
                    int(receipt.get("part")) == int(expected_chunk["part"])
                    and int(receipt.get("offset"))
                    == int(expected_chunk["offset"])
                    and int(receipt.get("size"))
                    == int(expected_chunk["size"])
                    and str(receipt.get("sha256") or "")
                    == str(expected_chunk["sha256"])
                    and receipt.get("integrityVerified") is True
                )
            except (TypeError, ValueError):
                exact = False
            if not exact:
                raise _TransferFailure("invalid_resume_receipts")
            receipts.append(
                {
                    **expected_chunk,
                    "integrityVerified": True,
                    "source": "resume",
                }
            )
        result = {
            "chunked": True,
            "token": token,
            "offset": offset,
            "acknowledgements": receipts,
        }
        from .proofs_d_nearby import check_resume_authorization
        check_resume_authorization(item, result)
        return result

    def _upload_chunked_file(
        self,
        transfer_id: str,
        endpoint: str,
        fingerprint: str,
        session_id: str,
        item: dict[str, Any],
        authorization: dict[str, Any],
    ) -> dict[str, Any]:
        """Upload unacknowledged content-addressed chunks sequentially."""

        token = str(authorization.get("token") or "")
        offset = int(authorization.get("offset") or 0)
        chunks = [
            dict(row)
            for row in item.get("chunks") or []
            if isinstance(row, dict)
        ]
        acknowledgements = [
            dict(row)
            for row in authorization.get("acknowledgements") or []
            if isinstance(row, dict)
        ]
        resumed_parts = len(acknowledgements)
        uploaded_parts = 0
        uploaded_bytes = 0
        from .proofs_d_nearby import check_ack_progress
        self._set_file_state(
            transfer_id,
            item["id"],
            state="uploading",
            bytes_sent=0,
            acknowledged_offset=offset,
            acknowledged_chunks=acknowledgements,
            resumed_parts=resumed_parts,
            uploaded_parts=0,
        )
        check_ack_progress(self, transfer_id, item, acknowledgements, offset)
        with Path(item["path"]).open("rb") as handle:
            for chunk in chunks[resumed_parts:]:
                self._raise_if_cancelled(transfer_id)
                chunk_offset = int(chunk["offset"])
                chunk_size = int(chunk["size"])
                handle.seek(chunk_offset)
                digest = hashlib.sha256()
                remaining = chunk_size
                while remaining:
                    self._raise_if_cancelled(transfer_id)
                    piece = handle.read(
                        min(_UPLOAD_CHUNK_BYTES, remaining)
                    )
                    if not piece:
                        break
                    digest.update(piece)
                    remaining -= len(piece)
                if (
                    remaining
                    or digest.hexdigest() != chunk["sha256"]
                ):
                    raise _TransferFailure("source_chunk_integrity_failed")
                query = urlencode(
                    {
                        "sessionId": session_id,
                        "fileId": item["id"],
                        "token": token,
                        "offset": chunk_offset,
                        "part": chunk["part"],
                        "chunkId": chunk["sha256"],
                    }
                )
                deadline = (
                    time.monotonic() + self._request_timeout_seconds()
                )
                connection, base_path = self._connection(
                    endpoint,
                    fingerprint,
                )
                try:
                    self._raise_if_cancelled(transfer_id)
                    self._apply_remaining_timeout(connection, deadline)
                    connection.putrequest(
                        "POST",
                        f"{base_path}/api/localsend/v2/upload?{query}",
                    )
                    connection.putheader(
                        "Content-Type",
                        "application/octet-stream",
                    )
                    connection.putheader(
                        "Content-Length",
                        str(chunk_size),
                    )
                    connection.putheader(
                        "Content-Range",
                        (
                            f"bytes {chunk_offset}-"
                            f"{chunk_offset + chunk_size - 1}/"
                            f"{item['size']}"
                        ),
                    )
                    connection.putheader(
                        "X-Neyvia-Chunk-Sha256",
                        chunk["sha256"],
                    )
                    connection.putheader(
                        "X-Neyvia-Chunk-Transfer",
                        NEARBY_CHUNK_TRANSFER_SCHEMA,
                    )
                    connection.endheaders()
                    handle.seek(chunk_offset)
                    remaining = chunk_size
                    while remaining:
                        self._raise_if_cancelled(transfer_id)
                        self._apply_remaining_timeout(
                            connection,
                            deadline,
                        )
                        piece = handle.read(
                            min(_UPLOAD_CHUNK_BYTES, remaining)
                        )
                        if not piece:
                            raise _TransferFailure(
                                "source_chunk_integrity_failed"
                            )
                        connection.send(piece)
                        remaining -= len(piece)
                    self._raise_if_cancelled(transfer_id)
                    self._apply_remaining_timeout(
                        connection,
                        deadline,
                    )
                    response = connection.getresponse()
                    if response.status not in {200, 204}:
                        raise _TransferFailure(
                            "recipient_upload_rejected",
                            http_status=response.status,
                        )
                    raw = self._read_chunk_ack_body(
                        transfer_id,
                        connection,
                        response,
                        deadline,
                    )
                    receipt = self._validate_chunk_acknowledgement(
                        response,
                        raw,
                        chunk,
                    )
                finally:
                    connection.close()
                acknowledgements.append(receipt)
                uploaded_parts += 1
                uploaded_bytes += chunk_size
                offset = chunk_offset + chunk_size
                self._set_file_state(
                    transfer_id,
                    item["id"],
                    state="uploading",
                    bytes_sent=uploaded_bytes,
                    acknowledged_offset=offset,
                    acknowledged_chunks=acknowledgements,
                    resumed_parts=resumed_parts,
                    uploaded_parts=uploaded_parts,
                )
                check_ack_progress(self, transfer_id, item, acknowledgements, offset)
        if offset != int(item["size"]) or len(acknowledgements) != len(chunks):
            raise _TransferFailure("incomplete_chunk_acknowledgement")
        self._set_file_state(
            transfer_id,
            item["id"],
            state="completed",
            bytes_sent=uploaded_bytes,
            acknowledged_offset=offset,
            acknowledged_chunks=acknowledgements,
            resumed_parts=resumed_parts,
            uploaded_parts=uploaded_parts,
        )
        return {
            "fileId": item["id"],
            "httpStatus": 204,
            "bytesSent": uploaded_bytes,
            "acknowledgedOffset": offset,
            "chunkCount": len(chunks),
            "resumedParts": resumed_parts,
            "uploadedParts": uploaded_parts,
            "remoteHashVerified": bool(chunks),
            "acknowledgements": acknowledgements,
        }

    @staticmethod
    def _validate_chunk_acknowledgement(
        response: http.client.HTTPResponse,
        raw: bytes,
        chunk: dict[str, Any],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if raw:
            try:
                decoded = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise _TransferFailure(
                    "invalid_chunk_acknowledgement",
                    http_status=response.status,
                ) from exc
            if not isinstance(decoded, dict):
                raise _TransferFailure(
                    "invalid_chunk_acknowledgement",
                    http_status=response.status,
                )
            payload = decoded
        acknowledged = payload.get("acknowledged")
        next_offset = payload.get("nextOffset")
        digest = payload.get("sha256")
        integrity_verified = payload.get("integrityVerified")
        if acknowledged is None:
            acknowledged = (
                response.getheader("X-Neyvia-Chunk-Acknowledged", "")
                .strip()
                .casefold()
                == "true"
            )
        if next_offset is None:
            next_offset = response.getheader("X-Neyvia-Next-Offset")
        if digest is None:
            digest = response.getheader("X-Neyvia-Chunk-Sha256")
        if integrity_verified is None:
            integrity_verified = (
                response.getheader("X-Neyvia-Integrity-Verified", "")
                .strip()
                .casefold()
                == "true"
            )
        if acknowledged is not True:
            raise _TransferFailure(
                "recipient_chunk_ack_missing",
                http_status=response.status,
            )
        try:
            valid = (
                int(next_offset)
                == int(chunk["offset"]) + int(chunk["size"])
                and str(digest or "") == str(chunk["sha256"])
            )
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise _TransferFailure(
                "invalid_chunk_acknowledgement",
                http_status=response.status,
            )
        if integrity_verified is not True:
            raise _TransferFailure(
                "recipient_chunk_integrity_unverified",
                http_status=response.status,
            )
        result = {**chunk, "integrityVerified": True, "source": "upload"}
        from .proofs_d_nearby import check_chunk_receipt
        check_chunk_receipt(chunk, result, "upload")
        return result

    def _json_request(
        self,
        endpoint: str,
        fingerprint: str,
        method: str,
        path: str,
        payload: dict[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        connection, base_path = self._connection(endpoint, fingerprint)
        try:
            connection.request(
                method,
                base_path + path,
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                },
            )
            response = connection.getresponse()
            raw = response.read(4 * 1024 * 1024)
            decoded = json.loads(raw) if raw else {}
            if not isinstance(decoded, dict):
                raise RuntimeError("Recipient returned a non-object response")
            return response.status, decoded
        finally:
            connection.close()

    def _cancel(
        self,
        endpoint: str,
        fingerprint: str,
        session_id: str,
    ) -> dict[str, Any]:
        if not session_id:
            return {
                "attempted": False,
                "acknowledged": False,
                "httpStatus": None,
                "errorCode": "",
            }
        try:
            connection, base_path = self._connection(endpoint, fingerprint)
            try:
                connection.request(
                    "POST",
                    base_path
                    + "/api/localsend/v2/cancel?"
                    + urlencode({"sessionId": session_id}),
                    body=b"",
                    headers={"Content-Length": "0"},
                )
                response = connection.getresponse()
                response.read()
                acknowledged = response.status in {200, 204}
                result = {
                    "attempted": True,
                    "acknowledged": acknowledged,
                    "httpStatus": response.status,
                    "errorCode": (
                        "" if acknowledged else "recipient_cancel_rejected"
                    ),
                }
                from .proofs_d_nearby import check_cancel_transport
                check_cancel_transport(result)
                return result
            finally:
                connection.close()
        except Exception:
            return {
                "attempted": True,
                "acknowledged": False,
                "httpStatus": None,
                "errorCode": "cancel_transport_failed",
            }

    def _finalize_transfer(
        self,
        *,
        transfer_id: str,
        plan_id: str,
        plan_hash: str,
        endpoint: str,
        fingerprint: str,
        session_id: str,
        verified_files: list[dict[str, Any]],
        results: list[dict[str, Any]],
        status: str,
        started: float,
        error_code: str = "",
        remote_http_status: int | None = None,
    ) -> dict[str, Any]:
        result_by_file = {
            str(row.get("fileId") or ""): row
            for row in results
            if isinstance(row, dict)
        }
        completed = set(result_by_file)
        active_state = self._read_active_state_for_update(transfer_id) or {}
        active_by_file = {
            str(row.get("fileId") or ""): row
            for row in active_state.get("files") or []
            if isinstance(row, dict)
        }
        rows: list[dict[str, Any]] = []
        for item in verified_files:
            result = dict(result_by_file.get(item["id"]) or {})
            progress = dict(active_by_file.get(item["id"]) or {})
            acknowledgements = [
                dict(row)
                for row in (
                    result.get("acknowledgements")
                    or progress.get("acknowledgedChunks")
                    or []
                )
                if isinstance(row, dict)
            ][:_MAX_TRANSFER_PARTS]
            rows.append({
                "fileId": item["id"],
                "fileName": item["fileName"],
                "sourceRef": self._workspace_reference(item["path"]),
                "size": item["size"],
                "sha256": item["sha256"],
                "transportAccepted": item["id"] in completed,
                "remoteHashVerified": bool(result.get("remoteHashVerified")),
                "chunkCount": len(item["chunks"]),
                "chunkManifestMigrated": bool(
                    item.get("chunkManifestMigrated")
                ),
                "acknowledgedParts": len(acknowledgements),
                "resumedParts": int(
                    result.get("resumedParts")
                    or progress.get("resumedParts")
                    or 0
                ),
                "uploadedParts": int(
                    result.get("uploadedParts")
                    or progress.get("uploadedParts")
                    or 0
                ),
                "resumeOffset": sum(
                    int(receipt.get("size") or 0)
                    for receipt in acknowledgements
                    if receipt.get("source") == "resume"
                ),
                "acknowledgedOffset": int(
                    result.get("acknowledgedOffset")
                    or progress.get("acknowledgedOffset")
                    or 0
                ),
                "chunkReceipts": acknowledgements,
            })
        if status == "completed" and len(completed) != len(rows):
            status = "failed"
            error_code = error_code or "incomplete_transport_acceptance"
        cancellation = dict(active_state.get("cancellation") or {})
        receipt_id = "nearby_receipt_" + uuid.uuid4().hex
        receipt = {
            "schema": NEARBY_TRANSFER_RECEIPT_SCHEMA,
            "receiptId": receipt_id,
            "transferId": transfer_id,
            "planId": plan_id,
            "planHash": plan_hash,
            "ok": status == "completed",
            "cancelled": status == "cancelled",
            "status": status,
            "protocol": "localsend-v2.1",
            "recipientIdentityDigest": hashlib.sha256(
                f"{endpoint}\0{fingerprint}".encode("utf-8")
            ).hexdigest(),
            "sessionDigest": (
                hashlib.sha256(session_id.encode("utf-8")).hexdigest()
                if session_id
                else ""
            ),
            "files": rows,
            "summary": {
                "fileCount": len(rows),
                "totalBytes": sum(int(row["size"]) for row in rows),
                "durationMs": round(
                    (time.perf_counter() - started) * 1000.0,
                    3,
                ),
                "transportAccepted": sum(
                    1 for row in rows if row["transportAccepted"]
                ),
                "remoteHashVerified": 0,
                "partCount": sum(row["chunkCount"] for row in rows),
                "acknowledgedParts": sum(
                    row["acknowledgedParts"] for row in rows
                ),
                "resumedParts": sum(row["resumedParts"] for row in rows),
                "uploadedParts": sum(row["uploadedParts"] for row in rows),
                "migratedChunkManifests": sum(
                    1 for row in rows if row["chunkManifestMigrated"]
                ),
            },
            "cancellation": {
                "requested": bool(cancellation.get("requested")),
                "remoteAttempted": bool(
                    cancellation.get("remoteAttempted")
                ),
                "remoteAcknowledged": bool(
                    cancellation.get("remoteAcknowledged")
                ),
                "remoteHttpStatus": cancellation.get("remoteHttpStatus"),
                "errorCode": str(cancellation.get("errorCode") or ""),
            },
            "error": {
                "code": error_code,
                "remoteHttpStatus": remote_http_status,
            }
            if error_code
            else None,
            "tokensRetained": False,
            "physicalDeviceVerified": False,
            "multiRecipientVerified": False,
            "completedAt": utc_now(),
        }
        receipt["summary"]["remoteHashVerified"] = sum(
            1 for row in rows if row["remoteHashVerified"]
        )
        receipt_path = self.receipt_root / f"{receipt_id}.json"
        atomic_write_json(receipt_path, receipt)
        with self._state_guard():
            current = self._read_json_bounded(
                self.active_state_path,
                max_bytes=_MAX_STATE_BYTES,
            )
            if current and str(current.get("transferId") or "") == transfer_id:
                terminal = {
                    **current,
                    "status": status,
                    "active": False,
                    "updatedAt": utc_now(),
                    "completedAt": receipt["completedAt"],
                    "receiptId": receipt_id,
                    "recipient": {},
                    "sessionId": "",
                    "error": receipt["error"],
                }
                atomic_write_json(self.active_state_path, terminal)
            self.cancel_request_path.unlink(missing_ok=True)
            self._release_transfer_claim_unlocked(transfer_id=transfer_id)
        return self._public_receipt(receipt, artifacts=True)

    def _public_receipt(
        self,
        receipt: dict[str, Any],
        *,
        artifacts: bool,
    ) -> dict[str, Any]:
        raw_files = [
            row
            for row in receipt.get("files") or []
            if isinstance(row, dict)
        ]
        files = [
            {
                "fileId": str(row.get("fileId") or ""),
                "fileName": str(row.get("fileName") or "")[:260],
                "sourceRef": self._safe_source_ref(row.get("sourceRef")),
                "size": max(0, int(row.get("size") or 0)),
                "sha256": str(row.get("sha256") or ""),
                "transportAccepted": bool(row.get("transportAccepted")),
                "remoteHashVerified": bool(row.get("remoteHashVerified")),
                "chunkManifestMigrated": bool(
                    row.get("chunkManifestMigrated")
                ),
                "chunkCount": max(0, int(row.get("chunkCount") or 0)),
                "acknowledgedParts": max(
                    0, int(row.get("acknowledgedParts") or 0)
                ),
                "resumedParts": max(
                    0, int(row.get("resumedParts") or 0)
                ),
                "uploadedParts": max(
                    0, int(row.get("uploadedParts") or 0)
                ),
                "resumeOffset": max(
                    0, int(row.get("resumeOffset") or 0)
                ),
                "acknowledgedOffset": max(
                    0, int(row.get("acknowledgedOffset") or 0)
                ),
                "chunkReceipts": [
                    {
                        "part": max(0, int(receipt.get("part") or 0)),
                        "offset": max(0, int(receipt.get("offset") or 0)),
                        "size": max(0, int(receipt.get("size") or 0)),
                        "sha256": str(receipt.get("sha256") or ""),
                        "integrityVerified": bool(
                            receipt.get("integrityVerified")
                        ),
                        "source": (
                            str(receipt.get("source") or "")
                            if receipt.get("source") in {"resume", "upload"}
                            else ""
                        ),
                    }
                    for receipt in row.get("chunkReceipts") or []
                    if isinstance(receipt, dict)
                ][:_MAX_TRANSFER_PARTS],
            }
            for row in raw_files[:_MAX_PUBLIC_FILES]
        ]
        cancellation = dict(receipt.get("cancellation") or {})
        error = receipt.get("error")
        public = {
            "schema": NEARBY_TRANSFER_RECEIPT_SCHEMA,
            "receiptId": str(receipt.get("receiptId") or ""),
            "transferId": str(receipt.get("transferId") or ""),
            "planId": str(receipt.get("planId") or ""),
            "ok": bool(receipt.get("ok")),
            "cancelled": bool(receipt.get("cancelled")),
            "status": str(receipt.get("status") or ""),
            "protocol": str(receipt.get("protocol") or ""),
            "recipientIdentityDigest": str(
                receipt.get("recipientIdentityDigest") or ""
            ),
            "sessionDigest": str(receipt.get("sessionDigest") or ""),
            "files": files,
            "summary": {
                "fileCount": int(
                    (receipt.get("summary") or {}).get("fileCount") or 0
                ),
                "totalBytes": int(
                    (receipt.get("summary") or {}).get("totalBytes") or 0
                ),
                "durationMs": float(
                    (receipt.get("summary") or {}).get("durationMs") or 0
                ),
                "transportAccepted": int(
                    (receipt.get("summary") or {}).get(
                        "transportAccepted"
                    )
                    or 0
                ),
                "remoteHashVerified": int(
                    (receipt.get("summary") or {}).get(
                        "remoteHashVerified"
                    )
                    or 0
                ),
                "partCount": int(
                    (receipt.get("summary") or {}).get("partCount") or 0
                ),
                "acknowledgedParts": int(
                    (receipt.get("summary") or {}).get(
                        "acknowledgedParts"
                    )
                    or 0
                ),
                "resumedParts": int(
                    (receipt.get("summary") or {}).get("resumedParts") or 0
                ),
                "uploadedParts": int(
                    (receipt.get("summary") or {}).get("uploadedParts") or 0
                ),
                "migratedChunkManifests": int(
                    (receipt.get("summary") or {}).get(
                        "migratedChunkManifests"
                    )
                    or 0
                ),
                "returnedFiles": len(files),
                "filesTruncated": max(0, len(raw_files) - len(files)),
            },
            "cancellation": {
                "requested": bool(cancellation.get("requested")),
                "remoteAttempted": bool(
                    cancellation.get("remoteAttempted")
                ),
                "remoteAcknowledged": bool(
                    cancellation.get("remoteAcknowledged")
                ),
                "remoteHttpStatus": cancellation.get("remoteHttpStatus"),
                "errorCode": str(cancellation.get("errorCode") or ""),
            },
            "error": (
                {
                    "code": str(error.get("code") or ""),
                    "remoteHttpStatus": error.get("remoteHttpStatus"),
                }
                if isinstance(error, dict)
                else None
            ),
            "tokensRetained": False,
            "physicalDeviceVerified": bool(
                receipt.get("physicalDeviceVerified")
            ),
            "multiRecipientVerified": bool(
                receipt.get("multiRecipientVerified")
            ),
            "completedAt": str(receipt.get("completedAt") or ""),
        }
        if artifacts:
            receipt_ref = self._workspace_reference(
                self.receipt_root / f"{public['receiptId']}.json"
            )
            public["receiptPath"] = receipt_ref
            public["artifacts"] = [
                {
                    "path": row["sourceRef"],
                    "role": "source",
                    "kind": "file",
                }
                for row in files
                if row["sourceRef"]
            ] + [
                {
                    "path": receipt_ref,
                    "role": "verification",
                    "kind": "nearby-transfer-receipt",
                    "relation": "verified_by",
                    "verifiedBy": (
                        "recipient-content-addressed-acknowledgement"
                        if public["summary"]["remoteHashVerified"]
                        == public["summary"]["fileCount"]
                        and public["summary"]["fileCount"] > 0
                        else "localsend-transport-acceptance"
                    ),
                }
            ]
        from .proofs_d_host import check_nearby_projection
        check_nearby_projection(receipt, public)
        return public

    def _public_progress(
        self,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        raw_files = [
            row
            for row in state.get("files") or []
            if isinstance(row, dict)
        ]
        cancellation = dict(state.get("cancellation") or {})
        error = state.get("error")
        public = {
            "transferId": str(state.get("transferId") or ""),
            "planId": str(state.get("planId") or ""),
            "status": str(state.get("status") or ""),
            "startedAt": str(state.get("startedAt") or ""),
            "updatedAt": str(state.get("updatedAt") or ""),
            "completedAt": str(state.get("completedAt") or ""),
            "files": [
                {
                    "fileId": str(row.get("fileId") or ""),
                    "fileName": str(row.get("fileName") or "")[:260],
                    "sourceRef": self._safe_source_ref(row.get("sourceRef")),
                    "size": max(0, int(row.get("size") or 0)),
                    "state": str(row.get("state") or ""),
                    "bytesSent": max(0, int(row.get("bytesSent") or 0)),
                    "chunkCount": max(
                        0, int(row.get("chunkCount") or 0)
                    ),
                    "chunkManifestMigrated": bool(
                        row.get("chunkManifestMigrated")
                    ),
                    "acknowledgedOffset": max(
                        0, int(row.get("acknowledgedOffset") or 0)
                    ),
                    "acknowledgedParts": len(
                        [
                            receipt
                            for receipt in row.get(
                                "acknowledgedChunks"
                            )
                            or []
                            if isinstance(receipt, dict)
                        ]
                    ),
                    "resumedParts": max(
                        0, int(row.get("resumedParts") or 0)
                    ),
                    "uploadedParts": max(
                        0, int(row.get("uploadedParts") or 0)
                    ),
                    "chunkReceipts": [
                        {
                            "part": max(
                                0, int(receipt.get("part") or 0)
                            ),
                            "offset": max(
                                0, int(receipt.get("offset") or 0)
                            ),
                            "size": max(
                                0, int(receipt.get("size") or 0)
                            ),
                            "sha256": str(
                                receipt.get("sha256") or ""
                            ),
                            "integrityVerified": bool(
                                receipt.get("integrityVerified")
                            ),
                            "source": (
                                str(receipt.get("source") or "")
                                if receipt.get("source")
                                in {"resume", "upload"}
                                else ""
                            ),
                        }
                        for receipt in row.get("acknowledgedChunks") or []
                        if isinstance(receipt, dict)
                    ][:_MAX_TRANSFER_PARTS],
                }
                for row in raw_files[:_MAX_PUBLIC_FILES]
            ],
            "summary": {
                "fileCount": int(
                    (state.get("summary") or {}).get("fileCount") or 0
                ),
                "totalBytes": int(
                    (state.get("summary") or {}).get("totalBytes") or 0
                ),
                "completedFiles": int(
                    (state.get("summary") or {}).get(
                        "completedFiles"
                    )
                    or 0
                ),
                "failedFiles": int(
                    (state.get("summary") or {}).get("failedFiles") or 0
                ),
                "bytesSent": int(
                    (state.get("summary") or {}).get("bytesSent") or 0
                ),
                "returnedFiles": min(len(raw_files), _MAX_PUBLIC_FILES),
                "filesTruncated": max(
                    0, len(raw_files) - _MAX_PUBLIC_FILES
                ),
            },
            "cancellation": {
                "requested": bool(cancellation.get("requested")),
                "requestedAt": str(
                    cancellation.get("requestedAt") or ""
                ),
                "remoteAttempted": bool(
                    cancellation.get("remoteAttempted")
                ),
                "remoteAcknowledged": bool(
                    cancellation.get("remoteAcknowledged")
                ),
                "remoteHttpStatus": cancellation.get("remoteHttpStatus"),
                "errorCode": str(cancellation.get("errorCode") or ""),
            },
            "error": (
                {"code": str(error.get("code") or "")}
                if isinstance(error, dict)
                else None
            ),
        }
        from .proofs_d_host import check_nearby_projection
        check_nearby_projection(state, public)
        return public

    @contextmanager
    def _state_guard(self) -> Iterator[None]:
        with self._process_state_lock:
            with self._cross_process_state_guard():
                yield

    @contextmanager
    def _cross_process_state_guard(self) -> Iterator[None]:
        """A short, stale-owner-aware lock shared by service processes."""

        self.nearby_root.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + 3.0
        acquired = False
        owner_path = self.state_lock_path / "owner.json"
        while time.monotonic() < deadline:
            try:
                self.state_lock_path.mkdir()
            except FileExistsError:
                remove_stale = False
                try:
                    age = max(
                        0.0,
                        time.time() - self.state_lock_path.stat().st_mtime,
                    )
                    lock = self._read_json_bounded(
                        owner_path,
                        max_bytes=64 * 1024,
                    )
                    owner_pid = int((lock or {}).get("ownerPid") or 0)
                    remove_stale = (
                        age >= 5.0 and not self._pid_is_running(owner_pid)
                    )
                except (
                    OSError,
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                    ValueError,
                ):
                    try:
                        remove_stale = (
                            time.time()
                            - self.state_lock_path.stat().st_mtime
                            >= 5.0
                        )
                    except OSError:
                        remove_stale = False
                if remove_stale:
                    if self.state_lock_path.is_file():
                        self.state_lock_path.unlink(missing_ok=True)
                    else:
                        owner_path.unlink(missing_ok=True)
                        try:
                            self.state_lock_path.rmdir()
                        except OSError:
                            pass
                    continue
                time.sleep(0.01)
                continue
            else:
                atomic_write_json(
                    owner_path,
                    {
                        "ownerPid": os.getpid(),
                        "createdAt": utc_now(),
                    },
                )
                acquired = True
                break
        if not acquired:
            raise RuntimeError("Nearby Send state is busy")
        try:
            yield
        finally:
            self._unlink_with_retry(owner_path)
            deadline = time.monotonic() + 0.5
            while True:
                try:
                    self.state_lock_path.rmdir()
                    break
                except FileNotFoundError:
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.01)

    def _claim_transfer(self, transfer_id: str) -> None:
        with self._state_guard():
            existing_state: dict[str, Any] | None
            try:
                existing_state = self._read_json_bounded(
                    self.active_state_path,
                    max_bytes=_MAX_STATE_BYTES,
                )
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValueError,
            ):
                existing_state = None
                self.active_state_path.unlink(missing_ok=True)
                self.cancel_request_path.unlink(missing_ok=True)

            if existing_state is not None:
                status = str(existing_state.get("status") or "")
                owner_pid = int(existing_state.get("ownerPid") or 0)
                if (
                    status in _ACTIVE_TRANSFER_STATES
                    and self._pid_is_running(owner_pid)
                ):
                    raise RuntimeError(
                        "Another Nearby Send transfer is already active"
                    )
                if status in _ACTIVE_TRANSFER_STATES:
                    interrupted = {
                        **existing_state,
                        "status": "interrupted",
                        "active": False,
                        "updatedAt": utc_now(),
                        "completedAt": utc_now(),
                        "recipient": {},
                        "sessionId": "",
                        "error": {"code": "owner_process_stopped"},
                    }
                    atomic_write_json(self.active_state_path, interrupted)
                    self.cancel_request_path.unlink(missing_ok=True)

            try:
                claim = self._read_json_bounded(
                    self.transfer_claim_path,
                    max_bytes=64 * 1024,
                )
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValueError,
            ):
                claim = None
            if claim is not None and self._pid_is_running(
                int(claim.get("ownerPid") or 0)
            ):
                raise RuntimeError(
                    "Another Nearby Send transfer is already active"
                )
            self.transfer_claim_path.unlink(missing_ok=True)
            descriptor = os.open(
                self.transfer_claim_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "schema": "neyvia.nearby-transfer-claim/v1",
                        "transferId": transfer_id,
                        "ownerPid": os.getpid(),
                        "createdAt": utc_now(),
                    },
                    handle,
                )
                handle.flush()
                os.fsync(handle.fileno())

    def _release_transfer_claim_unlocked(
        self,
        transfer_id: str = "",
        *,
        force: bool = False,
    ) -> None:
        if not self.transfer_claim_path.is_file():
            return
        if force:
            self.transfer_claim_path.unlink(missing_ok=True)
            return
        try:
            claim = self._read_json_bounded(
                self.transfer_claim_path,
                max_bytes=64 * 1024,
            )
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
        ):
            claim = None
        if claim is None or str(claim.get("transferId") or "") == transfer_id:
            self.transfer_claim_path.unlink(missing_ok=True)

    def _read_active_state_for_update(
        self,
        transfer_id: str = "",
    ) -> dict[str, Any] | None:
        with self._state_guard():
            try:
                state = self._read_json_bounded(
                    self.active_state_path,
                    max_bytes=_MAX_STATE_BYTES,
                )
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValueError,
            ):
                return None
            if state is None:
                return None
            if transfer_id and str(state.get("transferId") or "") != transfer_id:
                return None
            return state

    def _mutate_active_state(
        self,
        transfer_id: str,
        mutate: Any,
    ) -> dict[str, Any] | None:
        with self._state_guard():
            try:
                state = self._read_json_bounded(
                    self.active_state_path,
                    max_bytes=_MAX_STATE_BYTES,
                )
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValueError,
            ):
                return None
            if (
                state is None
                or str(state.get("transferId") or "") != transfer_id
            ):
                return None
            updated = mutate(state)
            if not isinstance(updated, dict):
                raise TypeError("Nearby Send state mutation must return a dict")
            atomic_write_json(self.active_state_path, updated)
            return updated

    def _set_file_state(
        self,
        transfer_id: str,
        file_id: str,
        *,
        state: str,
        bytes_sent: int | None = None,
        acknowledged_offset: int | None = None,
        acknowledged_chunks: list[dict[str, Any]] | None = None,
        resumed_parts: int | None = None,
        uploaded_parts: int | None = None,
    ) -> None:
        def update(current: dict[str, Any]) -> dict[str, Any]:
            files = [
                dict(row)
                for row in current.get("files") or []
                if isinstance(row, dict)
            ]
            for row in files:
                if str(row.get("fileId") or "") != file_id:
                    continue
                row["state"] = state
                if bytes_sent is not None:
                    row["bytesSent"] = max(
                        int(row.get("bytesSent") or 0),
                        min(max(0, int(bytes_sent)), int(row.get("size") or 0)),
                    )
                if acknowledged_offset is not None:
                    row["acknowledgedOffset"] = max(
                        int(row.get("acknowledgedOffset") or 0),
                        min(
                            max(0, int(acknowledged_offset)),
                            int(row.get("size") or 0),
                        ),
                    )
                if acknowledged_chunks is not None:
                    row["acknowledgedChunks"] = [
                        {
                            "part": int(receipt.get("part") or 0),
                            "offset": int(receipt.get("offset") or 0),
                            "size": int(receipt.get("size") or 0),
                            "sha256": str(receipt.get("sha256") or ""),
                            "integrityVerified": bool(
                                receipt.get("integrityVerified")
                            ),
                            "source": str(receipt.get("source") or ""),
                        }
                        for receipt in acknowledged_chunks[
                            :_MAX_TRANSFER_PARTS
                        ]
                        if isinstance(receipt, dict)
                    ]
                if resumed_parts is not None:
                    row["resumedParts"] = max(0, int(resumed_parts))
                if uploaded_parts is not None:
                    row["uploadedParts"] = max(0, int(uploaded_parts))
            summary = dict(current.get("summary") or {})
            summary["completedFiles"] = sum(
                1 for row in files if row.get("state") == "completed"
            )
            summary["failedFiles"] = sum(
                1 for row in files if row.get("state") == "failed"
            )
            summary["bytesSent"] = sum(
                max(0, int(row.get("bytesSent") or 0)) for row in files
            )
            return {
                **current,
                "files": files,
                "summary": summary,
                "updatedAt": utc_now(),
            }

        self._mutate_active_state(transfer_id, update)

    def _write_cancel_request(
        self,
        transfer_id: str,
        *,
        reason: str,
    ) -> None:
        atomic_write_json(
            self.cancel_request_path,
            {
                "schema": NEARBY_CANCEL_REQUEST_SCHEMA,
                "transferId": transfer_id,
                "requestedAt": utc_now(),
                "requesterPid": os.getpid(),
                "reason": reason,
            },
        )

    def _cancel_request_for(
        self,
        transfer_id: str,
    ) -> dict[str, Any] | None:
        try:
            request = self._read_json_bounded(
                self.cancel_request_path,
                max_bytes=64 * 1024,
            )
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
        ):
            return None
        if (
            request is None
            or request.get("schema") != NEARBY_CANCEL_REQUEST_SCHEMA
            or str(request.get("transferId") or "") != transfer_id
        ):
            return None
        return request

    def _raise_if_cancelled(self, transfer_id: str) -> None:
        request = self._cancel_request_for(transfer_id)
        if request is not None:
            raise _TransferCancelled(
                str(request.get("reason") or "operator_request")
            )

    def _merge_cancellation_result(
        self,
        transfer_id: str,
        result: dict[str, Any],
    ) -> None:
        def update(current: dict[str, Any]) -> dict[str, Any]:
            cancellation = dict(current.get("cancellation") or {})
            previous_acknowledged = bool(
                cancellation.get("remoteAcknowledged")
            )
            acknowledged = previous_acknowledged or bool(
                result.get("acknowledged")
            )
            return {
                **current,
                "status": (
                    "cancelling"
                    if str(current.get("status") or "")
                    in _ACTIVE_TRANSFER_STATES
                    else str(current.get("status") or "")
                ),
                "updatedAt": utc_now(),
                "cancellation": {
                    **cancellation,
                    "requested": bool(
                        cancellation.get("requested")
                        or self._cancel_request_for(transfer_id)
                    ),
                    "remoteAttempted": bool(
                        cancellation.get("remoteAttempted")
                        or result.get("attempted")
                    ),
                    "remoteAcknowledged": acknowledged,
                    "remoteHttpStatus": (
                        result.get("httpStatus")
                        if result.get("httpStatus") is not None
                        else cancellation.get("remoteHttpStatus")
                    ),
                    "errorCode": (
                        ""
                        if acknowledged
                        else str(
                            result.get("errorCode")
                            or cancellation.get("errorCode")
                            or ""
                        )
                    ),
                },
            }

        self._mutate_active_state(transfer_id, update)

    def _mark_interrupted(self, transfer_id: str) -> None:
        with self._state_guard():
            try:
                current = self._read_json_bounded(
                    self.active_state_path,
                    max_bytes=_MAX_STATE_BYTES,
                )
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValueError,
            ):
                current = None
            if current and str(current.get("transferId") or "") == transfer_id:
                atomic_write_json(
                    self.active_state_path,
                    {
                        **current,
                        "status": "interrupted",
                        "active": False,
                        "updatedAt": utc_now(),
                        "completedAt": utc_now(),
                        "recipient": {},
                        "sessionId": "",
                        "error": {"code": "sender_interrupted"},
                    },
                )
            self.cancel_request_path.unlink(missing_ok=True)
            self._release_transfer_claim_unlocked(transfer_id=transfer_id)

    def _workspace_reference(self, value: str | Path) -> str:
        path = Path(value)
        if not path.is_absolute():
            path = self.root / path
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(self.root)
        except ValueError:
            return ""
        return relative.as_posix()

    @staticmethod
    def _safe_source_ref(value: object) -> str:
        text = str(value or "").strip().replace("\\", "/")
        candidate = Path(text)
        if (
            not text
            or candidate.is_absolute()
            or ".." in candidate.parts
            or text.startswith("/")
        ):
            return ""
        return text[:1024]

    @staticmethod
    def _read_json_bounded(
        path: Path,
        *,
        max_bytes: int,
    ) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        if path.stat().st_size > max_bytes:
            raise ValueError("JSON state exceeds the safe read limit")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON state must be an object")
        return payload

    @staticmethod
    def _unlink_with_retry(path: Path) -> None:
        deadline = time.monotonic() + 0.5
        while True:
            try:
                path.unlink(missing_ok=True)
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    return
                time.sleep(0.01)

    @staticmethod
    def _pid_is_running(pid: int) -> bool:
        if pid <= 0:
            return False
        if pid == os.getpid():
            return True
        if os.name == "nt":
            import ctypes

            process_query_limited_information = 0x1000
            still_active = 259
            access_denied = 5
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(
                process_query_limited_information,
                False,
                pid,
            )
            if not handle:
                return ctypes.get_last_error() == access_denied
            try:
                exit_code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(
                    handle,
                    ctypes.byref(exit_code),
                ):
                    return True
                return exit_code.value == still_active
            finally:
                kernel32.CloseHandle(handle)
        try:
            os.kill(pid, 0)
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _request_timeout_seconds(self) -> float:
        return float(
            max(
                1,
                min(
                    int(
                        self.limits.get("requestTimeoutSeconds")
                        or 30
                    ),
                    300,
                ),
            )
        )

    @staticmethod
    def _apply_remaining_timeout(
        connection: http.client.HTTPConnection,
        deadline: float,
    ) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _TransferFailure("upload_timeout")
        timeout = max(0.05, remaining)
        connection.timeout = timeout
        if connection.sock is not None:
            connection.sock.settimeout(timeout)

    def _read_chunk_ack_body(
        self,
        transfer_id: str,
        connection: http.client.HTTPConnection,
        response: http.client.HTTPResponse,
        deadline: float,
    ) -> bytes:
        raw_length = response.getheader("Content-Length")
        if raw_length is None:
            if response.status == 204:
                return b""
            raise _TransferFailure(
                "recipient_chunk_ack_length_missing",
                http_status=response.status,
            )
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise _TransferFailure(
                "invalid_chunk_acknowledgement",
                http_status=response.status,
            ) from exc
        if not 0 <= length <= 64 * 1024:
            raise _TransferFailure(
                "recipient_chunk_ack_too_large",
                http_status=response.status,
            )
        body = bytearray()
        while len(body) < length:
            self._raise_if_cancelled(transfer_id)
            self._apply_remaining_timeout(connection, deadline)
            piece = response.read1(min(8192, length - len(body)))
            if not piece:
                raise _TransferFailure(
                    "invalid_chunk_acknowledgement",
                    http_status=response.status,
                )
            body.extend(piece)
        return bytes(body)

    def _connection(
        self,
        endpoint: str,
        fingerprint: str,
    ) -> tuple[http.client.HTTPConnection, str]:
        parsed = urlparse(endpoint)
        timeout = self._request_timeout_seconds()
        base_path = parsed.path.rstrip("/")
        if parsed.scheme == "https":
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            connection = http.client.HTTPSConnection(
                parsed.hostname,
                parsed.port or 443,
                timeout=timeout,
                context=context,
            )
            connection.connect()
            certificate = connection.sock.getpeercert(binary_form=True)
            actual = hashlib.sha256(certificate).hexdigest()
            if actual != fingerprint:
                connection.close()
                raise ssl.SSLError(
                    "Recipient TLS certificate fingerprint does not match"
                )
            return connection, base_path
        return (
            http.client.HTTPConnection(
                parsed.hostname,
                parsed.port or 80,
                timeout=timeout,
            ),
            base_path,
        )

    def _validate_endpoint(
        self,
        endpoint: str,
        fingerprint: object,
    ) -> str:
        text = str(endpoint or "").strip().rstrip("/")
        parsed = urlparse(text)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Recipient endpoint must be a clean HTTP(S) URL")
        if parsed.scheme == "https":
            normalized = self._normalize_fingerprint(fingerprint)
            if len(normalized) != 64:
                raise ValueError(
                    "HTTPS recipients require a SHA-256 certificate fingerprint"
                )
        else:
            try:
                host = ipaddress.ip_address(parsed.hostname)
            except ValueError as exc:
                raise ValueError(
                    "Plain HTTP is allowed only on loopback"
                ) from exc
            if (
                not self.policy.get("allowPlainHttpLoopbackOnly", True)
                or not host.is_loopback
            ):
                raise ValueError("Plain HTTP is allowed only on loopback")
        return text

    def _workspace_file(self, value: str | Path) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self.root / path
        path = path.resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise PermissionError(
                "Nearby Send can read only active-workspace files"
            ) from exc
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def _verify_planned_file(self, value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("Transfer plan contains an invalid file")
        row = dict(value)
        path = self._workspace_file(str(row.get("path") or ""))
        chunk_bytes, max_parts = self._chunk_limits()
        digest, chunks = _hash_file_with_chunks(
            path,
            chunk_bytes=chunk_bytes,
        )
        has_planned_chunks = "chunks" in row
        planned_chunks = row.get("chunks")
        try:
            planned_size = int(row.get("size", -1))
            planned_modified = int(row.get("modified", -1))
        except (TypeError, ValueError) as exc:
            raise ValueError("Transfer plan contains invalid file metadata") from exc
        if (
            path.stat().st_size != planned_size
            or path.stat().st_mtime_ns != planned_modified
            or digest != str(row.get("sha256") or "")
        ):
            raise ValueError(
                f"Source changed after transfer preview: {path.name}"
            )
        if has_planned_chunks and (
            not isinstance(planned_chunks, list)
            or planned_chunks != chunks
        ):
            raise ValueError(
                f"Nearby-send chunk manifest does not match: {path.name}"
            )
        if len(chunks) > max_parts:
            raise ValueError("Transfer exceeds nearby-send chunk part limit")
        row["path"] = str(path)
        row["chunks"] = chunks
        row["chunkManifestMigrated"] = not has_planned_chunks
        from .proofs_d_nearby import check_verified_file
        check_verified_file(row, chunks, migrated=not has_planned_chunks)
        return row

    def _sender_info(self) -> dict[str, Any]:
        return {
            "alias": f"Neyvia-{socket.gethostname()}",
            "version": str(self.protocol.get("version") or "2.1"),
            "deviceModel": socket.gethostname(),
            "deviceType": "headless",
            "fingerprint": uuid.uuid4().hex,
            "port": int(self.protocol.get("port") or 53317),
            "protocol": "https",
            "download": False,
        }

    @staticmethod
    def _normalize_fingerprint(value: object) -> str:
        text = str(value or "").strip().replace(":", "").casefold()
        if text and (
            len(text) != 64
            or any(character not in "0123456789abcdef" for character in text)
        ):
            raise ValueError("Certificate fingerprint must be SHA-256")
        return text

    @staticmethod
    def _discovered_device(
        row: dict[str, Any],
        origin: str,
    ) -> dict[str, Any] | None:
        alias = str(row.get("alias") or "").strip()
        protocol = str(row.get("protocol") or "").casefold()
        fingerprint = str(row.get("fingerprint") or "").strip()
        try:
            port = int(row.get("port") or 53317)
        except (TypeError, ValueError):
            return None
        if (
            not alias
            or protocol not in {"http", "https"}
            or port < 1
            or port > 65535
        ):
            return None
        device_id = "nearby_" + hashlib.sha256(
            f"{origin}\0{port}\0{fingerprint}".encode("utf-8")
        ).hexdigest()[:20]
        return {
            "deviceId": device_id,
            "alias": alias[:200],
            "deviceModel": str(row.get("deviceModel") or "")[:200],
            "deviceType": str(row.get("deviceType") or "desktop"),
            "protocolVersion": str(row.get("version") or ""),
            "endpoint": f"{protocol}://{origin}:{port}",
            "certificateFingerprint": (
                fingerprint.replace(":", "").casefold()
                if protocol == "https"
                else ""
            ),
            "download": bool(row.get("download")),
        }
