"""Workflow text domains on the existing frozen, paired Evolver mechanism."""
from __future__ import annotations

import inspect
import hashlib
import json
import uuid
from pathlib import Path

from .evolver_core import EvolverEngine
from .workflow_manuals import REPO, STAGES, validate_workflow


class LiveWorkflowRunner:
    """Fresh candidate evaluation through the explicitly requested Luna route."""
    def __init__(self, manual_id, directory):
        self.manual_id, self.directory = manual_id, Path(directory)

    def __call__(self, genome_text, item, seed):
        from .cl.benchmark_provider import propose
        from .cl.manuals import cl_to_manual, manual_to_cl
        data = cl_to_manual(genome_text)
        if data["id"] != self.manual_id:
            raise ValueError("Genome cannot change its workflow identity")
        chapter = "method" if self.manual_id == "hill-climb" else "workflow"
        data["chapters"] = {chapter: data["chapters"][chapter]}
        live_tools = {a["schema"] for a in data["chapters"][chapter]["actions"].values()}
        data["schemas"] = {k: v for k, v in data["schemas"].items() if k in live_tools}
        excerpt = manual_to_cl(data, {"neyvia.workflow.check": {"mutability_class": "read"},
                                        "neyvia.workflow.record": {"mutability_class": "artifact_write"},
                                        "neyvia.workflow.details": {"mutability_class": "read"}})
        prompt = ('Return only JSON {"events":[{"stage":"process step","data":{}}],"result":{"decision":boolean or option ID,"reason":"explanation"}}. '
                  'Use actual host evidence IDs as receipt strings. Do not invent measurements or invoke tools. '
                  '\nTASK: ' + item["task"] + '\nHOST EVIDENCE:\n' + json.dumps(item["evidence"], ensure_ascii=False)
                  + '\nFOLLOW THIS CL 1.1 MANUAL:\n' + excerpt)
        directory = self.directory / (item["id"] + "-" + str(seed) + "-" + uuid.uuid4().hex)
        image = REPO / item["image"] if item.get("image") else None
        if image is not None and hashlib.sha256(image.read_bytes()).hexdigest() != item["imageSha256"]:
            raise ValueError("Frozen rendered artifact changed")
        provider = propose(prompt, "gpt-6-luna", directory, image=image, timeout=240)
        report = json.loads(provider["answer"]) if provider.get("passed") else {}
        usage = provider.get("usage") or {}
        raw = directory / "events.jsonl"
        return {"report": report,
                "outcomeQuality": float(provider.get("passed", False) and report.get("result", {}).get("decision") == item["expected"]),
                "evidence": item["evidence"], "tokens": max(1, usage.get("input_tokens", 0) + usage.get("output_tokens", 0)),
                "providerReceipt": {**provider, "raw": str(raw), "rawSha256": hashlib.sha256(raw.read_bytes()).hexdigest()}}


class WorkflowEvaluator:
    """Runner performs the task; host judge supplies outcome quality and evidence.

    Runner(genome_text, item, seed) must return report, outcomeQuality, evidence,
    tokens and providerReceipt. No model-provided quality or usage is trusted.
    The runner implementation is locked together with this adapter.
    """
    def __init__(self, manual_id, runner):
        self.manual_id, self.runner = manual_id, runner

    def __call__(self, genome, item, seed):
        measured = self.runner(genome["text"], item, seed)
        receipt = measured["providerReceipt"]
        path = Path(receipt.get("raw", ""))
        real = (receipt.get("requestedModel", receipt.get("model")) == "gpt-6-luna"
                and bool(receipt.get("usage")) and path.is_file()
                and hashlib.sha256(path.read_bytes()).hexdigest() == receipt.get("rawSha256"))
        score = validate_workflow(self.manual_id, measured["report"], measured["outcomeQuality"],
                                  measured["tokens"], measured["evidence"])
        return {"objectives": {"fitness": score["fitness"], "outcome_quality": score["outcomeQuality"],
                               "adherence": score["adherence"], "tokens": score["tokens"]},
                "hard_gates": {"real_provider_receipt": real}, "workflow": score,
                "providerReceipt": receipt}


def establish_workflow_domain(engine: EvolverEngine, manual_id: str, panels: list[dict], runner,
                              *, version="1", max_trials=4, judge_files=()):
    if manual_id not in STAGES:
        raise ValueError("Unknown workflow manual")
    runner_source = inspect.getsourcefile(runner if inspect.isfunction(runner) else runner.__call__)
    if runner_source is None:
        raise ValueError("Runner must have a hash-lockable source file")
    source = REPO / "manuals" / "cl" / (manual_id + ".cl")
    domain_id = "workflow-" + manual_id + "-" + version
    engine.establish_domain(domain_id,
        judges=[source, Path(__file__), Path(__file__).with_name("workflow_manuals.py"), runner_source,
                Path(__file__).with_name("workflow_panels.py"),
                REPO / "src/grant_agent/cl/benchmark_provider.py", REPO / "src/grant_agent/cl/manuals.py", *judge_files],
        panels=panels,
        objectives={name: {"direction": "min" if name == "tokens" else "max", "noise": 0.0, "tolerance": 0.0}
                    for name in ("fitness", "outcome_quality", "adherence", "tokens")},
        promotion={"min_pairs": 4, "max_trials": max_trials, "max_evaluations": 512, "max_seconds": 7200},
        hard_gates=["real_provider_receipt"])
    seed = engine.register_genome(domain_id, {"kind": "text", "text": source.read_text(encoding="utf-8")},
                                  provenance={"manual": manual_id, "source_format": "Connected Language 1.1"})
    engine.set_incumbent(domain_id, seed["id"])
    return {"domain": domain_id, "seed": seed, "evaluator": WorkflowEvaluator(manual_id, runner)}
