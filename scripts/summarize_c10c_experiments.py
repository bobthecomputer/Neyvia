"""Preserve isolated post-study experiments without promoting their results."""
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / ".agent_control/C10c/identityrepair"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def reference(path):
    return {"path": path.relative_to(REPO).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    native_paths = sorted({*ROOT.glob("native-candidate-*.json"),
                           *(ROOT / "candidate-history").glob("*.json")})
    attempts = []
    for path in native_paths:
        proof = read(path)
        receipt_path = Path(proof["receiptPath"])
        if not receipt_path.is_relative_to(ROOT):
            raise ValueError("Candidate receipt escaped its isolated root")
        receipt = read(receipt_path)
        if reference(receipt_path)["sha256"] != proof["receiptSha256"]:
            raise ValueError("Candidate native receipt changed")
        snapshot = ROOT / "candidate-snapshots" / proof["sourceBinding"]["research_hops.py"]
        if proof["sourceBinding"] == read(ROOT / "composed-binding.json"):
            snapshot = ROOT / "composed"
        snapshot_available = all((snapshot / name).is_file() and hashlib.sha256(
            (snapshot / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == digest
            for name, digest in proof["sourceBinding"].items())
        attempts.append({**reference(path), "receipt": reference(receipt_path),
                         "passed": proof["passed"], "status": proof["status"],
                         "sourceBinding": proof["sourceBinding"],
                         "contextCap": proof.get("contextCap"),
                         "elapsedMs": proof["elapsedMs"], "tokens": proof["tokens"],
                         "error": receipt.get("error"), "checks": proof["checks"],
                         "exactSourceSnapshotAvailable": snapshot_available,
                         "snapshot": snapshot.relative_to(REPO).as_posix() if snapshot_available else None})
    replays = []
    for path in [ROOT / "section-proof.json", ROOT / "atomic-identity-proof.json",
                 ROOT.parent / "packingrepair/packing-replay.json"]:
        replay = read(path)
        passed = replay["passed"] if "passed" in replay else all(
            c.get("passed") for c in replay.get("checks", {}).values())
        replays.append({**reference(path), "passed": passed,
            "boundary": replay["boundary"]})
    output = {"schema": "neyvia.C10c.experimental.v1", "activated": False,
              "completedPairedPanels": 0, "candidateBinding": read(ROOT / "composed-binding.json"),
              "nativeAttempts": attempts, "capturedSourceReplays": replays,
              "boundary": "Development-only isolated source after the completed corrected study; no competitive improvement or production activation is established. Individual replay proofs bind their own candidate hashes, not necessarily the latest composed candidate."}
    path = REPO / "scripts/evidence/C10c-experimental.json"
    path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": path.relative_to(REPO).as_posix(), "attempts": len(attempts),
                      "activated": False, "passedAttempts": sum(a["passed"] for a in attempts)}))


if __name__ == "__main__":
    main()
