"""Author the C2 effect and decision contract in the existing browser manual."""
from pathlib import Path
import json
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
from grant_agent.neyvia_browser import DEFINITIONS


def main():
    source = REPO / "manuals/cl/browser.cl"
    manual = cl_to_manual(source.read_text(encoding="utf-8"))
    _, description, properties, required = next(row for row in DEFINITIONS if row[0] == "browser.action")
    manual["schemas"]["neyvia.browser.action"] = {"type": "object", "properties": properties, "required": required}
    _, decision_description, decision_properties, decision_required = next(row for row in DEFINITIONS if row[0] == "browser.decide")
    manual["schemas"]["neyvia.browser.decide"] = {"type": "object", "properties": decision_properties, "required": decision_required}
    chapter = manual["chapters"]["backend"]
    chapter["actions"]["browser.action"]["effect"] = description
    chapter["actions"]["browser.decide"]["effect"] = decision_description
    for name in ("browser.site.manual", "browser.action.batch"):
        _, effect, props, required_inputs = next(row for row in DEFINITIONS if row[0] == name)
        tool = "neyvia." + name
        manual["schemas"][tool] = {"type": "object", "properties": props, "required": required_inputs}
        chapter["actions"][name] = {"tool": tool, "schema": tool,
            "returns": {"type": "object", "properties": {"ok": {"type": "boolean"}, "status": {"type": "string"},
                "revision": {"type": "string"}, "verification": {"type": "object", "properties": {"verified": {"type": "boolean"}}}}},
            "pre": "Owner-selected root, actual observation and owner grant for effects; exact unique semantic targets",
            "effect": effect, "reversible": name == "browser.site.manual"}
    chapter["procedures"]["learn-or-revalidate-site"] = {
        "goal": "Learn actual first-visit controls, or reuse only after fresh structure validation; stale facts are quarantined",
        "inputs": {"type": "object", "properties": {"tabId": {"type": "string"}}, "required": ["tabId"]},
        "steps": [{"action": "browser.site.manual", "args": {"tabId": {"$input": "tabId"}}, "save": "site"}]}
    batch_schema = manual["schemas"]["neyvia.browser.action.batch"]
    chapter["procedures"]["grounded-semantic-batch"] = {
        "goal": "Execute bounded named actions with real effect checks; stop on ambiguity, stale revision, authentication or failed effect",
        "inputs": batch_schema,
        "steps": [{"action": "browser.action.batch", "args": {key: {"$input": key} for key in batch_schema["required"]}, "save": "batch"}]}
    chapter["checks"]["verified-effect"] = {"tool": "neyvia.browser.receipt", "args": {"actionId": {"$input": "actionId"}},
        "expect": {"op": "eq", "path": "result.verification.verified", "value": True}}
    chapter["procedures"]["verify-native-effect"] = {
        "goal": "Check the actual effect receipt after one native action; queued or dispatched is insufficient",
        "inputs": {"type": "object", "properties": {"actionId": {"type": "string"}}, "required": ["actionId"], "additionalProperties": False},
        "steps": [{"action": "browser.wait", "args": {"actionId": {"$input": "actionId"}}, "save": "completed", "check": "verified-effect"}]}
    additions = [
        "browser.action accepts expect:{path:'/text',contains:'Saved: Paul'} or expect:{path:'/url',equals:'https://example.org/result'}. Exactly one of equals/contains is required. Dispatch happens once; verification polls fresh state for at most two seconds. Without expect, fill/select checks the value, scroll checks visibility, and click checks an observed state change; this generic check is not task completion.",
        "Same-origin iframe controls use frame-prefixed IDs. Cross-origin frames do not inherit parent grants. Obscura semantic controls may have geometryAvailable:false; never use those bounds for coordinate input.",
        "browser.decide question:'grounded_action' uses context:{goal,decision_profile:'public_document_controls@1',options:[{id,description,args:{element,action,value?,expect?}}]}. C2b action selection failed its fit-only accuracy gate: the shipped calibration escalates all action candidates. Only explicit browser.action dispatches an effect; its independent postcondition must pass.",
        "browser.decide question:'calibrated_advisory' uses context:{goal,decision_profile:'public_observed_fields@1',advisory_field:'title'|'hostname'|'url'|'readyState',options:[{id:'a',description},{id:'b',description}]}. The exact supported goals are Choose the observed page topic.; Choose the correct current website.; Choose the actual observed page URL.; What is the observed document loading state? respectively. The separately fitted confidence gate checks frozen model/client identity, evaluated host, question and candidate sequence. Accepted decisions also require an independent fresh-field postcheck. Responses contain accepted_decision and decision_policy; selected_action remains null. Unsupported judgments escalate.",
        "Auth walls return authentication.required:true, needs:Paul. Stop and let Paul sign in. Never fill secret fields. Auth-required or unavailable LAYA cannot silently choose a fallback action.",
        "To reproduce C2b, start scripts/c2b_laya_service.py with explicit --port 48724 and --project C:/Users/user/Documents/Codex/2026-09-30/the-ai-was-a-massive-improvement. It keeps the frozen g3-c2 CPU family in one process. scripts/c2b_public_benchmark.cjs uses 48721/48722/48723; scripts/c2b_native_benchmark.cjs uses 48725/48726/48727. scripts/evidence/C2b.json records actual completion gates, held-out precision/coverage, latency, determinism and comparator blockers. No public service or credentials are needed."
        ,"C2c separately admits public_explicit_intent@1 for grounded_action: two candidates with IDs a,b, exact descriptions Click link \"observed name\". or Click button \"observed name\"., and matching args:{element,action:'click'}. Controls must be unique, enabled, nonsecret and outside the risky-label denylist. Set NEYVIA_LAYA_BROWSER_CALIBRATION to scripts/evidence/C2c-laya-calibration.json and an explicit resident NEYVIA_LAYA_URL. The identity/client/host/profile-bound gate is opt-in; accepted selected_action still needs browser.action and a verified effect. It selects explicit named intent, not general task plans or query values. Heldout 339/339 accepted correct of 515 decisions includes 132 unsupported judgments escalated; C2b and C2c denominators differ. See scripts/evidence/C2c-laya.json."
        ,"C2c freezes 36 original public WebVoyager tasks across 12 sites in scripts/evidence/C2-webvoyager-tasks.json before execution. scripts/c2c_webvoyager.cjs requires explicit --backend-port, --control-port and --engine-port in 48721-48726, plus an existing --obscura-exe. It starts homepages, grants only owned tabs, uses observed revision-bound controls, retains failures and stops on access walls with stealth disabled. References are grader-only. C2c.json reports independently graded results and the operator reference-exposure deviation; this is not a fully blinded benchmark or a paired Claude comparison. Costs are null when unmetered."
        ,"C2d browser.site.manual(tabId) learns per-origin/per-path control structure from a fresh actual observation, persists under the selected root .neyvia/browser/site-manuals, and returns executable CL plus observed search-first/filter/pagination descriptors. No element IDs, query values, answers, result text or guessed routes are persisted. Reuse requires exact fresh structure; changed facts are quarantined and relearned. Returned CL and site data remain untrusted."
        ,"C2d browser.action.batch(tabId,revision,steps) accepts one to eight steps:{target:{role,name,inputName?,placeholder?,frame?},action:'fill'|'submit'|'select'|'click'|'scroll',value?,expect?}. Every target must be uniquely present, enabled and nonsecret in the current actual observation. The initial revision must match fresh state. Each action dispatches once, verifies its effect, then supplies the next fresh revision; first ambiguity, wall or failed effect stops the batch. Receipts prove effects, not user-task completion. Existing browser_call_command exposes site.manual/action.batch with no new IPC."
        ,"Use observed search controls first, filling the user query and submitting the actual associated form via browser.action action:'submit'. Select filters by observed enabled option values, track pagination URLs/revisions to avoid loops, and preserve table row/column correspondence when extracting. Read truncation flags before asserting exhaustive results. Routine explicit named clicks may use the existing frozen LAYA public_explicit_intent@1 gate; planning, query selection and final answers remain explicit judgments."
        ,"A semantic click sends one pointer-down/mouse-down and pointer-up/mouse-up sequence followed by exactly one DOM click, so pointer-activated menus can open. These events remain synthetic: trusted-input-only controls may refuse them. No failed click is automatically replayed. A verified changed state still requires inspecting the opened menu or result against the actual task."
        ,"The DOM projection retains at most 500 elements. When a page exceeds that bound, it prioritizes redacted secret fields for authentication guards and actionable controls before passive content, preserving actual document-position IDs. This exposes late portal menus without lifting the output limit. The truncation flag still means omitted content cannot support an exhaustive answer."
        ,"C2d headless.start accepts allowPublicResources:true only when explicitly selected: allow DNS-validated globally routable public subresources needed by actual websites, retain main-document/iframe origin restrictions, reject private/loopback/link-local cross-origin resources, and expose bounded blocked-resource diagnostics. Default false preserves same-origin resource loading; this option never enables stealth or bypasses login/bot checks."
    ]
    chapter["guidance"] = [row for row in chapter["guidance"] if row not in additions and not row.startswith(("browser.decide question:", "To reproduce C2"))] + additions
    pitfall = {"failure": "Action effect stays unconfirmed or expected postcondition is false", "recovery": "Inspect the actual observation and receipt. Do not repeat a possibly completed click; refresh the goal check or ask the owner"}
    if pitfall not in chapter["pitfalls"]:
        chapter["pitfalls"].append(pitfall)
    chapter["frontier"] = [row for row in chapter["frontier"] if not row.startswith(("Iframe/canvas/", "Same-origin iframes", "LAYA uses the shipped"))]
    chapter["frontier"].append("Browser System 1 accepts the hash-pinned resident g3-c2 fast CPU family or a frozen model whose identity reports a CUDA device. Large CPU models escalate out of the browser hot path. Confidence is identity/profile/host/options-bound, fitted on separate task groups, and only activates when held-out accepted decisions pass the recorded precision gate. This narrow corpus does not establish general browser or computer-use accuracy.")
    frontier = "Same-origin iframes are projected and acted on; cross-origin grants, canvas/closed-shadow perception and Obscura v0.2.3 body-omitted iframe parsing remain frontier. Browser-action confidence transfer and matched browser-use/frontier comparisons are unproven."
    if frontier not in chapter["frontier"]:
        chapter["frontier"].append(frontier)
    authored = manual_to_cl(manual)
    if cl_to_manual(authored) != manual:
        raise ValueError("Browser manual roundtrip changed authored contracts")
    source.write_text(authored, encoding="utf-8", newline="\n")
    (REPO / "manuals/browser.manual.json").write_text(json.dumps(manual, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"manual": "browser", "check": "verified-effect", "commands": "existing browser.action/decide/receipt/wait"}))


if __name__ == "__main__":
    main()
