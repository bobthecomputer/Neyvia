"""Evolver completion requires actual paired compiler work, not queued jobs."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import time

from .record_effects import _path, _json

SUPPORTED = {'neyvia.evolver.run'}


def snapshot_for(protocol,name,args):
    from ..evolver_manual_local import DOMAIN
    if args['domain']!=DOMAIN:
        raise ValueError('Fresh local witness covers manual_json_local_v1 only; provider domains need their own actual evaluation')
    from ..neyvia_evolver import _jobs
    from ..evolver_core import EvolverEngine
    path=_path(protocol,'.neyvia/evolver.sqlite3')
    domains=EvolverEngine(path).status(DOMAIN)['domains'] if path.exists() else []
    with _jobs(protocol.gateway.root) as (db,_):
        prior=db.execute('SELECT * FROM jobs WHERE id=?',(args['requestId'],)).fetchone()
    return {'domain':domains[0] if domains else None,'job':dict(prior) if prior else None}


def _verify(protocol,args,value,before):
    from ..evolver_manual_local import DOMAIN,PRETTY,COMPACT
    from ..evolver_core import EvolverEngine,_hash
    from ..neyvia_evolver import job
    from .manuals import cl_to_manual
    from .tokens import count_tokens
    if args['domain']!=DOMAIN or before['job'] is not None: return False
    identity=args['requestId']
    until=time.monotonic()+300
    saved=job(protocol.gateway.root,identity)['job']
    while saved['state'] in {'queued','running'} and time.monotonic()<until:
        time.sleep(.2); saved=job(protocol.gateway.root,identity)['job']
    if saved['state']!='completed' or saved['pid']<=0 or saved['payload']!={'domain':DOMAIN,'maxTrials':args.get('maxTrials',1)}: return False
    if value.get('job',{}).get('id')!=identity: return False
    engine=EvolverEngine(_path(protocol,'.neyvia/evolver.sqlite3'))
    spec=engine._verify_frozen(DOMAIN)
    current=engine.status(DOMAIN)['domains'][0]
    prior=before['domain']
    if current['trials']!=(prior['trials'] if prior else 0)+1 or current['active_trial'] is not None: return False
    trials=saved['result']['domains'][DOMAIN]['trials']
    if len(trials)!=1: return False
    trial=trials[0]
    if trial!=current['receipts'][-1] or trial['state']!='accepted' or trial['promoted'] is not True: return False
    if current['incumbent']!=trial['candidate'] or len(trial['stages'])!=3 or not current['pareto_front']: return False
    if engine._genome(DOMAIN,trial['incumbent'])['text']!=PRETTY or engine._genome(DOMAIN,trial['candidate'])['text']!=COMPACT: return False
    panels={p['id']:p for p in spec['panels']}
    heldout=[]
    for index,stage in enumerate(trial['stages']):
        panel=panels[stage['panel']]
        if stage['panel_hash']!=_hash(panel) or stage['sample_count']!=12 or len(stage['pairs'])!=12: return False
        if panel['role']!=('discovery' if index==0 else 'held_out'): return False
        if index: heldout.append(panel['id'])
        if not stage['eligible'] or not stage['hard_gates_passed']: return False
        for item,pair in zip(panel['items'],stage['pairs']):
            seed=int(hashlib.sha256(f"{spec['promotion']['seed']}:{panel['id']}:{item['id']}".encode()).hexdigest()[:8],16)
            order=[trial['incumbent'],trial['candidate']] if seed%2 else [trial['candidate'],trial['incumbent']]
            if pair['item']!=item['id'] or pair['seed']!=seed or pair['order']!=order: return False
            path=Path(item['path']).resolve()
            if not path.is_relative_to(Path(__file__).resolve().parents[3]/'manuals') or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']: return False
            original=json.loads(path.read_text(encoding='utf-8'))
            baseline=count_tokens(json.dumps(original,ensure_ascii=False,indent=2))
            for side,recipe in (('incumbent',PRETTY),('candidate',COMPACT)):
                observation=pair[side]; receipt=observation['receipt']
                artifact=_path(protocol,receipt['artifact']); compiled=_path(protocol,receipt['compiledPath'])
                raw=artifact.read_bytes(); cl=compiled.read_bytes()
                tokens=count_tokens(raw.decode('utf-8'))
                if (receipt['inputPath']!=str(path) or receipt['inputSha256']!=item['sha256'] or
                    receipt['artifactSha256']!=hashlib.sha256(raw).hexdigest() or receipt['compiledSha256']!=hashlib.sha256(cl).hexdigest() or
                    json.loads(raw)!=original or cl_to_manual(cl.decode('utf-8'))!=original or receipt['recipe']!=recipe or receipt['seed']!=seed or
                    receipt['tokens']!=tokens or receipt['baselineTokens']!=baseline or
                    observation['objectives']!={'roundtrip':1,'tokenRatio':tokens/baseline} or
                    observation['hard_gates']!={'compiledRoundtrip':True,'exactSemantics':True}): return False
            if pair['candidate']['receipt']['tokens']>=pair['incumbent']['receipt']['tokens']: return False
    return len(set(heldout))==2 and set(current['held_out_used'])==set(heldout)


def checks_for(protocol,name,args):
    if name not in SUPPORTED: return []
    def verify(arguments,value,before):
        try: return _verify(protocol,arguments,value,before)
        except (OSError,ValueError,KeyError,TypeError,IndexError): return False
    return [{'name':'effect-evolver-real-local-paired-manual','observer':True,'effect':True,
        'subjectKey':name+':'+args['requestId'],'observerTool':'fresh-frozen-paired-compiler-artifacts',
        'subject':{'domain':args['domain'],'requestId':args['requestId']},
        'expectation':'Accepted counted trial from 36 real paired manual parse/compile/token measurements with two distinct heldout panels and an actual local Pareto update',
        'check':verify}]
