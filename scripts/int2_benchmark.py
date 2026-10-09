"""Six unchanged CL 1.1 Luna-b tasks, paired with the original scored receipts."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import os

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.cl.benchmark11 import frozen_inputs, run, schedule, task_config

TASK_IDS = (1, 5, 9, 13, 17, 22)


def main() -> int:
    os.environ['NEYVIA_PROOF_SOCKETPAIR_PORTS'] = '48604,48605,48606,48607,48608,48609'
    from intcl_socketpair import install_explicit_socketpair
    install_explicit_socketpair()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "run", "report"))
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--output", type=Path, default=REPO / "scripts/evidence/int2/luna-b")
    parser.add_argument("--tasks", nargs="+", type=int, default=list(TASK_IDS), choices=TASK_IDS,
                        help="Original smoke IDs; choose native IDs only for an environment repair rerun")
    args = parser.parse_args()
    if args.port not in range(48603, 48610):
        parser.error("use an assigned INT2 fixture port 48603-48609")
    directory = args.output.resolve()
    if not directory.is_relative_to(REPO):
        parser.error("evidence must stay inside INT2 workspace")
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    if args.mode == "freeze":
        if manifest_path.exists():
            parser.error("frozen smoke manifest is immutable; select a new output")
        tasks = task_config()["tasks"]
        selected_ids = tuple(dict.fromkeys(args.tasks))
        selected = [row for row in tasks if row["id"] in selected_ids]
        slots = [slot for slot in schedule(selected, native_tasks=[], repetitions=1)
                 if slot["arm"] == "b" and slot["model"] == "gpt-6-luna"]
        originals = []
        for task_id in selected_ids:
            path = REPO / f"scripts/evidence/cl11/scored-2/task-{task_id:02d}/gpt-6-luna/b/rep-1/result.json"
            result = json.loads(path.read_text(encoding="utf-8"))
            originals.append({"task": task_id, "path": path.relative_to(REPO).as_posix(),
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                              **{key: result.get(key) for key in ("valid", "success", "tokens", "doneStatus", "seed")}})
        manifest = {"version": "1.1", "scored": False, "smoke": True,
                    "reviewApproved": True, "workers": 1, "seed": 110103,
                    "maxTurns": 12, "maxActions": 48,
                    "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "inputs": frozen_inputs(), "tasks": tasks, "nativeTasks": [], "schedule": slots,
                    "originals": originals,
                    "method": "Six original authored goals, unchanged fixtures and independent scoring; Luna-b rep1 paired seeds. Smoke comparison only, not a full benchmark gate.",
                    "budgets": {"nativeDeadlineSeconds": 240, "claudeMaxBudgetUSD": .25,
                                "claudeMaxOutputTokens": 1500, "proposalReasoning": "low"}}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"frozen": list(selected_ids), "originalSuccess": [row["success"] for row in originals]}))
        return 0
    summary = run(directory, port_start=args.port, limit=0 if args.mode == "report" else None)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    full = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    current = {row["task"]: row for row in full["runs"]}
    comparisons = [{"task": row["task"], "before": row,
                    "after": {key: current.get(row["task"], {}).get(key)
                              for key in ("valid", "success", "tokens", "doneStatus", "seed")},
                    "newFailure": bool(row["valid"] and row["success"] and
                                       not (current.get(row["task"], {}).get("valid") and current.get(row["task"], {}).get("success")))}
                   for row in manifest["originals"]]
    expected = len(manifest["schedule"])
    comparison = {"schema": "neyvia.int2.luna-smoke.v1", "comparisons": comparisons,
                  "complete": len(current) == expected, "newFailures": [row["task"] for row in comparisons if row["newFailure"]],
                  "allCurrentSuccessful": len(current) == expected and all(row["valid"] and row["success"] for row in current.values())}
    (directory / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: comparison[key] for key in ("complete", "newFailures", "allCurrentSuccessful")}))
    return int(not comparison["complete"] or bool(comparison["newFailures"]))


if __name__ == "__main__":
    raise SystemExit(main())
