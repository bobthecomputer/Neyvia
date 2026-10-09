"""Frozen, gold-isolated paired FRAMES evaluation for C10c (stdlib only)."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time
import threading
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence"
HOLDOUT = EVIDENCE / "C10c-holdout.json"
FREEZE = EVIDENCE / "C10c-freeze.json"
REPO = HERE.parent
RUNS = EVIDENCE / "C10c-runs"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def freeze():
    if HOLDOUT.exists() or FREEZE.exists():
        raise SystemExit("Holdout freeze exists; refusing overwrite")
    development = json.loads((EVIDENCE / "C10-tasks.json").read_text(encoding="utf-8"))
    metadata = development["dataset"]
    with urlopen(metadata["data_url"], timeout=60) as response:
        source = response.read(2_000_001)
    if len(source) > 2_000_000:
        raise ValueError("Pinned dataset exceeded 2 MB limit")
    if hashlib.sha256(source).hexdigest() != metadata["source_sha256"]:
        raise ValueError("Pinned source hash mismatch")
    rows = list(csv.DictReader(io.StringIO(source.decode("utf-8-sig")), delimiter="\t"))
    common = development["questions"][0]["model_prompt"].split("\n\n", 1)[0]
    questions = []
    for index in range(50, 100):
        row = rows[index]
        questions.append({"id": f"frames-{index:03d}", "kind": "factual", "source_row": index,
                          "question": row["Prompt"], "model_prompt": common + "\n\n" + row["Prompt"],
                          "reference_answer": row["Answer"],
                          "reference_urls": [v.strip() for k, v in row.items() if k.startswith("wikipedia_link_") and v and v.strip()],
                          "reasoning_types": row.get("reasoning_types", "")})
    rubric = development["rubric"]
    frozen_at = dt.datetime.now(dt.timezone.utc).isoformat()
    panel = {"schema_version": 1, "benchmark": "FRAMES", "dataset": {
        **metadata, "selection": "Untouched zero-based TSV rows 50 through 99 inclusive, in original order, frozen before C10c tuning",
        "selection_sha256": digest(questions)}, "prompt_boundary": development["prompt_boundary"],
        "questions": questions, "open_briefs": [], "rubric": rubric, "rubric_sha256": digest(rubric),
        "frozen_at": frozen_at, "tuning_allowed": False}
    panel["panel_sha256"] = digest(panel)
    write_json(HOLDOUT, panel)
    receipt = {"schema_version": 1, "frozen_at": frozen_at, "frozen_before_c10c_tuning": True,
               "source_sha256": hashlib.sha256(source).hexdigest(), "download_bytes": len(source),
               "source_revision": metadata["revision"], "rows": [50, 99], "denominator": 50,
               "holdout_file": "scripts/evidence/C10c-holdout.json", "holdout_sha256": hashlib.sha256(HOLDOUT.read_bytes()).hexdigest(),
               "panel_sha256": panel["panel_sha256"], "rubric_sha256": panel["rubric_sha256"],
               "development_sha256": hashlib.sha256((EVIDENCE / "C10-tasks.json").read_bytes()).hexdigest(),
               "gold_boundary": "Only model_prompt is passed to research arms; no holdout questions or gold are printed to lead or tuning models. Evaluation gold reaches only the arm-blind judge after final answers exist.",
               "evaluation_protocol": "Run every scheduled row in both arms; preserve errors as incorrect. No gold, reference URLs, or alternate-arm answers in research context. Same frozen semantic accuracy and claim-entailment citation rubric for both panels. Separate evaluation costs from research costs. No holdout tuning after outcome inspection."}
    write_json(FREEZE, receipt)
    print(json.dumps({"freeze": str(FREEZE), "holdout_sha256": receipt["holdout_sha256"], "panel_sha256": panel["panel_sha256"], "rows": [50, 99], "denominator": 50, "frozen_at": frozen_at}))


def load_panel(name):
    frozen = json.loads(FREEZE.read_text(encoding="utf-8"))
    if hashlib.sha256(HOLDOUT.read_bytes()).hexdigest() != frozen["holdout_sha256"]:
        raise ValueError("Holdout freeze file hash mismatch")
    if hashlib.sha256((EVIDENCE / "C10-tasks.json").read_bytes()).hexdigest() != frozen["development_sha256"]:
        raise ValueError("Development panel changed since holdout freeze")
    path = HOLDOUT if name == "holdout" else EVIDENCE / "C10-tasks.json"
    panel = json.loads(path.read_text(encoding="utf-8"))
    without_hash = dict(panel)
    expected = without_hash.pop("panel_sha256")
    if digest(without_hash) != expected or digest(panel["rubric"]) != panel["rubric_sha256"]:
        raise ValueError("Panel or rubric canonical hash mismatch")
    if len(panel["questions"]) != 50:
        raise ValueError("Each factual panel must contain exactly 50 scheduled rows")
    # C10c compares factual panels; original five open briefs retain their original evidence.
    panel["open_briefs"] = []
    return panel, path


def sources():
    paths = [Path(__file__), HERE / "run_c10_research.py", HERE / "score_c10_research.py"]
    paths += list((REPO / "src/grant_agent").glob("research*.py"))
    paths += [REPO / "src/grant_agent" / name for name in (
        "autopilot_model.py", "browser_obscura.py", "neyvia_browser.py", "public_web_search.py",
        "laya_service.py", "efficiency_cascade.py", "native_tools.py")]
    paths += [REPO / "config/scroll-study-prices.json"]
    return {str(p.relative_to(REPO)).replace("\\", "/"): hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for p in sorted(set(paths))}


def runtime_environment(args):
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE="0", FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_COORDINATOR_AUTOSTART="0",
                      NEYVIA_BROWSER_PROOF_PORTS=",".join(str(p) for p in range(48771, 48780)),
                      NEYVIA_OBSCURA_EXE=str(REPO / ".agent_control/T20/obscura-v0.2.3/bin/obscura.exe"),
                      NEYVIA_LAYA_URL=f"http://127.0.0.1:{args.laya_port}", PYTHONDONTWRITEBYTECODE="1")


def scheduled(panel, ids):
    tasks = panel["questions"]
    if ids:
        wanted = set(ids.split(","))
        tasks = [t for t in tasks if t["id"] in wanted]
        if len(tasks) != len(wanted):
            raise ValueError("Unknown frozen task ID")
    return tasks


def run(args):
    import run_c10_research as launcher
    panel, panel_path = load_panel(args.panel)
    tasks = scheduled(panel, args.ids)
    directory = RUNS / args.run / args.panel
    runtime_environment(args)
    binding = sources()
    lock = directory / "source-freeze.json"
    if args.panel == "holdout":
        if args.ids:
            raise ValueError("Holdout always schedules all 50 rows; no selective tuning runs")
        if lock.exists():
            previous = json.loads(lock.read_text(encoding="utf-8"))
            if previous["sourceBinding"] != binding:
                raise ValueError("Code changed after first holdout request; frozen holdout cannot be resumed on tuned code")
        else:
            write_json(lock, {"frozen_at": dt.datetime.now(dt.timezone.utc).isoformat(), "sourceBinding": binding,
                              "holdoutPanelSha256": panel["panel_sha256"], "protocol": "Immutable code before any holdout outcome; retries on this exact source only"})
    arms = ["neyvia", "openai"] if args.arm == "both" else [args.arm]
    manifest_path = directory / "manifest.json"
    manifest = {"panelSha256": panel["panel_sha256"], "panelFileSha256": hashlib.sha256(panel_path.read_bytes()).hexdigest(),
                "rubricSha256": panel["rubric_sha256"], "tasks": [t["id"] for t in panel["questions"]],
                "thisInvocationTasks": [t["id"] for t in tasks], "arms": ["neyvia", "openai"], "thisInvocationArms": arms,
                "ports": [args.obscura_port, args.laya_port], "run": args.run, "panel": args.panel,
                "rounds": args.rounds, "timeout": args.timeout, "sourceBinding": binding,
                "sourceBindingEncoding": "SHA256 of source with LF newlines", "cold": True,
                "goldBoundary": "Research functions receive only id, kind and model_prompt; no reference answers/URLs or sibling answers",
                "denominator": 50, "status": "running"}
    write_json(manifest_path, manifest)
    pipeline = launcher.ResearchPipeline(directory / "runtime", obscura_port=args.obscura_port,
                                          rounds=args.rounds, timeout=args.timeout) if "neyvia" in arms else None

    def execute(task, arm):
        clean = {k: task[k] for k in ("id", "kind", "model_prompt")}
        path = directory / arm / (task["id"] + ".json")
        started = time.monotonic()
        try:
            result = launcher.run_one(clean, arm, directory, pipeline, args.timeout)
        except Exception as exc:
            result = {"status": "failed", "error": str(exc), "models": [], "arm": arm,
                      "taskId": clean["id"], "kind": clean["kind"], "elapsedMs": round((time.monotonic()-started)*1000, 3),
                      "cost": {"usd": None, "basis": "Outer failure with no observed usage receipt"}, "artifactPath": str(path)}
            write_json(path, result)
            print(json.dumps({"task": clean["id"], "arm": arm, "status": "failed", "error": str(exc)[:120]}), flush=True)
        return result

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            jobs = [pool.submit(execute, task, arm) for task in tasks for arm in arms]
            for job in as_completed(jobs):
                job.result()
        manifest["status"] = "requests-returned"
        manifest["completedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
        write_json(manifest_path, manifest)
    finally:
        if pipeline:
            pipeline.close()


def summarize(panel, directory):
    import score_c10_research as scorer
    report = scorer.summary(panel, directory)
    rows = []
    for task in panel["questions"]:
        path = directory / "scores" / (task["id"] + ".json")
        if path.exists():
            row = json.loads(path.read_text(encoding="utf-8"))
            if row.get("panelSha256") == panel["panel_sha256"] and row.get("rubricSha256") == panel["rubric_sha256"]:
                rows.append(row)
    report["complete"] = len(rows) == 50 and all(s["status"] != "judge-failed" for r in rows for s in r["scores"].values())
    report["scheduledTasks"] = 50
    report["scope"] = "50 factual FRAMES rows, cold independent research arms, all errors retained in denominator; excludes original five briefs"
    for arm in ("neyvia", "openai"):
        metrics = report["arms"][arm]
        metrics["researchReceiptsPresent"] = sum((directory / arm / (t["id"] + ".json")).exists() for t in panel["questions"])
        if metrics["researchReceiptsPresent"] != 50 or len(rows) != 50:
            metrics["cost"]["usd"] = None
            metrics["cost"]["factualUsd"] = None
            metrics["cost"]["costPerCorrect"] = None
            metrics["tokens"] = {key: None for key in metrics["tokens"]}
            report["complete"] = False
        claim_rows = [c for r in rows for c in r["scores"][arm].get("claims", [])]
        supported = sum(c["status"] == "supported" for c in claim_rows)
        metrics["citationValidity"] = {"supportedClaims": supported, "claimsJudged": len(claim_rows),
                                       "supportedClaimFraction": supported / len(claim_rows) if claim_rows else 0,
                                       "allClaimsSupportedAnswerFraction": metrics["allClaimsSupportedAnswers"] / 50,
                                       "entailmentMethod": "Arm-blind semantic judge on independently fetched excerpts; actual quote span validated separately, never quote presence as entailment"}
    write_json(directory / "summary.json", report)
    return report


def score(args):
    import score_c10_research as scorer
    panel, _ = load_panel(args.panel)
    directory = RUNS / args.run / args.panel
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE="0", FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_COORDINATOR_AUTOSTART="0", PYTHONDONTWRITEBYTECODE="1")
    tasks = scheduled(panel, args.ids)
    def ready_score(task):
        started = time.monotonic()
        while args.wait_for_requests and not all((directory / arm / (task["id"] + ".json")).exists() for arm in ("neyvia", "openai")):
            if time.monotonic() - started > 10800:
                raise TimeoutError("Scheduled paired research receipts did not return within three hours")
            time.sleep(1)
        return scorer.score_task(task, panel, directory, args.resume)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(ready_score, task) for task in tasks]
        for job in as_completed(jobs):
            job.result()
    report = summarize(panel, directory)
    print(json.dumps({"summary": str(directory / "summary.json"), "scoredTasks": report["scoredTasks"], "complete": report["complete"]}))


def report(args):
    panels = {}
    for name in ("development", "holdout"):
        panel, _ = load_panel(name)
        directory = RUNS / args.run / name
        panels[name] = summarize(panel, directory)
    complete = all(p["complete"] for p in panels.values())
    wins = {}
    for name, value in panels.items():
        n, o = value["arms"]["neyvia"], value["arms"]["openai"]
        costs = [a["cost"]["usd"] for a in (n, o)]
        wins[name] = bool(value["complete"] and n["correct"] > o["correct"] and all(isinstance(c, (int, float)) for c in costs) and costs[0] < costs[1])
    result = {"schema_version": 1, "run": args.run, "panels": panels, "complete": complete,
              "beatsOpenAIForLessOnBothPanels": complete and all(wins.values()), "panelWins": wins,
              "costBoundary": "Observed CLI token usage at repository list-price equivalent; subscription billed cost unavailable. CPU LAYA/search infrastructure and evaluation costs separate.",
              "freezeReceipt": "scripts/evidence/C10c-freeze.json", "noGeneralSuperiorityClaim": "Only these fixed panels establish observed accuracy and costs"}
    write_json(RUNS / args.run / "comparison.json", result)
    print(json.dumps({"comparison": str(RUNS / args.run / "comparison.json"), "complete": complete, "panelWins": wins}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze")
    sub.add_parser("validate-freeze")
    for name in ("run", "score", "report"):
        child = sub.add_parser(name)
        child.add_argument("--run", required=True)
        if name != "report":
            child.add_argument("--panel", choices=["development", "holdout"], required=True)
            child.add_argument("--workers", type=int, default=4)
            child.add_argument("--ids", help="Development-only selective work; holdout runner always schedules all 50")
        if name == "run":
            child.add_argument("--arm", choices=["neyvia", "openai", "both"], default="both")
            child.add_argument("--obscura-port", type=int, required=True)
            child.add_argument("--laya-port", type=int, required=True)
            child.add_argument("--rounds", type=int, default=2)
            child.add_argument("--timeout", type=float, default=600)
        if name == "score":
            child.add_argument("--resume", action="store_true")
            child.add_argument("--wait-for-requests", action="store_true", help="Score a row only after both real arms returned")
    args = parser.parse_args()
    if args.command == "freeze":
        freeze()
        return
    if args.command == "validate-freeze":
        for name in ("development", "holdout"):
            load_panel(name)
        print(json.dumps({"validated": True, "denominators": [50, 50], "goldPrinted": False}))
        return
    if not args.run.replace("-", "").replace("_", "").isalnum():
        parser.error("Simple run ID required")
    if getattr(args, "workers", 1) not in range(1, 5):
        parser.error("1..4 workers required")
    if args.command == "run":
        if args.obscura_port not in range(48771, 48780) or args.laya_port not in range(48771, 48780):
            parser.error("Explicit assigned ports 48771-48779 only")
        if not 1 <= args.rounds <= 5 or not 0 < args.timeout <= 600:
            parser.error("1..5 rounds and timeout <=600 seconds required")
    {"run": run, "score": score, "report": report}[args.command](args)


if __name__ == "__main__":
    main()
