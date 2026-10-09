"""Local-first BLAKE3 object cache prepared for an Iroh peer transport."""

from __future__ import annotations

import atexit
import base64
import copy
import hashlib
import json
import os
import queue
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterator

import blake3
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .capability_contracts import utc_now
from .durability import atomic_write_json
from .subprocess_utils import hidden_windows_subprocess_kwargs


IMPORT_PLAN_SCHEMA = "neyvia.p2p-cache-import-plan/v1"
FETCH_PLAN_SCHEMA = "neyvia.p2p-cache-fetch-plan/v1"
OBJECT_RECEIPT_SCHEMA = "neyvia.p2p-cache-object-receipt/v1"
PEER_CANDIDATES_SCHEMA = "neyvia.p2p-cache-peer-candidates/v1"
SCHEDULED_FETCH_PLAN_SCHEMA = "neyvia.p2p-cache-scheduled-fetch-plan/v1"
REPLICATION_PLAN_SCHEMA = "neyvia.p2p-cache-replication-plan/v1"
GC_PLAN_SCHEMA = "neyvia.p2p-cache-gc-plan/v1"
GC_RECEIPT_SCHEMA = "neyvia.p2p-cache-gc-receipt/v1"
GC_APPROVAL_SCHEMA = "neyvia.p2p-cache-gc-approval/v3"
GC_TRANSACTION_SCHEMA = "neyvia.p2p-cache-gc-transaction/v1"

_MAX_SCHEDULE_CANDIDATES = 32
_MAX_FETCH_ATTEMPTS = 8
_MAX_REPLICATION_TARGETS = 8
_MAX_GC_DELETES = 1_000
_MAX_GC_DELETE_BYTES = 4 * 1024 * 1024 * 1024
_UNAVAILABLE_PEER_HEALTH = {"offline", "unhealthy", "unreachable", "disabled"}
_GC_APPROVAL_ALGORITHM = "Ed25519"
_REPARSE_POINT_ATTRIBUTE = 0x400


def _deployment_storage_path(
    root: str | Path,
    configured: object,
    fallback: str | Path,
    *,
    _platform_name: str | None = None,
) -> Path:
    """Resolve mutable cache state without writing into an immutable release.

    Checked-in configuration can contain workstation-specific absolute paths.
    A foreign Windows path on POSIX (or a foreign POSIX path on Windows) is not
    a relative path: use the host-owned fallback beneath the control root.
    Genuine relative paths are also anchored to the control root and cannot
    escape it.
    """

    control_root = Path(root).expanduser().resolve()
    fallback_path = Path(fallback).expanduser()
    if not fallback_path.is_absolute():
        fallback_path = control_root / fallback_path
    fallback_path = fallback_path.resolve()

    raw = str(configured or "").strip()
    if not raw:
        return fallback_path
    platform_name = _platform_name or os.name
    foreign_absolute = (
        platform_name != "nt" and PureWindowsPath(raw).is_absolute()
    ) or (
        platform_name == "nt"
        and PurePosixPath(raw).is_absolute()
        and not raw.startswith(("//", "\\\\"))
    )
    if foreign_absolute:
        return fallback_path

    selected = Path(raw).expanduser()
    if selected.is_absolute():
        return selected.resolve()
    selected = (control_root / selected).resolve()
    try:
        selected.relative_to(control_root)
    except ValueError as exc:
        raise RuntimeError(
            "Relative P2P storage paths must stay inside the control root"
        ) from exc
    return selected


class _IrohSession:
    def __init__(
        self,
        *,
        executable: Path,
        expected_sha256: str,
        state_root: Path,
        store_root: Path,
        allowed_peers: tuple[str, ...],
        working_directory: Path,
        timeout: int,
        environment: dict[str, str],
    ) -> None:
        if not executable.is_file():
            raise RuntimeError("The verified Iroh cache sidecar is unavailable")
        with executable.open("rb") as handle:
            observed = hashlib.file_digest(handle, "sha256").hexdigest()
        if not expected_sha256 or observed != expected_sha256:
            raise RuntimeError("The Iroh cache sidecar hash does not match")
        self.timeout = timeout
        self.lock = threading.RLock()
        self.responses: queue.Queue[str | None] = queue.Queue()
        self.broken = False
        self.process = subprocess.Popen(
            [str(executable)],
            cwd=str(working_directory),
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
            **hidden_windows_subprocess_kwargs(),
        )
        self.reader = threading.Thread(
            target=self._read_responses,
            name="neyvia-iroh-cache-reader",
            daemon=True,
        )
        self.reader.start()
        try:
            ready = self._exchange(
                {
                    "operation": "session",
                    "stateRoot": str(state_root),
                    "storeRoot": str(store_root),
                    "allowedPeers": list(allowed_peers),
                }
            )
        except (OSError, RuntimeError):
            self.abort()
            raise
        if not bool(ready.get("ok")) or ready.get("status") != "session-ready":
            self.close()
            raise RuntimeError("The Iroh cache session did not start")

    def _read_responses(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                if line.strip():
                    self.responses.put(line)
        finally:
            self.responses.put(None)

    def _exchange(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.broken:
            raise RuntimeError("The Iroh cache session is not reusable")
        if self.process.poll() is not None or self.process.stdin is None:
            self.broken = True
            raise RuntimeError("The Iroh cache session is not running")
        try:
            self.process.stdin.write(
                json.dumps(
                    request,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
            self.process.stdin.flush()
        except OSError:
            self.broken = True
            raise
        try:
            line = self.responses.get(timeout=self.timeout)
        except queue.Empty as exc:
            self.broken = True
            raise RuntimeError("The Iroh cache session timed out") from exc
        if line is None:
            self.broken = True
            raise RuntimeError("The Iroh cache session stopped unexpectedly")
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            self.broken = True
            raise RuntimeError(
                "The Iroh cache session returned invalid output"
            ) from exc
        if not isinstance(payload, dict):
            self.broken = True
            raise RuntimeError("The Iroh cache session returned invalid output")
        return payload

    def request(self, request: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            return self._exchange(request)

    def close(self) -> None:
        with self.lock:
            if self.process.poll() is None and not self.broken:
                try:
                    self._exchange({"operation": "shutdown"})
                except (OSError, RuntimeError):
                    pass
            if self.process.stdin is not None:
                self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)

    def abort(self) -> None:
        """Stop a poisoned stream without consuming any queued response."""
        with self.lock:
            self.broken = True
            if self.process.stdin is not None:
                try:
                    self.process.stdin.close()
                except OSError:
                    pass
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)


_IROH_SESSIONS: dict[tuple[object, ...], _IrohSession] = {}
_IROH_SESSIONS_LOCK = threading.Lock()


@dataclass
class _ObjectMutationLockEntry:
    lock: threading.RLock
    references: int = 0


_OBJECT_MUTATION_LOCKS: dict[
    tuple[str, str],
    _ObjectMutationLockEntry,
] = {}
_OBJECT_MUTATION_LOCKS_GUARD = threading.Lock()


def shutdown_p2p_sessions() -> None:
    with _IROH_SESSIONS_LOCK:
        sessions = list(_IROH_SESSIONS.values())
        _IROH_SESSIONS.clear()
    for session in sessions:
        session.close()


atexit.register(shutdown_p2p_sessions)


def _canonical_hash(value: object) -> str:
    return blake3.blake3(
        _canonical_bytes(value)
    ).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class P2PCacheService:
    def __init__(
        self,
        root: str | Path,
        *,
        config_path: str | Path | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        project_root = Path(__file__).resolve().parents[2]
        selected = Path(
            config_path or self.root / "config" / "neyvia_p2p_cache.json"
        )
        if not selected.is_file():
            selected = project_root / "config" / "neyvia_p2p_cache.json"
        if not selected.is_file():
            raise FileNotFoundError(selected)
        self.config_path = selected.resolve()
        try:
            # utf-8-sig accepts a harmless editor-written BOM while preserving
            # strict JSON parsing for every other byte sequence.
            loaded_config = json.loads(selected.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            # Configurations can contain local deployment paths and peer
            # details.  Do not reflect either in a diagnostic returned to a
            # caller or captured in a receipt.
            raise ValueError("P2P cache configuration is invalid") from None
        if not isinstance(loaded_config, dict):
            raise ValueError("P2P cache configuration is invalid")
        self.config = loaded_config
        cache = dict(self.config.get("cache") or {})
        self.object_root = _deployment_storage_path(
            self.root,
            cache.get("root"),
            ".agent_control/p2p_cache/objects",
        )
        self.index_path = (
            self.root / ".agent_control" / "p2p_cache" / "index.sqlite3"
        )
        self.gc_journal_root = (
            self.index_path.parent / "gc_transactions"
        )
        if self.gc_journal_root.is_dir():
            self._recover_gc_transactions()

    @property
    def cache(self) -> dict[str, Any]:
        return dict(self.config.get("cache") or {})

    @property
    def policy(self) -> dict[str, Any]:
        return dict(self.config.get("policy") or {})

    @property
    def transport(self) -> dict[str, Any]:
        return dict(self.config.get("transport") or {})

    def compatibility_snapshot(self) -> dict[str, Any]:
        sidecar = self._sidecar_integrity()
        peers = self.policy.get("peers") or []
        return {
            "schema": "neyvia.p2p-cache-compatibility/v1",
            "transport": {
                key: self.transport.get(key)
                for key in (
                    "name",
                    "version",
                    "blobsVersion",
                    "docsVersion",
                    "gossipVersion",
                    "state",
                    "relayPolicy",
                    "publicIpfsGateway",
                )
            }
            | {
                # These are intentionally separate.  A deployment can be
                # configured but not installed, or installed but fail the
                # hash pin; neither condition is availability.
                "sidecarConfigured": sidecar["configured"],
                "sidecarExecutablePresent": sidecar["executablePresent"],
                "sidecarHashMatch": sidecar["hashMatch"],
                "sidecarAvailable": sidecar["available"],
                "sidecarState": str(
                    self.transport.get("sidecarState") or "not-installed"
                ),
                "persistentSession": bool(
                    self.transport.get("persistentSession", True)
                ),
            },
            "localStore": {
                "hash": "blake3",
                "rootAvailable": self.object_root.is_dir(),
                "indexAvailable": self.index_path.is_file(),
                "maxImportBytes": int(
                    self.cache.get("maxImportBytes") or 0
                ),
                "maxTextReadBytes": int(
                    self.cache.get("maxTextReadBytes") or 0
                ),
            },
            "policy": {
                "workspaceImportsOnly": bool(
                    self.policy.get("importsWorkspaceOnly", True)
                ),
                "publicDiscoveryDefault": bool(
                    self.policy.get("publicDiscoveryDefault", False)
                ),
                "publicRelayDefault": bool(
                    self.policy.get("publicRelayDefault", False)
                ),
                "encryptedTransportRequired": bool(
                    self.policy.get("encryptedTransportRequired", True)
                ),
                "approvedPeers": len(peers),
            },
            "limitations": {
                # Implemented = product code path exists; Available/Configured
                # track whether the sidecar binary and peers are ready.
                "localCasImplemented": True,
                "irohSidecarImplemented": True,
                "remoteFetchImplemented": True,
                "remoteFetchConfigured": sidecar["available"] and bool(peers),
                "remotePublishImplemented": False,
            },
        }

    def bootstrap(self) -> dict[str, Any]:
        stats = self.stats()
        return {
            "schema": "neyvia.p2p-cache-bootstrap/v1",
            "transport": str(self.transport.get("name") or ""),
            "transportState": str(self.transport.get("state") or ""),
            "objects": stats["summary"]["objects"],
            "bytes": stats["summary"]["bytes"],
            "pinned": stats["summary"]["pinned"],
            "localLookupReady": True,
            "remoteLookupReady": self._sidecar_integrity()["available"]
            and bool(self.policy.get("peers") or []),
            "detailsDeferred": True,
        }

    def plan_import(
        self,
        path: str | Path,
        *,
        kind: str = "artifact",
        pin: bool = True,
    ) -> dict[str, Any]:
        source = self._workspace_file(path)
        normalized_kind = str(kind or "").strip().casefold()
        allowed = {
            str(item).casefold()
            for item in self.policy.get("allowedKinds") or []
        }
        if normalized_kind not in allowed:
            raise ValueError("Unsupported cache object kind")
        size = source.stat().st_size
        maximum = int(
            self.cache.get("maxImportBytes") or 20 * 1024 * 1024 * 1024
        )
        if size > maximum:
            raise ValueError(f"Object exceeds {maximum} bytes")
        started = time.perf_counter()
        digest = self._hash_file(source)
        plan = {
            "schema": IMPORT_PLAN_SCHEMA,
            "planId": f"cacheplan_{uuid.uuid4().hex[:20]}",
            "createdAt": utc_now(),
            "sourcePath": str(source),
            "workspacePath": source.relative_to(self.root).as_posix(),
            "sourceSize": size,
            "sourceMtimeNs": source.stat().st_mtime_ns,
            "objectHash": digest,
            "algorithm": "blake3",
            "kind": normalized_kind,
            "pin": bool(pin),
            "alreadyPresent": self._object_path(digest).is_file(),
            "hashDurationMs": round(
                (time.perf_counter() - started) * 1000.0,
                3,
            ),
            "summary": {
                "copyRequired": not self._object_path(digest).is_file(),
                "networkRequired": False,
                "remotePublish": False,
            },
        }
        plan["planHash"] = self._plan_hash(plan)
        return plan

    def import_object(
        self,
        plan: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        if not approved:
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "artifact.write",
            }
        self._validate_plan(plan)
        source = self._workspace_file(str(plan.get("sourcePath") or ""))
        digest = str(plan["objectHash"])
        source_stat = source.stat()
        if (
            source_stat.st_size != int(plan.get("sourceSize") if plan.get("sourceSize") is not None else -1)
            or source_stat.st_mtime_ns
            != int(plan.get("sourceMtimeNs") or -1)
            or self._hash_file(source) != digest
        ):
            raise ValueError("Source changed after cache preview")
        target = self._object_path(digest)
        temporary: Path | None = None
        copied = False
        if not target.is_file():
            self._assert_safe_descendant(
                self.object_root,
                target.parent,
                allow_missing_final=True,
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            self._assert_safe_descendant(
                self.object_root,
                target.parent,
                require_final_directory=True,
            )
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{digest}.",
                suffix=".tmp",
                dir=str(target.parent),
            )
            temporary = Path(temp_name)
            try:
                self._copy_source_to_descriptor(
                    source,
                    descriptor=descriptor,
                    digest=digest,
                )
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
        with self._object_mutation_locks([digest]):
            database = self._connect(create=True)
            try:
                database.execute("BEGIN IMMEDIATE")
                source = self._workspace_file(
                    str(plan.get("sourcePath") or "")
                )
                source_stat = source.stat()
                if (
                    source_stat.st_size
                    != int(plan.get("sourceSize") if plan.get("sourceSize") is not None else -1)
                    or source_stat.st_mtime_ns
                    != int(plan.get("sourceMtimeNs") or -1)
                    or self._hash_file(source) != digest
                ):
                    raise ValueError("Source changed after cache preview")
                self._assert_safe_descendant(
                    self.object_root,
                    target.parent,
                    allow_missing_final=True,
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                self._assert_safe_descendant(
                    self.object_root,
                    target.parent,
                    require_final_directory=True,
                )
                if target.exists():
                    self._assert_safe_regular_file(
                        self.object_root,
                        target,
                    )
                    if self._hash_file(target) != digest:
                        raise RuntimeError(
                            "Existing cache object failed integrity"
                        )
                else:
                    if temporary is None:
                        descriptor, temp_name = tempfile.mkstemp(
                            prefix=f".{digest}.",
                            suffix=".tmp",
                            dir=str(target.parent),
                        )
                        temporary = Path(temp_name)
                        self._copy_source_to_descriptor(
                            source,
                            descriptor=descriptor,
                            digest=digest,
                        )
                    self._assert_safe_regular_file(
                        self.object_root,
                        temporary,
                    )
                    self._assert_safe_descendant(
                        self.object_root,
                        target,
                        allow_missing_final=True,
                    )
                    os.replace(temporary, target)
                    temporary = None
                    copied = True
                self._assert_safe_regular_file(self.object_root, target)
                if self._hash_file(target) != digest:
                    raise RuntimeError(
                        "Cache object failed final integrity recheck"
                    )
                target_stat = target.stat()
                self._record_object(
                    digest=digest,
                    size=target_stat.st_size,
                    mtime_ns=target_stat.st_mtime_ns,
                    kind=str(plan.get("kind") or ""),
                    pinned=bool(plan.get("pin")),
                    workspace_path=str(plan.get("workspacePath") or ""),
                    database=database,
                )
                database.commit()
            except Exception:
                database.rollback()
                raise
            finally:
                database.close()
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return {
            "schema": OBJECT_RECEIPT_SCHEMA,
            "receiptId": f"cachereceipt_{uuid.uuid4().hex[:20]}",
            "createdAt": utc_now(),
            "planId": str(plan.get("planId") or ""),
            "planHash": str(plan.get("planHash") or ""),
            "objectHash": digest,
            "algorithm": "blake3",
            "bytes": target_stat.st_size,
            "kind": str(plan.get("kind") or ""),
            "pinned": bool(plan.get("pin")),
            "copied": copied,
            "deduplicated": not copied,
            "integrityVerified": True,
            "networkUsed": False,
            "ok": True,
            "status": "available",
        }

    def plan_fetch(
        self,
        object_hash: str,
        *,
        peer_ref: str,
        kind: str = "artifact",
        pin: bool = True,
    ) -> dict[str, Any]:
        digest = self._validated_hash(object_hash)
        normalized_kind = str(kind or "").strip().casefold()
        allowed = {
            str(item).casefold()
            for item in self.policy.get("allowedKinds") or []
        }
        if normalized_kind not in allowed:
            raise ValueError("Unsupported cache object kind")
        peer = self._peer(peer_ref)
        ticket = self._peer_offer(peer, digest)
        plan = {
            "schema": FETCH_PLAN_SCHEMA,
            "planId": f"cachefetch_{uuid.uuid4().hex[:20]}",
            "createdAt": utc_now(),
            "objectHash": digest,
            "peerRef": str(peer.get("peerRef") or ""),
            "offerDigest": _canonical_hash(ticket),
            "kind": normalized_kind,
            "pin": bool(pin),
            "alreadyPresent": self._object_path(digest).is_file(),
            "maxBytes": int(
                self.cache.get("maxImportBytes") or 20 * 1024 * 1024 * 1024
            ),
            "summary": {
                "networkRequired": not self._object_path(digest).is_file(),
                "transport": "iroh-blobs",
                "encrypted": True,
                "publicDiscovery": False,
                "publicRelay": False,
            },
        }
        plan["planHash"] = self._plan_hash(plan)
        return plan

    def approved_peer_candidates(self, object_hash: str) -> dict[str, Any]:
        """Return a bounded, deterministic view of approved fetch candidates.

        Health and latency values are policy observations, not live probes.
        This method never starts the transport and never reports network
        availability on the strength of configuration alone.
        """
        digest = self._validated_hash(object_hash)
        limit = self._positive_bounded_policy_int(
            self.policy.get("maxScheduleCandidates"),
            default=_MAX_SCHEDULE_CANDIDATES,
            maximum=_MAX_SCHEDULE_CANDIDATES,
            label="maxScheduleCandidates",
        )
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_candidate in self.policy.get("peers") or []:
            peer = dict(raw_candidate or {})
            peer_ref = str(peer.get("peerRef") or "").strip()
            if (
                not peer_ref
                or peer_ref in seen
                or not bool(peer.get("enabled", True))
            ):
                continue
            seen.add(peer_ref)
            endpoint = str(peer.get("endpointId") or "").strip()
            if len(endpoint) < 32 or len(endpoint) > 128:
                continue
            try:
                ticket = self._peer_offer(peer, digest)
            except ValueError:
                continue
            health = self._peer_health(peer)
            status = health["status"]
            eligible = status not in _UNAVAILABLE_PEER_HEALTH
            candidates.append(
                {
                    "peerRef": peer_ref,
                    "health": status,
                    "latencyMs": health["latencyMs"],
                    "consecutiveFailures": health["consecutiveFailures"],
                    "score": self._peer_score(health),
                    "healthHash": _canonical_hash(health),
                    "eligible": eligible,
                    "peerIdentityHash": _canonical_hash(endpoint),
                    "offerDigest": _canonical_hash(ticket),
                }
            )
        candidates.sort(
            key=lambda item: (
                not bool(item["eligible"]),
                int(item["score"]),
                str(item["peerRef"]),
            )
        )
        bounded = candidates[:limit]
        for rank, candidate in enumerate(bounded, start=1):
            candidate["rank"] = rank
        sidecar = self._sidecar_integrity()
        return {
            "schema": PEER_CANDIDATES_SCHEMA,
            "objectHash": digest,
            "transportReady": sidecar["available"],
            "transportState": (
                "verified" if sidecar["available"] else "unavailable"
            ),
            "candidates": bounded,
            "summary": {
                "approvedWithOffer": len(candidates),
                "eligible": sum(
                    1 for candidate in candidates if candidate["eligible"]
                ),
                "returned": len(bounded),
                "truncated": len(candidates) > len(bounded),
            },
            "networkProbed": False,
            "detailsBounded": True,
        }

    def plan_scheduled_fetch(
        self,
        object_hash: str,
        *,
        kind: str = "artifact",
        pin: bool = True,
    ) -> dict[str, Any]:
        digest = self._validated_hash(object_hash)
        normalized_kind = str(kind or "").strip().casefold()
        allowed = {
            str(item).casefold()
            for item in self.policy.get("allowedKinds") or []
        }
        if normalized_kind not in allowed:
            raise ValueError("Unsupported cache object kind")
        candidates = self.approved_peer_candidates(digest)
        max_attempts = self._positive_bounded_policy_int(
            self.policy.get("maxFetchAttempts"),
            default=3,
            maximum=_MAX_FETCH_ATTEMPTS,
            label="maxFetchAttempts",
        )
        attempt_order = self._deterministic_attempt_order(
            digest,
            candidates=candidates,
        )
        already_present = self._object_path(digest).is_file()
        transport_ready = bool(candidates["transportReady"])
        if already_present:
            state = "local"
        elif not attempt_order:
            state = "no_eligible_peers"
        elif not transport_ready:
            state = "transport_unavailable"
        else:
            state = "ready"
        plan = {
            "schema": SCHEDULED_FETCH_PLAN_SCHEMA,
            "planId": f"cacheschedule_{uuid.uuid4().hex[:20]}",
            "createdAt": utc_now(),
            "objectHash": digest,
            "kind": normalized_kind,
            "pin": bool(pin),
            "alreadyPresent": already_present,
            "maxBytes": int(
                self.cache.get("maxImportBytes")
                or 20 * 1024 * 1024 * 1024
            ),
            "transportBinding": self._transport_schedule_binding(),
            "schedulingPolicyHash": _canonical_hash(
                self._scheduling_policy_snapshot()
            ),
            "attemptOrder": attempt_order,
            "retryPolicy": {
                "maxAttempts": max_attempts,
                "failover": True,
                "retrySamePeer": False,
            },
            "state": state,
            "summary": {
                "networkRequired": not already_present,
                "transportReady": transport_ready,
                "candidateCount": len(attempt_order),
                "selection": (
                    str(attempt_order[0]["peerRef"])
                    if attempt_order
                    else None
                ),
            },
        }
        plan["planHash"] = self._plan_hash(plan)
        return plan

    def fetch_scheduled(
        self,
        plan: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        if not approved:
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "network.read",
            }
        self._validate_scheduled_fetch_plan(plan)
        digest = self._validated_hash(str(plan.get("objectHash") or ""))
        target = self._object_path(digest)
        if target.is_file():
            target = self._verified_object(digest)
            receipt = self._fetch_receipt(
                plan,
                target,
                downloaded=False,
                duration_ms=0.0,
            )
            receipt.update(
                {
                    "scheduleState": "local",
                    "attempts": [],
                    "selectedPeerRef": None,
                    "networkAttempted": False,
                }
            )
            receipt.pop("peerRef", None)
            return receipt
        attempt_order = list(plan.get("attemptOrder") or [])
        if not attempt_order:
            return {
                "schema": OBJECT_RECEIPT_SCHEMA,
                "planId": str(plan.get("planId") or ""),
                "planHash": str(plan.get("planHash") or ""),
                "objectHash": digest,
                "ok": False,
                "status": "no_eligible_peers",
                "scheduleState": "blocked",
                "attempts": [],
                "networkUsed": False,
                "networkAttempted": False,
                "integrityVerified": False,
            }
        integrity = self._sidecar_integrity()
        if not integrity["available"]:
            return {
                "schema": OBJECT_RECEIPT_SCHEMA,
                "planId": str(plan.get("planId") or ""),
                "planHash": str(plan.get("planHash") or ""),
                "objectHash": digest,
                "ok": False,
                "status": "transport_unavailable",
                "scheduleState": "blocked",
                "attempts": [],
                "networkUsed": False,
                "networkAttempted": False,
                "integrityVerified": False,
            }
        attempts: list[dict[str, Any]] = []
        for sequence, candidate in enumerate(attempt_order, start=1):
            self._assert_scheduled_attempt_order_current(plan, digest=digest)
            if str(plan.get("schedulingPolicyHash") or "") != _canonical_hash(
                self._scheduling_policy_snapshot()
            ):
                raise ValueError(
                    "Scheduled cache fetch scheduling policy changed"
                )
            current_budget = self._positive_bounded_policy_int(
                self.policy.get("maxFetchAttempts"),
                default=3,
                maximum=_MAX_FETCH_ATTEMPTS,
                label="maxFetchAttempts",
            )
            if sequence > current_budget:
                raise ValueError(
                    "Scheduled cache fetch attempt budget changed"
                )
            peer_ref = str(candidate.get("peerRef") or "")
            peer = self._validate_scheduled_candidate(
                candidate,
                digest=digest,
            )
            single_plan = self.plan_fetch(
                digest,
                peer_ref=peer_ref,
                kind=str(plan.get("kind") or ""),
                pin=bool(plan.get("pin")),
            )
            if (
                str(single_plan.get("offerDigest") or "")
                != str(candidate.get("offerDigest") or "")
            ):
                raise ValueError("Peer offer changed after cache schedule preview")
            try:
                receipt = self.fetch_object(single_plan, approved=True)
            except subprocess.TimeoutExpired:
                attempts.append(
                    {
                        "sequence": sequence,
                        "peerRef": peer_ref,
                        "status": "timeout",
                        "errorClass": "transport_timeout",
                    }
                )
                continue
            except (OSError, RuntimeError) as exc:
                attempts.append(
                    {
                        "sequence": sequence,
                        "peerRef": peer_ref,
                        "status": "failed",
                        "errorClass": type(exc).__name__,
                    }
                )
                continue
            attempts.append(
                {
                    "sequence": sequence,
                    "peerRef": peer_ref,
                    "status": "succeeded",
                }
            )
            receipt.update(
                {
                    "planId": str(plan.get("planId") or ""),
                    "planHash": str(plan.get("planHash") or ""),
                    "scheduleState": "succeeded",
                    "attempts": attempts,
                    "selectedPeerRef": peer_ref,
                    "networkAttempted": True,
                }
            )
            receipt.pop("peerRef", None)
            return receipt
        return {
            "schema": OBJECT_RECEIPT_SCHEMA,
            "planId": str(plan.get("planId") or ""),
            "planHash": str(plan.get("planHash") or ""),
            "objectHash": digest,
            "ok": False,
            "status": "attempts_exhausted",
            "scheduleState": "exhausted",
            "attempts": attempts,
            "networkUsed": False,
            "networkAttempted": bool(attempts),
            "integrityVerified": False,
        }

    def plan_replication(
        self,
        object_hash: str,
        *,
        replica_peer_refs: tuple[str, ...] | list[str] = (),
    ) -> dict[str, Any]:
        digest = self._validated_hash(object_hash)
        self._verified_object(digest)
        replication = dict(self.policy.get("replication") or {})
        target_copies = max(
            1,
            min(
                int(replication.get("targetCopies") or 2),
                _MAX_REPLICATION_TARGETS + 1,
            ),
        )
        configured_targets = int(
            replication.get("maxTargetsPerPlan")
            or _MAX_REPLICATION_TARGETS
        )
        max_targets = max(
            1,
            min(configured_targets, _MAX_REPLICATION_TARGETS),
        )
        approved = self._approved_peers_for_replication()
        approved_refs = {str(peer["peerRef"]) for peer in approved}
        reported = sorted(
            {
                str(peer_ref).strip()
                for peer_ref in replica_peer_refs
                if str(peer_ref).strip() in approved_refs
            }
        )
        verified_copies = 1
        needed = max(0, target_copies - verified_copies)
        targets = [
            str(peer["peerRef"])
            for peer in approved
        ][: min(needed, max_targets)]
        plan = {
            "schema": REPLICATION_PLAN_SCHEMA,
            "planId": f"cachereplication_{uuid.uuid4().hex[:20]}",
            "createdAt": utc_now(),
            "objectHash": digest,
            "policy": {
                "targetCopies": target_copies,
                "maxTargetsPerPlan": max_targets,
            },
            "copyAccounting": {
                "verifiedCopies": verified_copies,
                "verifiedLocalCopies": 1,
                "verifiedRemoteCopies": 0,
                "plannedCopies": len(targets),
                "unverifiedReportedCopies": len(reported),
            },
            "reportedPeerRefs": reported,
            "targetPeerRefs": targets,
            "execution": {
                "implemented": False,
                "status": "planning_only",
                "providerContract": "P2PProviderService.plan_publication",
            },
            "summary": {
                "targetSatisfiedByVerifiedCopies": (
                    verified_copies >= target_copies
                ),
                "targetCouldBeSatisfiedAfterVerification": (
                    verified_copies + len(targets) >= target_copies
                ),
                "networkUsed": False,
            },
        }
        plan["planHash"] = self._plan_hash(plan)
        return plan

    def fetch_object(
        self,
        plan: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        if not approved:
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "network.read",
            }
        self._validate_fetch_plan(plan)
        digest = self._validated_hash(str(plan.get("objectHash") or ""))
        target = self._object_path(digest)
        if target.is_file():
            target = self._verified_object(digest)
            return self._fetch_receipt(
                plan,
                target,
                downloaded=False,
                duration_ms=0.0,
            )
        peer = self._peer(str(plan.get("peerRef") or ""))
        ticket = self._peer_offer(peer, digest)
        if str(plan.get("offerDigest") or "") != _canonical_hash(ticket):
            raise ValueError("Peer offer changed after cache fetch preview")
        executable = self._verified_sidecar_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".{digest}.{uuid.uuid4().hex}.iroh"
        request = {
            "operation": "fetch",
            "stateRoot": str(self._transport_state_root()),
            "storeRoot": str(self._transport_store_root()),
            "ticket": ticket,
            "objectHash": digest,
            "destination": str(temporary),
            "allowedPeers": [str(peer.get("endpointId") or "")],
            "maxBytes": int(plan.get("maxBytes") or 0),
        }
        started = time.perf_counter()
        try:
            result = self._run_sidecar(request)
            if not bool(result.get("ok")) or result.get("status") != "fetched":
                raise RuntimeError("The Iroh cache sidecar did not fetch the object")
            if not temporary.is_file() or self._hash_file(temporary) != digest:
                raise RuntimeError("Fetched cache object failed local integrity")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        stat = target.stat()
        self._record_object(
            digest=digest,
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            kind=str(plan.get("kind") or ""),
            pinned=bool(plan.get("pin")),
            workspace_path=f"remote:{plan.get('peerRef')}",
        )
        return self._fetch_receipt(
            plan,
            target,
            downloaded=True,
            duration_ms=round(
                (time.perf_counter() - started) * 1000.0,
                3,
            ),
        )

    def read_text(
        self,
        object_hash: str,
        *,
        offset: int = 0,
        length: int | None = None,
        encoding: str = "utf-8",
    ) -> dict[str, Any]:
        digest = self._validated_hash(object_hash)
        maximum = int(self.cache.get("maxTextReadBytes") or 65536)
        selected_length = maximum if length is None else int(length)
        if offset < 0 or selected_length < 1 or selected_length > maximum:
            raise ValueError(f"Read length must be between 1 and {maximum}")
        path = self._verified_object(digest)
        with path.open("rb") as handle:
            handle.seek(offset)
            payload = handle.read(selected_length)
        text = payload.decode(encoding, errors="replace")
        return {
            "schema": "neyvia.p2p-cache-text/v1",
            "objectHash": digest,
            "offset": offset,
            "bytesRead": len(payload),
            "text": text,
            "truncated": offset + len(payload) < path.stat().st_size,
            "source": "local-cas",
            "networkUsed": False,
        }

    def plan_garbage_collection(
        self,
        *,
        max_cache_bytes: int | None = None,
        max_objects: int | None = None,
    ) -> dict[str, Any]:
        """Plan bounded oldest-accessed eviction without deleting anything."""
        rows = self._object_rows()
        cache_policy = dict(self.cache.get("garbageCollection") or {})
        current_bytes = sum(int(row["size"]) for row in rows)
        current_objects = len(rows)
        byte_limit = self._non_negative_limit(
            max_cache_bytes,
            fallback=cache_policy.get("maxCacheBytes"),
            default=current_bytes,
            label="max_cache_bytes",
        )
        object_limit = self._non_negative_limit(
            max_objects,
            fallback=cache_policy.get("maxObjects"),
            default=current_objects,
            label="max_objects",
        )
        delete_limit, delete_byte_limit = self._current_gc_run_limits()
        authority_ready = self._gc_authority_ready()
        candidates = sorted(
            (row for row in rows if not bool(row["pinned"])),
            key=lambda row: (
                str(row["accessed_at"] or row["created_at"]),
                str(row["hash"]),
            ),
        )
        if (
            delete_limit == 0
            or delete_byte_limit == 0
            or not authority_ready
        ):
            candidates = []
        evictions: list[dict[str, Any]] = []
        reclaimed = 0
        projected_bytes = current_bytes
        projected_objects = current_objects
        for row in candidates:
            if projected_bytes <= byte_limit and projected_objects <= object_limit:
                break
            size = int(row["size"])
            if len(evictions) >= delete_limit:
                break
            if reclaimed + size > delete_byte_limit:
                break
            evictions.append(
                {
                    "objectHash": str(row["hash"]),
                    "bytes": size,
                    "mtimeNs": int(row["mtime_ns"]),
                    "lastAccessedAt": str(
                        row["accessed_at"] or row["created_at"]
                    ),
                    "reason": "quota",
                }
            )
            reclaimed += size
            projected_bytes -= size
            projected_objects -= 1
        plan = {
            "schema": GC_PLAN_SCHEMA,
            "planId": f"cachegc_{uuid.uuid4().hex[:20]}",
            "createdAt": utc_now(),
            "limits": {
                "maxCacheBytes": byte_limit,
                "maxObjects": object_limit,
                "maxDeletesPerRun": delete_limit,
                "maxDeleteBytesPerRun": delete_byte_limit,
            },
            "before": {
                "bytes": current_bytes,
                "objects": current_objects,
            },
            "evictions": evictions,
            "after": {
                "bytes": projected_bytes,
                "objects": projected_objects,
            },
            "summary": {
                "deleteCount": len(evictions),
                "deleteBytes": reclaimed,
                "pinnedProtected": sum(
                    1 for row in rows if bool(row["pinned"])
                ),
                "disabled": (
                    delete_limit == 0
                    or delete_byte_limit == 0
                    or not authority_ready
                ),
                "approvalAuthorityReady": authority_ready,
                "quotaSatisfied": (
                    projected_bytes <= byte_limit
                    and projected_objects <= object_limit
                ),
                "bounded": True,
                "networkUsed": False,
            },
        }
        plan["planHash"] = self._plan_hash(plan)
        return plan

    def apply_garbage_collection(
        self,
        plan: dict[str, Any],
        *,
        approval: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(approval, dict):
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "destructive",
            }
        self._validate_gc_plan(plan)
        approval_record = self._validate_gc_approval(approval, plan)
        digests = [
            str(candidate["objectHash"])
            for candidate in plan["evictions"]
        ]
        with self._object_mutation_locks(digests):
            return self._apply_validated_garbage_collection(
                plan,
                approval_record=approval_record,
            )

    def _apply_validated_garbage_collection(
        self,
        plan: dict[str, Any],
        *,
        approval_record: dict[str, Any],
    ) -> dict[str, Any]:
        self._recover_gc_transactions()
        self._enforce_current_gc_limits(plan)
        plan_id = str(plan["planId"])
        quarantine_dir = (
            self.object_root
            / ".gc-quarantine"
            / plan_id
        )
        quarantined: list[tuple[str, Path, Path, int]] = []
        journal = self._new_gc_journal(plan, approval_record)
        journal_path = (
            self.gc_journal_root
            / f"{journal['transactionId']}.json"
        )
        self._assert_safe_descendant(
            self.root,
            self.gc_journal_root,
            allow_missing_final=True,
        )
        self.gc_journal_root.mkdir(parents=True, exist_ok=True)
        self._assert_safe_descendant(
            self.root,
            self.gc_journal_root,
            require_final_directory=True,
        )
        self._assert_safe_descendant(
            self.root,
            journal_path,
            allow_missing_final=True,
        )
        database = self._connect(create=True)
        savepoint_started = False
        approval_leased = False
        approval_consumed = False
        try:
            self._lease_gc_approval(approval_record, plan)
            approval_leased = True
            database.execute("BEGIN IMMEDIATE")
            self._safe_write_gc_journal(journal_path, journal)
            database.execute("SAVEPOINT gc_mutation")
            savepoint_started = True
            self._assert_safe_descendant(
                self.object_root,
                quarantine_dir,
                allow_missing_final=True,
            )
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            self._assert_safe_descendant(
                self.object_root,
                quarantine_dir,
                require_final_directory=True,
            )
            for candidate in plan.get("evictions") or []:
                digest = self._validated_hash(
                    str(candidate.get("objectHash") or "")
                )
                row = database.execute(
                    "SELECT size, mtime_ns, pinned, accessed_at "
                    "FROM objects WHERE hash=?",
                    (digest,),
                ).fetchone()
                if row is None:
                    raise RuntimeError(
                        "Garbage collection object index changed"
                    )
                if bool(row["pinned"]):
                    raise RuntimeError(
                        "Garbage collection cannot remove pinned objects"
                    )
                if str(row["accessed_at"] or "") != str(
                    candidate.get("lastAccessedAt") or ""
                ):
                    raise RuntimeError(
                        "Garbage collection access state changed after preview"
                    )
                path = self._object_path(digest)
                self._assert_safe_regular_file(self.object_root, path)
                stat = path.stat()
                if (
                    stat.st_size != int(candidate["bytes"])
                    or stat.st_mtime_ns != int(candidate["mtimeNs"])
                    or int(row["size"]) != stat.st_size
                    or int(row["mtime_ns"]) != stat.st_mtime_ns
                    or self._hash_file(path) != digest
                ):
                    raise RuntimeError(
                        "Garbage collection object changed after preview"
                    )
                quarantine_path = quarantine_dir / digest
                self._assert_safe_descendant(
                    self.object_root,
                    quarantine_path,
                    allow_missing_final=True,
                )
                if os.path.lexists(quarantine_path):
                    raise RuntimeError(
                        "Garbage collection quarantine is not empty"
                    )
                os.replace(path, quarantine_path)
                self._assert_safe_regular_file(
                    self.object_root,
                    quarantine_path,
                )
                quarantined.append(
                    (digest, path, quarantine_path, stat.st_size)
                )
            for digest, _, _, size in quarantined:
                candidate = next(
                    item
                    for item in plan["evictions"]
                    if item["objectHash"] == digest
                )
                mutation = database.execute(
                    "DELETE FROM objects WHERE hash=? AND pinned=0 "
                    "AND size=? AND mtime_ns=? AND accessed_at=?",
                    (
                        digest,
                        size,
                        int(candidate["mtimeNs"]),
                        str(candidate["lastAccessedAt"]),
                    ),
                )
                if mutation.rowcount != 1:
                    raise RuntimeError(
                        "Garbage collection conditional index mutation failed"
                    )
            self._consume_gc_approval(
                approval=approval_record,
                approval_id=str(approval_record["approvalId"]),
            )
            approval_consumed = True
            database.execute("RELEASE SAVEPOINT gc_mutation")
            savepoint_started = False
            database.commit()
        except Exception:
            if not savepoint_started:
                database.rollback()
                if approval_leased and not approval_consumed:
                    self._consume_gc_approval(
                        approval=approval_record,
                        approval_id=str(approval_record["approvalId"]),
                    )
                raise
            try:
                database.execute("ROLLBACK TO SAVEPOINT gc_mutation")
                database.execute("RELEASE SAVEPOINT gc_mutation")
            except sqlite3.Error:
                database.rollback()
                raise
            restoration_error: OSError | None = None
            for _, original, quarantine_path, _ in reversed(quarantined):
                if not os.path.lexists(quarantine_path):
                    continue
                try:
                    self._assert_safe_regular_file(
                        self.object_root,
                        quarantine_path,
                    )
                    self._assert_safe_descendant(
                        self.object_root,
                        original,
                        allow_missing_final=True,
                    )
                    if os.path.lexists(original):
                        raise OSError(
                            "Cache object path was occupied during rollback"
                        )
                    os.replace(quarantine_path, original)
                    self._assert_safe_regular_file(
                        self.object_root,
                        original,
                    )
                except (OSError, RuntimeError) as exc:
                    restoration_error = restoration_error or exc
            journal["state"] = (
                "recovery_required"
                if restoration_error is not None
                else "aborted"
            )
            journal["finishedAt"] = utc_now()
            if not approval_consumed:
                self._consume_gc_approval(
                    approval=approval_record,
                    approval_id=str(approval_record["approvalId"]),
                )
                approval_consumed = True
            database.commit()
            self._safe_write_gc_journal(journal_path, journal)
            if restoration_error is not None:
                raise RuntimeError(
                    "Garbage collection rollback requires recovery"
                ) from restoration_error
            raise
        finally:
            database.close()

        journal["state"] = "database_committed"
        journal["committedAt"] = utc_now()
        self._safe_write_gc_journal(journal_path, journal)
        deleted: list[dict[str, Any]] = []
        retained_quarantine: list[dict[str, Any]] = []
        for digest, _, quarantine_path, size in quarantined:
            try:
                self._assert_safe_regular_file(
                    self.object_root,
                    quarantine_path,
                )
                quarantine_path.unlink()
            except (OSError, RuntimeError):
                retained_quarantine.append(
                    {
                        "objectHash": digest,
                        "bytes": size,
                    }
                )
            else:
                deleted.append(
                    {
                        "objectHash": digest,
                        "bytes": size,
                    }
                )
        try:
            quarantine_dir.rmdir()
            quarantine_dir.parent.rmdir()
        except OSError:
            pass
        journal["state"] = (
            "completed"
            if not retained_quarantine
            else "cleanup_pending"
        )
        journal["finishedAt"] = utc_now()
        journal["retainedQuarantine"] = [
            str(item["objectHash"]) for item in retained_quarantine
        ]
        self._safe_write_gc_journal(journal_path, journal)
        status = (
            "collected"
            if not retained_quarantine
            else "collected_pending_cleanup"
        )
        return {
            "schema": GC_RECEIPT_SCHEMA,
            "receiptId": f"cachegcreceipt_{uuid.uuid4().hex[:20]}",
            "createdAt": utc_now(),
            "planId": str(plan.get("planId") or ""),
            "planHash": str(plan.get("planHash") or ""),
            "approvalId": str(approval_record["approvalId"]),
            "approvalPrincipal": str(approval_record["principal"]),
            "approvalConsumed": True,
            "deleted": deleted,
            "quarantined": retained_quarantine,
            "summary": {
                "deletedCount": len(deleted),
                "deletedBytes": sum(
                    int(item["bytes"]) for item in deleted
                ),
                "removedFromCacheCount": len(quarantined),
                "retainedQuarantineCount": len(retained_quarantine),
                "networkUsed": False,
            },
            "ok": True,
            "status": status,
        }

    def stats(self) -> dict[str, Any]:
        rows = self._object_rows()
        return {
            "schema": "neyvia.p2p-cache-stats/v1",
            "summary": {
                "objects": len(rows),
                "bytes": sum(int(row["size"]) for row in rows),
                "pinned": sum(1 for row in rows if bool(row["pinned"])),
            },
            "objects": [
                {
                    "objectHash": row["hash"],
                    "bytes": row["size"],
                    "kind": row["kind"],
                    "pinned": bool(row["pinned"]),
                    "workspacePath": row["workspace_path"],
                    "createdAt": row["created_at"],
                    "lastAccessedAt": row["accessed_at"],
                }
                for row in rows[:100]
            ],
            "detailsBounded": True,
        }

    def _record_object(
        self,
        *,
        digest: str,
        size: int,
        mtime_ns: int,
        kind: str,
        pinned: bool,
        workspace_path: str,
        database: sqlite3.Connection | None = None,
    ) -> None:
        owns_connection = database is None
        selected = database or self._connect(create=True)
        try:
            selected.execute(
                "INSERT INTO objects "
                "(hash, size, mtime_ns, kind, pinned, workspace_path, "
                "created_at, accessed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(hash) DO UPDATE SET "
                "size=excluded.size, mtime_ns=excluded.mtime_ns, "
                "kind=excluded.kind, pinned=MAX(objects.pinned, excluded.pinned), "
                "workspace_path=excluded.workspace_path, "
                "accessed_at=excluded.accessed_at",
                (
                    digest,
                    size,
                    mtime_ns,
                    kind,
                    int(pinned),
                    workspace_path,
                    utc_now(),
                    utc_now(),
                ),
            )
            if owns_connection:
                selected.commit()
        finally:
            if owns_connection:
                selected.close()

    def _copy_source_to_descriptor(
        self,
        source: Path,
        *,
        descriptor: int,
        digest: str,
    ) -> None:
        hasher = blake3.blake3()
        with os.fdopen(descriptor, "wb") as output:
            with source.open("rb") as input_handle:
                while chunk := input_handle.read(
                    int(
                        self.cache.get("copyBufferBytes")
                        or 1024 * 1024
                    )
                ):
                    hasher.update(chunk)
                    output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if hasher.hexdigest() != digest:
            raise RuntimeError("Copied cache object failed integrity")

    @contextmanager
    def _object_mutation_locks(
        self,
        digests: list[str] | tuple[str, ...],
    ) -> Iterator[None]:
        normalized = sorted(
            {
                self._validated_hash(digest)
                for digest in digests
                if isinstance(digest, str) and digest
            }
        )
        selected: list[
            tuple[tuple[str, str], _ObjectMutationLockEntry]
        ] = []
        with _OBJECT_MUTATION_LOCKS_GUARD:
            for digest in normalized:
                key = (str(self.index_path), digest)
                entry = _OBJECT_MUTATION_LOCKS.get(key)
                if entry is None:
                    entry = _ObjectMutationLockEntry(
                        lock=threading.RLock(),
                    )
                    _OBJECT_MUTATION_LOCKS[key] = entry
                entry.references += 1
                selected.append((key, entry))
        try:
            with ExitStack() as stack:
                for _, entry in selected:
                    stack.enter_context(entry.lock)
                yield
        finally:
            with _OBJECT_MUTATION_LOCKS_GUARD:
                for key, entry in selected:
                    entry.references -= 1
                    if (
                        entry.references == 0
                        and _OBJECT_MUTATION_LOCKS.get(key) is entry
                    ):
                        _OBJECT_MUTATION_LOCKS.pop(key, None)

    def _connect(self, *, create: bool) -> sqlite3.Connection:
        if create:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
        database = sqlite3.connect(self.index_path, timeout=30.0)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA busy_timeout=30000")
        if create:
            initial_columns = {
                str(row["name"])
                for row in database.execute("PRAGMA table_info(objects)")
            }
            migration_required = "accessed_at" not in initial_columns
            if not migration_required:
                migration_required = (
                    database.execute(
                        "SELECT 1 FROM objects WHERE accessed_at IS NULL LIMIT 1"
                    ).fetchone()
                    is not None
                )
            if not migration_required:
                return database
            try:
                try:
                    database.execute("PRAGMA journal_mode=WAL")
                except sqlite3.OperationalError:
                    # Another first-use connection can already hold the
                    # migration lock. BEGIN IMMEDIATE below is the authority;
                    # journal mode is an optimization, not a safety fallback.
                    pass
                database.execute("BEGIN IMMEDIATE")
                database.execute(
                    "CREATE TABLE IF NOT EXISTS objects ("
                    "hash TEXT PRIMARY KEY, size INTEGER NOT NULL, "
                    "mtime_ns INTEGER NOT NULL, kind TEXT NOT NULL, "
                    "pinned INTEGER NOT NULL, workspace_path TEXT NOT NULL, "
                    "created_at TEXT NOT NULL, accessed_at TEXT)"
                )
                columns = {
                    str(row["name"])
                    for row in database.execute(
                        "PRAGMA table_info(objects)"
                    )
                }
                if "accessed_at" not in columns:
                    database.execute(
                        "ALTER TABLE objects ADD COLUMN accessed_at TEXT"
                    )
                database.execute(
                    "UPDATE objects SET accessed_at=created_at "
                    "WHERE accessed_at IS NULL"
                )
                database.commit()
            except Exception:
                database.rollback()
                database.close()
                raise
        return database

    @contextmanager
    def _database(self, *, create: bool) -> Iterator[sqlite3.Connection]:
        database = self._connect(create=create)
        try:
            with database:
                yield database
        finally:
            database.close()

    def _verified_object(self, digest: str) -> Path:
        path = self._object_path(digest)
        if not path.is_file():
            raise FileNotFoundError("Cache object is not available locally")
        with self._database(create=False) as database:
            row = database.execute(
                "SELECT size, mtime_ns FROM objects WHERE hash=?",
                (digest,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Cache object is missing index provenance")
        stat = path.stat()
        if (
            stat.st_size != int(row["size"])
            or stat.st_mtime_ns != int(row["mtime_ns"])
        ):
            if self._hash_file(path) != digest:
                raise RuntimeError("Cache object integrity changed")
            with self._database(create=True) as database:
                database.execute(
                    "UPDATE objects SET size=?, mtime_ns=? WHERE hash=?",
                    (stat.st_size, stat.st_mtime_ns, digest),
                )
                database.commit()
        with self._database(create=True) as database:
            database.execute(
                "UPDATE objects SET accessed_at=? WHERE hash=?",
                (utc_now(), digest),
            )
            database.commit()
        return path

    def _workspace_file(self, value: str | Path) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self.root / path
        path = path.resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Cache imports must stay inside the workspace") from exc
        if not path.is_file():
            raise ValueError("Cache source does not exist")
        return path

    @staticmethod
    def _absolute_lexical_path(value: str | Path) -> Path:
        return Path(os.path.abspath(os.fspath(value)))

    @staticmethod
    def _path_is_reparse(path: Path) -> bool:
        metadata = os.lstat(path)
        return stat.S_ISLNK(metadata.st_mode) or bool(
            getattr(metadata, "st_file_attributes", 0)
            & _REPARSE_POINT_ATTRIBUTE
        )

    def _assert_safe_descendant(
        self,
        anchor: Path,
        path: Path,
        *,
        allow_missing_final: bool = False,
        require_final_directory: bool = False,
    ) -> Path:
        """Reject lexical escapes and every existing symlink/reparse ancestor."""
        selected_anchor = self._absolute_lexical_path(anchor)
        selected = self._absolute_lexical_path(path)
        try:
            selected.relative_to(selected_anchor)
        except ValueError as exc:
            raise RuntimeError("Protected path escapes its configured root") from exc

        chain: list[Path] = []
        current = selected
        while True:
            chain.append(current)
            if current.parent == current:
                break
            current = current.parent
        for component in reversed(chain):
            exists = os.path.lexists(component)
            if not exists:
                continue
            if self._path_is_reparse(component):
                raise RuntimeError(
                    "Protected path contains a symlink or reparse point"
                )
            metadata = os.lstat(component)
            is_final = component == selected
            if not is_final and not stat.S_ISDIR(metadata.st_mode):
                raise RuntimeError(
                    "Protected path ancestor is not a directory"
                )
            if (
                is_final
                and require_final_directory
                and not stat.S_ISDIR(metadata.st_mode)
            ):
                raise RuntimeError("Protected path is not a directory")
        if (
            not allow_missing_final
            and not os.path.lexists(selected)
        ):
            raise RuntimeError("Protected path does not exist")
        return selected

    def _assert_safe_regular_file(
        self,
        anchor: Path,
        path: Path,
    ) -> Path:
        selected = self._assert_safe_descendant(anchor, path)
        metadata = os.lstat(selected)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("Protected path is not a regular file")
        return selected

    def _object_path(self, digest: str) -> Path:
        value = self._validated_hash(digest)
        return self.object_root / "blake3" / value[:2] / value

    def _object_rows(self) -> list[sqlite3.Row]:
        if not self.index_path.is_file():
            return []
        with self._database(create=True) as database:
            return list(
                database.execute(
                    "SELECT hash, size, mtime_ns, kind, pinned, "
                    "workspace_path, created_at, accessed_at "
                    "FROM objects ORDER BY created_at DESC, hash"
                )
            )

    @staticmethod
    def _non_negative_limit(
        value: int | None,
        *,
        fallback: object,
        default: int,
        label: str,
    ) -> int:
        selected = value if value is not None else fallback
        if selected is None:
            selected = default
        if isinstance(selected, bool) or not isinstance(selected, int):
            raise ValueError(f"{label} must be a non-negative integer")
        normalized = selected
        if normalized < 0:
            raise ValueError(f"{label} must be a non-negative integer")
        return normalized

    def _current_gc_run_limits(self) -> tuple[int, int]:
        cache_policy = dict(self.cache.get("garbageCollection") or {})
        configured_deletes = self._strict_gc_limit(
            cache_policy.get("maxDeletesPerRun"),
            default=128,
            maximum=_MAX_GC_DELETES,
            label="maxDeletesPerRun",
        )
        configured_bytes = self._strict_gc_limit(
            cache_policy.get("maxDeleteBytesPerRun"),
            default=_MAX_GC_DELETE_BYTES,
            maximum=_MAX_GC_DELETE_BYTES,
            label="maxDeleteBytesPerRun",
        )
        return configured_deletes, configured_bytes

    @staticmethod
    def _strict_gc_limit(
        value: object,
        *,
        default: int,
        maximum: int,
        label: str,
    ) -> int:
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{label} must be a non-negative integer")
        if value < 0:
            raise ValueError(f"{label} must be a non-negative integer")
        return min(value, maximum)

    def _enforce_current_gc_limits(self, plan: dict[str, Any]) -> None:
        delete_limit, byte_limit = self._current_gc_run_limits()
        evictions = list(plan.get("evictions") or [])
        total_bytes = sum(int(item["bytes"]) for item in evictions)
        declared = dict(plan.get("limits") or {})
        if (
            (bool(evictions) and (delete_limit == 0 or byte_limit == 0))
            or len(evictions) > delete_limit
            or total_bytes > byte_limit
            or int(declared.get("maxDeletesPerRun") or 0) > delete_limit
            or int(declared.get("maxDeleteBytesPerRun") or 0) > byte_limit
        ):
            raise PermissionError(
                "Garbage collection plan exceeds current configured limits"
            )

    @staticmethod
    def _valid_prefixed_id(value: str, prefix: str) -> bool:
        suffix = value.removeprefix(prefix)
        return (
            value.startswith(prefix)
            and len(suffix) == 20
            and all(
                character in "0123456789abcdef"
                for character in suffix
            )
        )

    @staticmethod
    def _parse_utc_timestamp(value: object, *, label: str) -> datetime:
        raw = str(value or "").strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise PermissionError(f"Invalid approval {label}") from exc
        if parsed.tzinfo is None:
            raise PermissionError(f"Invalid approval {label}")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _gc_approval_scope(plan: dict[str, Any]) -> dict[str, str]:
        return {
            "permission": "destructive",
            "action": "p2p-cache.garbage-collection",
            "planId": str(plan.get("planId") or ""),
            "planHash": str(plan.get("planHash") or ""),
        }

    def _validate_gc_approval(
        self,
        approval: dict[str, Any],
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        authority = self._gc_authority()
        issuer = str(authority["issuer"])
        key_id = str(authority["keyId"])
        raw_ttl = int(authority["maxTtlSeconds"])
        approval_id = str(approval.get("approvalId") or "")
        principal = str(approval.get("principal") or "").strip()
        scope = self._gc_approval_scope(plan)
        scope_hash = _canonical_hash(scope)
        if (
            approval.get("schema") != GC_APPROVAL_SCHEMA
            or not self._valid_prefixed_id(approval_id, "gcauth_")
            or str(approval.get("issuer") or "") != issuer
            or str(approval.get("algorithm") or "") != _GC_APPROVAL_ALGORITHM
            or str(approval.get("keyId") or "") != key_id
            or str(approval.get("permission") or "") != scope["permission"]
            or str(approval.get("action") or "") != scope["action"]
            or str(approval.get("planId") or "") != scope["planId"]
            or str(approval.get("planHash") or "") != scope["planHash"]
            or str(approval.get("scopeHash") or "") != scope_hash
            or not principal
            or len(principal) > 80
            or not principal.isprintable()
        ):
            raise PermissionError(
                "Garbage collection approval scope is invalid"
            )
        issued_at = self._parse_utc_timestamp(
            approval.get("issuedAt"),
            label="issuedAt",
        )
        expires_at = self._parse_utc_timestamp(
            approval.get("expiresAt"),
            label="expiresAt",
        )
        now = datetime.now(timezone.utc)
        if (
            issued_at > now + timedelta(seconds=30)
            or expires_at <= now
            or expires_at <= issued_at
            or expires_at - issued_at > timedelta(seconds=raw_ttl)
        ):
            raise PermissionError(
                "Garbage collection approval is expired or invalid"
            )
        signed = copy.deepcopy(approval)
        encoded_signature = str(signed.pop("signature", "")).strip()
        try:
            signature = base64.b64decode(
                encoded_signature,
                validate=True,
            )
            authority["publicKey"].verify(
                signature,
                _canonical_bytes(signed),
            )
        except (ValueError, InvalidSignature):
            raise PermissionError(
                "Garbage collection approval signature is invalid"
            ) from None
        return {
            "approvalId": approval_id,
            "principal": principal,
            "expiresAt": expires_at.isoformat().replace("+00:00", "Z"),
            "receiptHash": _canonical_hash(approval),
            "authority": authority,
        }

    def _gc_authority_ready(self) -> bool:
        try:
            self._gc_authority()
        except PermissionError:
            return False
        return True

    def _gc_authority(self) -> dict[str, Any]:
        raw = dict(
            self.policy.get("garbageCollectionApproval") or {}
        )
        issuer = str(raw.get("issuer") or "").strip()
        algorithm = str(raw.get("algorithm") or "").strip()
        key_id = str(raw.get("keyId") or "").strip()
        protected_raw = str(raw.get("protectedRoot") or "").strip()
        public_key_raw = str(raw.get("publicKeyPath") or "").strip()
        ledger_raw = str(raw.get("ledgerPath") or "").strip()
        raw_ttl = raw.get("maxTtlSeconds", 300)
        unavailable = (
            not issuer
            or algorithm != _GC_APPROVAL_ALGORITHM
            or not key_id
            or not protected_raw
            or not public_key_raw
            or not ledger_raw
            or isinstance(raw_ttl, bool)
            or not isinstance(raw_ttl, int)
            or raw_ttl < 1
            or raw_ttl > 3600
        )
        if unavailable:
            raise PermissionError(
                "Garbage collection approval authority is unavailable"
            )
        protected_root = Path(protected_raw)
        public_key_path = Path(public_key_raw)
        ledger_path = Path(ledger_raw)
        if (
            not protected_root.is_absolute()
            or not public_key_path.is_absolute()
            or not ledger_path.is_absolute()
        ):
            raise PermissionError(
                "Garbage collection approval authority is unavailable"
            )
        protected_root = self._absolute_lexical_path(protected_root)
        public_key_path = self._absolute_lexical_path(public_key_path)
        ledger_path = self._absolute_lexical_path(ledger_path)
        if (
            self._path_within(protected_root, self.root)
            or self._path_within(self.root, protected_root)
            or self._path_within(protected_root, self.object_root)
            or self._path_within(self.object_root, protected_root)
            or not self._path_within(public_key_path, protected_root)
            or not self._path_within(ledger_path, protected_root)
            or public_key_path == ledger_path
        ):
            raise PermissionError(
                "Garbage collection approval authority is unavailable"
            )
        try:
            self._assert_safe_descendant(
                protected_root,
                protected_root,
                require_final_directory=True,
            )
            self._assert_safe_regular_file(
                protected_root,
                public_key_path,
            )
            self._assert_safe_descendant(
                protected_root,
                ledger_path.parent,
                require_final_directory=True,
            )
            if os.path.lexists(ledger_path):
                self._assert_safe_regular_file(
                    protected_root,
                    ledger_path,
                )
            encoded_key = public_key_path.read_bytes()
            loaded_key = serialization.load_pem_public_key(encoded_key)
        except (OSError, RuntimeError, ValueError, TypeError):
            raise PermissionError(
                "Garbage collection approval authority is unavailable"
            ) from None
        if not isinstance(loaded_key, Ed25519PublicKey):
            raise PermissionError(
                "Garbage collection approval authority is unavailable"
            )
        return {
            "issuer": issuer,
            "algorithm": algorithm,
            "keyId": key_id,
            "maxTtlSeconds": raw_ttl,
            "protectedRoot": protected_root,
            "publicKeyPath": public_key_path,
            "ledgerPath": ledger_path,
            "publicKey": loaded_key,
        }

    @staticmethod
    def _path_within(path: Path, anchor: Path) -> bool:
        try:
            path.relative_to(anchor)
        except ValueError:
            return False
        return True

    def _connect_gc_ledger(
        self,
        authority: dict[str, Any],
    ) -> sqlite3.Connection:
        protected_root = Path(authority["protectedRoot"])
        ledger_path = Path(authority["ledgerPath"])
        self._assert_safe_descendant(
            protected_root,
            ledger_path.parent,
            require_final_directory=True,
        )
        if os.path.lexists(ledger_path):
            self._assert_safe_regular_file(protected_root, ledger_path)
        database = sqlite3.connect(ledger_path, timeout=30.0)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA busy_timeout=30000")
        try:
            database.execute("BEGIN IMMEDIATE")
            database.execute(
                "CREATE TABLE IF NOT EXISTS gc_approvals ("
                "approval_id TEXT PRIMARY KEY, "
                "receipt_hash TEXT NOT NULL, "
                "plan_id TEXT NOT NULL, plan_hash TEXT NOT NULL, "
                "principal TEXT NOT NULL, expires_at TEXT NOT NULL, "
                "state TEXT NOT NULL, leased_at TEXT NOT NULL, "
                "consumed_at TEXT)"
            )
            database.commit()
        except Exception:
            database.rollback()
            database.close()
            raise
        self._assert_safe_regular_file(protected_root, ledger_path)
        return database

    def _lease_gc_approval(
        self,
        approval: dict[str, Any],
        plan: dict[str, Any],
    ) -> None:
        database = self._connect_gc_ledger(approval["authority"])
        try:
            database.execute("BEGIN IMMEDIATE")
            database.execute(
                "INSERT INTO gc_approvals "
                "(approval_id, receipt_hash, plan_id, plan_hash, principal, "
                "expires_at, state, leased_at, consumed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'leased', ?, NULL)",
                (
                    str(approval["approvalId"]),
                    str(approval["receiptHash"]),
                    str(plan["planId"]),
                    str(plan["planHash"]),
                    str(approval["principal"]),
                    str(approval["expiresAt"]),
                    utc_now(),
                ),
            )
            database.commit()
        except sqlite3.IntegrityError:
            database.rollback()
            raise PermissionError(
                "Garbage collection approval was already used"
            ) from None
        finally:
            database.close()

    def _consume_gc_approval(
        self,
        *,
        approval: dict[str, Any],
        approval_id: str,
    ) -> None:
        database = self._connect_gc_ledger(approval["authority"])
        try:
            database.execute("BEGIN IMMEDIATE")
            mutation = database.execute(
                "UPDATE gc_approvals SET state='consumed', consumed_at=? "
                "WHERE approval_id=? AND state='leased'",
                (utc_now(), approval_id),
            )
            if mutation.rowcount != 1:
                database.rollback()
                raise PermissionError(
                    "Garbage collection approval lease changed"
                )
            database.commit()
        finally:
            database.close()

    def _consume_gc_approval_from_journal(
        self,
        journal: dict[str, Any],
    ) -> None:
        authority = self._gc_authority()
        approval_id = str(journal.get("approvalId") or "")
        if not self._valid_prefixed_id(approval_id, "gcauth_"):
            raise PermissionError("Garbage collection recovery approval is invalid")
        database = self._connect_gc_ledger(authority)
        try:
            database.execute("BEGIN IMMEDIATE")
            mutation = database.execute(
                "UPDATE gc_approvals SET state='consumed', consumed_at=? "
                "WHERE approval_id=? AND receipt_hash=? AND plan_id=? "
                "AND plan_hash=? AND state IN ('leased', 'consumed')",
                (
                    utc_now(),
                    approval_id,
                    str(journal.get("approvalReceiptHash") or ""),
                    str(journal.get("planId") or ""),
                    str(journal.get("planHash") or ""),
                ),
            )
            if mutation.rowcount != 1:
                database.rollback()
                raise PermissionError(
                    "Garbage collection recovery approval lease is unavailable"
                )
            database.commit()
        finally:
            database.close()

    def _new_gc_journal(
        self,
        plan: dict[str, Any],
        approval: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema": GC_TRANSACTION_SCHEMA,
            "transactionId": f"gctxn_{uuid.uuid4().hex[:20]}",
            "planId": str(plan["planId"]),
            "planHash": str(plan["planHash"]),
            "approvalId": str(approval["approvalId"]),
            "approvalReceiptHash": str(approval["receiptHash"]),
            "approvalPrincipal": str(approval["principal"]),
            "approvalExpiresAt": str(approval["expiresAt"]),
            "state": "in_progress",
            "startedAt": utc_now(),
            "ownerPid": os.getpid(),
            "leaseExpiresAt": (
                datetime.now(timezone.utc) + timedelta(minutes=5)
            ).isoformat().replace("+00:00", "Z"),
            "objects": [
                {
                    "objectHash": str(item["objectHash"]),
                    "bytes": int(item["bytes"]),
                }
                for item in plan.get("evictions") or []
            ],
        }

    def _safe_write_gc_journal(
        self,
        journal_path: Path,
        journal: dict[str, Any],
    ) -> None:
        self._assert_safe_descendant(
            self.root,
            journal_path.parent,
            require_final_directory=True,
        )
        if os.path.lexists(journal_path):
            self._assert_safe_regular_file(self.root, journal_path)
        else:
            self._assert_safe_descendant(
                self.root,
                journal_path,
                allow_missing_final=True,
            )
        atomic_write_json(journal_path, journal)
        self._assert_safe_regular_file(self.root, journal_path)

    def _recover_gc_transactions(self) -> None:
        if not os.path.lexists(self.gc_journal_root):
            return
        self._assert_safe_descendant(
            self.root,
            self.gc_journal_root,
            require_final_directory=True,
        )
        for journal_path in sorted(self.gc_journal_root.glob("gctxn_*.json")):
            try:
                self._assert_safe_regular_file(self.root, journal_path)
                journal = json.loads(
                    journal_path.read_text(encoding="utf-8")
                )
            except (
                OSError,
                RuntimeError,
                UnicodeDecodeError,
                json.JSONDecodeError,
            ):
                continue
            if not isinstance(journal, dict):
                continue
            state = str(journal.get("state") or "")
            if state in {
                "completed",
                "aborted",
                "recovered_precommit",
                "recovered_postcommit",
                "recovered_mixed",
            }:
                continue
            if state == "in_progress":
                try:
                    lease_expires = self._parse_utc_timestamp(
                        journal.get("leaseExpiresAt"),
                        label="leaseExpiresAt",
                    )
                except PermissionError:
                    continue
                owner_pid = journal.get("ownerPid")
                owner_alive = (
                    isinstance(owner_pid, int)
                    and self._process_is_alive(owner_pid)
                )
                if (
                    owner_alive
                    and lease_expires > datetime.now(timezone.utc)
                ):
                    continue
            plan_id = str(journal.get("planId") or "")
            transaction_id = str(journal.get("transactionId") or "")
            if (
                journal.get("schema") != GC_TRANSACTION_SCHEMA
                or not self._valid_prefixed_id(plan_id, "cachegc_")
                or not self._valid_prefixed_id(transaction_id, "gctxn_")
                or journal_path.name != f"{transaction_id}.json"
            ):
                continue
            raw_objects = journal.get("objects")
            if not isinstance(raw_objects, list) or len(raw_objects) > _MAX_GC_DELETES:
                continue
            try:
                digests = [
                    self._validated_hash(str(item.get("objectHash") or ""))
                    for item in raw_objects
                    if isinstance(item, dict)
                ]
            except ValueError:
                continue
            if len(digests) != len(raw_objects) or len(set(digests)) != len(digests):
                continue
            database = self._connect(create=True)
            recovered_precommit = False
            recovered_postcommit = False
            blocked = False
            try:
                database.execute("BEGIN IMMEDIATE")
                for digest in digests:
                    row = database.execute(
                        "SELECT 1 FROM objects WHERE hash=?",
                        (digest,),
                    ).fetchone()
                    original = self._object_path(digest)
                    quarantine = (
                        self.object_root
                        / ".gc-quarantine"
                        / plan_id
                        / digest
                    )
                    self._assert_safe_descendant(
                        self.object_root,
                        original,
                        allow_missing_final=True,
                    )
                    self._assert_safe_descendant(
                        self.object_root,
                        quarantine,
                        allow_missing_final=True,
                    )
                    quarantine_exists = os.path.lexists(quarantine)
                    original_exists = os.path.lexists(original)
                    if quarantine_exists:
                        self._assert_safe_regular_file(
                            self.object_root,
                            quarantine,
                        )
                    if original_exists:
                        self._assert_safe_regular_file(
                            self.object_root,
                            original,
                        )
                    if row is not None:
                        recovered_precommit = True
                        if quarantine_exists and not original_exists:
                            if self._hash_file(quarantine) != digest:
                                blocked = True
                            else:
                                os.replace(quarantine, original)
                                self._assert_safe_regular_file(
                                    self.object_root,
                                    original,
                                )
                        elif quarantine_exists and original_exists:
                            if (
                                self._hash_file(quarantine) == digest
                                and self._hash_file(original) == digest
                            ):
                                quarantine.unlink()
                            else:
                                blocked = True
                    else:
                        recovered_postcommit = True
                        if quarantine_exists:
                            if self._hash_file(quarantine) != digest:
                                blocked = True
                            else:
                                quarantine.unlink()
                self._consume_gc_approval_from_journal(journal)
                database.commit()
            except (
                OSError,
                PermissionError,
                sqlite3.Error,
                RuntimeError,
            ):
                database.rollback()
                blocked = True
            finally:
                database.close()
            if blocked:
                journal["state"] = "recovery_blocked"
            elif recovered_precommit and recovered_postcommit:
                journal["state"] = "recovered_mixed"
            elif recovered_precommit:
                journal["state"] = "recovered_precommit"
            else:
                journal["state"] = "recovered_postcommit"
            journal["recoveredAt"] = utc_now()
            self._safe_write_gc_journal(journal_path, journal)

    @staticmethod
    def _process_is_alive(process_id: int) -> bool:
        if process_id < 1:
            return False
        if os.name == "nt":
            try:
                import ctypes

                process_query_limited_information = 0x1000
                handle = ctypes.windll.kernel32.OpenProcess(
                    process_query_limited_information,
                    False,
                    process_id,
                )
                if not handle:
                    return False
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            except (AttributeError, OSError):
                return False
        try:
            os.kill(process_id, 0)
        except (OSError, ValueError):
            return False
        return True

    def _sidecar_path(self) -> Path:
        value = str(self.transport.get("executable") or "").strip()
        if not value:
            return Path()
        return Path(value).expanduser().resolve()

    @staticmethod
    def _is_sha256(value: str) -> bool:
        return len(value) == 64 and all(
            character in "0123456789abcdef" for character in value
        )

    def _sidecar_integrity(self) -> dict[str, Any]:
        """Return non-sensitive sidecar readiness facts without trusting state.

        ``sidecarState`` is deployment metadata, not integrity evidence.  The
        binary is available only when a configured executable exists and its
        current SHA-256 matches the configured pin.
        """
        raw_path = str(self.transport.get("executable") or "").strip()
        expected = str(self.transport.get("executableSha256") or "").strip().casefold()
        configured = bool(raw_path) and self._is_sha256(expected)
        executable = self._sidecar_path()
        executable_present = bool(raw_path) and executable.is_file()
        hash_match = False
        observed = ""
        if executable_present and self._is_sha256(expected):
            try:
                with executable.open("rb") as handle:
                    observed = hashlib.file_digest(handle, "sha256").hexdigest()
                hash_match = observed == expected
            except OSError:
                # A race, permissions change, or transient I/O failure means
                # the executable is not safe to run.
                hash_match = False
        return {
            "configured": configured,
            "executablePresent": executable_present,
            "hashMatch": hash_match,
            "available": configured and executable_present and hash_match,
            "observedSha256": observed,
        }

    def _transport_schedule_binding(self) -> dict[str, Any]:
        integrity = self._sidecar_integrity()
        executable = str(self.transport.get("executable") or "").strip()
        return {
            "transportName": str(self.transport.get("name") or ""),
            "transportVersion": str(self.transport.get("version") or ""),
            "sidecarVersion": str(
                self.transport.get("sidecarVersion") or ""
            ),
            "executablePathHash": _canonical_hash(executable),
            "executableSha256Pin": str(
                self.transport.get("executableSha256") or ""
            ).strip().casefold(),
            "executableSha256Observed": str(
                integrity.get("observedSha256") or ""
            ),
            "sidecarAvailable": bool(integrity["available"]),
            "persistentSession": bool(
                self.transport.get("persistentSession", True)
            ),
            "relayPolicy": str(
                self.transport.get("relayPolicy") or ""
            ),
            "stateRootHash": _canonical_hash(
                str(self.transport.get("stateRoot") or "")
            ),
            "storeRootHash": _canonical_hash(
                str(self.transport.get("storeRoot") or "")
            ),
            "commandTimeoutSeconds": int(
                self.transport.get("commandTimeoutSeconds") or 120
            ),
            "approvedPeerRequired": bool(
                self.policy.get("remoteFetchRequiresApprovedPeer", True)
            ),
            "publicDiscovery": bool(
                self.policy.get("publicDiscoveryDefault", False)
            ),
            "publicRelay": bool(
                self.policy.get("publicRelayDefault", False)
            ),
            "encryptedTransportRequired": bool(
                self.policy.get("encryptedTransportRequired", True)
            ),
            "maxImportBytes": int(
                self.cache.get("maxImportBytes")
                or 20 * 1024 * 1024 * 1024
            ),
        }

    def _verified_sidecar_path(self) -> Path:
        integrity = self._sidecar_integrity()
        if not integrity["available"]:
            raise RuntimeError("The verified Iroh cache sidecar is unavailable")
        return self._sidecar_path()

    def _transport_state_root(self) -> Path:
        return _deployment_storage_path(
            self.root,
            self.transport.get("stateRoot"),
            ".agent_control/p2p_cache/transport-state",
        )

    def _transport_store_root(self) -> Path:
        return _deployment_storage_path(
            self.root,
            self.transport.get("storeRoot"),
            ".agent_control/p2p_cache/transport-store",
        )

    def _peer(self, peer_ref: str) -> dict[str, Any]:
        normalized = str(peer_ref or "").strip()
        if not normalized:
            raise ValueError("peerRef is required")
        for candidate in self.policy.get("peers") or []:
            peer = dict(candidate or {})
            if (
                str(peer.get("peerRef") or "") == normalized
                and bool(peer.get("enabled", True))
            ):
                endpoint = str(peer.get("endpointId") or "").strip()
                if len(endpoint) < 32 or len(endpoint) > 128:
                    raise ValueError("Approved peer has an invalid endpoint identity")
                return peer
        raise ValueError("Unknown or disabled cache peer")

    @staticmethod
    def _peer_health(peer: dict[str, Any]) -> dict[str, Any]:
        observation = dict(peer.get("health") or {})
        status = str(
            observation.get("status")
            or peer.get("healthStatus")
            or "unknown"
        ).strip().casefold()
        if status not in {
            "healthy",
            "degraded",
            "unknown",
            "offline",
            "unhealthy",
            "unreachable",
            "disabled",
        }:
            status = "unknown"
        raw_latency = observation.get("latencyMs", peer.get("latencyMs"))
        try:
            latency = float(raw_latency)
        except (TypeError, ValueError):
            latency = 60_000.0
        if latency < 0:
            latency = 60_000.0
        latency = min(latency, 60_000.0)
        raw_failures = observation.get(
            "consecutiveFailures",
            peer.get("consecutiveFailures", 0),
        )
        try:
            failures = int(raw_failures)
        except (TypeError, ValueError):
            failures = 0
        return {
            "status": status,
            "latencyMs": round(latency, 3),
            "consecutiveFailures": max(0, min(failures, 1_000)),
        }

    @staticmethod
    def _peer_score(health: dict[str, Any]) -> int:
        health_rank = {
            "healthy": 0,
            "degraded": 1,
            "unknown": 2,
            "unhealthy": 3,
            "offline": 4,
            "unreachable": 4,
            "disabled": 5,
        }
        return (
            health_rank.get(str(health["status"]), 2) * 10_000_000
            + int(float(health["latencyMs"]) * 100)
            + int(health["consecutiveFailures"]) * 10_000
        )

    @staticmethod
    def _positive_bounded_policy_int(
        value: object,
        *,
        default: int,
        maximum: int,
        label: str,
    ) -> int:
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{label} must be an integer")
        if value < 1:
            raise ValueError(f"{label} must be at least 1")
        return min(value, maximum)

    def _scheduling_policy_snapshot(self) -> dict[str, Any]:
        return {
            "schema": "neyvia.p2p-cache-scheduling-policy/v1",
            "maxFetchAttempts": self._positive_bounded_policy_int(
                self.policy.get("maxFetchAttempts"),
                default=3,
                maximum=_MAX_FETCH_ATTEMPTS,
                label="maxFetchAttempts",
            ),
            "maxScheduleCandidates": self._positive_bounded_policy_int(
                self.policy.get("maxScheduleCandidates"),
                default=_MAX_SCHEDULE_CANDIDATES,
                maximum=_MAX_SCHEDULE_CANDIDATES,
                label="maxScheduleCandidates",
            ),
            "allowedKinds": sorted(
                {
                    str(item).strip().casefold()
                    for item in self.policy.get("allowedKinds") or []
                    if str(item).strip()
                }
            ),
            "healthEligibility": {
                "ineligibleStates": sorted(_UNAVAILABLE_PEER_HEALTH),
                "unknownEligible": True,
            },
            "scoring": {
                "version": 1,
                "healthyRank": 0,
                "degradedRank": 1,
                "unknownRank": 2,
                "healthRankWeight": 10_000_000,
                "latencyWeight": 100,
                "failureWeight": 10_000,
                "latencyClampMs": 60_000,
                "failureClamp": 1_000,
                "tieBreaker": "peerRef",
            },
        }

    def _validate_scheduled_candidate(
        self,
        candidate: dict[str, Any],
        *,
        digest: str,
    ) -> dict[str, Any]:
        peer = self._peer(str(candidate.get("peerRef") or ""))
        endpoint = str(peer.get("endpointId") or "").strip()
        if (
            str(candidate.get("peerIdentityHash") or "")
            != _canonical_hash(endpoint)
        ):
            raise ValueError(
                "Peer endpoint identity changed after cache schedule preview"
            )
        ticket = self._peer_offer(peer, digest)
        if str(candidate.get("offerDigest") or "") != _canonical_hash(ticket):
            raise ValueError("Peer offer changed after cache schedule preview")
        health = self._peer_health(peer)
        if health["status"] in _UNAVAILABLE_PEER_HEALTH:
            raise ValueError(
                "Peer health changed after cache schedule preview"
            )
        if (
            str(candidate.get("healthHash") or "")
            != _canonical_hash(health)
            or int(candidate.get("score", -1)) != self._peer_score(health)
        ):
            raise ValueError(
                "Peer health or score changed after cache schedule preview"
            )
        return peer

    def _deterministic_attempt_order(
        self,
        digest: str,
        *,
        candidates: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        selected = candidates or self.approved_peer_candidates(digest)
        max_attempts = self._positive_bounded_policy_int(
            self.policy.get("maxFetchAttempts"),
            default=3,
            maximum=_MAX_FETCH_ATTEMPTS,
            label="maxFetchAttempts",
        )
        return [
            {
                "peerRef": str(candidate["peerRef"]),
                "peerIdentityHash": str(candidate["peerIdentityHash"]),
                "offerDigest": str(candidate["offerDigest"]),
                "healthHash": str(candidate["healthHash"]),
                "score": int(candidate["score"]),
            }
            for candidate in selected["candidates"]
            if bool(candidate["eligible"])
        ][:max_attempts]

    def _assert_scheduled_attempt_order_current(
        self,
        plan: dict[str, Any],
        *,
        digest: str,
    ) -> None:
        expected = self._deterministic_attempt_order(digest)
        if plan.get("attemptOrder") != expected:
            raise ValueError(
                "Scheduled cache fetch attempt order or health changed"
            )

    def _approved_peers_for_replication(self) -> list[dict[str, Any]]:
        peers: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_peer in self.policy.get("peers") or []:
            peer = dict(raw_peer or {})
            peer_ref = str(peer.get("peerRef") or "").strip()
            endpoint = str(peer.get("endpointId") or "").strip()
            if (
                not peer_ref
                or peer_ref in seen
                or not bool(peer.get("enabled", True))
                or len(endpoint) < 32
                or len(endpoint) > 128
            ):
                continue
            seen.add(peer_ref)
            health = self._peer_health(peer)
            if health["status"] in _UNAVAILABLE_PEER_HEALTH:
                continue
            peers.append(
                {
                    "peerRef": peer_ref,
                    "score": self._peer_score(health),
                }
            )
        peers.sort(key=lambda peer: (int(peer["score"]), str(peer["peerRef"])))
        return peers

    @staticmethod
    def _peer_offer(peer: dict[str, Any], digest: str) -> str:
        offers = dict(peer.get("offers") or {})
        ticket = str(offers.get(digest) or "").strip()
        if not ticket or len(ticket) > 8192:
            raise ValueError("Approved peer has no bounded offer for this object")
        return ticket

    def _run_sidecar(self, request: dict[str, Any]) -> dict[str, Any]:
        timeout = int(self.transport.get("commandTimeoutSeconds") or 120)
        environment = self._minimal_environment()
        executable = self._verified_sidecar_path()
        if (
            request.get("operation") == "fetch"
            and bool(self.transport.get("persistentSession", True))
        ):
            allowed_peers = tuple(
                sorted(str(item) for item in request.get("allowedPeers") or [])
            )
            key = (
                str(executable),
                str(self.transport.get("executableSha256") or ""),
                str(self._transport_state_root()),
                str(self._transport_store_root()),
                allowed_peers,
                str(self.root),
            )
            with _IROH_SESSIONS_LOCK:
                stale_keys = [
                    candidate
                    for candidate in _IROH_SESSIONS
                    if candidate != key
                    and candidate[0] == key[0]
                    and candidate[2] == key[2]
                    and candidate[3] == key[3]
                    and candidate[5] == key[5]
                ]
                for stale_key in stale_keys:
                    _IROH_SESSIONS.pop(stale_key).close()
                session = _IROH_SESSIONS.get(key)
                if (
                    session is None
                    or session.process.poll() is not None
                    or session.broken
                ):
                    if session is not None:
                        session.close()
                    session = _IrohSession(
                        executable=executable,
                        expected_sha256=str(
                            self.transport.get("executableSha256") or ""
                        ),
                        state_root=self._transport_state_root(),
                        store_root=self._transport_store_root(),
                        allowed_peers=allowed_peers,
                        working_directory=self.root,
                        timeout=timeout,
                        environment=environment,
                    )
                    _IROH_SESSIONS[key] = session
            session_request = {
                key: value
                for key, value in request.items()
                if key
                not in {
                    "stateRoot",
                    "storeRoot",
                    "allowedPeers",
                }
            }
            try:
                return session.request(session_request)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                # A timeout or stream error leaves framing ambiguous.  Evict
                # and terminate the exact process so a delayed response can
                # never be consumed as the reply to a later request.
                with _IROH_SESSIONS_LOCK:
                    if _IROH_SESSIONS.get(key) is session:
                        _IROH_SESSIONS.pop(key, None)
                session.abort()
                raise
        completed = subprocess.run(
            [str(executable)],
            input=json.dumps(
                request,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n",
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
        lines = [
            line.strip()
            for line in completed.stdout.splitlines()
            if line.strip()
        ]
        if completed.returncode != 0 or len(lines) != 1:
            raise RuntimeError("The Iroh cache sidecar failed")
        try:
            payload = json.loads(lines[0])
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "The Iroh cache sidecar returned invalid output"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeError("The Iroh cache sidecar returned invalid output")
        return payload

    @staticmethod
    def _minimal_environment() -> dict[str, str]:
        return {
            name: value
            for name in (
                "SystemRoot",
                "WINDIR",
                "ComSpec",
                "TEMP",
                "TMP",
                "PATH",
                "LANG",
            )
            if (value := os.environ.get(name))
        }

    @staticmethod
    def _fetch_receipt(
        plan: dict[str, Any],
        target: Path,
        *,
        downloaded: bool,
        duration_ms: float,
    ) -> dict[str, Any]:
        return {
            "schema": OBJECT_RECEIPT_SCHEMA,
            "receiptId": f"cachereceipt_{uuid.uuid4().hex[:20]}",
            "createdAt": utc_now(),
            "planId": str(plan.get("planId") or ""),
            "planHash": str(plan.get("planHash") or ""),
            "objectHash": str(plan.get("objectHash") or ""),
            "algorithm": "blake3",
            "bytes": target.stat().st_size,
            "kind": str(plan.get("kind") or ""),
            "pinned": bool(plan.get("pin")),
            "copied": downloaded,
            "deduplicated": not downloaded,
            "integrityVerified": True,
            "networkUsed": downloaded,
            "transport": "iroh-blobs" if downloaded else "local-cas",
            "durationMs": duration_ms,
            "peerRef": str(plan.get("peerRef") or ""),
            "providerEndpointIdExposed": False,
            "ticketExposed": False,
            "ok": True,
            "status": "available",
        }

    @staticmethod
    def _validated_hash(value: str) -> str:
        normalized = str(value or "").strip().casefold()
        if len(normalized) != 64 or any(
            character not in "0123456789abcdef" for character in normalized
        ):
            raise ValueError("Invalid BLAKE3 object hash")
        return normalized

    @staticmethod
    def _hash_file(path: Path) -> str:
        hasher = blake3.blake3()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def _plan_hash(plan: dict[str, Any]) -> str:
        value = copy.deepcopy(plan)
        value.pop("planHash", None)
        return _canonical_hash(value)

    def _validate_plan(self, plan: dict[str, Any]) -> None:
        if not isinstance(plan, dict) or plan.get("schema") != IMPORT_PLAN_SCHEMA:
            raise ValueError("Invalid cache import plan")
        if str(plan.get("planHash") or "") != self._plan_hash(plan):
            raise ValueError("Cache import plan hash does not match")
        self._validated_hash(str(plan.get("objectHash") or ""))

    def _validate_fetch_plan(self, plan: dict[str, Any]) -> None:
        if not isinstance(plan, dict) or plan.get("schema") != FETCH_PLAN_SCHEMA:
            raise ValueError("Invalid cache fetch plan")
        if str(plan.get("planHash") or "") != self._plan_hash(plan):
            raise ValueError("Cache fetch plan hash does not match")
        self._validated_hash(str(plan.get("objectHash") or ""))
        peer = self._peer(str(plan.get("peerRef") or ""))
        ticket = self._peer_offer(
            peer,
            str(plan.get("objectHash") or ""),
        )
        if str(plan.get("offerDigest") or "") != _canonical_hash(ticket):
            raise ValueError("Peer offer changed after cache fetch preview")

    def _validate_scheduled_fetch_plan(self, plan: dict[str, Any]) -> None:
        if (
            not isinstance(plan, dict)
            or plan.get("schema") != SCHEDULED_FETCH_PLAN_SCHEMA
        ):
            raise ValueError("Invalid scheduled cache fetch plan")
        if str(plan.get("planHash") or "") != self._plan_hash(plan):
            raise ValueError("Scheduled cache fetch plan hash does not match")
        digest = self._validated_hash(str(plan.get("objectHash") or ""))
        if plan.get("transportBinding") != self._transport_schedule_binding():
            raise ValueError("Scheduled cache fetch transport policy changed")
        if str(plan.get("schedulingPolicyHash") or "") != _canonical_hash(
            self._scheduling_policy_snapshot()
        ):
            raise ValueError(
                "Scheduled cache fetch scheduling policy changed"
            )
        if int(plan.get("maxBytes") or 0) != int(
            self.cache.get("maxImportBytes")
            or 20 * 1024 * 1024 * 1024
        ):
            raise ValueError("Scheduled cache fetch byte limit changed")
        attempts = plan.get("attemptOrder")
        if not isinstance(attempts, list) or len(attempts) > _MAX_FETCH_ATTEMPTS:
            raise ValueError("Scheduled cache fetch attempts are invalid")
        seen: set[str] = set()
        for candidate in attempts:
            if not isinstance(candidate, dict):
                raise ValueError("Scheduled cache fetch candidate is invalid")
            peer_ref = str(candidate.get("peerRef") or "")
            if peer_ref in seen:
                raise ValueError("Scheduled cache fetch candidate is duplicated")
            seen.add(peer_ref)
            self._validate_scheduled_candidate(candidate, digest=digest)
        self._assert_scheduled_attempt_order_current(plan, digest=digest)

    def _validate_gc_plan(self, plan: dict[str, Any]) -> None:
        if not isinstance(plan, dict) or plan.get("schema") != GC_PLAN_SCHEMA:
            raise ValueError("Invalid cache garbage collection plan")
        evictions = plan.get("evictions")
        if (
            not isinstance(evictions, list)
            or len(evictions) > _MAX_GC_DELETES
        ):
            raise ValueError("Cache garbage collection plan exceeds safe limits")
        if str(plan.get("planHash") or "") != self._plan_hash(plan):
            raise ValueError("Cache garbage collection plan hash does not match")
        plan_id = str(plan.get("planId") or "")
        plan_suffix = plan_id.removeprefix("cachegc_")
        if (
            not plan_id.startswith("cachegc_")
            or len(plan_suffix) != 20
            or any(
                character not in "0123456789abcdef"
                for character in plan_suffix
            )
        ):
            raise ValueError("Invalid cache garbage collection plan identifier")
        limits = plan.get("limits")
        if not isinstance(limits, dict):
            raise ValueError("Invalid cache garbage collection limits")
        for name in (
            "maxCacheBytes",
            "maxObjects",
            "maxDeletesPerRun",
            "maxDeleteBytesPerRun",
        ):
            value = limits.get(name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("Invalid cache garbage collection limits")
        if (
            int(limits["maxDeletesPerRun"]) > _MAX_GC_DELETES
            or int(limits["maxDeleteBytesPerRun"]) > _MAX_GC_DELETE_BYTES
        ):
            raise ValueError("Cache garbage collection plan exceeds safe limits")
        seen: set[str] = set()
        total_bytes = 0
        for candidate in evictions:
            if not isinstance(candidate, dict):
                raise ValueError("Invalid cache garbage collection candidate")
            digest = self._validated_hash(
                str(candidate.get("objectHash") or "")
            )
            if digest in seen:
                raise ValueError("Cache garbage collection candidate is duplicated")
            seen.add(digest)
            try:
                size = int(candidate.get("bytes"))
                mtime_ns = int(candidate.get("mtimeNs"))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "Invalid cache garbage collection candidate"
                ) from exc
            if size < 0 or mtime_ns < 0:
                raise ValueError("Invalid cache garbage collection candidate")
            accessed_at = str(candidate.get("lastAccessedAt") or "")
            if not accessed_at or len(accessed_at) > 80:
                raise ValueError("Invalid cache garbage collection candidate")
            total_bytes += size
        if total_bytes > _MAX_GC_DELETE_BYTES:
            raise ValueError("Cache garbage collection plan exceeds safe limits")


from .proofs_d_runtime import checked as _checked
P2PCacheService.compatibility_snapshot = _checked("d.runtime.cache.compatibility", P2PCacheService.compatibility_snapshot)
P2PCacheService.bootstrap = _checked("d.runtime.cache.bootstrap", P2PCacheService.bootstrap)
P2PCacheService.plan_import = _checked("d.runtime.cache.plan", P2PCacheService.plan_import)
P2PCacheService.import_object = _checked("d.runtime.cache.import", P2PCacheService.import_object)
P2PCacheService.read_text = _checked("d.runtime.cache.read", P2PCacheService.read_text)
