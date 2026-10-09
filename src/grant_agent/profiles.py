from __future__ import annotations

import json
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any


@dataclass
class AgentProfileConfig:
    mode: str | None = None
    persona: str | None = None
    parallel_agents: int | None = None
    merge_policy: str | None = None
    pause_on_verification_failure: bool | None = None
    max_tokens: int | None = None
    max_handoffs: int | None = None
    max_runtime_seconds: int | None = None
    execution_scope: str | None = None
    approval_mode: str | None = None
    explanation_depth: str | None = None
    delegation_aggressiveness: str | None = None


@dataclass
class PersonalizationProfile:
    name: str
    description: str = ""
    ui: dict[str, Any] = field(default_factory=dict)
    agent: AgentProfileConfig = field(default_factory=AgentProfileConfig)


class ProfileRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        payload = self._load_payload(path)
        self.default_profile = str(payload.get("default_profile", "hands_free_builder"))
        self.workspace_profiles: list[dict[str, str]] = list(
            payload.get("workspace_profiles", [])
        )
        self.profiles = self._parse_profiles(payload.get("profiles", {}))

        if self.default_profile not in self.profiles and self.profiles:
            self.default_profile = next(iter(self.profiles.keys()))

    @staticmethod
    def _load_payload(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _parse_profiles(raw: dict[str, Any]) -> dict[str, PersonalizationProfile]:
        out: dict[str, PersonalizationProfile] = {}
        for name, config in raw.items():
            agent_raw = config.get("agent", {}) if isinstance(config, dict) else {}
            profile = PersonalizationProfile(
                name=name,
                description=str(config.get("description", "")),
                ui=dict(config.get("ui", {})),
                agent=AgentProfileConfig(
                    mode=agent_raw.get("mode"),
                    persona=agent_raw.get("persona"),
                    parallel_agents=agent_raw.get("parallel_agents"),
                    merge_policy=agent_raw.get("merge_policy"),
                    pause_on_verification_failure=agent_raw.get(
                        "pause_on_verification_failure"
                    ),
                    max_tokens=agent_raw.get("max_tokens"),
                    max_handoffs=agent_raw.get("max_handoffs"),
                    max_runtime_seconds=agent_raw.get("max_runtime_seconds"),
                    execution_scope=agent_raw.get("execution_scope"),
                    approval_mode=agent_raw.get("approval_mode"),
                    explanation_depth=agent_raw.get("explanation_depth"),
                    delegation_aggressiveness=agent_raw.get("delegation_aggressiveness"),
                ),
            )
            out[name] = profile
        return out

    def list_names(self) -> list[str]:
        return sorted(self.profiles.keys())

    def get(self, name: str | None) -> PersonalizationProfile | None:
        if not name:
            return None
        return self.profiles.get(name)

    def resolve(
        self,
        requested_name: str | None,
        workspace_root: Path | None = None,
    ) -> PersonalizationProfile | None:
        explicit = self.get(requested_name)
        if explicit:
            return explicit

        workspace_candidate = self.resolve_workspace_profile(workspace_root)
        if workspace_candidate:
            return workspace_candidate

        return self.get(self.default_profile)

    def resolve_workspace_profile(
        self,
        workspace_root: Path | None,
    ) -> PersonalizationProfile | None:
        if not workspace_root:
            return None
        workspace_text = workspace_root.as_posix()
        workspace_name = workspace_root.name
        for rule in self.workspace_profiles:
            pattern = str(rule.get("pattern", "")).strip()
            profile_name = str(rule.get("profile", "")).strip()
            if not pattern or not profile_name:
                continue
            if fnmatch(workspace_text, pattern) or fnmatch(workspace_name, pattern):
                profile = self.get(profile_name)
                if profile:
                    return profile
        return None


from .proofs_d_runtime import checked as _checked
ProfileRegistry.resolve = _checked("d.runtime.profile.resolve", ProfileRegistry.resolve)
