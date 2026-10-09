"""Resource-aware execution profiles for Neyvia Native."""

from __future__ import annotations

import ctypes
import os
import platform
from dataclasses import asdict, dataclass
from typing import Any


RESOURCE_PROFILE_SCHEMA = "neyvia.native-resource-profile/v1"
_VALID_MODES = {"auto", "eco", "balanced", "maximal", "memory-rich"}


@dataclass(frozen=True)
class NativeResourceProfile:
    mode: str
    detected_memory_mb: int
    maximum_turns: int
    tool_catalog_limit: int
    specialist_limit: int
    concurrency_limit: int
    context_budget_bytes: int
    retained_history_items: int
    verification_reserve_turns: int
    low_consumption: bool
    reason: str

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        return {
            "schema": RESOURCE_PROFILE_SCHEMA,
            "mode": value["mode"],
            "detectedMemoryMb": value["detected_memory_mb"],
            "maximumTurns": value["maximum_turns"],
            "toolCatalogLimit": value["tool_catalog_limit"],
            "specialistLimit": value["specialist_limit"],
            "concurrencyLimit": value["concurrency_limit"],
            "contextBudgetBytes": value["context_budget_bytes"],
            "retainedHistoryItems": value["retained_history_items"],
            "verificationReserveTurns": value["verification_reserve_turns"],
            "lowConsumption": value["low_consumption"],
            "reason": value["reason"],
        }


def detected_memory_mb() -> int:
    """Best-effort physical-memory detection without adding a dependency."""

    if os.name == "nt":
        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return max(1, int(status.ullTotalPhys // (1024 * 1024)))
        except (AttributeError, OSError):
            pass
    meminfo = "/proc/meminfo"
    if os.path.isfile(meminfo):
        try:
            with open(meminfo, "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("MemTotal:"):
                        return max(1, int(line.split()[1]) // 1024)
        except (OSError, ValueError, IndexError):
            pass
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return max(1, int(pages * page_size // (1024 * 1024)))
    except (AttributeError, OSError, ValueError):
        pass
    return 0


def normalize_resource_mode(value: object) -> str:
    normalized = str(value or "auto").strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "low": "eco",
        "low-consumption": "eco",
        "efficient": "eco",
        "normal": "balanced",
        "high": "maximal",
        "max": "maximal",
        "rich": "memory-rich",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in _VALID_MODES:
        raise ValueError(
            "resource mode must be auto, eco, balanced, maximal, or memory-rich"
        )
    return normalized


def _auto_mode(memory_mb: int) -> tuple[str, str]:
    if memory_mb and memory_mb < 6 * 1024:
        return "eco", "Detected less than 6 GiB of physical memory."
    if memory_mb and memory_mb >= 48 * 1024:
        return "memory-rich", "Detected at least 48 GiB; retain more local context and cache."
    if memory_mb and memory_mb >= 16 * 1024:
        return "maximal", "Detected at least 16 GiB; allow deeper bounded execution."
    return "balanced", "Use the portable balanced profile for this host."


def resolve_resource_profile(value: object = "auto") -> dict[str, Any]:
    requested = normalize_resource_mode(value)
    return _profile_for_memory(requested, detected_memory_mb())


def _profile_for_memory(requested: str, memory_mb: int) -> dict[str, Any]:
    """Pure resource admission used by detection and scratch calibration alike."""
    mode, reason = _auto_mode(memory_mb) if requested == "auto" else (requested, "Operator-selected resource profile.")
    profiles = {
        "eco": NativeResourceProfile(
            mode="eco",
            detected_memory_mb=memory_mb,
            maximum_turns=8,
            tool_catalog_limit=6,
            specialist_limit=1,
            concurrency_limit=1,
            context_budget_bytes=64 * 1024,
            retained_history_items=24,
            verification_reserve_turns=2,
            low_consumption=True,
            reason=reason,
        ),
        "balanced": NativeResourceProfile(
            mode="balanced",
            detected_memory_mb=memory_mb,
            maximum_turns=16,
            tool_catalog_limit=12,
            specialist_limit=2,
            concurrency_limit=2,
            context_budget_bytes=160 * 1024,
            retained_history_items=64,
            verification_reserve_turns=3,
            low_consumption=False,
            reason=reason,
        ),
        "maximal": NativeResourceProfile(
            mode="maximal",
            detected_memory_mb=memory_mb,
            maximum_turns=32,
            tool_catalog_limit=20,
            specialist_limit=4,
            concurrency_limit=4,
            context_budget_bytes=320 * 1024,
            retained_history_items=128,
            verification_reserve_turns=5,
            low_consumption=False,
            reason=reason,
        ),
        "memory-rich": NativeResourceProfile(
            mode="memory-rich",
            detected_memory_mb=memory_mb,
            maximum_turns=28,
            tool_catalog_limit=20,
            specialist_limit=3,
            concurrency_limit=max(2, min(6, (os.cpu_count() or 2) // 2)),
            context_budget_bytes=768 * 1024,
            retained_history_items=320,
            verification_reserve_turns=5,
            low_consumption=False,
            reason=reason,
        ),
    }
    payload = profiles[mode].public_dict()
    payload["requestedMode"] = requested
    payload["hostPlatform"] = platform.system().lower()
    from .proofs_d_native import check_resource
    check_resource(payload, requested, memory_mb)
    return payload
