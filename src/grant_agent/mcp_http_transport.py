"""MCP Streamable HTTP client using the standard library (JSON and SSE)."""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Iterator
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .mcp_protocol import NotificationDispatcher, list_all_tools


class _NoRedirect(HTTPRedirectHandler):
    # Never forward configured auth headers to another endpoint implicitly.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def sse_messages(response, *, deadline: float | None = None) -> Iterator[dict[str, Any]]:
    data: list[str] = []
    for raw in response:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("MCP HTTP request timed out")
        line = raw.decode("utf-8").rstrip("\r\n")
        if line == "":
            if data:
                payload = json.loads("\n".join(data))
                data.clear()
                for message in payload if isinstance(payload, list) else [payload]:
                    if not isinstance(message, dict):
                        raise RuntimeError("MCP SSE returned a non-object message")
                    yield message
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))


class StreamableHttpTransport:
    def __init__(self, url: str, *, headers: dict[str, str] | None = None,
                 protocol_version: str = "2025-03-26", request_timeout_s: float = 30) -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("Streamable HTTP requires an http(s) URL without embedded credentials")
        self.url = url
        self.headers = dict(headers or {})
        self.protocol_version = protocol_version
        self.request_timeout_s = max(0.1, float(request_timeout_s))
        self.notifications = NotificationDispatcher()
        self.session_id: str | None = None
        self._initialized = False
        self._next_id = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._listener: threading.Thread | None = None
        self._opener = build_opener(_NoRedirect())
        self.stream_error: str | None = None

    def _open(self, method: str, payload: dict[str, Any] | None = None, *, timeout: float | None = None):
        headers = dict(self.headers)
        headers["Accept"] = "text/event-stream" if method == "GET" else "application/json, text/event-stream"
        if self._initialized:
            headers["MCP-Protocol-Version"] = self.protocol_version
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._opener.open(Request(self.url, data=body, headers=headers, method=method),
                                 timeout=timeout or self.request_timeout_s)

    def _incoming(self, message: dict[str, Any]) -> None:
        if self.notifications.dispatch(message):
            return
        if "method" in message and "id" in message:
            # Sampling/elicitation is not advertised; explicitly reject unsupported requests.
            error = {"jsonrpc": "2.0", "id": message["id"],
                     "error": {"code": -32601, "message": "Client method not supported"}}
            with self._open("POST", error):
                pass

    def _post(self, payload: dict[str, Any]) -> Any:
        deadline = time.monotonic() + self.request_timeout_s
        with self._open("POST", payload) as response:
            if payload.get("method") == "initialize":
                session = response.headers.get("Mcp-Session-Id")
                if session and any(ord(ch) < 0x21 or ord(ch) > 0x7e for ch in session):
                    raise RuntimeError("MCP returned an invalid session ID")
                self.session_id = session
            if "id" not in payload:
                if response.status != 202:
                    raise RuntimeError("MCP notification was not accepted with HTTP 202")
                return None
            content_type = response.headers.get_content_type()
            if content_type == "application/json":
                parsed = json.load(response)
                messages = parsed if isinstance(parsed, list) else [parsed]
            elif content_type == "text/event-stream":
                messages = sse_messages(response, deadline=deadline)
            else:
                raise RuntimeError(f"MCP returned unsupported content type: {content_type}")
            for message in messages:
                if time.monotonic() > deadline:
                    raise TimeoutError("MCP HTTP request timed out")
                if not isinstance(message, dict):
                    raise RuntimeError("MCP HTTP returned a non-object message")
                if message.get("id") == payload["id"] and "method" not in message:
                    if "error" in message:
                        raise RuntimeError(f"MCP {payload['method']} error: {message['error']}")
                    return message.get("result")
                self._incoming(message)
            raise RuntimeError("MCP HTTP response ended without the requested result")

    def _request_unlocked(self, method: str, params: dict[str, Any]) -> Any:
        self._next_id += 1
        return self._post({"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params})

    def _initialize(self) -> None:
        result = self._request_unlocked("initialize", {
            "protocolVersion": self.protocol_version, "capabilities": {},
            "clientInfo": {"name": "neyvia-mcp-broker", "version": "0.1.0"}})
        if not isinstance(result, dict) or not result.get("protocolVersion"):
            raise RuntimeError("MCP returned an invalid initialize result")
        negotiated = str(result["protocolVersion"])
        if negotiated not in {"2025-03-26", "2025-06-18", "2025-11-25"}:
            raise RuntimeError(f"MCP returned an unsupported HTTP protocol version: {negotiated}")
        self.protocol_version = negotiated
        self._initialized = True
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        if self._listener is None or not self._listener.is_alive():
            self._stop.clear()
            self._listener = threading.Thread(target=self._listen, daemon=True)
            self._listener.start()

    def _request(self, method: str, params: dict[str, Any]) -> Any:
        with self._lock:
            if not self._initialized:
                self._initialize()
            try:
                return self._request_unlocked(method, params)
            except HTTPError as exc:
                if exc.code != 404 or not self.session_id:
                    raise
                # A terminated session rejects the request, so retry after a fresh handshake.
                self.session_id = None
                self._initialized = False
                self._initialize()
                return self._request_unlocked(method, params)

    def _listen(self) -> None:
        while not self._stop.is_set():
            listening_session = self.session_id
            try:
                with self._open("GET", timeout=min(2.0, self.request_timeout_s)) as response:
                    if response.headers.get_content_type() != "text/event-stream":
                        raise RuntimeError("MCP GET did not return an SSE stream")
                    for message in sse_messages(response):
                        if self._stop.is_set():
                            return
                        self._incoming(message)
                self.stream_error = None
            except HTTPError as exc:
                if exc.code == 405:
                    return  # Optional standalone notification stream is unsupported.
                self.stream_error = f"HTTP {exc.code}"
                if exc.code == 404:
                    if listening_session != self.session_id:
                        continue
                    return  # Next request establishes a new session.
            except Exception as exc:
                self.stream_error = type(exc).__name__
            self._stop.wait(0.25)

    def list_tools(self) -> list[dict[str, Any]]:
        return list_all_tools(self._request)

    def connect(self) -> None:
        """Complete initialize/initialized without implying tool discovery."""
        with self._lock:
            if not self._initialized:
                self._initialize()

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._request("tools/call", {"name": name, "arguments": dict(arguments)})
        if not isinstance(result, dict):
            raise RuntimeError("MCP tools/call returned an invalid result")
        return result

    def close(self) -> None:
        self._stop.set()
        if self._listener is not None:
            self._listener.join(timeout=2.5)
        with self._lock:
            if self.session_id:
                try:
                    with self._open("DELETE"):
                        pass
                except HTTPError as exc:
                    if exc.code not in {404, 405}:
                        raise
            self.session_id = None
            self._initialized = False
