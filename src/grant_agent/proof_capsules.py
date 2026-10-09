"""Durable, independently verifiable proof capsules and coherent change sets."""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .durability import atomic_write_json

CAPSULE_SCHEMA = "fluxio.proof_capsule.v1"
CHANGE_SET_SCHEMA = "fluxio.change_set.v1"


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rows(value: object, name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"{name} must be a list of objects")
    return [dict(row) for row in value]


@dataclass
class ProofCapsule:
    claim: str
    build: dict[str, Any]
    environment: dict[str, Any]
    starting_state: dict[str, Any]
    journey: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    result: dict[str, Any]
    limitations: list[str] = field(default_factory=list)
    reproduction: dict[str, Any] = field(default_factory=dict)
    capsule_id: str = field(default_factory=lambda: f"proof_{uuid.uuid4().hex[:12]}")
    operation_id: str | None = None
    verification: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not self.claim.strip() or not isinstance(self.build, dict) or not isinstance(self.environment, dict):
            raise ValueError("claim, build, and environment are required")
        self.journey = _rows(self.journey, "journey")
        self.actions = _rows(self.actions, "actions")
        self.artifacts = _rows(self.artifacts, "artifacts")
        if not isinstance(self.result, dict):
            raise ValueError("result must be an object")
        self.limitations = [str(item) for item in self.limitations]

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {"schema": CAPSULE_SCHEMA, "capsuleId": self.capsule_id, "operationId": self.operation_id, "claim": self.claim, "build": self.build, "environment": self.environment, "startingState": self.starting_state, "journey": self.journey, "actions": self.actions, "artifacts": self.artifacts, "result": self.result, "limitations": self.limitations, "reproduction": self.reproduction, "verification": self.verification, "createdAt": self.created_at}
        if include_hash:
            value["contentHash"] = _hash(value)
        return value

    @property
    def content_hash(self) -> str:
        return _hash(self.to_dict(include_hash=False))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProofCapsule":
        if value.get("schema") != CAPSULE_SCHEMA:
            raise ValueError("Unsupported proof capsule schema")
        obj = cls(capsule_id=str(value.get("capsuleId") or ""), operation_id=value.get("operationId"), claim=str(value.get("claim") or ""), build=dict(value.get("build") or {}), environment=dict(value.get("environment") or {}), starting_state=dict(value.get("startingState") or {}), journey=_rows(value.get("journey"), "journey"), actions=_rows(value.get("actions"), "actions"), artifacts=_rows(value.get("artifacts"), "artifacts"), result=dict(value.get("result") or {}), limitations=list(value.get("limitations") or []), reproduction=dict(value.get("reproduction") or {}), verification=dict(value.get("verification") or {}), created_at=str(value.get("createdAt") or _now()))
        if value.get("contentHash") is not None and value["contentHash"] != obj.content_hash:
            raise ValueError("Proof capsule content hash mismatch")
        return obj

    def verify_artifacts(self, root: Path) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        for item in self.artifacts:
            raw = str(item.get("path") or "").strip()
            expected = str(item.get("sha256") or "").lower()
            if not raw or len(expected) != 64:
                checks.append({"path": raw, "ok": False, "reason": "path_or_sha256_missing"})
                continue
            path = Path(raw)
            if not path.is_absolute():
                path = root / path
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root.resolve())
            except (OSError, ValueError):
                checks.append({"path": raw, "ok": False, "reason": "artifact_outside_or_missing"})
                continue
            actual = sha256_file(resolved)
            checks.append({"path": raw, "expectedSha256": expected, "actualSha256": actual, "ok": actual == expected})
        passed = bool(checks) and all(row["ok"] for row in checks)
        self.verification = {"artifactChecks": checks, "artifactsVerified": passed, "verifiedAt": _now(), "independent": True}
        return self.verification

    def prove(self, root: Path) -> dict[str, Any]:
        verification = self.verify_artifacts(root)
        result_passed = str(self.result.get("status") or self.result.get("outcome") or "").lower() in {"passed", "pass", "success", "verified"}
        # Byte integrity and a reported result do not establish the semantic
        # claim. Only an authoritative journey verifier (a separate harness)
        # may promote that field; caller supplied ``verified`` flags are inert.
        # No serialized capsule field is trusted as an authority signal. A
        # future in-process verifier may promote this through a private API;
        # the public native tool intentionally remains evidence-only.
        self.verification.update({"claimProven": False, "semanticClaimStatus": "artifact_integrity_only", "resultPassed": result_passed, "callerVerifiedFlagIgnored": True})
        return self.verification


@dataclass
class ChangeSet:
    intended_behavior: str
    source_modifications: list[dict[str, Any]]
    generated_artifacts: list[dict[str, Any]] = field(default_factory=list)
    affected_contracts: list[str] = field(default_factory=list)
    migrations: list[dict[str, Any]] = field(default_factory=list)
    compatibility_impact: dict[str, Any] = field(default_factory=dict)
    tests_and_proof: list[dict[str, Any]] = field(default_factory=list)
    rollback_boundary: dict[str, Any] = field(default_factory=dict)
    change_id: str = field(default_factory=lambda: f"change_{uuid.uuid4().hex[:12]}")
    verification: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {"schema": CHANGE_SET_SCHEMA, "changeId": self.change_id, "intendedBehavior": self.intended_behavior, "sourceModifications": self.source_modifications, "generatedArtifacts": self.generated_artifacts, "affectedContracts": self.affected_contracts, "migrations": self.migrations, "compatibilityImpact": self.compatibility_impact, "testsAndProof": self.tests_and_proof, "rollbackBoundary": self.rollback_boundary, "verification": self.verification}
        if include_hash:
            value["contentHash"] = _hash(value)
        return value

    def verify_coherence(self, root: Path) -> dict[str, Any]:
        checks = []
        for generated in self.generated_artifacts:
            path = Path(str(generated.get("path") or "")); path = path if path.is_absolute() else root / path
            expected = str(generated.get("sha256") or "")
            try:
                actual = sha256_file(path.resolve(strict=True)); ok = actual == expected
            except OSError:
                actual = ""; ok = False
            checks.append({"path": str(generated.get("path") or ""), "expectedSha256": expected, "actualSha256": actual, "ok": ok})
        self.verification = {"generatedChecks": checks, "sourceGeneratedCoherent": bool(checks) and all(row["ok"] for row in checks), "rollbackBoundaryDeclared": bool(self.rollback_boundary), "verifiedAt": _now()}
        return self.verification


class ProofCapsuleStore:
    def __init__(self, root: Path, scope: str = "default") -> None:
        self.base = Path(root) / ".agent_control" / "proof_capsules" / _hash(scope)[:24]
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, capsule_id: str) -> Path:
        return self.base / f"{_hash(capsule_id)}.json"

    def save(self, capsule: ProofCapsule) -> Path:
        return atomic_write_json(self._path(capsule.capsule_id), capsule.to_dict())

    def load(self, capsule_id: str) -> ProofCapsule:
        return ProofCapsule.from_dict(json.loads(self._path(capsule_id).read_text(encoding="utf-8")))

    def create(self, **kwargs: Any) -> ProofCapsule:
        capsule = ProofCapsule(**kwargs)
        self.save(capsule)
        return capsule
