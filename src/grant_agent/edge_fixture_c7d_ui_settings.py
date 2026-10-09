"""Settings argument and supplied-storage behavior, explicitly never rendered proof."""
from __future__ import annotations
import json
import subprocess
import uuid
from pathlib import Path

PURE = {"preferences.motion", "preferences.normalize", "orchestration.preset", "orchestration.resolve", "transparency.transition"}
STORED = {"permission.get", "permission.read", "permission.transfer", "permission.write", "transparency.persistence"}
IDS = PURE | STORED
NODE = r'''
import assert from 'node:assert/strict';import fs from 'node:fs';import path from 'node:path';import {pathToFileURL} from 'node:url';
const [repo,root,identity,category]=process.argv.slice(1);const file=path.join(root,'storage.json');
const load=name=>import(pathToFileURL(path.join(repo,'web/src/neyvia',name)));
const text=category==='empty'?'':category==='huge'?'owned supplied argument '.repeat(2048):'雪 café e\u0301 العربية';
const read=()=>JSON.parse(fs.readFileSync(file,'utf8'));const save=value=>fs.writeFileSync(file,JSON.stringify(value));
const storage={getItem:key=>read()[key]??null,setItem:(key,value)=>{const current=read();current[key]=String(value);save(current)},removeItem:key=>{const current=read();delete current[key];save(current)}};
globalThis.localStorage=storage;
if(identity.startsWith('permission.')){
 const p=await load('workspaceToolAccess.js');const key=p.WORKSPACE_PERMISSION_STORAGE_KEY;const scope=p.buildWorkspacePermissionScope('owned',text,'new-chat'),next=p.buildWorkspacePermissionScope('owned',text,'saved');
 if(category==='permissions'){
  if(identity==='permission.write')assert.equal(p.writeWorkspacePermissionMode(storage,scope,'workspace'),false);
  else if(identity==='permission.transfer')assert.equal(p.transferDraftWorkspacePermissionMode(storage,scope,next),false);
  else if(identity==='permission.read')assert.deepEqual(p.readWorkspacePermissionModes(storage),{});
  else assert.equal(p.workspacePermissionModeForScope(storage,scope,'read-only'),'read-only');
 }else{
  assert.equal(p.writeWorkspacePermissionMode(storage,scope,'workspace'),true);assert.equal(p.workspacePermissionModeForScope(storage,scope),'workspace');assert.equal(p.readWorkspacePermissionModes(storage)[scope],'workspace');
  const before=read()[key];assert.equal(p.transferDraftWorkspacePermissionMode(storage,p.buildWorkspacePermissionScope('other',text,'new-chat'),next),false);assert.equal(read()[key],before);
  assert.equal(p.transferDraftWorkspacePermissionMode(storage,scope,next),true);assert.equal(p.workspacePermissionModeForScope(storage,next),'workspace');
  assert.equal(p.writeWorkspacePermissionMode(storage,next,'read-only'),true);const kept=read()[key];assert.equal(p.transferDraftWorkspacePermissionMode(storage,scope,next),false);assert.equal(read()[key],kept);
  if(category==='stale'){const current=read();current[key]=JSON.stringify({[scope]:'full-access',[next]:'read-only'});save(current);assert.equal(p.workspacePermissionModeForScope(storage,scope),'full-access');assert.equal(p.workspacePermissionModeForScope(storage,next),'read-only');assert.equal(p.transferDraftWorkspacePermissionMode(storage,scope,next),false)}
  if(category==='empty'){assert.equal(p.writeWorkspacePermissionMode(storage,'','workspace'),false);const current=read();current[key]='{invalid';save(current);assert.deepEqual(p.readWorkspacePermissionModes(storage),{})}
 }
}else if(identity==='preferences.motion'){
 const p=await load('neyviaMotion.js');const source={reduceMotion:true,effectIntensity:text,transparencyLevel:text};const before=JSON.stringify(source);const out=p.neyviaMotionCssVariables(source);assert.equal(out['--neyvia-motion-fast'],'0ms');assert.equal(out['--neyvia-motion-pulse'],'0ms');assert.equal(out['--neyvia-effect-lift'],'0px');assert.equal(out['--neyvia-surface-opacity'],'97%');assert.equal(out['--neyvia-surface-blur'],'6px');assert.equal(JSON.stringify(source),before);assert.equal(p.neyviaMotionCssVariables({effectIntensity:'off',transparencyLevel:'solid'})['--neyvia-surface-blur'],'0px');
}else if(identity==='preferences.normalize'){
 const p=await load('neyviaShellPreferences.js');const source={uiPreset:text,appearanceTheme:text,colorMode:text,textSize:text,toolbar:[text,text,'attach'],reduceMotion:true};const before=JSON.stringify(source);const out=p.normalizeNeyviaShellPreferences(source);assert.equal(out.uiPreset,'researcher');assert.equal(out.colorMode,'auto');assert.equal(out.textSize,'md');assert.equal(out.reduceMotion,true);assert.ok(out.toolbar.includes('attach'));assert.equal(new Set(out.toolbar).size,out.toolbar.length);assert.equal(JSON.stringify(source),before);
}else if(identity.startsWith('orchestration.')){
 const p=await load('neyviaProductMode.js');const count=category==='huge'?999:category==='empty'?0:text;const roles=p.buildLeadWorkersRoles(count,true);assert.deepEqual(roles.map(r=>r.roleId),['lead',...Array(category==='huge'?4:2).fill('worker'),'integration','barrier']);assert.equal(roles[0].routeSelection.model,'gpt-5.6-sol');assert.equal(roles.at(-1).routeSelection.model,'gpt-5.6-terra');assert.equal(new Set(roles.map(r=>r.id)).size,roles.length);
 const input={conversationId:'owned',objective:text,metadata:{teamSelection:{mode:'explicit',roles:[' planner ','executor','verifier']},routeSnapshot:{planner:{runtimeId:'codex',model:'owned',objective:text}}}};const before=JSON.stringify(input);const resolved=p.resolveOrchestrationRoles(input,[],'hermes');assert.deepEqual(resolved.map(r=>r.roleId),['planner','executor','verifier']);assert.equal(resolved[0].routeSelection.model,'owned');assert.equal(resolved[0].runtime,'codex');assert.equal(JSON.stringify(input),before);assert.deepEqual(p.resolveOrchestrationRoles({},roles,'codex'),roles);
}else{
 const p=await load('next/nxOsStore.js');const initial=p.initialOsState({transparency:text});assert.equal(initial.transparency,'everything');const before=JSON.stringify(initial);for(const level of ['everything','summaries','minimal']){const out=p.reduceUiAction(initial,'view.transparency',{level});assert.equal(out.transparency,level);assert.equal(JSON.stringify(initial),before)}assert.throws(()=>p.reduceUiAction(initial,'view.transparency',{level:text}));
 if(identity==='transparency.persistence'){p.os.setTransparency('minimal');assert.equal(p.getOs().transparency,'minimal');if(category!=='permissions')assert.equal(read()['nx.os.transparency'],JSON.stringify('minimal'));p.os.setTransparency('summaries');assert.equal(p.getOs().transparency,'summaries');if(category!=='permissions')assert.equal(read()['nx.os.transparency'],JSON.stringify('summaries'))}
}
console.log(JSON.stringify({actualProductionArgumentModel:true,fileBackedSuppliedStorage:true,renderedProof:false,identity,category}));
if(category==='interrupted')process.exit(23);
'''


def blocker(contract, category):
    identity = contract.get("id", "")
    if identity not in IDS:
        return None
    if identity in PURE and category not in {"empty", "huge", "unicode"}:
        return {"kind": "not_applicable", "reason": f"Exact {identity} computes a CSS value map, normalized preference, supplied role descriptor or immutable reducer transition. It never renders, grants OS authority, executes a role, writes storage, starts a worker or compares a shared revision."}
    if identity in STORED and category in {"concurrency", "offline"}:
        return {"kind": "not_applicable", "reason": f"Exact {identity} is a synchronous single-realm supplied-storage read or read/merge/write, with no await, worker, endpoint or CAS/version admission. It declares no cross-device/cross-process atomicity. Actual read/write denial and retained destination-scope behavior are exercised; these model helpers never count as rendering or executed tool authority."}
    if identity in {"permission.get", "permission.read"} and category == "interrupted":
        return {"kind": "not_applicable", "reason": "Exact getter reads supplied storage and returns a value synchronously without a durable effect or interruption receipt; storage-writer process exit is independently exercised."}
    return None


def run(root, contracts, categories):
    from .edge_fixture_models import _deny_read
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    repo = Path(__file__).resolve().parents[2]; rows = []
    for identity in sorted(IDS & contracts.keys()):
        for category in categories:
            if blocker(contracts[identity], category):
                continue
            area = Path(root) / (identity.replace('.', '-') + '-' + category + '-' + uuid.uuid4().hex[:8]); area.mkdir(parents=True)
            source = area / "storage.json"
            source.write_text(json.dumps({"fluxio.chat.workspacePermissionModes": json.dumps({json.dumps(["owned", "雪 café e\u0301 العربية", "new-chat"], ensure_ascii=False, separators=(',', ':')): "workspace"})}), encoding="utf-8")
            command = ["node", "--input-type=module", "-e", NODE, str(repo), str(area), identity, category]
            if category == "permissions":
                with _deny_read(source):
                    result = subprocess.run(command, cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=30, **hidden_windows_subprocess_kwargs())
            else:
                result = subprocess.run(command, cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=30, **hidden_windows_subprocess_kwargs())
            ok = result.returncode == (23 if category == "interrupted" else 0)
            rows.append({"id": "c7d-ui-settings." + identity + "." + category, "contracts": [identity], "category": category,
                         "status": "passed" if ok else "failed", "detail": json.loads(result.stdout) if ok else result.stderr[-2500:],
                         "proofType": "production_argument_model", "boundary": "Supplied storage and argument models only; no rendered CSS, browser storage, provider execution or OS permission grant proof"})
    return rows
