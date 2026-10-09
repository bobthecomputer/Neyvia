import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const python=resolveNeyviaPython(repo).python; const root=mkdtempSync(path.join(tmpdir(),'neyvia-gateway-'));
try { const result=spawnSync(python,['-c',String.raw`
import json,sys
from pathlib import Path
from grant_agent.neyvia_agent import NeyviaToolGateway
from grant_agent.neyvia_mcp_stdio import CompactNeyviaMCPServer
root=Path(sys.argv[1]); g=NeyviaToolGateway(root,allow_mutations=True,action_scope='gateway',allowed_mutation_tools={'skill.live.iterate'})
count=root/'count'; count.write_text('0')
def effect(_): count.write_text(str(int(count.read_text())+1)); return {'ok':True,'status':'completed','changed':True}
g.native._handlers['skill.live.iterate']=effect
args={'path':'fixture.md','content':'updated','sessionId':'s'}
first=g.call_native('skill.live.iterate',args,action_id='gateway-1'); checks={'first':first['ok'] and count.read_text()=='1' and first.get('operationStatus')=='unverified'}
fresh=NeyviaToolGateway(root,allow_mutations=True,action_scope='gateway',allowed_mutation_tools={'skill.live.iterate'}); fresh.native._handlers['skill.live.iterate']=lambda _: (_ for _ in ()).throw(AssertionError('replayed'))
second=fresh.call_native('skill.live.iterate',args,action_id='gateway-1'); checks['duplicate']=second.get('duplicateSuppressed') and count.read_text()=='1'
server=CompactNeyviaMCPServer(root,session_id='s'); server._native=fresh
wire=server.handle({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'neyvia.operations.inspect','arguments':{'operationId':'gateway-1:skill.live.iterate'}}})['result']['structuredContent']; checks['inspect']=wire.get('status',wire.get('operation',{}).get('status'))=='unverified'
g.native.call=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('effect uncertain'))
failed=g.call_native('skill.live.iterate',args,action_id='gateway-fail'); checks['uncertain']=failed.get('status')=='action_uncertain'
checks['recovery']=bool(g.recoveries.list()) and g.recoveries.list()[0]['retrySafety']=='requires_reconciliation'
g2=NeyviaToolGateway(root,allow_mutations=True,action_scope='gateway-false',allowed_mutation_tools={'skill.live.iterate'}); g2.native._handlers['skill.live.iterate']=lambda _: {'ok':False,'status':'failed','message':'refused'}
false_result=g2.call_native('skill.live.iterate',args,action_id='gateway-false'); checks['falseRecovery']=false_result['status']=='failed' and bool(g2.recoveries.list()) and g2.operations.list()['operations'][0]['status']=='failed'
print(json.dumps(checks,separators=(',',':')))
`,root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:90000}); assert.equal(result.status,0,result.stderr||result.stdout); const checks=JSON.parse(result.stdout.trim()); for(const [name,value] of Object.entries(checks)) assert.equal(value,true,name); console.log(JSON.stringify({status:'verified',checks})); }
finally {rmSync(root,{recursive:true,force:true});}
