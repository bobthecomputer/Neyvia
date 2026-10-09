"""Evidence script: run the plan-25 evolving engine on the P22 gate and verify the result.

  python scripts/evolve_run.py --run <id>            # gate-plan, then cl-compile, then the control
  python scripts/evolve_run.py --run <id> --persist  # also write exploit predicates and learned moves into the CL files

The gate is measured in a private sparse clone of a pinned track/p22 commit inside this
worktree's ignored .agent_control/evolve (SSD, same disk class as the real gate). Large
run outputs go to D:/NeyviaRuns/EVOLVE/<run>. Results are a patch plus receipts for
P22/REL; track/p22 is never edited.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))

from grant_agent import evolve_engine as ev  # noqa: E402
from grant_agent.evolve_gate import GateTarget, make_rename_tree, git  # noqa: E402

P22_COMMIT = 'fd3c234e7660f95870aa66ecaf9e7fae612cadd2'
WORK = REPO / '.agent_control/evolve'
FAST_CONTRACTS = ['p22.impact', 'p22.uncovered', 'p22.permission-validation', 'p22.runtime-budget', 'p22.release-parsing',
                  'p22.workspace-selection', 'p22.codex-threads', 'p22.oauth-owner', 'p22.plan-hold', 'p22.coverage-model',
                  'p22.module-discovery']


COMMITS = {'gate-plan': ('p22-tree', P22_COMMIT), 'cl-compile': ('p22-tree', P22_COMMIT),
           'gate-plan-latest': ('p22-new', '8af3037d8eeaec26289e90d65da6ad2db154020e')}


def ensure_tree(task='gate-plan'):
    name, commit = COMMITS[task]
    tree = WORK / name
    if not (tree / '.git').exists():
        tree.parent.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(['git', 'clone', '-q', '--shared', '--no-checkout', str(Path('C:/Users/user/Projects/Neyvia-next')), str(tree)])
        subprocess.check_call(['git', 'sparse-checkout', 'init', '--no-cone'], cwd=tree)
        (tree / '.git/info/sparse-checkout').write_text('/*\n!/proof/\n!/docs/\n!/scripts/evidence/\n', encoding='utf-8')
        subprocess.check_call(['git', 'checkout', '-q', '--detach', commit], cwd=tree)
    if git(tree, 'rev-parse', 'HEAD') != commit or git(tree, 'status', '--porcelain', '--untracked-files=no'):
        raise SystemExit('Measurement tree is not the clean pinned p22 commit: ' + str(tree))
    return tree, make_rename_tree(tree, WORK / (name + '-rename'), commit=commit)


class Log:
    def __init__(self, path):
        self.path = path

    def __call__(self, message):
        line = time.strftime('%H:%M:%S ') + message
        print(line, flush=True)
        with self.path.open('a', encoding='utf-8') as handle:
            handle.write(line + '\n')


def direct_speedup(target, base, final, pairs=5):
    """Final verification: interleaved baseline vs final on the train cases (wall and process CPU)."""
    a, b, ca, cb = [], [], [], []
    for index in range(pairs):
        order = [('a', base), ('b', final)] if index % 2 == 0 else [('b', final), ('a', base)]
        for label, files in order:
            wall = cpu = 0
            for check in target.train_checks():
                result = target.measure(files, target.case(check))
                wall += result['wall']
                cpu += result.get('cpuSeconds') or 0
            (a if label == 'a' else b).append(wall)
            (ca if label == 'a' else cb).append(cpu)
    return {'baseline': a, 'final': b, 'baselineCpu': ca, 'finalCpu': cb,
            'speedup': round(statistics.median(a) / statistics.median(b), 4),
            'speedupMin': round(min(a) / min(b), 4), 'cpuSpeedup': round(statistics.median(ca) / statistics.median(cb), 4),
            'pairs': [round(x / y, 4) for x, y in zip(a, b)]}


def verify_outputs(target, files, reference):
    """Every train, held-out and perturbation check of a file set against the baseline reference."""
    rows = {check: target.check(files, check).get('outputSha256') for check in target.all_checks()}
    return {'identical': all(rows[c] == reference.get(c) for c in rows), 'differs': sorted(c for c in rows if rows[c] != reference.get(c))}


def lineage_from_run(run_dir, task, base):
    """Rebuild (step, move, parent files, child files) of a finished task from its receipts and candidates."""
    files_by_id = {}
    for overlay in (run_dir / task / 'candidates').glob('*/overlay.json'):
        mapping = json.loads(overlay.read_text(encoding='utf-8'))
        files = {rel: Path(path).read_bytes().decode('utf-8') for rel, path in mapping.items()}
        files_by_id[ev.sha(ev.canonical(files))[:12]] = files
    summary = json.loads((run_dir / f'{task}-summary.json').read_text(encoding='utf-8'))
    rows = {}
    for line in (run_dir / task / 'receipts.jsonl').read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        if row.get('kind') == 'evaluation':
            rows[row['id']] = row
    chain = summary['final']['ancestry'] + [summary['final']['id']]
    out = []
    for parent, child in zip(chain, chain[1:]):
        out.append((child, rows[child]['origin'].get('move'), base if parent == 'baseline' else files_by_id[parent], files_by_id[child]))
    return out, summary


def finish_task(task, target, engine_reference, lineage, summary, out, log, memory, learned):
    """Ablate the accepted lineage, verify the pruned final, retire moves whose step was pruned."""
    final, ablation = ev.ablate(target, target.baseline, lineage, log=log)
    summary['ablation'] = ablation
    summary['finalAfterAblation'] = {'steps': [r['label'] for r in ablation if r['kept']], 'pruned': [r['label'] for r in ablation if not r['kept']]}
    summary['finalVerification'] = verify_outputs(target, final, engine_reference)
    late = []
    if not summary['finalVerification']['identical']:
        # A later, stronger check disagrees: find the step that breaks it and remove that step.
        differs = summary['finalVerification']['differs']
        log(f'[{task}] final differs on {differs}; locating the breaking step')
        for step, move, parent, child in reversed(lineage):
            if step not in {r['step'] for r in ablation if r['kept']}:
                continue
            candidate = ev.revert_step(final, parent, child)
            if candidate is None:
                continue
            check = verify_outputs(target, candidate, engine_reference)
            if check['identical']:
                late.append({'step': step, 'move': move, 'failing': differs})
                memory.store.learn(ev.EPISODE_DOMAIN, memory.features(move or '', '', 'python-speed'), 'invalid',
                                   f'evolve-late:{task}:{step}', evidence={'failing': differs})
                log(f'[{task}] step {step} ({move}) breaks {differs}: removed')
                final, summary['finalVerification'] = candidate, check
                break
        else:
            log(f'[{task}] no single step explains the difference; falling back to the baseline')
            final, summary['finalVerification'] = dict(target.baseline), verify_outputs(target, target.baseline, engine_reference)
    summary['lateFindings'] = late
    for row in late:
        for check in row['failing']:
            identity = f'exploit-{check}'
            if any(p['id'] == identity for p in summary.get('exploitPredicates', [])):
                continue
            summary.setdefault('exploitPredicates', []).append({
                'id': identity, 'severity': 'error', 'evidence': ['measurements.identical', 'measurements.status'],
                'condition': {'all': [{'field': 'attributes.check', 'op': 'eq', 'value': check},
                                      {'any': [{'field': 'measurements.identical', 'op': 'eq', 'value': False},
                                               {'field': 'measurements.nondeterministic', 'op': 'eq', 'value': True}]}]},
                'fix': {'action': 'evolve.reject', 'arguments': {}},
                'means': f"Found after the search by the stronger final check: step {row['step']} ({row['move']}) passed every warm check but changed {check}"})
    pruned = {r['step'] for r in ablation if not r['kept']} | {row['step'] for row in late}
    retired = []
    rows = json.loads(learned.read_text(encoding='utf-8')) if learned.exists() else []
    for move in rows:
        if move.get('evidence', {}).get('candidate') in pruned:
            memory.store.forget('evolve-move:' + move['id'])
            retired.append(move['id'])
    if retired:
        learned.write_text(json.dumps([m for m in rows if m['id'] not in retired], indent=2), encoding='utf-8')
        log(f'[{task}] learned moves retired by ablation: {retired}')
    summary['retiredByAblation'] = retired
    for step, move, parent, child in lineage:
        if step in pruned:
            memory.store.learn(ev.EPISODE_DOMAIN, memory.features(move or '', '', 'python-speed'), 'loss',
                               f'evolve-ablation:{task}:{step}', evidence={'ablation': True})
    (out / f'{task}-final.json').write_text(json.dumps(final), encoding='utf-8')
    (out / f'{task}.patch').write_bytes(ev.patch(target.baseline, final).encode('utf-8'))
    log(f'[{task}] final verification (direct speed-up, cold)')
    summary['direct'] = direct_speedup(target, target.baseline, final)
    summary['cold'] = cold_speedup(target, target.baseline, final)
    summary['patch'] = str(out / f'{task}.patch')
    summary['patchLines'] = ev.footprint(target.baseline, final)
    (out / f'{task}-summary.json').write_text(json.dumps(summary, indent=2, default=str), encoding='utf-8')
    d = summary['direct']
    log(f'[{task}] direct speed-up {d["speedup"]}x (min {d["speedupMin"]}x, cpu {d["cpuSpeedup"]}x), cold {summary["cold"]}')
    return final


def cold_speedup(target, base, final, pairs=2):
    case = target.spec.get('cold')
    if not case:
        return None
    a, b = [], []
    for index in range(pairs):
        order = [('a', base), ('b', final)] if index % 2 == 0 else [('b', final), ('a', base)]
        for label, files in order:
            target.restore(target.tree, {})
            (a if label == 'a' else b).append(target.run(files, case)['wall'])
    target.restore(target.tree, {})
    return {'baseline': a, 'final': b, 'speedup': round(statistics.median(a) / statistics.median(b), 4)}


def contracts(target, files, scratch):
    job = scratch / 'fast-contracts.json'
    sandbox = Path('D:/NeyviaRuns/EVOLVE/p22-sandbox')
    job.write_text(json.dumps({'area': 'fast-contracts', 'contracts': FAST_CONTRACTS,
                               'stateRoot': str(sandbox / 'state' / scratch.name)}), encoding='utf-8')
    overlay = target.materialise(files)
    out = scratch / 'contracts-result.json'
    env = dict(os.environ, NEYVIA_GATE_ASSIGNED_PORTS='49081-49089', PYTHONIOENCODING='utf-8',
               EVOLVE_REDIRECT="Path('D:/NeyviaRuns/P22')=>Path('D:/NeyviaRuns/EVOLVE/p22-sandbox')")
    env.pop('PYTHONPATH', None)
    started = time.time()
    subprocess.run([ev.os.environ.get('NEYVIA_SYSTEM_PYTHON') or sys.executable, str(REPO / 'scripts/evolve_gate_runner.py'), '--tree', str(target.tree),
                    '--overlay', str(overlay), '--task', 'worker', '--job', str(job), '--root', str(scratch / 'contracts-root'), '--out', str(out)],
                   env=env, capture_output=True, text=True, timeout=1800, creationflags=ev.NO_WINDOW)
    result = json.loads(out.read_text(encoding='utf-8'))
    witnessed = (result.get('output') or {}).get('witnessed', [])
    return {'ok': (result.get('output') or {}).get('ok') is True and set(FAST_CONTRACTS) <= set(witnessed),
            'witnessed': witnessed, 'seconds': round(time.time() - started, 1), 'status': result.get('status'), 'error': result.get('error')}


def model_look(models, diff, task):
    prompt = (f"Review this optimisation patch for the P22 release gate ({task}). The engine already proved byte-identical outputs on "
              f"train, held-out and perturbation checks (edited sources, new proofs, renames, cold caches, repeats). Does the patch "
              f"preserve behaviour for every input? List concrete risks only.\n\n{diff[:30000]}")
    answer, call = models.ask('luna', prompt, ev.REVIEW_SCHEMA, label='review-' + task)
    return {'answer': answer, 'call': {k: call.get(k) for k in ('seconds', 'usage', 'ok', 'model')}}


def compile_constants(target):
    result = target.measure(target.baseline, target.case('check'))
    return {'moduleCheck': (result.get('output') or {}).get('receipt', {}).get('modules')}


def persist(summaries, learned_path):
    """Hardened judge and learned moves become part of the CL skill files (data)."""
    spec = REPO / 'manuals/cl/evolve.cl'
    text = spec.read_text(encoding='utf-8')
    lines = []
    for summary in summaries:
        for predicate in summary.get('exploitPredicates', []):
            line = '-- @predicate ' + json.dumps(predicate, separators=(',', ':'))
            if f'"id":"{predicate["id"]}"' not in text and line not in lines:
                lines.append(line)
    if lines:
        anchor = 'C evolve.verify identical:'
        text = text.replace(anchor, '\n'.join(lines) + '\n' + anchor, 1)
        spec.write_bytes(text.encode('utf-8'))
    moves_file = REPO / 'manuals/cl/evolve-moves.cl'
    moves_text = moves_file.read_text(encoding='utf-8')
    added = []
    for move in json.loads(learned_path.read_text(encoding='utf-8')) if learned_path.exists() else []:
        if f'"id":"{move["id"]}"' in moves_text:
            continue
        row = {k: move[k] for k in ('id', 'family', 'transform', 'applies_when', 'match', 'cl', 'origin', 'evidence')}
        added.append('-- @move ' + json.dumps(row, separators=(',', ':')))
    if added:
        anchor = 'C evolve.moves seeded:'
        moves_file.write_bytes(moves_text.replace(anchor, '-- Learned moves (written by evolve_run --persist from winning model ideas).\n' + '\n'.join(added) + '\n' + anchor, 1).encode('utf-8'))
    return {'predicates': len(lines), 'moves': len(added)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--run', required=True)
    parser.add_argument('--tasks', nargs='+', default=['gate-plan', 'cl-compile'])
    parser.add_argument('--control-task', help='run this task again with an empty episode store and no learned moves')
    parser.add_argument('--persist', action='store_true')
    parser.add_argument('--luna-cap', type=int, default=60)
    parser.add_argument('--sol-cap', type=int, default=10)
    parser.add_argument('--resume-from', help='earlier run id whose finished task searches are reused (ablation and verification re-run)')
    args = parser.parse_args()
    os.environ['NEYVIA_EVOLVE_RUN'] = args.run
    out = Path('D:/NeyviaRuns/EVOLVE') / args.run
    out.mkdir(parents=True, exist_ok=True)
    log = Log(out / 'run.log')
    tree, rename_tree = ensure_tree(args.tasks[0])
    state = WORK / 'state'
    learned = state / 'learned-moves.json'
    models = ev.Models(state, {'luna': args.luna_cap, 'sol': args.sol_cap})
    memory = ev.Memory(state)
    specs, _ = ev.load_spec()
    log(f'run {args.run}: tree {tree} @ {P22_COMMIT[:12]}; episodes at {state}; outputs at {out}')
    summaries, finals, engines = {}, {}, {}
    for task in args.tasks:
        spec = specs[task]
        tree, rename_tree = ensure_tree(task)
        target = GateTarget(task, tree, out / task, rename_tree=rename_tree)
        previous = Path('D:/NeyviaRuns/EVOLVE') / args.resume_from if args.resume_from else None
        if previous and (previous / f'{task}-summary.json').exists():
            # The search for this task already ran in an earlier process; re-run only the later judges.
            log(f'[{task}] resuming from {previous}: ablation and final verification only')
            lineage, summary = lineage_from_run(previous, task, target.baseline)
            reference = {check: target.check(target.baseline, check).get('outputSha256') for check in target.all_checks()}
            summary['resumedFrom'] = str(previous)
            finals[task] = finish_task(task, target, reference, lineage, summary, out, log, memory, learned)
            summaries[task] = summary
            continue
        engine = ev.Engine(target, state=state, runs=out / task, models=models, memory=memory, spec=spec, learned_moves=learned, log=log)
        constants = compile_constants(target) if task == 'cl-compile' else None
        budget = spec['budget']
        summary = engine.run(generations=budget['generations'], per_generation=budget['perGeneration'],
                             luna_per_generation=budget['lunaPerGeneration'], max_seconds=budget['maxSeconds'], adversary_constants=constants)
        engines[task] = engine
        (out / f'{task}-summary.json').write_text(json.dumps(summary, indent=2, default=str), encoding='utf-8')
        finals[task] = finish_task(task, target, engine.reference, engine.lineage(), summary, out, log, memory, learned)
        summaries[task] = summary
    if args.control_task:
        # Same task, same engine code, empty episode store and no learned moves: what the earlier tasks taught.
        task = args.control_task
        control_state = out / 'control-state'
        shutil.rmtree(control_state, ignore_errors=True)
        control_memory = ev.Memory(control_state)
        tree, rename_tree = ensure_tree(task)
        target = GateTarget(task, tree, out / 'control', rename_tree=rename_tree)
        spec = specs[task]
        engine = ev.Engine(target, state=control_state, runs=out / 'control', models=models, memory=control_memory, spec=spec,
                           learned_moves=control_state / 'learned-moves.json', log=log)
        budget = spec['budget']
        summaries['control'] = engine.run(generations=budget['generations'], per_generation=budget['perGeneration'],
                                          luna_per_generation=budget['lunaPerGeneration'], max_seconds=budget['maxSeconds'], adversary=False)
        summaries['control']['controlTask'] = task
        (out / 'control-summary.json').write_text(json.dumps(summaries['control'], indent=2, default=str), encoding='utf-8')
    # The gate's own contracts with both final patches together, and one model look.
    gate_task = 'gate-plan-latest' if 'gate-plan-latest' in finals else 'gate-plan'
    combined = {**finals.get(gate_task, {}), **(finals.get('cl-compile', {}) if gate_task == 'gate-plan' else {})}
    tree, rename_tree = ensure_tree(gate_task)
    any_target = GateTarget(gate_task, tree, out / 'verify', rename_tree=rename_tree)
    verify = {'contracts': contracts(any_target, combined, out / 'verify') if combined else None}
    combined_base = {rel: (tree / rel).read_text(encoding='utf-8') for rel in combined}
    diff = ev.patch(combined_base, combined)
    (out / 'gate-evolved.patch').write_bytes(diff.encode('utf-8'))
    try:
        verify['modelLook'] = model_look(models, diff, 'gate-plan + cl-compile') if diff else None
    except ev.ModelBudgetError as error:
        verify['modelLook'] = {'error': str(error)}
    log(f'contracts with combined patch: {verify["contracts"]}')
    summaries['verify'] = verify
    summaries['modelCalls'] = dict(models.used)
    if args.persist:
        summaries['persisted'] = persist([s for k, s in summaries.items() if k in args.tasks], learned)
    (out / 'summary.json').write_text(json.dumps(summaries, indent=2, default=str), encoding='utf-8')
    log('done: ' + str(out / 'summary.json'))


if __name__ == '__main__':
    main()
