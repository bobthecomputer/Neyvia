import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = resolveNeyviaPython(repo).python;
const root = mkdtempSync(path.join(tmpdir(), 'neyvia-task-continuity-'));
try {
  const result = spawnSync(python, ['-c', String.raw`
import json, sys
from grant_agent.task_continuity import TaskContinuityStore
root = sys.argv[1]
a = TaskContinuityStore(root, 'admin-a')
b = TaskContinuityStore(root, 'admin-a')
other = TaskContinuityStore(root, 'admin-b')
initial = a.read('computer')
assert initial['revision'] == 0 and initial['sharedLatest'] is None
saved = a.save('computer', 'conversation-1', initial['revision'], {'text': 'Bonjour — résumé', 'draft': True})
assert saved['ok'] and saved['checkpoint']['revision'] == 1
phone_view = b.read('phone')
assert phone_view['revision'] == 1 and phone_view['lastResumed']['conversationId'] == 'conversation-1'
conflict = b.save('phone', 'conversation-1', 0, {'text': 'stale'})
assert conflict['conflict'] and conflict['status'] == 'conflict' and conflict['current']['revision'] == 1
rebased = b.save('phone', 'conversation-1', 1, {'text': 'Téléphone ✅'})
assert rebased['ok'] and rebased['checkpoint']['cursor'] == 'r2'
cleared = a.save('computer', 'conversation-1', 2, None)
assert cleared['ok'] and cleared['checkpoint']['draft'] is None
reloaded = TaskContinuityStore(root, 'admin-a').read('computer')
assert reloaded['revision'] == 3 and reloaded['deviceCheckpoint']['draft'] is None
assert reloaded['lastResumed']['deviceId'] == 'computer'
assert other.read('computer')['revision'] == 0 and other.read('computer')['sharedLatest'] is None
errors = 0
for fn in (
    lambda: a.read('bad/device'),
    lambda: a.save('phone', 'conversation-1', True, None),
    lambda: a.save('phone', 'conversation-1', 3, 'x' * 70000),
):
    try: fn()
    except ValueError: errors += 1
assert errors == 3
print(json.dumps({'schema': reloaded['schema'], 'revision': reloaded['revision'], 'conflict': conflict['status'], 'unicode': rebased['checkpoint']['draft']['text'], 'ownerIsolation': other.read('computer')['revision'] == 0}))
`, root], {cwd: repo, env: {...process.env, PYTHONPATH: path.join(repo, 'src')}, encoding: 'utf8', timeout: 30000});
  assert.equal(result.status, 0, result.stderr || result.stdout || result.error?.message);
  const out = JSON.parse(result.stdout.trim());
  assert.equal(out.schema, 'neyvia.task-continuity.v1');
  assert.equal(out.revision, 3);
  assert.equal(out.conflict, 'conflict');
  assert.equal(out.unicode, 'Téléphone ✅');
  assert.equal(out.ownerIsolation, true);
  console.log('TASK_CONTINUITY_VERIFIED: transactional cross-device resume, stale-write conflict/rebase, reload, Unicode, clear, validation, and owner isolation');
} finally {
  rmSync(root, {recursive: true, force: true});
}
