// Benchmark-only transport; identical schemas in both arms, real scratch HTTP tools.
import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
const base=process.env.RECOVERY_BACKEND, url=new URL(base);
if(url.hostname!=='127.0.0.1'||!/^4818[1-9]$/.test(url.port))throw Error('Assigned scratch port required');
const fixture=JSON.parse(fs.readFileSync(process.env.RECOVERY_FIXTURE,'utf8'));
const catalog=JSON.parse(fs.readFileSync(process.env.RECOVERY_CATALOG,'utf8'));
const names=new Map(catalog.tools.map(row=>[row.name.replaceAll('.','_'),row]));
let cookie='',injected=false;
function unwrap(v){while(v?.tool&&v.result&&typeof v.result==='object')v=v.result;return v;}
async function http(tool,args){
 if(!cookie){const r=await fetch(base+'/api/auth/local-session',{method:'POST',body:'{}',headers:{'Content-Type':'application/json'}});if(!r.ok)throw Error('Scratch auth failed');cookie=r.headers.get('set-cookie').split(';')[0];}
 const r=await fetch(base+'/api/ui/tools/call',{method:'POST',body:JSON.stringify({tool,arguments:args}),headers:{'Content-Type':'application/json',Cookie:cookie},signal:AbortSignal.timeout(90000)});
 const receipt=await r.json();if(!r.ok)throw Error(JSON.stringify(receipt));return unwrap(receipt.data);
}
async function call(tool,args){
 if(tool==='neyvia.manual.run'){
  if(args.id!=='handoff-recovery')throw Error('Only benchmark manual permitted');
  args={...args,scopeTools:catalog.tools.filter(row=>row.name!=='neyvia.manual.run').map(row=>row.name)};
 }
 for(const key of ['path','from','to'])if(args[key]){
  if(tool.startsWith('neyvia.notes.')&&!String(args[key]).startsWith(fixture.prefix))throw Error('Different fixture note refused');
  if(tool.startsWith('neyvia.files.')&&!path.resolve(args[key]).startsWith(fixture.folder+path.sep))throw Error('Different fixture file refused');
 }
 if(args.inputs){if(!String(args.inputs.path).startsWith(fixture.prefix))throw Error('Different fixture note refused');
  for(const key of ['source','target'])if(args.inputs[key]&&!path.resolve(args.inputs[key]).startsWith(fixture.folder+path.sep))throw Error('Different fixture file refused');}
 const value=await http(tool,args);
 fs.appendFileSync(process.env.RECOVERY_TRACE,JSON.stringify({tool,args,result:value})+'\n');
 const stale=fixture.tasks.find(t=>t.id==='stale');
 const staleRead=tool==='neyvia.notes.read'&&args.path===stale.inputs.path;
 const staleJudge=tool==='neyvia.manual.run'&&args.inputs?.path===stale.inputs.path&&value.status==='judge';
 if(!injected&&(staleRead||staleJudge)){
  injected=true;const before=await http('neyvia.notes.read',{path:stale.inputs.path});
  const edit=await http('neyvia.notes.write',{path:stale.inputs.path,body:'Concurrent editor paragraph.',mode:'append',expectedModified:before.modified});
  if(edit.ok===false)throw Error('Concurrent editor fixture failed');
  fs.appendFileSync(process.env.RECOVERY_TRACE,JSON.stringify({fixture:'concurrent-editor',result:edit})+'\n');
 }
 return value;
}
for await(const line of readline.createInterface({input:process.stdin})){
 let request;try{
  request=JSON.parse(line);if(!('id'in request))continue;let result;
  if(request.method==='initialize')result={protocolVersion:'2024-11-05',capabilities:{tools:{}},serverInfo:{name:'recovery',version:'1'}};
  else if(request.method==='tools/list')result={tools:[...names].map(([name,row])=>({name,description:row.description,inputSchema:row.inputSchema}))};
  else if(request.method==='tools/call'){
   const row=names.get(request.params.name);if(!row)throw Error('Unknown tool');const value=await call(row.name,request.params.arguments||{});
   result={content:[{type:'text',text:JSON.stringify(value)}],structuredContent:value,isError:value.ok===false};
  }else if(request.method==='ping')result={};else throw Error('Unsupported method');
  process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:request.id,result})+'\n');
 }catch(e){process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:request?.id,error:{code:-32000,message:String(e.message)}})+'\n');}
}
