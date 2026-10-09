"""Replay the existing installer family against generated owned package bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.port not in range(48741, 48750):
        parser.error("Assigned C7 ports only")
    output = args.output.resolve()
    output.relative_to(REPO)
    root = REPO / ".agent_control/proofs/c7d-installer" / uuid.uuid4().hex
    root.mkdir(parents=True)
    for name in ("HOME", "USERPROFILE", "CODEX_HOME", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        directory = root / "home" / name.lower()
        directory.mkdir(parents=True)
        os.environ[name] = str(directory)
    os.environ.update(NEYVIA_C7_PORT=str(args.port), NEYVIA_TOOL_AUTO_UPDATE="0",
                      FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_COORDINATOR_AUTOSTART="0",
                      NEYVIA_NAS_ROOT=str(root), PYTHONPATH=str(REPO / "src"), PYTHONIOENCODING="utf-8")
    from grant_agent.proof_credential_guard import install
    install(root)

    def no_network(event, values):
        if event in {"socket.connect", "socket.bind", "socket.getaddrinfo"}:
            raise PermissionError("The owned installer campaign permits no network")
    sys.addaudithook(no_network)
    from grant_agent.edge_fixture_c7d_control import run
    identities = {"a-cli.installer.action", "a-cli.installer.integrity"}
    contracts = {row["id"]: row for path in (REPO / "config/proofs").glob("*.json")
                 if path.name != "test-inventory.json"
                 for row in json.loads(path.read_text(encoding="utf8")).get("contracts", [])
                 if row["id"] in identities}
    assert set(contracts) == identities
    paths = [Path(__file__), *[REPO / "src/grant_agent" / name for name in (
        "cli_installer.py", "edge_fixture_c7d_control.py", "cli_catalog.py", "durability.py",
        "proofs_a_cli.py", "proofs_a_cli_scheduler.py", "proof_credential_guard.py",
        "edge_fixture_native.py", "subprocess_utils.py", "runtimes/__init__.py", "runtimes/base.py")]]
    def bindings():
        return {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    before = bindings()
    rows = []
    for category in ("concurrency", "empty", "huge", "unicode", "permissions", "stale", "offline", "interrupted"):
        current = run(root, contracts, [category], families=["owned-installer"])
        rows.extend(current)
        (root / "progress.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf8")
        print(json.dumps({"category": category, "results": [{key: row[key] for key in ("id", "status", "durationMs")} for row in current]}), flush=True)
    # Hold one actual competing install at its packaging phase beyond the old
    # acquisition deadline. This is an explicit scheduling perturbation, not a
    # replacement installer or a substituted result; all archive, launcher,
    # manifest and rollback oracles remain the existing family builder's.
    from grant_agent import cli_installer as installer
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
    original_run = installer._run
    calls = 0
    guard = threading.Lock()
    hold = {}
    def delayed_pack(command, **kwargs):
        nonlocal calls
        selected = False
        if isinstance(command, list) and len(command) > 1 and command[1] == "pack":
            with guard:
                calls += 1
                selected = calls == 2  # Baseline install precedes eight competitors.
        if selected:
            started = time.monotonic()
            child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(31)"],
                                     **hidden_windows_subprocess_kwargs())
            try:
                code = child.wait(timeout=40)
            finally:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=5)
            hold.update(actualChildPid=child.pid, returnCode=code,
                        heldSeconds=time.monotonic() - started, childExited=child.poll() is not None)
        return original_run(command, **kwargs)
    installer._run = delayed_pack
    try:
        delayed_rows = run(root / "queued-over-deadline", {"a-cli.installer.action": contracts["a-cli.installer.action"]},
                           ["concurrency"], families=["owned-installer"])
    finally:
        installer._run = original_run
    delayed_ok = (len(delayed_rows) == 1 and delayed_rows[0]["status"] == "passed"
                  and hold.get("heldSeconds", 0) > 30 and hold.get("returnCode") == 0
                  and hold.get("childExited") and calls == 9)
    original = REPO / ".agent_control/proofs/c7/51e221fcf75f48f1ba32f9070bf21a45/semantic-fixtures/c7d-control.receipt.json"
    original_rows = json.loads(original.read_text(encoding="utf8"))["rows"]
    failed = next(row for row in original_rows if row["id"] == "c7d-control.a-cli.installer.action.concurrency")
    assert failed["status"] == "failed" and failed["detail"]["type"] == "TimeoutError"
    counts = {status: sum(row["status"] == status for row in rows) for status in ("passed", "failed")}
    stable = before == bindings()
    report = {"schema": "neyvia.c7d-installer-contention.v1", "explicitPort": args.port,
              "proofScope": "local_semantic", "scratchRoot": str(root), "sourceBindings": before,
              "sourceBindingAlgorithm": "sha256-raw-bytes", "sourceStable": stable,
              "before": {"path": str(original.relative_to(REPO)), "sha256": hashlib.sha256(original.read_bytes()).hexdigest(), "failure": failed},
              "rows": rows, "counts": counts,
              "queuedOverOriginalDeadline": {"schedulingPerturbation": "one owned hidden packaging-phase child delays the valid installer lease for 31 seconds", "actualHold": hold, "packCalls": calls, "row": delayed_rows[0], "ok": delayed_ok},
              "ok": counts == {"passed": 16, "failed": 0} and stable and delayed_ok,
              "installedProviderExecuted": False, "downloads": False, "renderedProof": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"counts": counts, "sourceStable": stable, "ok": report["ok"]}), flush=True)
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
