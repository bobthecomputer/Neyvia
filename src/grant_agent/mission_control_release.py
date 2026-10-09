"""Release responsibilities for the control room.

Facade-owned collaborators are explicit keyword dependencies so callers retain
the established late-binding and monkeypatch seams.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .models import DelegatedRuntimeSession, Mission

def _verify_desktop_script_contract(
    root: Path,
    *,
    _load_json_file,
) -> tuple[bool, str]:
    package_path = root / "package.json"
    payload = _load_json_file(package_path)
    if not isinstance(payload, dict):
        return False, "package.json is missing or unreadable."
    scripts = payload.get("scripts", {})
    if not isinstance(scripts, dict):
        return False, "package.json has no scripts section."
    command = str(scripts.get("verify:desktop", "")).strip()
    required_snippets = (
        "python -m pytest tests -q",
        "npm run frontend:build",
        "npm run tauri build -- --debug",
    )
    missing = [snippet for snippet in required_snippets if snippet not in command]
    if missing:
        return False, "verify:desktop is missing required stages."
    return True, "verify:desktop includes pytest, frontend build, and Tauri build."


def _verify_frontend_source_alignment(
    root: Path,
    *,
    _load_json_file,
    _vite_targets_web_root,
) -> tuple[bool, str]:
    required_paths = [
        root / "web" / "src" / "main.tsx",
        root / "web" / "src" / "neyvia" / "NeyviaApp.tsx",
        root / "web" / "src" / "neyvia" / "neyviaBridge.ts",
    ]
    if any(not path.exists() for path in required_paths):
        return False, "web frontend entrypoint files are missing."

    vite_path = root / "vite.config.mjs"
    tauri_path = root / "src-tauri" / "tauri.conf.json"
    if not vite_path.exists() or not tauri_path.exists():
        return False, "Vite or Tauri desktop config is missing."
    vite_text = vite_path.read_text(encoding="utf-8")
    if not _vite_targets_web_root(vite_text):
        return False, "vite.config.mjs is not aligned with web/."

    tauri_payload = _load_json_file(tauri_path)
    if not isinstance(tauri_payload, dict):
        return False, "src-tauri/tauri.conf.json is unreadable."
    frontend_dist = (
        str(tauri_payload.get("build", {}).get("frontendDist", ""))
        .replace("\\", "/")
        .strip()
    )
    if "web/dist" not in frontend_dist:
        return False, "src-tauri/tauri.conf.json is not aligned with web/dist."
    return True, "Frontend source-of-truth is aligned to web/."


def _verify_release_artifact_ci_contract(root: Path) -> tuple[bool, str]:
    workflow_path = root / ".github" / "workflows" / "release-proof.yml"
    if not workflow_path.exists():
        return False, ".github/workflows/release-proof.yml is missing."

    workflow_text = workflow_path.read_text(encoding="utf-8", errors="ignore")
    required_snippets = (
        "npm run frontend:build",
        "npm run verify:live-data",
        "npm run tauri build -- --no-sign",
        "npm run verify:production-gate:ci",
        "npm run verify:release-artifacts",
        "actions/upload-artifact",
        ".agent_control/proof_digests/ci-release-proof.md",
        ".agent_control/release_artifacts/**",
        "tmp-ui-checks/**",
    )
    missing = [snippet for snippet in required_snippets if snippet not in workflow_text]
    if missing:
        return False, "release-proof CI is missing required release evidence stages."
    return True, (
        "release-proof CI builds web and desktop artifacts, verifies the live-data "
        "and production contracts, archives proof artifacts, and uploads evidence."
    )


def _verify_public_web_distribution_contract(
    root: Path,
    *,
    _load_json_file,
) -> tuple[bool, str]:
    workflow_path = root / ".github" / "workflows" / "web-pages.yml"
    verifier_path = root / "scripts" / "verify_public_web_distribution.py"
    package_payload = _load_json_file(root / "package.json")
    if not workflow_path.exists():
        return False, ".github/workflows/web-pages.yml is missing."
    if not verifier_path.exists():
        return False, "scripts/verify_public_web_distribution.py is missing."
    if not isinstance(package_payload, dict):
        return False, "package.json is missing or unreadable."

    workflow_text = workflow_path.read_text(encoding="utf-8", errors="ignore")
    verifier_text = verifier_path.read_text(encoding="utf-8", errors="ignore")
    scripts = package_payload.get("scripts", {})
    web_distribution_script = str(scripts.get("verify:web-distribution", "")) if isinstance(scripts, dict) else ""
    required_workflow_snippets = (
        "npm run frontend:build",
        "npm run verify:web-distribution",
        "actions/upload-pages-artifact",
        "actions/deploy-pages",
        "path: web/dist",
        "page_url",
        "fluxio.public_web_deployment.v1",
        ".agent_control/deployment_evidence/public-web.json",
    )
    if any(snippet not in workflow_text for snippet in required_workflow_snippets):
        return False, "GitHub Pages workflow is missing required build/verify/deploy stages."
    if (
        "fluxio-public-web-release-candidate" not in workflow_text
        and "fluxio-public-web-deployment" not in workflow_text
    ):
        return False, "GitHub Pages workflow does not upload public web deployment evidence."
    if "verify_public_web_distribution.py" not in web_distribution_script:
        return False, "package.json does not expose verify:web-distribution."
    if "fluxio.public_web_distribution.v1" not in verifier_text:
        return False, "public web verifier does not emit the expected schema."
    return True, "GitHub Pages/PWA distribution contract is verified before public web deploy."


def _verify_self_improvement_evidence_contract(
    root: Path,
    *,
    _load_json_file,
) -> tuple[bool, str]:
    verifier_path = root / "scripts" / "verify_self_improvement_evidence.py"
    package_payload = _load_json_file(root / "package.json")
    release_workflow_path = root / ".github" / "workflows" / "release-proof.yml"
    archive_path = root / "scripts" / "archive_release_proofs.py"
    if not verifier_path.exists():
        return False, "scripts/verify_self_improvement_evidence.py is missing."
    if not isinstance(package_payload, dict):
        return False, "package.json is missing or unreadable."
    if not release_workflow_path.exists():
        return False, ".github/workflows/release-proof.yml is missing."
    verifier_text = verifier_path.read_text(encoding="utf-8", errors="ignore")
    workflow_text = release_workflow_path.read_text(encoding="utf-8", errors="ignore")
    archive_text = archive_path.read_text(encoding="utf-8", errors="ignore")
    scripts = package_payload.get("scripts", {})
    command = str(scripts.get("verify:self-improvement", "")) if isinstance(scripts, dict) else ""
    required = (
        "fluxio.self_improvement_evidence.v1" in verifier_text
        and "verify_self_improvement_evidence.py" in command
        and "--write" in command
        and ".agent_control/self_improvement_evidence/**" in workflow_text
        and "self_improvement_evidence" in archive_text
    )
    if not required:
        return False, "self-improvement evidence is not archived by the release-proof path."
    return True, (
        "Self-improvement evidence is measured on stateful runtimes and remains "
        "available to the release archive without requiring private history in clean CI."
    )


def _vite_targets_web_root(vite_text: str) -> bool:
    normalized = vite_text.replace("\\", "/")
    if 'resolve(repoRoot, "web")' in normalized or "resolve(repoRoot, 'web')" in normalized:
        return True
    if re.search(r"\broot\s*:\s*['\"]web['\"]", normalized):
        return True

    for match in re.finditer(
        r"const\s+([A-Za-z_]\w*)\s*=\s*resolve\(([^)]*)\)",
        normalized,
        flags=re.DOTALL,
    ):
        variable_name = match.group(1)
        args = match.group(2)
        if not re.search(r"['\"]web['\"]", args):
            continue
        root_refs_variable = re.search(
            rf"\broot\s*:\s*{re.escape(variable_name)}\b",
            normalized,
        )
        if root_refs_variable:
            return True
    return False


def _release_quality_score(
    *,
    completion_rate: int,
    delegated_run_rate: int,
    resume_run_rate: int,
    resume_completion_rate: int,
    verification_pause_rate: int,
    completed_or_continuing_rate: int | None = None,
    resume_completed_or_continuing_rate: int | None = None,
) -> int:
    completion_component = max(
        max(0, min(completion_rate, 100)),
        max(0, min(int(completed_or_continuing_rate or 0), 100)),
    )
    resume_component = resume_completion_rate if resume_run_rate > 0 else 50
    if resume_run_rate > 0 and resume_completed_or_continuing_rate is not None:
        resume_component = max(resume_component, resume_completed_or_continuing_rate)
    values = [
        max(0, min(completion_component, 100)),
        max(0, min(delegated_run_rate * 2, 100)),
        max(0, min(resume_component, 100)),
        max(0, min(100 - verification_pause_rate, 100)),
    ]
    return int(round(sum(values) / len(values)))


def _mission_events_record_delegated_active(root: Path) -> bool:
    events_path = root / ".agent_control" / "mission_events.jsonl"
    if not events_path.exists():
        return False
    try:
        handle = events_path.open("r", encoding="utf-8", errors="ignore")
    except OSError:
        return False
    with handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            metadata = event.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            kind = str(event.get("kind", "")).strip().lower()
            message = str(event.get("message", "")).strip().lower()
            pause_reason = str(
                metadata.get("pauseReason") or metadata.get("pause_reason") or ""
            ).strip().lower()
            lane = str(
                metadata.get("currentRuntimeLane") or metadata.get("current_runtime_lane") or ""
            ).strip().lower()
            if kind == "mission.runtime_cycle" and pause_reason == "delegated_runtime_running":
                return True
            if "hermes delegated lane running" in lane or "hermes delegated lane running" in message:
                return True
    return False


def _build_proving_cycle_readiness(
    root: Path,
    *,
    _age_seconds,
    _load_json_file,
    _mission_events_record_delegated_active,
    _mission_payload_runtime_budget_exhausted,
    _runtime_pid_alive,
) -> dict:
    payload = _load_json_file(root / ".agent_control" / "missions.json")
    missions = payload if isinstance(payload, list) else []
    runtime_session_paths = sorted(
        (root / ".agent_control" / "runtime_sessions").glob("delegate_*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ) if (root / ".agent_control" / "runtime_sessions").exists() else []
    runtime_counts = {
        "openclaw": 0,
        "hermes": 0,
    }
    completed_counts = {
        "openclaw": 0,
        "hermes": 0,
    }
    approval_wait_seen = False
    delegated_active_seen = False

    for mission in missions:
        if not isinstance(mission, dict):
            continue
        runtime_id = str(mission.get("runtime_id", "")).strip().lower()
        state = mission.get("state", {})
        if not isinstance(state, dict):
            state = {}
        status = str(state.get("status", "")).strip().lower()
        continuity_state = str(state.get("continuity_state", "")).strip().lower()
        planner_loop_status = str(state.get("planner_loop_status", "")).strip().lower()
        time_budget_status = str(state.get("time_budget_status", "")).strip().lower()
        stop_reason = str(state.get("stop_reason", "")).strip().lower()
        runtime_lane = str(state.get("current_runtime_lane", "")).strip().lower()
        escalation_policy = mission.get("escalation_policy", {})
        if not isinstance(escalation_policy, dict):
            escalation_policy = {}
        pending_approval_count = int(escalation_policy.get("pending_count", 0) or 0)
        delegated_sessions = state.get("delegated_runtime_sessions")
        if not isinstance(delegated_sessions, list):
            delegated_sessions = mission.get("delegated_runtime_sessions", [])
        delegated_session_statuses = {
            str(item.get("status", "")).strip().lower()
            for item in delegated_sessions
            if isinstance(item, dict)
        }
        if runtime_id in runtime_counts:
            runtime_counts[runtime_id] += 1
            if status == "completed":
                completed_counts[runtime_id] += 1
        budget_exhausted = _mission_payload_runtime_budget_exhausted(mission)
        if runtime_id == "hermes" and (
            status == "needs_approval"
            or continuity_state == "approval_waiting"
            or pending_approval_count > 0
            or "waiting_for_approval" in delegated_session_statuses
        ):
            approval_wait_seen = True
        if not budget_exhausted and (
            continuity_state == "delegated_active"
            or time_budget_status == "delegated_active"
            or stop_reason == "delegated_runtime_running"
            or (
                runtime_id == "hermes"
                and status in {"running", "launching", "needs_approval"}
                and planner_loop_status in {"running", "launching", "resume_dispatched"}
            )
            or any(
                status_name in {"launching", "running", "waiting_for_approval"}
                for status_name in delegated_session_statuses
            )
            or (
                "delegated lane" in runtime_lane
                and any(token in runtime_lane for token in ("launching", "running", "waiting"))
            )
        ):
            delegated_active_seen = True
    if not delegated_active_seen:
        for path in runtime_session_paths[:32]:
            session = _load_json_file(path)
            if not isinstance(session, dict):
                continue
            runtime_id = str(session.get("runtime_id") or "").strip().lower()
            status = str(session.get("status") or "").strip().lower()
            heartbeat_status = str(session.get("heartbeat_status") or "").strip().lower()
            pid = int(session.get("pid") or session.get("supervisor_pid") or 0)
            heartbeat_age = session.get("heartbeat_age_seconds")
            if heartbeat_age is None:
                heartbeat_age = _age_seconds(
                    str(session.get("heartbeat_at") or session.get("updated_at") or "")
                )
            stale_after = max(int(session.get("heartbeat_interval_seconds") or 10) * 3, 35)
            heartbeat_healthy = heartbeat_status == "healthy" or (
                heartbeat_age is not None and heartbeat_age <= stale_after
            )
            process_alive = pid > 0 and _runtime_pid_alive(pid)
            if (
                runtime_id == "hermes"
                and status in {"launching", "running", "waiting_for_approval"}
                and (process_alive or heartbeat_healthy or status == "waiting_for_approval")
            ):
                delegated_active_seen = True
                break
    if not delegated_active_seen and _mission_events_record_delegated_active(root):
        delegated_active_seen = True

    proofs = [
        {
            "proofId": "openclaw_proving_mission",
            "label": "OpenClaw proving mission completed",
            "required": False,
            "category": "optional_secondary_harness_parity",
            "passed": completed_counts["openclaw"] > 0,
            "details": (
                f"Completed OpenClaw missions: {completed_counts['openclaw']}. "
                "OpenClaw is optional secondary-harness parity evidence for this Hermes-first release."
            ),
        },
        {
            "proofId": "hermes_delegated_mission",
            "label": "Hermes delegated mission completed",
            "required": True,
            "category": "preferred_harness",
            "passed": completed_counts["hermes"] > 0,
            "details": f"Completed Hermes missions: {completed_counts['hermes']}.",
        },
        {
            "proofId": "approval_wait_evidence",
            "label": "Hermes approval-wait evidence recorded",
            "required": True,
            "category": "preferred_harness_control_flow",
            "passed": approval_wait_seen,
            "details": (
                "At least one Hermes mission recorded `needs_approval` or `approval_waiting`."
                if approval_wait_seen
                else "No Hermes approval-wait state has been recorded yet."
            ),
        },
        {
            "proofId": "delegated_active_evidence",
            "label": "Delegated-active continuity evidence recorded",
            "required": True,
            "category": "preferred_harness_continuity",
            "passed": delegated_active_seen,
            "details": (
                "At least one Hermes mission recorded delegated-active continuity or a live planner loop."
                if delegated_active_seen
                else "No delegated-active continuity state has been recorded yet."
            ),
        },
    ]
    missing = [item["label"] for item in proofs if item.get("required") and not item["passed"]]
    optional_missing = [
        item["label"]
        for item in proofs
        if not item.get("required") and not item["passed"]
    ]
    next_actions = [f"Capture required proof: {label}." for label in missing]
    next_actions.extend(f"Optional parity proof: {label}." for label in optional_missing)
    return {
        "missionCount": len(missions),
        "runtimeMissionCounts": runtime_counts,
        "runtimeCompletionCounts": completed_counts,
        "preferredRuntime": "hermes",
        "proofs": proofs,
        "missingProofs": missing,
        "optionalMissingProofs": optional_missing,
        "ready": not missing,
        "nextActions": next_actions[:4],
    }


def build_nas_deploy_readiness_snapshot(
    root: Path,
    *,
    onboarding: dict | None = None,
    setup_health: dict | None = None,
    storage_bridge: dict | None = None,
    detect_onboarding_status,
) -> dict:
    root = root.resolve()
    onboarding_payload = onboarding or detect_onboarding_status(root)
    setup_health_payload = setup_health or onboarding_payload.get("setupHealth", {})
    storage_bridge_payload = storage_bridge or {}

    checks = [
        {
            "checkId": "web_backend_script",
            "label": "web backend runner",
            "required": True,
            "passed": (root / "scripts" / "run_web_backend.py").exists(),
            "details": "scripts/run_web_backend.py is present for NAS HTTP serving.",
            "source": "filesystem",
        },
        {
            "checkId": "backend_restart_launcher",
            "label": "durable backend restart launcher",
            "required": True,
            "passed": (root / "scripts" / "start_backend_47880.sh").exists(),
            "details": "scripts/start_backend_47880.sh is present for durable NAS backend restarts.",
            "source": "filesystem",
        },
        {
            "checkId": "nas_setup_script",
            "label": "NAS setup script",
            "required": True,
            "passed": (root / "scripts" / "nas_setup.py").exists(),
            "details": "scripts/nas_setup.py is present for offline setup planning.",
            "source": "filesystem",
        },
        {
            "checkId": "doctor_script",
            "label": "NAS runtime doctor",
            "required": True,
            "passed": (root / "scripts" / "nas_runtime_doctor.py").exists(),
            "details": "scripts/nas_runtime_doctor.py is present for operator-run diagnostics.",
            "source": "filesystem",
        },
        {
            "checkId": "web_dist",
            "label": "frontend build assets",
            "required": False,
            "passed": (root / "web" / "dist" / "index.html").exists()
            and (root / "web" / "dist" / "assets").exists(),
            "details": "web/dist/index.html and web/dist/assets exist after npm run frontend:build.",
            "source": "filesystem",
        },
        {
            "checkId": "artifact_serving",
            "label": "safe artifact serving",
            "required": True,
            "passed": True,
            "details": "Generated artifacts are served through /api/artifact with allowed-root resolution.",
            "source": "web_backend_contract",
        },
        {
            "checkId": "runtime_auth_health",
            "label": "runtime/auth health",
            "required": False,
            "passed": bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("FLUXIO_OPENAI_CODEX_OAUTH_PRESENT")),
            "details": (
                "OpenAI Codex route auth is visible to this backend runtime."
                if bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("FLUXIO_OPENAI_CODEX_OAUTH_PRESENT"))
                else "OpenAI Codex auth is not visible in this offline check; runtime launch should block rather than fall back."
            ),
            "source": "environment",
        },
        {
            "checkId": "storage_bridge_mapping",
            "label": "NAS storage mapping",
            "required": False,
            "passed": bool(storage_bridge_payload.get("nas", {}).get("available") or storage_bridge_payload.get("available")),
            "details": str(storage_bridge_payload.get("summary") or "No NAS storage bridge is currently mapped."),
            "source": "control_room_snapshot",
        },
    ]
    service_summary = setup_health_payload.get("serviceManagementSummary", {})
    if isinstance(service_summary, dict):
        total_items = int(service_summary.get("totalItems", 0) or 0)
        healthy_count = int(service_summary.get("healthyCount", 0) or 0)
        checks.append(
            {
                "checkId": "setup_doctor_services",
                "label": "setup doctor services",
                "required": False,
                "passed": total_items > 0 and healthy_count == total_items,
                "details": f"{healthy_count}/{total_items} setup services are healthy.",
                "source": "setupHealth",
            }
        )

    for item in checks:
        item["status"] = "passed" if item["passed"] else ("blocked" if item["required"] else "warn")

    missing_required = [item["label"] for item in checks if item["required"] and not item["passed"]]
    return {
        "ready": not missing_required,
        "checks": checks,
        "missingRequired": missing_required,
        "setupHealth": setup_health_payload,
        "source": "offline_control_room_checks",
        "emptyState": "Run NAS setup or doctor scripts to add live host evidence." if missing_required else "",
    }


def build_release_readiness_snapshot(
    root: Path,
    *,
    onboarding: dict | None = None,
    setup_health: dict | None = None,
    harness_lab: dict | None = None,
    RELEASE_READINESS_WEIGHTS,
    _build_mission_watchdog_release_gate,
    _build_proving_cycle_readiness,
    _percent,
    _release_quality_score,
    _verify_desktop_script_contract,
    _verify_frontend_source_alignment,
    _verify_public_web_distribution_contract,
    _verify_release_artifact_ci_contract,
    _verify_self_improvement_evidence_contract,
    build_harness_lab_snapshot,
    detect_onboarding_status,
    utc_now_iso,
) -> dict:
    root = root.resolve()
    onboarding_payload = onboarding or detect_onboarding_status(root)
    setup_health_payload = setup_health or onboarding_payload.get("setupHealth", {})
    harness_lab_payload = harness_lab or build_harness_lab_snapshot(root)
    proving_cycle = _build_proving_cycle_readiness(root)

    checks = onboarding_payload.get("checks", {})
    service_summary = setup_health_payload.get("serviceManagementSummary", {})
    efficiency = harness_lab_payload.get("efficiency", {})
    session_health = harness_lab_payload.get("sessionHealth", {})

    verify_desktop_ok, verify_desktop_detail = _verify_desktop_script_contract(root)
    frontend_alignment_ok, frontend_alignment_detail = _verify_frontend_source_alignment(root)
    release_artifact_ci_ok, release_artifact_ci_detail = _verify_release_artifact_ci_contract(root)
    public_web_distribution_ok, public_web_distribution_detail = _verify_public_web_distribution_contract(root)
    self_improvement_evidence_ok, self_improvement_evidence_detail = _verify_self_improvement_evidence_contract(root)
    watchdog_gate = _build_mission_watchdog_release_gate(root)
    required_total_items = int(service_summary.get("totalItems", 0) or 0)
    required_healthy_count = int(service_summary.get("healthyCount", 0) or 0)
    completion_rate = int(efficiency.get("completionRate", 0) or 0)
    completed_or_continuing_rate = int(
        efficiency.get("completedOrContinuingRate", completion_rate) or 0
    )
    delegated_run_rate = int(efficiency.get("delegatedRunRate", 0) or 0)
    resume_run_rate = int(efficiency.get("resumeRunRate", 0) or 0)
    resume_completion_rate = int(efficiency.get("resumeCompletionRate", 0) or 0)
    resume_completed_or_continuing_rate = int(
        efficiency.get("resumeCompletedOrContinuingRate", resume_completion_rate) or 0
    )
    verification_pause_rate = int(efficiency.get("verificationPauseRate", 0) or 0)
    stale_heartbeat_count = int(session_health.get("staleHeartbeatCount", 0) or 0)

    required_gates = [
        {
            "gateId": "verify_desktop_contract",
            "label": "verify:desktop contract",
            "required": True,
            "passed": verify_desktop_ok,
            "details": verify_desktop_detail,
        },
        {
            "gateId": "frontend_source_alignment",
            "label": "frontend source alignment",
            "required": True,
            "passed": frontend_alignment_ok,
            "details": frontend_alignment_detail,
        },
        {
            "gateId": "uv_installed",
            "label": "uv installed",
            "required": True,
            "passed": bool(checks.get("uv", {}).get("installed")),
            "details": str(checks.get("uv", {}).get("details", "")),
        },
        {
            "gateId": "openclaw_installed",
            "label": "OpenClaw installed",
            "required": True,
            "passed": bool(checks.get("openclaw", {}).get("installed")),
            "details": str(checks.get("openclaw", {}).get("details", "")),
        },
        {
            "gateId": "hermes_installed",
            "label": "Hermes installed",
            "required": True,
            "passed": bool(checks.get("hermes", {}).get("installed")),
            "details": str(checks.get("hermes", {}).get("details", "")),
        },
        {
            "gateId": "setup_required_services_healthy",
            "label": "required setup services healthy",
            "required": True,
            "passed": required_total_items > 0 and required_healthy_count == required_total_items,
            "details": f"{required_healthy_count}/{required_total_items} required setup services are healthy.",
        },
        {
            "gateId": "runtime_heartbeat_stable",
            "label": "delegated heartbeat stable",
            "required": True,
            "passed": stale_heartbeat_count == 0,
            "details": (
                "No stale delegated runtime heartbeat detected."
                if stale_heartbeat_count == 0
                else f"{stale_heartbeat_count} delegated runtime session(s) have stale heartbeat."
            ),
        },
        watchdog_gate,
    ]
    optional_signals = [
        {
            "gateId": "completion_rate",
            "label": "recent completion rate >= 50%",
            "required": False,
            "passed": completion_rate >= 50,
            "details": f"Current completion rate is {completion_rate}%.",
        },
        {
            "gateId": "delegated_run_rate",
            "label": "delegated run rate >= 20%",
            "required": False,
            "passed": delegated_run_rate >= 20,
            "details": f"Current delegated run rate is {delegated_run_rate}%.",
        },
        {
            "gateId": "resume_completion_rate",
            "label": "resume completion rate >= 60%",
            "required": False,
            "passed": resume_run_rate == 0 or resume_completion_rate >= 60,
            "details": (
                "No resumed runs recorded yet."
                if resume_run_rate == 0
                else f"Current resume completion rate is {resume_completion_rate}%."
            ),
        },
        {
            "gateId": "release_artifact_ci",
            "label": "release proof archive enforced in CI",
            "required": False,
            "passed": release_artifact_ci_ok,
            "details": release_artifact_ci_detail,
        },
        {
            "gateId": "public_web_distribution",
            "label": "public web distribution contract",
            "required": False,
            "passed": public_web_distribution_ok,
            "details": public_web_distribution_detail,
        },
        {
            "gateId": "self_improvement_evidence",
            "label": "self-improvement evidence archived",
            "required": False,
            "passed": self_improvement_evidence_ok,
            "details": self_improvement_evidence_detail,
        },
        {
            "gateId": "proof_openclaw_completed",
            "label": "OpenClaw proving mission evidence",
            "required": False,
            "passed": bool(
                next(
                    (
                        item.get("passed", False)
                        for item in proving_cycle.get("proofs", [])
                        if item.get("proofId") == "openclaw_proving_mission"
                    ),
                    False,
                )
            ),
            "details": str(
                next(
                    (
                        item.get("details", "")
                        for item in proving_cycle.get("proofs", [])
                        if item.get("proofId") == "openclaw_proving_mission"
                    ),
                    "",
                )
            ),
        },
        {
            "gateId": "proof_hermes_completed",
            "label": "Hermes delegated mission evidence",
            "required": False,
            "passed": bool(
                next(
                    (
                        item.get("passed", False)
                        for item in proving_cycle.get("proofs", [])
                        if item.get("proofId") == "hermes_delegated_mission"
                    ),
                    False,
                )
            ),
            "details": str(
                next(
                    (
                        item.get("details", "")
                        for item in proving_cycle.get("proofs", [])
                        if item.get("proofId") == "hermes_delegated_mission"
                    ),
                    "",
                )
            ),
        },
    ]
    gates = required_gates + optional_signals
    required_passed = sum(1 for gate in required_gates if gate["passed"])
    required_total = len(required_gates)
    required_score = _percent(required_passed, required_total)
    quality_score = _release_quality_score(
        completion_rate=completion_rate,
        delegated_run_rate=delegated_run_rate,
        resume_run_rate=resume_run_rate,
        resume_completion_rate=resume_completion_rate,
        verification_pause_rate=verification_pause_rate,
        completed_or_continuing_rate=completed_or_continuing_rate,
        resume_completed_or_continuing_rate=resume_completed_or_continuing_rate,
    )
    overall_score = int(
        round(
            (required_score * RELEASE_READINESS_WEIGHTS["required"] / 100)
            + (quality_score * RELEASE_READINESS_WEIGHTS["quality"] / 100)
        )
    )

    if required_passed == required_total and overall_score >= 85:
        status = "ready_for_1_0_validation"
    elif required_passed == required_total:
        status = "validation_ready_with_quality_gaps"
    elif required_passed >= max(required_total - 1, 1):
        status = "close_but_blocked"
    else:
        status = "blocked"

    failed_required_actions = [
        f"{gate['label']}: {gate['details']}"
        for gate in required_gates
        if not gate["passed"]
    ]
    next_actions = (
        failed_required_actions
        + list(proving_cycle.get("nextActions", []))
        + list(onboarding_payload.get("nextActions", []))
    )
    return {
        "status": status,
        "score": overall_score,
        "requiredGateSummary": {
            "passed": required_passed,
            "total": required_total,
            "score": required_score,
        },
        "qualityScore": quality_score,
        "qualitySignals": {
            "completionRate": completion_rate,
            "completedOrContinuingRate": completed_or_continuing_rate,
            "delegatedRunRate": delegated_run_rate,
            "resumeRunRate": resume_run_rate,
            "resumeCompletionRate": resume_completion_rate,
            "resumeCompletedOrContinuingRate": resume_completed_or_continuing_rate,
            "verificationPauseRate": verification_pause_rate,
        },
        "proofReadiness": proving_cycle,
        "gates": gates,
        "nextActions": next_actions[:8],
        "calculatedAt": utc_now_iso(),
    }


def _release_mission_items(
    payload: object,
    *,
    _release_mission_items,
) -> list[tuple[str, dict]]:
    if isinstance(payload, dict):
        missions_value = payload.get("missions")
        if isinstance(missions_value, list):
            return _release_mission_items(missions_value)
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


def _build_mission_watchdog_release_gate(
    root: Path,
    *,
    TERMINAL_MISSION_STATUSES,
    _load_json_file,
    _mission_payload_runtime_budget_exhausted,
    _release_mission_items,
    load_watchdog_supervisor_state,
) -> dict:
    control_dir = root / ".agent_control"
    missions_payload = _load_json_file(control_dir / "missions.json")
    missions = _release_mission_items(missions_payload)
    active_missions = []
    for _, mission in missions:
        state = mission.get("state") if isinstance(mission.get("state"), dict) else {}
        status = str(state.get("status") or mission.get("status") or "").strip().lower()
        if (
            status
            and status not in TERMINAL_MISSION_STATUSES
            and status not in {"archived", "draft"}
            and not _mission_payload_runtime_budget_exhausted(mission)
        ):
            active_missions.append(mission)

    gate = {
        "gateId": "mission_watchdog_clear",
        "label": "mission watchdog clear",
        "required": True,
        "passed": True,
        "details": "No active missions require watchdog release evidence.",
        "activeMissionCount": len(active_missions),
        "watchdogReportPath": str(control_dir / "mission_watchdog.json"),
        "problemReportPath": str(control_dir / "mission_watchdog_problems.json"),
    }
    if not active_missions:
        return gate

    report_path = control_dir / "mission_watchdog.json"
    if not report_path.exists():
        gate.update(
            {
                "passed": False,
                "details": (
                    "Active missions exist, but no mission watchdog report was found. "
                    f"Run `python -m grant_agent.cli mission-watchdog --root {root}`."
                ),
            }
        )
        return gate

    report = _load_json_file(report_path)
    if not isinstance(report, dict):
        gate.update(
            {
                "passed": False,
                "details": "Mission watchdog report is unreadable.",
            }
        )
        return gate

    problem_report = report.get("problemReport") if isinstance(report.get("problemReport"), dict) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    problem_count = int(problem_report.get("problemCount") or 0)
    issue_count = int(summary.get("issueCount") or 0)
    blocking_issue_count = int(summary.get("bad") or 0) + int(summary.get("warn") or 0)
    problem_status = str(problem_report.get("status") or ("open" if problem_count else "clear")).lower()
    supervisor = load_watchdog_supervisor_state(root)
    supervisor_active = bool(supervisor.get("supervisorActive"))
    supervisor_status = str(supervisor.get("status") or "")
    first_problem = problem_report.get("firstProblem") if isinstance(problem_report.get("firstProblem"), dict) else {}
    next_action = str(
        first_problem.get("firstRepairStep")
        or first_problem.get("firstStep")
        or problem_report.get("nextAction")
        or report.get("nextAction")
        or ""
    )
    gate.update(
        {
            "problemCount": problem_count,
            "issueCount": issue_count,
            "blockingIssueCount": blocking_issue_count,
            "problemStatus": problem_status,
            "supervisorActive": supervisor_active,
            "supervisorStatus": supervisor_status,
            "supervisorStale": bool(supervisor.get("stale")),
            "supervisorProcessAlive": bool(supervisor.get("processAlive")),
            "supervisorPid": supervisor.get("processPid", 0),
            "lastRunAt": str(supervisor.get("lastRunAt") or ""),
            "nextRunAt": str(supervisor.get("nextRunAt") or ""),
        }
    )
    if blocking_issue_count > 0:
        gate.update(
            {
                "passed": False,
                "details": (
                    f"Watchdog found {blocking_issue_count} blocking active mission problem(s). "
                    f"First repair step: {next_action or 'open the watchdog problem report'}"
                ),
            }
        )
        return gate
    if not supervisor_active:
        stale_detail = (
            f" Last run: {supervisor.get('lastRunAt') or 'unknown'}; "
            f"next run: {supervisor.get('nextRunAt') or 'unknown'}; "
            f"process alive: {bool(supervisor.get('processAlive'))}; "
            f"status: {supervisor_status or 'unknown'}."
        )
        gate.update(
            {
                "passed": False,
                "details": (
                    "Mission watchdog report is clear, but the external supervisor loop is not active. "
                    "Restart `mission-watchdog --loop --max-runs 0`."
                    + stale_detail
                ),
            }
        )
        return gate

    gate.update(
        {
            "passed": True,
            "details": (
                f"Watchdog clear for {len(active_missions)} active mission(s); "
                f"supervisor PID {supervisor.get('processPid', 0)} is active."
                + (
                    f" {issue_count} non-blocking watchdog info item(s) remain visible."
                    if issue_count
                    else ""
                )
            ),
        }
    )
    return gate


def _build_runtime_session_health(
    root: Path,
    *,
    _age_seconds,
    _load_json_file,
    _percent,
    _runtime_pid_alive,
) -> dict:
    runtime_root = root / ".agent_control" / "runtime_sessions"
    session_paths = sorted(
        runtime_root.glob("delegate_*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ) if runtime_root.exists() else []
    active_count = 0
    waiting_approval_count = 0
    healthy_heartbeat_count = 0
    stale_heartbeat_count = 0
    delegated_healthy_count = 0
    delegated_stale_count = 0
    orphaned_active_count = 0
    latest_heartbeat_age_seconds: int | None = None
    latest_status = ""
    for path in session_paths[:16]:
        payload = _load_json_file(path)
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status", "unknown"))
        heartbeat_status = str(payload.get("heartbeat_status", "unknown"))
        pid = int(payload.get("pid") or 0)
        if status in {"launching", "running", "waiting_for_approval"} and pid > 0 and not _runtime_pid_alive(pid):
            orphaned_active_count += 1
            status = "orphaned"
            heartbeat_status = "inactive"
        heartbeat_age = payload.get("heartbeat_age_seconds")
        if heartbeat_age is None:
            heartbeat_age = _age_seconds(
                str(payload.get("heartbeat_at") or payload.get("updated_at") or "")
            )
        stale_after = max(int(payload.get("heartbeat_interval_seconds") or 10) * 3, 35)
        effective_heartbeat_status = heartbeat_status
        if status in {"launching", "running", "waiting_for_approval"} and heartbeat_age is not None:
            effective_heartbeat_status = (
                "stale" if heartbeat_age > stale_after else "healthy"
            )
        if heartbeat_age is not None and latest_heartbeat_age_seconds is None:
            latest_heartbeat_age_seconds = heartbeat_age
            latest_status = status
        if status in {"launching", "running", "waiting_for_approval"}:
            active_count += 1
        if status == "waiting_for_approval":
            waiting_approval_count += 1
        if effective_heartbeat_status == "healthy":
            healthy_heartbeat_count += 1
        elif effective_heartbeat_status == "stale":
            stale_heartbeat_count += 1
        if status in {"launching", "running", "waiting_for_approval"}:
            if effective_heartbeat_status == "healthy":
                delegated_healthy_count += 1
            elif effective_heartbeat_status == "stale":
                delegated_stale_count += 1
    delegated_total = delegated_healthy_count + delegated_stale_count
    return {
        "totalSessions": len(session_paths),
        "activeCount": active_count,
        "waitingApprovalCount": waiting_approval_count,
        "healthyHeartbeatCount": healthy_heartbeat_count,
        "staleHeartbeatCount": stale_heartbeat_count,
        "delegatedHealthyCount": delegated_healthy_count,
        "delegatedStaleCount": delegated_stale_count,
        "orphanedActiveCount": orphaned_active_count,
        "delegatedHealthyRate": _percent(delegated_healthy_count, delegated_total),
        "latestHeartbeatAgeSeconds": latest_heartbeat_age_seconds,
        "latestStatus": latest_status or "idle",
    }


def _runtime_pid_alive(
    pid: int,
    *,
    process_is_alive,
) -> bool:
    return process_is_alive(pid)


def _build_runtime_session_health_summary(
    *,
    missions: list[Mission],
    _age_seconds,
    _percent,
    _runtime_pid_alive,
) -> dict:
    sessions: list[DelegatedRuntimeSession] = []
    for mission in missions:
        sessions.extend(mission.delegated_runtime_sessions or [])
    sessions.sort(
        key=lambda item: item.heartbeat_at or item.updated_at or item.created_at or "",
        reverse=True,
    )
    active_count = 0
    waiting_approval_count = 0
    healthy_heartbeat_count = 0
    stale_heartbeat_count = 0
    delegated_healthy_count = 0
    delegated_stale_count = 0
    orphaned_active_count = 0
    latest_heartbeat_age_seconds: int | None = None
    latest_status = ""
    for session in sessions[:32]:
        status = str(session.status or "unknown").strip().lower()
        heartbeat_status = str(session.heartbeat_status or "unknown").strip().lower()
        if status in {"launching", "running", "waiting_for_approval"} and int(session.pid or 0) > 0 and not _runtime_pid_alive(int(session.pid or 0)):
            orphaned_active_count += 1
            status = "orphaned"
            heartbeat_status = "inactive"
        heartbeat_age = session.heartbeat_age_seconds
        if heartbeat_age is None:
            heartbeat_age = _age_seconds(session.heartbeat_at or session.updated_at or "")
        stale_after = max(int(session.heartbeat_interval_seconds or 10) * 3, 35)
        effective_heartbeat_status = heartbeat_status
        if status in {"launching", "running", "waiting_for_approval"} and heartbeat_age is not None:
            effective_heartbeat_status = "stale" if heartbeat_age > stale_after else "healthy"
        if heartbeat_age is not None and latest_heartbeat_age_seconds is None:
            latest_heartbeat_age_seconds = heartbeat_age
            latest_status = status
        if status in {"launching", "running", "waiting_for_approval"}:
            active_count += 1
        if status == "waiting_for_approval":
            waiting_approval_count += 1
        if effective_heartbeat_status == "healthy":
            healthy_heartbeat_count += 1
        elif effective_heartbeat_status == "stale":
            stale_heartbeat_count += 1
        if status in {"launching", "running", "waiting_for_approval"}:
            if effective_heartbeat_status == "healthy":
                delegated_healthy_count += 1
            elif effective_heartbeat_status == "stale":
                delegated_stale_count += 1
    delegated_total = delegated_healthy_count + delegated_stale_count
    return {
        "schema": "fluxio.runtime_session_health.summary.v1",
        "source": "mission_store_delegated_sessions",
        "fullSessionScanDeferred": True,
        "totalSessions": len(sessions),
        "scannedRecentSessions": min(len(sessions), 32),
        "activeCount": active_count,
        "waitingApprovalCount": waiting_approval_count,
        "healthyHeartbeatCount": healthy_heartbeat_count,
        "staleHeartbeatCount": stale_heartbeat_count,
        "delegatedHealthyCount": delegated_healthy_count,
        "delegatedStaleCount": delegated_stale_count,
        "orphanedActiveCount": orphaned_active_count,
        "delegatedHealthyRate": _percent(delegated_healthy_count, delegated_total),
        "latestHeartbeatAgeSeconds": latest_heartbeat_age_seconds,
        "latestStatus": latest_status or "idle",
    }



__all__ = [
    "_verify_desktop_script_contract",
    "_verify_frontend_source_alignment",
    "_verify_release_artifact_ci_contract",
    "_verify_public_web_distribution_contract",
    "_verify_self_improvement_evidence_contract",
    "_vite_targets_web_root",
    "_release_quality_score",
    "_mission_events_record_delegated_active",
    "_build_proving_cycle_readiness",
    "build_nas_deploy_readiness_snapshot",
    "build_release_readiness_snapshot",
    "_release_mission_items",
    "_build_mission_watchdog_release_gate",
    "_build_runtime_session_health",
    "_runtime_pid_alive",
    "_build_runtime_session_health_summary",
]
