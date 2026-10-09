from __future__ import annotations

import copy
import json
import os
import platform
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from .models import GuidanceCard, ImprovementQueueItem, OnboardingProgress, TutorialStep
from .profiles import ProfileRegistry
from .runtime_updates import (
    compare_version_tokens,
    latest_hermes_release,
    latest_openclaw_release,
    normalize_hermes_version,
    normalize_openclaw_version,
)
from .runtimes import runtime_adapter_map
from .runtimes.openclaw import read_openclaw_package_version
from .snapshot_cache import (
    invalidate_persistent_snapshot_cache,
    load_persistent_snapshot_cache,
    save_persistent_snapshot_cache,
)
from .subprocess_utils import hidden_windows_subprocess_kwargs

MINIMAX_GLOBAL_OPENCLAW_DOCS = "https://platform.minimax.io/docs/token-plan/openclaw"
MINIMAX_CN_OPENCLAW_DOCS = "https://platform.minimaxi.com/docs/token-plan/openclaw"
MINIMAX_GLOBAL_API_PORTAL = "https://platform.minimax.io/user-center/basic-information/interface-key"
MINIMAX_CN_API_PORTAL = "https://platform.minimaxi.com/user-center/basic-information/interface-key"

_ONBOARDING_CACHE_TTL_SECONDS = max(
    float(os.environ.get("FLUXIO_ONBOARDING_CACHE_TTL_SECONDS", "300")),
    5.0,
)
_ONBOARDING_CACHE: dict[str, tuple[float, dict]] = {}


def _shell_open_url_command(url: str, platform_name: str) -> str:
    normalized_platform = (platform_name or "").strip().lower()
    if normalized_platform == "windows":
        return f'start "" "{url}"'
    if normalized_platform == "darwin":
        return f'open "{url}"'
    return f'xdg-open "{url}"'


def _python_module_version(module_name: str, version_attr: str = "__version__") -> dict:
    python_command = shutil.which("python") or shutil.which("python3")
    if not python_command:
        return {
            "installed": False,
            "command": None,
            "version": "",
            "details": "Python is not ready yet. Install Python first, then Syntelos can add image tools automatically.",
        }
    script = (
        "import importlib; "
        f"module=importlib.import_module({module_name!r}); "
        f"print(getattr(module, {version_attr!r}, 'installed'))"
    )
    try:
        completed = subprocess.run(  # noqa: S603
            [python_command, "-c", script],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "installed": False,
            "command": python_command,
            "version": "",
            "details": f"Could not check {module_name}: {exc}",
        }
    version = completed.stdout.strip()
    if completed.returncode == 0:
        return {
            "installed": True,
            "command": python_command,
            "version": version,
            "details": "Installed and ready.",
        }
    return {
        "installed": False,
        "command": python_command,
        "version": "",
        "details": "Missing. Syntelos can install it for image review and visual automation.",
    }


def _primary_workspace_contract(root: Path) -> dict:
    workspaces = _load_control_list(root, "workspaces.json")
    if not workspaces:
        return {}
    return dict(workspaces[0])


def _minimax_auth_label(mode: str) -> str:
    normalized = str(mode or "none").strip().lower()
    if normalized in {
        "minimax-portal-oauth",
        "minimax-global-oauth",
        "minimax-cn-oauth",
        "oauth",
        "oauth-cn",
    }:
        return "MiniMax OpenClaw OAuth"
    if normalized == "minimax-api":
        return "API key"
    return "not configured"


def _normalize_minimax_auth_mode(value: object) -> str:
    normalized = str(value or "none").strip().lower()
    if normalized in {
        "minimax-portal-oauth",
        "minimax-global-oauth",
        "minimax-cn-oauth",
        "oauth",
        "oauth-cn",
        "portal-oauth",
    }:
        return "minimax-portal-oauth"
    if normalized in {"minimax-api", "minimax_api", "minimax-global-api", "minimax-cn-api"}:
        return "minimax-api"
    return "none"


def _minimax_openclaw_oauth_present() -> bool:
    return bool(str(os.environ.get("FLUXIO_MINIMAX_OPENCLAW_OAUTH_PRESENT", "")).strip())


def _normalize_openai_codex_auth_mode(value: object) -> str:
    normalized = str(value or "none").strip().lower()
    if normalized in {"chatgpt", "chatgpt-portal", "portal", "oauth", "chatgpt-oauth"}:
        return "oauth"
    if normalized in {"api", "api-key", "api_key"}:
        return "api"
    if normalized in {"codex-oauth", "openai-codex-oauth", "chatgpt_oauth"}:
        return "oauth"
    return normalized if normalized in {"none", "api", "oauth"} else "none"


def _openai_codex_auth_label(mode: str) -> str:
    normalized = _normalize_openai_codex_auth_mode(mode)
    if normalized == "api":
        return "API key"
    if normalized == "oauth":
        return "OpenAI Codex OAuth"
    return "not configured"


def _model_auth_ready(
    openai_codex_auth_mode: str,
    minimax_auth_mode: str,
) -> bool:
    minimax_mode = _normalize_minimax_auth_mode(minimax_auth_mode)
    return _normalize_openai_codex_auth_mode(openai_codex_auth_mode) in {
        "api",
        "oauth",
    } or minimax_mode == "minimax-api" or (
        minimax_mode == "minimax-portal-oauth" and _minimax_openclaw_oauth_present()
    )


def _command_version(command_name: str, version_args: list[str] | None = None) -> dict:
    command = shutil.which(command_name)
    if not command:
        # Hermes is frequently installed in WSL2 on Windows hosts.
        if command_name == "hermes":
            wsl_lookup = _command_version_from_wsl(command_name, version_args)
            if wsl_lookup.get("installed"):
                return wsl_lookup
        return {
            "installed": False,
            "command": None,
            "version": None,
            "details": f"{command_name} was not found on PATH.",
        }

    if command_name == "openclaw":
        package_version = read_openclaw_package_version(command)
        if package_version:
            return {
                "installed": True,
                "command": command,
                "version": package_version,
                "details": "Installed and reachable.",
            }

    args = [command, *(version_args or ["--version"])]
    try:
        completed = subprocess.run(  # noqa: S603
            args,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
        version_text = (completed.stdout or completed.stderr).strip() or None
    except Exception as exc:  # pragma: no cover - defensive
        version_text = None
        return {
            "installed": True,
            "command": command,
            "version": None,
            "details": f"Installed, but version lookup failed: {exc}",
        }

    return {
        "installed": True,
        "command": command,
        "version": version_text,
        "details": "Installed and reachable.",
    }


def _command_version_from_wsl(command_name: str, version_args: list[str] | None = None) -> dict:
    if os.name != "nt":
        return {
            "installed": False,
            "command": None,
            "version": None,
            "details": f"{command_name} was not found on PATH.",
        }

    wsl = shutil.which("wsl")
    if not wsl:
        return {
            "installed": False,
            "command": None,
            "version": None,
            "details": (
                f"{command_name} was not found on PATH, and WSL2 is not available for fallback detection."
            ),
        }

    args = " ".join(shlex.quote(arg) for arg in (version_args or ["--version"]))
    escaped_command = shlex.quote(command_name)
    lookup = f"command -v {escaped_command} >/dev/null 2>&1 && {escaped_command} {args}"
    try:
        completed = subprocess.run(  # noqa: S603
            [wsl, "bash", "-lc", lookup],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "installed": False,
            "command": None,
            "version": None,
            "details": f"WSL2 fallback lookup failed: {exc}",
        }

    if completed.returncode != 0:
        return {
            "installed": False,
            "command": None,
            "version": None,
            "details": f"{command_name} was not found on PATH or inside WSL2.",
        }

    version_text = (completed.stdout or completed.stderr).strip() or None
    return {
        "installed": True,
        "command": f"wsl:{command_name}",
        "version": version_text,
        "details": "Installed and reachable inside WSL2.",
    }


def detect_wsl_status() -> dict:
    if os.name != "nt":
        return {
            "required": False,
            "installed": True,
            "default_version": None,
            "details": "WSL2 is only required for the Windows-first install path.",
        }

    wsl = shutil.which("wsl")
    if not wsl:
        return {
            "required": True,
            "installed": False,
            "default_version": None,
            "details": "WSL is not installed. Install WSL2 to support OpenClaw and Hermes cleanly.",
        }

    try:
        completed = subprocess.run(  # noqa: S603
            [wsl, "--status"],
            capture_output=True,
            timeout=10,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
        stdout = _decode_command_output(completed.stdout, completed.stderr)
        lowered = stdout.lower()
        default_version = 2 if "default version: 2" in lowered else None
        if "default version: 1" in lowered:
            default_version = 1
        return {
            "required": True,
            "installed": True,
            "default_version": default_version,
            "details": stdout or "WSL is installed.",
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "required": True,
            "installed": True,
            "default_version": None,
            "details": f"WSL is present, but status lookup failed: {exc}",
        }


def _decode_command_output(stdout: bytes | str, stderr: bytes | str) -> str:
    for value in (stdout, stderr):
        if not value:
            continue
        if isinstance(value, str):
            text = value
        else:
            for encoding in ("utf-8", "utf-16-le", "cp1252"):
                try:
                    text = value.decode(encoding).strip()
                    break
                except UnicodeDecodeError:
                    text = value.decode("utf-8", errors="ignore").strip()
        if text:
            return text.replace("\x00", "")
    return ""


def invalidate_onboarding_status_cache(root: Path | None = None) -> None:
    if root is None:
        _ONBOARDING_CACHE.clear()
        return
    resolved_root = root.resolve()
    _ONBOARDING_CACHE.pop(str(resolved_root), None)
    invalidate_persistent_snapshot_cache(resolved_root, "onboarding_status")


def detect_onboarding_status(root: Path, *, force: bool = False) -> dict:
    root = root.resolve()
    cache_key = str(root)
    now = time.monotonic()
    cached = _ONBOARDING_CACHE.get(cache_key)
    if not force and cached and now - cached[0] < _ONBOARDING_CACHE_TTL_SECONDS:
        return copy.deepcopy(cached[1])
    if not force:
        persisted = load_persistent_snapshot_cache(
            root,
            "onboarding_status",
            _ONBOARDING_CACHE_TTL_SECONDS,
        )
        # Older snapshots predate the progressive first-run contract. Treat
        # them as stale immediately after an upgrade instead of hiding the new
        # setup stages until the ordinary cache TTL expires.
        if isinstance(persisted, dict) and isinstance(
            persisted.get("progressiveSetup"), dict
        ):
            _ONBOARDING_CACHE[cache_key] = (now, copy.deepcopy(persisted))
            return copy.deepcopy(persisted)

    readme_exists = (root / "README.md").exists()
    wsl = detect_wsl_status()
    setup_history = _load_setup_history(root)
    launched_mission_count = _launched_mission_count(root)
    phone_ready = _phone_destination_count(root) > 0
    checks = {
        "node": _command_version("node"),
        "python": _command_version("python"),
        "uv": _command_version("uv", ["--version"]),
        "opencv": _python_module_version("cv2"),
        "openclaw": _command_version("openclaw"),
        "hermes": _command_version("hermes"),
    }
    if checks["openclaw"].get("version"):
        checks["openclaw"]["version"] = normalize_openclaw_version(checks["openclaw"]["version"])
    if checks["hermes"].get("version"):
        checks["hermes"]["version"] = normalize_hermes_version(checks["hermes"]["version"])
    openclaw_latest = latest_openclaw_release()
    if checks["openclaw"].get("installed"):
        current_version = normalize_openclaw_version(checks["openclaw"].get("version") or "")
        latest_version = str(openclaw_latest.get("version") or "").strip()
        update_available = bool(
            current_version and latest_version and compare_version_tokens(current_version, latest_version) < 0
        )
        checks["openclaw"]["latestVersion"] = latest_version
        checks["openclaw"]["updateAvailable"] = update_available
        checks["openclaw"]["updateSourceUrl"] = openclaw_latest.get("sourceUrl") or ""
        if update_available and latest_version:
            checks["openclaw"]["details"] = f"Installed, but latest npm release is {latest_version}."
    hermes_latest = latest_hermes_release()
    if checks["hermes"].get("installed"):
        current_version = normalize_hermes_version(checks["hermes"].get("version") or "")
        latest_version = str(hermes_latest.get("version") or "").strip()
        release_comparison_available = bool(current_version and latest_version)
        update_available = bool(
            current_version and latest_version and compare_version_tokens(current_version, latest_version) < 0
        )
        if not release_comparison_available:
            update_available = "update available" in str(checks["hermes"].get("version") or "").lower()
        checks["hermes"]["latestVersion"] = latest_version
        checks["hermes"]["updateAvailable"] = update_available
        checks["hermes"]["updateSourceUrl"] = hermes_latest.get("sourceUrl") or ""
        if update_available and latest_version:
            location = (
                " inside WSL2"
                if str(checks["hermes"].get("command", "")).startswith("wsl:")
                else ""
            )
            checks["hermes"]["details"] = (
                f"Hermes is installed{location}, but latest upstream release is {latest_version}."
            )
    profile_registry = ProfileRegistry(root / "config" / "profiles.json")
    next_actions = _recommended_next_actions(root, checks, wsl)
    setup_health = _build_setup_health(
        root,
        checks,
        wsl,
        next_actions,
        setup_history=setup_history,
        launched_mission_count=launched_mission_count,
        phone_ready=phone_ready,
    )
    tutorial = _build_tutorial(root, checks, profile_registry, setup_health)
    # First run is a calm projection of this detailed doctor snapshot.  It is
    # derived lazily here so legacy setup consumers keep their exact contract.
    from .progressive_setup import build_progressive_setup

    progressive_setup = build_progressive_setup(root, force=force)
    setup_health["progressiveSetup"] = progressive_setup
    payload = {
        "platform": platform.system(),
        "workspaceRoot": str(root),
        "wsl": wsl,
        "checks": checks,
        "workspaceHints": {
            "hasReadme": readme_exists,
            "hasTauri": (root / "src-tauri").exists(),
            "hasPythonCore": (root / "src" / "grant_agent").exists(),
        },
        "nextActions": next_actions,
        "setupHealth": setup_health,
        "progressiveSetup": progressive_setup,
        "profileChoices": _profile_choices(profile_registry),
        "recommendedProfile": _recommended_profile(root, checks, profile_registry),
        "tutorial": tutorial,
    }
    save_persistent_snapshot_cache(root, "onboarding_status", payload)
    _ONBOARDING_CACHE[cache_key] = (now, copy.deepcopy(payload))
    return payload


def build_guidance_snapshot(root: Path, *, onboarding: dict | None = None) -> dict:
    root = root.resolve()
    onboarding = onboarding or detect_onboarding_status(root)
    profile_registry = ProfileRegistry(root / "config" / "profiles.json")
    checks = onboarding["checks"]
    tutorial = onboarding["tutorial"]
    progress = _load_guidance_progress(root)
    progress.selected_profile = tutorial["selectedProfile"]
    progress.completed_steps = tutorial["completedSteps"]
    progress.current_step_id = tutorial["currentStepId"]
    progress.is_complete = tutorial["isComplete"]
    _save_guidance_progress(root, progress)

    cards = _build_guidance_cards(root, tutorial, checks)
    product_improvements = _build_product_improvements(root, tutorial, checks)
    return {
        "onboardingProgress": progress.__dict__,
        "tutorialSteps": tutorial["steps"],
        "guidanceCards": [card.__dict__ for card in cards],
        "productImprovements": [item.__dict__ for item in product_improvements],
        "profileChoices": _profile_choices(profile_registry),
    }


def _recommended_next_actions(
    root: Path,
    checks: dict | None = None,
    wsl: dict | None = None,
) -> list[str]:
    status: list[str] = []
    wsl = wsl or detect_wsl_status()
    workspace_contract = _primary_workspace_contract(root)
    openai_codex_auth_mode = _normalize_openai_codex_auth_mode(
        workspace_contract.get("openai_codex_auth_mode", "none")
    )
    minimax_auth_mode = _normalize_minimax_auth_mode(
        workspace_contract.get("minimax_auth_mode", "none")
    )
    checks = checks or {
        "node": _command_version("node"),
        "python": _command_version("python"),
        "uv": _command_version("uv", ["--version"]),
        "opencv": _python_module_version("cv2"),
        "openclaw": _command_version("openclaw"),
        "hermes": _command_version("hermes"),
    }
    if wsl["required"] and not wsl["installed"]:
        status.append("Install WSL2 and reboot before backend setup.")
    if not checks["node"]["installed"]:
        status.append("Install Node 22.16+ or Node 24 for OpenClaw.")
    if not checks["python"]["installed"]:
        status.append("Install Python 3.11+ for the Grant Agent core.")
    if not checks["uv"]["installed"]:
        status.append("Use Setup -> Install uv (one click), then run Verify setup health.")
    if checks["python"]["installed"] and not checks.get("opencv", {}).get("installed"):
        status.append("Use Setup -> Install Image tools so screenshots and visual checks work.")
    if not checks["openclaw"]["installed"]:
        status.append("Use Setup -> Install OpenClaw (one click install + onboarding).")
    if not checks["hermes"]["installed"]:
        status.append("Use Setup -> Install Hermes (one click in WSL2, includes setup).")
    if (
        _workspace_count(root)
        and not _launched_mission_count(root)
        and not _model_auth_ready(openai_codex_auth_mode, minimax_auth_mode)
    ):
        status.append(
            "Save an OpenAI API key or MiniMax API key before launching a model-backed mission. ChatGPT app connection is configured separately through ChatGPT Apps/MCP."
        )
    if (root / "src-tauri").exists() and (not shutil.which("cargo") or not shutil.which("rustc")):
        status.append("Install Rust and Cargo before relying on the packaged Tauri desktop path.")
    if not _workspace_count(root):
        status.append("Add your first workspace so Syntelos can recommend skills and approvals.")
    if not _launched_mission_count(root):
        status.append("Launch a first mission to unlock the planner timeline and proof surfaces.")
    if _phone_destination_count(root) == 0:
        status.append("Configure Telegram escalation before long unattended runs.")

    if not status:
        status.append("Setup is complete. Launch or resume a mission.")
    return status


def _profile_choices(profile_registry: ProfileRegistry) -> list[dict]:
    choices: list[dict] = []
    for name in profile_registry.list_names():
        profile = profile_registry.get(name)
        if not profile:
            continue
        choices.append(
            {
                "name": name,
                "description": profile.description,
                "motion": profile.ui.get("motion", "standard"),
                "executionScope": profile.agent.execution_scope or "isolated",
                "approvalMode": profile.agent.approval_mode or "tiered",
                "explanationDepth": profile.agent.explanation_depth or "medium",
                "delegationAggressiveness": profile.agent.delegation_aggressiveness or "balanced",
            }
        )
    return choices


def _recommended_profile(
    root: Path,
    checks: dict,
    profile_registry: ProfileRegistry,
) -> str:
    if not checks["openclaw"]["installed"] or not checks["hermes"]["installed"]:
        return "beginner" if profile_registry.get("beginner") else profile_registry.default_profile
    if _mission_count(root) > 2 and profile_registry.get("advanced"):
        return "advanced"
    return "builder" if profile_registry.get("builder") else profile_registry.default_profile


def _build_tutorial(
    root: Path,
    checks: dict,
    profile_registry: ProfileRegistry,
    setup_health: dict,
) -> dict:
    progress = _load_guidance_progress(root)
    selected_profile = _selected_profile(root) or progress.selected_profile or _recommended_profile(
        root, checks, profile_registry
    )
    workspace_contract = _primary_workspace_contract(root)
    openai_codex_auth_mode = _normalize_openai_codex_auth_mode(
        workspace_contract.get("openai_codex_auth_mode", "none")
    )
    minimax_auth_mode = str(
        workspace_contract.get("minimax_auth_mode", "none")
    ).strip().lower()
    missions = _launched_mission_count(root)
    workspaces = _workspace_count(root)
    phone_ready = _phone_destination_count(root) > 0

    steps = [
        TutorialStep(
            step_id="detect_environment",
            title="Check local setup",
            description="Verify WSL2, Node, Python, uv, OpenClaw, and Hermes before launching a mission.",
            status="completed" if setup_health.get("environmentReady") else "pending",
            cta_label="View setup",
            panel="Setup",
        ),
        TutorialStep(
            step_id="choose_profile",
            title="Choose a guided profile",
            description="Pick Beginner, Builder, Advanced, or Experimental to set safe defaults for approvals and motion.",
            status="completed" if selected_profile else "pending",
            cta_label="Open guidance",
            panel="Guidance",
        ),
        TutorialStep(
            step_id="add_workspace",
            title="Add a workspace",
            description="Register a project so Syntelos can recommend skills, work engines, and verification.",
            status="completed" if workspaces else "pending",
            cta_label="Add workspace",
            panel="Projects",
        ),
        TutorialStep(
            step_id="launch_mission",
            title="Launch a mission",
            description="Start a guided mission to see the planner, approvals, proof, and action timeline in context.",
            status="completed" if missions else "pending",
            cta_label="Start mission",
            panel="Missions",
        ),
        TutorialStep(
            step_id="enable_phone",
            title="Enable phone escalation",
            description="Add a Telegram destination so blocked approvals and completion summaries reach your phone.",
            status="completed" if phone_ready else "pending",
            cta_label="Configure Telegram",
            panel="Integrations",
        ),
    ]
    completed = [item.step_id for item in steps if item.status == "completed"]
    current = next((item.step_id for item in steps if item.status != "completed"), "")
    return {
        "selectedProfile": selected_profile,
        "completedSteps": completed,
        "currentStepId": current,
        "isComplete": not current,
        "steps": [item.__dict__ for item in steps],
    }


def _build_guidance_cards(
    root: Path,
    tutorial: dict,
    checks: dict,
) -> list[GuidanceCard]:
    cards: list[GuidanceCard] = []
    if tutorial["currentStepId"]:
        cards.append(
            GuidanceCard(
                card_id="tutorial.current",
                title="Continue guided setup",
                body="Syntelos keeps the next setup step visible so non-technical users can recover context quickly.",
                kind="tutorial",
                cta_label="Open tutorial",
                panel="Guidance",
            )
        )
    workspace_contract = _primary_workspace_contract(root)
    openai_codex_auth_mode = _normalize_openai_codex_auth_mode(
        workspace_contract.get("openai_codex_auth_mode", "none")
    )
    minimax_auth_mode = str(
        workspace_contract.get("minimax_auth_mode", "none")
    ).strip().lower()
    if _workspace_count(root) and not _model_auth_ready(openai_codex_auth_mode, minimax_auth_mode):
        cards.append(
            GuidanceCard(
                card_id="auth.model",
                title="Authenticate Codex or MiniMax first",
                body="Open Settings and pick one working model account before asking Syntelos to run a real mission.",
                kind="setup",
                cta_label="Open auth",
                panel="Auth",
            )
        )
    if not tutorial["isComplete"] or not checks["openclaw"]["installed"] or not checks["hermes"]["installed"]:
        cards.append(
            GuidanceCard(
                card_id="runtime.install",
                title="Finish runtime setup",
                body="At least one runtime is still missing. Finish setup before expecting deep autonomous loops.",
                kind="setup",
                cta_label="Open setup",
                panel="Setup",
            )
        )
    if not _mission_count(root):
        cards.append(
            GuidanceCard(
                card_id="mission.first",
                title="Run a first mission",
                body="The planner, proof feed, and approvals become easier to understand after one real mission cycle.",
                kind="mission",
                cta_label="Start mission",
                panel="Missions",
            )
        )
    if _phone_destination_count(root) == 0:
        cards.append(
            GuidanceCard(
                card_id="phone.setup",
                title="Set up phone escalation",
                body="Remote approvals are part of the product promise. Configure Telegram before long unattended runs.",
                kind="integration",
                cta_label="Configure Telegram",
                panel="Integrations",
            )
        )
    return cards


def _build_product_improvements(
    root: Path,
    tutorial: dict,
    checks: dict,
) -> list[ImprovementQueueItem]:
    items: list[ImprovementQueueItem] = []
    if not tutorial["isComplete"]:
        items.append(
            ImprovementQueueItem(
                item_id="product_tutorial_completion",
                title="Improve tutorial completion rate",
                reason="The current onboarding path is still incomplete and should surface clearer next actions.",
                priority="high",
                category="tutorial",
            )
        )
    if _phone_destination_count(root) == 0:
        items.append(
            ImprovementQueueItem(
                item_id="product_phone_escalation",
                title="Promote remote approval setup earlier",
                reason="Phone escalation is still unconfigured, which weakens unattended long-run reliability.",
                priority="medium",
                category="automation",
            )
        )
    if not checks["hermes"]["installed"]:
        items.append(
            ImprovementQueueItem(
                item_id="product_runtime_guidance",
                title="Add clearer Hermes setup guidance",
                reason="Hermes is missing, so the setup flow should make the dual-runtime story easier to complete.",
                priority="medium",
                category="setup",
            )
        )
    return items


def _latest_setup_record(
    setup_history: list[dict],
    dependency_id: str | None = None,
    command_surface: str | None = None,
) -> dict:
    filtered = []
    for record in setup_history:
        proposal = record.get("proposal", {})
        args = proposal.get("args", {})
        payload = record.get("result", {}).get("payload", {})
        if dependency_id is not None and (
            args.get("dependencyId") != dependency_id
            and payload.get("dependencyId") != dependency_id
        ):
            continue
        if command_surface is not None and args.get("commandSurface") != command_surface:
            continue
        filtered.append(record)
    if not filtered:
        return {}
    filtered.sort(key=lambda item: item.get("executed_at") or "")
    return filtered[-1]


def _dependency_stage(
    dependency: dict,
    *,
    setup_history: list[dict],
    latest_verify: dict,
) -> str:
    latest_action = _latest_setup_record(setup_history, dependency["dependencyId"])
    latest_surface = latest_action.get("proposal", {}).get("args", {}).get("commandSurface", "")
    latest_gate = latest_action.get("gate", {}).get("status", "")
    latest_ok = latest_action.get("result", {}).get("ok")
    latest_action_time = latest_action.get("executed_at") or ""
    latest_verify_time = latest_verify.get("executed_at") or ""
    installed = bool(dependency.get("installed"))

    if latest_gate == "pending":
        return "install_available"
    if latest_surface == "setup.auth" and latest_ok is False:
        return "failed"
    if latest_surface == "setup.auth" and latest_ok:
        return "healthy" if installed else "verify_pending"
    if latest_surface == "setup.telegram" and latest_ok is False:
        return "failed"
    if latest_surface == "setup.telegram" and latest_ok:
        return "healthy" if installed else "verify_pending"
    if latest_surface in {"setup.install", "setup.repair"} and latest_ok is False:
        return "failed"
    if latest_surface in {"setup.install", "setup.repair"} and latest_ok:
        if installed and latest_verify_time >= latest_action_time:
            return "update_available" if dependency.get("updateAvailable") else "healthy"
        return "verify_pending"
    if installed and dependency.get("updateAvailable"):
        return "update_available"
    if installed:
        return "healthy"
    if dependency.get("repairActions"):
        return "install_available"
    return "missing"


def _service_category_for_dependency(dependency: dict) -> str:
    dependency_id = dependency.get("dependencyId", "")
    category = dependency.get("category", "")
    if dependency_id == "wsl2":
        return "runtime_substrate"
    if dependency_id == "telegram_ready":
        return "connected_app_bridge"
    if dependency_id == "guided_mission":
        return "workflow_gate"
    if category in {"runtime", "agent_runtime"}:
        return "runtime"
    if category == "tooling":
        return "tooling"
    if category == "desktop":
        return "local_service"
    return category or "local_service"


def _install_source_for_dependency(dependency: dict) -> str:
    dependency_id = dependency.get("dependencyId", "")
    repair_actions = dependency.get("repairActions", [])
    primary_action = repair_actions[0] if repair_actions else {}
    platform = primary_action.get("platform", "")
    command = primary_action.get("command", "")
    if dependency_id == "model_auth":
        return "provider_auth"
    if dependency_id == "wsl2":
        return "windows_feature"
    if dependency_id == "guided_mission":
        return "fluxio_desktop"
    if dependency_id == "telegram_ready":
        return "telegram_destination"
    if dependency_id == "minimax_auth":
        return "openclaw_auth"
    if dependency_id == "tauri_prereqs":
        return "rust_toolchain"
    if "winget" in command.lower():
        return "winget"
    if platform == "wsl2":
        return "wsl_script"
    if platform:
        return platform
    return "system_path"


def _verification_result_for_dependency(
    dependency: dict,
    latest_verify: dict,
) -> str:
    stage = dependency.get("stage", "missing")
    verify_ok = latest_verify.get("result", {}).get("ok")
    if stage == "healthy":
        return "passed" if latest_verify else "not_run"
    if stage == "update_available":
        return "outdated"
    if stage == "verify_pending":
        return "pending"
    if verify_ok is False and dependency.get("required"):
        return "failed"
    if stage in {"install_available", "missing", "failed"}:
        return "blocked"
    return "not_run"


def _last_action_summary(record: dict) -> dict:
    if not record:
        return {}
    proposal = record.get("proposal", {})
    result = record.get("result", {})
    return {
        "actionId": proposal.get("args", {}).get("workspaceActionId", ""),
        "title": proposal.get("title", record.get("action_id", "")),
        "status": result.get("result_summary", "") or ("ok" if result.get("ok") else "failed"),
        "executedAt": record.get("executed_at", ""),
    }


def _management_mode_for_dependency(dependency: dict) -> str:
    dependency_id = dependency.get("dependencyId", "")
    if dependency_id == "guided_mission":
        return "externally_managed"
    if dependency_id == "telegram_ready":
        return "fluxio_managed"
    if dependency.get("latestAction"):
        return "fluxio_managed"
    if dependency.get("repairActions"):
        return "fluxio_managed"
    if dependency.get("category") in {"runtime", "agent_runtime", "tooling", "desktop", "platform"}:
        return "externally_managed"
    return "externally_managed"


def _service_actions_for_dependency(dependency: dict) -> list[dict]:
    actions = []
    for action in dependency.get("repairActions", []):
        if (
            not action.get("command")
            and not action.get("followUp")
            and not action.get("batchCommands")
        ):
            continue
        action_kind = str(action.get("kind", "")).strip().lower()
        command_surface = str(action.get("commandSurface", "")).strip()
        if not command_surface:
            command_surface = (
                "setup.install"
                if action_kind == "install"
                else ("setup.auth" if action_kind == "auth" else "setup.repair")
            )
        actions.append(
            {
                **action,
                "surface": "setup",
                "commandSurface": command_surface,
            }
        )
    return actions


def _overall_install_state(dependencies: list[dict], installer_ready: bool) -> str:
    required = [item for item in dependencies if item.get("required")]
    required_stages = [item.get("stage", "missing") for item in required]
    if installer_ready:
        return "healthy"
    if "failed" in required_stages:
        return "failed"
    if "update_available" in required_stages:
        return "update_available"
    if "verify_pending" in required_stages:
        return "verify_pending"
    if "install_available" in required_stages:
        return "install_available"
    if all(stage == "healthy" for stage in required_stages):
        return "verify_pending"
    return "missing"


def _node_install_command(platform_name: str) -> str:
    normalized = (platform_name or "").strip().lower()
    if normalized == "windows":
        return "winget install OpenJS.NodeJS.LTS"
    if normalized == "darwin":
        return "brew install node"
    return "curl -fsSL https://fnm.vercel.app/install | bash && fnm install --lts"


def _uv_install_command(platform_name: str) -> str:
    normalized = (platform_name or "").strip().lower()
    if normalized == "windows":
        return "winget install --id=astral-sh.uv -e"
    return "curl -LsSf https://astral.sh/uv/install.sh | sh"


def _opencv_install_command(platform_name: str) -> str:
    normalized = (platform_name or "").strip().lower()
    python_command = "python" if normalized == "windows" else "python3"
    return f"{python_command} -m pip install opencv-python"


def _runtime_stack_repair_actions(
    *,
    checks: dict[str, dict],
    openclaw_install: dict[str, str],
    hermes_install: dict[str, str],
    openclaw_update: dict[str, str],
    hermes_update: dict[str, str],
    platform_name: str,
) -> list[dict]:
    batch_commands: list[dict] = []
    if not checks["node"]["installed"]:
        batch_commands.append(
            {
                "label": "Install Node LTS",
                "dependencyId": "node",
                "command": _node_install_command(platform_name),
                "followUp": "",
                "platform": platform_name,
                "autoRunFollowUp": False,
            }
        )
    if not checks["uv"]["installed"]:
        batch_commands.append(
            {
                "label": "Install uv",
                "dependencyId": "uv",
                "command": _uv_install_command(platform_name),
                "followUp": "",
                "platform": platform_name,
                "autoRunFollowUp": False,
            }
        )
    if checks["python"]["installed"] and not checks.get("opencv", {}).get("installed"):
        batch_commands.append(
            {
                "label": "Install Image tools",
                "dependencyId": "opencv",
                "command": _opencv_install_command(platform_name),
                "followUp": "",
                "platform": platform_name,
                "autoRunFollowUp": False,
            }
        )
    if not checks["openclaw"]["installed"]:
        batch_commands.append(
            {
                "label": "Install OpenClaw",
                "dependencyId": "openclaw",
                "command": openclaw_install.get("command", ""),
                "followUp": openclaw_install.get("follow_up", ""),
                "platform": platform_name,
                "autoRunFollowUp": True,
            }
        )
    elif checks["openclaw"].get("updateAvailable"):
        batch_commands.append(
            {
                "label": "Update OpenClaw",
                "dependencyId": "openclaw",
                "command": openclaw_update.get("command", ""),
                "followUp": openclaw_update.get("follow_up", ""),
                "platform": platform_name,
                "autoRunFollowUp": True,
            }
        )
    if not checks["hermes"]["installed"]:
        batch_commands.append(
            {
                "label": "Install Hermes",
                "dependencyId": "hermes",
                "command": hermes_install.get("command", ""),
                "followUp": hermes_install.get("follow_up", ""),
                "platform": "wsl2",
                "autoRunFollowUp": True,
            }
        )
    elif checks["hermes"].get("updateAvailable"):
        batch_commands.append(
            {
                "label": "Update Hermes",
                "dependencyId": "hermes",
                "command": hermes_update.get("command", ""),
                "followUp": hermes_update.get("follow_up", ""),
                "platform": "wsl2",
                "autoRunFollowUp": True,
            }
        )
    if not batch_commands:
        return []
    return [
        {
            "actionId": "install_runtime_stack",
            "dependencyId": "runtime_stack",
            "label": "Fix work engine setup",
            "description": "One click installs missing work engines, image tools, and available updates, then checks everything again.",
            "detail": "Syntelos runs the needed setup steps and re-checks the app automatically.",
            "kind": "repair",
            "platform": platform_name,
            "batchCommands": batch_commands,
            "autoRunFollowUp": True,
            "autoRunVerify": True,
            "serviceIds": [
                item.get("dependencyId", "")
                for item in batch_commands
                if item.get("dependencyId")
            ],
        }
    ]


def _build_setup_health(
    root: Path,
    checks: dict[str, dict],
    wsl: dict,
    next_actions: list[str],
    *,
    setup_history: list[dict] | None = None,
    launched_mission_count: int | None = None,
    phone_ready: bool | None = None,
) -> dict:
    setup_history = setup_history or []
    launched_mission_count = (
        _launched_mission_count(root)
        if launched_mission_count is None
        else launched_mission_count
    )
    phone_ready = (
        _phone_destination_count(root) > 0 if phone_ready is None else phone_ready
    )
    adapters = runtime_adapter_map()
    openclaw_install = adapters["openclaw"].install()
    hermes_install = adapters["hermes"].install()
    openclaw_update = adapters["openclaw"].update(root)
    hermes_update = adapters["hermes"].update(root)
    platform_name = platform.system().lower()
    workspace_contract = _primary_workspace_contract(root)
    openai_codex_auth_mode = _normalize_openai_codex_auth_mode(
        workspace_contract.get("openai_codex_auth_mode", "none")
    )
    minimax_auth_mode = str(
        workspace_contract.get("minimax_auth_mode", "none")
    ).strip().lower()
    model_auth_configured = _model_auth_ready(
        openai_codex_auth_mode,
        minimax_auth_mode,
    )
    model_auth_summary = (
        f"Primary model auth is configured through {_openai_codex_auth_label(openai_codex_auth_mode)}."
        if _normalize_openai_codex_auth_mode(openai_codex_auth_mode) in {"api", "oauth"}
        else (
            f"Primary model auth is configured through {_minimax_auth_label(minimax_auth_mode)}."
            if _model_auth_ready("none", minimax_auth_mode)
            else "Save an OpenAI API key, connect OpenAI Codex OAuth, or save a MiniMax API key in Builder -> Runtime before launching a model-backed mission."
        )
    )
    minimax_auth_configured = minimax_auth_mode == "minimax-api" or (
        minimax_auth_mode == "minimax-portal-oauth" and _minimax_openclaw_oauth_present()
    )
    minimax_auth_details = (
        f"MiniMax auth path is configured through {_minimax_auth_label(minimax_auth_mode)}."
        if minimax_auth_configured
        else "Save a MiniMax API key, or complete and verify MiniMax auth in OpenClaw outside this app before routing MiniMax runs."
    )
    tauri_required = (root / "src-tauri").exists()
    cargo_check = (
        _command_version("cargo")
        if tauri_required
        else {
            "installed": True,
            "command": None,
            "version": "",
            "details": "No Tauri desktop shell detected in this workspace.",
        }
    )
    rustc_check = (
        _command_version("rustc")
        if tauri_required
        else {
            "installed": True,
            "command": None,
            "version": "",
            "details": "No Tauri desktop shell detected in this workspace.",
        }
    )
    latest_verify = _latest_setup_record(setup_history, command_surface="setup.verify")

    dependencies = [
        {
            "dependencyId": "model_auth",
            "label": "Model auth",
            "category": "agent_runtime",
            "required": False,
            "installed": model_auth_configured,
            "version": (
                _openai_codex_auth_label(openai_codex_auth_mode)
                if _normalize_openai_codex_auth_mode(openai_codex_auth_mode) in {"api", "oauth"}
                else _minimax_auth_label(minimax_auth_mode)
            ),
            "details": model_auth_summary,
            "repairActions": [],
        },
        {
            "dependencyId": "wsl2",
            "label": "WSL2",
            "category": "platform",
            "required": bool(wsl.get("required")),
            "installed": bool(wsl.get("installed")),
            "version": f"WSL{wsl.get('default_version')}" if wsl.get("default_version") else "",
            "details": wsl.get("details", ""),
            "repairActions": (
                []
                if (not wsl.get("required")) or (wsl.get("installed") and wsl.get("default_version") in {2, None})
                else [
                    {
                        "actionId": "install_wsl2",
                        "label": "Install WSL2",
                        "description": "Install WSL2 and reboot before runtime setup.",
                        "command": "wsl --install",
                        "kind": "install",
                        "platform": "windows",
                    }
                ]
            ),
        },
        {
            "dependencyId": "node",
            "label": "Node",
            "category": "runtime",
            "required": True,
            "installed": bool(checks["node"]["installed"]),
            "version": checks["node"].get("version") or "",
            "details": checks["node"].get("details", ""),
            "repairActions": []
            if checks["node"]["installed"]
            else [
                {
                    "actionId": "install_node",
                    "label": "Install Node LTS",
                    "description": "Install Node for OpenClaw and desktop tooling.",
                    "command": "winget install OpenJS.NodeJS.LTS" if platform_name == "windows" else "",
                    "kind": "install",
                    "platform": platform_name,
                }
            ],
        },
        {
            "dependencyId": "python",
            "label": "Python",
            "category": "runtime",
            "required": True,
            "installed": bool(checks["python"]["installed"]),
            "version": checks["python"].get("version") or "",
            "details": checks["python"].get("details", ""),
            "repairActions": []
            if checks["python"]["installed"]
            else [
                {
                    "actionId": "install_python",
                    "label": "Install Python",
                    "description": "Install Python for the Grant Agent core.",
                    "command": "winget install Python.Python.3.12" if platform_name == "windows" else "",
                    "kind": "install",
                    "platform": platform_name,
                }
            ],
        },
        {
            "dependencyId": "uv",
            "label": "uv",
            "category": "tooling",
            "required": True,
            "installed": bool(checks["uv"]["installed"]),
            "version": checks["uv"].get("version") or "",
            "details": checks["uv"].get("details", ""),
            "repairActions": []
            if checks["uv"]["installed"]
            else [
                {
                    "actionId": "install_uv",
                    "label": "Install uv",
                    "description": "Install uv for faster Python environment management.",
                    "command": "winget install --id=astral-sh.uv -e" if platform_name == "windows" else "",
                    "kind": "install",
                    "platform": platform_name,
                }
            ],
        },
        {
            "dependencyId": "opencv",
            "label": "Image tools",
            "category": "tooling",
            "required": False,
            "installed": bool(checks.get("opencv", {}).get("installed")),
            "version": checks.get("opencv", {}).get("version") or "",
            "details": (
                "Ready for screenshot comparison, visual checks, and future image features."
                if checks.get("opencv", {}).get("installed")
                else "Optional, but recommended for screenshot comparison, visual checks, and image features."
            ),
            "repairActions": []
            if checks.get("opencv", {}).get("installed")
            else [
                {
                    "actionId": "install_opencv",
                    "label": "Install Image tools",
                    "description": "Install OpenCV for screenshots, UI checks, and image features.",
                    "command": _opencv_install_command(platform_name),
                    "kind": "install",
                    "platform": platform_name,
                    "autoRunVerify": True,
                }
            ],
        },
        {
            "dependencyId": "openclaw",
            "label": "OpenClaw",
            "category": "agent_runtime",
            "required": True,
            "installed": bool(checks["openclaw"]["installed"]),
            "version": checks["openclaw"].get("version") or "",
            "latestVersion": checks["openclaw"].get("latestVersion") or "",
            "updateAvailable": bool(checks["openclaw"].get("updateAvailable")),
            "details": (
                (
                    f"{checks['openclaw'].get('details', '')} Latest npm release: {checks['openclaw'].get('latestVersion', '')}."
                    if checks["openclaw"].get("latestVersion")
                    else checks["openclaw"].get("details", "")
                ).strip()
            ),
            "repairActions": (
                [
                    {
                        "actionId": "update_openclaw",
                        "label": "Update OpenClaw",
                        "description": "Upgrade OpenClaw to the latest npm release and rerun onboarding.",
                        "command": openclaw_update.get("command", ""),
                        "followUp": openclaw_update.get("follow_up", ""),
                        "autoRunFollowUp": True,
                        "autoRunVerify": True,
                        "kind": "repair",
                        "platform": platform_name,
                    }
                ]
                if checks["openclaw"].get("updateAvailable")
                else []
            )
            if checks["openclaw"]["installed"]
            else [
                {
                    "actionId": "install_openclaw",
                    "label": "Install OpenClaw",
                    "description": "One-click install and onboarding for OpenClaw.",
                    "command": openclaw_install.get("command", ""),
                    "followUp": openclaw_install.get("follow_up", ""),
                    "autoRunFollowUp": True,
                    "kind": "install",
                    "platform": platform_name,
                }
            ],
        },
        {
            "dependencyId": "hermes",
            "label": "Hermes",
            "category": "agent_runtime",
            "required": True,
            "installed": bool(checks["hermes"]["installed"]),
            "version": checks["hermes"].get("version") or "",
            "latestVersion": checks["hermes"].get("latestVersion") or "",
            "updateAvailable": bool(checks["hermes"].get("updateAvailable")),
            "details": (
                (
                    f"{checks['hermes'].get('details', '')} Latest upstream release: {checks['hermes'].get('latestVersion', '')}."
                    if checks["hermes"].get("latestVersion")
                    else checks["hermes"].get("details", "")
                ).strip()
            ),
            "repairActions": (
                [
                    {
                        "actionId": "update_hermes",
                        "label": "Update Hermes",
                        "description": "Run Hermes self-update and verify the installed version.",
                        "command": hermes_update.get("command", ""),
                        "followUp": hermes_update.get("follow_up", ""),
                        "autoRunFollowUp": True,
                        "autoRunVerify": True,
                        "kind": "repair",
                        "platform": "wsl2" if str(checks["hermes"].get("command", "")).startswith("wsl:") else platform_name,
                    }
                ]
                if checks["hermes"].get("updateAvailable")
                else []
            )
            if checks["hermes"]["installed"]
            else [
                {
                    "actionId": "install_hermes",
                    "label": "Install Hermes",
                    "description": "One-click install inside WSL2 and run Hermes setup.",
                    "command": hermes_install.get("command", ""),
                    "followUp": hermes_install.get("follow_up", ""),
                    "autoRunFollowUp": True,
                    "kind": "install",
                    "platform": "wsl2",
                }
            ],
        },
        {
            "dependencyId": "minimax_auth",
            "label": "MiniMax auth",
            "category": "agent_runtime",
            "required": False,
            "installed": minimax_auth_configured,
            "version": _minimax_auth_label(minimax_auth_mode),
            "details": minimax_auth_details,
            "repairActions": [
                {
                    "actionId": "minimax-global-oauth",
                    "label": "MiniMax global OAuth",
                    "description": "Run OpenClaw's MiniMax portal OAuth flow for the global endpoint.",
                    "command": "openclaw models auth login --provider minimax-portal --method oauth",
                    "followUp": "Syntelos launches this in an interactive terminal from MiniMax account setup, then verifies ~/.minimax/oauth_creds.json.",
                    "kind": "auth",
                    "platform": platform_name,
                },
                {
                    "actionId": "minimax-cn-oauth",
                    "label": "MiniMax CN OAuth",
                    "description": "Run OpenClaw's MiniMax portal OAuth flow for the CN endpoint.",
                    "command": "openclaw models auth login --provider minimax-portal --method oauth-cn",
                    "followUp": "Syntelos launches this in an interactive terminal from MiniMax account setup, then verifies ~/.minimax/oauth_creds.json.",
                    "kind": "auth",
                    "platform": platform_name,
                },
                {
                    "actionId": "minimax-global-api",
                    "label": "MiniMax global API key",
                    "description": "Open the global MiniMax API key portal for OpenClaw API-key auth.",
                    "command": _shell_open_url_command(
                        MINIMAX_GLOBAL_API_PORTAL,
                        platform_name,
                    ),
                    "followUp": "Generate an API key and configure OpenClaw with MiniMax Global API auth.",
                    "kind": "auth",
                    "platform": platform_name,
                },
                {
                    "actionId": "minimax-cn-api",
                    "label": "MiniMax CN API key",
                    "description": "Open the CN MiniMax API key portal for OpenClaw API-key auth.",
                    "command": _shell_open_url_command(
                        MINIMAX_CN_API_PORTAL,
                        platform_name,
                    ),
                    "followUp": "Generate an API key and configure OpenClaw with MiniMax CN API auth.",
                    "kind": "auth",
                    "platform": platform_name,
                },
            ],
        },
        {
            "dependencyId": "tauri_prereqs",
            "label": "Tauri prerequisites",
            "category": "desktop",
            "required": tauri_required,
            "installed": bool(cargo_check["installed"] and rustc_check["installed"]),
            "version": cargo_check.get("version") or rustc_check.get("version") or "",
            "details": (
                "Rust and Cargo are available for Tauri builds."
                if cargo_check["installed"] and rustc_check["installed"]
                else "Install Rust and Cargo before relying on the packaged Tauri desktop path."
            ),
            "repairActions": []
            if (cargo_check["installed"] and rustc_check["installed"])
            else [
                {
                    "actionId": "install_tauri_prereqs",
                    "dependencyId": "tauri_prereqs",
                    "label": "Install Rust toolchain",
                    "description": "Install Rust and Cargo for the Tauri desktop shell.",
                    "command": "winget install Rustlang.Rustup" if platform_name == "windows" else "curl https://sh.rustup.rs -sSf | sh -s -- -y",
                    "followUp": "rustup default stable",
                    "kind": "install",
                    "platform": platform_name,
                }
            ],
        },
        {
            "dependencyId": "telegram_ready",
            "label": "Telegram escalation",
            "category": "readiness",
            "required": False,
            "installed": bool(phone_ready),
            "version": "",
            "details": (
                "A Telegram destination is configured for blocked approvals and completion summaries."
                if phone_ready
                else "Add a Telegram destination so long unattended runs can escalate approvals."
            ),
            "repairActions": []
            if phone_ready
            else [
                {
                    "actionId": "configure_telegram_destination",
                    "label": "One-click Telegram setup",
                    "description": "Detect and save Telegram escalation destination for Syntelos missions.",
                    "detail": (
                        "Uses FLUXIO_TELEGRAM_DESTINATION, TELEGRAM_CHAT_ID, or an existing mission destination."
                    ),
                    "commandSurface": "setup.telegram",
                    "followUp": (
                        "If auto-detection cannot find a destination, set FLUXIO_TELEGRAM_DESTINATION and rerun this action."
                    ),
                    "kind": "repair",
                    "platform": platform_name,
                    "autoRunVerify": True,
                }
            ],
        },
        {
            "dependencyId": "guided_mission",
            "label": "First guided mission",
            "category": "readiness",
            "required": True,
            "installed": launched_mission_count > 0,
            "version": "",
            "details": (
                "Syntelos has already launched a guided mission from the desktop path."
                if launched_mission_count > 0
                else "Finish setup by launching one real guided mission from Syntelos."
            ),
            "repairActions": [],
        },
    ]

    for dependency in dependencies:
        for action in dependency.get("repairActions", []):
            action["dependencyId"] = dependency["dependencyId"]
        dependency["latestAction"] = _latest_setup_record(
            setup_history,
            dependency["dependencyId"],
        )
        dependency["stage"] = _dependency_stage(
            dependency,
            setup_history=setup_history,
            latest_verify=latest_verify,
        )
        dependency["blocked"] = bool(
            dependency.get("required") and dependency.get("stage") != "healthy"
        )
        dependency["serviceCategory"] = _service_category_for_dependency(dependency)
        dependency["installSource"] = _install_source_for_dependency(dependency)
        dependency["currentHealthStatus"] = dependency["stage"]
        dependency["lastVerificationResult"] = _verification_result_for_dependency(
            dependency,
            latest_verify,
        )
        dependency["lastRepairAction"] = _last_action_summary(dependency["latestAction"])
        dependency["managementMode"] = _management_mode_for_dependency(dependency)

    runtime_stack_actions = _runtime_stack_repair_actions(
        checks=checks,
        openclaw_install=openclaw_install,
        hermes_install=hermes_install,
        openclaw_update=openclaw_update,
        hermes_update=hermes_update,
        platform_name=platform_name,
    )
    repair_actions = runtime_stack_actions + [
        action
        for dependency in dependencies
        for action in dependency["repairActions"]
    ]
    missing_dependencies = [
        dependency["label"]
        for dependency in dependencies
        if dependency["required"] and dependency["stage"] != "healthy"
    ]
    filtered_repair_actions = [
        action
        for action in repair_actions
        if action.get("command") or action.get("followUp") or action.get("batchCommands")
    ]
    environment_ready = all(
        dependency["stage"] == "healthy"
        for dependency in dependencies
        if dependency["required"] and dependency["dependencyId"] != "guided_mission"
    )
    installer_ready = all(
        dependency["stage"] == "healthy"
        for dependency in dependencies
        if dependency["required"]
    )
    def history_summary(record: dict) -> dict:
        # Full receipts remain in durable history or its detail files. Embedding
        # their setup snapshots here recursively copies earlier snapshots.
        proposal = record.get("proposal", {})
        result = record.get("result", {})
        return {
            **{key: record[key] for key in ("action_id", "executed_at", "attempts", "event_id") if key in record},
            "proposal": {
                **{key: proposal[key] for key in ("title", "kind", "command", "mutability_class", "requires_approval") if key in proposal},
                "args": {key: proposal.get("args", {})[key] for key in ("workspaceActionId", "dependencyId", "commandSurface", "surface") if key in proposal.get("args", {})},
            },
            "gate": dict(record.get("gate", {})),
            "result": {key: result[key] for key in ("ok", "exit_code", "duration_ms", "error", "result_summary") if key in result},
            "detailPath": record.get("detailPath", ".agent_control/workspace_actions.json"),
        }

    for dependency in dependencies:
        if dependency.get("latestAction"):
            dependency["latestAction"] = history_summary(dependency["latestAction"])
    history_by_dependency = {
        dependency["dependencyId"]: [
            history_summary(record)
            for record in setup_history
            if record.get("proposal", {}).get("args", {}).get("dependencyId")
            == dependency["dependencyId"]
        ][-6:]
        for dependency in dependencies
    }
    verify_action = {
        "actionId": "verify_setup_health",
        "label": "Verify setup health",
        "description": "Re-check local dependencies, runtimes, and blockers after a repair.",
        "commandSurface": "setup.verify",
        "kind": "verify",
        "platform": platform_name,
        "surface": "setup",
    }
    service_management = [
        {
            "serviceId": dependency["dependencyId"],
            "label": dependency["label"],
            "serviceCategory": dependency["serviceCategory"],
            "installSource": dependency["installSource"],
            "currentHealthStatus": dependency["currentHealthStatus"],
            "lastVerificationResult": dependency["lastVerificationResult"],
            "lastRepairAction": dependency["lastRepairAction"],
            "managementMode": dependency["managementMode"],
            "version": dependency.get("version", ""),
            "latestVersion": dependency.get("latestVersion", ""),
            "updateAvailable": dependency.get("updateAvailable", False),
            "details": dependency.get("details", ""),
            "required": dependency.get("required", False),
            "serviceActions": _service_actions_for_dependency(dependency),
            "verifyAction": verify_action,
        }
        for dependency in dependencies
        if dependency["serviceCategory"] != "workflow_gate"
    ]
    summary_items = [
        item for item in service_management if item.get("required", False)
    ]
    return {
        "installState": _overall_install_state(dependencies, installer_ready),
        "environmentReady": environment_ready,
        "installerReady": installer_ready,
        "firstMissionLaunched": launched_mission_count > 0,
        "telegramReady": bool(phone_ready),
        "dependencies": dependencies,
        "missingDependencies": missing_dependencies,
        "repairActions": filtered_repair_actions,
        "globalActions": [verify_action],
        "actionHistoryByDependency": history_by_dependency,
        "serviceManagement": service_management,
        "serviceManagementSummary": {
            "totalItems": len(summary_items),
            "healthyCount": sum(
                1 for item in summary_items if item["currentHealthStatus"] == "healthy"
            ),
            "needsAttentionCount": sum(
                1 for item in summary_items if item["currentHealthStatus"] != "healthy"
            ),
            "fluxioManagedCount": sum(
                1 for item in summary_items if item["managementMode"] == "fluxio_managed"
            ),
            "externalCount": sum(
                1
                for item in summary_items
                if item["managementMode"] == "externally_managed"
            ),
        },
        "blockerExplanations": next_actions,
    }


def _selected_profile(root: Path) -> str:
    workspaces_path = root / ".agent_control" / "workspaces.json"
    if not workspaces_path.exists():
        return ""
    try:
        payload = json.loads(workspaces_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    if not payload:
        return ""
    return str(payload[0].get("user_profile", ""))


def _workspace_count(root: Path) -> int:
    return len(_load_control_list(root, "workspaces.json"))


def _mission_count(root: Path) -> int:
    return len(_load_control_list(root, "missions.json"))


def _launched_mission_count(root: Path) -> int:
    missions = _load_control_list(root, "missions.json")
    return sum(
        1
        for mission in missions
        if mission.get("state", {}).get("latest_session_id")
        or mission.get("state", {}).get("status")
        in {"running", "needs_approval", "verification_failed", "completed", "stopped"}
    )


def _phone_destination_count(root: Path) -> int:
    configured_destination = load_telegram_destination(root)
    missions = _load_control_list(root, "missions.json")
    mission_destinations = sum(
        1
        for mission in missions
        if mission.get("escalation_policy", {}).get("destination")
    )
    return mission_destinations + (1 if configured_destination else 0)


def load_telegram_destination(root: Path) -> str:
    path = root / ".agent_control" / "telegram_settings.json"
    if not path.exists():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("destination", "")).strip()


def _load_control_list(root: Path, filename: str) -> list[dict]:
    path = root / ".agent_control" / filename
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def _load_setup_history(root: Path) -> list[dict]:
    path = root / ".agent_control" / "workspace_actions.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    history = payload.get("__setup__", [])
    return history if isinstance(history, list) else []


def _load_guidance_progress(root: Path) -> OnboardingProgress:
    path = root / ".agent_control" / "guidance_state.json"
    if not path.exists():
        return OnboardingProgress()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return OnboardingProgress()
    return OnboardingProgress(**payload)


def _save_guidance_progress(root: Path, progress: OnboardingProgress) -> None:
    control_dir = root / ".agent_control"
    control_dir.mkdir(parents=True, exist_ok=True)
    path = control_dir / "guidance_state.json"
    payload = json.dumps(progress.__dict__, indent=2)
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == payload:
                return
        except OSError:
            pass
    path.write_text(payload, encoding="utf-8")
