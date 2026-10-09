"""Seal current real-run FIXCL3 evidence without promoting partial mechanisms."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

from fixcl3_aud4_matrix import REPO, positive_uses

EVIDENCE = REPO / 'scripts/evidence'
REQUIRED = ('authority', 'documents', 'core', 'records', 'mechanisms', 'environment',
            'jobs', 'configuration', 'provider', 'device-pdf', 'manual', 'provision',
            'projection', 'capture', 'app-open', 'cold', 'renderer', 'obscura-runtime',
            'manual-gate', 'manual-grounding', 'regression-compatibility')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_path(relative):
    path = (REPO / relative).resolve()
    if not path.is_relative_to(REPO) or not path.is_file():
        raise ValueError('Missing or out-of-worktree evidence source: ' + relative)
    return path


def bindings(proof):
    start = proof.get('sourceHashesAtStart', proof.get('sourceHashes', {}))
    end = proof.get('sourceHashesAtEnd', start)
    if not start or start != end:
        raise ValueError('Missing or changed source boundary')
    for relative, digest in start.items():
        if sha(checked_path(relative)) != digest:
            raise ValueError('Source drift: ' + relative)
    return start


def visit(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from visit(child)
    elif isinstance(value, list):
        for child in value:
            yield from visit(child)


def effect_bindings(proof):
    for value in visit(proof):
        for name, digest in value.get('effectSourceBindings', {}).items():
            if sha(checked_path('src/grant_agent/cl/' + name)) != digest:
                raise ValueError('Manual effect owner drift: ' + name)


def positive_calls(proof):
    """Read only successful host outputs, never admission-only bus payloads."""
    found = set()
    for value in visit(proof):
        if value.get('ok') is not True:
            continue
        for key in ('cl', 'text'):
            output = value.get(key)
            if isinstance(output, str):
                found.update(match.group(1).removeprefix('neyvia.') for match in
                    re.finditer(r'^R ([\w.]+) ok \S+[^\n]*\+effect-[^\n]+$', output, re.M))
    # Renderer effects legitimately begin unknown and complete only after a
    # later CL done() rereads the actual mounted content. Bind both calls to
    # the same requested pane, hash, action identity and manual use.
    for journey in proof.get('journeys', {}).values():
        initial = journey.get('manualOpen', {}).get('answer', {})
        completed = journey.get('doneAfterAck', {}).get('answer', {})
        if completed.get('ok') is not True or completed.get('text') != 'R done ok +G\n':
            continue
        marks = [mark for result in completed.get('results', []) for mark in result.get('goalChecks', [])]
        observations = [observation.get('value', {}) for mark in marks
                        for observation in mark.get('observations', [])
                        if observation.get('observer') == 'pane.observe']
        for action in initial.get('results', []):
            name = action.get('name')
            if name not in {'app.open', 'artifact.open'} or action.get('status') != 'unknown':
                continue
            manual = action.get('manualUse') or {}
            if not manual.get('actionIdentity') or not any(
                    use.get('actionIdentity') == manual['actionIdentity'] and use.get('tool') == 'neyvia.' + name
                    for use in journey.get('manualReceipts', [])):
                continue
            native = action.get('result', {})
            requested = native.get('result', {})
            expected_hash = requested.get('expectedContentHash')
            preview = requested.get('preview', {})
            if name == 'artifact.open' and preview.get('kind') == 'text' and isinstance(preview.get('text'), str) and preview.get('path') == requested.get('target'):
                expected_hash = hashlib.sha256(preview['text'].encode('utf-8')).hexdigest()
            if native.get('ok') is not True or native.get('tool') != 'neyvia.' + name or not requested.get('paneId') or not expected_hash:
                continue
            if not any(mark.get('name') == name and mark.get('passed') is True and mark.get('observed') is True for mark in marks):
                continue
            if any(observed.get('paneId') == requested['paneId'] and observed.get('contentHash') == expected_hash
                   and observed.get('target') == requested.get('target')
                   and observed.get('runtimeId') and all(observed.get(key) is True for key in
                   ('visible', 'mounted', 'acknowledged', 'fresh', 'current', 'contentMatches')) for observed in observations):
                found.add(name)
    return found


def committed_bytes(paths):
    checkout_forms = {}
    child = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=REPO,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, creationflags=0x08000000)
    try:
        for relative in sorted(paths):
            path = checked_path(relative)
            child.stdin.write(('HEAD:' + relative.replace('\\', '/') + '\n').encode())
            child.stdin.flush()
            header = child.stdout.readline().split()
            if header[-1] == b'missing':
                raise ValueError('Uncommitted source: ' + relative)
            raw = child.stdout.read(int(header[2]))
            child.stdout.read(1)
            working = path.read_bytes()
            if raw != working:
                # Unedited Windows checkout files can have core.autocrlf's
                # presentation bytes. Never permit this for changed/new
                # implementation: its exact Git bytes must match the proof.
                child.stdin.write(('152a5368:' + relative.replace('\\', '/') + '\n').encode())
                child.stdin.flush()
                baseline_header = child.stdout.readline().split()
                if baseline_header[-1] == b'missing':
                    raise ValueError('New source committed bytes differ: ' + relative)
                baseline = child.stdout.read(int(baseline_header[2]))
                child.stdout.read(1)
                crlf = raw.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
                if baseline != raw or crlf != working:
                    raise ValueError('Changed source committed bytes differ: ' + relative)
                checkout_forms[relative] = {'gitSha256': hashlib.sha256(raw).hexdigest(),
                    'checkoutSha256': hashlib.sha256(working).hexdigest(),
                    'boundary': 'Unchanged Git blob since 152a5368; exact Windows LF-to-CRLF checkout representation.'}
    finally:
        child.stdin.close()
        child.wait(timeout=15)
    return checkout_forms


def regression_boundary(accepted):
    """Conserve the unchanged assertions and independently bind their replay."""
    raw = accepted.get('FIXCL3-regression.json')
    compatibility = accepted.get('FIXCL3-regression-compatibility.json')
    names = {'terminal', 'work', 'creative', 'coordination', 'semantic', 'durable',
             'frontier-local', 'sidebar', 'browser'}
    if not raw or set(raw.get('probes', {})) != names or not compatibility:
        raise ValueError('Missing complete original regression replay')
    failures, total = [], 0
    for name, row in raw['probes'].items():
        path = checked_path(row['receipt'])
        proof = accepted.get(path.relative_to(EVIDENCE).as_posix())
        if not proof or sha(path) != row['receiptSha256'] or row['checks'] != proof['checks']:
            raise ValueError('Regression receipt changed: ' + name)
        if sha(checked_path(row['originalProbe'])) != row['originalSha256']:
            raise ValueError('Original assertion source changed: ' + name)
        phases = [phase for phase in raw['phases'] if phase['scratch'] == row['phaseScratch']]
        if len(phases) != 1:
            raise ValueError('Regression has no exact retained execution phase: ' + name)
        phase = phases[0]
        bindings(phase)
        if phase['baselineHashesAtStart'] != phase['baselineHashesAtEnd'] or any(
                sha(EVIDENCE / filename) != digest for filename, digest in phase['baselineHashesAtEnd'].items()):
            raise ValueError('Historical FIXCL2 receipts changed during replay')
        checks = proof['checks']
        total += len(checks)
        failures += [(name, key) for key, value in checks.items() if value is not True]
        if row['exitCode'] != (1 if name == 'browser' else 0):
            raise ValueError('Unexpected original regression exit: ' + name)
    if failures != [('browser', 'unobserved_capture_not_admitted')]:
        raise ValueError('Unexpected raw regression failures: ' + str(failures))
    if total != 131 or compatibility['rawCounts'] != raw['counts']:
        raise ValueError('Raw regression count changed')
    resolution = compatibility['resolution']
    if resolution['probe'] != 'browser' or resolution['assertion'] != failures[0][1] or compatibility['authorizedExpectedChanges'] != 1:
        raise ValueError('Compatibility resolution hides an unrelated failure')
    for field in ('originalProbe', 'rawBrowserReceipt', 'rawRegressionReceipt', 'currentCaptureReceipt'):
        reference = compatibility[field]
        if sha(checked_path(reference['path'])) != reference['sha256']:
            raise ValueError('Compatibility reference changed: ' + field)
    for png in compatibility['retainedPngs']:
        path = checked_path(png['path'])
        if sha(path) != png['expectedSha256'] or not path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Retained actual screenshot changed')
    return {'rawCounts': raw['counts'], 'rawFailedAssertions': failures,
            'authorizedExpectedChanges': 1, 'resolution': resolution,
            'rawReceiptSha256': sha(EVIDENCE / 'FIXCL3-regression.json'),
            'compatibilityReceiptSha256': sha(EVIDENCE / 'FIXCL3-regression-compatibility.json'),
            'boundary': 'The original capture-negative assertion remains false; current real capture effects and adverse gates independently prove the authorized replacement.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if args.port not in range(48821, 48830):
        parser.error('Explicit assigned port required')
    matrices = {label: json.loads((EVIDENCE / ('FIXCL3-AUD4-' + label + '.json')).read_bytes())
                for label in ('before', 'after')}
    for label, matrix in matrices.items():
        if matrix['label'] != label or not all(matrix['checks'].values()) or sum(matrix['counts'].values()) != 185:
            raise ValueError('Incomplete exact AUD4 matrix: ' + label)
    after = json.loads((EVIDENCE / 'FIXCL3-AUD4-after-snapshots.json').read_bytes())
    before = json.loads((EVIDENCE / 'FIXCL3-AUD4-before-snapshots.json').read_bytes())
    source_map = bindings(after)
    if not all(row['typedCodec'] for row in after['families']):
        raise ValueError('Missing typed codec family in the complete native registry')
    accepted, summaries, rejected = {}, {}, {}
    paths = sorted(EVIDENCE.glob('FIXCL3-*.json')) + [path for path in sorted((EVIDENCE / 'FIXCL3-regression').glob('*.json'))
        if 'first-attempt' not in path.name and 'browser-ipc' not in path.name]
    for path in paths:
        receipt_name = path.relative_to(EVIDENCE).as_posix()
        if 'AUD4' in path.name or path.name.endswith('first-attempt.json'):
            continue
        proof = json.loads(path.read_bytes())
        try:
            current = bindings(proof)
            effect_bindings(proof)
        except ValueError as exc:
            rejected[receipt_name] = str(exc)
            continue
        checks = proof.get('checks', proof.get('parserChecks', {}))
        if not isinstance(checks, dict):
            continue
        accepted[receipt_name] = proof
        summaries[receipt_name] = {'sha256': sha(path), 'sourceBindings': len(current),
            'passingChecks': [key for key, value in checks.items() if value is True],
            'failedChecks': [key for key, value in checks.items() if value is not True],
            'boundary': proof.get('boundary'), 'ok': proof.get('ok'),
            'visualChecks': proof.get('visualChecks', proof.get('pdfVisualChecks')),
            'visualReady': proof.get('visualReady', proof.get('pdfVisualReady')),
            'outsideRequirement': proof.get('outsideRequirement')}
    for name in REQUIRED:
        filename = 'FIXCL3-' + name + '.json'
        proof = accepted.get(filename)
        if not proof or proof.get('ok') is False or not proof.get('checks', proof.get('parserChecks')) or summaries[filename]['failedChecks']:
            raise ValueError('Required real layer unpassed or stale: ' + filename + ' ' + rejected.get(filename, ''))
    regression = regression_boundary(accepted)
    actual = {}
    positive, rejected_uses = positive_uses(accepted)
    if rejected_uses:
        raise ValueError('Stale admitted positive manual witnesses: ' + str(rejected_uses[:3]))
    for row in positive:
        if row['tool'].removeprefix('neyvia.') not in positive_calls(accepted[row['receipt']]):
            continue
        actual.setdefault(row['tool'], []).append(row)
    baseline = {row['tool']: row for row in before['actionInventory']}
    transitions = [dict(row, before=baseline.get(row['tool'], {}).get('effectStatus'))
                   for row in after['actionInventory']
                   if row['effectStatus'] != baseline.get(row['tool'], {}).get('effectStatus')]
    missing = [row['tool'] for row in transitions if row['effectStatus'] == 'grounded_adapter'
               and row['before'] != 'grounded_adapter' and row['tool'] not in actual]
    if missing:
        raise ValueError('New effect adapters lack retained positive CL manual witnesses: ' + ', '.join(missing))
    projection = json.loads((EVIDENCE / 'FIXCL3-manual-compile.json').read_bytes())
    codec = json.loads((EVIDENCE / 'FIXCL3-codec-invariants.json').read_bytes())
    if codec.get('ok') is not True or len(codec.get('checks', [])) != 10:
        raise ValueError('Typed codec invariants did not pass')
    if projection['mode'] != 'check' or not all(row['equal'] is True for row in projection['results']):
        raise ValueError('Manual executable projection differs')
    for row in projection['results']:
        if hashlib.sha256(Path(row['source']).read_text(encoding='utf-8').encode()).hexdigest() != row['source_sha256']:
            raise ValueError('Manual projection source drift: ' + row['id'])
    proof_artifacts = {}
    for proof in accepted.values():
        for relative in proof.get('sourceHashesAtStart', proof.get('sourceHashes', {})):
            normalized = relative.replace('\\', '/')
            if normalized.startswith('.agent_control/fixcl2/renderer-dist-e2e68586/'):
                proof_artifacts[normalized] = sha(checked_path(relative))
            elif not normalized.startswith('web/'):
                source_map[normalized] = sha(checked_path(relative))
    source_map['scripts/seal_fixcl3.py'] = sha(Path(__file__))
    for relative in ('scripts/fixcl3_aud4_matrix.py', 'scripts/fixcl_codec_probe.py', 'scripts/cl_compile_manuals.py'):
        source_map[relative] = sha(checked_path(relative))
    checkout_forms = committed_bytes(source_map)
    cold = accepted['FIXCL3-cold.json']['latency']
    inventory = after['actionInventory']
    frontier = [row for row in inventory if row['effectStatus'] == 'frontier']
    boundary_path = EVIDENCE / 'FIXCL3-AUD4-after-frontier.json'
    boundaries = json.loads(boundary_path.read_bytes()) if boundary_path.is_file() else None
    baseline_raw = subprocess.check_output(['git', 'show', '152a5368:scripts/evidence/FIXCL2.json'],
        cwd=REPO, creationflags=0x08000000)
    previous = json.loads(baseline_raw)
    commits = subprocess.check_output(['git', 'log', '152a5368..HEAD', '--format=%H %s'],
        cwd=REPO, text=True, creationflags=0x08000000).splitlines()
    result = {'schema': 'neyvia.FIXCL3.v1', 'status': 'partial_with_explicit_frontiers',
        'baseline': {'commit': '152a5368', 'frontierActions': previous['coverage']['statuses']['frontier'],
                     'coldProcessP50Ms': previous['latency']['measurements']['coldProcess']['p50Ms'],
                     'receiptSha256': hashlib.sha256(baseline_raw).hexdigest(), 'AUD4': matrices['before']['counts']},
        'checks': {'full185CellMatrixRerun': True, 'requiredRealLayersPassed': True,
            'freshSourceBindingsCurrent': True, 'allNewEffectAdaptersHavePositiveCLWitnesses': True,
            'manualProjectionEqual': True, 'allRegisteredFamiliesTyped': True,
            'typedCodecInvariantsPassed': True, 'productSourceMatchesCommittedSource': True,
            'allChangedSourceBytesMatchCommittedSourceExactly': True},
        'coverage': {'registeredActions': len(inventory), 'statuses': dict(Counter(row['effectStatus'] for row in inventory)),
            'actionInventory': inventory, 'changedActions': transitions,
            'newAdaptersWithoutSuccessfulCLActionWitness': missing, 'positiveEffectWitnesses': actual,
            'frontierBoundaries': boundaries,
            'boundary': 'Only exact retained positive calls establish effects; codec/classification presence does not.'},
        'AUD4': {label: {'counts': matrix['counts'], 'sha256': sha(EVIDENCE / ('FIXCL3-AUD4-' + label + '.json'))}
                 for label, matrix in matrices.items()},
        'latency': {'measurements': cold, 'p50TargetMs': 3000,
                    'p50RegressionVsBaselineMs': round(cold['coldProcess']['p50Ms'] - previous['latency']['measurements']['coldProcess']['p50Ms'], 3),
                    'p50TargetMet': cold['coldProcess']['p50Ms'] < 3000},
        'automaticProvisioning': accepted['FIXCL3-provision.json'],
        'receipts': summaries, 'rejectedRetainedReceipts': rejected,
        'originalFunctionalRegression': regression,
        'retainedBuildArtifactBindings': {'sha256': proof_artifacts,
            'boundary': 'Exact current retained PDF.js build dependency bytes used by the real renderer probes; untracked task-local artifacts, not committed product source or a new release build.'},
        'unchangedWindowsCheckoutBindings': checkout_forms,
        'sourceHashes': source_map, 'localCommits': commits,
        'limitations': ['Remaining frontier actions are incomplete, including explicit local implementation gaps.',
            'Local paired/provider fixtures establish exact local transport and bytes, not outside devices/accounts or model generation.',
            'Obscura native PDF canvas transforms are broken; actual parser/text/state proof does not establish rendered PDF pixels.',
            'Renderer uses the previously supplied built UI and a relay of real backend SSE; native streaming/desktop WebView2 are unproved.',
            'Provisioning is automatic with existing dependencies and bounded pinned downloads; unavailable public CDN remains a real dependency.',
            'No public promotion, NAS sync, push or merge.']}
    output = EVIDENCE / 'FIXCL3.json'
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'receipt': str(output), 'frontierActions': len(frontier),
        'newAdapterWitnesses': len([row for row in transitions if row['effectStatus'] == 'grounded_adapter' and row['tool'] in actual]),
        'AUD4': {label: matrix['counts'] for label, matrix in matrices.items()}, 'latency': result['latency']}))


if __name__ == '__main__':
    main()
