import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { resolveNeyviaPython } from './resolve-neyvia-python.mjs';

const { root: repo, python } = resolveNeyviaPython();
const fixtureRoot = mkdtempSync(path.join(tmpdir(), 'neyvia-native-commands-'));
try {
  const artifact = path.join(fixtureRoot, 'unicode-artifact.txt');
  const marker = path.join(fixtureRoot, 'child.pid');
  const script = String.raw`
import json, os, signal, subprocess, sys, time
from pathlib import Path
from grant_agent.native_tools import NativeToolRegistry

root = Path(sys.argv[1])
artifact = Path(sys.argv[2])
marker = Path(sys.argv[3])
registry = NativeToolRegistry(root)
rows = registry.list_tools(include_schemas=True)
names = {row['name'] for row in rows}
assert {'terminal.exec', 'runtime.environment'} <= names
commands = next(row for row in rows if row['name'] == 'terminal.exec')
assert commands['requires_approval'] is True
assert commands['mutability_class'] == 'external_action'
assert commands['parallel_safe'] is False
assert commands['inputSchema']['properties']['timeoutMs']['maximum'] == 120000
search_terminal = registry.search('PowerShell Python terminal commands')
assert any(row['name'] == 'terminal.exec' for row in search_terminal)
search_env = registry.search('runtime environment available shells')
assert any(row['name'] == 'runtime.environment' for row in search_env)

unicode_text = 'Neyvia café 漢字 🌱'
powershell = registry.call('terminal.exec', {
    'shell': 'powershell', 'cwd': str(root), 'timeoutMs': 15000, 'maxOutputChars': 2048,
    'command': "Write-Output '" + unicode_text + "'",
})
environment = registry.call('runtime.environment')
assert powershell['ok'] and powershell['result']['status'] == 'completed', powershell
assert powershell['result']['shell'] == 'powershell'
assert powershell['result']['exitCode'] == 0
assert unicode_text in powershell['result']['stdout'], repr(powershell['result']['stdout'])
assert powershell['result']['resolvedExecutable']
assert environment['ok'] and environment['result']['status'] == 'observed'
assert environment['result']['python']['executable'] == sys.executable
assert environment['result']['environmentValuesIncluded'] is False
assert 'environment' not in json.dumps(environment['result']).lower() or environment['result']['environmentValuesIncluded'] is False

py_command = (
    'from pathlib import Path; import hashlib; '
    'p=Path(' + repr(str(artifact)) + '); '
    'p.write_text(' + repr(unicode_text) + ', encoding="utf-8"); '
    'print(hashlib.sha256(p.read_bytes()).hexdigest())'
)
python_result = registry.call('terminal.exec', {
    'shell': 'python', 'cwd': str(root), 'timeoutMs': 15000, 'maxOutputChars': 2048,
    'command': py_command,
})
assert python_result['ok'] and python_result['result']['exitCode'] == 0, python_result
assert python_result['result']['shell'] == 'python'
assert artifact.is_file() and artifact.read_text(encoding='utf-8') == unicode_text
artifact_hash = __import__('hashlib').sha256(artifact.read_bytes()).hexdigest()
assert artifact_hash in python_result['result']['stdout']

failed = registry.call('terminal.exec', {
    'shell': 'python', 'command': "import sys; print('expected failure', file=sys.stderr); sys.exit(7)",
})
assert not failed['ok'] and failed['status'] == 'failed'
assert failed['result']['exitCode'] == 7 and 'expected failure' in failed['result']['stderr']

timeout_code = (
    'import os, subprocess, sys, time; '
    'flags=getattr(subprocess,"CREATE_NO_WINDOW",0); '
    'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(45)"], creationflags=flags); '
    'open(' + repr(str(marker)) + ',"w",encoding="utf-8").write(str(p.pid)); '
    'print(p.pid, flush=True); time.sleep(45)'
)
timed = registry.call('terminal.exec', {
    'shell': 'python', 'command': timeout_code, 'timeoutMs': 2500, 'maxOutputChars': 2048,
})
assert not timed['ok'] and timed['status'] == 'timed_out' and timed['result']['timedOut'], timed
assert marker.is_file(), timed
child_pid = int(marker.read_text(encoding='utf-8'))
deadline = time.monotonic() + 8
child_alive = True
while time.monotonic() < deadline:
    try:
        os.kill(child_pid, 0)
        child_alive = True
    except OSError:
        child_alive = False
        break
    time.sleep(0.1)
if child_alive:
    if os.name == 'nt':
        subprocess.run(['taskkill.exe', '/PID', str(child_pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        try: os.kill(child_pid, signal.SIGKILL)
        except OSError: pass
assert not child_alive, f'timed-out command left child process {child_pid} running'

truncation = registry.call('terminal.exec', {
    'shell': 'python', 'command': "import sys; print('x' * 8000); print('y' * 8000, file=sys.stderr)", 'maxOutputChars': 256,
})
assert truncation['ok'] and truncation['result']['truncated']
assert len(truncation['result']['stdout']) + len(truncation['result']['stderr']) <= 256
assert truncation['result']['stdoutTruncated'] and truncation['result']['stderrTruncated']
print(json.dumps({
    'discovery': True,
    'permissionMetadata': commands['requires_approval'] and commands['mutability_class'] == 'external_action' and not commands['parallel_safe'],
    'powershellUnicode': powershell['result']['stdout'],
    'pythonArtifactSha256': artifact_hash,
    'nonzeroExitCode': failed['result']['exitCode'],
    'timeout': {'status': timed['status'], 'processTreeStopped': timed['result']['processTreeStopped'], 'childCleanedUp': not child_alive},
    'boundedOutput': {'chars': len(truncation['result']['stdout']) + len(truncation['result']['stderr']), 'stdoutTruncated': truncation['result']['stdoutTruncated'], 'stderrTruncated': truncation['result']['stderrTruncated']},
    'environmentKeys': sorted(environment['result'].keys()),
}, ensure_ascii=False))
`;

  const result = spawnSync(python, ['-c', script, fixtureRoot, artifact, marker], {
    cwd: repo,
    env: { ...process.env, PYTHONPATH: path.join(repo, 'src'), PYTHONIOENCODING: 'utf-8' },
    encoding: 'utf8',
    timeout: 90000,
    maxBuffer: 2 * 1024 * 1024,
  });
  assert.equal(result.status, 0, result.stderr || result.stdout || result.error?.message);
  const evidence = JSON.parse(result.stdout);
  assert.equal(evidence.discovery, true);
  assert.equal(evidence.permissionMetadata, true);
  assert.equal(evidence.timeout.childCleanedUp, true);
  assert.equal(evidence.boundedOutput.stdoutTruncated, true);
  assert.equal(evidence.boundedOutput.stderrTruncated, true);
  assert(evidence.boundedOutput.chars <= 256);
  const artifactHash = createHash('sha256').update(readFileSync(artifact)).digest('hex');
  assert.equal(artifactHash, evidence.pythonArtifactSha256);
  console.log(JSON.stringify({ status: 'verified', ...evidence, artifactHash }));
} finally {
  if (existsSync(fixtureRoot)) rmSync(fixtureRoot, { recursive: true, force: true });
}
