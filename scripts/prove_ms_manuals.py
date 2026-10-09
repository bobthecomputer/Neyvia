"""Frozen, receipt-backed three-task paired Luna panel for each MS workflow."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "src"), str(REPO / "scripts")]
from grant_agent.cl.benchmark_provider import propose
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
from grant_agent.workflow_manuals import validate_workflow
from efficiency_log import append, digest

DEST = REPO / "scripts/evidence/MS-runs/manuals"
MANUALS = ("hill-climb", "creativity", "critique-review", "efficiency", "research", "design")


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def freeze():
    """Measure actual CL compilation; other panels inspect real saved artifacts.

    Corrupted projections are explicit adversarial review fixtures, never passed
    off as faults in the original files. No task mutates production source.
    """
    panel_path = DEST / "panel.json"
    if panel_path.exists():
        return json.loads(panel_path.read_text(encoding="utf-8"))
    tasks = []
    for i, name in enumerate(("notes", "workspace", "design"), 1):
        source = (REPO / f"manuals/cl/{name}.cl").read_text(encoding="utf-8")
        compiled = cl_to_manual(source)
        check = hashlib.sha256(json.dumps(compiled, sort_keys=True).encode()).hexdigest()
        samples = []
        for _ in range(5):
            began = time.perf_counter()
            assert cl_to_manual(source) == compiled
            samples.append(time.perf_counter() - began)
        base = 1 / statistics.median(samples)
        cached = compiled
        began = time.perf_counter()
        for _ in range(100):
            assert cached == compiled
        faster = 1 / ((time.perf_counter() - began) / 100)
        bad_projection = {**compiled, "chapters": {}}
        assert bad_projection != compiled
        value = faster if i == 1 else 0 if i == 2 else base
        noise = max(abs(1 / s - base) for s in samples)
        evidence = {
            "baseline": {"checkHash": check, "value": base, "noise": noise, "samplesSeconds": samples},
            "measurement": {"checkHash": check, "value": value, "success": i != 2,
                            "mechanism": "memoized compilation" if i == 1 else "drops chapters" if i == 2 else "unchanged replay"},
            "log-entry": {"kind": "research-ledger", "measurement": "measurement", "ledgerId": f"ms-measure-hill-climb-{i}"}}
        tasks.append({"id": f"hill-climb-{i}", "manual": "hill-climb", "evidence": evidence,
            "source": f"manuals/cl/{name}.cl", "sourceSha256": digest(REPO / f"manuals/cl/{name}.cl"),
            "task": "Decide whether to keep this single CL compilation change. Higher value is correct compilations per second. Zero means the frozen semantic equality check failed. Preserve the frozen check and noise threshold. Write an executable process report, including a stopping rule and evidence-linked research log.",
            "expected": value > base + noise})
    for i, (problem, expected) in enumerate((
        ("The study player must avoid testing unseen material. Choose a cheap reversible mechanism. Options: host-exposure-gate enforces observed prerequisites; random-question samples all cards; bigger-model asks a model each swipe. Generate at least three mechanism-distinct proposals and choose using novelty, usefulness and cost.", "host-exposure-gate"),
        ("A maths pack needs changed exercises after a miss. Options: parameterized-variants generates solved coefficient changes; repeat-identical replays unchanged text; decorative-motion animates it. Generate at least three mechanism-distinct proposals and choose using novelty, usefulness and cost.", "parameterized-variants"),
        ("Research costs need exact reproducible accounting. Options: receipt-ledger derives provider usage and hashes; model-estimate asks a model to guess token cost; screenshot-counter counts cards from pictures. Generate at least three mechanism-distinct proposals and choose using novelty, usefulness and cost.", "receipt-ledger")), 1):
        tasks.append({"id": f"creativity-{i}", "manual": "creativity", "evidence": {}, "task": problem + " Reframe the problem, borrow a principle from another field, and flip a constraint before choosing. Keep the supplied option IDs.", "expected": expected})
    smoke_path = REPO / "scripts/evidence/MS-runs/smoke/gpt-6-luna/receipt.json"
    smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
    for i, (mechanism, evidence) in enumerate((
        ("Seven distinct ordered study parts with source spans", {"inspection": {"success": False, "observedParts": ["FORMULA", "WHEN"], "requiredParts": 7, "fixture": "explicit incomplete pack projection"}, "source-audit": {"success": False, "unreferencedCards": 2}}),
        ("CL source must compile exactly to its registered JSON projection", {"inspection": {"success": False, "sourceSha256": digest(REPO / "manuals/cl/notes.cl"), "projection": "controlled mutation: chapters removed"}, "source-audit": {"success": False, "unregisteredSource": True}}),
        ("A route smoke proves only transport, not study learning or task completion", {"inspection": {"success": True, "answer": smoke["answer"], "usage": smoke["usage"], "sourceSha256": digest(smoke_path)}, "source-audit": {"success": False, "learningMeasured": False}})), 1):
        tasks.append({"id": f"critique-review-{i}", "manual": "critique-review", "evidence": evidence,
                      "task": "Review the defining mechanism: " + mechanism + ". Attack at least two failure paths, link verification receipts, and decide whether the artifact is done. Expose missing proof.", "expected": False})
    for i, path in enumerate(("config/neyvia_manuals.json", "scripts/fixtures/ms-chain-rule-course.md", "scripts/evidence/MS-runs/smoke/gpt-6-luna/receipt.json"), 1):
        began = time.perf_counter()
        raw = (REPO / path).read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        elapsed = (time.perf_counter() - began) * 1000
        measured = {"path": "script", "tokens": 0, "latencyMs": elapsed, "success": True, "sha256": checksum, "source": path}
        tasks.append({"id": f"efficiency-{i}", "manual": "efficiency", "evidence": {"attempt": measured, "measurement": measured, "log-entry": {"kind": "research-ledger", "measurement": "measurement", "ledgerId": f"ms-measure-efficiency-{i}"}},
            "task": "Choose a route for exact SHA-256 extraction from this local source. Available paths are script, memory, small-model, big-model. The attached actual read/hash measurement is validated; exact bytes matter. Report the process, measured token/latency cost, and log linkage.", "expected": "script"})
    for i, (question, success, observation) in enumerate((
        ("Does this Luna smoke prove improved learning retention?", False, {"answer": smoke["answer"], "latencyMs": smoke["latencyMs"], "learningObservations": 0}),
        ("Can this course example's stated derivative be verified at x=1?", True, {"expression": "(3*x*x+1)^(-2)", "analytic": -12 / 64, "finiteDifference": (((3 * (1 + 1e-5)**2 + 1)**-2) - ((3 * (1 - 1e-5)**2 + 1)**-2)) / 2e-5}),
        ("Does exact CL compilation equality prove rendered keyboard accessibility?", False, {"clSource": "manuals/cl/design.cl", "browserObserved": False})), 1):
        tasks.append({"id": f"research-{i}", "manual": "research", "evidence": {"experiment": {"success": success, **observation}},
            "task": question + " Use prior art: docs/research/scroll-study-learning.md distinguishes implementation checks from retention evidence; scripts/cl_compile_manuals.py checks source equality; the OpenStax note provides independently verifiable maths. State a falsifiable prediction, smallest test and honest limitation-bound result.", "expected": success})
    for i, image in enumerate(("docs/evidence/ui2-outputs/classic-notebook-dark.png", "docs/evidence/ui2-outputs/classic-notebook-light.png", "docs/evidence/t3-a11y/voice-live-spoken-open-notes.png"), 1):
        tasks.append({"id": f"design-{i}", "manual": "design", "image": image, "evidence": {"rendered-artifact": {"rendered": True, "path": image, "sha256": digest(REPO / image), "historical": True}},
            "task": "Review the attached historical UI screenshot for Paul's full-screen-mode requirement and clutter. Use details patterns with stated purposes, inspect the rendered artifact, and identify evidence-backed defects and taste. This image cannot establish current runtime completion; decide whether current product design is proven done. Propose no visual implementation.", "expected": False})
    save(panel_path, {"schema": "neyvia.ms.frozen-panel.v1", "tasks": tasks,
                "boundary": "Real Luna decisions on measured compilation, source extraction, public maths and frozen review artifacts. Controlled adverse projections are labeled; no general learning or UI release claim."})
    return json.loads(panel_path.read_text(encoding="utf-8"))


def log_measurements(panel):
    ledger = REPO / "docs/research/results.jsonl"
    old = {json.loads(line)["id"] for line in ledger.read_text(encoding="utf-8").splitlines()} if ledger.exists() else set()
    for index, task in enumerate(panel["tasks"]):
        if task["manual"] not in {"hill-climb", "efficiency"}:
            continue
        identifier = "ms-measure-" + task["id"]
        if identifier in old:
            continue
        fields = [("baseline", "value", "correct-compilations/s"), ("measurement", "value", "correct-compilations/s")] if task["manual"] == "hill-climb" else [("measurement", "tokens", "tokens"), ("measurement", "latencyMs", "ms")]
        metrics = [{"name": receipt + "_" + field, "unit": unit,
            "calculation": {"receipt": "panel", "pointer": f"/tasks/{index}/evidence/{receipt}/{field}"},
            "ci_request": {"method": "not-estimable", "reason": "Local fixed fixture measurement; no workload population estimate."}} for receipt, field, unit in fields]
        append({"schema": "neyvia.efficiency-result.v1", "id": identifier, "study": "MS frozen measurement " + task["id"],
            "method": "Actual local CL parse/equality timing or exact-byte file hash, frozen before model decisions. Adverse dropped-chapter projection explicitly controlled.",
            "models": ["no-model"], "tasks": {"description": task["task"], "repetitions": 1, "independent_unit": "local artifact"},
            "limitations": ["Fixed local fixture, not a general performance result. Identity-cache equality overhead excludes initial compilation."],
            "receipts": [{"id": "panel", "path": "scripts/evidence/MS-runs/manuals/panel.json", "sha256": digest(DEST / "panel.json"), "kind": "raw"}],
            "metrics": metrics, "evidence_status": "raw-verified"}, ledger, REPO / "docs/research/efficiency-log.md")


def excerpt(manual, source=None):
    data = cl_to_manual(source or (REPO / f"manuals/cl/{manual}.cl").read_text(encoding="utf-8"))
    ids = [key for key in data["chapters"] if key in {"method", "workflow", "workflow-method", "details", "taste"}]
    if ids:
        data["chapters"] = {key: data["chapters"][key] for key in ids}
    return manual_to_cl(data)


def run_case(task, arm, reviewed=False):
    directory = DEST / task["id"] / ("with-reviewed" if reviewed and arm == "with" else arm)
    if (directory / "result.json").exists():
        return json.loads((directory / "result.json").read_text(encoding="utf-8"))
    syntax = ('Return only JSON {"events":[{"stage":"process step","data":{}}],"result":{"decision":boolean or option ID,"reason":"explanation"}}. '
              'Events must faithfully report your decision process; use host receipt IDs for measurements. Do not invent measurements or invoke tools. ')
    prompt = syntax + "\nTASK: " + task["task"] + "\nHOST EVIDENCE:\n" + json.dumps(task["evidence"], ensure_ascii=False)
    source = (REPO / f"manuals/cl/{task['manual']}.cl").read_text(encoding="utf-8")
    manual = excerpt(task["manual"], source) if arm == "with" else ""
    if manual:
        prompt += "\nFOLLOW THIS CL 1.1 MANUAL:\n" + manual
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manual-source.cl").write_text(source, encoding="utf-8", newline="\n")
    receipt = propose(prompt, "gpt-6-luna", directory, image=REPO / task["image"] if task.get("image") else None, timeout=300)
    answer, error = {}, ""
    try:
        answer = json.loads(receipt["answer"])
    except (ValueError, TypeError) as exc:
        error = str(exc)
    quality = float(receipt["passed"] and answer.get("result", {}).get("decision") == task["expected"])
    usage = receipt.get("usage") or {}
    tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    checked = validate_workflow(task["manual"], answer, quality, max(1, tokens), task["evidence"])
    result = {"task": task["id"], "manual": task["manual"], "arm": arm, "model": "gpt-6-luna",
              "transportPassed": receipt["passed"], "outcomeQuality": quality, "adherence": checked["adherence"],
              "accepted": checked["accepted"], "fitness": checked["fitness"], "tokens": tokens,
              "latencyMs": receipt["latencyMs"], "answer": answer, "validation": checked, "parseError": error,
              "sourceSha256": hashlib.sha256(source.encode()).hexdigest(),
              "revision": "reviewed" if reviewed else "initial",
              "excerptSha256": hashlib.sha256(manual.encode()).hexdigest() if manual else None,
              "providerReceiptSha256": digest(directory / "receipt.json")}
    save(directory / "result.json", result)
    print(json.dumps({key: result[key] for key in ("task", "arm", "outcomeQuality", "adherence", "tokens")}), flush=True)
    return result


def log_results(results, reviewed=False):
    ledger = REPO / "docs/research/results.jsonl"
    old_ids = {json.loads(line)["id"] for line in ledger.read_text(encoding="utf-8").splitlines()} if ledger.exists() else set()
    for manual in MANUALS:
        records = [r for r in results if r["manual"] == manual]
        if len(records) != 6:
            continue
        path = DEST / (manual + ("-reviewed" if reviewed else "") + "-paired.json")
        save(path, records)
        identifier = "ms-manual-" + manual + ("-reviewed" if reviewed else "")
        if identifier in old_ids:
            continue
        metrics = []
        for arm in ("without", "with"):
            for field, unit in (("outcomeQuality", "quality"), ("adherence", "fraction"), ("tokens", "tokens"), ("latencyMs", "ms"), ("fitness", "quality*adherence/token")):
                metrics.append({"name": arm + "_" + field, "unit": unit,
                    "calculation": {"op": "mean", "args": [{"receipt": "paired", "where": {"/arm": arm}, "field": "/" + field}]},
                    "ci_request": {"method": "not-estimable", "reason": "Three fixed tasks and one trial per arm; no population improvement inference."}})
        append({"schema": "neyvia.efficiency-result.v1", "id": identifier, "study": "MS workflow: " + manual,
                "method": "Same frozen tasks and proposal format, isolated explicit Luna CLI route, low effort, one attempt. Arms alternate by task. Host grades result independently; executable manual scores evidence and chronology.",
                "models": ["gpt-6-luna"], "tasks": {"description": "Three frozen work-product decisions; with and without authored CL 1.1 workflow excerpt", "repetitions": 1, "independent_unit": "task"},
                "limitations": ["Fixed small panel; no held-out or statistical improvement claim.", "Reviewed cohort repeats tasks after schema-guidance repairs and reuses initial baselines; it is not independent holdout evidence." if reviewed else "Initial cohort includes recorded manual-guidance repairs during execution; exact injected prompts are preserved.", "Provider model route is explicit; deployed weights are not independently attested.", "Design reviews historical screenshots; current interactive browser unavailable."],
                "receipts": [{"id": "paired", "path": str(path.relative_to(REPO)).replace("\\", "/"), "sha256": digest(path), "kind": "raw"}],
                "metrics": metrics, "evidence_status": "raw-verified"}, ledger, REPO / "docs/research/efficiency-log.md")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manuals", nargs="+", choices=MANUALS, default=list(MANUALS))
    parser.add_argument("--freeze-only", action="store_true")
    parser.add_argument("--log-only", action="store_true")
    parser.add_argument("--reviewed", action="store_true", help="Preserve initial trial; rerun with repaired manuals and reuse frozen without-manual baselines")
    args = parser.parse_args()
    panel = freeze()
    log_measurements(panel)
    if args.freeze_only:
        return
    jobs = [(task, arm) for task in panel["tasks"] if task["manual"] in args.manuals
            for arm in (("with",) if args.reviewed else (("without", "with") if int(task["id"].rsplit("-", 1)[1]) % 2 else ("with", "without")))]
    if not args.log_only:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda pair: run_case(*pair, reviewed=args.reviewed), jobs))
    selected = {"without", "with-reviewed"} if args.reviewed else {"without", "with"}
    results = [json.loads(path.read_text(encoding="utf-8")) for path in DEST.glob("*/*/result.json") if path.parent.name in selected]
    save(DEST / ("reviewed-results.json" if args.reviewed else "results.json"), results)
    log_results(results, args.reviewed)
    print(json.dumps({"cases": len(results), "qualityPasses": sum(r["outcomeQuality"] for r in results),
                      "withAdherencePasses": sum(r["accepted"] for r in results if r["arm"] == "with")}), flush=True)


if __name__ == "__main__":
    main()
