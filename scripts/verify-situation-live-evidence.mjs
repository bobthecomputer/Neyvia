import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=process.cwd(),proof=path.join(repo,'proof/semantic-primitives');
const result=JSON.parse(readFileSync(path.join(proof,'situation-live-result.json')));
const effects=JSON.parse(readFileSync(path.join(proof,'situation-browser-effects.json')));
assert.equal(result.model,'gpt-5.6-luna');assert.equal(result.reasoningResolution.requestedEffort || result.reasoningResolution.requested || result.reasoningResolution.wireEffort,'medium');
assert.equal(result.policy.situationInterface,true);assert.equal(result.policy.modelVisibleToolCount,6);
assert.equal(effects.listening,true);assert.equal(effects.replacement,false);assert.equal(effects.events.length,1);assert.equal(effects.events[0].control,'listening');
const checked=spawnSync(resolveNeyviaPython(repo).python,['-c',String.raw`
import json,sys,hashlib
from pathlib import Path
from grant_agent.action_receipts import NativeActionStore
from grant_agent.situation_interface import SituationStore
r=Path(sys.argv[1]);work=sys.argv[2];s=NativeActionStore(r,'situation:'+work);a=s.inspect('enable-listening-once')
p=s._path('enable-listening-once').with_suffix('.result');out=json.loads(p.read_text());v=SituationStore(r,work);after=v.frame(out['toolResult']['after'])
print(json.dumps({'action':a,'result':out,'hashMatches':hashlib.sha256(json.dumps(out,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()==a['resultHash'],
 'controls':{o['name']:'checked' in o['states'] for o in after['objects'] if o['role']=='checkbox'},'source':after['source'],'actions':s.list()['actions']}))
`,result.workspaceRoot,result.sessionId],{env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:20000});
assert.equal(checked.status,0,checked.stderr);const durable=JSON.parse(checked.stdout);
assert(durable.hashMatches);assert.equal(durable.action.status,'completed');assert.equal(durable.result.status,'verified');assert.equal(durable.result.toolResult.verification.matched,true);
assert.equal(durable.result.toolResult.taskComplete,false);assert.equal(durable.controls['Continuous listening'],true);assert.equal(durable.controls['Replace microphone device'],false);
assert.equal(durable.source,'cdp-ax');assert.equal(durable.actions.length,1);
const report={status:'verified',scope:'Real Luna through the production situation gateway against a disposable live browser page',
 model:result.model,effort:'medium',actionReceipt:durable.action,independentEventCount:effects.events.length,controls:durable.controls,
 modelRunReceipt:result.receiptPath,durationMs:result.durationMs,usage:result.usage,
 limitations:['No real microphone or hardware claim','No comparison against another harness or larger model','Transport token usage remains high']};
writeFileSync(path.join(proof,'situation-live-verification.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({status:report.status,model:result.model,independentEventCount:effects.events.length,controls:durable.controls,durationMs:result.durationMs}));
