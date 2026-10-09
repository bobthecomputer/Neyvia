"""Seal actual C11g receipts, keeping failed trials and source drift visible."""
from datetime import datetime, timezone
import ast
import hashlib
import json
import re
from pathlib import Path
import sys
import zipfile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'scripts/evidence'
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.cl.manuals import cl_to_manual
from run_c11_cohort import percentile, write_receipt


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def drift(record):
    return [name for name, value in record.get('sourceSha256', record.get('sources', {})).items()
            if not (ROOT / name).is_file() or sha(ROOT / name) != value]


def guards(value):
    if isinstance(value, dict):
        if 'visibility_diagnostics_enabled' in value:
            yield value
        for child in value.values():
            yield from guards(child)
    elif isinstance(value, list):
        for child in value:
            yield from guards(child)


def zero(record):
    observed = list(guards(record))
    return bool(observed) and all(g.get('ok') is True and g['visibility_diagnostics_enabled'] is True
        and all(g.get(k, 0) == 0 for k in ('foreground_changes', 'new_visible_windows',
            'owned_escaped_windows_hidden', 'injected_mouse_events', 'injected_keyboard_events')) for g in observed)


def artifact_check(row):
    checked = row.get('independentFinalCheck', {})
    artifact = checked.get('artifact', {})
    if not artifact:
        return {'app': row['app'], 'ok': False, 'error': 'No persisted artifact advertised'}
    path = Path(artifact['path']).resolve()
    if not path.is_relative_to(ROOT / '.agent_control'):
        raise ValueError('Artifact is outside disposable task state')
    result = {'app': row['app'], 'path': path.relative_to(ROOT).as_posix(), 'ok': False}
    if not path.is_file():
        result['error'] = 'Persisted artifact missing'
        return result
    result.update(sha256=sha(path), bytes=path.stat().st_size)
    expected = checked.get('observed', '')
    rendered_ok = False
    if path.suffix in {'.docx', '.xlsx', '.pptx'}:
        with zipfile.ZipFile(path) as archive:
            text = '\n'.join(''.join(node.itertext()) for name in archive.namelist()
                if name.endswith('.xml') and name.startswith(('word/', 'xl/', 'ppt/slides/'))
                for node in [ET.fromstring(archive.read(name))])
    elif path.suffix == '.pdf':
        from grant_agent import pdf_compat
        text = '\n'.join(pdf_compat.page_texts(path))
    elif path.suffix in {'.txt', '.json', '.html', '.svg'}:
        text = path.read_text(encoding='utf-8-sig')
    elif path.suffix == '.png':
        from PIL import Image
        with Image.open(path) as screenshot:
            pixels = screenshot.convert('RGB')
            color = list(pixels.getpixel((0, 0)))
            ink = sum(1 for rgb in pixels.crop((0, 30, min(1100, pixels.width), min(220, pixels.height))).getdata()
                      if min(rgb) > 220)
            result.update(size=list(screenshot.size), cornerRgb=color, headingInkPixels=ink,
                          boundary='PNG pixels verify the browser-rendered background and heading presence; no OCR claim')
            rendered_ok = color == artifact['expectedRgb'] and ink > 1000 and list(screenshot.size) == artifact['size']
        text = ''
    else:
        text = ''
    result['ok'] = bool(checked.get('ok') and result['sha256'] == artifact['sha256']
        and result['bytes'] == artifact['bytes'] and expected and (expected in text or rendered_ok))
    if result['ok']:
        copies = EVIDENCE / 'C11g-artifacts'
        copies.mkdir(exist_ok=True)
        copy = copies / (re.sub(r'[^a-z0-9]+', '-', row['app'].lower()).strip('-') + path.suffix)
        copy.write_bytes(path.read_bytes())
        if sha(copy) != result['sha256']:
            raise RuntimeError('Review artifact differs from saved application output')
        result['reviewCopy'] = copy.relative_to(ROOT).as_posix()
    return result


def run():
    selected = ['C11g-apps-native.json', 'C11g-apps-ui.json',
                'C11g-preview.json', 'C11g-preview-repeat.json', 'C11g-bureau-final.json',
                'C11g-bureau-repeat.json', 'C11g-apps-bureau-task.json',
                'C11g-apps-native-refusal.json', 'C11g-apps-native-registry.json', 'C11g-apps-native-http.json',
                'C11g-apps-native-surfaces.json',
                'C11g-bureau-cleanup.json']
    records = {name: json.loads((EVIDENCE / name).read_text(encoding='utf-8'))
               for name in selected if (EVIDENCE / name).is_file()}
    bindings = {name: drift(record) for name, record in records.items()}
    apps, artifacts, timings, first_observations = {}, [], [], []
    for name, record in records.items():
        if not name.startswith('C11g-apps-') or name.endswith(('refusal.json', 'registry.json', 'http.json', 'surfaces.json')):
            continue
        for row in record.get('apps', []):
            learned = row.get('learnedFlow', {})
            native = 'independentFinalCheck' in row
            successful = (row.get('ok') and row.get('compiledPlan', {}).get('zeroToken')
                and row.get('replay', {}).get('ok') and row.get('tokens') == 0) if native else (
                row.get('passed') == 5 and learned.get('status') == 'passed'
                and learned.get('compiledReplay') and learned.get('tokens') == 0)
            if native and successful:
                artifact = artifact_check(row)
                artifacts.append(artifact)
                successful = artifact['ok']
            if successful and not bindings[name] and zero(record):
                apps[row['app']] = {'app': row['app'], 'receipt': name,
                    'boundary': record.get('boundary', record.get('environment')),
                    'completedTaskAndLearnedZeroTokenReplay': True}
            if not bindings[name] and zero(record):
                timings.extend(a['atomicMs'] for a in row.get('attempts', []) if a.get('actionSent'))
            if successful and not bindings[name] and zero(record) and 'firstObservationMs' in row:
                first_observations.append(row['firstObservationMs'])
    preview_names = ['C11g-preview.json', 'C11g-preview-repeat.json']
    bureau_names = ['C11g-bureau-final.json', 'C11g-bureau-repeat.json']
    preview_ok = all(name in records and records[name].get('ok') and zero(records[name])
                     and not bindings[name] for name in preview_names)
    bureau_ok = all(name in records and records[name].get('ok') and records[name].get('membershipVerified')
        and records[name].get('assignment', {}).get('pixelsReleasedAfterMembership')
        and records[name].get('assignment', {}).get('shellCloakVerified') and zero(records[name])
        and not bindings[name] for name in bureau_names)
    trials = []
    paths = set(EVIDENCE.glob('C11g-*.json')) | set((EVIDENCE / 'C11g-runs').glob('*.json'))
    for path in sorted(paths):
        record = json.loads(path.read_text(encoding='utf-8'))
        samples = list(guards(record))
        trials.append({'receipt': path.relative_to(ROOT).as_posix(), 'sha256': sha(path),
            'reportedOk': record.get('ok', record.get('complete')), 'guardSamples': len(samples),
            'guardFailures': sum(g.get('ok') is not True for g in samples),
            'diagnosticsDisabled': sum(g['visibility_diagnostics_enabled'] is not True for g in samples),
            'error': record.get('error')})
    manuals_ok = all(cl_to_manual((ROOT / 'manuals/cl' / (name + '.cl')).read_text(encoding='utf-8')) ==
        json.loads((ROOT / 'manuals' / (name + '.manual.json')).read_text(encoding='utf-8'))
        for name in ('computer-use', 'native-applications'))
    sources = [*sorted((ROOT / 'src/grant_agent').glob('cua_*.py')), ROOT / 'src/grant_agent/neyvia_cua.py',
        ROOT / 'src/grant_agent/native_tools.py', ROOT / 'src/grant_agent/neyvia_mcp.py',
        ROOT / 'src/grant_agent/native_tool_worker.py', ROOT / 'src-tauri/src/lib.rs', ROOT / 'tools/cua-driver-win/parked-hook.cpp',
        ROOT / 'tools/cua-driver-win/c1-probe.cs', ROOT / 'web/src/neyvia/next/NxPreviewPane.jsx',
        *sorted((ROOT / 'scripts').glob('prove_c11g*.py')), ROOT / 'scripts/c11_preview_ui.py',
        ROOT / 'scripts/prove_c11_preview.py', ROOT / 'scripts/run_c11_cohort.py',
        ROOT / 'config/cua-everyday-tasks.json', ROOT / 'config/cua-desktop-contract.json',
        ROOT / 'scripts/C1-comparison-run.json']
    for path in sources:
        if path.suffix == '.py':
            ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    bureau_task = records.get('C11g-apps-bureau-task.json', {})
    bureau_flow = any(row.get('learnedFlow', {}).get('compiledReplay') and row.get('passed') == 5
        for row in bureau_task.get('apps', [])) and not bindings.get('C11g-apps-bureau-task.json', ['missing'])
    gates = {'bureauMembershipBeforePixelsTwoRuns': bool(bureau_ok), 'bureauTaskAndLearnedReplay': bool(bureau_flow),
        'renderedInputAndRefusalTwoRuns': bool(preview_ok),
        '15DifferentLearnedApplications': len(apps) >= 15, 'acceptedRunsZeroDisturbance': bool(records) and all(zero(r) for r in records.values()),
        'publicHttpNativeSessionAndCOMAffinity': records.get('C11g-apps-native-http.json', {}).get('ok') is True,
        'nativeMcpAndPersistentDesktopWorker': records.get('C11g-apps-native-surfaces.json', {}).get('ok') is True,
        'currentSourceBindings': bool(bindings) and not any(bindings.values()), 'manualRoundtrips': manuals_ok,
        'artifactsReinspected': bool(artifacts) and all(a['ok'] for a in artifacts),
        'atomicP50Under150Ms': bool(timings) and percentile(timings, .5) < 150,
        'successfulFirstObservationsUnder500Ms': bool(first_observations) and max(first_observations) < 500}
    result = {'schema': 'neyvia.c11g.v1', 'at': datetime.now(timezone.utc).isoformat(), 'branch': 'track/c1-cua',
        'after': '20d91ae2', 'complete': all(gates.values()), 'gates': gates, 'apps': list(apps.values()),
        'summary': {'differentAppsWithCompletedLearnedZeroTokenTask': len(apps),
            'nativeAtomicP50MsIncludingSentFailures': percentile(timings, .5),
            'nativeFirstObservationMaxMs': max(first_observations) if first_observations else None,
            'historicalGuardFailureRecords': sum(t['guardFailures'] > 0 for t in trials),
            'historicalDiagnosticsDisabledRecords': sum(t['diagnosticsDisabled'] > 0 for t in trials)},
        'sourceDrift': bindings, 'artifacts': artifacts, 'trials': trials,
        'sourceSha256': {p.relative_to(ROOT).as_posix(): sha(p) for p in sources},
        'receiptSha256': {name: sha(EVIDENCE / name) for name in records},
        'comparison': {'file': 'scripts/C1-comparison-run.json', 'status': 'prepared; provider arms not executed'},
        'boundary': 'Local disposable targets; native COM/headless procedures and private UIA/CDP are reported separately. Native-app procedure replay is not universal pixel interaction.',
        'history': 'Failed trials retained, including guard-classified registration failures. Passing final runs do not erase historical guard failures.',
        'entireSessionAllGuardsPassed': not any(t['guardFailures'] for t in trials),
        'missing': [name for name, passed in gates.items() if not passed]}
    write_receipt(EVIDENCE / 'C11g.json', result)
    print(json.dumps({'summary': result['summary'], 'gates': gates, 'complete': result['complete']}))
    return result


if __name__ == '__main__':
    raise SystemExit(0 if run()['complete'] else 2)
