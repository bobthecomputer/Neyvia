"""Bounded access to this worktree's compact Neyvia MCP server (GUI track)."""
import argparse
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
for key in ("NEYVIA_COORDINATOR_AUTOSTART", "NEYVIA_TOOL_AUTO_UPDATE", "FLUXIO_WATCHDOG_AUTOSTART", "NEYVIA_MOBILE_PROBE_DEVICES"):
    os.environ[key] = "0"
from grant_agent.subprocess_utils import install_hidden_subprocess_default
install_hidden_subprocess_default()
from grant_agent.neyvia_mcp_stdio import CompactNeyviaMCPServer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manual", default="design")
    parser.add_argument("--chapter", default="tokens-themes")
    parser.add_argument("--lines-file", type=Path)
    parser.add_argument("--procedure", help="Execute twice, compile, then replay the owned manual procedure")
    parser.add_argument("--receipt", type=Path, default=Path("D:/NeyviaRuns/gui/harness.json"))
    args = parser.parse_args()
    server = CompactNeyviaMCPServer(REPO, permission_mode="full-access")
    def call(identity, tool, arguments):
        return server.handle({"jsonrpc": "2.0", "id": identity, "method": "tools/call",
                              "params": {"name": tool, "arguments": arguments}})
    def body(response):
        if response.get("error"):
            return {"ok":False,"error":response["error"]}
        value = response.get("result", {}).get("structuredContent", {})
        return value.get("result", value) if value.get("ok") is True else value
    loaded = call(1, "neyvia.manual.load", {"id": args.manual, "chapter": args.chapter})
    result = call(2, "neyvia.cl", {"lines": args.lines_file.read_text(encoding="utf-8")}) if args.lines_file else loaded
    if args.procedure:
        request = {"id": args.manual, "chapter": args.chapter, "procedure": args.procedure, "inputs": {}}
        runs = [call(n, "neyvia.manual.run", request) for n in (3,4)]
        compiled = call(5, "neyvia.manual.compile", {**request,"minRuns":2})
        result = {"runs":runs,"compiled":compiled}
        script_id = body(compiled).get("scriptId")
        if script_id:
            result["replay"] = call(6,"neyvia.manual.script.run",{"scriptId":script_id,"inputs":{}})
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps({"manualLoaded": loaded, "result": result}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"runs":[body(r).get("status") for r in result.get("runs",[])], "compiled":body(result.get("compiled",{})).get("scriptId"), "replay":body(result.get("replay",{})).get("status")} if args.procedure else body(result), ensure_ascii=True)[:2500])
    if args.procedure:
        return 0 if result.get("replay") and all(body(r).get("status") == "completed" for r in [*runs,result["replay"]]) else 1
    return 1 if result.get("error") or result.get("result", {}).get("isError") else 0


if __name__ == "__main__":
    raise SystemExit(main())
