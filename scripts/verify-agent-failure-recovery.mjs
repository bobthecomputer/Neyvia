import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { resolveNeyviaPython } from './resolve-neyvia-python.mjs';
const repo=process.cwd(),root=mkdtempSync(path.join(tmpdir(),'neyvia-failure-recovery-'));
try {
  const run=spawnSync(resolveNeyviaPython(repo).python,['-c',String.raw`
import asyncio,json,os,sys
from pathlib import Path
import grant_agent.neyvia_agent as agent
from grant_agent.subprocess_utils import capture_bounded_process,process_is_alive
from grant_agent.execution_ownership import ExecutionOwnership
r=Path(sys.argv[1]);child=r/'executor.py'
child.write_text('import json,os,subprocess,sys,time\nworker=subprocess.Popen([sys.executable,"-c","import time; time.sleep(20)"])\nprint(json.dumps({"type":"thread.started","thread_id":"partial-proof"}),flush=True)\nprint(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"Preserved partial observation"}}),flush=True)\nopen(sys.argv[1],"w").write(str(worker.pid))\ntime.sleep(20)\n',encoding='utf8')
original=agent.capture_bounded_process
agent._codex_cli_command=lambda:sys.executable
agent._popen_args=lambda args:[sys.executable,str(child),str(r/'child.pid')]
config=agent.NeyviaAgentConfig(root=r,session_id='timeout-proof',transport='codex-cli',model='gpt-5.6-luna',max_turns=1,timeout_seconds=2,enable_specialists=False,allow_mutations=True)
result=asyncio.run(agent.run_neyvia_agent(config,'Fixture execution; no model call'))
saved=json.loads(Path(result['receiptPath']).read_text())
checks={'failedReceipt':saved['status']=='failed','timeoutCode':saved['recovery']['code']=='executor_timeout','partialPreserved':'Preserved partial observation' in saved['recovery']['partialOutput'],'sessionPreserved':saved['externalRuntimeSessionId']=='partial-proof','uncertainEffects':saved['recovery']['sideEffects']=='uncertain','noBlindRetry':saved['recovery']['retrySafety']=='reconcile_before_retry','childStopped':not process_is_alive(int((r/'child.pid').read_text())),'treeTerminationConfirmed':saved['recovery']['processTreeStopped'] is True,'ownershipFailed':ExecutionOwnership(r,'timeout-proof').snapshot()['status']=='failed','noCommandInRecovery':'developer_instructions' not in json.dumps(saved['recovery'])}
child.write_text('import json,sys\nprint(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"Partial before exit failure"}}))\nsys.exit(2)\n',encoding='utf8')
second=asyncio.run(agent.run_neyvia_agent(config,'Second fixture'))
checks['exitFailurePreserved']=second['status']=='failed' and second['recovery']['exitCode']==2 and 'Partial before exit failure' in second['recovery']['partialOutput']
async def broken_sdk(*args,**kwargs):
    gateway=agent.NeyviaToolGateway(r,allow_mutations=True,action_scope='sdk-proof')
    gateway.call_native('work.focus',{'text':'Preserved step before provider failure'},action_id='before-sdk-failure')
    raise RuntimeError('Private provider diagnostic must not leak')
agent.Runner.run=broken_sdk
sdk_config=agent.NeyviaAgentConfig(root=r,session_id='sdk-proof',transport='responses',model='gpt-5.6-luna',enable_specialists=False,allow_mutations=True)
sdk=asyncio.run(agent.run_neyvia_agent(sdk_config,'SDK failure fixture',provider=object()))
checks['sdkFailureReceipt']=sdk['status']=='failed' and sdk['recovery']['exceptionType']=='RuntimeError'
checks['sdkUnknownUsageExplicit']=sdk['usage']['inputTokens'] is None and sdk['usage']['reportedByTransport'] is False
checks['sdkNoPrivateDiagnostic']='Private provider diagnostic' not in json.dumps(sdk)
checks['sdkPriorActionRecoverable']=agent.NeyviaToolGateway(r,action_scope='sdk-proof').actions.inspect('before-sdk-failure')['status']=='completed'
async def slow_sdk(*args,**kwargs):await asyncio.sleep(20)
agent.Runner.run=slow_sdk
sdk_timeout=asyncio.run(agent.run_neyvia_agent(agent.NeyviaAgentConfig(root=r,session_id='sdk-timeout',transport='responses',model='gpt-5.6-luna',enable_specialists=False,timeout_seconds=1),'SDK timeout fixture',provider=object()))
checks['sdkTimeoutReceipt']=sdk_timeout['status']=='failed' and sdk_timeout['recovery']['code']=='executor_timeout'
import grant_agent.web_backend as web
parent=r/'parent.py'
parent.write_text("import asyncio,json,sys\nfrom pathlib import Path\nimport grant_agent.neyvia_agent as a\nr=Path(sys.argv[1])\na._codex_cli_command=lambda:sys.executable\na._popen_args=lambda args:[sys.executable,'-c','import time;time.sleep(20)']\nprint(json.dumps(asyncio.run(a.run_neyvia_agent(a.NeyviaAgentConfig(root=r,session_id='nested-timeout',transport='codex-cli',model='gpt-5.6-luna',timeout_seconds=1,enable_specialists=False),'Nested fixture'))))\n",encoding='utf8')
nested,_,_,elapsed=web._run_process_capture([sys.executable,str(parent),str(r)],cwd=r,timeout=15)
checks['outerReceivesFailedReceipt']=nested['status']=='failed' and nested['recovery']['code']=='executor_timeout' and Path(nested['receiptPath']).is_file()
checks['outerPreservesCleanupMargin']=elapsed<15000
captured={}
def fake_capture(args,**kwargs):
    captured.update(args=args,timeout=kwargs['timeout'])
    return {'output':'deadline fixture','status':'completed'},'', '', 1
web._run_process_capture=fake_capture
web.FluxioWebBackend(r,r)._run_neyvia_chat({'message':'Deadline dispatch fixture','runtime':'neyvia-agent','workspacePath':str(r),'route':{'provider':'openai-codex','model':'gpt-5.6-luna','effort':'medium'}})
inner=int(captured['args'][captured['args'].index('--timeout-seconds')+1])
checks['nativeDispatchReservesReceiptTime']=inner==captured['timeout']-30
print(json.dumps(checks))
`,root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:45000});
  assert.equal(run.status,0,run.stderr||run.error?.message);
  const checks=JSON.parse(run.stdout);for(const [name,value] of Object.entries(checks))assert.equal(value,true,name);
  mkdirSync('proof/system-improvement',{recursive:true});
  writeFileSync('proof/system-improvement/failure-recovery-checks.json',JSON.stringify({verifiedAt:new Date().toISOString(),checks,boundary:'Real disposable executor and child processes; production receipt path; no model call.'},null,2)+'\n');
  console.log('AGENT_FAILURE_RECOVERY_VERIFIED',JSON.stringify(checks));
}finally{if(path.dirname(path.resolve(root))===path.resolve(tmpdir())&&path.basename(root).startsWith('neyvia-failure-recovery-'))rmSync(root,{recursive:true,force:true});}
