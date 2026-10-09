"""Current provider-vector owner calls and actual React server markup.

Server markup proves vector output only; it is never rendered-browser proof.
"""
from __future__ import annotations
import hashlib
import json
import subprocess
from pathlib import Path
from .subprocess_utils import hidden_windows_subprocess_kwargs

IDS={"provider.registry","provider.resolution","provider.tree","provider.svg"}
TEXT={"empty":"","huge":"Unknown selected mark "*15000,"unicode":"雪🙂 café العربية <&\""}
REPO=Path(__file__).resolve().parents[2]
SCRIPT=r'''
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {build} from 'esbuild';
import {PROVIDER_MARKS,providerMarkIds,resolveProviderMarkId} from '__DATA__';
import {describeProviderMark,providerMarkSvgString} from '__MODEL__';
import {checkProviderRegistry} from '__CHECK__';
const {identity,category,text}=JSON.parse(readFileSync(process.argv[2],'utf8'));
const hash=s=>createHash('sha256').update(s).digest('hex');
const ids=providerMarkIds;checkProviderRegistry(PROVIDER_MARKS,ids);
let observations=0,markup='';
let actualVectorCases=0;
for(const id of ids)for(const mono of [false,true]){
 const tree=describeProviderMark(id,{mono,size:24,title:text});assert.equal(tree.attrs['data-mark'],id);
 const svg=providerMarkSvgString(id,{mono,size:24,title:text});assert.ok(svg.startsWith('<svg')&&!/<image|<img|data:|base64/i.test(svg));actualVectorCases++;
}
if(identity==='provider.registry'){
 const candidate=structuredClone(PROVIDER_MARKS);candidate.claude.label=text;
 if(!text)assert.throws(()=>checkProviderRegistry(candidate,ids));else assert.equal(checkProviderRegistry(candidate,ids),candidate);
 const bad=structuredClone(PROVIDER_MARKS);bad.gemini.paths[0].d='raster.png';assert.throws(()=>checkProviderRegistry(bad,ids));observations=ids.length;
}else if(identity==='provider.resolution'){
 assert.equal(resolveProviderMarkId(text),null);
 for(const [alias,expected] of [[' GH ','github'],['xai','grok'],['gdrive','google-drive'],['shell','terminal']])assert.equal(resolveProviderMarkId(alias),expected);observations=5;
}else{
 const title=text,options={title,size:24};
 const tree=describeProviderMark('gemini',options);assert.equal(tree.attrs.width,24);assert.equal(tree.attrs['aria-label'],text||undefined);
 const mono=describeProviderMark('gemini',{...options,mono:true});assert.ok(!/url\(#|#[0-9a-f]{6}/i.test(JSON.stringify(mono)));
 const unknown=describeProviderMark('unknown-owned',{title});assert.equal(unknown.children[0].tag,'rect');
 markup=providerMarkSvgString('gemini',options);assert.ok(markup.startsWith('<svg')&&!/<image|<img|data:|base64/i.test(markup));
 const outputs=await Promise.all(Array.from({length:category==='concurrency'?32:2},async()=>providerMarkSvgString('gemini',options)));
 const namespaces=outputs.map(value=>value.match(/(?:linear|radial)Gradient[^>]* id="([^"]+)"/)[1]);assert.equal(new Set(namespaces).size,outputs.length);
 assert.ok(outputs.every(value=>value!==markup));observations=outputs.length+3;
 // Invoke the real framework component through a write:false esbuild bundle;
 // CSS is skipped only for server markup, never for a browser presentation claim.
 const source=`import React from 'react';import {renderToStaticMarkup} from 'react-dom/server';import {ProviderMark} from './web/src/neyvia/next/ProviderMark.jsx';console.log(renderToStaticMarkup(React.createElement('div',null,React.createElement(ProviderMark,{id:'gemini',title:'Owned vector',size:24}),React.createElement(ProviderMark,{id:'gemini',title:'Owned vector',size:24}))));`;
 const bundled=await build({stdin:{contents:source,resolveDir:'__REPO__',loader:'jsx'},jsx:'automatic',bundle:true,platform:'node',format:'cjs',write:false,loader:{'.css':'empty'},logLevel:'silent'});
 const bundlePath=fileURLToPath(new URL('./framework.cjs',import.meta.url));writeFileSync(bundlePath,bundled.outputFiles[0].text);const {spawnSync}=await import('node:child_process');const rendered=spawnSync(process.execPath,[bundlePath],{encoding:'utf8',windowsHide:true});assert.equal(rendered.status,0,rendered.stderr);
 const framework=rendered.stdout;assert.equal((framework.match(/<svg/g)||[]).length,2);const gradientIds=[...framework.matchAll(/(?:linear|radial)Gradient[^>]* id="([^"]+)"/g)].map(m=>m[1]);assert.equal(new Set(gradientIds).size,gradientIds.length);assert.ok(!/<image|<img|data:|base64/i.test(framework));
}
console.log(JSON.stringify({observations,actualVectorCases,registryEntries:ids.length,svgBytes:Buffer.byteLength(markup),svgSha256:hash(markup),actualReactServerMarkup:identity==='provider.tree'||identity==='provider.svg',renderedBrowserProof:false}));
'''


def run(root,contracts,categories):
    rows=[];base=Path(root).resolve()
    for identity in sorted(IDS&set(contracts)):
        for category in categories:
            if category not in TEXT and not(identity=="provider.svg" and category in {"concurrency","stale"}):continue
            scratch=base/".agent_control/proofs"/("c7d-provider-mark-"+identity+"-"+category);scratch.mkdir(parents=True,exist_ok=False)
            payload=scratch/"input.json";payload.write_text(json.dumps({"identity":identity,"category":category,"text":TEXT.get(category,"Owned mark")}),encoding="utf8")
            script=scratch/"observe.mjs";source=SCRIPT.replace("__REPO__",REPO.as_posix())
            for tag,path in (("__DATA__","providerMarksData.js"),("__MODEL__","providerMarkModel.js"),("__CHECK__","nxProviderMarkContracts.js")):source=source.replace(tag,(REPO/"web/src/neyvia/next"/path).as_uri())
            script.write_text(source,encoding="utf8");row={"id":"c7d-provider-marks."+identity+"."+category,"contracts":[identity],"category":category,"boundary":"Current registry/resolution/tree/SVG owner and actual React server markup; no rendered browser or provider installation proof"}
            completed=subprocess.run(["node",str(script),str(payload)],capture_output=True,text=True,encoding="utf8",timeout=60,**hidden_windows_subprocess_kwargs())
            if completed.returncode:row.update(status="failed",detail={"error":completed.stderr[-4000:],"returnCode":completed.returncode})
            else:row.update(status="passed",detail=json.loads(completed.stdout))
            rows.append(row)
    return rows


def blocker(contract,category):
    identity=contract.get("id")
    if identity not in IDS or category in TEXT or(identity=="provider.svg" and category in {"concurrency","stale"}):return None
    owners={"provider.registry":"checkProviderRegistry validates supplied vector registry identity, path/colour/gradient declarations; actual source registry is fixed and contains no raster imports","provider.resolution":"resolveProviderMarkId normalizes a supplied literal ID against loaded registry/alias objects","provider.tree":"describeProviderMark describes a supplied vector entry/options as an in-memory SVG tree","provider.svg":"providerMarkSvgString serializes the supplied vector/options and allocates a new in-process gradient namespace; concurrent/new namespace allocation is independently exercised"}
    return {"kind":"not_applicable","reason":f"Inspected exact {identity}: {owners[identity]}. It has no saved worker or file revision, permission grant, network, provider request or browser capture at this owning site; {category} therefore has no mechanism to interrupt/deny/disconnect/reload for this invariant. Actual React/server output remains separate from rendered-browser proof."}
