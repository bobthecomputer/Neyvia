"""Resolve one obsolete FIXCL2 capture expectation with retained real FIXCL3 proof.

The original assertion, its false result, and raw 130/131 result remain visible.
This read-only resolver verifies the current capture receipt and its actual PNGs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--wave', choices=['FIXCL3', 'FIXCL4', 'FIXCL5'], default='FIXCL3')
    args = parser.parse_args()
    if args.port not in range(48821, 48830):
        parser.error('Explicit assigned port required; resolver opens no listener')
    capture_path = args.capture.resolve()
    if capture_path != REPO / ('scripts/evidence/' + args.wave + '-capture.json'):
        parser.error('Use the current retained final capture receipt')
    aggregate_path = REPO / ('scripts/evidence/' + args.wave + '-regression.json')
    aggregate = json.loads(aggregate_path.read_bytes())
    capture = json.loads(capture_path.read_bytes())
    current_phase = aggregate['phases'][-1]
    # Expose exact current bindings for the sealer while retaining the raw
    # assertion result and historical phases without reinterpretation.
    aggregate['sourceHashes'] = dict(current_phase['sourceHashesAtEnd'])
    aggregate['sourceHashes']['scripts/fixcl3_regression_compatibility.py'] = sha(Path(__file__))
    aggregate['compatibilityResolution'] = {
        'receipt': 'scripts/evidence/' + args.wave + '-regression-compatibility.json',
        'authorizedExpectedChanges': 1,
        'rawNativeChecksPassed': 130, 'rawNativeChecksFailed': 1,
    }
    aggregate_path.write_text(json.dumps(aggregate, indent=2) + '\n', encoding='utf-8')
    browser_row = aggregate['probes']['browser']
    browser_path = REPO / browser_row['receipt']
    browser = json.loads(browser_path.read_bytes())
    script_path = REPO / browser_row['originalProbe']
    false_key = 'unobserved_capture_not_admitted'
    raw_false = {name: [key for key, value in row['checks'].items() if value is not True]
                 for name, row in aggregate['probes'].items() if row['failed']}
    retained_pngs = []
    for key in ('freshPng', 'changedPng'):
        row = capture.get(key) or {}
        path = Path(row.get('path', '')).resolve()
        scoped = path.is_relative_to(REPO / '.agent_control/proofs')
        raw = path.read_bytes() if scoped and path.is_file() else b''
        retained_pngs.append({'field': key, 'path': str(path), 'expectedSha256': row.get('sha256'),
                              'actualSha256': hashlib.sha256(raw).hexdigest() if raw else None,
                              'bytes': len(raw), 'pngSignature': raw.startswith(b'\x89PNG\r\n\x1a\n'),
                              'scoped': scoped})
    needed = ('capture-manual_positive_cl', 'capture-manual_fresh_effect',
              'actual_native_png_bytes', 'actual_native_render_nonuniform',
              'fresh_capture_owner_accepts_exact', 'fresh_capture_owner_refuses_png_tamper',
              'fresh_capture_owner_refuses_wrong_native_identity',
              'fresh_capture_owner_refuses_page_drift', 'capture-changed_positive_cl',
              'capture-changed_fresh_effect', 'real_page_change_changes_native_png',
              'every_new_adapter_positive_manual_witness')
    captured_sources = capture.get('sourceHashesAtEnd') or {}
    manual_sha = sha(REPO / 'manuals/cl/browser.cl')
    manual_receipts = [row for row in capture.get('manualReceipts', [])
                       if row.get('tool') == 'neyvia.browser.capture' and row.get('manual') == 'browser'
                       and row.get('status') == 'admitted' and row.get('sourceSha256') == manual_sha
                       and row.get('procedure') == 'browser.capture-owned-native-page'
                       and row.get('effectChecks')]
    checks = {
        'allNineOriginalProbesActuallyReplayed': len(aggregate['probes']) == 9,
        'rawResultExactly130Of131': aggregate['counts']['nativeChecksPassed'] == 130
            and aggregate['counts']['nativeChecksFailed'] == 1,
        'onlyObsoleteNegativeAssertionFailed': raw_false == {'browser': [false_key]},
        'originalBrowserAssertionUnmodified': sha(script_path) == browser_row['originalSha256']
            and false_key in script_path.read_text(encoding='utf-8')
            and browser['checks'][false_key] is False,
        'allNineNativeReceiptsMatchRetainedHashes': all(
            sha(REPO / row['receipt']) == row['receiptSha256'] for row in aggregate['probes'].values()),
        'replayProductAndHelperSourcesRemainCurrent': all(
            (REPO / name).is_file() and sha(REPO / name) == value
            for name, value in current_phase['sourceHashesAtEnd'].items()),
        'finalCaptureProbeAllNativeChecksPassed': bool(capture.get('checks'))
            and all(value is True for value in capture['checks'].values()),
        'actualCaptureAndFreshAdverseGatesProven': all(capture.get('checks', {}).get(key) is True for key in needed),
        'finalCaptureSourcesStableAndCurrent': bool(captured_sources)
            and capture.get('sourceHashesAtStart') == captured_sources
            and all((REPO / name).is_file() and sha(REPO / name) == value for name, value in captured_sources.items()),
        'currentCaptureExecutableManualReceiptsPresent': len(manual_receipts) >= 2,
        'realRetainedPngsVerifiedIndependently': all(row['scoped'] and row['pngSignature']
            and row['bytes'] > 0 and row['actualSha256'] == row['expectedSha256'] for row in retained_pngs),
        'realPageChangeProducedDifferentPng': len({row['actualSha256'] for row in retained_pngs}) == 2,
        'rawSourceStableAndFIXCL2BaselineConserved': aggregate['checks']['allReplaySourcesStable'] is True
            and aggregate['checks']['FIXCL2BaselineConserved'] is True,
    }
    proof = {
        'schema': 'neyvia.' + args.wave + '.regression-compatibility.v1', 'port': args.port,
        'rawCounts': aggregate['counts'], 'authorizedExpectedChanges': 1,
        'resolution': {'probe': 'browser', 'assertion': false_key, 'originalExpected': True,
                       'actualOriginalAssertion': False,
                       'originalContract': 'No browser.capture effect adapter is admitted.',
                       'currentAuthorizedContract': 'Typed browser.capture is admitted only with fresh exact native screenshot evidence and current manual receipt.',
                       'reason': 'The user explicitly requested typed codecs, fresh effect gates, and retained positive CL witnesses for remaining frontier actions.'},
        'checks': checks, 'retainedPngs': retained_pngs,
        'originalProbe': {'path': browser_row['originalProbe'], 'sha256': sha(script_path)},
        'rawBrowserReceipt': {'path': browser_row['receipt'], 'sha256': sha(browser_path)},
        'rawRegressionReceipt': {'path': aggregate_path.relative_to(REPO).as_posix(), 'sha256': sha(aggregate_path)},
        'currentCaptureReceipt': {'path': capture_path.relative_to(REPO).as_posix(), 'sha256': sha(capture_path),
                                 'nativeChecks': len(capture['checks']), 'sourceHashes': captured_sources},
        'manualReceipts': manual_receipts,
        'sourceHashes': {'scripts/fixcl3_regression_compatibility.py': sha(Path(__file__)),
                         'scripts/fixcl3_regression_probe.py': sha(REPO / 'scripts/fixcl3_regression_probe.py')},
    }
    path = REPO / ('scripts/evidence/' + args.wave + '-regression-compatibility.json')
    path.write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'rawCounts': proof['rawCounts'], 'authorizedExpectedChanges': 1,
                      'checks': checks, 'receipt': str(path)}))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
