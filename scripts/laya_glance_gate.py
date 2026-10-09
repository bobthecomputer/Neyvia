"""LAYA glance command for the P22 release gate.

gate.py: --laya-command <python> scripts/laya_glance_gate.py   (request JSON path appended)
Self-check: python scripts/laya_glance_gate.py --self-check [--build <built web dir>]

Prints exactly one JSON object to stdout; diagnostics go to stderr. Exit 0 only when every
(surface, variant) row is an admitted "looks fine". Run state, screenshots and receipt live beside the request (the gate folder).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def self_check(build, budget):
    from grant_agent.laya_glance_gate import VARIANTS, run
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO, capture_output=True, text=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout.strip()
    # Mirror the gate: its request, build and run state sit in one folder on the local SSD.
    from grant_agent.assigned_ports import state
    root = state('laya-gate') / ('self-check-' + time.strftime('%Y%m%d-%H%M%S'))
    root.mkdir(parents=True, exist_ok=True)
    if Path(build).resolve().drive.upper() != root.drive.upper():
        shutil.copytree(build, root / 'build')
        build = root / 'build'
    request = root / 'laya-request.json'
    request.write_text(json.dumps({'commit': commit, 'sourceBindings': {}, 'renderReceipt': None, 'build': str(build),
                                   'changedSurfaces': ['web/src/neyvia/next/NxPdfApp.jsx', 'web/src/neyvia/next/nxShellLauncher.js'],
                                   'variants': list(VARIANTS)}), encoding='utf-8')
    result = run(request, budget=budget, run_root=root / 'run')
    from grant_agent.assigned_ports import output
    evidence = output('scripts/evidence/LAYAG-gate-run.json'); evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps({'schema': 'neyvia.laya-glance-gate.self-check.v1', 'request': str(request),
                                    'command': [sys.executable, str(Path(__file__).resolve()), str(request)],
                                    **result}, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('request', nargs='?', type=Path)
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--build', type=Path, default=Path(r'D:\NeyviaRuns\laya-gate\build-cae0b12\dist'))
    parser.add_argument('--budget', type=float, default=150.0, help='Seconds before unrendered states become uncertain')
    from grant_agent.assigned_ports import add_arguments, apply
    add_arguments(parser)  # --port-block: the request's assignedPorts must lie inside it
    args = parser.parse_args()
    stdout, sys.stdout = sys.stdout, sys.stderr  # keep stdout for the single JSON answer
    commit = None
    try:
        apply(args, 'CORE')
        if args.self_check:
            result = self_check(args.build, args.budget)
        else:
            if not args.request:
                parser.error('request JSON path required')
            commit = json.loads(args.request.read_text(encoding='utf-8')).get('commit')
            from grant_agent.laya_glance_gate import run
            result = run(args.request, budget=args.budget)
    except Exception as exc:
        traceback.print_exc()
        result = {'commit': commit, 'observations': [], 'error': f'{type(exc).__name__}: {exc}'}
    stdout.write(json.dumps(result) + '\n')
    stdout.flush()
    rows = result.get('observations') or []
    ok = bool(rows) and all(r.get('verdict') == 'looks fine' and r.get('admitted') is True for r in rows)
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
