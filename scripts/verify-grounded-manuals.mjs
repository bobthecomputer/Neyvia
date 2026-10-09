import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
const repo=process.cwd();
const python=process.env.NEYVIA_PYTHON || 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
let code=String.raw`
import copy,json,os,sys,uuid
from pathlib import Path
from grant_agent.neyvia_mcp_stdio import CompactNeyviaMCPServer
from grant_agent.neyvia_manuals import get_manual,validate,unwrap,records
from grant_agent.native_tools import NativeToolRegistry
root=Path(sys.argv[1])/uuid.uuid4().hex; root.mkdir(parents=True,exist_ok=True)
(root/'proof.txt').write_bytes(b'cobalt orchard 739\n')
server=CompactNeyviaMCPServer(root,read_only=True,session_id='grounded-verification')
registry=server._gateway().native
def rpc(name,args):
 answer=server.handle({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}})
 if 'error' in answer:raise ValueError(answer['error']['message'])
 value=answer['result']['structuredContent']
 while isinstance(value,dict) and 'tool' in value and isinstance(value.get('result'),dict):value=value['result']
 return value
checks=[]
def require(condition,label):
 if not condition:raise AssertionError(label)
 checks.append(label)
validation=rpc('neyvia.manual.validate',{})
require(len(validation['manuals'])==len(records()),'all registered manuals grounded')
loaded=rpc('neyvia.manual.load',{'id':'workspace','chapter':'files'})
require('P read-and-confirm(' in loaded['text'],'rendered CL data procedure')
observed=rpc('neyvia.manual.observe',{'id':'workspace','chapter':'files','state':'current','inputs':{'path':'proof.txt'}})
require(observed['observed']['content']=='cobalt orchard 739\n','observer reads real bytes')
read=rpc('neyvia.manual.run',{'id':'workspace','chapter':'files','procedure':'read-and-confirm','inputs':{'path':'proof.txt','phrase':'cobalt orchard'}})
require(read['status']=='completed' and read['checks'][0]['passed'],'deterministic action and fresh verifier')
stopped=rpc('neyvia.manual.run',{'id':'workspace','chapter':'files','procedure':'replace-and-read','inputs':{'path':'proof.txt','content':'cobalt orchard 739\n'}})
require(stopped['status']=='judge' and stopped['nextStep']==1,'judge stops before later steps')
try:
 rpc('neyvia.manual.run',{'id':'workspace','chapter':'files','procedure':'replace-and-read','runId':stopped['runId'],'decisions':{'replace':'invented'}})
 raise AssertionError('invalid decision accepted')
except ValueError:checks.append('invalid judge option rejected')
resumed=rpc('neyvia.manual.run',{'id':'workspace','chapter':'files','procedure':'replace-and-read','runId':stopped['runId'],'decisions':{'replace':'leave'}})
require(resumed['status']=='completed' and resumed['decisions']=={'replace':'leave'},'resume retains explicit branch decision')
events=[json.loads(line) for line in (root/'.neyvia/manual-runs.jsonl').read_text(encoding='utf-8').splitlines()]
run_events=[row for row in events if row['runId']==stopped['runId']]
require(sum(row['event']=='action' for row in run_events)==1,'resume does not replay completed actions')
require(any(row['event']=='decision' for row in run_events),'branch decisions are logged')
failed=rpc('neyvia.manual.run',{'id':'workspace','chapter':'files','procedure':'read-and-confirm','inputs':{'path':'proof.txt','phrase':'absent'}})
require(failed['status']=='failed' and not failed['checks'][0]['passed'],'failed verifier halts and retains evidence')
(root/'denied.txt').write_bytes(b'original protected bytes')
judge=rpc('neyvia.manual.run',{'id':'workspace','chapter':'files','procedure':'replace-and-read','inputs':{'path':'denied.txt','content':'must not exist'}})
denied=rpc('neyvia.manual.run',{'id':'workspace','chapter':'files','procedure':'replace-and-read','runId':judge['runId'],'decisions':{'replace':'replace'}})
require(denied['status']=='failed' and (root/'denied.txt').read_bytes()==b'original protected bytes','manual cannot bypass read-only nested mutation gate')
patch=rpc('neyvia.manual.frontier',{'id':'workspace','note':'unmapped external path handling','observed':{'denied':True}})
patches=rpc('neyvia.manual.patches',{'id':'workspace'})
require(patch['status']=='quarantined' and any(row['patchId']==patch['patchId'] for row in patches['patches']),'frontier stays quarantined and listed')
require(get_manual('workspace')[1]==loaded['sha256'],'patch does not alter live manual')
try:
 rpc('neyvia.manual.run',{'id':'workspace','chapter':'files','procedure':'read-and-confirm','inputs':{'path':'proof.txt','phrase':'cobalt orchard'},'scopeTools':['neyvia.time.now']})
 raise AssertionError('caller scope bypass accepted')
except ValueError:checks.append('nested tool restriction checked before any procedure effects')
try:
 rpc('neyvia.manual.observe',{'id':'workspace','chapter':'files','state':'current','inputs':{'path':'proof.txt'},'scopeTools':['neyvia.time.now']})
 raise AssertionError('observer scope bypass accepted')
except ValueError:checks.append('observer retains caller nested-tool restriction')
for mutation,label in [
 (lambda data:data['chapters']['files']['actions']['workspace.read'].update(tool='neyvia.no-such-tool'),'missing tool fails grounding'),
 (lambda data:data['schemas']['workspace.read'].update(required=[]),'schema drift fails grounding'),
 (lambda data:data['chapters']['files']['procedures']['read-and-confirm']['steps'][0]['args'].update(path=123),'invalid typed step rejected'),
 (lambda data:data['chapters']['files']['checks']['has-text'].update(tool='workspace.write'),'mutating verifier rejected'),
]:
 data=copy.deepcopy(get_manual('workspace')[2]);mutation(data)
 try:validate(data,registry);raise AssertionError(label+' accepted')
 except (ValueError,KeyError):checks.append(label)
 except Exception as exc:
  from jsonschema import ValidationError
  if not isinstance(exc,ValidationError):raise
  checks.append(label)
try:
 rpc('neyvia.manual.observe',{'id':'workspace','chapter':'files','state':'current','inputs':{'path':4}})
 raise AssertionError('invalid observe input accepted')
except Exception as exc:
 require('invalid observe input accepted' not in str(exc),'observer inputs validated')
write_server=CompactNeyviaMCPServer(root,permission_mode='workspace',session_id='authorized-write')
server=write_server
(root/'written.txt').write_bytes(b'original writable bytes')
judge=rpc('neyvia.manual.run',{'id':'workspace','chapter':'files','procedure':'replace-and-read','inputs':{'path':'written.txt','content':'actual authorized bytes'}})
written=rpc('neyvia.manual.run',{'id':'workspace','chapter':'files','procedure':'replace-and-read','runId':judge['runId'],'decisions':{'replace':'replace'}})
require(written['status']=='completed' and (root/'written.txt').read_text()=='actual authorized bytes' and written['checks'][0]['passed'],'authorized write uses original gateway and reread verifier')
domain={}
def domain_run(identity,procedure,inputs,chapter='overview'):
 value=rpc('neyvia.manual.run',{'id':identity,'chapter':chapter,'procedure':procedure,'inputs':inputs})
 choices={'notes':{'replace-note':'replace'},'files':{'tidy':'move'},'onboarding':{'setup-choices':'save'},'mobile-studio':{'phone-frame':'preview'},'neyvia':{'density-choice':'apply'},'awareness':{'intent':'ready'},'hill-climb':{'candidate':'compare'},'workspace':{'command-scope':'run'}}
 while value['status']=='judge':
  value=rpc('neyvia.manual.run',{'id':identity,'chapter':chapter,'procedure':procedure,'runId':value['runId'],'decisions':{value['judge']['id']:choices[identity][value['judge']['id']]}})
 require(value['status']=='completed',identity+' real domain procedure/checks')
 domain[identity]=value
 return value
os.environ['NEYVIA_NOTES_DIR']=str(root/'notes');(root/'notes').mkdir(exist_ok=True)
(root/'notes'/'existing.md').write_bytes(b'# Original\n\nOriginal body\n')
note=registry.call('neyvia.notes.read',{'path':'existing.md'})['result']
domain_run('notes','write-and-pin',{'path':'existing.md','body':'# Grounded\n\nActual updated body #proof','expectedModified':note['modified']})
(root/'rename-source.txt').write_bytes(b'rename proof')
domain_run('files','rename-and-check',{'from':str(root/'rename-source.txt'),'to':str(root/'renamed-proof.txt'),'name':'renamed-proof.txt'})
domain_run('onboarding','save-choices',{'interests':['coding'],'completed':True})
device=registry.describe('neyvia.mobile.preview')['inputSchema']['properties']['device']['enum'][0]
domain_run('mobile-studio','set-phone-frame',{'device':device,'orientation':'landscape'})
from PIL import Image
Image.new('RGB',(17,19),(30,140,50)).save(root/'domain.png')
domain_run('image-studio','open-inspect',{'source':str(root/'domain.png'),'width':17})
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
writer=PdfWriter();page=writer.add_blank_page(width=300,height=300)
font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 20 250 Td (Grounded PDF orchard evidence) Tj ET')
page[NameObject('/Contents')]=writer._add_object(stream)
with (root/'proof.pdf').open('wb') as handle:writer.write(handle)
domain_run('pdf','open-and-read',{'source':'proof.pdf','page':1,'phrase':'orchard evidence'})
from grant_agent.neyvia_workspace_tools import workspace_for
workspace_for(root).bus.put('sessions',{'fixture-chat':{'title':'Before'}})
domain_run('neyvia','rename-and-confirm',{'id':'fixture-chat','title':'Grounded session title'},chapter='sessions')
domain_run('neyvia','choose-density',{'level':'workshop'},chapter='settings')
domain_run('awareness','intent-template',{'text':'Rename the file and verify it without publishing.'})
domain_run('hill-climb','inspect-measurements',{})
server=CompactNeyviaMCPServer(root,permission_mode='full-access',session_id='terminal-proof')
domain_run('workspace','prove-terminal',{},chapter='terminal')
print(json.dumps({'passed':True,'checks':checks,'validation':validation,'readRun':read,'judgeRun':resumed,'deniedRun':denied,'writeRun':written,'patch':patch,'domains':domain}))
`;
if (process.argv.includes('--contracts-only')) {
  code=code.slice(0,code.indexOf('domain={}'))+'domain={}\n'+code.slice(code.indexOf("print(json.dumps({'passed':True"));
}
const run=spawnSync(python,['-c',code,path.join(os.tmpdir(),'neyvia-manual-contracts')],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:90000});
assert.equal(run.status,0,run.stderr || run.stdout);
const proof=JSON.parse(run.stdout.trim());
const receipt=process.argv.includes('--contracts-only')?'manual_first_contracts.json':'manual_first_execution.json';
fs.writeFileSync(path.join(repo,'docs/manuals',receipt),JSON.stringify(proof,null,2)+'\n');
console.log(JSON.stringify({passed:proof.passed,checks:proof.checks}));
