"""Record FIX structural gates on the operator-selected Python and explicit ports."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import py_compile
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.durability import atomic_write_json
PYTHON = r'C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe'


def check_sources():
    from grant_agent.proof_contracts import source_bindings
    bindings = source_bindings()
    for file in (ROOT / 'web/src').rglob('*'):
        if file.is_file() and file.suffix in {'.js', '.jsx', '.ts', '.tsx', '.css', '.json', '.svg'}:
            bindings[file.relative_to(ROOT).as_posix()] = hashlib.sha256(
                file.read_text(encoding='utf-8').encode('utf-8')).hexdigest()
    return bindings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    parser.add_argument('--only', nargs='+', choices=('compile', 'build', 'node', 'verify', 'cl'))
    parser.add_argument('--area', action='append')
    parser.add_argument('--skip-manuals', action='store_true')
    parser.add_argument('--verify-timeout-seconds', type=float, default=3600,
                        help='Whole 40-area run budget; override for slower hosts')
    args = parser.parse_args()
    if args.verify_timeout_seconds <= 0: parser.error('Verification budget must be positive')
    if not args.label.replace('-', '').isalnum(): parser.error('Use a simple checkpoint label')
    control = ROOT / '.agent_control/fix'
    out = ROOT / 'scripts/evidence/fix/checks' / args.label
    out.mkdir(parents=True, exist_ok=True)
    control.mkdir(parents=True, exist_ok=True)
    from grant_agent.proof_ports import INT3_PORT_MAP
    slots = {48652:48661, 48654:48662, 48655:48669, 48656:48661, 48657:48662, 48658:48669}
    mapping = {str(key): slots[value] for key, value in INT3_PORT_MAP.items()}
    mapping['48494'] = 48669  # This three-listener proof requires three distinct slots.
    mapping['48491'], mapping['48492'] = 48661, 48662
    environment = dict(os.environ, NEYVIA_PROOF_ALLOWED_PORTS='[48661,48662,48669]',
        NEYVIA_PROOF_PORT_MAP=json.dumps(mapping), NEYVIA_SYSTEM_PYTHON=PYTHON,
        PYTHON=PYTHON, NEYVIA_PYTHON=PYTHON, NX_PYTHON=PYTHON,
        NEYVIA_VERIFY_SYSTEM_PYTHON=PYTHON, PYTHONUTF8='1',
        NEYVIA_TOOL_AUTO_UPDATE='0', NEYVIA_COORDINATOR_AUTOSTART='0', FLUXIO_WATCHDOG_AUTOSTART='0',
        FLUXIO_WEB_BACKEND_URL='http://127.0.0.1:48661', TAURI_DEV_PORT='48662',
        NEYVIA_UI_BACKEND_URL='http://127.0.0.1:48661',
        NEYVIA_PROOF_BUILD_ROOT=str(control / 'build'),
        PYTHONPATH=str(ROOT / 'src'), PYTHONDONTWRITEBYTECODE='1', NEYVIA_PROOF_PROGRESS='1')
    config = control / 'vite.config.mjs'
    config.write_text("import config from '../../vite.config.mjs';\nimport {resolve} from 'node:path';\nexport default env => ({...config(env),cacheDir:resolve('.agent_control/fix/vite-cache')});\n", encoding='utf-8')
    destination = out / 'results.json'
    results = json.loads(destination.read_text()) if destination.exists() else {}
    steps = args.only if args.only else ['compile', 'cl', 'build', 'node', 'verify']
    for step in steps:
        started = time.monotonic()
        before_sources = check_sources()
        atomic_write_json(out / (step + '-inputs.json'), {
            'sourceDigestAlgorithm': 'utf8-LF-sha256', 'sourceBindings': before_sources,
        })
        if step == 'compile':
            names = subprocess.check_output(['git', 'diff', '--name-only', '199a5450', '--', 'src', 'scripts'], cwd=ROOT, text=True).splitlines()
            names += subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '--', 'src', 'scripts'], cwd=ROOT, text=True).splitlines()
            failures, bindings = [], []
            for name in sorted(set(names)):
                file = ROOT / name
                if not name.endswith('.py') or name.startswith('scripts/evidence/') or not file.is_file(): continue
                try: py_compile.compile(str(file), cfile=str(control / 'compile' / (name.replace('/', '_') + 'c')), doraise=True)
                except py_compile.PyCompileError as error: failures.append({'file': name, 'error': str(error)})
                bindings.append({'path': name, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
            results[step] = {'exitCode': int(bool(failures)), 'files': bindings, 'failures': failures}
        else:
            commands = {
                'cl': [PYTHON, 'scripts/cl_compile_manuals.py', '--check'],
                'build': ['node', 'node_modules/vite/bin/vite.js', 'build', '--config', str(config), '--configLoader', 'runner', '--outDir', str(control / 'build')],
                'node': ['node', '--test', *map(str, sorted((ROOT / 'tests').glob('*.mjs')))],
                'verify': ['node', 'scripts/fluxio-cli.mjs', 'verify', '--root', str(control / 'verify'), '--allow-frontier', '--output', str(out / 'verify.json'), '--timeout-seconds', str(args.verify_timeout_seconds), *(['--skip-manuals'] if args.skip_manuals else []), *sum([['--area', area] for area in args.area or []], [])],
            }
            with (out / (step + '.log')).open('w', encoding='utf-8') as stream:
                run = subprocess.run(commands[step], cwd=ROOT, env=environment, stdout=stream, stderr=subprocess.STDOUT)
            results[step] = {'exitCode': run.returncode, 'command': commands[step], 'log': (out / (step + '.log')).relative_to(ROOT).as_posix()}
            if step == 'verify' and (out / 'verify.json').exists():
                report = json.loads((out / 'verify.json').read_text(encoding='utf-8'))
                results[step].update({k: report.get(k) for k in ('contractsOk', 'complete', 'sourceStable', 'failures', 'blocked')})
        results[step]['seconds'] = round(time.monotonic() - started, 3)
        results[step]['sourceStable'] = before_sources == check_sources()
        atomic_write_json(destination, results)
        print(json.dumps({'label': args.label, 'step': step, **{k: results[step][k] for k in ('exitCode', 'seconds')}}), flush=True)
        if results[step]['exitCode']: return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
