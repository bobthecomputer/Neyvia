"""Write an honest incomplete C7e deadline receipt from sealed family work."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
STATUSES = {"passed", "failed", "blocked"}


def _load_inventory(path, *, check_fixture=False):
    """Load and integrity-check the receipt-backed case denominator."""
    raw = Path(path).resolve()
    raw.relative_to((REPO / "scripts/evidence").resolve())
    data = json.loads(raw.read_bytes())
    from grant_agent.edge_fixture_catalog import BUILDERS
    from grant_agent.proof_contracts import source_digest
    if data.get("schema") != "neyvia.c7e-case-inventory.v1":
        raise ValueError("Unsupported C7e case inventory")
    families = data.get("families")
    if not isinstance(families, list) or {item.get("family") for item in families} != set(BUILDERS):
        raise ValueError("Case inventory must contain exactly the registered families")
    ids = set()
    family_by_name = {}
    for item in families:
        name = item["family"]
        cases = item.get("cases")
        if not isinstance(cases, list) or item.get("casesTotal") != len(cases):
            raise ValueError("Invalid case inventory total: " + name + " (" + str(item.get("casesTotal")) + "/" + str(len(cases) if isinstance(cases, list) else "not-list") + ")")
        if not isinstance(item.get("plannedCasesTotal", 0), int) or not 0 <= item.get("plannedCasesTotal", 0) <= len(cases):
            raise ValueError("Invalid planned case count: " + name)
        for case in cases:
            identity = case.get("id")
            if not isinstance(identity, str) or not identity or identity in ids:
                raise ValueError("Missing or duplicate inventory case ID: " + str(identity))
            ids.add(identity)
        refs = item.get("receipts", [])
        if not refs and not item.get("plannedSource"):
            raise ValueError("Inventory family lacks receipt/source provenance: " + name)
        module_source = item.get("moduleSource")
        if module_source:
            source_path = (REPO / module_source["path"]).resolve()
            source_path.relative_to(REPO)
            expected_owner = REPO / 'src' / (BUILDERS[name].replace('.', '/') + '.py')
            if not check_fixture and source_path != expected_owner.resolve():
                raise ValueError("Family inventory binds a different owner: " + name)
            if source_digest(source_path) != module_source.get("sha256"):
                raise ValueError("Family case inventory source changed: " + name)
        elif not check_fixture or item.get("plannedSource", {}).get("kind") != "check-only":
            raise ValueError("Production inventory family lacks a module source binding: " + name)
        planned_source = item.get("plannedSource", {})
        if planned_source.get("path"):
            source_path = (REPO / planned_source["path"]).resolve()
            source_path.relative_to(REPO)
            if source_digest(source_path) != planned_source.get("sha256"):
                raise ValueError("Planned case declaration source changed: " + name)
        definitions = {case["id"]: case for case in cases}
        for ref in refs:
            receipt = (REPO / ref["path"]).resolve()
            receipt.relative_to((REPO / ".agent_control/proofs/c7").resolve())
            receipt_bytes = receipt.read_bytes()
            if hashlib.sha256(receipt_bytes).hexdigest() != ref.get("sha256"):
                raise ValueError("Historical inventory receipt changed: " + name)
            receipt_data = json.loads(receipt_bytes)
            if receipt_data.get("family") != name:
                raise ValueError("Inventory receipt family mismatch: " + name)
            if module_source and receipt_data.get("sourceBindings", {}).get(module_source["path"]) != module_source["sha256"]:
                from build_C7e_case_inventory import compatible_history
                declared_generation = item.get('inventoryGeneration')
                if name not in {'c7d-desktop', 'c7d-control-completion'} or not declared_generation:
                    raise ValueError("Inventory receipt is not bound to its declared family source: " + name)
                actual_generation = compatible_history(module_source['path'], receipt_data['sourceBindings'][module_source['path']])
                if actual_generation != declared_generation:
                    raise ValueError('Historical case-generation signature differs: ' + name)
            for row in receipt_data.get("rows", []):
                case = definitions.get(row.get("id"))
                if case is None or row.get("category") != case.get("category"):
                    raise ValueError("Historical receipt case differs from inventory: " + name)
        family_by_name[name] = item

    authority_path = REPO / "scripts/evidence/C7d-authority.json"
    authority_bytes = authority_path.read_bytes()
    authority = json.loads(authority_bytes)
    declared = []
    for field, family, contract in (
        ("originalAuthorityBlockers", "scheduler", "a-cli.scheduler.capabilities"),
        ("additionalAuthorityBlockers", "c7d-control-completion", "control.chrome-live-action"),
    ):
        rows = authority.get(field, [])
        if len(rows) != 8 or any(row.get("contract") != contract for row in rows):
            raise ValueError("Authority inventory is not the exact eight-case declaration: " + field)
        authority_cases = family_by_name[family].get("authorityCases", [])
        expected = sorted((row["contract"], row["category"], row.get("neededAuthority")) for row in rows)
        observed = sorted((row.get("contract"), row.get("category"), row.get("neededAuthority")) for row in authority_cases)
        if observed != expected:
            raise ValueError("Family authority cases differ from C7d-authority.json: " + family)
        declared.extend((family, row) for row in rows)
    for family, entry in family_by_name.items():
        if family not in {"scheduler", "c7d-control-completion"} and entry.get("authorityCases", []):
            raise ValueError("Unexpected authority cases assigned to family: " + family)
    if data.get("authoritySha256") != hashlib.sha256(authority_bytes).hexdigest():
        raise ValueError("C7d authority source changed")
    if "authorityCasesTotal" in data and data["authorityCasesTotal"] != len(declared):
        raise ValueError("Authority case total differs from exact declarations")
    fixture_total = sum(item["casesTotal"] for item in families)
    if "fixtureCasesTotal" in data and data["fixtureCasesTotal"] != fixture_total:
        raise ValueError("Fixture case inventory total differs")
    if "casesTotal" in data and data["casesTotal"] != fixture_total + len(declared):
        raise ValueError("Combined C7e case inventory total differs")
    return family_by_name, declared


def _report(port, roots, inventory_path=None, *, check_fixture=False):
    from grant_agent.edge_fixture_catalog import BUILDERS, completed_receipts

    if inventory_path is None:
        inventory_path = REPO / "scripts/evidence/C7e-case-inventory.json"
    inventory, authority_cases = _load_inventory(inventory_path, check_fixture=check_fixture)

    if isinstance(roots, (str, Path)):
        roots = [roots]
    roots = [Path(root).resolve() for root in roots]
    if not roots:
        raise ValueError("At least one proof root is required")
    receipt_by_family = {}
    progress = {}
    seen_progress_files = set()
    proof_root = (REPO / ".agent_control/proofs/c7").resolve()
    for root in roots:
        root.relative_to(proof_root)
        fixture_root = root / "semantic-fixtures"
        receipts = completed_receipts(fixture_root) if (fixture_root / "families.json").is_file() else []
        for entry in receipts:
            family = entry["family"]
            if family not in BUILDERS:
                raise ValueError("Unknown completed family: " + family)
            previous = receipt_by_family.get(family)
            if previous:
                if previous["sha256"] == entry["sha256"]:
                    continue
                raise ValueError("Conflicting source-current receipts for family: " + family)
            raw = json.loads(Path(entry["path"]).read_bytes())
            rows = raw["rows"]
            if any(row.get("status") not in STATUSES for row in rows):
                raise ValueError("Invalid status in completed receipt: " + family)
            receipt_by_family[family] = {
                "family": family,
                "path": Path(entry["path"]).resolve().relative_to(REPO).as_posix(),
                "sha256": entry["sha256"],
                "cases": len(rows),
                "counts": {status: Counter(row["status"] for row in rows)[status] for status in sorted(STATUSES)},
            }

        for path in sorted(fixture_root.glob("*/case-progress.jsonl")):
            family = path.parent.name
            if family not in BUILDERS:
                continue
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            identity = (str(path.resolve()), digest)
            if identity in seen_progress_files:
                continue
            seen_progress_files.add(identity)
            aggregate = progress.setdefault(family, {"counts": Counter(), "files": []})
            aggregate["files"].append({"path": path.resolve().relative_to(REPO).as_posix(),
                                        "sha256": digest, "bytes": len(raw)})
            for line in raw.decode("utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                case = item.get("case")
                if isinstance(case, dict) and case.get("status") in STATUSES:
                    aggregate["counts"][case["status"]] += 1

    diagnostics = {
        family: {"family": family,
                 "counts": {status: aggregate["counts"][status] for status in sorted(STATUSES)},
                 "files": aggregate["files"], "completionReceipt": False}
        for family, aggregate in progress.items() if family not in receipt_by_family
    }
    diagnostic_families = set(diagnostics)

    authority_path = REPO / "scripts/evidence/C7d-authority.json"
    authority_bytes = authority_path.read_bytes()
    authority = json.loads(authority_bytes)
    family_states = []
    for family in BUILDERS:
        if family in receipt_by_family:
            state = "completed_source_current"
        elif family in diagnostic_families:
            state = "in_progress_unsealed"
        else:
            state = "pending_unobserved"
        counts = receipt_by_family.get(family, {}).get("counts", {})
        inventory_family = inventory[family]
        expected_cases = {case["id"]: case for case in inventory_family["cases"]}
        receipt = receipt_by_family.get(family)
        if receipt:
            current = json.loads((REPO / receipt["path"]).read_bytes())["rows"]
            actual_cases = {row.get("id"): row for row in current}
            if len(actual_cases) != len(current) or set(actual_cases) != set(expected_cases):
                raise ValueError("Current receipt case IDs differ from the exact family inventory: " + family)
            for identity, row in actual_cases.items():
                expected = expected_cases[identity]
                if row.get("category") != expected.get("category"):
                    raise ValueError("Current receipt case definition differs from inventory: " + identity)
        tally = {status: counts.get(status, 0) for status in ("passed", "failed", "blocked")}
        planned = inventory_family.get("plannedCasesTotal", 0)
        built_unverified = 0 if receipt else len(expected_cases) - planned
        unbuilt = 0 if receipt else planned
        authority_total = sum(owner == family for owner, _ in authority_cases)
        family_state = {"family": family, "state": state,
                              "casesTotal": len(expected_cases) + authority_total,
                              "fixtureCasesTotal": len(expected_cases),
                              "authorityCasesTotal": authority_total,
                              "passing": tally["passed"], "failing": tally["failed"],
                              "blocked": tally["blocked"] + authority_total,
                              "builtUnverified": built_unverified, "unbuilt": unbuilt,
                              "counts": tally, "notYetBuilt": unbuilt}
        if sum(family_state[key] for key in ("passing", "failing", "blocked", "builtUnverified", "unbuilt")) != family_state["casesTotal"]:
            raise ValueError("Family numeric case accounting does not sum: " + family)
        family_states.append(family_state)

    historical_recovery = []
    for category in ('empty', 'huge', 'unicode', 'concurrency', 'interrupted', 'stale'):
        path = REPO / 'scripts/evidence/C7e-sync-recovery' / (category + '.json')
        raw = path.read_bytes()
        value = json.loads(raw)
        if value.get('priorStatus') != 'failed' or value.get('case', {}).get('status') != 'passed':
            raise ValueError('Historical native recovery closure differs: ' + category)
        historical_recovery.append({'category': category,
                                    'path': path.relative_to(REPO).as_posix(),
                                    'sha256': hashlib.sha256(raw).hexdigest()})
    current_recovery = []
    recovery_receipt = receipt_by_family.get('c7d-control-completion')
    if recovery_receipt:
        current_recovery = [row for row in json.loads((REPO / recovery_receipt['path']).read_bytes())['rows']
                            if 'adapters.sync.recovery' in row.get('contracts', [])]

    return {
        "schema": "neyvia.c7e-deadline.v1", "ok": True, "complete": False,
        "fixturesComplete": False, "fixtureCompletion": "not_claimed",
        "explicitPort": port, "sourceCurrent": True,
        "proofRoots": [root.relative_to(REPO).as_posix() for root in roots],
        "proofIndexes": [{"path": path.relative_to(REPO).as_posix(),
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                         for root in roots
                         if (path := root / 'semantic-fixtures/families.json').is_file()],
        "completedFamilies": len(receipt_by_family), "familyReceipts": list(receipt_by_family.values()),
        "completedReceiptCounts": dict(Counter(
            status for entry in receipt_by_family.values() for status, count in entry["counts"].items()
            for _ in range(count))),
        "familyStates": family_states,
        "caseTotals": {"casesTotal": sum(row["casesTotal"] for row in family_states),
                       "passing": sum(row["passing"] for row in family_states),
                       "failing": sum(row["failing"] for row in family_states),
                       "blocked": sum(row["blocked"] for row in family_states),
                       "builtUnverified": sum(row["builtUnverified"] for row in family_states),
                       "unbuilt": sum(row["unbuilt"] for row in family_states)},
        "caseInventory": {"path": Path(inventory_path).resolve().relative_to(REPO).as_posix(),
                          "sha256": hashlib.sha256(Path(inventory_path).read_bytes()).hexdigest()},
        "unsealedCaseProgress": list(diagnostics.values()),
        "unsealedDiagnosticsAreCompletionEvidence": False,
        "originalAuthorityBlockers": authority["originalAuthorityBlockers"],
        "additionalAuthorityBlockers": authority["additionalAuthorityBlockers"],
        "authorityReceipt": {"path": authority_path.relative_to(REPO).as_posix(),
                             "sha256": hashlib.sha256(authority_bytes).hexdigest()},
        "nativeRecovery": {"historicalFailures": 6, "historicalClosures": historical_recovery,
                           "currentCases": len(current_recovery),
                           "currentCounts": dict(Counter(row['status'] for row in current_recovery)),
                           "currentCaseIds": [row['id'] for row in current_recovery],
                           "familyReceipt": recovery_receipt,
                           "boundary": "Six historical failures stay separate. Current counts use only the selected source-current full family; no NAS or remote peers."},
        "boundary": "Incomplete deadline receipt. Counts include only completed source-current family receipts. Unsealed case-progress rows are diagnostics and do not establish completion.",
    }


def _check():
    """Exercise completion boundaries against disposable metadata only."""
    from grant_agent.edge_fixture_catalog import BUILDERS

    scratch_parent = REPO / ".agent_control/proofs/c7"
    cases = []

    def record(case_id, action, expected):
        try:
            actual = action()
        except Exception as exc:
            actual = type(exc).__name__
        passed = expected(actual)
        cases.append({"id": case_id, "status": "passed" if passed else "failed"})
        assert passed, case_id + ": " + repr(actual)

    with tempfile.TemporaryDirectory(prefix="c7e-deadline-check-", dir=scratch_parent) as temp, \
            tempfile.TemporaryDirectory(prefix="c7e-inventory-check-", dir=REPO / "scripts/evidence") as inventory_temp:
        scratch = Path(temp) / "proof"
        fixtures = scratch / "semantic-fixtures"
        family = next(iter(BUILDERS))
        folder = fixtures / family
        folder.mkdir(parents=True)
        receipt = folder / (family + ".receipt.json")
        sealed_payload = {"family": family, "sourceStable": True, "sourceBindings": {}, "rows": [
            {"id": "scratch.pass", "status": "passed"}, {"id": "scratch.block", "status": "blocked"}]}
        receipt.write_text(json.dumps(sealed_payload), encoding="utf-8")
        sealed_bytes = receipt.read_bytes()
        digest = hashlib.sha256(receipt.read_bytes()).hexdigest()
        index = fixtures / "families.json"
        index.write_text(json.dumps([
            {"family": family, "path": str(receipt), "sha256": digest, "sourceStable": True}]), encoding="utf-8")
        (folder / "case-progress.jsonl").write_text(json.dumps({"diagnostic": True,
            "completionReceipt": False, "case": {"id": "scratch.partial", "status": "passed"}}) + "\n", encoding="utf-8")
        authority_bytes = (REPO / "scripts/evidence/C7d-authority.json").read_bytes()
        authority = json.loads(authority_bytes)
        inventory_families = []
        family2 = list(BUILDERS)[1]
        history = Path(temp) / "history"
        history.mkdir()
        history_receipt = history / (family2 + ".receipt.json")
        history_payload = {"family": family2, "rows": [{"id": "scratch.pending", "category": None,
                            "contracts": [], "status": "passed"}]}
        history_receipt.write_text(json.dumps(history_payload), encoding="utf-8")
        for name in BUILDERS:
            if name == family:
                case_defs = [{"id": row["id"], "category": row.get("category"), "contracts": row.get("contracts", [])}
                             for row in sealed_payload["rows"]]
                refs = [{"path": receipt.resolve().relative_to(REPO).as_posix(), "sha256": digest}]
                planned = 0
            elif name == family2:
                case_defs = [{"id": "scratch.pending", "category": None, "contracts": []}]
                refs = [{"path": history_receipt.resolve().relative_to(REPO).as_posix(),
                         "sha256": hashlib.sha256(history_receipt.read_bytes()).hexdigest()}]
                planned = 0
            else:
                case_defs = [{"id": "planned:" + name, "category": None, "contracts": []}]
                refs = []
                planned = 1
            authority_rows = []
            if name == "scheduler":
                authority_rows = [{"contract": row["contract"], "category": row["category"], "neededAuthority": row.get("neededAuthority")} for row in authority["originalAuthorityBlockers"]]
            if name == "c7d-control-completion":
                authority_rows = [{"contract": row["contract"], "category": row["category"], "neededAuthority": row.get("neededAuthority")} for row in authority["additionalAuthorityBlockers"]]
            inventory_families.append({"family": name, "cases": case_defs, "casesTotal": len(case_defs),
                                       "plannedCasesTotal": planned, "plannedSource": {"kind": "check-only"},
                                       "receipts": refs, "authorityCases": authority_rows})
        inventory_value = {"schema": "neyvia.c7e-case-inventory.v1", "families": inventory_families,
                           "authoritySha256": hashlib.sha256(authority_bytes).hexdigest()}
        inventory_path = Path(inventory_temp) / "inventory.json"
        inventory_path.write_text(json.dumps(inventory_value), encoding="utf-8")
        record("c7e.deadline.synthetic-inventory-refused", lambda: _load_inventory(inventory_path),
               lambda value: value == "ValueError")
        from build_C7e_case_inventory import generation_signature
        declared = 'IDS = {"owned"}\ndef effect():\n return 1\ndef run():\n return IDS\n'
        record('c7e.inventory.effect-change-is-not-case-generation',
               lambda: generation_signature(declared) == generation_signature(declared.replace('return 1', 'return 2')),
               lambda value: value is True)
        record('c7e.inventory.generation-change-refused',
               lambda: generation_signature(declared) == generation_signature(declared.replace('return IDS', 'return []')),
               lambda value: value is False)
        record('c7e.inventory.declaration-change-refused',
               lambda: generation_signature(declared) == generation_signature(declared.replace('"owned"', '"different"')),
               lambda value: value is False)
        # Source bindings use normalized UTF-8 text on Windows; receipt bytes
        # still use their exact raw digest.
        from grant_agent.proof_contracts import source_digest
        declared_source = Path(temp) / 'declared.py'
        declared_source.write_bytes(b'IDS = {"owned"}\r\n')
        selected = inventory_value['families'][2]
        previous = dict(selected)
        reference = {'path': declared_source.relative_to(REPO).as_posix(),
                     'sha256': source_digest(declared_source)}
        selected.update(moduleSource=reference, plannedSource={**reference, 'kind': 'declared_not_built'})
        inventory_path.write_text(json.dumps(inventory_value), encoding='utf8')
        record("c7e.deadline.crlf-declaration-binding", lambda: _load_inventory(inventory_path, check_fixture=True),
               lambda value: len(value[0]) == len(BUILDERS))
        selected['plannedSource']['sha256'] = hashlib.sha256(declared_source.read_bytes()).hexdigest()
        inventory_path.write_text(json.dumps(inventory_value), encoding='utf8')
        record("c7e.deadline.raw-source-digest-refused", lambda: _load_inventory(inventory_path, check_fixture=True),
               lambda value: value == 'ValueError')
        selected.clear(); selected.update(previous)
        inventory_path.write_text(json.dumps(inventory_value), encoding='utf8')
        report = _report(48741, [scratch], inventory_path, check_fixture=True)
        record("c7e.deadline.sealed-counts", lambda: report["completedReceiptCounts"],
               lambda value: value == {"passed": 1, "blocked": 1})
        record("c7e.deadline.unsealed-excluded", lambda: report["unsealedCaseProgress"],
               lambda value: value == [])
        record("c7e.deadline.sealed-family-numeric", lambda: report["familyStates"][0],
               lambda value: value["casesTotal"] == 2 and value["passing"] == 1 and value["failing"] == 0
               and value["blocked"] == 1 and value["builtUnverified"] == 0 and value["unbuilt"] == 0)
        record("c7e.deadline.pending-built-unverified", lambda: report["familyStates"][1],
               lambda value: value["passing"] == 0 and value["failing"] == 0 and value["builtUnverified"] == 1
               and value["unbuilt"] == 0 and value["casesTotal"] == 1)

        # Tampering with a sealed artifact must refuse the index entry.
        receipt.write_text(json.dumps({"family": family, "sourceStable": True,
                                       "sourceBindings": {}, "rows": []}), encoding="utf-8")
        record("c7e.deadline.corrupt-receipt-refused", lambda: _report(48741, [scratch], inventory_path, check_fixture=True),
               lambda value: value == "ValueError")

        # Root escape is an explicit refusal boundary.
        record("c7e.deadline.out-of-scope-root-refused", lambda: _report(48741, [REPO], inventory_path, check_fixture=True),
               lambda value: value == "ValueError")

        # An unsealed-only family reports diagnostics with raw integrity metadata,
        # zero sealed counts, and historical cases as built-unverified.
        receipt.write_bytes(sealed_bytes)
        index.write_text("[]", encoding="utf-8")
        (folder / "case-progress.jsonl").write_text(json.dumps({"diagnostic": True,
            "completionReceipt": False, "case": {"id": "scratch.partial", "status": "passed"}}) + "\n", encoding="utf-8")
        diagnostic_report = _report(48741, [scratch], inventory_path, check_fixture=True)
        row = next(item for item in diagnostic_report["familyStates"] if item["family"] == family)
        diagnostic = diagnostic_report["unsealedCaseProgress"][0]
        record("c7e.deadline.unsealed-file-reference", lambda: (row, diagnostic),
               lambda value: row["unbuilt"] == 0 and row["builtUnverified"] == 2 and row["counts"] == {"passed": 0, "failed": 0, "blocked": 0}
               and diagnostic["counts"]["passed"] == 1 and diagnostic["files"][0]["bytes"] > 0
               and len(diagnostic["files"][0]["sha256"]) == 64 and "row" not in diagnostic)

        # Merge roots, collapse only an exact same-family digest, and suppress
        # progress when any supplied root seals that family.
        receipt.write_bytes(sealed_bytes)
        index.write_text(json.dumps([{"family": family, "path": str(receipt),
            "sha256": hashlib.sha256(sealed_bytes).hexdigest(), "sourceStable": True}]), encoding="utf-8")
        root2 = Path(temp) / "proof2"
        fixtures2 = root2 / "semantic-fixtures"
        folder2 = fixtures2 / family
        folder2.mkdir(parents=True)
        receipt2a = folder2 / (family + ".receipt.json")
        receipt2a.write_bytes(sealed_bytes)
        folder2b = fixtures2 / family2
        folder2b.mkdir(parents=True)
        receipt2b = folder2b / (family2 + ".receipt.json")
        receipt2b.write_text(json.dumps({"family": family2, "sourceStable": True,
            "sourceBindings": {}, "rows": [{"id": "scratch.fail", "status": "failed"}]}), encoding="utf-8")
        root2_entries = []
        for name, path in ((family, receipt2a), (family2, receipt2b)):
            root2_entries.append({"family": name, "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "sourceStable": True})
        (fixtures2 / "families.json").write_text(json.dumps(root2_entries), encoding="utf-8")
        (folder2 / "case-progress.jsonl").write_text(json.dumps({"case": {"id": "scratch.sealed-progress",
            "status": "passed"}}) + "\n", encoding="utf-8")
        updated_families = []
        for name in BUILDERS:
            if name == family:
                case_defs = [{"id": row["id"], "category": row.get("category"), "contracts": row.get("contracts", [])}
                             for row in sealed_payload["rows"]]
                refs, planned = [{"path": receipt.resolve().relative_to(REPO).as_posix(), "sha256": digest}], 0
            elif name == family2:
                case_defs = [{"id": "scratch.fail", "category": None, "contracts": []}]
                refs, planned = [{"path": receipt2b.resolve().relative_to(REPO).as_posix(),
                                  "sha256": hashlib.sha256(receipt2b.read_bytes()).hexdigest()}], 0
            else:
                case_defs = [{"id": "planned:" + name, "category": None, "contracts": []}]
                refs, planned = [], 1
            authority_rows = []
            if name == "scheduler":
                authority_rows = [{"contract": row["contract"], "category": row["category"], "neededAuthority": row.get("neededAuthority")} for row in authority["originalAuthorityBlockers"]]
            elif name == "c7d-control-completion":
                authority_rows = [{"contract": row["contract"], "category": row["category"], "neededAuthority": row.get("neededAuthority")} for row in authority["additionalAuthorityBlockers"]]
            updated_families.append({"family": name, "cases": case_defs, "casesTotal": len(case_defs),
                                     "plannedCasesTotal": planned, "plannedSource": {"kind": "check-only"},
                                     "receipts": refs, "authorityCases": authority_rows})
        inventory_value["families"] = updated_families
        inventory_path.write_text(json.dumps(inventory_value), encoding="utf-8")
        merged = _report(48741, [scratch, root2], inventory_path, check_fixture=True)
        record("c7e.deadline.cross-root-exactsha-merge", lambda: merged,
               lambda value: value["completedFamilies"] == 2
               and value["completedReceiptCounts"] == {"passed": 1, "blocked": 1, "failed": 1}
               and len(value["unsealedCaseProgress"]) == 0)

        # A second distinct digest for the same family is not silently selected.
        root3 = Path(temp) / "proof3"
        fixtures3 = root3 / "semantic-fixtures"
        folder3 = fixtures3 / family
        folder3.mkdir(parents=True)
        receipt3 = folder3 / (family + ".receipt.json")
        receipt3.write_text(json.dumps({"family": family, "sourceStable": True,
            "sourceBindings": {}, "rows": [{"id": "scratch.different", "status": "passed"}]}), encoding="utf-8")
        (fixtures3 / "families.json").write_text(json.dumps([{"family": family,
            "path": str(receipt3), "sha256": hashlib.sha256(receipt3.read_bytes()).hexdigest(),
            "sourceStable": True}]), encoding="utf-8")
        record("c7e.deadline.cross-root-conflicting-sha-refused", lambda: _report(48741, [scratch, root3], inventory_path, check_fixture=True),
               lambda value: value == "ValueError")
    return {"schema": "neyvia.c7e-deadline-generator-check.v1", "ok": True,
            "complete": False, "cases": cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--root", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, default=REPO / "scripts/evidence/C7e-deadline.json")
    parser.add_argument("--inventory", type=Path, default=REPO / "scripts/evidence/C7e-case-inventory.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.port not in range(48741, 48750):
        parser.error("Explicit assigned port required")
    if args.check:
        check = _check()
        target = (REPO / "scripts/evidence/C7e-deadline-check.json").resolve()
        target.relative_to((REPO / "scripts/evidence").resolve())
        target.write_text(json.dumps(check, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(check))
        return
    target = args.output.resolve()
    target.relative_to((REPO / "scripts/evidence").resolve())
    report = _report(args.port, args.root, args.inventory)
    from datetime import datetime, timezone
    from grant_agent.proof_contracts import source_digest
    report['sealedAtUtc'] = datetime.now(timezone.utc).isoformat()
    report['sourceBindings'] = {'scripts/seal_C7e_deadline.py': source_digest(Path(__file__))}
    for field, name in (('bugs', 'C7e-bugs.json'), ('tokenUsage', 'C7e-tokens.json')):
        path = REPO / 'scripts/evidence' / name
        value = json.loads(path.read_bytes())
        report[field] = {'path': path.relative_to(REPO).as_posix(),
                         'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                         'counts': value['counts'] if field == 'bugs' else value['loggedTotals']}
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "complete": report["complete"],
                      "completedFamilies": report["completedFamilies"],
                      "caseTotals": report["caseTotals"],
                      "unsealedDiagnosticCases": len(report["unsealedCaseProgress"])}))


if __name__ == "__main__":
    main()
