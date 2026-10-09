"""Run pytest in an isolated source snapshot with the INTCL safety boundary."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
import sys
import site
import hashlib
import json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--ids-file", type=Path,
                        help="JSON exact node IDs selected by the guard after full collection")
    parser.add_argument("--suite-timeout", type=float, default=86400,
                        help="Whole-suite wall budget; per-test guard remains 120 seconds")
    parser.add_argument("tests", nargs="*")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    evidence = repo / ".agent_control" / "INTCL"
    guard_dir = evidence / "python-guard"
    guard_dir.mkdir(parents=True, exist_ok=True)
    (guard_dir / "sitecustomize.py").write_text(
        "from intcl_pytest_guard import install\ninstall()\n", encoding="utf-8")
    source = args.source.resolve()
    if not source.is_relative_to(repo) or source == repo:
        parser.error("source must be an isolated snapshot inside the task workspace")
    env = dict(os.environ)
    env.update(NEYVIA_TOOL_AUTO_UPDATE="0", NEYVIA_COORDINATOR_AUTOSTART="0",
               FLUXIO_WATCHDOG_AUTOSTART="0", PYTHONUNBUFFERED="1",
               PYTHONNOUSERSITE="1",
               INTCL_GUARD_LOG=str(evidence / f"{args.label}.guard.jsonl"),
               INTCL_OUTCOME_LOG=str(evidence / f"{args.label}.outcomes.json"),
               PYTHONPATH=os.pathsep.join((str(guard_dir), str(repo / "scripts"), str(source / "src"), str(source), site.getusersitepackages())))
    if args.ids_file:
        env["INTCL_SELECTED_IDS_FILE"] = str(args.ids_file.resolve())
    else:
        env.pop("INTCL_SELECTED_IDS_FILE", None)
    evidence.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-s", "-m", "pytest", "-p", "intcl_pytest_guard", "-q", "-ra", "-o", "faulthandler_timeout=60",
               "--tb=short", "--continue-on-collection-errors", *args.tests]
    if args.collect_only:
        command.append("--collect-only")
    snapshot_manifest = source.parent / (source.name.removesuffix("-src") + "-snapshot.json")
    invocation = {"source": str(source), "command": command,
                  "guardSha256": hashlib.sha256((repo / "scripts/intcl_pytest_guard.py").read_bytes()).hexdigest(),
                  "deadlineClass": "INTCLTestDeadline(BaseException)",
                  "deadlineSeconds": env.get("INTCL_TEST_DEADLINE", "120"),
                  "suiteTimeoutSeconds": args.suite_timeout,
                  "noUserSite": True, "explicitUserPackages": site.getusersitepackages(),
                  "selectedIdsFile": env.get("INTCL_SELECTED_IDS_FILE"),
                  "snapshotManifestSha256": hashlib.sha256(snapshot_manifest.read_bytes()).hexdigest()
                  if snapshot_manifest.exists() else None}
    (evidence / f"{args.label}.invocation.json").write_text(json.dumps(invocation, indent=2) + "\n", encoding="utf-8")
    with (evidence / f"{args.label}.pytest.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT,
                                timeout=args.suite_timeout)
    print(f"{args.label}: pytest exit {result.returncode}; receipts {evidence}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
