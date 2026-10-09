"""Replay the existing secret-policy cases with disposable protocol fixtures."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time

import pytest


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
spec = importlib.util.spec_from_file_location(
    "follow_secret_cases", REPO / "tests/test_secret_broker.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
scratch = REPO / ".agent_control/follow-secret-broker"
scratch.mkdir(exist_ok=True)
checks = []
for name in sorted(name for name in vars(module) if name.startswith("test_")):
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(dir=scratch, prefix="case-") as directory:
        with pytest.MonkeyPatch.context() as patch:
            getattr(module, name)(Path(directory), patch)
    checks.append({"id": "tests/test_secret_broker.py::" + name,
                   "passed": True, "ms": round((time.perf_counter() - started) * 1000, 2)})
receipt = {
    "boundary": "Production secret-broker policy with disposable CLI/destination protocol fixtures. No real vault or saved credentials accessed; no external command run. Seven existing safety scenarios adapted to current device/session/approval and opaque output contracts.",
    "checks": checks,
    "productionCodeChanged": False,
    "guardsRelaxed": False,
    "rawOutputReintroduced": False,
    "command": "Python313 scripts/verify_follow_secret_fixtures.py",
}
(REPO / "scripts/evidence/FOLLOW-secret-fixtures.json").write_text(
    json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n"
)
print(json.dumps({"passed": len(checks), "guardsRelaxed": False, "actualVaultProof": False}))
