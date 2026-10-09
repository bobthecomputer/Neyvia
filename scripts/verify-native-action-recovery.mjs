import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
import {createHash} from 'node:crypto';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const python=resolveNeyviaPython(repo).python;
const root=mkdtempSync(path.join(tmpdir(),'neyvia-actions-'));
try {
 const result=spawnSync(python,['-c',String.raw`
import json,os,sys,subprocess,time
from pathlib import Path
from grant_agent.action_receipts import NativeActionStore
from grant_agent.neyvia_agent import NeyviaToolGateway
from grant_agent.neyvia_mcp_stdio import CompactNeyviaMCPServer
root=Path(sys.argv[1]); counter=root/'counter';counter.write_text('0')
g=NeyviaToolGateway(root,allow_mutations=True,action_scope='fixture')
def change(args):
    counter.write_text(str(int(counter.read_text())+1))
    return {'changed':True}
g.native._handlers['skill.live.iterate']=change
args={'path':'fixture.md','content':'updated','sessionId':'test'}
assert g.call_native('skill.live.iterate',args)['status']=='action_id_required'
first=g.call_native('skill.live.iterate',args,action_id='update-fixture')
assert first['ok'] and not first['duplicateSuppressed'] and counter.read_text()=='1'
second=g.call_native('skill.live.iterate',args,action_id='update-fixture')
assert second['ok'] and second['duplicateSuppressed'] and counter.read_text()=='1'
assert second['receipt_id']==first['receipt_id']
assert g.call_native('skill.live.iterate',{**args,'content':'different'},action_id='update-fixture')['status']=='action_conflict'
# A new gateway/process context does not forget action identity.
fresh=NeyviaToolGateway(root,allow_mutations=True,action_scope='fixture')
fresh.native._handlers['skill.live.iterate']=lambda _: (_ for _ in ()).throw(AssertionError('replayed'))
assert fresh.call_native('skill.live.iterate',args,action_id='update-fixture')['duplicateSuppressed']
assert NativeActionStore(root,'other-mission').inspect('update-fixture')['status']=='not_started'
# The real MCP request boundary forwards action IDs and exposes read-only status.
server=CompactNeyviaMCPServer(root,session_id='fixture');server._native=g
request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'neyvia.native.call','arguments':{'toolId':'skill.live.iterate','arguments':args,'actionId':'update-fixture'}}}
wire=server.handle(request)['result']['structuredContent']
assert wire['duplicateSuppressed'] and counter.read_text()=='1'
inspected=server.handle({**request,'params':{'name':'neyvia.actions.inspect','arguments':{'actionId':'update-fixture'}}})['result']['structuredContent']
assert inspected['status']=='completed'
listing=server.handle({**request,'params':{'name':'neyvia.actions.inspect','arguments':{}}})['result']['structuredContent']
assert any(row['actionId']=='update-fixture' and row['status']=='completed' for row in listing['actions'])
assert listing['nextCursor'] is None
# Stable parent scope does not let an action ID target a different workspace.
moved=NeyviaToolGateway(root/'moved',allow_mutations=True,action_scope='fixture',action_root=root)
assert moved.call_native('skill.live.iterate',args,action_id='update-fixture')['status']=='action_conflict'
readonly=NeyviaToolGateway(root,allow_mutations=False,action_scope='fixture')
assert readonly.call_native('skill.live.iterate',args,action_id='update-fixture')['status']=='approval_required'
scoped=NeyviaToolGateway(root,allow_mutations=True,action_scope='fixture',allowed_mutation_tools={'orchestration.compile'})
assert scoped.call_native('skill.live.iterate',args,action_id='update-fixture')['status']=='mutation_outside_contract'
from grant_agent.neyvia_agent import _codex_neyvia_mcp_args
launch=_codex_neyvia_mcp_args(root,read_only=False,native_mutation_tools=('orchestration.compile',))
assert 'mcp_servers.neyvia.tools={"neyvia.native.call"={approval_mode="approve"}}' in launch
assert '--native-mutation-tool' in json.loads(next(x.split('=',1)[1] for x in launch if x.startswith('mcp_servers.neyvia.args=')))
assert not any('approval_mode="approve"' in x for x in _codex_neyvia_mcp_args(root,read_only=True))
# Simulate a process dying after the effect but before the result receipt.
crash_code="from pathlib import Path;from grant_agent.action_receipts import NativeActionStore;import sys,os;r=Path(sys.argv[1]);s=NativeActionStore(r,'crash');s.execute('one','fixture',{},lambda:((r/'crash-effect').write_text('done'),os._exit(23)))"
crashed=subprocess.run([sys.executable,'-c',crash_code,str(root)])
assert crashed.returncode==23 and (root/'crash-effect').read_text()=='done'
s=NativeActionStore(root,'crash')
assert s.execute('one','fixture',{},lambda: (_ for _ in ()).throw(AssertionError('replayed uncertain effect')))['status']=='action_uncertain'
# Simultaneous fresh processes may execute the same logical action only once.
parallel_code="""
from pathlib import Path
from grant_agent.action_receipts import NativeActionStore
import sys,time
r=Path(sys.argv[1]);s=NativeActionStore(r,'parallel')
def effect():
    p=r/'parallel-count'
    n=int(p.read_text()) if p.exists() else 0
    time.sleep(.3)
    p.write_text(str(n+1))
    return {'ok':True}
print(s.execute('one','fixture',{},effect)['duplicateSuppressed'])
"""
processes=[subprocess.Popen([sys.executable,'-c',parallel_code,str(root)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
outputs=[p.communicate(timeout=15) for p in processes]
assert all(p.returncode==0 for p in processes),outputs
assert sorted(o[0].strip() for o in outputs)==['False','True'] and (root/'parallel-count').read_text()=='1'
# Continuity writers must not steal a live lock merely because its mtime is old.
from grant_agent.continuity_policy import MissionContinuityStore
continuity=MissionContinuityStore(root)
continuity.create_or_update('mission',goal='keep durable state')
writer="from pathlib import Path;import sys;from grant_agent.continuity_policy import MissionContinuityStore;s=MissionContinuityStore(Path(sys.argv[1]));s.create_or_update('mission',patch={'nextAction':'child wrote'})"
with continuity._mission_lock('mission'):
    lock=continuity._record_path('mission').with_suffix('.json.lock')
    os.utime(lock,(time.time()-300,time.time()-300))
    other=subprocess.Popen([sys.executable,'-c',writer,str(root)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    time.sleep(.4)
    assert other.poll() is None and continuity.load('mission').get('nextAction')!='child wrote'
_,err=other.communicate(timeout=15)
assert other.returncode==0,err
assert continuity.load('mission')['nextAction']=='child wrote'
# Corrupted saved state never causes an automatic rerun.
action_path=Path(first['actionReceiptPath'])
action_path.with_suffix('.result').write_text('{}')
assert fresh.call_native('skill.live.iterate',args,action_id='update-fixture')['status']=='action_uncertain'
action_path.write_text('{')
try:
    fresh.call_native('skill.live.iterate',args,action_id='update-fixture')
    raise AssertionError('corrupt record accepted')
except ValueError: pass
print('NATIVE_ACTION_RECOVERY_VERIFIED: gateway and MCP replay suppression, conflict binding, cross-process concurrency, crash ambiguity, corruption, read-only authority')
`,root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:90000});
 assert.equal(result.status,0,result.stderr||result.stdout||result.error?.message);
 const evidence = result.stdout.trim();
 console.log(JSON.stringify({status:'verified', evidence, sha256:createHash('sha256').update(evidence).digest('hex')}));
} finally {rmSync(root,{recursive:true,force:true});}
