"""Run-scoped immutable compiled maps and version-bound provider selections."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .capability_contracts import canonical_hash
from .model_tool_intelligence import ModelToolIntelligence


class CompiledToolMapStore:
    """Retain every version for the gateway's lifetime, without latest-map fallback."""

    def __init__(self) -> None:
        self._versions: dict[str, dict[str, Any]] = {}
        self.latest_version = ""

    def retain(self, compiled: dict[str, Any]) -> str:
        version = canonical_hash(compiled.get("callMap") or {})
        self._versions.setdefault(version, deepcopy(compiled))
        self.latest_version = version
        return version

    @property
    def version_count(self) -> int:
        return len(self._versions)

    def resolve(self, selection: str, arguments: dict[str, Any]) -> dict[str, Any]:
        provider_call, separator, version = selection.partition("@")
        namespace, dot, name = provider_call.partition(".")
        if not dot or not namespace or not name:
            raise ValueError("provider_call must use namespace.name@callMapHash")
        if separator:
            compiled = self._versions.get(version)
            if compiled is None:
                raise KeyError(f"Compiled tool map version is not retained: {version}")
            # Do not use the resolver's suffix fallback for a version-bound selection.
            if provider_call not in (compiled.get("callMap") or {}):
                raise KeyError(f"Provider call is absent from selected map: {provider_call}")
        else:
            candidates = [(key, value) for key, value in self._versions.items()
                          if provider_call in (value.get("callMap") or {})]
            if not candidates:
                raise KeyError(f"Provider call is not retained: {provider_call}")
            meanings = {canonical_hash(value["callMap"][provider_call]) for _, value in candidates}
            if len(meanings) != 1:
                raise ValueError("Provider call has multiple retained meanings; use namespace.name@callMapHash")
            version, compiled = candidates[0]
        resolved = ModelToolIntelligence.resolve_openai_call(
            deepcopy(compiled), namespace=namespace, name=name, arguments=arguments)
        return {**resolved, "callMapHash": version}
