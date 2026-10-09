"""Author Connected Language contracts for the measured research tools."""
import json
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.cl.manuals import manual_to_cl, cl_to_manual
from grant_agent.neyvia_manuals import records, document, validate, render
from grant_agent.native_tools import NativeToolRegistry

if "--gate" in sys.argv:
    # The benchmark driver records observations; the authored manual owns the
    # acceptance checks. Reading these receipts makes no provider/model call.
    source_path = REPO / "manuals/cl/research-assistant.cl"
    data = cl_to_manual(source_path.read_text(encoding="utf-8"))
    registry = NativeToolRegistry(REPO / ".agent_control/C10/tool-manual")
    tool = "neyvia.research.receipt"
    data["schemas"][tool] = registry.describe(tool)["inputSchema"]
    inputs = {"type":"object","properties":{"path":{"type":"string","minLength":1}},"required":["path"],"additionalProperties":False}
    chapter = {"title":"Research tool correctness and latency gates", "state":{},"actions":{},"checks":{},"procedures":{},"judge":{},
        "pitfalls":[{"failure":"Complete measurement is reported as passing tool quality",
                     "recovery":"Run the measured contract and every tool contract separately; preserve failed gates and compare paired baselines."}],
        "frontier":["These contracts inspect fixed real-case observations. They do not prove 49/50 answer accuracy, semantic entailment or public deployment."],
        "guidance":["Use the byte-identical C10-tools.json copy at tool-gate/receipt.json, confined to the task runtime. Preserve raw per-case observations and the frozen corpus hash.",
                    "Run scripts/c10_tools.py for actual native tool and paired baseline measurements. The contracts below are the acceptance criteria; no new test files."]}
    chapter["actions"]["observe-tool-gate"] = {"tool":tool,"schema":tool,"returns":{"type":"object"},"reversible":True,
        "pre":"A bounded receipt.json under the selected task root contains the actual fixed tool benchmark observations.",
        "effect":"Read the recorded public-source benchmark; do not run another research model or modify providers."}
    fixed_tools = ["web.fetch","web.read","web.passages","web.cite","web.dedupe","web.search","web.image_search","neyvia.research.receipt",
                   "neyvia.browser.decide","web.fetch.pdf","neyvia.pdf.open","neyvia.pdf.extract_text","neyvia.pdf.search","neyvia.pdf.state",
                   "neyvia.browser.open","neyvia.browser.observe","neyvia.browser.capture"]
    observed = {"type":"object","required":["cases","correct","correctness","failureRate","p50Ms","p95Ms","baseline","gates"],
        "properties":{"cases":{"type":"integer","minimum":20},"correct":{"type":"integer","minimum":0},
          "correctness":{"type":"number","minimum":0,"maximum":1},"failureRate":{"type":"number","minimum":0,"maximum":1},
          "p50Ms":{"type":"number","minimum":0},"p95Ms":{"type":"number","minimum":0},
          "baseline":{"type":"object","required":["correct","p50Ms","p95Ms"]}}}
    measured = {"type":"object","required":["allMeasured","measuredTools","casesSha256","selected"],
        "properties":{"allMeasured":{"const":True},"measuredTools":{"const":17},
          "casesSha256":{"const":"14a0187091c99076a30e9a61ca444a0b52ccbf6c0503a5127f607ade6e40d632"},
          "selected":{"type":"object","required":fixed_tools,"additionalProperties":observed}}}
    def contract(name, path, schema):
        chapter["checks"][name] = {"tool":tool,"args":{"path":{"$input":"path"}},"expect":{"op":"schema","path":path,"schema":schema}}
        chapter["procedures"][name] = {"goal":"Inspect the fixed real-case evidence against "+name,"inputs":inputs,
            "steps":[{"action":"observe-tool-gate","args":{"path":{"$input":"path"}},"save":"observed","check":name}]}
    contract("tool-gate-measured", "", measured)
    for name in fixed_tools:
        passing = {**observed,"properties":{**observed["properties"],"correctness":{"type":"number","minimum":0.95,"maximum":1},
                   "failureRate":{"type":"number","minimum":0,"maximum":0.05},
                   "gates":{"type":"object","required":["latency","twentyRealCases"],
                            "properties":{"latency":{"const":True},"twentyRealCases":{"const":True}}}}}
        contract("gate-"+name.replace(".","-"), ["selected",name], passing)
    data["chapters"]["tool-gate"] = chapter
    validate(data, registry)
    metadata = {name:{"mutability_class":row.mutability_class} for name,row in registry._specs.items()}
    source_path.write_text(manual_to_cl(data,metadata),encoding="utf-8")
    print(json.dumps({"manual":"research-assistant","toolContracts":17,"measurementContract":1,"authored":"CL; compile JSON with cl_compile_manuals.py"}))
    sys.exit(0)

record = next(row for row in records() if row["id"] == "tools-depth")
data = document(record)[1]
registry = NativeToolRegistry(REPO / ".agent_control/C10/tool-manual")
spec = registry.describe("web.dedupe")
data["schemas"]["web.dedupe"] = spec["inputSchema"]
data["chapters"]["tools"]["actions"]["web.dedupe"] = {
    "tool":"web.dedupe", "schema":"web.dedupe", "reversible":True,
    "pre":"Selected workspace; use returned immutable document handles",
    "effect":"Group identical observed text while keeping every URL and content hash; no semantic deduplication",
    "returns":{"type":"object", "required":["groups","inputCount","uniqueCount","method"],
               "properties":{"groups":{"type":"array"},"inputCount":{"type":"integer"},"uniqueCount":{"type":"integer"},
                             "method":{"const":"exact-observed-text-sha256"}}}}
metadata = {name:{"mutability_class":row.mutability_class} for name,row in registry._specs.items()}
source = manual_to_cl(data,metadata)
if cl_to_manual(source) != data: raise ValueError("Manual round trip changed semantics")
validate(data, registry)
(REPO / record["clSource"]).write_text(source,encoding="utf-8")
(REPO / record["path"]).write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")
view = "<!-- Generated from " + record["clSource"] + "; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->\n# tools-depth\n\n"
for name,chapter in data["chapters"].items():
    view += "## " + name + "\n" + render(chapter,data["schemas"],data.get("proofs"),layer="tools-depth",source_version="1.1") + "\n"
(REPO / "docs/manuals/tools-depth.md").write_text(view.rstrip()+"\n",encoding="utf-8")
print(json.dumps({"manual":"tools-depth","dedupeToolValidated":True,"roundTrip":True}))
