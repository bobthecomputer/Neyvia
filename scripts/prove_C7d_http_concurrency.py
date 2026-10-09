"""Observe real owned HTTP owner runs and request threads without retries."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.port not in (48742, 48744):
        parser.error('Explicit owned HTTP port required')
    output = args.output.resolve(); output.relative_to(REPO / 'scripts/evidence')
    root = REPO / '.agent_control/proofs' / ('c7d-http-' + uuid.uuid4().hex)
    root.mkdir()
    for key in ('HOME', 'USERPROFILE', 'CODEX_HOME', 'HERMES_HOME', 'OPENCLAW_STATE_DIR', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP'):
        folder = root / 'home' / key.lower(); folder.mkdir(parents=True)
        os.environ[key] = str(folder)
    for key in ('NEYVIA_UI_STATE_ROOT', 'NEYVIA_UI_BACKEND_URL', 'FLUXIO_WORKSPACE_ROOT', 'FLUXIO_NAS_ROOT'):
        os.environ.pop(key, None)
    os.environ.update(NEYVIA_NAS_ROOT=str(root), NEYVIA_C7_PORT=str(args.port), NEYVIA_TOOL_AUTO_UPDATE='0', FLUXIO_WATCHDOG_AUTOSTART='0', NEYVIA_COORDINATOR_AUTOSTART='0', PYTHONPATH=str(REPO/'src'), PYTHONIOENCODING='utf-8')
    from grant_agent.proof_credential_guard import install
    install(root)
    def audit(event, values):
        if event in ('socket.connect', 'socket.bind'):
            address = values[1]
            if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', '::1') or address[1] not in range(48741, 48750):
                raise PermissionError('Owned explicit C7 loopback port required')
    sys.addaudithook(audit)
    from grant_agent.proof_ports import configure_ports
    configure_ports(list(range(48741, 48750)))
    from grant_agent.edge_contracts import inventory, CATEGORIES
    from grant_agent.proof_contracts import source_digest
    from grant_agent import edge_fixture_c7d_wz as fixture
    names = ['scripts/prove_C7d_http_concurrency.py', 'src/grant_agent/edge_fixture_c7d_wz.py', 'src/grant_agent/web_backend.py', 'src/grant_agent/web_backend_http.py', 'src/grant_agent/proofs_e_wz.py', 'src/grant_agent/local_network_policy.py']
    bindings = {name: source_digest(REPO/name) for name in names}
    _, contracts = inventory()
    rows = []
    observations = []
    for name in sorted(fixture.HTTP):
        identity = 'proofs-e-wz.' + name
        for category in CATEGORIES:
            if fixture.blocker(contracts[identity], category):
                continue
            area = root / (name + '-' + category); area.mkdir()
            start = time.monotonic()
            row = {'id': 'c7d-wz.'+name+'.'+category, 'contracts': [identity], 'category': category}
            try:
                row.update(status='passed', detail=fixture._http(area, category, name))
            except Exception as error:
                row.update(status='failed', detail={'type': type(error).__name__, 'error': str(error), 'traceback': traceback.format_exc()})
            for path in (area/'http-thread-stacks.txt', area/'http-request-events.json'):
                observations.append({'caseId':row['id'],'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size})
            row['durationMs'] = round((time.monotonic()-start)*1000)
            rows.append(row)
            (root/'progress.json').write_text(json.dumps(rows, indent=2)+'\n', encoding='utf-8')
            print(json.dumps({k:row[k] for k in ('id','status','durationMs')}), flush=True)
    before = REPO/'.agent_control/proofs/c7/250a7350507c4ac28291578fc28f6a5c/semantic-fixtures/c7d-wz.receipt.json'
    old = json.loads(before.read_text(encoding='utf-8'))
    stable = bindings == {name: source_digest(REPO/name) for name in names}
    aborted_prefix = REPO/'.agent_control/proofs/c7d-http-605e1a13fef9468880cd5ff5b81e95dd/prefix/c7d-control/case-progress.jsonl'
    report = {'schema':'neyvia.c7d-http-concurrency.v1', 'ok':stable and all(row['status']=='passed' for row in rows), 'sourceStable':stable, 'sourceBindings':bindings, 'root':str(root), 'explicitPort':args.port, 'rows':rows,
              'beforeFailedCases':[row for row in old['rows'] if row['status']=='failed'], 'beforeReceipt':str(before), 'beforeSha256':hashlib.sha256(before.read_bytes()).hexdigest(),
              'abortedPrefixDiagnostic':{'path':str(aborted_prefix),'sha256':hashlib.sha256(aborted_prefix.read_bytes()).hexdigest(),'completionReceipt':False,'reason':'Stopped when an unrelated parent campaign-budget source change invalidated the catalog prefix binding; no HTTP result was obtained.'},
              'observations':observations, 'originalFailureCause':'Original15s full-campaign failures had no live stacks. A later fullWZ run measured policy-lock contention; the exact held-SQLite-writer reproducer then failed real HTTP before the loopback policy repair and passed afterward. Attribution of the original15s failures to that measured mechanism is an inference; the final full campaign must pass independently.',
              'boundary':'Actual production HTTP handlers, gzip codec, socket transfer and generated disposable account; fixture retains thread timing without retries or deadline changes. This isolated matrix does not substitute for the full campaign or render/provider/public proof.'}
    policy_report=REPO/'scripts/evidence/C7d-loopback-policy.json'
    repaired=json.loads(policy_report.read_text(encoding='utf-8'))
    if not repaired['ok'] or not repaired['sourceStable'] or repaired['externalOSAttempts']:
        raise AssertionError('Actual loopback policy repair proof is not passing')
    if repaired['sourceBindings']['src/grant_agent/local_network_policy.py']!=bindings['src/grant_agent/local_network_policy.py']:
        raise AssertionError('Policy repair proof is stale')
    report['policyRepairProof']={'path':str(policy_report),'sha256':hashlib.sha256(policy_report.read_bytes()).hexdigest()}
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'ok':report['ok'],'passed':sum(row['status']=='passed' for row in rows),'failed':sum(row['status']=='failed' for row in rows),'root':str(root)}))
    return int(not report['ok'])


if __name__ == '__main__':
    raise SystemExit(main())
