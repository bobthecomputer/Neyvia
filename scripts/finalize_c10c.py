"""Seal complete C10c comparisons and their actual local raw receipts."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

from c10c_quality import EVIDENCE, REPO, RUNS, load_panel, summarize, sources


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--native-proof", required=True)
    args = parser.parse_args()
    if not args.run.replace("-", "").replace("_", "").isalnum():
        parser.error("Simple local run name required")
    panels = {}
    for name in ("development", "holdout"):
        panel, _ = load_panel(name)
        panels[name] = summarize(panel, RUNS / args.run / name)
    if not all(p["complete"] for p in panels.values()):
        raise ValueError("Both complete 50-row paired panels must be independently scored before sealing")
    native_path = EVIDENCE / args.native_proof
    native, f6, losses = read(native_path), read(EVIDENCE / "C10c-grounding.json"), read(EVIDENCE / "C10c-losses.json")
    engine_sha = hashlib.sha256((REPO / "src/grant_agent/research_hops.py").read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    if (not native["passed"] or native["sourceBinding"]["research_hops.py"] != engine_sha or
            not f6["passed"] or f6["groundingSourceSha256"] != engine_sha or losses["lossCount"] != 12):
        raise ValueError("Current engine needs native and adversarial grounding proof, plus all twelve classified losses")
    cache_proof = native.get("cacheReplay", {})
    cache_path = Path(cache_proof.get("path", ""))
    if (not cache_proof.get("passed") or not cache_path.is_file() or
            sha(cache_path) != cache_proof.get("sha256") or not read(cache_path).get("passed")):
        raise ValueError("Current native journey needs byte-identical production source-cache replay")
    metrics, wins = {}, {}
    for name, panel in panels.items():
        if read(RUNS / args.run / name / "manifest.json")["sourceBinding"] != sources():
            raise ValueError("Current source differs from the completed panel manifest")
        rows = [read(p) for p in (RUNS / args.run / name / "neyvia").glob("frames-*.json")]
        metrics[name] = {"questions": len(rows), "completed": sum(r["status"] == "completed" for r in rows),
            "claimGroundedCompleted": sum(r.get("claimGrounding", {}).get("accepted") is True and r["status"] == "completed" for r in rows),
            "actualSnippetLayaDecisions": sum(sum(x["judgment"].get("available", False) for x in r.get("snippetRanking", [])) for r in rows),
            "actualSnippetRankingCalls": sum(sum(bool(b.get("available") and b.get("response"))
                for b in r.get("snippetRankingBatches", [])) for r in rows),
            "unavailableSnippetRankingCalls": sum(sum(not b.get("available", False)
                for b in r.get("snippetRankingBatches", [])) for r in rows),
            "snippetPayloadViolations": [r["taskId"] for r in rows if any(
                set(b.get("payload", {}).get("state", {})) != {"goal", "hop"} or
                len(b["payload"]["state"].get("goal", "")) > 700 or
                len(b["payload"]["state"]["hop"].get("options", {})) > 4 or
                any(len(o.get("snippet", "")) > 500 or len(o.get("title", "")) > 240
                    for o in b["payload"]["state"]["hop"].get("options", {}).values())
                for b in r.get("snippetRankingBatches", []))],
            "fetchedSourceCacheHits": sum(len(r.get("sourceCacheHits", [])) for r in rows),
            "earlyGroundedStops": sum("earlyStop" in r for r in rows),
            "contextCapViolations": [r["taskId"] for r in rows if any(t > 5500 for t in r.get("contextTokens", []))],
            "actualBudgetOvershoots": [r["taskId"] for r in rows if r.get("budget", {}).get("exceeded")],
            "wholePageLayaLeaks": [r["taskId"] for r in rows if any(
                s.get("laya", {}).get("available") and (
                    "context" not in s["laya"] or
                    any(k in s["laya"]["context"] for k in ("current", "fullText", "tables", "controls")) or
                    len(s["laya"]["context"].get("passages", [])) > 2)
                for s in r.get("sources", []))],
            "engineBindingMatches": all(r.get("sourceBinding", {}) == native["sourceBinding"] for r in rows)}
        n, o = panel["arms"]["neyvia"], panel["arms"]["openai"]
        wins[name] = (n["correct"] > o["correct"] and all(isinstance(a["cost"]["usd"], (int, float)) for a in (n, o))
                      and n["cost"]["usd"] < o["cost"]["usd"])
    if any(m["contextCapViolations"] or m["wholePageLayaLeaks"] or m["snippetPayloadViolations"] or
           not m["engineBindingMatches"] for m in metrics.values()):
        raise ValueError("Context cap, passage-only LAYA or current-engine binding failed")
    archive_path = EVIDENCE / "C10c-raw.zip"
    candidates = set()
    proof_roots = list(EVIDENCE.glob("C10-native-*"))
    proof_roots = [p for p in proof_roots if p.is_dir()]
    repair_roots = [REPO / ".agent_control/C10c" / name for name in ("postfreeze", "identityrepair", "packingrepair")]
    for root in [RUNS, EVIDENCE / "C10c-grounding", *repair_roots, *proof_roots]:
        candidates.update(p for p in root.rglob("*.json") if p.is_file() and
            not any(part in {"browser", "profiles"} for part in p.relative_to(root).parts))
    candidates.update(p for root in repair_roots for p in root.rglob("*.py") if p.is_file())
    manifest = []
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(candidates):
            relative = path.relative_to(REPO).as_posix()
            archive.write(path, relative)
            manifest.append({"path": relative, "sha256": sha(path), "bytes": path.stat().st_size})
    with zipfile.ZipFile(archive_path) as archive:
        for item in manifest:
            if hashlib.sha256(archive.read(item["path"])).hexdigest() != item["sha256"]:
                raise ValueError("Raw receipt archive readback failed")
    manifest_path = EVIDENCE / "C10c-raw-manifest.json"
    manifest_path.write_text(json.dumps({"entries": manifest, "archiveSha256": sha(archive_path)}, indent=2) + "\n", encoding="utf-8")
    baseline = next(c["summary"] for c in read(EVIDENCE / "C10b.json")["completedComparisons"] if c["run"] == "final-cold")
    baseline_factual = []
    for p in (EVIDENCE / "C10-runs/final-cold/neyvia").glob("frames-*.json"):
        baseline_factual.extend(read(p).get("models", []))
    known_baseline_tokens = sum((m.get("tokens") or {}).get("total", 0) for m in baseline_factual)
    new_tokens = panels["development"]["arms"]["neyvia"]["tokens"]["total"]
    known_new_tokens = panels["development"]["arms"]["neyvia"]["observedKnownTokens"]["total"]
    previous_comparisons = []
    for path in sorted(RUNS.glob("*/comparison.json")):
        previous = read(path)
        if path.parent.name != args.run and previous.get("complete"):
            previous_comparisons.append({"run": path.parent.name, "path": str(path.relative_to(REPO)),
                "sha256": sha(path), "panels": previous["panels"]})
    loss_outcomes = []
    for loss in losses["losses"]:
        score_path = RUNS / args.run / "development/scores" / (loss["taskId"] + ".json")
        score = read(score_path)["scores"]["neyvia"]
        loss_outcomes.append({"taskId": loss["taskId"], "originalCategory": loss["primaryCategory"],
            "correctOnCurrentColdRun": score["correct"], "status": score["requestStatus"],
            "scoreReceipt": str(score_path.relative_to(REPO)), "sha256": sha(score_path)})
    receipt = {"schema": "neyvia.C10c.v1", "status": "competitive_goal_achieved" if all(wins.values()) else "mechanism_verified_competitive_goal_unmet",
        "updatedAt": dt.datetime.now(dt.timezone.utc).isoformat(), "branch": "track/c10-research", "sourceCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "c4MergeCommit": "26887b96", "holdoutFreezeCommit": "671deb70", "sourceBinding": sources(),
        "coldLossAudit": {"path": "scripts/evidence/C10c-losses.json", "sha256": sha(EVIDENCE / "C10c-losses.json"), "categories": losses["primaryCategoryCounts"], "judgeDisagreementsRemainCounted": True},
        "holdoutFreeze": {"path": "scripts/evidence/C10c-freeze.json", "sha256": sha(EVIDENCE / "C10c-freeze.json")},
        "blindAbortedAttempt": {"path": "scripts/evidence/C10c-blind-abort.json", "sha256": sha(EVIDENCE / "C10c-blind-abort.json"),
            "boundary": "The preliminary incomplete holdout attempt was stopped for defects independently proven in development receipts. Its three comparator answers were never inspected or used for tuning. All outputs remain archived. Definitive panels start afresh on repaired frozen code."},
        "nativeProof": {"path": str(native_path.relative_to(REPO)), "sha256": sha(native_path), "passed": native["passed"]},
        "sourceCacheProof": {"path": str(cache_path.relative_to(REPO)), "sha256": sha(cache_path), "passed": True},
        "F6": {"path": "scripts/evidence/C10c-grounding.json", "sha256": sha(EVIDENCE / "C10c-grounding.json"), "passed": f6["passed"]},
        "panels": panels, "mechanismMetrics": metrics, "panelWins": wins, "beatsOpenAIForLessOnBothPanels": all(wins.values()),
        "previousCompletedComparisons": previous_comparisons, "coldLossOutcomes": loss_outcomes,
        "tokenReduction": {"factualBaselineObservedKnownTokens": known_baseline_tokens, "newDevelopmentTokens": new_tokens,
            "newDevelopmentObservedKnownTokens": known_new_tokens,
            "factor": known_baseline_tokens / new_tokens if new_tokens else None,
            "observedKnownFactor": known_baseline_tokens / known_new_tokens if known_new_tokens else None,
            "boundary": "Factual rows 0-49 only. Complete new totals and factor remain null when any failed call lacks usage; observedKnownFactor compares measured lower bounds and cannot establish a complete fivefold reduction. Original 24.0M included five open briefs; new study excludes briefs."},
        "previousColdAccuracy": {arm: baseline["arms"][arm]["correct"] for arm in ("neyvia", "openai")},
        "rawEvidence": {"path": "scripts/evidence/C10c-raw.zip", "sha256": sha(archive_path), "manifest": "scripts/evidence/C10c-raw-manifest.json", "entries": len(manifest), "bytes": archive_path.stat().st_size, "readbackVerified": True},
        "costBoundary": "Observed actual CLI tokens at frozen repository API list-price equivalent; not a subscription invoice. Evaluation costs, CPU LAYA/search infrastructure and prior development attempts remain separate.",
        "authority": "Local committed source and raw receipts only; assigned ports 48771-48779, headless non-stealth, CPU LAYA. No credentials/NAS/protected tree/public services/downloads over 200 MB/push/remote merge.",
        "limitations": ["Two fixed public FRAMES panels; no general-superiority guarantee or provider seed control.", "Unverifiable external citation content is not counted supported.", "Timed-out provider calls without a usage event leave complete token/cost totals unknown; observed-known values are lower bounds.", "Completed comparator receipts may be reused byte-for-byte with hashed reuse manifests; no comparator answers were supplied to Neyvia.", "Repairs after the first complete evaluation were based on captured development host failures, without inspecting holdout questions, answers, gold or citations. All earlier attempted panels remain archived; the holdout is not claimed to be never executed.", "Development and holdout shared CPU LAYA and overlapped scoring; latency measures this actual contention, not an isolated serving benchmark.", "No rendered UI or public promotion claim."]}
    receipt["limitations"].append("Reused OpenAI latency belongs to the original complete comparator run; it is not a contemporaneous latency control.")
    experiment_path = EVIDENCE / "C10c-experimental.json"
    if experiment_path.exists():
        experiment = read(experiment_path)
        if experiment["activated"] or experiment["completedPairedPanels"]:
            raise ValueError("Isolated experiments must not be confused with the sealed engine or panels")
        receipt["unpromotedExperiments"] = {"path": str(experiment_path.relative_to(REPO)),
            "sha256": sha(experiment_path), "activated": False, "completedPairedPanels": 0}
        receipt["limitations"].append("Post-study subject/attribute packing, captured heading closure, explicit citation identity and 8,000-token context experiments remain isolated. Their native failures and narrower replay successes are retained; the completed panels evaluate the committed 5,500-token engine.")
    cleanup_path = EVIDENCE / "C10c-cleanup.json"
    if cleanup_path.exists():
        cleanup = read(cleanup_path)
        if not cleanup["ownedProcessesAbsent"] or not cleanup["noAssignedListener"]:
            raise ValueError("Owned runtime cleanup inventory is incomplete")
        receipt["cleanup"] = {"path": str(cleanup_path.relative_to(REPO)),
            "sha256": sha(cleanup_path), "observedAt": cleanup["observedAt"]}
    (EVIDENCE / "C10c.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": "scripts/evidence/C10c.json", "status": receipt["status"], "panelWins": wins, "tokenFactor": receipt["tokenReduction"]["factor"], "rawBytes": archive_path.stat().st_size}))


if __name__ == "__main__":
    main()
