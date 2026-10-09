"""One bounded Codex app-server turn with observable answer deltas."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .chat_stream import safe_tool_display
from .subprocess_utils import hidden_windows_subprocess_kwargs


def _stop_tree(process: subprocess.Popen[str]) -> bool:
    if process.poll() is not None:
        return False
    try:
        if os.name == "nt":
            stopped = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, timeout=10, check=False,
                **hidden_windows_subprocess_kwargs(),
            )
            if stopped.returncode == 0:
                return True
        else:
            import signal
            os.killpg(process.pid, signal.SIGKILL)
            return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    if process.poll() is None:
        process.kill()
    return False


def run_codex_streamed(
    *, command: str, config_args: list[str], cwd: Path, model: str,
    effort: str | None, base_instructions: str, prompt: str, allow_mutations: bool,
    timeout: int | None, on_event: Callable[[dict[str, Any]], None] | None = None,
    permission_mode: str = "",
) -> dict[str, Any]:
    """Run app-server over stdio; do not invent deltas or silently retry actions."""
    started = time.monotonic()
    process = subprocess.Popen(
        [command, "app-server", "--stdio", *config_args], cwd=str(cwd),
        env=dict(os.environ), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
        bufsize=1, start_new_session=os.name != "nt",
        **hidden_windows_subprocess_kwargs(new_process_group=True),
    )
    from .chat_run_control import note_runtime_process

    note_runtime_process(process.pid)
    incoming: queue.Queue[tuple[str, str | None]] = queue.Queue()
    stderr_tail: list[str] = []

    def drain(name: str, pipe: Any) -> None:
        try:
            for line in pipe:
                incoming.put((name, line))
        finally:
            incoming.put((name, None))

    readers = [
        threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True),
    ]
    for reader in readers:
        reader.start()

    def send(message: dict[str, Any]) -> None:
        process.stdin.write(json.dumps(message, ensure_ascii=True) + "\n")
        process.stdin.flush()

    def emit(kind: str, message: str, **data: Any) -> None:
        if on_event is not None:
            on_event({"kind": kind, "message": message, "data": data})

    def recorded_value(value: Any) -> str:
        return safe_tool_display(value)

    phases: dict[str, int] = {"processStarted": int((time.monotonic() - started) * 1000)}
    def mark(name: str) -> int:
        elapsed = int((time.monotonic() - started) * 1000)
        phases.setdefault(name, elapsed)
        return elapsed

    deadline = started + timeout if timeout is not None else None
    thread_id = ""
    turn_id = ""
    answer_by_item: dict[str, str] = {}
    last_answer_item = ""
    tool_events: list[str] = []
    from .model_usage import CodexUsage, ZERO
    usage_tracker = CodexUsage(ZERO)
    failure: dict[str, Any] | None = None
    finished = False
    tree_stopped = False
    send({"id": 1, "method": "initialize", "params": {
        "clientInfo": {"name": "neyvia-native", "version": "1.0"},
    }})
    try:
        while not finished:
            remaining = deadline - time.monotonic() if deadline is not None else 0.25
            if remaining <= 0:
                failure = {"code": "executor_timeout", "retrySafety": "reconcile_before_retry"}
                break
            try:
                source, raw = incoming.get(timeout=min(remaining, 0.25))
            except queue.Empty:
                if process.poll() is not None:
                    failure = {"code": "executor_failed", "exitCode": process.returncode}
                    break
                continue
            if raw is None:
                if source == "stdout" and not finished:
                    failure = {"code": "executor_failed", "exitCode": process.poll()}
                    break
                continue
            if source == "stderr":
                stderr_tail.append(raw[-500:])
                stderr_tail = stderr_tail[-8:]
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            request_id = event.get("id")
            error = event.get("error")
            if error and request_id in {1, 2, 3}:
                failure = {"code": "executor_failed", "stage": {1: "initialize", 2: "thread/start", 3: "turn/start"}[request_id],
                           "detail": str(error.get("message") if isinstance(error, dict) else error)[:500]}
                break
            result = event.get("result") if isinstance(event.get("result"), dict) else {}
            if request_id == 1:
                mark("initialized")
                send({"method": "initialized", "params": {}})
                send({"id": 2, "method": "thread/start", "params": {
                    "cwd": str(cwd), "model": model,
                    "sandbox": ("danger-full-access" if permission_mode == "full-access" else "workspace-write") if allow_mutations else "read-only",
                    "approvalPolicy": "never", "ephemeral": True,
                    "baseInstructions": base_instructions,
                    "developerInstructions": "",
                }})
                emit("runtime.progress", "Connected to Codex", eventType="thread.starting", elapsedMs=phases["initialized"])
            elif request_id == 2:
                mark("threadReady")
                thread_id = str((result.get("thread") or {}).get("id") or "")
                if not thread_id:
                    failure = {"code": "executor_failed", "stage": "thread/start"}
                    break
                params: dict[str, Any] = {
                    "threadId": thread_id, "input": [{"type": "text", "text": prompt}],
                    "summary": "concise",
                }
                if effort:
                    params["effort"] = effort
                send({"id": 3, "method": "turn/start", "params": params})
                emit("runtime.progress", "Model session ready", eventType="thread.started", elapsedMs=phases["threadReady"])
            elif request_id == 3:
                mark("turnStarted")
                turn_id = str((result.get("turn") or {}).get("id") or "")
                emit("runtime.progress", "Model is responding", eventType="turn.started", elapsedMs=phases["turnStarted"])
            elif request_id is not None and event.get("method"):
                # An unhandled server request must fail explicitly instead of hanging.
                send({"id": request_id, "error": {"code": -32601, "message": "Neyvia cannot grant this interactive request."}})
            method = str(event.get("method") or "")
            params = event.get("params") if isinstance(event.get("params"), dict) else {}
            if method == "item/agentMessage/delta":
                item_id = str(params.get("itemId") or "answer")
                delta = str(params.get("delta") or "")
                if delta:
                    mark("firstAnswer")
                    answer_by_item[item_id] = answer_by_item.get(item_id, "") + delta
                    last_answer_item = item_id
                    emit("runtime.answer_delta", delta, eventType=method, itemId=item_id)
            elif method == "item/reasoning/summaryTextDelta":
                delta = str(params.get("delta") or "")
                if delta:
                    mark("firstReasoningSummary")
                    emit("runtime.reasoning_summary_delta", delta, eventType=method)
            elif method in {"item/started", "item/completed"}:
                item = params.get("item") if isinstance(params.get("item"), dict) else {}
                item_type = str(item.get("type") or "")
                if item_type == "agentMessage" and method == "item/completed":
                    item_id = str(item.get("id") or "answer")
                    actual = str(item.get("text") or "")
                    if actual:
                        answer_by_item[item_id] = actual
                        last_answer_item = item_id
                elif item_type and item_type not in {"userMessage", "reasoning"}:
                    if item_type not in tool_events:
                        tool_events.append(item_type)
                    tool_name = str(item.get("tool") or item.get("name") or item_type)
                    tool_goal = recorded_value(item.get("description") or item.get("goal") or item.get("purpose"))
                    command_text = recorded_value(item.get("command"))
                    input_value = (item.get("arguments") or item.get("input")
                                   or item.get("query") or item.get("changes"))
                    input_text = recorded_value(input_value)
                    output_text = recorded_value(
                        item.get("aggregatedOutput") or item.get("result") or item.get("output")
                    ) if method == "item/completed" else ""
                    error_text = recorded_value(item.get("error"))
                    status = "started" if method == "item/started" else (
                        "failed" if error_text or str(item.get("status") or "").lower() in {"failed", "error"}
                        else "completed"
                    )
                    item_id = str(item.get("id") or "")
                    call_id = str(item.get("callId") or item.get("call_id") or item_id)
                    emit("runtime.tool", tool_name, eventType=method, tool=tool_name,
                         toolStatus=status, status=status,
                         callId=call_id, command=command_text, input=input_text,
                         output=output_text if status != "failed" else "",
                         error=error_text, goal=tool_goal, itemId=item_id)
            elif method == "thread/tokenUsage/updated":
                if usage_tracker.observe((params.get("tokenUsage") or {}).get("total")):
                    emit("runtime.progress", "", eventType="model.usage", usage=usage_tracker.receipt())
            elif method in {"turn/completed", "turn/failed"}:
                mark("turnFinished")
                turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
                turn_id = str(turn.get("id") or turn_id)
                if method == "turn/failed" or str(turn.get("status") or "") not in {"completed", ""}:
                    failure = {"code": "executor_failed", "stage": "turn", "status": turn.get("status")}
                finished = True
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        if process.poll() is None:
            try:
                process.wait(timeout=2 if finished else 0.1)
            except subprocess.TimeoutExpired:
                tree_stopped = _stop_tree(process)
        for reader in readers:
            reader.join(timeout=1)

    answer = answer_by_item.get(last_answer_item, "").strip()
    if not failure and not answer:
        failure = {"code": "empty_output"}
    if failure:
        failure.update({"processTreeStopped": tree_stopped, "partialOutput": answer,
                        "observedToolLabels": tool_events,
                        "sideEffects": "uncertain" if allow_mutations else "source_read_only_task_records_possible",
                        "retrySafety": "reconcile_before_retry",
                        "nextAction": "Inspect the saved run receipt and reconcile any action before continuing."})
    emit("runtime.progress", "Model turn completed" if not failure else "Model turn failed",
         eventType="turn.completed" if not failure else "turn.failed")
    return {"output": answer if not failure else (
        "The executor did not complete successfully. Partial progress was preserved in the run receipt; reconcile it before continuing."
    ), "failure": failure, "externalSessionId": thread_id, "turnId": turn_id,
            "toolEvents": tool_events, "usage": usage_tracker.receipt(), "durationMs": int((time.monotonic() - started) * 1000),
            "phaseTimingsMs": phases,
            "localSetupMs": phases.get("turnStarted"),
            "providerToFirstOutputMs": (min(phases[name] for name in ("firstAnswer", "firstReasoningSummary") if name in phases) - phases["turnStarted"])
                if "turnStarted" in phases and any(name in phases for name in ("firstAnswer", "firstReasoningSummary")) else None}
