"""Outcome contracts for CL completion and stale native references."""
from __future__ import annotations

import json
from pathlib import Path

CONTRACTS = ("cl.completion-after-effect", "cl.stale-reference-preserves")


def require(condition, contract, detail):
    if not condition:
        raise ValueError(f"Contract {contract}: {detail}")


def check_completion(root):
    """Run CL against a real scratch note, then verify completion after a write."""
    from .neyvia_agent import NeyviaAgentConfig, _product_cl_completion
    from .neyvia_gateway import NeyviaToolGateway
    from .neyvia_intent_plan import publish_plan
    from .ui_command_bus import bus_for

    root = Path(root).resolve()
    notes = root / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    note = notes / "Ideas.md"
    note.write_text("Original", encoding="utf-8")
    bus_for(root).put("notes:folder", str(notes))
    session = "cl-completion-proof"
    task = "cl-completion-proof-run"
    expression = 'notes.read(path="Ideas.md").body == "Original"'
    publish_plan(root, {"sessionId": session, "plan": [{
        "step": "Confirm the saved note", "status": "pending", "doneWhen": expression,
    }]})
    gateway = NeyviaToolGateway(root, allow_mutations=True, action_scope=session,
        allowed_mutation_tools={"neyvia.notes.write"})
    gateway.task_goal_root = root
    gateway.cl_task_id = task
    config = NeyviaAgentConfig(root=root, session_id=session, allow_mutations=True,
        native_mutation_tools=("neyvia.notes.write",))

    observed = gateway.call_native("neyvia.cl", {"lines":
        'notes.read(path="Ideas.md")\nG: notes.read(path="Ideas.md").body == "Original"\ndone("verified")'})
    require(observed["ok"], CONTRACTS[0], "CL did not observe and explicitly complete the authored note goal")
    before = _product_cl_completion(config, gateway, task)
    require(before["status"] == "completed" and before["goalChecks"]
            and before["goalChecks"][0]["passed"] and before["goalChecks"][0]["observed"],
            CONTRACTS[0], "product completion did not report a fresh passing observer")

    written = gateway.call_native("neyvia.notes.write", {"path": "Ideas.md", "body": "Changed"},
                                  action_id="cl-completion-proof-write")
    require(written.get("ok") is True and note.read_text(encoding="utf-8") == "Changed",
            CONTRACTS[0], "native write did not persist the changed note bytes")
    after = _product_cl_completion(config, gateway, task)
    require(after["status"] == "incomplete" and after.get("doneStatus") == "unverified"
            and gateway._cl_protocol.host.done_status is None,
            CONTRACTS[0], "a real native mutation retained prior CL completion")
    return {"before": before, "write": written, "savedText": note.read_text(encoding="utf-8"), "after": after}


def check_stale_reference(root):
    """Exercise HostContext refs while dispatching against a real scratch file."""
    from .cl.host import HostContext

    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    note = root / "stale-reference.txt"
    note.write_text("Original", encoding="utf-8")
    token = "native-target-fixture"
    tools = [
        {"name": "win.observe", "inputSchema": {"type": "object", "properties": {}},
         "annotations": {"readOnlyHint": True}},
        {"name": "win.value", "inputSchema": {"type": "object", "properties": {
            "target": {"type": "string"}}, "required": ["target"]}, "annotations": {"readOnlyHint": True}},
        {"name": "win.fill", "effect": "!", "inputSchema": {"type": "object", "properties": {
            "target": {"type": "string"}, "value": {"type": "string"}}, "required": ["target", "value"]}},
    ]

    def dispatch(name, args, action_id=""):
        if name == "win.observe":
            return {"elements": [{"element_token": token, "role": "textbox", "label": "Note",
                                   "value": note.read_text(encoding="utf-8")}]}
        require(args.get("target") == token, CONTRACTS[1], "host changed the selected native target")
        if name == "win.fill":
            note.write_text(args["value"], encoding="utf-8")
            return {"ok": True}
        return {"value": note.read_text(encoding="utf-8")}

    contracts = {
        "win.value": {"refs": ["target"]},
        "win.fill": {"refs": ["target"], "snapshot": lambda args: dispatch("win.observe", {}),
            "checks_factory": lambda args: [{"name": "value", "observer": "win.value",
                "check": lambda args, value, before: host._observer("win.value", [],
                    {"target": args["target"]})["value"] == args["value"]}]},
    }
    window_tools=[
        {'name':'win.windows','inputSchema':{'type':'object','properties':{}},'annotations':{'readOnlyHint':True}},
        {'name':'win.text','inputSchema':{'type':'object','properties':{'window_id':{'type':'integer'}},
            'required':['window_id']},'annotations':{'readOnlyHint':True}}]
    def window_dispatch(name,args,action_id=''):
        if name=='win.windows':
            return {'windows':[{'window_id':note.stat().st_ino,'title':str(note),'process':'owned-file-observer'}]}
        require(args['window_id']==note.stat().st_ino,CONTRACTS[1],'Restored observer changed its file identity')
        return {'text':note.read_text(encoding='utf-8')}
    window_contracts={'win.text':{'window_selection':True}}
    host = HostContext(window_tools,window_dispatch,contracts=window_contracts)
    first = host.execute('win.windows()\nG: win.text(w1).text == "Original"\ndone("observed")')
    require(first["ok"], CONTRACTS[1], "initial native observation did not bind a live reference")
    bindings = json.loads(json.dumps(host.completion_bindings()))
    restored = HostContext(window_tools,window_dispatch,contracts=window_contracts)
    restored.restore_completion_bindings(bindings)
    require(restored.evaluate(host.goals[0])["passed"], CONTRACTS[1], "restored completion binding lost its current observation")
    note.write_text("External writer", encoding="utf-8")
    current = restored.evaluate(host.goals[0])
    require(not current["passed"] and current["observations"][0]["value"]["text"] == "External writer",
            CONTRACTS[1], "completion reused a cached pre-change value instead of rereading the file")

    host = HostContext(tools, dispatch, contracts=contracts)
    require(host.execute('win.observe()\nG: win.value(target=e1).value == "External writer"')["ok"],
            CONTRACTS[1], "could not bind the current native reference")
    require(host.execute("win.observe()")["ok"] and "e1" not in host.live_refs() and "e2" in host.live_refs(),
            CONTRACTS[1], "fresh observation did not supersede the old reference")
    edited = host.execute('win.fill(target=e2, value="First edit")')
    require(edited["ok"] and note.read_text(encoding="utf-8") == "First edit",
            CONTRACTS[1], "current reference failed to apply its real file effect")
    stale = host.execute('win.fill(target=e1, value="Stale edit")')
    require(not stale["ok"] and stale["status"] == "stale" and note.read_text(encoding="utf-8") == "First edit",
            CONTRACTS[1], "stale reference mutated the file or was not refused")
    require(token not in stale["text"], CONTRACTS[1], "stale-ref feedback exposed the native target token")
    return {"restoredObservation": current, "freshWrite": edited, "staleResult": stale,
            "finalText": note.read_text(encoding="utf-8")}


def self_check(scratch):
    import time
    from .contract_gate import wants
    root = Path(scratch).resolve() / "cl-completion"
    root.mkdir(parents=True, exist_ok=True)
    cases=[];started=time.perf_counter()
    for identity,action in zip(CONTRACTS,(check_completion,check_stale_reference)):
        if not wants(identity):continue
        try:
            observed=action(root/identity)
            cases.append({'id':identity,'contracts':[identity],'ok':True,'observed':observed})
        except Exception as error:
            cases.append({'id':identity,'contracts':[identity],'ok':False,'error':str(error)})
    return {'area':'cl-completion','ok':bool(cases) and all(c['ok'] for c in cases),'cases':cases,
            'durationMs':round((time.perf_counter()-started)*1000)}
