"""Run pytest in an isolated source snapshot with the INT2 safety boundary."""
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
    evidence = repo / ".agent_control" / "int2"
    guard_source = repo / "scripts/int2_pytest_guard.py"
    guard_sha = hashlib.sha256(guard_source.read_bytes()).hexdigest()
    guard_dir = evidence / "python-guards" / (args.label + "-" + guard_sha[:12])
    guard_dir.mkdir(parents=True, exist_ok=True)
    frozen_guard = guard_dir / "int2_pytest_guard.py"
    frozen_guard.write_bytes(guard_source.read_bytes())
    (guard_dir / "sitecustomize.py").write_text(
        "import hashlib,json,os\nimport int2_pytest_guard as guard\nguard.install()\n"
        "from pathlib import Path\n"
        "proof=os.environ.get('INT2_GUARD_MODULE_PROOF')\n"
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
               FLUXIO_WATCHDOG_AUTOSTART="0", PYTHONUNBUFFERED="1",
               NEYVIA_PROOF_SOCKETPAIR_PORTS="48604,48605,48606,48607,48608,48609",
               PYTHONNOUSERSITE="1",
               INT2_GUARD_LOG=str(evidence / f"{args.label}.guard.jsonl"),
               INT2_WORKSPACE_ROOT=str(repo),
               INT2_GUARD_MODULE_PROOF=str(evidence / f"{args.label}.module-proof.jsonl"),
               INT2_OUTCOME_LOG=str(evidence / f"{args.label}.outcomes.json"),
               PYTHONPATH=os.pathsep.join((str(guard_dir), str(repo / "scripts"), str(source / "src"), str(source), site.getusersitepackages())))
    if args.ids_file:
        env["INT2_SELECTED_IDS_FILE"] = str(args.ids_file.resolve())
    else:
        env.pop("INT2_SELECTED_IDS_FILE", None)
    evidence.mkdir(parents=True, exist_ok=True)
    temp = evidence / "pytest-temp" / args.label
    temp.mkdir(parents=True, exist_ok=True)
    env.update(TEMP=str(temp), TMP=str(temp), GIT_CEILING_DIRECTORIES=str(evidence))
    tokenizer_cache = evidence / "tokenizer-cache"
    if tokenizer_cache.exists():
        env["TIKTOKEN_CACHE_DIR"] = str(tokenizer_cache)
    command = [sys.executable, "-s", "-m", "pytest", "-p", "int2_pytest_guard", "-q", "-ra", "-o", "faulthandler_timeout=60",
               "--tb=short", "--continue-on-collection-errors", *args.tests]
    if args.collect_only:
        command.append("--collect-only")
    snapshot_manifest = source.parent / (source.name.removesuffix("-src") + "-snapshot.json")
    invocation = {"source": str(source), "command": command,
                  "guardSha256": guard_sha,
                  "frozenGuardModulePath": str(frozen_guard),
                  "frozenGuardModuleSha256": hashlib.sha256(frozen_guard.read_bytes()).hexdigest(),
                  "deadlineClass": "INT2TestDeadline(BaseException)",
                  "deadlineSeconds": env.get("INT2_TEST_DEADLINE", "120"),
                  "suiteTimeoutSeconds": args.suite_timeout,
                  "noUserSite": True, "explicitUserPackages": site.getusersitepackages(),
                  "selectedIdsFile": env.get("INT2_SELECTED_IDS_FILE"),
                  "explicitSocketpairPorts": env.get("NEYVIA_PROOF_SOCKETPAIR_PORTS"),
                  "allowedLocalhostPorts": [48601,48602,48603,48604,48605,48606,48607,48608,48609],
                  "gitCeilingDirectories": env["GIT_CEILING_DIRECTORIES"],
                  "tokenizerCacheDirectory": env.get("TIKTOKEN_CACHE_DIR"),
                  "gitMutationBoundary": "Independent .git repos inside .agent_control/int2/pytest-temp only",
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
