#!/usr/bin/env node
// Explicit proof fixture port selection (int3_ports.py).
import { execFileSync as proofExecFileSync } from 'node:child_process';
import { fileURLToPath as proofFileURLToPath } from 'node:url';
const proofPortSelection = process.env.NEYVIA_PROOF_PORT_MAP === undefined ? null : JSON.parse(proofExecFileSync(
  process.env.NEYVIA_SYSTEM_PYTHON || process.env.PYTHON || 'python',
  [proofFileURLToPath(new URL('../src/grant_agent/proof_ports.py', import.meta.url))],
  { encoding: 'utf8', env: process.env }).trim());
function proofPort(original) { return proofPortSelection === null ? original : proofPortSelection[String(original)]; }
function proofText(text) { return text.replace(/(?<!\d)(48461|48462|48463|48465|48466|48467|48468|48469|48472|48473|48474|48475|48476|48477|48478|48479|48481|48487|48488|48489|48491|48492|48494|48495|48496|48497|48498|48499|48501|48502|48503|48508|48509)(?!\d)/g, value => String(proofPort(Number(value)))); }
import { generateKeyPairSync } from "node:crypto";
import { readFile, writeFile, mkdir, open, mkdtemp } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { resolve, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { signerFromKey, signer, prepareRelease, externalPackDeclarations, REPO } from "./prepare_slim_release.mjs";
import { inspectInstallerBudget } from "./check_installer_size.mjs";
import { checkSignedEnvelope, checkExternalDeclarations, checkInstallerBudgetObservation, checkVitePhysicalPaths, ReleaseContractError } from "./release-contracts.mjs";
const python="C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe";
const require=(ok,message)=>{if(!ok)throw Error(message);};
export async function runProofsERelease({root=resolve(REPO,".agent_control/proofs/proofs-e-release")}={}){
  const started=performance.now(),manual=JSON.parse(await readFile(join(REPO,"config/proofs/proofs-e-release.json"),"utf8")),failures=[],procedures=[],observers=[];
  await mkdir(root,{recursive:true}); const scratch=await mkdtemp(join(resolve(root),"run-"));
  const corruption=(id,call)=>{let rejected=false;try{call();}catch(error){rejected=error instanceof ReleaseContractError && error.contract===id;}require(rejected,"Corrupt observation escaped "+id);observers.push({id,status:"passed",corrupt_result_rejected:true});};
  async function procedure(id,call){try{const detail=await call();procedures.push({id,status:"passed",...detail});}catch(error){failures.push({id,error:error.message});procedures.push({id,status:"failed",error:error.message});}}
  await procedure("release.vite-physical-paths",async()=>{
    const settings={TAURI_DEV_HOST:"127.0.0.1",TAURI_DEV_PORT:proofText("48502"),FLUXIO_WEB_BACKEND_URL:proofText("http://127.0.0.1:48501")};
    const prior=Object.fromEntries(Object.keys(settings).map(key=>[key,process.env[key]]));
    try{
      Object.assign(process.env,settings);
      const url=pathToFileURL(join(REPO,"vite.config.mjs"));url.searchParams.set("proofs-e",String(performance.now()));
      const {default:evaluate}=await import(url.href);
      for(const command of ["build","serve"]){
        const configuration=evaluate({command,mode:"production"});checkVitePhysicalPaths(configuration,REPO);
        require(configuration.server.port===proofPort(48502) && configuration.server.proxy["/api"]===proofText("http://127.0.0.1:48501"),"Explicit isolated config ports were not retained");
        if(command==="build")corruption("release.vite-physical-paths",()=>checkVitePhysicalPaths({...configuration,resolve:{...configuration.resolve,alias:{"~":join(REPO,"incorrect-source")}}},REPO));
      }
      return {actualConfigEvaluations:2,physicalPathsChecked:true,devPort:proofPort(48502),backendPort:proofPort(48501),serverStarted:false,desktopLoaderExecuted:false};
    }finally{for(const [key,value] of Object.entries(prior)){if(value===undefined)delete process.env[key];else process.env[key]=value;}}
  });
  await procedure("release.ephemeral-signed-manifest",()=>{
    const {privateKey}=generateKeyPairSync("ed25519"),signing=signerFromKey(privateKey),bytes=Buffer.from('{"schema":"neyvia.base-pack/v1","packId":"fixture"}\n'),comment="pack=fixture version=1",signed=signing.sign(bytes,comment);
    checkSignedEnvelope(bytes,comment,signing.pubkey,signed);
    corruption("release.signed-envelope",()=>checkSignedEnvelope(Buffer.concat([bytes,Buffer.from("tamper")]),comment,signing.pubkey,signed));
    let changedCommentRejected=false;try{checkSignedEnvelope(bytes,comment+" altered",signing.pubkey,signed);}catch(error){changedCommentRejected=error instanceof ReleaseContractError;}
    require(changedCommentRejected,"Comment alteration escaped signature");return {keyFileRead:false,manifestByteTamperRejected:true,commentTamperRejected:true};
  });
  await procedure("release.staging-denials",()=>{
    let unsafe=false,insideKey=false;
    try{prepareRelease({output:join(scratch,"outside-release-target")});}catch(error){unsafe=/inside this worktree/.test(error.message);}
    try{signer(join(REPO,"fixture-key-never-read.pem"));}catch(error){insideKey=/outside the worktree/.test(error.message);}
    require(unsafe && insideKey,"Release path denial failed");observers.push({id:"release.staging-boundary",status:"passed",invalid_destination_rejected:true});return {outOfTreeDenied:true,inTreeKeyDenied:true,keyFileRead:false,releaseStaged:false};
  });
  await procedure("release.installer-scanner",async()=>{
    const budget=JSON.parse(await readFile(join(REPO,"src-tauri/installer-budget.json"),"utf8")),empty=join(scratch,"empty-target");await mkdir(empty);
    const cli=spawnSync(process.execPath,[join(REPO,"scripts/check_installer_size.mjs"),"--slim","--bundles","nsis"],{encoding:"utf8",env:{...process.env,CARGO_TARGET_DIR:empty}});
    require(cli.status!==0 && /requested artifact was not built/.test(cli.stderr),"Missing installer was accepted by actual CLI");
    const target=join(scratch,"scanner-target"),bundle=join(target,"release/bundle/nsis");await mkdir(bundle,{recursive:true});await writeFile(join(bundle,"fixture.exe"),"size scanner fixture");
    const clear=inspectInstallerBudget({targetRoot:target,slim:true,bundles:["nsis"]});require(clear.ok,"Empty slim backend and small artifact failed budget");
    const backend=join(target,"release/backend/node_modules");await mkdir(backend,{recursive:true});await writeFile(join(backend,"fixture.js"),"scoped fixture");
    const slim=inspectInstallerBudget({targetRoot:target,slim:true,bundles:["nsis"]}),full=inspectInstallerBudget({targetRoot:target,slim:false,bundles:["nsis"]});
    require(slim.reasons.includes("slim-backend") && full.reasons.some(reason=>reason.startsWith("forbidden:")),"Forbidden resources were accepted");
    const oversized=join(bundle,"oversized.exe"),handle=await open(oversized,"w");await handle.truncate(budget.budgets.nsis.maxBytes+1);await handle.close();
    require(inspectInstallerBudget({targetRoot:target,slim:true,bundles:["nsis"]}).reasons.includes("artifact-budget:nsis"),"Oversize artifact was accepted");
    corruption("release.installer-budget",()=>checkInstallerBudgetObservation({budget,selectedBundles:new Set(["nsis"]),artifacts:[{key:"nsis",found:null}],stagedFiles:[],stagedBytes:0,slim:true},{ok:true,reasons:[],violations:[],stagedFileCount:0}));
    return {actualCliMissingDenied:true,scopedArtifactsInspected:2,slimBackendDenied:true,forbiddenContentDenied:true,oversizedArtifactDenied:true,installerBuildExecuted:false};
  });
  await procedure("release.external-source-declarations",async()=>{
    const registry=JSON.parse(await readFile(join(REPO,"config/onboarding_packs.json"),"utf8")),declarations=externalPackDeclarations(registry);
    require(declarations.length>0,"No external declarations to inspect");
    const damaged=declarations.map((row,i)=>i?row:{...row,totalSize:row.totalSize+1});
    corruption("release.external-declarations",()=>checkExternalDeclarations(registry,damaged));return {declarationsObserved:declarations.length,downloadsExecuted:false,activationClaimed:false};
  });
  const environment={...process.env,PYTHONPATH:join(REPO,"src"),PYTHONDONTWRITEBYTECODE:"1"};
  delete environment.NEYVIA_MCP_BROKER_CONFIG;
  await procedure("runtime-and-impact.actual-files",()=>{
    const child=spawnSync(python,[join(REPO,"scripts/proofs_e_release_child.py"),join(scratch,"python")],{cwd:scratch,env:environment,encoding:"utf8",maxBuffer:8*1024*1024});
    require(child.status===0,child.stderr || "Python observer did not complete");const report=JSON.parse(child.stdout);require(report.ok,"Python observers failed");observers.push(...report.contracts);procedures.push(...report.procedures);return {childMs:report.elapsedMs,providerLaunched:false};
  });
  for(const declared of manual.contracts)if(!observers.some(row=>row.id===declared.id && row.status==="passed"))failures.push({id:declared.id,error:"Missing real contract witness"});
  const report={area:manual.area,status:failures.length?"failed":"passed",ok:!failures.length,scratchRoot:resolve(root),contractCount:manual.contracts.length,contracts:observers.map(row=>({id:row.id,status:row.status})),observers,procedures,coverage:manual.coverage,failures,elapsedMs:Math.round((performance.now()-started)*100)/100,boundary:"Actual physical Vite config paths, Ed25519 bytes/comment binding, read-only artifact scanner, checked pinned metadata, isolated on-disk capability inventory and static impact graph. No services, loader hooks, key files, installer build, provider launch, download or publication."};
  await writeFile(join(root,"proofs-e-release-receipt.json"),JSON.stringify(report,null,2)+"\n");return report;
}
if(process.argv[1] && resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const args=process.argv.slice(2),at=args.indexOf("--root");if(at>=0 && !args[at+1])throw Error("--root requires directory");
  const report=await runProofsERelease({root:at<0?undefined:resolve(args[at+1])});console.log(JSON.stringify(report,null,args.includes("--json")?0:2));process.exitCode=report.ok?0:1;
}
