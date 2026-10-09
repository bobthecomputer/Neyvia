"""Verify the runtime-cycle fixture and the real HTTP dispatcher seam."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch

import verify_follow_failures as failures


def main():
    failures.SCRATCH = failures.REPO / ".agent_control/follow-cycle-fixture"
    failures.isolate()
    path = failures.REPO / "tests/test_web_backend.py"
    spec = importlib.util.spec_from_file_location("follow_cycle_original", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    name = "test_runtime_lane_cycle_command_dispatches_to_cycle_runner"
    getattr(module.FluxioWebBackendTests(name), name)()
    root = failures.SCRATCH / "runtime"
    root.mkdir(exist_ok=True)
    (root / "README.md").write_text("# HTTP cycle routing fixture\n", encoding="utf-8")
    observation = {}
    with failures.real_http() as (backend, request):
        from grant_agent import web_backend
        def dispatch_fixture(**kwargs):
            assert kwargs["root"] == root.resolve()
            evidence = kwargs["reader_receipt"]["workspaceEvidence"]
            assert any(item["path"] == "README.md" for item in evidence["files"])
            lane_result = {"reply": "Explicit adapter fixture; no runtime executed"}
            with patch.object(backend, "_run_agent_chat", return_value=lane_result) as lane:
                assert kwargs["runner"]({"role": "planner"}) is lane_result
            lane.assert_called_once()
            assert lane.call_args.args[0]["_allowMutation"] is False
            assert lane.call_args.kwargs["allow_mutation"] is False
            observation.update(rootScoped=True, realReadmeInHashedManifest=True,
                               plannerDelegatesToSameBackend=True, plannerMutationDenied=True)
            return {"status": "dispatch_fixture", "runtimeExecuted": False}
        assert request("/api/auth/local-session", {})["http"] == 200
        with patch.object(web_backend, "run_runtime_lane_cycle", side_effect=dispatch_fixture):
            result = request("/api/backend", {"command": "run_runtime_lane_cycle_command", "payload": {
                "objective": "Inspect the runtime-cycle dispatcher", "cycleId": "follow-http-cycle", "includeConnectedApps": False}})
        assert result["http"] == 200 and result["body"]["data"]["status"] == "dispatch_fixture"
    receipt = {"schema": "neyvia.FOLLOW.cycle-fixture.v1", "passed": True,
               "cases": [{"id": "tests/test_web_backend.py::FluxioWebBackendTests::" + name, "passed": True}],
               "actualHttpPort": 48449, "httpDispatcher": observation, "ownedServerStopped": True,
               "boundary": "real authenticated HTTP and production dispatcher/cache/manifest/delegation; explicitly controlled cycle and chat adapter fixtures, no provider/runtime/model execution or runtime-cycle completion claim"}
    output = failures.REPO / "scripts/evidence/FOLLOW-cycle-fixture.json"
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
