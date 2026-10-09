"""Recover all Paul labels and frozen real page decisions without training heads."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys
from functools import lru_cache

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent.taste_fewshot import STATE, aspects, digest, lexical_embedding, save


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


@lru_cache(maxsize=4096)
def bound(path):
    path = Path(path)
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}


def last_image(run, arm, task):
    if run == 'r6':
        base=Path('C:/Users/user/Projects/nx-c5-noslop/proof/r6-blind')
        shots=list((base/'shots').glob('*'))
        name='landing' if task=='T1' else 'rare-ui'
        candidates=[p for p in shots if p.is_file() and p.name.startswith(('C' if arm=='arm-c' else 'L')+'-') and name in p.name]
        return str(candidates[0]) if candidates else None
    paths=list((REPO/'proof'/run/arm/task/'evidence').glob('*/round-*/round.json'))
    rows=[read(p) for p in paths]
    if not rows:
        path=REPO/'proof'/run/arm/task/'evidence/rounds.json'
        rows=next(iter(read(path).values()),[]) if path.exists() else []
    rows.sort(key=lambda row:row.get('round',0))
    return next((s['path'] for row in reversed(rows) for s in row.get('interaction',{}).get('screenshots',[])
                 if s['viewport']=='desktop' and s['theme']=='light' and Path(s['path']).exists()),None)


def personal():
    records, sources=[],[]
    def add(pair,kind,label,reason,group,files=(),images=(),source=None):
        record={'id':digest([pair,kind,label,reason])[:20],'pairId':pair,'labelKind':kind,'label':label,
                'reason':reason,'aspects':aspects(reason),'group':group,'files':list(files),
                'images':[bound(p) for p in images if p and Path(p).is_file()], 'source':source,
                'textEmbedding':lexical_embedding(reason+' '+str(files)),'embeddingKind':'lexical-hash-v1'}
        records.append(record)
    historical=read(REPO/'proof/preference-pairs.json')
    sources.append(bound(REPO/'proof/preference-pairs.json'))
    for pair in historical['pairs']:
        run=pair['run']; group='round1' if run.startswith('r4') else 'round2'
        reason=historical['identityReasons'].get('r4' if group=='round1' else 'r5','')
        files=[]
        text=[]
        for arm in ('C','L'):
            for name,row in pair['arms'][arm].get('files',{}).items():
                content=row.get('text') or ''
                files.append({'arm':arm,'name':name,'sha256':hashlib.sha256(content.encode()).hexdigest(),
                              'text':content[:1500],'originalPath':row.get('path')})
                text.append(content[:1000])
        add(pair['pairId'],'identity',pair.get('identityGuess','unknown'),reason,group,files=files,source={'run':run,'votedAt':pair.get('votedAt')})
        records[-1]['textEmbedding']=lexical_embedding(reason+' '.join(text))
        if pair.get('qualityPreference') in {'C','L','tie'}:
            add(pair['pairId'],'quality',pair['qualityPreference'],pair.get('reason') or reason,group,files=files)
    oldbase=Path('C:/Users/user/Projects/nx-c5-noslop/proof/r6-blind')
    oldkey=read(oldbase/'answer-key.SPOILER.json');sources.append(bound(oldbase/'answer-key.SPOILER.json'))
    oldvotes=read(REPO/'proof/preference-pairs-r6-votes.json');sources.append(bound(REPO/'proof/preference-pairs-r6-votes.json'))
    for task,item in oldkey['pairs'].items():
        imgs=[last_image('r6',arm,task) for arm in ('arm-c','arm-l')]
        files=[bound(p) | {'arm':arm} for arm in ('arm-c','arm-l') for p in (oldbase/arm).glob(item['file'])]
        vote=next((v for v in oldvotes['votes'] if v['pairId']==item['pairId']),None)
        add(item['pairId'],'identity','C' if vote and vote['pick']==item['claudeSide'] else 'unknown',
            'Round 3: Claude clearly better; Luna generic, partly broken; rare UI used common patterns.', 'round3',files,imgs,
            {'vote':vote,'spokenIdentity':True,'key':str(oldbase/'answer-key.SPOILER.json')})
        # Explicit spoken quality verdict recorded in the original source.
        add(item['pairId'],'quality','C',oldvotes['note'],'round3',files,imgs,str(REPO/'proof/preference-pairs-r6-votes.json'))
    for folder,run in [('round4','r7'),('round5','r10')]:
        keypath=REPO/'proof'/run/'answer-key.SPOILER.json';key=read(keypath);sources.append(bound(keypath))
        for category,kind,field in [('votes','identity','pick'),('better','quality','better')]:
            for path in sorted((REPO/'proof/votes-export'/folder/category).glob('*.json')):
                vote=read(path);sources.append(bound(path));pid=vote['pairId'];entry=key[pid]
                label='C' if vote[field]==entry['claude'] else 'L' if vote[field] in {'A','B'} else vote[field]
                task='T1' if 'Landing' in entry['title'] else 'T2'
                images=[last_image(run,arm,task) for arm in ('arm-l' if run=='r7' else 'arm-luna','arm-c')]
                # Claude's HTML lives in proof/r7/T1,T2 and proof/r10/arm-c may be absent;
                # keep source/text bindings rather than inventing a screenshot.
                files=[bound(p) for base in (REPO/'proof'/run/task,REPO/'proof'/run/'arm-l'/task,REPO/'proof'/run/'arm-luna'/task)
                       for p in base.glob('**/work/*.html')][:2]
                add(pid,kind,label,vote.get('reason') or f"Paul's explicit {kind} vote, {entry['title']}",folder,files,images,str(path))
    feedbackpath=REPO/'proof/votes-export/paul-feedback.json';feedback=read(feedbackpath);sources.append(bound(feedbackpath))
    keypath=REPO/'proof/r10/blind-shots-key.SPOILER.json';blindkey=read(keypath);sources.append(bound(keypath))
    for index,round_ in enumerate(feedback['rounds']):
        for number,reason in enumerate(round_['reasons']):
            group=f'feedback:{index+1}';pairs=[]
            if index==0:pairs=[r['pairId'] for r in records if r['group']=='round1']
            elif index==1:pairs=[r['pairId'] for r in records if r['group']=='round2']
            elif index==2:pairs=[v['pairId'] for v in oldkey['pairs'].values()]
            elif index==3:pairs=['qeca2519f','q1672b4c0']
            elif index==4:pairs=['qf363578a']
            elif index==5:pairs=['landing-blind-r10','rare-ui-blind-r10']
            else:pairs=['neyvia-app-light-v-dark']
            # Every reason survives once, linked to all relevant pairs. Its label
            # describes the aspect, not a fabricated per-artifact quality vote.
            add(f'reason-{index+1}-{number+1}','aspect',{'prefer':'presence of '+','.join(aspects(reason)),'text':reason},reason,group,
                source={'feedback':str(feedbackpath),'round':round_['round'],'relatedPairIds':sorted(set(pairs))})
    for task in ('T1','T2'):
        name='landing' if task=='T1' else 'rare-ui'
        images=[last_image('r10',arm,task) for arm in ('arm-sol','arm-luna')]
        add(name+'-blind-r10','identity',{'A':blindkey[name+'-A'],'B':blindkey[name+'-B'],'correct':True},
            'Paul identified all four blind screenshots correctly.','r10-blind',images=images,source=str(keypath))
        if task=='T1':
            add(name+'-blind-r10','quality','second',"Luna cleaned-up landing better than Sol's purple landing: misplaced button text, uncentred drawing, spelling mistakes.",
                'r10-blind',images=images,source=str(feedbackpath))
        else:
            add(name+'-blind-r10','aspect',{'sol':'interesting but overflow','luna':'unpolished regression'},
                'Sol rare UI interesting, text out of buttons; Luna rare UI unpolished and regressed. No explicit Sol versus Luna quality vote.','r10-blind',images=images,source=str(feedbackpath))
    from grant_agent import taste_vision as vision
    for row in records:
        if row['labelKind']=='aspect' and isinstance(row.get('source'),dict):
            related=row['source'].get('relatedPairIds',[])
            images={i['sha256']:i for candidate in records if candidate['pairId'] in related for i in candidate['images']}
            row['images']=list(images.values())[:4]
    original=vision.STATE
    try:
        vision.STATE=STATE/'vision-cache'
        for row in records:
            row['imageEmbeddings']=[vision.embedding(i['path']).tolist() for i in row['images']]
    finally:vision.STATE=original
    inventory=[]
    for base in [Path('C:/Users/user/Projects/nx-r4-blind/proof/r4-blind-20261004'),
                 Path('C:/Users/user/Projects/nx-c5-noslop/proof/r5-blind'),oldbase]:
        inventory.append({'path':str(base),'present':base.exists(),'answerKey':bound(base/'answer-key.SPOILER.json') if (base/'answer-key.SPOILER.json').exists() else None,
                          'readOnly':True})
    document={'schema':'neyvia.taste-fewshot-labels.v1','records':records,'sources':sources,'earlierRounds':inventory,
              'counts':{kind:sum(r['labelKind']==kind for r in records) for kind in ['identity','quality','aspect']},
              'reasonCount':sum(len(r['reasons']) for r in feedback['rounds']),'headTrained':False,
              'limitations':['Identity votes never become quality labels. Aspect constraints are conditioning, not independent votes.',
                             'Text-only embedding is lexical hashing. No personal held-out accuracy is estimable from these labels.']}
    save(STATE/'personal.json',document);return document


def checks(row):
    return {c['check']:c for c in row.get('pageChecks',{}).get('checks',[]) if c.get('level')=='block'}


def repair_facts(before,after):
    a,b=checks(before),checks(after);common=set(a)&set(b)
    regressed=sorted(k for k in common if a[k]['passed'] and not b[k]['passed'])
    improved=sorted(k for k in common if not a[k]['passed'] and b[k]['passed'])
    shots=lambda row:{s.get('variant',s['viewport']+'-'+s['theme']):s['sha256'] for s in row['interaction']['screenshots']}
    old,new=shots(before),shots(after)
    controls=lambda r:sum(v.get('exercised',0) if isinstance(v.get('exercised',0),int) else len(v.get('exercised',[])) for v in r['interaction'].get('variants',[]))
    return {'improvedChecks':improved,'newBlockingChecks':regressed,'remainingChecks':sorted(k for k in b if not b[k]['passed']),
            'hasRecordedChecks':bool(common),
            'introducedChecks':sorted(set(b)-set(a)),'samePixels':old==new,
            'lostControls':max(0,controls(before)-controls(after)),
            'motionBefore':before['interaction'].get('motion',{}).get('meaningful'),
            'motionAfter':after['interaction'].get('motion',{}).get('meaningful'),
            'changedRegions':after.get('change',{}),'beforeDefects':before.get('critique',{}).get('defects',[])[:4]}


def corpus():
    cases,excluded=[],[]
    groups={}
    for run in ('r7','r8','r9','r10','r11'):
        candidates=[]
        for path in (REPO/'proof'/run).glob('*/T*/evidence/rounds.json'):
            for rows in read(path).values():
                candidates.extend((path,row) for row in rows)
        for path in (REPO/'proof'/run).glob('*/T*/evidence/*/round-*/round.json'):
            try:candidates.append((path,read(path)))
            except (OSError,ValueError):continue
        for path,row in candidates:
            if row.get('interaction',{}).get('engine')!='obscura':continue
            group='/'.join(path.relative_to(REPO/'proof').parts[:3])
            groups.setdefault(group,[]).append((path,row))
    def add(kind,facts,expected,group,path,images,reason,label_kind):
        index=int(hashlib.sha256(group.encode()).hexdigest()[:8],16)%4
        split='heldout' if group.startswith('r11/') else 'calibration' if index==0 else 'train'
        cases.append({'id':digest([kind,group,str(path),facts])[:20], 'pairId':digest([group,str(path)])[:16],
            'kind':kind,'facts':facts,'expected':bool(expected),'label':bool(expected),'labelKind':label_kind,
            'reason':reason,'aspects':aspects(reason),'group':group,'split':split,'source':bound(path),
            'images':[{k:s[k] for k in ['path','sha256','variant','viewport','theme','observation','crop'] if k in s} for s in images]})
    for group,rows in sorted(groups.items()):
        rows.sort(key=lambda item:(item[1]['round'],item[0].stat().st_mtime_ns))
        unique=[];seen=set()
        for path,row in rows:
            key=(row['sha256'],digest(row.get('pageChecks',{})))
            if key in seen:continue
            seen.add(key);unique.append((path,row))
        for (oldpath,before),(path,after) in zip(unique,unique[1:]):
            facts=repair_facts(before,after)
            if isinstance(facts['changedRegions'],dict):facts['changedRegions']={k:v for k,v in facts['changedRegions'].items() if k in ['selector','selectors','kind','scope','rowIds','ratio']}
            else:facts['changedRegions']=str(facts['changedRegions'])[:300]
            bq=before['critique']['quality'];aq=after['critique']['quality']
            expected=aq>=bq and not facts['newBlockingChecks'] and not facts['lostControls']
            images=[s for r in (before,after) for s in r['interaction']['screenshots'] if s['viewport']=='desktop' and s['theme']=='light']
            if len(images)!=2 or not all(Path(s['path']).exists() for s in images):continue
            critic_expected=expected
            # The compiled gate answers the bounded retention question. It
            # never claims to predict subjective quality from check flags.
            safe=not facts['newBlockingChecks'] and not facts['lostControls'] and not (facts['motionBefore'] and not facts['motionAfter'])
            add('repair',facts,safe,group,path,images,
                f'Measured retention {safe}; independent critic quality {bq} -> {aq}; common-check regressions {facts["newBlockingChecks"]}; controls lost {facts["lostControls"]}.',
                'measured-retention-with-independent-critic')
            cases[-1]['criticExpected']=critic_expected
            cases[-1]['criticScores']={'before':bq,'after':aq}
            cases[-1]['supported']=facts['hasRecordedChecks']
        for path,row in unique:
            imgs=row['interaction']['screenshots']
            for check in row.get('pageChecks',{}).get('checks',[]):
                if check.get('check') not in {'text-box-fit','figure-centering','diagram-geometry','spelling','motion-sequence'}:continue
                # Both observed passes and failures; no synthetic perturbations.
                facts={'check':check['check'],'passed':check['passed'],'hits':check.get('hits',[])[:3],
                       'engineFrontier':any('frontier' in str(h).lower() or 'unmeasur' in str(h).lower() for h in check.get('hits',[]))}
                expected=not check['passed'] and not facts['engineFrontier']
                add('failure',facts,expected,group,path,imgs[:1],f'Real rendered {check["check"]}: {"failed" if expected else "no repairable failure"}.','recorded-check-outcome')
            manifest=[m for m in row.get('imageManifest',[]) if m.get('side')=='Candidate']
            if not manifest:continue
            issue=row['critique'].get('difference','')+' '+str(row['critique'].get('defects',[]))
            target=manifest[0]
            alternative=next((s for s in imgs if s['viewport']=='desktop' and s['theme']=='light'),None)
            if not alternative:continue
            # Actual critic-selected region against its real full-page overview.
            # Only local/section reviews provide a defensible relevance label.
            if row.get('reviewScope') not in {'section','sections'} or not target.get('crop'):continue
            swap=int(hashlib.sha256(str(path).encode()).hexdigest()[:2],16)%2
            options=[{'description':target.get('observation'),'region':target.get('crop')},
                     {'description':'Whole desktop-light overview','region':None}]
            if swap:options.reverse()
            add('crop',{'issue':issue[:500],'first':options[0],'second':options[1]},not swap,group,path,
                [target,alternative], 'Actual critic selected localized region for a section review.','critic-region-choice')
    # A screenshot shared across splits cannot qualify as held-out. Entire
    # groups are removed from training/calibration when any image overlaps.
    heldhash={s['sha256'] for c in cases if c['split']=='heldout' for s in c['images'] if 'sha256' in s}
    leaking={c['group'] for c in cases if c['split']!='heldout' and any(s.get('sha256') in heldhash for s in c['images'])}
    for c in cases:
        if c['group'] in leaking:excluded.append(c)
    cases=[c for c in cases if c['group'] not in leaking]
    cases=list({c['id']:c for c in cases}.values())
    result={'schema':'neyvia.taste-real-decisions.v1','cases':cases,'excludedGroups':sorted(leaking),
            'splitPolicy':'R11 held out in full; earlier run/arm/task groups hashed into train or calibration; cross-split exact-image overlap excluded.',
            'sources':{'r6':'Paul page pairs in personal layer; no sequential Obscura check receipts available', 'r7-r11':len(groups)},
            'limitations':['Critic labels are model decisions, not Paul preference. Consecutive attempts may correlate within a page group.',
                           'Historical section scores do not establish whole-page quality; gate labels are repair decisions only.',
                           'Crop labels reconstruct actual critic region selection, not an independent human localization benchmark.'],
            'counts':{split:{kind:sum(c['split']==split and c['kind']==kind for c in cases) for kind in ['repair','failure','crop']} for split in ['train','calibration','heldout']}}
    save(STATE/'real-pairs.json',result);return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--personal',action='store_true');parser.add_argument('--real',action='store_true');args=parser.parse_args()
    if args.personal:print(json.dumps({'personal':personal()['counts']}),flush=True)
    if args.real:print(json.dumps({'real':corpus()['counts']}),flush=True)


if __name__=='__main__':main()
