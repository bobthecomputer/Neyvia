/* Lead-owned capability probes. No config/credential reads or provider substitution. */
const {spawn}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path');
const repo=path.resolve(__dirname,'..'),out=path.join(repo,'scripts/evidence/C2b-comparators');
fs.mkdirSync(out,{recursive:true});
const mode=process.argv[2];
if(!['claude','openai'].includes(mode))throw Error('Pass claude or openai');
const prompt=mode==='claude'?
 'This is a lead-run Claude-in-Chrome availability probe for an authorized read-only public-web benchmark. Use ONLY the Claude-in-Chrome tabs_context_mcp browser tool to establish extension connectivity. Do not read files, credentials, settings, private tab contents, or use any other tools/provider. Do not create agents. Do not navigate localhost, private pages, or port 47881. Return the actual connectivity/error and tool name. If connected, create one owned benchmark tab at https://dictionary.cambridge.org/dictionary/english/sustainability and read its definition and pronunciation; never operate existing private tabs. Do not claim success unless browser tool calls returned.' :
 'This is a read-only capability probe for a public-web benchmark. Do not read files, credentials, config, private pages or use shell, do not spawn agents. Identify whether you have an actual browser automation tool that can navigate/click/observe public pages. If so, use only that tool on https://dictionary.cambridge.org/dictionary/english/sustainability and return the definition and pronunciation with actual tool evidence. If only web_search/open web retrieval is available, make one web open/search call to that public page, state that this is retrieval rather than interactive browser automation, and stop. Do not silently substitute a provider or claim a browser benchmark.';
const exe=mode==='claude'?'C:/Users/user/AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe':process.execPath;
const args=mode==='claude'?['-p','--chrome','--restricted','--strict-mcp-config','--tools','','--allowedTools','mcp__claude_in_chrome__*','--model','opus','--effort','medium','--no-session-persistence','--output-format','stream-json','--verbose',prompt]:
 ['--search','exec','--ephemeral','--sandbox','read-only','--json','-c','model_reasoning_effort="medium"',prompt];
// cmd is used only for the installed npm CLI launcher; no filesystem mutation commands.
if(mode==='openai')args.unshift('C:/Users/user/AppData/Roaming/npm/node_modules/@openai/codex/bin/codex.js');
const child=spawn(exe,args,{cwd:repo,windowsHide:true,stdio:['ignore','pipe','pipe']});
let stdout='',stderr='';const started=Date.now();
child.stdout.on('data',b=>{stdout+=b;fs.writeFileSync(path.join(out,mode+'.jsonl'),stdout);});
child.stderr.on('data',b=>{stderr+=b;fs.writeFileSync(path.join(out,mode+'.stderr.log'),stderr);});
const timer=setTimeout(()=>child.kill(),180000);
child.on('close',(code,signal)=>{clearTimeout(timer);const receipt={schema:'neyvia.C2b.comparator-probe@1',arm:mode,startedAt:new Date(started).toISOString(),elapsedMs:Date.now()-started,exitCode:code,signal,stdout:path.relative(repo,path.join(out,mode+'.jsonl')),stderr:path.relative(repo,path.join(out,mode+'.stderr.log')),boundary:'Capability probe; not a paired 21-task benchmark'};fs.writeFileSync(path.join(out,mode+'-probe.json'),JSON.stringify(receipt,null,2)+'\n');console.log(JSON.stringify(receipt));});
