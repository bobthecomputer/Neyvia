// Opt-in live model journey; installs only an authored local package in a disposable workspace.
import {mkdirSync,writeFileSync,readFileSync,existsSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const proof=path.join(repo,'proof','harness-actions-20260927');
const harness=process.argv[2]||'native';
if(!['native','codex','claude-code','hermes'].includes(harness))throw Error('Unknown harness');
const model=process.env.NEYVIA_PROBE_MODEL||(harness==='claude-code'?'sonnet':'gpt-6-luna');
const provider=process.env.NEYVIA_PROBE_PROVIDER||(harness==='claude-code'?'claude-code':'openai-codex');
const fixture=path.join(proof,`${harness}-workspace-${Date.now()}`);
mkdirSync(path.join(fixture,'local-package'),{recursive:true});
writeFileSync(path.join(fixture,'package.json'),JSON.stringify({name:'neyvia-action-fixture',version:'1.0.0',private:true}));
writeFileSync(path.join(fixture,'local-package','package.json'),JSON.stringify({name:'neyvia-local-action-check',version:'1.0.0',main:'index.js'}));
writeFileSync(path.join(fixture,'local-package','index.js'),"module.exports='LOCAL_INSTALL_VERIFIED';\n");
writeFileSync(path.join(fixture,'browser-check.cjs'),`
const {chromium}=require(${JSON.stringify(path.join(repo,'node_modules','playwright'))});
const fs=require('node:fs');
const http=require('node:http');
(async()=>{
const server=http.createServer((q,r)=>r.end(${JSON.stringify('<button onclick="document.body.dataset.clicked=\'yes\'">Check action</button>')}));
await new Promise(r=>server.listen(0,'127.0.0.1',r));
let browser;
try {browser=await chromium.launch({headless:true});const page=await browser.newPage();
await page.goto('http://127.0.0.1:'+server.address().port);
await page.getByRole('button',{name:'Check action'}).click();
const clicked=await page.getAttribute('body','data-clicked');if(clicked!=='yes')throw Error('Click missing');
fs.writeFileSync('browser-result.json',JSON.stringify({launched:true,clicked:true}));
console.log('BROWSER_CLICK_VERIFIED');
} finally {if(browser)await browser.close();server.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1});
`);
const prompt=`In this disposable workspace, use terminal.exec to actually complete these three authorized local actions. Search/describe tools as needed. 1. Run WSL Ubuntu-24.04 with --exec sh -c to write WSL_VERIFIED to wsl-result.txt in the current Windows-mounted workspace. 2. Run npm.cmd install --ignore-scripts --no-audit --no-fund ./local-package, then use Node to require neyvia-local-action-check and write its exported text to install-result.txt. 3. Run node browser-check.cjs, which starts a disposable local HTTP server, launches Chromium, clicks its button, records the result, and closes both. Inspect outputs and report exact failures. Do not alter files outside this workspace or install anything globally. Do not replace the fixture scripts or fabricate result files.`;
const py=String.raw`
import asyncio,json,os,sys
from pathlib import Path
from grant_agent.neyvia_agent import NeyviaAgentConfig,run_neyvia_agent
data=json.load(sys.stdin)
repo=Path(data['repo']);root=Path(data['fixture'])
instructions=root/'instructions.md'
instructions.write_text('Complete the user-authorized local action checks with tools. Report actual results. Never claim an action succeeded without observing it.',encoding='utf-8')
if data['harness']=='native':
    cfg=NeyviaAgentConfig(root=root,session_id='native-live-actions',model=data['model'],provider_id='openai-codex',transport='codex-cli',max_turns=16,timeout_seconds=240,allow_mutations=True,permission_mode='full-access',enable_specialists=False,instructions_file=instructions,situation_interface=False)
    receipt=asyncio.run(run_neyvia_agent(cfg,data['prompt']))
else:
    from grant_agent.web_backend import FluxioWebBackend
    backend=FluxioWebBackend(root,repo/'web'/'dist')
    if data['provider']=='openrouter':
        # Reuse the operator's existing credential for the same provider only;
        # keep it in the child process and never copy it into proof artifacts.
        auth=json.loads((Path.home()/'.local/share/opencode/auth.json').read_text(encoding='utf-8'))
        key=auth.get('openrouter',{}).get('key')
        if key: backend.provider_secrets['openrouter']=key
    receipt=backend.dispatch('send_agent_chat_command',{'message':data['prompt'].replace('use terminal.exec','use your command execution tool'),'runtime':data['harness'],'route':{'provider':data['provider'],'model':data['model'],'effort':'medium'},'workspacePath':str(root),'sessionId':root.name,'permissionMode':'full-access','runtimeTimeoutSeconds':240,'history':[]})
(Path(data['proof'])/(data['harness']+'-model-receipt.json')).write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'receiptPath':receipt.get('receiptPath'),'status':receipt.get('status')}))
`;
const result=spawnSync(resolveNeyviaPython(repo).python,['-c',py],{cwd:repo,input:JSON.stringify({repo,fixture,proof,prompt,harness,model,provider}),encoding:'utf8',env:{...process.env,PYTHONPATH:path.join(repo,'src')},timeout:300000,maxBuffer:1024*1024});
const read=n=>existsSync(path.join(fixture,n))?readFileSync(path.join(fixture,n),'utf8').trim():null;
const summary={model,harness,fixture,exitCode:result.status,wsl:read('wsl-result.txt')==='WSL_VERIFIED',localPackageInstall:read('install-result.txt')==='LOCAL_INSTALL_VERIFIED',browser:read('browser-result.json')?JSON.parse(read('browser-result.json')):null,stdout:result.stdout,stderr:result.stderr.slice(-3000)};
writeFileSync(path.join(proof,harness+'-independent-postconditions.json'),JSON.stringify(summary,null,2));
console.log(JSON.stringify(summary));
process.exitCode=result.status===0&&summary.wsl&&summary.localPackageInstall&&summary.browser?.clicked?0:1;
