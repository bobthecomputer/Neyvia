"""Durable registry objects for applications and supervised autonomy.

The registry records provenance and control decisions; it does not publish,
restart, or otherwise operate an external service.  Callers must supply
post-action evidence before an action can be marked successful.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .durability import atomic_write_json


LIVING_APPLICATION_SCHEMA = "neyvia.living_application.v1"
AUTONOMY_SCHEMA = "neyvia.supervised_autonomy.v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: object) -> str:
    return str(value or "").strip()


def _list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, Iterable):
        return []
    return [_text(item) for item in value if _text(item)]


def sha256_file(path: str | Path) -> str:
    """Hash the exact bytes on disk; missing/unreadable artifacts raise."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifact_hash(path: str | Path, expected_hash: str) -> bool:
    expected = _text(expected_hash).lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        return False
    try:
        return sha256_file(path).lower() == expected
    except (OSError, ValueError):
        return False


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    path: str
    sha256: str
    kind: str = "artifact"
    created_at: str = field(default_factory=_now)

    @classmethod
    def from_file(cls, artifact_id: str, path: str | Path, *, kind: str = "artifact") -> "ArtifactRecord":
        resolved = Path(path).resolve()
        return cls(_text(artifact_id), str(resolved), sha256_file(resolved), _text(kind) or "artifact")

    def verify(self) -> bool:
        return verify_artifact_hash(self.path, self.sha256)

    def as_dict(self) -> dict[str, Any]:
        return {"artifactId": self.artifact_id, "path": self.path, "sha256": self.sha256,
                "kind": self.kind, "createdAt": self.created_at, "verified": self.verify()}


@dataclass
class LivingApplication:
    application_id: str
    source: dict[str, Any] = field(default_factory=dict)
    build_recipe: dict[str, Any] = field(default_factory=dict)
    artifacts: list[ArtifactRecord] = field(default_factory=list)
    proofs: list[dict[str, Any]] = field(default_factory=list)
    deployments: list[dict[str, Any]] = field(default_factory=list)
    data_contracts: list[dict[str, Any]] = field(default_factory=list)
    permissions: list[dict[str, Any]] = field(default_factory=list)
    health: dict[str, Any] = field(default_factory=dict)
    feedback: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    rollback: dict[str, Any] = field(default_factory=dict)

    def add_artifact(self, artifact: ArtifactRecord) -> None:
        if not artifact.verify():
            raise ValueError(f"Artifact hash could not be verified: {artifact.path}")
        if any(item.artifact_id == artifact.artifact_id and item.path == artifact.path
               and item.sha256 == artifact.sha256 and item.kind == artifact.kind
               for item in self.artifacts):
            return
        self.artifacts = [item for item in self.artifacts if item.artifact_id != artifact.artifact_id]
        self.artifacts.append(artifact)
        self.history.append({"event": "artifact_registered", "artifactId": artifact.artifact_id, "sha256": artifact.sha256, "at": _now()})

    def record_deployment(self, deployment: Mapping[str, Any]) -> dict[str, Any]:
        """Record a deployment receipt only after local artifact verification."""
        row = dict(deployment)
        artifact_id = _text(row.get("artifactId"))
        artifact = next((item for item in self.artifacts if item.artifact_id == artifact_id), None)
        if artifact is None or not artifact.verify():
            raise ValueError("deployment artifact is missing or its current hash does not verify")
        row["artifactSha256"] = artifact.sha256
        row["recordedAt"] = _now()
        row["execution"] = "receipt_only"
        self.deployments.append(row)
        self.history.append({"event": "deployment_receipt", "artifactId": artifact_id, "at": row["recordedAt"]})
        return row

    def as_dict(self) -> dict[str, Any]:
        return {"schema": LIVING_APPLICATION_SCHEMA, "applicationId": self.application_id,
                "source": dict(self.source), "buildRecipe": dict(self.build_recipe),
                "artifacts": [item.as_dict() for item in self.artifacts], "proofs": list(self.proofs),
                "deployments": list(self.deployments), "dataContracts": list(self.data_contracts),
                "permissions": list(self.permissions), "health": dict(self.health),
                "feedback": list(self.feedback), "history": list(self.history), "rollback": dict(self.rollback)}


class LivingApplicationRegistry:
    def __init__(self) -> None:
        self._applications: dict[str, LivingApplication] = {}

    def register(self, application: LivingApplication) -> LivingApplication:
        if not application.application_id:
            raise ValueError("application_id is required")
        self._applications[application.application_id] = application
        return application

    def get(self, application_id: str) -> LivingApplication | None:
        return self._applications.get(_text(application_id))

    def snapshot(self) -> dict[str, Any]:
        return {"schema": LIVING_APPLICATION_SCHEMA, "applications": [item.as_dict() for item in self._applications.values()]}


@dataclass
class SupervisedAutonomy:
    objective: str
    boundaries: list[str] = field(default_factory=list)
    permitted_actions: set[str] = field(default_factory=set)
    escalation_conditions: list[str] = field(default_factory=list)
    evidence_threshold: int = 1
    budget: float = 0.0
    budget_used: float = 0.0
    health: str = "unknown"
    self_repair_policy: dict[str, Any] = field(default_factory=dict)
    revoked: bool = False
    revocation_reason: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)
    state_path: str = ""

    @classmethod
    def from_state_file(cls, path: str | Path) -> "SupervisedAutonomy":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            objective=_text(data.get("objective")), boundaries=_list(data.get("boundaries")),
            permitted_actions=set(_list(data.get("permittedActions"))),
            escalation_conditions=_list(data.get("escalationConditions")),
            evidence_threshold=max(0, int(data.get("evidenceThreshold", 1))),
            budget=float(data.get("budget", 0)), budget_used=float(data.get("budgetUsed", 0)),
            health=_text(data.get("health") or "unknown"), self_repair_policy=dict(data.get("selfRepairPolicy") or {}),
            revoked=bool(data.get("revoked")), revocation_reason=_text(data.get("revocationReason")),
            history=list(data.get("history") or []), state_path=str(Path(path).resolve()),
        )

    @contextmanager
    def _state_lock(self):
        if not self.state_path:
            yield
            return
        from .harness_jobs import _exclusive_job_lock
        Path(self.state_path).parent.mkdir(parents=True, exist_ok=True)
        with _exclusive_job_lock(Path(self.state_path)):
            yield

    def _reload_locked(self) -> None:
        if not self.state_path or not Path(self.state_path).is_file():
            return
        data = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        self.budget_used = float(data.get("budgetUsed", self.budget_used))
        self.budget = float(data.get("budget", self.budget))
        self.permitted_actions = set(_list(data.get("permittedActions")))
        self.evidence_threshold = max(0, int(data.get("evidenceThreshold", 1)))
        self.revoked = bool(data.get("revoked", self.revoked))
        self.revocation_reason = _text(data.get("revocationReason") or self.revocation_reason)
        self.history = list(data.get("history") or self.history)

    def _persist_locked(self) -> None:
        if self.state_path:
            prior = json.loads(Path(self.state_path).read_text(encoding="utf-8")) if Path(self.state_path).is_file() else {}
            atomic_write_json(Path(self.state_path), {**prior, **self.as_dict()})

    def authorize(self, action: str, *, cost: float = 0.0, evidence_count: int = 0, authority: bool = False) -> dict[str, Any]:
        """Return a fail-closed decision; this method never executes ``action``."""
        if not all(math.isfinite(value) and value >= 0 for value in (cost, self.budget, self.budget_used)):
            raise ValueError("Autonomy costs and budgets must be finite non-negative numbers")
        with self._state_lock():
            self._reload_locked()
            if not all(math.isfinite(value) and value >= 0 for value in (cost, self.budget, self.budget_used)):
                raise ValueError("Persisted autonomy budgets must be finite non-negative numbers")
            name = _text(action)
            reasons: list[str] = []
            if self.revoked: reasons.append("autonomy_revoked")
            if name not in self.permitted_actions: reasons.append("action_not_permitted")
            if not authority: reasons.append("authority_not_granted")
            if evidence_count < max(0, self.evidence_threshold): reasons.append("evidence_threshold_not_met")
            if cost < 0 or self.budget_used + cost > self.budget: reasons.append("budget_exhausted")
            allowed = not reasons
            if allowed: self.budget_used += cost
            decision = {"schema": AUTONOMY_SCHEMA, "action": name, "allowed": allowed, "reasons": reasons,
                        "budget": {"limit": self.budget, "used": self.budget_used, "remaining": max(0.0, self.budget - self.budget_used)},
                        "revoked": self.revoked, "executed": False, "at": _now()}
            self.history.append(decision)
            self._persist_locked()
            return decision

    def revoke(self, reason: str) -> None:
        with self._state_lock():
            self._reload_locked()
            self.revoked = True
            self.revocation_reason = _text(reason) or "revoked"
            self.history.append({"event": "revoked", "reason": self.revocation_reason, "at": _now()})
            self._persist_locked()

    def as_dict(self) -> dict[str, Any]:
        return {"schema": AUTONOMY_SCHEMA, "objective": self.objective, "boundaries": list(self.boundaries),
                "permittedActions": sorted(self.permitted_actions), "escalationConditions": list(self.escalation_conditions),
                "evidenceThreshold": self.evidence_threshold, "budget": self.budget, "budgetUsed": self.budget_used,
                "health": self.health, "selfRepairPolicy": dict(self.self_repair_policy), "revoked": self.revoked,
                "revocationReason": self.revocation_reason, "history": list(self.history)}


def authorize_autonomy_action(policy: SupervisedAutonomy, action: str, *, cost: float = 0.0, evidence_count: int = 0, authority: bool = False) -> dict[str, Any]:
    return policy.authorize(action, cost=cost, evidence_count=evidence_count, authority=authority)
