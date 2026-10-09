"""Verify the MS seal against actual files or the exact committed Git blobs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--committed", action="store_true")
    args = parser.parse_args()
    seal = json.loads((ROOT / "scripts/evidence/MS.json").read_text(encoding="utf-8"))
    artifacts = seal["artifacts"]
    if args.committed:
        queries = "".join("HEAD:" + row["path"] + "\n" for row in artifacts)
        output = subprocess.check_output(["git", "cat-file", "--batch"], input=queries.encode(), cwd=ROOT)
        blobs, offset = [], 0
        for row in artifacts:
            end = output.index(b"\n", offset)
            header = output[offset:end].split()
            if len(header) != 3 or header[1] != b"blob":
                raise ValueError("Missing committed artifact: " + row["path"])
            size = int(header[2])
            blobs.append(output[end + 1:end + 1 + size])
            offset = end + size + 2
    else:
        blobs = [(ROOT / row["path"]).read_bytes() for row in artifacts]
    for row, data in zip(artifacts, blobs):
        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("Artifact bytes changed: " + row["path"])
    by_path = {row["path"]: data for row, data in zip(artifacts, blobs)}
    def read(path):
        return json.loads(by_path["scripts/evidence/" + path].decode("utf-8-sig"))
    reviewed = read("MS-runs/manuals/reviewed-results.json")
    for manual in seal["M"]["manuals"]:
        for arm in ("with", "without"):
            rows = [r for r in reviewed if r["manual"] == manual and r["arm"] == arm]
            assert len(rows) == 3 and all(r["transportPassed"] and r["model"] == "gpt-6-luna" for r in rows)
    live = read("MS-evolver-live.json")["domains"]
    assert len(live) == 6 and all(r["measurement"]["hard_gates"]["real_provider_receipt"] for r in live)
    study = read("MS-runs/study/proof.json")
    assert study["ok"] and study["cards"] == 54 and all(study["checks"].values())
    assert all(r["ok"] for r in read("MS-runs/study/validator-adverse-cases.json").values())
    assert read("MS-runs/study/http.json")["allPassed"]
    assert all(r["ok"] for r in read("MS-runs/study/feed-proof.json")["checks"])
    for row in read("MS-runs/study/runtime-map.json")["files"]:
        assert hashlib.sha256(by_path[row["path"]]).hexdigest() == row["sha256"]
    assert not read("MS-runs/cleanup.json")["listeningAfter"]
    print(json.dumps({"ok": True, "artifacts": len(artifacts), "boundary": "committed blobs" if args.committed else "working files", "limitations": seal["limitations"]}))


if __name__ == "__main__":
    main()
