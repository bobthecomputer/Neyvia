"""Bounded native-tool handlers for Neyvia's durable semantic objects."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .living_applications import LivingApplication, LivingApplicationRegistry, SupervisedAutonomy
from .proof_capsules import ChangeSet, ProofCapsule, ProofCapsuleStore
from .recovery_objects import RecoveryObjectStore
from .working_memory import WorkingMemoryStore
from .semantic_missions import CollaborativeWorkspace, mission_from_message
from .durability import atomic_write_json


class SemanticToolRuntime:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.recovery = RecoveryObjectStore(self.root, "semantic-tools")
        self.proofs = ProofCapsuleStore(self.root, "semantic-tools")
        self.applications = LivingApplicationRegistry()
        self.autonomy: dict[str, SupervisedAutonomy] = {}

    def _safe_id(self, value: Any, label: str) -> str:
        text = str(value or "").strip()
        if not text or len(text) > 120 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", text):
            raise ValueError(f"{label} must be a safe identifier")
        return text

    def _managed_path(self, directory: str, identity: Any) -> Path:
        base = (self.root / ".agent_control" / directory).resolve()
        path = (base / f"{self._safe_id(identity, 'object identity')}.json").resolve()
        path.relative_to(base)
        return path

    def recovery_create(self, args: dict[str, Any]) -> dict[str, Any]:
        obj = self.recovery.create(dict(args["failedOperation"]), recovery_id=args.get("recoveryId"), operation_id=args.get("operationId"), confirmed_steps=args.get("confirmedSteps", []), uncertain_effects=args.get("uncertainEffects", []), evidence=args.get("evidence", []), retry_safety=args.get("retrySafety", "requires_reconciliation"), available_recovery_paths=args.get("availableRecoveryPaths", []), required_authority=args.get("requiredAuthority", []))
        return {"recovery": obj.to_dict(), "recoveryId": obj.recovery_id, "artifactPath": str(self.recovery._path(obj.recovery_id)), "artifacts": [str(self.recovery._path(obj.recovery_id))]}

    def recovery_read(self, args: dict[str, Any]) -> dict[str, Any]:
        obj = self.recovery.load(str(args["recoveryId"])); return {"recovery": obj.to_dict()}

    def proof_create(self, args: dict[str, Any]) -> dict[str, Any]:
        store = ProofCapsuleStore(self.root, str(args.get("sessionId") or "semantic-tools"))
        payload = dict(args); payload.pop("sessionId", None)
        for camel, snake in (("startingState", "starting_state"), ("operationId", "operation_id"), ("capsuleId", "capsule_id")):
            if camel in payload and snake not in payload:
                payload[snake] = payload.pop(camel)
        capsule = store.create(**payload)
        return {"proof": capsule.to_dict(), "proofId": capsule.capsule_id, "artifactPath": str(store._path(capsule.capsule_id)), "artifacts": [str(store._path(capsule.capsule_id))]}

    def proof_verify(self, args: dict[str, Any]) -> dict[str, Any]:
        store = ProofCapsuleStore(self.root, str(args.get("sessionId") or "semantic-tools"))
        capsule = store.load(str(args["proofId"])); result = capsule.prove(self.root); store.save(capsule)
        return {"proofId": capsule.capsule_id, "verification": result, "proof": capsule.to_dict()}

    def changeset_create(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = dict(args); payload.pop("sessionId", None); change = ChangeSet(**payload)
        path = self._managed_path("change_sets", change.change_id); atomic_write_json(path, change.to_dict())
        return {"changeSet": change.to_dict(), "changeId": change.change_id, "artifactPath": str(path), "artifacts": [str(path)]}

    def changeset_verify(self, args: dict[str, Any]) -> dict[str, Any]:
        path = Path(str(args["path"])).resolve(); managed = (self.root / ".agent_control" / "change_sets").resolve(); path.relative_to(managed); value = json.loads(path.read_text(encoding="utf-8")); change = ChangeSet(**{ "intended_behavior": value["intendedBehavior"], "source_modifications": value["sourceModifications"], "generated_artifacts": value.get("generatedArtifacts", []), "affected_contracts": value.get("affectedContracts", []), "migrations": value.get("migrations", []), "compatibility_impact": value.get("compatibilityImpact", {}), "tests_and_proof": value.get("testsAndProof", []), "rollback_boundary": value.get("rollbackBoundary", {}), "change_id": value.get("changeId", "") }); return {"changeId": change.change_id, "verification": change.verify_coherence(self.root)}

    def memory_project(self, args: dict[str, Any]) -> dict[str, Any]:
        return WorkingMemoryStore(self.root, str(args["sessionId"])).project(str(args.get("query") or ""), token_budget=int(args.get("tokenBudget") or 1800))

    def memory_read(self, args: dict[str, Any]) -> dict[str, Any]:
        return WorkingMemoryStore(self.root, str(args["sessionId"])).snapshot()

    def memory_find(self, args: dict[str, Any]) -> dict[str, Any]:
        return WorkingMemoryStore(self.root, str(args["sessionId"])).find(
            str(args.get("query") or ""), limit=int(args.get("limit") or 10),
            offset=int(args.get("offset") or 0))

    def memory_retrieve(self, args: dict[str, Any]) -> dict[str, Any]:
        record_id = str(args["recordId"]).strip()
        if not re.fullmatch(r"(?:wm_[a-f0-9]{16}|objective)", record_id):
            raise ValueError("recordId must be an exact working-memory record ID")
        store = WorkingMemoryStore(self.root, str(args["sessionId"]))
        record = store.retrieve(record_id)
        if record is None:
            return {"schema": "neyvia.working_memory_retrieval.v1", "memoryId": store.memory_id,
                    "recordId": record_id, "status": "not_found"}
        max_chars = max(512, min(int(args.get("maxChars") or 12000), 20000))
        encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(encoded) > max_chars:
            return {"schema": "neyvia.working_memory_retrieval.v1", "memoryId": store.memory_id,
                    "recordId": record_id, "status": "too_large", "recordSha256": record.get("recordSha256"),
                    "chars": len(encoded), "maxChars": max_chars}
        return {"schema": "neyvia.working_memory_retrieval.v1", "memoryId": store.memory_id,
                "recordId": record_id, "status": "found", "record": record}

    def mission_create(self, args: dict[str, Any]) -> dict[str, Any]:
        mission = mission_from_message(str(args["desiredOutcome"]), conversation_id=str(args.get("conversationId") or args["missionId"]), turn_id=str(args.get("turnId") or args["missionId"]), acceptance_gates=args.get("acceptanceGates", ()))
        mission.mission_id = self._safe_id(args["missionId"], "missionId"); path = self.root / ".agent_control" / "missions" / f"{mission.mission_id}.json"; atomic_write_json(path, mission.to_dict()); return {"mission": mission.to_dict(), "missionId": mission.mission_id, "artifactPath": str(path), "artifacts": [str(path)]}

    def application_register(self, args: dict[str, Any]) -> dict[str, Any]:
        identity = self._safe_id(args["applicationId"], "applicationId")
        path = self._managed_path("living_applications", identity)
        if path.exists():
            raise ValueError("Application already exists; preserve its history before updating")
        app = LivingApplication(application_id=identity, source=dict(args.get("source") or {}), build_recipe=dict(args.get("buildRecipe") or {}), health=dict(args.get("health") or {}), rollback=dict(args.get("rollback") or {}))
        self.applications.register(app); atomic_write_json(path, app.as_dict()); return {"application": app.as_dict(), "applicationId": app.application_id, "artifactPath": str(path), "artifacts": [str(path)]}

    def application_read(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self._managed_path("living_applications", args["applicationId"])
        return {"application": json.loads(path.read_text(encoding="utf-8"))}

    def autonomy_admit(self, args: dict[str, Any]) -> dict[str, Any]:
        policy_id = self._safe_id(args.get("policyId"), "policyId")
        path = self._managed_path("autonomy", policy_id)
        if not path.exists():
            return {"ok": False, "status": "authority_required", "policyId": policy_id, "message": "No trusted persisted autonomy policy exists for this policyId."}
        raw = json.loads(path.read_text(encoding="utf-8"))
        policy = SupervisedAutonomy.from_state_file(path)
        decision = policy.authorize(str(args.get("action") or ""), cost=float(args.get("cost") or 0), evidence_count=int(args.get("evidenceCount") or 0), authority=bool(raw.get("operatorAuthority") is True))
        return {"ok": decision["allowed"], "status": "admitted" if decision["allowed"] else "blocked", "policyId": policy_id, "decision": decision, "artifacts": [str(path)]}

    def autonomy_revoke(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self._managed_path("autonomy", args["policyId"])
        policy = SupervisedAutonomy.from_state_file(path)
        policy.revoke(str(args.get("reason") or "operator revoked"))
        return {"policy": policy.as_dict(), "policyId": str(args["policyId"]), "artifacts": [str(path)]}
