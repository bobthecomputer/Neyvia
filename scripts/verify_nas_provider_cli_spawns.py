#!/usr/bin/env python3
"""Run bounded, real spawn probes for Neyvia's native runtime and provider CLIs."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import time
from pathlib import Path
from typing import Any

from configure_nas_provider_auth_broker import (
    CORE_RUNTIME,
    PROXY_RUNTIME,
    _connect,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = "/volume1/Saclay/projects/vibe-coding-platform"
MANAGED_PYTHON = f"{CORE_RUNTIME}/bin/python"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _visible_model_text(output: str) -> str:
    parts: list[str] = []
    for line in output.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("type") or "").lower() == "text":
            value = payload.get("data") or payload.get("text")
            if isinstance(value, str):
                parts.append(value)
        part = payload.get("part")
        if isinstance(part, dict) and str(part.get("type") or "").lower() == "text":
            value = part.get("text")
            if isinstance(value, str):
                parts.append(value)
    return "".join(parts)


def _prefix(workspace: str) -> str:
    return (
        f"export HOME={shlex.quote(CORE_RUNTIME + '/home')}; "
        f"export PATH={shlex.quote(CORE_RUNTIME + '/bin')}:{shlex.quote(PROXY_RUNTIME + '/bin')}:/usr/local/bin:/usr/bin:/bin; "
        f"set -a; . {shlex.quote(PROXY_RUNTIME + '/home/.fluxio_cliproxy_env')}; set +a; "
        f"cd {shlex.quote(workspace)}; "
    )


def _run(
    client: Any,
    name: str,
    command: str,
    marker: str,
    *,
    timeout: int = 210,
    evidence: tuple[str, ...] = (),
) -> dict[str, Any]:
    started = time.monotonic()
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout + 20)
    output = stdout.read().decode("utf-8", "replace")
    error = stderr.read().decode("utf-8", "replace")
    exit_code = stdout.channel.recv_exit_status()
    combined = ANSI.sub("", f"{output}\n{error}")
    model_text = _visible_model_text(combined)
    evidence_seen = {item: item in combined for item in evidence}
    marker_seen = marker in combined or marker in model_text
    passed = exit_code == 0 and marker_seen and all(evidence_seen.values())
    return {
        "name": name,
        "passed": passed,
        "exitCode": exit_code,
        "elapsedSeconds": round(time.monotonic() - started, 2),
        "marker": marker,
        "markerSeen": marker_seen,
        "evidence": evidence_seen,
        "outputTail": combined[-6000:],
    }


def _codex_command(prefix: str) -> str:
    quote = '"'
    configs = [
        f"model_provider={quote}neyvia_cliproxy{quote}",
        f"model_providers.neyvia_cliproxy.name={quote}Neyvia CLIProxyAPI{quote}",
        f"model_providers.neyvia_cliproxy.base_url={quote}http://127.0.0.1:8317/v1{quote}",
        f"model_providers.neyvia_cliproxy.env_key={quote}CLIPROXY_API_KEY{quote}",
        f"model_providers.neyvia_cliproxy.wire_api={quote}responses{quote}",
        "model_providers.neyvia_cliproxy.requires_openai_auth=false",
    ]
    args = ["codex"]
    for config in configs:
        args.extend(["-c", config])
    args.extend(
        [
            "exec",
            "--model",
            "gpt-5.6-sol",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--json",
            "Reply exactly CODEX_BROKER_CONNECTED",
        ]
    )
    return (
        prefix
        + f"export CODEX_HOME={shlex.quote(CORE_RUNTIME + '/home/.codex-proxy')}; "
        + f"mkdir -p {shlex.quote(CORE_RUNTIME + '/home/.codex-proxy')}; "
        + "timeout 180 "
        + shlex.join(args)
        + " < /dev/null 2>&1"
    )


def _opencode_command(prefix: str) -> str:
    config = {
        "provider": {
            "neyvia-cliproxy": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Neyvia CLIProxyAPI",
                "options": {
                    "baseURL": "http://127.0.0.1:8317/v1",
                    "apiKey": "{env:OPENCODE_NEYVIA_API_KEY}",
                },
                "models": {
                    "gpt-5.6-sol": {
                        "name": "gpt-5.6-sol via Neyvia gateway",
                    }
                },
            }
        }
    }
    return (
        prefix
        + "export OPENCODE_NEYVIA_API_KEY=$CLIPROXY_API_KEY; "
        + f"export OPENCODE_CONFIG_CONTENT={shlex.quote(json.dumps(config, separators=(',', ':')))}; "
        + "timeout 180 opencode run --format json "
        + "--model neyvia-cliproxy/gpt-5.6-sol "
        + shlex.quote("Reply exactly OPENCODE_BROKER_CONNECTED")
        + " < /dev/null 2>&1"
    )


def run_acceptance(workspace: str) -> dict[str, Any]:
    client = _connect()
    prefix = _prefix(workspace)
    try:
        python_preflight = _run(
            client,
            "neyvia-managed-python-preflight",
            prefix
            + f"test -x {shlex.quote(MANAGED_PYTHON)} && "
            + f"{shlex.quote(MANAGED_PYTHON)} -c "
            + shlex.quote(
                "import json, sys; "
                "print(json.dumps({'marker':'NEYVIA_MANAGED_PYTHON_READY',"
                "'executable':sys.executable,'version':list(sys.version_info[:3])}))"
            ),
            "NEYVIA_MANAGED_PYTHON_READY",
            timeout=30,
        )
        if not python_preflight["passed"]:
            return {
                "schema": "neyvia.nas-provider-cli-spawns/v1",
                "generatedAt": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                ),
                "workspace": workspace,
                "managedPython": python_preflight,
                "passed": False,
                "passedCount": 0,
                "requiredCount": 8,
                "probes": [],
                "separateProviderOrInstall": [],
            }
        probes = [
            _run(
                client,
                "neyvia-own-runtime",
                prefix
                + f"export PYTHONPATH={shlex.quote(workspace + '/src')}; "
                + f"timeout 90 {shlex.quote(MANAGED_PYTHON)} -c "
                + shlex.quote(
                    "import json; from pathlib import Path; "
                    "from grant_agent.native_tools import NativeToolRegistry; "
                    "r=NativeToolRegistry(Path('.')); "
                    "x=r.call('workspace.search', {'query':'Neyvia','maxResults':5}); "
                    "print(json.dumps({'marker':'OWN_RUNTIME_CONNECTED','ok':x.get('ok'),"
                    "'runtimeId':'neyvia-native-tools','receiptPath':x.get('receipt_path')})); "
                    "raise SystemExit(0 if x.get('ok') else 1)"
                ),
                "OWN_RUNTIME_CONNECTED",
                timeout=120,
                evidence=('"ok": true',),
            ),
            _run(
                client,
                "codex",
                _codex_command(prefix),
                "CODEX_BROKER_CONNECTED",
            ),
            _run(
                client,
                "hermes",
                prefix
                + "timeout 150 hermes chat --provider openai-api --model gpt-5.6-sol "
                + "--query "
                + shlex.quote("Reply exactly HERMES_BROKER_CONNECTED")
                + " --quiet --max-turns 2 --ignore-rules 2>&1",
                "HERMES_BROKER_CONNECTED",
                timeout=180,
            ),
            _run(
                client,
                "openclaw",
                prefix
                + "openclaw agents add neyvia-broker-proof "
                + f"--workspace {shlex.quote(workspace)} "
                + "--model neyvia-openai/gpt-5.6-sol --non-interactive --json "
                + ">/tmp/neyvia-openclaw-add.json 2>/tmp/neyvia-openclaw-add.err || true; "
                + "timeout 180 openclaw agent --agent neyvia-broker-proof "
                + "--session-id neyvia-broker-acceptance --message "
                + shlex.quote("Reply exactly OPENCLAW_BROKER_CONNECTED")
                + " --thinking low --json --local 2>&1",
                "OPENCLAW_BROKER_CONNECTED",
                evidence=('"provider": "neyvia-openai"', '"fallbackUsed": false'),
            ),
            _run(
                client,
                "claude-code-subagent",
                prefix
                + "timeout 180 claude --print "
                + shlex.quote(
                    "You must use the Agent tool exactly once to spawn a subagent. "
                    "Ask that subagent to reply exactly CC_CHILD_CONNECTED. After "
                    "the subagent returns, reply exactly CC_PARENT_CONNECTED. "
                    "Do not merely describe the tool call."
                )
                + " --output-format stream-json --verbose --model gpt-5.6-sol "
                + "--permission-mode acceptEdits --forward-subagent-text "
                + "--allowedTools Agent --max-turns 4 < /dev/null 2>&1",
                "CC_PARENT_CONNECTED",
                evidence=(
                    '"name":"Agent"',
                    '"subtype":"task_started"',
                    "CC_CHILD_CONNECTED",
                ),
            ),
            _run(
                client,
                "kimi-code",
                prefix
                + "export KIMI_MODEL_NAME=gpt-5.6-sol; "
                + "export KIMI_MODEL_API_KEY=$CLIPROXY_API_KEY; "
                + "export KIMI_MODEL_PROVIDER_TYPE=openai; "
                + "export KIMI_MODEL_BASE_URL=http://127.0.0.1:8317/v1; "
                + "export KIMI_MODEL_DISPLAY_NAME=Neyvia-OpenAI-Broker; "
                + "export KIMI_DISABLE_TELEMETRY=1; "
                + "timeout 150 kimi --prompt "
                + shlex.quote("Reply exactly KIMI_BROKER_CONNECTED")
                + " --output-format stream-json < /dev/null 2>&1",
                "KIMI_BROKER_CONNECTED",
                timeout=180,
            ),
            _run(
                client,
                "grok-build",
                prefix
                + "export XAI_API_KEY=$CLIPROXY_API_KEY; "
                + "export GROK_MODELS_BASE_URL=http://127.0.0.1:8317/v1; "
                + "timeout 150 grok --no-auto-update --model gpt-5.6-sol "
                + "--single "
                + shlex.quote("Reply exactly GROK_BROKER_CONNECTED")
                + " --output-format streaming-json < /dev/null 2>&1",
                "GROK_BROKER_CONNECTED",
                timeout=180,
            ),
            _run(
                client,
                "opencode",
                _opencode_command(prefix),
                "OPENCODE_BROKER_CONNECTED",
            ),
        ]
        cursor = _run(
            client,
            "cursor",
            prefix
            + "if command -v cursor-agent >/dev/null 2>&1; then "
            + "cursor-agent --version; echo CURSOR_PROCESS_SPAWNED; "
            + "elif command -v cursor >/dev/null 2>&1; then "
            + "cursor --version; echo CURSOR_PROCESS_SPAWNED; "
            + "else echo CURSOR_NOT_INSTALLED; exit 3; fi",
            "CURSOR_PROCESS_SPAWNED",
            timeout=60,
        )
    finally:
        client.close()
    passed = sum(1 for probe in probes if probe["passed"])
    return {
        "schema": "neyvia.nas-provider-cli-spawns/v1",
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "workspace": workspace,
        "managedPython": python_preflight,
        "providerLogin": {
            "provider": "openai",
            "authMode": "codex-oauth",
            "refreshOwner": "cliproxyapi",
        },
        "passed": passed == len(probes),
        "passedCount": passed,
        "requiredCount": len(probes),
        "probes": probes,
        "separateProviderOrInstall": [cursor],
        "claim": (
            "A CLI counts as connected only when its real process returns the "
            "expected model marker. Cursor remains separate because Codex OAuth "
            "does not authenticate Cursor."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    report = run_acceptance(args.workspace)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        target = args.report.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
