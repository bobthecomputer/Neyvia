from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


DEFAULT_CONSTITUTION_TEXT = """# Agent Constitution

1. Read relevant docs/specs before proposing edits.
2. Produce a short plan before making changes.
3. Offer at least one creative alternative when planning.
4. Define acceptance checks before implementation.
5. Prefer safe, reversible actions with clear user control.
"""


@dataclass
class PreflightPolicy:
    require_docs_read: bool = True
    require_docs_accessible: bool = True
    require_plan_before_edit: bool = True
    require_creative_alternative: bool = True
    require_acceptance_checks: bool = True

    def validate(
        self,
        docs: list[str],
        readable_docs: int,
        plan_steps: list[str],
        alternatives: list[str],
        acceptance_checks: list[str],
    ) -> list[str]:
        failures: list[str] = []
        if self.require_docs_read and not docs:
            failures.append("No docs provided for docs-first preflight.")
        if self.require_docs_accessible and docs and readable_docs <= 0:
            failures.append("None of the referenced docs could be read.")
        if self.require_plan_before_edit and not plan_steps:
            failures.append("No execution plan produced before edits.")
        if self.require_creative_alternative and not alternatives:
            failures.append("No creative alternative was proposed.")
        if self.require_acceptance_checks and not acceptance_checks:
            failures.append("No acceptance checks defined.")
        return failures


@dataclass
class AgentConstitution:
    text: str = DEFAULT_CONSTITUTION_TEXT
    policy: PreflightPolicy = field(default_factory=PreflightPolicy)

    @classmethod
    def load(cls, path: Path) -> "AgentConstitution":
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        policy = PreflightPolicy(**payload.get("policy", {}))
        return cls(text=payload.get("text", DEFAULT_CONSTITUTION_TEXT), policy=policy)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"text": self.text, "policy": asdict(self.policy)}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
