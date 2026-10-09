"""Seal C10d evidence, full-panel gates and honest deduplicated usage."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

REPO = Path(__file__).resolve().parents[1]
EVIDENCE = REPO / "scripts/evidence"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def checked_panel(run, name):
    directory = EVIDENCE / "C10d-runs" / run / name
    manifest, summary = load(directory / "manifest.json"), load(directory / "summary.json")
    wanted = manifest["tasks"]
    expected = 55 if name == "development" else 50
    if len(wanted) != expected or not summary["complete"] or summary["scheduledTasks"] != expected:
        raise ValueError("Full panel or judgments incomplete: " + name)
    for arm in ("neyvia", "openai"):
        actual = sorted(p.stem for p in (directory / arm).glob("*.json"))
        if actual != sorted(wanted):
            raise ValueError("Missing, duplicate or extra scheduled request: " + name + "/" + arm)
        for task in wanted:
            row = load(directory / arm / (task + ".json"))
            if any(m["model"] != "gpt-6.1-sol" for m in row.get("models", [])):
                raise ValueError("Forbidden research model")
    n, o = summary["arms"]["neyvia"], summary["arms"]["openai"]
    known = all(isinstance(m["cost"]["usd"], (int, float)) for m in (n, o))
    gates = {"accuracyAtLeastRaw": n["correct"] >= o["correct"],
             "accuracyAtLeast49": n["correct"] >= 49,
             "citationValidityBetter": n["citationValidity"]["fraction"] > o["citationValidity"]["fraction"],
             "completeCostsKnown": known,
             "costNoMoreThanRaw": known and n["cost"]["usd"] <= o["cost"]["usd"]}
    if name == "development":
        gates.update(costNoMoreThanOriginal357=known and n["cost"]["usd"] <= 3.571479)
    return {"summary": str((directory / "summary.json").relative_to(REPO)), "result": summary,
            "accuracyPassed": gates["accuracyAtLeast49"] and gates["accuracyAtLeastRaw"],
            "priority": "Accuracy >=49/50 first; cost and citation gates cannot compensate for lower accuracy",
            "gates": gates, "passed": all(gates.values()), "sourceBinding": manifest["sourceBinding"]}


def usage():
    roots = [EVIDENCE / "C10d-runs", EVIDENCE / "C10-native-c10d", EVIDENCE / "C10-native-c10d-final"]
    models = {}
    for root in roots:
        for path in root.glob("**/.neyvia/autopilot-model/*.json"):
            receipt = load(path)
            if receipt.get("model") != "gpt-6.1-sol":
                raise ValueError("Non-Sol provider receipt in C10d evidence")
            models[str(path.resolve())] = receipt
    measured = [r["tokens"] for r in models.values() if isinstance(r.get("tokens"), dict)]
    totals = {key: sum(t[key] for t in measured) for key in ("input", "cachedInput", "output", "reasoningOutput", "total")}
    rates = load(REPO / "config/scroll-study-prices.json")["gpt-6.1-sol"]
    usd = sum(((t["input"] - t["cachedInput"]) * rates["input"] + t["cachedInput"] * rates["cached"] + t["output"] * rates["output"]) / 1e6 for t in measured)
    thread, main = os.environ.get("CODEX_THREAD_ID"), None
    if thread:
        for path in Path("C:/Users/user/.codex/sessions/2026/10/05").glob("*" + thread + "*.jsonl"):
            for line in path.open(encoding="utf-8"):
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                payload = event.get("payload", {})
                if event.get("type") == "event_msg" and payload.get("type") == "token_count":
                    main = payload.get("info", {}).get("total_token_usage")
    return {"providerCallsWithReceipts": len(models), "providerCallsWithUsage": len(measured),
            "providerCallsMissingUsage": len(models) - len(measured), "observedProviderTokens": totals,
            "observedProviderApiEquivalentUsd": usd, "mainSession": thread, "mainUsageAtCheckpoint": main,
            "combinedObservedTokenLowerBound": totals["total"] + (main["total_tokens"] if main else 0),
            "complete": False, "boundary": "Stopped processes may have unreported usage; supplied Claude arm has no provider usage. Main usage ends at the latest token-count event before this checkpoint. Actual billed subscription/CPU/search costs unknown."}


def archive(run, destination):
    roots = [EVIDENCE / "C10d-runs", EVIDENCE / "C10-native-c10d", EVIDENCE / "C10-native-c10d-final"]
    members = sorted({p for root in roots for p in root.rglob("*.json") if p.is_file()})
    members += [EVIDENCE / name for name in ("C10-claude-arm.jsonl", "C10d-ablation-decision.json", "C10d-harness-gaps.md", "C10c-freeze.json", "C10c-holdout.json", "C10-tasks.json")]
    commits = subprocess.check_output(["git", "rev-list", "--reverse", "bdd2983d1..HEAD"], cwd=REPO, text=True).splitlines()
    code = ["scripts/c10d_study.py", "src/grant_agent/research_pipeline.py", "src/grant_agent/research_sol.py", "src/grant_agent/research_grounding.py", "src/grant_agent/research_quotes.py", "src/grant_agent/research_evaluator.py", "src/grant_agent/research_review_loop.py", "src/grant_agent/research_state.py", "scripts/score_c10_research.py", "scripts/run_c10_research.py", "src/grant_agent/autopilot_model.py"]
    if destination.exists():
        raise ValueError("Evidence archive exists; use a new run name rather than overwrite")
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as out:
        for path in members:
            if path.exists():
                out.write(path, str(path.relative_to(REPO)).replace("\\", "/"))
        for commit in commits:
            for path in code:
                present = subprocess.run(["git", "cat-file", "-e", commit + ":" + path], cwd=REPO, capture_output=True)
                if present.returncode:
                    continue
                raw = subprocess.check_output(["git", "show", commit + ":" + path], cwd=REPO)
                out.writestr("source-snapshots/" + commit + "/" + path, raw)
        for path in (REPO / "scripts/finalize_c10d.py", REPO / "config/scroll-study-prices.json"):
            out.write(path, str(path.relative_to(REPO)).replace("\\", "/"))
    with zipfile.ZipFile(destination) as check:
        if check.testzip() is not None:
            raise ValueError("Archive CRC failed")
    return {"path": str(destination.relative_to(REPO)), "bytes": destination.stat().st_size,
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "crcPassed": True, "sourceCommits": commits}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    panels = {name: checked_panel(args.run, name) for name in ("development", "holdout")}
    if panels["development"]["sourceBinding"] != panels["holdout"]["sourceBinding"]:
        raise ValueError("Candidate source changed between complete panels")
    native = load(EVIDENCE / "C10-native-c10d-final.json")
    measured = usage()
    result = {"schema": "neyvia.C10d.v1", "updatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
              "run": args.run, "panels": panels, "ablation": load(EVIDENCE / "C10d-ablation-decision.json"),
              "claude": load(EVIDENCE / "C10d-runs/claude/development/summary.json"), "native": native,
              "measuredUsage": measured, "competitiveGoalMet": all(p["passed"] for p in panels.values()),
              "holdoutBoundary": "Existing frozen rows 50-99, repeated validation; no holdout tuning in C10d. Not a new untouched holdout.",
              "costBoundary": "Observed model CLI usage at fixed repository API-price snapshot; judge and coordinator overhead are separate from answer-arm costs; no invoice/CPU/search-cost claim."}
    result["archive"] = archive(args.run, EVIDENCE / ("C10d-raw-" + args.run + ".zip"))
    save(EVIDENCE / "C10d.json", result)
    ledger = {"track": "C10d", "stage": "complete_panels", "artifact": "scripts/evidence/C10d.json", "competitiveGoalMet": result["competitiveGoalMet"],
              "panels": {n: {"gates": p["gates"], "arms": p["result"]["arms"]} for n, p in panels.items()}, "measuredUsage": measured, "archive": result["archive"]}
    with (REPO / "docs/research/results.jsonl").open("a", encoding="utf-8") as out:
        out.write(json.dumps(ledger, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps({"sealed": True, "competitiveGoalMet": result["competitiveGoalMet"], "panels": {n:p["gates"] for n,p in panels.items()}, "usage": measured}))


if __name__ == "__main__":
    main()
