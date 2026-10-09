"""Replay reviewed explicit Codex permission and Cursor flag invariants."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile

import verify_follow_failures as failures


def main():
    failures.SCRATCH = failures.REPO / ".agent_control/follow-permission-fixture"
    failures.isolate()
    path = failures.REPO / "tests/test_neyvia_harnesses.py"
    spec = importlib.util.spec_from_file_location("follow_permission_original", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    name = "test_codex_and_cursor_only_receive_write_flags_for_executor_lane"
    with tempfile.TemporaryDirectory() as fixture:
        getattr(module, name)(Path(fixture))
    receipt = {"schema": "neyvia.FOLLOW.permission-fixture.v1", "passed": True,
               "cases": [{"id": "tests/test_neyvia_harnesses.py::" + name, "passed": True}],
               "readOnlyCodexDeniedWrite": True, "explicitWorkspacePermissionAccepted": True,
               "allowMutationAloneStillReadOnly": True, "cursorNegativeAndPositiveForcePreserved": True,
               "boundary": "actual production command construction, original four flag assertions retained and one new negative; captured subprocess fixture, no model/runtime launch or guard changes"}
    output = failures.REPO / "scripts/evidence/FOLLOW-permission-fixture.json"
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
