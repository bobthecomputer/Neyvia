// CLI access to the same owner-authenticated APIs; credentials never printed.
const operation=process.argv[2], args=JSON.parse(process.argv[3] || '{}');
const base=process.env.NEYVIA_UI_BACKEND_URL || 'http://127.0.0.1:48261';
if(base!=='http://127.0.0.1:48261')throw Error('T12 CLI uses only backend 48261');
let cookie;
async function post(url,body){const res=await fetch(base+url,{method:'POST',headers:{'Content-Type':'application/json',...(cookie?{Cookie:cookie}:{})},body:JSON.stringify(body)});const set=res.headers.get('set-cookie');if(set)cookie=set.split(';')[0];const value=await res.json();if(!value.ok)throw Error(value.error||JSON.stringify(value));return value.data;}
async function main(){await post('/api/auth/local-session',{});try{
 if(operation==='manual'){console.log(JSON.stringify(await post('/api/ui/tools/call',{tool:'neyvia.manual.load',arguments:{id:'game-dev',chapter:'bridges'}})));return;}
 if(operation==='tool'){console.log(JSON.stringify(await post('/api/ui/tools/call',{tool:args.tool,arguments:args.arguments||{}})));return;}
 const command=(op,payload)=>post('/api/backend',{command:'gamedev_'+op+'_command',payload});
 let value=await command(operation,args);
 if(operation==='action')for(let attempt=0;attempt<100&&['queued','running'].includes(value.status);attempt++){await new Promise(r=>setTimeout(r,150));value=await command('receipt',{requestId:value.requestId});}
 console.log(JSON.stringify(value));
}finally{await post('/api/auth/logout',{});}}
main().catch(error=>{console.error(String(error));process.exitCode=1;});
