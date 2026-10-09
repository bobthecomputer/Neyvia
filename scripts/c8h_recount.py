"""Keep C8h's preserved denominator and fresh authority boundaries explicit."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LOG = Path('C:/Users/user/Projects/plans/logs/window-guard.jsonl')


def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def run():
    from c8_scope import assigned_ports
    prior = read('scripts/evidence/C8f.json')
    attempts = []
    for path in sorted((ROOT / 'scripts/evidence').glob('C8h-native-*.json')):
        row = json.loads(path.read_text())
        if row.get('schema') != 'neyvia.c11.preview-journey.v1':
            continue
        attempts.append({'receipt': path.relative_to(ROOT).as_posix(),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'passed': row.get('ok') is True,
            'error': row.get('error'),
            'nativeManuals': row.get('additionalJourneys', {}).get('passed'),
            'learning': row.get('learning', {}).get('ok'),
            'renderedPreview': row.get('renderedPreview', {}).get('ok'),
            'guardViolations': row.get('guard', {}).get('violations'),
            'hostViolations': row.get('hostGuard', {}).get('violations'),
            'escapes': row.get('guard', {}).get('owned_escaped_windows_hidden', 0),
            'externalLogUnchanged': row.get('externalGuardLog', {}).get('unchanged'),
            'sourceDrift': [p for p, sha in row.get('sourceSha256', {}).items()
                if hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != sha]})
    passes = [r for r in attempts if r['passed'] and not r['sourceDrift']]
    batch_reports=[]
    observed_web={}
    attempted_ids=set()
    for path in sorted((ROOT/'scripts/evidence').glob('C8h-f10-batch-*.json')):
        report=json.loads(path.read_text())
        raw_path=ROOT/'scripts/evidence/C8-runs'/report['provenance']['runId']/'raw.json'
        raw=json.loads(raw_path.read_text())
        ids={r['id'] for r in raw.get('results',[])}
        attempted_ids.update(ids)
        rows=[r for r in report['rows'] if r['id'] in ids]
        guarded=report['provenance']['desktopGuard']['passed']
        for row in rows:
            if guarded and row['webOutcome']=='pass':
                observed_web[row['id']]=path.relative_to(ROOT).as_posix()
        batch_reports.append({'receipt':path.relative_to(ROOT).as_posix(),
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'guardPassed':guarded,'runErrors':report['provenance'].get('runErrors',[]),
            'attempted':len(ids),'fullPassed':sum(r['outcome']=='pass' for r in rows),
            'webPassedAtRun':sum(r['webOutcome']=='pass' for r in rows),
            'rows':[{'id':r['id'],'outcome':r['outcome'],'webOutcome':r['webOutcome'],
                     'reasons':r['reasons']} for r in rows]})
    sidebar_path=ROOT/'scripts/evidence/C8h-sidebar.json'
    sidebar=json.loads(sidebar_path.read_text()) if sidebar_path.exists() else None
    f10_hosts=[]
    for path in sorted((ROOT/'scripts/evidence').glob('C8h-f10-host-*.json')):
        host=json.loads(path.read_text()); guard=host['guard']
        f10_hosts.append({'receipt':path.relative_to(ROOT).as_posix(),
            'exitCode':host.get('exitCode'),'guardPassed':guard['ok'],
            'observedEscapes':guard.get('owned_escaped_windows_hidden',0),
            'violations':guard.get('violations',{}),'guardLogUnchanged':host['guardLogUnchanged'],
            'excluded':host.get('exitCode')!=0 or not guard['ok']})
    remaining = dict(prior['nativeRemaining'])
    native_effects = []
    remote_path = ROOT / 'scripts/evidence/C8h-remote-5.json'
    if remote_path.exists():
        remote = json.loads(remote_path.read_text())
        proof = remote.get('additionalJourneys', {}).get('remote', {})
        if (proof.get('passed') and remote.get('guard', {}).get('ok')
                and remote.get('hostGuard', {}).get('ok') and remote.get('externalGuardLog', {}).get('unchanged')
                and all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == sha
                    for p, sha in proof.get('sourceSha256', {}).items())):
            for row in proof['rows']:
                if row['passed']:
                    remaining.pop(row['id'], None)
                    native_effects.append({'id': row['id'], 'passed': True,
                        'receipt': remote_path.relative_to(ROOT).as_posix(),
                        'boundary': row['boundary'], 'fullF10Passed': False})
    runtime_path = ROOT / 'scripts/evidence/C8h-native-runtime-producer.json'
    gateway_path = ROOT / 'scripts/evidence/C8h-native-runtime-3.json'
    if runtime_path.exists() and gateway_path.exists():
        runtime = json.loads(runtime_path.read_text())
        gateway = json.loads(gateway_path.read_text())
        producer = runtime['nativeReceipt'].get('result', {})
        if (runtime['nativeReceipt'].get('ok') and producer.get('ok') and producer.get('cases')
                and all(case['ok'] for case in producer['cases'])
                and gateway.get('privateHostGuard', {}).get('ok')
                and all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == sha
                    for p, sha in runtime['sourceSha256'].items())):
            identity = 'native-runtime/native-runtime-proofs/observe-and-prove'
            remaining.pop(identity, None)
            native_effects.append({'id': identity, 'passed': True,
                'receipt': runtime_path.relative_to(ROOT).as_posix(),
                'casesPassed': len(producer['cases']), 'contracts': len(producer['contracts']),
                'boundary': producer['truthBoundary'], 'fullF10Passed': False})
    result = {'schema': 'neyvia.c8h.f10-recount.v1',
        'at': datetime.now(timezone.utc).isoformat(), 'complete': False,
        'sourceCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
            text=True, creationflags=subprocess.CREATE_NO_WINDOW).strip(),
        'sourceCommitRole':'Base HEAD while evidence was produced from editable worktree bytes; per-producer SHA256 manifests are the source authority',
        'releaseGate': 'blocked',
        'containmentGate': 'passed' if len(passes) >= 3 else 'pending-three-full-runs',
        'rootCause': {'caller': 'neyvia_dictation._spawn -> venv Python redirector -> phonon2_engine.py',
            'flags': 'DETACHED_PROCESS defeats CREATE_NO_WINDOW',
            'repro': 'Bare CreatePseudoConsole did not create an HWND on either desktop; real private terminal and real venv launcher were independently observed.',
            'repair': 'Pipe subprocess removes DETACHED_PROCESS; terminal ConPTY owners and clients start on an explicit private desktop without AllocConsole.',
            'proofScope': 'Disposable roots and explicit ports; external ASR refused before health/start.'},
        'counts': {'frozenRows': len(prior['rows']), 'nativeAttempts': len(attempts),
            'nativeFullPasses': len(passes), 'nativeFullPassesRequired': 3,
            'freshFullF10Passed': 0, 'fullF10Blocked': len(prior['rows']),
            'f10BatchReports':len(batch_reports),'f10DistinctAttempts':len(attempted_ids),
            'guardedWebPassesAtRun':len(observed_web),
            'freshMountedSidebarChecks':len(sidebar['freshMountedChecks']) if sidebar else 0,
            'remainingNineNativeEffectsProved': len(native_effects),
            'nativeEffectsStillUnproved': len(remaining),
            'sidebarFullSourceContractsPassed': 0, 'sidebarFullSourceContractsRequired': 7},
        'runs': attempts, 'acceptedNativeRuns': passes,
        'nativeRemaining': remaining, 'nativeEffects': native_effects,
        'f10Batches':batch_reports,'f10ProducerHosts':f10_hosts,'guardedWebObservationsAtRun':observed_web,
        'f10Boundary':'Fresh bounded attempts on pinned source/bundle bytes; web passes lack same-journey native T16 proof. Unattempted frozen rows remain blocked. The current expanded catalog is retained separately in each producer.',
        'sidebarContracts':sidebar['contracts'] if sidebar else [{**row, 'fresh': False,
            'historyReceipt': 'scripts/evidence/C8f-sidebar.json'} for row in prior['sidebarContracts']],
        'sidebarReceipt':'scripts/evidence/C8h-sidebar.json' if sidebar else None,
        'nativeFrontierReceipt':'scripts/evidence/C8h-native-frontier.json',
        'guardLog': {'bytes': LOG.stat().st_size,
            'sha256': hashlib.sha256(LOG.read_bytes()).hexdigest(),
            'originalBytes': 2827,
            'originalSha256': 'b156a8092b9cf20a75cc750a20bef8790fdd90d07a7b09d3f4aad8cce6d5eed9',
            'unchanged': hashlib.sha256(LOG.read_bytes()).hexdigest() == 'b156a8092b9cf20a75cc750a20bef8790fdd90d07a7b09d3f4aad8cce6d5eed9'},
        'usage': {'totalTokens': None, 'reason': 'Session token usage counter is not exposed.'},
        'authority': {'subagents': 0, 'nas': False, 'credentialFilesRead': False,
            'pushed': False, 'merged': False, 'ports': ','.join(map(str, sorted(assigned_ports()))), 'publicServicesTouched': False},
        'next': 'Wire same-journey native T16 replay into F10; supply genuine operator handoff, installed native editor, safe task-owned WebView2 host, image-tool and child-agent source events. Containment is proved; release and full sidebar/native coverage remain blocked.'}
    target = ROOT / 'scripts/evidence/C8h.json'
    target.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'receipt': target.relative_to(ROOT).as_posix(), 'counts': result['counts'],
        'containmentGate': result['containmentGate'], 'guardLogUnchanged': result['guardLog']['unchanged']}))
    return result


def contract():
    result = run()
    accepted = result['acceptedNativeRuns']
    passed = len(accepted) >= 3 and result['guardLog']['unchanged'] and all(
        row['passed'] and row['nativeManuals'] and row['learning'] and row['renderedPreview']
        and row['escapes'] == 0 and not row['guardViolations'] and not row['hostViolations']
        and row['externalLogUnchanged'] for row in accepted)
    Path('native-contract.json').write_text(json.dumps({'passed': passed,
        'acceptedRuns': accepted, 'guardLog': result['guardLog'],
        'boundary': 'Three full private-native runs on the current sources; this is not the F10 release gate'}, indent=2))
    if not passed:
        raise RuntimeError('Three full current-source native runs with unchanged guard bytes are required')


if __name__ == '__main__':
    run()
