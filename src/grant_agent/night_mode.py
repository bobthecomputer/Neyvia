from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
import shutil
import socket
from pathlib import Path
from typing import Any

from .models import NightReadinessReceipt

NIGHT_PRODUCTION_PROFILE_SCHEMA = "fluxio.night_production_profile.v1"
NIGHT_QUEUE_POLICY_SCHEMA = "fluxio.night_queue_policy.v1"
NIGHT_READINESS_FAILURE_MESSAGE_SCHEMA = "fluxio.night_readiness_failure_message.v1"
MORNING_DIGEST_SCHEMA = "fluxio.morning_digest.v1"
NIGHT_READINESS_MIN_FREE_BYTES = 512 * 1024 * 1024
NIGHT_QUEUE_PRIORITY = {
    "blocked_mission_reconciliation": 10,
    "small_repair_loops": 20,
    "headless_executor_work": 30,
    "headless_verifier_work": 40,
    "proof_compaction": 50,
    "morning_digest_generation": 60,
}


@dataclass
class NightProductionProfile:
    schema: str = NIGHT_PRODUCTION_PROFILE_SCHEMA
    profile_id: str = "production_night"
    label: str = "Production night"
    enabled: bool = True
    window_start_local: str = "01:00"
    window_end_local: str = "06:55"
    autopilot: bool = True
    mission_execution_allowed: bool = True
    default_runtime: str = "hermes"
    controller_host_role: str = "nas"
    accelerator_host_role: str = "pc_gateway"
    max_parallel_missions: int = 1
    default_max_repair_loops: int = 1
    resource_policy: str = "low_resource_truthful_progress"
    allowed_work: list[str] = field(default_factory=list)
    deferred_work: list[str] = field(default_factory=list)
    proof_requirements: list[str] = field(default_factory=list)
    next_action: str = (
        "Run night readiness before claiming or launching production missions."
    )


def build_production_night_profile() -> NightProductionProfile:
    return NightProductionProfile(
        allowed_work=[
            "blocked_mission_reconciliation",
            "small_repair_loops",
            "headless_executor_work",
            "headless_verifier_work",
            "proof_compaction",
            "morning_digest_generation",
        ],
        deferred_work=[
            "browser_verification_without_pc_gateway",
            "full_frontend_build_when_nas_pressure_high",
            "destructive_git_actions",
            "package_upgrades_without_explicit_approval",
            "commands_outside_leased_workspace_scope",
        ],
        proof_requirements=[
            "readiness_receipt",
            "plan_receipt",
            "execution_receipt",
            "verification_receipt",
            "changed_file_receipt",
            "command_receipt",
            "artifact_receipt_or_explicit_gap",
            "final_morning_report_row",
        ],
    )


def production_night_profile_payload() -> dict[str, Any]:
    result = asdict(build_production_night_profile())
    from .proofs_d_ui_planning import check_night_profile
    check_night_profile(result)
    return result


def build_night_readiness_receipt(
    *,
    root: str | Path,
    mission_id: str = "night_run",
    host: str = "",
    runtime: str = "hermes",
    runtime_auth_available: bool = False,
    runtime_available: bool = False,
    selected_skills_available: bool = True,
    nas_worker_alive: bool = False,
    desktop_gateway_status: str = "unknown",
    notification_channel: str = "",
    model_key_names: list[str] | None = None,
) -> NightReadinessReceipt:
    root_path = Path(root)
    free_bytes = _free_bytes(root_path)
    checks = {
        "nas_worker_alive": bool(nas_worker_alive),
        "runtime_auth_available": bool(runtime_auth_available),
        "selected_runtime_exists": bool(runtime_available),
        "selected_skills_available": bool(selected_skills_available),
        "workspace_path_exists": root_path.exists(),
        "disk_pressure_safe": free_bytes >= NIGHT_READINESS_MIN_FREE_BYTES,
        "mission_queue_can_run": _mission_queue_can_run(root_path),
        "desktop_gateway_status_known": bool(str(desktop_gateway_status or "").strip()),
        "notification_channel_configured_or_skipped": bool(notification_channel or notification_channel == ""),
    }
    failures = [name for name, passed in checks.items() if not passed]
    warnings: list[str] = []
    if not notification_channel:
        warnings.append("notification_channel_skipped")
    status = "passed" if not failures else "blocked"
    receipt = NightReadinessReceipt(
        receipt_id=f"receipt_night_ready_{mission_id}",
        mission_id=mission_id,
        host=host or socket.gethostname(),
        runtime=runtime,
        workspace=str(root_path),
        status=status,
        summary=(
            "Night run can start."
            if status == "passed"
            else f"Night run did not start because: {', '.join(failures)}."
        ),
        checks=checks,
        masked_keys=_masked_key_status(model_key_names or []),
        failures=failures,
        warnings=warnings,
        desktop_gateway_status=desktop_gateway_status,
        notification_channel=notification_channel or "skipped",
        outputs={
            "freeBytes": free_bytes,
            "minFreeBytes": NIGHT_READINESS_MIN_FREE_BYTES,
            "profile": production_night_profile_payload(),
        },
        next_action=(
            "Claim production night queue work."
            if status == "passed"
            else "Resolve readiness failures before claiming production night queue work."
        ),
    )
    from .proofs_d_ui_planning import check_readiness
    check_readiness(receipt)
    return receipt


def _classify_night_work(kind: str, *, pc_gateway_online: bool = False, nas_pressure_high: bool = False) -> dict[str, Any]:
    profile = build_production_night_profile()
    normalized = str(kind or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized == "browser_verification" and not pc_gateway_online:
        return _classification(normalized, "defer", "Browser verification waits for the PC gateway.")
    if normalized == "full_frontend_build" and nas_pressure_high:
        return _classification(normalized, "defer", "Full frontend builds wait while NAS pressure is high.")
    if normalized in {"destructive_git_action", "package_upgrade", "outside_leased_workspace"}:
        return _classification(normalized, "defer", "This work needs explicit approval or a valid lease.")
    if normalized in set(profile.allowed_work):
        return _classification(normalized, "allow", "Production night profile can run this work with receipts.")
    if normalized in {"browser_verification", "full_frontend_build"}:
        return _classification(normalized, "allow", "Accelerator-capable work can run when capacity permits.")
    return _classification(normalized, "hold", "Unknown night work waits for an explicit queue policy.")


def classify_night_work(kind: str, *, pc_gateway_online: bool = False, nas_pressure_high: bool = False) -> dict[str, Any]:
    result = _classify_night_work(kind, pc_gateway_online=pc_gateway_online, nas_pressure_high=nas_pressure_high)
    from .proofs_d_ui_planning import check_night_policy
    check_night_policy(_normalize_kind(kind), pc_gateway_online, nas_pressure_high, result)
    return result


def rank_night_queue(
    items: list[dict[str, Any]],
    *,
    pc_gateway_online: bool = False,
    nas_pressure_high: bool = False,
) -> dict[str, Any]:
    ranked: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        kind = _normalize_kind(item.get("kind") or item.get("workKind") or "")
        classification = classify_night_work(
            kind,
            pc_gateway_online=pc_gateway_online,
            nas_pressure_high=nas_pressure_high,
        )
        row = {
            "id": str(item.get("id") or item.get("missionId") or item.get("mission_id") or f"night_item_{index}"),
            "kind": kind,
            "missionId": str(item.get("missionId") or item.get("mission_id") or ""),
            "priority": NIGHT_QUEUE_PRIORITY.get(kind, 10_000),
            "decision": classification["decision"],
            "reason": classification["reason"],
            "payload": dict(item),
        }
        if row["decision"] == "allow":
            ranked.append(row)
        elif row["decision"] == "defer":
            deferred.append(row)
        else:
            held.append(row)
    ranked.sort(key=lambda row: (int(row["priority"]), row["id"]))
    result = {
        "schema": NIGHT_QUEUE_POLICY_SCHEMA,
        "ranked": ranked,
        "deferred": deferred,
        "held": held,
        "nextAction": (
            "Claim the first ranked night queue item."
            if ranked
            else "No eligible night queue item is ready; inspect deferred and held work."
        ),
    }
    from .proofs_d_ui_planning import check_night_queue
    check_night_queue(items, result)
    return result


def _build_readiness_failure_message(
    receipt: NightReadinessReceipt | dict[str, Any],
    *,
    receipt_path: str,
    channel: str = "browser_inbox",
) -> dict[str, Any]:
    payload = asdict(receipt) if hasattr(receipt, "__dataclass_fields__") else dict(receipt)
    failures = payload.get("failures") if isinstance(payload.get("failures"), list) else []
    status = str(payload.get("status") or "").strip().lower()
    blocked = status == "blocked" or bool(failures)
    if not blocked:
        return {
            "schema": NIGHT_READINESS_FAILURE_MESSAGE_SCHEMA,
            "status": "skipped",
            "channel": channel,
            "reason": "readiness_passed",
            "receiptPath": receipt_path,
        }
    reason = ", ".join(str(item) for item in failures if str(item or "").strip()) or "readiness_failed"
    return {
        "schema": NIGHT_READINESS_FAILURE_MESSAGE_SCHEMA,
        "status": "action",
        "channel": channel,
        "title": "Night run did not start",
        "body": f"Night run did not start because: {reason}.",
        "receiptPath": receipt_path,
        "missionId": str(payload.get("mission_id") or ""),
        "failureCount": len(failures),
        "failures": failures,
        "nextAction": "Open the readiness receipt, fix the failed checks, then rerun readiness.",
    }


def build_readiness_failure_message(receipt: NightReadinessReceipt | dict[str, Any], *, receipt_path: str, channel: str = "browser_inbox") -> dict[str, Any]:
    result = _build_readiness_failure_message(receipt, receipt_path=receipt_path, channel=channel)
    from .proofs_d_ui_planning import check_notification
    check_notification(asdict(receipt) if hasattr(receipt, "__dataclass_fields__") else receipt, result, receipt_path)
    return result


def build_morning_digest(
    *,
    completed_items: list[str],
    blocked_items: list[str],
    proof_commands: list[str],
    changed_files: list[str],
    nas_sync_status: str,
    first_unchecked_item: str,
    proof_gaps: list[str] | None = None,
    risks: list[str] | None = None,
) -> dict[str, Any]:
    gaps = list(proof_gaps or [])
    return {
        "schema": MORNING_DIGEST_SCHEMA,
        "completedItems": list(completed_items),
        "blockedItems": list(blocked_items),
        "proofGaps": gaps,
        "completedCount": len(completed_items),
        "blockedCount": len(blocked_items),
        "proofGapCount": len(gaps),
        "proofCommands": list(proof_commands),
        "changedFiles": list(changed_files),
        "nasSyncStatus": nas_sync_status,
        "firstUncheckedItem": first_unchecked_item,
        "risks": list(risks or []),
        "summary": (
            f"{len(completed_items)} completed, {len(blocked_items)} blocked, {len(gaps)} proof gaps; "
            f"next item: {first_unchecked_item or 'none'}."
        ),
    }


def write_morning_digest(
    root: str | Path,
    *,
    completed_items: list[str],
    blocked_items: list[str],
    proof_commands: list[str],
    changed_files: list[str],
    nas_sync_status: str,
    first_unchecked_item: str,
    proof_gaps: list[str] | None = None,
    risks: list[str] | None = None,
) -> dict[str, Any]:
    digest = build_morning_digest(
        completed_items=completed_items,
        blocked_items=blocked_items,
        proof_commands=proof_commands,
        changed_files=changed_files,
        nas_sync_status=nas_sync_status,
        first_unchecked_item=first_unchecked_item,
        proof_gaps=proof_gaps,
        risks=risks,
    )
    out_dir = Path(root) / ".agent_control" / "overnight"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "morning_digest_latest.json"
    md_path = out_dir / "morning_digest_latest.md"
    from .durability import atomic_write_json, atomic_write_text
    from .harness_jobs import _exclusive_job_lock
    # The receipt observer reads both files. Keep it within the same crash-safe
    # writer lock so another mission cannot replace either half before validation.
    with _exclusive_job_lock(json_path):
        atomic_write_json(json_path, digest)
        atomic_write_text(md_path, _morning_digest_markdown(digest))
        result = {
            **digest,
            "jsonPath": str(json_path),
            "markdownPath": str(md_path),
        }
        from .proofs_d_ui_planning import check_digest
        check_digest(root, result)
        return result


def _morning_digest_markdown(digest: dict[str, Any]) -> str:
    def section(title: str, values: list[str]) -> str:
        rows = values or ["None"]
        return f"## {title}\n\n" + "\n".join(f"- {item}" for item in rows) + "\n"

    return (
        "# Neyvia Morning Digest\n\n"
        f"Schema: {digest['schema']}\n\n"
        f"Summary: {digest['summary']}\n\n"
        + section("Completed", digest.get("completedItems", []))
        + "\n"
        + section("Blocked", digest.get("blockedItems", []))
        + "\n"
        + section("Proof Gaps", digest.get("proofGaps", []))
        + "\n"
        + section("Proof Commands", digest.get("proofCommands", []))
        + "\n"
        + section("Changed Files", digest.get("changedFiles", []))
        + "\n"
        f"## NAS Sync\n\n{digest.get('nasSyncStatus', '')}\n\n"
        f"## First Unchecked Item\n\n{digest.get('firstUncheckedItem', '')}\n\n"
        + section("Risks", digest.get("risks", []))
    )


def _free_bytes(root: Path) -> int:
    try:
        usage = shutil.disk_usage(root if root.exists() else root.parent)
        return int(usage.free)
    except OSError:
        return 0


def _mission_queue_can_run(root: Path) -> bool:
    try:
        control_dir = root / ".agent_control"
        control_dir.mkdir(parents=True, exist_ok=True)
        return control_dir.is_dir()
    except OSError:
        return False


def _masked_key_status(key_names: list[str]) -> dict[str, str]:
    masked: dict[str, str] = {}
    for name in key_names:
        key = str(name or "").strip()
        if not key:
            continue
        value = os.environ.get(key, "")
        if not value:
            masked[key] = "missing"
        elif len(value) <= 8:
            masked[key] = "***"
        else:
            masked[key] = f"{value[:3]}...{value[-4:]}"
    return masked


def _classification(kind: str, decision: str, reason: str) -> dict[str, Any]:
    return {
        "schema": "fluxio.night_work_classification.v1",
        "kind": kind,
        "decision": decision,
        "reason": reason,
    }


def _normalize_kind(kind: Any) -> str:
    return str(kind or "").strip().lower().replace("-", "_").replace(" ", "_")
