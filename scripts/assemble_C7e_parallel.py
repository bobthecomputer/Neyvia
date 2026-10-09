"""Assemble unchanged-source local C7 family observations into one campaign."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.proof_ports import C7_PORTS, c7_port_block
LOCAL_FAMILIES = 43
REAL_BOUNDARIES = {"rendered", "device", "provider"}


def assigned_port(port: int) -> bool:
    if type(port) is not int or port not in C7_PORTS:
        return False
    return port in c7_port_block(port)


def accepted_input_path(path: Path) -> bool:
    """Admit campaign indexes only from evidence or the task-local C7 proof root."""
    resolved = path.resolve()
    for parent in (REPO / "scripts/evidence", REPO / ".agent_control/proofs/c7"):
        try:
            resolved.relative_to(parent.resolve())
            return True
        except ValueError:
            continue
    return False


def merge_binding(bindings: dict, name: str, digest: str) -> None:
    if name in bindings and bindings[name] != digest:
        raise ValueError("Source lineage differs: " + name)
    bindings[name] = digest


def admit_family(gathered: dict, family: str, entry: dict, raw: bytes, source_port: int) -> bool:
    previous = gathered.get(family)
    if previous:
        if previous[0]["sha256"] != entry["sha256"]:
            raise ValueError("Duplicate family has different SHA: " + family)
        return False
    gathered[family] = (entry, raw, source_port)
    return True


def require_unique_journeys(journeys: list[dict]) -> None:
    if len({row["id"] for row in journeys}) != len(journeys):
        raise ValueError("Duplicate contract case identities")


def combine_journeys(observed, family_rows, source_family_ids):
    require_unique_journeys(observed)
    if not source_family_ids <= {row['id'] for row in observed}:
        raise ValueError('Input campaign omits a sealed family case')
    base = [row for row in observed if row['id'] not in source_family_ids]
    journeys = base + family_rows
    require_unique_journeys(journeys)
    return base, journeys


def validate_row(row: dict, contracts: dict, proof_boundary) -> None:
    if row.get("status") == "failed":
        raise ValueError("Cannot reuse failed case: " + str(row.get("id")))
    if (row.get("proofScope") in REAL_BOUNDARIES or row.get("boundary") in REAL_BOUNDARIES
            or row.get("liveObservation") or row.get("liveObservationNonce")):
        raise ValueError("Cannot reuse live or real-boundary case: " + str(row.get("id")))
    if any(proof_boundary(contracts[name]) in REAL_BOUNDARIES for name in row["contracts"]):
        raise ValueError("Cannot reuse live or real-boundary contract: " + str(row.get("id")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Passing selected-family verify_c7_edges.py campaign")
    parser.add_argument("--root", type=Path, action="append", default=[], help="Completed local receipt root; repeat as needed")
    parser.add_argument("--root-port", type=int, action="append", default=[], help="Assigned source port paired by order with each --root")
    parser.add_argument("--root-families", action="append", default=[], help="Comma-separated disjoint family slice for each root; '*' selects all")
    parser.add_argument("--output", type=Path, default=Path("scripts/evidence/C7e-parallel-local.json"))
    parser.add_argument("--port", type=int, required=True, help="Explicit assigned C7 assembly port")
    parser.add_argument("--check", action="store_true", help="Run metadata-only C7 contract checks and write the check receipt")
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(REPO / "scripts/evidence")
    if not assigned_port(args.port):
        parser.error("Explicit assigned assembly port required")
    if args.check:
        if args.input or args.root or args.root_port:
            parser.error("--check does not accept campaigns or observed roots")
        return run_checks(output)
    if args.input is None or not args.root:
        parser.error("--input and at least one --root are required")
    if len(args.root) != len(args.root_port):
        parser.error("Provide one --root-port for each --root, in the same order")
    if args.root_families and len(args.root_families) != len(args.root):
        parser.error('Provide one --root-families slice for each root')
    if any(not assigned_port(port) for port in args.root_port):
        parser.error("Each source root needs an assigned explicit port")

    source_path = args.input.resolve()
    if not accepted_input_path(source_path):
        raise ValueError("Input campaign must be under scripts/evidence or the task-local C7 proof root")
    source = json.loads(source_path.read_bytes())
    input_port = source.get("explicitPort")
    if not assigned_port(input_port):
        raise ValueError("Input campaign has no assigned explicit port")
    if not source.get("ok") or not source.get("sourceStable") or source.get("failures"):
        raise ValueError("Input campaign must pass with stable sources")
    if source.get("schemaOnly"):
        raise ValueError("Input must include the selected family's campaign journeys")
    input_root = Path(source["root"]).resolve()
    input_root.relative_to(REPO / ".agent_control/proofs/c7")

    from grant_agent.edge_contracts import inventory, matrix, proof_boundary
    from grant_agent.edge_fixture_catalog import BUILDERS, completed_receipts, summarize
    from grant_agent.proof_contracts import source_digest

    expected = set(BUILDERS) - {"c7d-rendered"}
    if len(expected) != LOCAL_FAMILIES:
        raise ValueError("Registered local family count changed")
    _, contracts = inventory()
    bindings = dict(source["sourceBindings"])
    for name, digest in bindings.items():
        bound_path = (REPO / name).resolve()
        bound_path.relative_to(REPO)
        if source_digest(bound_path) != digest:
            raise ValueError("Input campaign source changed: " + name)

    slices = args.root_families or ['*'] * len(args.root)
    roots = [(input_root, input_port, expected)]
    for path, port, names in zip(args.root, args.root_port, slices):
        selected = expected if names == '*' else set(names.split(','))
        if not selected or selected - expected:
            raise ValueError('Unknown or empty root family slice')
        roots.append((path.resolve(), port, selected))
    gathered: dict[str, tuple[dict, bytes, int]] = {}
    duplicate_origins: dict[str, list[dict]] = {}
    for root, source_port, selected in roots:
        if not any(root.is_relative_to(REPO / '.agent_control/proofs' / name)
                   for name in ('c7', 'c7e-family')):
            raise ValueError('Family root is outside the owned C7 campaign and fixture roots')
        entries = completed_receipts(root / "semantic-fixtures")
        if root == input_root and entries != source.get("familyReceipts"):
            raise ValueError("Input campaign receipt index differs from its observed root")
        for entry in entries:
            family = entry["family"]
            if family not in selected:
                continue
            if family == "c7d-rendered" or family not in expected:
                raise ValueError("Unexpected nonlocal family receipt: " + family)
            receipt_path = Path(entry["path"])
            raw = receipt_path.read_bytes()
            if not admit_family(gathered, family, entry, raw, source_port):
                duplicate_origins.setdefault(family, []).append({"path": entry["path"], "sourceCampaignPort": source_port})
                continue
            receipt = json.loads(raw)
            for name, digest in receipt["sourceBindings"].items():
                merge_binding(bindings, name, digest)
            for row in receipt["rows"]:
                validate_row(row, contracts, proof_boundary)
    if set(gathered) != expected:
        missing = sorted(expected - set(gathered))
        extra = sorted(set(gathered) - expected)
        raise ValueError(f"Expected exactly {LOCAL_FAMILIES} local families; missing={missing[:5]} extra={extra[:5]}")

    root = REPO / ".agent_control/proofs/c7" / uuid.uuid4().hex
    semantic_root = root / "semantic-fixtures"
    semantic_root.mkdir(parents=True)
    index = []
    added_rows = []
    reused = []
    for family in sorted(gathered):
        entry, raw, source_port = gathered[family]
        destination = semantic_root / (family + ".receipt.json")
        destination.write_bytes(raw)
        copied = {**entry, "path": str(destination), "observationOrigin": entry["path"],
                  "sourceCampaignPort": source_port,
                  "duplicateOrigins": duplicate_origins.get(family, [])}
        index.append(copied)
        receipt = json.loads(raw)
        added_rows.extend(receipt["rows"])
        reused.append({"family": family, "origin": entry["path"], "sha256": entry["sha256"],
                       "sourceCampaignPort": source_port,
                       "duplicateOrigins": duplicate_origins.get(family, []), "cases": len(receipt["rows"])})

    bindings[Path(__file__).relative_to(REPO).as_posix()] = source_digest(Path(__file__))
    for name, digest in bindings.items():
        bound_path = (REPO / name).resolve()
        bound_path.relative_to(REPO)
        if source_digest(bound_path) != digest:
            raise ValueError("A source bound to the observations has changed: " + name)
    (semantic_root / "families.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    if completed_receipts(semantic_root) != index:
        raise ValueError("Copied receipt index failed validation")

    source_family_ids = {row['id'] for entry in source['familyReceipts']
                         for row in json.loads(Path(entry['path']).read_bytes())['rows']}
    base_journeys, journeys = combine_journeys(source['journeys'], added_rows, source_family_ids)
    for row in base_journeys:
        validate_row(row, contracts, proof_boundary)
    coverage = matrix(contracts, journeys, semantic_fixtures=True)
    report = {**source, "root": str(root), "journeys": journeys, "semanticCoverage": coverage,
              "familyReceipts": index, "sourceBindings": bindings, "sourceStable": True,
              "semanticSummary": summarize(coverage), "explicitPort": args.port,
              "parallelLocalAssembly": {"sourceCampaign": source_path.relative_to(REPO).as_posix(),
                  "sourceCampaignPort": input_port, "families": reused, "familyCount": len(index),
                  "baseJourneyCount": len(base_journeys), "realBoundaryReuse": False,
                  "unchangedSourceRequired": True, "effectfulFamiliesReexecuted": False}}
    report["failures"] = [row for row in report["schemaCases"] + report["postconditionCases"] + journeys
                          if row["status"] == "failed"]
    report["ok"] = not report["failures"] and report["sourceStable"]
    report["complete"] = report["ok"] and not report["schemaFrontier"] and not report["postconditionFrontier"] and all(row["status"] == "passed" for row in coverage)
    report["counts"] = {name: dict(Counter(row["status"] for row in report[field])) for name, field in
                        {"schema": "schemaCases", "postconditions": "postconditionCases", "journeys": "journeys",
                         "semanticCoverage": "semanticCoverage"}.items()}
    baseline = json.loads((REPO / "scripts/evidence/C7.json").read_bytes())
    actual = {(row["contract"], row["category"]): row for row in coverage}
    report["baseline"]["formerlyBlocked"] = dict(Counter(actual[(row["contract"], row["category"])]["status"]
        for row in baseline["semanticCoverage"] if row["status"] == "blocked"))
    if not report["ok"]:
        raise ValueError("Assembled campaign includes failed cases")
    campaign_path = root / "campaign.json"
    campaign_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "complete": report["complete"], "families": len(index),
                      "counts": report["counts"], "root": str(root)}))
    return 0


def run_checks(output: Path) -> int:
    """Exercise admission guards with disposable metadata; never call builders."""
    from grant_agent.edge_contracts import proof_boundary

    contracts = {"local.ok": {"id": "local.ok", "proofBoundary": "local_semantic"},
                 "ui.rendered": {"id": "ui.rendered", "proofBoundary": "rendered"}}
    checks = []

    def ensure(condition):
        if not condition:
            raise AssertionError("Expected condition to hold")

    def case(name, fn):
        try:
            fn()
            checks.append({"case": name, "status": "passed"})
        except Exception as exc:
            checks.append({"case": name, "status": "failed", "detail": str(exc)})

    def expect_reject(name, fn):
        def run():
            try:
                fn()
            except ValueError:
                return
            raise AssertionError("Expected admission rejection")
        case(name, run)

    case("C7.parallel.assigned-output-port", lambda: ensure(assigned_port(48743)))
    case("C7.parallel.assigned-source-port", lambda: ensure(assigned_port(48741)))
    case("C7.parallel.same-sha-dedup", lambda: ensure(not admit_family({"f": ({"sha256": "abc"}, b"x", 48741)}, "f", {"sha256": "abc"}, b"x", 48743)))
    expect_reject("C7.parallel.conflicting-source-binding", lambda: merge_binding({"same.py": "abc"}, "same.py", "def"))
    expect_reject("C7.parallel.conflicting-family-sha", lambda: admit_family({"f": ({"sha256": "abc"}, b"x", 48741)}, "f", {"sha256": "def"}, b"y", 48743))
    expect_reject("C7.parallel.failed-row", lambda: validate_row({"id": "x", "status": "failed", "contracts": ["local.ok"]}, contracts, proof_boundary))
    expect_reject("C7.parallel.rendered-scope", lambda: validate_row({"id": "x", "status": "passed", "proofScope": "rendered", "contracts": ["local.ok"]}, contracts, proof_boundary))
    expect_reject("C7.parallel.live-observation-nonce", lambda: validate_row({"id": "x", "status": "passed", "liveObservationNonce": "n", "contracts": ["local.ok"]}, contracts, proof_boundary))
    expect_reject("C7.parallel.rendered-contract-boundary", lambda: validate_row({"id": "x", "status": "passed", "contracts": ["ui.rendered"]}, contracts, proof_boundary))
    expect_reject("C7.parallel.duplicate-journey-identity", lambda: require_unique_journeys([{"id": "x"}, {"id": "x"}]))
    case("C7.parallel.family-rows-counted-once", lambda: ensure(
        combine_journeys([{'id':'base'}, {'id':'family'}], [{'id':'family'}, {'id':'other'}], {'family'})
        == ([{'id':'base'}], [{'id':'base'}, {'id':'family'}, {'id':'other'}])))
    expect_reject("C7.parallel.missing-input-family-row", lambda:
        combine_journeys([{'id':'base'}], [{'id':'family'}], {'family'}))
    if len(checks) < 7 or any(check["status"] != "passed" for check in checks):
        raise ValueError("Parallel assembler contract check failed")
    receipt = {"schema": "neyvia.c7e-parallel-generator-check.v1", "ok": True,
               "effectfulFamiliesExecuted": False, "cases": checks,
               "sourceSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "boundary": "Metadata-only admission guard checks; no family observations or product effects were executed."}
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "contractCases": len(checks), "output": output.relative_to(REPO).as_posix()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
