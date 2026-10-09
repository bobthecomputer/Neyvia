"""Seal recovered real C7 runs without inventing interrupted compiled replays."""
from collections import Counter
import argparse
import ast
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def reference(path):
    path = Path(path).resolve()
    path.relative_to(REPO)
    return {'path': path.relative_to(REPO).as_posix(),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}


def fixture_transport_review():
    """Admit only the exact reviewed journal repair, never a product change."""
    name = 'src/grant_agent/edge_fixture_models.py'
    before = subprocess.check_output(['git', 'show', '0b7331ad2:' + name], cwd=REPO).decode('utf8')
    after = (REPO / name).read_text(encoding='utf8')
    old = '        with effect.open("a", encoding="utf-8") as handle:\n            handle.write(json.dumps({"target": target, "arguments": arguments, "approved": context["approved"]}, ensure_ascii=False) + "\\n")'
    new = '        append_jsonl_durable(effect, {"target": target, "arguments": arguments, "approved": context["approved"]})'
    expected = before.replace('def _loop(root, category):\n    from .model_tool_intelligence import ModelToolIntelligence, ToolFeedbackStore',
                              'def _loop(root, category):\n    from .model_tool_intelligence import ModelToolIntelligence, ToolFeedbackStore\n    from .durability import append_jsonl_durable')
    expected = expected.replace(old, new)
    if before == expected or ast.dump(ast.parse(expected)) != ast.dump(ast.parse(after)):
        raise ValueError('Fixture changes exceed the reviewed append transport repair')
    return name, hashlib.sha256(before.encode()).hexdigest()


def seal(port):
    from grant_agent.edge_fixture_catalog import BUILDERS
    from grant_agent.proof_contracts import source_digest
    from grant_agent.edge_contracts import inventory, matrix
    from grant_agent.durability import atomic_write_json
    evidence = REPO / 'scripts/evidence'
    accounting = json.loads((evidence / 'C7e-resume-accounting.json').read_bytes())
    if accounting['completedFamilies'] != len(BUILDERS) or accounting['caseTotals']['failing']:
        raise ValueError('Recovered denominator is incomplete')
    repaired, historical_digest = fixture_transport_review()
    selected = {r['family']: r for r in accounting['familyReceipts']}
    fresh = json.loads((evidence / 'C7e-models-resume.json').read_bytes())
    selected['models'] = fresh['familyReceipts'][0]
    if set(selected) != set(BUILDERS) or not fresh['ok'] or fresh['explicitPort'] != port:
        raise ValueError('Fresh family selection differs')
    current_cache, retained, cases, families = {}, {}, [], []

    def retain(path):
        ref = reference(path)
        retained[ref['path']] = ref
        return ref

    for name in BUILDERS:
        entry = selected[name]
        path = (REPO / entry['path']).resolve() if not Path(entry['path']).is_absolute() else Path(entry['path']).resolve()
        ref = retain(path)
        if ref['sha256'] != entry['sha256']:
            raise ValueError('Family receipt changed: ' + name)
        raw = json.loads(path.read_bytes())
        if raw['family'] != name or not raw['sourceStable'] or not raw['rows'] or any(r['status'] != 'passed' for r in raw['rows']):
            raise ValueError('Nonpassing family: ' + name)
        differences = []
        for source, digest in raw['sourceBindings'].items():
            if source not in current_cache:
                current_cache[source] = source_digest(REPO / source)
            if current_cache[source] != digest:
                if source != repaired or digest != historical_digest or name == 'models':
                    raise ValueError('Unreviewed source change: ' + name + ':' + source)
                differences.append(source)
        cases.extend(raw['rows'])
        families.append({'family': name, 'cases': len(raw['rows']), 'counts': dict(Counter(r['status'] for r in raw['rows'])),
                         'receipt': ref, 'productionSourceCurrent': True, 'reviewedFixtureTransportDifferences': differences})
        if name == 'c7d-rendered':
            for row in raw['rows']:
                native = Path(row['detail']['receipt'])
                retain(native)
                value = json.loads(native.read_bytes())
                guard = value['desktopGuard']
                if (not value['ok'] or not value['sourceStable'] or guard['ownedVisibleWindows']
                        or not guard['inputDesktopNeverSwitched']
                        or guard['foregroundBefore'] != guard['foregroundAfter']
                        or guard['cursorBefore'] != guard['cursorAfter']):
                    raise ValueError('Recovered native desktop guard failed')
                # Retain actual PNGs and auxiliary receipts in the eight native run roots.
                for p in native.parent.rglob('*'):
                    if p.is_file() and p.suffix.lower() in {'.png', '.json'}:
                        retain(p)
    if len({r['id'] for r in cases}) != len(cases) or len(cases) != 4671:
        raise ValueError('Exact generated denominator differs')
    for source, digest in current_cache.items():
        if source_digest(REPO / source) != digest:
            raise ValueError('Source changed during sealing')
    authority_path = evidence / 'C7d-authority.json'
    authority = json.loads(authority_path.read_bytes())
    authority_cases = authority['originalAuthorityBlockers'] + authority['additionalAuthorityBlockers']
    if len(authority_cases) != 16:
        raise ValueError('Authority denominator differs')
    retain(authority_path)
    retain(evidence / 'C7e-models-resume.json')
    retain(evidence / 'C7e-models-append-repair.json')
    probes = json.loads((evidence / 'C7e-models-append-repair.json').read_bytes())
    for probe in probes['cases']:
        for field in ('effectJournal', 'feedbackJournal'):
            recorded = probe[field]
            if retain(REPO / recorded['path']) != recorded:
                raise ValueError('Repeated concurrency journal changed')
    retain(evidence / 'C7e-resume-manual-compile.json')
    retain(evidence / 'C7e-bugs.json')
    before_path = REPO / json.loads((evidence / 'C7e-models-append-repair.json').read_bytes())['before']['receipt']
    retain(before_path)
    failed = json.loads(before_path.read_bytes())
    if not any(r['id'] == 'models.loop.concurrency' and r['status'] == 'failed' for r in failed['rows']):
        raise ValueError('Original failed concurrency case disappeared')
    scratch = Path(next(r for r in failed['rows'] if r['id'] == 'models.loop.concurrency')['detail']['scratch'])
    retain(scratch / 'effects.jsonl')
    retain(scratch / '.agent_control/mission_artifacts/model_tool_intelligence/feedback.jsonl')
    for family in ('models', 'c7d-desktop', 'c7d-rendered'):
        workspace = json.loads((REPO / '.agent_control/C7e/compiled-families' / (family + '.workspace.json')).read_bytes())
        root = Path(workspace['root']).resolve()
        root.relative_to(REPO / '.agent_control/proofs/c7e-compiled')
        completed = []
        for path in (root / '.neyvia/manual-runs').glob('*.json'):
            run = json.loads(path.read_bytes())
            if run['status'] == 'completed':
                if run['id'] != 'C7e-' + family or not run['checks'] or not all(c['passed'] for c in run['checks']):
                    raise ValueError('Recovered manual goal checks differ')
                completed.append(retain(path))
        if not completed:
            raise ValueError('No checked original manual execution: ' + family)
    archive = evidence / 'C7-completed-family-runs.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for name, ref in retained.items():
            data = (REPO / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != ref['sha256']:
                raise ValueError('Retained artifact changed')
            zipped.writestr(name, data)
        zipped.writestr('manifest.json', json.dumps(list(retained.values()), indent=2))
    with zipfile.ZipFile(archive) as zipped:
        if zipped.testzip() or any(hashlib.sha256(zipped.read(name)).hexdigest() != ref['sha256'] for name, ref in retained.items()):
            raise ValueError('Evidence archive readback differs')
    baseline = evidence / 'C7-original-admission.json.gz'
    if not baseline.exists():
        baseline.write_bytes(gzip.compress((evidence / 'C7.json').read_bytes(), mtime=0))
    # Stored native witnesses never become fresh observations in this new process.
    contracts = inventory()[1]
    coverage = matrix(contracts, cases, semantic_fixtures=True)
    gaps = [row for row in coverage if row.get('blockerKind') == 'fixture_gap']
    matrix_bytes = (json.dumps(coverage, indent=2) + '\n').encode('utf8')
    matrix_path = evidence / 'C7-coverage.json.gz'
    matrix_path.write_bytes(gzip.compress(matrix_bytes, mtime=0))
    if gzip.decompress(matrix_path.read_bytes()) != matrix_bytes:
        raise ValueError('Full matrix archive differs')
    projection = [{k: row[k] for k in ('contract', 'category', 'status', 'blockerKind') if k in row} for row in coverage]
    bugs = json.loads((evidence / 'C7e-bugs.json').read_bytes())
    report = {'schema': 'neyvia.c7-completion.v1', 'ok': True, 'complete': False,
              'allowedFamilyRunsComplete': True, 'completedFamilies': len(families), 'explicitPort': port,
              'caseTotals': {'generated': len(cases), 'passed': len(cases), 'failed': 0, 'authorityBlocked': 16, 'total': 4687},
              'families': families, 'compiledFamilyReplays': {'completedBeforeInterruption': 41, 'unfinished': ['models', 'c7d-desktop', 'c7d-rendered']},
              'bugs': bugs['counts'], 'authorityCases': authority_cases, 'semanticCoverage': projection,
              'fullMatrix': reference(matrix_path),
              'matrixCounts': dict(Counter(row['status'] for row in coverage)),
              'matrixBlockers': dict(Counter(row.get('blockerKind') for row in coverage if row['status'] == 'blocked')),
              'uncoveredContractCategories': [{'contract': row['contract'], 'category': row['category'], 'requiredChecks': row['checkedAt']} for row in gaps],
              'semanticCoverageBoundary': 'Fresh live witnesses are absent from this archival seal; stored rendered witnesses are not re-admitted as live observations.',
              'evidenceArchive': reference(archive), 'artifactCount': len(retained), 'baseline': reference(baseline),
              'verificationSourceReview': {'path': repaired, 'beforeSha256': historical_digest, 'afterSha256': source_digest(REPO / repaired),
                                         'scope': 'Only fixture effect-journal transport changed; all production source bindings match and models was rerun.'},
              'knownLimits': ['Obscura headless 3D painting may be blank; nonblocking per Paul.', '16 installed credential-doctor/legacy Chrome authority cases remain unrun.',
                              'Three compiled replays were interrupted; all 44 families have actual completed checked runs.',
                              str(len(gaps)) + ' contract/category slots remain without a generated case; family execution totals are not full matrix closure.'],
              'boundary': 'Recovered original real executions plus a fresh full models family. Archival proof, not a fresh all-family campaign, release gate, provider/device proof or promotion.'}
    atomic_write_json(evidence / 'C7.json', report)
    print(json.dumps({'families': len(families), 'cases': report['caseTotals'], 'archive': reference(archive), 'artifacts': len(retained)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True, choices=range(48731, 48740))
    seal(parser.parse_args().port)
