// Prepare a genuine queued native action, restart the owned backend, then verify.
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
const base='http://127.0.0.1:48261', evidence=JSON.parse(fs.readFileSync('scripts/evidence/T12.json','utf8'));
const saved='.agent_control/t12/recovery.json';let cookie;
async function post(url,body){const res=await fetch(base+url,{method:'POST',headers:{'Content-Type':'application/json',...(cookie?{Cookie:cookie}:{})},body:JSON.stringify(body)});const set=res.headers.get('set-cookie');if(set)cookie=set.split(';')[0];const answer=await res.json();if(!answer.ok)throw Error(answer.error);return answer.data;}
const command=(op,payload)=>post('/api/backend',{command:'gamedev_'+op+'_command',payload});
await post('/api/auth/local-session',{});
if(process.argv.includes('--prepare')){
 const child=spawn('node',['scripts/gamedev/native-scene.cjs',evidence.project],{cwd:process.cwd(),stdio:['ignore','pipe','pipe']});
 let logs='';child.stderr.on('data',b=>logs+=b);
 const ready=new Promise((resolve,reject)=>{child.stdout.on('data',b=>{for(const line of String(b).split('\n'))try{const value=JSON.parse(line);if(value.sessionId)resolve(value);}catch{}});child.on('exit',code=>reject(Error('Native host exited '+code+': '+logs.slice(-500))));});
 const native=await ready;const exited=new Promise(resolve=>child.once('exit',resolve));child.kill();await exited;
 const queued=await command('action',{sessionId:native.sessionId,action:'inspect',args:{},requestId:'T12-interrupt-'+Date.now()});
 const before=await command('receipt',{requestId:queued.requestId});if(before.status!=='queued')throw Error('Native queue was not stopped before execution');
 const completed=evidence.journeys.find(j=>j.status==='succeeded');
 fs.writeFileSync(saved,JSON.stringify({before,completedRequestId:completed.requestId,actualChildExitConfirmed:true},null,2));
 console.log(JSON.stringify({status:before.status,requestId:before.requestId,childStopped:true}));
}else{
 const observed=JSON.parse(fs.readFileSync(saved,'utf8'));
 observed.after=await command('receipt',{requestId:observed.before.requestId});
 observed.completedAfter=await command('receipt',{requestId:observed.completedRequestId});
 observed.passed=observed.after.status==='failed'&&observed.after.error.includes('restarted')&&observed.completedAfter.status==='succeeded';
 if(!observed.passed)throw Error('Restart state failed: '+JSON.stringify(observed));
 evidence.backendRestart=observed;
 fs.writeFileSync('scripts/evidence/T12.json',JSON.stringify(evidence,null,2)+'\n');
 fs.writeFileSync(saved,JSON.stringify(observed,null,2));
 console.log(JSON.stringify({restartInterrupted:observed.after.status,completedRetained:observed.completedAfter.status,passed:true}));
}
await post('/api/auth/logout',{});
