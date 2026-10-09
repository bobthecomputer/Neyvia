"""Real, matched Claude CLI evaluation against production Notes MCP tools.

No provider fallback and no backend, installations, credentials or built-in tools.
The no-manual arm hides manual discovery; underlying tool implementations match.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def utc():
    return datetime.now(timezone.utc).isoformat()


def serve(root, manual, receipt):
    from grant_agent.neyvia_mcp_stdio import CompactNeyviaMCPServer
    server = CompactNeyviaMCPServer(root, permission_mode="workspace")
    for line in sys.stdin:
        request = json.loads(line)
        params = request.get("params") or {}
        name = params.get("name", "")
        nested = params.get("arguments") or {}
        attempted_manual = name.startswith("neyvia.manual.") or any(
            str(nested.get(key, "")).startswith("neyvia.manual.") for key in ("tool", "toolId", "name", "query"))
        if not manual and attempted_manual:
            response = {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32003, "message": "Manuals excluded from this evaluation arm"}}
        else:
            response = server.handle(request)
        if response and request.get("method") == "initialize":
            response["result"]["instructions"] = "Use search/describe to discover tools, then native.call or tools.invoke using their declared call target. Only this scratch workspace is authorized."
            if manual:
                response["result"]["instructions"] += " Grounded executable manuals are available: load notes/overview for Notes tasks."
        if response and request.get("method") == "tools/list" and not manual:
            response["result"]["tools"] = [row for row in response["result"]["tools"] if not row["name"].startswith("neyvia.manual.")]
        if request.get("method") == "tools/call":
            with receipt.open("a", encoding="utf-8") as output:
                output.write(json.dumps({"at": utc(), "request": request, "response": response}, ensure_ascii=False) + "\n")
        if response is not None:
            print(json.dumps(response, ensure_ascii=True), flush=True)


def executable():
    native = Path(os.environ.get("APPDATA", "")) / "npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe"
    if native.is_file():
        return str(native)
    command = shutil.which("claude.exe") or shutil.which("claude")
    if not command:
        raise RuntimeError("Claude CLI is unavailable")
    return command


TASKS = (
    {"id": "append-tag-pin", "before": "# Research\nKeep the original research note.\n", "body": "Next: compare measured tokens. #research", "mode": "append"},
    {"id": "replace-pin", "before": "# Research\nDraft placeholder in disposable note.\n", "body": "# Research\nCompleted matched comparison. #research\n", "mode": "replace"},
)


def trial(base, model, manual, task, timeout):
    from grant_agent.neyvia_notes_tools import call_notes as call
    work = base / (model + "-" + task["id"])
    work.mkdir(parents=True)
    notes = work / "notes"
    call(work, "folder", {"folder": str(notes)})
    call(work, "write", {"path": "research.md", "body": task["before"]})
    mcp_receipt = work / "mcp-receipts.jsonl"
    config = work / "mcp.json"
    config.write_text(json.dumps({"mcpServers": {"t5": {"type": "stdio", "command": sys.executable,
        "args": [str(Path(__file__).resolve()), "--serve-mcp", "--root", str(work), "--tool-receipt", str(mcp_receipt), *(["--manual"] if manual else [])]}}}), encoding="utf-8")
    operation = "append exactly the following text, preserving all existing text" if task["mode"] == "append" else "replace the disposable draft with exactly the following body"
    prompt = (f"Operate only on this disposable Notes workspace through the provided MCP tools. Read research.md, then {operation}:\n"
        + json.dumps(task["body"]) + "\nUse its observed modified stamp as expectedModified. Pin the note. Read it back to verify body, #research tag and pin. "
        "Finish with a short success/failure receipt. Do not operate on any other workspace.")
    if manual:
        prompt += " Load the grounded notes overview manual first; use its procedures when applicable."
    args = [executable(), "--print", "--model", model, "--effort", "medium", "--restricted", "--tools", "",
        "--setting-sources", "", "--settings", '{"disableAllHooks":true}', "--disable-slash-commands", "--no-chrome",
        "--strict-mcp-config", "--mcp-config", str(config), "--allowedTools", "mcp__t5__*", "--permission-mode", "dontAsk",
        "--no-session-persistence", "--output-format", "stream-json", "--verbose",
        "--system-prompt", "You perform authorized disposable Notes tasks using provided MCP tools. Verify actual state. No subagents, shell, network tools or other workspaces.", prompt]
    started = time.monotonic()
    stream = work / "claude-stream.jsonl"
    error = None
    with stream.open("w", encoding="utf-8") as stdout:
        try:
            result = subprocess.run(args, cwd=work, stdout=stdout, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
            exit_code = result.returncode
            if exit_code:
                error = result.stderr[-1000:]
        except subprocess.TimeoutExpired:
            exit_code, error = None, "Claude CLI exceeded bounded timeout"
    elapsed = round(time.monotonic() - started, 3)
    messages = []
    for line in stream.read_text(encoding="utf-8").splitlines():
        try:
            messages.append(json.loads(line))
        except ValueError:
            pass
    final = next((row for row in reversed(messages) if row.get("type") == "result"), {})
    init = next((row for row in messages if row.get("type") == "system" and row.get("subtype") == "init"), {})
    usage = final.get("usage", {})
    model_usage = final.get("modelUsage", {})
    actual = init.get("model")
    actual_models = list(model_usage) or ([actual] if actual else [])
    model_match = bool(actual_models) and all(model in str(name).lower() for name in actual_models)
    observed = call(work, "read", {"path": "research.md"})
    expected = task["before"] + "\n" + task["body"] if task["mode"] == "append" else task["body"]
    # Seed ends in a single newline: Notes append separates paragraphs with two.
    body_match = observed["body"] == expected
    tool_receipts = [json.loads(line) for line in mcp_receipt.read_text(encoding="utf-8").splitlines()] if mcp_receipt.exists() else []
    manual_loaded = any(row["request"]["params"]["name"] == "neyvia.manual.load" for row in tool_receipts)
    guarded = any(row["request"]["params"]["arguments"].get("arguments", {}).get("expectedModified")
        or row["request"]["params"]["arguments"].get("inputs", {}).get("expectedModified") for row in tool_receipts)
    manual_run = any(row["request"]["params"]["name"] == "neyvia.manual.run" for row in tool_receipts)
    state_ok = body_match and observed.get("pinned") is True and "research" in observed.get("tags", [])
    total_tokens = sum(usage.get(key, 0) or 0 for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    stream_copy = base.parent.parent / ("T5-models-" + base.name + "-" + work.name + "-stream.jsonl")
    tools_copy = base.parent.parent / ("T5-models-" + base.name + "-" + work.name + "-tools.jsonl")
    shutil.copyfile(stream, stream_copy)
    if mcp_receipt.exists():
        shutil.copyfile(mcp_receipt, tools_copy)
    return {"task": task["id"], "requestedModel": model, "observedModels": actual_models, "modelMatch": model_match,
        "manual": manual, "manualLoaded": manual_loaded, "manualRun": manual_run, "guardedWriteObserved": bool(guarded),
        "success": state_ok and bool(guarded) and model_match and exit_code == 0 and not final.get("is_error") and (manual_loaded if manual else True),
        "stateVerified": state_ok, "elapsedSeconds": elapsed, "exitCode": exit_code, "error": error or final.get("errors"),
        "usage": usage, "modelUsage": model_usage, "totalTokensIncludingCache": total_tokens,
        "toolCalls": len(tool_receipts), "toolReceipt": str(tools_copy.relative_to(ROOT)), "streamReceipt": str(stream_copy.relative_to(ROOT)),
        "streamSha256": hashlib.sha256(stream.read_bytes()).hexdigest(), "observed": observed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve-mcp", action="store_true")
    parser.add_argument("--manual", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--tool-receipt", type=Path)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--output", type=Path, default=ROOT / "scripts/evidence/T5-models.json")
    parser.add_argument("--tasks", type=int, default=2, choices=(1, 2))
    options = parser.parse_args()
    if options.serve_mcp:
        for stream in (sys.stdin, sys.stdout):
            stream.reconfigure(encoding="utf-8")
        serve(options.root, options.manual, options.tool_receipt)
        return 0
    base = ROOT / "scripts/evidence/T5-models-runs" / uuid.uuid4().hex
    receipt = {"schema": "neyvia.t5-model-comparison.v1", "startedAt": utc(), "route": "Claude CLI first-party; production CompactNeyviaMCPServer stdio",
        "protocol": "Matched scratch Notes states; Haiku has actual grounded manual; Opus manual tools blocked; identical remaining gateway/tools; built-in tools disabled; medium effort; no model fallback",
        "limitations": ["At most two small Notes tasks, one trial per arm; cannot establish general reliability or savings", "Total tokens includes cache creation/read; billing cost is reported separately when CLI provides it", "Elapsed seconds includes CLI/MCP startup and network latency; cache warmth is provider controlled"], "trials": []}
    for task in TASKS[:options.tasks]:
        for model, manual in (("haiku", True), ("opus", False)):
            row = trial(base, model, manual, task, options.timeout)
            receipt["trials"].append(row)
            options.output.parent.mkdir(parents=True, exist_ok=True)
            options.output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(json.dumps({key: row[key] for key in ("task", "requestedModel", "success", "elapsedSeconds", "totalTokensIncludingCache", "error")}), flush=True)
    receipt["finishedAt"] = utc()
    receipt["allSucceeded"] = all(row["success"] for row in receipt["trials"])
    totals = {model: sum(row["totalTokensIncludingCache"] for row in receipt["trials"] if row["requestedModel"] == model) for model in ("haiku", "opus")}
    receipt["totalTokensIncludingCache"] = totals
    receipt["aggregate"] = {model: {
        "successes": sum(row["success"] for row in receipt["trials"] if row["requestedModel"] == model),
        "trials": sum(row["requestedModel"] == model for row in receipt["trials"]),
        "elapsedSeconds": round(sum(row["elapsedSeconds"] for row in receipt["trials"] if row["requestedModel"] == model), 3),
        "listPriceCostUsd": round(sum(usage.get("costUSD", 0) for row in receipt["trials"] if row["requestedModel"] == model for usage in row["modelUsage"].values()), 6)
    } for model in ("haiku", "opus")}
    receipt["haikuTokenSavingsFraction"] = round(1 - totals["haiku"] / totals["opus"], 6) if totals["opus"] else None
    options.output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if receipt["allSucceeded"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
