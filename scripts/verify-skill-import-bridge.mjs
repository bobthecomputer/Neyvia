import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
const repo=process.cwd(), root=mkdtempSync(path.join(os.tmpdir(),'neyvia-import-bridge-'));
const python=path.join(repo,'.venv','Scripts','python.exe');
const call=(command,payload)=>{
 const result=spawnSync(python,['-m','grant_agent.desktop_bridge','--root',root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},input:JSON.stringify({command,payload}),encoding:'utf8',timeout:45000,maxBuffer:8*1024*1024});
 assert.equal(result.status,0,result.stderr||result.stdout);
 const envelope=JSON.parse(result.stdout);assert.equal(envelope.ok,true,JSON.stringify(envelope));return envelope.data;
};
try{
 const content='---\nname: bridge-sample\ndescription: Benign import bridge check.\n---\n'+ 'Sample text.\n'.repeat(35000);
 const inspected=call('inspect_skill_import_command',{files:Array.from({length:5},(_,i)=>({name:`sample-${i}.md`,dataBase64:Buffer.from(content.replace('bridge-sample',`bridge-sample-${i}`)).toString('base64')}))});
 assert.equal(inspected.ok,true,JSON.stringify(inspected));assert.equal(inspected.items.length,5);
 const installed=call('install_skill_import_command',{importId:inspected.importId,selectedIds:inspected.items.map(row=>row.id)});
 assert.equal(installed.results[0].status,'installed',JSON.stringify(installed));
 assert.equal(readFileSync(path.join(root,'.codex','skills','bridge-sample-0','SKILL.md'),'utf8'),content.replace('bridge-sample','bridge-sample-0'));
 const expired=call('install_skill_import_command',{importId:inspected.importId,selectedIds:inspected.items.map(row=>row.id)});
 assert.equal(expired.ok,false);
 console.log(JSON.stringify({desktopImport:true,over2MBEnvelope:true,exactContent:true,consumedStageRejected:true}));
}finally{rmSync(root,{recursive:true,force:true});}
