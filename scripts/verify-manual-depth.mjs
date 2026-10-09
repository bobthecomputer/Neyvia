// Scratch app-native journeys and matched CLI comparison; no Python test suite.
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import net from 'node:net';
const repo=process.cwd(),python='C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
const root=process.env.MANUAL_DEPTH_ROOT||fs.mkdtempSync(path.join(os.tmpdir(),'neyvia-manual-depth-'));
const port=47970,base='http://127.0.0.1:'+port,evidencePath=process.env.MANUAL_DEPTH_EVIDENCE||path.join(repo,'docs/manuals/manual-depth.evidence.json');
const evidence={root,backend:base,sourceHead:spawnSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).stdout.trim(),checks:[],procedures:[],comparison:[]};
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let cookie='',backend;
function checked(name,condition,details={}){assert(condition,name);evidence.checks.push({name,passed:true,...details});console.log('PASS '+name);}
function persist(){fs.writeFileSync(evidencePath,JSON.stringify(evidence,null,2)+'\n');}
async function http(route,body){
 const response=await fetch(base+route,{method:body===undefined?'GET':'POST',body:body===undefined?undefined:JSON.stringify(body),
  headers:{'Content-Type':'application/json',...(cookie?{Cookie:cookie}:{})},signal:AbortSignal.timeout(90000)});
 if(response.headers.get('set-cookie'))cookie=response.headers.get('set-cookie').split(';')[0];
 const value=await response.json();if(!response.ok)throw Error(route+': '+JSON.stringify(value));return value;
}
function unwrap(value){
 while(value&&typeof value==='object'&&value.tool&&value.result&&typeof value.result==='object'){
  if(value.ok===false)return {...value,...value.result,ok:false};
  value=value.result;
 }
 return value;
}
async function tool(name,args={}){return unwrap((await http('/api/ui/tools/call',{tool:name,arguments:args})).data);}
async function procedure(id,name,inputs,decisions){
 let run=await tool('neyvia.manual.run',{id,chapter:'overview',procedure:name,inputs});
 while(run.status==='judge'){
  const decision=decisions[run.judge.id];assert(run.judge.options.includes(decision),'Missing decision '+run.judge.id);
  run=await tool('neyvia.manual.run',{id,chapter:'overview',procedure:name,runId:run.runId,decisions:{[run.judge.id]:decision}});
 }
 evidence.procedures.push(run);checked(id+'/'+name+' completed',run.ok&&run.status==='completed'&&run.checks.every(check=>check.passed));return run;
}
function fixture(){
 fs.mkdirSync(root,{recursive:true});
 const code=String.raw`
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'src'))
from grant_agent.native_tools import NativeToolRegistry
from grant_agent.neyvia_manuals import get_manual,render
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
root=Path(sys.argv[1]);(root/'notes').mkdir(exist_ok=True)
for trial in ['proof','small','large']:
 (root/'notes'/f'{trial}.md').write_text('# Idea notebook\n\nKeep this original paragraph.\n',encoding='utf-8')
 (root/f'{trial}-report.txt').write_text('Quarterly draft - preserve original bytes.\n',encoding='utf-8')
 (root/f'{trial}-archive').mkdir(exist_ok=True)
writer=PdfWriter()
for words in ['Introduction: cobalt orchard is only background.','Finding: cobalt orchard needs careful verification.']:
 page=writer.add_blank_page(width=300,height=300)
 font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
 page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
 stream=DecodedStreamObject();stream.set_data(('BT /F1 12 Tf 20 250 Td ('+words+') Tj ET').encode())
 page[NameObject('/Contents')]=writer._add_object(stream)
with (root/'passages.pdf').open('wb') as handle:writer.write(handle)
registry=NativeToolRegistry(root)
manuals={key:render(get_manual(key)[2]['chapters']['overview'],get_manual(key)[2]['schemas']) for key in ['notes','files','pdf']}
print(json.dumps({'tools':registry.list_tools(include_schemas=True),'manuals':manuals}))
`;
 const result=spawnSync(python,['-c',code,root],{cwd:repo,encoding:'utf8',windowsHide:true});assert.equal(result.status,0,result.stderr);
 const catalog=JSON.parse(result.stdout);fs.writeFileSync(path.join(root,'catalog.json'),JSON.stringify(catalog));return catalog;
}
async function launch(){
 await new Promise((resolve,reject)=>{const probe=net.createServer();probe.once('error',reject);probe.listen(port,'127.0.0.1',()=>probe.close(resolve));});
 backend=spawn(python,['scripts/run_web_backend.py','--host','127.0.0.1','--port',String(port),'--root',root,'--static-root',path.join(root,'static'),'--skip-runtime-auto-update'],
  {cwd:repo,windowsHide:true,env:{...process.env,NEYVIA_NOTES_DIR:path.join(root,'notes'),NEYVIA_COORDINATOR_AUTOSTART:'0',FLUXIO_WATCHDOG_AUTOSTART:'0',NEYVIA_TOOL_AUTO_UPDATE:'0',FLUXIO_RUNTIME_AUTO_UPDATE:'0'}});
 const log=fs.createWriteStream(path.join(root,'backend.log'));backend.stdout.pipe(log);backend.stderr.pipe(log);
 for(let n=0;n<120;n++){if(backend.exitCode!==null)throw Error('Backend exited; see '+root);try{await http('/api/auth/local-session',{});return;}catch{}await wait(500);}
 throw Error('Scratch backend not ready');
}
async function journeys(){
 const validation=await tool('neyvia.manual.validate');
 checked('all registered manuals validate',validation.ok&&validation.manuals.length>=14,{manuals:validation.manuals.map(m=>({id:m.id,chapters:m.chapters}))});
 await procedure('notes','capture-tagged-idea',{path:'proof.md',idea:'Capture the dictated design idea #research',tag:'research'},{capture:'append'});
 const before=fs.readFileSync(path.join(root,'proof-report.txt'),'utf8'),moved=path.join(root,'proof-archive','proof-report.txt');
 await procedure('files','tidy-with-undo',{from:path.join(root,'proof-report.txt'),to:moved,name:'proof-report.txt'},{tidy:'move'});
 await procedure('files','undo-last-tidy',{from:path.join(root,'proof-report.txt'),to:moved,originalName:'proof-report.txt'},{retain:'undo'});
 checked('Files undo restores exact bytes',fs.readFileSync(path.join(root,'proof-report.txt'),'utf8')===before&&!fs.existsSync(moved));
 const pdfBefore=fs.readFileSync(path.join(root,'passages.pdf'));
 await procedure('pdf','find-and-highlight',{source:'passages.pdf',page:2,phrase:'cobalt orchard'},{passage:'highlight'});
 checked('PDF source bytes preserved',pdfBefore.equals(fs.readFileSync(path.join(root,'passages.pdf'))));
 const events=spawnSync(python,['-c',"import sys,json;from pathlib import Path;sys.path.insert(0,str(Path.cwd()/'src'));from grant_agent.ui_command_bus import bus_for;print(json.dumps(bus_for(Path(sys.argv[1])).since()))",root],{cwd:repo,encoding:'utf8',windowsHide:true});
 assert.equal(events.status,0,events.stderr);evidence.uiEvents=JSON.parse(events.stdout);
 checked('PDF highlight event has actual page and text',evidence.uiEvents.some(row=>row.action==='pdf.highlight'&&row.payload.page===2&&row.payload.text==='cobalt orchard'));
 const note=await tool('neyvia.notes.read',{path:'proof.md'});
 const conflict=await tool('neyvia.notes.write',{path:'proof.md',body:'must not replace',expectedModified:'stale'});
 checked('stale note write refused',conflict.ok===false&&conflict.status==='conflict'&&fs.readFileSync(path.join(root,'notes/proof.md'),'utf8')===note.body);
 fs.writeFileSync(moved,'existing collision');
 const clash=await tool('neyvia.files.move',{from:path.join(root,'proof-report.txt'),to:moved});
 checked('Files collision preserves both files',clash.ok===false&&fs.readFileSync(moved,'utf8')==='existing collision'&&fs.readFileSync(path.join(root,'proof-report.txt'),'utf8')===before);
 const missing=await tool('neyvia.pdf.highlight',{page:1,text:'phrase absent from PDF'});checked('absent PDF highlight refused',missing.ok===false);
 evidence.pdfBoundary='Real PDF text search and highlight event emission; no browser, so overlay rendering not claimed.';persist();
}
async function evaluate(catalog,model,tier,app){
 const note=tier+'.md',origin=path.join(root,tier+'-report.txt'),target=path.join(root,tier+'-archive',tier+'-report.txt');
 const originalBytes=fs.readFileSync(origin);
 const tasks={
 notes:'Capture already-dictated idea in existing note '+note+': "A voice-first notebook should keep context #research". Keep existing words, append once, verify tag research, then pin. Use freshness guard for append and verify saved body/tag/pin.',
 files:'Tidy '+origin+' by moving it into '+path.dirname(target)+'. Inspect it there. Then undo that move because it belongs in original folder. Verify original bytes back and moved path absent. Never overwrite.',
 pdf:'In PDF '+path.join(root,'passages.pdf')+', find "cobalt orchard". Highlight occurrence in Finding passage, not Introduction, and add note "Evidence to revisit". Preserve PDF bytes. Report whether this proves actual UI rendering.'
 };
 const prompt=tasks[app]+(tier==='small'?'\nRelevant executable manual:\n'+catalog.manuals[app]:'');
 const tracePath=path.join(root,tier+'-'+app+'-tools.jsonl');
 const config={mcpServers:{manual_depth:{command:process.execPath,args:[path.join(repo,'scripts/manual-depth-mcp.mjs')],
  env:{MANUAL_DEPTH_BACKEND:base,MANUAL_DEPTH_CATALOG:path.join(root,'catalog.json'),MANUAL_DEPTH_APP:app,MANUAL_DEPTH_TRACE:tracePath}}}};
 const configPath=path.join(root,tier+'-'+app+'-mcp.json');fs.writeFileSync(configPath,JSON.stringify(config));
 const launcher=spawnSync('where.exe',['claude'],{encoding:'utf8'}).stdout.trim().split(/\r?\n/).find(p=>p.endsWith('.cmd'));assert(launcher,'Claude launcher missing');
 const entry=path.join(path.dirname(launcher),'node_modules/@anthropic-ai/claude-code/bin/claude.exe');assert(fs.existsSync(entry),'Claude CLI executable missing');
 const logPath=path.join(root,tier+'-'+app+'.jsonl'),errPath=path.join(root,tier+'-'+app+'.stderr');
 const out=fs.createWriteStream(logPath),err=fs.createWriteStream(errPath),started=Date.now();
 const cli=spawn(entry,['--print','--verbose','--output-format','stream-json','--model',model,'--effort','low','--no-session-persistence','--no-chrome','--disable-slash-commands','--setting-sources','',
  '--strict-mcp-config','--mcp-config',configPath,'--tools','','--permission-mode','dontAsk','--allowedTools','mcp__manual_depth__*',
  '--system-prompt','Use only provided scratch MCP tools. Inspect actual results, preserve unrelated state and report evidence. No other services/files/agents/providers. Do not ask for already authorized reversible scratch operations.','--',prompt],
  {cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe'],env:{...process.env,CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC:'1'}});
 cli.stdout.pipe(out);cli.stderr.pipe(err);
 const exitCode=await new Promise((resolve,reject)=>{cli.once('error',reject);cli.once('exit',resolve);});
 await Promise.all([new Promise(resolve=>out.end(resolve)),new Promise(resolve=>err.end(resolve))]);
 const lines=fs.readFileSync(logPath,'utf8').split('\n').filter(Boolean).map(line=>{try{return JSON.parse(line);}catch{return {unparsed:line};}});
 const final=lines.findLast(row=>row.type==='result')||{},declared=lines.find(row=>row.type==='system'&&row.subtype==='init');
 const traces=fs.existsSync(tracePath)?fs.readFileSync(tracePath,'utf8').trim().split('\n').filter(Boolean).map(line=>JSON.parse(line)):[];
 const successful=tool=>traces.filter(row=>row.tool===tool&&row.receipt.ok!==false&&unwrap(row.receipt.data)?.ok!==false);
 let success=false,proof={};
 if(app==='notes'){const state=await tool('neyvia.notes.read',{path:note});const guarded=successful('neyvia.notes.write').some(row=>row.args.mode==='append'&&row.args.expectedModified);success=guarded&&state.body?.includes('Keep this original paragraph.')&&state.body?.split('A voice-first notebook should keep context #research').length===2&&state.tags?.includes('research')&&state.pinned===true;proof={body:state.body,tags:state.tags,pinned:state.pinned,guarded};}
 if(app==='files'){success=successful('neyvia.files.move').length===1&&successful('neyvia.files.undo').length===1&&fs.existsSync(origin)&&originalBytes.equals(fs.readFileSync(origin))&&!fs.existsSync(target);proof={originExists:fs.existsSync(origin),targetExists:fs.existsSync(target),bytesRestored:fs.existsSync(origin)&&originalBytes.equals(fs.readFileSync(origin)),moves:successful('neyvia.files.move').length,undos:successful('neyvia.files.undo').length};}
 if(app==='pdf'){const emitted=successful('neyvia.pdf.highlight');success=emitted.some(row=>row.args.page===2&&row.args.text==='cobalt orchard'&&row.args.note==='Evidence to revisit'&&unwrap(row.receipt.data).event?.action==='pdf.highlight')&&String(final.result).toLowerCase().includes('render');proof={highlightCalls:emitted,renderingBoundaryReported:String(final.result).toLowerCase().includes('render')};}
 const usage=final.usage||{},modelUsage=final.modelUsage||{};
 evidence.comparison.push({app,tier,requestedModel:model,model:declared?.model||Object.keys(modelUsage)[0]||null,exitCode,success:exitCode===0&&!final.is_error&&Boolean(success),latencyMs:Date.now()-started,usage,modelUsage,
  totalTokens:(usage.input_tokens||0)+(usage.output_tokens||0)+(usage.cache_creation_input_tokens||0)+(usage.cache_read_input_tokens||0),
  tokenAccounting:'Provider cumulative input+cache creation+cache read+output; repeated context included.',
  proof,toolTrace:traces,finalText:final.result||null,logPath,error:fs.readFileSync(errPath,'utf8').slice(-2000)});
 persist();const row=evidence.comparison.at(-1);console.log(JSON.stringify({app,tier,model:row.model,success:row.success,totalTokens:row.totalTokens,latencyMs:row.latencyMs}));
}
try{
 const catalog=fixture();await launch();await journeys();
 if(process.argv.includes('--models')||process.argv.includes('--models-small')){
  evidence.comparisonProtocol='One task per Notes/Files/PDF, same live schemas/backend, same-shaped isolated fixtures. Small receives chapter, large no manual. One attempt each, no fallback. Tool evidence scored.';
  for(const app of ['notes','files','pdf']){
   console.log('EVALUATE small with manual: '+app);await evaluate(catalog,process.env.MANUAL_DEPTH_SMALL_MODEL||'haiku','small',app);
   if(!process.argv.includes('--models-small')){
    console.log('EVALUATE large without manual: '+app);await evaluate(catalog,process.env.MANUAL_DEPTH_LARGE_MODEL||'opus','large',app);
   }
  }
 }
 evidence.passed=true;persist();
}catch(error){evidence.passed=false;evidence.error=String(error.stack);persist();console.error(error);process.exitCode=1;}
finally{if(backend&&backend.exitCode===null){backend.kill();await new Promise(resolve=>backend.once('exit',resolve));}}
