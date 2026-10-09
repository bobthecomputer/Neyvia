"""Register six frozen domains and score actual three-task Luna captures.

Future disjoint four-case panels are configured; they are not scored by this
receipt replay. Paired statistical candidate promotion remains intentionally
unexecuted because three real tasks do not satisfy that evidence boundary.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.evolver_core import EvolverEngine
from grant_agent.workflow_evolver import establish_workflow_domain, LiveWorkflowRunner, WorkflowEvaluator
from grant_agent.workflow_panels import frozen_panels
from grant_agent.workflow_manuals import STAGES

DEST = REPO / "scripts/evidence/MS-runs/manuals"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class CapturedWorkflowRunner:
    """Evidence replay, never a substitute for fresh candidate model execution."""
    def __init__(self, identity, tasks):
        self.identity, self.tasks = identity, {t["id"]: t for t in tasks}

    def __call__(self, genome_text, item, seed):
        if item["id"] not in self.tasks:
            raise ValueError("Configured future panel needs fresh provider execution; no captured answer exists")
        directory = DEST / item["id"] / "with-reviewed"
        result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
        receipt_path = directory / "receipt.json"
        provider = json.loads(receipt_path.read_text(encoding="utf-8"))
        if digest(receipt_path) != result["providerReceiptSha256"]:
            raise ValueError("Captured provider receipt changed")
        if hashlib.sha256(genome_text.encode()).hexdigest() != result["sourceSha256"]:
            raise ValueError("Candidate genome was not the manual source used in the captured call")
        events_path = directory / "events.jsonl"
        events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        completed = [e for e in events if e.get("type") == "turn.completed"]
        messages = [e["item"]["text"] for e in events if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "agent_message"]
        usage = completed[-1].get("usage", {}) if completed else {}
        actual_tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        if (not provider.get("passed") or not completed or not messages
                or json.loads(messages[-1]) != result["answer"] or actual_tokens != result["tokens"]):
            raise ValueError("Actual provider event trace does not support captured answer")
        return {"report": result["answer"], "outcomeQuality": result["outcomeQuality"],
                "tokens": result["tokens"], "evidence": self.tasks[item["id"]]["evidence"],
                "providerReceipt": {**provider, "raw": str(events_path), "rawSha256": digest(events_path)}}


def main():
    panel_path = DEST / "panel.json"
    tasks = json.loads(panel_path.read_text(encoding="utf-8"))["tasks"]
    engine = EvolverEngine(REPO / ".agent_control/MS-evolver/evolver.sqlite3")
    domains, configured = [], {}
    for identity in STAGES:
        selected = [t for t in tasks if t["manual"] == identity]
        paths = [panel_path]
        for task in selected:
            paths.extend(DEST / task["id"] / "with-reviewed" / name
                         for name in ("result.json", "receipt.json", "events.jsonl", "prompt.txt"))
        if not all(p.is_file() for p in paths):
            raise ValueError(f"Reviewed real captures not complete for {identity}")
        captured_runner = CapturedWorkflowRunner(identity, selected)
        runner = LiveWorkflowRunner(identity, REPO / ".agent_control/MS-evolver/live-evaluations")
        panels = frozen_panels(identity)
        configured[identity] = panels
        frozen_sources = [Path(__file__), REPO / "src/grant_agent/workflow_evolver.py",
                          REPO / "src/grant_agent/workflow_panels.py", REPO / "src/grant_agent/workflow_manuals.py",
                          REPO / "manuals/cl" / (identity + ".cl"), *paths]
        version = hashlib.sha256(json.dumps(panels, sort_keys=True).encode()
                                 + "".join(digest(p) for p in frozen_sources).encode()).hexdigest()[:12]
        registered = establish_workflow_domain(engine, identity, panels, runner, version=version, judge_files=[*paths, Path(__file__)])
        text = (REPO / "manuals/cl" / (identity + ".cl")).read_text(encoding="utf-8")
        evaluations = [WorkflowEvaluator(identity, captured_runner)({"kind": "text", "text": text}, task, 7301)
                       for task in selected]
        if not all(e["hard_gates"]["real_provider_receipt"] for e in evaluations):
            raise ValueError("Provider authenticity boundary failed")
        status = engine.status(registered["domain"])["domains"][0]
        domains.append({"manual": identity, "domain": registered["domain"], "seed": registered["seed"],
                        "frozenLock": status["frozen_lock"], "judgeHashes": status["judge_hashes"],
                        "adapterEvaluations": evaluations, "statisticalTrials": status["trials"],
                        "liveEvaluator": "grant_agent.workflow_evolver.LiveWorkflowRunner",
                        "promotionExecuted": False})
    config = REPO / "config/evolver/workflows.panels.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps(configured, indent=2) + "\n", encoding="utf-8")
    receipt = {"schema": "neyvia.MS-evolver.v1", "domains": domains,
               "boundary": "Six registered, frozen CL text domains; eighteen actual Luna capture adapter evaluations; future panels unexecuted; no promotion"}
    (REPO / "scripts/evidence/MS-evolver.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"registered": len(domains), "actualAdapterEvaluations": sum(len(d["adapterEvaluations"]) for d in domains), "promotionExecuted": False}))


if __name__ == "__main__":
    main()
