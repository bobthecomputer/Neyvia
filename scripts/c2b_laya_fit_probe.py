"""One bounded representation comparison on fitting observations only."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import statistics
import sys
import time
import urllib.request


def main():
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "src"))
    import importlib.util
    frozen = importlib.util.spec_from_file_location("grant_agent.laya_client.fit_probe_projection", repo / "scripts/evidence/C2b-fit-probe-browser_client.py")
    module = importlib.util.module_from_spec(frozen)
    frozen.loader.exec_module(module)
    project_grounded_state, grounded_action_instructions = module.project_grounded_state, module.grounded_action_instructions
    source = repo / "scripts/evidence/C2b-decisions-attempt1.jsonl"
    fitting = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()
               if line.strip() and json.loads(line)["split"] == "calibration" and json.loads(line).get("family") == "grounded_action"]
    results, ambiguous = [], []
    for case in fitting:
        obs = json.loads((repo / case["provenance"]["observation_path"]).read_text(encoding="utf-8"))
        elements = {e["id"]: e for e in obs["elements"]}
        key = lambda control: (control["role"], " ".join(control["name"].split()))
        names = Counter(key(e) for e in obs["elements"] if e.get("enabled") and not e.get("secret") and "click" in e.get("actions", []))
        check = case["expected_check"]
        target, other = elements[check["element"]], elements[check["alternative"]]
        if names[key(target)] != 1 or names[key(other)] != 1:
            ambiguous.append(case["id"])
            continue
        descriptions = {control["id"]: f'Click {key(control)[0]} "{key(control)[1]}".' for control in (target, other)}
        goal = descriptions[target["id"]]
        options = [{**option, "description": descriptions[option["args"]["element"]]} for option in case["options"]]
        context = {"goal": goal, "options": options, "decision_profile": "public_named_controls@2"}
        state = project_grounded_state(obs, context)
        question = {"type": "choice", "instructions": grounded_action_instructions(goal, context["decision_profile"]),
                    "criteria": {o["id"]: o["description"] for o in options},
                    "view": ["goal", "controls", "current", "progress", "action_receipts"]}
        started = time.perf_counter()
        request = urllib.request.Request("http://127.0.0.1:48724/v1/decide", json.dumps({"state": state, "questions": {"decision": question}}).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            value = json.load(response)
        answer = value["answers"]["decision"]
        results.append({**case, "state": state, "goal": goal, "options": options, "question": question,
                        "decision_profile": context["decision_profile"], "response": value,
                        "prediction": answer["answer"], "confidence": answer["top_probability"],
                        "correct": answer["answer"] == case["gold"], "http_ms": (time.perf_counter()-started)*1000})
    thresholds = []
    for threshold in sorted({row["confidence"] for row in results}):
        accepted = [row for row in results if row["confidence"] >= threshold]
        if len(accepted) >= 20 and statistics.mean(row["correct"] for row in accepted) >= .95:
            thresholds.append({"threshold": threshold, "accepted": len(accepted), "correct": sum(row["correct"] for row in accepted)})
    best = max(thresholds, key=lambda value: value["accepted"], default=None)
    result = {"schema": "neyvia.C2b-action-fit-probe@1", "fitting_only": True, "heldout_read": False,
              "original_fitting_actions": len(fitting), "ambiguous_normalized_role_names": ambiguous,
              "evaluated": len(results), "accuracy": statistics.mean(row["correct"] for row in results) if results else None,
              "acceptance_candidate": best, "rows": results,
              "scope": "Explicit role/name intent, symmetric actual control evidence chunks, unchanged g3-c2 weights; no action execution"}
    output = repo / "scripts/evidence/C2b-laya-action-fit-probe.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}))


if __name__ == "__main__":
    main()
