"""Run the frozen local LAYA model and measure C2 browser decisions, offline."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
import urllib.request


def serve(args):
    """Compatibility shim for the installed Transformers 5 import relocation."""
    os.environ.update(USE_TF="0", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      LAYA_CUDA_GRAPHS="0", LAYA_WEIGHT_DTYPE="float32", LAYA_CPU_THREADS="4")
    import transformers.modeling_utils as modeling_utils
    if not hasattr(modeling_utils, "no_init_weights"):
        from transformers.initialization import no_init_weights
        modeling_utils.no_init_weights = no_init_weights
    # Transformers 5 split the nonpersistent RoPE buffer by attention type.
    # Materialize those deterministic frequencies on CPU, outside meta loading.
    from transformers.models.modernbert.modeling_modernbert import ModernBertRotaryEmbedding
    import torch
    torch.set_num_interop_threads(1)
    original_rotary_init = ModernBertRotaryEmbedding.__init__
    def rotary_init(self, config, device=None):
        original_rotary_init(self, config, device)
        for layer_type in getattr(self, "layer_types", []):
            for suffix in ("inv_freq", "original_inv_freq"):
                name = f"{layer_type}_{suffix}"
                buffer = getattr(self, name, None)
                if buffer is not None and buffer.device.type == "meta":
                    with torch.device("cpu"):
                        frequencies, _ = self.compute_default_rope_parameters(config, torch.device("cpu"), layer_type=layer_type)
                    self.register_buffer(name, frequencies, persistent=False)
    ModernBertRotaryEmbedding.__init__ = rotary_init
    sys.path.insert(0, str(args.project))
    from laya_system1.runtime import Runtime
    from laya_system1.service import Engine, create_server
    runtime = Runtime(args.model, device="cpu", calibration=args.calibration)
    runtime.identity["compatibility"] = "transformers5_import_and_nonpersistent_rope_buffers"
    engine = Engine(runtime, str(args.database), str(args.project / "question_sets"), 500)
    server = create_server(engine, port=args.port)
    print(json.dumps({"endpoint": f"http://127.0.0.1:{args.port}",
                      "identity": runtime.identity, "compatibility": "no_init_weights import relocation"}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        engine.close()


def evaluate(args):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from grant_agent.laya_client.calibration import temperature_probabilities
    from grant_agent.laya_client.contracts import digest
    cases = json.loads(args.cases.read_text(encoding="utf-8"))["cases"]
    if not cases or any(row.get("split") not in {"calibration", "heldout"} for row in cases):
        raise ValueError("Cases require explicit calibration/heldout splits")
    if set(row["id"] for row in cases if row["split"] == "calibration") & set(row["id"] for row in cases if row["split"] == "heldout"):
        raise ValueError("Calibration and held-out case IDs must be disjoint")
    def post(payload):
        request = urllib.request.Request(f"http://127.0.0.1:{args.port}/v1/decide", json.dumps(payload).encode(), {"Content-Type": "application/json"})
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=60) as response:
            value = json.load(response)
        return value, (time.perf_counter() - started) * 1000
    rows = []
    identity = None
    for case in cases:
        payload = {"state": case["state"], "questions": {"decision": case["question"]},
                   "scope": {"domain": "C2-consistency"}, "memory": False, "base_cache": False}
        response, elapsed = post(payload)
        if identity is None:
            identity = response["identity"]
        if identity != response["identity"] or response.get("memory_enabled") is not False or response["runtime"]["execution"] == "exact_base_cache":
            raise ValueError("Changed identity or cached/memory inference invalidates evaluation")
        answer = response["answers"]["decision"]
        repeats = []
        for _ in range(args.repeats - 1):
            repeated, repeated_elapsed = post(payload)
            if identity != repeated['identity'] or repeated.get('memory_enabled') is not False or repeated['runtime']['execution'] == 'exact_base_cache':
                raise ValueError('Repeat identity, memory or cache execution changed')
            repeats.append({"answer": repeated["answers"]["decision"]["answer"], "p": repeated["answers"]["decision"]["p"], "http_ms": repeated_elapsed,
                            "identity": repeated['identity'], "runtime": repeated["runtime"], "memory_enabled": repeated["memory_enabled"], "decision_id": repeated["decision_id"]})
        rows.append({**case, "response": response, "http_ms": elapsed, "repeats": repeats,
                     "deterministic": all(row["answer"] == answer["answer"] and row["p"] == answer["p"] for row in repeats)})
        print(json.dumps({"case": case["id"], "answer": answer["answer"], "gold": case["gold"], "p": answer["top_probability"], "ms": elapsed}), flush=True)
    fitting = [row for row in rows if row["split"] == "calibration"]
    heldout = [row for row in rows if row["split"] == "heldout"]
    if not fitting or not heldout:
        raise ValueError("Both calibration and held-out rows are required")
    # Conservative temperature scaling cannot increase an uncertain action's probability.
    temperatures = [1, 1.25, 1.5, 2, 3, 4, 6, 8, 12, 16]
    def nll(dataset, temperature):
        return statistics.mean(-math.log(max(temperature_probabilities(row["response"]["answers"]["decision"]["p"], temperature)[row["gold"]], 1e-12)) for row in dataset)
    temperature = min(temperatures, key=lambda value: nll(fitting, value))
    def metrics(dataset, temperature):
        data = []
        for row in dataset:
            answer = row["response"]["answers"]["decision"]
            probabilities = temperature_probabilities(answer["p"], temperature)
            confidence = probabilities[answer["answer"]]
            correct = answer["answer"] == row["gold"]
            data.append((confidence, correct, probabilities, row["gold"]))
        ece = 0
        for index in range(10):
            bucket = [row for row in data if index / 10 <= row[0] < (index + 1) / 10 or index == 9 and row[0] == 1]
            if bucket:
                ece += len(bucket) / len(data) * abs(statistics.mean(row[0] for row in bucket) - statistics.mean(row[1] for row in bucket))
        accepted = [row for row in data if row[0] >= .8]
        return {"count": len(data), "accuracy": statistics.mean(row[1] for row in data),
                "mean_confidence": statistics.mean(row[0] for row in data), "ece": ece,
                "brier": statistics.mean(sum((value - (key == gold)) ** 2 for key, value in probabilities.items()) for _, _, probabilities, gold in data),
                "nll": nll(dataset, temperature), "hit_rate": len(accepted) / len(data),
                "accepted_accuracy": statistics.mean(row[1] for row in accepted) if accepted else None,
                "escalated": len(data) - len(accepted)}
    raw_metrics, calibrated_metrics = metrics(heldout, 1), metrics(heldout, temperature)
    promoted = calibrated_metrics["brier"] <= raw_metrics["brier"] and calibrated_metrics["ece"] <= raw_metrics["ece"]
    calibration = {"schema": "neyvia.browser-confidence@1", "family": "browser_factual", "identity_digest": digest(identity),
                   "temperature": temperature if promoted else 1, "calibration_count": len(fitting), "heldout_count": len(heldout),
                   "cases_digest": digest(cases), "method": "conservative temperature NLL fit; heldout Brier/ECE veto",
                   "candidate_promoted": promoted, "supported_option_counts": sorted({len(row["question"]["criteria"]) for row in fitting}),
                   "decision_scope": "typed choices on the recorded browser states; action-selection transfer unproven",
                   "heldout_before": raw_metrics, "heldout_candidate": calibrated_metrics}
    samples = [row["http_ms"] for row in rows] + [repeat["http_ms"] for row in rows for repeat in row["repeats"]]
    result = {"schema": "neyvia.C2-laya-consistency@1", "identity": identity, "cases_digest": digest(cases), "memory_enabled": False, "base_cache": False,
              "determinism": {"cases": len(rows), "repeats_per_case": args.repeats, "identical": sum(row["deterministic"] for row in rows)},
              "heldout_before": raw_metrics, "heldout_after": calibrated_metrics if promoted else raw_metrics,
              "calibration": calibration, "latency_ms": {"http_p50": statistics.median(samples), "http_p95": statistics.quantiles(samples, n=100, method="inclusive")[94]},
              "rows": rows, "limitations": ["Small browser-task subset; no universal accuracy claim", "CPU inference latency; no GPU speed claim", "Recorded held-out factual decision calibration does not establish general action-selection confidence"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output.with_name("C2-laya-calibration.json").write_text(json.dumps(calibration, indent=2), encoding="utf-8")
    print(json.dumps({"determinism": result["determinism"], "heldout": result["heldout_after"], "candidate_promoted": promoted}), flush=True)


def probe(args):
    root = f"http://127.0.0.1:{args.port}"
    result = {"schema": "neyvia.C2-laya-runtime@1", "endpoint": root,
              "system_python": sys.executable, "launcher": str(Path(__file__).resolve()),
              "offline": True, "downloaded_bytes": 0, "neural_weights_modified": False}
    for route, key in (("/v1/health", "health"), ("/v1/question-sets", "question_sets")):
        with urllib.request.urlopen(root + route, timeout=10) as response:
            result[key] = json.load(response)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"endpoint": root, "status": result["health"]["status"], "identity": result["health"]["identity"]}), flush=True)


def summarize(args):
    """Derive reporting metadata from retained runs without running inference."""
    result = json.loads(args.output.read_text(encoding="utf-8"))
    if result.get("schema") != "neyvia.C2-laya-consistency@1":
        raise ValueError("Expected retained C2 LAYA inference receipt")
    rows = result["rows"]
    samples = [row["http_ms"] for row in rows] + [repeat["http_ms"] for row in rows for repeat in row["repeats"]]
    result["latency_ms"] = {"http_p50": statistics.median(samples), "http_p95": statistics.quantiles(samples, n=100, method="inclusive")[94]}
    result["calibration"]["supported_option_counts"] = sorted({len(row["question"]["criteria"]) for row in rows if row["split"] == "calibration"})
    result["calibration"]["decision_scope"] = "typed choices on the recorded browser states; action-selection transfer unproven"
    limitation = "Recorded held-out factual decision calibration does not establish general action-selection confidence"
    if limitation not in result["limitations"]:
        result["limitations"].append(limitation)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output.with_name("C2-laya-calibration.json").write_text(json.dumps(result["calibration"], indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("determinism", "heldout_before", "heldout_after", "latency_ms")}), flush=True)


def verify(args):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from grant_agent.laya_client.contracts import digest
    from grant_agent.laya_client.calibration import BrowserCalibration
    cases = json.loads(args.cases.read_text(encoding="utf-8"))["cases"]
    result = json.loads(args.output.read_text(encoding="utf-8"))
    if digest(cases) != result["cases_digest"] or len(cases) != len(result["rows"]):
        raise ValueError("Recorded case corpus changed")
    for case, row in zip(cases, result["rows"]):
        if any(case[key] != row[key] for key in case):
            raise ValueError("Decision receipt differs from original case")
        answer = row["response"]["answers"]["decision"]
        if row["response"]["identity"] != result["identity"] or row["response"]["memory_enabled"] or row["response"]["runtime"]["execution"] == "exact_base_cache":
            raise ValueError("Model identity, memory or execution changed")
        if not all(repeat["answer"] == answer["answer"] and repeat["p"] == answer["p"] for repeat in row["repeats"]):
            raise ValueError("Retained inference was nondeterministic")
    calibration = BrowserCalibration(args.output.with_name("C2-laya-calibration.json"))
    if calibration.spec["identity_digest"] != digest(result["identity"]):
        raise ValueError("Calibration identity mismatch")
    repo = Path(__file__).resolve().parents[1]
    sources = ["src/grant_agent/laya_client/browser_client.py", "src/grant_agent/laya_client/calibration.py", "src/grant_agent/laya_service.py", "scripts/c2_laya_consistency.py"]
    hashes = {}
    for relative in sources:
        path = repo / relative
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = {"schema": "neyvia.C2-laya-verification@1", "ok": True,
               "original_cases_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(), "original_cases_canonical_digest": digest(cases),
               "consistency_receipt_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(), "case_count": len(cases),
               "repeated_runs": sum(1 + len(row["repeats"]) for row in result["rows"]), "sources": hashes,
               "checks": ["original corpus and each recorded case unchanged", "all retained probabilities exactly repeat", "same frozen identity, no memory or base cache", "conservative calibration never raises action confidence", "owned source syntax valid"]}
    args.output.with_name("C2-laya-verification.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["serve", "evaluate", "probe", "summarize", "verify"])
    parser.add_argument("--project", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if args.port not in range(48717, 48720):
        parser.error("C2 LAYA requires its reserved explicit ports 48717–48719")
    if args.mode == "serve":
        if not args.database or not args.model or not args.project:
            parser.error("serve requires project, model and database")
        args.database.parent.mkdir(parents=True, exist_ok=True)
        serve(args)
    elif args.mode == "evaluate":
        if not args.cases or not args.output or args.repeats < 2:
            parser.error("evaluate requires cases, output and at least two repeats")
        evaluate(args)
    elif args.mode == "probe":
        probe(args)
    elif args.mode == "summarize":
        if not args.output:
            parser.error("summarize requires output receipt")
        summarize(args)
    else:
        if not args.cases or not args.output:
            parser.error("verify requires cases and output")
        verify(args)


if __name__ == "__main__":
    main()
