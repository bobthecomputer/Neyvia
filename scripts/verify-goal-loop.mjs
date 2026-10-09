import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {mkdtemp, mkdir, writeFile, rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
const repo=process.cwd();
const custom='Preserve this exact custom system prompt. Execute the user task.';
async function scenario(mode) {
 const dir=await mkdtemp(path.join(os.tmpdir(),'neyvia-goal-'));
 await writeFile(path.join(dir,'instructions.txt'),custom);
 for(const file of ['a','b','c']) await writeFile(path.join(dir,file+'.txt'),file+' observed');
 let calls=0, violation='';
 const goal=(action,extra={})=>({tool:'neyvia_goal',args:{action,goal:'Inspect three files',acceptance:'All files checked',evidence:'',next_action:'Read next file',blocker:'',...extra}});
 const read=file=>({tool:'neyvia_workspace_read',args:{path:file+'.txt',max_chars:1000}});
 let sequence=[goal('start'),read('a'),{text:'I will inspect b next.'},read('b'),goal('progress',{evidence:'b observed',next_action:'Read c'}),{text:'I will inspect c next.'},read('c'),goal('complete',{evidence:'Read a, b, c; all inspected'}),{text:'Verified all three files.'}];
 if(mode==='late')sequence=[{text:'I will read a next.'},read('a'),goal('complete',{evidence:'a inspected'}),{text:'Done.'}];
 if(mode==='stalled')sequence=[goal('start'),{text:'I plan to work.'},{text:'I still plan to work.'},read('a'),goal('complete',{evidence:'The alternative read succeeded'}),{text:'Recovered and verified.'}];
 if(mode==='repeated')sequence=[goal('start'),...Array.from({length:4},()=>({text:'The same plan with no action.'}))];
 if(mode==='blocked')sequence=[goal('start'),goal('blocked',{blocker:'Required file unavailable'}),{text:'Blocked.'}];
 if(mode==='question')sequence=[goal('start'),{tool:'neyvia_ask_user',args:{question:'Which target?',options:['A','B'],context:'Need the target'}}];

 if(mode==='simple')sequence=[{text:'Hello.'}];
 if(mode==='timeout')sequence=[goal('start'),{hang:true}];
 const server=createServer(async(req,res)=>{
  let data='';for await(const c of req)data+=c;
  try {
   const body=JSON.parse(data); calls++;
   assert.deepEqual(body.messages.filter(m=>m.role==='system'||m.role==='developer').map(m=>m.content),[custom]);
   if(calls===4 && mode==='complete')assert.ok(body.messages.some(m=>String(m.content).includes('Neyvia runtime goal checkpoint')));
   const step=sequence[calls-1];assert.ok(step,`Unexpected request ${calls} in ${mode}`);
   if(step.hang)return;
   if(mode==='nonstream'){res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify({id:'response-'+calls,object:'chat.completion',created:1,model:'fixture',choices:[{index:0,message:{role:'assistant',content:step.text??null,...(step.tool?{tool_calls:[{id:'call-'+calls,type:'function',function:{name:step.tool,arguments:JSON.stringify(step.args)}}]}:{})},finish_reason:step.tool?'tool_calls':'stop'}]}));return;}
   res.writeHead(200,{'content-type':'text/event-stream'});
   const chunk=(delta,finish=null)=>res.write('data: '+JSON.stringify({id:'goal-'+calls,object:'chat.completion.chunk',created:1,model:'fixture',choices:[{index:0,delta,finish_reason:finish}]})+'\n\n');
   chunk({role:'assistant'});
   if(step.tool){chunk({tool_calls:[{index:0,id:'call-'+calls,type:'function',function:{name:step.tool,arguments:JSON.stringify(step.args)}}]});chunk({},'tool_calls');}
   else{chunk({content:step.text});chunk({},'stop');}
   res.end('data: [DONE]\n\n');
  }catch(e){violation=e.stack;res.end();}
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 try{
  const child=spawn('python',['-m','grant_agent.neyvia_agent_cli','Inspect a.txt, b.txt and c.txt.','--root',dir,'--control-root',dir,'--session-id','goal-'+mode,'--model','fixture','--transport','chat-completions','--base-url',`http://127.0.0.1:${server.address().port}/v1`,'--api-key-env','GOAL_FIXTURE_KEY','--instructions-file',path.join(dir,'instructions.txt'),'--max-turns',mode==='budget'?'2':'12','--no-specialists','--json',...(mode==='simple'?[]:['--goal-mode']),...(mode==='timeout'?['--timeout-seconds','8']:[])],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src'),GOAL_FIXTURE_KEY:'fake',NEYVIA_STREAM_EVENTS:mode==='nonstream'?'0':'1'},windowsHide:true});
  let stdout='',stderr='';child.stdout.on('data',v=>stdout+=v);child.stderr.on('data',v=>stderr+=v);
  const timer=setTimeout(()=>child.kill(),45000);
  const code=await new Promise((resolve,reject)=>{child.on('close',resolve);child.on('error',reject)});clearTimeout(timer);
  assert.equal(violation,'');assert.equal(code,0,stderr+'\n'+stdout.slice(-2000));
  const receipt=(mode==='nonstream'?JSON.parse(stdout):null) || stdout.split(/\r?\n/).filter(l=>l.startsWith('{')).map(l=>{try{return JSON.parse(l)}catch{return null}}).find(r=>r?.schema==='neyvia.agent-run-receipt/v1');
  assert.ok(receipt,stdout.slice(-3000));assert.equal(calls,sequence.length);
  const expected={complete:'completed',late:'completed',stalled:'completed',repeated:'repeated_unchanged_work',blocked:'blocked',question:'input_required',budget:'completed',simple:'not_started',timeout:'failed',nonstream:'completed'}[mode];
  assert.equal(receipt.goalLoop.stopReason,expected);
  assert.equal(receipt.status,['blocked','repeated'].includes(mode)?'incomplete':mode==='question'?'input_required':mode==='timeout'?'failed':'completed');
  if(mode==='budget')assert.ok(receipt.goalLoop.rounds>=4,'SDK batches must continue without ending the goal');
  if(mode==='stalled')assert.ok(stdout.includes('Recovered and verified.'),'Stagnation must prompt a new approach, not terminate');
  if(mode==='complete'){assert.equal(receipt.goalLoop.rounds,3);assert.equal(receipt.usage.requests,9);assert.equal(receipt.goalLoop.distinctToolResults,3);assert.equal(receipt.promptContract.validatedCalls,9);assert.equal((stdout.match(/"kind": "runtime.progress"/g)||[]).length,2);}
  console.log(JSON.stringify({mode,requests:calls,rounds:receipt.goalLoop.rounds,stop:receipt.goalLoop.stopReason,status:receipt.status}));
 }finally{server.closeAllConnections();await new Promise(r=>server.close(r));await rm(dir,{recursive:true,force:true});}
}
for(const mode of ['complete','stalled','blocked','question','budget','simple','nonstream','timeout','repeated','late'].filter(mode=>process.argv.length<3||process.argv.slice(2).includes(mode)))await scenario(mode);
