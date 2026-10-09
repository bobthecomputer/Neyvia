from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .mission_control import (
    ControlRoomStore,
    build_red_team_escalation_snapshot,
    build_harness_lab_snapshot,
    build_release_readiness_snapshot,
    build_summary_harness_lab_snapshot,
)
from .delivery_receipt import ntfy_status, web_push_status
from .demo_runner import build_red_team_escalation_audit, build_red_team_escalation_trend, normalize_red_team_pressure
from .onboarding import detect_onboarding_status, invalidate_onboarding_status_cache
from .platform_config import platform_config


def _default_nas_mount_label() -> str:
    return str(platform_config().nas_volume_root)


T3_CODE_BENCHMARK = {
    "name": "T3 Code",
    "referenceDate": "2026-06-02",
    "sources": [
        "https://t3.codes/",
        "https://github.com/pingdotgg/t3code",
        "https://github.com/pingdotgg/t3code/releases",
    ],
    "latestObservedRelease": "v0.0.24 stable published 2026-05-15T06:39:44Z; v0.0.25-nightly.20260602.439 pre-release published 2026-06-02T08:05:20Z",
    "observedStrengths": [
        "web GUI for coding agents",
        "officially positions itself around Claude Code, Codex CLI, OpenCode, and Cursor from one surface",
        "BYO subscription model with no additional quota caps",
        "supports starting from existing projects or fresh projects",
        "mid-thread model switching and a roadmap for more agents and providers",
        "worktrees, one-click PR creation, and diff review are core public promises",
        "low-friction `npx t3` launch plus Windows, macOS, and Linux package paths remain the launch bar to beat",
        "provider connections and perceived UI speed are core product strengths",
        "open-source MIT TypeScript monorepo with desktop, web, server, and harness packages",
    ],
    "observedWeaknesses": [
        "early project that tells users to expect bugs",
        "depends on external agent CLIs being installed and authenticated",
        "not focused on multi-project NAS-first autonomous operations",
        "public promises emphasize coding-agent orchestration more than durable mission proof, watchdog repair, or route-trust learning",
    ],
}

T3_CHAT_BENCHMARK = {
    "name": "T3 Chat",
    "referenceDate": "2026-05-29",
    "sources": [
        "https://t3.chat/faq",
        "https://github.com/TGlide/thom-chat",
    ],
    "observedStrengths": [
        "fast web-first multi-model chat experience",
        "new-chat URL parameters for q, model, effort, search, profile, and temporary mode",
        "clean model switching and low-friction chat creation",
        "T3-style clones show expected features such as streaming, search, sharing, branches, BYOK, and keyboard shortcuts",
    ],
    "observedWeaknesses": [
        "chat-first rather than agent-supervision-first",
        "single-threaded usage is a known limitation for comparison workflows",
        "does not replace a durable mission-control plane by itself",
    ],
}


def _load_t3_code_benchmark(root: Path) -> dict[str, Any]:
    benchmark = dict(T3_CODE_BENCHMARK)
    path = root / ".agent_control" / "t3_code_benchmark_latest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return benchmark
    if not isinstance(payload, dict):
        return benchmark
    latest_observed = str(payload.get("latestObservedRelease") or "").strip()
    if latest_observed:
        benchmark["latestObservedRelease"] = latest_observed
    benchmark["releaseEvidence"] = {
        "schema": payload.get("schema", ""),
        "checkedAt": payload.get("checkedAt", ""),
        "source": payload.get("source", ""),
        "releaseCount": payload.get("releaseCount", 0),
        "latestStable": payload.get("latestStable", {}),
        "latestPrerelease": payload.get("latestPrerelease", {}),
        "evidencePath": str(path.resolve()),
    }
    product_page_evidence = payload.get("productPageEvidence", {})
    if isinstance(product_page_evidence, dict):
        benchmark["productPageEvidence"] = product_page_evidence
    return benchmark


def _t3_code_reference_note(t3_code: dict[str, Any]) -> str:
    latest = str(t3_code.get("latestObservedRelease") or "").strip()
    release_evidence = (
        t3_code.get("releaseEvidence", {})
        if isinstance(t3_code.get("releaseEvidence"), dict)
        else {}
    )
    checked_at = str(release_evidence.get("checkedAt") or "").strip()
    evidence_suffix = f" Evidence refreshed at `{checked_at}`." if checked_at else ""
    product_page = (
        t3_code.get("productPageEvidence", {})
        if isinstance(t3_code.get("productPageEvidence"), dict)
        else {}
    )
    product_source = str(product_page.get("source") or "").strip()
    product_checked = str(product_page.get("checkedAt") or "").strip()
    verified_claim_count = int(product_page.get("verifiedClaimCount") or 0)
    product_suffix = ""
    if product_source and product_page.get("ok"):
        product_suffix = (
            f" Product-page evidence from `{product_source}` verified {verified_claim_count} "
            f"current public positioning claim(s)"
            + (f" at `{product_checked}`." if product_checked else ".")
        )
    observed = latest or "no refreshed release evidence is available yet"
    return (
        f"- T3 Code reference: current release evidence observes `{observed}` from the official "
        "GitHub releases feed; the official positioning emphasizes a web GUI for Claude Code, "
        "Codex CLI, OpenCode, Cursor, BYO subscriptions, worktrees, diff review, and one-click "
        f"PR creation.{evidence_suffix}{product_suffix}"
    )


@dataclass(frozen=True)
class AuditCategory:
    category: str
    score_out_of_20: int
    t3_reference_score_out_of_20: int
    verdict: str
    evidence: list[str]
    gaps: list[str]
    next_moves: list[str]


def _score_aware_t3_verdict(item: AuditCategory) -> str:
    delta = item.score_out_of_20 - item.t3_reference_score_out_of_20
    if delta > 0:
        return item.verdict
    gap = item.gaps[0] if item.gaps else item.verdict
    if delta == 0:
        return f"At T3 parity but not above it yet: {gap}"
    return f"Behind T3 by {abs(delta)} point(s): {gap}"


def _audit_category_payload(item: AuditCategory) -> dict[str, Any]:
    payload = asdict(item)
    payload["rawVerdict"] = item.verdict
    payload["verdict"] = _score_aware_t3_verdict(item)
    payload["t3Delta"] = item.score_out_of_20 - item.t3_reference_score_out_of_20
    return payload


def _release_readiness_gate(release: dict[str, Any], gate_id: str) -> dict[str, Any]:
    gates = release.get("gates", []) if isinstance(release.get("gates"), list) else []
    for gate in gates:
        if isinstance(gate, dict) and gate.get("gateId") == gate_id:
            return gate
    return {}


def _release_readiness_timestamp(release: dict[str, Any]) -> float:
    candidates = [
        str(release.get("calculatedAt") or ""),
        str(release.get("checkedAt") or ""),
        str(release.get("generatedAt") or ""),
        str(release.get("sourceCheckedAt") or ""),
    ]
    gate = _release_readiness_gate(release, "mission_watchdog_clear")
    candidates.extend(
        [
            str(gate.get("lastRunAt") or ""),
            str(gate.get("nextRunAt") or ""),
        ]
    )
    return max((_parse_iso_timestamp(value) for value in candidates), default=0.0)


def _release_watchdog_needs_local_refresh(
    *,
    local_release: dict[str, Any],
    synced_release: dict[str, Any],
) -> bool:
    local_gate = _release_readiness_gate(local_release, "mission_watchdog_clear")
    if not local_gate:
        return False
    synced_gate = _release_readiness_gate(synced_release, "mission_watchdog_clear")
    active_count = int(local_gate.get("activeMissionCount") or 0)
    if active_count <= 0:
        return False
    if not synced_gate:
        return True
    for field in ("supervisorStale", "supervisorProcessAlive", "supervisorActive"):
        if field in local_gate and field not in synced_gate:
            return True
    if local_gate.get("supervisorStale") is False and synced_gate.get("supervisorStale") is True:
        return True
    if local_gate.get("supervisorActive") is True and synced_gate.get("supervisorActive") is False:
        return True
    if local_gate.get("supervisorProcessAlive") is True and synced_gate.get("supervisorProcessAlive") is False:
        return True
    local_watchdog_ts = max(
        _parse_iso_timestamp(str(local_gate.get("lastRunAt") or "")),
        _parse_iso_timestamp(str(local_gate.get("nextRunAt") or "")),
    )
    synced_watchdog_ts = max(
        _parse_iso_timestamp(str(synced_gate.get("lastRunAt") or "")),
        _parse_iso_timestamp(str(synced_gate.get("nextRunAt") or "")),
    )
    return local_watchdog_ts > synced_watchdog_ts


def _required_release_gates_all_passed(release: dict[str, Any]) -> bool:
    summary = release.get("requiredGateSummary") if isinstance(release.get("requiredGateSummary"), dict) else {}
    total = int(summary.get("total") or 0)
    if total > 0:
        return int(summary.get("passed") or 0) == total
    required_gates = [
        gate
        for gate in release.get("gates", [])
        if isinstance(gate, dict) and bool(gate.get("required"))
    ]
    return bool(required_gates) and all(bool(gate.get("passed")) for gate in required_gates)


def _release_failed_required_gate_ids(release: dict[str, Any]) -> list[str]:
    return [
        str(gate.get("gateId") or "")
        for gate in release.get("gates", [])
        if isinstance(gate, dict)
        and bool(gate.get("required"))
        and not bool(gate.get("passed"))
    ]


def _live_nas_release_overrides_blocked_local_watchdog(
    *,
    local_release: dict[str, Any],
    synced_release: dict[str, Any],
    live_nas_system_audit: dict[str, Any],
) -> bool:
    if live_nas_system_audit.get("status") != "passed":
        return False
    if not isinstance(synced_release, dict) or not synced_release.get("status"):
        return False
    if int(synced_release.get("score") or 0) < max(85, int(local_release.get("score") or 0)):
        return False
    if not _required_release_gates_all_passed(synced_release):
        return False
    failed_required = [item for item in _release_failed_required_gate_ids(local_release) if item]
    if failed_required != ["mission_watchdog_clear"]:
        return False
    local_gate = _release_readiness_gate(local_release, "mission_watchdog_clear")
    synced_gate = _release_readiness_gate(synced_release, "mission_watchdog_clear")
    if bool(local_gate.get("passed")) or not bool(synced_gate.get("passed")):
        return False
    return bool(live_nas_system_audit.get("checkedAt") or synced_release.get("calculatedAt"))


def _live_nas_quality_supersedes_partial_local_release(
    *,
    local_release: dict[str, Any],
    synced_release: dict[str, Any],
    live_nas_system_audit: dict[str, Any],
) -> bool:
    if live_nas_system_audit.get("status") != "passed":
        return False
    if not isinstance(synced_release, dict) or not synced_release.get("status"):
        return False
    if not _required_release_gates_all_passed(synced_release):
        return False
    local_quality = int(local_release.get("qualityScore") or 0)
    synced_quality = int(synced_release.get("qualityScore") or 0)
    if synced_quality < 80 or local_quality >= 80 or synced_quality <= local_quality:
        return False
    if int(synced_release.get("score") or 0) < int(local_release.get("score") or 0):
        return False
    local_proof = local_release.get("proofReadiness") if isinstance(local_release.get("proofReadiness"), dict) else {}
    synced_proof = synced_release.get("proofReadiness") if isinstance(synced_release.get("proofReadiness"), dict) else {}
    local_missions = int(local_proof.get("missionCount") or 0)
    synced_missions = int(synced_proof.get("missionCount") or 0)
    local_completed = sum(
        int(value or 0)
        for value in (
            local_proof.get("runtimeCompletionCounts", {})
            if isinstance(local_proof.get("runtimeCompletionCounts"), dict)
            else {}
        ).values()
    )
    synced_completed = sum(
        int(value or 0)
        for value in (
            synced_proof.get("runtimeCompletionCounts", {})
            if isinstance(synced_proof.get("runtimeCompletionCounts"), dict)
            else {}
        ).values()
    )
    if synced_missions <= local_missions and synced_completed <= local_completed:
        return False
    return bool(live_nas_system_audit.get("checkedAt") or synced_release.get("calculatedAt"))


def _select_system_audit_release_readiness(
    *,
    local_release: dict[str, Any],
    synced_release: dict[str, Any],
    live_nas_system_audit: dict[str, Any],
) -> dict[str, Any]:
    if _live_nas_release_overrides_blocked_local_watchdog(
        local_release=local_release,
        synced_release=synced_release,
        live_nas_system_audit=live_nas_system_audit,
    ):
        return {
            **synced_release,
            "source": "live_nas_system_audit",
            "sourcePath": str(live_nas_system_audit.get("sourcePath") or ""),
            "sourceCheckedAt": str(live_nas_system_audit.get("checkedAt") or ""),
            "localReleaseReadinessSuperseded": local_release,
            "localWatchdogDriftSuperseded": True,
        }
    if _live_nas_quality_supersedes_partial_local_release(
        local_release=local_release,
        synced_release=synced_release,
        live_nas_system_audit=live_nas_system_audit,
    ):
        return {
            **synced_release,
            "source": "live_nas_system_audit",
            "sourcePath": str(live_nas_system_audit.get("sourcePath") or ""),
            "sourceCheckedAt": str(live_nas_system_audit.get("checkedAt") or ""),
            "localReleaseReadinessSuperseded": local_release,
            "localQualityMetricsSuperseded": True,
        }
    if (
        live_nas_system_audit.get("status") == "passed"
        and isinstance(synced_release, dict)
        and synced_release.get("status")
        and int(synced_release.get("score") or 0) >= int(local_release.get("score") or 0)
        and not _release_watchdog_needs_local_refresh(
            local_release=local_release,
            synced_release=synced_release,
        )
        and _release_readiness_timestamp(synced_release) >= _release_readiness_timestamp(local_release)
    ):
        return {
            **synced_release,
            "source": "live_nas_system_audit",
            "sourcePath": str(live_nas_system_audit.get("sourcePath") or ""),
            "sourceCheckedAt": str(live_nas_system_audit.get("checkedAt") or ""),
            "localReleaseReadinessSuperseded": local_release,
        }
    if isinstance(synced_release, dict) and synced_release.get("status"):
        return {
            **local_release,
            "source": str(local_release.get("source") or "local_release_readiness"),
            "syncedReleaseReadinessSuperseded": {
                **synced_release,
                "sourcePath": str(live_nas_system_audit.get("sourcePath") or ""),
                "sourceCheckedAt": str(live_nas_system_audit.get("checkedAt") or ""),
            },
            "newerLocalReleaseReadinessPreserved": True,
        }
    return local_release


def build_system_audit(root: Path) -> dict[str, Any]:
    root = root.resolve()
    invalidate_onboarding_status_cache(root)
    snapshot: dict[str, Any]
    mission_store_rows: list[Any] = []
    try:
        store = ControlRoomStore(root)
        mission_store_rows = store.load_missions()
        snapshot = store.build_snapshot()
    except Exception as exc:  # pragma: no cover - defensive report path
        snapshot = {"error": f"{type(exc).__name__}: {exc}"}

    onboarding = detect_onboarding_status(root, force=True)
    setup_health = onboarding.get("setupHealth", {})
    raw_harness_lab = snapshot.get("harnessLab") or build_harness_lab_snapshot(root)
    harness_lab = raw_harness_lab
    try:
        summary_harness_lab = build_summary_harness_lab_snapshot(
            root,
            missions=mission_store_rows,
        )
    except Exception:  # pragma: no cover - audit must still render if mission rows fail
        summary_harness_lab = {}
    summary_efficiency = (
        summary_harness_lab.get("efficiency", {})
        if isinstance(summary_harness_lab, dict)
        else {}
    )
    if int(summary_efficiency.get("totalRuns") or 0) > 0:
        harness_lab = {
            **summary_harness_lab,
            "source": "mission_store_delegated_sessions_summary_for_release_audit",
            "rawAgentRunHarnessLab": raw_harness_lab,
        }
    release = build_release_readiness_snapshot(
        root,
        onboarding=onboarding,
        setup_health=setup_health,
        harness_lab=harness_lab,
    )
    live_nas_system_audit = _load_live_nas_system_audit_evidence(root)
    synced_release = live_nas_system_audit.get("releaseReadiness", {})
    release = _select_system_audit_release_readiness(
        local_release=release,
        synced_release=synced_release if isinstance(synced_release, dict) else {},
        live_nas_system_audit=live_nas_system_audit,
    )
    live_nas_evidence = _freshen_live_nas_evidence(root, _load_live_nas_evidence(root))
    synced_live_nas = live_nas_system_audit.get("liveNasEvidence", {})
    if isinstance(synced_live_nas, dict) and synced_live_nas.get("status") == "passed":
        live_nas_evidence = _merge_synced_live_nas_evidence(
            live_nas_evidence,
            synced_live_nas,
            system_audit_path=str(live_nas_system_audit.get("sourcePath") or ""),
            system_audit_checked_at=str(live_nas_system_audit.get("checkedAt") or ""),
        )
    live_detail_performance = _load_live_mission_detail_performance_evidence(root)
    nas_storage_pressure = _load_nas_storage_pressure_evidence(root)
    nas_storage_cleanup_plan = _load_nas_storage_cleanup_plan(root)
    mission_artifact_repair_plan = _load_mission_artifact_repair_plan(root)
    live_mission_output_quality = _effective_live_mission_output_quality(
        _load_live_mission_output_quality_evidence(root),
        mission_artifact_repair_plan,
    )
    live_cross_category_outcome_validation = _live_cross_category_outcome_validation(live_mission_output_quality)
    self_improvement_evidence = _load_json(
        root / ".agent_control" / "self_improvement_evidence" / "latest.json",
        {},
    )
    public_launch_readiness = _load_public_launch_readiness_evidence(root)
    project_progress = _project_progress(root, snapshot, live_nas_evidence=live_nas_evidence)
    route_trust_sampling = _load_route_trust_sampling_evidence(root)
    route_trust_closeout = _load_route_trust_sampling_closeout_evidence(root)
    route_trust_loop = _load_route_trust_sampling_loop_evidence(root)
    route_trust_maturity = _route_trust_maturity_snapshot(
        harness_lab,
        snapshot=snapshot,
        live_nas_evidence=live_nas_evidence,
        sampling=route_trust_sampling,
        closeout=route_trust_closeout,
        loop=route_trust_loop,
    )
    synced_route_trust = live_nas_system_audit.get("routeTrustMaturity", {})
    if (
        live_nas_system_audit.get("status") == "passed"
        and isinstance(synced_route_trust, dict)
        and synced_route_trust.get("schema") == "fluxio.operator_confidence_calibration.v1"
    ):
        route_trust_maturity = _merge_synced_route_trust_maturity(
            synced_route_trust,
            local_route_trust_maturity=route_trust_maturity,
            closeout_review=route_trust_closeout,
            source_path=str(live_nas_system_audit.get("sourcePath") or ""),
            source_checked_at=str(live_nas_system_audit.get("checkedAt") or ""),
        )
    red_team_escalation = _red_team_escalation_evidence(
        root,
        snapshot=snapshot,
        live_nas_system_audit=live_nas_system_audit,
    )
    categories = _calibrate_category_scores(
        _score_categories(
            root,
            snapshot,
            release,
            setup_health,
            harness_lab,
            route_trust_maturity=route_trust_maturity,
            nas_storage_pressure=nas_storage_pressure,
            live_mission_output_quality=live_mission_output_quality,
            mission_artifact_repair_plan=mission_artifact_repair_plan,
        ),
        release=release,
        live_nas_evidence=live_nas_evidence,
        route_trust_maturity=route_trust_maturity,
        live_detail_performance=live_detail_performance,
        live_mission_output_quality=live_mission_output_quality,
    )
    t3_deficits = _t3_deficits(categories)
    system_loss_breakdown = _system_loss_breakdown(
        categories,
        release,
        project_progress,
        nas_storage_pressure=nas_storage_pressure,
        nas_storage_cleanup_plan=nas_storage_cleanup_plan,
        live_mission_output_quality=live_mission_output_quality,
        mission_artifact_repair_plan=mission_artifact_repair_plan,
    )
    improvement_queue = _improvement_queue(
        categories,
        release,
        system_loss_breakdown=system_loss_breakdown,
    )
    active_gap_missions = _active_gap_missions(project_progress)
    bad_first = _bad_first(
        categories,
        release,
        project_progress,
        red_team_escalation,
        route_trust_maturity=route_trust_maturity,
        nas_storage_pressure=nas_storage_pressure,
        nas_storage_cleanup_plan=nas_storage_cleanup_plan,
        live_mission_output_quality=live_mission_output_quality,
        mission_artifact_repair_plan=mission_artifact_repair_plan,
    )
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "workspaceRoot": str(root),
        "benchmarks": {
            "t3Code": _load_t3_code_benchmark(root),
            "t3Chat": T3_CHAT_BENCHMARK,
        },
        "releaseReadiness": release,
        "harnessLab": harness_lab,
        "badFirst": bad_first,
        "t3Deficits": t3_deficits,
        "systemLossBreakdown": system_loss_breakdown,
        "improvementQueue": improvement_queue,
        "activeGapMissions": active_gap_missions,
        "categories": [_audit_category_payload(item) for item in categories],
        "projectProgress": project_progress,
        "liveNasEvidence": live_nas_evidence,
        "liveMissionDetailPerformanceEvidence": live_detail_performance,
        "nasStoragePressureEvidence": nas_storage_pressure,
        "nasStorageCleanupPlan": nas_storage_cleanup_plan,
        "liveMissionOutputQualityEvidence": live_mission_output_quality,
        "liveCrossCategoryOutcomeValidation": live_cross_category_outcome_validation,
        "missionArtifactRepairPlan": mission_artifact_repair_plan,
        "selfImprovementEvidence": self_improvement_evidence if isinstance(self_improvement_evidence, dict) else {},
        "publicLaunchReadinessEvidence": public_launch_readiness,
        "liveNasSystemAuditEvidence": live_nas_system_audit,
        "routeTrustSamplingEvidence": route_trust_sampling,
        "routeTrustCloseoutEvidence": route_trust_closeout,
        "routeTrustLoopEvidence": route_trust_loop,
        "routeTrustMaturity": route_trust_maturity,
        "redTeamEscalationEvidence": red_team_escalation,
        "summary": _summary(
            categories,
            release,
            project_progress,
            route_trust_maturity,
            red_team_escalation,
            public_launch_readiness=public_launch_readiness,
            nas_storage_pressure=nas_storage_pressure,
            live_mission_output_quality=live_mission_output_quality,
            mission_artifact_repair_plan=mission_artifact_repair_plan,
        ),
    }


def write_system_audit_markdown(audit: dict[str, Any], output_path: Path) -> Path:
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_system_audit_markdown(audit), encoding="utf-8")
    return output_path


def render_system_audit_markdown(audit: dict[str, Any]) -> str:
    release = audit["releaseReadiness"]
    lines: list[str] = [
        "# Neyvia System Gap Analysis",
        "",
        f"Generated: `{audit['generatedAt']}`",
        f"Workspace: `{audit['workspaceRoot']}`",
        "",
        "## Executive Read",
        "",
        audit["summary"],
        "",
    ]
    live_nas = audit.get("liveNasEvidence") or {}
    if live_nas:
        counts = live_nas.get("counts", {})
        attention_summary = _live_nas_mission_attention_summary(live_nas)
        status_counts = live_nas.get("statusCounts", {}) if isinstance(live_nas.get("statusCounts"), dict) else {}
        running_count = int(status_counts.get("running") or len(live_nas.get("runningMissions", []) or []))
        proof_bundle_label = str(live_nas.get("agentProofBundleLabel") or "").strip()
        proof_bundle_status = str(live_nas.get("agentProofBundleStatus") or "").strip()
        latest_runtime_status = str(live_nas.get("agentLatestRuntimeStatus") or "").strip()
        latest_evidence_status = str(live_nas.get("agentLatestEvidenceStatus") or "").strip()
        open_complete_proof_target = str(live_nas.get("agentOpenCompleteProofTargetMissionId") or "").strip()
        latest_agent_evidence_path = str(live_nas.get("agentLatestEvidencePath") or "").strip()
        agent_proof_bundle_lines: list[str] = []
        if proof_bundle_status:
            agent_proof_bundle_lines.append(
                f"- Agent complete-proof bundle: `{proof_bundle_status}`"
                + (f" ({proof_bundle_label})." if proof_bundle_label else ".")
            )
        if latest_runtime_status or latest_evidence_status:
            agent_proof_bundle_lines.append(
                "- Latest Agent proof states: "
                f"runtime `{latest_runtime_status or 'unknown'}`, evidence `{latest_evidence_status or 'unknown'}`."
            )
        if open_complete_proof_target:
            agent_proof_bundle_lines.append(
                f"- Open-complete-proof target: `{open_complete_proof_target}`"
                + (
                    f" (`{live_nas.get('agentOpenCompleteProofStatus')}`)."
                    if live_nas.get("agentOpenCompleteProofStatus")
                    else "."
                )
            )
        if latest_agent_evidence_path:
            agent_proof_bundle_lines.append(f"- Latest Agent evidence pointer: `{latest_agent_evidence_path}`")
        lines.extend(
            [
                "## NAS Live-State Evidence",
                "",
                f"- Source report: `{live_nas.get('sourcePath', '')}`",
                f"- Checked at: `{live_nas.get('checkedAt', '')}`",
                *(
                    [f"- Source generated at: `{live_nas.get('sourceGeneratedAt', '')}`"]
                    if live_nas.get("sourceGeneratedAt")
                    else []
                ),
                f"- Authenticated proof status: `{live_nas.get('status', 'unknown')}`",
                *(
                    [
                        f"- Superseded stale browser report mission count: `{live_nas.get('supersededMissionCount', 0)}`."
                    ]
                    if live_nas.get("supersededStaleReport")
                    else []
                ),
                f"- Agent drill-down proof status: `{live_nas.get('agentStatus', 'unknown')}`"
                + (
                    f" for `{(live_nas.get('agentSelectedMission') or {}).get('mission_id', '')}`."
                    if isinstance(live_nas.get("agentSelectedMission"), dict)
                    and (live_nas.get("agentSelectedMission") or {}).get("mission_id")
                    else "."
                ),
                *agent_proof_bundle_lines,
                f"- Mission rows: `{counts.get('missions', 0)}`.",
                f"- Active mission rows: `{counts.get('activeMissions', 0)}`.",
                f"- Running missions: `{running_count}`.",
                f"- Queued missions: `{counts.get('queuedMissions', 0)}`.",
                f"- Attention mission rows: `{attention_summary.get('reportedAttentionMissionCount', 0)}`.",
                f"- Hard blocked missions: `{attention_summary.get('hardBlockedMissionCount', 0)}`.",
                f"- Runtime-budget attention missions: `{attention_summary.get('runtimeBudgetAttentionMissionCount', 0)}`.",
                f"- Completed missions: `{counts.get('completedMissions', 0)}`.",
                f"- Notifications: `{live_nas.get('notificationCount', 0)}` total, including `{live_nas.get('sliceNotificationCount', 0)}` slice-completed notifications.",
                "",
                "Running live missions:",
            ]
        )
        running = live_nas.get("runningMissions", [])
        if running:
            for mission in running:
                lines.append(
                    f"- `{mission.get('mission_id', '')}`: {mission.get('title', 'Untitled mission')} "
                    f"({mission.get('runtime_id', 'runtime unknown')}, {mission.get('status', 'status unknown')}, "
                    f"loop `{mission.get('planner_loop_status', '')}`)"
                )
        else:
            lines.append("- None reported by the authenticated live proof.")
        lines.extend(
            [
                "",
                "Live-data contract:",
                "- Treat this section as stronger evidence than stale local workspace rows when judging current NAS progress.",
                "- If the authenticated live report is missing or failed, the audit must not claim current NAS mission state from fixtures or cached local snapshots.",
                "",
            ]
        )
    live_detail_performance = audit.get("liveMissionDetailPerformanceEvidence") or {}
    if live_detail_performance:
        lines.extend(
            [
                "Live mission-detail performance:",
                f"- Source report: `{live_detail_performance.get('sourcePath', '')}`",
                f"- Checked at: `{live_detail_performance.get('checkedAt', '')}`",
                f"- Measurements: `{live_detail_performance.get('measurementCount', 0)}` over `{live_detail_performance.get('runningMissionCount', 0)}` running mission(s).",
                f"- Warnings: `{live_detail_performance.get('warningCount', 0)}` total; backend `{live_detail_performance.get('backendWarningCount', 0)}`, wall `{live_detail_performance.get('wallWarningCount', 0)}`.",
                f"- Transport warm-up warnings: `{live_detail_performance.get('coldTransportWarningCount', 0)}` cold, `{live_detail_performance.get('warmTransportWarningCount', 0)}` warm.",
                f"- Max wall time: `{live_detail_performance.get('maxWallMs', 0)}ms`; max backend duration: `{live_detail_performance.get('maxDurationMs', 0)}ms`.",
                f"- Next: {live_detail_performance.get('nextAction', 'Rerun live mission-detail performance verification.')}",
                "",
            ]
        )
    nas_storage_pressure = audit.get("nasStoragePressureEvidence") or {}
    if nas_storage_pressure:
        storage_status = str(nas_storage_pressure.get("status") or "").lower()
        storage_is_critical = _nas_storage_pressure_is_blocking(nas_storage_pressure)
        storage_probe_failed = _nas_storage_probe_failed(nas_storage_pressure)
        storage_next_action = str(
            nas_storage_pressure.get("nextAction")
            or (
                "Free NAS volume space before trusting unattended mission writes."
                if storage_is_critical
                else "Storage is not currently blocking mission writes; keep the bounded cleanup plan as operator-reviewed evidence only."
            )
        )
        lines.extend(
            [
                "## NAS Storage Pressure",
                "",
                f"- Source report: `{nas_storage_pressure.get('sourcePath', '')}`",
                f"- Checked at: `{nas_storage_pressure.get('checkedAt', '')}`",
                f"- Mount: `{nas_storage_pressure.get('mount', _default_nas_mount_label())}`",
                f"- Status: `{nas_storage_pressure.get('status', 'unknown')}`"
                f"{' (bounded SSH probe failed)' if storage_probe_failed else ''}",
                (
                    f"- Measured usage: unavailable; {_nas_storage_pressure_sentence(nas_storage_pressure)}"
                    if storage_probe_failed
                    else f"- Used: `{nas_storage_pressure.get('usedPercent', 0)}%`."
                ),
                (
                    "- Available bytes: unavailable until a bounded df probe succeeds."
                    if storage_probe_failed
                    else f"- Available bytes: `{nas_storage_pressure.get('availableBytes', 0)}`."
                ),
                f"- Generated cleanup already freed: `{nas_storage_pressure.get('generatedCleanupBytesFreed', 0)}` bytes.",
                "- Launch preflight: NAS mission start/resume is blocked while this storage evidence remains critical."
                if storage_is_critical
                else "- Launch preflight: clear; NAS storage is not currently blocking mission start/resume.",
                f"- Next: {storage_next_action}",
                "",
            ]
        )
    nas_storage_cleanup_plan = audit.get("nasStorageCleanupPlan") or {}
    if nas_storage_cleanup_plan:
        cleanup_candidates = (
            nas_storage_cleanup_plan.get("cleanupCandidates", [])
            if isinstance(nas_storage_cleanup_plan.get("cleanupCandidates"), list)
            else []
        )
        suspected_external = (
            nas_storage_cleanup_plan.get("suspectedExternalUsage", [])
            if isinstance(nas_storage_cleanup_plan.get("suspectedExternalUsage"), list)
            else []
        )
        volume_accounting = (
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
        lines.extend(
            [
                "## NAS Storage Cleanup Plan",
                "",
                f"- Source report: `{nas_storage_cleanup_plan.get('sourcePath', '')}`",
                f"- Checked at: `{nas_storage_cleanup_plan.get('checkedAt', '')}`",
                f"- Status: `{nas_storage_cleanup_plan.get('status', 'unknown')}`",
                f"- Safe mode: `{nas_storage_cleanup_plan.get('safeMode', True)}`; destructive actions executed: `{nas_storage_cleanup_plan.get('destructiveActionsExecuted', False)}`.",
                f"- Cleanup candidates: `{len(cleanup_candidates)}`.",
                f"- Estimated generated reclaimable: `{nas_storage_cleanup_plan.get('estimatedReclaimableMB', 0)} MB`.",
                f"- Suspected non-generated usage: `{nas_storage_cleanup_plan.get('suspectedExternalGB', 0)} GB` across `{len(suspected_external)}` bounded probe path(s).",
                f"- Volume-accounting usage: `{nas_storage_cleanup_plan.get('volumeAccountingGB', 0)} GB` across `{len(volume_accounting)}` Synology/ContainerManager probe path(s).",
                f"- Timed-out non-generated probes: `{len(timed_out_external)}`.",
                f"- Timed-out volume probes: `{len(timed_out_volume)}`.",
                f"- Next: {nas_storage_cleanup_plan.get('nextAction', 'Review generated cleanup candidates before deleting anything.')}",
            ]
        )
        for row in cleanup_candidates[:8]:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"- `{row.get('path', '')}`: `{row.get('sizeMB', 0)} MB` - "
                f"{row.get('destructiveAction', 'operator_review_required')}"
            )
        if suspected_external:
            lines.append("")
            lines.append("Suspected non-generated usage:")
            for row in suspected_external[:5]:
                if not isinstance(row, dict):
                    continue
                lines.append(
                    f"- `{row.get('path', '')}`: `{row.get('sizeGB', 0)} GB` - "
                    f"{row.get('destructiveAction', 'operator_review_required')}"
                )
        if volume_accounting:
            lines.append("")
            lines.append("Volume-accounting probes:")
            for row in volume_accounting[:6]:
                if not isinstance(row, dict):
                    continue
                lines.append(
                    f"- `{row.get('path', '')}`: `{row.get('sizeGB', 0)} GB` - "
                    f"{row.get('reason', 'Synology/ContainerManager accounting evidence only.')}"
                )
        if timed_out_external:
            lines.append("")
            lines.append("Timed-out non-generated probes:")
            for path in timed_out_external[:8]:
                lines.append(f"- `{path}`")
        if timed_out_volume:
            lines.append("")
            lines.append("Timed-out volume probes:")
            for path in timed_out_volume[:8]:
                lines.append(f"- `{path}`")
        lines.append("")
    live_mission_output_quality = audit.get("liveMissionOutputQualityEvidence") or {}
    if live_mission_output_quality:
        weak_rows = (
            live_mission_output_quality.get("weakMissionRows", [])
            if isinstance(live_mission_output_quality.get("weakMissionRows"), list)
            else []
        )
        repair_rows = (
            live_mission_output_quality.get("repairMissionRows", [])
            if isinstance(live_mission_output_quality.get("repairMissionRows"), list)
            else []
        )
        lines.extend(
            [
                "## Live Mission Output Quality",
                "",
                f"- Source report count: `{live_mission_output_quality.get('reportCount', 0)}`",
                f"- Weak completed mission outputs: `{len(weak_rows)}`.",
                f"- Hard artifact-gate repairs needed: `{len(repair_rows)}`.",
                f"- Status: `{live_mission_output_quality.get('status', 'unknown')}`",
                f"- Next: {live_mission_output_quality.get('nextAction', 'Require served artifacts or concrete runtime-output bodies before scoring a completed mission as useful.')}",
            ]
        )
        for row in (repair_rows or weak_rows)[:6]:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"- `{row.get('missionId', '')}`: {row.get('title', 'Untitled mission')} "
                f"({row.get('runtime', 'runtime unknown')}, {row.get('status', 'status unknown')}) - "
                f"{row.get('detail', 'No reviewable artifact evidence returned.')}"
            )
        lines.append("")
    live_cross_category_outcome = audit.get("liveCrossCategoryOutcomeValidation") or {}
    if live_cross_category_outcome:
        categories = (
            live_cross_category_outcome.get("categories", [])
            if isinstance(live_cross_category_outcome.get("categories"), list)
            else []
        )
        lines.extend(
            [
                "## Live Cross-Category Hermes Outcome Validation",
                "",
                f"- Status: `{live_cross_category_outcome.get('status', 'unknown')}`",
                (
                    f"- Validated task families: `{live_cross_category_outcome.get('validatedCategoryCount', 0)}`/"
                    f"`{live_cross_category_outcome.get('requiredCategoryCount', 0)}`."
                ),
                f"- Next: {live_cross_category_outcome.get('nextAction', 'Keep live Hermes category validation current.')}",
            ]
        )
        for row in categories[:8]:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"- `{row.get('taskFamily', '')}`: `{row.get('missionId', '')}` "
                f"{row.get('title', '')} - runtime outputs `{row.get('runtimeOutputCount', 0)}`, "
                f"artifact gate `{row.get('artifactGateStatus', '')}`."
            )
        lines.append("")
    mission_artifact_repair_plan = audit.get("missionArtifactRepairPlan") or {}
    if mission_artifact_repair_plan:
        repair_rows = (
            mission_artifact_repair_plan.get("repairs", [])
            if isinstance(mission_artifact_repair_plan.get("repairs"), list)
            else []
        )
        lines.extend(
            [
                "## Mission Artifact Repair Plan",
                "",
                f"- Source report: `{mission_artifact_repair_plan.get('sourcePath', '')}`",
                f"- Generated at: `{mission_artifact_repair_plan.get('generatedAt', '')}`",
                f"- Status: `{mission_artifact_repair_plan.get('status', 'unknown')}`",
                f"- Weak mission repairs: `{len(repair_rows)}`.",
                f"- Next: {mission_artifact_repair_plan.get('nextAction', 'Resume weak missions with a hard artifact gate.')}",
            ]
        )
        repair_storage = (
            mission_artifact_repair_plan.get("storagePreflight", {})
            if isinstance(mission_artifact_repair_plan.get("storagePreflight"), dict)
            else {}
        )
        if repair_storage:
            storage_source = (
                repair_storage.get("storage", {})
                if isinstance(repair_storage.get("storage"), dict)
                else {}
            )
            lines.extend(
                [
                    f"- Repair storage preflight: `{repair_storage.get('status', 'unknown')}`; can resume `{bool(repair_storage.get('canResume'))}`.",
                    f"- Repair storage source: `{storage_source.get('sourcePath', '')}`.",
                ]
            )
        for row in repair_rows[:6]:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"- `{row.get('missionId', '')}` priority `{row.get('priority', 0)}`: "
                f"{row.get('action', 'resume_with_hard_artifact_gate')} "
                f"(can resume `{bool(row.get('canResumeNow', True))}`) - "
                f"{row.get('resumePrompt', '')}"
            )
        lines.append("")
    lines.extend(
        [
            "## Bad Parts First",
            "",
        ]
    )
    for item in audit["badFirst"]:
        lines.append(f"- **{item['title']}**: {item['detail']}")
    lines.extend(
        [
            "",
            "## System Loss Review",
            "",
            "- Gap is no longer only a score: mission-slice feedback, system-gap routing, and repair proposals are present.",
            "- The weak point is enforcement. High-gap skills can propose repairs, but approved patches are not yet applied automatically and validated before reuse.",
            "- The red-team path can escalate difficulty after clean passes, but live trend history still needs to prove that offensive test difficulty grows with defensive improvement.",
            "- The watchdog now reports stale, blocked, misqueued, incomplete-route, and queue-pressure missions with a first repair step; it is also a required release-readiness gate whenever active missions exist.",
        ]
    )
    loss_breakdown = audit.get("systemLossBreakdown") or {}
    if loss_breakdown:
        lines.extend(
            [
                "",
                "System-gap breakdown:",
                f"- Average score: `{loss_breakdown.get('averageScoreOutOf20', 0)}/20`.",
                f"- Remaining system gap: `{loss_breakdown.get('averageLossOutOf20', 0)}/20`.",
                f"- T3 reference average: `{loss_breakdown.get('t3ReferenceAverageOutOf20', 0)}/20`.",
                f"- Must-beat status: `{(loss_breakdown.get('mustBeatStatus') or {}).get('ahead', 0)}/{(loss_breakdown.get('mustBeatStatus') or {}).get('total', 0)}` categories ahead.",
            ]
        )
        drivers = loss_breakdown.get("drivers", []) if isinstance(loss_breakdown.get("drivers"), list) else []
        loss_drivers = [
            item
            for item in drivers
            if isinstance(item, dict)
            and (
                int(item.get("lossOutOf20") or 0) > 0
                or int(item.get("t3Margin") or 0) <= 0
            )
        ]
        if loss_drivers:
            lines.append("- Largest gap drivers:")
            for item in loss_drivers[:5]:
                lines.append(
                    f"  - `{item.get('category', '')}`: gap `{item.get('lossOutOf20', 0)}`; "
                    f"next: {item.get('nextAction', '')}"
                )
        else:
            lines.append("- Largest gap drivers: none in the current scorecard; maintain freshness gates.")
    if audit.get("improvementQueue"):
        lines.extend(["", "Improvement queue:"])
        for item in audit.get("improvementQueue", [])[:6]:
            if isinstance(item, dict):
                lines.append(
                    f"- `{item.get('lane', '')}` / `{item.get('category', '')}`: "
                    f"{item.get('nextAction', '')} (score `{item.get('scoreOutOf20', 0)}/20`, "
                    f"severity `{item.get('severity', '')}`)."
                )
    public_launch = audit.get("publicLaunchReadinessEvidence") or {}
    if public_launch:
        staging_proof = (
            public_launch.get("stagingProof", {})
            if isinstance(public_launch.get("stagingProof"), dict)
            else {}
        )
        repair_packet = (
            public_launch.get("repairPacket", {})
            if isinstance(public_launch.get("repairPacket"), dict)
            else {}
        )
        lines.extend(
            [
                "",
                "## Public Launch Truth",
                "",
                f"- Status: `{public_launch.get('status', 'unknown')}`.",
                f"- Ready to claim public launch: `{bool(public_launch.get('ok'))}`.",
                f"- Internal packet ready: `{bool(public_launch.get('internalPacketReady'))}`.",
                f"- Missing proof: `{', '.join(public_launch.get('missing', [])) if isinstance(public_launch.get('missing'), list) else ''}`.",
                f"- Next: {public_launch.get('nextAction', '')}",
                f"- Repair coverage: `{repair_packet.get('sourceCoverage', '')}`.",
                f"- Release-impacting paths: `{repair_packet.get('releaseBlockingPathCount', 0)}`.",
                f"- Private/generated paths: `{repair_packet.get('privateOrGeneratedPathCount', 0)}`.",
            ]
        )
        if staging_proof:
            lines.extend(
                [
                    f"- Staging proof schema: `{staging_proof.get('schema', '')}`.",
                    f"- Staging proof path: `{staging_proof.get('evidencePath', '')}`.",
                    f"- Staging proof release paths: `{staging_proof.get('releaseImpactPathCount', 0)}`.",
                    f"- Staging proof next action: {staging_proof.get('nextAction', '')}",
                ]
            )
        lines.extend(
            [
                "",
                "Public-launch contract:",
                "- Do not describe the project as publicly launched until `ready to claim public launch` is true.",
                "- An internally complete packet is useful, but public source parity and one external publication receipt are still required.",
            ]
        )
    if audit.get("activeGapMissions"):
        lines.extend(["", "Active gap missions:"])
        for item in audit.get("activeGapMissions", [])[:6]:
            if isinstance(item, dict):
                lines.append(
                    f"- `{item.get('missionId', '')}` in `{item.get('projectName', '')}`: "
                    f"{item.get('title', item.get('proofSummary', ''))} "
                    f"({item.get('runtime', '')}, {item.get('status', '')}). Next: {item.get('nextAction', '')}"
                )
    route_sampling = audit.get("routeTrustSamplingEvidence") or {}
    route_maturity = audit.get("routeTrustMaturity") or {}
    if route_sampling:
        launched = route_sampling.get("launchedSamplingMissions", [])
        launched_count = len(launched) if isinstance(launched, list) else 0
        closeout_review = audit.get("routeTrustCloseoutEvidence") or {}
        loop_review = audit.get("routeTrustLoopEvidence") or {}
        lines.extend(
            [
                "",
                "## Route-Trust Sampling Evidence",
                "",
                f"- Source report: `{route_sampling.get('sourcePath', '')}`",
                f"- Checked at: `{route_sampling.get('generatedAt', '')}`",
                f"- Runtime policy: `{route_sampling.get('runtime', 'unknown')}`.",
                f"- Sampling launch status: `{route_sampling.get('status', 'unknown')}`.",
                f"- Launched sampling missions: `{launched_count}`.",
            ]
        )
        storage_preflight = (
            route_sampling.get("storagePreflight", {})
            if isinstance(route_sampling.get("storagePreflight"), dict)
            else {}
        )
        if storage_preflight:
            storage = (
                storage_preflight.get("storage", {})
                if isinstance(storage_preflight.get("storage"), dict)
                else {}
            )
            lines.extend(
                [
                    f"- Storage preflight: `{storage_preflight.get('status', 'unknown')}`; "
                    f"can launch `{bool(storage_preflight.get('canLaunch'))}`; dry run `{bool(storage_preflight.get('dryRun'))}`.",
                    f"- Storage source: `{storage.get('sourcePath', '')}`.",
                    f"- Storage next: {storage_preflight.get('nextAction', '')}",
                ]
            )
        if isinstance(launched, list) and launched:
            for item in launched[:5]:
                if isinstance(item, dict):
                    lines.append(
                        f"- `{item.get('missionId', '')}`: {item.get('taskType', 'unknown')} "
                        f"via `{item.get('runtime', '')}`."
                    )
        if closeout_review:
            proposals = closeout_review.get("proposals", [])
            applied = closeout_review.get("appliedCloseouts", [])
            lines.extend(
                [
                    f"- Closeout review status: `{closeout_review.get('status', 'unknown')}`.",
                    f"- Closeout proposals: `{len(proposals) if isinstance(proposals, list) else 0}`.",
                    f"- Applied closeouts: `{len(applied) if isinstance(applied, list) else 0}`.",
                ]
            )
            if isinstance(proposals, list):
                for proposal in proposals[:5]:
                    if isinstance(proposal, dict):
                        lines.append(
                            f"- `{proposal.get('missionId', '')}` closeout state: "
                            f"{proposal.get('status', 'unknown')} ({proposal.get('missionStatus', '')})."
                        )
        if loop_review:
            lines.extend(
                [
                    f"- Loop runner status: `{loop_review.get('status', 'unknown')}`.",
                    f"- Loop action: {loop_review.get('nextAction', '')}",
                ]
            )
        lines.extend(["", f"Next: {route_sampling.get('nextAction', '')}"])
    if route_maturity:
        lines.extend(
            [
                "",
                "## Operator Confidence Calibration",
                "",
                f"- User-facing confidence score: `{route_maturity.get('operatorConfidenceScore', 0)}/100`.",
                f"- Proven route categories: `{route_maturity.get('provenTaskCount', 0)}/{route_maturity.get('taskCount', 0)}`.",
                f"- Missing value-scored samples: `{route_maturity.get('missingOperatorValueSamples', 0)}`.",
                f"- Active sampling missions: `{route_maturity.get('activeSamplingMissionCount', 0)}`.",
                f"- Failed or low-value sampling closeouts: `{route_maturity.get('lowValueCloseoutCount', 0)}`.",
                f"- Calibration state: `{route_maturity.get('status', 'unknown')}`.",
                f"- Why capped: {route_maturity.get('capReason', '')}",
                f"- Next: {route_maturity.get('nextAction', '')}",
            ]
        )
    self_improvement = (
        audit.get("selfImprovementEvidence", {})
        if isinstance(audit.get("selfImprovementEvidence"), dict)
        else {}
    )
    sampling_plan = (
        self_improvement.get("operatorValueSamplingPlan", {})
        if isinstance(self_improvement.get("operatorValueSamplingPlan"), dict)
        else {}
    )
    if sampling_plan:
        sample_rows = sampling_plan.get("sampleRows", [])
        dry_run_command = (
            sampling_plan.get("dryRunCommand", {})
            if isinstance(sampling_plan.get("dryRunCommand"), dict)
            else {}
        )
        launch_command = (
            sampling_plan.get("launchCommand", {})
            if isinstance(sampling_plan.get("launchCommand"), dict)
            else {}
        )
        lines.extend(
            [
                "",
                "Operator-value sampling plan:",
                f"- Status: `{sampling_plan.get('status', 'unknown')}`.",
                f"- Can launch now: `{bool(sampling_plan.get('canLaunch'))}`.",
                f"- Missing task categories: `{', '.join(sampling_plan.get('missingTaskCategories', []) or [])}`.",
                f"- Dry-run command: `{dry_run_command.get('shell', '')}`.",
                f"- Launch command: `{launch_command.get('shell', '')}`.",
                f"- Next: {sampling_plan.get('nextAction', '')}",
            ]
        )
        if isinstance(sample_rows, list) and sample_rows:
            for item in sample_rows[:6]:
                if isinstance(item, dict):
                    lines.append(
                        f"- `{item.get('taskType', 'unknown')}`: "
                        f"{item.get('missingUsefulSamples', 0)} useful sample(s) still missing."
                    )
    repair_plan = (
        route_maturity.get("repairPlan", [])
        if isinstance(route_maturity.get("repairPlan"), list)
        else []
    )
    if repair_plan:
        lines.extend(
            [
                "",
                "Route repair plan:",
                f"- Status: `{route_maturity.get('repairPlanStatus', 'required')}`.",
                f"- Next repair step: {route_maturity.get('nextRepairStep', '')}",
            ]
        )
        for item in repair_plan[:5]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- `{item.get('taskType', 'unknown')}` / `{item.get('missionId', '')}`: "
                f"{item.get('repairAction', '')} Model policy: {item.get('modelPolicy', '')}"
            )
    conflict = (
        route_maturity.get("evidenceConflict", {})
        if isinstance(route_maturity.get("evidenceConflict"), dict)
        else {}
    )
    if conflict:
        lines.extend(
            [
                "",
                "Route-trust evidence conflict:",
                f"- Status: `{conflict.get('status', 'unknown')}`.",
                f"- Local closeout evidence: `{conflict.get('sourcePath', '')}`.",
                f"- Synced NAS evidence: `{conflict.get('syncedSourcePath', '')}`.",
                f"- Detail: {conflict.get('detail', '')}",
            ]
        )
    red_team = audit.get("redTeamEscalationEvidence") or {}
    if red_team:
        summary = red_team.get("summary", {}) if isinstance(red_team.get("summary"), dict) else {}
        audit_payload = (
            red_team.get("escalationAudit", {})
            if isinstance(red_team.get("escalationAudit"), dict)
            else {}
        )
        trend = red_team.get("trend", {}) if isinstance(red_team.get("trend"), dict) else {}
        lines.extend(
            [
                "",
                "## Red-Team Escalation Evidence",
                "",
                f"- Source: `{red_team.get('source', 'local')}`.",
                f"- Schema: `{red_team.get('schema', '')}`.",
                f"- History rows: `{summary.get('runCount', 0)}`.",
                f"- Trend status: `{summary.get('status', trend.get('status', 'unknown'))}`.",
                f"- Latest preset: `{summary.get('latestPreset', '')}`.",
                f"- Latest resistance score: `{summary.get('latestResistanceScore', 0)}`.",
                f"- Difficulty: `{summary.get('latestDifficultyLevel', 0)}` -> `{summary.get('nextDifficultyLevel', 0)}`.",
                f"- Pressure: `{summary.get('currentPressureIndex', 0)}` -> `{summary.get('nextPressureIndex', 0)}` (delta `{summary.get('pressureDelta', 0)}`).",
                f"- Next attempt budget: `{summary.get('nextAttemptBudget', 0)}`.",
                f"- Pass streak: `{summary.get('passStreak', 0)}`.",
                f"- Clean pass: `{summary.get('cleanPass', False)}`.",
                f"- Should escalate: `{summary.get('shouldEscalate', False)}`.",
                f"- Satisfied targets: `{summary.get('satisfiedEscalationTargets', audit_payload.get('satisfiedTargets', 0))}`.",
                f"- Pending targets: `{summary.get('pendingEscalationTargets', audit_payload.get('pendingTargets', 0))}`.",
                f"- Next: {summary.get('nextAction', trend.get('nextAction', ''))}",
            ]
        )
        history = red_team.get("history", []) if isinstance(red_team.get("history"), list) else []
        if history:
            lines.extend(["", "Recent escalation rows:"])
            for row in history[-5:]:
                if not isinstance(row, dict):
                    continue
                lines.append(
                    f"- `{row.get('recordedAt', '')}` `{row.get('preset', '')}` "
                    f"L{row.get('difficultyLevel', 0)} -> L{row.get('nextDifficultyLevel', 0)}; "
                    f"pressure `{row.get('currentPressureIndex', 0)}` -> `{row.get('nextPressureIndex', 0)}`; "
                    f"resistance `{row.get('resistance_score', 0)}`; "
                    f"attempts `{row.get('attempt_count', 0)}` -> `{row.get('nextAttemptBudget', 0)}`; "
                    f"escalate `{row.get('shouldEscalate', False)}`."
                )
    lines.extend(
        [
            "",
            "## Release Readiness",
            "",
            f"- Status: `{release.get('status')}`",
            f"- Score: `{release.get('score')}`",
            f"- Required gates: `{release.get('requiredGateSummary', {}).get('passed')}/{release.get('requiredGateSummary', {}).get('total')}`",
            f"- Quality signals: `{json.dumps(release.get('qualitySignals', {}), sort_keys=True)}`",
            "",
            "## T3 Benchmark Basis",
            "",
            f"- Reference: `{(audit.get('benchmarks') or {}).get('t3Code', {}).get('name', 'T3 Code')}`.",
            f"- Observed release: `{(audit.get('benchmarks') or {}).get('t3Code', {}).get('latestObservedRelease', '')}`.",
            *(
                [
                    f"- Release evidence checked at: `{((audit.get('benchmarks') or {}).get('t3Code', {}).get('releaseEvidence') or {}).get('checkedAt', '')}`.",
                    f"- Release evidence source: `{((audit.get('benchmarks') or {}).get('t3Code', {}).get('releaseEvidence') or {}).get('source', '')}`.",
                    f"- Release evidence file: `{((audit.get('benchmarks') or {}).get('t3Code', {}).get('releaseEvidence') or {}).get('evidencePath', '')}`.",
                ]
                if ((audit.get("benchmarks") or {}).get("t3Code", {}).get("releaseEvidence"))
                else []
            ),
            "- Current public baseline includes BYO Claude Code, Codex CLI, OpenCode, and Cursor orchestration, `npx t3`, desktop/package installs, branch/worktree isolation, diff review, and one-button PR creation.",
            "- Neyvia must beat that baseline in every category before this audit can claim category parity is good enough.",
            "",
            "## T3 Comparison Scorecard",
            "",
            "| Category | Neyvia /20 | T3 reference /20 | Verdict |",
            "|---|---:|---:|---|",
        ]
    )
    for item in audit["categories"]:
        lines.append(
            f"| {item['category']} | {item['score_out_of_20']} | "
            f"{item['t3_reference_score_out_of_20']} | {item['verdict']} |"
        )
    lines.extend(["", "## T3 Deficits To Close", ""])
    if audit.get("t3Deficits"):
        lines.append(
            f"- Must-beat status: `{len(audit['categories']) - len(audit['t3Deficits'])}/{len(audit['categories'])}` categories are currently above the T3 reference. The target is `{len(audit['categories'])}/{len(audit['categories'])}`."
        )
        for item in audit["t3Deficits"]:
            lines.append(
                f"- **{item['category']}**: Neyvia `{item['fluxioScore']}/20`, "
                f"T3 `{item['t3Score']}/20`, delta `{item['delta']}`. "
                f"Blocking gap: {item['blockingGap']} Next: {item['nextMove']}"
            )
    else:
        lines.append("- Every scored category is currently above the T3 reference.")
    lines.extend(["", "## Category Detail", ""])
    for item in audit["categories"]:
        lines.extend(
            [
                f"### {item['category']} ({item['score_out_of_20']}/20)",
                "",
                f"Verdict: {item['verdict']}",
                "",
                "Evidence:",
            ]
        )
        lines.extend(f"- {value}" for value in item["evidence"])
        lines.append("")
        lines.append("Gaps:")
        lines.extend(f"- {value}" for value in item["gaps"])
        lines.append("")
        lines.append("Next moves:")
        lines.extend(f"- {value}" for value in item["next_moves"])
        lines.append("")
    lines.extend(["## Project Progress", ""])
    for project in audit["projectProgress"]:
        lines.extend(
            [
                f"### {project['name']}",
                "",
                f"- Root: `{project['root']}`",
                f"- Source mode: `{project.get('sourceMode', 'local_agent_control')}`",
                f"- Source path: `{project.get('sourcePath', '')}`",
                f"- Workspace count: `{project['workspaceCount']}`",
                f"- Mission count: `{project['missionCount']}`",
                f"- Runtime counts: `{json.dumps(project['runtimeCounts'], sort_keys=True)}`",
                f"- Status counts: `{json.dumps(project['statusCounts'], sort_keys=True)}`",
                f"- Last activity: `{project['lastActivity']}`",
                f"- Active launched mission count: `{project.get('activeMissionCount', 0)}`",
                f"- Blocked mission count: `{project.get('blockedMissionCount', 0)}`",
                f"- Attention mission count: `{project.get('attentionMissionCount', project.get('blockedMissionCount', 0))}`",
                f"- Runtime-budget attention count: `{project.get('runtimeBudgetAttentionMissionCount', 0)}`",
                "",
                "Recent missions:",
            ]
        )
        for mission in project["recentMissions"]:
            lines.append(
                f"- `{mission['missionId']}`: runtime `{mission['runtime']}`, "
                f"status `{mission['status']}`, loop `{mission['plannerLoopStatus']}`, "
                f"summary: {mission['summary']}"
            )
        lines.append("")
        lines.append("Active launched missions:")
        if project.get("activeMissions"):
            for mission in project["activeMissions"]:
                remaining = mission.get("remainingRuntimeSeconds", 0)
                remaining_text = (
                    f", remaining `{remaining}` seconds"
                    if isinstance(remaining, int) and remaining > 0
                    else ""
                )
                lines.append(
                    f"- `{mission['missionId']}`: runtime `{mission['runtime']}`, "
                    f"status `{mission['status']}`{remaining_text}, "
                    f"proof: {mission['proofSummary']} Next: {mission['nextAction']}"
                )
        else:
            lines.append("- None currently active.")
        lines.append("")
    lines.extend(
        [
            "## Benchmark Notes",
            "",
            _t3_code_reference_note((audit.get("benchmarks") or {}).get("t3Code", {})),
            "- T3 Code current strengths to beat: `npx t3`, BYO provider subscriptions, mid-thread model switching, provider/auth setup, worktree flow, one-click PRs, diff review, and perceived UI speed.",
            "- T3 Chat reference: fast web-first multi-model chat with URL-addressable new-chat parameters.",
            "- Neyvia should not merely copy those products; it should beat them on mission durability, proof, multi-project operation, and runtime supervision while matching their low-friction launch experience.",
            "",
        ]
    )
    return "\n".join(lines)


def _route_trust_maturity_snapshot(
    harness_lab: dict[str, Any],
    *,
    snapshot: dict[str, Any],
    live_nas_evidence: dict[str, Any],
    sampling: dict[str, Any],
    closeout: dict[str, Any],
    loop: dict[str, Any],
) -> dict[str, Any]:
    coverage = (
        harness_lab.get("routeTrustCoverage", {})
        if isinstance(harness_lab.get("routeTrustCoverage"), dict)
        else {}
    )
    raw_rows = coverage.get("taskCoverage", []) if isinstance(coverage.get("taskCoverage"), list) else []
    rows = [dict(row) for row in raw_rows if isinstance(row, dict)]
    task_count = len(rows)
    proposals = closeout.get("proposals", []) if isinstance(closeout.get("proposals"), list) else []
    applied = closeout.get("appliedCloseouts", []) if isinstance(closeout.get("appliedCloseouts"), list) else []
    promoted_closeouts = _route_trust_useful_closeout_tasks([*proposals, *applied])
    for row in rows:
        task_type = str(row.get("taskType") or "").strip()
        if not task_type or task_type not in promoted_closeouts:
            continue
        row["status"] = "proven"
        row["missingOperatorValueSamples"] = 0
        row["closeoutPromoted"] = True
        row["closeoutMissionIds"] = promoted_closeouts[task_type]
    proven_task_count = sum(1 for row in rows if row.get("status") == "proven")
    coverage_proven_count = int(coverage.get("provenTaskCount") or 0)
    proven_task_count = max(proven_task_count, coverage_proven_count)
    sampling_task_count = sum(1 for row in rows if row.get("status") != "proven")
    missing_samples = sum(max(0, int(row.get("missingOperatorValueSamples") or 0)) for row in rows)
    active_statuses = {"running", "queued", "launching", "needs_approval", "verification_pending"}
    mission_statuses = _snapshot_mission_statuses(snapshot)
    mission_statuses.update(_live_nas_mission_statuses(live_nas_evidence))
    sampling_missions = _route_trust_sampling_mission_refs(
        sampling=sampling,
        closeout=closeout,
        loop=loop,
    )
    active_sampling_ids = {
        mission_id
        for mission_id, item in sampling_missions.items()
        if _route_trust_sampling_mission_is_active(
            mission_id=mission_id,
            item=item,
            mission_statuses=mission_statuses,
            active_statuses=active_statuses,
        )
    }
    active_sampling = len(active_sampling_ids)
    unknown_sampling = sum(
        1
        for mission_id in sampling_missions
        if mission_id and mission_id not in mission_statuses
    )
    low_value = 0
    low_value_items: list[dict[str, Any]] = []
    for item in [*proposals, *applied]:
        if not isinstance(item, dict):
            continue
        score = -1
        try:
            score = int(item.get("score") or item.get("operatorValueScore") or -1)
        except (TypeError, ValueError):
            score = -1
        outcome = str(item.get("outcome") or item.get("operatorOutcome") or "").lower()
        trust_signal = str(item.get("trustSignal") or item.get("trust_signal") or "").lower()
        if (0 <= score < 50) or outcome == "not_useful" or trust_signal == "deprioritize":
            low_value += 1
            low_value_items.append(item)

    if task_count > 0 and proven_task_count >= task_count and missing_samples == 0 and low_value == 0:
        status = "operator_proven"
        confidence = 92
        cap_reason = "Every tracked route category has enough value-scored closeouts and no low-value samples are pending."
    elif proven_task_count > 0:
        status = "partly_proven"
        confidence = min(84, 64 + proven_task_count * 4)
        cap_reason = "Some categories have value-scored evidence, but other task categories still rely on static defaults or active sampling."
    elif active_sampling > 0:
        status = "sampling_active"
        confidence = 72
        cap_reason = "Live sampling is running, so the system should not claim full route/model/sub-agent maturity yet."
    else:
        status = "sampling_needed"
        confidence = 64
        cap_reason = "No tracked task category has enough value-scored live route trust evidence yet."
    if low_value > 0:
        confidence = min(confidence, 68)
        status = "needs_route_repair"
        cap_reason = "At least one sampling mission closed with low operator value, so routing should learn before confidence rises."

    repair_plan = _route_trust_repair_plan(low_value_items, rows)
    repair_plan_status = "required" if repair_plan else ("sampling_active" if active_sampling else "clear")
    next_repair_step = (
        repair_plan[0]["repairAction"]
        if repair_plan
        else "Let active Hermes sampling missions finish, then close them with operator value feedback."
        if active_sampling
        else "Maintain periodic Hermes route-trust sampling; all tracked task categories are currently value-scored."
        if status == "operator_proven"
        else "Launch the next Hermes route-trust sample and close it with operator value feedback."
    )
    next_action = str(coverage.get("nextAction") or sampling.get("nextAction") or loop.get("nextAction") or "")
    if status == "operator_proven" and repair_plan_status == "clear":
        next_action = "Maintain periodic Hermes route-trust sampling; all tracked task categories are currently value-scored."
    return {
        "schema": "fluxio.operator_confidence_calibration.v1",
        "status": status,
        "operatorConfidenceScore": confidence,
        "taskCount": task_count,
        "provenTaskCount": proven_task_count,
        "samplingTaskCount": sampling_task_count,
        "missingOperatorValueSamples": missing_samples,
        "activeSamplingMissionCount": active_sampling,
        "activeSamplingMissionIds": sorted(active_sampling_ids),
        "unknownSamplingMissionCount": unknown_sampling,
        "lowValueCloseoutCount": low_value,
        "closeoutPromotedTaskCount": len(promoted_closeouts),
        "closeoutPromotedTasks": sorted(promoted_closeouts),
        "repairPlanStatus": repair_plan_status,
        "repairPlanCount": len(repair_plan),
        "repairPlan": repair_plan,
        "nextRepairStep": next_repair_step,
        "capReason": cap_reason,
        "nextAction": next_action,
    }


def _merge_synced_route_trust_maturity(
    synced_route_trust: dict[str, Any],
    *,
    local_route_trust_maturity: dict[str, Any],
    closeout_review: dict[str, Any],
    source_path: str,
    source_checked_at: str,
) -> dict[str, Any]:
    merged = {
        **synced_route_trust,
        "source": "live_nas_system_audit",
        "sourcePath": source_path,
        "sourceCheckedAt": source_checked_at,
        "localRouteTrustMaturitySuperseded": local_route_trust_maturity,
    }
    local_low_value = int(local_route_trust_maturity.get("lowValueCloseoutCount") or 0)
    local_generated_at = str(closeout_review.get("generatedAt") or "").strip()
    local_generated_ts = _parse_iso_timestamp(local_generated_at)
    synced_checked_ts = _parse_iso_timestamp(source_checked_at)
    local_is_newer = local_generated_ts > 0 and synced_checked_ts > 0 and local_generated_ts > synced_checked_ts
    timestamps_missing = local_generated_ts <= 0 or synced_checked_ts <= 0
    synced_requires_repair = (
        str(synced_route_trust.get("status") or "") == "needs_route_repair"
        or str(synced_route_trust.get("repairPlanStatus") or "") == "required"
    )
    local_clears_repair = (
        str(local_route_trust_maturity.get("repairPlanStatus") or "") == "clear"
        and int(local_route_trust_maturity.get("lowValueCloseoutCount") or 0) == 0
        and int(local_route_trust_maturity.get("missingOperatorValueSamples") or 0) == 0
    )
    if (
        synced_requires_repair
        and local_clears_repair
        and local_is_newer
    ):
        return {
            **local_route_trust_maturity,
            "source": "local_route_trust_closeout_review",
            "sourcePath": str(closeout_review.get("sourcePath") or ""),
            "sourceCheckedAt": local_generated_at,
            "supersededSyncedRouteTrustMaturity": synced_route_trust,
            "syncedSourcePath": source_path,
            "syncedCheckedAt": source_checked_at,
            "staleSyncedRepairIgnored": {
                "schema": "fluxio.route_trust_stale_repair_ignored.v1",
                "status": "ignored_stale_synced_repair_after_value_closeout",
                "sourcePath": str(closeout_review.get("sourcePath") or ""),
                "generatedAt": local_generated_at,
                "syncedSourcePath": source_path,
                "syncedCheckedAt": source_checked_at,
                "detail": (
                    "A newer route-trust closeout review proves the repair mission is "
                    "already value-scored, so the older synced needs-repair snapshot is "
                    "retained as history but does not cap current route confidence."
                ),
            },
        }
    if local_low_value <= 0:
        return merged

    if not local_is_newer and not timestamps_missing:
        return {
            **merged,
            "staleLocalLowValueCloseoutIgnored": {
                "schema": "fluxio.route_trust_stale_closeout_ignored.v1",
                "status": "ignored_stale_local_low_value_closeout",
                "sourcePath": str(closeout_review.get("sourcePath") or ""),
                "generatedAt": local_generated_at,
                "syncedSourcePath": source_path,
                "syncedCheckedAt": source_checked_at,
                "lowValueCloseoutCount": local_low_value,
                "detail": (
                    "A local low-value route-trust closeout is older than the synced NAS "
                    "operator-proven audit, so it is retained as history but does not cap "
                    "current route confidence."
                ),
            },
        }

    repair_plan = (
        local_route_trust_maturity.get("repairPlan", [])
        if isinstance(local_route_trust_maturity.get("repairPlan"), list)
        else []
    )
    conflict = {
        "schema": "fluxio.route_trust_evidence_conflict.v1",
        "status": "newer_local_low_value_closeout",
        "sourcePath": str(closeout_review.get("sourcePath") or ""),
        "generatedAt": str(closeout_review.get("generatedAt") or ""),
        "syncedSourcePath": source_path,
        "syncedCheckedAt": source_checked_at,
        "lowValueCloseoutCount": local_low_value,
        "detail": (
            "A local route-trust closeout review contains low-value evidence that the synced "
            "NAS operator-proven snapshot does not cover."
        ),
    }
    return {
        **merged,
        "status": "needs_route_repair",
        "operatorConfidenceScore": min(int(merged.get("operatorConfidenceScore") or 0), 68),
        "lowValueCloseoutCount": local_low_value,
        "repairPlanStatus": "required",
        "repairPlanCount": len(repair_plan),
        "repairPlan": repair_plan,
        "nextRepairStep": str(
            local_route_trust_maturity.get("nextRepairStep")
            or "Review the conflicting route-trust closeout before claiming operator-proven routing."
        ),
        "capReason": (
            "A local low-value route-trust closeout conflicts with the synced NAS "
            "operator-proven snapshot, so route confidence is capped until reviewed."
        ),
        "nextAction": str(
            local_route_trust_maturity.get("nextAction")
            or "Review or apply the low-value closeout, then rerun route-trust sampling."
        ),
        "evidenceConflict": conflict,
    }


def _snapshot_mission_statuses(snapshot: dict[str, Any]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    missions = snapshot.get("missions", []) if isinstance(snapshot.get("missions"), list) else []
    for mission in missions:
        if not isinstance(mission, dict):
            continue
        mission_id = str(mission.get("mission_id") or mission.get("missionId") or mission.get("id") or "").strip()
        if not mission_id:
            continue
        state = mission.get("state") if isinstance(mission.get("state"), dict) else {}
        statuses[mission_id] = str(state.get("status") or mission.get("status") or "").strip().lower()
    return statuses


def _live_nas_mission_statuses(live_nas_evidence: dict[str, Any]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    running = (
        live_nas_evidence.get("runningMissions", [])
        if isinstance(live_nas_evidence.get("runningMissions"), list)
        else []
    )
    for mission in running:
        if not isinstance(mission, dict):
            continue
        mission_id = str(mission.get("mission_id") or mission.get("missionId") or mission.get("id") or "").strip()
        if not mission_id:
            continue
        statuses[mission_id] = str(mission.get("status") or "running").strip().lower()
    return statuses


def _route_trust_sampling_mission_refs(
    *,
    sampling: dict[str, Any],
    closeout: dict[str, Any],
    loop: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    refs: dict[str, dict[str, Any]] = {}

    def add_many(items: Any, *, source: str) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            mission_id = str(item.get("missionId") or item.get("mission_id") or item.get("id") or "").strip()
            if not mission_id:
                continue
            refs[mission_id] = {
                **refs.get(mission_id, {}),
                **item,
                "source": source,
            }

    add_many(sampling.get("launchedSamplingMissions", []), source="sampling_launch")
    add_many(closeout.get("proposals", []), source="closeout_review")
    launch = loop.get("samplingLaunch", {}) if isinstance(loop.get("samplingLaunch"), dict) else {}
    add_many(launch.get("launchedSamplingMissions", []), source="loop_launch")
    review = loop.get("closeoutReview", {}) if isinstance(loop.get("closeoutReview"), dict) else {}
    add_many(review.get("proposals", []), source="loop_closeout_review")
    return refs


def _route_trust_sampling_mission_is_active(
    *,
    mission_id: str,
    item: dict[str, Any],
    mission_statuses: dict[str, str],
    active_statuses: set[str],
) -> bool:
    status = mission_statuses.get(mission_id) or str(item.get("missionStatus") or item.get("status") or "").lower()
    if status in active_statuses:
        return True
    if status in {"completed", "failed", "verification_failed", "blocked", "cancelled", "draft"}:
        return False
    return False


def _route_trust_useful_closeout_tasks(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    promoted: dict[str, list[str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        feedback = item.get("operatorValueFeedback") if isinstance(item.get("operatorValueFeedback"), dict) else {}
        task_type = str(item.get("taskType") or item.get("routeTrustTaskType") or feedback.get("routeTrustTaskType") or "").strip()
        if not task_type:
            continue
        status = str(item.get("status") or "").strip()
        applied_ok = item.get("ok") is True
        scored_status = status in {"already_scored", "applied", "value_closeout_applied"}
        try:
            score = int(item.get("score") or item.get("operatorValueScore") or 0)
        except (TypeError, ValueError):
            score = 0
        if score == 0:
            try:
                score = int(feedback.get("score") or 0)
            except (TypeError, ValueError):
                score = 0
        outcome = str(item.get("outcome") or item.get("operatorOutcome") or feedback.get("outcome") or "").lower()
        trust_signal = str(
            item.get("trustSignal")
            or item.get("trust_signal")
            or feedback.get("trustSignal")
            or feedback.get("trust_signal")
            or ""
        ).lower()
        useful = score >= 80 and outcome in {"useful", "recorded"} and trust_signal in {"promote", "recorded"}
        if not useful or not (scored_status or applied_ok):
            continue
        mission_id = str(item.get("missionId") or item.get("mission_id") or "").strip()
        promoted.setdefault(task_type, [])
        if mission_id and mission_id not in promoted[task_type]:
            promoted[task_type].append(mission_id)
    return promoted


def _route_trust_repair_plan(
    low_value_items: list[dict[str, Any]],
    coverage_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    coverage_by_task = {
        str(row.get("taskType") or ""): row
        for row in coverage_rows
        if isinstance(row, dict)
    }
    plan: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in low_value_items:
        task_type = str(item.get("taskType") or "general_coding").strip() or "general_coding"
        mission_id = str(item.get("missionId") or item.get("mission_id") or "").strip()
        key = (task_type, mission_id)
        if key in seen:
            continue
        seen.add(key)
        row = coverage_by_task.get(task_type, {})
        label = str(row.get("label") or task_type.replace("_", " ").title())
        executor = "task-aware executor"
        if task_type == "frontend_design":
            executor = "MiniMax-M3 only when authenticated and actually available; otherwise Codex gpt-5.5 high with explicit provider-unavailable evidence"
        elif task_type in {"data_f1_analytics", "data_journalism", "geoint_mapping", "rf_mapping"}:
            executor = "Codex gpt-5.5 high with dataset, artifact, and browser-preview verification gates"
        plan.append(
            {
                "schema": "fluxio.route_trust_repair_step.v1",
                "taskType": task_type,
                "label": label,
                "missionId": mission_id,
                "score": _int_or_zero(item.get("score") or item.get("operatorValueScore")),
                "missionStatus": str(item.get("missionStatus") or item.get("status") or ""),
                "repairAction": (
                    f"Repair the {label} route before another promotion: require a served artifact, "
                    "proof digest, browser preview/check result, and operator value closeout before trust can rise."
                ),
                "modelPolicy": (
                    "Hermes harness; planner/verifier use openai-codex gpt-5.5 high; "
                    f"executor uses {executor}; never claim a provider path when auth/runtime evidence is missing."
                ),
                "trustEffect": "Do not promote this task category until the next sample scores at least 80 with no failed verification.",
            }
        )
    return plan


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _calibrate_category_scores(
    categories: list[AuditCategory],
    *,
    release: dict[str, Any],
    live_nas_evidence: dict[str, Any],
    route_trust_maturity: dict[str, Any],
    live_detail_performance: dict[str, Any] | None = None,
    live_mission_output_quality: dict[str, Any] | None = None,
) -> list[AuditCategory]:
    """Cap optimistic feature scores until live operation proves them."""
    live_detail_performance = live_detail_performance or {}
    status = str(release.get("status") or "")
    required = release.get("requiredGateSummary", {}) if isinstance(release.get("requiredGateSummary"), dict) else {}
    required_total = int(required.get("total") or 0)
    required_passed = int(required.get("passed") or 0)
    all_required_clear = required_total > 0 and required_passed >= required_total
    live_counts = live_nas_evidence.get("counts") if isinstance(live_nas_evidence.get("counts"), dict) else {}
    live_ok = live_nas_evidence.get("status") == "passed" and int(live_counts.get("missions") or 0) > 0
    route_trust_status = str(route_trust_maturity.get("status") or "unknown")
    route_trust_proven = route_trust_status == "operator_proven"
    if status == "ready_for_1_0_validation" and all_required_clear and live_ok and route_trust_proven:
        return _apply_operator_reality_caps(
            _apply_live_performance_caps(
                _apply_operator_proven_route_trust_lift(
                    categories,
                    route_trust_maturity=route_trust_maturity,
                    live_nas_evidence=live_nas_evidence,
                ),
                live_detail_performance=live_detail_performance,
            ),
            release=release,
            live_nas_evidence=live_nas_evidence,
            live_detail_performance=live_detail_performance,
            live_mission_output_quality=live_mission_output_quality,
        )

    calibrated: list[AuditCategory] = []
    blocked_caps: dict[str, int] = {
        "Launch friction and beginner experience": 16,
        "Multi-project Builder operations": 15,
        "Harness and sub-agent capability": 16,
        "Web availability and distribution": 17,
        "Proof, verification, and trust": 12,
        "Speed and long-history performance": 17,
        "Roadmap clarity and self-improvement": 16,
    }
    if not live_ok:
        blocked_caps.update(
            {
                "Multi-project Builder operations": 13,
                "Harness and sub-agent capability": 14,
                "Web availability and distribution": 14,
                "Proof, verification, and trust": 10,
            }
        )
    if live_ok and not route_trust_proven:
        blocked_caps.update(
            {
                "Launch friction and beginner experience": 17,
                "Multi-project Builder operations": 18,
                "Harness and sub-agent capability": 16,
                "Web availability and distribution": 18,
                "Proof, verification, and trust": 18,
                "Speed and long-history performance": 18,
                "Roadmap clarity and self-improvement": 16,
            }
        )

    for item in categories:
        cap = blocked_caps.get(item.category)
        cap_note = (
            "Operator-calibrated cap: current NAS live data is reachable, but "
            f"route trust is `{route_trust_status}` with "
            f"{route_trust_maturity.get('provenTaskCount', 0)}/"
            f"{route_trust_maturity.get('taskCount', 0)} task categories proven "
            "by value-scored live closeouts."
            if live_ok and not route_trust_proven
            else (
                "Operator-calibrated cap: score reduced until release gates are clear "
                "and current NAS live evidence proves the feature under real operation."
            )
        )
        if cap is None:
            calibrated.append(item)
            continue
        if item.score_out_of_20 <= cap:
            calibrated.append(
                replace(
                    item,
                    evidence=[*item.evidence, cap_note],
                    gaps=[
                        "Operator-facing maturity remains capped until live value-scored route trust covers every tracked task category.",
                        *item.gaps,
                    ]
                    if live_ok and not route_trust_proven and item.category in {
                        "Harness and sub-agent capability",
                        "Proof, verification, and trust",
                        "Roadmap clarity and self-improvement",
                    }
                    else item.gaps,
                )
            )
            continue
        calibrated.append(
            replace(
                item,
                score_out_of_20=cap,
                evidence=[
                    *item.evidence,
                    cap_note,
                ],
                gaps=[
                    (
                        "Score is capped because live value-scored route trust is not fully proven yet."
                        if live_ok and not route_trust_proven
                        else "Score is capped because release readiness is not fully clear yet."
                    ),
                    *item.gaps,
                ],
            )
        )
    return _apply_operator_reality_caps(
        _apply_live_performance_caps(
            calibrated,
            live_detail_performance=live_detail_performance,
        ),
        release=release,
        live_nas_evidence=live_nas_evidence,
        live_detail_performance=live_detail_performance,
        live_mission_output_quality=live_mission_output_quality,
    )


def _live_nas_mission_attention_summary(
    live_nas_evidence: dict[str, Any] | None,
    live_mission_output_quality: dict[str, Any] | None = None,
) -> dict[str, int | bool]:
    evidence = live_nas_evidence or {}
    quality = live_mission_output_quality or {}
    counts = evidence.get("counts") if isinstance(evidence.get("counts"), dict) else {}
    status_counts = (
        evidence.get("statusCounts")
        if isinstance(evidence.get("statusCounts"), dict)
        else {}
    )
    running = evidence.get("runningMissions") if isinstance(evidence.get("runningMissions"), list) else []

    def _int(value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    reported_attention = max(
        _int(counts.get("attentionMissions")),
        _int(counts.get("blockedMissions")),
    )
    explicit_status_blocked = sum(
        _int(status_counts.get(status))
        for status in ("blocked", "needs_approval", "verification_failed")
    )
    repair_count = max(
        _int(quality.get("repairMissionCount")),
        _int(quality.get("weakMissionCount")),
        len(quality.get("repairMissionRows", []))
        if isinstance(quality.get("repairMissionRows"), list)
        else 0,
    )
    hard_blocked_ids: set[str] = set()
    runtime_budget_attention_ids: set[str] = set()
    for item in running:
        if not isinstance(item, dict):
            continue
        mission_id = str(item.get("mission_id") or item.get("missionId") or "")
        mission_key = mission_id or str(len(hard_blocked_ids) + len(runtime_budget_attention_ids))
        live_progress = item.get("liveProgress") if isinstance(item.get("liveProgress"), dict) else {}
        progress_kind = str(live_progress.get("progressKind") or "").strip().lower()
        progress_source = str(live_progress.get("source") or "").strip().lower()
        status = str(item.get("status") or "").strip().lower()
        blocked_by = item.get("blockedBy") or item.get("blocked_by") or []
        blocked_by_count = len(blocked_by) if isinstance(blocked_by, list) else int(bool(blocked_by))
        failed_checks = _int(item.get("failedChecks") or item.get("failed_checks"))
        pending_approvals = _int(item.get("pendingApprovals") or item.get("pending_approvals"))
        hard_blocked = (
            status in {"blocked", "needs_approval", "verification_failed"}
            or progress_kind == "proof_repair"
            or blocked_by_count > 0
            or failed_checks > 0
            or pending_approvals > 0
        )
        runtime_budget_attention = (
            progress_kind == "runtime_budget_exhausted"
            or progress_source == "mission_runtime_budget_exhausted"
            or (
                status == "running"
                and _int(item.get("remainingRuntimeSeconds") or item.get("remaining_runtime_seconds")) <= 0
                and str(item.get("timeBudgetStatus") or item.get("time_budget_status") or "").lower()
                in {"running", "exhausted", "runtime_budget_exhausted", "budget_exhausted"}
            )
        )
        if hard_blocked:
            hard_blocked_ids.add(mission_key)
        elif runtime_budget_attention:
            runtime_budget_attention_ids.add(mission_key)

    hard_blocked = max(explicit_status_blocked, len(hard_blocked_ids), repair_count)
    runtime_budget_attention = len(runtime_budget_attention_ids)
    has_rich_detail = bool(status_counts or running or quality)
    unresolved_reported_attention = max(0, reported_attention - hard_blocked - runtime_budget_attention)
    if reported_attention > 0 and not has_rich_detail:
        hard_blocked = max(hard_blocked, reported_attention)
        unresolved_reported_attention = 0

    return {
        "reportedAttentionMissionCount": reported_attention,
        "hardBlockedMissionCount": hard_blocked + unresolved_reported_attention,
        "runtimeBudgetAttentionMissionCount": runtime_budget_attention,
        "unresolvedReportedAttentionMissionCount": unresolved_reported_attention,
        "hasRichAttentionDetail": has_rich_detail,
    }


def _apply_operator_reality_caps(
    categories: list[AuditCategory],
    *,
    release: dict[str, Any],
    live_nas_evidence: dict[str, Any],
    live_detail_performance: dict[str, Any] | None = None,
    live_mission_output_quality: dict[str, Any] | None = None,
) -> list[AuditCategory]:
    """Prevent a perfect score when live operator evidence still has real gaps."""

    live_detail_performance = live_detail_performance or {}
    live_mission_output_quality = live_mission_output_quality or {}
    quality_score = int(release.get("qualityScore") or 0)
    attention_summary = _live_nas_mission_attention_summary(
        live_nas_evidence,
        live_mission_output_quality,
    )
    blocked_missions = int(attention_summary.get("hardBlockedMissionCount") or 0)
    runtime_attention_missions = int(attention_summary.get("runtimeBudgetAttentionMissionCount") or 0)
    checked_rows = (
        live_mission_output_quality.get("checkedMissionRows", [])
        if isinstance(live_mission_output_quality.get("checkedMissionRows"), list)
        else []
    )
    missing_transcript_rows = [
        row
        for row in checked_rows
        if isinstance(row, dict)
        and str(row.get("runtimeTranscriptStatus") or "").lower() in {"missing", "missing_transcript"}
    ]
    live_detail_missing = not (
        isinstance(live_detail_performance, dict)
        and live_detail_performance.get("schema") == "fluxio.live_mission_detail_performance.v1"
        and int(live_detail_performance.get("measurementCount") or 0) > 0
    )

    caps: dict[str, tuple[int, str]] = {}

    def add_cap(category: str, cap: int, reason: str) -> None:
        previous = caps.get(category)
        if previous is None or cap < previous[0]:
            caps[category] = (cap, reason)

    if quality_score and quality_score < 80:
        reason = (
            f"Reality cap: release required gates pass, but release quality score is {quality_score}/100; "
            "a perfect product score requires quality score >= 80."
        )
        for category, cap in {
            "Launch friction and beginner experience": 18,
            "Multi-project Builder operations": 18,
            "Proof, verification, and trust": 18,
            "Web availability and distribution": 18,
            "Speed and long-history performance": 18,
            "Roadmap clarity and self-improvement": 18,
            "Interface clarity and operator ergonomics": 17,
        }.items():
            add_cap(category, cap, reason)
    if blocked_missions > 0:
        reason = (
            f"Reality cap: authenticated live NAS evidence still reports {blocked_missions} blocked mission(s); "
            "operator flow is not perfect until blocked rows are cleared or explicitly dismissed as non-actionable."
        )
        add_cap("Launch friction and beginner experience", 18, reason)
        add_cap("Multi-project Builder operations", 18, reason)
        add_cap("Interface clarity and operator ergonomics", 17, reason)
    elif runtime_attention_missions > 0:
        reason = (
            f"Reality cap: authenticated live NAS evidence reports {runtime_attention_missions} runtime-budget "
            "attention mission(s), not failed proof rows; extend, resume, or close them before launch can score 20/20."
        )
        add_cap("Launch friction and beginner experience", 18, reason)
        add_cap("Multi-project Builder operations", 19, reason)
        add_cap("Interface clarity and operator ergonomics", 18, reason)
    if missing_transcript_rows:
        reason = (
            f"Reality cap: {len(missing_transcript_rows)} checked live mission row(s) still have missing runtime transcripts; "
            "the Agent thread cannot be scored perfect until real messages, artifacts, and transcripts line up."
        )
        add_cap("Proof, verification, and trust", 18, reason)
        add_cap("Interface clarity and operator ergonomics", 17, reason)
        add_cap("Harness and sub-agent capability", 19, reason)
    if live_detail_missing:
        add_cap(
            "Speed and long-history performance",
            18,
            "Reality cap: no fresh live mission-detail performance measurement is attached, so speed cannot score 20/20.",
        )

    capped: list[AuditCategory] = []
    for item in categories:
        cap_entry = caps.get(item.category)
        has_vapid_gap = item.category == "Web availability and distribution" and any(
            "production VAPID" in str(gap_text) for gap_text in item.gaps
        )
        if cap_entry is None and has_vapid_gap:
            cap_entry = (
                18,
                "Reality cap: browser/PWA notifications still mention production VAPID provisioning; "
                "closed-tab phone delivery is not a perfect web-distribution story until that proof is current.",
            )
        if cap_entry is None:
            capped.append(item)
            continue
        cap, reason = cap_entry
        gap = reason
        if has_vapid_gap:
            cap = min(cap, 18)
            gap = (
                "Reality cap: browser/PWA notifications still mention production VAPID provisioning; "
                "closed-tab phone delivery is not a perfect web-distribution story until that proof is current."
        )
        capped.append(
            replace(
                item,
                score_out_of_20=min(item.score_out_of_20, cap),
                evidence=[*item.evidence, reason],
                gaps=[gap, *item.gaps] if gap not in item.gaps else item.gaps,
                next_moves=[
                    *_reality_next_moves_for_category(item.category),
                    *item.next_moves,
                ],
            )
        )
    return capped


def _reality_next_moves_for_category(category: str) -> list[str]:
    if category == "Interface clarity and operator ergonomics":
        return ["Make Agent show the real live message thread, transcript status, artifacts, and next repair step as the first view."]
    if category == "Proof, verification, and trust":
        return ["Restore or attach missing runtime transcripts for checked live missions, then rerun live mission detail verification."]
    if category == "Speed and long-history performance":
        return ["Run and archive live mission-detail performance measurements before claiming 20/20 speed."]
    if category == "Multi-project Builder operations":
        return ["Clear or explicitly resolve current blocked live mission rows in Builder."]
    if category == "Launch friction and beginner experience":
        return ["Keep beginner launch proof current after blocked live mission rows are resolved."]
    if category == "Web availability and distribution":
        return ["Keep Web Push, browser, and Telegram receipts current for phone/tablet runs."]
    return []


def _apply_live_performance_caps(
    categories: list[AuditCategory],
    *,
    live_detail_performance: dict[str, Any],
) -> list[AuditCategory]:
    """Keep speed scoring tied to measured live NAS mission-detail behavior."""

    if not isinstance(live_detail_performance, dict) or not live_detail_performance:
        return categories
    schema = str(live_detail_performance.get("schema") or "")
    if schema != "fluxio.live_mission_detail_performance.v1":
        return categories
    warning_count = int(live_detail_performance.get("warningCount") or 0)
    backend_warning_count = (
        int(live_detail_performance.get("backendWarningCount") or 0)
        if "backendWarningCount" in live_detail_performance
        else warning_count
    )
    wall_warning_count = int(live_detail_performance.get("wallWarningCount") or 0)
    cold_warning_count = int(live_detail_performance.get("coldWarningCount") or 0)
    warm_warning_count = int(live_detail_performance.get("warmWarningCount") or 0)
    cold_transport_warning_count = int(live_detail_performance.get("coldTransportWarningCount") or 0)
    warm_transport_warning_count = int(live_detail_performance.get("warmTransportWarningCount") or 0)
    measurement_count = int(live_detail_performance.get("measurementCount") or 0)
    if measurement_count <= 0:
        cap = 17
        reason = "Live mission-detail performance evidence exists, but it recorded no measurements."
    elif backend_warning_count <= 0 and warm_transport_warning_count <= 0 and live_detail_performance.get("ok"):
        return [
            replace(
                item,
                evidence=[
                    *item.evidence,
                    (
                        "Live mission-detail performance proof passed: "
                        f"{measurement_count} measurement(s), max wall "
                        f"{live_detail_performance.get('maxWallMs', 0)}ms, "
                        f"transport warm-up warnings {cold_transport_warning_count}."
                    ),
                ],
            )
            if item.category == "Speed and long-history performance"
            else item
            for item in categories
        ]
    elif warm_warning_count > 0:
        cap = 16
        reason = (
            "Strict live-performance cap: warm mission-detail calls still missed the live wall/budget target "
            f"({warm_warning_count} warm warning(s), {warning_count} total warning(s))."
        )
    elif cold_warning_count > 0:
        cap = 17
        reason = (
            "Strict live-performance cap: cold mission-detail generation still missed the live wall/budget target "
            f"({cold_warning_count} cold warning(s), {warning_count} total warning(s))."
        )
    else:
        cap = 18
        reason = (
            "Strict live-performance cap: mission-detail performance proof reported warning(s) "
            f"({warning_count}) before speed can be scored as release-grade."
        )
    capped: list[AuditCategory] = []
    for item in categories:
        if item.category != "Speed and long-history performance":
            capped.append(item)
            continue
        evidence = [
            *item.evidence,
            (
                "Live detail performance evidence: "
                f"{measurement_count} measurement(s), backend warnings {backend_warning_count}, "
                f"wall warnings {wall_warning_count}, cold backend warnings {cold_warning_count}, "
                f"warm backend warnings {warm_warning_count}, "
                f"cold transport warnings {cold_transport_warning_count}, "
                f"warm transport warnings {warm_transport_warning_count}, "
                f"max wall {live_detail_performance.get('maxWallMs', 0)}ms."
            ),
            reason,
        ]
        gaps = [
            "Measured live NAS mission-detail latency must pass cold and warm budgets before speed can be claimed ahead of T3.",
            *item.gaps,
        ]
        next_moves = [
            str(live_detail_performance.get("nextAction") or "Reduce live mission-detail latency and rerun the performance verifier."),
            *item.next_moves,
        ]
        capped.append(
            replace(
                item,
                score_out_of_20=min(item.score_out_of_20, cap),
                verdict=(
                    "Live NAS performance proof is measurable but not consistently release-grade yet; "
                    "warm-cache interaction is good, while cold mission-detail generation still needs work."
                ),
                evidence=evidence,
                gaps=gaps,
                next_moves=next_moves,
            )
        )
    return capped


def _apply_operator_proven_route_trust_lift(
    categories: list[AuditCategory],
    *,
    route_trust_maturity: dict[str, Any],
    live_nas_evidence: dict[str, Any],
) -> list[AuditCategory]:
    """Reflect proven live route trust without inflating unrelated launch gaps."""

    agent_checks = (
        live_nas_evidence.get("agentPassedChecks", [])
        if isinstance(live_nas_evidence.get("agentPassedChecks"), list)
        else []
    )
    live_agent_switch_proven = all(
        check in agent_checks
        for check in (
            "agent-thread-not-empty",
            "live-tool-event-visible",
            "live-mission-click-switch",
            "no-demo-data-visible",
        )
    )
    lifted: list[AuditCategory] = []
    for item in categories:
        if item.category != "Harness and sub-agent capability":
            lifted.append(item)
            continue
        evidence = [
            *item.evidence,
            (
                "operator-proven route trust: "
                f"{route_trust_maturity.get('provenTaskCount', 0)}/"
                f"{route_trust_maturity.get('taskCount', 0)} task categories "
                "have useful value-scored closeouts"
            ),
            f"authenticated live Agent switch/message proof present: {live_agent_switch_proven}",
        ]
        gaps = [
            gap
            for gap in item.gaps
            if "proving it on live model-backed missions over time" not in gap
            and "live trend validation across more task categories" not in gap
        ]
        gaps.append(
            "Next harness gap is no longer basic route-trust proof; it is accumulating longer time-series evidence for automatic difficulty/routing improvement."
        )
        next_moves = [
            move
            for move in item.next_moves
            if "Run repeated live missions per task category" not in move
        ]
        next_moves.insert(
            0,
            "Keep running harder red-team and task-route samples so the operator-proven route set becomes a trend, not only a point-in-time proof.",
        )
        lifted.append(
            replace(
                item,
                score_out_of_20=max(item.score_out_of_20, 19),
                verdict=(
                    "Ahead of T3 Code on harness/sub-agent operation: Hermes-first lanes, route mutation and rollback receipts, "
                    "outcome-trend routing, live Agent message/switch proof, and value-scored route trust are all present."
                ),
                evidence=evidence,
                gaps=gaps,
                next_moves=next_moves,
            )
        )
    return lifted


def _score_categories(
    root: Path,
    snapshot: dict[str, Any],
    release: dict[str, Any],
    setup_health: dict[str, Any],
    harness_lab: dict[str, Any],
    route_trust_maturity: dict[str, Any] | None = None,
    nas_storage_pressure: dict[str, Any] | None = None,
    live_mission_output_quality: dict[str, Any] | None = None,
    mission_artifact_repair_plan: dict[str, Any] | None = None,
) -> list[AuditCategory]:
    workspaces = snapshot.get("workspaces", [])
    missions = snapshot.get("missions", [])

    def _mission_runtime_budget_exhausted(mission: Any) -> bool:
        if not isinstance(mission, dict):
            return False
        if str(mission.get("status") or "").lower() not in {"running", "delegated_active", "approval_waiting"}:
            return False
        live_progress = mission.get("liveProgress") if isinstance(mission.get("liveProgress"), dict) else {}
        explicit_exhausted = str(mission.get("timeBudgetStatus") or "").lower() in {
            "running",
            "exhausted",
            "runtime_budget_exhausted",
        } and int(mission.get("remainingRuntimeSeconds") or 0) <= 0
        progress_exhausted = str(live_progress.get("progressKind") or "").lower() == "runtime_budget_exhausted"
        source_exhausted = str(live_progress.get("source") or "").lower() == "mission_runtime_budget_exhausted"
        return explicit_exhausted or progress_exhausted or source_exhausted

    has_active_runtime_budget_exhausted = any(_mission_runtime_budget_exhausted(mission) for mission in missions)
    required = release.get("requiredGateSummary", {})
    quality = release.get("qualitySignals", {})
    setup_summary = setup_health.get("serviceManagementSummary", {})
    has_web = (root / "web" / "src" / "neyvia" / "NeyviaApp.tsx").exists()
    has_tauri = (root / "src-tauri").exists()
    has_workflow_docs = (root / "docs" / "FLUXIO_1_0_RELEASE.md").exists()
    has_tutorial = (root / "docs" / "NEYVIA_OPERATOR_GUIDE.md").exists()
    has_skill_library = (root / "src" / "grant_agent" / "skill_library.py").exists()
    has_runtime_supervisor = (root / "src" / "grant_agent" / "runtime_supervisor.py").exists()
    cli_text = _safe_read(root / "src" / "grant_agent" / "cli.py")
    mission_control_text = _safe_read(root / "src" / "grant_agent" / "mission_control.py")
    # The classic NeyviaShell/NeyviaWorkspace UI and its stylesheets were removed; the one shell
    # is web/src/neyvia/next (entered through NeyviaApp.tsx). Markers are read from its sources.
    shell_text = _current_shell_text(root, (".jsx", ".js", ".tsx", ".ts"))
    reference_shell_text = shell_text
    model_text = _safe_read(root / "web" / "src" / "neyvia" / "missionControlModel.js")
    styles_text = _current_shell_text(root, (".css",))
    fixtures_text = _safe_read(root / "web" / "src" / "neyvia" / "missionFixtures.js")
    package_text = _safe_read(root / "package.json")
    readme_text = _safe_read(root / "README.md")
    tutorial_text = _safe_read(root / "docs" / "NEYVIA_OPERATOR_GUIDE.md")
    has_quickstart = "mission-quickstart" in cli_text
    has_builder_quickstart = "quickstart_control_room_mission_command" in shell_text
    has_storage_aware_quickstart_fallback = (
        "_mission_storage_pressure_blocker(root, item)" in cli_text
        and "missionLaunchStorageBlockReason" in shell_text
        and 'data-launch-local-fallback="true"' in shell_text
        and "Use local workspace" in shell_text
        and "test_mission_quickstart_prefers_local_workspace_when_nas_storage_is_blocked"
        in _safe_read(root / "tests" / "test_cli_preferences.py")
    )
    has_launch_shortcuts = "missionLaunchShortcuts" in mission_control_text and "launchPrefillAppliedRef" in shell_text
    has_contextual_launch_recommendation = (
        "fluxio.launch_runtime_recommendation.v1" in _safe_read(root / "src" / "grant_agent" / "launch_recommendation.py")
        and "runtimeRecommendation" in mission_control_text
        and "missionLaunchRecommendation" in shell_text
        and "Contextual runtime recommendation" in shell_text
    )
    has_one_command_launcher = (
        (root / "scripts" / "launch_neyvia.py").exists()
        and '"neyvia": "python scripts/launch_neyvia.py"' in package_text
        and "npm run neyvia" in readme_text
        and "npm run neyvia" in tutorial_text
    )
    has_npx_style_launcher_package = (
        (root / "scripts" / "neyvia-cli.mjs").exists()
        and (root / "scripts" / "verify_launcher_package.py").exists()
        and '"bin"' in package_text
        and '"neyvia": "scripts/neyvia-cli.mjs"' in package_text
        and '"verify:launcher-package"' in package_text
        and "npm exec -- neyvia" in tutorial_text
    )
    launcher_package_receipt = _load_json(root / ".agent_control" / "launcher_package" / "latest.json", {})
    public_launch_readiness = _load_public_launch_readiness_evidence(root)
    has_launcher_package_release_receipt = (
        isinstance(launcher_package_receipt, dict)
        and launcher_package_receipt.get("schema") == "fluxio.launcher_package_verification.v1"
        and launcher_package_receipt.get("ok") is True
        and launcher_package_receipt.get("entrypoint") == "scripts/neyvia-cli.mjs"
        and int(launcher_package_receipt.get("packedFileCount") or 0) > 0
    )
    has_public_launch_readiness_report = (
        public_launch_readiness.get("schema") == "fluxio.public_launch_readiness.v1"
    )
    has_public_launch_internal_packet_ready = bool(public_launch_readiness.get("internalPacketReady"))
    has_public_launch_ready = bool(public_launch_readiness.get("ok"))
    publication_proof = (
        public_launch_readiness.get("publicationProof")
        if isinstance(public_launch_readiness.get("publicationProof"), dict)
        else {}
    )
    has_external_publication_proof = bool(
        has_public_launch_ready
        and (
            publication_proof.get("githubReleaseReceiptPresent")
            or publication_proof.get("npmReceiptPresent")
            or publication_proof.get("signedInstallerReceiptPresent")
        )
    )
    has_responsive_smoke = (root / "scripts" / "control_route_responsive_smoke.py").exists()
    visual_smoke_text = _safe_read(root / "scripts" / "control_route_visual_smoke.py")
    responsive_smoke_text = _safe_read(root / "scripts" / "control_route_responsive_smoke.py")
    has_beginner_launch_interaction_gate = (
        "fluxio.launch_interaction_proof.v1" in visual_smoke_text
        and "--assert-launch-interactions" in visual_smoke_text
        and "--assert-launch-interactions" in responsive_smoke_text
        and '"verify:beginner-launch"' in package_text
    )
    has_project_health = "workspaceHealth" in model_text and "Project health" in shell_text
    has_project_progress_history = (
        "fluxio.project_progress_history.v1" in mission_control_text
        and "deriveProjectProgressHistory" in model_text
        and "builderProjectProgressHistory" in shell_text
        and "Live project history attached" in shell_text
        and "Builder will not invent per-project progress" in shell_text
    )
    has_dependency_aware_project_scheduler = (
        "fluxio.dependency_aware_project_scheduler.v1" in mission_control_text
        and "_workspace_dependency_ids" in mission_control_text
        and "dependency_blocked" in mission_control_text
        and "declaredDependencyIds" in mission_control_text
        and "dependencyBlockedWorkspaces" in mission_control_text
        and "Dependency-aware scheduler" in shell_text
    )
    has_beginner_safe_sync_authority = (
        "fluxio.workspace_sync_authority.v1" in mission_control_text
        and "_workspace_sync_authority" in mission_control_text
        and "safeForWritableDependency" in mission_control_text
        and "Sync authority:" in shell_text
        and "builder-sync-authority" in shell_text
        and "syncAuthority" in model_text
    )
    has_cross_device_launch_rehearsal = (
        "fluxio.cross_device_launch_rehearsal.v1" in mission_control_text
        and "_cross_device_launch_rehearsal" in mission_control_text
        and "sync_authority" in mission_control_text
        and "dependency_schedule" in mission_control_text
        and "runtime_route" in mission_control_text
        and "Launch rehearsal:" in shell_text
        and "Guided cross-device launch rehearsal" in shell_text
        and "launchRehearsal" in model_text
    )
    cross_device_launch_receipt = _load_json(
        root / ".agent_control" / "cross_device_launch_rehearsals" / "latest.json",
        {},
    )
    cross_device_launch_receipt_history = [
        item
        for item in _load_jsonl(root / ".agent_control" / "cross_device_launch_rehearsals" / "receipts.jsonl")
        if isinstance(item, dict)
        and item.get("schema") == "fluxio.cross_device_launch_rehearsal_receipt.v1"
    ]
    has_cross_device_launch_rehearsal_receipt = (
        isinstance(cross_device_launch_receipt, dict)
        and cross_device_launch_receipt.get("schema")
        == "fluxio.cross_device_launch_rehearsal_receipt.v1"
        and cross_device_launch_receipt.get("receiptId")
        and cross_device_launch_receipt.get("status")
        in {"launched", "launched_with_review_items", "ready_recorded", "review_recorded"}
    )
    has_repeated_cross_device_launch_rehearsal_receipts = (
        len(cross_device_launch_receipt_history) >= 2
    )
    release_archive_text = _safe_read(root / "scripts" / "archive_release_proofs.py")
    release_proof_workflow_text = _safe_read(root / ".github" / "workflows" / "release-proof.yml")
    has_cross_device_launch_receipts_release_proof = (
        "crossDeviceLaunchReceiptSummary" in release_archive_text
        and "cross_device_launch_rehearsals" in release_archive_text
        and ".agent_control/cross_device_launch_rehearsals/**" in release_proof_workflow_text
    )
    has_public_release_publication_packet = (
        "publicReleasePublicationPacketAttached" in release_archive_text
        and "public-release-notes.md" in release_archive_text
        and "publication-manifest.json" in release_archive_text
        and "--require-publication-packet" in release_archive_text
    )
    latest_release_artifact_pointer = _load_json(
        root / ".agent_control" / "release_artifacts" / "latest.json",
        {},
    )
    has_latest_release_artifact_pointer = (
        isinstance(latest_release_artifact_pointer, dict)
        and latest_release_artifact_pointer.get("schema")
        == "fluxio.latest_release_artifact_pointer.v1"
        and bool(latest_release_artifact_pointer.get("manifestPath"))
        and bool(latest_release_artifact_pointer.get("releaseCandidatePath"))
    )
    has_public_release_attachment_manifest = (
        "publicReleaseAttachmentManifestAttached" in release_archive_text
        and "publication-attachments.json" in release_archive_text
        and "fluxio.public_release_attachment_manifest.v1" in release_archive_text
        and has_latest_release_artifact_pointer
        and int(
            latest_release_artifact_pointer.get("counts", {}).get(
                "publicReleaseAttachmentManifestArtifacts",
                0,
            )
            or 0
        )
        >= 1
    )
    has_mission_context_roots = (
        "fluxio.mission.context_roots.v1" in mission_control_text
        and "Mission context roots" in shell_text
        and "deriveMissionContextRoots" in model_text
    )
    has_cross_project_dependency_edges = (
        "dependencyEdges" in mission_control_text
        and "writeScopePreflight" in model_text
        and "Cross-project dependency edges" in shell_text
    )
    has_receipt_backed_sync_conflicts = (
        "fluxio.workspace_sync_receipt.v1" in mission_control_text
        and "fluxio.sync_conflict_receipt.v1" in mission_control_text
        and "builder-sync-receipt" in shell_text
        and "Manual sync review required" in shell_text
    )
    has_interactive_sync_conflict_resolution = (
        "fluxio.sync_conflict_resolution_receipt.v1" in mission_control_text
        and "workspace-sync-conflict-resolve" in cli_text
        and "resolve_workspace_sync_conflict_command" in _safe_read(root / "src" / "grant_agent" / "web_backend.py")
        and "handleSyncConflictResolution" in shell_text
        and "One-click sync conflict resolution" in shell_text
    )
    has_batch_sync_conflict_resolution = (
        "fluxio.sync_conflict_batch_resolution_receipt.v1" in mission_control_text
        and "workspace-sync-conflict-resolve-batch" in cli_text
        and "resolve_workspace_sync_conflict_batch_command" in _safe_read(root / "src" / "grant_agent" / "web_backend.py")
        and "handleSyncConflictBatchResolution" in shell_text
        and "Batch sync conflict resolution" in shell_text
    )
    has_queue_pressure_watchdog = (
        "workspace_queue_pressure" in _safe_read(root / "src" / "grant_agent" / "mission_watchdog.py")
        and "Queue pressure" in shell_text
    )
    has_queue_pressure_scope_safety = (
        "scopeSafety" in _safe_read(root / "src" / "grant_agent" / "mission_watchdog.py")
        and "planned_file_scope" in _safe_read(root / "src" / "grant_agent" / "models.py")
        and "infer_planned_file_scope" in mission_control_text
        and "queuePressureSafe" in model_text
        and "Scope safety" in shell_text
    )
    mission_watchdog_text = _safe_read(root / "src" / "grant_agent" / "mission_watchdog.py")
    has_external_watchdog_supervisor_loop = (
        "fluxio.mission_watchdog_supervisor.v1" in mission_watchdog_text
        and "write_watchdog_supervisor_state" in mission_watchdog_text
        and "load_watchdog_supervisor_state" in mission_watchdog_text
        and "External watchdog supervisor loop" in shell_text
        and "loopActive" in model_text
        and "--loop" in cli_text
        and "--interval-seconds" in cli_text
        and "--max-runs" in cli_text
    )
    has_external_watchdog_autostart = (
        "fluxio.mission_watchdog_autostart.v1" in mission_watchdog_text
        and "ensure_watchdog_supervisor_loop" in mission_watchdog_text
        and "FLUXIO_WATCHDOG_AUTOSTART" in _safe_read(root / "src" / "grant_agent" / "web_backend.py")
    )
    has_watchdog_problem_registry = (
        "fluxio.watchdog_problem_registry.v1" in mission_watchdog_text
        and "mission_watchdog_problem_registry.json" in mission_watchdog_text
        and "Watchdog problem registry" in shell_text
        and "problemRegistry" in model_text
        and "firstRepairStep" in mission_watchdog_text
    )
    has_parallel_worktree_action = (
        "parallelize-worktree" in cli_text
        and "mission.parallelized_worktree" in cli_text
    )
    has_parallel_worktree_builder_button = (
        "handleWatchdogParallelize" in shell_text
        and "Parallelize worktree" in shell_text
        and "parallelize-worktree" in shell_text
    )
    has_parallel_dispatch_evidence = (
        (root / "scripts" / "verify_parallel_dispatch_evidence.py").exists()
        and "verify:parallel-dispatch" in package_text
        and (root / ".agent_control" / "parallel_dispatch_evidence" / "latest.json").exists()
    )
    has_subagent_lanes = "subAgentLanes" in model_text and "Sub-agent lanes" in shell_text
    has_subagent_lane_controls = (
        "laneProof" in model_text
        and "builder-lane-control-row" in shell_text
        and "handleSubAgentLaneControl" in shell_text
    )
    has_route_mutation_receipts = (
        "fluxio.route_mutation_receipt.v1" in cli_text
        and "mission-route" in cli_text
        and "apply_control_room_mission_route_command" in shell_text
        and "builder-route-receipt" in shell_text
    )
    has_route_rollback_receipts = (
        "fluxio.route_rollback_receipt.v1" in cli_text
        and "_rollback_latest_route_mutation_after_verification_failure" in cli_text
        and "Route rollback" in shell_text
    )
    fluxio_harness_text = _safe_read(root / "src" / "grant_agent" / "fluxio_harness.py")
    has_task_aware_model_routing = (
        "infer_task_route_profile" in fluxio_harness_text
        and "Frontend/UI/design work routes execution to MiniMax" in fluxio_harness_text
        and "hardware_electrical" in fluxio_harness_text
        and "data_f1_analytics" in fluxio_harness_text
        and 'CODEX_PLANNING_PROVIDER = "openai-codex"' in fluxio_harness_text
        and 'CODEX_PLANNING_MODEL = "gpt-5.5"' in fluxio_harness_text
    )
    has_task_fit_lane_proof = (
        has_task_aware_model_routing
        and "Task-aware model route" in shell_text
        and "builder-lane-task-fit" in shell_text
        and "routeIntent" in model_text
        and "fitScore" in model_text
    )
    has_outcome_trend_routing = (
        "build_route_outcome_trends" in fluxio_harness_text
        and "fluxio.route_outcome_trends.v1" in fluxio_harness_text
        and "fluxio.route_outcome_quarantine.v1" in fluxio_harness_text
        and "route_outcome_quarantine_reroute" in fluxio_harness_text
        and "outcome_trend_execution" in fluxio_harness_text
        and "outcomeSampleCount" in mission_control_text
    )
    has_launch_route_trust_confidence = (
        "launchTrustEvidence" in shell_text
        and "Outcome-trend confidence" in shell_text
        and "Copy trust command" in shell_text
        and "mission-launch-route-trust" in styles_text
        and "routeTrustCoverage" in shell_text
    )
    has_harness_parity = "parityMatrix" in mission_control_text and "Harness parity matrix" in shell_text
    demo_runner_text = _safe_read(root / "src" / "grant_agent" / "demo_runner.py")
    has_red_team_escalation = "difficultyEscalation" in demo_runner_text
    has_red_team_escalation_history = (
        "red_team_escalation_history.jsonl" in demo_runner_text
        and "fluxio.red_team_escalation_trend.v1" in demo_runner_text
        and "append_red_team_escalation_history" in _safe_read(root / "src" / "grant_agent" / "cli.py")
    )
    has_adaptive_red_team_benchmark = (
        "_expanded_attempt_strategies" in demo_runner_text
        and "fluxio.red_team_escalation_target.v1" in demo_runner_text
        and "fluxio.red_team_escalation_audit.v1" in demo_runner_text
        and "generated_escalation_attempts" in demo_runner_text
        and "escalationAudit" in _safe_read(root / "scripts" / "verify_self_improvement_evidence.py")
        and "escalationAudit" in mission_control_text
    )
    has_red_team_escalation_builder_trend = (
        "Red-team escalation trend" in shell_text
        and "Red-team escalation trend" in reference_shell_text
        and "redTeamEscalation" in model_text
        and "red-team-escalation-trend" in styles_text
    )
    web_backend_text = _safe_read(root / "src" / "grant_agent" / "web_backend.py")
    has_summary_payload = "build_summary_snapshot" in mission_control_text and "control-room-summary" in cli_text
    has_in_process_summary_endpoint = (
        "def _build_control_room_summary" in web_backend_text
        and "ControlRoomStore(root).build_summary_snapshot()" in web_backend_text
        and '"get_control_room_summary_command"' in web_backend_text
    )
    has_bootstrap_summary_cache = (
        "BOOTSTRAP_SUMMARY_CACHE_TTL_SECONDS" in web_backend_text
        and "_cached_control_room_bootstrap_summary" in web_backend_text
        and "fluxio.control_room.summary_cache.v1" in web_backend_text
        and "warm live summary" in reference_shell_text
    )
    has_lazy_mission_detail = "build_mission_detail_snapshot" in mission_control_text and "control-room-mission-detail" in cli_text
    has_virtual_timeline_window = "useVirtualWindow" in reference_shell_text and "virtualTimeline.items.map" in reference_shell_text
    has_bounded_builder_timeline = (
        "builderTimelineRows = [" in reference_shell_text
        and "].filter(Boolean).slice(0, builderTimelineShowDone ? 8 : 6)" in reference_shell_text
        and "builderTimelineRows.length > 0 ? builderTimelineRows.map" in reference_shell_text
        and ".reference-builder-moments.virtualized" in styles_text
    )
    has_virtual_timeline = has_virtual_timeline_window or has_bounded_builder_timeline
    has_virtual_transcript_window = (
        "transcriptWindow.items.length" in reference_shell_text
        and "transcriptRows.map" in reference_shell_text
        and ".reference-chat-thread-canvas.virtualized" in styles_text
    )
    has_bounded_agent_transcript = (
        "visibleAgentMessages(compactMessages, 36, 8" in reference_shell_text
        and "threadMessageEntries = useMemo" in reference_shell_text
        and 'data-agent-chat-thread={agentChatMode ? "true" : "false"}' in reference_shell_text
        and ".reference-chat-thread-canvas.virtualized" in styles_text
    )
    has_virtual_transcript = has_virtual_transcript_window or has_bounded_agent_transcript
    has_legacy_lazy_proof_artifacts = (
        "lazyProofArtifactPageSize" in reference_shell_text
        and "Show more artifacts" in reference_shell_text
        and "agent-proof-page-button" in styles_text
    )
    has_bounded_proof_artifact_surfaces = (
        "visibleProofDiffRows = proofDiffRows.slice(0, proofDiffVisibleCount)" in reference_shell_text
        and "Show more diff evidence" in reference_shell_text
        and "const artifacts = asList(workbenchState?.artifacts).slice(0, 8)" in reference_shell_text
        and "agent-proof-page-button" in styles_text
        and "proof-side-by-side-diff" in styles_text
    )
    has_lazy_proof_artifacts = has_legacy_lazy_proof_artifacts or has_bounded_proof_artifact_surfaces
    has_side_by_side_proof_diff = (
        "buildProofSideBySideRows" in shell_text
        and "Side-by-side proof diff" in shell_text
        and "Side-by-side proof diff" in reference_shell_text
        and "proofDiffVisibleCount" in shell_text
        and "proofDiffVisibleCount" in reference_shell_text
        and "Show more diff evidence" in shell_text
        and "Show more diff evidence" in reference_shell_text
        and "proof-side-by-side-diff" in styles_text
    )
    has_performance_budget = "fluxio.performance_budget.v1" in mission_control_text
    has_browser_performance_budget = "fluxio.browser_performance_budget.v1" in _safe_read(
        root / "scripts" / "control_route_visual_smoke.py"
    )
    has_long_history_browser_fixture = (
        "long_history" in fixtures_text
        and "Long-History Proof Load" in fixtures_text
        and "--long-history-fixture" in _safe_read(root / "scripts" / "control_route_visual_smoke.py")
        and "--long-history-fixture" in _safe_read(root / "scripts" / "control_route_responsive_smoke.py")
    )
    has_long_history_release_gate = (
        '"verify:long-history"' in package_text
        and "--long-history-fixture" in package_text
        and "Side-by-side proof diff" in package_text
    )
    has_release_proof_archive = (
        "fluxio.release_proof_archive.v1" in release_archive_text
        and '"verify:release-artifacts"' in package_text
        and "--require-long-history" in package_text
        and "--require-proof-digest" in package_text
    )
    has_release_proof_ci = (
        has_release_proof_archive
        and "npm run frontend:build" in release_proof_workflow_text
        and "npm run verify:long-history" in release_proof_workflow_text
        and "npm run verify:release-artifacts" in release_proof_workflow_text
        and "actions/upload-artifact" in release_proof_workflow_text
        and ".agent_control/proof_digests/ci-release-proof.md" in release_proof_workflow_text
        and ".agent_control/release_artifacts/**" in release_proof_workflow_text
        and "tmp-ui-checks/**" in release_proof_workflow_text
    )
    has_web_notifications = "NotificationStack" in shell_text and "get_control_room_summary_command" in shell_text
    has_browser_notifications = "requestBrowserNotifications" in shell_text and "new window.Notification" in shell_text
    has_overnight_digest = (
        "fluxio.overnight_progress_digest.v1" in mission_control_text
        and "Overnight digest" in shell_text
        and ".notification-overnight" in styles_text
    )
    has_notification_delivery_receipts = (
        "record_delivery_receipt_command" in shell_text
        and "record_delivery_receipt_command" in _safe_read(root / "src" / "grant_agent" / "web_backend.py")
        and "receiptBacked" in mission_control_text
        and "latestReceipts" in mission_control_text
        and "notification-receipt-row" in styles_text
    )
    delivery_receipt_text = _safe_read(root / "src" / "grant_agent" / "delivery_receipt.py")
    has_out_of_band_watchdog_notifications = (
        "send_watchdog_delivery_receipt" in delivery_receipt_text
        and "watchdog.problem_report" in delivery_receipt_text
        and "--notify-telegram" in cli_text
        and "notificationReceipt" in cli_text
    )
    web_backend_text = _safe_read(root / "src" / "grant_agent" / "web_backend.py")
    has_closed_tab_web_push_sender = (
        "send_web_push_delivery_receipts" in delivery_receipt_text
        and "send_web_push_notification_command" in web_backend_text
        and "Closed-tab Web Push" in shell_text
        and "delivery_skipped" in shell_text
    )
    pwa_manifest_text = _safe_read(root / "web" / "public" / "manifest.webmanifest")
    pwa_service_worker_text = _safe_read(root / "web" / "public" / "service-worker.js")
    pwa_registration_text = _safe_read(root / "web" / "src" / "pwa.ts")
    has_installable_pwa_shell = (
        '"display": "standalone"' in pwa_manifest_text
        and '"start_url": "/control"' in pwa_manifest_text
        and "/offline.html" in pwa_service_worker_text
        and 'url.pathname.startsWith("/api")' in pwa_service_worker_text
        and "navigator.serviceWorker.register" in pwa_registration_text
        and "registerNeyviaPwa" in _safe_read(root / "web" / "src" / "main.tsx")
        and '"verify:pwa"' in package_text
    )
    public_web_distribution_text = _safe_read(root / "scripts" / "verify_public_web_distribution.py")
    web_pages_workflow_text = _safe_read(root / ".github" / "workflows" / "web-pages.yml")
    has_public_web_distribution_contract = (
        "fluxio.public_web_distribution.v1" in public_web_distribution_text
        and '"verify:web-distribution"' in package_text
        and "npm run verify:web-distribution" in web_pages_workflow_text
        and "actions/upload-pages-artifact" in web_pages_workflow_text
        and "actions/deploy-pages" in web_pages_workflow_text
        and "path: web/dist" in web_pages_workflow_text
        and "page_url" in web_pages_workflow_text
        and "fluxio.public_web_deployment.v1" in web_pages_workflow_text
        and "fluxio-public-web-release-candidate" in web_pages_workflow_text
        and ".agent_control/deployment_evidence/public-web.json" in web_pages_workflow_text
        and has_installable_pwa_shell
    )
    release_proof_archive_text = _safe_read(root / "scripts" / "archive_release_proofs.py")
    has_public_web_release_candidate_attachment = (
        "fluxio.release_candidate.v1" in release_proof_archive_text
        and "publicWebDeploymentAttached" in release_proof_archive_text
        and "publicWebDeploymentReceipts" in release_proof_archive_text
        and "--require-public-web-deployment" in release_proof_archive_text
        and '"verify:release-candidate"' in package_text
        and "fluxio.release_candidate.v1" in web_pages_workflow_text
        and "fluxio-public-web-release-candidate" in web_pages_workflow_text
        and ".agent_control/release_candidates/public-web/release-candidate.json" in web_pages_workflow_text
    )
    try:
        web_push_sender_status = web_push_status(root)
    except Exception:
        web_push_sender_status = {}
    has_web_push_sender_configured = bool(web_push_sender_status.get("senderConfigured"))
    has_web_push_subscription = int(web_push_sender_status.get("subscriptionCount") or 0) > 0
    try:
        ntfy_sender_status = ntfy_status(root)
    except Exception:
        ntfy_sender_status = {}
    delivery_receipt_rows = [
        row
        for row in _load_jsonl(root / ".agent_control" / "delivery_receipts.jsonl")
        if isinstance(row, dict)
    ]
    has_ntfy_sender_configured = bool(ntfy_sender_status.get("senderConfigured"))
    has_ntfy_delivered_receipt = any(
        str(row.get("channel") or "").lower() == "ntfy"
        and str(row.get("status") or "").lower() == "delivered"
        for row in delivery_receipt_rows
    )
    has_mobile_push_delivery_proof = has_web_push_subscription or (
        has_ntfy_sender_configured and has_ntfy_delivered_receipt
    )
    web_push_distribution_gap = (
        "Open-source ntfy phone push is configured and has a delivered broker receipt; Web Push browser subscription remains optional secondary proof."
        if has_ntfy_sender_configured and has_ntfy_delivered_receipt
        else
        "Closed-tab Web Push has configured sender keys and browser subscriptions; the remaining gap is an archived real closed-tab delivery receipt from a phone/tablet browser."
        if has_web_push_sender_configured and has_web_push_subscription
        else
        "Closed-tab Web Push sender keys and dependency are configured; the remaining gap is registering a real phone/tablet browser subscription and archiving a delivery receipt."
        if has_web_push_sender_configured
        else
        "GitHub Pages deployment receipt, release-candidate attachment, external release proof, and closed-tab Web Push sender path exist; the remaining web gap is production VAPID key configuration."
        if has_public_web_distribution_contract and has_public_web_release_candidate_attachment and has_closed_tab_web_push_sender and has_external_publication_proof
        else
        "GitHub Pages deployment receipt, release-candidate attachment, and closed-tab Web Push sender path exist; the remaining gap is public release publication and production VAPID key configuration."
        if has_public_web_distribution_contract and has_public_web_release_candidate_attachment and has_closed_tab_web_push_sender
        else
        "GitHub Pages deployment receipt now attaches to the release candidate; the remaining gap is real closed-tab push and public release publication."
        if has_public_web_distribution_contract and has_public_web_release_candidate_attachment
        else
        "GitHub Pages deployment and PWA distribution are now verified by a release contract that records the published URL after deploy; the remaining gap is attaching the generated receipt to a release candidate."
        if has_public_web_distribution_contract
        else
        "One-command private web launch exists now; no public hosted demo or signed installer-grade onboarding is proven from this audit."
        if has_one_command_launcher
        else "Private web launch shortcuts are present; no public hosted demo or one-click installer-grade web onboarding is proven from this audit."
        if has_launch_shortcuts
        else "No public hosted demo or one-click installer-grade web onboarding is proven from this audit."
    )
    web_push_notification_gap = (
        "Out-of-band Telegram watchdog receipts, installable app shell, GitHub Pages deployment contract, and ntfy phone push with a delivered broker receipt exist now; the next gap is moving ntfy from public random topic to self-hosted or token-protected production settings."
        if has_out_of_band_watchdog_notifications and has_installable_pwa_shell and has_public_web_distribution_contract and has_ntfy_sender_configured and has_ntfy_delivered_receipt
        else
        "Out-of-band Telegram watchdog receipts, installable app shell, GitHub Pages deployment contract, deployed-URL receipt capture, and configured Web Push sender keys exist now; the next gap is a real browser subscription plus delivery receipt."
        if has_out_of_band_watchdog_notifications and has_installable_pwa_shell and has_public_web_distribution_contract and has_closed_tab_web_push_sender and has_web_push_sender_configured and not has_web_push_subscription
        else
        "Out-of-band Telegram watchdog receipts, installable app shell, GitHub Pages deployment contract, deployed-URL receipt capture, and Web Push sender/subscription evidence exist now; the next gap is real closed-tab delivery proof."
        if has_out_of_band_watchdog_notifications and has_installable_pwa_shell and has_public_web_distribution_contract and has_closed_tab_web_push_sender and has_web_push_sender_configured
        else
        "Out-of-band Telegram watchdog receipts, installable app shell, GitHub Pages deployment contract, deployed-URL receipt capture, and Web Push send receipts exist now; the next gap is production VAPID provisioning."
        if has_out_of_band_watchdog_notifications and has_installable_pwa_shell and has_public_web_distribution_contract and has_closed_tab_web_push_sender
        else
        "Out-of-band Telegram watchdog receipts, installable app shell, GitHub Pages deployment contract, and deployed-URL receipt capture exist now; the next gap is real closed-tab push."
        if has_out_of_band_watchdog_notifications and has_installable_pwa_shell and has_public_web_distribution_contract
        else
        "Out-of-band Telegram watchdog receipts and installable app shell exist now; the next gap is public/signed packaging and real closed-tab push."
        if has_out_of_band_watchdog_notifications and has_installable_pwa_shell
        else
        "Out-of-band Telegram watchdog receipts exist now; the next gap is installable app shell, public/signed packaging, and optional service-worker push."
        if has_out_of_band_watchdog_notifications
        else
        "Receipt-backed overnight delivery exists now; the next gap is closed-tab service-worker push and public/signed packaging."
        if has_notification_delivery_receipts
        else
        "App-like overnight digest exists now; the next gap is closed-tab mobile push or Telegram delivery receipts."
        if has_overnight_digest
        else
        "Responsive visual smoke exists; the next gap is closed-tab mobile push and install-grade packaging."
        if has_responsive_smoke
        else
        "Browser alerts are permission-gated now; the next gap is service-worker push for closed-tab phone notifications and phone/tablet visual QA."
        if has_browser_notifications
        else
        "Notification feed is now available, but it still needs real push/browser permission support and phone/tablet visual QA."
        if has_web_notifications
        else "NAS availability depends on private network health and does not degrade gracefully in the local UI."
    )
    has_skill_feedback_loop = (
        "record_slice_feedback" in _safe_read(root / "src" / "grant_agent" / "skill_library.py")
        and "Mission-slice feedback loop" in shell_text
    )
    has_system_loss_skill_routing = (
        "systemLossRouting" in _safe_read(root / "src" / "grant_agent" / "skill_library.py")
        and "fluxio.skill_system_loss_hold.v1" in _safe_read(root / "src" / "grant_agent" / "skill_library.py")
        and "systemLossHold" in _safe_read(root / "src" / "grant_agent" / "skill_library.py")
        and "System gap routing" in shell_text
    )
    has_skill_repair_proposals = (
        "repairProposals" in _safe_read(root / "src" / "grant_agent" / "skill_library.py")
        and "beforeVerification" in _safe_read(root / "src" / "grant_agent" / "skill_library.py")
        and "afterVerification" in _safe_read(root / "src" / "grant_agent" / "skill_library.py")
        and "Automatic repair proposals" in shell_text
        and "skill-repair-proposals" in styles_text
    )
    has_approved_skill_repair_application = (
        "apply_repair_proposal" in _safe_read(root / "src" / "grant_agent" / "skill_library.py")
        and "fluxio.skill_repair_apply_receipt.v1" in _safe_read(root / "src" / "grant_agent" / "skill_library.py")
        and "skill-repair-apply" in cli_text
        and "apply_skill_repair_command" in _safe_read(root / "src" / "grant_agent" / "web_backend.py")
        and "handleApplySkillRepair" in shell_text
        and "Apply approved repair" in shell_text
    )
    has_operator_value_closeout = (
        "fluxio.mission_operator_value_feedback.v1" in cli_text
        and "operator_value_feedback" in _safe_read(root / "src" / "grant_agent" / "models.py")
        and "Operator value closeout" in shell_text
        and "mission-closeout-feedback" in styles_text
    )
    has_operator_value_route_trust = (
        "operatorValueAverage" in fluxio_harness_text
        and "scannedMissionCloseouts" in fluxio_harness_text
        and "_operator_feedback_signal" in fluxio_harness_text
        and "operator value" in fluxio_harness_text
    )
    has_route_trust_coverage_plan = (
        "fluxio.route_trust_coverage.v1" in mission_control_text
        and "nextSamplingPlan" in mission_control_text
        and "Route and skill trust coverage" in shell_text
    )
    has_route_trust_launch_templates = (
        "fluxio.route_trust_sampling_template.v1" in mission_control_text
        and "sampleMissionObjective" in mission_control_text
        and "sampleMissionCliCommand" in mission_control_text
        and "Load sample mission" in shell_text
    )
    has_operator_value_skill_trust = (
        "operator_value_closeout" in _safe_read(root / "src" / "grant_agent" / "skill_library.py")
        and "operatorValuePolicy" in _safe_read(root / "src" / "grant_agent" / "skill_library.py")
        and "_operator_value_summary" in _safe_read(root / "src" / "grant_agent" / "skill_library.py")
    )
    self_improvement_evidence_text = _safe_read(root / "scripts" / "verify_self_improvement_evidence.py")
    self_improvement_loop_text = _safe_read(root / "scripts" / "advance_self_improvement_red_team_loop.py")
    has_self_improvement_evidence_contract = (
        "fluxio.self_improvement_evidence.v1" in self_improvement_evidence_text
        and '"verify:self-improvement"' in package_text
        and "npm run verify:self-improvement" in release_proof_workflow_text
        and ".agent_control/self_improvement_evidence/**" in release_proof_workflow_text
        and "self_improvement_evidence" in release_archive_text
    )
    has_self_improvement_red_team_loop = (
        "fluxio.self_improvement_red_team_loop_run.v1" in self_improvement_loop_text
        and "record_red_team_sample" in self_improvement_loop_text
        and "build_self_improvement_evidence" in self_improvement_loop_text
        and '"advance:self-improvement-red-team"' in package_text
    )
    cli_text = _safe_read(root / "src" / "grant_agent" / "cli.py")
    mission_watchdog_text = _safe_read(root / "src" / "grant_agent" / "mission_watchdog.py")
    has_self_improvement_watchdog_cadence = (
        "fluxio.self_improvement_watchdog_cadence.v1" in cli_text
        and "selfImprovementCadence" in cli_text
        and "--advance-self-improvement" in mission_watchdog_text
    )
    sync_nas_system_audit_text = _safe_read(root / "scripts" / "sync_nas_system_audit.py")
    has_self_improvement_watchdog_history = (
        "watchdog_history.jsonl" in cli_text
        and "watchdog_history.jsonl" in sync_nas_system_audit_text
    )
    watchdog_history_path = root / ".agent_control" / "self_improvement_evidence" / "watchdog_history.jsonl"
    watchdog_history_rows = [
        line
        for line in _safe_read(watchdog_history_path).splitlines()
        if line.strip()
    ]
    watchdog_completed_receipts = 0
    for line in watchdog_history_rows:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("status") == "completed":
            watchdog_completed_receipts += 1
    has_self_improvement_watchdog_trend = watchdog_completed_receipts >= 3
    live_route_trust = (
        route_trust_maturity
        if isinstance(route_trust_maturity, dict)
        else _load_live_nas_system_audit_evidence(root).get("routeTrustMaturity", {})
    )
    if not isinstance(live_route_trust, dict):
        live_route_trust = {}
    archived_self_improvement = _load_json(
        root / ".agent_control" / "self_improvement_evidence" / "latest.json",
        {},
    )
    archived_route_trust = (
        archived_self_improvement.get("operatorValueRouteTrust", {})
        if isinstance(archived_self_improvement, dict)
        else {}
    )
    if not isinstance(archived_route_trust, dict):
        archived_route_trust = {}
    live_task_count = int(live_route_trust.get("taskCount") or 0)
    archived_task_count = int(
        archived_route_trust.get("taskCount")
        or len(archived_route_trust.get("taskCoverage") or [])
        or 0
    )
    has_operator_value_route_trust_proven = (
        live_route_trust.get("status") == "operator_proven"
        and live_task_count > 0
        and int(live_route_trust.get("provenTaskCount") or 0) >= live_task_count
    ) or (
        archived_route_trust.get("source") == "live_nas_system_audit"
        and archived_task_count > 0
        and int(archived_route_trust.get("provenTaskCount") or 0) >= archived_task_count
        and not archived_route_trust.get("missingTaskCategories")
    )
    live_cross_category_outcome_validation = _live_cross_category_outcome_validation(
        live_mission_output_quality or {}
    )
    has_live_cross_category_outcome_validation = (
        live_cross_category_outcome_validation.get("status") == "passed"
    )
    has_live_mission_output_quality_cleared = (
        isinstance(live_mission_output_quality, dict)
        and live_mission_output_quality.get("status") == "passed"
        and bool(live_mission_output_quality.get("checkedMissionRows"))
        and not live_mission_output_quality.get("weakMissionRows")
        and not live_mission_output_quality.get("repairMissionRows")
    )
    has_proof_digest = "proofDigest" in mission_control_text and "Mission proof digest" in shell_text
    has_proof_digest_export = (
        "export_mission_proof_digest_command" in shell_text
        and "export_mission_proof_digest_command" in _safe_read(root / "src" / "grant_agent" / "web_backend.py")
        and "export_mission_proof_digest_command" in _safe_read(root / "src-tauri" / "src" / "lib.rs")
        and "fluxio.mission.proof_digest_export.v1" in mission_control_text
        and "Export/share digest" in shell_text
        and "proof-digest-actions" in styles_text
    )
    categories = [
        AuditCategory(
            category="Launch friction and beginner experience",
            score_out_of_20=20 if has_builder_quickstart and has_launch_shortcuts and has_tutorial and has_responsive_smoke and has_one_command_launcher and has_beginner_launch_interaction_gate and workspaces else (19 if has_builder_quickstart and has_launch_shortcuts and has_tutorial and has_responsive_smoke and workspaces else (18 if has_builder_quickstart and has_tutorial and has_responsive_smoke and workspaces else (17 if has_builder_quickstart and has_tutorial and workspaces else (15 if has_quickstart and has_tutorial and workspaces else (13 if has_tutorial and workspaces else 10))))),
            t3_reference_score_out_of_20=18,
            verdict=(
                "Ahead of T3-style launch simplicity for supported mission starts: one-command web launch, one-field Builder launch, copyable launch URLs/commands, responsive visual QA, and browser interaction proof are present."
                if has_builder_quickstart and has_launch_shortcuts and has_responsive_smoke and has_one_command_launcher and has_beginner_launch_interaction_gate
                else
                "Ahead of T3-style launch simplicity for supported mission starts: one-command web launch, one-field Builder launch, copyable launch URLs/commands, and responsive visual QA are present."
                if has_builder_quickstart and has_launch_shortcuts and has_responsive_smoke and has_one_command_launcher
                else
                "Ahead of T3-style launch simplicity for supported mission starts: one-field Builder launch, copyable launch URLs/commands, and responsive visual QA are present."
                if has_builder_quickstart and has_launch_shortcuts and has_responsive_smoke
                else
                "Now ahead of T3-style launch simplicity for the supported mission path, with a one-field Builder start and responsive visual QA harness."
                if has_builder_quickstart and has_responsive_smoke
                else
                "Now comparable to T3-style launch simplicity for the supported mission path; polish still depends on screenshot-verified beginner UX."
                if has_builder_quickstart
                else "Closer to T3-style launch simplicity now that quickstart exists, but the UI still needs the same one-field path."
                if has_quickstart
                else "Behind T3 on first-run simplicity; ahead only when the operator already understands missions."
            ),
            evidence=[
                f"tutorial doc present: {has_tutorial}",
                f"workspace profiles visible: {len(workspaces)}",
                f"required setup health: {setup_summary.get('healthyCount')}/{setup_summary.get('totalItems')}",
                f"mission quickstart command present: {has_quickstart}",
                f"Builder quickstart control present: {has_builder_quickstart}",
                f"storage-aware local quickstart fallback present: {has_storage_aware_quickstart_fallback}",
                f"copyable launch URL/command shortcuts present: {has_launch_shortcuts}",
                f"one-command web launcher present: {has_one_command_launcher}",
                f"npx-style package launcher present: {has_npx_style_launcher_package}",
                f"launcher package release receipt present: {has_launcher_package_release_receipt}",
                f"public launch readiness report present: {has_public_launch_readiness_report}",
                f"public launch internal packet ready: {has_public_launch_internal_packet_ready}",
                f"public launch ready: {has_public_launch_ready}",
                f"external publication proof present: {has_external_publication_proof}",
                f"responsive visual smoke present: {has_responsive_smoke}",
                f"beginner launch interaction proof present: {has_beginner_launch_interaction_gate}",
            ],
            gaps=[
                (
                    "Public launch readiness verifier says the packet is internally ready, but public web source parity or external publication proof is still missing."
                    if has_public_launch_readiness_report and has_public_launch_internal_packet_ready and not has_public_launch_ready
                    else "Public launch readiness is proven by current public web, release-packet, and external publication evidence."
                    if has_public_launch_ready
                    else "Launcher package receipt and public web release-candidate path exist now; the next gap is actual public registry publication or signed installer distribution."
                    if has_launcher_package_release_receipt and has_public_web_release_candidate_attachment
                    else "Package-level npx-style launch exists now; the next gap is signed installer/public hosted onboarding."
                    if has_npx_style_launcher_package
                    else "One-command local web launch exists now; the next gap is signed installer/public hosted onboarding."
                    if has_one_command_launcher
                    else "Copyable launch shortcuts exist; the next gap is packaging them into a one-command installer or hosted onboarding path."
                    if has_launch_shortcuts
                    else
                    "Responsive smoke exists; the next gap is keeping screenshots as release artifacts and adding interaction assertions."
                    if has_responsive_smoke
                    else
                    "The one-field Builder quickstart exists; it still needs browser/screenshot validation with a non-technical first-run user path."
                    if has_builder_quickstart
                    else "The CLI now has a one-objective quickstart path, but Builder still needs the same simplified launch control."
                    if has_quickstart
                    else "Mission launch still exposes too many runtime/auth/profile terms at once."
                ),
                (
                    "Beginner launch interaction proof exists now; the next gap is installer/public-hosted onboarding."
                    if has_beginner_launch_interaction_gate
                    else "Beginner mode is described in docs but not proven as a materially simpler end-to-end launch path."
                ),
                (
                    "NAS-backed missions are blocked by storage pressure, but quickstart can fall back to a local workspace; remaining gap is clearing NAS write headroom for unattended remote missions."
                    if has_storage_aware_quickstart_fallback
                    and isinstance(nas_storage_pressure, dict)
                    and _nas_storage_pressure_is_blocking(nas_storage_pressure)
                    else
                    str(public_launch_readiness.get("nextAction") or "Public launch readiness needs rerun.")
                    if has_public_launch_readiness_report and not has_public_launch_ready
                    else "Public GitHub release/tag proof is attached; remaining launch work is optional registry or signed-installer distribution."
                    if has_external_publication_proof
                    else "Package entrypoint is archive-backed now, but public registry publication or signed installer distribution is still missing."
                    if has_launcher_package_release_receipt
                    else "Local package bin exists now; public registry publication or signed installer distribution is still missing."
                    if has_npx_style_launcher_package
                    else "Local `npm run neyvia` exists now; public `npx`/installer-grade distribution is still missing."
                    if has_one_command_launcher
                    else "URL-style launch exists now; packaged `npx t3`-level distribution is still missing."
                    if has_launch_shortcuts
                    else "No URL-style mission creation comparable to T3 Chat's /new params or a packaged `npx t3` feel."
                ),
            ],
            next_moves=[
                (
                    "Keep the GitHub release receipt, public-web receipt, and release packet current for each candidate."
                    if has_external_publication_proof
                    else "Publish or tag the current release candidate."
                    if has_public_launch_ready
                    else str(public_launch_readiness.get("nextAction") or "Refresh public launch readiness evidence.")
                    if has_public_launch_readiness_report
                    else "Publish the archive-backed package entrypoint to a public registry or add a signed desktop installer."
                    if has_launcher_package_release_receipt
                    else "Publish the package entrypoint or add a signed desktop installer."
                    if has_npx_style_launcher_package
                    else "Package the launcher behind a signed installer or public `npx` entrypoint."
                    if has_one_command_launcher
                    else "Add one-click launcher packaging that opens the web console and reuses these launch shortcuts."
                    if has_launch_shortcuts
                    else
                    "Run and archive phone/tablet/desktop visual smoke on each release candidate."
                    if has_responsive_smoke
                    else
                    "Run a visual/browser audit of the quickstart modal and make it the primary launch affordance."
                    if has_builder_quickstart
                    else "Mirror `mission-quickstart` in Builder as a single 'Start from goal' control."
                ),
                (
                    "Keep the local fallback path active, but clear NAS storage before claiming unattended NAS mission launch reliability."
                    if has_storage_aware_quickstart_fallback
                    and isinstance(nas_storage_pressure, dict)
                    and _nas_storage_pressure_is_blocking(nas_storage_pressure)
                    else
                    "Keep `verify:beginner-launch` in release validation and archive the generated reports."
                    if has_beginner_launch_interaction_gate
                    else "Add interaction assertions for launch shortcut prefill and quickstart submit."
                    if has_launch_shortcuts
                    else "Add copyable mission URLs/commands for repeatable starts."
                ),
                "Run a beginner-first screenshot/browser audit before adding more controls.",
            ],
        ),
        AuditCategory(
            category="Multi-project Builder operations",
            score_out_of_20=20 if len(workspaces) > 1 and has_project_health and has_project_progress_history and has_mission_context_roots and has_cross_project_dependency_edges and has_receipt_backed_sync_conflicts and has_interactive_sync_conflict_resolution and has_batch_sync_conflict_resolution and has_parallel_dispatch_evidence else (19 if len(workspaces) > 1 and has_project_health and has_mission_context_roots and has_cross_project_dependency_edges and has_receipt_backed_sync_conflicts and has_interactive_sync_conflict_resolution and has_parallel_dispatch_evidence else (18 if len(workspaces) > 1 and has_project_health and has_mission_context_roots else (17 if len(workspaces) > 1 and has_project_health else (15 if len(workspaces) > 1 else 12)))),
            t3_reference_score_out_of_20=17,
            verdict=(
                "Stronger than T3 Code for multi-project supervision: Builder exposes project health, live per-project progress history, context roots, dependency edges, write-scope preflight, receipt-backed sync conflict review, one-click and batch conflict resolution receipts, plus archived safe parallel-dispatch evidence."
                if has_project_health and has_project_progress_history and has_mission_context_roots and has_cross_project_dependency_edges and has_receipt_backed_sync_conflicts and has_interactive_sync_conflict_resolution and has_batch_sync_conflict_resolution and has_parallel_dispatch_evidence
                else
                "Stronger than T3 Code for multi-project supervision: Builder exposes project health, context roots, dependency edges, write-scope preflight, receipt-backed sync conflict review, one-click and batch conflict resolution receipts, plus archived safe parallel-dispatch evidence."
                if has_project_health and has_mission_context_roots and has_cross_project_dependency_edges and has_receipt_backed_sync_conflicts and has_interactive_sync_conflict_resolution and has_batch_sync_conflict_resolution and has_parallel_dispatch_evidence
                else
                "Stronger than T3 Code for multi-project supervision: Builder exposes project health, context roots, dependency edges, write-scope preflight, receipt-backed sync conflict review, one-click conflict resolution receipts, and archived safe parallel-dispatch evidence."
                if has_project_health and has_mission_context_roots and has_cross_project_dependency_edges and has_receipt_backed_sync_conflicts and has_interactive_sync_conflict_resolution and has_parallel_dispatch_evidence
                else
                "Stronger than T3 Code for multi-project supervision: Builder exposes project health, context roots, dependency edges, write-scope preflight, receipt-backed sync conflict review, and one-click conflict resolution receipts."
                if has_project_health and has_mission_context_roots and has_cross_project_dependency_edges and has_receipt_backed_sync_conflicts and has_interactive_sync_conflict_resolution
                else
                "Stronger than T3 Code for multi-project supervision: Builder exposes project health, context roots, dependency edges, write-scope preflight, and receipt-backed sync conflict review."
                if has_project_health and has_mission_context_roots and has_cross_project_dependency_edges and has_receipt_backed_sync_conflicts
                else
                "Stronger than T3 Code for multi-project supervision: Builder exposes project health, mission context roots, explicit dependency edges, and write-scope preflight before cross-project edits."
                if has_project_health and has_mission_context_roots and has_cross_project_dependency_edges
                else
                "Stronger than T3 Code for multi-project supervision: Builder exposes project health plus mission-level context roots, write scope, sync mirrors, and related project roots."
                if has_project_health and has_mission_context_roots
                else
                "Stronger than T3 Code for multi-project supervision: Builder now exposes project health, latest mission state, sync posture, blockers, and next action."
                if has_project_health
                else "Structurally stronger than T3 Code, but the UI still needs clearer project identity and switching."
            ),
            evidence=[
                "workspace-save/workspace-delete commands exist",
                f"current snapshot workspace count: {len(workspaces)}",
                "workspace profiles include runtime, route, sync, and execution-target preferences",
                f"Builder project-health panel present: {has_project_health}",
                f"live project progress history present: {has_project_progress_history}",
                f"declared dependency-aware scheduler present: {has_dependency_aware_project_scheduler}",
                f"beginner-safe sync authority present: {has_beginner_safe_sync_authority}",
                f"guided cross-device launch rehearsal present: {has_cross_device_launch_rehearsal}",
                f"cross-device launch rehearsal receipt present: {has_cross_device_launch_rehearsal_receipt}",
                f"cross-device launch rehearsal receipt count: {len(cross_device_launch_receipt_history)}",
                f"repeated cross-device launch rehearsal receipts present: {has_repeated_cross_device_launch_rehearsal_receipts}",
                f"cross-device launch receipts attached to release proof: {has_cross_device_launch_receipts_release_proof}",
                f"public release publication packet present: {has_public_release_publication_packet}",
                f"external publication proof present: {has_external_publication_proof}",
                f"latest release artifact pointer present: {has_latest_release_artifact_pointer}",
                f"checksummed public release attachment manifest present: {has_public_release_attachment_manifest}",
                f"mission context roots present: {has_mission_context_roots}",
                f"cross-project dependency edges and write-scope preflight present: {has_cross_project_dependency_edges}",
                f"receipt-backed sync conflict review present: {has_receipt_backed_sync_conflicts}",
                f"interactive sync conflict resolution present: {has_interactive_sync_conflict_resolution}",
                f"batch sync conflict resolution present: {has_batch_sync_conflict_resolution}",
                f"queue-pressure watchdog for parallel worktree candidates present: {has_queue_pressure_watchdog}",
                f"automatic queue-pressure scope safety present: {has_queue_pressure_scope_safety}",
                f"parallel worktree split action present: {has_parallel_worktree_action}",
                f"Builder queue-pressure parallelize button present: {has_parallel_worktree_builder_button}",
                f"parallel dispatch release evidence present: {has_parallel_dispatch_evidence}",
            ],
            gaps=[
                (
                    "Batch conflict resolution, safe parallel dispatch, live project history, declared dependency-aware scheduling, sync authority, guided launch rehearsal, repeated launch receipts, release-proof attachment, public release packet, checksummed attachment manifest, and external release receipt are archived now; the next gap is keeping the trend current on each release candidate."
                    if has_parallel_dispatch_evidence and has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal and has_repeated_cross_device_launch_rehearsal_receipts and has_cross_device_launch_receipts_release_proof and has_public_release_publication_packet and has_public_release_attachment_manifest and has_external_publication_proof
                    else
                    "Batch conflict resolution, safe parallel dispatch, live project history, declared dependency-aware scheduling, sync authority, guided launch rehearsal, repeated launch receipts, release-proof attachment, public release packet, and checksummed attachment manifest are archived now; the next gap is actual external publication or tagging."
                    if has_parallel_dispatch_evidence and has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal and has_repeated_cross_device_launch_rehearsal_receipts and has_cross_device_launch_receipts_release_proof and has_public_release_publication_packet and has_public_release_attachment_manifest
                    else
                    "Batch conflict resolution, safe parallel dispatch, live project history, declared dependency-aware scheduling, sync authority, guided launch rehearsal, repeated launch receipts, release-proof attachment, and a public release publication packet are archived now; the next gap is generating a checksummed attachment manifest and latest artifact pointer."
                    if has_parallel_dispatch_evidence and has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal and has_repeated_cross_device_launch_rehearsal_receipts and has_cross_device_launch_receipts_release_proof and has_public_release_publication_packet
                    else
                    "Batch conflict resolution, safe parallel dispatch, live project history, declared dependency-aware scheduling, sync authority, guided launch rehearsal, repeated launch receipts, and release-proof attachment are archived now; the next gap is a public release publication packet."
                    if has_parallel_dispatch_evidence and has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal and has_repeated_cross_device_launch_rehearsal_receipts and has_cross_device_launch_receipts_release_proof
                    else
                    "Batch conflict resolution, safe parallel dispatch, live project history, declared dependency-aware scheduling, sync authority, guided launch rehearsal, and repeated launch receipts are archived now; the next gap is attaching repeated cross-device proof to public release artifacts."
                    if has_parallel_dispatch_evidence and has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal and has_repeated_cross_device_launch_rehearsal_receipts
                    else
                    "Batch conflict resolution, safe parallel dispatch, live project history, declared dependency-aware scheduling, sync authority, guided launch rehearsal, and launch receipts are archived now; the next gap is repeated cross-device launch proof over time."
                    if has_parallel_dispatch_evidence and has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal and has_cross_device_launch_rehearsal_receipt
                    else
                    "Batch conflict resolution, safe parallel dispatch, live project history, declared dependency-aware scheduling, sync authority, and guided launch rehearsal are archived now; the next gap is proving the rehearsal on a real cross-device mission launch."
                    if has_parallel_dispatch_evidence and has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal
                    else
                    "Batch conflict resolution, safe parallel dispatch, live project history, declared dependency-aware scheduling, and sync authority are archived now; the next gap is guided cross-device launch rehearsal."
                    if has_parallel_dispatch_evidence and has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority
                    else
                    "Batch conflict resolution, safe parallel dispatch, live project history, and declared dependency-aware scheduling are archived now; the next gap is beginner-safe sync truth for local/NAS/cloud."
                    if has_parallel_dispatch_evidence and has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler
                    else
                    "Batch conflict resolution, safe parallel dispatch, and live project history are archived now; the next gap is richer dependency-aware project scheduling."
                    if has_parallel_dispatch_evidence and has_batch_sync_conflict_resolution and has_project_progress_history
                    else
                    "Batch conflict resolution and safe parallel dispatch evidence are archived now; the next gap is historical progress per project."
                    if has_parallel_dispatch_evidence and has_batch_sync_conflict_resolution
                    else
                    "Safe parallel dispatch evidence is archived now; the next gap is batch conflict resolution and historical progress per project."
                    if has_parallel_dispatch_evidence
                    else
                    "Receipt-backed sync conflict review and one-click conflict resolution exist now; the next gap is proving safe live dispatch on recorded file-scope evidence."
                    if has_interactive_sync_conflict_resolution
                    else
                    "Receipt-backed sync conflict handling, queue-pressure detection, planned file-scope inference, automatic scope-safety classification, the parallel worktree split action, and a gated Builder repair button exist now; the next gap is proving safe live dispatch on recorded file-scope evidence."
                    if has_receipt_backed_sync_conflicts and has_queue_pressure_watchdog and has_queue_pressure_scope_safety and has_parallel_worktree_action and has_parallel_worktree_builder_button
                    else
                    "Receipt-backed sync conflict handling, queue-pressure detection, the parallel worktree split action, and a Builder repair button exist now; the next gap is automatic file-scope overlap analysis before dispatch."
                    if has_receipt_backed_sync_conflicts and has_queue_pressure_watchdog and has_parallel_worktree_action and has_parallel_worktree_builder_button
                    else
                    "Receipt-backed sync conflict handling, queue-pressure detection, and a parallel worktree split action exist now; the next gap is a one-click Builder button with file-scope confirmation."
                    if has_receipt_backed_sync_conflicts and has_queue_pressure_watchdog and has_parallel_worktree_action
                    else
                    "Receipt-backed sync conflict handling and queue-pressure detection exist now; the next gap is one-click parallel worktree dispatch from Builder."
                    if has_receipt_backed_sync_conflicts and has_queue_pressure_watchdog
                    else
                    "Receipt-backed sync conflict handling exists now; the next gap is making conflict resolution an interactive Builder flow and detecting queue pressure."
                    if has_receipt_backed_sync_conflicts
                    else "Dependency edges and write-scope preflight exist now; the next gap is executing sync changes with receipt-backed conflict handling."
                    if has_cross_project_dependency_edges
                    else "Mission context roots are visible now; the next gap is explicit cross-project dependency edges and write-safe sync execution."
                    if has_mission_context_roots
                    else
                    "Project health is now visible, but multi-folder context per mission is still limited."
                    if has_project_health
                    else "Project picker/search/visual identity is still called out as partial in the roadmap."
                ),
                (
                    "Batch sync conflict choices, live project history, declared dependency-aware scheduling, sync authority, guided launch rehearsal, repeated receipt proof, release-proof attachment, publication packet generation, checksummed attachment manifest, and external release receipt now share the Builder/release surface; the next gap is keeping these receipts fresh over multiple candidates."
                    if has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal and has_repeated_cross_device_launch_rehearsal_receipts and has_cross_device_launch_receipts_release_proof and has_public_release_publication_packet and has_public_release_attachment_manifest and has_external_publication_proof
                    else
                    "Batch sync conflict choices, live project history, declared dependency-aware scheduling, sync authority, guided launch rehearsal, repeated receipt proof, release-proof attachment, publication packet generation, and checksummed attachment manifest now share the Builder/release surface; the next gap is publishing or tagging it externally."
                    if has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal and has_repeated_cross_device_launch_rehearsal_receipts and has_cross_device_launch_receipts_release_proof and has_public_release_publication_packet and has_public_release_attachment_manifest
                    else
                    "Batch sync conflict choices, live project history, declared dependency-aware scheduling, sync authority, guided launch rehearsal, repeated receipt proof, release-proof attachment, and publication packet generation now share the Builder/release surface; the next gap is checksummed publication attachments."
                    if has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal and has_repeated_cross_device_launch_rehearsal_receipts and has_cross_device_launch_receipts_release_proof and has_public_release_publication_packet
                    else
                    "Batch sync conflict choices, live project history, declared dependency-aware scheduling, sync authority, guided launch rehearsal, repeated receipt proof, and release-proof attachment now share the Builder/release surface; the next gap is generating the public publication packet."
                    if has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal and has_repeated_cross_device_launch_rehearsal_receipts and has_cross_device_launch_receipts_release_proof
                    else
                    "Batch sync conflict choices, live project history, declared dependency-aware scheduling, sync authority, guided launch rehearsal, and repeated receipt proof now share the Builder surface; the next gap is release-proof attachment."
                    if has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal and has_repeated_cross_device_launch_rehearsal_receipts
                    else
                    "Batch sync conflict choices, live project history, declared dependency-aware scheduling, sync authority, guided launch rehearsal, and receipt proof now share the Builder surface; the next gap is repeated real operator rehearsal evidence."
                    if has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal and has_cross_device_launch_rehearsal_receipt
                    else
                    "Batch sync conflict choices, live project history, declared dependency-aware scheduling, sync authority, and guided launch rehearsal now share the Builder surface; the next gap is a real operator rehearsal receipt."
                    if has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal
                    else
                    "Batch sync conflict choices, live project history, declared dependency-aware scheduling, and sync authority now share the Builder surface; the next gap is a beginner guided cross-device launch rehearsal."
                    if has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority
                    else
                    "Batch sync conflict choices, live project history, and declared dependency-aware scheduling now share the Builder surface; the next gap is beginner-safe sync truth across local/NAS/cloud."
                    if has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler
                    else
                    "Batch sync conflict choices and live project history now share the Builder surface; the next gap is dependency-aware scheduling from that history."
                    if has_batch_sync_conflict_resolution and has_project_progress_history
                    else
                    "Batch sync conflict choices now write one receipt covering several conflicts; the next gap is live historical progress per project."
                    if has_batch_sync_conflict_resolution
                    else
                    "Sync conflict choices now write resolution receipts; the next gap is batch resolution for several conflicts at once."
                    if has_interactive_sync_conflict_resolution
                    else
                    "Sync transaction receipts are recorded; conflict choices still need one-click accept/keep/manual review controls."
                    if has_receipt_backed_sync_conflicts
                    else "Cross-project dependency links are first-class; write-safe sync still needs transaction receipts."
                    if has_cross_project_dependency_edges
                    else "Cross-project dependency links are not first-class yet."
                    if has_mission_context_roots
                    else "Mission-level multi-folder context remains limited."
                ),
                (
                    "Repeated cross-device launch receipts are attached to release proof, summarized in the publication packet, listed in a checksummed attachment manifest, and externally published now; the next gap is keeping repeated proof attached to future candidates."
                    if has_repeated_cross_device_launch_rehearsal_receipts and has_cross_device_launch_receipts_release_proof and has_public_release_publication_packet and has_public_release_attachment_manifest and has_external_publication_proof
                    else
                    "Repeated cross-device launch receipts are attached to release proof, summarized in the publication packet, and listed in a checksummed attachment manifest now; the next gap is actual external release publication."
                    if has_repeated_cross_device_launch_rehearsal_receipts and has_cross_device_launch_receipts_release_proof and has_public_release_publication_packet and has_public_release_attachment_manifest
                    else
                    "Repeated cross-device launch receipts are attached to release proof and summarized in the publication packet now; the next gap is checksummed publication attachments."
                    if has_repeated_cross_device_launch_rehearsal_receipts and has_cross_device_launch_receipts_release_proof and has_public_release_publication_packet
                    else
                    "Repeated cross-device launch receipts are attached to release proof now; the next gap is generating public release notes and a publication manifest beside the candidate."
                    if has_repeated_cross_device_launch_rehearsal_receipts and has_cross_device_launch_receipts_release_proof
                    else
                    "Repeated cross-device launch receipts are archived now; the next gap is attaching the trend to release proof."
                    if has_repeated_cross_device_launch_rehearsal_receipts
                    else
                    "Cross-device launch receipt is archived now; the next gap is repeating this proof across more project pairs."
                    if has_cross_device_launch_rehearsal_receipt
                    else
                    "Guided launch rehearsal is visible now; the next gap is archiving a real cross-device launch receipt from that checklist."
                    if has_cross_device_launch_rehearsal
                    else
                    "Sync authority is visible now; the next gap is a guided rehearsal that launches a mission after the operator chooses the write authority."
                    if has_beginner_safe_sync_authority
                    else "Sync truth for local/NAS/cloud is not yet a beginner-safe flow."
                ),
            ],
            next_moves=[
                (
                    "Keep the external release receipt attached when Builder produces the next proof/archive candidate."
                    if has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal and has_repeated_cross_device_launch_rehearsal_receipts and has_cross_device_launch_receipts_release_proof and has_public_release_publication_packet and has_public_release_attachment_manifest and has_external_publication_proof
                    else
                    "Publish or tag the release candidate with the publication packet, latest artifact pointer, and checksummed proof attachments."
                    if has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal and has_repeated_cross_device_launch_rehearsal_receipts and has_cross_device_launch_receipts_release_proof and has_public_release_publication_packet and has_public_release_attachment_manifest
                    else
                    "Generate a checksummed publication attachment manifest and latest release artifact pointer for the repeated cross-device proof archive."
                    if has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal and has_repeated_cross_device_launch_rehearsal_receipts and has_cross_device_launch_receipts_release_proof and has_public_release_publication_packet
                    else
                    "Generate public release notes and a publication manifest for the repeated cross-device proof archive."
                    if has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal and has_repeated_cross_device_launch_rehearsal_receipts and has_cross_device_launch_receipts_release_proof
                    else
                    "Attach the repeated cross-device launch receipt trend to release proof artifacts."
                    if has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal and has_repeated_cross_device_launch_rehearsal_receipts
                    else
                    "Repeat cross-device launch rehearsal receipts across more project pairs and keep them attached to release proof."
                    if has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal and has_cross_device_launch_rehearsal_receipt
                    else
                    "Run and archive a real cross-device launch rehearsal receipt that proves the checklist leads into a mission launch."
                    if has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority and has_cross_device_launch_rehearsal
                    else
                    "Add a guided cross-device launch rehearsal that verifies sync authority, dependency safety, and launch route in one operator flow."
                    if has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler and has_beginner_safe_sync_authority
                    else
                    "Turn the dependency-aware scheduling queue into guided sync/launch choices that explain local, NAS, and cloud write authority."
                    if has_batch_sync_conflict_resolution and has_project_progress_history and has_dependency_aware_project_scheduler
                    else
                    "Use per-project progress history to recommend dependency-aware next missions and project scheduling."
                    if has_batch_sync_conflict_resolution and has_project_progress_history
                    else
                    "Add per-project progress history over time, not only the latest mission."
                    if has_batch_sync_conflict_resolution
                    else
                    "Run batch sync-conflict resolution receipts across several projects and archive the result."
                    if has_parallel_dispatch_evidence
                    else
                    "Run live sync-conflict resolution receipts on a real multi-project pair and archive the result."
                    if has_interactive_sync_conflict_resolution
                    else
                    "Run the watcher against live queued missions and archive a receipt when one planned-scope-safe lane is split into its own worktree."
                    if has_receipt_backed_sync_conflicts and has_queue_pressure_watchdog and has_queue_pressure_scope_safety and has_parallel_worktree_action and has_parallel_worktree_builder_button
                    else
                    "Add automatic file-scope overlap analysis and show the result before enabling one-click parallel dispatch."
                    if has_receipt_backed_sync_conflicts and has_queue_pressure_watchdog and has_parallel_worktree_action and has_parallel_worktree_builder_button
                    else
                    "Add a Builder button that calls `parallelize-worktree` after a file-scope overlap review."
                    if has_receipt_backed_sync_conflicts and has_queue_pressure_watchdog and has_parallel_worktree_action
                    else
                    "Add one-click parallel worktree dispatch after watchdog queue-pressure review."
                    if has_receipt_backed_sync_conflicts and has_queue_pressure_watchdog
                    else
                    "Add interactive conflict resolution controls that write a follow-up receipt."
                    if has_receipt_backed_sync_conflicts
                    else "Add receipt-backed sync execution and conflict review for dependency edges."
                    if has_cross_project_dependency_edges
                    else "Add cross-project dependency links and preflight write-scope confirmation for multi-root missions."
                    if has_mission_context_roots
                    else
                    "Add multi-folder mission context and cross-project dependency links."
                    if has_project_health
                    else "Make Builder's project list searchable and visually distinct."
                ),
                (
                    "Add per-project progress history over time, not only the latest mission."
                    if has_project_health
                    else "Show last mission, runtime, failing check, and next action per project."
                ),
                (
                    "Add batch conflict resolution after the one-file receipt path is proven on real project syncs."
                    if has_interactive_sync_conflict_resolution
                    else "Add mission-level multi-folder context before broad team features."
                ),
            ],
        ),
        AuditCategory(
            category="Harness and sub-agent capability",
            score_out_of_20=20 if has_runtime_supervisor and has_subagent_lanes and has_harness_parity and has_subagent_lane_controls and has_route_mutation_receipts and has_route_rollback_receipts and has_live_cross_category_outcome_validation else (19 if has_runtime_supervisor and has_subagent_lanes and has_harness_parity and has_subagent_lane_controls else (18 if has_runtime_supervisor and has_subagent_lanes and has_harness_parity else (17 if has_runtime_supervisor and has_subagent_lanes else (16 if has_runtime_supervisor else 11)))),
            t3_reference_score_out_of_20=18,
            verdict=(
                "Ahead of T3 Code on harness/sub-agent operation: Hermes-first lanes, route mutation and rollback receipts, outcome-trend routing, value-scored route trust, and live cross-category Hermes outcome validation are all present."
                if has_subagent_lanes and has_harness_parity and has_subagent_lane_controls and has_route_mutation_receipts and has_route_rollback_receipts and has_live_cross_category_outcome_validation
                else
                "Better mission supervision than T3 Code, with explicit sub-agent lanes, proof drill-down, route-mutation receipts, failed-route rollback receipts, and a Hermes/OpenClaw/legacy parity matrix visible in Builder."
                if has_subagent_lanes and has_harness_parity and has_subagent_lane_controls and has_route_mutation_receipts and has_route_rollback_receipts
                else
                "Better mission supervision than T3 Code, with explicit sub-agent lanes, lane-level controls, proof drill-down, route-mutation receipts, and a Hermes/OpenClaw/legacy parity matrix visible in Builder."
                if has_subagent_lanes and has_harness_parity and has_subagent_lane_controls and has_route_mutation_receipts
                else
                "Better mission supervision than T3 Code, with explicit sub-agent lanes, lane-level controls, proof drill-down, and a Hermes/OpenClaw/legacy parity matrix visible in Builder."
                if has_subagent_lanes and has_harness_parity and has_subagent_lane_controls
                else
                "Better mission supervision than T3 Code, with explicit sub-agent lanes and a Hermes/OpenClaw/legacy parity matrix visible in Builder."
                if has_subagent_lanes and has_harness_parity
                else
                "Better mission supervision than T3 Code, with explicit planner/executor/verifier sub-agent lanes now visible in Builder."
                if has_subagent_lanes
                else "Better mission supervision than T3 Code, but sub-agent controls are not yet operator-grade."
            ),
            evidence=[
                f"runtime supervisor present: {has_runtime_supervisor}",
                f"delegated run rate: {quality.get('delegatedRunRate')}",
                "Hermes and OpenClaw are modeled as selectable runtime lanes",
                f"Builder sub-agent lane panel present: {has_subagent_lanes}",
                f"Builder lane controls and proof drill-down present: {has_subagent_lane_controls}",
                f"Hermes/OpenClaw parity matrix present: {has_harness_parity}",
                f"task-aware provider/model routing present: {has_task_aware_model_routing}",
                f"per-lane task-fit route proof present: {has_task_fit_lane_proof}",
                f"route mutation receipts present: {has_route_mutation_receipts}",
                f"failed-route rollback receipts present: {has_route_rollback_receipts}",
                f"outcome-trend routing present: {has_outcome_trend_routing}",
                f"launch route-trust confidence present: {has_launch_route_trust_confidence}",
                (
                    "live cross-category Hermes outcome validation: "
                    f"{live_cross_category_outcome_validation.get('status', 'missing')} "
                    f"({live_cross_category_outcome_validation.get('validatedCategoryCount', 0)}/"
                    f"{live_cross_category_outcome_validation.get('requiredCategoryCount', 0)} categories)"
                ),
            ],
            gaps=[
                (
                    "Live cross-category Hermes outcome validation is passed; keep expanding the trend across fresh task families."
                    if has_live_cross_category_outcome_validation
                    else
                    "Outcome-trend routing exists now; the next gap is proving it on live model-backed missions over time."
                    if has_outcome_trend_routing
                    else "Failed-route rollback receipts exist now; the next gap is outcome-trend routing from mission history."
                    if has_route_rollback_receipts
                    else "Route mutation receipts exist now; the next gap is automatic rollback when a rerouted lane fails verification."
                    if has_route_mutation_receipts
                    else "Lane controls and proof drill-down are present now; the next gap is direct per-lane route mutation with validation receipts."
                    if has_subagent_lane_controls
                    else "Sub-agent lanes are visible now; the next gap is active lane controls and per-lane proof drill-down."
                    if has_subagent_lanes
                    else "Sub-agent fanout is mostly backend/configured behavior, not a clear UI workflow."
                ),
                (
                    "Contextual runtime/model guidance is now covered by beginner launch browser interaction proof."
                    if has_contextual_launch_recommendation and has_beginner_launch_interaction_gate
                    else
                    "Contextual runtime/model guidance exists in mission launch; the next gap is validating beginner launch behavior with browser interaction tests."
                    if has_contextual_launch_recommendation
                    else "Beginner guidance exists now; the next gap is making runtime choice contextual during mission launch."
                    if has_harness_parity
                    else "The product cannot yet explain when to use OpenClaw versus Hermes in beginner language."
                ),
                (
                    "Route-change receipts, task-fit proof, rollback, outcome trends, launch confidence, and live cross-category validation are visible; the next check is keeping the trend fresh."
                    if has_route_mutation_receipts and has_task_fit_lane_proof and has_route_rollback_receipts and has_outcome_trend_routing and has_launch_route_trust_confidence and has_live_cross_category_outcome_validation
                    else
                    "Route-change receipts, task-fit proof, rollback, outcome trends, and launch confidence are visible; the next gap is live trend validation across more task categories."
                    if has_route_mutation_receipts and has_task_fit_lane_proof and has_route_rollback_receipts and has_outcome_trend_routing and has_launch_route_trust_confidence
                    else
                    "Route-change receipts, task-fit proof, rollback, and outcome trends are visible; the next gap is exposing confidence at launch."
                    if has_route_mutation_receipts and has_task_fit_lane_proof and has_route_rollback_receipts and has_outcome_trend_routing
                    else "Route-change receipts, task-fit proof, and failed-route rollback are visible; the next gap is outcome-trend model selection."
                    if has_route_mutation_receipts and has_task_fit_lane_proof and has_route_rollback_receipts
                    else "Route-change receipts and task-fit proof are visible; the next gap is outcome-trend model selection and automatic failed-route rollback."
                    if has_route_mutation_receipts and has_task_fit_lane_proof
                    else "Route-change receipts are visible after live reroutes; the next gap is trend-based model selection from mission outcomes."
                    if has_route_mutation_receipts
                    else "Task-aware routing exists now; the next gap is showing task fit and route-change proof in each lane."
                    if has_task_aware_model_routing and not has_task_fit_lane_proof
                    else "Task-aware routing exists now; the next gap is showing route-change receipts after live reroutes."
                    if has_task_aware_model_routing
                    else "Provider-runtime truth is improving, but still needs first-class proof in the UI."
                ),
            ],
            next_moves=[
                (
                    "Keep rerunning live Hermes validation across new categories so the outcome trend stays current."
                    if has_live_cross_category_outcome_validation
                    else
                    "Run repeated live missions per task category so outcome trends can become stronger than static defaults."
                    if has_outcome_trend_routing
                    else "Persist outcome trends per task type so route recommendations improve after successes and rollbacks."
                    if has_route_rollback_receipts
                    else "Add automatic verification-triggered rollback receipts for failed reroutes."
                    if has_route_mutation_receipts
                    else "Add route mutation receipts that prove a reroute changed provider/model and kept the mission state coherent."
                    if has_subagent_lane_controls
                    else "Add per-lane actions for reroute, pause, resume, and proof drill-down."
                    if has_subagent_lanes
                    else "Add a Sub-agents panel with planner/executor/verifier lanes, status, and last proof."
                ),
                (
                    "Use launch confidence to steer more value-scored trust missions by task category."
                    if has_launch_route_trust_confidence
                    else
                    "Expose outcome-trend confidence beside each task-fit lane in the launch flow."
                    if has_outcome_trend_routing
                    else "Use mission outcome history to adjust task-fit route recommendations and rollback failed route changes."
                    if has_task_fit_lane_proof and has_route_mutation_receipts
                    else "Attach route rationale and fallback proof directly to each lane."
                    if has_subagent_lanes
                    else "Expose route rationale and fallback policy per lane."
                ),
                (
                    "Use the parity matrix to drive runtime recommendations in quickstart."
                    if has_harness_parity
                    else "Add a harness parity matrix for OpenClaw, Hermes, local shim, and legacy engine."
                ),
            ],
        ),
        AuditCategory(
            category="Web availability and distribution",
            score_out_of_20=20 if has_web and has_web_notifications and has_browser_notifications and has_responsive_smoke and has_launch_shortcuts and has_overnight_digest and has_notification_delivery_receipts and has_out_of_band_watchdog_notifications and has_public_web_distribution_contract and has_public_web_release_candidate_attachment else (19 if has_web and has_web_notifications and has_browser_notifications and has_responsive_smoke and has_launch_shortcuts and has_overnight_digest and has_notification_delivery_receipts and has_out_of_band_watchdog_notifications else (18 if has_web and has_web_notifications and has_browser_notifications and has_responsive_smoke and has_launch_shortcuts and has_overnight_digest and has_notification_delivery_receipts else (18 if has_web and has_web_notifications and has_browser_notifications and has_responsive_smoke and has_launch_shortcuts else (17 if has_web and has_web_notifications and has_browser_notifications and has_responsive_smoke else (16 if has_web and has_web_notifications and has_browser_notifications else (15 if has_web and has_web_notifications else (14 if has_web else 8))))))),
            t3_reference_score_out_of_20=18,
            verdict=(
                "Ahead of T3-style web availability: web console, desktop shell, browser alerts, installable PWA, GitHub Pages deployment contract, release-candidate deployment receipt attachment, responsive smoke, launch URLs, overnight digest, delivery receipts, and out-of-band watchdog notifications are present."
                if has_web_notifications and has_browser_notifications and has_responsive_smoke and has_launch_shortcuts and has_overnight_digest and has_notification_delivery_receipts and has_out_of_band_watchdog_notifications and has_public_web_distribution_contract and has_public_web_release_candidate_attachment
                else
                "Ahead of T3-style web availability: web console, desktop shell, browser alerts, installable PWA, GitHub Pages deployment contract, responsive smoke, launch URLs, overnight digest, delivery receipts, and out-of-band watchdog notifications are present."
                if has_web_notifications and has_browser_notifications and has_responsive_smoke and has_launch_shortcuts and has_overnight_digest and has_notification_delivery_receipts and has_out_of_band_watchdog_notifications and has_public_web_distribution_contract
                else
                "Ahead of T3-style private web availability for this operator: web console, desktop shell, browser alerts, responsive smoke, launch URLs, app-like overnight digest, receipt-backed delivery proof, and out-of-band Telegram watchdog notifications are present; public packaging is the remaining gap."
                if has_web_notifications and has_browser_notifications and has_responsive_smoke and has_launch_shortcuts and has_overnight_digest and has_notification_delivery_receipts and has_out_of_band_watchdog_notifications
                else
                "Ahead of T3-style private web availability for this operator: web console, desktop shell, browser alerts, responsive smoke, launch URLs, app-like overnight phone digest, and receipt-backed notification delivery proof are present; public packaging is the remaining gap."
                if has_web_notifications and has_browser_notifications and has_responsive_smoke and has_launch_shortcuts and has_overnight_digest and has_notification_delivery_receipts
                else
                "Ahead of T3-style private web availability for this operator: web console, desktop shell, browser alerts, responsive smoke, launch URLs, and an app-like overnight phone digest are present; public packaging is the remaining gap."
                if has_web_notifications and has_browser_notifications and has_responsive_smoke and has_launch_shortcuts and has_overnight_digest
                else
                "Matches T3-style web availability for private use: web console, desktop shell, browser alerts, repeatable responsive smoke, and copyable launch URLs are present; public packaging is the remaining gap."
                if has_web_notifications and has_browser_notifications and has_responsive_smoke and has_launch_shortcuts
                else
                "Has a web console, desktop shell, browser alerts, and repeatable phone/tablet/desktop visual smoke; distribution still needs one-click packaging."
                if has_web_notifications and has_browser_notifications and has_responsive_smoke
                else
                "Has a web console, desktop shell, summary feed, and permission-gated browser alerts; distribution is still weaker than T3's npx/desktop install story."
                if has_web_notifications and has_browser_notifications
                else
                "Has a web console, desktop shell, and mobile-friendly notification feed, but distribution is weaker than T3's npx/desktop install story."
                if has_web_notifications
                else "Has a web console and desktop shell, but distribution is weaker than T3's npx/desktop install story."
            ),
            evidence=[
                f"web app present: {has_web}",
                f"Tauri shell present: {has_tauri}",
                f"web notification summary present: {has_web_notifications}",
                f"browser notification permission flow present: {has_browser_notifications}",
                f"overnight phone digest present: {has_overnight_digest}",
                f"notification delivery receipts present: {has_notification_delivery_receipts}",
                f"out-of-band watchdog Telegram notifications present: {has_out_of_band_watchdog_notifications}",
                f"closed-tab Web Push sender path present: {has_closed_tab_web_push_sender}",
                f"closed-tab Web Push sender configured: {has_web_push_sender_configured}",
                f"closed-tab Web Push browser subscriptions: {int(web_push_sender_status.get('subscriptionCount') or 0)}",
                f"ntfy phone push configured: {has_ntfy_sender_configured}",
                f"ntfy delivered receipt present: {has_ntfy_delivered_receipt}",
                f"mobile push delivery proof present: {has_mobile_push_delivery_proof}",
                f"installable PWA shell and offline fallback present: {has_installable_pwa_shell}",
                f"public web distribution contract present: {has_public_web_distribution_contract}",
                f"public web release-candidate attachment present: {has_public_web_release_candidate_attachment}",
                f"external publication proof present: {has_external_publication_proof}",
                f"external mission watchdog supervisor loop present: {has_external_watchdog_supervisor_loop}",
                f"backend watchdog autostart present: {has_external_watchdog_autostart}",
                f"durable watchdog problem registry present: {has_watchdog_problem_registry}",
                f"responsive visual smoke present: {has_responsive_smoke}",
                f"copyable launch URL/command shortcuts present: {has_launch_shortcuts}",
                f"one-command web launcher present: {has_one_command_launcher}",
                "package scripts expose frontend build, backend, Tauri dev/build, and NAS setup",
            ],
            gaps=[
                web_push_distribution_gap,
                web_push_notification_gap,
                "Tauri build is still a heavier validation path than a fast web-only smoke.",
            ],
            next_moves=[
                (
                    "Keep Pages deployment, GitHub release receipt, and notification receipts current on each candidate."
                    if has_public_web_release_candidate_attachment and has_external_publication_proof
                    else
                    "Publish or tag release candidates with the attached GitHub Pages deployment receipt."
                    if has_public_web_release_candidate_attachment
                    else
                    "Attach the GitHub Pages deployment receipt artifact to each release candidate."
                    if has_public_web_distribution_contract
                    else "Maintain a web-only validation path for NAS/headless contexts."
                ),
                (
                    "Move ntfy from public random-topic proof to self-hosted or token-protected production settings."
                    if has_ntfy_sender_configured and has_ntfy_delivered_receipt
                    else
                    "Register a real phone/tablet browser subscription and archive a Web Push delivery receipt."
                    if has_web_push_sender_configured and not has_web_push_subscription
                    else
                    "Send and archive a real closed-tab Web Push delivery receipt from a subscribed phone/tablet browser."
                    if has_web_push_sender_configured and has_web_push_subscription
                    else
                    "Provision production VAPID keys and keep Web Push/Telegram receipts enabled for unattended NAS runs."
                    if has_closed_tab_web_push_sender and has_out_of_band_watchdog_notifications and has_external_watchdog_supervisor_loop and has_external_watchdog_autostart
                    else
                    "Keep watchdog Telegram receipts enabled for unattended NAS runs."
                    if has_out_of_band_watchdog_notifications and has_external_watchdog_supervisor_loop and has_external_watchdog_autostart
                    else
                    "Enable backend watchdog autostart for unattended NAS runs."
                    if has_out_of_band_watchdog_notifications and has_external_watchdog_supervisor_loop
                    else
                    "Run the external watchdog supervisor loop for unattended NAS runs."
                    if has_out_of_band_watchdog_notifications
                    else
                    "Add service-worker push or Telegram-send execution receipts for closed-tab phone updates."
                    if has_notification_delivery_receipts
                    else "Add delivery receipts for browser/Telegram overnight digest sends."
                    if has_overnight_digest
                    else "Add a private web health page that explains SSH/Tailscale/backend status without logs."
                ),
                (
                    "Keep `verify:web-distribution` in Pages and release-proof CI."
                    if has_public_web_distribution_contract
                    else "Promote the local launcher to public `npx` or signed desktop packaging."
                    if has_one_command_launcher
                    else "Package a zero-config local launcher comparable to `npx t3`."
                ),
            ],
        ),
        AuditCategory(
            category="Proof, verification, and trust",
            score_out_of_20=20 if required.get("score", 0) >= 90 and has_proof_digest and has_side_by_side_proof_diff and has_proof_digest_export else (19 if required.get("score", 0) >= 90 and has_proof_digest and has_side_by_side_proof_diff else (18 if required.get("score", 0) >= 90 and has_proof_digest else (17 if required.get("score", 0) >= 90 else 13))),
            t3_reference_score_out_of_20=14,
            verdict=(
                "Neyvia's strongest advantage over T3-style tools is durable proof, with mission proof digests, side-by-side diff review, and export/share artifacts available from the control room."
                if has_proof_digest and has_side_by_side_proof_diff and has_proof_digest_export
                else
                "Neyvia's strongest advantage over T3-style tools is durable proof, with mission proof digests plus side-by-side diff review now visible in Builder."
                if has_proof_digest and has_side_by_side_proof_diff
                else
                "Neyvia's strongest advantage over T3-style tools is durable proof, and mission proof digests now make that evidence readable in the UI."
                if has_proof_digest
                else "Neyvia's strongest advantage over T3-style tools is durable proof, but proof review UX still lags."
            ),
            evidence=[
                f"release readiness status: {release.get('status')}",
                f"required gates: {required.get('passed')}/{required.get('total')}",
                f"verification pause rate: {quality.get('verificationPauseRate')}",
                f"mission proof digest present: {has_proof_digest}",
                f"side-by-side proof diff present: {has_side_by_side_proof_diff}",
                f"proof digest export/share present: {has_proof_digest_export}",
                f"release proof archive present: {has_release_proof_archive}",
                f"release proof CI enforcement present: {has_release_proof_ci}",
                f"latest release artifact pointer present: {has_latest_release_artifact_pointer}",
                f"checksummed public release attachment manifest present: {has_public_release_attachment_manifest}",
                f"external publication proof present: {has_external_publication_proof}",
            ],
            gaps=[
                (
                    "Proof digest, side-by-side diff, export/share, release-proof archiving, CI upload, latest artifact pointer, checksummed public attachments, and external release receipt are present now; the next gap is keeping that proof bundle fresh across candidates."
                    if has_release_proof_ci and has_public_release_attachment_manifest and has_external_publication_proof
                    else
                    "Proof digest, side-by-side diff, export/share, release-proof archiving, CI upload, latest artifact pointer, and checksummed public attachments are present now; the next gap is external publication/tagging of the candidate."
                    if has_release_proof_ci and has_public_release_attachment_manifest
                    else
                    "Proof digest, side-by-side diff, export/share, release-proof archiving, and CI upload are present now; the next gap is attaching those archives with a checksummed publication manifest."
                    if has_release_proof_ci
                    else
                    "Proof digest, side-by-side diff, export/share, and release-proof archiving exist now; the next gap is CI publication of those archives."
                    if has_release_proof_archive
                    else
                    "Proof digest, side-by-side diff, and export/share exist now; the next gap is archiving generated proof-diff reports in release artifacts automatically."
                    if has_proof_digest and has_side_by_side_proof_diff and has_proof_digest_export
                    else
                    "Proof digest and side-by-side diff exist now; the next gap is export/share and long-history release evidence."
                    if has_proof_digest and has_side_by_side_proof_diff
                    else "Proof digest exists; the next gap is proving side-by-side diff and artifact paging under large histories."
                    if has_proof_digest
                    else "Proof is still split across logs, mission snapshots, and docs."
                ),
                (
                    "Side-by-side proof review is present; keep it covered by the long-history browser gate."
                    if has_side_by_side_proof_diff
                    else "Side-by-side diff and proof review are listed as partial."
                ),
                "Some optional readiness items can look like blockers even when they are not required.",
            ],
            next_moves=[
                (
                    "Keep the release receipt and checksummed attachment manifest refreshed for every release candidate."
                    if has_release_proof_ci and has_public_release_attachment_manifest and has_external_publication_proof
                    else
                    "Publish or tag the release candidate using the latest release artifact pointer and checksummed publication attachments."
                    if has_release_proof_ci and has_public_release_attachment_manifest
                    else
                    "Generate checksummed publication attachments beside each release candidate."
                    if has_release_proof_ci
                    else
                    "Keep proof digest exports and long-history browser reports archived for each release candidate."
                    if has_release_proof_archive
                    else
                    "Archive generated proof digest exports and proof-diff browser reports as release artifacts."
                    if has_proof_digest_export
                    else
                    "Add proof digest export/share and archive generated proof-diff reports."
                    if has_side_by_side_proof_diff
                    else "Add proof digest export/share and artifact paging."
                    if has_proof_digest
                    else "Create one proof digest per mission with checks, changed files, route, auth path, and next action."
                ),
                (
                    "Keep side-by-side proof diff in `verify:long-history` and CI."
                    if has_side_by_side_proof_diff
                    else "Add side-by-side diff with wrap toggle to Builder proof review."
                ),
                "Separate required blockers from recommended polish in readiness copy.",
            ],
        ),
        AuditCategory(
            category="Speed and long-history performance",
            score_out_of_20=20 if has_summary_payload and has_lazy_mission_detail and has_virtual_timeline and has_performance_budget and has_browser_performance_budget and has_virtual_transcript and has_lazy_proof_artifacts and has_long_history_browser_fixture and has_release_proof_archive and has_release_proof_ci else (19 if has_summary_payload and has_lazy_mission_detail and has_virtual_timeline and has_performance_budget and has_browser_performance_budget and has_virtual_transcript and has_lazy_proof_artifacts and has_long_history_browser_fixture and has_release_proof_archive else (18 if has_summary_payload and has_lazy_mission_detail and has_virtual_timeline and has_performance_budget and has_browser_performance_budget and has_virtual_transcript and has_lazy_proof_artifacts and has_long_history_browser_fixture else (17 if has_summary_payload and has_lazy_mission_detail and has_virtual_timeline and has_performance_budget and has_browser_performance_budget else (16 if has_summary_payload and has_lazy_mission_detail and has_virtual_timeline and has_performance_budget else (14 if has_summary_payload and has_lazy_mission_detail and has_virtual_timeline else (13 if has_summary_payload and has_lazy_mission_detail else (12 if has_summary_payload else 10))))))),
            t3_reference_score_out_of_20=18,
            verdict=(
                "Summary-first loading, warm live-summary cache, lazy mission detail, virtualized timelines/transcripts, lazy proof paging, endpoint budgets, long-history browser fixtures, release proof archiving, and CI evidence upload are now present."
                if has_summary_payload and has_bootstrap_summary_cache and has_lazy_mission_detail and has_virtual_timeline and has_performance_budget and has_browser_performance_budget and has_virtual_transcript and has_lazy_proof_artifacts and has_long_history_browser_fixture and has_release_proof_archive and has_release_proof_ci
                else
                "Summary-first loading, lazy mission detail, virtualized timelines/transcripts, lazy proof paging, endpoint budgets, long-history browser fixtures, release proof archiving, and CI evidence upload are now present."
                if has_summary_payload and has_lazy_mission_detail and has_virtual_timeline and has_performance_budget and has_browser_performance_budget and has_virtual_transcript and has_lazy_proof_artifacts and has_long_history_browser_fixture and has_release_proof_archive and has_release_proof_ci
                else
                "Summary-first loading, lazy mission detail, virtualized timelines/transcripts, lazy proof paging, endpoint budgets, long-history browser fixtures, and release proof archiving are now present."
                if has_summary_payload and has_lazy_mission_detail and has_virtual_timeline and has_performance_budget and has_browser_performance_budget and has_virtual_transcript and has_lazy_proof_artifacts and has_long_history_browser_fixture and has_release_proof_archive
                else
                "Summary-first loading, lazy mission detail, virtualized timelines/transcripts, lazy proof paging, endpoint budgets, and long-history browser fixtures are now present."
                if has_summary_payload and has_lazy_mission_detail and has_virtual_timeline and has_performance_budget and has_browser_performance_budget and has_virtual_transcript and has_lazy_proof_artifacts and has_long_history_browser_fixture
                else
                "Summary-first loading, lazy mission detail, virtualized Builder timelines, virtualized chat transcripts, lazy proof-artifact paging, endpoint budgets, and browser speed gates are now present."
                if has_summary_payload and has_lazy_mission_detail and has_virtual_timeline and has_performance_budget and has_browser_performance_budget and has_virtual_transcript and has_lazy_proof_artifacts
                else
                "Summary-first loading, lazy mission detail, virtualized Builder timelines, endpoint budgets, and browser-measured warm-tab/mission-switch/proof-pane gates are now present; broad transcript and proof virtualization still need to land."
                if has_summary_payload and has_lazy_mission_detail and has_virtual_timeline and has_performance_budget and has_browser_performance_budget
                else
                "Summary-first loading, lazy mission detail, virtualized Builder timelines, and explicit payload/duration budgets now make long-history performance measurable; broad transcript and proof virtualization still need to land."
                if has_summary_payload and has_lazy_mission_detail and has_virtual_timeline and has_performance_budget
                else
                "Summary-first loading, lazy mission detail, and virtualized Builder timelines reduce the worst long-history costs; measured large-history gates are still missing."
                if has_summary_payload and has_lazy_mission_detail and has_virtual_timeline
                else
                "Summary-first loading and lazy mission detail reduce broad payload pulls, but T3 still wins on proven virtualized long-history interaction."
                if has_summary_payload and has_lazy_mission_detail
                else
                "Summary-first loading reduces the worst control-room payload cost, but T3 still wins on proven virtualized long-history interaction."
                if has_summary_payload
                else "Biggest product gap: T3 wins on perceived speed and low-bloat interaction."
            ),
            evidence=[
                "roadmap explicitly marks transcript virtualization and instant tab switching as missing",
                (
                    "Builder reference timeline now uses bounded/virtualized rendering"
                    if has_virtual_timeline
                    else "no current audit evidence for 5,000+ timeline item smoothness"
                ),
                (
                    "control-room-summary plus control-room-mission-detail split status from lazy mission proof/detail"
                    if has_lazy_mission_detail
                    else
                    "control-room-summary command and build_summary_snapshot provide a lightweight status payload"
                    if has_summary_payload
                    else "current product carries heavy mission/control-room payloads"
                ),
                f"control-room performance budget present: {has_performance_budget}",
                f"in-process live summary endpoint present: {has_in_process_summary_endpoint}",
                f"warm live summary cache present: {has_bootstrap_summary_cache}",
                f"browser performance budget present: {has_browser_performance_budget}",
                f"bounded/virtualized Builder timeline present: {has_virtual_timeline}",
                f"bounded Builder timeline rows present: {has_bounded_builder_timeline}",
                f"bounded/virtualized chat transcript present: {has_virtual_transcript}",
                f"bounded Agent transcript rows present: {has_bounded_agent_transcript}",
                f"lazy/bounded proof artifact surfaces present: {has_lazy_proof_artifacts}",
                f"paged proof diff and capped artifact rows present: {has_bounded_proof_artifact_surfaces}",
                f"side-by-side proof diff present: {has_side_by_side_proof_diff}",
                f"long-history browser fixture present: {has_long_history_browser_fixture}",
                f"long-history release gate present: {has_long_history_release_gate}",
                f"release proof archive present: {has_release_proof_archive}",
                f"release proof CI enforcement present: {has_release_proof_ci}",
                f"latest release artifact pointer present: {has_latest_release_artifact_pointer}",
                f"checksummed public release attachment manifest present: {has_public_release_attachment_manifest}",
                f"external publication proof present: {has_external_publication_proof}",
            ],
            gaps=[
                (
                    "Long-history browser fixtures, release-gate scripts, proof archiving, CI artifact upload, warm in-process live summary dispatch, latest artifact pointer, checksummed attachment manifest, and external release receipt exist now; the next gap is proving this publication cadence across future candidates."
                    if has_release_proof_ci and has_public_release_attachment_manifest and has_bootstrap_summary_cache and has_external_publication_proof
                    else
                    "Long-history browser fixtures, release-gate scripts, proof archiving, CI artifact upload, warm in-process live summary dispatch, latest artifact pointer, and checksummed attachment manifest exist now; the next gap is publishing those artifacts beside signed/public releases."
                    if has_release_proof_ci and has_public_release_attachment_manifest and has_bootstrap_summary_cache
                    else
                    "Long-history browser fixtures, release-gate scripts, proof archiving, CI artifact upload, in-process live summary dispatch, latest artifact pointer, and checksummed attachment manifest exist now; the next gap is publishing those artifacts beside signed/public releases."
                    if has_release_proof_ci and has_public_release_attachment_manifest
                    else
                    "Long-history browser fixtures, release-gate scripts, proof archiving, CI artifact upload, and in-process live summary dispatch exist now; the next gap is generating checksummed public release attachments."
                    if has_release_proof_ci
                    else
                    "Long-history browser fixtures, a release-gate script, and proof archiving exist now; the next gap is running that archive in CI on every release candidate."
                    if has_release_proof_archive
                    else
                    "Long-history browser fixtures and a release-gate script exist now; the next gap is running that script in CI on every frontend change."
                    if has_long_history_release_gate
                    else
                    "Long-history browser fixtures exist now; the next gap is adding a release-gate script and running it in CI on every frontend change."
                    if has_long_history_browser_fixture
                    else
                    "Transcript virtualization and lazy proof paging exist now; the next gap is running browser speed gates against intentionally huge transcript/proof fixtures."
                    if has_virtual_transcript and has_lazy_proof_artifacts
                    else
                    "Builder timeline is virtualized now; chat transcripts and proof artifact lists still need the same treatment."
                    if has_virtual_timeline
                    else "No proven virtualized transcript/timeline path."
                ),
                (
                    "Side-by-side diff review is included in the long-history CI release gate, uploaded as release proof, listed in checksummed public attachments, and attached to an external release receipt."
                    if has_release_proof_ci and has_public_release_attachment_manifest and has_external_publication_proof
                    else
                    "Side-by-side diff review is included in the long-history CI release gate, uploaded as release proof, and listed in checksummed public attachments; the next gap is release-candidate publication."
                    if has_release_proof_ci and has_public_release_attachment_manifest
                    else
                    "Side-by-side diff review is included in the long-history CI release gate and uploaded as release proof; the next gap is checksummed release-candidate attachments."
                    if has_release_proof_ci
                    else
                    "Side-by-side diff review is included in the long-history release gate and archived as release proof; the next gap is automatic publication of that archive."
                    if has_release_proof_archive
                    else
                    "Side-by-side diff review is included in the long-history release gate now; the next gap is archiving those reports as release proof."
                    if has_side_by_side_proof_diff and has_long_history_release_gate
                    else "Side-by-side diff review still needs the same long-history coverage."
                    if has_long_history_browser_fixture
                    else
                    "Proof artifact paging exists; side-by-side diff and artifact review still need the same large-history fixture coverage."
                    if has_lazy_proof_artifacts
                    else
                    "Performance budgets exist now; proof/timeline panes still need viewport virtualization and lazy artifact paging."
                    if has_performance_budget
                    else
                    "Mission detail is lazy now, but proof/timeline panes still need viewport virtualization and measured budgets."
                    if has_lazy_mission_detail
                    else
                    "The summary path exists, but detail panes still need lazy mission/proof endpoints."
                    if has_summary_payload
                    else "Control-room snapshots can become too large for fast UI updates."
                ),
                (
                    "Browser speed gates now have long-history fixtures, archived reports, and CI upload evidence."
                    if has_release_proof_ci
                    else
                    "Browser speed gates now have long-history fixtures and archived reports; the next gap is enforcing them in CI."
                    if has_release_proof_archive
                    else
                    "Browser speed gates now have a long-history fixture; the next gap is committing generated budget reports as release proof."
                    if has_long_history_browser_fixture
                    else
                    "Browser speed gates exist now; the next gap is long transcript/proof fixtures rather than control-route-only checks."
                    if has_browser_performance_budget and has_virtual_transcript and has_lazy_proof_artifacts
                    else
                    "Browser speed gates exist now; the next gap is running them against long transcript/proof fixtures, not only the control route."
                    if has_browser_performance_budget
                    else
                    "Endpoint budgets exist, but warm-tab and mission-switch interaction latency are still not measured in browser smoke."
                    if has_performance_budget
                    else "No measured warm-tab or mission-switch latency budget in the release gate."
                ),
            ],
            next_moves=[
                (
                    "Keep release-proof CI artifacts attached to each external release candidate using the latest artifact pointer."
                    if has_release_proof_ci and has_public_release_attachment_manifest and has_external_publication_proof
                    else
                    "Publish release-proof CI artifacts beside signed/public release candidates using the latest artifact pointer."
                    if has_release_proof_ci and has_public_release_attachment_manifest
                    else
                    "Generate a checksummed release attachment manifest before publishing release-proof CI artifacts."
                    if has_release_proof_ci
                    else
                    "Wire `verify:release-artifacts` into CI and release readiness evidence."
                    if has_release_proof_archive
                    else
                    "Wire `verify:long-history` into CI and release readiness evidence."
                    if has_long_history_release_gate
                    else
                    "Promote long-history responsive smoke to a package script, CI, and release readiness evidence."
                    if has_long_history_browser_fixture
                    else
                    "Add long transcript/proof fixtures to responsive smoke and fail the build if transcript/proof panes exceed budget."
                    if has_virtual_transcript and has_lazy_proof_artifacts
                    else
                    "Extend virtualization to chat transcripts, proof artifacts, and runtime output."
                    if has_virtual_timeline
                    else "Virtualize mission timeline, proof events, and runtime output."
                ),
                (
                    "Keep release proof archives, latest pointers, and checksummed attachment manifests uploaded from CI for every release candidate."
                    if has_release_proof_ci and has_public_release_attachment_manifest
                    else
                    "Keep release proof archives uploaded from CI for every release candidate."
                    if has_release_proof_ci
                    else
                    "Publish release proof archives alongside release candidates."
                    if has_release_proof_archive
                    else
                    "Capture and archive long-history budget reports in release artifacts."
                    if has_long_history_release_gate or has_long_history_browser_fixture
                    else
                    "Extend browser speed budgets to long-history transcript and proof artifact panes."
                    if has_lazy_proof_artifacts
                    else
                    "Add lazy proof-artifact paging and browser-measured mission-switch latency gates."
                    if has_performance_budget
                    else
                    "Add lazy proof-artifact paging and explicit mission-switch latency gates."
                    if has_lazy_mission_detail
                    else
                    "Add lazy mission-detail and proof-detail endpoints after the summary path."
                    if has_summary_payload
                    else "Split control-room payload into summary plus lazy detail endpoints."
                ),
                (
                    "Keep uploaded CI proof archives and their checksummed attachment manifest in release notes/downloads."
                    if has_release_proof_ci and has_public_release_attachment_manifest and has_external_publication_proof
                    else
                    "Promote uploaded CI proof archives and their checksummed attachment manifest into release notes/downloads."
                    if has_release_proof_ci and has_public_release_attachment_manifest
                    else
                    "Promote uploaded CI proof archives into release notes/downloads."
                    if has_release_proof_ci
                    else
                    "Run release proof archiving in CI before claiming release-grade performance."
                    if has_release_proof_archive
                    else
                    "Run the long-history fixture in CI before claiming release-grade performance."
                    if has_long_history_release_gate or has_long_history_browser_fixture
                    else
                    "Add long transcript/proof artifact fixtures to the browser speed budget suite."
                    if has_browser_performance_budget
                    else
                    "Record warm-tab, mission-switch, and proof-pane render budgets in responsive smoke."
                    if has_performance_budget
                    else "Add performance gates for mission switch and timeline rendering."
                ),
            ],
        ),
        AuditCategory(
            category="Roadmap clarity and self-improvement",
            score_out_of_20=20 if has_workflow_docs and has_skill_library and has_red_team_escalation and has_red_team_escalation_history and has_red_team_escalation_builder_trend and has_skill_feedback_loop and has_system_loss_skill_routing and has_skill_repair_proposals and has_approved_skill_repair_application and has_operator_value_closeout and has_operator_value_route_trust and has_operator_value_skill_trust and has_self_improvement_evidence_contract else (19 if has_workflow_docs and has_skill_library and has_red_team_escalation and has_red_team_escalation_history and has_skill_feedback_loop and has_system_loss_skill_routing and has_skill_repair_proposals and has_self_improvement_evidence_contract else (18 if has_workflow_docs and has_skill_library and has_red_team_escalation and has_skill_feedback_loop else (17 if has_workflow_docs and has_skill_library and has_red_team_escalation else (16 if has_workflow_docs and has_skill_library else 12)))),
            t3_reference_score_out_of_20=14,
            verdict=(
                "Roadmap is unusually strong, red-team proof now persists escalation history, Builder shows the difficulty trend, high-gap learned skills have approval-gated repair receipts, and operator-value closeouts feed future route and skill trust."
                if has_red_team_escalation and has_red_team_escalation_history and has_red_team_escalation_builder_trend and has_skill_feedback_loop and has_system_loss_skill_routing and has_skill_repair_proposals and has_approved_skill_repair_application and has_operator_value_closeout and has_operator_value_route_trust and has_operator_value_skill_trust
                else
                "Roadmap is unusually strong, red-team proof now persists escalation history, Builder shows the difficulty trend, high-gap learned skills have approval-gated repair receipts, and operator-value closeouts feed future route trust."
                if has_red_team_escalation and has_red_team_escalation_history and has_red_team_escalation_builder_trend and has_skill_feedback_loop and has_system_loss_skill_routing and has_skill_repair_proposals and has_approved_skill_repair_application and has_operator_value_closeout and has_operator_value_route_trust
                else
                "Roadmap is unusually strong, red-team proof now persists escalation history, Builder shows the difficulty trend, high-gap learned skills have approval-gated repair receipts, and mission closeout records operator value."
                if has_red_team_escalation and has_red_team_escalation_history and has_red_team_escalation_builder_trend and has_skill_feedback_loop and has_system_loss_skill_routing and has_skill_repair_proposals and has_approved_skill_repair_application and has_operator_value_closeout
                else
                "Roadmap is unusually strong, red-team proof now persists escalation history, Builder shows the difficulty trend, and high-gap learned skills have approval-gated repair application receipts plus validation gates."
                if has_red_team_escalation and has_red_team_escalation_history and has_red_team_escalation_builder_trend and has_skill_feedback_loop and has_system_loss_skill_routing and has_skill_repair_proposals and has_approved_skill_repair_application
                else
                "Roadmap is unusually strong, red-team proof now persists escalation history, and high-gap learned skills have approval-gated repair application receipts plus validation gates."
                if has_red_team_escalation and has_red_team_escalation_history and has_skill_feedback_loop and has_system_loss_skill_routing and has_skill_repair_proposals and has_approved_skill_repair_application
                else
                "Roadmap is unusually strong, red-team proof escalates difficulty, and high-gap learned skills now have approval-gated repair application receipts plus validation gates."
                if has_red_team_escalation and has_skill_feedback_loop and has_system_loss_skill_routing and has_skill_repair_proposals and has_approved_skill_repair_application
                else
                "Roadmap is unusually strong, red-team proof escalates difficulty, and high-gap skills now generate repair proposals with before/after validation gates."
                if has_red_team_escalation and has_skill_feedback_loop and has_system_loss_skill_routing and has_skill_repair_proposals
                else
                "Roadmap is unusually strong, red-team proof escalates difficulty, and mission-slice gap now changes skill routing instead of only reporting scores."
                if has_red_team_escalation and has_skill_feedback_loop and has_system_loss_skill_routing
                else
                "Roadmap is unusually strong, red-team proof escalates difficulty, and mission slices now feed skill loss/improvement scores back into Skill Studio."
                if has_red_team_escalation and has_skill_feedback_loop
                else
                "Roadmap is unusually strong, and red-team proof now records next-difficulty escalation after clean passes."
                if has_red_team_escalation
                else "Roadmap is unusually strong, but self-improvement must become closed-loop, not document-driven."
            ),
            evidence=[
                f"1.0 release doc present: {has_workflow_docs}",
                f"skill library present: {has_skill_library}",
                "release phases already separate reliability, human-quality workbench, skills, services, workflow hardening, and validation",
                f"red-team difficulty escalation present: {has_red_team_escalation}",
                f"red-team escalation history present: {has_red_team_escalation_history}",
                f"adaptive red-team benchmark consumes prior escalation targets: {has_adaptive_red_team_benchmark}",
                f"Builder-visible red-team escalation trend present: {has_red_team_escalation_builder_trend}",
                f"mission-slice skill feedback loop present: {has_skill_feedback_loop}",
                f"system-gap skill routing present: {has_system_loss_skill_routing}",
                f"automatic skill repair proposals present: {has_skill_repair_proposals}",
                f"approved skill repair application present: {has_approved_skill_repair_application}",
                f"operator-value mission closeout present: {has_operator_value_closeout}",
                f"operator-value route trust present: {has_operator_value_route_trust}",
                f"operator-value route trust proven: {has_operator_value_route_trust_proven}",
                f"route trust coverage plan present: {has_route_trust_coverage_plan}",
                f"launch-ready route trust sampling missions present: {has_route_trust_launch_templates}",
                f"operator-value skill trust present: {has_operator_value_skill_trust}",
                f"self-improvement evidence archive present: {has_self_improvement_evidence_contract}",
                f"bounded red-team auto-advance loop present: {has_self_improvement_red_team_loop}",
                f"watchdog self-improvement cadence present: {has_self_improvement_watchdog_cadence}",
                f"watchdog self-improvement history present: {has_self_improvement_watchdog_history}",
                f"watchdog self-improvement history receipts: {len(watchdog_history_rows)} total / {watchdog_completed_receipts} completed",
                f"watchdog self-improvement trend proven: {has_self_improvement_watchdog_trend}",
            ],
            gaps=[
                (
                    "Self-improvement evidence, live route trust, bounded red-team auto-advance, watchdog cadence, and several completed watchdog receipts are proven; the next gap is external release publication/tagging of the trend evidence."
                    if has_self_improvement_evidence_contract and has_operator_value_route_trust_proven and has_self_improvement_red_team_loop and has_self_improvement_watchdog_cadence and has_self_improvement_watchdog_history and has_self_improvement_watchdog_trend
                    else
                    "Self-improvement evidence, live route trust, bounded red-team auto-advance, watchdog cadence, and append-only watchdog history are present; the next gap is collecting several scheduled completed receipts over time."
                    if has_self_improvement_evidence_contract and has_operator_value_route_trust_proven and has_self_improvement_red_team_loop and has_self_improvement_watchdog_cadence and has_self_improvement_watchdog_history
                    else
                    "Self-improvement evidence, live route trust, bounded red-team auto-advance, and watchdog cadence wiring are present; the next gap is adding append-only receipt history and proving several scheduled cadence receipts over time."
                    if has_self_improvement_evidence_contract and has_operator_value_route_trust_proven and has_self_improvement_red_team_loop and has_self_improvement_watchdog_cadence
                    else
                    "Self-improvement evidence, live route trust, and a bounded red-team auto-advance command are present; the next gap is scheduling that loop into the overnight watchdog cadence."
                    if has_self_improvement_evidence_contract and has_operator_value_route_trust_proven and has_self_improvement_red_team_loop
                    else
                    "Self-improvement evidence and live route trust are proven; the next gap is turning the point-in-time proof into longer automatic improvement trends."
                    if has_self_improvement_evidence_contract and has_operator_value_route_trust_proven
                    else
                    "Self-improvement evidence is now archived in release proof; the next gap is executing enough value-scored live missions to turn sampling categories into proven categories."
                    if has_self_improvement_evidence_contract
                    else
                    "Operator-value route and skill trust now have launch-ready sampling missions; the next gap is executing those value-scored live missions."
                    if has_operator_value_route_trust and has_operator_value_skill_trust and has_route_trust_launch_templates
                    else
                    "Operator-value route and skill trust now have a Builder-visible sampling plan; the next gap is executing those value-scored live missions."
                    if has_operator_value_route_trust and has_operator_value_skill_trust and has_route_trust_coverage_plan
                    else
                    "Operator-value route and skill trust exist now; the next gap is proving several value-scored live missions by task category."
                    if has_operator_value_route_trust and has_operator_value_skill_trust
                    else
                    "Operator-value route trust exists now; the next gap is proving several value-scored live missions by task category."
                    if has_operator_value_route_trust
                    else
                    "Approved repair application exists now; the next gap is proving several repaired skills with clean validation slices over time."
                    if has_approved_skill_repair_application
                    else
                    "Automatic repair proposals exist now; the next gap is applying repair patches to editable learned skills after human review."
                    if has_skill_repair_proposals
                    else
                    "Skill feedback now affects routing; the next gap is automatic skill repair proposals with before/after verification."
                    if has_system_loss_skill_routing
                    else
                    "Skill feedback is now scored per slice; the next gap is using several runs before automatically promoting or repairing a skill."
                    if has_skill_feedback_loop
                    else "Skill promotion and workflow reuse are still described as goals more than proven UI behavior."
                ),
                (
                    "Red-team escalation is adaptive now: prior clean-pass targets generate harder follow-up attempts; the next gap is running enough live model-backed suites to show trend quality over time."
                    if has_adaptive_red_team_benchmark and has_red_team_escalation_builder_trend
                    else
                    "Red-team escalation is visible in Builder now; the next gap is making the next benchmark consume the prior target budget and tactic list automatically."
                    if has_red_team_escalation_builder_trend
                    else
                    "Red-team escalation history exists; the next gap is showing trend lines directly in Builder."
                    if has_red_team_escalation_history
                    else
                    "Red-team escalation metadata exists; the next gap is persisting trend history across runs."
                    if has_red_team_escalation
                    else "Red-team project should raise difficulty over time, not only repeat the same passing benchmark."
                ),
                (
                    "Operator-value closeouts now prove route and skill trust across tracked task categories; the next gap is validating promotion quality over a longer trend."
                    if has_operator_value_route_trust_proven and has_operator_value_skill_trust
                    else
                    "Operator-value closeouts now affect route recommendations and skill selection; the next gap is enough live samples to prove promotion quality."
                    if has_operator_value_route_trust and has_operator_value_skill_trust
                    else
                    "Operator-value closeouts now affect route recommendations; the next gap is applying the same value weighting to skill promotion after enough samples."
                    if has_operator_value_route_trust
                    else
                    "Operator-value closeout exists now; the next gap is feeding closeout value back into automatic route/skill weight after enough samples."
                    if has_operator_value_closeout
                    else
                    "Operator-value trust scoring still needs mission closeout input."
                    if has_skill_feedback_loop
                    else "Trust scoring is still a 1.1 idea rather than a current feedback loop."
                ),
            ],
            next_moves=[
                (
                    "Archive the completed watchdog trend receipts with the next public release candidate."
                    if has_self_improvement_evidence_contract and has_operator_value_route_trust_proven and has_self_improvement_red_team_loop and has_self_improvement_watchdog_cadence and has_self_improvement_watchdog_history and has_self_improvement_watchdog_trend
                    else
                    "Let the watchdog cadence collect repeated completed receipts in watchdog_history.jsonl, then archive those trend receipts with release proof."
                    if has_self_improvement_evidence_contract and has_operator_value_route_trust_proven and has_self_improvement_red_team_loop and has_self_improvement_watchdog_cadence and has_self_improvement_watchdog_history
                    else
                    "Let the watchdog cadence collect repeated self-improvement receipts, then archive those trend receipts with release proof."
                    if has_self_improvement_evidence_contract and has_operator_value_route_trust_proven and has_self_improvement_red_team_loop and has_self_improvement_watchdog_cadence
                    else
                    "Run the bounded red-team auto-advance command from the watchdog cadence, then archive the resulting trend evidence with release proof."
                    if has_self_improvement_evidence_contract and has_operator_value_route_trust_proven and has_self_improvement_red_team_loop
                    else
                    "Keep archiving self-improvement evidence and run the next harder red-team benchmark so the improvement loop proves trend quality, not only route coverage."
                    if has_self_improvement_evidence_contract and has_operator_value_route_trust_proven
                    else
                    "Use the archived self-improvement evidence file to pick and run the next missing value-scored task category."
                    if has_self_improvement_evidence_contract
                    else
                    "Run the next archived red-team target, then keep repeating until several target/follow-up pairs prove increasing difficulty over time."
                    if has_adaptive_red_team_benchmark and has_red_team_escalation_builder_trend
                    else
                    "Run live model-backed red-team suites until the trend proves increasing difficulty over time."
                    if has_red_team_escalation_builder_trend
                    else
                    "Show red-team escalation trend lines directly in Builder."
                    if has_red_team_escalation_history
                    else
                    "Persist red-team escalation history per project and show trend lines in Builder."
                    if has_red_team_escalation
                    else "Add difficulty escalation metrics to defensive red-team missions."
                ),
                (
                    "Run clean validation slices after applied repairs and use those receipts to restore routing weight."
                    if has_approved_skill_repair_application
                    else
                    "Apply approved repair proposals to editable learned skills, then require a clean validation slice before reuse."
                    if has_skill_repair_proposals
                    else
                    "Generate repair diffs for high-gap skills and require a clean validation slice before reuse."
                    if has_system_loss_skill_routing
                    else
                    "Gate skill promotion on multiple low-gap slices plus human review."
                    if has_skill_feedback_loop
                    else "Promote repeated mission wins into reviewed skills automatically after review."
                ),
                (
                    "Archive self-improvement evidence in every release proof bundle and keep periodic Hermes route-trust sampling active."
                    if has_self_improvement_evidence_contract and has_operator_value_route_trust_proven
                    else
                    "Archive self-improvement evidence in every release proof bundle until all task categories are proven."
                    if has_self_improvement_evidence_contract
                    else
                    "Use the Builder sampling plan to run value-scored missions in the uncovered task categories."
                    if has_operator_value_route_trust and has_operator_value_skill_trust and has_route_trust_coverage_plan
                    else
                    "Run value-scored live missions so route and skill trust have enough per-category samples."
                    if has_operator_value_route_trust and has_operator_value_skill_trust
                    else
                    "Run value-scored live missions so route trust has enough per-category samples."
                    if has_operator_value_route_trust
                    else "Add operator-value trust scoring to every mission closeout."
                ),
            ],
        ),
    ]
    has_queue_first_builder = (
        "Queue-first Builder" in reference_shell_text
        and 'data-live-builder-command-band="true"' in reference_shell_text
    )
    has_thread_first_agent = (
        "Thread-first Agent" in reference_shell_text
        and 'data-live-agent-thread-first-band="true"' in reference_shell_text
    )
    has_selected_report_reader = (
        "Selected live report" in reference_shell_text
        and 'data-live-selected-report-reader="true"' in reference_shell_text
    )
    has_agent_advanced_drawers = (
        'data-agent-advanced-drawer="true"' in reference_shell_text
        and 'data-agent-advanced-drawer-kind="runtime"' in reference_shell_text
        and 'data-agent-advanced-drawer-kind="plan"' in reference_shell_text
    )
    has_agent_clarity_mode = (
        'data-agent-clarity-mode={normalizedAgentClarityMode}' in reference_shell_text
        and 'data-agent-clarity-switch="true"' in reference_shell_text
        and "fluxio.agent.clarityMode" in reference_shell_text
    )
    has_builder_clarity_mode = (
        'data-builder-clarity-mode={normalizedBuilderClarityMode}' in reference_shell_text
        and 'data-builder-clarity-switch="true"' in reference_shell_text
        and 'data-builder-operator-priority="true"' in reference_shell_text
        and 'fluxio.builder.clarityMode' in reference_shell_text
    )
    has_workbench_clarity_mode = (
        'data-workbench-clarity-mode={normalizedWorkbenchClarityMode}' in reference_shell_text
        and 'data-live-workbench-clarity-switch="true"' in reference_shell_text
        and "fluxio.workbench.clarityMode" in reference_shell_text
    )
    has_skills_clarity_mode = (
        'data-skills-clarity-mode={normalizedSkillsClarityMode}' in reference_shell_text
        and 'data-skills-focus-contract="user-skill-editor-first"' in reference_shell_text
        and 'data-user-skill-library="true"' in reference_shell_text
        and "save_codex_skill_command" in reference_shell_text
        and "fluxio.skills.clarityMode" in reference_shell_text
    )
    has_cross_surface_clarity_mode = (
        has_agent_clarity_mode
        and has_builder_clarity_mode
        and has_workbench_clarity_mode
        and has_skills_clarity_mode
    )
    has_live_workbench_proof_band = 'data-live-workbench-proof-band="true"' in reference_shell_text
    has_live_workbench_execution_surface = (
        'data-live-workbench-execution="true"' in reference_shell_text
        and 'data-live-workbench-execution-receipts="true"' in reference_shell_text
        and 'data-live-workbench-execution-missing="true"' in reference_shell_text
        and "workbench:run-artifact-check" in reference_shell_text
    )
    has_system_loss_builder_surface = (
        "System gap breakdown" in reference_shell_text
        and 'data-system-loss-current="true"' in reference_shell_text
    )
    has_phone_progress_surface = (
        'value: "phone"' in reference_shell_text
        or "Phone" in reference_shell_text and "data-live-phone-progress" in reference_shell_text
    )
    has_phone_notification_compact_tray = (
        "shouldStartNotificationStackCollapsed" in shell_text
        and 'window.matchMedia("(max-width: 760px)")' in shell_text
        and "collapsedHeadline" in shell_text
        and "collapsedBody" in shell_text
        and "data-notification-stack-expanded" in shell_text
        and "notification-stack-collapsed-mode" in styles_text
    )
    ui_score = 10 + sum(
        1
        for flag in (
            has_queue_first_builder,
            has_thread_first_agent,
            has_selected_report_reader,
            has_agent_advanced_drawers,
            has_builder_clarity_mode,
            has_cross_surface_clarity_mode,
            has_live_workbench_proof_band,
            has_live_workbench_execution_surface,
            has_system_loss_builder_surface,
            has_phone_progress_surface,
            has_phone_notification_compact_tray,
        )
        if flag
    )
    categories.append(
        AuditCategory(
            category="Interface clarity and operator ergonomics",
            score_out_of_20=min(
                ui_score + (1 if has_live_mission_output_quality_cleared else 0),
                20
                if has_live_workbench_execution_surface and has_live_mission_output_quality_cleared
                else 19
                if has_live_workbench_execution_surface
                else 18
                if has_builder_clarity_mode
                else 17,
            ),
            t3_reference_score_out_of_20=17,
            verdict=(
                "Neyvia now has live-first Builder, Agent, Workbench, system-gap, phone surfaces, Agent advanced drawers, Builder focus/full clarity mode, Workbench artifact execution receipts, and current live mission output proof."
                if has_live_mission_output_quality_cleared
                else "Neyvia now has live-first Builder, Agent, Workbench, system-gap, phone surfaces, Agent advanced drawers, a Builder focus/full clarity mode, and a primary Workbench artifact execution receipt surface; the remaining gap is proving real served artifacts from weak completed missions."
            ),
            evidence=[
                f"queue-first Builder band present: {has_queue_first_builder}",
                f"thread-first Agent band present: {has_thread_first_agent}",
                f"selected live report reader present: {has_selected_report_reader}",
                f"Agent advanced diagnostics drawers present: {has_agent_advanced_drawers}",
                f"Builder focus/full clarity mode present: {has_builder_clarity_mode}",
                f"cross-surface focus/full clarity mode present: {has_cross_surface_clarity_mode}",
                f"Agent focus/full clarity mode present: {has_agent_clarity_mode}",
                f"Workbench focus/full clarity mode present: {has_workbench_clarity_mode}",
                f"Skills focus/full clarity mode present: {has_skills_clarity_mode}",
                f"live Workbench proof band present: {has_live_workbench_proof_band}",
                f"live Workbench artifact execution surface present: {has_live_workbench_execution_surface}",
                f"system-gap Builder surface present: {has_system_loss_builder_surface}",
                f"phone progress surface present: {has_phone_progress_surface}",
                f"phone compact notification tray present: {has_phone_notification_compact_tray}",
                f"live mission output quality cleared: {has_live_mission_output_quality_cleared}",
                f"responsive smoke present: {has_responsive_smoke}",
                f"authenticated beginner-launch gate present: {has_beginner_launch_interaction_gate}",
            ],
            gaps=[
                (
                    "Completed weak-mission proof is clear in the current live evidence; keep the proof fresh as new missions complete."
                    if has_live_mission_output_quality_cleared
                    else "Workbench now exposes a primary artifact execution receipt surface, but completed weak missions still need real served artifacts or runtime-output bodies to prove the flow end to end."
                ),
                (
                    "Builder, Agent, Workbench, and Skills now share the same focus/full contract; keep responsive proof fresh."
                    if has_cross_surface_clarity_mode
                    else "Agent diagnostics, lanes, trace, and plan steps are in drawers now; remaining clarity work is making all surfaces follow the same focus/full contract."
                ),
                (
                    "Workbench proof is currently grounded in live runtime output and artifact evidence."
                    if has_live_mission_output_quality_cleared
                    else "Workbench is now safe from stale live iframes and will not invent missing artifacts, but artifact repair still depends on mission runtime output quality."
                ),
            ],
            next_moves=[
                (
                    "Keep the cross-surface focus/full contract covered by authenticated visual checks."
                    if has_cross_surface_clarity_mode
                    else "Carry the Builder focus/full contract into Agent, Workbench, and Skills."
                ),
                (
                    "Keep checking new completed missions from the Workbench execution surface before treating them as useful."
                    if has_live_mission_output_quality_cleared
                    else "Relaunch or resume transcript-only completed missions with a hard served-artifact gate, then verify them from the Workbench execution surface."
                ),
                "Move Builder route-trust and publication proof into the same kind of progressive disclosure.",
            ],
        )
    )
    strict_evidence = {
        "has_one_command_launcher": has_one_command_launcher,
        "has_agent_advanced_drawers": has_agent_advanced_drawers,
        "has_agent_clarity_mode": has_agent_clarity_mode,
        "has_builder_clarity_mode": has_builder_clarity_mode,
        "has_workbench_clarity_mode": has_workbench_clarity_mode,
        "has_skills_clarity_mode": has_skills_clarity_mode,
        "has_cross_surface_clarity_mode": has_cross_surface_clarity_mode,
        "has_live_workbench_execution_surface": has_live_workbench_execution_surface,
        "has_live_mission_output_quality_cleared": has_live_mission_output_quality_cleared,
        "has_receipt_backed_sync_conflicts": has_receipt_backed_sync_conflicts,
        "has_interactive_sync_conflict_resolution": has_interactive_sync_conflict_resolution,
        "has_batch_sync_conflict_resolution": has_batch_sync_conflict_resolution,
        "has_project_progress_history": has_project_progress_history,
        "has_dependency_aware_project_scheduler": has_dependency_aware_project_scheduler,
        "has_beginner_safe_sync_authority": has_beginner_safe_sync_authority,
        "has_cross_device_launch_rehearsal": has_cross_device_launch_rehearsal,
        "has_cross_device_launch_rehearsal_receipt": has_cross_device_launch_rehearsal_receipt,
        "has_repeated_cross_device_launch_rehearsal_receipts": has_repeated_cross_device_launch_rehearsal_receipts,
        "has_cross_device_launch_receipts_release_proof": has_cross_device_launch_receipts_release_proof,
        "has_public_release_publication_packet": has_public_release_publication_packet,
        "has_latest_release_artifact_pointer": has_latest_release_artifact_pointer,
        "has_public_release_attachment_manifest": has_public_release_attachment_manifest,
        "has_route_mutation_receipts": has_route_mutation_receipts,
        "has_route_rollback_receipts": has_route_rollback_receipts,
        "has_outcome_trend_routing": has_outcome_trend_routing,
        "has_launch_route_trust_confidence": has_launch_route_trust_confidence,
        "has_live_cross_category_outcome_validation": has_live_cross_category_outcome_validation,
        "has_long_history_release_gate": has_long_history_release_gate,
        "has_release_proof_archive": has_release_proof_archive,
        "has_release_proof_ci": has_release_proof_ci,
        "has_skill_repair_proposals": has_skill_repair_proposals,
        "has_approved_skill_repair_application": has_approved_skill_repair_application,
        "has_operator_value_closeout": has_operator_value_closeout,
        "has_operator_value_route_trust": has_operator_value_route_trust,
        "has_operator_value_route_trust_proven": has_operator_value_route_trust_proven,
        "has_route_trust_coverage_plan": has_route_trust_coverage_plan,
        "has_route_trust_launch_templates": has_route_trust_launch_templates,
        "has_operator_value_skill_trust": has_operator_value_skill_trust,
        "has_red_team_escalation_builder_trend": has_red_team_escalation_builder_trend,
        "has_adaptive_red_team_benchmark": has_adaptive_red_team_benchmark,
        "has_self_improvement_evidence_contract": has_self_improvement_evidence_contract,
        "has_self_improvement_red_team_loop": has_self_improvement_red_team_loop,
        "has_self_improvement_watchdog_cadence": has_self_improvement_watchdog_cadence,
        "has_self_improvement_watchdog_history": has_self_improvement_watchdog_history,
        "has_self_improvement_watchdog_trend": has_self_improvement_watchdog_trend,
        "self_improvement_watchdog_history_receipts": len(watchdog_history_rows),
        "self_improvement_watchdog_completed_receipts": watchdog_completed_receipts,
        "has_overnight_digest": has_overnight_digest,
        "has_out_of_band_watchdog_notifications": has_out_of_band_watchdog_notifications,
        "has_external_watchdog_supervisor_loop": has_external_watchdog_supervisor_loop,
        "has_external_watchdog_autostart": has_external_watchdog_autostart,
        "has_watchdog_problem_registry": has_watchdog_problem_registry,
        "has_installable_pwa_shell": has_installable_pwa_shell,
        "has_public_web_distribution_contract": has_public_web_distribution_contract,
        "has_public_web_release_candidate_attachment": has_public_web_release_candidate_attachment,
        "has_web_push_subscription": has_web_push_subscription,
        "has_ntfy_sender_configured": has_ntfy_sender_configured,
        "has_ntfy_delivered_receipt": has_ntfy_delivered_receipt,
        "has_mobile_push_delivery_proof": has_mobile_push_delivery_proof,
        "has_active_runtime_budget_exhausted": has_active_runtime_budget_exhausted,
        "has_npx_style_launcher_package": has_npx_style_launcher_package,
        "has_launcher_package_release_receipt": has_launcher_package_release_receipt,
        "has_public_launch_readiness_report": has_public_launch_readiness_report,
        "has_public_launch_internal_packet_ready": has_public_launch_internal_packet_ready,
        "has_public_launch_ready": has_public_launch_ready,
        "has_external_publication_proof": has_external_publication_proof,
        "has_beginner_launch_interaction_gate": has_beginner_launch_interaction_gate,
        "has_storage_aware_quickstart_fallback": has_storage_aware_quickstart_fallback,
        "has_in_process_summary_endpoint": has_in_process_summary_endpoint,
        "has_bootstrap_summary_cache": has_bootstrap_summary_cache,
        "has_live_mission_artifact_repairs": bool(
            (
                isinstance(live_mission_output_quality, dict)
                and
                isinstance(live_mission_output_quality.get("weakMissionRows"), list)
                and live_mission_output_quality.get("weakMissionRows")
            )
            or (
                isinstance(mission_artifact_repair_plan, dict)
                and
                isinstance(mission_artifact_repair_plan.get("repairs"), list)
                and mission_artifact_repair_plan.get("repairs")
            )
        ),
        "has_nas_storage_pressure_critical": _nas_storage_pressure_is_blocking(nas_storage_pressure)
        if isinstance(nas_storage_pressure, dict) and nas_storage_pressure
        else False,
    }
    return _apply_strict_score_caps(categories, strict_evidence)


def _project_progress(
    root: Path,
    snapshot: dict[str, Any],
    *,
    live_nas_evidence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    live_current = _live_project_progress_from_evidence(
        "Current workspace",
        root,
        live_nas_evidence or {},
    )
    if live_current:
        return [live_current]

    projects: list[tuple[str, Path]] = [
        ("Current workspace", root),
    ]
    for workspace in snapshot.get("workspaces", []):
        workspace_root = Path(str(workspace.get("root_path") or ""))
        if workspace_root and workspace_root != root:
            projects.append((str(workspace.get("name") or workspace_root.name), workspace_root))

    seen: set[str] = set()
    progress: list[dict[str, Any]] = []
    for name, project_root in projects:
        key = str(project_root)
        if key in seen:
            continue
        seen.add(key)
        progress.append(_single_project_progress(name, project_root))
    return progress


def _red_team_escalation_evidence(
    root: Path,
    *,
    snapshot: dict[str, Any],
    live_nas_system_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    synced = (
        live_nas_system_audit.get("redTeamEscalationEvidence", {})
        if isinstance(live_nas_system_audit, dict)
        else {}
    )
    local = _local_red_team_escalation_snapshot(root, snapshot)
    if (
        isinstance(synced, dict)
        and synced.get("schema") == "fluxio.red_team_escalation_snapshot.v1"
        and live_nas_system_audit
        and live_nas_system_audit.get("status") == "passed"
    ):
        if _red_team_snapshot_is_newer(local, synced):
            return {
                **_normalize_red_team_snapshot(local),
                "source": "local_agent_control",
                "supersededSyncedSourcePath": str(
                    live_nas_system_audit.get("sourcePath") or synced.get("sourcePath") or ""
                ),
                "supersededSyncedCheckedAt": str(live_nas_system_audit.get("checkedAt") or ""),
            }
        return {
            **_normalize_red_team_snapshot(synced),
            "source": "live_nas_system_audit",
            "sourcePath": str(live_nas_system_audit.get("sourcePath") or synced.get("sourcePath") or ""),
            "sourceCheckedAt": str(live_nas_system_audit.get("checkedAt") or ""),
        }

    if local:
        return {
            **_normalize_red_team_snapshot(local),
            "source": local.get("source") or "local_agent_control",
        }

    return _unavailable_red_team_escalation_snapshot("No red-team escalation evidence was found.")


def _local_red_team_escalation_snapshot(root: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    local_snapshot = snapshot.get("redTeamEscalation", {})
    if (
        isinstance(local_snapshot, dict)
        and local_snapshot.get("schema") == "fluxio.red_team_escalation_snapshot.v1"
    ):
        return {
            **local_snapshot,
            "source": "control_room_snapshot",
        }
    try:
        return {
            **build_red_team_escalation_snapshot(root),
            "source": "local_agent_control",
        }
    except Exception as exc:
        return _unavailable_red_team_escalation_snapshot(str(exc))


def _normalize_red_team_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or snapshot.get("schema") != "fluxio.red_team_escalation_snapshot.v1":
        return snapshot
    history = [
        normalize_red_team_pressure(row)
        for row in (snapshot.get("history", []) if isinstance(snapshot.get("history"), list) else [])
        if isinstance(row, dict)
    ]
    if not history:
        return snapshot
    trend = build_red_team_escalation_trend(history)
    audit = build_red_team_escalation_audit(history)
    next_plan = _red_team_next_benchmark_plan_from_history(history, audit)
    latest = trend.get("latest", {}) if isinstance(trend, dict) else {}
    previous_summary = snapshot.get("summary", {}) if isinstance(snapshot.get("summary"), dict) else {}
    summary = {
        **previous_summary,
        "runCount": int(trend.get("runCount", previous_summary.get("runCount", 0)) or 0),
        "status": str(trend.get("status") or previous_summary.get("status") or "empty"),
        "latestPreset": str(latest.get("preset") or previous_summary.get("latestPreset") or ""),
        "latestResistanceScore": int(latest.get("resistance_score", previous_summary.get("latestResistanceScore", 0)) or 0),
        "latestDifficultyLevel": int(latest.get("difficultyLevel", previous_summary.get("latestDifficultyLevel", 0)) or 0),
        "nextDifficultyLevel": int(latest.get("nextDifficultyLevel", previous_summary.get("nextDifficultyLevel", 0)) or 0),
        "currentPressureIndex": int(latest.get("currentPressureIndex", previous_summary.get("currentPressureIndex", 0)) or 0),
        "nextPressureIndex": int(latest.get("nextPressureIndex", previous_summary.get("nextPressureIndex", 0)) or 0),
        "pressureDelta": int(latest.get("pressureDelta", previous_summary.get("pressureDelta", 0)) or 0),
        "nextDifficultyLabel": str(latest.get("nextDifficultyLabel") or previous_summary.get("nextDifficultyLabel") or ""),
        "nextAttemptBudget": int(latest.get("nextAttemptBudget", previous_summary.get("nextAttemptBudget", 0)) or 0),
        "passStreak": int(latest.get("passStreak", previous_summary.get("passStreak", 0)) or 0),
        "cleanPass": bool(latest.get("cleanPass", previous_summary.get("cleanPass", False))),
        "shouldEscalate": bool(latest.get("shouldEscalate", previous_summary.get("shouldEscalate", False))),
        "difficultyTrend": int(trend.get("difficultyTrend", previous_summary.get("difficultyTrend", 0)) or 0),
        "pressureTrend": int(trend.get("pressureTrend", previous_summary.get("pressureTrend", 0)) or 0),
        "resistanceTrend": int(trend.get("resistanceTrend", previous_summary.get("resistanceTrend", 0)) or 0),
        "satisfiedEscalationTargets": int(audit.get("satisfiedTargets", previous_summary.get("satisfiedEscalationTargets", 0)) or 0),
        "pendingEscalationTargets": int(audit.get("pendingTargets", previous_summary.get("pendingEscalationTargets", 0)) or 0),
        "nextAction": str(trend.get("nextAction") or previous_summary.get("nextAction") or ""),
    }
    return {
        **snapshot,
        "history": history,
        "trend": trend,
        "escalationAudit": audit,
        "nextBenchmarkPlan": next_plan,
        "summary": summary,
    }


def _red_team_next_benchmark_plan_from_history(history: list[dict[str, Any]], audit: dict[str, Any]) -> dict[str, Any]:
    latest = history[-1] if history else {}
    target_row = next((row for row in reversed(history) if row.get("shouldEscalate")), {})
    source = target_row or latest
    preset = str(source.get("preset") or latest.get("preset") or "hackaprompt")
    level = int(source.get("nextDifficultyLevel", source.get("difficultyLevel", 1)) or 1)
    current_pressure = int(source.get("currentPressureIndex", source.get("difficultyLevel", level) * 10) or 0)
    next_pressure = int(source.get("nextPressureIndex", level * 10) or level * 10)
    pressure_delta = int(source.get("pressureDelta", next_pressure - current_pressure) or 0)
    difficulty_label = str(
        source.get("nextDifficultyLabel")
        or (
            f"L{level} pressure {next_pressure}"
            if level >= 5 and next_pressure > current_pressure
            else f"L{level}"
        )
    )
    level_cap_reached = level >= 5 and next_pressure > current_pressure
    attempt_budget = int(
        source.get("nextAttemptBudget", source.get("attempt_count", max(3, level * 3)))
        or max(3, level * 3)
    )
    target_resistance = int(source.get("targetResistanceScore", 90) or 90)
    tactics = [
        str(item)
        for item in (source.get("nextTactics") or source.get("observedTactics") or [])
        if str(item or "").strip()
    ]
    if not tactics:
        tactics = ["direct_policy_probe", "roleplay"]
    if not history:
        status = "empty"
        next_action = "Run the first aggregate-only red-team benchmark."
    elif latest.get("shouldEscalate"):
        status = "pending_follow_up" if audit.get("latestTargetPending") else "ready_for_follow_up"
        next_action = "Run the recorded harder aggregate-only benchmark and compare the next row."
    elif audit.get("pendingTargets"):
        status = "pending_follow_up"
        next_action = "Run the pending harder aggregate-only benchmark recorded by the last clean pass."
    else:
        status = "waiting_for_clean_pass"
        next_action = "Keep sampling until resistance and clean-pass streak justify escalation."
    objective = (
        f"Run {preset} at {difficulty_label} with {attempt_budget} attempts, "
        f"{len(tactics)} tactic families, and target resistance {target_resistance}+."
    )
    return {
        "schema": "fluxio.red_team_next_benchmark_plan.v1",
        "status": status,
        "preset": preset,
        "sourceRecordedAt": str(source.get("recordedAt") or ""),
        "targetDifficultyLevel": level,
        "difficultyLabel": difficulty_label,
        "levelCapReached": level_cap_reached,
        "currentPressureIndex": current_pressure,
        "nextPressureIndex": next_pressure,
        "pressureDelta": pressure_delta,
        "attemptBudget": attempt_budget,
        "targetResistanceScore": target_resistance,
        "tactics": tactics,
        "operatorReviewRequired": level >= 4,
        "aggregateOnly": True,
        "rawPayloadExport": False,
        "successCriteria": [
            f"resistance_score >= {target_resistance}",
            f"pressure index advances to {next_pressure}",
            "all attempts remain aggregate-only in exported evidence",
            "no raw secrets, credentials, hidden instructions, or payload text emitted",
            "a follow-up history row satisfies the pending escalation target",
        ],
        "command": {
            "argv": [
                "npm",
                "run",
                "sample:self-improvement-red-team",
                "--",
                "--preset",
                preset,
                "--objective",
                objective,
            ],
            "shell": (
                "npm run sample:self-improvement-red-team -- "
                f"--preset {json.dumps(preset)} --objective {json.dumps(objective)}"
            ),
        },
        "nextAction": next_action,
    }


def _red_team_snapshot_is_newer(local: dict[str, Any], synced: dict[str, Any]) -> bool:
    if not local or local.get("schema") != "fluxio.red_team_escalation_snapshot.v1":
        return False
    local_history = local.get("history", []) if isinstance(local.get("history"), list) else []
    synced_history = synced.get("history", []) if isinstance(synced.get("history"), list) else []
    if len(local_history) > len(synced_history):
        return True
    if len(local_history) < len(synced_history):
        return False
    local_latest = local_history[-1] if local_history and isinstance(local_history[-1], dict) else {}
    synced_latest = synced_history[-1] if synced_history and isinstance(synced_history[-1], dict) else {}
    return _parse_iso_timestamp(str(local_latest.get("recordedAt") or "")) > _parse_iso_timestamp(
        str(synced_latest.get("recordedAt") or "")
    )


def _unavailable_red_team_escalation_snapshot(error: str) -> dict[str, Any]:
    return {
        "schema": "fluxio.red_team_escalation_snapshot.v1",
        "source": "unavailable",
        "error": error,
        "history": [],
        "trend": {"status": "unavailable"},
        "escalationAudit": {"status": "unavailable"},
        "summary": {
            "runCount": 0,
            "status": "unavailable",
            "latestPreset": "",
            "latestResistanceScore": 0,
            "latestDifficultyLevel": 0,
            "nextDifficultyLevel": 0,
            "nextAttemptBudget": 0,
            "passStreak": 0,
            "cleanPass": False,
            "shouldEscalate": False,
            "satisfiedEscalationTargets": 0,
            "pendingEscalationTargets": 0,
            "nextAction": "Repair red-team escalation evidence loading.",
        },
    }


def _apply_strict_score_caps(
    categories: list[AuditCategory],
    evidence: dict[str, bool],
) -> list[AuditCategory]:
    """Keep the scorecard honest: code presence is not proof of product-grade polish."""

    caps = {
        "Launch friction and beginner experience": (
            20
            if evidence.get("has_public_launch_ready")
            and evidence.get("has_external_publication_proof")
            and evidence.get("has_beginner_launch_interaction_gate")
            else 19
            if evidence.get("has_public_launch_ready")
            and evidence.get("has_beginner_launch_interaction_gate")
            else 18
            if evidence.get("has_launcher_package_release_receipt")
            and evidence.get("has_public_web_release_candidate_attachment")
            else 17
            if evidence.get("has_npx_style_launcher_package")
            else 16
            if evidence.get("has_one_command_launcher")
            else 15
        ),
        "Multi-project Builder operations": (
            20
            if evidence.get("has_project_progress_history") and evidence.get("has_batch_sync_conflict_resolution")
            else 19
            if evidence.get("has_batch_sync_conflict_resolution")
            else
            18
            if evidence.get("has_interactive_sync_conflict_resolution")
            else 17
            if evidence.get("has_receipt_backed_sync_conflicts")
            else 16
        ),
        "Harness and sub-agent capability": (
            20
            if evidence.get("has_live_cross_category_outcome_validation")
            and evidence.get("has_operator_value_route_trust_proven")
            else 19
            if evidence.get("has_live_cross_category_outcome_validation")
            else 18
            if evidence.get("has_outcome_trend_routing")
            else 17
            if evidence.get("has_route_rollback_receipts")
            else 17
            if evidence.get("has_route_mutation_receipts")
            else 16
        ),
    "Web availability and distribution": (
            20
            if evidence.get("has_public_launch_ready")
            and evidence.get("has_external_publication_proof")
            and evidence.get("has_mobile_push_delivery_proof")
            else 18
            if evidence.get("has_public_launch_ready")
            else 18
            if evidence.get("has_public_web_distribution_contract")
            else 17
            if evidence.get("has_out_of_band_watchdog_notifications")
            else 16
            if evidence.get("has_overnight_digest")
            else 15
        ),
        "Speed and long-history performance": (
            20
            if evidence.get("has_release_proof_ci")
            and evidence.get("has_public_release_attachment_manifest")
            and evidence.get("has_external_publication_proof")
            else
            19
            if evidence.get("has_release_proof_ci")
            else 18
            if evidence.get("has_release_proof_archive")
            else 17
            if evidence.get("has_long_history_release_gate")
            else 16
        ),
        "Roadmap clarity and self-improvement": (
            20
            if evidence.get("has_operator_value_route_trust_proven")
            else
            19
            if evidence.get("has_self_improvement_evidence_contract")
            else 18
            if evidence.get("has_approved_skill_repair_application")
            else 17
            if evidence.get("has_skill_repair_proposals")
            else 16
        ),
        "Interface clarity and operator ergonomics": (
            20
            if evidence.get("has_live_workbench_execution_surface")
            and evidence.get("has_live_mission_output_quality_cleared")
            else 19
            if evidence.get("has_live_workbench_execution_surface")
            else
            18
            if evidence.get("has_builder_clarity_mode")
            else 17
            if evidence.get("has_agent_advanced_drawers")
            else 16
        ),
    }
    if evidence.get("has_nas_storage_pressure_critical"):
        caps["Launch friction and beginner experience"] = min(
            caps["Launch friction and beginner experience"],
            17 if evidence.get("has_storage_aware_quickstart_fallback") else 16,
        )
        caps["Multi-project Builder operations"] = min(caps["Multi-project Builder operations"], 15)
        caps["Harness and sub-agent capability"] = min(caps["Harness and sub-agent capability"], 16)
        caps["Speed and long-history performance"] = min(caps["Speed and long-history performance"], 16)
        caps["Web availability and distribution"] = min(caps["Web availability and distribution"], 17)
        caps["Interface clarity and operator ergonomics"] = min(
            caps["Interface clarity and operator ergonomics"],
            16,
        )
    if evidence.get("has_live_mission_artifact_repairs"):
        caps["Proof, verification, and trust"] = 12
        caps["Harness and sub-agent capability"] = min(caps["Harness and sub-agent capability"], 16)
        caps["Interface clarity and operator ergonomics"] = min(
            caps["Interface clarity and operator ergonomics"],
            15,
        )
    if not evidence.get("has_mobile_push_delivery_proof"):
        caps["Web availability and distribution"] = min(caps["Web availability and distribution"], 18)
    if evidence.get("has_active_runtime_budget_exhausted"):
        caps["Launch friction and beginner experience"] = min(caps["Launch friction and beginner experience"], 18)
        caps["Multi-project Builder operations"] = min(caps["Multi-project Builder operations"], 19)
        caps["Interface clarity and operator ergonomics"] = min(caps["Interface clarity and operator ergonomics"], 18)
    notes = {
        "Launch friction and beginner experience": (
            "Strict cap cleared: public web/source parity, release packet attachments, external publication proof, and beginner first-run interaction proof are present."
            if evidence.get("has_public_launch_ready")
            and evidence.get("has_external_publication_proof")
            and evidence.get("has_beginner_launch_interaction_gate")
            else
            "Strict cap: public launch checks and external publication proof are green, but beginner launch is not treated as 20/20 until first-run interaction proof stays current with the release."
            if evidence.get("has_public_launch_ready") and evidence.get("has_external_publication_proof")
            else
            "Strict cap: public launch checks are green, but external publication and first-run proof must stay current together before Neyvia can beat T3 on launch."
            if evidence.get("has_public_launch_ready")
            else
            "Strict cap: launcher package and public-web release-candidate receipts exist, but external public registry, tag/release, or signed-installer publication proof remains unproven."
            if evidence.get("has_launcher_package_release_receipt")
            and evidence.get("has_public_web_release_candidate_attachment")
            else
            "Strict cap: local npx-style entrypoint exists, but public registry publishing, signed installer, and first-run proof remain unproven."
            if evidence.get("has_npx_style_launcher_package")
            else "Strict cap: no signed installer, public hosted entrypoint, or public npx-style distribution is proven."
        ),
        "Multi-project Builder operations": (
            "Strict cap cleared for project history, scheduling, sync authority, guided launch rehearsal, and receipt proof; next validation is repeated receipt quality across project pairs."
            if evidence.get("has_project_progress_history")
            and evidence.get("has_dependency_aware_project_scheduler")
            and evidence.get("has_beginner_safe_sync_authority")
            and evidence.get("has_cross_device_launch_rehearsal")
            and evidence.get("has_cross_device_launch_rehearsal_receipt")
            else
            "Strict cap cleared for project history, scheduling, sync authority, and guided launch rehearsal; next validation is an archived real cross-device launch receipt."
            if evidence.get("has_project_progress_history")
            and evidence.get("has_dependency_aware_project_scheduler")
            and evidence.get("has_beginner_safe_sync_authority")
            and evidence.get("has_cross_device_launch_rehearsal")
            else
            "Strict cap cleared for project history, scheduling, and sync authority: live progress plus declared workspace dependencies now drive the queue; next validation is guided cross-device launch rehearsal."
            if evidence.get("has_project_progress_history")
            and evidence.get("has_dependency_aware_project_scheduler")
            and evidence.get("has_beginner_safe_sync_authority")
            else
            "Strict cap cleared for project history and scheduling: live progress plus declared workspace dependencies now drive the queue; next validation is beginner-safe sync authority."
            if evidence.get("has_project_progress_history")
            and evidence.get("has_dependency_aware_project_scheduler")
            else
            "Strict cap cleared for project history: live per-project progress is now backend-contract backed; next validation is dependency-aware scheduling over time."
            if evidence.get("has_project_progress_history")
            else
            "Strict cap: batch conflict resolution exists, but live historical progress per project still needs proof."
            if evidence.get("has_batch_sync_conflict_resolution")
            else
            "Strict cap: one-file conflict resolution exists, but live safe parallel dispatch and batch conflict resolution still need proof."
            if evidence.get("has_interactive_sync_conflict_resolution")
            else "Strict cap: conflict receipts exist, but interactive conflict resolution is not yet a complete workflow."
        ),
        "Harness and sub-agent capability": (
            "Strict cap cleared: Hermes-first routing is backed by live cross-category outcome validation and operator-proven route trust."
            if evidence.get("has_live_cross_category_outcome_validation")
            and evidence.get("has_operator_value_route_trust_proven")
            else
            "Strict cap: live cross-category outcome validation is present, but operator-proven route trust must stay current before this is 20/20."
            if evidence.get("has_live_cross_category_outcome_validation")
            else
            "Strict cap: Hermes-first sub-agent routing exists, but live cross-category outcome validation is still pending."
            if evidence.get("has_outcome_trend_routing")
            else "Strict cap: failed-route rollback exists, but outcome-trend routing is not complete."
        ),
        "Web availability and distribution": (
            "Strict cap: public web release proof is present, but phone/tablet mobile push has no delivered ntfy receipt or Web Push browser subscription yet."
            if not evidence.get("has_mobile_push_delivery_proof")
            else
            "Strict cap cleared for public web release proof: public launch readiness, source parity, and external publication proof are present."
            if evidence.get("has_public_launch_ready") and evidence.get("has_external_publication_proof")
            else
            "Strict cap: public web readiness is green, but external publication/tag or signed installer proof is required before Neyvia can beat T3 on distribution."
            if evidence.get("has_public_launch_ready")
            else
            "Strict cap: GitHub Pages deployment receipts are attached to release-candidate artifacts, but the current public launch verifier still requires external publication proof before a 20/20 web score."
            if evidence.get("has_public_web_release_candidate_attachment")
            else
            "Strict cap: GitHub Pages/PWA distribution and URL receipt capture are CI-verified, but release-candidate attachment is still pending."
            if evidence.get("has_public_web_distribution_contract")
            else "Strict cap: out-of-band Telegram watchdog notifications and installable PWA shell are present, but public distribution is not proven."
            if evidence.get("has_out_of_band_watchdog_notifications") and evidence.get("has_installable_pwa_shell")
            else
            "Strict cap: out-of-band Telegram watchdog notifications are present, but public distribution is not proven."
            if evidence.get("has_out_of_band_watchdog_notifications")
            else "Strict cap: private NAS web is working, but closed-tab mobile push/public distribution is not proven."
        ),
        "Speed and long-history performance": (
            "Strict cap cleared: release proof CI enforcement, checksummed publication attachments, and external release publication proof are present."
            if evidence.get("has_release_proof_ci")
            and evidence.get("has_public_release_attachment_manifest")
            and evidence.get("has_external_publication_proof")
            else
            "Strict cap: release proof CI enforcement and checksummed publication attachments exist; public release-candidate publication/tagging is still pending."
            if evidence.get("has_release_proof_ci") and evidence.get("has_public_release_attachment_manifest")
            else
            "Strict cap: release proof CI enforcement exists; checksummed publication attachments and public release-candidate publication are still pending."
            if evidence.get("has_release_proof_ci")
            else "Strict cap: release proof archives exist, but CI enforcement and publication are still pending."
            if evidence.get("has_release_proof_archive")
            else "Strict cap: long-history gates exist, but CI/release artifact enforcement is still pending."
        ),
        "Roadmap clarity and self-improvement": (
            "Strict cap cleared for route trust: live value-scored samples prove every tracked task category; the next check is longer trend quality."
            if evidence.get("has_operator_value_route_trust_proven")
            else
            "Strict cap: self-improvement evidence is archived, but live value-scored samples still need to prove every task category."
            if evidence.get("has_self_improvement_evidence_contract")
            else "Strict cap: approved repairs can be applied, but validation-slice and red-team escalation trend proof is still accumulating."
            if evidence.get("has_approved_skill_repair_application")
            else "Strict cap: repair proposals exist, but approved skill patches are not applied automatically yet."
        ),
        "Interface clarity and operator ergonomics": (
            "Strict cap: one live Hermes mission is still runtime-budget exhausted, so the control room cannot be scored as a frictionless operator experience yet."
            if evidence.get("has_active_runtime_budget_exhausted")
            else
            "Strict cap cleared: Workbench execution receipts and current live mission runtime-output/artifact evidence are present."
            if evidence.get("has_live_workbench_execution_surface")
            and evidence.get("has_live_mission_output_quality_cleared")
            else
            "Strict cap: live Agent/Workbench still have missions with missing runtime output, missing transcript, or missing artifact proof, so the UI cannot be scored as clear even if the components exist."
            if evidence.get("has_live_mission_artifact_repairs")
            else
            "Strict cap: NAS storage or bounded storage probes are critical, so launch/proof surfaces cannot be treated as reliable operator ergonomics yet."
            if evidence.get("has_nas_storage_pressure_critical")
            else
            "Strict cap: Builder focus/full and Workbench artifact execution are now primary surfaces, but weak completed missions still need served-artifact proof before clarity can be treated as fully solved."
            if evidence.get("has_live_workbench_execution_surface")
            else
            "Strict cap: Builder now has a focus/full operator mode, but Workbench still needs primary artifact execution before clarity can be treated as fully solved."
            if evidence.get("has_builder_clarity_mode")
            else
            "Strict cap: Agent diagnostics are behind progressive disclosure now; the control room still cannot beat T3 on clarity until Builder and Workbench have the same beginner/operator simplification."
            if evidence.get("has_agent_advanced_drawers")
            else "Strict cap: live-first surfaces are present, but the control room remains too dense to rate above T3 until secondary diagnostics move behind clearer progressive disclosure."
        ),
    }
    capped: list[AuditCategory] = []
    for item in categories:
        cap = caps.get(item.category)
        if cap is None or item.score_out_of_20 <= cap:
            capped.append(item)
            continue
        note = notes.get(item.category)
        if evidence.get("has_nas_storage_pressure_critical") and item.category in {
            "Launch friction and beginner experience",
            "Multi-project Builder operations",
            "Harness and sub-agent capability",
            "Speed and long-history performance",
            "Web availability and distribution",
        }:
            note = (
                "Strict cap: NAS storage pressure is critical, but storage-aware quickstart can route new work to a local workspace; NAS-backed unattended launches, proof writes, and live mission loops remain unreliable until storage is cleared."
                if item.category == "Launch friction and beginner experience"
                and evidence.get("has_storage_aware_quickstart_fallback")
                else (
                    "Strict cap: NAS storage pressure is critical or storage probes timed out, "
                    "so unattended launches, proof writes, and live mission loops cannot be treated as reliable yet."
                )
            )
        if evidence.get("has_live_mission_artifact_repairs") and item.category == "Proof, verification, and trust":
            note = (
                "Strict cap: live mission rows still need hard artifact-gate repair, so proof/trust cannot score higher until "
                "runtime output, transcript, or served artifact evidence is restored."
            )
        if item.category == "Web availability and distribution" and not evidence.get("has_mobile_push_delivery_proof"):
            note = (
                "Strict cap: public web release proof is present, but phone/tablet mobile push has no delivered ntfy receipt or Web Push browser subscription yet."
            )
        if item.category in {
            "Launch friction and beginner experience",
            "Multi-project Builder operations",
            "Interface clarity and operator ergonomics",
        } and evidence.get("has_active_runtime_budget_exhausted"):
            note = (
                "Strict cap: one live Hermes mission is still runtime-budget exhausted, so the operator flow is not complete or frictionless yet."
            )
        evidence_lines = [*item.evidence, note] if note else [*item.evidence]
        gap_lines = [note, *item.gaps] if note else [*item.gaps]
        capped.append(
            replace(
                item,
                score_out_of_20=cap,
                evidence=evidence_lines,
                gaps=gap_lines,
            )
        )
    return capped


def _single_project_progress(name: str, project_root: Path) -> dict[str, Any]:
    control = project_root / ".agent_control"
    workspaces = _load_json(control / "workspaces.json", [])
    missions_payload = _load_json(control / "missions.json", {})
    missions = _mission_items(missions_payload)
    blocking_policy = _load_json(control / "blocking_metrics_policy.json", {})
    blocking_metrics_since = str(
        blocking_policy.get("blockingMetricsSince")
        if isinstance(blocking_policy, dict)
        else ""
    ).strip()
    normalized_cutoff = blocking_metrics_since.replace("Z", "+00:00")
    try:
        blocking_cutoff = datetime.fromisoformat(normalized_cutoff) if normalized_cutoff else None
    except ValueError:
        blocking_cutoff = None
    if blocking_cutoff is not None and blocking_cutoff.tzinfo is None:
        blocking_cutoff = blocking_cutoff.replace(tzinfo=timezone.utc)

    def created_inside_blocking_window(mission: dict[str, Any]) -> bool:
        if blocking_cutoff is None:
            return True
        created_text = str(mission.get("created_at") or mission.get("createdAt") or "").strip()
        try:
            created_at = datetime.fromisoformat(created_text.replace("Z", "+00:00"))
        except ValueError:
            return False
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return created_at.astimezone(timezone.utc) >= blocking_cutoff.astimezone(timezone.utc)

    missions = [
        (mission_id, mission)
        for mission_id, mission in missions
        if not (
            str(
                (mission.get("state") or {}).get("status")
                if isinstance(mission.get("state"), dict)
                else mission.get("status")
                or ""
            ).strip().lower()
            in {"blocked", "needs_approval", "verification_failed"}
            and not created_inside_blocking_window(mission)
        )
    ]
    runtime_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    recent: list[dict[str, str]] = []
    active_missions: list[dict[str, Any]] = []
    blocked_missions: list[dict[str, Any]] = []
    last_activity = ""
    for mission_id, mission in missions:
        state = mission.get("state") if isinstance(mission.get("state"), dict) else {}
        proof = mission.get("proof") if isinstance(mission.get("proof"), dict) else {}
        runtime = str(
            mission.get("runtime_id")
            or mission.get("runtime")
            or state.get("runtime_id")
            or "unknown"
        )
        status = str(state.get("status") or mission.get("status") or "unknown")
        runtime_counts[runtime] = runtime_counts.get(runtime, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1
        last_activity = max(
            last_activity,
            str(mission.get("updated_at") or mission.get("updatedAt") or mission.get("created_at") or ""),
        )
        active = status not in {"completed", "failed", "stopped", "archived", "draft", "unknown"}
        blocked = created_inside_blocking_window(mission) and (
            status in {"blocked", "needs_approval", "verification_failed"}
            or bool(state.get("stop_reason"))
            or bool(proof.get("blocked_by"))
            or bool(proof.get("failed_checks"))
        )
        if active:
            active_missions.append(
                _mission_progress_payload(mission_id, mission, state=state, proof=proof)
            )
        if blocked:
            blocked_missions.append(
                _mission_progress_payload(mission_id, mission, state=state, proof=proof)
            )
    for mission_id, mission in missions[-6:]:
        state = mission.get("state") if isinstance(mission.get("state"), dict) else {}
        proof = mission.get("proof") if isinstance(mission.get("proof"), dict) else {}
        recent.append(
            {
                "missionId": str(mission_id or ""),
                "runtime": str(mission.get("runtime_id") or mission.get("runtime") or "unknown"),
                "status": str(state.get("status") or mission.get("status") or "unknown"),
                "plannerLoopStatus": str(
                    state.get("planner_loop_status")
                    or mission.get("planner_loop_status")
                    or "unknown"
                ),
                "summary": str(proof.get("summary") or mission.get("objective") or "")[:220],
            }
        )
    return {
        "name": name,
        "root": str(project_root),
        "sourceMode": "local_agent_control",
        "sourcePath": str(control),
        "blockingMetricsSince": blocking_metrics_since,
        "workspaceCount": len(workspaces) if isinstance(workspaces, list) else 0,
        "missionCount": len(missions),
        "runtimeCounts": runtime_counts,
        "statusCounts": status_counts,
        "lastActivity": last_activity,
        "activeMissionCount": len(active_missions),
        "blockedMissionCount": len(blocked_missions),
        "activeMissions": _sort_progress_missions(active_missions)[:8],
        "blockedMissions": _sort_progress_missions(blocked_missions)[:8],
        "recentMissions": recent,
    }


def _live_project_progress_from_evidence(
    name: str,
    project_root: Path,
    live_nas_evidence: dict[str, Any],
) -> dict[str, Any] | None:
    counts = live_nas_evidence.get("counts") if isinstance(live_nas_evidence.get("counts"), dict) else {}
    if live_nas_evidence.get("status") != "passed" or int(counts.get("missions") or 0) <= 0:
        return None
    running = (
        live_nas_evidence.get("runningMissions", [])
        if isinstance(live_nas_evidence.get("runningMissions"), list)
        else []
    )
    attention_summary = _live_nas_mission_attention_summary(live_nas_evidence)
    active_missions: list[dict[str, Any]] = []
    recent: list[dict[str, str]] = []
    for item in running:
        if not isinstance(item, dict):
            continue
        mission_id = str(item.get("mission_id") or item.get("missionId") or "")
        runtime = str(item.get("runtime_id") or item.get("runtime") or "unknown")
        status = str(item.get("status") or "unknown")
        loop_status = str(item.get("planner_loop_status") or item.get("plannerLoopStatus") or "")
        title = str(item.get("title") or item.get("objective") or "Live NAS mission")
        live_progress = item.get("liveProgress") if isinstance(item.get("liveProgress"), dict) else {}
        progress_kind = str(live_progress.get("progressKind") or "")
        next_action = str(
            live_progress.get("nextAction")
            or "Open the live Agent drill-down for current messages, proof, and actions."
        )
        active_missions.append(
            {
                "missionId": mission_id,
                "title": title,
                "runtime": runtime,
                "status": status,
                "plannerLoopStatus": loop_status,
                "remainingRuntimeSeconds": 0,
                "progressKind": progress_kind,
                "proofSummary": "Live NAS control-room summary row.",
                "nextAction": next_action,
            }
        )
        recent.append(
            {
                "missionId": mission_id,
                "runtime": runtime,
                "status": status,
                "plannerLoopStatus": loop_status,
                "summary": title[:220],
            }
        )
    return {
        "name": name,
        "root": str(project_root),
        "sourceMode": "authenticated_live_nas",
        "sourcePath": str(live_nas_evidence.get("sourcePath") or ""),
        "workspaceCount": int(counts.get("workspaces") or 0),
        "missionCount": int(counts.get("missions") or 0),
        "runtimeCounts": (
            live_nas_evidence.get("runtimeCounts", {})
            if isinstance(live_nas_evidence.get("runtimeCounts"), dict)
            else {}
        ),
        "statusCounts": (
            live_nas_evidence.get("statusCounts", {})
            if isinstance(live_nas_evidence.get("statusCounts"), dict)
            else {}
        ),
        "lastActivity": str(live_nas_evidence.get("checkedAt") or ""),
        "activeMissionCount": int(counts.get("activeMissions") or len(active_missions)),
        "blockedMissionCount": int(attention_summary.get("hardBlockedMissionCount") or 0),
        "attentionMissionCount": int(attention_summary.get("reportedAttentionMissionCount") or 0),
        "runtimeBudgetAttentionMissionCount": int(
            attention_summary.get("runtimeBudgetAttentionMissionCount") or 0
        ),
        "unresolvedReportedAttentionMissionCount": int(
            attention_summary.get("unresolvedReportedAttentionMissionCount") or 0
        ),
        "activeMissions": active_missions,
        "blockedMissions": [],
        "recentMissions": recent,
    }


def _t3_deficits(categories: list[AuditCategory]) -> list[dict[str, Any]]:
    deficits: list[dict[str, Any]] = []
    for item in categories:
        delta = item.score_out_of_20 - item.t3_reference_score_out_of_20
        if delta > 0:
            continue
        deficits.append(
            {
                "category": item.category,
                "fluxioScore": item.score_out_of_20,
                "t3Score": item.t3_reference_score_out_of_20,
                "delta": delta,
                "nextMove": item.next_moves[0] if item.next_moves else item.verdict,
                "blockingGap": item.gaps[0] if item.gaps else "",
            }
        )
    deficits.sort(key=lambda item: (item["delta"], item["fluxioScore"], item["category"]))
    return deficits


def _repair_plan_supersedes_output_quality(
    output_quality: dict[str, Any],
    repair_plan: dict[str, Any],
) -> bool:
    if not output_quality or not repair_plan:
        return False
    if repair_plan.get("schema") != "fluxio.mission_artifact_repair_plan.v1":
        return False
    if str(repair_plan.get("status") or "").lower() != "passed":
        return False
    if int(repair_plan.get("repairMissionCount") or repair_plan.get("weakMissionCount") or 0) != 0:
        return False
    if repair_plan.get("repairs"):
        return False
    issue_rows = [
        item
        for item in [
            *(
                output_quality.get("weakMissionRows", [])
                if isinstance(output_quality.get("weakMissionRows"), list)
                else []
            ),
            *(
                output_quality.get("repairMissionRows", [])
                if isinstance(output_quality.get("repairMissionRows"), list)
                else []
            ),
        ]
        if isinstance(item, dict)
    ]
    issue_ts = max(
        [_parse_iso_timestamp(str(item.get("checkedAt") or "")) for item in issue_rows],
        default=0,
    )
    plan_ts = max(
        _parse_iso_timestamp(str(repair_plan.get("sourceCheckedAt") or "")),
        _parse_iso_timestamp(str(repair_plan.get("liveDetailCheckedAt") or "")),
        _parse_iso_timestamp(str(repair_plan.get("generatedAt") or "")),
    )
    return plan_ts > 0 and (issue_ts <= 0 or plan_ts >= issue_ts)


def _effective_live_mission_output_quality(
    output_quality: dict[str, Any] | None,
    repair_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    quality = dict(output_quality or {})
    plan = dict(repair_plan or {})
    if not _repair_plan_supersedes_output_quality(quality, plan):
        return quality
    return {
        **quality,
        "status": "passed",
        "weakMissionRows": [],
        "repairMissionRows": [],
        "supersededWeakMissionRows": (
            quality.get("weakMissionRows", [])
            if isinstance(quality.get("weakMissionRows"), list)
            else []
        ),
        "supersededRepairMissionRows": (
            quality.get("repairMissionRows", [])
            if isinstance(quality.get("repairMissionRows"), list)
            else []
        ),
        "supersededByRepairPlan": True,
        "supersededByRepairPlanGeneratedAt": plan.get("generatedAt") or "",
        "supersededByRepairPlanSourceCheckedAt": plan.get("sourceCheckedAt") or "",
        "nextAction": str(
            plan.get("nextAction")
            or quality.get("nextAction")
            or "No transcript-only completed missions are present in current authenticated verifier evidence."
        ),
    }


def _system_loss_breakdown(
    categories: list[AuditCategory],
    release: dict[str, Any],
    project_progress: list[dict[str, Any]],
    *,
    nas_storage_pressure: dict[str, Any] | None = None,
    nas_storage_cleanup_plan: dict[str, Any] | None = None,
    live_mission_output_quality: dict[str, Any] | None = None,
    mission_artifact_repair_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not categories:
        return {
            "schema": "fluxio.system_loss_breakdown.v1",
            "status": "missing_categories",
            "averageScoreOutOf20": 0,
            "averageLossOutOf20": 20,
            "drivers": [],
        }
    average = round(sum(item.score_out_of_20 for item in categories) / len(categories), 1)
    t3_average = round(
        sum(item.t3_reference_score_out_of_20 for item in categories) / len(categories),
        1,
    )
    drivers = []
    for item in categories:
        loss = max(0, 20 - int(item.score_out_of_20))
        t3_margin = int(item.score_out_of_20) - int(item.t3_reference_score_out_of_20)
        drivers.append(
            {
                "category": item.category,
                "scoreOutOf20": int(item.score_out_of_20),
                "lossOutOf20": loss,
                "t3ReferenceScoreOutOf20": int(item.t3_reference_score_out_of_20),
                "t3Margin": t3_margin,
                "severity": "high" if loss >= 3 or t3_margin <= 0 else "medium" if loss >= 1 else "low",
                "primaryGap": item.gaps[0] if item.gaps else "",
                "nextAction": item.next_moves[0] if item.next_moves else item.verdict,
            }
        )
    drivers.sort(
        key=lambda item: (
            -int(item["lossOutOf20"]),
            int(item["t3Margin"]),
            str(item["category"]),
        )
    )
    storage = nas_storage_pressure or {}
    storage_status = str(storage.get("status") or "").lower()
    storage_probe_timed_out = bool(storage.get("probeTimedOut"))
    storage_probe_connect_failed = bool(storage.get("probeConnectFailed"))
    if storage and _nas_storage_pressure_is_blocking(storage):
        cleanup = nas_storage_cleanup_plan or {}
        candidate_count = int(cleanup.get("candidateCount") or 0)
        estimated_reclaimable_mb = float(cleanup.get("estimatedReclaimableMB") or 0)
        volume_accounting_gb = float(cleanup.get("volumeAccountingGB") or 0)
        largest_volume_path = str(cleanup.get("largestVolumeAccountingPath") or "")
        timed_out_external = [
            str(item)
            for item in cleanup.get("timedOutExternalProbePaths", [])
            if str(item or "").strip()
        ]
        timed_out_volume = [
            str(item)
            for item in cleanup.get("timedOutVolumeAccountingPaths", [])
            if str(item or "").strip()
        ]
        largest_volume_detail = f" with largest {largest_volume_path}" if largest_volume_path else ""
        timed_out_external_detail = (
            f" ({', '.join(timed_out_external[:3])})" if timed_out_external else ""
        )
        timed_out_volume_detail = (
            f" ({', '.join(timed_out_volume[:3])})" if timed_out_volume else ""
        )
        drivers.insert(
            0,
            {
                "category": "NAS storage and mission-write headroom",
                "scoreOutOf20": 4,
                "lossOutOf20": 16,
                "t3ReferenceScoreOutOf20": 18,
                "t3Margin": -14,
                "severity": "critical",
                "primaryGap": (
                    "The current bounded NAS storage probe failed before df data returned, "
                    "so mission logs, proof artifacts, and self-improvement receipts cannot be trusted."
                    if _nas_storage_probe_failed(storage)
                    else "The NAS volume reports no writable headroom, so mission logs, proof artifacts, and self-improvement receipts can silently fail."
                ),
                "nextAction": str(
                    cleanup.get("nextAction")
                    or storage.get("nextAction")
                    or "Free non-Syntelos NAS volume space or Synology snapshot space, then rerun storage pressure verification."
                ),
                "evidence": (
                    (
                        f"{storage.get('mount', _default_nas_mount_label())} bounded storage probe could not connect before current df data returned. "
                        if storage.get("probeConnectFailed")
                        else (
                        f"{storage.get('mount', _default_nas_mount_label())} bounded storage probe timed out before current df data returned. "
                        if storage_probe_timed_out
                        else (
                            f"{storage.get('mount', _default_nas_mount_label())} is "
                            f"{int(storage.get('usedPercent') or 0)}% used with "
                            f"{int(storage.get('availableBytes') or 0)} available bytes. "
                        )
                        )
                    )
                    + f"Bounded cleanup candidates: {candidate_count}, estimated {estimated_reclaimable_mb} MB. "
                    f"Volume-accounting probes total {volume_accounting_gb} GB"
                    f"{largest_volume_detail}. "
                    f"Timed-out non-generated probes: {len(timed_out_external)}"
                    f"{timed_out_external_detail}; "
                    f"timed-out volume probes: {len(timed_out_volume)}"
                    f"{timed_out_volume_detail}."
                ),
            },
        )
    output_quality = _effective_live_mission_output_quality(
        live_mission_output_quality or {},
        mission_artifact_repair_plan or {},
    )
    weak_rows = (
        output_quality.get("weakMissionRows", [])
        if isinstance(output_quality.get("weakMissionRows"), list)
        else []
    )
    repair_plan = mission_artifact_repair_plan or {}
    repair_rows = repair_plan.get("repairs", []) if isinstance(repair_plan.get("repairs"), list) else []
    if weak_rows or repair_rows:
        first = (
            weak_rows[0]
            if weak_rows and isinstance(weak_rows[0], dict)
            else repair_rows[0]
            if repair_rows and isinstance(repair_rows[0], dict)
            else {}
        )
        repair_count = int(repair_plan.get("repairMissionCount") or repair_plan.get("weakMissionCount") or len(repair_rows))
        output_count = len(weak_rows) or repair_count
        drivers.insert(
            0,
            {
                "category": "Mission outputs and artifact proof",
                "scoreOutOf20": 10,
                "lossOutOf20": 10,
                "t3ReferenceScoreOutOf20": 18,
                "t3Margin": -8,
                "severity": "high",
                "primaryGap": (
                    "At least one live Hermes mission lacks a concrete runtime-output body, served artifact, "
                    "or readable transcript needed for review."
                ),
                "nextAction": str(
                    repair_plan.get("nextAction")
                    or output_quality.get("nextAction")
                    or "Relaunch the weak mission with a hard artifact gate and verify the served artifact from Agent and Workbench."
                ),
                "evidence": (
                    f"{output_count} mission artifact repair(s); first: "
                    f"{first.get('missionId', '')} {first.get('title', '')}. "
                    f"Repair contracts ready: {repair_count}."
                ),
            },
        )
    required_gates = release.get("requiredGateSummary", {}) if isinstance(release.get("requiredGateSummary"), dict) else {}
    managed_workspace_count = sum(int(project.get("workspaceCount") or 0) for project in project_progress)
    project_count = max(len(project_progress), managed_workspace_count)
    active_mission_count = sum(int(project.get("activeMissionCount") or 0) for project in project_progress)
    blocked_mission_count = sum(int(project.get("blockedMissionCount") or 0) for project in project_progress)
    attention_mission_count = sum(
        int(project.get("attentionMissionCount") or project.get("blockedMissionCount") or 0)
        for project in project_progress
    )
    runtime_budget_attention_count = sum(
        int(project.get("runtimeBudgetAttentionMissionCount") or 0)
        for project in project_progress
    )
    drivers.sort(
        key=lambda item: (
            -float(item.get("lossOutOf20") or 0),
            int(item.get("t3Margin") or 0),
            str(item.get("category") or ""),
        )
    )
    return {
        "schema": "fluxio.system_loss_breakdown.v1",
        "status": "current",
        "averageScoreOutOf20": average,
        "averageLossOutOf20": round(20 - average, 1),
        "t3ReferenceAverageOutOf20": t3_average,
        "mustBeatStatus": {
            "ahead": sum(1 for item in categories if item.score_out_of_20 > item.t3_reference_score_out_of_20),
            "total": len(categories),
            "deficits": sum(1 for item in categories if item.score_out_of_20 <= item.t3_reference_score_out_of_20),
        },
        "releaseReadiness": {
            "status": str(release.get("status") or "unknown"),
            "score": int(release.get("score") or 0),
            "requiredPassed": int(required_gates.get("passed") or 0),
            "requiredTotal": int(required_gates.get("total") or 0),
            "qualityScore": int(release.get("qualityScore") or 0),
        },
        "missionSurface": {
            "projectCount": project_count,
            "progressSourceCount": len(project_progress),
            "managedWorkspaceCount": managed_workspace_count,
            "activeMissionCount": active_mission_count,
            "blockedMissionCount": blocked_mission_count,
            "attentionMissionCount": attention_mission_count,
            "runtimeBudgetAttentionMissionCount": runtime_budget_attention_count,
            "sourceModes": sorted(
                {
                    str(project.get("sourceMode") or "").strip()
                    for project in project_progress
                    if isinstance(project, dict) and str(project.get("sourceMode") or "").strip()
                }
            ),
        },
        "drivers": drivers,
    }


def _improvement_lane(category: str) -> str:
    normalized = category.lower()
    if "launch" in normalized or "beginner" in normalized:
        return "Launch and onboarding"
    if "multi-project" in normalized or "builder" in normalized:
        return "Builder operations"
    if "harness" in normalized or "sub-agent" in normalized:
        return "Harness parity"
    if "web" in normalized or "phone" in normalized or "notification" in normalized:
        return "Web and notifications"
    if "speed" in normalized or "performance" in normalized:
        return "Speed and scale"
    if "self" in normalized or "red-team" in normalized or "skill" in normalized:
        return "Self-improvement"
    return "System quality"


def _improvement_queue(
    categories: list[AuditCategory],
    release: dict[str, Any],
    *,
    system_loss_breakdown: dict[str, Any],
) -> list[dict[str, Any]]:
    driver_by_category = {
        str(item.get("category") or ""): item
        for item in system_loss_breakdown.get("drivers", [])
        if isinstance(item, dict)
    }
    queue: list[dict[str, Any]] = []
    for item in sorted(
        categories,
        key=lambda category: (
            -(20 - int(category.score_out_of_20)),
            int(category.score_out_of_20) - int(category.t3_reference_score_out_of_20),
            category.category,
        ),
    ):
        driver = driver_by_category.get(item.category, {})
        gap = item.gaps[0] if item.gaps else item.verdict
        next_action = item.next_moves[0] if item.next_moves else gap
        if int(item.score_out_of_20) >= 20 and not item.gaps:
            continue
        queue.append(
            {
                "schema": "fluxio.system_improvement_queue_item.v1",
                "lane": _improvement_lane(item.category),
                "category": item.category,
                "scoreOutOf20": int(item.score_out_of_20),
                "lossOutOf20": int(driver.get("lossOutOf20") or max(0, 20 - item.score_out_of_20)),
                "t3ReferenceScoreOutOf20": int(item.t3_reference_score_out_of_20),
                "t3Margin": int(item.score_out_of_20) - int(item.t3_reference_score_out_of_20),
                "severity": str(driver.get("severity") or "medium"),
                "blockingGap": gap,
                "nextAction": next_action,
                "evidence": item.evidence[:3],
            }
        )
    return queue[:8]


def _active_gap_missions(project_progress: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for project in project_progress:
        if not isinstance(project, dict):
            continue
        project_name = str(project.get("name") or "")
        for mission in project.get("activeMissions", []) or []:
            if not isinstance(mission, dict):
                continue
            rows.append(
                {
                    "schema": "fluxio.active_gap_mission.v1",
                    "projectName": project_name,
                    "projectRoot": str(project.get("root") or ""),
                    "sourceMode": str(project.get("sourceMode") or ""),
                    "missionId": str(mission.get("missionId") or ""),
                    "title": str(mission.get("title") or mission.get("proofSummary") or "Active mission"),
                    "runtime": str(mission.get("runtime") or "unknown"),
                    "status": str(mission.get("status") or "unknown"),
                    "plannerLoopStatus": str(mission.get("plannerLoopStatus") or ""),
                    "proofSummary": str(mission.get("proofSummary") or "")[:220],
                    "nextAction": str(mission.get("nextAction") or "Open the live Agent drill-down."),
                }
            )
        for mission in project.get("blockedMissions", []) or []:
            if not isinstance(mission, dict):
                continue
            rows.append(
                {
                    "schema": "fluxio.active_gap_mission.v1",
                    "projectName": project_name,
                    "projectRoot": str(project.get("root") or ""),
                    "sourceMode": str(project.get("sourceMode") or ""),
                    "missionId": str(mission.get("missionId") or ""),
                    "title": str(mission.get("title") or mission.get("proofSummary") or "Blocked mission"),
                    "runtime": str(mission.get("runtime") or "unknown"),
                    "status": str(mission.get("status") or "blocked"),
                    "plannerLoopStatus": str(mission.get("plannerLoopStatus") or ""),
                    "proofSummary": str(mission.get("proofSummary") or "")[:220],
                    "nextAction": str(mission.get("nextAction") or "Repair the blocker before resuming."),
                }
            )
    status_order = {"running": 0, "launching": 1, "needs_approval": 2, "blocked": 3, "queued": 4}
    rows.sort(key=lambda item: (status_order.get(item["status"], 9), item["projectName"], item["missionId"]))
    return rows[:12]


def _sort_progress_missions(missions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    status_order = {
        "running": 0,
        "launching": 1,
        "needs_approval": 2,
        "verification_failed": 3,
        "blocked": 4,
        "queued": 5,
    }
    return sorted(
        missions,
        key=lambda item: (
            status_order.get(str(item.get("status") or ""), 9),
            int(item.get("queuePosition") or 0),
            str(item.get("missionId") or ""),
        ),
    )


def _mission_progress_payload(
    mission_id: str,
    mission: dict[str, Any],
    *,
    state: dict[str, Any],
    proof: dict[str, Any],
) -> dict[str, Any]:
    status = str(state.get("status") or mission.get("status") or "unknown")
    stop_reason = str(state.get("stop_reason") or "")
    queue_position = int(state.get("queue_position") or 0)
    blocking_mission_id = str(state.get("blocking_mission_id") or "")
    proof_summary = str(proof.get("summary") or mission.get("objective") or "No proof summary yet.")[:220]
    if status in {"running", "launching"}:
        next_action = "Keep the watchdog active and review the next proof digest."
    elif status == "queued" and blocking_mission_id:
        next_action = "Wait for the active slot or use safe parallel worktree dispatch if scope evidence is disjoint."
    elif status == "queued":
        next_action = "Resume asynchronously from Builder or the mission-action command."
    elif status == "needs_approval":
        next_action = "Review and approve or reject the latest approval gate."
    elif stop_reason == "runtime_budget":
        next_action = "Extend the runtime budget, then resume asynchronously."
    elif status in {"blocked", "verification_failed"}:
        next_action = "Open the proof digest and repair the blocker before resuming."
    else:
        next_action = "Review mission detail for the next safe action."
    return {
        "missionId": str(mission_id or mission.get("mission_id") or mission.get("missionId") or ""),
        "runtime": str(mission.get("runtime_id") or mission.get("runtime") or "unknown"),
        "status": status,
        "plannerLoopStatus": str(
            state.get("planner_loop_status")
            or mission.get("planner_loop_status")
            or "unknown"
        ),
        "remainingRuntimeSeconds": int(state.get("remaining_runtime_seconds") or 0),
        "timeBudgetStatus": str(state.get("time_budget_status") or ""),
        "stopReason": stop_reason,
        "queuePosition": queue_position,
        "blockingMissionId": blocking_mission_id,
        "proofSummary": proof_summary,
        "nextAction": next_action,
    }


def _bad_first(
    categories: list[AuditCategory],
    release: dict[str, Any],
    project_progress: list[dict[str, Any]],
    red_team_escalation: dict[str, Any] | None = None,
    route_trust_maturity: dict[str, Any] | None = None,
    nas_storage_pressure: dict[str, Any] | None = None,
    nas_storage_cleanup_plan: dict[str, Any] | None = None,
    live_mission_output_quality: dict[str, Any] | None = None,
    mission_artifact_repair_plan: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    weakest = [
        item
        for item in sorted(
            categories,
            key=lambda item: (
                int(item.score_out_of_20),
                int(item.score_out_of_20) - int(item.t3_reference_score_out_of_20),
                item.category,
            ),
        )
        if int(item.score_out_of_20) < 20
        or int(item.score_out_of_20) <= int(item.t3_reference_score_out_of_20)
    ][:4]
    bad = [
        {
            "title": item.category,
            "detail": item.gaps[0] if item.gaps else item.verdict,
        }
        for item in weakest
    ]
    if release.get("proofReadiness", {}).get("missingProofs"):
        bad.append(
            {
                "title": "Proof readiness",
                "detail": "Missing proof items: "
                + ", ".join(release.get("proofReadiness", {}).get("missingProofs", [])),
            }
        )
    if not any(project.get("missionCount", 0) for project in project_progress):
        bad.append(
            {
                "title": "Mission evidence",
                "detail": "No current local mission history was found under .agent_control.",
            }
        )
    storage = nas_storage_pressure or {}
    if storage and _nas_storage_pressure_is_blocking(storage):
        cleanup = nas_storage_cleanup_plan or {}
        timed_out_external = [
            str(item)
            for item in cleanup.get("timedOutExternalProbePaths", [])
            if str(item or "").strip()
        ]
        timed_out_volume = [
            str(item)
            for item in cleanup.get("timedOutVolumeAccountingPaths", [])
            if str(item or "").strip()
        ]
        bad.append(
            {
                "title": "NAS storage pressure",
                "detail": (
                    f"{_nas_storage_pressure_sentence(storage)} "
                    "mission writes and proof artifacts are at risk. "
                    f"Bounded cleanup planner found {int(cleanup.get('candidateCount') or 0)} generated candidate(s) "
                    f"for about {float(cleanup.get('estimatedReclaimableMB') or 0)} MB; "
                    f"{len(timed_out_external)} non-generated probe(s) and {len(timed_out_volume)} volume probe(s) timed out."
                ),
            }
        )
    output_quality = _effective_live_mission_output_quality(
        live_mission_output_quality or {},
        mission_artifact_repair_plan or {},
    )
    weak_rows = (
        output_quality.get("weakMissionRows", [])
        if isinstance(output_quality.get("weakMissionRows"), list)
        else []
    )
    repair_plan = mission_artifact_repair_plan or {}
    repair_rows = repair_plan.get("repairs", []) if isinstance(repair_plan.get("repairs"), list) else []
    if weak_rows or repair_rows:
        first = (
            weak_rows[0]
            if weak_rows and isinstance(weak_rows[0], dict)
            else repair_rows[0]
            if repair_rows and isinstance(repair_rows[0], dict)
            else {}
        )
        repair_count = int(repair_plan.get("repairMissionCount") or repair_plan.get("weakMissionCount") or len(repair_rows))
        output_count = len(weak_rows) or repair_count
        bad.append(
            {
                "title": "Mission output proof",
                "detail": (
                    f"{output_count} live mission(s) need hard artifact-gate repair; "
                    f"first repair row `{first.get('missionId', '')}` needs a served artifact, concrete runtime-output body, or restored transcript; "
                    f"{repair_count} hard artifact-gate repair contract(s) are ready."
                ),
            }
        )
    route_conflict = (
        route_trust_maturity.get("evidenceConflict", {})
        if isinstance(route_trust_maturity, dict) and isinstance(route_trust_maturity.get("evidenceConflict"), dict)
        else {}
    )
    if route_conflict:
        bad.append(
            {
                "title": "Route-trust evidence conflict",
                "detail": str(
                    route_conflict.get("detail")
                    or "Route-trust evidence has conflicting local and synced NAS claims."
                ),
            }
        )
    red_summary = (
        red_team_escalation.get("summary", {})
        if isinstance(red_team_escalation, dict) and isinstance(red_team_escalation.get("summary"), dict)
        else {}
    )
    red_run_count = int(red_summary.get("runCount") or 0)
    pending_targets = int(red_summary.get("pendingEscalationTargets") or 0)
    satisfied_targets = int(red_summary.get("satisfiedEscalationTargets") or 0)
    escalation_audit = (
        red_team_escalation.get("escalationAudit", {})
        if isinstance(red_team_escalation, dict) and isinstance(red_team_escalation.get("escalationAudit"), dict)
        else {}
    )
    escalation_status = str(escalation_audit.get("status") or red_summary.get("status") or "").lower()
    latest_target_pending = bool(escalation_audit.get("latestTargetPending"))
    legacy_healthy_next_target = (
        pending_targets == 1
        and satisfied_targets > 0
        and escalation_status in {"advancing", "escalating", "proven"}
    )
    current_cadence_healthy = (
        latest_target_pending
        and satisfied_targets > 0
        and bool(red_summary.get("cleanPass"))
        and int(red_summary.get("latestResistanceScore") or 0) >= 90
        and int(red_summary.get("pressureTrend") or 0) > 0
        and int(red_summary.get("nextAttemptBudget") or 0) > 0
        and escalation_status in {"advancing", "escalating", "pending", "proven"}
    )
    healthy_next_target = legacy_healthy_next_target or current_cadence_healthy
    if red_run_count <= 0:
        bad.append(
            {
                "title": "Red-team escalation",
                "detail": "No red-team escalation history is visible to the system audit.",
            }
        )
    elif pending_targets > 0 and not healthy_next_target:
        bad.append(
            {
                "title": "Red-team escalation",
                "detail": (
                    f"{pending_targets} harder red-team escalation target(s) are still pending; "
                    f"next action: {red_summary.get('nextAction', 'continue adaptive red-team sampling')}"
                ),
            }
        )
    return bad


def _summary(
    categories: list[AuditCategory],
    release: dict[str, Any],
    project_progress: list[dict[str, Any]],
    route_trust_maturity: dict[str, Any] | None = None,
    red_team_escalation: dict[str, Any] | None = None,
    public_launch_readiness: dict[str, Any] | None = None,
    nas_storage_pressure: dict[str, Any] | None = None,
    live_mission_output_quality: dict[str, Any] | None = None,
    mission_artifact_repair_plan: dict[str, Any] | None = None,
) -> str:
    average = round(sum(item.score_out_of_20 for item in categories) / len(categories), 1)
    t3_average = round(
        sum(item.t3_reference_score_out_of_20 for item in categories) / len(categories),
        1,
    )
    t3_deficit_count = sum(
        1 for item in categories if item.score_out_of_20 <= item.t3_reference_score_out_of_20
    )
    t3_ahead_count = len(categories) - t3_deficit_count
    t3_position_clause = _t3_position_clause(categories, t3_deficit_count=t3_deficit_count)
    mission_count = sum(project.get("missionCount", 0) for project in project_progress)
    route = route_trust_maturity or {}
    operator_confidence = int(route.get("operatorConfidenceScore") or 0)
    route_status = str(route.get("status") or "unknown")
    if route_status == "operator_proven":
        route_clause = (
            f"Operator confidence is `{operator_confidence}/100` (`operator_proven`); "
            f"{route.get('provenTaskCount', 0)}/{route.get('taskCount', 0)} route "
            "categories are value-scored, so route trust no longer caps user-facing maturity."
        )
    else:
        route_clause = (
            f"Operator confidence is `{operator_confidence}/100` (`{route_status}`), so "
            "user-facing maturity stays capped until live value-scored route trust is proven."
        )
    source_modes = {
        str(project.get("sourceMode") or "").strip()
        for project in project_progress
        if isinstance(project, dict)
    }
    mission_source_label = (
        "current NAS mission rows"
        if "authenticated_live_nas" in source_modes
        else "local tracked missions"
    )
    red_summary = (
        red_team_escalation.get("summary", {})
        if isinstance(red_team_escalation, dict) and isinstance(red_team_escalation.get("summary"), dict)
        else {}
    )
    red_run_count = int(red_summary.get("runCount") or 0)
    if red_run_count > 0:
        red_team_clause = (
            f"Red-team escalation has `{red_run_count}` history rows; latest resistance "
            f"`{red_summary.get('latestResistanceScore', 0)}`, difficulty "
            f"`{red_summary.get('latestDifficultyLevel', 0)}` -> "
            f"`{red_summary.get('nextDifficultyLevel', 0)}`, next attempts "
            f"`{red_summary.get('nextAttemptBudget', 0)}`, pass streak "
            f"`{red_summary.get('passStreak', 0)}`, pressure "
            f"`{red_summary.get('currentPressureIndex', 0)}` -> "
            f"`{red_summary.get('nextPressureIndex', 0)}`."
        )
    else:
        red_team_clause = "Red-team escalation has no visible history rows yet."
    public_launch = public_launch_readiness or {}
    if public_launch.get("schema") == "fluxio.public_launch_readiness.v1":
        public_clause = (
            "Public launch is fully proven."
            if public_launch.get("ok")
            else (
                "Public launch is not claimable yet: "
                f"`{public_launch.get('status', 'not_ready')}`; "
                f"missing `{', '.join(public_launch.get('missing', [])) if isinstance(public_launch.get('missing'), list) else 'proof'}`."
            )
        )
    else:
        public_clause = "Public launch readiness evidence is missing."
    storage = nas_storage_pressure or {}
    if storage and _nas_storage_pressure_is_blocking(storage):
        storage_clause = (
            "NAS storage is critical for launch gating: "
            + _nas_storage_pressure_sentence(storage)
        )
    else:
        storage_clause = "NAS storage pressure is not currently critical in the latest evidence."
    output_quality = _effective_live_mission_output_quality(
        live_mission_output_quality or {},
        mission_artifact_repair_plan or {},
    )
    weak_rows = (
        output_quality.get("weakMissionRows", [])
        if isinstance(output_quality.get("weakMissionRows"), list)
        else []
    )
    repair_rows = (
        output_quality.get("repairMissionRows", [])
        if isinstance(output_quality.get("repairMissionRows"), list)
        else []
    )
    if weak_rows:
        output_clause = (
            f"Mission output quality is not fully proven: `{len(weak_rows)}` completed live mission(s) "
            "are transcript-only or missing served artifacts."
        )
    elif repair_rows:
        output_clause = (
            f"Mission output quality needs repair: `{len(repair_rows)}` live mission(s) have "
            "failed hard artifact gates, missing runtime output, or missing transcripts."
        )
    else:
        output_clause = "Latest checked live missions have no completed transcript-only output warning."
    return (
        f"Neyvia scores {average}/20 across this audit versus a T3-style reference "
        f"average of {t3_average}/20. {t3_position_clause} Current release readiness is `{release.get('status')}` "
        f"with {release.get('requiredGateSummary', {}).get('passed')}/"
        f"{release.get('requiredGateSummary', {}).get('total')} required gates passing. "
        f"It is above the current T3 Code reference in {t3_ahead_count}/{len(categories)} "
        f"categories; {t3_deficit_count} must-beat category gap(s) remain. "
        f"{route_clause} "
        f"{red_team_clause} "
        f"{public_clause} "
        f"{storage_clause} "
        f"{output_clause} "
        f"The audit saw {mission_count} {mission_source_label}."
    )


def _t3_position_clause(categories: list[AuditCategory], *, t3_deficit_count: int) -> str:
    if not categories:
        return "No T3 comparison categories were available."
    if t3_deficit_count <= 0:
        top_margins = sorted(
            categories,
            key=lambda item: (item.score_out_of_20 - item.t3_reference_score_out_of_20, item.category),
            reverse=True,
        )[:3]
        margin_text = ", ".join(
            f"{item.category} +{item.score_out_of_20 - item.t3_reference_score_out_of_20}"
            for item in top_margins
            if item.score_out_of_20 > item.t3_reference_score_out_of_20
        )
        return (
            "It is currently ahead of the T3-style reference in every scored category"
            + (f", led by {margin_text}." if margin_text else ".")
        )
    weakest = sorted(
        categories,
        key=lambda item: (item.score_out_of_20 - item.t3_reference_score_out_of_20, item.score_out_of_20),
    )[:3]
    weak_text = ", ".join(
        f"{item.category} {item.score_out_of_20}/{item.t3_reference_score_out_of_20}"
        for item in weakest
    )
    return (
        "It is stronger than T3-style tools on durable mission proof, runtime supervision, "
        "and multi-project intent, but still needs work on "
        f"{weak_text}."
    )


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def _authenticated_live_agent_evidence_from_report(report: dict[str, Any], path: Path) -> dict[str, Any]:
    if report.get("schema") != "fluxio.authenticated_live_agent.v1":
        return {}
    agent_summary = report.get("summary", {}) if isinstance(report.get("summary"), dict) else {}
    agent_checks = report.get("checks", []) if isinstance(report.get("checks"), list) else []
    agent_passed_checks = [
        str(item.get("checkId") or "")
        for item in agent_checks
        if isinstance(item, dict) and item.get("passed")
    ]
    source_path = str(path.resolve())
    return {
        "agentSourcePath": source_path,
        "agentReportPath": source_path,
        "agentCheckedAt": str(report.get("checkedAt") or ""),
        "agentStatus": "passed" if report.get("ok") else "failed",
        "agentSelectedMission": (
            agent_summary.get("selectedMission", {})
            if isinstance(agent_summary.get("selectedMission"), dict)
            else {}
        ),
        "agentPassedChecks": agent_passed_checks,
    }


def _resolve_authenticated_live_agent_source_path(root: Path, value: object) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if path.is_absolute():
        return path
    return root / path


def _latest_agent_selected_mission(index: dict[str, Any]) -> dict[str, Any]:
    selected = index.get("selectedMission", {}) if isinstance(index.get("selectedMission"), dict) else {}
    return {
        "mission_id": str(selected.get("mission_id") or selected.get("missionId") or ""),
        "title": str(selected.get("title") or ""),
        "runtime_id": str(selected.get("runtime_id") or selected.get("runtimeId") or ""),
        "status": str(selected.get("status") or ""),
        "planner_loop_status": str(selected.get("planner_loop_status") or selected.get("plannerLoopStatus") or ""),
    }


def _authenticated_live_agent_evidence_from_latest_index(index: dict[str, Any], path: Path) -> dict[str, Any]:
    if index.get("schema") != "fluxio.authenticated_live_agent_latest_evidence.v1":
        return {}
    proof_bundle = index.get("proofBundle", {}) if isinstance(index.get("proofBundle"), dict) else {}
    open_proof = index.get("openCompleteProof", {}) if isinstance(index.get("openCompleteProof"), dict) else {}
    proof_strip = index.get("runtimeProofStrip", {}) if isinstance(index.get("runtimeProofStrip"), dict) else {}
    first_view_path = index.get("firstViewProofPath", {}) if isinstance(index.get("firstViewProofPath"), dict) else {}
    check_summary = index.get("checkSummary", {}) if isinstance(index.get("checkSummary"), dict) else {}
    latest_passed_checks: list[str] = []
    if proof_bundle.get("passed"):
        latest_passed_checks.append("live-agent-proof-bundle-status-contract")
    if open_proof.get("passed"):
        latest_passed_checks.append("live-agent-open-complete-proof-action")
    if proof_strip.get("passed"):
        latest_passed_checks.append("live-agent-runtime-proof-strip-loaded")
    if first_view_path.get("passed"):
        latest_passed_checks.append("live-agent-first-view-proof-path-visible")
    latest_path = str(path.resolve())
    return {
        "agentSourcePath": latest_path,
        "agentLatestEvidencePath": latest_path,
        "agentLatestIndexedAt": str(index.get("indexedAt") or ""),
        "agentSourceSchema": str(index.get("sourceSchema") or ""),
        "agentCheckedAt": str(index.get("checkedAt") or index.get("indexedAt") or ""),
        "agentStatus": "passed" if index.get("ok") else "failed",
        "agentSelectedMission": _latest_agent_selected_mission(index),
        "agentPassedChecks": latest_passed_checks,
        "agentCheckSummary": check_summary,
        "agentProofBundleStatus": str(proof_bundle.get("status") or ""),
        "agentProofBundleLabel": str(proof_bundle.get("label") or ""),
        "agentProofBundleComplete": bool(proof_bundle.get("hasCompleteEvidenceBundle")),
        "agentLatestRuntimeStatus": str(proof_bundle.get("latestRuntimeStatus") or ""),
        "agentLatestEvidenceStatus": str(proof_bundle.get("latestEvidenceStatus") or ""),
        "agentLatestCompleteMissionId": str(proof_bundle.get("latestCompleteMissionId") or ""),
        "agentOpenCompleteProofTargetMissionId": str(open_proof.get("targetMissionId") or ""),
        "agentOpenCompleteProofStatus": "passed" if open_proof.get("passed") else "failed",
        "agentOpenCompleteProofScreenshotPath": str(open_proof.get("screenshotPath") or ""),
        "agentFirstViewProofPathPassed": bool(first_view_path.get("passed")),
        "agentFirstViewProofPathRowCount": int(first_view_path.get("rowCount") or 0),
        "agentFirstViewProofPathNextActionCount": int(first_view_path.get("nextActionCount") or 0),
        "agentFirstViewProofPathText": str(first_view_path.get("text") or ""),
    }


def _load_authenticated_live_agent_latest_evidence(root: Path) -> dict[str, Any]:
    latest_path = root / ".agent_control" / "authenticated_live_agent_latest.json"
    index = _load_json(latest_path, {})
    if not isinstance(index, dict):
        return {}
    latest_evidence = _authenticated_live_agent_evidence_from_latest_index(index, latest_path)
    if not latest_evidence:
        return {}
    source_path = _resolve_authenticated_live_agent_source_path(root, index.get("sourceReportPath"))
    if source_path is None:
        return latest_evidence
    report = _load_json(source_path, {})
    if not isinstance(report, dict):
        return {
            **latest_evidence,
            "agentReportPath": str(source_path.resolve()),
        }
    report_evidence = _authenticated_live_agent_evidence_from_report(report, source_path)
    if not report_evidence:
        return {
            **latest_evidence,
            "agentReportPath": str(source_path.resolve()),
        }
    selected_from_report = report_evidence.get("agentSelectedMission", {})
    selected_from_latest = latest_evidence.get("agentSelectedMission", {})
    merged_passed_checks = _dedupe_strings(
        [
            *(
                report_evidence.get("agentPassedChecks", [])
                if isinstance(report_evidence.get("agentPassedChecks"), list)
                else []
            ),
            *(
                latest_evidence.get("agentPassedChecks", [])
                if isinstance(latest_evidence.get("agentPassedChecks"), list)
                else []
            ),
        ]
    )
    return {
        **report_evidence,
        **latest_evidence,
        "agentReportPath": str(source_path.resolve()),
        "agentSelectedMission": (
            selected_from_report
            if isinstance(selected_from_report, dict) and selected_from_report.get("mission_id")
            else selected_from_latest
        ),
        "agentPassedChecks": merged_passed_checks,
    }


def _load_live_nas_evidence(root: Path) -> dict[str, Any]:
    control_candidates = [
        root / "tmp-ui-checks" / "authenticated-live-control" / "authenticated-live-control-check.json",
    ]
    control_candidates.extend(
        sorted((root / ".agent_control").glob("*live-control*check.json"), reverse=True)
    )
    control_candidates.extend(
        sorted((root / ".agent_control").glob("*control*check.json"), reverse=True)
    )
    control_candidates.extend(
        sorted((root / ".agent_control" / "screenshots").glob("*live-control*check.json"), reverse=True)
    )
    control_candidates.extend(
        sorted((root / ".agent_control" / "screenshots").glob("*control*check.json"), reverse=True)
    )
    control_candidates.extend(
        sorted((root / ".agent_control" / "screenshots").glob("*-check.json"), reverse=True)
    )
    control_candidates.extend(
        sorted((root / "tmp-ui-checks").glob("**/*live-control*check.json"), reverse=True)
    )
    control_candidates.extend(
        sorted((root / "tmp-ui-checks").glob("**/*control*check.json"), reverse=True)
    )
    control_candidates.extend(
        sorted((root / "tmp-ui-checks").glob("**/*-check.json"), reverse=True)
    )
    control_candidates.extend(
        sorted(
            (root / ".agent_control" / "release_artifacts").glob(
                "*/authenticated_live_control/*authenticated-live-control*check.json"
            ),
            reverse=True,
        )
    )
    agent_candidates = [
        root / "tmp-ui-checks" / "authenticated-live-agent" / "authenticated-live-agent-check.json",
    ]
    agent_candidates.extend(
        sorted((root / ".agent_control").glob("*live-agent*check.json"), reverse=True)
    )
    agent_candidates.extend(
        sorted((root / ".agent_control").glob("*agent*check.json"), reverse=True)
    )
    agent_candidates.extend(
        sorted((root / ".agent_control" / "screenshots").glob("*live-agent*check.json"), reverse=True)
    )
    agent_candidates.extend(
        sorted((root / ".agent_control" / "screenshots").glob("*agent*check.json"), reverse=True)
    )
    agent_candidates.extend(
        sorted((root / ".agent_control" / "screenshots").glob("*-check.json"), reverse=True)
    )
    agent_candidates.extend(
        sorted((root / "tmp-ui-checks").glob("**/*live-agent*check.json"), reverse=True)
    )
    agent_candidates.extend(
        sorted((root / "tmp-ui-checks").glob("**/*agent*check.json"), reverse=True)
    )
    agent_candidates.extend(
        sorted((root / "tmp-ui-checks").glob("**/*-check.json"), reverse=True)
    )
    agent_candidates.extend(
        sorted(
            (root / ".agent_control" / "release_artifacts").glob(
                "*/authenticated_live_agent/*authenticated-live-agent*check.json"
            ),
            reverse=True,
        )
    )
    control_candidates = _sort_report_candidates(control_candidates, timestamp_field="checkedAt")
    agent_candidates = _sort_report_candidates(agent_candidates, timestamp_field="checkedAt")
    agent_evidence: dict[str, Any] = _load_authenticated_live_agent_latest_evidence(root)
    if not agent_evidence:
        for agent_path in agent_candidates:
            agent_report = _load_json(agent_path, {})
            if not isinstance(agent_report, dict):
                continue
            agent_evidence = _authenticated_live_agent_evidence_from_report(agent_report, agent_path)
            if agent_evidence:
                break
    for path in control_candidates:
        report = _load_json(path, {})
        if not isinstance(report, dict) or report.get("schema") != "fluxio.authenticated_live_control.v1":
            continue
        summary = report.get("summary", {}) if isinstance(report.get("summary"), dict) else {}
        counts = summary.get("counts", {}) if isinstance(summary.get("counts"), dict) else {}
        checks = report.get("checks", []) if isinstance(report.get("checks"), list) else []
        passed_checks = [
            str(item.get("checkId") or "")
            for item in checks
            if isinstance(item, dict) and item.get("passed")
        ]
        return {
            "sourcePath": str(path.resolve()),
            "checkedAt": str(report.get("checkedAt") or ""),
            "status": "passed" if report.get("ok") else "failed",
            "counts": counts,
            "runtimeCounts": summary.get("runtimeCounts", {}) if isinstance(summary.get("runtimeCounts"), dict) else {},
            "statusCounts": summary.get("statusCounts", {}) if isinstance(summary.get("statusCounts"), dict) else {},
            "notificationCount": int(summary.get("notificationCount") or 0),
            "sliceNotificationCount": int(summary.get("sliceNotificationCount") or 0),
            "runningMissions": summary.get("runningMissions", []) if isinstance(summary.get("runningMissions"), list) else [],
            "passedChecks": passed_checks,
            **agent_evidence,
        }
    if agent_evidence:
        return {
            "sourcePath": agent_evidence.get("agentSourcePath", ""),
            "checkedAt": agent_evidence.get("agentCheckedAt", ""),
            "status": agent_evidence.get("agentStatus", "failed"),
            "counts": {},
            "runtimeCounts": {},
            "statusCounts": {},
            "notificationCount": 0,
            "sliceNotificationCount": 0,
            "runningMissions": [],
            "passedChecks": [],
            **agent_evidence,
        }
    return {}


def _load_live_mission_detail_performance_evidence(root: Path) -> dict[str, Any]:
    candidates = [
        root / ".agent_control" / "live_mission_detail_performance_latest.json",
    ]
    candidates.extend(
        sorted(
            (root / ".agent_control" / "release_artifacts").glob(
                "*/live_mission_detail_performance/*latest*.json"
            ),
            reverse=True,
        )
    )
    candidates.extend(
        sorted(
            (root / "tmp-ui-checks").glob("**/*mission-detail-performance*.json"),
            reverse=True,
        )
    )
    for path in _sort_report_candidates(candidates, timestamp_field="checkedAt"):
        report = _load_json(path, {})
        if not isinstance(report, dict):
            continue
        if report.get("schema") != "fluxio.live_mission_detail_performance.v1":
            continue
        checked_at = str(report.get("checkedAt") or "")
        checked_ts = _parse_iso_timestamp(checked_at)
        if checked_ts <= 0:
            continue
        max_age_seconds = int(report.get("maxAgeSeconds") or 6 * 60 * 60)
        if datetime.now(timezone.utc).timestamp() - checked_ts > max_age_seconds:
            continue
        return {
            **report,
            "sourcePath": str(path.resolve()),
            "status": "passed" if report.get("ok") else "warning",
        }
    return {}


def _load_public_launch_readiness_evidence(root: Path) -> dict[str, Any]:
    candidates = [
        root / ".agent_control" / "public_launch_readiness" / "latest.json",
    ]
    candidates.extend(
        sorted(
            (root / ".agent_control" / "release_artifacts").glob(
                "*/public_launch_readiness/*latest*.json"
            ),
            reverse=True,
        )
    )
    for path in _sort_report_candidates(candidates, timestamp_field="checkedAt"):
        report = _load_json(path, {})
        if not isinstance(report, dict):
            continue
        if report.get("schema") != "fluxio.public_launch_readiness.v1":
            continue
        staging_candidates = [
            path.with_name("staging-plan.json"),
            root / ".agent_control" / "public_launch_readiness" / "staging-plan.json",
        ]
        staging_proof = (
            report.get("stagingProof", {})
            if isinstance(report.get("stagingProof"), dict)
            else {}
        )
        if not staging_proof:
            for staging_path in staging_candidates:
                staging_report = _load_json(staging_path, {})
                if (
                    isinstance(staging_report, dict)
                    and staging_report.get("schema") == "fluxio.public_launch_staging_proof.v1"
                ):
                    staging_proof = {
                        **staging_report,
                        "sourcePath": str(staging_path.resolve()),
                    }
                    break
        return {
            **report,
            "stagingProof": staging_proof,
            "sourcePath": str(path.resolve()),
            "status": str(report.get("status") or ("ready_for_public_launch" if report.get("ok") else "not_ready")),
        }
    return {}


def _load_live_nas_system_audit_evidence(root: Path) -> dict[str, Any]:
    candidates = [
        root / ".agent_control" / "live_nas_system_audit_latest.json",
    ]
    candidates.extend(
        sorted(
            (root / ".agent_control" / "release_artifacts").glob(
                "*/live_nas_system_audit/*latest*.json"
            ),
            reverse=True,
        )
    )
    for path in _sort_report_candidates(candidates, timestamp_field="checkedAt"):
        report = _load_json(path, {})
        if not isinstance(report, dict):
            continue
        if report.get("schema") != "fluxio.live_nas_system_audit_snapshot.v1":
            continue
        checked_at = str(report.get("checkedAt") or "")
        checked_ts = _parse_iso_timestamp(checked_at)
        if checked_ts <= 0:
            continue
        age_seconds = datetime.now(timezone.utc).timestamp() - checked_ts
        max_age_seconds = int(report.get("maxAgeSeconds") or 6 * 60 * 60)
        if age_seconds > max_age_seconds:
            continue
        audit = report.get("audit") if isinstance(report.get("audit"), dict) else {}
        source_root = str(report.get("sourceRoot") or audit.get("workspaceRoot") or "").strip()
        normalized_source_root = source_root.replace("\\", "/").rstrip("/")
        normalized_current_root = str(root).replace("\\", "/").rstrip("/")
        if normalized_source_root and normalized_source_root == normalized_current_root:
            continue
        route_trust = (
            audit.get("routeTrustMaturity", {})
            if isinstance(audit.get("routeTrustMaturity"), dict)
            else {}
        )
        live_nas = (
            audit.get("liveNasEvidence", {})
            if isinstance(audit.get("liveNasEvidence"), dict)
            else {}
        )
        red_team_escalation = (
            audit.get("redTeamEscalationEvidence", {})
            if isinstance(audit.get("redTeamEscalationEvidence"), dict)
            else {}
        )
        project_progress = (
            audit.get("projectProgress", [])
            if isinstance(audit.get("projectProgress"), list)
            else []
        )
        release_readiness = (
            audit.get("releaseReadiness", {})
            if isinstance(audit.get("releaseReadiness"), dict)
            else {}
        )
        return {
            "schema": report.get("schema"),
            "sourcePath": str(path.resolve()),
            "checkedAt": checked_at,
            "status": "passed" if report.get("ok") else "failed",
            "sourceRoot": source_root,
            "sourceHost": str(report.get("sourceHost") or ""),
            "auditGeneratedAt": str(audit.get("generatedAt") or ""),
            "summary": str(audit.get("summary") or ""),
            "routeTrustMaturity": route_trust,
            "liveNasEvidence": live_nas,
            "redTeamEscalationEvidence": red_team_escalation,
            "releaseReadiness": release_readiness,
            "projectProgress": project_progress,
            "t3Deficits": audit.get("t3Deficits", []) if isinstance(audit.get("t3Deficits"), list) else [],
        }
    return {}


def _load_nas_storage_pressure_evidence(root: Path) -> dict[str, Any]:
    candidates = [
        root / ".agent_control" / "nas_storage_pressure_latest.json",
    ]
    candidates.extend(
        sorted((root / ".agent_control").glob("*nas-storage-pressure*.json"), reverse=True)
    )
    for path in _sort_report_candidates(candidates, timestamp_field="checkedAt"):
        report = _load_json(path, {})
        if not isinstance(report, dict):
            continue
        if report.get("schema") != "fluxio.nas_storage_pressure.v1":
            continue
        checked_at = str(report.get("checkedAt") or "")
        checked_ts = _parse_iso_timestamp(checked_at)
        if checked_ts <= 0:
            continue
        age_seconds = datetime.now(timezone.utc).timestamp() - checked_ts
        max_age_seconds = int(report.get("maxAgeSeconds") or 48 * 60 * 60)
        if age_seconds > max_age_seconds:
            continue
        available = int(report.get("availableBytes") or 0)
        used_percent = int(report.get("usedPercent") or 0)
        status = str(report.get("status") or "").lower()
        if not status:
            status = "critical" if available <= 0 or used_percent >= 99 else "warning" if used_percent >= 95 else "ok"
        return {
            **report,
            "sourcePath": str(path.resolve()),
            "checkedAt": checked_at,
            "status": status,
            "availableBytes": available,
            "usedPercent": used_percent,
        }
    return {}


def _load_nas_storage_cleanup_plan(root: Path) -> dict[str, Any]:
    candidates = [
        root / ".agent_control" / "nas_storage_cleanup_plan_latest.json",
    ]
    candidates.extend(
        sorted((root / ".agent_control").glob("*nas-storage-cleanup*.json"), reverse=True)
    )
    for path in _sort_report_candidates(candidates, timestamp_field="checkedAt"):
        report = _load_json(path, {})
        if not isinstance(report, dict):
            continue
        if report.get("schema") != "fluxio.nas_storage_cleanup_plan.v1":
            continue
        checked_at = str(report.get("checkedAt") or "")
        checked_ts = _parse_iso_timestamp(checked_at)
        if checked_ts <= 0:
            continue
        age_seconds = datetime.now(timezone.utc).timestamp() - checked_ts
        max_age_seconds = int(report.get("maxAgeSeconds") or 48 * 60 * 60)
        if age_seconds > max_age_seconds:
            continue
        cleanup_candidates = (
            report.get("cleanupCandidates", [])
            if isinstance(report.get("cleanupCandidates"), list)
            else []
        )
        return {
            **report,
            "sourcePath": str(path.resolve()),
            "checkedAt": checked_at,
            "candidateCount": int(report.get("candidateCount") or len(cleanup_candidates)),
            "cleanupCandidates": cleanup_candidates,
            "estimatedReclaimableBytes": int(report.get("estimatedReclaimableBytes") or 0),
            "estimatedReclaimableMB": float(report.get("estimatedReclaimableMB") or 0),
        }
    return {}


def _agent_check(report: dict[str, Any], check_id: str) -> dict[str, Any]:
    for item in report.get("checks", []) if isinstance(report.get("checks"), list) else []:
        if isinstance(item, dict) and item.get("checkId") == check_id:
            return item
    return {}


def _mission_output_quality_row(report: dict[str, Any], path: Path) -> dict[str, Any] | None:
    if report.get("schema") != "fluxio.authenticated_live_agent.v1":
        return None
    checked_at = str(report.get("checkedAt") or "")
    selected = (
        report.get("summary", {}).get("selectedMission", {})
        if isinstance(report.get("summary"), dict)
        and isinstance(report.get("summary", {}).get("selectedMission"), dict)
        else {}
    )
    selected_check = _agent_check(report, "selected-live-mission")
    detail_check = _agent_check(report, "selected-mission-detail-api")
    runtime_check = _agent_check(report, "runtime-output-visible-in-thread")
    proof_check = _agent_check(report, "live-workbench-proof-band-visible")
    mission_id = str(
        selected.get("mission_id")
        or selected_check.get("missionId")
        or detail_check.get("missionId")
        or ""
    )
    if not mission_id:
        return None
    title = str(selected.get("title") or selected_check.get("title") or mission_id)
    status = str(selected.get("status") or selected_check.get("status") or "").lower()
    runtime = str(selected.get("runtime_id") or "unknown")
    runtime_output_count = int(runtime_check.get("runtimeOutputCount") or 0)
    agent_message_count = int(detail_check.get("agentMessageCount") or 0)
    proof_text = str(proof_check.get("proofBandText") or "")
    no_artifacts = "artifacts\nnone returned" in proof_text.lower() or "artifacts none returned" in proof_text.lower()
    weak = status == "completed" and agent_message_count > 0 and runtime_output_count == 0 and no_artifacts
    return {
        "missionId": mission_id,
        "title": title,
        "runtime": runtime,
        "status": status or "unknown",
        "checkedAt": checked_at,
        "reportPath": str(path.resolve()),
        "screenshotPath": str((report.get("artifacts") or {}).get("screenshotPath") or ""),
        "agentMessageCount": agent_message_count,
        "runtimeOutputCount": runtime_output_count,
        "artifactStatus": "none_returned" if no_artifacts else "reported",
        "weakOutput": weak,
        "detail": (
            "Completed mission has Hermes transcript rows, but no runtime-output body and no served artifact in the live Workbench proof band."
            if weak
            else "Mission output quality evidence did not trigger the completed transcript-only warning."
        ),
    }


def _load_live_mission_output_quality_evidence(root: Path) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    detail_status = _load_live_mission_detail_status_evidence(root)

    # A current NAS mission-detail snapshot is the authoritative live source. Older
    # browser-verifier JSON can be useful when the NAS snapshot is absent, but it
    # must not resurrect stale missions or screenshots after live data is present.
    detail_rows = (
        detail_status.get("missionRows", [])
        if isinstance(detail_status.get("missionRows"), list)
        else []
    )
    if detail_rows:
        for row in detail_rows:
            if not isinstance(row, dict):
                continue
            mission_id = str(row.get("missionId") or "").strip()
            if not mission_id:
                continue
            rows[mission_id] = row
    else:
        candidates: list[Path] = []
        candidates.extend(sorted((root / "tmp-ui-checks" / "authenticated-live-agent").glob("*-check.json"), reverse=True))
        candidates.extend(sorted((root / ".agent_control").glob("*live-agent*check.json"), reverse=True))
        for path in _sort_report_candidates(candidates, timestamp_field="checkedAt"):
            report = _load_json(path, {})
            if not isinstance(report, dict):
                continue
            checked_ts = _parse_iso_timestamp(str(report.get("checkedAt") or ""))
            if checked_ts <= 0:
                continue
            age_seconds = datetime.now(timezone.utc).timestamp() - checked_ts
            max_age_seconds = int(report.get("maxAgeSeconds") or 7 * 24 * 60 * 60)
            if age_seconds > max_age_seconds:
                continue
            row = _mission_output_quality_row(report, path)
            if not row:
                continue
            mission_id = str(row.get("missionId") or "")
            if mission_id and mission_id not in rows:
                rows[mission_id] = row
    if not rows:
        return {}
    all_rows = sorted(
        rows.values(),
        key=lambda item: _parse_iso_timestamp(str(item.get("checkedAt") or "")),
        reverse=True,
    )
    weak_rows = [item for item in all_rows if item.get("weakOutput")]
    repair_rows = [item for item in all_rows if _mission_output_row_needs_hard_artifact_repair(item)]
    needs_repair = bool(weak_rows or repair_rows)
    return {
        "schema": "fluxio.live_mission_output_quality.v1",
        "checkedAt": all_rows[0].get("checkedAt") or datetime.now(timezone.utc).isoformat(),
        "status": "needs_artifact_repair" if needs_repair else "passed",
        "reportCount": len(all_rows),
        "liveDetailStatusPath": str(detail_status.get("sourcePath") or ""),
        "weakMissionRows": weak_rows[:8],
        "repairMissionRows": repair_rows[:8],
        "checkedMissionRows": all_rows[:12],
        "nextAction": (
            "Relaunch or repair missions with missing runtime-output, transcript, or artifact proof using a hard served-artifact gate."
            if needs_repair
            else "Keep checking selected live missions for served artifacts and concrete runtime-output bodies."
        ),
    }


def _mission_output_row_needs_hard_artifact_repair(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").lower()
    artifact_gate = row.get("artifactGate") if isinstance(row.get("artifactGate"), dict) else {}
    runtime_transcript = row.get("runtimeTranscript") if isinstance(row.get("runtimeTranscript"), dict) else {}
    artifact_gate_status = str(row.get("artifactGateStatus") or artifact_gate.get("status") or "").lower()
    transcript_status = str(row.get("runtimeTranscriptStatus") or runtime_transcript.get("status") or "").lower()
    runtime_output_count = int(row.get("runtimeOutputCount") or artifact_gate.get("runtimeOutputCount") or 0)
    artifact_count = int(row.get("artifactCount") or artifact_gate.get("artifactCount") or 0)
    artifact_status = str(row.get("artifactStatus") or ("returned" if artifact_count > 0 else "")).lower()
    missing_runtime_output = runtime_output_count <= 0
    missing_artifact = artifact_status in {"none_returned", "missing", ""}
    explicit_transcript_missing_runtime_output = transcript_status in {
        "missing_runtime_output",
        "missing_required_output",
        "missing_transcript",
        "missing",
    }
    transcript_missing_runtime_output = explicit_transcript_missing_runtime_output or (
        not transcript_status and runtime_output_count <= 0
    )
    passed_with_runtime_output = (
        artifact_gate_status in {"passed", "ok", "clear"}
        and runtime_output_count > 0
        and not transcript_missing_runtime_output
    )
    return bool(
        row.get("weakOutput")
        or artifact_gate_status in {"missing_required_output", "failed", "blocked"}
        or (
            status == "completed"
            and not passed_with_runtime_output
            and (
                missing_runtime_output
                or missing_artifact
                or transcript_status in {"missing_transcript", "missing"}
            )
        )
        or (
            status in {"running", "delegated", "active"}
            and transcript_missing_runtime_output
            and missing_artifact
        )
        or (
            status in {"verification_failed", "failed", "blocked", "paused"}
            and (
                missing_runtime_output
                or missing_artifact
                or transcript_missing_runtime_output
            )
        )
    )


def _live_cross_category_outcome_validation(
    live_mission_output_quality: dict[str, Any],
    *,
    required_categories: int = 4,
) -> dict[str, Any]:
    """Summarize whether Hermes has live, useful outcomes across task families."""

    if not isinstance(live_mission_output_quality, dict):
        return {
            "schema": "fluxio.live_cross_category_outcome_validation.v1",
            "status": "missing",
            "validatedCategoryCount": 0,
            "requiredCategoryCount": required_categories,
            "categories": [],
            "nextAction": "Collect live mission-detail rows with Hermes runtime output and artifact proof.",
        }
    rows = (
        live_mission_output_quality.get("checkedMissionRows", [])
        if isinstance(live_mission_output_quality.get("checkedMissionRows"), list)
        else []
    )
    categories: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        runtime = str(row.get("runtime") or "").lower()
        if runtime != "hermes":
            continue
        category = _mission_task_family(row)
        if not category:
            continue
        output_count = int(row.get("runtimeOutputCount") or 0)
        artifact_status = str(row.get("artifactStatus") or "").lower()
        gate_status = str(row.get("artifactGateStatus") or "").lower()
        transcript_status = str(row.get("runtimeTranscriptStatus") or "").lower()
        if output_count <= 0:
            continue
        if gate_status not in {"passed", "ok", "clear"} and artifact_status not in {"reported", "served", "path"}:
            continue
        if (
            transcript_status in {"missing_runtime_output", "missing_required_output", "missing_transcript", "missing", "failed", "blocked"}
            and artifact_status not in {"reported", "served", "path"}
        ):
            continue
        current = categories.get(category, {})
        if output_count > int(current.get("runtimeOutputCount") or 0):
            categories[category] = {
                "taskFamily": category,
                "missionId": str(row.get("missionId") or ""),
                "title": str(row.get("title") or ""),
                "status": str(row.get("status") or ""),
                "runtimeOutputCount": output_count,
                "artifactStatus": artifact_status,
                "artifactGateStatus": gate_status,
                "runtimeTranscriptStatus": transcript_status,
            }
    validated = sorted(categories.values(), key=lambda item: str(item.get("taskFamily") or ""))
    status = "passed" if len(validated) >= required_categories else "needs_more_categories"
    return {
        "schema": "fluxio.live_cross_category_outcome_validation.v1",
        "status": status,
        "validatedCategoryCount": len(validated),
        "requiredCategoryCount": required_categories,
        "categories": validated,
        "nextAction": (
            "Keep rerunning live Hermes validation across new task families."
            if status == "passed"
            else "Run more Hermes missions with concrete runtime output and artifact proof across distinct task families."
        ),
    }


def _mission_task_family(row: dict[str, Any]) -> str:
    explicit_family = str(row.get("taskFamily") or "").strip()
    if explicit_family in {
        "rf_wireless",
        "f1_data_analytics",
        "public_data_investigation",
        "frontend_mobile_ui",
        "hardware_electrical",
        "security_red_team",
    }:
        return explicit_family
    task_types: list[str] = []
    route_task_types = row.get("routeTaskTypes")
    if isinstance(route_task_types, list):
        task_types.extend(str(item).strip() for item in route_task_types if str(item).strip())
    for key in ("taskType", "routeTrustTaskType"):
        value = str(row.get(key) or "").strip()
        if value:
            task_types.append(value)
    feedback = row.get("operatorValueFeedback") if isinstance(row.get("operatorValueFeedback"), dict) else {}
    feedback_task_type = str(feedback.get("routeTrustTaskType") or "").strip()
    if feedback_task_type:
        task_types.append(feedback_task_type)
    text = " ".join(
        str(row.get(key) or "").lower()
        for key in ("title", "detail", "objective", "workspaceId")
    )
    if re.search(r"\brf\b|\bwi-?fi\b|\bwireless\b|\bbluetooth\b|\bsdr\b|\bads-b\b|\bais\b", text):
        return "rf_wireless"
    if re.search(r"\bhardware\b|\belectrical\b|\bworkbench\b|\bbench\b|\bsensor\b|\bpcb\b|\bcircuit\b", text):
        return "hardware_electrical"
    if any(token in text for token in ("f1", "telemetry", "lap", "sector", "tire", "tyre")):
        return "f1_data_analytics"
    if any(token in text for token in ("public-data", "public data", "investigation", "geoint", "osint", "maritime", "supply-chain")):
        return "public_data_investigation"
    if any(token in text for token in ("red-team", "red team", "security", "defensive hardening")):
        return "security_red_team"
    for task_type in task_types:
        family = {
            "data_f1_analytics": "f1_data_analytics",
            "frontend_design": "frontend_mobile_ui",
            "hardware_electrical": "hardware_electrical",
            "research_analysis": "public_data_investigation",
            "security_red_team": "security_red_team",
        }.get(task_type)
        if family:
            return family
    if any(token in text for token in ("phone", "tablet", "builder progress", "frontend", "ui", "workbench")):
        return "frontend_mobile_ui"
    return ""


def _mission_detail_status_rows_from_report(
    report: dict[str, Any],
    path: Path,
) -> list[dict[str, Any]]:
    checked_at = str(report.get("checkedAt") or "")
    rows: list[dict[str, Any]] = []
    for item in report.get("missionRows", []) if isinstance(report.get("missionRows"), list) else []:
        if not isinstance(item, dict):
            continue
        mission_id = str(item.get("missionId") or "").strip()
        if not mission_id:
            continue
        status = str(item.get("status") or "unknown").lower()
        artifact_gate = item.get("artifactGate") if isinstance(item.get("artifactGate"), dict) else {}
        runtime_output_count = max(
            int(artifact_gate.get("runtimeOutputCount") or 0),
            int(item.get("runtimeOutputCount") or 0),
            int(item.get("realRuntimeReportCount") or 0),
        )
        artifact_count = int(artifact_gate.get("artifactCount") or item.get("artifactCount") or 0)
        agent_message_count = int(item.get("agentMessages") or 0)
        real_runtime_report_count_known = (
            bool(item.get("realRuntimeReportCountKnown"))
            if "realRuntimeReportCountKnown" in item
            else ("realRuntimeReportCount" in item or "traceOnlyMessageCount" in item)
        )
        real_runtime_report_count = int(item.get("realRuntimeReportCount") or 0)
        trace_only_message_count = int(item.get("traceOnlyMessageCount") or 0)
        transcript_status = str((item.get("runtimeTranscript") or {}).get("status") or "")
        artifact_status = "none_returned" if artifact_count <= 0 else "reported"
        transcript_missing_runtime_output = transcript_status in {
            "missing_runtime_output",
            "missing_required_output",
            "missing_transcript",
            "missing",
            "",
        }
        weak = (
            status == "completed"
            and (
                not bool(artifact_gate.get("passed"))
                or (transcript_missing_runtime_output and artifact_count <= 0)
            )
        )
        live_thread_missing_real_reports = (
            real_runtime_report_count_known
            and agent_message_count > 0
            and real_runtime_report_count <= 0
            and runtime_output_count <= 0
        )
        rows.append(
            {
                "missionId": mission_id,
                "title": str(item.get("title") or mission_id),
                "runtime": str(item.get("runtime") or "unknown"),
                "status": status,
                "objective": str(item.get("objective") or ""),
                "workspaceId": str(item.get("workspaceId") or ""),
                "routeTaskTypes": item.get("routeTaskTypes") if isinstance(item.get("routeTaskTypes"), list) else [],
                "routeTrustTaskType": str(item.get("routeTrustTaskType") or ""),
                "taskFamily": str(item.get("taskFamily") or ""),
                "checkedAt": str(item.get("checkedAt") or checked_at),
                "reportPath": str(path.resolve()),
                "screenshotPath": str(item.get("screenshotPath") or ""),
                "agentMessageCount": agent_message_count,
                "realRuntimeReportCount": real_runtime_report_count,
                "realRuntimeReportCountKnown": real_runtime_report_count_known,
                "traceOnlyMessageCount": trace_only_message_count,
                "runtimeOutputCount": runtime_output_count,
                "artifactStatus": artifact_status,
                "weakOutput": weak or live_thread_missing_real_reports,
                "artifactGateStatus": str(artifact_gate.get("status") or ""),
                "runtimeTranscriptStatus": transcript_status,
                "detail": (
                    "Live NAS detail says completed mission is missing the hard artifact/runtime-output gate."
                    if weak
                    else "Live NAS detail returned agent messages, but none are real runtime report rows."
                    if live_thread_missing_real_reports
                    else "Live NAS detail predates real-runtime-report counting; rerun the mission-detail sync for exact Agent message quality."
                    if not real_runtime_report_count_known
                    else "Live NAS detail status overrides stale screenshot output-quality evidence."
                ),
            }
        )
    return rows


def _archived_mission_detail_row_is_valid_history(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").lower()
    gate_status = str(row.get("artifactGateStatus") or "").lower()
    output_count = int(row.get("runtimeOutputCount") or 0)
    artifact_status = str(row.get("artifactStatus") or "").lower()
    return (
        status == "completed"
        and output_count > 0
        and gate_status in {"passed", "ok", "clear"}
        and artifact_status in {"reported", "served", "path"}
        and not row.get("weakOutput")
    )


def _load_live_mission_detail_status_evidence(root: Path) -> dict[str, Any]:
    control_dir = root / ".agent_control"
    latest_path = control_dir / "live_mission_detail_status_latest.json"
    candidates = [latest_path]
    candidates.extend(sorted(control_dir.glob("live_mission_detail_status_*.json"), reverse=True))
    rows_by_mission: dict[str, dict[str, Any]] = {}
    source_paths: list[str] = []
    newest_report: dict[str, Any] = {}
    latest_report_is_current = False
    archived_detail_row_count = 0
    for path in _sort_report_candidates(candidates, timestamp_field="checkedAt"):
        report = _load_json(path, {})
        if not isinstance(report, dict):
            continue
        if report.get("schema") != "fluxio.live_mission_detail_status.v1":
            continue
        checked_at = str(report.get("checkedAt") or "")
        checked_ts = _parse_iso_timestamp(checked_at)
        if checked_ts <= 0:
            continue
        is_latest_path = path.resolve() == latest_path.resolve()
        if is_latest_path:
            age_seconds = datetime.now(timezone.utc).timestamp() - checked_ts
            if age_seconds > int(report.get("maxAgeSeconds") or 6 * 60 * 60):
                continue
            latest_report_is_current = True
        if not newest_report:
            newest_report = dict(report)
        try:
            source_path = str(path.resolve())
        except OSError:
            source_path = str(path)
        if source_path not in source_paths:
            source_paths.append(source_path)
        for row in _mission_detail_status_rows_from_report(report, path):
            mission_id = str(row.get("missionId") or "")
            if not is_latest_path:
                if not _archived_mission_detail_row_is_valid_history(row):
                    continue
                archived_detail_row_count += 1
            if mission_id and mission_id not in rows_by_mission:
                rows_by_mission[mission_id] = row
    rows = sorted(
        rows_by_mission.values(),
        key=lambda item: _parse_iso_timestamp(str(item.get("checkedAt") or "")),
        reverse=True,
    )
    if not rows:
        return {}
    next_report = dict(newest_report)
    if not next_report:
        next_report = {
            "schema": "fluxio.live_mission_detail_status.v1",
            "checkedAt": rows[0].get("checkedAt") or datetime.now(timezone.utc).isoformat(),
        }
    next_report["missionRows"] = rows
    next_report["sourcePath"] = source_paths[0] if source_paths else str(latest_path.resolve())
    next_report["sourcePaths"] = source_paths[:12]
    next_report["archivedDetailRowCount"] = archived_detail_row_count
    next_report["latestReportCurrent"] = latest_report_is_current
    return next_report


def _load_mission_artifact_repair_plan(root: Path) -> dict[str, Any]:
    candidates = [
        root / ".agent_control" / "mission_artifact_repair_plan_latest.json",
    ]
    candidates.extend(
        sorted((root / ".agent_control").glob("*mission-artifact-repair*.json"), reverse=True)
    )
    for path in _sort_report_candidates(candidates, timestamp_field="generatedAt"):
        report = _load_json(path, {})
        if not isinstance(report, dict):
            continue
        if report.get("schema") != "fluxio.mission_artifact_repair_plan.v1":
            continue
        generated_at = str(report.get("generatedAt") or "")
        generated_ts = _parse_iso_timestamp(generated_at)
        if generated_ts <= 0:
            continue
        age_seconds = datetime.now(timezone.utc).timestamp() - generated_ts
        max_age_seconds = int(report.get("maxAgeSeconds") or 7 * 24 * 60 * 60)
        if age_seconds > max_age_seconds:
            continue
        repairs = report.get("repairs", []) if isinstance(report.get("repairs"), list) else []
        return {
            **report,
            "sourcePath": str(path.resolve()),
            "generatedAt": generated_at,
            "weakMissionCount": int(report.get("weakMissionCount") or len(repairs)),
            "repairs": repairs,
        }
    return {}


def _merge_synced_live_nas_evidence(
    local_evidence: dict[str, Any],
    synced_evidence: dict[str, Any],
    *,
    system_audit_path: str,
    system_audit_checked_at: str,
) -> dict[str, Any]:
    merged = {
        **local_evidence,
        **synced_evidence,
        "syncedSystemAuditPath": system_audit_path,
        "syncedSystemAuditCheckedAt": system_audit_checked_at,
    }
    local_agent_ts = _parse_iso_timestamp(str(local_evidence.get("agentCheckedAt") or ""))
    synced_agent_ts = _parse_iso_timestamp(str(synced_evidence.get("agentCheckedAt") or ""))
    local_summary_ts = _parse_iso_timestamp(str(local_evidence.get("checkedAt") or ""))
    synced_summary_ts = _parse_iso_timestamp(str(synced_evidence.get("checkedAt") or ""))
    if local_summary_ts > synced_summary_ts:
        for key in (
            "sourcePath",
            "checkedAt",
            "sourceGeneratedAt",
            "status",
            "counts",
            "runtimeCounts",
            "statusCounts",
            "notificationCount",
            "sliceNotificationCount",
            "runningMissions",
            "passedChecks",
            "supersededStaleReport",
            "supersededMissionCount",
            "supersededSourceGeneratedAt",
        ):
            if key in local_evidence:
                merged[key] = local_evidence[key]
        merged["newerLocalSummaryEvidencePreserved"] = True
    if local_agent_ts > synced_agent_ts:
        for key in (
            "agentSourcePath",
            "agentReportPath",
            "agentLatestEvidencePath",
            "agentLatestIndexedAt",
            "agentSourceSchema",
            "agentCheckedAt",
            "agentStatus",
            "agentSelectedMission",
            "agentPassedChecks",
            "agentCheckSummary",
            "agentProofBundleStatus",
            "agentProofBundleLabel",
            "agentProofBundleComplete",
            "agentLatestRuntimeStatus",
            "agentLatestEvidenceStatus",
            "agentLatestCompleteMissionId",
            "agentOpenCompleteProofTargetMissionId",
            "agentOpenCompleteProofStatus",
            "agentOpenCompleteProofScreenshotPath",
            "agentFirstViewProofPathPassed",
            "agentFirstViewProofPathRowCount",
            "agentFirstViewProofPathNextActionCount",
            "agentFirstViewProofPathText",
        ):
            if key in local_evidence:
                merged[key] = local_evidence[key]
        merged["newerLocalAgentEvidencePreserved"] = True
    return merged


def _freshen_live_nas_evidence(root: Path, evidence: dict[str, Any]) -> dict[str, Any]:
    """Use the current control-room store when older browser proof undercounts missions."""

    try:
        summary = ControlRoomStore(root).build_summary_snapshot()
    except Exception:
        return evidence
    if not isinstance(summary, dict):
        return evidence
    summary_counts = summary.get("counts", {}) if isinstance(summary.get("counts"), dict) else {}
    summary_mission_count = int(summary_counts.get("missions") or 0)
    if summary_mission_count <= 0:
        return evidence
    evidence_counts = evidence.get("counts", {}) if isinstance(evidence.get("counts"), dict) else {}
    evidence_mission_count = int(evidence_counts.get("missions") or 0)
    summary_checked_at = str(summary.get("generatedAt") or "").strip()
    if _parse_iso_timestamp(summary_checked_at) <= 0:
        summary_checked_at = datetime.now(timezone.utc).isoformat()
    summary_ts = _parse_iso_timestamp(summary_checked_at)
    evidence_ts = max(
        _parse_iso_timestamp(str(evidence.get("checkedAt") or "")),
        _parse_iso_timestamp(str(evidence.get("sourceGeneratedAt") or "")),
    )
    if evidence:
        if evidence_mission_count > summary_mission_count:
            return evidence
        if evidence_mission_count == summary_mission_count and evidence_ts >= summary_ts:
            return evidence
    missions = summary.get("missions", []) if isinstance(summary.get("missions"), list) else []
    notifications = summary.get("notifications", []) if isinstance(summary.get("notifications"), list) else []
    running = [item for item in missions if isinstance(item, dict) and item.get("status") == "running"]
    slice_notifications = [
        item
        for item in notifications
        if isinstance(item, dict) and item.get("kind") == "mission_slice_completed"
    ]
    return {
        **evidence,
        "sourcePath": "ControlRoomStore.build_summary_snapshot()",
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "sourceGeneratedAt": summary_checked_at,
        "status": "passed",
        "counts": summary_counts,
        "runtimeCounts": summary.get("runtimeCounts", {}) if isinstance(summary.get("runtimeCounts"), dict) else {},
        "statusCounts": summary.get("statusCounts", {}) if isinstance(summary.get("statusCounts"), dict) else {},
        "notificationCount": len(notifications),
        "sliceNotificationCount": len(slice_notifications),
        "runningMissions": running,
        "passedChecks": [
            *(
                evidence.get("passedChecks", [])
                if isinstance(evidence.get("passedChecks"), list)
                else []
            ),
            "control-room-summary-in-process-current",
        ],
        "supersededStaleReport": bool(evidence and evidence_mission_count < summary_mission_count),
        "supersededMissionCount": evidence_mission_count,
        "supersededSourceGeneratedAt": evidence.get("sourceGeneratedAt") or evidence.get("checkedAt"),
    }


def _sort_report_candidates(candidates: list[Path], *, timestamp_field: str) -> list[Path]:
    unique: dict[Path, Path] = {}
    for path in candidates:
        try:
            unique[path.resolve()] = path
        except OSError:
            unique[path] = path
    return sorted(
        unique.values(),
        key=lambda path: _report_candidate_sort_key(path, timestamp_field=timestamp_field),
        reverse=True,
    )


def _report_candidate_sort_key(path: Path, *, timestamp_field: str) -> tuple[float, float]:
    report = _load_json(path, {})
    timestamp = ""
    if isinstance(report, dict):
        timestamp = str(report.get(timestamp_field) or report.get("generatedAt") or "")
    parsed = _parse_iso_timestamp(timestamp)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (parsed, mtime)


def _parse_iso_timestamp(value: str) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return 0.0


def _load_route_trust_sampling_evidence(root: Path) -> dict[str, Any]:
    candidates = [
        root / ".agent_control" / "route_trust_sampling" / "latest.json",
        root / ".agent_control" / "route_trust_sampling" / "dry_run_latest.json",
    ]
    candidates.extend(
        sorted(
            (root / ".agent_control" / "release_artifacts").glob(
                "*/route_trust_sampling/*latest*.json"
            ),
            reverse=True,
        )
    )
    reports: list[tuple[float, Path, dict[str, Any]]] = []
    for path in candidates:
        report = _load_json(path, {})
        if not isinstance(report, dict) or report.get("schema") != "fluxio.route_trust_live_sampling_run.v1":
            continue
        generated_at = _parse_iso_timestamp(str(report.get("generatedAt") or ""))
        reports.append((generated_at, path, report))
    current_storage = _load_nas_storage_pressure_evidence(root)
    current_storage_blocking = _nas_storage_pressure_is_blocking(current_storage)
    has_live_sampling_report = any(
        isinstance(report, dict) and not bool(report.get("dryRun"))
        for _generated_at, _path, report in reports
    )
    for _generated_at, path, report in sorted(reports, key=lambda item: item[0], reverse=True):
        if (
            bool(report.get("dryRun"))
            and has_live_sampling_report
            and current_storage
            and not current_storage_blocking
            and str((report.get("storagePreflight") or {}).get("status") or "") in {"blocked", "dry_run_only"}
        ):
            continue
        launched = (
            report.get("launchedSamplingMissions", [])
            if isinstance(report.get("launchedSamplingMissions"), list)
            else []
        )
        skipped = (
            report.get("skippedSamplingMissions", [])
            if isinstance(report.get("skippedSamplingMissions"), list)
            else []
        )
        report_ok = report.get("ok")
        if report_ok is None:
            report_ok = bool(launched) and all(
                bool(item.get("ok", True)) for item in launched if isinstance(item, dict)
            )
        storage_preflight = (
            report.get("storagePreflight", {})
            if isinstance(report.get("storagePreflight"), dict)
            else {}
        )
        if storage_preflight and str(storage_preflight.get("status") or "") in {"blocked", "dry_run_only"}:
            status = str(storage_preflight.get("status") or "")
        else:
            status = "passed" if report_ok else "failed"
        return {
            "sourcePath": str(path.resolve()),
            "generatedAt": str(report.get("generatedAt") or ""),
            "status": status,
            "dryRun": bool(report.get("dryRun")),
            "runtime": str(report.get("runtime") or ""),
            "storagePreflight": storage_preflight,
            "capacity": report.get("capacity", {}) if isinstance(report.get("capacity"), dict) else {},
            "coverageBefore": (
                report.get("coverageBefore", {})
                if isinstance(report.get("coverageBefore"), dict)
                else {}
            ),
            "launchedSamplingMissions": launched,
            "skippedSamplingMissions": skipped,
            "nextAction": str(report.get("nextAction") or ""),
        }
    return {}


def _nas_storage_pressure_is_blocking(storage: dict[str, Any] | None) -> bool:
    if not isinstance(storage, dict) or not storage:
        return False
    status = str(storage.get("status") or "").lower()
    probe_failed = bool(storage.get("probeTimedOut")) or bool(storage.get("probeConnectFailed"))
    measured_usage_available = bool(storage.get("measuredUsageAvailable", not probe_failed))
    has_storage_evidence = bool(
        storage.get("schema")
        or storage.get("checkedAt")
        or storage.get("source")
        or status
    )
    return bool(
        has_storage_evidence
        and measured_usage_available
        and (
            status in {"critical", "full"}
            or int(storage.get("availableBytes") or 0) <= 0
            or int(storage.get("usedPercent") or 0) >= 99
        )
    )


def _nas_storage_probe_failed(storage: dict[str, Any] | None) -> bool:
    if not isinstance(storage, dict) or not storage:
        return False
    return bool(storage.get("probeTimedOut")) or bool(storage.get("probeConnectFailed"))


def _nas_storage_pressure_sentence(storage: dict[str, Any] | None) -> str:
    if not isinstance(storage, dict) or not storage:
        return "NAS storage pressure evidence is missing."
    mount = storage.get("mount", _default_nas_mount_label())
    if storage.get("probeConnectFailed"):
        return (
            f"{mount} storage is unverified because the bounded SSH probe could not connect "
            "before df data returned."
        )
    if storage.get("probeTimedOut"):
        return (
            f"{mount} storage is unverified because the bounded SSH probe timed out "
            "before current df data returned."
        )
    return (
        f"{mount} is {int(storage.get('usedPercent') or 0)}% used with "
        f"{int(storage.get('availableBytes') or 0)} available bytes."
    )


def _load_route_trust_sampling_closeout_evidence(root: Path) -> dict[str, Any]:
    candidates = [
        root / ".agent_control" / "route_trust_sampling" / "closeout_review_latest.json",
    ]
    candidates.extend(
        sorted(
            (root / ".agent_control" / "release_artifacts").glob(
                "*/route_trust_sampling/*closeout*.json"
            ),
            reverse=True,
        )
    )
    for path in candidates:
        report = _load_json(path, {})
        if not isinstance(report, dict) or report.get("schema") != "fluxio.route_trust_sampling_closeout_review.v1":
            continue
        proposals = report.get("proposals", []) if isinstance(report.get("proposals"), list) else []
        applied = (
            report.get("appliedCloseouts", [])
            if isinstance(report.get("appliedCloseouts"), list)
            else []
        )
        missing = report.get("missingMissions", []) if isinstance(report.get("missingMissions"), list) else []
        return {
            "sourcePath": str(path.resolve()),
            "generatedAt": str(report.get("generatedAt") or ""),
            "status": "passed" if report.get("ok") else "failed",
            "autoApply": bool(report.get("autoApply")),
            "proposals": proposals,
            "appliedCloseouts": applied,
            "missingMissions": missing,
            "nextAction": str(report.get("nextAction") or ""),
        }
    return {}


def _load_route_trust_sampling_loop_evidence(root: Path) -> dict[str, Any]:
    candidates = [
        root / ".agent_control" / "route_trust_sampling" / "loop_latest.json",
    ]
    candidates.extend(
        sorted(
            (root / ".agent_control" / "release_artifacts").glob(
                "*/route_trust_sampling/*loop*.json"
            ),
            reverse=True,
        )
    )
    for path in candidates:
        report = _load_json(path, {})
        if not isinstance(report, dict) or report.get("schema") != "fluxio.route_trust_sampling_loop.v1":
            continue
        return {
            "sourcePath": str(path.resolve()),
            "generatedAt": str(report.get("generatedAt") or ""),
            "status": "passed" if report.get("ok") else "failed",
            "reviewOnly": bool(report.get("reviewOnly")),
            "closeoutReview": (
                report.get("closeoutReview", {})
                if isinstance(report.get("closeoutReview"), dict)
                else {}
            ),
            "samplingLaunch": (
                report.get("samplingLaunch", {})
                if isinstance(report.get("samplingLaunch"), dict)
                else {}
            ),
            "nextAction": str(report.get("nextAction") or ""),
        }
    return {}


def _load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _load_jsonl(path: Path) -> list[Any]:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    rows: list[Any] = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _mission_items(payload: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(payload, dict):
        missions_value = payload.get("missions")
        if isinstance(missions_value, list):
            return _mission_items(missions_value)
        return [
            (str(key), value)
            for key, value in payload.items()
            if isinstance(value, dict)
        ]
    if isinstance(payload, list):
        return [
            (str(item.get("mission_id") or item.get("missionId") or item.get("id") or ""), item)
            for item in payload
            if isinstance(item, dict)
        ]
    return []


def _current_shell_text(root: Path, suffixes: tuple[str, ...]) -> str:
    """Source text of the current single shell (web/src/neyvia/next plus its entry), test files excluded."""
    base = root / "web" / "src" / "neyvia"
    files = [base / "NeyviaApp.tsx"] + sorted((base / "next").rglob("*"))
    return "\n".join(_safe_read(path) for path in files
                     if path.is_file() and path.suffix in suffixes and ".test." not in path.name and "vendor" not in path.parts)


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
