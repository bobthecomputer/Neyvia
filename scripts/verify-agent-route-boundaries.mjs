import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { resolveNeyviaPython } from './resolve-neyvia-python.mjs';
const root=mkdtempSync(path.join(tmpdir(),'neyvia-chat-route-'));
try {
  const run=spawnSync(resolveNeyviaPython().python,['-c',String.raw`
import json,sys
from pathlib import Path
import grant_agent.web_backend as web
r=Path(sys.argv[1]);b=web.FluxioWebBackend(r,r);calls=[]
def failed(payload):raise RuntimeError('fixture native route unavailable')
def fallback(payload):
 calls.append('codex')
 return {'reply':'explicit fallback fixture','runtime':'codex','status':'completed','route':payload['route']}
b._run_neyvia_chat=failed;b._run_codex_chat=fallback
web._codex_cli_login_status=lambda:{'authenticated':True}
p={'runtime':'neyvia-agent','workspacePath':str(r),'sessionId':'route-fixture','message':'Bounded route fixture','route':{'provider':'openai-codex','model':'gpt-5.6-luna','effort':'medium'}}
a=b._run_agent_chat(p,allow_mutation=True)
checks={'defaultPreservesRequestedRuntime':not calls and a['status']=='failed' and a['runtime']=='neyvia-agent'}
c=b._run_agent_chat({**p,'allowRuntimeFallback':True},allow_mutation=True)
checks['explicitFallbackRecorded']=len(calls)==1 and c['runtimeFallback']['from']=='neyvia-agent' and c['runtimeFallback']['to']=='codex'
d=b._run_agent_chat({**p,'exactRoute':True,'allowRuntimeFallback':True},allow_mutation=True)
checks['exactRouteOverridesFallback']=len(calls)==1 and d['status']=='failed'
print(json.dumps(checks))
`,root],{env:{...process.env,PYTHONPATH:path.resolve('src')},encoding:'utf8',timeout:30000});
  assert.equal(run.status,0,run.stderr||run.error?.message);const checks=JSON.parse(run.stdout);for(const [key,value] of Object.entries(checks))assert.equal(value,true,key);
  console.log('AGENT_ROUTE_BOUNDARIES_VERIFIED',JSON.stringify(checks));
}finally{if(path.dirname(path.resolve(root))===path.resolve(tmpdir())&&path.basename(root).startsWith('neyvia-chat-route-'))rmSync(root,{recursive:true,force:true});}
