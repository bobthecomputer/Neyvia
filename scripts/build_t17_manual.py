"""Generate the grounded autopilot manual from the live tool schemas."""
import json
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.neyvia_autopilot import DEFINITIONS

schemas = {"neyvia." + name: {"type": "object", "properties": props, "required": required}
           for name, _, props, required in DEFINITIONS}
chapter = {"title": "Autopilot: intent to verified checklist", "state": {
    "run": {"tool": "neyvia.autopilot.get", "args": {"runId": {"$input": "runId"}},
            "inputs": {"type": "object", "properties": {"runId": {"type": "string"}}, "required": ["runId"], "additionalProperties": False},
            "shape": {"type": "object", "required": ["run"]}}},
    "actions": {"inspect": {"tool": "neyvia.autopilot.get", "schema": "neyvia.autopilot.get", "returns": {"type": "object"},
                            "pre": "Returned runId in this workspace", "effect": "Read authoritative durable receipts", "reversible": True}},
    "checks": {"completed": {"tool": "neyvia.autopilot.get", "args": {"runId": {"$input": "runId"}},
                               "expect": {"path": "run.status", "op": "eq", "value": "completed"}}},
    "procedures": {"verify-run": {"goal": "Verify that all autopilot asks have executable completion receipts",
                                    "inputs": {"type": "object", "properties": {"runId": {"type": "string"}}, "required": ["runId"], "additionalProperties": False},
                                    "steps": [{"action": "inspect", "args": {"runId": {"$input": "runId"}}, "save": "run", "check": "completed"}]}},
    "judge": {}, "pitfalls": [{"failure": "Interrupted effect or verifier failure", "recovery": "Inspect receipt and reconcile; never restart the same write as a new request."}],
    "frontier": ["Automatic execution currently supports local observations and saved-source CAS text edits; external/irreversible actions require separate approval.",
                 "Quarantined mapping patches are proposed by exploration, never promoted by autopilot."],
    "guidance": ["Start with exact scopeTools; scope restricts caller authority and grants nothing.",
                 "Luna selects manual procedures and decides explicit JUDGE points; explicit gpt-6.1-sol handles disagreement/frontier.",
                 "Compiled scripts are reused only for current hashes and identical learned inputs; changed guards return to JUDGE.",
                 "Background runs belong to owner HTTP POST /api/ui/autopilot; tool starts run synchronously.",
                 "Same requestId retries return retained state. Stop is cooperative at the next action; poll get/list for proof."]}
manual = {"schema": "neyvia.manual.v1", "id": "autopilot", "kind": "workflow", "chapters": {"overview": chapter}, "schemas": schemas}
for operation, reversible, pre, effect in [
    ("start", False, "Explicit intent/requestId and exact scopeTools; caller already holds every nested grant",
     "Run synchronously through the Native gateway or start background owner HTTP; every ask gets checked receipts"),
    ("list", True, "Selected workspace", "Read durable run states"),
    ("stop", True, "Returned runId", "Stop at next action boundary; preserve newest progress and source bytes"),
    ("resume", False, "Original scope, worker quiesced, no unknown effects or unresolved authority",
     "Continue retained progress; completed children are never repeated")]:
    tool = "neyvia.autopilot." + operation
    chapter["actions"][operation] = {"tool": tool, "schema": tool, "returns": {"type": "object"},
                                    "pre": pre, "effect": effect, "reversible": reversible}
chapter["pitfalls"].append({"failure": "Nesting start inside manual.run", "recovery": "Call autopilot.start directly through the owning gateway; the controller owns manual execution locks."})
(REPO / "manuals/autopilot.manual.json").write_text(json.dumps(manual, indent=2) + "\n", encoding="utf-8")
index_path = REPO / "config/neyvia_manuals.json"
index = json.loads(index_path.read_text(encoding="utf-8"))
if not any(row["id"] == "autopilot" for row in index["manuals"]):
    index["manuals"].append({"id": "autopilot", "path": "manuals/autopilot.manual.json", "description": "Intent-driven scoped runs with executable per-ask receipts"})
index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
