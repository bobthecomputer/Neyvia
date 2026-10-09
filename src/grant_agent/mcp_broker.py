"""Outbound MCP broker MVP: discover → describe → call with auth + approval receipts.

Matrix gap #3. Inbound host remains NeyviaMCPServer; this module brokers *external*
MCP servers. Schemas stay cached and off the model hot path by default.
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from .mcp_http_transport import StreamableHttpTransport
from .mcp_protocol import JsonRpcFrameDecoder, NotificationDispatcher, list_all_tools
from .model_tool_intelligence import validate_json_schema_value
from .progressive_tools import ProgressiveToolSpec
from .subprocess_utils import hidden_windows_subprocess_kwargs


TOOL_RECEIPT_SCHEMA = "fluxio.native_tool_receipt.v1"
BROKER_SCHEMA = "neyvia.mcp_outbound_broker.v1"
BROKER_CONFIG_SCHEMA = "neyvia.mcp_broker_config.v1"
PROVIDER = "neyvia-mcp-broker"
AUTH_STATES = frozenset({"unknown", "unauthenticated", "authenticated", "expired", "error"})

ENV_CONFIG = "NEYVIA_MCP_BROKER_CONFIG"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _slug(value: object) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", str(value or "").strip().lower()).strip("-")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


class McpTransport(Protocol):
    def list_tools(self) -> list[dict[str, Any]]:
        ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass
class StubTransport:
    """In-process fake MCP server — no network required for CI."""

    tools: list[dict[str, Any]] = field(default_factory=list)
    handlers: dict[str, Callable[[dict[str, Any]], Any]] = field(default_factory=dict)
    fail_auth: bool = False

    def list_tools(self) -> list[dict[str, Any]]:
        if self.fail_auth:
            raise RuntimeError("stub transport auth failed")
        return [dict(tool) for tool in self.tools]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.fail_auth:
            raise RuntimeError("stub transport auth failed")
        tool_name = str(name or "").strip()
        if tool_name not in {str(t.get("name") or "") for t in self.tools}:
            raise KeyError(f"Unknown stub MCP tool: {tool_name}")
        handler = self.handlers.get(tool_name)
        if handler is not None:
            payload = handler(dict(arguments or {}))
        else:
            payload = {"echo": dict(arguments or {}), "tool": tool_name}
        if isinstance(payload, dict):
            return {
                "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                "structuredContent": payload,
                "isError": bool(payload.get("isError", False)),
            }
        return {
            "content": [{"type": "text", "text": str(payload)}],
            "structuredContent": {"value": payload},
            "isError": False,
        }


@dataclass
class StdioJsonRpcTransport:
    """Minimal MCP stdio client (JSONL or Content-Length framing).

    Incoming notifications are dispatched from the reader, including while idle.
    """

    command: list[str]
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    protocol_version: str = "2024-11-05"
    startup_timeout_s: float = 15.0
    request_timeout_s: float = 30.0
    framing: str = "content_length"
    _proc: subprocess.Popen[bytes] | None = field(default=None, repr=False, compare=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    _next_id: int = field(default=0, repr=False, compare=False)
    _initialized: bool = field(default=False, repr=False, compare=False)
    notifications: NotificationDispatcher = field(default_factory=NotificationDispatcher, repr=False, compare=False)
    _reader_queue: queue.Queue[Any] = field(default_factory=queue.Queue, repr=False, compare=False)
    _reader_thread: threading.Thread | None = field(default=None, repr=False, compare=False)

    def close(self) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None
            self._initialized = False
            self._reader_queue = queue.Queue()
            self._reader_thread = None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        for stream_name in ("stdin", "stdout", "stderr"):
            stream = getattr(proc, stream_name, None)
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
        try:
            proc.wait(timeout=1)
        except Exception:
            pass

    def _ensure_started(self) -> subprocess.Popen[bytes]:
        if self._proc is not None and self._proc.poll() is None:
            if not self._initialized:
                self._handshake()
            return self._proc
        if not self.command:
            raise RuntimeError("stdio MCP transport requires a command")
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in self.env.items()})
        self._proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cwd,
            env=env,
            bufsize=0,
            **hidden_windows_subprocess_kwargs(),
        )
        self._initialized = False
        self._reader_queue = queue.Queue()
        self._reader_thread = threading.Thread(target=self._pump_stdout, args=(self._proc,), daemon=True)
        self._reader_thread.start()
        self._handshake()
        return self._proc

    def _pump_stdout(self, proc: subprocess.Popen[bytes]) -> None:
        """Frame messages off-thread and deliver idle notifications immediately."""
        reader_queue = self._reader_queue
        decoder = JsonRpcFrameDecoder(self.framing)
        try:
            if proc.stdout is not None:
                while True:
                    chunk = proc.stdout.read(4096)
                    if not chunk:
                        break
                    for message in decoder.feed(chunk):
                        if not self.notifications.dispatch(message):
                            reader_queue.put(message)
        except Exception as exc:
            reader_queue.put(exc)
        finally:
            reader_queue.put(None)

    def _write_message(self, payload: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise RuntimeError("stdio MCP process is not running")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if self.framing == "newline":
            wire = body + b"\n"
        elif self.framing == "content_length":
            wire = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
        else:
            raise ValueError(f"unsupported stdio MCP framing: {self.framing}")
        proc.stdin.write(wire)
        proc.stdin.flush()

    def _read_message(self, *, timeout_s: float) -> dict[str, Any]:
        try:
            message = self._reader_queue.get(timeout=max(0.1, float(timeout_s)))
        except queue.Empty:
            raise TimeoutError("stdio MCP read timed out") from None
        if message is None:
            raise RuntimeError("stdio MCP process exited")
        if isinstance(message, Exception):
            raise message
        return message

    def _request_unlocked(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._next_id += 1
        req_id = self._next_id
        self._write_message(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params or {},
            }
        )
        deadline = time.monotonic() + self.request_timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"stdio MCP request timed out: {method}")
            message = self._read_message(timeout_s=remaining)
            if message.get("id") != req_id:
                continue
            if "error" in message:
                raise RuntimeError(f"stdio MCP {method} error: {message['error']}")
            return message.get("result")

    def _request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        with self._lock:
            self._ensure_started()
            return self._request_unlocked(method, params)

    def _notify_unlocked(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._write_message({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _handshake(self) -> None:
        if self._initialized:
            return
        result = self._request_unlocked(
            "initialize",
            {
                "protocolVersion": self.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "neyvia-mcp-broker", "version": "0.1.0"},
            },
        )
        if not isinstance(result, dict) or not result.get("protocolVersion"):
            raise RuntimeError("MCP returned an invalid initialize result")
        self._notify_unlocked("notifications/initialized", {})
        self._initialized = True

    def connect(self) -> None:
        """Complete the protocol handshake before catalog discovery."""
        with self._lock:
            self._ensure_started()

    def list_tools(self) -> list[dict[str, Any]]:
        return list_all_tools(self._request)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._request(
            "tools/call",
            {"name": str(name or "").strip(), "arguments": dict(arguments or {})},
        )
        if isinstance(result, dict):
            return dict(result)
        return {
            "content": [{"type": "text", "text": str(result)}],
            "structuredContent": {"value": result},
            "isError": False,
        }


class SseTransportStub:
    """Honest SSE stub — not implemented in this MVP."""

    def list_tools(self) -> list[dict[str, Any]]:
        raise RuntimeError("MCP SSE transport is not wired in MVP; use stdio `command` servers")

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("MCP SSE transport is not wired in MVP; use stdio `command` servers")


def _normalize_command(raw: dict[str, Any]) -> list[str]:
    command = raw.get("command")
    args = raw.get("args") or raw.get("arguments") or []
    if isinstance(command, list):
        parts = [str(item) for item in command if str(item).strip()]
    else:
        parts = [str(command or "").strip()] if str(command or "").strip() else []
    if isinstance(args, list):
        parts.extend(str(item) for item in args if str(item).strip())
    elif isinstance(args, str) and args.strip():
        parts.append(args.strip())
    return parts


def _build_stdio_transport(server_cfg: dict[str, Any], *, root: Path) -> StdioJsonRpcTransport:
    command = _normalize_command(server_cfg)
    if not command:
        raise ValueError("stdio MCP server requires command")
    env_raw = server_cfg.get("env") if isinstance(server_cfg.get("env"), dict) else {}
    cwd = str(server_cfg.get("cwd") or server_cfg.get("workingDirectory") or root)
    return StdioJsonRpcTransport(
        command=command,
        env={str(k): str(v) for k, v in env_raw.items()},
        cwd=cwd,
        protocol_version=str(server_cfg.get("protocolVersion") or "2024-11-05"),
        startup_timeout_s=float(server_cfg.get("startupTimeoutS") or 15),
        request_timeout_s=float(server_cfg.get("requestTimeoutS") or 30),
        framing=str(server_cfg.get("framing") or "content_length").strip().lower(),
    )


@dataclass
class McpServerState:
    name: str
    transport: str = "stub"
    auth_state: str = "unknown"
    configured: bool = True
    callable: bool = False
    has_environment: bool = False
    requires_approval_default: bool = False
    notes: list[str] = field(default_factory=list)
    command: str = ""
    url: str = ""
    _transport_impl: McpTransport | None = field(default=None, repr=False, compare=False)
    _schema_cache: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False, compare=False)
    _catalog_cached: bool = field(default=False, repr=False, compare=False)
    catalog_revision: int = 0
    resource_revision: int = 0
    notification_count: int = 0
    readiness: str = "configured"
    connected: bool = False
    discovered: bool = False
    verified: bool = False
    last_error: str = ""
    verification_receipt: str = ""
    observations: list[dict[str, Any]] = field(default_factory=list)

    def compact(self, *, include_observations: bool = False) -> dict[str, Any]:
        row = {
            "name": self.name,
            "transport": self.transport,
            "authState": self.auth_state,
            "configured": self.configured,
            "callable": self.callable,
            "hasEnvironment": self.has_environment,
            "requiresApprovalDefault": self.requires_approval_default,
            "toolCountCached": len(self._schema_cache) if self._catalog_cached else None,
            "notes": list(self.notes),
            "notificationCount": self.notification_count,
            "catalogRevision": self.catalog_revision,
            "resourceRevision": self.resource_revision,
            "readiness": self.readiness,
            "connected": self.connected,
            "discovered": self.discovered,
            "verified": self.verified,
            "lastError": self.last_error or None,
            "verificationReceipt": self.verification_receipt or None,
            "readinessObservation": dict(self.observations[-1]) if self.observations else None,
        }
        if include_observations:
            row["observations"] = list(self.observations)
        from .proofs_c_runtime import check_mcp_compact
        check_mcp_compact(self, row)
        return row


@dataclass
class BrokerReceipt:
    """Compatible with fluxio.native_tool_receipt.v1 (NAS NativeToolReceipt)."""

    tool: str
    ok: bool
    status: str
    duration_ms: int
    result: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    error: str = ""
    provider: str = PROVIDER
    schema: str = TOOL_RECEIPT_SCHEMA
    receipt_id: str = field(default_factory=lambda: f"tool_{uuid.uuid4().hex[:12]}")
    created_at: str = field(default_factory=_utc_now)
    receipt_path: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_auth_state(value: object) -> str:
    state = str(value or "unknown").strip().lower() or "unknown"
    return state if state in AUTH_STATES else "unknown"


def _tool_requires_approval(tool: dict[str, Any], *, server_default: bool = False) -> bool:
    annotations = tool.get("annotations") if isinstance(tool.get("annotations"), dict) else {}
    if "requiresApproval" in annotations:
        return bool(annotations.get("requiresApproval"))
    if bool(annotations.get("destructiveHint")):
        return True
    if "readOnlyHint" in annotations:
        return not bool(annotations.get("readOnlyHint"))
    mutability = str(tool.get("mutability_class") or tool.get("mutabilityClass") or "").strip().lower()
    if mutability in {"write", "mutate", "destructive", "external_write"}:
        return True
    return bool(server_default)


def _compact_tool_row(server: str, tool: dict[str, Any], *, requires_approval: bool) -> dict[str, Any]:
    name = str(tool.get("name") or "").strip()
    return {
        "name": name,
        "qualifiedName": f"mcp.{server}.{name}",
        "server": server,
        "description": str(tool.get("description") or ""),
        "category": "mcp-brokered",
        "available": True,
        "requiresApproval": requires_approval,
        "annotations": dict(tool.get("annotations") or {}),
    }


def default_demo_config() -> dict[str, Any]:
    """Small built-in stub catalog used when no config file is present."""
    return {
        "schema": BROKER_CONFIG_SCHEMA,
        "servers": {
            "demo": {
                "transport": "stub",
                "authState": "authenticated",
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo normalized arguments (read-only stub).",
                        "inputSchema": _object_schema(
                            {"text": {"type": "string"}},
                            ["text"],
                        ),
                        "annotations": {"readOnlyHint": True},
                    },
                    {
                        "name": "write_note",
                        "description": "Mutating stub that requires operator approval.",
                        "inputSchema": _object_schema(
                            {"note": {"type": "string"}},
                            ["note"],
                        ),
                        "annotations": {
                            "readOnlyHint": False,
                            "destructiveHint": False,
                            "requiresApproval": True,
                        },
                    },
                ],
            }
        },
    }


def load_broker_config(
    root: str | Path | None = None,
    *,
    config: dict[str, Any] | None = None,
    config_path: str | Path | None = None,
) -> tuple[dict[str, Any], str]:
    """Load broker config from explicit dict, path, env, or default demo stub."""
    if config is not None:
        return dict(config), "explicit"
    path_candidates: list[Path] = []
    if config_path:
        path_candidates.append(Path(config_path).expanduser())
    env_path = str(os.environ.get(ENV_CONFIG) or "").strip()
    if env_path:
        path_candidates.append(Path(env_path).expanduser())
    if root is not None:
        root_path = Path(root).resolve()
        path_candidates.extend(
            [
                root_path / ".agent_control" / "mcp_broker.json",
                root_path / ".agent_control" / "mcp_servers.json",
            ]
        )
    for candidate in path_candidates:
        if not candidate.exists() or not candidate.is_file():
            continue
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"MCP broker config must be an object: {candidate}")
        return payload, str(candidate)
    return default_demo_config(), "default_demo"


def _servers_from_config(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if isinstance(payload.get("servers"), dict):
        return {str(k): dict(v) for k, v in payload["servers"].items() if isinstance(v, dict)}
    # Codex-style mcp_servers / mcpServers name-index upgrade path
    for key in ("mcp_servers", "mcpServers"):
        raw = payload.get(key)
        if isinstance(raw, dict):
            return {str(k): dict(v) if isinstance(v, dict) else {"configured": True} for k, v in raw.items()}
        if isinstance(raw, list):
            out: dict[str, dict[str, Any]] = {}
            for item in raw:
                if isinstance(item, dict) and item.get("name"):
                    out[str(item["name"])] = dict(item)
                elif isinstance(item, str) and item.strip():
                    out[item.strip()] = {"configured": True, "transport": "unknown"}
            return out
    return {}


def _build_stub_transport(server_cfg: dict[str, Any]) -> StubTransport:
    tools = list(server_cfg.get("tools") or [])
    handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
    for tool in tools:
        name = str(tool.get("name") or "")
        if name == "echo":

            def _echo(args: dict[str, Any], *, _n: str = name) -> dict[str, Any]:
                return {"ok": True, "text": str(args.get("text") or ""), "tool": _n}

            handlers[name] = _echo
        elif name == "write_note":

            def _write(args: dict[str, Any], *, _n: str = name) -> dict[str, Any]:
                return {"ok": True, "written": True, "note": str(args.get("note") or ""), "tool": _n}

            handlers[name] = _write
    return StubTransport(tools=tools, handlers=handlers)


class McpOutboundBroker:
    """Callable outbound MCP gateway with auth-state and approval receipts."""

    def __init__(
        self,
        root: str | Path,
        *,
        config: dict[str, Any] | None = None,
        config_path: str | Path | None = None,
        include_default_demo: bool = True,
    ) -> None:
        self.root = Path(root).resolve()
        self.receipt_root = (
            self.root / ".agent_control" / "mission_artifacts" / "context_microkernel" / "mcp_broker"
        )
        self.receipt_root.mkdir(parents=True, exist_ok=True)
        payload, source = load_broker_config(self.root, config=config, config_path=config_path)
        if source == "default_demo" and not include_default_demo:
            payload = {"schema": BROKER_CONFIG_SCHEMA, "servers": {}}
            source = "empty"
        self.config_source = source
        self.config = payload
        self._servers: dict[str, McpServerState] = {}
        self._load_servers(payload)

    def _load_servers(self, payload: dict[str, Any]) -> None:
        for name, raw in sorted(_servers_from_config(payload).items()):
            explicit_transport = str(raw.get("transport") or raw.get("type") or "").strip().lower()
            if explicit_transport in {"inprocess", "fake", "mock", "local"}:
                transport_kind = "stub"
            elif explicit_transport in {"http", "streamable_http", "streamable-http"}:
                transport_kind = "streamable-http"
            elif explicit_transport:
                transport_kind = explicit_transport
            elif raw.get("url"):
                transport_kind = "streamable-http"
            elif raw.get("command"):
                # Codex-style mcp_servers rows: configured command, not yet a stub catalog.
                transport_kind = "stdio"
            elif isinstance(raw.get("tools"), list) and raw.get("tools"):
                transport_kind = "stub"
            else:
                transport_kind = "unknown"
            auth_state = _normalize_auth_state(raw.get("authState") or raw.get("auth_state"))
            has_env = bool(raw.get("env") or raw.get("hasEnvironment") or raw.get("has_environment"))
            requires_approval_default = bool(
                raw.get("requiresApprovalDefault") or raw.get("requires_approval_default")
            )
            notes: list[str] = []
            transport_impl: McpTransport | None = None
            callable_now = False
            if transport_kind == "stub":
                if not isinstance(raw.get("tools"), list) or not raw.get("tools"):
                    notes.append("configured_name_only_no_stub_tools")
                    if auth_state == "unknown":
                        auth_state = "unauthenticated"
                else:
                    transport_impl = _build_stub_transport(raw)
                    callable_now = auth_state == "authenticated"
                    if auth_state != "authenticated":
                        notes.append("auth_blocks_callable")
            elif transport_kind == "stdio":
                try:
                    transport_impl = _build_stdio_transport(raw, root=self.root)
                    # Stdio servers are treated as authenticated once the command is configured;
                    # operators can still force auth_state to block calls.
                    if auth_state == "unknown":
                        auth_state = "authenticated"
                    callable_now = auth_state == "authenticated"
                    notes.append("stdio_jsonrpc_mvp")
                    if auth_state != "authenticated":
                        notes.append("auth_blocks_callable")
                except Exception as exc:
                    notes.append(f"stdio_transport_build_failed:{exc}")
                    if auth_state == "unknown":
                        auth_state = "unauthenticated"
            elif transport_kind == "streamable-http":
                try:
                    headers_raw = raw.get("headers") or raw.get("http_headers") or {}
                    if not isinstance(headers_raw, dict):
                        raise ValueError("HTTP headers must be an object")
                    transport_impl = StreamableHttpTransport(
                        str(raw.get("url") or ""),
                        headers={str(k): str(v) for k, v in headers_raw.items()},
                        protocol_version=str(raw.get("protocolVersion") or "2025-03-26"),
                        request_timeout_s=float(raw.get("requestTimeoutS") or 30),
                    )
                    if auth_state == "unknown":
                        auth_state = "authenticated"
                    callable_now = auth_state == "authenticated"
                    if not callable_now:
                        notes.append("auth_blocks_callable")
                except Exception as exc:
                    notes.append(f"http_transport_build_failed:{exc}")
                    if auth_state == "unknown":
                        auth_state = "unauthenticated"
            elif transport_kind == "sse":
                notes.append("transport_sse_not_wired_in_mvp")
                notes.append("use_stdio_command_servers_instead")
                if auth_state == "unknown":
                    auth_state = "unauthenticated"
            else:
                notes.append(f"transport_{transport_kind}_not_wired_in_mvp")
                if auth_state == "unknown":
                    auth_state = "unauthenticated"
            state = McpServerState(
                name=name,
                transport=transport_kind,
                auth_state=auth_state,
                configured=True,
                callable=callable_now,
                has_environment=has_env,
                requires_approval_default=requires_approval_default,
                notes=notes,
                command=str(raw.get("command") or ""),
                url=str(raw.get("url") or ""),
                _transport_impl=transport_impl,
            )
            # Seed schema cache from config tools without exposing them to model context.
            for tool in list(raw.get("tools") or []):
                if isinstance(tool, dict) and tool.get("name"):
                    state._schema_cache[str(tool["name"])] = dict(tool)
            if state._schema_cache and transport_kind == "stub":
                state._catalog_cached = True
            self._observe(state, "configured", "configuration_loaded")
            if transport_kind == "stub":
                state.notes.append("simulation_only_never_verified")
            elif transport_impl is None:
                self._observe(state, "failing", "transport_unavailable")
            self._servers[name] = state
            notifications = getattr(transport_impl, "notifications", None)
            if notifications is not None:
                notifications.handler = lambda event, state=state: self._on_notification(state, event)

    def _on_notification(self, state: McpServerState, event: dict[str, Any]) -> None:
        state.notification_count += 1
        method = event["method"]
        if method == "notifications/tools/list_changed":
            state.catalog_revision += 1
            state._catalog_cached = False
            state._schema_cache = {}
            state.discovered = False
            state.verified = False
            state.verification_receipt = ""
            if state.connected and state.readiness != "failing":
                self._observe(state, "connected", "tools_list_changed")
        elif method in {"notifications/resources/list_changed", "notifications/resources/updated"}:
            state.resource_revision += 1

    @staticmethod
    def _observe(state: McpServerState, readiness: str, event: str, *, error: str = "",
                 receipt: str = "") -> None:
        """Record only protocol observations; configuration and notifications are not proof."""
        state.readiness = readiness
        state.last_error = error
        if readiness == "failing":
            state.verified = False
            state.verification_receipt = ""
        elif readiness == "connected":
            state.connected = True
        elif readiness == "discovered":
            state.discovered = True
        elif readiness == "verified":
            state.verified = True
            state.verification_receipt = receipt
        state.observations.append({"stage": readiness, "event": event, "observedAt": _utc_now(),
                                   **({"error": error} if error else {}),
                                   **({"receiptPath": receipt} if receipt else {})})
        state.observations = state.observations[-32:]

    def _fail(self, state: McpServerState, event: str, exc: Exception | str) -> None:
        state._catalog_cached = False
        self._observe(state, "failing", event, error=str(exc))

    def notifications(self, server: str | None = None) -> list[dict[str, Any]]:
        targets = [self.get_server(server)] if server else list(self._servers.values())
        events: list[dict[str, Any]] = []
        for state in targets:
            dispatcher = getattr(state._transport_impl, "notifications", None)
            if dispatcher is not None:
                events.extend({"server": state.name, **event} for event in dispatcher.drain())
        return events

    def close(self) -> None:
        for state in self._servers.values():
            close = getattr(state._transport_impl, "close", None)
            if close is not None:
                close()
            state.connected = False
            state.discovered = False
            state.verified = False
            state._catalog_cached = False
            state.verification_receipt = ""
            self._observe(state, "configured", "transport_closed")

    def list_servers(self) -> list[dict[str, Any]]:
        return [state.compact() for state in self._servers.values()]

    def get_server(self, name: str) -> McpServerState:
        key = str(name or "").strip()
        if key not in self._servers:
            raise KeyError(f"Unknown MCP server: {name}")
        return self._servers[key]

    def auth_state(self, server: str) -> dict[str, Any]:
        state = self.get_server(server)
        return {
            "schema": "neyvia.mcp_auth_state.v1",
            "server": state.name,
            "authState": state.auth_state,
            "callable": state.callable,
            "configured": state.configured,
            "notes": list(state.notes),
            "readiness": state.readiness,
        }

    def set_auth_state(self, server: str, auth_state: str) -> dict[str, Any]:
        state = self.get_server(server)
        state.auth_state = _normalize_auth_state(auth_state)
        if state.auth_state != "authenticated":
            self._fail(state, "authorization_revoked", f"authState={state.auth_state}")
        elif state.readiness == "failing":
            self._observe(state, "configured", "authorization_restored")
        state.callable = (
            state._transport_impl is not None
            and state.auth_state == "authenticated"
            and state.transport in {"stub", "stdio", "streamable-http"}
        )
        if state.callable:
            state.notes = [n for n in state.notes if n != "auth_blocks_callable"]
        elif state._transport_impl is not None and state.transport in {"stub", "stdio", "streamable-http"}:
            if "auth_blocks_callable" not in state.notes:
                state.notes.append("auth_blocks_callable")
        return self.auth_state(server)

    def _ensure_catalog(self, state: McpServerState) -> dict[str, dict[str, Any]]:
        if state._catalog_cached:
            return state._schema_cache
        if state._transport_impl is None:
            raise RuntimeError(f"MCP server '{state.name}' has no callable transport")
        if state.auth_state != "authenticated":
            raise RuntimeError(f"MCP server '{state.name}' authState={state.auth_state}")
        try:
            connect = getattr(state._transport_impl, "connect", None)
            if callable(connect):
                connect()
                self._observe(state, "connected", "initialize_completed")
            revision = state.catalog_revision
            tools = state._transport_impl.list_tools()
            if revision != state.catalog_revision:
                # A list-changed event during pagination invalidates the whole traversal.
                revision = state.catalog_revision
                tools = state._transport_impl.list_tools()
                if revision != state.catalog_revision:
                    raise RuntimeError("MCP tool catalog changed repeatedly during discovery; retry")
        except Exception as exc:
            self._fail(state, "discovery_failed", exc)
            raise
        cache: dict[str, dict[str, Any]] = {}
        for tool in tools:
            if isinstance(tool, dict) and tool.get("name"):
                cache[str(tool["name"])] = dict(tool)
        state._schema_cache = cache
        state._catalog_cached = state.catalog_revision == revision
        if state.transport in {"stdio", "streamable-http"}:
            self._observe(state, "discovered", "tools_list_completed")
        return cache

    def search(self, query: str, *, limit: int = 8, server: str | None = None) -> list[dict[str, Any]]:
        terms = {term for term in re.findall(r"[a-z0-9]+", str(query).lower()) if len(term) > 1}
        scored: list[tuple[int, dict[str, Any]]] = []
        targets = [self.get_server(server)] if server else list(self._servers.values())
        for state in targets:
            try:
                catalog = self._ensure_catalog(state) if state.callable else dict(state._schema_cache)
            except Exception:
                catalog = dict(state._schema_cache)
            for tool in catalog.values():
                requires = _tool_requires_approval(
                    tool, server_default=state.requires_approval_default
                )
                row = _compact_tool_row(state.name, tool, requires_approval=requires)
                row.update(available=state.callable and state.readiness != "failing",
                           readiness=state.readiness, verified=state.verified,
                           simulation=state.transport == "stub")
                haystack = " ".join(
                    [
                        row["name"],
                        row["qualifiedName"],
                        row["description"],
                        row["server"],
                        row["category"],
                    ]
                ).lower()
                score = sum(4 if term in row["name"] else 1 for term in terms if term in haystack)
                if not terms or score:
                    scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], item[1]["qualifiedName"]))
        # Never attach inputSchema on search results.
        result = [row for _, row in scored[: max(1, min(int(limit), 20))]]
        from .proofs_c_runtime import check_mcp_search
        check_mcp_search(result)
        return result

    def describe(self, server: str, tool: str | None = None, *, name: str | None = None) -> dict[str, Any]:
        server_name, tool_name = self._parse_target(server, tool=tool, name=name)
        state = self.get_server(server_name)
        catalog = self._ensure_catalog(state) if state.callable else dict(state._schema_cache)
        if tool_name not in catalog:
            # Attempt refresh once if callable
            if state.callable:
                state._catalog_cached = False
                catalog = self._ensure_catalog(state)
            if tool_name not in catalog:
                raise KeyError(f"Unknown MCP tool: mcp.{server_name}.{tool_name}")
        tool_spec = dict(catalog[tool_name])
        requires = _tool_requires_approval(tool_spec, server_default=state.requires_approval_default)
        result = {
            "name": tool_name,
            "qualifiedName": f"mcp.{server_name}.{tool_name}",
            "server": server_name,
            "description": str(tool_spec.get("description") or ""),
            "category": "mcp-brokered",
            "available": state.callable and state.readiness != "failing",
            "authState": state.auth_state,
            "requiresApproval": requires,
            "inputSchema": dict(tool_spec.get("inputSchema") or tool_spec.get("input_schema") or {}),
            "outputSchema": dict(tool_spec.get("outputSchema") or tool_spec.get("output_schema") or {}),
            "annotations": dict(tool_spec.get("annotations") or {}),
            "readiness": state.readiness,
            "verified": state.verified,
            "simulation": state.transport == "stub",
            "schemasDeferredDefault": True,
        }
        from .proofs_c_runtime import check_mcp_described
        check_mcp_described(state, tool_name, tool_spec, result, requires)
        return result

    def call(
        self,
        server: str,
        tool: str | None = None,
        arguments: dict[str, Any] | None = None,
        *,
        name: str | None = None,
        approved: bool = False,
        approval_id: str = "",
        mission_id: str = "",
    ) -> dict[str, Any]:
        server_name, tool_name = self._parse_target(server, tool=tool, name=name)
        state = self.get_server(server_name)
        qualified = f"mcp.{server_name}.{tool_name}"
        started = time.perf_counter()
        receipt = BrokerReceipt(tool=qualified, ok=False, status="failed", duration_ms=0)
        args = dict(arguments or {})
        dispatched = False
        try:
            if not state.configured:
                raise RuntimeError(f"MCP server '{server_name}' is not configured")
            if state.auth_state != "authenticated":
                receipt.status = "auth_required"
                raise RuntimeError(f"MCP server '{server_name}' authState={state.auth_state}")
            if not state.callable or state._transport_impl is None:
                raise RuntimeError(f"MCP server '{server_name}' is not callable")
            catalog = self._ensure_catalog(state)
            if tool_name not in catalog:
                raise KeyError(f"Unknown MCP tool: {qualified}")
            tool_spec = catalog[tool_name]
            input_validation = validate_json_schema_value(
                args,
                tool_spec.get("inputSchema") or tool_spec.get("input_schema") or {},
            )
            if input_validation["valid"] is False:
                receipt.status = "failed"
                receipt.error = f"invalid_arguments:{input_validation['error']}"
                receipt.result = {
                    "server": server_name,
                    "tool": tool_name,
                    "authState": state.auth_state,
                    "inputValidation": input_validation,
                }
                raise ValueError(receipt.error)
            requires = _tool_requires_approval(
                tool_spec, server_default=state.requires_approval_default
            )
            approval_meta = {
                "approvalRequired": requires,
                "approvalGranted": bool(approved) if requires else True,
                "approvalId": str(approval_id or "").strip() or None,
            }
            if requires and not approved:
                receipt.status = "approval_required"
                receipt.result = {
                    "server": server_name,
                    "tool": tool_name,
                    "authState": state.auth_state,
                    **approval_meta,
                    "message": "Mutating MCP call blocked until operator approval.",
                }
                receipt.error = "approval_required"
            else:
                try:
                    dispatched = True
                    remote = state._transport_impl.call_tool(tool_name, args)
                except Exception as exc:
                    self._fail(state, "tools_call_failed", exc)
                    raise
                structured = (
                    remote.get("structuredContent")
                    if isinstance(remote, dict) and isinstance(remote.get("structuredContent"), dict)
                    else {"raw": remote}
                )
                is_error = bool(isinstance(remote, dict) and remote.get("isError"))
                output_validation = validate_json_schema_value(
                    structured,
                    tool_spec.get("outputSchema")
                    or tool_spec.get("output_schema")
                    or {},
                )
                invalid_output = output_validation["valid"] is False
                receipt.ok = not is_error and not invalid_output
                receipt.status = "failed" if is_error or invalid_output else "completed"
                receipt.result = {
                    "server": server_name,
                    "tool": tool_name,
                    "authState": state.auth_state,
                    **approval_meta,
                    "structuredContent": structured,
                    "inputValidation": input_validation,
                    "outputValidation": output_validation,
                }
                if is_error:
                    receipt.error = str(structured.get("error") or "remote_tool_error")
                elif invalid_output:
                    receipt.error = f"invalid_output:{output_validation['error']}"
                if not receipt.ok:
                    self._fail(state, "tools_call_failed", receipt.error)
                artifacts = structured.get("artifacts") if isinstance(structured, dict) else None
                if isinstance(artifacts, list):
                    receipt.artifacts = [str(item) for item in artifacts if str(item).strip()]
        except KeyError as exc:
            receipt.error = str(exc)
            receipt.status = "failed"
        except Exception as exc:
            if receipt.status == "failed":
                receipt.status = "failed"
            receipt.error = str(exc)
            if not receipt.result:
                receipt.result = {
                    "server": server_name,
                    "tool": tool_name,
                    "authState": state.auth_state,
                }

        receipt.duration_ms = max(1, int((time.perf_counter() - started) * 1000))
        path = self.receipt_root / f"{receipt.receipt_id}_{_slug(qualified)}.json"
        receipt.receipt_path = str(path)
        payload = receipt.as_dict()
        payload["missionId"] = str(mission_id or "").strip() or None
        payload["brokerSchema"] = BROKER_SCHEMA
        _atomic_json(path, payload)
        if (receipt.ok and state.transport in {"stdio", "streamable-http"}
                and state.discovered and state._catalog_cached):
            self._observe(state, "verified", "validated_tools_call_completed", receipt=str(path))
        payload["readiness"] = state.readiness
        payload["verified"] = state.verified
        payload["simulation"] = state.transport == "stub"
        _atomic_json(path, payload)
        from .proofs_c_runtime import check_mcp_receipt
        check_mcp_receipt(state, payload, dispatched)
        return payload

    @staticmethod
    def _parse_target(
        server: str,
        *,
        tool: str | None = None,
        name: str | None = None,
    ) -> tuple[str, str]:
        if tool:
            return str(server or "").strip(), str(tool or "").strip()
        qualified = str(name or server or "").strip()
        # Accept mcp.<server>.<tool> or <server>/<tool> or <server>.<tool>
        if qualified.startswith("mcp."):
            parts = qualified.split(".", 2)
            if len(parts) == 3:
                return parts[1], parts[2]
        if "/" in qualified:
            left, right = qualified.split("/", 1)
            return left.strip(), right.strip()
        if "." in qualified and tool is None and name:
            left, right = qualified.split(".", 1)
            return left.strip(), right.strip()
        if tool is None and name is None:
            raise ValueError("tool name required (server + tool, or mcp.<server>.<tool>)")
        return str(server or "").strip(), str(tool or name or "").strip()

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": BROKER_SCHEMA,
            "provider": PROVIDER,
            "configSource": self.config_source,
            "schemasDeferredDefault": True,
            "receiptRoot": str(self.receipt_root),
            "servers": self.list_servers(),
            "progressiveTools": ["mcp.servers", "mcp.search", "mcp.describe", "mcp.call"],
            "receiptSchema": TOOL_RECEIPT_SCHEMA,
        }

    def write_smoke_receipt(self, *, mission_id: str = "mcp-outbound-broker-mvp") -> Path:
        """Emit a mission-level smoke receipt under context_microkernel/mcp_broker/."""
        call_receipt = None
        if any(s.callable for s in self._servers.values()):
            demo = next(s for s in self._servers.values() if s.callable)
            tools = list(demo._schema_cache.keys()) or ["echo"]
            read_tool = "echo" if "echo" in tools else tools[0]
            call_receipt = self.call(
                demo.name,
                read_tool,
                {"text": "broker-smoke"},
                approved=False,
                mission_id=mission_id,
            )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.receipt_root / f"{stamp}_{_slug(mission_id)}_broker_smoke.json"
        payload = {
            "schema": "neyvia.mcp_broker_smoke.v1",
            "generatedAt": _utc_now(),
            "missionId": mission_id,
            "ok": bool(call_receipt and call_receipt.get("ok")),
            "broker": self.snapshot(),
            "sampleCall": call_receipt,
            "receiptPath": str(path),
            "notes": [
                "Outbound MCP broker: stub, stdio and Streamable HTTP callable; legacy SSE remains unsupported.",
                "Foreign schemas cached off hot path.",
                "Mutating calls remain approval-gated.",
            ],
        }
        _atomic_json(path, payload)
        return path


PROGRESSIVE_MCP_TOOLS = (
    "mcp.servers",
    "mcp.search",
    "mcp.describe",
    "mcp.call",
)


def mcp_tool_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": "mcp.servers",
            "description": "List configured outbound MCP servers (auth-state, callable) without tool catalogs.",
            "category": "mcp-broker",
            "aliases": ("mcp list servers", "outbound mcp"),
            "input_schema": _object_schema({}),
            "mutability_class": "read",
        },
        {
            "name": "mcp.search",
            "description": "Search brokered MCP tools without dumping full foreign schemas.",
            "category": "mcp-broker",
            "aliases": ("mcp find", "broker search"),
            "input_schema": _object_schema(
                {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    "server": {"type": "string"},
                }
            ),
            "mutability_class": "read",
        },
        {
            "name": "mcp.describe",
            "description": "Describe one brokered MCP tool schema after search (cached).",
            "category": "mcp-broker",
            "aliases": ("mcp schema",),
            "input_schema": _object_schema(
                {
                    "server": {"type": "string"},
                    "tool": {"type": "string"},
                    "name": {"type": "string", "description": "Qualified mcp.<server>.<tool>"},
                }
            ),
            "mutability_class": "read",
        },
        {
            "name": "mcp.call",
            "description": "Call a brokered MCP tool with auth-state checks and approval gating for mutations.",
            "category": "mcp-broker",
            "aliases": ("mcp invoke", "broker call"),
            "input_schema": _object_schema(
                {
                    "server": {"type": "string"},
                    "tool": {"type": "string"},
                    "name": {"type": "string"},
                    "arguments": {"type": "object"},
                    "approved": {"type": "boolean"},
                    "approvalId": {"type": "string"},
                    "missionId": {"type": "string"},
                }
            ),
            "mutability_class": "write",
        },
    ]


def register_with_progressive_surface(
    surface: Any,
    broker: McpOutboundBroker,
) -> list[str]:
    """Attach mcp.* progressive entry points onto a ProgressiveToolSurface."""
    register = getattr(surface, "register", None)
    if not callable(register):
        raise TypeError("progressive surface missing register()")

    def _servers(_args: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": BROKER_SCHEMA,
            "servers": broker.list_servers(),
            "configSource": broker.config_source,
            "incomingNotifications": broker.notifications(),
        }

    def _search(args: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": "neyvia.mcp_broker.search.v1",
            "flow": ["search", "describe", "call"],
            "tools": broker.search(
                str(args.get("query") or ""),
                limit=int(args.get("limit") or 8),
                server=str(args.get("server") or "").strip() or None,
            ),
        }

    def _describe(args: dict[str, Any]) -> dict[str, Any]:
        return broker.describe(
            str(args.get("server") or ""),
            tool=str(args.get("tool") or "").strip() or None,
            name=str(args.get("name") or "").strip() or None,
        )

    def _call(args: dict[str, Any]) -> dict[str, Any]:
        return broker.call(
            str(args.get("server") or args.get("name") or ""),
            tool=str(args.get("tool") or "").strip() or None,
            arguments=dict(args.get("arguments") or {}),
            name=str(args.get("name") or "").strip() or None,
            approved=bool(args.get("approved", False)),
            approval_id=str(args.get("approvalId") or args.get("approval_id") or ""),
            mission_id=str(args.get("missionId") or args.get("mission_id") or ""),
        )

    handlers = {
        "mcp.servers": _servers,
        "mcp.search": _search,
        "mcp.describe": _describe,
        "mcp.call": _call,
    }
    registered: list[str] = []
    for spec in mcp_tool_specs():
        name = str(spec["name"])
        register(
            ProgressiveToolSpec(
                name=name,
                description=str(spec["description"]),
                category=str(spec.get("category") or "mcp-broker"),
                aliases=tuple(spec.get("aliases") or ()),
                input_schema=dict(spec.get("input_schema") or {}),
                annotations={
                    "readOnlyHint": str(spec.get("mutability_class") or "read") == "read",
                    "brokered": True,
                    "schemasDeferred": True,
                },
            ),
            handler=handlers[name],
        )
        registered.append(name)
    from .proofs_c_runtime import require
    require(set(registered) == {"mcp.servers", "mcp.search", "mcp.describe", "mcp.call"},
            "runtime.mcp.progressive", "progressive broker endpoints incomplete")
    return registered
