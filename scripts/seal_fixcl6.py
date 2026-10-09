"""Seal independently checked FIXCL6 evidence, retaining failure boundaries."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

REPO = Path(__file__).resolve().parents[1]
EVIDENCE = REPO / 'scripts/evidence'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session-log', type=Path, required=True)
    args = parser.parse_args()
    audit = json.loads((EVIDENCE / 'FIXCL6-AUD4-after.json').read_bytes())
    proof = json.loads((EVIDENCE / 'FIXCL6-sdk-mount.json').read_bytes())
    snapshot = json.loads((EVIDENCE / 'FIXCL6-AUD4-after-snapshots.json').read_bytes())
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=REPO, text=True).strip()
    if branch != 'track/fix-cl':
        raise ValueError('FIXCL6 seals only the authorized branch')
    source = snapshot['sourceHashesAtStart']
    conserved = all(sha(REPO / name) == digest for name, digest in source.items())
    screenshot = proof['screenshot']
    image = Path(screenshot['path']).resolve()
    if not image.is_relative_to(EVIDENCE.resolve()):
        raise ValueError('Only task-owned screenshot evidence is admitted')
    checks = {
        'all185AuditCellsAssessed': sum(audit['counts'].values()) == 185 and all(audit['checks'].values()),
        'snapshotSourcesConserved': conserved and source == snapshot['sourceHashesAtEnd'],
        'sdkJourneySourcesConserved': proof['sourceHashesAtStart'] == proof['sourceHashesAtEnd'] and
            all(sha(REPO / name) == digest for name, digest in proof['sourceHashesAtStart'].items()),
        'nativeScreenshotHashMatches': sha(image) == screenshot['sha256'],
        'phoneLayoutVisible': proof['checks']['sdk.nativePhoneActuallyVisible'],
        'actualOverlayWithdrawsVisibility': proof['checks']['sdk.overlayVisibilityObserverWithdraws'],
        'uncoveredVisibilityReturns': proof['checks']['sdk.uncoveredVisibilityObserverReturns'],
        'blankSdkRefusesPositiveCompletion': proof['checks']['sdk.previewActualPositiveCL'] is False,
        'noPositiveManualClaimFromFailedEffect': proof['checks']['sdk.currentManualEffectReceipt'] is False,
        'goalAll185Green': audit['counts'].get('G') == 185,
        'goalActualSdkPhoneContent': proof.get('ok') is True,
    }
    if not all(value for key, value in checks.items() if not key.startswith('goal')):
        raise ValueError('Evidence seal failed: ' + repr(checks))
    usage = None
    # Read only this exact current session's event counters, never prompts or credentials.
    with args.session_log.open(encoding='utf-8') as stream:
        for line in stream:
            event = json.loads(line)
            if event.get('type') == 'event_msg' and event.get('payload', {}).get('type') == 'token_count':
                info = event['payload'].get('info')
                if info:
                    usage = info.get('total_token_usage')
    files = ['FIXCL6-AUD4-after.json', 'FIXCL6-AUD4-after-snapshots.json',
             'FIXCL6-sdk-mount.json', 'FIXCL6-sdk-phone.png', 'FIXCL6-harness-gaps.md']
    baseline = json.loads((EVIDENCE / 'FIXCL5.json').read_bytes())
    sdk_frames = proof['sdkActualShell']['dom']['phone']['frames']
    failed = [key for key, value in proof['checks'].items() if value is not True]
    result = {
        'schema': 'neyvia.FIXCL6.v1', 'status': 'partial_renderer_blocked', 'branch': branch,
        'baseCommit': '6382993af', 'checks': checks, 'AUD4': {
            'counts': audit['counts'], 'priorFIXCL5Counts': baseline['AUD4']['counts'],
            'receipt': 'FIXCL6-AUD4-after.json',
            'comparisonBoundary': 'Same AUD4 surfaces/criteria and source-conservation rules. Source changes invalidate old broad source-bound witnesses; reduced green count is not an asserted behavioral regression.'},
        'sdk': {'complete': False, 'failedChecks': failed, 'frames': sdk_frames,
            'nativePixels': proof['nativeAppPixelObservation'], 'screenshot': screenshot,
            'blocker': 'Installed v0.2.4 and C2g fragment Obscura builds leave the actual sandboxed SDK frame blank; separate-context SDK success is not mounted-frame proof.'},
        'redCells': [{'surface': row['surface'], **cell} for row in audit['matrix'] for cell in row['cells'] if cell['status'] == 'R'],
        'uncompletedCells': [{'surface': row['surface'], 'axis': cell['axis'], 'status': cell['status'], 'finding': cell['finding']}
            for row in audit['matrix'] for cell in row['cells'] if cell['status'] != 'G'],
        'outsideBoundaries': (EVIDENCE / 'FIXCL5-outside-boundaries.txt').read_text(encoding='utf-8').splitlines(),
        'remainingLocalWork': ['Complete Video and Coming application mechanisms and their mounted executable manual journeys.',
            'Re-run invalidated existing broad source-bound witnesses; never rehash old results as fresh execution.',
            'Repair actual sandboxed SDK module execution and native iframe painting in an owned Obscura build.',
            'Complete the C7/C8 release/native matrix within separately admitted authority.'],
        'verification': {'frontendBuild': '.agent_control/fixcl6/build.log', 'frontendBuildSucceeded': 'built in' in
            (REPO / '.agent_control/fixcl6/build.log').read_text(encoding='utf-8'),
            'sdkExpectedExitCode': 1, 'ports': list(range(48781, 48790)),
            'boundary': 'Owned Obscura, actual HTTP CL/manual execution, real backend SSE frames relayed by retained harness; no native SSE or opaque-frame CDP success.'},
        'tokenUsage': {'observedSessionTotal': usage, 'includesCachedInput': True, 'boundary': 'Current session cumulative counter at sealing, before final response; no provider or subagent calls added.'},
        'receipts': {name: sha(EVIDENCE / name) for name in files},
    }
    (EVIDENCE / 'FIXCL6.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'status': result['status'], 'counts': audit['counts'], 'checks': checks, 'usage': usage}))


if __name__ == '__main__':
    main()
