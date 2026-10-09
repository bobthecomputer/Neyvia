#!/usr/bin/env node
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import process from "node:process";
const root = new URL("..", import.meta.url).pathname.replace(/^\/(\w):/, "$1:");
const code = String.raw`
import json,tempfile
from pathlib import Path
from grant_agent.behavioral_experiments import BehavioralExperimentLedger
with tempfile.TemporaryDirectory() as d:
 p=Path(d)/'ledger.json'; l=BehavioralExperimentLedger(p)
 l.create('e1',baseline_input={'prompt':'same'},variant_input={'prompt':'same'},acceptance={'kind':'response_contains','text':'ok'},requested_route={'runtime':'local','model':'candidate'},budget={'maxCalls':2},seed=4)
 l.record('e1',variant='baseline',response='no',actual_route={'runtime':'local','model':'candidate'})
 l.record('e1',variant='variant',response='ok',actual_route={'runtime':'local','model':'candidate'})
 result=l.compare('e1'); frozen=False
 try: l.create('e1',baseline_input={},variant_input={},acceptance={'kind':'variant_differs'},requested_route={},budget={'maxCalls':2})
 except FileExistsError: frozen=True
 negative=BehavioralExperimentLedger(p).compare('e1')
 mismatch=BehavioralExperimentLedger(p); mismatch.create('e2',baseline_input=1,variant_input=1,acceptance={'kind':'variant_differs'},requested_route={'runtime':'local','model':'candidate'},budget={'maxCalls':2}); mismatch.record('e2',variant='baseline',response='a',actual_route={'runtime':'other','model':'candidate'}); mismatch.record('e2',variant='variant',response='b',actual_route={'runtime':'other','model':'candidate'}); invalid=mismatch.compare('e2')
 print(json.dumps({'result':result,'frozen':frozen,'negative':negative,'invalid':invalid}))
`;
const run=spawnSync(process.env.PYTHON||"python",["-c",code],{cwd:root,encoding:"utf8",env:{...process.env,PYTHONPATH:`${root}/src${process.env.PYTHONPATH?`;${process.env.PYTHONPATH}`:""}`}});
if(run.status!==0){process.stderr.write(run.stderr);process.exit(run.status||1)}
const payload=JSON.parse(run.stdout); assert.equal(payload.result.criterionPassed,true); assert.equal(payload.result.evidenceVerified,false); assert.equal(payload.frozen,true); assert.equal(payload.negative.status,"compared"); assert.equal(payload.negative.evidenceVerified,false); assert.equal(payload.invalid.status,"invalid_comparison"); console.log(JSON.stringify({passed:true,checks:["frozen-definition","hashed-observations","observable-comparison","limitations","route-mismatch"]}));
