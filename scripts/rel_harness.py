"""Bounded local access to this checkout's Neyvia MCP adapter (REL ports only)."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

def server():
    spec = importlib.util.spec_from_file_location("rel_neyvia_mcp", REPO / "plugins/neyvia/mcp/neyvia_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Server(module.Backend("http://127.0.0.1:48961"))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool")
    parser.add_argument("arguments", nargs="?", default="{}")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int, default=7000)
    args = parser.parse_args()
    adapter = server()
    description = adapter.call("tools_describe", {"name": args.tool})
    if description.get("isError"):
        print(json.dumps(description, ensure_ascii=False))
        raise SystemExit(1)
    result = adapter.call("tools_call", {"tool": args.tool, "arguments": json.loads(args.arguments)})
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    for block in result.get("content", []):
        if block.get("type") != "text":
            continue
        content = block["text"]
        try:
            decoded = json.loads(content)
            content = decoded.get("text", json.dumps(decoded, ensure_ascii=False, indent=2))
        except ValueError:
            pass
        print(content[:args.limit])
    if result.get("isError"):
        raise SystemExit(1)

if __name__ == "__main__":
    main()
