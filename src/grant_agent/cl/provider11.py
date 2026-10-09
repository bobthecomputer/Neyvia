"""CL 1.1 provider transport: explicit routes, raw events, bounded native sessions."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from grant_agent.autopilot_model import _command, _stop, _sanitize
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
from .benchmark_provider import propose

MODELS = ("gpt-6-luna", "gpt-6.1-sol")


def usage_counts(usage: dict | None, provider="codex") -> dict:
    """Input includes cache; total never adds cached input a second time."""
    value = usage or {}
    cached = int(value.get("cached_input_tokens", value.get("cache_read_input_tokens", 0)) or 0)
    creation = int(value.get("cache_creation_input_tokens", 0) or 0)
    reported_input = int(value.get("input_tokens", 0) or 0)
    total_input = reported_input + cached + creation if provider == "claude" else reported_input
    output = int(value.get("output_tokens", 0) or 0)
    return {"input": total_input, "cachedInput": cached, "cacheCreation": creation,
            "uncachedInput": max(0, total_input - cached - creation),
            "output": output, "total": total_input + output}


def proposal(prompt: str, model: str, directory: Path) -> dict:
    if model not in MODELS:
        raise ValueError("An exact benchmark model route is required")
    return propose(prompt, model, directory)


def _claude_command() -> list[str]:
    executable = shutil.which("claude")
    if not executable:
        raise RuntimeError("Claude Code CLI unavailable")
    if Path(executable).suffix.lower() in {".cmd", ".ps1", ".bat"}:
        native_executable = Path(executable).parent / "node_modules/@anthropic-ai/claude-code/bin/claude.exe"
        if native_executable.is_file():
            return [str(native_executable)]
        node = shutil.which("node")
        entry = Path(executable).parent / "node_modules/@anthropic-ai/claude-code/cli.js"
        if not node or not entry.is_file():
            raise RuntimeError("Claude Code npm entry unavailable")
        return [node, str(entry)]
    return [executable]


def native(prompt: str, harness: str, directory: Path, *, fixture_root: Path,
           image: Path | None = None, browser_url: str | None = None,
           timeout: int = 240, claude_budget: float = .25) -> dict:
    """Actual native shell/file/image tools; optional raw Playwright MCP, no CL."""
    if harness not in {"codex-alone", "claude-alone"}:
        raise ValueError("Unknown native harness")
    directory.mkdir(parents=True, exist_ok=True)
    fixture_root = fixture_root.resolve()
    model = "gpt-6-luna" if harness == "codex-alone" else "haiku"
    answer_path = directory / "answer.txt"
    image_source = ({'path': str(image.resolve()), 'sha256': hashlib.sha256(image.read_bytes()).hexdigest()}
                    if image else None)
    mcp = None
    if browser_url:
        repo = Path(__file__).resolve().parents[3]
        script = repo / "scripts/cl11_playwright_mcp.py"
        python = Path("C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe")
        mcp = {"command": str(python), "args": [str(script), "--url", browser_url,
                                                       "--root", str(fixture_root)]}
    if harness == "codex-alone":
        args = [*_command(), "exec", "--json", "--ephemeral", "--ignore-user-config",
                "--ignore-rules", "--skip-git-repo-check", "--sandbox", "workspace-write",
                "--model", model, "--cd", str(fixture_root), "--color", "never",
                "-c", "project_doc_max_bytes=0", "-c", 'model_reasoning_effort="low"',
                "-c", 'web_search="disabled"', "--enable", "skip_host_skill_discovery",
                "--disable", "memories", "--disable", "hooks", "--disable", "plugins",
                "--disable", "apps", "--disable", "multi_agent", "--disable", "multi_agent_v2",
                "--output-last-message", str(answer_path.resolve())]
        if mcp:
            args += ["-c", "mcp_servers.playwright.command=" + json.dumps(mcp["command"]),
                     "-c", "mcp_servers.playwright.args=" + json.dumps(mcp["args"])]
        if image:
            args += ["--image", str(image.resolve())]
        args += ["-"]
    else:
        args = [*_claude_command(), "-p", "--model", model, "--effort", "low",
                "--output-format", "stream-json", "--verbose", "--no-session-persistence",
                "--setting-sources", "", "--strict-mcp-config", "--no-chrome",
                "--settings", json.dumps({'disableAllHooks': True, 'enabledPlugins': {}}),
                "--tools", "Bash,PowerShell,Read,Write,Edit,Glob,Grep",
                "--disable-slash-commands", "--permission-mode", "acceptEdits",
                "--allowedTools", "Bash,PowerShell,Read,Write,Edit,Glob,Grep,mcp__playwright__*",
                "--max-budget-usd", str(claude_budget)]
        if mcp:
            args += ["--mcp-config", json.dumps({"mcpServers": {"playwright": mcp}})]
        if image:
            prompt += "\nAttached image path: " + str(image.resolve())
    (directory / "prompt.txt").write_text(prompt, encoding="utf-8")
    started = time.monotonic()
    timed_out = False
    with (directory / "events.jsonl").open("wb") as out, (directory / "stderr.txt").open("wb") as err:
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                   cwd=fixture_root, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                                                        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "1500"},
                                   **hidden_windows_subprocess_kwargs())
        try:
            process.communicate(prompt.encode(), timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _stop(process)
    events, actions, errors = [], [], []
    image_reads, image_results = {}, set()
    usage, answer, returned_models = None, "", []
    for line in (directory / "events.jsonl").read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        events.append(event)
        if event.get("type") == "turn.completed":
            usage = event.get("usage")
        item = event.get("item", {})
        if item.get("type") in {"command_execution", "mcp_tool_call", "file_change"} and event.get("type") == "item.completed":
            actions.append(item)
        if event.get("type") == "assistant":
            message = event.get("message", {})
            if message.get("model"):
                returned_models.append(message["model"])
            for block in message.get("content", []):
                if block.get("type") == "tool_use":
                    actions.append(block)
                    if block.get('name') == 'Read':
                        image_reads[block['id']] = block.get('input', {}).get('file_path')
        if event.get('type') == 'user':
            for block in event.get('message', {}).get('content', []):
                if block.get('type') == 'tool_result' and not block.get('is_error'):
                    content = block.get('content', [])
                    if isinstance(content, list) and any(part.get('type') == 'image' for part in content if isinstance(part, dict)):
                        image_results.add(block.get('tool_use_id'))
        if event.get("type") == "result":
            usage, answer = event.get("usage"), event.get("result", "")
            if event.get("is_error"):
                errors.append(event.get("subtype", "provider error"))
        if event.get("type") in {"error", "turn.failed"}:
            errors.append(_sanitize(event.get("message") or event.get("error")))
    if answer_path.exists():
        answer = answer_path.read_text(encoding="utf-8")
    if timed_out:
        errors.append("Native session deadline exceeded")
    image_evidence = []
    if image_source and image.is_file() and hashlib.sha256(image.read_bytes()).hexdigest() == image_source['sha256']:
        if harness == 'codex-alone':
            image_evidence.append({**image_source, 'transport': 'cli-attachment'})
        else:
            for identity in image_results:
                path = image_reads.get(identity)
                if path and Path(path).resolve() == image.resolve():
                    image_evidence.append({**image_source, 'transport': 'successful-Read-image-result', 'toolUseId': identity})
    receipt = {"harness": harness, "requestedModel": model, "returnedModels": sorted(set(returned_models)),
               'invocation': args,
               "identityEvidence": "Explicit CLI route, no fallback; deployed weights are not independently attested",
               "exitCode": process.returncode, "passed": process.returncode == 0 and usage is not None and not errors,
               "usage": usage, "tokens": usage_counts(usage, "claude" if harness == "claude-alone" else "codex"),
               "latencyMs": round((time.monotonic() - started) * 1000), "actions": actions,
               "imageEvidence": image_evidence,
               "answer": answer, "errors": errors, "promptSha256": hashlib.sha256(prompt.encode()).hexdigest(),
               "stderr": _sanitize((directory / "stderr.txt").read_text(encoding="utf-8", errors="replace")[-3000:])}
    (directory / "receipt.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
    return receipt
