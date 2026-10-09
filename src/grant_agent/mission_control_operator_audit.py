"""Operator audit responsibilities for the control room.

Facade-owned collaborators are explicit keyword dependencies so callers retain
the established late-binding and monkeypatch seams.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .models import Mission

def _bootstrap_live_mission_output_quality(
    missions: list[Mission],
    *,
    TERMINAL_MISSION_STATUSES,
) -> dict:
    checked_rows: list[dict] = []
    repair_rows: list[dict] = []
    for mission in missions:
        status = str(mission.state.status or "")
        active = status not in TERMINAL_MISSION_STATUSES and status != "draft"
        failed = status in {"verification_failed", "failed"}
        if not active and not failed:
            continue
        artifact_gate = "missing_required_output" if failed else "unknown"
        transcript_status = "missing_transcript" if failed else "unknown"
        row = {
            "missionId": mission.mission_id,
            "title": mission.title or mission.objective or "Untitled mission",
            "runtime": mission.runtime_id or "unknown",
            "status": status,
            "agentMessageCount": 0,
            "runtimeOutputCount": 0,
            "artifactStatus": "none_returned" if failed else "unknown",
            "artifactGateStatus": artifact_gate,
            "runtimeTranscriptStatus": transcript_status,
            "detail": (
                "Mission is verification_failed in the live summary; runtime transcript/artifact proof must be rechecked before claiming output quality."
                if failed
                else "Mission is active; proof quality must come from the mission detail endpoint or runtime transcript."
            ),
        }
        checked_rows.append(row)
        if failed:
            repair_rows.append(
                {
                    **row,
                    "repairReason": "verification_failed mission needs a hard artifact gate and readable runtime transcript.",
                    "canResumeNow": False,
                    "command": f"Open Agent detail for {mission.mission_id}, then resume only after storage preflight passes.",
                }
            )
    return {
        "schema": "fluxio.live_mission_output_quality.bootstrap.v1",
        "status": "needs_artifact_repair" if repair_rows else "running" if checked_rows else "missing",
        "checkedMissionRows": checked_rows[:12],
        "repairMissionRows": repair_rows[:8],
        "weakMissionCount": len(repair_rows),
        "repairMissionCount": len(repair_rows),
        "nextAction": (
            "Repair verification-failed missions with hard artifact gates once NAS storage clears."
            if repair_rows
            else "Open mission detail rows to keep runtime proof and artifact evidence current."
        ),
    }


def _bootstrap_mission_artifact_repair_plan(
    *,
    live_mission_output_quality: dict,
    nas_storage_pressure: dict,
) -> dict:
    repair_rows = (
        live_mission_output_quality.get("repairMissionRows", [])
        if isinstance(live_mission_output_quality.get("repairMissionRows"), list)
        else []
    )
    probe_failed = bool(nas_storage_pressure.get("probeTimedOut")) or bool(nas_storage_pressure.get("probeConnectFailed"))
    measured_usage_available = bool(nas_storage_pressure.get("measuredUsageAvailable", not probe_failed))
    has_storage_evidence = bool(
        nas_storage_pressure.get("schema")
        or nas_storage_pressure.get("checkedAt")
        or nas_storage_pressure.get("source")
        or str(nas_storage_pressure.get("status") or "").strip()
    )
    storage_blocked = bool(
        has_storage_evidence
        and measured_usage_available
        and (
            str(nas_storage_pressure.get("status") or "").lower() in {"critical", "full"}
            or int(nas_storage_pressure.get("availableBytes") or 0) <= 0
            or int(nas_storage_pressure.get("usedPercent") or 0) >= 99
        )
    )
    return {
        "schema": "fluxio.mission_artifact_repair_plan.bootstrap.v1",
        "status": (
            "repairs_blocked_by_nas_storage"
            if repair_rows and storage_blocked
            else "repairs_ready"
            if repair_rows
            else "no_repairs"
        ),
        "repairMissionCount": len(repair_rows),
        "storagePreflight": {
            "canResume": not storage_blocked,
            "status": nas_storage_pressure.get("status") or "unknown",
            "probeTimedOut": bool(nas_storage_pressure.get("probeTimedOut")),
            "probeConnectFailed": bool(nas_storage_pressure.get("probeConnectFailed")),
            "measuredUsageAvailable": measured_usage_available,
            "availableBytes": int(nas_storage_pressure.get("availableBytes") or 0),
        },
        "repairs": repair_rows,
        "nextAction": (
            "Free NAS write headroom first, then resume failed missions with a hard artifact gate."
            if repair_rows and storage_blocked
            else "Resume failed missions with a hard artifact gate and readable runtime transcript."
            if repair_rows
            else "No artifact repair rows are visible in the bootstrap mission summary."
        ),
    }


def _storage_triage_summary(
    *,
    nas_storage_pressure: dict,
    nas_storage_cleanup_plan: dict,
    platform_config,
) -> dict:
    has_storage_evidence = bool(nas_storage_pressure or nas_storage_cleanup_plan)
    base_handoff = {
        "schema": "fluxio.storage_operator_handoff.v1",
        "status": "operator_review_required",
        "safeToAutoDelete": False,
        "generatedCleanupAvailable": False,
        "generatedCandidateCount": 0,
        "estimatedGeneratedReclaimableMB": 0,
        "largestAccountedPath": "",
        "largestAccountedGB": 0,
        "summary": "No generated Syntelos cleanup candidates are available. Storage recovery requires operator review of non-generated NAS data, snapshots, or Synology accounting.",
        "primaryCommand": "npm run plan:nas-storage-cleanup",
        "adminChecklist": [
            "Do not delete backup bundles, shared folders, or sparsebundle data from Neyvia.",
            "Use Synology Storage Manager, Snapshot Replication, and File Station to identify non-generated usage.",
            "After freeing durable space, replace /tmp recovery symlinks with real release files and rerun authenticated live-control verification.",
        ],
    }
    if not has_storage_evidence:
        return {
            "schema": "fluxio.storage_triage_summary.v1",
            "status": "missing",
            "usedPercent": 0,
            "availableBytes": 0,
            "generatedCandidateCount": 0,
            "estimatedGeneratedReclaimableMB": 0,
            "largestAccountedPath": "",
            "largestAccountedGB": 0,
            "timedOutProbeCount": 0,
            "destructiveActionsExecuted": False,
            "rows": [
                {
                    "id": "storage-evidence-missing",
                    "kind": "missing_live_probe",
                    "severity": "critical",
                    "title": "Storage evidence missing",
                    "detail": "No live NAS storage pressure or cleanup-plan evidence is loaded.",
                    "safeToDelete": False,
                    "nextAction": "Run the NAS storage pressure probe before showing write-headroom status.",
                }
            ],
            "nextAction": "Run live NAS storage pressure verification.",
            "handoff": {
                **base_handoff,
                "summary": "Storage evidence is missing. Run the bounded NAS cleanup planner before any deletion decision.",
            },
        }
    cleanup_rows = (
        nas_storage_cleanup_plan.get("cleanupCandidates", [])
        if isinstance(nas_storage_cleanup_plan.get("cleanupCandidates"), list)
        else []
    )
    volume_rows = (
        nas_storage_cleanup_plan.get("volumeAccountingUsage", [])
        if isinstance(nas_storage_cleanup_plan.get("volumeAccountingUsage"), list)
        else []
    )
    timed_out_external = [
        str(item)
        for item in nas_storage_cleanup_plan.get("timedOutExternalProbePaths", [])
        if str(item or "").strip()
    ]
    timed_out_volume = [
        str(item)
        for item in nas_storage_cleanup_plan.get("timedOutVolumeAccountingPaths", [])
        if str(item or "").strip()
    ]
    btrfs_rows = [
        str(item)
        for item in nas_storage_cleanup_plan.get("btrfsAccounting", [])
        if str(item or "").strip()
    ]
    available_bytes = int(nas_storage_pressure.get("availableBytes") or nas_storage_cleanup_plan.get("availableBytes") or 0)
    used_percent = int(nas_storage_pressure.get("usedPercent") or nas_storage_cleanup_plan.get("usedPercent") or 0)
    status_text = str(nas_storage_pressure.get("status") or nas_storage_cleanup_plan.get("storageStatus") or "").lower()
    probe_failed = bool(nas_storage_pressure.get("probeTimedOut")) or bool(nas_storage_pressure.get("probeConnectFailed"))
    measured_usage_available = bool(nas_storage_pressure.get("measuredUsageAvailable", not probe_failed))
    blocked = bool(
        measured_usage_available
        and (status_text in {"critical", "full"} or available_bytes <= 0 or used_percent >= 99)
    )
    headroom_detail = (
        f"{nas_storage_pressure.get('mount') or nas_storage_cleanup_plan.get('mount') or str(platform_config().nas_volume_root)} "
        "write headroom is unverified because the bounded NAS storage probe did not return current df data."
        if not measured_usage_available or probe_failed
        else (
            f"{nas_storage_pressure.get('mount') or nas_storage_cleanup_plan.get('mount') or str(platform_config().nas_volume_root)} "
            f"is {used_percent}% used with {available_bytes} available bytes."
        )
    )
    rows: list[dict] = [
        {
            "id": "write-headroom",
            "kind": "blocker" if blocked else "headroom",
            "severity": "critical" if blocked else "warn" if probe_failed or not measured_usage_available else "ok",
            "title": "NAS write headroom",
            "detail": headroom_detail,
            "safeToDelete": False,
            "nextAction": (
                "Clear real NAS volume or snapshot space before trusting unattended mission writes."
                if blocked
                else "Rerun the bounded NAS storage probe; this is not a measured full-disk state."
                if probe_failed or not measured_usage_available
                else "Keep the storage pressure probe in the release gate."
            ),
        },
        {
            "id": "generated-cleanup",
            "kind": "generated_cleanup",
            "severity": "ok" if cleanup_rows else "warn",
            "title": "Generated cleanup allowlist",
            "detail": (
                f"{len(cleanup_rows)} candidate(s), "
                f"{nas_storage_cleanup_plan.get('estimatedReclaimableMB', 0)} MB estimated reclaimable."
            ),
            "safeToDelete": bool(cleanup_rows),
            "nextAction": "Only delete rows that remain inside the generated evidence allowlist."
            if cleanup_rows
            else "Do not delete arbitrary NAS data; no generated Syntelos cleanup candidates were found.",
        },
    ]
    for index, row in enumerate(volume_rows[:3]):
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "id": f"volume-accounting-{index}",
                "kind": "operator_review",
                "severity": "high" if index == 0 else "medium",
                "title": str(row.get("path") or "Volume accounting path"),
                "detail": f"{row.get('sizeGB', 0)} GB accounted by bounded probe; not a generated cleanup candidate.",
                "safeToDelete": False,
                "nextAction": "Review in Synology/storage tools before deleting or pruning.",
            }
        )
    if timed_out_external or timed_out_volume:
        rows.append(
            {
                "id": "timed-out-accounting",
                "kind": "needs_deeper_probe",
                "severity": "high",
                "title": "Accounting timed out",
                "detail": f"{len(timed_out_external)} non-generated and {len(timed_out_volume)} volume probe(s) timed out.",
                "safeToDelete": False,
                "nextAction": "Use Synology Storage Analyzer, snapshot tools, or a longer root-authorized read-only probe.",
            }
        )
    if btrfs_rows:
        rows.append(
            {
                "id": "btrfs-accounting",
                "kind": "filesystem_accounting",
                "severity": "high" if blocked else "medium",
                "title": "Btrfs allocation",
                "detail": btrfs_rows[0],
                "safeToDelete": False,
                "nextAction": "Check Synology snapshots/versioning because normal folder totals may not explain allocated data.",
            }
        )
    handoff = {
        **base_handoff,
        "generatedCleanupAvailable": bool(cleanup_rows),
        "generatedCandidateCount": len(cleanup_rows),
        "estimatedGeneratedReclaimableMB": nas_storage_cleanup_plan.get("estimatedReclaimableMB", 0),
        "largestAccountedPath": nas_storage_cleanup_plan.get("largestVolumeAccountingPath") or "",
        "largestAccountedGB": nas_storage_cleanup_plan.get("volumeAccountingGB", 0),
        "summary": (
            f"{len(cleanup_rows)} generated cleanup candidate(s) are allowlisted; review only those paths."
            if cleanup_rows
            else "No generated Syntelos cleanup candidates are available. Storage recovery requires operator review of non-generated NAS data, snapshots, or Synology accounting."
        ),
    }
    return {
        "schema": "fluxio.storage_triage_summary.v1",
        "status": "blocked" if blocked else "ok",
        "measuredUsageAvailable": measured_usage_available,
        "probeTimedOut": bool(nas_storage_pressure.get("probeTimedOut")),
        "probeConnectFailed": bool(nas_storage_pressure.get("probeConnectFailed")),
        "usedPercent": used_percent,
        "availableBytes": available_bytes,
        "generatedCandidateCount": len(cleanup_rows),
        "estimatedGeneratedReclaimableMB": nas_storage_cleanup_plan.get("estimatedReclaimableMB", 0),
        "largestAccountedPath": nas_storage_cleanup_plan.get("largestVolumeAccountingPath") or "",
        "largestAccountedGB": nas_storage_cleanup_plan.get("volumeAccountingGB", 0),
        "timedOutProbeCount": len(timed_out_external) + len(timed_out_volume),
        "destructiveActionsExecuted": bool(nas_storage_cleanup_plan.get("destructiveActionsExecuted")),
        "rows": rows[:8],
        "nextAction": nas_storage_cleanup_plan.get("nextAction")
        or nas_storage_pressure.get("nextAction")
        or "Keep storage triage grounded in bounded live probes.",
        "handoff": handoff,
    }


def _deployment_durability_summary(
    *,
    root: Path,
    nas_storage_pressure: dict,
    storage_triage_summary: dict,
) -> dict:
    inspected_paths = [
        root / "web" / "dist",
        root / "src" / "grant_agent" / "mission_control.py",
        root / "src" / "grant_agent" / "web_backend.py",
        root / ".agent_control" / "start_backend_47880.sh",
    ]
    symlink_rows: list[dict] = []
    for path in inspected_paths:
        try:
            is_symlink = path.is_symlink()
        except OSError:
            is_symlink = False
        if not is_symlink:
            continue
        try:
            target = os.readlink(path)
        except OSError:
            target = ""
        normalized_target = target.replace("\\", "/")
        temporary = normalized_target.startswith("/tmp/") or normalized_target == "/tmp"
        symlink_rows.append(
            {
                "path": str(path),
                "target": target,
                "temporaryTarget": temporary,
                "severity": "critical" if temporary else "medium",
                "detail": (
                    "This active release path resolves through /tmp and will not survive a NAS reboot."
                    if temporary
                    else "This active release path is symlinked; verify the target is durable before release claims."
                ),
            }
        )
    storage_blocked = bool(storage_triage_summary.get("status") == "blocked")
    temporary_symlink_count = sum(1 for row in symlink_rows if row.get("temporaryTarget"))
    status = (
        "temporary_recovery"
        if temporary_symlink_count
        else "storage_blocked"
        if storage_blocked
        else "durable"
    )
    return {
        "schema": "fluxio.deployment_durability_summary.v1",
        "status": status,
        "durable": status == "durable",
        "storageBlocked": storage_blocked,
        "temporarySymlinkCount": temporary_symlink_count,
        "checkedPaths": symlink_rows,
        "headline": (
            "NAS web is running from temporary recovery paths."
            if temporary_symlink_count
            else "NAS web writes are blocked by storage pressure."
            if storage_blocked
            else "NAS web deployment paths appear durable."
        ),
        "nextAction": (
            "Free durable NAS space, replace /tmp symlinks with real release files, restart, then rerun authenticated live-control verification."
            if temporary_symlink_count
            else "Free durable NAS space before publishing another release claim."
            if storage_blocked
            else "Keep deployment receipts current with each release candidate."
        ),
    }


def _red_team_current_cadence_is_healthy(red_summary: dict) -> bool:
    if not isinstance(red_summary, dict):
        return False
    run_count = int(red_summary.get("runCount") or 0)
    satisfied_targets = int(red_summary.get("satisfiedEscalationTargets") or 0)
    latest_resistance = int(red_summary.get("latestResistanceScore") or red_summary.get("resistance_score") or 0)
    current_pressure = int(red_summary.get("currentPressureIndex") or 0)
    next_pressure = int(red_summary.get("nextPressureIndex") or 0)
    pressure_delta = int(red_summary.get("pressureDelta") or max(0, next_pressure - current_pressure))
    next_attempt_budget = int(red_summary.get("nextAttemptBudget") or 0)
    status = str(red_summary.get("status") or "").lower()
    pressure_is_advancing = (
        pressure_delta > 0
        or next_pressure > current_pressure > 0
        or status in {"advancing", "escalating", "passing", "proven"}
    )
    return (
        run_count > 0
        and satisfied_targets > 0
        and bool(red_summary.get("cleanPass"))
        and latest_resistance >= 90
        and next_attempt_budget > 0
        and pressure_is_advancing
    )


def _goal_completion_audit_summary(
    *,
    system_loss_breakdown: dict,
    speed_supervisor_summary: dict,
    design_debt_summary: dict,
    mission_advancement_summary: dict,
    storage_triage_summary: dict,
    deployment_durability_summary: dict,
    public_launch_readiness: dict,
    route_trust: dict,
    red_summary: dict,
    live_progress: dict,
    t3_reference: dict,
    must_beat_status: dict,
    _red_team_current_cadence_is_healthy,
) -> dict:
    rows: list[dict] = []

    def add_row(
        row_id: str,
        *,
        label: str,
        status: str,
        evidence: str,
        next_action: str,
        weight: int = 1,
    ) -> None:
        rows.append(
            {
                "id": row_id,
                "label": label,
                "status": status,
                "evidence": evidence,
                "nextAction": next_action,
                "weight": weight,
            }
        )

    def score_for(status: str) -> float:
        if status == "passed":
            return 1.0
        if status == "partial":
            return 0.55
        if status == "blocked":
            return 0.2
        return 0.0

    deployment_durable = bool(deployment_durability_summary.get("durable"))
    storage_blocked = storage_triage_summary.get("status") == "blocked"
    repair_count = int(mission_advancement_summary.get("repairMissionCount") or 0)
    real_output_count = int(mission_advancement_summary.get("realOutputMissionCount") or 0)
    interface_score = int(design_debt_summary.get("interfaceScoreOutOf20") or 0)
    agent_first_view_proven = bool(design_debt_summary.get("agentFirstViewProofPathPassed"))
    mission_count = int(live_progress.get("missionCount") or mission_advancement_summary.get("missionCount") or 0)
    active_count = int(live_progress.get("activeMissionCount") or 0)
    blocked_count = int(live_progress.get("blockedMissionCount") or 0)
    completed_count = int(live_progress.get("completedMissionCount") or 0)
    t3_ahead = int(must_beat_status.get("ahead") or 0)
    t3_total = int(must_beat_status.get("total") or 0)
    t3_deficits = int(must_beat_status.get("deficitCount") or 0)
    red_run_count = int(red_summary.get("runCount") or 0)
    pending_red_targets = int(red_summary.get("pendingEscalationTargets") or 0)
    red_cadence_healthy = _red_team_current_cadence_is_healthy(red_summary)
    summary_ok = bool(speed_supervisor_summary.get("summaryOk"))
    detail_ok = bool(speed_supervisor_summary.get("detailOk"))
    public_web_ready = str(public_launch_readiness.get("status") or "").lower() in {
        "ready_for_public_launch",
        "ready",
        "pass",
        "passed",
    }

    add_row(
        "system-gap-analysis",
        label="System gap analysis",
        status="passed" if system_loss_breakdown.get("schema") == "fluxio.system_loss_breakdown.v1" else "missing",
        evidence=(
            f"{system_loss_breakdown.get('averageScoreOutOf20', '?')}/20 with "
            f"remaining gap {system_loss_breakdown.get('averageLossOutOf20', '?')}/20."
        ),
        next_action=system_loss_breakdown.get("nextAction")
        or "Keep system-gap rows grounded in live audit evidence.",
        weight=2,
    )
    add_row(
        "speed",
        label="Speed and hot path",
        status="passed" if summary_ok and detail_ok else "partial" if summary_ok or detail_ok else "missing",
        evidence=(
            f"summary {speed_supervisor_summary.get('summaryMaxWallMs', '?')}ms, "
            f"detail {speed_supervisor_summary.get('detailMaxWallMs', '?')}ms."
        ),
        next_action=speed_supervisor_summary.get("nextAction")
        or "Keep summary-first loading and lazy mission detail under budget.",
        weight=2,
    )
    add_row(
        "subagents-harness",
        label="Sub-agents and harness parity",
        status="passed"
        if int(route_trust.get("provenTaskCount") or 0) >= int(route_trust.get("taskCount") or 1)
        else "partial",
        evidence=(
            f"{route_trust.get('provenTaskCount', 0)}/{route_trust.get('taskCount', 0)} "
            f"value-scored route tasks; status {route_trust.get('status', 'unknown')}."
        ),
        next_action=route_trust.get("nextAction")
        or "Keep Hermes planner/executor/verifier lanes value-scored across task categories.",
        weight=2,
    )
    add_row(
        "beginner-interface",
        label="Beginner UX and interface quality",
        status=(
            "passed"
            if design_debt_summary.get("schema")
            and repair_count == 0
            and (interface_score >= 20 or agent_first_view_proven)
            else "partial"
            if design_debt_summary.get("schema")
            else "missing"
        ),
        evidence=(
            (
                "Agent first-view proof path passed; "
                if agent_first_view_proven
                else ""
            )
            + f"Interface {interface_score}/20; "
            f"{design_debt_summary.get('repairMissionCount', 0)} proof repair mission(s)."
        ),
        next_action=(
            "Keep authenticated Agent first-view proof current while closing remaining interface deltas."
            if agent_first_view_proven and interface_score < 20
            else design_debt_summary.get("nextAction")
            or "Reduce concept overload and keep Agent/Workbench thread-first."
        ),
        weight=2,
    )
    add_row(
        "mission-launch-builder",
        label="Mission launch and multi-project Builder",
        status="passed" if int(live_progress.get("missionCount") or 0) > 0 else "missing",
        evidence=(
            f"{live_progress.get('missionCount', 0)} missions, "
            f"{live_progress.get('workspaceCount', 0)} workspaces, "
            f"{live_progress.get('queuedMissionCount', 0)} queued."
        ),
        next_action="Keep queue-first Builder, tutorials, and launch receipts current.",
        weight=2,
    )
    add_row(
        "web-availability",
        label="Web availability and notifications",
        status="passed" if public_web_ready else "partial" if deployment_durable else "blocked",
        evidence=(
            f"Public launch {public_launch_readiness.get('status', 'unknown')}; "
            f"deployment {deployment_durability_summary.get('status', 'unknown')}."
        ),
        next_action=public_launch_readiness.get("nextAction")
        or "Keep authenticated live-control and browser notification proof current.",
        weight=2,
    )
    add_row(
        "deployment-durability",
        label="Unattended operation durability",
        status="passed" if deployment_durable and not storage_blocked else "blocked",
        evidence=(
            f"storage {storage_triage_summary.get('status', 'unknown')}; "
            f"{deployment_durability_summary.get('temporarySymlinkCount', 0)} temporary release path(s)."
        ),
        next_action=deployment_durability_summary.get("nextAction")
        or storage_triage_summary.get("nextAction")
        or "Prove durable release files before unattended operation claims.",
        weight=3,
    )
    add_row(
        "storage-write-headroom",
        label="NAS write headroom",
        status="blocked" if storage_blocked else "passed",
        evidence=(
            f"{storage_triage_summary.get('usedPercent', 0)}% used; "
            f"{storage_triage_summary.get('availableBytes', 0)} available bytes."
        ),
        next_action=storage_triage_summary.get("nextAction")
        or "Keep public and private web proofs current.",
        weight=2,
    )
    add_row(
        "t3-comparison",
        label="T3 Code comparison",
        status="passed" if t3_total and t3_deficits == 0 else "partial" if t3_total else "missing",
        evidence=(
            f"{t3_ahead}/{t3_total or '?'} categories ahead; "
            f"latest reference {t3_reference.get('latestObservedRelease', 'unknown')}."
        ),
        next_action="Close every remaining T3 deficit before claiming objective completion.",
        weight=2,
    )
    add_row(
        "mission-output-quality",
        label="Real mission results and proof",
        status=(
            "blocked"
            if repair_count
            else "passed"
            if real_output_count > 0 or completed_count > 0
            else "partial"
            if active_count or mission_count > 0
            else "missing"
        ),
        evidence=(
            f"{active_count} active, {completed_count} completed, {blocked_count} blocked, "
            f"{real_output_count} real-output proof mission(s), {repair_count} artifact repair mission(s)."
        ),
        next_action=mission_advancement_summary.get("nextAction")
        or "Repair failed F1/artifact missions and keep RF/public-data output producing real transcripts.",
        weight=3,
    )
    add_row(
        "red-team-escalation",
        label="Red-team self-improvement",
        status=(
            "passed"
            if red_run_count > 0 and (pending_red_targets == 0 or red_cadence_healthy)
            else "partial"
            if pending_red_targets
            else "missing"
        ),
        evidence=(
            f"{red_summary.get('runCount', 0)} rows; pressure "
            f"{red_summary.get('currentPressureIndex', 0)} -> {red_summary.get('nextPressureIndex', 0)}; "
            f"next {red_summary.get('nextAttemptBudget', 0)} attempts."
        ),
        next_action=red_summary.get("nextAction")
        or "Run the next harder red-team benchmark and compare defensive deltas.",
        weight=2,
    )
    weighted_total = sum(int(row.get("weight") or 1) for row in rows) or 1
    weighted_score = sum(score_for(str(row.get("status") or "")) * int(row.get("weight") or 1) for row in rows)
    percent = int(round((weighted_score / weighted_total) * 100))
    blocked_rows = [row for row in rows if row.get("status") == "blocked"]
    partial_rows = [row for row in rows if row.get("status") == "partial"]
    missing_rows = [row for row in rows if row.get("status") == "missing"]
    attention_rows = blocked_rows or partial_rows or missing_rows
    status = "blocked" if blocked_rows else "partial" if partial_rows or missing_rows else "complete"
    return {
        "schema": "fluxio.goal_completion_audit.v1",
        "status": status,
        "completionPercent": percent,
        "passedCount": sum(1 for row in rows if row.get("status") == "passed"),
        "partialCount": len(partial_rows),
        "missingCount": len(missing_rows),
        "blockedCount": len(blocked_rows),
        "requirementCount": len(rows),
        "rows": rows,
        "topBlocker": attention_rows[0] if attention_rows else {},
        "nextAction": (
            blocked_rows[0]["nextAction"]
            if blocked_rows
            else partial_rows[0]["nextAction"]
            if partial_rows
            else missing_rows[0]["nextAction"]
            if missing_rows
            else "All objective requirements are currently proven."
        ),
    }


def _local_live_mission_output_quality(
    root: Path,
    *,
    _load_json_file,
) -> dict:
    detail_status = _load_json_file(root / ".agent_control" / "live_mission_detail_status_latest.json")
    if not isinstance(detail_status, dict) or detail_status.get("schema") != "fluxio.live_mission_detail_status.v1":
        return {}
    checked_at = str(detail_status.get("checkedAt") or "")
    rows: list[dict] = []
    repair_rows: list[dict] = []
    for item in detail_status.get("missionRows", []) if isinstance(detail_status.get("missionRows"), list) else []:
        if not isinstance(item, dict):
            continue
        gate = item.get("artifactGate") if isinstance(item.get("artifactGate"), dict) else {}
        transcript = item.get("runtimeTranscript") if isinstance(item.get("runtimeTranscript"), dict) else {}
        runtime_outputs = int(gate.get("runtimeOutputCount") or 0)
        artifact_count = int(gate.get("artifactCount") or 0)
        gate_status = str(gate.get("status") or "")
        transcript_status = str(transcript.get("status") or "")
        status = str(item.get("status") or "")
        artifact_status = "reported" if artifact_count > 0 or gate_status == "passed" and runtime_outputs > 0 else "none_returned"
        row = {
            "missionId": str(item.get("missionId") or ""),
            "title": str(item.get("title") or "Untitled mission"),
            "runtime": str(item.get("runtime") or "unknown"),
            "status": status,
            "checkedAt": checked_at,
            "reportPath": str(root / ".agent_control" / "live_mission_detail_status_latest.json"),
            "screenshotPath": "",
            "agentMessageCount": int(item.get("agentMessages") or 0),
            "runtimeOutputCount": runtime_outputs,
            "artifactStatus": artifact_status,
            "weakOutput": False,
            "artifactGateStatus": gate_status,
            "runtimeTranscriptStatus": transcript_status,
            "detail": "Local live mission detail status loaded because the authoritative NAS audit snapshot omitted mission-output quality evidence.",
        }
        rows.append(row)
        needs_repair = (
            status in {"verification_failed", "failed"}
            or gate_status == "missing_required_output"
            or (runtime_outputs <= 0 and transcript_status == "missing_transcript")
        )
        if needs_repair:
            repair_rows.append(row)
    return {
        "schema": "fluxio.live_mission_output_quality.v1",
        "checkedAt": checked_at,
        "status": "needs_artifact_repair" if repair_rows else "ok" if rows else "missing",
        "reportCount": len(rows),
        "liveDetailStatusPath": str(root / ".agent_control" / "live_mission_detail_status_latest.json"),
        "weakMissionRows": [],
        "repairMissionRows": repair_rows,
        "checkedMissionRows": rows,
        "weakMissionCount": len(repair_rows),
        "repairMissionCount": len(repair_rows),
        "nextAction": (
            "Repair failed missions with hard artifact gates once storage preflight allows writes."
            if repair_rows
            else "Keep active missions producing visible runtime output and artifacts."
        ),
    }


def _design_debt_summary(
    *,
    categories: list[dict],
    deficits: list[dict],
    bad_first: list,
    system_loss_breakdown: dict,
    live_mission_output_quality: dict,
    mission_artifact_repair_plan: dict,
    nas_storage_pressure: dict,
    agent_proof_bundle: dict | None = None,
    _system_improvement_next_action,
) -> dict:
    """Compact operator-facing UI/design debt so Builder does not bury it in long audit rows."""

    by_category = {
        str(item.get("category") or ""): item
        for item in categories
        if isinstance(item, dict)
    }
    interface = by_category.get("Interface clarity and operator ergonomics", {})
    launch = by_category.get("Launch friction and beginner experience", {})
    web = by_category.get("Web availability and distribution", {})
    repair_rows = (
        mission_artifact_repair_plan.get("repairs", [])
        if isinstance(mission_artifact_repair_plan.get("repairs"), list)
        else []
    )
    live_repair_rows = (
        live_mission_output_quality.get("repairMissionRows", [])
        if isinstance(live_mission_output_quality.get("repairMissionRows"), list)
        else []
    )
    repair_count = int(
        mission_artifact_repair_plan.get("repairMissionCount")
        or len(repair_rows)
        or live_mission_output_quality.get("repairMissionCount")
        or len(live_repair_rows)
        or live_mission_output_quality.get("weakMissionCount")
        or 0
    )
    storage_probe_failed = bool(nas_storage_pressure.get("probeTimedOut")) or bool(nas_storage_pressure.get("probeConnectFailed"))
    storage_measured_usage_available = bool(nas_storage_pressure.get("measuredUsageAvailable", not storage_probe_failed))
    storage_has_evidence = bool(
        nas_storage_pressure.get("schema")
        or nas_storage_pressure.get("checkedAt")
        or nas_storage_pressure.get("source")
        or str(nas_storage_pressure.get("status") or "").strip()
    )
    storage_blocked = bool(
        storage_has_evidence
        and storage_measured_usage_available
        and (
            str(nas_storage_pressure.get("status") or "").lower() in {"critical", "full"}
            or int(nas_storage_pressure.get("availableBytes") or 0) <= 0
            or int(nas_storage_pressure.get("usedPercent") or 0) >= 99
        )
    )
    rows: list[dict] = []

    def add_row(
        row_id: str,
        *,
        title: str,
        status: str,
        severity: str,
        detail: str,
        next_action: str,
        score: int | None = None,
    ) -> None:
        rows.append(
            {
                "id": re.sub(r"[^a-z0-9_:-]+", "-", row_id.lower()).strip("-") or f"row-{len(rows) + 1}",
                "title": title,
                "status": status,
                "severity": severity,
                "detail": detail,
                "nextAction": next_action,
                "scoreOutOf20": score,
            }
        )

    interface_score = int(interface.get("fluxioScore") or 0)
    launch_score = int(launch.get("fluxioScore") or 0)
    web_score = int(web.get("fluxioScore") or 0)
    agent_proof_bundle = agent_proof_bundle if isinstance(agent_proof_bundle, dict) else {}
    agent_first_view_proven = bool(agent_proof_bundle.get("firstViewProofPathPassed"))
    first_view_row_count = int(agent_proof_bundle.get("firstViewProofPathRowCount") or 0)
    first_view_next_action_count = int(agent_proof_bundle.get("firstViewProofPathNextActionCount") or 0)
    add_row(
        "interface-clarity",
        title="Agent and Workbench clarity",
        status="needs_repair" if repair_count else "watch",
        severity="high" if repair_count else "medium",
        detail=str(
            "Authenticated Agent first view exposes dialogue, transcript, proof, and next action."
            if agent_first_view_proven
            else interface.get("blockingGap")
            or "Agent/Workbench should show real mission thread, artifact proof, and next repair action without hunting."
        ),
        next_action=str(
            "Keep authenticated first-view proof fresh and close remaining T3 interface deltas."
            if agent_first_view_proven
            else interface.get("nextAction") or "Carry Builder focus/full clarity into Agent and Workbench."
        ),
        score=interface_score or None,
    )
    add_row(
        "launch-experience",
        title="Launch and onboarding",
        status="storage_limited" if storage_blocked else "ready_for_more_proof",
        severity="high" if storage_blocked else "medium",
        detail=str(
            launch.get("blockingGap")
            or "Beginner launch should stay one-field, copyable, and browser-verified."
        ),
        next_action=str(launch.get("nextAction") or "Keep beginner launch proof current and prefer local fallback when NAS is full."),
        score=launch_score or None,
    )
    if web_score:
        add_row(
            "web-mobile-notifications",
            title="Web, mobile, and notifications",
            status="nas_limited" if storage_blocked else "needs_delivery_proof",
            severity="medium",
            detail=str(web.get("blockingGap") or "The web/PWA shell exists, but operator trust depends on fresh delivery receipts."),
            next_action=str(web.get("nextAction") or "Keep Pages, release, and notification receipts current."),
            score=web_score,
        )
    if repair_count:
        first = repair_rows[0] if repair_rows and isinstance(repair_rows[0], dict) else live_repair_rows[0] if live_repair_rows and isinstance(live_repair_rows[0], dict) else {}
        add_row(
            "mission-proof-repairs",
            title="Real mission messages and artifacts",
            status="blocked" if storage_blocked else "repair_ready",
            severity="critical" if storage_blocked else "high",
            detail=(
                f"{repair_count} mission(s) need hard artifact-gate repair; first "
                f"`{first.get('missionId', '')}` has `{first.get('runtimeTranscriptStatus', first.get('artifactGateStatus', 'missing'))}` evidence."
            ),
            next_action=str(
                mission_artifact_repair_plan.get("nextAction")
                or live_mission_output_quality.get("nextAction")
                or "Resume failed missions only with concrete runtime output and artifact proof."
            ),
        )
    for item in bad_first:
        if not isinstance(item, dict):
            continue
        text = f"{item.get('title', '')} {item.get('detail', '')}".lower()
        if not any(token in text for token in ("ui", "interface", "agent", "workbench", "launch", "beginner", "notification", "message")):
            continue
        add_row(
            f"bad-first-{item.get('title', '')}",
            title=str(item.get("title") or "Operator experience gap"),
            status="open",
            severity="high",
            detail=str(item.get("detail") or ""),
            next_action=_system_improvement_next_action(str(item.get("title") or ""), str(item.get("detail") or "")),
        )
        if len(rows) >= 5:
            break

    worst = "critical" if any(row["severity"] == "critical" for row in rows) else "high" if any(row["severity"] == "high" for row in rows) else "medium"
    next_action = rows[0]["nextAction"] if rows else "Keep design debt tied to live mission proof."
    return {
        "schema": "fluxio.design_debt_summary.v1",
        "status": worst,
        "headline": (
            "Design debt is blocked by mission proof and NAS write reliability."
            if repair_count and storage_blocked
            else "Design debt is mostly clarity and proof surfacing."
            if repair_count
            else "Design debt is in watch mode."
        ),
        "interfaceScoreOutOf20": interface_score,
        "launchScoreOutOf20": launch_score,
        "webScoreOutOf20": web_score,
        "agentFirstViewProofPathPassed": agent_first_view_proven,
        "agentFirstViewProofPathRowCount": first_view_row_count,
        "agentFirstViewProofPathNextActionCount": first_view_next_action_count,
        "repairMissionCount": repair_count,
        "nasStorageBlocked": storage_blocked,
        "rows": rows[:5],
        "nextAction": next_action,
        "source": "system_audit_digest",
    }


def _mission_advancement_summary(
    *,
    live_mission_output_quality: dict,
    mission_artifact_repair_plan: dict,
    live_progress: dict,
) -> dict:
    checked_rows = (
        live_mission_output_quality.get("checkedMissionRows", [])
        if isinstance(live_mission_output_quality.get("checkedMissionRows"), list)
        else []
    )
    repair_rows = (
        mission_artifact_repair_plan.get("repairs", [])
        if isinstance(mission_artifact_repair_plan.get("repairs"), list)
        else []
    )
    evidence_screenshots_by_mission = {
        str(row.get("missionId") or row.get("mission_id") or ""): str(row.get("sourceScreenshotPath") or "")
        for row in repair_rows
        if isinstance(row, dict) and str(row.get("sourceScreenshotPath") or "").strip()
    }
    rows: list[dict] = []
    seen: set[str] = set()

    def row_health(row: dict, *, source: str) -> str:
        gate = str(row.get("artifactGateStatus") or "").lower()
        transcript = str(row.get("runtimeTranscriptStatus") or "").lower()
        outputs = int(row.get("runtimeOutputCount") or row.get("observedRuntimeOutputCount") or 0)
        artifacts = str(row.get("artifactStatus") or row.get("observedArtifactStatus") or "").lower()
        status = str(row.get("status") or "").lower()
        if source == "mission_artifact_repair_plan":
            return "needs_artifact_repair"
        if gate == "missing_required_output" or "missing" in transcript and outputs <= 0:
            return "needs_artifact_repair"
        if outputs > 0 or artifacts in {"reported", "served", "path"} or gate == "passed":
            return "real_output_visible"
        if status in {"running", "launching"}:
            return "running_needs_output"
        return "unknown"

    def add(row: dict, *, source: str) -> None:
        mission_id = str(row.get("missionId") or row.get("mission_id") or "").strip()
        if not mission_id or mission_id in seen:
            return
        seen.add(mission_id)
        health = row_health(row, source=source)
        evidence_screenshot_path = (
            str(row.get("sourceScreenshotPath") or row.get("screenshotPath") or "")
            or evidence_screenshots_by_mission.get(mission_id, "")
        )
        rows.append(
            {
                "missionId": mission_id,
                "title": str(row.get("title") or "Untitled mission"),
                "runtime": str(row.get("runtime") or "unknown"),
                "status": str(row.get("status") or "unknown"),
                "health": health,
                "agentMessageCount": int(row.get("agentMessageCount") or row.get("observedAgentMessageCount") or 0),
                "runtimeOutputCount": int(row.get("runtimeOutputCount") or row.get("observedRuntimeOutputCount") or 0),
                "artifactStatus": str(row.get("artifactStatus") or row.get("observedArtifactStatus") or ""),
                "artifactGateStatus": str(row.get("artifactGateStatus") or ""),
                "runtimeTranscriptStatus": str(row.get("runtimeTranscriptStatus") or ""),
                "detail": str(row.get("detail") or row.get("repairReason") or ""),
                "evidenceScreenshotPath": evidence_screenshot_path,
                "proofStateLabel": (
                    "screenshot proof attached"
                    if evidence_screenshot_path
                    else "no screenshot proof"
                    if health == "needs_artifact_repair"
                    else "runtime proof visible"
                    if health == "real_output_visible"
                    else "proof pending"
                ),
                "source": source,
            }
        )

    for row in checked_rows:
        if isinstance(row, dict):
            add(row, source="live_mission_output_quality")
    for row in repair_rows:
        if isinstance(row, dict):
            add(row, source="mission_artifact_repair_plan")

    rows.sort(
        key=lambda item: (
            0 if item["health"] == "needs_artifact_repair" else 1 if item["health"] == "running_needs_output" else 2,
            item["title"],
        )
    )
    real_count = sum(1 for row in rows if row["health"] == "real_output_visible")
    repair_count = sum(1 for row in rows if row["health"] == "needs_artifact_repair")
    return {
        "schema": "fluxio.mission_advancement_summary.v1",
        "status": "needs_repair" if repair_count else "running" if rows else "missing",
        "missionCount": int(live_progress.get("missionCount") or len(rows)),
        "activeMissionCount": int(live_progress.get("activeMissionCount") or 0),
        "realOutputMissionCount": real_count,
        "repairMissionCount": repair_count,
        "rows": rows[:8],
        "nextAction": (
            "Repair failed missions with hard artifact gates once NAS storage clears."
            if repair_count
            else "Keep active missions producing visible runtime output and artifacts."
        ),
    }


def _operator_next_path_summary(
    *,
    storage_triage_summary: dict,
    mission_advancement_summary: dict,
    mission_artifact_repair_plan: dict,
    deficits: list,
    public_launch_readiness: dict,
    route_trust: dict,
) -> dict:
    storage_blocked = str(storage_triage_summary.get("status") or "").lower() in {"blocked", "critical"}
    repair_count = int(mission_advancement_summary.get("repairMissionCount") or 0)
    real_output_count = int(mission_advancement_summary.get("realOutputMissionCount") or 0)
    first_repair = next(
        (
            row
            for row in mission_advancement_summary.get("rows", [])
            if isinstance(row, dict) and row.get("health") == "needs_artifact_repair"
        ),
        {},
    )
    first_deficit = next((row for row in deficits if isinstance(row, dict)), {})
    public_ok = bool(public_launch_readiness.get("ok"))
    operator_confidence = int(route_trust.get("operatorConfidenceScore") or 0)

    steps: list[dict] = []

    steps.append(
        {
            "id": "storage-preflight",
            "label": "Storage",
            "status": "blocked" if storage_blocked else "ready",
            "title": "Clear NAS write headroom" if storage_blocked else "NAS write preflight is clear",
            "detail": (
                storage_triage_summary.get("nextAction")
                or "NAS storage must be checked before trusting unattended mission writes."
            )
            if storage_blocked
            else "Mission writes can proceed without the current storage preflight blocking them.",
            "action": (
                "Review non-generated NAS data, snapshots, or Synology storage accounting before deleting anything."
                if storage_blocked
                else "Keep storage pressure checks fresh before launching NAS-backed missions."
            ),
            "command": "npm run plan:nas-storage-cleanup",
            "blocksLaunch": storage_blocked,
        }
    )

    steps.append(
        {
            "id": "mission-proof-repair",
            "label": "Mission proof",
            "status": "blocked" if storage_blocked and repair_count else "open" if repair_count else "ready",
            "title": (
                f"Repair {repair_count} mission proof gate{'' if repair_count == 1 else 's'}"
                if repair_count
                else f"{real_output_count} mission proof row{'' if real_output_count == 1 else 's'} visible"
            ),
            "detail": (
                first_repair.get("detail")
                or mission_artifact_repair_plan.get("nextAction")
                or "Failed missions need runtime-output and artifact evidence before they count."
            )
            if repair_count
            else "Current mission advancement rows include runtime proof or artifact evidence.",
            "action": (
                "Use the evidence screenshot, then resume with the hard artifact gate after storage clears."
                if repair_count
                else "Keep Agent and Workbench tied to the live mission detail endpoint."
            ),
            "command": "npm run repair:mission-artifacts",
            "missionId": str(first_repair.get("missionId") or ""),
            "blocksLaunch": bool(repair_count and storage_blocked),
        }
    )

    steps.append(
        {
            "id": "t3-parity",
            "label": "T3 parity",
            "status": "open" if first_deficit else "ready",
            "title": str(first_deficit.get("category") or "Tracked categories are above the T3 reference"),
            "detail": str(
                first_deficit.get("blockingGap")
                or first_deficit.get("nextAction")
                or "Keep the public T3 comparison evidence fresh and value-scored."
            ),
            "action": str(
                first_deficit.get("nextAction")
                or "Run the next value-scored route-trust sample and refresh the T3 benchmark."
            ),
            "command": "npm run benchmark:t3-code",
            "blocksLaunch": False,
        }
    )

    steps.append(
        {
            "id": "beginner-launch-proof",
            "label": "Launch proof",
            "status": "ready" if public_ok and not storage_blocked else "blocked" if storage_blocked else "open",
            "title": "Run beginner launch proof on a safe target",
            "detail": (
                "Public launch proof is present; keep beginner launch and authenticated live checks fresh."
                if public_ok
                else public_launch_readiness.get("nextAction")
                or "Public/beginner launch proof is not current."
            ),
            "action": (
                "Use local-workspace quickstart while NAS writes are blocked; do not start NAS-backed unattended work."
                if storage_blocked
                else "Run beginner launch verification and authenticated Agent proof after the next mission."
            ),
            "command": "npm run verify:beginner-launch",
            "blocksLaunch": storage_blocked,
        }
    )

    blockers = [step for step in steps if step.get("blocksLaunch")]
    open_steps = [step for step in steps if step.get("status") in {"open", "blocked"}]
    return {
        "schema": "fluxio.operator_next_path.v1",
        "status": "blocked" if blockers else "open" if open_steps else "ready",
        "headline": (
            "Unattended NAS work is blocked; follow the proof-first path."
            if blockers
            else "Next operator path is ready for guided launch."
            if not open_steps
            else "Finish the remaining proof and parity steps before calling the system done."
        ),
        "operatorConfidenceScore": operator_confidence,
        "stepCount": len(steps),
        "blockedStepCount": len(blockers),
        "steps": steps,
        "nextAction": steps[0]["action"] if blockers else steps[0]["action"] if steps else "",
    }


def _mission_gap_signal(mission: Mission) -> str:
    text = " ".join(
        [
            mission.title or "",
            mission.objective or "",
            mission.workspace_id or "",
        ]
    ).lower()
    if "fusion" in text:
        return "Harness and self-improvement"
    if any(token in text for token in ("builder", "phone", "tablet", "frontend", "progress")) or re.search(r"\bui\b", text):
        return "Beginner UX and Builder"
    if any(token in text for token in ("public-data", "investigation", "research", "rf", "wireless", "geoint")):
        return "Multi-project discovery"
    if any(token in text for token in ("harness", "sub-agent", "sub agent", "watchdog")):
        return "Harness and self-improvement"
    if any(token in text for token in ("red team", "red-team", "security", "defensive")):
        return "Red-team calibration"
    return "Route-trust sampling"


def _t3_code_reference_snapshot(
    root: Path,
    *,
    _load_json_file,
) -> dict:
    benchmark = _load_json_file(root / ".agent_control" / "t3_code_benchmark_latest.json")
    if not isinstance(benchmark, dict):
        return {
            "name": "T3 Code",
            "latestObservedRelease": (
                "T3 Code benchmark has not been refreshed in this workspace yet."
            ),
            "source": "",
        }
    stable = benchmark.get("latestStable") if isinstance(benchmark.get("latestStable"), dict) else {}
    prerelease = (
        benchmark.get("latestPrerelease")
        if isinstance(benchmark.get("latestPrerelease"), dict)
        else {}
    )
    observed = str(benchmark.get("latestObservedRelease") or "").strip()
    if not observed:
        observed = (
            f"{stable.get('tag', 'unknown stable')} stable published "
            f"{stable.get('publishedAt', 'unknown')}; "
            f"{prerelease.get('tag', 'unknown pre-release')} pre-release published "
            f"{prerelease.get('publishedAt', 'unknown')}"
        )
    product_page = benchmark.get("productPageEvidence") if isinstance(benchmark.get("productPageEvidence"), dict) else {}
    verified_claims = product_page.get("verifiedClaims") if isinstance(product_page.get("verifiedClaims"), list) else []
    return {
        "name": "T3 Code",
        "latestObservedRelease": observed,
        "stableTag": str(stable.get("tag") or ""),
        "stableUrl": str(stable.get("url") or ""),
        "prereleaseTag": str(prerelease.get("tag") or ""),
        "prereleaseUrl": str(prerelease.get("url") or ""),
        "checkedAt": str(benchmark.get("checkedAt") or ""),
        "source": str(benchmark.get("source") or ""),
        "productPageSource": str(product_page.get("source") or ""),
        "verifiedClaims": [str(item) for item in verified_claims[:8]],
    }


def _severity_label(value: int) -> str:
    if value >= 75:
        return "critical"
    if value >= 50:
        return "high"
    if value >= 25:
        return "medium"
    return "low"


def _system_loss_breakdown(
    *,
    categories: list[dict],
    deficits: list[dict],
    score_cap_reason: str,
    route_trust: dict,
    red_summary: dict,
    release: dict,
    live_progress: dict,
    nas_storage_pressure: dict | None = None,
    live_mission_output_quality: dict | None = None,
    _red_team_current_cadence_is_healthy,
    _severity_label,
    platform_config,
) -> dict:
    drivers: list[dict] = []
    seen: set[str] = set()
    scored_categories = [
        item
        for item in categories
        if isinstance(item, dict)
        and str(item.get("category") or "").strip()
        and item.get("fluxioScore") is not None
        and str(item["fluxioScore"]).strip() != ""
    ]
    category_scores = [
        max(0.0, min(20.0, float(item.get("fluxioScore") or 0)))
        for item in scored_categories
    ]
    average_score = round(sum(category_scores) / max(len(category_scores), 1), 1) if category_scores else 0.0
    average_loss = round(max(0.0, 20.0 - average_score), 1)
    ahead_count = sum(
        1
        for item in scored_categories
        if float(item.get("fluxioScore") or 0) > float(item.get("t3Score") or 0)
    )

    def add_driver(
        driver_id: str,
        *,
        title: str,
        lane: str,
        severity: int,
        detail: str,
        next_action: str,
        evidence: str,
    ) -> None:
        normalized_id = re.sub(r"[^a-z0-9_:-]+", "-", driver_id.lower()).strip("-")
        if not normalized_id or normalized_id in seen:
            return
        seen.add(normalized_id)
        capped = max(0, min(100, int(severity)))
        drivers.append(
            {
                "id": normalized_id,
                "title": title,
                "category": title,
                "lane": lane,
                "loss": capped,
                "lossOutOf20": round(capped / 100 * 20, 1),
                "severity": _severity_label(capped),
                "primaryGap": detail,
                "detail": detail,
                "nextAction": next_action,
                "evidence": evidence,
            }
        )

    for item in deficits[:5]:
        if not isinstance(item, dict):
            continue
        fluxio_score = int(item.get("fluxioScore") or 0)
        t3_score = int(item.get("t3Score") or 0)
        delta = int(item.get("delta") or (fluxio_score - t3_score))
        severity = min(100, max(35, (20 - fluxio_score) * 5 + abs(delta) * 8))
        title = str(item.get("category") or "T3 parity gap")
        add_driver(
            f"t3-{title}",
            title=title,
            lane="T3 parity",
            severity=severity,
            detail=str(item.get("blockingGap") or score_cap_reason or "Neyvia is not ahead of T3 in this category yet."),
            next_action=str(item.get("nextAction") or "Close this category before claiming full parity."),
            evidence=f"Neyvia {fluxio_score}/20 versus T3 {t3_score}/20.",
        )

    missing_value_samples = int(route_trust.get("missingOperatorValueSamples") or 0)
    if missing_value_samples > 0:
        add_driver(
            "route-trust-missing-value-samples",
            title="Route trust is under-sampled",
            lane="Harness routing",
            severity=min(100, 30 + missing_value_samples * 6),
            detail=score_cap_reason or "Live task routes still need operator value-scored closeouts.",
            next_action=str(route_trust.get("nextAction") or route_trust.get("nextRepairStep") or "Run value-scored route trust missions."),
            evidence=(
                f"{int(route_trust.get('provenTaskCount') or 0)}/"
                f"{int(route_trust.get('taskCount') or 0)} task categories proven; "
                f"{missing_value_samples} value samples missing."
            ),
        )

    gate_summary = release.get("requiredGateSummary") if isinstance(release.get("requiredGateSummary"), dict) else {}
    missing_gates = max(
        0,
        int(gate_summary.get("total") or 0) - int(gate_summary.get("passed") or 0),
    )
    if missing_gates > 0:
        add_driver(
            "release-gates-not-green",
            title="Release proof is incomplete",
            lane="Release proof",
            severity=min(100, 35 + missing_gates * 12),
            detail="Release/distribution trust still depends on required proof gates.",
            next_action="Attach public or signed release proof archives and rerun the release verifier.",
            evidence=(
                f"{int(gate_summary.get('passed') or 0)}/"
                f"{int(gate_summary.get('total') or 0)} required gates passing."
            ),
        )

    pending_red_targets = int(red_summary.get("pendingEscalationTargets") or 0)
    next_attempt_budget = int(red_summary.get("nextAttemptBudget") or 0)
    if pending_red_targets > 0 or next_attempt_budget > 0:
        red_cadence_healthy = _red_team_current_cadence_is_healthy(red_summary)
        add_driver(
            "red-team-escalation-pressure",
            title=(
                "Red-team maintenance is scheduled"
                if red_cadence_healthy
                else "Red-team difficulty must keep rising"
            ),
            lane="Self-improvement",
            severity=0
            if red_cadence_healthy
            else min(100, 38 + pending_red_targets * 14 + max(0, next_attempt_budget - 3) * 2),
            detail=(
                "Current clean red-team cadence is healthy; the next harder benchmark is scheduled as maintenance, not a product blocker."
                if red_cadence_healthy
                else "Defensive improvement is only meaningful if the next benchmark becomes harder after clean passes."
            ),
            next_action=str(red_summary.get("nextAction") or "Run the next aggregate-only red-team benchmark."),
            evidence=(
                f"{int(red_summary.get('runCount') or 0)} history rows; "
                f"difficulty {int(red_summary.get('latestDifficultyLevel') or 0)} -> "
                f"{int(red_summary.get('nextDifficultyLevel') or 0)}; "
                f"next attempts {next_attempt_budget}."
            ),
        )

    active_count = int(live_progress.get("activeMissionCount") or 0)
    mission_count = int(live_progress.get("missionCount") or 0)
    queued_count = int(live_progress.get("queuedMissionCount") or 0)
    attention_count = int(live_progress.get("attentionMissionCount") or 0)
    blocked_count = int(live_progress.get("blockedMissionCount") or 0)
    completed_count = int(live_progress.get("completedMissionCount") or 0)
    zero_active_queue_ready = (
        active_count == 0
        and queued_count == 0
        and attention_count == 0
        and blocked_count == 0
        and mission_count > 0
        and completed_count > 0
        and (
            bool(live_progress.get("zeroActiveQueueHealthy"))
            or bool(live_progress.get("schedulerQueueProofPassed"))
        )
    )
    if mission_count > 0 and active_count == 0 and not zero_active_queue_ready:
        add_driver(
            "no-active-live-missions",
            title="No active live missions",
            lane="Builder operations",
            severity=45,
            detail="The system cannot prove ongoing hands-free operation without an active mission row.",
            next_action="Launch or resume at least one live Hermes mission and keep its detail endpoint visible.",
            evidence=f"{mission_count} missions, {active_count} active.",
        )

    storage = nas_storage_pressure or {}
    storage_probe_failed = bool(storage.get("probeTimedOut")) or bool(storage.get("probeConnectFailed"))
    storage_measured_usage_available = bool(storage.get("measuredUsageAvailable", not storage_probe_failed))
    storage_has_evidence = bool(
        storage.get("schema")
        or storage.get("checkedAt")
        or storage.get("source")
        or str(storage.get("status") or "").strip()
    )
    if storage and storage_has_evidence and storage_measured_usage_available and (
        str(storage.get("status") or "").lower() in {"critical", "full"}
        or int(storage.get("availableBytes") or 0) <= 0
        or int(storage.get("usedPercent") or 0) >= 99
    ):
        add_driver(
            "nas-storage-pressure",
            title="NAS storage pressure",
            lane="System reliability",
            severity=92,
            detail="The NAS volume has no safe write headroom for mission logs, proof artifacts, or self-improvement receipts.",
            next_action=str(
                storage.get("nextAction")
                or "Free NAS volume or Synology snapshot space, then rerun storage verification."
            ),
            evidence=(
                f"{storage.get('mount', str(platform_config().nas_volume_root))} "
                f"{int(storage.get('usedPercent') or 0)}% used; "
                f"{int(storage.get('availableBytes') or 0)} available bytes."
            ),
        )

    output_quality = live_mission_output_quality or {}
    weak_rows = (
        output_quality.get("weakMissionRows", [])
        if isinstance(output_quality.get("weakMissionRows"), list)
        else []
    )
    if weak_rows:
        first = weak_rows[0] if isinstance(weak_rows[0], dict) else {}
        add_driver(
            "mission-output-artifact-proof",
            title="Mission output proof",
            lane="Mission quality",
            severity=72,
            detail="Completed Hermes missions can still look successful while only producing transcript rows and no served artifact/runtime-output body.",
            next_action=str(
                output_quality.get("nextAction")
                or "Repair transcript-only missions with a hard served-artifact gate."
            ),
            evidence=(
                f"{len(weak_rows)} weak mission output(s); first "
                f"{first.get('missionId', '')} {first.get('title', '')}."
            ),
        )

    if not drivers:
        add_driver(
            "keep-sampling",
            title="Keep sampling live outcomes",
            lane="System quality",
            severity=12,
            detail="No critical gap driver is visible in the current digest.",
            next_action="Keep value-scored missions, release proof, and red-team escalation current.",
            evidence="All tracked T3 categories are currently above the reference.",
        )

    drivers.sort(key=lambda item: (-int(item.get("loss") or 0), str(item.get("title") or "")))
    score = max(int(item.get("loss") or 0) for item in drivers) if drivers else 0
    return {
        "schema": "fluxio.system_loss_breakdown.v1",
        "averageScoreOutOf20": average_score,
        "averageLossOutOf20": average_loss,
        "mustBeatStatus": {
            "ahead": ahead_count,
            "total": len(scored_categories),
            "deficitCount": len(deficits),
        },
        "score": score,
        "severity": _severity_label(score),
        "driverCount": len(drivers),
        "drivers": drivers[:8],
        "nextAction": str(
            drivers[0].get("nextAction")
            if drivers
            else "Keep value-scored missions, release proof, and red-team escalation current."
        ),
    }



__all__ = [
    "_bootstrap_live_mission_output_quality",
    "_bootstrap_mission_artifact_repair_plan",
    "_storage_triage_summary",
    "_deployment_durability_summary",
    "_red_team_current_cadence_is_healthy",
    "_goal_completion_audit_summary",
    "_local_live_mission_output_quality",
    "_design_debt_summary",
    "_mission_advancement_summary",
    "_operator_next_path_summary",
    "_mission_gap_signal",
    "_t3_code_reference_snapshot",
    "_severity_label",
    "_system_loss_breakdown",
]
