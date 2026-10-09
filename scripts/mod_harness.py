"""Task-local controller for this checkout's real, authenticated Neyvia MCP."""
import argparse
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]


def server(base_url):
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port not in range(48871, 48890):
        raise ValueError("Assign an owned loopback port within 48871-48889")
    spec = importlib.util.spec_from_file_location("mod_mcp", REPO / "plugins/neyvia/mcp/neyvia_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Server(module.Backend(base_url))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--arguments", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()
    adapter = server(args.base_url)
    result = adapter.call("tools_call", {"tool": args.tool,
        "arguments": json.loads(args.arguments.read_text(encoding="utf-8")) if args.arguments else {}})
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for block in result.get("content", []):
        if block.get("type") == "text":
            print(block["text"][:args.limit])
    raise SystemExit(1 if result.get("isError") else 0)
