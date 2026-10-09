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
    evidence = REPO / ".agent_control/int2"
    sealed = REPO / "scripts/evidence/int2/pytest"
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
        partitioned = value.get("schema") == "neyvia.int2.partitioned-pytest.v1"
        composite = value.get("schema") == "neyvia.int2.composite-pytest.v1"
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
                from int2_pytest_composite import read, terminal
                raw = read(value["fullLabel"])
                raw_ids = terminal(value["fullLabel"], raw, allow_collection_errors=True)
                reconstructed = {nodeid: [r for r in raw["reports"] if r["nodeid"] == nodeid] for nodeid in raw_ids}
                for replacement in value["replacementRuns"]:
                    actual = read(replacement["label"])
                    ids = terminal(replacement["label"], actual)
                    if ids != set(replacement["finishedIDs"]) or not ids <= expected:
                        parser.error("composite replacement ID coverage mismatch")
                    for nodeid in ids:
                        reconstructed[nodeid] = [r for r in actual["reports"] if r["nodeid"] == nodeid]
                actual_reports = [r for nodeid in sorted(reconstructed) for r in reconstructed[nodeid]]
                raw_collect_modules = sorted({r["nodeid"] for r in raw["reports"]
                                              if r["phase"] == "collect" and r["outcome"] == "failed"})
                recovery = value.get("rawCollectionRecovery", [])
                recovered_modules = sorted(row["module"] for row in recovery)
                recovered = recovered_modules == raw_collect_modules
                for row in recovery:
                    module_ids = {nodeid for nodeid in expected if nodeid.startswith(row["module"] + "::")}
                    valid_runs = [replacement for replacement in value["replacementRuns"]
                                  if module_ids <= set(replacement["finishedIDs"])]
                    recovered = (recovered and bool(module_ids) and row["expectedModuleIDs"] == sorted(module_ids)
                                 and row["actualCompleteReplacementLabels"] == [run["label"] for run in valid_runs])
                collected = set(read(value["collectionLabel"])["collected_ids"])
                terminal_summary = value["fullTerminalSummary"]
                complete = (value["coverageComplete"] and recovered and bool(expected) and expected == collected
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
        module_proof = evidence / (label + ".module-proof.jsonl")
        for original in dict.fromkeys((path, log, guard, invocation, module_proof, *extra_artifacts)):
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
            rows[label]["rawCollectionFailureModules"] = value.get("rawCollectionFailureModules", [])
            rows[label]["rawCollectionRecovery"] = value.get("rawCollectionRecovery", [])
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
    baseline_invocation = json.loads((evidence / (args.baseline + ".invocation.json")).read_text(encoding="utf-8"))
    effective_after = json.loads((evidence / (args.after + ".outcomes.json")).read_text(encoding="utf-8"))
    after_invocation_label = effective_after.get("fullLabel", args.after)
    after_invocation = json.loads((evidence / (after_invocation_label + ".invocation.json")).read_text(encoding="utf-8"))
    final_manifest_shas = {source_artifacts["after"]["sha256"]}
    final_manifest_shas.update(artifact["sha256"] for artifact in effective_after.get("artifacts", [])
                               if artifact["path"].endswith("-snapshot.json"))
    guard_equal = baseline_invocation["guardSha256"] == after_invocation["guardSha256"]
    equivalence_path = sealed / "guard-equivalence.json"
    equivalence = json.loads(equivalence_path.read_text(encoding="utf-8"))
    corrected_sha = equivalence["correctedGuardSha256"]
    old_guard_archive = sealed / "guard-before-git-parser-repair.py"
    corrected_guard_archive = sealed / "guard-corrected-source.py"
    freeze_path = sealed / "old-guard-freeze.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    frozen_old = Path(freeze["frozenModulePath"])
    old_guard_stable = (frozen_old.resolve().is_relative_to(evidence.parent)
                        and hashlib.sha256(frozen_old.read_bytes()).hexdigest() == freeze["oldSha256"]
                        == equivalence["oldGuardSha256"] and not freeze["liveGuardEditedBeforeFreeze"])
    boundaries_unchanged = (equivalence["unchangedSecurityBoundaries"]
                            and all(equivalence["unchangedOtherFunctions"].values())
                            and all(equivalence["validation"]["checks"].values())
                            and old_guard_stable
                            and hashlib.sha256(old_guard_archive.read_bytes()).hexdigest() == equivalence["oldGuardSha256"]
                            and hashlib.sha256(corrected_guard_archive.read_bytes()).hexdigest() == corrected_sha
                            and equivalence["oldGuardSha256"] == baseline_invocation["guardSha256"]
                            and equivalence["validation"]["moduleSha256"] == corrected_sha)
    matched_replacements = {}

    def invocation_for(label):
        return json.loads((evidence / (label + ".invocation.json")).read_text(encoding="utf-8"))

    def verified_module(label, invocation):
        proof = evidence / (label + ".module-proof.jsonl")
        modules = [json.loads(line) for line in proof.read_text(encoding="utf-8").splitlines()] if proof.exists() else []
        return (bool(modules) and invocation.get("frozenGuardModuleSha256") == corrected_sha
                and all(row["sha256"] == corrected_sha
                        and row["module"] == invocation["frozenGuardModulePath"] for row in modules))

    for old_label, new_label in pairs:
        old_invocation, new_invocation = invocation_for(old_label), invocation_for(new_label)
        parity_fields = ("allowedLocalhostPorts", "deadlineClass", "deadlineSeconds", "noUserSite",
                         "explicitUserPackages", "explicitSocketpairPorts", "gitCeilingDirectories",
                         "gitMutationBoundary", "tokenizerCacheDirectory")
        environment_matched = all(old_invocation.get(key) == new_invocation.get(key) for key in parity_fields)
        source_matched = (old_invocation["source"] == baseline_invocation["source"]
                          and new_invocation["snapshotManifestSha256"] in final_manifest_shas)
        guards_matched = (old_invocation["guardSha256"] == new_invocation["guardSha256"] == corrected_sha
                          and verified_module(old_label, old_invocation) and verified_module(new_label, new_invocation)
                          and source_matched and environment_matched)
        if not guards_matched:
            parser.error(f"paired replacement actual frozen guards differ: {old_label}:{new_label}")
        matched_replacements[new_label] = {"baselineLabel": old_label, "afterLabel": new_label,
                                            "identicalCorrectedGuard": guards_matched,
                                            "matchedEnvironmentFields": list(parity_fields),
                                            "matchedOriginalAndCurrentSource": source_matched,
                                            "finishedIDs": rows[new_label]["reported_ids"]}
    replacement_guard_checks = []
    original_ids = set(baseline["reported_ids"])
    for replacement in after.get("replacementRuns", []):
        label = replacement["label"]
        ids = set(replacement["finishedIDs"])
        shared = ids & original_ids
        invocation = invocation_for(label)
        valid = (invocation["guardSha256"] == corrected_sha and verified_module(label, invocation)
                 and (not shared or label in matched_replacements
                      and shared <= set(matched_replacements[label]["finishedIDs"])))
        replacement_guard_checks.append({"label": label, "guardSha256": invocation["guardSha256"],
                                         "sharedOriginalIDs": sorted(shared), "newOnlyIDs": sorted(ids-original_ids),
                                         "matchedOriginalRun": matched_replacements.get(label), "validated": valid})
    replacement_guards_matched = (boundaries_unchanged and bool(replacement_guard_checks)
                                  and all(row["validated"] for row in replacement_guard_checks))
    integrity_path = sealed / "post-test-source-integrity.json"
    integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    tested_sources_unchanged = (integrity["allUnchanged"]
                                and all(row["unchanged"] and not row["mismatches"] for row in integrity["snapshots"])
                                and {"baseline", "final-bounded", "final-current", "final-repaired"}
                                <= {row["snapshot"] for row in integrity["snapshots"]})
    new = sorted(set(after["failed_ids"]) - observed_baseline_failures)
    fixed = sorted(set(baseline["failed_ids"]) - set(after["failed_ids"]))
    missing = sorted(set(baseline["reported_ids"]) - set(after["reported_ids"]))
    result = {"schema": "neyvia.int2.pytest-comparison.v1", "runs": rows,
              "sourceSnapshots": source_artifacts,
              "complete": baseline["complete"] and after["complete"],
              "firstRunNewFailures": initial_new, "newFailures": new,
              "pairedReruns": reruns, "observedBaselineFailureIDs": sorted(observed_baseline_failures),
              "replacementRuns": after.get("replacementRuns", []),
              "fixedFailures": fixed, "missingOriginalIDs": missing,
              "identicalGuard": guard_equal,
              "rawFullIdenticalGuard": guard_equal,
              "rawOldGuardFrozenBeforeCorrection": old_guard_stable,
              "oldGuardFreezeReceipt": {"path": freeze_path.relative_to(REPO).as_posix(),
                                         "sha256": hashlib.sha256(freeze_path.read_bytes()).hexdigest()},
              "matchedReplacementGuardReceipt": replacement_guards_matched,
              "unchangedSecurityBoundaries": boundaries_unchanged,
              "unchangedTestedSources": tested_sources_unchanged,
              "testedSourceIntegrityReceipt": {"path": integrity_path.relative_to(REPO).as_posix(),
                                               "sha256": hashlib.sha256(integrity_path.read_bytes()).hexdigest()},
              "replacementGuardChecks": replacement_guard_checks,
              "guardEquivalenceReceipt": {"path": equivalence_path.relative_to(REPO).as_posix(),
                                           "sha256": hashlib.sha256(equivalence_path.read_bytes()).hexdigest()},
              "noNewFailures": (baseline["complete"] and after["complete"] and guard_equal
                                and replacement_guards_matched and tested_sources_unchanged and not new and not missing),
              "boundary": "Complete original-source guarded suite versus whole terminal integrated raw suite and exact actual replacements for source repairs or task-local public tokenizer cache recovery. System Python, explicit existing user packages with -s/NOUSERSITE, 120-second per-test deadline, unchanged guarded localhost ports48601-48609, independent disposable Git repos only, no private credentials/provider/service access. Interrupted first trial is excluded. Raw failures, cache timing, source deltas and paired original-source reruns remain visible. This is scoped full coverage, not unrestricted live-system testing."}
    destination = REPO / "scripts/evidence/int2/pytest/comparison.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"noNewFailures": result["noNewFailures"], "newFailures": new,
                      "fixedCount": len(fixed), "missingOriginalIDs": missing}))
    return int(not result["noNewFailures"])


if __name__ == "__main__":
    raise SystemExit(main())
