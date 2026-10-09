"""Host-owned observers for the C13 executable manual contracts.
Disposable transport fixtures prove dispatch/accounting only, never live model quality.
"""
from __future__ import annotations
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from PIL import Image
from .taste_context import SourceIndex, compact_manual, driver_projection, image_packet, bounded_prompt, ContextBudgetError, source_projection, motion_packet
from .taste_budget import TasteBudget, BudgetExceeded
from . import taste_model
from .taste_laya import repair_route, check_triage
from .taste_checks import observed_checks

REPO=Path(__file__).resolve().parents[2]

def refused(fn, exception):
    try:fn()
    except exception:return True
    return False

def context_facts(root):
    manual=(REPO/'manuals/cl/taste.cl').read_text(encoding='utf-8')
    source='<html><section id="one"><h1>One</h1></section><section id="two">Two</section><script data-c13-section="one">let choice=1;</script></html>'
    windows=SourceIndex(source).windows(['#one'])
    descendants='<html><article class="cap"><div class="sample">A</div></article><article class="cap"><div class="sample">B</div></article><article class="cap"><div class="sample">C</div></article><div class="sample">Outside</div></html>'
    found=SourceIndex(descendants).find('.cap .sample')
    selected=''.join(w['source'] for w in SourceIndex(descendants).windows(['.cap .sample']))
    nested='<html><article id="panel"><div id="lens" tabindex="0">Lens</div></article><script>const lens=document.getElementById("lens");lens.onclick=()=>lens.textContent="Focused";</script></html>'
    shared='<html><style>'+''.join('.gesture%d{color:red}\n'%i for i in range(1000))+'</style><body><section id="region"><button class="gesture" id="target">Go</button></section><script>'+''.join("let other%d=document.querySelector('.gesture');\n"%i for i in range(1000))+"\nconst target=document.getElementById('target');target.onclick=()=>target.textContent='Changed';\n</script></body></html>"
    focused=SourceIndex(shared).windows(['#target'])
    pixels=root/'raw.png';Image.new('RGB',(1200,3000),'red').save(pixels)
    report={'passed':False,'screenshots':[],'variants':[]}
    for viewport in ['desktop','phone']:
        for theme in ['light','dark']:
            report['screenshots'].append({'viewport':viewport,'theme':theme,'variant':viewport+'-'+theme,'path':str(pixels)})
            report['variants'].append({'viewport':viewport,'theme':theme,'regions':[{'selector':'#one','section':'one','rect':[0,1000,1200,500]}],
                'controls':[{'id':'#one','modes':[{'mode':'pointer','effect':True}]},{'id':'#bad','dead':True,'modes':[{'mode':'touch','effect':False,'error':'dead'}]}]})
    paths,manifest=image_packet(report,'Candidate',root/'packet',selectors=['#one'])
    rotated,small=image_packet(report,'Anchor',root/'small',rotation=0,max_images=1)
    prompt=bounded_prompt('Immutable task','small guidance',root/'bounded',budget=400,raw='raw archived report '*10000)
    metrics=json.loads((root/'bounded/context-metrics.json').read_text(encoding='utf-8'))
    changed=source_projection(source,['#one'],[{'old':'One','new':'let choice=1;','rowId':'one'}])
    from .taste_gate import Sections
    citation=Sections('<article><h2>Bubble cursor</h2><p>Source: Grossman, “The bubble cursor,” CHI 2005. <a href="https://doi.org/example">ACM DOI</a></p></article>').records[0]
    ordinal=SourceIndex('<main><article><p class="source">A</p></article><article><p class="source">B</p></article></main>').find('article:nth-of-type(2) .source')
    from copy import deepcopy
    selected_report={**deepcopy(report),'html':str(root/'selected.html')}
    (root/'selected.html').write_text('<main><section id="one"><button id="bad">Bad</button></section><section id="two"><button id="other">Other</button></section></main>',encoding='utf-8')
    selected_report['variants'][0]['controls'].append({'id':'#other','dead':True,'modes':[{'mode':'keyboard','effect':False,'error':'dead'}]})
    return {
        'scopedFailures': [c['selector'] for c in driver_projection(selected_report,['#one'])['controls']]==['#bad'],
        'unresolvedRefused': refused(lambda:SourceIndex(source).windows(['article:nth-of-type(4) .source']),ContextBudgetError),
        'citationLabel':Sections.citation_title(citation,'https://doi.org/example')=='The bubble cursor',
        'qualifiedOrdinal':len(ordinal)==1 and 'B</p>' in '<main><article><p class="source">A</p></article><article><p class="source">B</p></article></main>'[ordinal[0]['start']:ordinal[0]['end']],
        'ownedHelper':any('let choice=1' in w['source'] for w in windows),
        'unaffectedSectionExcluded':all('id="two"' not in w['source'] for w in windows),
        'descendantCount':len(found),'allDescendants': 'C</div>' in selected and 'Outside' not in selected,
        'structuralOrdinal':SourceIndex(source).find('html>section:nth-of-type(2)')[0]['attrs']['id']=='two',
        'nestedHelper':any('lens.onclick' in w['source'] for w in SourceIndex(nested).windows(['#panel'])),
        'sharedWindowChars':sum(w['end']-w['start'] for w in focused),
        'targetedHelper':any('target.onclick' in w['source'] for w in focused),
        'cropCount':len(paths),'cropGeometry':all(m['crop'][1]>900 and max(m['size'])<=480 for m in manifest),
        'anchorImages':len(rotated),'anchorResolution':max(small[0]['size']),
        'failuresOnly':all(c['selector']=='#bad' for c in driver_projection(report)['controls']),
        'unknownGeometryRefused':refused(lambda:image_packet(report,'Candidate',root/'unknown',selectors=['#absent']),ContextBudgetError),
        'immutableRetained':'Immutable task' in prompt,'rawArchived':'raw archived report' not in prompt,'promptTokens':metrics['lastTokens'],
        'oversizeRefused':refused(lambda:bounded_prompt('Immutable task','unbounded '*1000,root/'denied',budget=400),ContextBudgetError),
        'duplicateReplacement': bool(source_projection('<section id="one">same</section><p>same</p>',['#one'],[{'old':'old','new':'same','rowId':'one'}],'<section id="one">old</section><p>same</p>')['changedWindows']),
        'changedSourceExact':any('let choice=1;' in w['source'] for w in changed['changedWindows']),
    }

def prefix_facts(root):
    manual=(REPO/'manuals/cl/taste.cl').read_text(encoding='utf-8')
    t1,t2=compact_manual(manual,rare=False),compact_manual(manual,rare=True)
    import re
    crops=re.findall(r'^  E crop (before|after) "([^"]+)" \[(\d+) (\d+) (\d+) (\d+)\]',manual,re.M)
    crop_bounds=True
    for side,path,x,y,w,h in crops:
        with Image.open(REPO/path) as image:
            crop_bounds=crop_bounds and int(x)+int(w)<=image.width and int(y)+int(h)<=image.height
    fields=('crop before','crop after','observe','reject','repair','not')
    complete=True
    for case in ('demonstrate','mechanism','proportion'):
        block=manual.split('E "'+case+'"')[1].split('\nE "')[0].split('\nJ ')[0]
        complete=complete and all('  E '+kind+' "' in block for kind in fields)
    runner=(REPO/'scripts/c13_run.py').read_text(encoding='utf-8')
    return {
        'actionEnumGuidance':'data-c13-action must be exactly one lowercase word: drag, cross, hold, or click.' in runner and 'data-c13-action="drag|cross|hold"' not in runner,
        'briefIsolation':'E "demonstrate"' in t1 and 'E "mechanism"' not in t1 and 'E "mechanism"' in t2 and 'E "demonstrate"' not in t2,
        'rubricAndChecks':all('J crit-fidelity' in p and 'J proportion' in p and all('host check '+n in p for n in ['theme-dark','side-void','visible-dash','stock-phrase','abstract-art']) for p in [t1,t2]),
        'stockProjected':all('good help' in p and 'think with care' in p for p in [t1,t2]),
        'voiceProjected':all('Plain voice, specific work' in p and 'No pitch phrases' in p for p in [t1,t2]),
        'motionProjected':all('Motion that explains the work' in p for p in [t1,t2]),
        'cropCount':len(crops),'cropBounds':crop_bounds,'caseFields':complete,
        'quantityProxiesAbsent':'"a lot" = 8' not in manual and '>= 8 vernacular' not in manual and '8+ words of its vernacular' not in manual,
    }

def budget_facts(root):
    model=taste_model
    b=TasteBudget(max_rounds=1,max_tokens=1000,max_usd=.02,max_call_tokens=500,max_call_usd=.01)
    b.start_round();round_limit=refused(b.start_round,BudgetExceeded)
    call_limit=refused(lambda:b.admit(model='gpt-6-luna',tokens=501,usd=.001),BudgetExceeded)
    b.admit(model='gpt-6-luna',tokens=300,usd=.005)
    b.account({'usageComplete':True,'usage':{'input_tokens':210,'cached_input_tokens':100,'output_tokens':100,'total_tokens':310},'costUsd':.001})
    overrun_closed='reservation' in b.snapshot()['closedReason'] and refused(lambda:b.admit(model='gpt-6-luna',tokens=1,usd=.00001),BudgetExceeded)
    valid={'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':60,'output_tokens':20}}
    usage,complete=model.measured_usage(json.dumps(valid)+'\n'+json.dumps(valid))
    capacity={'type':'turn.failed','error':{'message':'Selected model is at capacity. Please try a different model.'}}
    strict_capacity=model.rejected_before_inference(json.dumps(capacity)) and not model.rejected_before_inference(json.dumps(capacity)+'\n'+json.dumps({'type':'item.completed','item':{'type':'reasoning','text':'partial inference'}}))
    search=TasteBudget(max_tokens=3000000,max_call_tokens=500000,max_usd=1.1,max_call_usd=.85)
    search.calibration=[{'callKind':'draft','usageComplete':True,'searchEnabled':True,'usage':{'input_tokens':89706,'output_tokens':7982},'inputBreakdown':{'promptTextTokens':2897,'images':[]}}]
    draft=model.measured_reservation('bounded draft prompt',model.object_schema({'html':{'type':'string'}}),[],{'input':.1,'output':.5},search,search=True)
    search.calibration.append({'callKind':'research','usageComplete':True,'searchEnabled':False,'usage':{'input_tokens':90000,'output_tokens':100},'inputBreakdown':{'promptTextTokens':1000,'images':[]}})
    fixed=model.measured_reservation('tiny',model.object_schema({}),[],{'input':.1,'output':.5},search,search=False)
    seen=[];original=model.capture_bounded_process
    def fake(args,**kw):
        seen.append(args);Path(args[args.index('--output-last-message')+1]).write_text('{}')
        return {'stdout':json.dumps(valid),'stderr':'','returncode':0,'timedOut':False}
    try:
        model.capture_bounded_process=fake
        budget=TasteBudget(max_usd=.45)
        _,receipt=model.invoke('small prompt',root/'sol',model.object_schema({}),model='gpt-6.1-sol',budget=budget,reservation_tokens=1000,reservation_usd=.01,bounded=True)
        dispatch=seen[-1][seen[-1].index('--model')+1]=='gpt-6.1-sol'
        hidden_skills='skills.include_instructions=false' in seen[-1]
        model.invoke('another measured call',root/'sol',model.object_schema({}),model='gpt-6.1-sol',bounded=True)
        prior=(root/'sol/prior-invocation-1/usage.json').is_file()
        model.capture_bounded_process=lambda *a,**k:{'stdout':json.dumps(capacity),'stderr':'','returncode':1,'timedOut':False}
        retry=TasteBudget();refused(lambda:model.invoke('probe',root/'capacity',model.object_schema({}),budget=retry,effort='low'),RuntimeError)
        rejection=json.loads((root/'capacity/usage.json').read_text(encoding='utf-8'))
        free_capacity=rejection['rejectedBeforeInference'] and rejection['usageComplete'] and rejection['costUsd']==0 and retry.snapshot()['closedReason'] is None
        model.capture_bounded_process=fake;model.invoke('same model retry',root/'capacity',model.object_schema({}),budget=retry,effort='low')
        retry_calls=retry.snapshot()['calls']
        model.capture_bounded_process=lambda *a,**k:{'stdout':'','stderr':'provider failed','returncode':1,'timedOut':False}
        bad=TasteBudget();refused(lambda:model.invoke('small prompt',root/'missing',model.object_schema({}),budget=bad),RuntimeError)
        missing_closed=not bad.snapshot()['usageComplete'] and refused(lambda:bad.admit(model='gpt-6-luna',tokens=1,usd=.001),BudgetExceeded)
        model.capture_bounded_process=fake;model.invoke('retry',root/'missing',model.object_schema({}))
        failed_preserved=(root/'missing/failed-invocation-1/usage.json').is_file()
    finally:model.capture_bounded_process=original
    return {'roundLimit':round_limit,'callLimit':call_limit,'overrunClosed':overrun_closed,'totalTokens':usage['total_tokens'],'cachedTokens':usage['cached_input_tokens'],'usageComplete':complete,
            'strictCapacity':strict_capacity,'searchedDraftReservation':draft['tokens'],'fixedEnvelopeReservation':fixed['tokens'],
            'solDispatch':dispatch,'solCost':receipt['costUsd'],'hiddenSkillsDisabled':hidden_skills,'priorPreserved':prior,
            'capacityFree':free_capacity,'retryCalls':retry_calls,'missingUsageClosed':missing_closed,'failedPreserved':failed_preserved,
            'malformedUsageRefused':not model.measured_usage('')[1] and not model.measured_usage(json.dumps({'type':'turn.completed','usage':{'input_tokens':5,'cached_input_tokens':6,'output_tokens':1}}))[1]}

def laya_facts(root):
    diffs=[dict(rowId='A',cause='research',axis='content',gap=3,repair='fix source'),dict(rowId='B',cause='broken',axis='fidelity',gap=3,repair='fix input')]
    answered=repair_route(root,diffs,system1_fn=lambda *a,**k:dict(available=True,answer='B',confidence=.99,escalate=False))
    escalated=repair_route(root,diffs,system1_fn=lambda *a,**k:dict(available=True,answer='B',confidence=.6))
    previous=os.environ.get('NEYVIA_LAYA_URL')
    try:
        os.environ['NEYVIA_LAYA_URL']='http://127.0.0.1:8793'
        unavailable=repair_route(root,diffs)
    finally:
        if previous is None:os.environ.pop('NEYVIA_LAYA_URL',None)
        else:os.environ['NEYVIA_LAYA_URL']=previous
    blocked=check_triage(root,{'checks':[{'check':'theme-dark','level':'block','passed':False}]})
    rows=[json.loads(s) for s in (root/'.neyvia/laya/decisions.jsonl').read_text(encoding='utf-8').splitlines()]
    return {'answer':answered['decision'],'escalated':escalated['route'],'outOfScopeRefused':unavailable['route'],
            'blockingCannotBeWaived':blocked['route']=='deterministic' and blocked['blocking']==['theme-dark'],
            'outcomes':[r['outcome'] for r in rows],'outcomeOrder':[r['outcome'] for r in rows]==['answered','escalated','unavailable','deterministic'],'noClaimedSavings':all(r['tokensSavedEstimate']==0 for r in rows)}

def motion_facts(root):
    report=json.loads((REPO/'scripts/evidence/C13g-motion/positive/report.json').read_text(encoding='utf-8'))
    report['variants']=[{'diagramIssues':report['diagramIssues']}]
    from .taste_checks import _summary
    geometry_summary=_summary({'check':'diagram-geometry','hits':[{'labels':['Option A','Option B']},{'detail':'clipped text'}]})
    positive=all(not hits for _,_,hits in observed_checks(report))
    bad=deepcopy(report);bad['motion']['reduced']['changed']=True
    moving=bool(next(h for n,_,h in observed_checks(bad) if n=='reduced-motion'))
    connectors=json.loads((REPO/'scripts/evidence/C13g-contracts/connectors/report.json').read_text(encoding='utf-8'))
    fonts=json.loads((REPO/'scripts/evidence/C13g-contracts/font-geometry/report.json').read_text(encoding='utf-8'))
    native_fonts=fonts['fontProbe']
    fonts_ok=fonts['engine']=='obscura' and native_fonts[0]['html']<native_fonts[1]['html']<native_fonts[2]['html'] and len(fonts['diagramIssues'])==1 and fonts['diagramIssues'][0]['selector']=='#clipped' and fonts['diagramIssues'][0]['cause']=='label-overflows-node'
    from .taste_checks import prompt_view
    projection=prompt_view({'checks':[{'check':'diagram-geometry','level':'block','passed':False,'hits':fonts['diagramIssues']}]})
    measurement_ok=projection[0]['measurements'][0]['rect']['w']==fonts['diagramIssues'][0]['rect']['w']
    issues=connectors['diagramIssues']
    connector_facts=connectors['engine']=='obscura' and len(issues)==2 and all(h['selector']=='#bad-map' and h['cause']=='misaligned-connector' and h['distance']==25 for h in issues)
    paths,manifest=motion_packet(report,root/'packet')
    return {'nativeFontGeometry':fonts_ok,'measuredProjection':measurement_ok,'straightConnectors':connector_facts,'geometrySummary':geometry_summary=='Option A, Option B; clipped text','positiveObserved':positive,'movingReducedRejected':moving,'missingObservationsRejected':all(h for _,_,h in observed_checks({})),
            'orderedSheets':len(paths),'orderedFrames':all(len(m['frames'])>=4 for m in manifest),
            'engine':report['engine'],'proofPath':'scripts/evidence/C13g-motion/positive/report.json'}


def page_check_facts(root):
    from .taste_checks import page_checks,side_voids,theme_dark,prompt_view,gate_reasons
    def load(folder,html=None,report='render/report.json'):
        folder=REPO/folder;p=folder/report
        result=page_checks(REPO/html if html else folder/'artifact.html',json.loads(p.read_text(encoding='utf-8')),base=p.parent)
        return result,{c['check']:c for c in result['checks']}
    result,by=load('proof/r9/arm-luna/T1/evidence/landing/round-4')
    dark=by['theme-dark']['hits'];voids=by['side-void']['hits']
    initial=[]
    for number in (1,2):
        _,before=load('proof/r9/arm-luna/T1/evidence/landing/round-'+str(number))
        initial.append(not before['theme-dark']['passed'] and len(before['side-void']['hits'])==2 and len(before['visible-dash']['hits'])==3)
    _,anchor=load('proof/r9/arm-luna/T1/evidence/anchor-landing',html='proof/r6-blind/arm-c/landing.html',report='report.json')
    _,r8=load('proof/r8/arm-luna/final/T1/evidence/landing/round-4')
    shots=[]
    for viewport in ('desktop','phone'):
        for theme in ('light','dark'):
            path=root/(viewport+'-'+theme+'.png');Image.new('L',(40,40),245).save(path)
            shots.append({'viewport':viewport,'theme':theme,'path':str(path)})
    absent=theme_dark({'screenshots':shots},'<style>body{background:#fff}</style>')
    ignored=theme_dark({'screenshots':shots},'<style>@media(prefers-color-scheme:dark){body{background:#111}}</style>')
    for shot in shots:
        if shot['theme']=='dark':Image.new('L',(40,40),24).save(shot['path'])
    genuine=theme_dark({'screenshots':shots},'<style>@media(prefers-color-scheme:dark){body{background:#111}}</style>')
    missing=theme_dark({'screenshots':[s for s in shots if s['theme']=='light']},'')
    return {
        'ignoredDark':[h['viewport'] for h in dark]==['desktop','phone'] and all(h['cause']=='render-ignored-dark-theme' and h['identicalToLight'] and h['darkMedianLuma']>200 for h in dark),
        'invalidRender':not result['renderValid'],'voidColumns':len(voids)==2 and all(h['side']=='left' and h['share']>=.25 and h['columnFill']<=.06 for h in voids),
        'voidLocations':abs(voids[0]['region'][1]-1217)<12 and abs(voids[1]['region'][1]-1843)<12,
        'dashes':[h['text'] for h in by['visible-dash']['hits']]==['01 — Capabilities','02 — In practice','03 — Why work with me'],
        'stock':[h['phrase'] for h in by['stock-phrase']['hits']]==['good help'],
        'metaphorWarnings':len(by['abstract-art']['hits'])==2 and by['abstract-art']['level']=='warn',
        'historicalBlocks':result['blocks'],'repairableChecks':all(v['fix'] for v in prompt_view(result)) and any('side-void' in v for v in gate_reasons(result)),
        'earlyFailures':all(initial),'anchorNegative':all(anchor[n]['passed'] for n in ['side-void','visible-dash','stock-phrase']),
        'anchorDarkInvalid':{h['cause'] for h in anchor['theme-dark']['hits']}=={'render-ignored-dark-theme'},
        'r8Negative':r8['theme-dark']['passed'] and r8['side-void']['passed'],
        'claudeVoidNegative':all(side_voids(REPO/p)==[] for p in ['proof/c13-taste/shots-edge-before-switch/r3-c-landing-d-light.jpg','proof/c13-taste/shots-edge-before-switch/r3-c-rare-ui-d-light.jpg']),
        'lunaVoidPositive':len(side_voids(REPO/'proof/c13-taste/shots-edge-before-switch/r3-l-landing-d-light.jpg'))>=1,
        'noThemeDefect':{h['cause'] for h in absent}=={'page-has-no-dark-theme'},
        'rendererDefect':{h['cause'] for h in ignored}=={'render-ignored-dark-theme'},
        'genuineDarkAccepted':genuine==[],'missingDarkRefused':{h['cause'] for h in missing}=={'missing-capture'},
    }

def native_theme_facts(root):
    report=json.loads((REPO/'scripts/evidence/C13g-contracts/native-theme/report.json').read_text(encoding='utf-8'))
    states=report.get('nativeTheme',[])
    return {'nativeContexts':len(states),'engine':report['engine'],
        'dark':any(s['scheme']=='dark' and s['dark'] and not s['light'] and s['mode']=='240px' and s['background'].replace(' ','')=='rgb(16,32,48)' for s in states),
        'light':any(s['scheme']=='light' and s['light'] and not s['dark'] and s['mode']=='100px' and s['background'].replace(' ','')=='rgb(255,255,255)' for s in states),
        'proofPath':'scripts/evidence/C13g-contracts/native-theme/report.json'}

def r11_facts(root):
    from .taste_spelling import check as spelling
    from .taste_vision import cases, compare, STATE
    from .laya_hooks import triage_taste, verify
    import urllib.request
    os.environ['NEYVIA_LAYA_URL'] = 'http://127.0.0.1:48809'
    health = json.load(urllib.request.urlopen(os.environ['NEYVIA_LAYA_URL'] + '/v1/health'))
    evidence = {'checks':[{'check':name,'passed':True,'hits':[]} for name in ('theme-dark','side-void','visible-dash','stock-phrase','abstract-art')], 'blocks':0,'renderValid':True}
    triage = triage_taste(root, evidence)
    confirmation = verify('taste_triage', triage.get('decision') or 'ask_critic', evidence, root=root)
    benchmark = json.loads((REPO/'proof/r11/jevbench-before.json').read_bytes())
    personal = cases('personal')
    return {'liveLaya':health['status']=='ready' and triage.get('route')!='unavailable',
            'verifyRan':confirmation.get('ms',0)>0,
            'bilingualCorrect':not spelling([{'text':"Hello world. Bonjour bienvenue. Mina’s notes. Meeting Thurs.",'selector':'#copy'}]),
            'typosBlocked':bool(spelling([{'text':'Recieve the mesage.','selector':'#copy'}])),
            'separateLayers':all(r['source'].startswith('Paul') for r in personal) and all(not r['source'].startswith('Paul') for r in cases('corrective')),
            'personalAbstains':json.loads((STATE/'personal-candidate.json').read_bytes())['admitted'] is False,
            'jevbenchFloor':benchmark['n']==231 and benchmark['correct']>=138,
            'publicCases':sum(r['source'].startswith(('UICrit','Enrico')) for r in cases('corrective')),
            'historicalCases':sum(r['source']=='historical-deterministic' for r in cases('corrective'))}

from .taste_fewshot_contracts import personal_facts, real_facts, gate_facts, calibration_facts, font_facts, negative_facts, pipeline_facts, packet_facts, driver_facts, probe_facts, filing_probe_facts, label_export_facts, destination_facts
OBSERVERS={'r12-filing-probe':filing_probe_facts,'r12-probe':probe_facts,'r12-driver':driver_facts,'r12-negative':negative_facts,'r12-pipeline':pipeline_facts,'r12-packet':packet_facts,'r12-fonts':font_facts,'r12-calibration':calibration_facts,'r12-personal':personal_facts,'r12-real':real_facts,'r12-gate':gate_facts,'r11':r11_facts,'page-checks':page_check_facts,'native-theme':native_theme_facts,'context':context_facts,'prefix':prefix_facts,'budget':budget_facts,'laya':laya_facts,'motion':motion_facts}
OBSERVERS['r12-label-export']=label_export_facts
OBSERVERS['r12-destinations']=destination_facts
def corrective_render_facts(root):
    import subprocess
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    from .taste_spelling import check as spelling
    destination = REPO / 'proof/r11/corrective-contract'
    destination.mkdir(parents=True, exist_ok=True)
    reports = {}
    for kind in ('bad', 'good'):
        width = 80 if kind == 'bad' else 270
        # Obscura does not center inline SVG through text-align. The positive
        # fixture uses the actual 120px offset, not that unsupported declaration.
        margin = 240 if kind == 'bad' else 120
        copy = 'Recieve the mesage' if kind == 'bad' else 'Receive the message. Bonjour bienvenue.'
        html = destination / (kind + '.html')
        semantic = 'Decision diagram' if kind=='bad' else 'Letter specimen'
        html.write_text(f'<!doctype html><html><style>body{{margin:20px}}#label{{width:{width}px;height:40px;white-space:nowrap;font:20px Arial;padding:2px}}figure{{width:300px;text-align:center;margin:20px 0}}#drawing{{margin-left:{margin}px}}</style><p id="copy">{copy}</p><button id="label">Continue to the next page</button><figure id="plate"><svg id="drawing" width="60" height="60" viewBox="0 0 60 60"><circle cx="30" cy="30" r="25" fill="green"/></svg></figure><svg id="label-shape" aria-label="{semantic}" width="300" height="100" viewBox="0 0 300 100"><circle cx="120" cy="45" r="40" fill="#eee"/><text x="50" y="50" font-size="20">A very long label</text></svg></html>', encoding='utf-8')
        out = destination / kind
        process = subprocess.run(['node', str(REPO/'scripts/c13_render.mjs'), '--html', str(html), '--out', str(out),
                                  '--port', '48805', '--capture-only', 'true'], cwd=REPO, capture_output=True,
                                 text=True, timeout=120, **hidden_windows_subprocess_kwargs())
        if process.returncode:
            raise RuntimeError(process.stderr[-1000:] or process.stdout[-1000:])
        reports[kind] = json.loads((out/'report.json').read_bytes())
    rows = lambda kind, field: [r for v in reports[kind]['variants'] for r in v['corrective'][field]]
    return {'engine':'obscura', 'badBox':any(r['selector']=='#label' for r in rows('bad','overflow')),
            'goodBox':not any(r['selector']=='#label' for r in rows('good','overflow')),
            'badCenter':bool(rows('bad','centering')), 'goodCenter':not rows('good','centering'),
            'badSpelling':bool(spelling(rows('bad','text'))), 'goodSpelling':not spelling(rows('good','text')),
            'badNodeLabel':any(r['cause']=='label-overflows-node' for v in reports['bad']['variants'] for r in v['diagramIssues']),
            'decorativeOverlapAccepted':not any(r['cause']=='label-overflows-node' for v in reports['good']['variants'] for r in v['diagramIssues'])}


OBSERVERS['corrective-render'] = corrective_render_facts

def vision_regression_facts(root):
    """A disposable wrong-label fit must not replace the real admitted head."""
    import shutil
    from . import taste_vision as vision
    original = vision.STATE
    fixture = Path(root)/'vision-regression'
    fixture.mkdir(parents=True,exist_ok=True)
    rows = [dict(r) for r in vision.cases('corrective')]
    for row in rows:
        if row['split']=='train':row['preferred'] *= -1
    vision.save(fixture/'corrective-cases.json',rows)
    shutil.copyfile(original/'corrective-head.json',fixture/'corrective-head.json')
    shutil.copytree(original/'embeddings',fixture/'embeddings',dirs_exist_ok=True)
    before = vision.sha(fixture/'corrective-head.json')
    try:
        vision.STATE = fixture
        candidate = vision.train('corrective')
    finally:
        vision.STATE = original
    return {'vetoed':not candidate['admitted'] and not candidate['regressionPassed'],
            'candidateAccuracy':candidate['heldoutAccuracy'],
            'headRetained':before==vision.sha(fixture/'corrective-head.json')}

OBSERVERS['r11-regression'] = vision_regression_facts

def vision_gate_facts(root):
    from .taste_vision import cases, compare, save
    held = [r for r in cases('corrective') if r['split']=='heldout']
    forward = [compare(r['before'],r['after']) for r in held]
    qualified = [(r,v) for r,v in zip(held,forward) if not v['escalate']]
    row, result = qualified[0]
    reverse = compare(row['after'],row['before'])
    same = compare(row['before'],row['before'])
    website = REPO/'proof/r11/arm-fusion/T1/sealed/light.png'
    outside = compare(website,website)
    save(REPO/'proof/r11/pixel-qualification.json',{'caseId':row['id'],'forward':result,
         'reverse':reverse,'same':same,'website':outside,'qualifiedHeldoutCases':len(qualified)})
    return {'qualifiedHeldoutCases':len(qualified),
            'bidirectional':result['answer']=='after' and reverse['answer']=='before' and min(result['confidenceLowerBound'],reverse['confidenceLowerBound'])>=.95,
            'sameAbstains':same['escalate'] and same['answer'] is None,
            'websiteAbstains':not outside['calibratedScopeSupported'] and outside['escalate'] and outside['answer'] is None}

OBSERVERS['r11-vision-gate'] = vision_gate_facts

def learning_policy_facts(root):
    from . import taste_vision as vision
    original=vision.STATE
    row=next(r for r in vision.cases('corrective') if r['split']=='heldout')
    try:
        vision.STATE=Path(root)/'learning-policy'
        pairs=[vision.append_pair('personal',row['before'],row['after'],preferred=1,
                group='new-vote-'+str(i),source='Paul-contract') for i in range(30)]
        repeated=vision.append_pair('personal',row['before'],row['after'],preferred=-1,
                   group=pairs[0]['group'],source='Paul-contract',reason='Later reason')
        vision.save(vision.STATE/'personal-head.json',{'contract':'Exists only to freeze split membership'})
        later=[vision.append_pair('personal',row['before'],row['after'],preferred=1,
               group='later-vote-'+str(i),source='Paul-contract') for i in range(30)]
        return {'newLabelsReachAllSplits':{r['split'] for r in pairs}=={'train','heldout','calibration'},
                'groupStable':repeated['split']==pairs[0]['split'],
                'heldoutFrozen':all(r['split']!='heldout' for r in later)}
    finally:
        vision.STATE=original

OBSERVERS['r11-learning-policy'] = learning_policy_facts

def r11_pipeline_facts(root):
    import zipfile
    import hashlib
    from .taste_vision import STATE, cases, sha, compare_variants
    report=json.loads((REPO/'proof/r11/report.json').read_bytes())
    arms=report['arms']
    layer=report['learning']['corrective']
    head=json.loads((STATE/'corrective-head.json').read_bytes())
    observed=next(iter(json.loads((REPO/'proof/r11/arm-fusion/T1/evidence/rounds.json').read_bytes()).values()))
    variants=compare_variants(observed[-1]['interaction'],json.loads(Path(observed[-1]['anchorReportPath']).read_bytes()),observed[-2])
    previous_hashes={(s['viewport'],s['theme']):s['sha256'] for s in observed[-2]['interaction']['screenshots']}
    groups={split:set() for split in ('train','calibration','heldout')}
    for row in cases('corrective'):
        identity=row['group']
        ids=[Path(row[k]).stem for k in ('before','after')] if row['source']=='UICrit-human-Enrico' else []
        groups[row['split']].update(('enrico:'+s for s in ids) if ids else [identity])
    disjoint=all(not groups[a]&groups[b] for a,b in [('train','heldout'),('train','calibration'),('heldout','calibration')])
    blind=[]
    key=json.loads((REPO/'proof/r11/blind-shots-key.SPOILER.json').read_bytes())
    for task,name in [('T1','landing'),('T2','rare-ui')]:
        for letter,arm in key[task].items():
            row=next(r for r in arms if r['arm']==arm and r['task']==task)
            for theme in ('light','dark'):
                blind.append(sha(REPO/'proof/r11/blind'/name/theme/(letter+'.png'))==row['shots'][theme]['sha256'])
    pixels=[]
    for arm in ('arm-fusion','arm-sol'):
        for p in (REPO/'proof/r11'/arm).glob('T*/evidence/*/round-*/laya-vision.json'):
            pixels += [json.loads(p.read_bytes())['reference']]
    archive_path=REPO/'proof/r11/raw-proof/manifest.json'
    archives_bound=archive_path.exists()
    if archives_bound:
        archives=json.loads(archive_path.read_bytes())['archives']
        archives_bound=bool(archives)
        for archive in archives:
            path=REPO/'proof/r11'/archive['path']
            archives_bound &= sha(path)==archive['sha256'] and path.stat().st_size<100_000_000
            with zipfile.ZipFile(path) as bundle:
                archives_bound &= set(bundle.namelist())=={r['path'] for r in archive['entries']}
                for item in archive['entries']:
                    parts=Path(item['path']).parts
                    archives_bound &= 'host-state.json' not in parts and 'browser' not in parts and not any(p.startswith('.') for p in parts)
                    with bundle.open(item['path']) as stream:
                        archives_bound &= hashlib.file_digest(stream,'sha256').hexdigest()==item['sha256']
    return {'fourArms':len(arms)==4,'budgets':all(r['budgetPassed'] for r in arms),
            'archivesBound':bool(archives_bound),
            'blindBound':len(blind)==8 and all(blind),'splitsDisjoint':disjoint,
            'distinctPixels':all(r['beforeSha256']!=r['afterSha256'] for layer_name in ('corrective','personal') for r in cases(layer_name)),
            'fourPixelVariants':len(variants)==4 and all(v['previous']['beforeSha256']==previous_hashes[(v['viewport'],v['theme'])] for v in variants),
            'afterFloor':report['jevbenchAfter']['correct']>=138 and report['jevbenchAfter']['n']==231,
            'regressionProtected':layer['admitted'] or (not layer['regressionPassed'] and head['heldoutAccuracy']>=layer['heldoutAccuracy']),
            'calibratedOnly':all(r.get('escalate') or r.get('confidenceLowerBound',0)>=.95 for r in pixels),
            'liveAudited':report['laya']['unavailable']==0 and report['laya']['duringRun']>0,
            'noInventedSavings':report['laya']['actualSkippedModelCalls']==0 and report['laya']['actualTimeSavedSec']==0,
            'honestCompletion':all(not r['doneOk'] or (not r['blocks'] and r['interactionPassed'] and r['fidelityPassed']) for r in arms)}

OBSERVERS['r11-pipeline'] = r11_pipeline_facts
class Contracts:
    def __init__(self,root):self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.cache={}
    def observe(self,case):
        if case not in OBSERVERS:raise ValueError('Unknown host-owned contract case')
        if case not in self.cache:
            with tempfile.TemporaryDirectory(prefix=case+'-',dir=self.root) as directory:
                self.cache[case]=OBSERVERS[case](Path(directory))
        return self.cache[case]
