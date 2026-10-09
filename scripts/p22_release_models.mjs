import assert from 'node:assert/strict';
if (process.argv[2]==='sdk-client') {
  const {createNeyviaClient,NeyviaError}=await import('../packages/neyvia-sdk/index.js');
  const origin=process.argv[3]; globalThis.location={origin,href:origin+'/'};
  let options;
  const sdk=createNeyviaClient({baseUrl:origin,appId:'owned',fetchImpl:(url,init)=>{options=init;return fetch(url,init);}});
  const answer=await sdk.remember({key:'cue',content:'雪🙂',requestId:'once',sessionId:'session'});
  assert.equal(answer.body.command,'memory_remember_command');
  assert.equal(answer.body.payload.content,'雪🙂');
  assert.equal(answer.body.payload.exportPolicy,'local');
  assert.equal(answer.body.payload.sessionId,'session');
  assert.equal(answer.app,'owned'); assert.equal(options.credentials,'same-origin');
  const manual=await sdk.manual('notes',{chapter:'overview',level:2});
  assert.deepEqual(manual.body,{tool:'neyvia.cl.describe',arguments:{layer:'notes',level:2,chapter:'overview'}});
  for (const route of ['https://outside.invalid','http://127.0.0.1:47881']) {
    assert.throws(()=>createNeyviaClient({baseUrl:route}),/same origin/);
  }
  await assert.rejects(sdk.command('deny'),error=>error instanceof NeyviaError && error.code==='login_required' && error.status===401);
  console.log(JSON.stringify({ok:true,exactRequestDelivered:true,localExportPreserved:true,sameOriginEnforced:true,typedDenial:true}));
}
import * as view from '../web/src/neyvia/next/agentview/nxAgentViewModel.js';
import {sessionLabel, keepSelection} from '../web/src/neyvia/next/nxGameDevModel.js';
import {buildQueueTimeline} from '../web/src/neyvia/imageProviderAdapters.js';
import {settleStaleHistoryItem} from '../web/src/neyvia/imagePlaygroundState.js';
if (process.argv[2]!=='sdk-client') {
assert.equal(view.pollDelay({visible:false}), null);
assert.ok(view.pollDelay({quiet:100}) > view.pollDelay({quiet:0}));
const full=view.applyFrame(view.emptyStack(),{kind:'full',v:1,w:20,h:10,patches:[{x:0,y:0,w:20,h:10,src:'owned'}]});
assert.equal(full.v,1);
assert.equal(view.applyFrame(full,{kind:'delta',base:9,v:10,w:20,h:10,patches:[]}).needsFull,true);
assert.equal(view.applyFrame(full,{kind:'delta',base:1,v:2,w:20,h:10,patches:[{x:1,y:1,w:2,h:2,src:'changed'}]}).layers.length,2);
assert.deepEqual(view.feedbackPayload({run:'owned',stack:full,action:'picked',point:{x:.2,y:.4},text:' Look here '}),
  {run:'owned',text:'Look here',v:1,action:'picked',point:{x:.2,y:.4}});
assert.equal(view.feedbackPayload({run:'owned',text:'  '}),null);
assert.equal(sessionLabel({context:'Edit',environment:'browser-null'}),'Browser 3D editor · no 3D picture');
assert.equal(keepSelection('old',[{sessionId:'old',environment:'browser-null',status:'disconnected',projectPath:'p',context:'Edit'},
  {sessionId:'new',environment:'browser-null',status:'connected',projectPath:'p',context:'Edit'}]),'new');
const failed=buildQueueTimeline({queuedAt:'q',startedAt:'s',completedAt:'c',outcome:'failed'});
assert.ok(failed.some(row=>row.severity==='bad'));
assert.ok(!failed.some(row=>row.severity==='good'));
assert.equal(failed.find(row=>row.stage==='artifact written').at,'');
assert.equal(settleStaleHistoryItem({status:'running'}).status,'failed');
console.log(JSON.stringify({ok:true,frameMismatchRequestsFull:true,feedbackBound:true,gameSelectionKept:true,failedQueueNeverVerified:true}));
}
