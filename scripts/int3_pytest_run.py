"""Run pytest in an isolated source snapshot with the INT3 safety boundary."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
import sys
import site
import hashlib
import json
import time


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
    evidence = repo / ".agent_control" / "int3"
    # A queued matched pair may need to wait between phases for an owned HTTP
    # proof to release the same assigned ports. This precedes test invocation,
    # deadlines and timing; it cannot alter any test outcome or environment.
    start_gate = evidence / (args.label + ".start-gate.json")
    while start_gate.is_file():
        gate = json.loads(start_gate.read_text(encoding="utf-8"))
        if gate.get("ready") is True:
            break
        time.sleep(.25)
    guard_source = repo / "scripts/int3_pytest_guard.py"
    guard_sha = hashlib.sha256(guard_source.read_bytes()).hexdigest()
    guard_dir = evidence / "python-guards" / (args.label + "-" + guard_sha[:12])
    guard_dir.mkdir(parents=True, exist_ok=True)
    frozen_guard = guard_dir / "int3_pytest_guard.py"
    frozen_guard.write_bytes(guard_source.read_bytes())
    (guard_dir / "sitecustomize.py").write_text(
        "import hashlib,json,os\nimport int3_pytest_guard as guard\nguard.install()\n"
        "from pathlib import Path\n"
        "proof=os.environ.get('INT3_GUARD_MODULE_PROOF')\n"
        "if proof:\n"
        " with open(proof,'a',encoding='utf-8') as stream:\n"
        "  stream.write(json.dumps({'pid':os.getpid(),'module':guard.__file__,"
        "'sha256':hashlib.sha256(Path(guard.__file__).read_bytes()).hexdigest()})+'\\n')\n", encoding="utf-8")
    source = args.source.resolve()
    if not source.is_relative_to(repo) or source == repo:
        parser.error("source must be an isolated snapshot inside the task workspace")
    env = dict(os.environ)
    for inherited_git in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        env.pop(inherited_git, None)
    env.update(NEYVIA_TOOL_AUTO_UPDATE="0", NEYVIA_COORDINATOR_AUTOSTART="0",
               FLUXIO_WATCHDOG_AUTOSTART="0", PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1",
               NEYVIA_PROOF_SOCKETPAIR_PORTS="48654,48655,48656,48657,48658,48659",
               PYTHONNOUSERSITE="1",
               INT3_GUARD_LOG=str(evidence / f"{args.label}.guard.jsonl"),
               INT3_WORKSPACE_ROOT=str(repo),
               INT3_GUARD_MODULE_PROOF=str(evidence / f"{args.label}.module-proof.jsonl"),
               INT3_OUTCOME_LOG=str(evidence / f"{args.label}.outcomes.json"),
               PYTHONPATH=os.pathsep.join((str(guard_dir), str(repo / "scripts"), str(source / "src"), str(source), site.getusersitepackages())))
    if args.ids_file:
        env["INT3_SELECTED_IDS_FILE"] = str(args.ids_file.resolve())
    else:
        env.pop("INT3_SELECTED_IDS_FILE", None)
    evidence.mkdir(parents=True, exist_ok=True)
    temp = evidence / "pytest-temp" / args.label
    temp.mkdir(parents=True, exist_ok=True)
    env.update(TEMP=str(temp), TMP=str(temp), GIT_CEILING_DIRECTORIES=str(evidence))
    tokenizer_cache = evidence / "tokenizer-cache"
    if tokenizer_cache.exists():
        env["TIKTOKEN_CACHE_DIR"] = str(tokenizer_cache)
    command = [sys.executable, "-s", "-m", "pytest", "-p", "int3_pytest_guard", "-q", "-ra", "-o", "faulthandler_timeout=60",
               "--tb=short", "--continue-on-collection-errors", *args.tests]
    if args.collect_only:
        command.append("--collect-only")
    snapshot_manifest = source.parent / (source.name.removesuffix("-src") + "-snapshot.json")
    invocation = {"source": str(source), "command": command,
                  "guardSha256": guard_sha,
                  "frozenGuardModulePath": str(frozen_guard),
                  "frozenGuardModuleSha256": hashlib.sha256(frozen_guard.read_bytes()).hexdigest(),
                  "deadlineClass": "INT3TestDeadline(BaseException), Python pending-signal boundary",
                  "deadlineBoundary": "120-second timer schedules a Python SIGINT handler; blocking native calls return to Python before interruption; whole-suite subprocess timeout remains enforced",
                  "deadlineSeconds": env.get("INT3_TEST_DEADLINE", "120"),
                  "suiteTimeoutSeconds": args.suite_timeout,
                  "noUserSite": True, "explicitUserPackages": site.getusersitepackages(),
                  "selectedIdsFile": env.get("INT3_SELECTED_IDS_FILE"),
                  "explicitSocketpairPorts": env.get("NEYVIA_PROOF_SOCKETPAIR_PORTS"),
                  "allowedLocalhostPorts": [48651,48652,48653,48654,48655,48656,48657,48658,48659],
                  "gitCeilingDirectories": env["GIT_CEILING_DIRECTORIES"],
                  "tokenizerCacheDirectory": env.get("TIKTOKEN_CACHE_DIR"),
                  "gitMutationBoundary": "Independent .git repos inside .agent_control/int3/pytest-temp only",
                  "snapshotManifestSha256": hashlib.sha256(snapshot_manifest.read_bytes()).hexdigest()
                  if snapshot_manifest.exists() else None}
    (evidence / f"{args.label}.invocation.json").write_text(json.dumps(invocation, indent=2) + "\n", encoding="utf-8")
    started = time.monotonic()
    with (evidence / f"{args.label}.pytest.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT,
                                timeout=args.suite_timeout)
    invocation["wallSeconds"] = time.monotonic() - started
    invocation["exitCode"] = result.returncode
    (evidence / f"{args.label}.invocation.json").write_text(json.dumps(invocation, indent=2) + "\n", encoding="utf-8")
    print(f"{args.label}: pytest exit {result.returncode}; receipts {evidence}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
