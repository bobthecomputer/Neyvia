"""Recount C8f evidence without promoting partial effects into F10 passes."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.neyvia_inception import inventory
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
from c8_scope import assigned_ports


def read(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def digest(name):
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()


def run():
    baseline = read('scripts/evidence/C8e.json')
    native = read('scripts/evidence/C8f-native-manuals.json')
    sync = read('scripts/evidence/C8f-sync.json')
    sidebar = read('scripts/evidence/C8f-sidebar.json')
    provider = read('scripts/evidence/C8f-provider.json')
    catalog = inventory()
    frozen = {r['id']: r for r in baseline['rows']}
    assert len(frozen) == len(baseline['rows']) == 206
    waiting = {r['id'] for r in baseline['rows'] if r.get('waitingFor') == 'C11' and r.get('webOutcome') == 'waiting'}
    assert len(waiting) == 16
    actual = {r['id']: r for r in native['additionalJourneys']['rows'] if r['passed']}
    assert native['nativeManualsPassed'] and native['guard']['ok'] and not native['guard']['violations']
    assert sync['passed'] and all(r['guard']['ok'] and r['ownedProcessStopped'] for r in sync['nativeReceipts'])
    actual[sync['id']] = {'passed': True, 'receipt': 'scripts/evidence/C8f-sync.json'}
    assert len(actual) == 7 and set(actual) <= waiting
    effects = sidebar['selected']['result']['effectEvidence']
    seven = effects['contractEffects']
    assert len(seven) == 7
    failures = []
    seen = set()
    paths = list((ROOT / 'scripts/evidence/C11-preview-runs').glob('*.json'))
    paths += [ROOT / 'scripts/evidence/C8f-native.json', ROOT / 'scripts/evidence/C8f-notepad.json']
    for path in paths:
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if sha in seen:
            continue
        seen.add(sha)
        data = json.loads(raw)
        if path.name != 'C8f-notepad.json' and data.get('port') not in assigned_ports():
            continue
        guard = data.get('guard', {})
        if guard.get('violations') or data.get('error'):
            failures.append({'receipt': path.relative_to(ROOT).as_posix(), 'sha256': sha,
                'error': data.get('error'), 'guardPassed': guard.get('ok'),
                'violations': guard.get('violations'), 'containmentLog': guard.get('containment_log', [])})
    reasons = {
        'computer-use/proofs-e-models/read-model-proof-receipt': 'No full fresh producer for all model source cases; reading a report alone is insufficient.',
        'computer-use/test-loop/launch-check-handoff': 'New-window identity and genuine handover remain unproved; no Paul interaction was fabricated.',
        'game-dev/bridges/review-completed-action': 'No actual editor-bridge action receipt and real editor effect were produced.',
        'remote/overview/observe-allowed-window': 'Owner-indicator launch has no proven private-desktop route; input-desktop launch is prohibited.',
        'remote/user-side/observe-allowed-window': 'Owner-connected native remote route has no proven private-desktop containment.',
        'browser/backend/open-native-tab': 'Actual WebView2 host effect remains unproved; Chromium is not substituted.',
        'browser/backend/promote-task': 'Actual native host promotion remains unproved.',
        'proofs-b-desktop/@manual': 'Manual has no executable procedure; actual full desktop producer remains unproved.',
        'native-runtime/native-runtime-proofs/observe-and-prove': 'Full actual producer, including private-desktop browser-worker effects, was not executed.'
    }
    assert set(reasons) == waiting - set(actual)
    paths = ['scripts/evidence/C8e.json', 'scripts/evidence/C8f-native-manuals.json',
        'scripts/evidence/C8f-native.json', 'scripts/evidence/C8f-notepad.json',
        'scripts/evidence/C8f-sync.json', 'scripts/evidence/C8f-provider.json',
        'scripts/evidence/C8f-sidebar.json', 'scripts/evidence/C8f-syncthing-package.json',
        'scripts/evidence/C8f-sync-closed-guard.json']
    rows = [{'id': identity, 'historicalWebOutcome': row.get('webOutcome'),
        'historicalWebStatus': row.get('webStatus'), 'fullF10Status': 'blocked',
        'freshNativeEffect': identity in actual,
        'freshEvidence': ('scripts/evidence/C8f-sync.json' if identity == sync['id'] else
            'scripts/evidence/C8f-native-manuals.json') if identity in actual else None,
        'remainingReason': reasons.get(identity, 'Complete matched cases and fresh T16/release journey not proved.')}
        for identity, row in frozen.items()]
    usage = provider['usage'][0]
    receipt = {
        'schema': 'neyvia.c8f.f10-recount.v1', 'at': datetime.now(timezone.utc).isoformat(),
        'complete': False, 'releaseGate': 'blocked', 'webCoverageGate': 'blocked',
        'sourceCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
            **hidden_windows_subprocess_kwargs()).strip(),
        'milestoneCommits': ['4564e5f1f', 'a578aa0c2', '2dd161979', '89fdcd774'],
        'rules': {'f10': 'plans/logs/audit4-cl.md section F10',
            'matchedCases': 'Every applicable source case must have a real defining effect.',
            'historical': '164 web passes are C8e history, not fresh C8f or full release passes.',
            'partial': 'Native steps, genuine provider replies, screenshots and subchecks do not remove other journey gates.'},
        'counts': {'frozenC8eRows': 206, 'historicalWebPassed': 164, 'historicalWebBlocked': 26,
            'originalNativeWaiting': 16, 'freshNativeEffectsProved': len(actual),
            'nativeEffectsStillUnproved': len(reasons), 'freshFullF10Passed': 0,
            'fullF10Blocked': len(rows), 'sidebarRenderedSubchecksPassed': sum(
                c['passed'] for c in effects['checks'] if c['id'].startswith('c8f.sidebar.')),
            'sidebarFullSourceContractsPassed': sum(c['passed'] for c in seven)},
        'currentCatalog': {'manuals': len(catalog['manualHashes']),
            'procedures': sum(r.get('kind') == 'procedure' for r in catalog['rows']),
            'coverageRows': len(catalog['rows']),
            'newRowsOutsideFrozenCohort': sorted({r['id'] for r in catalog['rows']} - set(frozen)),
            'boundary': 'New rows are separate and unproved; the frozen denominator is never reduced.'},
        'rows': rows, 'nativeRemaining': reasons, 'sidebarContracts': seven,
        'nativeGuard': {'passed': native['guard']['ok'], 'violations': native['guard']['violations'],
            'renderedPreviewSkipped': native['renderedPreview'].get('skipped'),
            'manifestDrift': [p for p, sha in native['sourceSha256'].items() if digest(p) != sha],
            'driftExplanation': 'Unexecuted preview-UI retry experiment was reverted; executed native/manual sources remain unchanged.'},
        'priorFailedAttempts': failures,
        'priorSyncObserverFailure': {'receipt': 'scripts/evidence/C8f-sync-closed-guard.json',
            'reason': 'Real native effects and cleanup succeeded; checking the closed observer incorrectly failed the attempt. The later fresh run uses its final close receipt.'},
        'containmentBlocker': 'Intermittent owned visible input-desktop windows were detected and hidden, failing closed. Root cause unresolved; no blanket zero-disturbance claim.',
        'provider': {'model': provider['model'], 'effort': provider['effort'], 'genuineReturn': provider['passed'],
            'persistedInRenderedSidebarJourney': True, 'integratedProviderJobsProved': False,
            'firstCallUsage': {'inputTokens': 27882, 'outputTokens': 10, 'cachedInputTokens': 0},
            'secondCallUsage': usage, 'measuredProviderTokens': 27892 + usage['input_tokens'] + usage['output_tokens'],
            'totalSessionTokens': None, 'totalSessionTokensReason': 'Main assistant usage is not exposed; 53594 is the measured provider-only total.'},
        'verification': {'targetedNodeTests': 'tests/fixwave-sidebar-cleanup.test.mjs: 3 passed',
            'frontendBuild': 'Isolated C8f Vite build passed; no release promotion.',
            'native': 'Actual field readback, OS/window projections, native application write/scroll and compiled replay.',
            'sync': 'Pinned actual daemon on private desktop; local config/ignore/refusal/rollback/recovery effects and owned cleanup.',
            'sidebar': 'Actual persisted conversations, bus move/title/pin/archive, rendered confirmation and Undo, independent canonical readback.',
            'sidebarGuardPassed': sidebar['desktopGuardPassed']},
        'receiptHashes': {p: digest(p) for p in paths},
        'downloads': [read('scripts/evidence/C8f-syncthing-package.json')],
        'authority': {'subagents': 0, 'nas': False, 'credentialFilesRead': False,
            'publicServicesRestarted': False, 'pushed': False, 'ports': ','.join(map(str, sorted(assigned_ports())))},
        'paulActions': ['Android remains on Paul\u0027s list.'],
        'nextEngineeringWork': ['Repair native containment before further native-browser/Bureau journeys.',
            'Produce the nine remaining native effects and all seven sidebar source-case sets.',
            'Wire and prove genuine integrated provider jobs, then rerun matched F10/T16 journeys.']
    }
    (ROOT / 'scripts/evidence/C8f.json').write_bytes((json.dumps(receipt, indent=2) + '\n').encode())
    print(json.dumps({'counts': receipt['counts'], 'newCatalogRows': receipt['currentCatalog']['newRowsOutsideFrozenCohort'],
        'manifestDrift': receipt['nativeGuard']['manifestDrift'], 'measuredProviderTokens': receipt['provider']['measuredProviderTokens'],
        'priorFailedAttempts': len(failures)}))


if __name__ == '__main__':
    run()
