"""Frozen closed-book CLI transport: physical tool-surface exclusion plus audit."""
from __future__ import annotations
import hashlib
import json
import shutil
import subprocess
import time
import uuid

from .evolver_domains import Luna, MODEL, ModelFailure

DISABLED_FEATURES = ["apps", "plugins", "remote_plugin", "plugin_sharing", "browser_use",
    "browser_use_external", "browser_use_full_cdp_access", "computer_use", "image_generation",
    "in_app_browser", "in_app_chat", "in_app_dictation", "in_app_local_automation", "in_app_updates",
    "shell_tool", "unified_exec_tty", "multi_agent", "multi_agent_v2", "skill_search",
    "skill_mcp_dependency_install", "sleep_tool", "tool_suggest", "view_image", "deferred_executor",
    "executor_capability_discovery", "guardian_conversation_history_tools", "agent_message_board",
    "external_agent_memory_import", "standalone_web_search", "tool_call_mcp_elicitation", "enable_mcp_apps"]


class ClosedBookLuna(Luna):
    def ask(self, prompt, *, label, schema=None):
        run_id = uuid.uuid4().hex
        stem = self.raw / f"{label}-{run_id}"
        executable = shutil.which("codex.cmd") or shutil.which("codex")
        if not executable:
            raise ModelFailure("Codex CLI unavailable; no substitute model is permitted")
        command = [executable, "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
                   "--skip-git-repo-check", "--sandbox", "read-only", "--json", "--cd", str(self.sandbox),
                   "--model", MODEL, "-c", 'model_reasoning_effort="low"', "-c", 'web_search="disabled"',
                   "-c", "mcp_servers={}", "-c", "features.skip_host_skill_discovery=true"]
        for feature in DISABLED_FEATURES:
            command += ["--disable", feature]
        if schema:
            schema = json.loads(json.dumps(schema))
            if "id" in schema.get("properties", {}) and "\nTASK\n" in prompt:
                task = json.loads(prompt.rsplit("\nTASK\n", 1)[1])
                schema["properties"]["id"] = {"type": "string", "const": task["id"]}
            schema_path = stem.with_suffix(".schema.json")
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            command += ["--output-schema", str(schema_path)]
        command.append("-")
        stem.with_suffix(".prompt.txt").write_text(prompt, encoding="utf-8")
        started = time.time()
        try:
            result = subprocess.run(command, input=prompt, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=240,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
            stem.with_suffix(".stdout.jsonl").write_text(output, encoding="utf-8")
            stem.with_suffix(".failure.json").write_text(json.dumps({"model": MODEL, "status": "timeout", "seconds": 240}), encoding="utf-8")
            raise ModelFailure(f"Luna timeout; preserved {stem}") from exc
        stem.with_suffix(".stdout.jsonl").write_text(result.stdout, encoding="utf-8")
        stem.with_suffix(".stderr.txt").write_text(result.stderr, encoding="utf-8")
        events = []
        for line in result.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        messages = [e["item"]["text"] for e in events if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "agent_message"]
        unexpected = [e for e in events if e.get("item", {}).get("type") not in {None, "agent_message", "reasoning", "error"}]
        configuration_errors = [e["item"].get("message", "") for e in events if e.get("item", {}).get("type") == "error" and "unrecognized configuration" in e["item"].get("message", "")]
        usage = next((e.get("usage") for e in reversed(events) if e.get("type") == "turn.completed"), None)
        receipt = {"id": run_id, "model": MODEL, "command": command, "exitCode": result.returncode,
                   "threadId": next((e.get("thread_id") for e in events if e.get("type") == "thread.started"), None),
                   "usage": usage, "seconds": round(time.time() - started, 3), "raw": str(stem.with_suffix(".stdout.jsonl")),
                   "providerSamplingSeed": None, "seedBoundary": "Paired case and order seeds; provider sampling is not seedable through CLI",
                   "toolBoundary": "Closed-book-v3: apps/plugins/browser/computer/shell/agents/host skills physically disabled; any tool event rejects",
                   "disabledFeatures": DISABLED_FEATURES, "unexpectedToolEvents": [e.get("item", {}).get("type") for e in unexpected],
                   "platformNote": "Windows pins unified_exec implementation true; shell_tool interface is disabled and every tool event is rejected",
                   "promptSha256": hashlib.sha256(prompt.encode()).hexdigest(),
                   "schemaSha256": hashlib.sha256(json.dumps(schema).encode()).hexdigest() if schema else None}
        stem.with_suffix(".receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        if result.returncode or not messages or not usage or unexpected or configuration_errors:
            raise ModelFailure(f"Closed-book Luna call rejected; raw receipt {receipt['raw']}")
        try:
            return json.loads(messages[-1]), receipt
        except json.JSONDecodeError as exc:
            raise ModelFailure(f"Luna returned invalid JSON; raw receipt {receipt['raw']}") from exc
