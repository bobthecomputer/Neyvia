"""Add the executable Evolver chapter without replacing legacy Lab procedures."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / "manuals/hill-climb.manual.json"
manual = json.loads(path.read_text(encoding="utf-8"))
schemas = {
    "neyvia.evolver.state": {"type": "object", "properties": {"domain": {"type": "string"}}, "required": [], "additionalProperties": False},
    "neyvia.evolver.lineage": {"type": "object", "properties": {"domain": {"type": "string"}}, "required": ["domain"], "additionalProperties": False},
    "neyvia.evolver.receipt": {"type": "object", "properties": {"domain": {"type": "string"}, "trial": {"type": "integer", "minimum": 1}}, "required": ["domain", "trial"], "additionalProperties": False},
    "neyvia.evolver.run": {"type": "object", "properties": {"domain": {"type": "string", "enum": ["manual_compression", "cl_skill", "manual_compression_v2", "cl_skill_v2", "cl_skill_v3"]}, "requestId": {"type": "string", "minLength": 1}, "maxTrials": {"type": "integer", "minimum": 1, "maximum": 2}}, "required": ["domain", "requestId"]},
    "neyvia.evolver.job": {"type": "object", "properties": {"requestId": {"type": "string", "minLength": 1}}, "required": ["requestId"]},
    "neyvia.evolver.genome": {"type": "object", "properties": {"domain": {"type": "string"}, "genome": {"type": "string", "pattern": "^[a-f0-9]{64}$"}}, "required": ["domain", "genome"]},
}
manual["chapters"]["evolver"] = {
    "title": "Paired evolution with locked judges and fresh confirmation",
    "state": {"current": {"tool": "neyvia.evolver.state", "args": {}, "inputs": schemas["neyvia.evolver.state"],
                          "shape": {"type": "object", "properties": {"ok": {"const": True}, "domains": {"type": "array"}, "publicPromotion": {"const": False}}, "required": ["ok", "domains", "publicPromotion"]}}},
    "actions": {name.removeprefix("neyvia."): {"tool": name, "schema": name,
        "returns": {"type": "object"}, "pre": "Read selected workspace state; do not pass judge, panel or promotion edits",
        "effect": "Start a bounded real Luna job; local incumbent may change" if name == "neyvia.evolver.run" else "Read actual receipts; no public release changes", "reversible": name != "neyvia.evolver.run"} for name in schemas},
    "checks": {"observed": {"tool": "neyvia.evolver.state", "args": {}, "expect": {"path": "publicPromotion", "op": "eq", "value": False}}},
    "procedures": {"inspect": {"goal": "Inspect frozen evolution without publication", "inputs": {"type": "object", "properties": {}, "required": []}, "steps": [{"action": "evolver.state", "args": {}, "save": "state", "check": "observed"}]}},
    "judge": {"promotion": {"question": "Did discovery and fresh reconfirmation both satisfy the same frozen promotion contract?", "options": ["inspect-receipt", "retain-incumbent"], "constraints": "A Pareto member alone is insufficient. Read paired intervals, corrected alpha, hard gates and distinct panel IDs. Promotion changes only this workspace incumbent."}},
    "pitfalls": [{"failure": "Model sampling is called reproducibly seeded", "recovery": "CLI has no sampling-seed control. Seeds control task inputs and pair order; provider sampling remains uncontrolled."}, {"failure": "Token count called native Luna token count", "recovery": "Denominator uses o200k_base reference tokenization; actual CLI input/output usage is recorded separately."}, {"failure": "CL source checks called visual quality", "recovery": "This first domain measures frozen adherence plus compilation/markup correctness. Browser appearance is outside that measurement."}],
    "frontier": ["Claude owns the Hill climbing screen and rendered lineage journey", "Field L5, other domains and unrestricted rewrite languages require separate adapters and evidence"],
    "guidance": ["Domain source: src/grant_agent/evolver_domains.py; engine: src/grant_agent/evolver_core.py; real runner: scripts/run_t13_evolution.py"]
}
manual["schemas"].update(schemas)
for schema in schemas.values():
    schema.pop("additionalProperties", None)  # Registry advertises the same schema.
manual["chapters"]["overview"]["frontier"] = ["Legacy Lab measurements remain separate from frozen domain-specific Evolver evaluations", "Legacy competitions do not train or promote models"]
path.write_text(json.dumps(manual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(path)
