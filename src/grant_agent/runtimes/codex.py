from __future__ import annotations

import re
import subprocess
import sys
import uuid
from pathlib import Path

from ..models import Mission, RuntimeCapability, RuntimeInstallStatus, WorkspaceProfile
from ..subprocess_utils import hidden_windows_subprocess_kwargs
from .base import (
    AgentRuntimeAdapter,
    build_mission_resume_objective,
    mission_phase_route,
    runtime_subprocess_env,
    runtime_which,
    shell_join,
)


def _version(value: str) -> str | None:
    match = re.search(r"(?<!\d)v?(\d+(?:\.\d+){1,3}(?:[-+][0-9A-Za-z.-]+)?)", value or "")
    return match.group(1) if match else None


class CodexRuntimeAdapter(AgentRuntimeAdapter):
    """Supervise the official Codex CLI through its JSONL exec interface."""

    runtime_id = "codex"
    label = "Codex CLI"

    def list_capabilities(self) -> list[RuntimeCapability]:
        return [
            RuntimeCapability(
                key="headless_json",
                label="Headless JSONL",
                available=True,
                detail="Uses the documented `codex exec --json` event stream.",
            ),
            RuntimeCapability(
                key="provider_owned_auth",
                label="Provider-owned authentication",
                available=True,
                detail="Reuses the saved official Codex CLI login without exposing its token.",
            ),
            RuntimeCapability(
                key="file_edit",
                label="File edits",
                available=True,
                detail="Mission runs use Codex's explicit workspace-write sandbox.",
            ),
            RuntimeCapability(
                key="sessions",
                label="Resumable sessions",
                available=True,
                detail="Codex thread IDs are retained in the normalized runtime event stream.",
            ),
        ]

    def detect(self, workspace_root: Path) -> RuntimeInstallStatus:
        command = runtime_which("codex", workspace_root)
        version = None
        issues: list[str] = []
        if command:
            try:
                completed = subprocess.run(
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
                version = _version((completed.stdout or completed.stderr).strip())
                if completed.returncode != 0:
                    issues.append(f"Codex version probe exited with {completed.returncode}.")
            except Exception as exc:  # pragma: no cover - defensive runtime boundary.
                issues.append(f"Unable to read Codex version: {exc}")
        else:
            issues.append("Codex CLI (`codex`) was not found on PATH.")
        return RuntimeInstallStatus(
            runtime_id=self.runtime_id,
            label=self.label,
            detected=command is not None,
            command=command,
            version=version,
            latest_version=None,
            update_available=False,
            update_command="npm install -g @openai/codex@latest" if command else "",
            update_source_url="https://developers.openai.com/codex/cli/reference/",
            install_hint=(
                "Install with `npm install -g @openai/codex`, then run `codex login` once."
            ),
            doctor_summary=(
                "Codex CLI is installed and can be spawned through JSONL exec."
                if command
                else "Install and authenticate Codex before selecting this runtime."
            ),
            issues=issues,
            capabilities=self.list_capabilities(),
        )

    def install(self) -> dict[str, str]:
        return {
            "command": "npm install -g @openai/codex@latest",
            "follow_up": "codex login",
        }

    def doctor(self, workspace_root: Path) -> RuntimeInstallStatus:
        return self.detect(workspace_root)

    def update(self, workspace_root: Path) -> dict[str, str]:
        return {
            "command": "npm install -g @openai/codex@latest",
            "follow_up": "codex --version",
        }

    def start_mission(
        self,
        mission: Mission,
        workspace: WorkspaceProfile,
    ) -> dict[str, object]:
        return self._launch(mission, workspace, mission.objective)

    def resume_mission(
        self,
        mission: Mission,
        workspace: WorkspaceProfile,
    ) -> dict[str, object]:
        return self._launch(mission, workspace, build_mission_resume_objective(mission))

    def _launch(
        self,
        mission: Mission,
        workspace: WorkspaceProfile,
        objective: str,
    ) -> dict[str, object]:
        root = Path(workspace.root_path)
        command = runtime_which("codex", root)
        if not command:
            raise RuntimeError("Codex CLI (`codex`) was not found on PATH.")
        route = mission_phase_route(mission)
        model = str(route.get("model") or "").strip()
        if model.lower() in {"", "codex", "provider-default", "route-selected"}:
            model = ""
        args = [
            sys.executable,
            "-m",
            "grant_agent.external_cli_bridge",
            "--runtime",
            "codex",
            "--command",
            command,
            "--prompt",
            objective,
            "--mode",
            "mission",
            "--workspace-root",
            str(root),
        ]
        if model:
            args.extend(["--model", model])
        effort = str(route.get("effort") or "").strip()
        if effort:
            args.extend(["--effort", effort])
        return {
            "launch_command": shell_join(args),
            "workspace": workspace.root_path,
            "runtime_id": self.runtime_id,
            "route_contract": {
                "phase": str(route.get("phase") or "execute"),
                "role": str(route.get("role") or "executor"),
                "provider": "openai-codex-oauth",
                "model": model or "provider-default",
                "effort": effort or "high",
                "transport": "codex-exec-jsonl",
                "auth_preference": "official-provider-owned-login",
            },
            "route_summary": (
                f"{route.get('role') or 'executor'} via Codex CLI / "
                f"{model or 'provider default'}"
            ),
        }

    def stream_events(self, mission: Mission) -> list[dict[str, object]]:
        return [
            {
                "kind": "runtime.stream",
                "message": "Codex JSONL events are normalized into Neyvia runtime receipts.",
                "missionId": mission.mission_id,
            }
        ]

    def request_approval(self, mission: Mission, prompt: str) -> dict[str, object]:
        return {"channel": "desktop", "message": prompt, "missionId": mission.mission_id}

    def stop_mission(self, mission: Mission) -> dict[str, object]:
        return {
            "message": f"Stop requested for Codex mission {mission.mission_id}.",
            "runtime_id": self.runtime_id,
        }
