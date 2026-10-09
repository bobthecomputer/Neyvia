"""Resume real frozen-panel research arms; results remain separate from prompts."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.autopilot_model import decide
from grant_agent.research_pipeline import ANSWER, ResearchPipeline
from grant_agent.transition_memory import atomic_json


def price(models):
    rates = json.loads((REPO / "config/scroll-study-prices.json").read_text())
    total = 0.0
    for model in models:
        tokens, rate = model.get("tokens"), rates.get(model.get("model"))
        if not tokens or not rate:
            return {"usd": None, "basis": "Missing actual usage or rate"}
        total += ((tokens["input"] - tokens["cachedInput"]) * rate["input"] +
                  tokens["cachedInput"] * rate["cached"] + tokens["output"] * rate["output"]) / 1e6
    return {"usd": round(total, 8), "basis": "Observed CLI tokens at repository API list-price equivalent; not billed subscription cost",
            "provenance": rates["_provenance"]}


def run_one(task, arm, directory, pipeline, timeout, resume_directory=None):
    path = directory / arm / (task["id"] + ".json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    started = time.monotonic()
    if arm == "neyvia":
        prior = resume_directory / "neyvia" / (task["id"] + ".json") if resume_directory else None
        receipt = pipeline.run(task["model_prompt"], request_id=task["id"], resume_receipt=prior)
    else:
        receipt = {"status": "running", "models": []}
        try:
            result = decide(task["model_prompt"] + "\nFor every citation include a short exact quote and the specific claim it supports. "
                            "Do real web searches before answering. Search intermediate factual clues using short keywords, "
                            "not the verbatim benchmark question. Exclude benchmark answers and answer mirrors, including "
                            "artificialanalysis.ai/microevals. Return JSON.", ANSWER, directory / arm,
                            model="gpt-6.1-sol", timeout=timeout, web_search=True)
            receipt.update(status="completed", answer=result["answer"], tokens=result["tokens"])
            receipt["models"].append(result)
            emitted = Path(result["receiptPath"]).read_text(encoding="utf-8").casefold()
            cited = json.dumps(result["answer"], ensure_ascii=False).casefold()
            if any(host in emitted or host in cited for host in ("artificialanalysis.ai/microevals", "datasets/google/frames-benchmark")):
                raise ValueError("Comparator exposed to a benchmark answer mirror; attempt excluded")
        except Exception as exc:
            source = getattr(exc, "receipt_path", "")
            actual = json.loads(Path(source).read_text(encoding="utf-8")) if source and Path(source).exists() else {}
            receipt.update(status="failed", error=str(exc), failureReceipt=source, tokens=actual.get("tokens"))
            if source:
                receipt["models"].append({"model": "gpt-6.1-sol", "tokens": actual.get("tokens"), "receiptPath": source})
    receipt.update(arm=arm, taskId=task["id"], kind=task["kind"], elapsedMs=round((time.monotonic() - started) * 1000, 3),
                   cost=price(receipt["models"]), artifactPath=str(path))
    atomic_json(path, receipt)
    print(json.dumps({"task": task["id"], "arm": arm, "status": receipt["status"], "ms": receipt["elapsedMs"],
                      "cost": receipt["cost"]["usd"], "error": receipt.get("error", "")[:160]}), flush=True)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=["neyvia", "openai", "both"], default="both")
    parser.add_argument("--obscura-port", required=True, type=int)
    parser.add_argument("--laya-port", required=True, type=int)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=600, help="Per-request seconds, including retrieval/retries; override for slow public sites")
    parser.add_argument("--rounds", type=int, default=2, help="Bounded local retrieval before live Sol escalation; 1..5")
    parser.add_argument("--limit", type=int, default=55)
    parser.add_argument("--ids", help="Comma-separated task IDs; frozen panel unchanged")
    parser.add_argument("--run", default="baseline", help="Distinct attempt ID preserves original runs")
    parser.add_argument("--resume-sources-from", help="Reuse actual same-question Obscura receipts; report incremental repair cost, not cold performance")
    args = parser.parse_args()
    if args.obscura_port not in range(48771, 48780) or args.laya_port not in range(48771, 48780):
        parser.error("Explicit assigned ports48771-48779 only")
    if not 1 <= args.workers <= 4 or not 1 <= args.rounds <= 5 or not 0 < args.timeout <= 600:
        parser.error("1..4 workers (four isolated Obscura profiles),1..5 retrieval rounds,timeout<=600 seconds")
    if not args.run.replace("-", "").replace("_", "").isalnum():
        parser.error("Run identifier must be a simple name")
    if args.resume_sources_from and (not args.resume_sources_from.replace("-", "").replace("_", "").isalnum() or args.resume_sources_from == args.run):
        parser.error("Distinct simple source run identifier required")
    resume_directory = REPO / "scripts/evidence/C10-runs" / args.resume_sources_from if args.resume_sources_from else None
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE="0", FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_COORDINATOR_AUTOSTART="0",
                      NEYVIA_BROWSER_PROOF_PORTS=",".join(str(p) for p in range(48771, 48780)),
                      NEYVIA_OBSCURA_EXE=str(REPO / ".agent_control/T20/obscura-v0.2.3/bin/obscura.exe"),
                      NEYVIA_LAYA_URL=f"http://127.0.0.1:{args.laya_port}", PYTHONDONTWRITEBYTECODE="1")
    panel_path = REPO / "scripts/evidence/C10-tasks.json"
    panel = json.loads(panel_path.read_text(encoding="utf-8"))
    tasks = [*panel["questions"], *panel["open_briefs"]][:args.limit]
    if args.ids:
        wanted = set(args.ids.split(","))
        tasks = [t for t in tasks if t["id"] in wanted]
        if len(tasks) != len(wanted):
            parser.error("Unknown frozen-panel task ID")
    directory = REPO / "scripts/evidence/C10-runs" / args.run
    code_binding = {str(path.relative_to(REPO)).replace("\\", "/"): hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                    for path in [Path(__file__), REPO / "src/grant_agent/autopilot_model.py", REPO / "src/grant_agent/research_pipeline.py",
                                 REPO / "src/grant_agent/browser_obscura.py", REPO / "scripts/score_c10_research.py"]}
    arms = ["neyvia", "openai"] if args.arm == "both" else [args.arm]
    pipeline = ResearchPipeline(directory / "runtime", obscura_port=args.obscura_port,
                                rounds=args.rounds, timeout=args.timeout) if "neyvia" in arms else None
    try:
        jobs = [(task, arm) for task in tasks for arm in arms]
        skipped = [f"{arm}/{task['id']}" for task, arm in jobs if (directory / arm / (task['id'] + ".json")).exists()]
        receipts = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(run_one, task, arm, directory, pipeline, args.timeout, resume_directory) for task, arm in jobs]
            for future in as_completed(futures):
                receipts.append(future.result())
        atomic_json(directory / "manifest.json", {"panelSha256": panel["panel_sha256"],
                    "panelFileSha256": hashlib.sha256(panel_path.read_bytes()).hexdigest(), "rubricSha256": panel["rubric_sha256"],
                    "tasks": [t["id"] for t in tasks], "arms": arms, "ports": [args.obscura_port, args.laya_port],
                    "run": args.run, "rounds": args.rounds, "timeout": args.timeout, "resumeSourcesFrom": args.resume_sources_from,
                    "sourceBinding": code_binding, "sourceBindingScope": "Launcher source at this invocation; existing request files are skipped and retain their individual original bindings",
                    "skippedExistingRequests": skipped,
                    "receiptSourceBindings": {r["taskId"]: r.get("sourceBinding") for r in receipts if r["arm"] == "neyvia"},
                    "sourceBindingEncoding": "SHA256 of UTF-8 source with LF newlines"})
    finally:
        if pipeline:
            pipeline.close()


if __name__ == "__main__":
    main()
