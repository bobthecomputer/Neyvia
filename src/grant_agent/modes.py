from __future__ import annotations

from .proofs_c_models import checked

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ModePreset:
    name: str
    persona: str
    max_tokens: int
    max_handoffs: int
    max_runtime_seconds: int
    parallel_agents: int = 1
    merge_policy: str = "best_score"
    description: str = ""


class ModeRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._modes = self._load(path)

    @staticmethod
    def _load(path: Path) -> dict[str, ModePreset]:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        out: dict[str, ModePreset] = {}
        for key, value in payload.items():
            out[key] = ModePreset(
                name=key,
                persona=value["persona"],
                max_tokens=int(value["max_tokens"]),
                max_handoffs=int(value["max_handoffs"]),
                max_runtime_seconds=int(value["max_runtime_seconds"]),
                parallel_agents=int(value.get("parallel_agents", 1)),
                merge_policy=str(value.get("merge_policy", "best_score")),
                description=value.get("description", ""),
            )
        return out

    @checked("mode")
    def get(self, name: str) -> ModePreset:
        # Resolve against this call's selected-root snapshot, rather than the
        # settings that happened to exist when the registry was constructed.
        modes = self._load(self.path)
        if name in modes:
            return modes[name]
        if "balanced" in modes:
            return modes["balanced"]
        return ModePreset(
            name="fallback",
            persona="balanced_builder",
            max_tokens=2400,
            max_handoffs=6,
            max_runtime_seconds=300,
            parallel_agents=1,
            merge_policy="best_score",
            description="Default fallback mode",
        )

    def get_parallel_agents(self, name: str) -> int:
        return self.get(name).parallel_agents
