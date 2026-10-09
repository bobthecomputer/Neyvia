"""Recycle only the two temporary build folders created by this C9c task."""
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.neyvia_files_tools import recycle
from grant_agent.durability import atomic_write_json

def main():
    targets = [REPO / ".agent_control/C9c-build", REPO / "scripts/evidence/C9c-voting-builds"]
    records = []
    for path in targets:
        resolved = path.resolve()
        if resolved != path.absolute() or not resolved.is_relative_to(REPO):
            raise ValueError("Recycle target must remain at its explicitly named task path")
        record = {"path": str(path.relative_to(REPO)), "existsBefore": path.exists(), "method": "Neyvia files.recycle / Windows Recycle Bin"}
        binary = path / "debug/browser-proof.exe"
        if binary.is_file():
            record["nativeBinarySha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
        if path.exists(): recycle(path)
        record["existsAfter"] = path.exists()
        if record["existsAfter"]: raise ValueError("Recycle did not complete")
        records.append(record)
    receipt = {"schema": "neyvia.C9c-cleanup.v1", "records": records, "passed": True}
    atomic_write_json(REPO / "scripts/evidence/C9c-cleanup.json", receipt)
    print(json.dumps(receipt))

if __name__ == "__main__": main()
