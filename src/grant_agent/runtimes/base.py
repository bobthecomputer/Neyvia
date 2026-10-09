from __future__ import annotations

import os
import shlex
import subprocess
from abc import ABC, abstractmethod
from dataclasses import asdict
from pathlib import Path

from ..models import (
    Mission,
    ModelRouteConfig,
    RuntimeCapability,
    RuntimeInstallStatus,
    WorkspaceProfile,
)

PHASE_ROLE_PREFERENCES: dict[str, tuple[str, ...]] = {
    "plan": ("planner", "executor", "verifier"),
    "replan": ("planner", "verifier", "executor"),
    "execute": ("executor", "planner", "verifier"),
    "verify": ("verifier", "executor", "planner"),
}
PHASE_ALIASES = {
    "planning": "plan",
    "replanning": "replan",
    "execution": "execute",
    "executing": "execute",
    "verification": "verify",
    "verifying": "verify",
}


def shell_join(args: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(args)
    return shlex.join(args)


def _compact_line(value: object, *, limit: int = 420) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _mission_runtime_event_rows(mission: Mission) -> list[dict]:
    rows: list[dict] = []
    for session in list(getattr(mission, "delegated_runtime_sessions", []) or []):
        if isinstance(session, dict):
            events = session.get("latest_events") or []
        else:
            events = getattr(session, "latest_events", []) or []
        for event in list(events):
            if hasattr(event, "__dataclass_fields__"):
                rows.append(asdict(event))
            elif isinstance(event, dict):
                rows.append(dict(event))
    return rows


def _latest_operator_followups(mission: Mission, *, limit: int = 4) -> list[str]:
    followups: list[str] = []
    for event in _mission_runtime_event_rows(mission):
        kind = str(event.get("kind") or "").strip().lower()
        if kind not in {"operator.followup", "operator_followup", "mission.follow_up"}:
            continue
        message = _compact_line(event.get("message") or event.get("detail") or "")
        if message:
            followups.append(message)
    return followups[-limit:]


def _mission_artifact_rows(mission: Mission, *, limit: int = 6) -> list[str]:
    rows: list[str] = []
    proof = getattr(mission, "proof", None)
    for artifact in list(getattr(proof, "artifacts", []) or []):
        rows.append(_compact_line(artifact))
    code_execution = getattr(mission, "code_execution", None)
    for artifact in list(getattr(code_execution, "artifacts", []) or []):
        rows.append(_compact_line(artifact))
    state = getattr(mission, "state", None)
    state_code_execution = getattr(state, "code_execution", {}) or {}
    if isinstance(state_code_execution, dict):
        for artifact in list(state_code_execution.get("artifacts", []) or []):
            rows.append(_compact_line(artifact))
    return [row for row in rows if row][-limit:]


def build_mission_resume_objective(mission: Mission) -> str:
    """Build the runtime-facing resume prompt without losing repair context."""
    from ..ultra_reasoning import format_ultra_resume_boundaries

    mission_id = str(getattr(mission, "mission_id", "") or "").strip()
    objective = _compact_line(getattr(mission, "objective", ""), limit=900)
    title = _compact_line(getattr(mission, "title", ""), limit=220)
    proof = getattr(mission, "proof", None)
    state = getattr(mission, "state", None)
    lines = [
        f"Resume mission {mission_id}: {objective}",
        "",
        "Current mission context:",
    ]
    ultra_lines = format_ultra_resume_boundaries(getattr(mission, "mission_contract", None))
    if ultra_lines:
        lines.extend(["", *ultra_lines])
    if title:
        lines.append(f"- Title: {title}")
    status = str(getattr(state, "status", "") or "").strip()
    stop_reason = str(getattr(state, "stop_reason", "") or "").strip()
    last_error = str(getattr(state, "last_error", "") or "").strip()
    if status:
        lines.append(f"- State: {status}")
    if stop_reason:
        lines.append(f"- Stop reason: {stop_reason}")
    if last_error:
        lines.append(f"- Last error: {_compact_line(last_error)}")

    summary = _compact_line(getattr(proof, "summary", ""), limit=700)
    if summary:
        lines.append(f"- Proof summary: {summary}")
    for item in list(getattr(proof, "blocked_by", []) or [])[-6:]:
        blocked = _compact_line(item)
        if blocked:
            lines.append(f"- Blocker: {blocked}")
    for item in list(getattr(proof, "failed_checks", []) or [])[-6:]:
        failed = _compact_line(item)
        if failed:
            lines.append(f"- Failed check: {failed}")
    for item in _mission_artifact_rows(mission):
        lines.append(f"- Existing artifact evidence: {item}")

    followups = _latest_operator_followups(mission)
    if followups:
        lines.append("")
        lines.append("Latest operator follow-up requirements:")
        for item in followups:
            lines.append(f"- {item}")

    observation_count = max(1, min(24, int(getattr(state, "observation_count", 3) or 3)))
    awareness = str(getattr(state, "cross_mission_awareness", "observe") or "observe").strip().lower()
    if awareness not in {"off", "observe", "adapt"}:
        awareness = "observe"
    lines.extend(
        [
            "",
            "Mission coordination contract:",
            f"- Collect at least {observation_count} concrete observations before final verification.",
            "- If .agent_control/mission_coordination/current.json exists, read it before editing.",
            "- Other mission worktrees are read-only context; never edit or merge them directly.",
            (
                "- Cross-mission awareness is off; work only from this mission's declared scope."
                if awareness == "off"
                else "- Observe sibling mission intent, claimed files, and public interface changes before editing."
                if awareness == "observe"
                else "- Adapt compatible interfaces to sibling mission intent while preserving this mission's objective and isolated worktree."
            ),
        ]
    )

    lines.extend(
        [
            "",
            "Hard artifact/runtime-output gate for this resume:",
            "- Keep the selected runtime and provider/model route intact.",
            "- Produce a concrete runtime-output body that can be shown in the selected Agent thread.",
            "- Produce or update a reviewable artifact under .agent_control/mission_artifacts for this mission.",
            "- Record the artifact path, served URL, or preview URL in the mission proof.",
            "- Add a verifier receipt proving the artifact opened from Workbench or explain the exact blocking failure.",
            "- Do not mark the mission completed when only bookkeeping, planning text, stale delegated snippets, or trace-only rows exist.",
        ]
    )
    return "\n".join(lines)


def runtime_bin_candidates(workspace_root: Path) -> list[Path]:
    root = Path(workspace_root).expanduser()
    candidates = [
        neyvia_managed_runtime_root() / "bin",
        Path.home() / ".local" / "bin",
        root / ".venv" / ("Scripts" if os.name == "nt" else "bin"),
        root / "runtime" / "bin",
        root.parent / "runtime" / "bin",
        root.parent.parent / "runtime" / "bin",
    ]
    if os.name == "nt" and (root / "pyproject.toml").is_file():
        local_app_data = Path(
            os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        )
        candidates.extend(
            [
                local_app_data / "hermes" / "hermes-agent" / "venv" / "Scripts",
                Path.home() / ".grok" / "bin",
            ]
        )
    for parent in [root, *root.parents]:
        candidates.append(parent / "syntelos" / "runtime" / "bin")
    env_runtime_root = (
        os.environ.get("FLUXIO_RUNTIME_ROOT")
        or os.environ.get("SYNTELOS_RUNTIME_ROOT")
        or os.environ.get("SYNTHELOS_RUNTIME_ROOT")
    )
    if env_runtime_root:
        candidates.insert(0, Path(env_runtime_root).expanduser() / "bin")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen or not candidate.exists():
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def neyvia_managed_runtime_root() -> Path:
    """Return the per-user optional-runtime root used by the desktop installer."""

    override = str(os.environ.get("NEYVIA_MANAGED_RUNTIME_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        local = str(os.environ.get("LOCALAPPDATA") or "").strip()
        if local:
            return Path(local).expanduser().resolve() / "Neyvia" / "runtime"
    return Path.home().expanduser().resolve() / ".neyvia" / "runtime"


def runtime_lookup_path(workspace_root: Path) -> str:
    current_path = os.environ.get("PATH", "")
    prefixes = [str(item) for item in runtime_bin_candidates(workspace_root)]
    if not prefixes:
        return current_path
    return os.pathsep.join(prefixes + ([current_path] if current_path else []))


def runtime_subprocess_env(workspace_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    lookup_path = runtime_lookup_path(workspace_root)
    if lookup_path:
        env["PATH"] = lookup_path
    runtime_bins = runtime_bin_candidates(workspace_root)
    if runtime_bins and not str(env.get("NPM_CONFIG_PREFIX") or "").strip():
        env["NPM_CONFIG_PREFIX"] = str(runtime_bins[0].parent)
    _apply_runtime_home_env(env, workspace_root)
    return env


def _apply_runtime_home_env(env: dict[str, str], workspace_root: Path) -> None:
    for runtime_bin in runtime_bin_candidates(workspace_root):
        runtime_root = runtime_bin.parent
        runtime_home = runtime_root / "home"
        runtime_home.mkdir(parents=True, exist_ok=True)
        current_home = str(
            env.get("HOME", "")
            or env.get("USERPROFILE", "")
            or ""
        ).strip()
        managed_home_has_auth = _runtime_home_has_auth(runtime_home)
        prefer_managed_home = (
            managed_home_has_auth
            or not current_home
            or not Path(current_home).expanduser().exists()
        )
        if prefer_managed_home:
            env["HOME"] = str(runtime_home)
        elif current_home:
            # Many Windows CLIs follow HOME/XDG even when the shell exposes
            # only USERPROFILE. Preserve the operator's existing authenticated
            # stores instead of silently switching to an empty managed home.
            env.setdefault("HOME", current_home)
        for key in ("NEYVIA_RUNTIME_HOME", "FLUXIO_RUNTIME_HOME", "SYNTELOS_RUNTIME_HOME"):
            if prefer_managed_home:
                env[key] = str(runtime_home)
            else:
                env.setdefault(key, str(runtime_home))
        xdg_paths = {
            "XDG_DATA_HOME": runtime_home / ".local" / "share",
            "XDG_CONFIG_HOME": runtime_home / ".config",
            "XDG_CACHE_HOME": runtime_home / ".cache",
        }
        for key, fallback_path in xdg_paths.items():
            current_path = str(env.get(key, "") or "").strip()
            ambient_path = (
                Path(current_home) / fallback_path.relative_to(runtime_home)
                if current_home
                else Path()
            )
            if not current_path and current_home and ambient_path.exists():
                env[key] = str(ambient_path)
            elif not current_path or not Path(current_path).expanduser().exists():
                fallback_path.mkdir(parents=True, exist_ok=True)
                env[key] = str(fallback_path)
        hermes_home = runtime_home / ".hermes"
        if hermes_home.exists():
            current_hermes_home = str(env.get("HERMES_HOME", "") or "").strip()
            if (
                managed_home_has_auth
                or not current_hermes_home
                or not Path(current_hermes_home).expanduser().exists()
            ):
                env["HERMES_HOME"] = str(hermes_home)
        for env_file_name in (
            ".neyvia_provider_env",
            ".neyvia_cliproxy_env",
            ".fluxio_provider_env",
            ".fluxio_cliproxy_env",
        ):
            provider_env = runtime_home / env_file_name
            if not provider_env.exists():
                continue
            for raw_line in provider_env.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key.startswith("export "):
                    key = key.removeprefix("export ").strip()
                if key:
                    env[key] = value.strip().strip("\"'")
        return


def _runtime_home_has_auth(runtime_home: Path) -> bool:
    auth_paths = (
        runtime_home / ".neyvia_provider_env",
        runtime_home / ".neyvia_cliproxy_env",
        runtime_home / ".fluxio_provider_env",
        runtime_home / ".fluxio_cliproxy_env",
        runtime_home / ".cli-proxy-api",
        runtime_home / ".hermes" / "auth.json",
        runtime_home / "auth.json",
        runtime_home / ".minimax" / "oauth_creds.json",
        runtime_home / ".openclaw" / "agents" / "main" / "agent" / "auth-profiles.json",
        runtime_home / ".local" / "share" / "opencode" / "auth.json",
        runtime_home / ".codex" / "auth.json",
    )
    return any(
        (path.exists() and path.is_file())
        or (path.exists() and path.is_dir() and any(path.glob("*.json")))
        for path in auth_paths
    )


def runtime_which(command_name: str, workspace_root: Path) -> str | None:
    runtime_candidates = runtime_bin_candidates(workspace_root)
    direct = _direct_runtime_command(command_name, runtime_candidates)
    if direct:
        return direct
    runtime_bins = [str(item) for item in runtime_candidates]
    if runtime_bins:
        current_path = os.environ.get("PATH", "")
        lookup_path = os.pathsep.join(runtime_bins + ([current_path] if current_path else []))
        return shutil_which(command_name, lookup_path)
    return shutil_which(command_name, None)


def _direct_runtime_command(command_name: str, runtime_bins: list[Path]) -> str | None:
    suffixes = ["", ".cmd", ".bat", ".exe"] if os.name == "nt" else [""]
    for runtime_bin in runtime_bins:
        for suffix in suffixes:
            candidate = runtime_bin / f"{command_name}{suffix}"
            if candidate.exists() and candidate.is_file():
                return str(candidate)
    return None


def shutil_which(command_name: str, lookup_path: str | None) -> str | None:
    import shutil

    if lookup_path:
        return shutil.which(command_name, path=lookup_path)
    return shutil.which(command_name)


def shell_with_runtime_path(command: str, workspace_root: Path) -> str:
    if not runtime_bin_candidates(workspace_root):
        return command
    lookup_path = runtime_lookup_path(workspace_root)
    if not lookup_path:
        return command
    if os.name == "nt":
        return f'set "PATH={lookup_path}" && {command}'
    return f"PATH={shlex.quote(lookup_path)}; export PATH; {command}"


def _normalized_route_rows(mission: Mission) -> list[dict[str, str]]:
    route_configs = getattr(mission, "route_configs", None) or []
    normalized_rows: list[dict[str, str]] = []
    for item in route_configs:
        if isinstance(item, dict):
            row = dict(item)
        elif isinstance(item, ModelRouteConfig) or hasattr(item, "__dataclass_fields__"):
            row = asdict(item)
        else:
            continue
        role = str(row.get("role", "")).strip().lower()
        if not role:
            continue
        normalized_rows.append(
            {
                "role": role,
                "provider": str(row.get("provider", "")).strip().lower(),
                "model": str(row.get("model", "")).strip(),
                "effort": str(row.get("effort", "")).strip().lower(),
                "budget_class": str(
                    row.get("budget_class", row.get("budgetClass", ""))
                ).strip(),
            }
        )
    return normalized_rows


def mission_cycle_phase(
    mission: Mission,
    fallback_phase: str = "execute",
) -> str:
    state = getattr(mission, "state", None)
    explicit_phase = str(getattr(state, "current_cycle_phase", "") or "").strip().lower()
    normalized_phase = PHASE_ALIASES.get(explicit_phase, explicit_phase)
    if normalized_phase in PHASE_ROLE_PREFERENCES:
        return normalized_phase

    status = str(getattr(state, "status", "") or "").strip().lower()
    if status in {"draft", "queued"}:
        return "plan"
    if status == "verification_failed":
        return "replan"
    if status in {"completed", "verified"}:
        return "verify"
    return PHASE_ALIASES.get(fallback_phase, fallback_phase)


def mission_phase_route(
    mission: Mission,
    *,
    phase: str | None = None,
    preferred_roles: tuple[str, ...] | None = None,
) -> dict[str, str]:
    normalized_rows = _normalized_route_rows(mission)
    raw_phase = str(phase or mission_cycle_phase(mission)).strip().lower()
    phase_key = PHASE_ALIASES.get(raw_phase, raw_phase)
    default_roles = PHASE_ROLE_PREFERENCES.get(
        phase_key,
        PHASE_ROLE_PREFERENCES["execute"],
    )
    selected_roles = preferred_roles or default_roles
    for role in selected_roles:
        match = next(
            (item for item in normalized_rows if item.get("role") == role),
            None,
        )
        if match is not None:
            return {
                **match,
                "phase": phase_key,
                "phase_label": phase_key,
            }
    return {
        "role": "",
        "provider": "",
        "model": "",
        "effort": "",
        "budget_class": "",
        "phase": phase_key,
        "phase_label": phase_key,
    }


def route_role_for_phase(phase: str) -> str:
    normalized = PHASE_ALIASES.get(str(phase or "execute").strip().lower(), "execute")
    if normalized in {"plan", "replan"}:
        return "planner"
    if normalized == "verify":
        return "verifier"
    return "executor"


def mission_executor_route(
    mission: Mission,
    preferred_roles: tuple[str, ...] = ("executor", "planner", "verifier"),
) -> dict[str, str]:
    return mission_phase_route(
        mission,
        phase="execute",
        preferred_roles=preferred_roles,
    )


class AgentRuntimeAdapter(ABC):
    runtime_id: str
    label: str

    @abstractmethod
    def detect(self, workspace_root: Path) -> RuntimeInstallStatus:
        raise NotImplementedError

    @abstractmethod
    def install(self) -> dict[str, str]:
        raise NotImplementedError

    @abstractmethod
    def doctor(self, workspace_root: Path) -> RuntimeInstallStatus:
        raise NotImplementedError

    @abstractmethod
    def update(self, workspace_root: Path) -> dict[str, str]:
        raise NotImplementedError

    @abstractmethod
    def start_mission(
        self, mission: Mission, workspace: WorkspaceProfile
    ) -> dict[str, object]:
        raise NotImplementedError

    @abstractmethod
    def stream_events(self, mission: Mission) -> list[dict[str, object]]:
        raise NotImplementedError

    @abstractmethod
    def request_approval(self, mission: Mission, prompt: str) -> dict[str, object]:
        raise NotImplementedError

    @abstractmethod
    def resume_mission(self, mission: Mission, workspace: WorkspaceProfile) -> dict[str, object]:
        raise NotImplementedError

    @abstractmethod
    def stop_mission(self, mission: Mission) -> dict[str, object]:
        raise NotImplementedError

    def list_capabilities(self) -> list[RuntimeCapability]:
        return []
