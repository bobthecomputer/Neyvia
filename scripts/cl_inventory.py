"""Inventory the actual agent-facing contracts before and after CL migration."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def inventory(root: Path, *, grounded: bool = False) -> dict:
    from grant_agent.native_tools import NativeToolRegistry
    from grant_agent.neyvia_manuals import records, get_manual, validate

    registry = NativeToolRegistry(root)
    tools = registry.list_tools(include_unavailable=True, include_schemas=True)
    manuals = []
    for row in records():
        _, digest, data = get_manual(row["id"])
        manuals.append({"id": row["id"], "source": row["path"], "sha256": digest,
                        "chapters": list(data["chapters"]),
                        "actions": sorted({action["tool"] for chapter in data["chapters"].values()
                                           for action in chapter["actions"].values()})})
        if grounded:
            try:
                manuals[-1]["grounding"] = {"ok": True, "result": validate(data, registry)}
            except (ValueError, KeyError) as exc:
                manuals[-1]["grounding"] = {"ok": False, "error": str(exc)}
    sources = {
        "manuals": ["neyvia_manuals.py", "manual_contracts.py", "manual_first.py"],
        "native_tools": ["native_tools.py", "neyvia_workspace_tools.py"],
        "managed_mcp": ["neyvia_mcp_stdio.py", "neyvia_agent.py", "mcp_protocol.py"],
        "perception": ["neyvia_perception.py", "perception_frames.py", "perception_browser.py"],
        "native_window": ["neyvia_cua.py", "computer_use_twin.py"],
        "run_plan_receipts": ["neyvia_intent_plan.py", "action_receipts.py", "manual_state.py"],
        "system_context": ["manual_first.py", "neyvia_agent.py", "connected_sessions/codex.py", "connected_sessions/claude.py"],
    }
    return {"schema": "neyvia.cl.inventory.v1", "tools": tools, "manuals": manuals,
            "families": sorted({row["name"].split(".")[1] if row["name"].startswith("neyvia.") else row["name"].split(".")[0] for row in tools}),
            "surfaces": [{"surface": key, "owners": [{"path": "src/grant_agent/" + name,
                            "exists": (REPO / "src/grant_agent" / name).is_file()} for name in names]} for key, names in sources.items()]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO / ".agent_control/cl/runtime")
    parser.add_argument("--output", type=Path, default=REPO / ".agent_control/cl/inventory.json")
    parser.add_argument("--grounded", action="store_true", help="Also validate existing executable manual contracts")
    args = parser.parse_args()
    result = inventory(args.root.resolve(), grounded=args.grounded)
    raw = json.dumps(result, ensure_ascii=False, indent=2).encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(raw)
    print(json.dumps({"tools": len(result["tools"]), "manuals": len(result["manuals"]),
                      "families": len(result["families"]), "output": str(args.output),
                      "sha256": hashlib.sha256(raw).hexdigest()}))
    if args.grounded:
        failures = [{"id": row["id"], **row["grounding"]} for row in result["manuals"] if not row["grounding"]["ok"]]
        print(json.dumps({"groundedManuals": len(result["manuals"]) - len(failures), "failures": failures}))
        return int(bool(failures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
