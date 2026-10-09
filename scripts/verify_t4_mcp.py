"""Real local MCP protocol journeys, without patching broker or transport calls.

Run with system Python; uses one subprocess and localhost HTTP on port 48148.
The servers are disposable controlled fixtures, not external-provider certification.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def tool(name: str) -> dict:
    return {"name": name, "description": "Controlled local protocol fixture",
            "inputSchema": {"type": "object"},
            "outputSchema": {"type": "object", "properties": {"text": {"type": "string"}},
                             "required": ["text"]},
            "annotations": {"readOnlyHint": True}}


def respond(message: dict) -> dict | None:
    method, params = message.get("method"), message.get("params", {})
    if "id" not in message:
        return None
    if method == "initialize":
        result = {"protocolVersion": params["protocolVersion"], "capabilities": {"tools": {}},
                  "serverInfo": {"name": "t4-controlled-local", "version": "1"}}
    elif method == "tools/list":
        result = ({"tools": [tool("echo")], "nextCursor": "page-2"} if not params.get("cursor")
                  else {"tools": [tool("failure"), tool("invalid_output")]})
    elif method == "tools/call":
        name = params["name"]
        structured = {"text": str(params.get("arguments", {}).get("text", ""))}
        if name == "invalid_output":
            structured = {"text": 42}
        result = {"content": [{"type": "text", "text": json.dumps(structured)}],
                  "structuredContent": structured, "isError": name == "failure"}
    else:
        return {"jsonrpc": "2.0", "id": message["id"],
                "error": {"code": -32601, "message": "unknown method"}}
    return {"jsonrpc": "2.0", "id": message["id"], "result": result}


def stdio_server() -> None:
    for line in sys.stdin.buffer:
        message = json.loads(line)
        result = respond(message)
        if result is not None:
            sys.stdout.buffer.write(json.dumps(result).encode() + b"\n")
            if message.get("method") == "initialize":
                sys.stdout.buffer.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/ready"}).encode() + b"\n")
            sys.stdout.buffer.flush()


class HttpFixture(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    expired = False
    fail_next = False
    calls: list[dict] = []

    def log_message(self, *args) -> None:
        pass

    def send(self, status: int, payload: dict | None = None) -> None:
        body = json.dumps(payload).encode() if payload is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Mcp-Session-Id", "t4-fixture-session")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self.send(405)

    def do_DELETE(self) -> None:
        self.send(204)

    def do_POST(self) -> None:
        message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).calls.append({"method": message.get("method"), "params": message.get("params"),
                                 "session": self.headers.get("Mcp-Session-Id")})
        if type(self).fail_next and message.get("method") == "tools/call":
            type(self).fail_next = False
            self.send(503)
            return
        if type(self).expired and message.get("method") == "tools/call":
            type(self).expired = False
            self.send(404)
            return
        result = respond(message)
        if message.get("method") == "tools/call" and message.get("params", {}).get("arguments", {}).get("listChanged"):
            result = [{"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}, result]
        self.send(200 if result else 202, result)


def run_journey(broker, server: str) -> dict:
    stages = [broker.get_server(server).compact(include_observations=True)]
    assert stages[-1]["readiness"] == "configured" and not stages[-1]["connected"]
    found = broker.search("", server=server)
    stages.append(broker.get_server(server).compact(include_observations=True))
    assert len(found) == 3 and stages[-1]["readiness"] == "discovered"
    assert not stages[-1]["verified"]
    success = broker.call(server, "echo", {"text": f"real-{server}"})
    stages.append(broker.get_server(server).compact(include_observations=True))
    assert success["ok"] and stages[-1]["readiness"] == "verified"
    assert Path(stages[-1]["verificationReceipt"]).is_file()
    failure = broker.call(server, "failure", {})
    stages.append(broker.get_server(server).compact(include_observations=True))
    assert not failure["ok"] and stages[-1]["readiness"] == "failing"
    assert not stages[-1]["verified"]
    recovered = broker.call(server, "echo", {"text": "recovered"})
    assert recovered["ok"] and broker.get_server(server).readiness == "verified"
    invalid = broker.call(server, "invalid_output", {})
    assert not invalid["ok"] and broker.get_server(server).readiness == "failing"
    final = broker.call(server, "echo", {"text": "valid-again"})
    assert final["ok"]
    stages.append(broker.get_server(server).compact(include_observations=True))
    history = stages[-1]["observations"]
    assert {"configured", "connected", "discovered", "verified", "failing"} <= {o["stage"] for o in history}
    return {"stages": stages, "receipts": [success, failure, recovered, invalid, final]}


def verify(port: int = 48148, output: Path | None = None) -> dict:
    from grant_agent.mcp_broker import McpOutboundBroker
    from grant_agent.progressive_tools import ProgressiveToolSurface
    from grant_agent.mcp_broker import register_with_progressive_surface

    if not 48141 <= port <= 48149:
        raise ValueError("T4 ports are restricted to 48141-48149")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    scratch = ROOT / ".agent_control" / "t4_mcp_verify" / stamp
    http = ThreadingHTTPServer(("127.0.0.1", port), HttpFixture)
    listener = threading.Thread(target=http.serve_forever, daemon=True)
    listener.start()
    config = {"servers": {
        "stdio": {"command": sys.executable, "args": [str(Path(__file__).resolve()), "--stdio-server"],
                  "framing": "newline", "requestTimeoutS": 4},
        "http": {"url": f"http://127.0.0.1:{port}/mcp", "requestTimeoutS": 4},
        "stub": {"transport": "stub", "authState": "authenticated", "tools": [tool("echo")]},
    }}
    broker = McpOutboundBroker(scratch, config=config)
    try:
        report = {"schema": "neyvia.t4.mcp_real_journey.v1", "generatedAt": stamp,
                  "fixtures": "real local JSON-RPC subprocess and HTTP fixture; no external-provider claim",
                  "stdio": run_journey(broker, "stdio"), "http": run_journey(broker, "http")}
        HttpFixture.expired = True
        session_recovery = broker.call("http", "echo", {"text": "new-session"})
        assert session_recovery["ok"]
        HttpFixture.fail_next = True
        network_failure = broker.call("http", "echo", {"text": "503"})
        assert not network_failure["ok"] and broker.get_server("http").readiness == "failing"
        network_recovery = broker.call("http", "echo", {"text": "network-recovered"})
        assert network_recovery["ok"] and network_recovery["verified"]
        stub = broker.call("stub", "echo", {"text": "simulation"})
        assert stub["ok"] and not stub["verified"] and stub["simulation"]
        actual_notifications = broker.notifications("stdio")
        assert any(row["method"] == "notifications/ready" for row in actual_notifications)
        assert broker.get_server("stdio").readiness == "verified"
        auth_before = len(HttpFixture.calls)
        broker.set_auth_state("http", "expired")
        auth_block = broker.call("http", "echo", {"text": "blocked"})
        assert auth_block["status"] == "auth_required" and len(HttpFixture.calls) == auth_before
        broker.set_auth_state("http", "authenticated")
        auth_recovery = broker.call("http", "echo", {"text": "auth-recovered"})
        assert auth_recovery["ok"] and auth_recovery["verified"]
        list_changed = broker.call("http", "echo", {"text": "list-changed", "listChanged": True})
        assert list_changed["ok"] and not list_changed["verified"]
        assert broker.get_server("http").readiness == "connected"
        changed_discovery = broker.search("echo", server="http")
        assert changed_discovery and broker.get_server("http").readiness == "discovered"
        list_recovery = broker.call("http", "echo", {"text": "catalog-recovered"})
        assert list_recovery["verified"]
        surface = ProgressiveToolSurface()
        registered = register_with_progressive_surface(surface, broker)
        visible = surface.call("mcp.servers", {})
        searched = surface.call("mcp.search", {"server": "http", "query": "echo"})
        described = surface.call("mcp.describe", {"server": "http", "tool": "echo"})
        called = surface.call("mcp.call", {"server": "http", "tool": "echo", "arguments": {"text": "progressive-real"}})
        assert visible["servers"] and searched["tools"] and described["inputSchema"] and called["ok"]
        report.update(httpSessionRecovery=session_recovery, httpFailure=network_failure,
                      httpRecovery=network_recovery, stub=stub, httpProtocolCalls=HttpFixture.calls,
                      authBlocked=auth_block, authRecovery=auth_recovery,
                      catalogChanged=list_changed, catalogRecovery=list_recovery,
                      stdioNotifications=actual_notifications,
                      progressive={"registered": registered, "servers": visible, "search": searched,
                                   "describe": described, "call": called},
                      finalServers=broker.list_servers(), ok=True)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report
    finally:
        broker.close()
        http.shutdown()
        http.server_close()
        listener.join(timeout=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdio-server", action="store_true")
    parser.add_argument("--port", type=int, default=48148)
    parser.add_argument("--output", type=Path, default=ROOT / "scripts" / "evidence" / "T4-mcp.json")
    args = parser.parse_args()
    if args.stdio_server:
        stdio_server()
    else:
        result = verify(args.port, args.output)
        print(json.dumps({"ok": result["ok"], "receipt": str(args.output),
                          "transports": ["stdio", "streamable-http"], "stages": 5}))
