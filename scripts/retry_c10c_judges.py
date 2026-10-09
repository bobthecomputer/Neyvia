"""Retry only failed independent judges, preserving their original receipts."""
import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from c10c_quality import RUNS, load_panel, summarize
from score_c10_research import score_task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--panel", required=True, choices=("development", "holdout"))
    args = parser.parse_args()
    if not args.run.replace("-", "").replace("_", "").isalnum():
        parser.error("Simple local run ID required")
    panel, _ = load_panel(args.panel)
    directory = RUNS / args.run / args.panel
    pending = []
    history = directory / "judge-history"
    for task in panel["questions"]:
        path = directory / "scores" / (task["id"] + ".json")
        if not path.exists():
            continue
        raw = path.read_bytes()
        saved = json.loads(raw)
        if any(score["status"] == "judge-failed" for score in saved["scores"].values()):
            history.mkdir(exist_ok=True)
            archived = history / (task["id"] + "-" + hashlib.sha256(raw).hexdigest()[:16] + ".json")
            archived.write_bytes(raw)
            if archived.read_bytes() != raw:
                raise ValueError("Failed judge receipt preservation mismatch")
            pending.append(task)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda task: score_task(task, panel, directory, False), pending))
    report = summarize(panel, directory)
    print(json.dumps({"panel": args.panel, "retriedJudges": len(pending), "complete": report["complete"],
        "boundary": "Uniform retry of all failed judge receipts only; same research answers, blinded rubric and gold; originals preserved"}))


if __name__ == "__main__":
    main()
