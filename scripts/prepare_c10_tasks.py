"""Freeze the public FRAMES panel and arm-blind research rubric (stdlib only)."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from urllib.request import urlopen

REVISION = "58d9fb6330f3ab1316d1eca12e5e8ef23dcc22ef"
BASE = "https://huggingface.co/datasets/google/frames-benchmark"
OUTPUT = Path(__file__).resolve().parent / "evidence" / "C10-tasks.json"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def fetch(name):
    with urlopen(f"{BASE}/resolve/{REVISION}/{name}", timeout=60) as response:
        payload = response.read(2_000_001)
    if len(payload) > 2_000_000:
        raise ValueError("Dataset source exceeded the 2 MB safety cap")
    return payload


def main():
    if OUTPUT.exists():
        raise SystemExit("Frozen panel already exists; refusing to silently replace it")
    source = fetch("test.tsv")
    readme = fetch("README.md")
    if "license: apache-2.0" not in readme.decode("utf-8"):
        raise ValueError("Primary dataset card license declaration changed")
    rows = list(csv.DictReader(io.StringIO(source.decode("utf-8-sig")), delimiter="\t"))
    common = "Research the question using public web sources. Return a concise answer, explain necessary reasoning, and cite direct source URLs supporting the answer. State uncertainty rather than inventing facts. Do not inspect local evaluation files, benchmark datasets, gold answers, or other arms' outputs."
    questions = []
    for index, row in enumerate(rows[:50]):
        links = [value.strip() for key, value in row.items() if key.startswith("wikipedia_link_") and value and value.strip()]
        questions.append({"id": f"frames-{index:03d}", "kind": "factual", "source_row": index,
                          "question": row["Prompt"], "model_prompt": common + "\n\n" + row["Prompt"],
                          "reference_answer": row["Answer"], "reference_urls": links,
                          "reasoning_types": row.get("reasoning_types", "")})
    briefs = [
        ("local-research", "For a Windows developer building a private research assistant, compare local BM25, embedding retrieval, and live web search. Recommend an architecture for verifiable answers over changing public facts and private documents. Explain freshness, privacy, failure modes, operational complexity, and how to evaluate it without conflating retrieval and reasoning.", ["Explain which data leave the machine", "Address freshness and stale evidence", "Separate retrieval recall from answer correctness", "Recommend an implementable architecture"]),
        ("battery-storage", "Assess whether sodium-ion batteries can economically replace lithium iron phosphate batteries for stationary grid storage. Distinguish demonstrated commercial deployment from projected performance, discuss energy density, lifecycle and supply-chain tradeoffs, and give conditions under which each is preferable.", ["Distinguish deployed products from forecasts", "Compare lifecycle and energy density with units", "Discuss supply-chain and cost uncertainty", "Give conditional recommendations"]),
        ("rag-evaluation", "Design an evidence-based evaluation of a research assistant using FRAMES, SimpleQA and BrowseComp-style tasks. Explain which capabilities each measures, contamination and source leakage risks, citation verification, reproducible timing and cost, and a held-out protocol for iterative improvements.", ["Accurately distinguish benchmark scopes", "Discuss contamination and reference leakage", "Specify claim-level citation verification", "Separate development and held-out evaluation"]),
        ("heat-pumps", "Evaluate heat pumps versus gas boilers for an existing poorly insulated home in northern Europe. Identify the measurements needed before a decision, compare cold-weather behavior and whole-system costs, discuss electrical grid and refrigerant constraints, and avoid presenting one country's subsidies as universal.", ["Address building heat loss and emitter sizing", "Explain cold-weather efficiency", "Identify location-dependent costs and policies", "Provide a concrete decision process"]),
        ("browser-security", "Recommend a secure design for an AI research assistant that visits untrusted web pages and can also use local tools. Analyze prompt injection, credential leakage, downloads and irreversible actions. Compare isolation, provenance and permission approaches, and propose a useful test plan that includes failures.", ["Identify web-content authority confusion", "Propose concrete isolation and permission boundaries", "Address credentials and downloads", "Include adversarial failure tests"]),
    ]
    open_briefs = [{"id": f"brief-{i+1}", "kind": "open", "topic": topic, "question": question,
                    "model_prompt": common + "\n\nWrite at most 900 words. " + question,
                    "rubric_requirements": requirements} for i, (topic, question, requirements) in enumerate(briefs)]
    rubric = {
        "version": "c10-rubric-v1", "frozen_before_arm_runs": True,
        "arm_blinding": "Judge shuffled anonymized answers without provider identity, latency, usage or price; save per-answer rationales. Use identical judge prompt/model/version across arms.",
        "factual_accuracy": "Binary correct only if the substantive answer is semantically equivalent to the gold answer, includes all requested entities/quantities, and contains no contradictory asserted answer. Normalize formatting and equivalent units, not wrong facts. Abstentions, provider errors, empty or truncated answers count incorrect. Record the original gold and judge rationale. Exact normalized matches may be scored deterministically; all other answers require semantic judgment, never substring inclusion alone.",
        "citation_validity": "For every factual answer, enumerate all asserted answer-bearing claims and associated cited URLs. Fetch each URL and record status, final URL and content hash. A citation passes only if its content actually entails its associated claim; HTTP success alone is not support. No citation yields zero. Report supported claim fraction, reachable URL fraction and fraction of answers with all answer-bearing claims supported separately. Distinguish unreachable/blocked from contradicted and unsupported, and retain retrieved evidence excerpts.",
        "open_brief_scales": {
            "accuracy_0_to_4": ["0: mostly false or invented", "1: major factual errors", "2: generally plausible but important unsupported or incorrect claims", "3: accurate with minor omissions or qualified uncertainties", "4: accurate and complete on all brief requirements with no material unsupported assertion"],
            "citations_0_to_4": ["0: no usable supporting citations", "1: fewer than half of material claims supported", "2: at least half supported, major gaps remain", "3: most material claims supported by suitable direct sources", "4: all material factual claims supported, primary sources used where available, limitations of evidence explicit"],
            "decision_usefulness_0_to_4": ["0: fails task", "1: generic advice without tradeoffs", "2: addresses some requirements but weak actionable conclusion", "3: addresses all requirements and gives defensible conditional recommendation", "4: actionable recommendation with tradeoffs, uncertainties, decision-changing measurements and clear failure conditions"],
            "aggregate": "Mean of the three equally weighted scales; also publish all component scores. Cite factual evidence for every deducted accuracy point. Never reward verbosity alone."
        },
        "metrics": {
            "accuracy": "Correct factual answers / 50, including every scheduled case; no dropping failed requests.",
            "latency": "Wall-clock elapsed milliseconds from arm request start to final response including retrieval, retries, validation and cascade; report mean, p50, p95 and total.",
            "tokens": "Observed input, cached input, output and reasoning tokens from provider receipts; null with reason when unavailable. Retrieval-only tokens and judge tokens reported separately. Do not infer token counts from character counts.",
            "cost": "Actual metered USD when available; otherwise separately label token-rate estimate with price source/date or subscription marginal cash cost and unknown attributable plan cost. Missing price or usage is null, never zero. Report cost per correct answer only with a usable cost basis.",
            "retries": "Preserve all attempts and their overhead. Paired re-runs keep original panel/rubric unchanged. Do not use gold answers, benchmark source pages, or another arm's answer as research evidence.",
            "claims": "A 50-row development panel establishes only this panel. No general superiority claim without independent held-out evidence; compare quality, costs and latency separately."
        }
    }
    result = {"schema_version": 1, "benchmark": "FRAMES", "dataset": {
        "repository": "google/frames-benchmark", "source_url": BASE, "revision": REVISION,
        "data_url": f"{BASE}/resolve/{REVISION}/test.tsv", "license": "Apache-2.0",
        "license_evidence_url": f"{BASE}/blob/{REVISION}/README.md", "license_evidence": "Dataset author's README front matter declares license: apache-2.0; repository has no standalone LICENSE file at this revision.",
        "paper_url": "https://arxiv.org/abs/2409.12941", "citation": "Krishna et al. (2024), Fact, Fetch, and Reason: A Unified Evaluation of Retrieval-Augmented Generation, arXiv:2409.12941.",
        "source_sha256": hashlib.sha256(source).hexdigest(), "readme_sha256": hashlib.sha256(readme).hexdigest(), "download_bytes": len(source) + len(readme),
        "available_rows": len(rows), "selection": "First 50 TSV data rows in the pinned revision, preserving original order; no difficulty filtering, sampling or post-outcome replacement.",
        "selection_sha256": hashlib.sha256(canonical(questions)).hexdigest()},
        "prompt_boundary": "Only task.model_prompt is sent to a model; reference_answer, reference_urls, source metadata and rubric evaluation artifacts are never provided to research arms.",
        "questions": questions, "open_briefs": open_briefs, "rubric": rubric,
        "rubric_sha256": hashlib.sha256(canonical(rubric)).hexdigest()}
    result["panel_sha256"] = hashlib.sha256(canonical(result)).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "questions": len(questions), "open_briefs": len(open_briefs), "source_bytes": len(source), "panel_sha256": result["panel_sha256"]}))


if __name__ == "__main__":
    main()
