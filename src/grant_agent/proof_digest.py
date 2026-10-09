from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .mission_control import ControlRoomStore
from .models import DelegatedRuntimeSession, Mission


def build_mission_proof_digest(root: Path, mission_id: str) -> dict[str, Any]:
    root = root.resolve()
    store = ControlRoomStore(root)
    mission = store.get_mission(mission_id)
    if mission is None:
        raise ValueError(f"Unknown mission id: {mission_id}")
    workspace = store.get_workspace(mission.workspace_id)
    state = asdict(mission.state)
    proof = asdict(mission.proof)
    sessions = [asdict(item) for item in mission.delegated_runtime_sessions]
    latest_session = sessions[-1] if sessions else {}
    provider_truth = state.get("provider_runtime_truth") or {}
    digest = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "workspaceRoot": str(root),
        "missionId": mission.mission_id,
        "workspaceId": mission.workspace_id,
        "workspaceName": workspace.name if workspace else "",
        "runtime": mission.runtime_id,
        "title": mission.title,
        "objective": mission.objective,
        "status": state.get("status") or mission.planner_loop_status,
        "plannerLoopStatus": state.get("planner_loop_status") or mission.planner_loop_status,
        "continuityState": state.get("continuity_state"),
        "timeBudgetStatus": state.get("time_budget_status"),
        "currentRuntimeLane": state.get("current_runtime_lane"),
        "stopReason": state.get("stop_reason"),
        "routeConfigs": mission.route_configs,
        "providerRuntimeTruth": provider_truth,
        "executionScope": asdict(mission.execution_scope),
        "verificationCommands": mission.verification_policy.commands,
        "successChecks": mission.success_checks,
        "proof": proof,
        "delegatedSessionCount": len(sessions),
        "latestDelegatedSession": latest_session,
        "pendingApprovals": proof.get("pending_approvals") or [],
        "failedChecks": proof.get("failed_checks") or [],
        "passedChecks": proof.get("passed_checks") or [],
        "changedFiles": proof.get("changed_files") or [],
        "blockedBy": proof.get("blocked_by") or [],
        "nextAction": _next_action(mission, latest_session),
    }
    return digest


def write_mission_proof_digest_markdown(digest: dict[str, Any], output_path: Path) -> Path:
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_mission_proof_digest_markdown(digest), encoding="utf-8")
    return output_path


def render_mission_proof_digest_markdown(digest: dict[str, Any]) -> str:
    provider_truth = digest.get("providerRuntimeTruth") or {}
    latest = digest.get("latestDelegatedSession") or {}
    lines = [
        "# Mission Proof Digest",
        "",
        f"Generated: `{digest.get('generatedAt')}`",
        f"Mission: `{digest.get('missionId')}`",
        f"Workspace: `{digest.get('workspaceName') or digest.get('workspaceId')}`",
        f"Runtime: `{digest.get('runtime')}`",
        "",
        "## Current State",
        "",
        f"- Status: `{digest.get('status')}`",
        f"- Planner loop: `{digest.get('plannerLoopStatus')}`",
        f"- Continuity: `{digest.get('continuityState')}`",
        f"- Time budget: `{digest.get('timeBudgetStatus')}`",
        f"- Runtime lane: `{digest.get('currentRuntimeLane')}`",
        f"- Stop reason: `{digest.get('stopReason')}`",
        f"- Next action: {digest.get('nextAction')}",
        "",
        "## Provider Truth",
        "",
        f"- Auth present: `{provider_truth.get('authPresent')}`",
        f"- Auth mode: `{provider_truth.get('authMode')}`",
        f"- Auth path: `{provider_truth.get('authPath')}`",
        f"- Active route: `{json.dumps(provider_truth.get('activeRoute') or {}, sort_keys=True)}`",
        f"- Last successful call: `{json.dumps(provider_truth.get('lastSuccessfulCall') or {}, sort_keys=True)}`",
        "",
        "## Proof",
        "",
        f"- Summary: {digest.get('proof', {}).get('summary') or ''}",
        f"- Passed checks: `{json.dumps(digest.get('passedChecks') or [])}`",
        f"- Failed checks: `{json.dumps(digest.get('failedChecks') or [])}`",
        f"- Changed files: `{json.dumps(digest.get('changedFiles') or [])}`",
        f"- Pending approvals: `{json.dumps(digest.get('pendingApprovals') or [])}`",
        f"- Blocked by: `{json.dumps(digest.get('blockedBy') or [])}`",
        "",
        "## Latest Delegated Session",
        "",
        f"- Session: `{latest.get('delegated_id') or latest.get('delegatedId') or ''}`",
        f"- Status: `{latest.get('status')}`",
        f"- Exit code: `{latest.get('exit_code')}`",
        f"- Updated at: `{latest.get('updated_at')}`",
        f"- Last event: {latest.get('last_event') or ''}",
        "",
        "## Objective",
        "",
        digest.get("objective") or "",
        "",
        "## Success Checks",
        "",
    ]
    lines.extend(f"- {item}" for item in digest.get("successChecks") or [])
    lines.append("")
    return "\n".join(lines)


def _next_action(mission: Mission, latest_session: dict[str, Any]) -> str:
    proof = mission.proof
    state = mission.state
    if proof.pending_approvals:
        return "Review and approve or reject the pending mission approval."
    if proof.failed_checks:
        return "Fix failed verification checks, then resume the mission."
    if latest_session.get("status") == "running":
        return "Watch the delegated runtime session until it emits completion or a blocker."
    if state.status == "completed":
        return "Review proof and close the mission."
    if state.status in {"blocked", "failed"}:
        return "Resolve the blocker and resume when evidence changes."
    if state.continuity_state == "delegated_active" and latest_session.get("status") == "completed":
        return "Resume once to reconcile the completed delegated lane into mission state."
    return "Resume or launch the next mission slice if the objective still has remaining work."
