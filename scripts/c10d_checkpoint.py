"""Summarize a completed development experiment and append its measured ledger row."""
from __future__ import annotations
import argparse
import datetime as dt
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--decision", required=True)
    args = parser.parse_args()
    directory = REPO / "scripts/evidence/C10d-runs" / args.run / "development"
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if not summary["complete"]:
        raise ValueError("An incomplete experiment cannot justify retention")
    measured = {arm: {k: v[k] for k in ("correct", "citationValidity", "tokens", "cost")}
                for arm, v in summary["arms"].items()}
    row = {"track": "C10d", "stage": "development_change", "run": args.run,
           "updatedAt": dt.datetime.now(dt.timezone.utc).isoformat(), "change": args.change,
           "tasks": manifest["tasks"], "sourceBinding": manifest["sourceBinding"],
           "panelSha256": manifest["panelSha256"], "rubricSha256": manifest["rubricSha256"],
           "arms": measured, "decision": args.decision,
           "acceptance": "Accuracy first: full factual panel >=49/50 before citation/cost success; development subsets do not prove that gate"}
    target = REPO / "scripts/evidence" / ("C10d-" + args.run + "-decision.json")
    target.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    ledger = REPO / "docs/research/results.jsonl"
    previous = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not any(r.get("stage") == row["stage"] and r.get("run") == args.run for r in previous):
        with ledger.open("a", encoding="utf-8") as out:
            out.write(json.dumps(row, separators=(",", ":")) + "\n")
    print(json.dumps({"run": args.run, "questions": len(manifest["tasks"]), "arms": measured, "decision": args.decision}))


if __name__ == "__main__":
    main()
