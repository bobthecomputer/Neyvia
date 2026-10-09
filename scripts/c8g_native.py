"""Run the integrated native journey from an explicitly private process desktop.

Binding a caller thread does not change the desktop inherited by Popen children.
Keep the entire proof host private, including Playwright and CLI helper children.
The installed Python is copied and hash-pinned locally; nothing is installed.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
LOG = Path(r'C:\Users\user\Projects\plans\logs\window-guard.jsonl')


def child(port, debug_port, output):
    if os.environ.get('NEYVIA_C8H_TRACE_SPAWNS') == '1':
        import threading
        import traceback
        original = subprocess.Popen.__init__
        trace_lock = threading.Lock()
        def traced(process, *args, **options):
            frames = [{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
                      for f in traceback.extract_stack()[-10:-1]]
            original(process, *args, **options)
            command = args[0] if args else options.get('args', [])
            if isinstance(command, str):
                command = [command]
            row = {'pid': process.pid, 'parentPid': os.getpid(),
                'program': Path(str(command[0])).name if command else None,
                'scripts': [Path(str(v)).name for v in command[1:] if str(v).lower().endswith(('.py', '.ps1', '.js', '.mjs'))],
                'creationflags': options.get('creationflags'), 'thread': threading.current_thread().name,
                'frames': frames}
            with trace_lock, output.with_suffix('.spawns.jsonl').open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(row) + '\n')
        subprocess.Popen.__init__ = traced
    from prove_c11_preview import run
    from c8f_native import probe
    def observed_probe(scratch, request, call, sid, wid, state):
        observations = []
        def ready_call(op, arguments):
            value = call(op, arguments)
            if op == 'inspect' and 'query' not in arguments:
                # An initial incomplete provider read is not an effect. Resolve
                # the exact fixture field with bounded read-only observations.
                deadline = time.monotonic() + 2
                while not any(e.get('label') == 'Task input' for e in value.get('elements', [])):
                    observations.append({'operation': op, 'result': value})
                    if time.monotonic() >= deadline:
                        (scratch / 'c8g-native-observations.json').write_text(json.dumps(observations, indent=2))
                        raise RuntimeError('Native fixture field missing from fresh bounded provider reads')
                    time.sleep(.05)
                    value = call(op, {**arguments, 'query': 'Task input'})
            return value
        result = probe(scratch, request, ready_call, sid, wid, state)
        if os.environ.get('NEYVIA_C8H_NATIVE_PROBE') == 'remote':
            from c8h_remote import probe as remote_probe
            result['remote'] = remote_probe(scratch, request, call, sid, wid, state)
            result['passed'] = result['passed'] and result['remote']['passed']
        return result
    return run(port, debug_port, output, journey_probe=observed_probe,
               scratch_parent=ROOT / '.agent_control/proofs/C8/c8g-native')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--debug-port', required=True, type=int)
    parser.add_argument('--receipt', required=True, type=Path)
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    from c8_scope import assigned_ports
    if args.port == args.debug_port or any(p not in assigned_ports() for p in (args.port, args.debug_port)):
        parser.error('Distinct assigned C8 ports required')
    output = args.receipt.resolve()
    if not output.is_relative_to(ROOT / 'scripts/evidence'):
        parser.error('Receipt must remain inside task evidence')
    if args.child:
        return 0 if child(args.port, args.debug_port, output) else 2
    from grant_agent.cua_desktop import AgentDesktop
    from grant_agent.cua_guard import ZeroDisturbanceGuard
    area = ROOT / '.agent_control/proofs/C8/c8g-host' / uuid.uuid4().hex
    area.mkdir(parents=True)
    executable = area / 'python.exe'
    shutil.copy2(sys.executable, executable)
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    assert digest == hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
    argv = [str(executable), str(Path(__file__).resolve()), '--child',
            '--port', str(args.port), '--debug-port', str(args.debug_port), '--receipt', str(output)]
    before = LOG.read_bytes()
    guard = ZeroDisturbanceGuard().start()
    start = time.monotonic()
    launch = {'exitCode': None}
    failure = None
    try:
        with AgentDesktop(profile_root=area) as desktop:
            desktop.admit_pinned_console(argv, digest)
            process = desktop.launch(argv, cwd=ROOT, env={
                'PYTHONHOME': str(Path(sys.executable).parent),
                'PATH': str(Path(sys.executable).parent) + ';' + os.environ['PATH'],
            })
            guard.register_pid(process.pid)
            exit_code = process.wait(timeout=240)
            launch = {'pid': process.pid, 'desktop': desktop.name,
                      'api': 'CreateProcessW STARTUPINFO.lpDesktop; suspended job admission before ResumeThread',
                      'pythonSha256': digest, 'exitCode': exit_code}
    except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as exc:
        failure = type(exc).__name__ + ': ' + str(exc)[:400]
        exit_code = None
    finally:
        final_guard = guard.close()
    result = json.loads(output.read_text()) if output.exists() else {'ok': False, 'error': 'Child produced no receipt'}
    result['privateHost'] = launch
    if failure:
        result['hostFailure'] = failure
    result['hostGuard'] = final_guard
    result['externalGuardLog'] = {
        'sha256Before': hashlib.sha256(before).hexdigest(),
        'sha256After': hashlib.sha256(LOG.read_bytes()).hexdigest(),
        'unchanged': before == LOG.read_bytes(),
    }
    result['ok'] = bool(result.get('ok') and result.get('additionalJourneys', {}).get('passed')
                        and exit_code == 0 and final_guard['ok']
                        and result['externalGuardLog']['unchanged'])
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'receipt': str(output.relative_to(ROOT)), 'ok': result['ok'],
                      'error': result.get('error'), 'guard': final_guard['ok'],
                      'guardLogUnchanged': result['externalGuardLog']['unchanged'],
                      'elapsedSeconds': round(time.monotonic() - start, 2)}))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
