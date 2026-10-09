"""Grant Agent Harness package.

Public service classes stay available from :mod:`grant_agent`, but they are
loaded only when requested.  Entry points such as the web backend and workers
can therefore expose health/readiness without importing the full autonomous
engine and capability stack first.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_PUBLIC_EXPORTS = {
    "AutonomousEngine": (".engine", "AutonomousEngine"),
    "AgentConstitution": (".constitution", "AgentConstitution"),
    "PreflightPolicy": (".constitution", "PreflightPolicy"),
    "CapabilityService": (".capability_service", "CapabilityService"),
    "ComputerUseTwinService": (".computer_use_twin", "ComputerUseTwinService"),
    "ComputerUseVerifierService": (
        ".computer_use_verifier",
        "ComputerUseVerifierService",
    ),
    "DurableContextEngine": (".context_engine", "DurableContextEngine"),
    "ContextWindowManager": (".context_manager", "ContextWindowManager"),
    "ModelVisibleContext": (".context_microkernel", "ModelVisibleContext"),
    "MemoryStore": (".memory", "MemoryStore"),
    "ModelToolIntelligence": (
        ".model_tool_intelligence",
        "ModelToolIntelligence",
    ),
    "SessionStore": (".session_store", "SessionStore"),
}

__all__ = list(_PUBLIC_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _PUBLIC_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    from .proofs_d_runtime import check_package_export
    check_package_export(name, attribute_name, value)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
