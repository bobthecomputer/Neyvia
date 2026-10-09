/* Task-local upstream non-stealth build; pinned SHA256, no system install. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'../.agent_control/T20/obscura-v0.2.3');
const url='https://github.com/h4ckf0r0day/obscura/releases/download/v0.2.3/obscura-x86_64-windows.zip';
const expected='781a1b8bd12b65ec5aba95842e75e6f56b3101d360397506c0e35fe3f78536e8';
async function main(){
  fs.mkdirSync(root,{recursive:true});const archive=path.join(root,'obscura.zip');
  if(!fs.existsSync(archive)){
    const r=await fetch(url);if(!r.ok)throw Error('Download HTTP '+r.status);
    const size=Number(r.headers.get('content-length'));if(!size||size>200000000)throw Error('Unbounded/oversized archive');
    const stream=fs.openSync(archive,'wx');let count=0;
    try{for await(const chunk of r.body){count+=chunk.length;if(count>200000000)throw Error('Download limit');fs.writeSync(stream,chunk);}}finally{fs.closeSync(stream);}
  }
  const data=fs.readFileSync(archive);const digest=crypto.createHash('sha256').update(data).digest('hex');if(digest!==expected)throw Error('Archive SHA256 mismatch');
  const destination=path.join(root,'bin');if(!fs.existsSync(destination)){
    const r=spawnSync('powershell.exe',['-NoProfile','-NonInteractive','-Command','Expand-Archive -LiteralPath $env:T20_ARCHIVE -DestinationPath $env:T20_DESTINATION'],{windowsHide:true,env:{...process.env,T20_ARCHIVE:archive,T20_DESTINATION:destination},encoding:'utf8'});if(r.status!==0)throw Error(r.stderr);
  }
  fs.writeFileSync(path.join(root,'receipt.json'),JSON.stringify({url,version:'v0.2.3',archiveBytes:data.length,sha256:digest,stealthBuild:false,systemInstall:false},null,2)+'\n');
  console.log(JSON.stringify({destination,archiveBytes:data.length,sha256:digest}));
}
main().catch(e=>{console.error(e.message);process.exitCode=1;});
