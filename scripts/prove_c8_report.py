"""Exercise the real Inception report tool and adverse receipts on owned HTTP."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import uuid

from c8_desktop_guard import DesktopGuard
from c8_journey import Candidate
from run_c8_inception import REPO, confined, launch, stop, write, port


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=port, required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    report_path = Path(args.report).resolve()
    report_path.relative_to(REPO / 'scripts/evidence')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    root = confined(REPO / '.agent_control/proofs/C8' / ('report-check-' + uuid.uuid4().hex))
    latest = root / '.neyvia/inception/latest.json'
    original = {'results': [row['result'] for row in report['rows'] if row.get('result')], 'provenance': report['provenance']}
    checks = []
    process = handle = None
    guard = DesktopGuard(); guard.start()
    try:
        write(latest, original)
        process, handle, url = launch(REPO, root, Path(original['provenance']['candidate']['build']), args.port, root / 'backend.log')
        client = Candidate(url)
        control = client.tool('inception.report')
        expected_passed = sum(row['webStatus'] == 'passed' for row in report['rows'])
        checks.append({'id': 'real-tool-control', 'passed': control['counts']['webPassed'] == expected_passed and not control['errors'] and not control['releaseGate'], 'observed': {'counts': control['counts'], 'errors': control['errors'], 'releaseGate': control['releaseGate']}})
        summaries = control['perManual']
        checks.append({'id': 'per-manual-outcomes-conserved', 'passed': (
            sum(item['expected'] for item in summaries.values()) == control['counts']['expected']
            and sum(item['web']['pass'] for item in summaries.values()) == control['counts']['webPassed']
            and all(sum(item['web'].values()) == item['expected'] == sum(item['release'].values()) for item in summaries.values())
            and all(row['failureClassification'] in {'product bug', 'journey bug', 'environment'} and row['error'] for row in control['rows'] if row['webOutcome'] == 'fail')
            and all(row['waitingFor'] == 'C11' and row['waitingStep'] for row in control['rows'] if row['outcome'] == 'waiting')),
            'observed': {'manuals': len(summaries), 'counts': control['counts']}})
        executed = next(r['result'] for r in control['rows'] if r['webStatus'] == 'passed' and r['result'].get('t18'))
        proof = Path(executed['t18'][0]['proof'])
        proof.relative_to(REPO / 'scripts/evidence/C8-runs')
        copied = root / 'tampered-proof.json'
        shutil.copyfile(proof, copied)
        changed = json.loads(json.dumps(original))
        target = next(r for r in changed['results'] if r['id'] == executed['id'])
        target['t18'][0]['proof'] = str(copied)
        copied.write_bytes(copied.read_bytes() + b' ')
        write(latest, changed)
        observed = client.tool('inception.report')
        checks.append({'id': 'actual-proof-bytes-changed', 'passed': observed['counts']['webPassed'] == control['counts']['webPassed'] - 1, 'observed': observed['counts']})
        changed = json.loads(json.dumps(original))
        target = next(r for r in changed['results'] if r['id'] == executed['id'])
        target['goals'][0]['passed'] = False
        write(latest, changed)
        observed = client.tool('inception.report')
        rejected = next(row for row in observed['rows'] if row['id'] == executed['id'])
        checks.append({'id': 'failed-goal-classified-and-rejected', 'passed': (
            observed['counts']['webPassed'] == control['counts']['webPassed'] - 1
            and rejected['webOutcome'] == 'fail' and rejected['failureClassification'] == 'journey bug'
            and not observed['releaseGate']), 'observed': {key: rejected[key] for key in ('id', 'webOutcome', 'failureClassification', 'webReasons')}})
        changed = json.loads(json.dumps(original))
        target = next(r for r in changed['results'] if r['id'] == executed['id'])
        target['pageErrors'] = ['Controlled invalid receipt: unhandled candidate page error']
        write(latest, changed)
        observed = client.tool('inception.report')
        checks.append({'id': 'unhandled-page-error-refuses-pass', 'passed': observed['counts']['webPassed'] == control['counts']['webPassed'] - 1,
                       'observed': observed['counts']})
        effect_row = next(r['result'] for r in control['rows'] if r['webStatus'] == 'passed' and (r['result'].get('effectEvidence') or {}).get('contractEffects'))
        for case in ('status-only', 'missing-contract', 'synthetic-boundary', 'failed-matched-case', 'empty-effect-observation', 'missing-producer'):
            changed = json.loads(json.dumps(original))
            target = next(r for r in changed['results'] if r['id'] == effect_row['id'])
            effect = target['effectEvidence']
            if case == 'status-only':
                del target['effectEvidence']
            elif case == 'missing-contract':
                effect['contractEffects'].pop()
            elif case == 'synthetic-boundary':
                effect['contractEffects'][0]['boundary'] = 'synthetic-frontend-model'
            elif case == 'failed-matched-case':
                failed = dict(effect['contractEffects'][0], passed=False)
                effect['contractEffects'].append(failed)
            elif case == 'empty-effect-observation':
                effect['contractEffects'][0]['observed'] = {}
            else:
                target['calls'] = [c for c in target['calls'] if c.get('tool') != 'neyvia.verify']
            write(latest, changed)
            observed = client.tool('inception.report')
            rejected = next(row for row in observed['rows'] if row['id'] == effect_row['id'])
            checks.append({'id': 'F10-' + case, 'passed': observed['counts']['webPassed'] == control['counts']['webPassed'] - 1
                           and rejected['webStatus'] != 'passed' and observed['releaseGate'] is False,
                           'observed': {'counts': observed['counts'], 'reasons': rejected['webReasons']}})
        changed = json.loads(json.dumps(original)); del changed['provenance']['candidateSourceHashes']
        write(latest, changed)
        observed = client.tool('inception.report')
        checks.append({'id': 'missing-source-manifest', 'passed': 'Complete candidate source hash manifest required' in observed['errors'], 'observed': observed['errors']})
        changed = json.loads(json.dumps(original)); changed['provenance']['desktopGuard']['passed'] = False
        write(latest, changed)
        observed = client.tool('inception.report')
        checks.append({'id': 'saved-desktop-failure-retained', 'passed': 'Owned desktop guard failed' in observed['errors'], 'observed': observed['errors']})
        latest.write_text('{', encoding='utf-8')
        observed = client.tool('inception.report')
        checks.append({'id': 'malformed-receipt-blocked', 'passed': observed['releaseGate'] is False and bool(observed['errors']), 'observed': observed})
        write(latest, original)
        restored = client.tool('inception.report')
        checks.append({'id': 'control-restored', 'passed': restored['counts'] == control['counts'] and restored['errors'] == control['errors'], 'observed': restored['counts']})
    finally:
        if process:
            stop(process)
        if handle:
            handle.close()
        desktop = guard.finish()
        result = {'checks': checks, 'desktopGuard': desktop, 'target': f'http://127.0.0.1:{args.port}',
                  'passed': len(checks) == 15 and all(c['passed'] for c in checks) and desktop['passed']}
        path = REPO / 'scripts/evidence/C8-runs' / root.name / 'revalidation.json'; write(path, result)
        report['reportRevalidation'] = {**result, 'proof': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        write(report_path, report)
    print(json.dumps({'passed': result['passed'], 'checks': checks, 'desktopGuardPassed': desktop['passed']}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
