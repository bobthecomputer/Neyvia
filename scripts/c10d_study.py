"""Independent Sol ablations and frozen C10 panels, using the existing blind judge."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.research_pipeline import ResearchPipeline
from grant_agent.transition_memory import atomic_json
import c10c_quality as frozen
import run_c10_research as launcher
import score_c10_research as judge

RUNS = REPO / "scripts/evidence/C10d-runs"


def panel_for(name, limit=None):
    panel, path = frozen.load_panel(name)
    if name == "development":
        panel["open_briefs"] = json.loads(path.read_text(encoding="utf-8"))["open_briefs"]
    tasks = [*panel["questions"], *panel["open_briefs"]]
    return panel, tasks[:limit] if limit else tasks


def binding():
    paths = [Path(__file__), REPO / "scripts/score_c10_research.py", REPO / "scripts/run_c10_research.py"]
    paths += [REPO / "src/grant_agent" / name for name in ("research_pipeline.py", "research_sol.py", "research_quotes.py", "research_grounding.py", "research_evaluator.py", "research_review_loop.py", "autopilot_model.py", "research_sources.py", "browser_obscura.py", "public_web_search.py")]
    return {str(p.relative_to(REPO)).replace("\\", "/"): hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in paths}


def run(args, panel, tasks, directory):
    frozen.runtime_environment(args)
    code = binding()
    lock = directory / "source-freeze.json"
    if lock.exists() and json.loads(lock.read_text(encoding="utf-8"))["sourceBinding"] != code:
        raise ValueError("Source changed for existing run; use a distinct run ID")
    if args.panel == "holdout" and args.limit:
        raise ValueError("Holdout always schedules all questions")
    atomic_json(lock, {"sourceBinding": code, "panelSha256": panel["panel_sha256"],
                       "frozenAt": dt.datetime.now(dt.timezone.utc).isoformat()})
    pipeline = ResearchPipeline(directory / "runtime", obscura_port=args.obscura_port, timeout=600)
    arms = ["openai", "retrieval", "grounded"] if args.mode == "ablation" else ["openai", "neyvia"]
    atomic_json(directory / "manifest.json", {"panelSha256": panel["panel_sha256"], "rubricSha256": panel["rubric_sha256"],
        "tasks": [t["id"] for t in tasks], "arms": arms, "mode": args.mode, "sourceBinding": code,
        "baseline": "C10b 4bf9fcff source capture/context, no C10c hop pipeline",
        "pairing": "Independent live Sol search in every arm; no other-arm answer, gold or reference URLs reach research." if not args.development_seed else
                   "Controlled replay of own Neyvia answer/sources; immutable raw comparator reused only for judging, never supplied to research",
        "developmentSeed": args.development_seed})

    def execute(task):
        seed_dir = RUNS / args.development_seed / "development" if args.development_seed else None
        if seed_dir:
            raw = json.loads((seed_dir / "openai" / (task["id"] + ".json")).read_text(encoding="utf-8"))
            atomic_json(directory / "openai" / (task["id"] + ".json"), {**raw, "reusedComparator": str(seed_dir)})
        else:
            launcher.run_one(task, "openai", directory, None, 600)
        for arm in arms[1:]:
            path = directory / arm / (task["id"] + ".json")
            if path.exists():
                continue
            mode = arm if args.mode == "ablation" else args.mode
            started = time.monotonic()
            if seed_dir:
                from grant_agent.research_sol import run as sol_run
                seed = json.loads((seed_dir / "neyvia" / (task["id"] + ".json")).read_text(encoding="utf-8"))
                receipt = sol_run(pipeline, task["model_prompt"], arm + "-" + task["id"], mode=mode, development_seed=seed)
            else:
                receipt = pipeline.run(task["model_prompt"], request_id=arm + "-" + task["id"], mode=mode)
            # Every independent model call is charged to its own arm.
            receipt.update(arm=arm, taskId=task["id"], kind=task["kind"], artifactPath=str(path),
                           cost=launcher.price(receipt["models"]))
            atomic_json(path, receipt)
            print(json.dumps({"task": task["id"], "arm": arm, "status": receipt["status"],
                              "cost": receipt["cost"]["usd"], "error": receipt.get("error", "")}), flush=True)
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(execute, tasks))
    finally:
        pipeline.close()


def score(args, panel, tasks, directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    judge.ARMS = tuple(manifest["arms"])
    def ready_score(task):
        started = time.monotonic()
        while args.wait_for_requests and not all((directory / arm / (task["id"] + ".json")).exists() for arm in judge.ARMS):
            if time.monotonic() - started > 10800:
                raise TimeoutError("Scheduled research receipts did not return within three hours")
            time.sleep(1)
        saved = directory / "scores" / (task["id"] + ".json")
        retry = args.retry_failed and saved.exists() and any(
            s["status"] == "judge-failed" for s in json.loads(saved.read_text(encoding="utf-8"))["scores"].values())
        return judge.score_task(task, panel, directory, not retry)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(ready_score, tasks))
    # Preserve original hashes/rubric and explicitly describe scheduled subset.
    scheduled_panel = {**panel, "questions": [t for t in tasks if t["kind"] == "factual"],
                       "open_briefs": [t for t in tasks if t["kind"] == "open"]}
    result = judge.summary(scheduled_panel, directory)
    rows = [json.loads((directory / "scores" / (t["id"] + ".json")).read_text(encoding="utf-8")) for t in tasks]
    result["complete"] = len(rows) == len(tasks) and all(s["status"] != "judge-failed" for r in rows for s in r["scores"].values())
    result["scheduledTasks"] = len(tasks)
    for arm, metrics in result["arms"].items():
        claims = [c for row in rows if row["kind"] == "factual" for c in row["scores"][arm]["claims"]]
        metrics["citationValidity"] = {"supported": sum(c["status"] == "supported" for c in claims), "judged": len(claims),
            "fraction": sum(c["status"] == "supported" for c in claims) / len(claims) if claims else 0}
    atomic_json(directory / "summary.json", result)
    print(json.dumps({"complete": result["complete"], "arms": {a: {k: m[k] for k in ("correct", "citationValidity", "cost", "tokens")} for a, m in result["arms"].items()}}), flush=True)


def claude(panel, directory):
    source = REPO / "scripts/evidence/C10-claude-arm.jsonl"
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    metadata = [r for r in rows if r.get("id") == "summary"]
    rows = [r for r in rows if "id" in r and r["id"] != "summary"]
    tasks = [*panel["questions"], *panel["open_briefs"]]
    if len(rows) != len(tasks) or {r["id"] for r in rows} != {t["id"] for t in tasks}:
        raise ValueError("Claude arm must contain every frozen ID exactly once")
    for row in rows:
        task = next(t for t in tasks if t["id"] == row["id"])
        seconds = (dt.datetime.fromisoformat(row["end"].replace("Z", "+00:00")) - dt.datetime.fromisoformat(row["start"].replace("Z", "+00:00"))).total_seconds()
        atomic_json(directory / "claude" / (row["id"] + ".json"), {"status": "completed" if row["status"] == "answered" else "failed",
            "taskId": row["id"], "kind": task["kind"], "arm": "claude", "answer": {"answer": row["answer"],
                "explanation": row.get("reasoning", ""), "citations": row.get("citations", [])},
            "models": [], "elapsedMs": seconds * 1000, "sourceFile": str(source), "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "usageBoundary": "Supplied Claude artifact lacks provider token receipts; complete cost and tokens unknown"})
    atomic_json(directory / "manifest.json", {"arms": ["claude"], "tasks": [t["id"] for t in tasks], "panelSha256": panel["panel_sha256"], "rubricSha256": panel["rubric_sha256"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "score", "claude"])
    parser.add_argument("--run", required=True)
    parser.add_argument("--panel", choices=["development", "holdout"], default="development")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ids", help="Comma-separated development IDs; never permitted for holdout")
    parser.add_argument("--development-seed", help="Own Neyvia seed run for controlled component ablations only")
    parser.add_argument("--mode", choices=["ablation", "retrieval", "grounded"], default="ablation")
    parser.add_argument("--obscura-port", type=int, default=48773)
    parser.add_argument("--laya-port", type=int, default=48775)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--wait-for-requests", action="store_true")
    parser.add_argument("--retry-failed", action="store_true", help="Retry failed judge executions with identical rubric and retained history")
    args = parser.parse_args()
    if not args.run.replace("-", "").replace("_", "").isalnum() or not 1 <= args.workers <= 4:
        parser.error("Simple run ID and 1..4 workers required")
    panel, tasks = panel_for(args.panel, args.limit)
    if args.development_seed and (args.panel != "development" or not args.ids or args.mode != "grounded" or not args.development_seed.replace("-", "").isalnum()):
        parser.error("Own-seed replay requires grounded mode, explicit development IDs and a simple seed run")
    if args.ids:
        wanted = args.ids.split(",")
        if args.panel != "development" or len(set(wanted)) != len(wanted) or not set(wanted) <= {t["id"] for t in tasks}:
            parser.error("Unique existing development IDs required")
        tasks = [t for t in tasks if t["id"] in wanted]
    directory = RUNS / args.run / args.panel
    if args.command == "claude":
        claude(panel, directory)
    elif args.command == "run":
        run(args, panel, tasks, directory)
    else:
        score(args, panel, tasks, directory)


if __name__ == "__main__":
    main()
