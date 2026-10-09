"""Replay unchanged FIXCL2 functional assertions against frozen FIXCL3 sources.

Only literal receipt destinations and assigned-port constants are relocated in
memory. Original probe files and all FIXCL2 receipts remain untouched.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
WAVE = 'FIXCL3'
OUT = REPO / ('scripts/evidence/' + WAVE + '-regression')
PROBES = {
    'terminal': ('fixcl2_terminal_probe.py', False),
    'work': ('fixcl2_work_probe.py', True),
    'creative': ('fixcl2_creative_probe.py', False),
    'coordination': ('fixcl2_coordination_probe.py', True),
    'semantic': ('fixcl2_semantic_probe.py', False),
    'durable': ('fixcl2_durable_probe.py', True),
    'frontier-local': ('fixcl2_frontier_probe.py', True),
    'sidebar': ('fixcl2_sidebar_frontier_probe.py', True),
    'browser': ('fixcl2_browser_probe.py', False),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    paths = list((REPO / 'src/grant_agent').rglob('*.py'))
    paths += list((REPO / 'manuals').glob('*.manual.json'))
    paths += list((REPO / 'manuals/cl').glob('*.cl'))
    paths += [REPO / 'config/fixcl_manual_cache.json', REPO / 'config/neyvia_manuals.json']
    paths += [REPO / 'scripts' / entry[0] for entry in PROBES.values()]
    paths += [Path(__file__), REPO / 'scripts/fixcl_verify.py']
    return {path.relative_to(REPO).as_posix(): digest(path) for path in sorted(set(paths))}


def relocated_tree(name, port):
    script = REPO / 'scripts' / PROBES[name][0]
    original = script.read_bytes()
    tree = ast.parse(original, filename=str(script))
    legacy = {'terminal': 'terminal', 'creative': 'creative',
              'semantic': 'semantic', 'browser': 'browser'}.get(name)
    replacements = {}
    if legacy:
        replacements[f'scripts/evidence/FIXCL2-{legacy}.json'] = (
            f'scripts/evidence/{WAVE}-regression/{name}.json')
    if name == 'terminal':
        replacements[48822] = port
    elif name == 'coordination':
        replacements[48828] = port
    elif name == 'semantic':
        replacements[48829] = port
    elif name == 'browser':
        replacements.update({48825: 48827, 48826: 48828,
                             '48825,48826': '48827,48828,48829'})
    changes = []

    class Relocate(ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, (str, int)) and not isinstance(node.value, bool) and node.value in replacements:
                replacement = replacements[node.value]
                changes.append({'line': node.lineno, 'column': node.col_offset,
                                'original': node.value, 'replacement': replacement})
                return ast.copy_location(ast.Constant(replacement), node)
            return node

    tree = ast.fix_missing_locations(Relocate().visit(tree))
    return script, tree, {'originalSha256': hashlib.sha256(original).hexdigest(),
                          'relocatedAstSha256': hashlib.sha256(ast.dump(tree).encode()).hexdigest(),
                          'literalRelocations': changes}


def worker(name, port):
    script, tree, _ = relocated_tree(name, port)
    sys.path.insert(0, str(REPO / 'scripts'))
    sys.path.insert(0, str(REPO / 'src'))
    if name == 'browser':
        arguments = ['--engine-port', '48827', '--fixture-port', '48828']
    else:
        arguments = ['--port', str(port)]
    if PROBES[name][1]:
        arguments += ['--output', str(OUT / (name + '.json'))]
    sys.argv = [str(script), *arguments]
    namespace = {'__name__': '__main__', '__file__': str(script), '__package__': None}
    ipc = []
    if name == 'browser' and sys.platform == 'win32':
        # Preserve Windows asyncio's real socketpair, with an explicit owned
        # listener rather than its otherwise implicit ephemeral listener.
        def assigned_pair(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
            with socket.socket(family, type, proto) as listener:
                listener.bind(('127.0.0.1', 48829))
                listener.listen(1)
                client = socket.socket(family, type, proto)
                client.connect(listener.getsockname())
                server, _ = listener.accept()
                ipc.append({'listener': list(listener.getsockname()), 'mechanism': 'Windows asyncio socketpair'})
                return server, client
        socket.socketpair = assigned_pair
    try:
        exec(compile(tree, str(script), 'exec'), namespace)
    finally:
        if name == 'browser':
            (OUT / 'browser-ipc.json').write_text(json.dumps({'pairs': ipc}) + '\n', encoding='utf-8')


def main():
    global WAVE, OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', default=','.join(PROBES))
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--source-freeze', required=True,
                        help='Lead-provided source-freeze checkpoint, recorded verbatim')
    parser.add_argument('--worker', choices=PROBES)
    parser.add_argument('--wave', choices=['FIXCL3', 'FIXCL4', 'FIXCL5'], default='FIXCL3')
    args = parser.parse_args()
    WAVE = args.wave
    OUT = REPO / ('scripts/evidence/' + WAVE + '-regression')
    if args.port not in range(48821, 48830):
        parser.error('Explicit assigned port required')
    if args.worker:
        worker(args.worker, args.port)
        return 0
    names = args.only.split(',')
    if len(set(names)) != len(names) or any(name not in PROBES for name in names):
        parser.error('Use each named original probe at most once')
    OUT.mkdir(parents=True, exist_ok=True)
    scratch = REPO / '.agent_control/proofs' / (WAVE + '-regression-' + str(time.time_ns()))
    scratch.mkdir(parents=True)
    baseline = {path.name: digest(path) for path in (REPO / 'scripts/evidence').glob('FIXCL2*.json')}
    start = sources()
    aggregate_path = REPO / ('scripts/evidence/' + WAVE + '-regression.json')
    if aggregate_path.exists():
        aggregate = json.loads(aggregate_path.read_bytes())
        (scratch / 'previous-aggregate.json').write_bytes(aggregate_path.read_bytes())
    else:
        aggregate = {'schema': 'neyvia.' + WAVE + '.regression.v1', 'probes': {}}
    phase = {'sourceFreeze': args.source_freeze, 'sourceHashesAtStart': start,
             'baselineHashesAtStart': baseline, 'scratch': str(scratch), 'probes': names,
             'port': args.port}
    env = dict(os.environ)
    env.update(NEYVIA_TOOL_AUTO_UPDATE='0', FLUXIO_RUNTIME_AUTO_UPDATE='0',
               NEYVIA_COORDINATOR_AUTOSTART='0', FLUXIO_WATCHDOG_AUTOSTART='0',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
               PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
               NEYVIA_UI_BACKEND_URL=f'http://127.0.0.1:{args.port}')
    env.pop('NEYVIA_SIDEBAR_ASSET_BASE_URL', None)
    for name in names:
        path = OUT / (name + '.json')
        if path.exists():
            (scratch / (name + '-previous.json')).write_bytes(path.read_bytes())
            # Absence of a new receipt can never reuse an old successful one.
            path.replace(scratch / (name + '-previous-moved.json'))
        script, _, binding = relocated_tree(name, args.port)
        print(json.dumps({'running': name, 'sourceFreeze': args.source_freeze}), flush=True)
        then = time.monotonic()
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker', name,
                                     '--port', str(args.port),
                                     '--source-freeze', args.source_freeze, '--wave', WAVE], cwd=REPO, env=env,
                                    capture_output=True, text=True, encoding='utf-8', timeout=360,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            code, stdout, stderr = result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired as exc:
            code = 124
            stdout = (exc.stdout or b'').decode('utf-8', errors='replace') if isinstance(exc.stdout, bytes) else exc.stdout or ''
            stderr = (exc.stderr or b'').decode('utf-8', errors='replace') if isinstance(exc.stderr, bytes) else exc.stderr or ''
        (scratch / (name + '.stdout.txt')).write_text(stdout, encoding='utf-8')
        (scratch / (name + '.stderr.txt')).write_text(stderr, encoding='utf-8')
        receipt = json.loads(path.read_bytes()) if path.exists() else {}
        retained = scratch / (name + '-receipt.json')
        if path.exists():
            retained.write_bytes(path.read_bytes())
        checks = receipt.get('checks') or {}
        row = {'originalProbe': script.relative_to(REPO).as_posix(), **binding,
               'receipt': path.relative_to(REPO).as_posix(),
               'receiptSha256': digest(path) if path.exists() else None,
               'retainedReceipt': str(retained) if path.exists() else None,
               'exitCode': code, 'durationSeconds': round(time.monotonic() - then, 3),
               'checks': checks, 'passed': sum(value is True for value in checks.values()),
               'failed': sum(value is not True for value in checks.values()),
               'ok': code == 0 and bool(checks) and all(value is True for value in checks.values()),
               'stdout': str(scratch / (name + '.stdout.txt')), 'stderr': str(scratch / (name + '.stderr.txt')),
               'sourceFreeze': args.source_freeze, 'phaseScratch': str(scratch)}
        aggregate['probes'][name] = row
        if name == 'browser':
            ipc_path = OUT / 'browser-ipc.json'
            row['assignedWindowsIpc'] = {'receipt': ipc_path.relative_to(REPO).as_posix(),
                                         'sha256': digest(ipc_path), 'observation': json.loads(ipc_path.read_bytes())}
        aggregate_path.write_text(json.dumps(aggregate, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'completed': name, 'ok': row['ok'], 'passed': row['passed'],
                          'failed': row['failed'], 'exitCode': code}), flush=True)
    phase['sourceHashesAtEnd'] = sources()
    phase['results'] = {name: dict(aggregate['probes'][name]) for name in names}
    phase['baselineHashesAtEnd'] = {path.name: digest(path) for path in (REPO / 'scripts/evidence').glob('FIXCL2*.json')}
    phase['sourceUnchanged'] = phase['sourceHashesAtStart'] == phase['sourceHashesAtEnd']
    phase['FIXCL2BaselineUnchanged'] = phase['baselineHashesAtStart'] == phase['baselineHashesAtEnd']
    aggregate.setdefault('phases', []).append(phase)
    aggregate['checks'] = {
        'allNineOriginalProbesReplayed': set(aggregate['probes']) == set(PROBES),
        'allOriginalNativeChecksPassed': all(row['ok'] for row in aggregate['probes'].values()),
        'allReplaySourcesStable': all(item['sourceUnchanged'] for item in aggregate['phases']),
        'FIXCL2BaselineConserved': all(item['FIXCL2BaselineUnchanged'] for item in aggregate['phases']),
    }
    aggregate['counts'] = {'probes': len(aggregate['probes']),
                           'green': sum(row['ok'] for row in aggregate['probes'].values()),
                           'red': sum(not row['ok'] for row in aggregate['probes'].values()),
                           'nativeChecksPassed': sum(row['passed'] for row in aggregate['probes'].values()),
                           'nativeChecksFailed': sum(row['failed'] for row in aggregate['probes'].values())}
    aggregate_path.write_text(json.dumps(aggregate, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'counts': aggregate['counts'], 'checks': aggregate['checks']}))
    return 0 if all(aggregate['probes'][name]['ok'] for name in names) and phase['sourceUnchanged'] and phase['FIXCL2BaselineUnchanged'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
