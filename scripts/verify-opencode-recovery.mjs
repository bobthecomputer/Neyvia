import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
import {createHash} from 'node:crypto';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const fixture = mkdtempSync(path.join(tmpdir(), 'neyvia-recovery-'));
const python = resolveNeyviaPython(repo).python;
try {
  const result = spawnSync(python, ['-c', String.raw`
import json,sys,time
from pathlib import Path
from grant_agent.web_backend import _run_process_capture, FluxioWebBackend
from types import SimpleNamespace
from grant_agent.neyvia_conversations import NeyviaConversationStore
from grant_agent.crashproof import CrashProofStore
root=Path(sys.argv[1])
events=[]
started=time.monotonic()
child="import time;print('FLUXIO_EVENT:'+__import__('json').dumps({'kind':'runtime.progress','message':'alive'}),flush=True);time.sleep(1);print('{}',flush=True)"
_run_process_capture([sys.executable,'-c',child],cwd=root,timeout=5,on_event=lambda e:events.append((e,time.monotonic()-started)))
assert events[0][0]['message']=='alive' and events[0][1]<0.9, events
codex_events=[]
codex_child="import json,time;print(json.dumps({'type':'thread.started','thread_id':'thread_fixture'}),flush=True);time.sleep(1);print(json.dumps({'type':'item.completed','item':{'type':'command_execution','command':'read fixture','status':'completed'}}),flush=True);print(json.dumps({'type':'turn.completed','usage':{'input_tokens':91,'output_tokens':7,'cached_input_tokens':80}}),flush=True)"
started=time.monotonic()
_run_process_capture([sys.executable,'-c',codex_child],cwd=root,timeout=5,event_format='codex',on_event=lambda e:codex_events.append((e,time.monotonic()-started)))
assert codex_events[0][1]<0.9
assert codex_events[0][0]['data']['externalRuntimeSessionId']=='thread_fixture'
assert codex_events[1][0]['data']['processId'] and codex_events[1][0]['message']=='read fixture'
assert codex_events[-1][0]['data']['usage']['cacheReadTokens']==80
def stop_codex(event):
    if event['data']['eventType']=='item.completed':
        raise RuntimeError('Codex correction boundary')
try:
    _run_process_capture([sys.executable,'-c',codex_child+';time.sleep(30)'],cwd=root,timeout=5,event_format='codex',on_event=stop_codex)
    raise AssertionError('Codex did not stop on correction boundary')
except RuntimeError as exc:
    assert 'Codex correction boundary' in str(exc)
try:
    _run_process_capture([sys.executable,'-c',child.replace('sleep(1)','sleep(30)')],cwd=root,timeout=1,on_event=lambda e:None)
    raise AssertionError('timeout was accepted')
except RuntimeError as e:
    assert 'timed out' in str(e) and 'alive' in str(e), str(e)
def correction(event):
    raise RuntimeError('New user correction at a tool boundary')
started=time.monotonic()
try:
    _run_process_capture([sys.executable,'-c',child.replace('sleep(1)','sleep(30)')],cwd=root,timeout=10,on_event=correction)
    raise AssertionError('correction did not interrupt capture')
except RuntimeError as e:
    assert 'New user correction' in str(e)
    assert time.monotonic()-started<5
# Use the real bridge with a disposable stand-in CLI emitting OpenCode wire events.
fake=root/'fake_cli.py'
fake.write_text("import json,time\nprint(json.dumps({'type':'text','sessionID':'ses_fixture','part':{'type':'text','text':'real wire text'}}),flush=True)\ntime.sleep(0.5)\n")
bridge="import sys;import grant_agent.opencode_bridge as b;b._popen_args=lambda a:[sys.executable,sys.argv[1]];raise SystemExit(b.run_opencode(opencode_command=sys.executable,prompt='fixture',model='opencode-go/deepseek-v4-flash'))"
events=[]
_,stdout,_,_=_run_process_capture([sys.executable,'-c',bridge,str(fake)],cwd=root,timeout=10,on_event=events.append)
progress=next(e for e in events if e['kind']=='runtime.progress')
assert progress['data']['externalRuntimeSessionId']=='ses_fixture' and progress['data']['processId']
assert any(e['kind']=='runtime.model_message' for e in events)
assert next(e for e in events if e['kind']=='runtime.finished')['status']=='completed'
fake.write_text("import json\nprint(json.dumps({'type':'error','error':{'message':'provider rejected'}}),flush=True)\n")
try:
    _run_process_capture([sys.executable,'-c',bridge,str(fake)],cwd=root,timeout=10,on_event=lambda e:None)
    raise AssertionError('error wire event was accepted as success')
except RuntimeError:
    pass
fake.write_text("import json\nprint(json.dumps({'type':'text','part':{'type':'text','text':'I will copy files'}}),flush=True)\nprint(json.dumps({'type':'step_finish','part':{'reason':'tool-calls'}}),flush=True)\n")
try:
    _run_process_capture([sys.executable,'-c',bridge,str(fake)],cwd=root,timeout=10,on_event=lambda e:None)
    raise AssertionError('intermediate text was accepted as final completion')
except RuntimeError:
    pass
fake.write_text("import json,os\nprint(json.dumps({'type':'text','part':{'type':'text','text':os.environ.get('OPENCODE_CONFIG_CONTENT','{}')}}),flush=True)\nprint(json.dumps({'type':'step_finish','part':{'reason':'stop'}}),flush=True)\n")
events=[]
scoped=bridge.replace("prompt='fixture',", "prompt='fixture',external_directories=[sys.argv[2]],")
_run_process_capture([sys.executable,'-c',scoped,str(fake),str(root/'approved')],cwd=root,timeout=10,on_event=events.append)
config=json.loads(next(e['message'] for e in events if e['kind']=='runtime.model_message'))
assert config['permission']['external_directory'][(root/'approved').as_posix()+'/*']=='allow'
assert '*' not in config['permission']['external_directory']
events=[]
_run_process_capture([sys.executable,'-c',scoped.replace("prompt='fixture',","prompt='fixture',mode='chat',"),str(fake),str(root/'approved')],cwd=root,timeout=10,on_event=events.append)
config=json.loads(next(e['message'] for e in events if e['kind']=='runtime.model_message'))
assert config['permission']['external_directory']=='deny'
events=[]
bounded_bridge=scoped.replace("prompt='fixture',","prompt='fixture',max_steps=3,")
_run_process_capture([sys.executable,'-c',bounded_bridge,str(fake),str(root/'approved')],cwd=root,timeout=10,on_event=events.append)
config=json.loads(next(e['message'] for e in events if e['kind']=='runtime.model_message'))
assert config['agent']['neyvia-harness']['steps']==3
assert config['agent']['neyvia-harness']['permission']['task']=='deny'
assert config['permission']['external_directory'][(root/'approved').as_posix()+'/*']=='allow'
events=[]
_run_process_capture([sys.executable,'-c',bounded_bridge.replace("prompt='fixture',","prompt='fixture',mode='chat',"),str(fake),str(root/'approved')],cwd=root,timeout=10,on_event=events.append)
config=json.loads(next(e['message'] for e in events if e['kind']=='runtime.model_message'))
assert config['agent']['neyvia-harness']['permission']['bash']=='deny'
assert config['agent']['neyvia-harness']['permission']['external_directory']=='deny'
wire_events=[
 {'type':'step_start'},
 {'type':'text','part':{'type':'text','text':'intermediate planning text'}},
 {'type':'step_finish','part':{'id':'step-one','reason':'tool-calls','tokens':{'input':120,'output':10,'cache':{'read':80}},'cost':0.02}},
 {'type':'step_start'},
 {'type':'text','part':{'type':'text','text':'{"verdict":"pass","evidence":["observed"]}'}},
 {'type':'step_finish','part':{'reason':'stop'}}
]
fake.write_text("import json\nfor e in "+repr(wire_events)+": print(json.dumps(e),flush=True)\n")
events=[]
_run_process_capture([sys.executable,'-c',bridge,str(fake)],cwd=root,timeout=10,on_event=events.append)
final=next(e['message'] for e in events if e['kind']=='runtime.model_message')
assert json.loads(final)['verdict']=='pass' and 'intermediate' not in final
assert any(e['message']=='intermediate planning text' for e in events if e['kind']=='runtime.progress')
usage=[e['data']['usage'] for e in events if e.get('data',{}).get('usage')][-1]
assert usage['inputTokens']==120 and usage['cacheReadTokens']==80 and usage['steps']==2
assert 'reasoningTokens' not in usage, 'missing usage is unavailable, not zero'
from grant_agent.efficient_workflow import continuation_instructions
turns=[{'turnId':'old','role':'user','content':'Preserve the original files'},
       {'turnId':'new','role':'user','content':'Stop reopening the game'}]
node={'objective':'Finish remaining documentation', 'teamContract':{'authority':{'allowWorkspaceMutation':True}},
      'routeSelection':{'runtimeId':'opencode-go'},
      'progress':{'resumeExternalRuntimeSessionId':'ses_retained','deliveredUserTurnIds':['old']}}
delta=continuation_instructions(node,turns)
assert 'Preserve the original' not in delta['objective'] and 'Stop reopening' in delta['objective']
assert delta['_userTurnIds']==['old','new']
from grant_agent.efficient_workflow import is_user_instruction_turn
imported={'turnId':'imported','role':'user','source':'runtime-handback',
          'content':'Old generated prompt must not become a correction'}
kind_only={**imported,'source':'legacy','turnKind':'runtime-handback'}
assert not is_user_instruction_turn(imported) and not is_user_instruction_turn(kind_only)
assert is_user_instruction_turn(turns[1]), 'real correction must remain actionable'
assert continuation_instructions(node,[*turns,imported,kind_only])==delta
assert imported['content'] not in continuation_instructions({**node,'progress':{}},[imported])['objective']
assert delta['_continuationContext']['omittedDuplicateCharacters']==len(turns[0]['content'])
fresh=continuation_instructions({**node,'progress':{}},turns)
assert all(t['content'] in fresh['objective'] for t in turns)
readonly=continuation_instructions({**node,'teamContract':{}},turns)
assert turns[0]['content'] in readonly['objective'], 'non-resumed mirror must receive original instructions'
other_runtime=continuation_instructions({**node,'routeSelection':{'runtimeId':'native-codex'}},turns)
assert turns[0]['content'] in other_runtime['objective'], 'do not assume a different runtime resumes its session'
duplicate=continuation_instructions({'objective':turns[1]['content']},turns)
assert duplicate['objective'].endswith(turns[1]['content']), 'latest reassertion must survive an intervening instruction'
duplicate=continuation_instructions({'objective':turns[1]['content']},[turns[1]])
assert duplicate['objective'].count(turns[1]['content'])==1
from grant_agent.efficient_workflow import continuation_checkpoint
failed_checkpoint=continuation_checkpoint({'nodeId':'failed-without-reply','lifecycleStage':'failed',
    'progress':{'invocationId':'inv-denied'},'resultSummary':{'result':{'reply':'',
    'compartment':{'blockers':['external_directory denied']}}}})
assert failed_checkpoint['verdict']=='unverified'
assert failed_checkpoint['latestFailure']['blockers']==['external_directory denied']
assert failed_checkpoint['latestFailure']['sourceInvocationId']=='inv-denied'
assert 'external_directory denied' in continuation_instructions({'objective':'Continue safely',
    'progress':{'continuationCheckpoint':failed_checkpoint}},[])['objective']
bounded_failure=continuation_checkpoint({'resultSummary':{'result':{'compartment':{'blockers':['x'*1000+str(i) for i in range(20)]}}}})
assert len(bounded_failure['latestFailure']['blockers'])==5 and bounded_failure['latestFailure']['truncated']
assert all(len(value)<=500 for value in bounded_failure['latestFailure']['blockers'])
prior={'nodeId':'worker','lifecycleStage':'failed','progress':{'invocationId':'inv_previous'},
       'resultSummary':{'result':{'reply':json.dumps({'verdict':'unverified','completed':['installed'],
          'missing':['physical controller check'],'evidence':['receipt-path'],
          'blockers':['needs physical input'],'nextAction':'prepare documentation'})}}}
checkpoint=continuation_checkpoint(prior)
assert checkpoint['completed']==['installed'] and checkpoint['missing']==['physical controller check']
assert checkpoint['evidenceStatus'].startswith('model-reported') and checkpoint['verdict']=='unverified'
assert 'prepare documentation' in continuation_instructions({'objective':'Respect new correction',
    'progress':{'continuationCheckpoint':checkpoint}},[])['objective']
assert continuation_checkpoint({'progress':{'continuationCheckpoint':checkpoint},
    'resultSummary':{'result':{'reply':'transport failed'}},'lifecycleStage':'waiting'})['completed']==['installed']
carried=continuation_checkpoint({'progress':{'continuationCheckpoint':checkpoint},
    'resultSummary':{'result':{'reply':'transport failed'}},'lifecycleStage':'waiting'})
assert carried['carriedForwardFromEarlierAttempt'] and 'revalidate' in carried['freshness']
handback=continuation_checkpoint({'resultSummary':{'result':{'reply':json.dumps({'summary':'inspected file',
    'unknowns':['physical input'],'evidence':['line 9']})}}})
assert handback['summary']=='inspected file' and handback['unknowns']==['physical input']
assert handback['verdict']=='unverified' and not handback['carriedForwardFromEarlierAttempt']
cleared=continuation_checkpoint({'progress':{'continuationCheckpoint':checkpoint},
    'resultSummary':{'result':{'reply':'{"completed":[],"missing":[]}'}}})
assert cleared['completed']==[] and not cleared['carriedForwardFromEarlierAttempt']
oversized={**prior,'resultSummary':{'result':{'reply':json.dumps({'verdict':'unverified',
    'evidence':['x'*1000]*100})}}}
bounded=continuation_checkpoint(oversized)
assert len(json.dumps(bounded))<2500 and bounded['truncatedFields']==['evidence']
long_prompt=("literal $() "+chr(96)+" & text\n")*5000
wire="import sys;from grant_agent.opencode_bridge import main;import grant_agent.opencode_bridge as b;b.run_opencode=lambda **kw:print(len(kw['prompt'])) or 0;raise SystemExit(main(['--prompt-stdin']))"
_,stdout,_,_=_run_process_capture([sys.executable,'-c',wire],cwd=root,timeout=10,stdin_text=long_prompt,on_event=lambda e:None)
assert int(stdout.strip())==len(long_prompt)
store=CrashProofStore(root)
s=NeyviaConversationStore(root,database_path=store.database_path)
c=s.create_conversation(kind='orchestration',title='recovery fixture')['conversationId']
route={'runtimeId':'opencode-go','provider':'opencode-go','model':'deepseek-v4-flash','effort':'default'}
s.create_concurrency_plan(c,tasks=[{'id':'worker','role':'executor','objective':'fixture','routeSelection':route}])
n=s.transition_agent_node('worker',lifecycle_stage='failed',result_summary={'error':'timeout','proof':'kept'})
s.record_orchestration_outcome(c,status='failed')
retried=s.retry_agent_node(c,'worker',reason='Checkpointed work and refreshed instructions',expected_revision=n['revision'])
assert s.get_conversation(c)['status']=='active', 'retry must clear the old failed parent outcome'
assert retried['lifecycleStage']=='requested' and retried['routeSelection']['model']=='deepseek-v4-flash'
assert retried['progress']['retryCount']==1
siblings=s.create_conversation(kind='orchestration',title='multiple failures')['conversationId']
s.create_concurrency_plan(siblings,tasks=[{'id':key,'role':'executor','objective':'fixture','routeSelection':route} for key in ('sibling-a','sibling-b')])
failed=[s.transition_agent_node(key,lifecycle_stage='failed') for key in ('sibling-a','sibling-b')]
s.record_orchestration_outcome(siblings,status='failed')
s.retry_agent_node(siblings,'sibling-a',reason='repair first failure',expected_revision=failed[0]['revision'])
assert s.get_conversation(siblings)['status']=='failed', 'another failed node must remain visible'
s.retry_agent_node(siblings,'sibling-b',reason='repair second failure',expected_revision=failed[1]['revision'])
assert s.get_conversation(siblings)['status']=='active'
try:
    s.retry_agent_node(c,'worker',reason='duplicate',expected_revision=retried['revision'])
    raise AssertionError('live or queued node retried')
except ValueError:
    pass
paused=s.transition_agent_node('worker',lifecycle_stage='waiting',progress={'pendingCorrectionTurnIds':['turn_correction'],'externalRuntimeSessionId':'ses_preserved'})
continued=s.retry_agent_node(c,'worker',reason='Apply the new user correction',expected_revision=paused['revision'])
assert continued['progress']['resumeExternalRuntimeSessionId']=='ses_preserved'
assert continued['lifecycleStage']=='requested'
with s._connection() as connection:
    # The failed attempt remains durable after reset.
    assert 'kept' in str(connection.execute("SELECT * FROM conversation_events WHERE kind='agent.retry'").fetchall()[0][:])
c2=s.create_conversation(kind='orchestration',title='correction fixture')['conversationId']
s.create_concurrency_plan(c2,tasks=[
    {'id':'first','role':'reader','objective':'Inspect','routeSelection':route},
    {'id':'second','role':'executor','objective':'Original target','routeSelection':route,'dependencies':['first']}
],max_parallel=1)
b=FluxioWebBackend.__new__(FluxioWebBackend)
b.root=root
b._neyvia_mcp=SimpleNamespace(conversations=s)
b._resolve_execution_workspace=lambda value:root
from grant_agent.orchestration_control import state as run_state, finish as finish_run
preflight=s.create_conversation(kind='orchestration',title='invalid target fixture')['conversationId']
def invalid_workspace(value):
    raise RuntimeError('Directory is outside configured workspace roots')
b._resolve_execution_workspace=invalid_workspace
try:
    b._run_neyvia_orchestration({'conversationId':preflight})
    raise AssertionError('invalid workspace admitted')
except RuntimeError as exc:
    assert 'outside configured workspace roots' in str(exc)
assert run_state(root,preflight)=={}, 'preflight failure must not create an interrupted run'
b._resolve_execution_workspace=lambda value:root
assert b._run_neyvia_orchestration({'conversationId':preflight})['status']=='nothing_to_run'
finish_run(root,preflight,'interrupted')
try:
    b._run_neyvia_orchestration({'conversationId':preflight})
    raise AssertionError('real interrupted run replayed after preflight repair')
except ValueError as exc:
    assert 'Previous execution was interrupted' in str(exc)
seen=[]
def execute(**kwargs):
    node=kwargs['node']
    seen.append(node['nodeId'])
    if node['nodeId']=='first':
        s.append_turn(c2,role='user',content='Use the corrected external-drive target')
    else:
        assert 'corrected external-drive target' in node['objective']
        assert not any('corrected external-drive target' in r['content'] for r in kwargs['context_selection']), 'instruction must not be duplicated in the packet'
    s.transition_agent_node(node['nodeId'],lifecycle_stage='completed')
    return {'nodeId':node['nodeId'],'status':'completed','result':{'reply':'fixture evidence'}}
b._run_neyvia_agent_node=execute
assert b._execute_neyvia_orchestration({'conversationId':c2})['status']=='completed'
assert seen==['first','second']
b._execute_neyvia_orchestration({'conversationId':c2})
assert seen==['first','second'], 'completed stages must not be replayed'
selected=s.snapshot(limit=1,conversation_id=c)
assert selected['activeConstellation']['conversationId']==c
assert selected['conversations'][0]['conversationId']==c, 'selected older mission must survive list pagination'
assert {row['nodeId'] for row in selected['activeConstellation']['nodes']}=={'worker'}
chat=s.create_conversation(kind='chat',title='ordinary chat')['conversationId']
assert s.snapshot(conversation_id=chat)['activeConstellation'] is None
try:
    s.snapshot(conversation_id='missing-selection')
    raise AssertionError('Missing selection silently substituted the newest mission')
except KeyError:
    pass
print('PASS: streaming before completion, bounded timeout, real bridge session identity, provider errors, exact-route retry and evidence preservation')
`, fixture], {cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:60000});
  assert.equal(result.status, 0, result.stderr || result.stdout || result.error?.message);
  const evidence = result.stdout.trim();
  console.log(JSON.stringify({status:'verified', evidence, sha256:createHash('sha256').update(evidence).digest('hex')}));
} finally {
  rmSync(fixture,{recursive:true,force:true});
}
