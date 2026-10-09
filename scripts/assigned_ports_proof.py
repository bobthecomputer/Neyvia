"""Evidence: explicitly assigned port blocks and scratch roots (grant_agent.assigned_ports).

Exercises the helper and the real port gates of the 3D harness (laya3d_harness.owned_pair), the
UI-fix render (laya_ui_fix.render_ports) and the LAYA glance gate (laya_glance_gate.request_ports),
then evaluates manuals/cl/assigned-ports.cl. No port is bound and no editor or browser starts.

Usage: python scripts/assigned_ports_proof.py [--scratch-root R] -> scripts/evidence/PORTS-assigned.json
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
KEYS = ('NEYVIA_ASSIGNED_PORTS', 'NEYVIA_ASSIGNED_PORTS_OWNER', 'NEYVIA_SCRATCH_ROOT')


def refused(call):
    """The refusal message, or None when the call was accepted."""
    try:
        call()
    except ValueError as exc:
        return str(exc)
    return None


def with_env(values, call):
    saved = {k: os.environ.get(k) for k in KEYS}
    try:
        for k in KEYS:
            os.environ.pop(k, None)
        os.environ.update(values)
        return call()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def gates():
    web, ws = os.environ.get('NEYVIA_WEB_PORT'), os.environ.get('NEYVIA_GAMEDEV_WS_PORT')
    import laya3d_harness  # its import sets default bridge ports in this process; restored below
    for key, value in (('NEYVIA_WEB_PORT', web), ('NEYVIA_GAMEDEV_WS_PORT', ws)):
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    from grant_agent.laya_glance_gate import request_ports
    try:  # the UI-fix adapter exists on track/laya-core, not on branches cut before it
        from grant_agent.laya_ui_fix import render_ports
        render = lambda ports: render_ports({'ports': ports})
    except ImportError:
        render = None
    return laya3d_harness.owned_pair, render, lambda ports: request_ports({'assignedPorts': ports, 'ports': ports})  # P22 key; older branches read 'ports'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    from grant_agent import assigned_ports as A
    A.add_arguments(parser)
    args = parser.parse_args()
    A.apply(args, 'CORE')
    harness, render_gate, glance = gates()
    render = render_gate or (lambda ports: 'absent')  # rows read 'absent' when the UI-fix adapter is not on this branch
    seen = (lambda value, expected: value == expected or (render_gate is None and value == 'absent'))
    rows = {}
    rows['defaults'] = with_env({}, lambda: {
        'harnessDefault': harness(None), 'harness49105': harness(49105), 'harness49171': refused(lambda: harness(49171)),
        'render49114': render([49114, 49115]), 'render49177': refused(lambda: render([49177, 49178])),
        'glance48871': list(glance([48871, 48872])), 'glance49173': refused(lambda: glance([49173, 49174])),
        'evidence': str(A.output('scripts/evidence/x.json')), 'state': str(A.state('laya3d/run'))})
    rows['custom'] = {'block': str(A.assigned_block('49171-49179', 'CORE')), 'pairs': A.parse_block('49171-49179').pairs()}
    rows['overlap'] = {'anim': refused(lambda: A.assigned_block('49151-49159', 'CORE')),
                       'video': refused(lambda: A.assigned_block('49165-49175', 'CORE')),
                       'coreViaEnvWithoutOwner': with_env({'NEYVIA_ASSIGNED_PORTS': '49111-49119'}, lambda: refused(A.assigned_block))}
    rows['own'] = {'core': str(A.assigned_block('49114-49117', 'CORE')), 'anim': str(A.assigned_block('49151-49157', 'ANIM'))}
    rows['malformed'] = {t: refused(lambda t=t: A.parse_block(t)) for t in ('49179-49171', '49171', 'abc', '49171-49171')}
    assigned = {'NEYVIA_ASSIGNED_PORTS': '49171-49179', 'NEYVIA_ASSIGNED_PORTS_OWNER': 'CORE'}
    rows['assigned'] = with_env(assigned, lambda: {
        'harnessDefault': harness(None), 'harness49177': harness(49177),
        'harness49105': refused(lambda: harness(49105)), 'harness49179': refused(lambda: harness(49179)),
        'render49177': render([49177, 49178]), 'render49114': refused(lambda: render([49114, 49115])),
        'glance49173': list(glance([49173, 49174])), 'glance49116': refused(lambda: glance([49116, 49117]))})
    probe = (Path(tempfile.gettempdir()) / 'ports-proof-scratch').resolve()
    rows['scratch'] = with_env({'NEYVIA_SCRATCH_ROOT': str(probe)}, lambda: {
        'evidence': str(A.output('scripts/evidence/ANIM-summary.json')), 'manual': str(A.output('manuals/cl/laya-anim-exploits.cl')),
        'readableFallback': str(A.readable('manuals/cl/laya-3d.cl')), 'state': str(A.state('laya3d/run')),
        'under': str(A.under('laya-anim', 'D:/NeyviaRuns/laya-anim'))})
    d, c, a, s = rows['defaults'], rows['custom'], rows['assigned'], rows['scratch']
    proof = {
        'defaultsUnchanged': (d['harnessDefault'] == 49101 and d['harness49105'] == 49105 and bool(d['harness49171'])
                              and seen(d['render49114'], [49114, 49115]) and (render_gate is None or bool(d['render49177']))
                              and d['glance48871'] == [48871, 48872] and bool(d['glance49173'])
                              and d['evidence'] == str(ROOT / 'scripts/evidence/x.json')
                              and d['state'] == str(ROOT / '.agent_control/laya3d/run')),
        'customAccepted': (c['block'] == '49171-49179' and c['pairs'][0] == (49171, 49172) and len(c['pairs']) == 4
                           and a['harnessDefault'] == 49171 and a['harness49177'] == 49177
                           and seen(a['render49177'], [49177, 49178]) and a['glance49173'] == [49173, 49174]),
        'overlapRefused': all(rows['overlap'].values()),
        'ownSubBlockAccepted': rows['own'] == {'core': '49114-49117', 'anim': '49151-49157'},
        'malformedRefused': all(rows['malformed'].values()),
        'outsideRefused': all(bool(a[k]) for k in ('harness49105', 'harness49179', 'glance49116')) and (render_gate is None or bool(a['render49114'])),
        'scratchRedirected': (s['evidence'].startswith(str(probe)) and s['manual'].startswith(str(probe))
                              and s['readableFallback'] == str(ROOT / 'manuals/cl/laya-3d.cl')
                              and s['state'] == str(probe / '.agent_control/laya3d/run') and s['under'].startswith(str(probe))),
    }
    from grant_agent.cl_skill import _parse_skill, _Expr
    skill = _parse_skill(ROOT / 'manuals/cl/assigned-ports.cl')
    proof['checks'] = [{'name': x.name, 'expr': x.expr, 'passed': bool(_Expr(x.expr, {'proof': proof}, {}).run())} for x in skill.checks]
    report = {'schema': 'neyvia.assigned-ports.v1', 'command': 'python scripts/assigned_ports_proof.py', 'rows': rows, 'proof': proof,
              'uiFixRenderGate': render_gate is not None,
              'passed': bool(proof['checks']) and all(x['passed'] for x in proof['checks'])}
    path = A.output('scripts/evidence/PORTS-assigned.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1, default=str) + '\n', encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'checks': {x['name']: x['passed'] for x in proof['checks']}}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
