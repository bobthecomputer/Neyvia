#!/usr/bin/env node
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import process from "node:process";
const root=new URL("..",import.meta.url).pathname.replace(/^\/(\w):/,"$1:");
const code=String.raw`
import json,tempfile
from pathlib import Path
from grant_agent.contextual_learning import ContextualLearningStore
with tempfile.TemporaryDirectory() as d:
 r=Path(d); (r/'before.txt').write_text('before'); (r/'after.txt').write_text('after')
 s=ContextualLearningStore(r/'state.json',scope_root=r); row=s.record_correction('research',before_path='before.txt',after_path='after.txt',correction='tighten source caveat',agent_id='agent')
 provisional=s.history('research'); denied=False
 try:s.record_preference(row['correctionId'],preference=True,source='model')
 except ValueError:denied=True
 accepted=s.record_preference(row['correctionId'],preference=True,source='operator'); history=s.history('research')
 outside=False
 try:s.record_correction('game',before_path='../x',after_path='after.txt',correction='x')
 except ValueError:outside=True
 s.create_attention_experiment('a',baseline_input={'x':1},variant_input={'x':1},acceptance={'kind':'variant_differs'},requested_route={'runtime':'r','model':'m'},budget={'maxCalls':2}); s.record_attention_observation('a',variant='baseline',response='a',actual_route={'runtime':'r','model':'m'}); s.record_attention_observation('a',variant='variant',response='b',actual_route={'runtime':'r','model':'m'}); att=s.compare_attention('a')
 print(json.dumps({'row':row,'provisional':provisional,'denied':denied,'accepted':accepted,'history':history,'outside':outside,'attention':att}))
`;
const r=spawnSync(process.env.PYTHON||"python",["-c",code],{cwd:root,encoding:"utf8",env:{...process.env,PYTHONPATH:`${root}/src${process.env.PYTHONPATH?`;${process.env.PYTHONPATH}`:""}`}}); if(r.status!==0){process.stderr.write(r.stderr);process.exit(r.status||1)} const p=JSON.parse(r.stdout); assert.equal(p.row.status,"provisional"); assert.equal(p.denied,true); assert.equal(p.accepted.trustedOperator,true); assert.equal(p.history.independentSupport,false); assert.equal(p.outside,true); assert.equal(p.attention.representationClaim.includes("private internal"),true); console.log(JSON.stringify({passed:true,checks:["scoped-hashes","provisional-correction","operator-only-preference","uncertainty","attention-observable"]}));
