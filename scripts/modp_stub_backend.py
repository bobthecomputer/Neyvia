"""MODP evidence script: a small local stand-in for plan 29 section A (the Claude Code mod <-> Neyvia contract).

Not a test and not Neyvia: it only answers the six mod endpoints with fixed, deterministic data so the mod can be
developed and proven before (and next to) the real backend. Port block 49211-49219 by default. Standard library only.

    python scripts/modp_stub_backend.py --port 49211 --log D:/NeyviaRuns/29-MODP/stub-requests.jsonl

Control (for the proof driver): POST /stub/set {...config}, POST /stub/enqueue {session, event}, GET /stub/log.
The stop gate is real in one way: it fails until PROOF_OK.txt exists in the session's cwd, then passes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MOD = "/api/ui/claude-code/mod"
LOCK = threading.Lock()

SECTION = (
    "Neyvia is running next to you on this PC. Its tools are listed under the neyvia server: activity shows what other "
    "agents are doing, message talks to one, plan_update publishes your checklist, manual_run runs a Neyvia manual, "
    "laya_look describes a screenshot. Less common tools are behind ToolSearch. Before editing a file another agent "
    "holds, ask with message. Keep answers short."
)
TOOLS = [
    ("activity", "neyvia.activity", "What every running agent, session and mission is doing now.", {"type": "object", "properties": {}}),
    ("message", "neyvia.message", "Send a short message to another agent or session.",
     {"type": "object", "properties": {"to": {"type": "string"}, "text": {"type": "string"}}, "required": ["to", "text"]}),
    ("tools_search", "neyvia.tools.search", "Find Neyvia tool names by purpose.", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}),
    ("tools_describe", "neyvia.tools.describe", "Load one Neyvia tool schema.", {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}),
    ("tools_call", "neyvia.tools.call", "Call a discovered Neyvia tool.", {"type": "object", "properties": {"tool": {"type": "string"}, "arguments": {"type": "object"}}, "required": ["tool"]}),
    ("manual_run", "neyvia.manual.run", "Run a Neyvia manual procedure.", {"type": "object", "properties": {"id": {"type": "string"}, "procedure": {"type": "string"}}, "required": ["id"]}),
    ("plan_update", "neyvia.plan.update", "Publish the checklist for this work.",
     {"type": "object", "properties": {"plan": {"type": "array", "items": {"type": "object"}}}, "required": ["plan"]}),
    ("laya_look", "neyvia.laya.look", "Describe a screenshot or window as text.", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}),
    ("timer_start", "neyvia.timer.start", "Start a named timer.", {"type": "object", "properties": {"name": {"type": "string"}}}),
    ("pdf_open", "neyvia.pdf.open", "Open a PDF in Neyvia.", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}),
]
ROLES = [
    {"name": "scout", "description": "Reads and reports; never edits.", "prompt": "You are a scout. Read, search and report in under 100 words. Do not edit files.", "model": "claude-haiku-5-5", "effort": "low", "tools": ["Read", "Grep", "Glob"]},
    {"name": "builder", "description": "Makes the change.", "prompt": "You are a builder. Make the smallest correct change and say what you changed.", "model": "claude-sonnet-5-5", "effort": "medium"},
    {"name": "verifier", "description": "Checks the work with fresh eyes.", "prompt": "You are a verifier. Check the result against the request and report pass or fail with one reason.", "model": "claude-opus-5-5", "effort": "high", "tools": ["Read", "Grep", "Glob", "Bash"]},
]

CONFIG = {
    "denyPaths": [],
    "claims": [],
    "gate_enabled": True,
    "gate_max_blocks": 2,
    "stop_delay": 0.0,
    "bootstrap_delay": 0.0,
    "state_version": 0,
    "state_text": "",
    "budget": {"blockSpawn": False, "reason": ""},
    "extra_tools": 0,
}
SESSIONS: dict[str, dict] = {}
LOG: list[dict] = []
LOG_FILE: str | None = None


def extra_tools() -> list[dict]:
    return [{"name": f"extra_{i:03d}", "neyviaName": f"neyvia.extra.t{i:03d}", "description": f"Extra stub tool {i}.", "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}}, "deferred": True} for i in range(CONFIG["extra_tools"])]


def bootstrap() -> dict:
    return {
        "version": "stub-1",
        "section": {"text": SECTION},
        "context": {"text": "Neyvia memory digest: the person prefers short answers. Work board: nothing claimed."},
        "tools": sorted([{"name": n, "neyviaName": nn, "description": d, "inputSchema": s, "deferred": n not in {"activity", "message", "tools_search", "tools_describe", "tools_call", "manual_run", "plan_update", "laya_look"}} for n, nn, d, s in TOOLS] + extra_tools(), key=lambda row: row["name"]),
        "rules": {"denyPaths": CONFIG["denyPaths"], "claims": CONFIG["claims"]},
        "gate": {"enabled": CONFIG["gate_enabled"], "contracts": ["proof-file-exists"]},
        "roles": ROLES,
        "budget": CONFIG["budget"],
    }


def session_state(session: str) -> dict:
    return SESSIONS.setdefault(session, {"blocks": 0, "state_hash": "", "inbox": [], "inbox_seq": 0, "cwd": ""})


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):  # quiet
        return

    def handle(self):
        try:
            super().handle()
        except (ConnectionError, OSError):
            pass

    def _record(self, body):
        row = {"t": round(time.time(), 3), "method": self.command, "path": self.path, "mod": self.headers.get("X-Neyvia-Mod", ""),
               "inm": self.headers.get("If-None-Match", ""), "body": body}
        with LOCK:
            LOG.append(row)
            if LOG_FILE:
                with open(LOG_FILE, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row) + "\n")

    def _send(self, status: int, payload=None, headers: dict | None = None):
        data = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode() or "{}")
        except ValueError:
            return {}

    def do_GET(self):
        url = urlparse(self.path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        self._record(query)
        if url.path == "/stub/log":
            return self._send(200, {"log": LOG})
        if url.path == MOD + "/bootstrap":
            time.sleep(CONFIG["bootstrap_delay"])
            document = bootstrap()
            etag = '"' + hashlib.sha1(json.dumps(document, sort_keys=True).encode()).hexdigest()[:16] + '"'
            if query.get("cwd"):
                session_state(query.get("session", ""))["cwd"] = query["cwd"]
            if self.headers.get("If-None-Match") == etag:
                return self._send(304, None, {"ETag": etag})
            return self._send(200, document, {"ETag": etag})
        if url.path == MOD + "/state":
            state = session_state(query.get("session", ""))
            current = hashlib.sha1(f"{CONFIG['state_version']}".encode()).hexdigest()[:10]
            diff = None if state["state_hash"] == current or not CONFIG["state_text"] else CONFIG["state_text"]
            state["state_hash"] = current
            return self._send(200, {"ok": True, "hash": current, "diff": None if diff is None else {"text": diff, "parts": {"stub": diff}, "removed": []}})
        if url.path == MOD + "/inbox":
            state = session_state(query.get("session", ""))
            since = int(query.get("since") or 0)
            events = [event for event in state["inbox"] if event["id"] > since]
            return self._send(200, {"events": events, "next": str(state["inbox_seq"])})
        self._send(404, {"ok": False, "error": "unknown"})

    def do_POST(self):
        url = urlparse(self.path)
        body = self._body()
        self._record(body)
        if url.path == "/api/auth/local-session":
            return self._send(200, {"ok": True}, {"Set-Cookie": "neyvia_stub=1; Path=/; HttpOnly"})
        if self.headers.get("Cookie", "").find("neyvia_stub=1") < 0 and url.path.startswith(MOD):
            return self._send(401, {"ok": False, "error": "sign in"})
        if url.path == "/stub/set":
            CONFIG.update(body)
            return self._send(200, {"ok": True, "config": CONFIG})
        if url.path == "/stub/enqueue":
            state = session_state(body.get("session", ""))
            state["inbox_seq"] += 1
            state["inbox"].append({"id": state["inbox_seq"], **body.get("event", {})})
            return self._send(200, {"ok": True, "id": state["inbox_seq"]})
        if url.path == MOD + "/tool":
            tool, args = body.get("tool", ""), body.get("args") or {}
            if tool == "neyvia.activity":
                result = {"agents": [{"name": "Codex Luna", "doing": "running the regression floor", "state": "running", "files": ["src/a.py"]}]}
            elif tool == "neyvia.message":
                result = {"delivered": True, "to": args.get("to"), "queued_for": "next --resume turn"}
            elif tool == "neyvia.work.claim":
                result = {"claim": {"id": "claim-" + hashlib.sha1(json.dumps(args, sort_keys=True).encode()).hexdigest()[:8]}}
            elif tool == "neyvia.work.release":
                result = {"released": True}
            else:
                result = {"echo": tool, "args": args}
            return self._send(200, {"ok": True, "result": result})
        if url.path == MOD + "/stop":
            time.sleep(CONFIG["stop_delay"])
            session = body.get("session", "")
            state = session_state(session)
            proof = os.path.join(state.get("cwd") or ".", "PROOF_OK.txt")
            failing = [] if os.path.exists(proof) else [{"contract": "proof-file-exists", "hint": "Create PROOF_OK.txt in the project folder with the single word ok, then finish."}]
            if failing and state["blocks"] < CONFIG["gate_max_blocks"]:
                state["blocks"] += 1
                reason = "Neyvia: " + " ".join(f"[{row['contract']}] {row['hint']}" for row in failing)
                return self._send(200, {"ok": True, "block": reason, "failing": failing, "receipt": {"passed": False, "blocks": state["blocks"], "note": "blocked"}, "blocksSoFar": state["blocks"]})
            receipt = {"passed": not failing, "blocks": state["blocks"], "note": "all contracts passed" if not failing else "unproven: block limit reached"}
            return self._send(200, {"ok": True, "block": None, "failing": failing, "receipt": receipt, "blocksSoFar": state["blocks"]})
        if url.path == MOD + "/report":
            return self._send(200, {"ok": True})
        self._send(404, {"ok": False, "error": "unknown"})


def main() -> int:
    global LOG_FILE
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=49211)
    parser.add_argument("--log", default="")
    args = parser.parse_args()
    LOG_FILE = args.log or None
    if LOG_FILE:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    ThreadingHTTPServer.allow_reuse_address = False  # on Windows a reused port would let two stubs answer at once
    ThreadingHTTPServer.daemon_threads = True
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"modp stub on http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
