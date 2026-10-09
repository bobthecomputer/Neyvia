"""Real CL 1.1 calls through plugin, HTTP, web dispatch and desktop forwarding."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if args.port not in range(48521, 48530):
        parser.error("only assigned INTCL ports")
    root = args.root.resolve()
    if not root.is_relative_to(REPO):
        parser.error("backend root must be inside this worktree")
    base = f"http://127.0.0.1:{args.port}"
    os.environ.update(NEYVIA_UI_BACKEND_URL=base, NEYVIA_TOOL_AUTO_UPDATE="0",
                      NEYVIA_COORDINATOR_AUTOSTART="0", FLUXIO_WATCHDOG_AUTOSTART="0")
    spec = importlib.util.spec_from_file_location("intcl_plugin", REPO / "plugins/neyvia/mcp/neyvia_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    backend = module.Backend(base)
    server = module.Server(backend)
    transcripts, checks = {}, {}
    def capture(key, operation):
        try:
            value = operation()
        except Exception as exc:
            value = {"proofError": str(exc)}
        transcripts[key] = value
        return value
    def tool(name, arguments):
        return backend.request("/api/ui/tools/call", {"tool": name, "arguments": arguments})
    def result(value):
        return value.get("data", {}).get("result", {})
    def mcp(method, params=None):
        return server.handle({"jsonrpc": "2.0", "id": len(transcripts) + 1,
                              "method": method, "params": params or {}})
    health = capture("health", lambda: backend.request("/api/health"))
    checks["health"] = health.get("ok") is True
    initialized = capture("plugin_initialize", lambda: mcp("initialize"))
    checks["plugin_L0_primer"] = "L notes " in initialized.get("result", {}).get("instructions", "")
    catalog = capture("plugin_tools_list", lambda: mcp("tools/list"))
    names = {row["name"] for row in catalog.get("result", {}).get("tools", [])}
    checks["plugin_deferred_start"] = names == {"cl", "cl_describe", "tools_search", "tools_describe", "tools_call"}
    descriptions = capture("plugin_describe", lambda: mcp("tools/call", {"name": "cl_describe", "arguments": {"layer": "time"}}))
    checks["plugin_describe_route"] = "time.now" in str(descriptions)
    read = capture("plugin_cl", lambda: mcp("tools/call", {"name": "cl", "arguments": {"lines": "time.now()"}}))
    checks["plugin_cl_route"] = "R time.now ok" in str(read)
    denied = capture("plugin_scope_denied", lambda: mcp("tools/call", {"name": "cl", "arguments": {"lines": 'workspace.read(path="outside.txt")'}}))
    checks["plugin_existing_scope_preserved"] = denied.get("result", {}).get("isError") is True
    premature = capture("http_done_without_G", lambda: tool("neyvia.cl", {"lines": "done()"}))
    for name, arguments, expected in (("neyvia.cl.describe", {"primer": True}, "L notes "),
                                      ("neyvia.cl", {"lines": "time.now()"}, "R time.now ok")):
        key = name.replace(".", "_")
        direct = capture("http_" + key, lambda n=name, a=arguments: tool(n, a))
        checks["http_" + key] = expected in str(result(direct))
        dispatch = capture("web_dispatch_" + key,
                           lambda n=name, a=arguments: backend.request("/api/backend", {
                               "command": "call_native_tool_command", "payload": {"tool": n, "arguments": a}}))
        checks["web_dispatch_" + key] = expected in str(dispatch)
        from grant_agent.desktop_bridge import dispatch_desktop_command
        desktop = capture("desktop_forward_" + key,
                          lambda n=name, a=arguments: dispatch_desktop_command(root, "call_native_tool_command", {"tool": n, "arguments": a}))
        checks["desktop_forward_" + key] = expected in str(desktop)
    notes = root / "intcl-proof-notes"
    capture("owner_notes_folder", lambda: tool("neyvia.notes.folder", {"folder": str(notes)}))
    capture("owner_notes_write", lambda: tool("neyvia.notes.write", {"path": "proof.md", "body": "INTCL original\n"}))
    authored = capture("http_authored_G", lambda: tool("neyvia.cl", {
        "lines": 'G: notes.read(path="proof.md").body == "INTCL original\\n"'}))
    finished = capture("http_done_with_G", lambda: tool("neyvia.cl", {"lines": "done()"}))
    checks["HTTP_context_retains_observer_G"] = result(authored).get("ok") is True and result(finished).get("doneStatus") == "ok"
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "neyvia.cl.describe", "arguments": {"primer": True}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "neyvia.cl", "arguments": {"lines": "done()"}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "neyvia.cl", "arguments": {"lines": 'G: notes.read(path="proof.md").body == "INTCL procedure\\n" and notes.read(path="proof.md").pinned == True\nrun notes.write-and-pin(path="proof.md", body="INTCL procedure\\n", replace_note="replace")\ndone()'}}},
    ]
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    try:
        completed = subprocess.run([sys.executable, "-m", "grant_agent.neyvia_mcp_stdio", "--root", str(root),
                                    "--native-mutation-tool", "neyvia.notes.write", "--native-mutation-tool", "neyvia.notes.pin"], input="\n".join(json.dumps(row) for row in requests) + "\n",
                                   text=True, encoding="utf-8", capture_output=True, timeout=600, env=env)
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        errors = exc.stderr or ""
        completed = subprocess.CompletedProcess(exc.cmd, -1,
            output.decode("utf-8", errors="replace") if isinstance(output, bytes) else output,
            (errors.decode("utf-8", errors="replace") if isinstance(errors, bytes) else errors) + "\nINTCL native stdio deadline exceeded")
    stdio = [json.loads(line) for line in completed.stdout.splitlines() if line.startswith("{")]
    transcripts["native_stdio"] = {"exitCode": completed.returncode, "responses": stdio, "stderr": completed.stderr[-1000:]}
    checks["native_stdio_describe"] = len(stdio) == 5 and "L notes " in str(stdio[2])
    checks["done_requires_G"] = len(stdio) == 5 and stdio[3].get("result", {}).get("isError") is True and "R done unverified" in str(stdio[3])
    checks["native_stdio_procedure_done"] = len(stdio) == 5 and stdio[4].get("result", {}).get("isError") is False and "R done ok" in str(stdio[4])
    after = capture("independent_notes_readback", lambda: tool("neyvia.notes.read", {"path": "proof.md"}))
    checks["procedure_bytes_and_pin"] = result(after).get("body") == "INTCL procedure\n" and result(after).get("pinned") is True
    proof = {"schema": "neyvia.intcl.http.v1", "base": base, "root": str(root),
             "checks": checks, "allPassed": all(checks.values()), "transcripts": transcripts,
             "boundary": "Authenticated owned localhost, actual plugin requests, web dispatch, desktop persistent forwarding and native stdio; no public service"}
    destination = REPO / "scripts/evidence/intcl/http.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"allPassed": proof["allPassed"], "checks": checks, "receipt": str(destination)}))
    return int(not proof["allPassed"])


if __name__ == "__main__":
    raise SystemExit(main())
