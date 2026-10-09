"""Process-local CUA registration; never changes a user's CLI settings."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse


def server_spec(chat_id, app, title=""):
    url = os.environ.get("NEYVIA_UI_BACKEND_URL", "")
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.port not in (*range(48171, 48180), *range(48701, 48710), *range(48751, 48760), *range(49031, 49040)):
        return None
    source = Path(__file__).resolve().parents[1]
    if os.name == "nt":
        from .cua_native import NativeWorker
        command, args = str(NativeWorker.stdio_host()), [sys.executable]
    else:
        command, args = sys.executable, ["-B", "-m", "grant_agent.neyvia_cua_mcp"]
    return {"command": command, "args": args,
            "env": {"PYTHONPATH": str(source), "NEYVIA_UI_BACKEND_URL": url, "NEYVIA_CHAT_ID": str(chat_id), "NEYVIA_APP": app, "NEYVIA_CHAT_TITLE": title[:120]}}


def claude_args(chat_id, title=""):
    spec = server_spec(chat_id, "claude", title)
    return ["--mcp-config", json.dumps({"mcpServers": {"neyvia-cua": spec}}, ensure_ascii=True)] if spec else []


def codex_config(chat_id, app="codex"):
    spec = server_spec(chat_id, app)
    return {"mcp_servers.neyvia-cua": {**spec, "enabled": True, "startup_timeout_sec": 30, "tool_timeout_sec": 610}} if spec else {}
