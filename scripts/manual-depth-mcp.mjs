// Isolated evaluation transport: exact schemas and local scratch backend.
import fs from 'node:fs';
import readline from 'node:readline';
const base=process.env.MANUAL_DEPTH_BACKEND, parsed=new URL(base);
if(parsed.hostname!=='127.0.0.1'||!/^4797\d$/.test(parsed.port))throw Error('Scratch backend required');
const catalog=JSON.parse(fs.readFileSync(process.env.MANUAL_DEPTH_CATALOG,'utf8'));
const names=new Map(catalog.tools.filter(row=>row.name.startsWith('neyvia.'+process.env.MANUAL_DEPTH_APP+'.')).map(row=>[row.name.replaceAll('.','_'),row]));
let cookie='';
async function call(tool,args){
 if(!cookie){const auth=await fetch(base+'/api/auth/local-session',{method:'POST',body:'{}',headers:{'Content-Type':'application/json'}});if(!auth.ok)throw Error('Scratch auth failed');cookie=auth.headers.get('set-cookie').split(';')[0];}
 const response=await fetch(base+'/api/ui/tools/call',{method:'POST',body:JSON.stringify({tool,arguments:args}),headers:{'Content-Type':'application/json',Cookie:cookie},signal:AbortSignal.timeout(90000)});
 const receipt=await response.json();
 fs.appendFileSync(process.env.MANUAL_DEPTH_TRACE,JSON.stringify({tool,args,receipt})+'\n');
 if(!response.ok||receipt.ok===false)throw Error(JSON.stringify(receipt));return receipt.data;
}
for await(const line of readline.createInterface({input:process.stdin})){
 let request;
 try{
  request=JSON.parse(line);if(!('id' in request))continue;let result;
  if(request.method==='initialize')result={protocolVersion:'2024-11-05',capabilities:{tools:{}},serverInfo:{name:'manual-depth',version:'1'}};
  else if(request.method==='tools/list')result={tools:[...names].map(([name,row])=>({name,description:row.description,inputSchema:row.inputSchema}))};
  else if(request.method==='tools/call'){
   const row=names.get(request.params.name);if(!row)throw Error('Unknown tool');
   const value=await call(row.name,request.params.arguments||{});result={content:[{type:'text',text:JSON.stringify(value)}],structuredContent:value,isError:value.ok===false};
  }else if(request.method==='ping')result={};else throw Error('Unsupported method');
  process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:request.id,result})+'\n');
 }catch(error){process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:request?.id,error:{code:-32000,message:String(error.message)}})+'\n');}
}
