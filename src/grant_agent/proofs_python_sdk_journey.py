"""Outcome proof for the Python Neyvia SDK's typed HTTP 400 boundary."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


HOST = "127.0.0.1"
PORT = 49081
CONTRACT = "p22.python-sdk-http-boundary"
CONTRACTS = (CONTRACT,)


class _ObservedHTTP(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def self_check(root: Any = None) -> dict[str, Any]:
    """Require the real client to preserve a typed 400 from an owned observer."""
    from .contract_gate import wants
    from .proof_ports import proof_port

    started = time.perf_counter()
    if not wants(CONTRACTS):
        return {"ok": True, "contracts": [], "cases": [], "durationMs": 0}
    port = proof_port(48461)

    requests: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            return

        def do_POST(self) -> None:
            if self.path != "/api/backend":
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(size).decode("utf-8"))
            except (ValueError, UnicodeError):
                self.send_error(400)
                return
            requests.append({
                "path": self.path,
                "contentType": self.headers.get("Content-Type", ""),
                "body": body,
            })
            encoded = json.dumps({
                "ok": False,
                "error": "Invalid request shape",
                "code": "invalid_request",
            }).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = _ObservedHTTP((HOST, port), Handler)
    thread = threading.Thread(target=server.serve_forever, name="p22-python-sdk-http-400", daemon=True)
    thread.start()
    try:
        from neyvia_sdk import NeyviaClient, NeyviaError

        client = NeyviaClient(f"http://{HOST}:{port}", timeout=2.0)
        rejected_payload = {"field": "invalid"}
        try:
            client.command("reject_invalid", rejected_payload)
        except NeyviaError as error:
            if (error.status != 400 or error.code != "invalid_request"
                    or str(error) != "Invalid request shape"):
                raise AssertionError("Python SDK changed the HTTP 400 status, code, or message") from error
        else:
            raise AssertionError("Python SDK accepted the HTTP 400 refusal")

        expected_request = {
            "path": "/api/backend",
            "contentType": "application/json",
            "body": {"command": "reject_invalid", "payload": rejected_payload},
        }
        if requests != [expected_request]:
            raise AssertionError("Python SDK changed the request that received the typed HTTP 400")

        case = {
            "id": CONTRACT,
            "contracts": list(CONTRACTS),
            "ok": True,
            "observed": {"status": 400, "code": "invalid_request", "requestCount": len(requests), "port": port},
        }
        return {
            "ok": True,
            "contracts": list(CONTRACTS),
            "cases": [case],
            "failures": [],
            "durationMs": round((time.perf_counter() - started) * 1000, 2),
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)
        if thread.is_alive():
            raise RuntimeError("Owned SDK HTTP observer did not stop")
