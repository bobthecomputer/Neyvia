"""Rerun fresh Luna first drafts with/without a quarantined lesson through C9.

Incomplete historical environments are explicit blockers, never simulated wins.
This runner operates supported output-only tasks and rendered HTML. Desktop,
app-mutation and optimizer tasks lacking their original executor remain blocked.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from grant_agent.subprocess_utils import install_hidden_subprocess_default
from grant_agent.taste_gate import TasteGate, digest, save
from grant_agent.taste_judge import admit_lesson
from grant_agent.taste_model import invoke, object_schema

FILES_SCHEMA = object_schema({'files':{'type':'array','items':object_schema({'name':{'type':'string'},'content':{'type':'string'}})}})
SCORES_SCHEMA = object_schema({axis:{'type':'number','minimum':0,'maximum':4} for axis in ('fidelity','content','finish')})
JUDGE_SCHEMA = object_schema({side:object_schema({'scores':SCORES_SCHEMA,'evidence':{'type':'array','items':{'type':'string'}}}) for side in ('A','B')})


def kind(brief):
    if re.search(r'Character Map|charmap\.exe',brief,re.I):
        return 'blocked', 'Historical Character Map task requires original native desktop fixture; Paul desktop is forbidden'
    if re.search(r'Use the Notes app|course\.md|context_manager\.py|count_primes|extract_date|solve\(points\)|schedule\(exams',brief,re.I):
        return 'blocked', 'Historical tool/source task needs its original executor and immutable initial fixture; output prose cannot prove execution'
    return ('html','') if re.search(r'\.html|landing page|webpage|web page.*(?:UI|elements)|page.*(?:rare|UI elements)',brief,re.I) else ('text','')


def bindings(paths):
    return [{'path':str(path),'sha256':digest(path)} for path in paths]


def generate(brief,folder,manual,lesson,after,resume):
    prompt = ('Produce a FRESH FIRST DRAFT of the unchanged task below. Do not repair any previous answer; you will not see it. '
              'Return files with the requested filenames and complete content. For HTML use inline assets, system fonts, '
              'responsive desktop/phone and light/dark states, actual pointer/keyboard/touch controls. Rare interactions need '
              'primary research, uncommon defining mechanisms, author/venue/year credits in the element section. '
              'Do not claim native actions, benchmarks or file changes you have not actually performed.\nMANUAL:\n'+manual+
              ('\nEXPERIMENTAL QUARANTINED GUIDANCE:\n'+lesson if after else '')+'\nUNCHANGED TASK:\n'+brief)
    signature=hashlib.sha256(prompt.encode()).hexdigest()
    manifest=folder/'input.json'
    if resume and manifest.is_file():
        prior=json.loads(manifest.read_text(encoding='utf-8'))
        if prior.get('promptSha256')==signature and prior.get('outputs'):
            if any(digest(row['path'])!=row['sha256'] for row in prior['outputs']):
                raise ValueError('Resumed first-draft execution evidence changed')
            return json.loads((folder/'response.json').read_text(encoding='utf-8')),json.loads((folder/'usage.json').read_text(encoding='utf-8'))
    input_record={'promptSha256':signature,'model':'gpt-6-luna','firstDraft':True,'experimentalLesson':after}
    save(manifest,input_record)
    result=invoke(prompt,folder,FILES_SCHEMA,search=bool(re.search(r'rare|uncommon|https?://',brief,re.I)))
    save(manifest,{**input_record,'outputs':bindings([folder/'response.json',folder/'usage.json',folder/'events.jsonl'])})
    return result


def materialize(response,folder,task_kind):
    names=[]
    for row in response['files']:
        path=(folder/row['name']).resolve()
        if not path.is_relative_to(folder.resolve()) or path.suffix not in {'.html','.md','.txt','.json','.py','.toml'}:
            raise ValueError('Generation may write only scoped deliverable files')
        if path in names:
            raise ValueError('Duplicate generated deliverable')
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(row['content'],encoding='utf-8')
        names.append(path)
    if not names or task_kind=='html' and not any(path.suffix=='.html' for path in names):
        raise ValueError('Task deliverable missing')
    return names


def render(path,out,port):
    import subprocess
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
    result=subprocess.run(['node',str(ROOT/'scripts/c13_render.mjs'),'--html',str(path),'--out',str(out),'--port',str(port)],
                          capture_output=True,text=True,encoding='utf-8',timeout=1200,**hidden_windows_subprocess_kwargs())
    report_path=out/'report.json'
    if not report_path.is_file():
        raise RuntimeError('Neyvia Obscura render failed: '+result.stderr[-600:])
    report=json.loads(report_path.read_text(encoding='utf-8'))
    if 'obscura' not in report.get('engine','').lower() or report.get('html_sha256')!=digest(path):
        raise ValueError('C9 visual evidence requires hash-bound Neyvia Obscura render')
    return report


def evaluate_case(case_id,brief,out,args,manual,lesson,rubric):
    existing=out/'result.json'
    if args.resume and existing.is_file():
        cached=json.loads(existing.read_text(encoding='utf-8'))
        if cached.get('status')=='evaluated':
            for observation in cached['observations'].values():
                if digest(observation['path'])!=observation['sha256']:
                    raise ValueError('Resumed observation changed')
                bound=json.loads(Path(observation['path']).read_text(encoding='utf-8'))
                if (bound['taskSha256']!=args.task_hash or bound['suiteSha256']!=args.suite_hash or
                        bound['judgeSha256']!=args.judge_hash or bound['rubricSha256']!=digest(args.rubric) or
                        any(digest(row['path'])!=row['sha256'] for row in bound['execution']['files'])):
                    raise ValueError('Resumed case evidence changed')
            return cached
    task_kind,block=kind(brief)
    if block:
        result={'caseId':case_id,'status':'blocked','reason':block,'before':None,'after':None,'executionProven':False}
        save(out/'result.json',result)
        return result
    generated={}
    # Only two concurrent model calls. Rendering stays sequential on one assigned port.
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls={side:pool.submit(generate,brief,out/side/'generation',manual,lesson,side=='after',args.resume) for side in ('before','after')}
        for side,call in calls.items():
            response,usage=call.result()
            files=materialize(response,out/side/'deliverables',task_kind)
            generated[side]={'files':files,'usage':usage,'render':[],'images':[],'allImages':[],'imageManifest':[]}
            if task_kind=='html':
                for file in files:
                    if file.suffix!='.html': continue
                    report=render(file,out/side/'render'/file.stem,args.port)
                    generated[side]['render'].append(report)
                    selected,all_images,manifest=TasteGate(None,time.time())._critique_images(report,side,actions=True)
                    generated[side]['images'] += selected
                    generated[side]['allImages'] += all_images
                    generated[side]['imageManifest'] += manifest
    # Deterministic blind ordering from case id, not a model/arm label.
    order=['before','after'] if int(hashlib.sha256(case_id.encode()).hexdigest(),16)%2==0 else ['after','before']
    prompt=('You independently evaluate two first drafts, A and B, with the frozen rubric below. You do not know which uses '
            'experimental guidance. Score EACH axis 0..4 from actual evidence, never from claimed completion. '
            'Visual tasks require inspecting every attached screenshot: A images first, B images second. '
            'Functional claims are bounded by host driver reports. Cite image tile/region per visual criterion, lines for text. '
            'For nonvisual tasks do not invent screenshots or executed native/benchmark evidence.\nFROZEN RUBRIC:\n'+
            json.dumps(rubric)+'\nUNCHANGED TASK:\n'+brief)
    images=[]
    for label,side in zip(('A','B'),order):
        row=generated[side]; images+=row['images']
        prompt+='\n'+label+' HOST OBSERVATIONS:\n'+json.dumps(row['render'])
        prompt+='\n'+label+' ATTACHED IMAGE MANIFEST:\n'+json.dumps(row['imageManifest'])
        for file in row['files']:
            prompt+='\n'+label+' FILE '+file.name+':\n'+file.read_text(encoding='utf-8')
    verdict,judge_usage=invoke(prompt,out/'judge',JUDGE_SCHEMA,images=images)
    result={'caseId':case_id,'status':'evaluated','kind':task_kind,'blindingOrder':order,'verdict':verdict,'scores':{},
            'usage':[generated[side]['usage'] for side in ('before','after')]+[judge_usage],'firstDrafts':True,
            'rubricSha256':digest(args.rubric),'executionProven':True,'observations':{}}
    for label,side in zip(('A','B'),order):
        scores=verdict[label]['scores']
        if not verdict[label]['evidence'] or any(not isinstance(value,(int,float)) or isinstance(value,bool) or not 0<=value<=4 for value in scores.values()):
            raise ValueError('Frozen rubric requires finite scores with evidence')
        score=sum(scores.values())/len(scores)
        row=generated[side]
        # A failed real driver cannot earn a fully finished functional artifact.
        if row['render'] and not all(report['passed'] for report in row['render']):
            score=min(score,2.0)
        paths=row['files']+[out/side/'generation/events.jsonl',out/side/'generation/usage.json',out/side/'generation/input.json',
                           out/side/'generation/prompt.txt',out/'judge/events.jsonl',out/'judge/usage.json',out/'judge/response.json']
        for file in row['files']:
            report_path=out/side/'render'/file.stem/'report.json'
            if report_path.is_file(): paths.append(report_path)
        paths += [Path(image) for image in row['allImages']]
        observation={'score':score,'judgeSha256':args.judge_hash,'suiteSha256':args.suite_hash,'taskSha256':args.task_hash,
                     'rubricSha256':digest(args.rubric),'casePath':str(row['files'][0]),'caseSha256':digest(row['files'][0]),
                     'execution':{'model':'gpt-6-luna','exitCode':0,'timedOut':False,'files':bindings(paths)},'firstDraft':True}
        path=out/side/'observation.json'; save(path,observation)
        result['scores'][side]=score
        result['observations'][side]={'path':str(path),'sha256':digest(path),'score':score}
    result['improved']=result['scores']['after']>result['scores']['before']
    result['noRegression']=result['scores']['after']>=result['scores']['before']
    save(out/'result.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lesson',type=Path,required=True)
    parser.add_argument('--task',type=Path,required=True)
    parser.add_argument('--suite',type=Path,default=ROOT/'proof/preference-pairs.json')
    parser.add_argument('--judge',type=Path,default=ROOT/'config/c13-judge.json')
    parser.add_argument('--rubric',type=Path,default=ROOT/'config/c13-lesson-rubric.json')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--source-only',action='store_true',help='Real source rerun checkpoint; cannot admit a lesson without frozen suite')
    parser.add_argument('--cases',nargs='*',help='Optional explicit frozen pair IDs; other cases remain unexecuted and admission stays quarantined')
    parser.add_argument('--evidence-only',action='store_true',help='Run while promotion is quarantined: gathers evidence, can never admit')
    args=parser.parse_args()
    if args.port not in range(48801,48810): parser.error('Explicit assigned port 48801-48809 required')
    from grant_agent.taste_labels import load as load_labels, promotion_status
    judge_data=json.loads(args.judge.read_text(encoding='utf-8'))
    promotion=promotion_status(load_labels(args.suite),judge_data.get('calibration'))
    if promotion['quarantined'] and not args.evidence_only:
        parser.error('Taste-lesson promotion is quarantined ('+'; '.join(promotion['reasons'])+'); a replay spends model calls '
                     'and cannot admit. Collect genuine quality labels first, or pass --evidence-only')
    install_hidden_subprocess_default()
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE='0',FLUXIO_WATCHDOG_AUTOSTART='0',NEYVIA_COORDINATOR_AUTOSTART='0')
    args.out=args.out.resolve(); args.out.mkdir(parents=True,exist_ok=True)
    args.task=args.task.resolve(); args.judge=args.judge.resolve(); args.suite=args.suite.resolve(); args.rubric=args.rubric.resolve()
    record=json.loads(args.lesson.read_text(encoding='utf-8'))
    if record.get('state')!='quarantined': raise ValueError('Replay accepts quarantined guidance only')
    brief=args.task.read_text(encoding='utf-8')
    if brief!=record['evidence']['taskText']: raise ValueError('Replay task must be the lesson exact source brief')
    args.task_hash=digest(args.task); args.suite_hash=digest(args.suite)
    args.judge_hash=json.loads(args.judge.read_text(encoding='utf-8'))['modelSha256']
    from grant_agent.taste_judge import compare
    compare('','','',json.loads(args.judge.read_text(encoding='utf-8')))
    rubric=json.loads(args.rubric.read_text(encoding='utf-8')); manual=(ROOT/'manuals/cl/taste.cl').read_text(encoding='utf-8')
    frozen_manifest={'sourceTaskSha256':args.task_hash,'suiteSha256':args.suite_hash,'judgeSha256':args.judge_hash,
                     'rubricSha256':digest(args.rubric),'manualSha256':digest(ROOT/'manuals/cl/taste.cl'),'lessonSha256':digest(args.lesson)}
    prior=args.out/'frozen-inputs.json'
    if args.resume and prior.is_file() and json.loads(prior.read_text(encoding='utf-8'))!=frozen_manifest:
        raise ValueError('Frozen replay inputs changed; choose a new evidence directory')
    save(prior,frozen_manifest)
    lesson=record['manualPatchProposal']['append']
    print(json.dumps({'stage':'source-first-drafts','lesson':record['id']}),flush=True)
    source=evaluate_case('source',brief,args.out/'source',args,manual,lesson,rubric)
    suite=json.loads(args.suite.read_text(encoding='utf-8')); results=[]
    if args.cases and set(args.cases)-{row['pairId'] for row in suite['pairs']}:
        raise ValueError('Unknown frozen pair ID')
    if not args.source_only:
        for row in suite['pairs']:
            if args.cases is not None and row['pairId'] not in args.cases:
                task_kind,block=kind(row['taskText'])
                item={'caseId':row['pairId'],'status':'blocked' if block else 'not_run',
                      'reason':block or 'Outside explicitly selected subset; no score or success inferred',
                      'before':None,'after':None,'executionProven':False}
                save(args.out/'suite'/row['pairId']/'result.json',item)
                results.append(item)
                continue
            print(json.dumps({'stage':'frozen-case','caseId':row['pairId']}),flush=True)
            results.append(evaluate_case(row['pairId'],row['taskText'],args.out/'suite'/row['pairId'],args,manual,lesson,rubric))
    case_scores={side:{row['pairId']:next((item.get('scores',{}).get(side) for item in results if item['caseId']==row['pairId']),None)
                       for row in suite['pairs']} for side in ('before','after')}
    complete=all(value is not None for scores in case_scores.values() for value in scores.values())
    evidence={'judgePath':str(args.judge),'suitePath':str(args.suite),'judgeSha256':args.judge_hash,'suiteSha256':args.suite_hash,
              'rubricPath':str(args.rubric),'rubricSha256':digest(args.rubric),
              'taskPath':str(args.task),'taskSha256':args.task_hash,'noise':0,'beforeCase':source.get('observations',{}).get('before',{}),
              'afterCase':source.get('observations',{}).get('after',{})}
    for side,key in [('before','beforeSuite'),('after','afterSuite')]:
        finite=[value for value in case_scores[side].values() if value is not None]
        aggregate=sum(finite)/len(finite) if finite else 0.0
        paths=[args.out/'suite'/result['caseId']/'result.json' for result in results]
        observation={'score':aggregate,'caseScores':case_scores[side],'judgeSha256':args.judge_hash,'suiteSha256':args.suite_hash,
                     'taskSha256':args.task_hash,'rubricSha256':digest(args.rubric),'suiteComplete':complete,
                     'execution':{'model':'gpt-6-luna','exitCode':0,'timedOut':False,'files':bindings(paths)}}
        path=args.out/(side+'-suite.json'); save(path,observation)
        evidence[key]={'path':str(path),'sha256':digest(path),'score':aggregate}
    save(args.out/'admission-evidence.json',evidence)
    admission=admit_lesson(evidence)
    result={'schema':'neyvia.C13-lesson-replay.v1','lessonId':record['id'],'source':source,'suite':results,'suiteComplete':complete,
            'admission':admission,'costUsd':sum(usage.get('costUsd',0) for item in [source,*results] for usage in item.get('usage',[])),
            'blockedCases':[item for item in results if item['status']=='blocked'],'rubricSha256':digest(args.rubric),
            'scope':'fresh output-only first drafts and rendered HTML; unsupported historical native/tool environments block admission'}
    save(args.out/'result.json',result)
    print(json.dumps({'accepted':admission['accepted'],'sourceImproved':source.get('improved'),
                      'suiteComplete':complete,'blockedCases':len(result['blockedCases']),'costUsd':result['costUsd']}),flush=True)


if __name__=='__main__': main()
