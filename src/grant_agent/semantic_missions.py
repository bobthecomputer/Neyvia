"""Durable semantic objects for missions and collaborative conversations.

This module is intentionally independent of the existing conversation store.  It
provides a narrow integration seam: callers pass a conversation/turn identity
and receive immutable, provenance-bearing objects that can be persisted beside
the existing ledger.  A claim is never promoted to completed merely because a
message says it is complete; a Mission gate needs explicit, attributable proof.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA = "neyvia.semantic-mission.v1"
WORKSPACE_SCHEMA = "neyvia.collaborative-workspace.v1"
_SHA256 = re.compile(r"\b[0-9a-fA-F]{64}\b")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Provenance:
    """Identity of the source turn/event that produced a semantic object."""

    source_id: str
    source_kind: str = "conversation.turn"
    conversation_id: str = ""
    turn_id: str = ""
    source_hash: str = ""
    parent_ids: tuple[str, ...] = ()
    recorded_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not str(self.source_id).strip():
            raise ValueError("provenance source_id is required")

    @property
    def fingerprint(self) -> str:
        return _digest(asdict(self))


@dataclass
class MissionGate:
    gate_id: str
    statement: str
    status: str = "pending"
    evidence: list[dict[str, Any]] = field(default_factory=list)
    verified_at: str | None = None
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        self.status = str(self.status or "pending").lower()
        if self.status not in {"pending", "verified", "failed", "blocked"}:
            raise ValueError(f"unknown mission gate status: {self.status}")
        if not str(self.gate_id).strip() or not str(self.statement).strip():
            raise ValueError("mission gates require gate_id and statement")

    @property
    def proven(self) -> bool:
        return self.status == "verified" and bool(self.evidence)


@dataclass
class Mission:
    """A resumable agreement with explicit authority and proof boundaries."""

    mission_id: str
    desired_outcome: str
    acceptance_gates: list[MissionGate]
    boundaries: list[str] = field(default_factory=list)
    exact_routes: list[dict[str, Any]] = field(default_factory=list)
    authority: dict[str, Any] = field(default_factory=dict)
    completed_work: list[dict[str, Any]] = field(default_factory=list)
    unresolved_risks: list[dict[str, Any]] = field(default_factory=list)
    evidence_requirements: list[str] = field(default_factory=list)
    stopping_condition: str = "All acceptance gates are verified and no blocking risk remains."
    continuation_state: dict[str, Any] = field(default_factory=dict)
    status: str = "planned"
    workspace_id: str = ""
    provenance: Provenance | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.status = str(self.status or "planned").lower()
        if self.status not in {"planned", "running", "blocked", "completed", "failed"}:
            raise ValueError(f"unknown mission status: {self.status}")
        if not str(self.mission_id).strip() or not str(self.desired_outcome).strip():
            raise ValueError("mission_id and desired_outcome are required")
        self.acceptance_gates = [g if isinstance(g, MissionGate) else MissionGate(**g) for g in self.acceptance_gates]

    @property
    def proven_complete(self) -> bool:
        return bool(self.acceptance_gates) and all(g.proven for g in self.acceptance_gates) and not any(
            str(r.get("status", "open")).lower() in {"open", "blocking", "unresolved"} for r in self.unresolved_risks
        )

    def start(self) -> "Mission":
        if self.status == "completed":
            raise ValueError("completed missions cannot be restarted")
        self.status, self.updated_at = "running", _now()
        return self

    def verify_gate(self, gate_id: str, evidence: Mapping[str, Any], *, source: Provenance | None = None) -> MissionGate:
        """Verify one gate only with explicit attributable proof.

        ``verified`` must be true and the evidence must identify an artifact,
        proof capsule, operation receipt, or observation hash.  Narrative text
        alone is deliberately rejected.
        """
        gate = next((g for g in self.acceptance_gates if g.gate_id == gate_id), None)
        if gate is None:
            raise KeyError(gate_id)
        record = dict(evidence)
        if record.get("verified") is not True:
            raise ValueError("gate evidence must explicitly set verified=true")
        identity = record.get("proofId") or record.get("proof_id") or record.get("artifactHash") or record.get("sha256") or record.get("receiptId") or record.get("observationId")
        if not identity:
            raise ValueError("gate evidence needs a proof, artifact, receipt, or observation identity")
        record.setdefault("recordedAt", _now())
        if source:
            record.setdefault("provenance", asdict(source))
            gate.provenance = source
        gate.evidence.append(record)
        gate.status, gate.verified_at = "verified", record["recordedAt"]
        self.updated_at = _now()
        return gate

    def mark_completed(self) -> "Mission":
        if not self.proven_complete:
            missing = [g.gate_id for g in self.acceptance_gates if not g.proven]
            raise ValueError(f"mission remains unproven; missing verified gates: {', '.join(missing) or 'none'}")
        self.status, self.updated_at = "completed", _now()
        return self

    def block(self, reason: str, *, provenance: Provenance | None = None) -> None:
        self.status = "blocked"
        self.unresolved_risks.append({"riskId": _id("risk"), "status": "blocking", "reason": str(reason), "provenance": asdict(provenance) if provenance else None})
        self.updated_at = _now()

    def continue_from(self, checkpoint: Mapping[str, Any], *, provenance: Provenance | None = None) -> "Mission":
        """Persist a resumable checkpoint without treating it as completion."""
        checkpoint = dict(checkpoint)
        identity = checkpoint.get("checkpointId") or checkpoint.get("proofId") or checkpoint.get("receiptId")
        if not identity:
            raise ValueError("continuation checkpoint requires checkpointId, proofId, or receiptId")
        if checkpoint.get("verified") is True and not checkpoint.get("evidence"):
            raise ValueError("verified continuation requires explicit evidence")
        checkpoint.setdefault("recordedAt", _now())
        checkpoint.setdefault("provenance", asdict(provenance) if provenance else None)
        self.continuation_state = {**self.continuation_state, "latestCheckpoint": checkpoint, "resumable": True}
        self.updated_at = _now()
        return self

    def to_dict(self) -> dict[str, Any]:
        value = json.loads(_canonical(asdict(self)))
        value["schema"] = SCHEMA
        value["provenanceHash"] = self.provenance.fingerprint if self.provenance else _digest(value)
        # Runtime responses use the same camelCase identity vocabulary as the
        # conversation store while retaining the dataclass fields for local
        # callers that prefer Python naming.
        value.update({
            "missionId": self.mission_id,
            "desiredOutcome": self.desired_outcome,
            "acceptanceGates": [{**g, "gateId": g.get("gate_id", g.get("gateId"))} for g in value["acceptance_gates"]],
            "exactRoutes": self.exact_routes,
            "completedWork": self.completed_work,
            "unresolvedRisks": self.unresolved_risks,
            "evidenceRequirements": self.evidence_requirements,
            "stoppingCondition": self.stopping_condition,
            "continuationState": self.continuation_state,
            "workspaceId": self.workspace_id,
        })
        return value


@dataclass
class WorkspaceObject:
    object_id: str
    object_type: str
    content: dict[str, Any]
    provenance: Provenance
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": WORKSPACE_SCHEMA, "objectId": self.object_id, "objectType": self.object_type, "content": self.content, "provenance": asdict(self.provenance), "createdAt": self.created_at, "objectHash": _digest({"objectId": self.object_id, "objectType": self.object_type, "content": self.content, "provenance": asdict(self.provenance)})}


def _classify(text: str) -> str:
    lowered = text.lower().strip()
    if re.search(r"\b(i approve|approved|approval|go ahead|authori[sz]e)\b", lowered):
        return "approval"
    if re.search(r"\b(correct|correction|actually|change that|instead|clarif(?:y|ication))\b", lowered):
        return "correction"
    if re.search(r"\b(decide|decision|we will|let's|choose|use |must )\b", lowered):
        return "decision"
    if _SHA256.search(text) or re.search(r"(?:[A-Za-z]:\\|/|https?://)[^\s]+", text):
        return "artifact_reference"
    return "observation"


class CollaborativeWorkspace:
    """Turns ordinary messages into durable semantic workspace objects."""

    def __init__(self, workspace_id: str, *, storage_path: str | Path | None = None) -> None:
        self.workspace_id = str(workspace_id).strip() or _id("workspace")
        self.storage_path = Path(storage_path) if storage_path else None
        self.objects: list[WorkspaceObject] = []
        if self.storage_path and self.storage_path.exists():
            for line in self.storage_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                raw = json.loads(line)
                self.objects.append(WorkspaceObject(raw["objectId"], raw["objectType"], raw["content"], Provenance(**raw["provenance"]), raw.get("createdAt", _now())))

    def ingest_message(self, content: str, *, conversation_id: str, turn_id: str, role: str = "user", kind: str | None = None, metadata: Mapping[str, Any] | None = None) -> WorkspaceObject:
        text = str(content or "").strip()
        if not text:
            raise ValueError("message content is required")
        source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        provenance = Provenance(source_id=turn_id, conversation_id=conversation_id, turn_id=turn_id, source_hash=source_hash, parent_ids=tuple(str(x) for x in (metadata or {}).get("parentIds", ())))
        object_type = str(kind or _classify(text)).strip().lower()
        if object_type not in {"decision", "correction", "approval", "artifact_reference", "observation"}:
            raise ValueError(f"unsupported workspace object type: {object_type}")
        content_data: dict[str, Any] = {"text": text, "role": role}
        if metadata:
            content_data["metadata"] = dict(metadata)
        if object_type == "approval":
            content_data.update({"approved": True, "scope": (metadata or {}).get("scope") or text, "approvalIdentity": (metadata or {}).get("approvalIdentity") or turn_id})
        elif object_type == "artifact_reference":
            content_data["references"] = [{"value": token, "sha256": token.lower() if _SHA256.fullmatch(token) else None} for token in re.findall(r"https?://[^\s]+|[A-Za-z]:\\[^\s]+|/[A-Za-z0-9_./-]+|[0-9a-fA-F]{64}", text)]
        elif object_type in {"decision", "correction"}:
            content_data["statement"] = text
            content_data["state"] = "proposed" if object_type == "decision" else "supersedes_or_clarifies"
        item = WorkspaceObject(_id(object_type), object_type, content_data, provenance)
        self.objects.append(item)
        self._persist(item)
        return item

    def _persist(self, item: WorkspaceObject) -> None:
        if not self.storage_path:
            return
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical(item.to_dict()) + "\n")

    def snapshot(self) -> dict[str, Any]:
        return {"schema": WORKSPACE_SCHEMA, "workspaceId": self.workspace_id, "objects": [item.to_dict() for item in self.objects], "objectCount": len(self.objects), "snapshotHash": _digest([item.to_dict() for item in self.objects])}

    def decisions(self) -> list[WorkspaceObject]:
        return [item for item in self.objects if item.object_type == "decision"]


def mission_from_message(content: str, *, conversation_id: str, turn_id: str, workspace_id: str = "", acceptance_gates: Iterable[str] = ()) -> Mission:
    """Integration seam for a conversation turn that expresses a mission."""
    text = str(content or "").strip()
    provenance = Provenance(source_id=turn_id, conversation_id=conversation_id, turn_id=turn_id, source_hash=hashlib.sha256(text.encode()).hexdigest())
    gates = [MissionGate(_id("gate"), statement) for statement in acceptance_gates]
    return Mission(_id("mission"), text, gates, workspace_id=workspace_id, provenance=provenance, continuation_state={"sourceTurnId": turn_id, "sourceConversationId": conversation_id})


__all__ = ["Mission", "MissionGate", "Provenance", "WorkspaceObject", "CollaborativeWorkspace", "mission_from_message", "SCHEMA", "WORKSPACE_SCHEMA"]
