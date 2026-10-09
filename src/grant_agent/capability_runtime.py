"""Permission, preview, and performance runtime for capability plans."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, TypeVar

from .capability_contracts import (
    CAPABILITY_RUN_SCHEMA,
    PermissionDecision,
    PreviewEvent,
    TELEMETRY_RECEIPT_SCHEMA,
    canonical_hash,
    normalized_strings,
    utc_now,
)
from .proofs_a_capabilities import checked_action, check_run_record


T = TypeVar("T")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def process_memory_bytes() -> int | None:
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(
                handle,
                ctypes.byref(counters),
                counters.cb,
            )
            if ok:
                return int(counters.WorkingSetSize)
        except Exception:
            return None
        return None
    try:
        import resource

        maximum_rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return maximum_rss if os.uname().sysname == "Darwin" else maximum_rss * 1024
    except Exception:
        return None


class CapabilityPermissionEngine:
    """Translate profile permission modes into explicit per-action decisions."""

    READ_PERMISSIONS = frozenset(
        {"context.read", "artifact.read", "workspace.read", "network.read"}
    )
    LOCAL_MUTATIONS = frozenset(
        {"artifact.write", "workspace.write", "process.execute"}
    )
    HIGH_RISK = frozenset(
        {
            "secret.use",
            "network.write",
            "external.side_effect",
            "compute.spend",
            "device.control",
            "security.assess",
            "tool.manage",
            "destructive",
        }
    )
    MODE_ALIASES = {
        "strict": "always_ask",
        "tiered": "workspace_safe",
        "hands_free": "autonomous_scoped",
        "guided": "always_ask",
        "default": "workspace_safe",
    }

    def normalize_mode(self, mode: object) -> str:
        normalized = str(mode or "workspace_safe").strip().lower()
        return self.MODE_ALIASES.get(normalized, normalized)

    def decide(
        self,
        permissions: list[str] | tuple[str, ...],
        *,
        mode: str = "workspace_safe",
        approved_permissions: list[str] | tuple[str, ...] | None = None,
        workspace_scoped: bool = True,
    ) -> list[PermissionDecision]:
        normalized_mode = self.normalize_mode(mode)
        approved = {
            item.lower()
            for item in normalized_strings(approved_permissions)
        }
        decisions: list[PermissionDecision] = []
        for raw_permission in normalized_strings(permissions):
            permission = raw_permission.lower()
            if permission in approved:
                decisions.append(
                    PermissionDecision(
                        permission=permission,
                        status="allowed",
                        reason="The user explicitly approved this permission for the run.",
                    )
                )
                continue
            if permission in self.READ_PERMISSIONS:
                decisions.append(
                    PermissionDecision(
                        permission=permission,
                        status="allowed",
                        reason="Read-only context is allowed by the selected permission mode.",
                    )
                )
                continue
            if normalized_mode == "review_only":
                decisions.append(
                    PermissionDecision(
                        permission=permission,
                        status="denied",
                        reason="Review-only mode forbids mutations and execution.",
                    )
                )
                continue
            if permission in self.HIGH_RISK:
                decisions.append(
                    PermissionDecision(
                        permission=permission,
                        status="approval_required",
                        reason="Sensitive, external, paid, or destructive work requires approval.",
                        requires_approval=True,
                    )
                )
                continue
            if permission in self.LOCAL_MUTATIONS:
                if normalized_mode == "always_ask":
                    decisions.append(
                        PermissionDecision(
                            permission=permission,
                            status="approval_required",
                            reason="Always-ask mode requires approval for local changes and execution.",
                            requires_approval=True,
                        )
                    )
                elif not workspace_scoped:
                    decisions.append(
                        PermissionDecision(
                            permission=permission,
                            status="approval_required",
                            reason="The requested action is outside the selected workspace scope.",
                            requires_approval=True,
                        )
                    )
                else:
                    decisions.append(
                        PermissionDecision(
                            permission=permission,
                            status="allowed",
                            reason="The action is scoped to the selected workspace.",
                        )
                    )
                continue
            decisions.append(
                PermissionDecision(
                    permission=permission,
                    status="approval_required",
                    reason="The permission is not covered by a low-risk automatic policy.",
                    requires_approval=True,
                )
            )
        from .proofs_a_capabilities import check_permissions
        check_permissions(self, permissions, mode, approved_permissions, workspace_scoped, decisions)
        return decisions

    def summarize(self, decisions: list[PermissionDecision]) -> dict[str, Any]:
        rows = [item.as_dict() for item in decisions]
        return {
            "modeledPermissions": rows,
            "allowed": [item.permission for item in decisions if item.status == "allowed"],
            "approvalRequired": [
                item.permission
                for item in decisions
                if item.status == "approval_required"
            ],
            "denied": [item.permission for item in decisions if item.status == "denied"],
            "canStart": not any(item.status == "denied" for item in decisions),
            "canRunWithoutApproval": not any(
                item.status != "allowed" for item in decisions
            ),
        }


class CapabilityTelemetryStore:
    """Append-only operation receipts with duration and process memory deltas."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.path = (
            self.root
            / ".agent_control"
            / "mission_artifacts"
            / "capability_os"
            / "telemetry.jsonl"
        )
        self._lock = threading.Lock()

    def record(
        self,
        operation: str,
        *,
        duration_ms: float,
        ok: bool,
        started_memory_bytes: int | None = None,
        finished_memory_bytes: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        receipt = {
            "schema": TELEMETRY_RECEIPT_SCHEMA,
            "receiptId": f"telemetry_{uuid.uuid4().hex}",
            "operation": str(operation or "operation"),
            "ok": bool(ok),
            "durationMs": round(float(duration_ms), 3),
            "startedMemoryBytes": started_memory_bytes,
            "finishedMemoryBytes": finished_memory_bytes,
            "memoryDeltaBytes": (
                None
                if started_memory_bytes is None or finished_memory_bytes is None
                else finished_memory_bytes - started_memory_bytes
            ),
            "metadata": dict(metadata or {}),
            "recordedAt": utc_now(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(receipt, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        return receipt

    def measure(
        self,
        operation: str,
        handler: Callable[[], T],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[T, dict[str, Any]]:
        started_memory = process_memory_bytes()
        started = time.perf_counter()
        ok = False
        try:
            result = handler()
            ok = True
            return result, self.record(
                operation,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                ok=True,
                started_memory_bytes=started_memory,
                finished_memory_bytes=process_memory_bytes(),
                metadata=metadata,
            )
        except Exception:
            self.record(
                operation,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                ok=ok,
                started_memory_bytes=started_memory,
                finished_memory_bytes=process_memory_bytes(),
                metadata=metadata,
            )
            raise

    def recent(self, limit: int = 40) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 500))
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines[-bounded:]:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows


class CapabilityRunStore:
    """Durable plan/live/result preview lifecycle used by workers and the UI."""

    TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.directory = (
            self.root
            / ".agent_control"
            / "mission_artifacts"
            / "capability_os"
            / "runs"
        )
        self._lock = threading.RLock()

    def _path(self, run_id: str) -> Path:
        normalized = str(run_id or "").strip()
        if not normalized or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in normalized):
            raise ValueError("Invalid runId")
        return self.directory / f"{normalized}.json"

    @checked_action(check_run_record)
    def create(
        self,
        plan: dict[str, Any],
        *,
        permission_summary: dict[str, Any],
    ) -> dict[str, Any]:
        plan_id = str(plan.get("planId") or "").strip()
        if not plan_id:
            raise ValueError("planId is required")
        run_id = f"caprun_{uuid.uuid4().hex[:20]}"
        plan_event = PreviewEvent(
            run_id=run_id,
            phase="plan",
            kind="execution_plan",
            summary=str(plan.get("summary") or plan.get("goal") or "Capability plan"),
            payload={
                "planId": plan_id,
                "capabilityIds": list(plan.get("capabilityIds") or []),
                "permissions": permission_summary,
                "estimated": dict(plan.get("estimated") or {}),
            },
        ).as_dict()
        payload = {
            "schema": CAPABILITY_RUN_SCHEMA,
            "runId": run_id,
            "planId": plan_id,
            "planHash": str(plan.get("planHash") or canonical_hash(plan)),
            "status": (
                "awaiting_approval"
                if permission_summary.get("approvalRequired")
                else "ready"
            ),
            "goal": str(plan.get("goal") or ""),
            "capabilityIds": list(plan.get("capabilityIds") or []),
            "permissionSummary": dict(permission_summary),
            "previewEvents": [plan_event],
            "artifactIds": [],
            "createdAt": utc_now(),
            "updatedAt": utc_now(),
            "completedAt": "",
        }
        with self._lock:
            _atomic_json(self._path(run_id), payload)
        return payload

    def get(self, run_id: str) -> dict[str, Any]:
        path = self._path(run_id)
        if not path.exists():
            raise KeyError(f"Unknown capability run: {run_id}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Capability run could not be read: {run_id}") from exc
        if not isinstance(payload, dict) or payload.get("schema") != CAPABILITY_RUN_SCHEMA:
            raise RuntimeError(f"Invalid capability run payload: {run_id}")
        return payload

    @checked_action(check_run_record)
    def append_preview(self, event: PreviewEvent) -> dict[str, Any]:
        with self._lock:
            payload = self.get(event.run_id)
            if payload.get("status") in self.TERMINAL_STATUSES:
                raise RuntimeError("Cannot append preview to a terminal capability run")
            row = event.as_dict()
            payload.setdefault("previewEvents", []).append(row)
            for artifact_id in event.artifact_ids:
                if artifact_id not in payload.setdefault("artifactIds", []):
                    payload["artifactIds"].append(artifact_id)
            if event.phase == "live":
                payload["status"] = "running"
            payload["updatedAt"] = utc_now()
            _atomic_json(self._path(event.run_id), payload)
            return payload

    @checked_action(check_run_record)
    def finish(
        self,
        run_id: str,
        *,
        status: str,
        summary: str,
        payload: dict[str, Any] | None = None,
        artifact_ids: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in self.TERMINAL_STATUSES:
            raise ValueError(f"Unsupported terminal status: {normalized_status}")
        with self._lock:
            current = self.get(run_id)
            if current.get("status") in self.TERMINAL_STATUSES:
                return current
            event = PreviewEvent(
                run_id=run_id,
                phase="result",
                kind=normalized_status,
                summary=str(summary or normalized_status),
                payload=dict(payload or {}),
                artifact_ids=tuple(normalized_strings(artifact_ids)),
            ).as_dict()
            current.setdefault("previewEvents", []).append(event)
            for artifact_id in event["artifactIds"]:
                if artifact_id not in current.setdefault("artifactIds", []):
                    current["artifactIds"].append(artifact_id)
            current["status"] = normalized_status
            current["updatedAt"] = utc_now()
            current["completedAt"] = current["updatedAt"]
            _atomic_json(self._path(run_id), current)
            return current

    def list_runs(self, limit: int = 40) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 200))
        if not self.directory.exists():
            return []
        rows: list[dict[str, Any]] = []
        for path in sorted(
            self.directory.glob("caprun_*.json"),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        )[:bounded]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and payload.get("schema") == CAPABILITY_RUN_SCHEMA:
                rows.append(payload)
        return rows
