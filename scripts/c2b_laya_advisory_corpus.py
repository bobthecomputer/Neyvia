"""Freeze supported metadata decisions from fresh public native observations."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit


def main():
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "src"))
    from grant_agent.laya_client.browser_client import project_grounded_state
    from c2b_laya_evaluate import ADVISORY_FIELDS, advisory_eligible
    evidence = repo / "scripts/evidence"
    fitting = [json.loads(line) for line in (evidence/"C2b-decisions-valid-repair.jsonl").read_text(encoding="utf-8").splitlines()
               if line.strip() and json.loads(line)["split"] == "calibration" and advisory_eligible(json.loads(line))]
    if len(fitting) != 40:
        raise ValueError("Freeze the original ten fitting pages and four supported schemas")
    actions = [json.loads(line) for line in (evidence/"C2b-action-decisions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    pages = {}
    for row in actions:
        if row["split"] != "heldout":
            raise ValueError("Fresh document capture is held-out only")
        pages.setdefault(row["group"], row["provenance"])
    facts = []
    for page_index, (group, provenance) in enumerate(pages.items()):
        raw = (repo / provenance["observation_path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != provenance["observation_sha256"]:
            raise ValueError("Fresh native observation hash mismatch")
        obs = json.loads(raw)
        state = project_grounded_state(obs, {"decision_profile": "public_observed_fields@1"})
        for index, (instructions, field) in enumerate(ADVISORY_FIELDS.items()):
            gold = urlsplit(obs["url"]).hostname if field == "hostname" else obs[field]
            wrong = {"title": "An unrelated password reset page", "hostname": "example.invalid",
                     "url": "https://example.invalid/private", "readyState": "loading" if gold == "complete" else "complete"}[field]
            if gold == wrong:
                raise ValueError("Fresh metadata alternatives cannot be identical")
            swapped = (index + page_index) % 2 == 0
            criteria = {"a": wrong, "b": gold} if swapped else {"a": gold, "b": wrong}
            facts.append({"id": group+"-advisory-"+field, "split": "heldout", "domain": "browser",
                          "family": "readiness" if field == "readyState" else "evidence", "group": group,
                          "decision_profile": "public_observed_fields@1", "advisory_field": field,
                          "provenance": provenance, "state": state, "goal": instructions,
                          "question": {"type": "choice", "instructions": instructions, "criteria": criteria,
                                       "view": ["page", "controls", "current"]},
                          "gold": "b" if swapped else "a", "expected_check": {"field": field, "equals": gold,
                              "source": "independently checked actual native observation; no model output used"}})
    computer = [json.loads(line) for line in (evidence/"C2b-computer-decisions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = fitting+actions+facts+computer
    output = evidence/"C2b-decisions-advisory.jsonl"
    output.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows)+"\n", encoding="utf-8")
    print(json.dumps({"fitting": len(fitting), "fresh_action": len(actions), "fresh_advisory": len(facts),
                      "historical_computer": len(computer), "heldout_total": len(actions)+len(facts)+len(computer), "path": str(output)}))


if __name__ == "__main__":
    main()
