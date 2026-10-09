from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import os
from pathlib import Path
import time

from ..models import RuntimeCapability, RuntimeInstallStatus
from ..snapshot_cache import (
    invalidate_persistent_snapshot_cache,
    load_persistent_snapshot_cache,
    save_persistent_snapshot_cache,
)
from .base import AgentRuntimeAdapter
from .codex import CodexRuntimeAdapter
from .cursor import CursorRuntimeAdapter
from .hermes import HermesRuntimeAdapter
from .managed_cli import (
    ClaudeCodeRuntimeAdapter,
    DeepSeekHarnessRuntimeAdapter,
    GptmeRuntimeAdapter,
    GrokBuildRuntimeAdapter,
    KimiCodeRuntimeAdapter,
    PiRuntimeAdapter,
    PrimeAgentRuntimeAdapter,
    RookRuntimeAdapter,
    WallbreakerRuntimeAdapter,
)
from .openclaw import OpenClawRuntimeAdapter
from .opencode import OpenCodeRuntimeAdapter
from .neyvia import NeyviaRuntimeAdapter

_RUNTIME_STATUS_CACHE_TTL_SECONDS = max(
    float(os.environ.get("FLUXIO_RUNTIME_STATUS_CACHE_TTL_SECONDS", "300")),
    5.0,
)
_RUNTIME_STATUS_CACHE: dict[str, tuple[float, list[RuntimeInstallStatus]]] = {}


def runtime_adapters() -> list[AgentRuntimeAdapter]:
    return [
        NeyviaRuntimeAdapter(),
        CodexRuntimeAdapter(),
        OpenClawRuntimeAdapter(),
        HermesRuntimeAdapter(),
        OpenCodeRuntimeAdapter(),
        CursorRuntimeAdapter(),
        KimiCodeRuntimeAdapter(),
        ClaudeCodeRuntimeAdapter(),
        GrokBuildRuntimeAdapter(),
        PrimeAgentRuntimeAdapter(),
        PiRuntimeAdapter(),
        DeepSeekHarnessRuntimeAdapter(),
        GptmeRuntimeAdapter(),
        RookRuntimeAdapter(),
        WallbreakerRuntimeAdapter(),
    ]


def runtime_adapter_map() -> dict[str, AgentRuntimeAdapter]:
    return {adapter.runtime_id: adapter for adapter in runtime_adapters()}


def _runtime_status_from_payload(payload: object) -> list[RuntimeInstallStatus] | None:
    if not isinstance(payload, list):
        return None
    statuses: list[RuntimeInstallStatus] = []
    for item in payload:
        if not isinstance(item, dict):
            return None
        capabilities = [
            RuntimeCapability(**capability)
            for capability in item.get("capabilities", [])
            if isinstance(capability, dict)
        ]
        statuses.append(
            RuntimeInstallStatus(
                runtime_id=str(item.get("runtime_id", "")),
                label=str(item.get("label", "")),
                detected=bool(item.get("detected", False)),
                command=item.get("command"),
                version=item.get("version"),
                latest_version=item.get("latest_version"),
                update_available=bool(item.get("update_available", False)),
                update_command=item.get("update_command"),
                update_source_url=item.get("update_source_url"),
                install_hint=item.get("install_hint"),
                doctor_summary=str(item.get("doctor_summary", "")),
                issues=[
                    str(issue)
                    for issue in item.get("issues", [])
                    if str(issue).strip()
                ],
                capabilities=capabilities,
            )
        )
    return statuses


def invalidate_runtime_status_cache(workspace_root: Path | None = None) -> None:
    if workspace_root is None:
        _RUNTIME_STATUS_CACHE.clear()
        return
    root = Path(workspace_root).resolve()
    _RUNTIME_STATUS_CACHE.pop(str(root), None)
    invalidate_persistent_snapshot_cache(root, "runtime_statuses")


def detect_runtime_statuses(
    workspace_root: Path,
    *,
    force: bool = False,
) -> list[RuntimeInstallStatus]:
    root = Path(workspace_root).resolve()
    cache_key = str(root)
    now = time.monotonic()
    cached = _RUNTIME_STATUS_CACHE.get(cache_key)
    if not force and cached and now - cached[0] < _RUNTIME_STATUS_CACHE_TTL_SECONDS:
        return deepcopy(cached[1])

    if not force:
        persisted = _runtime_status_from_payload(
            load_persistent_snapshot_cache(
                root,
                "runtime_statuses",
                _RUNTIME_STATUS_CACHE_TTL_SECONDS,
            )
        )
        if persisted is not None:
            _RUNTIME_STATUS_CACHE[cache_key] = (now, deepcopy(persisted))
            return deepcopy(persisted)

    payload = [adapter.doctor(root) for adapter in runtime_adapters()]
    save_persistent_snapshot_cache(
        root,
        "runtime_statuses",
        [asdict(item) for item in payload],
    )
    _RUNTIME_STATUS_CACHE[cache_key] = (now, deepcopy(payload))
    return payload

