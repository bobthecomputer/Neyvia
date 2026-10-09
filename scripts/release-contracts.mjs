import { createHash, createPublicKey, verify } from "node:crypto";
import { existsSync, realpathSync } from "node:fs";
import { isAbsolute, join, relative, resolve } from "node:path";
export class ReleaseContractError extends Error {
  constructor(id) { super(`Release contract ${id} failed`); this.name="ReleaseContractError";this.contract=id; }
}
const requireClaim=(ok,id)=>{if(!ok)throw new ReleaseContractError(id);};
const inside=(root,path)=>{const rel=relative(root,path);return rel!=="" && !rel.startsWith("..") && !isAbsolute(rel);};
export function checkVitePhysicalPaths(configuration,workingDirectory){
  const physicalRoot=realpathSync(resolve(workingDirectory,"web"));
  requireClaim(configuration.root===physicalRoot && configuration.resolve?.alias?.["~"]===resolve(physicalRoot,"src") && configuration.build?.outDir===resolve(physicalRoot,"dist"),"release.vite-physical-paths");
  return configuration;
}
export function validateReleaseOutput(repository,output){
  if(!inside(join(repository,"src-tauri","target"),output))throw Error("Output must be a fresh directory inside this worktree src-tauri/target.");
  if(existsSync(output))throw Error("Output already exists; choose a fresh directory to preserve prior releases.");
  return output;
}
export function validateSigningKeyPath(repository,path){
  if(resolve(path)===resolve(repository) || inside(resolve(repository),resolve(path)))throw Error("The release signing key must be outside the worktree.");
  return path;
}
export function checkSignedEnvelope(bytes,comment,pubkey,text){
  const lines=String(text).trimEnd().split("\n"),publicPacket=Buffer.from(pubkey,"base64"),packet=Buffer.from(lines[1] || "","base64"),global=Buffer.from(lines[3] || "","base64");
  requireClaim(lines.length===4 && lines[0]==="untrusted comment: Neyvia manifest signature" && lines[2]===`trusted comment: ${comment}` && publicPacket.length===42 && packet.length===74 && global.length===64 && packet.subarray(0,2).toString()==="Ed" && publicPacket.subarray(0,2).toString()==="Ed" && packet.subarray(2,10).equals(publicPacket.subarray(2,10)),"release.signed-envelope");
  const raw=publicPacket.subarray(10),identity=createHash("sha256").update(raw).digest().subarray(0,8);
  requireClaim(identity.equals(publicPacket.subarray(2,10)),"release.signed-envelope");
  const key=createPublicKey({key:Buffer.concat([Buffer.from("302a300506032b6570032100","hex"),raw]),format:"der",type:"spki"});
  requireClaim(verify(null,bytes,key,packet.subarray(10)) && verify(null,Buffer.concat([packet.subarray(10),Buffer.from(comment)]),key,global),"release.signed-envelope");
  return text;
}
export function checkExternalDeclarations(registry,declarations){
  const expected=Object.entries(registry.packages).filter(([,v])=>!v.localComponents).map(([id])=>id);
  requireClaim(declarations.length===expected.length && declarations.every((row,i)=>row.packId===expected[i] && row.deliveryStatus==="needs-paul" && Array.isArray(row.needsPaul) && row.needsPaul.length && Array.isArray(row.files) && row.files.length && row.totalSize===row.files.reduce((sum,f)=>sum+f.size,0) && row.files.every(f=>Number.isFinite(f.size) && f.size>=0 && /^[a-f0-9]{64}$/.test(f.sha256) && /^https:\/\/(github\.com|files\.pythonhosted\.org)\//.test(f.url) && Boolean(f.source?.version && f.source?.metadataUrl) && f.source.role==="source-input" && f.requiresPaulApproval===(f.size>200_000_000))),"release.external-declarations");
  return declarations;
}
export function checkInstallerBudgetObservation({budget,selectedBundles,artifacts,stagedFiles,stagedBytes,slim},result){
  const reasons=[];
  for(const {key,found} of artifacts.filter(a=>selectedBundles.has(a.key))){const limit=budget.budgets?.[key];if(!limit)continue;if(!found)reasons.push("missing:"+key);else if(found.size>limit.maxBytes)reasons.push("artifact-budget:"+key);}
  if(slim && stagedFiles.length)reasons.push("slim-backend");
  if(!slim){if(!stagedFiles.length)reasons.push("backend-missing");else {
    if(budget.budgets?.stagedResources && stagedBytes>budget.budgets.stagedResources.maxBytes)reasons.push("resources-budget");
    for(const rule of budget.forbiddenContent || [])if(stagedFiles.some(path=>new RegExp(rule.pattern,"i").test(path)))reasons.push("forbidden:"+rule.pattern);
  }}
  requireClaim(result.ok===(reasons.length===0) && JSON.stringify(result.reasons)===JSON.stringify(reasons) && result.violations.length===reasons.length && result.stagedFileCount===stagedFiles.length,"release.installer-budget");
  return result;
}
