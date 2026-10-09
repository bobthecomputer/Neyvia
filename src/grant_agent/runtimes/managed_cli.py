from __future__ import annotations

import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
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


KIMI_CODE_MODEL_IDS = (
    "k3",
    "k3-256k",
    "kimi-for-coding",
    "kimi-for-coding-highspeed",
)
CLAUDE_AGENT_MODEL_ALIASES = ("sonnet", "opus", "haiku", "fable")
SAFE_CUSTOM_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,179}$")


@dataclass(frozen=True)
class ManagedCliSpec:
    runtime_id: str
    label: str
    command_name: str
    default_model: str
    install_command: str
    update_command: str
    login_hint: str
    docs_url: str
    supports_acp: bool
    headless_transport: str = "jsonl"
    security_only: bool = False


MANAGED_CLI_SPECS: dict[str, ManagedCliSpec] = {
    "kimi-code": ManagedCliSpec(
        runtime_id="kimi-code",
        label="Kimi Code",
        command_name="kimi",
        default_model="k3",
        install_command="npm install -g @moonshot-ai/kimi-code",
        update_command="kimi upgrade",
        login_hint="Run `kimi login` or sign in with `/login` in Kimi Code.",
        docs_url="https://www.kimi.com/code/docs/en/kimi-code-cli/guides/getting-started.html",
        supports_acp=True,
    ),
    "claude-code": ManagedCliSpec(
        runtime_id="claude-code",
        label="Claude Code",
        command_name="claude",
        default_model="sonnet",
        install_command="npm install -g @anthropic-ai/claude-code",
        update_command="npm install -g @anthropic-ai/claude-code@latest",
        login_hint=(
            "Authenticate with the official Claude Code login, an Anthropic API key, "
            "Amazon Bedrock, Google Vertex AI, or an operator-owned Anthropic Messages API gateway."
        ),
        docs_url="https://code.claude.com/docs/en/cli-reference",
        supports_acp=False,
    ),
    "grok-build": ManagedCliSpec(
        runtime_id="grok-build",
        label="Grok Build",
        command_name="grok",
        default_model="grok-4.5",
        install_command="curl -fsSL https://x.ai/cli/install.sh | bash",
        update_command="grok update --stable",
        login_hint=(
            "Prefer XAI_API_KEY or a harness profile with baseUrl "
            "(GROK_MODELS_BASE_URL / OpenAI-compatible proxy). "
            "`grok login --device-auth` remains operator-owned, not required for headless runs."
        ),
        docs_url="https://docs.x.ai/build/cli/reference",
        supports_acp=True,
    ),
    "prime-agent": ManagedCliSpec(
        runtime_id="prime-agent",
        label="Prime Agent",
        command_name="prime-agent",
        default_model="provider-selected",
        install_command=(
            "curl -fsSL https://app.primeintellect.ai/prime-agent/install.sh | sh"
        ),
        update_command="prime-agent update",
        login_hint=(
            "Use the official Prime Agent login/provider setup. On Windows, run the "
            "versioned checksum installer in WSL or Git Bash and configure a supported bash shell."
        ),
        docs_url="https://github.com/PrimeIntellect-ai/prime-agent",
        supports_acp=True,
    ),
    "pi": ManagedCliSpec(
        runtime_id="pi",
        label="Pi",
        command_name="pi",
        default_model="provider-selected",
        install_command="npm install -g --ignore-scripts @earendil-works/pi-coding-agent",
        update_command="pi update --self",
        login_hint="Run `pi`, then `/login`; Pi also supports API-key providers including OpenCode Go.",
        docs_url="https://github.com/earendil-works/pi/tree/main/packages/coding-agent",
        supports_acp=False,
    ),
    "deepseek-harness": ManagedCliSpec(
        runtime_id="deepseek-harness",
        label="DeepSeek Harness",
        command_name="dsh",
        default_model="provider-selected",
        install_command="npm install -g @deepseek-ai/dsh",
        update_command="npm install -g @deepseek-ai/dsh@latest",
        login_hint="Configure a model in the DeepSeek Harness settings before running the headless profile.",
        docs_url="https://www.deepseek.com/harness/en/",
        supports_acp=False,
        headless_transport="text-plus-session-log",
    ),
    "gptme": ManagedCliSpec(
        runtime_id="gptme",
        label="gptme",
        command_name="gptme",
        default_model="provider-selected",
        install_command="uv tool install gptme",
        update_command="uv tool upgrade gptme",
        login_hint="Configure a supported provider in gptme or its environment before launching a run.",
        docs_url="https://gptme.org/docs/usage.html",
        supports_acp=True,
    ),
    "wallbreaker": ManagedCliSpec(
        runtime_id="wallbreaker",
        label="Wallbreaker",
        command_name="wallbreaker",
        default_model="profile-selected",
        install_command="uv tool install wallbreaker",
        update_command="uv tool upgrade wallbreaker",
        login_hint=(
            "Configure attacker, target, and judge profiles only for an authorized, controlled security campaign."
        ),
        docs_url="https://github.com/JailbrokenAI/wallbreaker",
        supports_acp=False,
        headless_transport="text-plus-run-log",
        security_only=True,
    ),
    "rook": ManagedCliSpec(
        runtime_id="rook",
        label="Rook",
        command_name="rook",
        default_model="provider-selected",
        install_command="go install github.com/pdparchitect/rook/cmd/rook@latest",
        update_command="go install github.com/pdparchitect/rook/cmd/rook@latest",
        login_hint=(
            "Configure a supported provider, then launch only an explicitly authorized "
            "security objective with reviewed success criteria and rules of engagement."
        ),
        docs_url="https://github.com/pdparchitect/rook",
        supports_acp=False,
        headless_transport="text-plus-session-log",
        security_only=True,
    ),
}


def _normalize_version(value: str) -> str | None:
    match = re.search(r"(?<!\d)v?(\d+(?:\.\d+){1,3}(?:[-+][0-9A-Za-z.-]+)?)", value or "")
    return match.group(1) if match else (" ".join(str(value or "").split())[:80] or None)


def normalize_managed_cli_model(
    runtime_id: str,
    requested_model: str,
    *,
    allow_custom: bool = False,
) -> str:
    spec = MANAGED_CLI_SPECS[runtime_id]
    value = str(requested_model or "").strip()
    if not value:
        return spec.default_model
    normalized = value.lower()
    for prefix in (
        f"{runtime_id}/",
        "kimi-code/",
        "grok-build/",
        "claude-code/",
        "prime-agent/",
        "pi/",
        "gptme/",
        "deepseek-harness/",
        "wallbreaker/",
        "rook/",
    ):
        if normalized.startswith(prefix):
            value = value.split("/", 1)[1]
            normalized = value.lower()
            break
    if runtime_id == "kimi-code":
        if normalized not in KIMI_CODE_MODEL_IDS:
            raise ValueError(
                "Kimi Code requires one of k3, k3-256k, kimi-for-coding, or "
                "kimi-for-coding-highspeed. The direct API id kimi-k3 is not a "
                "CLI alias."
            )
        return normalized
    if runtime_id == "grok-build":
        if not SAFE_CUSTOM_MODEL_ID.fullmatch(value):
            raise ValueError("Grok Build model aliases must use a valid CLI model identifier.")
        return value
    if runtime_id in {"prime-agent", "pi", "gptme", "deepseek-harness", "wallbreaker", "rook"}:
        if normalized in {"provider-selected", "profile-selected", "route-selected", "auto"}:
            return ""
        if not SAFE_CUSTOM_MODEL_ID.fullmatch(value):
            raise ValueError(f"{spec.label} model aliases must use a valid provider/model identifier.")
        return value
    if normalized in CLAUDE_AGENT_MODEL_ALIASES or normalized.startswith("claude-"):
        return value
    if allow_custom and SAFE_CUSTOM_MODEL_ID.fullmatch(value):
        return value
    raise ValueError(
        "Claude Code requires a current Claude alias (sonnet, opus, haiku, fable) "
        "or a full claude-* model id. Custom gateway aliases require an explicit harness profile."
    )


class ManagedCliRuntimeAdapter(AgentRuntimeAdapter):
    """Compatibility adapter that supervises an installed, user-owned agent harness."""

    spec: ManagedCliSpec

    def __init__(self, spec: ManagedCliSpec) -> None:
        self.spec = spec
        self.runtime_id = spec.runtime_id
        self.label = spec.label

    def list_capabilities(self) -> list[RuntimeCapability]:
        capabilities = [
            RuntimeCapability(
                key="runtime_cli",
                label="Runtime CLI",
                available=False,
                detail=f"The installed {self.label} executable can be supervised as a child process.",
            ),
            RuntimeCapability(
                key=(
                    "headless_json"
                    if self.spec.headless_transport == "jsonl"
                    else "headless_log"
                ),
                label=(
                    "Headless JSON transport"
                    if self.spec.headless_transport == "jsonl"
                    else "Headless text and durable log transport"
                ),
                available=False,
                detail=(
                    "Fluxio normalizes the documented non-interactive JSON stream into runtime events and receipts."
                    if self.spec.headless_transport == "jsonl"
                    else "Fluxio captures the documented headless output and binds it to the harness-owned durable log."
                ),
            ),
            RuntimeCapability(
                key="agent_live_messages",
                label="Agent Live messages",
                available=False,
                detail="Assistant and tool events are mapped into the shared Agent Live transcript.",
            ),
            RuntimeCapability(
                key="file_edit",
                label="File edits",
                available=False,
                detail="The external CLI may edit the isolated mission workspace under its own permission rules.",
            ),
            RuntimeCapability(
                key="shell_commands",
                label="Shell commands",
                available=False,
                detail="The external CLI may run commands under its own permission rules and Fluxio workspace boundary.",
            ),
            RuntimeCapability(
                key="browser_inspection",
                label="Browser inspection",
                available=False,
                detail="Browser control is not inferred from CLI detection; attach Fluxio Browser proof separately.",
            ),
        ]
        if self.spec.supports_acp:
            capabilities.append(
                RuntimeCapability(
                    key="acp_transport",
                    label="ACP transport",
                    available=False,
                    detail="The provider exposes ACP, but Fluxio reports it ready only after a live negotiation receipt.",
                )
            )
        return capabilities

    def detect(self, workspace_root: Path) -> RuntimeInstallStatus:
        command = runtime_which(self.spec.command_name, workspace_root)
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
                if completed.returncode != 0:
                    issues.append(f"{self.label} version probe exited with {completed.returncode}.")
            except Exception as exc:  # pragma: no cover - defensive boundary
                issues.append(f"Unable to read {self.label} version: {exc}")
        else:
            issues.append(f"{self.label} CLI (`{self.spec.command_name}`) was not found on PATH.")

        return RuntimeInstallStatus(
            runtime_id=self.runtime_id,
            label=self.label,
            detected=command is not None,
            command=command,
            version=version,
            latest_version=None,
            update_available=False,
            update_command=self.spec.update_command if command else "",
            update_source_url=self.spec.docs_url,
            install_hint=f"Install with `{self.spec.install_command}`. {self.spec.login_hint}",
            doctor_summary=(
                (
                    f"{self.label} is installed. {self._transport_label()} and ACP remain capability-probed at run time."
                    if self.spec.supports_acp
                    else f"{self.label} is installed. {self._transport_label()} remains capability-probed at run time."
                )
                if command
                else f"Install and authenticate {self.label} before selecting this runtime."
            ),
            issues=issues,
            capabilities=self.list_capabilities(),
        )

    def install(self) -> dict[str, str]:
        return {"command": self.spec.install_command, "follow_up": self.spec.login_hint}

    def _transport_label(self) -> str:
        return (
            "Headless JSON"
            if self.spec.headless_transport == "jsonl"
            else "Headless text with a durable harness log"
        )

    def doctor(self, workspace_root: Path) -> RuntimeInstallStatus:
        status = self.detect(workspace_root)
        if status.detected and not status.version:
            status.issues.append(f"{self.label} responded, but its version was not readable.")
        return status

    def update(self, workspace_root: Path) -> dict[str, str]:
        return {"command": self.spec.update_command, "follow_up": f"{self.spec.command_name} --version"}

    def start_mission(self, mission: Mission, workspace: WorkspaceProfile) -> dict[str, object]:
        route_contract = self._route_contract(mission)
        return {
            "launch_command": self._mission_launch_command(
                mission.objective,
                mission_id=mission.mission_id,
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
                "message": (
                    f"{self.label} output is normalized from its real "
                    f"{self.spec.headless_transport} process."
                ),
                "missionId": mission.mission_id,
            }
        ]

    def request_approval(self, mission: Mission, prompt: str) -> dict[str, object]:
        return {"channel": "desktop", "message": prompt, "missionId": mission.mission_id}

    def resume_mission(self, mission: Mission, workspace: WorkspaceProfile) -> dict[str, object]:
        route_contract = self._route_contract(mission)
        return {
            "launch_command": self._mission_launch_command(
                build_mission_resume_objective(mission),
                mission_id=mission.mission_id,
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
            "message": f"Stop requested for {self.label} mission {mission.mission_id}.",
            "runtime_id": self.runtime_id,
        }

    def _route_contract(self, mission: Mission) -> dict[str, str]:
        route = mission_phase_route(mission)
        requested_provider = str(route.get("provider") or "").strip().lower()
        requested_model = str(route.get("model") or "").strip()
        profile_id = str(
            getattr(mission, "harness_profile_id", None)
            or route.get("harness_profile_id")
            or route.get("harnessProfileId")
            or ""
        ).strip()
        allow_custom = bool(profile_id) or self.runtime_id in {
            "grok-build",
            "prime-agent",
            "pi",
            "gptme",
            "deepseek-harness",
            "wallbreaker",
            "rook",
        }
        model = normalize_managed_cli_model(
            self.runtime_id,
            requested_model,
            allow_custom=allow_custom,
        )
        return {
            "phase": str(route.get("phase") or "execute").strip().lower(),
            "role": str(route.get("role") or "executor").strip().lower(),
            "provider": self.runtime_id,
            "requested_provider": requested_provider,
            "model": model,
            "canonical_model_id": model,
            "effort": str(route.get("effort") or "high").strip().lower(),
            "transport": self.spec.headless_transport,
            "acp_status": "available_unproven" if self.spec.supports_acp else "not_exposed",
            "harness_profile_id": profile_id,
            "auth_preference": (
                "official-claude-login-or-anthropic-api"
                if self.runtime_id == "claude-code"
                else "authorized-security-profiles"
                if self.spec.security_only
                else "api-key-or-provider-login"
            ),
            "security_only": "true" if self.spec.security_only else "false",
        }

    def _normalize_model(self, requested_model: str) -> str:
        return normalize_managed_cli_model(self.runtime_id, requested_model)

    def _mission_launch_command(
        self,
        objective: str,
        *,
        mission_id: str,
        workspace_root: str,
        route_contract: dict[str, str],
    ) -> str:
        root = Path(workspace_root)
        command = runtime_which(self.spec.command_name, root)
        if not command:
            raise RuntimeError(
                f"{self.label} CLI (`{self.spec.command_name}`) was not found on PATH."
            )
        session_id = ""
        if self.runtime_id in {"grok-build", "claude-code"}:
            session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"fluxio:{self.runtime_id}:{mission_id}"))
        args = [
            sys.executable,
            "-m",
            "grant_agent.external_cli_bridge",
            "--runtime",
            self.runtime_id,
            "--command",
            command,
            "--prompt",
            objective,
            "--mode",
            "mission",
            "--workspace-root",
            str(root),
        ]
        model = str(route_contract.get("model") or "").strip()
        if model:
            args.extend(["--model", model])
        effort = str(route_contract.get("effort") or "").strip()
        if effort:
            args.extend(["--effort", effort])
        if session_id:
            args.extend(["--session-id", session_id])
        profile_id = str(route_contract.get("harness_profile_id") or "").strip()
        if profile_id:
            args.extend(["--harness-profile", profile_id])
        return shell_join(args)

    @staticmethod
    def _route_summary(route_contract: dict[str, str]) -> str:
        model = route_contract.get("model") or "provider default"
        return (
            f"{route_contract.get('role') or 'executor'} via "
            f"{route_contract.get('provider')} / {model} / "
            f"{route_contract.get('effort') or 'default'}"
        )


class KimiCodeRuntimeAdapter(ManagedCliRuntimeAdapter):
    def __init__(self) -> None:
        super().__init__(MANAGED_CLI_SPECS["kimi-code"])


class ClaudeCodeRuntimeAdapter(ManagedCliRuntimeAdapter):
    def __init__(self) -> None:
        super().__init__(MANAGED_CLI_SPECS["claude-code"])


class GrokBuildRuntimeAdapter(ManagedCliRuntimeAdapter):
    def __init__(self) -> None:
        super().__init__(MANAGED_CLI_SPECS["grok-build"])


class PrimeAgentRuntimeAdapter(ManagedCliRuntimeAdapter):
    def __init__(self) -> None:
        super().__init__(MANAGED_CLI_SPECS["prime-agent"])


class PiRuntimeAdapter(ManagedCliRuntimeAdapter):
    def __init__(self) -> None:
        super().__init__(MANAGED_CLI_SPECS["pi"])


class DeepSeekHarnessRuntimeAdapter(ManagedCliRuntimeAdapter):
    def __init__(self) -> None:
        super().__init__(MANAGED_CLI_SPECS["deepseek-harness"])


class GptmeRuntimeAdapter(ManagedCliRuntimeAdapter):
    def __init__(self) -> None:
        super().__init__(MANAGED_CLI_SPECS["gptme"])


class WallbreakerRuntimeAdapter(ManagedCliRuntimeAdapter):
    def __init__(self) -> None:
        super().__init__(MANAGED_CLI_SPECS["wallbreaker"])


class RookRuntimeAdapter(ManagedCliRuntimeAdapter):
    def __init__(self) -> None:
        super().__init__(MANAGED_CLI_SPECS["rook"])


