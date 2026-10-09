"""Independently verify campaign artifacts, source binding and paired repairs."""
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.proof_contracts import source_digest


def main():
    receipt = json.loads((REPO / "scripts/evidence/C7.json").read_text(encoding="utf-8"))
    if not receipt["ok"] or not receipt["sourceStable"] or receipt["complete"]:
        raise ValueError("Campaign must pass and retain its explicit semantic frontier")
    for path, expected in receipt["sourceBindings"].items():
        if source_digest(REPO / path) != expected:
            raise ValueError("Source differs from campaign: " + path)
    for name, expected in receipt["baselines"].items():
        if hashlib.sha256((REPO / "scripts/evidence" / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Baseline artifact changed: " + name)
    host_path = REPO / receipt["hostProof"]["path"]
    if hashlib.sha256(host_path.read_bytes()).hexdigest() != receipt["hostProof"]["sha256"]:
        raise ValueError("Host proof bytes changed")
    host = json.loads(host_path.read_text(encoding="utf-8"))
    if not host["ok"] or not all(row["passed"] for row in host["manualChecks"]):
        raise ValueError("Actual MCP/manual journey did not pass")
    if receipt["schemaFrontier"] or receipt["postconditionFrontier"]:
        raise ValueError("Unreported schema witness frontier")
    for group in ("schemaCases", "postconditionCases", "journeys"):
        rows = receipt[group]
        if len({row["id"] for row in rows}) != len(rows) or any(row["status"] != "passed" for row in rows):
            raise ValueError("Duplicate or failed cases in " + group)
    tools = {row["tool"] for row in receipt["schemaCases"]}
    if len(tools) != receipt["inventory"]["tools"]:
        raise ValueError("Some native tool schemas were not generated")
    pairs = {(row["contract"], row["category"]) for row in receipt["semanticCoverage"]}
    if len(pairs) != receipt["inventory"]["semanticContracts"] * 8:
        raise ValueError("Contract/category generation is incomplete")
    if set(receipt["categories"]) != {row["category"] for row in receipt["journeys"]}:
        raise ValueError("A required category lacks a real local journey")
    before = json.loads((REPO / "scripts/evidence/C7-schema-before.json").read_text(encoding="utf-8"))
    after = {(row["tool"], row["payloadSha256"]): row for row in receipt["schemaCases"]}
    repaired, missing = [], []
    for row in before["failures"]:
        key = row["tool"], row["payloadSha256"]
        (repaired if key in after and after[key]["status"] == "passed" else missing).append(row["id"])
    if missing:
        raise ValueError("Baseline mismatch cases vanished instead of being repaired: " + str(missing[:10]))
    report = {"schema": "neyvia.c7-review.v1", "ok": True, "sourceCurrent": True, "artifactHashesVerified": True,
              "nativeSchemasCovered": len(tools), "baselineMismatchesRepaired": len(repaired), "missingOriginalFailures": missing,
              "postconditionCases": len(receipt["postconditionCases"]), "realJourneys": len(receipt["journeys"]),
              "allEightCategoriesExercised": True, "semanticPairsGenerated": len(pairs), "semanticCoverage": receipt["counts"]["semanticCoverage"]}
    (REPO / "scripts/evidence/C7-review.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
