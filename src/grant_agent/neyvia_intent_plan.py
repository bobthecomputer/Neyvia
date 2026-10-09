"""Model-authored intent plans; validation and publication make no provider call."""
from __future__ import annotations

import json
import re

INTENT_INSTRUCTIONS = """For a message with two or more asks (numbered items, several questions, "and also"), even quick ones, publish its intent checklist with every ask pending before you answer or change anything. Read the whole message; later corrections replace earlier asks, and retain dropped asks with their reason. For a long or dictated message, neyvia.intent.checklist (intent_checklist in MCP) gives the extraction prompt/schema; fill it yourself without another model call, and use doneWhen as observable acceptance. Publish the resulting asks with update_plan (Native: plan_json is a JSON array of {step,status}; MCP: plan_update with plan). Keep it updated after real progress: pending, in_progress, completed; at most one in_progress. Completion requires evidence; blocked work remains pending with an explanation. Preserve unfinished asks when the user steers the task. Mark an ask completed only after its answer or change exists, one update per finished ask, so the person watches it tick. For one simple ask, no checklist ceremony is needed."""

PLAN_FIELDS = {
    "plan": {"type": "array", "maxItems": 100, "items": {"type": "object", "properties": {
        "step": {"type": "string", "minLength": 1, "maxLength": 300},
        "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
        "doneWhen": {"type": "string", "minLength": 1, "maxLength": 12000,
                     "description": "CL 1.1 observer-based G expression; evaluated by the host before done()."}}, "required": ["step", "status"]}},
    "explanation": {"type": "string", "maxLength": 300},
    "sessionId": {"type": "string", "maxLength": 200},
}


_ASK_MARKERS = re.compile(r"\b(?:also|and then|another thing|one more thing|second(?:ly)?|third(?:ly)?|plus|after that|"
                          r"forget what i said|scratch that|no actually|instead)\b|\?|^\s*(?:\d+[.)]|[-*•])\s", re.I | re.M)


def needs_checklist(text: str) -> bool:
    """Cheap local gate (no model): long or several-ask messages get the checklist note on their turn."""
    text = text if isinstance(text, str) else ""
    return len(text.split()) >= 60 or len(_ASK_MARKERS.findall(text)) >= 2


def turn_note(tool: str) -> str:
    """What a Claude Code / Codex turn started from Neyvia is told when the message holds several asks."""
    from .neyvia_awareness import INTENT_RULES
    from .paul_manual import brief
    return ("Neyvia note: the person's message may hold several asks, and it is often dictated. Before you act, read all of it, "
            f"then publish a checklist, one item per ask in their order, all pending. Tools: {tool}.\nRead the message this way:\n"
            + INTENT_RULES + "\n" + brief(level=1)
            + "\nA long dictated message often holds 15 or more asks: one item each, even then; never merge asks to "
            "shorten the list. In your first reply, name any ask you dropped and why, in one line. Keep the checklist current: "
            "one item in progress at a time, completed only once its result exists, one update per finished ask. "
            "For a single simple ask, skip the checklist.")


CLAUDE_TASK_TOOLS = "TaskCreate,TaskUpdate,TaskList,TaskGet"


def claude_turn_args(text: str) -> list[str]:
    """Headless Claude Code (claude -p) hides its task tools unless they are allowed by name; without them no
    checklist reaches Neyvia's dashboard. Several-ask messages also get the intent note."""
    from .cl.protocol import primer_context
    args = ["--allowedTools", CLAUDE_TASK_TOOLS]
    note = primer_context()
    if needs_checklist(text):
        note += "\n" + turn_note(
            "TaskCreate (one task per ask), then TaskUpdate as each one moves. They may be deferred: load them with "
            "ToolSearch query \"select:TaskCreate,TaskUpdate\". On older Claude Code use TodoWrite")
    args += ["--append-system-prompt", note]
    from .proofs_c_intent import check_turn
    check_turn(text, args)
    return args


def codex_thread_params() -> dict:
    from .cl.protocol import primer_context
    return {"developerInstructions": primer_context() + "\n" + turn_note("update_plan")}


def intent_instructions(text):
    return text if INTENT_INSTRUCTIONS in text else text.rstrip() + "\n\n" + INTENT_INSTRUCTIONS


def validate_plan(steps):
    if not isinstance(steps, list) or len(steps) > 100:
        raise ValueError("plan must be an array of at most 100 steps")
    for row in steps:
        if not isinstance(row, dict) or set(row) - {"step", "status", "doneWhen"}:
            raise ValueError("Each plan step contains step, status and optional observer-based doneWhen")
        if not isinstance(row.get("step"), str) or not row["step"].strip() or len(row["step"]) > 300:
            raise ValueError("Each step needs 1–300 characters")
        if row.get("status") not in {"pending", "in_progress", "completed"}:
            raise ValueError("Use pending, in_progress or completed")
        if "doneWhen" in row:
            expression = row["doneWhen"]
            if not isinstance(expression, str) or not 1 <= len(expression) <= 12000:
                raise ValueError("doneWhen must be an observer-based CL expression of at most 12000 characters")
            import ast
            try:
                ast.parse(expression, mode="eval")
            except SyntaxError as exc:
                raise ValueError("doneWhen must be a valid CL observer expression") from exc
    if sum(row["status"] == "in_progress" for row in steps) > 1:
        raise ValueError("At most one plan step may be in_progress")
    return steps


def publish_plan(root, args):
    from .connected_sessions.plan import apply_op, replace_steps
    from .ui_command_bus import bus_for, now
    steps = validate_plan(args.get("plan"))
    session = args.get("sessionId") or "unscoped"
    if not isinstance(session, str) or len(session) > 200:
        raise ValueError("sessionId must contain at most 200 characters")
    explanation = args.get("explanation") or ""
    if not isinstance(explanation, str) or len(explanation) > 300:
        raise ValueError("explanation must contain at most 300 characters")
    bus = bus_for(root)
    previous_steps = bus.get("cl:task-goal-steps:" + session, {})
    steps = [{**row, **({"doneWhen": previous_steps[row["step"]]}
                         if "doneWhen" not in row and row["step"] in previous_steps else {})} for row in steps]
    goals = [row["doneWhen"] for row in steps if row.get("doneWhen")]
    previous_plan = bus.get("plan:" + session) or {}
    # Older saved plans predate per-step conditions. A pure status update of
    # the exact same steps preserves their existing aggregate goal as well.
    if (steps and not goals and not previous_steps
            and [row["step"] for row in steps] == [row["text"] for row in previous_plan.get("items", [])]):
        goals = bus.get("cl:task-goals:" + session, [])
    if goals:
        from .native_tools import NativeToolRegistry
        from .cl.goals import evaluate_goal
        registry = NativeToolRegistry(root)
        def readonly(name):
            exact = name if name in registry._specs else "neyvia." + name
            try:
                return registry.describe(exact).get("mutability_class") == "read"
            except KeyError:
                return False
        # Validate with an inert observer: publication never executes a goal's
        # calls, but a mutation/constant condition cannot replace valid goals.
        for expression in goals:
            checked = evaluate_goal(expression, lambda *_args: None, readonly)
            if not checked["observed"]:
                raise ValueError("doneWhen must read a grounded observer")
    op = replace_steps(steps, explanation, source="neyvia-intent")
    plan = apply_op(None, op, at=now())
    # UI plan folding intentionally projects step/status; retain executable
    # task-author conditions separately rather than losing them in that view.
    bus.put("cl:task-goals:" + session, goals)
    bus.put("cl:task-goal-steps:" + session, {row["step"]: row["doneWhen"] for row in steps if row.get("doneWhen")})
    bus.put("plan:" + session, plan)
    return {"ok": True, "plan": plan, "planOp": op, "sessionId": session, "providerCalls": 0}


def native_plan_tool(root, session_id, function_tool):
    """Bind the real SDK FunctionTool without growing the main agent's tool factory."""
    @function_tool(name_override="update_plan", description_override="Publish your intent checklist. plan_json contains {step,status,doneWhen?}; doneWhen is an observer-based CL G expression. Empty array clears. No model call.")
    def update_plan(plan_json: str, explanation: str = "") -> str:
        result = publish_plan(root, {"plan": json.loads(plan_json), "explanation": explanation, "sessionId": session_id})
        return json.dumps(result)
    return update_plan
