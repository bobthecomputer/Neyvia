"""Real authenticated backend/MCP discovery and no-grant refusal on an explicit C1 port."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from grant_agent.neyvia_cua_mcp import CuaMCPServer

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, required=True, choices=range(48701, 48710))
args = parser.parse_args()
server = CuaMCPServer("http://127.0.0.1:" + str(args.port))
started = time.perf_counter()
init = server.handle({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "c1-http-proof"}}})
catalog = server.handle({"id": 2, "method": "tools/list"})
if "error" in catalog:
    raise RuntimeError("Real tool discovery failed: " + str(catalog["error"]))
names = [tool["name"] for tool in catalog["result"]["tools"]]
if not {"adapt_app", "run_flow"} <= set(names):
    raise RuntimeError("Adaptive tools missing from MCP discovery")
refusal = server.handle({"id": 3, "method": "tools/call", "params": {"name": "run_flow", "arguments": {"window_id": 1, "steps": []}}})
result = refusal.get("result", {})
if not result.get("isError") or result.get("structuredContent", {}).get("error", {}).get("code") != "session_pending":
    raise RuntimeError("Unapproved native access was not refused")
receipt = {"schema": "neyvia.c1-http.v1", "port": args.port, "initialize": init,
           "discoveredTools": names, "unapprovedRefusal": refusal, "ok": True,
           "elapsedMs": (time.perf_counter() - started) * 1000,
           "boundary": "Real loopback backend authentication, upstream discovery and MCP no-grant refusal; native action proof is separate"}
(ROOT / "scripts/evidence/C1-http.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"ok": True, "tools": len(names), "port": args.port, "noGrantRefused": True}))
