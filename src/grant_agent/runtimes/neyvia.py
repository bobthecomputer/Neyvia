from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..opencode_go_models import native_go_transport_args
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


class NeyviaRuntimeAdapter(AgentRuntimeAdapter):
    """Expose OWN, Neyvia's native plan-first agent, as a supervised runtime."""

    runtime_id = "neyvia-agent"
    label = "Neyvia Agent (OWN)"

    def list_capabilities(self) -> list[RuntimeCapability]:
        return [
            RuntimeCapability(
                key="native_agent_loop",
                label="Native agent loop",
                available=True,
                detail="Neyvia owns the model loop rather than wrapping another coding CLI.",
            ),
            RuntimeCapability(
                key="progressive_tools",
                label="Progressive tools",
                available=True,
                detail="Tools are searched, described, policy checked, and receipt bound.",
            ),
            RuntimeCapability(
                key="specialists",
                label="Planner and verifier specialists",
                available=True,
                detail="Bounded specialist delegation is built into the native run.",
            ),
            RuntimeCapability(
                key="durable_sessions",
                label="Durable sessions",
                available=True,
                detail="SQLite session state and JSON receipts survive process restarts.",
            ),
        ]

    def detect(self, workspace_root: Path) -> RuntimeInstallStatus:
        command = runtime_which("neyvia-agent", workspace_root)
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
                output = (completed.stdout or completed.stderr).strip()
                match = re.search(r"(\d+(?:\.\d+){1,3})", output)
                version = match.group(1) if match else None
                if completed.returncode != 0:
                    issues.append(f"Neyvia Agent version probe exited with {completed.returncode}.")
            except Exception as exc:  # pragma: no cover - defensive runtime boundary.
                issues.append(f"Unable to read Neyvia Agent version: {exc}")
        else:
            issues.append("Neyvia Agent (`neyvia-agent`) was not found on PATH.")
        return RuntimeInstallStatus(
            runtime_id=self.runtime_id,
            label=self.label,
            detected=command is not None,
            command=command,
            version=version,
            latest_version=None,
            update_available=False,
            update_command="python -m pip install --upgrade ." if command else "",
            update_source_url="",
            install_hint="Install the Neyvia Python package into the managed runtime.",
            doctor_summary=(
                "OWN is installed and can be spawned as Neyvia's native agent."
                if command
                else "Install the Neyvia runtime before selecting OWN."
            ),
            issues=issues,
            capabilities=self.list_capabilities(),
        )

    def install(self) -> dict[str, str]:
        return {
            "command": "python -m pip install --upgrade .",
            "follow_up": "neyvia-agent --version",
        }

    def doctor(self, workspace_root: Path) -> RuntimeInstallStatus:
        return self.detect(workspace_root)

    def update(self, workspace_root: Path) -> dict[str, str]:
        return self.install()

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
        command = runtime_which("neyvia-agent", root)
        if not command:
            raise RuntimeError("Neyvia Agent (`neyvia-agent`) was not found on PATH.")
        route = mission_phase_route(mission)
        model = str(route.get("model") or "").strip()
        if model.lower() in {"", "provider-default", "route-selected", "codex"}:
            model = "gpt-5.6-sol"
        args = [
            command,
            objective,
            "--root",
            str(root),
            "--session-id",
            str(mission.mission_id or "neyvia-mission"),
            "--model",
            model,
            "--reasoning-effort",
            str(route.get("effort") or "high"),
            "--max-turns",
            "12",
            "--json",
        ]
        if str(route.get("provider") or "").lower() in {"opencode-go", "opencodego"}:
            args.extend(native_go_transport_args(model))
        return {
            "launch_command": shell_join(args),
            "workspace": workspace.root_path,
            "runtime_id": self.runtime_id,
            "route_contract": {
                "phase": str(route.get("phase") or "execute"),
                "role": str(route.get("role") or "executor"),
                "provider": str(route.get("provider") or "responses-compatible"),
                "model": model,
                "effort": str(route.get("effort") or "high"),
                "transport": "neyvia-native-receipt",
            },
            "route_summary": (
                f"{route.get('role') or 'executor'} via OWN / {model}"
            ),
        }

    def stream_events(self, mission: Mission) -> list[dict[str, object]]:
        return [
            {
                "kind": "runtime.stream",
                "message": "OWN emits a durable native Neyvia run receipt.",
                "missionId": mission.mission_id,
            }
        ]

    def request_approval(self, mission: Mission, prompt: str) -> dict[str, object]:
        return {"channel": "desktop", "message": prompt, "missionId": mission.mission_id}

    def stop_mission(self, mission: Mission) -> dict[str, object]:
        return {
            "message": f"Stop requested for OWN mission {mission.mission_id}.",
            "runtime_id": self.runtime_id,
        }
