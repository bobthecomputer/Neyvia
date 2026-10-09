"""Reviewable test -> manual contract -> host check -> real receipt mapping."""
from __future__ import annotations
import json
from pathlib import Path
from .proof_contracts import REPO, declarations, file_digest, manifest_files, source_bindings, source_binding_digest

REVALIDATION = REPO / "scripts/evidence/PROOFS-b-revalidation.json"


def procedure_passed(result, identity):
    """Resolve a reviewed receipt pointer, rather than accepting a label."""
    if not identity or identity == "self_check":
        return result.get("ok") is True
    prefix, slash, name = identity.partition("/")
    collections = [prefix] if slash and prefix in {"cases", "checks", "procedures", "observers"} else ["procedures", "cases", "checks", "observers"]
    target = name if slash and prefix in collections else identity
    matches = [row for key in collections for row in result.get(key, [])
               if isinstance(row, dict) and row.get("id", row.get("contract")) == target]
    return len(matches) == 1 and (matches[0].get("ok") is True or matches[0].get("status") == "passed")


def revalidate_existing(receipt_path, *, exclude=()):
    """Refresh observed evidence without editing another track's coverage rows.

    Original receipt/manifest hashes still have to pass the ordinary admission
    gate. This records only a new source binding for unchanged claims, backed by
    a fresh execution of the same declared contracts.
    """
    receipt_path = Path(receipt_path).resolve()
    receipt_path.relative_to(REPO)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("sourceStable") is not True or receipt.get("sourceBindings") != source_bindings():
        raise ValueError("Revalidation requires a fresh source-bound real run")
    results = {r["area"]: r for r in receipt["areas"] if r.get("ok") is True}
    live = declarations()
    inventory = json.loads((REPO / "config/proofs/test-inventory.json").read_text(encoding="utf-8"))
    entries = {}
    for row in inventory["files"]:
        if row["path"] in exclude:
            continue
        for case in row["cases"]:
            if not case.get("contract_ids"):
                continue
            original = (REPO / case["self_checks"][0].partition("#")[0]).resolve()
            manifest = (REPO / case["manifest"]).resolve()
            original.relative_to(REPO)
            manifest.relative_to(REPO)
            if file_digest(original) != case["receipt_sha256"] or file_digest(manifest) != case["manifest_sha256"]:
                raise ValueError("Original evidence changed; cannot revalidate: " + case["id"])
            area = json.loads(manifest.read_text(encoding="utf-8"))["area"]
            result = results.get(area, {})
            observed = {r if isinstance(r, str) else r["id"] for r in result.get("contracts", [])
                        if isinstance(r, str) or r.get("status", "passed") == "passed"}
            if not set(case["contract_ids"]) <= observed & live.keys():
                raise ValueError("Fresh run did not observe unchanged coverage: " + case["id"])
            entries[case["id"]] = {"area": area, "contracts": case["contract_ids"],
                "checkedAt": case["checked_at"],
                "priorBinding": case.get("source_binding_sha256"), "manifestSha256": case["manifest_sha256"],
                "originalReceiptSha256": case["receipt_sha256"]}
    evidence = {"schema": "neyvia.proofs.revalidation.v1", "receipt": receipt_path.relative_to(REPO).as_posix(),
                "receiptSha256": file_digest(receipt_path), "cases": entries}
    from .durability import atomic_write_json
    atomic_write_json(REVALIDATION, evidence)
    return list(entries)


def revalidated_cases(current_sources):
    """Return only cases whose unchanged claim was freshly observed on this source."""
    if not REVALIDATION.is_file():
        return {}
    try:
        evidence = json.loads(REVALIDATION.read_text(encoding="utf-8"))
        path = (REPO / evidence["receipt"]).resolve()
        path.relative_to(REPO)
        if evidence["schema"] != "neyvia.proofs.revalidation.v1" or file_digest(path) != evidence["receiptSha256"]:
            return {}
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if receipt.get("sourceStable") is not True or receipt.get("sourceBindings") != current_sources:
            return {}
        results = {r["area"]: r for r in receipt["areas"] if r.get("ok") is True}
        accepted = {}
        for identity, row in evidence["cases"].items():
            observed = {r if isinstance(r, str) else r["id"] for r in results.get(row["area"], {}).get("contracts", [])
                        if isinstance(r, str) or r.get("status", "passed") == "passed"}
            if row["contracts"] and set(row["contracts"]) <= observed:
                accepted[identity] = row
        return accepted
    except (KeyError, TypeError, ValueError, OSError):
        return {}


def evidence_revalidated(case, rows):
    row = rows.get(case["id"], {})
    return (row.get("contracts") == case["contract_ids"]
            and row.get("checkedAt") == case["checked_at"]
            and row.get("priorBinding") == case.get("source_binding_sha256")
            and row.get("manifestSha256") == case.get("manifest_sha256")
            and row.get("originalReceiptSha256") == case.get("receipt_sha256"))


def record_coverage(receipt_path, *, paths=None, test_paths=None, tests=None, only_tests=None):
    if only_tests is not None:
        paths = set(only_tests) if paths is None else set(paths) & set(only_tests)
    if tests is not None:
        paths = set(tests) if paths is None else set(paths) & set(tests)
    if test_paths is not None:
        paths = set(test_paths) if paths is None else set(paths) & set(test_paths)
    receipt_path = Path(receipt_path).resolve()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("contractsOk") is not True:
        raise ValueError("Coverage requires a passing contract verification receipt")
    live = declarations()
    inventory_path = REPO / "config/proofs/test-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    results = {row["area"]: row for row in receipt["areas"] if row.get("ok") is True}
    if receipt.get("sourceStable") is not True or receipt.get("sourceBindings") != source_bindings():
        raise ValueError("Receipt is not bound to current proof source; run fresh verification")
    changed = []
    for manifest_path in manifest_files():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        area = manifest.get("area")
        if area not in results:
            continue
        result = results[area]
        observed = {item if isinstance(item, str) else item["id"] for item in result.get("contracts", [])
                    if isinstance(item, str) or item.get("status", "passed") == "passed"}
        for mapping in manifest.get("coverage", []):
            if paths is not None and mapping["test"] not in paths:
                continue
            ids = mapping["contracts"]
            if not ids or not set(ids) <= observed or not set(ids) <= live.keys():
                raise ValueError("Coverage has undeclared/unobserved contract: " + mapping["case"])
            if not mapping.get("checkedAt"):
                raise ValueError("Coverage has no production enforcement site")
            if not procedure_passed(result, mapping.get("procedure")):
                raise ValueError("Coverage procedure did not pass: " + mapping["case"])
            declared_sites = {site for identity in ids for site in live[identity]["checkedAt"]}
            if not set(mapping["checkedAt"]) <= declared_sites:
                raise ValueError("Coverage site differs from the executable manual contract: " + mapping["case"])
            source = next(row for row in inventory["files"] if row["path"] == mapping["test"])
            matches = [row for row in source["cases"] if row["id"] == mapping["case_id"]] if "case_id" in mapping else [row for row in source["cases"] if row["name"] == mapping["case"]]
            if len(matches) != 1:
                raise ValueError("Ambiguous or unknown case; supply its line-qualified case_id: " + mapping["case"])
            case = matches[0]
            case.update(contract_ids=ids, checked_at=mapping["checkedAt"],
                self_checks=[f"{receipt_path.relative_to(REPO).as_posix()}#areas/{area}/" + mapping.get("procedure", "self_check")],
                receipt_sha256=file_digest(receipt_path), manifest=manifest_path.relative_to(REPO).as_posix(),
                manifest_sha256=file_digest(manifest_path), classification="real-current",
                mapping_schema="neyvia.proofs.mapping.v2")
            case["source_binding_sha256"] = source_binding_digest(receipt["sourceBindings"])
            if mapping.get("supersededAssertions"):
                case["superseded_assertions"] = mapping["supersededAssertions"]
            if mapping.get("migrationNote"):
                case["migration_note"] = mapping["migrationNote"]
            case.pop("source_bindings", None)
            changed.append(case["id"])
            source["contract_ids"] = sorted({identity for c in source["cases"] for identity in c["contract_ids"]})
            source["checked_at"] = sorted({site for c in source["cases"] for site in c["checked_at"]})
            source["self_checks"] = sorted({site for c in source["cases"] for site in c["self_checks"]})
            complete = all(c["contract_ids"] and c["checked_at"] and c["self_checks"] for c in source["cases"])
            source.update(disposition="covered" if complete else "partial", reason="Executable manual contracts checked by production host; isolated real action receipts linked per case.")
    from .durability import atomic_write_json
    atomic_write_json(inventory_path, inventory)
    render_map(inventory)
    return changed


def revalidate_coverage(receipt_path):
    """Refresh action evidence without rewriting another track's inventory rows.

    The original receipt and manifest remain immutable. A fresh, source-bound
    run must observe the same contracts in the same registered proof area.
    This is evidence renewal, never permission to declare new coverage.
    """
    receipt_path = Path(receipt_path).resolve()
    receipt_path.relative_to(REPO)
    report = json.loads(receipt_path.read_text(encoding="utf-8"))
    if report.get("sourceStable") is not True or report.get("sourceBindings") != source_bindings():
        raise ValueError("Revalidation requires a fresh source-bound real run")
    areas = [row["area"] for row in report["areas"] if row.get("ok") is True]
    from .durability import atomic_write_json
    atomic_write_json(REPO / "config/proof-coverage-revalidation.json", {
        "schema": "neyvia.proofs.revalidation.v1", "receipt": receipt_path.relative_to(REPO).as_posix(),
        "sha256": file_digest(receipt_path), "areas": areas})
    return areas


def coverage_source_current(case, *, current_sources=None):
    """Check original binding or explicit renewal of those exact observed IDs."""
    current_sources = current_sources if current_sources is not None else source_bindings()
    binding = case.get("source_binding_sha256")
    if not binding and case.get("source_bindings"):
        binding = source_binding_digest(case["source_bindings"])
    original_path = (REPO / case["self_checks"][0].partition("#")[0]).resolve()
    manifest_path = (REPO / case["manifest"]).resolve()
    original_path.relative_to(REPO)
    manifest_path.relative_to(REPO)
    if (not binding or file_digest(original_path) != case["receipt_sha256"]
            or file_digest(manifest_path) != case["manifest_sha256"]):
        return False
    original_report = json.loads(original_path.read_text(encoding="utf-8"))
    if (original_report.get("sourceStable") is not True
            or binding != source_binding_digest(original_report.get("sourceBindings", {}))):
        return False
    if binding == source_binding_digest(current_sources):
        report = original_report
        renewal = {"areas": [row["area"] for row in report.get("areas", [])]}
    else:
        pointer = REPO / "config/proof-coverage-revalidation.json"
        if pointer.is_file():
            renewal = json.loads(pointer.read_text(encoding="utf-8"))
            path = (REPO / renewal["receipt"]).resolve()
            expected_hash = renewal["sha256"]
        elif evidence_revalidated(case, revalidated_cases(current_sources)):
            renewal = json.loads(REVALIDATION.read_text(encoding="utf-8"))
            path = (REPO / renewal["receipt"]).resolve()
            expected_hash = renewal["receiptSha256"]
            renewal["areas"] = [row["area"] for row in renewal["cases"].values()]
        else:
            return False
        path.relative_to(REPO)
        if file_digest(path) != expected_hash:
            return False
        report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("sourceStable") is not True or report.get("sourceBindings") != current_sources:
        return False
    manifest = json.loads((REPO / case["manifest"]).read_text(encoding="utf-8"))
    area = manifest["area"]
    result = next((row for row in report["areas"] if row["area"] == area and row.get("ok") is True), None)
    if result is None or area not in renewal["areas"]:
        return False
    observed = {row if isinstance(row, str) else row["id"] for row in result.get("contracts", [])
                if isinstance(row, str) or row.get("status", "passed") == "passed"}
    live = declarations()
    expected = {row["id"]: row for row in manifest.get("contracts", [])}
    for identity in case["contract_ids"]:
        if identity not in live or identity not in expected:
            return False
        original, current = expected[identity], live[identity]
        def canonical(value):
            try:
                return value.encode("cp1252").decode("utf-8")
            except (UnicodeError, AttributeError):
                return value
        if any(canonical(original.get(key)) != canonical(current.get(key))
               for key in ("phase", "claim", "impact")):
            return False
        if set(original["checkedAt"]) != set(current["checkedAt"]):
            return False
    sites = {site for identity in case["contract_ids"] for site in live[identity]["checkedAt"]}
    procedure = case["self_checks"][0].partition("#areas/" + area + "/")[2]
    sites_current = set(case["checked_at"]) <= sites
    if not sites_current and not case.get("mapping_schema"):
        # Original mappings also named whole self-check procedures and action
        # facades. Preserve those immutable reviewed links; never grant this
        # compatibility path to a newly recorded v2 mapping.
        original_rows = [row for row in manifest.get("coverage", [])
                         if row["test"] == case["id"].partition("::")[0]
                         and (row.get("case_id") == case["id"] if row.get("case_id") else row["case"] == case["name"])]
        sites_current = (len(original_rows) == 1
                         and set(original_rows[0]["checkedAt"]) == set(case["checked_at"])
                         and set(original_rows[0]["contracts"]) == set(case["contract_ids"])
                         and original_rows[0].get("procedure", "self_check") == procedure)
    return (set(case["contract_ids"]) <= observed and sites_current
            and procedure_passed(result, procedure))


def retirement_gate(paths):
    inventory = json.loads((REPO / "config/proofs/test-inventory.json").read_text(encoding="utf-8"))
    live = declarations()
    current_sources = source_bindings()
    current_binding_digest = source_binding_digest(current_sources)
    refreshed = revalidated_cases(current_sources)
    authorized = []
    for text in paths:
        row = next(r for r in inventory["files"] if r["path"] == text)
        path = (REPO / text).resolve()
        path.relative_to(REPO)
        if not row["cases"] or row["disposition"] != "covered" or file_digest(path) != row["sha256"]:
            raise ValueError("Retirement requires complete coverage and unchanged original: " + text)
        for case in row["cases"]:
            if not case["contract_ids"] or not set(case["contract_ids"]) <= live.keys() or not case["checked_at"] or not case["self_checks"]:
                raise ValueError("Uncovered case: " + case["id"])
            receipt_path = REPO / case["self_checks"][0].partition("#")[0]
            if file_digest(receipt_path) != case["receipt_sha256"] or file_digest(REPO / case["manifest"]) != case["manifest_sha256"]:
                raise ValueError("Coverage evidence changed; record a fresh real run: " + case["id"])
            if not coverage_source_current(case, current_sources=current_sources):
                raise ValueError("Proof source changed; record fresh coverage: " + case["id"])
        authorized.append(path)
    return authorized


def render_map(inventory=None):
    if inventory is None:
        inventory = json.loads((REPO / "config/proofs/test-inventory.json").read_text(encoding="utf-8"))
    files = inventory["files"]
    total = sum(len(row["cases"]) for row in files)
    mapped = sum(bool(c["contract_ids"] and c["checked_at"] and c["self_checks"]) for row in files for c in row["cases"])
    deleted = sum(not (REPO / row["path"]).exists() for row in files)
    lines = ["# Tests to proofs coverage map", "", f"Baseline `{inventory['baseline_commit']}`; {len(files)} scoped files, {total} static case definitions.",
        f"Verified mappings: {mapped}/{total} ({100*mapped/total:.3f}%); deleted files: {deleted}.",
        "Counts are AST definitions, not expanded parametrized executions. Four overwritten planner methods remain explicitly recorded.",
        "A pending row is not permission to delete. Source assertions and missing imports alone do not prove dead code.",
        "Unchanged prior rows may be rebound to current source by scripts/evidence/PROOFS-b-revalidation.json; original receipt and manifest hashes remain enforced.", "",
        "| Original test / case | Disposition | Manual contract | Host check | Scratch receipt |", "|---|---|---|---|---|"]
    clean = lambda value: str(value).replace("|", "\\|").replace("\n", " ")
    for row in files:
        covered = [c for c in row["cases"] if c["contract_ids"]]
        if not covered:
            lines.append(f"| `{row['path']}` ({len(row['cases'])} cases) | {row['disposition']} | — | — | — |")
        else:
            for case in row["cases"]:
                disposition = "covered" if case["contract_ids"] else "pending"
                if case.get("migration_note"):
                    disposition += "; " + case["migration_note"]
                if not case["contract_ids"] and case.get("pending_reason"):
                    disposition += "; " + case["pending_reason"]
                lines.append("| " + " | ".join(clean(x) for x in [f"{row['path']}::{case['name']}", disposition,
                    ", ".join(case["contract_ids"]) or "—", "; ".join(case["checked_at"]) or "—", "; ".join(case["self_checks"]) or "—"]) + " |")
    (REPO / "docs/evidence/tests-to-proofs.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    inventory["totals"].update(mapped_case_definitions=mapped, coverage_percent=round(100*mapped/total, 3), deleted_files=deleted)
    from .durability import atomic_write_json
    atomic_write_json(REPO / "config/proofs/test-inventory.json", inventory)
