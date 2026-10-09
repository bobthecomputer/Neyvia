"""Exercise synchronous deadlines in a disposable, deliberately failing suite."""
from pathlib import Path
import hashlib
import json
import os
import site
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
scratch = ROOT / '.agent_control/int3/guard-probe'
scratch.mkdir(parents=True, exist_ok=True)
(scratch / 'test_deadline.py').write_text(
    'def test_expiration():\n    while True:\n        pass\n'
    'def test_next_test_runs():\n    assert 2 + 2 == 4\n', encoding='utf-8')
env = dict(os.environ, INT3_TEST_DEADLINE='0.05', INT3_WORKSPACE_ROOT=str(ROOT),
           INT3_OUTCOME_LOG=str(scratch / 'outcomes.json'), PYTHONNOUSERSITE='1',
           PYTHONDONTWRITEBYTECODE='1',
           PYTHONPATH=os.pathsep.join((str(ROOT / 'scripts'), site.getusersitepackages())),
           TEMP=str(scratch), TMP=str(scratch))
command = [sys.executable, '-s', '-m', 'pytest', '-p', 'int3_pytest_guard', '-q',
           '--tb=short', str(scratch / 'test_deadline.py')]
start = time.monotonic()
result = subprocess.run(command, cwd=scratch, env=env, capture_output=True, text=True, timeout=30)
outcomes = json.loads((scratch / 'outcomes.json').read_text())
finished = {r['nodeid'] for r in outcomes['reports'] if r['phase'] == 'teardown'}
passed = [r for r in outcomes['reports'] if r['phase'] == 'call' and r['outcome'] == 'passed']
ok = (result.returncode == 1 and len(outcomes['failed_ids']) == 1
      and len(finished) == 2 and len(passed) == 1 and 'INT3TestDeadline' in result.stdout)
receipt = {'schema': 'neyvia.int3.guard-probe.v1', 'ok': ok,
           'seconds': time.monotonic() - start, 'exitCode': result.returncode,
           'deadlineSeconds': .05, 'fullSuiteDeadlineSeconds': 120,
           'guardSha256': hashlib.sha256((ROOT / 'scripts/int3_pytest_guard.py').read_bytes()).hexdigest(),
           'expected': 'One actual pending-signal deadline failure, both teardown reports, next test passes, no asynchronous C exception injection',
           'outcomes': outcomes, 'stdout': result.stdout, 'stderr': result.stderr}
output = ROOT / 'scripts/evidence/int3/guard-deadline-probe.json'
output.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'ok': ok, 'exitCode': result.returncode, 'seconds': receipt['seconds']}))
raise SystemExit(0 if ok else 1)
