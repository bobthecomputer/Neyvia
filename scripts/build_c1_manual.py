"""Add the C1 chapter without changing other authored CL chapter bytes."""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from grant_agent.cl.manuals import manual_to_cl, cl_to_manual
from grant_agent.neyvia_cua import DEFINITIONS

source = ROOT / "manuals/cl/computer-use.cl"
authored = source.read_text(encoding="utf-8")
base = cl_to_manual(authored)
schemas = {"neyvia." + name: {"type": "object", "properties": props, "required": required}
           for name, _, props, required in DEFINITIONS if name in {"cua.adapt", "cua.flow"}}
inputs = {"type": "object", "properties": {"sessionId": {"type": "string"}, "window_id": {"type": "integer"}},
          "required": ["sessionId", "window_id"], "additionalProperties": False}
arguments = {key: {"$input": key} for key in inputs["properties"]}
chapter = {"title": "C1: first-use adaptation and verified background flows",
    "state": {"window": {"tool": "neyvia.cua.inspect", "inputs": inputs, "args": arguments, "shape": {"type": "object"}}},
    "actions": {name.split(".")[-1]: {"tool": name, "schema": name, "returns": {"type": "object"},
        "pre": "Owner-approved active CUA session and one allowed window", "effect": description, "reversible": name.endswith("adapt")}
        for name, description in [("neyvia.cua.adapt", "Read-only probing writes a quarantined CL draft; visual=true invokes T18 only for poor UIA"),
                                  ("neyvia.cua.flow", "Resolve fresh unique controls, act and check every step; promote verified use locally; compile after three grounded runs")]},
    "checks": {"observed": {"tool": "neyvia.cua.inspect", "args": arguments, "expect": {"path": "elements", "op": "exists"}}},
    "procedures": {"explore": {"goal": "Inspect an unseen allowed app without acting", "inputs": inputs,
        "steps": [{"action": "adapt", "args": arguments, "save": "draft", "check": "observed"}]}},
    "judge": {}, "pitfalls": [
        {"failure": "Selector is missing or ambiguous", "recovery": "Inspect again and choose a unique role/label/automationId/className selector"},
        {"failure": "Action outcome is unknown or Paul took over", "recovery": "Stop; inspect actual state before any deliberate retry"},
        {"failure": "Opaque coordinates lack a matching captured frame", "recovery": "Use adapt visual=true or capture; refresh changed pixels; opaque actions retain approval"}],
    "frontier": ["Latency targets, 15+ installed-app completion and matched competitor benchmarks require their own real receipts",
                 "Apps that reject background messages remain unsupported; no foreground input fallback",
                 "Visual extraction is model-dependent and may be slow or unavailable"],
    "guidance": ["Flow steps use selector/tool/args/expect. UIA checks: element.selector plus value_equals, label_equals, enabled_equals or exists.",
                 "Visual checks use visual.text_contains; uncertain OCR never verifies success. Exact captured pixels must remain unchanged across extraction.",
                 "The first successful use promotes the quarantined workspace draft. Later calls use manual.run; after three verified traces, manual.compile and manual.script.run take over.",
                 "Tools: neyvia.cua.adapt, neyvia.cua.flow; backend/desktop: cua_adapt_command, cua_flow_command; MCP: adapt_app, run_flow."]}
fragment = manual_to_cl({"schema": "neyvia.manual.v1", "id": "computer-use", "kind": "environment", "schemas": schemas,
                         "chapters": {"adaptation": chapter}})
# The authored document already owns t0...; give fragment types a disjoint name.
fragment = re.sub(r"\bt(\d+)\b", r"c1t\1", fragment)
prefix = "-- @manual "
base_line = next(line for line in authored.splitlines() if line.startswith(prefix))
fragment_line = next(line for line in fragment.splitlines() if line.startswith(prefix))
metadata = json.loads(base_line[len(prefix):])
addition = json.loads(fragment_line[len(prefix):])
for section in ("chapters", "schemas", "tool_metadata"):
    if section in addition:
        metadata.setdefault(section, {}).update(addition[section])
authored = authored.replace(base_line, prefix + json.dumps(metadata, ensure_ascii=False, separators=(",", ":")), 1)
fragment = "\n".join(line for line in fragment.splitlines() if not line.startswith(("CL ", "-- @manual "))) + "\n"
if "L computer-use.adaptation " in authored:
    raise SystemExit("C1 chapter already exists; edit its authored CL explicitly")
candidate = authored.rstrip() + "\n" + fragment
compiled = cl_to_manual(candidate)
assert all(compiled["chapters"][key] == value for key, value in base["chapters"].items())
assert all(compiled["schemas"][key] == value for key, value in base["schemas"].items())
source.write_text(candidate, encoding="utf-8", newline="\n")
(ROOT / "manuals/computer-use.manual.json").write_text(json.dumps(compiled, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"ok": True, "oldChaptersPreserved": len(base["chapters"]), "newChapter": "adaptation"}))
