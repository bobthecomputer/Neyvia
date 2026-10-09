"""Author the edge-campaign manual through the existing CL compiler."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.cl.manuals import manual_to_cl, cl_to_manual
from grant_agent.manual_contracts import validate_structure
from grant_agent.neyvia_manuals import DEFINITIONS


def main():
    rows = {"neyvia." + name: {"type": "object", "properties": props, "required": required}
            for name, _, props, required in DEFINITIONS if name.startswith("verify.edges")}
    tool, status = "neyvia.verify.edges", "neyvia.verify.edges.status"
    data = {"schema": "neyvia.manual.v1", "id": "edge-contracts", "kind": "workflow", "schemas": rows,
      "chapters": {"campaign": {"title": "Generate and run edge cases",
        "state": {"latest": {"tool": status, "args": {}, "inputs": {"type": "object"}, "shape": {"type": "object"}}},
        "actions": {
          "run": {"tool": tool, "schema": tool, "returns": {"type": "object"}, "pre": "Explicit assigned C7b port; reviewed disposable local fixtures only", "effect": "Generate native inputs and feature-family fixtures, reconcile every original semantic pair and persist a source-bound receipt", "reversible": True},
          "status": {"tool": status, "schema": status, "returns": {"type": "object"}, "pre": "No campaign needed for an unavailable result", "effect": "Read receipt summary and verify source freshness", "reversible": True}},
        "checks": {
          "passed": {"tool": status, "args": {}, "expect": {"path": "ok", "op": "eq", "value": True}},
          "fresh": {"tool": status, "args": {}, "expect": {"path": "sourceCurrent", "op": "eq", "value": True}}},
        "procedures": {name: {"goal": goal, "inputs": {"type": "object", "properties": {"port": rows[tool]['properties']['port']}, "required": ["port"]},
          "steps": [{"action": "run", "args": {"port": {"$input": "port"}, "schemaOnly": schema_only, "semanticFixtures": not schema_only}, "save": "campaign", "check": "passed"},
                    {"action": "status", "args": {}, "save": "fresh", "check": "fresh"}]}
          for name, schema_only, goal in (("verify-admission", True, "Every generated native input case agrees with its live schema after supported transport normalization"),
                                         ("verify-local-edges", False, "Generate and execute reviewed feature-family fixtures; report every unbound original semantic pair and its exact remaining requirement"))},
        "judge": {}, "pitfalls": [{"failure": "A contract has no semantic fixture", "recovery": "Keep its eight generated scenarios blocked; add a reviewed adapter and independent observer before claiming coverage"},
          {"failure": "Interrupted effect or stale source", "recovery": "Inspect durable receipts and rerun a new isolated campaign; never replay an uncertain effect automatically"}],
        "frontier": ["Passing schema admission does not prove arbitrary tool execution, native apps, providers or rendered UI", "Complete semantic coverage requires every contract/category pair to have a real effect journey"],
        "guidance": ["Use the source-bound JSON receipt for exact payload digests, failures, coverage and baseline comparison", "No credentials, external providers, NAS, live services, downloads or release promotion"]}}}
    validate_structure(data)
    source = manual_to_cl(data)
    if cl_to_manual(source) != data:
        raise ValueError("Edge manual CL roundtrip differs")
    (REPO / "manuals/cl/edge-contracts.cl").write_text(source, encoding="utf-8", newline="\n")
    (REPO / "manuals/edge-contracts.manual.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    path = REPO / "config/neyvia_manuals.json"
    index = json.loads(path.read_text(encoding="utf-8"))
    if not any(row["id"] == data["id"] for row in index["manuals"]):
        index["manuals"].append({"id": data["id"], "path": "manuals/edge-contracts.manual.json", "clSource": "manuals/cl/edge-contracts.cl", "description": "Generated adversarial contract cases, isolated real journeys and explicit uncovered edges"})
        path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\r\n")
    print(json.dumps({"id": data["id"], "clRoundtrip": True}))


if __name__ == "__main__":
    main()
