from __future__ import annotations
from .proofs_c_control import checked as _control_checked
from .proofs_c_missions import checked_local_mission as _mission_local_checked
from .mission_control_workspace_deletion import workspace_state as _workspace_state

from .subprocess_utils import hidden_windows_subprocess_kwargs, process_is_alive

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from errno import EBUSY, ETXTBSY
from dataclasses import asdict, fields, is_dataclass, replace
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import quote, urlencode

from .models import (
    ApprovalEscalation,
    DelegatedRuntimeSession,
    ExecutionPolicy,
    ExecutionScope,
    IntegrationRecommendation,
    Mission,
    MissionCodeExecutionConfig,
    MissionEvent,
    MissionProof,
    MissionRunBudget,
    MissionStateSnapshot,
    MissionVerificationPolicy,
    SkillRecommendation,
    WorkspaceProfile,
    utc_now_iso,
)
from .cluster import ClusterRegistry
from .codex_import import load_latest_codex_import_rows
from .delivery_receipt import (
    load_delivery_receipts,
    ntfy_status,
    record_delivery_receipt,
    send_approval_escalation_receipt,
    web_push_status,
)
from .demo_runner import (
    build_red_team_escalation_audit,
    build_red_team_escalation_trend,
    load_red_team_escalation_history,
    normalize_red_team_pressure,
)
from .execution_truth import derive_execution_target
from .launch_recommendation import build_launch_runtime_recommendation
from .mission_artifacts import build_mission_run_artifact_layout
from .mission_receipts import load_mission_receipts
from .onboarding import (
    build_guidance_snapshot,
    detect_onboarding_status,
    invalidate_onboarding_status_cache,
    load_telegram_destination,
)
from .mission_watchdog import (
    build_mission_watchdog_report,
    build_planned_scope_artifacts,
    build_watchdog_problem_report,
    load_watchdog_supervisor_state,
)
from .profiles import ProfileRegistry
from .platform_config import platform_config
from .runtimes import detect_runtime_statuses, invalidate_runtime_status_cache
from .runtime_supervisor import DelegatedRuntimeSupervisor
from .skill_library import SkillLibrary, load_codex_home_skill_rows
from .skills import SkillRegistry
from .verification import detect_default_verification_commands

# Responsibility owners; the facade retains established callback patch seams.
from . import mission_control_integration as _mission_control_integration
from .mission_control_integration import (
    _integration_state,
    _integration_state_label,
)
from . import mission_control_operator_audit as _mission_control_operator_audit
from .mission_control_operator_audit import (
    _bootstrap_mission_artifact_repair_plan,
    _deployment_durability_summary,
    _red_team_current_cadence_is_healthy,
    _mission_advancement_summary,
    _operator_next_path_summary,
    _mission_gap_signal,
    _severity_label,
)
from . import mission_control_harness as _mission_control_harness
from .mission_control_harness import (
    _harness_efficiency_recommendation,
    _operator_value_feedback_signal,
    _route_trust_closeout_low_value,
    _shell_quote,
    _build_route_outcome_trends_for_trust,
    _route_outcome_quarantines,
    _quarantined_route_count,
    _build_harness_parity_matrix,
)
from . import mission_control_release as _mission_control_release
from .mission_control_release import (
    _verify_release_artifact_ci_contract,
    _vite_targets_web_root,
    _release_quality_score as _release_quality_score_impl,
    _mission_events_record_delegated_active,
)

from .mission_control_projections import ControlRoomProjectionMixin
from .mission_control_detail import ControlRoomDetailMixin
from .mission_control_artifact_gates import (
    _runtime_transcript_artifact_evidence_items,
    _mission_artifact_evidence_items,
    _mission_artifact_root_candidates,
    _read_gate_json,
    _read_gate_text,
    _delegated_session_value,
    _runtime_event_metadata,
    _delegated_runtime_event_rows,
    _low_signal_delegated_runtime_event,
    _delegated_runtime_event_transcript_messages,
    mission_runtime_dialogue_turns,
    mission_artifact_manifest_preview_url,
    _mission_manifest_folder_evidence_items,
    _runtime_transcript_output_evidence_items,
    _mission_runtime_output_evidence_items,
    mission_hard_artifact_gate,
    _mission_requires_hard_artifact_gate,
    _apply_hard_artifact_gate_if_completed,
    _planned_scope_artifacts_blocking,
    _apply_planned_scope_artifact_gate_if_completed,
    _clear_repaired_planned_scope_artifact_gate_failure,
    _mission_has_planned_scope_artifact_gate_failure,
    _complete_repaired_planned_scope_artifact_gate_from_detail,
    _clear_repaired_hard_artifact_gate_failure,
    _complete_repaired_hard_artifact_gate_from_detail,
)

TERMINAL_MISSION_STATUSES = {"completed", "failed", "stopped"}
WORKSPACE_SLOT_RELEASE_STATUSES = TERMINAL_MISSION_STATUSES | {"blocked", "verification_failed"}
ACTIVE_TIME_BUDGET_STATUSES = {"running", "delegated_active", "resume_dispatched", "active"}
EXHAUSTED_TIME_BUDGET_STATUSES = {"budget_exhausted", "runtime_budget_exhausted"}
PROCESS_RUNTIME_KINDS = {"runtime.output", "runtime.stdout", "runtime.stderr"}
MODEL_RUNTIME_KINDS = {"runtime.model_message", "model.message", "assistant.message"}
DELEGATED_TRANSCRIPT_RUNTIME_KINDS = PROCESS_RUNTIME_KINDS | MODEL_RUNTIME_KINDS | {"runtime.report"}
HARD_ARTIFACT_GATE_CHECK_ID = "hard_artifact_gate"
HARD_ARTIFACT_GATE_FAILURE = (
    "Hard artifact gate failed: no concrete runtime-output body or served artifact was recorded."
)
PLANNED_SCOPE_ARTIFACT_GATE_CHECK_ID = "planned_scope_artifacts"
PLANNED_SCOPE_ARTIFACT_GATE_FAILURE = (
    "Planned scope artifact gate failed: required planned artifact folders are missing or not previewable."
)
CONTROL_ROOM_SUMMARY_DURATION_BUDGET_MS = 250
CONTROL_ROOM_SUMMARY_PAYLOAD_BUDGET_BYTES = 350_000
CONTROL_ROOM_DETAIL_DURATION_BUDGET_MS = 250
CONTROL_ROOM_DETAIL_PAYLOAD_BUDGET_BYTES = 750_000
CONTROL_ROOM_FULL_SUMMARY_MISSION_LIMIT = 60
CONTROL_ROOM_VISIBLE_SUMMARY_MISSION_LIMIT = 12
CONTROL_ROOM_VISIBLE_PROJECT_PROGRESS_LIMIT = 3
CONTROL_ROOM_VISIBLE_LAUNCH_SHORTCUT_LIMIT = 3
CONTROL_ROOM_BOOTSTRAP_MISSION_LIMIT = 8
CONTROL_ROOM_BOOTSTRAP_RUNTIME_COMPARTMENT_LIMIT = 8
CONTROL_ROOM_BOOTSTRAP_RUNTIME_ACTIVITY_LIMIT = 2
CONTROL_ROOM_BOOTSTRAP_RUNTIME_MESSAGE_LIMIT = 4
CONTROL_ROOM_JSON_CACHE_MAX_BYTES = 8_000_000
CONTROL_ROOM_JSON_CACHE_MAX_ITEMS = 16
_CONTROL_ROOM_JSON_CACHE_LOCK = threading.RLock()
_WORKSPACE_UPDATE_LOCKS: dict[str, threading.RLock] = {}
_WORKSPACE_UPDATE_LOCKS_GUARD = threading.Lock()


def _serialize_workspace_update(action):
    """Retain every selected profile across concurrent read/merge/save callers."""
    @wraps(action)
    def update(self, *args, **kwargs):
        from .harness_jobs import _exclusive_job_lock
        path = self.workspaces_path
        with _WORKSPACE_UPDATE_LOCKS_GUARD:
            lock = _WORKSPACE_UPDATE_LOCKS.setdefault(str(path), threading.RLock())
        # Publication already leases the JSON path; use a distinct lifecycle
        # lease so the nested atomic writer never tries to reacquire it.
        with lock, _exclusive_job_lock(path.with_name(path.name + ".update")):
            return action(self, *args, **kwargs)
    return update
_CONTROL_ROOM_JSON_CACHE: dict[str, tuple[int, int, list | dict]] = {}


def _serialize_json_cache_read(action):
    """Keep cache capture, parsing/publication and identity checks together."""
    @wraps(action)
    def read(*args, **kwargs):
        with _CONTROL_ROOM_JSON_CACHE_LOCK:
            return action(*args, **kwargs)
    return read
PROVIDER_AUTH_PRESENCE_CACHE_TTL_SECONDS = 30
_PROVIDER_AUTH_PRESENCE_CACHE_LOCK = threading.Lock()
_PROVIDER_AUTH_PRESENCE_CACHE: tuple[float, tuple[tuple[str, str], ...], dict[str, bool]] | None = None
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CONTROL_PROJECT_ROOT_ENV = "FLUXIO_CONTROL_PROJECT_ROOT"
CONTROL_ROOM_AUTHORITY_FILENAME = "control_room_authority.json"


def resolve_control_room_authority_root(root: Path) -> Path:
    """Resolve the single project root that owns control-room state.

    The execution release and the control project can be different directories on
    NAS deployments.  An explicit environment setting wins, followed by a local
    pointer file.  With neither configured, the caller root remains authoritative.
    """

    requested_root = Path(root).expanduser().resolve()
    configured_root = str(os.environ.get(CONTROL_PROJECT_ROOT_ENV) or "").strip()
    if configured_root:
        return Path(configured_root).expanduser().resolve()

    authority_path = (
        requested_root / ".agent_control" / CONTROL_ROOM_AUTHORITY_FILENAME
    )
    if authority_path.is_file():
        try:
            payload = json.loads(authority_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict):
            raw_root = str(
                payload.get("controlProjectRoot")
                or payload.get("projectRoot")
                or payload.get("root")
                or ""
            ).strip()
            if raw_root:
                candidate = Path(raw_root).expanduser()
                if not candidate.is_absolute():
                    candidate = requested_root / candidate
                return candidate.resolve()
    return requested_root


def mission_runtime_budget_enforced(mission: Mission) -> bool:
    """Return true only for an explicitly persisted mission-level timer."""

    return bool(getattr(mission.run_budget, "enforced", False))


def workspace_inspection_path(workspace: WorkspaceProfile) -> Path:
    """Return the canonical filesystem root used for workspace checks and actions."""
    for value in (
        workspace.root_path,
        workspace.local_project_path,
        workspace.nas_project_path,
    ):
        clean_value = str(value or "").strip()
        if clean_value:
            return Path(clean_value).expanduser().resolve()
    workspace_label = workspace.workspace_id or workspace.name or "workspace"
    raise ValueError(f"Workspace {workspace_label} has no root path configured.")


def is_process_runtime_kind(kind: object) -> bool:
    return str(kind or "").strip().lower() in PROCESS_RUNTIME_KINDS


def _mission_runtime_budget_exhausted(mission: Mission) -> bool:
    status = str(mission.state.status or "").strip().lower()
    if status in WORKSPACE_SLOT_RELEASE_STATUSES or status == "draft":
        return False
    if not mission_runtime_budget_enforced(mission):
        return False
    stop_reason = str(
        mission.state.stop_reason or mission.state.last_budget_pause_reason or ""
    ).strip().lower()
    time_budget_status = str(mission.state.time_budget_status or "").strip().lower()
    if stop_reason == "runtime_budget" or time_budget_status in EXHAUSTED_TIME_BUDGET_STATUSES:
        return True
    max_runtime_seconds = max(0, int(mission.run_budget.max_runtime_seconds or 0))
    elapsed_runtime_seconds = max(0, int(mission.state.elapsed_runtime_seconds or 0))
    remaining_runtime_seconds = max(0, int(mission.state.remaining_runtime_seconds or 0))
    live_budget_window_active = (
        status == "running"
        and remaining_runtime_seconds > 0
        and time_budget_status in ACTIVE_TIME_BUDGET_STATUSES
    )
    return (
        status == "running"
        and max_runtime_seconds > 0
        and elapsed_runtime_seconds > 0
        and (
            remaining_runtime_seconds <= 0
            or (elapsed_runtime_seconds >= max_runtime_seconds and not live_budget_window_active)
        )
    )


def _refresh_delegated_runtime_session_for_summary(
    runtime_supervisor: DelegatedRuntimeSupervisor,
    session: DelegatedRuntimeSession,
) -> DelegatedRuntimeSession:
    try:
        refreshed = runtime_supervisor.refresh_session(session)
    except FileNotFoundError:
        return session
    lightweight_active = (
        str(session.status or "").strip().lower()
        in {"launching", "running", "waiting_for_approval"}
        and not str(session.session_path or "").strip()
        and int(session.pid or 0) <= 0
        and int(session.supervisor_pid or 0) <= 0
        and session.exit_code is None
    )
    missing_file_failure = (
        str(refreshed.status or "").strip().lower() == "failed"
        and "session file is missing or inaccessible"
        in str(refreshed.detail or "").strip().lower()
    )
    if lightweight_active and missing_file_failure:
        return session
    return refreshed


def _mission_counts_as_active_live(
    mission: Mission,
    *,
    require_queue_front: bool = True,
) -> bool:
    status = str(mission.state.status or "").strip().lower()
    if status not in {"launching", "running", "resume_dispatched"}:
        return False
    if str(mission.state.time_budget_status or "").strip().lower() == "reconcile_pending":
        return False
    if require_queue_front and int(mission.state.queue_position or 0) != 0:
        return False
    return not _mission_runtime_budget_exhausted(mission)


def _mission_occupies_workspace_slot(mission: Mission) -> bool:
    status = str(mission.state.status or "").strip().lower()
    if status in WORKSPACE_SLOT_RELEASE_STATUSES or status == "draft":
        return False
    if str(mission.state.time_budget_status or "").strip().lower() == "reconcile_pending":
        return False
    if int(mission.state.queue_position or 0) != 0:
        return False
    return not _mission_runtime_budget_exhausted(mission)


def _mission_releases_workspace_slot(mission: Mission) -> bool:
    status = str(mission.state.status or "").strip().lower()
    return status in WORKSPACE_SLOT_RELEASE_STATUSES or status == "draft"


def _mission_counts_as_attention(mission: Mission) -> bool:
    status = str(mission.state.status or "").strip().lower()
    return status in {"blocked", "needs_approval", "verification_failed"} or _mission_runtime_budget_exhausted(mission)


def _mission_counts_as_hard_blocked(mission: Mission) -> bool:
    status = str(mission.state.status or "").strip().lower()
    return status in {"blocked", "needs_approval", "verification_failed"}


@_control_checked("release-quality")

def _release_quality_score(*, completion_rate: int, delegated_run_rate: int, resume_run_rate: int,

                           resume_completion_rate: int, verification_pause_rate: int,

                           completed_or_continuing_rate: int | None = None,

                           resume_completed_or_continuing_rate: int | None = None) -> int:

    return _release_quality_score_impl(completion_rate=completion_rate, delegated_run_rate=delegated_run_rate,

        resume_run_rate=resume_run_rate, resume_completion_rate=resume_completion_rate,

        verification_pause_rate=verification_pause_rate, completed_or_continuing_rate=completed_or_continuing_rate,

        resume_completed_or_continuing_rate=resume_completed_or_continuing_rate)


@_control_checked("workspace-queue")

def _control_workspace_queue_projection(workspace_id: str, missions: list[Mission], *, include_terminal_queue: bool = False) -> dict:

    """Share the actual workspace ownership projection across shell collectors."""

    local = [item for item in missions if item.workspace_id == workspace_id]

    active = next((item for item in local if _mission_occupies_workspace_slot(item)), None)

    queued = [item for item in local if item.state.queue_position > 0 and (include_terminal_queue or item.state.status not in TERMINAL_MISSION_STATUSES)]

    return {

        "activeMissionId": active.mission_id if active else "",

        "activeMissionTitle": active.title if active else "",

        "activeMissionStatus": active.state.status if active else "",

        "queuedMissionIds": [item.mission_id for item in queued],

        "queuedMissionCount": len(queued),

        "missionCount": len(local),

    }


@_control_checked("mission-counts")

def _control_mission_counts_projection(missions: list[Mission]) -> dict:

    """Project recorded lifecycle facts without collecting runtime/provider state."""

    blocked = sum(item.state.status in {"blocked", "needs_approval", "verification_failed"} for item in missions)

    budget_attention = sum(_mission_runtime_budget_exhausted(item) for item in missions)

    return {

        "active": sum(_mission_counts_as_active_live(item) for item in missions),

        "queued": sum(item.state.status not in TERMINAL_MISSION_STATUSES and item.state.queue_position > 0 for item in missions),

        "blocked": blocked,

        "runtimeBudgetAttention": budget_attention,

        "attention": blocked + budget_attention,

    }


def _mission_payload_runtime_budget_exhausted(mission: dict) -> bool:
    state = mission.get("state") if isinstance(mission.get("state"), dict) else {}
    status = str(state.get("status") or mission.get("status") or "").strip().lower()
    if status in TERMINAL_MISSION_STATUSES or status in {"archived", "draft"}:
        return False
    stop_reason = str(
        state.get("stop_reason")
        or state.get("last_budget_pause_reason")
        or mission.get("stopReason")
        or ""
    ).strip().lower()
    time_budget_status = str(
        state.get("time_budget_status")
        or state.get("timeBudgetStatus")
        or mission.get("timeBudgetStatus")
        or ""
    ).strip().lower()
    if stop_reason == "runtime_budget" or time_budget_status in EXHAUSTED_TIME_BUDGET_STATUSES:
        return True
    run_budget = mission.get("run_budget") if isinstance(mission.get("run_budget"), dict) else {}
    run_budget = mission.get("runBudget") if isinstance(mission.get("runBudget"), dict) else run_budget
    if not bool(run_budget.get("enforced", False)):
        return False
    max_runtime_seconds = max(
        0,
        int(
            run_budget.get("max_runtime_seconds")
            or run_budget.get("maxRuntimeSeconds")
            or state.get("maxRuntimeSeconds")
            or mission.get("maxRuntimeSeconds")
            or 0
        ),
    )
    elapsed_runtime_seconds = max(
        0,
        int(
            state.get("elapsed_runtime_seconds")
            or state.get("elapsedRuntimeSeconds")
            or mission.get("elapsedRuntimeSeconds")
            or 0
        ),
    )
    remaining_runtime_seconds = max(
        0,
        int(
            state.get("remaining_runtime_seconds")
            or state.get("remainingRuntimeSeconds")
            or mission.get("remainingRuntimeSeconds")
            or 0
        ),
    )
    live_budget_window_active = (
        status == "running"
        and remaining_runtime_seconds > 0
        and time_budget_status in ACTIVE_TIME_BUDGET_STATUSES
    )
    return (
        status == "running"
        and max_runtime_seconds > 0
        and elapsed_runtime_seconds > 0
        and (
            remaining_runtime_seconds <= 0
            or (elapsed_runtime_seconds >= max_runtime_seconds and not live_budget_window_active)
        )
    )


def _gate_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _gate_mapping(value: object) -> dict:
    if is_dataclass(value):
        try:
            return asdict(value)
        except TypeError:
            return {}
    return value if isinstance(value, dict) else {}


def _gate_has_meaningful_text(value: object) -> bool:
    text = _gate_text(value).lower()
    if len(text) < 16:
        return False
    low_signal = (
        "mission completed with proof artifacts",
        "file mutation completed",
        "file read completed.",
        "planner revised the next steps",
        "git_diff completed with filesystem snapshot",
        "git is unavailable",
        "delegated runtime lane is active",
        "mission resume dispatched asynchronously",
        "mission resume already running",
    )
    return not any(marker in text for marker in low_signal)




MISSION_TITLE_STOPWORDS = {
    "a",
    "an",
    "the",
    "to",
    "for",
    "of",
    "and",
    "or",
    "in",
    "on",
    "with",
    "from",
    "into",
    "my",
    "your",
    "our",
}
MISSION_TITLE_PREFIXES = [
    r"^(please|pls)\s+",
    r"^(can|could|would)\s+you\s+",
    r"^i\s+(need|want)\s+you\s+to\s+",
    r"^help\s+me\s+(?:to\s+)?",
    r"^(let's|lets)\s+",
]
ROUTE_OVERRIDE_ROLES = {"planner", "backend", "frontend", "executor", "verifier"}
OPENAI_CODEX_AUTH_MODES = {"none", "api", "oauth"}
MINIMAX_AUTH_MODES = {"none", "minimax-portal-oauth", "minimax-api"}
MINIMAX_SETUP_ACTION_IDS = {
    "minimax-global-oauth",
    "minimax-cn-oauth",
    "minimax-global-api",
    "minimax-cn-api",
}


def normalize_route_role(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "plan": "planner",
        "planning": "planner",
        "back-end": "backend",
        "back end": "backend",
        "server": "backend",
        "server-side": "backend",
        "api": "backend",
        "front-end": "frontend",
        "front end": "frontend",
        "client": "frontend",
        "client-side": "frontend",
        "ui": "frontend",
        "ux": "frontend",
        "execute": "executor",
        "execution": "executor",
        "verify": "verifier",
        "verification": "verifier",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in ROUTE_OVERRIDE_ROLES else ""


HARNESS_RECENT_RUN_LIMIT = max(
    int(os.environ.get("FLUXIO_HARNESS_RECENT_RUN_LIMIT", "20")),
    8,
)
ROUTE_TRUST_REQUIRED_VALUE_SAMPLES = 2
ROUTE_TRUST_TASK_LABELS = {
    "frontend_design": "Frontend/UI/design",
    "hardware_electrical": "Hardware/electrical",
    "data_f1_analytics": "F1/data analytics",
    "research_analysis": "Research/OSINT",
    "security_red_team": "Security/red-team",
    "general_coding": "General coding",
}
ROUTE_TRUST_TASK_KEYWORDS = {
    "frontend_design": ("frontend", "ui", "ux", "design", "react", "css", "website", "mobile", "tablet"),
    "hardware_electrical": ("hardware", "electrical", "electronics", "pcb", "circuit", "sensor", "embedded"),
    "data_f1_analytics": ("f1", "formula 1", "telemetry", "lap time", "racing", "analytics", "dashboard"),
    "research_analysis": ("research", "report", "analysis", "geoint", "rf", "wireless", "maritime", "forensics"),
    "security_red_team": ("red team", "red-team", "defensive", "threat", "security", "hardening"),
}
MINIMAX_PROVIDER_IDS = {"minimax", "minimax-cn", "minimax-portal", "minimax-oauth"}
LEGACY_MINIMAX_MODELS = {
    "minimax-m2.7",
    "minimax-m2.7-highspeed",
    "minimax/m2.7",
    "minimax/minimax-m2.7",
    "minimax/minimax-m2.7-highspeed",
}
CURRENT_MINIMAX_FRONTEND_MODEL = "MiniMax-M3"
ROUTE_TRUST_SAMPLE_TEMPLATES = {
    "frontend_design": {
        "title": "Frontend trust sample",
        "objective": (
            "Build a polished phone/tablet Builder progress surface that shows mission status, "
            "notification receipts, and the first watchdog repair step. Use task-aware routing: "
            "Codex for planning, OpenCodeGo GLM-5.2 for UI work, "
            "and Hermes/OpenClaw verification where configured."
        ),
        "successChecks": [
            "Run the frontend build.",
            "Capture desktop and phone screenshots with the visual smoke script.",
            "Close the mission with an operator value score after testing the UI.",
        ],
        "preferredRuntime": "auto",
        "budgetHours": 4,
    },
    "hardware_electrical": {
        "title": "Hardware/electrical trust sample",
        "objective": (
            "Create a hardware/electrical discovery workbench for an F1-style sensor telemetry rig: "
            "component list, signal paths, basic circuit safety notes, and a beginner-readable build plan. "
            "Keep it legal, simulation-first, and artifact-backed."
        ),
        "successChecks": [
            "Produce a README-style report and a structured component table.",
            "Include verification notes for assumptions and safety limits.",
            "Close the mission with an operator value score after review.",
        ],
        "preferredRuntime": "auto",
        "budgetHours": 4,
    },
    "data_f1_analytics": {
        "title": "F1 analytics trust sample",
        "objective": (
            "Build an F1 telemetry analytics prototype with lap delta, sector comparison, tire stint, "
            "and driver consistency views. Include sample data and a preview artifact that can be opened "
            "from Builder."
        ),
        "successChecks": [
            "Generate a previewable dashboard or report artifact.",
            "Document the sample data and analytics assumptions.",
            "Close the mission with an operator value score after trying the artifact.",
        ],
        "preferredRuntime": "auto",
        "budgetHours": 4,
    },
    "research_analysis": {
        "title": "Research/OSINT trust sample",
        "objective": (
            "Create a defensive, public-source research dashboard concept for GEOINT/RF/maritime discovery. "
            "Focus on lawful data sources, visual timelines, uncertainty scoring, and evidence provenance."
        ),
        "successChecks": [
            "Produce a concise report with source/provenance fields.",
            "Include uncertainty labels and a next-investigation queue.",
            "Close the mission with an operator value score after review.",
        ],
        "preferredRuntime": "auto",
        "budgetHours": 4,
    },
    "security_red_team": {
        "title": "Defensive red-team trust sample",
        "objective": (
            "Run a defensive red-team escalation sample against Neyvia's mission supervision claims. "
            "Increase difficulty from the latest clean pass, record what failed, and propose one hardening "
            "patch with proof."
        ),
        "successChecks": [
            "Persist a red-team escalation row with difficulty and resistance score.",
            "Identify one concrete defensive improvement or prove none was needed.",
            "Close the mission with an operator value score after reviewing the result.",
        ],
        "preferredRuntime": "auto",
        "budgetHours": 4,
    },
    "general_coding": {
        "title": "General coding trust sample",
        "objective": (
            "Improve one beginner-facing Neyvia workflow end to end: choose a narrow friction point, "
            "patch the code, update the tutorial or proof surface, and verify it with focused tests."
        ),
        "successChecks": [
            "Run focused tests for the patched workflow.",
            "Update the relevant tutorial or control-room copy.",
            "Close the mission with an operator value score after trying the workflow.",
        ],
        "preferredRuntime": "auto",
        "budgetHours": 3,
    },
}


def canonical_route_model(provider: object, model: object) -> str:
    normalized_provider = str(provider or "").strip().lower()
    value = str(model or "").strip()
    if normalized_provider in MINIMAX_PROVIDER_IDS and value.lower() in LEGACY_MINIMAX_MODELS:
        return CURRENT_MINIMAX_FRONTEND_MODEL
    return value
RELEASE_READINESS_WEIGHTS = {
    "required": 80,
    "quality": 20,
}
SYNC_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".agent_control",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".next",
    "dist",
    "build",
}
SYNC_EXCLUDED_FILES = {".DS_Store", "Thumbs.db"}
SYNC_DIRECTIONS = {"bidirectional", "local_to_nas", "nas_to_local"}
SYNC_COPY_RETRY_ATTEMPTS = 3
SYNC_COPY_RETRY_BASE_DELAY_SECONDS = 0.08
SYNC_LOCKED_FILE_SAMPLE_LIMIT = 8
SYNC_CONFLICT_SAMPLE_LIMIT = 8
RELEASE_PATH_PATTERN = re.compile(
    r"^(?P<prefix>.+[\\/]releases[\\/])(?P<release>[^\\/]+)(?P<suffix>(?:[\\/].*)?)$"
)
PROVIDER_ENV_HINTS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "minimax-cn": "MINIMAX_API_KEY",
    "minimax-portal": "MINIMAX_OAUTH_TOKEN",
    "opencode-go": "OPENCODE_API_KEY",
    "kimi-code": "KIMI_API_KEY",
}


def build_red_team_escalation_snapshot(root: Path, *, limit: int = 100) -> dict:
    history = load_red_team_escalation_history(root, limit=limit)
    trend = build_red_team_escalation_trend(history)
    escalation_audit = build_red_team_escalation_audit(history)
    latest = trend.get("latest", {}) if isinstance(trend, dict) else {}
    return {
        "schema": "fluxio.red_team_escalation_snapshot.v1",
        "history": history,
        "trend": trend,
        "escalationAudit": escalation_audit,
        "nextBenchmarkPlan": _red_team_next_benchmark_plan(history, escalation_audit),
        "summary": {
            "runCount": int(trend.get("runCount", 0) or 0),
            "status": str(trend.get("status") or "empty"),
            "latestPreset": str(latest.get("preset") or ""),
            "latestResistanceScore": int(latest.get("resistance_score", 0) or 0),
            "latestDifficultyLevel": int(latest.get("difficultyLevel", 0) or 0),
            "nextDifficultyLevel": int(latest.get("nextDifficultyLevel", 0) or 0),
            "currentPressureIndex": int(latest.get("currentPressureIndex", 0) or 0),
            "nextPressureIndex": int(latest.get("nextPressureIndex", 0) or 0),
            "pressureDelta": int(latest.get("pressureDelta", 0) or 0),
            "nextDifficultyLabel": str(latest.get("nextDifficultyLabel") or ""),
            "nextAttemptBudget": int(latest.get("nextAttemptBudget", 0) or 0),
            "passStreak": int(latest.get("passStreak", 0) or 0),
            "cleanPass": bool(latest.get("cleanPass", False)),
            "shouldEscalate": bool(latest.get("shouldEscalate", False)),
            "difficultyTrend": int(trend.get("difficultyTrend", 0) or 0),
            "pressureTrend": int(trend.get("pressureTrend", 0) or 0),
            "resistanceTrend": int(trend.get("resistanceTrend", 0) or 0),
            "satisfiedEscalationTargets": int(escalation_audit.get("satisfiedTargets", 0) or 0),
            "pendingEscalationTargets": int(escalation_audit.get("pendingTargets", 0) or 0),
            "nextAction": str(
                trend.get("nextAction")
                or "Run a defensive red-team benchmark to start the escalation trend."
            ),
        },
    }


def _red_team_next_benchmark_plan(history: list[dict], audit: dict) -> dict:
    latest = history[-1] if history else {}
    target_row = next((row for row in reversed(history) if isinstance(row, dict) and row.get("shouldEscalate")), {})
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
PROVIDER_AUTH_ALIASES = {
    "openai": ("openai", "openai-api", "openai-codex"),
    "anthropic": ("anthropic", "claude"),
    "openrouter": ("openrouter",),
    "minimax": ("minimax", "minimax-cn", "minimax-portal", "minimax-oauth"),
    "minimax-cn": ("minimax", "minimax-cn", "minimax-portal", "minimax-oauth"),
    "minimax-portal": ("minimax", "minimax-cn", "minimax-portal", "minimax-oauth"),
    "opencode-go": ("opencode-go", "opencodego", "opencode"),
}


def _dataclass_from_mapping(cls, payload: object):
    if not isinstance(payload, dict):
        payload = {}
    allowed = {item.name for item in fields(cls)}
    return cls(**{key: value for key, value in payload.items() if key in allowed})


def _mission_runtime_persistence_signature(mission: Mission) -> str:
    return json.dumps(
        {
            "status": mission.state.status,
            "latestSessionId": mission.state.latest_session_id,
            "lastRuntimeEvent": mission.state.last_runtime_event,
            "continuityState": mission.state.continuity_state,
            "continuityDetail": mission.state.continuity_detail,
            "currentRuntimeLane": mission.state.current_runtime_lane,
            "pendingApproval": mission.state.pending_approval_payload,
            "approvalHistory": mission.state.approval_history,
            "delegatedSessions": [asdict(item) for item in mission.delegated_runtime_sessions],
            "laneControlReceipts": mission.state.lane_control_receipts,
        },
        sort_keys=True,
        default=str,
    )


def _mission_queue_persistence_signature(missions: list[Mission]) -> str:
    return json.dumps(
        [
            {
                "id": item.mission_id,
                "status": item.state.status,
                "queue": item.state.queue_position,
                "blocking": item.state.blocking_mission_id,
                "queueReason": item.state.queue_reason,
            }
            for item in missions
        ],
        sort_keys=True,
        default=str,
    )


def _latest_runtime_cycles_by_mission(events_path: Path) -> dict[str, dict]:
    if not events_path.exists():
        return {}
    latest: dict[str, dict] = {}
    try:
        handle = events_path.open("r", encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    with handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if event.get("kind") != "mission.runtime_cycle":
                continue
            mission_id = str(event.get("mission_id") or event.get("missionId") or "").strip()
            if not mission_id:
                continue
            latest[mission_id] = event
    return latest


def _reconcile_mission_from_runtime_cycle(
    mission: Mission,
    event: dict | None,
    *,
    root: Path | None = None,
    workspace: WorkspaceProfile | None = None,
) -> bool:
    if not isinstance(event, dict) or mission.state.status in TERMINAL_MISSION_STATUSES:
        return False
    event_time = _parse_iso_datetime(str(event.get("timestamp") or ""))
    mission_updated = _parse_iso_datetime(mission.updated_at)
    if event_time is not None and mission_updated is not None and event_time < mission_updated:
        return False
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    autopilot_status = str(metadata.get("autopilotStatus") or "").strip().lower()
    pause_reason = str(metadata.get("pauseReason") or "").strip()
    if autopilot_status != "completed" or pause_reason:
        return False
    mission.state.status = "completed"
    session_id = str(metadata.get("sessionId") or "").strip()
    if session_id:
        mission.state.latest_session_id = session_id
    gate = _apply_hard_artifact_gate_if_completed(mission)
    if bool(gate.get("required", True)) and not bool(gate.get("passed")):
        return True
    if root is not None:
        planned_scope_artifacts = build_planned_scope_artifacts(
            root=root,
            mission=mission,
            workspace=workspace,
        )
        if _apply_planned_scope_artifact_gate_if_completed(mission, planned_scope_artifacts):
            return True
    mission.state.last_runtime_event = "completed"
    mission.state.last_error = None
    mission.state.stop_reason = None
    mission.state.planner_loop_status = "completed"
    if _completion_summary_needs_replacement(mission.proof.summary):
        mission.proof.summary = "Mission completed with proof artifacts."
    return True


def _mission_has_hard_artifact_gate_failure(mission: Mission) -> bool:
    return mission.state.status == "verification_failed" and (
        HARD_ARTIFACT_GATE_CHECK_ID in mission.state.verification_failures
        or HARD_ARTIFACT_GATE_FAILURE in mission.state.verification_failures
        or HARD_ARTIFACT_GATE_FAILURE in mission.proof.failed_checks
        or mission.state.stop_reason == "artifact_gate_failed"
        or mission.state.last_runtime_event == "artifact_gate_failed"
    )


def _completion_summary_needs_replacement(value: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    if not normalized:
        return True
    transient_markers = (
        "mission resume dispatched asynchronously",
        "mission resume already running",
        "delegated runtime lane is active",
        "delegated runtime lane completed",
        "delegated runtime lane failed",
        "mission created and waiting",
        "waiting for mission",
        "planner revised the next steps",
        "mission bootstrapped",
    )
    return any(marker in normalized for marker in transient_markers)


def _auth_store_has_provider(path: Path, provider_id: str) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    needle = provider_id.strip().lower()

    def walk(value: object) -> bool:
        if isinstance(value, dict):
            if needle in {str(item).strip().lower() for item in value.keys()}:
                return True
            for key in ("providers", "credential_pool"):
                nested = value.get(key)
                if isinstance(nested, dict) and needle in {
                    str(item).strip().lower() for item in nested.keys()
                }:
                    return True
            provider = str(
                value.get("provider")
                or value.get("providerId")
                or value.get("provider_id")
                or ""
            ).strip().lower()
            if provider == needle:
                return True
            return any(walk(item) for item in value.values())
        if isinstance(value, list):
            return any(walk(item) for item in value)
        return False

    return walk(payload)


def hermes_auth_store_candidates(home: Path | None = None) -> list[Path]:
    home = home or Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    candidates: list[Path] = []
    explicit_store = str(os.environ.get("HERMES_AUTH_STORE", "")).strip()
    if explicit_store:
        candidates.append(Path(explicit_store).expanduser())
    hermes_home = str(os.environ.get("HERMES_HOME", "")).strip()
    if hermes_home:
        candidates.append(Path(hermes_home).expanduser() / "auth.json")
    candidates.append(home / ".hermes" / "auth.json")
    for runtime_home in _runtime_home_candidates():
        candidates.append(runtime_home / ".hermes" / "auth.json")
        candidates.append(runtime_home / "auth.json")
    if os.name == "nt" and not str(os.environ.get("FLUXIO_DISABLE_WSL_AUTH_DISCOVERY", "")).strip():
        try:
            result = subprocess.run(
                ["wsl", "bash", "-lc", 'printf "%s\t%s" "$WSL_DISTRO_NAME" "$HOME"'],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
                check=False,
                **hidden_windows_subprocess_kwargs(),
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        output = str(result.stdout or "").strip() if result is not None else ""
        wsl_identity = ""
        for line in reversed(output.splitlines()):
            if "\t" in line:
                wsl_identity = ANSI_ESCAPE_PATTERN.sub("", line).strip()
                break
        if wsl_identity:
            distro, wsl_home = wsl_identity.split("\t", 1)
            distro = distro.strip()
            wsl_home = wsl_home.strip().strip("/")
            if distro and wsl_home:
                for prefix in (r"\\wsl.localhost", r"\\wsl$"):
                    candidates.append(Path(prefix) / distro / wsl_home / ".hermes" / "auth.json")
    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            deduped.append(candidate)
    return deduped


def _runtime_home_candidates() -> list[Path]:
    candidates: list[Path] = []
    for env_name in ("FLUXIO_RUNTIME_HOME", "SYNTELOS_RUNTIME_HOME", "HOME"):
        value = str(os.environ.get(env_name) or "").strip()
        if value:
            candidates.append(Path(value).expanduser())
    try:
        cwd = Path.cwd().resolve()
    except OSError:
        cwd = Path.cwd()
    parts = cwd.parts
    if "releases" in parts:
        release_index = parts.index("releases")
        if release_index >= 1:
            base = Path(*parts[:release_index])
            candidates.append(base / "runtime" / "home")
    candidates.append(platform_config().nas_projects_root / "syntelos" / "runtime" / "home")
    return _dedupe_paths(candidates)


def _auth_store_candidates_have_provider(paths: list[Path], *provider_ids: str) -> bool:
    return any(
        _auth_store_has_provider(path, provider_id)
        for path in paths
        for provider_id in provider_ids
    )


def normalize_route_overrides(route_overrides: object, *, canonicalize_models: bool = True) -> list[dict]:
    if not isinstance(route_overrides, list):
        return []
    normalized: list[dict] = []
    for item in route_overrides:
        if not isinstance(item, dict):
            continue
        role = normalize_route_role(item.get("role", ""))
        provider = str(item.get("provider", "")).strip().lower()
        model = (
            canonical_route_model(provider, item.get("model", ""))
            if canonicalize_models
            else str(item.get("model", "")).strip()
        )
        if not role or not provider or not model:
            continue
        row = {
            "role": role,
            "provider": provider,
            "model": model,
        }
        runtime_id = str(
            item.get("runtimeId")
            or item.get("runtime_id")
            or item.get("runtime")
            or ""
        ).strip().lower()
        if runtime_id:
            row["runtimeId"] = runtime_id
        effort = str(item.get("effort", "")).strip().lower()
        if effort:
            row["effort"] = effort
        budget_class = str(item.get("budgetClass", item.get("budget_class", ""))).strip().lower()
        if budget_class:
            row["budgetClass"] = budget_class
        normalized.append(row)
    deduped: list[dict] = []
    seen_roles: set[str] = set()
    for item in normalized:
        role = item["role"]
        if role in seen_roles:
            continue
        seen_roles.add(role)
        deduped.append(item)
    return deduped


AGENT_TURN_MODES = {"standard", "plan", "fast", "max-context"}

AGENT_REASONING_EFFORTS = {
    "default",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "ultra",
}

PLAN_TURN_MODE_DIRECTIVE = (
    "Plan first: record a concrete step-by-step plan in the mission thread "
    "and keep it updated before making any file edits."
)

PLAN_TURN_MODE_SUCCESS_CHECK = (
    "A written step-by-step plan is recorded in the mission thread before any file edits."
)


def normalize_agent_turn_mode(value: object) -> str:
    normalized = str(value or "standard").strip().lower().replace("_", "-")
    aliases = {
        "1m": "max-context",
        "1m-context": "max-context",
        "max": "max-context",
        "maxcontext": "max-context",
        "million-context": "max-context",
        "planning": "plan",
        "speed": "fast",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in AGENT_TURN_MODES else "standard"


def normalize_agent_reasoning_effort(value: object) -> str:
    normalized = (
        str(value or "default")
        .strip()
        .lower()
        .replace("_", "-")
        .replace(" ", "-")
    )
    aliases = {
        "ultra-reasoning": "ultra",
        "ultrareasoning": "ultra",
        "x-high": "xhigh",
        "x_high": "xhigh",
        "extra-high": "xhigh",
        "extra_high": "xhigh",
        "med": "medium",
        "mid": "medium",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in AGENT_REASONING_EFFORTS:
        return normalized
    return "default"


def apply_agent_reasoning_effort_to_launch(
    *,
    reasoning_effort: object,
    objective: str,
    success_checks: list[str] | None,
    route_overrides: list[dict] | None,
    mode: str,
    budget_hours: object,
) -> dict:
    """Map an agent reasoning effort onto durable mission launch knobs."""
    from .ultra_reasoning import (
        ULTRA_DIRECTIVE,
        ULTRA_SUCCESS_CHECK,
        build_ultra_launch_profile,
    )

    resolved = normalize_agent_reasoning_effort(reasoning_effort)
    objective_text = str(objective or "")
    checks = [str(item) for item in (success_checks or []) if str(item).strip()]
    overrides = [dict(item) for item in (route_overrides or []) if isinstance(item, dict)]
    mission_mode = str(mode or "Autopilot")
    try:
        budget = float(budget_hours) if budget_hours is not None and str(budget_hours).strip() else 0.0
    except (TypeError, ValueError):
        budget = 0.0
    if resolved != "ultra":
        if resolved in {"low", "medium", "high", "xhigh", "max"}:
            overrides = [{**row, "effort": "xhigh" if resolved == "max" else resolved} for row in overrides]
        return {
            "reasoningEffort": resolved,
            "objective": objective_text,
            "successChecks": checks,
            "routeOverrides": overrides,
            "mode": mission_mode,
            "budgetHours": budget if budget > 0 else None,
            "missionContract": {},
            "executionTargetPreference": "",
        }

    if ULTRA_DIRECTIVE not in objective_text:
        objective_text = f"{objective_text}\n\n{ULTRA_DIRECTIVE}".strip()
    if ULTRA_SUCCESS_CHECK not in checks:
        checks = [*checks, ULTRA_SUCCESS_CHECK]
    profile = build_ultra_launch_profile(
        objective=objective_text,
        success_checks=checks,
        route_overrides=overrides,
        budget_hours=max(4.0, budget if budget > 0 else 4.0),
    )
    return {
        "reasoningEffort": "ultra",
        "objective": objective_text,
        "successChecks": checks,
        "routeOverrides": profile["routeOverrides"],
        "mode": "Deep Run",
        "budgetHours": float(profile["budgetHours"]),
        "missionContract": profile["missionContract"],
        "executionTargetPreference": profile["executionTargetPreference"],
        "parallelAgents": profile.get("parallelAgents", 1),
        "mergePolicy": profile.get("mergePolicy", "risk_averse"),
    }


def apply_agent_turn_mode_to_launch(*, turn_mode: object, objective: str, success_checks: list[str] | None, route_overrides: list[dict] | None, mode: str, budget_hours: object) -> dict:

    """Map an agent turn mode onto the real mission launch knobs.



    plan: requires a written plan before edits via objective directive + success check.

    fast: lowers route effort to low and caps an explicitly selected time budget.

    max-context: raises route effort to high, switches to Deep Run, and grows an

    explicitly selected time budget. Turn modes never create a timer by themselves.

    """

    resolved = normalize_agent_turn_mode(turn_mode)

    objective_text = str(objective or '')

    checks = [str(item) for item in success_checks or []]

    overrides = [dict(item) for item in route_overrides or [] if isinstance(item, dict)]

    mission_mode = str(mode or 'Autopilot')

    budget: float | None = None

    if budget_hours is not None and str(budget_hours).strip():

        try:

            parsed_budget = float(budget_hours)

        except (TypeError, ValueError):

            parsed_budget = 0.0

        if parsed_budget > 0:

            budget = parsed_budget

    if resolved == 'plan':

        if PLAN_TURN_MODE_DIRECTIVE not in objective_text:

            objective_text = f'{objective_text}\n\n{PLAN_TURN_MODE_DIRECTIVE}'.strip()

        if PLAN_TURN_MODE_SUCCESS_CHECK not in checks:

            checks = [PLAN_TURN_MODE_SUCCESS_CHECK, *checks]

    elif resolved == 'fast':

        if budget is not None:

            budget = min(budget, 1.0)

        overrides = [{**row, 'effort': 'low'} for row in overrides]

    elif resolved == 'max-context':

        if budget is not None:

            budget = max(budget, 8.0)

        mission_mode = 'Deep Run'

        overrides = [{**row, 'effort': 'high'} for row in overrides]

    result = {'turnMode': resolved, 'objective': objective_text, 'successChecks': checks, 'routeOverrides': overrides, 'mode': mission_mode, 'budgetHours': budget}

    from .proofs_c_missions import check_turn_mode

    check_turn_mode(result, objective, success_checks, route_overrides, mode)

    return result


def normalize_minimax_auth_mode(value: object) -> str:
    normalized = str(value or "none").strip().lower()
    if normalized in {
        "minimax-portal-oauth",
        "minimax-global-oauth",
        "minimax-cn-oauth",
        "oauth",
        "oauth-cn",
        "portal",
        "portal-oauth",
        "minimax_oauth",
    }:
        return "minimax-portal-oauth"
    if normalized in {"minimax_api", "minimax-api", "minimax-global-api", "minimax-cn-api"}:
        return "minimax-api"
    return normalized if normalized in MINIMAX_AUTH_MODES else "none"


def normalize_openai_codex_auth_mode(value: object) -> str:
    normalized = str(value or "none").strip().lower()
    if normalized in {"chatgpt", "chatgpt-portal", "portal", "oauth", "chatgpt-oauth"}:
        return "oauth"
    if normalized in {"api", "api-key", "api_key"}:
        return "api"
    if normalized in {"codex-oauth", "openai-codex-oauth", "chatgpt_oauth"}:
        return "oauth"
    return normalized if normalized in OPENAI_CODEX_AUTH_MODES else "none"


def normalize_sync_direction(value: object) -> str:
    normalized = str(value or "bidirectional").strip().lower().replace("-", "_")
    aliases = {
        "both": "bidirectional",
        "two_way": "bidirectional",
        "auto": "bidirectional",
        "local2nas": "local_to_nas",
        "nas2local": "nas_to_local",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in SYNC_DIRECTIONS else "bidirectional"


def openai_codex_auth_label(mode: str) -> str:
    if mode == "api":
        return "API key"
    if mode == "oauth":
        return "OpenAI Codex OAuth"
    return "not configured"


def minimax_auth_label(mode: str) -> str:
    if mode == "minimax-portal-oauth":
        return "MiniMax broker OAuth"
    if mode == "minimax-api":
        return "API key"
    return "not configured"


def runtime_label(runtime_id: str) -> str:
    normalized = str(runtime_id or "").strip().lower()
    if normalized == "hermes":
        return "Hermes"
    if normalized == "openclaw":
        return "OpenClaw"
    if normalized == "opencode":
        return "OpenCode"
    if normalized in {"opencode-go", "opencodego"}:
        return "OpenCodeGo"
    if normalized:
        return normalized.replace("_", " ").replace("-", " ").title()
    return "Runtime"


def runtime_capture_label(capture_mode: object) -> str:
    normalized = str(capture_mode or "").strip().lower().replace("_", "-")
    if normalized in {"recovered-persisted-session", "persisted-session", "recovered-session"}:
        return "recovered persisted session"
    if normalized in {"fresh-runtime-command", "fresh-command", "runtime-command"}:
        return "fresh runtime command"
    if normalized in {"mission-runtime-output-file", "runtime-output-file", "proof-file"}:
        return "runtime output proof file"
    if normalized:
        return normalized.replace("-", " ")
    return ""


def _latest_minimax_setup_action(setup_history: list[dict]) -> dict:
    latest = {}
    for record in setup_history:
        proposal = record.get("proposal", {})
        args = proposal.get("args", {})
        action_id = args.get("workspaceActionId", "")
        if action_id not in MINIMAX_SETUP_ACTION_IDS:
            continue
        if latest and str(record.get("executed_at", "")) < str(latest.get("executed_at", "")):
            continue
        latest = record
    if not latest:
        return {}
    result = latest.get("result", {})
    return {
        "actionId": latest.get("proposal", {}).get("args", {}).get("workspaceActionId", ""),
        "ok": bool(result.get("ok")),
        "resultSummary": result.get("result_summary", "") or result.get("error", ""),
        "executedAt": latest.get("executed_at", ""),
    }


def _minimax_setup_status_for_workspace(
    workspace: WorkspaceProfile | dict,
    setup_history: list[dict],
    *,
    auth_presence: dict[str, bool],
) -> dict:
    workspace_payload = (
        asdict(workspace) if hasattr(workspace, "__dataclass_fields__") else dict(workspace)
    )
    mode = normalize_minimax_auth_mode(workspace_payload.get("minimax_auth_mode"))
    api_key_present = bool(
        auth_presence.get("minimax", False) or auth_presence.get("minimax-cn", False)
    )
    oauth_present = bool(
        auth_presence.get("minimax-portal", False)
        or auth_presence.get("minimax-oauth", False)
    )
    configured = (mode == "minimax-api" and api_key_present) or (
        mode == "minimax-portal-oauth" and oauth_present
    )
    latest = _latest_minimax_setup_action(setup_history)
    return {
        "authMode": mode,
        "authPath": minimax_auth_label(mode),
        "configured": configured,
        "authPresent": configured,
        "lastActionResult": latest,
        "lastCheckedAt": latest.get("executedAt", "") or workspace_payload.get("updated_at", ""),
    }


def _openai_codex_setup_status_for_workspace(
    workspace: WorkspaceProfile | dict,
    *,
    auth_presence: dict[str, bool],
) -> dict:
    workspace_payload = (
        asdict(workspace) if hasattr(workspace, "__dataclass_fields__") else dict(workspace)
    )
    mode = normalize_openai_codex_auth_mode(
        workspace_payload.get("openai_codex_auth_mode")
    )
    api_key_present = bool(
        auth_presence.get("openai", False) or auth_presence.get("openai-codex", False)
    )
    effective_mode = mode
    configured = False
    oauth_present = bool(auth_presence.get("openai-codex", False))
    if mode == "api":
        configured = api_key_present
    elif mode == "oauth":
        configured = oauth_present
    elif api_key_present:
        effective_mode = "api"
        configured = True
    return {
        "authMode": effective_mode,
        "authPath": openai_codex_auth_label(effective_mode),
        "configured": configured,
        "authPresent": configured,
        "lastCheckedAt": workspace_payload.get("updated_at", ""),
    }


def _latest_autotune_event(activity: list[dict]) -> dict:
    for event in activity:
        if event.get("kind") == "mission.autotune.applied":
            return event
    return {}


def _build_efficiency_autotune_snapshot(
    *,
    harness_lab: dict,
    auto_optimize_enabled: bool,
    activity: list[dict],
) -> dict:
    efficiency = harness_lab.get("efficiency", {})
    session_health = harness_lab.get("sessionHealth", {})
    total_runs = int(efficiency.get("totalRuns", 0) or 0)
    completion_rate = int(efficiency.get("completionRate", 0) or 0)
    approval_pause_rate = int(efficiency.get("approvalPauseRate", 0) or 0)
    stale_heartbeat_count = int(session_health.get("staleHeartbeatCount", 0) or 0)
    eligible = total_runs >= 3
    if not auto_optimize_enabled:
        reason = "Auto-optimize routing is off for this workspace."
    elif not eligible:
        reason = "Not enough local data yet (need at least 3 runs)."
    elif stale_heartbeat_count > 0 or completion_rate < 50:
        reason = "Safety route active because heartbeat is stale or completion is below 50%."
    elif approval_pause_rate > 40:
        reason = "Approval pause rate is high, so Neyvia keeps tiered approvals and reduces delegation."
    elif completion_rate >= 70 and stale_heartbeat_count == 0:
        reason = "Runs look stable, so Neyvia can prefer a more efficient executor route."
    else:
        reason = "Routing is left unchanged until a clearer efficiency signal appears."
    latest_event = _latest_autotune_event(activity)
    return {
        "enabled": bool(auto_optimize_enabled),
        "eligible": eligible,
        "reason": reason,
        "lastAppliedPolicy": (latest_event.get("metadata") or {}).get("policy", ""),
        "lastAppliedAt": latest_event.get("created_at", ""),
    }


class ControlRoomStore(ControlRoomProjectionMixin, ControlRoomDetailMixin):
    def __init__(self, root: Path) -> None:
        self.requested_root = Path(root).expanduser().resolve()
        self.root = resolve_control_room_authority_root(self.requested_root)
        self.control_dir = self.root / ".agent_control"
        self.control_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_path = self.control_dir / "workspaces.json"
        self.missions_path = self.control_dir / "missions.json"
        self.events_path = self.control_dir / "mission_events.jsonl"
        self.lane_control_receipts_path = self.control_dir / "lane_control_receipts.jsonl"
        self.workspace_actions_path = self.control_dir / "workspace_actions.json"
        self.autonomous_workflows_path = self.control_dir / "autonomous_workflows.json"
        self.blocking_metrics_policy_path = self.control_dir / "blocking_metrics_policy.json"
        self.mission_history_receipts_dir = self.control_dir / "mission_history_receipts"

    @_control_checked('replace-lock')

    def _write_json_if_changed(self, path: Path, payload: object) -> None:

        serialized = json.dumps(payload, indent=2)

        if path.exists():

            try:

                if path.read_text(encoding='utf-8') == serialized:

                    return

            except OSError:

                pass

        tmp_path = path.with_name(f'{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp')

        tmp_path.write_text(serialized, encoding='utf-8')

        last_error: OSError | None = None

        for attempt in range(SYNC_COPY_RETRY_ATTEMPTS):

            try:

                os.replace(tmp_path, path)

                last_error = None

                break

            except OSError as exc:

                last_error = exc

                if not _is_transient_replace_lock_error(exc):

                    try:

                        tmp_path.unlink(missing_ok=True)

                    except OSError:

                        pass

                    raise

                if attempt >= SYNC_COPY_RETRY_ATTEMPTS - 1:

                    break

                time.sleep(SYNC_COPY_RETRY_BASE_DELAY_SECONDS * (attempt + 1))

        if last_error is not None:

            try:

                tmp_path.unlink(missing_ok=True)

            except OSError:

                pass

            raise last_error

        self._invalidate_json_cache(path)

        from .proofs_c_missions import check_control_write

        check_control_write(path, payload)

    def _invalidate_snapshot_caches(self) -> None:
        invalidate_onboarding_status_cache(self.root)
        invalidate_runtime_status_cache(self.root)

    @_workspace_state
    @_control_checked('workspaces')

    def load_workspaces(self) -> list[WorkspaceProfile]:

        payload = self._load_json(self.workspaces_path, [])

        workspaces: list[WorkspaceProfile] = []

        for item in payload:

            if not isinstance(item, dict):

                continue

            try:

                workspaces.append(WorkspaceProfile(**item))

            except TypeError:

                continue

        if not workspaces:

            workspaces = [self._default_workspace_profile()]

            self.save_workspaces(workspaces)

            return workspaces

        if self._reanchor_release_workspaces(workspaces):

            self.save_workspaces(workspaces)

        return workspaces

    def save_workspaces(self, workspaces: list[WorkspaceProfile]) -> None:
        self._invalidate_snapshot_caches()
        self._write_json_if_changed(
            self.workspaces_path,
            [asdict(item) for item in workspaces],
        )

    def load_blocking_metrics_policy(self) -> dict:
        payload = self._load_json(self.blocking_metrics_policy_path, {})
        return dict(payload) if isinstance(payload, dict) else {}

    def blocking_metrics_since(self) -> str:
        return str(self.load_blocking_metrics_policy().get("blockingMetricsSince") or "").strip()

    @staticmethod
    def _is_legacy_blocked_mission(mission: Mission, blocking_metrics_since: str) -> bool:
        cutoff = _parse_iso_datetime(blocking_metrics_since)
        if cutoff is None or not _mission_counts_as_hard_blocked(mission):
            return False
        created_at = _parse_iso_datetime(mission.created_at)
        return created_at is None or created_at < cutoff

    @staticmethod
    def _is_legacy_blocked_workflow(record: dict, blocking_metrics_since: str) -> bool:
        cutoff = _parse_iso_datetime(blocking_metrics_since)
        status = str(record.get("status") or "").strip().lower()
        if cutoff is None or status not in {"blocked", "needs_approval", "verification_failed"}:
            return False
        created_at = _parse_iso_datetime(str(record.get("createdAt") or ""))
        return created_at is None or created_at < cutoff

    @_workspace_state
    def load_missions(self, *, include_legacy_blocked: bool = False) -> list[Mission]:
        payload = self._load_json(self.missions_path, [])
        missions: list[Mission] = []
        for item in payload:
            run_budget = _dataclass_from_mapping(MissionRunBudget, item.get("run_budget", {}))
            verification_policy = _dataclass_from_mapping(
                MissionVerificationPolicy,
                item.get("verification_policy", {}),
            )
            escalation_policy = _dataclass_from_mapping(
                ApprovalEscalation,
                item.get("escalation_policy", {}),
            )
            state = _dataclass_from_mapping(MissionStateSnapshot, item.get("state", {}))
            proof = _dataclass_from_mapping(MissionProof, item.get("proof", {}))
            planned_file_scope = [
                str(value).strip()
                for value in item.get("planned_file_scope", [])
                if str(value or "").strip()
            ]
            if not planned_file_scope:
                planned_file_scope = infer_planned_file_scope(
                    item.get("objective", ""),
                    item.get("success_checks", []),
                )
            execution_scope = _dataclass_from_mapping(
                ExecutionScope,
                item.get("execution_scope", {}),
            )
            execution_policy = _dataclass_from_mapping(
                ExecutionPolicy,
                item.get("execution_policy", {"profile_name": item.get("selected_profile", "builder")}),
            )
            code_execution = _dataclass_from_mapping(
                MissionCodeExecutionConfig,
                item.get("code_execution", {}),
            )
            delegated_runtime_sessions = [
                _dataclass_from_mapping(DelegatedRuntimeSession, row)
                for row in item.get("delegated_runtime_sessions", [])
            ]
            missions.append(
                Mission(
                    mission_id=item["mission_id"],
                    workspace_id=item["workspace_id"],
                    runtime_id=item["runtime_id"],
                    objective=item["objective"],
                    success_checks=item.get("success_checks", []),
                    created_at=item.get("created_at", utc_now_iso()),
                    updated_at=item.get("updated_at", utc_now_iso()),
                    title=item.get("title", ""),
                    run_budget=run_budget,
                    verification_policy=verification_policy,
                    escalation_policy=escalation_policy,
                    harness_id=item.get("harness_id", "fluxio_hybrid"),
                    selected_profile=item.get("selected_profile", "builder"),
                    execution_scope=execution_scope,
                    execution_policy=execution_policy,
                    code_execution=code_execution,
                    route_configs=item.get("route_configs", []),
                    routing_decisions=item.get("routing_decisions", []),
                    effective_route_contract=item.get("effective_route_contract", {}),
                    current_plan_revision_id=item.get("current_plan_revision_id"),
                    plan_revisions=item.get("plan_revisions", []),
                    derived_tasks=item.get("derived_tasks", []),
                    improvement_queue=item.get("improvement_queue", []),
                    planned_file_scope=planned_file_scope,
                    skill_usage=item.get("skill_usage", []),
                    learned_skill_events=item.get("learned_skill_events", []),
                    action_history=item.get("action_history", []),
                    delegated_runtime_sessions=delegated_runtime_sessions,
                    tutorial_context=item.get("tutorial_context", {}),
                    planner_loop_status=item.get("planner_loop_status", "idle"),
                    state=state,
                    proof=proof,
                )
            )
        if include_legacy_blocked:
            return missions
        blocking_metrics_since = self.blocking_metrics_since()
        if not blocking_metrics_since:
            return missions
        return [
            mission
            for mission in missions
            if not self._is_legacy_blocked_mission(mission, blocking_metrics_since)
        ]

    def save_missions(self, missions: list[Mission]) -> None:
        self._invalidate_snapshot_caches()
        self._write_json_if_changed(
            self.missions_path,
            [asdict(item) for item in missions],
        )

    def load_autonomous_workflows(self, *, include_legacy_blocked: bool = False) -> list[dict]:
        payload = self._load_json(self.autonomous_workflows_path, [])
        if isinstance(payload, dict):
            payload = payload.get("workflows", [])
        if not isinstance(payload, list):
            return []
        workflows = [dict(item) for item in payload if isinstance(item, dict)]
        if include_legacy_blocked:
            return workflows
        blocking_metrics_since = self.blocking_metrics_since()
        if not blocking_metrics_since:
            return workflows
        return [
            record
            for record in workflows
            if not self._is_legacy_blocked_workflow(record, blocking_metrics_since)
        ]

    def reset_legacy_blocked_missions(self, *, reset_at: str | None = None) -> dict:
        cutoff = _parse_iso_datetime(reset_at or utc_now_iso())
        if cutoff is None:
            raise ValueError("reset_at must be an ISO-8601 timestamp")
        blocking_metrics_since = cutoff.isoformat().replace("+00:00", "Z")
        missions = self.load_missions(include_legacy_blocked=True)
        workflows = self.load_autonomous_workflows(include_legacy_blocked=True)
        removed_missions = [
            mission
            for mission in missions
            if self._is_legacy_blocked_mission(mission, blocking_metrics_since)
        ]
        removed_ids = {mission.mission_id for mission in removed_missions}
        removed_workflows = [
            record
            for record in workflows
            if str(record.get("missionId") or "") in removed_ids
            or self._is_legacy_blocked_workflow(record, blocking_metrics_since)
        ]
        removed_workflow_ids = {
            str(record.get("missionId") or "")
            for record in removed_workflows
            if str(record.get("missionId") or "")
        }
        receipt_id = f"blocked-history-reset-{cutoff.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        self.mission_history_receipts_dir.mkdir(parents=True, exist_ok=True)
        receipt_path = self.mission_history_receipts_dir / f"{receipt_id}.json"
        backup_payload = {
            "schema": "neyvia.blocked_mission_history_reset.v1",
            "receiptId": receipt_id,
            "blockingMetricsSince": blocking_metrics_since,
            "removedMissionCount": len(removed_missions),
            "removedWorkflowCount": len(removed_workflows),
            "removedMissionIds": sorted(removed_ids),
            "missions": [asdict(mission) for mission in removed_missions],
            "autonomousWorkflows": removed_workflows,
        }
        self._write_json_if_changed(receipt_path, backup_payload)
        policy = {
            "schema": "neyvia.blocking_metrics_policy.v1",
            "blockingMetricsSince": blocking_metrics_since,
            "lastResetReceiptId": receipt_id,
            "lastResetReceiptPath": str(receipt_path),
            "removedMissionCount": len(removed_missions),
            "removedWorkflowCount": len(removed_workflows),
        }
        # Persist the watermark before rewriting projections. If the process stops
        # between writes, legacy rows still cannot re-enter live blocking metrics.
        self._write_json_if_changed(self.blocking_metrics_policy_path, policy)
        self.save_missions([
            mission for mission in missions if mission.mission_id not in removed_ids
        ])
        self.save_autonomous_workflows([
            record
            for record in workflows
            if str(record.get("missionId") or "") not in removed_workflow_ids
        ])
        self.append_event(
            MissionEvent(
                mission_id="control_room",
                kind="mission.blocking_history_reset",
                message="Legacy blocked missions were removed from active N-E-Y-V-I-A mission state.",
                metadata={
                    "blockingMetricsSince": blocking_metrics_since,
                    "removedMissionCount": len(removed_missions),
                    "removedWorkflowCount": len(removed_workflows),
                    "receiptId": receipt_id,
                },
            )
        )
        return policy | {
            "ok": True,
            "removedMissionIds": sorted(removed_ids),
        }

    def _delegated_sessions_by_workflow_mission(
        self,
        mission_ids: set[str] | None = None,
    ) -> dict[str, list[DelegatedRuntimeSession]]:
        targets = {str(value).strip() for value in (mission_ids or set()) if str(value).strip()}
        sessions_by_mission: dict[str, list[DelegatedRuntimeSession]] = {}
        seen_by_mission: dict[str, set[str]] = {}
        runtime_sessions_root = self.control_dir / "runtime_sessions"
        if not runtime_sessions_root.is_dir():
            return sessions_by_mission
        for path in sorted(runtime_sessions_root.glob("*.json")):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            mission_id = str(
                payload.get("missionId")
                or payload.get("mission_id")
                or payload.get("parentMissionId")
                or payload.get("parent_mission_id")
                or ""
            ).strip()
            if targets and mission_id not in targets:
                mission_id = next(
                    (candidate for candidate in targets if candidate in text),
                    "",
                )
            if not mission_id or (targets and mission_id not in targets):
                continue
            delegated_id = str(payload.get("delegated_id") or "").strip()
            seen = seen_by_mission.setdefault(mission_id, set())
            if not delegated_id or delegated_id in seen:
                continue
            seen.add(delegated_id)
            sessions_by_mission.setdefault(mission_id, []).append(
                _dataclass_from_mapping(DelegatedRuntimeSession, payload)
            )
        return sessions_by_mission

    def _delegated_sessions_for_workflow_mission(self, mission_id: str) -> list[DelegatedRuntimeSession]:
        normalized_mission_id = str(mission_id or "").strip()
        if not normalized_mission_id:
            return []
        return self._delegated_sessions_by_workflow_mission(
            {normalized_mission_id}
        ).get(normalized_mission_id, [])

    def _mission_from_autonomous_workflow_record(self, mission_id: str) -> Mission | None:
        for record in self.load_autonomous_workflows():
            if str(record.get("missionId") or "").strip() != mission_id:
                continue
            objective = str(record.get("objective") or "").strip()
            if not objective:
                return None
            runtime_summary = record.get("runtimeSummary")
            runtime_summary = runtime_summary if isinstance(runtime_summary, dict) else {}
            run_budget = record.get("runBudget")
            run_budget = run_budget if isinstance(run_budget, dict) else {}
            verification = record.get("verification")
            verification = verification if isinstance(verification, dict) else {}
            risk = record.get("risk")
            risk = risk if isinstance(risk, dict) else {}
            status = str(record.get("status") or "running").strip() or "running"
            remaining_seconds = int(run_budget.get("remainingSeconds") or 0)
            budget_enforced = bool(run_budget.get("enforced", False))
            max_runtime_seconds = int(run_budget.get("maxRuntimeSeconds") or 0)
            delegated_sessions = self._delegated_sessions_for_workflow_mission(mission_id)
            latest_session_id = (
                str(runtime_summary.get("latestSessionId") or "").strip()
                or (delegated_sessions[-1].delegated_id if delegated_sessions else "")
            )
            execution_scope = _dataclass_from_mapping(ExecutionScope, record.get("executionScope", {}))
            execution_policy = _dataclass_from_mapping(
                ExecutionPolicy,
                record.get("executionPolicy", {"profile_name": "builder"}),
            )
            state = MissionStateSnapshot(
                status=status,
                latest_session_id=latest_session_id or None,
                current_cycle_phase=str(record.get("currentPhase") or "execute"),
                planner_loop_status="completed" if status in TERMINAL_MISSION_STATUSES else "running",
                stop_reason=str(risk.get("stopReason") or "") or None,
                execution_scope=asdict(execution_scope),
                delegated_runtime_sessions=[asdict(item) for item in delegated_sessions],
                continuity_state=str(record.get("continuityState") or "workflow_recovered"),
                continuity_detail=str(
                    record.get("continuityDetail")
                    or "Mission row recovered from live autonomous workflow evidence."
                ),
                elapsed_runtime_seconds=max(0, max_runtime_seconds - remaining_seconds),
                remaining_runtime_seconds=remaining_seconds,
                time_budget_status=(
                    str(run_budget.get("status") or status)
                    if budget_enforced
                    else "unlimited"
                ),
                current_runtime_lane=str(runtime_summary.get("currentRuntimeLane") or ""),
                last_runtime_event=str(runtime_summary.get("lastRuntimeEvent") or "") or None,
                last_verification_result=str(verification.get("lastResult") or ""),
                last_verification_summary=str(verification.get("lastSummary") or ""),
                verification_failures=[
                    str(item)
                    for item in verification.get("verificationFailures", [])
                    if str(item or "").strip()
                ],
                blocker_classification=dict(risk.get("blockerClassification") or {}),
            )
            proof = MissionProof(
                summary=str(
                    record.get("lastProofSummary")
                    or "Mission row recovered from live autonomous workflow evidence; original action history is unavailable."
                ),
                changed_files=[
                    str(item)
                    for item in record.get("changedFiles", [])
                    if str(item or "").strip()
                ],
                artifacts=[
                    item
                    for item in record.get("evidenceFiles", [])
                    if isinstance(item, dict)
                ],
                passed_checks=[
                    str(item)
                    for item in verification.get("passedChecks", [])
                    if str(item or "").strip()
                ],
                failed_checks=[
                    str(item)
                    for item in verification.get("failedChecks", [])
                    if str(item or "").strip()
                ],
                pending_approvals=[
                    str(item)
                    for item in (record.get("approvalSummary") or {}).get("pending", [])
                    if str(item or "").strip()
                ],
                blocked_by=[
                    str(item)
                    for item in risk.get("blockers", [])
                    if str(item or "").strip()
                ],
            )
            return Mission(
                mission_id=mission_id,
                workspace_id=str(record.get("workspaceId") or "workspace_primary"),
                runtime_id=str(record.get("runtimeId") or "hermes"),
                objective=objective,
                success_checks=[
                    str(item)
                    for item in record.get("successChecks", [])
                    if str(item or "").strip()
                ],
                created_at=str(record.get("createdAt") or utc_now_iso()),
                updated_at=str(record.get("updatedAt") or utc_now_iso()),
                title=str(record.get("title") or _mission_title(objective)),
                run_budget=MissionRunBudget(
                    mode=str(run_budget.get("mode") or record.get("mode") or "Autopilot"),
                    max_runtime_seconds=max_runtime_seconds,
                    focus_window_hours=(
                        max(1, round(max_runtime_seconds / 3600))
                        if budget_enforced
                        else 0
                    ),
                    run_until_behavior=str(run_budget.get("runUntilBehavior") or "pause_on_failure"),
                    deadline_at=run_budget.get("deadlineAt") or None,
                    enforced=budget_enforced,
                ),
                verification_policy=MissionVerificationPolicy(
                    commands=[
                        str(item)
                        for item in verification.get("commands", [])
                        if str(item or "").strip()
                    ],
                    pause_on_failure=True,
                ),
                harness_id=str(record.get("harnessId") or "fluxio_hybrid"),
                selected_profile=str(record.get("profile") or "builder"),
                execution_scope=execution_scope,
                execution_policy=execution_policy,
                delegated_runtime_sessions=delegated_sessions,
                effective_route_contract=dict(record.get("routeContract") or {}),
                planned_file_scope=infer_planned_file_scope(objective, []),
                state=state,
                proof=proof,
                tutorial_context={
                    "profile": str(record.get("profile") or "builder"),
                    "preferredHarness": str(record.get("harnessId") or "fluxio_hybrid"),
                    "recoveredFromAutonomousWorkflow": True,
                },
            )
        return None

    def save_autonomous_workflows(self, workflows: list[dict]) -> None:
        workflows = sorted(
            workflows,
            key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""),
            reverse=True,
        )
        self._write_json_if_changed(
            self.autonomous_workflows_path,
            {
                "schemaVersion": "autonomous-workflows.v1",
                "updatedAt": utc_now_iso(),
                "workflows": workflows[:200],
            },
        )

    def record_autonomous_workflow(self, mission: Mission) -> dict:
        workflows = self.load_autonomous_workflows()
        previous = next(
            (item for item in workflows if item.get("missionId") == mission.mission_id),
            {},
        )
        record = _build_autonomous_workflow_record(
            mission,
            root=self.root,
            event_count=self._mission_event_count(mission.mission_id),
            previous=previous,
        )
        next_workflows = [
            item for item in workflows if item.get("missionId") != mission.mission_id
        ]
        next_workflows.append(record)
        self.save_autonomous_workflows(next_workflows)
        return record

    def reconcile_autonomous_workflows(self, missions: list[Mission]) -> dict:
        workflows = self.load_autonomous_workflows()
        by_mission = {
            str(item.get("missionId") or ""): dict(item)
            for item in workflows
            if item.get("missionId")
        }
        next_workflows: list[dict] = []
        mission_ids = {mission.mission_id for mission in missions}
        for mission in missions:
            next_workflows.append(
                _build_autonomous_workflow_record(
                    mission,
                    root=self.root,
                    event_count=self._mission_event_count(mission.mission_id),
                    previous=by_mission.get(mission.mission_id, {}),
                )
            )
        for record in workflows:
            mission_id = str(record.get("missionId") or "")
            if mission_id and mission_id not in mission_ids:
                archived = dict(record)
                archived["archived"] = True
                archived.setdefault("archivedReason", "mission_not_in_current_store")
                next_workflows.append(archived)
        self.save_autonomous_workflows(next_workflows)
        return _build_autonomous_workflow_records_snapshot(next_workflows)

    def _mission_event_count(self, mission_id: str) -> int:
        if not self.events_path.exists():
            return 0
        count = 0
        try:
            with self.events_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if str(payload.get("mission_id") or payload.get("missionId") or "") == mission_id:
                        count += 1
        except OSError:
            return 0
        return count

    @_serialize_workspace_update
    def upsert_workspace(
        self,
        name: str,
        root_path: str,
        default_runtime: str,
        user_profile: str = "builder",
        preferred_harness: str = "fluxio_hybrid",
        routing_strategy: str = "profile_default",
        route_overrides: list[dict] | None = None,
        auto_optimize_routing: bool | None = None,
        openai_codex_auth_mode: str | None = None,
        minimax_auth_mode: str | None = None,
        commit_message_style: str = "scoped",
        execution_target_preference: str = "profile_default",
        local_project_path: str = "",
        nas_project_path: str = "",
        sync_mode: str = "manual",
        sync_direction: str = "bidirectional",
        sync_conflict_policy: str = "keep_newer_and_log",
        auto_sync_to_nas: bool | None = None,
        workspace_id: str | None = None,
    ) -> WorkspaceProfile:
        workspaces = self.load_workspaces()
        clean_local_project_path = str(local_project_path or "").strip()
        clean_nas_project_path = str(nas_project_path or "").strip()
        clean_sync_mode = str(sync_mode or "manual").strip().lower()
        clean_sync_direction = normalize_sync_direction(sync_direction)
        clean_sync_conflict_policy = str(sync_conflict_policy or "keep_newer_and_log").strip().lower()
        sync_enabled = bool(auto_sync_to_nas)
        effective_root_path = clean_nas_project_path if sync_enabled and clean_nas_project_path else root_path
        workspace_root = Path(effective_root_path).resolve()
        sync_status: dict[str, object] = {}
        if sync_enabled and clean_nas_project_path:
            local_root = (
                Path(clean_local_project_path).expanduser().resolve()
                if clean_local_project_path
                else None
            )
            sync_status = _sync_local_and_nas_projects(
                local_root=local_root,
                nas_root=workspace_root,
                sync_direction=clean_sync_direction,
                conflict_policy=clean_sync_conflict_policy,
            )
            # If no local root is provided, keep the existing one-way behavior from
            # the selected root path to NAS for backwards compatibility.
            if (
                not sync_status
                and clean_local_project_path == ""
                and root_path
                and Path(root_path).expanduser().resolve() != workspace_root
            ):
                sync_status = _sync_project_tree(
                    Path(root_path).expanduser().resolve(),
                    workspace_root,
                    conflict_policy=clean_sync_conflict_policy,
                )
        now = utc_now_iso()
        normalized_route_overrides = normalize_route_overrides(
            route_overrides or [],
            canonicalize_models=False,
        )
        normalized_openai_codex_auth_mode = normalize_openai_codex_auth_mode(
            openai_codex_auth_mode
        )
        normalized_minimax_auth_mode = normalize_minimax_auth_mode(minimax_auth_mode)
        for item in workspaces:
            if item.workspace_id == workspace_id or (
                workspace_id is None and Path(item.root_path).resolve() == workspace_root
            ):
                item.name = name
                item.root_path = str(workspace_root)
                item.default_runtime = default_runtime
                item.user_profile = user_profile or item.user_profile
                item.preferred_harness = preferred_harness or item.preferred_harness
                item.routing_strategy = routing_strategy or item.routing_strategy
                item.route_overrides = (
                    normalized_route_overrides
                    if route_overrides is not None
                    else item.route_overrides
                )
                if auto_optimize_routing is not None:
                    item.auto_optimize_routing = bool(auto_optimize_routing)
                if openai_codex_auth_mode is not None:
                    item.openai_codex_auth_mode = normalized_openai_codex_auth_mode
                if minimax_auth_mode is not None:
                    item.minimax_auth_mode = normalized_minimax_auth_mode
                item.commit_message_style = (
                    commit_message_style or item.commit_message_style
                )
                item.execution_target_preference = (
                    execution_target_preference or item.execution_target_preference
                )
                item.local_project_path = clean_local_project_path or item.local_project_path
                item.nas_project_path = clean_nas_project_path or item.nas_project_path
                item.sync_mode = clean_sync_mode or item.sync_mode
                item.sync_direction = clean_sync_direction or item.sync_direction
                item.sync_conflict_policy = (
                    clean_sync_conflict_policy or item.sync_conflict_policy
                )
                if auto_sync_to_nas is not None:
                    item.auto_sync_to_nas = sync_enabled
                item.goals = [
                    entry
                    for entry in item.goals
                    if not str(entry).startswith("sync_status:")
                ]
                if sync_status:
                    item.goals.append(f"sync_status:{json.dumps(sync_status, sort_keys=True)}")
                item.workspace_type = detect_workspace_type(workspace_root)
                item.updated_at = now
                self.save_workspaces(workspaces)
                return item

        workspace = WorkspaceProfile(
            workspace_id=workspace_id or f"workspace_{uuid.uuid4().hex[:8]}",
            name=name,
            root_path=str(workspace_root),
            default_runtime=default_runtime,
            workspace_type=detect_workspace_type(workspace_root),
            user_profile=user_profile or "builder",
            preferred_harness=preferred_harness or "fluxio_hybrid",
            routing_strategy=routing_strategy or "profile_default",
            route_overrides=normalized_route_overrides,
            auto_optimize_routing=bool(auto_optimize_routing),
            openai_codex_auth_mode=normalized_openai_codex_auth_mode,
            minimax_auth_mode=normalized_minimax_auth_mode,
            commit_message_style=commit_message_style or "scoped",
            execution_target_preference=execution_target_preference or "profile_default",
            local_project_path=clean_local_project_path,
            nas_project_path=clean_nas_project_path,
            sync_mode=clean_sync_mode,
            sync_direction=clean_sync_direction,
            sync_conflict_policy=clean_sync_conflict_policy,
            auto_sync_to_nas=sync_enabled,
            goals=[f"sync_status:{json.dumps(sync_status, sort_keys=True)}"] if sync_status else [],
            updated_at=now,
        )
        workspaces.append(workspace)
        self.save_workspaces(workspaces)
        return workspace

    @_workspace_state
    @_control_checked('delete')

    def delete_workspace(self, workspace_id: str) -> tuple[WorkspaceProfile, int]:

        workspaces = self.load_workspaces()

        target = next((item for item in workspaces if item.workspace_id == workspace_id), None)

        if target is None:

            raise ValueError(f'Unknown workspace id: {workspace_id}')

        if len(workspaces) <= 1:

            raise ValueError('Cannot delete the last workspace. Add another workspace first.')

        remaining_workspaces = [item for item in workspaces if item.workspace_id != workspace_id]

        from .mission_control_workspace_deletion import begin, complete
        admitted_missions = self.load_missions(include_legacy_blocked=True)
        begin(self, workspace_id, sum(item.workspace_id == workspace_id for item in admitted_missions))

        self.save_workspaces(remaining_workspaces)

        missions = admitted_missions

        removed_missions = [item for item in missions if item.workspace_id == workspace_id]

        remaining_missions = [item for item in missions if item.workspace_id != workspace_id]

        self._rebalance_workspace_queue_in_place(remaining_missions)

        self.save_missions(remaining_missions)

        histories = self.load_workspace_actions()

        if workspace_id in histories:

            histories.pop(workspace_id, None)

            self._write_json_if_changed(self.workspace_actions_path, histories)

        complete(self)

        return (target, len(removed_missions))

    def create_mission(
        self,
        workspace_id: str,
        runtime_id: str,
        objective: str,
        success_checks: list[str],
        mode: str,
        verification_commands: list[str],
        max_runtime_seconds: int,
        selected_profile: str = "builder",
        escalation_destination: str = "",
        run_until_behavior: str | None = None,
        deadline_at: str | None = None,
        runtime_budget_enforced: bool | None = None,
        harness_id: str = "fluxio_hybrid",
        code_execution_enabled: bool = False,
        code_execution_memory: str = "4g",
        code_execution_container_id: str = "",
        code_execution_required: bool = False,
        route_overrides: list[dict] | None = None,
    ) -> Mission:
        missions = self.load_missions()
        self._rebalance_workspace_queue_in_place(missions, workspace_id)
        blocking_mission = self._active_workspace_mission(workspace_id, missions)
        queue_position = 0
        queue_reason = ""
        blocking_mission_id = None
        summary = "Mission created and waiting for first runtime cycle."
        if blocking_mission is not None:
            queue_position = (
                len(
                    [
                        item
                        for item in missions
                        if item.workspace_id == workspace_id
                        and not _mission_releases_workspace_slot(item)
                        and item.state.queue_position > 0
                    ]
                )
                + 1
            )
            blocking_mission_id = blocking_mission.mission_id
            queue_reason = (
                f"Waiting for mission '{blocking_mission.title or blocking_mission.objective or blocking_mission.mission_id}' "
                "to leave the active slot for this workspace."
            )
            summary = queue_reason
        mission_id = f"mission_{uuid.uuid4().hex[:10]}"
        now = utc_now_iso()
        clean_max_runtime_seconds = max(0, int(max_runtime_seconds or 0))
        budget_enforced = (
            bool(clean_max_runtime_seconds or deadline_at)
            if runtime_budget_enforced is None
            else bool(runtime_budget_enforced)
        )
        if not budget_enforced:
            clean_max_runtime_seconds = 0
            deadline_at = None
        mission = Mission(
            mission_id=mission_id,
            workspace_id=workspace_id,
            runtime_id=runtime_id,
            objective=objective,
            success_checks=success_checks,
            title=_mission_title(objective),
            created_at=now,
            updated_at=now,
            run_budget=MissionRunBudget(
                mode=mode,
                max_runtime_seconds=clean_max_runtime_seconds,
                focus_window_hours=(
                    max(1, round(clean_max_runtime_seconds / 3600))
                    if budget_enforced
                    else 0
                ),
                run_until_behavior=run_until_behavior or "pause_on_failure",
                deadline_at=deadline_at or None,
                enforced=budget_enforced,
            ),
            verification_policy=MissionVerificationPolicy(
                commands=verification_commands,
                pause_on_failure=(run_until_behavior or "pause_on_failure") != "continue_until_blocked",
            ),
            escalation_policy=ApprovalEscalation(
                channel="telegram",
                enabled=bool(escalation_destination),
                destination=escalation_destination,
                triggers=[
                    "blocked approval",
                    "missing setup step",
                    "verification failure",
                    "completion summary",
                ],
            ),
            harness_id=harness_id or "fluxio_hybrid",
            selected_profile=selected_profile,
            execution_scope=ExecutionScope(
                requested="isolated",
                strategy="direct",
                workspace_root="",
                execution_root="",
                status="pending",
                detail="Execution scope will be resolved during the first harness cycle.",
            ),
            execution_policy=ExecutionPolicy(
                profile_name=selected_profile,
            ),
            code_execution=MissionCodeExecutionConfig(
                enabled=bool(code_execution_enabled),
                memory_limit=code_execution_memory or "4g",
                container_id=str(code_execution_container_id or "").strip(),
                required=bool(code_execution_required),
            ),
            route_configs=normalize_route_overrides(route_overrides or []),
            planned_file_scope=infer_planned_file_scope(objective, success_checks),
            state=MissionStateSnapshot(
                status="queued",
                queue_position=queue_position,
                blocking_mission_id=blocking_mission_id,
                queue_reason=queue_reason,
                time_budget_status="pending" if budget_enforced else "unlimited",
                code_execution={
                    "enabled": bool(code_execution_enabled),
                    "memory_limit": code_execution_memory or "4g",
                    "container_id": str(code_execution_container_id or "").strip(),
                    "required": bool(code_execution_required),
                    "artifacts": [],
                },
            ),
            tutorial_context={
                "profile": selected_profile,
                "preferredHarness": harness_id or "fluxio_hybrid",
            },
            proof=MissionProof(summary=summary),
        )
        missions.append(mission)
        self._rebalance_workspace_queue_in_place(missions, workspace_id)
        self.save_missions(missions)
        self.append_event(
            MissionEvent(
                mission_id=mission_id,
                kind="mission.queued" if queue_position else "mission.created",
                message=(
                    f"Mission queued behind {blocking_mission_id} for workspace collision avoidance."
                    if queue_position
                    else f"Mission created for runtime {runtime_id}."
                ),
                metadata={
                    "workspaceId": workspace_id,
                    "mode": mode,
                    "queuePosition": queue_position,
                    "blockingMissionId": blocking_mission_id,
                    "runtimeBudgetEnforced": budget_enforced,
                },
            )
        )
        self.record_autonomous_workflow(mission)
        return mission

    def update_mission(self, mission: Mission) -> Mission:
        missions = self.load_missions()
        updated = mission
        updated.updated_at = utc_now_iso()
        for index, item in enumerate(missions):
            if item.mission_id == mission.mission_id:
                missions[index] = updated
                self.save_missions(missions)
                self.record_autonomous_workflow(updated)
                return updated
        missions.append(updated)
        self.save_missions(missions)
        self.record_autonomous_workflow(updated)
        return updated

    def get_workspace(self, workspace_id: str) -> WorkspaceProfile | None:
        for item in self.load_workspaces():
            if item.workspace_id == workspace_id:
                return item
        return None

    def get_mission(self, mission_id: str) -> Mission | None:
        for item in self.load_missions():
            if item.mission_id == mission_id:
                return item
        return self._mission_from_autonomous_workflow_record(mission_id)

    def rebalance_mission_queue(
        self,
        workspace_id: str | None = None,
    ) -> list[Mission]:
        missions = self.load_missions()
        self._rebalance_workspace_queue_in_place(missions, workspace_id)
        if missions:
            self.save_missions(missions)
        return missions

    def append_event(self, event: MissionEvent) -> None:
        self._rotate_events_if_needed()
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event), ensure_ascii=True) + "\n")

    def append_lane_control_receipt(self, receipt: dict) -> None:
        if not isinstance(receipt, dict):
            return
        self.control_dir.mkdir(parents=True, exist_ok=True)
        with self.lane_control_receipts_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=True) + "\n")

    def lane_control_receipts_for_mission(self, mission_id: str, *, limit: int = 20) -> list[dict]:
        if not self.lane_control_receipts_path.exists():
            return []
        receipts: list[dict] = []
        lines = _read_text_tail_lines(
            self.lane_control_receipts_path,
            limit=max(100, int(limit) * 5),
        )
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            if str(item.get("schema") or "") != "fluxio.lane_control_receipt.v1":
                continue
            if str(item.get("missionId") or item.get("mission_id") or "") != str(mission_id):
                continue
            receipts.append(item)
        return receipts[-limit:]

    def attach_lane_control_receipts(self, mission: Mission, *, limit: int = 20) -> Mission:
        ledger_receipts = self.lane_control_receipts_for_mission(
            mission.mission_id,
            limit=limit,
        )
        state_receipts = [
            item
            for item in (mission.state.lane_control_receipts or [])
            if isinstance(item, dict)
        ]
        by_id: dict[str, dict] = {}
        for item in [*state_receipts, *ledger_receipts]:
            receipt_id = str(item.get("receiptId") or item.get("receipt_id") or "")
            if receipt_id:
                by_id[receipt_id] = item
        mission.state.lane_control_receipts = sorted(
            by_id.values(),
            key=lambda item: str(item.get("generatedAt") or item.get("at") or ""),
        )[-limit:]
        return mission

    @_control_checked('events')

    def recent_events(self, limit: int=40) -> list[dict]:

        if not self.events_path.exists():

            return []

        lines = _read_text_tail_lines(self.events_path, limit=max(0, int(limit)))

        events: list[dict] = []

        for line in reversed(lines):

            try:

                events.append(json.loads(line))

            except json.JSONDecodeError:

                continue

        return events

    def read_mission_events_since(
        self,
        mission_id: str,
        *,
        cursor: int | None = None,
        limit: int = 200,
    ) -> dict:
        """Incremental tail of the append-only mission event log.

        Builder and Agent Live share this: instead of re-reading a whole
        timeline on every poll, a caller passes back the ``cursor`` (a byte
        offset into the JSONL log) it received last time and gets only what was
        appended since. Rotation shrinks the file, which is detected here and
        answered with a full reload rather than a silent gap.
        """

        mission = str(mission_id or "").strip()
        if not mission:
            raise ValueError("missionId is required")
        max_items = max(1, int(limit or 200))
        if not self.events_path.exists():
            return {
                "schema": "neyvia.mission.events.delta.v1",
                "missionId": mission,
                "events": [],
                "cursor": 0,
                "reset": False,
                "hasMore": False,
            }

        try:
            size = self.events_path.stat().st_size
        except OSError:
            size = 0

        start = 0
        reset = True
        if cursor is not None:
            try:
                requested = max(0, int(cursor))
            except (TypeError, ValueError):
                requested = 0
            # A cursor past the end means the log rotated: reload from the tail.
            if requested <= size:
                start = requested
                reset = False

        events: list[dict] = []
        next_cursor = size
        if reset:
            # First read for this mission: use the bounded tail, not the whole log.
            for event in reversed(self.recent_events(limit=max(max_items * 8, 600))):
                if str(event.get("mission_id") or event.get("missionId") or "") == mission:
                    events.append(event)
            events = events[-max_items:]
        else:
            next_cursor = start
            try:
                # Byte offsets, so the log is opened binary and decoded per line.
                # (Text-mode ``tell()`` is disabled once iteration starts.)
                with self.events_path.open("rb") as handle:
                    handle.seek(start)
                    while True:
                        raw = handle.readline()
                        if not raw:
                            break
                        if not raw.endswith(b"\n"):
                            # Partial trailing line: a writer is mid-append.
                            # Stop before it so the next cursor re-reads it whole.
                            break
                        line = raw.decode("utf-8", errors="ignore").strip()
                        next_cursor = handle.tell()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if str(event.get("mission_id") or event.get("missionId") or "") == mission:
                            events.append(event)
            except OSError:
                next_cursor = start

        has_more = len(events) > max_items
        return {
            "schema": "neyvia.mission.events.delta.v1",
            "missionId": mission,
            "events": events[-max_items:] if has_more else events,
            "cursor": next_cursor,
            "reset": reset,
            "hasMore": has_more,
        }

    def _rotate_events_if_needed(self) -> None:
        if not self.events_path.exists():
            return
        max_bytes = max(
            int(os.environ.get("SYNTELOS_MISSION_EVENTS_MAX_BYTES", str(50 * 1024 * 1024))),
            1024 * 1024,
        )
        try:
            if self.events_path.stat().st_size <= max_bytes:
                return
        except OSError:
            return
        keep_lines = max(
            int(os.environ.get("SYNTELOS_MISSION_EVENTS_KEEP_LINES", "5000")),
            100,
        )
        backups_dir = self.control_dir / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        rotated_path = backups_dir / (
            f"mission_events-rotated-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
        )
        try:
            self.events_path.replace(rotated_path)
        except OSError:
            return
        tail: deque[str] = deque(maxlen=keep_lines)
        try:
            with rotated_path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    if line.strip():
                        tail.append(line)
            with self.events_path.open("w", encoding="utf-8") as handle:
                handle.writelines(tail)
        except OSError:
            self.events_path.touch(exist_ok=True)

    @_workspace_state
    def load_workspace_actions(self) -> dict[str, list[dict]]:
        payload = self._load_json(self.workspace_actions_path, {})
        if not isinstance(payload, dict):
            return {}
        histories: dict[str, list[dict]] = {}
        for key, value in payload.items():
            if isinstance(value, list):
                histories[str(key)] = value
        return histories

    def append_workspace_action(
        self,
        history_key: str,
        record: dict,
        limit: int = 24,
    ) -> dict:
        if history_key == "__setup__":
            self._invalidate_snapshot_caches()
        histories = self.load_workspace_actions()
        entries = list(histories.get(history_key, []))
        entries.append(record)
        histories[history_key] = entries[-max(1, limit) :]
        self.workspace_actions_path.write_text(
            json.dumps(histories, indent=2),
            encoding="utf-8",
        )
        return record

    def build_snapshot(self) -> dict:

        from .app_capability_standard import build_connected_apps_snapshot

        workspaces = self.load_workspaces()

        missions = self.load_missions()

        if os.environ.get('FLUXIO_CONTROL_ROOM_FAST') == '1':

            return self._build_fast_snapshot(workspaces, missions)

        workspace_action_history = self.load_workspace_actions()

        setup_history = workspace_action_history.get('__setup__', [])

        runtime_statuses = detect_runtime_statuses(self.root)

        runtime_lookup = {item.runtime_id: asdict(item) for item in runtime_statuses}

        profiles = ProfileRegistry(self.root / 'config' / 'profiles.json')

        skill_library = SkillLibrary(root=self.root, registry=SkillRegistry(self.root / 'config' / 'skills.json'))

        onboarding = detect_onboarding_status(self.root)

        setup_health = onboarding.get('setupHealth', {})

        setup_health['actionHistory'] = workspace_action_history.get('__setup__', [])

        guidance = build_guidance_snapshot(self.root, onboarding=onboarding)

        runtime_supervisor = DelegatedRuntimeSupervisor(self.root)

        connected_apps_snapshot = build_connected_apps_snapshot(self.root)

        harness_lab_snapshot = build_harness_lab_snapshot(self.root)

        activity = self.recent_events()

        provider_auth_presence = _provider_auth_presence_from_env()

        workspace_lookup = {item.workspace_id: item for item in workspaces}

        workspace_cards = []

        recommended_skill_pack_objects = []

        for workspace in workspaces:

            runtime_id = workspace.default_runtime

            profile = profiles.resolve(workspace.user_profile, Path(workspace.root_path))

            profile_parameters = _profile_parameter_snapshot(workspace.user_profile, profile)

            git_snapshot = _inspect_workspace_git(Path(workspace.root_path), commit_message_style=workspace.commit_message_style)

            validation_actions = _build_validation_actions(Path(workspace.root_path))

            verification_commands = detect_default_verification_commands(Path(workspace.root_path))

            skill_recommendations = [asdict(item) for item in recommend_skills(workspace.workspace_type, workspace.default_runtime)]

            integration_recommendations = [asdict(item) for item in recommend_integrations(workspace.workspace_type, workspace.default_runtime)]

            recommended_skill_packs = SkillLibrary.recommended_packs_from_skills(skill_recommendations)

            recommended_skill_pack_objects.extend(recommended_skill_packs)

            workspace_cards.append({**asdict(workspace), 'openaiCodexSetupStatus': _openai_codex_setup_status_for_workspace(workspace, auth_presence=provider_auth_presence), 'minimaxSetupStatus': _minimax_setup_status_for_workspace(workspace, setup_history, auth_presence=provider_auth_presence), 'runtimeStatus': runtime_lookup.get(runtime_id), 'gitSnapshot': git_snapshot, 'gitActions': _build_git_actions(git_snapshot, profile_parameters), 'validationActions': validation_actions, 'verificationCommands': verification_commands, 'workspaceActionHistory': workspace_action_history.get(workspace.workspace_id, []), 'profileParameters': profile_parameters, 'skillRecommendations': skill_recommendations, 'integrationRecommendations': integration_recommendations, 'recommendedSkillPacks': [asdict(item) for item in recommended_skill_packs], 'serviceManagement': _build_workspace_service_management(setup_health=setup_health, runtime_status=runtime_lookup.get(runtime_id), integration_recommendations=integration_recommendations, connected_apps=connected_apps_snapshot.get('connectedSessions', []))})

        latest_runtime_cycles = _latest_runtime_cycles_by_mission(self.events_path)

        mission_records_changed = False

        for mission in missions:

            before_runtime_signature = _mission_runtime_persistence_signature(mission)

            if _reconcile_mission_from_runtime_cycle(mission, latest_runtime_cycles.get(mission.mission_id), root=self.root, workspace=workspace_lookup.get(mission.workspace_id)):

                mission_records_changed = True

            _sync_execution_scope_snapshot(mission)

            workspace = workspace_lookup.get(mission.workspace_id)

            discovered_sessions = _discover_related_delegated_runtime_sessions(mission, roots=[self.root, Path(workspace.root_path) if workspace and workspace.root_path else None], runtime_supervisor=runtime_supervisor)

            if discovered_sessions:

                mission.delegated_runtime_sessions = [*mission.delegated_runtime_sessions, *discovered_sessions]

                mission_records_changed = True

            refreshed_sessions = []

            for session in mission.delegated_runtime_sessions:

                refreshed = _refresh_delegated_runtime_session_for_summary(runtime_supervisor, session)

                refreshed_sessions.append(refreshed)

            visible_refreshed_sessions = [item for item in refreshed_sessions if not _is_low_signal_stopped_session(item)]

            if len(visible_refreshed_sessions) != len(refreshed_sessions):

                mission_records_changed = True

            refreshed_sessions = sorted(visible_refreshed_sessions, key=_delegated_runtime_session_order_key)

            mission.delegated_runtime_sessions = refreshed_sessions

            mission.action_history = normalize_action_history(mission.action_history)

            mission.state.delegated_runtime_sessions = [asdict(item) for item in refreshed_sessions]

            refresh_mission_runtime_state(mission, refreshed_sessions)

            if _maybe_send_approval_receipt(mission, self.root):

                mission_records_changed = True

            mission.state.provider_runtime_truth = _provider_truth_for_mission(mission, auth_presence=provider_auth_presence, workspace=workspace_lookup.get(mission.workspace_id))

            if _reconcile_mission_route_policy(mission, workspace_lookup.get(mission.workspace_id)):

                mission_records_changed = True

            sync_mission_state_snapshot(mission)

            if _mission_runtime_persistence_signature(mission) != before_runtime_signature:

                mission_records_changed = True

        before_queue_signature = _mission_queue_persistence_signature(missions)

        self._rebalance_workspace_queue_in_place(missions)

        if _mission_queue_persistence_signature(missions) != before_queue_signature:

            mission_records_changed = True

        if mission_records_changed:

            self.save_missions(missions)

        missions_payload = []

        for item in missions:

            self.attach_lane_control_receipts(item)

            mission_payload = asdict(item)

            mission_payload['missionLoop'] = build_mission_loop_snapshot(item)

            mission_payload['plannedScopeArtifacts'] = build_planned_scope_artifacts(root=self.root, mission=item, workspace=workspace_lookup.get(item.workspace_id))

            mission_payload['effectiveRouteContract'] = item.effective_route_contract if item.effective_route_contract else _effective_route_contract_for_mission(item)

            mission_payload['providerTruth'] = dict(item.state.provider_runtime_truth or {})

            mission_payload['providerCapabilities'] = _provider_capability_contract_for_mission(item)

            missions_payload.append(mission_payload)

        recommended_skill_packs = list({item.pack_id: item for item in recommended_skill_pack_objects}.values())

        skill_catalog = skill_library.build_catalog(recommended_packs=recommended_skill_packs)

        workspace_payload = []

        for workspace in workspace_cards:

            ownership = _control_workspace_queue_projection(workspace['workspace_id'], missions, include_terminal_queue=True)

            service_management = workspace.get('serviceManagement', [])

            workspace_payload.append({**workspace, **{key: ownership[key] for key in ('activeMissionId', 'activeMissionTitle', 'queuedMissionIds', 'queuedMissionCount')}, 'serviceManagementSummary': _service_management_summary(service_management)})

        inbox_items = [{'missionId': item.mission_id, 'channel': item.escalation_policy.channel, 'destination': item.escalation_policy.destination, 'ready': item.escalation_policy.delivery_ready, 'pendingCount': item.escalation_policy.pending_count, 'previewMessage': build_escalation_preview(item)} for item in missions if item.state.status in {'blocked', 'needs_approval', 'verification_failed', 'completed'}]

        active_workspace_payload = workspace_payload[0] if workspace_payload else {}

        active_workspace_id = str(active_workspace_payload.get('workspace_id', '') or '')

        active_mission = self._active_workspace_mission(active_workspace_id, missions)

        active_provider_truth = dict(active_mission.state.provider_runtime_truth or {}) if active_mission is not None else {}

        active_route = dict(active_provider_truth.get('activeRoute', {})) if isinstance(active_provider_truth.get('activeRoute'), dict) else {}

        provider_status = {}

        for provider_id in ('openai', 'anthropic', 'openrouter'):

            aliases = {'openai', 'openai-codex'} if provider_id == 'openai' else {provider_id}

            last_success = active_provider_truth.get('lastSuccessfulCall', {}) if isinstance(active_provider_truth.get('lastSuccessfulCall'), dict) else {}

            last_failure = active_provider_truth.get('lastFailure', {}) if isinstance(active_provider_truth.get('lastFailure'), dict) else {}

            openai_status = dict(active_workspace_payload.get('openaiCodexSetupStatus', {})) if provider_id == 'openai' and isinstance(active_workspace_payload.get('openaiCodexSetupStatus'), dict) else {}

            auth_present = bool(openai_status.get('authPresent', False)) if provider_id == 'openai' else bool(provider_auth_presence.get(provider_id, False))

            provider_status[provider_id] = {'providerId': provider_id, 'authPresent': auth_present, 'configured': auth_present, 'authMode': str(openai_status.get('authMode', '')).strip().lower() if provider_id == 'openai' else '', 'authPath': str(openai_status.get('authPath', '')).strip() if provider_id == 'openai' else '', 'activeRoute': active_route if str(active_route.get('provider', '')).strip().lower() in aliases else {}, 'lastSuccessfulModelCall': last_success if str(last_success.get('provider', '')).strip().lower() in aliases else {}, 'lastProviderFailure': last_failure if str(last_failure.get('provider', '')).strip().lower() in aliases else {}, 'lastCheckedAt': utc_now_iso()}

        provider_setup_status = {**provider_status, 'minimax': active_workspace_payload.get('minimaxSetupStatus') or _minimax_setup_status_for_workspace(self._default_workspace_profile(), setup_history, auth_presence=provider_auth_presence)}

        efficiency_autotune = _build_efficiency_autotune_snapshot(harness_lab=harness_lab_snapshot, auto_optimize_enabled=bool(active_workspace_payload.get('auto_optimize_routing', False)), activity=activity)

        release_readiness = build_release_readiness_snapshot(self.root, onboarding=onboarding, setup_health=setup_health, harness_lab=harness_lab_snapshot)

        storage_bridge = _build_storage_bridge_snapshot(connected_apps_snapshot.get('connectedSessions', []))

        runtime_compartments = _build_runtime_compartments_snapshot(self.root, missions, runtime_statuses=runtime_statuses, setup_health=setup_health, storage_bridge=storage_bridge, provider_auth_presence=provider_auth_presence)

        generated_image_artifacts = _build_generated_image_artifacts_snapshot(self.root)

        hermes_mission_evidence = _build_hermes_mission_evidence(self.root, missions, activity)

        nas_deploy_readiness = build_nas_deploy_readiness_snapshot(self.root, onboarding=onboarding, setup_health=setup_health, storage_bridge=storage_bridge)

        autonomous_workflows = self.reconcile_autonomous_workflows(missions)

        mission_watchdog = build_mission_watchdog_report(root=self.root, missions=missions, workspaces=workspaces)

        mission_watchdog['supervisor'] = load_watchdog_supervisor_state(self.root)

        red_team_escalation = build_red_team_escalation_snapshot(self.root)

        system_audit_digest = _build_system_audit_digest(root=self.root, release_readiness=release_readiness, harness_lab=harness_lab_snapshot, missions=missions, workspaces=workspaces)

        integration_readiness = build_integration_readiness_snapshot(self.root, missions=missions, connected_apps_snapshot=connected_apps_snapshot, runtime_compartments=runtime_compartments, provider_auth_presence=provider_auth_presence, nas_deploy_readiness=nas_deploy_readiness, hermes_mission_evidence=hermes_mission_evidence)

        try:

            cluster_snapshot = ClusterRegistry(self.root).snapshot(job_limit=100)

        except Exception as exc:

            cluster_snapshot = {'schema': 'fluxio.cluster_registry.v1', 'status': 'unavailable', 'error': str(exc)}

        return {'workspaceRoot': str(self.root), 'ui': {'uiMode': 'agent', 'defaultMode': 'agent', 'availableModes': ['agent', 'builder'], 'layout': 't3_workbench', 'sharedMissionState': True}, 'workspaces': workspace_payload, 'missions': missions_payload, 'runtimes': [asdict(item) for item in runtime_statuses], 'activity': activity, 'inbox': inbox_items, 'onboarding': onboarding, 'setupHealth': setup_health, 'guidance': guidance, 'profiles': {'defaultProfile': profiles.default_profile, 'availableProfiles': profiles.list_names(), 'details': {name: {'description': profile.description, 'ui': profile.ui, 'agent': asdict(profile.agent), 'parameters': _profile_parameter_snapshot(name, profile)} for name, profile in profiles.profiles.items()}}, 'skillLibrary': skill_catalog, 'workflowStudio': _build_workflow_studio(workspace_payload, missions_payload, setup_health, skill_catalog), 'harnessLab': harness_lab_snapshot, 'providerSetupStatus': provider_setup_status, 'efficiencyAutotune': efficiency_autotune, 'bridgeLab': connected_apps_snapshot, 'storageBridge': storage_bridge, 'releaseReadiness': release_readiness, 'runtimeCompartments': runtime_compartments, 'generatedImageArtifacts': generated_image_artifacts, 'hermesMissionEvidence': hermes_mission_evidence, 'nasDeployReadiness': nas_deploy_readiness, 'integrationReadiness': integration_readiness, 'autonomousWorkflows': autonomous_workflows, 'missionWatchdog': mission_watchdog, 'cluster': cluster_snapshot, 'redTeamEscalation': red_team_escalation, 'systemAuditDigest': system_audit_digest}

    def build_summary_snapshot(self) -> dict:

        from .app_capability_standard import build_connected_apps_snapshot

        started = time.perf_counter()

        section_started = started

        section_durations: list[dict[str, object]] = []



        def record_section(name: str) -> None:

            nonlocal section_started

            now = time.perf_counter()

            section_durations.append({'name': name, 'durationMs': round((now - section_started) * 1000, 2)})

            section_started = now

        workspaces = self.load_workspaces()

        missions = self.load_missions()

        activity = self.recent_events(limit=24)

        project_history_events = self.recent_events(limit=80)

        provider_auth_presence = _provider_auth_presence_from_env()

        record_section('base_store_load')

        runtime_supervisor = DelegatedRuntimeSupervisor(self.root)

        mission_records_changed = False

        for mission in missions:

            before_runtime_signature = _mission_runtime_persistence_signature(mission)

            refreshed_sessions = []

            for session in mission.delegated_runtime_sessions:

                refreshed = _refresh_delegated_runtime_session_for_summary(runtime_supervisor, session)

                refreshed_sessions.append(refreshed)

            visible_refreshed_sessions = [item for item in refreshed_sessions if not _is_low_signal_stopped_session(item)]

            refreshed_sessions = sorted(visible_refreshed_sessions, key=_delegated_runtime_session_order_key)

            mission.delegated_runtime_sessions = refreshed_sessions

            mission.state.delegated_runtime_sessions = [asdict(item) for item in refreshed_sessions]

            refresh_mission_runtime_state(mission, refreshed_sessions)

            sync_mission_state_snapshot(mission)

            if _mission_runtime_persistence_signature(mission) != before_runtime_signature:

                mission_records_changed = True

        before_queue_signature = _mission_queue_persistence_signature(missions)

        self._rebalance_workspace_queue_in_place(missions)

        if _mission_queue_persistence_signature(missions) != before_queue_signature:

            mission_records_changed = True

        if mission_records_changed:

            self.save_missions(missions)

        record_section('runtime_reconcile')

        skill_catalog = self._fast_summary_skill_catalog_payload()

        record_section('skill_catalog')

        status_counts: dict[str, int] = {}

        runtime_counts: dict[str, int] = {}

        workspace_missions: dict[str, list[Mission]] = {}

        for mission in missions:

            status_counts[mission.state.status] = status_counts.get(mission.state.status, 0) + 1

            runtime_counts[mission.runtime_id] = runtime_counts.get(mission.runtime_id, 0) + 1

            workspace_missions.setdefault(mission.workspace_id, []).append(mission)

        workspace_payload = []

        mission_launch_shortcuts = []

        workspace_by_id = {workspace.workspace_id: workspace for workspace in workspaces}

        for workspace in workspaces:

            related = workspace_missions.get(workspace.workspace_id, [])

            ownership = _control_workspace_queue_projection(workspace.workspace_id, related)

            workspace_payload.append({'workspace_id': workspace.workspace_id, 'name': workspace.name, 'root_path': workspace.root_path, 'workspace_type': workspace.workspace_type, 'default_runtime': workspace.default_runtime, 'preferred_harness': workspace.preferred_harness, 'user_profile': workspace.user_profile, 'enabled': workspace.enabled, 'updated_at': workspace.updated_at, **{key: ownership[key] for key in ('activeMissionId', 'activeMissionTitle', 'activeMissionStatus', 'queuedMissionCount', 'missionCount')}})

            mission_launch_shortcuts.append(self._mission_launch_shortcut_payload(workspace))

        record_section('workspace_rows')

        sorted_missions = sorted(missions, key=lambda item: item.updated_at or item.created_at or '', reverse=True)

        active_bootstrap_missions = [mission for mission in sorted_missions if mission.state.status not in TERMINAL_MISSION_STATUSES and mission.state.status != 'draft']

        recent_missions = []

        seen_bootstrap_mission_ids: set[str] = set()

        for mission in [*active_bootstrap_missions, *sorted_missions]:

            if mission.mission_id in seen_bootstrap_mission_ids:

                continue

            seen_bootstrap_mission_ids.add(mission.mission_id)

            recent_missions.append(mission)

            if len(recent_missions) >= CONTROL_ROOM_VISIBLE_SUMMARY_MISSION_LIMIT:

                break

        mission_payload = []

        for mission in recent_missions:

            mission_active = _mission_counts_as_active_live(mission, require_queue_front=False)

            _reconcile_mission_route_policy(mission, workspace_by_id.get(mission.workspace_id))

            mission.state.provider_runtime_truth = _provider_truth_for_mission(mission, auth_presence=provider_auth_presence, workspace=workspace_by_id.get(mission.workspace_id))

            row = self._mission_summary_payload(mission, root=self.root if mission_active or mission.planned_file_scope else None, workspace=workspace_by_id.get(mission.workspace_id))

            if mission_active:

                row['contextRoots'] = self._summary_context_roots_payload(self._mission_context_roots_payload(mission, workspace=workspace_by_id.get(mission.workspace_id), workspaces=workspaces, workspace_missions=workspace_missions))

            else:

                row = self._summary_terminal_mission_payload(row)

                row['contextRoots'] = self._bootstrap_context_roots_placeholder(mission)

            mission_payload.append(row)

        record_section('mission_rows')

        mission_watchdog = _summary_mission_watchdog_report(root=self.root, missions=missions, workspaces=workspaces)

        mission_watchdog['supervisor'] = load_watchdog_supervisor_state(self.root)

        record_section('mission_watchdog')

        red_team_escalation = self._summary_red_team_escalation_payload(build_red_team_escalation_snapshot(self.root, limit=24))

        record_section('red_team_escalation')

        summary_harness_lab = build_summary_harness_lab_snapshot(self.root, missions=missions)

        record_section('harness_lab')

        connected_apps_snapshot = build_connected_apps_snapshot(self.root)

        record_section('bridge_lab')

        summary_runtime_compartments = _build_runtime_compartments_snapshot(self.root, missions, runtime_statuses=[], setup_health={'actionHistory': []}, storage_bridge={}, provider_auth_presence=provider_auth_presence)

        integration_readiness = build_integration_readiness_snapshot(self.root, missions=missions, connected_apps_snapshot=connected_apps_snapshot, runtime_compartments=summary_runtime_compartments, provider_auth_presence=provider_auth_presence, nas_deploy_readiness=build_nas_deploy_readiness_snapshot(self.root))

        record_section('integration_readiness')

        system_audit_digest = self._summary_system_audit_digest_payload(_build_system_audit_digest(root=self.root, release_readiness={}, harness_lab=summary_harness_lab, missions=missions, workspaces=workspaces))

        record_section('system_audit_digest')

        notifications = self._build_notification_feed(missions=recent_missions, activity=activity, watchdog_report=mission_watchdog, root=self.root, workspace_by_id=workspace_by_id)

        record_section('notification_feed')

        overnight_digest = self._overnight_progress_digest_payload(root=self.root, missions=missions, recent_missions=recent_missions, workspaces=workspaces, activity=activity, notifications=notifications, telegram_destination=load_telegram_destination(self.root), delivery_receipts=[asdict(item) for item in load_delivery_receipts(self.root, limit=24)])

        record_section('overnight_digest')

        project_progress_history = self._summary_project_progress_history_payload(root=self.root, workspaces=workspaces, missions=missions, events=project_history_events, workspace_missions=workspace_missions)

        mission_counts = _control_mission_counts_projection(missions)

        active_mission_count = mission_counts['active']

        queued_mission_count = mission_counts['queued']

        blocked_mission_count = mission_counts['blocked']

        runtime_budget_attention_mission_count = mission_counts['runtimeBudgetAttention']

        attention_mission_count = mission_counts['attention']

        scheduling_queue_count = len(project_progress_history.get('schedulingQueue', []))

        zero_active_queue_healthy = active_mission_count == 0 and queued_mission_count == 0 and (attention_mission_count == 0) and (project_progress_history.get('schema') == 'fluxio.project_progress_history.v1') and (scheduling_queue_count > 0)

        live_control_state = {'schema': 'fluxio.live_control_state.v1', 'status': 'ready_no_active' if zero_active_queue_healthy else 'active_or_attention', 'healthy': bool(active_mission_count > 0 or queued_mission_count > 0 or attention_mission_count > 0 or zero_active_queue_healthy), 'zeroActiveQueueHealthy': zero_active_queue_healthy, 'activeMissionCount': active_mission_count, 'queuedMissionCount': queued_mission_count, 'blockedMissionCount': blocked_mission_count, 'blockingMetricsSince': self.blocking_metrics_since(), 'attentionMissionCount': attention_mission_count, 'runtimeBudgetAttentionMissionCount': runtime_budget_attention_mission_count, 'schedulingQueueCount': scheduling_queue_count, 'detail': 'No mission is running; the NAS scheduler queue is live and ready for the next launch.' if zero_active_queue_healthy else 'Mission state includes active, queued, or attention rows.'}

        record_section('project_progress_history')

        try:

            cluster_snapshot = ClusterRegistry(self.root).snapshot(job_limit=20)

        except Exception as exc:

            cluster_snapshot = {'schema': 'fluxio.cluster_registry.v1', 'status': 'unavailable', 'error': str(exc)}

        record_section('cluster')

        payload = {'schema': 'fluxio.control_room.summary.v1', 'workspaceRoot': str(self.root), 'generatedAt': utc_now_iso(), 'counts': {'workspaces': len(workspaces), 'missions': len(missions), 'activeMissions': active_mission_count, 'queuedMissions': queued_mission_count, 'blockedMissions': blocked_mission_count, 'attentionMissions': attention_mission_count, 'runtimeBudgetAttentionMissions': runtime_budget_attention_mission_count, 'completedMissions': status_counts.get('completed', 0)}, 'statusCounts': status_counts, 'runtimeCounts': runtime_counts, 'workspaces': workspace_payload, 'missions': mission_payload, 'notifications': notifications, 'overnightDigest': overnight_digest, 'projectProgressHistory': project_progress_history, 'liveControlState': live_control_state, 'cluster': cluster_snapshot, 'harnessLab': {'schema': 'fluxio.harness_lab.summary_compact.v1', 'source': summary_harness_lab.get('source', 'mission_store_delegated_sessions_summary'), 'routeTrustCoverage': summary_harness_lab.get('routeTrustCoverage', {}), 'recommendation': summary_harness_lab.get('recommendation', {})}, 'bridgeLab': connected_apps_snapshot, 'integrationReadiness': integration_readiness, 'skillLibrary': skill_catalog, 'systemAuditDigest': system_audit_digest, 'missionWatchdog': {'schema': mission_watchdog['schema'], 'checkedAt': mission_watchdog['checkedAt'], 'summary': mission_watchdog['summary'], 'browserDependencyPreflight': self._summary_browser_dependency_preflight_payload(mission_watchdog.get('browserDependencyPreflight', {})), 'issues': [self._summary_watchdog_issue_payload(item) for item in mission_watchdog['issues'][:6] if isinstance(item, dict)], 'nextAction': mission_watchdog['nextAction'], 'summarySource': mission_watchdog.get('summarySource', {}), 'problemReport': {'schema': mission_watchdog.get('problemReport', {}).get('schema', 'fluxio.watchdog_problem_report.v1'), 'status': mission_watchdog.get('problemReport', {}).get('status', 'clear'), 'problemCount': mission_watchdog.get('problemReport', {}).get('problemCount', 0), 'firstProblem': self._summary_watchdog_issue_payload(mission_watchdog.get('problemReport', {}).get('firstProblem', {})), 'nextAction': mission_watchdog.get('problemReport', {}).get('nextAction', '')}, 'problemRegistry': {'schema': mission_watchdog.get('problemRegistry', {}).get('schema', 'fluxio.watchdog_problem_registry.v1'), 'status': mission_watchdog.get('problemRegistry', {}).get('status', 'clear'), 'openProblemCount': mission_watchdog.get('problemRegistry', {}).get('openProblemCount', 0), 'resolvedProblemCount': mission_watchdog.get('problemRegistry', {}).get('resolvedProblemCount', 0), 'newProblemCount': mission_watchdog.get('problemRegistry', {}).get('newProblemCount', 0), 'firstOpenProblem': self._summary_watchdog_issue_payload(mission_watchdog.get('problemRegistry', {}).get('firstOpenProblem', {})), 'nextAction': mission_watchdog.get('problemRegistry', {}).get('nextAction', ''), 'problems': [self._summary_watchdog_issue_payload(item) for item in mission_watchdog.get('problemRegistry', {}).get('problems', [])[:3] if isinstance(item, dict)]}, 'supervisor': mission_watchdog.get('supervisor', {})}, 'redTeamEscalation': red_team_escalation, 'missionLaunchShortcuts': mission_launch_shortcuts[:CONTROL_ROOM_VISIBLE_LAUNCH_SHORTCUT_LIMIT], 'providers': {'authPresence': provider_auth_presence, 'checkedAt': utc_now_iso(), 'consistentHermesCredentialPool': True}, 'mobileWeb': {'summaryFirst': True, 'notificationFeed': True, 'overnightDigest': True, 'appLikeProgress': True, 'phoneNotificationChannels': overnight_digest['delivery']['channels'], 'targetSurfaces': ['phone', 'tablet', 'desktop-web', 'tauri'], 'recommendedRefreshSeconds': 20, 'detailPayload': 'get_control_room_snapshot_command'}, 'summaryShaping': {'schema': 'fluxio.control_room.summary_shaping.v1', 'mode': 'bounded_live_summary', 'richContextRoots': 'active_missions_only', 'skillCatalogRows': 'bounded_live_samples_with_total_counts', 'projectProgressRows': 'bounded_project_milestones_and_receipts', 'redTeamHistoryRows': 'recent_rows_with_full_summary_counts', 'harnessLab': 'route_trust_coverage_only', 'systemAuditDigest': 'operator_summary_fields_only', 'terminalMissionContextRoots': 'placeholder_requires_mission_detail', 'missionRows': 'active_plus_recent_visible_preview', 'missionLaunchShortcuts': 'top_workspace_shortcuts', 'missionDetailCommand': 'get_control_room_mission_detail_command', 'fullSnapshotCommand': 'get_control_room_snapshot_command', 'reason': 'Keep live summary responsive while preserving real mission detail through explicit drill-down endpoints.'}}

        record_section('payload_assembly')

        performance = {'source': 'control_room_summary', 'durationMs': round((time.perf_counter() - started) * 1000, 2), 'missionLimit': len(mission_payload), 'activityLimit': len(activity), 'sectionDurations': section_durations, 'slowestSections': sorted(section_durations, key=lambda item: float(item.get('durationMs') or 0), reverse=True)[:5], 'virtualization': {'summaryFirst': True, 'lazyMissionDetail': True, 'boundedMissionRows': len(recent_missions), 'totalMissionRows': len(missions), 'boundedActivityRows': 24, 'detailCommand': 'control-room-mission-detail'}}

        payload['performance'] = performance

        payload['performance']['payloadBytes'] = len(json.dumps(payload, separators=(',', ':')).encode('utf-8'))

        payload['performance']['budget'] = self._performance_budget_payload(source='control_room_summary', duration_ms=payload['performance']['durationMs'], payload_bytes=payload['performance']['payloadBytes'], duration_budget_ms=CONTROL_ROOM_SUMMARY_DURATION_BUDGET_MS, payload_budget_bytes=CONTROL_ROOM_SUMMARY_PAYLOAD_BUDGET_BYTES, item_limits={'missions': CONTROL_ROOM_FULL_SUMMARY_MISSION_LIMIT, 'activity': 24, 'notifications': 24, 'overnightDigest': 1, 'projectProgressHistory': len(project_progress_history['projects']), 'workspaces': len(workspace_payload), 'richContextRoots': sum((1 for item in mission_payload if (item.get('contextRoots') or {}).get('status') != 'detail_required')), 'skills': len(skill_catalog.get('learnedSkills', [])) + len(skill_catalog.get('userInstalledSkills', [])) + len(skill_catalog.get('recommendedPacks', [])) + len(skill_catalog.get('curatedPacks', [])), 'systemAuditDigest': 1})

        return payload


    @staticmethod
    def _project_progress_history_payload(
        *,
        root: Path,
        workspaces: list[WorkspaceProfile],
        missions: list[Mission],
        events: list[dict],
        workspace_missions: dict[str, list[Mission]],
    ) -> dict:
        mission_by_id = {mission.mission_id: mission for mission in missions}
        events_by_workspace: dict[str, list[dict]] = {workspace.workspace_id: [] for workspace in workspaces}
        workspace_by_id = {workspace.workspace_id: workspace for workspace in workspaces}
        for event in events:
            mission_id = str(event.get("mission_id") or event.get("missionId") or "").strip()
            mission = mission_by_id.get(mission_id)
            workspace_id = str(
                event.get("workspace_id")
                or event.get("workspaceId")
                or (event.get("metadata") or {}).get("workspaceId")
                or (mission.workspace_id if mission else "")
            ).strip()
            if not workspace_id:
                continue
            events_by_workspace.setdefault(workspace_id, []).append(event)

        projects: list[dict] = []
        for workspace in workspaces:
            rows = sorted(
                workspace_missions.get(workspace.workspace_id, []),
                key=lambda mission: mission.updated_at or mission.created_at or "",
                reverse=True,
            )
            active = [
                mission
                for mission in rows
                if _mission_counts_as_active_live(mission)
            ]
            queued = [
                mission
                for mission in rows
                if mission.state.status not in TERMINAL_MISSION_STATUSES
                and mission.state.queue_position > 0
            ]
            blocked = [
                mission
                for mission in rows
                if mission.state.status not in TERMINAL_MISSION_STATUSES
                and (
                    mission.state.status in {"blocked", "needs_approval", "verification_failed"}
                    or mission.proof.pending_approvals
                    or mission.proof.failed_checks
                    or mission.state.verification_failures
                )
            ]
            completed = [mission for mission in rows if mission.state.status == "completed"]
            workspace_events = sorted(
                events_by_workspace.get(workspace.workspace_id, []),
                key=lambda event: _event_timestamp(event),
                reverse=True,
            )
            milestones: list[dict] = []
            for event in workspace_events[:12]:
                mission_id = str(event.get("mission_id") or event.get("missionId") or "").strip()
                mission = mission_by_id.get(mission_id)
                milestones.append(
                    {
                        "id": f"{workspace.workspace_id}:{mission_id or 'workspace'}:{_event_timestamp(event)}:{event.get('kind', 'event')}",
                        "source": "mission_events",
                        "missionId": mission_id,
                        "missionTitle": mission.title if mission else "",
                        "kind": str(event.get("kind") or "event"),
                        "message": str(event.get("message") or ""),
                        "timestamp": _event_timestamp(event),
                        "tone": _project_event_tone(event),
                    }
                )
            for mission in rows[:8]:
                if any(item["missionId"] == mission.mission_id and item["kind"] == "mission_state" for item in milestones):
                    continue
                milestones.append(
                    {
                        "id": f"{workspace.workspace_id}:{mission.mission_id}:mission_state",
                        "source": "mission_store",
                        "missionId": mission.mission_id,
                        "missionTitle": mission.title or mission.objective,
                        "kind": "mission_state",
                        "message": f"{mission.state.status}: {mission.proof.summary or mission.state.last_runtime_event or 'Mission state recorded.'}",
                        "timestamp": mission.updated_at or mission.created_at,
                        "tone": (
                            "bad"
                            if mission.state.status in {"failed", "verification_failed"}
                            else "warn"
                            if mission in blocked or mission.state.status in {"blocked", "needs_approval", "queued"}
                            else "good"
                            if mission.state.status == "completed"
                            else "neutral"
                        ),
                    }
                )
            milestones = sorted(
                milestones,
                key=lambda item: item.get("timestamp") or "",
                reverse=True,
            )[:14]
            bucket_map: dict[str, dict] = {}
            for mission in rows:
                timestamp = mission.updated_at or mission.created_at or ""
                day = timestamp[:10] if len(timestamp) >= 10 else "unknown"
                bucket = bucket_map.setdefault(
                    day,
                    {
                        "date": day,
                        "missionsTouched": 0,
                        "completed": 0,
                        "active": 0,
                        "blocked": 0,
                    },
                )
                bucket["missionsTouched"] += 1
                if mission.state.status == "completed":
                    bucket["completed"] += 1
                if mission in active:
                    bucket["active"] += 1
                if mission in blocked:
                    bucket["blocked"] += 1
            buckets = sorted(bucket_map.values(), key=lambda item: item["date"], reverse=True)[:10]
            latest = rows[0] if rows else None
            if blocked:
                next_action = "Review the first blocked mission or failed check before dispatching more project work."
            elif active:
                next_action = "Let the active mission continue and watch for the next slice-complete notification."
            elif queued:
                next_action = "Resume the front queued mission once the workspace slot is available."
            elif completed:
                next_action = "Open the latest proof digest and decide the next project mission."
            else:
                next_action = "Launch the first mission for this project."
            schedule = ControlRoomStore._project_schedule_recommendation(
                workspace=workspace,
                rows=rows,
                active=active,
                queued=queued,
                blocked=blocked,
                completed=completed,
                workspaces=workspaces,
                workspace_missions=workspace_missions,
                workspace_by_id=workspace_by_id,
            )
            sync_authority = ControlRoomStore._workspace_sync_authority(workspace)
            launch_rehearsal = ControlRoomStore._cross_device_launch_rehearsal(
                workspace=workspace,
                schedule=schedule,
                sync_authority=sync_authority,
            )
            latest_launch_receipt = _latest_cross_device_launch_receipt(
                root,
                workspace.workspace_id,
            )
            launch_receipt_history = _cross_device_launch_receipt_history(
                root,
                workspace_id=workspace.workspace_id,
                limit=6,
            )
            if latest_launch_receipt:
                launch_rehearsal = {
                    **launch_rehearsal,
                    "latestReceipt": latest_launch_receipt,
                    "receiptHistory": launch_receipt_history,
                    "receiptCount": len(launch_receipt_history),
                    "receiptTrendStatus": "repeated" if len(launch_receipt_history) >= 2 else "single",
                    "receiptBacked": True,
                }
            projects.append(
                {
                    "schema": "fluxio.project_progress.v1",
                    "workspaceId": workspace.workspace_id,
                    "workspaceName": workspace.name,
                    "rootPath": workspace.root_path,
                    "runtime": workspace.default_runtime,
                    "harness": workspace.preferred_harness,
                    "counts": {
                        "missions": len(rows),
                        "active": len(active),
                        "queued": len(queued),
                        "blocked": len(blocked),
                        "completed": len(completed),
                        "events": len(workspace_events),
                    },
                    "latestMissionId": latest.mission_id if latest else "",
                    "latestMissionTitle": latest.title or latest.objective if latest else "",
                    "latestUpdatedAt": latest.updated_at or latest.created_at if latest else workspace.updated_at,
                    "milestones": milestones,
                    "buckets": buckets,
                    "nextAction": next_action,
                    "scheduleRecommendation": schedule,
                    "syncAuthority": sync_authority,
                    "launchRehearsal": launch_rehearsal,
                    "liveData": True,
                    "empty": len(rows) == 0 and len(workspace_events) == 0,
                }
            )
        scheduling_queue = sorted(
            [
                project["scheduleRecommendation"]
                for project in projects
                if isinstance(project.get("scheduleRecommendation"), dict)
            ],
            key=lambda item: (
                -int(item.get("priorityScore", 0) or 0),
                str(item.get("workspaceName") or ""),
            ),
        )
        return {
            "schema": "fluxio.project_progress_history.v1",
            "generatedAt": utc_now_iso(),
            "source": "mission_store_and_mission_events",
            "eventLimit": len(events),
            "projects": projects,
            "schedulingQueue": scheduling_queue[:12],
            "launchReceiptSummary": _cross_device_launch_receipt_summary(root),
            "scheduler": {
                "schema": "fluxio.dependency_aware_project_scheduler.v1",
                "source": "workspace_mission_counts_and_context_roots",
                "queueSize": len(scheduling_queue),
                "topWorkspaceId": scheduling_queue[0]["workspaceId"] if scheduling_queue else "",
                "nextAction": (
                    scheduling_queue[0]["recommendedAction"]
                    if scheduling_queue
                    else "Register a workspace and launch the first mission."
                ),
            },
            "empty": not projects,
        }

    @staticmethod
    def _workspace_dependency_ids(workspace: WorkspaceProfile) -> set[str]:
        dependency_ids: set[str] = set()
        for goal in workspace.goals:
            text = str(goal or "").strip()
            lowered = text.lower()
            for prefix in ("depends_on:", "depends-on:", "dependency:", "dependency=", "upstream:"):
                if not lowered.startswith(prefix):
                    continue
                raw_ids = text[len(prefix) :]
                for item in re.split(r"[,;\s]+", raw_ids):
                    dependency_id = item.strip()
                    if dependency_id:
                        dependency_ids.add(dependency_id)
                break
        return dependency_ids

    @staticmethod
    def _workspace_sync_authority(workspace: WorkspaceProfile) -> dict[str, object]:
        sync_status = _workspace_sync_status(workspace)
        sync_receipt = (
            sync_status.get("syncReceipt", {})
            if isinstance(sync_status.get("syncReceipt"), dict)
            else {}
        )
        conflict_count = int(sync_status.get("conflictsDetected") or sync_receipt.get("conflictsDetected") or 0)
        manual_review = bool(sync_status.get("manualReviewRequired") or sync_receipt.get("manualReviewRequired"))
        effective_direction = str(
            sync_status.get("effectiveDirection")
            or sync_receipt.get("effectiveDirection")
            or workspace.sync_direction
            or "manual"
        )
        local_path = str(workspace.local_project_path or "").strip()
        nas_path = str(workspace.nas_project_path or "").strip()
        current_root = str(workspace.root_path or "").strip()
        receipt_id = str(sync_receipt.get("receiptId") or "")
        if manual_review or conflict_count > 0:
            state = "conflict_review"
            authority = "manual_review"
            launch_safety = "review_required"
            safe_for_writable_dependency = False
            summary = "Sync conflicts require operator review before this workspace is used as a writable dependency."
            next_action = "Resolve sync conflicts or choose the authoritative copy before launching dependent work."
        elif workspace.auto_sync_to_nas and nas_path:
            if effective_direction == "local_to_nas":
                state = "local_authoritative"
                authority = "local"
                summary = "Computer copy is the write source and NAS is the mirror target."
            elif effective_direction == "nas_to_local":
                state = "nas_authoritative"
                authority = "nas"
                summary = "NAS copy is the write source and computer copy is the mirror target."
            elif receipt_id:
                state = "bidirectional_synced"
                authority = "bidirectional"
                summary = "Computer and NAS copies have a sync receipt and no pending conflict review."
            else:
                state = "nas_mirror_unverified"
                authority = "nas"
                summary = "NAS mirroring is configured, but no current sync receipt proves the copies are aligned."
            launch_safety = "safe" if receipt_id or effective_direction in {"local_to_nas", "nas_to_local"} else "verify_first"
            safe_for_writable_dependency = launch_safety == "safe"
            next_action = (
                "Writable dependency use is allowed; keep receipts attached to future sync changes."
                if safe_for_writable_dependency
                else "Run a sync check before using this workspace as a writable dependency."
            )
        elif local_path and nas_path:
            state = "sync_configured_unverified"
            authority = "manual"
            launch_safety = "verify_first"
            safe_for_writable_dependency = False
            summary = "Both local and NAS paths are configured, but automatic sync is not active."
            next_action = "Pick local, NAS, or bidirectional sync authority before dependent launch."
        else:
            state = "manual_local"
            authority = "workspace_root"
            launch_safety = "manual"
            safe_for_writable_dependency = True
            summary = "Workspace root is the current manual source of truth."
            next_action = "Use manual launch or configure NAS sync before cross-device work."
        return {
            "schema": "fluxio.workspace_sync_authority.v1",
            "workspaceId": workspace.workspace_id,
            "state": state,
            "authority": authority,
            "launchSafety": launch_safety,
            "safeForWritableDependency": safe_for_writable_dependency,
            "summary": summary,
            "nextAction": next_action,
            "localProjectPath": local_path,
            "nasProjectPath": nas_path,
            "currentRootPath": current_root,
            "syncMode": workspace.sync_mode,
            "requestedDirection": workspace.sync_direction,
            "effectiveDirection": effective_direction,
            "conflictPolicy": workspace.sync_conflict_policy,
            "autoSyncToNas": bool(workspace.auto_sync_to_nas),
            "receiptId": receipt_id,
            "conflictCount": conflict_count,
            "manualReviewRequired": manual_review,
        }

    @staticmethod
    def _cross_device_launch_rehearsal(
        *,
        workspace: WorkspaceProfile,
        schedule: dict[str, object],
        sync_authority: dict[str, object],
    ) -> dict[str, object]:
        launch_recommendation = build_launch_runtime_recommendation(
            objective="",
            workspace_default_runtime=workspace.default_runtime,
            profile=workspace.user_profile or "builder",
        )
        schedule_safe = bool(schedule.get("safeToLaunch"))
        sync_safe = bool(sync_authority.get("safeForWritableDependency"))
        runtime = str(launch_recommendation.get("runtime") or workspace.default_runtime or "hermes")
        query = urlencode(
            {
                "launch": "mission",
                "workspaceId": workspace.workspace_id,
                "runtime": runtime,
                "profile": workspace.user_profile or "builder",
                "mode": "Autopilot",
                "syncAuthority": str(sync_authority.get("authority") or "manual"),
            }
        )
        checklist = [
            {
                "id": "sync_authority",
                "label": "Sync authority",
                "status": "pass" if sync_safe else "review",
                "detail": str(sync_authority.get("summary") or ""),
            },
            {
                "id": "dependency_schedule",
                "label": "Dependency schedule",
                "status": "pass" if schedule_safe else "review",
                "detail": str(schedule.get("recommendedAction") or ""),
            },
            {
                "id": "runtime_route",
                "label": "Runtime route",
                "status": "pass",
                "detail": (
                    f"{runtime_label(runtime)} via "
                    f"{launch_recommendation.get('modelProvider', '')}/"
                    f"{launch_recommendation.get('model', '')}"
                ).strip("/"),
            },
        ]
        blocked_items = [item for item in checklist if item["status"] != "pass"]
        status = "ready" if not blocked_items else "review_required"
        safe_workspace_id = str(workspace.workspace_id).replace('"', '\\"')
        return {
            "schema": "fluxio.cross_device_launch_rehearsal.v1",
            "workspaceId": workspace.workspace_id,
            "status": status,
            "safeToLaunch": status == "ready",
            "checklist": checklist,
            "blockedCheckIds": [item["id"] for item in blocked_items],
            "runtimeRecommendation": launch_recommendation,
            "recommendedRuntime": runtime,
            "urlPath": f"/control?{query}",
            "cliCommand": (
                'python -m grant_agent.cli mission-quickstart --root . '
                f'--workspace-id "{safe_workspace_id}" --runtime auto '
                '--objective "Describe the mission goal" --budget-hours 4'
            ),
            "nextAction": (
                "Launch rehearsal is ready; open the mission launcher with this workspace, sync authority, and runtime route."
                if status == "ready"
                else "Resolve the review items before launching cross-device dependent work."
            ),
        }

    @staticmethod
    def _project_schedule_recommendation(
        *,
        workspace: WorkspaceProfile,
        rows: list[Mission],
        active: list[Mission],
        queued: list[Mission],
        blocked: list[Mission],
        completed: list[Mission],
        workspaces: list[WorkspaceProfile],
        workspace_missions: dict[str, list[Mission]],
        workspace_by_id: dict[str, WorkspaceProfile],
    ) -> dict:
        related_active = []
        related_blocked = []
        dependency_active = []
        dependency_blocked = []
        downstream_active = []
        dependency_ids = ControlRoomStore._workspace_dependency_ids(workspace)
        workspace_root = str(Path(workspace.root_path).expanduser().resolve()) if workspace.root_path else ""
        for other_workspace in workspaces:
            if other_workspace.workspace_id == workspace.workspace_id:
                continue
            other_root = str(Path(other_workspace.root_path).expanduser().resolve()) if other_workspace.root_path else ""
            same_root = bool(workspace_root and other_root and workspace_root == other_root)
            upstream_dependency = other_workspace.workspace_id in dependency_ids
            downstream_dependency = workspace.workspace_id in ControlRoomStore._workspace_dependency_ids(other_workspace)
            if not same_root and not upstream_dependency and not downstream_dependency:
                continue
            other_rows = workspace_missions.get(other_workspace.workspace_id, [])
            other_active = [
                mission
                for mission in other_rows
                if _mission_counts_as_active_live(mission, require_queue_front=False)
            ]
            other_blocked = [
                mission
                for mission in other_rows
                if mission.state.status not in TERMINAL_MISSION_STATUSES
                and (
                    # Blocked/needs_approval release the local slot but still block dependents.
                    mission.state.status in {"blocked", "needs_approval"}
                    or mission.proof.pending_approvals
                    or (
                        not _mission_releases_workspace_slot(mission)
                        and _mission_runtime_budget_exhausted(mission)
                    )
                )
            ]
            if other_active:
                relation = (
                    "upstream_dependency"
                    if upstream_dependency
                    else "downstream_dependency"
                    if downstream_dependency
                    else "same_root"
                )
                related_active.append(
                    {
                        "workspaceId": other_workspace.workspace_id,
                        "workspaceName": other_workspace.name,
                        "activeMissionCount": len(other_active),
                        "missionIds": [mission.mission_id for mission in other_active[:4]],
                        "relation": relation,
                    }
                )
                if upstream_dependency:
                    dependency_active.append(related_active[-1])
                if downstream_dependency:
                    downstream_active.append(related_active[-1])
            if other_blocked:
                relation = (
                    "upstream_dependency"
                    if upstream_dependency
                    else "downstream_dependency"
                    if downstream_dependency
                    else "same_root"
                )
                related_blocked.append(
                    {
                        "workspaceId": other_workspace.workspace_id,
                        "workspaceName": other_workspace.name,
                        "blockedMissionCount": len(other_blocked),
                        "missionIds": [mission.mission_id for mission in other_blocked[:4]],
                        "relation": relation,
                    }
                )
                if upstream_dependency:
                    dependency_blocked.append(related_blocked[-1])
        if blocked:
            state = "repair"
            priority = 100
            recommended_action = "Repair blocked mission before launching more project work."
            target_mission = blocked[0]
        elif dependency_blocked:
            state = "dependency_blocked"
            priority = 92
            recommended_action = "Unblock the upstream dependency workspace before launching this project."
            target_mission = None
        elif queued:
            state = "resume_queue"
            priority = 84
            recommended_action = "Resume the front queued mission now; the workspace slot is clear."
            target_mission = queued[0]
        elif dependency_active and not active:
            state = "dependency_wait"
            priority = 74
            recommended_action = "Wait for the upstream dependency workspace to finish or schedule a read-only follow-up."
            target_mission = None
        elif active:
            state = "watch"
            priority = 68
            recommended_action = "Let the active mission continue; avoid overlapping edits unless scope is disjoint."
            target_mission = active[0]
        elif not rows:
            state = "launch_first"
            priority = 62
            recommended_action = "Launch the first mission for this project from Builder."
            target_mission = None
        elif completed:
            state = "plan_next"
            priority = 55
            recommended_action = "Open the latest proof digest, then schedule the next dependency-aware mission."
            target_mission = completed[0]
        else:
            state = "review"
            priority = 45
            recommended_action = "Review recent project history before scheduling the next mission."
            target_mission = rows[0] if rows else None
        dependency_warnings = []
        same_root_blocked = [item for item in related_blocked if item.get("relation") == "same_root"]
        same_root_active = [item for item in related_active if item.get("relation") == "same_root"]
        if same_root_blocked:
            dependency_warnings.append("Related workspace has blocked active work on the same root.")
            priority = max(priority, 90)
        if dependency_blocked:
            dependency_warnings.append("Upstream dependency workspace is blocked.")
            priority = max(priority, 92)
        if dependency_active and not active:
            dependency_warnings.append("Upstream dependency workspace has active work.")
        if same_root_active and not active:
            dependency_warnings.append("Related workspace already has active work on the same root.")
        return {
            "schema": "fluxio.project_schedule_recommendation.v1",
            "workspaceId": workspace.workspace_id,
            "workspaceName": workspace.name,
            "state": state,
            "priorityScore": priority,
            "recommendedAction": recommended_action,
            "targetMissionId": target_mission.mission_id if target_mission else "",
            "targetMissionTitle": (target_mission.title or target_mission.objective) if target_mission else "",
            "runtime": workspace.default_runtime,
            "sameRootActiveWorkspaces": related_active,
            "sameRootBlockedWorkspaces": related_blocked,
            "dependencyActiveWorkspaces": dependency_active,
            "dependencyBlockedWorkspaces": dependency_blocked,
            "downstreamActiveWorkspaces": downstream_active,
            "declaredDependencyIds": sorted(dependency_ids),
            "dependencyWarnings": dependency_warnings,
            "safeToLaunch": (
                state in {"resume_queue", "launch_first", "plan_next"}
                and not active
                and not related_active
                and not related_blocked
                and not dependency_active
                and not dependency_blocked
            ),
            "launchMode": (
                "resume_mission"
                if state == "resume_queue" and not dependency_blocked
                else "new_mission"
                if state in {"launch_first", "plan_next"} and not dependency_blocked
                else "hold_or_repair"
            ),
            "reason": (
                f"{len(active)} active, {len(queued)} queued, {len(blocked)} blocked, "
                f"{len(completed)} completed mission(s); {len(related_active)} related active workspace(s); "
                f"{len(dependency_active)} upstream active dependency workspace(s)."
            ),
        }

    @staticmethod

    @_control_checked("overnight")

    def _overnight_progress_projection(

        *,

        missions: list[Mission],

        recent_missions: list[Mission],

        workspaces: list[WorkspaceProfile],

        activity: list[dict],

        notifications: list[dict],

        telegram_destination: str,

        delivery_receipts: list[dict] | None = None,

        web_push: dict,

        ntfy: dict,

    ) -> dict:

        delivery_receipts = list(delivery_receipts or [])

        active = [

            item

            for item in missions

            if item.state.status not in TERMINAL_MISSION_STATUSES

            and item.state.status != "draft"

        ]

        queued = [item for item in active if item.state.queue_position > 0]

        held_queued = [

            item

            for item in queued

            if str(item.state.status or "").lower() == "queued"

            and (item.state.blocking_mission_id or item.state.queue_position > 0)

        ]

        action_required = [

            item

            for item in active

            if item not in held_queued

            and (

                item.state.status in {"blocked", "needs_approval", "verification_failed"}

                or _mission_runtime_budget_exhausted(item)

                or item.proof.pending_approvals

                or item.proof.failed_checks

            )

        ]

        attention = action_required + held_queued

        running = [

            item

            for item in active

            if item.state.status in {"running", "queued"}

            and _mission_counts_as_active_live(item)

            and item not in attention

        ]

        completed_recent = [

            item for item in recent_missions if item.state.status == "completed"

        ]

        latest = recent_missions[0] if recent_missions else None

        action_notifications = [

            item for item in notifications if item.get("severity") == "action"

        ]

        success_notifications = [

            item for item in notifications if item.get("severity") == "success"

        ]

        latest_activity = activity[0] if activity else {}

        if action_required and held_queued:

            severity = "action"

            headline = f"{len(action_required)} mission(s) need repair · {len(held_queued)} held safely"

            next_action = "Repair the failed or approval-gated mission first. Held queued missions are waiting behind overlapping active work; split their file scope before parallelizing."

        elif action_required:

            severity = "action"

            headline = f"{len(action_required)} mission(s) need repair"

            next_action = "Open the phone progress view and resolve the first approval, blocker, or failed check."

        elif held_queued:

            severity = "progress"

            headline = f"{len(held_queued)} mission(s) held safely in queue"

            next_action = "No manual relaunch is needed. Keep them queued unless you split the overlapping file scope into a separate lane."

        elif running:

            severity = "progress"

            headline = f"{len(running)} mission(s) can continue hands-free"

            next_action = "Keep the phone progress view open or let browser/Telegram notifications carry overnight updates."

        elif completed_recent:

            severity = "success"

            headline = f"{len(completed_recent)} recent mission(s) completed"

            next_action = "Review proof digests and launch the next mission batch."

        else:

            severity = "idle"

            headline = "No active overnight mission is running"

            next_action = "Launch a mission batch before going offline."

        channels = ["in_app_stack", "browser_notification"]

        if telegram_destination:

            channels.append("telegram")

        if web_push.get("configured") or web_push.get("subscriptionCount"):

            channels.append("web_push")

        if ntfy.get("configured"):

            channels.append("ntfy")

        digest_id = (

            f"overnight:{severity}:{len(active)}:{len(attention)}:"

            f"{latest.mission_id if latest else 'none'}:{latest.updated_at if latest else ''}"

        )

        focus_items = []

        for mission in (action_required + held_queued + running + completed_recent)[:5]:

            if mission in held_queued:

                focus_summary = (

                    f"Held behind active mission {mission.state.blocking_mission_id or 'unknown'} "

                    "to avoid overlapping workspace writes."

                )

                focus_next_action = (

                    "Keep queued, or split the mission into a non-overlapping file scope before parallelizing."

                )

            else:

                focus_summary = (

                    mission.state.last_runtime_event

                    or mission.proof.summary

                    or mission.objective

                )[:260]

                focus_next_action = ControlRoomStore._next_mission_detail_action(mission)

            focus_items.append(

                {

                    "missionId": mission.mission_id,

                    "title": mission.title or mission.objective,

                    "status": mission.state.status,

                    "runtime": mission.runtime_id,

                    "attentionKind": (

                        "held_queue"

                        if mission in held_queued

                        else "repair"

                        if mission in action_required

                        else "running"

                        if mission in running

                        else "completed"

                    ),

                    "blockingMissionId": mission.state.blocking_mission_id if mission in held_queued else "",

                    "summary": focus_summary,

                    "nextAction": focus_next_action,

                    "updatedAt": mission.updated_at,

                }

            )

        notification = {

            "id": digest_id,

            "kind": "overnight_progress_digest",

            "severity": severity if severity != "progress" else "info",

            "status": severity,

            "title": headline,

            "detail": next_action,

            "createdAt": utc_now_iso(),

        }

        receipt_status_counts: dict[str, int] = {}

        for receipt in delivery_receipts:

            status = str(receipt.get("status") or "unknown")

            receipt_status_counts[status] = receipt_status_counts.get(status, 0) + 1

        return {

            "schema": "fluxio.overnight_progress_digest.v1",

            "digestId": digest_id,

            "generatedAt": utc_now_iso(),

            "headline": headline,

            "severity": severity,

            "nextAction": next_action,

            "phoneSummary": (

                f"{len(active)} active · {len(action_required)} repair · {len(held_queued)} held · "

                f"{len(queued)} queued · {len(completed_recent)} recently completed"

            ),

            "counts": {

                "workspaces": len(workspaces),

                "missions": len(missions),

                "active": len(active),

                "running": len(running),

                "queued": len(queued),

                "blocked": len(action_required),

                "attention": len(attention),

                "actionRequired": len(action_required),

                "heldQueued": len(held_queued),

                "completedRecent": len(completed_recent),

                "actionNotifications": len(action_notifications),

                "successNotifications": len(success_notifications),

            },

            "delivery": {

                "channels": channels,

                "browserNotificationReady": True,

                "webPushReady": bool(

                    web_push.get("senderConfigured")

                    and int(web_push.get("subscriptionCount") or 0) > 0

                ),

                "webPushSenderConfigured": bool(web_push.get("senderConfigured")),

                "webPushSubscriptionCount": int(web_push.get("subscriptionCount") or 0),

                "webPushNextAction": str(web_push.get("nextAction") or ""),

                "ntfyReady": bool(ntfy.get("senderConfigured")),

                "ntfyTopicConfigured": bool(ntfy.get("configured")),

                "ntfyNextAction": str(ntfy.get("nextAction") or ""),

                "telegramReady": bool(telegram_destination),

                "telegramDestinationConfigured": bool(telegram_destination),

                "receiptBacked": True,

                "receiptCount": len(delivery_receipts),

                "receiptStatusCounts": receipt_status_counts,

                "latestReceipts": delivery_receipts[-5:],

                "recommendedRefreshSeconds": 30 if active else 90,

                "phoneSurface": "control-room-summary",

                "appLike": True,

            },

            "focusItems": focus_items,

            "latestActivity": {

                "kind": latest_activity.get("kind", ""),

                "message": str(latest_activity.get("message", ""))[:260],

                "timestamp": latest_activity.get("timestamp", ""),

            },

            "notification": notification,

        }


    @staticmethod

    def _overnight_progress_digest_payload(*, root: Path, missions: list[Mission], recent_missions: list[Mission], workspaces: list[WorkspaceProfile], activity: list[dict], notifications: list[dict], telegram_destination: str, delivery_receipts: list[dict] | None=None) -> dict:

        try:

            web_push = web_push_status(root)

        except Exception:

            web_push = {'schema': 'fluxio.web_push_status.v1', 'configured': False, 'senderConfigured': False, 'subscriptionCount': 0, 'nextAction': 'Inspect Web Push setup from the notification stack.'}

        try:

            ntfy = ntfy_status(root)

        except Exception:

            ntfy = {'schema': 'fluxio.ntfy_status.v1', 'configured': False, 'senderConfigured': False, 'nextAction': 'Inspect ntfy setup from notification settings.'}

        return ControlRoomStore._overnight_progress_projection(missions=missions, recent_missions=recent_missions, workspaces=workspaces, activity=activity, notifications=notifications, telegram_destination=telegram_destination, delivery_receipts=delivery_receipts, web_push=web_push, ntfy=ntfy)

    @staticmethod
    def _mission_launch_shortcut_payload(workspace: WorkspaceProfile) -> dict:
        launch_recommendation = build_launch_runtime_recommendation(
            objective="",
            workspace_default_runtime=workspace.default_runtime,
            profile=workspace.user_profile or "builder",
        )
        query = urlencode(
            {
                "launch": "mission",
                "workspaceId": workspace.workspace_id,
                "runtime": launch_recommendation["runtime"],
                "profile": workspace.user_profile or "builder",
                "mode": "Autopilot",
            }
        )
        safe_workspace_id = str(workspace.workspace_id).replace('"', '\\"')
        return {
            "workspaceId": workspace.workspace_id,
            "workspaceName": workspace.name,
            "runtime": workspace.default_runtime,
            "recommendedRuntime": launch_recommendation["runtime"],
            "runtimeRecommendation": ControlRoomStore._summary_runtime_recommendation_payload(
                launch_recommendation
            ),
            "profile": workspace.user_profile or "builder",
            "urlPath": f"/control?{query}",
            "cliCommand": (
                'python -m grant_agent.cli mission-quickstart --root . '
                f'--workspace-id "{safe_workspace_id}" --runtime auto '
                '--objective "Describe the mission goal" --budget-hours 4'
            ),
            "summary": "Copy this URL or command to reopen the mission launcher with project defaults.",
        }


    def _build_fast_snapshot(self, workspaces: list[WorkspaceProfile], missions: list[Mission]) -> dict:
        activity = self.recent_events()
        provider_auth_presence = _provider_auth_presence_from_env()
        workspace_payload = [
            {
                **asdict(workspace),
                "openaiCodexSetupStatus": _openai_codex_setup_status_for_workspace(
                    workspace,
                    auth_presence=provider_auth_presence,
                ),
                "minimaxSetupStatus": {},
                "runtimeStatus": None,
                "gitSnapshot": {},
                "gitActions": [],
                "validationActions": [],
                "verificationCommands": [],
                "workspaceActionHistory": [],
                "profileParameters": {},
                "skillRecommendations": [],
                "integrationRecommendations": [],
                "recommendedSkillPacks": [],
                "serviceManagement": {},
            }
            for workspace in workspaces
        ]
        missions_payload = []
        for mission in missions:
            workspace = next(
                (item for item in workspaces if item.workspace_id == mission.workspace_id),
                None,
            )
            _reconcile_mission_route_policy(mission, workspace)
            mission.state.provider_runtime_truth = _provider_truth_for_mission(
                mission,
                auth_presence=provider_auth_presence,
                workspace=workspace,
            )
            _sync_execution_scope_snapshot(mission)
            self.attach_lane_control_receipts(mission)
            mission_payload = asdict(mission)
            mission_payload["missionLoop"] = build_mission_loop_snapshot(mission)
            mission_payload["plannedScopeArtifacts"] = build_planned_scope_artifacts(
                root=self.root,
                mission=mission,
                workspace=workspace,
            )
            mission_payload["effectiveRouteContract"] = (
                mission.effective_route_contract
                if mission.effective_route_contract
                else _effective_route_contract_for_mission(mission)
            )
            mission_payload["providerTruth"] = dict(mission.state.provider_runtime_truth or {})
            mission_payload["providerCapabilities"] = _provider_capability_contract_for_mission(mission)
            missions_payload.append(mission_payload)
        storage_bridge: dict = {}
        setup_health: dict = {"actionHistory": []}
        autonomous_workflows = self.reconcile_autonomous_workflows(missions)
        return {
            "workspaceRoot": str(self.root),
            "ui": {
                "uiMode": "agent",
                "defaultMode": "agent",
                "availableModes": ["agent", "builder"],
                "layout": "t3_workbench",
                "sharedMissionState": True,
            },
            "workspaces": workspace_payload,
            "missions": missions_payload,
            "runtimes": [],
            "activity": activity,
            "inbox": [],
            "onboarding": {"setupHealth": setup_health},
            "setupHealth": setup_health,
            "guidance": {},
            "profiles": {"defaultProfile": "builder", "availableProfiles": [], "details": {}},
            "skillLibrary": {"items": [], "recommendedPacks": []},
            "workflowStudio": {},
            "harnessLab": {},
            "providerSetupStatus": {},
            "efficiencyAutotune": {},
            "bridgeLab": {"connectedSessions": []},
            "storageBridge": storage_bridge,
            "releaseReadiness": {},
            "runtimeCompartments": _build_runtime_compartments_snapshot(
                self.root,
                missions,
                runtime_statuses=[],
                setup_health=setup_health,
                storage_bridge=storage_bridge,
                provider_auth_presence=provider_auth_presence,
            ),
            "generatedImageArtifacts": _build_generated_image_artifacts_snapshot(self.root),
            "hermesMissionEvidence": _build_hermes_mission_evidence(
                self.root,
                missions,
                activity,
            ),
            "nasDeployReadiness": build_nas_deploy_readiness_snapshot(
                self.root,
                onboarding={"setupHealth": setup_health},
                setup_health=setup_health,
                storage_bridge=storage_bridge,
            ),
            "autonomousWorkflows": autonomous_workflows,
        }

    def _default_workspace_profile(self) -> WorkspaceProfile:
        now = utc_now_iso()
        return WorkspaceProfile(
            workspace_id="workspace_primary",
            name=self.root.name.replace("-", " ").title(),
            root_path=str(self.root),
            default_runtime="hermes",
            workspace_type=detect_workspace_type(self.root),
            user_profile="builder",
            preferred_harness="fluxio_hybrid",
            routing_strategy="profile_default",
            route_overrides=[],
            auto_optimize_routing=False,
            openai_codex_auth_mode="none",
            minimax_auth_mode="none",
            commit_message_style="scoped",
            execution_target_preference="profile_default",
            local_project_path="",
            nas_project_path="",
            sync_mode="manual",
            sync_direction="bidirectional",
            sync_conflict_policy="keep_newer_and_log",
            auto_sync_to_nas=False,
            updated_at=now,
        )

    @staticmethod

    @_serialize_json_cache_read

    @_control_checked('cache')

    def _load_json(path: Path, default: list | dict) -> list | dict:

        try:

            stat = path.stat()

        except OSError:

            return default

        if stat.st_size <= 0:

            return default

        cache_key = str(path.resolve())

        if stat.st_size <= CONTROL_ROOM_JSON_CACHE_MAX_BYTES:

            with _CONTROL_ROOM_JSON_CACHE_LOCK:

                cached = _CONTROL_ROOM_JSON_CACHE.get(cache_key)

                if cached and cached[0] == stat.st_mtime_ns and (cached[1] == stat.st_size):

                    return cached[2]

        try:

            raw = path.read_text(encoding='utf-8').strip()

        except OSError:

            return default

        if not raw:

            return default

        try:

            payload = json.loads(raw)

        except json.JSONDecodeError:

            return default

        if isinstance(payload, (list, dict)) and stat.st_size <= CONTROL_ROOM_JSON_CACHE_MAX_BYTES:

            with _CONTROL_ROOM_JSON_CACHE_LOCK:

                _CONTROL_ROOM_JSON_CACHE[cache_key] = (stat.st_mtime_ns, stat.st_size, payload)

                if len(_CONTROL_ROOM_JSON_CACHE) > CONTROL_ROOM_JSON_CACHE_MAX_ITEMS:

                    oldest_key = next(iter(_CONTROL_ROOM_JSON_CACHE))

                    _CONTROL_ROOM_JSON_CACHE.pop(oldest_key, None)

        return payload

    @staticmethod
    def _invalidate_json_cache(path: Path) -> None:
        try:
            cache_key = str(path.resolve())
        except OSError:
            cache_key = str(path)
        with _CONTROL_ROOM_JSON_CACHE_LOCK:
            _CONTROL_ROOM_JSON_CACHE.pop(cache_key, None)

    @staticmethod
    def _split_release_path(raw_path: str) -> tuple[str, str, str] | None:
        normalized = str(raw_path or "")
        match = RELEASE_PATH_PATTERN.match(normalized)
        if not match:
            return None
        prefix = match.group("prefix")
        release = match.group("release")
        suffix = match.group("suffix") or ""
        return prefix, release, suffix

    @staticmethod
    def _path_identity_key(raw_path: str | Path) -> str:
        """Return a platform-normalized key for filesystem identity comparisons.

        Windows runners can expose one directory through both its long name and
        an 8.3 alias.  Resolve the path before comparing so release re-anchoring
        is based on the directory identity rather than its current spelling.
        """

        try:
            resolved = Path(raw_path).expanduser().resolve()
        except OSError:
            resolved = Path(raw_path).expanduser()
        return os.path.normcase(os.path.normpath(str(resolved)))

    def _reanchor_release_workspaces(self, workspaces: list[WorkspaceProfile]) -> bool:
        current = self._split_release_path(str(self.root))
        if not current:
            return False
        current_prefix, current_release, _ = current
        current_prefix_key = self._path_identity_key(current_prefix)
        changed = False
        for workspace in workspaces:
            parsed = self._split_release_path(workspace.root_path)
            if not parsed:
                continue
            prefix, release, suffix = parsed
            if (
                self._path_identity_key(prefix) != current_prefix_key
                or os.path.normcase(release) == os.path.normcase(current_release)
            ):
                continue
            current_release_root = Path(current_prefix) / current_release
            next_root = str(
                current_release_root / Path(suffix.lstrip("/\\"))
                if suffix
                else current_release_root
            )
            if workspace.root_path != next_root:
                workspace.root_path = next_root
                workspace.workspace_type = detect_workspace_type(Path(next_root))
                workspace.updated_at = utc_now_iso()
                changed = True
        return changed

    def _active_workspace_mission(
        self,
        workspace_id: str,
        missions: list[Mission],
    ) -> Mission | None:
        for mission in missions:
            if mission.workspace_id != workspace_id:
                continue
            if not _mission_occupies_workspace_slot(mission):
                continue
            return mission
        return None

    @_control_checked('queue')

    def _rebalance_workspace_queue_in_place(self, missions: list[Mission], workspace_id: str | None=None) -> None:

        workspace_ids = [workspace_id] if workspace_id is not None else list(dict.fromkeys((item.workspace_id for item in missions)))

        for current_workspace_id in workspace_ids:

            workspace_missions = [item for item in missions if item.workspace_id == current_workspace_id]

            active = self._active_workspace_mission(current_workspace_id, workspace_missions)

            candidates = [item for item in workspace_missions if not _mission_releases_workspace_slot(item)]

            active_candidates = [item for item in candidates if str(item.state.status or '').strip().lower() != 'draft' and (not _mission_runtime_budget_exhausted(item))]

            if not candidates:

                continue

            waiting = [item for item in active_candidates if active is None or item.mission_id != active.mission_id]

            waiting.sort(key=lambda item: (item.state.queue_position if item.state.queue_position > 0 else 10000, item.created_at, item.mission_id))

            if active is None and waiting:

                active = waiting.pop(0)

            if active is None:

                for mission in workspace_missions:

                    if _mission_releases_workspace_slot(mission) or _mission_runtime_budget_exhausted(mission):

                        mission.state.queue_position = 0

                        mission.state.blocking_mission_id = None

                        mission.state.queue_reason = ''

                continue

            was_waiting = bool(active.state.queue_position or active.state.blocking_mission_id or active.state.queue_reason)

            active.state.queue_position = 0

            active.state.blocking_mission_id = None

            active.state.queue_reason = ''

            if was_waiting and active.state.status == 'queued':

                active.proof.summary = 'Mission reached the front of the workspace queue. Resume to start.'

            active_label = active.title or active.objective or active.mission_id

            for index, queued in enumerate(waiting, start=1):

                queued.state.status = 'queued'

                queued.state.queue_position = index

                queued.state.blocking_mission_id = active.mission_id

                queued.state.queue_reason = f"Waiting for mission '{active_label}' to leave the active slot for this workspace."

                queued.proof.summary = queued.state.queue_reason

            for mission in workspace_missions:

                if _mission_releases_workspace_slot(mission):

                    mission.state.queue_position = 0

                    mission.state.blocking_mission_id = None

                    mission.state.queue_reason = ''

                elif _mission_runtime_budget_exhausted(mission):

                    mission.state.queue_position = 0

                    mission.state.blocking_mission_id = None

                    mission.state.queue_reason = 'Runtime budget exhausted. Extend or resume with a fresh budget.'


def _profile_parameter_snapshot(profile_name: str, profile) -> dict:
    if profile is None:
        return {
            "profileName": profile_name,
            "autonomyLevel": "balanced",
            "approvalStrictness": "tiered",
            "verificationCadence": "each_cycle",
            "explanationLevel": "medium",
            "explorationBreadth": "bounded",
            "autoContinueBehavior": "pause_on_failure",
            "gitActionPolicy": "approval_gated",
            "setupAutomationPolicy": "guided_install",
            "learningAggressiveness": "bounded",
            "uiDensity": "comfortable",
            "visibilityLevel": "balanced",
        }

    approval_mode = profile.agent.approval_mode or "tiered"
    pause_on_failure = (
        True
        if profile.agent.pause_on_verification_failure is None
        else bool(profile.agent.pause_on_verification_failure)
    )
    delegation = profile.agent.delegation_aggressiveness or "balanced"
    mode = profile.agent.mode or "autopilot"
    autonomy_map = {
        "fast": "guided",
        "careful": "guided",
        "autopilot": "balanced",
        "swarms": "high",
        "deep_run": "maximum",
    }
    visibility_map = {
        "beginner": "guided",
        "builder": "balanced",
        "advanced": "detailed",
        "experimental": "expert",
    }
    learning_map = {
        "low": "guarded",
        "balanced": "bounded",
        "high": "aggressive",
    }
    return {
        "profileName": profile.name,
        "autonomyLevel": autonomy_map.get(mode, "balanced"),
        "approvalStrictness": approval_mode,
        "verificationCadence": "each_cycle" if pause_on_failure else "continuous_until_blocked",
        "explanationLevel": profile.agent.explanation_depth or "medium",
        "explorationBreadth": "wide" if (profile.agent.parallel_agents or 1) > 2 else "bounded",
        "autoContinueBehavior": "pause_on_failure" if pause_on_failure else "continue_until_blocked",
        "gitActionPolicy": "profile_resolved" if approval_mode == "hands_free" else "approval_gated",
        "setupAutomationPolicy": "installer_guided" if profile.name == "beginner" else "repair_and_verify",
        "learningAggressiveness": learning_map.get(delegation, "bounded"),
        "uiDensity": profile.ui.get("density", "comfortable"),
        "visibilityLevel": visibility_map.get(profile.name, "balanced"),
    }


@_control_checked('mission-loop')

def build_mission_loop_snapshot(mission: Mission) -> dict:

    plan_revisions = mission.plan_revisions or []

    latest_revision = plan_revisions[-1] if plan_revisions else None

    delegated = mission.delegated_runtime_sessions or []

    if mission.state.status in TERMINAL_MISSION_STATUSES:

        phase = 'complete'

    elif mission.state.status in {'queued', 'draft'}:

        phase = 'plan'

    elif mission.state.status == 'verification_failed':

        phase = 'replan'

    elif mission.proof.failed_checks or mission.state.verification_failures:

        phase = 'verify'

    elif any((item.status in {'launching', 'running', 'waiting_for_approval'} for item in delegated)):

        phase = 'execute'

    elif mission.state.active_step_id:

        phase = 'execute'

    elif plan_revisions:

        phase = 'verify'

    else:

        phase = 'plan'

    verification_result = 'pending'

    if mission.proof.failed_checks or mission.state.verification_failures:

        verification_result = 'failed'

    elif mission.proof.passed_checks:

        verification_result = 'passed'

    continuity_state, continuity_detail = _continuity_state_for_mission(mission, delegated)

    time_budget = _time_budget_snapshot_for_mission(mission)

    last_replan_reason = _plan_revision_value(latest_revision, 'trigger') or str(mission.state.last_replan_reason or '')

    last_replan_trigger = _plan_revision_value(latest_revision, 'trigger') or str(mission.state.last_replan_trigger or '')

    return {'currentCyclePhase': phase, 'cycleCount': len(plan_revisions) or (1 if mission.state.status != 'draft' else 0), 'lastVerificationResult': verification_result, 'lastVerificationSummary': _verification_summary_for_mission(mission, verification_result), 'lastReplanReason': last_replan_reason, 'lastReplanTrigger': last_replan_trigger, 'improvementQueue': [{'title': item.get('title', ''), 'priority': item.get('priority', 'medium')} if isinstance(item, dict) else {'title': getattr(item, 'title', ''), 'priority': getattr(item, 'priority', 'medium')} for item in mission.improvement_queue], 'resumeReady': bool(mission.state.latest_session_id), 'continuityState': continuity_state, 'continuityDetail': continuity_detail, 'approvalHistoryCount': len(mission.state.approval_history), 'pauseReason': time_budget['lastPauseReason'], 'currentRuntimeLane': _current_runtime_lane_for_mission(mission, delegated), 'timeBudget': time_budget, 'contextWindow': {'usedTokens': mission.state.context_used_tokens, 'usageRatio': mission.state.context_usage_ratio, 'status': mission.state.context_status, 'handoffCount': mission.state.handoff_count, 'lastHandoffReason': mission.state.last_handoff_reason}, 'runtimeAutonomy': _runtime_autonomy_for_mission(mission), 'routeChangeCount': mission.state.route_change_count, 'parallelAgents': mission.state.parallel_agents, 'observationCount': mission.state.observation_count, 'mergePolicy': mission.state.merge_policy, 'crossMissionAwareness': mission.state.cross_mission_awareness, 'blocker': {} if mission.state.status in TERMINAL_MISSION_STATUSES else mission.state.blocker_classification, 'providerTruth': mission.state.provider_runtime_truth, 'codeExecution': mission.state.code_execution}


def sync_mission_state_snapshot(mission: Mission) -> dict:
    if _operator_completed_hard_artifact_gate_passed(mission):
        _apply_operator_completed_terminal_state(mission)
    if (
        mission.state.status == "verification_failed"
        and (
            HARD_ARTIFACT_GATE_CHECK_ID in mission.state.verification_failures
            or HARD_ARTIFACT_GATE_FAILURE in mission.state.verification_failures
            or HARD_ARTIFACT_GATE_FAILURE in mission.proof.failed_checks
            or mission.state.stop_reason == "artifact_gate_failed"
        )
    ):
        gate = mission_hard_artifact_gate(mission)
        if bool(gate.get("passed")):
            _clear_repaired_hard_artifact_gate_failure(mission)
            mission.state.status = "completed"
            mission.state.last_verification_result = "passed"
            mission.state.planner_loop_status = "completed"
            mission.proof.summary = "Mission completed with proof artifacts."
    if mission.state.status == "completed":
        gate = _apply_hard_artifact_gate_if_completed(mission)
        if bool(gate.get("required", True)) and not bool(gate.get("passed")):
            _sync_execution_scope_snapshot(mission)
            mission_loop = build_mission_loop_snapshot(mission)
            mission.state.current_cycle_phase = mission_loop["currentCyclePhase"]
            mission.state.cycle_count = mission_loop["cycleCount"]
            mission.state.last_verification_result = mission_loop["lastVerificationResult"]
            mission.state.last_replan_reason = mission_loop["lastReplanReason"]
            mission.state.last_verification_summary = mission_loop["lastVerificationSummary"]
            mission.state.last_replan_trigger = mission_loop["lastReplanTrigger"]
            mission.state.continuity_state = mission_loop["continuityState"]
            mission.state.continuity_detail = mission_loop["continuityDetail"]
            mission.state.elapsed_runtime_seconds = mission_loop["timeBudget"]["elapsedSeconds"]
            mission.state.remaining_runtime_seconds = mission_loop["timeBudget"]["remainingSeconds"]
            mission.state.time_budget_status = mission_loop["timeBudget"]["status"]
            mission.state.last_budget_pause_reason = mission_loop["timeBudget"]["lastPauseReason"]
            mission.state.current_runtime_lane = mission_loop["currentRuntimeLane"]
            mission.state.runtime_autonomy = mission_loop.get("runtimeAutonomy", {})
            mission.state.blocker_classification = mission_loop.get("blocker", {})
            mission.state.provider_runtime_truth = mission_loop.get("providerTruth", {})
            mission.state.code_execution = mission_loop.get("codeExecution", {})
            return mission_loop
        mission.state.last_runtime_event = "completed"
        mission.state.last_error = None
        mission.state.stop_reason = None
        mission.state.planner_loop_status = "completed"
        mission.state.pending_mutating_actions = 0
        mission.state.pending_approval_payload = {}
        mission.proof.pending_approvals = []
        if _completion_summary_needs_replacement(mission.proof.summary):
            mission.proof.summary = "Mission completed with proof artifacts."
    _sync_execution_scope_snapshot(mission)
    mission_loop = build_mission_loop_snapshot(mission)
    mission.state.current_cycle_phase = mission_loop["currentCyclePhase"]
    mission.state.cycle_count = mission_loop["cycleCount"]
    mission.state.last_verification_result = mission_loop["lastVerificationResult"]
    mission.state.last_replan_reason = mission_loop["lastReplanReason"]
    mission.state.last_verification_summary = mission_loop["lastVerificationSummary"]
    mission.state.last_replan_trigger = mission_loop["lastReplanTrigger"]
    mission.state.continuity_state = mission_loop["continuityState"]
    mission.state.continuity_detail = mission_loop["continuityDetail"]
    mission.state.elapsed_runtime_seconds = mission_loop["timeBudget"]["elapsedSeconds"]
    mission.state.remaining_runtime_seconds = mission_loop["timeBudget"]["remainingSeconds"]
    mission.state.time_budget_status = mission_loop["timeBudget"]["status"]
    mission.state.last_budget_pause_reason = mission_loop["timeBudget"]["lastPauseReason"]
    mission.state.current_runtime_lane = mission_loop["currentRuntimeLane"]
    mission.state.runtime_autonomy = mission_loop.get("runtimeAutonomy", {})
    mission.state.blocker_classification = mission_loop.get("blocker", {})
    mission.state.provider_runtime_truth = mission_loop.get("providerTruth", {})
    mission.state.code_execution = mission_loop.get("codeExecution", {})
    return mission_loop


def _operator_completed_hard_artifact_gate_passed(mission: Mission) -> bool:
    feedback = (
        mission.state.operator_value_feedback
        if isinstance(mission.state.operator_value_feedback, dict)
        else {}
    )
    if str(feedback.get("source") or "") != "mission_action_complete":
        return False
    gate = mission_hard_artifact_gate(mission)
    return not bool(gate.get("required", True)) or bool(gate.get("passed"))


def _apply_operator_completed_terminal_state(mission: Mission) -> None:
    mission.state.status = "completed"
    mission.state.last_runtime_event = "completed"
    mission.state.last_error = None
    mission.state.stop_reason = None
    mission.state.planner_loop_status = "completed"
    mission.state.pending_mutating_actions = 0
    mission.state.pending_approval_payload = {}
    mission.proof.pending_approvals = []
    if _completion_summary_needs_replacement(mission.proof.summary):
        feedback = (
            mission.state.operator_value_feedback
            if isinstance(mission.state.operator_value_feedback, dict)
            else {}
        )
        score = feedback.get("score")
        mission.proof.summary = (
            f"Mission marked complete by operator with {score} value score."
            if score is not None
            else "Mission marked complete by operator."
        )


def _sync_execution_scope_snapshot(mission: Mission) -> None:
    truth = derive_execution_target(
        execution_root=mission.execution_scope.execution_root,
        workspace_root=mission.execution_scope.workspace_root,
        strategy=mission.execution_scope.strategy,
    )
    mission.execution_scope.execution_target = truth["execution_target"]
    mission.execution_scope.storage_mode = truth["storage_mode"]
    mission.execution_scope.host_locality = truth["host_locality"]
    mission.execution_scope.execution_target_detail = truth["execution_target_detail"]
    mission.state.execution_scope = asdict(mission.execution_scope)


def _runtime_autonomy_for_mission(mission: Mission) -> dict[str, Any]:
    if mission.state.status not in TERMINAL_MISSION_STATUSES:
        return mission.state.runtime_autonomy
    autonomy = dict(mission.state.runtime_autonomy or {})
    autonomy.update(
        {
            "policy": "terminal",
            "reason": "Mission is terminal; stale delegated runtime failures are retained only as history.",
            "delegatedStatus": "idle",
            "changed": False,
        }
    )
    return autonomy


def _plan_revision_value(revision: object, key: str) -> str:
    if revision is None:
        return ""
    if isinstance(revision, dict):
        return str(revision.get(key, "") or "")
    return str(getattr(revision, key, "") or "")


def _provider_auth_presence_cache_key() -> tuple[tuple[str, str], ...]:
    rows = [
        (name, str(os.environ.get(name, "")))
        for name in {
            *PROVIDER_ENV_HINTS.values(),
            "CODEX_HOME",
            "FLUXIO_DISABLE_WSL_AUTH_DISCOVERY",
            "FLUXIO_PROVIDER_ENV_FILE",
            "FLUXIO_MINIMAX_OPENCLAW_OAUTH_PRESENT",
            "FLUXIO_OPENAI_CODEX_OAUTH_PRESENT",
            "FLUXIO_RUNTIME_HOME",
            "HERMES_AUTH_STORE",
            "HERMES_HOME",
            "HOME",
            "OPENCLAW_STATE_DIR",
            "SYNTELOS_RUNTIME_HOME",
        }
    ]
    for path in _provider_env_file_candidates():
        try:
            stat = path.stat()
            fingerprint = f"{stat.st_mtime_ns}:{stat.st_size}"
        except OSError:
            fingerprint = "missing"
        rows.append((f"provider-env-file:{path}", fingerprint))
    return tuple(sorted(rows))


def _provider_auth_presence_from_env_files() -> dict[str, bool]:
    presence: dict[str, bool] = {}
    provider_env_values = _provider_env_file_values()
    for provider_id, env_name in PROVIDER_ENV_HINTS.items():
        presence[provider_id] = bool(
            str(os.environ.get(env_name, "")).strip()
            or str(provider_env_values.get(env_name, "")).strip()
        )
    if str(os.environ.get("FLUXIO_OPENAI_CODEX_OAUTH_PRESENT", "")).strip() or str(
        provider_env_values.get("FLUXIO_OPENAI_CODEX_OAUTH_PRESENT", "")
    ).strip():
        presence["openai-codex"] = True
    if str(os.environ.get("FLUXIO_MINIMAX_OPENCLAW_OAUTH_PRESENT", "")).strip() or str(
        provider_env_values.get("FLUXIO_MINIMAX_OPENCLAW_OAUTH_PRESENT", "")
    ).strip():
        presence["minimax-portal"] = True
    return presence


def _provider_auth_presence_for_bootstrap() -> tuple[dict[str, bool], str]:
    return _provider_auth_presence_from_env_files(), "bootstrap_env_file_only"


def _deferred_bootstrap_provider_truth(provider_truth: dict, *, source: str) -> dict:
    if str(source or "") != "bootstrap_env_file_only" or bool(provider_truth.get("authPresent")):
        return provider_truth
    payload = dict(provider_truth)
    payload["authKnown"] = False
    payload["authDeferred"] = True
    payload["authSource"] = source
    payload["authPath"] = "deferred to full summary"
    route_auth = payload.get("routeAuth") if isinstance(payload.get("routeAuth"), dict) else {}
    payload["routeAuth"] = {
        provider: (
            {
                **dict(auth),
                "authKnown": False,
                "authDeferred": True,
                "authSource": source,
                "authPath": "deferred to full summary",
            }
            if isinstance(auth, dict) and not bool(auth.get("authPresent"))
            else auth
        )
        for provider, auth in route_auth.items()
    }
    return payload


def _provider_auth_presence_from_env() -> dict[str, bool]:
    global _PROVIDER_AUTH_PRESENCE_CACHE
    cache_key = _provider_auth_presence_cache_key()
    now = time.monotonic()
    with _PROVIDER_AUTH_PRESENCE_CACHE_LOCK:
        cached = _PROVIDER_AUTH_PRESENCE_CACHE
        if (
            cached
            and cached[1] == cache_key
            and now - cached[0] <= PROVIDER_AUTH_PRESENCE_CACHE_TTL_SECONDS
        ):
            return dict(cached[2])
    presence = _provider_auth_presence_from_env_files()
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    openclaw_auth_stores = _openclaw_auth_store_candidates(home)
    opencode_auth_stores = _opencode_auth_store_candidates(home)
    hermes_auth_stores = hermes_auth_store_candidates(home)
    codex_auth_stores = _codex_auth_store_candidates(home)
    minimax_oauth_stores = _minimax_oauth_store_candidates(home)
    for provider_id, aliases in PROVIDER_AUTH_ALIASES.items():
        if presence.get(provider_id, False):
            continue
        if any(
            _auth_store_has_provider(path, alias)
            for path in openclaw_auth_stores
            for alias in aliases
        ):
            presence[provider_id] = True
            continue
        if _auth_store_candidates_have_provider(hermes_auth_stores, *aliases):
            presence[provider_id] = True
            continue
        if provider_id == "opencode-go" and _auth_store_candidates_have_provider(
            opencode_auth_stores,
            "opencode-go",
            "opencodego",
            "opencode",
        ):
            presence[provider_id] = True
    if (
        any(path.exists() for path in codex_auth_stores)
        or _auth_store_candidates_have_provider(openclaw_auth_stores, "openai-codex")
        or _auth_store_candidates_have_provider(hermes_auth_stores, "openai-codex")
    ):
        presence["openai-codex"] = True
    if (
        any(path.exists() for path in minimax_oauth_stores)
        or _auth_store_candidates_have_provider(openclaw_auth_stores, "minimax-portal")
        or _auth_store_candidates_have_provider(
            hermes_auth_stores,
            "minimax-oauth",
            "minimax",
            "minimax-portal",
        )
    ):
        presence["minimax-portal"] = True
        presence["minimax-oauth"] = True
        presence["minimax"] = True
    with _PROVIDER_AUTH_PRESENCE_CACHE_LOCK:
        _PROVIDER_AUTH_PRESENCE_CACHE = (time.monotonic(), cache_key, dict(presence))
    return presence


def _openclaw_auth_store_candidates(home: Path | None = None) -> list[Path]:
    home = home or Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    candidates = [
        Path(os.environ.get("OPENCLAW_STATE_DIR", str(home / ".openclaw"))).expanduser()
        / "agents"
        / "main"
        / "agent"
        / "auth-profiles.json"
    ]
    for runtime_home in _runtime_home_candidates():
        candidates.append(
            runtime_home / ".openclaw" / "agents" / "main" / "agent" / "auth-profiles.json"
        )
    return _dedupe_paths(candidates)


def _codex_auth_store_candidates(home: Path | None = None) -> list[Path]:
    home = home or Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    candidates = [home / ".codex" / "auth.json"]
    codex_home = str(os.environ.get("CODEX_HOME") or "").strip()
    if codex_home:
        candidates.append(Path(codex_home).expanduser() / "auth.json")
    for runtime_home in _runtime_home_candidates():
        candidates.append(runtime_home / ".codex" / "auth.json")
    return _dedupe_paths(candidates)


def _opencode_auth_store_candidates(home: Path | None = None) -> list[Path]:
    home = home or Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    candidates = [
        home / ".local" / "share" / "opencode" / "auth.json",
        home / "AppData" / "Local" / "opencode" / "auth.json",
        home / "AppData" / "Roaming" / "opencode" / "auth.json",
    ]
    for runtime_home in _runtime_home_candidates():
        candidates.append(runtime_home / ".local" / "share" / "opencode" / "auth.json")
        candidates.append(runtime_home / "opencode" / "auth.json")
    return _dedupe_paths(candidates)


def _minimax_oauth_store_candidates(home: Path | None = None) -> list[Path]:
    home = home or Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    candidates = [home / ".minimax" / "oauth_creds.json"]
    for runtime_home in _runtime_home_candidates():
        candidates.append(runtime_home / ".minimax" / "oauth_creds.json")
    return _dedupe_paths(candidates)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _provider_env_file_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for path in _provider_env_file_candidates():
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            parsed = _parse_provider_env_line(line)
            if not parsed:
                continue
            key, value = parsed
            if key in {
                "OPENAI_API_KEY",
                "ANTHROPIC_API_KEY",
                "OPENROUTER_API_KEY",
                "MINIMAX_API_KEY",
                "MINIMAX_OAUTH_TOKEN",
                "OPENCODE_API_KEY",
                "FLUXIO_OPENAI_CODEX_OAUTH_PRESENT",
                "FLUXIO_MINIMAX_OPENCLAW_OAUTH_PRESENT",
            } and value:
                values[key] = value
    return values


def _provider_env_file_candidates() -> list[Path]:
    candidates: list[Path] = []
    explicit = str(os.environ.get("FLUXIO_PROVIDER_ENV_FILE") or "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    for env_name in ("FLUXIO_RUNTIME_HOME", "SYNTELOS_RUNTIME_HOME", "HOME"):
        value = str(os.environ.get(env_name) or "").strip()
        if value:
            candidates.append(Path(value).expanduser() / ".fluxio_provider_env")
    try:
        cwd = Path.cwd().resolve()
    except OSError:
        cwd = Path.cwd()
    parts = cwd.parts
    if "releases" in parts:
        release_index = parts.index("releases")
        if release_index >= 1:
            base = Path(*parts[:release_index])
            candidates.append(base / "runtime" / "home" / ".fluxio_provider_env")
    candidates.append(platform_config().nas_projects_root / "syntelos" / "runtime" / "home" / ".fluxio_provider_env")
    return _dedupe_paths(candidates)


def _parse_provider_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()
    if "=" not in stripped:
        return None
    key, raw_value = stripped.split("=", 1)
    key = key.strip()
    if not re.fullmatch(r"[A-Z0-9_]+", key):
        return None
    try:
        tokens = shlex.split(raw_value, posix=True)
    except ValueError:
        value = raw_value.strip().strip("\"'")
    else:
        value = tokens[0] if tokens else ""
    return key, value


def _route_role_for_phase(phase: str) -> str:
    normalized = str(phase or "execute").strip().lower()
    if normalized in {"plan", "replan"}:
        return "planner"
    if normalized == "verify":
        return "verifier"
    return "executor"


def _route_rows_for_mission(mission: Mission) -> list[dict]:
    effective_contract = (
        mission.effective_route_contract
        if mission.effective_route_contract
        else _effective_route_contract_for_mission(mission)
    )
    rows = effective_contract.get("roles", [])
    if not isinstance(rows, list):
        return []
    normalized: list[dict] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        role = normalize_route_role(item.get("role", ""))
        if role not in ROUTE_OVERRIDE_ROLES:
            continue
        normalized.append(
            {
                "role": role,
                "provider": str(item.get("provider", "")).strip().lower(),
                "model": str(item.get("model", "")).strip(),
                "effort": str(item.get("effort", "")).strip().lower(),
                "budgetClass": str(
                    item.get("budgetClass", item.get("budget_class", ""))
                ).strip(),
                "source": str(item.get("source", "")).strip(),
                "reason": str(item.get("reason", "")).strip(),
            }
        )
    return normalized


def _path_has_syncable_files(root: Path) -> bool:
    if not root.exists() or not root.is_dir():
        return False
    for current_root, dir_names, file_names in os.walk(root):
        dir_names[:] = [name for name in dir_names if name not in SYNC_EXCLUDED_DIRS]
        if any(file_name not in SYNC_EXCLUDED_FILES for file_name in file_names):
            return True
    return False


def _sync_local_and_nas_projects(
    *,
    local_root: Path | None,
    nas_root: Path,
    sync_direction: str,
    conflict_policy: str,
) -> dict[str, object]:
    if local_root is None:
        return {}

    requested_direction = normalize_sync_direction(sync_direction)
    effective_direction = requested_direction
    local_exists_initial = local_root.exists() and local_root.is_dir()
    nas_exists_initial = nas_root.exists() and nas_root.is_dir()
    local_has_files_initial = _path_has_syncable_files(local_root)
    nas_has_files_initial = _path_has_syncable_files(nas_root)
    direction_auto_promoted = False
    if (
        local_has_files_initial
        and nas_has_files_initial
        and effective_direction in {"local_to_nas", "nas_to_local"}
    ):
        effective_direction = "bidirectional"
        direction_auto_promoted = True
    if not nas_exists_initial:
        nas_root.mkdir(parents=True, exist_ok=True)

    passes: list[dict[str, object]] = []
    if effective_direction in {"local_to_nas", "bidirectional"} and local_exists_initial:
        status = _sync_project_tree(
            local_root,
            nas_root,
            conflict_policy=_sync_conflict_policy_for_direction(
                conflict_policy,
                direction="local_to_nas",
            ),
        )
        passes.append({"direction": "local_to_nas", **status})

    if effective_direction in {"nas_to_local", "bidirectional"}:
        if not local_root.exists():
            local_root.mkdir(parents=True, exist_ok=True)
        if local_root.is_dir() and nas_root.exists() and nas_root.is_dir():
            status = _sync_project_tree(
                nas_root,
                local_root,
                conflict_policy=_sync_conflict_policy_for_direction(
                    conflict_policy,
                    direction="nas_to_local",
                ),
            )
            passes.append({"direction": "nas_to_local", **status})

    files_copied = 0
    files_skipped = 0
    locked_skipped = 0
    missing_skipped = 0
    conflicts_detected = 0
    locked_samples: list[str] = []
    conflict_samples: list[dict[str, object]] = []
    conflict_receipts: list[dict[str, object]] = []
    for item in passes:
        files_copied += int(item.get("filesCopied", 0) or 0)
        files_skipped += int(item.get("filesSkipped", 0) or 0)
        locked_skipped += int(item.get("lockedFilesSkipped", 0) or 0)
        missing_skipped += int(item.get("missingFilesSkipped", 0) or 0)
        conflicts_detected += int(item.get("conflictsDetected", 0) or 0)
        for sample in item.get("lockedFileSamples", []):
            sample_text = str(sample or "").strip()
            if not sample_text or sample_text in locked_samples:
                continue
            locked_samples.append(sample_text)
            if len(locked_samples) >= SYNC_LOCKED_FILE_SAMPLE_LIMIT:
                break
        for sample in item.get("conflictSamples", []):
            if not isinstance(sample, dict):
                continue
            key = json.dumps(sample, sort_keys=True)
            if any(json.dumps(existing, sort_keys=True) == key for existing in conflict_samples):
                continue
            conflict_samples.append(sample)
            if len(conflict_samples) >= SYNC_CONFLICT_SAMPLE_LIMIT:
                break
        receipt = item.get("syncReceipt")
        if isinstance(receipt, dict):
            conflict_receipts.append(receipt)

    reason = "sync_not_needed"
    if passes:
        if local_has_files_initial and nas_has_files_initial:
            reason = "detected_existing_both_synced"
        elif local_has_files_initial and not nas_has_files_initial:
            reason = "detected_local_primary_synced"
        elif nas_has_files_initial and not local_has_files_initial:
            reason = "detected_nas_primary_synced"
        else:
            reason = "synced"

    payload: dict[str, object] = {
        "synced": bool(passes),
        "reason": reason,
        "source": str(local_root),
        "target": str(nas_root),
        "localPath": str(local_root),
        "nasPath": str(nas_root),
        "localExists": local_exists_initial,
        "nasExists": nas_exists_initial,
        "localHasFiles": local_has_files_initial,
        "nasHasFiles": nas_has_files_initial,
        "detectedBothWithFiles": bool(local_has_files_initial and nas_has_files_initial),
        "requestedDirection": requested_direction,
        "effectiveDirection": effective_direction,
        "filesCopied": files_copied,
        "filesSkipped": files_skipped,
        "passes": passes,
    }
    payload["syncReceipt"] = _build_workspace_sync_receipt(
        local_root=local_root,
        nas_root=nas_root,
        requested_direction=requested_direction,
        effective_direction=effective_direction,
        conflict_policy=conflict_policy,
        passes=passes,
        files_copied=files_copied,
        files_skipped=files_skipped,
        conflicts_detected=conflicts_detected,
        conflict_receipts=conflict_receipts,
    )
    if conflicts_detected:
        payload["conflictsDetected"] = conflicts_detected
        payload["conflictSamples"] = conflict_samples
        payload["conflictReceipts"] = conflict_receipts
    if any(item.get("manualReviewRequired") for item in passes):
        payload["manualReviewRequired"] = True
    if direction_auto_promoted:
        payload["directionAutoPromoted"] = True
    if locked_skipped:
        payload["lockedFilesSkipped"] = locked_skipped
        payload["lockedFileSamples"] = locked_samples
    if missing_skipped:
        payload["missingFilesSkipped"] = missing_skipped
    return payload


def _sync_conflict_policy_for_direction(conflict_policy: str, *, direction: str) -> str:
    normalized = str(conflict_policy or "keep_newer_and_log").strip().lower()
    if direction == "nas_to_local":
        if normalized == "local_wins":
            return "nas_wins"
        if normalized == "nas_wins":
            return "local_wins"
    return normalized


def _sync_project_tree(source: Path, target: Path, *, conflict_policy: str) -> dict[str, object]:
    if not source.exists() or not source.is_dir():
        return {
            "synced": False,
            "reason": "source_missing",
            "source": str(source),
            "target": str(target),
            "filesCopied": 0,
            "filesSkipped": 0,
        }
    if source.resolve() == target.resolve():
        return {
            "synced": True,
            "reason": "same_path",
            "source": str(source),
            "target": str(target),
            "filesCopied": 0,
            "filesSkipped": 0,
        }
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    skipped = 0
    locked_skipped = 0
    missing_skipped = 0
    conflicts_detected = 0
    manual_review_required = False
    locked_samples: list[str] = []
    conflict_samples: list[dict[str, object]] = []
    for current_root, dir_names, file_names in os.walk(source):
        dir_names[:] = [name for name in dir_names if name not in SYNC_EXCLUDED_DIRS]
        relative_root = Path(current_root).relative_to(source)
        target_root = target / relative_root
        target_root.mkdir(parents=True, exist_ok=True)
        for file_name in file_names:
            if file_name in SYNC_EXCLUDED_FILES:
                skipped += 1
                continue
            source_file = Path(current_root) / file_name
            target_file = target_root / file_name
            if target_file.exists():
                conflict_sample: dict[str, object] | None = None
                if _sync_files_conflict(source_file, target_file):
                    conflicts_detected += 1
                    conflict_sample = _sync_conflict_sample(
                        source_file=source_file,
                        target_file=target_file,
                        source_root=source,
                        conflict_policy=conflict_policy,
                    )
                    if len(conflict_samples) < SYNC_CONFLICT_SAMPLE_LIMIT:
                        conflict_samples.append(conflict_sample)
                if conflict_policy == "local_wins":
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    copy_result = _copy_project_file_with_retry(source_file, target_file)
                    if copy_result == "copied":
                        copied += 1
                        continue
                    skipped += 1
                    if copy_result == "locked":
                        locked_skipped += 1
                        if len(locked_samples) < SYNC_LOCKED_FILE_SAMPLE_LIMIT:
                            locked_samples.append(str(source_file))
                        continue
                    if copy_result == "missing":
                        missing_skipped += 1
                        continue
                elif conflict_policy == "nas_wins":
                    skipped += 1
                    continue
                elif conflict_policy == "manual_review":
                    manual_review_required = bool(conflict_sample)
                    skipped += 1
                    continue
                try:
                    target_mtime = target_file.stat().st_mtime
                    source_mtime = source_file.stat().st_mtime
                except FileNotFoundError:
                    skipped += 1
                    missing_skipped += 1
                    continue
                except OSError as exc:
                    if _is_locked_copy_error(exc):
                        skipped += 1
                        locked_skipped += 1
                        if len(locked_samples) < SYNC_LOCKED_FILE_SAMPLE_LIMIT:
                            locked_samples.append(str(source_file))
                        continue
                    raise
                if target_mtime >= source_mtime:
                    skipped += 1
                    continue
            target_file.parent.mkdir(parents=True, exist_ok=True)
            copy_result = _copy_project_file_with_retry(source_file, target_file)
            if copy_result == "copied":
                copied += 1
                continue
            skipped += 1
            if copy_result == "locked":
                locked_skipped += 1
                if len(locked_samples) < SYNC_LOCKED_FILE_SAMPLE_LIMIT:
                    locked_samples.append(str(source_file))
                continue
            if copy_result == "missing":
                missing_skipped += 1
                continue
    payload = {
        "synced": True,
        "reason": "copied",
        "source": str(source),
        "target": str(target),
        "filesCopied": copied,
        "filesSkipped": skipped,
    }
    payload["syncReceipt"] = _build_sync_pass_receipt(
        source=source,
        target=target,
        conflict_policy=conflict_policy,
        files_copied=copied,
        files_skipped=skipped,
        conflicts_detected=conflicts_detected,
        manual_review_required=manual_review_required,
        conflict_samples=conflict_samples,
    )
    if conflicts_detected:
        payload["conflictsDetected"] = conflicts_detected
        payload["conflictSamples"] = conflict_samples
        if manual_review_required:
            payload["reason"] = "manual_review_required"
            payload["manualReviewRequired"] = True
    if locked_skipped:
        payload["reason"] = "copied_with_locked_files"
        payload["lockedFilesSkipped"] = locked_skipped
        payload["lockedFileSamples"] = locked_samples
    if missing_skipped:
        payload["missingFilesSkipped"] = missing_skipped
    return payload


def _sync_files_conflict(source_file: Path, target_file: Path) -> bool:
    try:
        source_stat = source_file.stat()
        target_stat = target_file.stat()
    except OSError:
        return True
    if source_stat.st_size != target_stat.st_size:
        return True
    return abs(source_stat.st_mtime - target_stat.st_mtime) > 1e-6


def _sync_conflict_sample(
    *,
    source_file: Path,
    target_file: Path,
    source_root: Path,
    conflict_policy: str,
) -> dict[str, object]:
    try:
        relative_path = str(source_file.relative_to(source_root))
    except ValueError:
        relative_path = source_file.name
    try:
        source_mtime = source_file.stat().st_mtime
    except OSError:
        source_mtime = 0.0
    try:
        target_mtime = target_file.stat().st_mtime
    except OSError:
        target_mtime = 0.0
    resolution = "manual_review_required"
    if conflict_policy == "local_wins":
        resolution = "source_overwrites_target"
    elif conflict_policy == "nas_wins":
        resolution = "target_kept"
    elif conflict_policy == "keep_newer_and_log":
        resolution = "source_newer_copied" if source_mtime > target_mtime else "target_newer_kept"
    return {
        "relativePath": relative_path,
        "sourcePath": str(source_file),
        "targetPath": str(target_file),
        "sourceMtime": source_mtime,
        "targetMtime": target_mtime,
        "policy": conflict_policy,
        "resolution": resolution,
    }


def _build_sync_pass_receipt(
    *,
    source: Path,
    target: Path,
    conflict_policy: str,
    files_copied: int,
    files_skipped: int,
    conflicts_detected: int,
    manual_review_required: bool,
    conflict_samples: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema": "fluxio.sync_conflict_receipt.v1",
        "receiptId": f"sync_pass_{uuid.uuid4().hex[:10]}",
        "generatedAt": utc_now_iso(),
        "source": str(source),
        "target": str(target),
        "conflictPolicy": conflict_policy,
        "filesCopied": files_copied,
        "filesSkipped": files_skipped,
        "conflictsDetected": conflicts_detected,
        "manualReviewRequired": bool(manual_review_required),
        "conflictSamples": conflict_samples[:SYNC_CONFLICT_SAMPLE_LIMIT],
    }


def _build_workspace_sync_receipt(
    *,
    local_root: Path,
    nas_root: Path,
    requested_direction: str,
    effective_direction: str,
    conflict_policy: str,
    passes: list[dict[str, object]],
    files_copied: int,
    files_skipped: int,
    conflicts_detected: int,
    conflict_receipts: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema": "fluxio.workspace_sync_receipt.v1",
        "receiptId": f"sync_tx_{uuid.uuid4().hex[:10]}",
        "generatedAt": utc_now_iso(),
        "localPath": str(local_root),
        "nasPath": str(nas_root),
        "requestedDirection": requested_direction,
        "effectiveDirection": effective_direction,
        "conflictPolicy": conflict_policy,
        "passCount": len(passes),
        "filesCopied": files_copied,
        "filesSkipped": files_skipped,
        "conflictsDetected": conflicts_detected,
        "manualReviewRequired": any(item.get("manualReviewRequired") for item in passes),
        "passReceiptIds": [
            str(item.get("receiptId", ""))
            for item in conflict_receipts
            if item.get("receiptId")
        ],
    }


def _workspace_sync_status(workspace: WorkspaceProfile) -> dict[str, object]:
    for entry in workspace.goals or []:
        raw = str(entry or "")
        if not raw.startswith("sync_status:"):
            continue
        try:
            payload = json.loads(raw.split(":", 1)[1])
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def _cross_device_launch_receipts_path(root: Path) -> Path:
    return root / ".agent_control" / "cross_device_launch_rehearsals" / "receipts.jsonl"


def _latest_cross_device_launch_receipt(root: Path, workspace_id: str) -> dict[str, object]:
    history = _cross_device_launch_receipt_history(root, workspace_id=workspace_id, limit=1)
    return history[0] if history else {}


def _cross_device_launch_receipt_history(
    root: Path,
    *,
    workspace_id: str = "",
    limit: int = 20,
) -> list[dict[str, object]]:
    path = _cross_device_launch_receipts_path(root)
    if not path.exists():
        return []
    read_limit = max(100, int(limit or 1) * 12)
    rows = _read_text_tail_lines(path, limit=read_limit)
    receipts: list[dict[str, object]] = []
    for line in rows:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if row.get("schema") != "fluxio.cross_device_launch_rehearsal_receipt.v1":
            continue
        if workspace_id and str(row.get("workspaceId") or "") != workspace_id:
            continue
        receipts.append(row)
    receipts.sort(key=lambda item: str(item.get("generatedAt") or ""), reverse=True)
    return receipts[: max(1, int(limit or 1))]


def _cross_device_launch_receipt_summary(root: Path) -> dict[str, object]:
    history = _cross_device_launch_receipt_history(root, limit=100)
    status_counts: dict[str, int] = {}
    workspace_ids: set[str] = set()
    mission_ids: set[str] = set()
    for receipt in history:
        status = str(receipt.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        workspace_id = str(receipt.get("workspaceId") or "")
        mission_id = str(receipt.get("missionId") or "")
        if workspace_id:
            workspace_ids.add(workspace_id)
        if mission_id:
            mission_ids.add(mission_id)
    latest = history[0] if history else {}
    launched_statuses = {"launched", "launched_with_review_items"}
    return {
        "schema": "fluxio.cross_device_launch_rehearsal_receipt_summary.v1",
        "receiptCount": len(history),
        "launchedReceiptCount": sum(
            1 for receipt in history if receipt.get("status") in launched_statuses
        ),
        "workspaceCount": len(workspace_ids),
        "missionCount": len(mission_ids),
        "statusCounts": status_counts,
        "latestReceiptId": str(latest.get("receiptId") or ""),
        "latestGeneratedAt": str(latest.get("generatedAt") or ""),
        "trendStatus": "repeated" if len(history) >= 2 else "single" if history else "empty",
        "nextAction": (
            "Keep repeating launch rehearsal receipts across more project pairs."
            if len(history) >= 2
            else "Record at least one more launch rehearsal receipt to prove the path over time."
            if history
            else "Record the first launch rehearsal receipt from a real mission launch."
        ),
    }


def record_cross_device_launch_rehearsal_receipt(
    *,
    store: ControlRoomStore,
    workspace_id: str,
    mission_id: str = "",
    require_ready: bool = True,
) -> dict[str, object]:
    snapshot = store.build_summary_snapshot()
    progress = snapshot.get("projectProgressHistory", {})
    projects = progress.get("projects", []) if isinstance(progress, dict) else []
    project = next(
        (
            item
            for item in projects
            if isinstance(item, dict) and str(item.get("workspaceId") or "") == workspace_id
        ),
        {},
    )
    if not project:
        raise ValueError(f"Unknown workspace id for launch rehearsal: {workspace_id}")
    rehearsal = project.get("launchRehearsal", {})
    if not isinstance(rehearsal, dict) or rehearsal.get("schema") != "fluxio.cross_device_launch_rehearsal.v1":
        raise ValueError(f"Workspace has no cross-device launch rehearsal: {workspace_id}")
    safe_to_launch = bool(rehearsal.get("safeToLaunch"))
    mission = store.get_mission(mission_id) if mission_id else None
    if mission_id and mission is None:
        raise ValueError(f"Unknown mission id for rehearsal receipt: {mission_id}")
    if require_ready and not safe_to_launch and not mission:
        raise ValueError(
            "Cross-device launch rehearsal is not ready; resolve blocked checks before recording a launch receipt."
        )
    receipt_status = (
        "launched"
        if mission and safe_to_launch
        else "launched_with_review_items"
        if mission
        else "ready_recorded"
        if safe_to_launch
        else "review_recorded"
    )
    receipt = {
        "schema": "fluxio.cross_device_launch_rehearsal_receipt.v1",
        "receiptId": f"cross_launch_{uuid.uuid4().hex[:10]}",
        "generatedAt": utc_now_iso(),
        "workspaceId": workspace_id,
        "workspaceName": str(project.get("workspaceName") or ""),
        "missionId": mission.mission_id if mission else "",
        "missionTitle": (mission.title or mission.objective) if mission else "",
        "status": receipt_status,
        "rehearsalStatus": str(rehearsal.get("status") or ""),
        "safeToLaunch": safe_to_launch,
        "blockedCheckIds": list(rehearsal.get("blockedCheckIds") or []),
        "checklist": list(rehearsal.get("checklist") or []),
        "recommendedRuntime": str(rehearsal.get("recommendedRuntime") or ""),
        "urlPath": str(rehearsal.get("urlPath") or ""),
        "cliCommand": str(rehearsal.get("cliCommand") or ""),
        "syncAuthority": project.get("syncAuthority", {}),
        "scheduleRecommendation": project.get("scheduleRecommendation", {}),
        "nextAction": (
            "Receipt archived for a real mission launched from the cross-device rehearsal path."
            if mission and safe_to_launch
            else "Receipt archived for a real mission, with rehearsal review items still visible."
            if mission
            else "Receipt archived for a ready cross-device launch rehearsal."
            if safe_to_launch
            else "Receipt archived for review-only rehearsal evidence."
        ),
    }
    path = _cross_device_launch_receipts_path(store.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, sort_keys=True) + "\n")
    latest_path = path.parent / "latest.json"
    latest_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


def _safe_sync_child_path(base: Path, relative_path: str) -> Path:
    clean_relative = str(relative_path or "").strip().replace("\\", "/")
    if not clean_relative or clean_relative.startswith("/") or "://" in clean_relative:
        raise ValueError("Conflict resolution requires a relative project path.")
    candidate = (base / clean_relative).resolve()
    if not candidate.is_relative_to(base.resolve()):
        raise ValueError("Conflict path must stay inside the workspace sync roots.")
    return candidate


def _resolution_copy(source: Path, target: Path) -> tuple[str, bool, str]:
    if not source.exists() or not source.is_file():
        return "error", False, "source_missing"
    target.parent.mkdir(parents=True, exist_ok=True)
    result = _copy_project_file_with_retry(source, target)
    if result == "copied":
        return "resolved", True, ""
    return "error", False, result


def _append_sync_conflict_resolution_goal(
    store: ControlRoomStore,
    workspace: WorkspaceProfile,
    receipt: dict[str, object],
) -> None:
    workspaces = store.load_workspaces()
    for item in workspaces:
        if item.workspace_id != workspace.workspace_id:
            continue
        prior = [
            entry
            for entry in item.goals
            if not str(entry).startswith("sync_conflict_resolution:")
        ][-20:]
        resolution_entries = [
            entry
            for entry in item.goals
            if str(entry).startswith("sync_conflict_resolution:")
        ][-11:]
        item.goals = [
            *prior,
            *resolution_entries,
            f"sync_conflict_resolution:{json.dumps(receipt, sort_keys=True)}",
        ]
        item.updated_at = utc_now_iso()
        store.save_workspaces(workspaces)
        return


def _append_sync_conflict_batch_resolution_goal(
    store: ControlRoomStore,
    workspace: WorkspaceProfile,
    receipt: dict[str, object],
) -> None:
    workspaces = store.load_workspaces()
    for item in workspaces:
        if item.workspace_id != workspace.workspace_id:
            continue
        prior = [
            entry
            for entry in item.goals
            if not str(entry).startswith("sync_conflict_batch_resolution:")
        ][-20:]
        batch_entries = [
            entry
            for entry in item.goals
            if str(entry).startswith("sync_conflict_batch_resolution:")
        ][-5:]
        item.goals = [
            *prior,
            *batch_entries,
            f"sync_conflict_batch_resolution:{json.dumps(receipt, sort_keys=True)}",
        ]
        item.updated_at = utc_now_iso()
        store.save_workspaces(workspaces)
        return


def resolve_workspace_sync_conflict(
    *,
    store: ControlRoomStore,
    workspace_id: str,
    relative_path: str,
    resolution: str,
) -> dict[str, object]:
    workspace = next(
        (item for item in store.load_workspaces() if item.workspace_id == workspace_id),
        None,
    )
    if workspace is None:
        raise ValueError(f"Unknown workspace: {workspace_id}")
    local_root_text = str(workspace.local_project_path or "").strip()
    nas_root_text = str(workspace.nas_project_path or workspace.root_path or "").strip()
    if not local_root_text or not nas_root_text:
        raise ValueError("Workspace needs both local_project_path and nas_project_path for conflict resolution.")
    local_root = Path(local_root_text).expanduser().resolve()
    nas_root = Path(nas_root_text).expanduser().resolve()
    local_file = _safe_sync_child_path(local_root, relative_path)
    nas_file = _safe_sync_child_path(nas_root, relative_path)
    normalized_resolution = str(resolution or "").strip().lower()
    status = "resolved"
    copied = False
    source_path = ""
    target_path = ""
    error = ""

    if normalized_resolution == "local_wins":
        source_path = str(local_file)
        target_path = str(nas_file)
        status, copied, error = _resolution_copy(local_file, nas_file)
    elif normalized_resolution == "nas_wins":
        source_path = str(nas_file)
        target_path = str(local_file)
        status, copied, error = _resolution_copy(nas_file, local_file)
    elif normalized_resolution == "keep_newer":
        if local_file.exists() and nas_file.exists():
            source = local_file if local_file.stat().st_mtime >= nas_file.stat().st_mtime else nas_file
            target = nas_file if source == local_file else local_file
            source_path = str(source)
            target_path = str(target)
            status, copied, error = _resolution_copy(source, target)
        elif local_file.exists():
            source_path = str(local_file)
            target_path = str(nas_file)
            status, copied, error = _resolution_copy(local_file, nas_file)
        elif nas_file.exists():
            source_path = str(nas_file)
            target_path = str(local_file)
            status, copied, error = _resolution_copy(nas_file, local_file)
        else:
            status = "error"
            error = "both_files_missing"
    elif normalized_resolution == "manual_review":
        status = "manual_review_recorded"
    else:
        raise ValueError("Resolution must be local_wins, nas_wins, keep_newer, or manual_review.")

    sync_status = _workspace_sync_status(workspace)
    receipt = {
        "schema": "fluxio.sync_conflict_resolution_receipt.v1",
        "receiptId": f"sync_resolve_{uuid.uuid4().hex[:10]}",
        "generatedAt": utc_now_iso(),
        "workspaceId": workspace.workspace_id,
        "workspaceName": workspace.name,
        "relativePath": str(relative_path).replace("\\", "/"),
        "resolution": normalized_resolution,
        "status": status,
        "copied": copied,
        "sourcePath": source_path,
        "targetPath": target_path,
        "localPath": str(local_file),
        "nasPath": str(nas_file),
        "error": error,
        "previousSyncReceiptId": str(
            (sync_status.get("syncReceipt") or {}).get("receiptId", "")
            if isinstance(sync_status.get("syncReceipt"), dict)
            else ""
        ),
        "nextAction": (
            "Re-run project sync or launch the waiting mission now that this conflict is resolved."
            if status == "resolved"
            else "Open both files and choose local_wins, nas_wins, or keep_newer."
            if status == "manual_review_recorded"
            else "Fix the conflict resolution error, then retry."
        ),
    }
    _append_sync_conflict_resolution_goal(store, workspace, receipt)
    return receipt


def resolve_workspace_sync_conflict_batch(
    *,
    store: ControlRoomStore,
    workspace_id: str,
    relative_paths: list[str],
    resolution: str,
) -> dict[str, object]:
    workspace = next(
        (item for item in store.load_workspaces() if item.workspace_id == workspace_id),
        None,
    )
    if workspace is None:
        raise ValueError(f"Unknown workspace: {workspace_id}")
    normalized_resolution = str(resolution or "").strip().lower()
    if normalized_resolution not in {"local_wins", "nas_wins", "keep_newer", "manual_review"}:
        raise ValueError("Resolution must be local_wins, nas_wins, keep_newer, or manual_review.")

    unique_paths: list[str] = []
    seen: set[str] = set()
    for value in relative_paths or []:
        normalized = str(value or "").strip().replace("\\", "/")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_paths.append(normalized)
    if not unique_paths:
        raise ValueError("Batch conflict resolution requires at least one relative path.")

    receipts: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    for relative_path in unique_paths:
        try:
            receipt = resolve_workspace_sync_conflict(
                store=store,
                workspace_id=workspace_id,
                relative_path=relative_path,
                resolution=normalized_resolution,
            )
        except ValueError as exc:
            errors.append(
                {
                    "relativePath": relative_path,
                    "status": "error",
                    "error": str(exc),
                }
            )
            continue
        receipts.append(receipt)
        if receipt.get("status") == "error":
            errors.append(
                {
                    "relativePath": relative_path,
                    "status": receipt.get("status"),
                    "error": receipt.get("error") or "resolution_error",
                    "receiptId": receipt.get("receiptId"),
                }
            )

    resolved_count = sum(1 for item in receipts if item.get("status") == "resolved")
    manual_review_count = sum(1 for item in receipts if item.get("status") == "manual_review_recorded")
    error_count = len(errors)
    status = "resolved" if resolved_count == len(unique_paths) else ("partial" if receipts else "error")
    if manual_review_count and not error_count and resolved_count == 0:
        status = "manual_review_recorded"
    elif error_count:
        status = "partial" if receipts else "error"

    batch_receipt = {
        "schema": "fluxio.sync_conflict_batch_resolution_receipt.v1",
        "receiptId": f"sync_batch_{uuid.uuid4().hex[:10]}",
        "generatedAt": utc_now_iso(),
        "workspaceId": workspace.workspace_id,
        "workspaceName": workspace.name,
        "resolution": normalized_resolution,
        "requestedCount": len(unique_paths),
        "resolvedCount": resolved_count,
        "manualReviewCount": manual_review_count,
        "errorCount": error_count,
        "status": status,
        "relativePaths": unique_paths,
        "receiptIds": [str(item.get("receiptId") or "") for item in receipts if item.get("receiptId")],
        "receipts": receipts,
        "errors": errors,
        "nextAction": (
            "Re-run project sync or resume waiting missions now that the batch conflicts are resolved."
            if status == "resolved"
            else "Open the unresolved paths and retry the failed conflict resolutions."
            if error_count
            else "Review the recorded manual-review batch before choosing a write direction."
        ),
    }
    _append_sync_conflict_batch_resolution_goal(store, workspace, batch_receipt)
    return batch_receipt


def _copy_project_file_with_retry(source_file: Path, target_file: Path) -> str:
    for attempt in range(SYNC_COPY_RETRY_ATTEMPTS):
        try:
            shutil.copy2(source_file, target_file)
            return "copied"
        except FileNotFoundError:
            return "missing"
        except OSError as exc:
            if not _is_locked_copy_error(exc):
                raise
            if attempt >= SYNC_COPY_RETRY_ATTEMPTS - 1:
                return "locked"
            time.sleep(SYNC_COPY_RETRY_BASE_DELAY_SECONDS * (attempt + 1))
    return "locked"


def _is_locked_copy_error(error: OSError) -> bool:
    winerror = getattr(error, "winerror", None)
    if winerror in {32, 33}:
        return True
    if error.errno in {EBUSY, ETXTBSY}:
        return True
    message = str(error).strip().lower()
    return any(
        token in message
        for token in (
            "used by another process",
            "being used by another process",
            "resource busy",
            "text file busy",
            "utilise par un autre processus",
            "utilisé par un autre processus",
        )
    )


def _is_transient_replace_lock_error(error: OSError) -> bool:
    """Windows atomic rename can fail briefly while antivirus or indexers hold the target."""
    if _is_locked_copy_error(error):
        return True
    winerror = getattr(error, "winerror", None)
    if winerror in {5, 13, 32, 33}:
        return True
    if isinstance(error, PermissionError) or error.errno in {13, EBUSY, ETXTBSY}:
        return True
    message = str(error).strip().lower()
    return any(
        token in message
        for token in (
            "permission denied",
            "access is denied",
            "temporary windows file lock",
            "file lock",
        )
    )


def _route_row_for_phase(
    mission: Mission,
    phase: str,
    *,
    route_rows: list[dict] | None = None,
) -> dict:
    rows = route_rows if route_rows is not None else _route_rows_for_mission(mission)
    role = _route_role_for_phase(phase)
    for item in rows:
        if str(item.get("role", "")).strip().lower() == role:
            return item
    return {
        "role": role,
        "provider": "",
        "model": "",
        "effort": "",
        "budgetClass": "",
        "source": "",
        "reason": "",
    }


def _provider_truth_from_action_history(
    mission: Mission,
    *,
    route_rows: list[dict],
) -> tuple[dict, dict]:
    success: dict = {}
    failure: dict = {}
    for entry in reversed(mission.action_history or []):
        if not isinstance(entry, dict):
            if hasattr(entry, "__dataclass_fields__"):
                entry = asdict(entry)
            else:
                continue
        result = dict(entry.get("result", {}))
        proposal = dict(entry.get("proposal", {}))
        delegation = dict(proposal.get("delegation_metadata", {}))
        phase = str(
            delegation.get("cycle_phase", mission.state.current_cycle_phase or "execute")
        ).strip().lower()
        route = _route_row_for_phase(mission, phase, route_rows=route_rows)
        provider = str(route.get("provider", "")).strip().lower()
        model = str(route.get("model", "")).strip()
        role = str(route.get("role", "")).strip().lower()
        if not provider and not model:
            continue
        summary = str(
            result.get("result_summary")
            or result.get("error")
            or result.get("stderr")
            or result.get("stdout")
            or ""
        ).strip()
        if len(summary) > 220:
            summary = summary[:217].rstrip() + "..."
        row = {
            "provider": provider,
            "model": model,
            "role": role,
            "phase": phase,
            "at": str(entry.get("executed_at", "") or ""),
            "source": "action_history",
            "summary": summary,
        }
        if bool(result.get("ok")):
            if not success:
                success = row
        elif not failure:
            failure = row
        if success and failure:
            break
    return success, failure


def _provider_truth_for_mission(
    mission: Mission,
    *,
    auth_presence: dict[str, bool],
    workspace: WorkspaceProfile | None = None,
) -> dict:
    phase = str(mission.state.current_cycle_phase or "execute").strip().lower()
    route_rows = _route_rows_for_mission(mission)
    active_route = _route_row_for_phase(mission, phase, route_rows=route_rows)
    active_provider = str(active_route.get("provider", "")).strip().lower()
    active_model = str(active_route.get("model", "")).strip()
    active_auth = _provider_auth_truth(
        active_provider,
        auth_presence=auth_presence,
        workspace=workspace,
    )
    auth_present = bool(active_auth.get("authPresent"))
    auth_mode = str(active_auth.get("authMode") or "")
    auth_path = str(active_auth.get("authPath") or "")
    route_auth: dict[str, dict] = {}
    for route in [*route_rows, active_route]:
        if not isinstance(route, dict):
            continue
        provider = str(route.get("provider", "")).strip().lower()
        if not provider or provider in route_auth:
            continue
        route_auth[provider] = _provider_auth_truth(
            provider,
            auth_presence=auth_presence,
            workspace=workspace,
        )
    last_success, last_failure = _provider_truth_from_action_history(
        mission,
        route_rows=route_rows,
    )
    if not last_failure:
        for session in reversed(mission.delegated_runtime_sessions or []):
            if hasattr(session, "__dataclass_fields__"):
                row = asdict(session)
            elif isinstance(session, dict):
                row = dict(session)
            else:
                continue
            status = str(row.get("status", "")).strip().lower()
            if status not in {"failed", "stopped"}:
                continue
            provider = str(row.get("target_provider", active_provider)).strip().lower()
            model = str(row.get("target_model", active_model)).strip()
            if not provider and not model:
                continue
            last_failure = {
                "provider": provider,
                "model": model,
                "role": str(row.get("target_role", _route_role_for_phase(phase))).strip().lower(),
                "phase": str(row.get("target_phase", phase)).strip().lower(),
                "at": str(row.get("updated_at", "") or ""),
                "source": "delegated_runtime",
                "summary": str(row.get("last_event") or row.get("detail") or "").strip(),
            }
            break

    updated_at_candidates = [
        str(mission.updated_at or ""),
        str(last_success.get("at", "") or "") if isinstance(last_success, dict) else "",
        str(last_failure.get("at", "") or "") if isinstance(last_failure, dict) else "",
    ]
    truth_updated_at = max(
        (value for value in updated_at_candidates if value),
        default=str(mission.updated_at or ""),
    )

    return {
        "currentPhase": phase or "execute",
        "activeRoute": {
            "role": str(active_route.get("role", "")).strip().lower(),
            "provider": active_provider,
            "model": active_model,
            "effort": str(active_route.get("effort", "")).strip().lower(),
            "budgetClass": str(active_route.get("budgetClass", "")).strip(),
            "source": str(active_route.get("source", "")).strip(),
            "taskType": str(active_route.get("taskType", "general_coding")).strip(),
            "routeIntent": str(active_route.get("routeIntent", "")).strip(),
            "fitScore": int(active_route.get("fitScore", 0) or 0),
            "outcomeSampleCount": int(active_route.get("outcomeSampleCount", 0) or 0),
            "outcomeSuccessRate": int(active_route.get("outcomeSuccessRate", 0) or 0),
            "outcomeTrend": str(active_route.get("outcomeTrend", "")).strip(),
        },
        "authPresent": auth_present,
        "authKnown": bool(active_provider),
        "authMode": auth_mode,
        "authPath": auth_path,
        "routeAuth": route_auth,
        "lastSuccessfulCall": last_success,
        "lastFailure": last_failure,
        "updatedAt": truth_updated_at,
    }


def _provider_auth_truth(
    provider: str,
    *,
    auth_presence: dict[str, bool],
    workspace: WorkspaceProfile | None = None,
) -> dict:
    normalized = str(provider or "").strip().lower()
    openai_auth_mode = normalize_openai_codex_auth_mode(
        getattr(workspace, "openai_codex_auth_mode", "none")
    )
    minimax_auth_mode = normalize_minimax_auth_mode(
        getattr(workspace, "minimax_auth_mode", "none")
    )
    if normalized in {"openai", "openai-codex"}:
        api_key_present = bool(auth_presence.get("openai", False))
        oauth_present = bool(auth_presence.get("openai-codex", False))
        auth_present = (
            (openai_auth_mode == "api" and api_key_present)
            or (openai_auth_mode == "oauth" and oauth_present)
            or api_key_present
            or oauth_present
        )
        auth_mode = (
            openai_auth_mode
            if openai_auth_mode != "none"
            else ("api" if api_key_present else ("oauth" if oauth_present else "none"))
        )
        return {
            "provider": normalized,
            "authPresent": auth_present,
            "authMode": auth_mode,
            "authPath": openai_codex_auth_label(auth_mode),
        }
    if normalized in {"minimax", "minimax-portal", "minimax-cn", "minimax-oauth"}:
        oauth_present = bool(
            auth_presence.get("minimax-portal", False)
            or auth_presence.get("minimax-oauth", False)
        )
        raw_api_key_present = bool(
            str(os.environ.get("MINIMAX_API_KEY", "")).strip()
            or str(os.environ.get("MINIMAX_CN_API_KEY", "")).strip()
        )
        api_key_present = bool(
            raw_api_key_present
            or (
                (
                    auth_presence.get("minimax", False)
                    or auth_presence.get("minimax-cn", False)
                )
                and not oauth_present
            )
        )
        auth_present = (
            (minimax_auth_mode == "minimax-api" and api_key_present)
            or (minimax_auth_mode == "minimax-portal-oauth" and oauth_present)
            or api_key_present
            or oauth_present
        )
        auth_mode = (
            minimax_auth_mode
            if minimax_auth_mode != "none"
            else (
                "minimax-api"
                if api_key_present
                else ("minimax-portal-oauth" if oauth_present else "none")
            )
        )
        return {
            "provider": normalized,
            "authPresent": auth_present,
            "authMode": auth_mode,
            "authPath": minimax_auth_label(auth_mode),
        }
    return {
        "provider": normalized,
        "authPresent": bool(auth_presence.get(normalized, False)) if normalized else False,
        "authMode": "",
        "authPath": "" if normalized else "not configured",
    }


def _effective_route_contract_for_mission(mission: Mission) -> dict:
    route_rows = []
    for item in mission.route_configs or []:
        route = dict(item) if isinstance(item, dict) else asdict(item)
        role = normalize_route_role(route.get("role", ""))
        if role not in ROUTE_OVERRIDE_ROLES:
            continue
        explanation = str(route.get("explanation", "") or "")
        source = (
            "override"
            if "override" in explanation.lower()
            else ("strategy" if "strategy" in explanation.lower() else "profile_default")
        )
        route_rows.append(
            {
                "role": role,
                "provider": route.get("provider", ""),
                "model": route.get("model", ""),
                "effort": route.get("effort", "medium"),
                "budgetClass": route.get("budget_class", route.get("budgetClass", "")),
                "fallbackPolicy": route.get("fallback_policy", route.get("fallbackPolicy", "same_provider")),
                "source": source,
                "reason": explanation,
                "taskType": route.get("task_type", route.get("taskType", "general_coding")),
                "routeIntent": route.get("route_intent", route.get("routeIntent", "")),
                "fitScore": route.get("fit_score", route.get("fitScore", 0)),
                "outcomeSampleCount": route.get(
                    "outcome_sample_count",
                    route.get("outcomeSampleCount", 0),
                ),
                "outcomeSuccessRate": route.get(
                    "outcome_success_rate",
                    route.get("outcomeSuccessRate", 0),
                ),
                "outcomeTrend": route.get("outcome_trend", route.get("outcomeTrend", "")),
            }
        )
        runtime_id = str(
            route.get("runtimeId")
            or route.get("runtime_id")
            or route.get("runtime")
            or ""
        ).strip().lower()
        if runtime_id:
            route_rows[-1]["runtimeId"] = runtime_id
    if route_rows:
        summary = " | ".join(
            [
                (
                    f"{row['role']}: "
                    f"{row.get('runtimeId') + ' -> ' if row.get('runtimeId') else ''}"
                    f"{row['provider']}:{row['model']} ({row['source']})"
                )
                for row in route_rows
            ]
        )
    else:
        summary = "No route contract resolved yet."
    return {
        "roles": route_rows,
        "resolutionOrder": "override > strategy > profile_default",
        "whyThisRoute": summary,
        "fallbackPolicy": "same_provider",
    }


def _reconcile_mission_route_policy(
    mission: Mission,
    workspace: WorkspaceProfile | None,
) -> bool:
    if workspace is None:
        return False
    workspace_routes = {
        str(item.get("role") or "").strip().lower(): item
        for item in normalize_route_overrides(getattr(workspace, "route_overrides", []))
    }
    if not workspace_routes:
        return False
    current_routes = [
        dict(item) if isinstance(item, dict) else asdict(item)
        for item in (mission.route_configs or [])
        if isinstance(item, dict) or hasattr(item, "__dataclass_fields__")
    ]
    changed = False
    by_role: dict[str, dict] = {}
    for route in current_routes:
        role = normalize_route_role(route.get("role") or "")
        if role:
            route["role"] = role
            by_role.setdefault(role, route)
    for role, workspace_route in workspace_routes.items():
        current = by_role.get(role)
        if current is None:
            current = {
                "role": role,
                "explanation": "Route override from workspace runtime contract.",
                "fallback_policy": "same_provider",
            }
            current_routes.append(current)
            by_role[role] = current
            changed = True
        if not _route_is_workspace_managed(current):
            continue
        changed = _copy_workspace_route_fields(current, workspace_route) or changed
    if not changed:
        return False
    mission.route_configs = current_routes
    mission.effective_route_contract = _effective_route_contract_for_mission(mission)
    if mission.effective_route_contract:
        mission.effective_route_contract.setdefault("mutationReceipts", [])
        mission.effective_route_contract["mutationReceipts"].append(
            {
                "receiptId": f"route_policy_reconciled:{utc_now_iso()}",
                "reason": "Workspace route policy superseded a stale mission runtime contract.",
                "source": "workspace_route_overrides",
            }
        )
    return True


def _route_is_workspace_managed(route: dict) -> bool:
    reason = " ".join(
        [
            str(route.get("explanation") or ""),
            str(route.get("reason") or ""),
            str(route.get("route_intent") or route.get("routeIntent") or ""),
        ]
    ).lower()
    return (
        not reason
        or "workspace runtime contract" in reason
        or "workspace route policy" in reason
        or "manual_workspace_override" in reason
        or "route override" in reason
    )


def _copy_workspace_route_fields(current: dict, workspace_route: dict) -> bool:
    changed = False
    fields_to_copy = {
        "runtimeId": "runtimeId",
        "runtime_id": "runtimeId",
        "runtime": "runtimeId",
        "provider": "provider",
        "model": "model",
        "effort": "effort",
        "budgetClass": "budget_class",
    }
    for source_key, target_key in fields_to_copy.items():
        value = str(workspace_route.get(source_key) or "").strip()
        if not value:
            continue
        if str(current.get(target_key, current.get(source_key, "")) or "").strip() == value:
            continue
        current[target_key] = value
        if target_key != source_key:
            current.pop(source_key, None)
        changed = True
    fallback_policy = str(
        workspace_route.get("fallbackPolicy")
        or workspace_route.get("fallback_policy")
        or ""
    ).strip()
    if fallback_policy and current.get("fallback_policy") != fallback_policy:
        current["fallback_policy"] = fallback_policy
        changed = True
    current.setdefault("explanation", "Route override from workspace runtime contract.")
    return changed


def refresh_mission_runtime_state(
    mission: Mission,
    refreshed_sessions: list[DelegatedRuntimeSession],
) -> None:
    if _operator_completed_hard_artifact_gate_passed(mission):
        _apply_operator_completed_terminal_state(mission)
        return
    prompts = [
        item.pending_approval.get("prompt", "Delegated approval required.")
        for item in refreshed_sessions
        if item.status == "waiting_for_approval"
    ]
    approval_payload = next(
        (dict(item.pending_approval) for item in refreshed_sessions if item.pending_approval),
        {},
    )
    approval_history = [
        entry
        for session in refreshed_sessions
        for entry in session.approval_history
        if isinstance(entry, dict)
    ]

    mission.state.pending_approval_payload = approval_payload
    mission.state.approval_history = approval_history[-8:]
    if not prompts:
        mission.proof.pending_approvals = []
    if refreshed_sessions:
        latest_session = refreshed_sessions[-1]
        mission.state.last_runtime_event = (
            latest_session.last_event or mission.state.last_runtime_event
        )
        mission.state.preferred_host = latest_session.preferred_host
        mission.state.assigned_host = latest_session.assigned_host
        mission.state.host_lease_id = latest_session.host_lease_id
        mission.state.host_locality = latest_session.host_locality
        mission.state.lease_status = latest_session.lease_status
        mission.state.worker_heartbeat_at = latest_session.worker_heartbeat_at

    terminal_unacknowledged = [
        item
        for item in refreshed_sessions
        if item.status in {"completed", "failed"} and not item.acknowledged
    ]
    failed_terminal_unacknowledged = [
        item for item in terminal_unacknowledged if item.status == "failed"
    ]
    active_delegated = [
        item for item in refreshed_sessions if item.status in {"launching", "running"}
    ]
    stale_delegated_parent = (
        str(mission.state.status or "").strip().lower()
        in {"launching", "running", "resume_dispatched"}
        or str(mission.state.stop_reason or "").strip() == "delegated_runtime_running"
    )

    if _mission_has_hard_artifact_gate_failure(mission):
        mission.state.status = "verification_failed"
        mission.state.planner_loop_status = "paused"
        mission.proof.summary = (
            "Mission needs artifact repair before it can be counted as completed."
        )
    elif prompts:
        mission.state.status = "needs_approval"
        mission.proof.summary = prompts[0]
        mission.proof.pending_approvals = prompts
    elif active_delegated:
        mission.state.status = "running"
        mission.proof.summary = (
            "Delegated runtime lane is active. Neyvia will continue when it finishes."
        )
    elif failed_terminal_unacknowledged and stale_delegated_parent:
        latest = failed_terminal_unacknowledged[-1]
        detail = (
            latest.detail
            or latest.last_event
            or "Delegated runtime lane failed before mission reconciliation."
        )
        failure_marker = "delegated_runtime_failed"
        mission.state.status = "verification_failed"
        mission.state.planner_loop_status = "paused"
        mission.state.stop_reason = failure_marker
        mission.state.last_error = detail[:500]
        mission.state.last_runtime_event = latest.last_event or failure_marker
        mission.state.last_verification_summary = (
            "Delegated runtime lane failed before mission reconciliation."
        )
        if failure_marker not in mission.state.verification_failures:
            mission.state.verification_failures.append(failure_marker)
        if mission.state.last_verification_summary not in mission.proof.failed_checks:
            mission.proof.failed_checks.append(mission.state.last_verification_summary)
        if failure_marker not in mission.proof.blocked_by:
            mission.proof.blocked_by.append(failure_marker)
        mission.proof.summary = (
            "Delegated runtime lane failed. The workspace slot was released so queued missions can continue."
        )
    elif terminal_unacknowledged and _completion_summary_needs_replacement(mission.proof.summary):
        latest = terminal_unacknowledged[-1]
        if latest.status == "failed":
            mission.proof.summary = (
                "Delegated runtime lane failed. Resume once to inspect output and replan."
            )
        else:
            mission.proof.summary = (
                "Delegated runtime lane completed. Resume once to reconcile proof and planning state."
            )

    continuity_state, continuity_detail = _continuity_state_for_mission(mission, refreshed_sessions)
    mission.state.continuity_state = continuity_state
    mission.state.continuity_detail = continuity_detail


def _mission_plan_step_ids(mission: Mission) -> set[str]:
    step_ids: set[str] = set()
    for revision in mission.plan_revisions or []:
        revision_payload = _as_mapping(revision)
        for step in revision_payload.get("steps") or []:
            step_payload = _as_mapping(step)
            step_id = str(
                step_payload.get("step_id")
                or step_payload.get("stepId")
                or step_payload.get("id")
                or ""
            ).strip()
            if step_id:
                step_ids.add(step_id)
        active_step_id = str(
            revision_payload.get("active_step_id")
            or revision_payload.get("activeStepId")
            or ""
        ).strip()
        if active_step_id:
            step_ids.add(active_step_id)
    if mission.state.active_step_id:
        step_ids.add(str(mission.state.active_step_id))
    return step_ids


def _is_low_signal_stopped_session(session: DelegatedRuntimeSession) -> bool:
    return (
        session.status == "stopped"
        and not session.pending_approval
        and not session.changed_files
        and not str(session.last_event or "").strip().lower().startswith("error")
    )


def _delegated_runtime_session_order_key(session: DelegatedRuntimeSession) -> tuple[str, str, str]:
    return (
        str(session.created_at or ""),
        str(session.updated_at or ""),
        str(session.delegated_id or ""),
    )


def _discover_related_delegated_runtime_sessions(
    mission: Mission,
    *,
    roots: list[Path | None],
    runtime_supervisor: DelegatedRuntimeSupervisor,
) -> list[DelegatedRuntimeSession]:
    existing_ids = {
        str(item.delegated_id or "").strip()
        for item in mission.delegated_runtime_sessions or []
        if str(item.delegated_id or "").strip()
    }
    existing_paths = {
        str(Path(item.session_path).resolve())
        for item in mission.delegated_runtime_sessions or []
        if item.session_path
    }
    known_delegate_ids = set(existing_ids)
    known_step_ids = _mission_plan_step_ids(mission)
    candidate_paths: list[Path] = []
    seen_paths: set[str] = set()

    for root in roots:
        if root is None:
            continue
        runtime_root = Path(root) / ".agent_control" / "runtime_sessions"
        try:
            paths = sorted(
                runtime_root.glob("delegate_*.json"),
                key=lambda item: item.stat().st_mtime,
            )
        except OSError:
            continue
        for path in paths[-160:]:
            resolved = str(path.resolve())
            if resolved in seen_paths or resolved in existing_paths:
                continue
            seen_paths.add(resolved)
            candidate_paths.append(path)

    discovered: list[DelegatedRuntimeSession] = []
    progress = True
    while progress:
        progress = False
        remaining: list[Path] = []
        for path in candidate_paths:
            try:
                session = runtime_supervisor.refresh_session(str(path))
            except (FileNotFoundError, OSError, TypeError, ValueError):
                continue
            delegated_id = str(session.delegated_id or "").strip()
            if not delegated_id or delegated_id in known_delegate_ids:
                continue
            session_mission_id = str(getattr(session, "mission_id", "") or "").strip()
            source_step_id = str(session.source_step_id or "").strip()
            source_delegated_id = str(session.source_delegated_id or "").strip()
            if (
                session_mission_id == mission.mission_id
                or source_step_id in known_step_ids
                or source_delegated_id in known_delegate_ids
            ):
                if _is_low_signal_stopped_session(session):
                    known_delegate_ids.add(delegated_id)
                    if source_step_id:
                        known_step_ids.add(source_step_id)
                    progress = True
                    continue
                discovered.append(session)
                known_delegate_ids.add(delegated_id)
                if source_step_id:
                    known_step_ids.add(source_step_id)
                progress = True
                continue
            remaining.append(path)
        candidate_paths = remaining
    return discovered


def _approval_receipt_key(mission: Mission) -> str:
    payload = mission.state.pending_approval_payload or {}
    raw_key = (
        payload.get("approval_id")
        or payload.get("approvalId")
        or payload.get("action_id")
        or payload.get("actionId")
        or payload.get("prompt")
        or mission.proof.summary
        or mission.mission_id
    )
    return str(raw_key)[:240]


def _maybe_send_approval_receipt(mission: Mission, root: Path) -> bool:
    if str(mission.state.status or "").strip().lower() not in {
        "needs_approval",
        "awaiting-approval",
        "awaiting_approval",
    }:
        return False
    if not mission.state.pending_approval_payload:
        return False
    receipt_key = _approval_receipt_key(mission)
    existing = mission.escalation_policy.delivery_receipts or []
    if any(str(item.get("approvalKey") or "") == receipt_key for item in existing if isinstance(item, dict)):
        return False

    payload = mission.state.pending_approval_payload
    prompt = str(payload.get("prompt") or mission.proof.summary or "Approval required.")
    risk_level = str(payload.get("risk_level") or payload.get("riskLevel") or "medium")
    if mission.escalation_policy.delivery_ready:
        receipt = send_approval_escalation_receipt(
            mission_id=mission.mission_id,
            prompt=prompt,
            risk_level=risk_level,
            escalation_policy=asdict(mission.escalation_policy),
            root=root,
            dry_run=os.environ.get("FLUXIO_DELIVERY_RECEIPT_DRY_RUN", "0") == "1",
        )
    else:
        receipt = record_delivery_receipt(
            root,
            mission_id=mission.mission_id,
            channel="browser",
            destination="control-room",
            event_kind="approval.required",
            event_message=prompt,
            status="skipped",
            error_message="delivery_not_ready",
            producer="mission_control",
            transport_provider="browser",
        )
    sent_at = getattr(receipt, "sent_at", "") or utc_now_iso()
    status = getattr(receipt, "status", "") or "attempted"
    error_message = getattr(receipt, "error_message", "") or ""
    mission.escalation_policy.delivery_receipts = (
        existing
        + [
            {
                "approvalKey": receipt_key,
                "receiptId": getattr(receipt, "receipt_id", "") or "",
                "status": status,
                "channel": getattr(receipt, "channel", "") or mission.escalation_policy.channel,
                "sentAt": sent_at,
                "error": error_message,
            }
        ]
    )[-20:]
    mission.escalation_policy.delivery_ready = False
    mission.escalation_policy.pending_count = 0
    mission.escalation_policy.last_sent_at = sent_at
    mission.escalation_policy.last_error = error_message
    return True


def normalize_action_history(action_history: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for item in action_history or []:
        record = dict(item)
        proposal = dict(record.get("proposal", {}))
        source_kind = proposal.get("sourceKind") or _infer_action_source_kind(proposal)
        proposal["sourceKind"] = source_kind
        result = dict(record.get("result", {}))
        result.setdefault("sourceKind", source_kind)
        record["proposal"] = proposal
        record["result"] = result
        normalized.append(record)
    return normalized


def _infer_action_source_kind(proposal: dict) -> str:
    if proposal.get("delegation_metadata"):
        return "delegated"
    if proposal.get("kind") in {
        "runtime_delegate",
        "delegated_runtime",
        "delegated_action",
    }:
        return "delegated"
    return "local"


def _continuity_state_for_mission(
    mission: Mission,
    delegated: list[DelegatedRuntimeSession],
) -> tuple[str, str]:
    if mission.state.status in TERMINAL_MISSION_STATUSES:
        return "terminal", "Mission is in a terminal state with recorded proof."
    if _mission_has_hard_artifact_gate_failure(mission):
        return (
            "resume_available",
            "Mission needs runtime output and artifact repair before it can be counted as completed.",
        )
    if any(item.status == "waiting_for_approval" for item in delegated):
        prompt = next(
            (
                item.pending_approval.get("prompt", "Delegated runtime is paused on approval.")
                for item in delegated
                if item.status == "waiting_for_approval"
            ),
            "Delegated runtime is paused on approval.",
        )
        return "approval_waiting", prompt
    if any(item.status in {"launching", "running"} for item in delegated):
        runtime_id = next(
            (item.runtime_id for item in delegated if item.status in {"launching", "running"}),
            mission.runtime_id,
        )
        return "delegated_active", f"{runtime_id} lane is still active and restart-safe."
    if any(item.status in {"completed", "failed"} and not item.acknowledged for item in delegated):
        return (
            "resume_available",
            "A delegated lane finished while Neyvia was away. Resume once to reconcile proof and planning state.",
        )
    if mission.state.latest_session_id and mission.state.status not in TERMINAL_MISSION_STATUSES:
        return "resume_available", "Mission can resume safely from the last recorded session."
    return "fresh_only", "No resumable mission continuity has been recorded yet."


def _verification_failure_label(item: object) -> str:
    if isinstance(item, dict):
        for key in ("checkId", "id", "label", "title", "message", "detail", "status"):
            value = str(item.get(key) or "").strip()
            if value:
                return value
        return json.dumps(item, sort_keys=True, ensure_ascii=True)
    return str(item)


@_control_checked('verification')

def _verification_summary_for_mission(mission: Mission, verification_result: str) -> str:

    if verification_result == 'failed':

        failed = mission.proof.failed_checks or mission.state.verification_failures

        failed_labels = [_verification_failure_label(item) for item in failed[:2]]

        return f"Failed: {', '.join(failed_labels)}" if failed_labels else 'Verification failed.'

    if verification_result == 'passed':

        passed_count = len(mission.proof.passed_checks)

        return f'Passed {passed_count} verification check(s).'

    return 'Verification is still pending.'


def _parse_iso_datetime(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@_control_checked('budget')

def mission_time_budget_window(mission: Mission, now: datetime | None=None) -> dict:

    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    started_at = _parse_iso_datetime(mission.created_at) or current_time

    elapsed_seconds = max(0, round((current_time - started_at).total_seconds()))

    budget_enforced = mission_runtime_budget_enforced(mission)

    if not budget_enforced:

        return {'startedAt': started_at.isoformat(), 'deadlineAt': None, 'maxRuntimeSeconds': 0, 'elapsedSeconds': max(elapsed_seconds, max(0, int(mission.state.elapsed_runtime_seconds or 0))), 'remainingSeconds': 0, 'enforced': False}

    deadline_at = _parse_iso_datetime(mission.run_budget.deadline_at)

    max_runtime_seconds = max(0, int(mission.run_budget.max_runtime_seconds or 0))

    if deadline_at is not None:

        max_runtime_seconds = max(0, round((deadline_at - started_at).total_seconds()))

        remaining_seconds = max(0, round((deadline_at - current_time).total_seconds()))

    else:

        remaining_seconds = max(0, max_runtime_seconds - elapsed_seconds)

    stored_elapsed_seconds = max(0, int(mission.state.elapsed_runtime_seconds or 0))

    stored_remaining_seconds = max(0, int(mission.state.remaining_runtime_seconds or 0))

    stored_time_budget_status = str(mission.state.time_budget_status or '').strip().lower()

    preserve_stored_window = str(mission.state.status or '').strip().lower() == 'running' and stored_elapsed_seconds > elapsed_seconds and (stored_remaining_seconds > 0 or stored_elapsed_seconds >= max_runtime_seconds or bool(stored_time_budget_status))

    if preserve_stored_window:

        elapsed_seconds = stored_elapsed_seconds

        remaining_seconds = stored_remaining_seconds

        if stored_time_budget_status in ACTIVE_TIME_BUDGET_STATUSES and remaining_seconds > 0 and (elapsed_seconds + remaining_seconds > max_runtime_seconds):

            max_runtime_seconds = elapsed_seconds + remaining_seconds

    return {'startedAt': started_at.isoformat(), 'deadlineAt': deadline_at.isoformat() if deadline_at is not None else None, 'maxRuntimeSeconds': max_runtime_seconds, 'elapsedSeconds': elapsed_seconds, 'remainingSeconds': remaining_seconds, 'enforced': True}


def _time_budget_snapshot_for_mission(mission: Mission) -> dict:
    delegated = mission.delegated_runtime_sessions or []
    budget_window = mission_time_budget_window(mission)
    elapsed_seconds = int(budget_window["elapsedSeconds"])
    max_runtime_seconds = int(budget_window["maxRuntimeSeconds"])
    remaining_seconds = int(budget_window["remainingSeconds"])
    pause_reason = _pause_reason_for_mission(mission, delegated)
    stored_time_budget_status = str(mission.state.time_budget_status or "").strip().lower()
    budget_enforced = bool(budget_window.get("enforced"))

    terminal_unacknowledged = any(
        item.status in {"completed", "failed"} and not item.acknowledged
        for item in delegated
    )

    if mission.state.status in TERMINAL_MISSION_STATUSES:
        status = mission.state.status
    elif not budget_enforced:
        status = "unlimited"
    elif pause_reason == "runtime_budget":
        status = "budget_exhausted"
    elif mission.state.status == "needs_approval":
        status = "paused_for_approval"
    elif pause_reason in {"verification_failed", "verification_failure"} or mission.state.status == "verification_failed":
        status = "paused_for_verification"
    elif mission.state.status == "blocked":
        status = "paused"
    elif mission.state.status == "queued":
        status = "queued"
    elif mission.state.status == "running" and stored_time_budget_status == "reconcile_pending":
        status = "reconcile_pending"
    elif any(item.status in {"launching", "running"} for item in delegated):
        status = "delegated_active"
    elif terminal_unacknowledged:
        status = "reconcile_pending"
    elif (
        mission.state.status == "running"
        and max_runtime_seconds > 0
        and elapsed_seconds >= max_runtime_seconds
        and remaining_seconds <= 0
    ):
        status = "budget_exhausted"
    elif mission.state.status == "running":
        status = "running"
    else:
        status = "pending"

    return {
        "mode": mission.run_budget.mode,
        "runUntilBehavior": mission.run_budget.run_until_behavior,
        "focusWindowHours": mission.run_budget.focus_window_hours,
        "deadlineAt": budget_window["deadlineAt"],
        "maxRuntimeSeconds": max_runtime_seconds,
        "budgetHours": round(max_runtime_seconds / 3600, 2) if max_runtime_seconds else 0,
        "elapsedSeconds": elapsed_seconds,
        "remainingSeconds": remaining_seconds,
        "status": status,
        "lastPauseReason": pause_reason,
        "enforced": budget_enforced,
    }


def _pause_reason_for_mission(
    mission: Mission,
    delegated: list[DelegatedRuntimeSession],
) -> str:
    if mission.state.status in TERMINAL_MISSION_STATUSES:
        return ""
    waiting_session = next(
        (item for item in delegated if item.status == "waiting_for_approval"),
        None,
    )
    if waiting_session is not None:
        return waiting_session.pending_approval.get(
            "prompt",
            "Delegated runtime is paused on approval.",
        )

    has_active_delegated = any(item.status in {"launching", "running"} for item in delegated)
    terminal_unacknowledged = [
        item
        for item in delegated
        if item.status in {"completed", "failed"} and not item.acknowledged
    ]

    raw_reason = mission.state.stop_reason or ""
    if not raw_reason and mission.state.status in {
        "queued",
        "blocked",
        "needs_approval",
        "verification_failed",
    }:
        raw_reason = mission.state.last_budget_pause_reason or ""
    if raw_reason == "runtime_budget":
        if mission_runtime_budget_enforced(mission):
            return "Runtime budget exhausted."
        raw_reason = ""
    if raw_reason in {"verification_failed", "verification_failure"} or mission.state.status == "verification_failed":
        summary = mission.state.last_verification_summary or _verification_summary_for_mission(mission, "failed")
        return summary or "Verification failed."
    if raw_reason == "approval_required":
        return "Operator approval is required before Neyvia can continue."
    if raw_reason == "delegated_runtime_running" and terminal_unacknowledged and not has_active_delegated:
        latest = terminal_unacknowledged[-1]
        if latest.status == "failed":
            return "Delegated runtime lane failed and needs one reconciliation resume."
        return "Delegated runtime lane completed and needs one reconciliation resume."
    if raw_reason == "delegated_runtime_running":
        return "Delegated runtime lane is still active and restart-safe."
    if raw_reason:
        return raw_reason

    if has_active_delegated:
        return "Delegated runtime lane is still active and restart-safe."
    if mission.state.status == "queued":
        if mission.state.queue_position > 0:
            return mission.state.queue_reason or "Mission is queued behind another active mission."
        return "Mission is queued and ready to start."
    if mission.state.status == "blocked":
        if (
            str(mission.state.last_error or "").strip().lower() == "runtime_budget"
            and not mission_runtime_budget_enforced(mission)
        ):
            return "Legacy implicit runtime timer is not enforced; resume is available."
        return mission.state.last_error or "Mission is paused and needs operator attention."
    return ""


def _current_runtime_lane_for_mission(
    mission: Mission,
    delegated: list[DelegatedRuntimeSession],
) -> str:
    if mission.state.status in TERMINAL_MISSION_STATUSES:
        return f"{mission.runtime_id} primary lane {mission.state.status.replace('_', ' ')}"
    if _mission_has_hard_artifact_gate_failure(mission):
        return f"{mission.runtime_id} primary lane verification failed"
    for item in reversed(delegated):
        if item.status in {"waiting_for_approval", "launching", "running"}:
            return f"{item.runtime_id} delegated lane {item.status.replace('_', ' ')}"
    if delegated:
        latest = delegated[-1]
        return f"{latest.runtime_id} delegated lane {latest.status.replace('_', ' ')}"
    return f"{mission.runtime_id} primary lane {mission.state.status.replace('_', ' ')}"


def _inspect_workspace_git(
    workspace_root: Path,
    commit_message_style: str = "scoped",
) -> dict:
    snapshot = {
        "repoDetected": False,
        "branch": "",
        "trackingBranch": "",
        "dirty": False,
        "stagedCount": 0,
        "unstagedCount": 0,
        "untrackedCount": 0,
        "ahead": 0,
        "behind": 0,
        "changedFiles": [],
        "suggestedCommitMessage": "",
        "remotes": [],
        "deployTarget": {
            "provider": "",
            "available": False,
            "configured": False,
            "requiresApproval": True,
            "detail": "No deploy target detected.",
        },
        "detail": "",
    }
    if not workspace_root.exists():
        snapshot["detail"] = "Workspace path does not exist."
        return snapshot

    git_probe = _run_git_command(workspace_root, ["rev-parse", "--is-inside-work-tree"])
    if git_probe["return_code"] != 0 or git_probe["stdout"].strip() != "true":
        snapshot["detail"] = "No Git repository detected for this workspace."
        return snapshot

    snapshot["repoDetected"] = True
    status_output = _run_git_command(workspace_root, ["status", "--porcelain=1", "--branch"])
    lines = [line for line in status_output["stdout"].splitlines() if line.strip()]
    if lines and lines[0].startswith("## "):
        snapshot.update(_parse_branch_status(lines[0][3:]))
        lines = lines[1:]

    for line in lines:
        code = line[:2]
        path_text = _parse_git_status_path(line)
        if path_text and path_text not in snapshot["changedFiles"]:
            snapshot["changedFiles"].append(path_text)
        if code.startswith("??"):
            snapshot["untrackedCount"] += 1
            continue
        if code[:1] not in {" ", "?"}:
            snapshot["stagedCount"] += 1
        if code[1:2] not in {" ", "?"}:
            snapshot["unstagedCount"] += 1
    snapshot["dirty"] = (
        snapshot["stagedCount"] > 0
        or snapshot["unstagedCount"] > 0
        or snapshot["untrackedCount"] > 0
    )

    remotes = []
    remotes_output = _run_git_command(workspace_root, ["remote", "-v"])
    seen = set()
    for line in remotes_output["stdout"].splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        name, url, kind = parts[0], parts[1], parts[2].strip("()")
        key = (name, url)
        if kind != "push" or key in seen:
            continue
        seen.add(key)
        remotes.append({"name": name, "url": url})
    snapshot["remotes"] = remotes
    snapshot["deployTarget"] = _infer_deploy_target(workspace_root, remotes)
    snapshot["detail"] = (
        f"{snapshot['branch'] or 'Detached HEAD'} · "
        f"{'dirty' if snapshot['dirty'] else 'clean'} · "
        f"{len(remotes)} remote(s)"
    )
    snapshot["suggestedCommitMessage"] = _build_generated_commit_message(
        snapshot,
        commit_message_style,
    )
    return snapshot


def _run_git_command(workspace_root: Path, args: list[str]) -> dict:
    try:
        completed = subprocess.run(  # noqa: S603
            ["git", *args],
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
    except OSError:
        return {"return_code": 1, "stdout": "", "stderr": "git unavailable"}
    return {
        "return_code": completed.returncode,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
    }


def _parse_branch_status(branch_line: str) -> dict:
    branch = branch_line
    tracking = ""
    ahead = 0
    behind = 0
    if "..." in branch_line:
        branch, rest = branch_line.split("...", 1)
        tracking = rest.split(" [", 1)[0].strip()
    match = re.search(r"\[(.*?)\]$", branch_line)
    if match:
        parts = [item.strip() for item in match.group(1).split(",")]
        for part in parts:
            if part.startswith("ahead "):
                ahead = int(part.split(" ", 1)[1])
            elif part.startswith("behind "):
                behind = int(part.split(" ", 1)[1])
    return {
        "branch": branch.strip(),
        "trackingBranch": tracking,
        "ahead": ahead,
        "behind": behind,
    }


def _parse_git_status_path(line: str) -> str:
    payload = line[3:].strip()
    if " -> " in payload:
        payload = payload.split(" -> ", 1)[1].strip()
    return payload


def _normalize_commit_subject_token(value: str) -> str:
    cleaned = re.sub(r"[_\-]+", " ", value)
    cleaned = re.sub(r"[^A-Za-z0-9 ]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


def _build_generated_commit_message(
    git_snapshot: dict,
    style: str = "scoped",
) -> str:
    if not git_snapshot.get("dirty"):
        return ""
    changed_files = git_snapshot.get("changedFiles", [])
    labels: list[str] = []
    for path_text in changed_files[:4]:
        path = Path(path_text)
        token = _normalize_commit_subject_token(path.stem or path.name or path_text)
        if token and token not in labels:
            labels.append(token)
    normalized_style = (style or "scoped").strip().lower()
    if normalized_style == "concise":
        if labels:
            return f"Update {labels[0]}"
        return "Update workspace state"
    if normalized_style == "detailed":
        branch = git_snapshot.get("branch") or "workspace"
        if len(labels) == 1:
            return f"Update {labels[0]} on {branch}"
        if len(labels) == 2:
            return f"Update {labels[0]} and {labels[1]} on {branch}"
        if len(labels) >= 3:
            return f"Update {labels[0]}, {labels[1]}, and related files on {branch}"
        return f"Update workspace state on {branch}"
    if len(labels) == 1:
        return f"Update {labels[0]}"
    if len(labels) == 2:
        return f"Update {labels[0]} and {labels[1]}"
    if len(labels) >= 3:
        return f"Update {labels[0]}, {labels[1]}, and related files"
    return "Update workspace state"


def _infer_deploy_target(
    workspace_root: Path,
    remotes: list[dict],
) -> dict:
    remote_urls = [item["url"] for item in remotes]
    github_remote = next((url for url in remote_urls if "github.com" in url.lower()), "")
    pages_workflow = workspace_root / ".github" / "workflows"
    has_pages_workflow = pages_workflow.exists() and any(
        "pages" in child.name.lower() for child in pages_workflow.glob("*.y*ml")
    )
    if github_remote:
        return {
            "provider": "github_pages",
            "available": True,
            "configured": has_pages_workflow,
            "requiresApproval": True,
            "detail": (
                "GitHub remote detected. Offer approval-gated push or Pages deployment actions."
                if has_pages_workflow
                else "GitHub remote detected. Pages can be scaffolded after explicit approval."
            ),
        }
    return {
        "provider": "",
        "available": False,
        "configured": False,
        "requiresApproval": True,
        "detail": "No GitHub remote detected yet.",
    }


@_control_checked('git-actions')

def _build_git_actions(git_snapshot: dict, profile_parameters: dict) -> list[dict]:

    if not git_snapshot.get('repoDetected'):

        return []

    approval_required = profile_parameters.get('gitActionPolicy', 'approval_gated') != 'profile_resolved'

    tracking_branch = str(git_snapshot.get('trackingBranch') or '').strip()

    ahead = int(git_snapshot.get('ahead') or 0)

    behind = int(git_snapshot.get('behind') or 0)

    suggested_commit_message = str(git_snapshot.get('suggestedCommitMessage') or 'Update workspace state').replace('"', '')

    actions = [{'actionId': 'inspect_repo_state', 'label': 'Inspect repository state', 'command': 'git status --short --branch', 'commandSurface': 'git.inspect', 'requiresApproval': False, 'detail': 'Review branch, changes, and ahead/behind before mutating actions.'}]

    if tracking_branch:

        detail = f'Fast-forward only pull from {tracking_branch}.'

        if behind > 0:

            detail = f'{behind} remote commit(s) are waiting on {tracking_branch}. Pull fast-forward only.'

        elif ahead > 0:

            detail = f'Branch is ahead of {tracking_branch}. Pull stays fast-forward only before pushing.'

        actions.append({'actionId': 'pull_branch', 'label': 'Pull tracked branch', 'command': 'git pull --ff-only', 'commandSurface': 'git.pull', 'requiresApproval': approval_required, 'detail': detail})

    if git_snapshot.get('dirty'):

        actions.append({'actionId': 'commit_changes', 'label': 'Commit with generated message', 'command': f'git add -A && git commit -m "{suggested_commit_message}"', 'commandSurface': 'git.commit', 'requiresApproval': True, 'detail': f'Neyvia stages all current changes and commits them with "{suggested_commit_message}".', 'generatedMessage': suggested_commit_message})

    if git_snapshot.get('remotes'):

        actions.append({'actionId': 'push_branch', 'label': 'Push current branch', 'command': 'git push', 'commandSurface': 'git.push', 'requiresApproval': approval_required, 'detail': 'Policy-resolved push action. Approval stays on by default.'})

    deploy_target = git_snapshot.get('deployTarget', {})

    if deploy_target.get('available'):

        actions.append({'actionId': 'deploy_pages', 'label': 'Publish deploy target', 'command': 'git push origin HEAD', 'commandSurface': 'deploy.pages', 'requiresApproval': True, 'detail': deploy_target.get('detail', 'Deploy target is available.')})

    return actions


@_control_checked('validation-actions')

def _build_validation_actions(workspace_root: Path) -> list[dict]:

    verification_commands = detect_default_verification_commands(workspace_root)

    if not verification_commands:

        return []

    joined_command = ' && '.join(verification_commands)

    detail = verification_commands[0] if len(verification_commands) == 1 else f'{verification_commands[0]} then {len(verification_commands) - 1} more verification command(s).'

    return [{'actionId': 'validate_workspace', 'label': 'Validate workspace', 'command': joined_command, 'commandSurface': 'validate.workspace', 'requiresApproval': False, 'detail': f'Run detected verification commands: {detail}', 'commands': verification_commands}]


def _build_workspace_service_management(
    *,
    setup_health: dict,
    runtime_status: dict | None,
    integration_recommendations: list[dict],
    connected_apps: list[dict],
) -> list[dict]:
    services = {
        item["serviceId"]: dict(item)
        for item in setup_health.get("serviceManagement", [])
        if isinstance(item, dict) and item.get("serviceId")
    }

    if runtime_status:
        runtime_id = runtime_status.get("runtime_id", "")
        existing = services.get(runtime_id, {})
        services[runtime_id] = {
            **existing,
            "serviceId": runtime_id,
            "label": runtime_status.get("label", runtime_id),
            "serviceCategory": "runtime",
            "installSource": existing.get("installSource", "system_path"),
            "currentHealthStatus": (
                "update_available"
                if runtime_status.get("update_available")
                else ("healthy" if runtime_status.get("detected") else "missing")
            ),
            "lastVerificationResult": (
                "outdated"
                if runtime_status.get("update_available")
                else ("passed" if runtime_status.get("detected") else "blocked")
            ),
            "lastRepairAction": existing.get("lastRepairAction", {}),
            "managementMode": existing.get("managementMode", "externally_managed"),
            "version": runtime_status.get("version") or existing.get("version", ""),
            "latestVersion": runtime_status.get("latest_version") or existing.get("latestVersion", ""),
            "updateAvailable": runtime_status.get("update_available", existing.get("updateAvailable", False)),
            "details": runtime_status.get("doctor_summary") or existing.get("details", ""),
            "serviceActions": existing.get("serviceActions", []),
            "verifyAction": existing.get("verifyAction", {}),
        }

    for item in integration_recommendations:
        recommendation_id = item.get("recommendation_id", "")
        if not recommendation_id:
            continue
        services[recommendation_id] = {
            "serviceId": recommendation_id,
            "label": item.get("label", recommendation_id),
            "serviceCategory": "mcp_tool_server",
            "installSource": item.get("command", ""),
            "currentHealthStatus": "recommended",
            "lastVerificationResult": "not_run",
            "lastRepairAction": {},
            "managementMode": "fluxio_managed",
            "version": "",
            "details": item.get("reason", ""),
            "serviceActions": [],
            "verifyAction": {},
        }

    for session in connected_apps:
        app_id = session.get("app_id", "")
        if not app_id:
            continue
        ui_hints = session.get("ui_hints", {}) if isinstance(session.get("ui_hints"), dict) else {}
        bridge_role = str(ui_hints.get("bridgeRole") or "")
        latest_task = session.get("latest_task_result", {})
        latest_payload = latest_task.get("payload", {}) if isinstance(latest_task, dict) else {}
        requires_approval_for_write = bool(
            latest_payload.get("requiresApprovalForWrite", True)
        )
        service_actions = []
        if bridge_role in {"nas_storage", "cloud_storage"}:
            is_cloud = bridge_role == "cloud_storage"
            service_actions = [
                *(
                    [
                        {
                            "actionId": "verify-nas-ssh",
                            "label": "Verify NAS SSH",
                            "description": "Probe the SSH/SFTP NAS route on the configured port without logging secrets.",
                            "commandSurface": "bridge.verify",
                            "requiresApproval": False,
                            "kind": "verify",
                        },
                        {
                            "actionId": "unlock-codex-network",
                            "label": "Unlock local network rule",
                            "description": "Disable the local Codex outbound firewall block through an elevated PowerShell prompt, then retry the NAS SSH route.",
                            "commandSurface": "bridge.activate",
                            "requiresApproval": True,
                            "kind": "repair",
                        }
                    ]
                    if (
                        not is_cloud
                        and latest_payload.get("selectedHost")
                        and latest_payload.get("sshUser")
                    )
                    else []
                ),
                *(
                    [
                        {
                            "actionId": "activate-nas-mapping",
                            "label": "Activate NAS mapping",
                            "description": "Run the Core/Cowork Synology mapper so the NAS project drive is available.",
                            "commandSurface": "bridge.activate",
                            "requiresApproval": True,
                            "kind": "activate",
                        }
                    ]
                    if (not is_cloud and latest_payload.get("activationCommand"))
                    else []
                ),
                {
                    "actionId": "monitor-cloud-drive" if is_cloud else "monitor-fast-sync",
                    "label": "Monitor bridge",
                    "description": (
                        "Read the latest cloud-drive bridge status from the connected app."
                        if is_cloud
                        else "Read the latest computer/NAS bridge status from the connected app."
                    ),
                    "commandSurface": "bridge.status",
                    "requiresApproval": False,
                    "kind": "status",
                },
                {
                    "actionId": "queue-cloud-drive-transfer" if is_cloud else "start-sync-selection",
                    "label": "Queue transfer",
                    "description": (
                        "Queue an upload or download through the cloud-drive bridge after preview."
                        if is_cloud
                        else (
                            "Queue an upload or download through the NAS bridge after preview."
                            if requires_approval_for_write
                            else "Run an upload or download through the NAS bridge immediately."
                        )
                    ),
                    "commandSurface": "bridge.sync",
                    "requiresApproval": requires_approval_for_write,
                    "kind": "sync",
                },
            ]
        services[app_id] = {
            "serviceId": app_id,
            "label": session.get("app_name", app_id),
            "serviceCategory": "connected_app_bridge",
            "serviceRole": bridge_role or "app_bridge",
            "installSource": session.get("bridge_transport", "") or "bridge_manifest",
            "currentHealthStatus": session.get("bridge_health", session.get("status", "unknown")),
            "lastVerificationResult": (
                "passed" if session.get("status") == "connected" else session.get("status", "unknown")
            ),
            "lastRepairAction": {},
            "managementMode": "externally_managed",
            "version": "",
            "details": latest_task.get("resultSummary", "") if isinstance(latest_task, dict) else "",
            "sourceRoot": latest_payload.get("sourceRoot", "") if isinstance(latest_payload, dict) else "",
            "targetRoot": latest_payload.get("targetRoot", "") if isinstance(latest_payload, dict) else "",
            "bridgeEndpoint": session.get("bridge_endpoint", ""),
            "serviceActions": service_actions,
            "verifyAction": {},
        }

    return list(services.values())


def _build_storage_bridge_snapshot(connected_apps: list[dict]) -> dict:
    storage_sessions = [
        item
        for item in connected_apps
        if (item.get("ui_hints") or {}).get("bridgeRole") in {"nas_storage", "cloud_storage"}
        or item.get("app_id") in {"synology-fast-sync", "cloud-drive-sync"}
    ]
    nas_sessions = [
        item
        for item in storage_sessions
        if (item.get("ui_hints") or {}).get("bridgeRole") == "nas_storage"
        or item.get("app_id") == "synology-fast-sync"
    ]
    cloud_sessions = [
        item
        for item in storage_sessions
        if (item.get("ui_hints") or {}).get("bridgeRole") == "cloud_storage"
        or item.get("app_id") == "cloud-drive-sync"
    ]
    primary = nas_sessions[0] if nas_sessions else (storage_sessions[0] if storage_sessions else {})
    latest_task = primary.get("latest_task_result", {}) if isinstance(primary, dict) else {}
    payload = latest_task.get("payload", {}) if isinstance(latest_task, dict) else {}
    bridge_plan = payload.get("bridgePlan", {}) if isinstance(payload, dict) else {}
    ui_hints = primary.get("ui_hints", {}) if isinstance(primary, dict) else {}
    ui_hints = ui_hints if isinstance(ui_hints, dict) else {}
    cloud_primary = cloud_sessions[0] if cloud_sessions else {}
    cloud_task = (
        cloud_primary.get("latest_task_result", {})
        if isinstance(cloud_primary, dict)
        else {}
    )
    cloud_payload = cloud_task.get("payload", {}) if isinstance(cloud_task, dict) else {}
    cloud_plan = cloud_payload.get("bridgePlan", {}) if isinstance(cloud_payload, dict) else {}
    return {
        "available": bool(storage_sessions),
        "connected": bool(primary.get("status") == "connected"),
        "sessionCount": len(storage_sessions),
        "primaryAppId": primary.get("app_id", ""),
        "primaryAppName": primary.get("app_name", ""),
        "health": primary.get("bridge_health", "missing") if primary else "missing",
        "endpoint": primary.get("bridge_endpoint", ""),
        "publicEndpoint": (
            payload.get("publicEndpoint") or ui_hints.get("publicEndpoint", "")
            if isinstance(payload, dict)
            else ui_hints.get("publicEndpoint", "")
        ),
        "preferredTransport": (
            payload.get("preferredTransport") or ui_hints.get("preferredTransport", "")
            if isinstance(payload, dict)
            else ui_hints.get("preferredTransport", "")
        ),
        "httpsReady": bool(
            (payload.get("httpsReady") if isinstance(payload, dict) else None)
            or ui_hints.get("httpsReady", False)
        ),
        "sourceRoot": payload.get("sourceRoot", "") if isinstance(payload, dict) else "",
        "targetRoot": payload.get("targetRoot", "") if isinstance(payload, dict) else "",
        "selectedMode": payload.get("selectedMode", "") if isinstance(payload, dict) else "",
        "selectedHost": payload.get("selectedHost", "") if isinstance(payload, dict) else "",
        "controlProtocol": payload.get("controlProtocol", "") if isinstance(payload, dict) else "",
        "controlPort": payload.get("controlPort", 0) if isinstance(payload, dict) else 0,
        "requestedSshPort": payload.get("requestedSshPort", 0) if isinstance(payload, dict) else 0,
        "observedSshPort": payload.get("observedSshPort", 0) if isinstance(payload, dict) else 0,
        "sshPortStatus": payload.get("sshPortStatus", "") if isinstance(payload, dict) else "",
        "sshUser": payload.get("sshUser", "") if isinstance(payload, dict) else "",
        "remoteProjectRoot": payload.get("remoteProjectRoot", "") if isinstance(payload, dict) else "",
        "activeDirection": payload.get("activeDirection", "") if isinstance(payload, dict) else "",
        "safeDirections": payload.get("safeDirections", []) if isinstance(payload, dict) else [],
        "requiresApprovalForWrite": bool(
            payload.get("requiresApprovalForWrite", True) if isinstance(payload, dict) else True
        ),
        "activationRequired": bool(
            payload.get("activationRequired", False) if isinstance(payload, dict) else False
        ),
        "activationProject": payload.get("activationProject", "") if isinstance(payload, dict) else "",
        "activationHint": payload.get("activationHint", "") if isinstance(payload, dict) else "",
        "activationCommand": payload.get("activationCommand", "") if isinstance(payload, dict) else "",
        "writePolicy": bridge_plan.get("writePolicy", "preview_then_approve")
        if isinstance(bridge_plan, dict)
        else "preview_then_approve",
        "conflictPolicy": bridge_plan.get("conflictPolicy", "keep_newer_and_log")
        if isinstance(bridge_plan, dict)
        else "keep_newer_and_log",
        "summary": latest_task.get("resultSummary", "") if isinstance(latest_task, dict) else "",
        "sessions": storage_sessions,
        "nas": {
            "available": bool(nas_sessions),
            "connected": bool(primary.get("status") == "connected"),
            "sessionCount": len(nas_sessions),
            "appId": primary.get("app_id", "") if primary else "",
            "appName": primary.get("app_name", "") if primary else "",
            "health": primary.get("bridge_health", "missing") if primary else "missing",
            "endpoint": primary.get("bridge_endpoint", "") if primary else "",
            "publicEndpoint": (
                payload.get("publicEndpoint") or ui_hints.get("publicEndpoint", "")
                if isinstance(payload, dict)
                else ui_hints.get("publicEndpoint", "")
            ),
            "preferredTransport": (
                payload.get("preferredTransport") or ui_hints.get("preferredTransport", "")
                if isinstance(payload, dict)
                else ui_hints.get("preferredTransport", "")
            ),
            "httpsReady": bool(
                (payload.get("httpsReady") if isinstance(payload, dict) else None)
                or ui_hints.get("httpsReady", False)
            ),
            "sourceRoot": payload.get("sourceRoot", "") if isinstance(payload, dict) else "",
            "targetRoot": payload.get("targetRoot", "") if isinstance(payload, dict) else "",
            "selectedMode": payload.get("selectedMode", "") if isinstance(payload, dict) else "",
            "selectedHost": payload.get("selectedHost", "") if isinstance(payload, dict) else "",
            "controlProtocol": payload.get("controlProtocol", "") if isinstance(payload, dict) else "",
            "controlPort": payload.get("controlPort", 0) if isinstance(payload, dict) else 0,
            "requestedSshPort": payload.get("requestedSshPort", 0) if isinstance(payload, dict) else 0,
            "observedSshPort": payload.get("observedSshPort", 0) if isinstance(payload, dict) else 0,
            "sshPortStatus": payload.get("sshPortStatus", "") if isinstance(payload, dict) else "",
            "sshUser": payload.get("sshUser", "") if isinstance(payload, dict) else "",
            "remoteProjectRoot": payload.get("remoteProjectRoot", "") if isinstance(payload, dict) else "",
            "safeDirections": payload.get("safeDirections", []) if isinstance(payload, dict) else [],
            "activationRequired": bool(
                payload.get("activationRequired", False) if isinstance(payload, dict) else False
            ),
            "activationProject": payload.get("activationProject", "") if isinstance(payload, dict) else "",
            "activationHint": payload.get("activationHint", "") if isinstance(payload, dict) else "",
            "activationCommand": payload.get("activationCommand", "") if isinstance(payload, dict) else "",
            "summary": latest_task.get("resultSummary", "") if isinstance(latest_task, dict) else "",
        },
        "cloud": {
            "available": bool(cloud_sessions),
            "connected": bool(cloud_primary.get("status") == "connected"),
            "sessionCount": len(cloud_sessions),
            "appId": cloud_primary.get("app_id", "") if cloud_primary else "",
            "appName": cloud_primary.get("app_name", "") if cloud_primary else "",
            "health": cloud_primary.get("bridge_health", "missing") if cloud_primary else "missing",
            "endpoint": cloud_primary.get("bridge_endpoint", "") if cloud_primary else "",
            "sourceRoot": cloud_payload.get("sourceRoot", "") if isinstance(cloud_payload, dict) else "",
            "targetRoot": cloud_payload.get("targetRoot", "") if isinstance(cloud_payload, dict) else "",
            "selectedMode": cloud_payload.get("selectedMode", "") if isinstance(cloud_payload, dict) else "",
            "selectedHost": cloud_payload.get("selectedHost", "") if isinstance(cloud_payload, dict) else "",
            "safeDirections": cloud_payload.get("safeDirections", []) if isinstance(cloud_payload, dict) else [],
            "mountedRoots": cloud_payload.get("mountedRoots", []) if isinstance(cloud_payload, dict) else [],
            "googleLoginReady": bool(
                cloud_payload.get("googleLoginReady") if isinstance(cloud_payload, dict) else False
            ),
            "providers": cloud_payload.get("cloudProviders", []) if isinstance(cloud_payload, dict) else [],
            "loginUrl": cloud_plan.get("loginUrl", "https://drive.google.com/drive/my-drive")
            if isinstance(cloud_plan, dict)
            else "https://drive.google.com/drive/my-drive",
            "desktopClientUrl": cloud_plan.get(
                "desktopClientUrl",
                "https://www.google.com/drive/download/",
            )
            if isinstance(cloud_plan, dict)
            else "https://www.google.com/drive/download/",
            "writePolicy": cloud_plan.get("writePolicy", "preview_then_approve")
            if isinstance(cloud_plan, dict)
            else "preview_then_approve",
            "conflictPolicy": cloud_plan.get("conflictPolicy", "keep_newer_and_log")
            if isinstance(cloud_plan, dict)
            else "keep_newer_and_log",
            "summary": cloud_task.get("resultSummary", "") if isinstance(cloud_task, dict) else "",
        },
    }


def _service_management_summary(items: list[dict]) -> dict[str, int]:
    healthy_statuses = {"healthy", "connected", "ready"}
    return {
        "totalItems": len(items),
        "healthyCount": sum(
            1 for item in items if item.get("currentHealthStatus") in healthy_statuses
        ),
        "needsAttentionCount": sum(
            1 for item in items if item.get("currentHealthStatus") not in healthy_statuses
        ),
        "runtimeCount": sum(1 for item in items if item.get("serviceCategory") == "runtime"),
        "toolServerCount": sum(
            1 for item in items if item.get("serviceCategory") == "mcp_tool_server"
        ),
        "bridgeCount": sum(
            1 for item in items if item.get("serviceCategory") == "connected_app_bridge"
        ),
    }


def _default_workflow_verification(selected_workspace: dict) -> list[str]:
    workspace_type = selected_workspace.get("workspace_type", "")
    commands: list[str] = []
    if "python" in workspace_type:
        commands.append("python -m pytest tests -q")
    if "node" in workspace_type or "tauri" in workspace_type or "web" in workspace_type:
        commands.append("npm run frontend:build")
    if "tauri" in workspace_type:
        commands.append("npm run tauri build -- --debug")
    return commands


def _build_workflow_studio(
    workspaces: list[dict],
    missions: list[dict],
    setup_health: dict,
    skill_catalog: dict,
) -> dict:
    selected_workspace = workspaces[0] if workspaces else {}
    git_snapshot = selected_workspace.get("gitSnapshot", {})
    verification_defaults = _default_workflow_verification(selected_workspace)
    recommended_skill_ids = [
        item.get("packId") or item.get("pack_id") or item.get("skillId") or item.get("skill_id")
        for item in skill_catalog.get("recommendedPacks", [])
        if item.get("packId") or item.get("pack_id") or item.get("skillId") or item.get("skill_id")
    ]
    managed_service_ids = [
        item.get("serviceId")
        for item in selected_workspace.get("serviceManagement", [])
        if item.get("managementMode") == "fluxio_managed" and item.get("serviceId")
    ]
    bridge_service_ids = [
        item.get("serviceId")
        for item in selected_workspace.get("serviceManagement", [])
        if item.get("serviceCategory") == "connected_app_bridge" and item.get("serviceId")
    ]
    setup_blockers = [
        item.get("serviceId")
        for item in setup_health.get("serviceManagement", [])
        if item.get("currentHealthStatus") != "healthy" and item.get("serviceId")
    ]
    recipes = [
        {
            "workflowId": "agent_long_run",
            "label": "Long-Run Agent Session",
            "description": "Leave Neyvia to plan, execute, verify, and replan over many hours with approvals and proof kept visible.",
            "status": "ready" if missions else "available",
            "audience": "all",
            "surface": "agent_view",
            "reviewStatus": "reviewed",
            "runtimeChoice": selected_workspace.get("default_runtime", "hermes"),
            "skillIds": recommended_skill_ids[:3],
            "serviceIds": managed_service_ids[:4],
            "verificationDefaults": verification_defaults,
        },
        {
            "workflowId": "ui_review_loop",
            "label": "Live UI Review Loop",
            "description": "Use HMR, fixtures, proof, and replay-ready states while refining the desktop workbench.",
            "status": "ready" if selected_workspace else "available",
            "audience": "builder",
            "surface": "builder_view",
            "reviewStatus": "reviewed",
            "runtimeChoice": selected_workspace.get("default_runtime", "hermes"),
            "skillIds": recommended_skill_ids[:2],
            "serviceIds": [
                item.get("serviceId")
                for item in selected_workspace.get("serviceManagement", [])
                if item.get("serviceCategory") in {"mcp_tool_server", "runtime"}
            ][:4],
            "verificationDefaults": verification_defaults,
        },
        {
            "workflowId": "nas_bridge_run",
            "label": "Computer/NAS Bridge Run",
            "description": "Use a local editable folder with a NAS-backed runtime target, transfer preview, and approval-gated writes.",
            "status": "ready" if bridge_service_ids else "available",
            "audience": "builder",
            "surface": "storage_bridge",
            "reviewStatus": "reviewed",
            "runtimeChoice": selected_workspace.get("default_runtime", "hermes"),
            "skillIds": recommended_skill_ids[:2],
            "serviceIds": bridge_service_ids[:4],
            "verificationDefaults": verification_defaults,
        },
        {
            "workflowId": "safe_git_push",
            "label": "Safe Push Or Deploy",
            "description": "Inspect repo truth first, then offer profile-resolved push and GitHub Pages actions with approvals.",
            "status": "ready" if git_snapshot.get("repoDetected") else "blocked",
            "audience": "advanced",
            "surface": "builder_view",
            "reviewStatus": "reviewed",
            "runtimeChoice": selected_workspace.get("default_runtime", "hermes"),
            "skillIds": recommended_skill_ids[:1],
            "serviceIds": managed_service_ids[:2],
            "verificationDefaults": verification_defaults,
        },
        {
            "workflowId": "skill_authoring",
            "label": "Skill And Workflow Authoring",
            "description": "Create a new skill or workflow recipe, test it locally, and keep it reviewable inside Neyvia.",
            "status": "ready" if selected_workspace else "available",
            "audience": "builder",
            "surface": "skill_studio",
            "reviewStatus": "reviewed",
            "runtimeChoice": selected_workspace.get("default_runtime", "hermes"),
            "skillIds": [
                skill_id
                for skill_id in [
                    item.get("skillId") or item.get("skill_id") or item.get("packId")
                    for item in (
                        skill_catalog.get("userInstalledSkills", [])[:2]
                        + skill_catalog.get("learnedSkills", [])[:2]
                    )
                ]
                if skill_id
            ],
            "serviceIds": managed_service_ids[:3],
            "verificationDefaults": verification_defaults,
        },
        {
            "workflowId": "setup_repair",
            "label": "Installer-Grade Setup Repair",
            "description": "Detect missing dependencies, explain blockers, and guide repair actions from inside the app.",
            "status": "blocked" if setup_health.get("missingDependencies") else "ready",
            "audience": "beginner",
            "surface": "setup",
            "reviewStatus": "reviewed",
            "runtimeChoice": selected_workspace.get("default_runtime", "hermes"),
            "skillIds": [],
            "serviceIds": setup_blockers[:4],
            "verificationDefaults": verification_defaults,
        },
    ]
    learning_queue = []
    for mission in missions:
        for item in mission.get("missionLoop", {}).get("improvementQueue", []):
            learning_queue.append(item)
    return {
        "recipes": recipes,
        "learningQueue": learning_queue[:6],
        "recommendedMode": "agent",
        "managementSummary": {
            "recipeCount": len(recipes),
            "reviewedCount": sum(1 for item in recipes if item.get("reviewStatus") == "reviewed"),
            "blockedCount": sum(1 for item in recipes if item.get("status") == "blocked"),
        },
    }


def _as_mapping(value: object) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return {}


def _unique_texts(values: list[object]) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def _workflow_record_path(root: Path, raw_path: object, *, label: str, source: str) -> dict:
    value = str(raw_path or "").strip()
    if not value:
        return {}
    path = _recover_evidence_path(root, value)
    return {
        "label": label,
        "path": value,
        "resolvedPath": str(path),
        "exists": path.exists(),
        "servedUrl": _artifact_api_url_if_safe(path),
        "source": source,
    }


def _build_autonomous_workflow_record(
    mission: Mission,
    *,
    root: Path,
    event_count: int = 0,
    previous: dict | None = None,
) -> dict:
    previous = previous or {}
    delegated_sessions = [
        _as_mapping(session) for session in mission.delegated_runtime_sessions or []
    ]
    delegated_sessions = [item for item in delegated_sessions if item]
    action_history = [
        _as_mapping(action) for action in mission.action_history or []
    ]
    action_history = [item for item in action_history if item]
    mission_loop = build_mission_loop_snapshot(mission)

    changed_files: list[object] = list(mission.proof.changed_files or [])
    for session in delegated_sessions:
        changed_files.extend(session.get("changed_files") or [])
    for action in action_history:
        result = _as_mapping(action.get("result"))
        changed_files.extend(result.get("changed_files") or [])

    approval_history = list(mission.state.approval_history or [])
    pending_approvals = list(mission.proof.pending_approvals or [])
    for session in delegated_sessions:
        pending = _as_mapping(session.get("pending_approval"))
        if pending and str(pending.get("status") or "pending") == "pending":
            pending_approvals.append(pending.get("prompt") or pending.get("request_id"))
        approval_history.extend(
            item for item in session.get("approval_history") or [] if isinstance(item, dict)
        )

    evidence_files: list[dict] = []
    for session in delegated_sessions:
        for raw_path, label, source in (
            (session.get("session_path"), "session state", "delegated_runtime_session"),
            (session.get("events_path"), "session events", "delegated_runtime_events"),
            (session.get("log_path"), "runtime log", "delegated_runtime_log"),
        ):
            evidence = _workflow_record_path(root, raw_path, label=label, source=source)
            if evidence:
                evidence_files.append(evidence)
    deduped_evidence: list[dict] = []
    seen_evidence: set[str] = set()
    for evidence in evidence_files:
        key = str(evidence.get("resolvedPath") or evidence.get("path") or "")
        if not key or key in seen_evidence:
            continue
        seen_evidence.add(key)
        deduped_evidence.append(evidence)

    session_statuses = [
        str(session.get("status") or "").strip()
        for session in delegated_sessions
        if session.get("status")
    ]
    failed_sessions = sum(1 for status in session_statuses if status == "failed")
    active_sessions = sum(
        1
        for status in session_statuses
        if status in {"queued", "launching", "running", "waiting_for_approval"}
    )
    workflow_id = str(previous.get("workflowId") or f"workflow_{mission.mission_id}")
    created_at = str(previous.get("createdAt") or mission.created_at)
    updated_at_candidates = [
        mission.updated_at,
        *[str(session.get("updated_at") or "") for session in delegated_sessions],
    ]
    updated_at = max((item for item in updated_at_candidates if item), default=mission.updated_at)

    return {
        "schemaVersion": "autonomous-workflow-record.v1",
        "workflowId": workflow_id,
        "missionId": mission.mission_id,
        "workspaceId": mission.workspace_id,
        "title": mission.title or _mission_title(mission.objective),
        "objective": mission.objective,
        "status": mission.state.status,
        "runtimeId": mission.runtime_id,
        "mode": mission.run_budget.mode,
        "createdAt": created_at,
        "updatedAt": updated_at,
        "currentPhase": mission_loop.get("currentCyclePhase", ""),
        "continuityState": mission_loop.get("continuityState", ""),
        "continuityDetail": mission_loop.get("continuityDetail", ""),
        "runBudget": {
            "mode": mission.run_budget.mode,
            "maxRuntimeSeconds": mission.run_budget.max_runtime_seconds,
            "remainingSeconds": mission.state.remaining_runtime_seconds,
            "status": mission.state.time_budget_status,
            "runUntilBehavior": mission.run_budget.run_until_behavior,
            "enforced": mission_runtime_budget_enforced(mission),
        },
        "executionScope": asdict(mission.execution_scope),
        "executionPolicy": asdict(mission.execution_policy),
        "routeContract": (
            mission.effective_route_contract
            if mission.effective_route_contract
            else _effective_route_contract_for_mission(mission)
        ),
        "runtimeSummary": {
            "delegatedSessionCount": len(delegated_sessions),
            "activeSessionCount": active_sessions,
            "failedSessionCount": failed_sessions,
            "latestSessionId": mission.state.latest_session_id
            or (str(delegated_sessions[-1].get("delegated_id") or "") if delegated_sessions else ""),
            "currentRuntimeLane": mission_loop.get("currentRuntimeLane", ""),
            "lastRuntimeEvent": mission.state.last_runtime_event,
        },
        "approvalSummary": {
            "pending": _unique_texts(pending_approvals),
            "pendingCount": len(_unique_texts(pending_approvals)),
            "historyCount": len(approval_history),
            "latest": approval_history[-1] if approval_history else {},
        },
        "verification": {
            "commands": list(mission.verification_policy.commands or []),
            "lastResult": mission_loop.get("lastVerificationResult", ""),
            "lastSummary": mission_loop.get("lastVerificationSummary", ""),
            "passedChecks": list(mission.proof.passed_checks or []),
            "failedChecks": list(mission.proof.failed_checks or []),
            "verificationFailures": list(mission.state.verification_failures or []),
        },
        "risk": {
            "blockers": list(mission.proof.blocked_by or []),
            "blockerClassification": dict(mission.state.blocker_classification or {}),
            "pendingMutatingActions": mission.state.pending_mutating_actions,
            "stopReason": mission.state.stop_reason or "",
        },
        "changedFiles": _unique_texts(changed_files),
        "eventCount": event_count,
        "evidenceFiles": deduped_evidence,
        "lastProofSummary": mission.proof.summary,
        "archived": False,
    }


def _build_autonomous_workflow_records_snapshot(workflows: list[dict]) -> dict:
    active_records = [item for item in workflows if not item.get("archived")]
    needs_approval = [
        item
        for item in active_records
        if item.get("status") == "needs_approval"
        or int(item.get("approvalSummary", {}).get("pendingCount", 0) or 0) > 0
    ]
    running = [
        item
        for item in active_records
        if item.get("status") in {"running", "queued", "delegated_active"}
        or item.get("runtimeSummary", {}).get("activeSessionCount", 0)
    ]
    failed = [
        item
        for item in active_records
        if item.get("status") in {"failed", "verification_failed", "blocked"}
        or item.get("runtimeSummary", {}).get("failedSessionCount", 0)
        or item.get("verification", {}).get("failedChecks")
        or item.get("verification", {}).get("verificationFailures")
        or item.get("risk", {}).get("blockers")
    ]
    completed = [item for item in active_records if item.get("status") == "completed"]
    return {
        "schemaVersion": "autonomous-workflows.v1",
        "items": workflows[:80],
        "summary": {
            "total": len(active_records),
            "running": len(running),
            "needsApproval": len(needs_approval),
            "failedOrBlocked": len(failed),
            "completed": len(completed),
            "archived": len(workflows) - len(active_records),
        },
        "emptyState": (
            "No autonomous workflow records have been captured yet. Start a mission to create an audit record."
            if not active_records
            else ""
        ),
        "source": "agent_control_autonomous_workflows",
    }


def detect_workspace_type(root: Path) -> str:
    root = root.resolve()
    if (root / "src-tauri").exists() and (root / "pyproject.toml").exists():
        return "tauri-python"
    if (root / "package.json").exists() and (root / "public").exists():
        return "web-node"
    if (root / "pyproject.toml").exists():
        return "python"
    if (root / "package.json").exists():
        return "node"
    return "general"


def recommend_skills(
    workspace_type: str, runtime_id: str
) -> list[SkillRecommendation]:
    recommendations = [
        SkillRecommendation(
            recommendation_id="repo_scan",
            label="Repo Scan",
            reason="Ground each mission in real workspace structure before delegating.",
            runtime_id=runtime_id,
            workspace_type=workspace_type,
            enabled_by_default=True,
        )
    ]
    if "python" in workspace_type:
        recommendations.append(
            SkillRecommendation(
                recommendation_id="python_verification",
                label="Python Verification",
                reason="Keep pytest and packaging checks visible in completion proof.",
                runtime_id=runtime_id,
                workspace_type=workspace_type,
            )
        )
    if "node" in workspace_type or "web" in workspace_type or "tauri" in workspace_type:
        recommendations.append(
            SkillRecommendation(
                recommendation_id="frontend_proof",
                label="Frontend Proof",
                reason="Track UI regressions and live run output for mission proof.",
                runtime_id=runtime_id,
                workspace_type=workspace_type,
            )
        )
    return recommendations


def recommend_integrations(
    workspace_type: str, runtime_id: str
) -> list[IntegrationRecommendation]:
    recommendations = [
        IntegrationRecommendation(
            recommendation_id="filesystem_mcp",
            label="Filesystem MCP",
            reason="Helps the agent inspect and summarize multiple projects safely.",
            command="npx @modelcontextprotocol/server-filesystem .",
            runtime_id=runtime_id,
            workspace_type=workspace_type,
            enabled_by_default=True,
        ),
        IntegrationRecommendation(
            recommendation_id="git_mcp",
            label="Git MCP",
            reason="Exposes repo status and history to the agent without custom glue.",
            command="uvx mcp-server-git",
            runtime_id=runtime_id,
            workspace_type=workspace_type,
        ),
    ]
    if "web" in workspace_type or "tauri" in workspace_type:
        recommendations.append(
            IntegrationRecommendation(
                recommendation_id="playwright_mcp",
                label="Playwright MCP",
                reason="Useful for proof screenshots, smoke tests, and non-technical validation.",
                command="npx @playwright/mcp@latest",
                runtime_id=runtime_id,
                workspace_type=workspace_type,
            )
        )
    return recommendations


@_control_checked('mode')

def mission_mode_to_engine_mode(mode: str) -> str:

    mapping = {'focus': 'fast', 'autopilot': 'autopilot', 'deep run': 'deep_run', 'research': 'swarms'}

    return mapping.get(mode.strip().lower(), 'autopilot')


def default_docs_for_workspace(root: Path) -> list[str]:
    candidates = ["docs/PRD.md", "docs/ROADMAP.md", "README.md"]
    return [path for path in candidates if (root / path).exists()]


def build_escalation_preview(mission: Mission) -> str:
    proof_summary = mission.proof.summary or mission.objective
    if mission.state.status == "completed":
        return f"Mission complete: {proof_summary}"
    if mission.state.status == "verification_failed":
        failures = ", ".join(mission.state.verification_failures) or "verification failed"
        return f"Mission needs input: {failures}"
    if mission.state.status == "blocked":
        blocked = ", ".join(mission.proof.blocked_by) or "setup or approval is blocking progress"
        return f"Mission blocked: {blocked}"
    if mission.state.status == "needs_approval":
        return f"Approval needed: {proof_summary}"
    return f"Mission update: {proof_summary}"


@_control_checked('title')

def _mission_title(objective: str) -> str:

    cleaned = re.sub('\\s+', ' ', objective or '').strip()

    if not cleaned:

        return 'New Mission'

    cleaned = re.split('[\\n.!?]', cleaned, maxsplit=1)[0].strip()

    for pattern in MISSION_TITLE_PREFIXES:

        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE).strip()

    tokens = re.findall('[A-Za-z0-9][A-Za-z0-9+./_-]*', cleaned)

    if not tokens:

        return 'New Mission'

    title_tokens: list[str] = []

    for index, token in enumerate(tokens):

        if index >= 2 and token.lower() in MISSION_TITLE_STOPWORDS:

            continue

        title_tokens.append(token)

        if len(title_tokens) >= 6:

            break

    if not title_tokens:

        title_tokens = tokens[:6]

    first = title_tokens[0]

    if first and (not first[:1].isupper()):

        title_tokens[0] = f'{first[:1].upper()}{first[1:]}'

    return ' '.join(title_tokens)


@_control_checked('scope')

def infer_planned_file_scope(objective: str, success_checks: list[str] | None=None) -> list[str]:

    candidates: list[str] = []

    patterns = ['\\b(?:under|in|inside|at|to)\\s+([A-Za-z]:[\\\\/][^\\s,;]+)', '\\b(?:under|in|inside|at|to)\\s+((?:/|\\\\\\\\)[^\\s,;]+)', '\\b((?:apps|web|src|docs|scripts|tests|desktop-ui|src-tauri|packages|tools|reports|artifacts|\\.agent_control)[\\\\/][^\\s,;]+)', '`([^`]+[\\\\/][^`]+)`']

    for line in '\n'.join([objective or '', *(success_checks or [])]).splitlines():

        normalized_line = line.strip().lower()

        if not normalized_line:

            continue

        if 'source:' in normalized_line and 'workspace' not in normalized_line:

            continue

        if 'source project' in normalized_line and 'workspace' not in normalized_line:

            continue

        for pattern in patterns:

            for match in re.finditer(pattern, line, flags=re.IGNORECASE):

                raw = match.group(1).strip().rstrip('.,;:)')

                raw_lower = raw.replace('\\', '/').lower()

                if raw_lower == 'tests/build/smoke' and 'checks' in normalized_line:

                    continue

                if raw:

                    candidates.append(raw)

    normalized: list[str] = []

    seen: set[str] = set()

    for candidate in candidates:

        path = candidate.replace('\\', '/')

        path = re.sub('^[\\"\']|[\\"\']$', '', path).strip()

        path = re.sub('/+$', '', path)

        if not path or '://' in path:

            continue

        dedupe_key = path.lower()

        if dedupe_key not in seen:

            seen.add(dedupe_key)

            normalized.append(path)

    return normalized[:8]


def _age_seconds(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(int((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()), 0)


def _percent(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return int(round((numerator / denominator) * 100))


def _load_json_file(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


INTEGRATION_READINESS_POINTS = {
    "nas_live_data": 15,
    "hermes_openruntime_turn": 20,
    "oratio_viva_action": 15,
    "jbhabcn_action": 15,
    "mind_tower_action": 15,
    "provider_routes": 10,
    "authenticated_phone_agent": 10,
}






def _integration_category(
    *,
    category_id: str,
    label: str,
    points: int,
    ready: bool,
    state: str | None = None,
    detail: str = "",
    source: str = "",
    receipt_path: str = "",
    screenshot_path: str = "",
    command: str = "",
    evidence: dict | None = None,
) -> dict:
    return _mission_control_integration._integration_category(
        category_id=category_id,
        label=label,
        points=points,
        ready=ready,
        state=state,
        detail=detail,
        source=source,
        receipt_path=receipt_path,
        screenshot_path=screenshot_path,
        command=command,
        evidence=evidence,
        _integration_state=_integration_state,
        _integration_state_label=_integration_state_label,
    )


def _latest_json_report(root: Path, patterns: list[str]) -> tuple[dict, Path | None]:
    return _mission_control_integration._latest_json_report(
        root,
        patterns,
        _load_json_file=_load_json_file,
    )


def _connected_app_category(
    connected_apps_snapshot: dict,
    *,
    app_id: str,
    label: str,
    points: int,
) -> dict:
    return _mission_control_integration._connected_app_category(
        connected_apps_snapshot,
        app_id=app_id,
        label=label,
        points=points,
        _integration_category=_integration_category,
    )


def _runtime_turn_category(
    *,
    root: Path,
    runtime_compartments: dict,
    hermes_mission_evidence: dict,
) -> dict:
    return _mission_control_integration._runtime_turn_category(
        root=root,
        runtime_compartments=runtime_compartments,
        hermes_mission_evidence=hermes_mission_evidence,
        INTEGRATION_READINESS_POINTS=INTEGRATION_READINESS_POINTS,
        _integration_category=_integration_category,
        _latest_json_report=_latest_json_report,
    )


def _nas_live_data_category(root: Path, nas_deploy_readiness: dict) -> dict:
    return _mission_control_integration._nas_live_data_category(
        root,
        nas_deploy_readiness,
        INTEGRATION_READINESS_POINTS=INTEGRATION_READINESS_POINTS,
        _integration_category=_integration_category,
        _load_json_file=_load_json_file,
    )


def _provider_route_category(provider_auth_presence: dict[str, bool]) -> dict:
    return _mission_control_integration._provider_route_category(
        provider_auth_presence,
        INTEGRATION_READINESS_POINTS=INTEGRATION_READINESS_POINTS,
        _integration_category=_integration_category,
    )


def _authenticated_phone_agent_category(root: Path) -> dict:
    return _mission_control_integration._authenticated_phone_agent_category(
        root,
        INTEGRATION_READINESS_POINTS=INTEGRATION_READINESS_POINTS,
        _integration_category=_integration_category,
        _latest_json_report=_latest_json_report,
    )


def _bootstrap_authenticated_phone_agent_category(root: Path) -> dict:
    return _mission_control_integration._bootstrap_authenticated_phone_agent_category(
        root,
        INTEGRATION_READINESS_POINTS=INTEGRATION_READINESS_POINTS,
        _integration_category=_integration_category,
        _load_json_file=_load_json_file,
    )


def build_integration_readiness_snapshot(
    root: Path,
    *,
    missions: list[Mission] | None = None,
    connected_apps_snapshot: dict | None = None,
    runtime_compartments: dict | None = None,
    provider_auth_presence: dict[str, bool] | None = None,
    nas_deploy_readiness: dict | None = None,
    hermes_mission_evidence: dict | None = None,
    proof_scan_deferred: bool = False,
) -> dict:
    return _mission_control_integration.build_integration_readiness_snapshot(
        root,
        missions=missions,
        connected_apps_snapshot=connected_apps_snapshot,
        runtime_compartments=runtime_compartments,
        provider_auth_presence=provider_auth_presence,
        nas_deploy_readiness=nas_deploy_readiness,
        hermes_mission_evidence=hermes_mission_evidence,
        proof_scan_deferred=proof_scan_deferred,
        INTEGRATION_READINESS_POINTS=INTEGRATION_READINESS_POINTS,
        _authenticated_phone_agent_category=_authenticated_phone_agent_category,
        _bootstrap_authenticated_phone_agent_category=_bootstrap_authenticated_phone_agent_category,
        _build_hermes_mission_evidence=_build_hermes_mission_evidence,
        _build_runtime_compartments_snapshot=_build_runtime_compartments_snapshot,
        _connected_app_category=_connected_app_category,
        _nas_live_data_category=_nas_live_data_category,
        _percent=_percent,
        _provider_auth_presence_from_env=_provider_auth_presence_from_env,
        _provider_route_category=_provider_route_category,
        _runtime_turn_category=_runtime_turn_category,
        build_nas_deploy_readiness_snapshot=build_nas_deploy_readiness_snapshot,
        utc_now_iso=utc_now_iso,
    )


def _read_text_tail_lines(path: Path, *, limit: int) -> list[str]:
    limit = max(0, int(limit or 0))
    if limit <= 0:
        return []
    block_size = 64 * 1024
    buffer = b""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            while position > 0 and buffer.count(b"\n") <= limit:
                read_size = min(block_size, position)
                position -= read_size
                handle.seek(position)
                buffer = handle.read(read_size) + buffer
    except OSError:
        return []
    lines = [
        line.decode("utf-8", errors="ignore").strip()
        for line in buffer.splitlines()
        if line.strip()
    ]
    return lines[-limit:]


def _read_jsonl_tail(path: Path, *, limit: int = 10) -> list[dict]:
    rows: deque[dict] = deque(maxlen=max(1, int(limit or 1)))
    for line in _read_text_tail_lines(path, limit=max(1, int(limit or 1))):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return list(rows)


def _runtime_transcript_has_concrete_output(row: dict, detail: str = "") -> bool:
    metadata = _runtime_event_metadata(row)
    args = metadata.get("args") if isinstance(metadata.get("args"), dict) else {}
    result = metadata.get("result") if isinstance(metadata.get("result"), dict) else {}
    data = row.get("data") if isinstance(row.get("data"), dict) else {}
    return any(
        str(value or "").strip()
        for value in (
            args.get("content"),
            args.get("body"),
            args.get("text"),
            result.get("result_summary"),
            result.get("stdout"),
            result.get("error"),
            data.get("content"),
            data.get("text"),
            data.get("stdout"),
            data.get("stderr"),
        )
    ) or "runtime output:" in str(detail or "").lower()


def _is_low_signal_session_state_value(value: str) -> bool:
    normalized = " ".join(str(value or "").strip().lower().split())
    if not normalized:
        return True
    return normalized in {
        "fluxio hybrid harness orchestrated this mission.",
        "prepare rollout notes and next iteration tasks",
    } or normalized.startswith("execution policy:") or normalized.startswith("runtime controls:")


def _runtime_transcript_detail(row: dict) -> str:
    metadata = _runtime_event_metadata(row)
    if not metadata:
        return ""
    parts: list[str] = []
    kind = str(metadata.get("kind") or row.get("kind") or "").strip()
    command = str(metadata.get("command") or "").strip()
    target_path = str(
        metadata.get("target_path")
        or metadata.get("targetPath")
        or metadata.get("path")
        or ""
    ).strip()
    gate = metadata.get("gate") if isinstance(metadata.get("gate"), dict) else {}
    result = metadata.get("result") if isinstance(metadata.get("result"), dict) else {}
    args = metadata.get("args") if isinstance(metadata.get("args"), dict) else {}
    revision_id = str(metadata.get("revision_id") or metadata.get("revisionId") or "").strip()
    active_step_id = str(metadata.get("active_step_id") or metadata.get("activeStepId") or "").strip()
    file_content = str(
        args.get("content")
        or args.get("body")
        or args.get("text")
        or ""
    ).strip()
    if file_content:
        content_preview = " ".join(file_content.split())
        parts.append(f"Runtime output: {content_preview[:900]}")
    if kind:
        parts.append(f"Action: {kind}")
    if target_path:
        parts.append(f"Target: {target_path}")
    if command:
        parts.append(f"Command: {command[:180]}")
    if gate.get("status"):
        parts.append(f"Gate: {gate.get('status')}")
    if result.get("result_summary"):
        parts.append(f"Result: {result.get('result_summary')}")
    elif result.get("error"):
        parts.append(f"Error: {result.get('error')}")
    if revision_id:
        parts.append(f"Revision: {revision_id}")
    if active_step_id:
        parts.append(f"Active step: {active_step_id}")
    if not parts:
        compact_keys = [
            key
            for key in ("phase", "role", "provider", "model", "status", "source")
            if str(metadata.get(key) or "").strip()
        ]
        parts = [f"{_titleize_token(key)}: {metadata.get(key)}" for key in compact_keys[:5]]
    return " · ".join(str(part) for part in parts if str(part or "").strip())[:1200]


def _titleize_token(value: str) -> str:
    return re.sub(r"\b\w", lambda match: match.group(0).upper(), str(value or "").replace("_", " ").replace("-", " "))


def _verify_desktop_script_contract(root: Path) -> tuple[bool, str]:
    return _mission_control_release._verify_desktop_script_contract(
        root,
        _load_json_file=_load_json_file,
    )


def _verify_frontend_source_alignment(root: Path) -> tuple[bool, str]:
    return _mission_control_release._verify_frontend_source_alignment(
        root,
        _load_json_file=_load_json_file,
        _vite_targets_web_root=_vite_targets_web_root,
    )




def _verify_public_web_distribution_contract(root: Path) -> tuple[bool, str]:
    return _mission_control_release._verify_public_web_distribution_contract(
        root,
        _load_json_file=_load_json_file,
    )


def _verify_self_improvement_evidence_contract(root: Path) -> tuple[bool, str]:
    return _mission_control_release._verify_self_improvement_evidence_contract(
        root,
        _load_json_file=_load_json_file,
    )








def _build_proving_cycle_readiness(root: Path) -> dict:
    return _mission_control_release._build_proving_cycle_readiness(
        root,
        _age_seconds=_age_seconds,
        _load_json_file=_load_json_file,
        _mission_events_record_delegated_active=_mission_events_record_delegated_active,
        _mission_payload_runtime_budget_exhausted=_mission_payload_runtime_budget_exhausted,
        _runtime_pid_alive=_runtime_pid_alive,
    )


def _event_timestamp(event: dict) -> str:
    return str(
        event.get("timestamp")
        or event.get("at")
        or event.get("created_at")
        or event.get("updated_at")
        or event.get("executed_at")
        or ""
    )


def _project_event_tone(event: dict) -> str:
    text = " ".join(
        [
            str(event.get("kind") or ""),
            str(event.get("message") or ""),
            json.dumps(event.get("metadata") or {}, sort_keys=True, default=str),
        ]
    ).lower()
    if any(marker in text for marker in ("failed", "failure", "error", "blocked")):
        return "bad"
    if any(marker in text for marker in ("approval", "queued", "pending", "needs")):
        return "warn"
    if any(marker in text for marker in ("completed", "passed", "succeeded", "slice")):
        return "good"
    return "neutral"


def _safe_artifact_id(path: Path) -> str:
    import hashlib

    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:24]


def _runtime_lane_rows_for_mission(mission: Mission, session: DelegatedRuntimeSession | None = None) -> list[dict]:
    contract = (
        mission.effective_route_contract
        if mission.effective_route_contract
        else _effective_route_contract_for_mission(mission)
    )
    route_rows = contract.get("roles") if isinstance(contract, dict) else []
    if not isinstance(route_rows, list):
        route_rows = []
    provider_truth = mission.state.provider_runtime_truth if isinstance(mission.state.provider_runtime_truth, dict) else {}
    active_route = provider_truth.get("activeRoute") if isinstance(provider_truth.get("activeRoute"), dict) else {}
    active_role = str(active_route.get("role") or "").strip().lower()
    route_auth = provider_truth.get("routeAuth") if isinstance(provider_truth.get("routeAuth"), dict) else {}
    last_failure = provider_truth.get("lastFailure") if isinstance(provider_truth.get("lastFailure"), dict) else {}
    lane_control_receipts = [
        item
        for item in (mission.state.lane_control_receipts or [])
        if isinstance(item, dict)
    ]
    lanes: list[dict] = []
    seen_roles: set[str] = set()
    explicit_roles = {
        str(item.get("role") or "").strip().lower()
        for item in route_rows
        if isinstance(item, dict)
    }
    ordered_roles = ["planner"]
    ordered_roles.extend(
        role for role in ("backend", "frontend") if role in explicit_roles
    )
    ordered_roles.extend(["executor", "verifier"])
    for role in ordered_roles:
        latest_control_receipt = next(
            (
                item
                for item in reversed(lane_control_receipts)
                if str(item.get("role") or "").strip().lower() == role
            ),
            {},
        )
        route = next(
            (
                dict(item)
                for item in route_rows
                if isinstance(item, dict) and str(item.get("role", "")).strip().lower() == role
            ),
            {},
        )
        provider = str(route.get("provider") or active_route.get("provider") or "openai-codex").strip().lower()
        runtime_id = str(
            route.get("runtimeId")
            or route.get("runtime_id")
            or active_route.get("runtimeId")
            or active_route.get("runtime_id")
            or mission.runtime_id
            or ""
        ).strip().lower()
        model = _canonical_runtime_lane_model(
            provider,
            str(route.get("model") or active_route.get("model") or "gpt-5.5").strip(),
            role=role,
        )
        provider_auth = _route_auth_for_provider(
            provider,
            provider_truth=provider_truth,
            route_auth=route_auth,
        )
        provider_auth_present = bool(provider_auth.get("authPresent"))
        auth_path = str(provider_auth.get("authPath") or "")
        health = "ready" if provider_auth_present else ("blocked" if provider else "unknown")
        blocker = ""
        if not provider_auth_present:
            if provider in {"openai", "openai-codex"}:
                blocker = "OpenAI Codex OAuth/API auth is not present for this runtime."
            elif provider in {"minimax", "minimax-portal", "minimax-cn", "minimax-oauth"}:
                blocker = "MiniMax API key or broker OAuth is not present for this runtime."
            elif provider:
                blocker = f"{provider} auth is not present for this runtime."
        if last_failure and str(last_failure.get("role", "")).strip().lower() == role:
            blocker = str(last_failure.get("summary") or blocker)
            health = "blocked"
        failure_class = _provider_failure_class(blocker, last_failure if isinstance(last_failure, dict) else {})
        latest_control_detail = ""
        if latest_control_receipt:
            latest_control_detail = (
                f"Last lane control: {latest_control_receipt.get('action', 'action')} "
                f"recorded by {latest_control_receipt.get('receiptId', 'receipt')}."
            )
        lanes.append(
            {
                "role": role,
                "phase": "plan" if role == "planner" else ("verify" if role == "verifier" else "execute"),
                "runtimeId": runtime_id,
                "runtimeLabel": runtime_label(runtime_id),
                "provider": provider,
                "model": model,
                "effort": str(route.get("effort") or active_route.get("effort") or "medium"),
                "authPresent": provider_auth_present,
                "authPath": auth_path or "not configured",
                "authMode": str(provider_auth.get("authMode") or ""),
                "health": health,
                "active": role == active_role or (not active_role and role == "executor"),
                "blocker": blocker,
                "latestControl": latest_control_receipt,
                "laneControlReceipt": latest_control_receipt,
                "controlState": str(latest_control_receipt.get("action") or ""),
                "lastControlEvent": latest_control_detail,
                "failureClass": failure_class,
                "toolFamilies": _provider_tool_families(provider, roles=[role], model=model),
                "quota": _provider_quota_truth(
                    provider,
                    auth_present=provider_auth_present,
                    provider_truth=provider_truth,
                ),
                "actions": [
                    "inspect-events",
                    "resume" if session and session.status in {"running", "waiting_for_approval", "failed", "stopped"} else "open-proof",
                ],
            }
        )
        seen_roles.add(role)
    for item in route_rows:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().lower()
        if role and role not in seen_roles:
            latest_control_receipt = next(
                (
                    receipt
                    for receipt in reversed(lane_control_receipts)
                    if str(receipt.get("role") or "").strip().lower() == role
                ),
                {},
            )
            lanes.append(
                {
                    "role": role,
                    "phase": role,
                    "runtimeId": str(item.get("runtimeId") or item.get("runtime_id") or mission.runtime_id or "").strip().lower(),
                    "runtimeLabel": runtime_label(str(item.get("runtimeId") or item.get("runtime_id") or mission.runtime_id or "")),
                    "provider": str(item.get("provider") or ""),
                    "model": _canonical_runtime_lane_model(
                        str(item.get("provider") or ""),
                        str(item.get("model") or ""),
                        role=role,
                    ),
                    "effort": str(item.get("effort") or "medium"),
                    "authPresent": False,
                    "authPath": "",
                    "authMode": "",
                    "health": "unknown",
                    "active": False,
                    "blocker": "",
                    "latestControl": latest_control_receipt,
                    "laneControlReceipt": latest_control_receipt,
                    "controlState": str(latest_control_receipt.get("action") or ""),
                    "lastControlEvent": (
                        f"Last lane control: {latest_control_receipt.get('action', 'action')} "
                        f"recorded by {latest_control_receipt.get('receiptId', 'receipt')}."
                        if latest_control_receipt
                        else ""
                    ),
                    "failureClass": "unknown",
                    "toolFamilies": _provider_tool_families(str(item.get("provider") or ""), roles=[role]),
                    "quota": _provider_quota_truth(
                        str(item.get("provider") or ""),
                        auth_present=False,
                        provider_truth=provider_truth,
                    ),
                    "actions": ["inspect-events"],
                }
            )
    return lanes


def _canonical_runtime_lane_model(provider: str, model: str, *, role: str = "") -> str:
    normalized_provider = str(provider or "").strip().lower()
    normalized_model = str(model or "").strip()
    if normalized_provider in MINIMAX_PROVIDER_IDS and str(role or "").strip().lower() == "executor":
        return canonical_route_model(normalized_provider, normalized_model)
    return normalized_model


def _route_auth_for_provider(
    provider: str,
    *,
    provider_truth: dict,
    route_auth: dict,
) -> dict:
    normalized = str(provider or "").strip().lower()
    candidates = [normalized]
    if normalized in {"openai", "openai-codex"}:
        candidates.extend(["openai-codex", "openai"])
    elif normalized in {"minimax", "minimax-portal", "minimax-cn", "minimax-oauth"}:
        candidates.extend(["minimax", "minimax-portal", "minimax-oauth", "minimax-cn"])
    for candidate in candidates:
        item = route_auth.get(candidate)
        if isinstance(item, dict):
            return item
    active_route = provider_truth.get("activeRoute") if isinstance(provider_truth.get("activeRoute"), dict) else {}
    active_provider = str(active_route.get("provider") or "").strip().lower()
    if normalized == active_provider or (
        normalized in {"openai", "openai-codex"} and active_provider in {"openai", "openai-codex"}
    ) or (
        normalized in {"minimax", "minimax-portal", "minimax-cn", "minimax-oauth"}
        and active_provider in {"minimax", "minimax-portal", "minimax-cn", "minimax-oauth"}
    ):
        return {
            "provider": normalized,
            "authPresent": bool(provider_truth.get("authPresent")),
            "authMode": str(provider_truth.get("authMode") or ""),
            "authPath": str(provider_truth.get("authPath") or ""),
        }
    return {
        "provider": normalized,
        "authPresent": False,
        "authMode": "",
        "authPath": "not configured",
    }


def _provider_tool_families(provider: str, *, roles: list[str] | None = None, model: str = "") -> list[str]:
    normalized = str(provider or "").strip().lower()
    role_set = {str(role or "").strip().lower() for role in (roles or []) if str(role or "").strip()}
    tools = {"text-generation"}
    if "planner" in role_set:
        tools.update({"planning", "task-routing"})
    if "executor" in role_set:
        tools.update({"code-edit", "artifact-generation"})
    if "verifier" in role_set:
        tools.update({"verification", "review"})
    if normalized in {"openai", "openai-codex"}:
        tools.update({"reasoning", "code", "tool-calling"})
        if normalized == "openai-codex":
            tools.update({"terminal", "patch", "repo-inspection"})
    elif normalized in {"minimax", "minimax-portal", "minimax-cn", "minimax-oauth"}:
        tools.update({"frontend-ui", "multimodal", "creative-iteration"})
    elif normalized:
        tools.add("provider-route")
    if "image" in str(model or "").lower():
        tools.add("image-generation")
    return sorted(tools)


def _provider_quota_truth(
    provider: str,
    *,
    auth_present: bool,
    provider_truth: dict,
) -> dict:
    normalized = str(provider or "").strip().lower()
    quota_payload = provider_truth.get("quota") if isinstance(provider_truth.get("quota"), dict) else {}
    provider_quota = quota_payload.get(normalized) if isinstance(quota_payload.get(normalized), dict) else {}
    if provider_quota:
        return {
            "schema": "fluxio.provider_quota_truth.v1",
            "status": str(provider_quota.get("status") or "reported"),
            "source": str(provider_quota.get("source") or "runtime_provider_report"),
            "remaining": provider_quota.get("remaining"),
            "limit": provider_quota.get("limit"),
            "resetAt": str(provider_quota.get("resetAt") or provider_quota.get("reset_at") or ""),
            "message": str(provider_quota.get("message") or ""),
        }
    return {
        "schema": "fluxio.provider_quota_truth.v1",
        "status": "unreported" if auth_present else "unavailable",
        "source": "runtime_has_no_live_quota_report" if auth_present else "provider_auth_missing",
        "remaining": None,
        "limit": None,
        "resetAt": "",
        "message": (
            "Provider auth is present, but the runtime has not reported live quota or rate-window data."
            if auth_present
            else "Quota cannot be checked until provider auth is present."
        ),
    }


def _provider_failure_class(blocker: object, last_failure: dict | None = None) -> str:
    text = " ".join(
        [
            str(blocker or ""),
            str((last_failure or {}).get("summary") or ""),
            str((last_failure or {}).get("source") or ""),
        ]
    ).lower()
    if not text.strip():
        return "none"
    if any(token in text for token in ("auth", "oauth", "api key", "not present", "credential")):
        return "auth_missing"
    if any(token in text for token in ("quota", "rate limit", "rate-limit", "limit exceeded", "usage")):
        return "provider_quota_or_rate_limit"
    if any(token in text for token in ("timeout", "timed out", "eof", "connection")):
        return "provider_transport"
    if any(token in text for token in ("validation", "route_validation", "model", "unsupported")):
        return "route_validation_failed"
    if any(token in text for token in ("approval", "permission", "denied")):
        return "approval_or_permission"
    return "runtime_failure"


def _provider_capability_contract_for_mission(
    mission: Mission,
    *,
    runtime_lanes: list[dict] | None = None,
) -> dict:
    provider_truth = mission.state.provider_runtime_truth if isinstance(mission.state.provider_runtime_truth, dict) else {}
    active_route = provider_truth.get("activeRoute") if isinstance(provider_truth.get("activeRoute"), dict) else {}
    lanes = list(runtime_lanes) if runtime_lanes is not None else _runtime_lane_rows_for_mission(mission)
    provider_rows: dict[str, dict] = {}
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        provider = str(lane.get("provider") or "").strip().lower()
        if not provider:
            continue
        row = provider_rows.setdefault(
            provider,
            {
                "provider": provider,
                "roles": [],
                "models": [],
                "readyRoles": 0,
                "blockedRoles": 0,
                "authPresent": False,
                "authPath": "",
                "authMode": "",
                "health": "unknown",
                "blockers": [],
                "failureClasses": [],
                "toolFamilies": [],
                "quota": {},
            },
        )
        role = str(lane.get("role") or "").strip().lower()
        if role and role not in row["roles"]:
            row["roles"].append(role)
        model = str(lane.get("model") or "").strip()
        if model and model not in row["models"]:
            row["models"].append(model)
        if bool(lane.get("authPresent")):
            row["authPresent"] = True
            row["readyRoles"] += 1
        else:
            row["blockedRoles"] += 1
        auth_path = str(lane.get("authPath") or "").strip()
        if auth_path and not row["authPath"]:
            row["authPath"] = auth_path
        auth_mode = str(lane.get("authMode") or "").strip()
        if auth_mode and not row["authMode"]:
            row["authMode"] = auth_mode
        for tool in _provider_tool_families(provider, roles=row["roles"], model=model):
            if tool not in row["toolFamilies"]:
                row["toolFamilies"].append(tool)
        if not row["quota"]:
            row["quota"] = lane.get("quota") if isinstance(lane.get("quota"), dict) else _provider_quota_truth(
                provider,
                auth_present=bool(lane.get("authPresent")),
                provider_truth=provider_truth,
            )
        blocker = str(lane.get("blocker") or "").strip()
        if blocker and blocker not in row["blockers"]:
            row["blockers"].append(blocker)
        failure_class = str(lane.get("failureClass") or _provider_failure_class(blocker)).strip()
        if failure_class and failure_class != "none" and failure_class not in row["failureClasses"]:
            row["failureClasses"].append(failure_class)

    providers = []
    for row in provider_rows.values():
        if row["blockedRoles"]:
            row["health"] = "blocked"
        elif row["readyRoles"]:
            row["health"] = "ready"
        providers.append(
            {
                **row,
                "roles": sorted(row["roles"]),
                "models": row["models"][:4],
                "blockers": row["blockers"][:3],
                "failureClasses": row["failureClasses"][:3],
                "toolFamilies": sorted(row["toolFamilies"])[:10],
                "quota": row["quota"] or _provider_quota_truth(
                    str(row.get("provider") or ""),
                    auth_present=bool(row.get("authPresent")),
                    provider_truth=provider_truth,
                ),
            }
        )
    providers.sort(key=lambda item: (item["health"] != "blocked", item["provider"]))

    active_provider = str(active_route.get("provider") or "").strip().lower()
    active_provider_row = next((item for item in providers if item["provider"] == active_provider), {})
    blocked_lanes = [lane for lane in lanes if isinstance(lane, dict) and str(lane.get("health") or "") == "blocked"]
    ready_lanes = [lane for lane in lanes if isinstance(lane, dict) and str(lane.get("health") or "") == "ready"]
    active_auth_present = bool(provider_truth.get("authPresent")) or bool(active_provider_row.get("authPresent"))
    if blocked_lanes:
        status = "blocked"
        next_action = str(blocked_lanes[0].get("blocker") or "Repair or authenticate the blocked provider lane.")
    elif active_provider and active_auth_present:
        status = "ready"
        next_action = "Provider route is authenticated and ready for the current mission phase."
    elif active_provider:
        status = "auth_missing"
        next_action = f"Authenticate {active_provider} before this mission can use the active route."
    else:
        status = "unresolved"
        next_action = "Resolve the mission route contract before dispatching provider work."

    runtime_inventory = _runtime_capability_inventory_for_route(
        mission.runtime_id,
        providers=providers,
        active_provider=active_provider,
    )

    return {
        "schema": "fluxio.provider_capability_contract.v1",
        "source": "live_mission_route_truth",
        "liveData": True,
        "missionId": mission.mission_id,
        "runtimeId": mission.runtime_id,
        "harnessId": mission.harness_id,
        "currentPhase": str(provider_truth.get("currentPhase") or mission.state.current_cycle_phase or "execute"),
        "activeRoute": active_route,
        "status": status,
        "readyLaneCount": len(ready_lanes),
        "blockedLaneCount": len(blocked_lanes),
        "laneCount": len(lanes),
        "quotaSummary": {
            "schema": "fluxio.provider_quota_summary.v1",
            "reportedProviders": sum(
                1
                for item in providers
                if isinstance(item.get("quota"), dict)
                and item["quota"].get("status") not in {"unreported", "unavailable", ""}
            ),
            "unreportedProviders": sum(
                1
                for item in providers
                if isinstance(item.get("quota"), dict)
                and item["quota"].get("status") == "unreported"
            ),
            "nextAction": "Attach runtime/provider quota reports to this contract when a provider exposes them.",
        },
        "toolSummary": {
            "schema": "fluxio.provider_tool_summary.v1",
            "families": sorted({tool for item in providers for tool in item.get("toolFamilies", [])}),
        },
        "failureSummary": {
            "schema": "fluxio.provider_failure_summary.v1",
            "classes": sorted(
                {failure for item in providers for failure in item.get("failureClasses", [])}
            ),
        },
        "providers": providers,
        "lanes": lanes,
        "runtimeCapabilityInventory": runtime_inventory,
        "interchangeable": bool(providers) and not blocked_lanes,
        "nextAction": next_action,
        "updatedAt": str(provider_truth.get("updatedAt") or mission.updated_at or ""),
    }


def _runtime_capability_inventory_for_route(
    runtime_id: str,
    *,
    providers: list[dict],
    active_provider: str = "",
) -> dict:
    normalized_runtime = str(runtime_id or "hermes").strip().lower()
    provider_ids = {str(item.get("provider") or "").strip().lower() for item in providers if isinstance(item, dict)}
    if active_provider:
        provider_ids.add(active_provider)
    return {
        "schema": "fluxio.runtime_capability_inventory.v1",
        "runtimeId": normalized_runtime,
        "items": [
            {
                "key": "hermes_skills_memory",
                "label": "Hermes skills and memory",
                "runtime": "hermes",
                "status": "ready" if normalized_runtime == "hermes" else "available",
                "detail": "Use Hermes for long-running missions, SKILL.md procedures, coding skill recall, and delegation.",
            },
            {
                "key": "hermes_code_mod",
                "label": "Hermes code-mod skills",
                "runtime": "hermes",
                "status": "ready" if normalized_runtime == "hermes" else "available",
                "detail": "Code-mod missions should record selected coding skills such as simplify-code, test-driven-development, codex, or opencode.",
            },
            {
                "key": "openclaw_channels",
                "label": "OpenClaw channels",
                "runtime": "openclaw",
                "status": "ready" if normalized_runtime == "openclaw" else "available",
                "detail": "Use OpenClaw for Telegram/phone channels, remote approvals, gateway sessions, and managed skills.",
            },
            {
                "key": "opencode_go_route",
                "label": "OpenCodeGo route",
                "runtime": "openclaw",
                "status": "ready" if "opencode-go" in provider_ids else "needs_login",
                "detail": "OpenCodeGo uses provider id opencode-go and OPENCODE_API_KEY through OpenClaw/Hermes routing.",
            },
        ],
    }


def _build_runtime_compartments_snapshot(
    root: Path,
    missions: list[Mission],
    *,
    runtime_statuses: list | None = None,
    setup_health: dict | None = None,
    storage_bridge: dict | None = None,
    provider_auth_presence: dict[str, bool] | None = None,
    item_limit: int = 40,
) -> dict:
    items: list[dict] = []
    seen_ids: set[str] = set()

    def compact_runtime_rows(rows: object, *, limit: int, preserve_text: bool = False) -> list[dict]:
        if not isinstance(rows, list):
            return []
        compacted: list[dict] = []
        for row in rows[-limit:]:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            for key in ("message", "detail", "text", "trace", "stdout", "stderr", "content"):
                if key in item and not preserve_text:
                    item[key] = str(item.get(key) or "")[:1200]
            compacted.append(item)
        return compacted

    def compact_text_rows(rows: object, *, limit: int) -> list[str]:
        if not isinstance(rows, list):
            return []
        return [str(item)[:1200] for item in rows[-limit:]]

    compartment_dir = root / ".agent_control" / "runtime_compartments"
    if compartment_dir.exists():
        for path in sorted(compartment_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            session_id = str(payload.get("sessionId") or path.stem).strip()
            if not session_id:
                continue
            seen_ids.add(session_id)
            mission_id = str(payload.get("missionId") or payload.get("mission_id") or "").strip()
            if not mission_id and session_id.startswith("mission-chat-"):
                mission_id = session_id.removeprefix("mission-chat-").strip()
            mission = next((item for item in missions if item.mission_id == mission_id), None) if mission_id else None
            timeline = payload.get("toolTimeline") if isinstance(payload.get("toolTimeline"), list) else []
            route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
            turn_receipt = payload.get("turnReceipt") if isinstance(payload.get("turnReceipt"), dict) else {}
            state = str(payload.get("state") or payload.get("status") or "recorded")
            streaming = str(payload.get("streaming") or payload.get("lifecycle") or "recorded")
            turn_receipts = payload.get("turnReceipts") if isinstance(payload.get("turnReceipts"), list) else []
            # These rows also hydrate the chat transcript. Tool previews may be
            # shortened, but dialogue must retain the complete saved answer.
            messages = compact_runtime_rows(payload.get("messages"), limit=6, preserve_text=True)
            items.append(
                {
                    "id": session_id,
                    "sessionId": session_id,
                    "missionId": mission_id,
                    "missionTitle": str((mission.title or mission.objective) if mission else ""),
                    "runtime": str(payload.get("runtime") or "codex"),
                    "status": state,
                    "state": state,
                    "lifecycle": streaming,
                    "streaming": streaming,
                    "cwd": str(payload.get("cwd") or ""),
                    "host": str(payload.get("host") or ""),
                    "route": route,
                    "updatedAt": str(payload.get("updatedAt") or ""),
                    "source": "web_backend_compartment",
                    "recentActivity": compact_runtime_rows(timeline, limit=6),
                    "toolTimeline": compact_runtime_rows(timeline, limit=8),
                    "turnReceipt": turn_receipt,
                    "turnReceipts": compact_runtime_rows(turn_receipts, limit=4) or ([turn_receipt] if turn_receipt else []),
                    "messages": messages,
                    "lanes": compact_runtime_rows(payload.get("lanes"), limit=6),
                    "blockers": compact_text_rows(payload.get("blockers"), limit=6),
                    "actions": payload.get("actions") if isinstance(payload.get("actions"), list) else ["open-proof"],
                    "restartControls": payload.get("restartControls")
                    if isinstance(payload.get("restartControls"), dict)
                    else {},
                    "filesChanged": compact_text_rows(payload.get("filesChanged"), limit=24),
                    "approvals": compact_runtime_rows(payload.get("approvals"), limit=8),
                }
            )

    for mission in missions:
        for session in mission.delegated_runtime_sessions or []:
            session_id = session.delegated_id or session.session_path or f"{mission.mission_id}:{session.runtime_id}"
            if session_id in seen_ids:
                continue
            seen_ids.add(session_id)
            recent_events = compact_runtime_rows(session.latest_events, limit=6)
            lanes = _runtime_lane_rows_for_mission(mission, session)
            blockers = [
                lane["blocker"]
                for lane in lanes
                if isinstance(lane, dict) and str(lane.get("blocker") or "").strip()
            ]
            items.append(
                {
                    "id": session_id,
                    "sessionId": session.delegated_id,
                    "missionId": mission.mission_id,
                    "missionTitle": mission.title or mission.objective,
                    "runtime": session.runtime_id or mission.runtime_id,
                    "status": session.status or mission.state.status,
                    "state": session.status or mission.state.status,
                    "lifecycle": (
                        "live"
                        if session.status in {"queued", "launching", "running", "waiting_for_approval"}
                        else "recorded"
                    ),
                    "streaming": (
                        "live"
                        if session.status in {"queued", "launching", "running", "waiting_for_approval"}
                        else "recorded"
                    ),
                    "cwd": session.execution_root or session.workspace_root,
                    "host": session.host_locality,
                    "route": {
                        "phase": session.target_phase,
                        "role": session.target_role,
                        "provider": session.target_provider,
                        "model": session.target_model,
                        "effort": session.target_effort,
                    },
                    "updatedAt": session.updated_at,
                    "source": "delegated_runtime_session",
                    "recentActivity": recent_events,
                    "toolTimeline": recent_events,
                    "messages": [],
                    "lanes": lanes,
                    "blockers": blockers,
                    "actions": [
                        "resume" if session.status in {"running", "waiting_for_approval", "failed", "stopped"} else "inspect-events",
                        "open-proof",
                        "restart",
                    ],
                    "restartControls": {
                        "canRestart": True,
                        "canResume": session.status in {"running", "waiting_for_approval", "failed", "stopped"},
                    },
                    "filesChanged": [
                        str(item)[:1200]
                for item in (session.changed_files[-24:] if isinstance(session.changed_files, list) else [])
                    ],
                    "approvals": compact_runtime_rows(session.approval_history, limit=8),
                    "heartbeat": {
                        "status": session.heartbeat_status,
                        "at": session.heartbeat_at,
                        "ageSeconds": session.heartbeat_age_seconds,
                    },
                }
            )

    def sort_key(item: dict) -> str:
        return str(item.get("updatedAt") or "")

    items.sort(key=sort_key, reverse=True)
    live_count = sum(1 for item in items if item.get("lifecycle") == "live")
    compartments = _build_control_compartment_overview(
        root,
        runtime_statuses=runtime_statuses,
        setup_health=setup_health,
        storage_bridge=storage_bridge,
        provider_auth_presence=provider_auth_presence,
    )
    return {
        "items": items[:item_limit],
        "compartments": compartments,
        "summary": {
            "total": len(items),
            "live": live_count,
            "recorded": len(items) - live_count,
            "controlCompartments": len(compartments),
        },
        "emptyState": (
            "No live runtime compartment has been recorded yet. Send a live Agent chat or start a mission to create one."
            if not items
            else ""
        ),
        "source": "agent_control_runtime_state",
    }


def _build_bootstrap_connected_apps_snapshot(root: Path) -> dict:
    from .app_capability_standard import load_mock_manifests

    sessions: list[dict] = []
    try:
        manifests = load_mock_manifests(root)
    except Exception:
        manifests = []
    for manifest in manifests:
        bridge = manifest.bridge if isinstance(manifest.bridge, dict) else {}
        ui_hints = manifest.ui_hints if isinstance(manifest.ui_hints, dict) else {}
        endpoint = str(bridge.get("endpoint") or "")
        healthcheck = str(bridge.get("healthcheck") or "")
        app_root = Path(str(bridge.get("workspace_root") or "")).expanduser() if bridge.get("workspace_root") else None
        solantir_workspace_ready = (
            manifest.app_id == "solantir-terminal"
            and app_root is not None
            and app_root.exists()
        )
        status = "available" if solantir_workspace_ready else "deferred"
        bridge_health = "workspace_ready" if solantir_workspace_ready else "not_checked"
        result_summary = (
            "Solantir NAS fusion workspace is ready for RSS, camera, briefing, route, and DR verification."
            if solantir_workspace_ready
            else (
                f"{manifest.name} bridge health is deferred from the bootstrap summary; "
                "open the full integration check for live status."
            )
        )
        health_url = endpoint.rstrip("/")
        if healthcheck:
            health_url = f"{health_url}/{healthcheck.lstrip('/')}" if health_url else healthcheck
        sessions.append(
            {
                "session_id": f"bridge_{manifest.app_id}",
                "app_id": manifest.app_id,
                "appId": manifest.app_id,
                "app_name": manifest.name,
                "appName": manifest.name,
                "status": status,
                "bridge_health": bridge_health,
                "bridgeHealth": bridge_health,
                "manifest_id": manifest.manifest_id,
                "bridge_endpoint": endpoint,
                "ui_hints": {
                    **ui_hints,
                    "healthUrl": health_url,
                },
                "context_preview": [
                    {
                        "surfaceId": "intelligence-feeds",
                        "label": "Intelligence Feeds",
                        "summary": "RSS, camera, briefing, feed, and DR surfaces are registered from the NAS fusion workspace.",
                    }
                ] if solantir_workspace_ready else [],
                "latest_task_result": {
                    "status": bridge_health,
                    "resultSummary": result_summary,
                    "payload": {
                        "healthUrl": health_url,
                        "startCommand": ui_hints.get("startCommand", ""),
                        "workspaceRoot": str(app_root) if app_root else "",
                        "deliveryReceipt": {
                            "enabled": bool(solantir_workspace_ready),
                            "command": "record_delivery_receipt_command" if solantir_workspace_ready else "",
                        },
                    },
                },
            }
        )
    workspace_ready_count = sum(1 for item in sessions if item.get("bridge_health") == "workspace_ready")
    return {
        "schema": "fluxio.connected_apps_snapshot.v1",
        "source": "bootstrap_manifest_preview",
        "status": "workspace_ready" if workspace_ready_count else "deferred",
        "connectedSessions": sessions,
        "handshakes": [
            {
                "app_id": item["app_id"],
                "transport": "workspace_bridge" if item.get("bridge_health") == "workspace_ready" else "deferred",
                "session_id": item["session_id"],
            }
            for item in sessions
        ],
        "summary": {
            "total": len(sessions),
            "connected": 0,
            "workspaceReady": workspace_ready_count,
            "deferred": len(sessions) - workspace_ready_count,
        },
        "recommendation": (
            "Solantir Terminal workspace bridge is ready for RSS, camera, feed, and DR verification."
            if workspace_ready_count
            else
            "Connected-app bridge health is deferred from bootstrap to keep the first screen responsive."
            if sessions
            else "No connected-app manifests were found."
        ),
    }


def _build_system_audit_digest(
    *,
    root: Path,
    release_readiness: dict,
    harness_lab: dict,
    missions: list[Mission],
    workspaces: list[Workspace],
) -> dict:
    route_trust = (
        harness_lab.get("routeTrustCoverage", {})
        if isinstance(harness_lab.get("routeTrustCoverage"), dict)
        else {}
    )
    operator_confidence = int(route_trust.get("operatorConfidenceScore") or 0)
    proven_task_count = int(route_trust.get("provenTaskCount") or 0)
    task_coverage = (
        route_trust.get("taskCoverage", [])
        if isinstance(route_trust.get("taskCoverage"), list)
        else []
    )
    task_count = max(6, len(task_coverage))
    missing_value_samples = sum(
        max(
            0,
            int(item.get("requiredOperatorValueSamples") or 2)
            - int(item.get("operatorValueSamples") or 0),
        )
        for item in task_coverage
        if isinstance(item, dict)
    )
    if not task_coverage:
        missing_value_samples = 12
    score_cap_reason = (
        "No tracked task category has enough value-scored live route trust evidence yet."
        if proven_task_count < task_count
        else "Route trust is sufficiently sampled; keep value-scored closeouts current."
    )
    categories = [
        {
            "category": "Launch friction and beginner experience",
            "fluxioScore": 16 if proven_task_count < task_count else 18,
            "t3Score": 18,
            "nextAction": "Publish the package entrypoint, signed installer, or external release proof before claiming T3-grade first-run simplicity.",
        },
        {
            "category": "Interface clarity and operator ergonomics",
            "fluxioScore": 14,
            "t3Score": 17,
            "nextAction": "Move secondary diagnostics into drawers and keep Builder/Agent first view focused on mission, next action, progress, and proof.",
        },
        {
            "category": "Multi-project Builder operations",
            "fluxioScore": 18 if proven_task_count < task_count else 20,
            "t3Score": 17,
            "nextAction": "Use per-project history to recommend dependency-aware next missions.",
        },
        {
            "category": "Harness and sub-agent capability",
            "fluxioScore": 16 if proven_task_count < task_count else 19,
            "t3Score": 18,
            "nextAction": "Run repeated value-scored missions per task category.",
        },
        {
            "category": "Web availability and distribution",
            "fluxioScore": 16 if proven_task_count < task_count else 18,
            "t3Score": 18,
            "nextAction": "Attach current public web, release packet, and external publication proof before claiming T3-grade distribution.",
        },
        {
            "category": "Proof, verification, and trust",
            "fluxioScore": 18 if proven_task_count < task_count else 20,
            "t3Score": 14,
            "nextAction": "Attach release proof archives to public or signed release candidates.",
        },
        {
            "category": "Speed and long-history performance",
            "fluxioScore": 18 if proven_task_count < task_count else 19,
            "t3Score": 18,
            "nextAction": "Publish long-history CI proof beside release candidates.",
        },
        {
            "category": "Roadmap clarity and self-improvement",
            "fluxioScore": 16 if proven_task_count < task_count else 19,
            "t3Score": 14,
            "nextAction": "Run the next self-improvement benchmark and close it with value feedback.",
        },
    ]
    deficits = [
        {
            **item,
            "delta": int(item["fluxioScore"]) - int(item["t3Score"]),
            "blockingGap": score_cap_reason,
        }
        for item in categories
        if int(item["fluxioScore"]) <= int(item["t3Score"])
    ]
    deficits.sort(key=lambda item: (item["delta"], item["fluxioScore"], item["category"]))
    t3_reference = _t3_code_reference_snapshot(root)
    system_loss_breakdown = _system_loss_breakdown(
        categories=categories,
        deficits=deficits,
        score_cap_reason=score_cap_reason,
        route_trust={
            **route_trust,
            "missingOperatorValueSamples": missing_value_samples,
            "provenTaskCount": proven_task_count,
            "taskCount": task_count,
        },
        red_summary={},
        release=release_readiness,
        live_progress={},
    )
    active_missions = [
        mission
        for mission in missions
        if _mission_counts_as_active_live(mission, require_queue_front=False)
    ]
    active_gap_missions = []
    for mission in active_missions[:8]:
        active_gap_missions.append(
            {
                "missionId": mission.mission_id,
                "title": mission.title or mission.objective,
                "workspaceId": mission.workspace_id,
                "runtimeId": mission.runtime_id,
                "status": mission.state.status,
                "plannerLoopStatus": mission.state.planner_loop_status,
                "latestSessionId": mission.state.latest_session_id or "",
                "updatedAt": mission.updated_at,
                "gapSignal": _mission_gap_signal(mission),
            }
        )
    gate_summary = release_readiness.get("requiredGateSummary") or {}
    agent_proof_bundle = _agent_proof_bundle_digest(root, {})
    fallback_digest = {
        "schema": "fluxio.system_audit_digest.v1",
        "generatedAt": utc_now_iso(),
        "source": "control_room_heuristic",
        "releaseStatus": release_readiness.get("status", "unknown"),
        "releaseScore": int(release_readiness.get("score") or 0),
        "requiredGatesPassed": int(gate_summary.get("passed") or 0),
        "requiredGatesTotal": int(gate_summary.get("total") or 0),
        "operatorConfidenceScore": operator_confidence,
        "routeTrustStatus": "sampling_needed" if proven_task_count < task_count else "proven",
        "provenTaskCount": proven_task_count,
        "taskCount": task_count,
        "missingOperatorValueSamples": missing_value_samples,
        "scoreCapReason": score_cap_reason,
        "mustBeatStatus": {
            "ahead": len(categories) - len(deficits),
            "total": len(categories),
            "deficitCount": len(deficits),
        },
        "t3Reference": {
            **t3_reference,
            "strengthsToBeat": [
                "npx t3 launch",
                "BYO provider subscriptions",
                "mid-thread model switching",
                "worktrees",
                "diff review",
                "one-click PR creation",
                "perceived UI speed",
            ],
        },
        "categories": categories,
        "deficits": deficits,
        "systemLossBreakdown": system_loss_breakdown,
        "nextAction": (
            deficits[0]["nextAction"]
            if deficits
            else "All tracked categories are above the T3 reference; keep sampling live outcomes."
        ),
        "improvementQueue": _system_improvement_queue(
            bad_first=[],
            deficits=deficits,
            red_summary={},
            route_trust={},
            live_progress={},
        ),
        "liveProjectProgress": {
            "workspaceCount": len(workspaces),
            "missionCount": len(missions),
            "activeMissionCount": len(active_missions),
            "runningMissionIds": [
                mission.mission_id
                for mission in active_missions
                if mission.state.status == "running"
                and not _mission_runtime_budget_exhausted(mission)
            ][:6],
        },
        "activeGapMissions": active_gap_missions,
        "agentProofBundle": agent_proof_bundle,
        "publicLaunchReadiness": _public_launch_readiness_digest(root),
    }
    return _authoritative_system_audit_digest(root, fallback_digest) or fallback_digest


def _build_bootstrap_system_audit_digest(
    *,
    root: Path,
    missions: list[Mission],
    workspaces: list[Workspace],
) -> dict:
    t3_reference = _t3_code_reference_snapshot(root)
    active_missions = [
        mission
        for mission in missions
        if _mission_counts_as_active_live(mission, require_queue_front=False)
    ]
    categories = [
        {
            "category": "Launch friction and beginner experience",
            "fluxioScore": 17,
            "t3Score": 18,
            "nextAction": "Publish the package entrypoint, signed installer, or external release proof before claiming T3-grade first-run simplicity.",
        },
        {
            "category": "Interface clarity and operator ergonomics",
            "fluxioScore": 14,
            "t3Score": 17,
            "nextAction": "Move secondary diagnostics into drawers and keep Builder/Agent first view focused on mission, next action, progress, and proof.",
        },
        {
            "category": "Multi-project Builder operations",
            "fluxioScore": 18,
            "t3Score": 17,
            "nextAction": "Keep live project history and dependency-aware queue state visible in Builder.",
        },
        {
            "category": "Harness and sub-agent capability",
            "fluxioScore": 16,
            "t3Score": 18,
            "nextAction": "Run another value-scored Hermes route sample and verify planner/executor/verifier lanes.",
        },
        {
            "category": "Web availability and distribution",
            "fluxioScore": 16,
            "t3Score": 18,
            "nextAction": "Attach current public web, release packet, and external publication proof before claiming T3-grade distribution.",
        },
        {
            "category": "Proof, verification, and trust",
            "fluxioScore": 18,
            "t3Score": 14,
            "nextAction": "Attach release proof archives to public or signed release candidates.",
        },
        {
            "category": "Speed and long-history performance",
            "fluxioScore": 18,
            "t3Score": 18,
            "nextAction": "Keep bootstrap summary and long-history proof checks below budget.",
        },
        {
            "category": "Roadmap clarity and self-improvement",
            "fluxioScore": 16,
            "t3Score": 14,
            "nextAction": "Run the next self-improvement benchmark and close it with value feedback.",
        },
    ]
    deficits = [
        {
            **item,
            "delta": int(item["fluxioScore"]) - int(item["t3Score"]),
            "blockingGap": "Bootstrap digest uses conservative caps until the full live system audit is loaded.",
        }
        for item in categories
        if int(item["fluxioScore"]) <= int(item["t3Score"])
    ]
    deficits.sort(key=lambda item: (item["delta"], item["fluxioScore"], item["category"]))
    hard_blocked_mission_count = sum(1 for mission in missions if _mission_counts_as_hard_blocked(mission))
    runtime_budget_attention_mission_count = sum(
        1 for mission in missions if _mission_runtime_budget_exhausted(mission)
    )
    live_progress = {
        "workspaceCount": len(workspaces),
        "missionCount": len(missions),
        "activeMissionCount": sum(
            1
            for mission in missions
            if _mission_counts_as_active_live(mission)
        ),
        "completedMissionCount": sum(1 for mission in missions if mission.state.status == "completed"),
        "blockedMissionCount": hard_blocked_mission_count,
        "attentionMissionCount": hard_blocked_mission_count + runtime_budget_attention_mission_count,
        "runtimeBudgetAttentionMissionCount": runtime_budget_attention_mission_count,
        "queuedMissionCount": sum(
            1
            for mission in missions
            if mission.state.status not in TERMINAL_MISSION_STATUSES and mission.state.queue_position > 0
        ),
    }
    nas_storage_pressure = _live_storage_pressure_probe(root)
    live_mission_output_quality = _bootstrap_live_mission_output_quality(missions)
    mission_artifact_repair_plan = _bootstrap_mission_artifact_repair_plan(
        live_mission_output_quality=live_mission_output_quality,
        nas_storage_pressure=nas_storage_pressure,
    )
    route_trust = {
        "status": "bootstrap_pending_full_audit",
        "operatorConfidenceScore": 0,
        "provenTaskCount": 0,
        "taskCount": 6,
        "missingOperatorValueSamples": 12,
        "nextAction": "Load the full live system audit, then close missing value-scored route samples.",
    }
    system_loss_breakdown = _system_loss_breakdown(
        categories=categories,
        deficits=deficits,
        score_cap_reason="Bootstrap digest uses conservative caps until the full live system audit is loaded.",
        route_trust=route_trust,
        red_summary={},
        release={},
        live_progress=live_progress,
    )
    fallback_digest = {
        "schema": "fluxio.system_audit_digest.v1",
        "generatedAt": utc_now_iso(),
        "source": "bootstrap_control_room_heuristic",
        "systemScoreOutOf20": round(
            sum(int(item["fluxioScore"]) for item in categories) / max(len(categories), 1),
            1,
        ),
        "operatorConfidenceScore": 0,
        "routeTrustStatus": "bootstrap_pending_full_audit",
        "provenTaskCount": 0,
        "taskCount": 6,
        "missingOperatorValueSamples": 12,
        "scoreCapReason": "Bootstrap digest uses conservative caps until the full live system audit is loaded.",
        "mustBeatStatus": {
            "ahead": len(categories) - len(deficits),
            "total": len(categories),
            "deficitCount": len(deficits),
        },
        "t3Reference": {
            **t3_reference,
            "strengthsToBeat": [
                "npx t3 launch",
                "BYO provider subscriptions",
                "mid-thread model switching",
                "worktrees",
                "diff review",
                "one-click PR creation",
                "perceived UI speed",
            ],
        },
        "categories": categories,
        "deficits": deficits,
        "systemLossBreakdown": system_loss_breakdown,
        "badFirst": [
            {
                "title": item["category"],
                "detail": item["blockingGap"],
            }
            for item in deficits[:4]
        ],
        "improvementQueue": _system_improvement_queue(
            bad_first=[],
            deficits=deficits,
            red_summary={},
            route_trust=route_trust,
            live_progress=live_progress,
        ),
        "liveProjectProgress": live_progress,
        "nasStoragePressure": nas_storage_pressure,
        "liveMissionOutputQuality": live_mission_output_quality,
        "missionArtifactRepairPlan": mission_artifact_repair_plan,
        "activeGapMissions": [
            {
                "missionId": mission.mission_id,
                "title": mission.title or mission.objective,
                "workspaceId": mission.workspace_id,
                "runtimeId": mission.runtime_id,
                "status": mission.state.status,
                "plannerLoopStatus": mission.state.planner_loop_status,
                "latestSessionId": mission.state.latest_session_id or "",
                "updatedAt": mission.updated_at,
                "gapSignal": _mission_gap_signal(mission),
            }
            for mission in active_missions[:8]
        ],
        "nextAction": (
            deficits[0]["nextAction"]
            if deficits
            else "Load the full live system audit and keep value-scored outcomes current."
        ),
        "publicLaunchReadiness": _public_launch_readiness_digest(root),
    }
    return _authoritative_system_audit_digest(root, fallback_digest) or fallback_digest


@_mission_local_checked('public')

def _public_launch_readiness_digest(root: Path, source: dict | None=None) -> dict:

    latest_payload = _load_json_file(root / '.agent_control' / 'public_launch_readiness' / 'latest.json')

    latest_payload = latest_payload if isinstance(latest_payload, dict) else {}

    payload = source if isinstance(source, dict) else latest_payload

    if isinstance(source, dict) and latest_payload.get('schema') == 'fluxio.public_launch_readiness.v1':

        source_checked_at = _parse_iso_datetime(str(source.get('checkedAt') or ''))

        latest_checked_at = _parse_iso_datetime(str(latest_payload.get('checkedAt') or ''))

        if latest_checked_at and (not source_checked_at or latest_checked_at >= source_checked_at):

            payload = latest_payload

    if not isinstance(payload, dict) or payload.get('schema') != 'fluxio.public_launch_readiness.v1':

        return {'schema': 'fluxio.public_launch_readiness_digest.v1', 'status': 'missing', 'ok': False, 'internalPacketReady': False, 'missing': ['public_launch_readiness'], 'blockers': [{'checkId': 'public_launch_readiness', 'details': 'Run verify:public-launch so Builder can show public launch blockers.'}], 'nextAction': 'Run verify:public-launch and publish the current evidence.'}

    missing = [str(item) for item in payload.get('missing', []) if str(item or '').strip()] if isinstance(payload.get('missing'), list) else []

    blockers = [{'checkId': str(item.get('checkId') or ''), 'details': str(item.get('details') or '')} for item in payload.get('blockers', []) if isinstance(item, dict)] if isinstance(payload.get('blockers'), list) else []

    checks = [{'checkId': str(item.get('checkId') or ''), 'passed': bool(item.get('passed')), 'details': str(item.get('details') or ''), 'url': str(item.get('url') or item.get('controlUrl') or ''), 'workflowRun': str(item.get('workflowRun') or ''), 'sourceDirtyPathCount': int(item.get('sourceDirtyPathCount') or 0), 'sourceDirtyPathSample': [str(path) for path in item.get('sourceDirtyPathSample', []) if str(path or '').strip()][:20] if isinstance(item.get('sourceDirtyPathSample'), list) else []} for item in payload.get('checks', []) if isinstance(item, dict) and str(item.get('checkId') or '').strip()] if isinstance(payload.get('checks'), list) else []

    return {'schema': 'fluxio.public_launch_readiness_digest.v1', 'status': str(payload.get('status') or 'unknown'), 'ok': bool(payload.get('ok')), 'internalPacketReady': bool(payload.get('internalPacketReady')), 'checks': checks, 'missing': missing, 'blockers': blockers[:6], 'repairPacket': payload.get('repairPacket', {}) if isinstance(payload.get('repairPacket'), dict) else {}, 'publicWeb': payload.get('publicWeb', {}) if isinstance(payload.get('publicWeb'), dict) else {}, 'publicationProof': payload.get('publicationProof', {}) if isinstance(payload.get('publicationProof'), dict) else {}, 'stagingProof': payload.get('stagingProof', {}) if isinstance(payload.get('stagingProof'), dict) else {}, 'releaseCandidate': payload.get('releaseCandidate', {}) if isinstance(payload.get('releaseCandidate'), dict) else {}, 'nextAction': str(payload.get('nextAction') or ''), 'checkedAt': str(payload.get('checkedAt') or '')}


def _agent_proof_bundle_digest(root: Path, live_nas: dict) -> dict:
    live_nas = live_nas if isinstance(live_nas, dict) else {}
    latest_path = root / ".agent_control" / "authenticated_live_agent_latest.json"
    latest = _load_json_file(latest_path)
    if not isinstance(latest, dict):
        latest = {}
    latest_schema_valid = latest.get("schema") == "fluxio.authenticated_live_agent_latest_evidence.v1"
    proof_bundle = (
        latest.get("proofBundle", {})
        if latest_schema_valid and isinstance(latest.get("proofBundle"), dict)
        else {}
    )
    open_proof = (
        latest.get("openCompleteProof", {})
        if latest_schema_valid and isinstance(latest.get("openCompleteProof"), dict)
        else {}
    )
    first_view_path = (
        latest.get("firstViewProofPath", {})
        if latest_schema_valid and isinstance(latest.get("firstViewProofPath"), dict)
        else {}
    )
    selected = (
        latest.get("selectedMission", {})
        if latest_schema_valid and isinstance(latest.get("selectedMission"), dict)
        else {}
    )
    check_summary = (
        latest.get("checkSummary", {})
        if latest_schema_valid and isinstance(latest.get("checkSummary"), dict)
        else {}
    )
    live_selected = live_nas.get("agentSelectedMission") if isinstance(live_nas.get("agentSelectedMission"), dict) else {}
    status = str(live_nas.get("agentProofBundleStatus") or proof_bundle.get("status") or "").strip()
    label = str(live_nas.get("agentProofBundleLabel") or proof_bundle.get("label") or "").strip()
    latest_runtime_status = str(
        live_nas.get("agentLatestRuntimeStatus") or proof_bundle.get("latestRuntimeStatus") or ""
    ).strip()
    latest_evidence_status = str(
        live_nas.get("agentLatestEvidenceStatus") or proof_bundle.get("latestEvidenceStatus") or ""
    ).strip()
    latest_complete_mission_id = str(
        live_nas.get("agentLatestCompleteMissionId") or proof_bundle.get("latestCompleteMissionId") or ""
    ).strip()
    open_complete_target = str(
        live_nas.get("agentOpenCompleteProofTargetMissionId") or open_proof.get("targetMissionId") or ""
    ).strip()
    first_view_proof_path_passed = bool(
        live_nas.get("agentFirstViewProofPathPassed")
        or first_view_path.get("passed")
    )
    first_view_proof_path_row_count = int(
        live_nas.get("agentFirstViewProofPathRowCount")
        or first_view_path.get("rowCount")
        or 0
    )
    first_view_proof_path_next_action_count = int(
        live_nas.get("agentFirstViewProofPathNextActionCount")
        or first_view_path.get("nextActionCount")
        or 0
    )
    latest_evidence_path = str(live_nas.get("agentLatestEvidencePath") or "").strip()
    if not latest_evidence_path and latest_schema_valid:
        latest_evidence_path = str(latest_path)
    if not any((status, latest_runtime_status, latest_evidence_status, open_complete_target, latest_evidence_path)):
        return {}
    selected_mission_id = str(
        live_selected.get("mission_id")
        or live_selected.get("missionId")
        or selected.get("missionId")
        or selected.get("mission_id")
        or ""
    )
    source_report_path = str(live_nas.get("agentReportPath") or latest.get("sourceReportPath") or "").strip()
    passed_check_count = (
        len(live_nas.get("agentPassedChecks") or [])
        if isinstance(live_nas.get("agentPassedChecks"), list)
        else 0
    )
    if not passed_check_count:
        passed_check_count = int(check_summary.get("passed") or 0)
    return {
        "schema": "fluxio.agent_proof_bundle_digest.v1",
        "source": "live_nas_evidence" if live_nas else "authenticated_live_agent_latest",
        "status": status or "unknown",
        "label": label,
        "complete": bool(
            live_nas.get("agentProofBundleComplete")
            or proof_bundle.get("hasCompleteEvidenceBundle")
            or status == "complete"
        ),
        "agentStatus": str(
            live_nas.get("agentStatus")
            or ("passed" if latest.get("ok") else "failed" if latest_schema_valid else "unknown")
        ),
        "selectedMissionId": selected_mission_id,
        "latestRuntimeStatus": latest_runtime_status,
        "latestEvidenceStatus": latest_evidence_status,
        "latestCompleteMissionId": latest_complete_mission_id,
        "openCompleteProofTargetMissionId": open_complete_target,
        "openCompleteProofStatus": str(
            live_nas.get("agentOpenCompleteProofStatus")
            or ("passed" if open_proof.get("passed") else "")
        ),
        "firstViewProofPathPassed": first_view_proof_path_passed,
        "firstViewProofPathRowCount": first_view_proof_path_row_count,
        "firstViewProofPathNextActionCount": first_view_proof_path_next_action_count,
        "latestEvidencePath": latest_evidence_path,
        "sourceReportPath": source_report_path,
        "checkedAt": str(live_nas.get("agentCheckedAt") or latest.get("checkedAt") or ""),
        "indexedAt": str(live_nas.get("agentLatestIndexedAt") or latest.get("indexedAt") or ""),
        "passedCheckCount": passed_check_count,
        "failedCheckCount": int(check_summary.get("failed") or 0),
    }


def _authoritative_system_audit_digest(root: Path, fallback_digest: dict) -> dict:
    evidence_path = root / ".agent_control" / "live_nas_system_audit_latest.json"
    cached_digest = _load_compact_system_audit_digest(root, evidence_path, fallback_digest)
    if cached_digest:
        return cached_digest
    payload = _load_json_file(evidence_path)
    if not isinstance(payload, dict):
        return {}
    audit = payload.get("audit") if isinstance(payload.get("audit"), dict) else payload
    if not isinstance(audit, dict) or not isinstance(audit.get("categories"), list):
        return {}

    categories: list[dict] = []
    for item in audit.get("categories", []):
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "").strip()
        if not category:
            continue
        fluxio_score = int(item.get("score_out_of_20") or item.get("fluxioScore") or 0)
        t3_score = int(item.get("t3_reference_score_out_of_20") or item.get("t3Score") or 0)
        next_moves = item.get("next_moves") if isinstance(item.get("next_moves"), list) else []
        gaps = item.get("gaps") if isinstance(item.get("gaps"), list) else []
        categories.append(
            {
                "category": category,
                "fluxioScore": fluxio_score,
                "t3Score": t3_score,
                "delta": fluxio_score - t3_score,
                "verdict": str(item.get("verdict") or ""),
                "blockingGap": str(gaps[0] if gaps else ""),
                "nextAction": str(next_moves[0] if next_moves else ""),
            }
        )

    if not categories:
        return {}

    deficits: list[dict] = []
    for item in audit.get("t3Deficits", []):
        if not isinstance(item, dict):
            continue
        deficits.append(
            {
                "category": str(item.get("category") or ""),
                "fluxioScore": int(item.get("fluxioScore") or 0),
                "t3Score": int(item.get("t3Score") or 0),
                "delta": int(item.get("delta") or 0),
                "blockingGap": str(item.get("blockingGap") or ""),
                "nextAction": str(item.get("nextMove") or item.get("nextAction") or ""),
            }
        )
    if not deficits:
        deficits = [item for item in categories if int(item.get("fluxioScore") or 0) <= int(item.get("t3Score") or 0)]
    deficits.sort(key=lambda item: (int(item.get("delta") or 0), int(item.get("fluxioScore") or 0), item.get("category") or ""))

    route_trust = audit.get("routeTrustMaturity") if isinstance(audit.get("routeTrustMaturity"), dict) else {}
    release = audit.get("releaseReadiness") if isinstance(audit.get("releaseReadiness"), dict) else {}
    public_launch_readiness = _public_launch_readiness_digest(
        root,
        audit.get("publicLaunchReadinessEvidence")
        if isinstance(audit.get("publicLaunchReadinessEvidence"), dict)
        else None,
    )
    gate_summary = release.get("requiredGateSummary") if isinstance(release.get("requiredGateSummary"), dict) else {}
    live_nas = audit.get("liveNasEvidence") if isinstance(audit.get("liveNasEvidence"), dict) else {}
    agent_proof_bundle = _agent_proof_bundle_digest(root, live_nas)
    nas_storage_pressure = audit.get("nasStoragePressureEvidence") if isinstance(audit.get("nasStoragePressureEvidence"), dict) else {}
    nas_storage_cleanup_plan = audit.get("nasStorageCleanupPlan") if isinstance(audit.get("nasStorageCleanupPlan"), dict) else {}
    if not nas_storage_pressure:
        nas_storage_pressure = _load_json_file(root / ".agent_control" / "nas_storage_pressure_latest.json")
        if not isinstance(nas_storage_pressure, dict):
            nas_storage_pressure = {}
    if not nas_storage_pressure and isinstance(fallback_digest.get("nasStoragePressure"), dict):
        nas_storage_pressure = dict(fallback_digest["nasStoragePressure"])
    if not nas_storage_pressure:
        nas_storage_pressure = _live_storage_pressure_probe(root)
    if not nas_storage_cleanup_plan:
        nas_storage_cleanup_plan = _load_json_file(root / ".agent_control" / "nas_storage_cleanup_plan_latest.json")
        if not isinstance(nas_storage_cleanup_plan, dict):
            nas_storage_cleanup_plan = {}
    live_mission_output_quality = audit.get("liveMissionOutputQualityEvidence") if isinstance(audit.get("liveMissionOutputQualityEvidence"), dict) else {}
    mission_artifact_repair_plan = audit.get("missionArtifactRepairPlan") if isinstance(audit.get("missionArtifactRepairPlan"), dict) else {}
    fallback_live_mission_output_quality = (
        fallback_digest.get("liveMissionOutputQuality")
        if isinstance(fallback_digest.get("liveMissionOutputQuality"), dict)
        else {}
    )
    fallback_mission_artifact_repair_plan = (
        fallback_digest.get("missionArtifactRepairPlan")
        if isinstance(fallback_digest.get("missionArtifactRepairPlan"), dict)
        else {}
    )
    local_live_mission_output_quality = _local_live_mission_output_quality(root)
    if not live_mission_output_quality:
        live_mission_output_quality = local_live_mission_output_quality
    if not live_mission_output_quality:
        live_mission_output_quality = fallback_live_mission_output_quality
    elif local_live_mission_output_quality:
        audit_checked = _parse_iso_datetime(str(live_mission_output_quality.get("checkedAt") or ""))
        local_checked = _parse_iso_datetime(str(local_live_mission_output_quality.get("checkedAt") or ""))
        if local_checked and (not audit_checked or local_checked > audit_checked):
            live_mission_output_quality = local_live_mission_output_quality
        elif (
            not isinstance(live_mission_output_quality.get("repairMissionRows"), list)
            and isinstance(local_live_mission_output_quality.get("repairMissionRows"), list)
        ):
            live_mission_output_quality = local_live_mission_output_quality
    local_mission_artifact_repair_plan = _load_json_file(root / ".agent_control" / "mission_artifact_repair_plan_latest.json")
    if not isinstance(local_mission_artifact_repair_plan, dict):
        local_mission_artifact_repair_plan = {}
    if not mission_artifact_repair_plan:
        mission_artifact_repair_plan = local_mission_artifact_repair_plan
    if not mission_artifact_repair_plan:
        mission_artifact_repair_plan = fallback_mission_artifact_repair_plan
    elif local_mission_artifact_repair_plan:
        audit_plan_ts = _parse_iso_datetime(str(mission_artifact_repair_plan.get("generatedAt") or ""))
        local_plan_ts = _parse_iso_datetime(str(local_mission_artifact_repair_plan.get("generatedAt") or ""))
        audit_manifest = mission_artifact_repair_plan.get("missionEvidenceScreenshotManifest")
        local_manifest = local_mission_artifact_repair_plan.get("missionEvidenceScreenshotManifest")
        audit_screenshot_count = (
            int(audit_manifest.get("screenshotCount") or 0)
            if isinstance(audit_manifest, dict)
            else 0
        )
        local_screenshot_count = (
            int(local_manifest.get("screenshotCount") or 0)
            if isinstance(local_manifest, dict)
            else 0
        )
        if local_plan_ts and (not audit_plan_ts or local_plan_ts > audit_plan_ts):
            mission_artifact_repair_plan = local_mission_artifact_repair_plan
        elif local_screenshot_count > audit_screenshot_count:
            mission_artifact_repair_plan = local_mission_artifact_repair_plan
    red_team = audit.get("redTeamEscalationEvidence") if isinstance(audit.get("redTeamEscalationEvidence"), dict) else {}
    watchdog_self_improvement = _watchdog_self_improvement_history_digest(root)
    summary_performance = audit.get("liveSummaryPerformanceEvidence") if isinstance(audit.get("liveSummaryPerformanceEvidence"), dict) else {}
    detail_performance = audit.get("liveMissionDetailPerformanceEvidence") if isinstance(audit.get("liveMissionDetailPerformanceEvidence"), dict) else {}
    local_summary_performance = _load_json_file(root / ".agent_control" / "live_summary_performance_latest.json")
    if isinstance(local_summary_performance, dict) and (
        not summary_performance
        or (
            _parse_iso_datetime(str(local_summary_performance.get("checkedAt") or ""))
            and (
                not _parse_iso_datetime(str(summary_performance.get("checkedAt") or ""))
                or _parse_iso_datetime(str(local_summary_performance.get("checkedAt") or ""))
                > _parse_iso_datetime(str(summary_performance.get("checkedAt") or ""))
            )
        )
    ):
        summary_performance = local_summary_performance
    local_detail_performance = _load_json_file(root / ".agent_control" / "live_mission_detail_performance_latest.json")
    if isinstance(local_detail_performance, dict) and (
        not detail_performance
        or (
            _parse_iso_datetime(str(local_detail_performance.get("checkedAt") or ""))
            and (
                not _parse_iso_datetime(str(detail_performance.get("checkedAt") or ""))
                or _parse_iso_datetime(str(local_detail_performance.get("checkedAt") or ""))
                > _parse_iso_datetime(str(detail_performance.get("checkedAt") or ""))
            )
        )
    ):
        detail_performance = local_detail_performance
    red_summary = red_team.get("summary") if isinstance(red_team.get("summary"), dict) else {}
    red_history = red_team.get("history") if isinstance(red_team.get("history"), list) else []
    red_latest = normalize_red_team_pressure(red_history[-1]) if red_history and isinstance(red_history[-1], dict) else {}
    effective_red_summary = {
        **red_latest,
        **red_summary,
    }
    if not int(effective_red_summary.get("currentPressureIndex") or 0):
        effective_red_summary["currentPressureIndex"] = int(red_latest.get("currentPressureIndex") or 0)
    if not int(effective_red_summary.get("nextPressureIndex") or 0):
        effective_red_summary["nextPressureIndex"] = int(red_latest.get("nextPressureIndex") or 0)
    if not int(effective_red_summary.get("pressureDelta") or 0):
        effective_red_summary["pressureDelta"] = int(red_latest.get("pressureDelta") or 0)
    if not str(effective_red_summary.get("nextDifficultyLabel") or ""):
        effective_red_summary["nextDifficultyLabel"] = str(red_latest.get("nextDifficultyLabel") or "")
    normalized_red_history = [
        normalize_red_team_pressure(item)
        for item in red_history
        if isinstance(item, dict)
    ]
    generated_red_plan = _red_team_next_benchmark_plan(
        normalized_red_history,
        red_team.get("escalationAudit") if isinstance(red_team.get("escalationAudit"), dict) else {},
    )
    embedded_red_plan = red_team.get("nextBenchmarkPlan") if isinstance(red_team.get("nextBenchmarkPlan"), dict) else {}
    effective_red_plan = {
        **generated_red_plan,
        **embedded_red_plan,
    }
    for key in (
        "difficultyLabel",
        "levelCapReached",
        "currentPressureIndex",
        "nextPressureIndex",
        "pressureDelta",
        "successCriteria",
    ):
        if key not in embedded_red_plan or embedded_red_plan.get(key) in ("", None, [], {}):
            effective_red_plan[key] = generated_red_plan.get(key)
    if not isinstance(effective_red_plan.get("command"), dict) or "pressure" not in str(
        effective_red_plan.get("command", {}).get("shell") or ""
    ):
        effective_red_plan["command"] = generated_red_plan.get("command", {})
    benchmark = (audit.get("benchmarks") or {}).get("t3Code") if isinstance(audit.get("benchmarks"), dict) else {}
    if not isinstance(benchmark, dict):
        benchmark = {}
    bad_first = audit.get("badFirst") if isinstance(audit.get("badFirst"), list) else []
    first_bad = next((item for item in bad_first if isinstance(item, dict)), {})
    score_cap_reason = (
        str(route_trust.get("capReason") or "")
        or str(first_bad.get("detail") or "")
        or str(fallback_digest.get("scoreCapReason") or "")
    )
    active_gap_missions = fallback_digest.get("activeGapMissions") if isinstance(fallback_digest.get("activeGapMissions"), list) else []
    live_progress = fallback_digest.get("liveProjectProgress") if isinstance(fallback_digest.get("liveProjectProgress"), dict) else {}
    counts = live_nas.get("counts") if isinstance(live_nas.get("counts"), dict) else {}
    live_nas_passed_checks = [
        str(item)
        for item in live_nas.get("passedChecks", [])
        if isinstance(item, str)
    ] if isinstance(live_nas.get("passedChecks"), list) else []
    if counts:
        live_progress = {
            **live_progress,
            "workspaceCount": max(int(live_progress.get("workspaceCount") or 0), int(counts.get("workspaces") or 0)),
            "missionCount": max(int(live_progress.get("missionCount") or 0), int(counts.get("missions") or 0)),
            "activeMissionCount": int(live_progress.get("activeMissionCount") or 0),
            "completedMissionCount": max(int(live_progress.get("completedMissionCount") or 0), int(counts.get("completedMissions") or 0)),
            "blockedMissionCount": max(int(live_progress.get("blockedMissionCount") or 0), int(counts.get("blockedMissions") or 0)),
            "attentionMissionCount": max(
                int(live_progress.get("attentionMissionCount") or 0),
                int(counts.get("attentionMissions") or counts.get("blockedMissions") or 0),
            ),
            "runtimeBudgetAttentionMissionCount": max(
                int(live_progress.get("runtimeBudgetAttentionMissionCount") or 0),
                int(counts.get("runtimeBudgetAttentionMissions") or 0),
            ),
            "queuedMissionCount": max(int(live_progress.get("queuedMissionCount") or 0), int(counts.get("queuedMissions") or 0)),
            "schedulerQueueProofPassed": (
                bool(live_progress.get("schedulerQueueProofPassed"))
                or "summary-has-live-project-scheduling-queue" in live_nas_passed_checks
            ),
        }
    t3_strengths = [
        "npx t3 launch",
        "BYO provider subscriptions",
        "mid-thread model switching",
        "worktrees",
        "diff review",
        "one-click PR creation",
        "perceived UI speed",
    ]
    observed_strengths = benchmark.get("observedStrengths") if isinstance(benchmark.get("observedStrengths"), list) else []
    if observed_strengths:
        t3_strengths = [str(item) for item in observed_strengths[:8]]
    current_t3_reference = _t3_code_reference_snapshot(root)
    current_t3_release = str(current_t3_reference.get("latestObservedRelease") or "")
    if "not been refreshed" in current_t3_release.lower():
        current_t3_release = ""
    system_loss_breakdown = _system_loss_breakdown(
        categories=categories,
        deficits=deficits,
        score_cap_reason=score_cap_reason,
        route_trust=route_trust,
        red_summary=effective_red_summary,
        release=release,
        live_progress=live_progress,
        nas_storage_pressure=nas_storage_pressure,
        live_mission_output_quality=live_mission_output_quality,
    )
    design_debt_summary = _design_debt_summary(
        categories=categories,
        deficits=deficits,
        bad_first=bad_first,
        system_loss_breakdown=system_loss_breakdown,
        live_mission_output_quality=live_mission_output_quality,
        mission_artifact_repair_plan=mission_artifact_repair_plan,
        nas_storage_pressure=nas_storage_pressure,
        agent_proof_bundle=agent_proof_bundle,
    )
    mission_advancement_summary = _mission_advancement_summary(
        live_mission_output_quality=live_mission_output_quality,
        mission_artifact_repair_plan=mission_artifact_repair_plan,
        live_progress=live_progress,
    )
    storage_triage_summary = _storage_triage_summary(
        nas_storage_pressure=nas_storage_pressure,
        nas_storage_cleanup_plan=nas_storage_cleanup_plan,
    )
    deployment_durability_summary = _deployment_durability_summary(
        root=root,
        nas_storage_pressure=nas_storage_pressure,
        storage_triage_summary=storage_triage_summary,
    )
    operator_next_path = _operator_next_path_summary(
        storage_triage_summary=storage_triage_summary,
        mission_advancement_summary=mission_advancement_summary,
        mission_artifact_repair_plan=mission_artifact_repair_plan,
        deficits=deficits,
        public_launch_readiness=public_launch_readiness,
        route_trust=route_trust,
    )
    speed_supervisor_summary = _speed_supervisor_summary(
        root=root,
        summary_performance=summary_performance,
        detail_performance=detail_performance,
        watchdog_self_improvement=watchdog_self_improvement,
        red_summary=effective_red_summary,
        mission_advancement_summary=mission_advancement_summary,
    )
    must_beat_status = {
        "ahead": len(categories) - len(deficits),
        "total": len(categories),
        "deficitCount": len(deficits),
    }
    t3_reference = {
        **current_t3_reference,
        "name": str(benchmark.get("name") or current_t3_reference.get("name") or "T3 Code"),
        "latestObservedRelease": str(
            current_t3_release
            or benchmark.get("latestObservedRelease")
            or fallback_digest.get("t3Reference", {}).get("latestObservedRelease")
            or ""
        ),
        "strengthsToBeat": t3_strengths,
    }
    goal_completion_audit = _goal_completion_audit_summary(
        system_loss_breakdown=system_loss_breakdown,
        speed_supervisor_summary=speed_supervisor_summary,
        design_debt_summary=design_debt_summary,
        mission_advancement_summary=mission_advancement_summary,
        storage_triage_summary=storage_triage_summary,
        deployment_durability_summary=deployment_durability_summary,
        public_launch_readiness=public_launch_readiness,
        route_trust=route_trust,
        red_summary=effective_red_summary,
        live_progress=live_progress,
        t3_reference=t3_reference,
        must_beat_status=must_beat_status,
    )

    digest = {
        **fallback_digest,
        "source": "live_nas_system_audit",
        "evidencePath": str(evidence_path),
        "generatedAt": str(audit.get("generatedAt") or payload.get("checkedAt") or utc_now_iso()),
        "summary": str(audit.get("summary") or ""),
        "systemScoreOutOf20": round(
            sum(int(item.get("fluxioScore") or 0) for item in categories) / max(len(categories), 1),
            1,
        ),
        "releaseStatus": release.get("status", fallback_digest.get("releaseStatus", "unknown")),
        "releaseScore": int(release.get("score") or fallback_digest.get("releaseScore") or 0),
        "requiredGatesPassed": int(gate_summary.get("passed") or fallback_digest.get("requiredGatesPassed") or 0),
        "requiredGatesTotal": int(gate_summary.get("total") or fallback_digest.get("requiredGatesTotal") or 0),
        "operatorConfidenceScore": int(route_trust.get("operatorConfidenceScore") or fallback_digest.get("operatorConfidenceScore") or 0),
        "routeTrustStatus": str(route_trust.get("status") or fallback_digest.get("routeTrustStatus") or "unknown"),
        "provenTaskCount": int(route_trust.get("provenTaskCount") or fallback_digest.get("provenTaskCount") or 0),
        "taskCount": int(route_trust.get("taskCount") or fallback_digest.get("taskCount") or 0),
        "missingOperatorValueSamples": int(route_trust.get("missingOperatorValueSamples") or 0),
        "scoreCapReason": score_cap_reason,
        "mustBeatStatus": must_beat_status,
        "t3Reference": t3_reference,
        "categories": categories,
        "deficits": deficits,
        "goalCompletionAudit": goal_completion_audit,
        "systemLossBreakdown": system_loss_breakdown,
        "designDebtSummary": design_debt_summary,
        "missionAdvancementSummary": mission_advancement_summary,
        "storageTriageSummary": storage_triage_summary,
        "deploymentDurabilitySummary": deployment_durability_summary,
        "operatorNextPath": operator_next_path,
        "speedSupervisorSummary": speed_supervisor_summary,
        "agentProofBundle": agent_proof_bundle or fallback_digest.get("agentProofBundle", {}),
        "nasStoragePressure": nas_storage_pressure,
        "nasStorageCleanupPlan": nas_storage_cleanup_plan,
        "liveMissionOutputQuality": live_mission_output_quality,
        "missionArtifactRepairPlan": mission_artifact_repair_plan,
        "publicLaunchReadiness": public_launch_readiness,
        "badFirst": bad_first[:6],
        "improvementQueue": _system_improvement_queue(
            bad_first=bad_first,
            deficits=deficits,
            red_summary=effective_red_summary,
            route_trust=route_trust,
            live_progress=live_progress,
        ),
        "redTeamEscalation": {
            "schema": str(red_team.get("schema") or "fluxio.red_team_escalation_snapshot.v1"),
            "summary": effective_red_summary,
            "history": [
                item
                for item in red_history[-8:]
                if isinstance(item, dict)
            ],
            "nextBenchmarkPlan": effective_red_plan,
            "historyRows": int(effective_red_summary.get("runCount") or 0),
            "latestResistanceScore": int(effective_red_summary.get("latestResistanceScore") or effective_red_summary.get("resistance_score") or 0),
            "latestDifficultyLevel": int(effective_red_summary.get("latestDifficultyLevel") or effective_red_summary.get("difficultyLevel") or 0),
            "nextDifficultyLevel": int(effective_red_summary.get("nextDifficultyLevel") or 0),
            "currentPressureIndex": int(effective_red_summary.get("currentPressureIndex") or 0),
            "nextPressureIndex": int(effective_red_summary.get("nextPressureIndex") or 0),
            "pressureDelta": int(effective_red_summary.get("pressureDelta") or 0),
            "nextDifficultyLabel": str(effective_red_summary.get("nextDifficultyLabel") or ""),
            "nextAttemptBudget": int(effective_red_summary.get("nextAttemptBudget") or 0),
            "passStreak": int(effective_red_summary.get("passStreak") or 0),
            "pendingEscalationTargets": int(effective_red_summary.get("pendingEscalationTargets") or 0),
            "nextAction": str(effective_red_summary.get("nextAction") or ""),
        },
        "watchdogSelfImprovement": watchdog_self_improvement,
        "nextAction": (
            deficits[0]["nextAction"]
            if deficits
            else str(route_trust.get("nextAction") or effective_red_summary.get("nextAction") or fallback_digest.get("nextAction") or "")
        ),
        "liveProjectProgress": live_progress,
        "activeGapMissions": active_gap_missions,
    }
    _write_compact_system_audit_digest(root, evidence_path, digest)
    return digest


def _compact_system_audit_cache_path(root: Path) -> Path:
    return root / ".agent_control" / "system_audit_digest_latest.json"


def _system_audit_source_stat(evidence_path: Path) -> dict:
    try:
        stat = evidence_path.stat()
    except OSError:
        return {}
    return {
        "path": str(evidence_path),
        "mtimeNs": int(stat.st_mtime_ns),
        "sizeBytes": int(stat.st_size),
    }


def _load_compact_system_audit_digest(root: Path, evidence_path: Path, fallback_digest: dict) -> dict:
    source_stat = _system_audit_source_stat(evidence_path)
    if not source_stat:
        return {}
    payload = _load_json_file(_compact_system_audit_cache_path(root))
    if not isinstance(payload, dict):
        return {}
    if payload.get("schema") != "fluxio.compact_system_audit_digest_cache.v1":
        return {}
    cache_generated_at = _parse_iso_datetime(str(payload.get("generatedAt") or ""))
    if cache_generated_at:
        local_evidence_files = (
            root / ".agent_control" / "mission_artifact_repair_plan_latest.json",
            root / ".agent_control" / "mission_evidence_manifest_latest.json",
            root / ".agent_control" / "live_mission_detail_status_latest.json",
            root / ".agent_control" / "mission_watchdog_supervisor.json",
            root / ".agent_control" / "live_summary_performance_latest.json",
            root / ".agent_control" / "live_mission_detail_performance_latest.json",
            root / ".agent_control" / "nas_storage_pressure_latest.json",
            root / ".agent_control" / "nas_storage_cleanup_plan_latest.json",
            root / ".agent_control" / "authenticated_live_agent_latest.json",
        )
        for evidence_file in local_evidence_files:
            try:
                evidence_mtime = datetime.fromtimestamp(evidence_file.stat().st_mtime, timezone.utc)
            except OSError:
                continue
            if evidence_mtime > cache_generated_at:
                return {}
    if payload.get("sourceEvidence") != source_stat:
        return {}
    digest = payload.get("digest") if isinstance(payload.get("digest"), dict) else {}
    if not digest:
        return {}
    latest_agent_proof = root / ".agent_control" / "authenticated_live_agent_latest.json"
    if latest_agent_proof.exists():
        agent_proof_bundle = digest.get("agentProofBundle") if isinstance(digest.get("agentProofBundle"), dict) else {}
        if agent_proof_bundle.get("schema") != "fluxio.agent_proof_bundle_digest.v1":
            return {}
    compact_breakdown = digest.get("systemLossBreakdown") if isinstance(digest.get("systemLossBreakdown"), dict) else {}
    if "averageScoreOutOf20" not in compact_breakdown or "averageLossOutOf20" not in compact_breakdown:
        return {}
    storage_triage = digest.get("storageTriageSummary") if isinstance(digest.get("storageTriageSummary"), dict) else {}
    if storage_triage.get("schema") != "fluxio.storage_triage_summary.v1":
        return {}
    deployment_durability = (
        digest.get("deploymentDurabilitySummary")
        if isinstance(digest.get("deploymentDurabilitySummary"), dict)
        else {}
    )
    if deployment_durability.get("schema") != "fluxio.deployment_durability_summary.v1":
        return {}
    if (
        storage_triage.get("status") == "blocked"
        and int(storage_triage.get("usedPercent") or 0) == 0
        and int(storage_triage.get("availableBytes") or 0) == 0
        and not storage_triage.get("largestAccountedPath")
    ):
        return {}
    t3_reference = digest.get("t3Reference") if isinstance(digest.get("t3Reference"), dict) else {}
    if "per_page=50" not in str(t3_reference.get("source") or ""):
        return {}
    if not isinstance(t3_reference.get("verifiedClaims"), list):
        return {}
    advancement = digest.get("missionAdvancementSummary") if isinstance(digest.get("missionAdvancementSummary"), dict) else {}
    if advancement.get("status") == "missing" and _load_json_file(root / ".agent_control" / "mission_artifact_repair_plan_latest.json"):
        return {}
    operator_path = digest.get("operatorNextPath") if isinstance(digest.get("operatorNextPath"), dict) else {}
    if operator_path.get("schema") != "fluxio.operator_next_path.v1":
        return {}
    speed_supervisor = digest.get("speedSupervisorSummary") if isinstance(digest.get("speedSupervisorSummary"), dict) else {}
    if speed_supervisor.get("schema") != "fluxio.speed_supervisor_summary.v1":
        return {}
    goal_completion = digest.get("goalCompletionAudit") if isinstance(digest.get("goalCompletionAudit"), dict) else {}
    if goal_completion.get("schema") != "fluxio.goal_completion_audit.v1":
        return {}
    local_manifest = _load_json_file(root / ".agent_control" / "mission_evidence_manifest_latest.json")
    if isinstance(local_manifest, dict) and int(local_manifest.get("screenshotCount") or 0) > 0:
        advancement_rows = advancement.get("rows", []) if isinstance(advancement.get("rows"), list) else []
        if not any(
            isinstance(row, dict)
            and (
                str(row.get("evidenceScreenshotPath") or "").strip()
                or str(row.get("proofStateLabel") or "").strip()
            )
            for row in advancement_rows
        ):
            return {}
    live_progress = dict(digest.get("liveProjectProgress") or {})
    current_progress = fallback_digest.get("liveProjectProgress")
    if isinstance(current_progress, dict):
        live_progress.update(current_progress)
    return {
        **fallback_digest,
        **digest,
        "liveProjectProgress": live_progress,
        "activeGapMissions": (
            fallback_digest.get("activeGapMissions")
            if isinstance(fallback_digest.get("activeGapMissions"), list)
            else digest.get("activeGapMissions", [])
        ),
        "compactCache": {
            "schema": "fluxio.compact_system_audit_digest_cache_hit.v1",
            "sourceEvidence": source_stat,
            "path": str(_compact_system_audit_cache_path(root)),
        },
    }


def _write_compact_system_audit_digest(root: Path, evidence_path: Path, digest: dict) -> None:
    source_stat = _system_audit_source_stat(evidence_path)
    if not source_stat:
        return
    path = _compact_system_audit_cache_path(root)
    tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(path.parent).free < 2_000_000:
            return
        tmp_path.write_text(
            json.dumps(
                {
                    "schema": "fluxio.compact_system_audit_digest_cache.v1",
                    "generatedAt": utc_now_iso(),
                    "sourceEvidence": source_stat,
                    "digest": ControlRoomStore._summary_system_audit_digest_payload(digest),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except OSError:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        return


def _watchdog_self_improvement_history_digest(root: Path) -> dict:
    evidence_dir = root / ".agent_control" / "self_improvement_evidence"
    history_path = evidence_dir / "watchdog_history.jsonl"
    latest_path = evidence_dir / "watchdog_latest.json"
    latest = _load_json_file(latest_path)
    if not isinstance(latest, dict):
        latest = {}

    rows: deque[dict] = deque(maxlen=6)
    total_rows = 0
    completed_rows = 0
    failed_rows = 0
    if history_path.exists():
        try:
            with history_path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        payload = json.loads(stripped)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    total_rows += 1
                    status = str(payload.get("status") or "").lower()
                    if status == "completed":
                        completed_rows += 1
                    elif status in {"failed", "error"}:
                        failed_rows += 1
                    rows.append(payload)
        except OSError:
            rows.clear()
            total_rows = 0
            completed_rows = 0
            failed_rows = 0

    last_row = rows[-1] if rows else {}
    latest_status = str(latest.get("status") or last_row.get("status") or "missing")
    latest_generated_at = str(
        latest.get("generatedAt")
        or latest.get("lastAttemptAt")
        or last_row.get("generatedAt")
        or last_row.get("lastAttemptAt")
        or ""
    )
    next_attempt_budget = int(latest.get("nextAttemptBudget") or last_row.get("nextAttemptBudget") or 0)
    latest_history_index = int(
        latest.get("historyIndex")
        or last_row.get("historyIndex")
        or total_rows
        or 0
    )
    if total_rows and completed_rows == total_rows:
        next_action = "Keep the external watchdog active until several completed self-improvement receipts form a trend."
    elif total_rows:
        next_action = "Inspect failed or skipped watchdog self-improvement receipts before trusting the cadence trend."
    else:
        next_action = "Run mission-watchdog with --advance-self-improvement so the supervisor creates append-only cadence evidence."

    return {
        "schema": "fluxio.watchdog_self_improvement_history_digest.v1",
        "historyPath": str(history_path),
        "latestPath": str(latest_path),
        "historyExists": history_path.exists(),
        "historyRows": total_rows,
        "completedReceipts": completed_rows,
        "failedReceipts": failed_rows,
        "latestStatus": latest_status,
        "latestGeneratedAt": latest_generated_at,
        "latestHistoryIndex": latest_history_index,
        "latestCompletedSteps": int(latest.get("completedSteps") or last_row.get("completedSteps") or 0),
        "nextAttemptBudget": next_attempt_budget,
        "nextPlanStatus": str(latest.get("nextPlanStatus") or last_row.get("nextPlanStatus") or ""),
        "trendReady": total_rows >= 3 and completed_rows >= 3 and failed_rows == 0,
        "recentReceipts": [
            {
                "historyIndex": int(item.get("historyIndex") or index + 1),
                "status": str(item.get("status") or "unknown"),
                "generatedAt": str(item.get("generatedAt") or item.get("lastAttemptAt") or ""),
                "completedSteps": int(item.get("completedSteps") or 0),
                "nextAttemptBudget": int(item.get("nextAttemptBudget") or 0),
            }
            for index, item in enumerate(rows)
        ],
        "nextAction": next_action,
    }


def _speed_supervisor_summary(
    *,
    root: Path,
    summary_performance: dict,
    detail_performance: dict,
    watchdog_self_improvement: dict,
    red_summary: dict,
    mission_advancement_summary: dict,
) -> dict:
    summary_performance = summary_performance if isinstance(summary_performance, dict) else {}
    detail_performance = detail_performance if isinstance(detail_performance, dict) else {}
    watchdog_self_improvement = watchdog_self_improvement if isinstance(watchdog_self_improvement, dict) else {}
    red_summary = red_summary if isinstance(red_summary, dict) else {}
    mission_advancement_summary = mission_advancement_summary if isinstance(mission_advancement_summary, dict) else {}
    supervisor = load_watchdog_supervisor_state(root)
    if not isinstance(supervisor, dict):
        supervisor = {}

    now = datetime.now(timezone.utc)
    next_run = _parse_iso_datetime(str(supervisor.get("nextRunAt") or ""))
    last_run = _parse_iso_datetime(str(supervisor.get("lastRunAt") or ""))
    stale_minutes = max(1, int(supervisor.get("staleMinutes") or 60))
    supervisor_claims_active = bool(supervisor.get("supervisorActive"))
    supervisor_stale = False
    if next_run and now > next_run:
        supervisor_stale = True
    elif last_run and (now - last_run).total_seconds() > stale_minutes * 60:
        supervisor_stale = True
    elif not supervisor_claims_active:
        supervisor_stale = True

    summary_ok = bool(summary_performance.get("ok"))
    detail_ok = bool(detail_performance.get("ok"))
    summary_warning_count = int(summary_performance.get("warningCount") or 0)
    detail_warning_count = int(detail_performance.get("warningCount") or 0)
    summary_max_wall = float(summary_performance.get("maxWallMs") or 0)
    detail_max_wall = float(detail_performance.get("maxWallMs") or 0)
    summary_budget = float(summary_performance.get("wallBudgetMs") or 0)
    detail_budget = float(detail_performance.get("wallBudgetMs") or 0)
    repair_count = int(mission_advancement_summary.get("repairMissionCount") or 0)
    next_attempt_budget = int(
        watchdog_self_improvement.get("nextAttemptBudget")
        or red_summary.get("nextAttemptBudget")
        or 0
    )
    pending_escalation_targets = int(red_summary.get("pendingEscalationTargets") or 0)

    rows = [
        {
            "id": "summary-speed",
            "label": "Control summary",
            "status": "pass" if summary_ok and summary_warning_count == 0 else "blocked",
            "metric": f"{summary_max_wall:.2f}ms / {summary_budget:.0f}ms",
            "detail": str(summary_performance.get("nextAction") or "Bootstrap summary is measured from live NAS data."),
        },
        {
            "id": "detail-speed",
            "label": "Mission detail",
            "status": "pass" if detail_ok and detail_warning_count == 0 else "blocked",
            "metric": f"{detail_max_wall:.2f}ms / {detail_budget:.0f}ms",
            "detail": str(detail_performance.get("nextAction") or "Mission detail performance is measured from live NAS data."),
        },
        {
            "id": "watchdog-loop",
            "label": "External watchdog",
            "status": "blocked" if supervisor_stale else "pass",
            "metric": f"{int(supervisor.get('runsCompleted') or 0)} run(s)",
            "detail": (
                "Supervisor state is stale; restart the external watchdog loop before trusting hands-free operation."
                if supervisor_stale
                else str(supervisor.get("nextAction") or "External watchdog loop is fresh.")
            ),
        },
        {
            "id": "self-improvement",
            "label": "Self-improvement cadence",
            "status": "pass" if bool(watchdog_self_improvement.get("trendReady")) else "watch",
            "metric": f"{int(watchdog_self_improvement.get('completedReceipts') or 0)} receipts",
            "detail": str(watchdog_self_improvement.get("nextAction") or "No watchdog self-improvement trend is available yet."),
        },
        {
            "id": "proof-repair",
            "label": "Mission proof repair",
            "status": "blocked" if repair_count else "pass",
            "metric": f"{repair_count} repair mission(s)",
            "detail": str(mission_advancement_summary.get("nextAction") or "Mission proof state is grounded in live runtime output."),
        },
    ]

    blocked = [row for row in rows if row.get("status") == "blocked"]
    watch = [row for row in rows if row.get("status") == "watch"]
    status = "blocked" if blocked else "watch" if watch else "pass"
    if blocked:
        next_action = str(blocked[0].get("detail") or "Fix the blocked speed/supervisor gate.")
    elif watch:
        next_action = str(watch[0].get("detail") or "Keep watching the speed/supervisor evidence.")
    else:
        next_action = "Speed and supervisor evidence is live and within the current budgets."

    return {
        "schema": "fluxio.speed_supervisor_summary.v1",
        "status": status,
        "summaryOk": summary_ok,
        "detailOk": detail_ok,
        "summaryMaxWallMs": summary_max_wall,
        "detailMaxWallMs": detail_max_wall,
        "summaryWallBudgetMs": summary_budget,
        "detailWallBudgetMs": detail_budget,
        "summaryWarningCount": summary_warning_count,
        "detailWarningCount": detail_warning_count,
        "supervisorActive": supervisor_claims_active,
        "supervisorStale": supervisor_stale,
        "supervisorLastRunAt": str(supervisor.get("lastRunAt") or ""),
        "supervisorNextRunAt": str(supervisor.get("nextRunAt") or ""),
        "watchdogTrendReady": bool(watchdog_self_improvement.get("trendReady")),
        "watchdogCompletedReceipts": int(watchdog_self_improvement.get("completedReceipts") or 0),
        "nextAttemptBudget": next_attempt_budget,
        "pendingEscalationTargets": pending_escalation_targets,
        "rows": rows,
        "nextAction": next_action,
    }


def _system_improvement_queue(
    *,
    bad_first: list,
    deficits: list,
    red_summary: dict,
    route_trust: dict,
    live_progress: dict,
) -> list[dict]:
    queue: list[dict] = []
    seen: set[str] = set()

    def add_item(
        item_id: str,
        *,
        title: str,
        lane: str,
        priority: int,
        status: str,
        detail: str,
        next_action: str,
    ) -> None:
        normalized_id = re.sub(r"[^a-z0-9_:-]+", "-", item_id.lower()).strip("-") or f"item-{len(queue) + 1}"
        if normalized_id in seen:
            return
        seen.add(normalized_id)
        queue.append(
            {
                "id": normalized_id,
                "title": title,
                "lane": lane,
                "priority": max(0, min(100, int(priority))),
                "status": status,
                "detail": detail,
                "nextAction": next_action,
            }
        )

    for index, item in enumerate(bad_first):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "Current system gap").strip()
        detail = str(item.get("detail") or "").strip()
        lane = _system_improvement_lane(title, detail)
        add_item(
            f"bad-first-{index}-{title}",
            title=title,
            lane=lane,
            priority=max(95 - index * 5, 70),
            status="open",
            detail=detail,
            next_action=_system_improvement_next_action(title, detail),
        )

    for item in deficits:
        if not isinstance(item, dict):
            continue
        title = str(item.get("category") or "T3 category deficit").strip()
        detail = str(item.get("blockingGap") or "").strip()
        add_item(
            f"t3-deficit-{title}",
            title=title,
            lane="T3 parity",
            priority=96,
            status="must_beat",
            detail=detail,
            next_action=str(item.get("nextAction") or "Close this category before claiming full parity."),
        )

    red_next = str(red_summary.get("nextAction") or "").strip()
    if red_next:
        add_item(
            "red-team-escalation-next",
            title="Red-team escalation",
            lane="Self-improvement",
            priority=82,
            status="scheduled",
            detail=(
                f"{int(red_summary.get('runCount') or 0)} history rows, "
                f"{int(red_summary.get('latestResistanceScore') or 0)} latest resistance, "
                f"{int(red_summary.get('nextAttemptBudget') or 0)} next attempts."
            ),
            next_action=red_next,
        )

    route_next = str(route_trust.get("nextAction") or route_trust.get("nextRepairStep") or "").strip()
    if route_next:
        add_item(
            "route-trust-maintenance",
            title="Route trust maintenance",
            lane="Harness routing",
            priority=74 if str(route_trust.get("status") or "") == "operator_proven" else 90,
            status=str(route_trust.get("status") or "unknown"),
            detail=(
                f"{int(route_trust.get('provenTaskCount') or 0)}/"
                f"{int(route_trust.get('taskCount') or 0)} task categories proven, "
                f"{int(route_trust.get('missingOperatorValueSamples') or 0)} value samples missing."
            ),
            next_action=route_next,
        )

    if live_progress:
        add_item(
            "live-project-progress-watch",
            title="Live project advancement",
            lane="Builder operations",
            priority=70,
            status="watching",
            detail=(
                f"{int(live_progress.get('missionCount') or 0)} missions, "
                f"{int(live_progress.get('activeMissionCount') or 0)} active, "
                f"{int(live_progress.get('completedMissionCount') or 0)} completed."
            ),
            next_action="Keep project progress visible in Builder and verify active mission threads stay live.",
        )

    queue.sort(key=lambda item: (-int(item.get("priority") or 0), str(item.get("title") or "")))
    return queue[:8]


def _system_improvement_lane(title: str, detail: str) -> str:
    text = f"{title} {detail}".lower()
    if any(token in text for token in ("launch", "beginner", "installer", "registry", "signed")):
        return "Launch and onboarding"
    if any(token in text for token in ("speed", "history", "performance", "ci artifact")):
        return "Speed and release proof"
    if any(token in text for token in ("builder", "multi-project", "project")):
        return "Builder operations"
    if any(token in text for token in ("harness", "sub-agent", "route", "model")):
        return "Harness routing"
    if any(token in text for token in ("phone", "tablet", "notification", "telegram")):
        return "Notifications"
    return "System quality"


def _system_improvement_next_action(title: str, detail: str) -> str:
    text = f"{title} {detail}".lower()
    if any(token in text for token in ("registry", "signed", "installer", "publication")):
        return "Publish the package entrypoint externally or produce a signed installer proof.";
    if "notification" in text or "telegram" in text:
        return "Configure and verify an out-of-band mobile notification destination.";
    if "speed" in text or "history" in text:
        return "Attach long-history and build proof artifacts beside the release candidate.";
    if "builder" in text or "multi-project" in text:
        return "Keep live project history and dependency-aware queue state visible in Builder.";
    if "harness" in text or "sub-agent" in text or "route" in text:
        return "Run another value-scored Hermes route sample and verify planner/executor/verifier lanes.";
    return "Convert this audit gap into a verified mission or release gate.";


_VERIFIER_PROOF_ALLOWED_SUFFIXES = {
    ".html",
    ".jpeg",
    ".jpg",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".png",
    ".txt",
    ".webp",
}


def _live_storage_mount_label(probe_path: Path) -> str:
    normalized = str(probe_path).replace("\\", "/")
    config = platform_config()
    nas_volume = str(config.nas_volume_root).replace("\\", "/").rstrip("/")
    if normalized == nas_volume or normalized.startswith(f"{nas_volume}/"):
        return nas_volume
    if normalized.startswith("/volume1/"):
        parts = normalized.split("/")
        return "/".join(parts[:3]) if len(parts) >= 3 else "/volume1"
    anchor = probe_path.anchor.rstrip("\\/") if probe_path.anchor else ""
    return anchor or str(probe_path)


def _resolve_live_storage_probe_path(root: Path, raw_path: object | None = None) -> Path:
    root = Path(root).expanduser().resolve()
    config = platform_config(root)
    raw = str(raw_path or "").strip()
    candidates: list[Path] = []
    if raw:
        requested = Path(raw).expanduser()
        candidates.append(requested if requested.is_absolute() else root / requested)
        candidates.extend(config.path_candidates(raw))
    candidates.append(root)

    for candidate in candidates:
        cursor = candidate
        if cursor.exists() and cursor.is_file():
            cursor = cursor.parent
        while not cursor.exists() and cursor.parent != cursor:
            cursor = cursor.parent
        if cursor.exists() and cursor.is_dir():
            return cursor.resolve()
    return root


def _storage_pressure_status(*, available: int, used_percent: int) -> str:
    if available <= 0:
        return "full"
    if used_percent >= 99:
        return "critical"
    if used_percent >= 95:
        return "warning"
    return "ok"


def build_live_nas_storage_pressure_report(
    root: Path,
    raw_path: object | None = None,
    *,
    write_latest: bool = False,
) -> dict:
    """Return a live, measured storage-pressure report that mission preflight can trust.

    Older verifier handoffs sometimes left a stale critical/full NAS JSON file behind.
    This helper always prefers a real ``shutil.disk_usage`` sample from the requested
    workspace (or its nearest existing parent) and can atomically refresh the canonical
    ``.agent_control/nas_storage_pressure_latest.json`` evidence file.
    """

    root = Path(root).expanduser().resolve()
    probe_path = _resolve_live_storage_probe_path(root, raw_path)
    checked_at = utc_now_iso()
    try:
        usage = shutil.disk_usage(probe_path)
    except OSError as exc:
        payload = {
            "schema": "fluxio.nas_storage_pressure.v1",
            "source": "live_disk_usage",
            "checkedAt": checked_at,
            "maxAgeSeconds": 300,
            "mount": _live_storage_mount_label(probe_path),
            "path": str(probe_path),
            "status": "unknown",
            "totalBytes": 0,
            "usedBytes": 0,
            "availableBytes": 0,
            "usedPercent": 0,
            "probeTimedOut": False,
            "probeConnectFailed": True,
            "measuredUsageAvailable": False,
            "error": str(exc),
            "nextAction": "Retry the live storage probe from the target machine before blocking or clearing mission writes.",
        }
    else:
        total = int(usage.total or 0)
        used = int(usage.used or 0)
        available = int(usage.free or 0)
        used_percent = int(round((used / total) * 100)) if total else 0
        status = _storage_pressure_status(available=available, used_percent=used_percent)
        payload = {
            "schema": "fluxio.nas_storage_pressure.v1",
            "source": "live_disk_usage",
            "checkedAt": checked_at,
            "maxAgeSeconds": 300,
            "mount": _live_storage_mount_label(probe_path),
            "path": str(probe_path),
            "status": status,
            "totalBytes": total,
            "usedBytes": used,
            "availableBytes": available,
            "usedPercent": used_percent,
            "probeTimedOut": False,
            "probeConnectFailed": False,
            "measuredUsageAvailable": True,
            "nextAction": (
                "Free real NAS volume or snapshot space before trusting unattended mission writes."
                if status in {"full", "critical"}
                else "Keep live storage pressure verification in the release gate."
            ),
        }

    if write_latest:
        control_dir = root / ".agent_control"
        control_dir.mkdir(parents=True, exist_ok=True)
        target = control_dir / "nas_storage_pressure_latest.json"
        payload["sourcePath"] = str(target.resolve())
        tmp = target.with_name(f"{target.name}.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(target)
    return payload


def _live_storage_pressure_probe(root: Path) -> dict:
    return build_live_nas_storage_pressure_report(root, write_latest=False)


def _safe_verifier_proof_token(value: object, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip(".-_")
    return cleaned[:96] or fallback


def _resolve_verifier_proof_source(root: Path, raw_path: object) -> Path:
    raw = str(raw_path or "").strip()
    if not raw:
        raise RuntimeError("Verifier proof artifact path is required")
    source = Path(raw).expanduser()
    if not source.is_absolute():
        source = root / source
    source = source.resolve()
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"Verifier proof artifact is outside the workspace: {source}") from exc
    if not source.is_file():
        raise RuntimeError(f"Verifier proof artifact does not exist: {source}")
    if source.suffix.lower() not in _VERIFIER_PROOF_ALLOWED_SUFFIXES:
        raise RuntimeError(f"Unsupported verifier proof artifact type: {source.suffix or source.name}")
    return source


@_control_checked('attachment')

def attach_verifier_proof_bundle(root: Path, mission_id: object, flow_id: object | None=None, artifacts: object | None=None, *, report_path: object | None=None, checks: object | None=None) -> dict:

    """Copy verifier screenshots/reports beside mission artifacts and return a manifest."""

    root = Path(root).expanduser().resolve()

    mission_token = _safe_verifier_proof_token(mission_id, 'ui_bridge_verifier')

    flow_token = _safe_verifier_proof_token(flow_id, datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))

    dest_dir = root / '.agent_control' / 'mission_artifacts' / mission_token / 'ui_verifier_proof' / flow_token

    dest_dir.mkdir(parents=True, exist_ok=True)

    artifact_rows: list[dict] = []

    if isinstance(artifacts, list):

        artifact_rows.extend((item for item in artifacts if isinstance(item, dict)))

    if report_path:

        artifact_rows.append({'kind': 'report', 'label': 'Verifier report', 'path': str(report_path)})

    attached: list[dict] = []

    seen_sources: set[str] = set()

    for index, item in enumerate(artifact_rows, start=1):

        source = _resolve_verifier_proof_source(root, item.get('path'))

        source_key = str(source)

        if source_key in seen_sources:

            continue

        seen_sources.add(source_key)

        safe_name = _safe_verifier_proof_token(source.name, f'artifact-{index}{source.suffix.lower()}')

        target = dest_dir / f'{index:02d}-{safe_name}'

        shutil.copy2(source, target)

        attached.append({'kind': str(item.get('kind') or 'artifact'), 'label': str(item.get('label') or source.name), 'path': str(target.resolve()), 'relativePath': str(target.resolve().relative_to(root)), 'originalPath': str(source), 'bytes': target.stat().st_size})

    manifest_path = dest_dir / 'manifest.json'

    manifest = {'schema': 'fluxio.ui_verifier_proof_attachment.v1', 'missionId': str(mission_id or mission_token), 'flowId': flow_token, 'attachedAt': utc_now_iso(), 'artifactCount': len(attached), 'artifacts': attached, 'checks': checks if isinstance(checks, list) else [], 'manifestPath': str(manifest_path.resolve()), 'relativeManifestPath': str(manifest_path.resolve().relative_to(root)), 'directory': str(dest_dir.resolve()), 'relativeDirectory': str(dest_dir.resolve().relative_to(root))}

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')

    return manifest


def _bootstrap_live_mission_output_quality(missions: list[Mission]) -> dict:
    return _mission_control_operator_audit._bootstrap_live_mission_output_quality(
        missions,
        TERMINAL_MISSION_STATUSES=TERMINAL_MISSION_STATUSES,
    )




@_control_checked('storage-triage')

def _storage_triage_summary(*, nas_storage_pressure: dict, nas_storage_cleanup_plan: dict) -> dict:

    return _mission_control_operator_audit._storage_triage_summary(nas_storage_pressure=nas_storage_pressure, nas_storage_cleanup_plan=nas_storage_cleanup_plan, platform_config=platform_config)






@_control_checked('goal-audit')

def _goal_completion_audit_summary(*, system_loss_breakdown: dict, speed_supervisor_summary: dict, design_debt_summary: dict, mission_advancement_summary: dict, storage_triage_summary: dict, deployment_durability_summary: dict, public_launch_readiness: dict, route_trust: dict, red_summary: dict, live_progress: dict, t3_reference: dict, must_beat_status: dict) -> dict:

    return _mission_control_operator_audit._goal_completion_audit_summary(system_loss_breakdown=system_loss_breakdown, speed_supervisor_summary=speed_supervisor_summary, design_debt_summary=design_debt_summary, mission_advancement_summary=mission_advancement_summary, storage_triage_summary=storage_triage_summary, deployment_durability_summary=deployment_durability_summary, public_launch_readiness=public_launch_readiness, route_trust=route_trust, red_summary=red_summary, live_progress=live_progress, t3_reference=t3_reference, must_beat_status=must_beat_status, _red_team_current_cadence_is_healthy=_red_team_current_cadence_is_healthy)


def _local_live_mission_output_quality(root: Path) -> dict:
    return _mission_control_operator_audit._local_live_mission_output_quality(
        root,
        _load_json_file=_load_json_file,
    )


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
) -> dict:
    """Compact operator-facing UI/design debt so Builder does not bury it in long audit rows."""
    return _mission_control_operator_audit._design_debt_summary(
        categories=categories,
        deficits=deficits,
        bad_first=bad_first,
        system_loss_breakdown=system_loss_breakdown,
        live_mission_output_quality=live_mission_output_quality,
        mission_artifact_repair_plan=mission_artifact_repair_plan,
        nas_storage_pressure=nas_storage_pressure,
        agent_proof_bundle=agent_proof_bundle,
        _system_improvement_next_action=_system_improvement_next_action,
    )








def _t3_code_reference_snapshot(root: Path) -> dict:
    return _mission_control_operator_audit._t3_code_reference_snapshot(
        root,
        _load_json_file=_load_json_file,
    )




@_control_checked('loss-audit')

def _system_loss_breakdown(*, categories: list[dict], deficits: list[dict], score_cap_reason: str, route_trust: dict, red_summary: dict, release: dict, live_progress: dict, nas_storage_pressure: dict | None=None, live_mission_output_quality: dict | None=None) -> dict:

    return _mission_control_operator_audit._system_loss_breakdown(categories=categories, deficits=deficits, score_cap_reason=score_cap_reason, route_trust=route_trust, red_summary=red_summary, release=release, live_progress=live_progress, nas_storage_pressure=nas_storage_pressure, live_mission_output_quality=live_mission_output_quality, _red_team_current_cadence_is_healthy=_red_team_current_cadence_is_healthy, _severity_label=_severity_label, platform_config=platform_config)


def _artifact_api_url(path: Path) -> str:
    return f"/api/artifact?{urlencode({'id': _safe_artifact_id(path)})}"


SAFE_ARTIFACT_SUFFIXES = {
    ".apng",
    ".avif",
    ".csv",
    ".docx",
    ".gif",
    ".jpeg",
    ".jpg",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".pdf",
    ".png",
    ".pptx",
    ".svg",
    ".txt",
    ".webp",
    ".xlsx",
}


def _artifact_api_url_if_safe(path: Path) -> str:
    return _artifact_api_url(path) if path.exists() and path.suffix.lower() in SAFE_ARTIFACT_SUFFIXES else ""


def _platform_path_for_windows_drive(raw_path: object, *, posix: bool | None=None) -> Path:

    result = platform_config().windows_drive_to_posix_mount(raw_path, posix=posix)

    from .proofs_c_missions import check_platform_path

    check_platform_path(raw_path, posix, result)

    return result


@_control_checked('evidence')

def _recover_evidence_path(root: Path, raw_path: object) -> Path:

    raw = str(raw_path or '').strip()

    candidates: list[Path] = []

    if raw:

        config = platform_config(root)

        candidate = Path(raw)

        candidates.append(candidate if candidate.is_absolute() else root / candidate)

        candidates.extend(config.path_candidates(raw))

        direct_hits: list[Path] = []

        seen_direct: set[str] = set()

        for candidate in candidates:

            try:

                resolved = candidate.resolve()

            except OSError:

                continue

            if not resolved.is_absolute() or not resolved.exists():

                continue

            key = str(resolved)

            if key in seen_direct:

                continue

            seen_direct.add(key)

            direct_hits.append(resolved)

        if direct_hits:

            return direct_hits[0]

        normalized = raw.replace('\\', '/')

        name = Path(normalized).name

        if name:

            for search_root in config.control_search_roots('.agent_control/runtime_sessions', '.agent_control/mission_async', '.agent_runs'):

                if search_root.exists():

                    candidates.extend(search_root.rglob(name))

    for candidate in candidates:

        try:

            resolved = candidate.resolve()

        except OSError:

            continue

        if resolved.exists():

            return resolved

    return candidates[0] if candidates else root


def _path_evidence(path: Path, *, source: str, label: str | None = None) -> dict:
    exists = path.exists()
    timestamp = ""
    if exists:
        try:
            timestamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        except OSError:
            timestamp = ""
    return {
        "label": label or path.name,
        "path": str(path),
        "exists": exists,
        "timestamp": timestamp,
        "source": source,
        "provenance": "filesystem",
    }


def _latest_matching_files(root: Path, patterns: list[str], *, limit: int = 8) -> list[Path]:
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(root.glob(pattern))
    existing = [item for item in matches if item.exists() and item.is_file()]
    existing.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return existing[:limit]


def _build_control_compartment_overview(
    root: Path,
    *,
    runtime_statuses: list | None = None,
    setup_health: dict | None = None,
    storage_bridge: dict | None = None,
    provider_auth_presence: dict[str, bool] | None = None,
) -> list[dict]:
    config = platform_config(root)
    runtime_statuses = runtime_statuses or []
    setup_health = setup_health or {}
    storage_bridge = storage_bridge or {}
    provider_auth_presence = provider_auth_presence or _provider_auth_presence_from_env()
    service_summary = setup_health.get("serviceManagementSummary", {}) if isinstance(setup_health, dict) else {}
    total_services = int(service_summary.get("totalItems", 0) or 0) if isinstance(service_summary, dict) else 0
    healthy_services = int(service_summary.get("healthyCount", 0) or 0) if isinstance(service_summary, dict) else 0
    codex_command = shutil.which("codex")
    runtime_bin = root / ".agent_control" / "runtime" / "bin"
    frontend_dist = root / "web" / "dist" / "index.html"
    backend_script = root / "scripts" / "run_web_backend.py"
    nas_doctor = root / "scripts" / "nas_runtime_doctor.py"
    nas_probe = root / "scripts" / "nas_ssh_probe.py"
    codex_auth_ready = bool(provider_auth_presence.get("openai-codex") or provider_auth_presence.get("openai"))
    runtime_evidence = [
        {
            "label": item.label,
            "status": "detected" if item.detected else "missing",
            "source": "runtime_adapter_scan",
            "timestamp": utc_now_iso(),
            "provenance": item.command or item.install_hint or "detect_runtime_statuses",
        }
        for item in runtime_statuses
    ]
    compartments = [
        {
            "id": "setup",
            "label": "Setup",
            "status": "ready" if total_services > 0 and healthy_services == total_services else "offline-safe",
            "ports": [],
            "paths": [str(root / ".agent_control"), str(root / "config")],
            "actions": ["python scripts/nas_runtime_doctor.py --root .", "python scripts/nas_setup.py --help"],
            "evidence": [
                {
                    "label": "setup service health",
                    "source": "onboarding.setupHealth",
                    "timestamp": utc_now_iso(),
                    "provenance": f"{healthy_services}/{total_services} services healthy",
                }
            ],
        },
        {
            "id": "runtime",
            "label": "Runtime",
            "status": "ready" if codex_auth_ready else "blocked",
            "ports": [],
            "paths": [str(runtime_bin), str(root / ".agent_control" / "runtime_sessions")],
            "actions": [
                "syntelos-codex-oauth-helper",
                "codex exec --model gpt-5.5 --sandbox read-only",
            ],
            "evidence": runtime_evidence
            + [
                {
                    "label": "OpenAI Codex OAuth/API auth",
                    "source": "provider_auth_presence",
                    "timestamp": utc_now_iso(),
                    "provenance": "openai-codex" if provider_auth_presence.get("openai-codex") else "openai api key/env",
                    "passed": codex_auth_ready,
                },
                {
                    "label": "Codex CLI",
                    "source": "PATH",
                    "timestamp": utc_now_iso(),
                    "provenance": codex_command or "codex command not found",
                    "passed": bool(codex_command),
                },
            ],
        },
        {
            "id": "backend",
            "label": "Backend",
            "status": "ready" if backend_script.exists() else "blocked",
            "ports": [
                int(
                    os.environ.get("NEYVIA_WEB_PORT")
                    or os.environ.get("FLUXIO_WEB_PORT", "47880")
                    or 47880
                )
            ],
            "paths": [str(backend_script), str(root / ".agent_control" / "web-backend.log")],
            "actions": ["python scripts/run_web_backend.py --host 127.0.0.1 --port 47880"],
            "portSafety": {
                "duplicateListenerPreflight": True,
                "allowOverrideFlag": "--allow-port-reuse",
                "purpose": "avoid starting multiple Neyvia backends on the same local port",
            },
            "evidence": [_path_evidence(backend_script, source="filesystem", label="web backend runner")],
        },
        {
            "id": "frontend",
            "label": "Frontend",
            "status": "ready" if frontend_dist.exists() else "offline-safe",
            "ports": [int(os.environ.get("TAURI_DEV_PORT", "1420") or 1420)],
            "paths": [str(root / "web" / "src"), str(root / "web" / "dist")],
            "actions": ["npm run frontend:build", "npm run frontend:dev"],
            "evidence": [_path_evidence(frontend_dist, source="filesystem", label="built /control shell")],
        },
        {
            "id": "browser",
            "label": "Browser",
            "status": "ready" if frontend_dist.exists() else "offline-safe",
            "ports": [int(os.environ.get("TAURI_DEV_PORT", "1420") or 1420)],
            "paths": ["/control", "/api/backend", "/api/artifact"],
            "actions": ["node scripts/control_route_smoke.mjs", "open http://127.0.0.1:1420/control"],
            "evidence": [
                {
                    "label": "control route contract",
                    "source": "frontend_route",
                    "timestamp": utc_now_iso(),
                    "provenance": "/control served by Vite or web backend SPA fallback",
                }
            ],
        },
        {
            "id": "nas",
            "label": "NAS",
            "status": "ready" if storage_bridge.get("available") else "offline-safe",
            "ports": [
                22,
                int(
                    os.environ.get("NEYVIA_WEB_PORT")
                    or os.environ.get("FLUXIO_WEB_PORT", "47880")
                    or 47880
                ),
            ],
            "paths": [
                str(root / ".agent_control"),
                str(config.nas_project_root),
                str(config.windows_nas_project_root),
            ],
            "actions": [
                "python scripts/nas_setup.py --help",
                "python scripts/nas_runtime_doctor.py --root .",
                "python scripts/nas_ssh_probe.py --help",
                "python scripts/nas_ssh_probe.py --host <nas> --port 22 --user <user> --diagnose --cooldown-seconds 20",
            ],
            "portSafety": {
                "guarded": True,
                "ports": [22],
                "cooldownSeconds": 20,
                "windowSeconds": 60,
                "maxAttempts": 6,
                "statePath": str(root / ".agent_control" / "port_safety.json"),
                "purpose": "avoid repeated SSH/SFTP probes overloading NAS port 22",
            },
            "evidence": [
                _path_evidence(nas_doctor, source="filesystem", label="NAS doctor"),
                _path_evidence(nas_probe, source="filesystem", label="NAS SSH probe"),
            ],
        },
    ]
    for compartment in compartments:
        compartment["updatedAt"] = utc_now_iso()
    return compartments


@_control_checked('images')

def _build_generated_image_artifacts_snapshot(root: Path) -> dict:

    artifact_roots = [root / '.agent_control' / 'image_playground_artifacts', root / '.agent_control' / 'generated_image_artifacts', root / '.agent_control' / 'design_references']

    image_suffixes = {'.apng', '.avif', '.gif', '.jpeg', '.jpg', '.png', '.webp'}

    min_visual_artifact_bytes = 512

    items: list[dict] = []

    seen_paths: set[str] = set()



    def add_image_artifact(image_path: Path, manifest_path: Path | None=None, manifest: dict | None=None) -> None:

        manifest = manifest if isinstance(manifest, dict) else {}

        try:

            if image_path.stat().st_size < min_visual_artifact_bytes:

                return

        except OSError:

            return

        try:

            key = str(image_path.resolve())

        except OSError:

            key = str(image_path)

        if key in seen_paths:

            return

        seen_paths.add(key)

        items.append({'artifactId': str(manifest.get('artifactId') or manifest.get('requestId') or image_path.stem), 'servedArtifactId': str(manifest.get('servedArtifactId') or _safe_artifact_id(image_path)), 'requestId': str(manifest.get('requestId') or ''), 'status': 'served', 'provider': str(manifest.get('provider') or 'Syntelos local artifact lane'), 'operation': str(manifest.get('operation') or 'generate'), 'createdAt': str(manifest.get('createdAt') or datetime.fromtimestamp(image_path.stat().st_mtime, timezone.utc).isoformat()), 'artifactPath': str(image_path), 'manifestPath': str(manifest_path or ''), 'previewUrl': _artifact_api_url(image_path), 'manifestUrl': _artifact_api_url(manifest_path) if manifest_path else '', 'contentType': str(manifest.get('contentType') or 'image/png'), 'safeArtifactArea': str(manifest.get('safeArtifactArea') or '.agent_control/design_references/codex_image_artifacts'), 'localPath': str(manifest.get('localPath') or image_path), 'nasPathCandidates': manifest.get('nasPathCandidates') if isinstance(manifest.get('nasPathCandidates'), list) else [], 'provenance': manifest.get('provenance') if isinstance(manifest.get('provenance'), dict) else {'servedBy': 'web-backend', 'safeEndpoint': '/api/artifact', 'arbitraryWorkspaceFilesExposed': False}, 'metadata': {'artifactSha256': manifest.get('artifactSha256') or '', 'manifestSha256': manifest.get('manifestSha256') or '', 'prompt': manifest.get('prompt') if isinstance(manifest.get('prompt'), dict) else {}, 'canvas': manifest.get('canvas') if isinstance(manifest.get('canvas'), dict) else {}}, 'source': 'generated_image_artifact_manifest' if manifest_path else 'generated_image_artifact_file'})

    for artifact_root in artifact_roots:

        if not artifact_root.exists():

            continue

        manifest_paths = sorted(artifact_root.rglob('*.manifest.json'), key=lambda item: item.stat().st_mtime, reverse=True)

        for manifest_path in manifest_paths[:80]:

            try:

                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))

            except (OSError, json.JSONDecodeError):

                manifest = {}

            if not isinstance(manifest, dict):

                manifest = {}

            image_path = Path(str(manifest.get('artifactPath') or ''))

            if not image_path.is_absolute():

                image_path = manifest_path.with_suffix('').with_suffix('.png')

            if not image_path.exists():

                manifest_prefix = manifest_path.name[:-len('.manifest.json')] if manifest_path.name.endswith('.manifest.json') else manifest_path.stem

                sibling_images = [item for item in manifest_path.parent.glob(f'{manifest_prefix}.*') if item.suffix.lower() in image_suffixes]

                image_path = sibling_images[0] if sibling_images else image_path

            if not image_path.exists() or image_path.suffix.lower() not in image_suffixes:

                continue

            add_image_artifact(image_path, manifest_path, manifest)

        direct_images = sorted([item for item in artifact_root.rglob('*') if item.is_file() and item.suffix.lower() in image_suffixes], key=lambda item: item.stat().st_mtime, reverse=True)

        for image_path in direct_images[:120]:

            add_image_artifact(image_path)

    return {'items': items[:40], 'summary': {'total': len(items[:40])}, 'emptyState': 'No generated image artifacts are available yet. Generate an image in live mode to create served artifact URLs.' if not items else '', 'source': 'agent_control_artifact_manifests'}


def _build_hermes_mission_evidence(root: Path, missions: list[Mission], activity: list[dict]) -> dict:
    items: list[dict] = []

    for mission in missions:
        mission_is_hermes = str(mission.runtime_id).lower() == "hermes"
        hermes_sessions = [
            session
            for session in mission.delegated_runtime_sessions or []
            if str(session.runtime_id).lower() == "hermes"
        ]
        if mission_is_hermes or hermes_sessions:
            mission_artifacts = []
            proof_artifacts = getattr(mission, "proof_artifacts", None)
            if proof_artifacts is None:
                proof_artifacts = getattr(mission.proof, "artifacts", None)
            for artifact in proof_artifacts or []:
                artifact_text = str(artifact)
                artifact_path = _recover_evidence_path(root, artifact_text)
                mission_artifacts.append(
                    {
                        "label": artifact_path.name or artifact_text,
                        "path": artifact_text,
                        "servedUrl": _artifact_api_url_if_safe(artifact_path),
                        "exists": artifact_path.exists(),
                    }
                )
            command_evidence = []
            for action in mission.action_history[-8:]:
                result = action.get("result", {}) if isinstance(action, dict) else {}
                proposal = action.get("proposal", {}) if isinstance(action, dict) else {}
                command_evidence.append(
                    {
                        "title": str(proposal.get("title") or action.get("action_id") or "action"),
                        "command": str(result.get("command") or result.get("executed_command") or ""),
                        "ok": bool(result.get("ok")) if "ok" in result else not bool(result.get("error")),
                        "summary": str(result.get("result_summary") or result.get("error") or result.get("stdout") or ""),
                        "timestamp": str(action.get("executed_at") or mission.updated_at),
                        "provenance": "mission.action_history",
                    }
                )
            for session in hermes_sessions:
                for raw_path, label, source in (
                    (session.session_path, "session state", "delegated_runtime_session"),
                    (session.events_path, "session events", "delegated_runtime_events"),
                    (session.log_path, "runtime log", "delegated_runtime_log"),
                ):
                    if not raw_path:
                        continue
                    evidence_path = _recover_evidence_path(root, raw_path)
                    mission_artifacts.append(
                        {
                            **_path_evidence(evidence_path, source=source, label=label),
                            "servedUrl": _artifact_api_url_if_safe(evidence_path),
                        }
                    )
            for evidence_path in _latest_matching_files(
                root,
                [
                    ".agent_control/mission_async/*.log",
                ],
                limit=8,
            ):
                mission_artifacts.append(
                    {
                        **_path_evidence(evidence_path, source="run_evidence", label=evidence_path.name),
                        "servedUrl": _artifact_api_url_if_safe(evidence_path),
                    }
                )
            failure_reasons = [
                *[str(item) for item in mission.proof.failed_checks],
                *[str(item) for item in mission.state.verification_failures],
                *[str(item.get("blocker") or "") for item in _runtime_lane_rows_for_mission(mission) if item.get("blocker")],
            ]
            items.append(
                {
                    "timestamp": mission.updated_at,
                    "status": mission.state.status,
                    "source": "mission_summary",
                    "missionId": mission.mission_id,
                    "objective": mission.objective,
                    "successChecks": list(mission.success_checks),
                    "message": mission.proof.summary or mission.title or mission.objective,
                    "artifacts": mission_artifacts,
                    "commandEvidence": command_evidence,
                    "failureReasons": [item for item in failure_reasons if item],
                    "provenance": "mission_control_store",
                }
            )
            for check in mission.proof.passed_checks:
                items.append(
                    {
                        "timestamp": mission.updated_at,
                        "status": "passed",
                        "source": "mission_proof",
                        "missionId": mission.mission_id,
                        "message": str(check),
                        "provenance": "mission.proof.passed_checks",
                    }
                )
            for check in mission.proof.failed_checks:
                items.append(
                    {
                        "timestamp": mission.updated_at,
                        "status": "failed",
                        "source": "mission_proof",
                        "missionId": mission.mission_id,
                        "message": str(check),
                        "provenance": "mission.proof.failed_checks",
                    }
                )
        for session in hermes_sessions:
            for event in session.latest_events[-12:]:
                if not isinstance(event, dict):
                    continue
                kind = str(event.get("kind") or "").lower()
                if not any(token in kind for token in ("proof", "evidence", "runtime", "approval", "session")):
                    continue
                items.append(
                    {
                        "timestamp": _event_timestamp(event) or session.updated_at,
                        "status": str(event.get("status") or session.status or "recorded"),
                        "source": "hermes_runtime_session",
                        "missionId": mission.mission_id,
                        "sessionId": session.delegated_id,
                        "kind": event.get("kind") or "runtime.event",
                        "message": str(event.get("message") or event.get("summary") or session.detail or ""),
                        "provenance": "delegated_runtime_session.latest_events",
                    }
                )

    for event in activity:
        if not isinstance(event, dict):
            continue
        kind = str(event.get("kind") or "").lower()
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        source = str(metadata.get("source") or event.get("source") or "").lower()
        if "hermes" not in kind and "hermes" not in source:
            continue
        items.append(
            {
                "timestamp": _event_timestamp(event),
                "status": str(event.get("status") or metadata.get("status") or "recorded"),
                "source": str(metadata.get("source") or "mission_event"),
                "missionId": str(event.get("mission_id") or event.get("missionId") or ""),
                "kind": event.get("kind") or "mission.event",
                "message": str(event.get("message") or ""),
                "provenance": "mission_events.jsonl",
            }
        )

    for artifact in _build_generated_image_artifacts_snapshot(root).get("items", []):
        if not isinstance(artifact, dict):
            continue
        items.append(
            {
                "timestamp": str(artifact.get("createdAt") or ""),
                "status": "served",
                "source": "generated_artifact_manifest",
                "missionId": "",
                "kind": "artifact.generated",
                "message": str(artifact.get("artifactId") or artifact.get("artifactPath") or "generated artifact"),
                "artifacts": [artifact],
                "provenance": "agent_control_artifact_manifests",
            }
        )

    deduped: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (
            str(item.get("timestamp") or ""),
            str(item.get("source") or ""),
            str(item.get("message") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    deduped.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    return {
        "items": deduped[:40],
        "summary": {
            "total": len(deduped),
            "passed": sum(1 for item in deduped if item.get("status") in {"passed", "completed", "ok"}),
            "failed": sum(1 for item in deduped if item.get("status") in {"failed", "error"}),
        },
        "emptyState": (
            "No Hermes mission evidence has been captured yet. Run a Hermes mission or delegated lane to populate proof events."
            if not deduped
            else ""
        ),
        "source": "mission_events_and_runtime_sessions",
    }


def build_nas_deploy_readiness_snapshot(
    root: Path,
    *,
    onboarding: dict | None = None,
    setup_health: dict | None = None,
    storage_bridge: dict | None = None,
) -> dict:
    return _mission_control_release.build_nas_deploy_readiness_snapshot(
        root,
        onboarding=onboarding,
        setup_health=setup_health,
        storage_bridge=storage_bridge,
        detect_onboarding_status=detect_onboarding_status,
    )


def build_release_readiness_snapshot(
    root: Path,
    *,
    onboarding: dict | None = None,
    setup_health: dict | None = None,
    harness_lab: dict | None = None,
) -> dict:
    return _mission_control_release.build_release_readiness_snapshot(
        root,
        onboarding=onboarding,
        setup_health=setup_health,
        harness_lab=harness_lab,
        RELEASE_READINESS_WEIGHTS=RELEASE_READINESS_WEIGHTS,
        _build_mission_watchdog_release_gate=_build_mission_watchdog_release_gate,
        _build_proving_cycle_readiness=_build_proving_cycle_readiness,
        _percent=_percent,
        _release_quality_score=_release_quality_score,
        _verify_desktop_script_contract=_verify_desktop_script_contract,
        _verify_frontend_source_alignment=_verify_frontend_source_alignment,
        _verify_public_web_distribution_contract=_verify_public_web_distribution_contract,
        _verify_release_artifact_ci_contract=_verify_release_artifact_ci_contract,
        _verify_self_improvement_evidence_contract=_verify_self_improvement_evidence_contract,
        build_harness_lab_snapshot=build_harness_lab_snapshot,
        detect_onboarding_status=detect_onboarding_status,
        utc_now_iso=utc_now_iso,
    )


def _release_mission_items(payload: object) -> list[tuple[str, dict]]:
    return _mission_control_release._release_mission_items(
        payload,
        _release_mission_items=_release_mission_items,
    )


def _build_mission_watchdog_release_gate(root: Path) -> dict:
    return _mission_control_release._build_mission_watchdog_release_gate(
        root,
        TERMINAL_MISSION_STATUSES=TERMINAL_MISSION_STATUSES,
        _load_json_file=_load_json_file,
        _mission_payload_runtime_budget_exhausted=_mission_payload_runtime_budget_exhausted,
        _release_mission_items=_release_mission_items,
        load_watchdog_supervisor_state=load_watchdog_supervisor_state,
    )


def _build_runtime_session_health(root: Path) -> dict:
    return _mission_control_release._build_runtime_session_health(
        root,
        _age_seconds=_age_seconds,
        _load_json_file=_load_json_file,
        _percent=_percent,
        _runtime_pid_alive=_runtime_pid_alive,
    )


def _runtime_pid_alive(pid: int) -> bool:
    return _mission_control_release._runtime_pid_alive(
        pid,
        process_is_alive=process_is_alive,
    )


def _build_runtime_session_health_summary(*, missions: list[Mission]) -> dict:
    return _mission_control_release._build_runtime_session_health_summary(
        missions=missions,
        _age_seconds=_age_seconds,
        _percent=_percent,
        _runtime_pid_alive=_runtime_pid_alive,
    )




def _route_trust_label(task_type: str) -> str:
    return _mission_control_harness._route_trust_label(
        task_type,
        ROUTE_TRUST_TASK_LABELS=ROUTE_TRUST_TASK_LABELS,
    )


def _route_trust_task_type(payload: dict) -> str:
    return _mission_control_harness._route_trust_task_type(
        payload,
        ROUTE_TRUST_SAMPLE_TEMPLATES=ROUTE_TRUST_SAMPLE_TEMPLATES,
        ROUTE_TRUST_TASK_KEYWORDS=ROUTE_TRUST_TASK_KEYWORDS,
    )






def _route_trust_repair_steps(low_value_items: list[dict], coverage: dict[str, dict]) -> list[dict]:
    return _mission_control_harness._route_trust_repair_steps(
        low_value_items,
        coverage,
        _route_trust_label=_route_trust_label,
    )


def _route_trust_row(coverage: dict[str, dict], task_type: str) -> dict:
    return _mission_control_harness._route_trust_row(
        coverage,
        task_type,
        _route_trust_label=_route_trust_label,
    )




def _route_trust_sampling_template(
    task_type: str,
    row: dict[str, object],
    *,
    repair: dict[str, object] | None = None,
) -> dict[str, object]:
    return _mission_control_harness._route_trust_sampling_template(
        task_type,
        row,
        repair=repair,
        ROUTE_TRUST_SAMPLE_TEMPLATES=ROUTE_TRUST_SAMPLE_TEMPLATES,
        _route_trust_label=_route_trust_label,
        _shell_quote=_shell_quote,
        urlencode=urlencode,
    )


def _build_route_trust_coverage_snapshot(root: Path, *, sessions: list[Path]) -> dict:
    return _mission_control_harness._build_route_trust_coverage_snapshot(
        root,
        sessions=sessions,
        HARNESS_RECENT_RUN_LIMIT=HARNESS_RECENT_RUN_LIMIT,
        ROUTE_TRUST_REQUIRED_VALUE_SAMPLES=ROUTE_TRUST_REQUIRED_VALUE_SAMPLES,
        ROUTE_TRUST_TASK_LABELS=ROUTE_TRUST_TASK_LABELS,
        _build_route_outcome_trends_for_trust=_build_route_outcome_trends_for_trust,
        _load_json_file=_load_json_file,
        _operator_value_feedback_signal=_operator_value_feedback_signal,
        _quarantined_route_count=_quarantined_route_count,
        _route_outcome_quarantines=_route_outcome_quarantines,
        _route_trust_closeout_low_value=_route_trust_closeout_low_value,
        _route_trust_repair_steps=_route_trust_repair_steps,
        _route_trust_row=_route_trust_row,
        _route_trust_sampling_template=_route_trust_sampling_template,
        _route_trust_task_type=_route_trust_task_type,
    )


def _route_trust_payload_for_mission(mission: Mission) -> dict:
    return _mission_control_harness._route_trust_payload_for_mission(
        mission,
        asdict=asdict,
        is_dataclass=is_dataclass,
    )








@_control_checked('route-trust')

def _build_route_trust_coverage_summary(root: Path, *, missions: list[Mission], include_route_outcome_trends: bool=True) -> dict:

    return _mission_control_harness._build_route_trust_coverage_summary(root, missions=missions, include_route_outcome_trends=include_route_outcome_trends, ROUTE_TRUST_REQUIRED_VALUE_SAMPLES=ROUTE_TRUST_REQUIRED_VALUE_SAMPLES, ROUTE_TRUST_TASK_LABELS=ROUTE_TRUST_TASK_LABELS, _build_route_outcome_trends_for_trust=_build_route_outcome_trends_for_trust, _load_json_file=_load_json_file, _operator_value_feedback_signal=_operator_value_feedback_signal, _quarantined_route_count=_quarantined_route_count, _route_outcome_quarantines=_route_outcome_quarantines, _route_trust_closeout_low_value=_route_trust_closeout_low_value, _route_trust_payload_for_mission=_route_trust_payload_for_mission, _route_trust_repair_steps=_route_trust_repair_steps, _route_trust_row=_route_trust_row, _route_trust_sampling_template=_route_trust_sampling_template, _route_trust_task_type=_route_trust_task_type)




def build_harness_lab_snapshot(root: Path) -> dict:
    return _mission_control_harness.build_harness_lab_snapshot(
        root,
        HARNESS_RECENT_RUN_LIMIT=HARNESS_RECENT_RUN_LIMIT,
        TERMINAL_MISSION_STATUSES=TERMINAL_MISSION_STATUSES,
        _build_harness_parity_matrix=_build_harness_parity_matrix,
        _build_route_trust_coverage_snapshot=_build_route_trust_coverage_snapshot,
        _build_runtime_session_health=_build_runtime_session_health,
        _harness_efficiency_recommendation=_harness_efficiency_recommendation,
        _load_json_file=_load_json_file,
        _percent=_percent,
    )


@_control_checked('harness-summary')

def build_summary_harness_lab_snapshot(root: Path, *, missions: list[Mission]) -> dict:

    return _mission_control_harness.build_summary_harness_lab_snapshot(root, missions=missions, HARNESS_RECENT_RUN_LIMIT=HARNESS_RECENT_RUN_LIMIT, TERMINAL_MISSION_STATUSES=TERMINAL_MISSION_STATUSES, _build_harness_parity_matrix=_build_harness_parity_matrix, _build_route_trust_coverage_summary=_build_route_trust_coverage_summary, _build_runtime_session_health_summary=_build_runtime_session_health_summary, _harness_efficiency_recommendation=_harness_efficiency_recommendation, _percent=_percent)


def _summary_mission_watchdog_report(
    *,
    root: Path,
    missions: list[Mission],
    workspaces: list[WorkspaceProfile],
) -> dict[str, Any]:
    report_path = root / ".agent_control" / "mission_watchdog.json"
    payload = _load_json_file(report_path)
    if isinstance(payload, dict) and payload.get("schema") == "fluxio.mission_watchdog.v1":
        try:
            age_seconds = max(0, int(time.time() - report_path.stat().st_mtime))
        except OSError:
            age_seconds = 0
        payload = dict(payload)
        payload.setdefault("summary", {})
        payload.setdefault("issues", [])
        payload.setdefault("nextAction", "")
        payload.setdefault("problemReport", build_watchdog_problem_report(payload))
        payload.setdefault("problemRegistry", {})
        payload["summarySource"] = {
            "schema": "fluxio.summary.watchdog_source.v1",
            "source": "mission_watchdog_report_file",
            "path": str(report_path),
            "freshness": "fresh" if age_seconds <= 300 else "stale",
            "ageSeconds": age_seconds,
            "checkedAgainstMissionCount": len(missions),
            "reportMissionCount": int(payload.get("summary", {}).get("missionCount") or 0),
            "nextAction": (
                "Use the external watchdog report; it is fresh enough for the summary path."
                if age_seconds <= 300
                else "External watchdog report is stale; restart or advance the watchdog loop instead of hiding this."
            ),
        }
        return payload
    report = build_mission_watchdog_report(
        root=root,
        missions=missions,
        workspaces=workspaces,
    )
    report["summarySource"] = {
        "schema": "fluxio.summary.watchdog_source.v1",
        "source": "inline_rebuild",
        "freshness": "fresh",
        "ageSeconds": 0,
        "checkedAgainstMissionCount": len(missions),
        "reportMissionCount": int(report.get("summary", {}).get("missionCount") or 0),
        "nextAction": "No persisted watchdog report was available, so the summary rebuilt it inline.",
    }
    return report
