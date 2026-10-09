"""Seal the six-task smoke from original, initial, and environment-retry receipts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
EVIDENCE = REPO / "scripts/evidence/intcl"
TASKS = (1, 5, 9, 13, 17, 22)


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def artifact(path: Path):
    return {"path": path.relative_to(REPO).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial", type=Path, default=EVIDENCE / "luna-b")
    parser.add_argument("--no-retry", action="store_true", help="Seal a fresh complete six-task run without selecting environment retries")
    args = parser.parse_args()
    initial = args.initial.resolve()
    if not initial.is_relative_to(EVIDENCE):
        parser.error("initial evidence must be within scripts/evidence/intcl")
    retry = None if args.no_retry else EVIDENCE / "luna-b-native-retry"
    manifest = read(initial / "manifest.json")
    from grant_agent.cl.benchmark11 import frozen_inputs
    if frozen_inputs() != manifest["inputs"]:
        raise ValueError("The smoke's frozen inputs do not match the current source")
    if retry:
        retry_manifest = read(retry / "manifest.json")
        if manifest["inputs"] != retry_manifest["inputs"]:
            raise ValueError("Environment retry changed frozen source inputs")
        if manifest["tasks"] != retry_manifest["tasks"]:
            raise ValueError("Environment retry changed authored tasks")
    originals = {row["task"]: row for row in manifest["originals"]}
    comparisons = []
    for task in TASKS:
        before = originals[task]
        old_path = REPO / before["path"]
        if artifact(old_path)["sha256"] != before["sha256"]:
            raise ValueError(f"Original scored receipt changed: task {task}")
        relative = f"task-{task:02d}/gpt-6-luna/b/rep-1/result.json"
        initial_path = initial / relative
        after_path = (retry if retry and task in (9, 22) else initial) / relative
        after = read(after_path)
        first = read(initial_path)
        if after["seed"] != before["seed"]:
            raise ValueError(f"Paired seed changed: task {task}")
        comparisons.append({
            "task": task, "before": before,
            "after": {**artifact(after_path), **{key: after.get(key) for key in
                      ("valid", "success", "tokens", "doneStatus", "seed")}},
            "initialAttempt": {**artifact(initial_path), "valid": first["valid"],
                               "success": first["success"]},
            "newFailure": bool(before["valid"] and before["success"] and
                               not (after["valid"] and after["success"])),
        })
    result = {
        "schema": "neyvia.intcl.six-task-comparison.v1",
        "model": "gpt-6-luna", "arm": "b", "repetition": 1, "tasks": list(TASKS),
        "complete": True,
        "allPassed": all(row["after"]["valid"] and row["after"]["success"] for row in comparisons),
        "noNewFailures": not any(row["newFailure"] for row in comparisons),
        "baselineSuccess": sum(row["before"]["valid"] and row["before"]["success"] for row in comparisons),
        "afterSuccess": sum(row["after"]["valid"] and row["after"]["success"] for row in comparisons),
        "baselineTotalTokens": sum(row["before"]["tokens"]["total"] for row in comparisons),
        "afterTotalTokens": sum(row["after"]["tokens"]["total"] for row in comparisons),
        "comparisons": comparisons,
        "manifests": [artifact(initial / "manifest.json"), *([artifact(retry / "manifest.json")] if retry else [])],
        "nativeEnvironment": artifact((retry or initial) / "environment.json"),
        "scope": "Paired smoke with unchanged goals and scoring. " + (
            "Initial native 9/22 failures remain visible; these alone were rerun after staging the existing pinned local driver. " if retry else
            "Fresh six-task run of the repaired source using the existing pinned local driver. ") +
            "This is not the full benchmark confidence gate.",
    }
    destination = EVIDENCE / "six-task-comparison.json"
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("allPassed", "noNewFailures", "baselineSuccess", "afterSuccess")}))
    return int(not result["noNewFailures"])


if __name__ == "__main__":
    raise SystemExit(main())
