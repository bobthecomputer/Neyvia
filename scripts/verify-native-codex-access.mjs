import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,writeFileSync,mkdirSync,rmSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
const root=process.cwd(), temp=mkdtempSync(path.join(os.tmpdir(),'neyvia-codex-'));
try {
 const home=path.join(temp,'codex');mkdirSync(home);
 writeFileSync(path.join(home,'config.toml'),`[mcp_servers.fixture]\ncommand = ${JSON.stringify(process.execPath)}\nargs = [${JSON.stringify(path.join(root,'scripts','verify-mcp-jsonl.mjs'))}, "--server"]\ndisabled_tools = ["blocked"]\n`);
 mkdirSync(path.join(home,'skills','hello'),{recursive:true});writeFileSync(path.join(home,'skills','hello','SKILL.md'),'---\nname: hello\ndescription: Fixture instructions\n---\nSay constellation.');
 const py=`import json,os\nfrom pathlib import Path\nfrom grant_agent.neyvia_agent import NeyviaToolGateway\ng=NeyviaToolGateway(Path(${JSON.stringify(temp)}))\ntry:\n a=g.call_native('codex.instructions.list',{})\n assert a['ok'],a\n r=g.call_native('codex.instructions.read',{'skillId':'codex:personal:hello'})\n assert 'Say constellation.' in json.dumps(r),r\n p=g.native._codex_plugin_access()\n server=p.rows[0]['server']\n found=g.call_native('codex.plugins.search',{'server':server})\n assert 'ping' in json.dumps(found),found\n call=g.call_native('codex.plugins.read',{'server':server,'tool':'ping'})\n assert call['ok'] and 'pong' in json.dumps(call),call\n denied=g.call_native('codex.plugins.call',{'server':server,'tool':'ping'})\n assert not denied['ok'],denied\n blocked=g.call_native('codex.plugins.read',{'server':server,'tool':'blocked'})\n assert not blocked['ok'],blocked\n print(json.dumps({'skillRead':True,'pluginDiscovery':True,'pluginReadExecuted':True,'writeDenied':True,'disabledToolDenied':True}))\nfinally:\n if hasattr(g.native,'_codex_plugins'):g.native._codex_plugins.close()\n if hasattr(g,'situation_service'):g.situation_service.close()\n`;
 const run=spawnSync(path.join(root,'.venv','Scripts','python.exe'),['-c',py],{cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'src'),CODEX_HOME:home},encoding:'utf8',timeout:60000});
 assert.equal(run.status,0,run.stderr||run.stdout);console.log(run.stdout);
}finally{rmSync(temp,{recursive:true,force:true});}

