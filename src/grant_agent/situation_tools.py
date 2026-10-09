from .situation_interface import SituationStore


def situation_tool_definitions():
    scope={"workId":{"type":"string"}}
    return [
      ("situation.define","Record an explicit task contract for the situation interface. Agent-authored contracts are proposals, never authority grants.","artifact_write",
       {**scope,"task":{"type":"string"},"constraints":{"type":"array"},"acceptance":{"type":"array"},"expectedRevision":{"type":"integer"}},["workId","task"]),
      ("situation.recall","Read a bounded saved situation without claiming the browser is currently attached. Use neyvia.situation for fresh browser interaction.","read",
       {**scope,"focus":{"type":"string"},"presentation":{"type":"string","enum":["structured","text","spatial"]},"maxCharacters":{"type":"integer","minimum":800,"maximum":24000}},["workId"]),
    ]


def call_situation(root,name,args):
    store=SituationStore(root,args["workId"])
    if name=="situation.define":
        return store.define(args["task"],args.get("constraints"),args.get("acceptance"),expected_revision=args.get("expectedRevision",0))
    if name=="situation.recall":
        return store.view(focus=args.get("focus",""),presentation=args.get("presentation","structured"),max_characters=args.get("maxCharacters",6000))
    raise ValueError("Unknown situation native tool")
