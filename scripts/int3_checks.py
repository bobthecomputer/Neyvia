"""Record the requested per-merge structural checks without changing shared state."""
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
BASE = 'a18870b7602998728859ffcf25c7af6d497e53ea'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('label')
    parser.add_argument('--only', choices=('compile', 'build', 'node', 'pytest'))
    parser.add_argument('--pytest-path', action='append')
    parser.add_argument('--node-source', type=Path, default=ROOT)
    parser.add_argument('--node-current-files', action='store_true', help='Match baseline Node files to the surviving integrated suite')
    args = parser.parse_args()
    out = ROOT / 'scripts/evidence/int3/checks' / args.label
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, NEYVIA_TOOL_AUTO_UPDATE='0', NEYVIA_COORDINATOR_AUTOSTART='0',
               FLUXIO_WATCHDOG_AUTOSTART='0', FLUXIO_WEB_BACKEND_URL='http://127.0.0.1:48651',
               TAURI_DEV_PORT='48652', NEYVIA_PROOF_SOCKETPAIR_PORTS='48654,48655,48656,48657,48658,48659')
    python = r'C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe'
    env.update(PYTHON=python, NEYVIA_PYTHON=python, NX_PYTHON=python)
    result_path = out / 'results.json'
    results = json.loads(result_path.read_text()) if result_path.exists() else {}
    steps = [args.only] if args.only else ['compile', 'build', 'node', 'pytest']
    for step in steps:
        start = time.monotonic()
        if step == 'compile':
            names = subprocess.check_output(['git', 'diff', '--name-only', BASE, '--', 'src', 'scripts', 'tests'], cwd=ROOT, text=True).splitlines()
            names += [p.relative_to(ROOT).as_posix() for p in (ROOT / 'scripts').glob('int3*.py')]
            rows, failures = [], []
            for name in sorted(set(names)):
                path = ROOT / name
                if not name.endswith('.py') or name.startswith('scripts/evidence/') or not path.is_file():
                    continue
                try:
                    py_compile.compile(str(path), doraise=True)
                except py_compile.PyCompileError as exc:
                    failures.append({'path': name, 'error': str(exc)})
                rows.append({'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            results[step] = {'exitCode': int(bool(failures)), 'files': rows, 'failures': failures}
        else:
            if step in ('node','pytest'):
                guard_dir = ROOT / '.agent_control/int3/node-python-guard'
                guard_dir.mkdir(parents=True, exist_ok=True)
                (guard_dir / 'sitecustomize.py').write_text('import int3_pytest_guard\nint3_pytest_guard.install()\n', encoding='utf-8')
                temp = ROOT / '.agent_control/int3/pytest-temp' / args.label
                temp.mkdir(parents=True, exist_ok=True)
                env.update(NODE_OPTIONS='--require ' + str(ROOT / 'scripts/int3_node_guard.cjs'),
                           PYTHONPATH=os.pathsep.join([str(guard_dir), str(ROOT / 'scripts'), str(args.node_source.resolve() / 'src')]),
                           INT3_WORKSPACE_ROOT=str(ROOT), TEMP=str(temp), TMP=str(temp),
                           PYTHONDONTWRITEBYTECODE='1', GIT_CEILING_DIRECTORIES=str(ROOT / '.agent_control'),
                           INT3_OUTCOME_LOG=str(out/'related-pytest.json'))
            node_paths = ([args.node_source.resolve()/'tests'/path.name for path in (ROOT/'tests').glob('*.mjs')]
                          if args.node_current_files else list((args.node_source.resolve()/'tests').glob('*.mjs')))
            command = (['node', str(ROOT / 'node_modules/vite/bin/vite.js'), 'build', '--configLoader', 'runner',
                        '--outDir', str(ROOT / '.agent_control/int3/build')]
                       if step == 'build' else ['node', '--test', *map(str,node_paths)])
            if step == 'pytest':
                command = [python, '-m', 'pytest', '-p', 'int3_pytest_guard', '-q', '--tb=short',
                           '-o', 'log_file='+str(temp/'internal.log'),
                           *(args.pytest_path or ['tests/test_intcl_manual_sources.py','tests/test_cl_config_validation.py'])]
            with (out / (step + '.log')).open('w', encoding='utf-8') as stream:
                run = subprocess.run(command, cwd=args.node_source.resolve() if step=='node' else ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
            results[step] = {'exitCode': run.returncode, 'command': command, 'log': (out / (step + '.log')).relative_to(ROOT).as_posix()}
        results[step]['seconds'] = round(time.monotonic() - start, 3)
        result_path.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'label': args.label, 'step': step, 'exitCode': results[step]['exitCode'], 'seconds': results[step]['seconds']}), flush=True)
    return int(any(results[step]['exitCode'] for step in steps))

if __name__ == '__main__':
    raise SystemExit(main())
