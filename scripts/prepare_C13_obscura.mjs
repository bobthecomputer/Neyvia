/** Pinned, bounded task-local Obscura rendering engine; no install or browser fallback. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';
const version='v0.2.4',size=68520432,expected='8e5428bf8c101f1439c53a9dcb52d7d09bb22599206b49f6420028d93d01189b';
const url=`https://github.com/h4ckf0r0day/obscura/releases/download/${version}/obscura-x86_64-windows.zip`;
const root=path.resolve('scripts/evidence/c13-runtime');fs.mkdirSync(root,{recursive:true});
const archive=path.join(root,`obscura-${version}.zip`),destination=path.join(root,`obscura-${version}`);
if(!fs.existsSync(archive)){
 const response=await fetch(url);if(!response.ok||Number(response.headers.get('content-length'))!==size)throw Error('Obscura archive origin/size changed');
 const handle=fs.openSync(archive,'wx');let count=0;
 try{for await(const chunk of response.body){count+=chunk.length;if(count>size)throw Error('Obscura archive exceeded pinned size');fs.writeSync(handle,chunk);}}finally{fs.closeSync(handle);}
}
const bytes=fs.readFileSync(archive),digest=crypto.createHash('sha256').update(bytes).digest('hex');
if(bytes.length!==size||digest!==expected)throw Error('Obscura archive failed pinned SHA256 verification');
if(!fs.existsSync(path.join(destination,'obscura.exe'))){
 const result=spawnSync('powershell.exe',['-NoProfile','-NonInteractive','-Command','Expand-Archive -LiteralPath $env:C13_ARCHIVE -DestinationPath $env:C13_DESTINATION'],{windowsHide:true,env:{...process.env,C13_ARCHIVE:archive,C13_DESTINATION:destination},encoding:'utf8'});
 if(result.status!==0)throw Error(result.stderr);
}
const executable=path.join(destination,'obscura.exe');
const receipt={version,url,archiveBytes:size,sha256:expected,executable,executableSha256:crypto.createHash('sha256').update(fs.readFileSync(executable)).digest('hex'),stealth:false,systemInstall:false};
fs.writeFileSync('scripts/evidence/C13-obscura-provision.json',JSON.stringify(receipt,null,2)+'\n');console.log(JSON.stringify(receipt));
