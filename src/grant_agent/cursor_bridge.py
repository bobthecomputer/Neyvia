from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from .subprocess_utils import hidden_windows_subprocess_kwargs
except ImportError:  # pragma: no cover - direct script fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs

STRUCTURED_EVENT_PREFIX = "FLUXIO_EVENT:"

# Import after the direct-script fallback has made the package available.
from grant_agent.proofs_a_cli import checked


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


def _compact(value: object, *, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _content_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                item_type = str(item.get("type") or "").lower()
                if item_type in {"", "text", "output_text"} and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
        return "\n".join(part.strip() for part in parts if part and part.strip()).strip()
    if isinstance(value, dict):
        return _content_text(value.get("content") or value.get("text") or value.get("result"))
    return ""


@checked('a-cli.cursor.text')
def _message_text(payload: dict[str, Any]) -> str:
    message = payload.get("message")
    if isinstance(message, dict):
        text = _content_text(message.get("content"))
        if text:
            return text
    for key in ("content", "text", "result", "summary"):
        text = _content_text(payload.get(key))
        if text:
            return text
    delta = payload.get("delta")
    if isinstance(delta, dict):
        text = _content_text(delta.get("content") or delta.get("text"))
        if text:
            return text
    return ""


def _event_session_id(payload: dict[str, Any]) -> str:
    for key in ("session_id", "sessionId", "sessionID", "conversation_id", "conversationId"):
        value = payload.get(key)
        if value:
            return str(value)
    message = payload.get("message")
    if isinstance(message, dict):
        for key in ("session_id", "sessionId", "sessionID", "conversation_id", "conversationId"):
            value = message.get(key)
            if value:
                return str(value)
    return ""


def _event_tool_label(payload: dict[str, Any]) -> str:
    for key in ("tool_call", "toolCall", "tool_use", "toolUse", "call"):
        value = payload.get(key)
        if isinstance(value, dict):
            name = value.get("name") or value.get("tool_name") or value.get("toolName")
            if name:
                return str(name)
    name = payload.get("name") or payload.get("tool_name") or payload.get("toolName")
    return str(name or "").strip()


def run_cursor(
    *,
    cursor_command: str,
    prompt: str,
    model: str = "",
    output_format: str = "stream-json",
    stream_partial_output: bool = True,
    force: bool = False,
) -> int:
    args = [cursor_command, "-p", "--output-format", output_format]
    if output_format == "stream-json" and stream_partial_output:
        args.append("--stream-partial-output")
    if force:
        args.append("--force")
    if model:
        args.extend(["--model", model])
    args.append(prompt)

    emit_event(
        kind="runtime.launch",
        message=f"Cursor Agent started{f' with {model}' if model else ''}.",
        status="running",
        data={
            "sourceKind": "real-runtime-output",
            "captureMode": "fresh-runtime-command",
            "model": model,
            "runtime": "cursor",
        },
    )
    child = subprocess.Popen(  # noqa: S603
        _popen_args(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **hidden_windows_subprocess_kwargs(),
    )

    assistant_parts: list[str] = []
    result_text = ""
    session_id = ""
    raw_tail: list[str] = []
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
                assistant_parts.append(line)
                emit_event(
                    kind="runtime.output",
                    message=_compact(line),
                    status="running",
                    data={
                        "sourceKind": "real-runtime-output",
                        "captureMode": "fresh-runtime-command",
                        "model": model,
                        "runtime": "cursor",
                    },
                )
                continue
            if not isinstance(payload, dict):
                continue
            event_session_id = _event_session_id(payload)
            if event_session_id:
                session_id = event_session_id
            payload_type = str(payload.get("type") or payload.get("event") or payload.get("kind") or "").lower()
            text = _message_text(payload)
            if payload_type in {"result", "done", "complete", "completed"} and text:
                result_text = text
            elif text and payload_type in {
                "",
                "assistant",
                "message",
                "message_delta",
                "content_block_delta",
                "text",
                "response",
            }:
                if not assistant_parts or assistant_parts[-1] != text:
                    assistant_parts.append(text)
            tool_label = _event_tool_label(payload)
            if tool_label:
                emit_event(
                    kind="runtime.output",
                    message=f"Cursor tool event: {tool_label}",
                    status="running",
                    data={
                        "sourceKind": "real-runtime-output",
                        "captureMode": "fresh-runtime-command",
                        "model": model,
                        "runtime": "cursor",
                    },
                )

    return_code = child.wait()
    assistant_text = (result_text or "\n".join(part for part in assistant_parts if part)).strip()
    event_data = {
        "sourceKind": "real-runtime-output",
        "captureMode": "fresh-runtime-command",
        "runtime": "cursor",
        "model": model,
        "externalRuntimeSessionId": session_id,
    }
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
            "Cursor Agent run completed."
            if return_code == 0
            else f"Cursor Agent run failed with exit code {return_code}."
        ),
        status="running" if return_code == 0 else "failed",
        data=event_data,
    )
    return return_code


def _popen_args(args: list[str]) -> list[str]:
    if not args:
        return args
    resolved = shutil.which(args[0]) or args[0]
    launch_args = [resolved, *args[1:]]
    if os.name == "nt" and Path(resolved).suffix.lower() in {".bat", ".cmd"}:
        return ["cmd", "/d", "/s", "/c", subprocess.list2cmdline(launch_args)]
    return launch_args


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bridge Cursor Agent output into Neyvia runtime events.")
    parser.add_argument("--cursor-command", default="agent")
    parser.add_argument("--model", default="")
    parser.add_argument("--output-format", default="stream-json")
    parser.add_argument("--no-stream-partial-output", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--prompt", required=True)
    args = parser.parse_args(argv)
    return run_cursor(
        cursor_command=args.cursor_command,
        prompt=args.prompt,
        model=args.model,
        output_format=args.output_format,
        stream_partial_output=not args.no_stream_partial_output,
        force=args.force,
    )


if __name__ == "__main__":
    raise SystemExit(main())
