"""Prove real family receipts survive worker exit and refuse corrupted claims."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker-root", type=Path)
    args = parser.parse_args()
    if args.port not in range(48741, 48750):
        parser.error("Assigned ports 48741-48749 only")
    root = args.worker_root or REPO / ".agent_control/proofs/c7-checkpoints" / uuid.uuid4().hex
    root = root.resolve()
    root.relative_to(REPO / ".agent_control/proofs")
    root.mkdir(parents=True, exist_ok=True)
    for key in ("HOME", "USERPROFILE", "CODEX_HOME", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        folder = root / "home" / key.lower()
        folder.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(folder)
    os.environ.update(NEYVIA_COORDINATOR_AUTOSTART="0", FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_TOOL_AUTO_UPDATE="0", NEYVIA_C7_PORT=str(args.port), PYTHONPATH=str(REPO / "src"))
    from grant_agent.proof_credential_guard import install
    install(root)
    from grant_agent.edge_fixture_catalog import run, completed_receipts
    if args.worker_root:
        from grant_agent.edge_contracts import inventory, CATEGORIES
        from grant_agent.proof_ports import configure_ports
        configure_ports(list(range(48741, 48750)))
        _, contracts = inventory()
        run(root / "families", contracts, CATEGORIES, ["pure"])
        # Intentionally stop before any whole-campaign receipt or second family.
        os._exit(23)
    if not args.output:
        parser.error("--output required for the parent observer")
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
    child = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--port", str(args.port), "--worker-root", str(root)],
                           cwd=REPO, env=dict(os.environ), capture_output=True, text=True, timeout=90,
                           **hidden_windows_subprocess_kwargs())
    if child.returncode != 23:
        raise ValueError("Worker did not reach intentional exit: " + child.stderr[-1200:])
    family_root = root / "families"
    index = completed_receipts(family_root)
    assert len(index) == 1 and index[0]["family"] == "pure"
    path = Path(index[0]["path"])
    original = path.read_bytes()
    index_path = family_root / "families.json"
    original_index = index_path.read_bytes()
    receipt = json.loads(original)
    observed_rows = len(receipt["rows"])
    assert observed_rows and all(row["status"] == "passed" for row in receipt["rows"])
    refusals = {}
    try:
        path.write_bytes(original + b" ")
        try:
            completed_receipts(family_root)
        except ValueError as error:
            assert "Corrupt semantic family receipt" in str(error)
            refusals["receiptBytes"] = str(error)
        else:
            raise AssertionError("Altered family receipt bytes accepted")
        receipt["sourceBindings"]["src/grant_agent/edge_contracts.py"] = "0" * 64
        path.write_text(json.dumps(receipt), encoding="utf-8")
        index[0]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        index_path.write_text(json.dumps(index), encoding="utf-8")
        try:
            completed_receipts(family_root)
        except ValueError as error:
            assert "Stale semantic family receipt" in str(error)
            refusals["sourceBinding"] = str(error)
        else:
            raise AssertionError("Changed source claim accepted")
    finally:
        path.write_bytes(original)
        index_path.write_bytes(original_index)
    restored = completed_receipts(family_root)
    args.output.resolve().relative_to(REPO)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {"schema": "neyvia.c7c.checkpoint-proof.v1", "ok": True, "explicitPort": args.port,
              "workerExit": child.returncode, "completedFamilies": restored, "observedRows": observed_rows,
              "wholeCampaignCompletionClaimed": False, "refusals": refusals,
              "restoredExactBytes": path.read_bytes() == original and index_path.read_bytes() == original_index}
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "workerExit": 23, "observedRows": observed_rows, "refused": list(refusals)}))


if __name__ == "__main__":
    main()
