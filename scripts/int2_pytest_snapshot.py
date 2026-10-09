"""Capture current tracked source bytes for an isolated INT2 pytest run."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--base-evidence", type=Path, help="Original snapshot supplying unchanged historical evidence")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    control = repo / ".agent_control/int2"
    target = control / (args.label + "-src")
    if target.exists():
        parser.error("snapshot exists; use a fresh label")
    target.mkdir(parents=True)
    names = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=repo).decode("utf-8").split("\0")
    hashes, excluded = {}, []
    baseline = args.base_evidence.resolve() if args.base_evidence else None
    if baseline and not baseline.is_relative_to(control):
        parser.error("baseline evidence source must be inside INT2 scratch")
    baseline_manifest = json.loads((baseline.parent / (baseline.name.removesuffix("-src") + "-snapshot.json")).read_text(encoding="utf-8")) if baseline else None
    preserved_evidence = []
    for name in sorted(set(names)):
        if not name:
            continue
        normalized = name.lower()
        if normalized.startswith(".agent_control/") or any(word in normalized for word in ("nas_access_runbook", "nas_codex2_", "auth.json", "credentials.json", "admin_password")):
            excluded.append(name)
            continue
        source = repo / name
        if baseline and name.startswith("scripts/evidence/"):
            if name in baseline_manifest["hashes"]:
                source = baseline / name
                preserved_evidence.append(name)
            elif normalized.startswith(("scripts/evidence/cl/", "scripts/evidence/cl11/", "scripts/evidence/intcl/", "scripts/evidence/int2/")) or normalized == "scripts/evidence/int2.json":
                excluded.append(name)
                continue
        if not source.is_file():
            continue
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        hashes[name] = hashlib.sha256(destination.read_bytes()).hexdigest()
    manifest = {"snapshot": str(target), "files": len(hashes), "hashes": hashes,
                "excluded": excluded, "preservedBaselineEvidence": preserved_evidence,
                "baselineEvidenceSource": str(baseline) if baseline else None,
                "archivalExclusionBoundary": "New historical CL/cl11/INTCL raw runs and live INT2 receipts only; all current implementation, config, manuals, docs, tests and scripts retained",
                "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()}
    (control / (args.label + "-snapshot.json")).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"snapshot": str(target), "files": len(hashes), "excludedCount": len(excluded), "preservedBaselineEvidenceCount": len(preserved_evidence)}))


if __name__ == "__main__":
    main()
