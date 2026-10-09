import assert from 'node:assert/strict';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const repo = path.resolve(import.meta.dirname, '..');
const python = path.join(repo, '.venv', 'Scripts', 'python.exe');
const env = { ...process.env, PYTHONPATH: path.join(repo, 'src') };
const probe = String.raw`
import json
from grant_agent.connected_codex_chats import connected_codex_capabilities, list_codex_chats, read_codex_chat
ready = connected_codex_capabilities()
if not ready['available']:
    print(json.dumps({'available': False, 'count': 0, 'readable': False}))
else:
    result = list_codex_chats(limit=8)
    chats = result.get('chats', [])
    readable = False
    if chats:
        # Read one actual thread through app-server, without printing transcript text.
        read_codex_chat(chats[0]['id'])
        readable = True
    print(json.dumps({'available': True, 'count': len(chats), 'readable': readable, 'transport': result.get('capabilities', {}).get('transport')}))
`;
const result = spawnSync(python, ['-c', probe], { cwd: repo, env, encoding: 'utf8', timeout: 90000 });
assert.equal(result.status, 0, result.stderr || 'connected Codex chat check failed');
const report = JSON.parse(result.stdout);
if (!report.available) {
  console.log('CONNECTED_CODEX_CHATS_UNAVAILABLE');
} else {
  assert.equal(report.transport, 'codex-app-server');
  assert.ok(report.count >= 0);
  if (report.count > 0) assert.equal(report.readable, true, 'a listed existing chat can be read through app-server');
  console.log(`CONNECTED_CODEX_CHATS_OK transport=${report.transport} listed=${report.count} read=${report.readable}`);
}
