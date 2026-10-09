"""Run independent real Luna trials in the same workspace DB as the app."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from grant_agent.evolver_core import EvolverEngine
from grant_agent.evolver_domains import DomainEvaluator, Luna, domain_spec, propose, token_count
from grant_agent.evolver_domains_v2 import ReviewedEvaluator, domain_spec_v2, propose_v2
from grant_agent.evolver_domains_v3 import domain_spec_v3, selected_candidate_v3
from grant_agent.evolver_transport_v3 import ClosedBookLuna


class TaskIdentityLuna(Luna):
    """Constrain response identity to request metadata; never rewrite answers."""
    def ask(self, prompt, *, label, schema=None):
        if schema and "id" in schema.get("properties", {}) and "\nTASK\n" in prompt:
            task = json.loads(prompt.rsplit("\nTASK\n", 1)[1])
            schema = json.loads(json.dumps(schema))
            schema["properties"]["id"] = {"type": "string", "const": task["id"]}
        return super().ask(prompt, label=label, schema=schema)


def discovery_feedback(engine, domain_id, current, spec):
    """Only training observations may inform the next wording proposal."""
    if not domain_id.startswith("cl_skill") or not current["receipts"]:
        return None
    candidate = current["receipts"][-1]["candidate"]
    panels = {panel["id"] for panel in spec["panels"] if panel["role"] == "discovery"}
    failed = []
    with engine._db() as db:
        for row in db.execute("SELECT panel,item,result FROM observations WHERE domain=? AND genome=?", (domain_id, candidate)):
            if row["panel"] not in panels:
                continue
            observed = json.loads(row["result"])
            if observed["objectives"]["success"] >= 1:
                continue
            adherence = observed["receipt"]["judge"].get("adherence", {})
            judgements = adherence.get("judgements", {})
            failed.append({"case": row["item"], "success": observed["objectives"]["success"],
                           "missingJudgements": sorted(set(judgements.get("required", [])) - set(judgements.get("answered", {}))),
                           "failedChecks": [check["name"] for check in adherence.get("results", []) if check["status"] == "fail"]})
    if not failed:
        return None
    from grant_agent.cl_skill import _parse_skill
    original = _parse_skill(REPO / "manuals/skills/design-craft.cl")
    required = sorted({step.split()[1].split("=")[0] for steps in original.procedures.values() for step in steps if step.startswith("J ")})
    return {"source": "original frozen CL-Skill plus discovery observations only", "priorCandidate": candidate,
            "discoveryPanels": sorted(panels), "failures": failed,
            "requiredJudgements": {name: original.judges[name]["options"] for name in required},
            "constraint": "Preserve original exact CL judgement names/options and the required procedure choices in the compressed document. Wording may change. Do not invent protocol identifiers or options."}


def run(root, domain, max_trials=1, output_path=None):
    root = Path(root).resolve()
    if root != REPO and REPO not in root.parents:
        raise ValueError("Evolution root must remain within this owned worktree")
    # A dev backend exports its UI state root to children. Evaluation fixtures
    # must each own their Notes folder/state, otherwise concurrent pairs mutate
    # one shared folder selector. Network policy remains explicitly main-root.
    os.environ.pop("NEYVIA_UI_STATE_ROOT", None)
    os.environ.pop("NEYVIA_UI_BACKEND_URL", None)
    engine = EvolverEngine(root / ".neyvia/evolver.sqlite3")
    luna = ClosedBookLuna(root) if domain == "cl_skill_v3" else TaskIdentityLuna(root)
    domains = [domain] if domain != "all" else ["manual_compression_v2", "cl_skill_v3"]
    summary = {"schema": "neyvia.evolver-real-run/v1", "started": time.time(), "root": str(root),
               "model": "gpt-6-luna", "sampling": "Independent CLI call per case; task seeds paired, provider sampling not seedable",
               "tokenEncoding": "o200k_base reference, distinct from provider reported usage", "domains": {}}
    output = Path(output_path).resolve() if output_path else root / ".neyvia/evolver-last-run.json"
    if root not in output.parents:
        raise ValueError("Output must remain within the run root")
    output.parent.mkdir(parents=True, exist_ok=True)
    for domain_id in domains:
        version3 = domain_id == "cl_skill_v3"
        reviewed = domain_id.endswith("_v2") or version3
        spec = (domain_spec_v3 if version3 else domain_spec_v2 if reviewed else domain_spec)(domain_id)
        domain_luna = ClosedBookLuna(root) if version3 else luna
        # Establishment hashes judge source, original checks and disjoint panels
        # before ANY candidate proposal is requested.
        engine.establish_domain(domain_id, judges=spec["judges"], panels=spec["panels"], objectives=spec["objectives"], promotion=spec["promotion"],
                                hard_gates=["authority"] if domain_id.startswith("manual_compression") else ["judgeDecided", "artifactAuthority"])
        initial = engine.register_genome(domain_id, {"kind": "text", "text": spec["baseline"]}, provenance={"source": "original rendered Notes manual" if domain_id.startswith("manual_compression") else "original design-craft CL-Skill"})
        state = engine.status(domain_id)["domains"][0]
        if not state.get("incumbent"):
            engine.set_incumbent(domain_id, initial["id"])
        details = {"baseline": initial["id"], "baselineTokens": token_count(spec["baseline"]), "trials": []}
        summary["domains"][domain_id] = details
        evaluator = (ReviewedEvaluator if reviewed else DomainEvaluator)(root, domain_id, domain_luna)
        for trial_number in range(1, max_trials + 1):
            current = engine.status(domain_id)["domains"][0]
            if current["trials"] >= current["budget"]["max_trials"]:
                details["state"] = current
                details["budgetExhausted"] = True
                break
            incumbent_id = current["incumbent"]
            incumbent = engine._genome(domain_id, incumbent_id)
            actual_trial_number = current["trials"] + 1
            feedback = None if version3 else discovery_feedback(engine, domain_id, current, spec)
            brief = incumbent["text"] + ("\n\nTRAINING-ONLY DISCOVERY FEEDBACK\n" + json.dumps(feedback) if feedback else "")
            text, proposal_receipt = selected_candidate_v3() if version3 else (propose_v2 if reviewed else propose)(domain_luna, domain_id, brief, actual_trial_number)
            candidate = engine.register_genome(domain_id, {"kind": "text", "text": text}, parent_id=incumbent_id,
                                               operator="discovery-qualified-transport-transfer" if version3 else "luna-wording-structure", provenance={"proposal": proposal_receipt, "discoveryOnly": True,
                                                                                              "trainingFeedback": feedback})
            print(json.dumps({"domain": domain_id, "phase": "candidate", "candidate": candidate["id"], "tokensBefore": token_count(incumbent["text"]), "tokensAfter": token_count(text)}), flush=True)
            result = engine.evaluate_candidate(domain_id, candidate["id"], evaluator.__call__)
            details["trials"].append(result)
            details["state"] = engine.status(domain_id)
            output.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
            print(json.dumps({"domain": domain_id, "phase": "finished", "state": result["state"], "promoted": result["promoted"], "error": result.get("error")}), flush=True)
            if result["state"] == "blocked":
                break
    summary["finished"] = time.time()
    output.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--domain", choices=["all", "manual_compression", "cl_skill", "manual_compression_v2", "cl_skill_v2", "cl_skill_v3", "paul_intent", "manual_json_local_v1"], default="all")
    parser.add_argument("--max-trials", type=int, choices=[1, 2], default=1)
    parser.add_argument("--output")
    args = parser.parse_args()
    if os.environ.get('NEYVIA_PROOF_CREDENTIAL_GUARD') == '1':
        from grant_agent.proof_credential_guard import install
        from grant_agent.subprocess_utils import install_hidden_subprocess_default
        install(Path(args.root)); install_hidden_subprocess_default()
    try:
        if args.domain == "manual_json_local_v1":
            from grant_agent.evolver_manual_local import run as run_local_manual
            run_local_manual(args.root, args.max_trials, args.output)
        elif args.domain == "paul_intent":  # R2: the manual of Paul, tuned on his real messages
            from grant_agent.evolver_paul_intent import run as run_paul_intent
            summary = run_paul_intent(args.root, args.max_trials)
            summary["domains"] = {"paul_intent": {"trials": summary["trials"]}}  # the job reader expects per-domain trials
            if args.output:
                Path(args.output).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            run(args.root, args.domain, args.max_trials, args.output)
    except Exception as exc:
        print(json.dumps({"state": "blocked", "errorType": type(exc).__name__, "error": str(exc)}), flush=True)
        raise SystemExit(1)
