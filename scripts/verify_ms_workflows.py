"""Replay real captured Luna answers through registered executable CL manuals.

This is a receipt integrity and application-runner check, not a fabricated model
evaluation. The input panel and answers must come from prove_ms_manuals.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.native_tools import NativeToolRegistry
from grant_agent.workflow_manuals import STAGES, validate_workflow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=REPO / "scripts/evidence/MS-runs/manuals/panel.json")
    parser.add_argument("--results-dir", type=Path, default=REPO / "scripts/evidence/MS-runs/manuals")
    parser.add_argument("--root", type=Path, default=REPO / ".agent_control/MS-workflows")
    parser.add_argument("--receipt", type=Path, default=REPO / "scripts/evidence/MS-workflows.json")
    args = parser.parse_args()
    root = args.root.resolve()
    root.relative_to(REPO)
    root.mkdir(parents=True, exist_ok=True)
    registry = NativeToolRegistry(root)
    panel = json.loads(args.panel.read_text(encoding="utf-8"))
    tasks = panel if isinstance(panel, list) else panel["tasks"]
    validations, journeys = [], []
    for identity in STAGES:
        result = registry.call("neyvia.manual.validate", {"id": identity})
        if not result["ok"]:
            raise RuntimeError("Manual grounding failed: " + json.dumps(result))
        validations.append({"manual": identity, "ok": True})
    for task in tasks:
        reviewed = args.results_dir / task["id"] / "with-reviewed" / "result.json"
        path = reviewed if reviewed.is_file() else args.results_dir / task["id"] / "with" / "result.json"
        if not path.is_file():
            continue
        measured = json.loads(path.read_text(encoding="utf-8"))
        evidence = task["evidence"]
        descriptors = {}
        for identity, data in evidence.items():
            content = json.dumps(data, sort_keys=True, allow_nan=False).encode()
            digest = hashlib.sha256(content).hexdigest()
            receipt_path = root / "host-measurements" / (digest + ".json")
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_bytes(content)
            descriptors[identity] = {"path": str(receipt_path.relative_to(root)), "sha256": digest}
        inputs = {"report": measured["answer"], "evidence": descriptors,
                  "outcomeQuality": measured["outcomeQuality"], "tokens": measured["tokens"]}
        identity = task["manual"]
        score = validate_workflow(identity, measured["answer"], measured["outcomeQuality"], measured["tokens"], evidence)
        result = registry.call("neyvia.manual.run", {"id": identity,
            "chapter": "method" if identity == "hill-climb" else "workflow",
            "procedure": "verify-and-record", "inputs": inputs})
        status = result.get("result", {}).get("status")
        expected = "completed" if score["accepted"] else "failed"
        if status != expected:
            raise RuntimeError(f"Real manual run disagrees with checker: {task['id']} {status} != {expected}")
        journeys.append({"task": task["id"], "adherence": score["adherence"], "accepted": score["accepted"],
                         "manualRun": result["result"], "answerSha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        if descriptors:
            forged = {**inputs, "manual": identity, "evidence": {next(iter(descriptors)): {"path": next(iter(descriptors.values()))["path"], "sha256": "0" * 64}}}
            rejected = registry.call("neyvia.workflow.record", forged)
            if rejected["ok"] or "SHA256" not in rejected.get("error", ""):
                raise RuntimeError("Altered receipt was not rejected before recording")
    details = registry.call("neyvia.workflow.details", {})
    if not details["ok"] or len(details["result"]["patterns"]) != 8:
        raise RuntimeError("Attributed details catalog unreachable")
    payload = {"schema": "neyvia.MS-workflow-journeys.v1", "grounded": validations, "journeys": journeys,
               "tamperRejected": True, "detailsPatterns": 8,
               "boundary": "Real captured model reports through local native tools/manual runner; no public promotion"}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"grounded": len(validations), "realReports": len(journeys),
                      "completed": sum(j["accepted"] for j in journeys), "tamperRejected": True}))


if __name__ == "__main__":
    main()
