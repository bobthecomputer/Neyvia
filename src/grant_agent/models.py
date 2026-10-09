from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PersonaProfile:
    name: str
    tone: str
    risk_tolerance: str
    creativity_level: str
    coding_style: str
    verbosity: str


@dataclass
class PromptStack:
    base_constitution: str
    project_profile: str
    persona: PersonaProfile
    task_brief: str
    step_policy: str


@dataclass
class VerificationResult:
    command: str
    return_code: int
    stdout: str
    stderr: str
    duration_ms: int
    status: str = "executed"
    risk_level: str = "low"


@dataclass
class TimelineEvent:
    kind: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now_iso)


@dataclass
class RunState:
    objective: str
    plan_steps: list[str]
    acceptance_checks: list[str]
    completed_steps: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    verification_results: list[VerificationResult] = field(default_factory=list)
    retrieved_skills: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class HandoffPacket:
    schema_version: str
    generated_at: str
    reason: str
    session_id: str
    parent_session_id: str | None
    objective: str
    prompt_stack: dict[str, Any]
    progress: dict[str, Any]
    changed_files: list[str]
    decisions: list[str]
    risks: list[str]
    acceptance_checks: list[str]
    verification: list[dict[str, Any]]
    next_actions: list[str]
    resume_instructions: list[str]


@dataclass
class RuntimeCapability:
    key: str
    label: str
    available: bool
    detail: str = ""


@dataclass
class RuntimeInstallStatus:
    runtime_id: str
    label: str
    detected: bool
    command: str | None = None
    version: str | None = None
    latest_version: str | None = None
    update_available: bool = False
    update_command: str | None = None
    update_source_url: str | None = None
    install_hint: str | None = None
    doctor_summary: str = ""
    issues: list[str] = field(default_factory=list)
    capabilities: list[RuntimeCapability] = field(default_factory=list)


@dataclass
class MissionRunBudget:
    mode: str
    max_runtime_seconds: int
    focus_window_hours: int = 12
    run_until_behavior: str = "pause_on_failure"
    deadline_at: str | None = None
    enforced: bool = False


@dataclass
class MissionVerificationPolicy:
    commands: list[str] = field(default_factory=list)
    pause_on_failure: bool = True


@dataclass
class MissionProof:
    summary: str = ""
    changed_files: list[str] = field(default_factory=list)
    artifacts: list[Any] = field(default_factory=list)
    passed_checks: list[str] = field(default_factory=list)
    failed_checks: list[str] = field(default_factory=list)
    pending_approvals: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)


@dataclass
class MissionStateSnapshot:
    status: str = "draft"
    latest_session_id: str | None = None
    last_runtime_event: str | None = None
    last_error: str | None = None
    current_cycle_phase: str = "plan"
    cycle_count: int = 0
    last_verification_result: str = ""
    last_replan_reason: str = ""
    queue_position: int = 0
    blocking_mission_id: str | None = None
    queue_reason: str = ""
    remaining_steps: list[str] = field(default_factory=list)
    verification_failures: list[str] = field(default_factory=list)
    active_step_id: str | None = None
    repeated_failure_count: int = 0
    planner_loop_status: str = "idle"
    stop_reason: str | None = None
    last_plan_summary: str = ""
    execution_scope: dict[str, Any] = field(default_factory=dict)
    pending_mutating_actions: int = 0
    delegated_runtime_sessions: list[dict[str, Any]] = field(default_factory=list)
    replay_action_cursor: str = ""
    tutorial_context: dict[str, Any] = field(default_factory=dict)
    continuity_state: str = "fresh_only"
    continuity_detail: str = ""
    last_verification_summary: str = ""
    last_replan_trigger: str = ""
    pending_approval_payload: dict[str, Any] = field(default_factory=dict)
    approval_history: list[dict[str, Any]] = field(default_factory=list)
    elapsed_runtime_seconds: int = 0
    remaining_runtime_seconds: int = 0
    time_budget_status: str = "pending"
    last_budget_pause_reason: str = ""
    current_runtime_lane: str = ""
    context_used_tokens: int = 0
    context_usage_ratio: float = 0.0
    context_status: str = "ok"
    handoff_count: int = 0
    last_handoff_reason: str = ""
    route_change_count: int = 0
    parallel_agents: int = 1
    observation_count: int = 3
    merge_policy: str = "best_score"
    cross_mission_awareness: str = "observe"
    runtime_autonomy: dict[str, Any] = field(default_factory=dict)
    blocker_classification: dict[str, Any] = field(default_factory=dict)
    blocker_history: list[dict[str, Any]] = field(default_factory=list)
    provider_runtime_truth: dict[str, Any] = field(default_factory=dict)
    lane_control_receipts: list[dict[str, Any]] = field(default_factory=list)
    code_execution: dict[str, Any] = field(default_factory=dict)
    operator_value_feedback: dict[str, Any] = field(default_factory=dict)
    preferred_host: str = ""
    assigned_host: str = ""
    host_lease_id: str = ""
    host_locality: str = ""
    lease_status: str = ""
    worker_heartbeat_at: str = ""


@dataclass
class ApprovalEscalation:
    channel: str
    enabled: bool
    destination: str
    triggers: list[str] = field(default_factory=list)
    pending_count: int = 0
    delivery_ready: bool = False
    preview_message: str = ""
    last_sent_at: str | None = None
    last_error: str | None = None
    delivery_receipts: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DeliveryReceipt:
    receipt_id: str
    mission_id: str
    channel: str
    destination: str
    event_kind: str
    event_message: str
    sent_at: str
    status: str
    error_message: str = ""
    delivery_url: str = ""
    retry_count: int = 0
    origin_runtime: str = ""
    origin_provider: str = ""
    origin_model: str = ""
    transport_provider: str = ""
    producer: str = ""
    mission_title: str = ""
    source_session_id: str = ""
    evidence_path: str = ""
    screenshot_path: str = ""
    idempotency_key: str = ""


MISSION_RUN_SCHEMA_VERSION = "fluxio.mission_run.v1"
MISSION_RUN_PHASES = (
    "preflight",
    "planner",
    "executor",
    "verifier",
    "repair",
    "final_report",
)
MISSION_RUN_STATUSES = (
    "draft",
    "queued",
    "running",
    "blocked",
    "repair_needed",
    "failed",
    "completed",
    "cancelled",
)
MISSION_RUN_TERMINAL_STATUSES = ("blocked", "failed", "completed", "cancelled")
MISSION_RECEIPT_COMMON_SCHEMA_VERSION = "fluxio.mission_receipt.v1"
NIGHT_READINESS_RECEIPT_SCHEMA_VERSION = "fluxio.night_readiness_receipt.v1"
SKILL_BRIEF_SCHEMA_VERSION = "fluxio.skill_brief.v1"
SUB_AGENT_RECEIPT_SCHEMA_VERSION = "fluxio.sub_agent_receipt.v1"
PLAN_RECEIPT_SCHEMA_VERSION = "fluxio.plan_receipt.v1"
EXECUTION_RECEIPT_SCHEMA_VERSION = "fluxio.execution_receipt.v1"
VERIFICATION_RECEIPT_SCHEMA_VERSION = "fluxio.verification_receipt.v1"
REPAIR_RECEIPT_SCHEMA_VERSION = "fluxio.repair_receipt.v1"
FINAL_PROOF_RECEIPT_SCHEMA_VERSION = "fluxio.final_proof_receipt.v1"
STUCK_MISSION_RECEIPT_SCHEMA_VERSION = "fluxio.stuck_mission_receipt.v1"
STUCK_MISSION_RECEIPT_DECISIONS = ("blocked", "operator_needed")
VERIFICATION_RECEIPT_DECISIONS = (
    "accepted",
    "repair_needed",
    "blocked",
    "operator_needed",
)


@dataclass
class MissionReceiptBase:
    schema: str
    receipt_id: str
    mission_id: str
    phase: str
    host: str
    runtime: str
    workspace: str
    status: str
    summary: str
    generated_at: str = field(default_factory=utc_now_iso)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    proof_paths: list[str] = field(default_factory=list)
    next_action: str = ""
    mission_run_id: str = ""
    producer: str = "fluxio"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NightReadinessReceipt:
    receipt_id: str
    mission_id: str
    host: str
    runtime: str
    workspace: str
    status: str
    summary: str
    schema: str = NIGHT_READINESS_RECEIPT_SCHEMA_VERSION
    generated_at: str = field(default_factory=utc_now_iso)
    phase: str = "preflight"
    checks: dict[str, Any] = field(default_factory=dict)
    masked_keys: dict[str, str] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    desktop_gateway_status: str = "unknown"
    notification_channel: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    proof_paths: list[str] = field(default_factory=list)
    next_action: str = ""
    mission_run_id: str = ""
    producer: str = "fluxio"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillBrief:
    brief_id: str
    mission_id: str
    task_brief: str
    selected_skills: list[dict[str, Any]]
    repo_specific_skills: list[dict[str, Any]]
    allowed_tools: list[str]
    forbidden_areas: list[str]
    relevant_examples: list[str]
    constraints: list[str]
    known_failures: list[dict[str, Any]]
    prior_successful_recipes: list[dict[str, Any]]
    skill_count: int
    generated_at: str = field(default_factory=utc_now_iso)
    schema: str = SKILL_BRIEF_SCHEMA_VERSION
    next_action: str = "Planner should choose from selected_skills and carry constraints forward."


@dataclass
class SubAgentReceipt:
    receipt_id: str
    mission_id: str
    assignment: str
    role: str
    status: str
    inputs: dict[str, Any]
    files_inspected: list[str]
    findings: list[dict[str, Any]]
    confidence: float
    proof_paths: list[str]
    next_recommendation: str
    generated_at: str = field(default_factory=utc_now_iso)
    schema: str = SUB_AGENT_RECEIPT_SCHEMA_VERSION
    phase: str = "sub_agent"
    advisory_only: bool = True
    mission_run_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanReceipt:
    receipt_id: str
    mission_id: str
    host: str
    runtime: str
    workspace: str
    status: str
    summary: str
    goal_restatement: str
    schema: str = PLAN_RECEIPT_SCHEMA_VERSION
    generated_at: str = field(default_factory=utc_now_iso)
    phase: str = "planner"
    assumptions: list[str] = field(default_factory=list)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    file_scope: list[str] = field(default_factory=list)
    selected_skills: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)
    expected_changed_files: list[str] = field(default_factory=list)
    expected_artifacts: list[str] = field(default_factory=list)
    verification_ladder: list[str] = field(default_factory=list)
    risk_level: str = "medium"
    maximum_repair_loops: int = 1
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    proof_paths: list[str] = field(default_factory=list)
    next_action: str = ""
    mission_run_id: str = ""
    producer: str = "fluxio"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionReceipt:
    receipt_id: str
    mission_id: str
    host: str
    runtime: str
    workspace: str
    status: str
    summary: str
    schema: str = EXECUTION_RECEIPT_SCHEMA_VERSION
    generated_at: str = field(default_factory=utc_now_iso)
    phase: str = "executor"
    tasks_attempted: list[str] = field(default_factory=list)
    tasks_completed: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    commands_run: list[dict[str, Any]] = field(default_factory=list)
    stdout_summaries: list[str] = field(default_factory=list)
    stderr_summaries: list[str] = field(default_factory=list)
    errors_encountered: list[str] = field(default_factory=list)
    skipped_work: list[str] = field(default_factory=list)
    self_critique: str = ""
    next_suggested_verifier_checks: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    proof_paths: list[str] = field(default_factory=list)
    next_action: str = ""
    mission_run_id: str = ""
    producer: str = "fluxio"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationReceipt:
    receipt_id: str
    mission_id: str
    host: str
    runtime: str
    workspace: str
    status: str
    summary: str
    decision: str
    schema: str = VERIFICATION_RECEIPT_SCHEMA_VERSION
    generated_at: str = field(default_factory=utc_now_iso)
    phase: str = "verifier"
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    not_tested: list[str] = field(default_factory=list)
    evidence_inspected: list[str] = field(default_factory=list)
    satisfies_original_goal: bool = False
    proof_gaps: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    proof_paths: list[str] = field(default_factory=list)
    next_action: str = ""
    mission_run_id: str = ""
    producer: str = "fluxio"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RepairReceipt:
    receipt_id: str
    mission_id: str
    host: str
    runtime: str
    workspace: str
    status: str
    summary: str
    schema: str = REPAIR_RECEIPT_SCHEMA_VERSION
    generated_at: str = field(default_factory=utc_now_iso)
    phase: str = "repair"
    verifier_failure_summary: str = ""
    repair_loop_index: int = 1
    tasks_attempted: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    commands_run: list[dict[str, Any]] = field(default_factory=list)
    remaining_failures: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    proof_paths: list[str] = field(default_factory=list)
    next_action: str = ""
    mission_run_id: str = ""
    producer: str = "fluxio"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FinalProofReceipt:
    receipt_id: str
    mission_id: str
    host: str
    runtime: str
    workspace: str
    status: str
    summary: str
    final_mission_status: str
    schema: str = FINAL_PROOF_RECEIPT_SCHEMA_VERSION
    generated_at: str = field(default_factory=utc_now_iso)
    phase: str = "final_report"
    receipts_produced: list[MissionRunReceiptRef] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    commands_run: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    verification_result: str = ""
    proof_gaps: list[str] = field(default_factory=list)
    operator_actions_needed: list[str] = field(default_factory=list)
    follow_up_work: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    proof_paths: list[str] = field(default_factory=list)
    next_action: str = ""
    mission_run_id: str = ""
    producer: str = "fluxio"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StuckMissionReceipt:
    receipt_id: str
    mission_id: str
    host: str
    runtime: str
    workspace: str
    status: str
    summary: str
    decision: str
    schema: str = STUCK_MISSION_RECEIPT_SCHEMA_VERSION
    generated_at: str = field(default_factory=utc_now_iso)
    phase: str = "watchdog"
    stop_reason: str = ""
    artifact_gate_status: str = "missing_required_output"
    elapsed_minutes: int = 0
    missing_output_event_count: int = 0
    changed_files: list[str] = field(default_factory=list)
    artifacts: list[Any] = field(default_factory=list)
    latest_events: list[dict[str, Any]] = field(default_factory=list)
    last_stdout: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    proof_paths: list[str] = field(default_factory=list)
    next_action: str = ""
    mission_run_id: str = ""
    producer: str = "fluxio-watchdog"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MissionRunReceiptRef:
    receipt_id: str
    kind: str
    status: str
    path: str = ""
    summary: str = ""
    producer_phase: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    artifact_paths: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MissionRunPhaseState:
    phase: str
    status: str = "pending"
    attempt: int = 0
    host_id: str = ""
    runtime_id: str = ""
    lease_id: str = ""
    receipt_id: str = ""
    receipt_path: str = ""
    summary: str = ""
    error: str = ""
    started_at: str = ""
    completed_at: str = ""
    proof_paths: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MissionRunProcessRef:
    process_key: str
    kind: str
    command: str
    cwd: str
    host_id: str
    pid: int = 0
    parent_pid: int = 0
    status: str = "registered"
    started_at: str = field(default_factory=utc_now_iso)
    heartbeat_at: str = ""
    completed_at: str = ""
    ttl_seconds: int = 0
    port: int = 0
    exit_code: int | None = None
    stdout_tail_path: str = ""
    stderr_tail_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MissionRun:
    mission_run_id: str
    mission_id: str
    workspace_id: str
    objective: str
    schema_version: str = MISSION_RUN_SCHEMA_VERSION
    status: str = "draft"
    current_phase: str = "preflight"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    started_at: str = ""
    completed_at: str = ""
    runtime_id: str = ""
    runtime_kind: str = ""
    profile_name: str = ""
    run_profile: str = "standard"
    workspace_root: str = ""
    execution_root: str = ""
    host_id: str = ""
    preferred_host: str = ""
    assigned_host: str = ""
    host_locality: str = ""
    job_id: str = ""
    lease_id: str = ""
    lease_status: str = ""
    lease_heartbeat_at: str = ""
    queue_reason: str = ""
    blocked_reason: str = ""
    file_scope: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)
    selected_skills: list[str] = field(default_factory=list)
    required_artifacts: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    artifact_paths: list[str] = field(default_factory=list)
    proof_gaps: list[str] = field(default_factory=list)
    event_stream_path: str = ""
    final_report_path: str = ""
    receipts: list[MissionRunReceiptRef] = field(default_factory=list)
    phases: list[MissionRunPhaseState] = field(default_factory=list)
    process_tree: list[MissionRunProcessRef] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillSource:
    kind: str
    label: str = ""
    path: str = ""
    runtime_id: str = ""
    trusted: bool = True


@dataclass
class SkillPack:
    pack_id: str
    label: str
    description: str
    source: SkillSource
    recommended: bool = False
    installed: bool = False
    skills: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    audience: str = "all"
    action_kinds: list[str] = field(default_factory=list)
    profile_suitability: list[str] = field(default_factory=list)
    guidance_only: bool = False
    execution_capable: bool = False


@dataclass
class LearnedSkill:
    skill_id: str
    label: str
    description: str
    prompt_hint: str
    source: SkillSource
    confidence: float = 0.0
    status: str = "learned"
    disabled: bool = False
    usage_count: int = 0
    tags: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    audit: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    last_used_at: str | None = None


@dataclass
class SkillPromotionCandidate:
    candidate_id: str
    label: str
    reason: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    status: str = "candidate"
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class SkillUsageRecord:
    skill_id: str
    label: str
    step_id: str
    mission_id: str
    helped: bool
    source_kind: str
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class ModelRouteConfig:
    role: str
    provider: str
    model: str
    effort: str = "medium"
    budget_class: str = "balanced"
    fallback_policy: str = "same_provider"
    explanation: str = ""
    task_type: str = "general_coding"
    route_intent: str = ""
    fit_score: int = 0
    outcome_sample_count: int = 0
    outcome_success_rate: int = 0
    outcome_trend: str = ""


@dataclass
class ExecutionScope:
    requested: str = "isolated"
    strategy: str = "direct"
    execution_root: str = ""
    workspace_root: str = ""
    execution_target: str = "unresolved"
    storage_mode: str = "unknown"
    host_locality: str = "unknown"
    execution_target_detail: str = ""
    branch_name: str = ""
    worktree_path: str = ""
    isolated: bool = False
    status: str = "pending"
    detail: str = ""


@dataclass
class ExecutionPolicy:
    profile_name: str
    approval_mode: str = "tiered"
    explanation_depth: str = "medium"
    delegation_aggressiveness: str = "balanced"
    auto_allowed_kinds: list[str] = field(default_factory=list)
    approval_required_kinds: list[str] = field(default_factory=list)
    destructive_requires_approval: bool = True


@dataclass
class MissionCodeExecutionConfig:
    enabled: bool = False
    memory_limit: str = "4g"
    container_id: str = ""
    required: bool = False
    file_ids: list[str] = field(default_factory=list)
    last_started_at: str = ""
    last_result: str = ""
    last_error: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DelegatedRuntimeEvent:
    event_id: str
    delegated_id: str
    runtime_id: str
    kind: str
    message: str
    status: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class DelegatedApprovalRequest:
    request_id: str
    delegated_id: str
    runtime_id: str
    prompt: str
    risk_level: str = "medium"
    status: str = "pending"
    created_at: str = field(default_factory=utc_now_iso)
    resolved_at: str | None = None
    resolved_by: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DelegatedSessionSnapshot:
    delegated_id: str
    runtime_id: str
    status: str
    mission_id: str = ""
    detail: str = ""
    last_event: str = ""
    last_event_kind: str = ""
    latest_events: list[DelegatedRuntimeEvent] = field(default_factory=list)
    pending_approval: DelegatedApprovalRequest | None = None
    event_cursor: int = 0
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    workspace_root: str = ""
    execution_root: str = ""
    execution_target: str = "unresolved"
    storage_mode: str = "unknown"
    host_locality: str = "unknown"
    execution_target_detail: str = ""
    session_path: str = ""
    log_path: str = ""
    source_step_id: str = ""
    pid: int = 0
    supervisor_pid: int = 0
    exit_code: int | None = None
    heartbeat_at: str = ""
    heartbeat_status: str = "unknown"
    heartbeat_age_seconds: int | None = None
    heartbeat_interval_seconds: int = 10
    target_phase: str = ""
    target_role: str = ""
    target_provider: str = ""
    target_model: str = ""
    target_effort: str = ""
    target_budget_class: str = ""
    handoff_count: int = 0
    handoff_reason: str = ""
    source_delegated_id: str = ""
    changed_files: list[str] = field(default_factory=list)


@dataclass
class DelegatedRuntimeSession:
    delegated_id: str
    runtime_id: str
    launch_command: str
    mission_id: str = ""
    status: str = "queued"
    detail: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    last_event: str = ""
    session_path: str = ""
    workspace_root: str = ""
    execution_root: str = ""
    execution_target: str = "unresolved"
    storage_mode: str = "unknown"
    host_locality: str = "unknown"
    execution_target_detail: str = ""
    preferred_host: str = ""
    assigned_host: str = ""
    cluster_job_id: str = ""
    host_lease_id: str = ""
    lease_status: str = ""
    worker_heartbeat_at: str = ""
    log_path: str = ""
    events_path: str = ""
    decision_path: str = ""
    source_step_id: str = ""
    pid: int = 0
    supervisor_pid: int = 0
    exit_code: int | None = None
    acknowledged: bool = False
    last_event_kind: str = ""
    latest_events: list[dict[str, Any]] = field(default_factory=list)
    pending_approval: dict[str, Any] = field(default_factory=dict)
    approval_history: list[dict[str, Any]] = field(default_factory=list)
    event_cursor: int = 0
    heartbeat_at: str = ""
    heartbeat_status: str = "unknown"
    heartbeat_age_seconds: int | None = None
    heartbeat_interval_seconds: int = 10
    target_phase: str = ""
    target_role: str = ""
    target_provider: str = ""
    target_model: str = ""
    target_effort: str = ""
    target_budget_class: str = ""
    handoff_count: int = 0
    handoff_reason: str = ""
    source_delegated_id: str = ""
    changed_files: list[str] = field(default_factory=list)


@dataclass
class TutorialStep:
    step_id: str
    title: str
    description: str
    status: str = "pending"
    cta_label: str = ""
    panel: str = ""


@dataclass
class GuidanceCard:
    card_id: str
    title: str
    body: str
    kind: str
    status: str = "active"
    cta_label: str = ""
    panel: str = ""


@dataclass
class OnboardingProgress:
    selected_profile: str = ""
    completed_steps: list[str] = field(default_factory=list)
    dismissed_cards: list[str] = field(default_factory=list)
    current_step_id: str = ""
    is_complete: bool = False


@dataclass
class GuidanceTrigger:
    trigger_id: str
    kind: str
    reason: str
    mission_id: str = ""
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class RoutingDecision:
    role: str
    provider: str
    model: str
    reason: str
    budget_class: str
    task_type: str = "general_coding"
    route_intent: str = ""
    fit_score: int = 0
    outcome_sample_count: int = 0
    outcome_success_rate: int = 0
    outcome_trend: str = ""
    timestamp: str = field(default_factory=utc_now_iso)


@dataclass
class AppTaskDescriptor:
    task_id: str
    label: str
    description: str
    requires_approval: bool = False
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class AppContextSurface:
    surface_id: str
    label: str
    description: str
    access: str = "read"
    data_shape: dict[str, Any] = field(default_factory=dict)


@dataclass
class AppActionHook:
    hook_id: str
    label: str
    description: str
    mutability: str = "read"
    risk_level: str = "low"
    requires_approval: bool = False
    execution_kind: str = ""
    execution_command: str = ""
    health_url: str = ""
    app_url: str = ""


@dataclass
class CapabilityGrant:
    grant_id: str
    capability_key: str
    status: str
    scope: str = "app"
    reason: str = ""


@dataclass
class AppCapabilityManifest:
    manifest_id: str
    schema_version: str
    app_id: str
    name: str
    description: str
    bridge: dict[str, Any] = field(default_factory=dict)
    auth: dict[str, Any] = field(default_factory=dict)
    permissions: list[str] = field(default_factory=list)
    tasks: list[AppTaskDescriptor] = field(default_factory=list)
    context_surfaces: list[AppContextSurface] = field(default_factory=list)
    action_hooks: list[AppActionHook] = field(default_factory=list)
    ui_hints: dict[str, Any] = field(default_factory=dict)
    application_surface: dict[str, Any] = field(default_factory=dict)


@dataclass
class AppBridgeHandshake:
    app_id: str
    bridge_version: str
    session_id: str
    transport: str
    capabilities: list[str] = field(default_factory=list)
    auth_mode: str = "local_token"
    requires_user_present: bool = False


@dataclass
class ConnectedAppSession:
    session_id: str
    app_id: str
    app_name: str
    status: str
    bridge_health: str
    manifest_id: str = ""
    granted_capabilities: list[CapabilityGrant] = field(default_factory=list)
    active_tasks: list[str] = field(default_factory=list)
    last_seen_at: str = field(default_factory=utc_now_iso)
    notes: list[str] = field(default_factory=list)
    handshake_status: str = ""
    bridge_transport: str = ""
    bridge_endpoint: str = ""
    source_kind: str = "connected_app"
    app_root: str = ""
    context_preview: list[dict[str, Any]] = field(default_factory=list)
    action_hooks: list[dict[str, Any]] = field(default_factory=list)
    task_history: list[dict[str, Any]] = field(default_factory=list)
    latest_task_result: dict[str, Any] = field(default_factory=dict)
    approval_callback: dict[str, Any] = field(default_factory=dict)
    ui_hints: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlannedStep:
    step_id: str
    title: str
    description: str = ""
    status: str = "pending"
    kind: str = "primary"
    attempts: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class PlanRevision:
    revision_id: str
    trigger: str
    summary: str
    steps: list[PlannedStep] = field(default_factory=list)
    active_step_id: str | None = None
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class DerivedTask:
    task_id: str
    title: str
    reason: str
    source_step_id: str = ""
    status: str = "pending"
    priority: str = "normal"
    attempt_count: int = 0


@dataclass
class ImprovementQueueItem:
    item_id: str
    title: str
    reason: str
    priority: str = "medium"
    in_mission_scope: bool = False
    status: str = "queued"
    category: str = "product"
    source_step_id: str = ""
    notes: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class ActionApprovalGate:
    required: bool
    status: str = "not_required"
    risk_level: str = "low"
    reason: str = ""
    approved_by: str = ""
    resolved_at: str | None = None


@dataclass
class ActionProposal:
    action_id: str
    kind: str
    title: str
    command: str = ""
    query: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    risk_level: str = "low"
    requires_approval: bool = False
    source_step_id: str = ""
    reason: str = ""
    status: str = "proposed"
    event_id: str = ""
    target_path: str = ""
    target_scope: str = "workspace"
    mutability_class: str = "read"
    policy_decision: str = "auto_run"
    branch_name: str = ""
    worktree_path: str = ""
    delegation_metadata: dict[str, Any] = field(default_factory=dict)
    replay_cursor: str = ""


@dataclass
class ActionResultEnvelope:
    ok: bool
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    error: str = ""
    changed_files: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    target_path: str = ""
    result_summary: str = ""


@dataclass
class ActionExecutionRecord:
    action_id: str
    proposal: ActionProposal
    gate: ActionApprovalGate = field(
        default_factory=lambda: ActionApprovalGate(required=False)
    )
    result: ActionResultEnvelope = field(
        default_factory=lambda: ActionResultEnvelope(ok=False)
    )
    attempts: int = 0
    event_id: str = ""
    acked: bool = False
    replayed: bool = False
    executed_at: str | None = None
    retry_outcome: str = ""


@dataclass
class HarnessExecutionContext:
    mission_id: str
    workspace_root: str
    runtime_id: str
    profile_name: str
    execution_scope: ExecutionScope = field(default_factory=ExecutionScope)
    execution_policy: ExecutionPolicy = field(
        default_factory=lambda: ExecutionPolicy(profile_name="builder")
    )
    code_execution: MissionCodeExecutionConfig = field(
        default_factory=MissionCodeExecutionConfig
    )
    route_configs: list[ModelRouteConfig] = field(default_factory=list)
    broadening_threshold: int = 2
    innovation_scope: str = "bounded"
    harness_id: str = "fluxio_hybrid"


@dataclass
class HarnessStopReason:
    kind: str
    detail: str = ""


@dataclass
class HarnessStepResult:
    status: str
    plan_revision: PlanRevision | None = None
    action_record: ActionExecutionRecord | None = None
    verification_results: list[VerificationResult] = field(default_factory=list)
    derived_tasks: list[DerivedTask] = field(default_factory=list)
    improvement_items: list[ImprovementQueueItem] = field(default_factory=list)
    routing_decisions: list[RoutingDecision] = field(default_factory=list)
    stop_reason: HarnessStopReason | None = None


@dataclass
class MissionEvent:
    mission_id: str
    kind: str
    message: str
    timestamp: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Mission:
    mission_id: str
    workspace_id: str
    runtime_id: str
    objective: str
    success_checks: list[str]
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    title: str = ""
    run_budget: MissionRunBudget = field(
        default_factory=lambda: MissionRunBudget(
            mode="Autopilot",
            max_runtime_seconds=0,
            focus_window_hours=0,
            enforced=False,
        )
    )
    verification_policy: MissionVerificationPolicy = field(
        default_factory=MissionVerificationPolicy
    )
    escalation_policy: ApprovalEscalation = field(
        default_factory=lambda: ApprovalEscalation(
            channel="telegram",
            enabled=False,
            destination="",
            triggers=[],
        )
    )
    harness_id: str = "fluxio_hybrid"
    selected_profile: str = "builder"
    execution_scope: ExecutionScope = field(default_factory=ExecutionScope)
    execution_policy: ExecutionPolicy = field(
        default_factory=lambda: ExecutionPolicy(profile_name="builder")
    )
    code_execution: MissionCodeExecutionConfig = field(
        default_factory=MissionCodeExecutionConfig
    )
    route_configs: list[ModelRouteConfig] = field(default_factory=list)
    routing_decisions: list[RoutingDecision] = field(default_factory=list)
    effective_route_contract: dict[str, Any] = field(default_factory=dict)
    current_plan_revision_id: str | None = None
    plan_revisions: list[PlanRevision] = field(default_factory=list)
    derived_tasks: list[DerivedTask] = field(default_factory=list)
    improvement_queue: list[ImprovementQueueItem] = field(default_factory=list)
    planned_file_scope: list[str] = field(default_factory=list)
    skill_usage: list[SkillUsageRecord] = field(default_factory=list)
    learned_skill_events: list[dict[str, Any]] = field(default_factory=list)
    action_history: list[ActionExecutionRecord] = field(default_factory=list)
    delegated_runtime_sessions: list[DelegatedRuntimeSession] = field(default_factory=list)
    tutorial_context: dict[str, Any] = field(default_factory=dict)
    mission_contract: dict[str, Any] = field(default_factory=dict)
    planner_loop_status: str = "idle"
    state: MissionStateSnapshot = field(default_factory=MissionStateSnapshot)
    proof: MissionProof = field(default_factory=MissionProof)


@dataclass
class WorkspaceProfile:
    workspace_id: str
    name: str
    root_path: str
    default_runtime: str
    workspace_type: str
    user_profile: str = "builder"
    preferred_harness: str = "fluxio_hybrid"
    routing_strategy: str = "profile_default"
    route_overrides: list[dict[str, Any]] = field(default_factory=list)
    auto_optimize_routing: bool = False
    openai_codex_auth_mode: str = "none"
    minimax_auth_mode: str = "none"
    commit_message_style: str = "scoped"
    execution_target_preference: str = "profile_default"
    local_project_path: str = ""
    nas_project_path: str = ""
    sync_mode: str = "manual"
    sync_direction: str = "bidirectional"
    sync_conflict_policy: str = "keep_newer_and_log"
    auto_sync_to_nas: bool = False
    preferred_host: str = ""
    assigned_host: str = ""
    allow_nas_fallback: bool = False
    goals: list[str] = field(default_factory=list)
    enabled: bool = True
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class SkillRecommendation:
    recommendation_id: str
    label: str
    reason: str
    runtime_id: str
    workspace_type: str
    enabled_by_default: bool = False


@dataclass
class IntegrationRecommendation:
    recommendation_id: str
    label: str
    reason: str
    command: str
    runtime_id: str
    workspace_type: str
    enabled_by_default: bool = False


def to_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return value
