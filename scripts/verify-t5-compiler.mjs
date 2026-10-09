// Real MCP tools and real scoped file effects; no Python test framework.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const repo = process.cwd();
const python = 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
const code = String.raw`
import json,sys,uuid
from pathlib import Path
from grant_agent.neyvia_mcp_stdio import CompactNeyviaMCPServer
root=Path(sys.argv[1])/uuid.uuid4().hex
root.mkdir(parents=True)
(root/'proof.txt').write_text('compiler cobalt orchard',encoding='utf-8')
server=CompactNeyviaMCPServer(root,permission_mode='workspace',session_id='T5-compiler-real')
checks=[]
receipts=[]
def rpc(name,args):
 answer=server.handle({'jsonrpc':'2.0','id':len(receipts)+1,'method':'tools/call','params':{'name':name,'arguments':args}})
 if 'error' in answer:raise ValueError(answer['error']['message'])
 value=answer['result']['structuredContent']
 while isinstance(value,dict) and 'tool' in value and isinstance(value.get('result'),dict):
  if value.get('ok') is False:raise ValueError(value.get('error') or str(value))
  value=value['result']
 receipts.append({'tool':name,'args':args,'result':value})
 return value
def require(value,label):
 if not value:raise AssertionError(label)
 checks.append(label)
def rejected(fn,label):
 try:fn()
 except Exception as exc:
  checks.append(label);receipts.append({'rejection':label,'error':str(exc)});return
 raise AssertionError(label+' was accepted')
inputs={'path':'proof.txt','content':'compiler cobalt orchard'}
def ordinary(choice,procedure='replace-and-read',chosen=inputs):
 run=rpc('neyvia.manual.run',{'id':'workspace','chapter':'files','procedure':procedure,'inputs':chosen})
 require(run['status']=='judge','ordinary procedure reaches real JUDGE')
 run=rpc('neyvia.manual.run',{'id':'workspace','chapter':'files','procedure':procedure,'runId':run['runId'],'decisions':{run['judge']['id']:choice}})
 require(run['status']=='completed','ordinary procedure completes through gateway')
 return run
for _ in range(3):ordinary('replace')
fixed=rpc('neyvia.manual.compile',{'id':'workspace','chapter':'files','procedure':'replace-and-read','inputs':inputs,'minRuns':3})
require(fixed['fixedDecisions']=={'replace':'replace'} and fixed['zeroToken'],'three grounded identical runs specialize guarded JUDGE')
compiled=rpc('neyvia.manual.script.run',{'scriptId':fixed['scriptId'],'inputs':inputs})
require(compiled['status']=='completed' and compiled['zeroToken'] and compiled['modelCalls']==0 and compiled['checks'][0]['passed'],'compiled artifact performs real checked write with zero model calls')
require((root/'proof.txt').read_text()=='compiler cobalt orchard','compiled artifact verified actual disk bytes')
rejected(lambda:rpc('neyvia.manual.script.run',{'scriptId':fixed['scriptId'],'inputs':{'path':'proof.txt','content':'new unlearned bytes'}}),'unlearned inputs rejected before effects')
rejected(lambda:rpc('neyvia.manual.script.run',{'scriptId':fixed['scriptId'],'inputs':inputs,'scopeTools':['workspace.read']}),'compiled artifact retains nested tool restriction')
server=CompactNeyviaMCPServer(root,read_only=True,session_id='T5-compiler-denied')
denied=rpc('neyvia.manual.script.run',{'scriptId':fixed['scriptId'],'inputs':inputs})
require(denied['status']=='failed' and (root/'proof.txt').read_text()=='compiler cobalt orchard','read-only MCP caller cannot gain write authority from compiled artifact')
server=CompactNeyviaMCPServer(root,permission_mode='workspace',session_id='T5-compiler-real')
(root/'proof.txt').write_text('concurrent changed state',encoding='utf-8')
guard=rpc('neyvia.manual.script.run',{'scriptId':fixed['scriptId'],'inputs':inputs})
require(guard['status']=='judge' and guard['compiledGuardEscalations']==['replace'] and not guard['zeroToken'],'changed observation restores JUDGE before mutation')
rejected(lambda:rpc('neyvia.manual.run',{'id':'workspace','chapter':'files','procedure':'replace-and-read','runId':guard['runId'],'decisions':{'replace':'replace'}}),'ordinary runner cannot resume a compiled run')
guard_done=rpc('neyvia.manual.script.run',{'scriptId':fixed['scriptId'],'runId':guard['runId'],'decisions':{'replace':'leave'}})
require(guard_done['status']=='completed' and (root/'proof.txt').read_text()=='concurrent changed state','explicit guarded resume leaves concurrent bytes intact')
(root/'proof.txt').write_text('compiler cobalt orchard',encoding='utf-8')
for _ in range(3):ordinary('leave')
rejected(lambda:rpc('neyvia.manual.script.run',{'scriptId':fixed['scriptId'],'inputs':inputs}),'new varied branch evidence invalidates earlier specialization')
variable=rpc('neyvia.manual.compile',{'id':'workspace','chapter':'files','procedure':'replace-and-read','inputs':inputs,'minRuns':3})
require(variable['variableJudges']==['replace'] and not variable['fixedDecisions'],'branches that varied remain explicit JUDGE')
run=rpc('neyvia.manual.script.run',{'scriptId':variable['scriptId'],'inputs':inputs})
require(run['status']=='judge','variable artifact stops at actual branch')
run=rpc('neyvia.manual.script.run',{'scriptId':variable['scriptId'],'runId':run['runId'],'decisions':{'replace':'replace'}})
require(run['status']=='completed' and run['checks'][0]['passed'],'variable artifact resumes through original executable verifier')
# Exercise first-step judgement via a real quarantined, reviewed local revision.
loaded=rpc('neyvia.manual.load',{'id':'workspace','chapter':'files'})
judge_first={'goal':'Review then verify a grounded file','inputs':{'type':'object','properties':{'path':{'type':'string'},'phrase':{'type':'string'}},'required':['path','phrase'],'additionalProperties':False},'steps':[{'judge':'replace'},{'action':'workspace.read','args':{'path':{'$input':'path'}},'save':'file','check':'has-text'}]}
patch=rpc('neyvia.manual.frontier',{'id':'workspace','note':'Disposable compiler journey: first-step JUDGE','observed':{'receipt':'T5 compiler native runs'},'operations':[{'op':'add','path':'/chapters/files/procedures/compiler-judge-first','value':judge_first}]})
promoted=rpc('neyvia.manual.patch.apply',{'id':'workspace','patchId':patch['patchId'],'expectedSha256':loaded['sha256'],'approved':True,'reviewer':'T5 disposable-fixture verifier','evidence':['scripts/verify-t5-compiler.mjs']})
require(promoted['ok'],'disposable grounded manual revision promoted through actual tool')
rejected(lambda:rpc('neyvia.manual.script.run',{'scriptId':variable['scriptId'],'inputs':inputs}),'manual revision invalidates stale script hash')
judge_inputs={'path':'proof.txt','phrase':'cobalt orchard'}
for _ in range(3):ordinary('leave','compiler-judge-first',judge_inputs)
first=rpc('neyvia.manual.compile',{'id':'workspace','chapter':'files','procedure':'compiler-judge-first','inputs':judge_inputs,'minRuns':3})
done=rpc('neyvia.manual.script.run',{'scriptId':first['scriptId'],'inputs':judge_inputs})
require(done['status']=='completed' and done['zeroToken'],'first-step JUDGE chronology compiles and executes')
indexed=rpc('neyvia.manual.compiled',{'id':'workspace'})
require(len(indexed['scripts'])==3 and sum(row['stale'] for row in indexed['scripts'])==2,'compiled index reports active and stale artifacts')
print(json.dumps({'passed':True,'root':str(root),'checks':checks,'fixedScript':fixed['scriptId'],'variableScript':variable['scriptId'],'judgeFirstScript':first['scriptId'],'receipts':receipts,'modelCalls':0}))
`;
const evidenceRoot = path.join(repo, 'scripts', 'evidence', 'T5-compiler-runs');
fs.mkdirSync(evidenceRoot, {recursive: true});
const run = spawnSync(python, ['-c', code, evidenceRoot], {
  cwd: repo, env: {...process.env, PYTHONPATH: path.join(repo, 'src')},
  encoding: 'utf8', timeout: 180000, maxBuffer: 8 * 1024 * 1024,
});
assert.equal(run.status, 0, run.stderr || run.stdout);
const proof = JSON.parse(run.stdout.trim());
fs.writeFileSync(path.join(repo, 'scripts', 'evidence', 'T5-compiler.json'), JSON.stringify(proof, null, 2) + '\n');
console.log(JSON.stringify({passed: proof.passed, root: proof.root, checks: proof.checks}));
