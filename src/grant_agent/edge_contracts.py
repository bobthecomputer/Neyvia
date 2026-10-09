"""Bounded, reproducible adversarial campaigns against the real contract host.

Generated payloads are synthetic. Schema admission never calls a handler;
semantic journeys have explicit owned fixtures. Unbound cases remain blocked.
"""
from __future__ import annotations

import copy
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator

CATEGORIES = ("empty", "huge", "unicode", "concurrency", "interrupted", "permissions", "offline", "stale")
MAX_GENERATED_SIZE = 2 * 1024 * 1024 + 1
STRATEGIES = {
    "empty": "Remove required inputs and send zero-length collections/text; verify refusal or exact declared empty effect.",
    "huge": "Exercise declared size maximum and maximum+1 with bounded synthetic data; verify rejected bytes/state unchanged.",
    "unicode": "Use combining accents, RTL, astral characters, NUL and malformed UTF-8 boundaries; compare exact persisted bytes.",
    "concurrency": "Synchronize competing callers at the same observed revision; require the contract's winner/conflict and conservation invariant.",
    "interrupted": "Exit an owned worker between effect and durable completion; reopen and require no implicit replay of uncertain effects.",
    "permissions": "Remove the target-specific required grant or deny native replacement; require refusal and preserved state.",
    "offline": "Refuse network in an isolated worker or close an explicitly assigned local endpoint; verify truthful failure and local durability.",
    "stale": "Change state after observation and reuse the original revision/token; verify conflict and preservation of the newer state.",
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def example(schema, depth=0):
    """Construct witnesses where possible; unresolved schemas are explicit frontier."""
    if depth > 12:
        raise ValueError("Schema witness depth exceeded")
    if "const" in schema:
        return copy.deepcopy(schema["const"])
    if schema.get("enum"):
        return copy.deepcopy(schema["enum"][0])
    for keyword in ("oneOf", "anyOf"):
        if keyword in schema:
            for branch in schema[keyword]:
                value = example(branch, depth + 1)
                if Draft202012Validator(schema).is_valid(value):
                    return value
            raise ValueError("No bounded composition witness")
    kind = schema.get("type", "object" if "properties" in schema else "string")
    if isinstance(kind, list):
        kind = kind[0]
    if kind == "object":
        return {key: example(schema.get("properties", {}).get(key, {}), depth + 1)
                for key in schema.get("required", [])}
    if kind == "array":
        size = schema.get("minItems", 0)
        if size > 100:
            raise ValueError("Array witness exceeds campaign bound")
        return [example(schema.get("items", {}), depth + 1) for _ in range(size)]
    if kind == "string":
        size = max(1, schema.get("minLength", 0))
        if size > MAX_GENERATED_SIZE:
            raise ValueError("String witness exceeds campaign bound")
        # Common ID/hash patterns; arbitrary regex generation is not fabricated.
        candidates = ["x" * size, "a" * 64, "doc_" + "a" * 64, "a" * 32, "a-1", "2026-10-04T00:00:00Z"]
        return next((value for value in candidates if Draft202012Validator(schema).is_valid(value)), candidates[0])
    if kind in {"number", "integer"}:
        return schema.get("minimum", schema.get("exclusiveMinimum", 0) + 1)
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    raise ValueError("Unsupported bounded schema witness")


def mutations(schema, baseline, path=(), depth=0):
    """Explore each declared leaf, not just the first field of a tool."""
    yield path, "empty", None
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((value for value in kind if value != "null"), "null")
    if kind in {"integer", "number", "array", "object", "boolean"}:
        yield path, "transport", json.dumps(baseline)
    if kind == "object":
        yield path, "empty", {}
        yield path, "empty", []
        if schema.get("additionalProperties") is False:
            yield path, "unicode", {**baseline, "unexpected-雪": True}
        if depth < 3:
            properties = schema.get("properties", {})
            for key in dict.fromkeys([*properties, *schema.get("required", [])]):
                child = properties.get(key, {})
                if key in schema.get("required", []):
                    yield path, "empty", {k: v for k, v in baseline.items() if k != key}
                try:
                    value = baseline.get(key, example(child))
                except ValueError:
                    continue
                for inner, category, changed in mutations(child, value, path + (key,), depth + 1):
                    yield inner, category, changed
    elif kind == "array":
        yield path, "transport", {"item": baseline}
        yield path, "empty", []
        size = min(101, schema.get("maxItems", 100) + 1)
        item = example(schema.get("items", {}))
        yield path, "huge", [item] * size
        if schema.get("uniqueItems"):
            yield path, "concurrency", [item, item]
        yield path, "unicode", ["雪🙂e\u0301\u202e", "a\x00b"]
    elif kind == "string":
        yield path, "empty", ""
        yield path, "empty", {}
        yield path, "huge", "x" * min(MAX_GENERATED_SIZE, schema.get("maxLength", 65535) + 1)
        for value in ("雪🙂e\u0301\u202e", "a\x00b", "\ud800"):
            yield path, "unicode", value
    elif kind in {"integer", "number"}:
        yield path, "empty", True  # JSON booleans are not numbers.
        yield path, "huge", schema.get("maximum", 2**63) + 1
        yield path, "empty", schema.get("minimum", 0) - 1
        yield path, "huge", float("inf")
        yield path, "huge", float("nan")
    elif kind == "boolean":
        yield path, "empty", 1
    if "const" in schema or "enum" in schema:
        yield path, "unicode", "not-an-option-雪"


def replaced(value, path, changed):
    result = copy.deepcopy(value)
    if not path:
        return changed
    current = result
    for key in path[:-1]:
        current = current.setdefault(key, {})
    current[path[-1]] = changed
    return result


def schema_campaign(registry, tools=None):
    from .native_arguments import normalize
    if tools is not None and (not tools or set(tools) - set(registry._specs)):
        raise ValueError("Select existing tool contracts; an empty selection is not a pass")
    rows, frontier = [], []
    for tool, spec in sorted(registry._specs.items()):
        if tools is not None and tool not in tools:
            continue
        schema = spec.input_schema
        validator = Draft202012Validator(schema)
        try:
            baseline = example(schema)
            if not validator.is_valid(baseline):
                raise ValueError("No valid bounded schema witness")
        except ValueError as exc:
            frontier.append({"tool": tool, "status": "blocked", "reason": str(exc)})
            continue
        cases = [((), "baseline", baseline), *mutations(schema, baseline)]
        seen = set()
        for path, category, mutation in cases:
            payload = mutation if category == "baseline" else replaced(baseline, path, mutation)
            fingerprint = digest(payload)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            # None retains the public API's omitted-arguments convention.
            normalized = normalize(schema, {} if payload is None else payload)
            expected = isinstance(payload, dict) or payload is None
            expected = expected and validator.is_valid(normalized)
            try:
                json.dumps(normalized, allow_nan=False)
            except ValueError:
                expected = False
            try:
                actual = registry.prepare_arguments(tool, payload)
                accepted = True
                unchanged = actual == normalized
            except (ValueError, TypeError, KeyError):
                accepted, unchanged = False, True
            rows.append({"id": f"schema:{tool}:{len(seen)}", "tool": tool, "category": category,
                         "contracts": ["input:" + tool], "path": ".".join(path) or "$", "payloadSha256": fingerprint,
                         "expectedAdmission": expected, "actualAdmission": accepted,
                         "status": "passed" if expected == accepted and unchanged else "failed",
                         "boundary": "production prepare_arguments; no handler invocation"})
    return rows, frontier


def inventory():
    from .proof_contracts import catalog, manifest_files
    actions, declared = catalog()
    contracts = {identity: {**row, "source": row["manual"]} for identity, row in declared.items()}
    for path in manifest_files():
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data.get("contracts", []):
            # Manual and manifest copies are one contract, with both origins retained.
            contracts.setdefault(row["id"], {**row, "source": path.relative_to(path.parents[2]).as_posix()})
    return actions, contracts


def postcondition_campaign(actions):
    """Fault-inject synthetic responses at the actual after_action boundary."""
    from .proof_contracts import after_action, ContractViolation
    rows, frontier = [], []
    for tool, contracts in sorted(actions.items()):
        for contract in contracts:
            schema = contract["output"].schema
            try:
                baseline = example(schema)
                if not contract["output"].is_valid(baseline):
                    raise ValueError("No valid bounded response witness")
            except ValueError as exc:
                frontier.append({"contract": contract["id"], "status": "blocked", "reason": str(exc)})
                continue
            seen = set()
            for path, category, changed in [((), "baseline", baseline), *mutations(schema, baseline)]:
                response = changed if category == "baseline" else replaced(baseline, path, changed)
                fingerprint = digest(response)
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                expected = isinstance(response, dict)
                failure = expected and (response.get("ok") is False or isinstance(response.get("status"), str) and response["status"] in {"failed", "error", "blocked", "approval_required", "frontier", "conflict"})
                expected = expected and (failure or contract["output"].is_valid(response))
                try:
                    after_action([contract], response)
                    actual = True
                except (ContractViolation, TypeError):
                    actual = False
                rows.append({"id": f"post:{contract['id']}:{len(seen)}", "tool": tool, "category": category,
                             "contracts": [contract["id"]], "path": ".".join(path) or "$", "responseSha256": fingerprint,
                             "expectedAdmission": expected, "actualAdmission": actual,
                             "status": "passed" if expected == actual else "failed",
                             "boundary": "production after_action response fault injection; no handler effects"})
    return rows, frontier


REAL_PROOF_BOUNDARIES = {
    "livecontrol.provider-dom": "rendered",
    "livecontrol.hermes-dom": "rendered",
    "livecontrol.cli-browser-option": "rendered",
    "native.tools.annotation": "rendered",
    "native.worker.reuse": "rendered",
    "control.neyvia-live-action": "rendered",
    "a.factory-notes-ui": "rendered",
    "a.factory-guided-ui": "rendered",
    "proofs-b.browser.blocked-receipt": "rendered",
    "proofs-b.browser.capacity-label": "rendered",
    "proofs-b.browser.capacity-explanation": "rendered",
}
PROOF_SCOPES = {"local_semantic", "model", "rendered", "device", "provider"}


def invariant_digest(contract):
    """Bind applicability to the exact invariant, rather than a family name."""
    return digest({key: contract.get(key) for key in ("id", "phase", "claim", "checkedAt")})


def proof_boundary(contract):
    required = contract.get("proofBoundary", REAL_PROOF_BOUNDARIES.get(contract["id"]))
    if required is None:
        required = "model" if any(str(site).startswith("web/") for site in contract.get("checkedAt", [])) else "local_semantic"
    if not isinstance(required, str) or required not in PROOF_SCOPES:
        raise ValueError("Unknown contract proof boundary: " + contract["id"])
    if contract["id"] in REAL_PROOF_BOUNDARIES and required != REAL_PROOF_BOUNDARIES[contract["id"]]:
        raise ValueError("Cannot weaken the audited real proof boundary: " + contract["id"])
    return required


def matrix(contracts, journeys, *, semantic_fixtures=False, proof_observer=None):
    """All applicable cases must pass; missing real observers remain blocked.

    A real proof observer is a host-injected callable that checks current
    rendered/device/provider effects for this exact contract and case. Receipt
    hashes, supplied proof labels and synthetic model outputs cannot replace it.
    Existing cases default to applicable, so absence of metadata never drops an
    obligation. Explicit exclusions must agree with the invariant's audited
    blocker and bind the current invariant hash and category.
    """
    from .edge_fixture_catalog import blocker
    covered = {}
    seen = set()
    for row in journeys:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] or row["id"] in seen:
            raise ValueError("Semantic case identity must be nonempty and unique")
        seen.add(row["id"])
        bindings = row.get("contracts")
        if (not isinstance(bindings, list) or not bindings or any(not isinstance(name, str) for name in bindings)
                or len(bindings) != len(set(bindings)) or set(bindings) - contracts.keys()):
            raise ValueError("Unknown, duplicate or malformed semantic contract binding: " + row["id"])
        if (not isinstance(row.get("category"), str) or row["category"] not in CATEGORIES
                or not isinstance(row.get("status"), str) or row["status"] not in {"passed", "failed", "blocked"}):
            raise ValueError("Unknown semantic category or status: " + row["id"])
        if "proofScope" in row and (not isinstance(row["proofScope"], str) or row["proofScope"] not in PROOF_SCOPES):
            raise ValueError("Unknown semantic proof scope: " + row["id"])
        applicability = row.get("applicability")
        if "applicability" in row and (not isinstance(applicability, dict) or set(applicability) != set(bindings)):
            raise ValueError("Applicability must bind every exact case invariant: " + row["id"])
        for identity in bindings:
            contract, category = contracts[identity], row["category"]
            if contract.get("id") != identity:
                raise ValueError("Contract inventory identity differs: " + identity)
            applicable = True
            if applicability is not None:
                audit = applicability[identity]
                if (not isinstance(audit, dict) or type(audit.get("applicable")) is not bool
                        or audit.get("contract") != identity or audit.get("category") != category
                        or audit.get("invariantSha256") != invariant_digest(contract)
                        or not isinstance(audit.get("reason"), str) or not audit["reason"].strip()):
                    raise ValueError("Malformed or stale invariant applicability: " + row["id"])
                applicable = audit["applicable"]
                if not applicable:
                    reason = blocker(contract, category) if semantic_fixtures else {}
                    if reason.get("kind") != "not_applicable" or audit["reason"] != reason.get("reason"):
                        raise ValueError("Unaudited invariant exclusion: " + row["id"])
                    if row["status"] != "blocked":
                        raise ValueError("An excluded case cannot claim pass or failure: " + row["id"])
            required = proof_boundary(contract)
            effective = row["status"]
            if applicable and effective == "passed" and required in {"rendered", "device", "provider"}:
                boundary = str(row.get("boundary", "")).lower()
                negatives = {"rendered": ("no rendered", "not rendering", "no rendering", "synthetic frontend model"),
                             "device": ("no device", "not device"), "provider": ("no provider", "not provider")}
                contradicted = any(phrase in boundary for phrase in (*negatives[required], "model behavior only"))
                observed = (not contradicted and row.get("proofScope") == required and callable(proof_observer)
                            and proof_observer(contract, category, row) is True)
                if not observed:
                    effective = "blocked"
            covered.setdefault((identity, category), []).append((row, applicable, effective))
    result = []
    for identity in sorted(contracts):
        contract = contracts[identity]
        for category in CATEGORIES:
            matched = covered.get((identity, category), [])
            applicable = [(row, status) for row, applies, status in matched if applies]
            status = ("failed" if any(value == "failed" for _, value in applicable)
                      else "passed" if applicable and all(value == "passed" for _, value in applicable) else "blocked")
            audited_authority=blocker(contract,category) if semantic_fixtures else {}
            if audited_authority.get('kind')=='authority_boundary' and status!='failed':
                status='blocked'
            conflicting_applicability = bool(applicable) and any(not applies for _, applies, _ in matched)
            if conflicting_applicability and status != "failed":
                status = "blocked"
            entry = {"contract": identity, "category": category, "strategy": STRATEGIES[category],
                     "expectedInvariant": contract["claim"], "checkedAt": contract.get("checkedAt", []),
                     "status": status, "cases": [row["id"] for row, _, _ in matched],
                     "applicableCases": [row["id"] for row, _ in applicable],
                     "excludedCases": [row["id"] for row, applies, _ in matched if not applies],
                     "proofBoundary": proof_boundary(contract), "invariantSha256": invariant_digest(contract)}
            if status == "blocked":
                unresolved = [row["id"] for row, value in applicable if value != "passed"]
                if audited_authority.get('kind')=='authority_boundary':
                    reason=audited_authority
                elif conflicting_applicability:
                    reason = {"kind": "applicability_conflict", "reason": "Matched cases disagree on this exact invariant/category applicability"}
                elif unresolved:
                    proof_missing = any(row["status"] == "passed" and value == "blocked" for row, value in applicable)
                    reason = {"kind": "proof_boundary" if proof_missing else "matched_case_blocked",
                              "reason": "Every applicable matched case must pass at its required proof boundary",
                              "cases": unresolved}
                else:
                    reason = blocker(contract, category) if semantic_fixtures else {
                        "kind": "fixture_gap", "reason": "Semantic builders were not requested; schema admission is separate"}
                entry.update(reason=reason["reason"], blockerKind=reason["kind"], fixtureRequirement=reason)
                if reason["kind"] == "not_applicable":
                    entry["accountedNotApplicable"] = True
            result.append(entry)
    return result


def run(root, *, include_journeys=True, semantic_fixtures=False, families=None):
    from .native_tools import NativeToolRegistry
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    registry = NativeToolRegistry(root, nas_root=root)
    before = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in root.rglob("*") if path.is_file()}
    schemas, frontier = schema_campaign(registry)
    after = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in root.rglob("*") if path.is_file()}
    if before != after:
        schemas.append({"id": "schema:no-effects", "status": "failed", "category": "permissions", "contracts": [],
                        "detail": "Pure admission campaign changed workspace state"})
    actions, contracts = inventory()
    postconditions, post_frontier = postcondition_campaign(actions)
    journeys = []
    from .edge_live_observations import LiveObservations
    live_observations=LiveObservations()
    if include_journeys:
        from .edge_journeys import run as run_journeys
        from .edge_notes import run as run_notes
        journeys = run_journeys(root / "journeys") + run_notes(root / "notes-journeys")
    if semantic_fixtures and include_journeys:
        from .edge_fixture_catalog import run as run_fixtures
        journeys += run_fixtures(root / "semantic-fixtures", contracts, CATEGORIES, families, live_observations=live_observations)
    coverage = matrix(contracts, journeys, semantic_fixtures=semantic_fixtures, proof_observer=live_observations)
    failures = [row for row in schemas + postconditions + journeys if row["status"] == "failed"]
    return {"schema": "neyvia.edge-contracts.v1", "ok": not failures,
            "complete": not failures and not frontier and not post_frontier and all(row["status"] == "passed" for row in coverage),
            "durationMs": round((time.perf_counter() - start) * 1000, 2), "root": str(root),
            "inventory": {"tools": len(registry._specs), "manualActions": sum(map(len, actions.values())), "semanticContracts": len(contracts)},
            "categories": list(CATEGORIES), "counts": {"schema": dict(Counter(row["status"] for row in schemas)),
                "postconditions": dict(Counter(row["status"] for row in postconditions)),
                "journeys": dict(Counter(row["status"] for row in journeys)), "semanticCoverage": dict(Counter(row["status"] for row in coverage))},
            "schemaCases": schemas, "schemaFrontier": frontier, "postconditionCases": postconditions, "postconditionFrontier": post_frontier,
            "journeys": journeys, "semanticCoverage": coverage, "semanticFixtures": semantic_fixtures,
            "failures": failures, "boundary": "schema admission for native tools; semantic effects only for listed owned journeys"}


def summary(report):
    return {key: report[key] for key in ("schema", "ok", "complete", "inventory", "counts", "durationMs", "sourceStable", "explicitPort")}


def call(service, name, args):
    """Registered bot interface; heavy campaigns always use a fresh interpreter."""
    from .proof_contracts import REPO, source_digest
    from .durability import atomic_write_json
    latest = service.bus.root / ".agent_control/c7/latest.json"
    if name == "verify.edges.status":
        if not latest.exists():
            return {"ok": True, "available": False, "complete": False}
        value = json.loads(latest.read_text(encoding="utf-8"))
        receipt = Path(value["receipt"]).resolve()
        from .proof_ports import c7_run_root
        receipt.relative_to(c7_run_root())
        intact = receipt.is_file() and hashlib.sha256(receipt.read_bytes()).hexdigest() == value["receiptSha256"]
        current = all((REPO / path).is_file() and source_digest(REPO / path) == expected
                      for path, expected in value["sourceBindings"].items())
        family_state = {}
        if args.get("family"):
            from .edge_fixture_catalog import BUILDERS
            if args["family"] not in BUILDERS:
                raise ValueError("Unknown edge fixture family")
            # Inspect actual matched rows, not the campaign's schema-admission
            # success. Missing, blocked or failed cases cannot earn a pass.
            rows = [row for row in json.loads(receipt.read_text(encoding="utf-8"))["journeys"]
                    if row.get("builder") == args["family"]] if intact else []
            family_state = {"family": args["family"], "familyCases": len(rows),
                            "familyCounts": dict(Counter(row["status"] for row in rows)),
                            "allApplicableCasesPassed": bool(rows) and current and intact
                                and all(row["status"] == "passed" for row in rows)}
        return {**summary(value), **family_state, "ok": value["ok"] and current and intact, "complete": value["complete"] and current and intact,
                "available": True, "sourceCurrent": current, "receiptIntact": intact, "receipt": value["receipt"]}
    from .proof_ports import c7_port_block
    c7_port_block(args.get("port"))
    if args.get("families"):
        from .edge_fixture_catalog import BUILDERS
        families = args["families"]
        if not isinstance(families, list) or not families or len(set(families)) != len(families) or any(f not in BUILDERS for f in families):
            raise ValueError("Select unique known edge fixture families")
        if args.get("schemaOnly") or not args.get("semanticFixtures", True):
            raise ValueError("Family selection requires semantic fixtures")
    import os
    import sys
    import uuid
    from .subprocess_utils import capture_bounded_process
    from .proof_ports import c7_run_root
    output = c7_run_root() / (uuid.uuid4().hex + ".json")
    command = [sys.executable, str(REPO / "scripts/verify_c7_edges.py"), "--port", str(args["port"]), "--output", str(output)]
    if args.get("schemaOnly"):
        command.append("--schema-only")
    elif args.get("semanticFixtures", True):
        command.append("--semantic-fixtures")
    for family in args.get("families", []):
        command.extend(["--family", family])
    # The full 44-family replay includes durable OS writes and eight native
    # browser categories. Seven families alone take over an hour; keep a hard
    # deadline that admits the measured workload without relaxing case checks.
    timeout = 10800 if "--semantic-fixtures" in command else 5400
    completed = capture_bounded_process(command, cwd=REPO, env=dict(os.environ), input_text=None, timeout=timeout)
    if completed["timedOut"] or not output.exists():
        return {"ok": False, "complete": False, "status": "failed", "error": "Edge worker failed before its final receipt", "timedOut": completed["timedOut"]}
    value = json.loads(output.read_text(encoding="utf-8"))
    value["receipt"] = str(output)
    atomic_write_json(latest, {**summary(value), "sourceBindings": value["sourceBindings"],
                              "receipt": str(output), "receiptSha256": hashlib.sha256(output.read_bytes()).hexdigest()})
    return {**summary(value), "available": True, "receipt": str(output)}
