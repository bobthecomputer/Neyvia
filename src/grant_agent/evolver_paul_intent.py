"""Evolver domain ``paul_intent``: tune the manual of Paul's model view on his real messages.

Genome: the manual brief text the host injects at intent time (paul_manual.brief(level=2)).
Task: GPT-6 Luna reads one real long message of Paul with the frozen prompt frame plus the
genome and returns a checklist; the frozen deterministic judge (paul_intent_judge) scores it.
Discovery panels are labelled training messages; held-out panels are the ten messages that
were never used to write the manual. A promotion changes only the workspace incumbent; a
human copies an accepted brief back into manuals/cl/working-with-paul.cl.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .evolver_domains import CONFIG, Luna, ModelFailure, token_count
from .paul_intent_judge import CASES, CHECKLIST_SCHEMA, judge, load_cases

DOMAIN = "paul_intent"
FRAME = CONFIG / "paul_intent.frame.txt"
PANELS = CONFIG / "paul_intent.panels.json"
TRANSPORT = ("Closed-book task. Do not use tools, read files or delegate. Return only JSON that matches the schema "
             "(items with ask, quote, kind, doneWhen, status, needsPaul; dropped; questions).\n\n")


def build_panels() -> list[dict]:
    """Four disjoint panels of five gold cases: two discovery, two held-out."""
    cases = list(load_cases().values())
    panels = []
    for role, split in (("discovery", "discovery"), ("held_out", "heldout")):
        chosen = sorted((c for c in cases if c["split"] == split), key=lambda c: c["date"])
        for index in range(2):
            panels.append({"id": f"{split}-{'ab'[index]}", "role": role,
                           "items": [{"id": c["id"]} for c in chosen[index::2]]})
    return panels


def domain_spec() -> dict:
    from .paul_manual import brief
    return {"baseline": brief(level=2), "panels": json.loads(PANELS.read_text(encoding="utf-8")),
            "judges": [str(Path(__file__).resolve()), str(Path(judge.__code__.co_filename).resolve()),
                       str(CASES), str(FRAME), str(PANELS)],
            "objectives": {"success": {"direction": "max", "tolerance": 0.0, "noise": 0.0},
                           "tokens": {"direction": "min", "tolerance": 0.0, "noise": 0.0}},
            "promotion": {"alpha": 0.05, "min_pairs": 5, "max_trials": 2, "max_evaluations": 80,
                          "max_seconds": 3600, "seed": 1821},
            "hard_gates": ["answered"]}


def score(result: dict) -> float:
    """One number per case: asks found with one item each, minus a quarter per misread, floored at zero."""
    return max(0.0, result["foundStrict"] / result["asks"] - 0.25 * result["misreads"])


class PaulIntentEvaluator:
    def __init__(self, root, luna: Luna):
        self.root, self.luna = Path(root), luna
        self.cases = load_cases()
        self.frame = FRAME.read_text(encoding="utf-8")

    def __call__(self, genome, item, seed):
        case = self.cases[item["id"]]
        text = genome["text"]
        prompt = TRANSPORT + self.frame.replace("{manual}", text).replace("{text}", case["text"])
        answer, receipt = self.luna.ask(prompt, label=f"paul-intent-{case['id']}-{hashlib.sha256(text.encode()).hexdigest()[:8]}",
                                        schema=CHECKLIST_SCHEMA)
        judged = judge(case, answer)
        return {"objectives": {"success": score(judged), "tokens": float(token_count(text))},
                "hard_gates": {"answered": not judged["emptyChecklist"]},
                "receipt": {"model": receipt, "taskId": case["id"], "panel": item.get("panel"), "seed": seed,
                            "answer": answer, "judge": judged,
                            "tokenEncoding": "o200k_base reference encoding, not provider native"}}


def propose(luna: Luna, incumbent: str, trial: int, feedback: list[dict]) -> tuple[str, dict]:
    """Luna rewrites the brief from discovery feedback only; held-out cases are never shown."""
    prompt = ("Return only JSON {\"text\": \"replacement document\"}. Do not use tools or delegate.\n"
              "The document below teaches a model how to read Paul's long dictated messages into a checklist of asks. "
              "Rewrite it to be shorter and clearer while keeping every rule that helped, its [p/n] odds and every judgement point. "
              "Do not invent rules or odds. Fix what the training failures show.\n"
              "TRAINING FAILURES (discovery panels only)\n" + json.dumps(feedback, ensure_ascii=False)
              + f"\nTRIAL {trial}\nINCUMBENT\n" + incumbent)
    answer, receipt = luna.ask(prompt, label=f"paul-intent-proposal-{trial}",
                               schema={"type": "object", "properties": {"text": {"type": "string"}},
                                       "required": ["text"], "additionalProperties": False})
    if not isinstance(answer.get("text"), str) or not answer["text"].strip():
        raise ModelFailure("Luna proposed an empty brief")
    return answer["text"], receipt


def discovery_feedback(engine, current, spec) -> list[dict]:
    panels = {p["id"] for p in spec["panels"] if p["role"] == "discovery"}
    genome = current["incumbent"]
    rows = []
    with engine._db() as db:
        for row in db.execute("SELECT panel,item,result FROM observations WHERE domain=? AND genome=?", (DOMAIN, genome)):
            if row["panel"] in panels:
                judged = json.loads(row["result"])["receipt"]["judge"]
                rows.append({"case": row["item"], "missing": judged["missing"], "violated": judged["violated"],
                             "mishears": [m["heard"] for m in judged["mishears"]]})
    return rows


def run(root, max_trials=1, output=None) -> dict:
    """Establish the frozen domain (idempotent), seed the incumbent and run bounded paired trials."""
    import time
    from .evolver_core import EvolverEngine
    root = Path(root).resolve()
    engine = EvolverEngine(root / ".neyvia/evolver.sqlite3")
    spec = domain_spec()
    engine.establish_domain(DOMAIN, judges=spec["judges"], panels=spec["panels"], objectives=spec["objectives"],
                            promotion=spec["promotion"], hard_gates=spec["hard_gates"])
    seed = engine.register_genome(DOMAIN, {"kind": "text", "text": spec["baseline"]},
                                  provenance={"source": "manuals/working-with-paul.manual.json brief level 2"})
    if not engine.status(DOMAIN)["domains"][0].get("incumbent"):
        engine.set_incumbent(DOMAIN, seed["id"])
    luna = Luna(root)
    evaluator = PaulIntentEvaluator(root, luna)
    summary = {"schema": "neyvia.evolver-real-run/v1", "domain": DOMAIN, "model": "gpt-6-luna", "started": time.time(),
               "baseline": seed["id"], "baselineTokens": token_count(spec["baseline"]), "trials": []}
    for _ in range(max_trials):
        current = engine.status(DOMAIN)["domains"][0]
        if current["trials"] >= current["budget"]["max_trials"]:
            summary["budgetExhausted"] = True
            break
        number = current["trials"] + 1
        incumbent = engine._genome(DOMAIN, current["incumbent"])["text"]
        text, proposal = propose(luna, incumbent, number, discovery_feedback(engine, current, spec))
        candidate = engine.register_genome(DOMAIN, {"kind": "text", "text": text}, parent_id=current["incumbent"],
                                           operator="luna-brief-rewrite", provenance={"proposal": proposal, "discoveryOnly": True})
        summary["trials"].append(engine.evaluate_candidate(DOMAIN, candidate["id"], evaluator.__call__))
    summary["state"] = engine.status(DOMAIN)
    summary["finished"] = time.time()
    if output:
        Path(output).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary
