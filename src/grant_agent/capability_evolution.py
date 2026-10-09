"""Durable, evidence-gated capability evolution for the Neyvia ecosystem.

The service treats skills, agent roles, workflows, and generated applications as
versioned capabilities.  Repetition is never interpreted as improvement.  A
candidate only earns an operator decision after a comparable baseline/candidate
trial has enough verification and value evidence.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import shutil
import sqlite3
import sys
import uuid
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .agent_delta import read_agent_delta
from .proofs_a_capabilities import checked_action
from .proofs_a_capability_evolution import (
    check_recommendation, check_trial, check_materialization, check_lease,
    check_handoff, check_constellation, check_materialization_write,
    check_app_import, check_app_learning,
)
from .skill_package import (
    build_validated_skill_package,
    extract_skill_workflow_steps,
    validate_skill_markdown,
)


CAPABILITY_EVOLUTION_SCHEMA = "neyvia.capability_evolution.v1"
CAPABILITY_ACTIONS = {
    "prove",
    "branch",
    "repair",
    "merge",
    "quarantine",
    "retire",
    "promote_to_app",
}
TRIAL_STATES = {
    "planned",
    "collecting",
    "evidence_ready",
    "accepted",
    "held",
    "rejected",
    "cancelled",
}
FINAL_TRIAL_STATES = {"accepted", "rejected", "cancelled"}
LINEAGE_STATES = {
    "active",
    "candidate",
    "approved",
    "superseded",
    "quarantined",
    "retired",
}
TURN_RECEIPT_SCHEMA = "fluxio.turn_receipt.v1"
RECEIPT_MEASUREMENT_SCHEMA = "neyvia.receipt_measurement.v1"
RECEIPT_COMPARISON_SCHEMA = "neyvia.receipt_comparison.v1"
COUNTERFACTUAL_FORGE_SCHEMA = "neyvia.counterfactual_skill_forge.v1"
COUNTERFACTUAL_CASE_LIMIT = 6
SKILL_CANDIDATE_BRIEF_SCHEMA = "neyvia.skill_candidate_brief.v1"
SEALED_SKILL_CANDIDATE_SCHEMA = "neyvia.sealed_skill_candidate.v1"
SKILL_MATERIALIZATION_SCHEMA = "neyvia.skill_materialization.v1"
SKILL_MATERIALIZATION_RECEIPT_SCHEMA = (
    "neyvia.skill_materialization_receipt.v1"
)
SKILL_MATERIALIZATION_ROLLBACK_SCHEMA = (
    "neyvia.skill_materialization_rollback.v1"
)
PROOF_LEASE_SCHEMA = "neyvia.capability_proof_lease.v1"
PROOF_LEASE_EVENT_SCHEMA = "neyvia.capability_proof_lease_event.v1"
PROOF_LEASE_REVIEW_SCHEMA = "neyvia.capability_proof_lease_review.v1"
PROOF_LEASE_STATES = {
    "current",
    "review_due",
    "reproof_required",
    "held",
    "retirement_review",
    "withdrawn",
}
PROOF_LEASE_DISPOSITIONS = {
    "needs_repair",
    "no_longer_needed",
}
PROOF_LEASE_MAX_DEPENDENCIES = 12
PROOF_LEASE_MAX_DEPENDENCY_BYTES = 16 * 1024 * 1024
PROOF_LEASE_MIN_REVIEW_DAYS = 1
PROOF_LEASE_MAX_REVIEW_DAYS = 365
PROOF_LEASE_EXCLUDED_PARTS = {
    ".agent_control",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "memory",
    "node_modules",
    "target",
    "venv",
}
PROOF_LEASE_SECRET_SUFFIXES = {
    ".env",
    ".key",
    ".p12",
    ".pem",
    ".pfx",
}
PROOF_LEASE_SECRET_NAME = re.compile(
    r"(?:^|[-_.])(cookie|credential|login-data|password|private-key|secret|token)(?:[-_.]|$)",
    re.IGNORECASE,
)
APP_FACTORY_HANDOFF_SCHEMA = "neyvia.app_factory_lineage_handoff.v1"
APP_FACTORY_HANDOFF_REVIEW_SCHEMA = (
    "neyvia.app_factory_lineage_handoff_review.v1"
)
APP_FACTORY_VERIFICATION_RECEIPT_SCHEMA = (
    "neyvia.app-factory-verification-receipt/v1"
)
APP_FACTORY_APP_BINDING_SCHEMA = "neyvia.app_factory_app_binding.v1"
APP_FACTORY_HANDOFF_STABLE_FIELDS = (
    "schema",
    "handoffId",
    "materializationId",
    "trialId",
    "approvedLineageId",
    "parentLineageId",
    "skillId",
    "candidateDigest",
    "skillSha256",
    "metadataSha256",
    "workflowSteps",
    "comparisonRuns",
    "forgeId",
    "forgeDigest",
    "scorecard",
    "authorityComparison",
    "rollback",
    "candidateActivated",
    "appActivated",
    "transcriptsIncluded",
)
CAPABILITY_RUN_SCHEMA = "neyvia.capability-run/v2"
CAPABILITY_RUN_BUNDLE_SCHEMA = "neyvia.capability-run-bundle/v2"
APP_OUTCOME_IMPORT_SCHEMA = "neyvia.app_outcome_import.v1"
APP_RUN_MEASUREMENT_SCHEMA = "neyvia.app_run_measurement.v1"
PERSONAL_FRICTION_GRAPH_SCHEMA = "neyvia.personal_friction_graph.v1"
OPERATOR_DIVIDENDS_SCHEMA = "neyvia.operator_dividends.v1"
CAPABILITY_RUN_MAX_BUNDLE_BYTES = 2 * 1024 * 1024
CAPABILITY_RUN_MAX_RUNS = 100
CAPABILITY_RUN_MAX_STEPS = 50
CAPABILITY_RUN_MAX_DURATION_SECONDS = 7 * 24 * 60 * 60
CAPABILITY_RUN_OUTCOMES = {"completed", "blocked"}
CAPABILITY_RUN_OPERATOR_VALUES = {"helpful", "not_sure", "not_helpful"}
CAPABILITY_RUN_FRICTION_CODES = {
    "none",
    "repeated_manual_entry",
    "context_reentry",
    "tool_switching",
    "unclear_output",
    "verification_gap",
    "permission_wait",
    "runtime_failure",
    "other",
}
CAPABILITY_RUN_FRICTION_SEVERITIES = {"none", "low", "medium", "high"}
FRICTION_PATTERN_MINIMUM = 2
FRICTION_LABELS = {
    "repeated_manual_entry": "Repeated manual entry",
    "context_reentry": "Context had to be rebuilt",
    "tool_switching": "Too much tool switching",
    "unclear_output": "Output needed clarification",
    "verification_gap": "Proof was hard to verify",
    "permission_wait": "Permission flow interrupted work",
    "runtime_failure": "Runtime failed during the workflow",
    "other": "Repeated operator friction",
}
COUNTERFACTUAL_REQUIRED_ACTIONS = {
    "branch",
    "repair",
    "merge",
    "promote_to_app",
}
SKILL_CANDIDATE_REQUIRED_ACTIONS = {
    "branch",
    "repair",
    "merge",
}
SKILL_MATERIALIZATION_STATES = {
    "materialized_inactive",
    "withdrawn",
}
OPERATOR_VALUE_VERDICTS = {
    "candidate_better",
    "about_the_same",
    "baseline_better",
}
RECEIPT_SUCCESS_STATUSES = {
    "completed",
    "completed_no_reply",
    "done",
    "passed",
    "ready",
    "returned",
    "success",
    "succeeded",
}
RECEIPT_FAILURE_STATUSES = {
    "blocked",
    "cancelled",
    "canceled",
    "error",
    "failed",
    "input_required",
    "timeout",
    "timed_out",
}
VERIFICATION_TERMS = (
    "build",
    "check",
    "lint",
    "proof",
    "test",
    "validat",
    "verif",
)
INTERVENTION_TERMS = (
    "approval",
    "blocked",
    "error",
    "fail",
    "input_required",
    "intervention",
    "retry",
    "timeout",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_after(value: str, *, days: int) -> str:
    parsed = _parse_utc(value)
    if parsed is None:
        raise ValueError("issuedAt is not a valid timestamp")
    return (parsed + timedelta(days=days)).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _stable_id(prefix: str, *values: object) -> str:
    joined = "\x1f".join(str(value or "").strip() for value in values)
    return f"{prefix}_{hashlib.sha256(joined.encode('utf-8')).hexdigest()[:18]}"


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _bounded_text(value: object, limit: int = 500) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit]


def _float(value: object, fallback: float | None = None) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _int(value: object, fallback: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, dict)]


def _skill_slug(value: object, *, limit: int = 48) -> str:
    normalized = re.sub(
        r"[^a-z0-9]+",
        "-",
        str(value or "").strip().casefold(),
    ).strip("-")
    normalized = re.sub(r"-+", "-", normalized)
    return normalized[:limit].rstrip("-") or "skill"


def _versioned_skill_id(
    label: object,
    capability_id: object,
    action: object,
    trial_id: object,
) -> str:
    base_value = label or capability_id or "skill"
    base = _skill_slug(base_value)
    suffix = (
        f"-{_skill_slug(action, limit=12)}-"
        f"{_skill_slug(str(trial_id).rsplit('_', 1)[-1], limit=8)}"
    )
    max_base_length = max(1, 64 - len(suffix))
    base = base[:max_base_length].rstrip("-") or "skill"
    return f"{base}{suffix}"


def _is_sealed_skill_candidate(candidate: object) -> bool:
    return bool(
        isinstance(candidate, dict)
        and candidate.get("schema") == SEALED_SKILL_CANDIDATE_SCHEMA
        and candidate.get("state") == "sealed"
        and candidate.get("packageDigest")
        and candidate.get("skillMarkdown")
        and candidate.get("openaiYaml")
        and candidate.get("activated") is False
    )


def _trial_requires_sealed_skill_candidate(trial: dict[str, Any]) -> bool:
    return bool(
        str(trial.get("capabilityKind") or "skill") == "skill"
        and str(trial.get("action") or "") in SKILL_CANDIDATE_REQUIRED_ACTIONS
    )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.writing-{uuid.uuid4().hex[:8]}")
    try:
        temporary.write_bytes(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
        )
        temporary.replace(path)
    except OSError:
        if temporary.exists():
            temporary.unlink()
        raise


def _source_digest(path_value: object, fallback: object) -> str:
    path_text = str(path_value or "").strip()
    if path_text:
        try:
            source_path = Path(path_text).expanduser().resolve()
            if source_path.is_file():
                return hashlib.sha256(source_path.read_bytes()).hexdigest()
        except OSError:
            pass
    return _canonical_digest(fallback)


def _metric_delta(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    key: str,
    *,
    lower_is_better: bool = False,
) -> float | None:
    before = _float(baseline.get(key))
    after = _float(candidate.get(key))
    if before is None or after is None:
        return None
    return round((before - after) if lower_is_better else (after - before), 4)


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stable_app_factory_handoff_contract(
    handoff: dict[str, Any],
) -> dict[str, Any]:
    contract = {
        field: handoff.get(field)
        for field in APP_FACTORY_HANDOFF_STABLE_FIELDS
    }
    if isinstance(handoff.get("proofLease"), dict):
        contract["proofLease"] = handoff["proofLease"]
    return contract


def _app_factory_binding_digest(
    handoff_digest: str,
    spec: dict[str, Any],
) -> str:
    return _canonical_digest(
        {
            "schema": APP_FACTORY_APP_BINDING_SCHEMA,
            "handoffDigest": handoff_digest,
            "appId": str(spec.get("appId") or ""),
            "name": str(spec.get("name") or ""),
            "brief": str(spec.get("brief") or ""),
            "target": str(spec.get("target") or ""),
            "template": "capability",
            "theme": str(spec.get("theme") or ""),
            "directory": str(spec.get("directory") or ""),
        }
    )


def _platform_contract() -> dict[str, str]:
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    return {
        "system": platform.system().strip().casefold() or "unknown",
        "machine": platform.machine().strip().casefold() or "unknown",
        "python": python_version,
    }


def _normalized_status(value: object) -> str:
    return str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")


def _receipt_cost(receipt: dict[str, Any]) -> float | None:
    for candidate in (
        receipt.get("cost"),
        receipt.get("costUsd"),
        receipt.get("costUSD"),
        (receipt.get("usage") or {}).get("cost")
        if isinstance(receipt.get("usage"), dict)
        else None,
    ):
        value = _float(candidate)
        if value is not None and value >= 0:
            return round(value, 6)
    return None


def _receipt_artifact_refs(receipt: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for item in receipt.get("proofArtifacts") or []:
        if isinstance(item, dict):
            value = (
                item.get("path")
                or item.get("url")
                or item.get("previewUrl")
                or item.get("uri")
                or item.get("artifactId")
                or item.get("kind")
            )
        else:
            value = item
        text = _bounded_text(value, 300)
        if text and text not in refs:
            refs.append(text)
    return refs[:24]


def _permission_names(value: object) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    names: list[str] = []
    for item in value:
        text = _bounded_text(item, 120).casefold()
        if text and text not in names:
            names.append(text)
    return sorted(names)[:40]


def _receipt_authority(receipt: dict[str, Any]) -> dict[str, Any]:
    permission_summary = (
        dict(receipt.get("permissionSummary") or {})
        if isinstance(receipt.get("permissionSummary"), dict)
        else {}
    )
    authority = (
        dict(receipt.get("authority") or {})
        if isinstance(receipt.get("authority"), dict)
        else {}
    )
    source = permission_summary or authority
    recorded = bool(source)
    allowed = _permission_names(
        source.get("allowed")
        or source.get("allowedPermissions")
        or source.get("granted")
    )
    approval_required = _permission_names(
        source.get("approvalRequired")
        or source.get("approvalGated")
        or source.get("requiresApproval")
    )
    denied = _permission_names(
        source.get("denied")
        or source.get("forbidden")
        or source.get("blocked")
    )
    return {
        "recorded": recorded,
        "allowed": allowed,
        "approvalRequired": approval_required,
        "denied": denied,
        "digest": (
            _canonical_digest(
                {
                    "allowed": allowed,
                    "approvalRequired": approval_required,
                    "denied": denied,
                }
            )
            if recorded
            else ""
        ),
    }


def _authority_delta(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    if not baseline.get("recorded") or not candidate.get("recorded"):
        return {
            "status": "unknown",
            "recorded": False,
            "expandedPermissions": [],
            "reducedPermissions": [],
            "unchangedPermissions": [],
            "newlyDeniedRequests": [],
            "gatePassed": False,
            "reason": "Both receipts must record their permission boundary.",
        }

    def states(summary: dict[str, Any]) -> dict[str, str]:
        result: dict[str, str] = {}
        for name in summary.get("denied") or []:
            result[str(name)] = "denied"
        for name in summary.get("approvalRequired") or []:
            result[str(name)] = "approval_required"
        for name in summary.get("allowed") or []:
            result[str(name)] = "allowed"
        return result

    before = states(baseline)
    after = states(candidate)
    authority_rank = {
        "absent": -1,
        "denied": 0,
        "approval_required": 1,
        "allowed": 2,
    }
    expanded: list[str] = []
    reduced: list[str] = []
    unchanged: list[str] = []
    newly_denied: list[str] = []
    for permission in sorted(set(before) | set(after)):
        before_state = before.get(permission, "absent")
        after_state = after.get(permission, "absent")
        if before_state == after_state:
            unchanged.append(permission)
            continue
        if before_state == "absent" and after_state == "denied":
            newly_denied.append(permission)
            continue
        if authority_rank[after_state] > authority_rank[before_state]:
            expanded.append(permission)
        else:
            reduced.append(permission)

    status = "expanded" if expanded else "reduced" if reduced else "unchanged"
    return {
        "status": status,
        "recorded": True,
        "baseline": {
            "allowed": list(baseline.get("allowed") or []),
            "approvalRequired": list(baseline.get("approvalRequired") or []),
            "denied": list(baseline.get("denied") or []),
        },
        "candidate": {
            "allowed": list(candidate.get("allowed") or []),
            "approvalRequired": list(candidate.get("approvalRequired") or []),
            "denied": list(candidate.get("denied") or []),
        },
        "expandedPermissions": expanded,
        "reducedPermissions": reduced,
        "unchangedPermissions": unchanged,
        "newlyDeniedRequests": newly_denied,
        "gatePassed": not expanded,
        "reason": (
            "The candidate requests broader authority."
            if expanded
            else "The candidate stays within or narrows the active authority boundary."
        ),
    }


class NeyviaCapabilityEvolution:
    """Local evolution ledger shared by Constellation, Skills, and App Factory."""

    def __init__(
        self,
        root: str | Path,
        *,
        database_path: str | Path | None = None,
        hermes_import_dir: str | Path | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.database_path = (
            Path(database_path).expanduser().resolve()
            if database_path
            else self.root / ".agent_control" / "ecosystem.sqlite3"
        )
        self.hermes_import_dir = (
            Path(hermes_import_dir).expanduser().resolve()
            if hermes_import_dir
            else Path.home() / ".hermes" / "imported-state"
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS capability_lineages (
                    lineage_id TEXT PRIMARY KEY,
                    capability_id TEXT NOT NULL,
                    capability_kind TEXT NOT NULL,
                    label TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    parent_lineage_id TEXT,
                    state TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_capability_lineages_capability
                    ON capability_lineages(capability_id, capability_kind, updated_at DESC);

                CREATE TABLE IF NOT EXISTS capability_evolution_trials (
                    trial_id TEXT PRIMARY KEY,
                    lineage_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    capability_kind TEXT NOT NULL,
                    label TEXT NOT NULL,
                    action TEXT NOT NULL,
                    state TEXT NOT NULL,
                    title TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    context_json TEXT NOT NULL DEFAULT '{}',
                    baseline_json TEXT NOT NULL DEFAULT '{}',
                    candidate_json TEXT NOT NULL DEFAULT '{}',
                    success_contract_json TEXT NOT NULL DEFAULT '{}',
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    verdict_json TEXT NOT NULL DEFAULT '{}',
                    created_by TEXT NOT NULL DEFAULT 'operator',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(lineage_id) REFERENCES capability_lineages(lineage_id)
                );
                CREATE INDEX IF NOT EXISTS idx_capability_trials_recent
                    ON capability_evolution_trials(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_capability_trials_capability
                    ON capability_evolution_trials(capability_id, state, updated_at DESC);

                CREATE TABLE IF NOT EXISTS capability_observations (
                    observation_id TEXT PRIMARY KEY,
                    lineage_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    capability_kind TEXT NOT NULL,
                    mission_id TEXT NOT NULL DEFAULT '',
                    conversation_id TEXT NOT NULL DEFAULT '',
                    source_ref TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    accepted_by TEXT NOT NULL DEFAULT '',
                    measurements_json TEXT NOT NULL DEFAULT '{}',
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(source_ref, capability_id),
                    FOREIGN KEY(lineage_id) REFERENCES capability_lineages(lineage_id)
                );
                CREATE INDEX IF NOT EXISTS idx_capability_observations_capability
                    ON capability_observations(capability_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS capability_skill_materializations (
                    materialization_id TEXT PRIMARY KEY,
                    trial_id TEXT NOT NULL UNIQUE,
                    approved_lineage_id TEXT NOT NULL UNIQUE,
                    parent_lineage_id TEXT NOT NULL,
                    skill_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    package_path TEXT NOT NULL,
                    candidate_digest TEXT NOT NULL,
                    skill_sha256 TEXT NOT NULL,
                    metadata_sha256 TEXT NOT NULL,
                    rollback_json TEXT NOT NULL DEFAULT '{}',
                    receipt_json TEXT NOT NULL DEFAULT '{}',
                    materialized_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(trial_id) REFERENCES capability_evolution_trials(trial_id),
                    FOREIGN KEY(approved_lineage_id) REFERENCES capability_lineages(lineage_id)
                );
                CREATE INDEX IF NOT EXISTS idx_skill_materializations_recent
                    ON capability_skill_materializations(updated_at DESC);

                CREATE TABLE IF NOT EXISTS capability_proof_leases (
                    lease_id TEXT PRIMARY KEY,
                    materialization_id TEXT NOT NULL UNIQUE,
                    trial_id TEXT NOT NULL,
                    approved_lineage_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    skill_id TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    state TEXT NOT NULL,
                    contract_json TEXT NOT NULL DEFAULT '{}',
                    assessment_json TEXT NOT NULL DEFAULT '{}',
                    issued_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(materialization_id)
                        REFERENCES capability_skill_materializations(materialization_id),
                    FOREIGN KEY(trial_id)
                        REFERENCES capability_evolution_trials(trial_id),
                    FOREIGN KEY(approved_lineage_id)
                        REFERENCES capability_lineages(lineage_id)
                );
                CREATE INDEX IF NOT EXISTS idx_capability_proof_leases_recent
                    ON capability_proof_leases(updated_at DESC);

                CREATE TABLE IF NOT EXISTS capability_proof_lease_events (
                    event_id TEXT PRIMARY KEY,
                    lease_id TEXT NOT NULL,
                    materialization_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    state TEXT NOT NULL,
                    receipt_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(lease_id)
                        REFERENCES capability_proof_leases(lease_id)
                );
                CREATE INDEX IF NOT EXISTS idx_proof_lease_events_recent
                    ON capability_proof_lease_events(
                        materialization_id, created_at DESC
                    );
                """
            )
            connection.commit()

    def _ensure_lineage(
        self,
        connection: sqlite3.Connection,
        *,
        capability_id: str,
        capability_kind: str,
        label: str,
        origin: str,
        metadata: dict[str, Any] | None = None,
        parent_lineage_id: str = "",
        state: str = "active",
        lineage_id: str = "",
        now: str | None = None,
    ) -> str:
        if state not in LINEAGE_STATES:
            raise ValueError(f"unsupported lineage state: {state}")
        timestamp = now or utc_now()
        resolved_id = lineage_id or _stable_id(
            "lineage",
            origin,
            capability_kind,
            capability_id,
            parent_lineage_id or "root",
        )
        connection.execute(
            """
            INSERT INTO capability_lineages (
                lineage_id, capability_id, capability_kind, label, origin,
                parent_lineage_id, state, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(lineage_id) DO UPDATE SET
                label = excluded.label,
                state = CASE
                    WHEN capability_lineages.state IN ('retired', 'quarantined', 'superseded')
                    THEN capability_lineages.state
                    ELSE excluded.state
                END,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                resolved_id,
                capability_id,
                capability_kind,
                label,
                origin,
                parent_lineage_id or None,
                state,
                _json(metadata or {}),
                timestamp,
                timestamp,
            ),
        )
        return resolved_id

    @staticmethod
    def _catalog_rows(skill_catalog: dict[str, Any] | None) -> list[dict[str, Any]]:
        catalog = skill_catalog if isinstance(skill_catalog, dict) else {}
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for section, kind in (
            ("userInstalledSkills", "skill"),
            ("learnedSkills", "skill"),
            ("curatedPacks", "skill_pack"),
        ):
            for raw in catalog.get(section) or []:
                if not isinstance(raw, dict):
                    continue
                capability_id = str(
                    raw.get("skillId")
                    or raw.get("skill_id")
                    or raw.get("packId")
                    or raw.get("pack_id")
                    or raw.get("id")
                    or ""
                ).strip()
                if not capability_id:
                    continue
                identity = f"neyvia:{kind}:{capability_id}"
                if identity in seen:
                    continue
                seen.add(identity)
                feedback = (
                    dict(raw.get("feedbackSummary") or {})
                    if isinstance(raw.get("feedbackSummary"), dict)
                    else {}
                )
                evolution = (
                    dict(raw.get("evolutionSummary") or {})
                    if isinstance(raw.get("evolutionSummary"), dict)
                    else {}
                )
                operator_value = (
                    dict(feedback.get("operatorValue") or {})
                    if isinstance(feedback.get("operatorValue"), dict)
                    else {}
                )
                source_path = str(
                    raw.get("sourcePath")
                    or (
                        raw.get("source", {}).get("path")
                        if isinstance(raw.get("source"), dict)
                        else ""
                    )
                    or ""
                )
                source_digest = _source_digest(
                    source_path,
                    {
                        "skillId": capability_id,
                        "label": raw.get("label") or raw.get("name") or "",
                        "description": raw.get("description") or "",
                        "instructions": raw.get("instructions") or "",
                        "source": raw.get("source") or {},
                    },
                )
                rows.append(
                    {
                        "identity": identity,
                        "capabilityId": capability_id,
                        "capabilityKind": kind,
                        "label": str(raw.get("label") or raw.get("name") or capability_id),
                        "origin": "neyvia",
                        "source": section,
                        "sourcePath": source_path,
                        "sourceDigest": source_digest,
                        "state": str(evolution.get("state") or "new"),
                        "usageCount": _int(
                            evolution.get("usageCount", raw.get("usageCount", 0))
                        ),
                        "helpedCount": _int(
                            evolution.get("helpedCount", raw.get("helpedCount", 0))
                        ),
                        "revisionCount": _int(evolution.get("revisionCount", 0)),
                        "feedbackCount": _int(feedback.get("sliceCount", 0)),
                        "operatorValueSampleCount": _int(
                            evolution.get(
                                "operatorValueSampleCount",
                                operator_value.get("sampleCount", 0),
                            )
                        ),
                        "operatorValueAverage": _float(
                            evolution.get(
                                "operatorValueAverage",
                                operator_value.get("averageScore"),
                            )
                        ),
                        "latestSystemLoss": _float(feedback.get("latestSystemLoss")),
                        "latestImprovementScore": _float(
                            feedback.get("latestImprovementScore")
                        ),
                        "zeroImprovementStreak": _int(
                            feedback.get("zeroImprovementStreak", 0)
                        ),
                        "selectionState": str(
                            (feedback.get("selectionPolicy") or {}).get("state")
                            if isinstance(feedback.get("selectionPolicy"), dict)
                            else ""
                        ),
                        "trustPolicy": str(
                            evolution.get("trustPolicy")
                            or "Usage alone never raises trust."
                        ),
                        "evolution": evolution,
                        "feedback": feedback,
                    }
                )
        return rows

    def _hermes_rows(self) -> list[dict[str, Any]]:
        learned = _load_json_list(
            self.hermes_import_dir / "jbheaven-learned_skills.json"
        )
        usage = _load_json_list(self.hermes_import_dir / "jbheaven-skill_usage.json")
        feedback = _load_json_list(
            self.hermes_import_dir / "jbheaven-skill_feedback.json"
        )
        usage_by_skill: dict[str, list[dict[str, Any]]] = defaultdict(list)
        feedback_by_skill: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in usage:
            skill_id = str(item.get("skill_id") or item.get("skillId") or "").strip()
            if skill_id:
                usage_by_skill[skill_id].append(item)
        for item in feedback:
            skill_id = str(item.get("skillId") or item.get("skill_id") or "").strip()
            if skill_id:
                feedback_by_skill[skill_id].append(item)

        rows: list[dict[str, Any]] = []
        for raw in learned:
            skill_id = str(raw.get("skill_id") or raw.get("skillId") or "").strip()
            if not skill_id:
                continue
            skill_usage = usage_by_skill.get(skill_id, [])
            skill_feedback = sorted(
                feedback_by_skill.get(skill_id, []),
                key=lambda item: str(item.get("createdAt") or item.get("created_at") or ""),
            )
            zero_streak = 0
            for item in reversed(skill_feedback):
                score = _float(item.get("improvementScore"), 0.0) or 0.0
                if abs(score) > 0.05:
                    break
                zero_streak += 1
            latest_feedback = skill_feedback[-1] if skill_feedback else {}
            source_digest = _canonical_digest(
                {
                    "skillId": skill_id,
                    "label": raw.get("label") or "",
                    "description": raw.get("description") or "",
                    "promptHint": raw.get("prompt_hint")
                    or raw.get("promptHint")
                    or "",
                    "status": raw.get("status") or "",
                    "updatedAt": raw.get("updated_at")
                    or raw.get("updatedAt")
                    or "",
                }
            )
            rows.append(
                {
                    "identity": f"hermes:skill:{skill_id}",
                    "capabilityId": skill_id,
                    "capabilityKind": "skill",
                    "label": str(raw.get("label") or skill_id),
                    "origin": "hermes_import",
                    "source": "imported_verified_aggregates",
                    "sourcePath": "",
                    "sourceDigest": source_digest,
                    "state": str(raw.get("status") or "learned"),
                    "usageCount": len(skill_usage)
                    or _int(raw.get("usage_count", raw.get("usageCount", 0))),
                    "helpedCount": sum(
                        1 for item in skill_usage if bool(item.get("helped"))
                    ),
                    "revisionCount": 0,
                    "feedbackCount": len(skill_feedback),
                    "operatorValueSampleCount": 0,
                    "operatorValueAverage": None,
                    "latestSystemLoss": _float(
                        latest_feedback.get("systemLoss")
                    ),
                    "latestImprovementScore": _float(
                        latest_feedback.get("improvementScore")
                    ),
                    "zeroImprovementStreak": zero_streak,
                    "selectionState": str(
                        latest_feedback.get("nextAction") or ""
                    ),
                    "trustPolicy": (
                        "Imported usage is historical evidence, not permission to "
                        "raise Neyvia trust."
                    ),
                    "evolution": {},
                    "feedback": {
                        "sliceCount": len(skill_feedback),
                        "zeroImprovementStreak": zero_streak,
                    },
                }
            )
        return rows

    @staticmethod
    def _success_contract(action: str) -> dict[str, Any]:
        return {
            "schema": "neyvia.capability_trial_contract.v1",
            "requiredComparableRuns": 2 if action in {"branch", "repair", "merge"} else 1,
            "minOutcomeLift": 0.05,
            "maxProofRegression": 0.0,
            "requiredSignals": ["verification", "operator_value"],
            "counterfactualReviewRequired": action
            in COUNTERFACTUAL_REQUIRED_ACTIONS,
            "counterfactualCaseLimit": COUNTERFACTUAL_CASE_LIMIT,
            "humanApprovalRequired": True,
            "rollbackRequired": action
            in {"branch", "repair", "merge", "retire", "promote_to_app"},
        }

    @checked_action(check_recommendation)
    def _recommendation(self, row: dict[str, Any]) -> dict[str, Any]:
        capability_id = str(row["capabilityId"])
        label = str(row["label"])
        usage_count = _int(row.get("usageCount"))
        feedback_count = _int(row.get("feedbackCount"))
        revision_count = _int(row.get("revisionCount"))
        zero_streak = _int(row.get("zeroImprovementStreak"))
        latest_loss = _float(row.get("latestSystemLoss"))
        state = str(row.get("state") or "new")
        selection_state = str(row.get("selectionState") or "")
        operator_samples = _int(row.get("operatorValueSampleCount"))

        if (
            state == "needs_repair"
            or selection_state == "deprioritize"
            or (latest_loss is not None and latest_loss >= 0.55)
        ):
            action = "repair"
            title = f"Repair {label} before reuse"
            reason = (
                "Recent outcome evidence crossed the repair threshold, so routing "
                "should remain held until a clean comparison passes."
            )
            priority = 0
        elif zero_streak >= 2 and usage_count >= 3:
            action = "branch"
            title = f"Branch {label} for the context that repeats"
            reason = (
                f"{zero_streak} consecutive feedback slices reported no measurable "
                "lift. Repetition is stagnation evidence, not improvement."
            )
            priority = 1
        elif state == "proven" and operator_samples >= 2:
            action = "promote_to_app"
            title = f"Turn repeated {label} work into an app"
            reason = (
                "Verification and operator-value evidence support a reusable "
                "interface, while App Factory can preserve the skill lineage."
            )
            priority = 4
        elif usage_count or feedback_count or revision_count:
            action = "prove"
            title = f"Prove the next {label} revision"
            reason = (
                "There is reuse or version history, but not enough comparable "
                "operator-value evidence to raise trust."
            )
            priority = 2
        else:
            action = "prove"
            title = f"Give {label} its first bounded proof"
            reason = (
                "The capability is available but unmeasured. One accepted task can "
                "establish a truthful baseline without promoting it."
            )
            priority = 3

        contract = self._success_contract(action)
        proposal_id = _stable_id(
            "evolution",
            row.get("origin"),
            row.get("capabilityKind"),
            capability_id,
            action,
        )
        return {
            "proposalId": proposal_id,
            "capabilityId": capability_id,
            "capabilityKind": row.get("capabilityKind") or "skill",
            "label": label,
            "origin": row.get("origin") or "neyvia",
            "action": action,
            "title": title,
            "reason": reason,
            "priority": priority,
            "status": "suggested",
            "humanDecisionRequired": True,
            "evidenceSummary": {
                "usageCount": usage_count,
                "feedbackCount": feedback_count,
                "revisionCount": revision_count,
                "operatorValueSampleCount": operator_samples,
                "latestSystemLoss": latest_loss,
                "latestImprovementScore": _float(
                    row.get("latestImprovementScore")
                ),
                "zeroImprovementStreak": zero_streak,
            },
            "successContract": contract,
            "nextAction": (
                "Run a baseline/candidate comparison. Neyvia will not activate a "
                "change until the evidence contract passes and you approve it."
            ),
        }

    @staticmethod
    @checked_action(check_trial)
    def _trial_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "trialId": row["trial_id"],
            "lineageId": row["lineage_id"],
            "capabilityId": row["capability_id"],
            "capabilityKind": row["capability_kind"],
            "label": row["label"],
            "action": row["action"],
            "state": row["state"],
            "title": row["title"],
            "reason": row["reason"],
            "context": _decode(row["context_json"], {}),
            "baseline": _decode(row["baseline_json"], {}),
            "candidate": _decode(row["candidate_json"], {}),
            "successContract": _decode(row["success_contract_json"], {}),
            "evidence": _decode(row["evidence_json"], []),
            "verdict": _decode(row["verdict_json"], {}),
            "createdBy": row["created_by"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _lineage_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "lineageId": row["lineage_id"],
            "capabilityId": row["capability_id"],
            "capabilityKind": row["capability_kind"],
            "label": row["label"],
            "origin": row["origin"],
            "parentLineageId": row["parent_lineage_id"],
            "state": row["state"],
            "metadata": _decode(row["metadata_json"], {}),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    @checked_action(check_materialization)
    def _materialization_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema": SKILL_MATERIALIZATION_SCHEMA,
            "materializationId": row["materialization_id"],
            "trialId": row["trial_id"],
            "approvedLineageId": row["approved_lineage_id"],
            "parentLineageId": row["parent_lineage_id"],
            "skillId": row["skill_id"],
            "state": row["state"],
            "packagePath": row["package_path"],
            "candidateDigest": row["candidate_digest"],
            "skillSha256": row["skill_sha256"],
            "metadataSha256": row["metadata_sha256"],
            "rollback": _decode(row["rollback_json"], {}),
            "receipt": _decode(row["receipt_json"], {}),
            "materializedBy": row["materialized_by"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "candidateActivated": False,
        }

    @staticmethod
    def _proof_lease_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema": PROOF_LEASE_SCHEMA,
            "leaseId": row["lease_id"],
            "materializationId": row["materialization_id"],
            "trialId": row["trial_id"],
            "approvedLineageId": row["approved_lineage_id"],
            "capabilityId": row["capability_id"],
            "skillId": row["skill_id"],
            "revision": int(row["revision"]),
            "state": row["state"],
            "contract": _decode(row["contract_json"], {}),
            "assessment": _decode(row["assessment_json"], {}),
            "issuedBy": row["issued_by"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "candidateActivated": False,
            "transcriptsIncluded": False,
        }

    def _dependency_record(self, path_value: object) -> dict[str, Any]:
        path_text = str(path_value or "").strip().replace("\\", "/")
        if not path_text:
            raise ValueError("dependency paths cannot be empty")
        relative = Path(path_text)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(
                f"dependency path must stay inside the workspace: {path_text}"
            )
        raw_path = self.root.joinpath(*relative.parts)
        probe = self.root
        for part in relative.parts:
            probe = probe / part
            if probe.is_symlink():
                raise ValueError(
                    f"dependency paths cannot contain symlinks: {path_text}"
                )
        try:
            resolved = raw_path.resolve(strict=True)
            resolved.relative_to(self.root)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise ValueError(
                f"dependency file is missing or outside the workspace: {path_text}"
            ) from exc
        if not resolved.is_file():
            raise ValueError(f"dependency path is not a file: {path_text}")
        normalized = resolved.relative_to(self.root).as_posix()
        lowered_parts = {part.casefold() for part in Path(normalized).parts}
        if lowered_parts & PROOF_LEASE_EXCLUDED_PARTS:
            raise ValueError(
                f"dependency path enters a private or generated directory: {normalized}"
            )
        lowered_name = resolved.name.casefold()
        if (
            lowered_name == ".env"
            or any(lowered_name.endswith(suffix) for suffix in PROOF_LEASE_SECRET_SUFFIXES)
            or PROOF_LEASE_SECRET_NAME.search(lowered_name)
        ):
            raise ValueError(
                f"dependency path looks secret-bearing and cannot enter proof: {normalized}"
            )
        size = resolved.stat().st_size
        if size > PROOF_LEASE_MAX_DEPENDENCY_BYTES:
            raise ValueError(
                f"dependency file exceeds {PROOF_LEASE_MAX_DEPENDENCY_BYTES} bytes: "
                f"{normalized}"
            )
        digest = hashlib.sha256()
        with resolved.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return {
            "path": normalized,
            "sha256": digest.hexdigest(),
            "bytes": size,
        }

    def _dependency_records(self, values: object) -> list[dict[str, Any]]:
        if values is None or values == "":
            return []
        if not isinstance(values, list):
            raise ValueError("dependencyPaths must be a bounded list")
        if len(values) > PROOF_LEASE_MAX_DEPENDENCIES:
            raise ValueError(
                f"track at most {PROOF_LEASE_MAX_DEPENDENCIES} dependency files"
            )
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for value in values:
            record = self._dependency_record(value)
            if record["path"] in seen:
                continue
            seen.add(record["path"])
            records.append(record)
        return records

    def _dependency_assessment(
        self,
        expected: object,
    ) -> dict[str, Any]:
        rows = [
            dict(item)
            for item in expected or []
            if isinstance(item, dict) and item.get("path")
        ]
        if not rows:
            return {
                "status": "not_tracked",
                "trackedCount": 0,
                "changedPaths": [],
                "missingPaths": [],
                "reason": (
                    "No external dependency files were selected. Package, route, "
                    "platform, and review signals remain checked."
                ),
            }
        changed: list[str] = []
        missing: list[str] = []
        for row in rows[:PROOF_LEASE_MAX_DEPENDENCIES]:
            path = str(row.get("path") or "")
            try:
                current = self._dependency_record(path)
            except (ValueError, OSError):
                missing.append(path)
                continue
            if (
                current["sha256"] != str(row.get("sha256") or "")
                or current["bytes"] != _int(row.get("bytes"), -1)
            ):
                changed.append(path)
        status = "missing" if missing else "changed" if changed else "passed"
        return {
            "status": status,
            "trackedCount": len(rows),
            "changedPaths": changed,
            "missingPaths": missing,
            "reason": (
                "Tracked dependency files still match the renewed proof."
                if status == "passed"
                else "One or more tracked dependency files changed, disappeared or could not be read."
            ),
        }

    def _materialization_package_assessment(
        self,
        materialization: dict[str, Any],
    ) -> dict[str, Any]:
        package_path = Path(
            str(materialization.get("packagePath") or "")
        ).expanduser()
        try:
            resolved_package = package_path.resolve(strict=True)
            materializations_root = (
                self.root
                / ".agent_control"
                / "capability_materializations"
            ).resolve()
            resolved_package.relative_to(materializations_root)
            skill_path = resolved_package / "SKILL.md"
            metadata_path = resolved_package / "agents" / "openai.yaml"
            if (
                resolved_package.is_symlink()
                or skill_path.is_symlink()
                or metadata_path.is_symlink()
                or not skill_path.is_file()
                or not metadata_path.is_file()
            ):
                raise ValueError("the exact materialized package is missing")
            skill_sha256 = hashlib.sha256(skill_path.read_bytes()).hexdigest()
            metadata_sha256 = hashlib.sha256(
                metadata_path.read_bytes()
            ).hexdigest()
        except (OSError, ValueError):
            return {
                "status": "missing",
                "reason": "The exact materialized skill package is missing or unsafe.",
            }
        if (
            skill_sha256 != str(materialization.get("skillSha256") or "")
            or metadata_sha256
            != str(materialization.get("metadataSha256") or "")
        ):
            return {
                "status": "changed",
                "reason": "The materialized package bytes changed after approval.",
            }
        return {
            "status": "passed",
            "skillSha256": skill_sha256,
            "metadataSha256": metadata_sha256,
            "reason": "The exact approved package is present and unchanged.",
        }

    @staticmethod
    def _candidate_proof_routes(
        trial: dict[str, Any],
    ) -> list[dict[str, str]]:
        routes: list[dict[str, str]] = []
        seen: set[tuple[str, str, str, str]] = set()
        for run in trial.get("evidence") or []:
            if not isinstance(run, dict) or not run.get("constraintsPassed"):
                continue
            receipt_pair = (
                dict(run.get("receiptPair") or {})
                if isinstance(run.get("receiptPair"), dict)
                else {}
            )
            candidate = (
                dict(receipt_pair.get("candidate") or {})
                if isinstance(receipt_pair.get("candidate"), dict)
                else {}
            )
            route = {
                "runtime": _bounded_text(candidate.get("runtime"), 120),
                "provider": _bounded_text(candidate.get("provider"), 120),
                "model": _bounded_text(candidate.get("model"), 160),
                "receiptId": _bounded_text(candidate.get("receiptId"), 180),
                "receiptDigest": str(
                    candidate.get("receiptDigest") or ""
                ).strip(),
            }
            identity = (
                route["runtime"],
                route["provider"],
                route["model"],
                route["receiptDigest"],
            )
            if not route["runtime"] or not route["provider"] or identity in seen:
                continue
            seen.add(identity)
            routes.append(route)
        return routes[:12]

    @staticmethod
    def _candidate_authority_envelope(
        trial: dict[str, Any],
    ) -> dict[str, Any]:
        rank = {
            "absent": 0,
            "denied": 1,
            "approval_required": 2,
            "allowed": 3,
        }
        states: dict[str, str] = {}
        sample_digests: list[str] = []
        for run in trial.get("evidence") or []:
            if not isinstance(run, dict) or not run.get("constraintsPassed"):
                continue
            pair = (
                dict(run.get("receiptPair") or {})
                if isinstance(run.get("receiptPair"), dict)
                else {}
            )
            candidate = (
                dict(pair.get("candidate") or {})
                if isinstance(pair.get("candidate"), dict)
                else {}
            )
            authority = (
                dict(candidate.get("authority") or {})
                if isinstance(candidate.get("authority"), dict)
                else {}
            )
            if authority.get("recorded") is not True:
                continue
            sample_digests.append(_canonical_digest(authority))
            for permission in authority.get("denied") or []:
                key = str(permission or "").strip()
                if key and rank["denied"] > rank.get(states.get(key, "absent"), 0):
                    states[key] = "denied"
            for permission in authority.get("approvalRequired") or []:
                key = str(permission or "").strip()
                if (
                    key
                    and rank["approval_required"]
                    > rank.get(states.get(key, "absent"), 0)
                ):
                    states[key] = "approval_required"
            for permission in authority.get("allowed") or []:
                key = str(permission or "").strip()
                if key:
                    states[key] = "allowed"
        return {
            "recorded": bool(sample_digests),
            "allowed": sorted(
                key for key, state in states.items() if state == "allowed"
            ),
            "approvalRequired": sorted(
                key
                for key, state in states.items()
                if state == "approval_required"
            ),
            "denied": sorted(
                key for key, state in states.items() if state == "denied"
            ),
            "sampleDigests": sample_digests[:12],
        }

    @staticmethod
    def _lease_digest(contract: dict[str, Any]) -> str:
        stable = dict(contract)
        stable.pop("leaseDigest", None)
        return _canonical_digest(stable)

    @staticmethod
    def _provider_assessment(
        routes: object,
        provider_availability: dict[str, bool] | None,
    ) -> dict[str, Any]:
        rows = [dict(item) for item in routes or [] if isinstance(item, dict)]
        providers = sorted(
            {
                str(item.get("provider") or "").strip()
                for item in rows
                if str(item.get("provider") or "").strip()
            }
        )
        if not providers:
            return {
                "status": "missing",
                "providers": [],
                "unavailableProviders": [],
                "uncheckedProviders": [],
                "reason": "The accepted proof has no recorded provider route.",
            }
        availability = (
            dict(provider_availability)
            if isinstance(provider_availability, dict)
            else {}
        )
        unavailable = [
            provider
            for provider in providers
            if provider in availability and availability[provider] is False
        ]
        unchecked = [
            provider for provider in providers if provider not in availability
        ]
        status = (
            "unavailable"
            if unavailable
            else "not_checked"
            if unchecked
            else "passed"
        )
        return {
            "status": status,
            "providers": providers,
            "unavailableProviders": unavailable,
            "uncheckedProviders": unchecked,
            "reason": (
                "Every provider route used by the accepted proof is available."
                if status == "passed"
                else "One or more proof routes are unavailable."
                if status == "unavailable"
                else "Provider availability was not checked in this view."
            ),
        }

    @checked_action(check_lease)
    def _assess_proof_lease(
        self,
        lease: dict[str, Any],
        materialization: dict[str, Any],
        *,
        provider_availability: dict[str, bool] | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        assessed_at = now or utc_now()
        contract = (
            dict(lease.get("contract") or {})
            if isinstance(lease.get("contract"), dict)
            else {}
        )
        expected_digest = str(contract.get("leaseDigest") or "")
        contract_integrity = bool(
            expected_digest and self._lease_digest(contract) == expected_digest
        )
        package = self._materialization_package_assessment(materialization)
        dependencies = self._dependency_assessment(
            contract.get("dependencies") or []
        )
        provider = self._provider_assessment(
            contract.get("proofRoutes") or [],
            provider_availability,
        )
        expected_platform = (
            dict(contract.get("platform") or {})
            if isinstance(contract.get("platform"), dict)
            else {}
        )
        current_platform = _platform_contract()
        changed_platform_fields = [
            key
            for key in ("system", "machine", "python")
            if str(expected_platform.get(key) or "")
            != str(current_platform.get(key) or "")
        ]
        platform_signal = {
            "status": "changed" if changed_platform_fields else "passed",
            "changedFields": changed_platform_fields,
            "expected": expected_platform,
            "current": current_platform,
            "reason": (
                "The proof runtime family still matches."
                if not changed_platform_fields
                else "The operating system, machine family, or Python runtime changed."
            ),
        }
        review_at = _parse_utc(contract.get("reviewAt"))
        assessed_time = _parse_utc(assessed_at) or datetime.now(timezone.utc)
        review_due = bool(review_at and assessed_time >= review_at)
        review_signal = {
            "status": "due" if review_due else "current",
            "reviewAt": contract.get("reviewAt") or "",
            "issuedAt": contract.get("issuedAt") or "",
            "reason": (
                "The scheduled human review is due."
                if review_due
                else "The scheduled human review is still current."
            ),
        }
        prior_assessment = (
            dict(lease.get("assessment") or {})
            if isinstance(lease.get("assessment"), dict)
            else {}
        )
        manual_disposition = (
            dict(prior_assessment.get("manualDisposition") or {})
            if isinstance(prior_assessment.get("manualDisposition"), dict)
            else {}
        )
        persisted_state = str(lease.get("state") or "")
        goal_status = (
            "needs_repair"
            if persisted_state == "held"
            and manual_disposition.get("disposition") == "needs_repair"
            else "no_longer_needed"
            if persisted_state == "retirement_review"
            else "confirmed"
        )
        goal_signal = {
            "status": goal_status,
            "goalDigest": (
                (contract.get("goal") or {}).get("digest")
                if isinstance(contract.get("goal"), dict)
                else ""
            ),
            "reason": (
                "The operator marked this capability for repair."
                if goal_status == "needs_repair"
                else "The operator marked the goal as no longer needed."
                if goal_status == "no_longer_needed"
                else "The reviewed goal remains recorded."
            ),
        }

        if materialization.get("state") == "withdrawn":
            state = "withdrawn"
        elif (
            not contract_integrity
            or package["status"] != "passed"
            or provider["status"] in {"missing", "unavailable"}
            or persisted_state == "held"
        ):
            state = "held"
        elif persisted_state == "retirement_review":
            state = "retirement_review"
        elif (
            dependencies["status"] in {"changed", "missing"}
            or platform_signal["status"] == "changed"
        ):
            state = "reproof_required"
        elif review_due:
            state = "review_due"
        else:
            state = "current"

        next_actions = {
            "current": "No action now. Recheck at the scheduled review or when conditions change.",
            "review_due": "Confirm the goal still matters and renew from a fresh verified receipt.",
            "reproof_required": "Run one bounded verification under the changed conditions, then renew.",
            "held": (
                "Restore package integrity or provider access before promotion."
                if goal_status != "needs_repair"
                else "Open a bounded repair lineage. A receipt alone cannot clear this hold."
            ),
            "retirement_review": "Review replacement evidence before retiring this capability.",
            "withdrawn": "The inactive branch is withdrawn; its proof remains available for audit.",
        }
        return {
            "schema": PROOF_LEASE_REVIEW_SCHEMA,
            "leaseId": lease.get("leaseId") or "",
            "materializationId": materialization.get("materializationId") or "",
            "revision": _int(lease.get("revision"), 1),
            "state": state,
            "leaseDigest": expected_digest,
            "contractIntegrity": contract_integrity,
            "contractSummary": {
                "goalStatement": (
                    (contract.get("goal") or {}).get("statement")
                    if isinstance(contract.get("goal"), dict)
                    else ""
                ),
                "proofRoutes": [
                    {
                        "runtime": item.get("runtime") or "",
                        "provider": item.get("provider") or "",
                        "model": item.get("model") or "",
                    }
                    for item in contract.get("proofRoutes") or []
                    if isinstance(item, dict)
                ],
                "dependencyPaths": [
                    item.get("path") or ""
                    for item in contract.get("dependencies") or []
                    if isinstance(item, dict)
                ],
                "reviewAfterDays": _int(
                    contract.get("reviewAfterDays"),
                    0,
                ),
                "reviewAt": contract.get("reviewAt") or "",
            },
            "signals": {
                "package": package,
                "provider": provider,
                "dependencies": dependencies,
                "platform": platform_signal,
                "review": review_signal,
                "goal": goal_signal,
            },
            "nextAction": next_actions[state],
            "canRenew": state in {
                "review_due",
                "reproof_required",
                "retirement_review",
            },
            "canPromoteToApp": state == "current",
            "assessedAt": assessed_at,
            "candidateActivated": False,
            "transcriptsIncluded": False,
        }

    @staticmethod
    def _app_factory_job_handoff(job: object) -> dict[str, Any]:
        if not isinstance(job, dict):
            return {}
        handoff = job.get("capabilityHandoff")
        if not isinstance(handoff, dict):
            return {}
        if handoff.get("schema") != APP_FACTORY_HANDOFF_SCHEMA:
            return {}
        return dict(handoff)

    @classmethod
    def _app_factory_handoff_reviews_from_records(
        cls,
        *,
        trials: list[dict[str, Any]],
        materializations: list[dict[str, Any]],
        app_factory_jobs: list[dict[str, Any]] | None = None,
        proof_lease_reviews: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        trial_by_id = {str(item.get("trialId") or ""): item for item in trials}
        jobs_by_materialization: dict[str, dict[str, Any]] = {}
        for job in app_factory_jobs or []:
            handoff = cls._app_factory_job_handoff(job)
            materialization_id = str(
                handoff.get("materializationId") or ""
            ).strip()
            if materialization_id and materialization_id not in jobs_by_materialization:
                jobs_by_materialization[materialization_id] = job

        reviews: list[dict[str, Any]] = []
        for materialization in materializations:
            trial = trial_by_id.get(str(materialization.get("trialId") or ""))
            if not trial or trial.get("state") != "accepted":
                continue
            candidate = (
                dict(trial.get("candidate") or {})
                if isinstance(trial.get("candidate"), dict)
                else {}
            )
            if not _is_sealed_skill_candidate(candidate):
                continue
            verdict = (
                dict(trial.get("verdict") or {})
                if isinstance(trial.get("verdict"), dict)
                else {}
            )
            forge = (
                dict(verdict.get("counterfactualForge") or {})
                if isinstance(verdict.get("counterfactualForge"), dict)
                else {}
            )
            job = jobs_by_materialization.get(
                str(materialization.get("materializationId") or "")
            )
            job_handoff = cls._app_factory_job_handoff(job)
            source_state = str(materialization.get("state") or "")
            proof_lease = (proof_lease_reviews or {}).get(
                str(materialization.get("materializationId") or "")
            ) or {}
            lease_current = proof_lease.get("state") == "current"
            current_lease_digest = str(
                proof_lease.get("leaseDigest") or ""
            )
            job_proof_lease = (
                dict(job_handoff.get("proofLease") or {})
                if isinstance(job_handoff.get("proofLease"), dict)
                else {}
            )
            job_lease_current = bool(
                lease_current
                and current_lease_digest
                and job_proof_lease.get("leaseDigest")
                == current_lease_digest
            )
            if source_state == "withdrawn":
                state = "source_withdrawn"
            elif job:
                verification = (
                    dict(job.get("verification") or {})
                    if isinstance(job.get("verification"), dict)
                    else {}
                )
                registration = (
                    dict(job.get("registration") or {})
                    if isinstance(job.get("registration"), dict)
                    else {}
                )
                if (
                    verification.get("state") == "passed"
                    and registration.get("state") == "draft-ready"
                ):
                    state = (
                        "draft_ready"
                        if job_lease_current
                        else "draft_maintenance_due"
                    )
                elif str(job.get("status") or "") in {
                    "failed",
                    "needs_attention",
                }:
                    state = "needs_attention"
                else:
                    state = "building"
            elif not proof_lease or proof_lease.get("state") == "unestablished":
                state = "proof_lease_required"
            elif not lease_current:
                state = "maintenance_required"
            else:
                state = "review_required"

            label = _bounded_text(trial.get("label") or materialization["skillId"], 80)
            suggested_name = (
                label
                if label.casefold().endswith((" app", " workbench"))
                else f"{label} Workbench"
            )[:80]
            suggested_brief = _bounded_text(
                "Guide the sealed "
                f"{label} workflow step by step, keep completed runs on this "
                "device, and export portable proof receipts.",
                900,
            )
            app_job = None
            if job:
                app_job = {
                    "jobId": job.get("jobId") or "",
                    "status": job.get("status") or "",
                    "currentStage": job.get("currentStage") or "",
                    "projectRoot": job.get("projectRoot") or "",
                    "previewUrl": job.get("previewUrl") or "",
                    "spec": job.get("spec") or {},
                    "verification": job.get("verification") or {},
                    "registration": job.get("registration") or {},
                    "package": job.get("package") or {},
                    "nativeBuild": job.get("nativeBuild") or {},
                }
            reviews.append(
                {
                    "schema": APP_FACTORY_HANDOFF_REVIEW_SCHEMA,
                    "handoffId": job_handoff.get("handoffId")
                    or _stable_id(
                        "app_factory_handoff",
                        materialization.get("materializationId"),
                        materialization.get("candidateDigest"),
                        current_lease_digest or "lease-unestablished",
                    ),
                    "state": state,
                    "sourceState": source_state,
                    "materializationId": materialization["materializationId"],
                    "trialId": trial["trialId"],
                    "approvedLineageId": materialization["approvedLineageId"],
                    "parentLineageId": materialization["parentLineageId"],
                    "skillId": materialization["skillId"],
                    "label": label,
                    "candidateDigest": materialization["candidateDigest"],
                    "candidateActivated": False,
                    "appActivated": False,
                    "proofLease": proof_lease,
                    "suggestedApp": {
                        "name": suggested_name,
                        "brief": suggested_brief,
                        "target": "desktop",
                        "template": "capability",
                        "theme": "midnight",
                        "directory": f"apps/{_skill_slug(suggested_name)}",
                    },
                    "evidenceSummary": {
                        "comparableRunCount": _int(
                            verdict.get("comparableRunCount")
                        ),
                        "qualifyingRunCount": _int(
                            verdict.get("qualifyingRunCount")
                        ),
                        "averageOutcomeLift": _float(
                            verdict.get("averageOutcomeLift")
                        ),
                        "forgeId": forge.get("forgeId") or "",
                        "scorecard": forge.get("scorecard") or {},
                        "authorityComparison": forge.get(
                            "authorityComparison"
                        )
                        or {},
                        "transcriptsIncluded": False,
                    },
                    "canCreateApp": bool(
                        source_state == "materialized_inactive"
                        and lease_current
                        and not job
                    ),
                    "appFactoryJob": app_job,
                    "rule": (
                        "A local app draft may inherit only this exact inactive "
                        "package while its digest-bound proof lease is current. "
                        "Draft creation does not install the skill, publish the "
                        "app, or activate either."
                    ),
                }
            )
        reviews.sort(
            key=lambda item: (
                0 if item["state"] == "review_required" else 1,
                str(item.get("label") or "").casefold(),
            )
        )
        return reviews

    def app_factory_handoff_reviews(
        self,
        *,
        app_factory_jobs: list[dict[str, Any]] | None = None,
        provider_availability: dict[str, bool] | None = None,
    ) -> list[dict[str, Any]]:
        with self._connection() as connection:
            trial_rows = connection.execute(
                """
                SELECT * FROM capability_evolution_trials
                ORDER BY updated_at DESC, trial_id DESC
                LIMIT 80
                """
            ).fetchall()
            materialization_rows = connection.execute(
                """
                SELECT * FROM capability_skill_materializations
                ORDER BY updated_at DESC, materialization_id DESC
                LIMIT 80
                """
            ).fetchall()
            lease_rows = connection.execute(
                """
                SELECT * FROM capability_proof_leases
                ORDER BY updated_at DESC, lease_id DESC
                LIMIT 80
                """
            ).fetchall()
            app_observation_rows = connection.execute(
                """
                SELECT * FROM capability_observations
                WHERE source_kind = 'app_run'
                ORDER BY created_at DESC, observation_id DESC
                LIMIT 1000
                """
            ).fetchall()
        materializations = [
            self._materialization_from_row(row)
            for row in materialization_rows
        ]
        materialization_by_id = {
            item["materializationId"]: item for item in materializations
        }
        proof_lease_reviews: dict[str, dict[str, Any]] = {}
        for row in lease_rows:
            lease = self._proof_lease_from_row(row)
            materialization = materialization_by_id.get(
                lease["materializationId"]
            )
            if materialization:
                proof_lease_reviews[lease["materializationId"]] = (
                    self._assess_proof_lease(
                        lease,
                        materialization,
                        provider_availability=provider_availability,
                    )
                )
        for materialization in materializations:
            proof_lease_reviews.setdefault(
                materialization["materializationId"],
                self._unestablished_lease_review(materialization),
            )
        return self._app_factory_handoff_reviews_from_records(
            trials=[self._trial_from_row(row) for row in trial_rows],
            materializations=materializations,
            app_factory_jobs=app_factory_jobs,
            proof_lease_reviews=proof_lease_reviews,
        )

    def _lease_context(
        self,
        connection: sqlite3.Connection,
        materialization_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
        materialization_row = connection.execute(
            """
            SELECT * FROM capability_skill_materializations
            WHERE materialization_id = ?
            """,
            (_bounded_text(materialization_id, 180),),
        ).fetchone()
        if not materialization_row:
            raise KeyError(materialization_id)
        materialization = self._materialization_from_row(
            materialization_row
        )
        trial_row = connection.execute(
            """
            SELECT * FROM capability_evolution_trials
            WHERE trial_id = ?
            """,
            (materialization["trialId"],),
        ).fetchone()
        if not trial_row:
            raise ValueError("the source evolution trial is missing")
        lease_row = connection.execute(
            """
            SELECT * FROM capability_proof_leases
            WHERE materialization_id = ?
            """,
            (materialization["materializationId"],),
        ).fetchone()
        return (
            materialization,
            self._trial_from_row(trial_row),
            self._proof_lease_from_row(lease_row) if lease_row else None,
        )

    def _unestablished_lease_review(
        self,
        materialization: dict[str, Any],
    ) -> dict[str, Any]:
        package = self._materialization_package_assessment(materialization)
        eligible = bool(
            materialization.get("state") == "materialized_inactive"
            and package["status"] == "passed"
        )
        return {
            "schema": PROOF_LEASE_REVIEW_SCHEMA,
            "leaseId": "",
            "materializationId": materialization.get("materializationId") or "",
            "revision": 0,
            "state": (
                "unestablished"
                if materialization.get("state") == "materialized_inactive"
                else "withdrawn"
            ),
            "leaseDigest": "",
            "contractIntegrity": False,
            "signals": {
                "package": package,
                "provider": {
                    "status": "not_bound",
                    "providers": [],
                    "reason": "Provider routes will be bound from accepted receipts.",
                },
                "dependencies": {
                    "status": "not_bound",
                    "trackedCount": 0,
                    "reason": "Choose only non-secret workspace files that affect this skill.",
                },
                "platform": {
                    "status": "not_bound",
                    "current": _platform_contract(),
                    "reason": "The current runtime family will be sealed into the lease.",
                },
                "review": {
                    "status": "not_scheduled",
                    "reason": "Choose a bounded human review window.",
                },
                "goal": {
                    "status": "not_confirmed",
                    "reason": "State the user outcome this capability must keep serving.",
                },
            },
            "nextAction": (
                "Bind the proven package to its goal, environment, dependencies, "
                "and next review."
                if eligible
                else "Restore the exact inactive package before establishing proof."
            ),
            "canEstablish": eligible,
            "canRenew": False,
            "canPromoteToApp": False,
            "assessedAt": utc_now(),
            "candidateActivated": False,
            "transcriptsIncluded": False,
        }

    def assess_capability_proof_lease(
        self,
        materialization_id: str,
        *,
        provider_availability: dict[str, bool] | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        with self._connection() as connection:
            materialization, _, lease = self._lease_context(
                connection,
                materialization_id,
            )
        if lease is None:
            return self._unestablished_lease_review(materialization)
        return self._assess_proof_lease(
            lease,
            materialization,
            provider_availability=provider_availability,
            now=now,
        )

    def establish_capability_proof_lease(
        self,
        materialization_id: str,
        *,
        goal_statement: str,
        dependency_paths: list[str] | None = None,
        review_after_days: int = 30,
        review_confirmed: bool = False,
        issued_by: str = "operator",
        provider_availability: dict[str, bool] | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        if not review_confirmed:
            raise ValueError(
                "confirm the goal, exact package, proof routes, dependencies, "
                "and review window"
            )
        goal = _bounded_text(goal_statement, 800)
        if len(goal) < 12:
            raise ValueError(
                "goalStatement must describe the user outcome in at least 12 characters"
            )
        days = _int(review_after_days)
        if not PROOF_LEASE_MIN_REVIEW_DAYS <= days <= PROOF_LEASE_MAX_REVIEW_DAYS:
            raise ValueError(
                "reviewAfterDays must be between "
                f"{PROOF_LEASE_MIN_REVIEW_DAYS} and "
                f"{PROOF_LEASE_MAX_REVIEW_DAYS}"
            )
        dependencies = self._dependency_records(dependency_paths or [])
        timestamp = now or utc_now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            materialization, trial, existing = self._lease_context(
                connection,
                materialization_id,
            )
            if materialization["state"] != "materialized_inactive":
                raise ValueError(
                    "only an inactive, non-withdrawn skill branch can receive a proof lease"
                )
            if trial["state"] != "accepted":
                raise ValueError("the source evolution trial is no longer accepted")
            candidate = (
                dict(trial.get("candidate") or {})
                if isinstance(trial.get("candidate"), dict)
                else {}
            )
            verdict = (
                dict(trial.get("verdict") or {})
                if isinstance(trial.get("verdict"), dict)
                else {}
            )
            forge = (
                dict(verdict.get("counterfactualForge") or {})
                if isinstance(verdict.get("counterfactualForge"), dict)
                else {}
            )
            authority_comparison = (
                dict(forge.get("authorityComparison") or {})
                if isinstance(forge.get("authorityComparison"), dict)
                else {}
            )
            if (
                not _is_sealed_skill_candidate(candidate)
                or candidate.get("packageDigest")
                != materialization["candidateDigest"]
                or forge.get("schema") != COUNTERFACTUAL_FORGE_SCHEMA
                or forge.get("reviewGatePassed") is not True
                or forge.get("candidatePackageDigest")
                != materialization["candidateDigest"]
                or authority_comparison.get("status") == "expanded"
                or forge.get("transcriptsIncluded") is not False
            ):
                raise ValueError(
                    "the source trial no longer proves an exact, authority-bounded package"
                )
            package = self._materialization_package_assessment(materialization)
            if package["status"] != "passed":
                raise ValueError(package["reason"])
            routes = self._candidate_proof_routes(trial)
            authority_envelope = self._candidate_authority_envelope(trial)
            if not routes or authority_envelope.get("recorded") is not True:
                raise ValueError(
                    "accepted candidate receipts must preserve provider routes and authority"
                )
            if existing:
                current_contract = (
                    dict(existing.get("contract") or {})
                    if isinstance(existing.get("contract"), dict)
                    else {}
                )
                same_request = bool(
                    (current_contract.get("goal") or {}).get("statement")
                    == goal
                    and current_contract.get("dependencies") == dependencies
                    and _int(current_contract.get("reviewAfterDays")) == days
                )
                if not same_request:
                    raise ValueError(
                        "a proof lease already exists; renew it instead of replacing its history"
                    )
                connection.rollback()
                return self._assess_proof_lease(
                    existing,
                    materialization,
                    provider_availability=provider_availability,
                    now=timestamp,
                )

            lease_id = _stable_id(
                "proof_lease",
                materialization["materializationId"],
                materialization["candidateDigest"],
            )
            contract = {
                "schema": PROOF_LEASE_SCHEMA,
                "leaseId": lease_id,
                "materializationId": materialization["materializationId"],
                "trialId": materialization["trialId"],
                "approvedLineageId": materialization["approvedLineageId"],
                "capabilityId": trial["capabilityId"],
                "skillId": materialization["skillId"],
                "revision": 1,
                "candidateDigest": materialization["candidateDigest"],
                "skillSha256": materialization["skillSha256"],
                "metadataSha256": materialization["metadataSha256"],
                "forgeId": forge.get("forgeId") or "",
                "forgeDigest": _canonical_digest(forge),
                "successContractDigest": _canonical_digest(
                    trial.get("successContract") or {}
                ),
                "goal": {
                    "statement": goal,
                    "digest": _canonical_digest(
                        {"schema": "neyvia.capability_goal.v1", "statement": goal}
                    ),
                },
                "proofRoutes": routes,
                "proofRoutesDigest": _canonical_digest(routes),
                "authorityEnvelope": authority_envelope,
                "authorityEnvelopeDigest": _canonical_digest(
                    authority_envelope
                ),
                "dependencies": dependencies,
                "dependenciesDigest": _canonical_digest(dependencies),
                "platform": _platform_contract(),
                "reviewAfterDays": days,
                "issuedAt": timestamp,
                "reviewAt": _utc_after(timestamp, days=days),
                "candidateActivated": False,
                "transcriptsIncluded": False,
            }
            contract["leaseDigest"] = self._lease_digest(contract)
            lease = {
                "schema": PROOF_LEASE_SCHEMA,
                "leaseId": lease_id,
                "materializationId": materialization["materializationId"],
                "trialId": materialization["trialId"],
                "approvedLineageId": materialization["approvedLineageId"],
                "capabilityId": trial["capabilityId"],
                "skillId": materialization["skillId"],
                "revision": 1,
                "state": "current",
                "contract": contract,
                "assessment": {},
                "issuedBy": _bounded_text(issued_by or "operator", 80),
                "createdAt": timestamp,
                "updatedAt": timestamp,
            }
            assessment = self._assess_proof_lease(
                lease,
                materialization,
                provider_availability=provider_availability,
                now=timestamp,
            )
            if assessment["state"] != "current":
                raise ValueError(
                    "the proof lease is not current: "
                    f"{assessment['nextAction']}"
                )
            connection.execute(
                """
                INSERT INTO capability_proof_leases (
                    lease_id, materialization_id, trial_id,
                    approved_lineage_id, capability_id, skill_id,
                    revision, state, contract_json, assessment_json,
                    issued_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, 'current', ?, ?, ?, ?, ?)
                """,
                (
                    lease_id,
                    materialization["materializationId"],
                    materialization["trialId"],
                    materialization["approvedLineageId"],
                    trial["capabilityId"],
                    materialization["skillId"],
                    _json(contract),
                    _json(assessment),
                    _bounded_text(issued_by or "operator", 80),
                    timestamp,
                    timestamp,
                ),
            )
            event = {
                "schema": PROOF_LEASE_EVENT_SCHEMA,
                "leaseId": lease_id,
                "materializationId": materialization["materializationId"],
                "kind": "established",
                "revision": 1,
                "state": "current",
                "leaseDigest": contract["leaseDigest"],
                "goalDigest": contract["goal"]["digest"],
                "dependenciesDigest": contract["dependenciesDigest"],
                "proofRoutesDigest": contract["proofRoutesDigest"],
                "reviewAt": contract["reviewAt"],
                "candidateActivated": False,
                "transcriptsIncluded": False,
            }
            connection.execute(
                """
                INSERT INTO capability_proof_lease_events (
                    event_id, lease_id, materialization_id, kind,
                    state, receipt_json, created_at
                ) VALUES (?, ?, ?, 'established', 'current', ?, ?)
                """,
                (
                    _new_id("proof_lease_event"),
                    lease_id,
                    materialization["materializationId"],
                    _json(event),
                    timestamp,
                ),
            )
            connection.commit()
        return assessment

    def renew_capability_proof_lease(
        self,
        materialization_id: str,
        *,
        candidate_digest: str,
        receipt_record: dict[str, Any],
        goal_still_matches: bool = False,
        operator_value: str = "",
        review_confirmed: bool = False,
        renewed_by: str = "operator",
        provider_availability: dict[str, bool] | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        if not review_confirmed:
            raise ValueError(
                "confirm the exact package, fresh receipt, goal, authority, and review window"
            )
        if goal_still_matches is not True:
            raise ValueError("confirm that the recorded goal still matches")
        if _normalized_status(operator_value) != "still_useful":
            raise ValueError("operatorValue must be still_useful")
        timestamp = now or utc_now()
        measurement = self._receipt_measurement(receipt_record)
        if not measurement["eligible"] or not measurement["verificationPassed"]:
            raise ValueError(
                "renewal requires a fresh ledger-resolved receipt with passing verification"
            )
        if measurement.get("authorityRecorded") is not True:
            raise ValueError(
                "renewal requires a receipt with a recorded authority boundary"
            )

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            materialization, trial, lease = self._lease_context(
                connection,
                materialization_id,
            )
            if lease is None:
                raise ValueError(
                    "establish the first proof lease before attempting renewal"
                )
            if (
                materialization["state"] != "materialized_inactive"
                or trial["state"] != "accepted"
            ):
                raise ValueError(
                    "only an accepted, materialized-inactive branch can renew proof"
                )
            expected_digest = str(candidate_digest or "").strip()
            if expected_digest != materialization["candidateDigest"]:
                raise ValueError(
                    "candidate digest changed after review; refresh before renewal"
                )
            prior_assessment = (
                dict(lease.get("assessment") or {})
                if isinstance(lease.get("assessment"), dict)
                else {}
            )
            manual_disposition = (
                dict(prior_assessment.get("manualDisposition") or {})
                if isinstance(prior_assessment.get("manualDisposition"), dict)
                else {}
            )
            if (
                lease.get("state") == "held"
                and manual_disposition.get("disposition") == "needs_repair"
            ):
                raise ValueError(
                    "a repair disposition requires a new bounded lineage; "
                    "a receipt alone cannot clear it"
                )
            package = self._materialization_package_assessment(
                materialization
            )
            if package["status"] != "passed":
                raise ValueError(package["reason"])
            prior_contract = (
                dict(lease.get("contract") or {})
                if isinstance(lease.get("contract"), dict)
                else {}
            )
            receipt_time = _parse_utc(measurement.get("createdAt"))
            issued_time = _parse_utc(prior_contract.get("issuedAt"))
            if (
                receipt_time is None
                or issued_time is None
                or receipt_time <= issued_time
            ):
                raise ValueError(
                    "renewal receipt must be newer than the current proof lease"
                )
            prior_renewal = (
                dict(prior_contract.get("renewalReceipt") or {})
                if isinstance(
                    prior_contract.get("renewalReceipt"),
                    dict,
                )
                else {}
            )
            if prior_renewal.get("receiptId") == measurement["receiptId"]:
                raise ValueError(
                    "the same receipt cannot renew a proof lease twice"
                )
            authority_envelope = (
                dict(prior_contract.get("authorityEnvelope") or {})
                if isinstance(
                    prior_contract.get("authorityEnvelope"),
                    dict,
                )
                else {}
            )
            authority_delta = _authority_delta(
                authority_envelope,
                dict(measurement.get("authority") or {}),
            )
            if (
                authority_delta.get("recorded") is not True
                or authority_delta.get("gatePassed") is not True
                or authority_delta.get("status") == "expanded"
            ):
                raise ValueError(
                    "the fresh receipt expands or omits the approved authority boundary"
                )
            dependency_paths = [
                str(item.get("path") or "")
                for item in prior_contract.get("dependencies") or []
                if isinstance(item, dict) and item.get("path")
            ]
            dependencies = self._dependency_records(dependency_paths)
            next_revision = _int(lease.get("revision"), 1) + 1
            route = {
                "runtime": measurement["runtime"],
                "provider": measurement["provider"],
                "model": measurement["model"],
                "receiptId": measurement["receiptId"],
                "receiptDigest": measurement["receiptDigest"],
            }
            if not route["runtime"] or not route["provider"]:
                raise ValueError(
                    "the fresh receipt does not identify its runtime and provider"
                )
            next_authority = dict(measurement["authority"])
            next_authority["sampleDigests"] = [
                _canonical_digest(measurement["authority"])
            ]
            days = _int(
                prior_contract.get("reviewAfterDays"),
                30,
            )
            next_contract = {
                **prior_contract,
                "revision": next_revision,
                "proofRoutes": [route],
                "proofRoutesDigest": _canonical_digest([route]),
                "authorityEnvelope": next_authority,
                "authorityEnvelopeDigest": _canonical_digest(
                    next_authority
                ),
                "dependencies": dependencies,
                "dependenciesDigest": _canonical_digest(dependencies),
                "platform": _platform_contract(),
                "issuedAt": timestamp,
                "reviewAt": _utc_after(timestamp, days=days),
                "previousLeaseDigest": prior_contract.get("leaseDigest") or "",
                "renewalReceipt": {
                    "receiptId": measurement["receiptId"],
                    "receiptDigest": measurement["receiptDigest"],
                    "turnId": measurement["turnId"],
                    "conversationId": measurement["conversationId"],
                    "verificationStatus": measurement["verificationStatus"],
                    "proofQuality": measurement["proofQuality"],
                    "authorityDelta": authority_delta,
                    "candidateDigest": materialization["candidateDigest"],
                    "transcriptsIncluded": False,
                },
                "candidateActivated": False,
                "transcriptsIncluded": False,
            }
            next_contract.pop("leaseDigest", None)
            next_contract["leaseDigest"] = self._lease_digest(next_contract)
            next_lease = {
                **lease,
                "revision": next_revision,
                "state": "current",
                "contract": next_contract,
                "assessment": {},
                "issuedBy": _bounded_text(renewed_by or "operator", 80),
                "updatedAt": timestamp,
            }
            assessment = self._assess_proof_lease(
                next_lease,
                materialization,
                provider_availability=provider_availability,
                now=timestamp,
            )
            if assessment["state"] != "current":
                raise ValueError(
                    "the renewed proof is not current: "
                    f"{assessment['nextAction']}"
                )
            connection.execute(
                """
                UPDATE capability_proof_leases
                SET revision = ?, state = 'current', contract_json = ?,
                    assessment_json = ?, issued_by = ?, updated_at = ?
                WHERE lease_id = ?
                """,
                (
                    next_revision,
                    _json(next_contract),
                    _json(assessment),
                    _bounded_text(renewed_by or "operator", 80),
                    timestamp,
                    lease["leaseId"],
                ),
            )
            event = {
                "schema": PROOF_LEASE_EVENT_SCHEMA,
                "leaseId": lease["leaseId"],
                "materializationId": materialization["materializationId"],
                "kind": "renewed",
                "revision": next_revision,
                "state": "current",
                "previousLeaseDigest": prior_contract.get("leaseDigest") or "",
                "leaseDigest": next_contract["leaseDigest"],
                "receiptId": measurement["receiptId"],
                "receiptDigest": measurement["receiptDigest"],
                "authorityDelta": authority_delta,
                "dependenciesDigest": next_contract["dependenciesDigest"],
                "reviewAt": next_contract["reviewAt"],
                "candidateActivated": False,
                "transcriptsIncluded": False,
            }
            connection.execute(
                """
                INSERT INTO capability_proof_lease_events (
                    event_id, lease_id, materialization_id, kind,
                    state, receipt_json, created_at
                ) VALUES (?, ?, ?, 'renewed', 'current', ?, ?)
                """,
                (
                    _new_id("proof_lease_event"),
                    lease["leaseId"],
                    materialization["materializationId"],
                    _json(event),
                    timestamp,
                ),
            )
            connection.commit()
        return assessment

    def record_capability_proof_lease_disposition(
        self,
        materialization_id: str,
        *,
        disposition: str,
        review_confirmed: bool = False,
        note: str = "",
        recorded_by: str = "operator",
        now: str | None = None,
    ) -> dict[str, Any]:
        if not review_confirmed:
            raise ValueError(
                "confirm the repair or retirement-review disposition"
            )
        normalized = _normalized_status(disposition)
        if normalized not in PROOF_LEASE_DISPOSITIONS:
            raise ValueError(
                "disposition must be needs_repair or no_longer_needed"
            )
        timestamp = now or utc_now()
        next_state = (
            "held" if normalized == "needs_repair" else "retirement_review"
        )
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            materialization, _, lease = self._lease_context(
                connection,
                materialization_id,
            )
            if lease is None:
                raise ValueError(
                    "establish proof before recording a maintenance disposition"
                )
            if materialization["state"] != "materialized_inactive":
                raise ValueError(
                    "the inactive branch is no longer eligible for maintenance review"
                )
            manual = {
                "disposition": normalized,
                "note": _bounded_text(note, 1000),
                "recordedBy": _bounded_text(recorded_by or "operator", 80),
                "recordedAt": timestamp,
                "candidateActivated": False,
            }
            stored_assessment = (
                dict(lease.get("assessment") or {})
                if isinstance(lease.get("assessment"), dict)
                else {}
            )
            stored_assessment["manualDisposition"] = manual
            connection.execute(
                """
                UPDATE capability_proof_leases
                SET state = ?, assessment_json = ?, updated_at = ?
                WHERE lease_id = ?
                """,
                (
                    next_state,
                    _json(stored_assessment),
                    timestamp,
                    lease["leaseId"],
                ),
            )
            event = {
                "schema": PROOF_LEASE_EVENT_SCHEMA,
                "leaseId": lease["leaseId"],
                "materializationId": materialization["materializationId"],
                "kind": "disposition_recorded",
                "revision": lease["revision"],
                "state": next_state,
                "leaseDigest": (
                    (lease.get("contract") or {}).get("leaseDigest")
                    if isinstance(lease.get("contract"), dict)
                    else ""
                ),
                "manualDisposition": manual,
                "candidateActivated": False,
                "transcriptsIncluded": False,
            }
            connection.execute(
                """
                INSERT INTO capability_proof_lease_events (
                    event_id, lease_id, materialization_id, kind,
                    state, receipt_json, created_at
                ) VALUES (?, ?, ?, 'disposition_recorded', ?, ?, ?)
                """,
                (
                    _new_id("proof_lease_event"),
                    lease["leaseId"],
                    materialization["materializationId"],
                    next_state,
                    _json(event),
                    timestamp,
                ),
            )
            connection.commit()
        return self.assess_capability_proof_lease(
            materialization["materializationId"],
            now=timestamp,
        )

    @staticmethod
    def _receipt_measurement(record: dict[str, Any]) -> dict[str, Any]:
        receipt = (
            dict(record.get("receipt") or {})
            if isinstance(record.get("receipt"), dict)
            else {}
        )
        turn_id = _bounded_text(record.get("turnId"), 180)
        conversation_id = _bounded_text(record.get("conversationId"), 180)
        schema_valid = receipt.get("schema") == TURN_RECEIPT_SCHEMA
        status = _normalized_status(receipt.get("status"))
        success = status in RECEIPT_SUCCESS_STATUSES
        terminal = success or status in RECEIPT_FAILURE_STATUSES or bool(
            receipt.get("endedAt")
        )
        exit_code = receipt.get("exitCode")
        exit_passed = exit_code in {None, "", 0, "0"}
        if not exit_passed:
            exit_passed = _normalized_status(exit_code) in {
                "passed",
                "success",
                "succeeded",
            }

        timeline = [
            item
            for item in receipt.get("toolTimeline") or []
            if isinstance(item, dict)
        ][:30]
        verification_events = []
        intervention_events = []
        for item in timeline:
            searchable = " ".join(
                (
                    str(item.get("kind") or ""),
                    str(item.get("summary") or ""),
                )
            ).casefold()
            item_status = _normalized_status(item.get("status"))
            if any(term in searchable for term in VERIFICATION_TERMS):
                verification_events.append(item)
            if (
                item_status in RECEIPT_FAILURE_STATUSES
                or any(term in searchable for term in INTERVENTION_TERMS)
            ):
                intervention_events.append(item)

        artifacts = _receipt_artifact_refs(receipt)
        changed_files = [
            _bounded_text(item, 300)
            for item in receipt.get("changedFiles") or []
            if _bounded_text(item, 300)
        ][:30]
        verification_observed = bool(artifacts or verification_events)
        verification_trace_passed = (
            not verification_events
            or _normalized_status(
                verification_events[-1].get("status")
            )
            not in RECEIPT_FAILURE_STATUSES
        )
        verification_passed = bool(
            schema_valid
            and success
            and exit_passed
            and verification_observed
            and verification_trace_passed
        )

        proof_components = {
            "receiptIntegrity": 0.2 if schema_valid and turn_id else 0.0,
            "terminalTrace": 0.15 if terminal else 0.0,
            "proofArtifacts": (
                min(0.35, 0.25 + 0.025 * max(0, len(artifacts) - 1))
                if artifacts
                else 0.0
            ),
            "verificationTrace": 0.2 if verification_events else 0.0,
            "changedFileTrace": 0.05 if changed_files else 0.0,
            "toolTimeline": 0.05 if timeline else 0.0,
        }
        proof_quality = round(min(1.0, sum(proof_components.values())), 4)
        duration_ms = _float(receipt.get("durationMs"))
        duration_seconds = (
            round(max(0.0, duration_ms) / 1000.0, 3)
            if duration_ms is not None
            else None
        )
        authority = _receipt_authority(receipt)
        digest = _canonical_digest(
            {
                key: receipt.get(key)
                for key in (
                    "schema",
                    "sessionId",
                    "missionId",
                    "sourceType",
                    "sourceMessageId",
                    "runtime",
                    "provider",
                    "model",
                    "effort",
                    "status",
                    "exitCode",
                    "startedAt",
                    "endedAt",
                    "durationMs",
                    "toolTimeline",
                    "changedFiles",
                    "proofArtifacts",
                    "permissionSummary",
                    "authority",
                )
            }
        )
        receipt_id = _stable_id(
            "turn_receipt",
            conversation_id,
            turn_id,
            digest,
        )
        eligible = bool(schema_valid and turn_id and conversation_id and terminal and verification_observed)
        if eligible and verification_passed:
            eligibility_reason = "Completed with durable verification evidence."
        elif eligible:
            eligibility_reason = "Durable verification was recorded, but the run did not pass."
        elif not schema_valid:
            eligibility_reason = "This turn does not use the supported receipt schema."
        elif not verification_observed:
            eligibility_reason = "No proof artifact or verification trace was recorded."
        else:
            eligibility_reason = "The run has not reached a terminal state."

        return {
            "schema": RECEIPT_MEASUREMENT_SCHEMA,
            "receiptId": receipt_id,
            "receiptDigest": digest,
            "receiptSchema": receipt.get("schema") or "",
            "turnId": turn_id,
            "conversationId": conversation_id,
            "createdAt": _bounded_text(record.get("createdAt"), 80),
            "missionId": _bounded_text(receipt.get("missionId"), 180),
            "status": status or "not_reported",
            "runtime": _bounded_text(receipt.get("runtime"), 120),
            "provider": _bounded_text(receipt.get("provider"), 120),
            "model": _bounded_text(receipt.get("model"), 160),
            "effort": _bounded_text(receipt.get("effort"), 80),
            "eligible": eligible,
            "eligibilityReason": eligibility_reason,
            "verificationObserved": verification_observed,
            "verificationPassed": verification_passed,
            "verificationStatus": (
                "passed"
                if verification_passed
                else "failed"
                if verification_observed
                else "missing"
            ),
            "proofQuality": proof_quality,
            "proofComponents": proof_components,
            "proofArtifactCount": len(artifacts),
            "artifactRefs": artifacts,
            "changedFileCount": len(changed_files),
            "durationSeconds": duration_seconds,
            "interventionCount": len(intervention_events),
            "cost": _receipt_cost(receipt),
            "authority": authority,
            "authorityRecorded": authority["recorded"],
            "transcriptsIncluded": False,
        }

    @classmethod
    def receipt_candidate(cls, record: dict[str, Any]) -> dict[str, Any]:
        measurement = cls._receipt_measurement(record)
        return {
            key: measurement[key]
            for key in (
                "schema",
                "receiptId",
                "receiptDigest",
                "turnId",
                "conversationId",
                "createdAt",
                "missionId",
                "status",
                "runtime",
                "provider",
                "model",
                "effort",
                "eligible",
                "eligibilityReason",
                "verificationStatus",
                "proofQuality",
                "proofArtifactCount",
                "changedFileCount",
                "durationSeconds",
                "interventionCount",
                "authority",
                "authorityRecorded",
                "transcriptsIncluded",
            )
        }

    @staticmethod
    def _receipt_pair_outcome_scores(
        baseline: dict[str, Any],
        candidate: dict[str, Any],
        operator_value: str,
    ) -> tuple[float, float]:
        scores = {
            "baseline": (
                (0.45 if baseline.get("verificationPassed") else 0.0)
                + 0.35 * float(baseline.get("proofQuality") or 0.0)
            ),
            "candidate": (
                (0.45 if candidate.get("verificationPassed") else 0.0)
                + 0.35 * float(candidate.get("proofQuality") or 0.0)
            ),
        }

        baseline_duration = _float(baseline.get("durationSeconds"))
        candidate_duration = _float(candidate.get("durationSeconds"))
        if (
            baseline_duration is not None
            and candidate_duration is not None
            and baseline_duration > 0
            and candidate_duration > 0
        ):
            relative_gap = abs(baseline_duration - candidate_duration) / max(
                baseline_duration,
                candidate_duration,
            )
            if relative_gap <= 0.05:
                scores["baseline"] += 0.04
                scores["candidate"] += 0.04
            elif baseline_duration < candidate_duration:
                scores["baseline"] += 0.08
            else:
                scores["candidate"] += 0.08

        baseline_interventions = _int(baseline.get("interventionCount"))
        candidate_interventions = _int(candidate.get("interventionCount"))
        if baseline_interventions == candidate_interventions:
            scores["baseline"] += 0.02
            scores["candidate"] += 0.02
        elif baseline_interventions < candidate_interventions:
            scores["baseline"] += 0.04
        else:
            scores["candidate"] += 0.04

        if operator_value == "candidate_better":
            scores["candidate"] += 0.08
        elif operator_value == "baseline_better":
            scores["baseline"] += 0.08
        else:
            scores["baseline"] += 0.04
            scores["candidate"] += 0.04
        return (
            round(min(1.0, scores["baseline"]), 4),
            round(min(1.0, scores["candidate"]), 4),
        )

    @classmethod
    @checked_action(check_app_learning)
    def _app_outcome_learning(
        cls,
        rows: list[sqlite3.Row],
        *,
        open_trial_by_lineage: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        friction_groups: dict[tuple[str, str], dict[str, Any]] = {}
        completed_count = 0
        blocked_count = 0
        helpful_count = 0
        correction_count = 0
        measured_seconds = 0.0
        estimated_minutes_returned = 0.0
        estimate_count = 0

        for row in rows:
            measurements = _decode(row["measurements_json"], {})
            evidence = _decode(row["evidence_json"], {})
            if not isinstance(measurements, dict) or not isinstance(evidence, dict):
                continue
            outcome = str(measurements.get("outcome") or "")
            duration_seconds = max(
                0.0,
                float(_float(measurements.get("durationSeconds"), 0.0) or 0.0),
            )
            measured_seconds += duration_seconds
            if outcome == "completed":
                completed_count += 1
            elif outcome == "blocked":
                blocked_count += 1
            if measurements.get("operatorValue") == "helpful":
                helpful_count += 1
            correction_count += max(
                0,
                _int(measurements.get("correctionCount")),
            )
            estimated_return = _float(
                measurements.get("operatorEstimatedMinutesReturned")
            )
            if estimated_return is not None:
                estimate_count += 1
                estimated_minutes_returned += max(0.0, estimated_return)

            friction_code = str(measurements.get("frictionCode") or "none")
            if friction_code == "none":
                continue
            lineage_id = str(row["lineage_id"])
            key = (lineage_id, friction_code)
            group = friction_groups.setdefault(
                key,
                {
                    "lineageId": lineage_id,
                    "capabilityId": str(row["capability_id"]),
                    "capabilityKind": str(row["capability_kind"]),
                    "skillId": str(
                        evidence.get("skillId") or row["capability_id"]
                    ),
                    "frictionCode": friction_code,
                    "label": FRICTION_LABELS.get(
                        friction_code,
                        FRICTION_LABELS["other"],
                    ),
                    "occurrences": 0,
                    "blockedCount": 0,
                    "correctionCount": 0,
                    "severity": "none",
                    "affectedApps": set(),
                    "receiptDigests": [],
                    "latestAt": "",
                },
            )
            group["occurrences"] += 1
            group["blockedCount"] += int(outcome == "blocked")
            group["correctionCount"] += max(
                0,
                _int(measurements.get("correctionCount")),
            )
            group["affectedApps"].add(str(evidence.get("appId") or ""))
            receipt_digest = str(evidence.get("receiptDigest") or "")
            if receipt_digest and receipt_digest not in group["receiptDigests"]:
                group["receiptDigests"].append(receipt_digest)
            severity = str(measurements.get("frictionSeverity") or "none")
            severity_rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
            if severity_rank.get(severity, 0) > severity_rank.get(
                str(group["severity"]),
                0,
            ):
                group["severity"] = severity
            group["latestAt"] = max(
                str(group["latestAt"]),
                str(row["created_at"] or ""),
            )

        friction_nodes: list[dict[str, Any]] = []
        proposals: list[dict[str, Any]] = []
        mutation_by_code = {
            "repeated_manual_entry": (
                "Add one reviewed input preset or batch boundary without widening authority."
            ),
            "context_reentry": (
                "Create a bounded context pack that restores only the verified inputs "
                "needed by this workflow."
            ),
            "tool_switching": (
                "Compose the existing steps into one local workflow while keeping each "
                "tool boundary visible."
            ),
            "unclear_output": (
                "Repair the output contract so the result and its proof are unambiguous."
            ),
            "verification_gap": (
                "Add a deterministic verification step and require its artifact before "
                "the run can pass."
            ),
            "permission_wait": (
                "Repair the approval sequence without granting any new permission."
            ),
            "runtime_failure": (
                "Repair runtime routing and add a reproducible failure check before reuse."
            ),
            "other": (
                "Review the repeated friction receipts and define the smallest bounded "
                "workflow change."
            ),
        }
        repair_codes = {
            "unclear_output",
            "verification_gap",
            "permission_wait",
            "runtime_failure",
        }
        active_trials = open_trial_by_lineage or {}
        for group in friction_groups.values():
            node = {
                **group,
                "affectedApps": sorted(
                    item for item in group["affectedApps"] if item
                ),
                "receiptDigests": list(group["receiptDigests"][:12]),
                "patternReady": (
                    int(group["occurrences"]) >= FRICTION_PATTERN_MINIMUM
                ),
                "transcriptsIncluded": False,
            }
            friction_nodes.append(node)
            if not node["patternReady"]:
                continue
            action = (
                "repair"
                if str(node["frictionCode"]) in repair_codes
                else "branch"
            )
            trial = active_trials.get(str(node["lineageId"]))
            proposals.append(
                {
                    "proposalId": _stable_id(
                        "friction_proposal",
                        node["lineageId"],
                        node["frictionCode"],
                    ),
                    "lineageId": node["lineageId"],
                    "capabilityId": node["capabilityId"],
                    "capabilityKind": node["capabilityKind"] or "skill",
                    "label": node["skillId"] or node["capabilityId"],
                    "origin": "app_outcome",
                    "action": action,
                    "title": (
                        f"{action.title()} {node['skillId'] or node['capabilityId']} "
                        f"where {str(node['label']).lower()} repeats"
                    ),
                    "reason": (
                        f"{node['occurrences']} distinct sealed app receipts reported "
                        f"{str(node['label']).lower()}. Usage did not raise trust; the "
                        "pattern only created this review proposal."
                    ),
                    "mutationBrief": mutation_by_code.get(
                        str(node["frictionCode"]),
                        mutation_by_code["other"],
                    ),
                    "priority": (
                        0
                        if node["blockedCount"] or node["severity"] == "high"
                        else 1
                    ),
                    "status": "trial_active" if trial else "suggested",
                    "trialId": trial["trialId"] if trial else "",
                    "humanDecisionRequired": True,
                    "evidenceSummary": {
                        "appRunCount": node["occurrences"],
                        "frictionCount": node["occurrences"],
                        "blockedCount": node["blockedCount"],
                        "correctionCount": node["correctionCount"],
                        "frictionCode": node["frictionCode"],
                        "receiptDigests": node["receiptDigests"],
                        "transcriptsIncluded": False,
                    },
                    "successContract": cls._success_contract(action),
                    "nextAction": (
                        "Review the typed receipt pattern, then start a sealed bounded "
                        "trial. Neyvia will not edit or activate the skill automatically."
                    ),
                }
            )

        friction_nodes.sort(
            key=lambda item: (
                -int(item["patternReady"]),
                -int(item["blockedCount"]),
                -int(item["occurrences"]),
                str(item["frictionCode"]),
            )
        )
        proposals.sort(
            key=lambda item: (
                int(item["priority"]),
                -_int(item["evidenceSummary"].get("frictionCount")),
                str(item["proposalId"]),
            )
        )
        return {
            "schema": PERSONAL_FRICTION_GRAPH_SCHEMA,
            "receiptCount": len(rows),
            "frictionSignalCount": sum(
                int(item["occurrences"]) for item in friction_nodes
            ),
            "patternCount": sum(
                int(bool(item["patternReady"])) for item in friction_nodes
            ),
            "nodes": friction_nodes,
            "proposals": proposals,
            "operatorDividends": {
                "schema": OPERATOR_DIVIDENDS_SCHEMA,
                "completedOutcomeCount": completed_count,
                "blockedOutcomeCount": blocked_count,
                "helpfulOutcomeCount": helpful_count,
                "correctionCount": correction_count,
                "measuredRunMinutes": round(measured_seconds / 60.0, 2),
                "operatorEstimatedMinutesReturned": round(
                    estimated_minutes_returned,
                    2,
                ),
                "operatorEstimateCount": estimate_count,
                "measuredClaim": (
                    "Elapsed time and outcome state are derived from sealed run "
                    "timestamps."
                ),
                "estimateClaim": (
                    "Time returned is an operator counterfactual estimate and never "
                    "raises capability trust."
                ),
            },
            "transcriptsIncluded": False,
            "privateRunTextStored": False,
            "trustRaised": False,
        }

    def snapshot(
        self,
        *,
        skill_catalog: dict[str, Any] | None = None,
        constellation: dict[str, Any] | None = None,
        active_mission_id: str = "",
        receipt_records: list[dict[str, Any]] | None = None,
        app_factory_jobs: list[dict[str, Any]] | None = None,
        provider_availability: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        capabilities = [*self._catalog_rows(skill_catalog), *self._hermes_rows()]
        timestamp = utc_now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for item in capabilities:
                item["lineageId"] = self._ensure_lineage(
                    connection,
                    capability_id=str(item["capabilityId"]),
                    capability_kind=str(item["capabilityKind"]),
                    label=str(item["label"]),
                    origin=str(item["origin"]),
                    metadata={
                        "source": item.get("source") or "",
                        "sourcePath": item.get("sourcePath") or "",
                        "sourceDigest": item.get("sourceDigest") or "",
                    },
                    now=timestamp,
                )
            connection.commit()
            trial_rows = connection.execute(
                """
                SELECT * FROM capability_evolution_trials
                ORDER BY updated_at DESC, trial_id DESC
                LIMIT 40
                """
            ).fetchall()
            observation_rows = connection.execute(
                """
                SELECT lineage_id, capability_id, COUNT(*) AS observation_count,
                    SUM(CASE WHEN accepted_by != '' THEN 1 ELSE 0 END) AS accepted_count
                FROM capability_observations
                GROUP BY lineage_id, capability_id
                """
            ).fetchall()
            lineage_rows = connection.execute(
                """
                SELECT * FROM capability_lineages
                ORDER BY updated_at DESC, lineage_id DESC
                LIMIT 120
                """
            ).fetchall()
            materialization_rows = connection.execute(
                """
                SELECT * FROM capability_skill_materializations
                ORDER BY updated_at DESC, materialization_id DESC
                LIMIT 80
                """
            ).fetchall()
            lease_rows = connection.execute(
                """
                SELECT * FROM capability_proof_leases
                ORDER BY updated_at DESC, lease_id DESC
                LIMIT 80
                """
            ).fetchall()
            app_observation_rows = connection.execute(
                """
                SELECT * FROM capability_observations
                WHERE source_kind = 'app_run'
                ORDER BY created_at DESC, observation_id DESC
                LIMIT 1000
                """
            ).fetchall()

        observations = {
            str(row["lineage_id"]): {
                "observationCount": int(row["observation_count"]),
                "acceptedOutcomeCount": int(row["accepted_count"] or 0),
            }
            for row in observation_rows
        }
        trials = [self._trial_from_row(row) for row in trial_rows]
        materializations = [
            self._materialization_from_row(row)
            for row in materialization_rows
        ]
        materialization_by_id = {
            item["materializationId"]: item for item in materializations
        }
        proof_leases = [
            self._proof_lease_from_row(row) for row in lease_rows
        ]
        proof_lease_reviews: dict[str, dict[str, Any]] = {}
        for lease in proof_leases:
            materialization = materialization_by_id.get(
                lease["materializationId"]
            )
            if not materialization:
                continue
            proof_lease_reviews[lease["materializationId"]] = (
                self._assess_proof_lease(
                    lease,
                    materialization,
                    provider_availability=provider_availability,
                    now=timestamp,
                )
            )
        for materialization in materializations:
            proof_lease_reviews.setdefault(
                materialization["materializationId"],
                self._unestablished_lease_review(materialization),
            )
        app_factory_handoffs = self._app_factory_handoff_reviews_from_records(
            trials=trials,
            materializations=materializations,
            app_factory_jobs=app_factory_jobs,
            proof_lease_reviews=proof_lease_reviews,
        )
        app_handoff_by_materialization = {
            item["materializationId"]: item
            for item in app_factory_handoffs
        }
        materialization_by_trial = {
            item["trialId"]: item for item in materializations
        }
        skill_materialization_reviews: list[dict[str, Any]] = []
        for trial in trials:
            candidate = (
                dict(trial.get("candidate") or {})
                if isinstance(trial.get("candidate"), dict)
                else {}
            )
            if (
                trial.get("state") != "accepted"
                or not _is_sealed_skill_candidate(candidate)
            ):
                continue
            materialization = materialization_by_trial.get(trial["trialId"])
            proof_lease = (
                proof_lease_reviews.get(
                    materialization["materializationId"]
                )
                if materialization
                else None
            )
            app_factory_handoff = (
                app_handoff_by_materialization.get(
                    materialization["materializationId"]
                )
                if materialization
                else None
            )
            source_binding = (
                dict(candidate.get("sourceBinding") or {})
                if isinstance(candidate.get("sourceBinding"), dict)
                else {}
            )
            skill_materialization_reviews.append(
                {
                    "schema": "neyvia.skill_materialization_review.v1",
                    "trialId": trial["trialId"],
                    "approvedLineageId": (
                        trial.get("verdict", {}).get("approvedLineageId")
                        if isinstance(trial.get("verdict"), dict)
                        else ""
                    ),
                    "state": (
                        materialization["state"]
                        if materialization
                        else "review_required"
                    ),
                    "candidateSkillId": candidate.get("targetSkillId") or "",
                    "candidateDigest": candidate.get("packageDigest") or "",
                    "skillSha256": candidate.get("skillSha256") or "",
                    "metadataSha256": candidate.get("metadataSha256") or "",
                    "activeLineageId": source_binding.get("lineageId") or "",
                    "activeCapabilityId": source_binding.get("capabilityId")
                    or trial["capabilityId"],
                    "activeSourcePath": source_binding.get("sourcePath") or "",
                    "activeSourceDigest": source_binding.get("sourceDigest")
                    or "",
                    "materialization": materialization,
                    "proofLease": proof_lease,
                    "appFactoryHandoff": app_factory_handoff,
                    "candidateActivated": False,
                    "canMaterialize": materialization is None,
                    "canPromoteToApp": bool(
                        materialization
                        and materialization["state"]
                        == "materialized_inactive"
                        and proof_lease
                        and proof_lease["state"] == "current"
                        and (
                            not app_factory_handoff
                            or app_factory_handoff["state"]
                            == "review_required"
                        )
                    ),
                    "rollbackAvailable": bool(
                        materialization
                        and materialization["state"]
                        == "materialized_inactive"
                    ),
                }
            )
        counterfactual_forges = [
            dict(item.get("verdict", {}).get("counterfactualForge") or {})
            for item in trials
            if isinstance(
                item.get("verdict", {}).get("counterfactualForge"),
                dict,
            )
        ]
        open_trial_by_lineage = {
            item["lineageId"]: item
            for item in reversed(trials)
            if item["state"] not in FINAL_TRIAL_STATES
        }
        app_outcome_learning = self._app_outcome_learning(
            app_observation_rows,
            open_trial_by_lineage=open_trial_by_lineage,
        )
        recommendations: list[dict[str, Any]] = []
        for item in capabilities:
            item.update(observations.get(str(item["lineageId"]), {}))
            item["openTrial"] = open_trial_by_lineage.get(str(item["lineageId"]))
            recommendation = self._recommendation(item)
            recommendation["lineageId"] = item["lineageId"]
            if item["openTrial"]:
                recommendation["status"] = "trial_active"
                recommendation["trialId"] = item["openTrial"]["trialId"]
                if (
                    item["openTrial"]["state"] == "evidence_ready"
                    and item["openTrial"]["action"]
                    in COUNTERFACTUAL_REQUIRED_ACTIONS
                ):
                    recommendation["nextAction"] = (
                        "Seal a bounded counterfactual replay and authority review "
                        "before approving the candidate lineage."
                    )
                else:
                    recommendation["nextAction"] = (
                        "Continue the active comparison and collect the missing "
                        "verification or operator-value signal."
                    )
            recommendations.append(recommendation)
        recommendations.sort(
            key=lambda item: (
                int(item.get("priority") or 9),
                -_int(item.get("evidenceSummary", {}).get("usageCount")),
                str(item.get("label") or ""),
            )
        )

        graph = constellation if isinstance(constellation, dict) else {}
        team_rows: list[dict[str, Any]] = []
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            contract = (
                dict(node.get("teamContract") or {})
                if isinstance(node.get("teamContract"), dict)
                else {}
            )
            delta = read_agent_delta(node)
            contract_fields = (
                "outcome",
                "requiredEvidence",
                "authority",
                "budget",
                "stopCondition",
                "handback",
            )
            contract_ready = all(contract.get(field) for field in contract_fields)
            evidence_count = len(delta.evidence) + len(delta.artifacts)
            team_rows.append(
                {
                    "nodeId": node.get("nodeId") or "",
                    "label": node.get("title") or "Specialist",
                    "runtime": node.get("runtime") or "",
                    "lifecycleStage": node.get("lifecycleStage") or "",
                    "contractReady": contract_ready,
                    "contract": contract,
                    "evidenceItemCount": evidence_count,
                    "evidenceReady": evidence_count > 0,
                }
            )

        accepted_trials = [item for item in trials if item["state"] == "accepted"]
        outcome_lifts = [
            _float(item.get("verdict", {}).get("averageOutcomeLift"))
            for item in accepted_trials
        ]
        outcome_lifts = [value for value in outcome_lifts if value is not None]
        imported = [item for item in capabilities if item["origin"] == "hermes_import"]
        receipt_candidates = [
            self.receipt_candidate(item)
            for item in receipt_records or []
            if isinstance(item, dict)
        ]
        return {
            "schema": CAPABILITY_EVOLUTION_SCHEMA,
            "generatedAt": timestamp,
            "activeMissionId": str(active_mission_id or ""),
            "trustPolicy": {
                "usageRaisesTrust": False,
                "rule": (
                    "Usage is a discovery signal. Only comparable verification plus "
                    "operator value can approve a new lineage."
                ),
                "humanApprovalRequired": True,
                "rollbackRequired": True,
            },
            "summary": {
                "capabilityCount": len(capabilities),
                "provenCount": sum(
                    1 for item in capabilities if item.get("state") == "proven"
                ),
                "learningCount": sum(
                    1
                    for item in capabilities
                    if item.get("state") in {"learning", "learned", "active"}
                ),
                "unmeasuredCount": sum(
                    1
                    for item in capabilities
                    if not _int(item.get("feedbackCount"))
                    and not _int(item.get("operatorValueSampleCount"))
                ),
                "stagnatingCount": sum(
                    1
                    for item in capabilities
                    if _int(item.get("zeroImprovementStreak")) >= 2
                ),
                "heldCount": sum(
                    1
                    for item in capabilities
                    if item.get("state") == "needs_repair"
                    or item.get("selectionState") == "deprioritize"
                ),
                "activeTrialCount": sum(
                    1 for item in trials if item["state"] not in FINAL_TRIAL_STATES
                ),
                "acceptedEvolutionCount": len(accepted_trials),
                "counterfactualReadyCount": sum(
                    1
                    for item in counterfactual_forges
                    if item.get("reviewGatePassed") is True
                ),
                "counterfactualBlockedCount": sum(
                    1
                    for item in counterfactual_forges
                    if item.get("state") == "blocked"
                ),
                "materializedInactiveCount": sum(
                    1
                    for item in materializations
                    if item["state"] == "materialized_inactive"
                ),
                "withdrawnMaterializationCount": sum(
                    1
                    for item in materializations
                    if item["state"] == "withdrawn"
                ),
                "appFactoryHandoffReadyCount": sum(
                    1
                    for item in app_factory_handoffs
                    if item["state"] == "review_required"
                ),
                "appFactoryDraftCount": sum(
                    1
                    for item in app_factory_handoffs
                    if item["state"]
                    in {"draft_ready", "draft_maintenance_due"}
                ),
                "proofLeaseCurrentCount": sum(
                    1
                    for item in proof_lease_reviews.values()
                    if item["state"] == "current"
                ),
                "proofLeaseDueCount": sum(
                    1
                    for item in proof_lease_reviews.values()
                    if item["state"]
                    in {"review_due", "reproof_required"}
                ),
                "proofLeaseHeldCount": sum(
                    1
                    for item in proof_lease_reviews.values()
                    if item["state"]
                    in {"held", "retirement_review"}
                ),
                "proofLeaseUnestablishedCount": sum(
                    1
                    for item in proof_lease_reviews.values()
                    if item["state"] == "unestablished"
                ),
                "appOutcomeReceiptCount": app_outcome_learning["receiptCount"],
                "frictionPatternCount": app_outcome_learning["patternCount"],
            },
            "compoundingReturn": {
                "acceptedEvolutionCount": len(accepted_trials),
                "averageOutcomeLift": (
                    round(sum(outcome_lifts) / len(outcome_lifts), 4)
                    if outcome_lifts
                    else None
                ),
                "claimStatus": "measured" if outcome_lifts else "not_yet_measured",
                "message": (
                    "Accepted comparisons are producing measurable outcome lift."
                    if outcome_lifts
                    else "No compounding claim yet. Complete and approve a comparison first."
                ),
            },
            "team": {
                "conversationId": graph.get("conversationId") or "",
                "memberCount": len(team_rows),
                "contractReadyCount": sum(
                    1 for item in team_rows if item["contractReady"]
                ),
                "evidenceReadyCount": sum(
                    1 for item in team_rows if item["evidenceReady"]
                ),
                "members": team_rows,
            },
            "receiptComparisons": {
                "schema": "neyvia.receipt_comparison_sources.v1",
                "conversationId": graph.get("conversationId") or "",
                "candidateCount": len(receipt_candidates),
                "eligibleCount": sum(
                    1 for item in receipt_candidates if item["eligible"]
                ),
                "candidates": receipt_candidates,
                "transcriptsIncluded": False,
                "rule": (
                    "Only receipts resolved from this Constellation conversation "
                    "can enter a trial comparison."
                ),
            },
            "recommendations": recommendations[:10],
            "trials": trials,
            "lineages": [self._lineage_from_row(row) for row in lineage_rows],
            "skillMaterializationReviews": skill_materialization_reviews,
            "skillMaterializations": materializations,
            "proofLeases": proof_leases,
            "proofLeaseReviews": sorted(
                proof_lease_reviews.values(),
                key=lambda item: (
                    {
                        "held": 0,
                        "reproof_required": 1,
                        "review_due": 2,
                        "retirement_review": 3,
                        "unestablished": 4,
                        "current": 5,
                        "withdrawn": 6,
                    }.get(str(item.get("state") or ""), 9),
                    str(item.get("materializationId") or ""),
                ),
            ),
            "appFactoryHandoffs": app_factory_handoffs,
            "appOutcomeLearning": app_outcome_learning,
            "importedEvidence": {
                "available": bool(imported),
                "source": "Hermes aggregate skill history",
                "capabilityCount": len(imported),
                "usageCount": sum(_int(item.get("usageCount")) for item in imported),
                "feedbackCount": sum(
                    _int(item.get("feedbackCount")) for item in imported
                ),
                "stagnatingCount": sum(
                    1
                    for item in imported
                    if _int(item.get("zeroImprovementStreak")) >= 2
                ),
                "rawConversationContentRead": False,
            },
        }

    def create_trial(self, payload: dict[str, Any]) -> dict[str, Any]:
        capability_id = _bounded_text(payload.get("capabilityId"), 160)
        if not capability_id:
            raise ValueError("capabilityId is required")
        capability_kind = _bounded_text(
            payload.get("capabilityKind") or "skill", 80
        )
        label = _bounded_text(payload.get("label") or capability_id, 160)
        origin = _bounded_text(payload.get("origin") or "neyvia", 80)
        action = _bounded_text(payload.get("action") or "prove", 80)
        if action not in CAPABILITY_ACTIONS:
            raise ValueError(f"unsupported capability evolution action: {action}")
        timestamp = utc_now()
        context = (
            dict(payload.get("context") or {})
            if isinstance(payload.get("context"), dict)
            else {}
        )
        baseline = (
            dict(payload.get("baseline") or {})
            if isinstance(payload.get("baseline"), dict)
            else {}
        )
        candidate = (
            dict(payload.get("candidate") or {})
            if isinstance(payload.get("candidate"), dict)
            else {}
        )
        success_contract = self._success_contract(action)
        if isinstance(payload.get("successContract"), dict):
            success_contract.update(dict(payload["successContract"]))
        success_contract["counterfactualReviewRequired"] = (
            action in COUNTERFACTUAL_REQUIRED_ACTIONS
        )
        success_contract["counterfactualCaseLimit"] = COUNTERFACTUAL_CASE_LIMIT
        success_contract["humanApprovalRequired"] = True
        trial_id = _new_id("capability_trial")
        sealed_candidate_required = bool(
            capability_kind == "skill"
            and action in SKILL_CANDIDATE_REQUIRED_ACTIONS
        )
        success_contract["sealedSkillCandidateRequired"] = (
            sealed_candidate_required
        )
        if sealed_candidate_required:
            candidate = {
                **candidate,
                "schema": SKILL_CANDIDATE_BRIEF_SCHEMA,
                "state": "draft_required",
                "targetSkillId": _versioned_skill_id(
                    label,
                    capability_id,
                    action,
                    trial_id,
                ),
                "displayName": f"{label} {action.replace('_', ' ').title()}",
                "sealed": False,
                "activated": False,
            }
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            lineage_id = str(payload.get("lineageId") or "").strip()
            if lineage_id:
                known = connection.execute(
                    "SELECT lineage_id FROM capability_lineages WHERE lineage_id = ?",
                    (lineage_id,),
                ).fetchone()
                if not known:
                    raise ValueError(f"unknown capability lineage: {lineage_id}")
            else:
                lineage_id = self._ensure_lineage(
                    connection,
                    capability_id=capability_id,
                    capability_kind=capability_kind,
                    label=label,
                    origin=origin,
                    metadata={"source": "evolution_trial"},
                    now=timestamp,
                )
            active = connection.execute(
                """
                SELECT trial_id FROM capability_evolution_trials
                WHERE lineage_id = ?
                    AND state IN ('planned', 'collecting', 'evidence_ready', 'held')
                ORDER BY updated_at DESC LIMIT 1
                """,
                (lineage_id,),
            ).fetchone()
            if active:
                raise ValueError(
                    f"an active evolution trial already exists for {capability_id}: "
                    f"{active['trial_id']}"
                )
            title = _bounded_text(
                payload.get("title")
                or f"{action.replace('_', ' ').title()} {label}",
                240,
            )
            reason = _bounded_text(
                payload.get("reason")
                or "Run a bounded baseline/candidate comparison before changing trust.",
                900,
            )
            connection.execute(
                """
                INSERT INTO capability_evolution_trials (
                    trial_id, lineage_id, capability_id, capability_kind, label,
                    action, state, title, reason, context_json, baseline_json,
                    candidate_json, success_contract_json, evidence_json,
                    verdict_json, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'planned', ?, ?, ?, ?, ?, ?, '[]', '{}', ?, ?, ?)
                """,
                (
                    trial_id,
                    lineage_id,
                    capability_id,
                    capability_kind,
                    label,
                    action,
                    title,
                    reason,
                    _json(context),
                    _json(baseline),
                    _json(candidate),
                    _json(success_contract),
                    _bounded_text(payload.get("createdBy") or "operator", 80),
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM capability_evolution_trials WHERE trial_id = ?",
                (trial_id,),
            ).fetchone()
        return self._trial_from_row(row)

    def seal_skill_candidate(
        self,
        trial_id: str,
        *,
        skill_markdown: str,
        display_name: str = "",
        default_prompt: str = "",
        sealed_by: str = "operator",
        review_confirmed: bool = False,
    ) -> dict[str, Any]:
        """Bind an exact, reviewed skill package before comparison evidence."""

        if not review_confirmed:
            raise ValueError(
                "confirm that the exact candidate SKILL.md and interface metadata were reviewed"
            )
        normalized_trial_id = _bounded_text(trial_id, 180)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM capability_evolution_trials WHERE trial_id = ?",
                (normalized_trial_id,),
            ).fetchone()
            if not row:
                raise KeyError(trial_id)
            trial = self._trial_from_row(row)
            if not _trial_requires_sealed_skill_candidate(trial):
                raise ValueError(
                    "this trial action does not produce a versioned skill candidate"
                )
            if trial["state"] != "planned" or trial.get("evidence"):
                raise ValueError(
                    "the exact skill candidate must be sealed before the first comparison"
                )
            candidate_brief = (
                dict(trial.get("candidate") or {})
                if isinstance(trial.get("candidate"), dict)
                else {}
            )
            target_skill_id = str(
                candidate_brief.get("targetSkillId")
                or _versioned_skill_id(
                    trial["label"],
                    trial["capabilityId"],
                    trial["action"],
                    trial["trialId"],
                )
            )
            package = build_validated_skill_package(
                skill_markdown,
                display_name=display_name
                or str(candidate_brief.get("displayName") or trial["label"]),
                default_prompt=default_prompt,
            )
            if package["skillId"] != target_skill_id:
                raise ValueError(
                    "Candidate SKILL.md name must match the versioned target "
                    f"{target_skill_id}."
                )
            lineage_row = connection.execute(
                "SELECT * FROM capability_lineages WHERE lineage_id = ?",
                (trial["lineageId"],),
            ).fetchone()
            if not lineage_row:
                raise ValueError(
                    f"unknown active lineage for trial: {trial['lineageId']}"
                )
            active_lineage = self._lineage_from_row(lineage_row)
            active_metadata = (
                dict(active_lineage.get("metadata") or {})
                if isinstance(active_lineage.get("metadata"), dict)
                else {}
            )
            active_source_digest = str(
                active_metadata.get("sourceDigest") or ""
            ) or _canonical_digest(
                {
                    "lineageId": active_lineage["lineageId"],
                    "capabilityId": active_lineage["capabilityId"],
                    "origin": active_lineage["origin"],
                    "metadata": active_metadata,
                }
            )
            package_digest = _canonical_digest(
                {
                    "schema": SEALED_SKILL_CANDIDATE_SCHEMA,
                    "trialId": trial["trialId"],
                    "parentLineageId": trial["lineageId"],
                    "activeSourceDigest": active_source_digest,
                    "packageSha256": package["packageSha256"],
                }
            )
            existing_candidate = (
                dict(trial.get("candidate") or {})
                if isinstance(trial.get("candidate"), dict)
                else {}
            )
            if _is_sealed_skill_candidate(existing_candidate):
                if existing_candidate.get("packageDigest") == package_digest:
                    connection.rollback()
                    return trial
                raise ValueError(
                    "the candidate package is already sealed; start a new trial to change it"
                )
            timestamp = utc_now()
            sealed_candidate = {
                "schema": SEALED_SKILL_CANDIDATE_SCHEMA,
                "state": "sealed",
                "targetSkillId": target_skill_id,
                "displayName": (
                    str(display_name or "").strip()
                    or str(candidate_brief.get("displayName") or trial["label"])
                )[:80],
                "description": package["description"],
                "skillMarkdown": package["skillMarkdown"],
                "openaiYaml": package["openaiYaml"],
                "skillSha256": package["skillSha256"],
                "metadataSha256": package["metadataSha256"],
                "packageSha256": package["packageSha256"],
                "packageDigest": package_digest,
                "validation": package["validation"],
                "sourceBinding": {
                    "lineageId": active_lineage["lineageId"],
                    "capabilityId": active_lineage["capabilityId"],
                    "sourcePath": active_metadata.get("sourcePath") or "",
                    "sourceDigest": active_source_digest,
                },
                "sealedBy": _bounded_text(sealed_by or "operator", 80),
                "sealedAt": timestamp,
                "sealed": True,
                "activated": False,
            }
            connection.execute(
                """
                UPDATE capability_evolution_trials
                SET candidate_json = ?, updated_at = ?
                WHERE trial_id = ?
                """,
                (
                    _json(sealed_candidate),
                    timestamp,
                    normalized_trial_id,
                ),
            )
            connection.commit()
            updated = connection.execute(
                "SELECT * FROM capability_evolution_trials WHERE trial_id = ?",
                (normalized_trial_id,),
            ).fetchone()
        return self._trial_from_row(updated)

    def record_receipt_comparison(
        self,
        trial_id: str,
        *,
        baseline_record: dict[str, Any],
        candidate_record: dict[str, Any],
        same_contract_confirmed: bool,
        operator_value: str,
        operator_note: str = "",
        recorded_by: str = "operator",
        mission_id: str = "",
    ) -> dict[str, Any]:
        """Bind one comparison to two receipts resolved by the backend ledger."""

        normalized_trial_id = str(trial_id or "").strip()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM capability_evolution_trials WHERE trial_id = ?",
                (normalized_trial_id,),
            ).fetchone()
        if not row:
            raise KeyError(trial_id)
        trial = self._trial_from_row(row)
        if trial["state"] in FINAL_TRIAL_STATES:
            raise ValueError(
                f"cannot add evidence to a {trial['state']} evolution trial"
            )
        if (
            _trial_requires_sealed_skill_candidate(trial)
            and not _is_sealed_skill_candidate(trial.get("candidate"))
        ):
            raise ValueError(
                "seal the exact candidate SKILL.md before recording comparison evidence"
            )
        if not same_contract_confirmed:
            raise ValueError(
                "confirm that the baseline and candidate used the same task contract"
            )
        normalized_value = _normalized_status(operator_value)
        if normalized_value not in OPERATOR_VALUE_VERDICTS:
            raise ValueError(
                "operatorValue must be candidate_better, about_the_same, or baseline_better"
            )

        baseline = self._receipt_measurement(baseline_record)
        candidate = self._receipt_measurement(candidate_record)
        if baseline["receiptSchema"] != TURN_RECEIPT_SCHEMA:
            raise ValueError("the baseline turn is not a real Neyvia turn receipt")
        if candidate["receiptSchema"] != TURN_RECEIPT_SCHEMA:
            raise ValueError("the candidate turn is not a real Neyvia turn receipt")
        if not baseline["eligible"]:
            raise ValueError(
                f"the baseline receipt is not comparable: {baseline['eligibilityReason']}"
            )
        if not candidate["eligible"]:
            raise ValueError(
                f"the candidate receipt is not comparable: {candidate['eligibilityReason']}"
            )
        if baseline["receiptId"] == candidate["receiptId"]:
            raise ValueError("baseline and candidate must be different turn receipts")
        if baseline["conversationId"] != candidate["conversationId"]:
            raise ValueError(
                "baseline and candidate receipts must come from the same Constellation conversation"
            )
        expected_conversation_id = _bounded_text(
            (trial.get("context") or {}).get("conversationId"),
            180,
        )
        if (
            expected_conversation_id
            and baseline["conversationId"] != expected_conversation_id
        ):
            raise ValueError(
                "selected receipts do not belong to this trial's Constellation conversation"
            )

        baseline_outcome, candidate_outcome = (
            self._receipt_pair_outcome_scores(
                baseline,
                candidate,
                normalized_value,
            )
        )

        def run_metrics(
            measurement: dict[str, Any],
            outcome_score: float,
        ) -> dict[str, Any]:
            return {
                "receiptId": measurement["receiptId"],
                "outcomeScore": outcome_score,
                "proofQuality": measurement["proofQuality"],
                "verificationPassed": measurement["verificationPassed"],
                "interventionCount": measurement["interventionCount"],
                "durationSeconds": measurement["durationSeconds"],
                "cost": measurement["cost"],
            }

        comparison_scope_id = _stable_id(
            "comparison_scope",
            normalized_trial_id,
            baseline["conversationId"],
        )
        run_id = _stable_id(
            "comparison",
            normalized_trial_id,
            baseline["receiptDigest"],
            candidate["receiptDigest"],
        )
        receipt_pair = {
            "schema": RECEIPT_COMPARISON_SCHEMA,
            "comparisonScopeId": comparison_scope_id,
            "conversationId": baseline["conversationId"],
            "sameContractConfirmed": True,
            "candidatePackageDigest": (
                trial.get("candidate", {}).get("packageDigest")
                if isinstance(trial.get("candidate"), dict)
                else ""
            ),
            "baseline": {
                key: baseline[key]
                for key in (
                    "receiptId",
                    "receiptDigest",
                    "turnId",
                    "createdAt",
                    "missionId",
                    "status",
                    "runtime",
                    "provider",
                    "model",
                    "verificationStatus",
                    "proofQuality",
                    "proofArtifactCount",
                    "changedFileCount",
                    "durationSeconds",
                    "interventionCount",
                    "authority",
                    "authorityRecorded",
                )
            },
            "candidate": {
                key: candidate[key]
                for key in (
                    "receiptId",
                    "receiptDigest",
                    "turnId",
                    "createdAt",
                    "missionId",
                    "status",
                    "runtime",
                    "provider",
                    "model",
                    "verificationStatus",
                    "proofQuality",
                    "proofArtifactCount",
                    "changedFileCount",
                    "durationSeconds",
                    "interventionCount",
                    "authority",
                    "authorityRecorded",
                )
            },
            "transcriptsIncluded": False,
        }
        artifact_refs = [
            f"turn-receipt:{baseline['receiptId']}",
            f"turn-receipt:{candidate['receiptId']}",
            *[f"baseline:{item}" for item in baseline["artifactRefs"]],
            *[f"candidate:{item}" for item in candidate["artifactRefs"]],
        ]
        chosen_mission_id = (
            _bounded_text(mission_id, 180)
            or candidate["missionId"]
            or baseline["missionId"]
            or _bounded_text((trial.get("context") or {}).get("missionId"), 180)
        )
        return self.record_trial_evidence(
            normalized_trial_id,
            {
                "runId": run_id,
                "missionId": chosen_mission_id,
                "comparable": True,
                "baseline": run_metrics(baseline, baseline_outcome),
                "candidate": run_metrics(candidate, candidate_outcome),
                "verificationPassed": candidate["verificationPassed"],
                "operatorValueRecorded": True,
                "operatorValue": {
                    "verdict": normalized_value,
                    "note": _bounded_text(operator_note, 1200),
                    "recordedBy": _bounded_text(recorded_by or "operator", 80),
                },
                "receiptPair": receipt_pair,
                "candidatePackageDigest": (
                    trial.get("candidate", {}).get("packageDigest")
                    if isinstance(trial.get("candidate"), dict)
                    else ""
                ),
                "measurementRubric": {
                    "schema": "neyvia.receipt_outcome_rubric.v1",
                    "completionWeight": 0.45,
                    "proofWeight": 0.35,
                    "durationWeight": 0.08,
                    "interventionWeight": 0.04,
                    "operatorValueWeight": 0.08,
                    "derivedFromReceipts": True,
                },
                "artifacts": artifact_refs,
                "notes": (
                    _bounded_text(operator_note, 1200)
                    or "Receipt-bound comparison recorded under the active trial contract."
                ),
                "transcriptsIncluded": False,
            },
        )

    def build_counterfactual_forge(
        self,
        trial_id: str,
        *,
        case_run_ids: list[str],
        review_confirmed: bool,
        reviewed_by: str = "operator",
    ) -> dict[str, Any]:
        """Seal a bounded, receipt-backed replay review before lineage approval."""

        normalized_trial_id = _bounded_text(trial_id, 180)
        normalized_run_ids = [
            _bounded_text(item, 180)
            for item in case_run_ids
            if _bounded_text(item, 180)
        ]
        if not review_confirmed:
            raise ValueError(
                "confirm that the bounded replay set and authority differences were reviewed"
            )
        if len(set(normalized_run_ids)) != len(normalized_run_ids):
            raise ValueError("counterfactual replay cases must be distinct")
        if len(normalized_run_ids) > COUNTERFACTUAL_CASE_LIMIT:
            raise ValueError(
                f"counterfactual replay sets are limited to {COUNTERFACTUAL_CASE_LIMIT} cases"
            )

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM capability_evolution_trials WHERE trial_id = ?",
                (normalized_trial_id,),
            ).fetchone()
            if not row:
                raise KeyError(trial_id)
            trial = self._trial_from_row(row)
            if trial["state"] in FINAL_TRIAL_STATES:
                raise ValueError(
                    f"cannot forge a replay review for a {trial['state']} evolution trial"
                )
            if trial["action"] not in COUNTERFACTUAL_REQUIRED_ACTIONS:
                raise ValueError(
                    "this evolution action does not require a counterfactual forge"
                )
            sealed_candidate_required = _trial_requires_sealed_skill_candidate(
                trial
            )
            if (
                sealed_candidate_required
                and not _is_sealed_skill_candidate(trial.get("candidate"))
            ):
                raise ValueError(
                    "the counterfactual forge requires an exact sealed skill candidate"
                )
            sealed_candidate_digest = (
                str(trial.get("candidate", {}).get("packageDigest") or "")
                if isinstance(trial.get("candidate"), dict)
                else ""
            )

            contract = dict(trial.get("successContract") or {})
            required_cases = max(
                1,
                _int(contract.get("requiredComparableRuns"), 1),
            )
            if len(normalized_run_ids) < required_cases:
                raise ValueError(
                    f"select at least {required_cases} receipt-backed replay cases"
                )

            evidence_by_id = {
                str(item.get("runId") or ""): item
                for item in trial.get("evidence") or []
                if isinstance(item, dict) and item.get("runId")
            }
            cases: list[dict[str, Any]] = []
            for run_id in normalized_run_ids:
                run = evidence_by_id.get(run_id)
                if not run:
                    raise ValueError(
                        f"unknown counterfactual replay evidence: {run_id}"
                    )
                receipt_pair = (
                    dict(run.get("receiptPair") or {})
                    if isinstance(run.get("receiptPair"), dict)
                    else {}
                )
                if (
                    receipt_pair.get("schema") != RECEIPT_COMPARISON_SCHEMA
                    or receipt_pair.get("sameContractConfirmed") is not True
                    or receipt_pair.get("transcriptsIncluded") is not False
                    or run.get("transcriptsIncluded") is not False
                ):
                    raise ValueError(
                        f"replay case {run_id} is not a transcript-free receipt comparison"
                    )
                if sealed_candidate_required and (
                    run.get("candidatePackageDigest")
                    != sealed_candidate_digest
                    or receipt_pair.get("candidatePackageDigest")
                    != sealed_candidate_digest
                ):
                    raise ValueError(
                        f"replay case {run_id} is not bound to the sealed skill candidate"
                    )
                baseline_receipt = (
                    dict(receipt_pair.get("baseline") or {})
                    if isinstance(receipt_pair.get("baseline"), dict)
                    else {}
                )
                candidate_receipt = (
                    dict(receipt_pair.get("candidate") or {})
                    if isinstance(receipt_pair.get("candidate"), dict)
                    else {}
                )
                baseline_authority = (
                    dict(baseline_receipt.get("authority") or {})
                    if isinstance(baseline_receipt.get("authority"), dict)
                    else {}
                )
                candidate_authority = (
                    dict(candidate_receipt.get("authority") or {})
                    if isinstance(candidate_receipt.get("authority"), dict)
                    else {}
                )
                authority = _authority_delta(
                    baseline_authority,
                    candidate_authority,
                )
                if not authority["recorded"]:
                    raise ValueError(
                        f"replay case {run_id} is missing receipt-bound authority evidence"
                    )

                deltas = (
                    dict(run.get("deltas") or {})
                    if isinstance(run.get("deltas"), dict)
                    else {}
                )
                operator_value = (
                    dict(run.get("operatorValue") or {})
                    if isinstance(run.get("operatorValue"), dict)
                    else {}
                )
                outcome_lift = _float(deltas.get("outcomeLift"), 0.0) or 0.0
                proof_lift = _float(deltas.get("proofQualityLift"), 0.0) or 0.0
                candidate_metrics = (
                    dict(run.get("candidate") or {})
                    if isinstance(run.get("candidate"), dict)
                    else {}
                )
                candidate_verified = bool(
                    candidate_metrics.get("verificationPassed")
                )
                operator_verdict = _normalized_status(
                    operator_value.get("verdict")
                )
                min_lift = float(contract.get("minOutcomeLift") or 0.05)
                max_proof_regression = float(
                    contract.get("maxProofRegression") or 0.0
                )

                if (
                    not candidate_verified
                    or proof_lift < -max_proof_regression
                    or operator_verdict == "baseline_better"
                    or outcome_lift < 0
                ):
                    classification = "regression"
                    reason = (
                        "The candidate lost verification, proof quality, measured "
                        "outcome, or operator value."
                    )
                elif (
                    bool(run.get("constraintsPassed"))
                    and operator_verdict == "candidate_better"
                    and outcome_lift >= min_lift
                ):
                    classification = "win"
                    reason = (
                        "The candidate cleared the contract with measurable lift "
                        "and operator support."
                    )
                elif (
                    candidate_verified
                    and operator_verdict == "about_the_same"
                    and proof_lift >= -max_proof_regression
                ):
                    classification = "tie"
                    reason = (
                        "The candidate preserved verification and proof without "
                        "measurable operator value lift."
                    )
                else:
                    classification = "inconclusive"
                    reason = (
                        "The receipt pair is comparable, but it does not establish "
                        "a win, tie, or regression."
                    )

                case_id = _stable_id(
                    "counterfactual_case",
                    normalized_trial_id,
                    baseline_receipt.get("receiptDigest"),
                    candidate_receipt.get("receiptDigest"),
                )
                cases.append(
                    {
                        "caseId": case_id,
                        "runId": run_id,
                        "contractRef": receipt_pair.get("comparisonScopeId") or "",
                        "baselineReceiptId": baseline_receipt.get("receiptId") or "",
                        "candidateReceiptId": candidate_receipt.get("receiptId") or "",
                        "classification": classification,
                        "reason": reason,
                        "outcomeLift": round(outcome_lift, 4),
                        "proofQualityLift": round(proof_lift, 4),
                        "operatorVerdict": operator_verdict,
                        "candidatePackageDigest": sealed_candidate_digest,
                        "authority": authority,
                        "transcriptsIncluded": False,
                    }
                )

            counts = {
                name: sum(
                    1 for item in cases if item["classification"] == name
                )
                for name in ("win", "tie", "regression", "inconclusive")
            }
            expanded_permissions = sorted(
                {
                    permission
                    for item in cases
                    for permission in item["authority"]["expandedPermissions"]
                }
            )
            reduced_permissions = sorted(
                {
                    permission
                    for item in cases
                    for permission in item["authority"]["reducedPermissions"]
                }
            )
            authority_status = (
                "expanded"
                if expanded_permissions
                else "reduced"
                if reduced_permissions
                else "unchanged"
            )
            regression_free = counts["regression"] == 0
            determinate = counts["inconclusive"] == 0
            review_gate_passed = bool(
                len(cases) >= required_cases
                and counts["win"] >= 1
                and regression_free
                and determinate
                and authority_status != "expanded"
            )
            forge_id = _stable_id(
                "counterfactual_forge",
                normalized_trial_id,
                sealed_candidate_digest,
                *sorted(
                    f"{item['baselineReceiptId']}:{item['candidateReceiptId']}"
                    for item in cases
                ),
            )
            existing_forge = (
                dict((trial.get("verdict") or {}).get("counterfactualForge") or {})
                if isinstance(
                    (trial.get("verdict") or {}).get("counterfactualForge"),
                    dict,
                )
                else {}
            )
            if existing_forge.get("forgeId") == forge_id:
                connection.rollback()
                return trial

            timestamp = utc_now()
            forge = {
                "schema": COUNTERFACTUAL_FORGE_SCHEMA,
                "forgeId": forge_id,
                "trialId": normalized_trial_id,
                "candidatePackageDigest": sealed_candidate_digest,
                "state": "review_ready" if review_gate_passed else "blocked",
                "caseLimit": COUNTERFACTUAL_CASE_LIMIT,
                "caseCount": len(cases),
                "requiredCaseCount": required_cases,
                "cases": cases,
                "scorecard": {
                    "wins": counts["win"],
                    "ties": counts["tie"],
                    "regressions": counts["regression"],
                    "inconclusive": counts["inconclusive"],
                },
                "authorityComparison": {
                    "status": authority_status,
                    "expandedPermissions": expanded_permissions,
                    "reducedPermissions": reduced_permissions,
                    "gatePassed": authority_status != "expanded",
                },
                "regressionFree": regression_free,
                "determinate": determinate,
                "reviewConfirmed": True,
                "reviewedBy": _bounded_text(reviewed_by or "operator", 80),
                "reviewedAt": timestamp,
                "reviewGatePassed": review_gate_passed,
                "recommendedDecision": (
                    "accept" if review_gate_passed else "hold"
                ),
                "candidateActivated": False,
                "transcriptsIncluded": False,
            }
            verdict = dict(trial.get("verdict") or {})
            verdict.update(
                {
                    "status": (
                        "counterfactual_clear"
                        if review_gate_passed
                        else "counterfactual_blocked"
                    ),
                    "recommendedDecision": forge["recommendedDecision"],
                    "counterfactualReviewRequired": True,
                    "counterfactualForge": forge,
                    "humanDecisionRequired": True,
                    "candidateActivated": False,
                }
            )
            next_state = "evidence_ready" if review_gate_passed else "held"
            connection.execute(
                """
                UPDATE capability_evolution_trials
                SET state = ?, verdict_json = ?, updated_at = ?
                WHERE trial_id = ?
                """,
                (
                    next_state,
                    _json(verdict),
                    timestamp,
                    normalized_trial_id,
                ),
            )
            connection.commit()
            updated = connection.execute(
                "SELECT * FROM capability_evolution_trials WHERE trial_id = ?",
                (normalized_trial_id,),
            ).fetchone()
        return self._trial_from_row(updated)

    def record_trial_evidence(
        self, trial_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM capability_evolution_trials WHERE trial_id = ?",
                (str(trial_id or ""),),
            ).fetchone()
            if not row:
                raise KeyError(trial_id)
            trial = self._trial_from_row(row)
            if trial["state"] in FINAL_TRIAL_STATES:
                raise ValueError(
                    f"cannot add evidence to a {trial['state']} evolution trial"
                )
            sealed_candidate_required = _trial_requires_sealed_skill_candidate(
                trial
            )
            if (
                sealed_candidate_required
                and not _is_sealed_skill_candidate(trial.get("candidate"))
            ):
                raise ValueError(
                    "seal the exact candidate SKILL.md before recording comparison evidence"
                )
            sealed_candidate_digest = (
                str(trial.get("candidate", {}).get("packageDigest") or "")
                if isinstance(trial.get("candidate"), dict)
                else ""
            )
            requested_candidate_digest = str(
                payload.get("candidatePackageDigest") or ""
            ).strip()
            if (
                sealed_candidate_required
                and requested_candidate_digest
                and requested_candidate_digest != sealed_candidate_digest
            ):
                raise ValueError(
                    "comparison evidence does not match the sealed skill candidate"
                )
            requested_run_id = _bounded_text(payload.get("runId"), 180)
            if requested_run_id and any(
                item.get("runId") == requested_run_id
                for item in trial.get("evidence") or []
                if isinstance(item, dict)
            ):
                connection.rollback()
                return trial
            comparable = bool(payload.get("comparable"))
            if not comparable:
                raise ValueError(
                    "evolution evidence must explicitly confirm baseline/candidate comparability"
                )
            baseline = (
                dict(payload.get("baseline") or {})
                if isinstance(payload.get("baseline"), dict)
                else {}
            )
            candidate = (
                dict(payload.get("candidate") or {})
                if isinstance(payload.get("candidate"), dict)
                else {}
            )
            for metric in ("outcomeScore", "proofQuality"):
                if _float(baseline.get(metric)) is None or _float(
                    candidate.get(metric)
                ) is None:
                    raise ValueError(
                        f"comparable evidence requires numeric baseline and candidate {metric}"
                    )
            verification_passed = bool(payload.get("verificationPassed"))
            operator_value_recorded = bool(payload.get("operatorValueRecorded"))
            operator_value = (
                dict(payload.get("operatorValue") or {})
                if isinstance(payload.get("operatorValue"), dict)
                else {}
            )
            artifacts = [
                _bounded_text(item, 300)
                for item in payload.get("artifacts") or []
                if _bounded_text(item, 300)
            ][:24]
            notes = _bounded_text(payload.get("notes"), 1200)
            if not artifacts and not notes:
                raise ValueError(
                    "comparison evidence requires an artifact reference or bounded note"
                )
            deltas = {
                "outcomeLift": _metric_delta(
                    baseline, candidate, "outcomeScore"
                ),
                "proofQualityLift": _metric_delta(
                    baseline, candidate, "proofQuality"
                ),
                "interventionReduction": _metric_delta(
                    baseline,
                    candidate,
                    "interventionCount",
                    lower_is_better=True,
                ),
                "costReduction": _metric_delta(
                    baseline, candidate, "cost", lower_is_better=True
                ),
                "durationReductionSeconds": _metric_delta(
                    baseline,
                    candidate,
                    "durationSeconds",
                    lower_is_better=True,
                ),
            }
            contract = trial["successContract"]
            outcome_lift = _float(deltas["outcomeLift"], 0.0) or 0.0
            proof_lift = _float(deltas["proofQualityLift"], 0.0) or 0.0
            operator_supports_candidate = (
                not operator_value
                or operator_value.get("verdict") == "candidate_better"
            )
            constraints_passed = (
                verification_passed
                and operator_value_recorded
                and operator_supports_candidate
                and outcome_lift >= float(contract.get("minOutcomeLift") or 0.05)
                and proof_lift >= -float(contract.get("maxProofRegression") or 0.0)
            )
            run = {
                "runId": requested_run_id or _new_id("comparison"),
                "recordedAt": utc_now(),
                "missionId": _bounded_text(payload.get("missionId"), 180),
                "comparable": True,
                "baseline": baseline,
                "candidate": candidate,
                "deltas": deltas,
                "verificationPassed": verification_passed,
                "operatorValueRecorded": operator_value_recorded,
                "operatorValue": operator_value,
                "receiptPair": (
                    dict(payload.get("receiptPair") or {})
                    if isinstance(payload.get("receiptPair"), dict)
                    else {}
                ),
                "measurementRubric": (
                    dict(payload.get("measurementRubric") or {})
                    if isinstance(payload.get("measurementRubric"), dict)
                    else {}
                ),
                "candidatePackageDigest": sealed_candidate_digest,
                "artifacts": artifacts,
                "notes": notes,
                "constraintsPassed": constraints_passed,
                "transcriptsIncluded": False,
            }
            runs = [*trial["evidence"], run][-40:]
            comparable_runs = [item for item in runs if item.get("comparable")]
            qualifying_runs = [
                item for item in comparable_runs if item.get("constraintsPassed")
            ]
            required_runs = max(
                1, _int(contract.get("requiredComparableRuns"), 1)
            )
            evidence_ready = (
                len(comparable_runs) >= required_runs
                and len(qualifying_runs) >= required_runs
            )
            average_lift = round(
                sum(
                    float(item.get("deltas", {}).get("outcomeLift") or 0.0)
                    for item in comparable_runs
                )
                / max(1, len(comparable_runs)),
                4,
            )
            counterfactual_required = bool(
                trial["action"] in COUNTERFACTUAL_REQUIRED_ACTIONS
                or contract.get("counterfactualReviewRequired")
            )
            verdict = {
                "status": "candidate_better"
                if evidence_ready and average_lift > 0
                else "more_evidence_required",
                "recommendedDecision": (
                    "review_counterfactual"
                    if evidence_ready
                    and average_lift > 0
                    and counterfactual_required
                    else "accept"
                    if evidence_ready and average_lift > 0
                    else "hold"
                ),
                "comparableRunCount": len(comparable_runs),
                "qualifyingRunCount": len(qualifying_runs),
                "requiredComparableRuns": required_runs,
                "averageOutcomeLift": average_lift,
                "counterfactualReviewRequired": counterfactual_required,
                "humanDecisionRequired": True,
                "candidateActivated": False,
            }
            state = "evidence_ready" if evidence_ready else "collecting"
            timestamp = utc_now()
            connection.execute(
                """
                UPDATE capability_evolution_trials
                SET state = ?, evidence_json = ?, verdict_json = ?, updated_at = ?
                WHERE trial_id = ?
                """,
                (state, _json(runs), _json(verdict), timestamp, trial_id),
            )
            connection.commit()
            updated = connection.execute(
                "SELECT * FROM capability_evolution_trials WHERE trial_id = ?",
                (trial_id,),
            ).fetchone()
        return self._trial_from_row(updated)

    def decide_trial(
        self,
        trial_id: str,
        *,
        decision: str,
        decided_by: str = "operator",
        note: str = "",
    ) -> dict[str, Any]:
        normalized = str(decision or "").strip().casefold()
        if normalized not in {"accept", "hold", "reject", "cancel"}:
            raise ValueError(f"unsupported evolution trial decision: {decision}")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM capability_evolution_trials WHERE trial_id = ?",
                (str(trial_id or ""),),
            ).fetchone()
            if not row:
                raise KeyError(trial_id)
            trial = self._trial_from_row(row)
            if trial["state"] in FINAL_TRIAL_STATES:
                raise ValueError(
                    f"evolution trial is already final: {trial['state']}"
                )
            if normalized == "accept" and _trial_requires_sealed_skill_candidate(
                trial
            ):
                sealed_candidate = (
                    dict(trial.get("candidate") or {})
                    if isinstance(trial.get("candidate"), dict)
                    else {}
                )
                if not _is_sealed_skill_candidate(sealed_candidate):
                    raise ValueError(
                        "candidate cannot be accepted because its exact SKILL.md "
                        "was not sealed before comparison"
                    )
            if normalized == "accept" and trial["action"] in COUNTERFACTUAL_REQUIRED_ACTIONS:
                counterfactual_forge = (
                    dict(
                        trial.get("verdict", {}).get("counterfactualForge")
                        or {}
                    )
                    if isinstance(
                        trial.get("verdict", {}).get("counterfactualForge"),
                        dict,
                    )
                    else {}
                )
                if (
                    counterfactual_forge.get("schema")
                    != COUNTERFACTUAL_FORGE_SCHEMA
                    or counterfactual_forge.get("reviewConfirmed") is not True
                    or counterfactual_forge.get("reviewGatePassed") is not True
                ):
                    raise ValueError(
                        "candidate cannot be accepted until its counterfactual "
                        "replay and authority review passes"
                    )
            if normalized == "accept" and _trial_requires_sealed_skill_candidate(
                trial
            ):
                sealed_candidate = dict(trial.get("candidate") or {})
                counterfactual_forge = (
                    dict(
                        trial.get("verdict", {}).get(
                            "counterfactualForge"
                        )
                        or {}
                    )
                    if isinstance(
                        trial.get("verdict", {}).get(
                            "counterfactualForge"
                        ),
                        dict,
                    )
                    else {}
                )
                if (
                    counterfactual_forge.get("candidatePackageDigest")
                    != sealed_candidate.get("packageDigest")
                ):
                    raise ValueError(
                        "candidate cannot be accepted because its forge does not "
                        "match the sealed skill package"
                    )
            if normalized == "accept" and (
                trial["state"] != "evidence_ready"
                or trial.get("verdict", {}).get("recommendedDecision") != "accept"
            ):
                raise ValueError(
                    "candidate cannot be accepted until its comparison contract passes"
                )
            timestamp = utc_now()
            next_state = {
                "accept": "accepted",
                "hold": "held",
                "reject": "rejected",
                "cancel": "cancelled",
            }[normalized]
            verdict = dict(trial.get("verdict") or {})
            verdict.update(
                {
                    "decision": normalized,
                    "decidedBy": _bounded_text(decided_by or "operator", 80),
                    "decidedAt": timestamp,
                    "decisionNote": _bounded_text(note, 800),
                    "candidateActivated": False,
                }
            )
            lineage: dict[str, Any] | None = None
            if normalized == "accept":
                action = trial["action"]
                if action in {"quarantine", "retire"}:
                    lineage_state = (
                        "quarantined" if action == "quarantine" else "retired"
                    )
                    connection.execute(
                        """
                        UPDATE capability_lineages
                        SET state = ?, updated_at = ?
                        WHERE lineage_id = ?
                        """,
                        (lineage_state, timestamp, trial["lineageId"]),
                    )
                    lineage_id = trial["lineageId"]
                else:
                    lineage_id = self._ensure_lineage(
                        connection,
                        capability_id=(
                            f"{trial['capabilityId']}@"
                            f"{trial['trialId'].rsplit('_', 1)[-1][:8]}"
                        ),
                        capability_kind=trial["capabilityKind"],
                        label=f"{trial['label']} candidate",
                        origin="neyvia_evolution",
                        parent_lineage_id=trial["lineageId"],
                        state="approved",
                        metadata={
                            "trialId": trial["trialId"],
                            "action": action,
                            "materializationStatus": "review_required",
                            "candidateSkillId": (
                                trial.get("candidate", {}).get("targetSkillId")
                                if isinstance(trial.get("candidate"), dict)
                                else ""
                            ),
                            "candidatePackageDigest": (
                                trial.get("candidate", {}).get("packageDigest")
                                if isinstance(trial.get("candidate"), dict)
                                else ""
                            ),
                            "candidateActivated": False,
                        },
                        now=timestamp,
                    )
                lineage_row = connection.execute(
                    "SELECT * FROM capability_lineages WHERE lineage_id = ?",
                    (lineage_id,),
                ).fetchone()
                lineage = self._lineage_from_row(lineage_row)
                verdict["approvedLineageId"] = lineage_id
                verdict["materializationStatus"] = "review_required"
                verdict["nextAction"] = (
                    "Review and materialize the approved lineage in Skill Studio "
                    "or App Factory. The active capability was not silently changed."
                )
            connection.execute(
                """
                UPDATE capability_evolution_trials
                SET state = ?, verdict_json = ?, updated_at = ?
                WHERE trial_id = ?
                """,
                (next_state, _json(verdict), timestamp, trial_id),
            )
            connection.commit()
            updated = connection.execute(
                "SELECT * FROM capability_evolution_trials WHERE trial_id = ?",
                (trial_id,),
            ).fetchone()
        result = self._trial_from_row(updated)
        if lineage:
            result["approvedLineage"] = lineage
        return result

    @checked_action(check_materialization_write)
    def materialize_skill_candidate(
        self,
        trial_id: str,
        *,
        candidate_digest: str,
        review_confirmed: bool = False,
        materialized_by: str = "operator",
    ) -> dict[str, Any]:
        """Write an accepted, digest-bound skill package as an inactive branch."""

        if not review_confirmed:
            raise ValueError(
                "confirm the sealed package digest, authority boundary, and rollback path"
            )
        normalized_trial_id = _bounded_text(trial_id, 180)
        expected_digest = str(candidate_digest or "").strip()
        if not expected_digest:
            raise ValueError("candidateDigest is required")

        temporary_root: Path | None = None
        final_root: Path | None = None
        created_final_root = False
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM capability_evolution_trials WHERE trial_id = ?",
                    (normalized_trial_id,),
                ).fetchone()
                if not row:
                    raise KeyError(trial_id)
                trial = self._trial_from_row(row)
                if trial["state"] != "accepted":
                    raise ValueError(
                        "only an operator-accepted skill lineage can be materialized"
                    )
                if not _trial_requires_sealed_skill_candidate(trial):
                    raise ValueError(
                        "this accepted trial does not contain a versioned skill branch"
                    )
                candidate = (
                    dict(trial.get("candidate") or {})
                    if isinstance(trial.get("candidate"), dict)
                    else {}
                )
                if not _is_sealed_skill_candidate(candidate):
                    raise ValueError(
                        "the accepted lineage has no exact sealed skill package"
                    )
                if candidate.get("packageDigest") != expected_digest:
                    raise ValueError(
                        "candidate digest changed after review; refresh before materializing"
                    )

                verdict = (
                    dict(trial.get("verdict") or {})
                    if isinstance(trial.get("verdict"), dict)
                    else {}
                )
                forge = (
                    dict(verdict.get("counterfactualForge") or {})
                    if isinstance(verdict.get("counterfactualForge"), dict)
                    else {}
                )
                if (
                    forge.get("reviewGatePassed") is not True
                    or forge.get("candidatePackageDigest") != expected_digest
                ):
                    raise ValueError(
                        "the accepted forge does not prove this sealed skill package"
                    )
                approved_lineage_id = str(
                    verdict.get("approvedLineageId") or ""
                ).strip()
                if not approved_lineage_id:
                    raise ValueError(
                        "the accepted trial has no approved candidate lineage"
                    )
                approved_lineage_row = connection.execute(
                    "SELECT * FROM capability_lineages WHERE lineage_id = ?",
                    (approved_lineage_id,),
                ).fetchone()
                if not approved_lineage_row:
                    raise ValueError(
                        f"approved lineage is missing: {approved_lineage_id}"
                    )
                approved_lineage = self._lineage_from_row(
                    approved_lineage_row
                )
                if (
                    approved_lineage["parentLineageId"]
                    != trial["lineageId"]
                    or approved_lineage["state"] != "approved"
                ):
                    raise ValueError(
                        "the candidate lineage is no longer approved for materialization"
                    )

                existing_row = connection.execute(
                    """
                    SELECT * FROM capability_skill_materializations
                    WHERE trial_id = ?
                    """,
                    (normalized_trial_id,),
                ).fetchone()
                if existing_row:
                    existing = self._materialization_from_row(existing_row)
                    if existing["candidateDigest"] != expected_digest:
                        raise ValueError(
                            "a different package is already materialized for this trial"
                        )
                    connection.rollback()
                    return existing

                validation_package = build_validated_skill_package(
                    str(candidate.get("skillMarkdown") or ""),
                    display_name=str(candidate.get("displayName") or ""),
                )
                skill_markdown = str(candidate.get("skillMarkdown") or "")
                openai_yaml = str(candidate.get("openaiYaml") or "")
                skill_sha256 = hashlib.sha256(
                    skill_markdown.encode("utf-8")
                ).hexdigest()
                metadata_sha256 = hashlib.sha256(
                    openai_yaml.encode("utf-8")
                ).hexdigest()
                package_sha256 = hashlib.sha256(
                    (
                        "neyvia.skill_package.v1\0"
                        + skill_sha256
                        + "\0"
                        + metadata_sha256
                    ).encode("utf-8")
                ).hexdigest()
                if (
                    validation_package["skillId"]
                    != candidate.get("targetSkillId")
                    or skill_sha256 != candidate.get("skillSha256")
                    or metadata_sha256 != candidate.get("metadataSha256")
                    or package_sha256 != candidate.get("packageSha256")
                ):
                    raise ValueError(
                        "the sealed skill package no longer matches its recorded hashes"
                    )

                source_binding = (
                    dict(candidate.get("sourceBinding") or {})
                    if isinstance(candidate.get("sourceBinding"), dict)
                    else {}
                )
                recomputed_digest = _canonical_digest(
                    {
                        "schema": SEALED_SKILL_CANDIDATE_SCHEMA,
                        "trialId": trial["trialId"],
                        "parentLineageId": trial["lineageId"],
                        "activeSourceDigest": source_binding.get(
                            "sourceDigest"
                        )
                        or "",
                        "packageSha256": candidate.get("packageSha256") or "",
                    }
                )
                if recomputed_digest != expected_digest:
                    raise ValueError(
                        "the sealed candidate source binding no longer matches its digest"
                    )

                materialization_id = _stable_id(
                    "skill_materialization",
                    normalized_trial_id,
                    approved_lineage_id,
                    expected_digest,
                )
                control_root = (
                    self.root / ".agent_control"
                ).resolve()
                control_root.relative_to(self.root)
                materializations_root = (
                    control_root / "capability_materializations"
                ).resolve()
                materializations_root.relative_to(control_root)
                materializations_root.mkdir(parents=True, exist_ok=True)
                final_root = (
                    materializations_root / materialization_id
                ).resolve()
                final_root.relative_to(materializations_root)
                if final_root.exists():
                    raise ValueError(
                        "an untracked materialization folder already exists; "
                        "review it before retrying"
                    )
                temporary_root = (
                    materializations_root
                    / f".{materialization_id}.writing-{uuid.uuid4().hex[:8]}"
                ).resolve()
                temporary_root.relative_to(materializations_root)
                branch_dir = (
                    temporary_root
                    / "branch"
                    / str(candidate["targetSkillId"])
                )
                agents_dir = branch_dir / "agents"
                agents_dir.mkdir(parents=True)
                skill_path = branch_dir / "SKILL.md"
                metadata_path = agents_dir / "openai.yaml"
                skill_path.write_bytes(skill_markdown.encode("utf-8"))
                metadata_path.write_bytes(openai_yaml.encode("utf-8"))
                if (
                    hashlib.sha256(skill_path.read_bytes()).hexdigest()
                    != skill_sha256
                    or hashlib.sha256(metadata_path.read_bytes()).hexdigest()
                    != metadata_sha256
                ):
                    raise RuntimeError(
                        "materialized package hashes did not match the sealed candidate"
                    )

                parent_lineage_row = connection.execute(
                    "SELECT * FROM capability_lineages WHERE lineage_id = ?",
                    (trial["lineageId"],),
                ).fetchone()
                if not parent_lineage_row:
                    raise ValueError(
                        f"active parent lineage is missing: {trial['lineageId']}"
                    )
                parent_lineage = self._lineage_from_row(parent_lineage_row)
                rollback = {
                    "schema": SKILL_MATERIALIZATION_ROLLBACK_SCHEMA,
                    "strategy": "retain_active_lineage",
                    "activeLineageId": parent_lineage["lineageId"],
                    "activeCapabilityId": parent_lineage["capabilityId"],
                    "activeLineageState": parent_lineage["state"],
                    "activeSourcePath": source_binding.get("sourcePath") or "",
                    "activeSourceDigest": source_binding.get("sourceDigest") or "",
                    "candidatePackageRetained": True,
                    "candidateActivationChanged": False,
                    "command": "rollback_capability_skill_materialization_command",
                }
                timestamp = utc_now()
                final_package_path = (
                    final_root
                    / "branch"
                    / str(candidate["targetSkillId"])
                )
                final_receipt_path = final_root / "materialization.json"
                receipt = {
                    "schema": SKILL_MATERIALIZATION_RECEIPT_SCHEMA,
                    "materializationId": materialization_id,
                    "trialId": trial["trialId"],
                    "approvedLineageId": approved_lineage_id,
                    "parentLineageId": trial["lineageId"],
                    "state": "materialized_inactive",
                    "skillId": candidate["targetSkillId"],
                    "packagePath": str(final_package_path),
                    "skillPath": str(final_package_path / "SKILL.md"),
                    "metadataPath": str(
                        final_package_path / "agents" / "openai.yaml"
                    ),
                    "receiptPath": str(final_receipt_path),
                    "candidateDigest": expected_digest,
                    "skillSha256": skill_sha256,
                    "metadataSha256": metadata_sha256,
                    "authorityComparison": forge.get(
                        "authorityComparison"
                    )
                    or {},
                    "rollback": rollback,
                    "reviewConfirmed": True,
                    "materializedBy": _bounded_text(
                        materialized_by or "operator", 80
                    ),
                    "materializedAt": timestamp,
                    "candidateActivated": False,
                }
                _atomic_write_json(
                    temporary_root / "materialization.json",
                    receipt,
                )
                temporary_root.replace(final_root)
                created_final_root = True
                temporary_root = None

                connection.execute(
                    """
                    INSERT INTO capability_skill_materializations (
                        materialization_id, trial_id, approved_lineage_id,
                        parent_lineage_id, skill_id, state, package_path,
                        candidate_digest, skill_sha256, metadata_sha256,
                        rollback_json, receipt_json, materialized_by,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'materialized_inactive', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        materialization_id,
                        trial["trialId"],
                        approved_lineage_id,
                        trial["lineageId"],
                        candidate["targetSkillId"],
                        str(final_package_path),
                        expected_digest,
                        skill_sha256,
                        metadata_sha256,
                        _json(rollback),
                        _json(receipt),
                        _bounded_text(materialized_by or "operator", 80),
                        timestamp,
                        timestamp,
                    ),
                )
                approved_metadata = (
                    dict(approved_lineage.get("metadata") or {})
                    if isinstance(approved_lineage.get("metadata"), dict)
                    else {}
                )
                approved_metadata.update(
                    {
                        "materializationStatus": "materialized_inactive",
                        "materializationId": materialization_id,
                        "packagePath": str(final_package_path),
                        "candidatePackageDigest": expected_digest,
                        "candidateActivated": False,
                    }
                )
                connection.execute(
                    """
                    UPDATE capability_lineages
                    SET metadata_json = ?, updated_at = ?
                    WHERE lineage_id = ?
                    """,
                    (
                        _json(approved_metadata),
                        timestamp,
                        approved_lineage_id,
                    ),
                )
                verdict.update(
                    {
                        "materializationStatus": "materialized_inactive",
                        "materializationId": materialization_id,
                        "candidateActivated": False,
                    }
                )
                connection.execute(
                    """
                    UPDATE capability_evolution_trials
                    SET verdict_json = ?, updated_at = ?
                    WHERE trial_id = ?
                    """,
                    (
                        _json(verdict),
                        timestamp,
                        normalized_trial_id,
                    ),
                )
                connection.commit()
                created_final_root = False
                materialization_row = connection.execute(
                    """
                    SELECT * FROM capability_skill_materializations
                    WHERE materialization_id = ?
                    """,
                    (materialization_id,),
                ).fetchone()
            return self._materialization_from_row(materialization_row)
        except Exception:
            if temporary_root and temporary_root.exists():
                shutil.rmtree(temporary_root)
            if created_final_root and final_root and final_root.exists():
                shutil.rmtree(final_root)
            raise

    @checked_action(check_handoff)
    def prepare_app_factory_handoff(
        self,
        materialization_id: str,
        *,
        candidate_digest: str,
        review_confirmed: bool = False,
        reviewed_by: str = "operator",
        provider_availability: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        """Build a transcript-free, hash-bound capsule for a local app draft."""

        if not review_confirmed:
            raise ValueError(
                "confirm the source evidence, sealed workflow, inactive state, "
                "and local-draft boundary"
            )
        normalized_id = _bounded_text(materialization_id, 180)
        expected_digest = str(candidate_digest or "").strip()
        if not normalized_id:
            raise ValueError("materializationId is required")
        if not expected_digest:
            raise ValueError("candidateDigest is required")

        with self._connection() as connection:
            materialization_row = connection.execute(
                """
                SELECT * FROM capability_skill_materializations
                WHERE materialization_id = ?
                """,
                (normalized_id,),
            ).fetchone()
            if not materialization_row:
                raise KeyError(materialization_id)
            materialization = self._materialization_from_row(
                materialization_row
            )
            trial_row = connection.execute(
                """
                SELECT * FROM capability_evolution_trials
                WHERE trial_id = ?
                """,
                (materialization["trialId"],),
            ).fetchone()
            if not trial_row:
                raise ValueError("the source evolution trial is missing")
            trial = self._trial_from_row(trial_row)
            approved_lineage_row = connection.execute(
                """
                SELECT * FROM capability_lineages
                WHERE lineage_id = ?
                """,
                (materialization["approvedLineageId"],),
            ).fetchone()
            parent_lineage_row = connection.execute(
                """
                SELECT * FROM capability_lineages
                WHERE lineage_id = ?
                """,
                (materialization["parentLineageId"],),
            ).fetchone()
            lease_row = connection.execute(
                """
                SELECT * FROM capability_proof_leases
                WHERE materialization_id = ?
                """,
                (normalized_id,),
            ).fetchone()
        if materialization["state"] != "materialized_inactive":
            raise ValueError(
                "only an inactive, non-withdrawn skill materialization can "
                "enter App Factory"
            )
        if materialization["candidateDigest"] != expected_digest:
            raise ValueError(
                "candidate digest changed after review; refresh before creating an app"
            )
        if trial["state"] != "accepted":
            raise ValueError(
                "the source trial is no longer accepted for App Factory"
            )
        if not approved_lineage_row or not parent_lineage_row:
            raise ValueError(
                "the approved candidate or active parent lineage is missing"
            )
        approved_lineage = self._lineage_from_row(approved_lineage_row)
        parent_lineage = self._lineage_from_row(parent_lineage_row)
        if approved_lineage["state"] != "approved":
            raise ValueError(
                "the candidate lineage is not in an approved inactive state"
            )
        if parent_lineage["state"] in {"quarantined", "retired"}:
            raise ValueError(
                "the active parent lineage is no longer eligible as an app rollback anchor"
            )
        if not lease_row:
            raise ValueError(
                "establish a current proof lease before creating an app draft"
            )
        proof_lease = self._proof_lease_from_row(lease_row)
        proof_lease_review = self._assess_proof_lease(
            proof_lease,
            materialization,
            provider_availability=provider_availability,
        )
        if proof_lease_review["state"] != "current":
            raise ValueError(
                "the capability proof lease is not current: "
                f"{proof_lease_review['nextAction']}"
            )

        candidate = (
            dict(trial.get("candidate") or {})
            if isinstance(trial.get("candidate"), dict)
            else {}
        )
        if (
            not _is_sealed_skill_candidate(candidate)
            or candidate.get("packageDigest") != expected_digest
        ):
            raise ValueError(
                "the accepted trial no longer matches the sealed skill package"
            )
        verdict = (
            dict(trial.get("verdict") or {})
            if isinstance(trial.get("verdict"), dict)
            else {}
        )
        if (
            verdict.get("approvedLineageId")
            != materialization["approvedLineageId"]
        ):
            raise ValueError(
                "the materialization is not bound to the accepted lineage verdict"
            )
        forge = (
            dict(verdict.get("counterfactualForge") or {})
            if isinstance(verdict.get("counterfactualForge"), dict)
            else {}
        )
        authority = (
            dict(forge.get("authorityComparison") or {})
            if isinstance(forge.get("authorityComparison"), dict)
            else {}
        )
        if (
            forge.get("schema") != COUNTERFACTUAL_FORGE_SCHEMA
            or forge.get("reviewGatePassed") is not True
            or forge.get("candidatePackageDigest") != expected_digest
            or authority.get("status") == "expanded"
            or forge.get("transcriptsIncluded") is not False
        ):
            raise ValueError(
                "the source forge no longer proves a regression-free, "
                "authority-bounded package"
            )

        package_path = Path(materialization["packagePath"]).resolve()
        control_root = (self.root / ".agent_control").resolve()
        materializations_root = (
            control_root / "capability_materializations"
        ).resolve()
        package_path.relative_to(materializations_root)
        skill_path = package_path / "SKILL.md"
        metadata_path = package_path / "agents" / "openai.yaml"
        if not skill_path.is_file() or not metadata_path.is_file():
            raise ValueError("the exact materialized skill package is missing")
        skill_bytes = skill_path.read_bytes()
        metadata_bytes = metadata_path.read_bytes()
        if (
            hashlib.sha256(skill_bytes).hexdigest()
            != materialization["skillSha256"]
            or hashlib.sha256(metadata_bytes).hexdigest()
            != materialization["metadataSha256"]
        ):
            raise ValueError(
                "the materialized skill package changed after approval"
            )
        skill_markdown = skill_bytes.decode("utf-8")
        openai_yaml = metadata_bytes.decode("utf-8")
        if (
            skill_markdown != candidate.get("skillMarkdown")
            or openai_yaml != candidate.get("openaiYaml")
        ):
            raise ValueError(
                "the inactive package bytes no longer match the tested candidate"
            )
        workflow_steps = extract_skill_workflow_steps(skill_markdown)

        comparison_rows: list[dict[str, Any]] = []
        for run in trial.get("evidence") or []:
            if not isinstance(run, dict) or not run.get("constraintsPassed"):
                continue
            receipt_pair = (
                dict(run.get("receiptPair") or {})
                if isinstance(run.get("receiptPair"), dict)
                else {}
            )
            operator_value = (
                dict(run.get("operatorValue") or {})
                if isinstance(run.get("operatorValue"), dict)
                else {}
            )
            deltas = (
                dict(run.get("deltas") or {})
                if isinstance(run.get("deltas"), dict)
                else {}
            )
            comparison_rows.append(
                {
                    "runId": run.get("runId") or "",
                    "comparisonScopeId": receipt_pair.get(
                        "comparisonScopeId"
                    )
                    or "",
                    "receiptPairDigest": _canonical_digest(receipt_pair),
                    "outcomeLift": _float(deltas.get("outcomeLift")),
                    "proofQualityLift": _float(
                        deltas.get("proofQualityLift")
                    ),
                    "durationReductionSeconds": _float(
                        deltas.get("durationReductionSeconds")
                    ),
                    "operatorVerdict": operator_value.get("verdict") or "",
                    "candidatePackageDigest": run.get(
                        "candidatePackageDigest"
                    )
                    or "",
                    "transcriptsIncluded": False,
                }
            )
        required_runs = max(
            1,
            _int(
                (trial.get("successContract") or {}).get(
                    "requiredComparableRuns"
                ),
                1,
            ),
        )
        if len(comparison_rows) < required_runs:
            raise ValueError(
                "the source lineage no longer has enough qualifying comparisons"
            )

        validation = validate_skill_markdown(skill_markdown)
        if (
            validation["status"] != "passed"
            or validation["name"] != materialization["skillId"]
        ):
            raise ValueError(
                "the materialized package no longer passes its sealed validation"
            )
        lease_contract = (
            dict(proof_lease.get("contract") or {})
            if isinstance(proof_lease.get("contract"), dict)
            else {}
        )
        handoff_id = _stable_id(
            "app_factory_handoff",
            normalized_id,
            expected_digest,
            lease_contract.get("leaseDigest") or "",
        )
        rollback_source = (
            dict(materialization.get("rollback") or {})
            if isinstance(materialization.get("rollback"), dict)
            else {}
        )
        rollback_contract = {
            "strategy": rollback_source.get("strategy") or "",
            "activeLineageId": rollback_source.get("activeLineageId") or "",
            "activeCapabilityId": rollback_source.get("activeCapabilityId")
            or "",
            "activeLineageState": rollback_source.get("activeLineageState")
            or "",
            "activeSourceDigest": rollback_source.get("activeSourceDigest")
            or "",
            "candidatePackageRetained": bool(
                rollback_source.get("candidatePackageRetained")
            ),
            "candidateActivationChanged": False,
        }
        proof_lease_binding = {
            "schema": PROOF_LEASE_SCHEMA,
            "leaseId": proof_lease["leaseId"],
            "materializationId": normalized_id,
            "revision": proof_lease["revision"],
            "state": "current",
            "leaseDigest": lease_contract.get("leaseDigest") or "",
            "goalDigest": (
                (lease_contract.get("goal") or {}).get("digest")
                if isinstance(lease_contract.get("goal"), dict)
                else ""
            ),
            "proofRoutesDigest": lease_contract.get("proofRoutesDigest")
            or "",
            "dependenciesDigest": lease_contract.get("dependenciesDigest")
            or "",
            "reviewAt": lease_contract.get("reviewAt") or "",
            "issuedAt": lease_contract.get("issuedAt") or "",
            "candidateActivated": False,
            "transcriptsIncluded": False,
        }
        stable_contract = {
            "schema": APP_FACTORY_HANDOFF_SCHEMA,
            "handoffId": handoff_id,
            "materializationId": normalized_id,
            "trialId": trial["trialId"],
            "approvedLineageId": materialization["approvedLineageId"],
            "parentLineageId": materialization["parentLineageId"],
            "skillId": materialization["skillId"],
            "candidateDigest": expected_digest,
            "skillSha256": materialization["skillSha256"],
            "metadataSha256": materialization["metadataSha256"],
            "workflowSteps": workflow_steps,
            "comparisonRuns": comparison_rows,
            "forgeId": forge.get("forgeId") or "",
            "forgeDigest": _canonical_digest(forge),
            "scorecard": forge.get("scorecard") or {},
            "authorityComparison": authority,
            "rollback": rollback_contract,
            "proofLease": proof_lease_binding,
            "candidateActivated": False,
            "appActivated": False,
            "transcriptsIncluded": False,
        }
        handoff_digest = _canonical_digest(stable_contract)
        description = _bounded_text(
            validation.get("description")
            or trial.get("reason")
            or trial.get("label"),
            900,
        )
        return {
            **stable_contract,
            "handoffDigest": handoff_digest,
            "state": "reviewed_for_local_draft",
            "label": _bounded_text(trial.get("label") or materialization["skillId"], 160),
            "description": description,
            "sourcePackage": {
                "path": str(package_path),
                "skillPath": str(skill_path),
                "metadataPath": str(metadata_path),
                "materializationReceiptPath": (
                    materialization.get("receipt", {}).get("receiptPath")
                    if isinstance(materialization.get("receipt"), dict)
                    else ""
                ),
                "skillSha256": materialization["skillSha256"],
                "metadataSha256": materialization["metadataSha256"],
            },
            "evidenceSummary": {
                "comparableRunCount": _int(
                    verdict.get("comparableRunCount")
                ),
                "qualifyingRunCount": len(comparison_rows),
                "averageOutcomeLift": _float(
                    verdict.get("averageOutcomeLift")
                ),
                "scorecard": forge.get("scorecard") or {},
                "authorityComparison": authority,
                "transcriptsIncluded": False,
            },
            "review": {
                "confirmed": True,
                "reviewedBy": _bounded_text(reviewed_by or "operator", 80),
                "reviewedAt": utc_now(),
                "boundary": (
                    "Create a local App Factory draft only. Do not install the "
                    "skill, activate either capability, compile native code, "
                    "publish to Marketplace, or widen authority."
                ),
            },
        }

    @checked_action(check_materialization_write)
    def rollback_skill_materialization(
        self,
        materialization_id: str,
        *,
        candidate_digest: str,
        review_confirmed: bool = False,
        rolled_back_by: str = "operator",
        reason: str = "",
    ) -> dict[str, Any]:
        """Quarantine an inactive branch while retaining its immutable proof."""

        if not review_confirmed:
            raise ValueError(
                "confirm that the inactive branch should be rolled back and quarantined"
            )
        normalized_id = _bounded_text(materialization_id, 180)
        expected_digest = str(candidate_digest or "").strip()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM capability_skill_materializations
                WHERE materialization_id = ?
                """,
                (normalized_id,),
            ).fetchone()
            if not row:
                raise KeyError(materialization_id)
            materialization = self._materialization_from_row(row)
            if materialization["candidateDigest"] != expected_digest:
                raise ValueError(
                    "candidate digest changed after review; refresh before rollback"
                )
            if materialization["state"] == "withdrawn":
                connection.rollback()
                return materialization
            if materialization["state"] != "materialized_inactive":
                raise ValueError(
                    f"cannot rollback a {materialization['state']} materialization"
                )

            package_path = Path(materialization["packagePath"]).resolve()
            control_root = (
                self.root / ".agent_control"
            ).resolve()
            control_root.relative_to(self.root)
            materializations_root = (
                control_root / "capability_materializations"
            ).resolve()
            materializations_root.relative_to(control_root)
            package_path.relative_to(materializations_root)
            skill_path = package_path / "SKILL.md"
            metadata_path = package_path / "agents" / "openai.yaml"
            if (
                not skill_path.is_file()
                or not metadata_path.is_file()
                or hashlib.sha256(skill_path.read_bytes()).hexdigest()
                != materialization["skillSha256"]
                or hashlib.sha256(metadata_path.read_bytes()).hexdigest()
                != materialization["metadataSha256"]
            ):
                raise ValueError(
                    "the materialized package is missing or changed; rollback was not recorded"
                )

            timestamp = utc_now()
            rollback = {
                **(
                    materialization.get("rollback")
                    if isinstance(materialization.get("rollback"), dict)
                    else {}
                ),
                "schema": SKILL_MATERIALIZATION_ROLLBACK_SCHEMA,
                "state": "withdrawn",
                "materializationId": normalized_id,
                "candidateDigest": expected_digest,
                "rolledBackBy": _bounded_text(
                    rolled_back_by or "operator", 80
                ),
                "reason": _bounded_text(
                    reason
                    or "Inactive candidate branch withdrawn by the operator.",
                    800,
                ),
                "rolledBackAt": timestamp,
                "packageRetainedAt": str(package_path),
                "candidateActivationChanged": False,
            }
            rollback_path = package_path.parents[1] / "rollback.json"
            rollback["receiptPath"] = str(rollback_path)
            _atomic_write_json(rollback_path, rollback)
            receipt = (
                dict(materialization.get("receipt") or {})
                if isinstance(materialization.get("receipt"), dict)
                else {}
            )
            receipt.update(
                {
                    "state": "withdrawn",
                    "rollbackReceiptPath": str(rollback_path),
                    "candidateActivated": False,
                }
            )
            connection.execute(
                """
                UPDATE capability_skill_materializations
                SET state = 'withdrawn', rollback_json = ?, receipt_json = ?,
                    updated_at = ?
                WHERE materialization_id = ?
                """,
                (
                    _json(rollback),
                    _json(receipt),
                    timestamp,
                    normalized_id,
                ),
            )
            lineage_row = connection.execute(
                "SELECT * FROM capability_lineages WHERE lineage_id = ?",
                (materialization["approvedLineageId"],),
            ).fetchone()
            if lineage_row:
                lineage = self._lineage_from_row(lineage_row)
                lineage_metadata = (
                    dict(lineage.get("metadata") or {})
                    if isinstance(lineage.get("metadata"), dict)
                    else {}
                )
                lineage_metadata.update(
                    {
                        "materializationStatus": "withdrawn",
                        "rollbackReceiptPath": str(rollback_path),
                        "candidateActivated": False,
                    }
                )
                connection.execute(
                    """
                    UPDATE capability_lineages
                    SET state = 'quarantined', metadata_json = ?, updated_at = ?
                    WHERE lineage_id = ?
                    """,
                    (
                        _json(lineage_metadata),
                        timestamp,
                        materialization["approvedLineageId"],
                    ),
                )
            trial_row = connection.execute(
                "SELECT * FROM capability_evolution_trials WHERE trial_id = ?",
                (materialization["trialId"],),
            ).fetchone()
            if trial_row:
                trial = self._trial_from_row(trial_row)
                verdict = dict(trial.get("verdict") or {})
                verdict.update(
                    {
                        "materializationStatus": "withdrawn",
                        "rollbackReceiptPath": str(rollback_path),
                        "candidateActivated": False,
                    }
                )
                connection.execute(
                    """
                    UPDATE capability_evolution_trials
                    SET verdict_json = ?, updated_at = ?
                    WHERE trial_id = ?
                    """,
                    (
                        _json(verdict),
                        timestamp,
                        materialization["trialId"],
                    ),
                )
            lease_row = connection.execute(
                """
                SELECT * FROM capability_proof_leases
                WHERE materialization_id = ?
                """,
                (normalized_id,),
            ).fetchone()
            if lease_row:
                lease = self._proof_lease_from_row(lease_row)
                connection.execute(
                    """
                    UPDATE capability_proof_leases
                    SET state = 'withdrawn', updated_at = ?
                    WHERE lease_id = ?
                    """,
                    (timestamp, lease["leaseId"]),
                )
                lease_event = {
                    "schema": PROOF_LEASE_EVENT_SCHEMA,
                    "leaseId": lease["leaseId"],
                    "materializationId": normalized_id,
                    "kind": "withdrawn",
                    "revision": lease["revision"],
                    "state": "withdrawn",
                    "leaseDigest": (
                        (lease.get("contract") or {}).get("leaseDigest")
                        if isinstance(lease.get("contract"), dict)
                        else ""
                    ),
                    "rollbackReceiptPath": str(rollback_path),
                    "candidateActivated": False,
                    "transcriptsIncluded": False,
                }
                connection.execute(
                    """
                    INSERT INTO capability_proof_lease_events (
                        event_id, lease_id, materialization_id, kind,
                        state, receipt_json, created_at
                    ) VALUES (?, ?, ?, 'withdrawn', 'withdrawn', ?, ?)
                    """,
                    (
                        _new_id("proof_lease_event"),
                        lease["leaseId"],
                        normalized_id,
                        _json(lease_event),
                        timestamp,
                    ),
                )
            connection.commit()
            updated = connection.execute(
                """
                SELECT * FROM capability_skill_materializations
                WHERE materialization_id = ?
                """,
                (normalized_id,),
            ).fetchone()
        return self._materialization_from_row(updated)

    @checked_action(check_app_import)
    def import_capability_run_bundle(
        self,
        bundle: dict[str, Any],
        *,
        app_factory_jobs: list[dict[str, Any]],
        imported_by: str = "operator",
        provider_availability: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        """Import typed app outcomes after re-verifying every local receipt binding."""

        if not isinstance(bundle, dict):
            raise ValueError("capability run bundle must be a JSON object")
        if len(_json(bundle).encode("utf-8")) > CAPABILITY_RUN_MAX_BUNDLE_BYTES:
            raise ValueError("capability run bundle exceeds the 2 MiB import boundary")
        if bundle.get("schema") != CAPABILITY_RUN_BUNDLE_SCHEMA:
            raise ValueError(
                f"capability run bundle must use {CAPABILITY_RUN_BUNDLE_SCHEMA}"
            )
        if bundle.get("candidateActivated") is not False:
            raise ValueError("capability run bundle must keep the candidate inactive")
        if bundle.get("transcriptsIncluded") is not False:
            raise ValueError("capability run bundle cannot include transcripts")

        job_id = _bounded_text(bundle.get("appFactoryJobId"), 180)
        if not job_id:
            raise ValueError("appFactoryJobId is required")
        job = next(
            (
                item
                for item in app_factory_jobs or []
                if isinstance(item, dict)
                and str(item.get("jobId") or "") == job_id
            ),
            None,
        )
        if not job:
            raise ValueError("the App Factory job is not present in this workspace")
        if str(job.get("status") or "") != "ready":
            raise ValueError("only a ready App Factory job can return outcome evidence")
        verification = (
            dict(job.get("verification") or {})
            if isinstance(job.get("verification"), dict)
            else {}
        )
        if (
            str(verification.get("state") or "") != "passed"
            or not verification.get("receiptPath")
        ):
            raise ValueError(
                "the App Factory job has no passing durable verification receipt"
            )
        handoff = self._app_factory_job_handoff(job)
        if not handoff or handoff.get("schema") != APP_FACTORY_HANDOFF_SCHEMA:
            raise ValueError(
                "the App Factory job is not bound to a verified capability handoff"
            )
        spec = dict(job.get("spec") or {}) if isinstance(job.get("spec"), dict) else {}
        if (
            handoff.get("state") != "reviewed_for_local_draft"
            or handoff.get("candidateActivated") is not False
            or handoff.get("appActivated") is not False
            or handoff.get("transcriptsIncluded") is not False
            or _canonical_digest(
                _stable_app_factory_handoff_contract(handoff)
            )
            != str(handoff.get("handoffDigest") or "")
        ):
            raise ValueError(
                "the App Factory capability handoff changed after review"
            )
        expected_app_binding = _app_factory_binding_digest(
            str(handoff.get("handoffDigest") or ""),
            spec,
        )
        if str(handoff.get("appBindingDigest") or "") != expected_app_binding:
            raise ValueError(
                "the App Factory app binding changed after verification"
            )
        receipt_path = Path(str(verification["receiptPath"])).expanduser()
        if not receipt_path.is_absolute():
            receipt_path = self.root / receipt_path
        try:
            receipt_path = receipt_path.resolve(strict=True)
            receipt_path.relative_to(self.root)
        except (OSError, ValueError):
            raise ValueError(
                "the App Factory verification receipt is outside this workspace"
            ) from None
        if (
            not receipt_path.is_file()
            or receipt_path.stat().st_size > CAPABILITY_RUN_MAX_BUNDLE_BYTES
        ):
            raise ValueError(
                "the App Factory verification receipt is unavailable or too large"
            )
        try:
            verification_receipt = json.loads(
                receipt_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise ValueError(
                "the App Factory verification receipt cannot be read"
            ) from None
        receipt_handoff = (
            dict(verification_receipt.get("capabilityHandoff") or {})
            if isinstance(
                verification_receipt.get("capabilityHandoff"),
                dict,
            )
            else {}
        )
        if (
            verification_receipt.get("schema")
            != APP_FACTORY_VERIFICATION_RECEIPT_SCHEMA
            or str(verification_receipt.get("jobId") or "")
            != job_id
            or str(verification_receipt.get("appId") or "")
            != str(spec.get("appId") or "")
            or str(receipt_handoff.get("handoffId") or "")
            != str(handoff.get("handoffId") or "")
            or str(receipt_handoff.get("handoffDigest") or "")
            != str(handoff.get("handoffDigest") or "")
            or str(receipt_handoff.get("appBindingDigest") or "")
            != expected_app_binding
        ):
            raise ValueError(
                "the App Factory verification receipt does not match the ready job"
            )
        expected = {
            "appFactoryJobId": job_id,
            "appId": str(spec.get("appId") or ""),
            "handoffId": str(handoff.get("handoffId") or ""),
            "handoffDigest": str(handoff.get("handoffDigest") or ""),
            "candidateDigest": str(handoff.get("candidateDigest") or ""),
            "skillId": str(handoff.get("skillId") or ""),
        }
        for field, value in expected.items():
            if not value or str(bundle.get(field) or "") != value:
                raise ValueError(
                    f"capability run bundle {field} does not match the verified app"
                )
        bundle_lease = (
            dict(bundle.get("proofLease") or {})
            if isinstance(bundle.get("proofLease"), dict)
            else {}
        )
        handoff_lease = (
            dict(handoff.get("proofLease") or {})
            if isinstance(handoff.get("proofLease"), dict)
            else {}
        )
        for field in ("leaseId", "revision", "leaseDigest"):
            if bundle_lease.get(field) != handoff_lease.get(field):
                raise ValueError(
                    f"capability run bundle proofLease.{field} does not match the app"
                )

        raw_runs = bundle.get("runs")
        if (
            not isinstance(raw_runs, list)
            or not raw_runs
            or len(raw_runs) > CAPABILITY_RUN_MAX_RUNS
        ):
            raise ValueError(
                f"capability run bundle must contain 1-{CAPABILITY_RUN_MAX_RUNS} runs"
            )
        now = datetime.now(timezone.utc)
        normalized_runs: list[dict[str, Any]] = []
        run_identities: set[str] = set()
        for raw_run in raw_runs:
            if not isinstance(raw_run, dict):
                raise ValueError("every capability run must be a JSON object")
            if raw_run.get("schema") != CAPABILITY_RUN_SCHEMA:
                raise ValueError(f"every capability run must use {CAPABILITY_RUN_SCHEMA}")
            if raw_run.get("candidateActivated") is not False:
                raise ValueError("capability run must keep the candidate inactive")
            if raw_run.get("transcriptsIncluded") is not False:
                raise ValueError("capability run cannot include transcripts")
            if str(raw_run.get("status") or "") != "sealed":
                raise ValueError("only sealed capability runs can enter learning")
            for field, value in expected.items():
                if str(raw_run.get(field) or "") != value:
                    raise ValueError(
                        f"capability run {field} does not match its verified app"
                    )
            run_lease = (
                dict(raw_run.get("proofLease") or {})
                if isinstance(raw_run.get("proofLease"), dict)
                else {}
            )
            for field in ("leaseId", "revision", "leaseDigest"):
                if run_lease.get(field) != handoff_lease.get(field):
                    raise ValueError(
                        f"capability run proofLease.{field} does not match its app"
                    )
            run_id = _bounded_text(raw_run.get("runId"), 180)
            if not run_id:
                raise ValueError("every capability run requires a runId")
            source_ref = f"app-run:{expected['appId']}:{run_id}"
            if source_ref in run_identities:
                raise ValueError("capability run bundle repeats the same run identity")
            run_identities.add(source_ref)
            receipt_digest = str(raw_run.get("receiptDigest") or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", receipt_digest):
                raise ValueError("capability run receiptDigest must be SHA-256")
            receipt_payload = {
                key: value
                for key, value in raw_run.items()
                if key != "receiptDigest"
            }
            if _canonical_digest(receipt_payload) != receipt_digest:
                raise ValueError("capability run receipt digest does not match its bytes")
            outcome = str(raw_run.get("outcome") or "")
            if outcome not in CAPABILITY_RUN_OUTCOMES:
                raise ValueError("capability run outcome must be completed or blocked")
            operator_value = str(raw_run.get("operatorValue") or "")
            if operator_value not in CAPABILITY_RUN_OPERATOR_VALUES:
                raise ValueError(
                    "capability run operatorValue must be helpful, not_sure, or not_helpful"
                )
            friction = (
                dict(raw_run.get("friction") or {})
                if isinstance(raw_run.get("friction"), dict)
                else {}
            )
            friction_code = str(friction.get("code") or "")
            friction_severity = str(friction.get("severity") or "")
            if friction_code not in CAPABILITY_RUN_FRICTION_CODES:
                raise ValueError("capability run friction code is unsupported")
            if friction_severity not in CAPABILITY_RUN_FRICTION_SEVERITIES:
                raise ValueError("capability run friction severity is unsupported")
            correction_value = friction.get("correctionCount", 0)
            if (
                isinstance(correction_value, bool)
                or not isinstance(correction_value, int)
            ):
                raise ValueError("correctionCount must be an integer")
            correction_total = correction_value
            if correction_total < 0 or correction_total > 100:
                raise ValueError("correctionCount must be between 0 and 100")
            if friction_code == "none" and (
                friction_severity != "none" or correction_total
            ):
                raise ValueError(
                    "a friction-free run cannot report severity or corrections"
                )
            if friction_code != "none" and friction_severity == "none":
                raise ValueError("reported friction requires a non-zero severity")
            usual_value = friction.get("usualMinutes")
            usual_minutes: int | None = None
            if usual_value not in (None, ""):
                if (
                    isinstance(usual_value, bool)
                    or not isinstance(usual_value, int)
                ):
                    raise ValueError("usualMinutes must be an integer")
                usual_minutes = usual_value
                if usual_minutes < 1 or usual_minutes > 10_080:
                    raise ValueError("usualMinutes must be between 1 and 10080")

            started_at = _parse_utc(raw_run.get("startedAt"))
            completed_at = _parse_utc(raw_run.get("completedAt"))
            if not started_at or not completed_at or completed_at < started_at:
                raise ValueError("capability run timestamps are invalid")
            if started_at > now + timedelta(minutes=5):
                raise ValueError("capability run starts in the future")
            duration_seconds = (completed_at - started_at).total_seconds()
            if duration_seconds > CAPABILITY_RUN_MAX_DURATION_SECONDS:
                raise ValueError("capability run exceeds the seven-day duration boundary")
            steps = raw_run.get("steps")
            if (
                not isinstance(steps, list)
                or not steps
                or len(steps) > CAPABILITY_RUN_MAX_STEPS
                or any(not isinstance(item, dict) for item in steps)
            ):
                raise ValueError(
                    f"capability run must contain 1-{CAPABILITY_RUN_MAX_STEPS} steps"
                )
            if outcome == "completed" and any(
                item.get("complete") is not True for item in steps
            ):
                raise ValueError("a completed run must complete every workflow step")
            if not str(raw_run.get("proofNote") or "").strip():
                raise ValueError("capability run requires a proof note")

            estimated_return: float | None = None
            if usual_minutes is not None and outcome == "completed":
                estimated_return = round(
                    max(0.0, usual_minutes - (duration_seconds / 60.0)),
                    2,
                )
            normalized_runs.append(
                {
                    "sourceRef": source_ref,
                    "runId": run_id,
                    "receiptDigest": receipt_digest,
                    "measurements": {
                        "schema": APP_RUN_MEASUREMENT_SCHEMA,
                        "outcome": outcome,
                        "completed": outcome == "completed",
                        "durationSeconds": round(duration_seconds, 3),
                        "operatorValue": operator_value,
                        "frictionCode": friction_code,
                        "frictionSeverity": friction_severity,
                        "correctionCount": correction_total,
                        "usualMinutes": usual_minutes,
                        "operatorEstimatedMinutesReturned": estimated_return,
                        "estimateBasis": (
                            "operator_counterfactual"
                            if usual_minutes is not None
                            else "not_supplied"
                        ),
                    },
                }
            )

        materialization_id = _bounded_text(
            handoff.get("materializationId"),
            180,
        )
        approved_lineage_id = _bounded_text(
            handoff.get("approvedLineageId"),
            180,
        )
        timestamp = utc_now()
        imported = 0
        duplicates = 0
        typed_rows: list[dict[str, Any]] = []
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            materialization_row = connection.execute(
                """
                SELECT * FROM capability_skill_materializations
                WHERE materialization_id = ?
                """,
                (materialization_id,),
            ).fetchone()
            lease_row = connection.execute(
                """
                SELECT * FROM capability_proof_leases
                WHERE materialization_id = ?
                """,
                (materialization_id,),
            ).fetchone()
            lineage_row = connection.execute(
                "SELECT * FROM capability_lineages WHERE lineage_id = ?",
                (approved_lineage_id,),
            ).fetchone()
            if not materialization_row or not lease_row or not lineage_row:
                connection.rollback()
                raise ValueError(
                    "the capability lineage, materialization, or Proof Lease is missing"
                )
            materialization = self._materialization_from_row(materialization_row)
            lease = self._proof_lease_from_row(lease_row)
            assessment = self._assess_proof_lease(
                lease,
                materialization,
                provider_availability=provider_availability,
                now=timestamp,
            )
            if assessment.get("state") != "current":
                connection.rollback()
                raise ValueError(
                    "the capability Proof Lease is no longer current: "
                    f"{assessment.get('nextAction') or 're-proof before import'}"
                )
            lease_contract = (
                dict(lease.get("contract") or {})
                if isinstance(lease.get("contract"), dict)
                else {}
            )
            if (
                materialization.get("state") != "materialized_inactive"
                or materialization.get("candidateDigest")
                != expected["candidateDigest"]
                or lease.get("leaseId") != handoff_lease.get("leaseId")
                or lease.get("revision") != handoff_lease.get("revision")
                or lease_contract.get("leaseDigest")
                != handoff_lease.get("leaseDigest")
            ):
                connection.rollback()
                raise ValueError(
                    "the app outcome bundle is stale relative to its current lineage"
                )

            for item in normalized_runs:
                existing = connection.execute(
                    """
                    SELECT * FROM capability_observations
                    WHERE source_ref = ? AND capability_id = ?
                    """,
                    (item["sourceRef"], expected["skillId"]),
                ).fetchone()
                if existing:
                    existing_evidence = _decode(existing["evidence_json"], {})
                    if (
                        isinstance(existing_evidence, dict)
                        and existing_evidence.get("receiptDigest")
                        == item["receiptDigest"]
                    ):
                        duplicates += 1
                        continue
                    connection.rollback()
                    raise ValueError(
                        "a capability run identity already exists with a different digest"
                    )
                observation_id = _stable_id(
                    "observation",
                    item["sourceRef"],
                    expected["skillId"],
                )
                evidence = {
                    "schema": APP_OUTCOME_IMPORT_SCHEMA,
                    "appFactoryJobId": expected["appFactoryJobId"],
                    "appId": expected["appId"],
                    "handoffId": expected["handoffId"],
                    "handoffDigest": expected["handoffDigest"],
                    "candidateDigest": expected["candidateDigest"],
                    "skillId": expected["skillId"],
                    "materializationId": materialization_id,
                    "approvedLineageId": approved_lineage_id,
                    "leaseId": handoff_lease.get("leaseId"),
                    "leaseRevision": handoff_lease.get("revision"),
                    "leaseDigest": handoff_lease.get("leaseDigest"),
                    "runId": item["runId"],
                    "receiptDigest": item["receiptDigest"],
                    "transcriptsIncluded": False,
                    "privateRunTextStored": False,
                    "candidateActivated": False,
                }
                connection.execute(
                    """
                    INSERT INTO capability_observations (
                        observation_id, lineage_id, capability_id,
                        capability_kind, mission_id, conversation_id,
                        source_ref, source_kind, accepted_by,
                        measurements_json, evidence_json, created_at
                    ) VALUES (?, ?, ?, 'skill', '', '', ?, 'app_run', ?, ?, ?, ?)
                    """,
                    (
                        observation_id,
                        approved_lineage_id,
                        expected["skillId"],
                        item["sourceRef"],
                        _bounded_text(imported_by or "operator", 80),
                        _json(item["measurements"]),
                        _json(evidence),
                        timestamp,
                    ),
                )
                imported += 1
                typed_rows.append(
                    {
                        "observationId": observation_id,
                        "runId": item["runId"],
                        "receiptDigest": item["receiptDigest"],
                        "measurements": item["measurements"],
                    }
                )
            connection.commit()
            app_rows = connection.execute(
                """
                SELECT * FROM capability_observations
                WHERE source_kind = 'app_run'
                ORDER BY created_at DESC, observation_id DESC
                LIMIT 1000
                """
            ).fetchall()

        learning = self._app_outcome_learning(app_rows)
        return {
            "schema": APP_OUTCOME_IMPORT_SCHEMA,
            "status": "accepted_into_discovery",
            "appFactoryJobId": expected["appFactoryJobId"],
            "appId": expected["appId"],
            "skillId": expected["skillId"],
            "receivedRunCount": len(normalized_runs),
            "importedRunCount": imported,
            "duplicateRunCount": duplicates,
            "observations": typed_rows,
            "frictionPatternCount": learning["patternCount"],
            "proposalCount": len(learning["proposals"]),
            "trustRaised": False,
            "candidateActivated": False,
            "transcriptsStored": False,
            "privateRunTextStored": False,
            "nextAction": (
                "Review any repeated friction proposal in the Compounding Loop. "
                "A sealed comparison is still required before behavior can change."
            ),
        }

    @checked_action(check_constellation)
    def accept_constellation_outcome(
        self,
        *,
        constellation: dict[str, Any],
        synthesis_id: str,
        mission_id: str = "",
        accepted_by: str = "operator",
    ) -> dict[str, Any]:
        graph = constellation if isinstance(constellation, dict) else {}
        synthesis = (
            dict(graph.get("synthesis") or {})
            if isinstance(graph.get("synthesis"), dict)
            else {}
        )
        if not synthesis or synthesis.get("synthesisId") != synthesis_id:
            raise ValueError("the requested synthesis is not the active constellation synthesis")
        if str(synthesis.get("status") or "") != "ready":
            raise ValueError(
                "only a synthesis whose evidence contract is ready can enter learning"
            )
        candidate_ids = {
            str(item) for item in synthesis.get("candidateNodeIds") or []
        }
        nodes = [
            item
            for item in graph.get("nodes") or []
            if isinstance(item, dict) and str(item.get("nodeId") or "") in candidate_ids
        ]
        if not nodes:
            raise ValueError("the synthesis has no candidate nodes")
        timestamp = utc_now()
        observations: list[dict[str, Any]] = []
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for node in nodes:
                delta = read_agent_delta(node)
                evidence_count = len(delta.evidence)
                artifact_count = len(delta.artifacts)
                if not evidence_count and not artifact_count:
                    continue
                capabilities = [
                    str(item).strip()
                    for item in node.get("capabilities") or []
                    if str(item).strip()
                ] or [f"agent-role:{node.get('title') or node.get('nodeId')}"]
                for capability_id in capabilities:
                    lineage_id = self._ensure_lineage(
                        connection,
                        capability_id=capability_id,
                        capability_kind="agent_capability",
                        label=capability_id.replace(":", " · "),
                        origin="constellation",
                        metadata={"runtime": node.get("runtime") or ""},
                        now=timestamp,
                    )
                    source_ref = (
                        f"{synthesis_id}:{node.get('nodeId') or 'candidate'}"
                    )
                    observation_id = _stable_id(
                        "observation", source_ref, capability_id
                    )
                    measurements = {
                        "completed": node.get("lifecycleStage") == "completed",
                        "evidenceItemCount": evidence_count,
                        "artifactCount": artifact_count,
                        "blockerCount": len(delta.blockers),
                        "conflictCount": len(delta.conflicts),
                        "synthesisStatus": synthesis.get("status") or "",
                    }
                    evidence = {
                        "claims": len(delta.claims),
                        "evidence": delta.evidence[:12],
                        "artifacts": delta.artifacts[:12],
                        "transcriptsIncluded": False,
                    }
                    connection.execute(
                        """
                        INSERT INTO capability_observations (
                            observation_id, lineage_id, capability_id,
                            capability_kind, mission_id, conversation_id,
                            source_ref, source_kind, accepted_by,
                            measurements_json, evidence_json, created_at
                        ) VALUES (?, ?, ?, 'agent_capability', ?, ?, ?, 'synthesis', ?, ?, ?, ?)
                        ON CONFLICT(source_ref, capability_id) DO UPDATE SET
                            accepted_by = excluded.accepted_by,
                            measurements_json = excluded.measurements_json,
                            evidence_json = excluded.evidence_json
                        """,
                        (
                            observation_id,
                            lineage_id,
                            capability_id,
                            str(mission_id or ""),
                            str(graph.get("conversationId") or ""),
                            source_ref,
                            _bounded_text(accepted_by or "operator", 80),
                            _json(measurements),
                            _json(evidence),
                            timestamp,
                        ),
                    )
                    observations.append(
                        {
                            "observationId": observation_id,
                            "lineageId": lineage_id,
                            "capabilityId": capability_id,
                            "measurements": measurements,
                            "acceptedBy": _bounded_text(
                                accepted_by or "operator", 80
                            ),
                        }
                    )
            if not observations:
                connection.rollback()
                raise ValueError(
                    "the synthesis contains no typed evidence or artifacts to learn from"
                )
            connection.commit()
        return {
            "schema": "neyvia.capability_outcome_acceptance.v1",
            "status": "accepted_into_learning",
            "synthesisId": synthesis_id,
            "conversationId": graph.get("conversationId") or "",
            "missionId": str(mission_id or ""),
            "observationCount": len(observations),
            "observations": observations,
            "trustRaised": False,
            "nextAction": (
                "Neyvia recorded this as accepted outcome evidence. A comparable "
                "trial is still required before any capability trust can rise."
            ),
        }
