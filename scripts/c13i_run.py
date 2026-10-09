"""Resumable R12 page comparison, using Obscura and metered tool-free models.

Inference calls are bounded model calls, not collaborating/spawned agents.
Both arms start with the identical selected Sol source, and use identical
render/check/critic contracts. Large raw images and model streams live on D:.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
os.environ['NEYVIA_TOOL_AUTO_UPDATE']='0'
os.environ['FLUXIO_WATCHDOG_AUTOSTART']='0'
os.environ['NEYVIA_COORDINATOR_AUTOSTART']='0'
os.environ['NEYVIA_C13_OBSCURA_STARTUP_MS']='45000'

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent.subprocess_utils import install_hidden_subprocess_default
install_hidden_subprocess_default()
from grant_agent.taste_fewshot import STATE, gate, save, nearest, digest
from grant_agent.taste_checks import page_checks, prompt_view
from grant_agent.taste_model import invoke, object_schema, successful_call
from grant_agent.taste_context import image_packet, source_projection, compact_manual
from grant_agent.taste_episode_export import append as append_labels, retention

PROOF=REPO/'proof/r12'
RAW=Path('D:/NeyviaRuns/r12')
TASKS={'T1':'landing.html','T2':'rare-ui.html'}
WEB_PORT=48801
ENGINE_PORT=48802
REPLAY_REPAIR=None


def read(path):return json.loads(Path(path).read_bytes())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def observed_checks(path,report):
    checks=page_checks(path,report,corrective=3,require_controls=True)
    for probe in (PROOF/'diagnostics').glob('*alternate*.json'):
        case=read(probe)
        if case['sourceSha256']!=sha(path) or case['keyboardPassed']:continue
        if sha(case['reportPath'])!=case['reportSha256']:raise ValueError('Alternate destination receipt changed')
        check=next(c for c in checks['checks'] if c['check']=='control-coverage')
        check['passed']=False
        check.setdefault('hits',[]).append({'selector':'#filing-pad','detail':'Actual alternate destinations failed',
            'source':str(probe),'destinations':case['destinations']})
    checks['blocks']=sum(c['level']=='block' and not c['passed'] for c in checks['checks'])
    return checks


def seed():
    selections={}
    for task,name in TASKS.items():
        candidates=[]
        for run in (['r11'] if task=='T1' else ['r10','r11']):
            for path in (REPO/'proof'/run/'arm-sol'/task/'evidence').glob('*/round-*/round.json'):
                row=read(path)
                artifact=path.parent/'artifact.html'
                if artifact.exists():candidates.append((row['critique']['quality'],-row['pageChecks']['blocks'],row['round'],path,row))
        best=max(candidates,key=lambda r:r[:3]);path,row=best[3:]
        target=PROOF/'seed'/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((path.parent/'artifact.html').read_bytes())
        selections[task]={'source':str(path.parent/'artifact.html'),'sha256':sha(target),'recordedScore':row['critique']['quality'],
                          'recordedBlocks':row['pageChecks']['blocks'],'scoreScope':row.get('reviewScope'),'roundSource':str(path)}
        for arm in ['fusion-v2','sol-alone','luna-alone']:
            dest=PROOF/arm/task/'work'/name;dest.parent.mkdir(parents=True,exist_ok=True)
            if not dest.exists():dest.write_bytes(target.read_bytes())
    save(PROOF/'seed/selection.json',selections);print(json.dumps(selections),flush=True)


def render(path,out):
    target=out/'render';target.mkdir(parents=True,exist_ok=True)
    report_path=target/'report.json'
    driver=digest([sha(REPO/'scripts'/name) for name in ['c13_render.mjs','c13_observed.mjs','c13_obscura_host.py']]+[sha(PROOF/'seed/rare-journeys.json'),sha(REPO/'src/grant_agent/browser_render_profile.js')])
    if report_path.exists() and read(report_path).get('html_sha256')==sha(path) and len(read(report_path).get('screenshots',[]))==4 and read(report_path).get('verificationDriverSha256')==driver:
        return read(report_path)
    if report_path.exists():
        ordinal=1
        while (out/('failed-render-'+str(ordinal))).exists():ordinal+=1
        archive=out/('failed-render-'+str(ordinal));archive.mkdir()
        for file in target.iterdir():
            if file.is_file():shutil.copyfile(file,archive/file.name)
        if (out/'render-process.json').exists():shutil.copyfile(out/'render-process.json',archive/'process.json')
    args=['node',str(REPO/'scripts/c13_render.mjs'),'--html',str(path.resolve()),'--out',str(target.resolve()),
          '--port',str(WEB_PORT),'--engine-port',str(ENGINE_PORT)]
    if path.name in {'rare-ui.html','accepted-before.html'} and 'T2' in out.parts:
        args+=['--journeys',str(PROOF/'seed/rare-journeys.json')]
    started=time.perf_counter();launched=time.time()
    result=subprocess.run(args,cwd=REPO,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',timeout=1400)
    save(out/'render-process.json',{'exitCode':result.returncode,'stdout':result.stdout,'stderr':result.stderr[-5000:],
                                  'elapsedSec':time.perf_counter()-started,'command':args,'startedAtUnix':launched,'driverSha256':driver})
    if not report_path.exists():raise RuntimeError('Obscura produced no report: '+result.stderr[-1000:])
    report=read(report_path)
    if report_path.stat().st_mtime<launched-1 or report.get('html_sha256')!=sha(path):raise RuntimeError('Renderer did not produce a fresh bound report')
    if len(report.get('screenshots',[]))!=4:raise RuntimeError('Incomplete Obscura variants')
    report['verificationDriverSha256']=driver;save(report_path,report)
    return report


def inspect(path,out):
    report=render(path,out);checks=observed_checks(path,report)
    save(out/'checks.json',checks)
    return report,checks


def critique(path,report,checks,out,task,model='gpt-6.1-sol',selectors=(),selected=None):
    dest=out/'critic-v2'
    if successful_call(dest) and (out/'quality.json').exists() and read(out/'quality.json')['artifactSha256']==sha(path) and read(out/'quality.json').get('checksSha256')==digest(checks) and all(any(e['path']==shot['path'] and e.get('sha256')==shot['sha256'] for e in read(out/'quality.json').get('imageManifest',[])) for shot in report['screenshots']):
        return read(dest/'response.json'),read(dest/'usage.json')
    # A four-image limit on image_packet used to spend the entire quota on
    # light desktop sections. Bind one actual full-page image per variant.
    images=[s['path'] for s in report['screenshots']]
    manifest=[{'observation':s['variant'],'path':s['path'],'sha256':s['sha256']} for s in report['screenshots']]
    if selected:
        for image,entry in zip(*selected):
            if image not in images:images.append(image);manifest.append(entry)
    if len(images)<2:raise ValueError('Critic needs both dark and light evidence')
    schema=object_schema({'quality':{'type':'integer','minimum':0,'maximum':100},
        'ready':{'type':'boolean'},'reason':{'type':'string'},
        'repairs':{'type':'array','items':object_schema({'selector':{'type':'string'},'reason':{'type':'string'},'fix':{'type':'string'}})}})
    selection=read(PROOF/'seed/selection.json')[task]
    source_task=Path(selection['roundSource'].split('\\evidence\\')[0].split('/evidence/')[0])/'task.txt'
    brief=source_task.read_text(encoding='utf-8')
    personal=read(STATE/'personal.json')['records']
    conditioning=nearest(personal,brief+' '+json.dumps(prompt_view(checks)),images=images[:2],count=4)
    prompt=('Judge the ACTUAL dark/light page screenshots as a whole. Score 0..100. A functional blocking check means ready=false. '
            'Keep Paul\'s aspect reasons in mind. A button label must fit; measured geometry and meaningful motion matter. '
            'Give at most THREE concrete targeted repairs; preserve successful content and mechanisms. Do not infer quality from author or previous score. '
            'Do not praise clipped text or flattened generic UI.\nBRIEF:'+brief+'\nPAUL EXAMPLES:'+json.dumps(conditioning)+
            '\nCAPTURES:'+json.dumps(manifest)+'\nCHECKS:'+json.dumps(prompt_view(checks))+
            '\nMOTION AND CONTROL OBSERVATIONS:'+json.dumps({'motion':report.get('motion',{}).get('meaningful'),
                'sequences':[{k:s[k] for k in ['name','meaningful','reason','changed'] if k in s} for s in report.get('motion',{}).get('sequences',[])],
                'controls':[{k:v[k] for k in ['viewport','theme','exercised','discovered','coverage_complete','passed'] if k in v} for v in report['variants']]})[:2500]+
            '\nCONTENT:'+json.dumps(source_projection(path.read_text(encoding='utf-8'))['sections'])[:5500])
    response,usage=invoke(prompt,dest,schema,images=images,model=model,effort='low',bounded=True,timeout=600)
    save(out/'quality.json',response | {'artifactSha256':sha(path),'checksSha256':digest(checks),'usage':usage,'imageManifest':manifest,'scope':'fresh page review of four rendered theme/viewport crops plus any selected issue crop'})
    return response,usage


def repair(path,report,checks,verdict,out,task,model,patch_feedback=None):
    dest=out/'repair'
    if successful_call(dest) and patch_feedback is None:return read(dest/'response.json'),read(dest/'usage.json')
    if REPLAY_REPAIR and patch_feedback is None:
        original=read(REPLAY_REPAIR/'patch.json');call=REPLAY_REPAIR/'repair'
        pending=read(out/'patch.json') if (out/'patch.json').exists() else None
        source_sha=sha(out/'before.html') if pending and sha(path)==pending['afterSha256'] else sha(path)
        if source_sha!=original['beforeSha256'] or not successful_call(call) or read(call/'usage.json')['model']!=model:
            raise ValueError('Replay requires the identical original source and the actual matching model receipt')
        save(out/'replayed-repair.json',{'source':str(call),'responseSha256':sha(call/'response.json'),
             'usageSha256':sha(call/'usage.json'),'beforeSha256':source_sha,'newModelCall':False})
        return read(call/'response.json'),read(call/'usage.json')
    schema=object_schema({'edits':{'type':'array','minItems':1,'maxItems':6,'items':object_schema({
        'old':{'type':'string'},'new':{'type':'string'},'reason':{'type':'string'}})},'summary':{'type':'string'}})
    personal=read(STATE/'personal.json')['records']
    guidance=nearest(personal,json.dumps(verdict)+json.dumps(prompt_view(checks)),count=4)
    prompt=('Repair this existing page in place. Return literal old/new replacements, each old occurs EXACTLY ONCE in ORIGINAL HTML. '
            'At most six edits, no rewrite. Combine edits to the same original region into ONE replacement; ranges cannot overlap. Fix current blocking checks first, then the critic\'s top defect. '
            'Preserve distinctive illustrations, rare mechanism algorithms, citations and the note demo. '
            'The full filing journey currently shifts vertically when its status wraps during pickup. Reserve stable status/control geometry in ALL states, especially on phones: pickup text must not change total page height or move the SVG frame mid-stroke. Keep real touch/pointer destination hit-testing and never fabricate the filed status. '
            'Preserve legitimate disabled states. ALL THREE original filing destinations (Check again, Keep proof, Discard sample) must remain usable by keyboard and drag. Never restrict hit-testing or Enter to only Keep proof. Return proof must return a filed proof, not fabricate pickup while unfiled. The driver supplies actual keyboard prerequisites and full Space/ArrowDown/ArrowUp/Enter filing journeys, with a Keep proof assertion; do not fake status updates or make idempotent controls toggle merely to satisfy the harness. For phone SVG clipping, remove conflicting min-height/height restrictions and use a viewport that preserves the actual viewBox aspect ratio; CSS viewBox properties do nothing. Responsive SVG layouts must also update data-c13-path to their actual current viewBox destination coordinates: an unchanged desktop endpoint can land between phone trays. Preserve real destination hit-testing and the Keep proof assertion. '
            'Preserve a meaningful, ordered before/intermediate/settled motion sequence and reduced-motion support. '
            'Copy should sound human, not SaaS. No em/en dashes, no invented dates. '
            'Obscura renders CSS through its own engine; inspect actual measured box facts. '
            'For labels inside a button, use flex centring plus adequate min-height/padding. '
            'Prefer neutral colors in rgb syntax if CSS color parsing is suspect. A theme-specific foreground fix must preserve contrast in BOTH themes: use explicit html[data-theme] selectors with a separate light and dark color, including hover/focus. Never apply a dark-theme text color unconditionally to a dark light-theme button. Do not use CSS viewBox/x/y properties to move SVG geometry.\nPAUL:'+json.dumps(guidance)+
            '\nCRITIC:'+json.dumps(verdict)+'\nBLOCKS:'+json.dumps(prompt_view(checks))+
            '\nLITERAL PATCH FEEDBACK:'+json.dumps(patch_feedback)+
            '\nHTML:\n'+path.read_text(encoding='utf-8'))
    return invoke(prompt,dest,schema,model=model,effort='low',bounded=True,timeout=600)


def apply(path,edits,out):
    patch_started=time.perf_counter()
    source=path.read_text(encoding='utf-8');proposed=source
    applied=[];ignored=[];ranges=[]
    for edit in edits:
        if edit['old']==edit['new']:
            ignored.append(edit);continue
        position=source.find(edit['old']) if edit['old'] else -1
        stop=position+len(edit['old'])
        conflict=any(position<b and stop>a for a,b,_ in ranges)
        if position<0 or source.count(edit['old'])!=1 or conflict:
            save(out/'patch-refused.json',{'reason':'Literal old must occur once in original source and ranges cannot overlap',
                'edit':edit,'overlap':conflict,'originalMatches':source.count(edit['old']),
                'sourceChanged':False,'sourceSha256':sha(path)})
            raise ValueError('Ambiguous or overlapping literal patch')
        ranges.append((position,stop,edit['new']));applied.append(edit)
    if not applied:raise ValueError('A repair must make a meaningful literal change')
    for start,stop,replacement in sorted(ranges,reverse=True):
        proposed=proposed[:start]+replacement+proposed[stop:]
    churn=sum(len(edit['old'])+len(edit['new']) for edit in applied)/(len(source)+len(proposed))
    if churn>.35:raise ValueError('Repair exceeded 35% churn')
    (out/'before.html').write_bytes(path.read_bytes())
    path.write_text(proposed,encoding='utf-8')
    save(out/'patch.json',{'beforeSha256':sha(out/'before.html'),'afterSha256':sha(path),
        'churn':churn,'churnKind':'conservative edited-span fraction; equal interior characters count as touched',
        'processingSec':time.perf_counter()-patch_started,'edits':applied,'ignoredNoops':ignored})


def decisions(arm,task,report,checks,out,prior=None):
    """Use the same finite check/crop questions in both measured workflows."""
    out.mkdir(parents=True,exist_ok=True)
    records=[]
    failed=[c for c in checks['checks'] if c['level']=='block' and not c['passed']]
    inspected=failed or [next(c for c in checks['checks'] if c['check']=='text-box-fit')]
    for index,check in enumerate(inspected):
        facts={'check':check['check'],'passed':check['passed'],'hits':check.get('hits',[])[:3],
               'engineFrontier':any('frontier' in str(h).lower() or 'unmeasur' in str(h).lower() for h in check.get('hits',[]))}
        target=out/('failure-'+str(index)+'.json')
        if target.exists() and read(target).get('factsSha256')==digest(facts):result=read(target)
        elif arm=='fusion-v2':result=gate('failure',facts,group='r12/'+arm+'/'+task,output=target)
        else:
            # Sol alone retains the existing deterministic checks. Do not
            # manufacture a paid call to make LAYA's check reproduction save.
            result={'answer':not facts['passed'] and not facts['engineFrontier'],'route':'script','kind':'failure',
                    'usage':None,'factsSha256':digest(facts)};save(target,result)
        records.append(result)
    hit=next((h for c in failed for h in c['hits'] if h.get('selector')),None)
    if not hit and prior:
        hit=next((h for c in prior['checks'] for h in c.get('hits',[]) if h.get('selector')),None)
    known_issue=bool(hit)
    if not hit:
        control=next((c for v in report['variants'] for c in v.get('controls',[]) if c.get('id')),None)
        if control:hit={'selector':control['id'],'detail':'Current control for the next critic inspection; no known blocker.'}
    if hit:
        selector=hit['selector'];region=next((r for v in report['variants'] if v['viewport']=='desktop' and v['theme']=='light'
                 for r in v.get('regions',[]) if r['selector']==selector),None)
        if region:
            images,manifest=image_packet(report,'Issue',out/'crop',selectors=[selector],rotation=0,max_images=1,max_actions=0)
            facts={'issue':json.dumps(hit)[:500], 'hasKnownIssue':known_issue, 'first':{'description':'Localized defect '+selector,'region':region['rect']},
                   'second':{'description':'Whole desktop-light overview','region':None}}
            target=out/'crop.json'
            if target.exists() and read(target).get('factsSha256')==digest(facts):result=read(target)
            elif arm=='fusion-v2':result=gate('crop',facts,group='r12/'+arm+'/'+task,output=target)
            else:
                result={'answer':True,'route':'script','kind':'crop','usage':None,'factsSha256':digest(facts)};save(target,result)
            result['selectedImage']=manifest[0] if result['answer'] and result['route']!='escalate' and images else report['screenshots'][0]
            save(target,result);records.append(result)
    save(out/'decisions.json',records);return records


def baseline(task):
    path=PROOF/'seed'/TASKS[task];out=RAW/'baseline'/task
    report,checks=inspect(path,out)
    quality,usage=critique(path,report,checks,out,task)
    save(PROOF/'baseline'/task/'summary.json',{'artifactSha256':sha(path),'checks':checks,'quality':quality,
        'reportPath':str(out/'render/report.json'),'qualityPath':str(out/'quality.json'),'usage':usage})
    print(json.dumps({'baseline':task,'blocks':checks['blocks'],'quality':quality['quality']}),flush=True)


def loop(arm,task,rounds):
    path=PROOF/arm/task/'work'/TASKS[task]
    base=read(PROOF/'baseline'/task/'summary.json')
    accepted_report_path=base['reportPath']
    report=read(accepted_report_path);checks=base['checks'];quality=base['quality']
    accepted=path.read_bytes();history=[]
    model='gpt-6-luna' if arm in {'fusion-v2','luna-alone'} else 'gpt-6.1-sol'
    from c13i_data import repair_facts
    ledger=PROOF/arm/task/'history.json'
    if ledger.exists():
        history=read(ledger)
        if history:
            current=history[-1]
            accepted_report_path=current['acceptedReportPath']
            report=read(accepted_report_path);checks=current['acceptedChecks'];quality=current['acceptedQuality']
            expected=current['artifactSha256']
            candidates=[path,PROOF/'seed'/TASKS[task],*list((RAW/arm/task).glob('round-*/*.html'))]
            snapshot=next((p for p in candidates if p.is_file() and sha(p)==expected),None)
            if snapshot is None:raise ValueError('Accepted source snapshot unavailable; refuse unsafe resume')
            accepted=snapshot.read_bytes()
            current_checks=observed_checks(snapshot,report)
            if current_checks['blocks']>checks['blocks']:
                checks=current_checks
                verifier_out=RAW/arm/task/'accepted-verifier';verifier_out.mkdir(parents=True,exist_ok=True)
                save(verifier_out/'checks.json',checks)
                quality,_=critique(snapshot,report,checks,verifier_out,task)
            final_summary=PROOF/arm/task/'summary.json'
            if final_summary.exists() and read(final_summary)['artifactSha256']==expected:
                latest=read(final_summary);quality=latest['quality']
                accepted_report_path=latest['reportPath']
                report=read(accepted_report_path)
                if report['html_sha256']!=expected:raise ValueError('Freshest accepted report does not bind source')
                checks=observed_checks(snapshot,report)
                save(RAW/arm/task/'before-current-checks.json',checks)
    driver=digest([sha(REPO/'scripts'/name) for name in ['c13_render.mjs','c13_observed.mjs','c13_obscura_host.py']]+[sha(PROOF/'seed/rare-journeys.json'),sha(REPO/'src/grant_agent/browser_render_profile.js')])
    if report.get('verificationDriverSha256')!=driver and len(history)<rounds:
        before_path=RAW/arm/task/'accepted-before.html';before_path.parent.mkdir(parents=True,exist_ok=True)
        before_path.write_bytes(accepted)
        report,checks=inspect(before_path,RAW/arm/task/'accepted-current')
        accepted_report_path=str(RAW/arm/task/'accepted-current/render/report.json')
        quality,_=critique(before_path,report,checks,RAW/arm/task/'accepted-current',task)
    for number in range(len(history)+1,rounds+1):
        out=RAW/arm/task/('round-'+str(number));out.mkdir(parents=True,exist_ok=True)
        before_report=report;before_checks=checks;before_quality=quality
        pending=read(out/'patch.json') if (out/'patch.json').exists() else None
        if path.read_bytes()!=accepted and not (pending and sha(path)==pending['afterSha256']):
            path.write_bytes(accepted)
        response,usage=repair(path,report,checks,quality,out,task,model)
        if not (out/'patch.json').exists() or sha(path)!=read(out/'patch.json')['afterSha256']:
            for attempt in range(3):
                try:
                    apply(path,response['edits'],out);break
                except ValueError as error:
                    if attempt==2:raise
                    detail=read(out/'patch-refused.json') if (out/'patch-refused.json').exists() else {'reason':str(error)}
                    save(out/('patch-refused-attempt-'+str(attempt+1)+'.json'),detail)
                    response,usage=repair(path,report,checks,quality,out,task,model,patch_feedback=detail)
        report,checks=inspect(path,out)
        routine=decisions(arm,task,report,checks,out/'decisions',before_checks)
        row=lambda r,c,q:{'interaction':r,'pageChecks':c,'critique':q,'change':response['summary']}
        facts=repair_facts(row(before_report,before_checks,before_quality),row(report,checks,{}))
        old_variants={(v['viewport'],v['theme']):v for v in before_report['variants']}
        failed_journeys=sum(bool(old_variants[(v['viewport'],v['theme'])].get('passed')) and not v.get('passed') for v in report['variants'])
        facts['lostControls']+=failed_journeys
        facts['changedRegions']=response['summary'][:450]
        facts['sameDriverRevision']=before_report.get('verificationDriverSha256')==report.get('verificationDriverSha256')
        decision=None
        if arm=='fusion-v2':
            image=next(s['path'] for s in report['screenshots'] if s['viewport']=='desktop' and s['theme']=='light')
            decision=gate('repair',facts,images=[image],group='r12/'+arm+'/'+task,output=out/'keep-revert.json')
        paid=True
        if decision and decision['route']=='laya':
            keep=decision['answer'];paid=False
            quality=before_quality | {'qualityScope':'retained prior score; no new critic score assigned'}
        else:
            crop=next((d['selectedImage'] for d in routine if d.get('kind')=='crop' and d.get('selectedImage')),None)
            chosen=([crop['path']],[crop]) if crop else None
            quality,_=critique(path,report,checks,out,task,selected=chosen)
            keep=(quality['quality']>=before_quality['quality'] or
                  before_checks['blocks']>checks['blocks'] and quality['ready']) and not facts['newBlockingChecks'] and not facts['lostControls']
        if not keep:
            path.write_bytes(accepted);report=before_report;checks=before_checks;quality=before_quality
        else:accepted=path.read_bytes()
        (out/'accepted.html').write_bytes(accepted)
        accepted_report_path=(out/'render/report.json') if keep else accepted_report_path
        item={'round':number,'model':model,'usage':usage,'keep':keep,'gate':decision,'paidCritic':paid,
              'routineDecisions':routine,'proposedChecks':read(out/'checks.json'),'acceptedChecks':checks,'acceptedQuality':quality,
              'acceptedReportPath':str(accepted_report_path),'artifactSha256':sha(path),
              'acceptedSnapshot':str(out/'accepted.html'),'beforeArtifactSha256':sha(out/'before.html'),
              'proposedArtifactSha256':read(out/'patch.json')['afterSha256'],'raw':str(out)}
        history.append(item);save(ledger,history)
        append_labels([retention(item,arm,task)])
        print(json.dumps({'arm':arm,'task':task,'round':number,'keep':keep,'route':decision['route'] if decision else 'sol',
                          'blocks':checks['blocks']}),flush=True)
        if checks['blocks']==0 and report['passed'] and number>=2:break
    if path.read_bytes()!=accepted:path.write_bytes(accepted)
    finalout=RAW/arm/task/'final';finalout.mkdir(parents=True,exist_ok=True)
    # Reuse an actual accepted render only while every bound input and output
    # still matches. The independent final critic remains a fresh paid review.
    bound=(report.get('html_sha256')==sha(path) and
           report.get('verificationDriverSha256')==driver and
           len(report.get('screenshots',[]))==4 and
           all(Path(s['path']).is_file() and sha(s['path'])==s['sha256'] for s in report['screenshots']))
    if bound:
        checks=observed_checks(path,report)
        save(finalout/'checks.json',checks)
        final_report_path=accepted_report_path
    else:
        report,checks=inspect(path,finalout)
        final_report_path=str(finalout/'render/report.json')
    final_routine=decisions(arm,task,report,checks,finalout/'decisions',checks)
    crop=next((d['selectedImage'] for d in final_routine if d.get('kind')=='crop' and d.get('selectedImage')),None)
    chosen=([crop['path']],[crop]) if crop else None
    quality,usage=critique(path,report,checks,finalout,task,selected=chosen)
    summary={'arm':arm,'task':task,'artifactSha256':sha(path),'checks':checks,'quality':quality,'usage':usage,
             'reportPath':str(final_report_path),'qualityPath':str(finalout/'quality.json'),'raw':str(finalout),
             'routineDecisions':final_routine,
             'complete':checks['blocks']==0 and quality['ready'] and report['passed'] and not report.get('errors'),
             'rounds':len(history)}
    save(PROOF/arm/task/'summary.json',summary);print(json.dumps({'final':arm+'/'+task,'blocks':checks['blocks'],'quality':quality['quality']}),flush=True)


def main():
    global WEB_PORT,ENGINE_PORT,REPLAY_REPAIR
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['seed','baseline','loop'],required=True)
    parser.add_argument('--task',choices=['T1','T2']);parser.add_argument('--arm',choices=['fusion-v2','sol-alone','luna-alone']);parser.add_argument('--rounds',type=int,default=3)
    parser.add_argument('--port',type=int,default=48801);parser.add_argument('--engine-port',type=int,default=48802)
    parser.add_argument('--replay-repair');args=parser.parse_args()
    if args.replay_repair:
        REPLAY_REPAIR=Path(args.replay_repair).resolve()
        if args.phase!='loop' or not REPLAY_REPAIR.is_relative_to((RAW/args.arm/args.task).resolve()):
            raise ValueError('Replay is restricted to the same owned arm and task')
    WEB_PORT,ENGINE_PORT=args.port,args.engine_port
    if WEB_PORT not in range(48801,48810) or ENGINE_PORT not in range(48801,48810) or WEB_PORT==ENGINE_PORT:
        raise ValueError('Two distinct assigned C13 ports required')
    if args.phase=='seed':seed()
    elif args.phase=='baseline':baseline(args.task)
    else:loop(args.arm,args.task,args.rounds)


if __name__=='__main__':main()
