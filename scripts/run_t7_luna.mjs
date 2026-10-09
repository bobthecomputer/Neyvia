// Real persisted Codex CLI conversations for the T7 acceptance journey.
import {spawn} from 'node:child_process';
import {mkdirSync, writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
const root = resolve('.agent_control/t7/luna-work'); mkdirSync(root,{recursive:true});
const agentOnly = process.argv.includes('--agents');
const imageOnly = process.argv.includes('--image');
const runs = imageOnly ? [['image-proof', 'Generate one small minimalist image of a solid blue circle on a white background using the available image generation tool. This is an authorized image-event integration probe. Use no shell or browser tools, and make no code changes. If image generation is unavailable, say so plainly.']] : agentOnly ? [['agent-proof', 'This is an authorized agent-tool acceptance task. Call spawn_agent (exactly once) with model gpt-6-luna and a brief: explain how Tab order and visible focus help keyboard-only website users. Then wait for that child to finish, read its answer, and call interrupt_agent on it. Do not use shell, filesystem or browser tools. If spawn_agent is unavailable, explicitly report that instead of claiming delegation. Finish with the child ID and one sentence from its answer.']] : [
  ['access-a', 'Give a short practical plan to make a web page usable by people relying on screen readers and keyboard navigation. Use exactly one subagent to check focus order, wait for its answer and call interrupt_agent on it before finishing. Use gpt-6-luna for that child. Do not use shell, browser or filesystem tools.'],
  ['access-b', 'Explain in a short paragraph how accessible websites support blind visitors, with tab order, focus indicators and semantic landmarks. Do not call tools.'],
  ['food-a', 'Give a short practical recipe for baking sourdough bread: starter fermentation, kneading, proofing and oven temperature. Do not call tools.'],
  ['food-b', 'Explain in a short paragraph how a fermented loaf is made using flour, water, a live culture, resting dough and baking. Do not call tools.'],
];
const records=[];
for (const [name,prompt] of runs) {
 const start=Date.now(); const dir=resolve(root,name); mkdirSync(dir,{recursive:true});
 const output=await new Promise((res,rej)=>{
   const child=spawn(process.execPath,['C:/Users/user/AppData/Roaming/npm/node_modules/@openai/codex/bin/codex.js','exec','--ignore-user-config','--enable','multi_agent','--enable','multi_agent_v2','-m','gpt-6-luna','-c',`model_reasoning_effort="${agentOnly?'medium':'low'}"`,'-s','read-only','--skip-git-repo-check','--json','-C',dir,'-'],{windowsHide:true});
   child.stdin.end(prompt);
   let stdout='',stderr=''; child.stdout.on('data',b=>stdout+=b);child.stderr.on('data',b=>stderr+=b);
   child.on('error',rej);child.on('close',code=>res({code,stdout,stderr}));
 });
 writeFileSync(resolve('.agent_control/t7',name+'.jsonl'),output.stdout);
 writeFileSync(resolve('.agent_control/t7',name+'.stderr.txt'),output.stderr);
 const events=output.stdout.split(/\r?\n/).filter(Boolean).map(line=>{try{return JSON.parse(line)}catch{return {unparsed:line}}});
 const thread=events.find(e=>e.type==='thread.started')?.thread_id;
 const record={name,prompt,threadId:thread,model:'gpt-6-luna',exitCode:output.code,ms:Date.now()-start,usage:events.find(e=>e.type==='turn.completed')?.usage,events}; records.push(record);
 writeFileSync(`.agent_control/t7/${imageOnly?'image-runs':agentOnly?'agent-runs':'luna-runs'}.json`,JSON.stringify(records,null,2));
 console.log(JSON.stringify({name,thread,code:output.code,ms:record.ms,usage:record.usage}));
 if(output.code!==0) throw Error(output.stderr.slice(-500));
}
