import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const manifest = path.join(root, 'src-tauri', 'Cargo.toml');
const proofDirectory = path.join(root, 'proof', 'desktop-backend-deadline-20260925');
const receiptPath = path.join(proofDirectory, 'deadline-verification.json');
const sha256 = (filePath) => createHash('sha256').update(readFileSync(filePath)).digest('hex');
const receipt = {
  schema: 'neyvia.desktop-backend-deadline-verification.v1',
  createdAt: new Date().toISOString(),
  source: {
    rustSha256: sha256(path.join(root, 'src-tauri', 'src', 'lib.rs')),
    controllerSha256: sha256(path.join(root, 'src', 'grant_agent', 'desktop_controller.py')),
    verifierSha256: sha256(fileURLToPath(import.meta.url)),
  },
  checks: {},
};
const saveReceipt = () => {
  mkdirSync(proofDirectory, { recursive: true });
  writeFileSync(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, 'utf8');
};
const controllerCheck = String.raw`
import json, os, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from src.grant_agent import desktop_controller as dc
os.environ['FLUXIO_AGENT_CHAT_RUNTIME_TIMEOUT_SECONDS'] = '15'
os.environ['FLUXIO_AGENT_CHAT_RUNTIME_TIMEOUT_MAX_SECONDS'] = '7200'
assert dc._request_wait_timeout_seconds('send_agent_chat_command', {'runtimeTimeoutSeconds': 7200}) == 7320
assert dc._request_wait_timeout_seconds('send_agent_chat_command', {'runtimeTimeoutSeconds': 15}) == 135
assert dc._request_wait_timeout_seconds('get_agent_prompt_library_command', {}) == 3600
with tempfile.TemporaryDirectory(prefix='neyvia-controller-timeout-') as temp:
    root = Path(temp)
    db = dc._connect(root)
    now = time.time()
    rows = [
        ('long-chat-001', 'send_agent_chat_command', {'runtimeTimeoutSeconds': 7200}, 'claimed', now - 4000),
        ('short-chat-01', 'send_agent_chat_command', {'runtimeTimeoutSeconds': 15}, 'claimed', now - 140),
        ('queued-old-01', 'get_agent_prompt_library_command', {}, 'queued', now - 181),
    ]
    for request_id, command, payload, state, updated in rows:
        db.execute(
            'INSERT INTO controller_requests(root,request_id,content_hash,command,payload_json,session_id,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
            (str(root), request_id, 'fixture', command, json.dumps(payload), 'session', state, updated, updated),
        )
    dc._compact_terminal_rows(db, str(root), now)
    actual = {row['request_id']: row['state'] for row in db.execute('SELECT request_id,state FROM controller_requests')}
    assert actual['long-chat-001'] == 'claimed', actual
    assert actual['short-chat-01'] == 'expired', actual
    assert actual['queued-old-01'] == 'expired', actual
    db.close()
print('controller timeout policy and per-request compaction passed')
`;
const controller = spawnSync('python', ['-c', controllerCheck, root], {
  cwd: root,
  encoding: 'utf8',
  timeout: 30_000,
  maxBuffer: 1024 * 1024,
});
if (controller.error) throw controller.error;
if (controller.stdout) process.stdout.write(controller.stdout);
if (controller.stderr) process.stderr.write(controller.stderr);
receipt.checks.controllerPolicyAndCompaction = {
  passed: controller.status === 0,
  summary: (controller.stdout ?? '').trim(),
};
if (controller.status !== 0) {
  receipt.result = 'failed';
  saveReceipt();
  process.exit(controller.status ?? 1);
}
if (process.argv.includes('--controller-only')) {
  receipt.result = 'partial';
  receipt.rustTests = 'not-run';
  saveReceipt();
  process.exit(0);
}

const result = spawnSync(
  'cargo',
  [
    'test',
    '--manifest-path',
    manifest,
    '--lib',
    'desktop_backend_deadline_',
    '--',
    '--nocapture',
  ],
  {
    cwd: root,
    encoding: 'utf8',
    timeout: 600_000,
    maxBuffer: 4 * 1024 * 1024,
  },
);

if (result.error) {
  receipt.result = 'failed';
  receipt.checks.rust = { passed: false, error: String(result.error) };
  saveReceipt();
  throw result.error;
}
if (result.stdout) process.stdout.write(result.stdout);
if (result.stderr) process.stderr.write(result.stderr);
const output = `${result.stdout ?? ''}\n${result.stderr ?? ''}`;
receipt.checks.rust = {
  passed: result.status === 0,
  summary: output.split(/\r?\n/).filter((line) => /^test tests::desktop_backend_deadline_|^test result:/.test(line)),
};
receipt.result = result.status === 0 ? 'passed' : 'failed';
saveReceipt();
if (result.status !== 0) {
  process.exitCode = result.status ?? 1;
} else {
  if (process.platform === 'win32' && !output.includes('3 passed')) {
    throw new Error('Expected both the >180-second and timeout/reap production helper checks to pass.');
  }
}
