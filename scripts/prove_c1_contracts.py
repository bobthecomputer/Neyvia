"""Validate C1's real registered contracts and authored manual without dispatch."""
import ast
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from grant_agent.native_tools import NativeToolRegistry
from grant_agent.neyvia_manuals import get_manual, validate
from grant_agent.cua_adaptation import Adaptation

scratch = ROOT / ".agent_control/c1/contracts"
registry = NativeToolRegistry(scratch, nas_root=scratch / "local-only")
record, sha, manual = get_manual("computer-use")
grounded = validate(manual, registry)
descriptions = {name: registry.describe(name) for name in ("neyvia.cua.adapt", "neyvia.cua.flow")}
accepted = [
    [{"element": {"selector": {"role": "Edit"}, "value_equals": "verified"}}],
    [{"element": {"selector": {"label": "Applied"}, "exists": True}}],
    [{"visual": {"text_contains": "Applied"}}],
]
rejected = [[], [None], [{"element": {"selector": {"role": "Edit"}, "value_equals": None}}],
    [{"element": {"selector": {"role": "Edit"}, "exists": "yes"}}],
    [{"element": {"selector": {"unsupported": "x"}, "exists": True}}],
    [{"visual": {"text_contains": ""}}],
    [{"visual": {"text_contains": "Applied"}}, accepted[0][0]],
    [{"element": {"selector": {"role": "Edit"}, "value_equals": "x", "exists": True}}],
]
for value in accepted:
    Adaptation.validate_expectations(value)
for value in rejected:
    try:
        Adaptation.validate_expectations(value)
    except ValueError:
        continue
    raise RuntimeError("Invalid postcondition was admitted: " + repr(value))
paths = [ROOT / "src/grant_agent" / (name + ".py") for name in
    ("cua_adaptation", "cua_native", "manual_versions", "neyvia_cua", "neyvia_cua_mcp", "neyvia_manuals", "neyvia_workspace_tools")]
paths += list(ROOT.glob("scripts/*c1*.py"))
for path in paths:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
receipt = {"schema": "neyvia.c1-contracts.v1", "ok": True, "manualSha256": sha,
    "grounded": grounded, "registeredTools": descriptions, "acceptedPostconditions": len(accepted),
    "rejectedPostconditions": len(rejected), "parsedFiles": [str(p.relative_to(ROOT)) for p in paths],
    "boundary": "Real registry/schema/manual validation only; no native window action or model call"}
(ROOT / "scripts/evidence/C1-contracts.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"ok": True, "accepted": len(accepted), "rejected": len(rejected), "parsed": len(paths)}))
