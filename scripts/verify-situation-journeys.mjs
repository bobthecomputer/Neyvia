import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';

const repo=process.cwd(), root=mkdtempSync(path.join(tmpdir(),'neyvia-journey-'));
try {
 const run=spawnSync(resolveNeyviaPython(repo).python,['-c',String.raw`
import json,sys
from pathlib import Path
from types import SimpleNamespace
from grant_agent.neyvia_mcp_stdio import CompactNeyviaMCPServer
from grant_agent.situation_interface import SituationStore
from grant_agent.ui_graph import UiNode,Bounds
r=Path(sys.argv[1]); c=CompactNeyviaMCPServer(r,session_id='journey-proof',native_mutation_tools=['workspace.browser'],situation_interface=True); s=c.server
state={'items':0,'actions':0,'reloads':0,'ambiguous':False}; url='http://127.0.0.1:4173/control'
page=SimpleNamespace(url=url,evaluate=lambda script:1)
def reload(*,wait_until,timeout):state['reloads']+=1
page.reload=reload;s.ui_tools.attached_page=page
def observe(page):
 nodes=[UiNode(id='add',role='button',name='Add item',actions=('click',),bounds=Bounds(2,2,80,24))]
 if state['ambiguous']:nodes.append(UiNode(id='add-duplicate',role='button',name='Add item',actions=('click',),bounds=Bounds(2,28,80,24)))
 for i in range(state['items']):nodes.append(UiNode(id='item-'+str(i),role='text',name='Saved item '+str(i+1),bounds=Bounds(2,30+i*20,100,16)))
 s.ui_tools.observer.ingest_nodes(nodes,url=page.url,source='journey-test')
s.ui_tools.observe_page=observe
def action(args):
 state['actions']+=1
 if args['arguments']['id']=='add':state['items']+=1
 return {'ok':True,'status':'clicked','actionReceiptPath':'synthetic-receipt'}
s._run_workspace_browser=action
store=SituationStore(r,'journey-proof');store.define('Create and preserve one list item',[],['One item appears and survives reload'])
browser=s.situations
initial=browser.call('observe','journey-proof',{},may_change=True);before=store.frame()['frameId']
checks=[{'kind':'count','role':'button','name':'Add item','equals':1},
 {'kind':'text_contains','text':'Saved item 1','contains':False},
 {'kind':'url_equals','value':url}]
assertion=browser.call('assert','journey-proof',{'checks':checks},may_change=True)
assertion_after=browser.call('observe','journey-proof',{},may_change=True);after=store.frame()['frameId']
effect_checks=[{'kind':'added','role':'text','name':'Saved item 1','equals':1},
 {'kind':'count','role':'text','name':'Saved item 1','equals':1},
 {'kind':'text_contains','text':'Saved item 1','contains':True},
 {'kind':'url_contains','value':'/control'}]
saved=None
journey={'operation':'save','journeyId':'one-item','sourceDigest':'sha256:source-v1',
 'steps':[{'target':{'role':'button','name':'Add item'},'action':'click','args':{},
 'assertions':[{'kind':'count','role':'text','name':'Saved item 1','equals':1}]}],
 'acceptance':[{'kind':'count','role':'text','name':'Saved item 1','equals':1},
 {'kind':'text_contains','text':'Saved item 1','contains':True}]}
saved_journey=browser.call('journey','journey-proof',journey)
stale_source=None
try: browser.call('journey','journey-proof',{**journey,'operation':'replay','runId':'wrong-source','sourceDigest':'sha256:source-v2'},may_change=True)
except Exception as e: stale_source=str(e)
replay=browser.call('journey','journey-proof',{'operation':'replay','journeyId':'one-item','runId':'first-run',
 'sourceDigest':'sha256:source-v1','reload':True,
 'reloadAssertions':[{'kind':'count','role':'text','name':'Saved item 1','equals':1},
 {'kind':'text_contains','text':'Saved item 1','contains':True}]},may_change=True)
saved=browser.call('assert','journey-proof',{'checks':effect_checks,'beforeFrameId':initial['frameId']},may_change=True)
resumed=browser.call('journey','journey-proof',{'operation':'replay','journeyId':'one-item','runId':'first-run',
 'sourceDigest':'sha256:source-v1','reload':True,
 'reloadAssertions':[{'kind':'count','role':'text','name':'Saved item 1','equals':1}]},may_change=True)
persisted=SituationStore(r,'journey-proof').journey_run('one-item','first-run')
retrieved=browser.call('journey','journey-proof',{'operation':'inspect','journeyId':'one-item','runId':'first-run'})
ambiguous=None
before_remove=browser.call('observe','journey-proof',{},may_change=True);remove_before=store.frame()['frameId']
state['items']=0
removed=browser.call('assert','journey-proof',{'checks':[{'kind':'removed','role':'text','name':'Saved item 1','equals':1}],
 'beforeFrameId':remove_before},may_change=True)
failing=browser.call('journey','journey-proof',{'operation':'save','journeyId':'wrong-acceptance','sourceDigest':'sha256:source-v1',
 'steps':[{'target':{'role':'button','name':'Add item'},'action':'click','args':{},
 'assertions':[{'kind':'count','role':'text','name':'Saved item 2','equals':1}]}],
 'acceptance':[{'kind':'count','role':'text','name':'Saved item 2','equals':1}]})
failed_run=browser.call('journey','journey-proof',{'operation':'replay','journeyId':'wrong-acceptance','runId':'failed-run',
 'sourceDigest':'sha256:source-v1'},may_change=True)
state['ambiguous']=True
fresh=browser.call('observe','journey-proof',{},may_change=True); frame=store.frame()
try:browser.call('change','journey-proof',{'frameId':frame['frameId'],'target':{'role':'button','name':'Add item'},'action':'click','actionId':'ambiguous','expected':{'field':'name','equals':'Add item'}},may_change=True)
except Exception as e:ambiguous=str(e)
print(json.dumps({'assertion':assertion,'effectChecks':saved,'initialFrame':initial['frameId'],'afterFrame':after,
 'savedJourney':saved_journey,'staleSource':stale_source,'replay':replay,'persisted':persisted,
 'resumed':resumed,'removed':removed,'retrieved':retrieved,'failedRun':failed_run,
 'actions':state['actions'],'reloads':state['reloads'],'ambiguous':ambiguous}))
`,root],{env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:60000,maxBuffer:2e6});
 assert.equal(run.status,0,run.stderr);const out=JSON.parse(run.stdout);
 assert.equal(out.assertion.matched,true);assert.equal(out.assertion.taskComplete,true);
 assert(out.assertion.checks.every(c=>'observed' in c));assert.equal(out.effectChecks.matched,true);
 assert.notEqual(out.initialFrame,out.afterFrame);assert.equal(out.savedJourney.status,'saved');
 assert.match(out.staleSource,/Source digest/);assert.equal(out.replay.accepted,true,JSON.stringify(out.replay));
 assert.equal(out.replay.steps[0].beforeFrameId!=null,true);assert.equal(out.replay.steps[0].afterFrameId!=null,true);
 assert.equal(out.replay.reloadAcceptance.matched,true);assert.equal(out.reloads,1);assert.equal(out.actions,2);
 assert.equal(out.resumed.accepted,true,JSON.stringify(out.resumed));assert.equal(out.resumed.steps[0].result.status,'previous_action_rechecked');
 assert.equal(out.removed.matched,true,JSON.stringify(out.removed));assert.equal(out.removed.checks[0].observed,1);
 assert.equal(out.persisted.accepted,true);assert.equal(out.persisted.taskComplete,true);
 assert.equal(out.retrieved.accepted,true);
 assert.equal(out.failedRun.status,'failed');assert.equal(out.failedRun.accepted,false);assert.equal(out.failedRun.taskComplete,undefined);
 assert.equal(out.actions,2);assert.equal(out.reloads,1);
 assert.match(out.ambiguous,/absent or ambiguous/);
 console.log(JSON.stringify({status:'passed',checks:['fresh effect assertions','role/name target fail-closed','visible text/count/URL','added-object delta','saved journey replay','source digest binding','bounded reload persistence','durable run receipt'],actionExecutions:out.actions,reloadCalls:out.reloads}));
} finally {rmSync(root,{recursive:true,force:true});}
