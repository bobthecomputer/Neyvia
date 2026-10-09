"""Run real authored manual checks through reviewed, confined local fixtures."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def main():
    root = REPO / '.agent_control/proofs' / ('FIX-manual-fixtures-' + uuid.uuid4().hex)
    root.mkdir(parents=True)
    for key in ('NEYVIA_UI_STATE_ROOT', 'NEYVIA_UI_BACKEND_URL', 'FLUXIO_WORKSPACE_ROOT'):
        os.environ.pop(key, None)
    from grant_agent.proof_credential_guard import install, prepare_broker_fixture
    install(root)
    prepare_broker_fixture(root)
    from grant_agent.proof_verifier import manual_self_checks
    rows = manual_self_checks(root)
    wanted = {('design', 'overview', 'themes'), ('design', 'tokens-themes', 'themes'),
              ('neyvia', 'time', 'current'), ('neyvia-reference', 'time', 'current'),
              ('settings', 'overview', 'preferences'), ('settings', 'overview', 'current'),
              ('settings', 'overview', 'read-preferences'), ('transparency', 'overview', 'current'),
              ('voice', 'overview', 'grammar'),
              ('workspace', 'files', 'current'), ('workspace', 'files', 'create-and-confirm'),
              ('workspace', 'files', 'read-and-confirm'), ('tools-depth', 'tools', 'file'),
              ('efficiency', 'cascade', 'latency'), ('efficiency', 'cascade', 'learned'),
              ('efficiency', 'cascade', 'inspect-cost'), ('efficiency', 'cascade', 'extract-and-confirm')}
    selected = [row for row in rows if (row['manual'], row.get('chapter'), row.get('id')) in wanted]
    failures = [row for row in rows if row['status'] == 'failed']
    written = root / 'confirmed.txt'
    exact_write = written.is_file() and written.read_bytes() == 'Exact scratch write: Élodie 000739\n'.encode('utf-8')
    procedure_receipts = []
    for path in (root / '.neyvia/manual-runs').glob('*.json'):
        actual = json.loads(path.read_text(encoding='utf-8'))
        if (actual.get('id'), actual.get('chapter'), actual.get('procedure')) in {
            ('workspace', 'files', 'create-and-confirm'),
            ('workspace', 'files', 'read-and-confirm'),
            ('efficiency', 'cascade', 'extract-and-confirm'),
        }:
            procedure_receipts.append(actual)
    extraction = next((row['results']['extraction'] for row in procedure_receipts
                       if row['id'] == 'efficiency'), {})
    exact_script = (extraction.get('route') == 'script' and extraction.get('modelCalls') == []
                    and extraction.get('answer') == {
                        'valueJson': '{"id":"000739","name":"Élodie"}',
                        'sourceSha256': hashlib.sha256((root / 'exact.json').read_bytes()).hexdigest()})
    report = {'schema': 'neyvia.FIX.manual-fixtures.v1', 'root': str(root),
              'passed': len(selected) == len(wanted) and all(row['status'] == 'passed' for row in selected) and not failures and exact_write and exact_script,
              'checks': selected, 'remainingBlocked': sum(row['status'] == 'blocked' for row in rows),
              'independentWrittenBytes': exact_write,
              'independentExactScript': exact_script, 'productionProcedureReceipts': procedure_receipts,
              'otherFailures': failures,
              'sources': {path: hashlib.sha256((REPO / path).read_bytes()).hexdigest() for path in
                          ('src/grant_agent/proof_verifier.py', 'web/src/neyvia/next/nxThemes.css',
                           'web/src/neyvia/next/nxTokens.css', 'web/src/neyvia/next/details/details.manifest.json',
                           'src/grant_agent/neyvia_efficiency.py', 'src/grant_agent/efficiency_cascade.py',
                           'manuals/cl/workspace.cl', 'manuals/cl/efficiency.cl', 'scripts/prove_fix_manual_fixtures.py')},
              'boundary': 'Real registered tools and authored manual checks in an explicit scratch workspace with protected-file guard; exact authored source fixtures. No rendered theme or global policy change claim.'}
    destination = REPO / 'scripts/evidence/FIX-manual-fixtures.json'
    destination.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'checks': len(selected), 'failures': failures,
                      'blocked': report['remainingBlocked']}))
    return int(not report['passed'])


if __name__ == '__main__':
    raise SystemExit(main())
