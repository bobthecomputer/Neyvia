"""Measure actual initialized harness prompts and schemas; no model request is sent."""
from __future__ import annotations
import argparse
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

def measure(root: Path, backend: str):
    import tiktoken
    from grant_agent.neyvia_agent import NeyviaAgentConfig, build_neyvia_agent
    from grant_agent.neyvia_mcp_stdio import CompactNeyviaMCPServer
    encoding = tiktoken.get_encoding("o200k_base")
    def counted(tools, prompt):
        schemas = json.dumps(tools, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return {"tools": len(tools), "schemaTokens": len(encoding.encode(schemas)),
                "promptTokens": len(encoding.encode(prompt)),
                "totalTokens": len(encoding.encode(schemas)) + len(encoding.encode(prompt)),
                "names": [row["name"] for row in tools], "prompt": prompt, "schemas": tools}
    config = NeyviaAgentConfig(root=root, session_id="manual-first-meter")
    agent, _, _ = build_neyvia_agent(config, provider=None)
    native = [{"name": tool.name, "description": tool.description, "inputSchema": tool.params_json_schema}
              for tool in agent.tools]
    server = CompactNeyviaMCPServer(root, permission_mode="read-only", session_id="manual-first-meter")
    init = server.handle({"jsonrpc":"2.0", "id":1, "method":"initialize", "params":{}})["result"]
    mcp = server.handle({"jsonrpc":"2.0", "id":2, "method":"tools/list"})["result"]["tools"]
    spec = importlib.util.spec_from_file_location("plugin", REPO / "plugins/neyvia/mcp/neyvia_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plugin = module.Server(module.Backend(backend))
    plugin_tools = plugin.tools()
    plugin_instructions = plugin.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})["result"]["instructions"]
    skill = (REPO / "plugins/neyvia/skills/neyvia/SKILL.md").read_text(encoding="utf-8")
    return {"tokenizer":"tiktoken o200k_base; canonical JSON, not provider billing",
            "scope":"Neyvia-owned initialized prompt + schemas; excludes harness built-ins, hidden wrappers and user task",
            "native": counted(native, str(agent.instructions)),
            "mcp": counted(mcp, init.get("instructions", "")),
            "claude_plugin": counted(plugin_tools, plugin_instructions + "\n" + skill)}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--backend", default="http://127.0.0.1:47931")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    result = measure(args.root, args.backend)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({key:{k:v for k,v in row.items() if k not in {"prompt","schemas","names"}}
                      for key,row in result.items() if isinstance(row,dict)}))
