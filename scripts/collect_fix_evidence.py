"""Bind FIX's actual receipts, final checks, commits and remaining work."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.durability import atomic_write_json


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def load(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', required=True)
    parser.add_argument('--receipt-id', choices=('FIX', 'FIXb'), default='FIX')
    parser.add_argument('--commit-base', default='night/neyvia')
    args = parser.parse_args()
    if not args.checkpoint.replace('-', '').isalnum():
        parser.error('Use a simple checkpoint name')
    checkpoint = f'scripts/evidence/fix/checks/{args.checkpoint}'
    checks = load(checkpoint + '/results.json')
    verifier = load(checkpoint + '/verify.json')
    inventory = load('scripts/evidence/FIX-open-inventory.json')
    names = [
        'FIX-permission', 'FIX-process', 'FIX-observer-read-final',
        'FIX-observer-write', 'FIX-observer-native', 'FIX-observer-typed-final',
        'FIX-latency', 'FIX-followups', 'FIX-followups-ui', 'FIX-classic',
        'FIX-browser', 'FIX-native-browser', 'FIX-browser-ui', 'FIX-video', 'FIX-manual-fixtures',
    ]
    if (ROOT / 'scripts/evidence/FIX-evolver-ui.json').exists():
        names.append('FIX-evolver-ui')
    for name in ('FIX-reader', 'FIX-reader-ui', 'FIX-navigation-ui', 'FIX-browser-permissions',
                 'FIX-sidebar-ui', 'FIX-sidebar-network', 'FIX-sidebar-runs',
                 'FIX-workflow-readiness', 'FIX-manual-host'):
        if (ROOT / f'scripts/evidence/{name}.json').exists():
            names.append(name)
    if args.receipt_id == 'FIXb':
        names += [name for name in ('FIXb-blind', 'FIXb-sidebar-grouping',
                  'FIXb-accessibility', 'FIXb-remote', 'FIXb-cache',
                  'FIXb-provider-idle-after', 'FIXb-native-space')
                  if (ROOT / f'scripts/evidence/{name}.json').exists()]
    paths = [f'scripts/evidence/{name}.json' for name in names]
    paths += [f'scripts/evidence/fix/lead-{name}.json' for name in
              ('observer-read', 'observer-write', 'observer-typed', 'observer-native', 'sidebar', 'remote')]
    receipts = []
    for path in paths:
        data = load(path)
        passed = next((data[key] for key in ('passed', 'ok', 'allPassed')
                       if isinstance(data.get(key), bool)), None)
        if passed is None:
            passed = bool(data.get('checks')) and all(row.get('passed', row.get('ok', False)) for row in data['checks'])
        if data.get('budgetPassed') is False:
            passed = False
        sources = data.get('sources', data.get('sourceHashes', {}))
        pairs = sources.items() if isinstance(sources, dict) else (
            (row.get('path'), row.get('sha256')) for row in sources)
        bound_sources = [(name, digest) for name, digest in pairs
                         if name and isinstance(digest, str) and len(digest) == 64]
        changed_sources = [name for name, digest in bound_sources
                           if not (ROOT / name).is_file()
                           or hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
        receipts.append({'path': path, 'sha256': hashlib.sha256((ROOT / path).read_bytes()).hexdigest(),
                         'passed': passed, 'checks': len(data.get('checks', data.get('rows', []))),
                         'rawSourceBindingsChecked': len(bound_sources), 'currentRawSourceChanges': changed_sources,
                         'boundary': data.get('boundary', data.get('limitations', data.get('limits')))})
    failed_receipts = [row['path'] for row in receipts if row['passed'] is not True]
    structural_sources = {}
    for name in ('compile', 'cl', 'build', 'node'):
        inputs = ROOT / checkpoint / (name + '-inputs.json')
        if inputs.exists():
            bindings = load(inputs.relative_to(ROOT))['sourceBindings']
            structural_sources[name] = {
                'bindings': len(bindings),
                'changed': [path for path, digest in bindings.items()
                            if not (ROOT / path).is_file() or hashlib.sha256(
                                (ROOT / path).read_text(encoding='utf-8').encode()).hexdigest() != digest],
            }
    compiled_changes = [row['path'] for row in checks['compile'].get('files', [])
                        if not (ROOT / row['path']).is_file() or hashlib.sha256(
                            (ROOT / row['path']).read_bytes()).hexdigest() != row['sha256']]
    structural_ok = all(checks[name]['exitCode'] == 0 for name in ('compile', 'cl', 'build', 'node'))
    if args.receipt_id == 'FIXb':
        structural_ok = structural_ok and len(structural_sources) == 4 and all(
            not row['changed'] for row in structural_sources.values()) and not compiled_changes
    source_changes = [path for path, expected in verifier['sourceBindings'].items()
                      if hashlib.sha256((ROOT / path).read_text(encoding='utf-8').encode()).hexdigest() != expected]
    latency = load('scripts/evidence/FIX-latency.json')
    sidebar = load('scripts/evidence/fix/lead-sidebar.json')['checks'][0]['coldMs']
    remote = load('scripts/evidence/fix/lead-remote.json')
    sidebar_ui_path = 'scripts/evidence/FIX-sidebar-ui.json'
    sidebar_ui = load(sidebar_ui_path) if (ROOT / sidebar_ui_path).exists() else None
    report = {
        'schema': f'neyvia.{args.receipt_id}.v1', 'at': datetime.now(timezone.utc).isoformat(),
        'status': 'PARTIAL', 'releaseReady': False,
        'implementationHead': git('rev-parse', 'HEAD'), 'branch': git('branch', '--show-current'),
        'commitBase': git('rev-parse', args.commit_base),
        'commits': git('log', '--reverse', '--format=%H %s', args.commit_base + '..HEAD').splitlines(),
        'r4PermissionFixIntegrated': subprocess.run(['git', 'merge-base', '--is-ancestor', 'c9a073c9', 'HEAD'], cwd=ROOT).returncode == 0,
        'receipts': receipts,
        'failedAcceptanceReceipts': failed_receipts,
        'declaredRawReceiptSourcesStable': all(not row['currentRawSourceChanges'] for row in receipts),
        'latency': {'historical50ItemProjectionColdMs': [row['coldMs'] for row in latency['sidebar']['samples']] + [sidebar],
                    'remoteColdMs': latency['remote']['coldMs'], 'independentRemote': remote.get('timing', remote.get('timings')),
                    'boundaries': [latency['sidebar']['boundary'], latency['limitations']],
                    'renderedSidebar': None if sidebar_ui is None else {
                        'receipt': sidebar_ui_path, 'ok': sidebar_ui.get('ok'),
                        'budgetPassed': sidebar_ui.get('budgetPassed'),
                        'sourceStable': sidebar_ui.get('sourceStable'),
                        'definition': sidebar_ui.get('definition'), 'boundary': sidebar_ui.get('boundary'),
                        'samples': sidebar_ui.get('samples'), 'error': sidebar_ui.get('error') }},
        'finalChecks': {'checkpoint': checkpoint, 'structuralGreen': structural_ok,
                        'structuralSourceChecks': structural_sources,
                        'compiledRawSourceChanges': compiled_changes,
                        'resultsSha256': hashlib.sha256((ROOT / checkpoint / 'results.json').read_bytes()).hexdigest(),
                        'verifierSha256': hashlib.sha256((ROOT / checkpoint / 'verify.json').read_bytes()).hexdigest(),
                        'verifyExitCode': checks['verify']['exitCode'],
                        **{key: verifier[key] for key in ('contractsOk', 'complete', 'sourceStable', 'failures', 'blocked')},
                        'areaCount': len(verifier['areas']), 'currentSourceChanges': source_changes,
                        'coveragePercent': verifier['coverage']['coveragePercent'],
                        'failedAreas': [row for row in verifier['areas'] if not row.get('ok')],
                        'blockedNativeCases': [{'area': area['area'], **row} for area in verifier['areas']
                                               for row in area.get('cases', []) if row.get('status') == 'blocked'],
                        'scope': 'Integrated worktree checks; historical per-commit full-suite success is not claimed.'},
        'remaining': inventory['items'],
        'limits': ['Whole PROOFS migration and broader handoff features remain incomplete; see each disposition.',
                   'Installed desktop, physical microphone/devices, second PC and public release are unproven.',
                   'No push, merge out, NAS sync, credential/runbook read or protected-service change.'],
    }
    if args.receipt_id == 'FIXb':
        fresh_remote = ROOT / 'scripts/evidence/FIXb-remote.json'
        if fresh_remote.exists():
            report['latency']['freshRemote'] = load(fresh_remote.relative_to(ROOT))
        report['historicalEvidenceNotice'] = 'Older receipts are retained with current source drift reported; only each recorded boundary is claimed.'
    destination = ROOT / f'scripts/evidence/{args.receipt_id}.json'
    atomic_write_json(destination, report)
    print(json.dumps({'receipt': str(destination), 'realReceiptsPassed': len(receipts) - len(failed_receipts),
                      'failedAcceptanceReceipts': failed_receipts,
                      'structuralGreen': structural_ok, 'contractsOk': verifier['contractsOk'],
                      'sourceStable': verifier['sourceStable'], 'complete': verifier['complete']}))


if __name__ == '__main__':
    main()
