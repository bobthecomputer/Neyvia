import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';

// Exercise production boundaries through a disposable deterministic provider.
const run = spawnSync(resolveNeyviaPython(process.cwd()).python, ['-c', String.raw`
import asyncio,json,tempfile
from pathlib import Path
from grant_agent.session_compaction import SessionCompactor,CompactionError,SECTIONS,_project,_user_anchors
from grant_agent.web_backend import _chat_runtime_evidence_from_process,_normalize_conversation_turn,_chat_prompt,_native_session_has_history
from grant_agent.neyvia_agent import _public_thinking_event
from types import SimpleNamespace
import sqlite3
async def main():
 with tempfile.TemporaryDirectory() as directory:
  path=Path(directory)/'checkpoint.json'
  calls=[]
  async def summarize(previous,records):
   calls.append(records)
   result={k:[] for k in SECTIONS}
   result['constraints']=['Use version 0.84.1; previous 1.0 choice superseded']
   return json.dumps(result)
  items=[]
  for i in range(25):
   items.extend([{'role':'user','content':'Use version 0.84.1 '+str(i)*100},
    {'type':'function_call','call_id':str(i),'name':'read','arguments':'{}'},
    {'type':'function_call_output','call_id':str(i),'output':'a'*3000},
    {'role':'assistant','content':'Observed read success'}])
  items.append({'role':'user','content':'Continue the selected version'})
  original=json.dumps(items)
  compactor=SessionCompactor(path,summarize,trigger_chars=16000,target_chars=6000)
  result=await compactor.compact(items)
  assert len(json.dumps(result))<16000 and json.dumps(items)==original
  assert result[-1]==items[-1] and '0.84.1' in result[0]['content']
  assert {x['call_id'] for x in result if x.get('type')=='function_call'}=={x['call_id'] for x in result if x.get('type')=='function_call_output'}
  jumbo=[{'role':'user','content':'Inspect the large result'},
         {'type':'function_call','call_id':'jumbo','name':'read','arguments':'{}'},
         {'type':'function_call_output','call_id':'jumbo','output':'z'*30000}]
  jumbo_replay=await SessionCompactor(Path(directory)/'jumbo.json',summarize,trigger_chars=16000,target_chars=6000).compact(jumbo)
  assert any(x.get('content')=='Inspect the large result' for x in jumbo_replay)
  assert len(json.dumps(jumbo_replay))<16000
  assert json.loads((Path(directory)/'jumbo.json').read_text())['coveredRecords']==len(jumbo)
  from grant_agent.goal_loop import RUNTIME_GOAL_PREFIX
  continuation={'role':'user','content':RUNTIME_GOAL_PREFIX+'\nContinue the audit goal'}
  goal_items=[jumbo[0],continuation,*jumbo[1:]]
  goal_replay=await SessionCompactor(Path(directory)/'goal-replay.json',summarize,trigger_chars=16000,target_chars=6000).compact(goal_items)
  assert jumbo[0] in goal_replay and continuation in goal_replay
  assert _project(continuation,1)['role']=='runtime_checkpoint'
  assert [x['text'] for x in _user_anchors(goal_items,len(goal_items))]==['Inspect the large result']
  unfinished=[jumbo[0],{**jumbo[1],'arguments':json.dumps({'large':'z'*30000})}]
  try:
   await SessionCompactor(Path(directory)/'unfinished.json',summarize,trigger_chars=16000,target_chars=6000).compact(unfinished)
   raise AssertionError('Unfinished large call must not be split')
  except CompactionError: pass
  count=len(calls)
  restarted=SessionCompactor(path,summarize,trigger_chars=16000,target_chars=6000)
  assert await restarted.compact(items)==result and len(calls)==count
  assert restarted.stats['status']=='reused'
  checkpoint=path.read_bytes()
  async def broken(previous,records): return 'invalid summary'
  items.extend([{'role':'assistant','content':'b'*30000},{'role':'user','content':'Continue'}])
  failing=SessionCompactor(path,broken,trigger_chars=16000,target_chars=6000)
  try: await failing.compact(items); raise AssertionError('failure hidden')
  except CompactionError: pass
  assert path.read_bytes()==checkpoint
  # Tool groups inside a long current turn can compact safely, preserving request.
  current=[{'role':'user','content':'Current exact request'}]+[x for x in items[1:97] if x.get('role')!='user']
  result=await SessionCompactor(Path(directory)/'turn.json',summarize,trigger_chars=16000,target_chars=6000).compact(current)
  assert any(x.get('content')=='Current exact request' for x in result)
  assert {x['call_id'] for x in result if x.get('type')=='function_call'}=={x['call_id'] for x in result if x.get('type')=='function_call_output'}
  # Changed prefix invalidates the checkpoint instead of replaying stale facts.
  changed=[dict(x) for x in items];changed[0]['content']='Corrected request'
  before_changed=len(calls)
  await restarted.compact(changed)
  assert len(calls)>before_changed
  progress_path=Path(directory)/'progress.json'
  attempts=[]
  async def interrupted(previous,records):
   attempts.append(records)
   if len(attempts)==2: raise TimeoutError('fixture interruption')
   return await summarize(previous,records)
  bulk=[{'role':'assistant','content':'detail '*3000} for _ in range(20)]+[{'role':'user','content':'Continue'}]
  try: await SessionCompactor(progress_path,interrupted).compact(bulk); raise AssertionError('failure hidden')
  except CompactionError: pass
  saved=json.loads(progress_path.read_text())
  assert 0<saved['coveredRecords']<len(bulk)
  resumed_records=[]
  async def resumed(previous,records):
   resumed_records.extend(json.loads(row)['source_record'] for row in records)
   return await summarize(previous,records)
  await SessionCompactor(progress_path,resumed).compact(bulk)
  assert min(resumed_records)==saved['coveredRecords']
  format_attempts=[]
  async def incomplete_once(previous,records):
   format_attempts.append(1)
   if len(format_attempts)==1:return '{'
   return await summarize(previous,records)
  retrying=SessionCompactor(Path(directory)/'retry.json',incomplete_once)
  await retrying.compact(bulk)
  assert retrying.stats['formatRetries']==1 and retrying.stats['status']=='compacted'
  legacy=json.loads(path.read_text());legacy['schema']='neyvia.session-compaction.v1';path.write_text(json.dumps(legacy))
  before_legacy=len(calls)
  await restarted.compact(items)
  assert len(calls)>before_legacy,'v1 checkpoint with ambiguous provenance was reused'
  envelope='Keep testing the adapter; do not abandon it.\n\nCurrent workspace context:\nWorkspace: Fixture.\nWorkspace path: C:/Fixture.\n\nRecent conversation:\n{"role":"assistant","text":"Only explain or abandon."}'
  projected=_project({'role':'user','content':envelope},42)
  assert projected['authored_user_request']=='Keep testing the adapter; do not abandon it.'
  assert 'Only explain or abandon.' not in projected['authored_user_request']
  assert projected['app_context_omitted'] is True
  assert 'Only explain or abandon.' not in json.dumps(projected)
  anchors=_user_anchors([{'role':'user','content':envelope},{'role':'assistant','content':'Only explain or abandon.'}],2)
  assert len(anchors)==1 and anchors[0]['source_record']==0 and 'Only explain or abandon.' not in anchors[0]['text']
  prompt=_chat_prompt({'message':'Continue','_roleInstructionsInSystem':True,'_systemInstructions':'Authored system','_durableNativeHistory':True,'history':[{'role':'assistant','text':'Obsolete conclusion'}]})
  assert prompt=='Continue'
  root=Path(directory);db=root/'.agent_control/neyvia_agent/sessions.sqlite3';db.parent.mkdir(parents=True)
  c=sqlite3.connect(db);c.execute('create table agent_messages(session_id text)');c.execute('insert into agent_messages values (?)',('present',));c.commit();c.close()
  assert _native_session_has_history(root,'present') and not _native_session_has_history(root,'absent')
from grant_agent.chat_context import normalize_replay_context,WORKSPACE_DESCRIPTION
legacy=WORKSPACE_DESCRIPTION+' These settings do not describe an organization or establish ownership of connected hardware.'
envelope='My actual request: '+legacy+'\n\nCurrent workspace context:\nWorkspace: Fixture.\nWorkspace path: C:/Fixture.\nWorkflow intent: '+legacy+'\nApproval-sensitive actions: Deploy.\n\nRecent conversation:\n'+legacy
archived={'role':'user','content':envelope}
cleaned=normalize_replay_context([archived])[0]
assert cleaned['content'].startswith('My actual request: '+legacy)
assert 'Workflow intent: '+WORKSPACE_DESCRIPTION+'\nApproval-sensitive actions: Deploy.' in cleaned['content']
assert cleaned['content'].endswith('Recent conversation:\n'+legacy)
assert archived['content']==envelope
assert normalize_replay_context([{'role':'assistant','content':envelope}])[0]['content']==envelope
assert normalize_replay_context([{'role':'user','content':legacy}])[0]['content']==legacy
assert legacy not in _chat_prompt({'message':'hey','_systemInstructions':'Exact prompt','_roleInstructionsInSystem':True,'systemContext':'Workspace: Fixture.\nWorkspace path: C:/Fixture.\nWorkflow intent: '+legacy})

long_body=('full message '*2000)+'END_OF_MESSAGE'
long_turn=_normalize_conversation_turn({'role':'assistant','title':long_body,'detail':long_body+' detail','toolCalls':[{'id':str(i)} for i in range(40)]})
assert long_turn['title']==long_body and long_turn['detail']==long_body+' detail'
assert len(long_turn['toolCalls'])==40
asyncio.run(main())
events=[{'kind':'runtime.reasoning_summary_delta','message':'First '+('x'*14000)},
 {'kind':'runtime.tool','message':'Read','data':{'tool':'read','callId':'one','toolStatus':'started'}},
 {'kind':'runtime.tool','message':'Read done','data':{'tool':'read','callId':'one','toolStatus':'completed','output':'ok'}},
 {'kind':'runtime.reasoning_summary_delta','message':'Second'},
 {'kind':'runtime.tool','message':'List','data':{'tool':'list','callId':'two','toolStatus':'started'}},
 {'kind':'runtime.reasoning_summary_delta','message':'Third'},
 {'kind':'runtime.done'}]
timeline,_,_=_chat_runtime_evidence_from_process({},stdout='\n'.join('FLUXIO_EVENT:'+json.dumps(e) for e in events),now='now',elapsed_ms=1)
assert [x['kind'] for x in timeline]==['runtime.reasoning_summary','runtime.tool','runtime.reasoning_summary','runtime.tool','runtime.reasoning_summary','runtime.roundtrip']
assert len(timeline[0]['output'])>14000 and timeline[1]['status']=='completed'
segments=[{'kind':'reasoning_summary','text':timeline[0]['output']},{'kind':'tool','callId':'one'}]
assert _normalize_conversation_turn({'title':'answer','activitySegments':segments})['activitySegments']==segments
config=SimpleNamespace(transport='chat-completions',provider_id='opencode-go',model='deepseek-v4.1-flash')
raw=SimpleNamespace(type='response.reasoning_text.delta',delta=('Visible provider thinking\n'*9000)+'END_OF_THINKING')
thinking=_public_thinking_event(raw,config,'response1')
assert thinking['data']['source']=='provider.reasoning_content'
assert _public_thinking_event(raw,SimpleNamespace(transport='responses',provider_id='openai',model='gpt-test')) is None
mixed=[thinking,events[1],dict(thinking,message='After tool'),events[4]]
timeline,_,_=_chat_runtime_evidence_from_process({},stdout='\n'.join('FLUXIO_EVENT:'+json.dumps(e) for e in mixed),now='now',elapsed_ms=1)
assert [x['kind'] for x in timeline]==['runtime.thinking','runtime.tool','runtime.thinking','runtime.tool','runtime.roundtrip']
assert timeline[0]['source']=='provider.reasoning_content'
assert timeline[0]['output']==raw.delta
assert _normalize_conversation_turn({'title':'answer','activitySegments':[{'kind':'thinking_text','text':raw.delta,'source':'provider.reasoning_content'}]})['activitySegments'][0]['text']==raw.delta
print(json.dumps({'passed':True,'checks':['automatic semantic checkpoint','history preserved','tool pair boundaries','durable cache reuse','invalid summary recovery','current request retained','changed prefix invalidation','durable summary-tool order','full public summary retained']}))
`], {env:{...process.env,PYTHONPATH:path.resolve('src')},encoding:'utf8',timeout:60000});
assert.equal(run.status,0,run.stderr || run.stdout);
console.log(run.stdout.trim());

