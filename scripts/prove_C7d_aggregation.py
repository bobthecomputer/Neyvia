"""Exercise the production C7 matrix gate with adversarial case receipts.

This is an aggregation proof, not rendered/device/provider evidence. Deliberate
inputs are never relabelled as a real browser or provider journey.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.port not in range(48741, 48750):
        parser.error("Assigned ports 48741-48749 only")
    target = args.output.resolve()
    target.relative_to(REPO / "scripts/evidence")
    root = REPO / ".agent_control/proofs/c7-aggregation" / uuid.uuid4().hex
    root.mkdir(parents=True)
    os.environ.update(NEYVIA_COORDINATOR_AUTOSTART="0", FLUXIO_WATCHDOG_AUTOSTART="0",
                      NEYVIA_TOOL_AUTO_UPDATE="0", NEYVIA_C7_PORT=str(args.port))
    from grant_agent.proof_credential_guard import install
    install(root)
    from grant_agent.edge_contracts import CATEGORIES, inventory, invariant_digest, matrix
    from grant_agent.edge_fixture_catalog import blocker
    from grant_agent.proof_contracts import source_digest

    paths = ["src/grant_agent/edge_contracts.py", "src/grant_agent/edge_live_observations.py", "scripts/prove_C7d_aggregation.py",
             "src/grant_agent/edge_fixture_pure.py", "src/grant_agent/connected_sessions/claude_items.py",
             "src/grant_agent/proof_ports.py", "src/grant_agent/neyvia_browser_capture.py",
             "src/grant_agent/edge_journeys.py"]
    bindings = {path: source_digest(REPO / path) for path in paths}
    _, catalog = inventory()
    identity = "image.payload.geometry"
    contract = catalog[identity]
    contracts = {identity: contract}
    category = "empty"
    results = []

    def row(name, status="passed", **extra):
        return {"id": name, "contracts": [identity], "category": category, "status": status, **extra}

    def observe(name, rows, expected, *, selected=contracts, selected_category=category, **options):
        values = matrix(selected, rows, **options)
        assert len(values) == len(selected) * len(CATEGORIES), "A matrix obligation disappeared"
        value = next(value for value in values if value["contract"] == next(iter(selected)) and value["category"] == selected_category)
        assert value["status"] == expected, (name, value)
        assert set(value["cases"]) == {value["id"] for value in rows if value["category"] == selected_category}, name
        results.append({"case": name, "status": value["status"], "matched": len(value["cases"]),
                        "proofBoundary": value["proofBoundary"], "blockerKind": value.get("blockerKind")})
        return value

    def refused(name, rows):
        try:
            matrix(contracts, rows, semantic_fixtures=True)
        except ValueError as error:
            results.append({"case": name, "status": "refused", "reason": str(error)})
        else:
            raise AssertionError("Malformed campaign accepted: " + name)

    observe("all-applicable-pass", [row("first"), row("second")], "passed")
    observe("passed-then-blocked", [row("first"), row("second", "blocked")], "blocked")
    observe("blocked-then-passed", [row("first", "blocked"), row("second")], "blocked")
    observe("passed-then-failed", [row("first"), row("second", "failed")], "failed")
    observe("failed-and-blocked", [row("first", "failed"), row("second", "blocked")], "failed")
    observe("missing-case-keeps-obligation", [], "blocked")
    other_category = {**row("other-category", "failed"), "category": "unicode"}
    observe("category-isolation", [row("owned-category"), other_category], "passed")
    refused("unknown-contract", [{**row("unknown"), "contracts": ["not.a.real.contract"]}])
    refused("unknown-category", [{**row("unknown"), "category": "not-a-category"}])
    refused("unknown-status", [row("unknown", "complete")])
    refused("duplicate-case", [row("same"), row("same")])
    refused("empty-bindings", [{**row("empty"), "contracts": []}])
    refused("malformed-bindings", [{**row("malformed"), "contracts": identity}])
    refused("unknown-proof-scope", [row("unknown-scope", proofScope="hash_valid")])
    refused("malformed-category", [{**row("list-category"), "category": []}])
    refused("malformed-status", [{**row("list-status"), "status": {}}])
    refused("malformed-proof-scope", [row("list-scope", proofScope=[])])
    refused("duplicate-contract-binding", [{**row("duplicate-binding"), "contracts": [identity, identity]}])
    second_identity = "image.layers.selection"
    second_contracts = {identity: contract, second_identity: catalog[second_identity]}
    separate = {**row("other-invariant", "blocked"), "contracts": [second_identity]}
    values = matrix(second_contracts, [row("first-invariant"), separate])
    statuses = {value["contract"]: value["status"] for value in values if value["category"] == category}
    assert statuses == {identity: "passed", second_identity: "blocked"}, statuses
    results.append({"case": "exact-invariant-isolation", "status": "passed", "invariantStatuses": statuses})

    audit = {"contract": identity, "category": category, "applicable": True,
             "invariantSha256": invariant_digest(contract), "reason": "Exact input geometry mutation"}
    applicable_row = row("explicit-applicable", applicability={identity: audit})
    observe("exact-applicable-metadata", [applicable_row], "passed")
    refused("boolean-applicability", [row("boolean", applicability=False)])
    refused("null-applicability", [row("null", applicability=None)])
    refused("missing-invariant-applicability", [row("missing", applicability={})])
    for field, changed in (("contract", "other.contract"), ("category", "unicode"),
                           ("invariantSha256", "0" * 64), ("applicable", "false"), ("reason", "")):
        bad = copy.deepcopy(applicable_row)
        bad["id"] = "bad-" + field
        bad["applicability"][identity][field] = changed
        refused("wrong-applicability-" + field, [bad])
    unsupported = copy.deepcopy(applicable_row)
    unsupported["applicability"][identity]["applicable"] = False
    unsupported["status"] = "blocked"
    refused("unsupported-exclusion", [unsupported])

    na_category = "offline"
    na_reason = blocker(contract, na_category)
    assert na_reason["kind"] == "not_applicable", na_reason
    excluded = row("audited-exclusion", "blocked", applicability={identity: {
        "contract": identity, "category": na_category, "applicable": False,
        "invariantSha256": invariant_digest(contract), "reason": na_reason["reason"]}})
    excluded["category"] = na_category
    value = observe("audited-exclusion-never-passed", [excluded], "blocked", selected_category=na_category, semantic_fixtures=True)
    assert value["accountedNotApplicable"] and not value["applicableCases"]
    included = {**row("conflicting-applicable"), "category": na_category}
    observe("mixed-applicability-keeps-blocked", [included, excluded], "blocked", selected_category=na_category, semantic_fixtures=True)

    rendered_id = "proofs-b.browser.blocked-receipt"
    rendered_contracts = {rendered_id: catalog[rendered_id]}
    for name, extra in (
        ("synthetic-model-is-not-rendered", {"boundary": "Actual synthetic frontend model; no rendered UI proof", "proofScope": "model"}),
        ("hash-valid-is-not-rendered", {"receiptIntact": True, "receiptSha256": "a" * 64}),
        ("rendered-label-is-not-observation", {"proofScope": "rendered", "boundary": "claimed rendered proof"}),
    ):
        candidate = {**row(name, **extra), "contracts": [rendered_id]}
        observe(name, [candidate], "blocked", selected=rendered_contracts)
    candidate = {**row("contradicted-render-label", proofScope="rendered", boundary="no rendered UI proof"), "contracts": [rendered_id]}
    observe("contradictory-boundary-refused", [candidate], "blocked", selected=rendered_contracts, proof_observer=lambda *_: True)
    candidate = {**row("observer-false", proofScope="rendered"), "contracts": [rendered_id]}
    observe("observer-denial-keeps-blocked", [candidate], "blocked", selected=rendered_contracts, proof_observer=lambda *_: False)
    from grant_agent.edge_live_observations import LiveObservations
    fresh_observer=LiveObservations()
    replay={**candidate,'id':'replayed-native-nonce','liveObservationNonce':'historical-valid-looking-nonce','receiptIntact':True}
    observe('native-nonce-replay-without-live-host-keeps-blocked',[replay],'blocked',selected=rendered_contracts,proof_observer=fresh_observer)
    try:
        fresh_observer.record(rendered_contracts[rendered_id],category,replay,lambda: {},lambda:False)
    except ValueError:
        results.append({'case':'disconnected-native-host-refused','status':'refused'})
    else:
        raise AssertionError('Disconnected browser admitted live proof')
    # These supplied observations exercise witness admission only; they do not
    # constitute rendered proof or enter the real campaign's case collection.
    supplied=lambda: {'readyState':'complete','revision':'supplied-gate-probe',
        'elements':[{'id':'probe'}],'tabId':'supplied-gate-probe','url':'http://127.0.0.1:48746/probe'}
    witness=fresh_observer.capture(rendered_contracts[rendered_id],category,supplied,lambda:True)
    for name,token,selected_category in (('unknown-native-witness','unknown',category),
                                        ('wrong-native-witness-category',witness,'unicode' if category!='unicode' else 'empty')):
        trial={**candidate,'id':name,'category':selected_category}
        try:
            fresh_observer.admit(rendered_contracts[rendered_id],selected_category,trial,token)
        except ValueError:
            results.append({'case':name,'status':'refused'})
        else:raise AssertionError('Unbound native witness admitted')
    admitted={**candidate,'id':'supplied-witness-consumption'}
    fresh_observer.admit(rendered_contracts[rendered_id],category,admitted,witness)
    try:
        fresh_observer.admit(rendered_contracts[rendered_id],category,{**admitted,'id':'reused-native-witness'},witness)
    except ValueError:
        results.append({'case':'consumed-native-witness-refused','status':'refused'})
    else:raise AssertionError('Consumed native witness admitted twice')
    # Generated admission cases only: supplied observations and callbacks never
    # enter the campaign as rendered proof or make browser requests.
    from grant_agent.neyvia_browser_capture import NeyviaCaptureRuntime, authenticated_request
    original_port = os.environ['NEYVIA_C7_PORT']
    try:
        os.environ['NEYVIA_C7_PORT'] = '48983'
        for kind in ('observer', 'capture-context', 'authenticated-transport'):
            for allowed in (True, False):
                selected_port = 48986 if allowed else 48977
                probe_url = f'http://127.0.0.1:{selected_port}/supplied-gate-probe'
                try:
                    if kind == 'observer':
                        fresh_observer.capture(rendered_contracts[rendered_id], category,
                            lambda: {**supplied(), 'url': probe_url}, lambda: True)
                    elif kind == 'capture-context':
                        NeyviaCaptureRuntime(lambda *_: {}, initial_url=probe_url)
                    else:
                        authenticated_request(selected_port, 'owned-admission-probe')
                except ValueError:
                    assert not allowed, kind + ' rejected its assigned block'
                else:
                    assert allowed, kind + ' admitted another worker block'
                results.append({'case': kind + ('-assigned-block' if allowed else '-foreign-block-refused'),
                                'status': 'passed', 'admissionOnly': True})
    finally:
        os.environ['NEYVIA_C7_PORT'] = original_port
    from grant_agent.edge_journeys import offline_endpoint_error
    import socket
    for listening in (True, False):
        selected_port = 48743 if listening else 48744
        with socket.socket() as server:
            if listening:
                server.bind(('127.0.0.1', selected_port))
                server.listen(1)
            try:
                error = offline_endpoint_error(selected_port)
            except ValueError:
                assert listening, 'Unavailable TCP endpoint rejected'
            else:
                assert not listening and isinstance(error, (ConnectionRefusedError, TimeoutError)), 'Connected TCP endpoint claimed offline'
            results.append({'case': 'offline-tcp-' + ('listener-refused' if listening else 'connection-failure-observed'),
                            'status': 'passed', 'port': selected_port, 'actualSocket': True})
    # The same rejection applies when an owning contract explicitly requires
    # actual device/provider observation rather than a model/hash projection.
    for scope in ("device", "provider"):
        scoped = {identity: {**contract, "proofBoundary": scope}}
        observe(scope + "-hash-only-keeps-blocked", [row(scope, proofScope=scope, receiptIntact=True)], "blocked", selected=scoped)

    # Real family builder -> production owner -> observed case -> production
    # matrix, then an independently blocked match against that exact case.
    from grant_agent.edge_fixture_pure import run as run_pure
    real_identity = "providers.claude.identity"
    real_contracts = {real_identity: catalog[real_identity]}
    actual_rows = run_pure(root / "real-family", real_contracts, CATEGORIES)
    assert len(actual_rows) == 3 and all(value["status"] == "passed" for value in actual_rows), actual_rows
    actual = actual_rows[0]
    observe("real-family-owner-to-matrix", [actual], "passed", selected=real_contracts, selected_category=actual["category"])
    interrupted = {**actual, "id": actual["id"] + ":missing-observation", "status": "blocked"}
    observe("real-passing-owner-cannot-mask-blocked", [actual, interrupted], "blocked",
            selected=real_contracts, selected_category=actual["category"])

    authority_id='a-cli.scheduler.capabilities'
    authority_contracts={authority_id:catalog[authority_id]}
    claimed={**row('untrusted-authority-positive'),'contracts':[authority_id]}
    retained=observe('catalog-authority-cannot-be-granted-by-positive-row',[claimed],'blocked',selected=authority_contracts,semantic_fixtures=True)
    assert retained['blockerKind']=='authority_boundary'
    failed={**claimed,'id':'untrusted-authority-failed','status':'failed'}
    observe('catalog-authority-does-not-hide-failure',[claimed,failed],'failed',selected=authority_contracts,semantic_fixtures=True)

    # C7 contract cases for the family observer. These supplied receipts prove
    # refusal behavior only; they are never native or rendered campaign proof.
    from types import SimpleNamespace
    from grant_agent.edge_contracts import call as edge_call
    observer_root = root / 'observer'
    latest = observer_root / '.agent_control/c7/latest.json'
    latest.parent.mkdir(parents=True)
    supplied_receipt = REPO / '.agent_control/proofs/c7' / (uuid.uuid4().hex + '.json')
    supplied_receipt.parent.mkdir(parents=True, exist_ok=True)
    service = SimpleNamespace(bus=SimpleNamespace(root=observer_root))
    for name, statuses, builder, intact, current, expected in (
        ('family-all-cases-pass', ['passed', 'passed'], 'pure', True, True, True),
        ('family-pass-cannot-mask-blocked', ['passed', 'blocked'], 'pure', True, True, False),
        ('family-pass-cannot-mask-failed', ['failed', 'passed'], 'pure', True, True, False),
        ('family-empty-refused', [], 'pure', True, True, False),
        ('family-wrong-selection-refused', ['passed'], 'frontend', True, True, False),
        ('family-corrupt-receipt-refused', ['passed'], 'pure', False, True, False),
        ('family-stale-source-refused', ['passed'], 'pure', True, False, False),
    ):
        supplied_receipt.write_text(json.dumps({'journeys': [{'id': str(i), 'builder': builder, 'status': status}
                                                           for i, status in enumerate(statuses)]}), encoding='utf8')
        latest.write_text(json.dumps({'schema': 'neyvia.edge-contracts.v1', 'ok': True, 'complete': False,
            'inventory': {}, 'counts': {}, 'durationMs': 0, 'sourceStable': True, 'explicitPort': args.port,
            'receipt': str(supplied_receipt),
            'receiptSha256': hashlib.sha256(supplied_receipt.read_bytes()).hexdigest() if intact else '0' * 64,
            'sourceBindings': {'src/grant_agent/edge_contracts.py': bindings['src/grant_agent/edge_contracts.py'] if current else '0' * 64}}), encoding='utf8')
        value = edge_call(service, 'verify.edges.status', {'family': 'pure'})
        assert value['allApplicableCasesPassed'] is expected, (name, value)
        results.append({'case': name, 'status': 'passed', 'familyCases': value['familyCases'],
                        'observedAllApplicableCasesPassed': value['allApplicableCasesPassed']})

    assert bindings == {path: source_digest(REPO / path) for path in paths}, "Aggregation sources changed during proof"
    report = {"schema": "neyvia.c7d-aggregation.v1", "ok": True, "explicitPort": args.port,
              "cases": len(results), "results": results,
              "sourceBindings": bindings, "sourceStable": True,
              "inventoryContracts": len(catalog), "allObligationsRetained": True,
              "boundary": "Actual production matrix/inventory validator; adversarial supplied rows. No rendered/device/provider journey is claimed."}
    raw = (json.dumps(report, indent=2, ensure_ascii=True) + "\n").encode()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    print(json.dumps({"ok": True, "cases": len(results), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}))


if __name__ == "__main__":
    main()
