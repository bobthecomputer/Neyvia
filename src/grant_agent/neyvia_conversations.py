from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from . import turn_compartment
from .semantic_missions import CollaborativeWorkspace, Mission, MissionGate, Provenance, mission_from_message


CONVERSATION_KINDS = {"chat", "orchestration"}
TITLE_MODES = {"off", "suggest", "automatic"}
ATTENTION_STATES = {
    "needs-action",
    "active",
    "ready-for-review",
    "quiet",
    "settled",
}
TERMINAL_CONVERSATION_STATUSES = {
    "completed",
    "done",
    "failed",
    "stopped",
    "cancelled",
    "canceled",
}
QUESTION_BRANCH_ALLOWED_PREFIXES = (
    "artifact.read",
    "browser.read",
    "context.read",
    "conversation.read",
    "file.read",
    "git.read",
    "log.read",
    "mcp.resource.read",
    "search.",
    "shell.read",
)
AGENT_LIFECYCLE_STAGES = (
    "requested",
    "allocating",
    "packing_context",
    "isolating_workspace",
    "connecting_tools",
    "ready",
    "working",
    "waiting",
    "input_required",
    "completed",
    "failed",
    "cancelled",
)
TEAM_CONTRACT_FIELDS = (
    "outcome",
    "requiredEvidence",
    "authority",
    "budget",
    "stopCondition",
    "handback",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _tokens(value: object) -> list[str]:
    return list(dict.fromkeys(re.findall(r"[\w]+", str(value or "").casefold(), flags=re.UNICODE)))


def _fingerprint(*values: object) -> str:
    normalized = " ".join(sorted(set(token for value in values for token in _tokens(value))))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24] if normalized else ""


def generated_title(value: object, *, limit: int = 72) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"^(please|could you|can you|i would like you to|i want you to)\s+", "", text, flags=re.I)
    if not text:
        return "New conversation"
    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip(" .:-")
    if len(first.split()) < 3 and len(text.split()) >= 3:
        first = text
    if len(first) > limit:
        first = first[: limit - 1].rstrip(" ,.;:-") + "…"
    return first[:1].upper() + first[1:] if first else "New conversation"


def _bounded_text(value: object, *, limit: int = 700) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _latest_goal_loop_status(turn_rows: list[sqlite3.Row]) -> str:
    """Read the latest durable goal checkpoint without treating model text as state."""
    def visit(value: object) -> list[str]:
        found: list[str] = []
        if isinstance(value, dict):
            checkpoint = value.get("goalLoop")
            if isinstance(checkpoint, dict):
                nested = checkpoint.get("checkpoint") if isinstance(checkpoint.get("checkpoint"), dict) else checkpoint
                status = str(nested.get("status") or "").strip().casefold()
                if status in {"active", "blocked", "paused", "completed"}:
                    found.append(status)
            for child in value.values():
                found.extend(visit(child))
        elif isinstance(value, list):
            for child in value:
                found.extend(visit(child))
        return found

    latest = ""
    for row in turn_rows:
        # A new request invalidates completion evidence from an earlier task.
        if row["role"] == "user":
            latest = ""
        latest_values = visit(_decode(row["metadata_json"], {}))
        if latest_values:
            latest = latest_values[-1]
    return latest


DEFAULT_TEAM_STOP_CONDITION = "Stop when the bounded outcome is evidenced, blocked, or needs operator input."


def _team_contract(raw: object, task: dict[str, Any]) -> dict[str, Any]:
    """Create an explicit, bounded contract for one specialist."""

    supplied = dict(raw) if isinstance(raw, dict) else {}
    objective = _bounded_text(
        supplied.get("outcome")
        or task.get("objective")
        or task.get("title")
        or "Return the assigned bounded outcome."
    )
    required_evidence = [
        _bounded_text(item, limit=180)
        for item in supplied.get("requiredEvidence") or []
        if _bounded_text(item, limit=180)
    ][:12]
    if not required_evidence:
        required_evidence = [
            "Typed claims with source or verification references",
            "At least one durable artifact or verification result",
        ]
    authority = (
        dict(supplied.get("authority") or {})
        if isinstance(supplied.get("authority"), dict)
        else {}
    )
    authority.setdefault(
        "allowed",
        ["read_assigned_scope", "propose_changes", "produce_artifacts"],
    )
    authority.setdefault(
        "requiresApproval",
        ["external_side_effect", "scope_expansion", "activate_capability"],
    )
    authority.setdefault(
        "forbidden",
        ["invent_receipts", "silently_raise_trust", "silently_mutate_active_skills"],
    )
    budget = (
        dict(supplied.get("budget") or {})
        if isinstance(supplied.get("budget"), dict)
        else {}
    )
    budget.setdefault("proofChecks", 2)
    budget.setdefault("contextMode", "bounded")
    budget.setdefault("maxParallelPeers", 4)
    handback = (
        dict(supplied.get("handback") or {})
        if isinstance(supplied.get("handback"), dict)
        else {}
    )
    handback.setdefault("schema", "neyvia.agent_delta.v1")
    handback.setdefault(
        "required",
        ["claims", "evidence", "artifacts", "conflicts", "blockers"],
    )
    handback.setdefault("transcriptsIncluded", False)
    return {
        "schema": "neyvia.team_contract.v1",
        "outcome": objective,
        "requiredEvidence": required_evidence,
        "authority": authority,
        "budget": budget,
        "stopCondition": _bounded_text(
            supplied.get("stopCondition")
            or DEFAULT_TEAM_STOP_CONDITION
        ),
        "handback": handback,
    }


def _dynamic_child_contract(
    raw: object,
    *,
    objective: object,
    required_evidence: object = None,
    stop_condition: object = None,
) -> dict[str, Any]:
    """Canonicalize a dynamic-child contract without discarding its provenance."""

    supplied = dict(raw) if isinstance(raw, dict) else {}
    lifecycle = supplied.get("lifecycle") if isinstance(supplied.get("lifecycle"), dict) else {}
    handback = supplied.get("handback") if isinstance(supplied.get("handback"), dict) else {}
    evidence_source = (
        required_evidence
        if isinstance(required_evidence, list) and required_evidence
        else handback.get("required")
    )
    required = [
        _bounded_text(item, limit=180)
        for item in evidence_source or []
        if _bounded_text(item, limit=180)
    ][:12]
    canonical = dict(supplied)
    if supplied.get("schema") and supplied.get("schema") != "neyvia.team_contract.v1":
        canonical.setdefault("dynamicChildSchema", supplied["schema"])
    canonical["schema"] = "neyvia.team_contract.v1"
    canonical["outcome"] = _bounded_text(objective)
    canonical["requiredEvidence"] = required
    canonical["stopCondition"] = _bounded_text(
        stop_condition
        or supplied.get("stopCondition")
        or lifecycle.get("stopCondition")
        or DEFAULT_TEAM_STOP_CONDITION
    )
    return canonical


def _explicit_route_snapshot(conversation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return only an immutable explicit route snapshot, never workspace defaults."""

    metadata = conversation.get("metadata") if isinstance(conversation, dict) else {}
    selection = metadata.get("teamSelection") if isinstance(metadata, dict) else None
    snapshot = metadata.get("routeSnapshot") if isinstance(metadata, dict) else None
    if not isinstance(selection, dict) or selection.get("mode") != "explicit" or not isinstance(snapshot, dict):
        return {}
    output: dict[str, dict[str, Any]] = {}
    for role, raw in snapshot.items():
        if not isinstance(raw, dict):
            continue
        output[str(role).strip().lower()] = {
            "role": str(raw.get("role") or role).strip().lower(),
            "runtimeId": str(raw.get("runtimeId") or raw.get("runtime") or "").strip().lower(),
            "provider": str(raw.get("provider") or "").strip(),
            "model": str(raw.get("model") or "").strip(),
            "effort": str(raw.get("effort") or "").strip().lower(),
        }
    return output


def _route_conflicts(snapshot: dict[str, Any], requested: dict[str, Any]) -> list[str]:
    """Return fields where a requested route contradicts immutable history."""
    conflicts: list[str] = []
    for field in ("runtimeId", "provider", "model", "effort"):
        if field not in requested or requested.get(field) in (None, ""):
            continue
        expected = str(snapshot.get(field) or "").strip().lower()
        actual = str(requested.get(field) or "").strip().lower()
        if expected and actual and expected != actual:
            conflicts.append(field)
    return conflicts


def typed_plan_hash(plan: dict[str, Any]) -> str:
    """Return the approval digest for a typed lead plan.

    Approval metadata and a previously computed digest are excluded so the
    digest is stable across the plan -> approve handoff.
    """

    body = dict(plan) if isinstance(plan, dict) else {}
    for key in ("approvedPlanHash", "planHash", "approved", "validated", "approval"):
        body.pop(key, None)
    return hashlib.sha256(_json(body).encode("utf-8")).hexdigest()


def validate_typed_lead_plan(plan: object) -> dict[str, Any]:
    """Validate the model-facing lead schema without persisting children."""

    if not isinstance(plan, dict):
        raise ValueError("typed lead plan must be an object")
    if str(plan.get("schema") or "") != "neyvia.orchestration.typed-lead-plan.v1":
        raise ValueError("typed lead plan has an unsupported schema")
    children = plan.get("children") or plan.get("tasks")
    if not isinstance(children, list) or not 6 <= len(children) <= 10:
        raise ValueError("validated typed lead plans must contain between 6 and 10 children")
    governor = plan.get("governor")
    if not isinstance(governor, dict):
        raise ValueError("typed lead plan must include a governor object")
    try:
        max_parallel = int(governor.get("maxParallel"))
    except (TypeError, ValueError) as exc:
        raise ValueError("typed lead plan governor.maxParallel must be an integer") from exc
    if not 1 <= max_parallel <= 16:
        raise ValueError("typed lead plan governor.maxParallel must be between 1 and 16")
    ids: set[str] = set()
    names: set[str] = set()
    dependencies: dict[str, set[str]] = {}
    for raw in children:
        if not isinstance(raw, dict):
            raise ValueError("each typed child must be an object")
        child_id = str(raw.get("id") or raw.get("taskId") or "").strip()
        name = str(raw.get("name") or raw.get("title") or "").strip()
        if not child_id or not name:
            raise ValueError("each typed child requires a unique id and name")
        if child_id in ids or name.casefold() in names:
            raise ValueError("typed lead children must have unique ids and names")
        ids.add(child_id)
        names.add(name.casefold())
        route = raw.get("routeSelection") or raw.get("route")
        if not isinstance(route, dict) or not str(route.get("model") or "").strip() or not str(route.get("effort") or "").strip():
            raise ValueError(f"typed child {child_id} requires an explicit route")
        for field in ("budget", "authority", "handback"):
            if not isinstance(raw.get(field), dict) or not raw.get(field):
                raise ValueError(f"typed child {child_id} requires an explicit {field}")
        if not isinstance(raw.get("tools"), list) and not isinstance(raw.get("capabilities"), list):
            raise ValueError(f"typed child {child_id} requires an explicit tools list")
        dependencies[child_id] = {
            str(value).strip()
            for value in raw.get("dependencies") or []
            if str(value).strip()
        }
    for child_id, required in dependencies.items():
        unknown = sorted(required - ids)
        if unknown:
            raise ValueError(f"unknown dependencies for {child_id}: {', '.join(unknown)}")
    pending = set(ids)
    resolved: set[str] = set()
    while pending:
        ready = {child_id for child_id in pending if dependencies[child_id] <= resolved}
        if not ready:
            raise ValueError("typed child dependency graph contains a cycle")
        resolved.update(ready)
        pending -= ready
    return dict(plan)


LEAD_WORKERS_PRESET_ID = "lead-workers"
LEAD_WORKERS_MAX_NODES = 6
LEAD_WORKERS_MAX_PARALLEL = 3
FROZEN_SOL_PLANNER_ROUTE = {
    "role": "planner",
    "runtimeId": "codex",
    "provider": "openai-codex",
    "model": "gpt-5.6-sol",
    "model_id": "codex/gpt-5.6-sol",
    "effort": "xhigh",
}


def build_lead_workers_preset(
    conversation_id: str,
    *,
    objective: str = "Complete the bounded orchestration objective.",
    worker_count: int = 2,
    sequential_integration: bool = False,
) -> dict[str, Any]:
    """Build the reusable, route-frozen Lead + workers graph contract.

    This only creates durable-plan input. It never starts a runtime invocation.
    """

    try:
        bounded_workers = int(worker_count)
    except (TypeError, ValueError) as exc:
        raise ValueError("lead-workers workerCount must be an integer from 2 to 4") from exc
    if bounded_workers < 2 or bounded_workers > 4:
        raise ValueError("lead-workers workerCount must be between 2 and 4")
    integration = bool(sequential_integration)
    node_count = 1 + bounded_workers + int(integration) + 1
    if node_count > LEAD_WORKERS_MAX_NODES:
        raise ValueError(
            "lead-workers exceeds the six-node milestone cap; use at most 3 workers when sequential integration is enabled"
        )

    conversation_key = str(conversation_id or "").strip()
    if not conversation_key:
        raise ValueError("conversationId is required for the lead-workers preset")
    bounded_objective = str(objective or "").strip() or "Complete the bounded orchestration objective."
    bounded_objective = bounded_objective[:800]
    lead_id = f"lead_{conversation_key}"
    worker_ids = [f"worker_{conversation_key}_{index + 1}" for index in range(bounded_workers)]
    integration_id = f"integration_{conversation_key}" if integration else ""
    barrier_id = f"barrier_{conversation_key}"

    sol_route = {
        "role": "planner",
        "runtimeId": "codex",
        "provider": "openai-codex",
        "model": "gpt-5.6-sol",
        "model_id": "codex/gpt-5.6-sol",
        "effort": "xhigh",
    }
    luna_route = {
        "role": "executor",
        "runtimeId": "codex",
        "provider": "openai-codex",
        "model": "gpt-5.6-luna",
        "model_id": "codex/gpt-5.6-luna",
        "effort": "high",
    }
    terra_route = {
        "role": "verifier",
        "runtimeId": "codex",
        "provider": "openai-codex",
        "model": "gpt-5.6-terra",
        "model_id": "codex/gpt-5.6-terra",
        "effort": "medium",
    }
    worker_tasks = [
        {
            "id": worker_id,
            "role": "executor",
            "title": f"Luna worker {index + 1}",
            "objective": f"Implement a disjoint, evidenced slice of: {bounded_objective}",
            "routeSelection": luna_route,
            "dependencies": [lead_id],
            "assignedScope": [f"lead-workers:worker:{index + 1}"],
            "capabilities": ["workspace-write", "code-editing", "tool-execution"],
            "teamContract": {
                "authority": {
                    "allowWorkspaceMutation": True,
                    "allowed": ["read_assigned_scope", "propose_changes", "produce_artifacts", "workspace-write", "code-editing"],
                },
            },
        }
        for index, worker_id in enumerate(worker_ids)
    ]
    integration_task = (
        {
            "id": integration_id,
            "role": "executor",
            "title": "Luna sequential integration",
            "objective": f"Integrate the completed worker deltas for: {bounded_objective}",
            "routeSelection": luna_route,
            "dependencies": worker_ids,
            "assignedScope": ["lead-workers:integration"],
            "capabilities": ["workspace-write", "code-editing", "tool-execution"],
            "teamContract": {
                "authority": {
                    "allowWorkspaceMutation": True,
                    "allowed": ["read_assigned_scope", "propose_changes", "produce_artifacts", "workspace-write", "code-editing"],
                },
            },
        }
        if integration
        else None
    )
    barrier_dependencies = [integration_id] if integration else list(worker_ids)
    tasks = [
        {
            "id": lead_id,
            "role": "planner",
            "title": "Sol lead",
            "objective": f"Decompose and coordinate the bounded objective: {bounded_objective}",
            "routeSelection": sol_route,
            "assignedScope": ["lead-workers:lead"],
            "capabilities": ["reasoning", "tool-execution"],
        },
        *worker_tasks,
        *([integration_task] if integration_task else []),
        {
            "id": barrier_id,
            "role": "verifier",
            "title": "Terra verification barrier",
            "objective": f"Verify receipts, changed scope, and evidence for: {bounded_objective}",
            "routeSelection": terra_route,
            "dependencies": barrier_dependencies,
            "assignedScope": ["lead-workers:verification"],
            "capabilities": ["reasoning", "tool-execution"],
        },
    ]
    preset = {
        "id": LEAD_WORKERS_PRESET_ID,
        "schema": "neyvia.orchestration.preset.lead-workers.v1",
        "workerCount": bounded_workers,
        "sequentialIntegration": integration,
        "nodeCount": node_count,
        "maxParallel": LEAD_WORKERS_MAX_PARALLEL,
        "routes": {"lead": sol_route, "workers": luna_route, "barrier": terra_route},
        "proofBoundary": "runtime receipts and durable child history only; synthetic branch scoring is not proof",
    }
    return {"preset": preset, "tasks": tasks, "maxParallel": LEAD_WORKERS_MAX_PARALLEL}


class NeyviaConversationStore:
    """Crash-proof conversations, context, and dependency-aware agent graphs."""

    def __init__(self, root: str | Path, *, database_path: str | Path | None = None) -> None:
        self.root = Path(root).resolve()
        self.database_path = Path(database_path) if database_path else self.root / ".agent_control" / "crashproof.sqlite3"
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.fts_available = False
        self._ensure_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL CHECK(kind IN ('chat', 'orchestration')),
                    parent_conversation_id TEXT,
                    branch_kind TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    generated_title TEXT NOT NULL DEFAULT '',
                    title_mode TEXT NOT NULL DEFAULT 'automatic',
                    title_locked INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'active',
                    attention_state TEXT NOT NULL DEFAULT 'active',
                    lifecycle_state TEXT NOT NULL DEFAULT 'active',
                    settled_at TEXT,
                    settled_by TEXT,
                    settlement_reason TEXT,
                    snoozed_until TEXT,
                    snooze_reason TEXT,
                    next_wake_condition TEXT,
                    project_id TEXT NOT NULL DEFAULT '',
                    branch TEXT NOT NULL DEFAULT '',
                    pull_request_json TEXT NOT NULL DEFAULT '{}',
                    unread_meaningful_changes INTEGER NOT NULL DEFAULT 0,
                    capability_policy_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    topic_fingerprint TEXT NOT NULL DEFAULT '',
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_meaningful_activity_at TEXT NOT NULL,
                    archived_at TEXT,
                    deleted_at TEXT,
                    FOREIGN KEY(parent_conversation_id) REFERENCES conversations(conversation_id)
                );
                CREATE INDEX IF NOT EXISTS idx_conversations_recent
                    ON conversations(deleted_at, last_meaningful_activity_at DESC);
                CREATE INDEX IF NOT EXISTS idx_conversations_parent
                    ON conversations(parent_conversation_id, last_meaningful_activity_at DESC);

                CREATE TABLE IF NOT EXISTS conversation_turns (
                    turn_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    turn_kind TEXT NOT NULL DEFAULT 'dialogue',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    meaningful INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_conversation_turns_order
                    ON conversation_turns(conversation_id, created_at, turn_id);

                CREATE TABLE IF NOT EXISTS conversation_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    meaningful INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS context_atoms (
                    atom_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    evidence_turn_id TEXT,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    freshness_expires_at TEXT,
                    supersedes_atom_id TEXT,
                    permission_scope_json TEXT NOT NULL DEFAULT '{}',
                    topic_fingerprint TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
                    FOREIGN KEY(evidence_turn_id) REFERENCES conversation_turns(turn_id) ON DELETE SET NULL,
                    FOREIGN KEY(supersedes_atom_id) REFERENCES context_atoms(atom_id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_context_atoms_conversation
                    ON context_atoms(conversation_id, deleted_at, updated_at DESC);

                CREATE TABLE IF NOT EXISTS agent_nodes (
                    node_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    parent_node_id TEXT,
                    durable_task_id TEXT,
                    parent_task_id TEXT NOT NULL DEFAULT '',
                    child_conversation_id TEXT,
                    approved_plan_hash TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    objective TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'queued',
                    lifecycle_stage TEXT NOT NULL DEFAULT 'requested',
                    runtime TEXT NOT NULL DEFAULT '',
                    assigned_scope_json TEXT NOT NULL DEFAULT '[]',
                    capabilities_json TEXT NOT NULL DEFAULT '[]',
                    team_contract_json TEXT NOT NULL DEFAULT '{}',
                    progress_json TEXT NOT NULL DEFAULT '{}',
                    result_summary_json TEXT NOT NULL DEFAULT '{}',
                    wave INTEGER NOT NULL DEFAULT 0,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
                    FOREIGN KEY(parent_node_id) REFERENCES agent_nodes(node_id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_nodes_conversation
                    ON agent_nodes(conversation_id, wave, created_at);

                CREATE TABLE IF NOT EXISTS agent_dependencies (
                    conversation_id TEXT NOT NULL,
                    from_node_id TEXT NOT NULL,
                    to_node_id TEXT NOT NULL,
                    dependency_kind TEXT NOT NULL DEFAULT 'finish_to_start',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(conversation_id, from_node_id, to_node_id),
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
                    FOREIGN KEY(from_node_id) REFERENCES agent_nodes(node_id) ON DELETE CASCADE,
                    FOREIGN KEY(to_node_id) REFERENCES agent_nodes(node_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS orchestration_plans (
                    conversation_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    schema_name TEXT NOT NULL,
                    approved_plan_hash TEXT NOT NULL,
                    parent_task_id TEXT NOT NULL DEFAULT '',
                    plan_json TEXT NOT NULL DEFAULT '{}',
                    governor_json TEXT NOT NULL DEFAULT '{}',
                    preset_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS dynamic_plan_runs (
                    run_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    planner_route_json TEXT NOT NULL DEFAULT '{}',
                    planner_receipt_json TEXT NOT NULL DEFAULT '{}',
                    raw_reply TEXT NOT NULL DEFAULT '',
                    typed_plan_json TEXT NOT NULL DEFAULT '{}',
                    validation_errors_json TEXT NOT NULL DEFAULT '[]',
                    plan_hash TEXT NOT NULL DEFAULT '',
                    approval_receipt_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_dynamic_plan_runs_latest
                    ON dynamic_plan_runs(conversation_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS synthesis_runs (
                    synthesis_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    recommendation TEXT NOT NULL DEFAULT '',
                    rationale TEXT NOT NULL DEFAULT '',
                    candidate_node_ids_json TEXT NOT NULL DEFAULT '[]',
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS semantic_missions (
                    mission_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL UNIQUE,
                    mission_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS semantic_workspace_objects (
                    object_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    object_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
                    FOREIGN KEY(turn_id) REFERENCES conversation_turns(turn_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_semantic_workspace_objects_conversation
                    ON semantic_workspace_objects(conversation_id, created_at, object_id);
                """
            )
            existing_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(conversations)")
            }
            lifecycle_columns = {
                "attention_state": "TEXT NOT NULL DEFAULT 'active'",
                "lifecycle_state": "TEXT NOT NULL DEFAULT 'active'",
                "settled_at": "TEXT",
                "settled_by": "TEXT",
                "settlement_reason": "TEXT",
                "snoozed_until": "TEXT",
                "snooze_reason": "TEXT",
                "next_wake_condition": "TEXT",
                "project_id": "TEXT NOT NULL DEFAULT ''",
                "branch": "TEXT NOT NULL DEFAULT ''",
                "pull_request_json": "TEXT NOT NULL DEFAULT '{}'",
                "unread_meaningful_changes": "INTEGER NOT NULL DEFAULT 0",
                "archived_at": "TEXT",
            }
            for name, definition in lifecycle_columns.items():
                if name not in existing_columns:
                    connection.execute(
                        f"ALTER TABLE conversations ADD COLUMN {name} {definition}"
                    )
            agent_node_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(agent_nodes)")
            }
            if "team_contract_json" not in agent_node_columns:
                connection.execute(
                    "ALTER TABLE agent_nodes ADD COLUMN "
                    "team_contract_json TEXT NOT NULL DEFAULT '{}'"
                )
            for name, definition in {
                "parent_task_id": "TEXT NOT NULL DEFAULT ''",
                "child_conversation_id": "TEXT",
                "approved_plan_hash": "TEXT NOT NULL DEFAULT ''",
            }.items():
                if name not in agent_node_columns:
                    connection.execute(
                        f"ALTER TABLE agent_nodes ADD COLUMN {name} {definition}"
                    )
            try:
                connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS conversation_search_fts USING fts5(
                        conversation_id UNINDEXED,
                        source_id UNINDEXED,
                        source_kind UNINDEXED,
                        title,
                        content,
                        tags,
                        tokenize='unicode61 remove_diacritics 2'
                    )
                    """
                )
                self.fts_available = True
            except sqlite3.OperationalError:
                self.fts_available = False
            connection.commit()

    def create_conversation(
        self,
        *,
        workspace_id: str = "",
        kind: str = "chat",
        parent_conversation_id: str | None = None,
        branch_kind: str = "",
        title: str = "",
        title_mode: str = "automatic",
        capability_policy: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        conversation_id: str | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        normalized_kind = str(kind or "chat").strip().lower()
        normalized_title_mode = str(title_mode or "automatic").strip().lower()
        if normalized_kind not in CONVERSATION_KINDS:
            raise ValueError(f"unknown conversation kind: {kind}")
        if normalized_title_mode not in TITLE_MODES:
            raise ValueError(f"unknown title mode: {title_mode}")
        timestamp = now or utc_now_iso()
        conversation_id = conversation_id or f"conversation_{uuid.uuid4().hex}"
        if parent_conversation_id:
            self.get_conversation(parent_conversation_id)
        visible_title = generated_title(title) if title else "New conversation"
        generated = visible_title if title and normalized_title_mode != "off" else ""
        policy = capability_policy or {"mode": "standard", "readOnly": False}
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO conversations (
                    conversation_id, workspace_id, kind, parent_conversation_id, branch_kind,
                    title, generated_title, title_mode, title_locked, status,
                    capability_policy_json, metadata_json, topic_fingerprint,
                    created_at, updated_at, last_meaningful_activity_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    str(workspace_id or "").strip(),
                    normalized_kind,
                    parent_conversation_id,
                    str(branch_kind or "").strip(),
                    visible_title,
                    generated,
                    normalized_title_mode,
                    int(bool(title and normalized_title_mode == "off")),
                    _json(policy),
                    _json(metadata or {}),
                    _fingerprint(title, metadata or {}),
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            self._append_event(connection, conversation_id, "conversation.created", {"kind": normalized_kind, "branchKind": branch_kind}, True, timestamp)
            self._index_row(connection, conversation_id, conversation_id, "conversation", visible_title, "", f"{normalized_kind} {branch_kind}")
            connection.commit()
        mission_meta = metadata or {}
        if normalized_kind == "orchestration" or mission_meta.get("desiredOutcome") or mission_meta.get("objective") or isinstance(mission_meta.get("mission"), dict):
            mission_spec = mission_meta.get("mission") if isinstance(mission_meta.get("mission"), dict) else mission_meta
            self.create_semantic_mission(
                conversation_id,
                desired_outcome=str(mission_spec.get("desiredOutcome") or mission_spec.get("objective") or title or "Continue the conversation mission"),
                acceptance_gates=[str(item) for item in (mission_spec.get("acceptanceGates") or mission_spec.get("successChecks") or [])],
                boundaries=[str(item) for item in (mission_spec.get("boundaries") or [])],
                exact_routes=mission_spec.get("exactRoutes") or mission_meta.get("routeSnapshot") or [],
                authority=mission_spec.get("authority") or {},
                evidence_requirements=[str(item) for item in (mission_spec.get("evidenceRequirements") or [])],
                continuation_state={"createdFromConversation": conversation_id},
                now=timestamp,
            )
        return self.get_conversation(conversation_id)

    def goal_modes(self, conversation_ids: list[str]) -> dict[str, bool]:
        """Read canonical preferences for the UI index in one bounded query."""
        ids = list(dict.fromkeys(str(value) for value in conversation_ids if value))[:1000]
        if not ids:
            return {}
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT conversation_id, metadata_json FROM conversations WHERE deleted_at IS NULL AND conversation_id IN ("
                + ",".join("?" for _ in ids) + ")", ids).fetchall()
        result = {}
        for row in rows:
            metadata = _decode(row["metadata_json"], {})
            if isinstance(metadata, dict) and isinstance(metadata.get("goalMode"), bool):
                result[str(row["conversation_id"])] = metadata["goalMode"]
        return result

    def set_goal_mode(
        self,
        conversation_id: str,
        enabled: bool,
        *,
        now: str | None = None,
    ) -> dict[str, Any]:
        """Persist whether this chat should continue against an explicit goal."""
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        timestamp = now or utc_now_iso()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._required_conversation_row(connection, conversation_id)
            metadata = _decode(row["metadata_json"], {})
            metadata = metadata if isinstance(metadata, dict) else {}
            metadata["goalMode"] = bool(enabled)
            connection.execute(
                "UPDATE conversations SET metadata_json = ?, revision = revision + 1, updated_at = ?, last_meaningful_activity_at = ? WHERE conversation_id = ?",
                (_json(metadata), timestamp, timestamp, conversation_id),
            )
            self._append_event(connection, conversation_id, "conversation.goal-mode-changed", {"enabled": bool(enabled)}, True, timestamp)
            connection.commit()
        return self.get_conversation(conversation_id)

    def create_question_branch(
        self,
        parent_conversation_id: str,
        *,
        question: str,
        title_mode: str = "automatic",
        now: str | None = None,
    ) -> dict[str, Any]:
        # Apply the turn's admission rule before creating its durable branch.
        # Otherwise an empty question leaves an orphan conversation on refusal.
        if not str(question or "").strip():
            raise ValueError("conversation turn content is required")
        parent = self.get_conversation(parent_conversation_id)
        branch = self.create_conversation(
            workspace_id=parent["workspaceId"],
            kind=parent["kind"],
            parent_conversation_id=parent_conversation_id,
            branch_kind="question",
            title=question,
            title_mode=title_mode,
            capability_policy={
                "mode": "ask",
                "readOnly": True,
                "allowedActionPrefixes": list(QUESTION_BRANCH_ALLOWED_PREFIXES),
                "mutationAllowed": False,
                "publicCommunicationAllowed": False,
                "spendAllowed": False,
            },
            metadata={"inheritsContextFrom": parent_conversation_id},
            now=now,
        )
        self.append_turn(branch["conversationId"], role="user", content=question, source="question-branch", now=now)
        result = self.get_conversation(branch["conversationId"], include_turns=True)
        from .proofs_d_neyvia import conversation_question
        conversation_question(parent, result)
        return result

    def get_conversation(self, conversation_id: str, *, include_turns: bool = False) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM conversations WHERE conversation_id = ?", (conversation_id,)).fetchone()
            if not row:
                raise KeyError(conversation_id)
            conversation = self._conversation_from_row(row)
            if include_turns:
                turns = connection.execute(
                    "SELECT * FROM conversation_turns WHERE conversation_id = ? ORDER BY created_at, turn_id",
                    (conversation_id,),
                ).fetchall()
                conversation["turns"] = [self._turn_from_row(turn) for turn in turns]
            conversation["semantic"] = self._semantic_projection(connection, conversation_id)
        return conversation

    def create_semantic_mission(
        self,
        conversation_id: str,
        *,
        desired_outcome: str,
        acceptance_gates: list[str],
        boundaries: list[str] | None = None,
        exact_routes: list[dict[str, Any]] | None = None,
        authority: dict[str, Any] | None = None,
        evidence_requirements: list[str] | None = None,
        stopping_condition: str = "All acceptance gates are verified and no blocking risk remains.",
        continuation_state: dict[str, Any] | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        """Persist a Mission beside a real conversation, preserving route identity."""
        conversation = self.get_conversation(conversation_id)
        timestamp = now or utc_now_iso()
        source_turn = (self.get_conversation(conversation_id, include_turns=True).get("turns") or [{}])[-1]
        source_id = str(source_turn.get("turnId") or conversation_id)
        provenance = Provenance(source_id=source_id, conversation_id=conversation_id, turn_id=str(source_turn.get("turnId") or ""), source_hash=hashlib.sha256(str(desired_outcome).encode()).hexdigest())
        mission = Mission(
            mission_id=f"mission_{uuid.uuid4().hex}", desired_outcome=str(desired_outcome).strip(),
            acceptance_gates=[MissionGate(f"gate_{uuid.uuid4().hex}", str(g).strip()) for g in acceptance_gates if str(g).strip()],
            boundaries=list(boundaries or []), exact_routes=list(exact_routes or conversation.get("metadata", {}).get("routeSnapshot", [])),
            authority=dict(authority or {}), evidence_requirements=list(evidence_requirements or []),
            stopping_condition=stopping_condition, continuation_state=dict(continuation_state or {}),
            workspace_id=str(conversation.get("workspaceId") or ""), provenance=provenance,
        )
        payload = mission.to_dict()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT INTO semantic_missions (mission_id, conversation_id, mission_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(conversation_id) DO UPDATE SET mission_json=excluded.mission_json, updated_at=excluded.updated_at", (mission.mission_id, conversation_id, _json(payload), timestamp, timestamp))
            self._append_event(connection, conversation_id, "semantic.mission.created", {"missionId": mission.mission_id, "gateCount": len(mission.acceptance_gates), "provenanceHash": payload["provenanceHash"]}, True, timestamp)
            connection.commit()
        return payload

    def ingest_semantic_turn(self, conversation_id: str, turn_id: str, *, semantic_type: str | None = None) -> dict[str, Any]:
        """Project one stored turn into the semantic workspace.

        Decision-like objects require an explicit ``semantic_type`` (or turn
        metadata ``semanticType``); free-form wording is retained as an
        observation and never silently promoted to a decision or approval.
        """
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM conversation_turns WHERE conversation_id = ? AND turn_id = ?", (conversation_id, turn_id)).fetchone()
            if not row:
                raise KeyError(turn_id)
            existing = connection.execute("SELECT object_json FROM semantic_workspace_objects WHERE conversation_id = ? AND turn_id = ? ORDER BY created_at, object_id LIMIT 1", (conversation_id, turn_id)).fetchone()
            if existing:
                return _decode(existing["object_json"], {})
            metadata = _decode(row["metadata_json"], {})
            requested = str(semantic_type or metadata.get("semanticType") or "").strip().lower()
            allowed = {"decision", "correction", "approval", "artifact_reference", "observation"}
            if requested not in allowed:
                requested = "artifact_reference" if re.search(r"\b[0-9a-fA-F]{64}\b", row["content"]) else "observation"
            provenance = Provenance(source_id=turn_id, conversation_id=conversation_id, turn_id=turn_id, source_hash=hashlib.sha256(row["content"].encode()).hexdigest())
            workspace = CollaborativeWorkspace(conversation_id)
            item = workspace.ingest_message(row["content"], conversation_id=conversation_id, turn_id=turn_id, role=row["role"], kind=requested, metadata=metadata)
            payload = item.to_dict()
            connection.execute("INSERT OR REPLACE INTO semantic_workspace_objects (object_id, conversation_id, turn_id, object_type, object_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (item.object_id, conversation_id, turn_id, item.object_type, _json(payload), item.created_at))
            self._append_event(connection, conversation_id, "semantic.workspace.objected", {"objectId": item.object_id, "objectType": item.object_type, "turnId": turn_id, "provenanceHash": item.to_dict()["objectHash"]}, True, item.created_at)
            connection.commit()
            return payload

    def continue_semantic_mission(self, conversation_id: str, checkpoint: dict[str, Any], *, source_turn_id: str = "") -> dict[str, Any]:
        """Update durable continuation state while preserving route and authority."""
        with self._connection() as connection:
            row = connection.execute("SELECT mission_json FROM semantic_missions WHERE conversation_id = ?", (conversation_id,)).fetchone()
            if not row:
                raise KeyError(conversation_id)
            payload = _decode(row["mission_json"], {})
        mission = self._mission_from_semantic_payload(payload)
        provenance = None
        if source_turn_id:
            provenance = Provenance(source_id=source_turn_id, conversation_id=conversation_id, turn_id=source_turn_id, source_hash=hashlib.sha256(_json(checkpoint).encode()).hexdigest())
        mission.continue_from(checkpoint, provenance=provenance)
        updated = mission.to_dict()
        timestamp = utc_now_iso()
        with self._connection() as connection:
            connection.execute("UPDATE semantic_missions SET mission_json = ?, updated_at = ? WHERE conversation_id = ?", (_json(updated), timestamp, conversation_id))
            self._append_event(connection, conversation_id, "semantic.mission.continued", {"missionId": updated.get("missionId"), "checkpointId": checkpoint.get("checkpointId") or checkpoint.get("proofId") or checkpoint.get("receiptId")}, True, timestamp)
            connection.commit()
        return updated

    def verify_semantic_mission_gate(self, conversation_id: str, gate_id: str, evidence: dict[str, Any], *, source_turn_id: str = "") -> dict[str, Any]:
        """Verify a gate from durable proof identity, never narrative completion text."""
        proof_id = str(evidence.get("proofId") or evidence.get("operationId") or "").strip()
        if not proof_id:
            raise ValueError("gate evidence must reference a persisted verified operation")
        from .verified_operations import VerifiedOperationStore
        operation = VerifiedOperationStore(self.root, conversation_id).inspect(proof_id)
        if operation.get("status") != "verified":
            raise ValueError("referenced operation is not durably verified")
        result = operation.get("result") if isinstance(operation.get("result"), dict) else {}
        verification = result.get("verification") if isinstance(result.get("verification"), dict) else {}
        if verification.get("verified") is not True:
            raise ValueError("referenced operation has no verified result")
        trusted_evidence = {**evidence, "verified": True, "operationReceiptPath": operation.get("operationId"), "resultHash": operation.get("resultHash")}
        with self._connection() as connection:
            row = connection.execute("SELECT mission_json FROM semantic_missions WHERE conversation_id = ?", (conversation_id,)).fetchone()
            if not row:
                raise KeyError(conversation_id)
            payload = _decode(row["mission_json"], {})
        mission = self._mission_from_semantic_payload(payload)
        provenance = Provenance(source_id=source_turn_id, conversation_id=conversation_id, turn_id=source_turn_id, source_hash=hashlib.sha256(_json(evidence).encode()).hexdigest()) if source_turn_id else None
        gate = next((item for item in mission.acceptance_gates if item.gate_id == gate_id), None)
        if gate is None or verification.get("claim") != gate.statement:
            raise ValueError("verified operation does not prove this acceptance gate's exact claim")
        mission.verify_gate(gate_id, trusted_evidence, source=provenance)
        updated = mission.to_dict()
        with self._connection() as connection:
            connection.execute("UPDATE semantic_missions SET mission_json = ?, updated_at = ? WHERE conversation_id = ?", (_json(updated), utc_now_iso(), conversation_id))
            connection.commit()
        return updated

    @staticmethod
    def _mission_from_semantic_payload(payload: dict[str, Any]) -> Mission:
        gates = []
        for raw in payload.get("acceptanceGates") or payload.get("acceptance_gates") or []:
            item = dict(raw)
            gate_id = item.get("gateId") or item.get("gate_id")
            gates.append(MissionGate(str(gate_id), str(item.get("statement") or ""), status=str(item.get("status") or "pending"), evidence=list(item.get("evidence") or []), verified_at=item.get("verified_at") or item.get("verifiedAt")))
        return Mission(mission_id=str(payload.get("missionId") or payload.get("mission_id")), desired_outcome=str(payload.get("desiredOutcome") or payload.get("desired_outcome") or ""), acceptance_gates=gates, boundaries=list(payload.get("boundaries") or []), exact_routes=list(payload.get("exactRoutes") or payload.get("exact_routes") or []), authority=dict(payload.get("authority") or {}), completed_work=list(payload.get("completedWork") or payload.get("completed_work") or []), unresolved_risks=list(payload.get("unresolvedRisks") or payload.get("unresolved_risks") or []), evidence_requirements=list(payload.get("evidenceRequirements") or payload.get("evidence_requirements") or []), stopping_condition=str(payload.get("stoppingCondition") or payload.get("stopping_condition") or ""), continuation_state=dict(payload.get("continuationState") or payload.get("continuation_state") or {}), status=str(payload.get("status") or "planned"), workspace_id=str(payload.get("workspaceId") or payload.get("workspace_id") or ""))

    @staticmethod
    def _semantic_projection(connection: sqlite3.Connection, conversation_id: str) -> dict[str, Any]:
        mission_row = connection.execute("SELECT mission_json FROM semantic_missions WHERE conversation_id = ?", (conversation_id,)).fetchone()
        object_rows = connection.execute("SELECT object_json FROM semantic_workspace_objects WHERE conversation_id = ? ORDER BY created_at, object_id LIMIT 100", (conversation_id,)).fetchall()
        return {"mission": _decode(mission_row["mission_json"], None) if mission_row else None, "objects": [_decode(row["object_json"], {}) for row in object_rows], "objectCount": len(object_rows)}

    def get_conversation_page(
        self,
        conversation_id: str,
        *,
        turn_limit: int = 80,
        before_turn_id: str = "",
    ) -> dict[str, Any]:
        """Return one newest-first query page, rendered in chronological order."""

        bounded_limit = max(1, min(int(turn_limit), 200))
        normalized_before = str(before_turn_id or "").strip()
        with self._connection() as connection:
            conversation_row = connection.execute(
                "SELECT * FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if not conversation_row:
                raise KeyError(conversation_id)
            parameters: list[Any] = [conversation_id]
            boundary = ""
            if normalized_before:
                before = connection.execute(
                    "SELECT conversation_id, created_at FROM "
                    "conversation_turns WHERE turn_id = ?",
                    (normalized_before,),
                ).fetchone()
                if (
                    not before
                    or before["conversation_id"] != conversation_id
                ):
                    raise ValueError(
                        "beforeTurnId is not part of this conversation"
                    )
                boundary = str(before["created_at"])
                parameters.extend(
                    [boundary, boundary, normalized_before]
                )
            where_boundary = (
                "AND (created_at < ? OR "
                "(created_at = ? AND turn_id < ?))"
                if boundary
                else ""
            )
            parameters.append(bounded_limit + 1)
            rows = connection.execute(
                "SELECT * FROM conversation_turns "
                "WHERE conversation_id = ? "
                f"{where_boundary} "
                "ORDER BY created_at DESC, turn_id DESC LIMIT ?",
                tuple(parameters),
            ).fetchall()
            total_turns = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM conversation_turns "
                    "WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()["count"]
            )
        has_earlier = len(rows) > bounded_limit
        selected = list(rows[:bounded_limit])
        selected.reverse()
        turns = [self._history_turn_from_row(row) for row in selected]
        conversation = self._conversation_from_row(conversation_row)
        conversation["turns"] = turns
        conversation["turnPage"] = {
            "schema": "neyvia.conversation-turn-page.v1",
            "returnedTurns": len(turns),
            "totalTurns": total_turns,
            "hasEarlierTurns": has_earlier,
            "beforeTurnId": (
                str(turns[0]["turnId"])
                if has_earlier and turns
                else ""
            ),
            "turnLimit": bounded_limit,
        }
        from .proofs_d_neyvia import conversation_page
        conversation_page(conversation, bounded_limit, (boundary, normalized_before) if boundary else None)
        return conversation

    def get_turn(self, turn_id: str, *, hydrate: bool = True) -> dict[str, Any]:
        """Return one turn; ``hydrate`` rebuilds a referenced compartment's session windows."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM conversation_turns WHERE turn_id = ?",
                (str(turn_id or "").strip(),),
            ).fetchone()
            if not row:
                raise KeyError(turn_id)
            turn = self._turn_from_row(row)
            result = turn["metadata"].get("runtimeResult")
            if hydrate and isinstance(result, dict) and turn_compartment.is_delta(result.get("compartment")):
                result["compartment"] = turn_compartment.hydrate(
                    result["compartment"],
                    self._compartment_loader(connection, turn["conversationId"]),
                )
        return turn

    @staticmethod
    def _compartment_loader(connection: sqlite3.Connection, conversation_id: str) -> turn_compartment.Loader:
        """Read another turn's stored compartment, only within the same conversation."""

        def load(turn_id: str) -> dict[str, Any] | None:
            row = connection.execute(
                "SELECT json_extract(metadata_json, '$.runtimeResult.compartment') AS compartment "
                "FROM conversation_turns WHERE turn_id = ? AND conversation_id = ?",
                (turn_id, conversation_id),
            ).fetchone()
            value = _decode(row["compartment"], None) if row else None
            return value if isinstance(value, dict) else None

        return load

    def compartment_for_storage(self, conversation_id: str, compartment: dict[str, Any]) -> dict[str, Any]:
        """Reduce a fresh runtime compartment to this turn's data plus a verified base reference."""
        history = compartment.get("history") if isinstance(compartment.get("history"), dict) else {}
        with self._connection() as connection:
            latest = connection.execute(
                "SELECT turn_id FROM conversation_turns WHERE conversation_id = ? AND role = 'assistant' "
                "ORDER BY created_at DESC, rowid DESC LIMIT 3",
                (conversation_id,),
            ).fetchall()
            candidates = [str(history.get("previousTurnId") or ""), *(row["turn_id"] for row in latest)]
            stored = turn_compartment.for_storage(
                compartment,
                candidates,
                self._compartment_loader(connection, conversation_id),
            )
        return stored if isinstance(stored, dict) else compartment

    def compact_turn_compartments(
        self,
        *,
        conversation_id: str | None = None,
        dry_run: bool = False,
        vacuum: bool = False,
    ) -> dict[str, Any]:
        """Convert full-window compartments stored before the reference format.

        A turn is converted only when its own messages plus its predecessor's
        window reproduce its stored windows exactly, and the converted row is
        read back through the normal read path before it is kept. Any other
        turn keeps its full window, which later turns may then reference.
        """
        report: dict[str, Any] = {
            "schema": "neyvia.turn-compartment-compaction.v1",
            "dryRun": dry_run,
            "examined": 0,
            "converted": 0,
            "keptFullWindow": 0,
            "alreadyCompact": 0,
            "metadataBytesBefore": 0,
            "metadataBytesAfter": 0,
        }
        with self._connection() as connection:
            if conversation_id:
                conversation_ids = [conversation_id]
            else:
                conversation_ids = [
                    row["conversation_id"]
                    for row in connection.execute("SELECT DISTINCT conversation_id FROM conversation_turns")
                ]
            for current_conversation in conversation_ids:
                load = self._compartment_loader(connection, current_conversation)
                turn_ids = [
                    row["turn_id"]
                    for row in connection.execute(
                        "SELECT turn_id FROM conversation_turns WHERE conversation_id = ? AND role = 'assistant' "
                        "ORDER BY created_at, rowid",
                        (current_conversation,),
                    )
                ]
                # Last window per runtime session: (turn id, messages, receipts).
                previous: dict[str, tuple[str, list[Any], list[Any]]] = {}
                connection.execute("BEGIN IMMEDIATE")
                for turn_id in turn_ids:
                    row = connection.execute(
                        "SELECT metadata_json FROM conversation_turns WHERE turn_id = ?",
                        (turn_id,),
                    ).fetchone()
                    metadata = _decode(row["metadata_json"], {})
                    result = metadata.get("runtimeResult") if isinstance(metadata, dict) else None
                    compartment = result.get("compartment") if isinstance(result, dict) else None
                    if not isinstance(compartment, dict):
                        continue
                    session_id = str(compartment.get("sessionId") or "")
                    before = len(row["metadata_json"].encode("utf-8"))
                    report["metadataBytesBefore"] += before
                    if turn_compartment.is_delta(compartment):
                        report["alreadyCompact"] += 1
                        report["metadataBytesAfter"] += before
                        messages, receipts, _ = turn_compartment.rebuild_window(compartment, load)
                        previous[session_id] = (turn_id, messages, receipts)
                        continue
                    if not turn_compartment.has_full_window(compartment):
                        report["metadataBytesAfter"] += before
                        continue
                    report["examined"] += 1
                    original_messages, original_receipts, _ = turn_compartment.rebuild_window(compartment, load)
                    base_id, base_messages, base_receipts = previous.get(session_id, ("", [], []))
                    converted = turn_compartment.legacy_as_delta(
                        compartment,
                        base_turn_id=base_id,
                        base_messages=base_messages,
                        base_receipts=base_receipts,
                    )
                    previous[session_id] = (turn_id, original_messages, original_receipts)
                    if converted is None:
                        report["keptFullWindow"] += 1
                        report["metadataBytesAfter"] += before
                        continue
                    converted["history"]["turnId"] = turn_id
                    metadata["runtimeResult"]["compartment"] = converted
                    encoded = _json(metadata)
                    connection.execute("SAVEPOINT compact_turn")
                    connection.execute(
                        "UPDATE conversation_turns SET metadata_json = ? WHERE turn_id = ?",
                        (encoded, turn_id),
                    )
                    # Read the row back exactly as get_turn would.
                    reread = load(turn_id)
                    rebuilt = turn_compartment.rebuild_window(reread, load) if reread else ([], [], False)
                    if (
                        not rebuilt[2]
                        or turn_compartment.window_digest(rebuilt[0], rebuilt[1])
                        != turn_compartment.window_digest(original_messages, original_receipts)
                    ):
                        connection.execute("ROLLBACK TO compact_turn")
                        connection.execute("RELEASE compact_turn")
                        report["keptFullWindow"] += 1
                        report["metadataBytesAfter"] += before
                        continue
                    connection.execute("RELEASE compact_turn")
                    report["converted"] += 1
                    report["metadataBytesAfter"] += len(encoded.encode("utf-8"))
                if dry_run:
                    connection.rollback()
                else:
                    connection.commit()
            if vacuum and not dry_run:
                connection.execute("VACUUM")
        return report

    @staticmethod
    def _turn_receipt_from_metadata(metadata: object) -> dict[str, Any] | None:
        """Resolve a durable runtime receipt without reading turn content."""

        if not isinstance(metadata, dict):
            return None
        direct = metadata.get("turnReceipt")
        if isinstance(direct, dict):
            return dict(direct)
        runtime_result = metadata.get("runtimeResult")
        if not isinstance(runtime_result, dict):
            return None
        direct_runtime = runtime_result.get("turnReceipt")
        if isinstance(direct_runtime, dict):
            return dict(direct_runtime)
        compartment = runtime_result.get("compartment")
        if not isinstance(compartment, dict):
            return None
        nested = compartment.get("turnReceipt")
        return dict(nested) if isinstance(nested, dict) else None

    def list_turn_receipts(
        self,
        conversation_id: str,
        *,
        limit: int = 80,
    ) -> list[dict[str, Any]]:
        """Return receipt-bearing turn references, never transcript content."""

        bounded_limit = max(1, min(int(limit), 200))
        with self._connection() as connection:
            conversation = connection.execute(
                "SELECT conversation_id FROM conversations "
                "WHERE conversation_id = ? AND deleted_at IS NULL",
                (str(conversation_id or "").strip(),),
            ).fetchone()
            if not conversation:
                raise KeyError(conversation_id)
            rows = connection.execute(
                "SELECT turn_id, conversation_id, metadata_json, created_at "
                "FROM conversation_turns WHERE conversation_id = ? "
                "ORDER BY created_at DESC, turn_id DESC LIMIT ?",
                (str(conversation_id or "").strip(), bounded_limit),
            ).fetchall()
        receipts: list[dict[str, Any]] = []
        for row in rows:
            receipt = self._turn_receipt_from_metadata(
                _decode(row["metadata_json"], {})
            )
            if not receipt:
                continue
            receipts.append(
                {
                    "turnId": row["turn_id"],
                    "conversationId": row["conversation_id"],
                    "createdAt": row["created_at"],
                    "receipt": receipt,
                }
            )
        from .proofs_d_neyvia import conversation_receipts
        conversation_receipts(self, conversation_id, receipts)
        return receipts

    def get_turn_receipt(
        self,
        conversation_id: str,
        turn_id: str,
    ) -> dict[str, Any]:
        """Resolve one receipt by its durable conversation and turn identity."""

        turn = self.get_turn(turn_id, hydrate=False)
        if str(turn.get("conversationId") or "") != str(
            conversation_id or ""
        ).strip():
            raise ValueError("turnId is not part of this conversation")
        receipt = self._turn_receipt_from_metadata(turn.get("metadata"))
        if not receipt:
            raise ValueError("the selected turn does not contain a runtime receipt")
        result = {
            "turnId": turn["turnId"],
            "conversationId": turn["conversationId"],
            "createdAt": turn["createdAt"],
            "receipt": receipt,
        }
        from .proofs_d_neyvia import conversation_receipts
        conversation_receipts(self, conversation_id, [result])
        return result

    def list_conversations(
        self,
        *,
        workspace_id: str | None = None,
        kind: str | None = None,
        parent_conversation_id: str | None = None,
        include_deleted: bool = False,
        include_archived: bool = False,
        archived_only: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if not include_deleted:
            clauses.append("deleted_at IS NULL")
        if archived_only:
            clauses.append("archived_at IS NOT NULL")
        elif not include_archived:
            clauses.append("archived_at IS NULL")
            # The composer creates a durable shell before the first send. Keep
            # it addressable by id, but do not fill the conversation roster
            # with shells that never became conversations. Structural work
            # items and question branches have their own durable purpose.
        if not archived_only:
            clauses.append("NOT (kind = 'chat' AND parent_conversation_id IS NULL AND title = 'New conversation' AND NOT EXISTS (SELECT 1 FROM conversation_turns t WHERE t.conversation_id = conversations.conversation_id))")
        if workspace_id is not None:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)
        if kind is not None:
            if kind not in CONVERSATION_KINDS:
                raise ValueError(f"unknown conversation kind: {kind}")
            clauses.append("kind = ?")
            params.append(kind)
        if parent_conversation_id is not None:
            clauses.append("parent_conversation_id = ?")
            params.append(parent_conversation_id)
        query = """SELECT conversations.*, (
            SELECT COALESCE(NULLIF(json_extract(t.metadata_json, '$.runtimeResult.runtime'), ''),
                            NULLIF(json_extract(t.metadata_json, '$.runtime'), ''))
            FROM conversation_turns t WHERE t.conversation_id = conversations.conversation_id
            AND COALESCE(NULLIF(json_extract(t.metadata_json, '$.runtimeResult.runtime'), ''),
                         NULLIF(json_extract(t.metadata_json, '$.runtime'), '')) IS NOT NULL
            ORDER BY t.created_at DESC, t.turn_id DESC LIMIT 1
        ) AS last_runtime FROM conversations"""
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY last_meaningful_activity_at DESC, conversation_id LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        with self._connection() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [self._conversation_from_row(row) for row in rows]

    def archive_inactive_conversations(
        self,
        *,
        active_conversation_ids: set[str] | list[str] | tuple[str, ...] = (),
        now: str | None = None,
        inactive_hours: int = 24,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Reversibly archive only old conversations with explicit completion.

        Call this at the normal conversation-list lifecycle and pass every
        conversation with a live runtime request. Ambiguous, waiting, failed,
        or unfinished work remains visible. Age alone never completes a task.
        """
        timestamp = now or utc_now_iso()
        try:
            instant = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("now must be an ISO-8601 timestamp") from exc
        if instant.tzinfo is None:
            raise ValueError("now must include a timezone")
        cutoff = (instant.astimezone(timezone.utc).timestamp() - max(1, int(inactive_hours)) * 3600)
        cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat().replace("+00:00", "Z")
        active = {str(item).strip() for item in active_conversation_ids if str(item).strip()}
        archived: list[str] = []
        protected: dict[str, str] = {}
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT * FROM conversations WHERE deleted_at IS NULL AND archived_at IS NULL AND last_meaningful_activity_at <= ? ORDER BY last_meaningful_activity_at LIMIT ?",
                (cutoff_iso, max(1, min(int(limit), 1000))),
            ).fetchall()
            for row in rows:
                conversation_id = str(row["conversation_id"])
                reason = ""
                if conversation_id in active:
                    reason = "runtime-active"
                else:
                    turns = connection.execute(
                        "SELECT role, metadata_json FROM conversation_turns WHERE conversation_id = ? ORDER BY created_at, rowid",
                        (conversation_id,),
                    ).fetchall()
                    goal_status = _latest_goal_loop_status(turns)
                    metadata = self._row_metadata(row)
                    last_turn_metadata = _decode(turns[-1]["metadata_json"], {}) if turns else {}
                    last_result = last_turn_metadata.get("runtimeResult") or {}
                    ordinary_reply_complete = (
                        bool(turns) and turns[-1]["role"] == "assistant"
                        and isinstance(last_result, dict) and last_result.get("status") == "completed"
                        and not last_result.get("pendingQuestions")
                        and not metadata.get("goalMode") and not goal_status
                    )
                    explicitly_complete = (
                        str(row["status"]).casefold() in {"completed", "done"}
                        or bool(row["settled_at"] and row["attention_state"] == "settled")
                        or goal_status == "completed"
                        or ordinary_reply_complete
                    )
                    if turns and turns[-1]["role"] == "user":
                        reason = "unanswered-request"
                    elif goal_status in {"active", "blocked", "paused"}:
                        reason = f"goal-{goal_status}"
                    elif metadata.get("goalMode") is True and goal_status != "completed":
                        reason = "goal-mode-without-completion"
                    elif not explicitly_complete:
                        reason = "not-explicitly-complete"
                if not reason and (row["attention_state"] == "needs-action" or self._blocking_attention_reasons(row)):
                    reason = "unresolved-attention"
                if not reason:
                    mission_row = connection.execute(
                        "SELECT mission_json FROM semantic_missions WHERE conversation_id = ?",
                        (conversation_id,),
                    ).fetchone()
                    if mission_row:
                        mission = _decode(mission_row["mission_json"], {})
                        if not isinstance(mission, dict) or mission.get("status") != "completed":
                            reason = "unfinished-mission"
                        elif any(str(risk.get("status", "open")).casefold() in {"open", "blocking", "unresolved"} for risk in (mission.get("unresolvedRisks") or mission.get("unresolved_risks") or []) if isinstance(risk, dict)):
                            reason = "unresolved-mission-risk"
                    if not reason:
                        node = connection.execute(
                            "SELECT status, lifecycle_stage FROM agent_nodes WHERE conversation_id = ? AND status NOT IN ('completed','failed','cancelled') LIMIT 1",
                            (conversation_id,),
                        ).fetchone()
                        if node:
                            reason = "unfinished-agent-work"
                if reason:
                    protected[conversation_id] = reason
                    continue
                connection.execute(
                    "UPDATE conversations SET archived_at = ?, revision = revision + 1 WHERE conversation_id = ? AND archived_at IS NULL",
                    (timestamp, conversation_id),
                )
                self._append_event(connection, conversation_id, "conversation.archived", {"reason": "completed-and-inactive", "inactiveHours": max(1, int(inactive_hours))}, False, timestamp)
                archived.append(conversation_id)
            connection.commit()
        return {
            "schema": "neyvia.conversation-auto-archive.v1",
            "archivedAt": timestamp,
            "cutoff": cutoff_iso,
            "archived": archived,
            "protected": protected,
        }

    def restore_conversation(self, conversation_id: str, *, now: str | None = None) -> dict[str, Any]:
        """Restore an automatically archived conversation to the normal roster."""
        timestamp = now or utc_now_iso()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE conversations SET archived_at = NULL, last_meaningful_activity_at = ?, revision = revision + 1 WHERE conversation_id = ? AND deleted_at IS NULL AND archived_at IS NOT NULL",
                (timestamp, conversation_id),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise KeyError(conversation_id)
            self._append_event(connection, conversation_id, "conversation.restored", {}, True, timestamp)
            connection.commit()
        return self.get_conversation(conversation_id)

    def attention_inbox(
        self,
        *,
        query: str = "",
        filter_state: str = "",
        project_id: str = "",
        limit: int = 80,
    ) -> dict[str, Any]:
        normalized_filter = str(filter_state or "").strip().casefold()
        if normalized_filter and normalized_filter not in ATTENTION_STATES:
            raise ValueError(f"unknown attention filter: {filter_state}")
        normalized_query = str(query or "").strip().casefold()
        normalized_project = str(project_id or "").strip()
        rows = self.list_conversations(limit=max(1, min(int(limit or 80), 500)))
        threads = []
        for row in rows:
            thread = self._attention_thread(row)
            if normalized_filter and thread["attentionState"] != normalized_filter:
                continue
            if normalized_project and thread["projectId"] != normalized_project:
                continue
            if normalized_query:
                haystack = " ".join(
                    str(thread.get(key) or "")
                    for key in (
                        "title",
                        "conversationId",
                        "missionId",
                        "projectId",
                        "workspaceId",
                    )
                ).casefold()
                if normalized_query not in haystack:
                    continue
            threads.append(thread)
        counts = {state: 0 for state in ATTENTION_STATES}
        for thread in threads:
            counts[thread["attentionState"]] += 1
        return {
            "schema": "neyvia.attention.inbox.v1",
            "generatedAt": utc_now_iso(),
            "threads": threads,
            "counts": counts,
        }

    def settle_conversation(
        self,
        conversation_id: str,
        *,
        settlement_reason: str,
        settled_by: str = "user",
        now: str | None = None,
    ) -> dict[str, Any]:
        reason = str(settlement_reason or "").strip()
        if not reason:
            raise ValueError("settlementReason is required")
        timestamp = now or utc_now_iso()
        with self._connection() as connection:
            row = self._required_conversation_row(connection, conversation_id)
            blocking = self._blocking_attention_reasons(row)
            if blocking:
                raise RuntimeError(
                    "Conversation cannot be settled while blocking attention is open: "
                    + ", ".join(blocking)
                )
            connection.execute(
                """
                UPDATE conversations
                SET attention_state = 'settled', lifecycle_state = 'settled',
                    settled_at = ?, settled_by = ?, settlement_reason = ?,
                    snoozed_until = NULL, snooze_reason = NULL,
                    next_wake_condition = NULL, revision = revision + 1,
                    updated_at = ?
                WHERE conversation_id = ?
                """,
                (
                    timestamp,
                    str(settled_by or "user").strip() or "user",
                    reason,
                    timestamp,
                    conversation_id,
                ),
            )
            self._append_event(
                connection,
                conversation_id,
                "attention.settled",
                {"settlementReason": reason, "settledBy": settled_by or "user"},
                True,
                timestamp,
            )
            connection.commit()
        return self.get_conversation(conversation_id)

    def reopen_conversation(
        self,
        conversation_id: str,
        *,
        reason: str = "",
        now: str | None = None,
    ) -> dict[str, Any]:
        timestamp = now or utc_now_iso()
        with self._connection() as connection:
            row = self._required_conversation_row(connection, conversation_id)
            state = self._derived_attention_state(row, ignore_settlement=True)
            connection.execute(
                """
                UPDATE conversations
                SET attention_state = ?, lifecycle_state = 'active',
                    settled_at = NULL, settled_by = NULL, settlement_reason = NULL,
                    revision = revision + 1, updated_at = ?
                WHERE conversation_id = ?
                """,
                (state, timestamp, conversation_id),
            )
            self._append_event(
                connection,
                conversation_id,
                "attention.reopened",
                {"reason": str(reason or "").strip()},
                True,
                timestamp,
            )
            connection.commit()
        return self.get_conversation(conversation_id)

    def snooze_conversation(
        self,
        conversation_id: str,
        *,
        snoozed_until: str = "",
        until_event: str = "",
        snooze_reason: str = "",
        now: str | None = None,
    ) -> dict[str, Any]:
        wake_at = str(snoozed_until or "").strip()
        wake_event = str(until_event or "").strip()
        if not wake_at and not wake_event:
            raise ValueError("snoozedUntil or untilEvent is required")
        if wake_at:
            try:
                datetime.fromisoformat(wake_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("snoozedUntil must be an ISO-8601 timestamp") from exc
        timestamp = now or utc_now_iso()
        with self._connection() as connection:
            row = self._required_conversation_row(connection, conversation_id)
            if row["settled_at"]:
                raise RuntimeError("A settled conversation must be reopened before snoozing")
            blocking = self._blocking_attention_reasons(row)
            if blocking:
                raise RuntimeError(
                    "Blocking attention cannot be snoozed: " + ", ".join(blocking)
                )
            connection.execute(
                """
                UPDATE conversations
                SET attention_state = 'quiet', lifecycle_state = 'snoozed',
                    snoozed_until = ?, snooze_reason = ?,
                    next_wake_condition = ?, revision = revision + 1,
                    updated_at = ?
                WHERE conversation_id = ?
                """,
                (
                    wake_at or None,
                    str(snooze_reason or "").strip() or None,
                    wake_event or None,
                    timestamp,
                    conversation_id,
                ),
            )
            self._append_event(
                connection,
                conversation_id,
                "attention.snoozed",
                {"snoozedUntil": wake_at or None, "untilEvent": wake_event or None},
                True,
                timestamp,
            )
            connection.commit()
        return self.get_conversation(conversation_id)

    def wake_conversation(
        self,
        conversation_id: str,
        *,
        now: str | None = None,
    ) -> dict[str, Any]:
        timestamp = now or utc_now_iso()
        with self._connection() as connection:
            row = self._required_conversation_row(connection, conversation_id)
            state = self._derived_attention_state(row, ignore_snooze=True)
            connection.execute(
                """
                UPDATE conversations
                SET attention_state = ?, lifecycle_state = 'active',
                    snoozed_until = NULL, snooze_reason = NULL,
                    next_wake_condition = NULL, revision = revision + 1,
                    updated_at = ?
                WHERE conversation_id = ?
                """,
                (state, timestamp, conversation_id),
            )
            self._append_event(
                connection,
                conversation_id,
                "attention.woken",
                {},
                True,
                timestamp,
            )
            connection.commit()
        return self.get_conversation(conversation_id)

    def set_conversation_project(
        self,
        conversation_id: str,
        *,
        project_id: str,
        now: str | None = None,
    ) -> dict[str, Any]:
        project = str(project_id or "").strip()
        if not project:
            raise ValueError("projectId is required")
        timestamp = now or utc_now_iso()
        with self._connection() as connection:
            self._required_conversation_row(connection, conversation_id)
            connection.execute(
                """
                UPDATE conversations
                SET project_id = ?, revision = revision + 1, updated_at = ?
                WHERE conversation_id = ?
                """,
                (project, timestamp, conversation_id),
            )
            self._append_event(
                connection,
                conversation_id,
                "attention.project-linked",
                {"projectId": project},
                True,
                timestamp,
            )
            connection.commit()
        return self.get_conversation(conversation_id)

    def append_turn(
        self,
        conversation_id: str,
        *,
        role: str,
        content: str,
        detail: str = "",
        source: str = "",
        turn_kind: str = "dialogue",
        metadata: dict[str, Any] | None = None,
        meaningful: bool = True,
        expected_revision: int | None = None,
        turn_id: str | None = None,
        idempotent: bool = False,
        now: str | None = None,
    ) -> dict[str, Any]:
        text = str(content or "").strip()
        if not text:
            raise ValueError("conversation turn content is required")
        timestamp = now or utc_now_iso()
        turn_id = turn_id or f"turn_{uuid.uuid4().hex}"
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM conversations WHERE conversation_id = ?", (conversation_id,)).fetchone()
            if not row or row["deleted_at"]:
                connection.rollback()
                raise KeyError(conversation_id)
            if idempotent and turn_id:
                existing = connection.execute(
                    "SELECT * FROM conversation_turns WHERE turn_id = ?",
                    (turn_id,),
                ).fetchone()
                if existing:
                    existing_turn = self._turn_from_row(existing)
                    expected_payload = {
                        "conversationId": conversation_id,
                        "role": str(role or ""),
                        "content": text,
                        "detail": str(detail or ""),
                        "source": str(source or ""),
                        "turnKind": str(turn_kind or "dialogue"),
                    }
                    actual_payload = {
                        key: existing_turn.get(key)
                        for key in expected_payload
                    }
                    from .proofs_d_neyvia import conversation_replay
                    conversation_replay(turn_id, expected_payload, actual_payload)
                    connection.rollback()
                    return existing_turn
            from .proofs_d_neyvia import conversation_revision
            conversation_revision(row["revision"], expected_revision)
            connection.execute(
                """
                INSERT INTO conversation_turns (
                    turn_id, conversation_id, role, content, detail, source, turn_kind,
                    metadata_json, meaningful, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (turn_id, conversation_id, role, text, str(detail or ""), str(source or ""), str(turn_kind or "dialogue"), _json(metadata or {}), int(meaningful), timestamp),
            )
            next_title = row["title"]
            next_generated = row["generated_title"]
            if row["title_mode"] in {"suggest", "automatic"} and not row["title_locked"] and row["title"] == "New conversation":
                next_generated = generated_title(text)
                if row["title_mode"] == "automatic":
                    next_title = next_generated
            next_fingerprint = _fingerprint(row["topic_fingerprint"], row["title"], text, metadata or {})
            updated_at = timestamp if meaningful else row["updated_at"]
            meaningful_at = timestamp if meaningful else row["last_meaningful_activity_at"]
            connection.execute(
                """
                UPDATE conversations SET title = ?, generated_title = ?, topic_fingerprint = ?,
                    revision = revision + 1, updated_at = ?, last_meaningful_activity_at = ?
                WHERE conversation_id = ?
                """,
                (next_title, next_generated, next_fingerprint, updated_at, meaningful_at, conversation_id),
            )
            self._append_event(connection, conversation_id, "turn.appended", {"turnId": turn_id, "role": role, "turnKind": turn_kind}, meaningful, timestamp)
            self._index_row(connection, conversation_id, turn_id, "turn", next_title, f"{text}\n{detail}".strip(), f"{role} {source} {turn_kind}")
            if next_title != row["title"]:
                self._replace_conversation_index(connection, conversation_id, next_title, row["kind"], row["branch_kind"])
            from .proofs_d_neyvia import conversation_append
            conversation_append(connection, row, turn_id, role, text, timestamp, meaningful, next_title, next_generated)
            connection.commit()
            inserted = connection.execute("SELECT * FROM conversation_turns WHERE turn_id = ?", (turn_id,)).fetchone()
        turn = self._turn_from_row(inserted)
        # Every durable turn receives a semantic projection.  Classification
        # remains conservative: only explicit turn metadata can create a
        # decision/correction/approval object.
        self.ingest_semantic_turn(conversation_id, turn_id)
        checkpoint = (metadata or {}).get("missionCheckpoint")
        if isinstance(checkpoint, dict) and any(checkpoint.get(key) for key in ("checkpointId", "proofId", "receiptId")):
            with self._connection() as connection:
                has_mission = connection.execute("SELECT 1 FROM semantic_missions WHERE conversation_id = ?", (conversation_id,)).fetchone()
            if has_mission:
                # A checkpoint is reported continuation state, never proof or authority.
                self.continue_semantic_mission(conversation_id, {**checkpoint, "verified": False}, source_turn_id=turn_id)
        return turn

    def set_title(self, conversation_id: str, title: str, *, lock: bool = True, now: str | None = None) -> dict[str, Any]:
        visible = generated_title(title)
        if visible == "New conversation":
            raise ValueError("title is required")
        timestamp = now or utc_now_iso()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE conversations SET title = ?, title_locked = ?, revision = revision + 1,
                    updated_at = ? WHERE conversation_id = ? AND deleted_at IS NULL
                """,
                (visible, int(lock), timestamp, conversation_id),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise KeyError(conversation_id)
            row = connection.execute("SELECT kind, branch_kind FROM conversations WHERE conversation_id = ?", (conversation_id,)).fetchone()
            self._replace_conversation_index(connection, conversation_id, visible, row["kind"], row["branch_kind"])
            self._append_event(connection, conversation_id, "title.updated", {"locked": bool(lock)}, True, timestamp)
            connection.commit()
        return self.get_conversation(conversation_id)

    def delete_conversation(self, conversation_id: str, *, now: str | None = None) -> dict[str, Any]:
        timestamp = now or utc_now_iso()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE conversations SET status = 'deleted', deleted_at = ?, updated_at = ?, revision = revision + 1 WHERE conversation_id = ? AND deleted_at IS NULL",
                (timestamp, timestamp, conversation_id),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise KeyError(conversation_id)
            connection.execute("UPDATE context_atoms SET deleted_at = ?, updated_at = ? WHERE conversation_id = ? AND deleted_at IS NULL", (timestamp, timestamp, conversation_id))
            if self.fts_available:
                connection.execute("DELETE FROM conversation_search_fts WHERE conversation_id = ?", (conversation_id,))
            self._append_event(connection, conversation_id, "conversation.deleted", {}, True, timestamp)
            from .proofs_d_neyvia import conversation_delete
            conversation_delete(connection, conversation_id, timestamp, self.fts_available)
            connection.commit()
        return {"conversationId": conversation_id, "deleted": True, "deletedAt": timestamp}

    def delete_conversations(self, conversations: list[dict[str, Any]], *, now: str | None = None) -> dict[str, Any]:
        """Soft-delete an explicit, revision-bound set of conversations atomically.

        Every row must be snapshotted by its durable id and current revision. This
        prevents stale UI selections from deleting a conversation that changed
        after the user reviewed the list.
        """
        if not isinstance(conversations, list) or not conversations or len(conversations) > 500:
            raise ValueError("conversations must contain between 1 and 500 snapshot entries")
        snapshots: dict[str, int] = {}
        for item in conversations:
            if not isinstance(item, dict):
                raise ValueError("each conversation snapshot must be an object")
            conversation_id = str(item.get("conversationId") or "").strip()
            if not conversation_id:
                raise ValueError("conversationId is required for every snapshot")
            if conversation_id in snapshots:
                raise ValueError(f"duplicate conversationId: {conversation_id}")
            if item.get("expectedRevision") is None:
                raise ValueError(f"expectedRevision is required for {conversation_id}")
            try:
                revision = int(item["expectedRevision"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"expectedRevision must be an integer for {conversation_id}") from exc
            if revision < 1:
                raise ValueError(f"expectedRevision must be positive for {conversation_id}")
            snapshots[conversation_id] = revision

        timestamp = now or utc_now_iso()
        receipt_id = f"delete_{uuid.uuid4().hex}"
        ids = list(snapshots)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            placeholders = ",".join("?" for _ in ids)
            rows = connection.execute(
                f"SELECT conversation_id, revision, deleted_at FROM conversations WHERE conversation_id IN ({placeholders})",
                ids,
            ).fetchall()
            current = {str(row["conversation_id"]): row for row in rows}
            mismatches = [
                conversation_id for conversation_id, revision in snapshots.items()
                if conversation_id not in current
                or current[conversation_id]["deleted_at"] is not None
                or int(current[conversation_id]["revision"]) != revision
            ]
            if mismatches:
                connection.rollback()
                raise RuntimeError(f"conversation snapshot conflict; no rows deleted: {', '.join(mismatches)}")

            for conversation_id in ids:
                connection.execute(
                    "UPDATE conversations SET status = 'deleted', deleted_at = ?, updated_at = ?, revision = revision + 1 WHERE conversation_id = ? AND deleted_at IS NULL",
                    (timestamp, timestamp, conversation_id),
                )
                connection.execute(
                    "UPDATE context_atoms SET deleted_at = ?, updated_at = ? WHERE conversation_id = ? AND deleted_at IS NULL",
                    (timestamp, timestamp, conversation_id),
                )
                if self.fts_available:
                    connection.execute("DELETE FROM conversation_search_fts WHERE conversation_id = ?", (conversation_id,))
                self._append_event(connection, conversation_id, "conversation.deleted", {"receiptId": receipt_id, "bulk": True}, True, timestamp)
            connection.commit()
        return {
            "receiptId": receipt_id,
            "deleted": True,
            "deletedAt": timestamp,
            "count": len(ids),
            "conversations": [{"conversationId": conversation_id, "deleted": True} for conversation_id in ids],
        }

    def action_allowed(self, conversation_id: str, action: str) -> dict[str, Any]:
        conversation = self.get_conversation(conversation_id)
        policy = conversation["capabilityPolicy"]
        normalized = str(action or "").strip().lower()
        if not policy.get("readOnly"):
            return {"allowed": True, "reason": "standard_conversation", "action": normalized}
        prefixes = tuple(str(value).lower() for value in policy.get("allowedActionPrefixes") or QUESTION_BRANCH_ALLOWED_PREFIXES)
        allowed = bool(normalized) and any(normalized.startswith(prefix) for prefix in prefixes)
        result = {
            "allowed": allowed,
            "reason": "question_branch_read_only" if not allowed else "read_only_action_allowed",
            "action": normalized,
            "conversationId": conversation_id,
            "policy": "ask",
        }
        from .proofs_d_neyvia import conversation_action
        conversation_action(conversation, normalized, result)
        return result

    def put_context_atom(
        self,
        conversation_id: str,
        *,
        kind: str,
        content: str,
        evidence_turn_id: str | None = None,
        confidence: float = 1.0,
        freshness_expires_at: str | None = None,
        supersedes_atom_id: str | None = None,
        permission_scope: dict[str, Any] | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        self.get_conversation(conversation_id)
        text = str(content or "").strip()
        if not text:
            raise ValueError("context atom content is required")
        timestamp = now or utc_now_iso()
        atom_id = f"atom_{uuid.uuid4().hex}"
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO context_atoms (
                    atom_id, conversation_id, kind, content, evidence_turn_id, confidence,
                    freshness_expires_at, supersedes_atom_id, permission_scope_json,
                    topic_fingerprint, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (atom_id, conversation_id, str(kind or "note"), text, evidence_turn_id, max(0.0, min(float(confidence), 1.0)), freshness_expires_at, supersedes_atom_id, _json(permission_scope or {}), _fingerprint(kind, text), timestamp, timestamp),
            )
            if supersedes_atom_id:
                connection.execute("UPDATE context_atoms SET updated_at = ? WHERE atom_id = ?", (timestamp, supersedes_atom_id))
            title = connection.execute("SELECT title FROM conversations WHERE conversation_id = ?", (conversation_id,)).fetchone()["title"]
            self._index_row(connection, conversation_id, atom_id, "context_atom", title, text, str(kind or "note"))
            self._append_event(connection, conversation_id, "context.atom.created", {"atomId": atom_id, "kind": kind}, False, timestamp)
            connection.commit()
            row = connection.execute("SELECT * FROM context_atoms WHERE atom_id = ?", (atom_id,)).fetchone()
        return self._context_atom_from_row(row)

    def list_conversation_context_atoms(
        self,
        conversation_id: str,
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        """Return recent, live context atoms owned by one conversation."""

        self.get_conversation(conversation_id)
        bounded_limit = max(1, min(int(limit), 32))
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM context_atoms
                WHERE conversation_id = ? AND deleted_at IS NULL
                ORDER BY updated_at DESC, atom_id DESC
                LIMIT ?
                """,
                (conversation_id, bounded_limit),
            ).fetchall()
        return [self._context_atom_from_row(row) for row in rows]

    def retrieve_context(
        self,
        query: str,
        *,
        workspace_id: str | None = None,
        exclude_conversation_id: str | None = None,
        limit: int = 8,
        now: str | None = None,
    ) -> dict[str, Any]:
        timestamp = now or utc_now_iso()
        query_tokens = set(_tokens(query))
        clauses = ["a.deleted_at IS NULL", "c.deleted_at IS NULL", "(a.freshness_expires_at IS NULL OR a.freshness_expires_at > ?)"]
        params: list[Any] = [timestamp]
        if workspace_id is not None:
            clauses.append("c.workspace_id = ?")
            params.append(workspace_id)
        if exclude_conversation_id:
            clauses.append("a.conversation_id != ?")
            params.append(exclude_conversation_id)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT a.*, c.title AS conversation_title, c.kind AS conversation_kind
                FROM context_atoms a JOIN conversations c ON c.conversation_id = a.conversation_id
                WHERE {' AND '.join(clauses)} ORDER BY a.updated_at DESC LIMIT 500
                """,
                tuple(params),
            ).fetchall()
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            atom_tokens = set(_tokens(f"{row['kind']} {row['content']} {row['conversation_title']}"))
            overlap = len(query_tokens & atom_tokens)
            score = overlap * 10.0 + float(row["confidence"] or 0) + (0.25 if row["evidence_turn_id"] else 0)
            if not query_tokens or overlap:
                scored.append((score, row))
        scored.sort(key=lambda item: (item[0], item[1]["updated_at"]), reverse=True)
        items = []
        for score, row in scored[: max(1, min(int(limit), 50))]:
            item = self._context_atom_from_row(row)
            item.update({"score": score, "conversationTitle": row["conversation_title"], "conversationKind": row["conversation_kind"]})
            items.append(item)
        return {
            "schema": "neyvia.context-atlas.retrieval.v1",
            "query": str(query or ""),
            "items": items,
            "lease": {"maxTurns": 6, "maxItems": len(items), "expiresAfterUse": True},
            "provenanceRequired": True,
        }

    def search(
        self,
        query: str,
        *,
        workspace_id: str | None = None,
        kind: str | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        query_text = str(query or "").strip()
        if not query_text:
            return {"schema": "neyvia.conversation-search.v1", "query": "", "mode": "recency", "results": self.list_conversations(workspace_id=workspace_id, kind=kind, limit=limit)}
        conversations = {row["conversationId"]: row for row in self.list_conversations(workspace_id=workspace_id, kind=kind, limit=1000)}
        hits: dict[str, dict[str, Any]] = {}
        tokens = _tokens(query_text)
        with self._connection() as connection:
            if self.fts_available and tokens:
                fts_query = " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)
                try:
                    rows = connection.execute(
                        """
                        SELECT conversation_id, source_id, source_kind, title,
                               snippet(conversation_search_fts, 4, '<mark>', '</mark>', '…', 18) AS excerpt,
                               bm25(conversation_search_fts) AS rank
                        FROM conversation_search_fts WHERE conversation_search_fts MATCH ?
                        ORDER BY rank LIMIT 300
                        """,
                        (fts_query,),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
                for row in rows:
                    conversation = conversations.get(row["conversation_id"])
                    if not conversation:
                        continue
                    score = 100.0 + max(0.0, -float(row["rank"] or 0))
                    current = hits.get(row["conversation_id"])
                    if not current or score > current["score"]:
                        hits[row["conversation_id"]] = {
                            **conversation,
                            "score": score,
                            "matchedSourceId": row["source_id"],
                            "matchedSourceKind": row["source_kind"],
                            "excerpt": row["excerpt"] or row["title"],
                            "whyMatched": f"Matched {row['source_kind']} content",
                        }
        query_set = set(tokens)
        for conversation in conversations.values():
            title_tokens = set(_tokens(conversation["title"]))
            overlap = len(query_set & title_tokens)
            if not query_set or not query_set.issubset(title_tokens):
                continue
            exact_title = query_text.casefold() == conversation["title"].casefold()
            title_phrase = query_text.casefold() in conversation["title"].casefold()
            score = (300.0 if exact_title else 200.0 if title_phrase else 120.0) + overlap * 5.0
            current = hits.get(conversation["conversationId"])
            if not current or score > current["score"]:
                hits[conversation["conversationId"]] = {
                    **conversation,
                    "score": score,
                    "matchedSourceId": conversation["conversationId"],
                    "matchedSourceKind": "title",
                    "excerpt": conversation["title"],
                    "whyMatched": "Matched conversation title or topic fingerprint",
                }
        results = sorted(hits.values(), key=lambda item: (item["score"], item["lastMeaningfulActivityAt"]), reverse=True)[: max(1, min(int(limit), 100))]
        return {
            "schema": "neyvia.conversation-search.v1",
            "query": query_text,
            "mode": "fts5+topic_fingerprint" if self.fts_available else "topic_fingerprint",
            "results": results,
            "facets": {"kinds": sorted({item["kind"] for item in results}), "count": len(results)},
        }

    def create_concurrency_plan(
        self,
        conversation_id: str,
        *,
        tasks: list[dict[str, Any]],
        max_parallel: int = 4,
        preset: dict[str, Any] | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        conversation = self.get_conversation(conversation_id)
        if conversation["kind"] != "orchestration":
            raise ValueError("concurrency plans require an orchestration conversation")
        if not tasks:
            raise ValueError("at least one orchestration task is required")
        timestamp = now or utc_now_iso()
        bounded_parallel = max(1, min(int(max_parallel), 16))
        route_snapshot = _explicit_route_snapshot(conversation)
        explicit_roles = list(route_snapshot)
        normalized: dict[str, dict[str, Any]] = {}
        for index, raw in enumerate(tasks):
            node_id = str(raw.get("id") or raw.get("nodeId") or f"agent_{uuid.uuid4().hex}").strip()
            if not node_id or node_id in normalized:
                raise ValueError("agent node ids must be non-empty and unique")
            raw_contract = raw.get("teamContract") or raw.get("team_contract")
            role = str(
                raw.get("role")
                or raw.get("teamRole")
                or raw.get("targetRole")
                or (raw_contract.get("role") if isinstance(raw_contract, dict) else "")
                or (explicit_roles[index] if index < len(explicit_roles) else "")
            ).strip().lower()
            requested_route = raw.get("routeSelection") or raw.get("route")
            snapshotted_route = route_snapshot.get(role) if role else None
            if snapshotted_route and isinstance(requested_route, dict):
                conflicts = _route_conflicts(snapshotted_route, requested_route)
                if conflicts:
                    raise ValueError(
                        f"route selection for {role or node_id} conflicts with immutable route snapshot: "
                        + ", ".join(conflicts)
                    )
            route_source = snapshotted_route or requested_route
            route_selection = dict(route_source) if isinstance(route_source, dict) else {}
            normalized_task = {
                "nodeId": node_id,
                "parentNodeId": str(raw.get("parentNodeId") or "").strip() or None,
                "title": generated_title(raw.get("title") or raw.get("objective") or f"Agent {index + 1}"),
                "objective": str(raw.get("objective") or raw.get("title") or "").strip(),
                "dependencies": [str(value) for value in raw.get("dependencies") or []],
                "assignedScope": sorted(set(str(value).strip() for value in raw.get("assignedScope") or [] if str(value).strip())),
                "capabilities": sorted(set(str(value).strip() for value in raw.get("capabilities") or [] if str(value).strip())),
                "role": role,
                "runtime": str(route_selection.get("runtimeId") or raw.get("runtime") or "").strip().lower(),
                "routeSelection": route_selection,
                "routeSource": "conversation.routeSnapshot" if snapshotted_route else ("requested" if route_selection else "unresolved"),
                "estimatedSeconds": max(0, int(raw.get("estimatedSeconds") or 0)),
            }
            normalized_task["teamContract"] = _team_contract(
                raw_contract,
                normalized_task,
            )
            normalized_task["teamContract"]["role"] = role
            if isinstance(preset, dict):
                normalized_task["teamContract"]["preset"] = dict(preset)
            if route_selection:
                normalized_task["teamContract"]["routeSelection"] = route_selection
            normalized[node_id] = normalized_task
        for node in normalized.values():
            unknown = [dependency for dependency in node["dependencies"] if dependency not in normalized]
            if unknown:
                raise ValueError(f"unknown dependencies for {node['nodeId']}: {', '.join(unknown)}")
            if node["nodeId"] in node["dependencies"]:
                raise ValueError(f"agent node cannot depend on itself: {node['nodeId']}")
        pending = dict(normalized)
        scheduled: set[str] = set()
        waves: list[list[str]] = []
        while pending:
            candidates = [node for node in pending.values() if set(node["dependencies"]).issubset(scheduled)]
            if not candidates:
                raise ValueError("orchestration dependency graph contains a cycle")
            selected: list[dict[str, Any]] = []
            occupied_scope: set[str] = set()
            for node in candidates:
                scope = set(node["assignedScope"])
                if selected and scope & occupied_scope:
                    continue
                selected.append(node)
                occupied_scope.update(scope)
                if len(selected) >= bounded_parallel:
                    break
            if not selected:
                selected = [candidates[0]]
            wave_ids = [node["nodeId"] for node in selected]
            waves.append(wave_ids)
            for node_id in wave_ids:
                scheduled.add(node_id)
                pending.pop(node_id)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for wave_index, wave in enumerate(waves):
                for node_id in wave:
                    node = normalized[node_id]
                    connection.execute(
                        """
                        INSERT INTO agent_nodes (
                            node_id, conversation_id, parent_node_id, title, objective, status,
                            lifecycle_stage, runtime, assigned_scope_json, capabilities_json,
                            team_contract_json, progress_json, result_summary_json, wave,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, 'queued', 'requested', ?, ?, ?, ?, ?, '{}', ?, ?, ?)
                        ON CONFLICT(node_id) DO UPDATE SET
                            title = excluded.title, objective = excluded.objective,
                            runtime = excluded.runtime, assigned_scope_json = excluded.assigned_scope_json,
                            capabilities_json = excluded.capabilities_json,
                            team_contract_json = excluded.team_contract_json,
                            wave = excluded.wave,
                            revision = agent_nodes.revision + 1, updated_at = excluded.updated_at
                        """,
                        (
                            node_id,
                            conversation_id,
                            node["parentNodeId"],
                            node["title"],
                            node["objective"],
                            node["runtime"],
                            _json(node["assignedScope"]),
                            _json(node["capabilities"]),
                            _json(node["teamContract"]),
                            _json(
                                {
                                    "current": 0,
                                    "total": 0,
                                    "estimatedSeconds": node["estimatedSeconds"],
                                }
                            ),
                            wave_index,
                            timestamp,
                            timestamp,
                        ),
                    )
                    for dependency in node["dependencies"]:
                        connection.execute(
                            "INSERT OR REPLACE INTO agent_dependencies VALUES (?, ?, ?, 'finish_to_start', ?)",
                            (conversation_id, dependency, node_id, timestamp),
                        )
            self._append_event(
                connection,
                conversation_id,
                "orchestration.plan.created",
                {"waves": waves, "maxParallel": bounded_parallel, "preset": preset},
                True,
                timestamp,
            )
            connection.execute(
                """
                INSERT INTO orchestration_plans (
                    conversation_id, plan_id, schema_name, approved_plan_hash,
                    parent_task_id, plan_json, governor_json, preset_json, created_at, updated_at
                ) VALUES (?, ?, 'neyvia.orchestration.plan.v1', '', '', ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    plan_id = excluded.plan_id,
                    schema_name = excluded.schema_name,
                    plan_json = excluded.plan_json,
                    governor_json = excluded.governor_json,
                    preset_json = excluded.preset_json,
                    updated_at = excluded.updated_at
                """,
                (
                    conversation_id,
                    f"plan_{conversation_id}",
                    _json({"waves": waves, "maxParallel": bounded_parallel, "preset": preset}),
                    _json({
                        "maxParallel": bounded_parallel,
                        "waveCount": len(waves),
                        "strategy": "dependency_and_scope_aware",
                        "reason": "Independent scopes run together; dependencies and overlapping scopes stay ordered.",
                    }),
                    _json(preset or {}),
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute("UPDATE conversations SET updated_at = ?, last_meaningful_activity_at = ?, revision = revision + 1 WHERE conversation_id = ?", (timestamp, timestamp, conversation_id))
            connection.commit()
        graph = self.agent_graph(conversation_id)
        graph["governor"] = {
            "maxParallel": bounded_parallel,
            "waveCount": len(waves),
            "strategy": "dependency_and_scope_aware",
            "reason": "Independent scopes run together; dependencies and overlapping scopes stay ordered.",
        }
        if isinstance(preset, dict):
            graph["preset"] = dict(preset)
        return graph

    def create_lead_workers_plan(
        self,
        conversation_id: str,
        *,
        objective: str = "Complete the bounded orchestration objective.",
        worker_count: int = 2,
        sequential_integration: bool = False,
        now: str | None = None,
    ) -> dict[str, Any]:
        """Persist the reusable Lead + workers plan without running it."""

        specification = build_lead_workers_preset(
            conversation_id,
            objective=objective,
            worker_count=worker_count,
            sequential_integration=sequential_integration,
        )
        return self.create_concurrency_plan(
            conversation_id,
            tasks=list(specification["tasks"]),
            max_parallel=int(specification["maxParallel"]),
            preset=dict(specification["preset"]),
            now=now,
        )

    def create_dynamic_child_plan(
        self,
        conversation_id: str,
        *,
        plan: dict[str, Any],
        run_id: str,
        approval_receipt: dict[str, Any],
        approved_plan_hash: str | None = None,
        parent_task_id: str | None = None,
        approved: bool | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        """Atomically persist a validated lead plan and its named child sessions.

        This is deliberately separate from the reusable lead-workers preset:
        children are supplied by the lead as typed work, then become durable
        conversations and graph nodes in one transaction. No runtime is
        started here.
        """

        validate_typed_lead_plan(plan)
        if not isinstance(plan, dict):
            raise ValueError("typed lead plan must be an object")
        conversation = self.get_conversation(conversation_id)
        if conversation["kind"] != "orchestration":
            raise ValueError("dynamic child plans require an orchestration conversation")
        run = self.get_dynamic_plan_run(run_id)
        if run["conversationId"] != conversation_id or run["status"] not in {"approved", "spawned"}:
            raise ValueError("dynamic plan must be approved by Neyvia before child creation")
        approval_record = approval_receipt if isinstance(approval_receipt, dict) else {}
        if approval_record != (run.get("approvalReceipt") or {}):
            raise ValueError("the supplied approval receipt is not the persisted Neyvia receipt")

        expected_hash = typed_plan_hash(plan)
        supplied_hash = str(
            approved_plan_hash
            or plan.get("approvedPlanHash")
            or plan.get("planHash")
            or approval_record.get("planHash")
            or ""
        ).strip().lower()
        if supplied_hash != expected_hash or expected_hash != run["planHash"]:
            raise ValueError("approved plan hash does not match the typed plan")
        approved_hash_value = expected_hash

        raw_children = plan.get("children") or plan.get("tasks")
        if not isinstance(raw_children, list) or not 6 <= len(raw_children) <= 10:
            raise ValueError("validated typed lead plans must contain between 6 and 10 children")
        governor = plan.get("governor")
        if not isinstance(governor, dict):
            raise ValueError("typed lead plan must include a governor object")
        try:
            max_parallel = int(governor.get("maxParallel"))
        except (TypeError, ValueError) as exc:
            raise ValueError("typed lead plan governor.maxParallel must be an integer") from exc
        if max_parallel < 1 or max_parallel > 16:
            raise ValueError("typed lead plan governor.maxParallel must be between 1 and 16")

        plan_id = str(plan.get("planId") or plan.get("id") or f"plan_{approved_hash_value[:16]}").strip()
        normalized: dict[str, dict[str, Any]] = {}
        for raw in raw_children:
            if not isinstance(raw, dict):
                raise ValueError("each typed child must be an object")
            child_id = str(raw.get("id") or raw.get("taskId") or "").strip()
            title = _bounded_text(raw.get("name") or raw.get("title"), limit=180)
            if not child_id or not title:
                raise ValueError("each typed child requires an id and a name")
            if child_id in normalized:
                raise ValueError(f"duplicate typed child id: {child_id}")
            role = str(raw.get("role") or raw.get("teamRole") or "executor").strip().lower()
            route = raw.get("routeSelection") or raw.get("route")
            if not isinstance(route, dict):
                route = {
                    key: raw.get(key)
                    for key in ("runtimeId", "provider", "model", "effort")
                    if raw.get(key) not in (None, "")
                }
            route = dict(route)
            if not str(route.get("model") or "").strip() or not str(route.get("effort") or "").strip():
                raise ValueError(f"typed child {child_id} requires route model and effort")
            budget = raw.get("budget")
            authority = raw.get("authority")
            tools = raw.get("tools") if "tools" in raw else raw.get("capabilities")
            if not isinstance(budget, dict) or not budget:
                raise ValueError(f"typed child {child_id} requires an explicit budget")
            if not isinstance(authority, dict) or not authority:
                raise ValueError(f"typed child {child_id} requires explicit authority")
            if not isinstance(tools, list):
                raise ValueError(f"typed child {child_id} requires an explicit tools list")
            dependencies = [str(value).strip() for value in raw.get("dependencies") or [] if str(value).strip()]
            lifecycle = raw.get("lifecycle")
            lifecycle_stage = str(
                raw.get("lifecycleStage")
                or (lifecycle.get("stage") if isinstance(lifecycle, dict) else lifecycle)
                or "requested"
            ).strip().lower()
            if lifecycle_stage not in {"requested", "queued"}:
                raise ValueError(f"typed child {child_id} must start in requested or queued lifecycle")
            handback = raw.get("handback")
            if not isinstance(handback, dict) or not handback:
                raise ValueError(f"typed child {child_id} requires a handback contract")
            child_plan = {
                "id": child_id,
                "taskId": str(raw.get("taskId") or "").strip(),
                "title": title,
                "objective": _bounded_text(raw.get("objective") or title),
                "role": role,
                "routeSelection": route,
                "budget": dict(budget),
                "authority": dict(authority),
                "tools": sorted(set(str(value).strip() for value in tools if str(value).strip())),
                "dependencies": dependencies,
                "assignedScope": sorted(set(str(value).strip() for value in raw.get("assignedScope") or [] if str(value).strip())),
                "lifecycle": dict(lifecycle) if isinstance(lifecycle, dict) else {"stage": lifecycle_stage},
                "handback": dict(handback),
                "requiredEvidence": list(raw.get("requiredEvidence") or []) if isinstance(raw.get("requiredEvidence"), list) else [],
                "stopCondition": _bounded_text(raw.get("stopCondition")),
                "estimatedSeconds": max(0, int(raw.get("estimatedSeconds") or 0)),
            }
            normalized[child_id] = child_plan
        for child_id, child in normalized.items():
            unknown = [dependency for dependency in child["dependencies"] if dependency not in normalized]
            if unknown:
                raise ValueError(f"unknown dependencies for {child_id}: {', '.join(unknown)}")

        pending = dict(normalized)
        scheduled: set[str] = set()
        waves: list[list[str]] = []
        while pending:
            candidates = [child for child in pending.values() if set(child["dependencies"]).issubset(scheduled)]
            if not candidates:
                raise ValueError("typed child dependency graph contains a cycle")
            selected: list[dict[str, Any]] = []
            occupied_scope: set[str] = set()
            for child in candidates:
                scope = set(child["assignedScope"])
                if selected and scope & occupied_scope:
                    continue
                selected.append(child)
                occupied_scope.update(scope)
                if len(selected) >= max_parallel:
                    break
            if not selected:
                selected = [candidates[0]]
            wave_ids = [child["id"] for child in selected]
            waves.append(wave_ids)
            scheduled.update(wave_ids)
            for child_id in wave_ids:
                pending.pop(child_id)

        timestamp = now or utc_now_iso()
        parent_task = str(parent_task_id or plan.get("parentTaskId") or f"conversation:{conversation_id}").strip()
        preset = dict(plan.get("preset") or {
            "id": "dynamic-lead-children",
            "schema": "neyvia.orchestration.preset.dynamic-lead-children.v1",
        })
        plan_record = {
            "schema": str(plan.get("schema") or "neyvia.orchestration.typed-lead-plan.v1"),
            "planId": plan_id,
            "approvedPlanHash": approved_hash_value,
            "parentConversationId": conversation_id,
            "parentTaskId": parent_task,
            "governor": {**dict(governor), "maxParallel": max_parallel, "waves": waves},
            "preset": preset,
        }
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT approved_plan_hash FROM orchestration_plans WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if existing:
                if existing["approved_plan_hash"] == approved_hash_value:
                    connection.commit()
                    return self.agent_graph(conversation_id)
                connection.rollback()
                raise ValueError("conversation already has a different persisted orchestration plan")
            for wave_index, wave in enumerate(waves):
                for child_id in wave:
                    child = normalized[child_id]
                    safe_child_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", child_id).strip("-") or f"child-{hashlib.sha256(child_id.encode('utf-8')).hexdigest()[:10]}"
                    child_conversation_id = f"conversation_{conversation_id}_{safe_child_id}_{approved_hash_value[:8]}"
                    durable_task_id = str(child.get("taskId") or f"task:{child_conversation_id}")
                    contract = _dynamic_child_contract(
                        {
                            "schema": "neyvia.dynamic_child_contract.v1",
                            "planId": plan_id,
                            "approvedPlanHash": approved_hash_value,
                            "parentConversationId": conversation_id,
                            "parentTaskId": parent_task,
                            "childConversationId": child_conversation_id,
                            "childTaskId": durable_task_id,
                            "role": child["role"],
                            "routeSelection": child["routeSelection"],
                            "budget": child["budget"],
                            "authority": child["authority"],
                            "tools": child["tools"],
                            "dependencies": child["dependencies"],
                            "governor": plan_record["governor"],
                            "lifecycle": child["lifecycle"],
                            "handback": child["handback"],
                            "preset": preset,
                        },
                        objective=child["objective"],
                        required_evidence=child["requiredEvidence"],
                        stop_condition=child["stopCondition"],
                    )
                    child_metadata = {**contract, "objective": child["objective"], "assignedScope": child["assignedScope"]}
                    connection.execute(
                        """
                        INSERT INTO conversations (
                            conversation_id, workspace_id, kind, parent_conversation_id, branch_kind,
                            title, generated_title, title_mode, title_locked, status,
                            capability_policy_json, metadata_json, topic_fingerprint,
                            created_at, updated_at, last_meaningful_activity_at
                        ) VALUES (?, ?, 'orchestration', ?, 'dynamic-child', ?, ?, 'automatic', 0, 'active', ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            child_conversation_id,
                            conversation["workspaceId"],
                            conversation_id,
                            child["title"],
                            child["title"],
                            _json({"mode": "dynamic-child", "readOnly": False, "parentConversationId": conversation_id}),
                            _json(child_metadata),
                            _fingerprint(child["title"], child["objective"]),
                            timestamp,
                            timestamp,
                            timestamp,
                        ),
                    )
                    self._append_event(connection, child_conversation_id, "conversation.created", {"kind": "orchestration", "branchKind": "dynamic-child", "parentConversationId": conversation_id}, True, timestamp)
                    self._index_row(connection, child_conversation_id, child_conversation_id, "conversation", child["title"], child["objective"], "orchestration dynamic-child")
                    connection.execute(
                        """
                        INSERT INTO agent_nodes (
                            node_id, conversation_id, parent_node_id, durable_task_id, parent_task_id,
                            child_conversation_id, approved_plan_hash, title, objective, status,
                            lifecycle_stage, runtime, assigned_scope_json, capabilities_json,
                            team_contract_json, progress_json, result_summary_json, wave,
                            created_at, updated_at
                        ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, 'queued', 'requested', ?, ?, ?, ?, ?, '{}', ?, ?, ?)
                        """,
                        (
                            child_id,
                            conversation_id,
                            durable_task_id,
                            parent_task,
                            child_conversation_id,
                            approved_hash_value,
                            child["title"],
                            child["objective"],
                            str(child["routeSelection"].get("runtimeId") or "").strip().lower(),
                            _json(child["assignedScope"]),
                            _json(child["tools"]),
                            _json(contract),
                            _json({"current": 0, "total": 0, "estimatedSeconds": child["estimatedSeconds"]}),
                            wave_index,
                            timestamp,
                            timestamp,
                        ),
                    )
                    for dependency in child["dependencies"]:
                        connection.execute(
                            "INSERT INTO agent_dependencies VALUES (?, ?, ?, 'finish_to_start', ?)",
                            (conversation_id, dependency, child_id, timestamp),
                        )
            connection.execute(
                """
                INSERT INTO orchestration_plans (
                    conversation_id, plan_id, schema_name, approved_plan_hash,
                    parent_task_id, plan_json, governor_json, preset_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    plan_id,
                    plan_record["schema"],
                    approved_hash_value,
                    parent_task,
                    _json(plan_record | {"children": list(normalized.values())}),
                    _json(plan_record["governor"]),
                    _json(preset),
                    timestamp,
                    timestamp,
                ),
            )
            self._append_event(connection, conversation_id, "orchestration.dynamic_children.created", {"planId": plan_id, "approvedPlanHash": approved_hash_value, "childCount": len(normalized), "waves": waves, "parentTaskId": parent_task}, True, timestamp)
            connection.execute(
                "UPDATE dynamic_plan_runs SET status = 'spawned', updated_at = ? WHERE run_id = ?",
                (timestamp, run_id),
            )
            connection.execute("UPDATE conversations SET updated_at = ?, last_meaningful_activity_at = ?, revision = revision + 1 WHERE conversation_id = ?", (timestamp, timestamp, conversation_id))
            connection.commit()
        return self.agent_graph(conversation_id)

    def retry_agent_node(self, conversation_id: str, node_id: str, *, reason: str,
                         expected_revision: int) -> dict[str, Any]:
        """Retry a failed or correction-paused attempt without changing its route."""
        if not reason.strip():
            raise ValueError("A retry reason describing the changed conditions is required")
        timestamp = utc_now_iso()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM agent_nodes WHERE node_id = ? AND conversation_id = ?",
                                     (node_id, conversation_id)).fetchone()
            if not row:
                raise KeyError(node_id)
            if int(row["revision"]) != expected_revision:
                raise RuntimeError("agent node revision conflict")
            previous = self._agent_node_from_row(row)
            correction_pause = row["lifecycle_stage"] == "waiting" and bool(
                previous.get("progress", {}).get("pendingCorrectionTurnIds")
            )
            if row["lifecycle_stage"] != "failed" and not correction_pause:
                raise ValueError("Only a failed or correction-paused node can be explicitly retried")
            self._append_event(connection, conversation_id, "agent.retry", {
                "nodeId": node_id, "reason": reason, "previousAttempt": previous,
            }, True, timestamp)
            from .efficient_workflow import continuation_checkpoint
            progress = {"retryReason": reason, "retryCount": int(previous.get("progress", {}).get("retryCount") or 0) + 1,
                        "continuationCheckpoint": continuation_checkpoint(previous),
                        "deliveredUserTurnIds": list(previous.get("progress", {}).get("deliveredUserTurnIds") or []),
                        "previousInvocationId": previous.get("progress", {}).get("invocationId"),
                        "resumeExternalRuntimeSessionId": previous.get("progress", {}).get("externalRuntimeSessionId")
                        or previous.get("progress", {}).get("resumeExternalRuntimeSessionId")}
            connection.execute("UPDATE agent_nodes SET lifecycle_stage = 'requested', status = 'queued', "
                               "progress_json = ?, result_summary_json = '{}', revision = revision + 1, updated_at = ? "
                               "WHERE node_id = ?", (_json(progress), timestamp, node_id))
            # A prior failed outcome is historical once its last failed node is
            # explicitly retried. Preserve unrelated failures and user settlement.
            connection.execute(
                "UPDATE conversations SET status = 'active', lifecycle_state = 'active', "
                "attention_state = 'active', revision = revision + 1, updated_at = ? "
                "WHERE conversation_id = ? AND status = 'failed' "
                "AND lifecycle_state = 'failed' AND attention_state = 'ready-for-review' "
                "AND NOT EXISTS (SELECT 1 FROM agent_nodes WHERE conversation_id = ? "
                "AND lifecycle_stage = 'failed')",
                (timestamp, conversation_id, conversation_id),
            )
            connection.commit()
            updated = connection.execute("SELECT * FROM agent_nodes WHERE node_id = ?", (node_id,)).fetchone()
        return self._agent_node_from_row(updated)

    def transition_agent_node(
        self,
        node_id: str,
        *,
        lifecycle_stage: str,
        status: str | None = None,
        durable_task_id: str | None = None,
        progress: dict[str, Any] | None = None,
        result_summary: dict[str, Any] | None = None,
        expected_revision: int | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        if lifecycle_stage not in AGENT_LIFECYCLE_STAGES:
            raise ValueError(f"unknown agent lifecycle stage: {lifecycle_stage}")
        timestamp = now or utc_now_iso()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM agent_nodes WHERE node_id = ?", (node_id,)).fetchone()
            if not row:
                connection.rollback()
                raise KeyError(node_id)
            if expected_revision is not None and int(row["revision"]) != int(expected_revision):
                connection.rollback()
                raise RuntimeError(f"agent node revision conflict: expected {expected_revision}, found {row['revision']}")
            current_index = AGENT_LIFECYCLE_STAGES.index(row["lifecycle_stage"]) if row["lifecycle_stage"] in AGENT_LIFECYCLE_STAGES else 0
            next_index = AGENT_LIFECYCLE_STAGES.index(lifecycle_stage)
            terminal_override = lifecycle_stage in {"failed", "cancelled", "input_required", "waiting"}
            answered_resume = (row["lifecycle_stage"] == "input_required"
                               and lifecycle_stage == "allocating"
                               and bool((progress or {}).get("answeredQuestionIds")))
            if next_index < current_index and not terminal_override and not answered_resume:
                connection.rollback()
                raise ValueError(f"agent lifecycle cannot move backwards: {row['lifecycle_stage']} -> {lifecycle_stage}")
            progress_payload = progress if isinstance(progress, dict) else {}
            result_payload = result_summary if isinstance(result_summary, dict) else {}
            spawn_receipt = (
                progress_payload.get("spawnReceipt")
                or result_payload.get("spawnReceipt")
                or progress_payload.get("runtimeReceipt")
                or result_payload.get("runtimeReceipt")
            )
            has_spawn_identity = bool(
                isinstance(spawn_receipt, dict)
                and (
                    spawn_receipt.get("sessionId")
                    or spawn_receipt.get("processId")
                    or spawn_receipt.get("receiptId")
                )
            ) or bool(
                progress_payload.get("processId")
                or progress_payload.get("sessionId")
                or result_payload.get("processId")
                or result_payload.get("sessionId")
            )
            if status == "working" and not has_spawn_identity:
                # A planned/diagnostic lane may be marked ready, but it must
                # not look live until a fresh process/session receipt exists.
                next_status = "ready"
            elif status:
                next_status = status
            elif lifecycle_stage == "completed":
                next_status = "completed"
            elif lifecycle_stage == "failed":
                next_status = "failed"
            elif lifecycle_stage == "cancelled":
                next_status = "cancelled"
            elif lifecycle_stage == "input_required":
                next_status = "input_required"
            elif lifecycle_stage == "waiting":
                next_status = "waiting"
            elif lifecycle_stage == "working" and has_spawn_identity:
                next_status = "working"
            elif lifecycle_stage in {"ready", "working", "allocating", "packing_context", "isolating_workspace", "connecting_tools"}:
                next_status = "ready"
            else:
                next_status = lifecycle_stage
            connection.execute(
                """
                UPDATE agent_nodes SET lifecycle_stage = ?, status = ?, durable_task_id = COALESCE(?, durable_task_id),
                    progress_json = COALESCE(?, progress_json), result_summary_json = COALESCE(?, result_summary_json),
                    revision = revision + 1, updated_at = ? WHERE node_id = ?
                """,
                (lifecycle_stage, next_status, durable_task_id, _json(progress) if progress is not None else None, _json(result_summary) if result_summary is not None else None, timestamp, node_id),
            )
            self._append_event(connection, row["conversation_id"], "agent.lifecycle", {"nodeId": node_id, "stage": lifecycle_stage, "status": next_status}, lifecycle_stage in {"input_required", "completed", "failed"}, timestamp)
            connection.commit()
            updated = connection.execute("SELECT * FROM agent_nodes WHERE node_id = ?", (node_id,)).fetchone()
        return self._agent_node_from_row(updated)

    def record_orchestration_outcome(
        self,
        conversation_id: str,
        *,
        status: str,
        node_counts: dict[str, int] | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        normalized_status = str(status or "").strip().casefold()
        if normalized_status not in {"completed", "failed"}:
            raise ValueError(f"unsupported orchestration outcome: {status}")
        timestamp = now or utc_now_iso()
        counts = {
            str(key): max(0, int(value))
            for key, value in (node_counts or {}).items()
        }
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._required_conversation_row(connection, conversation_id)
            if str(row["kind"] or "").casefold() != "orchestration":
                connection.rollback()
                raise ValueError("orchestration outcome requires an orchestration conversation")
            connection.execute(
                """
                UPDATE conversations
                SET status = ?, attention_state = 'ready-for-review',
                    lifecycle_state = ?, snoozed_until = NULL,
                    snooze_reason = NULL, next_wake_condition = NULL,
                    revision = revision + 1, updated_at = ?,
                    last_meaningful_activity_at = ?
                WHERE conversation_id = ?
                """,
                (
                    normalized_status,
                    normalized_status,
                    timestamp,
                    timestamp,
                    conversation_id,
                ),
            )
            self._append_event(
                connection,
                conversation_id,
                f"orchestration.{normalized_status}",
                {
                    "status": normalized_status,
                    "attentionState": "ready-for-review",
                    "nodeCounts": counts,
                },
                True,
                timestamp,
            )
            connection.commit()
        return self.get_conversation(conversation_id)

    def agent_graph(self, conversation_id: str) -> dict[str, Any]:
        self.get_conversation(conversation_id)
        with self._connection() as connection:
            nodes = connection.execute("SELECT * FROM agent_nodes WHERE conversation_id = ? ORDER BY wave, created_at, node_id", (conversation_id,)).fetchall()
            edges = connection.execute("SELECT * FROM agent_dependencies WHERE conversation_id = ? ORDER BY from_node_id, to_node_id", (conversation_id,)).fetchall()
            synthesis = connection.execute("SELECT * FROM synthesis_runs WHERE conversation_id = ? ORDER BY updated_at DESC LIMIT 1", (conversation_id,)).fetchone()
            plan_row = connection.execute("SELECT * FROM orchestration_plans WHERE conversation_id = ?", (conversation_id,)).fetchone()
        preset = None
        for row in nodes:
            contract = json.loads(row["team_contract_json"] or "{}")
            if isinstance(contract, dict) and isinstance(contract.get("preset"), dict):
                preset = contract["preset"]
                break
        governor = _decode(plan_row["governor_json"], {}) if plan_row else {}
        stored_preset = _decode(plan_row["preset_json"], {}) if plan_row else {}
        if isinstance(stored_preset, dict) and stored_preset:
            preset = stored_preset
        plan_payload = _decode(plan_row["plan_json"], {}) if plan_row else {}
        child_conversations = self.list_dynamic_children(conversation_id)
        latest_run = self.latest_dynamic_plan_run(conversation_id)
        return {
            "schema": "neyvia.constellation.v1",
            "conversationId": conversation_id,
            "nodes": [self._agent_node_from_row(row) for row in nodes],
            "edges": [{"from": row["from_node_id"], "to": row["to_node_id"], "kind": row["dependency_kind"]} for row in edges],
            "synthesis": self._synthesis_from_row(synthesis) if synthesis else None,
            "lifecycleStages": list(AGENT_LIFECYCLE_STAGES),
            "preset": preset,
            "governor": governor or None,
            "approvedPlanHash": plan_row["approved_plan_hash"] if plan_row else "",
            "parentTaskId": plan_row["parent_task_id"] if plan_row else "",
            "plan": plan_payload or None,
            "childConversations": child_conversations,
            "latestRun": latest_run,
        }

    def list_dynamic_children(self, conversation_id: str) -> list[dict[str, Any]]:
        """Return named child conversations linked to a parent graph."""

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT c.*, n.node_id, n.durable_task_id, n.parent_task_id,
                       n.approved_plan_hash, n.lifecycle_stage, n.status,
                       n.wave, n.revision AS node_revision
                FROM conversations c
                LEFT JOIN agent_nodes n ON n.child_conversation_id = c.conversation_id
                WHERE c.parent_conversation_id = ? AND c.branch_kind = 'dynamic-child'
                ORDER BY c.created_at, c.conversation_id
                """,
                (conversation_id,),
            ).fetchall()
        children: list[dict[str, Any]] = []
        for row in rows:
            item = self._conversation_from_row(row)
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            item.update(
                {
                    "childTaskId": row["durable_task_id"],
                    "parentTaskId": row["parent_task_id"] or metadata.get("parentTaskId", ""),
                    "nodeId": row["node_id"],
                    "approvedPlanHash": row["approved_plan_hash"] or metadata.get("approvedPlanHash", ""),
                    "lifecycleStage": row["lifecycle_stage"],
                    "taskStatus": row["status"],
                    "wave": int(row["wave"] or 0),
                    "nodeRevision": int(row["node_revision"] or 1),
                    "routeSelection": metadata.get("routeSelection", {}),
                    "budget": metadata.get("budget", {}),
                    "authority": metadata.get("authority", {}),
                    "tools": metadata.get("tools", []),
                    "dependencies": metadata.get("dependencies", []),
                    "handback": metadata.get("handback", {}),
                }
            )
            children.append(item)
        return children

    @staticmethod
    def _dynamic_plan_run_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "runId": row["run_id"],
            "conversationId": row["conversation_id"],
            "status": row["status"],
            "plannerRoute": _decode(row["planner_route_json"], {}),
            "plannerReceipt": _decode(row["planner_receipt_json"], {}) or None,
            "rawReply": row["raw_reply"],
            "typedPlan": _decode(row["typed_plan_json"], {}) or None,
            "validationErrors": _decode(row["validation_errors_json"], []),
            "planHash": row["plan_hash"],
            "approvalReceipt": _decode(row["approval_receipt_json"], {}) or None,
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def create_dynamic_plan_run(
        self,
        conversation_id: str,
        *,
        planner_route: dict[str, Any],
        now: str | None = None,
    ) -> dict[str, Any]:
        conversation = self.get_conversation(conversation_id)
        if conversation["kind"] != "orchestration":
            raise ValueError("dynamic plans require an orchestration conversation")
        if planner_route != FROZEN_SOL_PLANNER_ROUTE:
            raise ValueError("dynamic planning requires the frozen Sol planner route")
        run_id = f"dynamic-plan-{uuid.uuid4().hex[:20]}"
        timestamp = now or utc_now_iso()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO dynamic_plan_runs (
                    run_id, conversation_id, status, planner_route_json, created_at, updated_at
                ) VALUES (?, ?, 'planning', ?, ?, ?)
                """,
                (run_id, conversation_id, _json(planner_route), timestamp, timestamp),
            )
            self._append_event(connection, conversation_id, "orchestration.dynamic_plan.requested", {"runId": run_id, "plannerRoute": planner_route}, True, timestamp)
            connection.commit()
        return self.get_dynamic_plan_run(run_id)

    def get_dynamic_plan_run(self, run_id: str) -> dict[str, Any]:
        normalized = str(run_id or "").strip()
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM dynamic_plan_runs WHERE run_id = ?", (normalized,)).fetchone()
        if not row:
            raise KeyError(normalized)
        return self._dynamic_plan_run_from_row(row)

    def latest_dynamic_plan_run(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM dynamic_plan_runs WHERE conversation_id = ? ORDER BY updated_at DESC, run_id DESC LIMIT 1",
                (conversation_id,),
            ).fetchone()
        return self._dynamic_plan_run_from_row(row) if row else None

    def update_dynamic_plan_run(
        self,
        run_id: str,
        *,
        status: str,
        planner_receipt: dict[str, Any] | None = None,
        raw_reply: str | None = None,
        typed_plan: dict[str, Any] | None = None,
        validation_errors: list[str] | None = None,
        plan_hash: str | None = None,
        approval_receipt: dict[str, Any] | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        timestamp = now or utc_now_iso()
        fields = ["status = ?", "updated_at = ?"]
        values: list[Any] = [str(status), timestamp]
        for column, value in (
            ("planner_receipt_json", planner_receipt),
            ("raw_reply", raw_reply),
            ("typed_plan_json", typed_plan),
            ("validation_errors_json", validation_errors),
            ("plan_hash", plan_hash),
            ("approval_receipt_json", approval_receipt),
        ):
            if value is not None:
                fields.append(f"{column} = ?")
                values.append(_json(value) if column.endswith("_json") else value)
        values.append(str(run_id))
        with self._connection() as connection:
            cursor = connection.execute(
                f"UPDATE dynamic_plan_runs SET {', '.join(fields)} WHERE run_id = ?",
                values,
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise KeyError(str(run_id))
            connection.commit()
        return self.get_dynamic_plan_run(str(run_id))

    def approve_dynamic_plan_run(
        self,
        run_id: str,
        *,
        approval_receipt: dict[str, Any],
    ) -> dict[str, Any]:
        run = self.get_dynamic_plan_run(run_id)
        if run["status"] != "awaiting_approval" or not run.get("planHash"):
            raise ValueError("dynamic plan is not awaiting approval")
        if not isinstance(approval_receipt, dict):
            raise ValueError("a Neyvia approval receipt is required")
        if (
            str(approval_receipt.get("schema") or "") != "neyvia.approval.receipt.v1"
            or str(approval_receipt.get("issuer") or "").strip().lower() != "neyvia"
            or approval_receipt.get("approved") is not True
            or str(approval_receipt.get("runId") or "") != run["runId"]
            or str(approval_receipt.get("planHash") or "").strip().lower() != run["planHash"]
        ):
            raise ValueError("approval receipt is not bound to this dynamic plan hash and run")
        return self.update_dynamic_plan_run(
            run_id,
            status="approved",
            approval_receipt=dict(approval_receipt),
        )

    def record_synthesis(
        self,
        conversation_id: str,
        *,
        candidate_node_ids: list[str],
        recommendation: str,
        rationale: str,
        evidence: dict[str, Any],
        status: str = "ready",
        now: str | None = None,
    ) -> dict[str, Any]:
        from .agent_delta import read_agent_delta

        graph = self.agent_graph(conversation_id)
        known = {node["nodeId"] for node in graph["nodes"]}
        unknown = sorted(set(candidate_node_ids) - known)
        if unknown:
            raise ValueError(f"unknown synthesis candidates: {', '.join(unknown)}")
        nodes_by_id = {node["nodeId"]: node for node in graph["nodes"]}
        coverage: list[dict[str, Any]] = []
        supplied_evidence = evidence if isinstance(evidence, dict) else {}
        for node_id in candidate_node_ids:
            node = nodes_by_id[node_id]
            delta = read_agent_delta(node)
            contract = (
                dict(node.get("teamContract") or {})
                if isinstance(node.get("teamContract"), dict)
                else {}
            )
            provided = supplied_evidence.get(node_id)
            explicit_evidence = bool(
                provided
                and (
                    not isinstance(provided, dict)
                    or any(value not in (None, "", [], {}) for value in provided.values())
                )
            )
            evidence_item_count = len(delta.evidence) + len(delta.artifacts)
            contract_ready = all(contract.get(field) for field in TEAM_CONTRACT_FIELDS)
            coverage.append(
                {
                    "nodeId": node_id,
                    "completed": node.get("lifecycleStage") == "completed",
                    "contractReady": contract_ready,
                    "typedEvidenceItemCount": evidence_item_count,
                    "explicitEvidenceProvided": explicit_evidence,
                    "evidenceReady": evidence_item_count > 0 or explicit_evidence,
                }
            )
        evidence_contract_ready = (
            len(coverage) >= 2
            and all(
                item["completed"]
                and item["contractReady"]
                and item["evidenceReady"]
                for item in coverage
            )
        )
        resolved_status = status if evidence_contract_ready else "blocked_evidence"
        stored_evidence = dict(supplied_evidence)
        stored_evidence["_contract"] = {
            "schema": "neyvia.synthesis_evidence_contract.v1",
            "ready": evidence_contract_ready,
            "minimumComparableCandidates": 2,
            "candidateCount": len(coverage),
            "coverage": coverage,
            "transcriptsIncluded": False,
            "nextAction": (
                "Review comparable typed evidence before accepting an outcome."
                if evidence_contract_ready
                else "Complete each candidate contract and attach typed evidence or a durable artifact."
            ),
        }
        timestamp = now or utc_now_iso()
        synthesis_id = f"synthesis_{uuid.uuid4().hex}"
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO synthesis_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    synthesis_id,
                    conversation_id,
                    resolved_status,
                    str(recommendation or ""),
                    str(rationale or ""),
                    _json(candidate_node_ids),
                    _json(stored_evidence),
                    timestamp,
                    timestamp,
                ),
            )
            self._append_event(
                connection,
                conversation_id,
                "synthesis.ready"
                if evidence_contract_ready
                else "synthesis.evidence_blocked",
                {
                    "synthesisId": synthesis_id,
                    "candidates": candidate_node_ids,
                    "evidenceContractReady": evidence_contract_ready,
                },
                True,
                timestamp,
            )
            connection.commit()
            row = connection.execute("SELECT * FROM synthesis_runs WHERE synthesis_id = ?", (synthesis_id,)).fetchone()
        return self._synthesis_from_row(row)

    def import_legacy_state(self, payload: object) -> dict[str, Any]:
        """Idempotently preserve the former JSON conversation snapshots in SQLite.

        The JSON file remains readable as a rollback artifact, but it is no longer the
        concurrent source of truth once its sessions and turns have been imported.
        """
        from .harness_jobs import _exclusive_job_lock
        # The read/create/append decisions span multiple SQLite transactions.
        # Keep competing importers under one crash-safe lease, including the
        # resulting count observer; a killed importer can be resumed idempotently.
        with _exclusive_job_lock(self.database_path.with_suffix(".legacy-import"), timeout_seconds=120):
            return self._import_legacy_state(payload)

    def _import_legacy_state(self, payload: object) -> dict[str, Any]:
        state = payload if isinstance(payload, dict) else {}
        sessions = state.get("chatSessions") if isinstance(state.get("chatSessions"), list) else []
        transcripts = state.get("chatSessionTranscripts") if isinstance(state.get("chatSessionTranscripts"), dict) else {}
        imported_conversations = 0
        imported_turns = 0
        skipped_conversations = 0
        skipped_turns = 0
        with self._connection() as connection:
            before = (connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0], connection.execute("SELECT COUNT(*) FROM conversation_turns").fetchone()[0])
        for raw_session in sessions:
            if not isinstance(raw_session, dict):
                continue
            conversation_id = str(raw_session.get("id") or "").strip()
            if not conversation_id:
                continue
            try:
                self.get_conversation(conversation_id)
                skipped_conversations += 1
            except KeyError:
                self.create_conversation(
                    conversation_id=conversation_id,
                    workspace_id=str(raw_session.get("workspaceId") or ""),
                    kind="chat",
                    title=str(raw_session.get("title") or "New conversation"),
                    title_mode="automatic",
                    metadata={
                        "migratedFrom": "fluxio.conversation_state.v1",
                        "legacyLastPreview": str(raw_session.get("lastPreview") or ""),
                        "legacyUpdatedAt": str(raw_session.get("updatedAt") or ""),
                    },
                    now=str(raw_session.get("createdAt") or "") or None,
                )
                imported_conversations += 1
            for raw_turn in transcripts.get(conversation_id) or []:
                if not isinstance(raw_turn, dict):
                    continue
                # Optimistic UI placeholders must not occupy a durable turn ID
                # before the matching runtime result is committed.
                if raw_turn.get("pending") or raw_turn.get("source") == "runtime-pending":
                    skipped_turns += 1
                    continue
                turn_id = str(raw_turn.get("id") or "").strip() or None
                if turn_id:
                    with self._connection() as connection:
                        exists = connection.execute(
                            "SELECT 1 FROM conversation_turns WHERE turn_id = ?",
                            (turn_id,),
                        ).fetchone()
                    if exists:
                        skipped_turns += 1
                        continue
                content = str(raw_turn.get("title") or raw_turn.get("detail") or "").strip()
                if not content:
                    continue
                self.append_turn(
                    conversation_id,
                    turn_id=turn_id,
                    role=str(raw_turn.get("role") or "user"),
                    content=content,
                    detail=str(raw_turn.get("detail") or ""),
                    source=str(raw_turn.get("source") or "legacy-json"),
                    turn_kind=str(raw_turn.get("messageKind") or "dialogue"),
                    metadata={
                        "migratedFrom": "fluxio.conversation_state.v1",
                        "tone": str(raw_turn.get("tone") or "neutral"),
                        "turnReceipt": raw_turn.get("turnReceipt") if isinstance(raw_turn.get("turnReceipt"), dict) else None,
                        "chips": list(raw_turn.get("chips") or [])[:6],
                    },
                    meaningful=not bool(raw_turn.get("pending")),
                    now=str(raw_turn.get("createdAt") or "") or None,
                )
                imported_turns += 1
        result = {
            "schema": "neyvia.conversation-migration.v1",
            "source": "fluxio.conversation_state.v1",
            "importedConversations": imported_conversations,
            "importedTurns": imported_turns,
            "skippedConversations": skipped_conversations,
            "skippedTurns": skipped_turns,
        }
        from .proofs_d_neyvia import conversation_import
        conversation_import(self, result, before)
        return result

    def snapshot(self, *, limit: int = 80, conversation_id: str | None = None) -> dict[str, Any]:
        conversations = self.list_conversations(limit=limit)
        selected = self.get_conversation(conversation_id) if conversation_id else None
        if selected and not any(row["conversationId"] == conversation_id for row in conversations):
            conversations = [selected, *conversations[:max(0, limit - 1)]]
        question_branches = [row for row in conversations if row["branchKind"] == "question"]
        orchestrations = [row for row in conversations if row["kind"] == "orchestration" and not row["parentConversationId"]]
        active = selected if conversation_id else (orchestrations[0] if orchestrations else None)
        active_graph = self.agent_graph(active["conversationId"]) if active and active["kind"] == "orchestration" else None
        return {
            "schema": "neyvia.conversation-snapshot.v1",
            "generatedAt": utc_now_iso(),
            "conversations": conversations,
            "questionBranches": question_branches,
            "activeConstellation": active_graph,
            "search": {"available": True, "mode": "fts5+topic_fingerprint" if self.fts_available else "topic_fingerprint"},
            "titleModes": sorted(TITLE_MODES),
            "durability": {"database": str(self.database_path), "journalMode": "WAL", "optimisticRevisions": True, "tombstones": True},
        }

    def deletion_snapshot(self) -> dict[str, Any]:
        """Return every active id and revision for an explicit clear-history review."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT conversation_id, revision FROM conversations WHERE deleted_at IS NULL ORDER BY conversation_id"
            ).fetchall()
        conversations = [
            {"conversationId": str(row["conversation_id"]), "expectedRevision": int(row["revision"])}
            for row in rows
        ]
        return {"schema": "neyvia.conversation-deletion-snapshot.v1", "count": len(conversations), "conversations": conversations}

    @staticmethod
    def _required_conversation_row(
        connection: sqlite3.Connection,
        conversation_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM conversations WHERE conversation_id = ? AND deleted_at IS NULL",
            (str(conversation_id or "").strip(),),
        ).fetchone()
        if not row:
            raise KeyError(conversation_id)
        return row

    @staticmethod
    def _row_metadata(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        if isinstance(row, dict):
            metadata = row.get("metadata")
            return metadata if isinstance(metadata, dict) else {}
        metadata = _decode(row["metadata_json"], {})
        return metadata if isinstance(metadata, dict) else {}

    @classmethod
    def _blocking_attention_reasons(
        cls,
        row: sqlite3.Row | dict[str, Any],
    ) -> list[str]:
        metadata = cls._row_metadata(row)
        reasons = []
        if bool(metadata.get("hasBlockingApproval")) or int(
            metadata.get("pendingApprovalCount") or 0
        ) > 0:
            reasons.append("approval-required")
        if bool(metadata.get("hasVerificationFailure")) or int(
            metadata.get("verificationFailureCount") or 0
        ) > 0:
            reasons.append("verification-failed")
        if bool(metadata.get("awaitingUserAnswer")):
            reasons.append("answer-required")
        if bool(metadata.get("securityDecisionPending")):
            reasons.append("security-decision")
        if bool(metadata.get("runtimeUnavailable")):
            reasons.append("runtime-unavailable")
        return reasons

    @classmethod
    def _derived_attention_state(
        cls,
        row: sqlite3.Row | dict[str, Any],
        *,
        ignore_settlement: bool = False,
        ignore_snooze: bool = False,
    ) -> str:
        def value(sql_name: str, api_name: str, default: object = "") -> object:
            if isinstance(row, dict):
                return row.get(api_name, default)
            return row[sql_name]

        if cls._blocking_attention_reasons(row):
            return "needs-action"
        if not ignore_settlement and value("settled_at", "settledAt"):
            return "settled"
        snoozed_until = str(value("snoozed_until", "snoozedUntil") or "").strip()
        wake_condition = str(
            value("next_wake_condition", "nextWakeCondition") or ""
        ).strip()
        snooze_active = bool(wake_condition)
        if snoozed_until:
            try:
                snooze_active = (
                    datetime.fromisoformat(snoozed_until.replace("Z", "+00:00"))
                    > datetime.now(timezone.utc)
                )
            except ValueError:
                snooze_active = False
        if not ignore_snooze and snooze_active:
            return "quiet"
        status = str(value("status", "status") or "").strip().casefold()
        if status in TERMINAL_CONVERSATION_STATUSES:
            return "ready-for-review"
        stored = str(
            value("attention_state", "attentionState", "active") or "active"
        ).strip().casefold()
        if stored in ATTENTION_STATES - {"quiet", "settled"}:
            return stored
        return "active"

    @classmethod
    def _attention_thread(cls, row: dict[str, Any]) -> dict[str, Any]:
        metadata = cls._row_metadata(row)
        blocking = cls._blocking_attention_reasons(row)
        state = cls._derived_attention_state(row)
        return {
            "conversationId": row["conversationId"],
            "kind": row["kind"],
            "title": row["title"],
            "missionId": str(metadata.get("missionId") or "") or None,
            "projectId": row.get("projectId") or None,
            "workspaceId": row.get("workspaceId") or None,
            "branch": row.get("branch") or None,
            "pullRequest": row.get("pullRequest") or None,
            "attentionState": state,
            "lifecycleState": row.get("lifecycleState") or "active",
            "settledAt": row.get("settledAt"),
            "settledBy": row.get("settledBy"),
            "settlementReason": row.get("settlementReason"),
            "snoozedUntil": row.get("snoozedUntil"),
            "snoozeReason": row.get("snoozeReason"),
            "nextWakeCondition": row.get("nextWakeCondition"),
            "hasBlockingApproval": "approval-required" in blocking,
            "hasVerificationFailure": "verification-failed" in blocking,
            "awaitingUserAnswer": "answer-required" in blocking,
            "securityDecisionPending": "security-decision" in blocking,
            "hasVerificationEvidence": bool(
                metadata.get("hasVerificationEvidence")
            ),
            "unreadMeaningfulChanges": int(
                row.get("unreadMeaningfulChanges") or 0
            ),
            "lastMeaningfulActivityAt": row.get("lastMeaningfulActivityAt"),
        }

    @staticmethod
    def _append_event(connection: sqlite3.Connection, conversation_id: str, kind: str, payload: dict[str, Any], meaningful: bool, timestamp: str) -> None:
        connection.execute(
            "INSERT INTO conversation_events (conversation_id, kind, payload_json, meaningful, created_at) VALUES (?, ?, ?, ?, ?)",
            (conversation_id, kind, _json(payload), int(meaningful), timestamp),
        )

    def _index_row(self, connection: sqlite3.Connection, conversation_id: str, source_id: str, source_kind: str, title: str, content: str, tags: str) -> None:
        if not self.fts_available:
            return
        connection.execute("DELETE FROM conversation_search_fts WHERE source_id = ?", (source_id,))
        connection.execute(
            "INSERT INTO conversation_search_fts (conversation_id, source_id, source_kind, title, content, tags) VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, source_id, source_kind, title, content, tags),
        )

    def _replace_conversation_index(self, connection: sqlite3.Connection, conversation_id: str, title: str, kind: str, branch_kind: str) -> None:
        self._index_row(connection, conversation_id, conversation_id, "conversation", title, "", f"{kind} {branch_kind}")

    @staticmethod
    def _conversation_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "runtimeId": row["last_runtime"] if "last_runtime" in row.keys() else "",
            "conversationId": row["conversation_id"],
            "workspaceId": row["workspace_id"],
            "kind": row["kind"],
            "parentConversationId": row["parent_conversation_id"],
            "branchKind": row["branch_kind"],
            "title": row["title"],
            "generatedTitle": row["generated_title"],
            "titleMode": row["title_mode"],
            "titleLocked": bool(row["title_locked"]),
            "status": row["status"],
            "attentionState": row["attention_state"],
            "lifecycleState": row["lifecycle_state"],
            "settledAt": row["settled_at"],
            "settledBy": row["settled_by"],
            "settlementReason": row["settlement_reason"],
            "snoozedUntil": row["snoozed_until"],
            "snoozeReason": row["snooze_reason"],
            "nextWakeCondition": row["next_wake_condition"],
            "projectId": row["project_id"],
            "branch": row["branch"],
            "pullRequest": _decode(row["pull_request_json"], {}),
            "unreadMeaningfulChanges": int(row["unread_meaningful_changes"]),
            "capabilityPolicy": _decode(row["capability_policy_json"], {}),
            "metadata": _decode(row["metadata_json"], {}),
            "topicFingerprint": row["topic_fingerprint"],
            "revision": int(row["revision"]),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "lastMeaningfulActivityAt": row["last_meaningful_activity_at"],
            "archivedAt": row["archived_at"],
            "deletedAt": row["deleted_at"],
        }

    @staticmethod
    def _history_turn_from_row(row: sqlite3.Row) -> dict[str, Any]:
        """Project dialogue without embedding a full runtime snapshot per turn.

        Raw tool traces and snapshots remain available through get_turn; the
        paginated transcript needs the complete text and route/receipt only.
        """
        turn = NeyviaConversationStore._turn_from_row(row)
        metadata = turn["metadata"]
        result = metadata.get("runtimeResult")
        if isinstance(result, dict):
            compartment = result.get("compartment") or {}
            metadata["runtimeResult"] = {
                key: result[key]
                for key in ("runtime", "route", "status", "sessionId", "elapsedMs", "turnReceipt")
                if key in result
            }
            if isinstance(compartment, dict) and compartment.get("turnReceipt"):
                metadata["runtimeResult"]["compartment"] = {
                    "turnReceipt": compartment["turnReceipt"],
                }
            metadata["runtimeDetailsAvailable"] = True
        return turn

    @staticmethod
    def _turn_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "turnId": row["turn_id"],
            "conversationId": row["conversation_id"],
            "role": row["role"],
            "content": row["content"],
            "detail": row["detail"],
            "source": row["source"],
            "turnKind": row["turn_kind"],
            "metadata": _decode(row["metadata_json"], {}),
            "meaningful": bool(row["meaningful"]),
            "createdAt": row["created_at"],
        }

    @staticmethod
    def _context_atom_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "atomId": row["atom_id"],
            "conversationId": row["conversation_id"],
            "kind": row["kind"],
            "content": row["content"],
            "evidenceTurnId": row["evidence_turn_id"],
            "confidence": float(row["confidence"]),
            "freshnessExpiresAt": row["freshness_expires_at"],
            "supersedesAtomId": row["supersedes_atom_id"],
            "permissionScope": _decode(row["permission_scope_json"], {}),
            "topicFingerprint": row["topic_fingerprint"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _agent_node_from_row(row: sqlite3.Row) -> dict[str, Any]:
        team_contract = _decode(row["team_contract_json"], {})
        if (
            isinstance(team_contract, dict)
            and team_contract.get("schema") == "neyvia.dynamic_child_contract.v1"
        ):
            team_contract = _dynamic_child_contract(
                team_contract,
                objective=row["objective"],
            )
        route_selection = team_contract.get("routeSelection") if isinstance(team_contract, dict) else {}
        return {
            "nodeId": row["node_id"],
            "conversationId": row["conversation_id"],
            "parentNodeId": row["parent_node_id"],
            "durableTaskId": row["durable_task_id"],
            "parentTaskId": row["parent_task_id"],
            "childConversationId": row["child_conversation_id"],
            "approvedPlanHash": row["approved_plan_hash"],
            "title": row["title"],
            "objective": row["objective"],
            "status": row["status"],
            "lifecycleStage": row["lifecycle_stage"],
            "runtime": row["runtime"],
            "role": team_contract.get("role", "") if isinstance(team_contract, dict) else "",
            "routeSelection": route_selection if isinstance(route_selection, dict) else {},
            "route": route_selection if isinstance(route_selection, dict) else {},
            "assignedScope": _decode(row["assigned_scope_json"], []),
            "capabilities": _decode(row["capabilities_json"], []),
            "teamContract": team_contract,
            "progress": _decode(row["progress_json"], {}),
            "resultSummary": _decode(row["result_summary_json"], {}),
            "wave": int(row["wave"]),
            "revision": int(row["revision"]),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _synthesis_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "synthesisId": row["synthesis_id"],
            "conversationId": row["conversation_id"],
            "status": row["status"],
            "recommendation": row["recommendation"],
            "rationale": row["rationale"],
            "candidateNodeIds": _decode(row["candidate_node_ids_json"], []),
            "evidence": _decode(row["evidence_json"], {}),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
