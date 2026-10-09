from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .subprocess_utils import hidden_windows_subprocess_kwargs


SELF_REPAIR_JOB_KIND = "app_self_repair"
SELF_REPAIR_REQUEST_SCHEMA = "fluxio.self_repair_request.v1"
SELF_REPAIR_RECEIPT_SCHEMA = "fluxio.self_repair_receipt.v1"
SELF_REPAIR_CAPABILITY = "app.self_repair"
MAX_REPAIR_ATTEMPTS = 3
MAX_PHASE_TIMEOUT_SECONDS = 300
MAX_TRACKED_PATHS = 32
MAX_OUTPUT_CHARS = 4000


class SelfRepairContractError(ValueError):
    """Raised when a repair request cannot be executed safely or deterministically."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _contract_for_job(job: dict[str, Any]) -> dict[str, Any]:
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    contract = payload.get("selfRepair") or payload.get("self_repair")
    return contract if isinstance(contract, dict) else {}


def is_self_repair_job(job: dict[str, Any]) -> bool:
    kind = str(job.get("jobKind") or job.get("job_kind") or "").strip().lower()
    return kind == SELF_REPAIR_JOB_KIND or bool(_contract_for_job(job))


def _command(contract: dict[str, Any], camel_key: str, snake_key: str) -> list[str]:
    raw = contract.get(camel_key)
    if raw is None:
        raw = contract.get(snake_key)
    if not isinstance(raw, list) or not raw:
        raise SelfRepairContractError(f"{camel_key} must be a non-empty argv list.")
    command = [str(item) for item in raw]
    if any(not item.strip() or "\x00" in item for item in command):
        raise SelfRepairContractError(f"{camel_key} contains an invalid argument.")
    return command


def _resolve_inside(workspace: Path, value: object, *, default: str = "") -> Path:
    raw = str(value or default).strip()
    if not raw:
        raise SelfRepairContractError("A workspace-relative path is required.")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise SelfRepairContractError(f"Path escapes the repair workspace: {raw}") from exc
    return resolved


def _hash_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"state": "missing", "sha256": "", "size": 0}
    if not path.is_file():
        return {"state": "not_file", "sha256": "", "size": 0}
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
    except OSError as exc:
        return {"state": "unreadable", "sha256": "", "size": size, "error": str(exc)}
    return {"state": "file", "sha256": digest.hexdigest(), "size": size}


def _tracked_state(workspace: Path, values: object) -> dict[str, dict[str, Any]]:
    if not isinstance(values, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for raw in values[:MAX_TRACKED_PATHS]:
        path = _resolve_inside(workspace, raw)
        relative = path.relative_to(workspace).as_posix()
        result[relative] = _hash_file(path)
    return result


def _run_phase(
    *,
    name: str,
    command: list[str],
    workspace: Path,
    env: dict[str, str],
    timeout_seconds: int,
    attempt: int = 0,
) -> dict[str, Any]:
    started_at = _utc_now()
    started = time.monotonic()
    try:
        completed = subprocess.run(  # noqa: S603
            command,
            cwd=str(workspace),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, int(timeout_seconds)),
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
        return_code = int(completed.returncode)
        stdout = completed.stdout[-MAX_OUTPUT_CHARS:]
        stderr = completed.stderr[-MAX_OUTPUT_CHARS:]
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        return_code = 124
        stdout = str(exc.stdout or "")[-MAX_OUTPUT_CHARS:]
        stderr = str(exc.stderr or "")[-MAX_OUTPUT_CHARS:]
        timed_out = True
    except OSError as exc:
        return_code = 127
        stdout = ""
        stderr = str(exc)[-MAX_OUTPUT_CHARS:]
        timed_out = False
    return {
        "phase": name,
        "attempt": attempt,
        "command": command,
        "ok": return_code == 0,
        "returnCode": return_code,
        "timedOut": timed_out,
        "stdout": stdout,
        "stderr": stderr,
        "startedAt": started_at,
        "completedAt": _utc_now(),
        "durationMs": int((time.monotonic() - started) * 1000),
    }


def _receipt_artifact(path: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifactId": str(receipt["receiptId"]),
        "kind": "self_repair_receipt",
        "path": str(path),
        "metadata": {
            "schema": receipt["schema"],
            "repairId": receipt["repairId"],
            "status": receipt["status"],
            "finalVerificationPassed": bool(
                receipt.get("proof", {}).get("finalVerificationPassed")
            ),
        },
    }


def _phase_event(kind: str, message: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"kind": kind, "message": message, "payload": payload}


def execute_self_repair_job(
    job: dict[str, Any],
    *,
    workspace: Path,
    env: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    """Run a bounded detect -> repair -> verify loop and emit a durable receipt."""

    workspace = workspace.resolve()
    contract = _contract_for_job(job)
    repair_id = str(contract.get("repairId") or contract.get("repair_id") or "").strip()
    repair_id = repair_id or f"repair_{uuid.uuid4().hex[:12]}"
    receipt_id = f"receipt_{uuid.uuid4().hex[:12]}"
    default_receipt = f".agent_control/self_repair_receipts/{repair_id}.json"
    try:
        receipt_path = _resolve_inside(
            workspace,
            contract.get("receiptPath") or contract.get("receipt_path"),
            default=default_receipt,
        )
    except SelfRepairContractError:
        receipt_path = _resolve_inside(workspace, default_receipt)

    started_at = _utc_now()
    phases: list[dict[str, Any]] = []
    phase_events: list[dict[str, Any]] = []
    tracked_before: dict[str, dict[str, Any]] = {}
    tracked_after: dict[str, dict[str, Any]] = {}
    requested_attempts = 0
    max_attempts = 0
    attempts_used = 0
    initial_detection_failed = False
    repair_command_passed = False
    final_verification_passed = False
    status = "blocked"
    outcome = "invalid_contract"
    stop_reason = "invalid_repair_contract"
    detail = "Worker rejected an invalid self-repair contract."
    contract_error = ""

    try:
        if not contract:
            raise SelfRepairContractError("selfRepair contract is required.")
        request_schema = str(contract.get("schema") or "").strip()
        if request_schema and request_schema != SELF_REPAIR_REQUEST_SCHEMA:
            raise SelfRepairContractError(
                f"Unsupported self-repair request schema: {request_schema}"
            )
        detect_command = _command(contract, "detectCommand", "detect_command")
        repair_command = _command(contract, "repairCommand", "repair_command")
        verify_command = _command(contract, "verifyCommand", "verify_command")
        requested_attempts = int(contract.get("maxAttempts") or contract.get("max_attempts") or 1)
        max_attempts = max(1, min(MAX_REPAIR_ATTEMPTS, requested_attempts))
        requested_phase_timeout = int(
            contract.get("phaseTimeoutSeconds")
            or contract.get("phase_timeout_seconds")
            or min(60, timeout_seconds)
        )
        phase_timeout = max(1, min(MAX_PHASE_TIMEOUT_SECONDS, requested_phase_timeout, timeout_seconds))
        tracked_values = contract.get("trackedPaths")
        if tracked_values is None:
            tracked_values = contract.get("tracked_paths")
        tracked_before = _tracked_state(workspace, tracked_values)

        deadline = time.monotonic() + max(1, int(timeout_seconds))

        def run_phase(name: str, command: list[str], *, attempt: int = 0) -> dict[str, Any]:
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                return {
                    "phase": name,
                    "attempt": attempt,
                    "command": command,
                    "ok": False,
                    "returnCode": 124,
                    "timedOut": True,
                    "stdout": "",
                    "stderr": "Self-repair job exhausted its total timeout.",
                    "startedAt": _utc_now(),
                    "completedAt": _utc_now(),
                    "durationMs": 0,
                }
            remaining = max(1, int(remaining_seconds))
            return _run_phase(
                name=name,
                command=command,
                workspace=workspace,
                env=env,
                timeout_seconds=min(phase_timeout, remaining),
                attempt=attempt,
            )

        detection = run_phase("detect", detect_command)
        phases.append(detection)
        initial_detection_failed = not detection["ok"]
        if detection["ok"]:
            final_verification_passed = True
            status = "completed"
            outcome = "already_healthy"
            stop_reason = "health_check_passed"
            detail = "Application was already healthy; no repair action was needed."
            phase_events.append(
                _phase_event(
                    "repair.not_required",
                    detail,
                    {"repairId": repair_id, "returnCode": detection["returnCode"]},
                )
            )
        else:
            phase_events.append(
                _phase_event(
                    "repair.detected",
                    "Worker detected a failing application health check.",
                    {"repairId": repair_id, "returnCode": detection["returnCode"]},
                )
            )
            for attempt in range(1, max_attempts + 1):
                attempts_used = attempt
                repair = run_phase("repair", repair_command, attempt=attempt)
                phases.append(repair)
                repair_command_passed = repair_command_passed or bool(repair["ok"])
                phase_events.append(
                    _phase_event(
                        "repair.applied" if repair["ok"] else "repair.action_failed",
                        (
                            "Worker applied the repair action."
                            if repair["ok"]
                            else "Worker repair action failed."
                        ),
                        {
                            "repairId": repair_id,
                            "attempt": attempt,
                            "returnCode": repair["returnCode"],
                        },
                    )
                )
                if not repair["ok"]:
                    continue
                verification = run_phase("verify", verify_command, attempt=attempt)
                phases.append(verification)
                phase_events.append(
                    _phase_event(
                        "repair.verified" if verification["ok"] else "repair.verification_failed",
                        (
                            "Worker verified that the application is healthy."
                            if verification["ok"]
                            else "Application verification still fails after repair."
                        ),
                        {
                            "repairId": repair_id,
                            "attempt": attempt,
                            "returnCode": verification["returnCode"],
                        },
                    )
                )
                if verification["ok"]:
                    final_verification_passed = True
                    status = "completed"
                    outcome = "repaired"
                    stop_reason = "verification_passed"
                    detail = "Worker repaired the application and passed the post-repair health check."
                    break
            if not final_verification_passed:
                status = "failed"
                outcome = "repair_failed"
                stop_reason = "verification_not_proven"
                detail = (
                    "Worker exhausted the bounded repair attempts without proving "
                    "the application healthy."
                )
        tracked_after = _tracked_state(workspace, tracked_values)
    except (SelfRepairContractError, TypeError, ValueError) as exc:
        contract_error = str(exc)
        phase_events.append(
            _phase_event(
                "repair.contract_blocked",
                detail,
                {"repairId": repair_id, "error": contract_error},
            )
        )

    tracked_changes = sorted(
        path
        for path in set(tracked_before) | set(tracked_after)
        if tracked_before.get(path) != tracked_after.get(path)
    )
    receipt = {
        "schema": SELF_REPAIR_RECEIPT_SCHEMA,
        "receiptId": receipt_id,
        "repairId": repair_id,
        "jobId": str(job.get("jobId") or job.get("job_id") or ""),
        "missionId": str(job.get("missionId") or job.get("mission_id") or ""),
        "workspace": str(workspace),
        "status": status,
        "outcome": outcome,
        "stopReason": stop_reason,
        "detail": detail,
        "startedAt": started_at,
        "completedAt": _utc_now(),
        "bounds": {
            "requestedMaxAttempts": requested_attempts,
            "maxAttempts": max_attempts,
            "hardAttemptCap": MAX_REPAIR_ATTEMPTS,
            "attemptsUsed": attempts_used,
            "totalTimeoutSeconds": max(1, int(timeout_seconds)),
        },
        "proof": {
            "initialDetectionFailed": initial_detection_failed,
            "repairCommandPassed": repair_command_passed,
            "finalVerificationPassed": final_verification_passed,
            "trackedBefore": tracked_before,
            "trackedAfter": tracked_after,
            "trackedPathChanges": tracked_changes,
        },
        "phases": phases,
        "contractError": contract_error,
    }
    from .proofs_e_wz import check_repair
    check_repair(receipt)
    _atomic_write_json(receipt_path, receipt)
    check_repair(receipt, receipt_path)
    artifact = _receipt_artifact(receipt_path, receipt)
    last_phase = phases[-1] if phases else {}
    return {
        "status": status,
        "detail": detail,
        "returnCode": 0 if status == "completed" else (2 if status == "blocked" else 1),
        "stdout": str(last_phase.get("stdout") or "")[-MAX_OUTPUT_CHARS:],
        "stderr": (
            contract_error or str(last_phase.get("stderr") or "")
        )[-MAX_OUTPUT_CHARS:],
        "changedFiles": tracked_changes,
        "artifacts": [artifact],
        "phaseEvents": phase_events,
        "repairReceipt": receipt,
        "repairReceiptPath": str(receipt_path),
    }


def queue_self_repair_job(
    registry: Any,
    *,
    workspace: Path,
    detect_command: list[str],
    repair_command: list[str],
    verify_command: list[str],
    tracked_paths: list[str] | None = None,
    mission_id: str = "",
    workspace_id: str = "",
    repair_id: str = "",
    max_attempts: int = 1,
    phase_timeout_seconds: int = 60,
    total_timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Queue a repair through the normal cluster worker path."""

    resolved_workspace = workspace.expanduser().resolve()
    resolved_repair_id = repair_id or f"repair_{uuid.uuid4().hex[:12]}"
    return registry.upsert_job(
        mission_id=mission_id,
        workspace_id=workspace_id or f"workspace:{resolved_workspace.name}",
        lane_role="repair",
        job_kind=SELF_REPAIR_JOB_KIND,
        required_capabilities=[SELF_REPAIR_CAPABILITY],
        planned_file_scope=list(tracked_paths or ["."]),
        required_artifacts=["self_repair_receipt"],
        payload={
            "executionRoot": str(resolved_workspace),
            "timeoutSeconds": max(1, int(total_timeout_seconds)),
            "selfRepair": {
                "schema": SELF_REPAIR_REQUEST_SCHEMA,
                "repairId": resolved_repair_id,
                "detectCommand": list(detect_command),
                "repairCommand": list(repair_command),
                "verifyCommand": list(verify_command),
                "trackedPaths": list(tracked_paths or []),
                "maxAttempts": int(max_attempts),
                "phaseTimeoutSeconds": int(phase_timeout_seconds),
            },
        },
        status_detail="Application self-repair queued for a bundled worker.",
    )


