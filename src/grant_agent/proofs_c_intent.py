"""Intent-turn contracts at the existing harness argument boundary."""
from __future__ import annotations

CONTRACTS = ["proofs-c.intent.task-tools", "proofs-c.intent.multi-ask-note"]


def check_turn(text, arguments):
    from .neyvia_intent_plan import CLAUDE_TASK_TOOLS, _ASK_MARKERS, turn_note
    normalized = text if isinstance(text, str) else ""
    multi = len(normalized.split()) >= 60 or len(_ASK_MARKERS.findall(normalized)) >= 2
    expected = ["--allowedTools", CLAUDE_TASK_TOOLS]
    if arguments[:2] != expected:
        raise ValueError("proofs-c.intent.task-tools: every headless turn must expose task tools")
    from .cl.protocol import primer_context
    expected_note = primer_context()
    if multi:
        expected_note += "\n" + turn_note(
            "TaskCreate (one task per ask), then TaskUpdate as each one moves. They may be deferred: load them with "
            "ToolSearch query \"select:TaskCreate,TaskUpdate\". On older Claude Code use TodoWrite")
    if arguments != expected + ["--append-system-prompt", expected_note]:
        raise ValueError("proofs-c.intent.multi-ask-note: CL primer or required intent instructions changed")



def self_check(root):
    from .neyvia_intent_plan import claude_turn_args, needs_checklist, turn_note
    samples = [("Repair the icon", False), ("Why is this slow?", False),
               ("Check the build? Also rename the button.", True),
               (" ".join(["dictated"] * 60), True), (None, False)]
    cases = []
    for text, wanted in samples:
        result = claude_turn_args(text)
        if needs_checklist(text) != wanted or (turn_note("").split("Tools:")[0] in result[3]) != wanted:
            raise ValueError("Intent turn gate diverged from the observed message")
        cases.append({"id": "multi-ask" if wanted else "simple-turn", "ok": True})
    try:
        check_turn("short", ["--allowedTools", "Read"])
    except ValueError:
        cases.append({"id": "corrupt-harness-arguments-denied", "ok": True})
    else:
        raise ValueError("Task tool omission was accepted")
    for text in ("short", "Check the build? Also rename the button."):
        corrupted = claude_turn_args(text)
        corrupted[3] = corrupted[3] + " mutated"
        try:
            check_turn(text, corrupted)
        except ValueError:
            cases.append({"id": "corrupt-primer-or-intent-note-denied", "ok": True})
        else:
            raise ValueError("Changed CL primer or checklist note was accepted")
    return {"ok": True, "contracts": CONTRACTS, "cases": cases, "scratchRoot": str(root)}
