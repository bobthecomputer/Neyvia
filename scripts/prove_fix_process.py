"""Independent live-child proof of the production Windows process query."""
from __future__ import annotations
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    from grant_agent.cli import _pid_exists
    from grant_agent.cluster import _pid_alive
    child = subprocess.Popen([sys.executable, '-c', 'input()'], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    rows = []
    try:
        for _ in range(10):
            started = time.perf_counter()
            live = _pid_exists(child.pid) and _pid_alive(child.pid)
            rows.append({'pid': child.pid, 'phase': 'owned-child-alive', 'alive': live,
                         'passed': live, 'ms': round((time.perf_counter() - started) * 1000, 3)})
        child.stdin.write(b'\n'); child.stdin.flush()
        child.wait(timeout=10)
        for _ in range(10):
            started = time.perf_counter()
            live = _pid_exists(child.pid) or _pid_alive(child.pid)
            rows.append({'pid': child.pid, 'phase': 'owned-child-exited', 'alive': live,
                         'passed': not live, 'ms': round((time.perf_counter() - started) * 1000, 3)})
        rows.append({'phase': 'invalid-pid', 'passed': not _pid_exists(0) and not _pid_exists(-1) and not _pid_alive(0) and not _pid_alive(-1)})
    finally:
        if child.poll() is None: child.terminate(); child.wait(timeout=5)
        for stream in (child.stdin, child.stdout, child.stderr): stream.close()
    result = {'schema': 'neyvia.FIX.process-query.v1', 'passed': all(row['passed'] for row in rows), 'rows': rows,
        'boundary': 'CLI and cluster query the same disposable owned child through the existing native helper before/after normal exit; no tasklist decoding or external service'}
    result['sources'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                         for name in ('src/grant_agent/cli.py', 'src/grant_agent/cluster.py', 'src/grant_agent/subprocess_utils.py', 'scripts/prove_fix_process.py')}
    (ROOT / 'scripts/evidence/FIX-process.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': result['passed'], 'calls': len(rows), 'maxMs': max(row.get('ms', 0) for row in rows)}))
    return int(not result['passed'])


if __name__ == '__main__':
    raise SystemExit(main())
