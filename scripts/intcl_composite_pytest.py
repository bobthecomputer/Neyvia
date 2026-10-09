"""Verify complete final pytest coverage, retaining raw runs and real replacements."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[1]
CONTROL = REPO / ".agent_control/INTCL"


def read(label: str) -> dict:
    return json.loads((CONTROL / (label + ".outcomes.json")).read_text(encoding="utf-8"))


def finished(value: dict) -> set[str]:
    started = {r["nodeid"] for r in value["reports"] if r["phase"] == "setup"}
    ended = {r["nodeid"] for r in value["reports"] if r["phase"] == "teardown"}
    if not started or started != ended:
        raise ValueError("started and completed test IDs differ")
    return ended


def terminal(label: str, value: dict) -> set[str]:
    if any(r["phase"] == "collect" and r["outcome"] == "failed" for r in value["reports"]):
        raise ValueError(f"collection errors prevent complete coverage: {label}")
    ids = finished(value)
    summary = re.search(r"\d+ (?:passed|failed|skipped|errors?).* in \d+(?:\.\d+)?s",
                        (CONTROL / (label + ".pytest.log")).read_text(encoding="utf-8", errors="replace"))
    selected = set(value.get("selected_ids", value.get("collected_ids", [])))
    if value["exitstatus"] not in (0, 1) or not summary or ids != selected:
        raise ValueError(f"not a complete terminal run: {label}")
    return ids


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--replacement", action="append", default=[])
    parser.add_argument("--snapshot", action="append", default=[])
    parser.add_argument("--label", default="final-coverage")
    args = parser.parse_args()
    collection = read(args.collection)
    if collection["exitstatus"] != 0 or collection.get("collection_errors"):
        parser.error("independent latest collection failed")
    expected = set(collection["collected_ids"])
    full = read(args.full)
    full_ids = terminal(args.full, full)
    if full_ids != set(full["collected_ids"]):
        parser.error("raw full run did not execute its entire collection")
    effective = {nodeid: [r for r in full["reports"] if r["nodeid"] == nodeid] for nodeid in full_ids}
    artifacts: dict[str, dict] = {}

    def capture(path: Path) -> None:
        if path.exists():
            artifacts[path.relative_to(REPO).as_posix()] = {
                "path": path.relative_to(REPO).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def capture_run(label: str) -> None:
        for suffix in (".outcomes.json", ".pytest.log", ".invocation.json", ".guard.jsonl"):
            capture(CONTROL / (label + suffix))

    manifests = {}
    for name in args.snapshot:
        path = CONTROL / (name + "-snapshot.json")
        manifests[hashlib.sha256(path.read_bytes()).hexdigest()] = path
        capture(path)
    replacements = []
    owners = {nodeid: args.full for nodeid in full_ids}
    for label in [args.full, *args.replacement]:
        invocation = json.loads((CONTROL / (label + ".invocation.json")).read_text(encoding="utf-8"))
        manifest_sha = invocation["snapshotManifestSha256"]
        if manifest_sha not in manifests:
            parser.error(f"invocation source manifest not anchored: {label}: {manifest_sha}")
        capture_run(label)
        if label == args.full:
            continue
        value = read(label)
        ids = terminal(label, value)
        if not ids <= expected:
            parser.error(f"replacement contains IDs outside final collection: {label}")
        changes = []
        for nodeid in sorted(ids):
            before = effective.get(nodeid, [])
            after = [r for r in value["reports"] if r["nodeid"] == nodeid]
            changes.append({"nodeid": nodeid, "previousRun": owners.get(nodeid),
                            "previousFailed": any(r["outcome"] == "failed" for r in before),
                            "replacementFailed": any(r["outcome"] == "failed" for r in after)})
            effective[nodeid] = after
            owners[nodeid] = label
        replacements.append({"label": label, "caseCount": len(ids), "finishedIDs": sorted(ids),
                             "exitstatus": value["exitstatus"], "terminalSummary": True,
                             "sourceManifestSha256": manifest_sha, "guardSha256": invocation["guardSha256"],
                             "failedIDs": value["failed_ids"], "changes": changes})
    reports = [r for nodeid in sorted(effective) for r in effective[nodeid]]
    capture_run(args.collection)
    complete = set(effective) == expected and finished({"reports": reports}) == expected
    result = {"schema": "neyvia.intcl.composite-pytest.v1", "coverageComplete": complete,
              "exitstatus": None, "normalTerminalRun": False, "reports": reports,
              "failed_ids": sorted({r["nodeid"] for r in reports if r["outcome"] == "failed"}),
              "collected_ids": sorted(expected), "selected_ids": sorted(expected),
              "fullLabel": args.full, "collectionLabel": args.collection,
              "fullFinishedIDs": sorted(full_ids), "fullExitstatus": full["exitstatus"],
              "fullTerminalSummary": True, "rawFullFailedIDs": full["failed_ids"],
              "rawFullCounts": dict(Counter(r["phase"] + "/" + r["outcome"] for r in full["reports"])),
              "addedFinalIDs": sorted(expected - full_ids), "removedRawIDs": sorted(full_ids - expected),
              "replacementRuns": replacements, "effectiveRunByID": owners,
              "artifacts": list(artifacts.values()),
              "boundary": "Full final raw suite plus actual terminal replacements for late source changes and guard false positives. Original failures remain rawFullFailedIDs. Latest source changes are config validation idempotence, stale alias diagnostics, truthful CLI tool-count metadata; fixtures use assigned Windows asyncio socket ports. The read-only startup test migrates its obsolete eager manual.load expectation to CL L0 and exercises the described deferred manual.load gateway, preserving all other safety checks. Three config-validation cases are added. No replaced outcome is inferred."}
    output = CONTROL / (args.label + ".outcomes.json")
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"coverageComplete": complete, "rawCases": len(full_ids), "finalCases": len(expected),
                      "effectiveFailedIDs": len(result["failed_ids"]), "replacementRuns": len(replacements)}))
    return int(not complete)


if __name__ == "__main__":
    raise SystemExit(main())
