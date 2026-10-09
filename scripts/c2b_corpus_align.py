"""Align recorded real action rows with the exact deployed CPU projection."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "src"))
    from grant_agent.laya_client.browser_client import project_grounded_state, grounded_action_instructions
    from c2b_laya_evaluate import ADVISORY_FIELDS
    rows = [json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines() if line.strip()]
    count = 0
    for row in rows:
        instructions = row["question"]["instructions"]
        if row.get("family") in {"evidence", "readiness"} and instructions in ADVISORY_FIELDS:
            raw = (repo / row["provenance"]["observation_path"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != row["provenance"]["observation_sha256"]:
                raise ValueError("Original advisory observation identity changed")
            obs = json.loads(raw)
            field = ADVISORY_FIELDS[instructions]
            from urllib.parse import urlsplit
            expected = urlsplit(obs["url"]).hostname if field == "hostname" else obs[field]
            if row["question"]["criteria"][row.get("gold", row.get("expected"))] != expected:
                raise ValueError("Advisory gold differs from the actual independent native field")
            row["advisory_field"] = field
            row["decision_profile"] = "public_observed_fields@1"
            row["state"] = project_grounded_state(obs, {"decision_profile": row["decision_profile"]})
            row["question"]["view"] = ["page", "controls", "current"]
        if row.get("family") != "grounded_action":
            continue
        raw = (repo / row["provenance"]["observation_path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["provenance"]["observation_sha256"]:
            raise ValueError("Original observation identity changed")
        obs = json.loads(raw)
        check, gold = row["expected_check"], row.get("gold", row.get("expected"))
        targets = (check["element"], check["alternative"])
        if targets[0] == targets[1]:
            raise ValueError("Action alternatives must be distinct actual controls")
        elements = {element["id"]: element for element in obs["elements"]}
        for target in targets:
            control = elements[target]
            if not control.get("enabled") or control.get("secret") or check["action"] not in control.get("actions", []):
                raise ValueError("Action corpus must retain actual enabled non-secret controls")
        criteria = row["question"]["criteria"]
        if len(criteria) != 2 or gold not in criteria:
            raise ValueError("This narrow profile needs two observed candidates")
        options = [{"id": key, "description": description,
                    "args": {"element": targets[0] if key == gold else targets[1], "action": check["action"]}}
                   for key, description in criteria.items()]
        for option in options:
            actual = elements[option["args"]["element"]]
            if actual.get("name") not in option["description"]:
                raise ValueError("Candidate description does not retain its observed control name")
        context = {"goal": row["goal"], "options": options, "decision_profile": row["decision_profile"]}
        row["state"] = project_grounded_state(obs, context)
        row["options"] = options
        row["question"]["instructions"] = grounded_action_instructions(row["goal"])
        row["question"]["view"] = ["goal", "controls", "current", "progress", "action_receipts"]
        row["projection_profile"] = "exact BrowserClient.project_grounded_state"
        count += 1
    args.cases.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows)+"\n", encoding="utf-8")
    print(json.dumps({"rows": len(rows), "aligned_actual_action_rows": count}))


if __name__ == "__main__":
    main()
