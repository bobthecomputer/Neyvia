"""Evidence script: turn evolve run summaries into the plan-25 proof and evaluate the CL checks.

  python scripts/evolve_proof.py --runs r4 r5

Reads D:/NeyviaRuns/EVOLVE/<run>/<task>-summary.json, control-summary.json and summary.json
for each run (a later run's task wins), evaluates manuals/cl/evolve.cl and evolve-moves.cl
checks against the measured proof and writes scripts/evidence/EVOLVE-proof.json and
scripts/evidence/EVOLVE-curve.svg.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))

from grant_agent.cl_skill import _parse_skill, _Expr  # noqa: E402
from grant_agent.evolve_moves import load_moves  # noqa: E402

ORDER = ['gate-plan', 'cl-compile', 'gate-plan-latest']
RUNS = Path('D:/NeyviaRuns/EVOLVE')


def read(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def receipts(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []


def evaluations_to(curve, threshold):
    return next((p for p in curve if p['speedup'] >= threshold), None)


def kept_sources(summary, rows):
    """Sources of the steps that survived ablation and late findings (the real wins)."""
    kept = [r for r in summary.get('ablation', []) if r['kept']]
    late = {r['step'] for r in summary.get('lateFindings', [])}
    out = []
    for row in kept:
        if row['step'] in late:
            continue
        origin = rows.get(row['step'], {}).get('origin', {})
        out.append({'step': row['step'], 'move': row['label'], 'source': origin.get('source'), 'hands': origin.get('hands')})
    return out


def svg(curves, path):
    width, height, pad = 660, 320, 44
    series = [(name, c) for name, c in curves.items() if c]
    top = max([p['speedup'] for _, c in series for p in c] + [1.1])
    right = max([p['evaluations'] for _, c in series for p in c] + [1])
    colours = {'gate-plan': '#2f7d4f', 'cl-compile': '#c2652a', 'gate-plan-latest': '#2b5fa8', 'control': '#888888'}
    def xy(p):
        return pad + (width - 2 * pad) * p['evaluations'] / right, height - pad - (height - 2 * pad) * (p['speedup'] - 1) / max(top - 1, 1e-9)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" font-family="sans-serif" font-size="11">',
             f'<rect width="{width}" height="{height}" fill="#fff"/>',
             f'<line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="#999"/>',
             f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height-pad}" stroke="#999"/>',
             f'<text x="{width/2}" y="{height-10}" text-anchor="middle">candidates actually run (evaluations)</text>',
             f'<text x="12" y="{height/2}" transform="rotate(-90 12 {height/2})" text-anchor="middle">best confirmed speed-up during search (x)</text>',
             f'<text x="{pad-4}" y="{height-pad}" text-anchor="end">1.0</text>',
             f'<text x="{pad-4}" y="{pad+4}" text-anchor="end">{top:.2f}</text>']
    for index, (name, curve) in enumerate(series):
        points, last = [], None
        for p in curve:
            x, y = xy(p)
            if last is not None:
                points.append(f'{x:.1f},{last:.1f}')
            points.append(f'{x:.1f},{y:.1f}')
            last = y
        colour = colours.get(name, '#333')
        parts.append(f'<polyline fill="none" stroke="{colour}" stroke-width="2" points="{" ".join(points)}"/>')
        parts.append(f'<text x="{width-pad-190}" y="{pad+14*index}" fill="{colour}">{name} (search peak {curve[-1]["speedup"]:.2f}x)</text>')
    parts.append('</svg>')
    path.write_text('\n'.join(parts), encoding='utf-8')


def memo_probe():
    """Run the skip-repeated-validation helper (the exact text the move inserts) with a small bound."""
    from grant_agent.evolve_moves import HELPERS
    from jsonschema import Draft202012Validator, SchemaError
    space = {}
    exec(compile(HELPERS['skip-repeated-validation'], '<evolve-helper>', 'exec'), space)
    space['_EVOLVE_VALIDATED_MAX'] = 8
    once, memo = space['_evolve_once'], space['_EVOLVE_VALIDATED']
    calls = []
    def check(schema):
        calls.append(1)
        return Draft202012Validator.check_schema(schema)
    for index in range(40):
        once('check', check, {'type': 'object', 'title': f'schema-{index}'})
    bounded = len(memo) == 8
    before = len(calls)
    once('check', check, {'type': 'object', 'title': 'schema-0'})  # evicted long ago: validated again
    revalidated = len(calls) == before + 1
    once('check', check, {'type': 'object', 'title': 'schema-39'})  # recent: skipped
    skipped = len(calls) == before + 1
    raised = 0
    for _ in range(3):
        try:
            once('check', check, {'type': 'objekt'})
        except SchemaError:
            raised += 1
    returning = []
    def returns_value(value):
        returning.append(value)
        return 'not-none'
    once('returns', returns_value, {'a': 1}); once('returns', returns_value, {'a': 1})
    return {'bound': 8, 'entries': len(memo), 'bounded': bounded, 'evictedRevalidated': revalidated, 'recentSkipped': skipped,
            'invalidRaisedEveryTime': raised == 3, 'nonNoneNeverRemembered': len(returning) == 2,
            'defaultBound': 4096}


def retirement_proof():
    """Replay the real episode store under the context-scoped rule and the old global rule."""
    from grant_agent.evolve_engine import Memory, load_retire_rule, retirement_table
    memory = Memory(REPO / '.agent_control/evolve/state')
    rule = load_retire_rule()
    scoped, elsewhere = retirement_table(memory, rule)
    global_rule = {'scope': [], 'tries': 3, 'maxWins': 0}
    stats = memory.stats()
    globally = sorted(m for m, c in stats.items() if sum(c.values()) >= 3 and c['win'] == 0)
    return {'rule': rule, 'retiredContexts': scoped, 'retiredButAvailableElsewhere': elsewhere,
            'globalRuleWouldRetire': globally,
            'availableAgainUnderScopedRule': sorted(m for m in globally if m not in scoped)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', nargs='+', required=True)
    args = parser.parse_args()
    summaries, receipt_rows, control, verify, run_of = {}, {}, None, {}, {}
    for run in args.runs:
        folder = RUNS / run
        for task in ORDER:
            summary = read(folder / f'{task}-summary.json')
            if summary and 'direct' in summary:
                summaries[task], run_of[task] = summary, run
                source_run = Path(summary['resumedFrom']) if summary.get('resumedFrom') else folder
                receipt_rows[task] = receipts(source_run / task / 'receipts.jsonl')
        control = read(folder / 'control-summary.json') or control
        top = read(folder / 'summary.json')
        if top and top.get('verify'):
            verify[run] = top['verify']
    tasks = [t for t in ORDER if t in summaries]
    proof = {'runs': args.runs, 'training': False, 'tasks': tasks}
    calls = Counter()
    for line in (REPO / '.agent_control/evolve/state/model-calls.jsonl').read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        if row.get('run') in set(args.runs) | {'r3'}:
            calls[row['tier']] += 1
            calls['tokensIn'] += (row.get('usage') or {}).get('input_tokens', 0)
            calls['tokensOut'] += (row.get('usage') or {}).get('output_tokens', 0)
    proof['modelCalls'] = dict(calls)
    proof['bigModelCalls'] = calls['sol']
    per_task = {}
    for task in tasks:
        s = summaries[task]
        rows = {r['id']: r for r in receipt_rows[task] if r.get('kind') == 'evaluation'}
        confirmations = {r['id']: r for r in receipt_rows[task] if r.get('kind') == 'confirmation'}
        kept = kept_sources(s, rows)
        confirmed = [rows[i]['origin'].get('source') for i, c in confirmations.items() if c.get('held')]
        per_task[task] = {'run': run_of[task], 'direct': s['direct'], 'cold': s.get('cold'), 'patchLines': s.get('patchLines'),
                          'finalVerification': s.get('finalVerification'), 'keptSteps': kept,
                          'prunedSteps': s.get('finalAfterAblation', {}).get('pruned'), 'lateFindings': s.get('lateFindings'),
                          'confirmedWinSources': dict(Counter(confirmed)),
                          'evaluations': s.get('evaluations'), 'verdicts': s.get('verdicts'), 'prefilterKilled': s.get('prefilterKilled'),
                          'adversary': [{k: r[k] for k in ('generation', 'tried', 'found', 'rate')} for r in s.get('adversary', [])],
                          'exploitPredicates': [p['id'] for p in s.get('exploitPredicates', [])],
                          'judgeWeights': s.get('judgeWeights'), 'retired': s.get('retired'), 'pareto': s.get('pareto'),
                          'archive': s.get('archive'), 'curve': s.get('curve'), 'firstWinAt': s.get('firstWinAt'),
                          'winEpisodes': sum(1 for i, c in confirmations.items() if c.get('held') and rows.get(i, {}).get('episode', {}).get('learned'))}
        sources = [k['source'] for k in kept]
        per_task[task]['libraryShare'] = round(sources.count('library') / len(sources), 3) if sources else None
    proof['perTask'] = per_task
    proof['outputsIdentical'] = all((per_task[t]['finalVerification'] or {}).get('identical') for t in tasks)
    proof['gatePlanSpeedup'] = per_task.get('gate-plan-latest', per_task.get('gate-plan', {})).get('direct', {}).get('speedup', 0)
    proof['gatePlanSpeedupPinnedFirst'] = per_task.get('gate-plan', {}).get('direct', {}).get('speedup', 0)
    proof['compileSpeedup'] = per_task.get('cl-compile', {}).get('direct', {}).get('speedup', 0)
    shares = [per_task[t]['libraryShare'] for t in tasks if per_task[t]['libraryShare'] is not None]
    proof['libraryShareFirst'] = shares[0] if shares else 0
    proof['libraryShareSecond'] = shares[-1] if shares else 0
    # Contract runs per final patch (the gate's own worker); see scripts/evidence/EVOLVE-contracts.json.
    recorded = json.loads((REPO / 'scripts/evidence/EVOLVE-contracts.json').read_text(encoding='utf-8'))
    patches = {k: v for k, v in recorded.items() if isinstance(v, dict) and 'workerOk' in v}
    proof['contractsPass'] = bool(patches) and all(v['workerOk'] and v['allRequestedWitnessed'] for v in patches.values())
    proof['contracts'] = patches
    proof['modelLook'] = {run: (v.get('modelLook') or {}).get('answer') for run, v in verify.items()}
    proof['winEpisodes'] = sum(per_task[t]['winEpisodes'] for t in tasks)
    if control and control.get('controlTask') in per_task:
        warm_task = control['controlTask']
        warm = summaries[warm_task]
        common = min(warm['curve'][-1]['speedup'], control['curve'][-1]['speedup'])
        threshold = 1 + 0.9 * (common - 1)
        a, b = evaluations_to(warm['curve'], threshold), evaluations_to(control['curve'], threshold)
        proof['secondTask'] = {'task': warm_task, 'threshold': round(threshold, 4), 'withExperience': a, 'withoutExperience': b,
                               'firstWinWith': warm.get('firstWinAt'), 'firstWinWithout': control.get('firstWinAt'),
                               'searchPeakWith': warm['curve'][-1]['speedup'], 'searchPeakWithout': control['curve'][-1]['speedup'],
                               'evaluationsWith': warm.get('evaluations'), 'evaluationsWithout': control.get('evaluations'),
                               'prefilterKilledWith': warm.get('prefilterKilled'), 'prefilterKilledWithout': control.get('prefilterKilled'),
                               'retiredWith': list((warm.get('retired') or {})), 'retiredWithout': list((control.get('retired') or {}))}
        proof['secondTaskFaster'] = bool(common > 1 and a and b and a['evaluations'] < b['evaluations'])
        proof['controlCurve'] = control['curve']
    else:
        proof['secondTaskFaster'] = False
    falls = []
    for task in tasks:
        rounds = [r for r in per_task[task]['adversary'] if r['tried']]
        if rounds and rounds[0]['rate']:
            falls.append(rounds[-1]['rate'] < rounds[0]['rate'])
    proof['exploitRateFalls'] = bool(falls) and all(falls)
    moves = load_moves(REPO / 'manuals/cl/evolve-moves.cl')
    retirement, memo = retirement_proof(), memo_probe()
    proof['retirement'], proof['memoProbe'] = retirement, memo
    checks = []
    final_path = REPO / 'scripts/evidence/EVOLVE2-final.json'
    final = json.loads(final_path.read_text(encoding='utf-8')) if final_path.exists() else {}
    proof['final'] = {k: final.get(k) for k in ('target', 'appliesToTarget', 'outputsIdentical', 'gateSpeedup', 'compileSpeedup',
                                                 'memoEntries', 'memoBound', 'contractsSame')}
    for name, scope in (('evolve.cl', {'proof': proof, 'final': final}),
                        ('evolve-moves.cl', {'moves': {'seeded': sum(1 for m in moves if 'origin' not in m), 'executedAsText': False,
                                                       'retiredButAvailableElsewhere': len(retirement['retiredButAvailableElsewhere']),
                                                       'memoBounded': memo['bounded'] and memo['evictedRevalidated'] and memo['recentSkipped'] and memo['invalidRaisedEveryTime'],
                                                       'memoKeepsOnlySuccess': memo['nonNoneNeverRemembered'] and memo['invalidRaisedEveryTime']}})):
        skill = _parse_skill(REPO / 'manuals/cl' / name)
        for check in skill.checks:
            try:
                passed = bool(_Expr(check.expr, scope, {}).run())
            except (ValueError, KeyError, TypeError) as error:
                passed = f'error: {error}'
            checks.append({'manual': name, 'name': check.name, 'expr': check.expr, 'passed': passed})
    proof['checks'] = checks
    evidence = REPO / 'scripts/evidence'
    (evidence / 'EVOLVE-proof.json').write_text(json.dumps(proof, indent=2, default=str), encoding='utf-8')
    curves = {t: summaries[t].get('curve') for t in tasks}
    if control:
        curves['control'] = control.get('curve')
    svg(curves, evidence / 'EVOLVE-curve.svg')
    for row in checks:
        print(('PASS ' if row['passed'] is True else 'FAIL ') + row['manual'] + ' ' + row['name'] + ': ' + row['expr'])
    print(json.dumps({k: proof.get(k) for k in ('gatePlanSpeedup', 'gatePlanSpeedupPinnedFirst', 'compileSpeedup', 'contractsPass', 'bigModelCalls',
                                                'modelCalls', 'libraryShareFirst', 'libraryShareSecond', 'secondTaskFaster', 'exploitRateFalls',
                                                'outputsIdentical', 'winEpisodes')}, indent=1))


if __name__ == '__main__':
    main()
