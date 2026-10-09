"""Reusable Chrome DevTools Protocol client (promoted from control_route_interaction_smoke)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import time
import urllib.parse
import urllib.request
from typing import Any


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def json_get(url: str, *, timeout: float = 10.0) -> object:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class DevToolsSocket:
    def __init__(self, websocket_url: str, *, timeout: float = 10.0) -> None:
        parsed = urllib.parse.urlparse(websocket_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 80
        self.path = parsed.path
        if parsed.query:
            self.path += f"?{parsed.query}"
        self.socket = socket.create_connection((self.host, self.port), timeout=timeout)
        self._handshake()

    def _handshake(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self.socket.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.socket.recv(4096)
            if not chunk:
                break
            response += chunk
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"WebSocket handshake failed: {response[:200]!r}")
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        )
        if accept not in response:
            raise RuntimeError("WebSocket handshake did not return the expected accept key.")

    def send_text(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.socket.sendall(bytes(header) + masked)

    def recv_text(self) -> str:
        while True:
            first = self.socket.recv(2)
            if len(first) < 2:
                raise RuntimeError("WebSocket closed.")
            opcode = first[0] & 0x0F
            masked = bool(first[1] & 0x80)
            length = first[1] & 0x7F
            if length == 126:
                length = struct.unpack("!H", self.socket.recv(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self.socket.recv(8))[0]
            mask = self.socket.recv(4) if masked else b""
            payload = b""
            while len(payload) < length:
                payload += self.socket.recv(length - len(payload))
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode == 0x8:
                raise RuntimeError("WebSocket close frame received.")
            if opcode == 0x9:
                continue
            if opcode in (0x1, 0x0):
                return payload.decode("utf-8", errors="replace")

    def close(self) -> None:
        self.socket.close()


class Cdp:
    """Minimal CDP request/response client over a DevTools websocket."""

    def __init__(self, ws: DevToolsSocket | None, *, transport=None) -> None:
        self.ws, self.transport = ws, transport
        self.next_id = 0

    def send(self, method: str, params: dict[str, object] | None = None) -> object:
        if self.transport is not None:
            return self.transport(method, params or {})
        self.next_id += 1
        message_id = self.next_id
        self.ws.send_text(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.ws.recv_text())
            if message.get("id") == message_id:
                if "error" in message:
                    raise RuntimeError(f"CDP {method} failed: {message['error']}")
                return message.get("result", {})

    def eval(self, expression: str, await_promise: bool = False) -> object:
        result = self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
            },
        )
        remote = result.get("result", {}) if isinstance(result, dict) else {}
        if isinstance(remote, dict) and "value" in remote:
            return remote["value"]
        return remote

    def enable_page(self) -> None:
        self.send("Page.enable")
        self.send("Runtime.enable")

    def enable_accessibility(self) -> None:
        self.send("Accessibility.enable")

    def get_full_ax_tree(self) -> list[dict[str, Any]]:
        result = self.send("Accessibility.getFullAXTree")
        nodes = result.get("nodes") if isinstance(result, dict) else None
        if not isinstance(nodes, list):
            return []
        return [node for node in nodes if isinstance(node, dict)]

    def capture_screenshot_clip(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        format: str = "png",
        scale: float = 1.0,
    ) -> bytes:
        """Page.captureScreenshot with a clip rect (vision page-fault crop path)."""
        clip = {
            "x": max(0.0, float(x)),
            "y": max(0.0, float(y)),
            "width": max(1.0, float(width)),
            "height": max(1.0, float(height)),
            "scale": float(scale) if scale else 1.0,
        }
        result = self.send(
            "Page.captureScreenshot",
            {"format": format, "clip": clip, "fromSurface": True},
        )
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, str) or not data:
            raise RuntimeError("CDP Page.captureScreenshot returned no image data")
        return base64.b64decode(data)


def wait_for_devtools(port: int, *, attempts: int = 40, delay: float = 0.25) -> list[dict[str, object]]:
    for _ in range(attempts):
        try:
            tabs = json_get(f"http://127.0.0.1:{port}/json/list")
            if isinstance(tabs, list) and tabs:
                page_tabs = [
                    tab
                    for tab in tabs
                    if tab.get("type") == "page" and not str(tab.get("url", "")).startswith("chrome-extension:")
                ]
                if page_tabs:
                    return page_tabs
        except Exception:
            time.sleep(delay)
    raise RuntimeError("Chrome DevTools endpoint did not start.")


def connect_cdp(websocket_url: str) -> tuple[DevToolsSocket, Cdp]:
    ws = DevToolsSocket(websocket_url)
    return ws, Cdp(ws)
