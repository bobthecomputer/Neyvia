"""Bounded command-line bridge to this worktree's Neyvia MCP/CL gateway."""
import argparse
import json
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.neyvia_mcp_stdio import CompactNeyviaMCPServer

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lines")
    args = parser.parse_args()
    server = CompactNeyviaMCPServer(REPO, permission_mode="full-access", session_id="dogfix")
    result = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "neyvia.cl", "arguments": {"lines": args.lines, "actionId": "dogfix-" + uuid.uuid4().hex}}})
    value = result.get("result", {}).get("structuredContent", {})
    raw = value.get("text") or json.dumps(result)
    log = REPO / ".agent_control/dogfix/cl.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        stream.write(raw + "\n")
    print("\n".join(line for line in raw.splitlines() if line.startswith(("R ", "X ", "Q "))))
    raise SystemExit(0 if value.get("ok") else 1)
