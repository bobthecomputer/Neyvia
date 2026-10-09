"""Reject semantically ambiguous recorded action goals before corpus grading."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    kept, rejected = [], []
    for row in rows:
        if row.get("family") == "grounded_action":
            raw = (repo / row["provenance"]["observation_path"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != row["provenance"]["observation_sha256"]:
                raise ValueError("Recorded observation identity changed")
            obs = json.loads(raw)
            safe = [e for e in obs["elements"] if e.get("enabled") and not e.get("secret") and "click" in e.get("actions", [])]
            key = lambda control: (control["role"], " ".join(control["name"].split()))
            counts = Counter(key(e) for e in safe)
            elements = {e["id"]: e for e in safe}
            check = row["expected_check"]
            targets = [elements[check["element"]], elements[check["alternative"]]]
            if any(counts[key(control)] != 1 for control in targets):
                rejected.append({"id": row["id"], "split": row["split"], "reason": "normalized_role_name_is_not_unique_in_actual_safe_controls", "controls": [key(e) for e in targets]})
                continue
        kept.append(row)
    args.output.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in kept)+"\n", encoding="utf-8")
    receipt = {"schema": "neyvia.C2b-corpus-validity@1", "input_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
               "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(), "input": len(rows), "retained": len(kept),
               "rejected": rejected, "rule": "Actual observation semantic uniqueness only; no model predictions or confidence inspected",
               "caveat": "Validity repair of an already observed corpus; does not create a fresh holdout or confer deployment promotion"}
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"retained": len(kept), "rejected": len(rejected), "by_split": dict(Counter(row["split"] for row in kept))}))


if __name__ == "__main__":
    main()
