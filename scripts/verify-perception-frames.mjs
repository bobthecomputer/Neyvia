import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'); const root=mkdtempSync(path.join(tmpdir(),'neyvia-frame-'));
try { const r=spawnSync(resolveNeyviaPython(repo).python,['-c',`from grant_agent.ui_tools import UiToolSurface; import json
s=UiToolSurface(workspace_root=__import__('pathlib').Path('${root.replaceAll('\\','\\\\')}')); s.observer.capture_node_crop=lambda node,**k:{'ok':True,'method':'fixture','path':'crop.png','nodeId':node.id}; nodes=[{'id':'upload','role':'button','name':'Upload','states':['enabled'],'actions':['click'],'bounds':{'x':1,'y':2,'w':30,'h':20}}]; s.call('ui.observe',{'nodes':nodes,'url':'http://localhost:3000'}); f=s.call('ui.frame',{'nodeId':'upload','crop':True}); stale=s.call('ui.frame',{'nodeId':'upload','expectedRevision':99}); old=s.call('ui.frame',{'nodeId':'upload','expectedRevision':0}); print(json.dumps({'frame':f,'stale':stale,'old':old,'specs':[x['name'] for x in __import__('grant_agent.ui_tools',fromlist=['ui_tool_specs']).ui_tool_specs()]}))`,root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8'}); assert.equal(r.status,0,r.stderr); const o=JSON.parse(r.stdout); assert(o.specs.includes('ui.frame')&&o.specs.includes('ui.inspect_frame')); assert.equal(o.frame.schema,'neyvia.perception_frame.v1'); assert.equal(o.frame.selectedNode.id,'upload'); assert.equal(o.frame.crop.ok,true); assert.equal(o.stale.status,'stale_frame'); assert.equal(o.old.status,'stale_frame'); console.log('PERCEPTION_FRAMES_VERIFIED: resident graph identity, selected crop, and stale-frame rejection'); } finally {rmSync(root,{recursive:true,force:true});}
