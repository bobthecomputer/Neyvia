"""Reconcile unchanged-source local observations with freshly witnessed native UI."""
import argparse
from collections import Counter
import hashlib
import gzip
import json
import os
from pathlib import Path
import sys
import time
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf8')


def ref(path):
    return {'path': path.relative_to(REPO).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--local-campaign', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seal-final', action='store_true', help='Seal using this campaign\'s live native observer after the compiled replays finish')
    args = parser.parse_args()
    from grant_agent.proof_ports import c7_port_block
    try:
        assigned_ports = c7_port_block(args.port)
    except ValueError as error:
        parser.error(str(error))
    prior_path, output = args.local_campaign.resolve(), args.output.resolve()
    prior_path.relative_to(REPO / 'scripts/evidence')
    output.relative_to(REPO / 'scripts/evidence')
    from c7_dependencies import configure
    configure()
    prior_raw = prior_path.read_bytes()
    prior = json.loads(prior_raw)
    if 'fullReceipt' in prior:
        prior_archive = REPO / prior['fullReceipt']['path']
        if ref(prior_archive)['sha256'] != prior['fullReceipt']['sha256']:
            raise ValueError('Corrupt local observation archive')
        prior_raw = gzip.decompress(prior_archive.read_bytes())
        prior = json.loads(prior_raw)
    else:
        prior_archive = prior_path.with_name(prior_path.stem + '-full.json.gz')
        prior_archive.write_bytes(gzip.compress(prior_raw, mtime=0))
        if gzip.decompress(prior_archive.read_bytes()) != prior_raw:
            raise ValueError('Local observation archive differs')
        write(prior_path, {key: prior[key] for key in ('ok', 'sourceStable', 'explicitPort', 'root', 'counts')} | {'fullReceipt':ref(prior_archive)})
    if not prior['ok'] or not prior['sourceStable'] or prior['failures'] or prior['explicitPort'] != args.port:
        raise ValueError('Local observations are not passing and source-stable')
    root = REPO / '.agent_control/proofs/c7' / uuid.uuid4().hex
    root.mkdir(parents=True)
    for key in ('HOME', 'USERPROFILE', 'CODEX_HOME', 'HERMES_HOME', 'OPENCLAW_STATE_DIR', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP'):
        directory = root / 'home' / key.lower()
        directory.mkdir(parents=True)
        os.environ[key] = str(directory)
    for key in ('NEYVIA_UI_STATE_ROOT', 'NEYVIA_UI_BACKEND_URL', 'FLUXIO_WEB_BACKEND_URL', 'FLUXIO_WORKSPACE_ROOT', 'NEYVIA_NAS_ROOT', 'FLUXIO_NAS_ROOT'):
        os.environ.pop(key, None)
    os.environ.update(NEYVIA_C7_PORT=str(args.port), NEYVIA_TOOL_AUTO_UPDATE='0', NEYVIA_COORDINATOR_AUTOSTART='0', FLUXIO_WATCHDOG_AUTOSTART='0', PYTHONPATH=str(REPO / 'src'), NEYVIA_NAS_ROOT=str(root))
    from grant_agent.proof_credential_guard import install, prepare_broker_fixture
    install(root)
    prepare_broker_fixture(root)
    from grant_agent.proof_ports import configure_ports
    configure_ports(assigned_ports)
    def audit(event, values):
        if event in {'socket.connect', 'socket.bind'}:
            address = values[1]
            if not isinstance(address, tuple) or address[0] not in {'127.0.0.1', '::1'} or address[1] not in assigned_ports:
                raise PermissionError('Assigned loopback ports only')
    sys.addaudithook(audit)
    from grant_agent.proof_contracts import source_digest
    from grant_agent.edge_fixture_catalog import BUILDERS, completed_receipts, run, summarize
    from grant_agent.edge_contracts import inventory, CATEGORIES, matrix, summary, proof_boundary
    from grant_agent.edge_live_observations import LiveObservations
    bindings = dict(prior['sourceBindings'])
    bindings[Path(__file__).relative_to(REPO).as_posix()] = source_digest(Path(__file__))
    if args.seal_final:
        bindings['scripts/seal_C7_final.py'] = source_digest(REPO / 'scripts/seal_C7_final.py')
    def current():
        return all(source_digest(REPO / name) == expected for name, expected in bindings.items())
    if not current():
        raise ValueError('Local campaign source has changed')
    old_families = completed_receipts(Path(prior['root']) / 'semantic-fixtures')
    if old_families != prior['familyReceipts'] or {r['family'] for r in old_families} != set(BUILDERS) - {'c7d-rendered'}:
        raise ValueError('Expected all 43 local families')
    _, contracts = inventory()
    for row in prior['journeys']:
        if row.get('proofScope') in {'rendered', 'device', 'provider'} or row.get('liveObservationNonce') or row.get('liveObservation') or any(proof_boundary(contracts[c]) in {'rendered', 'device', 'provider'} for c in row['contracts']):
            raise ValueError('Cannot reuse real-boundary observations: ' + row['id'])
    from grant_agent.neyvia_mcp_stdio import CompactNeyviaMCPServer
    from grant_agent.neyvia_manuals import unwrap, expect
    server = CompactNeyviaMCPServer(root, read_only=True, session_id='c7e-reconcile')
    calls = []
    def rpc(tool, arguments):
        answer = server.handle({'jsonrpc': '2.0', 'id': len(calls) + 1, 'method': 'tools/call', 'params': {'name': tool, 'arguments': arguments}})
        if answer.get('error'):
            raise ValueError(answer['error'])
        result = unwrap(answer['result']['structuredContent'])
        if result.get('ok') is False:
            raise ValueError(result)
        calls.append({'tool': tool, 'arguments': arguments, 'result': result})
        return result
    rpc('neyvia.manual.load', {'id': 'edge-contracts', 'chapter': 'campaign'})
    rpc('neyvia.manual.validate', {'id': 'edge-contracts'})
    started = time.perf_counter()
    observer = LiveObservations()
    semantic_root = root / 'semantic-fixtures'
    native = run(semantic_root, contracts, CATEGORIES, ['c7d-rendered'], live_observations=observer)
    index = completed_receipts(semantic_root)
    for entry in old_families:
        destination = semantic_root / (entry['family'] + '.receipt.json')
        destination.write_bytes(Path(entry['path']).read_bytes())
        index.append({**entry, 'path': str(destination), 'observationOrigin': entry['path']})
    write(semantic_root / 'families.json', index)
    completed_receipts(semantic_root)
    journeys = prior['journeys'] + native
    if len({r['id'] for r in journeys}) != len(journeys):
        raise ValueError('Duplicate fixture cases')
    coverage = matrix(contracts, journeys, semantic_fixtures=True, proof_observer=observer)
    report = {**prior, 'root': str(root), 'journeys': journeys, 'semanticCoverage': coverage,
              'familyReceipts': index, 'sourceBindings': bindings, 'sourceStable': current(),
              'semanticSummary': summarize(coverage), 'durationMs': round(prior['durationMs'] + (time.perf_counter() - started) * 1000, 2),
              'localObservationReuse': {'campaign': ref(prior_archive), 'uncompressedSha256':hashlib.sha256(prior_raw).hexdigest(), 'families': 43, 'unchangedSourceRequired': True, 'realBoundaryReuse': False},
              'boundary': 'Previously executed unchanged-source local effects plus freshly witnessed native Neyvia browser effects; no cached rendered/device/provider proof'}
    report['failures'] = [r for r in report['schemaCases'] + report['postconditionCases'] + journeys if r['status'] == 'failed']
    report['ok'] = not report['failures'] and report['sourceStable']
    report['complete'] = report['ok'] and not report['schemaFrontier'] and not report['postconditionFrontier'] and all(r['status'] == 'passed' for r in coverage)
    report['counts'] = {name: dict(Counter(r['status'] for r in report[field])) for name, field in {'schema':'schemaCases', 'postconditions':'postconditionCases', 'journeys':'journeys', 'semanticCoverage':'semanticCoverage'}.items()}
    baseline = json.loads((REPO / 'scripts/evidence/C7.json').read_bytes())
    actual = {(r['contract'], r['category']): r for r in coverage}
    report['baseline']['formerlyBlocked'] = dict(Counter(actual[(r['contract'], r['category'])]['status'] for r in baseline['semanticCoverage'] if r['status'] == 'blocked'))
    receipt = root / 'campaign.json'
    write(receipt, report)
    write(root / '.agent_control/c7/latest.json', {**summary(report), 'sourceBindings': bindings, 'receipt': str(receipt), 'receiptSha256': ref(receipt)['sha256']})
    rpc('neyvia.manual.observe', {'id':'edge-contracts', 'chapter':'campaign', 'state':'latest'})
    status = rpc('neyvia.verify.edges.status', {})
    checks = json.loads((REPO / 'manuals/edge-contracts.manual.json').read_bytes())['chapters']['campaign']['checks']
    outcomes = [{'check': name, 'passed': expect(status, check['expect'], {}, {}, root)} for name, check in checks.items()]
    if not status['receiptIntact'] or not all(r['passed'] for r in outcomes):
        raise ValueError('Manual observer predicates failed')
    host_path = output.with_name(output.stem + '-host.json')
    write(host_path, {'ok':True, 'transport':'actual CompactNeyviaMCPServer JSON-RPC', 'manualCompleted':False, 'manualChecks':outcomes, 'calls':calls, 'boundary':'Authored observer predicates; full procedure was not replayed'})
    report['hostProof'] = {**ref(host_path), 'manualCompleted':False, 'freshChecks':len(outcomes)}
    write(output, report)
    print(json.dumps({'ok':report['ok'], 'counts':report['counts'], 'root':str(root)}))
    if args.seal_final:
        from seal_C7_final import compiled_proofs, seal
        while True:
            try:
                compiled_proofs(output.parent)
                break
            except (OSError, ValueError, KeyError):
                time.sleep(5)
        seal(output, args.port, proof_observer=observer)
    return int(not report['ok'])


if __name__ == '__main__':
    raise SystemExit(main())
