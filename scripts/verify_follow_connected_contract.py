"""Replay the expanded connected command contract on an explicit owned port."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

import verify_follow_approval as guard


def main():
    guard.SCRATCH = guard.REPO / ".agent_control/follow-connected-contract"
    guard.isolate()
    path = guard.REPO / "tests/test_connected_sessions_api.py"
    spec = importlib.util.spec_from_file_location("follow_connected_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from pytest import MonkeyPatch  # fixture utility; no test runner
    rows = []
    with tempfile.TemporaryDirectory(dir=guard.SCRATCH) as directory, MonkeyPatch.context() as patch:
        # The fixture folder is deliberately a plain directory inside our
        # worktree. Prevent Git discovery from escaping to the parent repo.
        patch.setenv("GIT_CEILING_DIRECTORIES", str(guard.SCRATCH))
        fixture = module.service.__wrapped__(Path(directory), patch, port=48449)
        service = next(fixture)
        try:
            for name in ("test_every_contract_command_is_dispatched_and_shaped", "test_refusals_carry_a_code_and_the_right_status"):
                getattr(module, name)(service)
                rows.append({"id": "tests/test_connected_sessions_api.py::" + name, "passed": True})
            module.test_only_the_pc_owner_can_run_agents_or_change_files(service, patch)
            rows.append({"id": "tests/test_connected_sessions_api.py::test_only_the_pc_owner_can_run_agents_or_change_files", "passed": True})
        finally:
            fixture.close()
    result = {"passed": True, "cases": rows, "port": 48449,
              "boundary": "Real HTTP authentication, commands and owner/refusal guards with FakeAdapter protocol responses; no signed-in provider or model execution."}
    (guard.REPO / "scripts/evidence/FOLLOW-connected-contract.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
