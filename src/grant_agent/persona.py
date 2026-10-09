from __future__ import annotations

import json
from pathlib import Path

from .models import PersonaProfile


class PersonaRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._profiles = self._load_profiles(path)

    @staticmethod
    def _load_profiles(path: Path) -> dict[str, PersonaProfile]:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        profiles: dict[str, PersonaProfile] = {}
        for key, raw in payload.items():
            profiles[key] = PersonaProfile(
                name=raw["name"],
                tone=raw["tone"],
                risk_tolerance=raw["risk_tolerance"],
                creativity_level=raw["creativity_level"],
                coding_style=raw["coding_style"],
                verbosity=raw["verbosity"],
            )
        return profiles

    def get(self, profile_name: str) -> PersonaProfile:
        if profile_name in self._profiles:
            return self._profiles[profile_name]
        if "balanced_builder" in self._profiles:
            return self._profiles["balanced_builder"]
        return PersonaProfile(
            name="fallback",
            tone="pragmatic",
            risk_tolerance="medium",
            creativity_level="medium",
            coding_style="small reversible changes",
            verbosity="concise",
        )
