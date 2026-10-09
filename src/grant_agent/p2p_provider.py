"""Supervised, rollback-safe publication of Neyvia CAS objects over Iroh."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from .capability_contracts import utc_now
from .managed_local_service import ManagedLocalService, ManagedServiceSpec
from .p2p_cache import (
    P2PCacheService,
    _canonical_hash,
    _deployment_storage_path,
)


PUBLICATION_PLAN_SCHEMA = "neyvia.p2p-provider-publication-plan/v1"
PUBLICATION_RECEIPT_SCHEMA = "neyvia.p2p-provider-publication-receipt/v1"
PROVIDER_MANIFEST_SCHEMA = "neyvia.iroh-provider-manifest/v1"

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class P2PProviderService:
    def __init__(
        self,
        root: str | Path,
        *,
        config_path: str | Path | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.cache = P2PCacheService(root, config_path=config_path)
        self.config = self.cache.config
        self.provider = dict(self.config.get("provider") or {})
        self.state_root = self._absolute_provider_path("stateRoot")
        self.manifest_path = self._absolute_provider_path("manifestPath")
        self.offers_path = self._absolute_provider_path("offersPath")
        self.publication_state_path = self.state_root / "publication-state.json"
        self.receipt_path = self.state_root / "publication-receipts.jsonl"
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(
                str(self.publication_state_path),
                threading.RLock(),
            )

    def status(self) -> dict[str, Any]:
        state = self._current_state()
        service_status = "stopped"
        healthy = False
        if state["active"]:
            service = self._service_from_manifest()
            observed = service.status()
            service_status = str(observed.get("status") or "unknown")
            healthy = bool(observed.get("healthy"))
        offers = _read_object(self.offers_path)
        offers_ready = bool(
            state["active"]
            and offers.get("schema") == "neyvia.iroh-provider-offers/v1"
            and offers.get("manifestHash") == state["manifestHash"]
            and len(offers.get("offers") or []) == len(state["objects"])
        )
        return {
            "schema": "neyvia.p2p-provider-status/v1",
            "active": state["active"],
            "serviceStatus": service_status,
            "healthy": healthy,
            "manifestHash": state["manifestHash"],
            "objects": list(state["objects"]),
            "peerRefs": list(state["peerRefs"]),
            "summary": {
                "objectCount": len(state["objects"]),
                "peerCount": len(state["peerRefs"]),
                "offersReady": offers_ready,
            },
            "publicDiscovery": False,
            "publicRelay": False,
            "endpointIdsExposed": False,
            "ticketsExposed": False,
        }

    def plan_publication(
        self,
        object_hashes: list[str],
        *,
        peer_refs: list[str],
        actor: str = "agent",
    ) -> dict[str, Any]:
        normalized_hashes = sorted(
            {self.cache._validated_hash(value) for value in object_hashes}
        )
        normalized_peers = sorted(
            {str(value or "").strip() for value in peer_refs if str(value or "").strip()}
        )
        if normalized_hashes and not normalized_peers:
            raise ValueError("At least one approved peer is required to publish")
        bindings: list[dict[str, Any]] = []
        for digest in normalized_hashes:
            path = self.cache._verified_object(digest)
            stat = path.stat()
            bindings.append(
                {
                    "objectHash": digest,
                    "bytes": stat.st_size,
                    "mtimeNs": stat.st_mtime_ns,
                }
            )
        for peer_ref in normalized_peers:
            self.cache._peer(peer_ref)
        current = self._current_state()
        plan = {
            "schema": PUBLICATION_PLAN_SCHEMA,
            "planId": f"providerplan_{uuid.uuid4().hex[:20]}",
            "createdAt": utc_now(),
            "actor": str(actor or "agent")[:80],
            "baseStateHash": self._state_hash(current),
            "objects": bindings,
            "peerRefs": normalized_peers,
            "action": "activate" if bindings else "stop",
            "summary": {
                "objectCount": len(bindings),
                "peerCount": len(normalized_peers),
                "providerRestartRequired": bool(current["active"] or bindings),
                "publicDiscovery": False,
                "publicRelay": False,
                "endpointIdsExposed": False,
                "ticketsExposed": False,
            },
        }
        plan["planHash"] = self._plan_hash(plan)
        return plan

    def apply_publication(
        self,
        plan: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        if not approved:
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermissions": [
                    "network.write",
                    "artifact.write",
                    "external.side_effect",
                ],
            }
        with self._lock:
            self._validate_plan(plan)
            current = self._current_state()
            if str(plan.get("baseStateHash") or "") != self._state_hash(current):
                raise ValueError("Provider state changed after publication preview")
            bindings = [dict(item) for item in plan.get("objects") or []]
            for binding in bindings:
                path = self.cache._verified_object(
                    str(binding.get("objectHash") or "")
                )
                stat = path.stat()
                if (
                    stat.st_size != int(binding.get("bytes") or -1)
                    or stat.st_mtime_ns != int(binding.get("mtimeNs") or -1)
                ):
                    raise ValueError("Published cache object changed after preview")
            peer_refs = [str(value) for value in plan.get("peerRefs") or []]
            peers = [self.cache._peer(value) for value in peer_refs]

            old_manifest = (
                self.manifest_path.read_bytes()
                if self.manifest_path.is_file()
                else None
            )
            old_state = (
                self.publication_state_path.read_bytes()
                if self.publication_state_path.is_file()
                else None
            )
            old_offers = (
                self.offers_path.read_bytes()
                if self.offers_path.is_file()
                else None
            )
            old_service = (
                self._service_from_manifest()
                if current["active"]
                else None
            )
            if old_service is not None:
                old_service.stop()

            new_service: ManagedLocalService | None = None
            try:
                if not bindings:
                    stopped_state = self._empty_state()
                    _atomic_json(self.publication_state_path, stopped_state)
                    _atomic_json(
                        self.offers_path,
                        {
                            "schema": "neyvia.iroh-provider-offers/v1",
                            "manifestHash": "",
                            "offers": [],
                            "active": False,
                            "credentialMaterial": False,
                        },
                    )
                    receipt = self._receipt(
                        plan,
                        state=stopped_state,
                        service_status="stopped",
                    )
                    self._append_receipt(receipt)
                    return receipt

                manifest = self._build_manifest(bindings, peers)
                _atomic_json(self.manifest_path, manifest)
                new_service = self._service_from_manifest(manifest)
                started = new_service.start()
                activated_state = {
                    "schema": "neyvia.p2p-provider-state/v1",
                    "active": True,
                    "manifestHash": manifest["manifestHash"],
                    "objects": [
                        str(item["objectHash"]) for item in bindings
                    ],
                    "peerRefs": peer_refs,
                    "activatedAt": utc_now(),
                }
                _atomic_json(self.publication_state_path, activated_state)
                receipt = self._receipt(
                    plan,
                    state=activated_state,
                    service_status=str(started.get("status") or "running"),
                )
                self._append_receipt(receipt)
                return receipt
            except Exception:
                if new_service is not None:
                    try:
                        observed = new_service.status()
                        if observed.get("status") == "running":
                            new_service.stop()
                    except Exception:
                        pass
                self._restore_bytes(self.manifest_path, old_manifest)
                self._restore_bytes(self.publication_state_path, old_state)
                self._restore_bytes(self.offers_path, old_offers)
                if old_service is not None:
                    old_service.start()
                raise

    def read_offers_for_broker(self) -> dict[str, Any]:
        state = self._current_state()
        if not state["active"]:
            raise RuntimeError("The Iroh provider is not active")
        offers = _read_object(self.offers_path)
        if (
            offers.get("schema") != "neyvia.iroh-provider-offers/v1"
            or offers.get("manifestHash") != state["manifestHash"]
        ):
            raise RuntimeError("Provider offers do not match active state")
        return offers

    def receipts(self, *, limit: int = 50) -> dict[str, Any]:
        bounded = max(1, min(int(limit), 200))
        events: list[dict[str, Any]] = []
        if self.receipt_path.is_file():
            for line in self.receipt_path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()[-bounded:]:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    events.append(value)
        return {
            "schema": "neyvia.p2p-provider-receipts/v1",
            "events": events,
            "detailsBounded": True,
            "endpointIdsExposed": False,
            "ticketsExposed": False,
        }

    def _build_manifest(
        self,
        bindings: list[dict[str, Any]],
        peers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        manifest = {
            "schema": PROVIDER_MANIFEST_SCHEMA,
            "stateRoot": str(self._absolute_provider_path("identityStateRoot")),
            "storeRoot": str(self._absolute_provider_path("blobStoreRoot")),
            "offersPath": str(self.offers_path),
            "healthPort": self._health_port(),
            "sources": [
                {
                    "path": str(
                        self.cache._object_path(str(item["objectHash"]))
                    ),
                    "objectHash": str(item["objectHash"]),
                }
                for item in bindings
            ],
            "allowedPeers": [
                str(peer.get("endpointId") or "") for peer in peers
            ],
        }
        manifest["manifestHash"] = _canonical_hash(manifest)
        return manifest

    def _service_from_manifest(
        self,
        manifest: dict[str, Any] | None = None,
    ) -> ManagedLocalService:
        selected = manifest or _read_object(self.manifest_path)
        if selected.get("schema") != PROVIDER_MANIFEST_SCHEMA:
            raise RuntimeError("The active provider manifest is unavailable")
        executable = self.cache._sidecar_path()
        return ManagedLocalService(
            ManagedServiceSpec(
                service_id="neyvia.iroh-provider",
                executable=executable,
                executable_sha256=str(
                    self.cache.transport.get("executableSha256") or ""
                ),
                argv=("--provider-config", str(self.manifest_path)),
                state_root=self.state_root / "service",
                health_url=(
                    f"http://127.0.0.1:{int(selected['healthPort'])}/health"
                ),
                health_expected={
                    "status": "healthy",
                    "manifestHash": str(selected["manifestHash"]),
                    "endpointIdExposed": False,
                    "ticketsExposed": False,
                },
                required_files=(
                    (self.manifest_path, _sha256_file(self.manifest_path)),
                ),
                cwd=self.root,
                environment=self.cache._minimal_environment(),
                inherit_environment=False,
                startup_timeout_seconds=float(
                    self.provider.get("startupTimeoutSeconds") or 20
                ),
                stop_timeout_seconds=float(
                    self.provider.get("stopTimeoutSeconds") or 10
                ),
            )
        )

    def _current_state(self) -> dict[str, Any]:
        value = _read_object(self.publication_state_path)
        if value.get("schema") != "neyvia.p2p-provider-state/v1":
            return self._empty_state()
        return {
            "schema": "neyvia.p2p-provider-state/v1",
            "active": bool(value.get("active")),
            "manifestHash": str(value.get("manifestHash") or ""),
            "objects": sorted(
                str(item) for item in value.get("objects") or []
            ),
            "peerRefs": sorted(
                str(item) for item in value.get("peerRefs") or []
            ),
        }

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "schema": "neyvia.p2p-provider-state/v1",
            "active": False,
            "manifestHash": "",
            "objects": [],
            "peerRefs": [],
        }

    @staticmethod
    def _state_hash(state: dict[str, Any]) -> str:
        return _canonical_hash(
            {
                "active": bool(state.get("active")),
                "manifestHash": str(state.get("manifestHash") or ""),
                "objects": sorted(
                    str(item) for item in state.get("objects") or []
                ),
                "peerRefs": sorted(
                    str(item) for item in state.get("peerRefs") or []
                ),
            }
        )

    @staticmethod
    def _plan_hash(plan: dict[str, Any]) -> str:
        value = copy.deepcopy(plan)
        value.pop("planHash", None)
        return _canonical_hash(value)

    def _validate_plan(self, plan: dict[str, Any]) -> None:
        if (
            not isinstance(plan, dict)
            or plan.get("schema") != PUBLICATION_PLAN_SCHEMA
        ):
            raise ValueError("Invalid provider publication plan")
        if str(plan.get("planHash") or "") != self._plan_hash(plan):
            raise ValueError("Provider publication plan hash does not match")
        for binding in plan.get("objects") or []:
            if not isinstance(binding, dict):
                raise ValueError("Invalid provider object binding")
            self.cache._validated_hash(
                str(binding.get("objectHash") or "")
            )

    def _receipt(
        self,
        plan: dict[str, Any],
        *,
        state: dict[str, Any],
        service_status: str,
    ) -> dict[str, Any]:
        return {
            "schema": PUBLICATION_RECEIPT_SCHEMA,
            "receiptId": f"providerreceipt_{uuid.uuid4().hex[:20]}",
            "createdAt": utc_now(),
            "planId": str(plan.get("planId") or ""),
            "planHash": str(plan.get("planHash") or ""),
            "active": bool(state.get("active")),
            "manifestHash": str(state.get("manifestHash") or ""),
            "objects": list(state.get("objects") or []),
            "peerRefs": list(state.get("peerRefs") or []),
            "serviceStatus": service_status,
            "publicDiscovery": False,
            "publicRelay": False,
            "endpointIdsExposed": False,
            "ticketsExposed": False,
            "ok": True,
            "status": "active" if state.get("active") else "stopped",
        }

    def _append_receipt(self, receipt: dict[str, Any]) -> None:
        self.receipt_path.parent.mkdir(parents=True, exist_ok=True)
        with self.receipt_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    receipt,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _restore_bytes(path: Path, value: bytes | None) -> None:
        if value is None:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.restore")
        temporary.write_bytes(value)
        os.replace(temporary, path)

    def _absolute_provider_path(self, name: str) -> Path:
        base = self.root / ".agent_control" / "p2p_cache"
        fallbacks = {
            "stateRoot": base / "provider-control",
            "manifestPath": getattr(
                self,
                "state_root",
                base / "provider-control",
            )
            / "provider-manifest.json",
            "offersPath": getattr(
                self,
                "state_root",
                base / "provider-control",
            )
            / "provider-offers.json",
            "identityStateRoot": base / "provider-identity",
            "blobStoreRoot": base / "provider-store",
        }
        fallback = fallbacks.get(name)
        if fallback is None:
            raise RuntimeError(f"Unknown provider path: {name}")
        return _deployment_storage_path(
            self.root,
            self.provider.get(name),
            fallback,
        )

    def _health_port(self) -> int:
        value = int(self.provider.get("healthPort") or 0)
        if value < 1024 or value > 65535:
            raise RuntimeError("Provider healthPort must be between 1024 and 65535")
        return value
