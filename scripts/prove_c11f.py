"""Bind real C11f lane receipts and independently inspect saved artifacts.

This does not manufacture runs or equate scripted COM/shell replay with learned
manual-compiler flows. Use the named lane runners to reproduce the observations.
"""
from datetime import datetime, timezone
import ast
import hashlib
import json
from pathlib import Path
import sys
import zipfile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'scripts/evidence'
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.cl.manuals import cl_to_manual
from run_c11_cohort import percentile, write_receipt


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name):
    path = EVIDENCE / name
    return json.loads(path.read_text(encoding='utf-8'))


def source_drift(receipt):
    return [name for name, expected in receipt.get('sourceSha256', receipt.get('sources', {})).items()
            if not (ROOT / name).is_file() or digest(ROOT / name) != expected]


def run():
    native, office, shell, preview = [load('C11f-' + name + '.json')
                                     for name in ('native', 'office', 'shell', 'preview')]
    tasks, timings, artifacts = [], [], []
    for row in native['apps']:
        if row.get('passed') == 5:
            tasks.append({'app': row['app'], 'goal': row['task'], 'lane': 'native', 'ok': True})
        timings.extend(a['atomicMs'] for a in row.get('attempts', []) if a.get('actionSent'))
    for row in office['tasks']:
        if not row['replay']:
            tasks.append({'app': row['app'], 'id': row['id'], 'goal': row['goal'], 'lane': 'hidden-com', 'ok': row['ok']})
            timings.extend(a['elapsedMs'] for a in row['actions'])
        path = Path(row['artifact']['path']).resolve()
        if not path.is_relative_to(ROOT / '.agent_control/c11f-office'):
            raise ValueError('Office artifact escaped the disposable task root')
        with zipfile.ZipFile(path) as archive:
            text = '\n'.join(node.text or '' for name in archive.namelist()
                if name.endswith('.xml') and name.startswith(('word/', 'xl/', 'ppt/slides/'))
                for node in ET.fromstring(archive.read(name)).iter() if node.text)
        artifacts.append({'path': path.relative_to(ROOT).as_posix(), 'sha256': digest(path),
                          'ok': digest(path) == row['artifact']['sha256'] and office['token'] in text})
    shell_root = ROOT / '.agent_control/c11f-shell' / shell['token']
    files = {'write-note': 'note.txt', 'copy-note': 'copy.txt', 'rename-note': 'renamed.txt',
             'write-list': 'list.txt', 'search-notes': 'match.txt', 'archive-notes': 'notes.zip'}
    for row in shell['tasks']:
        path = shell_root / files[row['id']]
        if row['id'] == 'archive-notes':
            with zipfile.ZipFile(path) as archive:
                content = archive.read('archive-note.txt').decode('utf-8-sig').strip()
        else:
            content = path.read_text(encoding='utf-8-sig').strip()
        expected = 'C11_' + shell['token'] + '_' + row['id'] + '_4'
        checked = content == expected and (row['id'] != 'rename-note' or not (shell_root / 'draft.txt').exists())
        artifacts.append({'path': path.relative_to(ROOT).as_posix(), 'sha256': digest(path), 'ok': checked})
        tasks.append({'app': row['app'], 'id': row['id'], 'goal': row['goal'], 'lane': 'hidden-shell', 'ok': row['ok'] and checked})
        timings.extend(a['atomicMs'] for a in row['attempts'] if a['actionSent'])
    panel = json.loads((ROOT / 'config/cua-everyday-tasks.json').read_text(encoding='utf-8'))
    forbidden = {'Windows Firewall', 'Local Users and Groups', 'Disk Management', 'Services',
        'Authorization Manager', 'Certificates (Current User)', 'Device Manager', 'Component Services',
        'Shared Folders', 'Computer Management', 'ODBC Data Sources', 'Optimize Drives'}
    panel_ok = not forbidden.intersection(row['app'] for row in panel['apps'])
    manual = json.loads((ROOT / 'manuals/computer-use.manual.json').read_text(encoding='utf-8'))
    manual_ok = cl_to_manual((ROOT / 'manuals/cl/computer-use.cl').read_text(encoding='utf-8')) == manual
    sources = [*sorted((ROOT / 'src/grant_agent').glob('cua_*.py')),
        ROOT / 'src/grant_agent/neyvia_cua.py', ROOT / 'manuals/computer-use.manual.json',
        ROOT / 'manuals/cl/computer-use.cl', ROOT / 'config/cua-desktop-contract.json',
        ROOT / 'config/cua-everyday-tasks.json', ROOT / 'tools/cua-driver-win/parked-hook.cpp',
        ROOT / 'scripts/run_c11_cohort.py', ROOT / 'scripts/build_c11f_panel.py',
        ROOT / 'scripts/prove_c11_preview.py', ROOT / 'scripts/c11_preview_ui.py',
        ROOT / 'web/src/neyvia/next/NxPreviewPane.jsx', *sorted((ROOT / 'scripts').glob('prove_c11f*.py'))]
    for path in sources:
        if path.suffix == '.py': ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    receipts = sorted(EVIDENCE.glob('C11f-*.json'))
    trials = []
    for path in receipts:
        record = json.loads(path.read_text(encoding='utf-8'))
        guard = record.get('guard', {})
        if 'bureau' in path.stem or 'membership' in path.stem:
            trials.append({'receipt': path.name, 'ok': record.get('ok'), 'error': record.get('error'),
                'membershipVerified': record.get('membershipVerified') is True,
                'guardOk': guard.get('ok'), 'violations': guard.get('violations'),
                'newVisibleWindows': guard.get('new_visible_windows'),
                'ownedEscapesHidden': guard.get('owned_escaped_windows_hidden')})
    drifts = {name: source_drift(record) for name, record in
              [('native', native), ('office', office), ('shell', shell), ('preview', preview)]}
    completed = sum(row['ok'] for row in tasks)
    lane_zero = (native['summary']['zeroDisturbance'] and native['guardAfter']['ok']
                 and all(row['guardAfter']['ok'] for row in native['apps'] if row.get('passed'))
                 and all(record['guard']['ok'] for record in (office, shell)))
    all_zero = lane_zero and preview.get('guard', {}).get('ok') and all(row['guardOk'] for row in trials)
    summary = {'distinctEverydayTasksCompleted': completed,
        'appsWithCompletedTasks': len({row['app'] for row in tasks if row['ok']}),
        'activePanelApps': len(panel['apps']), 'atomicAttempts': len(timings),
        'p50Ms': percentile(timings, .5), 'p95Ms': percentile(timings, .95),
        'nativeP50Ms': native['summary']['p50Ms'], 'officeEditReadbackP50Ms': office['actionAndReadbackP50Ms'],
        'shellP50Ms': shell['p50Ms'], 'learnedCompiledZeroTokenAppFlows': native['summary']['appsWithVerifiedCompiledZeroTokenFlow'],
        'successfulNativeFirstObservationMaxMs': max(row['firstObservationMs'] for row in native['apps'] if row.get('passed')),
        'savedArtifactsIndependentlyInspected': len(artifacts), 'successfulTaskLanesZeroDisturbance': lane_zero,
        'entireSessionZeroDisturbance': bool(all_zero)}
    gates = {'everydayPanelOnly': panel_ok, '15EverydayTasks': completed >= 15,
        'atomicP50Under150Ms': summary['p50Ms'] < 150,
        'successfulNativeFirstObservationUnder500Ms': native['gates']['successfulAppsFirstObservationUnder500Ms'],
        'learnedCompiledReplayZeroTokens': summary['learnedCompiledZeroTokenAppFlows'] >= 4,
        'allArtifactsVerified': all(row['ok'] for row in artifacts), 'manualRoundtrip': manual_ok,
        'currentSourcesBound': not any(drifts.values()), 'zeroAttributedDisturbanceAcrossTrials': bool(all_zero),
        'brokerBureauMembership': any(row['ok'] and row['membershipVerified'] for row in trials), 'renderedPreview': preview.get('ok') is True,
        '15LearnedAppManualsAndFlows': native['gates']['atLeast15AppsWithVerifiedCompiledZeroTokenFlow']}
    result = {'schema': 'neyvia.c11f.v1', 'at': datetime.now(timezone.utc).isoformat(),
        'branch': 'track/c1-cua', 'after': '948235ff', 'summary': summary, 'tasks': tasks, 'artifacts': artifacts,
        'timingBoundary': 'Equal five atomic edit/command/verified-readback attempts per distinct task; failures included. Office document creation/save/reopen and GUI startup reported separately. Deterministic Office replays excluded from this task-balanced median.',
        'gates': gates, 'complete': all(gates.values()), 'sourceDrift': drifts,
        'sourceSha256': {path.relative_to(ROOT).as_posix(): digest(path) for path in sources},
        'receiptSha256': {path.relative_to(ROOT).as_posix(): digest(path) for path in receipts},
        'bureauTrials': trials,
        'preview': {'ok': preview.get('ok'), 'error': preview.get('error'), 'rendered': preview.get('renderedPreview'),
                    'frameFailures': preview.get('frameFailures'), 'guardOk': preview.get('guard', {}).get('ok')},
        'missing': ['Successful Bureau membership for broker/singleton apps; shared Explorer HWND containment and token ownership not run/proven',
                    '15 learned app manuals/compiled flows',
                    'Zero disturbance across this session: diagnostic Bureau trials triggered the guard; visibility registration is disabled']
                    + ([] if preview.get('ok') else ['Rendered preview still failed its current real journey']),
        'authority': 'No NAS/credentials, visible user desktop launch, input injection, push, merge or public-service changes authorized. Failed visibility guards are retained as failures, not excused.',
        'historyNote': 'Older receipts keep their original sources and outcomes. The writer now archives receipts without run IDs; early overwritten shell initialization failures were not archived and are not represented as successful trials.',
        'reproduce': ['System Python -B scripts/prove_c11f_office.py',
            'System Python -B scripts/prove_c11f_shell.py',
            'System Python -B scripts/run_c11_cohort.py --apps "Character Map" "Visual Studio Code" "Microsoft Edge" "Google Chrome" --manifest config/cua-everyday-tasks.json --receipt scripts/evidence/C11f-native.json --launch-timeout 12',
            'System Python -B scripts/prove_c11_preview.py --port 48701 --debug-port 48702 --receipt scripts/evidence/C11f-preview.json',
            'System Python -B scripts/prove_c11f.py']}
    write_receipt(EVIDENCE / 'C11f.json', result)
    print(json.dumps({'summary': summary, 'gates': gates, 'complete': result['complete']}))
    return result


if __name__ == '__main__':
    raise SystemExit(0 if run()['complete'] else 2)
