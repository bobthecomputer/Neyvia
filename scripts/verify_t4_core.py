"""Exercise T4 through real backend HTTP and compact MCP subprocess calls."""
from __future__ import annotations

import hashlib
import http.cookiejar
import json
import os
import socket
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
from grant_agent.neyvia_manuals import unwrap


def run():
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 48141)) == 0:
            raise RuntimeError("Assigned backend port 48141 is already occupied; do not reuse another run")
    root = REPO / ".agent_control" / "T4" / ("run-" + uuid.uuid4().hex)
    root.mkdir(parents=True)
    text = "First line\r\nCafé 🌳 needle\r\nLast line\r\n"
    (root / "notes.txt").write_bytes(text.encode("utf-8"))
    receipt = {"schema": "neyvia.T4.core.v1", "root": str(root), "checks": [], "calls": [],
               "boundary": "actual scratch backend HTTP and real compact MCP subprocess; no model quality or desktop rendering claim"}

    def check(name, condition):
        receipt["checks"].append({"name": name, "ok": bool(condition)})
        if not condition:
            raise RuntimeError(name)

    document = {"version": 1, "requests": 0}

    class Page(BaseHTTPRequestHandler):
        def do_GET(self):
            document["requests"] += 1
            body = ("<html><head><title>T4 source</title></head><body>" +
                    "<p>Observed source paragraph about the stability frontier.</p>" * 100 +
                    f"<p>Revision {document['version']}</p></body></html>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    page = ThreadingHTTPServer(("127.0.0.1", 48142), Page)
    thread = threading.Thread(target=page.serve_forever, daemon=True)
    thread.start()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "src")
    env["NEYVIA_UI_STATE_ROOT"] = str(root)
    env.pop("NEYVIA_UI_BACKEND_URL", None)
    backend_log = (root / "backend.log").open("w", encoding="utf-8")
    backend = subprocess.Popen([sys.executable, str(REPO / "scripts/run_web_backend.py"),
                                "--host", "127.0.0.1", "--port", "48141", "--root", str(root),
                                "--skip-runtime-auto-update"], cwd=REPO, env=env,
                               stdout=backend_log, stderr=backend_log, **hidden_windows_subprocess_kwargs())
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def post(path, payload):
        request = urllib.request.Request("http://127.0.0.1:48141" + path,
                                         data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json"})
        with opener.open(request, timeout=30) as response:
            return json.load(response)

    def call(tool, args, ok=True):
        outer = post("/api/backend", {"command": "call_native_tool_command",
                                     "payload": {"tool": tool, "arguments": args}})
        native = outer["data"]
        if not Path(native["receipt_path"]).is_relative_to(root):
            raise RuntimeError("Receipt came from another backend root")
        receipt["calls"].append({"transport": "backend-http", "tool": tool, "receipt": native})
        check(tool + (" success" if ok else " refused"), native["ok"] is ok)
        return native.get("result") or native

    def start_mcp(mode):
        return subprocess.Popen([sys.executable, "-m", "grant_agent.neyvia_mcp_stdio", "--root", str(root),
                                 "--permission-mode", mode], cwd=REPO, env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", **hidden_windows_subprocess_kwargs())

    processes = []
    try:
        deadline = time.monotonic() + 45
        while True:
            if backend.poll() is not None:
                raise RuntimeError("Scratch backend exited; inspect " + str(root / "backend.log"))
            try:
                ready = post("/api/auth/local-session", {})
                check("scratch backend authenticated", ready["ok"])
                break
            except (OSError, urllib.error.URLError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.2)
        search = call("workspace.search", {"query": "needle", "includeGlob": "**/*.txt"})
        check("workspace search finds observed line", search["matches"][0]["line"] == 2)
        full = call("workspace.read", {"path": "notes.txt"})
        ranged = call("workspace.read", {"path": "notes.txt", "startLine": 2, "endLine": 2,
                                         "expectedSha256": full["sha256"]})
        check("line range retains CRLF and Unicode offsets", ranged["content"] == "Café 🌳 needle\r\n" and ranged["offset"] == len("First line\r\n") and ranged["nextOffset"] is None)
        index = text.index("needle")
        patch_args = {"path": "notes.txt", "expectedSha256": full["sha256"],
                      "edits": [{"start": index, "end": index + 6, "text": "found", "expectedText": "needle"}]}
        result = call("workspace.patch", patch_args)
        expected = text.replace("needle", "found").encode()
        check("patch exact persisted bytes", (root / "notes.txt").read_bytes() == expected and result["readbackVerified"])
        call("workspace.patch", patch_args, ok=False)
        check("stale patch preserved current file", (root / "notes.txt").read_bytes() == expected)
        call("workspace.read", {"path": "notes.txt", "offset": 2, "expectedSha256": full["sha256"]}, ok=False)
        current_hash = hashlib.sha256(expected).hexdigest()
        call("workspace.patch", {"path": "notes.txt", "expectedSha256": current_hash,
                                  "edits": [{"start": 0, "end": 10, "text": "x"}, {"start": 1, "end": 2, "text": "y"}]}, ok=False)
        call("workspace.patch", {"path": "../outside.txt", "expectedSha256": current_hash,
                                  "edits": [{"start": 0, "end": 0, "text": "x"}]}, ok=False)
        check("invalid patches have no effects", (root / "notes.txt").read_bytes() == expected)
        (root / "multi.txt").write_bytes("αβ\r\nend\r\n".encode("utf-8"))
        multiple = call("workspace.read", {"path": "multi.txt"})
        call("workspace.patch", {"path": "multi.txt", "expectedSha256": multiple["sha256"],
                                 "edits": [{"start": 0, "end": 1, "text": "", "expectedText": "α"},
                                           {"start": 4, "end": 7, "text": "tail", "expectedText": "end"}]})
        check("multi-range deletion uses original coordinates", (root / "multi.txt").read_bytes() == "β\r\ntail\r\n".encode("utf-8"))
        url = "http://127.0.0.1:48142/source"
        fetched = call("web.fetch", {"url": url, "maxChars": 200})
        check("fetch returns bounded handle", fetched["document"].startswith("doc_") and fetched["truncated"] and fetched["nextOffset"] == 200)
        cached = call("web.fetch", {"url": url, "maxChars": 200})
        check("URL cache avoids repeat network", cached["cacheHit"] and document["requests"] == 1)
        continuation = call("web.read", {"document": fetched["document"], "offset": 200, "maxChars": 200})
        check("continuation preserves identity", continuation["document"] == fetched["document"] and continuation["offset"] == 200)
        passages = call("web.passages", {"document": fetched["document"], "query": "stability frontier", "limit": 2})
        check("passage search gives continuation and citations", len(passages["matches"]) == 2 and passages["nextOffset"] is not None)
        passage = passages["matches"][0]
        cited = call("web.cite", {"document": fetched["document"], "start": passage["start"], "end": passage["end"], "expectedText": passage["quote"]})
        check("exact source quote citation", cited["citation"] == {key: passage[key] for key in cited["citation"]})
        call("web.cite", {"document": fetched["document"], "start": passage["start"], "end": passage["end"], "expectedText": "invented"}, ok=False)
        document["version"] = 2
        refreshed = call("web.fetch", {"url": url, "refresh": True})
        check("refresh creates new immutable handle", refreshed["document"] != fetched["document"])
        old = call("web.passages", {"document": fetched["document"], "query": "Revision 1"})
        check("old handle survives refresh", old["count"] == 1)
        # Reach tools through the same compact stdio gateway used by model harnesses.
        sequence = 0

        def rpc(proc, name, args):
            nonlocal sequence
            sequence += 1
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": sequence, "method": "tools/call",
                                        "params": {"name": name, "arguments": args}}) + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError("MCP child ended: " + proc.stderr.read()[:1000])
            response = json.loads(line)
            receipt["calls"].append({"transport": "compact-mcp-stdio", "tool": name, "response": response})
            if "error" in response:
                return response
            return response["result"].get("structuredContent") or json.loads(response["result"]["content"][0]["text"])

        writer = start_mcp("workspace")
        processes.append(writer)
        description = rpc(writer, "neyvia.tools.describe", {"name": "workspace.patch"})
        check("compact MCP discovers guarded patch", description.get("name") == "workspace.patch")
        changed = rpc(writer, "neyvia.native.call", {"toolId": "workspace.patch", "actionId": "T4-patch-1",
                                                    "arguments": {"path": "notes.txt", "expectedSha256": current_hash,
                                                                  "edits": [{"start": 0, "end": 5, "text": "Fresh"}]}})
        check("MCP workspace grant verifies real edit", changed.get("ok") and changed.get("operationStatus") == "verified" and (root / "notes.txt").read_bytes().startswith(b"Fresh"))
        replay = rpc(writer, "neyvia.native.call", {"toolId": "workspace.patch", "actionId": "T4-patch-1",
                                                   "arguments": {"path": "notes.txt", "expectedSha256": current_hash,
                                                                 "edits": [{"start": 0, "end": 5, "text": "Fresh"}]}})
        check("mutation action replay avoids duplicate edits", replay.get("ok") and replay.get("duplicateSuppressed"))
        reader = start_mcp("read-only")
        processes.append(reader)
        denied = rpc(reader, "neyvia.native.call", {"toolId": "workspace.patch", "actionId": "T4-denied",
                                                    "arguments": {"path": "notes.txt", "expectedSha256": current_hash,
                                                                  "edits": [{"start": 0, "end": 5, "text": "NO"}]}})
        check("MCP read-only grant refuses patch", denied.get("ok") is False and denied.get("status") == "approval_required")
        persisted = rpc(reader, "neyvia.native.call", {"toolId": "web.passages", "arguments": {"document": fetched["document"], "query": "Revision 1"}})
        check("document handle survives new harness process", persisted.get("ok") and persisted.get("result", {}).get("count") == 1)
        validated = unwrap(rpc(writer, "neyvia.manual.validate", {"id": "tools-depth"}))
        check("new manual validates through actual MCP", validated["manuals"][0].get("grounded") is True)
        manual_inputs = {"path": "notes.txt", "edits": [{"start": 0, "end": 5, "text": "Clear", "expectedText": "Fresh"}],
                         "expectedContent": "Clear" + expected.decode("utf-8")[5:]}
        judged = unwrap(rpc(writer, "neyvia.manual.run", {"id": "tools-depth", "procedure": "guarded-edit", "inputs": manual_inputs}))
        check("manual pauses for snapshot edit judgement", judged.get("status") == "judge" and (root / "notes.txt").read_bytes().startswith(b"Fresh"))
        resumed = unwrap(rpc(writer, "neyvia.manual.run", {"id": "tools-depth", "procedure": "guarded-edit", "runId": judged["runId"], "decisions": {"review-edit": "apply"}}))
        check("manual guarded edit and check really execute", resumed.get("status") == "completed" and resumed["checks"][0]["passed"] and (root / "notes.txt").read_bytes().startswith(b"Clear"))
        research = unwrap(rpc(reader, "neyvia.manual.run", {"id": "tools-depth", "procedure": "cited-research", "inputs": {"url": url, "query": "stability frontier"}}))
        check("manual cached research runs before relevance judge", research.get("status") == "judge" and research["checks"][0]["passed"] and research["results"]["passages"]["count"] == 3)
        receipt["ok"] = True
    except Exception as exc:
        receipt["ok"] = False
        receipt["error"] = str(exc)
        raise
    finally:
        for proc in processes:
            proc.stdin.close()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=8)
            proc.stdout.close()
            proc.stderr.close()
        backend.terminate()
        backend.wait(timeout=10)
        backend_log.close()
        page.shutdown()
        page.server_close()
        output = REPO / "scripts/evidence/T4-core.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": receipt.get("ok"), "checks": len(receipt["checks"]), "receipt": str(output), "error": receipt.get("error")}))
    return receipt


if __name__ == "__main__":
    run()
