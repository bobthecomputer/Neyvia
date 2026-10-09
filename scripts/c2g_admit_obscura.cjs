/* Admit only a completed offline source build after an actual Obscura journey. */
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const repo=path.resolve('.'),hash=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const read=file=>JSON.parse(fs.readFileSync(path.join(repo,file),'utf8'));
function receiptOption(flag,fallback){const index=process.argv.indexOf(flag),name=index<0?fallback:process.argv[index+1];if(!/^C2g-[a-zA-Z0-9-]+\.json$/.test(name||''))throw Error('Scoped C2g receipt filename required');return 'scripts/evidence/'+name;}
const buildFile=receiptOption('--build','C2g-engine-source-build.json'),proofFile=receiptOption('--proof','C2g-browser-abilities.json'),admissionFile=receiptOption('--output','C2g-engine-admission.json'),stagingFile=admissionFile.replace(/\.json$/,'-staging.json');
const build=read(buildFile);
if(build.exitCode!==0||!build.finishedAt||build.stealth!==false||build.cargoNetwork!==false)throw Error('Completed non-stealth offline build required');
for(const [file,digest] of Object.entries(build.sourceHashes))if(hash(path.join(build.source,file))!==digest)throw Error('Source changed after build: '+file);
const artifacts=build.artifacts;
if(artifacts.length!==2)throw Error('Engine and companion required');
for(const artifact of artifacts){const file=path.join(repo,artifact.path);if(!file.startsWith(path.join(repo,'.agent_control')+path.sep)||hash(file)!==artifact.sha256||fs.statSync(file).size!==artifact.bytes)throw Error('Build artifact changed');}
const directory=path.join(repo,'.agent_control/C2g/obscura-capabilities',artifacts.map(x=>x.sha256.slice(0,12)).join('-'));
fs.mkdirSync(directory,{recursive:true});
const admitted=artifacts.map(artifact=>{const target=path.join(directory,path.basename(artifact.path));if(!fs.existsSync(target))fs.copyFileSync(path.join(repo,artifact.path),target);if(hash(target)!==artifact.sha256)throw Error('Staged artifact changed');return {...artifact,path:path.relative(repo,target).replaceAll('\\','/')};});
const report={schema:'neyvia.C2g.source-fork-admission@1',at:new Date().toISOString(),sourceTag:'v0.2.4',upstream:'https://github.com/h4ckf0r0day/obscura/tree/v0.2.4',engineVersion:build.engineVersion,buildReceipt:buildFile,buildReceiptSha256:hash(buildFile),buildExitCode:build.exitCode,patch:'scripts/obscura-v024-C2g-capabilities.patch',sourcePatchSha256:hash('scripts/obscura-v024-C2g-capabilities.patch'),sourceHashes:build.sourceHashes,additionalPatches:build.additionalPatches||[],engineBinary:admitted.find(x=>path.basename(x.path)==='obscura.exe'),workerBinary:admitted.find(x=>path.basename(x.path)==='obscura-worker.exe'),stealth:false,cargoNetwork:false,systemInstall:false,mechanism:build.sourcePatch.mechanism};
for(const patch of report.additionalPatches)if(hash(patch.path)!==patch.sha256)throw Error('Additional source patch changed after build');
if(process.argv.includes('--stage')){
  fs.writeFileSync(stagingFile,JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify({engine:report.engineBinary.path,receipt:stagingFile,admitted:false}));
}else{
  const file=proofFile,proof=read(file);
  if(proof.engine!=='Obscura'||proof.stealth!==false||proof.error||proof.engineSha256!==report.engineBinary.sha256||!proof.cleanup.engineStopped||!proof.cleanup.fixtureClosed||proof.checks.length<10||proof.checks.some(x=>x.ok!==true))throw Error('Actual matching Obscura journey required before admission');
  report.runtimeProof={path:file,sha256:hash(file),checks:proof.checks.map(({name,ok})=>({name,ok})),capture:proof.capture};
  if(process.argv.includes('--scroll-proof')){
    const file=receiptOption('--scroll-proof','C2g-scroll-background-after.json'),proof=read(file);
    if(proof.engineSha256!==report.engineBinary.sha256||proof.phase!=='after'||proof.error||proof.checks.length!==4||proof.checks.some(x=>x.ok!==true)||!proof.cleanup.engineStopped||!proof.cleanup.fixtureClosed)throw Error('Matching actual fragment screenshot regression proof required');
    report.scrollProof={path:file,sha256:hash(file),checks:proof.checks,captures:proof.captures};
  }
  fs.writeFileSync(admissionFile,JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify({engine:report.engineBinary.path,receipt:admissionFile,admitted:true}));
}
