import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=process.cwd(), root=mkdtempSync(path.join(tmpdir(),'neyvia-intent-'));
try {
 const r=spawnSync(resolveNeyviaPython(repo).python,['-c',String.raw`
from grant_agent.neyvia_mcp import NeyviaMCPServer
from grant_agent.ui_graph import UiNode
from types import SimpleNamespace
import json,sys
s=NeyviaMCPServer(sys.argv[1]); state={'checked':False,'calls':0}
s.ui_tools.attached_page=SimpleNamespace(url='http://127.0.0.1:4173/control')
def observe(page):
 s.ui_tools.observer.ingest_nodes([UiNode(id='listening',role='checkbox',name='Continuous listening',states=('checked',) if state['checked'] else (),actions=('click',))],url=page.url)
s.ui_tools.observe_page=observe
def act(p):
 state['calls']+=1; state['checked']=True
 return {'ok':True,'status':'done'}
s._run_workspace_browser=act
intent={'semanticTarget':'Continuous listening','action':'click','acceptableIds':['listening'],'expectedTransition':{'field':'checked','from':False,'to':True}}
def run(i,authority=True):
 return s.handle({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'neyvia.workspace.intent','arguments':{'intent':i,'authority':{'granted':authority},'actionId':'a','missionId':'m'}}})
denied=run(intent,False); success=run(intent); state['checked']=False
wrong=run({**intent,'acceptableIds':['other']})
precondition=run({**intent,'expectedTransition':{'field':'checked','from':True,'to':False}})
print(json.dumps({'denied':denied,'success':success,'wrong':wrong,'precondition':precondition,'calls':state['calls']}))
`,root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8'});
 assert.equal(r.status,0,r.stderr); const out=JSON.parse(r.stdout);
 assert.equal(out.denied.result.isError,true);
 assert.equal(out.success.result?.isError,false,JSON.stringify(out.success));
 assert.equal(out.wrong.result.isError,true);
 assert.equal(out.precondition.result.isError,true);
 assert.equal(out.calls,1);
 console.log('INTENT_BROWSER_INTEGRATION_VERIFIED: production MCP dispatch and resident graph, success, authority, identity and transition guards');
} finally {rmSync(root,{recursive:true,force:true});}
