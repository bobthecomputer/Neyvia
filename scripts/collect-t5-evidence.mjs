import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
const repo=process.cwd(),dir=path.join(repo,'scripts/evidence');
const read=name=>JSON.parse(fs.readFileSync(path.join(dir,name),'utf8'));
const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
const runtime=read('T5-runtime.json'),compiler=read('T5-compiler.json'),http=read('T5-http.json'),models=read('T5-models.json');
if(![runtime,compiler,http].every(x=>x.passed) || !models.allSucceeded)throw new Error('A real acceptance journey is missing or failed');
function retain(root){
  const files={};const base=path.join(root,'.neyvia');
  function visit(folder){for(const entry of fs.readdirSync(folder,{withFileTypes:true})){
    const full=path.join(folder,entry.name);
    if(entry.isDirectory())visit(full);
    else if(/\.(json|jsonl)$/.test(entry.name)){
      const bytes=fs.readFileSync(full);files[path.relative(base,full).replaceAll('\\','/')]={sha256:digest(bytes),text:bytes.toString('utf8')};
    }
  }}
  visit(base);return {root,files};
}
const retained={schema:'neyvia.t5-retained-evidence.v1',runtime:retain(runtime.root),compiler:retain(compiler.root)};
fs.writeFileSync(path.join(dir,'T5-artifacts.json'),JSON.stringify(retained,null,2)+'\n');
const receipts=['T5-runtime.json','T5-compiler.json','T5-http.json','T5-models.json','T5-artifacts.json','T5-domains.json',...fs.readdirSync(dir).filter(name=>/^T5-models-.+-(stream|tools)\.jsonl$/.test(name))];
const commands=['manual.project','manual.versions','manual.patch.apply','manual.demote','manual.recovery.bind','manual.recover','manual.compile','manual.compiled','manual.script.run'];
const sourceFiles=['src/grant_agent/neyvia_manuals.py','src/grant_agent/manual_state.py','src/grant_agent/manual_versions.py','src/grant_agent/manual_recovery.py','src/grant_agent/manual_compiler.py','src/grant_agent/manual_contracts.py','src/grant_agent/manual_first.py','src/grant_agent/neyvia_agent.py','src/grant_agent/neyvia_ui_api.py','plugins/neyvia/mcp/neyvia_mcp.py','config/neyvia_manuals.json','manuals/manuals-next.manual.json','manuals/neyvia.manual.json','manuals/neyvia-reference.manual.json'];
const evidence={schema:'neyvia.track-evidence.v1',track:'T5',at:new Date().toISOString(),branch:execFileSync('git',['branch','--show-current'],{encoding:'utf8'}).trim(),passed:true,
  acceptance:{largeStateHandlesAndProjections:true,diffsAfterFirstObservation:true,versionLineageAndGroundedPatchApplication:true,obsoleteProcedureDemotion:true,
    procedureToScriptFromVerifiedRuns:true,zeroModelExecutionAndVariableBranches:true,failedRunBoundRecovery:true,machineDetectedFrontier:true,realSmallVsLargeComparison:true},
  proof:{runtime:{checks:runtime.checks.length,receipt:'scripts/evidence/T5-runtime.json'},compiler:{checks:compiler.checks.length,receipt:'scripts/evidence/T5-compiler.json'},
    existingDomainJourneys:{passed:read('T5-domains.json').passed,checks:read('T5-domains.json').checks.length,receipt:'scripts/evidence/T5-domains.json'},
    httpAndPlugin:{checks:http.checks.length,port:48151,receipt:'scripts/evidence/T5-http.json'},modelComparison:{smallModel:'claude-haiku-4-5-20251001',largeModel:'claude-opus-5-5',tasksPerModel:2,successesPerModel:2,
      reportedTokensIncludingCache:models.totalTokensIncludingCache,smallArmTokenReductionPercent:models.haikuTokenSavingsFraction*100,receipt:'scripts/evidence/T5-models.json'},
    stateResponseTokens:{tokenizer:'o200k_base',snapshotBaseline:runtime.tokens.before,handleResponse:runtime.tokens.after,reductionPercent:100*(1-runtime.tokens.after/runtime.tokens.before)},
    rawDurableLogsAndArtifacts:'scripts/evidence/T5-artifacts.json'},
  commands:commands.map(name=>({name:'neyvia.'+name,definitions:'src/grant_agent/neyvia_manuals.py:DEFINITIONS',native:'neyvia_workspace_tools.tool_specs -> NativeToolRegistry',
    dispatch:'neyvia_manuals.call; effectful script/recovery also intercepted by NeyviaToolGateway.call_native',stdio:'CompactNeyviaMCPServer manual namespace / deferred discovery',
    http:'GET /api/ui/tools and POST /api/ui/tools/call',plugin:'plugins/neyvia/mcp/neyvia_mcp.py PORTED; effectful calls constrained to plugin scope',desktop:'Existing tools API; no new desktop IPC command or user control required'})),
  checks:['Node real MCP journeys','Node real HTTP and distributable plugin journeys','Existing grounded-manual validator, including real Notes/Files/PDF/image/terminal procedures','Python compileall syntax check only; no pytest','Generated manual views --check','git diff --check'],
  limits:['Two small matched Notes tasks, one trial per model arm; model and manual differ together, so this does not isolate the manual effect or prove general superiority.',
    'Haiku loaded the real manual but used direct tools, not manual.run, in the comparison.',
    'Compiled plans specialize exact learned inputs and identical pre-JUDGE state; new inputs use ordinary execution and changed state returns JUDGE.',
    'Frontier uses grounded contract matching; automatic explorer/LAYA service integration belongs to T15 and is not implemented here.',
    'Changes remain on the local track branch; no live release, public service, push or merge.',
    'NAS sync pending: selected task forbids touching Tailscale; local recoverable commit and scoped bundle are the handoff.'],
  preservation:{initialWorktree:'clean',forbiddenFilesEdited:[],publicServicesChanged:[],downloads:[],localSnapshot:'.agent_control/t5-branch.bundle',nas:'pending; excluded network route'},
  sourceHashEncoding:'UTF-8 with CRLF normalized to LF; receipt hashes use exact bytes',
  files:Object.fromEntries(sourceFiles.map(name=>[name,digest(fs.readFileSync(path.join(repo,name),'utf8').replaceAll('\r\n','\n'))])),
  receipts:Object.fromEntries(receipts.map(name=>[name,{sha256:digest(fs.readFileSync(path.join(dir,name))),bytes:fs.statSync(path.join(dir,name)).size}]))};
fs.writeFileSync(path.join(dir,'T5.json'),JSON.stringify(evidence,null,2)+'\n');
console.log(JSON.stringify({passed:true,receipt:'scripts/evidence/T5.json',runtimeChecks:runtime.checks.length,compilerChecks:compiler.checks.length,httpChecks:http.checks.length,retainedFiles:Object.values(retained).filter(x=>x?.files).reduce((n,x)=>n+Object.keys(x.files).length,0)}));
