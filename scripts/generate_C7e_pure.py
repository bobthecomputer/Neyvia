"""Compile the family-scoped pure edge campaign manual from its JSON contract."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
from grant_agent.manual_contracts import validate_structure
from grant_agent.neyvia_manuals import DEFINITIONS


def build_manual():
    schemas = {
        "neyvia." + name: {"type": "object", "properties": props, "required": required}
        for name, _, props, required in DEFINITIONS
        if name.startswith("verify.edges")
    }
    tool = "neyvia.verify.edges"
    status = "neyvia.verify.edges.status"
    port = schemas[tool]['properties']['port']
    family_check = lambda path: {
        "tool": status,
        "args": {"family": "pure"},
        "expect": {"path": path, "op": "eq", "value": True},
    }
    data = {
        "schema": "neyvia.manual.v1",
        "id": "C7e-pure",
        "kind": "workflow",
        "schemas": schemas,
        "chapters": {
            "pure": {
                "title": "Generated pure-family edge contracts",
                "state": {
                    "latest": {
                        "tool": status,
                        "args": {"family": "pure"},
                        "inputs": {"type": "object"},
                        "shape": {"type": "object"},
                    }
                },
                "actions": {
                    "run": {
                        "tool": tool,
                        "schema": tool,
                        "returns": {"type": "object"},
                        "pre": "Explicit assigned local C7 port; generated pure-family fixtures only",
                        "effect": "Generate and execute the existing pure fixture builder cases and persist a source-bound receipt",
                        "reversible": True,
                    },
                    "status": {
                        "tool": status,
                        "schema": status,
                        "returns": {"type": "object"},
                        "pre": "A family campaign receipt exists",
                        "effect": "Read actual pure-family case counts, outcomes, source freshness and receipt integrity",
                        "reversible": True,
                    },
                },
                "checks": {
                    "family-passed": family_check("allApplicableCasesPassed"),
                    "fresh": family_check("sourceCurrent"),
                    "intact": family_check("receiptIntact"),
                },
                "procedures": {
                    "run-family": {
                        "goal": "Execute the existing pure-family builder; its actual nonempty family rows all pass against current source and an intact receipt",
                        "inputs": {
                            "type": "object",
                            "properties": {"port": port},
                            "required": ["port"],
                        },
                        "steps": [
                            {
                                "action": "run",
                                "args": {
                                    "port": {"$input": "port"},
                                    "semanticFixtures": True,
                                    "schemaOnly": False,
                                    "families": ["pure"],
                                },
                                "save": "campaign",
                                "check": "family-passed",
                            },
                            {
                                "action": "status",
                                "args": {"family": "pure"},
                                "save": "family-status",
                                "check": "fresh",
                            },
                            {
                                "action": "status",
                                "args": {"family": "pure"},
                                "save": "receipt-status",
                                "check": "intact",
                            },
                        ],
                    }
                },
                "judge": {},
                "pitfalls": [
                    {
                        "failure": "Any actual pure-family case is missing, blocked or failed",
                        "recovery": "Preserve the receipt and inspect its familyCounts and failed rows; do not infer coverage from campaign completion",
                    },
                    {
                        "failure": "The source changes or the receipt is damaged",
                        "recovery": "Retain the receipt as historical evidence and rerun the family campaign against current source",
                    },
                ],
                "frontier": [
                    "This procedure covers only generated pure-family builder rows; other edge families and rendered application behavior remain separate",
                ],
                "guidance": [
                    "Use familyCases and familyCounts from the source-bound receipt for exact generated case and outcome totals",
                    "No credentials, external providers, NAS, live services, downloads or release promotion",
                ],
            }
        },
    }
    validate_structure(data)
    return data


def main():
    data = build_manual()
    source = manual_to_cl(data)
    if cl_to_manual(source) != data:
        raise ValueError("C7e pure manual CL roundtrip differs")
    (REPO / "manuals/cl/C7e-pure.cl").write_text(source, encoding="utf-8", newline="\n")
    (REPO / "manuals/C7e-pure.manual.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({"id": data["id"], "clRoundtrip": True, "procedure": "run-family"}))


if __name__ == "__main__":
    main()
