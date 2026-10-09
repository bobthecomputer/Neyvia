from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from grant_agent.p2p_cache import P2PCacheService, shutdown_p2p_sessions
from grant_agent.p2p_provider import P2PProviderService
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


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


def _identity(executable: Path, state_root: Path) -> str:
    completed = subprocess.run(
        [str(executable)],
        input=(
            json.dumps(
                {
                    "operation": "identity",
                    "stateRoot": str(state_root),
                }
            )
            + "\n"
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        shell=False,
        env=_minimal_environment(),
        **hidden_windows_subprocess_kwargs(),
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stdout or completed.stderr)
    response = json.loads(completed.stdout.splitlines()[0])
    endpoint_id = str(response.get("endpointId") or "")
    if len(endpoint_id) < 32:
        raise RuntimeError("Consumer identity was not created")
    return endpoint_id


def _config(
    runtime_root: Path,
    executable: Path,
    executable_sha256: str,
    *,
    peer_ref: str,
    endpoint_id: str,
    offers: dict[str, str] | None = None,
    provider: bool,
    health_port: int,
) -> dict[str, Any]:
    prefix = "provider" if provider else "consumer"
    return {
        "schema": "neyvia.p2p-cache-config/v1",
        "transport": {
            "name": "Iroh",
            "version": "1.0.3",
            "blobsVersion": "0.103.0",
            "sidecarState": "verified",
            "executable": str(executable),
            "executableSha256": executable_sha256,
            "stateRoot": str(runtime_root / f"{prefix}-transport-state"),
            "storeRoot": str(runtime_root / f"{prefix}-transport-store"),
            "commandTimeoutSeconds": 30,
            "persistentSession": True,
        },
        "cache": {
            "root": str(runtime_root / f"{prefix}-objects"),
            "hash": "blake3",
            "maxImportBytes": 16 * 1024 * 1024,
            "maxTextReadBytes": 64 * 1024,
            "copyBufferBytes": 1024 * 1024,
            "verifyOnChangedMetadata": True,
        },
        "provider": {
            "stateRoot": str(runtime_root / "provider-control"),
            "manifestPath": str(runtime_root / "provider-manifest.json"),
            "offersPath": str(runtime_root / "provider-offers.json"),
            "identityStateRoot": str(runtime_root / "provider-identity"),
            "blobStoreRoot": str(runtime_root / "provider-blob-store"),
            "healthPort": health_port,
            "startupTimeoutSeconds": 20,
            "stopTimeoutSeconds": 10,
        },
        "policy": {
            "importsWorkspaceOnly": True,
            "remoteFetchRequiresApprovedPeer": True,
            "remotePublishRequiresApproval": True,
            "publicDiscoveryDefault": False,
            "publicRelayDefault": False,
            "encryptedTransportRequired": True,
            "allowedKinds": [
                "context-chunk",
                "artifact",
                "module",
                "package",
                "model",
                "index",
            ],
            "peers": [
                {
                    "peerRef": peer_ref,
                    "endpointId": endpoint_id,
                    "enabled": True,
                    "offers": offers or {},
                }
            ],
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run(root: Path, executable: Path) -> dict[str, Any]:
    executable = executable.resolve(strict=True)
    executable_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
    scratch_parent = (
        root / ".agent_control" / "capability_os" / "qa" / "runtime"
    )
    scratch_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="iroh-provider-",
        dir=scratch_parent,
        ignore_cleanup_errors=True,
    ) as temporary:
        runtime_root = Path(temporary).resolve()
        consumer_state = runtime_root / "consumer-transport-state"
        consumer_id = _identity(executable, consumer_state)
        provider_config_path = runtime_root / "provider-config.json"
        _write_json(
            provider_config_path,
            _config(
                runtime_root,
                executable,
                executable_sha256,
                peer_ref="peer.consumer",
                endpoint_id=consumer_id,
                provider=True,
                health_port=_free_loopback_port(),
            ),
        )
        provider = P2PProviderService(
            runtime_root,
            config_path=provider_config_path,
        )
        first_source = runtime_root / "first-context.bin"
        first_source.write_bytes((b"neyvia-fast-context-" * 65536)[:1048576])
        first_import = provider.cache.import_object(
            provider.cache.plan_import(
                first_source,
                kind="context-chunk",
            ),
            approved=True,
        )
        first_hash = str(first_import["objectHash"])
        service_started = False
        try:
            activation_started = time.perf_counter()
            activation = provider.apply_publication(
                provider.plan_publication(
                    [first_hash],
                    peer_refs=["peer.consumer"],
                    actor="provider-lifecycle-proof",
                ),
                approved=True,
            )
            activation_ms = round(
                (time.perf_counter() - activation_started) * 1000,
                3,
            )
            service_started = True
            active_status = provider.status()
            raw_offers = provider.read_offers_for_broker()
            offer_map = {
                str(item["objectHash"]): str(item["ticket"])
                for item in raw_offers["offers"]
            }
            provider_endpoint = str(raw_offers["endpointId"])

            consumer_config_path = runtime_root / "consumer-config.json"
            _write_json(
                consumer_config_path,
                _config(
                    runtime_root,
                    executable,
                    executable_sha256,
                    peer_ref="peer.provider",
                    endpoint_id=provider_endpoint,
                    offers=offer_map,
                    provider=False,
                    health_port=_free_loopback_port(),
                ),
            )
            consumer = P2PCacheService(
                runtime_root,
                config_path=consumer_config_path,
            )
            fetch_started = time.perf_counter()
            fetched = consumer.fetch_object(
                consumer.plan_fetch(
                    first_hash,
                    peer_ref="peer.provider",
                    kind="context-chunk",
                ),
                approved=True,
            )
            fetch_wall_ms = round(
                (time.perf_counter() - fetch_started) * 1000,
                3,
            )
            downloaded = consumer._object_path(first_hash)
            integrity_verified = (
                hashlib.sha256(downloaded.read_bytes()).hexdigest()
                == hashlib.sha256(first_source.read_bytes()).hexdigest()
                and str(fetched["objectHash"]) == first_hash
            )

            second_source = runtime_root / "second-context.bin"
            second_source.write_bytes(
                (b"neyvia-provider-reload-" * 32768)[:524288]
            )
            second_import = provider.cache.import_object(
                provider.cache.plan_import(
                    second_source,
                    kind="context-chunk",
                ),
                approved=True,
            )
            second_hash = str(second_import["objectHash"])
            reload_started = time.perf_counter()
            reloaded = provider.apply_publication(
                provider.plan_publication(
                    [first_hash, second_hash],
                    peer_refs=["peer.consumer"],
                    actor="provider-lifecycle-proof",
                ),
                approved=True,
            )
            reload_ms = round(
                (time.perf_counter() - reload_started) * 1000,
                3,
            )
            reload_status = provider.status()

            managed = provider._service_from_manifest()
            managed.stop()
            stopped_health = provider.status()
            restart_started = time.perf_counter()
            managed.start()
            restart_ms = round(
                (time.perf_counter() - restart_started) * 1000,
                3,
            )
            restart_status = provider.status()

            stopped = provider.apply_publication(
                provider.plan_publication([], peer_refs=[]),
                approved=True,
            )
            service_started = False
            final_status = provider.status()
            public_payload = json.dumps(
                {
                    "activation": activation,
                    "activeStatus": active_status,
                    "fetch": fetched,
                    "reload": reloaded,
                    "reloadStatus": reload_status,
                    "restartStatus": restart_status,
                    "stop": stopped,
                    "finalStatus": final_status,
                    "receipts": provider.receipts(),
                }
            )
            return {
                "schema": "neyvia.iroh-provider-lifecycle-run/v1",
                "binary": {
                    "path": str(executable),
                    "sha256": executable_sha256,
                    "bytes": executable.stat().st_size,
                },
                "objectBytes": first_source.stat().st_size,
                "objectHash": first_hash,
                "activationMs": activation_ms,
                "fetchWallMs": fetch_wall_ms,
                "fetchDurationMs": fetched["durationMs"],
                "reloadMs": reload_ms,
                "restartMs": restart_ms,
                "integrityVerified": integrity_verified,
                "activeHealthy": active_status["healthy"],
                "reloadHealthy": reload_status["healthy"],
                "stoppedHealthObserved": (
                    stopped_health["serviceStatus"] == "stopped"
                    and not stopped_health["healthy"]
                ),
                "restartHealthy": restart_status["healthy"],
                "finalStopped": (
                    not final_status["active"]
                    and final_status["serviceStatus"] == "stopped"
                ),
                "endpointIdsExposed": '"endpointId":' in public_payload,
                "ticketsExposed": '"ticket":' in public_payload,
                "publicDiscovery": False,
                "publicRelay": False,
                "receipts": len(provider.receipts()["events"]),
            }
        finally:
            shutdown_p2p_sessions()
            if service_started:
                try:
                    provider._service_from_manifest().stop()
                except Exception:
                    pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--executable",
        default=(
            r"D:\Neyvia\apps\neyvia-iroh-cache\0.1.0"
            r"\bin\neyvia-iroh-cache.exe"
        ),
    )
    arguments = parser.parse_args()
    result = run(
        Path(arguments.root).resolve(),
        Path(arguments.executable),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    required = (
        "integrityVerified",
        "activeHealthy",
        "reloadHealthy",
        "stoppedHealthObserved",
        "restartHealthy",
        "finalStopped",
    )
    return 0 if all(result[name] for name in required) else 1


if __name__ == "__main__":
    raise SystemExit(main())
