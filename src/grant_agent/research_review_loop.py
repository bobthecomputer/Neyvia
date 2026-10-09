"""Bounded evaluator feedback; exhausted attempts produce a best final answer."""
from __future__ import annotations
import json

from .research_evaluator import beast, evaluate
from .research_grounding import ANSWER, match


def review(pipeline, question, candidate, sources, ask, capture, evidence, receipt, rules):
    issues = "Research budget exhausted before verification"
    try:
        # Jina node-DeepResearch bounds unsuccessful attempts, then forces a
        # final answer. Keep independent checks separate from reference overlap.
        for attempt in range(min(2, pipeline.rounds) + 1):
            candidate = match(candidate, sources, receipt)
            context = evidence(candidate)
            check = evaluate(question, candidate, context, ask, receipt)
            if check["accepted"]:
                return candidate
            issues = check["issues"] or json.dumps(check, ensure_ascii=False)
            if attempt == min(2, pipeline.rounds):
                break
            candidate = ask(question + "\n" + rules +
                "\nRepair only unresolved required facts. Verify alternate interpretations, entities, "
                "roles and event milestones, rather than merely repeating the previous answer. "
                "Use the evaluator's targeted queries to obtain new independent primary evidence. "
                "Correct the answer and necessary derivation when observations contradict them. "
                "Do not treat missing exact quotation spans as false factual claims.\nIssues:\n" +
                json.dumps(check, ensure_ascii=False) + "\nCandidate:\n" +
                json.dumps(candidate, ensure_ascii=False) + "\nAccumulated evidence:\n" + context,
                ANSWER, live=True)
            capture(candidate)
    except Exception as exc:
        issues = str(exc)
        if "Benchmark mirror exposure" in issues:
            raise
        receipt["errors"].append({"stage": "evaluation", "error": issues[:800]})
    # An exhausted or temporarily unavailable evaluator must not delete the
    # latest substantive answer. It also must not pretend that answer passed.
    receipt["claimGrounding"] = {"accepted": False, "issues": issues,
                                  "bestEffort": True, "independent": False}
    try:
        candidate = beast(question, candidate, evidence(candidate, summarize=False), issues, ask, receipt)
    except Exception as exc:
        receipt.setdefault("beastMode", {}).update(finalizerError=str(exc)[:800],
                                                  preservedLastSubstantiveAnswer=bool(candidate.get("answer")))
    return match(candidate, sources, receipt)
