"""Extend the existing authored browser manual; preserve other chapters."""
from pathlib import Path
import json
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
from grant_agent.neyvia_browser import DEFINITIONS

source = REPO / "manuals/cl/browser.cl"
document = cl_to_manual(source.read_text(encoding="utf-8"))
chapter = {"title": "First-success compiled browser procedures", "state": {}, "actions": {}, "checks": {},
           "procedures": {}, "judge": {}, "pitfalls": [], "frontier": [], "guidance": []}
for name, description, properties, required in DEFINITIONS:
    if name not in {"browser.script.learn", "browser.script.run", "browser.site.manual"}:
        continue
    document["schemas"]["neyvia." + name] = {"type": "object", "properties": properties, "required": required}
    chapter["actions"][name] = {"tool": "neyvia." + name, "schema": "neyvia." + name,
                               "pre": "Explicit owner tab grant, actual same-origin state, bounded unique semantic controls",
                               "effect": description, "reversible": False,
                               "returns": {"type": "object", "properties": {"ok": {"type": "boolean"}, "verification": {"type": "object"}}}}
chapter["state"]["page"] = {"tool": "neyvia.browser.observe", "args": {"tabId": {"$input": "tabId"}},
    "inputs": {"type": "object", "properties": {"tabId": {"type": "string"}}, "required": ["tabId"]},
    "shape": {"type": "object", "required": ["revision", "elements", "text"]}}
chapter["procedures"]["replay-first-success"] = {"goal": "Reuse a proved parameterized flow without a model; fresh goal early exit and no replay after failure",
    "inputs": {"type": "object", "properties": {"tabId": {"type": "string"}, "name": {"type": "string"}, "inputs": {"type": "object", "maxProperties": 24}, "expectedText": {"type": "string"}}, "required": ["tabId", "name", "inputs", "expectedText"]},
    "steps": [{"action": "browser.script.run", "args": {key: {"$input": key} for key in ("tabId", "name", "inputs")}, "save": "replayed", "check": "fresh-goal"}]}
chapter["checks"]["fresh-goal"] = {"tool": "neyvia.browser.observe", "args": {"tabId": {"$input": "tabId"}},
    "expect": {"path": "text", "op": "contains", "value": {"$input": "expectedText"}}}
chapter["judge"]["task-complete"] = {"question": "Do fresh result facts cover every requested constraint?", "options": ["complete", "continue", "blocked"],
    "constraints": "A script predicate proves its declared goal only. Latest/date/order/filter/negative-answer coverage requires full fresh evidence; no cached answer reuse."}
chapter["pitfalls"] = [{"failure": "Procedure effect or goal fails", "recovery": "Procedure is quarantined; inspect the returned observation and relearn before another execution"}]
chapter["frontier"] = ["Obscura site bootstrap errors can leave controls unhydrated. Login/CAPTCHA is needs-owner, never bypassed."]
chapter["guidance"] = ["learn executes and verifies the first success before admission; values bind through {$input:name}, no saved answers or query values",
    "run validates fresh exact targets and origin; returns zero model calls/tokens/cost and actual goal receipt; earlyExit=true dispatches no action",
    "A profile owns one Obscura worker. Different profiles/spaces allow independent tab work; no fixed waits."]
document["chapters"]["compiled-browser"] = chapter
source.write_text(manual_to_cl(document), encoding="utf-8")
encoded = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
for path in (REPO / "manuals/browser.manual.json", REPO / "config/browser.manual.contract.json"):
    path.write_text(encoded, encoding="utf-8")
print(json.dumps({"manual": "browser", "chapter": "compiled-browser", "tools": list(chapter["actions"])}))
