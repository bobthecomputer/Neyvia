"""Head-free, provenance-bound taste conditioning and selective calibration.

The frozen CLIP encoder retrieves page examples. Text-only records use a
deterministic lexical embedding. Neither embedding is a learned taste head.
LAYA probabilities are diagnostics until validated on independent real pages.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import re
import time
import urllib.request

REPO = Path(__file__).resolve().parents[2]
STATE = REPO / 'proof/r12/learning'
ASPECTS = {
    'motion': r'animat|motion|fluid|sequence|demo|transition',
    'voice': r'copy|writ|word|filler|dash|slogan|sell|saas|naming|noise',
    'overflow': r'overflow|clipp|out of|outside|fit|button|pill',
    'centring': r'centr|center|align|balance',
    'spelling': r'spell|typo|misspell',
    'geometry': r'diagram|shape|geometry|misalign|drawing|illustrat',
    'polish': r'polish|finish|taste|generic|broken|regress|theme|structure|report',
}


def aspects(text):
    return [key for key, pattern in ASPECTS.items() if re.search(pattern, text, re.I)] or ['polish']


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    compact = path.name in {'personal.json','real-pairs.json'}
    path.write_text(json.dumps(value, indent=None if compact else 2, ensure_ascii=False,
                               separators=(',',':') if compact else None) + '\n', encoding='utf-8')


def lexical_embedding(text, dimension=512):
    """Stable normalized lexical embedding; no fitting, vocabulary or downloads."""
    words = re.findall(r'[\w]+', text.lower())
    terms = words + [' '.join(words[i:i+2]) for i in range(len(words)-1)]
    terms += [word[i:i+4] for word in words for i in range(max(0, len(word)-3))]
    vector = [0.0] * dimension
    for term in terms:
        hashed = hashlib.sha256(term.encode()).digest()
        index = int.from_bytes(hashed[:4], 'little') % dimension
        vector[index] += 1 if hashed[4] & 1 else -1
    length = math.sqrt(sum(v*v for v in vector)) or 1
    return [v/length for v in vector]


def similarity(a, b):
    return sum(x*y for x, y in zip(a, b))


def nearest(records, query, *, images=(), count=4, exclude_groups=()):
    text_vector = lexical_embedding(query)
    image_vectors = []
    if images:
        from . import taste_vision as vision
        # Do not mutate R11's admitted learning state when computing new caches.
        old_state = vision.STATE
        try:
            vision.STATE = STATE / 'vision-cache'
            image_vectors = [vision.embedding(path) for path in images if Path(path).is_file()]
        finally:
            vision.STATE = old_state
    ranked = []
    for row in records:
        if row.get('group') in exclude_groups:
            continue
        score = similarity(text_vector, row.get('textEmbedding') or lexical_embedding(row['reason']))
        vectors = row.get('imageEmbeddings', [])
        if image_vectors and vectors:
            score = .4*score + .6*max(similarity(a,b) for a in image_vectors for b in vectors)
        ranked.append((score, row))
    ranked.sort(key=lambda item: (-item[0], item[1]['id']))
    # Reasons are individual labels, but repeated reasons from one vote do not
    # become multiple independent votes in confidence estimates.
    selected, groups = [], set()
    for score, row in ranked:
        vote = row.get('pairId', row['id'])
        if vote in groups:
            continue
        groups.add(vote)
        selected.append({k: row[k] for k in ('id','pairId','labelKind','label','reason','aspects') if k in row} | {'similarity':round(float(score),5)})
        if len(selected) >= count:
            break
    return selected


QUESTIONS = {
    'repair': ('Is the proposed repair better enough to KEEP? Compare observed checks, motion, content and retrieved reasons. '
               'Return true to keep an improvement or a harmless targeted fix with preserved behavior. Return false for a regression, '
               'lost content, worse geometry or worse motion. Ignore author identity and do not assume an attractive rewrite is better.'),
    'failure': ('Is the reported check failure REAL and repairable in this page? Return true for measured overflow, spelling, '
                'miscentring, geometry or broken motion. Return false for a declared engine frontier, unsupported observation, '
                'decorative overlap without semantic nodes, or a label that actually fits its measured box. Preserve blockers until verified.'),
    'crop': ('Choose the image the critic should inspect for the stated issue. Return true if the FIRST crop covers the issue and '
             'shows it more clearly; return false if the SECOND crop is more relevant. Prefer the measured defect region over '
             'an unrelated overview. For motion prefer the ordered motion frames. Do not choose a crop based on which page looks better.'),
}


def predict(kind, facts, examples, *, url='http://127.0.0.1:48809', timeout=45):
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    if parsed.hostname not in {'127.0.0.1','localhost'} or parsed.port not in range(48801,48810):
        raise ValueError('Explicit C13 loopback port required')
    request = {'questions': {'decision': {'type':'noul','instructions':QUESTIONS[kind], 'thresholds':{'answer':0}}},
               'state': {'observations':facts, 'labelled_examples':examples},
               'scope': {'task':'C13i','kind':kind,'factsSha256':digest(facts)},
               'memory':False, 'base_cache':False}
    started = time.perf_counter()
    wire = urllib.request.Request(url+'/v1/systemone', data=json.dumps(request).encode(), headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(wire, timeout=timeout) as response:
        result = json.load(response)
    answer = result['answers']['decision']
    if answer['answer'] not in {'true','false'}:
        raise ValueError('Unknown typed decision')
    return {'answer':answer['answer']=='true', 'confidence':answer['top_probability'],
            'latencyMs':(time.perf_counter()-started)*1000, 'decisionId':result['decision_id'],
            'identity':result['identity'], 'usage':result.get('usage'),
            'factsSha256':digest(facts),'examplesSha256':digest(examples),
            'distribution':answer.get('p'), 'available':True}


def routine_embedding(kind, facts):
    """A fixed observation projection, not a fitted corrective classifier.

    No critic score, expected label, author or page ID enters this embedding.
    It represents the high-frequency decision, rather than the whole page.
    """
    if kind=='repair':
        values=[bool(facts.get('newBlockingChecks')),bool(facts.get('lostControls')),
                bool(facts.get('motionBefore')) and not bool(facts.get('motionAfter'))]
        # A regression and a lost control outweigh incidental text similarity.
        weights=[4,4,3]
        return [w if value else -w for value,w in zip(values,weights)]
    if kind=='failure':
        # The returned check flag is an observation; engine frontiers retain
        # abstention/verification authority and cannot clear blocking checks.
        values=[bool(facts.get('passed')),bool(facts.get('engineFrontier')),bool(facts.get('hits'))]
        return [3 if value else -3 for value in values]
    first=str(facts.get('first',{}).get('description','')).lower()
    second=str(facts.get('second',{}).get('description','')).lower()
    return [3 if 'overview' in first or 'whole' in first else -3,
            3 if 'overview' in second or 'whole' in second else -3,
            1 if facts.get('first',{}).get('region') else -1,
            1 if facts.get('second',{}).get('region') else -1]


def episodic_prediction(kind,facts,records):
    """Nearest labelled decision episodes; never train on a held-out label.

    Support is label agreement, not a model softmax probability. Calibration
    supplies the empirical accuracy and abstention policy separately.
    """
    query=routine_embedding(kind,facts)
    lexical=lexical_embedding(json.dumps(facts))
    distances=[]
    for row in records:
        if kind=='repair' and not row.get('supported',row['facts'].get('hasRecordedChecks',False)):
            continue
        observed=routine_embedding(kind,row['facts'])
        distance=sum((a-b)**2 for a,b in zip(query,observed))
        lex=similarity(lexical,lexical_embedding(json.dumps(row['facts'])))
        distances.append((distance,-lex,row))
    distances.sort(key=lambda item:(item[0],item[1],item[2]['id']))
    selected=[item for item in distances if item[0]==distances[0][0]][:8] if distances else []
    yes=sum(row['expected'] for _,_,row in selected)
    total=len(selected)
    answer=yes>=total-yes
    support=max(yes,total-yes)/total if total else 0
    # Unseen observation signatures abstain; approximate lexical retrieval
    # remains advisory and cannot silently become a verified routine.
    exact=bool(selected and selected[0][0]==0 and (kind!='repair' or facts.get('hasRecordedChecks')))
    return {'answer':answer,'confidence':support if exact and total>=3 else 0,
            'source':'head-free episodic LAYA taste wrapper','supportCases':total,
            'supportGroups':sorted({row['group'] for _,_,row in selected}),
            'exactObservationSignature':exact,
            'nearestEpisodes':[{'id':row['id'],'label':row['expected'],'reason':row['reason'],
                'distance':distance,'textSimilarity':-lex} for distance,lex,row in selected],
            'embedding':query,'confidenceKind':'retrieved-label agreement; empirical gate calibrated separately'}


def wilson(correct, total, z=1.96):
    if not total:
        return 0
    p = correct/total
    return (p+z*z/(2*total)-z*math.sqrt(p*(1-p)/total+z*z/(4*total*total)))/(1+z*z/total)


def calibrate(rows, *, min_cases=12, accuracy=.9, lower=.7):
    """Select max coverage on calibration only; held-out labels never tune it."""
    qualified = []
    for threshold in sorted({r['prediction']['confidence'] for r in rows if r['prediction']['confidence']>0}):
        selected = [r for r in rows if r['prediction']['confidence'] >= threshold]
        correct = sum(r['prediction']['answer']==r['expected'] for r in selected)
        if len(selected)>=min_cases and correct/len(selected)>=accuracy and wilson(correct,len(selected))>=lower:
            qualified.append({'threshold':threshold,'cases':len(selected),'correct':correct,
                              'accuracy':correct/len(selected),'wilsonLower95':wilson(correct,len(selected))})
    return max(qualified,key=lambda r:r['cases']) if qualified else {'threshold':None,'cases':0,'reason':'No empirical gate qualified'}


def gate(kind, facts, *, images=(), group=None, url='http://127.0.0.1:48809', output=None):
    personal = json.loads((STATE/'personal.json').read_bytes())['records']
    corrective = json.loads((STATE/'real-pairs.json').read_bytes())['cases']
    labelled = [r for r in corrective if r['split']=='train' and r['kind']==kind]
    query = json.dumps(facts,ensure_ascii=False)
    context = nearest(personal,query,images=images,count=3,exclude_groups=[group])
    demonstrations = nearest(labelled,query,count=3,exclude_groups=[group])
    base = predict(kind,facts,context+demonstrations,url=url)
    result = base | episodic_prediction(kind,facts,labelled)
    result['baseModelAnswer']=base['answer'];result['baseModelConfidence']=base['confidence']
    policy = json.loads((STATE/'calibration.json').read_bytes())['gates'][kind]
    threshold = policy.get('threshold')
    admission=json.loads((STATE/'heldout-report.json').read_bytes())['admitted'][kind]
    compatible = facts.get('sameDriverRevision',True)
    crop_supported = kind!='crop' or facts.get('hasKnownIssue',True)
    answered = crop_supported and compatible and admission and threshold is not None and result['confidence']>0 and result['confidence']>=threshold
    # Observable regression is always blocking even if a local model disagrees.
    safety_veto = kind=='repair' and result['answer'] and bool(facts.get('newBlockingChecks') or facts.get('lostControls'))
    result |= {'kind':kind,'route':'laya' if answered and not safety_veto else 'escalate',
               'threshold':threshold,'calibrationAccuracy':policy.get('accuracy'),
               'confidenceLowerBound':policy.get('wilsonLower95'),'examples':context+demonstrations,
               'safetyVeto':safety_veto,'sameDriverRevision':compatible,'cropSupported':crop_supported,'personalLayer':'few-shot, no fitted head',
               'personalAccuracy':None,'savedTokensActual':0,'savedSecondsActual':0}
    if output:
        target=Path(output)
        if target.exists():
            ordinal=1
            while (target.parent/('prior-decision-'+target.stem+'-'+str(ordinal)+'.json')).exists():ordinal+=1
            (target.parent/('prior-decision-'+target.stem+'-'+str(ordinal)+'.json')).write_bytes(target.read_bytes())
        save(target,result)
    return result
