"""Fit only calibration rows; evaluate untouched real-run decision groups."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time
import urllib.request
from urllib.parse import urlsplit

ADVISORY_FIELDS = {"Choose the observed page topic.": "title", "Choose the correct current website.": "hostname",
                   "Choose the actual observed page URL.": "url", "What is the observed document loading state?": "readyState"}


def advisory_eligible(row):
    return (row.get("family") in {"evidence", "readiness"}
            and row.get("decision_profile") == "public_observed_fields@1"
            and ADVISORY_FIELDS.get(row["question"]["instructions"]) == row.get("advisory_field")
            and row["question"].get("view") == ["page", "controls", "current"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 48721 <= args.port <= 48729 or args.repeats < 2:
        parser.error("Use an assigned explicit port and at least two deterministic repeats")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from grant_agent.laya_client.contracts import digest
    from grant_agent.laya_client.browser_client import grounded_action_instructions
    cases = [json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len({row["id"] for row in cases}) != len(cases):
        raise ValueError("Decision IDs must be unique")
    fitting = [row for row in cases if row["split"] == "calibration"]
    heldout = [row for row in cases if row["split"] == "heldout"]
    if len(fitting) < 20 or len(heldout) < 200 or len(fitting)+len(heldout) != len(cases):
        raise ValueError("Need at least 20 calibration and 200 held-out real decisions")
    groups = lambda rows: {row.get("group", row["provenance"].get("url", row["provenance"].get("window"))) for row in rows}
    if None in groups(cases) or groups(fitting) & groups(heldout):
        raise ValueError("Fit and held-out page/window groups must be disjoint")
    if {digest(row["state"]) for row in fitting} & {digest(row["state"]) for row in heldout}:
        raise ValueError("The same observation cannot enter both calibration and held-out splits")
    def fit_threshold(dataset):
        eligible = []
        for threshold in sorted({row["confidence"] for row in dataset}):
            accepted = [row for row in dataset if row["confidence"] >= threshold]
            if len(accepted) >= 20 and statistics.mean(row["correct"] for row in accepted) >= .95:
                eligible.append((len(accepted), threshold))
        return max(eligible, default=(0, 1.000001), key=lambda item: (item[0], -item[1]))[1]
    rows, identity, frozen_threshold = [], None, None
    ordered_cases = sorted(cases, key=lambda row: row["split"] != "calibration")
    for index, case in enumerate(ordered_cases):
        if case["split"] == "heldout" and frozen_threshold is None:
            frozen_threshold = fit_threshold([row for row in rows if advisory_eligible(row)])
            freeze = {"schema": "neyvia.C2b-threshold-freeze@1", "advisory_threshold": frozen_threshold,
                      "action_threshold": 1.000001, "fit_predictions_digest": digest(rows),
                      "fit_count": len(rows), "eligible_fit_count": sum(advisory_eligible(row) for row in rows),
                      "identity_digest": digest(identity), "frozen_before_any_heldout_inference": True}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.with_name("C2b-laya-threshold-freeze.json").write_text(json.dumps(freeze, indent=2), encoding="utf-8")
            print(json.dumps(freeze), flush=True)
        question = case.get("question") or {"type": "choice", "instructions": case["goal"],
            "criteria": {option["id"]: option["description"] for option in case["options"]}}
        gold = case.get("gold", case.get("expected"))
        if case.get("family") == "grounded_action":
            goal = case["state"].get("goal")
            if not isinstance(goal, str) or question.get("instructions") != grounded_action_instructions(goal, case.get("decision_profile")) or question.get("view") != ["goal", "controls", "current", "progress", "action_receipts"]:
                raise ValueError("Action calibration must use the exact deployed question template and state view")
        if gold not in question["criteria"] or not case.get("provenance") or not case.get("expected_check"):
            raise ValueError("Every row needs independently checked gold and live observation provenance")
        payload = json.dumps({"state": case["state"], "questions": {"decision": question},
                              "memory": False, "base_cache": False}).encode("utf-8")
        answers, samples, model_samples = [], [], []
        for _ in range(args.repeats):
            started = time.perf_counter()
            request = urllib.request.Request(f"http://127.0.0.1:{args.port}/v1/decide", payload,
                                            {"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=10) as response:
                value = json.load(response)
            samples.append((time.perf_counter()-started)*1000)
            model_samples.append(value["latency_ms"]["model"])
            identity = identity or value["identity"]
            if identity != value["identity"] or value.get("memory_enabled") is not False or value["runtime"]["execution"] != "cpu-only-r5":
                raise ValueError("Frozen CPU identity, actual inference or no-memory gate changed")
            answer = value["answers"]["decision"]
            answers.append({"answer": answer["answer"], "p": answer["p"], "decision_id": value["decision_id"],
                            "runtime": value["runtime"]})
        rows.append({**case, "question": question, "gold": gold, "prediction": answers[0]["answer"],
            "p": answers[0]["p"], "confidence": max(answers[0]["p"].values()),
            "correct": answers[0]["answer"] == gold, "deterministic": all((a["answer"], a["p"]) == (answers[0]["answer"], answers[0]["p"]) for a in answers),
            "repeats": answers, "http_ms": samples, "model_ms": model_samples})
        if index % 50 == 0:
            print(json.dumps({"decisions": index+1, "total": len(cases)}), flush=True)
    fit_rows = [row for row in rows if row["split"] == "calibration"]
    threshold = frozen_threshold
    action_fit = [row for row in fit_rows if row.get("family") == "grounded_action"]
    action_threshold = 1.000001
    def metrics(dataset, acceptance_threshold=threshold, *, advisory_gate=True):
        accepted = [row for row in dataset if row["confidence"] >= acceptance_threshold and (not advisory_gate or advisory_eligible(row))]
        correct = sum(row["correct"] for row in accepted)
        p = correct/len(accepted) if accepted else None
        # Wilson lower bound is disclosed; observed 95% is not a population guarantee.
        n = len(accepted)
        lower = ((p+1.96**2/(2*n)-1.96*math.sqrt(p*(1-p)/n+1.96**2/(4*n*n)))/(1+1.96**2/n)) if n else None
        return {"count": len(dataset), "accuracy": statistics.mean(row["correct"] for row in dataset),
                "accepted": n, "accepted_correct": correct, "precision": p,
                "precision_wilson_lower_95": lower, "coverage": n/len(dataset),
                "escalated": len(dataset)-n}
    hold_rows = [row for row in rows if row["split"] == "heldout"]
    fit_metrics, hold_metrics = metrics(fit_rows), metrics(hold_rows)
    family_metrics = {family: metrics([row for row in hold_rows if row.get("family", "unspecified") == family])
                      for family in sorted({row.get("family", "unspecified") for row in hold_rows})}
    action_hold = [row for row in hold_rows if row.get("family") == "grounded_action"]
    action_metrics = metrics(action_hold, action_threshold, advisory_gate=False) if action_hold else {}
    action_fit_metrics = metrics(action_fit, action_threshold, advisory_gate=False) if action_fit else {}
    action_profiles = sorted({row.get("decision_profile", "") for row in action_fit})
    profile_supported = bool(action_profiles and "" not in action_profiles and
                             set(row.get("decision_profile") for row in action_hold) <= set(action_profiles))
    action_validated = False
    validated = bool(hold_metrics["accepted"] and hold_metrics["precision"] >= .95 and all(row["deterministic"] for row in rows))
    spec = {"schema": "neyvia.browser-confidence@2", "family": "browser_factual", "temperature": 1,
            "decision_scope": "supported_browser_advisory",
            "identity_digest": digest(identity),
            "calibration_count": len(fit_rows), "heldout_count": len(hold_rows), "acceptance_threshold": action_threshold,
            "mixed_decision_threshold": threshold,
            "advisory_threshold": threshold, "advisory_validated": validated,
            "validated": action_validated, "mixed_decision_validated": False,
            "advisory_fitting_eligible_count": sum(advisory_eligible(row) for row in fit_rows),
            "advisory_heldout_eligible_count": sum(advisory_eligible(row) for row in hold_rows),
            "supported_option_counts": sorted({len(row["p"]) for row in action_fit}),
            "supported_option_id_sequences": [list(sequence) for sequence in sorted({tuple(row["p"]) for row in action_fit})],
            "supported_decision_profiles": action_profiles,
            "browser_client_sha256": hashlib.sha256((Path(__file__).resolve().parents[1]/"src/grant_agent/laya_client/browser_client.py").read_bytes()).hexdigest(),
            "advisory_browser_client_sha256": hashlib.sha256((Path(__file__).resolve().parents[1]/"src/grant_agent/laya_client/browser_client.py").read_bytes()).hexdigest(),
            "supported_advisory_questions": [{"instructions": instructions, "field": ADVISORY_FIELDS[instructions]} for instructions in sorted({row["question"]["instructions"] for row in fit_rows if advisory_eligible(row)})],
            "advisory_option_id_sequences": [list(sequence) for sequence in sorted({tuple(row["p"]) for row in fit_rows if advisory_eligible(row)})],
            "advisory_evaluated_hosts": sorted({urlsplit(row["provenance"].get("url", "")).hostname for row in fit_rows + hold_rows if advisory_eligible(row) and urlsplit(row["provenance"].get("url", "")).hostname}),
            "evaluated_hosts": sorted({urlsplit(row["provenance"].get("url", "")).hostname for row in action_fit + action_hold if urlsplit(row["provenance"].get("url", "")).hostname}),
            "method": "maximum supported-advisory fitting coverage with at least 20 accepted and observed precision >= .95; threshold frozen before heldout scoring; action gate disabled after failed fitting-only probe",
            "dataset_digest": digest(cases), "calibration": fit_metrics, "heldout": hold_metrics,
            "heldout_by_family": family_metrics, "action_calibration": action_fit_metrics,
            "action_heldout": action_metrics,
            "scope_limit": "Only declared profiles on the finitely evaluated hosts and option counts; no arbitrary UI/control confidence transfer"}
    percentile = lambda values, p: sorted(values)[min(len(values)-1, math.ceil(len(values)*p)-1)]
    clocks = {name: [ms for row in rows for ms in row[name]] for name in ("http_ms", "model_ms")}
    result = {"schema": "neyvia.C2b-laya@1", "identity": identity, "calibration": spec,
              "determinism": {"cases": len(rows), "repeats": args.repeats, "identical": sum(row["deterministic"] for row in rows)},
              "latency_ms": {name: {"p50": statistics.median(values), "p95": percentile(values,.95)} for name,values in clocks.items()},
              "advisory_postcheck": {"accepted_after_independent_native_field_check": hold_metrics["accepted_correct"],
                                     "rejected_by_native_field_check": hold_metrics["accepted"]-hold_metrics["accepted_correct"],
                                     "precision_after_postcheck": 1.0 if hold_metrics["accepted_correct"] else None,
                                     "boundary": "Recorded actual native field checks; live application journey reported separately"},
              "rows": rows, "limitations": ["Real-run observation replay; held-out decisions are correlated within pages/tasks", "Observed accepted precision is not a population guarantee", "No GPU, larger model, fitted labels or answer cache in the decision process"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    args.calibration.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    print(json.dumps({"calibration": fit_metrics, "heldout": hold_metrics, "threshold": threshold,
                      "validated": validated, "action_threshold": action_threshold,
                      "action_validated": action_validated, "action_heldout": action_metrics,
                      "latency": result["latency_ms"], "determinism": result["determinism"]}), flush=True)


if __name__ == "__main__":
    main()
