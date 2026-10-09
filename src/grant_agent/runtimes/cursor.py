from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
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

# The desktop editor also installs a `cursor` command on Windows. It accepts
# `--version`, but commands such as `status` launch the GUI instead of the
# headless agent. Cursor's documented automation binary is `cursor-agent`, so
# never treat the editor shim as an agent runtime.
CURSOR_CLI_COMMAND_CANDIDATES = ("cursor-agent",)


class CursorRuntimeAdapter(AgentRuntimeAdapter):
    """Cursor wired through its CLI (`cursor-agent`), not UI automation.

    The CLI/API path is the durable provider integration; driving the Cursor
    desktop app through UI automation stays a fallback outside this adapter.
    """

    runtime_id = "cursor"
    label = "Cursor CLI"

    def list_capabilities(self) -> list[RuntimeCapability]:
        return [
            RuntimeCapability(
                key="native_cursor_cli_run",
                label="Native Cursor CLI run",
                available=True,
                detail="Runs cursor-agent in non-interactive print mode inside the workspace.",
            ),
            RuntimeCapability(
                key="agent_live_messages",
                label="Agent Live messages",
                available=True,
                detail="Assistant output is captured from the CLI stream with real runtime provenance.",
            ),
            RuntimeCapability(
                key="file_edit",
                label="File edits",
                available=True,
                detail="Cursor CLI applies workspace file edits directly.",
            ),
            RuntimeCapability(
                key="shell_commands",
                label="Shell commands",
                available=True,
                detail="Cursor CLI can execute command-backed coding tasks when permitted.",
            ),
            RuntimeCapability(
                key="browser_inspection",
                label="Browser inspection",
                available=False,
                detail="Cursor CLI does not expose browser control; Fluxio Browser proof is attached by the verifier route.",
            ),
        ]

    def detect(self, workspace_root: Path) -> RuntimeInstallStatus:
        command = self._cli_command(workspace_root)
        version = None
        issues: list[str] = []
        if not command:
            wsl_version = self._wsl_cursor_version()
            if wsl_version:
                command = "wsl:cursor-agent"
                version = wsl_version
        if command and command != "wsl:cursor-agent":
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
                issues.append(f"Unable to read Cursor CLI version: {exc}")
        elif not command:
            issues.append("Cursor CLI (cursor-agent) was not found on PATH or inside WSL.")

        return RuntimeInstallStatus(
            runtime_id=self.runtime_id,
            label=self.label,
            detected=command is not None,
            command=command,
            version=version,
            latest_version=None,
            update_available=False,
            update_command=self.update(workspace_root).get("command", "") if command else "",
            update_source_url="https://cursor.com/cli",
            install_hint=(
                "Install the Cursor CLI from https://cursor.com/cli, then run "
                "`cursor-agent login` so missions can route through it."
            ),
            doctor_summary=(
                "Cursor CLI is ready for native mission routing."
                if command
                else "Install the Cursor CLI (cursor-agent) before selecting the Cursor runtime."
            ),
            issues=issues,
            capabilities=self.list_capabilities(),
        )

    def install(self) -> dict[str, str]:
        return {
            "command": "curl https://cursor.com/install -fsS | bash",
            "follow_up": "cursor-agent login",
        }

    def doctor(self, workspace_root: Path) -> RuntimeInstallStatus:
        status = self.detect(workspace_root)
        if status.detected and not status.version:
            status.issues.append("Cursor CLI responded, but version output was empty.")
        if status.detected:
            login_state = self._login_state(status.command or "cursor-agent", workspace_root)
            if login_state == "unknown" and str(status.command or "").startswith("wsl:"):
                login_state = self._wsl_login_state()
            if login_state == "logged_out":
                status.issues.append("Cursor CLI is installed but not logged in. Run `cursor-agent login`.")
                status.doctor_summary = "Cursor CLI is installed; log in with `cursor-agent login` to route missions."
        return status

    def update(self, workspace_root: Path) -> dict[str, str]:
        return {
            "command": "cursor-agent update",
            "follow_up": "cursor-agent --version",
        }

    def start_mission(
        self, mission: Mission, workspace: WorkspaceProfile
    ) -> dict[str, object]:
        route_contract = self._route_contract(mission)
        return {
            "launch_command": self._mission_launch_command(
                mission.objective,
                workspace_root=workspace.root_path,
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
                "message": "Cursor CLI mission stream is captured from cursor-agent print-mode output.",
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
                route_contract=route_contract,
            ),
            "workspace": workspace.root_path,
            "runtime_id": self.runtime_id,
            "route_contract": route_contract,
            "route_summary": self._route_summary(route_contract),
        }

    def stop_mission(self, mission: Mission) -> dict[str, object]:
        return {
            "message": f"Stop requested for Cursor CLI mission {mission.mission_id}.",
            "runtime_id": self.runtime_id,
        }

    def _cli_command(self, workspace_root: Path) -> str | None:
        for candidate in CURSOR_CLI_COMMAND_CANDIDATES:
            command = runtime_which(candidate, workspace_root)
            if command:
                return command
        return None

    def _login_state(self, command: str, workspace_root: Path) -> str:
        try:
            completed = subprocess.run(  # noqa: S603
                [command, "status"],
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
        except Exception:  # pragma: no cover - defensive
            return "unknown"
        output = f"{completed.stdout}\n{completed.stderr}".lower()
        if "not logged in" in output or "logged out" in output:
            return "logged_out"
        if "logged in" in output or "authenticated" in output:
            return "logged_in"
        if "login" in output:
            return "logged_out"
        return "unknown"

    def _mission_launch_command(
        self,
        objective: str,
        *,
        workspace_root: str = ".",
        route_contract: dict[str, str] | None = None,
    ) -> str:
        root = Path(workspace_root)
        cursor_command = self._cli_command(root)
        route_contract = route_contract or {}
        args = [
            cursor_command or "cursor-agent",
            "--print",
            "--output-format",
            "text",
            "--force",
        ]
        model = str(route_contract.get("model", "")).strip()
        if model:
            args.extend(["--model", model])
        args.append(objective)
        if cursor_command:
            return shell_join(args)
        if self._wsl_cursor_available():
            inner = shlex.join(args)
            return f"wsl bash -lc {shlex.quote(inner)}"
        return shell_join(args)

    def _route_contract(self, mission: Mission) -> dict[str, str]:
        route = mission_phase_route(mission)
        return {
            "phase": str(route.get("phase", "")).strip().lower(),
            "role": str(route.get("role", "")).strip().lower(),
            "provider": "cursor",
            "model": str(route.get("model", "")).strip(),
            "canonical_model_id": str(route.get("model", "")).strip(),
            "effort": str(route.get("effort", "")).strip().lower(),
        }

    def _route_summary(self, route_contract: dict[str, str]) -> str:
        model = str(route_contract.get("model", "")).strip()
        role = str(route_contract.get("role", "")).strip()
        phase = str(route_contract.get("phase", "")).strip()
        if not model:
            return "Cursor CLI launch route is using the Cursor default model configuration."
        route_prefix = ""
        if phase or role:
            route_prefix = f"{phase or 'execute'}:{role or 'route'} -> "
        return f"Cursor CLI launch route: {route_prefix}{model}"


    def _wsl_cursor_available(self) -> bool:
        return self._wsl_cursor_version() is not None

    def _wsl_cursor_version(self) -> str | None:
        if os.name != "nt":
            return None
        wsl = shutil.which("wsl")
        if not wsl:
            return None
        try:
            completed = subprocess.run(  # noqa: S603
                [wsl, "bash", "-lc", "command -v cursor-agent >/dev/null 2>&1 && cursor-agent --version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=12,
                check=False,
                **hidden_windows_subprocess_kwargs(),
            )
        except Exception:  # pragma: no cover - defensive
            return None
        if completed.returncode != 0:
            return None
        return _normalize_version((completed.stdout or completed.stderr).strip())

    def _wsl_login_state(self) -> str:
        if os.name != "nt":
            return "unknown"
        wsl = shutil.which("wsl")
        if not wsl:
            return "unknown"
        try:
            completed = subprocess.run(  # noqa: S603
                [wsl, "bash", "-lc", "cursor-agent status"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=12,
                check=False,
                **hidden_windows_subprocess_kwargs(),
            )
        except Exception:  # pragma: no cover - defensive
            return "unknown"
        output = f"{completed.stdout} {completed.stderr}".lower()
        if "not logged in" in output or "logged out" in output:
            return "logged_out"
        if "logged in" in output or "authenticated" in output:
            return "logged_in"
        if "login" in output:
            return "logged_out"
        return "unknown"


def _normalize_version(value: str) -> str | None:
    first = str(value or "").strip().splitlines()
    if not first:
        return None
    match = re.search(r"\d+(?:\.\d+)+", first[0])
    return match.group(0) if match else first[0].strip() or None
