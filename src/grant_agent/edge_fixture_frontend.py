"""Generated image/PDF model scenarios; no rendering or provider claim."""
from __future__ import annotations
from .subprocess_utils import hidden_windows_subprocess_kwargs
import json
import subprocess
from pathlib import Path

IDS = {'image.payload.geometry', 'image.layers.selection', 'image.layers.update',
       'image.layers.delete', 'image.history.focus', 'image.history.annotations',
       'image.history.thread', 'image.keyboard.announcement', 'image.keyboard.trail',
       'image.keyboard.entry', 'image.keyboard.tooltip', 'pdf.text-geometry',
       'pdf.search', 'pdf.zoom', 'pdf.page'}

NODE = r'''
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
const [repo,category]=process.argv.slice(1);
const m=await import(pathToFileURL(path.join(repo,'web/src/neyvia/imagePlaygroundState.js')));
const p=await import(pathToFileURL(path.join(repo,'web/src/neyvia/next/nxPdfModel.js')));
const text=category==='empty'?'':category==='huge'?'long '.repeat(14000):'雪🙂e\u0301 العربية';
const rows=[];
function record(contract,fn){try{const detail=fn();rows.push({contract,status:'passed',detail:detail||{inputCharacters:text.length}})}catch(error){rows.push({contract,status:'failed',detail:String(error.stack||error)})}}
function project(){return {canvas:{width:100,height:80},prompt:{text,negative:text,style:text,preserveComposition:true},provider:{id:'local-reference-only'},selection:{x:-2.7,y:6.3,width:0,height:-4,feather:-1},designReferences:[],layers:[{id:'a',name:text,type:'shape',x:3.6,y:-1.2,width:20.4,height:10.5,visible:true},{id:'b',name:'other',type:'shape',x:7,y:8,width:9,height:10,visible:false}],selectedLayerId:'a',history:[{id:'h',requestId:'request'+text,receipt:{promptHash:'receipt'},provider:'openai',annotationSnapshot:{pins:[{text}],rectangles:[],comments:[],layers:[]}}, {id:'other-h',requestId:'other',receipt:{promptHash:'other'},provider:'openai'}],focusedHistoryId:'h',opsThreads:[]};}
record('image.payload.geometry',()=>{const model=project();const r=m.projectToProviderPayload(model,'edit',{snapshotDataUrl:text});assert.equal(r.prompt.text,text);assert.equal(r.inputs.snapshotDataUrl,text);assert.equal(r.inputs.visibleLayerCount,1);assert.deepEqual(r.inputs.editRegion,{x:-3,y:6,width:0,height:-4,feather:-1});assert.equal(r.layers[0].x,4);assert.equal(r.layers[0].y,-1);assert.equal(r.canvas.width,100);});
record('image.layers.selection',()=>{const before=project();const r=m.createLayerFromSelection(before,{id:'chosen',name:text});const layer=r.layers.at(-1);assert.equal(layer.id,'chosen');assert.equal(r.selectedLayerId,'chosen');assert.deepEqual(r.layers.slice(0,2),before.layers);assert.equal(layer.width,1);assert.equal(layer.height,1);assert.equal(layer.mask.feather,0);assert.equal(layer.x,-3);});
record('image.layers.update',()=>{const before=project();const frozen=JSON.stringify(before);const r=m.updateLayerInProject(before,'a',{name:text,x:99});assert.equal(r.layers[0].name,text);assert.equal(r.layers[0].x,99);assert.deepEqual(r.layers[1],before.layers[1]);assert.equal(JSON.stringify(before),frozen,'An addressed layer patch must not mutate its caller input or unrelated design references');});
record('image.layers.delete',()=>{const before=project();const r=m.removeLayerFromProject(before,'a');assert.deepEqual(r.layers,[before.layers[1]]);assert.equal(r.selectedLayerId,'b');const one=m.removeLayerFromProject(r,'b');assert.deepEqual(one.layers,r.layers);const stale=m.removeLayerFromProject(r,'missing');assert.deepEqual(stale.layers,r.layers);});
record('image.history.focus',()=>{const before=project();const r=m.setFocusedHistoryItem(before,'h');assert.equal(r.focusedHistoryId,'h');assert.deepEqual(r.annotationReadiness.pins,[{text}]);const missing=m.setFocusedHistoryItem(before,'missing'+text);assert.equal(missing.focusedHistoryId,'');assert.deepEqual(missing.annotationReadiness.pins,[]);});
record('image.history.annotations',()=>{const before=project();const r=m.updateFocusedHistoryAnnotations(before,{comments:[{text}]});assert.deepEqual(r.annotationReadiness.comments,[{text}]);assert.deepEqual(r.history.find(x=>x.id==='h').annotationSnapshot.comments,[{text}]);assert.deepEqual(r.history.find(x=>x.id==='other-h'),before.history[1]);});
record('image.history.thread',()=>{const before=project();const r=m.createOpsThreadForFocusedHistory(before,{title:text});const twice=m.createOpsThreadForFocusedHistory(r,{title:'different'});const h=twice.history.find(x=>x.id==='h');const thread=twice.opsThreads.find(x=>x.id===h.issueThread.id);assert.equal(thread.requestId,'request'+text);assert.equal(thread.receiptHash,'receipt');assert.equal(twice.opsThreads.length,1);assert.equal(twice.annotationReadiness.activeThreadRef,thread.id);assert.equal(h.issueThread.href,'#issue-thread-'+encodeURIComponent(thread.id));});
const change={fromScope:'queue',fromIndex:9,fromCount:99,toScope:'history',toIndex:1,toCount:2,reason:'group-jump'};
record('image.keyboard.announcement',()=>{assert.equal(m.buildKeyboardTraversalAnnouncement(change),'Queue 9/99 -> History 1/2');assert.equal(m.buildKeyboardTraversalAnnouncement({...change,reason:text}),'History 1/2 focused');});
record('image.keyboard.trail',()=>{const count=category==='huge'?3000:2;const trail=Array.from({length:count},(_,i)=>({announcement:text,at:String(i)}));const r=m.appendKeyboardJumpTrail(trail,change,{maxEntries:3,at:text||'fixed'});assert.equal(r.length,Math.min(count+1,3));assert.deepEqual(r.slice(0,-1),trail.slice(-2));assert.equal(r.at(-1).at,text||'fixed');assert.equal(r.at(-1).reason,'group-jump');});
record('image.keyboard.entry',()=>{assert.equal(m.formatKeyboardJumpTrailEntry({announcement:text,at:'not-a-date'}),'Recently '+(text.trim()||'Traversal'));assert.equal(m.formatKeyboardJumpTrailEntry({announcement:text}),(text.trim()||'Traversal'));});
record('image.keyboard.tooltip',()=>{assert.equal(m.formatKeyboardJumpTrailTooltip({announcement:text,reason:'group-jump',at:'not-a-date'}),'Scope jump • '+(text.trim()||'Traversal'));});
record('pdf.text-geometry',()=>{const item={str:text,width:60,height:10,transform:[1,0,0,10,7,20]};const total=Math.max(1,text.length);assert.deepEqual(p.itemRect(item,0,total),[7,17.8,67,28.8]);});
record('pdf.search',()=>{const source=text+'needle needle';const item={str:source,width:source.length,height:10,transform:[1,0,0,10,0,20]};const pages=[{page:1,items:[item]}];const hits=p.searchTexts(pages,'NEEDLE',2);assert.equal(hits.length,2);assert.equal(hits[0].page,1);assert.equal(hits[0].rect[0],text.length);assert.equal(hits[1].rect[0],text.length+7);assert.deepEqual(p.searchTexts(pages,category==='empty'?'':text+'absent'),[]);assert.equal(p.searchTexts(pages,'needle',1).length,1);});
record('pdf.zoom',()=>{const scale=category==='empty'?0:category==='huge'?1e12:1.25;assert.equal(p.stepZoom(scale,1),category==='empty'?0.5:category==='huge'?3:1.5);assert.equal(p.stepZoom(scale,-1),category==='empty'?0.5:category==='huge'?3:1);});
record('pdf.page',()=>{assert.equal(p.clampPage(text,4),1);assert.equal(p.clampPage(1e12,4),4);assert.equal(p.clampPage(-100,4),1);assert.equal(p.clampPage(2.7,4),3);});
console.log(JSON.stringify(rows));
'''


def run(root, contracts, categories):
    repo = Path(__file__).resolve().parents[2]
    rows = []
    for category in categories:
        if category not in {'empty', 'huge', 'unicode'}:
            continue
        result = subprocess.run(['node', '--input-type=module', '-e', NODE, str(repo), category],
                                cwd=repo, capture_output=True, text=True, encoding='utf-8', timeout=60, **hidden_windows_subprocess_kwargs())
        if result.returncode:
            raise RuntimeError(result.stderr[-1500:])
        for item in json.loads(result.stdout):
            if item['contract'] in contracts:
                rows.append({'id': 'frontend-model.'+item['contract']+'.'+category,
                             'category': category, 'contracts': [item['contract']],
                             'status': item['status'], 'detail': item['detail'],
                             'boundary': 'Actual production image/PDF pure model with synthetic data, not rendering/provider execution'})
    return rows


def blocker(contract, category):
    if contract['id'] in IDS and category in {'concurrency', 'interrupted', 'permissions', 'offline', 'stale'}:
        return {'kind': 'not_applicable', 'reason': f"Audited {contract['id']} owns an in-memory supplied model/result, with no durable store, permission grant or transport. These model transforms do not mutate a shared revision or resume a worker; actual application rendering/loading/generation has separate contracts."}
    return None
