"""Evidence: improve() with real UI fix actions on the three P22 bugs at their pre-fix commit.

Tree: commit 9589de605 exported to D:/NeyviaRuns/CORE/ui-fix/src-9589de605 (web/, vite
config, package.json, node_modules junction to Neyvia-next). Each transcription is a fresh
production build of the tree (cached per source digest) rendered privately in the admitted
headless Obscura on CORE ports 49114/49115, observed as DOM + pixel facts.

For each bug: one improve() call allowed only a plausible-but-wrong fix (expected: reverted,
tree restored byte-identical), then one allowed only the named fix (expected: kept).
Guards: minFontPx min, pageErrors max (textNodes is reported; app-state noise moves it). Receipts: .agent_control/CORE/ui-improve.

Usage: python scripts/core_ui_fix_proof.py [--cases chips,see-through,pdf]
       -> scripts/evidence/CORE-ui-fix.json
Assigned allocation (grant_agent.assigned_ports): --port-block 49171-49179 renders on the block's
first pair; --scratch-root R exports a fresh 9589de605 tree to R/CORE/ui-fix/src-9589de605 (git
archive + node_modules junction), keeps runs under R/CORE/ui-fix and writes R/scripts/evidence/CORE-ui-fix.json.
"""
from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
TREE = Path('D:/NeyviaRuns/CORE/ui-fix/src-9589de605')
RUNS = Path('D:/NeyviaRuns/CORE/ui-fix')
STATE_ROOT = ROOT / '.agent_control/CORE/ui-improve'
GUARDS = {'minFontPx': 'min', 'pageErrors': 'max'}
CASES = {
    'chips': {'state': 'files-main', 'predicate': 'clipped-text', 'bad': 'ui.css.shrink-text', 'good': 'ui.css.align-start',
              'goodCalls': 3, 'withinClass': 'nx-chip', 'bug': 'Composer chips lose their first letters (P22 render-before-chips)'},
    'see-through': {'state': 'files-side-floating', 'predicate': 'see-through', 'bad': 'ui.css.opaque-surface',
                    'good': 'ui.css.stacking-layer', 'goodCalls': 2, 'bug': 'Shell text paints through a floating side panel (P22 render-before-pointer)'},
    'pdf': {'state': 'pdf', 'predicate': 'blank-render', 'bad': 'ui.patch.pdf-plain-skeleton',
            'good': 'ui.patch.pdf-module-worker-fallback', 'goodCalls': 1, 'bug': 'Black PDF page (P22 render-before at 9589de605)'},
}


def targets(scene, case):
    """The bug's own findings: chips are clipped-text whose DOM owner sits inside an nx-chip."""
    from grant_agent import scene_core
    from grant_agent.laya_ui_fix import _classes, _dom_owner
    found = [f for f in scene_core.judge(scene, record=False)['findings'] if f['predicate'] == case['predicate']]
    if case.get('withinClass'):
        nodes = {n['id']: n for n in scene['nodes']}
        found = [f for f in found if (owner := _dom_owner(scene, nodes.get(f['node'])))
                 and any(c.startswith(case['withinClass']) for c in _classes(scene, owner['attributes']['element']))]
    return sorted({f['node'] for f in found})


def summary(scene, verdict):
    kinds = {}
    for f in verdict['findings']:
        kinds.setdefault(f['predicate'], []).append(f['node'])
    return {'sceneSha256': scene['sha256'], 'findings': {k: sorted(v) for k, v in sorted(kinds.items())},
            'metrics': {k: scene.get('metrics', {}).get(k) for k in GUARDS}, 'render': scene.get('provenance', {}).get('render'),
            'sourceDigest': scene.get('provenance', {}).get('sourceDigest'), 'timings': scene.get('timings')}


def steps(outcome):
    return [{'finding': {k: s['finding'][k] for k in ('predicate', 'node')}, 'action': s['finding']['fix']['action'],
             'status': s['status'], 'guarded': s.get('guarded'), 'before': s.get('before'), 'after': s.get('after'),
             'fix': s.get('fix'), 'error': s.get('error')} for s in outcome['steps']]


def tree_diff(snapshot):
    from grant_agent.laya_ui_fix import _web_files
    lines = []
    for path in _web_files(TREE):
        rel = path.relative_to(TREE).as_posix()
        old = snapshot['files'].get(rel)
        new = path.read_bytes()
        if old != new:
            lines += difflib.unified_diff((old or b'').decode(errors='replace').splitlines(), new.decode(errors='replace').splitlines(),
                                          'a/' + rel, 'b/' + rel, lineterm='', n=1)
    return '\n'.join(lines)


COMMIT = '9589de605'
NODE_MODULES = Path('C:/Users/user/Projects/Neyvia-next/node_modules')


def export_tree(tree):
    """Fresh export of the pre-fix commit (same paths as the original export), for a scratch root only."""
    import io, subprocess, tarfile
    tree.mkdir(parents=True, exist_ok=True)
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    data = subprocess.run(['git', 'archive', '--format=tar', COMMIT, 'web', 'vite.config.mjs', 'package.json',
                           'scripts/release-contracts.mjs'], cwd=ROOT, capture_output=True, check=True, creationflags=flags).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(tree, filter='data')
    subprocess.run(['cmd', '/c', 'mklink', '/J', str(tree / 'node_modules'), str(NODE_MODULES)], capture_output=True,
                   check=True, creationflags=flags)


def run_case(name, case, pristine, ports):
    from grant_agent import scene_core
    from grant_agent.laya_ui_fix import digest, restore
    restore({'tree': str(TREE)}, pristine)
    source = {'tree': str(TREE), 'state': case['state'], 'variant': 'dark-desktop', 'ports': ports, 'runs': str(RUNS)}
    started = time.perf_counter()
    before = scene_core.transcribe('ui', source)
    report = {'bug': case['bug'], 'state': case['state'], 'predicate': case['predicate'],
              'before': summary(before, scene_core.judge(before, record=False)), 'calls': []}
    focus = targets(before, case)
    report['focus'] = focus
    budget = {'max_steps': 1, 'max_seconds': 300, 'allowed_fixes': [case['bad']], 'guards': GUARDS, 'nodes': focus}
    outcome = scene_core.improve('ui', source, budget, root=STATE_ROOT)
    report['calls'].append({'allowed': case['bad'], 'role': 'wrong candidate', 'receipt': outcome['receipt'], 'steps': steps(outcome),
                            'treeRestored': digest(TREE) == pristine['digest']})
    for _ in range(case['goodCalls']):
        current = scene_core.judge(scene_core.transcribe('ui', source), record=False)
        if not any(f['predicate'] == case['predicate'] and f['node'] in focus for f in current['findings']):
            break
        budget = {'max_steps': 3, 'max_seconds': 300, 'allowed_fixes': [case['good']], 'guards': GUARDS,
                  'nodes': [n for n in focus if any(f['node'] == n for f in current['findings'])]}
        outcome = scene_core.improve('ui', source, budget, root=STATE_ROOT)
        report['calls'].append({'allowed': case['good'], 'role': 'named fix', 'receipt': outcome['receipt'], 'steps': steps(outcome)})
        if not any(s['status'] == 'kept' for s in outcome['steps']):
            break
    after = scene_core.transcribe('ui', source)
    report['after'] = summary(after, scene_core.judge(after, record=False))
    report['retainedPatch'] = tree_diff(pristine)
    report['seconds'] = round(time.perf_counter() - started, 1)
    before_hits = len(focus)
    report['remainingTargets'] = targets(after, case)  # recomputed: a fixed label reads differently
    after_hits = len(report['remainingTargets'])
    kept = [s for c in report['calls'] if c['role'] == 'named fix' for s in c['steps'] if s['status'] == 'kept']
    reverted = [s for c in report['calls'] if c['role'] == 'wrong candidate' for s in c['steps'] if s['status'] == 'reverted']
    report['checks'] = {
        'bugObservedBefore': before_hits > 0,
        'wrongCandidateReverted': bool(reverted) and report['calls'][0]['treeRestored'],
        'namedFixKept': bool(kept),
        'bugGoneAfter': after_hits == 0,
        'guardsHeld': all(s['guarded'] for s in kept),
    }
    report['passed'] = all(report['checks'].values())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', default=','.join(CASES))
    parser.add_argument('--ports', default=None, help='backend,engine (default 49114,49115, or the first pair of --port-block)')
    from grant_agent.assigned_ports import add_arguments, apply, output, state, under
    add_arguments(parser)
    args = parser.parse_args()
    global TREE, RUNS, STATE_ROOT
    block, scratch = apply(args, 'CORE')
    TREE, RUNS = under('CORE/ui-fix/src-' + COMMIT, TREE), under('CORE/ui-fix', RUNS)
    STATE_ROOT = state('CORE/ui-improve') if scratch else STATE_ROOT
    exported = None
    if scratch and not TREE.exists():
        export_tree(TREE); exported = str(TREE)
    from grant_agent.laya_ui_fix import checkpoint, digest
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    pristine_path = RUNS / 'pristine-9589de605.json'
    if not pristine_path.is_file():  # the export as written by git archive, before any fix
        snap = checkpoint({'tree': str(TREE), 'state': 'home'})
        pristine_path.write_text(json.dumps({'digest': snap['digest'], 'files': {k: v.decode('latin-1') for k, v in snap['files'].items()}}), encoding='utf-8')
    saved = json.loads(pristine_path.read_text(encoding='utf-8'))
    pristine = {'digest': saved['digest'], 'files': {k: v.encode('latin-1') for k, v in saved['files'].items()}}
    evidence_path = output('scripts/evidence/CORE-ui-fix.json'); evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence = json.loads(evidence_path.read_text(encoding='utf-8')) if evidence_path.is_file() else {}
    evidence.update({'schema': 'neyvia.core-ui-fix.v1', 'command': 'python scripts/core_ui_fix_proof.py',
                     'tree': str(TREE), 'commit': '9589de605', 'pristineDigest': pristine['digest'], 'guards': GUARDS})
    evidence.setdefault('cases', {})
    ports = [int(p) for p in args.ports.split(',')] if args.ports else list(block.pair(0)) if block else [49114, 49115]
    evidence['allocation'] = {'ports': ports, 'portBlock': str(block) if block else None, 'scratchRoot': str(scratch) if scratch else None,
                              'exportedTree': exported, 'runs': str(RUNS), 'stateRoot': str(STATE_ROOT)}
    for name in args.cases.split(','):
        try:
            evidence['cases'][name] = run_case(name, CASES[name], pristine, ports)
        except Exception as exc:
            import traceback
            evidence['cases'][name] = {'passed': False, 'error': f'{type(exc).__name__}: {exc}', 'traceback': traceback.format_exc()[-2000:]}
        evidence['passed'] = all(c.get('passed') for c in evidence['cases'].values()) and set(evidence['cases']) == set(CASES)
        evidence_path.write_text(json.dumps(evidence, indent=1, default=str) + '\n', encoding='utf-8')
        print(name, json.dumps(evidence['cases'][name].get('checks') or evidence['cases'][name].get('error')), flush=True)
    from grant_agent.laya_ui_fix import restore
    restore({'tree': str(TREE)}, pristine)  # leave the export as committed
    evidence['proof'] = proof(evidence)
    evidence['passed'] = evidence['passed'] and all(c['passed'] for c in evidence['proof']['checks'])
    evidence_path.write_text(json.dumps(evidence, indent=1, default=str) + '\n', encoding='utf-8')
    print(json.dumps({'passed': evidence['passed'], 'proof': {k: v for k, v in evidence['proof'].items() if k != 'checks'},
                      'failedChecks': [c['name'] for c in evidence['proof']['checks'] if not c['passed']]}))


def proof(evidence):
    """CL owns acceptance (manuals/cl/laya-ui-fix.cl, fix.verify checks)."""
    from grant_agent.cl_skill import _parse_skill, _Expr
    from grant_agent.laya_glance_gate import _admitted_engine
    from grant_agent.laya_instant import store
    cases = [c for c in evidence['cases'].values() if 'checks' in c]
    kept = [s for c in cases for call in c['calls'] if call['role'] == 'named fix' for s in call['steps'] if s['status'] == 'kept']
    admitted = _admitted_engine()[1]
    renders = [json.loads(p.read_text(encoding='utf-8')).get('provenance', {}).get('engineSha256') for p in (RUNS / 'scenes').glob('*.json')]
    memory = store(str(STATE_ROOT)); memory.refresh()
    summary = {'bugs': len(cases), 'observedBefore': sum(c['checks']['bugObservedBefore'] for c in cases),
               'wrongReverted': sum(c['checks']['wrongCandidateReverted'] for c in cases),
               'treeRestored': sum(bool(c['calls'][0].get('treeRestored')) for c in cases),
               'namedKept': sum(c['checks']['namedFixKept'] for c in cases), 'goneAfter': sum(c['checks']['bugGoneAfter'] for c in cases),
               'guardRegressions': sum(not s['guarded'] for s in kept), 'privateRender': bool(renders) and all(r == admitted for r in renders),
               'training': False, 'episodes': len(memory.rows), 'renders': len(renders)}
    skill = _parse_skill(ROOT / 'manuals/cl/laya-ui-fix.cl')
    summary['checks'] = [{'name': c.name, 'expr': c.expr, 'passed': bool(_Expr(c.expr, {'proof': summary}, {}).run())}
                         for c in skill.checks if c.action == 'fix.verify']
    return summary


if __name__ == '__main__':
    main()
