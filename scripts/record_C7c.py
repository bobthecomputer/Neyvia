"""Seal a compact C7c receipt with a compressed, independently reconciled matrix."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.port not in range(48741, 48750):
        parser.error("Assigned ports 48741-48749 only")
    source, target = args.input.resolve(), args.output.resolve()
    for path in (source, target):
        path.relative_to(REPO / "scripts/evidence")
    if source.stat().st_size > 128 * 1024 * 1024 or source == target:
        raise ValueError("Use a distinct, bounded owned full campaign artifact")
    raw = source.read_bytes()
    full = json.loads(raw)
    from grant_agent.proof_contracts import source_digest
    from grant_agent.edge_fixture_catalog import completed_receipts
    for name, expected in full["sourceBindings"].items():
        path = (REPO / name).resolve()
        path.relative_to(REPO)
        if source_digest(path) != expected:
            raise ValueError("Campaign source no longer current: " + name)
    if not full["ok"] or not full["sourceStable"] or full["explicitPort"] != args.port:
        raise ValueError("Campaign did not pass on stable source and selected port")
    arrays = {"schema": "schemaCases", "postconditions": "postconditionCases", "journeys": "journeys", "semanticCoverage": "semanticCoverage"}
    counts = {key: dict(Counter(row["status"] for row in full[value])) for key, value in arrays.items()}
    if counts != full["counts"] or full["failures"]:
        raise ValueError("Campaign totals do not reconcile with actual observations")
    families = completed_receipts(Path(full["root"]) / "semantic-fixtures")
    if families != full["familyReceipts"]:
        raise ValueError("Family index differs from the campaign artifact")
    baseline_path = REPO / "scripts/evidence/C7.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    actual = {(r["contract"], r["category"]): r for r in full["semanticCoverage"]}
    original = [r for r in baseline["semanticCoverage"] if r["status"] == "blocked"]
    if len(actual) != len(full["semanticCoverage"]):
        raise ValueError("Duplicate matrix obligations")
    if any((r["contract"], r["category"]) not in actual for r in baseline["semanticCoverage"]):
        raise ValueError("Original matrix obligation disappeared")
    reconciliation = dict(Counter(actual[(r["contract"], r["category"])]["status"] for r in original))
    if reconciliation != full["baseline"]["formerlyBlocked"]:
        raise ValueError("Original blocked-pair reconciliation differs")
    host = full["hostProof"]
    host_path = (REPO / host["path"]).resolve()
    host_path.relative_to(REPO / "scripts/evidence")
    if hashlib.sha256(host_path.read_bytes()).hexdigest() != host["sha256"]:
        raise ValueError("Host proof bytes changed")
    host_data = json.loads(host_path.read_text(encoding="utf-8"))
    if not host_data["ok"] or not all(row["passed"] for row in host_data["manualChecks"]):
        raise ValueError("Executable host/manual journey failed")
    compressed = target.with_name(target.stem + "-full.json.gz")
    with compressed.open("wb") as stream:
        with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0) as writer:
            writer.write(raw)
    blocked = [r for r in actual.values() if r["status"] == "blocked"]
    blocked_kinds = dict(Counter(r["blockerKind"] for r in blocked))
    commits = subprocess.run(["git", "log", "f2c5bd08..HEAD", "--format=%h %s"], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout.splitlines()
    report = {"schema": "neyvia.c7c-receipt.v1", "ok": True, "complete": full["complete"],
              "sourceCurrent": True, "sourceStable": True, "explicitPort": args.port,
              "durationMs": full["durationMs"], "inventory": full["inventory"], "counts": counts,
              "baseline": full["baseline"], "semanticSummary": full["semanticSummary"],
              "blockedKinds": blocked_kinds,
              "remainingByOrigin": dict(Counter(r["contract"].split(".")[0] for r in blocked if r["blockerKind"] == "fixture_gap")),
              "remainingByCategory": dict(Counter(r["category"] for r in blocked if r["blockerKind"] == "fixture_gap")),
              "completionGate": "Effect fixtures or audited reasons must account for each original pair. Fixture gaps remain work; not-applicable and authority-boundary rows are never passed fixtures.",
              "familyReceipts": families, "hostProof": host, "sourceBindings": full["sourceBindings"],
              "fullMatrix": {"path": compressed.relative_to(REPO).as_posix(), "sha256": hashlib.sha256(compressed.read_bytes()).hexdigest(),
                             "compressedBytes": compressed.stat().st_size, "uncompressedBytes": len(raw),
                             "uncompressedSha256": hashlib.sha256(raw).hexdigest()},
              "commitsBeforeReceipt": commits,
              "boundaries": ["Owned local state and explicit loopback ports only; no NAS sync, credentials, protected live trees, supervisor or public service changes.",
                             "Frontend model fixtures are model proofs. Chrome surface inventory was empty; rendered UI, physical devices and live providers are not proved.",
                             "No test retirement, public promotion, push or merge."]}
    target.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "complete": report["complete"], "originalPairs": len(original),
                      "formerlyBlocked": reconciliation, "blockedKinds": blocked_kinds, "compressedBytes": compressed.stat().st_size}))


if __name__ == "__main__":
    main()
