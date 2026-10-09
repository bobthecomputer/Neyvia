"""Actual model calls prove policy thresholds do not change predictions."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    if not 48721 <= args.port <= 48729:
        parser.error("Use an assigned explicit port")
    evidence = Path(__file__).resolve().parent/"evidence"
    result = json.loads((evidence/"C2b-laya-advisory.json").read_text(encoding="utf-8"))
    case = next(row for row in result["rows"] if row["split"] == "calibration" and row.get("advisory_field") == "readyState")
    samples = []
    for threshold in (None, .5, result["calibration"]["advisory_threshold"], .999999):
        question = copy.deepcopy(case["question"])
        if threshold is None:
            question.pop("thresholds", None)
        else:
            question["thresholds"] = {"answer": threshold}
        request = urllib.request.Request(f"http://127.0.0.1:{args.port}/v1/decide",
            json.dumps({"state": case["state"], "questions": {"decision": question}, "memory": False, "base_cache": False}).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            value = json.load(response)
        answer = value["answers"]["decision"]
        samples.append({"threshold": threshold, "p": answer["p"], "answer": answer["answer"], "policy": answer["policy"],
                        "identity": value["identity"], "runtime": value["runtime"], "decision_id": value["decision_id"]})
    passed = all((sample["p"], sample["answer"], sample["identity"]) == (samples[0]["p"], samples[0]["answer"], samples[0]["identity"]) for sample in samples)
    receipt = {"schema": "neyvia.C2b-threshold-independence@1", "passed": passed,
               "source_case": case["id"], "samples": samples,
               "boundary": "Four actual uncached CPU calls; threshold changes only returned policy, not input features, p or model answer"}
    (evidence/"C2b-threshold-independence.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps({"passed": passed, "policies": [sample["policy"] for sample in samples]}))
    if not passed:
        raise RuntimeError("Threshold affected model prediction; deployment must fail closed")


if __name__ == "__main__":
    main()
