from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

try:
    from .subprocess_utils import hidden_windows_subprocess_kwargs
except ImportError:  # pragma: no cover - direct script fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs


STRUCTURED_EVENT_PREFIX = "FLUXIO_EVENT:"
SUPPORTED_EXTERNAL_CLI_RUNTIMES = (
    "codex",
    "kimi-code",
    "claude-code",
    "grok-build",
    "prime-agent",
    "pi",
    "deepseek-harness",
    "gptme",
    "rook",
    "wallbreaker",
)
_KIMI_PERMISSION_HEADER = re.compile(
    r"^\s*\[\[\s*permission\.rules\s*\]\]\s*(?:#.*)?$",
    flags=re.IGNORECASE,
)
_TOML_TABLE_HEADER = re.compile(r"^\s*\[+[^\]]+\]+\s*(?:#.*)?$")
_KIMI_READ_ONLY_DENIED_TOOLS = (
    "Write",
    "Edit",
    "Bash",
    "Agent",
    "AgentSwarm",
    "Task",
    "TaskStop",
    "CronCreate",
    "CronDelete",
    "Skill",
)


def _merge_launch_env(
    *,
    runtime: str,
    workspace_root: str = "",
    harness_profile: str = "",
) -> dict[str, str]:
    """Overlay documented API-key / proxy env from a harness profile (no secrets on disk)."""
    env = os.environ.copy()
    root_text = str(workspace_root or "").strip()
    if not root_text:
        return env
    try:
        from .harness_registry import merge_harness_launch_env
    except ImportError:  # pragma: no cover - direct script fallback
        return env
    return merge_harness_launch_env(
        Path(root_text),
        str(runtime or "").strip().lower(),
        profile_id=str(harness_profile or "").strip(),
        base_env=env,
    )


def emit_event(
    *,
    kind: str,
    message: str,
    status: str = "running",
    data: dict[str, Any] | None = None,
) -> None:
    payload = {
        "kind": kind,
        "message": message,
        "status": status,
        "data": data or {},
    }
    print(f"{STRUCTURED_EVENT_PREFIX}{json.dumps(payload, ensure_ascii=True)}", flush=True)


def _compact(value: object, *, limit: int = 700) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _read_only_prompt(prompt: str) -> str:
    return (
        "This is a regular conversation turn. Inspect context when useful, but do not "
        "modify files, run state-changing commands, or start background work.\n\n"
        f"{prompt}"
    )


def _kimi_read_only_config(source: str) -> str:
    """Move existing permission rules behind NEYVIA's hard deny rules.

    Kimi evaluates permission rules from top to bottom. Its non-interactive
    prompt mode cannot be combined with Plan mode and otherwise uses automatic
    approvals, so Direct chat needs a dedicated temporary config.
    """

    lines = source.splitlines()
    kept: list[str] = []
    permission_blocks: list[list[str]] = []
    index = 0
    while index < len(lines):
        if not _KIMI_PERMISSION_HEADER.match(lines[index]):
            kept.append(lines[index])
            index += 1
            continue
        block = [lines[index]]
        index += 1
        while index < len(lines) and not _TOML_TABLE_HEADER.match(lines[index]):
            block.append(lines[index])
            index += 1
        permission_blocks.append(block)

    read_only_rules: list[str] = []
    for tool_name in _KIMI_READ_ONLY_DENIED_TOOLS:
        read_only_rules.extend(
            [
                "[[permission.rules]]",
                'decision = "deny"',
                'scope = "turn-override"',
                f'pattern = "{tool_name}"',
                'reason = "NEYVIA Direct chat is read-only."',
                "",
            ]
        )
    preserved_rules = [line for block in permission_blocks for line in [*block, ""]]
    return "\n".join([*kept, "", *read_only_rules, *preserved_rules]).rstrip() + "\n"


def _kimi_copy_ignore(directory: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if _is_link_like(Path(directory) / name)
        or name
        in {
            ".git",
            ".agent_control",
            ".codex",
            ".kimi-code",
            ".venv",
            "__pycache__",
            "dist",
            "node_modules",
            "output",
            "target",
        }
        or name.endswith((".key", ".pem", ".p12", ".pfx", ".tar", ".zip"))
        or (name.startswith(".env") and name != ".env.example")
    }


def _kimi_home_copy_ignore(directory: str, names: list[str]) -> set[str]:
    ignored = _kimi_copy_ignore(directory, names)
    ignored.update(
        name
        for name in names
        if name in {"logs", "sessions", "cache", "mcp.json"}
        or name.endswith(".log")
    )
    return ignored


def _is_link_like(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction and is_junction())
    except OSError:
        return True


def _prepare_kimi_read_only_runtime(
    *,
    workspace_root: str,
    child_env: dict[str, str],
) -> tuple[tempfile.TemporaryDirectory[str], tempfile.TemporaryDirectory[str], Path]:
    """Create an isolated source mirror and Kimi home for Direct chat."""

    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    if not workspace.is_dir():
        raise ValueError(f"Kimi Direct chat workspace is not a directory: {workspace}")

    workspace_temp = tempfile.TemporaryDirectory(prefix="neyvia-kimi-workspace-")
    mirror = Path(workspace_temp.name) / workspace.name
    shutil.copytree(
        workspace,
        mirror,
        symlinks=False,
        ignore=_kimi_copy_ignore,
    )

    home_temp = tempfile.TemporaryDirectory(prefix="neyvia-kimi-home-")
    isolated_home = Path(home_temp.name)
    source_home = Path(
        child_env.get("KIMI_CODE_HOME") or (Path.home() / ".kimi-code")
    ).expanduser()
    if source_home.is_dir():
        shutil.copytree(
            source_home,
            isolated_home,
            dirs_exist_ok=True,
            symlinks=False,
            ignore=_kimi_home_copy_ignore,
        )
    config_path = isolated_home / "config.toml"
    existing_config = (
        config_path.read_text(encoding="utf-8", errors="replace")
        if config_path.is_file()
        else ""
    )
    config_path.write_text(_kimi_read_only_config(existing_config), encoding="utf-8")
    try:
        os.chmod(isolated_home, 0o700)
        os.chmod(config_path, 0o600)
    except OSError:
        pass
    child_env["KIMI_CODE_HOME"] = str(isolated_home)
    child_env["KIMI_DISABLE_TELEMETRY"] = "1"
    return workspace_temp, home_temp, mirror


def _prepare_generic_read_only_runtime(
    workspace_root: str,
) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    """Mirror a workspace for CLIs that do not expose a native read-only sandbox."""

    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    if not workspace.is_dir():
        raise ValueError(f"Direct-chat workspace is not a directory: {workspace}")
    workspace_temp = tempfile.TemporaryDirectory(prefix="neyvia-harness-workspace-")
    mirror = Path(workspace_temp.name) / workspace.name
    shutil.copytree(
        workspace,
        mirror,
        symlinks=False,
        ignore=_kimi_copy_ignore,
    )
    return workspace_temp, mirror


def build_cli_args(
    *,
    runtime: str,
    command: str,
    prompt: str,
    model: str = "",
    effort: str = "",
    mode: str = "mission",
    permission_mode: str = "",
    session_id: str = "",
    system_prompt_file: str = "",
) -> list[str]:
    """Build only documented non-interactive CLI invocations.

    Fluxio deliberately keeps API model identifiers separate from CLI aliases.
    For example, Kimi Code accepts ``k3`` while Kimi's direct API accepts
    ``kimi-k3``; this bridge never rewrites one into the other.
    """

    runtime_id = str(runtime or "").strip().lower()
    if runtime_id not in SUPPORTED_EXTERNAL_CLI_RUNTIMES:
        raise ValueError(f"Unsupported external CLI runtime: {runtime}")
    if str(system_prompt_file or "").strip() and runtime_id != "claude-code":
        raise ValueError("A system prompt file is supported only by the Claude Code CLI adapter.")
    operation_mode = "chat" if str(mode or "").strip().lower() == "chat" else "mission"
    requested_permission = str(permission_mode or "").strip().lower()
    if requested_permission not in {"", "read-only", "workspace", "full-access"}:
        raise ValueError("permission_mode must be read-only, workspace, or full-access.")
    effective_prompt = _read_only_prompt(prompt) if operation_mode == "chat" else prompt
    normalized_effort = str(effort or "").strip().lower()

    if runtime_id == "kimi-code":
        args = [command]
        if model:
            args.extend(["--model", model])
        args.extend(["--print", "--prompt", effective_prompt, "--output-format", "stream-json"])
        return args

    if runtime_id == "codex":
        args = [
            command,
            "exec",
            "--json",
        ]
        if requested_permission == "full-access":
            args.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            sandbox = (
                "workspace-write" if requested_permission == "workspace"
                else "read-only" if requested_permission == "read-only"
                else "read-only" if operation_mode == "chat" else "workspace-write"
            )
            args.extend(["--sandbox", sandbox])
        if model:
            args.extend(["--model", model])
        args.append(effective_prompt)
        return args

    if runtime_id == "grok-build":
        args = [command, "--no-auto-update"]
        if model:
            args.extend(["--model", model])
        if session_id:
            args.extend(["--session-id", session_id])
        if operation_mode == "chat":
            args.extend(["--disallowed-tools", "Bash,Edit,Write"])
        args.extend(["--single", effective_prompt, "--output-format", "streaming-json"])
        return args

    if runtime_id == "prime-agent":
        args = [command, "--print", "--mode", "json", "--offline"]
        if model:
            args.extend(["--model", model])
        if normalized_effort in {"off", "minimal", "low", "medium", "high", "xhigh", "max"}:
            args.extend(["--thinking", normalized_effort])
        args.extend(["--", effective_prompt])
        return args

    if runtime_id == "pi":
        args = [command, "--print", "--mode", "json", "--offline"]
        if model:
            args.extend(["--model", model])
        if normalized_effort in {"off", "minimal", "low", "medium", "high", "xhigh", "max"}:
            args.extend(["--thinking", normalized_effort])
        if operation_mode == "chat":
            args.extend(["--no-approve", "--tools", "read,grep,find,ls"])
        else:
            args.append("--approve")
        args.extend(["--", effective_prompt])
        return args

    if runtime_id == "gptme":
        args = [command, "--non-interactive", "--output-format", "json", "--no-stream"]
        if model:
            args.extend(["--model", model])
        if operation_mode == "chat":
            args.extend(["--tools", "read"])
        args.append(effective_prompt)
        return args

    if runtime_id == "deepseek-harness":
        return [command, "--profile", "headless", effective_prompt]

    if runtime_id == "wallbreaker":
        if operation_mode == "chat":
            raise ValueError(
                "Wallbreaker is an authorized security campaign harness and is not available in Direct chat."
            )
        args = [command, "--auto", "--rounds", "12"]
        if model:
            args.extend(["--model", model])
        args.append(effective_prompt)
        return args

    if runtime_id == "rook":
        if operation_mode == "chat":
            raise ValueError(
                "Rook is an authorized security-audit harness and is not available in Direct chat."
            )
        args = [command, "--verbose", "--max-iterations", "120"]
        if model:
            args.extend(["--model", model])
        args.append(effective_prompt)
        return args

    args = [command, "--print", effective_prompt, "--output-format", "stream-json", "--verbose"]
    if model:
        args.extend(["--model", model])
    if normalized_effort in {"low", "medium", "high", "xhigh", "max"}:
        args.extend(["--effort", normalized_effort])
    if session_id:
        args.extend(["--session-id", session_id])
    claude_permission_mode = (
        "bypassPermissions" if requested_permission == "full-access"
        else "acceptEdits" if requested_permission == "workspace"
        else "plan" if requested_permission == "read-only" or operation_mode == "chat"
        else "acceptEdits"
    )
    claude_allowed_tools = (
        ["Read", "Glob", "Grep"]
        if claude_permission_mode == "plan"
        else ["Read", "Glob", "Grep", "Edit", "Write"]
        if claude_permission_mode == "acceptEdits"
        else ["Read", "Glob", "Grep", "Edit", "Write", "Bash", "WebFetch", "WebSearch"]
    )
    args.extend([
        "--permission-mode",
        claude_permission_mode,
        "--max-turns",
        "8" if operation_mode == "chat" else "24",
    ])
    args.append("--forward-subagent-text")
    if claude_permission_mode == "bypassPermissions":
        # Make the complete built-in tool set available. MCP/plugin tools keep
        # their normal installation/configuration lifecycle.
        args.extend(["--tools", "default"])
    else:
        args.append("--allowedTools")
        args.extend(claude_allowed_tools)
    if runtime_id == "claude-code" and str(system_prompt_file or "").strip():
        args.extend(["--system-prompt-file", str(system_prompt_file)])
    return args


def _content_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip().lower()
            if item_type in {"", "text", "output_text", "assistant_text"}:
                text = _content_text(item.get("text") or item.get("content"))
                if text:
                    parts.append(text)
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        for key in ("content", "text", "result", "output_text"):
            text = _content_text(value.get(key))
            if text:
                return text
    return ""


def _payload_kind(payload: dict[str, Any]) -> str:
    return str(
        payload.get("type")
        or payload.get("event")
        or payload.get("kind")
        or payload.get("method")
        or ""
    ).strip().lower()


def _assistant_text(payload: dict[str, Any]) -> tuple[str, bool]:
    """Return assistant text and whether it is a terminal/final value."""

    kind = _payload_kind(payload)
    role = str(payload.get("role") or "").strip().lower()
    message = payload.get("message")
    if isinstance(message, dict):
        message_role = str(message.get("role") or role).strip().lower()
        if message_role == "assistant" or kind in {"assistant", "message", "assistant_message"}:
            text = _content_text(message.get("content") or message.get("text"))
            if text:
                return text, False

    assistant_event = payload.get("assistantMessageEvent")
    if isinstance(assistant_event, dict):
        text = _content_text(
            assistant_event.get("delta")
            or assistant_event.get("text")
            or assistant_event.get("content")
        )
        if text:
            return text, False

    item = payload.get("item")
    if isinstance(item, dict):
        item_type = str(item.get("type") or "").strip().lower()
        if item_type == "agent_message":
            text = _content_text(item.get("text") or item.get("content"))
            if text:
                return text, True

    if role == "assistant" or kind in {
        "assistant",
        "assistant_message",
        "message",
        "message_delta",
        "content_block_delta",
        "agent_message_chunk",
        "response.output_text.delta",
    }:
        text = _content_text(
            payload.get("content")
            or payload.get("text")
            or payload.get("delta")
            or payload.get("output_text")
        )
        if text:
            return text, False

    if kind in {"result", "done", "complete", "completed", "final", "response.completed"}:
        text = _content_text(
            payload.get("result")
            or payload.get("output")
            or payload.get("response")
            or payload.get("content")
            or payload.get("text")
        )
        if text:
            return text, True
    return "", False


def _session_id(payload: dict[str, Any]) -> str:
    candidates: list[object] = [payload]
    for key in ("message", "result", "session"):
        value = payload.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in (
            "session_id",
            "sessionId",
            "sessionID",
            "conversation_id",
            "conversationId",
        ):
            value = candidate.get(key)
            if value:
                return str(value)
        thread_id = candidate.get("thread_id")
        if thread_id:
            return str(thread_id)
        if _payload_kind(payload) == "session" and candidate.get("id"):
            return str(candidate["id"])
    return ""


def _tool_labels(payload: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    candidates: list[object] = [
        payload,
        payload.get("item"),
        payload.get("tool_call"),
        payload.get("toolCall"),
        payload.get("tool_use"),
        payload.get("toolUse"),
        payload.get("tool_calls"),
    ]
    message = payload.get("message")
    if isinstance(message, dict):
        candidates.extend([message.get("tool_calls"), message.get("content")])
    for candidate in candidates:
        rows = candidate if isinstance(candidate, list) else [candidate]
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_type = str(row.get("type") or "").lower()
            if row_type in {
                "command_execution",
                "file_change",
                "mcp_tool_call",
                "web_search",
            }:
                label = (
                    row.get("command")
                    or row.get("name")
                    or row.get("server")
                    or row_type
                )
                compact_label = _compact(label, limit=160)
                if compact_label and compact_label not in labels:
                    labels.append(compact_label)
                continue
            has_tool_shape = bool(
                row.get("tool_name")
                or row.get("toolName")
                or row.get("function")
            )
            if row_type and "tool" not in row_type and not has_tool_shape:
                continue
            name = row.get("name") or row.get("tool_name") or row.get("toolName")
            function = row.get("function")
            if not name and isinstance(function, dict):
                name = function.get("name")
            if name and str(name) not in labels:
                labels.append(str(name))
    return labels


def _popen_args(args: list[str]) -> list[str]:
    if not args:
        return args
    resolved = shutil.which(args[0]) or args[0]
    launch_args = [resolved, *args[1:]]
    if os.name == "nt" and Path(resolved).suffix.lower() in {".bat", ".cmd"}:
        shim = Path(resolved)
        try:
            shim_text = shim.read_text(encoding="utf-8", errors="replace")
        except OSError:
            shim_text = ""
        match = re.search(r'"%dp0%\\([^"\r\n]+\.(?:c?js|mjs))"\s+%\*', shim_text, flags=re.IGNORECASE)
        script = (shim.parent / match.group(1).replace("\\", os.sep)).resolve() if match else None
        node_command = shutil.which("node")
        if script and script.is_file() and node_command:
            return [node_command, str(script), *args[1:]]
        return ["cmd", "/d", "/s", "/c", subprocess.list2cmdline(launch_args)]
    return launch_args


def run_external_cli(
    *,
    runtime: str,
    command: str,
    prompt: str,
    model: str = "",
    effort: str = "",
    mode: str = "mission",
    permission_mode: str = "",
    session_id: str = "",
    workspace_root: str = "",
    harness_profile: str = "",
    system_prompt_file: str = "",
) -> int:
    rook_objective_path = ""
    if str(runtime or "").strip().lower() == "rook":
        workspace = Path(workspace_root).expanduser().resolve(strict=True)
        objective_root = workspace / ".agent_control" / "harness_jobs" / "rook_objectives"
        objective_root.mkdir(parents=True, exist_ok=True)
        objective_path = objective_root / f"objective-{uuid.uuid4().hex}.yaml"
        objective_path.write_text(
            json.dumps(
                {
                    "objective": str(prompt or "").strip(),
                    "success": [
                        "Every finding is tied to reproducible evidence or explicitly marked unconfirmed.",
                        "The final report states the tested scope, tools used, and unresolved limitations.",
                    ],
                    "rules_of_engagement": [
                        "Operate only inside the explicitly authorized target and workspace.",
                        "Do not expand scope, establish persistence, or access unrelated credentials or data.",
                        "Prefer read-only validation and stop when the authorization boundary is ambiguous.",
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        rook_objective_path = str(objective_path)
    args = build_cli_args(
        runtime=runtime,
        command=command,
        prompt=rook_objective_path or prompt,
        model=model,
        effort=effort,
        mode=mode,
        permission_mode=permission_mode,
        session_id=session_id,
        system_prompt_file=system_prompt_file,
    )
    child_env = _merge_launch_env(
        runtime=runtime,
        workspace_root=workspace_root,
        harness_profile=harness_profile,
    )
    normalized_effort = str(effort or "").strip().lower()
    kimi_effort_applied = False
    if (
        runtime == "kimi-code"
        and child_env.get("KIMI_MODEL_API_KEY")
        and child_env.get("KIMI_MODEL_BASE_URL")
        and str(model or "").strip()
    ):
        selected_kimi_model = str(model).strip()
        child_env["KIMI_MODEL_NAME"] = selected_kimi_model
        if selected_kimi_model == "k3":
            child_env["KIMI_MODEL_MAX_CONTEXT_SIZE"] = "1048576"
        elif selected_kimi_model in {
            "k3-256k",
            "kimi-for-coding",
            "kimi-for-coding-highspeed",
        }:
            child_env["KIMI_MODEL_MAX_CONTEXT_SIZE"] = "262144"
    if (
        runtime == "kimi-code"
        and child_env.get("KIMI_MODEL_NAME")
        and child_env.get("KIMI_MODEL_API_KEY")
        and normalized_effort in {"low", "high", "max"}
    ):
        child_env["KIMI_MODEL_THINKING_EFFORT"] = normalized_effort
        kimi_effort_applied = True
    read_only_temporaries: list[tempfile.TemporaryDirectory[str]] = []
    child_cwd: Path | None = None
    if str(workspace_root or "").strip():
        candidate_cwd = Path(workspace_root).expanduser().resolve()
        if candidate_cwd.is_dir():
            child_cwd = candidate_cwd
    read_only_enforcement = ""
    if str(mode or "").strip().lower() == "chat":
        if runtime == "kimi-code":
            workspace_temp, home_temp, child_cwd = _prepare_kimi_read_only_runtime(
                workspace_root=workspace_root,
                child_env=child_env,
            )
            read_only_temporaries.extend([workspace_temp, home_temp])
            read_only_enforcement = "isolated-workspace-and-static-deny-rules"
        elif runtime == "claude-code":
            read_only_enforcement = "claude-plan-permission-mode"
        elif runtime == "grok-build":
            read_only_enforcement = "grok-write-and-shell-tools-disabled"
        elif runtime == "codex":
            read_only_enforcement = "codex-read-only-sandbox"
        elif runtime in {"prime-agent", "pi", "gptme", "deepseek-harness"}:
            workspace_temp, child_cwd = _prepare_generic_read_only_runtime(workspace_root)
            read_only_temporaries.append(workspace_temp)
            read_only_enforcement = "isolated-workspace-mirror"
    effective_model = model or str(child_env.get("FLUXIO_HARNESS_MODEL") or "").strip()
    if effective_model and not model:
        # Re-build args when the profile supplies the model alias.
        args = build_cli_args(
            runtime=runtime,
            command=command,
            prompt=rook_objective_path or prompt,
            model=effective_model,
            effort=effort,
            mode=mode,
            permission_mode=permission_mode,
            session_id=session_id,
            system_prompt_file=system_prompt_file,
        )
    auth_surface = "ambient"
    if (
        child_env.get("GROK_MODELS_BASE_URL")
        or child_env.get("ANTHROPIC_BASE_URL")
        or child_env.get("KIMI_MODEL_BASE_URL")
    ):
        auth_surface = str(child_env.get("FLUXIO_HARNESS_COMPAT") or "gateway")
    elif (
        child_env.get("XAI_API_KEY")
        or child_env.get("ANTHROPIC_API_KEY")
        or child_env.get("ANTHROPIC_AUTH_TOKEN")
        or child_env.get("KIMI_MODEL_API_KEY")
    ):
        auth_surface = "api-key"
    headless_transport = (
        "text-plus-session-log"
        if runtime == "deepseek-harness"
        else "text-plus-run-log"
        if runtime == "wallbreaker"
        else "text-plus-session-log"
        if runtime == "rook"
        else "headless-json"
    )
    effort_control = (
        "ephemeral-provider-env"
        if kimi_effort_applied
        else "provider-default"
        if runtime in {"kimi-code", "deepseek-harness", "gptme", "wallbreaker", "rook"}
        else "cli-argument"
    )
    event_data = {
        "sourceKind": "real-runtime-output",
        "captureMode": "fresh-runtime-command",
        "transport": headless_transport,
        "runtime": runtime,
        "model": effective_model or model,
        "effortRequested": normalized_effort,
        "effortControl": effort_control,
        "operationMode": mode,
        "authSurface": auth_surface,
        "harnessProfile": str(harness_profile or child_env.get("FLUXIO_HARNESS_PROFILE") or ""),
        "gatewayBaseUrlSet": bool(
            child_env.get("GROK_MODELS_BASE_URL")
            or child_env.get("ANTHROPIC_BASE_URL")
            or child_env.get("KIMI_MODEL_BASE_URL")
        ),
        "readOnlyEnforcement": read_only_enforcement,
    }
    emit_event(
        kind="runtime.launch",
        message=f"{runtime} headless run started{f' with {effective_model or model}' if (effective_model or model) else ''}.",
        data=event_data,
    )
    try:
        child = subprocess.Popen(  # noqa: S603
            _popen_args(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=child_env,
            cwd=str(child_cwd) if child_cwd else None,
            **hidden_windows_subprocess_kwargs(),
        )
    except BaseException:
        for temporary in reversed(read_only_temporaries):
            temporary.cleanup()
        raise

    assistant_parts: list[str] = []
    plain_parts: list[str] = []
    final_text = ""
    external_session_id = ""
    raw_tail: list[str] = []
    if child.stdout is not None:
        for raw_line in iter(child.stdout.readline, ""):
            line = raw_line.strip()
            if not line:
                continue
            raw_tail = [*raw_tail[-5:], line]
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                if runtime == "wallbreaker" and line.startswith("[tool "):
                    label = line.removeprefix("[tool ").removesuffix("]")
                    emit_event(
                        kind="runtime.tool",
                        message=f"wallbreaker tool event: {_compact(label)}",
                        data={**event_data, "tool": _compact(label, limit=160)},
                    )
                    continue
                if runtime == "wallbreaker" and line.startswith("[run log]"):
                    emit_event(
                        kind="runtime.artifact",
                        message=_compact(line),
                        data={**event_data, "artifactKind": "wallbreaker-run-log"},
                    )
                    continue
                if runtime in {"deepseek-harness", "wallbreaker", "rook"}:
                    plain_parts.append(line)
                emit_event(
                    kind="runtime.output",
                    message=_compact(line),
                    data=event_data,
                )
                continue
            if not isinstance(payload, dict):
                continue
            observed_session_id = _session_id(payload)
            if observed_session_id:
                external_session_id = observed_session_id
            text, terminal = _assistant_text(payload)
            if text:
                if terminal:
                    final_text = text
                elif not assistant_parts or assistant_parts[-1] != text:
                    assistant_parts.append(text)
            for tool_label in _tool_labels(payload):
                emit_event(
                    kind="runtime.tool",
                    message=f"{runtime} tool event: {tool_label}",
                    data={**event_data, "tool": tool_label},
                )

    return_code = child.wait()
    assistant_text = (final_text or "".join(assistant_parts) or "\n".join(plain_parts)).strip()
    final_data = {
        **event_data,
        "externalRuntimeSessionId": external_session_id or session_id,
    }
    if assistant_text:
        emit_event(
            kind="runtime.model_message",
            message=assistant_text,
            data=final_data,
        )
    elif raw_tail:
        emit_event(
            kind="runtime.output",
            message=_compact(" | ".join(raw_tail), limit=1000),
            status="failed" if return_code else "completed",
            data=final_data,
        )
    emit_event(
        kind="runtime.finished" if return_code == 0 else "runtime.failed",
        message=(
            f"{runtime} headless run completed."
            if return_code == 0
            else f"{runtime} headless run failed with exit code {return_code}."
        ),
        status="completed" if return_code == 0 else "failed",
        data=final_data,
    )
    for temporary in reversed(read_only_temporaries):
        temporary.cleanup()
    return return_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bridge supported external coding-harness output into Neyvia events."
    )
    parser.add_argument("--runtime", required=True, choices=SUPPORTED_EXTERNAL_CLI_RUNTIMES)
    parser.add_argument("--command", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--effort", default="")
    parser.add_argument("--mode", default="mission", choices=["chat", "mission"])
    parser.add_argument(
        "--permission-mode",
        default="",
        choices=["", "read-only", "workspace", "full-access"],
        help="Explicit harness permission boundary selected for this turn.",
    )
    parser.add_argument("--session-id", default="")
    parser.add_argument("--system-prompt-file", default="")
    parser.add_argument(
        "--workspace-root",
        default="",
        help="Workspace root used to load .agent_control/harness_profiles.json overlays.",
    )
    parser.add_argument(
        "--harness-profile",
        default="",
        help="Optional harness profile id (API key / OpenAI-compatible proxy / local proxy).",
    )
    args = parser.parse_args(argv)
    return run_external_cli(
        runtime=args.runtime,
        command=args.command,
        prompt=args.prompt,
        model=args.model,
        effort=args.effort,
        mode=args.mode,
        permission_mode=args.permission_mode,
        session_id=args.session_id,
        workspace_root=args.workspace_root,
        harness_profile=args.harness_profile,
        system_prompt_file=args.system_prompt_file,
    )


if __name__ == "__main__":
    raise SystemExit(main())

