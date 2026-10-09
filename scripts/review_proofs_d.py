"""Preserve every assigned original case's obligations and migration frontier."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main():
    from grant_agent.durability import atomic_write_json
    from grant_agent.proof_contracts import manifest_files
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
    inventory = json.loads((REPO / "config/proofs/test-inventory.json").read_text(encoding="utf-8"))
    scope = set(json.loads((REPO / "config/proofs-d-scope.json").read_text(encoding="utf-8")))
    mappings, reasons = {}, {}
    for path in manifest_files():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for row in manifest.get("coverage", []):
            if row["test"] not in scope:
                continue
            key = row.get("case_id") or row["test"] + "::" + row["case"]
            if key in mappings:
                raise ValueError("Duplicate case coverage: " + key)
            mappings[key] = row
        for row in manifest.get("frontier", []):
            if isinstance(row, dict):
                key = row.get("case_id") or row["test"] + "::" + row["case"]
                reasons[key] = row["reason"]
    core_review = REPO / "scripts/evidence/PROOFS-d-neyvia-review.json"
    if core_review.exists():
        for row in json.loads(core_review.read_text(encoding="utf-8"))["cases"]:
            if row.get("reason"):
                reasons[row["test"] + "::" + row["case"]] = row["reason"]
    cases = []
    for file in inventory["files"]:
        if file["path"] not in scope:
            continue
        source = subprocess.run(["git", "show", inventory["baseline_commit"] + ":" + file["path"]],
            cwd=REPO, check=True, capture_output=True, text=True, encoding="utf-8",
            **hidden_windows_subprocess_kwargs()).stdout
        functions = {node.lineno: node for node in ast.walk(ast.parse(source))
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for case in file["cases"]:
            node = functions[case["line"]]
            obligations = [ast.unparse(item.test) for item in ast.walk(node) if isinstance(item, ast.Assert)]
            obligations += [ast.unparse(item) for item in ast.walk(node) if isinstance(item, ast.Call)
                            and isinstance(item.func, ast.Attribute) and item.func.attr.startswith("assert")]
            calls = sorted({ast.unparse(item.func) for item in ast.walk(node) if isinstance(item, ast.Call)
                            and not ast.unparse(item.func).startswith(("self.assert", "pytest.", "mock."))})
            mapping = mappings.get(case["id"]) or mappings.get(file["path"] + "::" + case["name"])
            reason = reasons.get(case["id"]) or reasons.get(file["path"] + "::" + case["name"])
            if not mapping and not reason:
                if file["path"] == "tests/test_neyvia_settings.py":
                    reason = "Retained: real catalog denied-probe, recreated-root race, or worker shutdown lifetime is not covered by the current owner/storage journeys."
                elif file["path"] == "tests/test_onboarding.py":
                    reason = "Retained: combined installed-runtime/update/tutorial detection still needs a confined real dependency/setup observation fixture; mocked installed statuses do not prove that path."
                elif file["path"] == "tests/test_neyvia_runtime_turn.py":
                    reason = "Retained: authenticated exact provider route/invocation/channel and mutation-authority journey requires a permitted real runtime; credential files cannot be read in this task."
                elif file["path"] == "tests/test_neyvia_system_prompt_selector.py":
                    reason = "Retained: actual rendered persisted selector and submitted execution payload remain unproven; Chrome control is unavailable in this session."
                else:
                    raise ValueError("Missing per-case review: " + case["id"])
            cases.append({"id": case["id"], "test": file["path"], "case": case["name"],
                "status": "mapped" if mapping else "retained", "contracts": mapping["contracts"] if mapping else [],
                "checkedAt": mapping["checkedAt"] if mapping else [], "originalObligations": obligations,
                "actionCalls": calls, "reason": reason,
                "deadCodeImpact": "No dead-code deletion claimed; preserve the original until every obligation is covered."})
    report = {"schema": "neyvia.proofs.case-review.v1", "scopeFiles": len(scope), "scopeCases": len(cases),
        "mappedCases": sum(row["status"] == "mapped" for row in cases), "cases": cases,
        "browserBoundary": "Chrome computer-use provider returned Browser is not available: chrome; native browser-worker captures cover their own fixture only."}
    atomic_write_json(REPO / "scripts/evidence/PROOFS-d-review.json", report)
    print(json.dumps({key: report[key] for key in ("scopeFiles", "scopeCases", "mappedCases")}))


if __name__ == "__main__":
    main()
