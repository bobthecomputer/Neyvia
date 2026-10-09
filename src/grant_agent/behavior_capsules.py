"""Executable behavior capsules for Neyvia Native.

Markdown remains the human-readable layer.  A behavior capsule is the machine
contract compiled around it: bounded phases, tool scopes, evidence gates,
resource policy, and a seven-dimensional behavior vector.  The implementation
is deliberately deterministic and provider-neutral; it does not claim access
to a model's latent activations.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


CAPSULE_SCHEMA = "neyvia.behavior-capsule/v1"
PLAN_SCHEMA = "neyvia.behavior-plan/v1"
_VECTOR_KEYS = (
    "initiative",
    "rigor",
    "exploration",
    "toolAutonomy",
    "compression",
    "interruptionSensitivity",
    "verificationPressure",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _bounded_unit(value: object, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return round(max(0.0, min(1.0, number)), 4)


def _safe_id(value: object) -> str:
    clean = re.sub(r"[^a-z0-9._-]+", "-", str(value or "").strip().lower()).strip(".-")
    if not clean:
        raise ValueError("A behavior capsule id is required.")
    return clean[:96]


@dataclass(frozen=True)
class BehaviorPhase:
    phase_id: str
    objective: str
    required_evidence: tuple[str, ...]
    allowed_tool_scopes: tuple[str, ...]
    maximum_turns: int

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "BehaviorPhase":
        phase_id = _safe_id(value.get("id") or value.get("phaseId"))
        maximum_turns = max(1, min(32, int(value.get("maximumTurns") or 4)))
        return cls(
            phase_id=phase_id,
            objective=str(value.get("objective") or phase_id).strip(),
            required_evidence=tuple(
                str(item).strip()
                for item in value.get("requiredEvidence", ())
                if str(item).strip()
            ),
            allowed_tool_scopes=tuple(
                str(item).strip()
                for item in value.get("allowedToolScopes", ("workspace.read",))
                if str(item).strip()
            ),
            maximum_turns=maximum_turns,
        )


@dataclass(frozen=True)
class BehaviorCapsule:
    capsule_id: str
    label: str
    version: int
    task_kinds: tuple[str, ...]
    keywords: tuple[str, ...]
    behavior_vector: dict[str, float]
    phases: tuple[BehaviorPhase, ...]
    specialist_roles: tuple[str, ...]
    skill_ids: tuple[str, ...]
    proof_gates: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    mutation_expected: bool
    low_resource_compatible: bool

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "BehaviorCapsule":
        vector_source = value.get("behaviorVector") or {}
        vector = {
            key: _bounded_unit(vector_source.get(key), 0.5)
            for key in _VECTOR_KEYS
        }
        phases = tuple(
            BehaviorPhase.from_mapping(item)
            for item in value.get("phases", ())
            if isinstance(item, dict)
        )
        if not phases:
            raise ValueError("A behavior capsule requires at least one phase.")
        proof_gates = tuple(
            str(item).strip()
            for item in value.get("proofGates", ())
            if str(item).strip()
        )
        return cls(
            capsule_id=_safe_id(value.get("id")),
            label=str(value.get("label") or value.get("id") or "Behavior").strip(),
            version=max(1, int(value.get("version") or 1)),
            task_kinds=tuple(
                _safe_id(item) for item in value.get("taskKinds", ("general",))
            ),
            keywords=tuple(
                str(item).strip().lower()
                for item in value.get("keywords", ())
                if str(item).strip()
            ),
            behavior_vector=vector,
            phases=phases,
            specialist_roles=tuple(
                _safe_id(item)
                for item in value.get("specialistRoles", ())
                if str(item).strip()
            ),
            skill_ids=tuple(
                _safe_id(item)
                for item in value.get("skillIds", ())
                if str(item).strip()
            ),
            proof_gates=proof_gates,
            stop_conditions=tuple(
                str(item).strip()
                for item in value.get(
                    "stopConditions",
                    (
                        "required evidence is fresh",
                        "no blocking proof failure remains",
                        "additional work has no positive verified value",
                    ),
                )
                if str(item).strip()
            ),
            mutation_expected=bool(value.get("mutationExpected", False)),
            low_resource_compatible=bool(value.get("lowResourceCompatible", True)),
        )

    def public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["id"] = payload.pop("capsule_id")
        payload["behaviorVector"] = payload.pop("behavior_vector")
        payload["taskKinds"] = payload.pop("task_kinds")
        payload["specialistRoles"] = payload.pop("specialist_roles")
        payload["skillIds"] = payload.pop("skill_ids")
        payload["proofGates"] = payload.pop("proof_gates")
        payload["stopConditions"] = payload.pop("stop_conditions")
        payload["mutationExpected"] = payload.pop("mutation_expected")
        payload["lowResourceCompatible"] = payload.pop("low_resource_compatible")
        payload["phases"] = [
            {
                "id": row["phase_id"],
                "objective": row["objective"],
                "requiredEvidence": list(row["required_evidence"]),
                "allowedToolScopes": list(row["allowed_tool_scopes"]),
                "maximumTurns": row["maximum_turns"],
            }
            for row in payload["phases"]
        ]
        return payload


def _phase(
    phase_id: str,
    objective: str,
    evidence: Iterable[str],
    scopes: Iterable[str],
    turns: int,
) -> dict[str, Any]:
    return {
        "id": phase_id,
        "objective": objective,
        "requiredEvidence": list(evidence),
        "allowedToolScopes": list(scopes),
        "maximumTurns": turns,
    }


_BUILT_INS: tuple[dict[str, Any], ...] = (
    {
        "id": "direct-verified",
        "label": "Direct + verify",
        "taskKinds": ["general", "bounded-change"],
        "keywords": ["rename", "typo", "small", "single", "read", "explain"],
        "behaviorVector": {
            "initiative": 0.58,
            "rigor": 0.82,
            "exploration": 0.2,
            "toolAutonomy": 0.48,
            "compression": 0.82,
            "interruptionSensitivity": 0.75,
            "verificationPressure": 0.88,
        },
        "phases": [
            _phase("inspect", "Inspect the exact target and constraints.", ["target_observed"], ["workspace.read", "search"], 2),
            _phase("execute", "Perform the smallest sufficient action.", ["action_receipt"], ["workspace.read", "workspace.write", "tool.call"], 4),
            _phase("verify", "Run the narrow deterministic check.", ["proof_receipt"], ["workspace.read", "verify"], 3),
        ],
        "specialistRoles": ["verifier"],
        "skillIds": ["unlazy", "user-path-validator"],
        "proofGates": ["receipt_integrity", "fresh_workspace_state"],
        "mutationExpected": False,
    },
    {
        "id": "implementation",
        "label": "Plan → build → verify",
        "taskKinds": ["implementation", "coding"],
        "keywords": ["implement", "build", "code", "feature", "refactor", "integrate", "frontend", "backend"],
        "behaviorVector": {
            "initiative": 0.86,
            "rigor": 0.9,
            "exploration": 0.54,
            "toolAutonomy": 0.82,
            "compression": 0.58,
            "interruptionSensitivity": 0.68,
            "verificationPressure": 0.96,
        },
        "phases": [
            _phase("reconnaissance", "Map the implementation surface and existing contracts.", ["workspace_map", "acceptance_contract"], ["workspace.read", "search", "tool.search"], 4),
            _phase("plan", "Produce a dependency-aware implementation plan.", ["plan_receipt"], ["workspace.read", "specialist.plan"], 3),
            _phase("implement", "Implement the complete bounded workflow.", ["workspace_delta", "tool_receipts"], ["workspace.read", "workspace.write", "tool.call", "specialist.execute"], 10),
            _phase("verify", "Prove the result against executable checks and user path.", ["deterministic_check", "proof_receipt"], ["workspace.read", "verify", "browser.observe", "specialist.verify"], 6),
        ],
        "specialistRoles": ["planner", "executor", "verifier"],
        "skillIds": ["agi-pilled-execution", "unlazy", "user-path-validator"],
        "proofGates": ["workspace_delta", "deterministic_check", "receipt_integrity", "fresh_workspace_state"],
        "mutationExpected": True,
    },
    {
        "id": "diagnosis-repair",
        "label": "Reproduce → repair → verify",
        "taskKinds": ["diagnosis", "repair", "incident"],
        "keywords": ["bug", "fix", "crash", "reconnect", "failure", "broken", "regression", "incident"],
        "behaviorVector": {
            "initiative": 0.88,
            "rigor": 0.96,
            "exploration": 0.72,
            "toolAutonomy": 0.84,
            "compression": 0.48,
            "interruptionSensitivity": 0.78,
            "verificationPressure": 1.0,
        },
        "phases": [
            _phase("triage", "Collect symptoms, logs, versions, and affected paths.", ["symptom_receipt", "environment_facts"], ["workspace.read", "process.observe", "network.observe", "search"], 5),
            _phase("reproduce", "Create a deterministic reproduction or falsify the suspected cause.", ["reproduction_receipt"], ["workspace.read", "tool.call", "verify"], 6),
            _phase("repair", "Apply the smallest robust repair with rollback protection.", ["workspace_delta", "checkpoint_receipt"], ["workspace.read", "workspace.write", "tool.call"], 9),
            _phase("regression", "Prove recovery and the important failure path.", ["deterministic_check", "failure_path_proof"], ["workspace.read", "verify", "browser.observe", "network.observe"], 7),
        ],
        "specialistRoles": ["investigator", "executor", "verifier"],
        "skillIds": ["agi-pilled-research-loop", "agi-pilled-execution", "unlazy"],
        "proofGates": ["reproduction_receipt", "workspace_delta", "deterministic_check", "failure_path_proof"],
        "mutationExpected": True,
    },
    {
        "id": "research-falsify",
        "label": "Research → synthesize → falsify",
        "taskKinds": ["research", "analysis"],
        "keywords": ["research", "compare", "investigate", "architecture", "benchmark", "paper", "evidence"],
        "behaviorVector": {
            "initiative": 0.82,
            "rigor": 0.96,
            "exploration": 0.94,
            "toolAutonomy": 0.7,
            "compression": 0.44,
            "interruptionSensitivity": 0.62,
            "verificationPressure": 0.9,
        },
        "phases": [
            _phase("question", "Define decision-changing questions and falsifiers.", ["research_contract"], ["workspace.read", "search", "specialist.plan"], 3),
            _phase("collect", "Collect diverse primary evidence and contradictory cases.", ["source_ledger"], ["workspace.read", "web.read", "search", "specialist.research"], 8),
            _phase("synthesize", "Build the strongest supported model and alternatives.", ["synthesis_artifact"], ["workspace.read", "artifact.write", "specialist.research"], 6),
            _phase("falsify", "Attack the conclusion with independent checks.", ["falsification_receipt"], ["workspace.read", "verify", "specialist.verify"], 5),
        ],
        "specialistRoles": ["planner", "researcher", "verifier"],
        "skillIds": ["research-question-orchestrate", "agi-pilled-research-loop"],
        "proofGates": ["source_ledger", "falsification_receipt", "claim_provenance"],
        "mutationExpected": False,
    },
    {
        "id": "design-evolution",
        "label": "Design → render → critic → verify",
        "taskKinds": ["design", "ui", "ux"],
        "keywords": ["design", "ui", "ux", "beautiful", "interface", "visual", "responsive", "animation"],
        "behaviorVector": {
            "initiative": 0.9,
            "rigor": 0.9,
            "exploration": 0.9,
            "toolAutonomy": 0.8,
            "compression": 0.46,
            "interruptionSensitivity": 0.74,
            "verificationPressure": 0.94,
        },
        "phases": [
            _phase("taste-contract", "Define hierarchy, user focus, states, and visual thesis.", ["design_contract"], ["workspace.read", "search", "specialist.design"], 4),
            _phase("alternatives", "Generate meaningfully different compositions, not color variants.", ["candidate_set"], ["workspace.read", "artifact.write", "specialist.design"], 6),
            _phase("implement", "Implement the selected coherent system.", ["workspace_delta"], ["workspace.read", "workspace.write", "tool.call"], 10),
            _phase("render-critic", "Render realistic states and run the visual critic loop.", ["screenshot_set", "critic_receipt"], ["browser.observe", "artifact.write", "specialist.critic"], 8),
            _phase("user-proof", "Prove responsive, keyboard, failure, and reduced-motion journeys.", ["user_path_receipt"], ["browser.observe", "verify", "specialist.verify"], 7),
        ],
        "specialistRoles": ["designer", "critic", "verifier"],
        "skillIds": ["neyvia-aesthetic-innovation-master", "neyvia-design-taste-v2", "neyvia-design-taste-v3", "user-path-validator"],
        "proofGates": ["workspace_delta", "screenshot_set", "critic_receipt", "user_path_receipt"],
        "mutationExpected": True,
        "lowResourceCompatible": False,
    },
)


class BehaviorCapsuleRegistry:
    """Load, validate, select, and compile versioned behavior capsules."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.config_path = self.root / "config" / "neyvia_behavior_capsules.json"
        self._capsules = self._load()
        self._compile_cache: dict[str, dict[str, Any]] = {}
        self.cache_hits = 0
        self.cache_misses = 0

    def _load(self) -> dict[str, BehaviorCapsule]:
        raw: list[dict[str, Any]] = [dict(item) for item in _BUILT_INS]
        if self.config_path.is_file():
            try:
                payload = json.loads(self.config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"Invalid behavior capsule config: {exc}") from exc
            additions = payload.get("capsules", ()) if isinstance(payload, dict) else ()
            raw.extend(item for item in additions if isinstance(item, dict))
        capsules: dict[str, BehaviorCapsule] = {}
        for item in raw:
            capsule = BehaviorCapsule.from_mapping(item)
            current = capsules.get(capsule.capsule_id)
            if current is None or capsule.version >= current.version:
                capsules[capsule.capsule_id] = capsule
        return capsules

    def list(self) -> list[dict[str, Any]]:
        return [self._capsules[key].public_dict() for key in sorted(self._capsules)]

    def get(self, capsule_id: str) -> BehaviorCapsule:
        normalized = _safe_id(capsule_id)
        try:
            return self._capsules[normalized]
        except KeyError as exc:
            raise KeyError(f"Unknown behavior capsule: {normalized}") from exc

    def select(self, task: str, preferred: str = "auto") -> BehaviorCapsule:
        requested = str(preferred or "auto").strip().lower()
        if requested not in {"", "auto"}:
            return self.get(requested)
        words = set(re.findall(r"[a-z0-9]+", str(task or "").lower()))
        scored: list[tuple[int, int, str, BehaviorCapsule]] = []
        for capsule in self._capsules.values():
            score = sum(3 for keyword in capsule.keywords if keyword in words)
            score += sum(1 for keyword in capsule.keywords if keyword in str(task or "").lower())
            scored.append((score, capsule.version, capsule.capsule_id, capsule))
        scored.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
        if not scored or scored[0][0] <= 0:
            return self._capsules["direct-verified"]
        return scored[0][3]

    def compile(
        self,
        task: str,
        *,
        preferred: str = "auto",
        resource_profile: dict[str, Any] | None = None,
        learned_adjustment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        profile = dict(resource_profile or {})
        adjustment = dict(learned_adjustment or {})
        capsule = self.select(task, preferred)
        cache_material = {
            "task": str(task or "").strip(),
            "capsule": capsule.public_dict(),
            "resourceProfile": profile,
            "learnedAdjustment": adjustment,
        }
        cache_key = canonical_hash(cache_material)
        cached = self._compile_cache.get(cache_key)
        if cached is not None:
            self.cache_hits += 1
            from .proofs_a_capabilities import check_behavior
            check_behavior(cached, capsule, self)
            return json.loads(json.dumps(cached))
        self.cache_misses += 1
        vector = dict(capsule.behavior_vector)
        for key, delta in (adjustment.get("behaviorVectorDelta") or {}).items():
            if key in vector:
                vector[key] = _bounded_unit(vector[key] + float(delta), vector[key])
        max_turns = sum(phase.maximum_turns for phase in capsule.phases)
        resource_turns = int(profile.get("maximumTurns") or max_turns)
        maximum_turns = max(1, min(max_turns, resource_turns, 64))
        if profile.get("mode") == "eco" and not capsule.low_resource_compatible:
            maximum_turns = min(maximum_turns, 12)
        plan = {
            "schema": PLAN_SCHEMA,
            "compiledAt": _utc_now(),
            "capsule": capsule.public_dict(),
            "behaviorVector": vector,
            "resourceProfile": profile,
            "maximumTurns": maximum_turns,
            "toolCatalogLimit": max(4, min(20, int(profile.get("toolCatalogLimit") or 12))),
            "specialistLimit": max(0, min(6, int(profile.get("specialistLimit") or len(capsule.specialist_roles)))),
            "skillRuntime": {
                "instructionIds": list(capsule.skill_ids),
                "phaseBindings": {
                    phase.phase_id: list(phase.required_evidence)
                    for phase in capsule.phases
                },
                "executableGates": list(capsule.proof_gates),
                "mode": "instruction-plus-executable-contract",
            },
            "learning": {
                "applied": bool(adjustment.get("applied")),
                "evidenceRuns": int(adjustment.get("evidenceRuns") or 0),
                "reason": str(adjustment.get("reason") or "No evidence-backed adjustment applied."),
            },
            "stopConditions": list(capsule.stop_conditions),
        }
        plan["planHash"] = canonical_hash({key: value for key, value in plan.items() if key not in {"compiledAt", "planHash"}})
        self._compile_cache[cache_key] = plan
        from .proofs_a_capabilities import check_behavior
        check_behavior(plan, capsule, self)
        return json.loads(json.dumps(plan))

    def cache_snapshot(self) -> dict[str, Any]:
        total = self.cache_hits + self.cache_misses
        return {
            "hits": self.cache_hits,
            "misses": self.cache_misses,
            "hitRate": round(self.cache_hits / total, 4) if total else 0.0,
            "entries": len(self._compile_cache),
        }
