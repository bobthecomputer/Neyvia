from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from .proofs_e_sv import enforced


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


@dataclass
class Skill:
    name: str
    description: str
    schema: dict
    permissions: list[str]
    examples: list[str]
    action_kinds: list[str]
    profile_suitability: list[str]
    guidance_only: bool
    execution_capable: bool


class SkillRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.skills = self._load(path)

    @staticmethod
    def _load(path: Path) -> list[Skill]:
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        from .proofs_d_host import check_skill_catalog
        check_skill_catalog(path, payload)
        output: list[Skill] = []
        for raw in payload:
            output.append(
                Skill(
                    name=raw["name"],
                    description=raw["description"],
                    schema=raw.get("schema", {}),
                    permissions=raw.get("permissions", []),
                    examples=raw.get("examples", []),
                    action_kinds=raw.get("action_kinds", []),
                    profile_suitability=raw.get("profile_suitability", []),
                    guidance_only=bool(raw.get("guidance_only", False)),
                    execution_capable=bool(raw.get("execution_capable", False)),
                )
            )
        return output

    @enforced("sv.skills.retrieval")
    def retrieve(self, task_brief: str, top_k: int = 3) -> list[Skill]:
        if not self.skills:
            return []
        query_tokens = _tokenize(task_brief)

        def score(skill: Skill) -> tuple[int, int]:
            text_tokens = _tokenize(skill.name + " " + skill.description)
            overlap = len(query_tokens & text_tokens)
            return overlap, -len(skill.name)

        ranked = sorted(self.skills, key=score, reverse=True)
        positive = [skill for skill in ranked[:top_k] if score(skill)[0] > 0]
        if positive:
            return positive
        return ranked[:top_k]
