#!/usr/bin/env node
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { PROOFS_E_MODEL_CONTRACTS as registry, checkedProofsEModel, ProofsEContractError, observeProofsEModels, same } from "../web/src/neyvia/next/nxProofsEContracts.js";
const repository=fileURLToPath(new URL("../",import.meta.url));
const modules={};
for(const name of ["Autopilot","Composer","Conductor","Cua","Devices","GameDev","Layout","Missions","NightShift","Onboarding","Outputs","Placement","Plan","Replay","Runtime","Dashboard","AppSkin"]) modules[name.toLowerCase()]=await import(`../web/src/neyvia/next/nx${name}Model.js`);
const atPath=(value,path)=>path?path.split(".").reduce((v,k)=>v?.[k],value):value;
const corrupt=(value)=>typeof value==="string"?"\0"+value:typeof value==="boolean"?!value:typeof value==="number"?value+1:value===null?{}:Array.isArray(value)?value.length?value.slice(1):[{}]:{...value,__unclaimed:true};
function damaged(id,result) {
  if(id==="composer.attachResult") return 99;
  if(id==="composer.draftUpdate") return [...result];
  const key={"autopilot.attributeCalls":"perItem","autopilot.shapeRun":"totalTokens","conductor.shapeJob":"canStart","missions.shapeMission":"progress","nightshift.shapeBoard":"missionCount","nightshift.morning":"unknownRuns","nightshift.treeLayout":"leaves","nightshift.policyForm":"maxTaskMinutes","nightshift.policyPatch":"patch","onboarding.timeline":"totalMs"}[id];
  if(key) return {...result,[key]:corrupt(result[key])};
  if(id==="runtime.mergeRuntimes")return result.map((row,i)=>i?row:{...row,ceiling:"ungranted"});
  return corrupt(result);
}
function resolveArgs(value,values){
  if(value && typeof value==="object" && !Array.isArray(value)){
    if(value.$catalog === "onboarding") return values.get("_catalog");
    if(value.$appSkinCount)return modules.appskin.SKINS.length*modules.appskin.THEME_IDS.length; // every skin in every theme of the registry (nxThemeRegistry.js), never a hard-coded count
    if(value.$ref)return atPath(values.get(value.$ref),value.path);
    if(value.$date)return new Date(value.$date);
    if(value.$repeat)return Array.from({length:value.count},(_,i)=>resolveArgs({...value.$repeat,name:`item-${i}`},values));
    if(value.$image)return {id:value.id || "photo",name:value.name || "photo.png",mime:value.mime || "image/png",data:"A".repeat(value.$image)};
    return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,resolveArgs(v,values)]));
  }
  return Array.isArray(value)?value.map(v=>resolveArgs(v,values)):value;
}
async function drafts(procedures,failures,witnesses){
  const c=modules.composer,store=c.createDraftStore(),seen=[];
  const read=async files=>{seen.push(...files.map(f=>f.name));return files.map(f=>({id:f.name,name:f.name,mime:f.type,data:"A".repeat(f.realSize || 8)}));};
  let error;
  try{
    const refusal=await c.attachToDraft(store,"origin",[{name:"unsupported.txt",size:2,type:"text/plain"},{name:"misreported.png",size:3,type:"image/png",realSize:12*1024*1024+1}],read);
    if(!same(seen,["misreported.png"]) || store.get("origin").length || !/unsupported/.test(refusal) || !/larger/.test(refusal))throw Error("Admission/read/byte gate failed");
    let finish;
    const pending=c.attachToDraft(store,"origin",[{name:"later.png",size:4,type:"image/png"}],files=>new Promise(resolve=>{finish=()=>resolve(files.map(f=>({id:f.name,name:f.name,mime:f.type,data:"QUJD"})));}));
    const other=[{id:"other",name:"other",mime:"image/png",data:"AAAA"}];store.update("other",other);finish();
    if(await pending!=="" || store.get("origin")[0]?.name!=="later.png" || store.get("other")!==other)throw Error("Async origin routing failed");
    const sent=new Set(store.get("origin").map(i=>i.id));store.update("origin",current=>[...current,{id:"new",name:"new",mime:"image/png",data:"AAAA"}]);store.update("origin",current=>current.filter(i=>!sent.has(i.id)));
    if(store.get("origin")[0]?.id!=="new" || store.get("other")!==other || store.get("empty-a")!==store.get("empty-b"))throw Error("Selective send cleanup failed");
  }catch(e){error=e.message;failures.push({id:"composer.draft-lifecycle",error});}
  procedures.push({id:"composer.draft-lifecycle",status:error?"failed":"passed",readFiles:seen.length,lateOriginConfirmed:!error});
}
export async function runProofsEModels({root=resolve(repository,".agent_control/proofs/proofs-e-models")}={}){
  const started=performance.now(),manual=JSON.parse(await readFile(resolve(repository,"config/proofs/proofs-e-models.json"),"utf8")),catalog=JSON.parse(await readFile(resolve(repository,"config/neyvia_onboarding.json"),"utf8")),procedures=[],failures=[],witnesses=new Map(),hits=new Map();
  observeProofsEModels((id,args,result)=>{witnesses.set(id,{args,result});hits.set(id,(hits.get(id)||0)+1);});
  try{
    for(const procedure of manual.procedures){const values=new Map([["_catalog",catalog]]);let calls=0,error;
      try {for(const action of procedure.actions){let result,thrown=false;
        try {result=await modules[action.module][action.function](...resolveArgs(action.args,values));} catch(e){if(!action.refuses || !(new RegExp(action.refuses)).test(e.message))throw e;thrown=true;}
        calls++;if(action.refuses && !thrown)throw Error("Invalid action was accepted");
        if(!thrown){if(action.saveAs)values.set(action.saveAs,result);for(const goal of action.goals || []){const observed=atPath(result,goal.path),expected=resolveArgs(goal.value,values);if(goal.match?!new RegExp(goal.match).test(String(observed)):!same(observed,expected))throw Error(`Procedure goal ${goal.path || "result"} was not reached`);}}
      }}catch(e){error=e.message;failures.push({id:procedure.id,error});}
      procedures.push({id:procedure.id,status:error?"failed":"passed",calls,...(error?{error}:{})});
    }
    await drafts(procedures,failures,witnesses);
  }finally{observeProofsEModels(null);}
  const observers=[];
  for(const [id,contract] of Object.entries(registry)){
    const witness=witnesses.get(id);let rejected=false;
    if(witness)try{checkedProofsEModel(id,witness.args,damaged(id,witness.result));}catch(e){rejected=e instanceof ProofsEContractError && e.contract===id;}
    observers.push({id,status:witness&&rejected?"passed":"failed",realCalls:hits.get(id)||0,corrupt_result_rejected:rejected});
    if(!witness || !rejected)failures.push({id,error:!witness?"Missing real action witness":"Corrupt output escaped postcondition"});
  }
  const report={area:manual.area,status:failures.length?"failed":"passed",ok:!failures.length,scratchRoot:resolve(root),contractCount:Object.keys(registry).length,contracts:observers.map(o=>({id:o.id,status:o.status})),procedures,observers,coverage:manual.coverage,elapsedMs:Math.round((performance.now()-started)*100)/100,failures,boundary:"Real model transformations and draft store lifecycle; frontend rendering, remote engines and provider/device actions remain separate boundaries"};
  await mkdir(root,{recursive:true});await writeFile(resolve(root,"proofs-e-models-receipt.json"),JSON.stringify(report,null,2)+"\n");return report;
}
if(process.argv[1] && resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const args=process.argv.slice(2),flag=args.indexOf("--root");if(flag>=0 && !args[flag+1])throw Error("--root requires a scratch directory");
  const report=await runProofsEModels({root:flag<0?undefined:resolve(args[flag+1])});console.log(JSON.stringify(report,null,args.includes("--json")?0:2));process.exitCode=report.ok?0:1;
}
