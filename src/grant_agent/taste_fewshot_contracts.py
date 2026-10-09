"""Real-data observations for the authored R12 Connected Language checks."""
import json
from pathlib import Path
from .taste_fewshot import STATE, REPO, digest, lexical_embedding, nearest


def personal_facts(root):
    data=json.loads((STATE/'personal.json').read_bytes())
    rows=data['records']
    feedback=json.loads((REPO/'proof/votes-export/paul-feedback.json').read_bytes())
    reasons=[reason for group in feedback['rounds'] for reason in group['reasons']]
    expected_votes=list((REPO/'proof/votes-export').glob('round*/*/*.json'))
    covered={Path(r['source']).resolve() for r in rows if isinstance(r.get('source'),str)}
    identities=[r for r in rows if r['labelKind']=='identity']
    quality=[r for r in rows if r['labelKind']=='quality']
    all_aspects={aspect for row in rows for aspect in row['aspects']}
    hashes_ok=all(__import__('hashlib').sha256(Path(s['path']).read_bytes()).hexdigest()==s['sha256'] for s in data['sources'])
    retrieved=nearest(rows,'motion animation button text clipping',count=3)
    unknown={'id':'unknown','pairId':'unknown','labelKind':'identity','label':'L','reason':'identity only','aspects':['voice'],'group':'unknown'}
    return {'votesComplete':all(p.resolve() in covered for p in expected_votes),
            'reasonsComplete':all(any(r['reason']==reason and r['labelKind']=='aspect' for r in rows) for reason in reasons),
            'earlierRoundsPresent':all(r['present'] and r['answerKey'] for r in data['earlierRounds']),
            'identityLabels':len(identities),'qualityLabels':len(quality),'aspectLabels':sum(r['labelKind']=='aspect' for r in rows),
            'allSevenAspects':all_aspects=={'motion','voice','overflow','centring','spelling','geometry','polish'},
            'sourceHashesMatch':hashes_ok,'headFree':not data['headTrained'],
            'retrievesReasons':len(retrieved)==3 and all(r['reason'] for r in retrieved),
            'identitiesRemainDistinct':all(r['labelKind']=='identity' for r in nearest([unknown],'identity',count=1)),
            'textEmbeddingNormalized':abs(sum(x*x for x in lexical_embedding('rough note motion and polish'))-1)<1e-8}


def real_facts(root):
    data=json.loads((STATE/'real-pairs.json').read_bytes());rows=data['cases']
    hashes={split:{s['sha256'] for r in rows if r['split']==split for s in r['images'] if 'sha256' in s} for split in ['train','calibration','heldout']}
    group_splits={r['group']:{x['split'] for x in rows if x['group']==r['group']} for r in rows}
    return {'realObscura':all('/evidence/' in r['source']['path'].replace('\\','/') and Path(r['source']['path']).is_file() for r in rows),
            'allDecisionKinds':{r['kind'] for r in rows}=={'repair','failure','crop'},
            'heldoutIsR11':all(r['group'].startswith('r11/') for r in rows if r['split']=='heldout'),
            'groupsDisjoint':all(len(v)==1 for v in group_splits.values()),
            'pixelsDisjoint':not(hashes['heldout']&(hashes['train']|hashes['calibration'])),
            'noAfterScoreInInputs':all(not({'quality','afterQuality','afterCritique','expected'} & set(r['facts'])) for r in rows if r['kind']=='repair'),
            'realRepairHeldout':sum(r['split']=='heldout' and r['kind']=='repair' for r in rows),
            'calibrationRepairCases':sum(r['split']=='calibration' and r['kind']=='repair' for r in rows)}


def gate_facts(root):
    report=json.loads((STATE/'heldout-report.json').read_bytes())
    policy=json.loads((STATE/'calibration.json').read_bytes())
    calibration=json.loads((STATE/'calibration-decisions.json').read_bytes())
    heldout=json.loads((STATE/'heldout-decisions.json').read_bytes())
    return {'calibrationBound':digest(calibration)==policy['sourceSha256'],
            'heldoutBound':digest(heldout)==report['decisionsSha256'] and digest(policy)==report['policySha256'],
            'frozenModelIdentity':len({r['prediction']['identity']['checkpoint_sha256'] for r in calibration+heldout})==1,
            'actualInference':all(r['prediction']['decisionId'] and r['prediction']['usage']['input_tokens']>0 for r in calibration+heldout),
            'repairAdmitted':report['admitted']['repair'],'failureAdmitted':report['admitted']['failure'],'cropAdmitted':report['admitted']['crop'],
            'repairCoverage':report['metrics']['repair']['coverage'],
            'repairAccuracy':report['metrics']['repair']['selectiveAccuracy'] or 0}


def calibration_facts(root):
    policy=json.loads((STATE/'calibration.json').read_bytes())
    rows=json.loads((STATE/'calibration-decisions.json').read_bytes())
    first=json.loads((STATE/'attempt-1/calibration.json').read_bytes())
    pixel=json.loads((STATE/'pixel-calibration.json').read_bytes())
    return {'frozenRowsMatch':digest(rows)==policy['sourceSha256'],
            'allGatesQualified':all(v['threshold'] is not None and v['threshold']>0 and v['accuracy']>=.9 for v in policy['gates'].values()),
            'noHeadTraining':not policy['headTrained'],
            'firstAttemptDeactivated':all(v['threshold'] is None for v in first['gates'].values()),
            'subjectiveNotQualified':pixel['gate']['threshold'] is None}


def font_facts(root):
    from .taste_spelling import check
    report=json.loads(Path('D:/NeyviaRuns/r12/baseline/T2/render/report.json').read_bytes())
    actual=[r for v in report['variants'] for r in v['corrective']['text']
            if r['selector'].startswith('#face-name-') or r['selector']=='#filing-status']
    before=json.loads((REPO/'proof/r12/baseline/T2/preflight-summary.json').read_bytes())
    flagged={h['word'].casefold() for c in before['checks']['checks'] if c['check']=='spelling' for h in c['hits']}
    negative=[dict(actual[0],text='Ariall Helveticaa unfileed')]
    return {'actualFontLabelsAccepted':len(actual)>0 and check(actual)==[],
            'realFalsePositivesCaptured':{'arial','helvetica','unfiled'}<=flagged,
            'nearMissesBlocked':len(check(negative))==3,
            'noCitationWaiver':all(not r.get('citation') and not r.get('code') for r in actual)}


def negative_facts(root):
    rows=json.loads((REPO/'proof/r12/negative/real-routes.json').read_bytes())
    corpus=json.loads((STATE/'real-pairs.json').read_bytes())['cases']
    original={r['id']:r for r in corpus}
    bad=next(r for r in rows if r['scenario']=='measured-regression')
    missing=next(r for r in rows if r['scenario']=='missing-observations')
    return {'realCaseBindings':all(digest(original[r['caseId']])==r['caseSha256'] and
                original[r['caseId']]['facts']==r['facts'] for r in rows),
            'actualInference':all(r['prediction']['decisionId'] and
                r['prediction']['usage']['input_tokens']>0 for r in rows),
            'regressionEscalates':bool(bad['facts']['newBlockingChecks']) and
                bad['prediction']['route']=='escalate',
            'unsupportedAbstains':not missing['facts'].get('hasRecordedChecks') and
                missing['prediction']['confidence']==0 and missing['prediction']['route']=='escalate'}


def pipeline_facts(root):
    from hashlib import sha256
    read=lambda p:json.loads(Path(p).read_bytes())
    sha=lambda p:sha256(Path(p).read_bytes()).hexdigest()
    selections=read(REPO/'proof/r12/seed/selection.json')
    conversions={r['task']:r for r in read(REPO/'proof/r12/seed/newline-canonicalization.json')['rows']}
    initial_conversions=[]
    observed=[];continuity=[];gates=[];crop_bindings=[];routine_bindings=[];replay_bindings=[]
    for arm in ['fusion-v2','sol-alone','luna-alone']:
        for task,name in [('T1','landing.html'),('T2','rare-ui.html')]:
            folder=REPO/'proof/r12'/arm/task
            summary=read(folder/'summary.json');report=read(summary['reportPath'])
            history=read(folder/'history.json');prior=selections[task]['sha256']
            artifact=folder/'work'/name
            checks=summary['checks']
            observed.append({'arm':arm,'task':task,'summary':summary,'report':report,
                'bound':sha(artifact)==report['html_sha256']==summary['artifactSha256'],
                'shotsBound':len(report['screenshots'])==4 and all(sha(s['path'])==s['sha256'] for s in report['screenshots']),
                'checksBound':digest(read(Path(summary['raw'])/'checks.json'))==digest(checks)})
            for row in history:
                patch=read(Path(row['raw'])/'patch.json')
                before=sha(Path(row['raw'])/'before.html')
                replay_path=Path(row['raw'])/'replayed-repair.json'
                if replay_path.exists():
                    replay=read(replay_path);origin=Path(replay['source'])
                    replay_bindings.append(origin.resolve().is_relative_to(Path('D:/NeyviaRuns/r12',arm,task).resolve())
                        and replay['newModelCall'] is False and replay['beforeSha256']==before
                        and replay['responseSha256']==sha(origin/'response.json')
                        and replay['usageSha256']==sha(origin/'usage.json') and read(origin/'usage.json')['model']==row['model'])
                initial=False
                if row['round']==1 and arm in conversions[task]['legacyArms']:
                    conversion=conversions[task]
                    initial=prior==conversion['originalSha256'] and before==conversion['convertedSha256'] and (
                        REPO/'proof/r12/seed'/name).read_bytes().replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')==(
                            Path(row['raw'])/'before.html').read_bytes()
                    initial_conversions.append(initial)
                continuity.append((before==prior or initial) and row['artifactSha256']==
                                  (patch['afterSha256'] if row['keep'] else prior))
                prior=row['artifactSha256']
                if arm=='fusion-v2':
                    gate=row['gate']
                    gates.append(bool(gate and gate['decisionId'] and gate['identity']['weights_frozen']
                        and gate['identity']['device']=='cpu' and gate['usage']['input_tokens']>0
                        and {d['kind'] for d in row['routineDecisions']}=={'failure','crop'}
                        and all(d['decisionId'] for d in row['routineDecisions'])
                        and (row['paidCritic'] or (gate['route']=='laya' and row['keep']==gate['answer']))))
            continuity.append(prior==summary['artifactSha256'])
            failed=[c for c in checks['checks'] if c['level']=='block' and not c['passed']]
            inspected=failed or [next(c for c in checks['checks'] if c['check']=='text-box-fit')]
            actual_failure=[d for d in summary.get('routineDecisions',[]) if d['kind']=='failure']
            expected_facts=[{'check':c['check'],'passed':c['passed'],'hits':c.get('hits',[])[:3],
                'engineFrontier':any('frontier' in str(h).lower() or 'unmeasur' in str(h).lower() for h in c.get('hits',[]))} for c in inspected]
            routine_bindings.append(len(actual_failure)==len(expected_facts) and all(d['factsSha256']==digest(f) for d,f in zip(actual_failure,expected_facts)))
            if arm=='fusion-v2' and not any(h.get('selector') for c in checks['checks'] for h in c.get('hits',[])):
                crop_decision=next((d for d in summary.get('routineDecisions',[]) if d['kind']=='crop'),{})
                routine_bindings.append(crop_decision.get('cropSupported') is False and crop_decision.get('route')=='escalate')
            quality=read(Path(summary['raw'])/'quality.json')
            manifest=quality.get('imageManifest')
            if not manifest:
                prompt=(Path(summary['raw'])/'critic-v2/prompt.txt').read_text(encoding='utf-8')
                manifest=json.loads(prompt.split('\nCAPTURES:',1)[1].split('\nCHECKS:',1)[0])
            selected=next((d.get('selectedImage') for d in summary.get('routineDecisions',[]) if d['kind']=='crop'),None)
            crop_bindings.append(bool(selected and any(e['path']==selected['path'] for e in manifest)
                and {s['path'] for s in report['screenshots']}<=set(e['path'] for e in manifest)
                and quality['artifactSha256']==summary['artifactSha256']
                and quality['checksSha256']==digest(checks)))
    import sys
    import tempfile
    sys.path.insert(0,str(REPO/'scripts'))
    import c13i_run as runner
    old_replay=runner.REPLAY_REPAIR
    refused=False
    try:
        runner.REPLAY_REPAIR=Path('D:/NeyviaRuns/r12/sol-alone/T2/round-5')
        original=read(runner.REPLAY_REPAIR/'patch.json')
        source=REPO/'proof/r12/seed/landing.html'
        if sha(source)!=original['beforeSha256']:
            with tempfile.TemporaryDirectory(prefix='replay-contract-',dir='D:/NeyviaRuns/r12') as directory:
                out=Path(directory)
                if not out.resolve().is_relative_to(Path('D:/NeyviaRuns/r12').resolve()):
                    raise ValueError('Replay contract scratch escaped its owned root')
                try:runner.repair(source,{},{},{},out,'T1','gpt-6.1-sol')
                except ValueError as error:
                    refused='identical original source' in str(error) and not list(out.iterdir())
    finally:runner.REPLAY_REPAIR=old_replay
    return {'sixCompletedPages':len(observed)==6 and all(o['summary']['complete'] for o in observed),
            'initialNewlineConversionBound':len(initial_conversions)==4 and all(initial_conversions) and
                (REPO/'proof/r12/seed/landing.html').read_bytes().replace(b'\n',b'\r\n')!=
                    Path('D:/NeyviaRuns/r12/fusion-v2/T2/round-1/before.html').read_bytes(),
            'sourceRenderCheckBindings':all(o['bound'] and o['shotsBound'] and o['checksBound'] for o in observed),
            'actualControlJourneys':all(o['report']['passed'] and not o['report'].get('errors') and len(o['report']['variants'])==4
                and all(v['passed'] and v['coverage_complete'] and v['exercised']==v['discovered'] and v['discovered']>0
                        for v in o['report']['variants']) for o in observed),
            'blockingChecksPassed':all(o['summary']['checks']['blocks']==0 and
                {'spelling','text-box-fit','figure-centering','diagram-geometry'}<=
                    {c['check'] for c in o['summary']['checks']['checks'] if c['passed']} for o in observed),
            'sameStartingSources':all(selections[t]['sha256']==sha(REPO/'proof/r12/seed'/name) for t,name in [('T1','landing.html'),('T2','rare-ui.html')]) and all(continuity),
            'everyFusionRoundGated':len(gates)>=4 and all(gates),
            'selectedCropsReachCritic':all(crop_bindings),'routineFactsAreCurrent':all(routine_bindings),
            'paidRepairReplayBound':refused and all(replay_bindings)}


def packet_facts(root):
    from hashlib import sha256
    read=lambda p:json.loads(Path(p).read_bytes())
    sha=lambda p:sha256(Path(p).read_bytes()).hexdigest()
    key=read(REPO/'proof/r12/SPOILER-key.json');report=read(REPO/'proof/r12/report.json')
    shots=[s for t in key['tasks'].values() for s in t['shots']]
    return {'twentyFourBlindShots':len(shots)==24 and all(sha(REPO/'proof/r12'/s['path'])==s['sha256']==s['sourceSha256'] for s in shots),
            'bothThemesAndArms':all(len(t['comparisons'])==3 and
                {frozenset(c['arms'].values()) for c in t['comparisons'].values()}==
                    {frozenset(p) for p in [('fusion-v2','sol-alone'),('luna-alone','sol-alone'),('fusion-v2','luna-alone')]} and
                all(set(c['arms'])=={'A','B'} and {(s['label'],s['theme']) for s in t['shots'] if s['comparison']==number}==
                    {('A','light'),('A','dark'),('B','light'),('B','dark')} for number,c in t['comparisons'].items())
                for t in key['tasks'].values()),
            'measuredUsage':report['totals']['allUsageComplete'] and all(a['usageComplete'] and a['tokens']>0 for a in report['arms']),
            'noInventedCallSavings':all(c['criticCallsActuallyOmitted']==next(a['criticCallsOmitted'] for a in report['arms']
                if a['task']==c['task'] and a['arm']==c['candidate']) for c in report['comparison']),
            'calibrationCostsIncluded':report['totals']['localDecisionTokens']>report['totals']['localCalibrationTokens'],
            'baseModelBoundaryVisible':report['ablation']['withoutModelSameEpisodeAnswers'] and
                report['ablation']['baseModelAgreement']<1}


def driver_facts(root):
    from hashlib import sha256
    from .taste_checks import control_coverage
    read=lambda path:json.loads(Path(path).read_bytes())
    before=read(REPO/'proof/r12/diagnostics/control-frontier-before.json')
    resolved=[];compiled=[];revisions=[];preparations=[];recipes=[];filed=[];delivered=[]
    current=digest([sha256((REPO/'scripts'/name).read_bytes()).hexdigest()
                    for name in ['c13_render.mjs','c13_observed.mjs','c13_obscura_host.py']]+[sha256((REPO/'proof/r12/seed/rare-journeys.json').read_bytes()).hexdigest(),sha256((REPO/'src/grant_agent/browser_render_profile.js').read_bytes()).hexdigest()])
    for arm in ['fusion-v2','sol-alone','luna-alone']:
        for task in ['T1','T2']:
            summary=read(REPO/'proof/r12'/arm/task/'summary.json')
            report=read(summary['reportPath']);revisions.append(report.get('verificationDriverSha256')==current)
            if task!='T2':continue
            recipes.append(report.get('journeyRecipes')==read(REPO/'proof/r12/seed/rare-journeys.json'))
            controls=[c for v in report['variants'] for c in v['controls']]
            filed += [m for c in controls if c['id']=='#filing-pad' for m in c['modes']]
            preparations += [m['prerequisite'] for c in controls for m in c['modes'] if m.get('prerequisite')]
            resolved += [m['effect'] for c in controls if c['target']=='lens-ring' for m in c['modes']]
            compiled += [m['gesturePathCompilation'] for c in controls for m in c['modes'] if 'gesturePathCompilation' in m]
            for control in controls:
                for mode in control['modes']:
                    if 'gesturePathCompilation' not in mode:continue
                    points=mode.get('gestureInput',{}).get('deliveredPoints',[])
                    delivered.append(len(points)>=8 and all(len(p['screenCTM'])==6 and
                        abs(p['x']-(p['screenCTM'][0]*p['svg'][0]+p['screenCTM'][2]*p['svg'][1]+p['screenCTM'][4]))<1e-6 and
                        abs(p['y']-(p['screenCTM'][1]*p['svg'][0]+p['screenCTM'][3]*p['svg'][1]+p['screenCTM'][5]))<1e-6 for p in points))
    correct=[]
    for path in compiled:
        basis=path['viewBox']
        normalized=[[(u-basis[0])/basis[2],(v-basis[1])/basis[3]] for u,v in path['sourcePoints']]
        correct.append(normalized==path['normalized'] and 2<=len(normalized)<=16 and
                       all(-.25<=n<=1.25 for p in normalized for n in p) and
                       all(0<=n<=1 for n in normalized[0]))
    bad_targets=[m for v in before['variants'] for c in v['controls'] if c.get('target')=='lens-ring'
                 for m in c['modes'] if 'Discovered control disappeared' in m.get('error','')]
    return {'realTargetFailurePreserved':len(bad_targets)>=4,
            'bareTargetsResolve':len(resolved)>=12 and all(resolved),
            'legacyPathsDelivered':len(compiled)>=8 and all(correct),
            'strokeTransformsMeasured':len(delivered)>=8 and all(delivered),
            'currentDriverBindings':len(revisions)==6 and all(revisions),
            'oldCoverageStillBlocks':len(control_coverage(before))>0,
            'actualStatePreparation':len(preparations)>=4 and all(p['enabled'] and p['keys'] and
                p['before_sha256']!=p['after_sha256'] and p['observedChanges'] for p in preparations),
            'matchedStateRecipes':len(recipes)==3 and all(recipes),
            'actualFiledJourneys':len(filed)==36 and all(m['effect'] and 'Keep proof' in m.get('assertion',{}).get('text','') for m in filed)}


def label_export_facts(root):
    import sys
    from .taste_episode_export import LABELS
    sys.path.insert(0,str(REPO/'scripts'))
    from c13i_labels import collect
    expected,counts=collect()
    actual=[json.loads(line) for line in LABELS.read_text(encoding='utf-8').splitlines() if line]
    ids=[r['episodeId'] for r in actual];by_id={r['episodeId']:r for r in actual}
    receipt=json.loads((REPO/'proof/r12/label-export.json').read_bytes())
    return {'allUsedLabelsExported':all(r['episodeId'] in by_id and
                {k:v for k,v in by_id[r['episodeId']].items() if k!='at'}==
                {k:v for k,v in r.items() if k!='at'} for r in expected),
            'countsBound':counts==receipt['counts'] and counts['personal']==47 and counts['historicalRetention']==151
                and set(receipt['episodeIds'])=={r['episodeId'] for r in expected},
            'oneEpisodePerLine':len(ids)==len(set(ids)) and all(r['domain']=='taste' and
                r['layer'] in {'personal','corrective'} and r['at'] and r['source'] and
                'pageId' in r['input'] and 'screenshotPath' in r['input'] for r in actual),
            'missingImagesExplicit':sum(r['layer']=='personal' and r['input']['screenshotPath'] is None
                and r['input']['evidenceKind']=='reason-only' for r in expected)==counts['reasonOnlyPersonal']}


def destination_facts(root):
    from hashlib import sha256
    read=lambda p:json.loads(Path(p).read_bytes())
    sha=lambda p:sha256(Path(p).read_bytes()).hexdigest()
    before=read(REPO/'proof/r12/diagnostics/luna-alternate-before.json')
    bad=read(before['reportPath'])
    bound=lambda case:sha(case['sourceSnapshot'])==case['sourceSha256'] and sha(case['reportPath'])==case['reportSha256'] and read(case['reportPath'])['scriptSha256']==sha(REPO/'scripts/c13i_alternate.mjs')
    current=[read(REPO/'proof/r12/diagnostics'/(arm+'-alternate.json')) for arm in ['fusion-v2','sol-alone','luna-alone']]
    return {'realRegressionBound':bound(before) and bad['html_sha256']==before['sourceSha256'] and
                len(before['destinations'])==2 and all(not m['effect'] and m['keyboardInput'][0]=='Space' and
                    m['keyboardInput'][-1]=='Enter' and 'Choose Keep proof' in m['assertion']['text'] for m in before['destinations']),
            'allDestinationsDelivered':all(bound(c) and c['sourceSha256']==sha(REPO/'proof/r12'/c['arm']/'T2/work/rare-ui.html')
                and c['keyboardPassed'] and {m['destination'] for m in c['destinations']}=={'Check again','Discard sample'}
                and all(m['effect'] and m['destination'] in m['assertion']['text'] for m in c['destinations']) for c in current)}

def probe_facts(root):
    from hashlib import sha256
    read=lambda path:json.loads(Path(path).read_bytes())
    evidence=read(REPO/'proof/r12/diagnostics/lens-probe.json')
    raw=Path(evidence['sourceReportPath'])
    report=read(raw)
    control=report['variants'][0]['controls'][0]
    modes=control['modes']
    return {'boundedScope':report['scope']=='bounded-real-control-probe' and len(report['variants'])==1,
            'realSeedBound':sha256((REPO/'proof/r12/seed/rare-ui.html').read_bytes()).hexdigest()==report['html_sha256'],
            'rawBound':sha256(raw.read_bytes()).hexdigest()==evidence['sourceReportSha256'],
            'twoActualEffects':report['passed'] and control['id']=='#lens-pad' and
                {m['mode'] for m in modes}=={'pointer','touch'} and all(m['effect'] and
                m['before_sha256']!=m['after_sha256'] and len(m.get('observedChanges',[]))>0 for m in modes),
            'actualViewBox':all(m['gesturePathCompilation']['viewBox']==[0,0,800,360] and
                m['gesturePathCompilation']['sourcePoints']==[[290,170],[535,170]] for m in modes)}

def filing_probe_facts(root):
    from hashlib import sha256
    read=lambda path:json.loads(Path(path).read_bytes())
    bad=read(Path('D:/NeyviaRuns/r12/diagnostics/filing-probe/report.json'))
    good=read(Path('D:/NeyviaRuns/r12/diagnostics/filing-probe-release/report.json'))
    failed=bad['variants'][0]['controls'][0]['modes']
    passed=good['variants'][0]['controls'][0]['modes']
    return {'identicalRealSource':bad['html_sha256']==good['html_sha256']==sha256((REPO/'proof/r12/diagnostics/filing-probe-source.html').read_bytes()).hexdigest(),
            'beforeActuallyUnfiled':not bad['passed'] and len(failed)==2 and all(not m['effect'] and 'unfiled' in m['assertion']['text'] for m in failed),
            'afterActuallyFiled':good['passed'] and {m['mode'] for m in passed}=={'pointer','touch'} and all(m['effect'] and 'Keep proof' in m['assertion']['text'] and m['before_sha256']!=m['after_sha256'] for m in passed),
            'boundedProbe':bad['scope']==good['scope']=='bounded-real-control-probe' and len(bad['variants'])==len(good['variants'])==1}
