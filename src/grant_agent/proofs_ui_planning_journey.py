"""One user-path contract for typed mission planning and execution authority."""
from __future__ import annotations

import time


CONTRACT = "p22.ui-planning.authority-journey"
CONTRACTS = (CONTRACT,)


def _require(value: bool, detail: str) -> None:
    if not value:
        raise ValueError(f"Contract {CONTRACT}: {detail}")


def self_check(root=None):
    """Compile a reviewable plan and prove unsafe dependency structure is refused."""
    from .contract_gate import wants

    started = time.perf_counter()
    if not wants(CONTRACTS):
        return {"ok": True, "contracts": [], "cases": [], "durationMs": 0}

    from .orchestration_language import NeyviaLanguageError, compile_neyvia_program

    source = '''NEYVIA/1
GOAL text=Prepare a reviewed release plan
LANE builder runtime=neyvia-native model=local effort=low permissions=workspace.write
LANE reviewer runtime=neyvia-native model=local effort=low permissions=proof.read
STEP inspect lane=builder action=tool tool=workspace.read risk=read output=scope accept="Files are within the task root"
STEP publish lane=builder action=tool tool=release.stage after=inspect risk=external_write output=staged accept="Owner approval is recorded"
VERIFY release-proof lane=reviewer after=publish accept="The staged release has a current proof receipt"
'''
    try:
        plan = compile_neyvia_program(source)
        steps = {row["step_id"]: row for row in plan["steps"]}
        stages = [row["stepIds"] for row in plan["executionStages"]]
        _require(stages.index(["inspect"]) < stages.index(["publish"]),
                 "the execution view must place inspection before the external write")
        _require(stages.index(["publish"]) < stages.index(["release-proof"]),
                 "the proof step must wait for the staged release")
        _require(steps["publish"]["permissionEnvelope"]["approvalRequired"] is True
                 and steps["publish"]["permissionEnvelope"]["mutability"] == "external_write",
                 "the visible plan must mark external publication as approval-gated")
        _require(steps["publish"]["proofRequired"] is True
                 and steps["release-proof"]["proofRequired"] is True,
                 "both the write and verification step must retain their proof obligations")
        _require(steps["publish"]["permissionEnvelope"]["allowed"] == ["workspace.write"],
                 "the planned write must retain only the selected lane permissions")
        _require(len(plan.get("planHash", "")) == 64 and plan.get("schema") == "neyvia.orchestration_plan.v1",
                 "the compiled typed plan must remain reviewable as the canonical plan schema")

        cyclic = '''NEYVIA/1
GOAL text=Reject a cyclic execution plan
LANE builder
STEP first lane=builder action=runtime after=second
STEP second lane=builder action=runtime after=first
'''
        try:
            compile_neyvia_program(cyclic)
        except NeyviaLanguageError as error:
            _require("Dependency cycle" in str(error), "cycle refusal must explain the unsatisfied dependency order")
        else:
            raise ValueError(f"Contract {CONTRACT}: a cyclic plan was accepted")

        case = {"id": CONTRACT, "contracts": list(CONTRACTS), "ok": True,
                "stageOrder": stages, "approvalRequired": steps["publish"]["permissionEnvelope"]["approvalRequired"],
                "proofRequired": [steps["publish"]["proofRequired"], steps["release-proof"]["proofRequired"]],
                "cycleRefused": True}
        return {"ok": True, "contracts": list(CONTRACTS), "cases": [case],
                "outcomes": [{"id": CONTRACT, "status": "PASS"}], "failures": [],
                "durationMs": round((time.perf_counter() - started) * 1000, 3),
                "frontier": "Exercises the production typed planner and its review projection; it does not claim a rendered desktop or browser view."}
    except Exception as error:
        return {"ok": False, "contracts": list(CONTRACTS),
                "cases": [{"id": CONTRACT, "contracts": list(CONTRACTS), "ok": False, "error": str(error)}],
                "outcomes": [{"id": CONTRACT, "status": "FAIL", "detail": str(error)}],
                "failures": [str(error)], "durationMs": round((time.perf_counter() - started) * 1000, 3)}
