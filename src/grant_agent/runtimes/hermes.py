from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

from ..models import Mission, RuntimeCapability, RuntimeInstallStatus, WorkspaceProfile
from ..opencode_go_models import normalize_opencode_go_model
from ..subprocess_utils import hidden_windows_subprocess_kwargs
from ..runtime_updates import compare_version_tokens, latest_hermes_release, normalize_hermes_version
from .base import (
    AgentRuntimeAdapter,
    build_mission_resume_objective,
    mission_phase_route,
    _direct_runtime_command,
    runtime_bin_candidates,
    runtime_lookup_path,
    runtime_subprocess_env,
    shell_join,
    shell_with_runtime_path,
)

HERMES_PROVIDER_MAP = {
    "openai": "openai-codex",
    "openai-codex": "openai-codex",
    "openrouter": "openrouter",
    "opencon": "openrouter",
    "opencon-pro": "openrouter",
    "openconpro": "openrouter",
    "nous": "nous",
    "copilot-acp": "copilot-acp",
    "copilot": "copilot",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "huggingface": "huggingface",
    "zai": "zai",
    "kimi-coding": "kimi-coding",
    "kimi-coding-cn": "kimi-coding-cn",
    "minimax": "minimax",
    "minimax-oauth": "minimax-oauth",
    "minimax-cn": "minimax-cn",
    "opencode": "opencode",
    "opencode-go": "opencode-go",
    "opencodego": "opencode-go",
    "kilocode": "kilocode",
    "xiaomi": "xiaomi",
    "arcee": "arcee",
}

# Hermes keeps a global model default in config.yaml. When Fluxio selects a
# provider without also selecting a model, that global default may belong to a
# different provider (for example, an Anthropic model with OpenAI Codex). Keep
# the explicit Fluxio route coherent instead of inheriting an incompatible
# cross-provider default.
HERMES_PROVIDER_DEFAULT_MODELS = {
    "openai-codex": "gpt-5.6-sol",
}

def _runtime_which(command_name: str, workspace_root: Path) -> str | None:
    candidates = runtime_bin_candidates(workspace_root)
    direct = _direct_runtime_command(command_name, candidates)
    if direct:
        return direct
    if candidates:
        return shutil.which(command_name, path=runtime_lookup_path(workspace_root))
    return shutil.which(command_name)


class HermesRuntimeAdapter(AgentRuntimeAdapter):
    runtime_id = "hermes"
    label = "Hermes"

    def list_capabilities(self) -> list[RuntimeCapability]:
        return [
            RuntimeCapability(
                key="scheduled_automations",
                label="Scheduled automations",
                available=True,
                detail="Hermes has built-in scheduling and long-running agent loops.",
            ),
            RuntimeCapability(
                key="skills_memory",
                label="Skills and memory",
                available=True,
                detail="Hermes learns and recalls skills across sessions.",
            ),
            RuntimeCapability(
                key="code_mod_skills",
                label="Code-mod skills",
                available=True,
                detail="Hermes can route coding work through bundled SKILL.md procedures such as simplify-code, test-driven-development, codex, and opencode when present.",
            ),
            RuntimeCapability(
                key="file_edit",
                label="File edits",
                available=True,
                detail="Hermes can apply supervised workspace file changes through code-mod skills and mission execution lanes.",
            ),
            RuntimeCapability(
                key="shell_commands",
                label="Shell commands",
                available=True,
                detail="Hermes can run command/check steps through the workspace runtime harness when mission permissions allow it.",
            ),
            RuntimeCapability(
                key="browser_inspection",
                label="Browser inspection",
                available=True,
                detail="Hermes can use Fluxio Browser/Preview evidence and verifier proofs attached to the run.",
            ),
            RuntimeCapability(
                key="delegation",
                label="Delegation",
                available=True,
                detail="Hermes can spawn isolated subagents for parallel workstreams.",
            ),
        ]

    def detect(self, workspace_root: Path) -> RuntimeInstallStatus:
        command = _runtime_which("hermes", workspace_root)
        version_output = None
        detected_in_wsl = False
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
                version_output = (completed.stdout or completed.stderr).strip() or None
            except Exception as exc:  # pragma: no cover - defensive
                issues.append(f"Unable to read Hermes version: {exc}")
        else:
            version_output = self._wsl_hermes_version()
            if version_output is not None:
                command = "wsl:hermes"
                detected_in_wsl = True
            else:
                issues.append("Hermes CLI was not found on PATH or inside WSL2.")

        version = normalize_hermes_version(version_output)
        latest_release = latest_hermes_release()
        latest_version = latest_release.get("version") or None
        release_comparison_available = bool(command and version and latest_version)
        update_available = False
        if (
            command
            and version
            and latest_version
            and compare_version_tokens(version, latest_version) < 0
        ):
            update_available = True
        elif command and version_output and not release_comparison_available:
            update_available = "update available" in version_output.lower()
        if update_available and latest_version:
            issues.append(f"Hermes is behind the latest upstream release ({latest_version}).")

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
            install_hint=(
                "Use Fluxio Setup -> Install Hermes for one-click WSL2 install + setup, "
                "or run `curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash` "
                "then `hermes setup`."
            ),
            doctor_summary=(
                (
                    (
                        f"Hermes is installed in WSL2, but the latest upstream release is {latest_version}."
                        if update_available and latest_version and detected_in_wsl
                        else (
                            f"Hermes is installed, but the latest upstream release is {latest_version}."
                            if update_available and latest_version
                            else (
                                "Hermes is ready for mission routing through WSL2."
                                if detected_in_wsl
                                else "Hermes is ready for mission routing."
                            )
                        )
                    )
                )
                if command
                else "Install Hermes from setup (one-click WSL2 flow) before using the runtime."
            ),
            issues=issues,
            capabilities=self.list_capabilities(),
        )

    def install(self) -> dict[str, str]:
        return {
            "command": "curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash",
            "follow_up": "hermes setup",
        }

    def doctor(self, workspace_root: Path) -> RuntimeInstallStatus:
        status = self.detect(workspace_root)
        if status.detected and not status.version:
            status.issues.append("Hermes responded, but version output was empty.")
        return status

    def update(self, workspace_root: Path) -> dict[str, str]:
        command = _runtime_which("hermes", workspace_root)
        if command:
            managed_upgrade = self._managed_package_upgrade_snippet(command, workspace_root)
            update_command = "hermes update"
            if managed_upgrade:
                update_command = f"{update_command}; {managed_upgrade}"
            return {
                "command": shell_with_runtime_path(update_command, workspace_root),
                "follow_up": "hermes --version",
            }
        if self._wsl_hermes_available():
            return {
                "command": 'wsl bash -lc "hermes update; if hermes --version 2>&1 | grep -qi \'update available\'; then command -v uv >/dev/null 2>&1 && uv pip install --upgrade hermes-agent; fi; hermes --version"',
                "follow_up": 'wsl bash -lc "hermes --version"',
            }
        return {
            "command": "hermes update",
            "follow_up": "hermes --version",
        }

    def _managed_package_upgrade_snippet(self, command: str, workspace_root: Path) -> str:
        if os.name == "nt":
            return ""
        python_path = self._managed_venv_python(command, workspace_root)
        if python_path is None:
            return ""
        return self._package_upgrade_snippet(python_path)

    @staticmethod
    def _package_upgrade_snippet(python_path: Path) -> str:
        quoted_python = shlex.quote(str(python_path))
        return (
            'HERMES_VERSION_OUTPUT="$(hermes --version 2>&1 || true)"; '
            'printf "%s\\n" "$HERMES_VERSION_OUTPUT"; '
            'if printf "%s\\n" "$HERMES_VERSION_OUTPUT" | grep -qi "update available"; then '
            'UV_CMD="$(command -v uv || true)"; '
            'if [ -n "$UV_CMD" ]; then '
            f'"$UV_CMD" pip install --python {quoted_python} --upgrade hermes-agent; '
            'else echo "Hermes package upgrade skipped: uv not found" >&2; '
            "fi; "
            "fi; "
            "hermes --version"
        )

    def _managed_venv_python(self, command: str, workspace_root: Path) -> Path | None:
        if command.startswith("wsl:"):
            return None
        command_path = Path(command).expanduser()
        roots: list[Path] = []
        if command_path.is_absolute():
            roots.append(command_path.parent.parent)
        roots.extend(runtime_bin.parent for runtime_bin in runtime_bin_candidates(workspace_root))
        seen: set[str] = set()
        for root in roots:
            key = str(root)
            if key in seen:
                continue
            seen.add(key)
            candidates = [
                root / "hermes-agent" / "venv" / "bin" / "python",
                root / "hermes-agent" / "venv" / "Scripts" / "python.exe",
            ]
            for candidate in candidates:
                if candidate.exists():
                    return candidate
        return None

    def start_mission(
        self, mission: Mission, workspace: WorkspaceProfile
    ) -> dict[str, object]:
        route_contract = self._route_contract(mission)
        launch_command = self._mission_launch_command(
            mission.objective,
            workspace_root=workspace.root_path,
            route_contract=route_contract,
        )
        return {
            "launch_command": launch_command,
            "workspace": workspace.root_path,
            "runtime_id": self.runtime_id,
            "route_contract": route_contract,
            "route_summary": self._route_summary(route_contract),
        }

    def stream_events(self, mission: Mission) -> list[dict[str, object]]:
        return [
            {
                "kind": "runtime.stream",
                "message": "Hermes mission stream is available through CLI or messaging gateway.",
                "missionId": mission.mission_id,
            }
        ]

    def request_approval(self, mission: Mission, prompt: str) -> dict[str, object]:
        return {
            "channel": "telegram",
            "message": prompt,
            "missionId": mission.mission_id,
        }

    def resume_mission(
        self, mission: Mission, workspace: WorkspaceProfile
    ) -> dict[str, object]:
        objective = build_mission_resume_objective(mission)
        route_contract = self._route_contract(mission)
        return {
            "launch_command": self._mission_launch_command(
                objective,
                workspace_root=workspace.root_path,
                route_contract=route_contract,
            ),
            "workspace": workspace.root_path,
            "runtime_id": self.runtime_id,
            "route_contract": route_contract,
            "route_summary": self._route_summary(route_contract),
        }

    def stop_mission(self, mission: Mission) -> dict[str, object]:
        return {
            "message": f"Stop requested for Hermes mission {mission.mission_id}.",
            "runtime_id": self.runtime_id,
        }

    def _mission_launch_command(
        self,
        objective: str,
        *,
        workspace_root: str = ".",
        route_contract: dict[str, str] | None = None,
    ) -> str:
        route_contract = route_contract or {}
        provider = self._normalize_provider(route_contract.get("provider", ""))
        model = self._normalize_model(provider, route_contract.get("model", ""))
        native_args = ["hermes", "chat", "-q", objective, "-Q", "--accept-hooks"]
        if model:
            native_args.extend(["--model", model])
        if provider:
            native_args.extend(["--provider", provider])
        root = Path(workspace_root)
        hermes_command = _runtime_which("hermes", root)
        if hermes_command:
            native_args[0] = hermes_command
            return shell_join(native_args)
        hermes_chat_cmd = shell_join(native_args)
        if self._wsl_hermes_available():
            return f"wsl bash -lc {shlex.quote(hermes_chat_cmd)}"
        return hermes_chat_cmd

    def _route_contract(self, mission: Mission) -> dict[str, str]:
        route = mission_phase_route(mission)
        provider = self._normalize_provider(route.get("provider", ""))
        model = self._normalize_model(provider, route.get("model", ""))
        if provider and not model:
            model = HERMES_PROVIDER_DEFAULT_MODELS.get(provider, "")
        return {
            "phase": str(route.get("phase", "")).strip().lower(),
            "role": str(route.get("role", "")).strip().lower(),
            "provider": provider,
            "model": model,
            "effort": str(route.get("effort", "")).strip().lower(),
        }

    def _normalize_provider(self, provider: str) -> str:
        return HERMES_PROVIDER_MAP.get(str(provider or "").strip().lower(), "")

    def _normalize_model(self, provider: str, model: object) -> str:
        value = str(model or "").strip()
        if provider == "opencode-go":
            return normalize_opencode_go_model(value)
        if provider == "openrouter":
            normalized = value.lower()
            if normalized in {"glm-5.2", "glm5.2", "glm_5.2", "openrouter/z-ai/glm-5.2"}:
                return "z-ai/glm-5.2"
            if normalized.startswith("openrouter/"):
                return value.split("/", 1)[1]
        if provider == "openai-codex":
            normalized = value.lower()
            if normalized in {"gpt-5.5-codex", "gpt-5.5-codex-high"}:
                return "gpt-5.5"
            if normalized in {"gpt-5.3-codex", "gpt-5.3"}:
                return "gpt-5.3-codex-spark"
        if provider in {"minimax", "minimax-oauth", "minimax-cn"}:
            normalized = value.lower()
            if normalized in {"minimax-m3", "minimax/minimax-m3"}:
                return "MiniMax-M3"
            if normalized in {
                "minimax-m2.7",
                "minimax-m2.7-highspeed",
                "minimax/minimax-m2.7",
                "minimax/minimax-m2.7-highspeed",
            }:
                return "MiniMax-M3"
            if normalized in {"minimax-m2.5", "minimax/minimax-m2.5"}:
                return "MiniMax-M2.5"
            if normalized in {"minimax-m2.5-free", "minimax/minimax-m2.5-free"}:
                return "MiniMax-M2.5-free"
        return value

    def _route_summary(self, route_contract: dict[str, str]) -> str:
        model = str(route_contract.get("model", "")).strip()
        provider = str(route_contract.get("provider", "")).strip()
        effort = str(route_contract.get("effort", "")).strip()
        role = str(route_contract.get("role", "")).strip()
        phase = str(route_contract.get("phase", "")).strip()
        if not model and not provider:
            return "Hermes launch route is using the runtime default model configuration."
        route_prefix = ""
        if phase or role:
            route_prefix = f"{phase or 'execute'}:{role or 'route'} -> "
        summary = f"Hermes launch route: {route_prefix}{provider or 'auto'}/{model or 'default'}"
        if effort:
            summary += f" ({effort})"
        return summary

    def _wsl_hermes_available(self) -> bool:
        if os.name != "nt":
            return False
        wsl = shutil.which("wsl")
        if not wsl:
            return False
        try:
            completed = subprocess.run(  # noqa: S603
                [wsl, "bash", "-lc", "command -v hermes >/dev/null 2>&1"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                check=False,
                **hidden_windows_subprocess_kwargs(),
            )
        except Exception:  # pragma: no cover - defensive
            return False
        return completed.returncode == 0

    def _wsl_hermes_version(self) -> str | None:
        if os.name != "nt":
            return None
        wsl = shutil.which("wsl")
        if not wsl:
            return None
        try:
            completed = subprocess.run(  # noqa: S603
                [
                    wsl,
                    "bash",
                    "-lc",
                    f"command -v hermes >/dev/null 2>&1 && hermes {shlex.quote('--version')}",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
                **hidden_windows_subprocess_kwargs(),
            )
        except Exception:  # pragma: no cover - defensive
            return None
        if completed.returncode != 0:
            return None
        return (completed.stdout or completed.stderr).strip() or ""
