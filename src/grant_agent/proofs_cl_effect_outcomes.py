"""Measured CL adaptive-work journey through the real host and durable store."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .contract_gate import wants

CONTRACT = "cl.adaptive-work-journey"


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise ValueError(f"Contract {CONTRACT}: {detail}")


def check_adaptive_work_journey(root: Path) -> dict:
    """Run one compiled CL write, then prove stale work input changes no bytes."""
    from .adaptive_work import AdaptiveWorkStore
    from .proof_credential_guard import install
    from .ui_command_bus import bus_for
    from .neyvia_gateway import NeyviaToolGateway

    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    install(root)

    notes = root / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    guard_note = notes / "journey-guard.md"
    guard_note.write_text("preserve this observer", encoding="utf-8")
    bus_for(root).put("notes:folder", str(notes))

    work_id = "p22-cl-effect-" + uuid.uuid4().hex[:10]
    gateway = NeyviaToolGateway(
        root,
        allow_mutations=True,
        action_scope=work_id,
        allowed_mutation_tools={"work.problem", "work.update_problem"},
    )
    scope = ["work.problem", "work.update_problem", "neyvia.notes.read"]
    first = gateway.call_native("neyvia.cl", {"lines": "\n".join((
        'notes.read(path="journey-guard.md")',
        'G: notes.read(path="journey-guard.md").body == "preserve this observer"',
        f'run adaptive-work.record-problem(workId="{work_id}", text="Map the missing behavior 雪🙂", blocker="owned fixture")',
    )), "scopeTools": scope})
    _require(first.get("ok") is True, "the compiled CL problem journey did not pass")
    checks = [check for row in first.get("results", []) for check in row.get("checks", [])]
    _require(sum(row.get("name") == "effect-work-problem" and row.get("passed") is True
                 for row in checks) == 1, "fresh work_effects predicate did not pass exactly once")
    _require(first.get("text", "").count("R work.problem ok") == 1,
             "CL did not dispatch exactly one production work.problem action")

    store = AdaptiveWorkStore(root, work_id)
    before_rejection = store.snapshot()
    events_path = store.events
    events_before = events_path.read_bytes()
    _require(before_rejection["revision"] == 1 and len(before_rejection["problems"]) == 1,
             "the actual durable work state did not contain the requested problem")
    problem = before_rejection["problems"][0]
    _require(problem.get("text") == "Map the missing behavior 雪🙂"
             and problem.get("blocker") == "owned fixture" and problem.get("source") == "agent_report",
             "the saved user-visible problem did not preserve its exact content")

    rejected = gateway.call_native("neyvia.cl", {"lines": "\n".join((
        'G: notes.read(path="journey-guard.md").body == "preserve this observer"',
        f'run adaptive-work.record-update-problem(workId="{work_id}", problemId="problem-000000000000", status="resolved", need="test")',
    )), "scopeTools": scope})
    after_rejection = store.snapshot()
    events_after = events_path.read_bytes()
    _require(rejected.get("ok") is False and rejected.get("status") == "failed",
             "an update naming an absent problem was not refused")
    _require(after_rejection == before_rejection and events_after == events_before,
             "the refused stale problem reference changed durable state or event bytes")
    _require(guard_note.read_text(encoding="utf-8") == "preserve this observer",
             "the independent native note fact changed during the journey")
    return {
        "workId": work_id,
        "revision": after_rejection["revision"],
        "problem": problem,
        "freshEffectCheck": "effect-work-problem",
        "missingProblemRefRefused": True,
        "stateAndEventBytesPreserved": True,
        "observerNote": guard_note.read_text(encoding="utf-8"),
        "boundary": "Compiled CL, production native dispatch, fresh adaptive-work store and event reread; no model/provider call",
    }


def self_check(scratch: str | Path) -> dict:
    started = time.perf_counter()
    if not wants(CONTRACT):
        return {"contracts": [CONTRACT], "cases": [], "ok": False,
                "durationMs": round((time.perf_counter() - started) * 1000)}
    # Keep SQLite and state writes on the repository SSD. The supervisor owns
    # its disposable executor root; the durable outcome receipt may live on D:.
    state_root = Path(__file__).resolve().parents[2] / ".agent_control" / "p22" / "cl-effect-outcomes" / uuid.uuid4().hex
    try:
        observed = check_adaptive_work_journey(state_root)
        cases = [{"id": CONTRACT, "contracts": [CONTRACT], "ok": True,
                  "observed": observed}]
    except Exception as error:
        cases = [{"id": CONTRACT, "contracts": [CONTRACT], "ok": False,
                  "error": str(error)}]
        observed = None
    return {"contracts": [CONTRACT], "cases": cases,
            "ok": bool(cases) and all(row.get("ok") is True for row in cases),
            "runtimeState": str(state_root), "durationMs": round((time.perf_counter() - started) * 1000),
            **({"state": observed} if observed is not None else {})}
