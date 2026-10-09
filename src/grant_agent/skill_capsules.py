"""Executable skill capsules layered over human-readable skill instructions."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from .proofs_e_sv import enforced


SKILL_CAPSULE_SCHEMA = "neyvia.skill-capsule/v1"
SKILL_PLAN_SCHEMA = "neyvia.skill-runtime-plan/v1"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _safe_id(value: object) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", str(value or "").strip().lower()).strip(".-")
    if not normalized:
        raise ValueError("skill capsule id is required")
    return normalized[:120]


@dataclass(frozen=True)
class SkillCapsule:
    skill_id: str
    label: str
    instruction_paths: tuple[str, ...]
    behavior_vector_delta: dict[str, float]
    required_tool_scopes: tuple[str, ...]
    phase_bindings: dict[str, tuple[str, ...]]
    proof_gates: tuple[str, ...]
    executable_checks: tuple[tuple[str, ...], ...]
    minimum_evidence: int

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "SkillCapsule":
        checks: list[tuple[str, ...]] = []
        for raw in value.get("executableChecks", ()):
            if isinstance(raw, list) and raw and all(isinstance(item, str) for item in raw):
                checks.append(tuple(raw))
        bindings = {
            _safe_id(key): tuple(str(item) for item in items if str(item).strip())
            for key, items in (value.get("phaseBindings") or {}).items()
            if isinstance(items, list)
        }
        deltas = {
            str(key): max(-0.25, min(0.25, float(delta)))
            for key, delta in (value.get("behaviorVectorDelta") or {}).items()
        }
        return cls(
            skill_id=_safe_id(value.get("id")),
            label=str(value.get("label") or value.get("id") or "Skill").strip(),
            instruction_paths=tuple(
                str(item).strip()
                for item in value.get("instructionPaths", ())
                if str(item).strip()
            ),
            behavior_vector_delta=deltas,
            required_tool_scopes=tuple(
                str(item).strip()
                for item in value.get("requiredToolScopes", ())
                if str(item).strip()
            ),
            phase_bindings=bindings,
            proof_gates=tuple(
                str(item).strip()
                for item in value.get("proofGates", ())
                if str(item).strip()
            ),
            executable_checks=tuple(checks),
            minimum_evidence=max(0, min(100, int(value.get("minimumEvidence") or 0))),
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "schema": SKILL_CAPSULE_SCHEMA,
            "id": self.skill_id,
            "label": self.label,
            "instructionPaths": list(self.instruction_paths),
            "behaviorVectorDelta": dict(self.behavior_vector_delta),
            "requiredToolScopes": list(self.required_tool_scopes),
            "phaseBindings": {key: list(value) for key, value in self.phase_bindings.items()},
            "proofGates": list(self.proof_gates),
            "executableChecks": [list(row) for row in self.executable_checks],
            "minimumEvidence": self.minimum_evidence,
        }


_BUILT_INS = (
    {
        "id": "unlazy",
        "label": "Ambitious execution",
        "instructionPaths": [".codex/skills/unlazy/SKILL.md"],
        "behaviorVectorDelta": {"initiative": 0.12, "toolAutonomy": 0.08},
        "requiredToolScopes": ["workspace.read", "verify"],
        "phaseBindings": {"implement": ["complete authorized workflow", "recoverable persistence"]},
        "proofGates": ["receipt_integrity", "fresh_workspace_state"],
        "minimumEvidence": 1,
    },
    {
        "id": "user-path-validator",
        "label": "User-path validation",
        "instructionPaths": [".codex/skills/user-path-validator/SKILL.md"],
        "behaviorVectorDelta": {"rigor": 0.08, "verificationPressure": 0.12},
        "requiredToolScopes": ["browser.observe", "verify"],
        "phaseBindings": {"verify": ["shortest realistic user journey"]},
        "proofGates": ["user_path_receipt"],
        "minimumEvidence": 1,
    },
    {
        "id": "neyvia-aesthetic-innovation-master",
        "label": "Aesthetic and innovation master",
        "instructionPaths": [".codex/skills/neyvia-aesthetic-innovation-master/SKILL.md"],
        "behaviorVectorDelta": {"exploration": 0.12, "rigor": 0.06},
        "requiredToolScopes": ["browser.observe", "artifact.write"],
        "phaseBindings": {
            "taste-contract": ["visual thesis", "hierarchy"],
            "alternatives": ["meaningfully different candidates"],
        },
        "proofGates": ["screenshot_set", "critic_receipt"],
        "minimumEvidence": 2,
    },
    {
        "id": "neyvia-design-taste-v2",
        "label": "Rendered visual critic",
        "instructionPaths": [".codex/skills/neyvia-design-taste-v2/SKILL.md"],
        "behaviorVectorDelta": {"rigor": 0.1, "verificationPressure": 0.1},
        "requiredToolScopes": ["browser.observe", "verify"],
        "phaseBindings": {"render-critic": ["render", "observe", "diagnose", "iterate"]},
        "proofGates": ["screenshot_set", "critic_receipt"],
        "minimumEvidence": 3,
    },
    {
        "id": "neyvia-design-taste-v3",
        "label": "Beauty scout and innovation engine",
        "instructionPaths": [".codex/skills/neyvia-design-taste-v3/SKILL.md"],
        "behaviorVectorDelta": {"exploration": 0.16, "initiative": 0.06},
        "requiredToolScopes": ["search", "browser.observe", "artifact.write"],
        "phaseBindings": {"alternatives": ["reference principles", "concept tournament"]},
        "proofGates": ["candidate_set", "critic_receipt"],
        "minimumEvidence": 3,
    },
)


class SkillCapsuleRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.config_path = self.root / "config" / "neyvia_skill_capsules.json"
        self._capsules = self._load()

    def _load(self) -> dict[str, SkillCapsule]:
        rows = [dict(item) for item in _BUILT_INS]
        if self.config_path.is_file():
            try:
                payload = json.loads(self.config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"Invalid skill capsule registry: {exc}") from exc
            rows.extend(item for item in payload.get("capsules", ()) if isinstance(item, dict))
        capsules: dict[str, SkillCapsule] = {}
        for row in rows:
            capsule = SkillCapsule.from_mapping(row)
            capsules[capsule.skill_id] = capsule
        return capsules

    def list(self) -> list[dict[str, Any]]:
        return [self._capsules[key].public_dict() for key in sorted(self._capsules)]

    @enforced("sv.skills.capsule")
    def compile(self, skill_ids: Iterable[str]) -> dict[str, Any]:
        selected: list[SkillCapsule] = []
        missing: list[str] = []
        for raw in skill_ids:
            skill_id = _safe_id(raw)
            capsule = self._capsules.get(skill_id)
            if capsule is None:
                missing.append(skill_id)
            else:
                selected.append(capsule)
        vector_delta: dict[str, float] = {}
        tool_scopes: set[str] = set()
        proof_gates: set[str] = set()
        checks: list[list[str]] = []
        phase_bindings: dict[str, list[str]] = {}
        instruction_receipts: list[dict[str, Any]] = []
        for capsule in selected:
            for key, value in capsule.behavior_vector_delta.items():
                vector_delta[key] = round(max(-0.25, min(0.25, vector_delta.get(key, 0.0) + value)), 4)
            tool_scopes.update(capsule.required_tool_scopes)
            proof_gates.update(capsule.proof_gates)
            checks.extend(list(row) for row in capsule.executable_checks)
            for phase, items in capsule.phase_bindings.items():
                phase_bindings.setdefault(phase, []).extend(items)
            for relative in capsule.instruction_paths:
                path = (self.root / relative).resolve()
                inside = path == self.root or self.root in path.parents
                if not inside or not path.is_file():
                    instruction_receipts.append({"path": relative, "available": False, "sha256": ""})
                    continue
                data = path.read_bytes()
                instruction_receipts.append(
                    {
                        "path": relative,
                        "available": True,
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "bytes": len(data),
                    }
                )
        plan = {
            "schema": SKILL_PLAN_SCHEMA,
            "skills": [capsule.public_dict() for capsule in selected],
            "missingSkillIds": missing,
            "behaviorVectorDelta": vector_delta,
            "requiredToolScopes": sorted(tool_scopes),
            "phaseBindings": {key: value for key, value in sorted(phase_bindings.items())},
            "proofGates": sorted(proof_gates),
            "executableChecks": checks,
            "instructionReceipts": instruction_receipts,
            "truthBoundary": (
                "Instruction text influences the model; phase bindings, scopes, checks, and proof gates "
                "are the executable portion enforced by Neyvia."
            ),
        }
        plan["planHash"] = _hash({key: value for key, value in plan.items() if key != "planHash"})
        from .proofs_d_ui_planning import check_capsules
        check_capsules(self.root, plan)
        return plan
