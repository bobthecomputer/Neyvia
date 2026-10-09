"""Run or inspect autopilot through the production Native permission gateway."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--operation", choices=["start", "get", "list", "stop", "resume"], default="start")
    parser.add_argument("--permission-mode", choices=["read-only", "workspace"], default="workspace")
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.native_access import mutation_tools_for_mode
    gateway = NeyviaToolGateway(args.root, allow_mutations=args.permission_mode != "read-only",
                               permission_mode=args.permission_mode,
                               allowed_mutation_tools=set(mutation_tools_for_mode(args.permission_mode)))
    result = gateway.call_native("neyvia.autopilot." + args.operation, payload)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
