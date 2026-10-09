"""Bounded Native runtime admission and owned-process outcome contract."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path


CONTRACT = "native.runtime.process-journey"


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise ValueError(f"Contract {CONTRACT}: {detail}")


def _child_environment() -> dict[str, str]:
    # Only pass values needed to start Python and the owned Windows cleanup tool.
    keys = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
    env = {key: os.environ[key] for key in keys if os.environ.get(key)}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _journey(state_root: Path) -> dict:
    from .native_resource_profiles import _profile_for_memory
    from .native_spawn_contracts import NativeSpawnRegistry, build_specialist_routes
    from .native_spawn_evaluator import evaluate_spawn_receipt
    from .subprocess_utils import capture_bounded_process, process_is_alive

    profile = _profile_for_memory("eco", 4096)
    require(profile["lowConsumption"] and profile["specialistLimit"] == 1
            and profile["concurrencyLimit"] == 1 and profile["verificationReserveTurns"] >= 1,
            "eco admission exceeded its single-worker bound or removed verification reserve")
    plan = {"planHash": "runtime-journey-plan", "capsule": {"specialistRoles": ["planner", "verifier"]}}
    routes = build_specialist_routes(
        "local-fixture-model", raw_overrides={"planner": {"provider": "local-process", "model": "bounded-python"}},
        behavior_plan=plan, resource_profile=profile,
    )
    require(list(routes) == ["planner"] and not routes["planner"].allow_mutations,
            "resource admission did not bound route selection and authority")

    registry = NativeSpawnRegistry(state_root, "runtime-journey-parent")
    contract = registry.start(routes["planner"], "Return a bounded local receipt", plan["planHash"])
    script = (
        "import json; print(json.dumps({'result':'bounded local journey',"
        "'role':'planner','model':'bounded-python','parent':'runtime-journey-parent'}))"
    )
    completed = capture_bounded_process(
        [sys.executable, "-c", script], cwd=state_root, env=_child_environment(),
        input_text="", timeout=4.0,
    )
    require(not completed["timedOut"] and completed["returncode"] == 0
            and not completed["stderr"], "owned child did not complete cleanly")
    projected = json.loads(completed["stdout"])
    require(projected == {
        "result": "bounded local journey", "role": "planner",
        "model": "bounded-python", "parent": "runtime-journey-parent",
    }, "child output lost or changed requested route and parent context")
    receipt = registry.finish(
        contract, status="completed", output=completed["stdout"],
        usage={"reportedByTransport": False}, run_items=["local_process_output"],
    )
    accepted = evaluate_spawn_receipt(
        receipt, expected_parent_session_id="runtime-journey-parent",
        expected_plan_hash=plan["planHash"], required_evidence=["bounded local journey"],
    )
    require(accepted["accepted"] and receipt["route"]["model"] == "bounded-python"
            and receipt["route"]["provider"] == "local-process"
            and receipt["role"] == "planner" and receipt["outputHash"],
            "completed child receipt did not preserve and validate its admitted route/output")

    timeout_contract = registry.start(routes["planner"], "Exercise bounded cancellation", plan["planHash"])
    timeout_script = (
        "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c',"
        "'import time; time.sleep(30)']); print(p.pid,flush=True); time.sleep(30)"
    )
    stopped = capture_bounded_process(
        [sys.executable, "-c", timeout_script], cwd=state_root, env=_child_environment(),
        input_text="", timeout=0.8,
    )
    try:
        descendant_pid = int(stopped["stdout"].strip().splitlines()[0])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"Contract {CONTRACT}: timed-out child did not expose its owned descendant") from exc
    require(stopped["timedOut"] and stopped["processTreeStopped"] is True
            and stopped["returncode"] is not None and not process_is_alive(descendant_pid),
            "timeout left the owned process tree alive or did not report cleanup")
    rejected_receipt = registry.finish(
        timeout_contract, status="cancelled", output=stopped["stdout"],
        error="bounded local process timed out",
    )
    rejected = evaluate_spawn_receipt(
        rejected_receipt, expected_parent_session_id="runtime-journey-parent",
        expected_plan_hash=plan["planHash"],
    )
    require(not rejected["accepted"] and any("not completed" in item for item in rejected["failures"]),
            "cancelled child was admitted as a completed result")
    return {
        "id": CONTRACT,
        "status": "PASS",
        "executed": [
            "native_resource_profiles._profile_for_memory",
            "native_spawn_contracts.build_specialist_routes",
            "native_spawn_contracts.NativeSpawnRegistry.start/finish",
            "subprocess_utils.capture_bounded_process",
            "subprocess_utils.process_is_alive",
            "native_spawn_evaluator.evaluate_spawn_receipt",
            "proofs_runtime_journey._journey",
        ],
        "positive": {"route": receipt["route"], "output": projected,
                     "evaluation": accepted["status"]},
        "refusal": {"status": rejected_receipt["status"],
                    "evaluation": rejected["status"], "processTreeStopped": stopped["processTreeStopped"],
                    "descendantAlive": process_is_alive(descendant_pid)},
        "boundary": "Runs only an owned local Python child; no provider, model, network, or live application is invoked.",
    }


def self_check(root: str | Path, selected: list[str] | None = None) -> dict:
    """Run the single measured runtime journey inside task-local SSD state."""
    if selected is not None and CONTRACT not in selected:
        return {"ok": True, "outcomes": [], "unselected": [CONTRACT]}
    repo = Path(root).resolve()
    state_root = repo / ".agent_control" / "p22" / "runtime-journey" / uuid.uuid4().hex
    state_root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    outcome = _journey(state_root)
    outcome["durationMs"] = round((time.perf_counter() - started) * 1000, 2)
    receipt_root = Path("D:/NeyviaRuns/P22/runtime-journey")
    receipt_root.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_root / f"{state_root.name}.json"
    receipt_path.write_text(json.dumps(outcome, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    outcome["receipt"] = str(receipt_path)
    return {"ok": outcome["status"] == "PASS", "outcomes": [outcome]}
