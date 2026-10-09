// Exercise the production adapters through a disposable transcript and native protocol records.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

const python = process.env.T22_PYTHON || 'C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe';
const program = String.raw`
import sys, json, tempfile, threading, sqlite3
from pathlib import Path
sys.path.insert(0, 'src')
from grant_agent.connected_sessions.codex_items import map_thread_item, map_turns
from grant_agent.connected_sessions.codex_stream import ThreadStream
from grant_agent.connected_sessions.codex import CodexAdapter
from grant_agent.connected_sessions.claude_items import tool_data, apply_tool_result
from grant_agent.connected_sessions.claude_stream import build_argv
from grant_agent.connected_sessions.claude_transcript import ItemStore
from grant_agent.connected_sessions.model import TurnOptions
from grant_agent.connected_sessions.opencode_acp import AcpTurn
from grant_agent.connected_sessions.opencode_history import tool_output
from grant_agent.connected_sessions.transparency import PAYLOAD_LIMIT
from grant_agent.connected_sessions.events import EventBuffer
out = {}
out['boundedEvent'] = EventBuffer('fixture').publish({'type':'item.updated','sessionId':'sid','item':{'id':'large','data':{'command':'x'*100000}}})
command = 'echo first\necho second ' + 'x' * 4000
out['codexCommand'] = map_thread_item({'type':'commandExecution','id':'cmd','command':command,'status':'completed','exitCode':7,'durationMs':18,'aggregatedOutput':'failure'},seq=0,at=None)[0].public()
out['codexContent'] = map_thread_item({'type':'reasoning','id':'r','summary':['Summary'],'content':['Exposed content']},seq=1,at=None)[0].public()
out['codexAbsent'] = [i.public() for i in map_turns([{'id':'t','status':'completed','items':[{'type':'agentMessage','id':'a','text':'done'}]}],{'t':0})]
events = []
stream = ThreadStream('sid','tid',events.append)
stream.begin_turn({'id':'t'})
stream.handle('item/started',{'item':{'id':'r','type':'reasoning'},'turnId':'t'})
stream.handle('item/reasoning/textDelta',{'itemId':'r','contentIndex':0,'delta':'Actual exposed content'})
out['codexLive'] = stream.live_items()[0].public()
data = tool_data('Bash',{'command':command})
apply_tool_result(data,text='failure',is_error=True,structured={'exitCode':7,'durationMs':42})
out['claudeCommand'] = data
out['claudeArgv'] = build_argv('claude',None,TurnOptions(model='haiku'))
out['claudeBound'] = tool_data('Read',{'file_path':'x' * (PAYLOAD_LIMIT + 200)})
records = [
 {'type':'assistant','timestamp':'2026-10-03T00:00:00Z','message':{'id':'m1','role':'assistant','content':[{'type':'tool_use','id':'edit','name':'Edit','input':{'file_path':'fixture.txt','old_string':'before\n','new_string':'after\n'}}]}},
 {'type':'user','timestamp':'2026-10-03T00:00:01Z','toolUseResult':{'structuredPatch':[{'oldStart':1,'oldLines':1,'newStart':1,'newLines':1,'lines':['-before','+after']}]},'message':{'role':'user','content':[{'type':'tool_result','tool_use_id':'edit','content':'edited'}]}},
 {'type':'assistant','timestamp':'2026-10-03T00:00:02Z','message':{'id':'m2','role':'assistant','stop_reason':'end_turn','content':[{'type':'text','text':'done'}]}}
]
with tempfile.TemporaryDirectory(dir='.agent_control/t22') as tmp:
 path = Path(tmp)/'fixture.jsonl'
 path.write_text('\n'.join(json.dumps(r) for r in records)+'\n', encoding='utf-8')
 store = ItemStore(path,'fixture')
 store.refresh()
 out['claudeTranscript'] = [i.public() for i in store.items]
 database = Path(tmp)/'native.db'
 conn = sqlite3.connect(database)
 conn.execute('CREATE TABLE message(id TEXT,session_id TEXT)')
 conn.execute('CREATE TABLE part(id TEXT,message_id TEXT,data TEXT)')
 conn.execute('INSERT INTO message VALUES (?,?)',('message','native-session'))
 conn.execute('INSERT INTO part VALUES (?,?,?)',('part','message',json.dumps({'type':'tool','callID':'call','state':{'output':'x'*12000}})))
 conn.commit()
 conn.close()
 out['opencodeFullOutput'] = tool_output(database,'native-session','run:call')
codex = CodexAdapter.__new__(CodexAdapter)
codex._lock = threading.RLock()
codex._thread_id = lambda sid: 'native'
codex._rpc = lambda *args, **kwargs: {'data':[{'items':[{'type':'commandExecution','id':'cmd','aggregatedOutput':'x'*12000}]}]}
out['codexFullOutput'] = codex.tool_output('sid','cmd')
codex._output_turns = {('native','cmd'):'turn'}
codex._rpc = lambda *args, **kwargs: {'data':[{'turnId':'turn','item':{'type':'commandExecution','id':'cmd','aggregatedOutput':'x'*12000}}]}
out['codexLocatedOutput'] = codex.tool_output('sid','cmd')
acp = AcpTurn.__new__(AcpTurn)
acp.loading, acp.run_id, acp.sid, acp.seq = False, 'fixture', 'sid', 0
acp.items, acp.stream, acp.tool_started, acp.emit = {}, None, {}, lambda event: None
acp.update(1,'session/update',{'update':{'sessionUpdate':'agent_thought_chunk','content':{'type':'text','text':'Shared thought'}}})
acp.update(1,'session/update',{'update':{'sessionUpdate':'tool_call','toolCallId':'cmd','kind':'execute','title':'Bash','status':'in_progress','rawInput':{'command':command}}})
acp.update(1,'session/update',{'update':{'sessionUpdate':'tool_call_update','toolCallId':'cmd','status':'completed','content':[{'type':'content','content':{'type':'text','text':'result'}}],'rawOutput':{'metadata':{'exit':0}}}})
out['opencode'] = list(acp.items.values())
print(json.dumps(out))
`;
const run = spawnSync(python, ['-'], { input: program, encoding: 'utf8', maxBuffer: 4 * 1024 * 1024 });
assert.equal(run.status, 0, run.stderr);
const result = JSON.parse(run.stdout);
assert.ok(result.codexCommand.data.command.includes('\n'));
assert.ok(result.codexCommand.data.command.length > 4000);
assert.equal(result.codexCommand.data.exitCode, 7);
assert.equal(result.codexContent.data.summary, 'Summary\n\nExposed content');
assert.equal(result.codexLive.data.summary, 'Actual exposed content');
assert.ok(result.codexAbsent.some(i => i.kind === 'reasoning' && i.data.exposure === 'not_reported'));
assert.equal(result.claudeCommand.command, result.codexCommand.data.command);
assert.equal(result.claudeCommand.exitCode, 7);
assert.equal(result.claudeCommand.durationMs, 42);
assert.ok(result.claudeArgv.includes('{"alwaysThinkingEnabled":true}'));
assert.equal(result.claudeBound.argsTruncated, true);
assert.ok(result.claudeBound.args.includes('omitted'));
assert.ok(result.claudeTranscript.some(i => i.kind === 'diff' && i.data.patch.includes('+after')));
assert.ok(result.claudeTranscript.some(i => i.kind === 'reasoning' && i.data.exposure === 'not_reported'));
assert.ok(result.opencode.some(i => i.kind === 'reasoning' && i.data.summary === 'Shared thought'));
const tool = result.opencode.find(i => i.kind === 'tool');
assert.equal(tool.data.command, result.codexCommand.data.command);
assert.equal(tool.data.category, 'command');
assert.equal(tool.data.exitCode, 0);
assert.equal(tool.data.output, 'result');
assert.equal(typeof tool.data.durationMs, 'number');
assert.equal(result.codexFullOutput.length, 12000);
assert.equal(result.codexLocatedOutput.length, 12000);
assert.equal(result.opencodeFullOutput.length, 12000);
assert.equal(result.boundedEvent.truncated, true);
assert.ok(Buffer.byteLength(JSON.stringify(result.boundedEvent)) <= 64 * 1024);
console.log(JSON.stringify({ ok: true, checks: 25, scope: 'production adapter mapping, streaming, full-output hooks, event limits and disposable transcript replay' }));
