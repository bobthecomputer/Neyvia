"""Real Sol challenge of a matching quote attached to a false claim (F6)."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.autopilot_model import decide
from grant_agent.research_hops import CHECK, PREFIX, claim_grounding_gate, claim_grounding_prompt, windows
from grant_agent.research_pipeline import captured_quote
from grant_agent.cl.turn_context import TurnContext
from grant_agent.transition_memory import atomic_json
from run_c10_research import price


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-proof", required=True)
    args = parser.parse_args()
    path = (REPO / args.native_proof).resolve()
    if not path.is_relative_to(REPO / "scripts/evidence"):
        parser.error("Owned native evidence only")
    proof = json.loads(path.read_text(encoding="utf-8"))
    source_receipt = Path(proof["receiptPath"])
    research = json.loads(source_receipt.read_text(encoding="utf-8"))
    cited = research["answer"]["citations"][0]
    source = next(s for s in research["sources"] if s["url"] == cited["url"])
    actual_path = Path(source["receiptPath"])
    actual = json.loads(actual_path.read_text(encoding="utf-8"))["projection"]
    observed = {**source, "fullText": actual["text"], "tables": actual.get("tables", [])}
    passages = windows(observed, "Harriet Lane mother Jane Buchanan", limit=2600)
    passage = next(p for p in passages if captured_quote(p["quoteText"], cited["quote"], minimum=6))
    question = "What mother does this public source identify for Harriet Lane?"
    plan = {"hops": [{"id": "mother", "question": question, "dependsOn": [], "query": "Harriet Lane mother"}],
            "calculation": "None", "answerFormat": "Name stated in the source"}
    directory = REPO / "scripts/evidence/C10c-grounding"
    results = []
    for name, false in [("supported", False), ("false-claim-matching-quote", True)]:
        candidate = {"answer": "Mary Todd Lincoln" if false else research["answer"]["answer"],
                     "explanation": "The cited source identifies this person as Harriet Lane's mother.",
                     "citations": [{**cited, "claim": "Harriet Lane's mother was Mary Todd Lincoln." if false else cited["claim"]}]}
        spec = json.loads(json.dumps(CHECK))
        spec["properties"]["claims"]["items"]["properties"]["passages"]["items"] = {"enum": [passage["id"]]}
        spec["properties"]["hopCoverage"]["items"] = {"enum": ["mother"]}
        context = TurnContext(question, PREFIX, token_budget=5500, archive_dir=directory / name / "context")
        context.append("user", claim_grounding_prompt(plan, [], candidate, [passage]))
        model = decide(context.prompt(), spec, directory / name, model="gpt-6.1-sol", timeout=120,
                       developer_instructions=PREFIX)
        bindings = [{"claim": candidate["citations"][0]["claim"], "passage": passage["id"]}]
        accepted = claim_grounding_gate(model["answer"], plan, {passage["id"]}, candidate, bindings)
        results.append({"case": name, "literalQuoteExists": bool(captured_quote(passage["quoteText"], cited["quote"])),
                        "groundingAccepted": accepted, "expected": not false, "candidate": candidate,
                        "actualPassage": passage, "model": model, "cost": price([model])})
    proof = {"schema": "neyvia.C10c.F6.v1", "passed": all(r["groundingAccepted"] == r["expected"] and r["literalQuoteExists"] for r in results),
        "sourceNativeProof": str(path.relative_to(REPO)), "actualSourceReceipt": str(actual_path),
        "actualSourceSha256": hashlib.sha256(actual_path.read_bytes()).hexdigest(),
        "groundingSourceSha256": hashlib.sha256((REPO / "src/grant_agent/research_hops.py").read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        "results": results, "boundary": "Actual captured public source and real Sol judgments through production prompt and gate; matching quotation attached to a false claim must fail"}
    atomic_json(REPO / "scripts/evidence/C10c-grounding.json", proof)
    print(json.dumps({"passed": proof["passed"], "cases": [{"case": r["case"], "quoteExists": r["literalQuoteExists"], "accepted": r["groundingAccepted"]} for r in results]}))
    if not proof["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
