"""Execute each registered workflow's fresh candidate evaluator once on Luna."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.evolver_core import EvolverEngine
from grant_agent.workflow_evolver import LiveWorkflowRunner, establish_workflow_domain
from grant_agent.workflow_manuals import STAGES
from grant_agent.workflow_panels import frozen_panels


def run(identity):
    folder = REPO / "scripts/evidence/MS-runs/evolver-live" / identity
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "proof.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    panels = frozen_panels(identity)
    runner = LiveWorkflowRunner(identity, folder / "provider")
    engine = EvolverEngine(REPO / ".agent_control/MS-evolver-live" / identity)
    domain = establish_workflow_domain(engine, identity, panels, runner,
                                      version="live", judge_files=[Path(__file__)])
    genome = {"kind": "text", "text": (REPO / f"manuals/cl/{identity}.cl").read_text(encoding="utf-8")}
    item = panels[0]["items"][0]
    measured = domain["evaluator"](genome, item, 17)
    result = {"manual": identity, "domain": domain["domain"], "genome": domain["seed"],
              "item": item, "measurement": measured,
              "sourceSha256": hashlib.sha256(genome["text"].encode()).hexdigest(),
              "promotionExecuted": False}
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"manual": identity, "hardGates": measured["hard_gates"], "adherence": measured["workflow"]["adherence"]}), flush=True)
    if not all(measured["hard_gates"].values()):
        raise RuntimeError("Fresh evaluator did not produce a real provider receipt")
    return result


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, STAGES))
    path = REPO / "scripts/evidence/MS-evolver-live.json"
    path.write_text(json.dumps({"schema": "neyvia.ms.evolver-live.v1", "domains": results,
                               "freshEvaluations": len(results), "promotionExecuted": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
