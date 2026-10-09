from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    from .subprocess_utils import hidden_windows_subprocess_kwargs
except ImportError:  # pragma: no cover - direct script fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs

STRUCTURED_EVENT_PREFIX = "FLUXIO_EVENT:"


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


def _event_text(payload: dict[str, Any]) -> str:
    part = payload.get("part")
    if isinstance(part, dict) and str(part.get("type") or "").lower() == "text":
        return str(part.get("text") or "").strip()
    if str(payload.get("type") or "").lower() == "text":
        value = payload.get("text")
        if isinstance(value, str):
            return value.strip()
    return ""


def _event_session_id(payload: dict[str, Any]) -> str:
    value = payload.get("sessionID") or payload.get("sessionId")
    if value:
        return str(value)
    part = payload.get("part")
    if isinstance(part, dict):
        value = part.get("sessionID") or part.get("sessionId")
        if value:
            return str(value)
    return ""


def _compact(value: object, *, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def run_opencode(
    *,
    opencode_command: str,
    prompt: str,
    model: str = "",
    title: str = "",
    variant: str = "",
    mode: str = "mission",
    external_directories: list[str] | None = None,
    resume_session: str = "",
    max_steps: int | None = None,
    instructions_file: str = "",
) -> int:
    args = [opencode_command, "run", "--format", "json"]
    if model:
        args.extend(["--model", model])
    if title:
        args.extend(["--title", title])
    if resume_session:
        args.extend(["--session", resume_session])
    if variant:
        args.extend(["--variant", variant])
    operation_mode = "chat" if str(mode or "").strip().lower() == "chat" else "mission"
    child_env = os.environ.copy()
    config = json.loads(child_env.get("OPENCODE_CONFIG_CONTENT") or "{}")
    if not isinstance(config, dict):
        raise ValueError("OpenCode inline configuration must be an object")
    if operation_mode == "mission" and external_directories:
        permission = config.setdefault("permission", {})
        if not isinstance(permission, dict):
            raise ValueError("Cannot merge scoped directories into a shorthand permission policy")
        directories = permission.get("external_directory", {})
        if isinstance(directories, str):
            directories = {"*": directories}
        if not isinstance(directories, dict):
            raise ValueError("OpenCode external_directory policy must be a mapping or permission action")
        directories = dict(directories)
        for directory in external_directories:
            approved = Path(directory).expanduser()
            if not approved.is_absolute() or approved == Path(approved.anchor):
                raise ValueError("External directory grants require a specific absolute directory")
            for value in {str(approved), approved.as_posix()}:
                directories[value.rstrip("/\\") + "/*"] = "allow"
                directories[value.rstrip("/\\") + "\\*"] = "allow"
        permission["external_directory"] = directories
    if operation_mode == "chat":
        config["permission"] = {
                    "*": "deny",
                    "read": "allow",
                    "glob": "allow",
                    "grep": "allow",
                    "lsp": "allow",
                    "webfetch": "allow",
                    "websearch": "allow",
                    "edit": "deny",
                    "bash": "deny",
                    "task": "deny",
                    "skill": "deny",
                    "external_directory": "deny",
                }
    if max_steps is not None or instructions_file:
        if max_steps is not None and (isinstance(max_steps, bool) or not isinstance(max_steps, int) or not 1 <= max_steps <= 64):
            raise ValueError("OpenCode max_steps must be an integer from 1 to 64")
        # Own the selected agent's budget rather than mutating the user's build
        # agent or trusting a provider default that may have no step limit.
        agents = config.setdefault("agent", {})
        if not isinstance(agents, dict):
            raise ValueError("OpenCode agent configuration must be an object")
        agent_name = "neyvia-harness"
        agents[agent_name] = {"description": "Neyvia bounded workflow executor", "mode": "primary",
                              "permission": {"task": "deny"}}
        if max_steps is not None:
            agents[agent_name]["steps"] = max_steps
        if instructions_file:
            prompt_file = Path(instructions_file).expanduser().resolve(strict=True)
            if not 1 <= prompt_file.stat().st_size <= 1_000_000:
                raise ValueError("System prompt file must contain at most 1 MB")
            # Use OpenCode's actual agent system-prompt channel. A file reference
            # avoids the Windows environment size limit for long saved prompts.
            agents[agent_name]["prompt"] = "{file:" + prompt_file.as_posix() + "}"
        # Neyvia owns delegation and exact route selection. A bounded child must
        # not silently start nested agents outside that graph and its budget.
        if operation_mode == "chat":
            agents[agent_name]["permission"] = dict(config["permission"])
        args.extend(["--agent", agent_name])
    child_env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config, separators=(",", ":"))

    emit_event(
        kind="runtime.launch",
        message=f"OpenCode run started{f' with {model}' if model else ''}.",
        status="running",
        data={
            "sourceKind": "real-runtime-output",
            "captureMode": "fresh-runtime-command",
            "model": model,
            "runtime": "opencode",
            "operationMode": operation_mode,
            "maxSteps": max_steps,
            "readOnlyEnforcement": (
                "inline-deny-permissions" if operation_mode == "chat" else ""
            ),
        },
    )
    # Transport user text as UTF-8 data, not a Windows command-line argument.
    # This also avoids quoting differences in Bun and the Windows argument limit.
    with tempfile.TemporaryFile() as prompt_input:
        prompt_input.write(prompt.encode("utf-8"))
        prompt_input.seek(0)
        child = subprocess.Popen(  # noqa: S603
            _popen_args(args),
            stdin=prompt_input,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=child_env,
            **hidden_windows_subprocess_kwargs(),
        )

    text_parts: list[str] = []
    step_text_parts: list[str] = []
    final_text_parts: list[str] = []
    session_id = ""
    raw_tail: list[str] = []
    runtime_error = False
    last_finish = ""
    failure_detail = ""
    usage: dict[str, Any] = {"source": "provider-reported", "steps": 0}
    usage_steps: set[str] = set()
    if child.stdout is not None:
        for raw_line in iter(child.stdout.readline, ""):
            line = raw_line.strip()
            if not line:
                continue
            raw_tail.append(line)
            raw_tail = raw_tail[-6:]
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                if "auto-rejecting" in line:
                    runtime_error = True
                    failure_detail = _compact(line)
                emit_event(
                    kind="runtime.output",
                    message=_compact(line),
                    status="running",
                    data={
                        "sourceKind": "real-runtime-output",
                        "captureMode": "fresh-runtime-command",
                        "model": model,
                        "runtime": "opencode",
                    },
                )
                continue
            if isinstance(payload, dict):
                if payload.get("type") == "step_start":
                    step_text_parts = []
                if payload.get("type") == "error":
                    runtime_error = True
                    failure_detail = _compact(payload.get("error") or payload)
                event_session_id = _event_session_id(payload)
                if event_session_id:
                    session_id = event_session_id
                text = _event_text(payload)
                if text:
                    text_parts.append(text)
                    step_text_parts.append(text)
                part = payload.get("part") if isinstance(payload.get("part"), dict) else {}
                state = part.get("state") if isinstance(part.get("state"), dict) else {}
                if payload.get("type") == "step_finish":
                    last_finish = str(part.get("reason") or "")
                    if last_finish == "stop":
                        final_text_parts = list(step_text_parts)
                    step_id = str(part.get("id") or "")
                    if not step_id or step_id not in usage_steps:
                        if step_id:
                            usage_steps.add(step_id)
                        usage["steps"] += 1
                        tokens = part.get("tokens") if isinstance(part.get("tokens"), dict) else {}
                        cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
                        for key, value in {"inputTokens": tokens.get("input"), "outputTokens": tokens.get("output"),
                                           "reasoningTokens": tokens.get("reasoning"), "cacheReadTokens": cache.get("read"),
                                           "cacheWriteTokens": cache.get("write"), "cost": part.get("cost")}.items():
                            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                                usage[key] = usage.get(key, 0) + value
                emit_event(
                    kind="runtime.progress",
                    message=_compact(text or state.get("title") or part.get("tool") or payload.get("type")),
                    data={
                        "sourceKind": "real-runtime-output",
                        "runtime": "opencode",
                        "model": model,
                        "externalRuntimeSessionId": session_id,
                        "processId": child.pid,
                        "eventType": payload.get("type"),
                        "tool": part.get("tool") if isinstance(part, dict) else None,
                        "toolStatus": state.get("status"),
                        **({"usage": dict(usage)} if payload.get("type") == "step_finish" else {}),
                    },
                )

    return_code = child.wait()
    if last_finish and last_finish != "stop":
        runtime_error = True
        failure_detail = failure_detail or f"OpenCode stopped without a final answer (finish reason: {last_finish})."
    if runtime_error and return_code == 0:
        return_code = 1
    assistant_text = "\n".join(part for part in (final_text_parts or text_parts) if part).strip()
    event_data = {
        "sourceKind": "real-runtime-output",
        "captureMode": "fresh-runtime-command",
        "runtime": "opencode",
        "model": model,
        "externalRuntimeSessionId": session_id,
    }
    if runtime_error:
        emit_event(kind="runtime.error", message=failure_detail or "OpenCode runtime error",
                   status="failed", data=event_data)
    if assistant_text:
        emit_event(
            kind="runtime.model_message",
            message=assistant_text,
            status="running",
            data=event_data,
        )
    elif raw_tail:
        emit_event(
            kind="runtime.output",
            message=_compact(" | ".join(raw_tail), limit=900),
            status="failed" if return_code else "completed",
            data=event_data,
        )
    emit_event(
        kind="runtime.finished" if return_code == 0 else "runtime.failed",
        message=(
            "OpenCode run completed."
            if return_code == 0
            else f"OpenCode run failed with exit code {return_code}."
        ),
        status="completed" if return_code == 0 else "failed",
        data=event_data,
    )
    return return_code


def _popen_args(args: list[str]) -> list[str]:
    if not args:
        return args
    resolved = shutil.which(args[0]) or args[0]
    launch_args = [resolved, *args[1:]]
    if os.name == "nt" and Path(resolved).suffix.lower() in {".bat", ".cmd"}:
        # npm's batch shim splits multiline prompts at cmd.exe boundaries and
        # expands shell metacharacters. Launch its payload directly instead.
        shim_dir = Path(resolved).parent
        executable = shim_dir / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
        if executable.is_file():
            return [str(executable), *args[1:]]
        script = shim_dir / "node_modules" / "opencode-ai" / "bin" / "opencode"
        node = shutil.which("node")
        if script.is_file() and node:
            return [node, str(script), *args[1:]]
        raise RuntimeError("Cannot safely launch this OpenCode batch wrapper. Install the native OpenCode executable or the opencode-ai npm package.")
    return launch_args


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bridge OpenCode JSON output into Neyvia runtime events.")
    parser.add_argument("--opencode-command", default="opencode")
    parser.add_argument("--model", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--variant", default="")
    parser.add_argument("--mode", default="mission", choices=["chat", "mission"])
    parser.add_argument("--external-directory", action="append", default=[])
    parser.add_argument("--resume-session", default="")
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--instructions-file", default="")
    prompts = parser.add_mutually_exclusive_group(required=True)
    prompts.add_argument("--prompt")
    prompts.add_argument("--prompt-stdin", action="store_true")
    args = parser.parse_args(argv)
    return run_opencode(
        opencode_command=args.opencode_command,
        prompt=sys.stdin.read() if args.prompt_stdin else args.prompt,
        model=args.model,
        title=args.title,
        variant=args.variant,
        mode=args.mode,
        external_directories=args.external_directory,
        resume_session=args.resume_session,
        max_steps=args.max_steps,
        instructions_file=args.instructions_file,
    )


if __name__ == "__main__":
    raise SystemExit(main())

