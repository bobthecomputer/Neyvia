"""Real A4 CLI journey, receipt-processing benchmark and fail-closed readbacks.

Uses task-local disposable copies for adverse cases; never launches a model,
service or test framework. Leaves all receipts for inspection.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

from efficiency_log import ROOT, LEDGER, SCHEMA, atomic_write, digest, read_json, read_ledger


def main():
    run_id=uuid.uuid4().hex
    folder=ROOT/'scripts/evidence/A4-runs'/run_id
    folder.mkdir(parents=True)
    observations=[]
    cases=[]
    ledger=read_ledger(LEDGER)
    for study in ('manual-recovery','t14-cascade','t17-autopilot'):
        source=next(r for r in ledger if r['id']==study)['receipts'][0]
        path=ROOT/source['path']
        for repetition in range(1,4):
            start=time.perf_counter_ns()
            blob=path.read_bytes()
            parsed=json.loads(blob.decode('utf-8-sig'))
            matched=hashlib.sha256(blob).hexdigest()==source['sha256']
            elapsed=(time.perf_counter_ns()-start)/1e6
            assert matched and isinstance(parsed,dict)
            cases.append({'task':study,'repetition':repetition,'read_hash_parse_ms':elapsed,'hash_matches':matched,'parsed':True,'bytes':len(blob),'source':source})
    raw=folder/'receipt-processing.json'
    atomic_write(raw,json.dumps({'method':'Read exact historical receipt bytes, calculate SHA-256, decode UTF-8 and parse JSON; perf_counter_ns encloses these operations only. Three files, three repetitions in fixed order; local filesystem cache may be warm.', 'samples':cases},indent=2)+'\n')
    def select(field):return {'receipt':'raw','pointer':'/samples','field':'/'+field}
    no_ci={'method':'not-estimable','reason':'Three local files in one process; no repeated deployment quantile CI.'}
    spec={'schema':SCHEMA,'id':'a4-receipt-processing-'+run_id,'study':'A4 real receipt-processing benchmark',
          'evidence_status':'raw-verified','method':'Actual local file read, SHA-256 and JSON parsing; perf_counter_ns; filesystem cache may be warm. No model calls. This measures ledger input processing, not model inference.',
          'models':['none; Python 3.13 standard-library receipt processing'],
          'tasks':{'description':'manual recovery, T14 cascade and T17 Autopilot raw receipts','repetitions':3,'independent_unit':'receipt file; repeats stay in the file cluster'},
          'receipts':[{'id':'raw','path':raw.relative_to(ROOT).as_posix(),'sha256':digest(raw),'kind':'raw'}],
          'limitations':['Three local files on this machine and fixed order; not a model-efficiency gain or deployment throughput benchmark.'],
          'metrics':[
              {'name':'hash_matches','unit':'count','calculation':{'op':'sum','args':[select('hash_matches')]},'ci_request':no_ci},
              {'name':'parse_successes','unit':'count','calculation':{'op':'sum','args':[select('parsed')]},'ci_request':no_ci},
              {'name':'processing_mean','unit':'ms','calculation':{'op':'mean','args':[select('read_hash_parse_ms')]},'ci_request':{'method':'cluster-bootstrap-mean','values':select('read_hash_parse_ms'),'clusters':select('task'),'seed':417,'resamples':2000,'level':.95}},
              {'name':'processing_p95','unit':'ms','calculation':{'op':'quantile','args':[select('read_hash_parse_ms'),.95]},'ci_request':no_ci}]}
    spec_path=folder/'result-spec.json';atomic_write(spec_path,json.dumps(spec,indent=2)+'\n')
    cli=ROOT/'scripts/efficiency_log.py'
    def call(label,*args,success=True):
        start=time.perf_counter_ns()
        proc=subprocess.run([sys.executable,str(cli),*map(str,args)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=180)
        entry={'label':label,'argv':[sys.executable,str(cli),*map(str,args)],'exit_code':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr,'elapsed_ms':(time.perf_counter_ns()-start)/1e6}
        observations.append(entry)
        assert (proc.returncode==0)==success, entry
        return entry
    call('append real benchmark to canonical ledger','append','--result',spec_path)
    call('fresh process revalidates canonical ledger and Markdown','verify')
    scratch=ROOT/'.agent_control/a4'/run_id
    scratch.mkdir(parents=True)
    scratch_ledger=scratch/'results.jsonl';report=scratch/'log.md'
    flags=['--ledger',scratch_ledger,'--report',report]
    call('append first benchmark to disposable ledger','append','--result',spec_path,*flags)
    call('fresh process observes persisted row','verify',*flags)
    original=digest(scratch_ledger)
    def rejected(label,path):
        call(label,'append','--result',path,*flags,success=False)
        assert digest(scratch_ledger)==original,'Rejection changed ledger'
    rejected('duplicate ID rejected without changing ledger',spec_path)
    bad=copy.deepcopy(spec);bad['id']+='-missing';bad['receipts'][0]['path']='scripts/evidence/A4-runs/nonexistent.json'
    p=scratch/'missing.json';atomic_write(p,json.dumps(bad));rejected('missing raw receipt rejected',p)
    bad=copy.deepcopy(spec);bad['id']+='-schema';bad['schema']='unknown'
    p=scratch/'schema.json';atomic_write(p,json.dumps(bad));rejected('unknown schema rejected',p)
    bad=copy.deepcopy(spec);bad['id']+='-literal';bad['metrics'][0]['calculation']=9000
    p=scratch/'literal.json';atomic_write(p,json.dumps(bad));rejected('unsupported measured constant rejected',p)
    bad=copy.deepcopy(spec);bad['id']+='-empty';bad['metrics'][0]['calculation']['args'][0]['where']={'/task':'unobserved-task'}
    p=scratch/'empty.json';atomic_write(p,json.dumps(bad));rejected('empty selection cannot manufacture zero',p)
    # Only disposable copies are altered; original historical evidence is untouched.
    altered=scratch/'altered-receipt.json';atomic_write(altered,json.dumps({'samples':[]}))
    bad=copy.deepcopy(spec);bad['id']+='-hash';bad['receipts'][0]['path']=str(altered)
    p=scratch/'hash.json';atomic_write(p,json.dumps(bad));rejected('changed raw bytes rejected by hash',p)
    rows=read_ledger(scratch_ledger);rows[0]['metrics'][0]['value']+=1
    corrupt=scratch/'corrupt.jsonl';atomic_write(corrupt,json.dumps(rows[0])+'\n')
    call('edited stored metric rejected by recalculation','verify','--ledger',corrupt,'--report',report,success=False)
    atomic_write(report,'stale projection\n')
    call('stale Markdown detected','verify',*flags,success=False)
    call('render recovers Markdown','render',*flags)
    call('recovered projection verified in fresh process','verify',*flags)
    lock=Path(str(scratch_ledger)+'.lock');atomic_write(lock,'owned proof lock\n')
    rejected('concurrent writer lock fails closed',spec_path)
    lock.unlink()
    p=scratch/'malformed.json';atomic_write(p,'{"schema":')
    rejected('malformed benchmark JSON rejected',p)
    final=read_ledger(LEDGER)
    evidence={'schema':'neyvia.A4.end-to-end.v1','at':datetime.now(timezone.utc).isoformat(),'run_id':run_id,'passed':True,
              'defining_mechanism':'Raw receipts -> verified/recomputed result row -> atomic append -> generated report -> fresh-process hash/statistical validation; adverse writes refused without ledger mutation.',
              'real_benchmark_spec':spec_path.relative_to(ROOT).as_posix(),'benchmark_samples':len(cases),'observations':observations,
              'historical_results':sum(not r['id'].startswith('a4-receipt-processing-') for r in final),
              'real_ledger_benchmark_runs':sum(r['id'].startswith('a4-receipt-processing-') for r in final),
              'canonical_results':len(final),'metrics':sum(len(r['metrics']) for r in final),
              'status_counts':{s:sum(r['evidence_status']==s for r in final) for s in ('raw-verified','aggregate-only','unverified')},
              'artifacts':[{'path':p.relative_to(ROOT).as_posix(),'sha256':digest(p)} for p in (LEDGER,ROOT/'docs/research/efficiency-log.md',ROOT/'docs/research/schema.md',ROOT/'docs/research/coverage.json',cli,ROOT/'scripts/import_efficiency_history.py',Path(__file__))],
              'limits':['Historical values are receipt replays, not new model evaluations. Aggregate-only and missing-raw measurements remain explicitly qualified. No UI feature, deployed service, official rank or general efficiency claim.', 'No NAS, credential reads, protected worktrees, services, installs, downloads, pushes or merges; no network ports used.']}
    atomic_write(ROOT/'scripts/evidence/A4.json',json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:evidence[k] for k in ('passed','run_id','canonical_results','metrics','status_counts')}))


if __name__=='__main__':main()
