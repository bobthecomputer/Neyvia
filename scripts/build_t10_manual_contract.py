"""Produce a grounded manual source for Claude's owned manuals/docs handoff."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from grant_agent.manual_contracts import validate_grounding
from grant_agent.native_tools import NativeToolRegistry
from grant_agent.neyvia_nightshift import DEFINITIONS


def main():
    registry = NativeToolRegistry(REPO / ".agent_control" / "T10-manual-contract")
    schemas, actions = {}, {}
    for name, description, _, _ in DEFINITIONS:
        tool = "neyvia." + name
        schemas[tool] = registry.describe(tool)["inputSchema"]
        actions[name] = {"tool": tool, "schema": tool, "returns": {"type": "object"},
                         "pre": "Owner-approved scope; explicit prompts, prerequisites and saved resource policy",
                         "effect": description, "reversible": name not in {"nightshift.start", "nightshift.tick", "nightshift.begin"}}
    empty = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    chapter = {"title": "Night Shift task tree, budgets and morning evidence",
               "state": {"board": {"tool": "neyvia.nightshift.tasks", "args": {}, "inputs": empty, "shape": {"type": "object"}},
                         "morning": {"tool": "neyvia.nightshift.summary", "args": {}, "inputs": empty, "shape": {"type": "object"}}},
               "actions": actions,
               "checks": {"usage-known": {"tool": "neyvia.nightshift.summary", "args": {}, "expect": {"path": "usage.complete", "op": "eq", "value": True}}},
               "procedures": {"read-morning": {"goal": "Observe real evidence and measured usage before reviewing completion",
                   "inputs": empty, "steps": [{"action": "nightshift.summary", "args": {}, "save": "morning", "check": "usage-known"}, {"judge": "acceptance"}]}},
               "judge": {"acceptance": {"question": "Do the evidence links satisfy the requested acceptance criteria?", "options": ["accept", "inspect"],
                   "constraints": "A completed CLI run proves execution, not output quality. Inspect file hashes, commits and transcript; unknown usage blocks exact token-budget admission."}},
               "pitfalls": [{"failure": "Checked imported row treated as done", "recovery": "Import is dormant; tick with fresh typed file, commit or this task's completed run evidence"},
                            {"failure": "Interrupted task resent after restart", "recovery": "Inspect its saved run; explicit start creates a new accounted attempt"},
                            {"failure": "Resource hold mistaken for failure", "recovery": "Read summary task reason; approved policy changes or explicit new night release armed work"}],
               "frontier": ["CLI token caps are enforced at reported usage events and may overshoot between events", "GPU policy covers declared requiresGpu tasks; external workloads are not observed"],
               "guidance": ["HTTP /api/nightshift and nightshift_<action>_command share SQLite state; desktop commands forward to the persistent authenticated backend",
                            "Bot start, budget changes and beginning a new night require fingerprint-bound owner approval; owner UI uses authenticated commands",
                            "Quiet times are HH:MM local or UTC; equal endpoints mean all day; ASR GPU reservation is the default"]}
    manual = {"schema": "neyvia.manual.v1", "id": "nightshift", "kind": "workflow", "schemas": schemas, "chapters": {"overview": chapter}}
    validate_grounding(manual, registry)
    output = REPO / "config" / "nightshift.manual.contract.json"
    output.write_text(json.dumps(manual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"grounded": True, "tools": len(schemas), "source": str(output), "promotion": "Claude copies to manuals/nightshift.manual.json and registers after the file exists"}))


if __name__ == "__main__":
    main()
