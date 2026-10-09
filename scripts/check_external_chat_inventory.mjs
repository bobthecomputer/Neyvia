import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';

const repo = path.resolve(import.meta.dirname, '..');
const python = path.join(repo, '.venv', 'Scripts', 'python.exe');
const fixture = await mkdtemp(path.join(tmpdir(), 'neyvia-external-chats-'));
const env = { ...process.env, USERPROFILE: fixture, HOME: fixture };
delete env.CODEX_HOME;
delete env.CLAUDE_CONFIG_DIR;
delete env.OPENCODE_DATA_DIR;
env.PYTHONPATH = path.join(repo, 'src');
const run = (args) => {
  const result = spawnSync(python, ['-m', 'grant_agent.external_chat_inventory', ...args], { cwd: repo, env, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr || 'external chat inventory command failed');
  return JSON.parse(result.stdout);
};
const digest = async (file) => createHash('sha256').update(await readFile(file)).digest('hex');

try {
  const codexDir = path.join(fixture, '.codex', 'sessions', '2026', '09', '29');
  const claudeDir = path.join(fixture, '.claude', 'projects', 'demo-project');
  const opencodeDir = path.join(fixture, '.local', 'share', 'opencode');
  await Promise.all([mkdir(codexDir, { recursive: true }), mkdir(claudeDir, { recursive: true }), mkdir(opencodeDir, { recursive: true })]);
  const codexFile = path.join(codexDir, 'rollout-2026-09-29T10-00-00-12345678-1234-1234-1234-123456789abc.jsonl');
  const claudeFile = path.join(claudeDir, 'claude-session-001.jsonl');
  const codexData = [
    { timestamp: '2026-09-29T10:00:00Z', type: 'response_item', payload: { type: 'message', role: 'user', content: [{ type: 'input_text', text: 'Codex fixture request' }] } },
    { timestamp: '2026-09-29T10:00:00Z', type: 'response_item', payload: { type: 'message', role: 'assistant', channel: 'analysis', content: [{ type: 'output_text', text: 'This private analysis must not appear' }] } },
    { timestamp: '2026-09-29T10:00:01Z', type: 'response_item', payload: { type: 'message', role: 'assistant', content: [{ type: 'output_text', text: 'Codex fixture reply' }] } },
  ].map(JSON.stringify).join('\n');
  const claudeData = [
    { timestamp: '2026-09-29T10:01:00Z', type: 'user', message: { role: 'user', content: [{ type: 'text', text: 'Claude fixture request' }] } },
    { timestamp: '2026-09-29T10:01:01Z', type: 'assistant', message: { role: 'assistant', content: [{ type: 'text', text: 'Claude fixture reply' }] } },
  ].map(JSON.stringify).join('\n');
  await Promise.all([writeFile(codexFile, codexData), writeFile(claudeFile, claudeData)]);
  const py = String.raw`
import sqlite3, sys, json
db=sqlite3.connect(sys.argv[1])
db.executescript('CREATE TABLE session(id TEXT PRIMARY KEY,title TEXT); CREATE TABLE message(id TEXT PRIMARY KEY,session_id TEXT,data TEXT); CREATE TABLE part(id TEXT PRIMARY KEY,message_id TEXT,data TEXT);')
db.execute('INSERT INTO session VALUES(?,?)',('opencode-session-001','OpenCode fixture'))
db.execute('INSERT INTO message VALUES(?,?,?)',('om1','opencode-session-001',json.dumps({'role':'user'})))
db.execute('INSERT INTO part VALUES(?,?,?)',('op1','om1',json.dumps({'type':'text','text':'OpenCode fixture request'})))
db.execute('INSERT INTO message VALUES(?,?,?)',('om2','opencode-session-001',json.dumps({'role':'assistant'})))
db.execute('INSERT INTO part VALUES(?,?,?)',('op2','om2',json.dumps({'type':'text','text':'OpenCode fixture reply'})))
db.commit(); db.close()
`;
  const createDb = spawnSync(python, ['-c', py, path.join(opencodeDir, 'opencode.db')], { env, encoding: 'utf8' });
  assert.equal(createDb.status, 0, createDb.stderr);
  const before = await Promise.all([digest(codexFile), digest(claudeFile), digest(path.join(opencodeDir, 'opencode.db'))]);
  const listed = run(['list', '--root', fixture]);
  assert.deepEqual(new Set(listed.chats.map((chat) => chat.app)), new Set(['codex', 'claude-code', 'opencode']));
  assert.ok(listed.chats.every((chat) => chat.id.startsWith(`external:${chat.app}:${listed.host.deviceId}:`)));
  assert.ok(listed.chats.every((chat) => chat.deviceId === listed.host.deviceId && chat.deviceName));
  for (const [app, phrase] of [['codex', 'Codex fixture reply'], ['claude-code', 'Claude fixture reply'], ['opencode', 'OpenCode fixture reply']]) {
    const chat = listed.chats.find((item) => item.app === app);
    assert.ok(chat, `${app} chat discovered`);
    const transcript = run(['read', '--root', fixture, '--id', chat.id]);
    assert.equal(transcript.chat.id, chat.id);
    assert.ok(transcript.messages.some((message) => message.role === 'assistant' && message.text === phrase), `${app} transcript is readable`);
    assert.equal(transcript.truncated, false);
  }
  const filtered = run(['list', '--root', fixture, '--app', 'codex']);
  assert.equal(filtered.chats.length, 1);
  assert.equal(filtered.chats[0].app, 'codex');
  const searched = run(['list', '--root', fixture, '--query', 'CLAUDE FIXTURE']);
  assert.equal(searched.chats.length, 1);
  assert.equal(searched.chats[0].app, 'claude-code');
  const codexChat = listed.chats.find((chat) => chat.app === 'codex');
  const codexTranscript = run(['read', '--root', fixture, '--id', codexChat.id]);
  assert.ok(!codexTranscript.messages.some((message) => message.text.includes('private analysis')));
  const indexDb = path.join(fixture, '.codex', 'state_5.sqlite');
  const indexFixture = spawnSync(python, ['-c', String.raw`
import sqlite3,sys,os
c=sqlite3.connect(sys.argv[1])
c.execute('CREATE TABLE threads(id TEXT,rollout_path TEXT,name TEXT,title TEXT,has_user_event INTEGER)')
p=sys.argv[2]
if os.name=='nt':p='\\\\?\\'+p
c.execute('INSERT INTO threads VALUES(?,?,?,?,?)',('12345678-1234-1234-1234-123456789abc',p,'Named desktop chat','Raw startup metadata',0))
c.commit();c.close()
`, indexDb, codexFile], {env,encoding:'utf8'});
  assert.equal(indexFixture.status,0,indexFixture.stderr);
  const indexed = run(['list','--root',fixture,'--app','codex']);
  assert.equal(indexed.chats[0].title,'Named desktop chat','desktop name survives stale has_user_event and Windows extended path');
  const after = await Promise.all([digest(codexFile), digest(claudeFile), digest(path.join(opencodeDir, 'opencode.db'))]);
  assert.deepEqual(after, before, 'external app stores were not modified');
  console.log('EXTERNAL_CHAT_INVENTORY_OK apps=codex,claude-code,opencode transcript=read-only device-identity=namespaced');
} finally {
  await rm(fixture, { recursive: true, force: true });
}
