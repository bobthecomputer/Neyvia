import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const repo = path.resolve(import.meta.dirname, '..');
const python = path.join(repo, '.venv', 'Scripts', 'python.exe');
const fixture = await mkdtemp(path.join(tmpdir(), 'neyvia-connected-claude-'));
const session = '3f63dd34-f8e8-4a5f-a99e-4434ea2226f1';
const transcript = path.join(fixture, '.claude', 'projects', 'demo-project', `${session}.jsonl`);
await mkdir(path.dirname(transcript), { recursive: true });
await writeFile(transcript, [
  JSON.stringify({ type: 'user', sessionId: session, message: { role: 'user', content: [{ type: 'text', text: 'fixture prompt' }] } }),
  JSON.stringify({ type: 'assistant', sessionId: session, message: { role: 'assistant', content: [{ type: 'text', text: 'fixture answer' }] } }),
].join('\n'));

const source = String.raw`
import json
from grant_agent import connected_claude_chats as adapter
from grant_agent.external_chat_inventory import list_external_chats
rows = list_external_chats(app='claude-code')['chats']
identity = next(row['id'] for row in rows if row['id'].endswith(':${session}'))
caps = adapter.capabilities()
assert caps['provider'] == 'claude-code'
assert 'Desktop conversations' in caps['unsupported']['claudeDesktopChats']
assert 'Claude.ai chats' in caps['unsupported']['claudeWebChats']
assert caps['capabilities']['images'] == 'inherited-session-context-only'
sid, path = adapter._resolve_session(identity)
assert sid == '${session}' and path.endswith('${session}.jsonl')
wire = json.loads(adapter._request_line('Continue fixture').decode('utf-8'))
assert wire == {'type':'user','message':{'role':'user','content':[{'type':'text','text':'Continue fixture'}]}}
events = []
adapter._session_is_running = lambda session_id: True
try:
    adapter.send_message(identity, 'Must not double-write', request_id='fixture-request', on_event=events.append)
except adapter.ConnectedClaudeChatError as exc:
    assert exc.code == 'session_active'
else:
    raise AssertionError('active session was not refused')
assert events == []
try:
    adapter.send_message('external:claude-desktop:device:chat', 'no', request_id='x', on_event=lambda event: None)
except adapter.ConnectedClaudeChatError as exc:
    assert exc.code == 'unsupported_chat'
else:
    raise AssertionError('Desktop chat was accepted')
print(json.dumps({'identity':identity,'capabilities':caps,'activeConflict':'refused','desktop':'unsupported'}))
`;
try {
  const result = spawnSync(python, ['-c', source], {
    cwd: repo,
    encoding: 'utf8',
    env: { ...process.env, USERPROFILE: fixture, HOME: fixture, PYTHONPATH: path.join(repo, 'src') },
  });
  assert.equal(result.status, 0, result.stderr || 'Claude connected-chat verification failed');
  const report = JSON.parse(result.stdout);
  assert.ok(report.identity.startsWith('external:claude-code:'));
  assert.equal(report.activeConflict, 'refused');
  assert.equal(report.desktop, 'unsupported');
  console.log('CONNECTED_CLAUDE_CHAT_OK adapter=official-cli contract=stream-json active-session=refused desktop-web=unsupported');

  if (process.argv.includes('--live')) {
    const liveSource = String.raw`
import json, os, subprocess, sys, tempfile, shutil, uuid
from pathlib import Path
sys.path.insert(0, r'${path.join(repo, 'src')}')
from grant_agent import connected_claude_chats as adapter
from grant_agent.external_chat_inventory import list_external_chats
cli=adapter._cli_path()
if not cli:
 print(json.dumps({'status':'blocked','phase':'preflight','reason':'official Claude Code CLI unavailable'})); raise SystemExit(0)
if os.environ.get('CLAUDE_CODE_SKIP_PROMPT_HISTORY') == '1':
 print(json.dumps({'status':'blocked','phase':'preflight','reason':'existing Claude Code setting disables persistent session history'})); raise SystemExit(0)
sid=str(uuid.uuid4()); project=Path(tempfile.mkdtemp(prefix='neyvia-claude-resume-proof-'))
try:
 try:
  p=subprocess.run([str(cli),'--print','--session-id',sid,'--tools','','--output-format','json','Harmless disposable chat check: reply with exactly CREATED_MARKER_CEDAR_2841 and no other text. Do not use tools.'],cwd=str(project),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180,shell=False,text=True,encoding='utf-8',errors='replace')
 except subprocess.TimeoutExpired:
  print(json.dumps({'status':'blocked','phase':'create','reason':'official Claude Code CLI exceeded the 180 second initial request limit; authentication status was not established'})); raise SystemExit(0)
 if p.returncode:
  err=p.stderr.casefold(); reason='authentication or account access unavailable' if any(x in err for x in ('auth','login','sign in','unauthorized','subscription')) else 'Claude Code failed to create the disposable session'
  print(json.dumps({'status':'blocked','phase':'create','reason':reason,'returnCode':p.returncode})); raise SystemExit(0)
 rows=list_external_chats(app='claude-code')['chats']; chat=next((x for x in rows if x['id'].endswith(':'+sid)),None)
 if not chat:
  print(json.dumps({'status':'blocked','phase':'inventory','reason':'new session not visible in Claude Code inventory'})); raise SystemExit(0)
 events=[]
 try:
  result=adapter.send_message(chat['id'],'Continue the harmless check. Reply with exactly RESUMED_MARKER_MAPLE_7316 and no other text. Do not use tools.',request_id='disposable-live-proof-'+sid,on_event=events.append,timeout_seconds=180)
 except adapter.ConnectedClaudeChatError as exc:
  print(json.dumps({'status':'blocked','phase':'resume','code':exc.code,'reason':exc.message,'eventTypes':[e.get('type') for e in events]})); raise SystemExit(0)
 text=result['text']; initial='CREATED_MARKER_CEDAR_2841' in p.stdout; resumed='RESUMED_MARKER_MAPLE_7316' in text
 print(json.dumps({'status':'success' if initial and resumed else 'inconclusive','sessionId':sid,'chatId':chat['id'],'initialMarker':initial,'resumeMarker':resumed,'resultText':text[:200],'eventTypes':[e.get('type') for e in events]}))
finally:
 shutil.rmtree(project,ignore_errors=True)
`;
    const live = spawnSync(python, ['-c', liveSource], {
      cwd: repo,
      encoding: 'utf8',
      timeout: 360_000,
      env: { ...process.env, PYTHONPATH: path.join(repo, 'src') },
    });
    assert.equal(live.status, 0, live.stderr || 'Live Claude Code continuity check failed');
    const liveReport = JSON.parse(live.stdout);
    console.log(`CONNECTED_CLAUDE_LIVE_${liveReport.status.toUpperCase()} ${JSON.stringify(liveReport)}`);
  }
} finally {
  await rm(fixture, { recursive: true, force: true });
}
