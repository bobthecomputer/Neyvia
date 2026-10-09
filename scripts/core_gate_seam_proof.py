"""Evidence: the LAYA glance answers plan 22's release-gate request as a command.

Writes requests with exactly the keys P22's contract_gate sends (commit, sourceBindings,
changedSurfaces, renderReceipt, build, assignedPorts, observerPorts, variants), runs
    python scripts/laya_glance_gate.py --budget <s> <request.json>
as the gate does, and applies the gate's own acceptance rule (matching commit; every
surface x variant row "looks fine", admitted, with a screenshot hash and a reason).

Builds: the pre-fix commit 9589de605 (expected: not admitted, broken rows named) and the
same tree after LAYA's kept fixes from scripts/core_ui_fix_proof.py (CORE-ui-fix.json).
Renders are private (admitted headless Obscura) on CORE ports 49116/49117.

Usage: python scripts/core_gate_seam_proof.py -> scripts/evidence/CORE-gate-seam.json
Assigned allocation (grant_agent.assigned_ports): --port-block B glances on B's second pair (observer
ports = first pair); --scratch-root R reads R's UI-fix tree/evidence and writes R/CORE/gate and
R/scripts/evidence/CORE-gate-seam.json. The glance subprocess inherits the allocation.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
RUNS = Path('D:/NeyviaRuns/CORE/gate')
TREE = Path('D:/NeyviaRuns/CORE/ui-fix/src-9589de605')
COMMIT = '9589de60590d82ab98546d589a91ab2381fbb47c'
SURFACES = ['web/src/neyvia/next/NxPdfApp.jsx', 'web/src/neyvia/next/nxShell.css']
VARIANTS = ['dark-desktop', 'light-desktop', 'dark-phone', 'light-phone']


def accept(verdict, commit):
    """contract_gate.run's acceptance rule for the LAYA step, verbatim in meaning."""
    expected = {(s, v) for s in SURFACES for v in VARIANTS}
    admitted = {(r['surface'], r['variant']) for r in verdict.get('observations', [])
                if r.get('verdict') == 'looks fine' and r.get('admitted') is True and r.get('screenshotSha256') and r.get('reason')}
    return verdict.get('commit') == commit and admitted == expected


BUDGET = 240
ASSIGNED, OBSERVER = [49116, 49117], [49114, 49115]
UI_RUNS = Path('D:/NeyviaRuns/CORE/ui-fix')


def glance(label, build):
    folder = RUNS / label
    folder.mkdir(parents=True, exist_ok=True)
    request = folder / 'laya-request.json'
    request.write_text(json.dumps({'commit': COMMIT, 'sourceBindings': {}, 'changedSurfaces': SURFACES,
                                   'renderReceipt': str(folder / 'render/receipt.json'), 'build': str(build),
                                   'assignedPorts': ASSIGNED, 'observerPorts': OBSERVER, 'variants': VARIANTS}),
                       encoding='utf-8')
    command = [sys.executable, str(ROOT / 'scripts/laya_glance_gate.py'), '--budget', str(BUDGET), str(request)]
    started = time.perf_counter()
    done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=600,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    seconds = round(time.perf_counter() - started, 1)
    (folder / 'stderr.log').write_text(done.stderr, encoding='utf-8')
    try:
        verdict = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {'command': command, 'exit': done.returncode, 'seconds': seconds, 'error': 'invalid response', 'stdout': done.stdout[-2000:]}
    rows = [{k: r.get(k) for k in ('surface', 'variant', 'verdict', 'admitted', 'screenshotSha256', 'reason')}
            | {'bugs': sorted({(b['type'], (b.get('fix') or {}).get('action')) for b in r.get('bugs') or []})}
            for r in verdict.get('observations', [])]
    return {'command': command, 'exit': done.returncode, 'seconds': seconds, 'accepted': accept(verdict, COMMIT),
            'commitEchoed': verdict.get('commit') == COMMIT, 'rows': rows, 'receipt': verdict.get('receipt'),
            'verdictCounts': {v: sum(r['verdict'] == v for r in rows) for v in ('looks fine', 'looks broken', 'uncertain')}}


def fixed_build():
    """Re-apply every fix LAYA kept in the UI-fix proof to the pristine tree, build, restore."""
    from grant_agent.laya_ui_fix import build, checkpoint, digest, replay, restore
    from grant_agent.assigned_ports import readable
    evidence = json.loads(readable('scripts/evidence/CORE-ui-fix.json').read_text(encoding='utf-8'))
    source = {'tree': str(TREE), 'state': 'home', 'runs': str(UI_RUNS)}
    pristine = checkpoint(source)
    try:
        applied = replay(source, [s['fix'] for case in evidence['cases'].values() for call in case.get('calls', [])
                                  if call['role'] == 'named fix' for s in call['steps'] if s['status'] == 'kept'])
        out, _ = build(source, digest(TREE))
        return out, applied
    finally:
        restore(source, pristine)


def main():
    global BUDGET, RUNS, TREE, UI_RUNS, ASSIGNED, OBSERVER
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--budget', type=int, default=BUDGET, help='seconds per glance (P22 passes its remaining deadline)')
    from grant_agent.assigned_ports import add_arguments, apply, output, under
    add_arguments(parser)
    args = parser.parse_args()
    BUDGET = args.budget
    block, scratch = apply(args, 'CORE')
    RUNS, TREE, UI_RUNS = under('CORE/gate', RUNS), under('CORE/ui-fix/src-9589de605', TREE), under('CORE/ui-fix', UI_RUNS)
    if block:
        OBSERVER, ASSIGNED = list(block.pair(0)), list(block.pair(1))
    RUNS.mkdir(parents=True, exist_ok=True)
    from grant_agent.laya_ui_fix import digest
    pristine_build = UI_RUNS / 'builds' / digest(TREE)[:16]
    report = {'schema': 'neyvia.core-gate-seam.v1', 'command': 'python scripts/core_gate_seam_proof.py --budget ' + str(BUDGET),
              'contract': 'scripts/evidence/P22-gate.md on track/p22 (request keys from contract_gate.run)',
              'before': glance('before-9589de605', pristine_build)}
    after_build, applied = fixed_build()
    report['fixesReplayed'] = applied
    report['after'] = glance('after-laya-fixes', after_build)
    from grant_agent.cl_skill import _parse_skill, _Expr
    summary = {'answersContract': all(report[k].get('commitEchoed') and len(report[k].get('rows', [])) == len(SURFACES) * len(VARIANTS)
                                      for k in ('before', 'after')),
               'preFixAdmitted': report['before'].get('accepted'),
               'preFixBrokenRows': sum(r['verdict'] == 'looks broken' and any(action for _, action in r['bugs'])
                                       for r in report['before'].get('rows', [])),
               'afterAdmitted': report['after'].get('accepted')}
    skill = _parse_skill(ROOT / 'manuals/cl/laya-ui-fix.cl')  # CL owns acceptance (gate.verify checks)
    report['proof'] = {**summary, 'checks': [{'name': c.name, 'expr': c.expr, 'passed': bool(_Expr(c.expr, {'proof': summary}, {}).run())}
                                             for c in skill.checks if c.action == 'gate.verify']}
    report['checks'] = {c['name']: c['passed'] for c in report['proof']['checks']}
    report['passed'] = all(report['checks'].values())
    report['allocation'] = {'assignedPorts': ASSIGNED, 'observerPorts': OBSERVER, 'portBlock': str(block) if block else None,
                            'scratchRoot': str(scratch) if scratch else None, 'runs': str(RUNS), 'tree': str(TREE)}
    output('scripts/evidence/CORE-gate-seam.json').parent.mkdir(parents=True, exist_ok=True)
    output('scripts/evidence/CORE-gate-seam.json').write_text(json.dumps(report, indent=1, default=str) + '\n', encoding='utf-8')
    print(json.dumps({'passed': report['passed'], **report['checks'], 'before': report['before'].get('verdictCounts'),
                      'after': report['after'].get('verdictCounts'), 'afterAccepted': report['after'].get('accepted')}))


if __name__ == '__main__':
    main()
