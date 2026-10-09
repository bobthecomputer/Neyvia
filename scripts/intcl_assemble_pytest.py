"""Assemble honest complete collection coverage from an interrupted run and its tail.

The initial run remains partial. Completion describes exact case coverage across
the preserved initial cases and a real terminal tail, never a fabricated exit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", default="baseline-safe-collection-v2")
    parser.add_argument("--partial", default="baseline-partial-before-wrapper-guard")
    parser.add_argument("--tail", default="baseline-tail-safe-v2")
    parser.add_argument("--label", default="baseline-coverage")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    control = repo / ".agent_control/INTCL"
    collection_path = control / (args.collection + ".outcomes.json")
    collection = json.loads(collection_path.read_text(encoding="utf-8"))
    partial_path = control / (args.partial + ".outcomes.json.progress.jsonl")
    partial = [json.loads(line) for line in partial_path.read_text(encoding="utf-8").splitlines()]
    tail_path = control / (args.tail + ".outcomes.json")
    tail = json.loads(tail_path.read_text(encoding="utf-8"))
    tail_log = control / (args.tail + ".pytest.log")
    expected = set(collection["collected_ids"])
    first_finished = {row["nodeid"] for row in partial if row["phase"] == "teardown"}
    last_started = {row["nodeid"] for row in tail["reports"] if row["phase"] == "setup"}
    last_finished = {row["nodeid"] for row in tail["reports"] if row["phase"] == "teardown"}
    selected = set(tail["selected_ids"])
    terminal = bool(re.search(r"\d+ (?:passed|failed|skipped|error|errors).* in \d+(?:\.\d+)?s", tail_log.read_text(encoding="utf-8", errors="replace")))
    complete = (set(tail["collected_ids"]) == expected and first_finished <= expected
                and selected == expected - first_finished
                and last_started == last_finished == selected
                and not first_finished & last_finished
                and first_finished | last_finished == expected
                and tail["exitstatus"] in (0, 1) and terminal)
    reports = [row for row in partial if row["nodeid"] in first_finished] + tail["reports"]
    artifacts = []
    for path in (collection_path, partial_path, tail_path, tail_log,
                 control / (args.partial + ".pytest.log"),
                 control / (args.partial + ".guard.jsonl"),
                 control / (args.tail + ".guard.jsonl"),
                 control / (args.tail + ".invocation.json")):
        if path.exists():
            artifacts.append({"path": path.relative_to(repo).as_posix(),
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    result = {"schema": "neyvia.intcl.partitioned-pytest.v1", "coverageComplete": complete,
              "exitstatus": None, "normalTerminalRun": False,
              "reports": reports, "failed_ids": sorted({row["nodeid"] for row in reports if row["outcome"] == "failed"}),
              "collected_ids": sorted(expected), "selected_ids": sorted(expected),
              "initialFinishedIDs": sorted(first_finished), "tailFinishedIDs": sorted(last_finished),
              "tailExitstatus": tail["exitstatus"], "tailTerminalSummary": terminal,
              "collectionLabel": args.collection, "partialLabel": args.partial, "tailLabel": args.tail,
              "artifacts": artifacts,
              "boundary": "Original source: initial guarded run's completed cases plus all remaining exact IDs under the tightened Windows-provider-wrapper guard. The interrupted initial run remains explicitly partial. User-site packages added explicitly while -s/NOUSERSITE suppress inherited usercustomize."}
    output = control / (args.label + ".outcomes.json")
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"coverageComplete": complete, "initialFinished": len(first_finished),
                      "tailFinished": len(last_finished), "expected": len(expected),
                      "failedIDs": len(result["failed_ids"])}))
    return int(not complete)


if __name__ == "__main__":
    raise SystemExit(main())
