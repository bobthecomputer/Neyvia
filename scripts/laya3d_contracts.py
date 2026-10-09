"""Blender upgrade journey on native labelled fixtures, then evaluate laya-3d.cl checks.

Private Blender (--background) hosts the bridge; the shared scene_core transcribes,
judges and improves. Labels come from fixture construction, never from the judge.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

from laya3d_harness import Harness,REPO

ALLOWED=['mesh.merge','mesh.fill_holes','mesh.normals','mesh.unwrap','mesh.pack_uv','mesh.smooth','mesh.scale','mesh.remove_floaters']
TARGETS={'closedSurface':True,'uv':True,'smooth':True,'unitScale':True,'singleComponent':True,'floaterMaxVertices':8}


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,default=str),encoding='utf-8')


def score(results,predicates):
    counts={}
    for result in results:
        labelled=set(result['case']['labels']); predicted=set(result['predicted'])
        for name in labelled|predicted|predicates:
            counter=counts.setdefault(name,{'tp':0,'fp':0,'fn':0,'tn':0})
            counter['tp' if name in predicted and name in labelled else 'fp' if name in predicted else 'fn' if name in labelled else 'tn']+=1
    for count in counts.values():
        count['precision']=count['tp']/(count['tp']+count['fp']) if count['tp']+count['fp'] else None
        count['recall']=count['tp']/(count['tp']+count['fn']) if count['tp']+count['fn'] else None
    tp=sum(v['tp'] for v in counts.values())
    return counts,tp/max(tp+sum(v['fp'] for v in counts.values()),1),tp/max(tp+sum(v['fn'] for v in counts.values()),1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=None,help='default D:/NeyviaRuns/laya3d/upgrade-contract (or <scratch>/laya3d/upgrade-contract)')
    parser.add_argument('--limit',type=int,default=24)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--port',type=int,default=None,help='default 49105, or the first pair of --port-block')
    from grant_agent.assigned_ports import add_arguments,apply,choose_port,under
    add_arguments(parser)
    args=parser.parse_args(); apply(args,'CORE')
    args.root=args.root or under('laya3d/upgrade-contract',Path('D:/NeyviaRuns/laya3d/upgrade-contract'))
    harness=Harness(args.root,port=choose_port(args.port,49105))
    results=json.loads((args.root/'cases.json').read_text(encoding='utf-8')) if args.resume and (args.root/'cases.json').exists() else []
    try:
        save(args.root/'loaded-manual.json',harness.tool('neyvia.manual.load',{'id':'game-dev','chapter':'bridges'}))
        project=args.root/'blender'; project.mkdir(parents=True,exist_ok=True)
        fixture_args=[] if (project/'labels.json').exists() else ['--fixtures']
        started=time.perf_counter()
        session=harness.launch('blender',project,['--background','--factory-startup','--python',str(REPO/'scripts/gamedev/blender/laya3d_background.py'),'--',str(project),*fixture_args])
        startup=time.perf_counter()-started
        from grant_agent import scene_core
        from grant_agent.cl_skill import _parse_skill,_Expr
        predicates={r['id'] for r in scene_core.vocabulary('blender')}
        rows=json.loads((project/'labels.json').read_text())[:args.limit]
        for row in rows:
            if any(r['case']['id']==row['id'] for r in results): continue
            start=time.perf_counter()
            harness.action(session,'restore',{'path':row['path'],'sha256':hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()})
            source={'root':str(harness.state),'domain':'blender','sessionId':session,'renders':True,'targets':TARGETS}
            before=scene_core.transcribe('blender',source)
            verdict=scene_core.judge(before,root=harness.state)
            # Caller-supplied metric guard: the core keeps no fix that shrinks any canonical mask IoU.
            outcome=scene_core.improve('blender',source,{'max_steps':8,'max_seconds':180,'allowed_fixes':ALLOWED,
                                       'guards':{'silhouette_quality':'min'}},root=harness.state)
            after=scene_core.transcribe('blender',source)
            remaining=scene_core.judge(after,root=harness.state,record=False)
            result={'case':row,'predicted':sorted({f['predicate'] for f in verdict['findings']}),
                    'remaining':sorted({f['predicate'] for f in remaining['findings']}),
                    'before':before,'after':after,'verdict':verdict,'upgrade':outcome,
                    'renders':source.get('_renders',[]),'seconds':time.perf_counter()-start}
            results.append(result); save(args.root/'cases.json',results)
            print(row['id'],result['predicted'],[s['status'] for s in outcome['steps']],result['remaining'],round(result['seconds'],2),flush=True)
        counts,precision,recall=score(results,predicates)
        steps=[(r['case']['id'],s) for r in results for s in r['upgrade']['steps']]
        # Exact rollback: a reverted fix whose re-observed Scene (mesh facts + canonical
        # mask digests + IoU) is byte-identical to the pre-fix Scene.
        rollbacks=[r['case']['id'] for r in results
                   if any(s['status']=='reverted' for s in r['upgrade']['steps'])
                   and r['upgrade']['steps'][-1]['status']=='reverted'
                   and r['upgrade']['steps'][-1]['before']==r['after']['sha256']]
        from grant_agent.laya_instant import store
        episodes=store(str(harness.state)); episodes.refresh()
        summary={'cases':len(results),'perDefect':counts,'precision':precision,'recall':recall,
                 'improved':sum(s['status']=='kept' for _,s in steps),
                 'kept':[f'{c}:{s["finding"]["fix"]["action"]}' for c,s in steps if s['status']=='kept'],
                 'reverted':[f'{c}:{s["finding"]["fix"]["action"]}' for c,s in steps if s['status']=='reverted'],
                 'rollback':bool(rollbacks),'rollbackCases':rollbacks,
                 'silhouettePreserved':all(r['after']['metrics']['silhouette_quality']>=r['before']['metrics']['silhouette_quality'] for r in results),
                 'cleanAfter':sum(not r['remaining'] for r in results),
                 'episodes':len(episodes.rows),'training':False,'startupSeconds':startup,
                 'secondsPerModel':{r['case']['id']:r['seconds'] for r in results},
                 'labelSource':'native fixture construction (laya3d_background.py --fixtures), not judge output'}
        # CL owns acceptance, not Python assertions mirrored from implementation.
        skill=_parse_skill(REPO/'manuals/cl/laya-3d.cl')
        summary['checks']=[{'name':c.name,'expr':c.expr,'passed':bool(_Expr(c.expr,{'proof':summary},{}).run())} for c in skill.checks]
        save(args.root/'summary.json',summary)
        print(json.dumps({k:v for k,v in summary.items() if k not in {'perDefect','secondsPerModel'}}),flush=True)
    finally: harness.close()


if __name__=='__main__': main()
