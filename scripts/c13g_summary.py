"""Seal observed round-9 metrics; never turn a failure into a completed task."""
import json
from pathlib import Path
from c13_run import measured_usage, WT, OUT
from grant_agent.taste_gate import digest, save

def summary(round_name='r10'):
    if round_name not in {'r9','r10'}:raise ValueError('Only owned C13 comparison rounds are supported')
    rows=[]
    for arm,model in [('arm-luna','gpt-6-luna'),('arm-sol','gpt-6.1-sol')]:
        for task in OUT:
            folder=WT/'proof'/round_name/arm/task
            calls=measured_usage(folder) if folder.exists() else []
            state=folder/'result.json'
            if not state.exists():state=folder/'failure.json'
            result=json.loads(state.read_text(encoding='utf-8')) if state.exists() else {}
            rounds_path=folder/'evidence/rounds.json'
            rounds=next(iter(json.loads(rounds_path.read_text(encoding='utf-8')).values()),[]) if rounds_path.exists() else []
            latest=rounds[-1] if rounds else {}
            shots=latest.get('interaction',{}).get('screenshots',[])
            tokens={k:sum(c.get('usage',{}).get(k,0) for c in calls) for k in
                    ('input_tokens','cached_input_tokens','output_tokens','total_tokens')}
            usage_paths=list(folder.rglob('usage.json')) if folder.exists() else []
            spans=[(p.stat().st_mtime-json.loads(p.read_text(encoding='utf-8')).get('elapsedSec',0),p.stat().st_mtime) for p in usage_paths]
            wall=max(b for a,b in spans)-min(a for a,b in spans) if spans else None
            baseline=json.loads((WT/'proof/r7/arm-l'/task/'result.json').read_text(encoding='utf-8'))
            floor=baseline['qualityByRound'][-1]
            quality=latest.get('critique',{}).get('quality')
            cost=sum(c.get('costUsd') or 0 for c in calls)
            cap=.45 if task=='T1' else 1.10
            complete=bool(calls) and all(c.get('usageComplete') for c in calls)
            motion_ids={'motion-sequence','theme-toggle','reduced-motion','diagram-geometry'}
            motion_pass=motion_ids <= {c['check'] for c in latest.get('pageChecks',{}).get('checks',[]) if c.get('passed')}
            current_done=bool(result.get('doneOk') and motion_pass)
            row={'arm':arm,'model':model,'task':task,'tokens':tokens,'listPriceCostUsd':cost,
                 'usageComplete':complete,'modelTimeSec':sum(c.get('elapsedSec',0) for c in calls),
                 'taskTimeSec':wall,'rounds':len(rounds),
                 'rubricJudgeScore':quality,'rubric':latest.get('critique',{}).get('rubric',[]),
                 'qualityByRound':[r['critique']['quality'] for r in rounds],
                 'round4BaselineScore':floor,'costTargetUsd':cap,'doneOk':current_done,'historicalDoneOk':result.get('doneOk',False),'motionGatePassed':motion_pass,
                 'targetMet':bool(current_done and complete and quality is not None and quality>=floor and cost<=cap),
                 'error':result.get('error'),'callReservations':[
                    {'reserved':c.get('reservation'),'measuredTokens':c.get('usage',{}).get('total_tokens'),
                     'costUsd':c.get('costUsd'),'closedReason':c.get('budget',{}).get('closedReason')} for c in calls],
                 'allReservationsCovered':all(
                     not c.get('reservation') or
                     (c.get('usage',{}).get('total_tokens',0)<=c['reservation']['reservedTokens'] and
                      (c.get('costUsd') or 0)<=c['reservation']['reservedUsd'])
                     for c in calls),
                 'pageChecks':latest.get('pageChecks'),
                 'layaReceipts':str((folder/'work/.neyvia/laya/decisions.jsonl').relative_to(WT)),
                 'driverPass':latest.get('interaction',{}).get('passed'),
                 'fidelity':latest.get('fidelity'),'screenshots':[
                     {**s,'path':str(Path(s['path']).relative_to(WT)),'verifiedSha256':digest(s['path'])} for s in shots],
                 'artifact':str((folder/'work'/OUT[task]).relative_to(WT)),
                 'outputSha256':digest(folder/'work'/OUT[task]) if (folder/'work'/OUT[task]).exists() else None}
            rows.append(row)
    packet={'schema':'neyvia.C13g-comparison.v3','protocol':'plain voice and observed motion/theming/diagram checks','round':round_name,'execution':'sequential arms, Luna then Sol, same production CL taste driver and Obscura',
            'costBasis':'repository list-price equivalent of provider counters; cached is a subset of input',
            'round4Basis':'final round-4 session r7 rubric score; rare UI r7 was itself incomplete',
            'results':rows,'allTargetsMet':all(r['targetMet'] for r in rows),
            'totalTokens':sum(r['tokens']['total_tokens'] for r in rows),
            'cachedInputTokens':sum(r['tokens']['cached_input_tokens'] for r in rows),
            'listPriceCostUsd':sum(r['listPriceCostUsd'] for r in rows)}
    save(WT/'proof'/round_name/'summary.json',packet)
    print(json.dumps({k:packet[k] for k in ('allTargetsMet','totalTokens','cachedInputTokens','listPriceCostUsd')}))
if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--round',choices=['r9','r10'],default='r10')
    summary(parser.parse_args().round)
