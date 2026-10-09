"""Author the goal cascade and drag contract in the existing browser manual."""
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
from grant_agent.neyvia_browser import DEFINITIONS

source = REPO / "manuals/cl/browser.cl"
document = cl_to_manual(source.read_text(encoding="utf-8"))
for name, description, properties, required in DEFINITIONS:
    if name in {"browser.task.run", "browser.task.pause", "browser.task.resume", "browser.action", "browser.action.batch"}:
        document["schemas"]["neyvia." + name] = {"type": "object", "properties": properties, "required": required}
# Keep the authored batch procedure's input contract aligned with its actual
# action schema, including drag destinations and transient disambiguation.
for chapter in document["chapters"].values():
    for procedure in chapter["procedures"].values():
        for step in procedure["steps"]:
            action = chapter["actions"].get(step.get("action"), {})
            if action.get("tool") == "neyvia.browser.action.batch" and step.get("args", {}).get("steps") == {"$input": "steps"}:
                procedure["inputs"]["properties"]["steps"] = document["schemas"][action["schema"]]["properties"]["steps"]
name = "browser.task.run"
properties = next(p for n, _, p, _ in DEFINITIONS if n == name)
document["chapters"]["goal-cascade"] = {
    "title": "Compiled, LAYA and Luna goal cascade",
    "state": {"page": {"tool": "neyvia.browser.observe", "args": {"tabId": {"$input": "tabId"}},
        "inputs": {"type": "object", "properties": {"tabId": {"type": "string"}}, "required": ["tabId"]},
        "shape": {"type": "object", "required": ["revision", "elements", "text"]}}},
    "actions": {name: {"tool": "neyvia." + name, "schema": "neyvia." + name,
        "pre": "Actual live owner-granted tab; independent goal clauses; bounded action and model budgets",
        "effect": "Replay a verified compiled procedure, check the explicit goal, then calibrated LAYA candidates and explicitly enabled gpt-6-luna planning; every mutation uses existing fresh-revision receipts",
        "reversible": False, "returns": {"type": "object", "properties": {"status": {"type": "string"}, "verification": {"type": "object"}, "modelCalls": {"type": "integer"}}}}},
    "checks": {"result-text": {"tool": "neyvia.browser.observe", "args": {"tabId": {"$input": "tabId"}},
        "expect": {"path": "text", "op": "contains", "value": {"$input": "expectedText"}}}},
    "procedures": {"complete-checked-goal": {"goal": "Complete a browser goal with explicit independent result evidence",
        "inputs": {"type": "object", "properties": {**properties, "expectedText": {"type": "string"}}, "required": ["tabId", "goal", "requirements", "expectedText", "allowModel"]},
        "steps": [{"action": name, "args": {key: {"$input": key} for key in ("tabId", "goal", "requirements", "allowModel")}, "save": "cascade", "check": "result-text"}]}},
    "judge": {"all-clauses": {"question": "Does every user requirement have current, complete, cited evidence and a returned answer?",
        "options": ["done", "continue", "needs-owner"], "constraints": "A fresh quote predicate confirms a source binding, not semantic correctness by itself. Latest, ranking and negative results require actual ordering/date/filter coverage. allowModel=true explicitly enables bounded Luna calls."}},
    "pitfalls": [{"failure": "Goal fails or LAYA confidence/scope is insufficient", "recovery": "Continue through the explicitly enabled typed Luna route; do not count acquired evidence as success"},
        {"failure": "Native stale revision rejected before dispatch", "recovery": "Refresh and replan only with dispatched=false; an uncertain dispatched effect is never automatically replayed"},
        {"failure": "Dispatched effect is unconfirmed", "recovery": "Observe read-only, extract fresh facts and replan; never replay the uncertain action. Stop only if observation also fails."},
        {"failure": "Observed CAPTCHA, bot check or login", "recovery": "Pause as needs-owner, preserve the tab in Neyvia's right pane and ask Paul to resolve it; no engine switch or automatic solving."}],
    "frontier": ["No implicit visible engine launch. Native retry requires the agent-desktop host. LAYA calibration covers explicit named-control subdecisions, not arbitrary task planning."],
    "guidance": ["No saved answer or reference enters the executor; compiled scripts are quarantined after failure.",
        "Drag source and destination bind the same fresh observation; actual DOM drag events and independent expect verify the result.",
        "A transient target id may disambiguate identical current controls only with a fresh revision and matching semantics. Stored compiled procedures exclude these transient ids.",
        "Browser procedure: observe the page, extract required facts, stop immediately if every goal clause is satisfied, otherwise act once, verify the effect from a fresh observation, then verify the complete returned answer. Typed Luna completion requires a separate all-criteria judge; partial or unsupported negative answers must replan. Repeated failures or unchanged pages nudge a new observed route, never an uncertain effect replay.",
        "For a complete topic/date filtered set with nothing in the requested window, return an explicit not-in-the-window answer with coverage evidence. Ordinary enabled consent controls are actions, not owner walls."]}
chapter = document["chapters"]["goal-cascade"]
for verb in ("pause", "resume"):
    schema = "neyvia.browser.task." + verb
    chapter["actions"]["browser.task." + verb] = {"tool": schema, "schema": schema,
        "pre": "Freshly observed wall on a task-owned tab" if verb == "pause" else "Paul requests resume with persisted taskId",
        "effect": "Retain the blocked page and ask Paul" if verb == "pause" else "Re-observe, resume only after the wall clears, and retain needs-owner accounting",
        "reversible": False, "returns": {"type": "object", "properties": {"status": {"type": "string"}, "taskId": {"type": "string"}, "ownerHandoff": {"type": "boolean"}}}}
source.write_text(manual_to_cl(document), encoding="utf-8")
for path in (REPO / "manuals/browser.manual.json", REPO / "config/browser.manual.contract.json"):
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"manual": "browser", "chapter": "goal-cascade", "tool": "neyvia.browser.task.run"}))
