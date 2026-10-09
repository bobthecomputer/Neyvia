from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from ..models import Mission, RuntimeCapability, RuntimeInstallStatus, WorkspaceProfile
from ..opencode_go_models import normalize_opencode_go_model
from ..runtime_updates import compare_version_tokens, latest_opencode_release
from ..subprocess_utils import hidden_windows_subprocess_kwargs
from .base import (
    AgentRuntimeAdapter,
    build_mission_resume_objective,
    mission_phase_route,
    runtime_subprocess_env,
    runtime_which,
    shell_join,
)

OPENCODE_PROVIDER_MAP = {
    "openrouter": "openrouter",
    "deepseek": "openrouter",
    "opencode": "",
    "opencode-go": "opencode-go",
    "opencodego": "opencode-go",
    "openai": "openai",
    "openai-codex": "openai",
    "minimax-coding-plan": "minimax-coding-plan",
    "minimax": "minimax-coding-plan",
}

class OpenCodeRuntimeAdapter(AgentRuntimeAdapter):
    runtime_id = "opencode"
    label = "OpenCode"

    def list_capabilities(self) -> list[RuntimeCapability]:
        return [
            RuntimeCapability(
                key="native_opencode_run",
                label="Native OpenCode run",
                available=True,
                detail="Runs the local OpenCode CLI directly and streams JSON output into Agent Live.",
            ),
            RuntimeCapability(
                key="openrouter_deepseek_models",
                label="OpenRouter DeepSeek models",
                available=True,
                detail="Preserves openrouter/deepseek/... model ids for DeepSeek routes.",
            ),
            RuntimeCapability(
                key="agent_live_messages",
                label="Agent Live messages",
                available=True,
                detail="Assistant text is emitted as runtime.model_message with real runtime provenance.",
            ),
            RuntimeCapability(
                key="file_edit",
                label="File edits",
                available=True,
                detail="OpenCode can apply workspace file edits through the native CLI run.",
            ),
            RuntimeCapability(
                key="shell_commands",
                label="Shell commands",
                available=True,
                detail="OpenCode can execute command-backed coding tasks through the native CLI when permitted.",
            ),
            RuntimeCapability(
                key="browser_inspection",
                label="Browser inspection",
                available=False,
                detail="Native OpenCode does not expose browser control directly; Fluxio Browser proof must be attached through the surrounding verifier route.",
            ),
        ]

    def detect(self, workspace_root: Path) -> RuntimeInstallStatus:
        command = runtime_which("opencode", workspace_root)
        version = None
        issues: list[str] = []
        if command:
            try:
                completed = subprocess.run(  # noqa: S603
                    [command, "--version"],
                    cwd=str(workspace_root),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=8,
                    check=False,
                    env=runtime_subprocess_env(workspace_root),
                    **hidden_windows_subprocess_kwargs(),
                )
                version = _normalize_version((completed.stdout or completed.stderr).strip())
            except Exception as exc:  # pragma: no cover - defensive
                issues.append(f"Unable to read OpenCode version: {exc}")
        else:
            issues.append("OpenCode CLI was not found on PATH.")

        latest_release = latest_opencode_release()
        latest_version = latest_release.get("version") or None
        update_available = bool(
            command
            and version
            and latest_version
            and compare_version_tokens(version, latest_version) < 0
        )
        if update_available and latest_version:
            issues.append(f"OpenCode is behind the latest npm release ({latest_version}).")

        return RuntimeInstallStatus(
            runtime_id=self.runtime_id,
            label=self.label,
            detected=command is not None,
            command=command,
            version=version,
            latest_version=latest_version,
            update_available=update_available,
            update_command=self.update(workspace_root).get("command", "") if command else "",
            update_source_url=latest_release.get("sourceUrl") or None,
            install_hint="Install or expose the OpenCode CLI on PATH, then run `opencode auth login` or configure its providers.",
            doctor_summary=(
                (
                    f"OpenCode is installed, but the latest npm release is {latest_version}."
                    if update_available and latest_version
                    else "OpenCode is ready for native mission routing."
                )
                if command
                else "Install OpenCode before selecting the native OpenCode runtime."
            ),
            issues=issues,
            capabilities=self.list_capabilities(),
        )

    def install(self) -> dict[str, str]:
        return {
            "command": "npm install -g opencode-ai",
            "follow_up": "opencode auth login",
        }

    def doctor(self, workspace_root: Path) -> RuntimeInstallStatus:
        status = self.detect(workspace_root)
        if status.detected and not status.version:
            status.issues.append("OpenCode responded, but version output was empty.")
        return status

    def update(self, workspace_root: Path) -> dict[str, str]:
        return {
            "command": "npm install -g opencode-ai@latest",
            "follow_up": "opencode --version",
        }

    def start_mission(
        self, mission: Mission, workspace: WorkspaceProfile
    ) -> dict[str, object]:
        route_contract = self._route_contract(mission)
        return {
            "launch_command": self._mission_launch_command(
                mission.objective,
                workspace_root=workspace.root_path,
                title=getattr(mission, "title", "") or getattr(mission, "mission_id", ""),
                route_contract=route_contract,
            ),
            "workspace": workspace.root_path,
            "runtime_id": self.runtime_id,
            "route_contract": route_contract,
            "route_summary": self._route_summary(route_contract),
        }

    def stream_events(self, mission: Mission) -> list[dict[str, object]]:
        return [
            {
                "kind": "runtime.stream",
                "message": "OpenCode mission stream is captured through the Fluxio OpenCode bridge.",
                "missionId": mission.mission_id,
            }
        ]

    def request_approval(self, mission: Mission, prompt: str) -> dict[str, object]:
        return {
            "channel": "desktop",
            "message": prompt,
            "missionId": mission.mission_id,
        }

    def resume_mission(
        self, mission: Mission, workspace: WorkspaceProfile
    ) -> dict[str, object]:
        route_contract = self._route_contract(mission)
        return {
            "launch_command": self._mission_launch_command(
                build_mission_resume_objective(mission),
                workspace_root=workspace.root_path,
                title=getattr(mission, "title", "") or getattr(mission, "mission_id", ""),
                route_contract=route_contract,
            ),
            "workspace": workspace.root_path,
            "runtime_id": self.runtime_id,
            "route_contract": route_contract,
            "route_summary": self._route_summary(route_contract),
        }

    def stop_mission(self, mission: Mission) -> dict[str, object]:
        return {
            "message": f"Stop requested for OpenCode mission {mission.mission_id}.",
            "runtime_id": self.runtime_id,
        }

    def _mission_launch_command(
        self,
        objective: str,
        *,
        workspace_root: str = ".",
        title: str = "",
        route_contract: dict[str, str] | None = None,
    ) -> str:
        root = Path(workspace_root)
        opencode_command = runtime_which("opencode", root) or "opencode"
        route_contract = route_contract or {}
        model_id = self._canonical_model_id(route_contract)
        args = [
            sys.executable,
            "-m",
            "grant_agent.opencode_bridge",
            "--opencode-command",
            opencode_command,
            "--prompt",
            objective,
        ]
        if model_id:
            args.extend(["--model", model_id])
        title_value = _safe_title(title)
        if title_value:
            args.extend(["--title", title_value])
        variant = self._variant(route_contract.get("effort", ""))
        if variant:
            args.extend(["--variant", variant])
        return shell_join(args)

    def _route_contract(self, mission: Mission) -> dict[str, str]:
        route = mission_phase_route(mission)
        provider = self._normalize_provider(route.get("provider", ""))
        model = str(route.get("model", "")).strip()
        canonical_model_id = self._normalize_model_id(provider, model)
        return {
            "phase": str(route.get("phase", "")).strip().lower(),
            "role": str(route.get("role", "")).strip().lower(),
            "provider": provider,
            "model": model,
            "canonical_model_id": canonical_model_id,
            "effort": str(route.get("effort", "")).strip().lower(),
        }

    def _normalize_provider(self, provider: str) -> str:
        normalized = str(provider or "").strip().lower()
        return OPENCODE_PROVIDER_MAP.get(normalized, normalized)

    def _normalize_model_id(self, provider: str, model: str) -> str:
        value = str(model or "").strip()
        if not value:
            return ""
        if provider in {"opencode-go", "opencodego"}:
            go_model = normalize_opencode_go_model(value)
            return f"opencode-go/{go_model}" if go_model else ""
        if "/" in value:
            return value
        if provider == "openrouter" and value.startswith("deepseek-"):
            return f"openrouter/deepseek/{value}"
        if provider:
            return f"{provider}/{value}"
        return value

    def _canonical_model_id(self, route_contract: dict[str, str]) -> str:
        existing = str(route_contract.get("canonical_model_id") or "").strip()
        if existing:
            return existing
        return self._normalize_model_id(
            str(route_contract.get("provider", "")).strip(),
            str(route_contract.get("model", "")).strip(),
        )

    def _variant(self, effort: str) -> str:
        normalized = str(effort or "").strip().lower()
        if normalized in {"minimal", "low", "medium", "high", "max"}:
            return normalized
        if normalized == "xhigh":
            return "max"
        return ""

    def _route_summary(self, route_contract: dict[str, str]) -> str:
        model_id = self._canonical_model_id(route_contract)
        effort = str(route_contract.get("effort", "")).strip().lower()
        role = str(route_contract.get("role", "")).strip()
        phase = str(route_contract.get("phase", "")).strip()
        if not model_id:
            return "OpenCode launch route is using the runtime default model configuration."
        route_prefix = ""
        if phase or role:
            route_prefix = f"{phase or 'execute'}:{role or 'route'} -> "
        summary = f"OpenCode launch route: {route_prefix}{model_id}"
        if effort:
            summary += f" ({effort})"
        return summary


def _normalize_version(value: str) -> str | None:
    first = str(value or "").strip().splitlines()
    if not first:
        return None
    match = re.search(r"\d+(?:\.\d+)+", first[0])
    return match.group(0) if match else first[0].strip() or None


def _safe_title(value: object) -> str:
    title = " ".join(str(value or "").split())
    return title[:80]
