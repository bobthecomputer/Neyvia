'use strict';
// Reuse the admitted task build cache and installed direct toolchain, offline.
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),crypto=require('node:crypto');
const output=process.argv[2];
if(!output||!/^scripts\/evidence\/C2g-[\w-]+\.json$/.test(output)||fs.existsSync(output))throw Error('Fresh task-scoped build receipt required');
const repo=process.cwd(),target='D:/CodexScratch/nx-c2-browser-C2b-native';
const toolchain='C:/Users/user/.rustup/toolchains/stable-x86_64-pc-windows-msvc/bin';
const vc='C:/Program Files/Microsoft Visual Studio/18/Insiders/VC/Tools/MSVC/14.50.35503',sdk='C:/Program Files (x86)/Windows Kits/10',version='10.0.26100.0';
const rustc=cp.execFileSync(toolchain+'/rustc.exe',['--version'],{encoding:'utf8',windowsHide:true}).trim();
if(!rustc.startsWith('rustc 1.90.0 '))throw Error('Previously admitted installed native toolchain changed');
const hashes=files=>Object.fromEntries(files.map(p=>[p,crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex')]));
const sources=['scripts/browser-probe/src/main.rs','src-tauri/src/browser_runtime.rs','src-tauri/src/browser_projection.js','src/grant_agent/browser_dom.js'];
const report={schema:'neyvia.C2g.native-build@1',startedAt:new Date().toISOString(),offline:true,downloads:0,systemInstall:false,rustc,targetDirectory:target,sourceHashes:hashes(sources)};
const save=()=>fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');save();
const env={...process.env,CARGO_NET_OFFLINE:'true',RUSTC:toolchain+'/rustc.exe',RUSTDOC:toolchain+'/rustdoc.exe',
 PATH:[toolchain,vc+'/bin/Hostx64/x64',sdk+'/bin/'+version+'/x64',process.env.PATH].join(';'),
 INCLUDE:[vc+'/include',sdk+'/Include/'+version+'/ucrt',sdk+'/Include/'+version+'/shared',sdk+'/Include/'+version+'/um',sdk+'/Include/'+version+'/winrt'].join(';'),
 LIB:[vc+'/lib/x64',sdk+'/Lib/'+version+'/ucrt/x64',sdk+'/Lib/'+version+'/um/x64'].join(';'),
 CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER:vc+'/bin/Hostx64/x64/link.exe',VCToolsInstallDir:vc+'/',WindowsSdkDir:sdk+'/',WindowsSDKVersion:version+'/'};
report.command=['build','--offline','--locked','--manifest-path','scripts/browser-probe/Cargo.toml','--bin','browser-proof-c2d-roles','--target-dir',target];
const log=path.resolve('.agent_control/C2g/'+path.basename(output,'.json')+'.log'),fd=fs.openSync(log,'a');report.log=path.relative(repo,log);
const child=cp.spawn(toolchain+'/cargo.exe',report.command,{cwd:repo,env,windowsHide:true,stdio:['ignore',fd,fd]});fs.closeSync(fd);report.pid=child.pid;save();
child.on('error',e=>{report.error=e.message;save();process.exitCode=1;});
child.on('exit',code=>{report.exitCode=code;report.finishedAt=new Date().toISOString();report.sourcesUnchanged=JSON.stringify(hashes(sources))===JSON.stringify(report.sourceHashes);
 if(code===0&&report.sourcesUnchanged){const built=path.join(target,'debug/browser-proof-c2d-roles.exe');report.sha256=crypto.createHash('sha256').update(fs.readFileSync(built)).digest('hex');report.bytes=fs.statSync(built).size;
  const destination=path.resolve('.agent_control/C2g/native/'+report.sha256.slice(0,16));fs.mkdirSync(destination,{recursive:true});report.exe=path.relative(repo,path.join(destination,'browser-c2g-probe.exe'));fs.copyFileSync(built,report.exe);
  if(hashes([report.exe])[report.exe]!==report.sha256)throw Error('Staged native copy digest changed');
 }save();console.log(JSON.stringify({code,receipt:output,exe:report.exe,sourcesUnchanged:report.sourcesUnchanged}));process.exitCode=code||(!report.sourcesUnchanged?1:0);});
