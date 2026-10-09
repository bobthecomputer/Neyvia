"""MCP agent adapter to the PC-owned Cua session, approvals and shared preview log."""
from __future__ import annotations

import http.cookiejar
import json
import os
import sys
import threading
import secrets
from typing import Any, BinaryIO
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, ProxyHandler, Request, build_opener


def _tool(name: str, description: str, properties: dict, required: tuple[str, ...] = (), *, read_only: bool = False) -> dict:
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False},
            "annotations": {"readOnlyHint": read_only, "destructiveHint": False, "idempotentHint": read_only, "openWorldHint": False}}


PREVIEW_TOOLS = [
    _tool("preview_log", "Read this chat's Cua session's shared action log, including Paul's actions.",
          {"since_seq": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, read_only=True),
    _tool("preview_wait", "Wait while Paul holds control. Resume only after Give back; read the note and Paul's actions.",
          {"timeout_ms": {"type": "integer", "minimum": 0, "maximum": 600000}}, read_only=True),
    _tool("request_app", "Ask Paul to allow another application in this session; waits up to 120 seconds for approval.",
          {"app": {"type": "string", "minLength": 1}, "reason": {"type": "string", "minLength": 1}}, ("app", "reason")),
    _tool("preview_note", "Add an agent note to the shared preview log.",
          {"text": {"type": "string", "maxLength": 500}}, ("text",)),
    _tool("preview_show", "Show this session's interactive computer-use preview to Paul.", {}),
]
from .neyvia_cua import TARGET, STEP
PREVIEW_TOOLS += [
    _tool("adapt_app", "Read-only first-use app exploration and quarantined CL manual; visual fallback is explicit.",
          {**TARGET, "visual": {"type": "boolean"}}, ("window_id",)),
    _tool("run_flow", "Execute a verified background flow, promote successful scoped learning and compile repeated grounded runs.",
          {**TARGET, "steps": {"type": "array", "items": STEP, "minItems": 1, "maxItems": 16}}, ("window_id", "steps")),
]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("The local Cua backend must not redirect requests")


class CuaMCPServer:
    def __init__(self, backend_url: str | None = None) -> None:
        self.url = (backend_url or os.environ.get("NEYVIA_UI_BACKEND_URL", "http://127.0.0.1:48171")).rstrip("/")
        parsed = urlsplit(self.url)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.port not in (*range(48171, 48180), *range(48701, 48710), *range(48751, 48760), *range(49031, 49040)) or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment):
            raise ValueError("Cua backend must be loopback HTTP on approved native service or assigned C1/C8/RX development ports")
        self._opener = build_opener(ProxyHandler({}), _NoRedirect(), HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self._authenticated = False
        self._initialized = False
        self.session_id = ""
        self.connection_id = secrets.token_hex(12)
        self.client = {"chatId": os.environ.get("NEYVIA_CHAT_ID", ""),
                       "app": os.environ.get("NEYVIA_APP", ""), "title": os.environ.get("NEYVIA_CHAT_TITLE", "")}

    def _http(self, path: str, body: dict | None = None, *, timeout: float = 130) -> Any:
        request = Request(self.url + path, data=None if body is None else json.dumps(body).encode("utf-8"),
                          headers={"Content-Type": "application/json", "Origin": self.url})
        try:
            with self._opener.open(request, timeout=timeout) as response:
                value = json.load(response)
        except HTTPError as exc:
            if exc.code == 401:
                self._authenticated = False
            raise RuntimeError("Cua backend HTTP " + str(exc.code)) from exc
        if not isinstance(value, dict) or value.get("ok") is not True:
            raise RuntimeError(str(value.get("error", "Invalid Cua backend response")) if isinstance(value, dict) else "Invalid Cua backend response")
        return value.get("data", value)

    def _authenticate(self) -> None:
        if not self._authenticated:
            self._http("/api/auth/local-session", {})
            self._authenticated = True

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        identity = request.get("id")
        method = request.get("method")
        if "id" not in request:
            return None
        try:
            params = request.get("params") or {}
            if not isinstance(params, dict):
                raise ValueError("MCP params must be an object")
            if method == "initialize":
                if not self._initialized:
                    name = str((params.get("clientInfo") or {}).get("name") or "cua-agent")
                    self.client["chatId"] = self.client["chatId"] or name
                    self.client["app"] = self.client["app"] or name
                    self._initialized = True
                result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "neyvia-cua", "version": "1.0.0"}}
            elif method == "ping":
                result = {}
            elif not self._initialized:
                raise ValueError("Initialize the MCP connection before using tools")
            elif method == "tools/list":
                self._authenticate()
                value = self._http("/api/ui/cua/tools")
                tools = value if isinstance(value, list) else value.get("tools")
                if not isinstance(tools, list):
                    raise RuntimeError("Cua backend returned an invalid tool inventory")
                result = {"tools": tools}
            elif method == "tools/call":
                name = params.get("name")
                arguments = params.get("arguments", {})
                if not isinstance(name, str) or not isinstance(arguments, dict):
                    raise ValueError("A tool name and arguments object are required")
                self._authenticate()
                result = self._http("/api/ui/cua", {"op": "driver", "args": {
                    "tool": name, "arguments": arguments, "client": dict(self.client),
                    "sessionId": self.session_id, "connectionId": self.connection_id, "requestId": identity, "requestMeta": params.get("_meta") or {}}},
                    timeout=610 if name == "preview_wait" else 130)
                if not isinstance(result, dict) or not isinstance(result.get("content"), list):
                    raise RuntimeError("Cua backend did not return an MCP ToolResult")
                preview = (result.get("_meta") or {}).get("neyvia/preview") or {}
                selected = preview.get("session")
                if isinstance(selected, dict):
                    selected = selected.get("id")
                if not selected and name == "start_session" and not result.get("isError"):
                    selected = (result.get("structuredContent") or {}).get("session")
                if selected:
                    if self.session_id and str(selected) != self.session_id:
                        raise RuntimeError("Cua backend changed this connection's bound session")
                    self.session_id = str(selected)
                if name == "end_session" and not result.get("isError"):
                    self.session_id = ""
            else:
                return {"jsonrpc": "2.0", "id": identity, "error": {"code": -32601, "message": "Unknown MCP method"}}
            return {"jsonrpc": "2.0", "id": identity, "result": result}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": identity, "error": {"code": -32000, "message": str(exc)}}


def _read_message(source: BinaryIO) -> tuple[dict, str] | None:
    line = source.readline()
    while line and not line.strip():
        line = source.readline()
    if not line:
        return None
    if line.lower().startswith(b"content-length:"):
        length = int(line.split(b":", 1)[1].strip())
        if length < 0 or length > 16 * 1024 * 1024:
            raise ValueError("MCP message exceeds the 16 MB limit")
        while True:
            header = source.readline()
            if header in {b"\r\n", b"\n"}:
                break
            if not header:
                raise EOFError("Incomplete MCP header")
        body = source.read(length)
        if len(body) != length:
            raise EOFError("Incomplete MCP body")
        framing = "content_length"
    else:
        body, framing = line, "newline"
    value = json.loads(body.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("MCP request must be an object")
    return value, framing


def main() -> int:
    server = CuaMCPServer()
    write_lock = threading.Lock()
    while True:
        try:
            item = _read_message(sys.stdin.buffer)
            if item is None:
                return 0
            request, framing = item
            response = server.handle(request)
            if response is not None:
                body = json.dumps(response, ensure_ascii=False).encode("utf-8")
                wire = (f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
                        if framing == "content_length" else body + b"\n")
                with write_lock:
                    sys.stdout.buffer.write(wire)
                    sys.stdout.buffer.flush()
        except (ValueError, EOFError) as exc:
            print("Invalid MCP input: " + str(exc), file=sys.stderr)
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
