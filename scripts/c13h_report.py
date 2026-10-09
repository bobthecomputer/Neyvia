"""Seal observed R11 artifacts, audit learning labels and publish a blind local packet."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import secrets
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'scripts'))
from grant_agent.taste_vision import STATE, cases, save, sha, train, serialized, append_pair, compare_variants
from grant_agent.laya_hooks import triage_taste, verify
from c13_run import measured_usage

PROOF = ROOT/'proof/r11'
LIMITS = {'arm-fusion':{'T1':.15,'T2':.30},'arm-sol':{'T1':1.10,'T2':2.75}}
NAMES = {'T1':'landing','T2':'rare-ui'}
read = lambda path: json.loads(Path(path).read_bytes())


def archive_rounds():
    """Keep replay evidence compact without committing runtime profiles or seal keys."""
    destination = PROOF/'raw-proof'
    destination.mkdir(exist_ok=True)
    archives = []
    for arm in LIMITS:
        chunks, chunk, size = [], [], 0
        for path in sorted((PROOF/arm).rglob('*')):
            if not path.is_file() or path.name == 'host-state.json':continue
            relative = path.relative_to(PROOF)
            if any(part == 'browser' or part.startswith('.') for part in relative.parts):continue
            if path.suffix not in ('.json', '.jsonl', '.html', '.txt', '.cl', '.png'):continue
            if chunk and size+path.stat().st_size>80_000_000:
                chunks.append(chunk); chunk, size = [], 0
            chunk.append(path); size += path.stat().st_size
        if chunk:chunks.append(chunk)
        for number, chunk in enumerate(chunks,1):
            target = destination/(arm+f'-{number:02d}.zip')
            entries = []
            with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
                for path in chunk:
                    relative = str(path.relative_to(PROOF)).replace('\\', '/')
                    bundle.write(path,relative)
                    entries.append({'path':relative,'bytes':path.stat().st_size,'sha256':sha(path)})
            archives.append({'path':str(target.relative_to(PROOF)), 'bytes':target.stat().st_size, 'sha256':sha(target), 'entries':entries})
    save(destination/'manifest.json', {'archives':archives,
         'excluded':'Runtime profiles, hidden directories, host-state seal keys and database files remain local.'})


def learn_votes(path=None):
    """Consume explicit quality votes, never identity guesses or missing votes."""
    path = Path(path) if path else PROOF/'paul-votes.json'
    if not path.exists():
        return 0
    base = path.parent
    key = read(base/'blind-shots-key.SPOILER.json')
    count = 0
    for vote in read(path)['votes']:
        task, winner = vote['task'], vote['preferred'].upper()
        if task not in NAMES or winner not in ('A','B','TIE') or not vote.get('reason'):
            raise ValueError('Quality vote needs task T1/T2, preferred A/B/tie and a reason')
        a = read(base/key[task]['A']/task/'sealed/receipt.json')
        b = read(base/key[task]['B']/task/'sealed/receipt.json')
        theme = vote.get('theme','light')
        if winner=='TIE':
            context_path=STATE/'personal-ties.json'
            context=read(context_path) if context_path.exists() else []
            item={**vote,'run':base.name,'beforeSha256':a['shots'][theme]['sha256'],'afterSha256':b['shots'][theme]['sha256']}
            if item not in context:context.append(item)
            save(context_path,context)
            continue
        append_pair('personal',a['shots'][theme]['path'],b['shots'][theme]['path'],
                    preferred=1 if winner=='B' else -1,group='paul-'+base.name+'-'+task,
                    source='Paul-quality-vote',reason=vote['reason'])
        count += 1
    train('personal')
    return count


@serialized
def audit_labels():
    path = STATE/'corrective-cases.json'
    rows = read(path)
    reports = {}
    for folder in (PROOF/'arm-fusion', PROOF/'arm-sol'):
        for p in folder.glob('T*/evidence/*/round-*/page-checks.json'):
            render = p.parent/'render/report.json'
            if not render.exists():
                continue
            report = read(render)
            shot = next((s for s in report['screenshots'] if s['viewport']=='desktop' and s['theme']=='light'),None)
            if shot:
                reports[shot['sha256']] = (read(p), report)
    exclusions = []
    public_splits = {r['group'].split(':')[-1]:r['split'] for r in rows if r['source']=='Enrico-Obscura-synthetic'}
    for row in rows:
        if row['beforeSha256'] == row['afterSha256']:
            reason = 'Identical captured pixels cannot supply a visual preference label; runtime evidence retained'
            row.update(excludedFromTraining=True, exclusionReason=reason)
            exclusions.append({'id':row['id'],'reason':reason})
            continue
        if row['source']=='UICrit-human-Enrico':
            ids = [Path(row[k]).stem for k in ('before','after')]
            if any(public_splits.get(i,row['split'])!=row['split'] for i in ids):
                reason = 'Underlying Enrico screen crosses training/calibration split across public sources'
                row.update(excludedFromTraining=True,exclusionReason=reason)
                exclusions.append({'id':row['id'],'reason':reason})
        if row['source'] != 'deterministic-repair':
            continue
        a, b = reports.get(row['beforeSha256']), reports.get(row['afterSha256'])
        reason = None
        if not a or not b:
            reason = 'Missing hash-bound observer pair'
        elif a[1]['observer_sha256'] != b[1]['observer_sha256']:
            reason = 'Observer protocol changed; not a labelled repair'
        else:
            before = {c['check']:c for c in a[0]['checks']}
            common = [c for c in b[0]['checks'] if c['check'] in before and c['level']=='block']
            old = sum(not before[c['check']]['passed'] for c in common)
            new = sum(not c['passed'] for c in common)
            label = (1 if new < old else -1) if new != old else None
            if row['preferred'] != label:
                reason = 'Staged requirement changed count or common checks tied; no valid preference label'
        if reason:
            row.update(excludedFromTraining=True,exclusionReason=reason)
            exclusions.append({'id':row['id'],'reason':reason})
    save(path, rows)
    save(STATE/'r11-label-audit.json', {'casesRetained':len(rows),'excluded':exclusions,
         'rule':'Only distinct captured pixels and changed common blocking checks measured with the same observer label a visual repair. Raw cases retained.'})
    personal_path = STATE/'personal-cases.json'
    personal = read(personal_path)
    for row in personal:
        if row['source']=='Paul-explicit-comment':
            row.update(excludedFromTraining=True,exclusionReason='Comment baseline was inferred, not bound to exact screenshots; retained as context')
    save(personal_path,personal)


def audit_laya():
    """Late audit is explicitly marked; it never rewrites an original run receipt."""
    receipts, visuals = [], []
    for arm in LIMITS:
        for task in NAMES:
            folder = PROOF/arm/task
            for p in sorted((folder/'evidence').glob('*/round-*/round.json')):
                row = read(p)
                live_path = p.parent/'laya-vision.json'
                live = read(live_path) if live_path.exists() else {}
                if len(live.get('variants',[]))==4:
                    visuals.append({'path':str(live_path.relative_to(ROOT)),'timing':'during-run','variants':live['variants']})
                else:
                    target = p.parent/'laya-variant-audit.json'
                    checks = read(p.parent/'page-checks.json')
                    binding = {'headSha256':sha(STATE/'corrective-head.json'), 'artifactSha256':row['sha256'],
                               'checksSha256':sha(p.parent/'page-checks.json'), 'anchorReportSha256':sha(row['anchorReportPath']),
                               'personalHeadSha256':sha(STATE/'personal-head.json') if (STATE/'personal-head.json').exists() else None}
                    item = read(target) if target.exists() else {}
                    if len(item.get('variants',[]))!=4 or any(item.get(k)!=v for k,v in binding.items()):
                        item = {**binding,'timing':'retrospective-audit',
                                'reason':'Earlier host scored desktop light only. Historical previous-variant identity was not recorded, so this late audit compares the bound reference.',
                                'variants':compare_variants(row['interaction'],read(row['anchorReportPath'])),
                                'triage':triage_taste(folder/'work',checks),
                                'verify':verify('taste_triage','ask_critic',checks,root=folder/'work')}
                        save(target,item)
                    visuals.append({'path':str(target.relative_to(ROOT)),**item})
            for p in sorted((folder/'evidence').glob('*/round-*/page-checks.json')):
                live = p.parent/'laya-vision.json'
                if live.exists():
                    result = read(live)
                    receipts.append({'path':str(live.relative_to(ROOT)),'timing':'during-run',
                                     'triage':result['triage'],'verify':result['verify']})
                else:
                    checks = read(p)
                    triage = triage_taste(folder/'work',checks)
                    confirmation = verify('taste_triage',triage.get('decision') or 'ask_critic',checks,root=folder/'work')
                    item = {'timing':'retrospective-audit','reason':'Original review stopped before vision receipt',
                            'checksSha256':sha(p),'triage':triage,'verify':confirmation}
                    save(p.parent/'laya-retrospective.json',item)
                    receipts.append({'path':str((p.parent/'laya-retrospective.json').relative_to(ROOT)),**item})
            for p in sorted(folder.glob('repair-*/laya-repair-route.json')):
                result = read(p)
                if 'liveVerify' not in result:
                    state = read(folder/'host-state.json')
                    observed = next(iter(state['rounds'].values()),[])
                    if not observed:
                        continue
                    checks = observed[min(int(p.parent.name.split('-')[-1])-1,len(observed)-1)]['pageChecks']
                    item = {'timing':'retrospective-audit','originalSha256':sha(p),
                            'triage':triage_taste(folder/'work',checks),
                            'verify':verify('taste_triage','repair_first',checks,root=folder/'work')}
                    save(p.parent/'laya-retrospective.json',item)
                else:
                    item = {'timing':'during-run','triage':result['liveTriage'],'verify':result['liveVerify']}
                receipts.append({'path':str(p.relative_to(ROOT)),**item})
    result = {'receipts':receipts,'duringRun':sum(r['timing']=='during-run' for r in receipts),
              'visualReceipts':visuals,'visualVariants':sum(len(r['variants']) for r in visuals),
              'retrospectiveVisualVariants':sum(len(r['variants']) for r in visuals if r['timing']=='retrospective-audit'),
              'pixelAnswers':sum(v[k].get('answer') is not None for r in visuals for v in r['variants'] for k in ('reference','personalReference','previous') if k in v),
              'retrospective':sum(r['timing']=='retrospective-audit' for r in receipts),
              'triageAnswers':sum(r['triage']['route']=='laya' for r in receipts),
              'escalations':sum(r['triage']['route']=='escalate' for r in receipts),
              'unavailable':sum(r['triage']['route']=='unavailable' for r in receipts),
              'actualSkippedModelCalls':0,'actualTimeSavedSec':0,
              'reason':'No paid inference was skipped by LAYA. Audit latency is overhead, not savings.'}
    save(PROOF/'laya-audit.json',result)
    return result


def seal_arm(arm, task):
    folder = PROOF/arm/task
    state = read(folder/'host-state.json')
    rows = next(iter(state['rounds'].values()),[])
    if not rows:
        raise ValueError(f'{arm}/{task}: no completed observed review to seal')
    accepted = read(folder/'accepted.json')
    row = rows[accepted['round']-1]
    if row['sha256'] != accepted['sha256']:
        raise ValueError('Accepted index/hash mismatch')
    source = Path(row['folder'])/'artifact.html'
    if sha(source) != accepted['sha256']:
        raise ValueError('Artifact hash mismatch')
    destination = folder/'sealed'
    destination.mkdir(exist_ok=True)
    shutil.copyfile(source,destination/(NAMES[task]+'.html'))
    report = row['interaction']
    shots = {}
    for theme in ('light','dark'):
        shot = next(s for s in report['screenshots'] if s['viewport']=='desktop' and s['theme']==theme)
        if sha(shot['path']) != shot['sha256'] or report['html_sha256'] != row['sha256']:
            raise ValueError('Screenshot/artifact hash mismatch')
        target = destination/(theme+'.png')
        shutil.copyfile(shot['path'],target)
        shots[theme] = {'path':str(target),'sha256':sha(target)}
    calls = measured_usage(folder)
    if any(not r['usageComplete'] or r['costUsd'] is None for r in calls):
        raise ValueError('Unknown usage blocks a cost claim')
    cost = sum(r['costUsd'] for r in calls)
    reviews = list((folder/'evidence'/NAMES[task]).glob('round-*/round.json'))
    failure = read(folder/'failure.json') if (folder/'failure.json').exists() else {}
    result = read(folder/'result.json') if (folder/'result.json').exists() else {}
    final = read(folder/'sol-final/verdict.json') if (folder/'sol-final/verdict.json').exists() else None
    value = {'arm':arm,'task':task,'artifactSha256':sha(source),'selectedRound':row['round'],
             'selectedObservation':row['folder'],'quality':row['critique']['quality'],
             'qualityBasis':'Arm model critic against Claude anchor; not a blind human vote',
             'qualityReviewScope':row.get('reviewScope','global'),
             'acceptedRounds':len(rows),'completedReviewsIncludingRejected':len(reviews),
             'renderAttempts':len(list((folder/'evidence'/NAMES[task]).glob('round-*/render/report.json'))),
             'repairCalls':sum(r.get('callKind')=='repair' for r in calls),
             'rollbackCount':len(list(folder.glob('rollback-*.json'))),
             'costUsd':cost,'limitUsd':LIMITS[arm][task],'budgetPassed':cost<=LIMITS[arm][task],
             'claudeDeclaredCostUsd':2.21 if task=='T1' else 5.55,
             'costRatioToClaude':(2.21 if task=='T1' else 5.55)/cost,
             'tokens':{k:sum(r['usage'].get(k,0) for r in calls) for k in ('input_tokens','cached_input_tokens','output_tokens','total_tokens')},
             'modelElapsedSec':sum(r['elapsedSec'] for r in calls),
             'renderElapsedSec':sum(read(p).get('duration_ms',0)/1000 for p in (folder/'evidence').rglob('report.json') if 'reusedFrom' not in read(p)),
             'renderCacheReuses':sum('reusedFrom' in read(p) for p in (folder/'evidence').rglob('report.json')),
             'blocks':[c['check'] for c in row['pageChecks']['checks'] if c['level']=='block' and not c['passed']],
             'interactionPassed':report['passed'],'fidelityPassed':row['fidelity']['passed'],
             'doneOk':bool(result.get('doneOk') and result.get('outputSha256')==sha(source)),
             'stopReason':failure.get('error') if (folder/'failure.json').exists() and (not (folder/'result.json').exists() or (folder/'failure.json').stat().st_mtime>(folder/'result.json').stat().st_mtime) else result.get('doneStatus'),
             'solFinalPass':final,'shots':shots,'callsByModel':{m:sum(r['model']==m for r in calls) for m in sorted({r['model'] for r in calls})}}
    value['solFinalPassMatchesSelected'] = bool(final and final['artifactSha256']==sha(source))
    value['fusionTarget30xPassed'] = value['costRatioToClaude']>=30 if arm=='arm-fusion' else None
    from grant_agent.taste_spelling import check as spellcheck
    checks = {**row['pageChecks'],'checks':[dict(c) for c in row['pageChecks']['checks']]}
    spelling = next(c for c in checks['checks'] if c['check']=='spelling')
    if len(report.get('variants',[]))!=4 or any(not v.get('corrective',{}).get('text') for v in report['variants']):raise ValueError('Four bound rendered text observations required for spelling audit')
    spelling.update(hits=spellcheck([r for v in report['variants'] for r in v.get('corrective',{}).get('text',[])]))
    spelling['passed'] = not spelling['hits']
    checks['blocks'] = sum(c['level']=='block' and not c['passed'] for c in checks['checks'])
    triage = triage_taste(folder/'work',checks)
    audit = {'timing':'retrospective-spelling-audit','artifactSha256':sha(source),
             'dictionaryRuleSha256':sha(ROOT/'src/grant_agent/taste_spelling.py'),
             'reason':'Recheck the bound rendered copy with current dictionaries; other original checks are retained.',
             'checks':checks,'triage':triage,
             'verify':verify('taste_triage',triage.get('decision') or 'ask_critic',checks,root=folder/'work')}
    if triage.get('route')=='unavailable' or audit['verify'].get('ms',0)<=0:
        raise RuntimeError('Selected artifact spelling audit requires live LAYA triage and verification')
    save(destination/'spelling-audit.json',audit)
    value['historicalBlocks'] = value['blocks']
    value['blocks'] = [c['check'] for c in checks['checks'] if c['level']=='block' and not c['passed']]
    value['selectedSpellingAudit'] = audit
    save(destination/'receipt.json',value)
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit',action='store_true')
    parser.add_argument('--seal',action='store_true')
    parser.add_argument('--archive',action='store_true',help='Archive raw round evidence after the arm jobs stop')
    parser.add_argument('--learn-votes',action='store_true',help='Import explicit proof/r11/paul-votes.json quality choices')
    parser.add_argument('--votes-path',type=Path,help='Quality votes beside another run\'s sealed blind packet')
    args=parser.parse_args()
    os.environ['NEYVIA_LAYA_URL']='http://127.0.0.1:48809'
    if args.learn_votes:
        print(json.dumps({'personalVotesImported':learn_votes(args.votes_path)}))
    if args.audit:
        audit_labels()
        for layer in ('corrective','personal'):
            train(layer)
        audit_laya()
    if args.seal:
        arms=[seal_arm(arm,task) for arm in LIMITS for task in NAMES]
        key_path=PROOF/'blind-shots-key.SPOILER.json'
        key=read(key_path) if key_path.exists() else {task:dict(zip(('A','B'),secrets.SystemRandom().sample(list(LIMITS),2))) for task in NAMES}
        for task in NAMES:
            for letter,arm in key[task].items():
                selected=next(r for r in arms if r['arm']==arm and r['task']==task)
                for theme in ('light','dark'):
                    path=PROOF/'blind'/NAMES[task]/theme/(letter+'.png')
                    path.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(selected['shots'][theme]['path'],path)
        save(key_path,key)
        index = ['# Blind comparison', '', 'Compare A and B for each task in both themes. Choose A, B or a tie, and give a brief reason.',
                 '', '| Task | Theme | A | B |', '|---|---|---|---|']
        for task,name in NAMES.items():
            for theme in ('light','dark'):
                index.append(f'| {"Landing" if task=="T1" else "Rare UI"} | {theme} | [A]({name}/{theme}/A.png) | [B]({name}/{theme}/B.png) |')
        (PROOF/'blind/README.md').write_text('\n'.join(index)+'\n',encoding='utf-8')
        layers={layer:{k:v for k,v in read(STATE/(layer+'-candidate.json')).items() if k!='weights'} for layer in ('corrective','personal')}
        for layer, value in layers.items():
            head_path = STATE/(layer+'-head.json')
            value['servedHead'] = {k:v for k,v in read(head_path).items() if k!='weights'} if head_path.exists() else None
        orchestration=read(PROOF/'orchestration-usage.json') if (PROOF/'orchestration-usage.json').exists() else None
        root_tokens=orchestration['usage']['total_tokens'] if orchestration and orchestration.get('usage') else None
        report={'schema':'neyvia.C13h.r11.v1','arms':arms,'learning':layers,
                'tokens':sum(r['tokens']['total_tokens'] for r in arms),'orchestrationTokens':root_tokens,
                'costBasis':'Measured arm usage at repository list-price equivalents; not an invoice. Orchestration dollar cost is not exposed.',
                'orchestrationUsageCheckpoint':orchestration,
                'jevbenchBefore':read(PROOF/'jevbench-before.json'),'jevbenchAfter':read(PROOF/'jevbench-after.json'),
                'heldoutPixelAudit':read(STATE/'corrective-heldout-pixel-audit.json') if (STATE/'corrective-heldout-pixel-audit.json').exists() else None,
                'laya':read(PROOF/'laya-audit.json'),
                'limitations':['Blind votes pending. Model critic score does not establish Paul preference.',
                  'Corrective held-out accuracy is on synthetic perturbations of Enrico screenshots. Human UICrit labels participate only in training.',
                  'The pixel audit removed identical-image contrast labels. Both heads were compared on the same remaining 48 held-out centering/overflow cases. New visible contrast overlays enter training/calibration only.',
                  'Personal layer has too few labels for a held-out estimate. Pixel answers abstain until calibrated.',
                  'The corrective gate is calibrated on mobile screenshot perturbations (80 independent calibration scenes); full website renders are outside that scope and abstain. Gate qualification probes are not run-time quality answers or savings.',
                  'Section critiques carry scores for unchanged regions; unfinished section reviews are not final global quality judgments.',
                  'All four selected artifacts remain incomplete with blocking checks. Fusion T1 used further Luna repairs after its paid Sol final pass, so that verdict is stale; fusion T2 final crops match its selected artifact.',
                  'Final visual inspection found saturated blue colouring and poor contrast in the pure Sol rare UI rendered by Obscura. Its section score does not approve the whole page; browser-equivalent appearance was not tested.',
                  'Centering checks measure declared centered containers; optical balance remains a rendered critic judgment.',
                  'Some early repair verification was retrospective; timings are marked, never rewritten.',
                  'Provider usage arrives after each turn. Admission reservation is not a provider hard dollar cap.',
                  'No measured model calls were skipped; actual LAYA time saved is zero.']}
        report['totalProviderTokensAtCheckpoint']=report['tokens']+root_tokens if root_tokens is not None else None
        save(PROOF/'report.json',report)
        lines=['# R11 fusion and pure Sol', '', '| Arm | Task | Critic /100 | Review scope | Cost USD | Reviews (accepted/all) | Blocks |',
               '|---|---|---:|---|---:|---:|---|']
        for r in arms:
            lines.append(f"| {r['arm']} | {r['task']} | {r['quality']} | {r['qualityReviewScope']} | {r['costUsd']:.5f} | {r['acceptedRounds']}/{r['completedReviewsIncludingRejected']} | {', '.join(r['blocks']) or 'none'} |")
        lines += ['', report['costBasis'], f"Measured arm tokens: {report['tokens']:,}. Orchestration tokens at checkpoint: {root_tokens:,}. Total: {report['totalProviderTokensAtCheckpoint']:,}." if root_tokens is not None else f"Measured arm tokens: {report['tokens']:,}. Orchestration usage is not exposed.",
                  'JevBench: 138/231 before; '+str(report['jevbenchAfter']['correct'])+'/231 after.',
                  'LAYA answers/time saved: '+str(report['laya']['triageAnswers'])+' triage / '+str(report['laya']['pixelAnswers'])+' pixel answers; zero skipped paid calls / zero seconds proven saved.',
                  '', 'The fusion 30-to-100-times-cheaper target is measured separately from the maximum dollar caps; current ratios are '+', '.join(f"{r['task']}: {r['costRatioToClaude']:.1f}x" for r in arms if r['arm']=='arm-fusion')+'.',
                  '', 'Learning layers:']
        for layer,r in layers.items():
            served = r['servedHead']
            accuracy='not estimable' if served is None else f"{served['heldoutAccuracy']:.1%}"
            lines.append(f"- {layer}: {r['cases']} labelled cases; candidate {r['trainCases']} train / {r['heldoutCases']} held out; served head trained on {served['trainCases'] if served else 0}; served-head accuracy {accuracy}; calibrated margin {served['calibratedMargin'] if served else None}.")
        lines += ['', 'Limitations:']+['- '+s for s in report['limitations']]
        (PROOF/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        print(json.dumps({'costUsd':sum(r['costUsd'] for r in arms),'tokens':report['tokens'],'arms':len(arms)}))
    if args.archive:
        archive_rounds()


if __name__=='__main__':main()
