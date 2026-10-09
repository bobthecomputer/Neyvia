"""Compare complete guarded pytest runs by exact node IDs and phase outcomes."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default="baseline-bounded")
    parser.add_argument("--after", default="final-bounded")
    parser.add_argument("--baseline-snapshot", default="baseline")
    parser.add_argument("--after-snapshot", default="final")
    parser.add_argument("--paired-rerun", action="append", default=[],
                        help="baseline-label:after-label; retain the full initial difference and matched original-source rerun receipts")
    args = parser.parse_args()
    evidence = REPO / ".agent_control/INTCL"
    sealed = REPO / "scripts/evidence/intcl/pytest"
    sealed.mkdir(parents=True, exist_ok=True)
    rows = {}
    pairs = [tuple(value.split(":")) for value in args.paired_rerun]
    if any(len(pair) != 2 for pair in pairs):
        parser.error("paired reruns require baseline-label:after-label")
    labels = [args.baseline, args.after, *(label for pair in pairs for label in pair)]
    for label in dict.fromkeys(labels):
        path = evidence / (label + ".outcomes.json")
        if not path.is_file():
            parser.error(f"complete outcome receipt missing: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        setup_ids = {row["nodeid"] for row in value["reports"] if row["phase"] == "setup"}
        teardown_ids = {row["nodeid"] for row in value["reports"] if row["phase"] == "teardown"}
        log = evidence / (label + ".pytest.log")
        partitioned = value.get("schema") == "neyvia.intcl.partitioned-pytest.v1"
        composite = value.get("schema") == "neyvia.intcl.composite-pytest.v1"
        extra_artifacts = []
        if partitioned or composite:
            for artifact in value["artifacts"]:
                original = (REPO / artifact["path"]).resolve()
                if not original.is_relative_to(evidence) or hashlib.sha256(original.read_bytes()).hexdigest() != artifact["sha256"]:
                    parser.error(f"partition artifact changed or out of scope: {artifact['path']}")
                extra_artifacts.append(original)
            expected = set(value["collected_ids"])
            if partitioned:
                first = set(value["initialFinishedIDs"])
                last = set(value["tailFinishedIDs"])
                terminal_summary = value["tailTerminalSummary"]
                complete = (value["coverageComplete"] and bool(expected) and setup_ids == teardown_ids == expected
                            and first | last == expected and not first & last
                            and value["tailExitstatus"] in (0, 1) and terminal_summary)
            else:
                from intcl_composite_pytest import read, terminal
                raw = read(value["fullLabel"])
                raw_ids = terminal(value["fullLabel"], raw)
                reconstructed = {nodeid: [r for r in raw["reports"] if r["nodeid"] == nodeid] for nodeid in raw_ids}
                for replacement in value["replacementRuns"]:
                    actual = read(replacement["label"])
                    ids = terminal(replacement["label"], actual)
                    if ids != set(replacement["finishedIDs"]) or not ids <= expected:
                        parser.error("composite replacement ID coverage mismatch")
                    for nodeid in ids:
                        reconstructed[nodeid] = [r for r in actual["reports"] if r["nodeid"] == nodeid]
                actual_reports = [r for nodeid in sorted(reconstructed) for r in reconstructed[nodeid]]
                collected = set(read(value["collectionLabel"])["collected_ids"])
                terminal_summary = value["fullTerminalSummary"]
                complete = (value["coverageComplete"] and bool(expected) and expected == collected
                            and setup_ids == teardown_ids == set(reconstructed) == expected
                            and value["reports"] == actual_reports and raw["failed_ids"] == value["rawFullFailedIDs"]
                            and value["fullExitstatus"] in (0, 1) and terminal_summary)
        else:
            terminal_summary = bool(re.search(r"\d+ (?:passed|failed|skipped|error|errors).* in \d+(?:\.\d+)?s", log.read_text(encoding="utf-8", errors="replace")))
            collection_failed = any(row["phase"] == "collect" and row["outcome"] == "failed" for row in value["reports"])
            complete = (value["exitstatus"] in (0, 1) and bool(setup_ids) and setup_ids == teardown_ids
                        and setup_ids == set(value.get("selected_ids", setup_ids)) and terminal_summary and not collection_failed)
        guard = evidence / (label + ".guard.jsonl")
        guard_paths = [original for original in extra_artifacts if original.name.endswith(".guard.jsonl")] if partitioned or composite else [guard]
        denied = [json.loads(line) for original in guard_paths if original.exists()
                  for line in original.read_text(encoding="utf-8").splitlines()]
        artifacts = []
        invocation = evidence / (label + ".invocation.json")
        for original in dict.fromkeys((path, log, guard, invocation, *extra_artifacts)):
            if original.exists():
                destination = sealed / original.name
                shutil.copy2(original, destination)
                artifacts.append({"path": destination.relative_to(REPO).as_posix(),
                                  "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()})
        case_counts = Counter()
        for nodeid in teardown_ids:
            reports = [report for report in value["reports"] if report["nodeid"] == nodeid]
            if any(report["outcome"] == "failed" and report["phase"] in ("setup", "teardown") for report in reports):
                outcome = "errors"
            elif any(report["outcome"] == "failed" for report in reports):
                outcome = "failed"
            elif any(report["outcome"] == "skipped" for report in reports):
                outcome = "skipped"
            else:
                outcome = "passed"
            case_counts[outcome] += 1
        rows[label] = {"exitstatus": value["exitstatus"], "failed_ids": value["failed_ids"],
                       "method": "full suite with exact actual replacements" if composite else "partitioned exact collection coverage" if partitioned else "whole terminal suite",
                       "complete": complete, "startedCaseCount": len(setup_ids),
                       "finishedCaseCount": len(teardown_ids), "terminalSummary": terminal_summary,
                       "counts": dict(Counter(row["phase"] + "/" + row["outcome"] for row in value["reports"])),
                       "caseCounts": dict(case_counts),
                       "reported_ids": sorted({row["nodeid"] for row in value["reports"]}),
                       "denial_counts": dict(Counter(row["reason"] for row in denied)),
                       "receipt": (sealed / path.name).relative_to(REPO).as_posix(),
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "artifacts": artifacts}
        if composite:
            rows[label]["rawFullFailedIDs"] = value["rawFullFailedIDs"]
            rows[label]["replacementRuns"] = value["replacementRuns"]
            rows[label]["addedFinalIDs"] = value["addedFinalIDs"]
    baseline, after = rows[args.baseline], rows[args.after]
    source_artifacts = {}
    for side, name in (("baseline", args.baseline_snapshot), ("after", args.after_snapshot)):
        original = evidence / (name + "-snapshot.json")
        if not original.is_file():
            parser.error(f"source snapshot receipt missing: {original}")
        destination = sealed / original.name
        shutil.copy2(original, destination)
        source_artifacts[side] = {"path": destination.relative_to(REPO).as_posix(),
                                  "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}
    initial_new = sorted(set(after.get("rawFullFailedIDs", after["failed_ids"])) - set(baseline["failed_ids"]))
    observed_baseline_failures = set(baseline["failed_ids"])
    reruns = []
    for old_label, new_label in pairs:
        old, rerun = rows[old_label], rows[new_label]
        if not old["complete"] or not rerun["complete"]:
            parser.error(f"paired rerun is incomplete: {old_label}:{new_label}")
        if old["reported_ids"] != rerun["reported_ids"]:
            parser.error(f"paired rerun collection differs: {old_label}:{new_label}")
        observed_baseline_failures.update(old["failed_ids"])
        for nodeid in initial_new:
            if nodeid in old["reported_ids"] and nodeid in rerun["reported_ids"]:
                reruns.append({"nodeid": nodeid, "baselineReceipt": old["receipt"],
                               "afterReceipt": rerun["receipt"],
                               "baselineFailed": nodeid in old["failed_ids"],
                               "afterFailed": nodeid in rerun["failed_ids"]})
    new = sorted(set(after["failed_ids"]) - observed_baseline_failures)
    fixed = sorted(set(baseline["failed_ids"]) - set(after["failed_ids"]))
    missing = sorted(set(baseline["reported_ids"]) - set(after["reported_ids"]))
    result = {"schema": "neyvia.intcl.pytest-comparison.v1", "runs": rows,
              "sourceSnapshots": source_artifacts,
              "complete": baseline["complete"] and after["complete"],
              "firstRunNewFailures": initial_new, "newFailures": new,
              "pairedReruns": reruns, "observedBaselineFailureIDs": sorted(observed_baseline_failures),
              "replacementRuns": after.get("replacementRuns", []),
              "fixedFailures": fixed, "missingOriginalIDs": missing,
              "noNewFailures": baseline["complete"] and after["complete"] and not new and not missing,
              "boundary": "Original source coverage preserves completed initial cases and, if marked partitioned, runs every remaining exact collected ID. Final coverage preserves its whole terminal raw suite and any explicitly recorded actual terminal per-ID replacements for late source changes or guard false positives. System Python, explicit existing user-site packages with -s/NOUSERSITE, 120-second Python-level deadline; forbidden operations fail visibly. Guard differences, initial failures, test contract migration and original-source paired reruns remain visible. Not an unrestricted live-system suite."}
    destination = REPO / "scripts/evidence/intcl/pytest-comparison.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"noNewFailures": result["noNewFailures"], "newFailures": new,
                      "fixedCount": len(fixed), "missingOriginalIDs": missing}))
    return int(not result["noNewFailures"])


if __name__ == "__main__":
    raise SystemExit(main())
