"""OpenCode's supported ACP transport, with owner-only permission decisions."""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import unquote

from .codex_rpc import AppServerConnection
from .broker import ConnectedError
from .transparency import bounded_text, normalize_item, reasoning_data

MODES = ["read-only", "workspace", "full-access"]


def command():
    found = shutil.which("opencode.exe") or shutil.which("opencode") or shutil.which("opencode.cmd")
    if found and found.lower().endswith(".cmd"):
        native = Path(found).parent / "node_modules/opencode-ai/bin/opencode.exe"
        return str(native) if native.is_file() else None
    return found


def environment(mode):
    env = dict(os.environ)
    config = json.loads(env.get("OPENCODE_CONFIG_CONTENT") or "{}")
    config.update(autoupdate=False, permission={"*": "deny" if mode == "read-only" else "ask",
                                               "read": "allow", "glob": "allow", "grep": "allow", "list": "allow"})
    env.update(OPENCODE_DISABLE_AUTOUPDATE="true", OPENCODE_CONFIG_CONTENT=json.dumps(config))
    return env


class AcpTurn:
    def __init__(self, cli, cwd, options, run_id, emit, *, mcp_servers=None):
        self.cwd, self.options, self.run_id, self.emit = cwd, options, run_id, emit
        self.sid, self.seq, self.pending = None, 0, {}
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.loading = False
        self.mcp_servers = list(mcp_servers or [])
        self.items, self.stream = {}, None
        self.tool_started = {}
        self.rpc = AppServerConnection(lambda: [*( [cli] if isinstance(cli, str) else cli), "acp", "--cwd", cwd],
            on_notification=self.update, on_server_request=self.request,
            initialize_params={"protocolVersion": 1, "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
                               "clientInfo": {"name": "neyvia", "version": "1"}},
            initialized_notification=False, jsonrpc=True, environment=environment(options.permission_mode or "read-only"))

    def item(self, kind, data, identity=None):
        key = self.run_id + ":" + identity if identity else None
        old = self.items.get(key)
        if old:
            item = {**old, "data": {**old["data"], **data}}
        else:
            self.seq += 1
            item = {"id": key or f"{self.run_id}:{self.seq}", "seq": self.seq, "kind": kind, "data": data}
        normalize_item("opencode", kind, item["data"])
        self.items[item["id"]] = item
        self.emit({"type": "item.updated" if old else "item.added", "sessionId": self.sid, "item": item})
        return item["id"]

    def update(self, generation, method, params):
        if method != "session/update" or self.loading:
            return
        update = params.get("update") or {}
        kind = update.get("sessionUpdate")
        if kind in {"agent_message_chunk", "agent_thought_chunk"}:
            content = update.get("content") or {}
            if content.get("type") == "text":
                item_kind = "assistant" if kind == "agent_message_chunk" else "reasoning"
                text = content.get("text", "")
                if self.stream and self.stream[0] == item_kind:
                    identity = self.stream[1]
                    data = self.items[identity]["data"]
                    field = "text" if item_kind == "assistant" else "summary"
                    data[field], data["truncated"] = bounded_text(data.get(field, "") + text)
                    if item_kind == "assistant":
                        self.emit({"type": "item.delta", "sessionId": self.sid, "itemId": identity, "textDelta": text})
                    else:
                        data.update(hidden=False, exposure="thinking", notice=None)
                        self.emit({"type": "item.updated", "sessionId": self.sid, "item": self.items[identity]})
                else:
                    data = {"text": text, "attachments": []} if item_kind == "assistant" else reasoning_data("opencode", text, source="acp")
                    self.stream = (item_kind, self.item(item_kind, data))
        elif kind in {"tool_call", "tool_call_update"}:
            self.stream = None
            status = {"completed": "ok", "failed": "error"}.get(update.get("status"), "running")
            tool_id = update.get("toolCallId")
            self.tool_started.setdefault(tool_id, time.monotonic())
            data = {}
            if "kind" in update:
                data["category"] = {"execute": "command", "edit": "edit", "read": "read", "search": "search", "fetch": "web"}.get(update.get("kind"), "other")
            if "locations" in update:
                data["files"] = [row["path"] for row in update.get("locations") or [] if row.get("path")]
            if "status" in update:
                data["status"] = status
            if "title" in update:
                data.update(name=update["title"], title=update["title"])
            if "rawInput" in update:
                raw = update["rawInput"]
                data["args"], data["inputTruncated"] = bounded_text(raw)
                data["input"] = data["args"]
                if isinstance(raw, dict) and isinstance(raw.get("command"), str):
                    data["command"], data["inputTruncated"] = bounded_text(raw["command"])
                    data.update(input=data["command"], category="command")
            if "content" in update:
                texts = [str((row.get("content") or {}).get("text") or "") for row in update["content"] if row.get("type") == "content"]
                data["output"], data["outputTruncated"] = bounded_text("\n".join(texts) if texts else update["content"])
            if "rawOutput" in update:
                raw_output = update["rawOutput"]
                data["result"], data["resultTruncated"] = bounded_text(raw_output)
                if isinstance(raw_output, dict):
                    metadata = raw_output.get("metadata") or raw_output
                    exit_code = metadata.get("exit", metadata.get("exitCode"))
                    if isinstance(exit_code, int):
                        data["exitCode"] = exit_code
            if status in {"ok", "error"}:
                data.update(durationMs=round((time.monotonic() - self.tool_started[tool_id]) * 1000), durationSource="transport-observed")
            self.item("tool", data, tool_id)
            for content in update.get("content") or []:
                if content.get("type") == "diff":
                    import difflib
                    patch = "".join(difflib.unified_diff(str(content.get("oldText") or "").splitlines(True),
                        str(content.get("newText") or "").splitlines(True), fromfile=content.get("path") or "before", tofile=content.get("path") or "after"))
                    bounded, truncated = bounded_text(patch)
                    self.item("diff", {"files": [{"path": content.get("path")}], "patch": bounded,
                                       "truncated": truncated, "source": "acp"}, str(tool_id) + ":diff:" + str(content.get("path")))
        elif kind == "usage_update":
            self.emit({"type": "context.updated", "sessionId": self.sid,
                       "context": {"used_tokens": update.get("used"), "window_tokens": update.get("size"), "source": "OpenCode ACP context"}})

    def forbidden(self, call):
        from ..neyvia_workspace_tools import WorkspaceTools
        for location in call.get("locations") or []:
            if location.get("path"):
                try:
                    path = Path(location["path"])
                    WorkspaceTools.safe_path(path if path.is_absolute() else Path(self.cwd) / path)
                except ValueError:
                    return True
        raw = call.get("rawInput") or {}
        for field in ("filePath", "path", "directory"):
            if isinstance(raw.get(field), str):
                try:
                    path = Path(raw[field])
                    WorkspaceTools.safe_path(path if path.is_absolute() else Path(self.cwd) / path)
                except ValueError:
                    return True
        text = json.dumps(raw).replace("\\\\", "/").casefold()
        return "c:/users/user/projects/neyvia/" in text or '"c:/users/user/projects/neyvia"' in text

    def request(self, generation, identity, method, params):
        if method != "session/request_permission":
            self.rpc.reject(generation, identity, "Unsupported ACP client operation")
            return
        call = params.get("toolCall") or {}
        cached = self.items.get(self.run_id + ":" + str(call.get("toolCallId")), {}).get("data", {})
        if "rawInput" not in call and cached.get("input"):
            try:
                call = {**call, "rawInput": json.loads(cached["input"])}
            except ValueError:
                pass
        call = {"title": cached.get("title"), **call}
        choices = {row["kind"]: row["optionId"] for row in params.get("options") or []}
        if self.cancelled.is_set() or self.options.permission_mode in {None, "read-only"} or self.forbidden(call):
            self.rpc.respond(generation, identity, {"outcome": {"outcome": "cancelled"}})
            return
        key = str(identity)
        with self.lock:
            self.pending[key] = (generation, identity, choices)
        pending = {"requestId": key, "title": call.get("title") or "OpenCode permission", "detail": json.dumps(call.get("rawInput") or {})[:8000],
                   "cwd": self.cwd, "choices": [decision for decision, kind in (("approve", "allow_once"), ("deny", "reject_once")) if kind in choices]}
        self.item("approval", pending)
        self.emit({"type": "run.state", "sessionId": self.sid, "runId": self.run_id, "state": "waiting_approval", "pendingRequest": pending})

    def answer(self, key, response):
        with self.lock:
            entry = self.pending.get(key)
            if not entry:
                raise ConnectedError("stale_request", "That OpenCode permission is no longer pending", 409)
            generation, identity, choices = entry
            kind = {"approve": "allow_once", "deny": "reject_once"}.get(response.get("decision"))
            if kind and kind not in choices:
                raise ConnectedError("invalid_response", "That OpenCode decision is unavailable", 400)
            result = {"outcome": "selected", "optionId": choices[kind]} if kind else {"outcome": "cancelled"}
            self.rpc.respond(generation, identity, {"outcome": result})
            self.pending.pop(key)
        self.emit({"type": "run.state", "sessionId": self.sid, "runId": self.run_id, "state": "running"})

    def interrupt(self):
        self.cancelled.set()
        with self.lock:
            keys = list(self.pending)
        for key in keys:
            self.answer(key, {"decision": "cancel"})
        if self.sid and self.rpc.alive:
            self.rpc.notify("session/cancel", {"sessionId": self.sid})
        timer = threading.Timer(5, self.rpc.kill)
        timer.daemon = True
        timer.start()

    def run(self, session_id, message):
        self.rpc.ensure_started()
        if self.cancelled.is_set():
            raise ConnectedError("cancelled", "OpenCode turn cancelled before submission", 409)
        if session_id:
            self.sid = unquote(session_id.split(":", 3)[-1])
            capabilities = self.rpc.server_info.get("agentCapabilities") or {}
            method = "session/resume" if "resume" in (capabilities.get("sessionCapabilities") or {}) else "session/load"
            self.loading = True
            try:
                setup = self.rpc.request(method, {"sessionId": self.sid, "cwd": self.cwd, "mcpServers": self.mcp_servers})
            finally:
                self.loading = False
        else:
            setup = self.rpc.request("session/new", {"cwd": self.cwd, "mcpServers": self.mcp_servers})
            self.sid = setup["sessionId"]
        self.emit({"type": "session.updated", "sessionId": self.sid})
        configs = {row["id"]: row for row in setup.get("configOptions") or []}
        requested = {"mode": "plan" if self.options.permission_mode in {None, "read-only"} else "build"}
        if self.options.model:
            requested["model"] = self.options.model
        for key, value in requested.items():
            config = configs.get(key) or {}
            if value not in {row.get("value") for row in config.get("options") or []}:
                raise ConnectedError("invalid_option", f"OpenCode does not expose {key}={value}", 400)
            self.rpc.request("session/set_config_option", {"sessionId": self.sid, "configId": key, "value": value})
        prompt = [{"type": "text", "text": message}] if message else []
        prompt += [{"type": "image", "data": image["data"], "mimeType": image["mime"]} for image in self.options.images]
        if self.cancelled.is_set():
            raise ConnectedError("cancelled", "OpenCode turn cancelled before submission", 409)
        result = self.rpc.request("session/prompt", {"sessionId": self.sid, "prompt": prompt}, timeout=None)
        if result.get("stopReason") != "end_turn":
            raise ConnectedError("opencode_stopped", "OpenCode stopped: " + str(result.get("stopReason")), 409)
        if not any(item["kind"] == "reasoning" for item in self.items.values()):
            self.item("reasoning", reasoning_data("opencode", None, source="acp"), "reasoning-unreported")
        return self.sid
