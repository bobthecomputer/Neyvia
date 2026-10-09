"""Prove small historical invariants through the production native transport."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
checks = []
for filename, function, cls in (
    ("test_native_hooks.py", "test_hook_runs_without_shell_and_writes_receipt", None),
    ("test_native_resource_profiles.py", "test_resource_mode_aliases_and_rejection", None),
    ("test_verification.py", "test_detect_default_commands", "VerificationTests"),
):
    spec = importlib.util.spec_from_file_location(filename[:-3], REPO / "tests" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    getattr(getattr(module, cls)() if cls else module, function)()
    checks.append({"id": "tests/" + filename + "::" + (cls + "::" if cls else "") + function, "passed": True})
scratch = REPO / ".agent_control/follow-small-failures"
scratch.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir=scratch) as directory:
    requests = [{"jsonrpc": "2.0", "id": index, "method": "native.resources.resolve", "params": {"mode": mode}}
                for index, mode in enumerate(("low consumption", "low_consumption", "max", "infinite"), 1)]
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    process = subprocess.run([sys.executable, "-m", "grant_agent.neyvia_native_rpc", "--root", directory],
                             input="".join(json.dumps(row) + "\n" for row in requests), text=True,
                             capture_output=True, timeout=30, cwd=REPO, env=env,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert process.returncode == 0
    responses = [json.loads(line) for line in process.stdout.splitlines()]
    assert len(responses) == 4
    assert [row["result"]["mode"] for row in responses[:3]] == ["eco", "eco", "maximal"]
    assert responses[-1]["error"]["code"] == -32602
receipt = {"boundary": "Actual production native JSONL RPC subprocess on disposable root; real shell-free hook subprocess and exact historical cases. Verification detector exercises both availability branches, runs neither full suite.",
           "checks": checks, "nativeRpcCalls": 4, "invalidModeRefused": True,
           "hookReceiptInspectedBeforeFixtureRemoval": True, "testSuiteCommandsExecuted": False}
(REPO / "scripts/evidence/FOLLOW-small-failures.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
print(json.dumps({"passed": len(checks), "nativeRpcCalls": 4}))
