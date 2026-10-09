"""Run production CL syntax/semantic audits without executing tool effects."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.cl.manuals import cl_to_manual
from grant_agent.cl.schema import cl_to_mcp, mcp_to_cl
from grant_agent.cl.validator import validate_document
from grant_agent.native_tools import NativeToolRegistry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO / ".agent_control/cl/conformance-runtime")
    parser.add_argument("--receipt", type=Path, default=REPO / ".agent_control/cl/conformance.json")
    parser.add_argument("--strict", action="store_true", help="Return failure when any audited document is not conformant")
    args = parser.parse_args()
    registry = NativeToolRegistry(args.root)
    # Registry DTOs contain tuples; MCP transports JSON arrays. Compare the
    # actual canonical JSON boundary, not Python-only tuple/list identity.
    rows = json.loads(json.dumps(registry.list_tools(include_unavailable=True, include_schemas=True), ensure_ascii=False, allow_nan=False))
    results = []
    known = {row["name"]: {"effect": None if row.get("mutability_class") in {"read", "none"} else "!"} for row in rows}
    for name in ("neyvia.notes.write", "neyvia.notes.pin", "neyvia.notes.folder", "neyvia.notes.open"):
        if name in known:
            known[name]["effect"] = "!"
    def audit(identity, source, kind, extra=None):
        result = validate_document(source, external_actions=known)
        results.append({"id": identity, "kind": kind, "sha256": hashlib.sha256(source.encode()).hexdigest(), **result, **(extra or {})})
    source = mcp_to_cl(rows)
    if cl_to_mcp(source) != rows:
        raise ValueError("Native inventory MCP roundtrip changed a tool contract")
    audit("native-inventory", source, "inventory", {"roundtrip_equal": True, "tools": len(rows)})
    families = sorted({row["name"].split(".", 1)[0] for row in rows})
    for family in families:
        selected = [row for row in rows if row["name"].split(".", 1)[0] == family]
        source = mcp_to_cl(selected)
        if cl_to_mcp(source) != selected:
            raise ValueError("MCP family roundtrip changed: " + family)
        audit(family, source, "family", {"roundtrip_equal": True, "tools": len(selected)})
    for path in sorted((REPO / "manuals/cl").glob("*.cl")):
        source = path.read_text(encoding="utf-8")
        compiled = cl_to_manual(source)
        artifact = REPO / "manuals" / (compiled["id"] + ".manual.json")
        if compiled != json.loads(artifact.read_text(encoding="utf-8-sig")):
            raise ValueError("Manual compiled artifact differs: " + path.name)
        audit(path.stem, source, "manual", {"compiled_equal": True})
    for path in sorted((REPO / "docs/standard/examples").glob("*.cl")):
        audit(path.stem, path.read_text(encoding="utf-8"), "example")
    summary = {"documents": len(results), "native_tools": len(rows), "families": len(families),
               "syntax_pass": sum(row["syntax_ok"] for row in results), "semantic_pass": sum(row["semantic_ok"] for row in results),
               "manuals": sum(row["kind"] == "manual" for row in results), "examples": sum(row["kind"] == "example" for row in results)}
    receipt = {"schema": "neyvia.cl.conformance.v1", "summary": summary, "results": results,
               "scope": "Production parser, compiler and static R1/R2/R3/R4/R5/R13 audit; no tool effects executed; semantic gaps remain failures."}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary))
    if args.strict and summary["semantic_pass"] != summary["documents"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
