from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from typing import Iterator
from urllib.parse import urlparse

from .runtimes.base import runtime_subprocess_env, runtime_which
from .subprocess_utils import hidden_windows_subprocess_kwargs


HARNESS_PROFILE_RELATIVE_PATH = Path(".agent_control/harness_profiles.json")
MAX_INSTRUCTION_BYTES = 512_000
MAX_PROFILE_COUNT = 40
PROFILE_FIELDS = {
    "id",
    "label",
    "harnessId",
    "providerId",
    "model",
    "smallModel",
    "baseUrl",
    "credentialEnv",
    "credentialKind",
    "compatibilityMode",
}

# Documented open env surfaces (no proprietary protocol decoding).
COMPAT_MODES = {
    "",
    "native",
    "xai-native",
    "api-key",
    "openai-compatible",
    "anthropic-gateway",
    "enterprise-gateway",
    "aws-bedrock",
    "google-vertex",
    "cliproxy",
    "local-proxy",
}


@dataclass(frozen=True)
class HarnessSpec:
    harness_id: str
    label: str
    execution_adapter: str
    command_name: str
    default_model: str
    description: str
    accent: str
    transports: tuple[str, ...]
    instruction_files: tuple[str, ...]
    skill_roots: tuple[str, ...]
    model_policy: str
    docs_url: str
    capabilities: tuple[tuple[str, str, str], ...]
    license_id: str = ""
    integration_tier: str = "first-class"
    headless_transport: str = "native"
    security_only: bool = False


HARNESS_SPECS: tuple[HarnessSpec, ...] = (
    HarnessSpec(
        harness_id="neyvia-agent",
        label="Neyvia Native",
        execution_adapter="neyvia-agent",
        command_name="neyvia-agent",
        default_model="gpt-5.6-sol",
        description=(
            "Neyvia's own plan-first harness: durable sessions, progressive "
            "native and managed tools, specialist delegation, recovery, "
            "approval policy, and proof-bound completion receipts."
        ),
        accent="#70e1b2",
        transports=(
            "OpenAI Responses compatible",
            "OpenAI Chat Completions compatible",
            "native tools",
            "durable SQLite sessions",
        ),
        instruction_files=("AGENTS.md", ".codex/skills/*/SKILL.md"),
        skill_roots=(".codex/skills",),
        model_policy=(
            "Use an explicitly configured Responses or Chat Completions provider route. "
            "External CLIs stay delegated harnesses and are not presented as Neyvia providers."
        ),
        docs_url="",
        capabilities=(
            ("agent_loop", "Native bounded model loop", "native"),
            ("sessions", "Durable resumable sessions", "native"),
            ("tool_search", "Progressive native and managed tool search", "native"),
            ("tools", "Schema and policy checked tool execution", "native"),
            ("subagents", "Planner and verifier specialists", "native"),
            ("proof", "Durable run and tool receipts", "native"),
            ("approvals", "Read-only default and mutation grants", "native"),
        ),
    ),
    HarnessSpec(
        harness_id="fluxio-hybrid",
        label="Neyvia Hybrid",
        execution_adapter="hermes",
        command_name="hermes",
        default_model="route-selected",
        description="Neyvia supervises routed lanes, approvals, proof, and recovery across installed harnesses.",
        accent="#70e1b2",
        transports=("native orchestration", "runtime lanes", "mission receipts"),
        instruction_files=("AGENTS.md", ".codex/skills/*/SKILL.md"),
        skill_roots=(".codex/skills",),
        model_policy="Route each role independently through workspace policy.",
        docs_url="",
        capabilities=(
            ("orchestration", "Multi-harness orchestration", "native"),
            ("queue", "Supervised queue and receipts", "native"),
            ("routing", "Per-role model routing", "native"),
            ("proof", "Browser and artifact proof", "native"),
            ("instructions", "AGENTS.md and skills", "native"),
        ),
    ),
    HarnessSpec(
        harness_id="hermes",
        label="Hermes",
        execution_adapter="hermes",
        command_name="hermes",
        default_model="provider-selected",
        description="Hermes sessions, tools, skills and delegation through its installed CLI. Dataset training exports remain owned by Hermes's separate batch runner.",
        accent="#d5b58a",
        transports=("CLI", "runtime events"),
        instruction_files=("AGENTS.md",),
        skill_roots=(".hermes/skills",),
        model_policy="Use the selected Hermes provider and model without substituting another route.",
        docs_url="https://hermes-agent.nousresearch.com/docs/",
        capabilities=(
            ("sessions", "Resumable sessions", "native"),
            ("tools", "Tools and skills", "native"),
            ("delegation", "Isolated subagents", "native"),
            ("dataset_export", "Training trajectories via Hermes batch runner", "external"),
        ),
    ),
    HarnessSpec(
        harness_id="openclaw",
        label="OpenClaw",
        execution_adapter="openclaw",
        command_name="openclaw",
        default_model="provider-selected",
        description="OpenClaw's installed runtime and gateway, with managed skills and remote-control integrations.",
        accent="#ff9c8c",
        transports=("CLI", "gateway events"),
        instruction_files=("AGENTS.md",),
        skill_roots=(".openclaw/skills",),
        model_policy="Use the explicitly configured OpenClaw provider route.",
        docs_url="https://docs.openclaw.ai/",
        capabilities=(
            ("tools", "Managed tools and skills", "native"),
            ("gateway", "Gateway sessions", "native"),
            ("remote", "Remote control bridge", "native"),
        ),
    ),
    HarnessSpec(
        harness_id="codex",
        label="Codex CLI",
        execution_adapter="codex",
        command_name="codex",
        default_model="gpt-5.6-sol",
        description="OpenAI coding harness with non-interactive JSONL, resumable sessions, skills, AGENTS.md, and MCP.",
        accent="#81a9ff",
        transports=("exec JSONL", "resume", "MCP server"),
        instruction_files=("AGENTS.md", ".codex/skills/*/SKILL.md"),
        skill_roots=(".codex/skills",),
        model_policy="OpenAI models and configured Codex providers.",
        docs_url="https://developers.openai.com/codex/cli/reference/",
        capabilities=(
            ("headless_json", "Headless JSONL", "native"),
            ("sessions", "Resumable sessions", "native"),
            ("tools", "Shell and file tools", "native"),
            ("subagents", "Agent delegation", "native"),
            ("mcp", "MCP client and server", "native"),
            ("skills", "Skills and AGENTS.md", "native"),
        ),
    ),
    HarnessSpec(
        harness_id="claude-code",
        label="Claude Code",
        execution_adapter="claude-code",
        command_name="claude",
        default_model="sonnet",
        description="Anthropic coding harness with stream JSON, sessions, tools, hooks, MCP, skills, and subagents.",
        accent="#dc9d70",
        transports=("stream JSON", "session resume", "MCP"),
        instruction_files=("CLAUDE.md", "CLAUDE.local.md", ".claude/rules/*.md"),
        skill_roots=(".claude/skills",),
        model_policy=(
            "Claude models through Anthropic-supported login, API, Bedrock, Vertex, "
            "or an operator-owned Anthropic Messages API gateway. Other models are "
            "available only through the explicit loopback CLIProxyAPI profile."
        ),
        docs_url="https://code.claude.com/docs/en/cli-usage",
        capabilities=(
            ("headless_json", "Headless stream JSON", "native"),
            ("sessions", "Persistent and resumed sessions", "native"),
            ("tools", "Tools and permission modes", "native"),
            ("subagents", "Native subagents", "native"),
            ("mcp", "MCP servers", "native"),
            ("hooks", "Hooks and skills", "native"),
            ("gateway", "LLM gateway configuration", "experimental"),
            ("cliproxy", "Explicit CLIProxyAPI model route", "experimental"),
        ),
    ),
    HarnessSpec(
        harness_id="grok-build",
        label="Grok Build",
        execution_adapter="grok-build",
        command_name="grok",
        default_model="grok-4.5",
        description=(
            "xAI coding harness with TUI, headless streaming JSON, ACP, sessions, worktrees, "
            "skills, plugins, and OpenAI-compatible custom models (API key / local proxy)."
        ),
        accent="#f0d671",
        transports=("streaming JSON", "ACP", "interactive TUI"),
        instruction_files=("AGENTS.md", ".grok/rules/*.md"),
        skill_roots=(".grok/skills",),
        model_policy=(
            "Built-in xAI routes plus documented custom models via GROK_MODELS_BASE_URL / "
            "config.toml aliases — prefer XAI_API_KEY or a local OpenAI-compatible proxy over device login."
        ),
        docs_url="https://docs.x.ai/build/cli/reference",
        capabilities=(
            ("headless_json", "Headless streaming JSON", "native"),
            ("sessions", "Sessions and dashboard", "native"),
            ("tools", "Shell and file tools", "native"),
            ("subagents", "Native subagents", "native"),
            ("acp", "ACP transport", "native"),
            ("worktrees", "Worktree isolation", "native"),
            ("skills", "Skills and plugins", "native"),
            ("custom_models", "Custom models and aliases", "native"),
            ("gateway", "OpenAI-compatible / CLIProxy-style base URL", "native"),
        ),
    ),
    HarnessSpec(
        harness_id="kimi-code",
        label="Kimi Code",
        execution_adapter="kimi-code",
        command_name="kimi",
        default_model="k3",
        description="Moonshot coding harness exposed through its documented stream-JSON and ACP interfaces.",
        accent="#c2a2ff",
        transports=("stream JSON", "ACP", "interactive CLI"),
        instruction_files=("AGENTS.md",),
        skill_roots=(".codex/skills",),
        model_policy=(
            "Use k3-256k for routine bounded work and k3 for deep work. Kimi "
            "Code aliases stay separate from direct API and OpenCode Go model IDs."
        ),
        docs_url="https://www.kimi.com/code/docs/en/kimi-code/models.html",
        capabilities=(
            ("headless_json", "Headless stream JSON", "native"),
            ("tools", "Shell and file tools", "native"),
            ("acp", "ACP transport", "native"),
            ("instructions", "Project instructions", "native"),
            ("task_lanes", "Routine and deep model lanes", "native"),
        ),
    ),
    HarnessSpec(
        harness_id="opencode",
        label="OpenCode",
        execution_adapter="opencode",
        command_name="opencode",
        default_model="provider-selected",
        description="Provider-flexible coding harness with local tools and NEYVIA-normalized runtime events.",
        accent="#69d6df",
        transports=("CLI", "structured events"),
        instruction_files=("AGENTS.md",),
        skill_roots=(".codex/skills",),
        model_policy="Select any provider/model route supported by the installed OpenCode configuration.",
        docs_url="https://opencode.ai/docs/",
        capabilities=(
            ("tools", "Shell and file tools", "native"),
            ("sessions", "Interactive sessions", "native"),
            ("providers", "Multiple model providers", "native"),
            ("instructions", "Project instructions", "native"),
        ),
    ),
    HarnessSpec(
        harness_id="cursor",
        label="Cursor Agent",
        execution_adapter="cursor",
        command_name="cursor-agent",
        default_model="auto",
        description="Cursor command-line agent supervised by Neyvia with workspace-scoped execution receipts.",
        accent="#ff8fb5",
        transports=("CLI", "structured events"),
        instruction_files=("AGENTS.md", ".cursor/rules/*.mdc"),
        skill_roots=(".cursor/skills",),
        model_policy="Models exposed by the authenticated Cursor installation.",
        docs_url="https://docs.cursor.com/en/cli/overview",
        capabilities=(
            ("tools", "Shell and file tools", "native"),
            ("sessions", "Agent sessions", "native"),
            ("rules", "Project rules", "native"),
        ),
    ),
    HarnessSpec(
        harness_id="prime-agent",
        label="Prime Agent",
        execution_adapter="prime-agent",
        command_name="prime-agent",
        default_model="provider-selected",
        description=(
            "Prime Intellect's terminal agent with strict JSONL output, persistent "
            "IPython, recursive subagents, durable goals, and bounded autonomous runs."
        ),
        accent="#8ea2ff",
        transports=("JSONL", "ACP", "persistent sessions"),
        instruction_files=("AGENTS.md",),
        skill_roots=(".agents/skills",),
        model_policy="Select a model supported by the operator's authenticated Prime Agent providers.",
        docs_url="https://github.com/PrimeIntellect-ai/prime-agent",
        capabilities=(
            ("headless_json", "Strict headless JSONL", "native"),
            ("sessions", "Persistent and retained sessions", "native"),
            ("tools", "Persistent IPython tool runtime", "native"),
            ("subagents", "Recursive subagents", "native"),
            ("goals", "Goals, heartbeats, and schedules", "native"),
            ("skills", "AGENTS.md and shared agent skills", "native"),
            ("autonomy", "Bounded autonomous mode", "native"),
        ),
        license_id="MIT",
        headless_transport="jsonl",
    ),
    HarnessSpec(
        harness_id="pi",
        label="Pi",
        execution_adapter="pi",
        command_name="pi",
        default_model="provider-selected",
        description=(
            "A small composable coding agent with four core tools, JSONL and RPC "
            "interfaces, tree-structured sessions, skills, and broad provider support."
        ),
        accent="#f2b86b",
        transports=("JSONL", "RPC", "TypeScript SDK"),
        instruction_files=("AGENTS.md",),
        skill_roots=(".agents/skills",),
        model_policy=(
            "Select an authenticated Pi provider/model, including OpenCode Go when its login is available."
        ),
        docs_url="https://github.com/earendil-works/pi/tree/main/packages/coding-agent",
        capabilities=(
            ("headless_json", "Headless JSONL", "native"),
            ("rpc", "Strict RPC control", "native"),
            ("sessions", "Tree-structured sessions", "native"),
            ("tools", "Read, write, edit, and bash tools", "native"),
            ("skills", "AGENTS.md and shared agent skills", "native"),
            ("providers", "Multiple providers including OpenCode Go", "native"),
            ("sandbox", "Host isolation required", "supervised"),
        ),
        license_id="MIT",
        headless_transport="jsonl",
    ),
    HarnessSpec(
        harness_id="deepseek-harness",
        label="DeepSeek Harness",
        execution_adapter="deepseek-harness",
        command_name="dsh",
        default_model="provider-selected",
        description=(
            "DeepSeek's developer-preview Cordis harness with pluggable models, tools, "
            "sessions, sandbox, agent loop, UI, and append-only traces."
        ),
        accent="#6b90ff",
        transports=("headless text", "durable session log", "Cordis plugins"),
        instruction_files=("AGENTS.md",),
        skill_roots=(".agents/skills",),
        model_policy="Use the model configured in the selected DeepSeek Harness profile.",
        docs_url="https://www.deepseek.com/harness/en/",
        capabilities=(
            ("headless_log", "Headless text plus session log", "native"),
            ("sessions", "Append-only trace and sessions", "native"),
            ("tools", "Profile-selected tool plugins", "native"),
            ("plugins", "Cordis plugin architecture", "native"),
            ("modes", "Standard, Code, Minimal, and Creator modes", "native"),
            ("sdk", "Python SDK", "platform-limited"),
        ),
        license_id="MIT",
        integration_tier="developer-preview",
        headless_transport="text-plus-session-log",
    ),
    HarnessSpec(
        harness_id="gptme",
        label="gptme",
        execution_adapter="gptme",
        command_name="gptme",
        default_model="provider-selected",
        description=(
            "A local-first, provider-agnostic agent with JSONL output, persistent "
            "conversations, shell and Python tools, MCP, ACP, and reusable lessons."
        ),
        accent="#77d8ae",
        transports=("JSONL", "MCP", "ACP"),
        instruction_files=("AGENTS.md",),
        skill_roots=(".agents/skills",),
        model_policy="Select a model configured through gptme's supported providers.",
        docs_url="https://gptme.org/docs/usage.html",
        capabilities=(
            ("headless_json", "Non-interactive JSONL", "native"),
            ("sessions", "Persistent conversations", "native"),
            ("tools", "Shell, Python, web, and vision tools", "native"),
            ("mcp", "MCP support", "native"),
            ("acp", "ACP support", "native"),
            ("lessons", "Reusable lessons", "native"),
        ),
        license_id="MIT",
        headless_transport="jsonl",
    ),
    HarnessSpec(
        harness_id="rook",
        label="Rook",
        execution_adapter="rook",
        command_name="rook",
        default_model="provider-selected",
        description=(
            "A durable autonomous security-audit harness that runs reviewed objective files, "
            "records sessions and evidence, and stays bounded by explicit rules of engagement."
        ),
        accent="#ff8d70",
        transports=("streamed text", "durable sessions", "objective ledger"),
        instruction_files=("AGENTS.md",),
        skill_roots=(".agents/skills",),
        model_policy=(
            "Use an operator-configured provider only inside an explicitly authorized audit scope."
        ),
        docs_url="https://github.com/pdparchitect/rook",
        capabilities=(
            ("headless_log", "Verbose text plus durable session log", "native"),
            ("objectives", "Reviewable objective and success criteria", "native"),
            ("sessions", "Resumable session records", "native"),
            ("ledger", "Evidence-backed completion ledger", "native"),
            ("tools", "File, shell, and security skill tools", "native"),
            ("direct_chat", "Direct chat", "blocked"),
        ),
        license_id="MIT",
        integration_tier="external-security",
        headless_transport="text-plus-session-log",
        security_only=True,
    ),
    HarnessSpec(
        harness_id="wallbreaker",
        label="Wallbreaker",
        execution_adapter="wallbreaker",
        command_name="wallbreaker",
        default_model="profile-selected",
        description=(
            "An external red-team campaign harness for authorized, controlled model "
            "security evaluation with attacker, target, and judge profiles."
        ),
        accent="#ff7b6b",
        transports=("streamed text", "durable run log", "campaign reports"),
        instruction_files=("AGENTS.md",),
        skill_roots=(".agents/skills",),
        model_policy=(
            "Use only explicitly authorized attacker, target, and judge profiles inside a bounded campaign."
        ),
        docs_url="https://github.com/JailbrokenAI/wallbreaker",
        capabilities=(
            ("headless_log", "Text stream plus run log", "native"),
            ("campaigns", "Bounded multi-round campaigns", "native"),
            ("profiles", "Attacker, target, and judge profiles", "native"),
            ("reports", "Durable reports and baselines", "native"),
            ("direct_chat", "Direct chat", "blocked"),
        ),
        license_id="AGPL-3.0",
        integration_tier="external-security",
        headless_transport="text-plus-run-log",
        security_only=True,
    ),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(value: object, fallback: str = "profile") -> str:
    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip()).strip(".-")
    return (clean[:80] or fallback).lower()


def _load_profiles(root: Path) -> dict[str, Any]:
    path = root / HARNESS_PROFILE_RELATIVE_PATH
    if not path.exists():
        return {"schema": "fluxio.harness_profiles.v1", "profiles": [], "updatedAt": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return {"schema": "fluxio.harness_profiles.v1", "profiles": [], "updatedAt": None}
    except json.JSONDecodeError as exc:
        backup = path.with_name(
            f"{path.name}.corrupt.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.{secrets.token_hex(3)}"
        )
        try:
            shutil.copy2(path, backup)
        except OSError:
            backup = Path()
        return {
            "schema": "fluxio.harness_profiles.v1",
            "profiles": [],
            "updatedAt": None,
            "recoveryWarning": (
                f"The profile store was invalid JSON at line {exc.lineno}. "
                f"A recovery copy was preserved at {backup}."
            ),
        }
    if not isinstance(payload, dict) or not isinstance(payload.get("profiles"), list):
        return {"schema": "fluxio.harness_profiles.v1", "profiles": [], "updatedAt": None}
    return payload


@contextmanager
def _profile_store_lock(root: Path) -> Iterator[None]:
    from .harness_jobs import _exclusive_job_lock

    path = root / HARNESS_PROFILE_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    # Reuse the persistent OS guard and crash-safe compatibility fence. Windows
    # can report access denied during an O_EXCL/delete race; contenders must
    # serialize before opening the compatibility marker, never age-steal it.
    with _exclusive_job_lock(path, timeout_seconds=10):
        yield


def resolve_harness_profile(
    root: Path,
    harness_id: str,
    profile_id: str = "",
) -> dict[str, Any] | None:
    """Return a stored profile row (never includes secrets)."""
    profiles = [row for row in _load_profiles(root.resolve()).get("profiles", []) if isinstance(row, dict)]
    matching = [row for row in profiles if str(row.get("harnessId") or "").strip().lower() == harness_id]
    if not matching:
        return None
    if profile_id:
        return next((row for row in matching if row.get("id") == profile_id), None)
    return matching[-1]


def save_harness_profile(root: Path, raw_profile: dict[str, Any]) -> dict[str, Any]:
    root = root.resolve()
    harness_id = str(raw_profile.get("harnessId") or "").strip().lower()
    if harness_id not in {spec.harness_id for spec in HARNESS_SPECS}:
        raise ValueError(f"Unsupported harness profile target: {harness_id or 'missing'}")
    profile = {key: str(raw_profile.get(key) or "").strip() for key in PROFILE_FIELDS}
    profile["id"] = _safe_id(profile.get("id") or f"{harness_id}-default")
    profile["harnessId"] = harness_id
    profile["label"] = profile.get("label") or f"{harness_id} profile"
    mode = str(profile.get("compatibilityMode") or "").strip().lower()
    if mode and mode not in COMPAT_MODES:
        raise ValueError(
            "compatibilityMode must be one of: native, xai-native, api-key, "
            "openai-compatible, anthropic-gateway, cliproxy, local-proxy."
        )
    profile["compatibilityMode"] = mode
    if profile.get("credentialEnv") and not re.fullmatch(r"[A-Z][A-Z0-9_]{2,80}", profile["credentialEnv"]):
        raise ValueError("Credential environment variable must use an uppercase environment-variable name.")
    if profile.get("baseUrl") and not re.match(r"^https?://[^\s]+$", profile["baseUrl"]):
        raise ValueError("Gateway base URL must be an http(s) URL.")
    if len(profile.get("model", "")) > 180 or len(profile.get("smallModel", "")) > 180:
        raise ValueError("Model identifiers must be 180 characters or fewer.")
    profile["updatedAt"] = _utc_now()
    from .proofs_b_harness import check_profile
    check_profile(profile)
    with _profile_store_lock(root):
        store = _load_profiles(root)
        rows = [
            row
            for row in store.get("profiles", [])
            if isinstance(row, dict) and row.get("id") != profile["id"]
        ]
        rows.append(profile)
        if len(rows) > MAX_PROFILE_COUNT:
            raise ValueError(f"At most {MAX_PROFILE_COUNT} harness profiles can be stored.")
        payload = {
            "schema": "fluxio.harness_profiles.v1",
            "profiles": rows,
            "updatedAt": profile["updatedAt"],
        }
        path = root / HARNESS_PROFILE_RELATIVE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(path)
    return profile


def _instruction_candidates(root: Path) -> list[Path]:
    candidates = [root / "AGENTS.md", root / "CLAUDE.md", root / "CLAUDE.local.md"]
    for pattern in (".claude/rules/*.md", ".grok/rules/*.md", ".cursor/rules/*.mdc"):
        candidates.extend(root.glob(pattern))
    return candidates


def _skill_candidates(root: Path) -> list[Path]:
    rows: list[Path] = []
    for directory in (".codex/skills", ".claude/skills", ".grok/skills", ".cursor/skills"):
        rows.extend((root / directory).glob("*/SKILL.md"))
    return rows


def discover_harness_context(root: Path) -> dict[str, Any]:
    root = root.resolve()
    instructions: list[dict[str, Any]] = []
    for path in sorted({candidate.resolve() for candidate in _instruction_candidates(root) if candidate.is_file()}):
        try:
            path.relative_to(root)
            content = path.read_text(encoding="utf-8", errors="replace")
            stat = path.stat()
        except (OSError, ValueError):
            continue
        instructions.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": stat.st_size,
                "lines": content.count("\n") + 1,
                "modifiedAt": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "preview": " ".join(content.split())[:220],
            }
        )
    skills: list[dict[str, Any]] = []
    for path in sorted({candidate.resolve() for candidate in _skill_candidates(root) if candidate.is_file()}):
        try:
            relative = path.relative_to(root)
            content = path.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue
        name_match = re.search(r"(?m)^name:\s*(.+)$", content)
        skills.append(
            {
                "path": relative.as_posix(),
                "name": (name_match.group(1).strip().strip('"\'') if name_match else path.parent.name),
                "bytes": path.stat().st_size,
            }
        )
    return {
        "workspace": str(root),
        "instructions": instructions,
        "skills": skills,
        "instructionCount": len(instructions),
        "skillCount": len(skills),
    }


def _validate_instruction_path(root: Path, relative_path: str) -> Path:
    relative = Path(str(relative_path or "").replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Instruction path must remain inside the selected workspace.")
    posix = relative.as_posix()
    allowed = (
        posix in {"AGENTS.md", "CLAUDE.md", "CLAUDE.local.md"}
        or bool(re.fullmatch(r"\.(?:claude|grok)/rules/[A-Za-z0-9_.-]+\.md", posix))
        or bool(re.fullmatch(r"\.cursor/rules/[A-Za-z0-9_.-]+\.mdc", posix))
    )
    if not allowed:
        raise ValueError("Only AGENTS.md, CLAUDE.md, CLAUDE.local.md, and supported rules files can be edited here.")
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("Instruction path escaped the workspace boundary.") from exc
    return target


def save_harness_instruction(root: Path, relative_path: str, content: str) -> dict[str, Any]:
    root = root.resolve()
    encoded = str(content or "").encode("utf-8")
    if len(encoded) > MAX_INSTRUCTION_BYTES:
        raise ValueError(f"Instruction file exceeds {MAX_INSTRUCTION_BYTES} bytes.")
    target = _validate_instruction_path(root, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    from .harness_jobs import _exclusive_job_lock
    # The backup, replacement and contract readback must observe one target
    # generation, including when separate processes save the same instruction.
    with _exclusive_job_lock(target, timeout_seconds=120):
        return _save_harness_instruction_locked(root, target, encoded)


def _save_harness_instruction_locked(root: Path, target: Path, encoded: bytes) -> dict[str, Any]:
    backup_path = ""
    previous = target.read_bytes() if target.exists() else None
    if target.exists():
        backup = target.with_name(
            f"{target.name}.bak.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.{secrets.token_hex(3)}"
        )
        shutil.copy2(target, backup)
        backup_path = str(backup)
    tmp = target.with_name(f"{target.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}")
    tmp.write_bytes(encoded.rstrip() + b"\n")
    tmp.replace(target)
    receipt = {
        "ok": True,
        "path": str(target),
        "relativePath": target.relative_to(root).as_posix(),
        "backupPath": backup_path,
        "bytes": target.stat().st_size,
        "savedAt": _utc_now(),
    }
    from .proofs_b_harness import check_instruction
    check_instruction(root, target, receipt, encoded, previous)
    return receipt


def read_harness_instruction(root: Path, relative_path: str) -> dict[str, Any]:
    root = root.resolve()
    target = _validate_instruction_path(root, relative_path)
    content = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
    return {
        "path": str(target),
        "relativePath": target.relative_to(root).as_posix(),
        "exists": target.exists(),
        "content": content,
        "bytes": len(content.encode("utf-8")),
    }


def _resolve_credential(
    profile: dict[str, Any],
    source_env: dict[str, str] | None,
) -> tuple[str, str]:
    credential_name = str(profile.get("credentialEnv") or "").strip()
    if not credential_name:
        return "", ""
    value = str((source_env or {}).get(credential_name) or os.environ.get(credential_name) or "").strip()
    return credential_name, value


def harness_gateway_environment(
    root: Path,
    harness_id: str,
    profile_id: str = "",
    source_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build child-process env for supported provider authentication.

    Profiles never store secrets — only env var *names* and public base URLs.
    Claude keeps official Anthropic authentication separate from an explicitly
    selected, loopback-only CLIProxyAPI compatibility route.
    Grok may use its documented GROK_MODELS_BASE_URL + XAI_API_KEY overlay.
    """

    profile = resolve_harness_profile(root, harness_id, profile_id)
    if not profile:
        return {}
    env: dict[str, str] = {}
    mode = str(profile.get("compatibilityMode") or "").strip().lower()
    credential_name, credential_value = _resolve_credential(profile, source_env)

    if harness_id == "neyvia-agent":
        if profile.get("baseUrl"):
            env["OPENAI_BASE_URL"] = str(profile["baseUrl"]).rstrip("/")
        if credential_value:
            env["OPENAI_API_KEY"] = credential_value
            if credential_name and credential_name != "OPENAI_API_KEY":
                env[credential_name] = credential_value
        if profile.get("model"):
            env["FLUXIO_HARNESS_MODEL"] = str(profile["model"])

    elif harness_id == "claude-code":
        if mode in {"local-proxy", "openai-compatible"}:
            raise ValueError(
                "Claude Code requires an Anthropic Messages-compatible route. Use official "
                "Claude login, Anthropic API key, Bedrock, Vertex, an approved Anthropic "
                "gateway, or the explicit CLIProxyAPI compatibility mode."
            )
        if mode not in {
            "",
            "native",
            "api-key",
            "anthropic-gateway",
            "enterprise-gateway",
            "aws-bedrock",
            "google-vertex",
            "cliproxy",
        }:
            raise ValueError(f"Unsupported Claude Code compatibility mode: {mode}")
        if mode == "aws-bedrock":
            env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        if mode == "google-vertex":
            env["CLAUDE_CODE_USE_VERTEX"] = "1"
        base_url = str(profile.get("baseUrl") or "").strip().rstrip("/")
        if mode == "cliproxy":
            base_url = base_url or "http://127.0.0.1:8317"
            parsed = urlparse(base_url)
            if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError(
                    "The managed CLIProxyAPI route must use a loopback-only http:// URL."
                )
            if not credential_value:
                raise ValueError(
                    "CLIProxyAPI is selected, but its private client credential is unavailable."
                )
            env["ANTHROPIC_BASE_URL"] = base_url
            env["ANTHROPIC_AUTH_TOKEN"] = credential_value
            env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] = "1"
        elif base_url:
            if mode not in {"anthropic-gateway", "enterprise-gateway"}:
                raise ValueError(
                    "A custom Claude base URL requires the anthropic-gateway or "
                    "enterprise-gateway compatibility mode."
                )
            env["ANTHROPIC_BASE_URL"] = base_url
        if profile.get("model"):
            env["ANTHROPIC_MODEL"] = str(profile["model"])
            env["FLUXIO_HARNESS_MODEL"] = str(profile["model"])
        if profile.get("smallModel"):
            env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = str(profile["smallModel"])
        if credential_value:
            credential_target = (
                "ANTHROPIC_API_KEY"
                if str(profile.get("credentialKind") or "").strip().lower() == "api-key"
                else "ANTHROPIC_AUTH_TOKEN"
            )
            env[credential_target] = credential_value
            if credential_name and credential_name != credential_target:
                env[credential_name] = credential_value
        if mode:
            env["FLUXIO_HARNESS_COMPAT"] = mode

    elif harness_id == "grok-build":
        base_url = str(profile.get("baseUrl") or "").strip().rstrip("/")
        if base_url:
            # Documented xAI open surface for OpenAI-compatible / corporate gateways.
            env["GROK_MODELS_BASE_URL"] = base_url
            if mode in {"cliproxy", "local-proxy", "openai-compatible"}:
                env["FLUXIO_HARNESS_COMPAT"] = mode or "openai-compatible"
        if credential_value:
            # Prefer documented XAI_API_KEY; also mirror source name for env_key configs.
            env["XAI_API_KEY"] = credential_value
            if credential_name and credential_name not in {"XAI_API_KEY", "GROK_CODE_XAI_API_KEY"}:
                env[credential_name] = credential_value
        elif mode in {"api-key", "xai-native", "native", ""} and not base_url:
            # No profile credential — leave ambient XAI_API_KEY alone (do not clear).
            pass
        if profile.get("model"):
            env["FLUXIO_HARNESS_MODEL"] = str(profile["model"])

    elif harness_id == "kimi-code":
        model = str(profile.get("model") or "").strip()
        small_model = str(profile.get("smallModel") or "").strip()
        if credential_value and mode != "cliproxy":
            env[credential_name or "KIMI_API_KEY"] = credential_value
        if profile.get("baseUrl"):
            env["FLUXIO_HARNESS_BASE_URL"] = str(profile["baseUrl"]).rstrip("/")
        if model:
            env["FLUXIO_HARNESS_MODEL"] = model
        if small_model:
            env["FLUXIO_HARNESS_SMALL_MODEL"] = small_model
        if credential_value and profile.get("baseUrl") and model:
            # Kimi's documented KIMI_MODEL_* family creates an ephemeral provider
            # in memory. Nothing is written to config.toml or a credential store.
            env["KIMI_MODEL_NAME"] = model
            env["KIMI_MODEL_API_KEY"] = credential_value
            env["KIMI_MODEL_BASE_URL"] = str(profile["baseUrl"]).rstrip("/")
            env["KIMI_MODEL_PROVIDER_TYPE"] = (
                "openai"
                if mode in {"openai-compatible", "local-proxy", "cliproxy"}
                else "kimi"
            )
            if model == "k3":
                env["KIMI_MODEL_MAX_CONTEXT_SIZE"] = "1048576"
            elif model in {
                "k3-256k",
                "kimi-for-coding",
                "kimi-for-coding-highspeed",
            }:
                env["KIMI_MODEL_MAX_CONTEXT_SIZE"] = "262144"

    elif harness_id == "deepseek-harness":
        if credential_value:
            env["DEEPSEEK_API_KEY"] = credential_value
            if credential_name and credential_name != "DEEPSEEK_API_KEY":
                env[credential_name] = credential_value
        if profile.get("model"):
            env["FLUXIO_HARNESS_MODEL"] = str(profile["model"])

    elif harness_id == "rook":
        if credential_value:
            env[credential_name] = credential_value
            provider_by_env = {
                "ZAI_API_KEY": "zai",
                "OPENAI_API_KEY": "openai",
                "ANTHROPIC_API_KEY": "anthropic",
                "GROQ_API_KEY": "groq",
                "MISTRAL_API_KEY": "mistral",
                "DEEPSEEK_API_KEY": "deepseek",
                "OPENROUTER_API_KEY": "openrouter",
                "TOGETHER_API_KEY": "together",
                "CEREBRAS_API_KEY": "cerebras",
                "XAI_API_KEY": "xai",
                "MOONSHOT_API_KEY": "moonshot",
                "DASHSCOPE_API_KEY": "qwen",
            }
            if credential_name in provider_by_env:
                env["ROOK_DEFAULT_PROVIDER"] = provider_by_env[credential_name]
        if profile.get("model"):
            env["FLUXIO_HARNESS_MODEL"] = str(profile["model"])

    if mode:
        env.setdefault("FLUXIO_HARNESS_COMPAT", mode)
    if profile.get("id"):
        env["FLUXIO_HARNESS_PROFILE"] = str(profile["id"])
    from .proofs_b_harness import check_gateway
    check_gateway(harness_id, profile, credential_name, credential_value, env)
    return env


def merge_harness_launch_env(
    root: Path,
    harness_id: str,
    *,
    profile_id: str = "",
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Merge runtime env with a harness profile gateway overlay."""
    env = dict(base_env or os.environ)
    env.update(harness_gateway_environment(root, harness_id, profile_id, env))
    return env


def _probe_harness_command(
    command: str,
    root: Path,
    harness_id: str = "",
) -> tuple[bool, str, str]:
    """Prove that a discovered CLI is executable, not merely present on PATH."""

    if harness_id == "neyvia-agent" and Path(command).is_file():
        # The native harness is part of the running Neyvia release. Starting a
        # second Python interpreter merely to import the same lightweight
        # version module can exceed the NAS cold-disk budget and previously
        # produced a false "blocked" state. Launcher presence plus the version
        # already loaded by this backend is the catalog proof; an Inspect or
        # real job remains the execution proof.
        from .neyvia_version import NEYVIA_AGENT_VERSION

        return True, f"Neyvia Agent {NEYVIA_AGENT_VERSION}", ""

    # Wallbreaker's public CLI currently exposes ``--help`` but no
    # ``--version`` switch. Treating that standards-compliant install as
    # broken made the catalogue lie after a successful isolated install.
    probe_switch = "--help" if harness_id == "wallbreaker" else "--version"
    args = [command, probe_switch]
    if os.name == "nt" and Path(command).suffix.lower() in {".bat", ".cmd"}:
        args = ["cmd", "/d", "/s", "/c", subprocess.list2cmdline(args)]
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(  # noqa: S603
            args,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=runtime_subprocess_env(root),
            **hidden_windows_subprocess_kwargs(new_process_group=True),
        )
        stdout, stderr = process.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        if process is not None and process.poll() is None:
            if os.name == "nt" and process.pid:
                subprocess.run(  # noqa: S603
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                    check=False,
                    **hidden_windows_subprocess_kwargs(),
                )
            else:
                process.kill()
        return False, "", "Version probe timed out after 3 seconds. Use Inspect to retry explicitly."
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "", f"{type(exc).__name__}: {exc}"
    output = " ".join((stdout or stderr or "").split())[:240]
    if process.returncode == 0:
        return True, output, ""
    return False, output, output or f"Version probe exited with {process.returncode}."


def _probe_kimi_provider_configuration(
    command: str,
    root: Path,
) -> tuple[bool | None, str]:
    """Inspect Kimi's safe provider summary without requesting raw config JSON."""

    args = [command, "provider", "list"]
    if os.name == "nt" and Path(command).suffix.lower() in {".bat", ".cmd"}:
        args = ["cmd", "/d", "/s", "/c", subprocess.list2cmdline(args)]
    try:
        completed = subprocess.run(
            args,
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
            env=runtime_subprocess_env(root),
            **hidden_windows_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"Kimi provider setup could not be inspected: {type(exc).__name__}."
    output = " ".join((completed.stdout or completed.stderr or "").split())[:300]
    if completed.returncode != 0:
        return None, output or "Kimi provider setup inspection failed."
    if not output or "no providers configured" in output.casefold():
        return False, "Kimi CLI is installed, but no provider is configured."
    return True, "Kimi has at least one configured provider. A live run still proves authentication."


def runtime_picker_choices() -> list[dict[str, Any]]:
    """Cheap canonical discovery: adapter support, never installation/auth proof."""
    return [
        {
            "value": spec.execution_adapter,
            "label": spec.label,
            "defaultModel": "" if spec.default_model in {"provider-selected", "route-selected", "profile-selected", "auto"} else spec.default_model,
            "securityOnly": spec.security_only,
            "discoveryOnly": True,
        }
        for spec in HARNESS_SPECS if spec.harness_id != "fluxio-hybrid"
    ]


def build_harness_catalog(
    root: Path,
    runtime_statuses: list[dict[str, Any]] | None = None,
    *,
    provider_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    effective_provider_env = {
        **os.environ,
        **dict(provider_env or {}),
    }
    status_by_id = {
        str(row.get("runtime_id") or row.get("runtimeId") or ""): row
        for row in (runtime_statuses or [])
        if isinstance(row, dict)
    }
    command_by_harness: dict[str, str] = {}
    probe_by_harness: dict[str, tuple[bool, str, str]] = {}
    for spec in HARNESS_SPECS:
        status = status_by_id.get(spec.execution_adapter, {})
        command_by_harness[spec.harness_id] = str(
            status.get("command")
            or runtime_which(spec.command_name, root)
            or shutil.which(spec.command_name)
            or ""
        )

    pending_probes = {
        spec.harness_id: command_by_harness[spec.harness_id]
        for spec in HARNESS_SPECS
        if spec.harness_id != "fluxio-hybrid"
        and command_by_harness[spec.harness_id]
        and not status_by_id.get(spec.execution_adapter)
    }
    kimi_provider_probe: tuple[bool | None, str] | None = None
    kimi_command = command_by_harness.get("kimi-code", "")
    if pending_probes or kimi_command:
        # Version checks are independent. Running them concurrently keeps the
        # first Harnesses paint bounded by the slowest CLI instead of the sum
        # of every optional runner's startup time.
        worker_count = min(8, len(pending_probes) + (1 if kimi_command else 0))
        with ThreadPoolExecutor(max_workers=max(1, worker_count)) as pool:
            futures = {
                pool.submit(
                    _probe_harness_command,
                    command,
                    root,
                    harness_id,
                ): ("version", harness_id)
                for harness_id, command in pending_probes.items()
            }
            if kimi_command:
                futures[pool.submit(
                    _probe_kimi_provider_configuration,
                    kimi_command,
                    root,
                )] = ("kimi-provider", "kimi-code")
            for future in as_completed(futures):
                kind, harness_id = futures[future]
                try:
                    if kind == "kimi-provider":
                        kimi_provider_probe = future.result()
                    else:
                        probe_by_harness[harness_id] = future.result()
                except Exception as exc:  # pragma: no cover - defensive worker isolation
                    if kind == "kimi-provider":
                        kimi_provider_probe = (
                            None,
                            f"Kimi provider setup could not be inspected: {type(exc).__name__}.",
                        )
                    else:
                        probe_by_harness[harness_id] = (
                            False,
                            "",
                            f"{type(exc).__name__}: {exc}",
                        )
    rows: list[dict[str, Any]] = []
    for spec in HARNESS_SPECS:
        status = status_by_id.get(spec.execution_adapter, {})
        command = command_by_harness[spec.harness_id]
        installed = spec.harness_id == "fluxio-hybrid" or bool(command)
        readiness_detail = ""
        probed_version = ""
        if spec.harness_id == "fluxio-hybrid":
            detected = True
        elif status:
            detected = bool(status.get("detected"))
            readiness_detail = " ".join(
                str(item) for item in status.get("issues", []) if str(item).strip()
            )[:500]
        elif command:
            detected, probed_version, readiness_detail = probe_by_harness.get(
                spec.harness_id,
                (False, "", "Runtime probe did not return a result."),
            )
        else:
            detected = False
        if spec.harness_id == "fluxio-hybrid":
            command = "fluxio-web-backend"
        provider_configured: bool | None = None
        provider_readiness = "not-applicable"
        if spec.harness_id in {"kimi-code", "deepseek-harness", "rook"} and detected:
            if spec.harness_id == "kimi-code":
                provider_configured, provider_detail = kimi_provider_probe or (
                    None,
                    "Kimi provider setup was not inspected.",
                )
            elif spec.harness_id == "deepseek-harness":
                provider_configured = bool(
                    str(effective_provider_env.get("DEEPSEEK_API_KEY") or "").strip()
                )
                provider_detail = (
                    "DeepSeek Harness has a credential route. A live run still proves authentication."
                    if provider_configured
                    else (
                        "DeepSeek Harness is installed, but its headless profile reported no "
                        "DeepSeek credential. Connect it in the DSH Models page or provide "
                        "DEEPSEEK_API_KEY through a secret-free Neyvia profile."
                    )
                )
            else:
                provider_configured = any(
                    str(effective_provider_env.get(name) or "").strip()
                    for name in (
                        "ZAI_API_KEY",
                        "OPENAI_API_KEY",
                        "ANTHROPIC_API_KEY",
                        "GROQ_API_KEY",
                        "MISTRAL_API_KEY",
                        "DEEPSEEK_API_KEY",
                        "OPENROUTER_API_KEY",
                        "TOGETHER_API_KEY",
                        "CEREBRAS_API_KEY",
                        "XAI_API_KEY",
                        "MOONSHOT_API_KEY",
                        "DASHSCOPE_API_KEY",
                    )
                )
                provider_detail = (
                    "Rook has an ambient provider credential. A live authorized run still proves the route."
                    if provider_configured
                    else (
                        "Rook v0.6.1 is installed and checksum-verified, but no supported provider "
                        "credential is connected. Add an exact provider key reference before launch."
                    )
                )
            profile = resolve_harness_profile(root, spec.harness_id)
            credential_name = str(
                (profile or {}).get("credentialEnv") or ""
            ).strip()
            ephemeral_profile_ready = bool(
                profile
                and credential_name
                and str(effective_provider_env.get(credential_name) or "").strip()
                and (
                    spec.harness_id in {"deepseek-harness", "rook"}
                    or (
                        str(profile.get("baseUrl") or "").strip()
                        and str(profile.get("model") or "").strip()
                    )
                )
            )
            if ephemeral_profile_ready:
                provider_configured = True
                provider_detail = (
                    "A Kimi ephemeral provider profile and runtime credential are configured. "
                    "A live run still proves the route."
                    if spec.harness_id == "kimi-code"
                    else (
                        f"A {spec.label} credential reference resolves at runtime. "
                        "A live run still proves the route."
                    )
                )
            provider_readiness = (
                "configured"
                if provider_configured is True
                else "setup-required"
                if provider_configured is False
                else "unverified"
            )
            if provider_detail:
                readiness_detail = provider_detail
        runner_readiness = (
            "ready"
            if detected
            else "blocked"
            if installed
            else "not-installed"
        )
        readiness = runner_readiness
        if spec.harness_id in {"kimi-code", "deepseek-harness", "rook"} and detected:
            readiness = (
                "provider-configured"
                if provider_configured is True
                else "provider-setup-required"
                if provider_configured is False
                else "provider-unverified"
            )
        row = asdict(spec)
        row.update(
            {
                "harnessId": spec.harness_id,
                "executionAdapter": spec.execution_adapter,
                "commandName": spec.command_name,
                "defaultModel": spec.default_model,
                "instructionFiles": list(spec.instruction_files),
                "skillRoots": list(spec.skill_roots),
                "licenseId": spec.license_id,
                "integrationTier": spec.integration_tier,
                "headlessTransport": spec.headless_transport,
                "securityOnly": spec.security_only,
                "detected": detected,
                "installed": installed,
                "command": command,
                "version": status.get("version") or probed_version,
                "readiness": readiness,
                "runnerReadiness": runner_readiness,
                "providerConfigured": provider_configured,
                "providerReadiness": provider_readiness,
                "readinessDetail": readiness_detail,
                "capabilities": [
                    {
                        "key": key,
                        "label": label,
                        "support": support,
                        "available": (
                            detected
                            and support == "native"
                            and provider_configured is not False
                        ),
                    }
                    for key, label, support in spec.capabilities
                ],
            }
        )
        for key in (
            "harness_id",
            "execution_adapter",
            "command_name",
            "default_model",
            "instruction_files",
            "skill_roots",
            "model_policy",
            "docs_url",
            "license_id",
            "integration_tier",
            "headless_transport",
            "security_only",
        ):
            row.pop(key, None)
        row["modelPolicy"] = spec.model_policy
        row["docsUrl"] = spec.docs_url
        rows.append(row)
    catalog = {
        "schema": "fluxio.harness_catalog.v1",
        "generatedAt": _utc_now(),
        "workspace": str(root),
        "harnesses": rows,
        "profiles": _load_profiles(root).get("profiles", []),
        "extensions": [
            {
                "id": "dsh-j-space",
                "hostHarnessId": "deepseek-harness",
                "label": "J-Space cognition",
                "description": (
                    "An on-demand DSH skill provider for disciplined long-horizon reasoning, "
                    "verification, and a workspace-owned task ledger. It adds no hidden model or tools."
                ),
                "licenseId": "Apache-2.0",
                "docsUrl": "https://github.com/Harzva/dsh-j-space",
                "sourceCommit": "d419a27002993c021db1552bac2e486d66731a02",
                "readiness": (
                    "installed"
                    if any(
                        (Path.home() / ".dsh" / "profiles").glob(
                            "*/node_modules/dsh-j-space/package.json"
                        )
                    )
                    else "host-not-installed"
                    if not any(
                        item.get("harnessId") == "deepseek-harness" and item.get("detected")
                        for item in rows
                    )
                    else "ready-to-install"
                ),
            }
        ],
        "context": discover_harness_context(root),
        "semantics": {
            "model": "Inference engine selected by a route.",
            "harness": "Agent environment that owns tools, sessions, rules, and native capabilities.",
            "orchestrator": "Neyvia schedules and supervises one or more harness executions.",
            "profile": (
                "Operator-owned gateway overlay: baseUrl + credentialEnv name + model alias. "
                "Secrets stay in the process environment; never in harness_profiles.json."
            ),
        },
        "openSurfaces": {
            "grok-build": {
                "auth": ["XAI_API_KEY", "GROK_CODE_XAI_API_KEY", "grok login --device-auth (operator-owned)"],
                "gateway": ["GROK_MODELS_BASE_URL", "~/.grok/config.toml [model.*]"],
                "transport": ["--output-format streaming-json", "grok agent stdio (ACP)"],
                "docs": "https://docs.x.ai/build/cli/reference",
            },
            "claude-code": {
                "auth": [
                    "Official Claude Code login (Claude subscription or Anthropic Console)",
                    "ANTHROPIC_API_KEY",
                    "Amazon Bedrock or Google Vertex AI",
                ],
                "gateway": [
                    "Operator-owned Anthropic Messages API gateway via ANTHROPIC_BASE_URL",
                ],
                "transport": [
                    "--output-format stream-json",
                    "bounded --max-turns",
                    "explicit --allowedTools",
                ],
                "docs": "docs/CLAUDE_CODE_COMPLIANCE.md",
            },
        },
    }
    from .proofs_b_harness import check_catalog
    check_catalog(catalog)
    return catalog

